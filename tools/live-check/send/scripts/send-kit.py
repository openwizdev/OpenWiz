#!/usr/bin/env python3
"""X1: the send brackets for OpenWiz 0.0.3's live test (#10, decided L-9).

Standard-library Python 3.9. It reuses 0.0.1's quick check (the full list in
four views, sampled sessions, the compare and its classes; quick-check.py and
observe.py, imported from the repository, never copied) and adds the send
brackets: every send runs `openwiz send` (or waits for Jake's press in the
composer) with X2 (x2-shim.py, the call-counting shim) first on PATH, and
checks the outcome, the calls X2 counted, the send record and where the text
landed. It never says "pass": each step is as_expected, not_as_expected or
incomplete, and the first step that is not as expected stops the run.

    send-kit.py texts    [--texts F]                       the approved texts: label, bytes, SHA-256
    send-kit.py setup    --work W --room-cli P --openwiz P --threads F [--server P] [--checks...]
    send-kit.py map      --work W [--show-titles]           the test threads, for Jake's eyes
    send-kit.py recheck  --work W                           L-3: thread tell --help, structure only
    send-kit.py run      --work W --groups C1,C2,...        the groups of plan.json, bracketed
    send-kit.py server   --work W start|stop|kill           openwiz-server with X2 on its PATH
    send-kit.py swap     --work W start|end|stop-server|kill-server|start-server
                                                            the web part's server, under a supervisor and a guard
    send-kit.py parity   --work W                           L10, from the send records (no call)
    send-kit.py receipts --work W                           L4, the structure of X2's captured receipts
    send-kit.py l13      --work W -- <quick-check args>     L13, 0.0.1's quick check while the page refreshes

Privacy: ids exist only in the threads file, X1's memory and the run
directory (0700, files 0600); the texts are synthetic and approved. Every
report is structure only and passes the quick check's leak scan before it is
printed. Exit 0: every step as expected. 10: a stop. 11: a script error.
"""

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TICKET = os.path.dirname(HERE)
TOOLKIT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.abspath(os.path.join(TOOLKIT, "..", ".."))
sys.path.insert(0, TOOLKIT)
import core
from core import (qc, observe, Stop, JUDGED_FIELDS, CHILD_WRAPPER,
                  sha, now_ms, write_private, in_repository, structure, strings,
                  wait_for, marker, identity, signal_if_same, port_answers, health,
                  listeners, confirmed_old, restore_old, swap_state, swap_write,
                  close_gate, Gone, _stop_signals, guard, swap_control, strip,
                  judge, unjudged_changes, decoded_strings, leaked, Schemas,
                  json_type, schema_error)
from core import supervise as _supervise


def supervise(kit, minutes):
    return _supervise(kit, minutes, __file__)


# The approved texts (decided L-5, 2026-10-30): #10's prepared texts at
# 7e5c920 (closed PR #23), by label and SHA-256 of their exact UTF-8 bytes.
APPROVED = {
    "M01": "818443cc4f9c6282ec7e0562a242008852c9e8b6b12f208ae060857bd4bd472e",
    "M02": "8702241087b615304b089d942edb96d3533406bd54b5e11dffaaad97a3f0850e",
    "M03": "755775fb03526a637058b41acedff2f5e01a8dfd17ef6296287a872186628a6d",
    "M04": "13d5d9401b271f0f5b6afdd1a38425f3b7b7168b7c084586659e860ff1dcd370",
    "M05": "780d4ee0b6ed511134345f3cc61a2dd23ea89a0b8350ff285fa3fdaa52df3a99",
    "M06": "6d9e54f59e15214c3c5c479623f25fa939420d62c65e88e5cf6745d9f38b4b96",
    "M07": "56691e6c8eda56763389bede99fb84486313b3090d213aab9c0b1b3ee2d7fef8",
    "M08": "4e6ef05e76e37ae9b15ba0e90db58a3aea2aa23a1c8f9fd2faab0073107d83da",
    "M09": "79087fce9c31c07ac09d4da1f2570e71aa0a4156e3822f5f19606513a90fe54a",
    "M10": "e02eaa4c5b32a08d5bdb6241cebe0c90cdea5edc934960f06e80e5e51b9ca12a",
    "M11": "b1ca9d1f3283c8710c09ac4e18a3e74dad7ed00460304896b19907b08f38b25b",
    "M12": "88a6ddf9b1a82412cda456802ce129b6b0fd59ea68872d7993ba5328a69194fc",
    "M13": "1145b65b58abfa1b0829a65988894456e78ff71f83f757a79cb80cf47aa15bd9",
    "M14": "29d06102289db02905f4a827b43ed99e75e517e7e1638718226573d93bd71289",
    "M15": "e06801277889199b2d05f23a63244d3060a99d09e1a9f9e23449bed79ea1fc63",
    "M16": "47af985aa0f119e8e0dcaa1f146490f058fa395e20e86a402d2b22566078c793",
    "M17": "6cc88cc10554ec5f9196c3221ec31d5bc9069d6020d3a7863c1f26e08646a66e",
    "M18": "ba163a462a1337a9e334175f34258052683917fab1935da7c6fa0e4230cb06b1",
    "M19": "33f252424745f6c4ebbce85337cb7c6ec6ef66f8d9a11472ecb02e5f5d0bb7fc",
    "M20": "8787e225e5f07377f40f71d59c78fdb607cb5e25a73ab45eaab00d3b9674b1d6",
    "M21": "77e8aa6cc11cd975c14e7d9c5b0655d63001934d15808c1cd3898c13206e3f9e",
    "M25": "db9eff178337a35bb9ee6186524f490188437f38c0da3f1743d0501e7b95e089",
}
LABELS = ("T-A", "T-B", "T-C")
ENV_NAMES = {"TA": "T-A", "TB": "T-B", "TC": "T-C"}
ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}\Z")
SHOWN = {"accepted": "sent", "queued": "queued", "failed": "failed", "uncertain": "uncertain"}


def load_texts(path):
    """The texts file, checked line by line against APPROVED. Any difference stops."""
    texts, threads = {}, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                raise Stop("the texts file has a line that is not label, thread, text")
            label, thread, text = parts
            if label not in APPROVED or sha(text) != APPROVED[label] or label in texts:
                raise Stop("text %s is not approved, or its SHA-256 differs" % label)
            texts[label], threads[label] = text, thread
    if set(texts) != set(APPROVED):
        raise Stop("the texts file lacks an approved text")
    return texts, threads


def load_plan(path, texts):
    with open(path) as f:
        plan = json.load(f)
    seen = set()
    for g in plan["groups"]:
        for s in g["steps"]:
            if s["id"] in seen:
                raise Stop("plan: a repeated step id")
            seen.add(s["id"])
            if "msg" in s and s["msg"] not in texts:
                raise Stop("plan: a step uses an unapproved text")
            if "thread" in s and s["thread"] not in LABELS:
                raise Stop("plan: a step names an unknown thread")
            if s.get("op", "new") != "new" and s["op"].split(":", 1)[1] not in seen:
                raise Stop("plan: a step reuses the op id of a later step")
    return plan


def read_threads(path):
    """TA=<id>, TB=<id>, TC=<id>, written by Jake on the Mac, 0600. Never printed."""
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise Stop("the threads file must be readable by its owner only (chmod 600)")
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip("'\"")
            if k.strip() not in ENV_NAMES or not ID_RE.match(v) or v.startswith("-"):
                raise Stop("the threads file has a line that is not TA, TB or TC = <id>")
            out[ENV_NAMES[k.strip()]] = v
    if set(out) != set(LABELS) or len(set(out.values())) != 3:
        raise Stop("the threads file needs three different ids: TA, TB and TC")
    return out


def step_calls(s):
    """The calls a plan step is approved to make (its expected count)."""
    c = (s.get("expect") or {}).get("calls", 0)
    return max(c) if isinstance(c, list) else int(c or 0)


def planned_calls(plan):
    """L-8's allowance: every call the plan makes (23)."""
    return sum(step_calls(s) for g in plan["groups"] for s in g["steps"])


RECONCILE = ("the allowance's charge journal (charges.log) is missing or unreadable: its usage is unknown, "
             "never zero; ask Jake to reconcile it")


def read_charges(d):
    """The allowance's charge journal, by step (Sol R14). Setup creates it, empty, with the
    manifest; from then on a missing or unreadable one (or one releasing more than it reserved)
    is unknown usage, never zero: it stops for Jake to reconcile, and nothing recreates it."""
    by = {}
    try:
        with open(os.path.join(d, "charges.log")) as f:
            for line in f:
                e = json.loads(line)
                by[e["step"]] = by.get(e["step"], 0) + {"reserve": 1, "release": -1}[e["op"]]
    except (OSError, ValueError, KeyError, TypeError):
        raise Stop(RECONCILE)
    if any(n < 0 for n in by.values()):
        raise Stop(RECONCILE)
    return by


# --------------------------------------------------------------------------
# The kit's work directory


class Kit:
    def __init__(self, work):
        self.work = os.path.abspath(work)
        with open(os.path.join(self.work, "kit.json")) as f:
            self.cfg = json.load(f)
        self.x2 = os.path.join(self.work, "x2")
        self.state = os.path.join(self.work, "state")
        self.run = os.path.join(self.work, "run")
        self.texts, self.text_threads = load_texts(self.cfg["texts"])
        self.plan = load_plan(self.cfg["plan"], self.texts)
        self.threads = read_threads(self.cfg["threads"])
        self.ctx = KitCtx(self.cfg["room_cli"], self.run, set(self.threads.values()))
        self.opids = self._load("opids.json", {})
        self.dry = bool(self.cfg.get("dry_run"))
        self.forbidden = set()  # live strings no report may hold (memory only)

    def _load(self, name, default):
        p = os.path.join(self.run, name)
        return json.load(open(p)) if os.path.exists(p) else default

    def save_opids(self):
        write_private(os.path.join(self.run, "opids.json"), self.opids)

    def arm(self, name, allowed=None, fault="capture", hold_s=0, ttl_s=300):
        """X2's step file, replaced in one rename. allowed: (label, mode, sha, max_calls).
        A step that allows a tell expires after ttl_s, so one left armed by a crash
        lets nothing through (Sol R2)."""
        step = {"step": name, "real_room_cli": self.cfg["room_cli"], "threads": self.threads,
                "fault": fault, "hold_s": hold_s, "allowed_tell": None,
                "auth": secrets.token_hex(8),  # this arming: a tell held past it is not called (Sol R12)
                "allowance": self.cfg.get("allowance"), "sitting": self.cfg.get("sitting")}
        if allowed:
            lab, mode, digest, n = allowed
            step["allowed_tell"] = {"thread": lab, "mode": mode, "text_sha256": digest, "max_calls": n}
            step["expires_ms"] = now_ms() + int((ttl_s + hold_s) * 1000)
        for m in ("holding-before", "answered-holding"):
            if os.path.exists(os.path.join(self.x2, m)):
                os.remove(os.path.join(self.x2, m))
        # Under X2's admission lock (Sol's review of the 0.0.4 kit, finding 2): a tell waiting
        # on it sees this step, never the one before.
        with self.lock():
            tmp = os.path.join(self.x2, "step.json.tmp")
            write_private(tmp, step)
            os.replace(tmp, os.path.join(self.x2, "step.json"))

    @contextlib.contextmanager
    def lock(self):
        """X2's lock: admission, arming and the sitting ledger all go under it."""
        with open(os.path.join(self.x2, "tell.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def disarm(self):
        self.arm("between-steps")

    def tells(self, name):
        """X2's counter for one step: attempts, calls made, refusals, aborts (parent gone),
        and held tells revoked by a disarm or an expiry during the hold (Sol R12)."""
        c = {"attempts": 0, "calls": 0, "refused": 0, "aborted": 0, "revoked": 0, "modes": [], "threads": []}
        path = os.path.join(self.x2, "tell.log")
        if os.path.exists(path):
            for line in open(path):
                e = json.loads(line)
                if e.get("step") != name:
                    continue
                o = e.get("outcome")
                if o in ("called", "holding", "refused"):
                    c["attempts"] += 1
                    c["threads"].append(e.get("thread"))
                    c["modes"].append(e.get("mode"))
                c["calls"] += o in ("called", "called_after_hold")
                c["refused"] += o == "refused"
                c["aborted"] += o == "aborted_parent_gone"
                c["revoked"] += o == "aborted_revoked"
                c["tainted"] = c.get("tainted", 0) + (o == "aborted_tainted")
        return c

    def ledger(self):
        """The sitting ledger (Sol R13): every refusal and revoked hold X2 has written since
        setup. Any entry taints the whole sitting; there is no baseline and no watermark."""
        try:  # setup makes it empty: a missing or unreadable ledger taints the sitting too
            with open(os.path.join(self.x2, "sitting.log")) as f:
                return [json.loads(line) for line in f]
        except (OSError, ValueError):
            return [{"kind": "unreadable"}]

    def allowance(self, by_step=False):
        """L-8's allowance, kept outside every sitting (Sol's R8 on #168): the total, what is
        charged (sends made, and holds not yet ended) in all sittings, what is left. A missing
        or unreadable charge journal stops for reconciliation, never reads as zero (Sol R14)."""
        try:
            d = self.cfg["allowance"]
            total = int(json.load(open(os.path.join(d, "allowance.json")))["total"])
        except (OSError, ValueError, KeyError, TypeError):
            raise Stop("the allowance cannot be read")
        by = read_charges(d)
        used = sum(by.values())
        out = {"total": total, "used": used, "remaining": total - used}
        return (out, by) if by_step else out

    def require_clean(self):
        """`run` and every preparation command start here: nothing more is done in a tainted sitting."""
        found = self.ledger()
        if found:
            raise Stop(taint_text(found) + "; nothing was done (only a new setup clears it)")

    def settled_tells(self, name, hold_s):
        """Waits until every call X2 held in this step has been called or aborted."""
        def done():
            path = os.path.join(self.x2, "tell.log")
            if not os.path.exists(path):
                return True
            held = ended = 0
            for line in open(path):
                e = json.loads(line)
                if e.get("step") == name:
                    held += e.get("outcome") == "holding"
                    ended += e.get("outcome") in ("called_after_hold", "aborted_parent_gone", "aborted_revoked",
                                                  "aborted_tainted")
            return ended >= held
        if not wait_for(done, hold_s + 15):
            raise Stop("X2 never ended its hold (%s)" % name)

    def env(self):
        env = dict(os.environ)
        env["PATH"] = self.x2 + os.pathsep + env.get("PATH", "")
        env["OPENWIZ_STATE_DIR"] = self.state
        for k in ("ROOM_SERVER_URL",):
            env.pop(k, None)
        return env

    def path_guard(self, env):
        """room-cli on the command's PATH must be X2, or nothing is sent (#23, M5)."""
        found = shutil.which("room-cli", path=env["PATH"])
        if not found or os.path.realpath(found) != os.path.realpath(os.path.join(self.x2, "room-cli")):
            raise Stop("room-cli on the send's PATH is not X2; nothing was sent")

    def record(self, label, digest, op=None):
        """O16: the send record of one op id, or the newest for this thread and text.
        Kept: its state, delivery kind and reason, whether the text is kept and
        matches, recovered; and the op id in memory only."""
        best = None
        sends = os.path.join(self.state, "sends")
        for name in (os.listdir(sends) if os.path.isdir(sends) else []):
            if not name.endswith(".json"):
                continue
            try:
                r = json.load(open(os.path.join(sends, name)))
            except ValueError:
                continue
            b = r.get("binding") or {}
            if op is not None and r.get("op_id") != op:
                continue
            if b.get("target") != self.threads[label] or b.get("text_sha256") != digest:
                continue
            key = r.get("claimed_at") or 0
            if best is None or key >= (best.get("claimed_at") or 0):
                best = r
        if best is None:
            return None
        d = best.get("delivery") or {}
        text = best.get("text")
        return {"op": best.get("op_id"), "state": best.get("state"), "delivery": d.get("kind"),
                "reason": d.get("reason"), "text_kept": isinstance(text, str),
                "text_matches": isinstance(text, str) and sha(text) == digest,
                "recovered": bool(best.get("recovered") or d.get("recovered")),
                "keys": structure(best)}


class KitCtx(observe.Ctx):
    """0.0.1's observer context, plus the reads L-10 approved on test threads only:
    O13 (thread queue list) and O12 (thread tell --help)."""

    def __init__(self, room_cli, run_dir, test_ids):
        super().__init__(room_cli, run_dir)
        self.test_ids = test_ids

    def room(self, argv, env=None, wrap=None):
        a = list(argv)
        extra = (a == ["thread", "tell", "--help"]
                 or (len(a) == 5 and a[:3] == ["thread", "queue", "list"]
                     and a[3] in self.test_ids and a[4] == "--json"))
        if not extra:
            return super().room(argv, env, wrap)
        kind = " ".join(a[:3])
        try:
            r = subprocess.run([self.room_cli] + a, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise Stop("observer read timed out: " + kind)
        with self.lock:
            self.reads[kind] = self.reads.get(kind, 0) + 1
        return r


# --------------------------------------------------------------------------
# Test-thread observation (O13, O14, O18)


def target_state(kit, label):
    sid = kit.threads[label]
    show = kit.ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
    if not isinstance(show, dict):
        raise Stop("test thread %s cannot be read" % label)
    t = show.get("thread") or {}
    rows = kit.ctx.room_json(["thread", "queue", "list", sid, "--json"])
    if not isinstance(rows, list):
        raise Stop("thread queue list of %s is not an array (its shape is unobserved)" % label)
    status, display = t.get("status"), (t.get("runtime") or {}).get("displayStatus")
    return {"status": status, "display": display, "qmc": t.get("queuedMessageCount"),
            "rows": len(rows), "idle": status == "idle" and display == "idle"}


def all_events(kit, label):
    """Every event of a test thread, oldest first, by `thread log --after-seq`
    windows of 100 (the standing approval's form; O14)."""
    sid, out, after = kit.threads[label], [], None
    for _ in range(100):
        rows = observe.log_rows(kit.ctx, sid, after, observe.LOG_WINDOW)
        if rows is None:
            raise Stop("test thread %s is gone" % label)
        out.extend(r for r in rows if isinstance(r, dict))
        if len(rows) < observe.LOG_WINDOW:
            return out
        after = rows[-1].get("seq")
        if not isinstance(after, int):
            raise Stop("an event without a sequence number")
    raise Stop("too many events on a test thread")


def carrying(events, text):
    """Events carrying the text: exact (a string value equal to it) or wrapped
    (a string value containing it), counted per event type. In memory only."""
    exact, wrapped, per_type, keys = 0, [], {}, []
    for e in events:
        vals = list(strings(e.get("data", e)))
        if any(v == text for v in vals):
            exact += 1
        elif any(text in v for v in vals):
            v = next(v for v in vals if text in v)
            i = v.index(text)
            wrapped.append({"prefix_bytes": len(v[:i].encode()), "suffix_bytes": len(v[i + len(text):].encode())})
        else:
            continue
        t = e.get("type") if isinstance(e.get("type"), str) else "absent"
        per_type[t] = per_type.get(t, 0) + 1
        keys.append(sorted(e.get("data", {}).keys()) if isinstance(e.get("data"), dict) else [])
    return {"exact": exact, "wrapped": wrapped, "max_per_type": max(per_type.values()) if per_type else 0,
            "types": len(per_type), "data_keys": keys}


# --------------------------------------------------------------------------
# Running OpenWiz, and the processes the kit owns


def ledger_counts(entries):
    """The ledger by kind (never an id or a text)."""
    c = {"sends_outside_the_plan": 0, "tells_refused": 0, "calls_refused": 0, "held_tells_revoked": 0,
         "ledger_unreadable": 0}
    for e in entries:
        if e.get("kind") == "unreadable":
            c["ledger_unreadable"] += 1
        elif e.get("kind") == "revoked":
            c["held_tells_revoked"] += 1
        elif not e.get("tell"):
            c["calls_refused"] += 1
        elif e.get("step") == "between-steps":
            c["sends_outside_the_plan"] += 1
        else:
            c["tells_refused"] += 1
    return c


def taint_text(entries):
    c = ledger_counts(entries)
    words = {"sends_outside_the_plan": "send(s) outside the plan reached X2 (refused, nothing sent)",
             "tells_refused": "tell(s) refused by X2",
             "calls_refused": "call(s) refused by X2 (not on OpenWiz's allowlist)",
             "held_tells_revoked": "held tell(s) aborted by X2 (disarmed or expired during the hold)",
             "ledger_unreadable": "the sitting ledger missing or unreadable"}
    return "the sitting is tainted: " + ", ".join("%d %s" % (n, words[k]) for k, n in c.items() if n)


def decide(kit, rep):
    """The outcome, decided from the sitting ledger (Sol R13). The caller holds X2's lock,
    and this is the last thing before the report is written and the command exits."""
    found = kit.ledger()
    rep["x2_ledger"] = ledger_counts(found)
    try:
        rep["allowance"] = kit.allowance()
    except Stop as e:  # Sol R14: unknown usage fails the report, which is still written
        rep["allowance"] = "unknown"
        rep["stopped"] = rep.get("stopped") or str(e)
        rep["outcome"] = "not_as_expected"
    if found:
        rep["stopped"] = rep.get("stopped") or taint_text(found)
        rep["outcome"] = "not_as_expected"
    return rep


def run_openwiz(kit, step, op, text, label):
    mode = step["mode"]
    argv = [kit.cfg["openwiz"], "send", kit.threads[label]] + (["--steer"] if mode == "steer" else []) \
        + ["--op-id", op, "--json", "--", text]
    env = kit.env()
    kit.path_guard(env)
    procs = [subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) for _ in range(step.get("procs", 1))]
    kill = step.get("kill")
    if kill:
        name = "answered-holding" if kill == "after-answer" else "holding-before"
        if not wait_for(lambda: marker(kit, name), 30):
            for p in procs:
                p.kill()
            raise Stop("X2 never reached its hold (%s)" % step["id"])
        for p in procs:
            p.send_signal(signal.SIGKILL)
    outs = []
    for i, p in enumerate(procs):
        try:
            out, err = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            raise Stop("openwiz did not finish in 120 s (%s)" % step["id"])
        write_private(os.path.join(kit.run, "out-%s-%d.json" % (step["id"], i)), out.decode("utf-8", "replace"))
        try:
            rep = json.loads(out) if out.strip() else None
        except ValueError:
            rep = None
        outs.append((p.returncode, rep))
    return outs


# --------------------------------------------------------------------------
# The swap: one supervisor owns X1's 0.0.3 server for the web part, and a guard
# restores Jake's confirmed 0.0.2 launch if the supervisor dies or overruns.


# Sol R2, round 3 (the orchestrator's diagnosis): one owner. The GUARD is the parent of
# X1's server: it spawns the wrapper itself, so it always knows its own child (unreaped,
# so its PID and process group cannot be reused), stops it, confirms the exit with
# waitpid, and only then restores 0.0.2. The supervisor never holds the child; it only
# asks the guard, over the guard's stdin pipe, to take over, stop, start or end. The
# guard acts on that pipe (its EOF means the supervisor is gone), never on swap.json,
# which is a status record only.
#
# The wrapper reads its own pipe from the guard: on "g" it starts the server as its
# child (in the wrapper's process group); on "t" or "k" (F4, F6) it signals the server,
# waits for it and exits; on EOF (the guard died) it does the same with SIGTERM. So the
# server can never outlive the guard.


# --------------------------------------------------------------------------
# The composer's requests, made by X1 (the W groups, and every press in a dry run)


def post(kit, label, body, host=None, headers=None, timeout=45, holder=None):
    """One send request exactly as the composer makes it (contracts/web-api.v1.md), to
    the server on the port the tunnel serves. Returns (http status or None, report or
    None, what the composer shows by WS-8). `holder` gets the connection, so a dry run
    can drop the client's side (the phone going offline)."""
    host = host or kit.cfg["host"]
    data = json.dumps(body).encode()
    h = {"Host": host, "Origin": "https://" + host, "Sec-Fetch-Site": "same-origin",
         "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",  # apps/web's REQUEST_HEADERS
         "Content-Type": "application/json", "X-OpenWiz-Send": "1", "Content-Length": str(len(data))}
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    try:
        conn = http.client.HTTPConnection("127.0.0.1", kit.cfg["port"], timeout=timeout)
        if holder is not None:
            holder["conn"] = conn
        conn.putrequest("POST", "/api/v1/sessions/%s/messages" % kit.threads[label], skip_host=True,
                        skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        conn.endheaders(data)
        r = conn.getresponse()
        status, raw = r.status, r.read()
        conn.close()
    except (OSError, http.client.HTTPException):
        return None, None, "uncertain"
    try:
        rep = json.loads(raw)
    except ValueError:
        rep = None
    if status == 200 and isinstance(rep, dict):
        return status, rep, SHOWN.get(rep.get("status"), "uncertain")
    return status, rep, "not sent" if status in (400, 403, 405, 411, 413, 415, 421) else "uncertain"


def lookup(kit, label, op):
    """The composer's Check again: the lookup route (no call)."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", kit.cfg["port"], timeout=15)
        conn.request("GET", "/api/v1/sessions/%s/messages/%s" % (kit.threads[label], op),
                     headers={"Host": kit.cfg["host"], "Accept": "application/json",
                              "X-Requested-With": "XMLHttpRequest"})
        r = conn.getresponse()
        status, raw = r.status, r.read()
        conn.close()
        rep = (json.loads(raw).get("result") or {}).get("report") or {}
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return "uncertain"
    return SHOWN.get(rep.get("status"), "uncertain") if status == 200 else "uncertain"


def web_op(mode="queue"):
    """apps/web's op id for a draft's first attempt: `web-<32 hex>-q1` or `-s1` (WS-7, #91)."""
    return "web-%s-%s1" % (secrets.token_hex(16), "q" if mode == "queue" else "s")


# --------------------------------------------------------------------------
# Steps


def ensure(kit, step, label):
    """The target's state before a send: idle, or busy for busy_min seconds."""
    a = kit.args
    need = step.get("need", "any")
    if need == "idle":
        if not wait_for(lambda: (lambda s: s["idle"] and s["rows"] == 0 and s["qmc"] == 0)(
                target_state(kit, label)), a.idle_timeout, a.poll):
            return "incomplete: %s did not become idle within %d s" % (label, a.idle_timeout)
    elif need == "busy":
        since, end = None, time.monotonic() + a.idle_timeout
        while time.monotonic() < end:
            s = target_state(kit, label)
            if not s["idle"]:
                since = since or time.monotonic()
                if time.monotonic() - since >= a.busy_min:
                    return None
            else:
                since = None
            time.sleep(a.poll)
        return "incomplete: %s was not busy for %d s" % (label, a.busy_min)
    return None


def check(expect, got):
    """Every expectation the step names against what was seen; the differences."""
    bad = []
    for k, want in expect.items():
        if k in ("deliver", "exact", "queue_rows_after", "shown", "exits", "produced_if_shown", "outcomes"):
            continue
        have = got.get(k)
        if isinstance(want, list) and not isinstance(have, list):  # one of these
            if have not in want:
                bad.append("%s %s, expected %s" % (k, have, "/".join(str(w) for w in want)))
        elif have != want:
            bad.append("%s %s, expected %s" % (k, have, want))
    if "outcomes" in expect:  # exact (status, delivery) pairs, each as reported: never mixed
        pair = [got.get("status"), got.get("delivery")]
        if pair not in expect["outcomes"]:
            bad.append("status/delivery %s/%s, expected %s" % (pair[0], pair[1],
                       " or ".join("/".join(o) for o in expect["outcomes"])))
    if "exits" in expect:
        exits = got.get("exit_list", [])
        for code, (lo, hi) in expect["exits"].items():
            n = sum(1 for e in exits if str(e) == code)
            if not lo <= n <= hi:
                bad.append("%d runs exited %s, expected %d to %d" % (n, code, lo, hi))
        if sum(1 for e in exits if str(e) not in expect["exits"]):
            bad.append("a run exited otherwise")
    return bad


def report_fields(rep):
    """What leaves the Mac from one openwiz.messaging.v1 report (#23 §3.4)."""
    if not isinstance(rep, dict):
        return {}
    res = rep.get("result") or {}
    d = res.get("delivery") or {}
    eff = ((rep.get("effects") or {}).get("effect") or {})
    return {"status": rep.get("status"), "delivery": d.get("kind"), "reason": d.get("reason"),
            "waiting_on": d.get("waiting_on"), "replayed": res.get("replayed"),
            "recovered": res.get("recovered"), "differs": res.get("differs"),
            "effect": (eff.get("known") or {}).get("kind", "unknown"),
            "text_sha_matches": None, "keys": structure(rep)}


def do_send(kit, step, label, text):
    digest = sha(text)
    if step.get("op", "new") == "new":
        op = "op-acc-%s-%s" % (step["msg"], secrets.token_hex(8))
        kit.opids[step["id"]] = op
        kit.save_opids()
    else:
        op = kit.opids[step["op"].split(":", 1)[1]]
    exp = step["expect"]
    allowed = (label, step["mode"], digest, 1) if exp.get("calls", 0) or exp.get("attempts", 0) else None
    kit.arm(step["id"], allowed, step.get("fault", "capture"), step.get("hold_s", 0), ttl_s=180)
    t0 = now_ms()
    outs = run_openwiz(kit, step, op, text, label)
    kit.settled_tells(step["id"], step.get("hold_s", 0))
    kit.disarm()
    code, rep = outs[0]
    got = dict(report_fields(rep), exit=code, exit_list=[c for c, _ in outs], ms=now_ms() - t0)
    if rep is not None:
        got["text_sha_matches"] = rep.get("text_sha256") == digest
        if got["text_sha_matches"] is False:
            got["bad_text"] = True
    got.update({k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls", "refused", "aborted", "revoked")})
    return got


def do_web(kit, step, label, text):
    """One send from the web. `post`: X1 makes the composer's request itself, to the
    port the tunnel serves. `press`: Jake presses on his phone (the runner relays the prompt
    and his answer); in a dry run X1 presses for him."""
    digest = sha(text)
    exp = step["expect"]
    by_x1 = step["do"] == "post" or kit.dry
    allowed = (label, step["mode"], digest, 1) if exp.get("calls", 0) or exp.get("attempts", 0) else None
    kit.arm(step["id"], allowed, step.get("fault", "capture"), step.get("hold_s", 0),
            ttl_s=(60 if by_x1 else kit.args.press_timeout + 60))
    got, box, th = {}, {}, None
    kill = step.get("kill") or ""
    if by_x1:
        op = web_op(step["mode"])
        body = {"op_id": op, "mode": step["mode"], "text": text, "resume_paused_queue": False,
                "accept_possible_duplicate": False}
        kit.opids[step["id"]] = op
        kit.save_opids()

        holder = {}

        def press():
            box["r"] = post(kit, label, body, holder=holder)
            if step.get("double"):
                box["r2"] = post(kit, label, body)
        th = threading.Thread(target=press)
        th.start()
    else:
        say("PRESS: on %s, open %s in the web page, put text %s in the composer, exactly:\n    %s\n%s"
            "    and press %s." % (step["device"], label, step["msg"], text,
                                   ("    " + step["note"] + "\n") if step.get("note") else "", step["button"]))
    if not wait_for(lambda: kit.tells(step["id"])["attempts"] > 0, kit.args.press_timeout, 0.2):
        return {"incomplete": "no call reached X2 within %d s" % kit.args.press_timeout}
    if step.get("race_cli"):
        wait_for(lambda: marker(kit, "holding-before"), 10)
        rec = kit.record(label, digest)
        race = run_openwiz(kit, dict(step, procs=1, kill=None, id=step["id"] + "-cli"), rec["op"], text, label)
        got["race_exit"] = race[0][0]
    if kill:
        name = "answered-holding" if kill.endswith("after-answer") else "holding-before"
        if not wait_for(lambda: marker(kit, name), 30):
            return {"incomplete": "X2 never reached its hold"}
        if kill == "server-term-after-answer":
            swap_control(kit, "stop-server")
        elif kill == "server-kill-during-hold":
            swap_control(kit, "kill-server")
        elif kill == "phone-offline-after-answer" and by_x1:
            # A dry run's stand-in for the phone going offline: the client's side of the
            # connection goes while the server finishes the send.
            wait_for(lambda: "conn" in holder and holder["conn"].sock is not None, 10, 0.05)
            try:
                holder["conn"].sock.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
        # phone-offline, live: Jake turns on Airplane Mode right after pressing (the step's note).
    if not kill.startswith("server"):  # a stopped server never finishes the record
        wait_for(lambda: (lambda r: r is not None and r["state"] == "finished")(kit.record(label, digest)),
                 step.get("hold_s", 0) + 20, 0.3)
    if th is not None:
        th.join(60)
        got["shown"] = box.get("r", (None, None, "uncertain"))[2]
        if step.get("double"):  # Sol R10: the second press's own answer is checked too
            st2, rep2, _ = box.get("r2", (None, None, None))
            r2 = (rep2 or {}).get("result") or {}
            got["second"] = ("replayed" if st2 == 200 and (rep2 or {}).get("status") == "accepted"
                             and r2.get("replayed") is True else
                             "in_progress" if st2 == 200 and (rep2 or {}).get("status") == "in_progress" else
                             "http %s" % st2)
    else:
        got["shown"] = ask(kit, step["id"], "What does the composer show? (sent, queued, failed, uncertain)",
                           ("sent", "queued", "failed", "uncertain"))
    kit.settled_tells(step["id"], step.get("hold_s", 0))
    kit.disarm()
    rec = kit.record(label, digest)
    if rec:
        kit.opids[step["id"]] = rec.pop("op")
        kit.save_opids()
        got.update(record=rec["state"], delivery=rec["delivery"], recovered=rec["recovered"],
                   text_kept=rec["text_kept"])
    got.update({k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls", "refused", "aborted", "revoked")})
    return got


def do_hand(kit, step):
    """Check again or Try again on an earlier send: no new call may be made. X1 does it
    as the composer does (the lookup route, or the same op id again), or Jake does it
    on his phone."""
    of = next(s for g in kit.plan["groups"] for s in g["steps"] if s["id"] == step["of"])
    label, text = of["thread"], kit.texts[of["msg"]]
    kit.arm(step["id"])  # no tell allowed
    if step.get("by") == "x1" or kit.dry:
        if step["button"] == "Check again":
            shown = lookup(kit, label, kit.opids[of["id"]])
        else:
            body = {"op_id": kit.opids[of["id"]], "mode": of["mode"], "text": text,
                    "resume_paused_queue": False, "accept_possible_duplicate": False}
            shown = post(kit, label, body)[2]
    else:
        say("PRESS: on %s, press %s on %s's pending send." % (step["device"], step["button"], label))
        shown = ask(kit, step["id"], "What does the composer show now? (sent, queued, failed, uncertain)",
                    ("sent", "queued", "failed", "uncertain"))
    time.sleep(1)
    rec = kit.record(label, sha(text)) or {}
    got = {"shown": shown, "record": rec.get("state"), "delivery": rec.get("delivery"),
           "recovered": rec.get("recovered")}
    got.update({k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls")})
    kit.disarm()
    return got


def do_replay(kit, step):
    """The same op id's request again: a replay must make no call (X2 allows none)."""
    of = next(s for g in kit.plan["groups"] for s in g["steps"] if s["id"] == step["of"])
    text = kit.texts[of["msg"]]
    kit.arm(step["id"])
    body = {"op_id": kit.opids[of["id"]], "mode": of["mode"], "text": text,
            "resume_paused_queue": False, "accept_possible_duplicate": False}
    status, rep, _ = post(kit, of["thread"], body)
    kit.disarm()
    got = dict(report_fields(rep), http=status)
    got.update({k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls")})
    return got


PROBES = (  # (name, header changes, expected status)
    ("loopback Host", {"Host": "127.0.0.1:{port}", "Origin": "http://127.0.0.1:{port}"}, 421),
    ("no Origin", {"Origin": None}, 403),
    ("foreign Origin", {"Origin": "https://example.invalid"}, 403),
    ("cross-site fetch", {"Sec-Fetch-Site": "cross-site"}, 403),
    ("no X-OpenWiz-Send", {"X-OpenWiz-Send": None}, 403),
    ("form content type", {"Content-Type": "application/x-www-form-urlencoded"}, 415),
)


def public_probe(kit, label, body):
    """An unauthenticated send to the public hostname: Access must answer (302, 401
    or 403) before anything reaches the Mac."""
    import ssl
    import urllib.parse
    data = json.dumps(body).encode()
    url = urllib.parse.urlsplit(kit.cfg.get("access_url") or "https://" + kit.cfg["host"])
    try:
        if url.scheme == "https":
            conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=20,
                                               context=ssl.create_default_context())
        else:  # tests only: a stand-in for Access on loopback
            conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=20)
        conn.request("POST", "/api/v1/sessions/%s/messages" % kit.threads[label], body=data,
                     headers={"Host": kit.cfg["host"], "Content-Type": "application/json", "X-OpenWiz-Send": "1"})
        status = conn.getresponse().status
        conn.close()
        return status
    except (OSError, http.client.HTTPException):
        return None


def do_probe(kit, step):
    """L9: requests that must send nothing. X2 allows no tell, so even one that got
    through would be refused, and counted."""
    label, text = step["thread"], kit.texts[step["msg"]]
    kit.arm(step["id"])
    body = {"op_id": "op-acc-M25-" + secrets.token_hex(8), "mode": "queue", "text": text,
            "resume_paused_queue": False, "accept_possible_duplicate": False}
    results, port = {}, kit.cfg["port"]
    for name, change, want in PROBES:
        h = {k: (v.format(port=port) if isinstance(v, str) else v) for k, v in change.items()}
        results[name] = {"status": post(kit, label, body, headers=h)[0], "expected": [want]}
    if kit.dry:
        results["public, no login"] = {"status": "not made (dry run)", "expected": ["not made (dry run)"]}
    else:
        results["public, no login"] = {"status": public_probe(kit, label, body), "expected": [302, 401, 403]}
        write_private(os.path.join(kit.run, "cross-site-probe.html"), CROSS_SITE_PAGE.format(
            host=kit.cfg["host"], id=kit.threads[label], body=json.dumps(body).replace('"', "&quot;")))
        say("OPTIONAL (Jake, at the Mac, 1 minute): open %s in Safari and press its two buttons."
            % os.path.join(kit.run, "cross-site-probe.html"))
        results["cross-site page"] = {"status": ask(kit, step["id"], "Cross-site page: done or skip?",
                                                    ("done", "skip")), "expected": ["done", "skip"]}
    time.sleep(1)
    kit.disarm()
    got = {"probes": {k: v["status"] for k, v in results.items()},
           "probes_as_expected": all(v["status"] in v["expected"] for v in results.values())}
    got.update({k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls")})
    return got


CROSS_SITE_PAGE = """<!doctype html><meta charset="utf-8"><title>OpenWiz L9 cross-site probe</title>
<p>Synthetic probe for OpenWiz's live test (L9). Each button tries to send M25 from another origin; both must send nothing.</p>
<form method="post" action="https://{host}/api/v1/sessions/{id}/messages" enctype="text/plain">
<input type="hidden" name="{body}" value=""><button>1. Cross-site form post</button></form>
<button onclick="fetch('https://{host}/api/v1/sessions/{id}/messages',{{method:'POST',credentials:'include',mode:'no-cors',body:'{{}}'}})">2. Cross-site fetch</button>
"""


def do_quiet(kit, step):
    """No OpenWiz call: wait (and, after F4 and F6, start the server again) while X2
    allows no tell. Anything that dispatches by itself is counted."""
    kit.arm(step["id"])
    if step.get("server") == "start":
        swap_control(kit, "start-server")
    a = kit.args
    secs = {"settle": a.settle, "settle+late": a.settle + a.late}[step["wait"]]
    time.sleep(secs)
    got = {k: v for k, v in kit.tells(step["id"]).items() if k in ("attempts", "calls")}
    kit.disarm()
    return got


def do_record(kit, step):
    of = next(s for g in kit.plan["groups"] for s in g["steps"] if s["id"] == step["of"])
    rec = kit.record(of["thread"], sha(kit.texts[of["msg"]]), kit.opids.get(of["id"]))
    if rec is None:
        return {"incomplete": "no send record"}
    return {"state": rec["state"], "delivery": rec["delivery"], "text_kept": rec["text_kept"] and rec["text_matches"]}


def say(text):
    sys.stderr.write("\n>>> " + text + "\n")
    sys.stderr.flush()


def ask(kit, step_id, question, choices):
    """Jake's answer. `--answers chat` (the default): Jake answers the runner in chat,
    and the runner writes it to <run>/answer-<step>.txt. `--answers terminal`: typed."""
    if kit.args.answers == "terminal":
        while True:
            sys.stderr.write(">>> %s " % question)
            sys.stderr.flush()
            a = sys.stdin.readline().strip().lower()
            if a in choices:
                return a
    path = os.path.join(kit.run, "answer-%s.txt" % step_id)
    say("ANSWER %s: %s (Jake answers the runner, which writes it to answer-%s.txt)" % (step_id, question, step_id))
    end = time.monotonic() + kit.args.press_timeout
    while time.monotonic() < end:
        if os.path.exists(path):
            words = open(path).read().split()
            os.remove(path)
            if words and words[0].lower() in choices:
                return words[0].lower()
            say("ANSWER %s: not one of %s; again" % (step_id, ", ".join(choices)))
        time.sleep(0.5)
    raise Stop("no answer for %s within %d s" % (step_id, kit.args.press_timeout))


# --------------------------------------------------------------------------
# Groups and the bracket


def judged_set(snap, not_judged, warm_hours, start_ms):
    """The sessions the bracket judges while Jake keeps working: quiet at the run's
    start AND not updated in the `warm_hours` before it (cold). Jake's recent and
    running sessions, sessions that appear later, the test threads and the excluded
    ids are reported, never judged. A change in a judged session stops the run."""
    cut = start_ms - int(warm_hours * 3600 * 1000)
    out = set()
    for sid, row in snap["rows"].items():
        up = row.get("updatedAt")
        if (sid not in not_judged and qc.classify(row) == "quiet"
                and isinstance(up, int) and not isinstance(up, bool) and up < cut):
            out.add(sid)
    return out


def settle(kit):
    """Every test thread idle with no queue row, and at least `settle` seconds."""
    a = kit.args
    t0 = time.monotonic()
    ok = wait_for(lambda: all((lambda s: s["idle"] and s["rows"] == 0)(target_state(kit, l)) for l in LABELS),
                  a.idle_timeout, a.poll)
    rest = a.settle - (time.monotonic() - t0)
    if rest > 0:
        time.sleep(rest)
    return ok


def run_groups(kit, names):
    a = kit.args
    groups = {g["id"]: g for g in kit.plan["groups"]}
    for n in names:
        if n not in groups:
            raise Stop("no group " + n)
    test_ids = set(kit.threads.values())
    exclude = set(a.exclude_id or [])
    t0 = time.monotonic()
    x2 = os.path.join(kit.x2, "room-cli")
    if not os.path.exists(x2) or observe.file_sha256(x2) != observe.file_sha256(os.path.join(HERE, "x2-shim.py")):
        raise Stop("X2 is missing or is not the reviewed shim; nothing was sent")
    kit.require_clean()
    # L-8's allowance, across sittings (Sol's R8 on #168): a step already called in any sitting
    # is never repeated, and the groups must fit what is left. X2 enforces both again.
    try:
        al, by = kit.allowance(by_step=True)
    except Stop as e:
        raise Stop("%s; nothing was sent" % e)
    steps = [s for n in names for s in groups[n]["steps"] if step_calls(s)]
    if any(by.get(s["id"], 0) > 0 for s in steps):
        raise Stop("%d of these steps made their calls already, in an earlier sitting or this one; run only "
                   "the groups still to run; nothing was sent" % sum(1 for s in steps if by.get(s["id"], 0) > 0))
    need = sum(step_calls(s) for s in steps)
    if need > al["remaining"]:
        raise Stop("these groups need %d sends, and the approved allowance (L-8) has %d left; nothing was sent"
                   % (need, al["remaining"]))
    kit.disarm()
    version = qc.version_record(kit.ctx)
    collect_forbidden(kit)
    first = qc.lists(kit.ctx, "before")
    for label, sid in kit.threads.items():
        if sid not in first["views"].get("default", []):
            raise Stop("test thread %s is not in the default list view" % label)
    # The judged set, its baseline rows and the samples' starting points are the SITTING's:
    # made by its first run command and kept in the run directory for every later one (Sol's
    # review of the 0.0.4 kit, finding 3), so a judged session that changes between two run
    # commands is still caught, and nothing between them can make it unjudged.
    sitting_path = os.path.join(kit.run, "sitting.json")
    if os.path.exists(sitting_path):
        sitting = json.load(open(sitting_path))
        judged = set(sitting["judged"])
        first = dict(first, rows=dict(first["rows"], **sitting["baseline"]))
        samples = sitting["samples"]
        details0 = sitting["details0"]
    else:
        judged = judged_set(first, exclude | test_ids, a.warm_hours, now_ms())
        if len(judged) < a.min_judged:  # too few cold sessions to stand for the rest: never a pass
            raise Stop("only %d sessions are quiet and older than %g h (at least %d are needed); "
                       "nothing was sent" % (len(judged), a.warm_hours, a.min_judged))
        samples = qc.choose_samples(strip(first, test_ids), set(first["rows"]) - judged, a.samples)
        details0 = {s: observe.detail(kit.ctx, s) for s in samples}
        write_private(sitting_path, {"judged": sorted(judged), "baseline": {sid: first["rows"][sid] for sid in judged},
                                     "samples": samples, "details0": details0, "started_ms": now_ms()})
    details = dict(details0)  # each group reads the samples' new events since the sitting began
    rep = {"report": "openwiz-0.0.3-live-test", "dry_run": kit.dry,
           "kit_sha256": observe.file_sha256(__file__),
           "core_sha256": observe.file_sha256(core.__file__),
           "x2_sha256": observe.file_sha256(os.path.join(kit.x2, "room-cli")),
           "quick_check_sha256": observe.file_sha256(qc.__file__),
           "observe_sha256": observe.file_sha256(observe.__file__),
           "version_read": version, "groups": [], "outcome": "as_expected",
           "judged": {"rule": "quiet at the start and not updated in the %g h before it; "
                              "each judged against its own start, on every field" % a.warm_hours,
                      "sessions": len(judged),
                      "not_judged": {"recent_or_active": len(set(first["rows"]) - judged - test_ids - exclude),
                                     "excluded_ids": len(exclude & set(first["rows"])),
                                     "test_threads": len(test_ids)}}}
    stop = None
    land0 = landing_all(kit)
    rep["landing_at_start"] = land0["verdict"]
    if land0["verdict"] != "as_expected":
        stop = "incomplete: the test threads do not hold what the steps so far sent: " + land0["verdict"]
    prev = first
    for name in names:
        if stop:
            break
        g = groups[name]
        grep = {"group": name, "claims": g["claims"], "steps": []}
        rep["groups"].append(grep)
        seqs = []
        for s in g["steps"]:
            if not seqs or seqs[-1][0] != s["seq"]:
                seqs.append((s["seq"], []))
            seqs[-1][1].append(s)
        for _, steps in seqs:
            if stop:
                break
            for a_, b_ in zip(steps, steps[1:]):
                if a_.get("do") == "press" and b_.get("do") == "press":
                    a_["_next"] = b_
            ran = []
            for step in steps:
                srep = run_step(kit, step)
                grep["steps"].append(srep)
                ran.append(step)
                sys.stderr.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), step["id"], srep["verdict"]))
                sys.stderr.flush()
                if srep["verdict"] == "as_expected" and kit.ledger():
                    # Sol's review of the 0.0.4 kit, finding 4, and R13: any refusal at X2
                    # taints the sitting, and stops the run.
                    srep["verdict"] = "not_as_expected: " + taint_text(kit.ledger())
                if srep["verdict"] != "as_expected":
                    stop = "%s: %s" % (step["id"], srep["verdict"])
                    break
            if not settle(kit):
                stop = stop or "incomplete: a test thread did not settle within %d s" % a.idle_timeout
            # Where every approved text landed so far (L1, L8, L11), cumulatively (Sol R5).
            expect_landing(kit, ran)
            land = landing_all(kit)
            grep.setdefault("landing", []).append(land)
            if land["verdict"] != "as_expected":
                stop = stop or land["verdict"]
        if not stop and a.late:
            kit.arm(name + "-late")
            time.sleep(a.late)
            late = kit.tells(name + "-late")["attempts"]
            kit.disarm()
            land = landing_all(kit)
            grep["late_wait"] = {"s": a.late, "attempts": late, "landing": land["verdict"]}
            if late:
                stop = "%s: a call during the late wait" % name
            elif land["verdict"] != "as_expected":
                stop = "%s, after the late wait: %s" % (name, land["verdict"])
        # The bracket: the judged sessions against the run's start (the quick check's
        # list fields, plus what decides quiet or active), and the samples' events.
        collect_forbidden(kit)
        after = qc.lists(kit.ctx, "after-" + name)
        details_a = {s: observe.detail(kit.ctx, s, details[s]) for s in samples}
        res = {s: qc.sample_eval(kit.ctx, s, details0[s], details_a[s]) for s in samples}
        failures, missing = judge(first, after, judged)
        sample_fail = sum(1 for r in res.values() if r["advance"] or r["qmc_changed"])
        unreadable = sum(1 for r in res.values() if r["unreadable"]) + sum(after.get("unreadable", {}).values())
        grep["outside"] = {"sessions": len(after["rows"]), "judged": len(judged),
                           "appeared_not_judged": len(set(after["rows"]) - set(first["rows"])),
                           "failures": failures, "missing_field": missing,
                           "not_judged_changed": unjudged_changes(prev, after, judged | test_ids),
                           "samples": len(samples), "samples_with_new_events": sample_fail,
                           "unreadable": unreadable}
        if failures or sample_fail:
            grep["outside"]["verdict"] = "not_as_expected: a judged session changed (L1)"
            stop = stop or "%s: a judged session outside the test threads changed (L1)" % name
        elif missing or unreadable:
            grep["outside"]["verdict"] = "incomplete: something judged could not be compared"
            stop = stop or "%s: incomplete outside the test threads" % name
        else:
            grep["outside"]["verdict"] = "as_expected"
        # Anything X2 refused (a send from the web page between steps, a call off the
        # allowlist) reached no thread; it still taints the sitting, and stops the run.
        found = kit.ledger()
        if found:
            grep["outside"]["x2_ledger"] = ledger_counts(found)
            stop = stop or "%s: %s" % (name, taint_text(found))
        # X1's own count, apart from X2's gate: any tell at all between steps, in the sitting.
        between = kit.tells("between-steps")["attempts"]
        if between:
            grep["outside"]["tells_between_steps"] = between
            stop = stop or "%s: a send outside the plan reached X2" % name
        prev, details = after, details_a
    if not stop:
        land = landing_all(kit)  # the run's close
        rep["landing_at_end"] = land["verdict"]
        if land["verdict"] != "as_expected":
            stop = "at the end: " + land["verdict"]
    rep["stopped"] = stop
    rep["outcome"] = "as_expected" if not stop else ("incomplete" if "incomplete" in stop else "not_as_expected")
    rep["reads"] = dict(sorted(kit.ctx.reads.items()))
    rep["duration_s"] = int(time.monotonic() - t0)
    return publish(kit, rep)


def run_step(kit, step):
    t0 = now_ms()
    do = step["do"]
    srep = {"step": step["id"], "do": do}
    try:
        if do in ("send", "press", "post"):
            label, text = step["thread"], kit.texts[step["msg"]]
            if sha(text) != APPROVED[step["msg"]]:
                raise Stop("a text's hash changed")
            pre = ensure(kit, step, label)
            if pre:
                srep["verdict"] = pre
                return srep
            got = do_send(kit, step, label, text) if do == "send" else do_web(kit, step, label, text)
            if step["expect"].get("queue_rows_after") is not None:
                got["queue_rows_after"] = target_state(kit, label)["rows"]
        elif do == "quiet":
            got = do_quiet(kit, step)
        elif do == "record":
            got = do_record(kit, step)
        elif do == "hand":
            got = do_hand(kit, step)
        elif do == "replay":
            got = do_replay(kit, step)
        elif do == "probe":
            got = do_probe(kit, step)
        else:
            raise Stop("unknown step kind")
    except Stop as e:
        srep["verdict"] = "incomplete: " + str(e)
        return srep
    finally:
        kit.disarm()  # Sol R2: no step ever ends with a send armed
    if "incomplete" in got:
        srep["verdict"] = "incomplete: " + got.pop("incomplete")
        return srep
    exp = dict(step["expect"])
    bad = check({k: v for k, v in exp.items() if k not in ("deliver", "exact")}, got)
    if "produced_if_shown" in exp:  # F7: Jake's network may go off only after the answer arrived
        srep["fault_produced"] = got.get("shown") == exp["produced_if_shown"]
    if "shown" in exp and got.get("shown") not in exp["shown"]:
        bad.append("the composer showed %s, expected %s" % (got.get("shown"), "/".join(exp["shown"])))
    if "queue_rows_after" in exp and got.get("queue_rows_after") != exp["queue_rows_after"]:
        bad.append("queue rows %s, expected %s" % (got.get("queue_rows_after"), exp["queue_rows_after"]))
    if do == "probe" and not got.get("probes_as_expected"):
        bad.append("a probe answered other than expected")
    if got.get("bad_text"):
        bad.append("the report's text hash is not the approved one")
    if got.get("refused"):
        bad.append("X2 refused %d tell(s): a call to another thread, mode or text, or a resend" % got["refused"])
    if got.get("revoked"):
        bad.append("X2 aborted %d held tell(s): the step was disarmed or expired during the hold" % got["revoked"])
    if "second" in got and got["second"] not in ("replayed", "in_progress"):
        bad.append("the second press's answer was %s, not a replay" % got["second"])
    keep = ("exit", "exit_list", "status", "delivery", "reason", "waiting_on", "replayed", "recovered",
            "differs", "effect", "text_sha_matches", "attempts", "calls", "refused", "aborted", "revoked", "record",
            "state", "text_kept", "shown", "race_exit", "http", "probes", "queue_rows_after", "second", "ms")
    srep["got"] = {k: got[k] for k in keep if k in got}
    if do in ("send",) and "keys" in got:
        srep["report_keys_sha256"] = hashlib.sha256(json.dumps(got["keys"], sort_keys=True).encode()).hexdigest()
        write_private(os.path.join(kit.run, "keys-%s.json" % step["id"]), got["keys"])
    srep["ms"] = now_ms() - t0
    srep["verdict"] = "as_expected" if not bad else "not_as_expected: " + "; ".join(bad)
    return srep


def expect_landing(kit, steps):
    """Adds the steps that ran to the run's cumulative expectations (run/landing.json)."""
    st = kit._load("landing.json", {"expected": {}, "exact": []})
    for s in steps:
        if "msg" in s and s.get("expect", {}).get("deliver") is not None:
            key = "%s|%s" % (s["thread"], s["msg"])
            st["expected"][key] = st["expected"].get(key, 0) + s["expect"]["deliver"]
            if s["expect"].get("exact") and s["msg"] not in st["exact"]:
                st["exact"].append(s["msg"])
    write_private(os.path.join(kit.run, "landing.json"), st)


def landing_all(kit):
    """Sol R5: every approved text, on all three test threads, from each thread's first
    event, against what every completed step so far expects: on its own thread
    exactly as often as expected, never on another, never twice in one event type,
    the L11 texts exact, and no attachment key. M18, M20 and M25 are expected nowhere."""
    st = kit._load("landing.json", {"expected": {}, "exact": []})
    events = {l: all_events(kit, l) for l in LABELS}
    out, bad = {"checked": [], "verdict": "as_expected"}, []
    for m in sorted(APPROVED):
        text = kit.texts[m]
        for l in LABELS:
            c = carrying(events[l], text)
            want = st["expected"].get("%s|%s" % (l, m), 0)
            n = c["exact"] + len(c["wrapped"])
            if want or n:
                out["checked"].append({"msg": m, "thread": l, "expected": want, "carrying": n,
                                       "max_per_event_type": c["max_per_type"], "exact": c["exact"],
                                       "wrapped": c["wrapped"]})
            if c["max_per_type"] != want:
                bad.append("%s on %s: %d, expected %d" % (m, l, c["max_per_type"], want))
            if m in st["exact"] and c["wrapped"]:
                bad.append("%s arrived wrapped (L11: Jake decides)" % m)
            if [k for keys in c["data_keys"] for k in keys if k in ("files", "attachments", "images")]:
                bad.append("%s's event has an attachment key" % m)
    if bad:
        out["verdict"] = "not_as_expected: " + "; ".join(bad)
    return out


TITLE_KEYS = ("id", "title", "titleFallback", "projectId", "parentThreadId", "environmentId", "environmentHostId")


def collect_forbidden(kit):
    """Sol R4: every live string a report must never hold, kept in memory only: each
    session's id and title (and its project, parent, environment and host ids), each
    project's and machine's id and name, and the test threads' titles."""
    def add(v):  # every nonempty string, however short (Sol R4, round 2: a false stop beats a leak)
        if isinstance(v, str) and v.strip() and v != observe.MISSING:
            kit.forbidden.add(v)
    rows = kit.ctx.room_json(["thread", "list", "--json", "--include-hidden", "--include-archived"])
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            for k in TITLE_KEYS:
                add(r.get(k))
    for flags in ([], ["--hidden"]):
        for r in kit.ctx.room_json(["project", "list", "--json", "--include-personal"] + flags) or []:
            if isinstance(r, dict):
                add(r.get("id"))
                add(r.get("name"))
    for r in kit.ctx.room_json(["machine", "list", "--json"]) or []:
        if isinstance(r, dict):
            add(r.get("id"))
            add(r.get("name"))
    for sid in kit.threads.values():
        show = kit.ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
        if isinstance(show, dict):
            add((show.get("thread") or {}).get("title"))


def publish(kit, rep):
    """The leak scan, on every report X1 prints, over the decoded report. A hit prints
    nothing, and keeps the report on the Mac only. Under X2's lock, the outcome is
    decided from the sitting ledger, then the report is written (Sol R13)."""
    with kit.lock():
        decide(kit, rep)
        return _write_report(kit, rep)


def _write_report(kit, rep):
    text = json.dumps(rep, indent=1, sort_keys=True)
    decoded = json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False)
    args = getattr(kit, "args", None)
    forbid = set(kit.forbidden) | set(kit.threads.values()) | set(kit.opids.values()) \
        | set(getattr(args, "forbid", None) or []) | set(getattr(args, "exclude_id", None) or []) \
        | {kit.work, os.path.expanduser("~"), kit.cfg["host"]}
    hits = len(leaked(forbid, rep))
    if hits:
        write_private(os.path.join(kit.run, "report-blocked-%d.json" % now_ms()), decoded)
        raise Stop("the report would contain %d forbidden strings; nothing printed "
                   "(kept in the run directory only)" % hits)
    n = len([f for f in os.listdir(kit.run) if f.startswith("report-")])
    write_private(os.path.join(kit.run, "report-%02d.json" % (n + 1)), text)
    return rep


# --------------------------------------------------------------------------
# Commands


def cmd_texts(a):
    texts, threads = load_texts(a.texts)
    rows = [{"label": k, "thread": threads[k], "bytes": len(texts[k].encode()), "sha256": sha(texts[k])}
            for k in sorted(texts)]
    return {"texts": rows, "all_approved": True}


def cmd_setup(a):
    work = os.path.abspath(a.work)
    if os.path.exists(work):
        raise Stop("the work directory exists; each run needs a new one")
    if in_repository(os.path.dirname(work)):
        raise Stop("the work directory is inside a git repository (openwiz refuses such a state directory)")
    for p in (a.room_cli, a.openwiz) + ((a.server,) if a.server else ()):
        if not (os.path.isabs(p) and os.access(p, os.X_OK)):
            raise Stop("every program path must be absolute and executable")
    texts, _ = load_texts(a.texts)
    load_plan(a.plan, texts)
    read_threads(a.threads)
    binary = {}
    for name, path, want in (("openwiz", a.openwiz, a.expect_sha256),
                             ("openwiz-server", a.server, a.expect_server_sha256)):
        if want:
            if observe.file_sha256(path) != want.lower():
                raise Stop("the %s binary's sha256 is not the expected one" % name)
            binary[name] = "sha256 matches"
    if a.checkout:
        head = subprocess.run(["git", "-C", a.checkout, "rev-parse", "HEAD"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode().strip()
        if a.expect_head and head != a.expect_head:
            raise Stop("the checkout's head is not the expected one")
        binary["head"] = head
    # L-8's allowance (Sol's R8 on #168): one directory outside every sitting. A fresh setup
    # inherits what is left; only Jake amending L-8 changes the total.
    adir = os.path.abspath(os.path.expanduser(a.allowance))
    total = planned_calls(load_plan(a.plan, texts))
    if adir == work or adir.startswith(work + os.sep) or work.startswith(adir + os.sep) or in_repository(adir):
        raise Stop("the allowance directory must be its own, outside the work directory and any repository")
    afile, journal = os.path.join(adir, "allowance.json"), os.path.join(adir, "charges.log")
    os.makedirs(adir, mode=0o700, exist_ok=True)
    # Sol R14: the first setup makes the manifest and its empty charge journal together, under the
    # allowance's lock; every later one requires both. A lost or unreadable journal (or a journal
    # without its manifest) is unknown usage, never zero: setup stops before making a sitting.
    with open(os.path.join(adir, "allowance.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(afile):
            try:
                on_record = json.load(open(afile))["total"]
            except (OSError, ValueError, KeyError, TypeError):
                raise Stop("the allowance on record cannot be read")
            if on_record != total:
                raise Stop("the allowance on record is not L-8's %d sends; only Jake can amend it" % total)
            read_charges(adir)
        elif os.path.lexists(journal):
            raise Stop("the allowance's charge journal (charges.log) has no manifest (allowance.json): its "
                       "approval is unknown; ask Jake to reconcile it")
        else:  # the first setup: the empty journal first, then the manifest (each whole or not at all)
            os.close(os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            write_private(afile, {"total": total, "approval": "L-8"})
    os.makedirs(work, mode=0o700)
    for d in ("x2", "state", "run"):
        os.makedirs(os.path.join(work, d), mode=0o700)
    write_private(os.path.join(work, "x2", "sitting.log"), "")
    shutil.copyfile(os.path.join(HERE, "x2-shim.py"), os.path.join(work, "x2", "room-cli"))
    os.chmod(os.path.join(work, "x2", "room-cli"), 0o700)
    restore = json.loads(a.restore_cmd) if a.restore_cmd else None
    if restore is not None and not (isinstance(restore, list) and restore and all(isinstance(x, str) for x in restore)
                                    and os.path.isabs(restore[0]) and a.restore_log and os.path.isabs(a.restore_log)
                                    and a.restore_sha256):
        raise Stop("the confirmed 0.0.2 launch needs an absolute command (JSON), its log and its sha256")
    cfg = {"room_cli": os.path.abspath(a.room_cli), "openwiz": os.path.abspath(a.openwiz),
           "server": os.path.abspath(a.server) if a.server else None, "texts": os.path.abspath(a.texts),
           "plan": os.path.abspath(a.plan), "threads": os.path.abspath(a.threads), "port": a.port,
           "host": a.host, "web_root": a.web_root, "dry_run": a.dry_run, "access_url": a.access_url,
           "restore_cmd": restore, "restore_log": a.restore_log,
           "restore_sha256": a.restore_sha256.lower() if a.restore_sha256 else None,
           "allowance": adir, "sitting": secrets.token_hex(8)}
    write_private(os.path.join(work, "kit.json"), cfg)
    kit = Kit(work)
    kit.disarm()
    kit.path_guard(kit.env())
    return {"setup": "ready", "dry_run": a.dry_run, "binary": binary,
            "x2_sha256": observe.file_sha256(os.path.join(work, "x2", "room-cli")),
            "kit_sha256": observe.file_sha256(__file__),
           "core_sha256": observe.file_sha256(core.__file__), "path_guard": "room-cli on the send PATH is X2",
            "allowance": kit.allowance()}


def cmd_map(a):
    """The test threads, checked; titles only with --show-titles, on Jake's screen."""
    kit = Kit(a.work)
    kit.require_clean()
    kit.disarm()
    default = kit.ctx.room_json(["thread", "list", "--json"])
    ids = {r.get("id") for r in default if isinstance(r, dict)}
    out, bad = {}, []
    for label in LABELS:
        sid = kit.threads[label]
        show = kit.ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
        if not isinstance(show, dict):
            bad.append("%s not found" % label)
            continue
        t = show.get("thread") or {}
        local = isinstance((show.get("environment") or {}).get("hostId"), str)
        s = target_state(kit, label)
        row = {"where": "Local" if local else "Cloud", "harness": t.get("providerId"),
               "status": s["status"], "queued": s["qmc"], "queue_rows": s["rows"],
               "in_default_view": sid in ids, "events": len(all_events(kit, label))}
        if a.show_titles:
            row["title"] = t.get("title")
        out[label] = row
        want = "Local" if label == "T-A" else "Cloud"
        if row["where"] != want:
            bad.append("%s is %s, should be %s" % (label, row["where"], want))
        if not (s["idle"] and s["qmc"] == 0 and s["rows"] == 0 and sid in ids):
            bad.append("%s is not idle, empty and visible" % label)
    if bad:
        raise Stop("; ".join(bad))
    rep = {"threads": out, "map": "ok: Jake confirms each label by eye", "outcome": "as_expected"}
    if a.show_titles:
        with kit.lock():
            return decide(kit, rep)  # Jake's own terminal only: never saved, never committed
    collect_forbidden(kit)
    return publish(kit, rep)


def cmd_recheck(a):
    """L-3: thread tell's help, kept on the Mac; only its structure is printed."""
    kit = Kit(a.work)
    kit.require_clean()
    r = kit.ctx.room(["thread", "tell", "--help"])
    text = (r.stdout + r.stderr).decode("utf-8", "replace")
    write_private(os.path.join(kit.run, "thread-tell-help.txt"), text)
    collect_forbidden(kit)
    return publish(kit, {"outcome": "as_expected", "exit": r.returncode, "help_sha256": sha(text), "lines": len(text.splitlines()),
            "shows_double_dash": bool(re.search(r"(^|[\s\[])--(\s|\]|$)", text)),
            "mentions_stdin": "stdin" in text.lower(),
            "rule": "if --'s meaning as the end of options is not confirmed, group C1 (M13 alone) runs first and "
                    "any surprise stops the run (L-3)"})


def cmd_parity(a):
    """L10: the CLI's and the web's send records, by kind, structure only (no call)."""
    kit = Kit(a.work)
    kit.require_clean()
    pairs = (("idle send", "C2-M01", "P1-M06"), ("queue on busy", "C2-M03", "W1-M08"),
             ("steer on busy", "C3-M05", "W2-M10"))
    steps = {s["id"]: s for g in kit.plan["groups"] for s in g["steps"]}
    out = {}
    for name, cli, web in pairs:
        rc = rw = None
        if cli in kit.opids and web in kit.opids:
            rc = kit.record(steps[cli]["thread"], APPROVED[steps[cli]["msg"]], kit.opids[cli])
            rw = kit.record(steps[web]["thread"], APPROVED[steps[web]["msg"]], kit.opids[web])
        if not rc or not rw:
            out[name] = {"verdict": "incomplete: a record is missing"}
            continue
        out[name] = {"cli": rc["delivery"], "web": rw["delivery"],
                     "record_structure_equal": rc["keys"] == rw["keys"],
                     "verdict": "as_expected" if rc["delivery"] == rw["delivery"] and rc["keys"] == rw["keys"]
                     else "not_as_expected"}
    verdicts = [v["verdict"] for v in out.values()]
    outcome = ("as_expected" if all(v == "as_expected" for v in verdicts) else
               "not_as_expected" if any(v == "not_as_expected" for v in verdicts) else "incomplete")
    collect_forbidden(kit)
    return publish(kit, {"parity": out, "outcome": outcome})  # Sol R8: a failure exits nonzero


# Sol R6, round 3: each page route's answer is validated against its contract schema
# file (contracts/, pushed to the Mac with the kit), with a small validator for the
# subset of JSON Schema those files use.
CONTRACTS = os.path.join(TOOLKIT, "test", "contracts")
_SCHEMAS = {}


def contract(name):
    if name not in _SCHEMAS:
        with open(os.path.join(CONTRACTS, name)) as f:
            _SCHEMAS[name] = json.load(f)
    return _SCHEMAS[name]


def page_answer_problem(route, status, doc, ta):
    """None if the answer is valid for this route by its contract and names T-A; else what
    is wrong (a JSON path and a rule, never a value)."""
    if status != 200:
        return "status %s" % status
    if route in ("inventory", "session"):
        root = contract("inventory.v1.schema.json")
        e = schema_error(doc, {"$ref": "#/$defs/envelope"}, root)
        if e:
            return e
        e = schema_error(doc["data"], {"$ref": "#/$defs/" + ("inventory" if route == "inventory" else "session_view")},
                         root, "$.data")
        if e:
            return e
        ids = ([r["id"] for r in doc["data"]["sessions"]] if route == "inventory" else [doc["data"]["session"]["id"]])
        return None if ta in ids else ("T-A not in the inventory" if route == "inventory" else "another session")
    root = contract("messaging.v1.schema.json")
    e = schema_error(doc, {"$ref": "#/$defs/preview"}, root)
    if e:
        return e
    return None if doc["target"]["id"] == ta else "another session"


def cmd_l13(a):
    """L13: 0.0.1's quick check, unchanged, while the web page's reads run (the
    inventory, T-A's session and its composer preview, every 2 s, as the page polls).
    Jake keeps working, so the check judges only cold sessions and the test threads:
    every session updated in the `--warm-hours` before it, or not quiet, is passed to
    it as --exclude-id (counted, never printed). X2 timestamps every page read, so the
    reads inside the check's window are counted, and it allows no tell."""
    kit = Kit(a.work)
    kit.require_clean()
    name = "L13"
    test_ids = set(kit.threads.values())
    rows = kit.ctx.room_json(["thread", "list", "--json", "--include-hidden", "--include-archived"])
    snap = {"rows": {r["id"]: observe.list_fields(r) for r in rows
                     if isinstance(r, dict) and isinstance(r.get("id"), str) and ID_RE.match(r["id"])}}
    judged = judged_set(snap, test_ids, a.warm_hours, now_ms()) | test_ids
    if len(judged) - len(test_ids) < a.min_judged:
        raise Stop("only %d sessions are quiet and older than %g h (at least %d are needed)"
                   % (len(judged) - len(test_ids), a.warm_hours, a.min_judged))
    warm = sorted(set(snap["rows"]) - judged)
    qargs = list(a.qc_args)
    if qargs[:1] == ["--"]:
        qargs = qargs[1:]
    for sid in warm:
        qargs += ["--exclude-id", sid]
    kit.arm(name)
    t0 = now_ms()
    stop = threading.Event()
    ta = kit.threads["T-A"]
    routes = (("inventory", "/api/v1/inventory", "openwiz.inventory.v1"),
              ("session", "/api/v1/sessions/%s" % ta, "openwiz.inventory.v1"),
              ("preview", "/api/v1/sessions/%s/preview" % ta, "openwiz.send-preview.v1"))
    answers = {r[0]: {"valid": 0, "failed": 0} for r in routes}

    def page():  # the page's polling, as the tunnel delivers it (Sol R6: every answer is checked)
        while not stop.wait(2):
            for route, path, schema in routes:
                why = "no answer"
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", kit.cfg["port"], timeout=20)
                    conn.request("GET", path, headers={"Host": kit.cfg["host"], "Accept": "application/json",
                                                       "X-Requested-With": "XMLHttpRequest"})
                    r = conn.getresponse()
                    body = r.read()
                    conn.close()
                    why = page_answer_problem(route, r.status, json.loads(body), ta)
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                answers[route]["valid" if why is None else "failed"] += 1
                if why is not None:  # a kind of problem only, never a value
                    answers[route].setdefault("problems", [])
                    if why not in answers[route]["problems"]:
                        answers[route]["problems"].append(why)
    th = threading.Thread(target=page, daemon=True)
    th.start()
    p = subprocess.run([sys.executable, qc.__file__, "run"] + qargs, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stop.set()
    th.join(30)
    t1 = now_ms()
    try:
        qrep = json.loads(p.stdout)
    except ValueError:
        qrep = {}
    reads = {}
    path = os.path.join(kit.x2, "reads.log")
    for line in (open(path) if os.path.exists(path) else []):
        e = json.loads(line)
        if e.get("step") == name and t0 <= e.get("t_ms", 0) <= t1:
            k = re.sub(r"thread (show|output) \S+", r"thread \1", e.get("kind", ""))
            reads[k] = reads.get(k, 0) + 1
    attempts = kit.tells(name)["attempts"]
    kit.disarm()
    failed = sorted(k for k, v in answers.items() if v["failed"])
    silent = sorted(k for k, v in answers.items() if not v["valid"])
    verdict = ("not_as_expected: a tell during the check" if attempts else
               "not_as_expected: quick check %s" % qrep.get("outcome", qrep.get("stopped"))
               if qrep.get("outcome") != "pass" else
               "not_as_expected: page routes answered wrongly: %s" % ", ".join(failed) if failed else
               "incomplete: no valid answer from: %s" % ", ".join(silent) if silent else
               "incomplete: the page made no read during the check" if not reads else "as_expected")
    out = {"l13": {"quick_check": qrep.get("outcome", "stopped"), "quick_check_exit": p.returncode,
                   "judged": {"rule": "the test threads, and sessions quiet and not updated in the %g h before"
                                      % a.warm_hours, "sessions": len(judged & set(snap["rows"])),
                              "excluded_as_recent_or_active": len(warm)},
                   "quick_check_samples": (qrep.get("samples") or {}).get("count"),
                   "quick_check_why": {"failures": qrep.get("failures"),
                                       "openwiz_runs_failed": qrep.get("openwiz_runs_failed"),
                                       "samples_failed": (qrep.get("samples") or {}).get("failed"),
                                       "checks": {k: (v.get("outcome") if "outcome" in v else
                                                      {x: y.get("outcome") for x, y in v.items() if isinstance(y, dict)})
                                                  for k, v in (qrep.get("checks") or {}).items() if isinstance(v, dict)}},
                   "page_routes": answers, "page_reads_in_window": reads, "attempts": attempts,
                   "window_s": (t1 - t0) // 1000,
                   "verdict": verdict}, "outcome": "as_expected" if verdict == "as_expected" else "stop"}
    collect_forbidden(kit)
    return publish(kit, out)


# The receipt shapes observed live in #10 (2026-11-02, room-cli 0.43.1, its PC receipt probe):
# ticket 1's documented keys were never what room-cli printed. "documented_keys" in the
# report below now means these observed keys.
SENT_KEYS = {"threadId", "ok", "delivery", "mode"}
QUEUED_KEYS = {"id", "initiator", "senderThreadId", "threadId", "content", "model", "reasoningLevel",
               "permissionMode", "serviceTier", "hardQueue", "sendAt", "waitingOn", "failureReason",
               "payload", "editable", "createdAt", "updatedAt"}
STEER_QUEUED_KEYS = QUEUED_KEYS - {"hardQueue"}  # Cloud Queue or Steer, queued (waitingOn null)


def cmd_receipts(a):
    """L4: the structure of every receipt X2 captured (key names and JSON types,
    never a value), by kind, against the observed keys (SENT_KEYS, QUEUED_KEYS). A rejection
    (stderr) is reported only as whether its first line is a documented one."""
    kit = Kit(a.work)
    kit.require_clean()
    kinds = {}
    for name in sorted(os.listdir(kit.x2)):
        if not (name.startswith("capture-") and name.endswith(".out")):
            continue
        base = os.path.join(kit.x2, name[:-4])
        raw = open(base + ".out", "rb").read()
        err = open(base + ".err", "rb").read() if os.path.exists(base + ".err") else b""
        try:
            doc = json.loads(raw) if raw.strip() else None
        except ValueError:
            doc = "not_json"
        if isinstance(doc, dict):
            kind = doc.get("delivery") if doc.get("delivery") in ("sent", "queued") else "other"
            q = doc.get("queuedMessage")
            if kind == "queued":
                w = q.get("waitingOn", "absent") if isinstance(q, dict) else "absent"
                if doc.get("mode") == "queue" and w == {"kind": "thread-busy"}:
                    kind = "queued:thread-busy"
                elif doc.get("mode") in ("queue", "steer") and w is None:
                    kind = "queued:not-reported"
                else:
                    kind = "queued:other"
            documented = ((kind == "sent" and set(doc) == SENT_KEYS) or
                          (kind in ("queued:thread-busy", "queued:not-reported")
                           and set(doc) == SENT_KEYS | {"queuedMessage"}
                           and isinstance(q, dict)
                           and set(q) == (STEER_QUEUED_KEYS if kind == "queued:not-reported" else QUEUED_KEYS)))
            entry = {"structure": structure(doc), "documented_keys": documented}
        elif doc is None:
            first = err.decode("utf-8", "replace").splitlines()[:1]
            kind = "rejection"
            entry = {"first_line_documented": bool(first) and first[0] in (
                "Error: HTTP 404: Thread not found", "Error: HTTP 400: Invalid input",
                "Error: HTTP 400: Unsupported mode")}
        else:
            kind, entry = "not_json", {}
        # Sol R9: every receipt counts; one undocumented one makes its whole kind drift.
        k = kinds.setdefault(kind, {"count": 0})
        k["count"] += 1
        for key in ("documented_keys", "first_line_documented"):
            if key in entry:
                k[key] = k.get(key, True) and entry[key]
        if "structure" in entry:
            if "structure" in k and k["structure"] != entry["structure"]:
                k["structures_differ"] = True
            k.setdefault("structure", entry["structure"])
    drift = [k for k, v in sorted(kinds.items()) if v.get("documented_keys") is False
             or v.get("first_line_documented") is False or k in ("other", "not_json") or v.get("structures_differ")]
    drift += ["missing: %s" % r for r in a.require.split(",") if r and r not in kinds]
    collect_forbidden(kit)
    return publish(kit, {"receipts": kinds, "drift": drift, "required": a.require.split(","),
                         "outcome": "as_expected" if not drift else
                         "drift: blocks the claims that use these receipts (L4)"})


def cmd_swap(a):
    """The swap (the one --write step Jake OKs): `start` checks that the port is
    served by the confirmed 0.0.2 launch (or by nothing), then starts the supervisor
    and waits for X1's server; `end` asks it to restore 0.0.2; the others are the
    run's fault requests (F4, F6) and the restart."""
    kit = Kit(a.work)
    if a.action == "start":
        kit.require_clean()
        if swap_state(kit).get("state") in ("starting", "up"):
            raise Stop("a swap is already running")
        confirmed_old(kit)  # refuses before anything is signalled or started
        for f in ("swap.json", "swap-control"):
            if os.path.exists(os.path.join(kit.run, f)):
                os.remove(os.path.join(kit.run, f))
        log = os.open(os.path.join(kit.run, "supervisor.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "swap-supervise", "--work", kit.work,
                          "--minutes", str(a.minutes)], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
        os.close(log)
        wait_for(lambda: swap_state(kit).get("state") not in (None, "starting"), 60, 0.2)
    elif a.action == "end":
        if swap_state(kit).get("state") == "up":
            write_private(os.path.join(kit.run, "swap-control"), {"cmd": "end", "nonce": "end"})
        wait_for(lambda: swap_state(kit).get("state") in ("restored", "restore-failed", "restored-by-guard", "guard-died"), 90)
    else:
        swap_control(kit, a.action)
    st = swap_state(kit)
    want = {"start": "up", "end": "restored"}.get(a.action, "up")
    ok = st.get("state") == want or (a.action == "end" and st.get("state") == "restored-by-guard")
    # The restore is never held back by a tainted sitting; its report still fails (Sol R13).
    return publish(kit, {"swap": st.get("state"), "old_was_running": st.get("old_was_running"),
                         "error": st.get("error"), "outcome": "as_expected" if ok else "stop"})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("texts")
    s.add_argument("--texts", default=os.path.join(TICKET, "texts.tsv"))
    s = sub.add_parser("setup")
    s.add_argument("--work", required=True)
    s.add_argument("--room-cli", required=True)
    s.add_argument("--openwiz", required=True)
    s.add_argument("--server")
    s.add_argument("--threads", required=True)
    s.add_argument("--texts", default=os.path.join(TICKET, "texts.tsv"))
    s.add_argument("--plan", default=os.path.join(HERE, "plan.json"))
    s.add_argument("--port", type=int, default=7370,
                   help="the site's port (where the tunnel sends it): 0.0.2's now, X1's 0.0.3 during the swap")
    s.add_argument("--restore-cmd", help="the confirmed 0.0.2 launch, a JSON array (HANDOFF's command line)")
    s.add_argument("--restore-log", help="the 0.0.2 server's log, appended to on restore")
    s.add_argument("--restore-sha256", help="the 0.0.2 server binary's sha256")
    s.add_argument("--host", default="openwiz.invalid", help="the public host name (never committed)")
    s.add_argument("--web-root")
    s.add_argument("--access-url", help="where the unauthenticated L9 probe goes (default https://<host>)")
    s.add_argument("--expect-sha256")
    s.add_argument("--expect-server-sha256")
    s.add_argument("--checkout")
    s.add_argument("--expect-head")
    s.add_argument("--dry-run", action="store_true", help="the fake only: X1 presses for Jake")
    s.add_argument("--allowance", default="~/.openwiz-0.0.3-live-test-allowance",
                   help="L-8's allowance, kept for every sitting: always this one directory")
    s = sub.add_parser("map")
    s.add_argument("--work", required=True)
    s.add_argument("--show-titles", action="store_true", help="Jake's terminal only; never saved")
    s = sub.add_parser("recheck")
    s.add_argument("--work", required=True)
    s = sub.add_parser("run")
    s.add_argument("--work", required=True)
    s.add_argument("--groups", required=True)
    s.add_argument("--exclude-id", action="append")
    s.add_argument("--forbid", action="append")
    s.add_argument("--samples", type=int, default=6)
    s.add_argument("--settle", type=float, default=120)
    s.add_argument("--late", type=float, default=300)
    s.add_argument("--idle-timeout", type=float, default=600)
    s.add_argument("--busy-min", type=float, default=5)
    s.add_argument("--poll", type=float, default=2)
    s.add_argument("--press-timeout", type=float, default=900)
    s.add_argument("--warm-hours", type=float, default=48,
                   help="sessions updated this recently before the run are Jake's: reported, not judged")
    s.add_argument("--min-judged", type=int, default=20,
                   help="fewer cold sessions than this to judge stops the run before any send")
    s.add_argument("--answers", choices=("chat", "terminal"), default="chat",
                   help="how Jake's answers arrive: through the runner (files), or typed")
    s = sub.add_parser("swap")
    s.add_argument("--work", required=True)
    s.add_argument("action", choices=("start", "end", "stop-server", "kill-server", "start-server"))
    s.add_argument("--minutes", type=float, default=90, help="the swap's deadline: then 0.0.2 is restored")
    s = sub.add_parser("swap-supervise")
    s.add_argument("--work", required=True)
    s.add_argument("--minutes", type=float, required=True)
    s = sub.add_parser("swap-guard")
    s.add_argument("--work", required=True)
    s.add_argument("--minutes", type=float, required=True)
    s = sub.add_parser("parity")
    s.add_argument("--work", required=True)
    s = sub.add_parser("receipts")
    s.add_argument("--work", required=True)
    s.add_argument("--require", default="sent,queued:thread-busy",
                   help="the receipt kinds the run must have produced")
    s = sub.add_parser("l13")
    s.add_argument("--work", required=True)
    s.add_argument("--warm-hours", type=float, default=48)
    s.add_argument("--min-judged", type=int, default=20)
    s.add_argument("qc_args", nargs=argparse.REMAINDER, help="-- then quick-check.py run's arguments")
    a = p.parse_args(argv)
    try:
        if a.cmd == "swap-supervise":
            supervise(Kit(a.work), a.minutes)
            return 0
        if a.cmd == "swap-guard":
            guard(Kit(a.work), a.minutes)
            return 0
        if a.cmd == "run":
            kit = Kit(a.work)
            kit.args = a
            groups = a.groups.split(",")
            if not kit.dry and any(not g.startswith(("C", "W", "P")) for g in groups):
                raise Stop("unknown group")
            rep = run_groups(kit, groups)
        else:
            rep = {"texts": cmd_texts, "setup": cmd_setup, "map": cmd_map, "recheck": cmd_recheck,
                   "parity": cmd_parity, "swap": cmd_swap, "l13": cmd_l13,
                   "receipts": cmd_receipts}[a.cmd](a)
    except Stop as e:
        print(json.dumps({"stopped": str(e)}))
        return 10
    except KeyboardInterrupt:
        print(json.dumps({"stopped": "interrupted"}))
        return 130
    except Exception as e:  # its text could hold an id: the type only
        if os.environ.get("SEND_KIT_DEBUG"):
            raise
        print(json.dumps({"stopped": "unexpected error: %s" % type(e).__name__}))
        return 11
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 0 if rep.get("outcome") in ("as_expected", None) and a.cmd in ("texts", "setup") \
        or rep.get("outcome") == "as_expected" else 10


if __name__ == "__main__":
    sys.exit(main())
