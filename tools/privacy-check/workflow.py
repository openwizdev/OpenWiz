import json
import re


class Unknown(ValueError):
    pass


def split_flow(text):
    result, start, depth, quote = [], 0, 0, None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\' and quote == '"':
                i += 2
                continue
            if c == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        elif c in "\"'":
            quote = c
        elif c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
        elif c == ',' and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
        i += 1
    if quote or depth:
        raise Unknown('unclosed flow list')
    result.append(text[start:].strip())
    return result


def uncomment(text):
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\' and quote == '"':
                i += 2
                continue
            if c == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        elif c in "\"'" and (i == 0 or text[i - 1] in ' [:,'):
            quote = c
        elif c == '#' and (i == 0 or text[i - 1].isspace()):
            return text[:i].rstrip()
        i += 1
    return text.rstrip()


def scalar(text):
    text = text.strip()
    if not text:
        return None
    if text.startswith('[') and text.endswith(']'):
        inner = text[1:-1].strip()
        return [] if not inner else [scalar(x) for x in split_flow(inner)]
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise Unknown('unsupported quoted scalar') from exc
        if not isinstance(value, str):
            raise Unknown('expected quoted string')
        return value
    if text.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", text):
            raise Unknown('unsupported quoted scalar')
        return text[1:-1].replace("''", "'")
    if text.startswith(('&', '*', '!', '{', ']', '}', '%', '?', '|', '>')) or ': ' in text or '\t' in text:
        raise Unknown('unsupported YAML syntax')
    return text


def parse(source):
    rows = []
    block = None
    for n, line in enumerate(source.splitlines(), 1):
        if '\t' in line[:len(line) - len(line.lstrip())]:
            raise Unknown('tab indentation')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        if block is not None and indent > block:
            continue
        block = None
        text = uncomment(line[indent:])
        if not text:
            continue
        if text == '---' and not rows:
            continue
        if re.search(r':\s*[|>][+-]?[1-9]?$', text):
            text = re.sub(r'[|>][+-]?[1-9]?$', 'OPAQUE_BLOCK', text)
            block = indent + (2 if text.startswith('- ') else 0)
        rows.append((indent, text, n))

    def pair(text):
        match = re.fullmatch(r'([^:]+):(?:\s+(.*)|)', text)
        if not match:
            raise Unknown('expected mapping')
        key = scalar(match[1])
        if not isinstance(key, str) or key == '<<':
            raise Unknown('unsupported mapping key')
        return key, match[2] or ''

    def node(pos, indent):
        sequence = rows[pos][1] == '-' or rows[pos][1].startswith('- ')
        result = [] if sequence else {}
        while pos < len(rows) and rows[pos][0] == indent:
            _, text, _ = rows[pos]
            pos += 1
            if sequence:
                if text != '-' and not text.startswith('- '):
                    raise Unknown('mixed sequence and mapping')
                text = text[1:].strip()
                if not text:
                    if pos == len(rows) or rows[pos][0] <= indent:
                        result.append(None)
                    else:
                        value, pos = node(pos, rows[pos][0])
                        result.append(value)
                elif re.match(r'[^:]+:(?:\s|$)', text):
                    key, rest = pair(text)
                    item = {key: scalar(rest)}
                    if pos < len(rows) and rows[pos][0] > indent:
                        more, pos = node(pos, rows[pos][0])
                        if not isinstance(more, dict) or key in more:
                            raise Unknown('ambiguous sequence mapping')
                        item.update(more)
                    result.append(item)
                else:
                    result.append(scalar(text))
            else:
                key, rest = pair(text)
                if key in result:
                    raise Unknown('duplicate mapping key')
                if rest:
                    result[key] = scalar(rest)
                elif pos < len(rows) and (rows[pos][0] > indent or
                        (rows[pos][0] == indent and rows[pos][1].startswith('- '))):
                    result[key], pos = node(pos, rows[pos][0])
                else:
                    result[key] = None
        if pos < len(rows) and rows[pos][0] > indent:
            raise Unknown('unexpected indentation')
        return result, pos

    if not rows:
        raise Unknown('empty workflow')
    value, end = node(0, rows[0][0])
    if end != len(rows) or not isinstance(value, dict):
        raise Unknown('expected one workflow mapping')
    return value


HOSTED = {'ubuntu-latest', 'ubuntu-24.04', 'ubuntu-24.04-arm', 'ubuntu-slim', 'macos-15', 'macos-15-intel'}


def allowed_runner(value, job):
    if isinstance(value, list):
        return len(value) == 1 and isinstance(value[0], str) and value[0] in HOSTED
    if not isinstance(value, str):
        return False
    if value in HOSTED:
        return True
    fallback = re.fullmatch(r"\$\{\{\s*vars\.(CI_RUNS_ON|CI_RUST_RUNS_ON)\s*\|\|\s*'([^']+)'\s*\}\}", value)
    if fallback:
        return fallback[2] in HOSTED
    private_route = re.fullmatch(
        r"\$\{\{\s*github\.event_name == 'pull_request' && "
        r"github\.event\.pull_request\.head\.repo\.full_name != github\.repository "
        r"&& 'ubuntu-24.04' \|\| github\.repository == 'jparker2006/ClosedWiz' && \("
        r"vars\.CI_(?:RUST_RUNS_ON|WEB_RUNS_ON|SMALL_RUNS_ON \|\| vars\.CI_WEB_RUNS_ON)"
        r" \|\| 'namespace-profile-closedwiz-rust'\) \|\| 'ubuntu-24.04'\s*\}\}", value)
    if private_route:
        return True
    match = re.fullmatch(r'\$\{\{\s*matrix\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}', value)
    if not match:
        return False
    strategy = job.get('strategy', {})
    matrix = strategy.get('matrix') if isinstance(strategy, dict) else None
    if not isinstance(matrix, dict):
        return False
    key = match[1]
    values = matrix.get(key, [])
    if not isinstance(values, list):
        return False
    values = list(values)
    include = matrix.get('include', [])
    if not isinstance(include, list):
        return False
    for row in include:
        if not isinstance(row, dict):
            return False
        if key in row:
            values.append(row[key])
        elif not matrix.get(key):
            return False
    return bool(values) and all(isinstance(x, str) and x in HOSTED for x in values)


def refused_jobs(source):
    workflow = parse(source)
    jobs = workflow.get('jobs')
    if not isinstance(jobs, dict) or not jobs:
        raise Unknown('missing jobs mapping')
    bad = []
    for name, job in jobs.items():
        if not isinstance(job, dict):
            bad.append(name)
        elif 'uses' in job:
            target = job['uses']
            if 'runs-on' in job or not isinstance(target, str) or not re.fullmatch(r'\./\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml', target):
                bad.append(name)
        elif not allowed_runner(job.get('runs-on'), job):
            bad.append(name)
    return bad
