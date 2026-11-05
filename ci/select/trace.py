#!/usr/bin/env python3
"""Run every test of one lane under strace, and keep what each one read
(#432, K15). Run from the repository root.

  python3 -I ci/select/trace.py rust OUT [--jobs N] [--alongside NAME CMD...]
  python3 -I ci/select/trace.py web OUT [--jobs N]
  python3 -I ci/select/trace.py export OUT     # npm run build, in apps/web
  python3 -I ci/select/trace.py ready          # exit 0 if strace can trace here

Each test (units.py) runs on its own under `strace --seccomp-bpf -f`, as
CI runs it: `cargo test --locked <its cargo arguments>` from the root, or
`node --test --test-force-exit <its file>` from apps/web. Every repository
path it, or any process it started, opened, looked for (a stat or an open
that found nothing counts), executed or listed is kept, then resolved
(resolve.py): a Rust program under target/ becomes the sources it was built
from, apps/web/out the web export's inputs (`export`), node_modules the
lockfile. The top-level cargo's own reads are left out: it only checks that
every crate is built, and the programs it runs are resolved instead.

OUT/<test id>.json is that test's record: {"files", "dirs", "seconds",
"exit", "traced"}. A test that fails under strace runs again without it: that
run decides the exit status, and its record says "traced": false, so map.py
leaves it out of the map and the selector always runs it. The exit status
is 0 only if every test (and the --alongside command) passed in the end.

`export` traces `npm run build` once and writes OUT/export.json: the files
and folders the web export is built from.

The web lane first builds the programs the browser proofs run, once (as
run-browser.mjs does), and holds each file to run-browser.mjs's rule for a
full run: nothing skipped (its log says `skipped 0`).

`ready` installs strace when it is missing and `sudo -n` can (the cloud
runners; the PC's image has no sudo), then checks it can trace a process
here. A job that isn't ready runs its tests the usual way, and makes no map.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import resolve  # noqa: E402
import units as units_mod  # noqa: E402

STRACE = ['strace', '--seccomp-bpf', '-f', '-qq', '-y', '-e', 'signal=none',
          '-e', 'trace=%file,%process,fchdir,getdents,getdents64']
# The processes whose reads are left out: cargo checking its build is
# fresh, and the rustup proxy in front of it.
QUIET = {'cargo', 'rustup'}

LINE = re.compile(r'^(\d+) +(.*)$')
CALL = re.compile(r'^([a-z0-9_]+)\((.*)$')
RESUMED = re.compile(r'^<\.\.\. ([a-z0-9_]+) resumed>(.*)$')
FD = re.compile(r'(AT_FDCWD|-?\d+)<((?:[^>\\]|\\.)*)>')
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
RESULT = re.compile(r'\)\s+=\s+(-?\d+|\?)(?:<((?:[^>\\]|\\.)*)>)?')
# Calls whose first string argument is a path; *at calls name a folder fd first.
AT = {'openat', 'openat2', 'newfstatat', 'fstatat64', 'statx', 'faccessat', 'faccessat2', 'readlinkat', 'execveat',
      'mkdirat', 'unlinkat', 'renameat', 'renameat2', 'linkat', 'symlinkat', 'fchmodat', 'fchownat', 'utimensat',
      'name_to_handle_at', 'mknodat', 'futimesat'}
PLAIN = {'open', 'creat', 'stat', 'lstat', 'stat64', 'lstat64', 'access', 'readlink', 'execve', 'chdir', 'truncate',
         'mkdir', 'rmdir', 'unlink', 'rename', 'link', 'symlink', 'chmod', 'chown', 'lchown', 'utime', 'utimes',
         'mknod', 'getxattr', 'lgetxattr', 'listxattr', 'llistxattr', 'setxattr', 'lsetxattr', 'removexattr',
         'lremovexattr', 'chroot', 'statfs', 'swapon', 'swapoff', 'quotactl', 'inotify_add_watch',
         'fanotify_mark', 'mount', 'umount2', 'pivot_root', 'uselib', 'acct'}
FORKS = {'clone', 'clone3', 'fork', 'vfork'}


def unescape(s):
    """strace's escapes (\\n, \\", \\\\, \\ooo, \\xHH) back to the bytes, as text."""
    out, i = bytearray(), 0
    raw = s.encode('utf-8', errors='surrogateescape')
    while i < len(raw):
        c = raw[i]
        if c != 0x5c or i + 1 == len(raw):
            out.append(c)
            i += 1
            continue
        n = chr(raw[i + 1])
        simple = {'n': 10, 't': 9, 'r': 13, 'v': 11, 'f': 12, '\\': 92, '"': 34, "'": 39}
        if n in simple:
            out.append(simple[n])
            i += 2
        elif n == 'x':
            out.append(int(raw[i + 2:i + 4], 16))
            i += 4
        elif n in '01234567':
            j = i + 1
            while j < len(raw) and j < i + 4 and chr(raw[j]) in '01234567':
                j += 1
            out.append(int(raw[i + 1:j], 8))
            i = j
        else:
            out.append(c)
            i += 1
    return out.decode('utf-8', errors='surrogateescape')


def parse(lines, root_pid_cwd):
    """The absolute paths a trace touched and the folders it listed, from
    strace -f -y lines. root_pid_cwd: the first process's working folder.
    Reads by a process running QUIET programs are left out."""
    cwd, exe = {}, {}
    pending = {}
    touched, listed = set(), set()
    first = None
    for raw in lines:
        m = LINE.match(raw.rstrip('\n'))
        if not m:
            continue
        pid, rest = int(m.group(1)), m.group(2)
        if first is None:
            first = pid
            cwd[pid] = root_pid_cwd
        if rest.endswith('<unfinished ...>'):
            pending[pid] = rest[:-len('<unfinished ...>')].rstrip()
            continue
        r = RESUMED.match(rest)
        if r:
            rest = pending.pop(pid, r.group(1) + '(') + r.group(2)
        c = CALL.match(rest)
        if not c:
            continue
        name, args = c.group(1), c.group(2)
        here = cwd.get(pid, root_pid_cwd)
        res = RESULT.search(args)
        ret = res.group(1) if res else '?'
        if name in FORKS:
            if ret.isdigit():
                cwd[int(ret)] = here
                exe[int(ret)] = exe.get(pid)
            continue
        if name in ('getdents', 'getdents64'):
            f = FD.match(args)
            if f:
                listed.add(unescape(f.group(2)))
            continue
        if name == 'fchdir':
            f = FD.match(args)
            if f and ret == '0':
                cwd[pid] = unescape(f.group(2))
            continue
        if name not in AT and name not in PLAIN:
            continue
        path, base = None, here
        if name in AT:
            f = FD.match(args)
            s = STRING.search(args)
            if not s:
                continue
            path = unescape(s.group(1))
            if f and not path.startswith('/'):
                base = unescape(f.group(2))
        else:
            s = STRING.search(args)
            if not s:
                continue
            path = unescape(s.group(1))
        if path == '':
            continue  # AT_EMPTY_PATH: the open file itself, seen when it was opened
        full = os.path.normpath(os.path.join(base, path))
        if name in ('execve', 'execveat') and ret == '0':
            exe[pid] = os.path.basename(full)
        if name == 'chdir' and ret == '0':
            cwd[pid] = full
        if exe.get(pid) in QUIET:
            continue
        touched.add(full)
        if res and res.group(2):  # an fd: the path it really opened, symlinks resolved
            touched.add(os.path.normpath(unescape(res.group(2))))
    return touched, listed


def strace_run(argv, cwd, env, log):
    """Run argv under strace; (exit status, touched, listed, seconds)."""
    with tempfile.NamedTemporaryFile(prefix='trace-', suffix='.strace', delete=False) as t:
        out = t.name
    try:
        began = time.monotonic()
        with open(log, 'ab') as lf:
            rc = subprocess.run(STRACE + ['-o', out] + argv, cwd=cwd, env=env, stdout=lf,
                                stderr=subprocess.STDOUT).returncode
        took = time.monotonic() - began
        with open(out, errors='surrogateescape') as f:
            touched, listed = parse(f, os.path.abspath(cwd))
    finally:
        os.unlink(out)
    return rc, touched, listed, took


def plain_run(argv, cwd, env, log):
    began = time.monotonic()
    with open(log, 'ab') as lf:
        rc = subprocess.run(argv, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
    return rc, time.monotonic() - began


def commands(lane, root, threads):
    """{test id: (argv, cwd)} for one lane."""
    found = units_mod.list_units(root)
    out = {}
    for uid, how in sorted(found.items()):
        if lane == 'rust' and uid.startswith('rust:'):
            out[uid] = (['cargo', 'test', '--locked', *how, '--', f'--test-threads={threads}'], root)
        elif lane == 'web' and uid.startswith('web:'):
            out[uid] = (['node', '--test', '--test-force-exit', '--test-reporter=spec', how],
                        os.path.join(root, 'apps/web'))
    if not out:
        raise SystemExit(f'trace: no {lane} tests found')
    return out


SKIPPED_NONE = re.compile(r'^\S* ?skipped 0$', re.M)
# run-browser.mjs's coverage rule for a full run (soak-skip.mjs): the soak,
# the top-level `soak: ` test of its file, ran and passed.
SOAK_TEST = 'web:browser:v7-soak'
SOAK_PASSED = re.compile(r'^\u2714 soak: ', re.M)


def trace_lane(lane, out_dir, jobs, threads, root, only=None):
    os.makedirs(out_dir, exist_ok=True)
    logs = os.path.join(out_dir, 'logs')
    os.makedirs(logs, exist_ok=True)
    todo = commands(lane, root, threads)
    if only:
        unknown = sorted(set(only) - set(todo))
        if unknown:
            raise SystemExit(f'trace: not {lane} tests here: {unknown}')
        todo = {u: todo[u] for u in only}
    env = dict(os.environ)
    resolver = resolve.Resolver(root)
    if lane == 'web':
        # As run-browser.mjs: the server and the fake, built once before any file.
        build = subprocess.run(['node', '-e', "import('./test/support/rust.mjs').then((m) => m.buildBinaries())"],
                               cwd=os.path.join(root, 'apps/web'))
        if build.returncode:
            print(f'trace: building the browser proofs\' programs failed (exit {build.returncode})')
            return 1

    def one(uid):
        argv, cwd = todo[uid]
        log = os.path.join(logs, uid.replace(':', '_') + '.log')
        rc, touched, listed, took = strace_run(argv, cwd, env, log)
        traced = rc == 0
        decided = 0  # where the attempt that decides begins in the log
        if not traced:
            with open(log, 'ab') as lf:
                lf.write(f'\n== trace: {uid} failed under strace (exit {rc}); once more without it\n'.encode())
                decided = lf.tell()
            rc, took = plain_run(argv, cwd, env, log)
        deciding = ''
        if lane == 'web':
            with open(log, 'rb') as f:
                f.seek(decided)
                deciding = f.read().decode(errors='replace')
        if rc == 0 and lane == 'web':
            if not SKIPPED_NONE.search(deciding):
                rc = 1
                with open(log, 'a') as lf:
                    lf.write(f'\ntrace: {uid}: a full run skips nothing, and its log has no "skipped 0"\n')
            elif uid == SOAK_TEST and not only and not SOAK_PASSED.search(deciding):
                rc = 1
                with open(log, 'a') as lf:
                    lf.write(f'\ntrace: {uid}: a full run runs the soak, and its log shows no passing "soak: " test\n')
        files, dirs, why = resolver.resolve(touched, listed) if traced else ([], [], 'failed under strace')
        record = {'files': files, 'dirs': dirs, 'seconds': round(took, 1), 'exit': rc,
                  'traced': traced and why is None}
        if why:
            record['untraced'] = why
        with open(os.path.join(out_dir, uid.replace(':', '_') + '.json'), 'w') as f:
            json.dump({'test': uid, **record}, f, indent=1, sort_keys=True)
        return uid, rc, log, record

    if lane == 'web' and not only and SOAK_TEST not in todo:
        print(f'trace: a full web run owes the soak ({SOAK_TEST}), and it is not here')
        return 1
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for uid, rc, log, record in pool.map(one, sorted(todo)):
            results.append((uid, rc, log, record))
    failed = 0
    for uid, rc, log, record in results:
        print(f'== trace: {uid}')
        with open(log, errors='replace') as f:
            sys.stdout.write(f.read())
    for uid, rc, log, record in results:
        state = 'ok' if rc == 0 else f'FAILED (exit {rc})'
        mapped = 'mapped' if record['traced'] else 'not mapped: ' + record.get('untraced', '')
        print(f'trace: {uid}: {state}, {record["seconds"]} s, {len(record["files"])} files, '
              f'{len(record["dirs"])} folders, {mapped}')
        failed += rc != 0
    sys.stdout.flush()
    return failed


def trace_export(out_dir, root):
    os.makedirs(out_dir, exist_ok=True)
    log = os.path.join(out_dir, 'export.log')
    rc, touched, listed, took = strace_run(['npm', 'run', 'build'], os.path.join(root, 'apps/web'),
                                           dict(os.environ), log)
    with open(log, errors='replace') as f:
        sys.stdout.write(f.read())
    if rc != 0:
        print(f'trace: npm run build failed (exit {rc})')
        return 1
    files, dirs = resolve.Resolver(root).export_inputs(touched, listed)
    with open(os.path.join(out_dir, 'export.json'), 'w') as f:
        json.dump({'files': files, 'dirs': dirs, 'seconds': round(took, 1)}, f, indent=1, sort_keys=True)
    print(f'trace: the web export: {len(files)} files, {len(dirs)} folders, {round(took, 1)} s')
    return 0


def can_trace():
    probe = ['strace', '--seccomp-bpf', '-f', '-qq', '-o', os.devnull, 'true']
    return shutil.which('strace') is not None and subprocess.run(
        probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ready():
    if can_trace():
        print('trace: strace can trace here')
        return 0
    if not shutil.which('strace') and shutil.which('sudo'):
        for cmd in (['sudo', '-n', 'apt-get', 'update', '-q'], ['sudo', '-n', 'apt-get', 'install', '-y', '-q', 'strace']):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if can_trace():
        print('trace: strace installed, and can trace here')
        return 0
    print('trace: strace can\'t trace here (missing, no sudo, or ptrace refused): the tests run the usual way')
    return 1


def main(argv):
    if argv == ['ready']:
        return ready()
    ap = argparse.ArgumentParser()
    ap.add_argument('lane', choices=['rust', 'web', 'export'])
    ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--threads', type=int, default=8, help='each Rust test binary\'s --test-threads')
    ap.add_argument('--only', nargs='+', help='by hand: just these tests (a map needs them all)')
    ap.add_argument('--alongside', nargs=argparse.REMAINDER, help='NAME COMMAND...: run beside the lane')
    args = ap.parse_args(argv)
    if not shutil.which('strace'):
        raise SystemExit('trace: strace is not installed')
    root = os.getcwd()
    along = None
    if args.alongside:
        name, *cmd = args.alongside
        along_log = tempfile.NamedTemporaryFile(prefix='alongside-', suffix='.log', delete=False)
        print(f'trace: {name}, beside the traced tests: {" ".join(cmd)}')
        along = (name, subprocess.Popen(cmd, stdout=along_log, stderr=subprocess.STDOUT), along_log)
    try:
        if args.lane == 'export':
            failed = trace_export(args.out, root)
        else:
            failed = trace_lane(args.lane, args.out, args.jobs, args.threads, root, args.only)
    except BaseException:
        if along:  # the tracer failed: stop the other suite, which runs again with the tests
            along[1].kill()
            along[1].wait()
        raise
    if along:
        name, proc, log = along
        rc = proc.wait()
        log.close()
        print(f'== trace: {name}')
        with open(log.name, errors='replace') as f:
            sys.stdout.write(f.read())
        os.unlink(log.name)
        print(f'trace: {name}: ' + ('ok' if rc == 0 else f'FAILED (exit {rc})'))
        failed += rc != 0
    return 1 if failed else 0


if __name__ == '__main__':
    # 0: every test passed; 1: a test failed; 3: the tracer itself failed
    # (ci.yml then runs the tests the usual way, and the run makes no map).
    try:
        code = main(sys.argv[1:])
    except SystemExit as e:
        code = e.code if e.code in (0, 1) else 3
        if code == 3:
            print(f'trace: the tracer failed: {e.code}')
    except Exception:
        import traceback
        traceback.print_exc()
        code = 3
    sys.exit(code)
