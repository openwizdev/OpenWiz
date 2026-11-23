#!/usr/bin/env python3
import argparse
import base64
import datetime
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rig = _load('rig', os.path.join(HERE, 'rig.py'))
kit = _load('kit', os.path.join(HERE, '..', 'driver-kit', 'kit.py'))
Refused = rig.Refused
ROOT = rig.ROOT
OPENWIZ, WIZMARKET = 'openwizdev/OpenWiz', 'openwizdev/WizMarket'
TICKET_KEYS = {'id', 'ticket', 'pr', 'listing'}
FROZEN = re.compile(r'launch-fleet: look: live run due at the approved frozen head of #([0-9]+): ([0-9a-f]{40})'
                    r'(?![0-9a-f])')
ETAGS = 'heads-etags.json'
FORK_READY_TRIES = 6
CHECK_LINE = re.compile(r'(pass|fail) (version|start|wake|stop|token): ')
PATH = re.compile(r'/[\w.~-]')
CHECK_PREFIX = re.compile(r'^(?:pass|fail) (?:version|start|wake|stop|token): ', re.M)


def holds_credential_after_check_names(text):
    return kit.holds_credential(CHECK_PREFIX.sub('', text))


def load_tickets(path):
    tickets = rig.read_json(path, '--tickets')
    if not isinstance(tickets, dict) or not tickets:
        raise Refused('--tickets is not an object of hosts')
    for host, t in tickets.items():
        if not (re.fullmatch(rig.NAME, host) and isinstance(t, dict) and set(t) == TICKET_KEYS and
                isinstance(t['id'], str) and re.fullmatch(r'[A-Z][A-Z0-9]{1,15}', t['id']) and
                all(type(t[k]) is int and t[k] > 0 for k in ('ticket', 'pr')) and
                isinstance(t['listing'], str) and re.fullmatch(r'[a-z0-9-]{2,40}', t['listing'])):
            raise Refused('--tickets: %s is not {"id", "ticket", "pr", "listing"}' % host)
    return tickets


def git(*args, cwd=None):
    # SECURITY: replace refs are ignored, so a checkout can never show another commit's tree under the head's name.
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
    try:
        p = subprocess.run(['git', '-C', cwd or ROOT] + list(args), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=600, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def reviewed_hosts(folder):
    # SECURITY: only tracked host configs of the clean checkout run, so every status command is reviewed code.
    real, root = os.path.realpath(folder), os.path.realpath(ROOT)
    if os.path.commonpath([real, root]) != root:
        raise Refused('--hosts is not a folder inside this checkout')
    try:
        names = sorted(n for n in os.listdir(real) if n.endswith('.json'))
    except OSError as e:
        raise Refused('cannot read --hosts: %s' % e)
    for n in names:
        if git('ls-files', '--error-unmatch', '--', os.path.relpath(os.path.join(real, n), root)) is None:
            raise Refused('--hosts holds %s, which is not a tracked file of this checkout' % n)
    return real


def record_authors():
    text = git('show', 'HEAD:docs/agents/fleet.md') or ''
    rows = [line for line in text.splitlines() if line.startswith('| Record authors |')]
    authors = re.findall(r'`([^`]+)`', rows[0]) if len(rows) == 1 else []
    if not authors:
        raise Refused('docs/agents/fleet.md has no single Record authors row')
    return {a.lower() for a in authors}


def gh(args, send=None):
    try:
        return subprocess.run(['gh'] + args, input=None if send is None else json.dumps(send),
                              stdin=subprocess.DEVNULL if send is None else None, capture_output=True, text=True,
                              timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused('gh did not run: %s' % type(e).__name__)


def gh_json(args, send=None):
    p = gh(args, send)
    try:
        if p.returncode == 0:
            return json.loads(p.stdout)
    except ValueError:
        pass
    raise Refused('gh %s failed (exit %d)' % (' '.join(a for a in args[:4] if a != '--input'), p.returncode))


def read_comments(number, cache):
    found, path = [], 'repos/%s/issues/%d/comments?per_page=100' % (OPENWIZ, number)
    while path:
        saved = cache.get(path)
        p = gh(['api', '-i'] + (['-H', 'If-None-Match: ' + saved['etag']] if saved else []) + [path])
        head, _, body = p.stdout.replace('\r\n', '\n').partition('\n\n')
        lines = head.splitlines()
        status = lines[0].split()[1] if lines and len(lines[0].split()) > 1 else ''
        headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(':') for h in lines[1:])}
        if status == '304' and saved:
            page = saved['comments']
        elif status == '200' and p.returncode == 0:
            try:
                page = [{'id': c['id'], 'login': c['user']['login'], 'body': c['body'] or ''} for c in json.loads(body)]
            except (ValueError, KeyError, TypeError):
                raise Refused('GitHub gave an unreadable answer for #%d' % number)
            if headers.get('etag'):
                cache[path] = {'etag': headers['etag'], 'comments': page}
        else:
            raise Refused('cannot read the comments of #%d (HTTP %s)' % (number, status or '?'))
        found += page
        nxt = re.search(r'<https://api\.github\.com/([^>]+)>;\s*rel="next"', headers.get('link', ''))
        path = nxt.group(1) if nxt else None
    return found


def frozen_head(comments, authors):
    head = None
    for c in comments:
        if c['login'].lower() in authors:
            for line in c['body'].splitlines():
                m = FROZEN.match(line)
                if m:
                    head = int(m.group(1)), m.group(2)
    return head


def public_stdout(stdout, private):
    kept = []
    for line in stdout.splitlines():
        m = CHECK_LINE.match(line)
        if not m:
            continue
        # PRIVACY: a credential shape, a path (`/` then a name, so the worktree and checkout too), the settings'
        # repository or owner, or the signed-in login withholds the whole line.
        if holds_credential_after_check_names(line) or PATH.search(line) or any(p.lower() in line.lower() for p in private if p):
            line = '%s %s: withheld' % m.groups()
        kept.append(line + '\n')
    return ''.join(kept)


def run_kit(driver, entry, wait, settings, private):
    command = [sys.executable, '-I', rig.KIT, '--driver', driver, '--repo', settings['repo'],
               '--ticket', str(settings['ticket']), '--harness', entry['harness'], '--model', entry['model'],
               '--wait', str(wait)]
    p = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    sys.stderr.write(p.stdout)
    sys.stderr.flush()
    return p.returncode, public_stdout(p.stdout, private)


def comment_for(ticket, passed, head, stdout):
    lines = stdout if stdout.endswith('\n') or not stdout else stdout + '\n'
    return '**%s live kit run: %d of 5 pass**, at head `%s`\n\n```\n%s```\n' % (ticket['id'], passed, head, lines)


class Session:
    def __init__(self, args):
        self.args, self.failed, self.receipts, self.login, self.folder = args, False, [], None, None

    def say(self, line):
        print(line, flush=True)

    def refuse(self, host, why):
        self.say('refused %s: %s' % (host, why))
        self.failed = True

    def run_by(self):
        if self.login is None:
            self.login = gh_json(['api', 'user']).get('login')
            if not isinstance(self.login, str) or not self.login:
                raise Refused('gh gave no signed-in login')
        return self.login

    def post_comment(self, host, pr, text):
        if holds_credential_after_check_names(text):
            self.refuse(host, 'the comment holds a credential, so it is not %s' % (
                'posted' if self.args.post else 'printed'))
            return None
        if not self.args.post:
            self.say('would post on %s#%d:' % (OPENWIZ, pr))
            print(text, end='', flush=True)
            return None
        url = gh_json(['api', '-X', 'POST', 'repos/%s/issues/%d/comments' % (OPENWIZ, pr), '--input', '-'],
                      {'body': text})['html_url']
        self.say('posted ' + url)
        return url

    def receipt(self, host, ticket, record_path, comment_url):
        if self.folder is None:
            self.folder = tempfile.mkdtemp(dir=self.args.out, prefix='wizmarket-')
        p = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'receipt.py'), record_path, '--listing',
                            ticket['listing'], '--run-by', self.run_by(), '-o', self.folder],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if p.returncode != 0:
            why = (p.stderr.strip().splitlines() or ['exit %d' % p.returncode])[-1]
            self.refuse(host, 'no receipt: ' + why)
            return
        path = p.stdout.strip()
        with open(path) as f:
            text = f.read()
        rel = os.path.relpath(path, self.folder)
        if holds_credential_after_check_names(text):
            self.refuse(host, 'the receipt holds a credential, so it is not %s' % (
                'posted' if self.args.post else 'printed'))
            return
        if not self.args.post:
            self.say('would add %s to %s:' % (rel, WIZMARKET))
            print(text, end='', flush=True)
        self.receipts.append((rel, text, host, ticket, comment_url))

    def host(self, name, ticket, configs, settings, kit_head, authors, cache):
        found = frozen_head(read_comments(ticket['ticket'], cache), authors)
        if found is None:
            return self.say('skipped %s: no frozen head' % name)
        pr, head = found
        if pr != ticket['pr']:
            return self.say('skipped %s: the frozen head names #%d, not the build PR #%d' % (name, pr, ticket['pr']))
        config = configs.get(name)
        if config is None:
            return self.say('skipped %s: no host config' % name)
        why = rig.check_host(config)
        if why == 'cost' and name in self.args.allow_cost:
            why = None
        if why:
            return self.say('skipped %s: %s' % (name, why))
        if git('fetch', '-q', '--no-tags', 'origin', head) is None:
            self.failed = True
            return self.say('skipped %s: git cannot fetch the frozen head %s' % (name, head[:12]))
        fetched = git('rev-parse', 'FETCH_HEAD')
        if fetched != head:
            self.failed = True
            return self.say('skipped %s: git fetched %s, not the frozen head %s' % (name, (fetched or '?')[:12],
                                                                                    head[:12]))
        scratch = tempfile.mkdtemp()
        worktree = os.path.join(scratch, 'driver')
        try:
            if git('worktree', 'add', '-q', '--detach', worktree, head) is None or \
                    git('rev-parse', 'HEAD', cwd=worktree) != head:
                self.failed = True
                return self.say('skipped %s: the worktree is not at the frozen head %s' % (name, head[:12]))
            for entry in config['runs']:
                self.entry(name, ticket, config, entry, head, kit_head, settings, worktree)
        finally:
            git('worktree', 'remove', '--force', worktree)
            shutil.rmtree(scratch, ignore_errors=True)

    def entry(self, name, ticket, config, entry, head, kit_head, settings, worktree):
        began = time.monotonic()
        day = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        owner = settings['repo'].split('/')[0]
        kit_exit, stdout = run_kit(os.path.join(worktree, config['driver']), entry, config['wait'], settings,
                                   [settings['repo'], owner, self.run_by()])
        record = {'host': config['host'], 'harness': entry['harness'], 'model': entry['model'], 'date': day,
                  'driver_commit': head, 'kit_commit': kit_head, 'outcome': 'ran', 'skipped': None,
                  'kit_exit': kit_exit, 'stdout': stdout, 'seconds': int(round(time.monotonic() - began))}
        rig.write_record(self.args.out, record)
        record_path = os.path.join(self.args.out, day, '%s-%s-%s.json' % (
            config['host'], entry['harness'], entry['model']))
        passed = sum(1 for line in stdout.splitlines() if line.startswith('pass '))
        self.say('ran %s: %d of 5 at %s' % (name, passed, head[:12]))
        if kit_exit not in (0, 1):
            return self.refuse(name, 'kit.py could not run (exit %d), so nothing is posted' % kit_exit)
        self.failed = self.failed or kit_exit != 0
        url = self.post_comment(name, ticket['pr'], comment_for(ticket, passed, head, stdout))
        if kit_exit == 0 and passed == 5 and (url or not self.args.post):
            self.receipt(name, ticket, record_path, url)

    def wizmarket(self):
        if not (self.args.post and self.receipts):
            return
        title = 'Kit receipts: 5 of 5 for %s' % ', '.join(sorted({r[3]['listing'] for r in self.receipts}))
        body = 'Kit receipts written by `kernel/live-rig/heads.py`, each a 5-of-5 run at a driver PR\'s frozen head:' \
               '\n\n' + ''.join('- `%s`: build PR %s#%d, run posted at %s\n' % (rel, OPENWIZ, t['pr'], url)
                                for rel, _, _, t, url in self.receipts)
        if holds_credential_after_check_names(title + '\n' + body):
            return self.refuse('wizmarket', 'the pull request text holds a credential, so it is not posted')
        fork = gh_json(['api', '-X', 'POST', 'repos/%s/forks' % WIZMARKET, '--input', '-'], {})['full_name']
        base = gh_json(['api', 'repos/%s/git/ref/heads/main' % WIZMARKET])['object']['sha']
        branch = os.path.splitext(self.receipts[0][0])[0].replace('/', '-')
        for attempt in range(FORK_READY_TRIES):
            p = gh(['api', '-X', 'POST', 'repos/%s/git/refs' % fork, '--input', '-'],
                   {'ref': 'refs/heads/' + branch, 'sha': base})
            if p.returncode == 0:
                break
            if attempt == FORK_READY_TRIES - 1:
                raise Refused('gh could not make the branch on the fork (exit %d)' % p.returncode)
            time.sleep(5)
        for rel, text, _, _, _ in self.receipts:
            gh_json(['api', '-X', 'PUT', 'repos/%s/contents/%s' % (fork, rel), '--input', '-'],
                    {'message': 'Add %s' % rel, 'content': base64.b64encode(text.encode()).decode(), 'branch': branch})
        url = gh_json(['api', '-X', 'POST', 'repos/%s/pulls' % WIZMARKET, '--input', '-'],
                      {'title': title, 'head': '%s:%s' % (fork.split('/')[0], branch), 'base': 'main',
                       'body': body})['html_url']
        self.say('posted ' + url)


def run(args):
    tickets = load_tickets(args.tickets)
    unknown = sorted(set(args.allow_cost) - set(tickets))
    if unknown:
        raise Refused('--allow-cost names %s, which --tickets does not list' % ', '.join(unknown))
    settings = rig.load_settings(args.settings)
    kit_head = rig.clean_head()
    configs = {h['host']: h for h in rig.load_hosts(reviewed_hosts(args.hosts), None)}
    authors = record_authors()
    os.makedirs(args.out, exist_ok=True)
    cache_path = os.path.join(args.out, ETAGS)
    cache = rig.read_json(cache_path, ETAGS) if os.path.exists(cache_path) else {}
    session = Session(args)
    try:
        for name, ticket in tickets.items():
            session.host(name, ticket, configs, settings, kit_head, authors, cache)
    finally:
        with open(cache_path + '.part', 'w') as f:
            json.dump(cache, f)
        os.replace(cache_path + '.part', cache_path)
    session.wizmarket()
    return 1 if session.failed else 0


def main(argv):
    ap = argparse.ArgumentParser(prog='heads.py')
    ap.add_argument('--tickets', required=True, help='the live-check tickets file, kernel/live-rig/vps/live-tickets.json')
    ap.add_argument('--hosts', required=True, help='the folder of host configs; only its *.json files are read')
    ap.add_argument('--settings', required=True, help='a local JSON file {"repo": "<owner>/<name>", "ticket": <n>}')
    ap.add_argument('--out', required=True, help='the folder for run records, receipts and saved ETags')
    ap.add_argument('--allow-cost', action='append', default=[], metavar='HOST',
                    help='run this paid host; only the person passes it, never an agent')
    ap.add_argument('--post', action='store_true',
                    help="post through the person's own signed-in gh; without it, print what would be posted")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (Refused, OSError) as e:
        print('heads.py: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
