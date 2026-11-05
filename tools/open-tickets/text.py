#!/usr/bin/env python3
"""Private local body/record drafts, checked by O3; never a GitHub write.

A caller must independently verify the private comment exists and contains the
saved quotes before using a draft publicly. This command cannot prove that.
"""
import argparse
from datetime import date
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan import Refusal, number, require, exact, parse_json  # noqa: E402

SOURCE = 'https://github.com/jparker2006/ClosedWiz'
CHECKER = Path(__file__).resolve().parent.parent / 'privacy-check' / 'check.py'
THREAD = re.compile(r'\bthr_[A-Za-z0-9][A-Za-z0-9_-]*')
MARKS = '"“”'
ALIAS_AUTHORITY = SOURCE + '/issues/1283#issuecomment-6711486946'


def compile_aliases(policy, literals):
    if policy is None:
        return None
    exact(policy, ['schema', 'mode', 'authority', 'literals_sha256', 'issues', 'roles'], 'body aliases')
    require(policy['schema'] == 'openwiz.body-aliases.v1' and policy['mode'] == 'dry_run_only' and
            policy['authority'] == ALIAS_AUTHORITY and
            policy['literals_sha256'] == hashlib.sha256(literals.read_bytes()).hexdigest(),
            'body aliases: authority or required list differs')
    scope, roles = policy['issues'], policy['roles']
    require(type(scope) is list and scope and all(number(n) for n in scope) and scope == sorted(set(scope)) and
            type(roles) is dict and roles and all(type(v) is str and v in {'home_account', 'private_name'}
                                                 for v in roles.values()), 'body aliases: invalid scope or roles')
    replacements = {}
    for value in literals.read_text(encoding='utf-8').splitlines():
        key = hashlib.sha256(value.encode()).hexdigest()
        if key in roles:
            require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value) is not None,
                    'body aliases: literal is not a runtime name')
            replacements[value] = roles[key]
    require(len(replacements) == len(roles), 'body aliases: unbound literal role')
    return scope, replacements


def alias_body(body, old, kind, aliases):
    if aliases is None or kind != 'issue' or old not in aliases[0]:
        return body
    roles = aliases[1]
    # Protect whole unknown home accounts and email addresses from partial
    # replacement; the unchanged value must still reach the required checker.
    protected = re.compile(r'''(?:/(?:home|Users)/[^/\s"'`<>:;,()\[\]{}]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)''')

    def ordinary(value):
        names = '|'.join(re.escape(v) for v in sorted(roles, key=len, reverse=True))
        pattern = r'(?<![\w.-])(?:' + names + r')(?![\w-]|\.[\w-])'
        return re.sub(pattern, lambda m: '<build-account>' if roles[m[0]] == 'home_account' else '<private-name>', value)

    output, start = [], 0
    for match in protected.finditer(body):
        output.append(ordinary(body[start:match.start()]))
        token = match[0]
        home = re.fullmatch(r'/(?:home|Users)/([A-Za-z0-9_.-]+)', token)
        # A plain ssh command names a runtime host, not an email destination.
        # Only an exact already-bound host may change; unknown/composite hosts
        # and other address tokens stay intact for the required checker.
        ssh_host = (token.split('@', 1)[1] if not home and '@' in token and
                    re.search(r'\bssh\s+$', body[:match.start()]) else None)
        output.append('${HOME}' if home and roles.get(home[1]) == 'home_account' else
                      ordinary(token) if roles.get(ssh_host) == 'private_name' else token)
        start = match.end()
    output.append(ordinary(body[start:]))
    return ''.join(output)


def named_positions(line):
    quoted = False
    positions = []
    for match in re.finditer(r'["“”]|\bJake\b', line):
        if match[0] in MARKS:
            quoted = not quoted
        elif not quoted:
            positions.append(match.start())
    return positions


def replace_quotes(line, start, pointer, quotes):
    if start and line[start - 1] == '\\':
        start -= 1
    result, position = line[:start], start
    while position < len(line):
        escaped = (line[position] == '\\' and position + 1 < len(line) and
                   line[position + 1] in MARKS)
        opening_at = position + int(escaped)
        if line[opening_at] not in MARKS:
            result += line[position]
            position += 1
            continue
        opening = line[opening_at]
        closing = '”' if opening == '“' else ('“' if opening == '”' else '"')
        end = opening_at + 1
        while end < len(line):
            slashes = len(line[:end]) - len(line[:end].rstrip('\\'))
            if line[end] == closing and bool(slashes % 2) == escaped:
                break
            end += 1
        require(end < len(line), 'text: unclosed or ambiguous private record')
        quotes.append(line[position:end + 1])
        result += pointer
        position = end + 1
    return result


CLOSING = re.compile(
    r'\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\b(?:\s*:)?\s*'
    r'(?P<token>(?:https?://github\.com/|#|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#|[<\[(*_`])\S*)',
    re.IGNORECASE)
BARE_REFERENCE = re.compile(r'(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>[1-9][0-9]*)')
URL_REFERENCE = re.compile(r'https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/'
                           r'(?P<route>issues|pull)/(?P<number>[1-9][0-9]*)', re.IGNORECASE)
REFERENCE_START = re.compile(r'(?:https?://github\.com/|#|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#)', re.IGNORECASE)


def complete_prose(line):
    depth, index = 0, 0
    while index < len(line):
        value = line[index]
        if value == '\\':
            return False
        if value == '`':
            width = len(line[index:]) - len(line[index:].lstrip('`'))
            closing = next((run for run in re.finditer(r'`+', line[index + width:]) if len(run[0]) == width), None)
            end = -1 if closing is None else index + width + closing.start()
            if end <= index + width:
                return False
            index = end + width
            if depth == 0:
                break
            continue
        if value == '(':
            depth += 1
        elif value == ')':
            depth -= 1
            if depth == 0:
                index += 1
                break
        index += 1
    return depth == 0 and index > 0 and (index == len(line) or line[index] in ' \t\r.,;!')


def closing_references(body, mapping, private_targets=None):
    def mapped(match):
        token = match['token']
        if token[0] in '<[(*_`':
            # Only complete ordinary prose is safe to leave unchanged. Do not
            # reinterpret wrapped, unknown, nested or reference-style links.
            line = body[match.start('token'):].split('\n', 1)[0]
            require(token[0] in '(`' and complete_prose(line) and not REFERENCE_START.search(line),
                    'text: unsupported closing-reference wrapper')
            return match[0]
        if not REFERENCE_START.match(token):
            return match[0]
        # Only sentence punctuation may follow a complete reference. URL
        # fragments, queries, markup and other suffixes never match a prefix.
        reference = token.rstrip('.,;!')
        suffix = token[len(reference):]
        parsed = URL_REFERENCE.fullmatch(reference) or BARE_REFERENCE.fullmatch(reference)
        require(parsed is not None, 'text: unsupported closing-reference suffix or token')
        repo, old = parsed['repo'], parsed['number']
        source_repo = 'jparker2006/ClosedWiz'
        if repo and repo.casefold() != source_repo.casefold():
            return match[0]
        require(parsed.re is not URL_REFERENCE or parsed['route'].lower() == 'issues',
                'text: closing reference is not a source issue')
        require(type(mapping) is dict, 'text: closing reference has no mapped destination')
        if int(old) not in mapping:
            require(type(private_targets) is dict and int(old) in private_targets,
                    'text: closing reference has no mapped destination')
            url = private_targets[int(old)]
            require(url == SOURCE + '/issues/' + old,
                    'text: excluded reference identity differs')
            return f'Related private issue [ClosedWiz #{old}]({url})' + suffix
        new = mapping[int(old)]
        require(new == 'planned' or number(new), 'text: invalid closing destination')
        replacement = '${openwiz:' + old + '}' if new == 'planned' else '#' + str(new)
        return match[0][:-len(token)] + replacement + suffix

    return CLOSING.sub(mapped, body)


def transform(body, pointer, old, kind, merged=(), closing_map=None, completed=None, merge_proofs=None,
              private_targets=None, body_aliases=None, held=()):
    require(type(body) is str and number(old) and kind in {'issue', 'pull_request'},
            'text: invalid source')
    route = 'issues' if kind == 'issue' else 'pull'
    require(re.fullmatch(re.escape(SOURCE + '/' + route + '/' + str(old)) +
                         r'#issuecomment-[1-9][0-9]*', pointer), 'text: invalid private-record pointer')
    require(not re.search(r'^was \[ClosedWiz #', body, re.MULTILINE), 'text: source already has a move link')
    lines, output, quotes, index = body.splitlines(keepends=True), [], [], 0
    previous, previous_named = '', False
    link = '[private record](' + pointer + ')'
    while index < len(lines):
        line = lines[index]
        positions = named_positions(line)
        if line.lstrip().startswith('>') and previous_named and re.search(r':(?:\*\*)?\s*$', previous):
            block = []
            while index < len(lines) and lines[index].lstrip().startswith('>'):
                block.append(lines[index])
                index += 1
            quotes.append(''.join(block).rstrip('\r\n'))
            output.append(link + '\n')
            previous, previous_named = '', False
            continue
        starts = []
        for position in positions:
            match = re.match(r'^[^"“”]*:(?:\*\*)?\s*\\?["“”]', line[position:])
            if match:
                starts.append(position + match.end() - 1)
        if starts:
            start = min(starts)
            output.append(replace_quotes(line, start, link, quotes))
        else:
            output.append(line)
        previous, previous_named = line.rstrip('\r\n'), bool(positions)
        index += 1
    public = THREAD.sub('', ''.join(output)).rstrip()
    if kind == 'pull_request':
        public = closing_references(public, closing_map, private_targets)
    public = alias_body(public, old, kind, body_aliases)
    if merged:
        require(all(number(n) for n in merged) and list(merged) == sorted(set(merged)),
                'text: invalid merged prerequisites')
        public += '\n\nMerged prerequisites (private records): ' + ', '.join(
            f'[ClosedWiz #{n}]({SOURCE}/issues/{n})' for n in merged) + '.'
        if merge_proofs is not None:
            public += ' Proof: ' + ', '.join(
                f"[closing PR #{p['pull_request']}]({SOURCE}/pull/{p['pull_request']})"
                for n in merged for p in merge_proofs[str(n)]) + '.'
    if completed:
        require(type(completed) is dict and all(number(n) and number(c) for n, c in completed.items()),
                'text: invalid completed prerequisites')
        public += '\n\nCompleted prerequisites (private records): ' + ', '.join(
            f'[ClosedWiz #{n}]({SOURCE}/issues/{n}) '
            f'([completion record]({SOURCE}/issues/{n}#issuecomment-{c}))'
            for n, c in sorted(completed.items())) + '.'
    if held:
        public += '\n\nHELD private prerequisites: ' + ', '.join(
            f"[ClosedWiz #{p['closedwiz']}]({p['url']}) (state: open)" for p in held) + '.'
    was = f'was [ClosedWiz #{old}]({SOURCE}/{route}/{old})'
    public = public + '\n\n' + was
    return public, quotes


def private_record(new, day, quotes):
    require(number(new), 'text: invalid destination number')
    require(type(day) is str and date.fromisoformat(day).isoformat() == day, 'text: invalid date')
    return (f'**Private record for OpenWiz #{new}, {day}:**\n\n' +
            ''.join(f'{i}. {quote}\n' for i, quote in enumerate(quotes, 1)))


def check_text(title, body, checker, literals):
    require(checker.is_file() and literals.is_file(), 'privacy: checker or required literals unavailable')
    # O3 validates the list as well; refuse before even launching it if it is unreadable/empty.
    values = literals.read_text(encoding='utf-8').splitlines()
    require(values and all(value.strip() for value in values), 'privacy: required literals unreadable or empty')
    with tempfile.TemporaryDirectory(prefix='openwiz-text-') as temporary:
        root = Path(temporary)
        title_file, body_file = root / 'title', root / 'body'
        title_file.write_text(title, encoding='utf-8')
        body_file.write_text(body, encoding='utf-8')
        result = subprocess.run([sys.executable, '-I', str(checker), '--title-file', str(title_file),
                                 '--body-file', str(body_file), '--literals', str(literals),
                                 '--require-literals'], capture_output=True, text=True, check=False)
    require(result.returncode == 0 and result.stdout.splitlines() == ['literals: used'],
            'privacy: O3 refused proposed title/body or did not establish literal coverage')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title-file', required=True, type=Path)
    parser.add_argument('--body-file', required=True, type=Path)
    parser.add_argument('--closedwiz', required=True, type=int)
    parser.add_argument('--openwiz', required=True, type=int)
    parser.add_argument('--kind', required=True, choices=['issue', 'pull_request'])
    parser.add_argument('--date', required=True)
    parser.add_argument('--pointer', required=True)
    parser.add_argument('--checker', type=Path, default=CHECKER)
    parser.add_argument('--literals', required=True, type=Path)
    parser.add_argument('--body-aliases', type=Path, help='explicit body-only dry-run alias policy')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        require(not args.out.exists(), 'text: output already exists')
        title = args.title_file.read_text(encoding='utf-8')
        policy = None if args.body_aliases is None else parse_json(args.body_aliases.read_text(encoding='utf-8'))
        body, quotes = transform(args.body_file.read_bytes().decode('utf-8'), args.pointer,
                                 args.closedwiz, args.kind, body_aliases=compile_aliases(policy, args.literals))
        record = private_record(args.openwiz, args.date, quotes) if quotes else None
        check_text(title, body, args.checker, args.literals)
        args.out.mkdir(mode=0o700)
        (args.out / 'body.txt').write_text(body, encoding='utf-8')
        if record:
            (args.out / 'private-record.txt').write_bytes(record.encode('utf-8'))
        print('private draft checked: O3 text/literals; pointer existence and migration unverified')
    except (Refusal, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, Refusal) else 'unreadable or invalid input'
        print('refused: ' + reason, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
