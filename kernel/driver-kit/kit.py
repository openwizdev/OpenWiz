#!/usr/bin/env python3
"""The driver v1 test kit: run the five checks against one driver on a throwaway ticket.

    kit.py --driver <program> --repo <owner>/<name> --ticket <n> --harness <h> --model <m>
           [--skill <skill>] [--wait <seconds>] [--tracker <file>]

Prints one line per check, `pass <check>: ...` or `fail <check>: ...`, in the order version, start,
wake, stop, token. Exit 0: all five pass; 1: a check failed; 2: the kit could not run. It never
writes to GitHub: the agent the driver starts writes its own status note. Linux: it watches /proc.
The rules are kernel/driver.v1.md's.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_loader('records_kit', importlib.machinery.SourceFileLoader(
    'records_kit', os.path.join(HERE, '..', 'records-kit', 'check.py')))
records_kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records_kit)

# Known credential shapes: the pinned status contract's credential rules, as its writer
# (skills/launch-fleet/scripts/status.py at that commit) recognises them, then the kit's earlier shapes; and any
# value of the kit's own environment whose name says it is a secret.
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


class Unusable(Exception):
    pass


def _unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('a key is repeated')
    return dict(pairs)


def parse(text):
    """One JSON object or value, refusing a repeated key (ValueError)."""
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
    """Why value breaks the JSON Schema s, or None. It reads only KEYWORDS, as JSON Schema means them."""
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
    """The records version this kernel implements, from records.v1.md's title."""
    with open(os.path.join(HERE, '..', 'records.v1.md')) as f:
        m = re.search(r'\(`(openwiz:records v[0-9]+)`\)', f.readline())
    if not m:
        raise Unusable('records.v1.md names no records version')
    return m.group(1)


def texts(value):
    """Every string and object key inside a decoded JSON value."""
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


FLEET = """query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {
  object(expression: "HEAD:docs/agents/fleet.md") { ... on Blob { text } } } }"""


class Ticket:
    """The throwaway ticket's comments, from a local tracker file or from GitHub. Reads only."""

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
        """{comment id: (updated_at, body, fields)} for every record author's v1 builder note."""
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

    def leak(self, what):
        if what not in self.leaks:
            self.leaks.append(what)

    def call(self, cmd, request=None):
        """('ok', answer), ('refused', error) or ('bad', why), each checked against schema.json."""
        try:
            p = subprocess.run([self.args.driver, cmd], input='' if request is None else json.dumps(request),
                               env=self.env, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 'bad', '%s did not finish: %s' % (cmd, e)
        if holds_credential(p.stdout + p.stderr):
            self.leak('the driver printed a credential')
        held = 'bad', 'its %s output held a credential, which the kit does not show' % cmd
        if holds_credential(p.stdout):
            # Nothing of it is parsed or shown: any part could carry the credential into the kit's output.
            return held
        try:
            out = parse(p.stdout)
        except ValueError:
            return 'bad', '%s printed no single JSON value' % cmd
        if any(holds_credential(text) for text in texts(out)):
            # Decoding can restore what the JSON text escaped (a \u escape): check every decoded string and key too.
            self.leak('the driver printed a credential')
            return held
        if p.returncode not in (0, 1):
            return 'bad', '%s exited %d' % (cmd, p.returncode)
        kind, s = ('ok', self.schema['commands'][cmd]['output']) if p.returncode == 0 else ('refused', self.schema['error'])
        why = invalid(out, s, 'its %s %s' % (cmd, 'answer' if kind == 'ok' else 'error'))
        return ('bad', why) if why else (kind, out)

    def started(self):
        """(command line, environment) of every live process the driver started (they carry the kit's mark)."""
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    env = f.read().decode('utf-8', 'replace').split('\0')
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    cmd = f.read().decode('utf-8', 'replace').split('\0')
            except OSError:
                continue
            if self.mark in env:
                yield cmd, env

    def scan(self):
        for cmd, env in self.started():
            if any(holds_credential(a) for a in cmd):
                self.leak('a process the driver started holds a credential on its command line')
            for entry in env:
                name, _, value = entry.partition('=')
                if holds_credential(value) and os.environ.get(name) != value:
                    self.leak('a process the driver started holds a credential in %s, which the kit never gave it' % name)

    def wait(self, ready):
        """ready()'s first true value within --wait seconds, scanning the driver's processes meanwhile."""
        end = time.monotonic() + self.args.wait
        while True:
            self.scan()
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
        self.scan()
        if self.leaks:
            return 'fail', '; '.join(self.leaks)
        return 'pass', 'no login or token passed through the driver'

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
        if not os.path.isdir('/proc/self'):
            raise Unusable("the kit needs Linux's /proc to watch the processes a driver starts")
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
