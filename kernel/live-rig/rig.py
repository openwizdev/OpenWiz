#!/usr/bin/env python3
import argparse
import ast
import datetime
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
KIT = 'kernel/driver-kit/kit.py'
HOST_KEYS = ('host', 'driver', 'needs', 'signed_in', 'cost', 'runs', 'wait')
NAME = r'[A-Za-z0-9][A-Za-z0-9._-]{0,59}'
PROGRAM = r'[A-Za-z0-9][A-Za-z0-9._+-]{0,59}'
KIT_HARNESS = r'[a-z0-9][a-z0-9._-]{0,59}'
KIT_MODEL = r'(?=.{1,100}$)[A-Za-z0-9][A-Za-z0-9 ._:@+-]*(/[A-Za-z0-9][A-Za-z0-9 ._:@+-]*)*'
REPO = r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}'
STATUS_SECONDS = 30
CHECK_LINE = re.compile(r'(pass|fail) (version|start|wake|stop|token): ')
PLAIN = re.compile(r"[A-Za-z0-9 .,;:'()-]*")


class Refused(Exception):
    pass


def _unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('a key is repeated')
    return dict(pairs)


def read_json(path, what):
    try:
        with open(path) as f:
            return json.loads(f.read(), object_pairs_hook=_unique)
    except (OSError, ValueError) as e:
        raise Refused('cannot read %s: %s' % (what, e))


def _text(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _valid(config, name):
    def bad(why):
        raise Refused('%s: %s' % (name, why))
    if not isinstance(config, dict) or set(config) != set(HOST_KEYS):
        bad('a host config has exactly ' + ', '.join(HOST_KEYS))
    if not _text(config['host'], NAME):
        bad('host is not a name')
    if not _text(config['driver'], r'adapters/[a-z0-9][a-z0-9-]{0,59}/driver'):
        bad('driver is not adapters/<host>/driver')
    if not isinstance(config['needs'], list) or not all(_text(p, PROGRAM) for p in config['needs']):
        bad('needs is not a list of program names')
    if not isinstance(config['signed_in'], list) or not all(
            isinstance(c, list) and c and _text(c[0], PROGRAM) and all(isinstance(a, str) and '\0' not in a for a in c)
            for c in config['signed_in']):
        bad('signed_in is not a list of commands, each a program name and its arguments')
    if config['cost'] not in ('none', 'paid', 'unknown'):
        bad('cost is not none, paid or unknown')
    if not isinstance(config['runs'], list) or not all(
            isinstance(r, dict) and set(r) == {'harness', 'model'} and _text(r['harness'], KIT_HARNESS) and
            _text(r['model'], KIT_MODEL) for r in config['runs']):
        bad('runs is not a list of {"harness", "model"}')
    if len({(r['harness'], r['model']) for r in config['runs']}) != len(config['runs']):
        bad('runs names one harness and model twice')
    if not (type(config['wait']) is int and 1 <= config['wait'] <= 900):
        bad('wait is not a whole number of seconds from 1 to 900')
    return config


def load_host(path):
    name = os.path.basename(path)
    return _valid(read_json(path, name), name)


def driver_name(host):
    return host['driver'].split('/')[1]


def driver_path(host, drivers, release):
    if release is not None:
        return os.path.join(os.path.realpath(release), 'driver')
    if drivers is not None:
        return os.path.join(os.path.realpath(drivers), driver_name(host), 'driver')
    return os.path.join(ROOT, host['driver'])


def installed(host, drivers, release):
    path = driver_path(host, drivers, release)
    if drivers is None and release is None:
        return host['driver'] if os.path.isfile(path) else None
    for step in (os.path.dirname(path), path):
        try:
            mode = os.lstat(step).st_mode
        except FileNotFoundError:
            return None
        except OSError as e:
            raise Refused('cannot look up the driver for %s: %s' % (host['host'], e.strerror))
        if stat.S_ISLNK(mode):
            raise Refused('the driver for %s is reached through a symlink, which an installed driver never is'
                          % host['host'])
    if not stat.S_ISREG(mode):
        raise Refused('the driver for %s is not a regular file' % host['host'])
    return path


def record_name(host, entry):
    return '%s-%s-%s.json' % (host['host'], entry['harness'], entry['model'])


def _inside(path):
    return os.path.commonpath([os.path.realpath(path), ROOT]) == ROOT


def load_hosts(folder, only):
    parts = os.path.join(os.getcwd(), folder).split(os.sep)
    try:
        if not stat.S_ISDIR(os.stat(folder).st_mode):
            raise Refused('--hosts is not a folder')
    except OSError as e:
        raise Refused('cannot read --hosts as written: %s' % e.strerror)
    folder = os.path.realpath(folder)
    if os.path.commonpath([folder, ROOT]) != ROOT:
        raise Refused('--hosts is not a folder inside this checkout, so its host configs are not reviewed code')
    for i in range(2, len(parts) + 1):
        given = os.sep.join(parts[:i])
        if parts[i - 1] in ('', '.', '..'):
            continue
        try:
            link = stat.S_ISLNK(os.lstat(given).st_mode)
        except OSError as e:
            raise Refused('cannot look up a step of --hosts: %s' % e.strerror)
        if link and _inside(os.path.dirname(given)):
            raise Refused('--hosts goes through a symlink inside the checkout, so its host configs are not '
                          'reviewed code')
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith('.json'))
    except OSError as e:
        raise Refused('cannot read --hosts: %s' % e)
    modes = {}
    for entry in git('ls-files', '-s', '-z', '--', os.path.relpath(folder, ROOT)).split('\0'):
        meta, _, path = entry.partition('\t')
        modes[path] = meta.split(' ')[0]
    for n in names:
        path = os.path.join(folder, n)
        mode = modes.get(os.path.relpath(path, ROOT))
        if mode is None:
            raise Refused('--hosts holds %s, which git does not track, so it is not reviewed code' % n)
        if mode not in ('100644', '100755') or not stat.S_ISREG(os.lstat(path).st_mode):
            raise Refused('--hosts holds %s, which is not a regular file, so it is not reviewed code' % n)
    hosts = [load_host(os.path.join(folder, n)) for n in names]
    if len({h['host'].casefold() for h in hosts}) != len(hosts):
        raise Refused('two host configs name the same host, ignoring case')
    files = [record_name(h, e).casefold() for h in hosts for e in h['runs']]
    if len(set(files)) != len(files):
        raise Refused('two runs entries would write the same run record')
    if only is not None:
        hosts = [h for h in hosts if h['host'] == only]
        if not hosts:
            raise Refused('no host config names %s' % only)
    return hosts


def load_settings(path):
    s = read_json(path, '--settings')
    if not (isinstance(s, dict) and set(s) == {'repo', 'ticket'} and _text(s['repo'], REPO) and
            type(s['ticket']) is int and s['ticket'] > 0):
        raise Refused('--settings is not {"repo": "<owner>/<name>", "ticket": <n>}')
    return s


def git(*args):
    try:
        p = subprocess.run(['git', '-C', ROOT] + list(args), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused('git did not run: %s' % e)
    if p.returncode:
        raise Refused('git %s failed' % args[0])
    return p.stdout


def clean_head():
    if git('status', '--porcelain', '--untracked-files=all'):
        raise Refused('the checkout has uncommitted changes, so a run record could name no real commit')
    head = git('rev-parse', 'HEAD').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', head):
        raise Refused('the checkout has no 40-hex HEAD')
    return head


def signed_in(command):
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=STATUS_SECONDS).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_host(host):
    for program in host['needs']:
        if shutil.which(program) is None:
            return 'not installed: ' + program
    if host['cost'] != 'none':
        return 'cost'
    for command in host['signed_in']:
        if not signed_in(command):
            program = command[0]
            if program == 'env':
                for word in command[1:]:
                    if re.match(r'[A-Za-z_][A-Za-z0-9_]*=', word):
                        continue
                    if _text(word, PROGRAM):
                        program = word
                    break
            return 'not signed in: ' + program
    return None


def kit_shapes():
    with open(os.path.join(ROOT, KIT)) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, 'id', None) for t in node.targets] == ['SHAPES']:
            call = node.value
            flag = call.args[1] if isinstance(call, ast.Call) and len(call.args) == 2 else None
            if isinstance(flag, ast.Attribute) and flag.attr == 'I' and getattr(flag.value, 'id', None) == 're':
                return re.compile(ast.literal_eval(call.args[0]), re.I)
    raise Refused('%s has no credential shapes the rig can read' % KIT)


def signed_in_login():
    try:
        p = subprocess.run(['gh', 'api', 'user', '--jq', '.login'], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=STATUS_SECONDS, env=dict(os.environ, GH_TELEMETRY='0'))
    except (OSError, subprocess.TimeoutExpired):
        return None
    login = p.stdout.strip()
    return login if p.returncode == 0 and re.fullmatch(r'[A-Za-z0-9-]{1,39}', login) else None


def record_stdout(text, settings, login):
    shapes = kit_shapes()
    owner, _, name = settings['repo'].partition('/')
    private = [v.lower() for v in (settings['repo'], owner, name, login or '')]
    kept = []
    for line in text.splitlines():
        check = CHECK_LINE.match(line)
        if not check:
            continue
        what = line[check.end():]
        if login is None or shapes.search(what) or not PLAIN.fullmatch(what) or \
                any(v in what.lower() for v in private):
            line = '%s %s: withheld' % check.groups()
        kept.append(line + '\n')
    return ''.join(kept)


def run_kit(host, entry, settings, driver=None):
    command = [sys.executable, '-I', KIT, '--driver', driver or host['driver'], '--repo', settings['repo'],
               '--ticket', str(settings['ticket']), '--harness', entry['harness'], '--model', entry['model'],
               '--wait', str(host['wait'])]
    p = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    sys.stderr.write(p.stdout)
    sys.stderr.flush()
    return p.returncode, p.stdout


def write_record(out, record):
    folder = os.path.join(out, record['date'])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, record_name(record, record))
    with open(path + '.part', 'w') as f:
        f.write(json.dumps(record, indent=2) + '\n')
    os.replace(path + '.part', path)


def run(args):
    settings = load_settings(args.settings)
    if args.release is not None and (args.host is None or args.drivers is not None):
        raise Refused('--release is one driver, so it needs --host and no --drivers')
    for flag, folder in (('--drivers', args.drivers), ('--release', args.release)):
        if folder is not None and not os.path.isdir(folder):
            raise Refused('%s is not a folder' % flag)
    hosts = load_hosts(args.hosts, args.host)
    drivers = {}
    for host in hosts:
        drivers[host['host']] = installed(host, args.drivers, args.release)
    head = clean_head()
    kit_shapes()
    try:
        os.makedirs(args.out, exist_ok=True)
        lock = open(os.path.join(args.out, 'rig.lock'), 'a')
    except OSError as e:
        raise Refused('cannot use --out: %s' % e)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('rig.py: another run holds the lock', file=sys.stderr)
        return 0
    except OSError as e:
        raise Refused('cannot lock --out: %s' % e)
    failed, login = False, False
    for host in hosts:
        began = time.monotonic()
        driver = drivers[host['host']]
        why = check_host(host) or (None if driver else 'not installed: driver ' + driver_name(host))
        for entry in host['runs']:
            day = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
            kit_exit = stdout = passed = None
            if why is None:
                if login is False:
                    login = signed_in_login()
                began = time.monotonic()
                kit_exit, full = run_kit(host, entry, settings, driver)
                passed = sum(1 for line in full.splitlines() if CHECK_LINE.match(line) and line.startswith('pass '))
                stdout = record_stdout(full, settings, login)
            write_record(args.out, {
                'host': host['host'], 'harness': entry['harness'], 'model': entry['model'], 'date': day,
                'driver_commit': head, 'kit_commit': head, 'outcome': 'skipped' if why else 'ran',
                'skipped': why, 'kit_exit': kit_exit, 'stdout': stdout,
                'seconds': int(round(time.monotonic() - began))})
            if why:
                print('skipped %s %s: %s' % (host['host'], entry['harness'], why), flush=True)
            else:
                print('ran %s %s: %d of 5' % (host['host'], entry['harness'], passed), flush=True)
                failed = failed or kit_exit != 0
    return 1 if failed else 0


def main(argv):
    ap = argparse.ArgumentParser(prog='rig.py')
    ap.add_argument('--hosts', required=True, help='the folder of host configs; only its *.json files are read')
    ap.add_argument('--settings', required=True, help='a local JSON file {"repo": "<owner>/<name>", "ticket": <n>}')
    ap.add_argument('--out', required=True, help='the folder for run records and the lock')
    ap.add_argument('--host', help="run only the host config with this host name")
    ap.add_argument('--drivers', help='a drivers folder laid out <name>/driver, such as the install\'s '
                                      '$OPENWIZ_ADAPTERS, to run each driver from instead of adapters/')
    ap.add_argument('--release', help='an unpacked driver release (driver, schema.json and README.md at its root) '
                                      'to run the --host driver from')
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (Refused, OSError) as e:
        print('rig.py: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
