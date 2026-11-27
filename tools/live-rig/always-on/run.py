#!/usr/bin/env python3
import argparse
import datetime
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

OPENWIZ = 'https://github.com/openwizdev/OpenWiz.git'
ROOT = os.path.expanduser('~/.local/share/openwiz-live')
CHECKS = ('version', 'start', 'wake', 'stop', 'token')
LINE = re.compile(r'(pass|fail) (version|start|wake|stop|token): (.*)')
DRIVER_STATE = {'openclaw': 'OPENWIZ_OPENCLAW_STATE'}
SKILL_HOMES = {'claude': '~/.claude/skills', 'codex': '~/.codex/skills'}
SIGN_INS = {'claude': (('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY'), '~/.claude/.credentials.json'),
            'codex': (('OPENAI_API_KEY',), '~/.codex/auth.json')}
ADAPTERS = {'claude': '@agentclientprotocol/claude-agent-acp', 'codex': '@agentclientprotocol/codex-acp'}
MARKER = '<!-- openwiz:status v1 -->'
SECRET_NAME = re.compile(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY$|^KEY', re.I)
DAY = 24 * 3600


class Blocked(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(t):
    return t.strftime('%Y-%m-%d %H:%M UTC')


def took(seconds):
    seconds = int(round(seconds))
    return '%d s' % seconds if seconds < 60 else '%d min %02d s' % divmod(seconds, 60)


def last_line(text):
    lines = [x for x in text.strip().splitlines() if x.strip()]
    return lines[-1].strip() if lines else 'no output'


def redact(text):
    # PRIVACY: receipts are public. Every secret value in this environment and the home folder are taken out of
    # any text a receipt or log keeps, whatever produced it.
    for value in sorted((v for k, v in os.environ.items() if SECRET_NAME.search(k) and len(v) >= 8), key=len,
                        reverse=True):
        text = text.replace(value, '<redacted>')
    return text.replace(os.path.expanduser('~'), '~')


def sh(argv, cwd=None, timeout=900, env=None):
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, '', '%s timed out after %s' % (os.path.basename(argv[0]), took(timeout))
    except OSError as e:
        return 127, '', '%s did not run: %s' % (os.path.basename(argv[0]), e.strerror)
    return p.returncode, p.stdout, p.stderr


def must(argv, what, **kw):
    code, out, err = sh(argv, **kw)
    if code:
        raise Blocked('%s failed (exit %d): %s' % (what, code, redact(last_line(err or out))))
    return out


def gh_json(argv, what):
    try:
        return json.loads(must(['gh'] + argv, what, timeout=120))
    except ValueError:
        raise Blocked('%s gave no JSON' % what)


class Run:
    def __init__(self, a):
        self.a = a
        self.home = os.path.join(a.root, a.driver)
        self.started = now()
        self.clock = time.monotonic()
        self.facts = {'when': stamp(self.started), 'cleanup': [], 'notes': []}
        self.kit = None
        self.blocked = None

    def py(self, *argv, **kw):
        return sh([sys.executable, '-I'] + list(argv), **kw)

    def clone(self, work):
        dest = os.path.join(work, 'OpenWiz')
        t = time.monotonic()
        must(['git', 'clone', '--quiet', '--filter=blob:none', OPENWIZ, dest], 'cloning OpenWiz')
        git = lambda *x: must(['git', '-C', dest] + list(x), 'git ' + x[0]).strip()
        self.facts['main'] = git('rev-parse', 'HEAD')
        self.facts['driver_commit'] = git('log', '-1', '--format=%H', '--', 'adapters/%s' % self.a.driver)
        self.facts['clone_seconds'] = time.monotonic() - t
        if not os.path.isfile(os.path.join(dest, 'adapters', self.a.driver, 'driver')):
            raise Blocked('OpenWiz main has no adapters/%s/driver' % self.a.driver)
        return dest

    def skills(self, repo):
        code, out, err = self.py('tools/wizskills/install.py', cwd=repo)
        if code:
            raise Blocked('tools/wizskills/install.py exited %d: %s' % (code, redact(last_line(out + err))))
        with open(os.path.join(repo, 'wizskills.lock')) as f:
            version = json.load(f)['version']
        dest = os.path.join(self.a.root, 'wizskills-' + version)
        must(['sh', os.path.join(repo, '.wizskills', 'install.sh'), '--version', version, '--dest', dest],
             'installing WizSkills %s' % version)
        home = os.path.expanduser(SKILL_HOMES.get(self.a.harness, '~/.claude/skills'))
        os.makedirs(home, exist_ok=True)
        ours, foreign = os.path.join(self.a.root, 'wizskills-'), []
        for skill in sorted(os.listdir(os.path.join(dest, 'skills'))):
            target, link = os.path.join(dest, 'skills', skill), os.path.join(home, skill)
            if not os.path.isfile(os.path.join(target, 'SKILL.md')):
                continue
            if os.path.islink(link) and os.readlink(link).startswith(ours):
                if os.readlink(link) == target:
                    continue
                os.unlink(link)
            elif os.path.lexists(link):
                foreign.append(skill)
                continue
            os.symlink(target, link)
        self.facts['wizskills'] = version
        if self.a.skill in foreign:
            self.facts['notes'].append('the agent\'s `%s` skill is not the runner\'s link to WizSkills %s, so it '
                                       'ran whatever that entry holds' % (self.a.skill, version))
        return dest

    def offline(self, repo):
        t = time.monotonic()
        code, out, err = self.py('adapters/%s/test_driver.py' % self.a.driver, cwd=repo, timeout=1800)
        text = out + err
        ran = re.findall(r'^Ran (\d+) tests? in', text, re.M)
        summary = [x for x in text.splitlines() if x.startswith(('OK', 'FAILED'))]
        self.facts['offline'] = {'ok': code == 0, 'exit': code, 'seconds': time.monotonic() - t,
                                 'ran': int(ran[-1]) if ran else None,
                                 'summary': redact(summary[-1] if summary else last_line(text)),
                                 'failed': [redact(x) for x in re.findall(r'^(?:FAIL|ERROR): (\S+)', text, re.M)][:10]}

    def preflight(self):
        names, path = SIGN_INS.get(self.a.harness, ((), None))
        if not (any(os.environ.get(n) for n in names) or (path and os.path.isfile(os.path.expanduser(path)))):
            raise Blocked('no %s sign-in reached this run: none of %s is set and %s is missing; load the box\'s '
                          'sign-ins before the runner, as the README shows' % (self.a.harness, ', '.join(names), path))
        if self.a.driver == 'openclaw':
            if not shutil.which('acpx'):
                raise Blocked('acpx is not on PATH; install it with `npm install -g acpx@0.22.0`')
            self.facts['acpx'] = must(['acpx', '--version'], 'acpx --version', timeout=60).strip()
        t = gh_json(['issue', 'view', str(self.a.ticket), '-R', self.a.repo, '--json', 'state,labels'],
                    'reading the test ticket')
        labels = {x['name'] for x in t['labels']}
        if t['state'] != 'OPEN':
            raise Blocked('%s#%d is %s; reopen it' % (self.a.repo, self.a.ticket, t['state'].lower()))
        if 'ready-for-agent' not in labels:
            raise Blocked('%s#%d has no ready-for-agent label, so build-ticket claims nothing; a maintainer adds it'
                          % (self.a.repo, self.a.ticket))
        if 'needs-info' in labels:
            must(['gh', 'issue', 'edit', str(self.a.ticket), '-R', self.a.repo, '--remove-label', 'needs-info'],
                 'removing needs-info', timeout=120)
            self.facts['cleanup'].append('took needs-info off the ticket, left by an earlier asking note')

    def live_notes(self):
        out = must(['gh', 'api', '--paginate', 'repos/%s/issues/%d/comments' % (self.a.repo, self.a.ticket),
                    '--jq', '.[] | {id, body}'], 'reading the ticket\'s comments', timeout=120)
        for line in out.splitlines():
            c = json.loads(line)
            lines = (c['body'] or '').replace('\r\n', '\n').strip().split('\n')
            if lines[0] != MARKER:
                continue
            fields = dict(x.partition(': ')[::2] for x in lines[1:])
            if fields.get('agent') == 'builder' and fields.get('state') in ('working', 'asking'):
                yield c['id'], fields

    def stop_notes(self, skills, when):
        status = os.path.join(skills, 'skills', 'launch-fleet', 'scripts', 'status.py')
        for note, f in self.live_notes():
            code, out, err = self.py(status, 'write', '--repo', self.a.repo, '--ticket', str(self.a.ticket),
                                     '--agent', 'builder', '--state', 'stopped', '--why', 'live check ended',
                                     '--harness', f.get('harness', self.a.harness),
                                     '--model', f.get('model', self.a.model), '--skills', f.get('skills', ''),
                                     '--step', 'The live check stopped this run', '--note', str(note), timeout=180)
            self.facts['cleanup'].append('marked builder note %d stopped %s' % (note, when) if code == 0 else
                                         'could not mark builder note %d stopped (exit %d): %s'
                                         % (note, code, redact(last_line(out + err))))

    def github_refs(self):
        heads = must(['git', 'ls-remote', '--heads', 'https://github.com/%s.git' % self.a.repo], 'listing branches',
                     timeout=120)
        prs = gh_json(['pr', 'list', '-R', self.a.repo, '--state', 'open', '--limit', '200', '--json',
                       'number,headRefName,title,body'], 'listing pull requests')
        return {x.split('\trefs/heads/', 1)[1] for x in heads.splitlines() if '\trefs/heads/' in x}, prs

    def tidy_github(self, before):
        branches, prs = self.github_refs()
        new_branches = branches - before[0]
        known = {p['number'] for p in before[1]}
        named = re.compile(r'(^|/)%d(-|$)' % self.a.ticket)
        for p in prs:
            if p['number'] in known:
                continue
            if (p['headRefName'] in new_branches and named.search(p['headRefName'])) or \
                    p['title'].startswith('#%d:' % self.a.ticket):
                must(['gh', 'pr', 'close', str(p['number']), '-R', self.a.repo, '--delete-branch', '--comment',
                      'Closed by the %s driver\'s scheduled live check: its builder opened this on the test ticket '
                      '#%d, and the kit keeps nothing.' % (self.a.driver, self.a.ticket)], 'closing a pull request')
                new_branches.discard(p['headRefName'])
                self.facts['cleanup'].append('closed pull request #%d and deleted its branch' % p['number'])
        for b in sorted(new_branches):
            if named.search(b):
                must(['gh', 'api', '-X', 'DELETE', 'repos/%s/git/refs/heads/%s' % (self.a.repo, b)],
                     'deleting a branch', timeout=120)
                self.facts['cleanup'].append('deleted branch `%s`' % b)
            else:
                self.facts['cleanup'].append('left branch `%s` alone: it appeared during the run but is not named '
                                             'for the ticket' % b)

    def tidy_driver(self, state, repo, before):
        for path in sorted(glob.glob(os.path.join(state, 'run-*.json'))):
            try:
                with open(path) as f:
                    stopped = json.load(f).get('stopped')
            except (OSError, ValueError):
                stopped = None
            if stopped is False:
                run = os.path.basename(path)[:-len('.json')]
                code, out, _ = self.stop_run(state, repo, run)
                self.facts['cleanup'].append('stopped driver run %s the kit left running' % run if code == 0 else
                                             'could not stop driver run %s (exit %d): %s'
                                             % (run, code, redact(last_line(out))))
        for folder in sorted(set(glob.glob(os.path.join(state, 'work', 'run-*'))) - before):
            shutil.rmtree(folder, ignore_errors=True)

    def stop_run(self, state, repo, run):
        try:
            p = subprocess.run([os.path.join(repo, 'adapters', self.a.driver, 'driver'), 'stop'],
                               input=json.dumps({'run': run}), env=self.env(state), cwd=repo, capture_output=True,
                               text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e), ''
        return p.returncode, p.stdout, p.stderr

    def env(self, state):
        env = dict(os.environ)
        if self.a.driver in DRIVER_STATE:
            env[DRIVER_STATE[self.a.driver]] = state
        return env

    def run_kit(self, repo, state):
        cmd = [sys.executable, '-I', 'kernel/driver-kit/kit.py', '--driver', 'adapters/%s/driver' % self.a.driver,
               '--repo', self.a.repo, '--ticket', str(self.a.ticket), '--harness', self.a.harness, '--model',
               self.a.model, '--skill', self.a.skill, '--wait', str(self.a.wait)]
        t0 = time.monotonic()
        p = subprocess.Popen(cmd, cwd=repo, env=self.env(state), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        err = []
        reader = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True)
        reader.start()
        timer = threading.Timer(3 * self.a.wait + 900, p.kill)
        timer.start()
        lines, last = [], 0.0
        for raw in p.stdout:
            at = time.monotonic() - t0
            m = LINE.fullmatch(raw.rstrip('\n'))
            if m:
                lines.append({'check': m.group(2), 'verdict': m.group(1), 'what': redact(m.group(3)),
                              'at': at, 'took': at - last})
                last = at
        code = p.wait()
        timer.cancel()
        reader.join(10)
        self.kit = {'exit': code, 'lines': lines, 'seconds': time.monotonic() - t0,
                    'stderr': [redact(x.rstrip('\n')) for x in err if x.strip()][:20],
                    'killed': code == -9}

    def adapter(self):
        pkg = ADAPTERS.get(self.a.harness)
        found = glob.glob(os.path.expanduser('~/.npm/_npx/*/node_modules/%s/package.json' % pkg)) if pkg else []
        if found:
            try:
                with open(max(found, key=os.path.getmtime)) as f:
                    self.facts['adapter'] = '%s %s' % (pkg, json.load(f)['version'])
            except (OSError, ValueError, KeyError):
                pass

    def go(self):
        os.makedirs(self.home, mode=0o700, exist_ok=True)
        work = tempfile.mkdtemp(prefix='work-', dir=self.home)
        state = os.path.join(self.home, 'driver-state')
        repo = None
        try:
            repo = self.clone(work)
            self.offline(repo)
            skills = self.skills(repo)
            self.preflight()
            self.stop_notes(skills, 'before the run (an earlier run left it live)')
            before_refs = self.github_refs()
            before_work = set(glob.glob(os.path.join(state, 'work', 'run-*')))
            try:
                self.run_kit(repo, state)
            finally:
                self.tidy(self.tidy_driver, state, repo, before_work)
                self.tidy(self.stop_notes, skills, 'after the run')
                self.tidy(self.tidy_github, before_refs)
            self.adapter()
        except Blocked as e:
            self.blocked = str(e)
        except Exception as e:
            self.blocked = redact('the runner failed: %s: %s' % (type(e).__name__, e))
        finally:
            self.facts['seconds'] = time.monotonic() - self.clock
            self.body = self.receipt()
            self.privacy = self.checked(repo, self.body)
            shutil.rmtree(work, ignore_errors=True)

    def tidy(self, step, *args):
        try:
            step(*args)
        except Blocked as e:
            self.facts['cleanup'].append('cleanup step %s failed: %s' % (step.__name__, e))

    def verdicts(self):
        got = {x['check']: x for x in (self.kit or {}).get('lines', [])}
        return [(c, got[c]['verdict'] if c in got else 'missing') for c in CHECKS]

    def result(self):
        if self.blocked:
            return 'blocked: ' + self.blocked
        if self.kit['exit'] == 2:
            return 'the kit could not run'
        passed = sum(v == 'pass' for _, v in self.verdicts())
        return '%d of 5 pass' % passed

    def signature(self):
        norm = lambda s: re.sub(r'\d+', 'N', re.sub(r'run-[0-9a-f]{12}', 'run-<id>', s))
        kit = self.kit or {}
        return json.dumps({'blocked': norm(self.blocked or ''), 'offline': (self.facts.get('offline') or {}).get('ok'),
                           'exit': kit.get('exit'),
                           'checks': [(x['check'], x['verdict'], norm(x['what']) if x['verdict'] == 'fail' else '')
                                      for x in kit.get('lines', [])],
                           'stderr': [norm(x) for x in kit.get('stderr', []) if x.startswith('kit.py:')]},
                          sort_keys=True)

    def receipt(self):
        a, f, kit = self.a, self.facts, self.kit or {}
        out = ['### Live check: %s driver, %s: %s' % (a.driver, f['when'], self.result()), '']
        if 'main' in f:
            out.append('- **Driver:** `adapters/%s` at OpenWiz `main` `%s`; the driver last changed in `%s`'
                       % (a.driver, f['main'][:12], f['driver_commit'][:12]))
        via = ', '.join(x for x in ('acpx %s' % f['acpx'] if f.get('acpx') else '', f.get('adapter', '')) if x)
        out.append('- **Harness and model:** `%s`, `%s`%s' % (a.harness, a.model, ' (through %s)' % via if via else ''))
        out.append('- **Ticket:** %s#%d, skill `%s`%s, `--wait %d`'
                   % (a.repo, a.ticket, a.skill, ' from WizSkills %s' % f['wizskills'] if f.get('wizskills') else '',
                      a.wait))
        off = f.get('offline')
        if off:
            out.append('- **Offline tests:** %s, `python3 -I adapters/%s/test_driver.py`: %s%s (%s)'
                       % ('pass' if off['ok'] else 'fail', a.driver,
                          'ran %d, ' % off['ran'] if off['ran'] is not None else '', off['summary'],
                          took(off['seconds'])))
            if off['failed']:
                out.append('  - failing: ' + ', '.join('`%s`' % x for x in off['failed']))
        if self.blocked:
            out += ['', '**Blocked before the kit finished:** `%s`' % self.blocked.replace('`', "'")]
        if kit.get('lines') or kit.get('exit') is not None:
            out += ['', '| Check | Result | Took | At | The kit said |', '| --- | --- | --- | --- | --- |']
            got = {x['check']: x for x in kit['lines']}
            for c in CHECKS:
                x = got.get(c)
                out.append('| %s | %s | %s | %s | %s |' % ((c, x['verdict'], took(x['took']), took(x['at']),
                                                             x['what'].replace('|', '\\|')) if x else
                                                            (c, 'missing', '', '', 'the kit printed no line')))
            out += ['', 'Kit exit %d after %s%s.' % (kit['exit'], took(kit['seconds']),
                                                     ' (killed at its time limit)' if kit.get('killed') else '')]
            if kit['stderr']:
                out += ['', 'The kit on stderr:', '```text'] + kit['stderr'] + ['```']
        failures = [x for x in kit.get('lines', []) if x['verdict'] == 'fail']
        if failures:
            out += ['', '**Failures, exactly as the kit printed them:**', '```text']
            out += ['fail %s: %s' % (x['check'], x['what']) for x in failures] + ['```']
        out += ['', '- **Cleanup:** ' + ('; '.join(f['cleanup']) if f['cleanup'] else 'nothing to clean: no '
                                         'branch, pull request or live note was left')]
        for n in f['notes']:
            out.append('- **Note:** ' + n)
        out += ['- **Whole run:** %s' % took(self.facts.get('seconds', time.monotonic() - self.clock)), '',
                'Posted by `tools/live-rig/always-on/run.py` on an always-on box, every %d hours; a receipt comes when '
                'the result changes, or once a day.' % self.a.every]
        return redact('\n'.join(out)) + '\n'

    def checked(self, repo, body):
        if not repo or not os.path.isfile(os.path.join(repo, 'tools', 'privacy-check', 'check.py')):
            return None
        with tempfile.TemporaryDirectory() as tmp:
            title, text = os.path.join(tmp, 'title'), os.path.join(tmp, 'body')
            with open(title, 'w') as f:
                f.write('Live check receipt: %s driver\n' % self.a.driver)
            with open(text, 'w') as f:
                f.write(body)
            code, out, err = self.py(os.path.join(repo, 'tools', 'privacy-check', 'check.py'), '--title-file', title,
                                     '--body-file', text, timeout=120)
        return code == 0


def post(a, body):
    owner_repo, _, number = a.receipts.partition('#')
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as f:
        f.write(body)
    try:
        return must(['gh', 'issue', 'comment', number, '-R', owner_repo, '--body-file', f.name],
                    'posting the receipt', timeout=120).strip()
    finally:
        os.unlink(f.name)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(path, value):
    with open(path + '.new', 'w') as f:
        json.dump(value, f, indent=1)
    os.replace(path + '.new', path)


def main(argv):
    ap = argparse.ArgumentParser(prog='run.py', description='Run one driver kit live check and post its receipt.')
    ap.add_argument('--driver', default='openclaw')
    ap.add_argument('--repo', required=True)
    ap.add_argument('--ticket', type=int, required=True)
    ap.add_argument('--harness', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--skill', default='build-ticket')
    ap.add_argument('--wait', type=int, default=900)
    ap.add_argument('--receipts', required=True, help='owner/repo#N, the issue the receipts go to')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--every', type=int, default=6, help='the schedule, in hours, as the receipt says')
    ap.add_argument('--no-post', action='store_true', help='run and keep the receipt, but post nothing')
    ap.add_argument('--post-last', action='store_true', help='post the last kept receipt, if never posted')
    a = ap.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*', a.receipts):
        ap.error('--receipts must be owner/repo#N')
    home = os.path.join(a.root, a.driver)
    os.makedirs(os.path.join(home, 'receipts'), mode=0o700, exist_ok=True)
    os.umask(0o077)
    lock = open(os.path.join(home, 'lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('%s run.py: another run holds the lock; nothing done' % stamp(now()))
        return 0
    last_path, posted_path = os.path.join(home, 'last.json'), os.path.join(home, 'posted.json')
    if a.post_last:
        last = load(last_path)
        if not last or last.get('url'):
            print('run.py: no unposted receipt')
            return 1
        if last.get('privacy') is not True:
            print('run.py: the last receipt did not pass the privacy check, so it is not posted')
            return 1
        with open(last['receipt']) as f:
            url = post(a, f.read())
        save(last_path, dict(last, url=url))
        save(posted_path, {'signature': last['signature'], 'at': time.time(), 'url': url})
        print('run.py: posted %s' % url)
        return 0
    run = Run(a)
    run.go()
    body = run.body
    when = run.started.strftime('%Y%m%dT%H%M%SZ')
    receipt = os.path.join(home, 'receipts', when + '.md')
    with open(receipt, 'w') as f:
        f.write(body)
    signature, posted = run.signature(), load(posted_path)
    due = signature != posted.get('signature') or time.time() - posted.get('at', 0) >= DAY - 900
    url = None
    if due and not a.no_post:
        if run.privacy is True:
            try:
                url = post(a, body)
                save(posted_path, {'signature': signature, 'at': time.time(), 'url': url})
            except Blocked as e:
                print('run.py: %s' % e)
        else:
            print('run.py: %s, so it is not posted; read %s' % (
                'the receipt did not pass the privacy check' if run.privacy is False else
                'no privacy check could run without a clone of OpenWiz', receipt))
    save(last_path, {'signature': signature, 'receipt': receipt, 'privacy': run.privacy, 'url': url,
                     'at': time.time()})
    with open(os.path.join(home, 'runs.jsonl'), 'a') as f:
        f.write(json.dumps({'at': stamp(run.started), 'main': run.facts.get('main'), 'result': run.result(),
                            'seconds': round(run.facts['seconds']), 'posted': url}) + '\n')
    print('%s run.py: %s; %s' % (stamp(run.started), run.result(),
                                 'posted %s' % url if url else 'not posted (%s)' % ('due' if due else 'unchanged')))
    return 0 if run.result() == '5 of 5 pass' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
