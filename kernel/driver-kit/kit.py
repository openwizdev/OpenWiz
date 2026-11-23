#!/usr/bin/env python3
import argparse
import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import select
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_loader('records_kit', importlib.machinery.SourceFileLoader(
    'records_kit', os.path.join(HERE, '..', 'records-kit', 'check.py')))
records_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records_kit)
OVERRIDE = 'OPENWIZ_HOSTKEY_TEST_ORIGIN'
KEY_PATH = '/.openwiz/hostkey-test-key'
HOSTKEY = os.path.realpath(os.path.join(HERE, 'hostkey.py'))
SHOWN_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
PYTHON = re.compile(r'python3?(\.[0-9]+)?')
SAMPLE_SECONDS = 0.005
LOADER_PREFIXES = ('LD_', 'DYLD_')
TRUSTED_PYTHONS = {os.path.realpath(p) for p in (sys.executable, getattr(sys, '_base_executable', sys.executable))
                   if p and os.path.isabs(p) and os.path.isfile(p)}
PATH_ARGUMENT = ('/', './', '../', '~')
HIDDEN_TRIES, HIDDEN_PAUSE = 5, 0.01
KEYCHAIN_TOOLS = re.compile(rb'(?<![A-Za-z0-9_-])(security|secret-tool|find-generic-password)(?![A-Za-z0-9_-])')

SHAPES = re.compile(r'\b(?:[a-z_]*token|[a-z_]*key|secret|password|passwd|pwd|sig|signature|auth|credentials?)\s*='
                    r'|\b(?:password|passwd|secret|token)\s*:\s*\S|\bbearer\s+\S'
                    r'|\bgh[pousr]_[A-Za-z0-9]{8,}|\bgithub_pat_|\bAKIA[0-9A-Z]{16}\b'
                    r'|\bxox[abprs]-|\bsk-[A-Za-z0-9_-]{16,}'
                    r'|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}'
                    r'|xox[abposr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,}', re.I)
SECRETS = [v for k, v in os.environ.items()
           if re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY$|^KEY', k.upper()) and len(v) >= 8]
KEYWORDS = {'$schema', 'type', 'required', 'additionalProperties', 'properties', 'pattern', 'minLength',
            'maxLength', 'minimum', 'items', 'minItems', 'uniqueItems', 'enum', 'const', 'allOf', 'contains'}
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}
PROC = os.path.isdir('/proc/self')
PROBE = ['-I', '-c', "import sys; sys.stdout.write('.'); sys.stdout.flush(); sys.stdin.read()"]


class Unusable(Exception):
    pass


def _unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('a key is repeated')
    return dict(pairs)


def parse(text):
    return json.loads(text, object_pairs_hook=_unique)


def _known(s):
    if not isinstance(s, dict) or set(s) - KEYWORDS:
        raise Unusable('schema.json uses a keyword the kit does not check')
    for sub in list(s.get('properties', {}).values()) + s.get('allOf', []) + \
            [s[k] for k in ('items', 'contains') if k in s]:
        _known(sub)


def load_schema():
    with open(os.path.join(HERE, 'schema.json')) as f:
        schema = parse(f.read())
    for c in schema['commands'].values():
        for s in (c['input'], c['output']):
            if s is not None:
                _known(s)
    _known(schema['error'])
    return schema


def _same(a, b):
    return a == b and type(a) is type(b)


def invalid(value, s, at='the answer'):
    if 'const' in s and not _same(value, s['const']):
        return '%s is not %s' % (at, json.dumps(s['const']))
    if 'enum' in s and not any(_same(value, e) for e in s['enum']):
        return '%s is not one of %s' % (at, ', '.join(map(json.dumps, s['enum'])))
    t = s.get('type')
    if t and not (type(value) is int if t == 'integer' else type(value) is TYPES[t]):
        return '%s is not a%s %s' % (at, 'n' if t[0] in 'aeiou' else '', t)
    if isinstance(value, str):
        if not s.get('minLength', 0) <= len(value) <= s.get('maxLength', len(value)):
            return '%s has the wrong length' % at
        p = s.get('pattern')
        if p and not re.search(p[:-1] + r'\Z' if p.endswith('$') else p, value):
            return '%s does not match %s' % (at, p)
    if t == 'integer' and value < s.get('minimum', value):
        return '%s is below %s' % (at, s['minimum'])
    if isinstance(value, list):
        if len(value) < s.get('minItems', 0):
            return '%s has too few items' % at
        if s.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            return '%s repeats an item' % at
        for v in value if 'items' in s else []:
            why = invalid(v, s['items'], 'an item of ' + at)
            if why:
                return why
        if 'contains' in s and not any(invalid(v, s['contains']) is None for v in value):
            return '%s lacks %s' % (at, json.dumps(s['contains'].get('const', s['contains'])))
    if isinstance(value, dict):
        for k in s.get('required', []):
            if k not in value:
                return '%s lacks %s' % (at, k)
        if s.get('additionalProperties') is False and set(value) - set(s.get('properties', {})):
            return '%s has an unknown field %s' % (at, sorted(set(value) - set(s['properties']))[0])
        for k, sub in s.get('properties', {}).items():
            why = k in value and invalid(value[k], sub, k)
            if why:
                return why
    for sub in s.get('allOf', []):
        why = invalid(value, sub, at)
        if why:
            return why
    return None


def records_version():
    with open(os.path.join(HERE, '..', 'records.v1.md')) as f:
        m = re.search(r'\(`(openwiz:records v[0-9]+)`\)', f.readline())
    if not m:
        raise Unusable('records.v1.md names no records version')
    return m.group(1)


def texts(value):
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            yield from v
            stack += v.values()
        elif isinstance(v, list):
            stack += v


def holds_credential(text):
    return bool(SHAPES.search(text)) or any(v in text for v in SECRETS)


def shown(name, *values):
    if SHOWN_NAME.fullmatch(name) and not holds_credential(name) and not any(v in name for v in values):
        return name
    return 'a variable the kit does not name'


FLEET = """query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {
  object(expression: "HEAD:docs/agents/fleet.md") { ... on Blob { text } } } }"""


class Request(tuple):
    phase = None


class FakeHost:
    def __init__(self, status=200, headers=(), body=b'{}', answers=(), test_key=None, trust=None, phase=None):
        self.requests, self.fetches = [], []
        self.lock = threading.Lock()
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self):
                try:
                    size = int(self.headers.get('Content-Length') or 0)
                except ValueError:
                    size = 0
                sent = self.rfile.read(size)
                code, data = status, body
                if self.path == KEY_PATH:
                    given = test_key is not None and self.command == 'GET' and (
                        trust is None or trust(self.client_address[1]))
                    with host.lock:
                        host.fetches.append(given)
                    code, data = (200, json.dumps({'key': test_key}).encode()) if given else (404, b'{}')
                else:
                    record = Request((self.requestline, list(self.headers.items()), sent))
                    record.phase = phase() if phase else None
                    with host.lock:
                        host.requests.append(record)
                    for a in answers:
                        if a['method'] == self.command and re.fullmatch(a['path'], self.path.partition('?')[0]):
                            code, data = a['status'], json.dumps(a['body']).encode()
                            break
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = answer

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Ticket:
    def __init__(self, repo, number, tracker):
        self.repo, self.number, self.tracker = repo, number, tracker
        self.poll = 0.05 if tracker else 10
        if tracker:
            self.authors = self._file()['record_authors']
        else:
            owner, _, name = repo.partition('/')
            blob = records_kit._graphql(FLEET, owner=owner, name=name)['object']
            rows = [x for x in (blob or {}).get('text', '').splitlines() if x.startswith('| Record authors |')]
            self.authors = re.findall(r'`([^`]+)`', rows[0]) if len(rows) == 1 else []
            if not self.authors:
                raise Unusable('%s has no single Record authors row in docs/agents/fleet.md' % repo)
        self.authors = {a.lower() for a in self.authors}

    def _file(self):
        try:
            with open(self.tracker) as f:
                t = records_kit._object(parse(f.read()), ('record_authors', 'comments'), 'the tracker')
            for a in records_kit._list(t['record_authors'], 'record_authors'):
                records_kit._str(a, 'a record author')
            for c in records_kit._list(t['comments'], 'comments'):
                records_kit._object(c, ('id', 'author', 'updated_at', 'body'), 'a comment')
                records_kit._int(c['id'], 'a comment id')
                records_kit._str(c['author'], 'a comment author')
                records_kit._time(c['updated_at'], 'a comment time')
                records_kit._str(c['body'], 'a comment body')
            return t
        except (OSError, ValueError, records_kit.Unreadable) as e:
            raise Unusable('cannot read the tracker: %s' % e)

    def comments(self):
        if self.tracker:
            return self._file()['comments']
        owner, _, name = self.repo.partition('/')
        found, after = [], None
        while True:
            try:
                page = records_kit._graphql(records_kit.COMMENTS % records_kit.COMMENT, owner=owner, name=name,
                                            number=self.number, after=after)['issue']['comments']
                found += [records_kit._comment(c) for c in page['nodes']]
            except (KeyError, TypeError) as e:
                raise Unusable('GitHub gave an unreadable answer: %s' % e)
            if not page['pageInfo']['hasNextPage']:
                return found
            after = page['pageInfo']['endCursor']

    def builder_notes(self):
        notes = {}
        for c in self.comments():
            if c['author'].lower() in self.authors and c['body'].split('\n', 1)[0].rstrip('\r') == records_kit.MARKER:
                fields = records_kit.read_note(c['body'])
                if fields and fields['agent'] == 'builder':
                    notes[c['id']] = (c['updated_at'], c['body'], fields)
        return notes


class Kit:
    def __init__(self, args, ticket):
        self.args, self.ticket, self.schema = args, ticket, load_schema()
        self.mark = 'OPENWIZ_KIT_RUN=' + secrets.token_hex(8)
        self.env = dict(os.environ, OPENWIZ_KIT_RUN=self.mark.partition('=')[2])
        self.leaks = []
        self.groups = set()
        self.lock = threading.RLock()
        self.runtime, self.listed_pids, self.active = set(), set(), set()
        self.seen = PROC
        self.blind = None if PROC else self.unseen()

    def leak(self, what):
        with self.lock:
            if what not in self.leaks:
                self.leaks.append(what)

    def call(self, cmd, request=None, env=None, canary=None):
        try:
            p = subprocess.run([self.args.driver, cmd], input='' if request is None else json.dumps(request),
                               env=env or self.env, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 'bad', '%s did not finish: %s' % (cmd, e)
        if canary and canary[1] in p.stdout + p.stderr:
            # SECURITY: the kit's key canary; nothing of this output is shown.
            self.leak('the driver printed the %s key' % canary[0])
            return 'bad', 'its %s output held the key' % cmd
        if holds_credential(p.stdout + p.stderr):
            self.leak('the driver printed a credential')
        held = 'bad', 'its %s output held a credential, which the kit does not show' % cmd
        if holds_credential(p.stdout):
            # SECURITY: nothing of it is parsed or shown; any part could carry the credential into the kit's output.
            return held
        try:
            out = parse(p.stdout)
        except ValueError:
            return 'bad', '%s printed no single JSON value' % cmd
        if any(holds_credential(text) for text in texts(out)):
            self.leak('the driver printed a credential')
            return held
        if p.returncode not in (0, 1):
            return 'bad', '%s exited %d' % (cmd, p.returncode)
        kind, s = ('ok', self.schema['commands'][cmd]['output']) if p.returncode == 0 else ('refused', self.schema['error'])
        why = invalid(out, s, 'its %s %s' % (cmd, 'answer' if kind == 'ok' else 'error'))
        return ('bad', why) if why else (kind, out)

    def started(self):
        if not PROC:
            yield from self.listed()
            return
        table = self.table()
        for pid, (ppid, uid, env, cmd) in table.items():
            if env is not None and self.mark in env:
                yield cmd, env
        for pid, (ppid, uid, env, cmd) in table.items():
            if env is None and uid == os.getuid() and self.under_run(table, ppid):
                self.leak('a process of the driver hides its details, so the kit cannot check it')

    def table(self):
        found = {}
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/stat' % pid) as f:
                    state, ppid = f.read().rpartition(')')[2].split()[:2]
                ppid = int(ppid)
                with open('/proc/%s/status' % pid) as f:
                    uid = int(next(row for row in f if row.startswith('Uid:')).split()[1])
            except (OSError, ValueError, IndexError, StopIteration):
                continue
            try:
                env, cmd = self.details(pid)
            except PermissionError:
                if state in 'ZX' or not self.running(pid):
                    continue
                env = cmd = None
            except OSError:
                continue
            found[pid] = (ppid, uid, env, cmd)
        return found

    @staticmethod
    def details(pid, tries=HIDDEN_TRIES):
        for attempt in range(tries):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    env = f.read().decode('utf-8', 'replace').split('\0')
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    return env, f.read().decode('utf-8', 'replace').split('\0')
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(HIDDEN_PAUSE)

    @staticmethod
    def folder_of(pid, tries=HIDDEN_TRIES):
        for attempt in range(tries):
            try:
                return os.readlink('/proc/%s/cwd' % pid)
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(HIDDEN_PAUSE)

    @staticmethod
    def running(pid):
        try:
            with open('/proc/%s/stat' % pid) as f:
                return f.read().rpartition(')')[2].split()[0] not in 'ZX'
        except OSError:
            return False

    def under_run(self, table, pid):
        seen = set()
        while str(pid) in table and pid not in seen:
            seen.add(pid)
            ppid, _, env, _ = table[str(pid)]
            if env is not None and self.mark in env:
                return True
            pid = ppid
        return False

    @staticmethod
    def ps(*args):
        try:
            p = subprocess.run(['ps', '-A', '-ww', '-o', 'pid='] + list(args), stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Unusable('ps did not run: %s' % e)
        if p.returncode:
            raise Unusable('ps failed: %s' % p.stderr.strip()[:200])
        return {int(pid): rest for pid, _, rest in (row.strip().partition(' ') for row in p.stdout.splitlines())}

    def unseen(self):
        probe = 'OPENWIZ_KIT_PROBE=' + self.mark.partition('=')[2]
        p = subprocess.Popen([sys.executable] + PROBE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             env=dict(os.environ, OPENWIZ_KIT_PROBE=probe.partition('=')[2]))
        try:
            ready = select.select([p.stdout], [], [], 30)[0] and os.read(p.stdout.fileno(), 1) == b'.'
            if ready and re.search(r'(?:^|\s)%s(?:\s|$)' % re.escape(probe),
                                   self.ps('-o', 'command=', '-E').get(p.pid, '')):
                return None
        finally:
            p.stdin.close()
            p.kill()
            p.wait()
            p.stdout.close()
        return "ps shows no process's environment here, so the kit cannot tell which processes the driver started"

    def listed(self):
        args = self.ps('-o', 'pgid=', '-o', 'stat=', '-o', 'command=')
        full = self.ps('-o', 'command=', '-E')
        mark = re.compile(r'(?:^|\s)%s(?:\s|$)' % re.escape(self.mark))
        found = []
        for pid, row in args.items():
            f = row.split(None, 2)
            if len(f) < 2 or f[1].startswith('Z') or pid == os.getpid():
                continue
            group, cmd = int(f[0]), f[2] if len(f) > 2 else ''
            words = full.get(pid, '').strip()
            text = ' ' + (words[len(cmd):] if words.startswith(cmd) else words)
            marked = bool(mark.search(text))
            self.seen = self.seen or marked
            if marked and group != os.getpgrp():
                self.groups.add(group)
            found.append((pid, (group, cmd, text, marked)))
        for pid, (group, cmd, text, marked) in found:
            if marked or group in self.groups:
                self.listed_pids.add(pid)
                for k, v in self.env.items():
                    text = re.sub(r'(?<=\s)%s(?=\s|$)' % re.escape('%s=%s' % (k, v)), '', text)
                yield [cmd], [e.strip() for e in re.split(r'\s(?=[A-Za-z_][A-Za-z0-9_]*=)', text) if e.strip()]

    def unverified(self):
        if self.blind or self.seen:
            return self.blind
        return 'ps -E never showed a process of this run, so the kit cannot tell which processes the driver started'

    def commandlines(self):
        if not PROC:
            return list(self.ps('-o', 'command=').values())
        found = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    found.append(f.read().decode('utf-8', 'replace'))
            except OSError:
                continue
        return found

    def scan(self, canary=None):
        with self.lock:
            self._scan(canary)

    def run_processes(self):
        if PROC:
            for pid, (_, _, env, cmd) in self.table().items():
                if env is None or self.mark not in env:
                    continue
                try:
                    cwd = self.folder_of(pid)
                except PermissionError:
                    if self.running(pid):
                        self.leak('a process of the driver hides its details, so the kit cannot check it')
                    continue
                except OSError:
                    continue
                yield cmd[:-1], cwd
            return
        rows = self.ps('-o', 'command=')
        for pid in sorted(self.listed_pids):
            if pid not in rows:
                continue
            cwd = self.process_cwd(pid)
            if cwd is None:
                if not self.ps('-o', 'stat=').get(pid, 'Z').strip().startswith('Z'):
                    self.leak('the kit could not resolve a file a process of the driver ran, so it cannot check it')
                continue
            yield rows[pid], cwd

    def collect_runtime(self):
        for argv, cwd in self.run_processes():
            for path in (self.argument_files(argv, cwd) if isinstance(argv, list) else self.text_files(argv, cwd)):
                self.runtime.add(os.path.realpath(path))

    def argument_files(self, argv, cwd):
        for a in argv[1:]:
            path = os.path.join(cwd, os.path.expanduser(a))
            if a and os.path.isfile(path):
                yield path
            elif a.startswith(PATH_ARGUMENT) and not os.path.isdir(path):
                self.leak('the kit could not resolve a file a process of the driver ran, so it cannot check it')

    def text_files(self, text, cwd):
        words, i = text.split(' '), 1
        while i < len(words):
            pathlike = words[i].startswith(PATH_ARGUMENT)
            found = next(((j, path) for j in range(len(words) if pathlike else i + 1, i, -1)
                          for path in [os.path.join(cwd, os.path.expanduser(' '.join(words[i:j])))]
                          if os.path.exists(path)), None)
            if found:
                if os.path.isfile(found[1]):
                    yield found[1]
                i = found[0]
                continue
            if pathlike:
                self.leak('the kit could not resolve a file a process of the driver ran, so it cannot check it')
            i += 1

    def _scan(self, canary):
        if canary:
            name, value = canary
            if any(value in line for line in self.commandlines()):
                self.leak('a process holds the %s key on its command line' % name)
            for cmd, env in self.started():
                for entry in env:
                    if value in entry:
                        self.leak('a process the driver started holds the %s key in %s'
                                  % (name, shown(entry.partition('=')[0], value)))
            self.collect_runtime()
        for cmd, env in self.started():
            if any(holds_credential(a) for a in cmd):
                self.leak('a process the driver started holds a credential on its command line')
            for entry in env:
                name, _, value = entry.partition('=')
                if holds_credential(value) and os.environ.get(name) != value:
                    self.leak('a process the driver started holds a credential in %s, which the kit never gave it'
                              % shown(name))

    def wait(self, ready, canary=None):
        end = time.monotonic() + self.args.wait
        while True:
            self.scan(canary)
            found = ready()
            if found or time.monotonic() > end:
                return found
            time.sleep(self.ticket.poll)

    def version(self):
        records = records_version()
        kind, v = self.call('version')
        if kind != 'ok':
            return 'fail', v['error'] if kind == 'refused' else v
        if records not in v['records']:
            return 'fail', 'it names no ' + records
        kind, s = self.call('schema')
        if kind != 'ok':
            return 'fail', s['error'] if kind == 'refused' else s
        if s != self.schema:
            return 'fail', 'its schema is not kernel/driver-kit/schema.json'
        return 'pass', '%s, and the schema is driver v1' % records

    def start(self):
        before = set(self.ticket.builder_notes())
        a = self.args
        kind, v = self.call('start', {'repository': a.repo, 'ticket': a.ticket, 'skill': a.skill,
                                      'harness': a.harness, 'model': a.model})
        if kind != 'ok':
            return 'fail', v['error'] if kind == 'refused' else v
        self.run = v['run']
        new = self.wait(lambda: sorted(set(self.ticket.builder_notes()) - before))
        if not new:
            return 'fail', 'no builder status note appeared within %d seconds' % a.wait
        if len(new) > 1:
            return 'fail', 'the run posted %d builder notes; it keeps one' % len(new)
        self.note = new[0]
        fields = self.ticket.builder_notes()[self.note][2]
        if fields['state'] not in ('working', 'asking'):
            return 'fail', 'builder status note %d is %s, not live' % (self.note, fields['state'])
        if a.skill not in [s.partition('@')[0] for s in fields['skills'].split(', ')]:
            return 'fail', 'builder status note %d does not name the %s skill' % (self.note, a.skill)
        return 'pass', 'the run posted builder status note %d' % self.note

    def wake(self):
        notes = self.ticket.builder_notes()
        kind, v = self.call('wake', {'run': self.run})
        if kind != 'ok':
            return 'fail', v['error'] if kind == 'refused' else v
        if v['run'] != self.run:
            return 'fail', 'it answered for another run'
        changed = self.wait(lambda: {i: n for i, n in self.ticket.builder_notes().items()
                                     if i not in notes or (i == self.note and n[:2] != notes[i][:2])})
        if set(changed or {}) - {self.note}:
            return 'fail', 'the wake posted another builder note; a run keeps one'
        if not changed:
            return 'fail', 'builder status note %d did not change after the wake' % self.note
        return 'pass', 'the run edited builder status note %d' % self.note

    def stop(self):
        kind, v = self.call('stop', {'run': self.run})
        if self.unverified():
            return 'fail', self.unverified()
        if kind != 'ok':
            return 'fail', v['error'] if kind == 'refused' else v
        if v['run'] != self.run:
            return 'fail', 'it answered for another run'
        kind, v = self.call('wake', {'run': self.run})
        if kind == 'ok':
            return 'fail', 'a wake after stop was taken'
        if kind == 'bad':
            return 'fail', v
        if not self.wait(lambda: not any(True for _ in self.started())):
            return 'fail', 'a process the run started still runs after stop'
        return 'pass', 'the run ended, and a wake after it is refused'

    def token(self):
        a = self.args
        kind, v = self.call('start', {'repository': a.repo, 'ticket': a.ticket, 'skill': a.skill,
                                      'harness': a.harness, 'model': a.model, 'token': 'kit-probe-not-a-login'})
        if kind == 'ok':
            self.call('stop', {'run': v['run']})
            self.leak('start took a token field instead of refusing it')
        elif kind == 'bad':
            self.leak('its answer to a token field: ' + v)
        hosts = self.key_hosts()
        for name in hosts:
            self.key_check(name, self.hosts[name])
        self.scan()
        if self.unverified():
            self.leak(self.unverified())
        if self.leaks:
            return 'fail', '; '.join(self.leaks)
        return 'pass', 'no login or token passed through the driver' + ''.join(
            ", and on start, wake and stop the %s key reached its host only from the key helper, in its header" % name
            for name in hosts)

    def key_hosts(self):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(self.args.driver)), 'README.md'), 'rb') as f:
                text = f.read().decode('utf-8')
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as e:
            raise Unusable("cannot read the driver's README.md: %s" % type(e).__name__)
        try:
            spec = importlib.util.spec_from_loader('hostkey', importlib.machinery.SourceFileLoader(
                'hostkey', os.path.join(HERE, 'hostkey.py')))
            hostkey = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hostkey)
            self.hosts = hostkey.registry()
        except OSError:
            raise Unusable('the key helper kernel/driver-kit/hostkey.py is missing, so the kit cannot check host keys')
        except hostkey.Refused as e:
            raise Unusable(e.args[0])
        return [n for n in sorted(self.hosts)
                if re.search(r'(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])' % re.escape(n), text, re.I)]

    def driver_files(self):
        top = os.path.dirname(os.path.abspath(self.args.driver))

        def unreadable(e):
            raise e
        seen = set()
        for folder, subs, names in os.walk(top, onerror=unreadable, followlinks=True):
            real = os.path.realpath(folder)
            if real in seen:
                subs[:] = []
                continue
            seen.add(real)
            subs.sort()
            for n in sorted(names):
                yield os.path.join(folder, n)

    def names_key(self, path, entry, readme=False):
        with open(path, 'rb') as f:
            data = f.read()
        variable, keychain = entry['variable'].encode(), entry['keychain'].encode()
        if readme:
            data = b'\n'.join(line.replace(variable, b'', 1).replace(keychain, b'', 1)
                              if variable in line and keychain in line else line for line in data.split(b'\n'))
        found = []
        if entry['variable'].encode() in data:
            found.append("names %s, the key's variable" % entry['variable'])
        tool = KEYCHAIN_TOOLS.search(data)
        if tool:
            found.append('calls the keychain tool %s' % tool.group(1).decode())
        return found

    def shown_path(self, path):
        return path.isprintable() and not holds_credential(path) and not any(v in path for v in self.active)

    def file_check(self, entry):
        top = os.path.dirname(os.path.abspath(self.args.driver))
        try:
            for path in self.driver_files():
                rel = os.path.relpath(path, top)
                for what in self.names_key(path, entry, rel == 'README.md'):
                    self.leak("the driver's file %s %s" % (rel, what) if self.shown_path(rel) else
                              "a file of the driver, which the kit does not name, %s" % what)
        except OSError:
            self.leak('the kit could not read every file of the driver, so it cannot check them')

    def runtime_check(self, entry):
        top = os.path.realpath(os.path.dirname(os.path.abspath(self.args.driver)))
        for path in sorted(self.runtime):
            real = os.path.realpath(path)
            if real == HOSTKEY or real.startswith(top + os.sep):
                continue
            try:
                found = self.names_key(real, entry)
            except OSError:
                self.leak('the kit could not read a file a process of the driver ran, so it cannot check it')
                continue
            rel = os.path.relpath(real, top)
            for what in found:
                self.leak('the file %s, which a process of the driver ran, %s' % (rel, what)
                          if self.shown_path(rel) else
                          'a file a process of the driver ran, which the kit does not name, %s' % what)

    def lifecycle(self):
        path = os.path.join(os.path.dirname(os.path.abspath(self.args.driver)), 'fixtures', 'kit-host.json')
        try:
            with open(path) as f:
                answers = records_kit._object(parse(f.read()), ('answers',), 'kit-host.json')['answers']
            for a in records_kit._list(answers, 'answers'):
                records_kit._object(a, ('method', 'path', 'status', 'body'), 'an answer')
                if a['method'] not in ('GET', 'POST', 'DELETE') or not isinstance(a['path'], str) or not (
                        type(a['status']) is int and 100 <= a['status'] <= 599):
                    raise ValueError('an answer is not a method, a path pattern and a status')
                re.compile(a['path'])
            return answers
        except FileNotFoundError:
            return []
        except (OSError, ValueError, re.error, records_kit.Unreadable) as e:
            raise Unusable("cannot read the driver's fixtures/kit-host.json: %s" % e)

    def peer(self, port, server):
        if not PROC:
            try:
                out = subprocess.run(['lsof', '-nP', '-a', '-iTCP:%d' % port, '-sTCP:ESTABLISHED', '-F', 'pn'],
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30).stdout
            except (OSError, subprocess.TimeoutExpired):
                return None, None
            pid = None
            for field in out.splitlines():
                if field[:1] == 'p':
                    pid = field[1:]
                elif field == 'n127.0.0.1:%d->127.0.0.1:%d' % (port, server) and pid and pid.isdigit():
                    row = self.ps('-o', 'command=').get(int(pid))
                    return (int(pid), row.split(' ')) if row is not None else (None, None)
            return None, None
        inode = None
        try:
            with open('/proc/net/tcp') as f:
                for row in f.read().splitlines()[1:]:
                    fields = row.split()
                    if int(fields[1].split(':')[1], 16) == port and int(fields[2].split(':')[1], 16) == server:
                        inode = fields[9]
        except (OSError, ValueError, IndexError):
            return None, None
        for pid in filter(str.isdigit, os.listdir('/proc')) if inode else ():
            try:
                fds = os.listdir('/proc/%s/fd' % pid)
                if any(os.readlink('/proc/%s/fd/%s' % (pid, fd)) == 'socket:[%s]' % inode for fd in fds):
                    with open('/proc/%s/cmdline' % pid, 'rb') as f:
                        return int(pid), f.read().decode('utf-8', 'replace').split('\0')[:-1]
            except OSError:
                continue
        return None, None

    def trusted_helper(self, port, server):
        pid, argv = self.peer(port, server)
        if pid is None or not argv or len(argv) != 3 or argv[1] != '-I' or not PYTHON.fullmatch(
                os.path.basename(argv[0])):
            return False
        cwd, exe, names = self.process_cwd(pid), self.executable(pid), self.environment_names(pid)
        if cwd is None or exe is None or names is None:
            return False
        return os.path.realpath(os.path.join(cwd, argv[2])) == HOSTKEY and os.path.realpath(exe) in TRUSTED_PYTHONS \
            and not any(n.startswith(LOADER_PREFIXES) for n in names)

    @staticmethod
    def lsof_name(pid, kind):
        try:
            out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', kind, '-Fn'], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        return next((f[1:] for f in out.splitlines() if f[:1] == 'n'), None)

    def process_cwd(self, pid):
        if not PROC:
            return self.lsof_name(pid, 'cwd')
        try:
            return os.readlink('/proc/%d/cwd' % pid)
        except OSError:
            return None

    def executable(self, pid):
        if not PROC:
            return self.lsof_name(pid, 'txt')
        try:
            return os.readlink('/proc/%d/exe' % pid)
        except OSError:
            return None

    def environment_names(self, pid):
        if not PROC:
            try:
                row = self.ps('-o', 'command=', '-E').get(pid)
            except Unusable:
                return None
            if row is None or not re.search(r'(?:^|\s)%s(?:\s|$)' % re.escape(self.mark), row):
                return None
            return set(re.findall(r'(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=', row))
        try:
            with open('/proc/%d/environ' % pid, 'rb') as f:
                return {e.partition(b'=')[0].decode('utf-8', 'replace') for e in f.read().split(b'\0') if e}
        except OSError:
            return None

    def sampled(self, cmd, request, env, canary):
        stop = threading.Event()

        def watch():
            try:
                self.scan(canary)
            except Exception:
                self.leak("the kit's process watch failed, so it cannot check the driver")
                stop.set()

        def sample():
            while not stop.wait(SAMPLE_SECONDS):
                watch()
        watcher = threading.Thread(target=sample, daemon=True)
        watcher.start()
        try:
            return self.call(cmd, request, env, canary)
        finally:
            failed = stop.is_set()
            stop.set()
            watcher.join()
            if not failed:
                watch()

    def key_check(self, name, entry):
        self.file_check(entry)
        canary = (name, 'kit-canary-' + secrets.token_hex(16))
        self.active.add(canary[1])
        phase, server = {'now': None}, []
        host = FakeHost(answers=self.lifecycle(), test_key=canary[1], phase=lambda: phase['now'],
                        trust=lambda port: self.trusted_helper(port, server[0]))
        server.append(host.server.server_address[1])
        env = {k: v for k, v in self.env.items() if k != entry['variable']}
        env[OVERRIDE] = host.origin
        a = self.args
        try:
            phase['now'] = 'start'
            kind, v = self.sampled('start', {'repository': a.repo, 'ticket': a.ticket, 'skill': a.skill,
                                             'harness': a.harness, 'model': a.model}, env, canary)
            run = v['run'] if kind == 'ok' else 'kit-key-run'
            for op in ('wake', 'stop'):
                phase['now'] = op
                self.sampled(op, {'run': run}, env, canary)
            phase['now'] = None
            self.wait(lambda: not any(True for _ in self.started()), canary)
        except Exception:
            self.leak("the kit's process watch failed, so it cannot check the driver")
            kind = 'bad'
        finally:
            host.close()
        self.runtime_check(entry)
        with host.lock:
            fetches, requests = list(host.fetches), list(host.requests)
        if not all(fetches):
            self.leak("a process that is not the key helper asked the kit's fake host for the key")
        sent = {'start': 0, 'wake': 0, 'stop': 0}
        for request in requests:
            line, headers, body = request
            rest = line + ''.join('%s: %s' % (k, v) for k, v in headers if k.lower() != 'authorization')
            if canary[1] in rest + body.decode('utf-8', 'replace'):
                self.leak("the %s key reached the kit's fake host outside the helper's Authorization header" % name)
            if [v for k, v in headers if k.lower() == 'authorization'] != ['Bearer ' + canary[1]]:
                self.leak("a request reached the kit's fake host without the %s key in the helper's header" % name)
            elif request.phase in sent:
                sent[request.phase] += 1
        if not requests:
            self.leak("the %s key never reached the kit's fake host" % name)
        elif kind != 'ok':
            self.leak("start failed against the kit's fake host, so the kit could not check wake and stop")
        else:
            for op, count in sent.items():
                if not count:
                    self.leak("%s sent the kit's fake host no request through the key helper" % op)

    def checks(self):
        yield 'version', self.version()
        result = self.start()
        yield 'start', result
        for name in ('wake', 'stop'):
            yield name, getattr(self, name)() if result[0] == 'pass' else ('fail', 'not run: start failed')
        yield 'token', self.token()


def main(argv):
    ap = argparse.ArgumentParser(prog='kit.py')
    for name in ('--driver', '--repo', '--harness', '--model'):
        ap.add_argument(name, required=True)
    ap.add_argument('--ticket', type=int, required=True)
    ap.add_argument('--skill', default='build-ticket')
    ap.add_argument('--tracker', help='a local throwaway tracker file, read instead of GitHub')
    ap.add_argument('--wait', type=int, default=900, help='seconds to wait for each note change')
    args = ap.parse_args(argv)
    failed = False
    try:
        kit = Kit(args, Ticket(args.repo, args.ticket, args.tracker))
        for name, (verdict, what) in kit.checks():
            print('%s %s: %s' % (verdict, name, what), flush=True)
            failed = failed or verdict == 'fail'
    except (Unusable, records_kit.Unreadable) as e:
        print('kit.py: %s' % e, file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
