#!/usr/bin/env python3
import argparse
import datetime
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, '..', '..'))
KIT = os.path.join(HERE, '..', 'driver-kit', 'kit.py')
RIG = os.path.join(HERE, 'rig.py')
HOST_FOLDERS = ('kernel/live-rig/hosts', 'kernel/live-rig/vps/hosts')
LISTINGS = os.path.join(HERE, 'listings.json')
REPO = 'openwizdev/OpenWiz'
KEYS = {'host', 'harness', 'model', 'date', 'driver_commit', 'kit_commit', 'outcome', 'skipped', 'kit_exit',
        'stdout', 'seconds'}
CHECKS = ('version', 'start', 'wake', 'stop', 'token')
KIT_PASS = {'version': 'pass version: openwiz:records v1, and the schema is driver v1',
            'stop': 'pass stop: the run ended, and a wake after it is refused',
            'token': 'pass token: no login or token passed through the driver'}
KIT_NOTE_PASS = {'start': 'pass start: the run posted builder status note ',
                 'wake': 'pass wake: the run edited builder status note '}
NOTE_ID = re.compile(r'[0-9]+\Z', re.ASCII)
HEX40 = re.compile(r'[0-9a-f]{40}\Z', re.ASCII)
DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z', re.ASCII)
PUBLIC_TOKEN = re.compile(r'[a-z0-9][a-z0-9._-]{0,59}\Z', re.ASCII)
LISTING_ID = re.compile(r'[a-z0-9-]{2,40}\Z', re.ASCII)
LOGIN = re.compile(r'[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}\Z', re.ASCII)
PRIVATE_ID = re.compile(r'\b(?:thr_[A-Za-z0-9]|(?:proj|prj|mch|usr|acct|auto)_[A-Za-z0-9]|cr_[0-9A-Za-z]'
                        r'|[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\b)', re.ASCII)
MAX_RECORD = 65536
USAGE = 'usage: receipt.py <run record> --listing <id> --run-by <login> -o <dir>'
UNREADABLE = 'the run record is not readable JSON with each key once'
INCONSISTENT = 'the run record is not a consistent ran or skipped record'
EXISTS = 'a receipt is already at its path; the first one is kept'
UNWRITTEN = 'the receipt could not be written'
NOT_CONFIGURED = 'the run record host, harness and model are not one runs entry of a tracked host config'
UNREAD_HOSTS = 'the tracked host configs could not be read'
BAD_HOST = 'a tracked host config is not a valid host config'


class Refused(Exception):
    pass


class Usage(Exception):
    pass


class Args(argparse.ArgumentParser):
    def error(self, message):
        raise Usage()


def source(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kit():
    return source('kit', KIT)


def git(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    try:
        p = subprocess.run(['git', '--no-replace-objects', '-C', ROOT, '-c', 'core.fsmonitor=false'] + list(args),
                           stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused(UNREAD_HOSTS)
    if p.returncode:
        raise Refused(UNREAD_HOSTS)
    return p.stdout


def configured():
    if git('rev-parse', '--show-toplevel').decode('utf-8', 'surrogateescape').strip() != ROOT:
        raise Refused(UNREAD_HOSTS)
    head = git('rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    rig = source('rig', RIG)
    triples = set()
    for folder in HOST_FOLDERS:
        for entry in git('ls-tree', '-z', head, folder + '/').split(b'\0'):
            meta, _, rel = entry.decode('utf-8', 'surrogateescape').partition('\t')
            mode, kind, oid = (meta.split(' ') + ['', '', ''])[:3]
            if (kind, os.path.dirname(rel)) != ('blob', folder) or mode not in ('100644', '100755'):
                continue
            if not rel.endswith('.json'):
                continue
            try:
                text = git('cat-file', 'blob', oid).decode('utf-8')
                host = rig._valid(json.loads(text, object_pairs_hook=rig._unique), os.path.basename(rel))
            except (ValueError, RecursionError, rig.Refused):
                raise Refused(BAD_HOST)
            triples.update((host['host'], r['harness'], r['model']) for r in host['runs'])
    return triples


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def once_each(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError
    return dict(pairs)


def no_constant(name):
    raise ValueError


def load(path):
    try:
        with open(path, 'rb') as f:
            data = f.read(MAX_RECORD + 1)
    except OSError:
        raise Refused(UNREADABLE)
    if len(data) > MAX_RECORD:
        raise Refused('the run record is larger than 64 KiB')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=once_each, parse_constant=no_constant)
    except (ValueError, RecursionError):
        raise Refused(UNREADABLE)


def real_date(v):
    if not isinstance(v, str) or not DATE.match(v):
        return False
    try:
        datetime.date(int(v[:4]), int(v[5:7]), int(v[8:]))
    except ValueError:
        return False
    return True


def checked(rec):
    if not isinstance(rec, dict) or set(rec) != KEYS:
        raise Refused('the run record does not have exactly the run record keys')
    ran = (rec['outcome'] == 'ran' and rec['skipped'] is None and is_int(rec['kit_exit'])
           and isinstance(rec['stdout'], str))
    skipped = (rec['outcome'] == 'skipped' and isinstance(rec['skipped'], str) and rec['skipped'] != ''
               and rec['kit_exit'] is None and rec['stdout'] is None)
    if not ran and not skipped:
        raise Refused(INCONSISTENT)
    if not is_int(rec['seconds']) or rec['seconds'] < 0:
        raise Refused('the run record seconds is not a whole number of seconds')
    if skipped:
        raise Refused('the run record is a skipped run')
    if rec['kit_exit'] != 0:
        raise Refused('kit.py exited non-zero, not 0')
    for key in ('harness', 'model'):
        if not isinstance(rec[key], str) or not PUBLIC_TOKEN.match(rec[key]):
            raise Refused('the run record %s is not a public token' % key)
    for key in ('driver_commit', 'kit_commit'):
        if not isinstance(rec[key], str) or not HEX40.match(rec[key]):
            raise Refused('the run record %s is not a 40-hex lowercase commit' % key)
    if not real_date(rec['date']):
        raise Refused('the run record date is not a real YYYY-MM-DD date')
    return rec


def kit_lines(stdout):
    lines = stdout.split('\n')
    if lines[-1] != '':
        raise Refused("kit.py's stdout does not end in a newline")
    lines = lines[:-1]
    if len(lines) != 5:
        raise Refused("kit.py's stdout does not have its five lines")
    names = [re.match(r'(?:pass|fail) (\w+): ', l, re.ASCII) for l in lines]
    if None in names:
        raise Refused("kit.py's stdout holds a line that is not a check line")
    if sorted(m.group(1) for m in names) != sorted(CHECKS):
        raise Refused("kit.py's stdout does not name its five checks once each")
    if tuple(m.group(1) for m in names) != CHECKS:
        raise Refused("kit.py's lines are out of order; the order is %s" % ', '.join(CHECKS))
    for name, line in zip(CHECKS, lines):
        if line.split(': ', 1)[1] == 'withheld':
            raise Refused("the %s line is withheld in the run record; a receipt needs kit.py's line" % name)
    passed = sum(l.startswith('pass ') for l in lines)
    if passed != 5:
        raise Refused('the run is not 5 of 5 pass')
    out = []
    notes = set()
    for name, line in zip(CHECKS, lines):
        if name in KIT_NOTE_PASS:
            prefix = KIT_NOTE_PASS[name]
            if not (line.startswith(prefix) and NOTE_ID.match(line[len(prefix):])):
                raise Refused("the %s line is not kit.py's passing %s line" % (name, name))
            notes.add(line[len(prefix):])
            line = prefix + '<note>'
        elif line != KIT_PASS[name]:
            raise Refused("the %s line is not kit.py's passing %s line" % (name, name))
        out.append(line)
    if len(notes) != 1:
        raise Refused('the start and wake lines name different builder status notes')
    return out


def listing_for(rec, listing):
    with open(LISTINGS) as f:
        listings = json.load(f)
    if not isinstance(rec['host'], str) or rec['host'] not in listings:
        raise Refused('the run record host is not in listings.json')
    if listing == listings[rec['host']]:
        return listing
    harness = listings.get('%s/%s' % (rec['host'], rec['harness']))
    if harness is None:
        raise Refused("--listing is not this run's driver listing, and its harness has no listing in listings.json")
    if listing != harness:
        raise Refused("--listing is neither this run's driver listing nor its harness listing in listings.json")
    return listing


def receipt(rec, listing, run_by):
    if not LISTING_ID.match(listing):
        raise Refused('--listing is not a listing id')
    if not LOGIN.match(run_by):
        raise Refused('--run-by is not a GitHub login')
    rec = checked(rec)
    body = kit_lines(rec['stdout'])
    listing = listing_for(rec, listing)
    lines = ['# listing: ' + listing, '# host: ' + rec['host'],
             '# driver: %s@%s' % (REPO, rec['driver_commit']), '# kit: %s@%s' % (REPO, rec['kit_commit']),
             '# harness: ' + rec['harness'], '# model: ' + rec['model'], '# date: ' + rec['date'],
             '# run by: ' + run_by] + body + ['Result: 5 of 5 pass']
    k = kit()
    for n, line in enumerate(lines, 1):
        if PRIVATE_ID.search(line):
            raise Refused('line %d holds a private id' % n)
        if line != KIT_PASS['token'] and k.holds_credential(line):
            raise Refused('line %d holds a credential shape' % n)
    if (rec['host'], rec['harness'], rec['model']) not in configured():
        raise Refused(NOT_CONFIGURED)
    path = os.path.join('receipts', listing, '%s-%s.txt' % (rec['date'], rec['driver_commit'][:12]))
    return path, ''.join(l + '\n' for l in lines).encode('utf-8')


def install(out, rel, data):
    path = os.path.join(out, rel)
    tmp = None
    try:
        if os.path.lexists(path):
            raise Refused(EXISTS)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.receipt-', suffix='.tmp', dir=os.path.dirname(path))
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise Refused(EXISTS)
    except OSError:
        raise Refused(UNWRITTEN)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path


def main(argv):
    ap = Args(prog='receipt.py', add_help=False)
    ap.add_argument('record')
    ap.add_argument('--listing', required=True)
    ap.add_argument('--run-by', required=True)
    ap.add_argument('-o', dest='out', required=True)
    try:
        a = ap.parse_args(argv)
    except Usage:
        print('receipt.py: ' + USAGE, file=sys.stderr)
        return 2
    try:
        rel, data = receipt(load(a.record), a.listing, a.run_by)
        path = install(a.out, rel, data)
    except Refused as e:
        print('receipt.py: %s' % e, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
