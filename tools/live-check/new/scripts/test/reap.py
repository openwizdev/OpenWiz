#!/usr/bin/env python3
"""Test-only: stops what one test suite started, and nothing else. SYNTHETIC ONLY.

    reap.py <token>

Fixes #152's R11 (Sol, round 2): that suite's cleanup killed any listener on its
port range whose command line named a server, which another run's or another agent's
server could match. Here ownership is proved, not guessed: lib.sh makes a random
128-bit token and exports it as KIT13_OWNER, so every process the suite starts (the
kit, its supervisors and guards, the servers, the stand-ins, and anything they start)
inherits it in its environment. This reaper reads each process's environment
(/proc/<pid>/environ: Linux, where the suites run) and signals only those that carry
exactly `KIT13_OWNER=<token>`, never itself or its ancestors. A process without the
token, whatever its name or port, is never signalled. Prints how many it stopped.
"""
import os
import signal
import sys
import time

token = sys.argv[1]
want = ("KIT13_OWNER=%s" % token).encode()
if len(token) < 32:
    sys.exit("reap.py: a token of at least 32 characters is needed")


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def owned():
    skip = ancestors()
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in skip:
            continue
        try:
            with open("/proc/%s/environ" % name, "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        if want in env:
            out.append(int(name))
    return out


stopped = 0
for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
    pids = owned()
    for pid in pids:
        try:
            os.kill(pid, sig)
            stopped += sig == signal.SIGTERM
        except OSError:
            pass
    end = time.monotonic() + wait
    while pids and time.monotonic() < end and owned():
        time.sleep(0.1)
print(stopped)
