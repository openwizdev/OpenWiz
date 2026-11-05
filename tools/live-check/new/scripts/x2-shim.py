#!/usr/bin/env python3
"""X2: the call-counting shim for OpenWiz 0.0.4's live check (#13, sheet L-1 to L-12).

Copied from 0.0.3's kit (PR #152 at 3a7b501, scripts/x2-shim.py) and extended for
0.0.4's two writes: `thread spawn` (new) and `thread tell` with attachments (B-7).
Installed by new-kit.py as `<W>/x2/room-cli`, first on the PATH of every `openwiz`
and `openwiz-server` the check starts, so every room-cli call OpenWiz makes passes
through it. It calls the real room-cli by the absolute path in its step file, never
by PATH lookup. Standard-library Python 3.9.

Fail closed. It reads `step.json` next to itself on every call; no step file, or one
it cannot read, refuses everything (exit 97, nothing called). A step that allows a
write carries `expires_ms`: past it, the write is refused, so a step left armed by
an X1 that crashed lets nothing through.

**Any refusal taints the sitting (#168's R6, final round).** Every call X2 refuses, of
any kind and at any time, is written into the ledger under the lock as a taint, naming its
step, kind and reason. A tainted sitting admits no write again, and every X1 report decides
its outcome from that taint, last, under the same lock. Only a new setup clears it.

**One sitting, one ledger (#168's R1 and R2).** `ledger.json` next to it, made once at
setup, holds the run's write budget (4 creates, 2 sends: L-3, L-5), how much of it is
used, every plan step's consumed write (by the step's stable id, `auth`), and the step
file's generation. A write is admitted only **under `writes.lock`**, the same lock X1
holds to arm or disarm: X2 takes it, reads the step file again, refuses it if its
generation is not the one this call started under (X1 replaced it while the call
waited), or it has expired, or the write is not the step's, or the step's write was
already made (in this or any earlier invocation), or the budget is used up; and only
then records the write as consumed. No ledger refuses every write. A hold before the
call checks again, under the lock, after the hold; a call aborted before it reached
room-cli (zero calls, proven) gives its consumption back.

**One approval, every sitting (#168's R8).** The ledger names the approval's file, kept
outside every sitting's work directory: L-8's total (4 creates, 2 sends) and every write
charged under it, by any sitting. Under writes.lock, then the approval's own lock (always in
that order), X2 refuses a write whose step was already made under the approval, in any
sitting, or once the approval's total is charged; else it charges the write (`reserved`
while it holds, `dispatched` once it goes to room-cli). A charge is released only when zero
calls are proven (a hold aborted before room-cli); every other charge stays, uncertain ones
included. No readable approval refuses the write.

- A read on OpenWiz's allowlist (`cloud status --json` included): logged by kind (ids
  replaced by a target label or `other`) in reads.log, then exec'd.
- `thread spawn --project <id> --machine cloud --provider <h> --model <m>
  --reasoning-level <e> --request-id <rid> --json [(--file|--image) <path>]...
  --prompt <text>`: allowed only when the step allows a spawn, the project is the
  step's project (P-A), the harness, model and effort are the step's, the text's
  SHA-256 is the step's approved hash, the attachments are exactly the step's (flag,
  order, SHA-256 and size of the file at each path, read now), and fewer than
  `max_calls` writes were already allowed in this step.
- `thread tell <id> --mode queue|steer --json [(--file|--image) <path>]... -- <text>`:
  the same, for the step's thread (T-A or T-B) and mode.
- Anything else, including every other write: refused (exit 97), logged by shape.

Every write, allowed or not, is one line in writes.log: that is the call counter.
Never logged: the text, an id, a path, a model name. writes.log holds the step, the
kind, the target label, the text's SHA-256 and bytes, the attachments' flags and
SHA-256, and the outcome.

Fault modes, per step (sheet L-6):
- capture (default): the real room-cli replaces this process (exec), so OpenWiz's
  own timeout stops the real call, as without X2. A forked tee keeps a copy of its
  stdout and stderr in the capture files (0600, never leave the Mac).
- hold-before H: writes the marker `holding-before`, waits H seconds, then, under the
  lock, calls only if its parent is the process that started it and is still alive,
  the ledger can still be read and the sitting is not tainted (#168's R6: a refusal
  during the hold denies the held write too), and the write still passes every check of
  its first admission (the step's generation, its expiry, the target, settings or mode,
  text and each file's bytes). Otherwise it logs `aborted_parent_gone`,
  `aborted_disarmed`, `aborted_no_ledger`, `aborted_tainted`, `aborted_expired` or
  `aborted_changed`, gives its reservation back (in the ledger, the taint kept, and on
  the approval), and exits 98 without calling. An approval it can't read then aborts it
  too (`aborted_no_approval`), its charge kept.
- hold-after H: runs the real call as a child, keeps its output, writes the marker
  `answered-holding`, waits H seconds, then prints the output and exits with its
  code (the CLI killed mid-create: the thread exists, the answer never arrives).
"""

import contextlib
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
REQUEST_ID_RE = re.compile(r"ow1-[0-9a-f]{40}\Z")
SETTING_RE = re.compile(r"[!-~]{1,128}\Z")
LIST_VIEWS = ([], ["--include-hidden"], ["--include-archived"],
              ["--include-hidden", "--include-archived"])
PROVIDERS = ("codex", "claude-code")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MAX_FILE = 25 * 1024 * 1024


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
    if a in (["--version"], ["machine", "list", "--json"], ["cloud", "status", "--json"],
             ["project", "list", "--json", "--include-personal"],
             ["project", "list", "--json", "--include-personal", "--hidden"]):
        return True
    if a[:3] == ["thread", "list", "--json"] and a[3:] in LIST_VIEWS:
        return True
    return (len(a) == 4 and a[0] == "thread" and a[1] in ("show", "output")
            and bool(ID_RE.match(a[2])) and not a[2].startswith("-") and a[3] == "--json")


def pairs_of(rest):
    """[(flag, path)] for zero or more `--file|--image <absolute path>` pairs, else None."""
    if len(rest) % 2:
        return None
    out = []
    for flag, path in zip(rest[::2], rest[1::2]):
        if flag not in ("--file", "--image") or not os.path.isabs(path) or "\x00" in path:
            return None
        out.append((flag, path))
    return out


def tell_shape(a):
    """(id, mode, pairs, text) for the send's exact shape, else None."""
    if (len(a) >= 8 and a[:2] == ["thread", "tell"] and ID_RE.match(a[2]) and not a[2].startswith("-")
            and a[3] == "--mode" and a[4] in ("queue", "steer") and a[5] == "--json" and a[-2] == "--"):
        pairs = pairs_of(a[6:-2])
        if pairs is not None:
            return a[2], a[4], pairs, a[-1]
    return None


def spawn_shape(a):
    """(project, provider, model, effort, pairs, text) for the create's exact shape, else None."""
    head = ["thread", "spawn", "--project", None, "--machine", "cloud", "--provider", None, "--model", None,
            "--reasoning-level", None, "--request-id", None, "--json"]
    if len(a) < len(head) + 2 or a[-2] != "--prompt":
        return None
    for want, got in zip(head, a):
        if want is not None and want != got:
            return None
    project, provider, model, effort, rid = a[3], a[7], a[9], a[11], a[13]
    if not (ID_RE.match(project) and not project.startswith("-") and provider in PROVIDERS
            and SETTING_RE.match(model) and not model.startswith("-") and effort in EFFORTS
            and REQUEST_ID_RE.match(rid)):
        return None
    pairs = pairs_of(a[len(head):-2])
    if pairs is None:
        return None
    return project, provider, model, effort, pairs, a[-1]


def label_of(sid, targets):
    for lab, tid in targets.items():
        if tid == sid:
            return lab
    return "other"


def read_kind(a, targets):
    if len(a) >= 3 and a[0] == "thread" and a[1] in ("show", "output"):
        return " ".join([a[0], a[1], label_of(a[2], targets)] + a[3:])
    return " ".join(a)


def file_facts(path):
    """(sha256, size) of the file at the path now, or (None, None)."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE + 1)
        return hashlib.sha256(data).hexdigest(), len(data)
    except OSError:
        return None, None


def load_ledger():
    try:
        with open(os.path.join(HERE, "ledger.json")) as f:
            led = json.load(f)
        if not (isinstance(led, dict) and isinstance(led.get("budget"), dict) and isinstance(led.get("used"), dict)
                and isinstance(led.get("auth"), dict)):
            return None
        return led
    except (OSError, ValueError):
        return None


def save_ledger(led):
    tmp = os.path.join(HERE, "ledger.json.tmp.%d" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(led, f, sort_keys=True)
    os.replace(tmp, os.path.join(HERE, "ledger.json"))


def taint(entry, locked):
    """#168's R6, final round: any refusal, of any kind, at any time, taints the whole sitting.
    Written into the ledger under writes.lock (`locked`: the caller holds it already), with the
    refusal named by its step, kind and reason, never a value. Nothing clears it but a new
    setup. No ledger: nothing to taint (X1 can't use the sitting either)."""
    def write():
        led = load_ledger()
        if led is None:
            return
        led["tainted"] = True
        led["refusals"] = int(led.get("refusals", 0)) + 1
        named = led.setdefault("refused", [])
        if len(named) < 50:
            named.append({"step": str(entry.get("step") or "none").split("@")[0], "kind": entry.get("kind") or "other",
                          "why": entry.get("why")})
        save_ledger(led)
    if locked:
        write()
        return
    with open(os.path.join(HERE, "writes.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        write()


def refuse(entry, why, locked=False):
    """Refuses this call (exit 97, nothing called): logged, and the sitting tainted."""
    entry.update(outcome="refused", why=why)
    append("writes.log" if entry.get("kind") in ("spawn", "tell") else "refused.log", entry)
    taint(entry, locked)
    sys.stderr.write("x2: refused (%s)\n" % why)
    sys.exit(REFUSED)


def give_back(auth, kind):
    """Zero calls proven (aborted before room-cli): the write's consumption goes back."""
    led = load_ledger()
    if led is None:
        return
    a = led["auth"].get(auth) or {}
    a["calls"] = max(0, int(a.get("calls", 0)) - 1)
    led["auth"][auth] = a
    led["used"][kind] = max(0, int(led["used"].get(kind, 0)) - 1)
    save_ledger(led)


def load_approval(path):
    """The approval's file (#168's R8): L-8's total and every charge made under it, by any sitting."""
    try:
        with open(path) as f:
            ap = json.load(f)
        if not (isinstance(ap, dict) and isinstance(ap.get("total"), dict) and isinstance(ap.get("charges"), list)
                and all(isinstance(c, dict) for c in ap["charges"])):
            return None
        return ap
    except (OSError, ValueError, TypeError):
        return None


def save_approval(path, ap):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(ap, f, sort_keys=True)
    os.replace(tmp, path)


@contextlib.contextmanager
def approval_locked(path):
    """The approval's own lock: taken inside writes.lock, never the other way round."""
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def charges(ap, kind=None, auth=None):
    """The charges that count: every one not released (zero calls proven), uncertain ones included."""
    return [c for c in ap["charges"] if c.get("state") != "released"
            and (kind is None or c.get("kind") == kind) and (auth is None or c.get("auth") == auth)]


def move_charge(path, cid, state, outcome=None):
    """This call's charge moves on: `dispatched`, or `released` (zero calls proven). False if
    the approval can't be read or written: the charge then stays as it was (charged)."""
    try:
        with approval_locked(path):
            ap = load_approval(path)
            mine = [c for c in ap["charges"] if c.get("id") == cid] if ap else []
            if len(mine) != 1 or mine[0].get("state") != "reserved":
                return False
            mine[0].update(state=state, **({"outcome": outcome} if outcome else {}))
            save_approval(path, ap)
            return True
    except OSError:
        return False


def load_step():
    try:
        with open(os.path.join(HERE, "step.json")) as f:
            step = json.load(f)
        if not (isinstance(step, dict) and isinstance(step.get("step"), str)
                and os.path.isabs(step.get("real_room_cli", ""))
                and isinstance(step.get("targets"), dict)):
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


def why_not(step, kind, target, fields, text, pairs):
    """None if the step allows this one write; else why not (never a value)."""
    allow = step.get("allowed_write")
    if not isinstance(allow, dict) or allow.get("kind") != kind:
        return "this step allows no %s" % kind
    if not isinstance(step.get("expires_ms"), int) or now_ms() > step["expires_ms"]:
        return "this step has expired"
    if target == "other" or allow.get("target") != target:
        return "not this step's %s" % ("project" if kind == "spawn" else "thread")
    for k, v in fields.items():
        if allow.get(k) != v:
            return "not this step's %s" % k
    if allow.get("text_sha256") != hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest():
        return "not this step's approved text"
    want = allow.get("attachments") or []
    if len(want) != len(pairs):
        return "not this step's attachments"
    for w, (flag, path) in zip(want, pairs):
        digest, size = file_facts(path)
        if w.get("flag") != flag or w.get("sha256") != digest or w.get("size") != size:
            return "not this step's attachments"
    return None


def main():
    argv = sys.argv[1:]
    step = load_step()
    if step is None:
        refuse({"t_ms": now_ms(), "step": None, "shape": " ".join(argv[:2])}, "no step file")
    name, real, targets = step["step"], step["real_room_cli"], step["targets"]
    started_gen = step.get("generation")  # the step this call started under
    if read_allowed(argv):
        append("reads.log", {"t_ms": now_ms(), "step": name, "kind": read_kind(argv, targets)})
        os.execv(real, [real] + argv)
    spawn, tell = spawn_shape(argv), tell_shape(argv)
    if spawn is None and tell is None:
        shape = " ".join(a for a in argv if a.startswith("-") or a in ("thread", "tell", "spawn", "list", "show"))
        kind = "spawn" if argv[1:2] == ["spawn"] else "tell" if argv[1:2] == ["tell"] else None
        entry = {"t_ms": now_ms(), "step": name, "shape": shape}
        if kind:
            entry["kind"] = kind
        refuse(entry, "not on OpenWiz's allowlist")
    if spawn is not None:
        project, provider, model, effort, pairs, text = spawn
        kind, target = "spawn", label_of(project, targets)
        fields = {"provider": provider, "model": model, "effort": effort}
    else:
        sid, mode, pairs, text = tell
        kind, target = "tell", label_of(sid, targets)
        fields = {"mode": mode}
    body = text.encode("utf-8", "surrogateescape")
    entry = {"t_ms": now_ms(), "step": name, "kind": kind, "target": target,
             "text_sha256": hashlib.sha256(body).hexdigest(), "text_bytes": len(body),
             "attachments": [{"flag": f, "sha256": file_facts(p)[0]} for f, p in pairs], "pid": os.getpid()}
    if kind == "tell":
        entry["mode"] = fields["mode"]
    # Admission: under the lock X1 holds to arm and disarm (#168's R2), on the step file as
    # it is now, against the sitting's ledger (#168's R1). Nothing is judged before the lock.
    with open(os.path.join(HERE, "writes.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cur = load_step()
        led = load_ledger()
        if cur is None:
            why = "no readable step file"
        elif cur.get("generation") != started_gen or cur.get("step") != name:
            why = "the step changed while this call waited"
        elif led is None:
            why = "no readable ledger"
        elif led.get("tainted"):
            why = "the sitting is tainted: X2 refused a call before"
        else:
            step = cur
            why = why_not(step, kind, target, fields, text, pairs)
        if why is None:
            allow = step["allowed_write"]
            auth = allow.get("auth")
            done = int((led["auth"].get(auth) or {}).get("calls", 0)) if isinstance(auth, str) else None
            appr = led.get("approval")
            if done is None:
                why = "this step's write has no authorisation"
            elif done >= int(allow.get("max_calls", 1)):
                why = "this step's write was already made"
            elif int(led["used"].get(kind, 0)) >= int(led["budget"].get(kind, 0)):
                why = "the run's write budget is used up"
            elif not (isinstance(appr, str) and os.path.isabs(appr)):
                why = "the ledger names no approval"
        entry["generation"] = (cur or {}).get("generation")
        if why is not None:
            refuse(entry, why, locked=True)
        fault = step.get("fault", "capture")
        # #168's R8: the approval's allowance, across every sitting, under its own lock (inside this one).
        cid = "%s-%d-%d" % (led.get("sitting"), os.getpid(), now_ms())
        try:
            with approval_locked(appr):
                ap = load_approval(appr)
                if ap is None:
                    why = "no readable approval"
                elif len(charges(ap, auth=auth)) >= int(allow.get("max_calls", 1)):
                    why = "this step's write was already made under this approval (sitting %s)" % (
                        charges(ap, auth=auth)[0].get("sitting"))
                elif len(charges(ap, kind=kind)) >= int(ap["total"].get(kind, 0)):
                    why = "the approval's allowance is used up"
                else:
                    ap["charges"].append(dict({"id": cid, "sitting": led.get("sitting"), "auth": auth, "kind": kind,
                                               "state": "reserved" if fault == "hold-before" else "dispatched",
                                               "t_ms": now_ms()}, **({"op": argv[13]} if kind == "spawn" else {})))
                    save_approval(appr, ap)
        except OSError:
            why = "no readable approval"
        if why is not None:
            refuse(entry, why, locked=True)
        led["auth"][auth] = {"kind": kind, "calls": done + 1}
        led["used"][kind] = int(led["used"].get(kind, 0)) + 1
        save_ledger(led)
        entry["fault"] = fault
        entry["outcome"] = "holding" if fault == "hold-before" else "called"
        append("writes.log", entry)
    n = sum(1 for _ in open(os.path.join(HERE, "writes.log")))
    base = os.path.join(HERE, "capture-%s-%s-%d" % (kind, re.sub(r"[^A-Za-z0-9_.-]", "_", name), n))
    hold = float(step.get("hold_s", 0))
    marker = {"pid": os.getpid(), "ppid": os.getppid(), "t_ms": now_ms()}
    if fault == "hold-before":
        parent = os.getppid()
        with open(os.path.join(HERE, "holding-before"), "w") as f:
            json.dump(marker, f)
        time.sleep(hold)
        with open(os.path.join(HERE, "writes.lock"), "a") as lock:  # judged again, under the lock
            fcntl.flock(lock, fcntl.LOCK_EX)
            alive = True
            try:
                os.kill(parent, 0)
            except OSError:
                alive = False
            # #168's R2, round 2: judged again on everything the first admission judged (the
            # step's generation, its expiry, and the whole payload: target, settings or mode, text
            # and each file's bytes), keeping the reservation it already holds. #168's R6 (Jake's
            # (a)): and on the ledger as it is now: unreadable, or tainted by a refusal during the
            # hold, aborts it before the call.
            now, why, led_now = load_step(), None, load_ledger()
            if os.getppid() != parent or not alive:
                outcome = "aborted_parent_gone"
            elif now is None or now.get("generation") != entry["generation"] or now.get("step") != name:
                outcome = "aborted_disarmed"
            elif led_now is None:
                outcome = "aborted_no_ledger"
            elif led_now.get("tainted"):
                outcome = "aborted_tainted"
            else:
                why = why_not(now, kind, target, fields, text, pairs)
                outcome = None if why is None else "aborted_expired" if "expired" in why else "aborted_changed"
            if outcome is None and not move_charge(appr, cid, "dispatched"):
                outcome = "aborted_no_approval"  # its charge stays: it can't be moved on, nor released
            if outcome is not None:  # nothing reached room-cli: the reservation goes back, the taint stays
                give_back(auth, kind)
                if outcome != "aborted_no_approval":
                    move_charge(appr, cid, "released", outcome)
                append("writes.log", dict(entry, t_ms=now_ms(), outcome=outcome, **({"why": why} if why else {})))
                sys.exit(ABORTED)
            append("writes.log", dict(entry, t_ms=now_ms(), outcome="called_after_hold"))
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
