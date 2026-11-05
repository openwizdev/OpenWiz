#!/usr/bin/env python3
"""X2: the call-counting shim for OpenWiz 0.0.3's live test (#10, L-9).

Installed by send-kit.py as `<W>/x2/room-cli`, first on the PATH of every
`openwiz` and `openwiz-server` the run starts, so every room-cli call OpenWiz
makes passes through it. It calls the real room-cli by the absolute path in
its step file, never by PATH lookup. Standard-library Python 3.9.

Fail closed. It reads `step.json` next to itself on every call; no step file,
or one it cannot read, refuses everything (exit 97, nothing called). A step that
allows a tell carries `expires_ms`: past it, the tell is refused, so a step left
armed by an X1 that crashed lets nothing through.

- A read on OpenWiz's allowlist: logged by kind (ids replaced by a test-thread
  label or `other`) in reads.log, then exec'd.
- `thread tell <id> --mode queue|steer --json -- <text>`: allowed only when
  the step allows a tell, the id is that step's test thread, the mode is the
  step's mode and the text's SHA-256 is the step's approved hash, and fewer
  than `max_calls` tells (default 1) were already allowed in this step. Every
  tell, allowed or not, is one line in tell.log: that is the call counter.
- Anything else, including every other tell: refused (exit 97), logged by shape.

The sitting ledger (Sol R13; the orchestrator's rule for the 0.0.4 kit): every
refusal, a tell or any other call, and every held tell aborted as revoked, is one
line in `sitting.log`, written under `tell.lock`. Any line taints the whole
sitting; X1 decides every outcome from it, under the same lock, when it publishes.
Only a new setup (a new work directory) clears it. A tainted or unreadable ledger
(setup makes it empty; a missing one is unreadable) admits no tell, and a tell
held before its call is aborted (`aborted_tainted`, its reservation returned, the
taint kept) if the ledger is tainted or unreadable when the hold ends.

The allowance (Sol's R8 on #168): L-8's 23 sends are one budget for every sitting,
kept in a directory outside them (`allowance` in the step file): `allowance.json`
holds the total, `charges.log` every reservation and release, under
`allowance.lock`. A tell is admitted only if its step has no call charged in any
sitting and the total is not used up; it is reserved then, and released only when
it made no call (a zero-call abort). An unreadable allowance admits no tell. Setup
creates `charges.log`, empty, with `allowance.json`; from then on a missing or
unreadable journal (or one releasing more than it reserved) is unknown usage, never
zero (Sol R14): it admits no tell, stops for Jake to reconcile, and X2 never
recreates it (a release only appends to an existing journal).

Fault modes, per step (#10's L6 and L7; decided L-6):
- capture (default): the real room-cli replaces this process (exec), so
  OpenWiz's own timeout stops the real call, as without X2. A forked tee keeps a
  copy of its stdout and stderr in the capture files (0600, never leave the Mac).
- hold-before H: writes the marker `holding-before`, waits H seconds, then calls
  only if its parent is the process that started it and is still alive.
  Otherwise it logs `aborted_parent_gone` and exits 98 without calling. Then,
  under the same lock as admission, it reads the step again: unless it is still
  the very arming it was admitted on (the same `auth`), for the same thread, mode
  and text, and not expired, it logs `aborted_revoked` and exits 98 without
  calling (Sol R12). Either way its reservation stays used.
- hold-after H: runs the real call as a child, keeps its output, writes the
  marker `answered-holding`, waits H seconds, then prints the output and exits
  with its code (OpenWiz stops it first at its 15 s call timeout when H >= 15).

Never logged: the text, an id, a title. tell.log holds the step label, the
thread label, the mode, the text's SHA-256 and byte count, and the outcome.
"""

import fcntl
import hashlib
import json
import os
import re
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
REFUSED, ABORTED = 97, 98
ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}\Z")
LIST_VIEWS = ([], ["--include-hidden"], ["--include-archived"],
              ["--include-hidden", "--include-archived"])


def now_ms():
    return time.time_ns() // 1_000_000


def append(name, entry):
    """One JSON line, one write, O_APPEND: concurrent calls never interleave."""
    fd = os.open(os.path.join(HERE, name), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)


def read_allowed(a):
    """OpenWiz's read allowlist (crates/adapters/cloudroom/src/allowlist.rs), kept
    apart from OpenWiz's and the fake's copies so a mistake in one is caught."""
    if a in (["--version"], ["machine", "list", "--json"],
             ["project", "list", "--json", "--include-personal"],
             ["project", "list", "--json", "--include-personal", "--hidden"]):
        return True
    if a[:3] == ["thread", "list", "--json"] and a[3:] in LIST_VIEWS:
        return True
    return (len(a) == 4 and a[0] == "thread" and a[1] in ("show", "output")
            and bool(ID_RE.match(a[2])) and not a[2].startswith("-") and a[3] == "--json")


def tell_shape(a):
    """(id, mode, text) for the one write's exact shape, else None."""
    if (len(a) == 8 and a[:2] == ["thread", "tell"] and ID_RE.match(a[2])
            and not a[2].startswith("-") and a[3] == "--mode" and a[4] in ("queue", "steer")
            and a[5] == "--json" and a[6] == "--"):
        return a[2], a[4], a[7]
    return None


def label_of(sid, threads):
    for lab, tid in threads.items():
        if tid == sid:
            return lab
    return "other"


def read_kind(a, threads):
    if len(a) >= 3 and a[0] == "thread" and a[1] in ("show", "output"):
        return " ".join([a[0], a[1], label_of(a[2], threads)] + a[3:])
    return " ".join(a)


def taint(step, kind, why, tell, locked=False):
    """One line in the sitting ledger, under tell.lock (`locked`: the caller holds it)."""
    entry = {"t_ms": now_ms(), "step": step, "kind": kind, "why": why, "tell": tell}
    if locked:
        append("sitting.log", entry)
        return
    with open(os.path.join(HERE, "tell.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        append("sitting.log", entry)


def ledger_state():
    """clean, tainted or unreadable: the sitting ledger, read by a holder of tell.lock."""
    try:
        with open(os.path.join(HERE, "sitting.log")) as f:
            lines = [json.loads(line) for line in f]
    except (OSError, ValueError):
        return "unreadable"
    return "tainted" if lines else "clean"


RECONCILE = ("the allowance's charge journal is missing or unreadable: its usage is unknown, never zero; "
             "ask Jake to reconcile it")


def allowance(step, change):
    """Under allowance.lock: `reserve` (None if reserved, else why not) or `release`. The charge
    journal must exist and read whole (Sol R14); it is appended to, never created."""
    d = step.get("allowance")
    if not (isinstance(d, str) and os.path.isabs(d)):
        return "the allowance cannot be read"
    try:
        with open(os.path.join(d, "allowance.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with open(os.path.join(d, "allowance.json")) as f:
                total = int(json.load(f)["total"])
            by = {}
            path = os.path.join(d, "charges.log")
            try:
                with open(path) as f:
                    for line in f:
                        e = json.loads(line)
                        by[e["step"]] = by.get(e["step"], 0) + {"reserve": 1, "release": -1}[e["op"]]
            except (OSError, ValueError, KeyError, TypeError):
                return RECONCILE
            if any(k < 0 for k in by.values()):
                return RECONCILE
            n = sum(by.values())
            if change == "reserve":
                if by.get(step["step"], 0) >= int((step.get("allowed_tell") or {}).get("max_calls", 1)):
                    return "this step's call is charged already (this sitting or an earlier one)"
                if n >= total:
                    return "the approved allowance (L-8) is used up"
            fd = os.open(path, os.O_WRONLY | os.O_APPEND)  # never O_CREAT: no history is recreated
            try:
                os.write(fd, (json.dumps({"t_ms": now_ms(), "sitting": step.get("sitting"), "step": step["step"],
                                          "op": change}, sort_keys=True) + "\n").encode())
            finally:
                os.close(fd)
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return "the allowance cannot be read"


def refuse(step, why, shape):
    """A call off the allowlist: refused, and the sitting tainted. One shaped like a tell
    (`--file`, `auto`) is also counted in tell.log, as a refused attempt in its step."""
    tell = shape.startswith("thread tell")
    if tell:
        append("tell.log", {"t_ms": now_ms(), "step": step, "outcome": "refused", "why": why, "shape": shape})
    taint(step, "refused", why + ": " + shape, tell)
    sys.stderr.write("x2: refused (%s)\n" % why)
    sys.exit(REFUSED)


def load_step():
    try:
        with open(os.path.join(HERE, "step.json")) as f:
            step = json.load(f)
        if not (isinstance(step, dict) and isinstance(step.get("step"), str)
                and os.path.isabs(step.get("real_room_cli", ""))
                and isinstance(step.get("threads"), dict)):
            return None
        return step
    except (OSError, ValueError):
        return None


def tee_exec(real, argv, base):
    """exec the real room-cli; a forked child copies its stdout and stderr to the
    capture files and on to OpenWiz's pipes. The real call is OpenWiz's direct
    child, so OpenWiz's timeout stops it."""
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    pid = os.fork()
    if pid == 0:  # the tee
        os.close(out_w)
        os.close(err_w)
        import select
        files = {}
        for fd, name, dest in ((out_r, ".out", 1), (err_r, ".err", 2)):
            files[fd] = (os.open(base + name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), dest)
        open_fds = [out_r, err_r]
        while open_fds:
            ready, _, _ = select.select(open_fds, [], [])
            for fd in ready:
                data = os.read(fd, 65536)
                if not data:
                    open_fds.remove(fd)
                    continue
                cap, dest = files[fd]
                os.write(cap, data)
                try:
                    os.write(dest, data)
                except OSError:
                    pass
        os._exit(0)
    os.close(out_r)
    os.close(err_r)
    os.dup2(out_w, 1)
    os.dup2(err_w, 2)
    os.close(out_w)
    os.close(err_w)
    os.execv(real, [real] + argv)


def main():
    argv = sys.argv[1:]
    step = load_step()
    if step is None:
        refuse(None, "no readable step file", " ".join(argv[:2]))
    name, real, threads = step["step"], step["real_room_cli"], step["threads"]
    if read_allowed(argv):
        append("reads.log", {"t_ms": now_ms(), "step": name, "kind": read_kind(argv, threads)})
        os.execv(real, [real] + argv)
    tell = tell_shape(argv)
    if tell is None:
        refuse(name, "not on OpenWiz's allowlist", " ".join(a for a in argv if a.startswith("-")
                                                           or a in ("thread", "tell", "list", "show")))
    sid, mode, text = tell
    sha = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()
    # Admission happens entirely under the lock that X1 takes to arm or disarm a step (Sol's
    # review of the 0.0.4 kit, PR #168, finding 2): the step is read again here, so a tell
    # that waited on the lock while the step was disarmed is refused, never admitted on the
    # step it saw before it waited. The same lock makes the call counter exact.
    with open(os.path.join(HERE, "tell.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        step = load_step() or {"step": None, "threads": {}, "allowed_tell": None}
        name, threads, real = step["step"], step["threads"], step.get("real_room_cli")
        lab = label_of(sid, threads)
        entry = {"t_ms": now_ms(), "step": name, "thread": lab, "mode": mode, "text_sha256": sha,
                 "text_bytes": len(text.encode("utf-8", "surrogateescape")), "pid": os.getpid()}
        allow = step.get("allowed_tell")
        auth = step.get("auth")
        why = None
        state = ledger_state()
        if state != "clean":
            why = "the sitting's ledger is %s" % state
        elif not isinstance(allow, dict):
            why = "this step allows no tell"
        elif not isinstance(step.get("expires_ms"), int) or now_ms() > step["expires_ms"]:
            why = "this step has expired"
        elif lab == "other" or allow.get("thread") != lab:
            why = "not this step's thread"
        elif allow.get("mode") != mode:
            why = "not this step's mode"
        elif allow.get("text_sha256") != sha:
            why = "not this step's approved text"
        if why is None:
            used = 0
            path = os.path.join(HERE, "tell.log")
            if os.path.exists(path):
                with open(path) as f:
                    for line in f:
                        e = json.loads(line)
                        if e.get("step") == name and e.get("outcome") in ("called", "holding"):
                            used += 1
                        elif e.get("step") == name and e.get("outcome") == "aborted_tainted":
                            used -= 1  # a reservation returned
            if used >= int(allow.get("max_calls", 1)):
                why = "this step's calls are used up"
        if why is None:
            why = allowance(step, "reserve")  # the last check: a reservation once it passes
        if why is not None:
            entry.update(outcome="refused", why=why)
            append("tell.log", entry)
            taint(name, "refused", why, tell=True, locked=True)
            sys.stderr.write("x2: refused (%s)\n" % why)
            sys.exit(REFUSED)
        fault = step.get("fault", "capture")
        entry["fault"] = fault
        entry["outcome"] = "holding" if fault == "hold-before" else "called"
        append("tell.log", entry)
    n = sum(1 for _ in open(os.path.join(HERE, "tell.log")))
    base = os.path.join(HERE, "capture-%s-%d" % (re.sub(r"[^A-Za-z0-9_.-]", "_", name), n))
    hold = float(step.get("hold_s", 0))
    marker = {"pid": os.getpid(), "ppid": os.getppid(), "t_ms": now_ms()}
    if fault == "hold-before":
        parent = os.getppid()
        with open(os.path.join(HERE, "holding-before"), "w") as f:
            json.dump(marker, f)
        time.sleep(hold)
        alive = True
        try:
            os.kill(parent, 0)
        except OSError:
            alive = False
        if os.getppid() != parent or not alive:
            append("tell.log", dict(entry, t_ms=now_ms(), outcome="aborted_parent_gone"))
            allowance(step, "release")  # zero calls: the send goes back to the allowance
            sys.exit(ABORTED)
        # Sol R12: the hold outlives the admission, so the call is authorised again, under
        # the admission lock: the same arming (auth), binding and expiry, or no call. The
        # holding line stays, so the reservation is still used.
        with open(os.path.join(HERE, "tell.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            now = load_step() or {}
            still = now.get("allowed_tell")
            state = ledger_state()
            if state != "clean":  # Sol on #168: the sitting was tainted during the hold
                append("tell.log", dict(entry, t_ms=now_ms(), outcome="aborted_tainted", why="the ledger is " + state))
                allowance(step, "release")
                sys.stderr.write("x2: aborted (the sitting's ledger is %s)\n" % state)
                sys.exit(ABORTED)
            why = None
            if not isinstance(auth, str) or now.get("auth") != auth or now.get("step") != name:
                why = "the step was disarmed or replaced during the hold"
            elif not isinstance(now.get("expires_ms"), int) or now_ms() > now["expires_ms"]:
                why = "the step expired during the hold"
            elif not isinstance(still, dict) or (still.get("thread"), still.get("mode"), still.get("text_sha256")) \
                    != (allow.get("thread"), allow.get("mode"), allow.get("text_sha256")) \
                    or label_of(sid, now.get("threads") or {}) != lab or now.get("real_room_cli") != real:
                why = "the step's binding changed during the hold"
            if why is not None:
                append("tell.log", dict(entry, t_ms=now_ms(), outcome="aborted_revoked", why=why))
                taint(name, "revoked", why, tell=True, locked=True)
                allowance(step, "release")
                sys.stderr.write("x2: aborted (%s)\n" % why)
                sys.exit(ABORTED)
            append("tell.log", dict(entry, t_ms=now_ms(), outcome="called_after_hold"))
        tee_exec(real, argv, base)
    if fault == "hold-after":
        import subprocess
        p = subprocess.run([real] + argv, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for suffix, data in ((".out", p.stdout), (".err", p.stderr)):
            fd = os.open(base + suffix, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, data)
            os.close(fd)
        with open(os.path.join(HERE, "answered-holding"), "w") as f:
            json.dump(dict(marker, t_ms=now_ms()), f)
        time.sleep(hold)
        sys.stdout.buffer.write(p.stdout)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(p.stderr)
        sys.exit(p.returncode)
    tee_exec(real, argv, base)


if __name__ == "__main__":
    main()
