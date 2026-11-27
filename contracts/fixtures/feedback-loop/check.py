#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
CONTRACT = 'contracts/feedback-loop.v1.md'
FIXTURES = 'contracts/fixtures/feedback-loop'
ISSUE_KEYS = {'number', 'author', 'pull_request', 'title', 'body', 'labels', 'milestone', 'comments'}
COVERAGE = ('report', 'not a report', 'facts', 'facts refused', 'report link', 'forged link', 'to a fleet', 'held',
            'landed', 'second merge', 'closes no report')


def strict(text):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError('a repeated key')
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def contract(root):
    text = (root / CONTRACT).read_text(encoding='utf-8')
    blocks = re.findall(r'^```feedback-loop-v1\n(.*?)^```$', text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('expected one feedback-loop-v1 block')
    return strict(blocks[0])


def shape(obj, keys, what):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(f'{what} must have exactly the keys {sorted(keys)}')
    return obj


def issue(obj):
    shape(obj, ISSUE_KEYS, 'an issue')
    if not isinstance(obj['number'], int) or isinstance(obj['number'], bool) or obj['number'] < 1:
        raise ValueError('an issue number must be a positive integer')
    if not isinstance(obj['pull_request'], bool) or not isinstance(obj['body'], str) \
            or not isinstance(obj['author'], str):
        raise ValueError('an issue needs a boolean pull_request, a string body and an author')
    if not isinstance(obj['labels'], list) or not all(isinstance(x, str) for x in obj['labels']):
        raise ValueError('labels must be a list of strings')
    if obj['milestone'] is not None and not isinstance(obj['milestone'], str):
        raise ValueError('a milestone is a string or null')
    for c in obj['comments']:
        shape(c, {'author', 'body'}, 'a comment')
    return obj


def is_report(obj, c):
    if obj['pull_request']:
        return False
    if c['label'] in obj['labels']:
        return True
    lines = obj['body'].split('\n')
    markers = [x for x in lines if re.fullmatch(c['marker'], x)]
    return len(lines) >= 3 and lines[-2] == '' and markers == [lines[-1]]


PRIVATE_FACT_VALUE = re.compile(
    r'^(?:gh[pousr]_|github_pat_|sk-|akia|xox[a-z]-|[sr]k_(?:live|test)_|glpat-|npm_|hf_'
    r'|thr_|sess_|acct_'
    r'|(?:[0-9]{1,3}\.){3}[0-9]{1,3}$)',
    re.ASCII,
)


def parse_facts(obj, c):
    if not is_report(obj, c):
        return None
    lines = obj['body'].split('\n')
    markers = [x for x in lines if re.fullmatch(c['marker'], x)]
    if len(lines) < 5 or lines[-2] != '' or lines[-4] != '' or markers != [lines[-1]]:
        return None
    f = c['facts']
    prefix = f['prefix']
    candidates = [x for x in lines if x.startswith(prefix)]
    if candidates != [lines[-3]]:
        return None
    line = lines[-3]
    if len(line) > f['max_length'] or not all(32 <= ord(ch) <= 126 for ch in line):
        return None
    raw = line[len(prefix):]
    try:
        parsed = strict(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    order = f['order']
    keys = list(parsed.keys())
    if any(k not in f['values'] for k in keys):
        return None
    if any(k not in parsed for k in f['required']):
        return None
    if [k for k in order if k in parsed] != keys:
        return None
    for k, v in parsed.items():
        spec = f['values'][k]
        if spec['type'] == 'integer':
            if type(v) is not int or v < spec['min'] or v > spec['max']:
                return None
        elif spec['type'] == 'string':
            if type(v) is not str or not re.fullmatch(spec['pattern'], v, re.ASCII):
                return None
            if PRIVATE_FACT_VALUE.match(v):
                return None
        else:
            return None
    if json.dumps(parsed, separators=(',', ':'), ensure_ascii=True) != raw:
        return None
    body_lines = lines[:-4]
    log_indices = [i for i, x in enumerate(body_lines) if x == f['log_heading']]
    if not log_indices:
        if 'log_lines' in parsed or 'redactions' in parsed:
            return None
    else:
        if len(log_indices) != 1:
            return None
        actual_log_lines = len(body_lines) - log_indices[0] - 1
        if 'log_lines' in parsed and parsed['log_lines'] != actual_log_lines:
            return None
    return parsed


def check_facts(case, c):
    obj = issue(case['input'])
    exp = shape(case['expect'], {'is_report', 'facts'}, 'a facts expectation')
    found_report = is_report(obj, c)
    found_facts = parse_facts(obj, c)
    problems = []
    if found_report != exp['is_report']:
        problems.append(f'is_report is {found_report}, the case expects {exp["is_report"]}')
    if found_facts != exp['facts']:
        problems.append(f'facts is {found_facts}, the case expects {exp["facts"]}')
    tags = ['facts' if found_facts is not None else 'facts refused']
    return problems, tags


def report_link(obj, c, authors):
    lines = obj['body'].split('\n')
    links = [x for x in lines if re.fullmatch(c['report_link'], x)]
    if obj['pull_request'] or obj['author'] not in authors or len(lines) < 3 or lines[-2] != '' \
            or links != [lines[-1]]:
        return None
    return int(re.fullmatch(c['report_link'], lines[-1]).group(1))


def closed(pr, c):
    found = [re.fullmatch(c['closing'], x) for x in pr['closes']]
    return [int(m.group(1)) for m in found if m]


def landed_re(c):
    form = re.escape(c['landed'])
    form = form.replace(re.escape('{pull_request}'), c['pull_request'][1:-1])
    return form.replace(re.escape('{version}'), c['version'][1:-1])


def landed_posts(inp, c):
    pr, issues, authors = inp['pull_request'], inp['issues'], inp['record_authors']
    posts = []
    full = f"{pr['repository']}#{pr['number']}"
    if not pr['merged'] or not re.fullmatch(c['pull_request'], full):
        return posts
    linked = [report_link(issue(issues[str(n)]), c, authors) for n in closed(pr, c)]
    for n in dict.fromkeys(x for x in linked if x is not None):
        obj = issue(issues[str(n)])
        if not is_report(obj, c) or obj['milestone'] is None:
            continue
        if not re.fullmatch(c['version'], obj['milestone']):
            continue
        if any(x['author'] in authors and re.fullmatch(landed_re(c), x['body']) for x in obj['comments']):
            continue
        posts.append([n, c['landed'].format(pull_request=full, version=obj['milestone'])])
    return posts


def check_report(case, c):
    obj = issue(case['input'])
    shape(case['expect'], {'is_report'}, 'a report expectation')
    found = is_report(obj, c)
    if found != case['expect']['is_report']:
        return [f'is_report is {found}, the case expects {case["expect"]["is_report"]}'], [('report' if found else 'not a report')]
    return [], ['report' if found else 'not a report']


def check_link(case, c):
    inp = shape(case['input'], {'issue', 'record_authors'}, 'a link input')
    shape(case['expect'], {'report'}, 'a link expectation')
    found = report_link(issue(inp['issue']), c, inp['record_authors'])
    tag = ['report link' if found is not None else 'forged link']
    if found != case['expect']['report']:
        return [f'report is {found}, the case expects {case["expect"]["report"]}'], tag
    return [], tag


def check_triage(case, c):
    inp, exp = case['input'], case['expect']
    report = issue(inp['report'])
    shape(inp['criteria'], c['criteria'], 'criteria')
    if not all(isinstance(v, bool) for v in inp['criteria'].values()):
        raise ValueError('each criterion is true or false')
    shape(exp, {'outcome', 'report_labels', 'report_milestone', 'report_comments', 'brief'}, 'a triage expectation')
    problems = []
    if not is_report(report, c):
        problems.append('triage input is not a report')
    outcome = 'fleet' if all(inp['criteria'].values()) else 'held'
    if exp['outcome'] != outcome:
        problems.append(f'outcome must be {outcome}')
        return problems, []
    rule = c['outcomes'][outcome]
    if sorted(exp['report_labels']) != sorted(rule['report_labels']):
        problems.append(f'the report must be labelled exactly {rule["report_labels"]}')
    if exp['report_comments'] != []:
        problems.append('triage posts no comment on the report')
    if outcome == 'held':
        if exp['brief'] is not None or exp['report_milestone'] is not None:
            problems.append('a held report gets no brief and no milestone')
        return problems, ['held']
    brief = exp['brief']
    shape(brief, {'title', 'body', 'labels', 'milestone'}, 'a brief')
    if sorted(brief['labels']) != sorted(rule['brief_labels']):
        problems.append(f'the brief must be labelled exactly {rule["brief_labels"]}')
    if not isinstance(brief['milestone'], str) or not re.fullmatch(c['version'], brief['milestone']):
        problems.append('the brief needs a version milestone')
    elif exp['report_milestone'] != brief['milestone']:
        problems.append("the report takes the brief's milestone")
    brief_issue = dict(brief, number=1, author='triage', pull_request=False, comments=[])
    if report_link(brief_issue, c, ['triage']) != report['number']:
        problems.append(f'the brief must end with the report link to #{report["number"]}')
    copied = re.findall(r'https?://\S+|`[^`]+`', report['body'])
    if any(x in brief['body'] for x in copied):
        problems.append('the brief copies a link or code from the report')
    return problems, ['to a fleet']


def check_landed(case, c):
    inp, exp = case['input'], case['expect']
    shape(inp, {'pull_request', 'issues', 'record_authors'}, 'a landed input')
    shape(inp['pull_request'], {'repository', 'number', 'merged', 'closes'}, 'a pull request')
    shape(exp, {'posts'}, 'a landed expectation')
    pr = inp['pull_request']
    if not isinstance(pr['merged'], bool) or not isinstance(pr['closes'], list) \
            or not all(isinstance(x, str) for x in pr['closes']):
        raise ValueError('merged is true or false and closes is a list of closing lines')
    posts = landed_posts(inp, c)
    problems = [] if exp['posts'] == posts else [f'posts must be {posts}']
    tags = []
    if len(posts) == 1:
        tags.append('landed')
    links = [report_link(issue(inp['issues'][str(n)]), c, inp['record_authors']) for n in closed(pr, c)]
    reached = [issue(inp['issues'][str(n)]) for n in links if n is not None]
    if pr['merged'] and not posts:
        if any(is_report(o, c) and o['comments'] for o in reached):
            tags.append('second merge')
        elif not any(is_report(o, c) for o in reached):
            tags.append('closes no report')
    return problems, tags


KINDS = {'report': check_report, 'facts': check_facts, 'link': check_link, 'triage': check_triage, 'landed': check_landed}


def scalar(s):
    if s.startswith('"'):
        return json.loads(s)
    if s in ('true', 'false'):
        return s == 'true'
    if s.startswith('[') and s.endswith(']'):
        return [scalar(x.strip()) for x in s[1:-1].split(',')]
    if not s or s[0] in '#&*!|>{%@`\'?-[' or ': ' in s or ' #' in s:
        raise ValueError(f'unsupported YAML value: {s!r}')
    return s


def yaml_block(lines, i, ind):
    if lines[i][1].startswith('- '):
        out = []
        while i < len(lines) and lines[i][0] == ind and lines[i][1].startswith('- '):
            rest = lines[i][1][2:]
            if ':' in rest:
                lines[i] = (ind + 2, rest)
                value, i = yaml_block(lines, i, ind + 2)
            else:
                value, i = scalar(rest), i + 1
            out.append(value)
        return out, i
    out = {}
    while i < len(lines) and lines[i][0] == ind and not lines[i][1].startswith('- '):
        key, sep, rest = lines[i][1].partition(':')
        if not sep or not re.fullmatch(r'[a-z][a-z_-]*', key) or key in out:
            raise ValueError(f'unsupported YAML line: {lines[i][1]!r}')
        rest = rest.strip()
        if rest:
            out[key], i = scalar(rest), i + 1
        elif i + 1 < len(lines) and lines[i + 1][0] > ind:
            out[key], i = yaml_block(lines, i + 1, lines[i + 1][0])
        else:
            raise ValueError(f'empty YAML key: {key}')
    return out, i


def parse_yaml(text):
    if '\t' in text or '\r' in text:
        raise ValueError('tabs and carriage returns are refused')
    lines = [(len(x) - len(x.lstrip(' ')), x.strip()) for x in text.split('\n') if x.strip()]
    value, i = yaml_block(lines, 0, 0)
    if i != len(lines):
        raise ValueError(f'unsupported YAML line: {lines[i][1]!r}')
    return value


def check_template(root, c):
    t = c['template']
    form = parse_yaml((root / t['path']).read_text(encoding='utf-8'))
    shape(form, {'name', 'description', 'labels', 'body'}, 'the template')
    problems = []
    if form['name'] != t['name'] or form['labels'] != t['labels']:
        problems.append(f'the template must be named {t["name"]!r} and labelled exactly {t["labels"]}')
    fields = []
    for f in form['body']:
        attrs = f.get('attributes', {})
        if 'render' in attrs or set(f) - {'type', 'id', 'attributes', 'validations'}:
            problems.append(f'field {f.get("id")} asks for more than words')
        if f.get('type') == 'checkboxes':
            req = bool(attrs.get('options')) and all(o.get('required') is True for o in attrs['options'])
        else:
            req = f.get('validations', {}).get('required') is True
        fields.append({'type': f.get('type'), 'id': f.get('id'), 'required': req})
        if f.get('type') == 'markdown':
            if not str(attrs.get('value', '')).startswith(t['notice']):
                problems.append('the template must open with the public notice')
            elif attrs.get('value') != t['warning']:
                problems.append('the template must carry exactly the approved warning')
        if f.get('id') == 'public-words' and [o.get('label') for o in attrs.get('options', [])] != [t['confirmation']]:
            problems.append('the public-words checkbox must confirm exactly the approved confirmation')
    if fields != t['fields']:
        problems.append(f'the template fields must be exactly {t["fields"]}, found {fields}')
    return problems


def check(root):
    root = Path(root)
    c = contract(root)
    problems, covered = [], set()
    for path in sorted((root / FIXTURES).glob('*.json')):
        try:
            case = shape(strict(path.read_text(encoding='utf-8')), {'kind', 'about', 'input', 'expect'}, 'a case')
            found, tags = KINDS[case['kind']](case, c)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            found, tags = [f'unreadable: {e}'], []
        problems += [f'{path.name}: {p}' for p in found]
        covered.update(tags)
    problems += [f'fixtures: no {k} case' for k in COVERAGE if k not in covered]
    try:
        problems += [f'template: {p}' for p in check_template(root, c)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        problems.append(f'template: unreadable: {e}')
    return problems


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[3]
    try:
        problems = check(root)
    except (OSError, ValueError) as e:
        print(f'check: cannot read the contract: {e}')
        return 2
    for p in problems:
        print(p)
    print('check: ok' if not problems else f'check: {len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
