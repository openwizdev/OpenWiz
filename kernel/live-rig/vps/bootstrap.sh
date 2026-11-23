#!/usr/bin/env bash
set -eu
py="$(command -v python3 || true)"
if [ -z "$py" ] || ! "$py" -I -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    echo "bootstrap: needs python3 3.9 or later on PATH; install it with your system package manager" \
         "(this bootstrap never runs sudo)" >&2
    exit 2
fi
here="$(cd "$(dirname "$0")" && pwd)"
code="$(sed '1,/^python_below = True$/d' "$0")"
exec "$py" -I -c "$code" "$here" "$@"
python_below = True
import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

USAGE = '''usage: bootstrap.sh [--dry-run] [--prefix DIR] [--tools FILE]

Installs the free CLIs the waiting live-check hosts need, pinned in tools.json, into --prefix
(default ~/.local; commands go in <prefix>/bin). Every download is checked against its pinned
sha256 before anything is run or installed from it. It never signs in, never installs a paid tool,
never runs sudo, and runs nothing it installed except `<tool> --version`; a tool is published only
after its staged copy names its pinned version, so a working one is never replaced by a broken one.
Each program it starts gets only HOME, USER, LOGNAME, SHELL, LANG, LC_ALL, LC_CTYPE, TERM, TMPDIR
and TZ from your environment, never a token or key. A second run installs nothing. --dry-run prints
each step and writes nothing, not even a temporary file.

Exit 0 when every tool is installed, already there or left out by design; 1 when a download,
checksum or install failed; 2 on a usage error or a missing python3 3.9+.'''
NO_SUDO = 'this bootstrap never runs sudo'
PASSED_ON = ('HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'TMPDIR', 'TZ')


class Refused(Exception):
    pass


def usage(message):
    print('bootstrap: %s\n%s' % (message, USAGE), file=sys.stderr)
    sys.exit(2)


def options(here, argv):
    opts = {'dry': False, 'prefix': '~/.local', 'tools': os.path.join(here, 'tools.json')}
    while argv:
        arg = argv.pop(0)
        if arg == '--dry-run':
            opts['dry'] = True
        elif arg in ('--prefix', '--tools') and argv:
            opts[arg[2:]] = argv.pop(0)
        elif arg in ('-h', '--help'):
            print(USAGE)
            sys.exit(0)
        else:
            usage('unknown argument: %s' % arg)
    opts['prefix'] = os.path.abspath(os.path.expanduser(opts['prefix']))
    return opts


def platform_key():
    system, machine = platform.system().lower(), platform.machine().lower()
    if machine in ('amd64', 'x86_64'):
        machine = 'x86_64'
    elif machine in ('arm64', 'aarch64'):
        machine = 'arm64' if system == 'darwin' else 'aarch64'
    return '%s-%s' % (system, machine)


def child_env(path=None):
    env = {name: os.environ[name] for name in PASSED_ON if name in os.environ}
    env.update(PATH=path or os.environ.get('PATH', '/usr/bin:/bin'), DO_NOT_TRACK='1')
    return env


def run_version(command):
    try:
        r = subprocess.run([command, '--version'], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=60, env=child_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout + r.stderr).strip() if r.returncode == 0 else None


def numbers(text):
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', text or '')
    return match and tuple(int(x or 0) for x in match.groups())


def system_tool(name, minimum):
    path = shutil.which(name)
    have = numbers(run_version(path)) if path else None
    fix = 'install %s %s or later with your system package manager (%s)' % (name, minimum, NO_SUDO)
    if not path:
        return None, 'not on PATH; ' + fix
    if not have:
        return None, '`%s --version` names no version; %s' % (name, fix)
    if have < numbers(minimum):
        return None, '%s %s is older than %s; %s' % (name, '.'.join(map(str, have)), minimum, fix)
    return '.'.join(map(str, have)), None


def digest(path):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def fetch(file, work):
    path = os.path.join(work, 'download')
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(file['url'], timeout=120) as src, open(path, 'wb') as dst:
            for block in iter(lambda: src.read(1 << 20), b''):
                digest.update(block)
                dst.write(block)
    except (OSError, ValueError) as e:
        raise Refused('download failed: %s' % (getattr(e, 'reason', None) or type(e).__name__))
    if digest.hexdigest() != file['sha256']:
        os.remove(path)
        raise Refused('checksum mismatch: expected %s, got %s' % (file['sha256'], digest.hexdigest()))
    return path


def place(data, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + '.part'
    with open(part, 'wb') as f:
        f.write(data)
    os.chmod(part, 0o755)
    os.replace(part, dst)


def member(path, name):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return z.read(name)
    with tarfile.open(path) as t:
        f = t.extractfile(name)
        if f is None:
            raise Refused('%s is not a file in the archive' % name)
        return f.read()


def check_version(tool, command):
    if tool.get('run_version', True):
        said = run_version(command)
        if not said or tool['version'] not in said:
            raise Refused('`%s --version` does not name %s' % (tool['name'], tool['version']))


def run_installer(tool, script, prefix, work):
    home = os.path.expanduser('~')
    dst = os.path.join(prefix, 'bin', tool['name'])
    # SAFETY: a third-party installer finds a refusing sudo first on its PATH; this bootstrap never runs sudo.
    guard = os.path.join(work, 'guard')
    place(('#!/bin/sh\necho "bootstrap: sudo refused; %s" >&2\nexit 1\n' % NO_SUDO).encode(),
          os.path.join(guard, 'sudo'))
    args = [a.replace('{home}', home) for a in tool['args']]
    path = os.pathsep.join([guard, os.path.join(prefix, 'bin'), os.environ.get('PATH', '')])
    r = subprocess.run(['bash', script] + args, stdin=subprocess.DEVNULL, stdout=sys.stderr, cwd=work,
                       env=child_env(path))
    if r.returncode:
        raise Refused('its installer exited %d' % r.returncode)
    if not os.path.isfile(dst):
        raise Refused('its installer left no %s' % dst)
    check_version(tool, dst)


def install(tool, file, prefix, work):
    name, kind = tool['name'], tool['kind']
    dst = os.path.join(prefix, 'bin', name)
    path = fetch(file, work)
    if kind == 'installer':
        return run_installer(tool, path, prefix, work)
    staged = os.path.join(prefix, 'lib', 'openwiz-vps', 'staged', name)
    # A wheel lives at a path named by its sha256, so a repin never rewrites the one a working launcher imports.
    wheels = os.path.join(prefix, 'lib', 'openwiz-vps', 'wheels', name)
    wheel = os.path.join(wheels, file['sha256'] + '.whl')
    new_wheel = False
    try:
        if kind == 'binary':
            place(open(path, 'rb').read(), staged)
        elif kind == 'archive':
            try:
                place(member(path, file['member']), staged)
            except (KeyError, OSError, tarfile.TarError, zipfile.BadZipFile) as e:
                raise Refused('cannot unpack %s: %s' % (file['member'], type(e).__name__))
        elif kind == 'wheel':
            if digest(wheel) != file['sha256']:
                try:
                    place(open(path, 'rb').read(), wheel)
                except OSError as e:
                    raise Refused('%s: %s' % ('its cached wheel fails its checksum and cannot be replaced'
                                              if os.path.lexists(wheel) else 'cannot write its wheel',
                                              type(e).__name__))
                new_wheel = True
            code = 'import importlib, sys; sys.path.insert(0, sys.argv.pop(1)); ' \
                   'sys.exit(importlib.import_module(%r).main())' % tool['module']
            place(('#!/bin/sh\nexec %s -I -c %s %s "$@"\n' % (shlex.quote(sys.executable), shlex.quote(code),
                                                             shlex.quote(wheel))).encode(), staged)
        else:
            raise Refused('unknown kind %r in tools.json' % kind)
        check_version(tool, staged)
    except Refused:
        if new_wheel:
            os.remove(wheel)
        raise
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(staged, dst)
    if kind == 'wheel':
        for old in os.listdir(wheels):
            if os.path.join(wheels, old) != wheel:
                os.remove(os.path.join(wheels, old))


def hold_lock(prefix):
    path = os.path.join(prefix, 'lib', 'openwiz-vps', 'lock')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path, 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('bootstrap: waiting for another bootstrap on %s' % prefix, file=sys.stderr, flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError as e:
        print('bootstrap: cannot lock %s: %s' % (path, type(e).__name__), file=sys.stderr)
        sys.exit(1)
    return lock


def stamp_path(prefix, name):
    return os.path.join(prefix, 'lib', 'openwiz-vps', name + '.json')


def stamped(tool, file, prefix):
    try:
        with open(stamp_path(prefix, tool['name'])) as f:
            stamp = json.load(f)
    except (OSError, ValueError):
        return False
    return stamp == {'version': tool['version'], 'sha256': file['sha256']} and \
        os.path.exists(os.path.join(prefix, 'bin', tool['name']))


def main():
    opts = options(sys.argv[1], sys.argv[2:])
    prefix, dry, key = opts['prefix'], opts['dry'], platform_key()
    home_prefix = os.path.join(os.path.expanduser('~'), '.local')
    try:
        with open(opts['tools']) as f:
            tools = json.load(f)['tools']
    except (OSError, ValueError, KeyError) as e:
        usage('cannot read %s: %s' % (opts['tools'], type(e).__name__))
    installed, there, left, available, failed, work = 0, 0, [], set(), False, None
    lock = None if dry else hold_lock(prefix)

    def leave(name, why):
        left.append('left out %s: %s' % (name, why))
        print(left[-1], flush=True)

    def already(name, have):
        nonlocal there
        there += 1
        available.add(name)
        print('already there %s %s' % (name, have), flush=True)

    try:
        for tool in tools:
            name = tool['name']
            dst = os.path.join(prefix, 'bin', name)
            if tool.get('left_out'):
                leave(name, tool['left_out'])
                continue
            if tool['kind'] == 'system':
                have, why = system_tool(name, tool['min_version'])
                if why:
                    leave(name, why)
                else:
                    already(name, have)
                continue
            if tool.get('home_only') and prefix != home_prefix:
                leave(name, 'its installer installs into your home (%s) with no option to confine it, so it '
                            'is never installed under --prefix; run without --prefix to install it'
                            % tool['home_only'])
                continue
            file = tool['files'].get(key) or tool['files'].get('any')
            if file and stamped(tool, file, prefix):
                already(name, tool['version'])
                continue
            if os.path.lexists(dst) and not os.path.exists(stamp_path(prefix, name)):
                leave(name, 'your existing %s was not installed by this bootstrap, so it is kept and never run; '
                            'move it aside to install the pinned %s' % (dst, tool['version']))
                continue
            if tool['kind'] == 'installer' and os.path.lexists(dst):
                leave(name, 'your existing %s is kept and not run, since its installer would overwrite it in '
                            'place; move it aside to install the pinned %s' % (dst, tool['version']))
                continue
            have = system_tool(name, tool['system_min'])[0] if tool.get('system_min') else None
            if have:
                already(name, have)
                continue
            if not file:
                leave(name, 'no %s build pinned in tools.json%s' % (key, '; ' + tool['note'] if 'note' in tool else ''))
                continue
            missing = [n for n in tool.get('needs', []) if n not in available]
            if missing:
                leave(name, 'needs ' + ', '.join(missing))
                continue
            if dry:
                print('would install %s %s from %s, sha256 %s' % (name, tool['version'], file['url'], file['sha256']),
                      flush=True)
                installed += 1
                available.add(name)
                continue
            work = work or tempfile.mkdtemp(prefix='openwiz-vps-')
            step = tempfile.mkdtemp(dir=work)
            kept = ' (the existing one is kept)' if os.path.lexists(dst) else ''
            try:
                install(tool, file, prefix, step)
            except Refused as e:
                failed = True
                leave(name, str(e) + kept)
                continue
            finally:
                shutil.rmtree(step, ignore_errors=True)
                shutil.rmtree(os.path.join(prefix, 'lib', 'openwiz-vps', 'staged'), ignore_errors=True)
            stamp = stamp_path(prefix, name)
            place(json.dumps({'version': tool['version'], 'sha256': file['sha256']}).encode(), stamp)
            os.chmod(stamp, 0o644)
            installed += 1
            available.add(name)
            print('installed %s %s' % (name, tool['version']), flush=True)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        if lock:
            lock.close()
    if dry:
        print('bootstrap: dry run, %d to install, %d already there, %d left out' % (installed, there, len(left)))
    else:
        print('bootstrap: %d installed, %d already there, %d left out' % (installed, there, len(left)))
    for line in left:
        print(line)
    return 1 if failed else 0


sys.exit(main())
