#!/usr/bin/env python3
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def read(ref, path):
    return (ROOT / path).read_text() if ref is None else git('show', f'{ref}:{path}')


def rust_files(ref):
    names = git('ls-files', '--', '*.rs') if ref is None else git('ls-tree', '-r', '--name-only', ref)
    return [name for name in names.split() if name.endswith('.rs')]


def steps(text):
    found, job, step, block = [], None, None, False
    for line in text.splitlines():
        if re.fullmatch(r'  [a-z0-9-]+:', line):
            job, step = line.strip()[:-1], None
            continue
        start = re.match(r'      - (.*)', line)
        if start:
            step = {'job': job, 'if': '', 'run': ''}
            found.append(step)
            line = '        ' + start.group(1)
        if step is None:
            continue
        key = re.fullmatch(r'        ([a-z-]+): ?(.*)', line)
        if key:
            block = key.group(1) == 'run' and key.group(2) == '|'
            if key.group(1) in ('if', 'run') and not block:
                step[key.group(1)] = key.group(2)
        elif block and (line.startswith('          ') or not line.strip()):
            step['run'] += line + '\n'
        elif not line.startswith('        '):
            step, block = None, False
    return found


def inventory(ref):
    ci = read(ref, '.github/workflows/ci.yml')
    where = defaultdict(list)
    for step in steps(ci):
        part = re.search(r'matrix\.part == (\d+)', step['if'])
        label = step['job'] + (f' ({part.group(1)})' if part else '')
        for suite in dict.fromkeys(re.findall(r'[\w./*-]+\.py\b', step['run'])):
            where[suite].append(label)
    for name in rust_files(ref):
        text = read(ref, name)
        if 'Command::new("python3")' in text:
            for suite in re.findall(r'"([\w./-]+\.py)"', text):
                if Path(suite).name.startswith('test_'):
                    where[suite].append('cargo test ' + name)
    return ci, where


def dead_skips(ref):
    script = read(ref, 'ci/rust-tests.sh')
    if '--skip' not in script:
        return []
    loop = re.search(r'for \w+ in \$(\w+); do skip="\$skip --skip', script)
    names = re.search(rf'^{loop.group(1)}="([^"]*)"', script, re.M).group(1).split() if loop else ['<unresolved>']
    source = '\n'.join(read(ref, name) for name in rust_files(ref))
    return [name for name in names if not re.search(rf'\bfn {re.escape(name)}\s*\(', source)]


def evaluate(expression, context):
    tokens = re.findall(r"'(?:[^']|'')*'|\|\||&&|==|!=|!|\(|\)|[A-Za-z_][\w.-]*|\d+|\S", expression)
    if any(re.fullmatch(r"[^'|&=!()\w]", t) for t in tokens):
        raise ValueError(f'an expression this check does not read: {expression}')
    words = {'||': ' or ', '&&': ' and ', '!': ' not ', 'true': 'True', 'false': 'False', 'null': 'None'}
    python = ''.join(words.get(t, f' C[{t!r}] ' if re.match(r'[A-Za-z_]', t) else f' {t} ') for t in tokens)
    return eval(python, {'__builtins__': {}}, {'C': defaultdict(lambda: None, context)})


def concurrency(text, context):
    block = re.search(r'^concurrency:\n  group: (.*)\n  cancel-in-progress: (.*)$', text, re.M)
    if not block:
        return None
    group = re.sub(r'\$\{\{(.*?)\}\}', lambda m: str(evaluate(m.group(1), context) or ''), block.group(1))
    cancel = re.fullmatch(r'\$\{\{(.*)\}\}', block.group(2).strip())
    return group, bool(evaluate(cancel.group(1), context)) if cancel else block.group(2).strip() == 'true'


def privacy_findings(ref):
    text = read(ref, '.github/workflows/privacy.yml')
    events = {
        'pull request 7 pushed': ('pull_request', 7, 101, 'refs/pull/7/merge'),
        'pull request 7 edited': ('pull_request', 7, 102, 'refs/pull/7/merge'),
        'pull request 8': ('pull_request', 8, 103, 'refs/pull/8/merge'),
        'first main push': ('push', None, 201, 'refs/heads/main'),
        'second main push': ('push', None, 202, 'refs/heads/main'),
        'merge group': ('merge_group', None, 301, 'refs/heads/gh-readonly-queue/main/pr-7-0000000'),
    }
    got = {}
    for name, (event, number, run, ref_name) in events.items():
        got[name] = concurrency(text, {'github.event_name': event, 'github.event.pull_request.number': number,
                                       'github.run_id': run, 'github.ref': ref_name})
        if got[name] is None:
            return ['privacy.yml has no concurrency group']
    findings = []
    if got['pull request 7 pushed'] != got['pull request 7 edited'] or not got['pull request 7 edited'][1]:
        findings.append('an edit of a pull request does not cancel its older privacy run')
    if got['pull request 7 pushed'][0] == got['pull request 8'][0]:
        findings.append('two pull requests share one privacy group')
    for name in ('first main push', 'second main push', 'merge group'):
        others = [got[other][0] for other in events if other != name]
        if got[name][1] or got[name][0] in others:
            findings.append(f'the {name} run can be cancelled or replaced by another run')
    return findings


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: check_ci.py <the commit before #3102>; compares it with this working tree')
    before_ref = sys.argv[1]
    _, before = inventory(before_ref)
    ci, after = inventory(None)
    failed = []
    for suite in sorted(set(before) | set(after)):
        if before.get(suite) != after.get(suite):
            print(f'moved: {suite}: before {before.get(suite)}, after {after.get(suite)}')
    twice = {suite: places for suite, places in after.items() if len(places) > 1}
    failed += [f'runs {len(places)} times: {suite}: {places}' for suite, places in sorted(twice.items())]
    failed += [f'no longer runs: {suite}' for suite in sorted(set(before) - set(after))]
    matrix = re.search(r'^        part: \[(.*)\]$', ci, re.M).group(1).replace(' ', '').split(',')
    used = {place.split('(')[1][:-1] for places in after.values() for place in places if place.startswith('release (')}
    failed += [f'release part {part} runs no suite' for part in matrix if part not in used]
    failed += [f'a step runs in release part {part}, which the matrix lacks' for part in used if part not in matrix]
    failed += [f'rust-tests.sh skips a test that does not exist: {name}' for name in dead_skips(None)]
    failed += privacy_findings(None)
    if 'web-test' in ci:
        failed.append('ci.yml still has the legacy web-test job or names it')
    print(f'suites: {len(before)} before, {len(after)} after; runs: '
          f'{sum(map(len, before.values()))} before, {sum(map(len, after.values()))} after')
    for line in failed:
        print('FAIL:', line)
    print('check_ci: ok' if not failed else f'check_ci: {len(failed)} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
