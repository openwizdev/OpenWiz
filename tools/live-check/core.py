#!/usr/bin/env python3
"""Private shared safety mechanics from the reviewed #152/#168 kits.

Python 3.9, standard library only. Policy (targets, budgets, ledgers, steps,
publication and read allowlists) belongs to the send and new drivers.
"""
import hashlib
import http.client
import importlib.util
import json
import os
import re
import secrets
import select
import signal
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True
OBSERVER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "observer")
spec = importlib.util.spec_from_file_location("quick_check", os.path.join(OBSERVER_DIR, "quick-check.py"))
qc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qc)
observe = qc.observe
Stop = observe.Stop
JUDGED_FIELDS = tuple(qc.COMPARED) + ("queuedWork", "pending", "activity")

CHILD_WRAPPER = (
    "import os, select, signal, subprocess, sys\n"
    "if os.read(0, 1) != b'g':\n"
    "    sys.exit(3)\n"
    "p = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL)\n"
    "while True:\n"
    "    r, _, _ = select.select([0], [], [], 0.5)\n"
    "    if r:\n"
    "        b = os.read(0, 1)\n"
    "        try:\n"
    "            p.send_signal(signal.SIGKILL if b == b'k' else signal.SIGTERM)\n"
    "        except OSError:\n"
    "            pass\n"
    "        try:\n"
    "            p.wait(10)\n"
    "        except subprocess.TimeoutExpired:\n"
    "            p.kill()\n"
    "            p.wait(5)\n"
    "        sys.exit(0)\n"
    "    if p.poll() is not None:\n"
    "        sys.exit(0)\n")


def sha(text):  # noop
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_ms():
    return time.time_ns() // 1_000_000


def write_private(path, data):
    observe.write_private(path, data if isinstance(data, (str, bytes)) else json.dumps(data, indent=1, sort_keys=True))


def in_repository(path):
    p = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return True
        up = os.path.dirname(p)
        if up == p:
            return False
        p = up


def structure(v):
    """Key names and JSON types, recursively, never a value (L4, L10)."""
    if isinstance(v, dict):
        return {k: structure(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        return [structure(v[0])] if v else []
    return "null" if v is None else type(v).__name__


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


def wait_for(cond, timeout, poll=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(poll)
    return cond()


def marker(kit, name):
    return os.path.exists(os.path.join(kit.x2, name))


def identity(pid):
    """What the kit records of a process before it may ever signal it: its PID, its
    start time and its full command line (ps works the same on macOS and Linux).
    None if it is not running (or is a zombie)."""
    r = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-o", "args=", "-p", str(pid)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    line = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode != 0 or not line or line.startswith("Z"):
        return None
    parts = line.split(None, 6)  # stat, then lstart's five words, then args
    if len(parts) < 7:
        return None
    return {"pid": pid, "lstart": " ".join(parts[1:6]), "args": parts[6]}


def signal_if_same(ident, sig):
    """Signals the process only if its PID still names the very process recorded
    (same start time, same command line). A reused or vanished PID is never signalled."""
    if not ident:
        return False
    cur = identity(ident["pid"])
    after = ident.get("args_after_go")  # a swap child: the wrapper's line, then the server's once it execs
    if cur is None or cur["lstart"] != ident["lstart"] or not (
            cur["args"] == ident["args"] or (after and (cur["args"] == after or cur["args"].endswith(" " + after)))):
        return False
    try:
        os.kill(ident["pid"], sig)
    except OSError:
        return False
    return True


def port_answers(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def health(port):
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/v1/health", headers={"Host": "127.0.0.1:%d" % port})
        ok = conn.getresponse().status == 200
        conn.close()
        return ok
    except (OSError, http.client.HTTPException):
        return False


def listeners(port):
    r = subprocess.run(["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return {int(x) for x in r.stdout.split()}


def confirmed_old(kit):
    """The process serving the port, if it is exactly the confirmed 0.0.2 launch: the
    listener's command line equals the recorded one, and its binary's sha256 is the
    recorded one. None if nothing listens; Stop if anything else does."""
    c = kit.cfg
    port, cmd = c["port"], c.get("restore_cmd")
    if not cmd:
        raise Stop("no confirmed 0.0.2 launch given at setup")
    pids = listeners(port)
    if not pids:
        if port_answers(port):
            raise Stop("something answers on port %d but no listener could be identified; nothing was signalled" % port)
        return None
    idents = [identity(p) for p in pids]
    if len(idents) != 1 or idents[0] is None or idents[0]["args"] != " ".join(cmd) \
            or observe.file_sha256(cmd[0]) != c.get("restore_sha256"):
        raise Stop("what answers on port %d is not the confirmed launch; nothing was signalled" % port)
    return idents[0]


def restore_old(kit):
    """Starts the confirmed 0.0.2 launch, detached, logging where it always did."""
    c = kit.cfg
    if port_answers(c["port"]):
        return False
    log = os.open(c["restore_log"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    p = subprocess.Popen(c["restore_cmd"], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         cwd=os.path.dirname(c["restore_log"]), start_new_session=True)
    os.close(log)
    swap_write(kit, restored_old=identity(p.pid))  # what the kit started, for the record
    return wait_for(lambda: health(c["port"]), 20, 0.3)


def swap_state(kit):
    try:
        return json.load(open(os.path.join(kit.run, "swap.json")))
    except (OSError, ValueError):
        return {}


def swap_write(kit, **kw):
    st = swap_state(kit)
    st.update(kw)
    tmp = os.path.join(kit.run, "swap.json.tmp.%d" % os.getpid())
    write_private(tmp, st)
    os.replace(tmp, os.path.join(kit.run, "swap.json"))
    return st


def close_gate(kit):
    """X2 lets no tell through from now on (reads still pass for Jake's page)."""
    kit.arm("closed")


class Gone(Exception):
    """The other end of a swap pipe went away."""


def _stop_signals():
    def handler(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def guard(kit, minutes):
    """The swap's owner (see above). Its stdin carries the supervisor's requests, one
    JSON line each; its stdout carries one reply per request."""
    c = kit.cfg
    backstop = now_ms() + int(minutes * 60000) + 60000  # the supervisor's deadline, plus a minute
    env = kit.env()
    kit.path_guard(env)
    wrapper = None
    old_stopped = False
    buf = [b""]
    inbox = []
    _stop_signals()

    def poll_request(timeout):
        if b"\n" not in buf[0]:
            r, _, _ = select.select([0], [], [], timeout)
            if not r:
                return None
            data = os.read(0, 4096)
            if not data:
                raise Gone()
            buf[0] += data
        if b"\n" not in buf[0]:
            return None
        line, buf[0] = buf[0].split(b"\n", 1)
        return json.loads(line)

    def reply(**kw):
        try:
            os.write(1, (json.dumps(kw) + "\n").encode())
        except OSError:
            raise Gone()

    def wait_or_gone(cond, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            req = poll_request(0.2)
            if req is not None:
                inbox.append(req)
        return cond()

    def start_server():
        nonlocal wrapper
        log = os.open(os.path.join(kit.run, "server.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        argv = [c["server"], "--port", str(c["port"]), "--allowed-host", c["host"]]
        if c.get("web_root"):
            argv += ["--web-root", c["web_root"]]
        wrapper = subprocess.Popen([sys.executable, "-c", CHILD_WRAPPER] + argv, env=env, stdin=subprocess.PIPE,
                                   stdout=log, stderr=log, start_new_session=True)
        os.close(log)
        wrapper.stdin.write(b"g")
        wrapper.stdin.flush()
        return wait_or_gone(lambda: health(c["port"]), 15)

    def stop_server(how=b"t", sweep=False):
        """Asks the wrapper to stop the server (it signals it, and waits for it), waits
        until the wrapper has exited (a zombie: still unreaped, so its group cannot be
        reused), then reaps it: the exit confirmed by waitpid. With `sweep` (the swap's
        end), anything still in that group is killed first. Not for F4 and F6: there an
        in-flight room-cli call (X2 holding) must be left to end by itself, as it would
        without the kit."""
        nonlocal wrapper
        if wrapper is None:
            return
        try:
            wrapper.stdin.write(how)
            wrapper.stdin.flush()
        except OSError:
            pass
        exited = wait_for(lambda: identity(wrapper.pid) is None, 15, 0.1)
        if sweep or not exited:
            try:
                os.killpg(wrapper.pid, signal.SIGKILL)
            except OSError:
                pass
        wrapper.wait()
        wrapper = None
        wait_for(lambda: not port_answers(c["port"]), 10)

    def finish(state):
        """Stops X1's server (confirmed), then puts 0.0.2 back: restarted if the guard
        stopped it, or confirmed still serving if it never did."""
        close_gate(kit)
        stop_server(sweep=True)
        ok = (not port_answers(c["port"]) and restore_old(kit)) if old_stopped else health(c["port"])
        swap_write(kit, state=state if ok else "restore-failed")

    def takeover():
        nonlocal old_stopped
        old = confirmed_old(kit)
        swap_write(kit, old_was_running=old is not None)
        if old is not None:
            if not signal_if_same(old, signal.SIGTERM):
                raise Stop("the 0.0.2 server could not be stopped")
            old_stopped = True
            if not wait_for(lambda: not port_answers(c["port"]), 15):
                raise Stop("the 0.0.2 server did not stop")
        else:
            old_stopped = True  # nothing was serving: restore it at the end all the same
        return start_server()

    try:
        while True:
            if now_ms() > backstop:  # the supervisor overran: end without it
                finish("restored-by-guard")
                return
            req = inbox.pop(0) if inbox else poll_request(1.0)
            if req is None:
                continue
            op = req.get("op")
            if op == "takeover" or op == "start":
                if not (takeover() if op == "takeover" else start_server()):
                    finish("restored")
                    reply(ok=False, why="X1's server did not answer its health route")
                    return
                reply(ok=True)
            elif op in ("stop", "kill"):
                stop_server(b"t" if op == "stop" else b"k")
                reply(ok=True)
            elif op == "end":
                finish("restored")
                reply(ok=True)
                return
    except (Gone, SystemExit):
        finish("restored-by-guard")
    except Stop as e:
        swap_write(kit, error=str(e))
        finish("restored")
        try:
            reply(ok=False, why=str(e))
        except Gone:
            pass


def supervise(kit, minutes, driver):
    """The swap's supervisor: starts the guard with a pipe each way, asks it to take
    over, relays the run's control requests (F4, F6, start again), and asks it to end
    at the deadline, on a signal or on an error. It never holds X1's server."""
    deadline = now_ms() + int(minutes * 60000)
    log = os.open(os.path.join(kit.run, "guard.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    g = subprocess.Popen([sys.executable, os.path.abspath(driver), "swap-guard", "--work", kit.work,
                          "--minutes", str(minutes)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                         start_new_session=True)
    os.close(log)
    swap_write(kit, state="starting", deadline_ms=deadline, supervisor=identity(os.getpid()), guard=identity(g.pid))
    buf = [b""]
    _stop_signals()

    def ask(op, timeout=90):
        try:
            g.stdin.write((json.dumps({"op": op}) + "\n").encode())
            g.stdin.flush()
        except OSError:
            raise Gone()
        end = time.monotonic() + timeout
        while b"\n" not in buf[0]:
            left = end - time.monotonic()
            r, _, _ = select.select([g.stdout], [], [], max(0, min(1, left)))
            if r:
                data = os.read(g.stdout.fileno(), 4096)
                if not data:
                    raise Gone()
                buf[0] += data
            elif left <= 0:
                raise Gone()  # the guard did not answer: treated as gone
        line, buf[0] = buf[0].split(b"\n", 1)
        return json.loads(line)

    try:
        if not ask("takeover").get("ok"):
            return  # the guard restored 0.0.2 and recorded the state
        swap_write(kit, state="up")
        ctl = os.path.join(kit.run, "swap-control")
        while True:
            if g.poll() is not None:
                raise Gone()
            if now_ms() >= deadline:
                ask("end")
                return
            if os.path.exists(ctl):
                req = json.load(open(ctl))
                os.remove(ctl)
                cmd = req.get("cmd")
                if cmd == "end":
                    ask("end")
                    swap_write(kit, ack=req.get("nonce"))
                    return
                r = ask({"stop-server": "stop", "kill-server": "kill", "start-server": "start"}.get(cmd, "none"))
                swap_write(kit, ack=req.get("nonce"))
                if cmd == "start-server" and not r.get("ok"):
                    return  # the guard restored 0.0.2
            time.sleep(0.1)
    except Gone:
        close_gate(kit)
        if g.poll() is not None or swap_state(kit).get("state") not in ("restored", "restored-by-guard",
                                                                         "restore-failed"):
            swap_write(kit, state="guard-died",
                       error="the guard died: X1's server stopped with it; restore 0.0.2 by hand, as HANDOFF says")
    except BaseException:
        try:
            ask("end", 60)
        except Gone:
            close_gate(kit)
            swap_write(kit, state="guard-died",
                       error="the guard died: X1's server stopped with it; restore 0.0.2 by hand, as HANDOFF says")


def swap_control(kit, cmd, timeout=30):
    """One request to the supervisor (F4: stop-server; F6: kill-server; start-server),
    acknowledged before the run goes on."""
    if swap_state(kit).get("state") != "up":
        raise Stop("the swap is not up")
    nonce = secrets.token_hex(8)
    tmp = os.path.join(kit.run, "swap-control.tmp")
    write_private(tmp, {"cmd": cmd, "nonce": nonce})
    os.replace(tmp, os.path.join(kit.run, "swap-control"))
    if not wait_for(lambda: swap_state(kit).get("ack") == nonce, timeout, 0.1):
        raise Stop("the swap supervisor did not answer " + cmd)
    if cmd == "start-server" and not health(kit.cfg["port"]):
        raise Stop("X1's server did not come back")


def strip(snap, ids):
    """A snapshot without the test threads: removed, never excluded (#23, S2)."""
    s = dict(snap)
    s["rows"] = {k: v for k, v in snap["rows"].items() if k not in ids}
    s["views_disagree"] = [k for k in snap["views_disagree"] if k not in ids]
    s["views"] = {v: [k for k in l if k not in ids] for v, l in snap["views"].items()}
    return s


def judge(initial, current, judged):
    """Sol R3: every judged session against its own row at the run's start, on every
    field that decides quiet or active as well as the compared ones. A judged session
    is never exempted later, whatever it looks like now."""
    failures, missing = {}, 0
    for sid in sorted(judged):
        b, a = initial["rows"].get(sid), current["rows"].get(sid)
        if a is None:
            failures["disappeared"] = failures.get("disappeared", 0) + 1
            continue
        if any(x.get(f, observe.MISSING) == observe.MISSING for x in (a, b) for f in JUDGED_FIELDS):
            missing += 1
        for f in JUDGED_FIELDS:
            if b.get(f, observe.MISSING) != a.get(f, observe.MISSING):
                failures[f] = failures.get(f, 0) + 1
    return failures, missing


def unjudged_changes(prev, cur, skip):
    """Field counts for the sessions that are reported, not judged."""
    out = {}
    for sid in set(prev["rows"]) | set(cur["rows"]):
        if sid in skip:
            continue
        b, a = prev["rows"].get(sid), cur["rows"].get(sid)
        for f in (["appeared"] if b is None else ["disappeared"] if a is None else
                  [f for f in JUDGED_FIELDS if b.get(f, observe.MISSING) != a.get(f, observe.MISSING)]):
            out[f] = out.get(f, 0) + 1
    return dict(sorted(out.items()))


def decoded_strings(v):
    """Every key and string value of a report, decoded (no JSON escaping), recursively."""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield str(k)
            yield from decoded_strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from decoded_strings(x)


def leaked(forbid, rep):
    """The forbidden strings found in the report: each against every decoded key and
    string value (Sol R4, round 2: serialised text escapes quotes, backslashes and
    non-ASCII). Short ones match as whole tokens (observe.leaks), longer ones anywhere."""
    found = set()
    for s in set(decoded_strings(rep)):
        for v in forbid:
            if v and v not in found and (v == s or observe.leaks(v, s)):
                found.add(v)
    return found


def json_type(v):
    return ("null" if v is None else "boolean" if isinstance(v, bool) else "integer" if isinstance(v, int)
            else "number" if isinstance(v, float) else "string" if isinstance(v, str)
            else "array" if isinstance(v, list) else "object" if isinstance(v, dict) else "unknown")


def schema_error(v, node, root, path="$"):
    """The first place where v breaks the schema node, or None. Supports exactly what the
    contracts use: $ref (local), oneOf, type, const, enum, required, properties,
    additionalProperties (false), items, minimum, minLength and maxLength."""
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/"):
            return path + ": unsupported $ref"
        node = root["$defs"][ref[len("#/$defs/"):]]
    if "oneOf" in node:
        ok = [b for b in node["oneOf"] if schema_error(v, b, root, path) is None]
        return None if len(ok) == 1 else "%s: matches %d of oneOf" % (path, len(ok))
    if "const" in node and v != node["const"]:
        return path + ": const"
    if "enum" in node and v not in node["enum"]:
        return path + ": enum"
    t = node.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        jt = json_type(v)
        if jt not in types and not (jt == "integer" and "number" in types):
            return "%s: type %s" % (path, jt)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "minimum" in node and v < node["minimum"]:
        return path + ": minimum"
    if isinstance(v, str):
        if len(v) < node.get("minLength", 0) or len(v) > node.get("maxLength", len(v)):
            return path + ": length"
    if isinstance(v, dict):
        props = node.get("properties", {})
        for name in node.get("required", []):
            if name not in v:
                return "%s: missing %s" % (path, name)
        if node.get("additionalProperties") is False:
            extra = [k for k in v if k not in props]
            if extra:
                return "%s: unexpected %s" % (path, extra[0])
        for name, x in v.items():
            if name in props:
                e = schema_error(x, props[name], root, path + "." + name)
                if e:
                    return e
    if isinstance(v, list) and "items" in node:
        for i, x in enumerate(v):
            e = schema_error(x, node["items"], root, "%s[%d]" % (path, i))
            if e:
                return e
    return None


class Schemas:
    KNOWN = {"$schema", "$id", "$ref", "$defs", "title", "description", "type", "const", "enum", "required",
             "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength",
             "maxLength", "pattern", "minimum", "maximum", "oneOf", "anyOf", "allOf"}

    def __init__(self, contracts):
        self.dir = contracts
        self.docs = {}
        for name in ("new-thread", "attachment", "messaging", "inventory", "prompt"):
            with open(os.path.join(contracts, "%s.v1.schema.json" % name)) as f:
                self.docs[name] = json.load(f)

    def problems(self, doc, contract, definition=None):
        """[] if doc is valid against the contract's root (or one of its $defs); else
        the first problems, as JSON paths and rules (never a value)."""
        root = self.docs[contract]
        schema = root["$defs"][definition] if definition else root
        out = []
        self._check(doc, schema, root, "$", out)
        return out[:5]

    def _ref(self, root, ref):
        if not ref.startswith("#/$defs/"):
            raise Stop("a contract uses a $ref the kit can't follow")
        return root["$defs"][ref[len("#/$defs/"):]]

    @staticmethod
    def _type_ok(v, t):
        return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
                "boolean": isinstance(v, bool), "null": v is None,
                "integer": isinstance(v, int) and not isinstance(v, bool),
                "number": isinstance(v, (int, float)) and not isinstance(v, bool)}[t]

    @staticmethod
    def _same(a, b):
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def _check(self, v, s, root, path, out):
        unknown = set(s) - self.KNOWN
        if unknown:
            raise Stop("a contract uses a keyword the kit can't check: " + ",".join(sorted(unknown)))
        if "$ref" in s:
            self._check(v, self._ref(root, s["$ref"]), root, path, out)
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(self._type_ok(v, t) for t in types):
                out.append("%s: type" % path)
                return
        if "const" in s and not self._same(v, s["const"]):
            out.append("%s: const" % path)
        if "enum" in s and not any(self._same(v, e) for e in s["enum"]):
            out.append("%s: enum" % path)
        if isinstance(v, str):
            if len(v) < s.get("minLength", 0) or ("maxLength" in s and len(v) > s["maxLength"]):
                out.append("%s: length" % path)
            if "pattern" in s and not re.search(s["pattern"], v):
                out.append("%s: pattern" % path)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if ("minimum" in s and v < s["minimum"]) or ("maximum" in s and v > s["maximum"]):
                out.append("%s: range" % path)
        if isinstance(v, dict):
            for k in s.get("required", []):
                if k not in v:
                    out.append("%s: missing %s" % (path, k))
            props = s.get("properties", {})
            for k, x in v.items():
                if k in props:
                    self._check(x, props[k], root, "%s.%s" % (path, k), out)
                elif s.get("additionalProperties") is False:
                    out.append("%s: extra key" % path)
                elif isinstance(s.get("additionalProperties"), dict):
                    self._check(x, s["additionalProperties"], root, "%s.*" % path, out)
        if isinstance(v, list):
            if len(v) < s.get("minItems", 0) or ("maxItems" in s and len(v) > s["maxItems"]):
                out.append("%s: items count" % path)
            if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
                out.append("%s: repeated item" % path)
            if "items" in s:
                for i, x in enumerate(v):
                    self._check(x, s["items"], root, "%s[%d]" % (path, i), out)
        for key, need in (("oneOf", 1), ("anyOf", None), ("allOf", "all")):
            if key in s:
                ok = 0
                for sub in s[key]:
                    o = []
                    self._check(v, sub, root, path, o)
                    ok += not o
                if (need == 1 and ok != 1) or (need is None and ok < 1) or (need == "all" and ok != len(s[key])):
                    out.append("%s: %s" % (path, key))
