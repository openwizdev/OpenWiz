#!/usr/bin/env python3
USAGE = '''The real-user journey bench: a fresh public repository to a first merged PR.

Exit 0: a fleet pull request merged, every page agreed with GitHub and the
repository was removed. Exit 1: any of those did not happen. Exit 2: bad input.'''

import argparse
import datetime
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
INSTALL_LINE = 'Install OpenWiz from github.com/openwizdev/OpenWiz'
HEADER = '# Bench\n\n| Bench | Before | Now | Pages | Run |\n| --- | --- | --- | --- | --- |\n'
ROW = '| Real-user |'


class Fail(Exception):
    pass


class FixtureError(Exception):
    pass


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_time(s):
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)


def clock_text(seconds):
    seconds = int(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}'


class LiveRunner:
    def now(self):
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    def sleep(self, seconds):
        time.sleep(seconds)

    def run(self, argv, cwd=None, env=None):
        full = dict(os.environ, **(env or {}))
        r = subprocess.run(argv, cwd=cwd, env=full, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr


class FixtureReplay:
    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        try:
            data = json.loads((self.folder / 'calls.json').read_text())
            self.t = parse_time(data['start'])
            self.rules = list(data['rules'])
        except (OSError, ValueError, KeyError) as e:
            raise FixtureError(f'unreadable fixture {self.folder / "calls.json"}: {e}')
        (self.folder / 'ran.jsonl').write_text('')

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += datetime.timedelta(seconds=seconds)

    def run(self, argv, cwd=None, env=None):
        with open(self.folder / 'ran.jsonl', 'a') as log:
            log.write(json.dumps({'argv': argv, 'env': sorted(env or {})}) + '\n')
        for rule in self.rules:
            if argv[:len(rule['argv'])] == rule['argv']:
                if rule.get('once'):
                    self.rules.remove(rule)
                self.sleep(rule.get('advance', 0))
                return rule.get('code', 0), rule.get('stdout', ''), rule.get('stderr', '')
        raise FixtureError('no fixture answer for: ' + ' '.join(argv))


def first_line(text):
    return (text.strip().splitlines() or [''])[0]


def prompt(repo):
    return (f'{INSTALL_LINE}\n\n'
            f'Then onboard the repository {repo} (already cloned here) to a first small fleet: '
            'one spec with one small ticket, approved, built, reviewed and merged by the fleet. '
            'This is a throwaway bench repository: take the default answer to every question.')


def first_merge(runner, repo, start, timeout, poll):
    prefix = f'https://github.com/{repo}/issues/'
    while True:
        code, out, err = runner.run(['gh', 'pr', 'list', '--repo', repo, '--state', 'merged',
                                     '--json', 'number,url,mergedAt,closingIssuesReferences'])
        if code:
            raise Fail(f'could not list pull requests: {first_line(err)}')
        fleet = [p for p in json.loads(out or '[]')
                 if any((i.get('url') or '').startswith(prefix) for i in p.get('closingIssuesReferences') or [])]
        if fleet:
            return min(fleet, key=lambda p: p['mergedAt'])
        if (runner.now() - start).total_seconds() + poll > timeout:
            return None
        runner.sleep(poll)


def check_pages(runner, repo, wizsite):
    token = os.environ.get('GH_TOKEN')
    if not token:
        code, out, err = runner.run(['gh', 'auth', 'token'])
        if code:
            raise Fail(f'no GitHub token for the checker: {first_line(err)}')
        token = out.strip()
    script = os.path.join(os.path.abspath(wizsite), 'scripts', 'live-check.mjs')
    code, out, err = runner.run(['node', script, '--repo', repo, '--prod', '--json'], env={'GH_TOKEN': token})
    try:
        result = json.loads(out)
        pages = [(bool(p['pass']), p['page'], p.get('detail', '')) for p in result['pages']]
    except (ValueError, KeyError, TypeError):
        return {'ok': False, 'pages': [], 'note': f'the checker gave no result (exit {code}): {first_line(err)}'}
    return {'ok': bool(result.get('ok')) and code == 0 and all(p[0] for p in pages), 'pages': pages}


def remove(runner, repo):
    code, _, err = runner.run(['gh', 'repo', 'delete', repo, '--yes'])
    if not code:
        return True, 'deleted'
    why = first_line(err)
    code, _, err2 = runner.run(['gh', 'repo', 'archive', repo, '--yes'])
    if not code:
        return True, f'archived (delete refused: {why})'
    return False, f'NO, still public (delete refused: {why}; archive refused: {first_line(err2)})'


def write_row(path, now_text, pages_text, day):
    path = pathlib.Path(path)
    text = path.read_text() if path.exists() else HEADER
    lines = text.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.startswith(ROW)), None)
    before = 'none' if at is None else lines[at].split('|')[3].strip()
    row = f'{ROW} {before} | {now_text} | {pages_text} | {day} |'
    if at is None:
        if text and not text.endswith('\n'):
            text += '\n'
        text += row + '\n'
    else:
        lines[at] = row + '\n'
        text = ''.join(lines)
    path.write_text(text)
    return row


def journey(runner, args, out):
    start = runner.now()
    owner = args.owner
    if not owner:
        code, login, err = runner.run(['gh', 'api', 'user', '--jq', '.login'])
        if code:
            raise Fail(f'could not read the signed-in GitHub user: {first_line(err)}')
        owner = login.strip()
    repo = f'{owner}/openwiz-bench-{start.strftime("%Y%m%dt%H%M%Sz")}'
    code, _, err = runner.run(['gh', 'repo', 'create', repo, '--public', '--add-readme'])
    if code:
        raise Fail(f'could not create the repository: {first_line(err)}')
    out(f'Repository: {repo} (public, throwaway)')
    merged = checked = None
    removed = (False, 'not reached')
    try:
        with tempfile.TemporaryDirectory(prefix='openwiz-bench-') as work:
            clone = os.path.join(work, 'repo')
            code, _, err = runner.run(['gh', 'repo', 'clone', repo, clone])
            if code:
                raise Fail(f'could not clone the repository: {first_line(err)}')
            started = runner.now()
            code, _, err = runner.run(shlex.split(args.agent) + [prompt(repo)], cwd=clone)
            if code:
                out(f'Time to first merged PR: none (the agent exited {code}: {first_line(err)})')
            else:
                merged = first_merge(runner, repo, started, args.timeout, args.poll)
                if merged:
                    took = (parse_time(merged['mergedAt']) - started).total_seconds()
                    merged['took'] = took
                    out(f'Time to first merged PR: {clock_text(took)} '
                        f'(pull request #{merged["number"]}, merged {merged["mergedAt"]})')
                else:
                    out(f'Time to first merged PR: none (no fleet pull request merged within {clock_text(args.timeout)})')
        checked = check_pages(runner, repo, args.wizsite)
        agree = sum(p[0] for p in checked['pages'])
        out(f'Checker: {"PASS" if checked["ok"] else "FAIL"}, {agree}/{len(checked["pages"])} pages agree with GitHub')
        if checked.get('note'):
            out(f'  {checked["note"]}')
        for ok, page, detail in checked['pages']:
            out(f'  {"PASS" if ok else "FAIL"} {page}: {detail}')
    finally:
        removed = remove(runner, repo)
        out(f'Repository removed: {removed[1]}')
    now_text = clock_text(merged['took']) if merged else 'no merge'
    pages_text = f'{sum(p[0] for p in checked["pages"])}/{len(checked["pages"])} pages agree'
    out('Row: ' + write_row(args.bench_file, now_text, pages_text, runner.now().strftime('%Y-%m-%d')))
    return bool(merged) and checked['ok'] and removed[0]


def main(argv=None):
    p = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--agent', required=True, help='the coding agent command; the install prompt is its last argument')
    p.add_argument('--owner', help='the GitHub account for the throwaway repository (default: the signed-in user)')
    p.add_argument('--wizsite', default=str(ROOT.parent / 'WizSite'), help='a WizSite checkout with scripts/live-check.mjs')
    p.add_argument('--bench-file', default=str(ROOT / 'docs' / 'bench.md'))
    p.add_argument('--timeout', type=int, default=4 * 3600, help='seconds to wait for the first merge')
    p.add_argument('--poll', type=int, default=60, help='seconds between merge checks')
    p.add_argument('--dry-run', metavar='FIXTURE_DIR', help='answer every command from FIXTURE_DIR/calls.json')
    args = p.parse_args(argv)

    def out(line):
        print(line, flush=True)

    try:
        runner = FixtureReplay(args.dry_run) if args.dry_run else LiveRunner()
        return 0 if journey(runner, args, out) else 1
    except Fail as e:
        print(f'journey: {e}', file=sys.stderr)
        return 1
    except FixtureError as e:
        print(f'journey: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
