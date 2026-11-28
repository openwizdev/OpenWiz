#!/usr/bin/env python3
import argparse
import importlib.machinery
import importlib.util
import os
import secrets
import signal
import statistics
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))

DETACHED_HELPER = (
    "import os, sys, time\n"
    "n = int(sys.argv[1])\n"
    "if os.fork():\n"
    "    os._exit(0)\n"
    "os.setsid()\n"
    "pids = []\n"
    "for _ in range(n):\n"
    "    p = os.fork()\n"
    "    if p == 0:\n"
    "        time.sleep(300)\n"
    "        os._exit(0)\n"
    "    pids.append(p)\n"
    "os.write(1, (' '.join(map(str, [os.getpid()] + pids)) + '\\n').encode())\n"
    "time.sleep(300)\n"
)


def load_kit(path):
    spec = importlib.util.spec_from_loader('kit_bench', importlib.machinery.SourceFileLoader('kit_bench', path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_kit(kit, mark):
    k = kit.Kit.__new__(kit.Kit)
    k.lock, k.leaks, k.mark = threading.RLock(), [], mark
    k.groups, k.sessions, k.owned, k.hidden = set(), set(), {}, set()
    k.ps_session = None
    k.seen, k.env, k.listed_pids, k.since = True, {}, set(), 0
    k.runtime, k.active, k.setting, k.effort_seen = set(), set(), None, False
    k.subreaper, k._direct = False, set()
    return k


def measure(kit_obj, canary, warmup, scans):
    for _ in range(warmup):
        kit_obj._scan(canary)
    times = []
    for _ in range(scans):
        t0 = time.perf_counter()
        kit_obj._scan(canary)
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times)


def run(args):
    kit = load_kit(args.kit)
    mark_val = secrets.token_hex(8)
    mark = 'OPENWIZ_KIT_RUN=' + mark_val
    canary = ('example', 'kit-canary-' + secrets.token_hex(16))
    counts = [int(x) for x in args.counts.split(',') if x.strip()]
    print('| Total procs | Unrelated | Marked | Scan median (ms) | Key check median (ms) |', flush=True)
    print('| ---: | ---: | ---: | ---: | ---: |', flush=True)
    for unrelated_n in counts:
        marked_n = min(args.marked, 2) if unrelated_n == 0 else args.marked
        detached_pids, marked_procs = [], []
        try:
            if unrelated_n > 0:
                p = subprocess.Popen([sys.executable, '-I', '-c', DETACHED_HELPER, str(unrelated_n)],
                                     stdout=subprocess.PIPE)
                line = p.stdout.readline().decode().strip()
                p.stdout.close()
                p.wait()
                detached_pids = [int(x) for x in line.split()]
            env = dict(os.environ, OPENWIZ_KIT_RUN=mark_val)
            for _ in range(marked_n):
                marked_procs.append(subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(300)'],
                                                     env=env))
            time.sleep(0.1)
            total = len([x for x in os.listdir('/proc') if x.isdigit()])
            k = make_kit(kit, mark)
            plain_rounds = [measure(k, None, args.warmup, args.scans) for _ in range(args.rounds)]
            key_rounds = [measure(k, canary, args.warmup, args.scans) for _ in range(args.rounds)]
            print('| %d | %d | %d | %.2f | %.2f |' % (
                total, unrelated_n, marked_n, statistics.median(plain_rounds), statistics.median(key_rounds)),
                flush=True)
        finally:
            for p in marked_procs:
                p.kill()
            for p in marked_procs:
                p.wait()
            for pid in detached_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            time.sleep(0.05)


def main(argv):
    ap = argparse.ArgumentParser(prog='bench.py')
    ap.add_argument('--kit', default=os.path.join(HERE, 'kit.py'))
    ap.add_argument('--counts', default='0,40,190,390')
    ap.add_argument('--marked', type=int, default=10)
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--scans', type=int, default=40)
    ap.add_argument('--warmup', type=int, default=5)
    run(ap.parse_args(argv))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
