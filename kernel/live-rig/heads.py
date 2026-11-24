#!/usr/bin/env python3
import argparse
import base64
import datetime
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rig = _load('rig', os.path.join(HERE, 'rig.py'))
Refused = rig.Refused
ROOT = rig.ROOT
OPENWIZ, WIZMARKET = 'openwizdev/OpenWiz', 'openwizdev/WizMarket'
TICKET_KEYS = {'id', 'ticket', 'pr', 'listing'}
FROZEN = re.compile(r'launch-fleet: look: live run due at the approved frozen head of #([0-9]+): ([0-9a-f]{40})'
                    r'(?![0-9a-f])')
ETAGS = 'heads-etags.json'
JOURNAL = 'publish.json'
JOURNAL_KEYS = {'login', 'outcome', 'comments', 'receipts', 'fork', 'ref', 'put', 'pull'}
FORK_READY_TRIES = 6
PAGE = 100
RUN_LINE = '<!-- openwiz:heads-run %s -->\n'
MAX_PAGES = 30
STAMP = '%Y-%m-%dT%H:%M:%SZ'
COMMENT = re.compile(r'\*\*[A-Z][A-Z0-9]{1,15} live kit run: [0-5] of 5 pass\*\*, at head `[0-9a-f]{40}`\n\n```\n'
                     r'((?:[^`\n]*\n)*)```\n')
COMMENT_URL = r'https://github\.com/openwizdev/OpenWiz/pull/[0-9]+#issuecomment-[0-9]+'
RECORD_REL = r'[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.json'
RECEIPT_REL = re.compile(r'receipts/([a-z0-9-]{2,40})/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{12}\.txt')
CHECK_PREFIX = re.compile(r'^(?:pass|fail) (?:version|start|wake|stop|token): ', re.M)
GH_OVERRIDES = ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_HOST')
SHAPES = []


def holds_credential_after_check_names(text):
    if not SHAPES:
        SHAPES.append(rig.kit_shapes())
    return bool(SHAPES[0].search(CHECK_PREFIX.sub('', text)))


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
    if len({host.casefold() for host in tickets}) != len(tickets):
        raise Refused('--tickets names one host twice, ignoring case')
    return tickets


def git(*args, cwd=None):
    # SECURITY: replace refs are ignored, so a checkout can never show another commit's tree under the head's name.
    env = dict(stored_login_env(), GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
    try:
        p = subprocess.run(['git', '-C', cwd or ROOT] + list(args), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=600, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def record_authors():
    text = git('show', 'HEAD:docs/agents/fleet.md') or ''
    rows = [line for line in text.splitlines() if line.startswith('| Record authors |')]
    authors = re.findall(r'`([^`]+)`', rows[0]) if len(rows) == 1 else []
    if not authors:
        raise Refused('docs/agents/fleet.md has no single Record authors row')
    return {a.lower() for a in authors}


def stored_login_env():
    # SECURITY: every gh call, the kit's included, goes as the person's stored github.com login, never an override.
    # SECURITY: names are filtered before any value is read, so a blocked override's value never enters this process.
    return dict({k: os.environ[k] for k in list(os.environ) if k not in GH_OVERRIDES}, GH_HOST='github.com')


def gh(args, send=None):
    env = stored_login_env()
    try:
        return subprocess.run(['gh'] + args + ['--hostname', 'github.com'], input=None if send is None else json.dumps(send),
                              stdin=subprocess.DEVNULL if send is None else None, capture_output=True, text=True,
                              timeout=120, env=env)
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
    path = 'repos/%s/issues/%d/comments?per_page=%d' % (OPENWIZ, number, PAGE)
    saved = cache.get(path)
    if not (isinstance(saved, dict) and set(saved) == {'etag', 'comments', 'more'}):
        saved = None
    p = gh(['api', '-i'] + (['-H', 'If-None-Match: ' + saved['etag']] if saved else []) + [path])
    head, _, body = p.stdout.replace('\r\n', '\n').partition('\n\n')
    lines = head.splitlines()
    status = lines[0].split()[1] if lines and len(lines[0].split()) > 1 else ''
    headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(':') for h in lines[1:])}
    linked = bool(re.search(r'rel="(?:next|last)"', headers.get('link', '')))
    if status == '304' and saved:
        found, more = saved['comments'], saved['more'] or linked or len(saved['comments']) >= PAGE
    elif status == '200' and p.returncode == 0:
        try:
            found = [{'id': c['id'], 'login': c['user']['login'], 'body': c['body'] or ''} for c in json.loads(body)]
        except (ValueError, KeyError, TypeError):
            raise Refused('GitHub gave an unreadable answer for #%d' % number)
        more = linked
        if headers.get('etag'):
            cache[path] = {'etag': headers['etag'], 'comments': found, 'more': more}
    else:
        raise Refused('cannot read the comments of #%d (HTTP %s)' % (number, status or '?'))
    if more:
        raise Refused('#%d has more comments than one read gives, so its latest frozen head is unknown' % number)
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


def run_kit(driver, entry, wait, settings, login):
    command = [sys.executable, '-I', rig.KIT, '--driver', driver, '--repo', settings['repo'],
               '--ticket', str(settings['ticket']), '--harness', entry['harness'], '--model', entry['model'],
               '--wait', str(wait)]
    p = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                       env=stored_login_env())
    sys.stderr.write(p.stdout)
    sys.stderr.flush()
    return p.returncode, rig.record_stdout(p.stdout, settings, login)


def receipt_py(record, listing, login, folder):
    return subprocess.run([sys.executable, '-I', os.path.join(HERE, 'receipt.py'), record, '--listing', listing,
                           '--run-by', login, '-o', folder], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          env=stored_login_env())


def rebuilt_receipt(out, r, login):
    folder = tempfile.mkdtemp()
    try:
        p = receipt_py(os.path.join(out, r['record']), r['listing'], login, folder)
        if p.returncode != 0:
            return None
        with open(p.stdout.strip()) as f:
            return os.path.relpath(p.stdout.strip(), folder), f.read()
    except OSError:
        return None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check_journal(plan, settings, out):
    def ok(value, pattern):
        return isinstance(value, str) and re.fullmatch(pattern, value) is not None

    def stamp(value):
        try:
            return value is None or bool(datetime.datetime.strptime(value, STAMP))
        except (TypeError, ValueError):
            return False

    def index(value, top=None):
        return type(value) is int and value >= 0 and (top is None or value < top)

    if not (isinstance(plan, dict) and set(plan) == JOURNAL_KEYS and ok(plan['login'], r'[A-Za-z0-9-]{1,39}') and
            plan['outcome'] in (0, 1) and type(plan['outcome']) is int and type(plan['ref']) is bool and
            isinstance(plan['comments'], list) and plan['comments'] and
            isinstance(plan['receipts'], list) and isinstance(plan['put'], list) and
            (plan['fork'] is None or ok(plan['fork'], r'[A-Za-z0-9-]{1,39}/WizMarket')) and
            (plan['pull'] is None or ok(plan['pull'], r'https://github\.com/openwizdev/WizMarket/pull/[0-9]+'))):
        raise Refused('%s is not a publish heads.py wrote' % JOURNAL)
    for c in plan['comments']:
        if not (isinstance(c, dict) and set(c) == {'pr', 'body', 'run', 'tried', 'url'} and
                index(c['pr']) and c['pr'] > 0 and
                isinstance(c['body'], str) and ok(c['run'], r'[0-9a-f]{32}') and stamp(c['tried']) and
                (c['url'] is None or ok(c['url'], COMMENT_URL))):
            raise Refused('%s holds a comment heads.py did not plan' % JOURNAL)
        lines = COMMENT.fullmatch(c['body'])
        if c['url'] is None and (lines is None or holds_credential_after_check_names(c['body']) or
                                 rig.record_stdout(lines.group(1), settings, plan['login']) != lines.group(1)):
            raise Refused('%s holds a comment that is not public kit output, so nothing is posted' % JOURNAL)
    for r in plan['receipts']:
        if not (isinstance(r, dict) and set(r) == {'rel', 'text', 'listing', 'pr', 'comment', 'record'} and
                ok(r['record'], RECORD_REL) and
                ok(r['rel'], RECEIPT_REL.pattern) and RECEIPT_REL.fullmatch(r['rel']).group(1) == r['listing'] and
                index(r['pr']) and r['pr'] > 0 and index(r['comment'], len(plan['comments'])) and
                isinstance(r['text'], str)):
            raise Refused('%s holds a receipt heads.py did not plan' % JOURNAL)
        if holds_credential_after_check_names(r['text']):
            raise Refused('%s holds a receipt with a credential, so nothing is posted' % JOURNAL)
        # SECURITY: a receipt is published only as receipt.py rebuilds it from its run record under the verified login.
        if rebuilt_receipt(out, r, plan['login']) != (r['rel'], r['text']) or \
                not receipt_matches_comment(os.path.join(out, r['record']), r, plan['comments'][r['comment']]):
            raise Refused('%s holds a receipt that is not its run record\'s receipt, so nothing is posted' % JOURNAL)
    if not all(isinstance(rel, str) for rel in plan['put']) or \
            not set(plan['put']) <= {r['rel'] for r in plan['receipts']}:
        raise Refused('%s puts a file it does not plan' % JOURNAL)


def receipt_matches_comment(record, r, comment):
    try:
        rec = rig.read_json(record, 'the run record')
        lines = COMMENT.fullmatch(comment['body'])
        return comment['pr'] == r['pr'] and lines is not None and lines.group(1) == rec['stdout'] and \
            comment['body'].split('\n', 1)[0].endswith(
                ' live kit run: 5 of 5 pass**, at head `%s`' % rec['driver_commit'])
    except (Refused, TypeError, KeyError):
        return False


def comment_for(ticket, passed, head, stdout):
    lines = stdout if stdout.endswith('\n') or not stdout else stdout + '\n'
    return '**%s live kit run: %d of 5 pass**, at head `%s`\n\n```\n%s```\n' % (ticket['id'], passed, head, lines)


def save(path, plan):
    with open(path + '.part', 'w') as f:
        json.dump(plan, f)
    os.replace(path + '.part', path)


class Session:
    def __init__(self, args):
        self.args, self.failed, self.login, self.folder, self.read = args, False, None, None, {}
        self.plan = {'login': None, 'outcome': None, 'comments': [], 'receipts': [], 'fork': None, 'ref': False,
                     'put': [], 'pull': None}

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
        self.plan['comments'].append({'pr': pr, 'body': text, 'run': secrets.token_hex(16), 'tried': None, 'url': None})
        return len(self.plan['comments']) - 1

    def receipt(self, host, ticket, record_path, comment):
        if self.folder is None:
            self.folder = tempfile.mkdtemp(dir=self.args.out, prefix='wizmarket-')
        p = receipt_py(record_path, ticket['listing'], self.run_by(), self.folder)
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
        self.plan['receipts'].append({'rel': rel, 'text': text, 'listing': ticket['listing'], 'pr': ticket['pr'],
                                      'comment': comment, 'record': os.path.relpath(record_path, self.args.out)})

    def host(self, name, ticket, configs, settings, kit_head, authors, cache):
        number = ticket['ticket']
        if number not in self.read:
            try:
                self.read[number] = frozen_head(read_comments(number, cache), authors)
            except Refused as e:
                self.read[number] = e
        if isinstance(self.read[number], Refused):
            return self.refuse(name, str(self.read[number]))
        found = self.read[number]
        if found is None:
            return self.say('skipped %s: no frozen head' % name)
        pr, head = found
        if pr != ticket['pr']:
            return self.say('skipped %s: the frozen head names #%d, not the build PR #%d' % (name, pr, ticket['pr']))
        config = configs.get(name.casefold())
        if config is None:
            return self.say('skipped %s: no host config' % name)
        if name.casefold() in {h.casefold() for h in self.args.allow_cost}:
            config = dict(config, cost='none')
        why = rig.check_host(config)
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
        kit_exit, stdout = run_kit(os.path.join(worktree, config['driver']), entry, config['wait'], settings,
                                   self.run_by())
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
        comment = self.post_comment(name, ticket['pr'], comment_for(ticket, passed, head, stdout))
        if kit_exit == 0 and passed == 5 and comment is not None:
            self.receipt(name, ticket, record_path, comment)



class Publish:
    def __init__(self, path, plan):
        self.path, self.plan = path, plan

    def step(self, key, value):
        self.plan[key] = value
        save(self.path, self.plan)

    def run(self):
        if gh_json(['api', 'user']).get('login') != self.plan['login']:
            raise Refused('gh is signed in as another login than this publish was planned under, so nothing is posted')
        for c in self.plan['comments']:
            if c['url'] is not None:
                continue
            body = c['body'] + RUN_LINE % c['run']
            if c['tried']:
                c['url'] = self.posted(c, body)
            if c['url'] is None:
                c['tried'] = datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)
                save(self.path, self.plan)
                c['url'] = gh_json(['api', '-X', 'POST', 'repos/%s/issues/%d/comments' % (OPENWIZ, c['pr']), '--input',
                                    '-'], {'body': body})['html_url']
            save(self.path, self.plan)
            print('posted ' + c['url'], flush=True)
        if self.plan['receipts']:
            self.wizmarket(self.plan['receipts'])
        os.remove(self.path)

    def posted(self, c, body):
        # SECURITY: run identity is this run's marker under the stored login on any page, never a body match or a clock.
        marker, mine = RUN_LINE.strip() % c['run'], []
        for page in range(1, MAX_PAGES + 1):
            found = gh_json(['api', 'repos/%s/issues/%d/comments?per_page=%d&page=%d' % (OPENWIZ, c['pr'], PAGE, page)])
            if not (isinstance(found, list) and all(isinstance(f, dict) for f in found)):
                raise Refused('cannot tell whether the earlier comment on #%d was posted, so nothing is posted' % c['pr'])
            mine += [f for f in found if isinstance(f.get('user'), dict) and f['user'].get('login') == self.plan['login']
                     and isinstance(f.get('body'), str) and marker in f['body']]
            if len(found) < PAGE:
                break
        else:
            raise Refused('#%d has more comments than heads.py reads, so nothing is posted' % c['pr'])
        if len(mine) > 1:
            raise Refused('#%d holds this run\'s comment more than once' % c['pr'])
        if mine and mine[0]['body'] != body:
            raise Refused('an earlier comment of this run on #%d was changed, so nothing is posted' % c['pr'])
        url = mine[0].get('html_url') if mine else None
        if mine and not (isinstance(url, str) and re.fullmatch(COMMENT_URL, url) and
                         url.split('/pull/')[1].split('#')[0] == str(c['pr'])):
            raise Refused('#%d gave an unreadable comment address, so nothing is posted' % c['pr'])
        return url

    @staticmethod
    def intended(found, head, title, body):
        return [p['html_url'] for p in found if isinstance(p, dict) and p.get('state') == 'open' and
                p.get('title') == title and p.get('body') == body and isinstance(p.get('head'), dict) and
                p['head'].get('label') == head and isinstance(p.get('base'), dict) and p['base'].get('ref') == 'main'
                ] if isinstance(found, list) else []

    def wizmarket(self, receipts):
        title = 'Kit receipts: 5 of 5 for %s' % ', '.join(sorted({r['listing'] for r in receipts}))
        body = 'Kit receipts written by `kernel/live-rig/heads.py`, each a 5-of-5 run at a driver PR\'s frozen head:' \
               '\n\n' + ''.join('- `%s`: build PR %s#%d, run posted at %s\n' % (
                   r['rel'], OPENWIZ, r['pr'], self.plan['comments'][r['comment']]['url']) for r in receipts)
        if holds_credential_after_check_names(title + '\n' + body):
            raise Refused('the WizMarket pull request text holds a credential, so it is not posted')
        if self.plan['fork'] is None:
            self.step('fork', gh_json(['api', '-X', 'POST', 'repos/%s/forks' % WIZMARKET, '--input', '-'], {})['full_name'])
        fork, branch = self.plan['fork'], os.path.splitext(receipts[0]['rel'])[0].replace('/', '-')
        if not self.plan['ref']:
            base = gh_json(['api', 'repos/%s/git/ref/heads/main' % WIZMARKET])['object']['sha']
            for attempt in range(FORK_READY_TRIES):
                p = gh(['api', '-X', 'POST', 'repos/%s/git/refs' % fork, '--input', '-'],
                       {'ref': 'refs/heads/' + branch, 'sha': base})
                if p.returncode == 0 or gh(['api', 'repos/%s/git/ref/heads/%s' % (fork, branch)]).returncode == 0:
                    break
                if attempt == FORK_READY_TRIES - 1:
                    raise Refused('gh could not make the branch on the fork (exit %d)' % p.returncode)
                time.sleep(5)
            self.step('ref', True)
        for r in receipts:
            if r['rel'] not in self.plan['put']:
                p = gh(['api', '-X', 'PUT', 'repos/%s/contents/%s' % (fork, r['rel']), '--input', '-'],
                       {'message': 'Add %s' % r['rel'], 'content': base64.b64encode(r['text'].encode()).decode(),
                        'branch': branch})
                if p.returncode != 0 and self.fork_text(fork, r['rel'], branch) != r['text']:
                    raise Refused('gh could not add %s to the fork (exit %d)' % (r['rel'], p.returncode))
                self.step('put', self.plan['put'] + [r['rel']])
        if self.plan['pull'] is None:
            head = '%s:%s' % (fork.split('/')[0], branch)
            p = gh(['api', '-X', 'POST', 'repos/%s/pulls' % WIZMARKET, '--input', '-'],
                   {'title': title, 'head': head, 'base': 'main', 'body': body})
            try:
                url = json.loads(p.stdout)['html_url'] if p.returncode == 0 else None
            except (ValueError, KeyError, TypeError):
                url = None
            if url is None:
                found = self.intended(gh_json(['api', 'repos/%s/pulls?head=%s&state=open' % (
                    WIZMARKET, urllib.parse.quote(head, safe=':'))]), head, title, body)
                if len(found) != 1:
                    raise Refused('gh could not open the WizMarket pull request (exit %d)' % p.returncode)
                url = found[0]
            self.step('pull', url)
        print('posted ' + self.plan['pull'], flush=True)

    @staticmethod
    def fork_text(fork, rel, branch):
        p = gh(['api', 'repos/%s/contents/%s?ref=%s' % (fork, rel, urllib.parse.quote(branch))])
        try:
            return base64.b64decode(json.loads(p.stdout)['content']).decode() if p.returncode == 0 else None
        except (ValueError, KeyError, TypeError):
            return None


def preview(plan):
    print('would finish the publish an earlier --post left unfinished:')
    for c in plan['comments']:
        if c['url'] is None:
            print('would post on %s#%d:\n%s' % (OPENWIZ, c['pr'], c['body']), end='')
    for r in plan['receipts']:
        if r['rel'] not in plan['put']:
            print('would add %s to %s:\n%s' % (r['rel'], WIZMARKET, r['text']), end='')
    if plan['receipts'] and plan['pull'] is None:
        print('would open a pull request on %s' % WIZMARKET)
    sys.stdout.flush()


def run(args):
    tickets = load_tickets(args.tickets)
    unknown = sorted({h.casefold() for h in args.allow_cost} - {h.casefold() for h in tickets})
    if unknown:
        raise Refused('--allow-cost names %s, which --tickets does not list' % ', '.join(unknown))
    settings = rig.load_settings(args.settings)
    os.environ['GIT_NO_REPLACE_OBJECTS'] = '1'
    kit_head = rig.clean_head()
    configs = {h['host'].casefold(): h for h in rig.load_hosts(args.hosts, None)}
    authors = record_authors()
    holds_credential_after_check_names('')
    os.makedirs(args.out, exist_ok=True)
    journal = os.path.join(args.out, JOURNAL)
    if os.path.exists(journal):
        plan = rig.read_json(journal, JOURNAL)
        check_journal(plan, settings, args.out)
        if not args.post:
            preview(plan)
            return plan['outcome']
        print('finishing the publish an earlier --post left unfinished', flush=True)
        Publish(journal, plan).run()
        return plan['outcome']
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
    if args.post and session.plan['comments']:
        session.plan.update(login=session.run_by(), outcome=1 if session.failed else 0)
        check_journal(session.plan, settings, args.out)
        save(journal, session.plan)
        Publish(journal, session.plan).run()
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
