#!/usr/bin/env python3
"""X1: the create and attachment brackets for OpenWiz 0.0.4's live check (#13, sheet L-1 to L-12).

Standard-library Python 3.9. It reuses 0.0.1's quick check (quick-check.py and
observe.py, imported from the repository, never copied) and 0.0.3's kit (PR #152 at
3a7b501: the send brackets, the judged set while Jake works, the guard-owned server
swap, the decoded-JSON privacy walk and the answer checks; copied here, because #152 is
not on main, with Sol's open findings R2, R6 and R11 fixed). It adds the 0.0.4 steps:
every create runs `openwiz new --yes` (or waits for Jake's press in the launcher) and
every attachment send `openwiz send --attach` (or Jake's tray), with X2 (x2-shim.py,
the call-counting shim) first on PATH, and checks the outcome, the calls X2 counted,
the record, the threads in P-A, what CloudRoom reports for each new thread, where each
text landed and what the agent reported about the attached files' bytes. It never says
"pass": each step is as_expected, not_as_expected or incomplete, and the first step
that is not as expected stops the run.

    new-kit.py texts    [--texts F]                       the approved texts: label, target, bytes, SHA-256
    new-kit.py files    --out DIR                         the 6 synthetic files (L-7), made and checked
    new-kit.py approval init|show|amend --approval A     L-8's allowance across every sitting (#168's R8)
    new-kit.py setup    --work W --approval A --room-cli P --openwiz P --targets F --files DIR [--server P] [--checks...]
    new-kit.py settings --work W [--set h=model/effort]... picks the settings and P-N from today's catalogue
    new-kit.py map      --work W [--show]                 the targets and settings, checked (--show: Jake's eyes)
    new-kit.py recheck  --work W                          spawn's and tell's help, structure only (lesson 6)
    new-kit.py run      --work W --groups C0,C1,...       the groups of plan.json, bracketed
    new-kit.py swap     --work W start|end|stop-server|kill-server|start-server
    new-kit.py parity   --work W                          S10, from the records (no call)
    new-kit.py receipts --work W                          S4, the structure of X2's captured receipts

Privacy: ids exist only in the targets file, X1's memory and the work directory (0700,
files 0600); the texts and files are synthetic and approved. Every report is structure
only and passes the decoded leak scan before it is printed. Exit 0: as expected. 10: a
stop. 11: a script error.
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
import struct
import subprocess
import sys
import threading
import time
import zlib

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


# The approved texts (L-7): synthetic "reply ok" prompts, by label and SHA-256 of their
# exact UTF-8 bytes. texts.tsv must match, line for line.
APPROVED = {
    "N1": "7a40480e34d9447267ab411073a63a6ab396007df9f1f9da659c10ed7198a789",
    "N2": "bc423f817d5dfa3ba234f8c371eeddd4fe217a45a398bfbe7ca3321e644337b3",
    "N3": "0527997bb623fc05ddc1e450e9d6102a0e4ae22e02f053f85c0548a876f2f7bf",
    "N4": "c94744058e4214548860d0527a5345d2aadebc886d2e622141db8530cf691a08",
    "N5": "a1fdca326dbf63cf8ea2584af60a6cbc8b549c26e0ba8a3206d1cdead40e0a0f",
    "N6": "7a9f7ae5224dca8b525f9ce51946da903720f3f5fb4bff8de0ab5e1bd52ba2ba",
    "R1": "908a46d298d9eb13f6beac972f626376e5938cf985ef1a47337ce95a2758415d",
    "R2": "59dbf83497f6ae3bab3b97266d6d3d11c95d6b6633f37dad113e82e61c109773",
    "R3": "4587cf72b5d0b4e92793cdbc66e9a180ab56538e1afb2b29afce97226a9d210c",
    "R4": "b99de8c06ec0df967a76a9a68c4154510c30bb85ad7e109fd6a580843fed8dfb",
    "R5": "d99348859ebc85c6a01626e96ab61ee16e52173c3b900e23d10dc595eee37b82",
    "R6": "9b1185ae25a12f0483c89879cecd9a728b6b23268923a83f06f589fb584e44c5",
    "A1": "de882816da9758ef4c69d7f313d549e1bc89b0d444b80570d9f5a64d8dc4ed4f",
    "A2": "d6ccd00ce81a00b6caad24d7adea6fa75a5df69e3ec106ed3a97c2ae81a635ef",
    "U1": "ebf35784ae0060d14fbb9105eea0a487896c424ae95489091c378fc6d29ba649",
}
TARGETS = ("P-A", "T-A", "T-B")
ENV_NAMES = {"PA": "P-A", "TA": "T-A", "TB": "T-B"}
HARNESSES = ("claude-code", "codex")
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}\Z")
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
MIB = 1024 * 1024
SHOWN = {"created": "created", "refused": "refused", "failed": "failed", "uncertain": "uncertain",
         "in_progress": "in progress", "conflicting_reuse": "conflicting reuse",
         "accepted": "sent", "queued": "queued"}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# The 6 synthetic files (L-7): made here, byte for byte the same on every machine,
# and checked against these SHA-256 values before anything uses them.


def _png(width, height, rgb, pad_to=None):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    head = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text = chunk(b"tEXt", b"Comment\x00Synthetic OpenWiz acceptance image")
    body = chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    if pad_to is None:
        return head + text + body
    n = pad_to - len(head + text + body) - 12 - len(b"Comment\x00")
    return head + text + chunk(b"tEXt", b"Comment\x00" + b"S" * n) + body


def _jpeg(pad_to):
    """A baseline JPEG, 8x8, one grey component: its one block is DC category 0, then
    EOB, with one-symbol Huffman tables. Comment segments pad it to exactly pad_to bytes,
    so every byte is part of the JPEG stream (it decodes in Chromium: README)."""
    soi = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    rest = (b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + b"\x01" * 64
            + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 8, 8, 1) + b"\x01\x11\x00"
            + b"\xff\xc4" + struct.pack(">H", 20) + b"\x00\x01" + b"\x00" * 15 + b"\x00"
            + b"\xff\xc4" + struct.pack(">H", 20) + b"\x10\x01" + b"\x00" * 15 + b"\x00"
            + b"\xff\xda" + struct.pack(">HB", 8, 1) + b"\x01\x00\x00\x3f\x00" + b"\x3f" + b"\xff\xd9")
    need, coms = pad_to - len(soi + app0 + rest), b""
    while need > 0:
        n = min(need, 65535 + 2)
        if need - n in (1, 2, 3):
            n -= 4
        coms += b"\xff\xfe" + struct.pack(">H", n - 2) + b"S" * (n - 4)
        need -= n
    return soi + app0 + coms + rest


def synthetic_files():
    return {
        "F1": ("syn-small.png", _png(16, 16, (40, 120, 200))),
        "F2": ("syn-10mib.jpg", _jpeg(10 * MIB)),
        "F3": ("syn-over.png", _png(16, 16, (200, 120, 40), pad_to=10 * MIB + 1)),
        "F4": ("syn-notes.txt", b"Synthetic OpenWiz acceptance file F4: plain text, attached as a file.\n"),
        "F5": ("syn-script.svg",
               b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
               b'<script>document.title = "Synthetic OpenWiz acceptance F5: this script must never run";</script>'
               b'<rect width="64" height="64" fill="#2878c8"/></svg>\n'),
        "F6": ("syn-photo.heic", struct.pack(">I", 24) + b"ftypheic" + struct.pack(">I", 0) + b"mif1heic"
               + b"Synthetic OpenWiz acceptance HEIC F6: refused, never converted.\n"),
    }


FILES = {  # label: (name, bytes, SHA-256): files.md
    "F1": ("syn-small.png", 133, "c43c8b8aeeb4288c7a38e12c1220121e473c7903af32771f28982fbf2a99feb0"),
    "F2": ("syn-10mib.jpg", 10 * MIB, "af884df93fc613d05ab87581a0a0026335b3cee7a48843d1e34f27e9fbfd4bb0"),
    "F3": ("syn-over.png", 10 * MIB + 1, "a0c7663ba3b22336f432ba11fd0d97dd682ae0967f4a2bd0a05a9151dfa9aa13"),
    "F4": ("syn-notes.txt", 70, "8273ca0844b7468654f3eb840aba94785f5d0e08f9c83332cac6820a8ba7b673"),
    "F5": ("syn-script.svg", 231, "ce02b7282df7a90c4fab3d58ae0e3f8671d703e15353a16e1bc86ea86ccb7c12"),
    "F6": ("syn-photo.heic", 88, "9ce42b1007ce613ff772b19d056edee0c3bf9cd3e89a393c6efbff9bdaa53e28"),
}


def check_files(d):
    """Every approved file in d, exactly: its name, size and SHA-256. Any difference stops."""
    for label, (name, size, digest) in FILES.items():
        p = os.path.join(d, name)
        if not os.path.isfile(p) or os.path.getsize(p) != size or observe.file_sha256(p) != digest:
            raise Stop("file %s is missing, or its size or SHA-256 differs" % label)


def file_path(kit, label):
    return os.path.join(kit.cfg["files"], FILES[label][0])


# --------------------------------------------------------------------------
# Texts, plan, targets


def load_texts(path):
    """The texts file, checked line by line against APPROVED. Any difference stops."""
    texts, where = {}, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                raise Stop("the texts file has a line that is not label, target, text")
            label, target, text = parts
            if label not in APPROVED or sha(text) != APPROVED[label] or label in texts:
                raise Stop("text %s is not approved, or its SHA-256 differs" % label)
            texts[label], where[label] = text, target
    if set(texts) != set(APPROVED):
        raise Stop("the texts file lacks an approved text")
    return texts, where


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
            for a in s.get("attach", []):
                if a not in FILES:
                    raise Stop("plan: a step attaches an unapproved file")
            if s.get("op", "new") != "new" and s["op"].split(":", 1)[1] not in seen:
                raise Stop("plan: a step reuses the op id of a later step")
    return plan


def read_targets(path):
    """PA=<project id>, TA=<thread id>, TB=<thread id>, written by Jake on the PC, 0600. Never printed."""
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise Stop("the targets file must be readable by its owner only (chmod 600)")
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip("'\"")
            if k.strip() not in ENV_NAMES or not ID_RE.match(v) or v.startswith("-") or ENV_NAMES[k.strip()] in out:
                raise Stop("the targets file has a line that is not PA, TA or TB = <id>")
            out[ENV_NAMES[k.strip()]] = v
    if set(out) != set(TARGETS) or len(set(out.values())) != 3:
        raise Stop("the targets file needs three different ids: PA, TA and TB")
    return out


# --------------------------------------------------------------------------
# The contracts, read as they are (Sol R6 on #152: the answers' required fields AND
# their types, nested, from the contracts themselves; never a hand-copied list).


# Which contract and definition each kind of answer must meet.
CONTRACT_OF = {
    "openwiz.new-thread.v1": ("new-thread", "report"),
    "openwiz.new-thread-preview.v1": ("new-thread", "preview"),
    "openwiz.new-thread-status.v1": ("new-thread", "status_read"),
    "openwiz.cloud-options.v1": ("new-thread", "options"),
    "openwiz.messaging.v1": ("messaging", "report"),
    "openwiz.attachment-add.v1": ("attachment", "add_report"),
    "openwiz.attachment-list.v1": ("attachment", "list_report"),
    "openwiz.attachment-remove.v1": ("attachment", "remove_report"),
    "openwiz.inventory.v1": ("inventory", None),
}


def contract_problem(kit, doc, want=None):
    """None if doc is one of OpenWiz's documents, of the schema wanted, and valid
    against its contract; else what is wrong (a rule, never a value)."""
    if not isinstance(doc, dict):
        return "not a JSON object"
    schema = doc.get("schema")
    if want is not None and schema != want:
        return "schema %s, expected %s" % ("absent" if schema is None else "other", want)
    if schema not in CONTRACT_OF:
        return "an unknown schema"
    p = kit.schemas.problems(doc, *CONTRACT_OF[schema])
    return ("breaks %s: %s" % (schema, "; ".join(p))) if p else None


# --------------------------------------------------------------------------
# The kit's work directory


# --------------------------------------------------------------------------
# The approval (#168's R8, Jake's (a)): L-8's allowance, across every sitting. Its file is
# kept outside every sitting's work directory, made once (`approval init`), named by every
# setup, and never remade. X2 charges each write there under the approval's own lock (inside
# its writes.lock); a charge is released only when zero calls are proven. A fresh setup
# inherits only what's left, and only Jake amending the approval raises the total.

L8 = {"spawn": 4, "tell": 2}  # L-3, L-5: at most 4 new threads and 2 attachment sends, in all
KINDS = (("spawn", "creates"), ("tell", "sends"))


def load_approval(path):
    try:
        ap = json.load(open(path))
        if (isinstance(ap, dict) and ap.get("schema") == "kit13.approval.v1" and isinstance(ap.get("total"), dict)
                and isinstance(ap.get("charges"), list) and all(isinstance(c, dict) for c in ap["charges"])
                and isinstance(ap.get("sittings"), list) and isinstance(ap.get("amendments"), list)):
            return ap
    except (OSError, ValueError, TypeError):
        pass
    raise Stop("the approval's file can't be read: nothing is set up or armed (it is never remade; ask Jake)")


def save_approval(path, ap):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    write_private(tmp, ap)
    os.replace(tmp, path)


@contextlib.contextmanager
def approval_locked(path):
    """The approval's own lock (X2 takes it inside its writes.lock, never the other way round)."""
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def charged(ap, kind=None, auth=None):
    """Every charge that counts: all but those released (zero calls proven), uncertain ones included."""
    return [c for c in ap["charges"] if c.get("state") != "released"
            and (kind is None or c.get("kind") == kind) and (auth is None or c.get("auth") == auth)]


def remaining(ap, kind):
    return max(0, int(ap["total"].get(kind, 0)) - len(charged(ap, kind)))


def approval_block(ap, sitting=None):
    """The cumulative totals and what's left: counts, step ids and sitting numbers only (never a
    path, an op id or Jake's words). `made` lists every charged write; a state other than
    `dispatched` is uncertain, and stays charged."""
    b = {"total": {n: int(ap["total"].get(k, 0)) for k, n in KINDS},
         "charged": {n: len(charged(ap, k)) for k, n in KINDS},
         "uncertain": {n: sum(1 for c in charged(ap, k) if c.get("state") != "dispatched") for k, n in KINDS},
         "remaining": {n: remaining(ap, k) for k, n in KINDS},
         "made": [{"step": str(c.get("auth")), "kind": c.get("kind"), "sitting": c.get("sitting"), "state": c.get("state")}
                  for c in charged(ap)],
         "sittings": len(ap["sittings"]), "amendments": len(ap["amendments"])}
    if sitting is not None:
        b["sitting"] = sitting
    return b


class Kit:
    def __init__(self, work):
        self.work = os.path.abspath(work)
        with open(os.path.join(self.work, "kit.json")) as f:
            self.cfg = json.load(f)
        self.x2 = os.path.join(self.work, "x2")
        self.state = os.path.join(self.work, "state")
        self.run = os.path.join(self.work, "run")
        self.texts, self.text_targets = load_texts(self.cfg["texts"])
        self.plan = load_plan(self.cfg["plan"], self.texts)
        self.targets = read_targets(self.cfg["targets"])
        check_files(self.cfg["files"])
        self.schemas = Schemas(self.cfg["contracts"])
        self.settings = self._load("settings.json", None)
        self.ctx = KitCtx(self.cfg["room_cli"], self.run)
        self.opids = self._load("opids.json", {})
        self.new = self._load("new.json", {})  # new thread id -> {"step", "msg"}
        self.dry = bool(self.cfg.get("dry_run"))
        self.forbidden = set()  # live strings no report may hold (memory only)
        self.args = None
        self.tag = secrets.token_hex(4)  # X2's step names (for counting) are this invocation's own
        self._lock_fd, self._lock_depth = None, 0

    @contextlib.contextmanager
    def locked(self):
        """X2's lock (`x2/writes.lock`), re-entrant within this process: X1 arms and disarms
        under it, and X2 admits a write only under it (#168's R2)."""
        if self._lock_depth == 0:
            self._lock_fd = open(os.path.join(self.x2, "writes.lock"), "a")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        self._lock_depth += 1
        try:
            yield
        finally:
            self._lock_depth -= 1
            if self._lock_depth == 0:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
                self._lock_fd = None

    def agent_reply(self):
        r = self.cfg.get("agent_reply")
        return (r[0], r[1]) if isinstance(r, list) and len(r) == 2 else None

    def approval(self):
        if not self.cfg.get("approval"):
            raise Stop("this sitting names no approval: nothing is armed")
        return load_approval(self.cfg["approval"])

    def ledger(self):
        try:
            led = json.load(open(os.path.join(self.x2, "ledger.json")))
            if isinstance(led, dict) and isinstance(led.get("auth"), dict) and isinstance(led.get("used"), dict):
                return led
        except (OSError, ValueError):
            pass
        raise Stop("X2's ledger can't be read; nothing is armed")

    def save_ledger(self, led):
        tmp = os.path.join(self.x2, "ledger.json.tmp.%d" % os.getpid())
        write_private(tmp, led)
        os.replace(tmp, os.path.join(self.x2, "ledger.json"))

    def _load(self, name, default):
        p = os.path.join(self.run, name)
        return json.load(open(p)) if os.path.exists(p) else default

    def save(self, name, data):
        write_private(os.path.join(self.run, name), data)

    def x2_targets(self):
        t = dict(self.targets)
        if self.settings and self.settings.get("p_n"):
            t["P-N"] = self.settings["p_n"]
        return t

    def arm(self, name, write=None, fault="capture", hold_s=0, ttl_s=300):
        """X2's step file, replaced in one rename, under X2's lock, with a new generation.
        write: the one write this step allows (kind, target, settings or mode, text hash,
        attachments, max_calls, and `auth`: the plan step's stable id). It is armed only if
        the sitting's ledger shows that step's write not yet made and the run's budget not
        used up (#168's R1): a re-entry stops here, and never re-arms. A step that allows a
        write expires after ttl_s, so one left armed by a crash lets nothing through."""
        with self.locked():
            led = self.ledger()
            if write and self.cfg.get("read_guard") is not True:
                raise Stop("setup did not prove the openwiz read through X2; no write can be armed")
            if write and led.get("tainted"):
                raise Stop("the sitting is tainted (X2 refused %d call(s)): X1 arms no write in a tainted sitting; "
                           "only a new setup clears it" % int(led.get("refusals", 0)))
            if write:
                kind, auth = write["kind"], write.get("auth")
                if not isinstance(auth, str):
                    raise Stop("a write without its plan step's authorisation; nothing is armed")
                if int((led["auth"].get(auth) or {}).get("calls", 0)) >= int(write.get("max_calls", 1)):
                    raise Stop("%s's write was already made in this sitting: the run stops (a re-entry never "
                               "re-arms)" % auth)
                ap = self.approval()  # #168's R8: every sitting under the approval
                made = charged(ap, auth=auth)
                if len(made) >= int(write.get("max_calls", 1)):
                    raise Stop("%s's write was already made under this approval (sitting %s): it is never repeated; "
                               "its evidence stays in that sitting's work directory" % (auth, made[0].get("sitting")))
                if int(led["used"].get(kind, 0)) >= int(led["budget"].get(kind, 0)):
                    raise Stop("the sitting's write budget (%d creates, %d sends) is used up: the run stops"
                               % (led["budget"].get("spawn", 0), led["budget"].get("tell", 0)))
                if not remaining(ap, kind):
                    raise Stop("the approval's allowance (%d creates, %d sends: L-8) is used up: the run stops; more "
                               "needs Jake to amend the approval" % (int(ap["total"].get("spawn", 0)),
                                                                      int(ap["total"].get("tell", 0))))
            led["generation"] = int(led.get("generation", 0)) + 1
            step = {"step": "%s@%s" % (name, self.tag), "real_room_cli": self.cfg["room_cli"],
                    "targets": self.x2_targets(), "fault": fault, "hold_s": hold_s, "allowed_write": None,
                    "generation": led["generation"]}
            if write:
                step["allowed_write"] = write
                step["expires_ms"] = now_ms() + int((ttl_s + hold_s) * 1000)
            for m in ("holding-before", "answered-holding"):
                if os.path.exists(os.path.join(self.x2, m)):
                    os.remove(os.path.join(self.x2, m))
            self.save_ledger(led)
            tmp = os.path.join(self.x2, "step.json.tmp")
            write_private(tmp, step)
            os.replace(tmp, os.path.join(self.x2, "step.json"))

    def disarm(self):
        self.arm("between-steps")

    def writes(self, name):
        """X2's counter for one step: attempts, calls made, refusals, aborts."""
        c = {"attempts": 0, "calls": 0, "refused": 0, "aborted": 0}
        path = os.path.join(self.x2, "writes.log")
        if os.path.exists(path):
            for line in open(path):
                e = json.loads(line)
                if e.get("step") != "%s@%s" % (name, self.tag):
                    continue
                o = e.get("outcome")
                c["attempts"] += o in ("called", "holding", "refused")
                c["calls"] += o in ("called", "called_after_hold")
                c["refused"] += o == "refused"
                c["aborted"] += str(o).startswith("aborted")
        return c

    def settled_writes(self, name, hold_s):
        """Waits until every call X2 held in this step has been called or aborted."""
        def done():
            path = os.path.join(self.x2, "writes.log")
            if not os.path.exists(path):
                return True
            held = ended = 0
            for line in open(path):
                e = json.loads(line)
                if e.get("step") == "%s@%s" % (name, self.tag):
                    held += e.get("outcome") == "holding"
                    ended += e.get("outcome") == "called_after_hold" or str(e.get("outcome")).startswith("aborted")
            return ended >= held
        if not wait_for(done, hold_s + 15):
            raise Stop("X2 never ended its hold (%s)" % name)

    def env(self):
        env = dict(os.environ)
        env["PATH"] = self.x2 + os.pathsep + env.get("PATH", "")
        env["OPENWIZ_STATE_DIR"] = self.state
        env.pop("ROOM_SERVER_URL", None)
        return env

    def path_guard(self, env):
        """room-cli on the command's PATH must be X2, or nothing is created or sent."""
        found = shutil.which("room-cli", path=env["PATH"])
        if not found or os.path.realpath(found) != os.path.realpath(os.path.join(self.x2, "room-cli")):
            raise Stop("room-cli on the write's PATH is not X2; nothing was created or sent")

    def setting(self, harness):
        if not self.settings or harness not in self.settings.get("pick", {}):
            raise Stop("no settings for %s: run settings first" % harness)
        p = self.settings["pick"][harness]
        return p["model"], p["effort"]

    def new_record(self, op=None, digest=None):
        """The new-thread record of an op id (or the newest for P-A and a text hash),
        summarised: its state, outcome kind and reason, the thread it names, whether the
        text is kept and matches, recovered; its keys' structure; the op id in memory only."""
        best = None
        d = os.path.join(self.state, "new-threads")
        for name in (os.listdir(d) if os.path.isdir(d) else []):
            if not name.endswith(".json"):
                continue
            try:
                r = json.load(open(os.path.join(d, name)))
            except ValueError:
                continue
            b = r.get("binding") or {}
            if op is not None and r.get("op_id") != op:
                continue
            if digest is not None and b.get("text_sha256") != digest:
                continue
            if (b.get("project") or {}).get("value") not in (self.targets["P-A"], (self.settings or {}).get("p_n")):
                continue
            if best is None or (r.get("claimed_at") or 0) >= (best.get("claimed_at") or 0):
                best = r
        if best is None:
            return None
        o = best.get("outcome") or {}
        text = best.get("text")
        return {"op": best.get("op_id"), "state": best.get("state"), "outcome": o.get("kind"),
                "reason": o.get("reason"), "thread": o.get("thread_id"), "text_kept": isinstance(text, str),
                "text_matches": isinstance(text, str) and sha(text) == (digest or (best.get("binding") or {}).get(
                    "text_sha256")), "recovered": bool(best.get("recovered") or o.get("recovered")),
                "keys": structure(best), "shape": shape(best)}

    def send_record(self, label, digest, op=None):
        best = None
        d = os.path.join(self.state, "sends")
        for name in (os.listdir(d) if os.path.isdir(d) else []):
            if not name.endswith(".json"):
                continue
            try:
                r = json.load(open(os.path.join(d, name)))
            except ValueError:
                continue
            b = r.get("binding") or {}
            if op is not None and r.get("op_id") != op:
                continue
            if b.get("target") != self.targets[label] or b.get("text_sha256") != digest:
                continue
            if best is None or (r.get("claimed_at") or 0) >= (best.get("claimed_at") or 0):
                best = r
        if best is None:
            return None
        dl = best.get("delivery") or {}
        return {"op": best.get("op_id"), "state": best.get("state"), "delivery": dl.get("kind"),
                "reason": dl.get("reason"), "keys": structure(best)}

    def staged(self):
        """The staged attachments' SHA-256s, from the store's own records (`.meta.json` in
        each attachment's directory; never their bytes, no room-cli call)."""
        out = []
        d = os.path.join(self.state, "attachments")
        for name in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
            p = os.path.join(d, name)
            if not os.path.isdir(p):
                continue
            try:
                out.append(json.load(open(os.path.join(p, ".meta.json")))[0]["sha256"])
            except (OSError, ValueError, LookupError, TypeError):
                out.append("unreadable")
        return out

    def leftovers(self):
        """What a staging left behind in the store: anything but its two locks and the
        complete attachments (a directory with its record and no `.partial` file)."""
        n = 0
        d = os.path.join(self.state, "attachments")
        for name in (os.listdir(d) if os.path.isdir(d) else []):
            p = os.path.join(d, name)
            if name in (".staging.lock", ".claims.lock"):
                continue
            if not os.path.isdir(p) or not os.path.isfile(os.path.join(p, ".meta.json")) \
                    or any(f.endswith(".partial") for f in os.listdir(p)):
                n += 1
        return n


class KitCtx(observe.Ctx):
    """0.0.1's observer context, plus the two help reads lesson 6 asks for before a live
    check (the standing approval's `<subcommand> --help`)."""

    def room(self, argv, env=None, wrap=None):
        a = list(argv)
        if a not in (["thread", "spawn", "--help"], ["thread", "tell", "--help"]):
            return super().room(argv, env, wrap)
        kind = " ".join(a)
        try:
            r = subprocess.run([self.room_cli] + a, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise Stop("observer read timed out: " + kind)
        with self.lock:
            self.reads[kind] = self.reads.get(kind, 0) + 1
        return r


def shape(v):
    """structure(), with every list folded to "array": two records of one kind compare
    equal whether or not their prompts carried attachments (S10)."""
    if isinstance(v, dict):
        return {k: shape(v[k]) for k in sorted(v)}
    return "array" if isinstance(v, list) else ("null" if v is None else type(v).__name__)


# --------------------------------------------------------------------------
# Observing the targets (L-9): counts per project, each new thread's thread show, and
# its oldest events (thread log --limit 100); T-A's and T-B's events in windows of 100.


def show_of(kit, sid):
    doc = kit.ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
    if not isinstance(doc, dict):
        return None
    t = doc.get("thread") if isinstance(doc.get("thread"), dict) else {}
    ex = doc.get("execution") if isinstance(doc.get("execution"), dict) else {}
    rt = t.get("runtime") if isinstance(t.get("runtime"), dict) else {}
    return {"project": t.get("projectId"), "provider": t.get("providerId"), "model": ex.get("model"),
            "effort": ex.get("reasoningLevel"), "status": t.get("status"), "display": rt.get("displayStatus"),
            "qmc": t.get("queuedMessageCount"), "local": isinstance((doc.get("environment") or {}).get("hostId"), str),
            "title": t.get("title")}


def idle(s):
    return s is not None and s["status"] == "idle" and s["display"] in (None, "idle") and s["qmc"] in (0, None)


def events_of(kit, sid, all_windows):
    """A thread's events, oldest first: the oldest 100 (a new thread, L-9), or every
    window of 100 (T-A and T-B)."""
    out, after = [], None
    for _ in range(100 if all_windows else 1):
        rows = observe.log_rows(kit.ctx, sid, after, observe.LOG_WINDOW)
        if rows is None:
            raise Stop("a target thread is gone")
        out.extend(r for r in rows if isinstance(r, dict))
        if len(rows) < observe.LOG_WINDOW or not all_windows:
            return out
        after = rows[-1].get("seq")
        if not isinstance(after, int):
            raise Stop("an event without a sequence number")
    raise Stop("too many events on a test thread")


def carrying(events, text):
    """Events carrying the text: exact (a string value equal to it) or wrapped (a string
    value containing it), counted per event type. In memory only."""
    exact, wrapped, per_type, keys, seqs = 0, [], {}, [], []
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
        seqs.append(e.get("seq"))
    return {"exact": exact, "wrapped": wrapped, "max_per_type": max(per_type.values()) if per_type else 0,
            "types": len(per_type), "data_keys": keys, "seqs": seqs}


def field_strings(v, path=""):
    """(field path, string) for every string value under v: `data.input`, `data.files[].sha256`."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k in sorted(v):
            yield from field_strings(v[k], "%s.%s" % (path, k) if path else str(k))
    elif isinstance(v, list):
        for x in v:
            yield from field_strings(x, path + "[]")


def agent_report(events, prompt, want, reply):
    """AL1, the agent's own report of the attached files' bytes, **recorded as just that**
    (sheet L-5; #168's R4, round 2): it decides no outcome. Recorded: where 64-hex strings
    appear after the prompt's own event (the one carrying the exact text): each event type
    and field path, with how many are the attached files' SHA-256 and how many others (never
    a value). The verdict is about the agent's reply only, and only when its shape is known:
    `reply` = (event type, field path), named at setup. Then: matches (every attached file's
    SHA-256 in that field of a reply after the prompt), differs (hashes there, not those),
    absent (no such reply or none there). Without a known shape, or with no prompt event,
    it is `unattributed`: whatever else carries a hash (upload, system or tool metadata)
    never stands in for the agent."""
    want = set(want)
    pe = next((e for e in events if isinstance(e.get("seq"), int) and any(v == prompt for v in
                                                                          strings(e.get("data", e)))), None)
    found = {}
    after = [e for e in events if pe is not None and isinstance(e.get("seq"), int) and e["seq"] > pe["seq"]]
    for e in after:
        for path, v in field_strings(e):
            hs = set(HEX64.findall(v.lower()))
            if hs:
                key = (e.get("type") if isinstance(e.get("type"), str) else "absent", path)
                f = found.setdefault(key, {"type": key[0], "field": path, "expected": 0, "other": 0})
                f["expected"] += len(hs & want)
                f["other"] += len(hs - want)
    rec = {"found": [found[k] for k in sorted(found)], "reply_shape": "named at setup" if reply else "not named"}
    if reply is None or pe is None:
        rec["verdict"] = "unattributed" if reply is None else "absent"
        return rec
    rtype, rfield = reply
    seen, replies = set(), 0
    for e in after:
        if e.get("type") != rtype:
            continue
        replies += 1
        for path, v in field_strings(e):
            if path == rfield:
                seen.update(HEX64.findall(v.lower()))
    rec["verdict"] = ("matches" if want and want <= seen else "differs" if seen else "absent")
    rec["replies"] = replies
    return rec


def pa_rows(snap, pa):
    return {sid for sid, r in snap["rows"].items() if r.get("project") == pa}


# --------------------------------------------------------------------------
# Running OpenWiz, and the processes the kit owns


def openwiz(kit, step, argv, procs=1, kill=None):
    """Runs `openwiz <argv>` (procs at once) with X2 first on PATH; kill: SIGKILL each
    once X2 reached its hold ("after-call": the answer held; "before-call")."""
    env = kit.env()
    kit.path_guard(env)
    ps = [subprocess.Popen([kit.cfg["openwiz"]] + argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE) for _ in range(procs)]
    if kill:
        name = "answered-holding" if kill == "after-call" else "holding-before"
        if not wait_for(lambda: marker(kit, name), 60):
            for p in ps:
                p.kill()
            raise Stop("X2 never reached its hold (%s)" % step["id"])
        for p in ps:
            p.send_signal(signal.SIGKILL)
    outs = []
    for i, p in enumerate(ps):
        try:
            out, err = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            raise Stop("openwiz did not finish in 180 s (%s)" % step["id"])
        write_private(os.path.join(kit.run, "out-%s-%d.json" % (step["id"], i)), out.decode("utf-8", "replace"))
        try:
            rep = json.loads(out) if out.strip() else None
        except ValueError:
            rep = None
        outs.append((p.returncode, rep, err.decode("utf-8", "replace")))
    return outs


def same_process(ident):
    """Whether the PID still names the very process recorded (start time and command
    line; a swap child's line may be the wrapper's or, after the go, the server's)."""
    if not ident:
        return False
    cur = identity(ident["pid"])
    after = ident.get("args_after_go")
    return cur is not None and cur["lstart"] == ident["lstart"] and (
        cur["args"] == ident["args"] or bool(after and (cur["args"] == after or cur["args"].endswith(" " + after))))


def stop_verified(ident, timeout=10):
    """SIGTERM, then SIGKILL, only while it is still the very process; True once it is
    gone (or was never there)."""
    if not same_process(ident):
        return True
    signal_if_same(ident, signal.SIGTERM)
    if wait_for(lambda: not same_process(ident), timeout, 0.1):
        return True
    signal_if_same(ident, signal.SIGKILL)
    return wait_for(lambda: not same_process(ident), 5, 0.1)


# --------------------------------------------------------------------------
# The swap (copied from #152, with R2 fixed): one supervisor owns X1's 0.0.4 server for
# the web part, and a guard restores Jake's confirmed launch if the supervisor dies or
# overruns. The confirmed launch is whatever server Jake runs at the time (0.0.3's or
# 0.0.2's), given at setup by its command line and binary sha256.


# #152's R2, round 3 (the orchestrator's design), copied from #152 at e7568d4: one owner. The GUARD is the parent of
# X1's server: it spawns the wrapper itself, so it always knows its own child (unreaped,
# so its PID and process group cannot be reused), stops it, confirms the exit with
# waitpid, and only then restores the confirmed launch. The supervisor never holds the child; it only
# asks the guard, over the guard's stdin pipe, to take over, stop, start or end. The
# guard acts on that pipe (its EOF means the supervisor is gone), never on swap.json,
# which is a status record only.
#
# The wrapper reads its own pipe from the guard: on "g" it starts the server as its
# child (in the wrapper's process group); on "t" or "k" (F4, F6) it signals the server,
# waits for it and exits; on EOF (the guard died) it does the same with SIGTERM. So the
# server can never outlive the guard.


# --------------------------------------------------------------------------
# The web page's requests, made by X1 exactly as apps/web makes them
# (contracts/web-api.v1.md), to the port the tunnel serves.

PAGE_HEADERS = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}  # apps/web's REQUEST_HEADERS


def request(kit, method, path, body=None, headers=None, host=None, timeout=45, holder=None, send_bytes=None):
    """(http status or None, parsed JSON or None). headers: changes to the page's own
    (a value None drops one). send_bytes: send only that many body bytes, then close."""
    host = host or kit.cfg["host"]
    h = {"Host": host}
    h.update(PAGE_HEADERS)
    if method != "GET":
        h.update({"Origin": "https://" + host, "Sec-Fetch-Site": "same-origin", "X-OpenWiz-Send": "1"})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if body is not None:
        h["Content-Length"] = str(len(body))
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    try:
        conn = http.client.HTTPConnection("127.0.0.1", kit.cfg["port"], timeout=timeout)
        if holder is not None:
            holder["conn"] = conn
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        if send_bytes is not None:
            conn.endheaders(body[:send_bytes])
            conn.sock.shutdown(socket.SHUT_RDWR)
            conn.close()
            return None, None
        conn.endheaders(body)
        r = conn.getresponse()
        status, raw = r.status, r.read()
        conn.close()
    except (OSError, http.client.HTTPException):
        return None, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def upload(kit, label, headers=None, send_bytes=None, holder=None):
    """The tray's upload of one approved file (XMLHttpRequest, raw bytes)."""
    name, _, _ = FILES[label]
    data = open(file_path(kit, label), "rb").read()
    h = {"Content-Type": "application/octet-stream", "X-OpenWiz-Name": name}
    h.update(headers or {})
    return request(kit, "POST", "/api/v1/attachments", data, h, send_bytes=send_bytes, holder=holder, timeout=120)


def web_op(kind="c"):
    """apps/web's op id for a draft's first attempt: `web-<32 hex>-c1` for a create
    (#12), `web-<32 hex>-q1` for a queued send (WS-7, #91)."""
    return "web-%s-%s1" % (secrets.token_hex(16), kind)


def threads_path(kit, project):
    return "/api/v1/projects/%s/threads" % project


# --------------------------------------------------------------------------
# Steps


def check(expect, got):
    """Every expectation the step names against what was seen; the differences."""
    bad = []
    for k, want in expect.items():
        if k in ("land", "exact", "exits", "shown", "p_a_new", "agent"):
            continue
        have = got.get(k)
        if isinstance(want, list) and not isinstance(have, list):  # one of these
            if have not in want:
                bad.append("%s %s, expected %s" % (k, have, "/".join(str(w) for w in want)))
        elif have != want:
            bad.append("%s %s, expected %s" % (k, have, want))
    if "exits" in expect:
        exits = got.get("exit_list", [])
        for code, (lo, hi) in expect["exits"].items():
            n = sum(1 for e in exits if str(e) == code)
            if not lo <= n <= hi:
                bad.append("%d runs exited %s, expected %d to %d" % (n, code, lo, hi))
        if sum(1 for e in exits if str(e) not in expect["exits"]):
            bad.append("a run exited otherwise")
    return bad


def report_fields(kit, rep):
    """What leaves the PC from one OpenWiz report: its outcome class and flags, never a value."""
    if not isinstance(rep, dict):
        return {"report": "none"}
    res = rep.get("result") if isinstance(rep.get("result"), dict) else {}
    o = res.get("outcome") if isinstance(res.get("outcome"), dict) else {}
    dl = res.get("delivery") if isinstance(res.get("delivery"), dict) else {}
    got = {"schema": rep.get("schema"), "status": rep.get("status"), "kind": res.get("kind"),
           "reason": o.get("reason") or dl.get("reason"), "replayed": res.get("replayed"),
           "recovered": res.get("recovered"), "differs": res.get("differs"), "delivery": dl.get("kind"),
           "contract": contract_problem(kit, rep) or "valid"}
    if rep.get("schema") == "openwiz.new-thread-status.v1" and res.get("kind") == "recorded":
        inner = res.get("report") if isinstance(res.get("report"), dict) else {}
        got["status"] = inner.get("status")
        obs = res.get("observations") if isinstance(res.get("observations"), dict) else None
        got["observed_threads"] = len(obs.get("threads") or []) if obs else None
    if isinstance(rep.get("verdict"), dict):
        got["verdict"] = rep["verdict"].get("kind")
    if isinstance(rep.get("state"), dict):
        got["state"] = rep["state"].get("kind")
    for k in ("ready", "failed"):
        if isinstance(rep.get(k), list):
            got[k] = len(rep[k])
    if isinstance(rep.get("failed"), list) and rep["failed"]:
        got["failed_reasons"] = sorted((f.get("readiness") or {}).get("reason") for f in rep["failed"])
    return got


def new_op(kit, step):
    if step.get("op", "new") == "new":
        op = "op-acc-%s-%s" % (step["id"].lower(), secrets.token_hex(8))
        kit.opids[step["id"]] = op
        kit.save("opids.json", kit.opids)
        return op
    return kit.opids[step["op"].split(":", 1)[1]]


def create_settings(kit, step):
    """(harness, model, effort) for a create step: the picked settings, or an unoffered
    combination, or another effort (a reuse that differs)."""
    if step.get("unoffered"):
        u = kit.settings.get("unoffered")
        if not u:
            raise Stop("no unoffered combination could be found in today's catalogue")
        return u["harness"], u["model"], u["effort"]
    harness = step["harness"]
    if harness == "images":
        harness = (kit.settings.get("images") or [None])[0]
        if harness is None:
            raise Stop("no harness takes images today (an allowed gap, L-12)")
    model, effort = kit.setting(harness)
    if step.get("other_effort"):
        effort = next(e for e in EFFORT_ORDER if e != effort)
    return harness, model, effort


def write_for(kit, step, kind, target, fields, text):
    """The one write X2 allows in a step: its settings or mode, text hash, attachments."""
    w = {"kind": kind, "target": target, "text_sha256": sha(text), "max_calls": 1, "attachments": [],
         "auth": step["id"]}
    w.update(fields)
    # room-cli gets the files first, then the images (#15, attachment_args).
    for kind_first in ("file", "image"):
        for a in step.get("attach", []):
            name, size, digest = FILES[a]
            is_image = name.endswith((".png", ".jpg"))
            if (kind_first == "image") == is_image:
                w["attachments"].append({"flag": "--image" if is_image else "--file", "sha256": digest, "size": size})
    return w


def do_cli(kit, step):
    """One openwiz command: models, a preview, a create, a status read, a send or a
    refusal. X2 allows the step's one write, or none."""
    exp = step["expect"]
    op = new_op(kit, step) if step["do"] in ("create", "preview", "send", "refuse-new", "refuse-send") else None
    text = kit.texts[step["msg"]] if "msg" in step else None
    attach = []
    for a in step.get("attach", []):
        attach += ["--attach", file_path(kit, a)]
    write = None
    if step["do"] == "models":
        argv = ["models", "--json"]
    elif step["do"] == "status":
        argv = ["new", "--status", kit.opids[step["of"]] if "of" in step else "op-acc-none-" + secrets.token_hex(8),
                "--json"]
    elif step["do"] in ("create", "preview", "refuse-new"):
        h, m, e = create_settings(kit, step)
        project = kit.settings["p_n"] if step.get("project") == "P-N" else kit.targets["P-A"]
        argv = ["new", "--project-id", project, "--harness", h, "--model", m, "--effort", e, "--op-id", op] + attach \
            + (["--yes"] if step["do"] != "preview" else []) + ["--json", "--", text]
        if exp.get("calls") or exp.get("attempts"):
            write = write_for(kit, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, text)
    else:  # send, refuse-send
        mode = step.get("mode", "queue")
        argv = ["send", kit.targets[step["target"]]] + (["--steer"] if mode == "steer" else []) + ["--op-id", op] \
            + attach + ["--json", "--", text]
        if exp.get("calls") or exp.get("attempts"):
            write = write_for(kit, step, "tell", step["target"], {"mode": mode}, text)
    if write:
        write["max_calls"] = step.get("max_calls", 1)
    kit.arm(step["id"], write, step.get("fault", "capture"), step.get("hold_s", 0), ttl_s=240)
    t0 = now_ms()
    outs = openwiz(kit, step, argv, step.get("procs", 1), step.get("kill"))
    kit.settled_writes(step["id"], step.get("hold_s", 0))
    kit.disarm()
    code, rep, err = outs[0]
    if step.get("procs", 1) > 1:  # the report of the run that made the call, if one did
        code, rep, err = next((o for o in outs if o[0] == 0 and (o[1] or {}).get("result", {}).get("replayed") is False),
                              outs[0])
    got = dict(report_fields(kit, rep), exit=code, exit_list=[c for c, _, _ in outs], ms=now_ms() - t0,
               stderr_line=bool(err.strip()))
    got["contracts"] = "valid" if all(r is None or contract_problem(kit, r) is None for _, r, _ in outs) else "broken"
    if rep is not None and text is not None and "text_sha256" in rep:
        got["text_sha_matches"] = rep.get("text_sha256") == sha(text)
    got.update(kit.writes(step["id"]))
    if step.get("attach"):  # AL7: no staged copy of these files is left (accepted, or never staged)
        digests = {FILES[a][2] for a in step["attach"]}
        got["staged_left"] = sum(1 for d in kit.staged() if d in digests)
    got["_report"] = rep
    got["_thread"] = (((rep or {}).get("result") or {}).get("outcome") or {}).get("thread_id")
    return got


def tray(kit, labels):
    """The tray: each file uploaded as the page uploads it, and ready with its approved
    SHA-256. (ids, None), or (None, what went wrong)."""
    ids = []
    for a in labels:
        st, rep = upload(kit, a)
        prob = contract_problem(kit, rep, "openwiz.attachment-add.v1")
        staged = ready_attachment(rep)
        if st != 200 or prob or staged is None or staged.get("sha256") != FILES[a][2]:
            return None, "the tray's upload of %s did not come back ready (%s)" % (a, prob or st)
        ids.append(staged["id"])
    return ids, None


def ready_attachment(rep):
    """The one staged attachment of an add report for one file, or None."""
    ready = (rep or {}).get("ready") if isinstance(rep, dict) else None
    if not isinstance(ready, list) or len(ready) != 1:
        return None
    a = ((ready[0] or {}).get("staged") or {}).get("attachment")
    return a if isinstance(a, dict) else None


def do_tray(kit, step):
    """The tray's checks, as the page makes them (W2): each file uploaded, its answer
    checked against its contract; ready or failed with the core's reason; every ready one
    removed again. Nothing reaches room-cli (X2 allows no write)."""
    kit.arm(step["id"])
    before = kit.staged()
    got = {"tray": {}}
    for a in step["tray"]:
        st, rep = upload(kit, a)
        prob = contract_problem(kit, rep, "openwiz.attachment-add.v1") if st == 200 else "status %s" % st
        staged = ready_attachment(rep)
        failed = (rep or {}).get("failed") or []
        if prob:
            got["tray"][a] = "broken: " + prob
        elif staged is not None:
            got["tray"][a] = "ready" if staged.get("sha256") == FILES[a][2] else "ready, other bytes"
            st_rm, rm = request(kit, "DELETE", "/api/v1/attachments/%s" % staged["id"])
            if st_rm != 200 or contract_problem(kit, rm, "openwiz.attachment-remove.v1"):
                got["removal"] = "failed"
        elif len(failed) == 1:
            got["tray"][a] = "failed:%s" % ((failed[0].get("readiness") or {}).get("reason"))
        else:
            got["tray"][a] = "neither ready nor failed"
    kit.disarm()
    got["staged_unchanged"] = kit.staged() == before
    got.update(kit.writes(step["id"]))
    return got


def web_body(kit, step, op, ids):
    """The launcher's create body, or the composer's send body (contracts/web-api.v1.md)."""
    text = kit.texts[step["msg"]]
    if step["do"] == "web-create":
        h, m, e = create_settings(kit, step)
        return threads_path(kit, kit.targets["P-A"]), {"op_id": op, "harness": h, "model": m, "effort": e,
                                                        "text": text, "attachments": ids}
    return "/api/v1/sessions/%s/messages" % kit.targets[step["target"]], {
        "op_id": op, "mode": step.get("mode", "queue"), "text": text, "resume_paused_queue": False,
        "accept_possible_duplicate": False, "attachments": ids}


def web_write(kit, step):
    """The one write X2 allows for a web step (one that expects a call, or an attempt
    that a fault stops before the call), or None."""
    if not (step["expect"].get("calls") or step["expect"].get("attempts")):
        return None
    text = kit.texts[step["msg"]]
    if step["do"] == "web-create":
        h, m, e = create_settings(kit, step)
        return write_for(kit, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, text)
    return write_for(kit, step, "tell", step["target"], {"mode": step.get("mode", "queue")}, text)


def do_web(kit, step):
    """One request of the web page's, made by X1 (the W groups): a create or a send, with
    the tray's uploads first; for the server-kill fault, the supervisor kills X1's server
    during X2's hold before the call."""
    kit.arm(step["id"], web_write(kit, step), step.get("fault", "capture"), step.get("hold_s", 0), ttl_s=120)
    ids, prob = tray(kit, step.get("attach", []))
    if prob:
        return {"incomplete": prob}
    op = new_op(kit, step)
    path, body = web_body(kit, step, op, ids)
    box = {}
    th = threading.Thread(target=lambda: box.__setitem__("r", request(kit, "POST", path, body)))
    th.start()
    if step.get("kill"):
        if not wait_for(lambda: marker(kit, "holding-before"), 30):
            th.join(60)
            return {"incomplete": "X2 never reached its hold"}
        swap_control(kit, "kill-server")
    th.join(60)
    kit.settled_writes(step["id"], step.get("hold_s", 0))
    kit.disarm()
    st, rep = box.get("r", (None, None))
    got = report_fields(kit, rep) if st == 200 else {"report": "none"}
    got["http"] = st
    got["shown"] = SHOWN.get((rep or {}).get("status"), "uncertain") if st == 200 else (
        "not sent" if st in (400, 403, 405, 411, 413, 415, 421) else "uncertain")
    got.update(kit.writes(step["id"]))
    got["_report"] = rep
    got["_thread"] = (((rep or {}).get("result") or {}).get("outcome") or {}).get("thread_id")
    for i in ids if step.get("remove_after") else []:
        st_rm, rm = request(kit, "DELETE", "/api/v1/attachments/%s" % i)
        if st_rm != 200 or contract_problem(kit, rm, "openwiz.attachment-remove.v1"):
            got["removal"] = "failed"
    return got


def do_replay(kit, step):
    """The same op id's request again, twice at once (a double press, a reload): a replay
    must make no call (X2 allows none), and both answers are checked (#152, Sol R10)."""
    of = step["of"]
    rec = kit.new_record(kit.opids.get(of))
    if rec is None:
        return {"incomplete": "no record of %s" % of}
    raw = json.load(open(os.path.join(kit.state, "new-threads", rec["op"] + ".json")))
    b = raw["binding"]
    req = raw.get("requested") or {}
    ids = [a.get("id") for a in (raw.get("attachments") or [])]
    body = {"op_id": rec["op"], "harness": req.get("harness"), "model": req.get("model"),
            "effort": req.get("effort"), "text": kit.texts[step["msg"]], "attachments": ids}
    if b.get("text_sha256") != sha(body["text"]):
        return {"incomplete": "the record is not this text's"}
    kit.arm(step["id"])
    box = {}
    ths = [threading.Thread(target=lambda i=i: box.__setitem__(i, request(kit, "POST", threads_path(
        kit, kit.targets["P-A"]), body))) for i in range(step.get("times", 2))]
    for t in ths:
        t.start()
    for t in ths:
        t.join(60)
    kit.disarm()
    answers = []
    for i in range(step.get("times", 2)):
        st, rep = box.get(i, (None, None))
        r = (rep or {}).get("result") or {}
        answers.append("replayed" if st == 200 and (rep or {}).get("status") == "created" and r.get("replayed") is True
                       and contract_problem(kit, rep) is None and (r.get("outcome") or {}).get("thread_id") ==
                       rec["thread"] else "in_progress" if st == 200 and (rep or {}).get("status") == "in_progress"
                       else "http %s" % st)
    got = {"answers": answers}
    got.update(kit.writes(step["id"]))
    return got


PROBES = (  # (name, route, header changes, expected status): L-10, the create's and the upload's checks
    ("create, loopback Host", "create", {"Host": "127.0.0.1:{port}", "Origin": "http://127.0.0.1:{port}"}, 421),
    ("create, no Origin", "create", {"Origin": None}, 403),
    ("create, foreign Origin", "create", {"Origin": "https://example.invalid"}, 403),
    ("create, cross-site fetch", "create", {"Sec-Fetch-Site": "cross-site"}, 403),
    ("create, no X-OpenWiz-Send", "create", {"X-OpenWiz-Send": None}, 403),
    ("create, form content type", "create", {"Content-Type": "application/x-www-form-urlencoded"}, 415),
    ("upload, loopback Host", "upload", {"Host": "127.0.0.1:{port}", "Origin": "http://127.0.0.1:{port}"}, 421),
    ("upload, no X-OpenWiz-Send", "upload", {"X-OpenWiz-Send": None}, 403),
    ("upload, multipart", "upload", {"Content-Type": "multipart/form-data; boundary=synthetic"}, 415),
)


OPENWIZ_CSP = "default-src 'none'; frame-ancestors 'none'"  # every OpenWiz API answer carries it


def create_lines(kit):
    """How many creates X1's own server has logged (its log names the route, never a value)."""
    path = os.path.join(kit.run, "server.log")
    return sum(1 for line in (open(path, errors="replace") if os.path.exists(path) else [])
               if " POST /api/v1/projects/{id}/threads " in line)


def public_probe(kit, body):
    """L-10, S9 (#168's R7): an unauthenticated create through the public hostname, shaped
    exactly as the launcher's (every header it sends, same-origin), with no login and no
    cookie, while X2 allows no write. Access must answer it at the edge (302, 401 or 403)
    and it must never reach the app: an answer with OpenWiz's own headers or error body, or
    a create in X1's server's log, means it did. (status, reached the app)."""
    import ssl
    import urllib.parse
    host = kit.cfg["host"]
    data = json.dumps(body).encode()
    url = urllib.parse.urlsplit(kit.cfg.get("access_url") or "https://" + host)
    h = {"Host": host, "Origin": "https://" + host, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json",
         "X-OpenWiz-Send": "1", "Content-Length": str(len(data))}
    h.update(PAGE_HEADERS)
    n0 = create_lines(kit)
    try:
        if url.scheme == "https":
            conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=20,
                                               context=ssl.create_default_context())
        else:  # tests only: a stand-in for Access (or none) on loopback
            conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=20)
        conn.putrequest("POST", threads_path(kit, kit.targets["P-A"]), skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        conn.endheaders(data)
        r = conn.getresponse()
        status, csp, raw = r.status, r.getheader("Content-Security-Policy"), r.read()
        conn.close()
    except (OSError, http.client.HTTPException):
        return None, False
    try:
        doc = json.loads(raw)
    except ValueError:
        doc = None
    time.sleep(1)  # the server logs a request after it answers
    app = csp == OPENWIZ_CSP or (isinstance(doc, dict) and isinstance(doc.get("error"), dict)) \
        or (isinstance(doc, dict) and "schema" in doc) or create_lines(kit) > n0
    return status, app


def do_probe(kit, step):
    """L-10 and S9: requests that must create, send and stage nothing. X2 allows no
    write, so even one that got through would be refused, and counted."""
    text = kit.texts[step["msg"]]
    h, m, e = create_settings(kit, dict(step, harness="codex"))
    kit.arm(step["id"])
    before = kit.staged()
    results, port = {}, kit.cfg["port"]
    for name, route, change, want in PROBES:
        hd = {k: (v.format(port=port) if isinstance(v, str) else v) for k, v in change.items()}
        if route == "create":
            body = {"op_id": "op-acc-r6-" + secrets.token_hex(8), "harness": h, "model": m, "effort": e,
                    "text": text, "attachments": []}
            st = request(kit, "POST", threads_path(kit, kit.targets["P-A"]), body, headers=hd,
                         host=hd.get("Host"))[0]
        else:
            st = upload(kit, "F1", headers=hd)[0]
        results[name] = {"status": st, "expected": [want]}
    body = {"op_id": "op-acc-r6-" + secrets.token_hex(8), "harness": h, "model": m, "effort": e, "text": text,
            "attachments": []}
    if kit.dry and not kit.cfg.get("access_url"):
        results["public, no login"] = {"status": "not made (dry run)", "expected": ["not made (dry run)"]}
    else:
        st, app = public_probe(kit, body)
        results["public, no login"] = {"status": st, "expected": [302, 401, 403]}
        results["public, reached the app"] = {"status": app, "expected": [False]}
    time.sleep(1)
    kit.disarm()
    got = {"probes": {k: v["status"] for k, v in results.items()},
           "probes_as_expected": all(v["status"] in v["expected"] for v in results.values()),
           "staged_unchanged": kit.staged() == before}
    got.update(kit.writes(step["id"]))
    return got


def do_cut_upload(kit, step):
    """The network cut mid-upload, at the server: half of a 10 MiB upload, then the
    connection goes. Nothing may be staged, and nothing is left half-written."""
    kit.arm(step["id"])
    before = kit.staged()
    size = FILES["F2"][1]
    upload(kit, "F2", send_bytes=size // 2)
    time.sleep(step.get("wait_s", 3))
    st, rep = request(kit, "GET", "/api/v1/attachments")
    kit.disarm()
    got = {"http": st, "list_contract": contract_problem(kit, rep, "openwiz.attachment-list.v1") or "valid",
           "staged_unchanged": kit.staged() == before, "left_over": kit.leftovers()}
    got.update(kit.writes(step["id"]))
    return got


def do_routes(kit, step):
    """The read routes the launcher and the tray poll, each answer checked against its
    contract (types and nesting, Sol R6) and its target; X2 allows no write."""
    kit.arm(step["id"])
    h, m, e = create_settings(kit, dict(step, harness="codex"))
    n1 = kit.opids.get("C2-N1")
    reads = [("cloud options", "GET", "/api/v1/cloud-options", None, "openwiz.cloud-options.v1"),
             ("attachments", "GET", "/api/v1/attachments", None, "openwiz.attachment-list.v1"),
             ("inventory", "GET", "/api/v1/inventory", None, "openwiz.inventory.v1"),
             ("preview", "POST", threads_path(kit, kit.targets["P-A"]) + "/preview",
              {"op_id": web_op(), "harness": h, "model": m, "effort": e, "text": kit.texts["N3"], "attachments": []},
              "openwiz.new-thread-preview.v1")]
    if n1:
        reads.append(("status of N-1", "GET", "/api/v1/new-threads/%s" % n1, None, "openwiz.new-thread-status.v1"))
    answers = {}
    for name, method, path, body, schema in reads:
        st, doc = request(kit, method, path, body)
        prob = ("status %s" % st) if st != 200 else contract_problem(kit, doc, schema)
        if prob is None and name == "status of N-1":
            o = ((((doc.get("result") or {}).get("report") or {}).get("result") or {}).get("outcome") or {})
            prob = None if o.get("thread_id") in kit.new else "another thread"
        if prob is None and name == "preview":
            prob = None if (doc.get("project") or {}).get("id") == kit.targets["P-A"] else "another project"
        if prob is None and name == "inventory":
            ids = [r.get("id") for r in ((doc.get("data") or {}).get("sessions") or [])]
            prob = None if kit.targets["T-A"] in ids or kit.targets["T-B"] in ids else "no test thread listed"
        answers[name] = prob or "valid"
    kit.disarm()
    got = {"answers": answers, "all_valid": all(v == "valid" for v in answers.values())}
    got.update(kit.writes(step["id"]))
    return got


def do_quiet(kit, step):
    """No OpenWiz write: wait (and, after the server kill, start it again) while X2
    allows no write. Anything that dispatches by itself is counted."""
    kit.arm(step["id"])
    if step.get("server") == "start":
        swap_control(kit, "start-server")
    a = kit.args
    time.sleep({"settle": a.settle, "settle+late": a.settle + a.late}[step["wait"]])
    got = kit.writes(step["id"])
    kit.disarm()
    return got


def do_web_status(kit, step):
    """The launcher's status read of an earlier op id (no call), then the same body again."""
    kit.arm(step["id"])
    op = kit.opids[step["of"]]
    st, doc = request(kit, "GET", "/api/v1/new-threads/%s" % op)
    rep = ((doc or {}).get("result") or {}).get("report") or {}
    got = {"http": st, "contract": contract_problem(kit, doc, "openwiz.new-thread-status.v1") or "valid",
           "status": rep.get("status"), "recovered": (rep.get("result") or {}).get("recovered")}
    kit.disarm()
    got.update(kit.writes(step["id"]))
    return got


def say(text):
    sys.stderr.write("\n>>> " + text + "\n")
    sys.stderr.flush()


def ask(kit, step_id, question, choices):
    """Jake's answer. `--answers chat` (the default): Jake answers the runner in chat, and
    the runner writes it to <run>/answer-<step>.txt. `--answers terminal`: typed."""
    if kit.args.answers == "terminal":
        while True:
            sys.stderr.write(">>> %s (%s) " % (question, ", ".join(choices)))
            sys.stderr.flush()
            a = sys.stdin.readline().strip().lower()
            if a in choices:
                return a
    path = os.path.join(kit.run, "answer-%s.txt" % step_id)
    say("ANSWER %s: %s (%s). Jake answers the runner, which writes it to answer-%s.txt"
        % (step_id, question, ", ".join(choices), step_id))
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


def jake_press(kit, step):
    """What Jake's hands do in one J step, as the page's requests (never X2's arming): in
    a dry run X1 makes them itself; in the kit's live-path test, jake-sim.py calls this."""
    if step["do"] in ("web-create", "web-send"):
        ids, prob = tray(kit, step.get("attach", []))
        if prob is None:
            path, body = web_body(kit, step, web_op("c" if step["do"] == "web-create" else "q"), ids)
            request(kit, "POST", path, body)
        return
    for a in step.get("tray", []):  # the tray's refusals and the SVG: uploads, then removals
        staged = ready_attachment(upload(kit, a)[1])
        if staged is not None:
            request(kit, "DELETE", "/api/v1/attachments/%s" % staged["id"])
    if step.get("cut"):  # the phone's network cut mid-upload
        upload(kit, "F2", send_bytes=FILES["F2"][1] // 3)
    if step.get("reads"):
        request(kit, "GET", "/api/v1/cloud-options")


def do_hand(kit, step):
    """One of Jake's hands-on steps (J groups): X1 arms X2 for the one write the step
    allows (or none), tells Jake what to do, waits for the write (or for his answer),
    then checks the record, the calls and what he says the page showed."""
    text = kit.texts.get(step.get("msg"))
    write = web_write(kit, step) if step["do"] in ("web-create", "web-send") else None
    kit.arm(step["id"], write, ttl_s=kit.args.press_timeout + 60)
    before = kit.staged()
    settings_line = ""
    if step["do"] == "web-create":
        h, m, e = create_settings(kit, step)
        settings_line = " Pick harness %s, model %s, effort %s." % (h, m, e)  # Jake's own screen only
    say("PRESS %s: %s%s%s" % (step["id"], step["say"], settings_line,
                              (" The text, exactly:\n    " + text) if text else ""))
    if kit.dry:
        jake_press(kit, step)
    got = {}
    if write:
        if not wait_for(lambda: kit.writes(step["id"])["attempts"] > 0, kit.args.press_timeout, 0.5):
            kit.disarm()
            return {"incomplete": "no call reached X2 within %d s" % kit.args.press_timeout}
        if step["do"] == "web-create":
            wait_for(lambda: (lambda r: r is not None and r["state"] == "finished")(kit.new_record(digest=sha(text))),
                     min(60, kit.args.press_timeout), 0.5)
            rec = kit.new_record(digest=sha(text))
            if rec:
                kit.opids[step["id"]] = rec["op"]
                kit.save("opids.json", kit.opids)
                got.update(record=rec["state"], outcome=rec["outcome"], _thread=rec["thread"])
        else:
            wait_for(lambda: (lambda r: r is not None and r["state"] == "finished")(
                kit.send_record(step["target"], sha(text))), min(60, kit.args.press_timeout), 0.5)
            rec = kit.send_record(step["target"], sha(text))
            if rec:
                kit.opids[step["id"]] = rec["op"]
                kit.save("opids.json", kit.opids)
                got.update(record=rec["state"], delivery=rec["delivery"])
    for q in step.get("ask", []):
        got["said_" + q["key"]] = ask(kit, step["id"] + "-" + q["key"], q["q"], q["choices"])
    time.sleep(1)
    kit.settled_writes(step["id"], 0)
    kit.disarm()
    got["staged_left"] = len([s for s in kit.staged() if s not in before])
    got.update(kit.writes(step["id"]))
    return got


# --------------------------------------------------------------------------
# Groups and the bracket (from #152)


def judged_set(snap, not_judged, warm_hours, start_ms, project):
    """The sessions the bracket judges while Jake and the factory keep working: the test
    project's (P-A's) sessions that were quiet at the run's start AND not updated in the
    `warm_hours` before it (cold). Every session outside the test's own threads and P-A
    (Jake's, the factory's), sessions that appear later, the test's own threads and the
    excluded ids are reported, never judged (Jake, #13, 2026-11-05: concurrent factory
    activity is reported outside the test targets; private record:
    https://github.com/jparker2006/ClosedWiz/issues/13#issuecomment-6650598367).
    A change in a judged session stops the run."""
    cut = start_ms - int(warm_hours * 3600 * 1000)
    out = set()
    for sid, row in snap["rows"].items():
        up = row.get("updatedAt")
        if (sid not in not_judged and row.get("project") == project and qc.classify(row) == "quiet"
                and isinstance(up, int) and not isinstance(up, bool) and up < cut):
            out.add(sid)
    return out


def carry_from(ap, work):
    """A sitting starts from what recorded sittings under the same approval made
    (#13, 2026-11-05: a fresh sitting's landing check otherwise found their texts on the
    targets and stopped). Merged into this sitting's run directory: every earlier sitting's
    landing expectations and new threads, and P-A's threads at the first sitting's start.
    A run refreshes these records, including its own completed steps, before judging.
    A sitting that charged a write but whose records can't be read stops the setup: what it
    made would be forgotten. None if there is no earlier sitting."""
    earlier = [s for s in ap.get("sittings", []) if isinstance(s, dict) and isinstance(s.get("work"), str)]
    if not earlier:
        return None
    made = {c.get("sitting") for c in charged(ap)}
    land = {"expected": {}, "exact": [], "creates": 0, "reports": {}}
    new, pa_start, froms = {}, None, []
    for s in sorted(earlier, key=lambda x: x.get("n", 0)):
        run = os.path.join(s["work"], "run")
        try:
            st = json.load(open(os.path.join(run, "landing.json"))) if os.path.exists(os.path.join(run, "landing.json")) else None
            nw = json.load(open(os.path.join(run, "new.json"))) if os.path.exists(os.path.join(run, "new.json")) else {}
            si = json.load(open(os.path.join(run, "sitting.json"))) if os.path.exists(os.path.join(run, "sitting.json")) else None
        except (OSError, ValueError):
            raise Stop("sitting %s's records can't be read: what it made would be forgotten; nothing was set up" % s.get("n"))
        if st is None:
            if s.get("n") in made:
                raise Stop("sitting %s charged a write but has no landing record; nothing was set up" % s.get("n"))
            continue
        for k, v in st.get("expected", {}).items():
            # Each labelled write is unique under this approval. Later sittings
            # include earlier expectations, so merge their counts rather than add them.
            land["expected"][k] = max(land["expected"].get(k, 0), int(v))
        land["exact"] += [m for m in st.get("exact", []) if m not in land["exact"]]
        land["reports"].update(st.get("reports", {}))
        new.update(nw)
        if pa_start is None and si is not None:
            pa_start = si.get("pa_start")
        froms.append(s.get("n"))
    if not froms:
        return None
    land["creates"] = sum(v for k, v in land["expected"].items() if k.startswith("P-A|"))
    run = os.path.join(work, "run")
    write_private(os.path.join(run, "landing.json"), land)
    write_private(os.path.join(run, "new.json"), new)
    write_private(os.path.join(run, "carried.json"), {"from": froms, "pa_start": sorted(pa_start or [])})
    return {"from": froms, "creates": land["creates"]}


def own_threads(kit):
    return set(kit.targets[l] for l in ("T-A", "T-B")) | set(kit.new)


def settle(kit):
    """T-A, T-B and every new thread idle with no queued message, and at least `settle` s."""
    a = kit.args
    t0 = time.monotonic()
    ok = wait_for(lambda: all(idle(show_of(kit, s)) for s in sorted(own_threads(kit))), a.idle_timeout, a.poll)
    rest = a.settle - (time.monotonic() - t0)
    if rest > 0:
        time.sleep(rest)
    return ok


def expect_landing(kit, steps):
    """Adds the steps that ran to the cumulative expectations (run/landing.json): each
    text, on T-A, T-B, or P-A (the first prompt of one new thread there)."""
    st = kit._load("landing.json", {"expected": {}, "exact": [], "creates": 0, "reports": {}})
    for s in steps:
        land = s.get("expect", {}).get("land")
        if land is None or "msg" not in s:
            continue
        key = "%s|%s" % (s.get("target", "P-A"), s["msg"])
        n = s.get("_landed", land)
        if s["expect"].get("calls") and s.get("_calls") == 0:
            n = 0  # its write never happened (X2 refused it, or no press came): nothing can land
        st["expected"][key] = st["expected"].get(key, 0) + n
        if s["expect"].get("exact") and s["msg"] not in st["exact"]:
            st["exact"].append(s["msg"])
        if s.get("target", "P-A") == "P-A":
            st["creates"] += n
        if s["expect"].get("agent") and n:
            st["reports"][key] = [FILES[a][2] for a in s.get("attach", [])]
    kit.save("landing.json", st)


def landing_all(kit, snap):
    """#152's R5, extended to the new threads: every approved text, on T-A and T-B (from
    each thread's first event) and on every thread in P-A that wasn't there at the start
    (its oldest 100 events), against what every completed step so far expects. A text
    lands on its own target exactly as often as expected, never elsewhere, never twice
    in one event type; the dash and path texts exactly; no attachment key on a text the
    step sent without one; P-A gains exactly one thread per create, each made by a step
    and carrying exactly one create's text. The agent's reports (AL1) are recorded."""
    st = kit._load("landing.json", {"expected": {}, "exact": [], "creates": 0, "reports": {}})
    pa = kit.targets["P-A"]
    start = set((kit._load("sitting.json", None) or {}).get("pa_start", []))
    new_pa = sorted(pa_rows(snap, pa) - start)
    events = {l: events_of(kit, kit.targets[l], True) for l in ("T-A", "T-B")}
    for sid in new_pa:
        events[sid] = events_of(kit, sid, False)
    out, bad, reports = {"checked": [], "verdict": "as_expected", "new_in_pa": len(new_pa),
                         "creates_expected": st["creates"]}, [], {}
    unknown = [s for s in new_pa if s not in kit.new]
    if unknown:
        bad.append("%d thread(s) in P-A that no step made" % len(unknown))
    if len(new_pa) != st["creates"]:
        bad.append("P-A gained %d threads, expected %d" % (len(new_pa), st["creates"]))
    per_thread = {}
    for m in sorted(APPROVED):
        text = kit.texts[m]
        for where, evs in events.items():
            c = carrying(evs, text)
            label = where if where in ("T-A", "T-B") else "P-A"
            want = st["expected"].get("%s|%s" % (label, m), 0)
            n = c["exact"] + len(c["wrapped"])
            if n and label == "P-A":
                per_thread.setdefault(where, []).append(m)
            if label != "P-A" and (want or n):
                out["checked"].append({"msg": m, "target": label, "expected": want, "carrying": n,
                                       "max_per_event_type": c["max_per_type"], "exact": c["exact"],
                                       "wrapped": c["wrapped"]})
                if c["max_per_type"] != want:
                    bad.append("%s on %s: %d, expected %d" % (m, label, c["max_per_type"], want))
            if label == "P-A" and c["max_per_type"] > 1:
                bad.append("%s twice in one new thread" % m)
            if n and m in st["exact"] and c["wrapped"]:
                bad.append("%s arrived wrapped (S11: Jake decides)" % m)
            keyed = [k for keys in c["data_keys"] for k in keys if k in ("files", "attachments", "images")]
            if n and keyed and ("%s|%s" % (label, m)) not in st["reports"]:
                bad.append("%s's event has an attachment key, and was sent without one" % m)
            key = "%s|%s" % (label, m)
            if n and key in st["reports"]:
                reports[key] = agent_report(evs, text, st["reports"][key], kit.agent_reply())
    for m in sorted(APPROVED):  # each create's text: the first prompt of exactly as many new threads as expected
        want = st["expected"].get("P-A|%s" % m, 0)
        have = sum(1 for msgs in per_thread.values() if m in msgs)
        if want or have:
            out["checked"].append({"msg": m, "target": "P-A", "expected": want, "threads": have})
        if have != want:
            bad.append("%s in %d new threads in P-A, expected %d" % (m, have, want))
    for sid, msgs in per_thread.items():
        if len(msgs) != 1:
            bad.append("a new thread in P-A carries %d approved texts" % len(msgs))
    for sid in new_pa:
        if sid in kit.new and sid not in per_thread and st["creates"]:
            bad.append("a new thread in P-A carries no approved text (yet)")
    out["agent_reports"] = dict(sorted(reports.items()))
    for key in st["reports"]:
        if key not in reports and st["expected"].get(key):
            out["agent_reports"][key] = {"found": [], "verdict": "absent" if kit.agent_reply() else "unattributed"}
    if bad:
        out["verdict"] = "not_as_expected: " + "; ".join(bad)
    return out


def thread_checks(kit, step, tid, harness_model_effort):
    """S2 and S5 for one new thread: CloudRoom's own view of it (thread show) against the
    request, and its start stages until it is idle (labels and seconds only)."""
    h, m, e = harness_model_effort
    if not wait_for(lambda: show_of(kit, tid) is not None, 30, 1):
        return {"incomplete": "the new thread can't be read"}
    s = show_of(kit, tid)
    got = {"in_p_a": s["project"] == kit.targets["P-A"], "provider_as_requested": s["provider"] == h,
           "model_as_requested": s["model"] == m, "effort_as_requested": s["effort"] == e, "cloud": not s["local"]}
    series, t0 = [], time.monotonic()
    while time.monotonic() - t0 < kit.args.idle_timeout:
        s = show_of(kit, tid)
        if s is not None and (not series or series[-1][0] != s["status"]):
            series.append([s["status"], int(time.monotonic() - t0)])
        if idle(s):
            break
        time.sleep(max(kit.args.poll, 1))
    got["stages"] = series
    got["started"] = bool(series) and series[-1][0] == "idle"
    return got


def run_step(kit, step):
    t0 = now_ms()
    do = step["do"]
    srep = {"step": step["id"], "do": do}
    try:
        if step.get("msg") and sha(kit.texts[step["msg"]]) != APPROVED[step["msg"]]:
            raise Stop("a text's hash changed")
        if do == "hand" or step.get("by") == "jake":
            got = do_hand(kit, step)
        elif do in ("models", "status", "create", "preview", "refuse-new", "send", "refuse-send"):
            got = do_cli(kit, step)
        elif do in ("web-create", "web-send"):
            got = do_web(kit, step)
        elif do == "replay":
            got = do_replay(kit, step)
        elif do == "probe":
            got = do_probe(kit, step)
        elif do == "tray":
            got = do_tray(kit, step)
        elif do == "cut-upload":
            got = do_cut_upload(kit, step)
        elif do == "routes":
            got = do_routes(kit, step)
        elif do == "quiet":
            got = do_quiet(kit, step)
        elif do == "web-status":
            got = do_web_status(kit, step)
        else:
            raise Stop("unknown step kind")
        if "incomplete" not in got and got.get("_thread") and step.get("op", "new") != "new":
            # A rerun or a repeat of an earlier op id: it must name that create's own thread.
            of = step["op"].split(":", 1)[1]
            got["same_thread"] = kit.new.get(got["_thread"], {}).get("step") == of
        elif "incomplete" not in got and got.get("_thread") and step["do"] in ("create", "web-create"):
            tid = got["_thread"]
            if tid in kit.new:
                got["thread_is_new"] = False
            else:
                kit.new[tid] = {"step": step["id"], "msg": step["msg"]}
                kit.save("new.json", kit.new)
                got["thread_is_new"] = True
                got.update(thread_checks(kit, step, tid, create_settings(kit, step)))
        if "incomplete" not in got and step.get("expect", {}).get("p_a_new") is not None:
            # A create whose outcome stays uncertain (the CLI killed mid-create): the
            # threads P-A gained, by CloudRoom's own list; 0 or 1, never 2 (S6).
            snap = {"rows": {r["id"]: observe.list_fields(r) for r in kit.ctx.room_json(
                ["thread", "list", "--json", "--include-hidden", "--include-archived"]) if isinstance(r, dict)
                and isinstance(r.get("id"), str)}}
            seen = sorted(pa_rows(snap, kit.targets["P-A"]) - set(kit._load("sitting.json", {}).get("pa_start", []))
                          - set(kit.new))
            got["p_a_new"] = len(seen)
            for tid in seen:
                kit.new[tid] = {"step": step["id"], "msg": step["msg"]}
            kit.save("new.json", kit.new)
            step["_landed"] = len(seen)
            if seen:
                got.update(thread_checks(kit, step, seen[0], create_settings(kit, step)))
    except Stop as e:
        srep["verdict"] = "incomplete: " + str(e)
        step["_calls"] = kit.writes(step["id"])["calls"]
        return srep
    finally:
        kit.disarm()  # #152, Sol R2: no step ever ends with a write armed
    step["_calls"] = got.get("calls", 0)
    if "incomplete" in got:
        srep["verdict"] = "incomplete: " + got.pop("incomplete")
        return srep
    exp = dict(step["expect"])
    bad = check(exp, got)
    if "p_a_new" in exp and got.get("p_a_new") not in exp["p_a_new"]:
        bad.append("P-A gained %s threads, expected one of %s" % (got.get("p_a_new"), exp["p_a_new"]))
    if "shown" in exp and got.get("shown") not in exp["shown"]:
        bad.append("the page showed %s, expected %s" % (got.get("shown"), "/".join(exp["shown"])))
    if do == "probe" and not got.get("probes_as_expected"):
        bad.append("a probe answered other than expected")
    if do == "routes" and not got.get("all_valid"):
        bad.append("a read route answered against its contract or for another target")
    if got.get("removal") == "failed":
        bad.append("the tray's removal of a ready file failed")
    if do == "replay" and any(a not in ("replayed", "in_progress") for a in got.get("answers", [])):
        bad.append("a repeat's answer was not a replay")
    if got.get("text_sha_matches") is False:
        bad.append("the report's text hash is not the approved one")
    if got.get("contracts") == "broken" or got.get("contract", "valid") != "valid":
        bad.append("a report breaks its contract")
    for k in ("in_p_a", "provider_as_requested", "model_as_requested", "effort_as_requested", "cloud"):
        if got.get(k) is False:
            bad.append("the new thread: %s is false (S1, S2)" % k)
    if got.get("thread_is_new") is False:
        bad.append("the create named a thread that an earlier step made")
    if got.get("same_thread") is False:
        bad.append("the repeat named another thread than its op id's create")
    if "started" in got and not got["started"] and not exp.get("start_optional"):
        bad.append("the new thread did not become idle within %d s" % kit.args.idle_timeout)
    keep = ("exit", "exit_list", "schema", "status", "kind", "reason", "replayed", "recovered", "differs", "delivery",
            "verdict", "state", "ready", "failed", "failed_reasons", "contract", "contracts", "text_sha_matches",
            "attempts", "calls", "refused", "aborted", "http", "shown", "probes", "staged_unchanged", "left_over",
            "answers", "record", "outcome", "p_a_new", "tray", "removal", "report", "observed_threads", "in_p_a", "provider_as_requested", "model_as_requested",
            "effort_as_requested", "cloud", "stages", "started", "thread_is_new", "same_thread", "staged_left", "list_contract",
            "stderr_line", "ms") + tuple(k for k in got if k.startswith("said_"))
    srep["got"] = {k: got[k] for k in keep if k in got}
    if got.get("_report") is not None and do in ("create", "web-create"):
        write_private(os.path.join(kit.run, "keys-%s.json" % step["id"]), structure(got["_report"]))
    srep["ms"] = now_ms() - t0
    srep["verdict"] = "as_expected" if not bad else "not_as_expected: " + "; ".join(bad)
    return srep


def run_groups(kit, names):
    a = kit.args
    groups = {g["id"]: g for g in kit.plan["groups"]}
    for n in names:
        if n not in groups:
            raise Stop("no group " + n)
    if not kit.settings:
        raise Stop("no settings: run settings first")
    exclude = set(a.exclude_id or [])
    t0 = time.monotonic()
    x2 = os.path.join(kit.x2, "room-cli")
    if not os.path.exists(x2) or observe.file_sha256(x2) != observe.file_sha256(os.path.join(HERE, "x2-shim.py")):
        raise Stop("X2 is missing or is not the reviewed shim; nothing was created or sent")
    kit.disarm()
    # A sibling may have finished after setup. Refresh all recorded sittings,
    # including this sitting's own completed steps, before judging the landing.
    try:
        with approval_locked(kit.cfg["approval"]):
            carry_from(kit.approval(), kit.work)
    except Stop as exc:
        return publish(kit, {"outcome": "incomplete", "stopped": str(exc), "groups": []})
    kit.new = kit._load("new.json", {})
    version = qc.version_record(kit.ctx)
    collect_forbidden(kit)
    first = qc.lists(kit.ctx, "before")
    for label in ("T-A", "T-B"):
        if kit.targets[label] not in first["views"].get("default", []):
            raise Stop("test thread %s is not in the default list view" % label)
    if kit.targets["P-A"] not in first.get("projects", []):
        raise Stop("P-A is not in the project list")
    pa = kit.targets["P-A"]
    sitting = kit._load("sitting.json", None)
    if sitting is None:
        # The sitting's first run (#168's R3): its judged set, their rows, the samples and their
        # last events, P-A's threads and X2's refusals so far are fixed here, once, and every
        # later run of the sitting is judged against them.
        pa_now = pa_rows(first, pa)
        if any(qc.classify(first["rows"][s]) != "quiet" for s in pa_now):
            raise Stop("P-A has work in flight (L-2); nothing was created or sent")
        # A fresh sitting under the same approval carries P-A's threads at the first sitting's start,
        # so the threads earlier sittings made still count as made by a step (#13, 2026-11-05).
        carried = kit._load("carried.json", None)
        pa_start = set(carried["pa_start"]) if carried else pa_now
        own = own_threads(kit)
        judged = judged_set(first, exclude | own, a.warm_hours, now_ms(), pa)
        if len(judged) < a.min_judged:  # too few cold sessions to stand for the rest: never a pass
            raise Stop("only %d sessions in the test project are quiet and older than %g h (at least %d are "
                       "needed); nothing was created or sent" % (len(judged), a.warm_hours, a.min_judged))
        samples = qc.choose_samples(strip(first, own), set(first["rows"]) - judged, a.samples)
        details0 = {s: observe.detail(kit.ctx, s) for s in samples}
        sitting = {"judged": sorted(judged), "baseline": {s: first["rows"][s] for s in judged}, "samples": samples,
                   "details0": details0, "pa_start": sorted(pa_start), "warm_hours": a.warm_hours, "started_ms": now_ms()}
        kit.save("sitting.json", sitting)
    judged, samples, details0 = set(sitting["judged"]), sitting["samples"], sitting["details0"]
    baseline = {"rows": sitting["baseline"]}
    pa_start = set(sitting["pa_start"])
    own = own_threads(kit) | (pa_rows(first, pa) - pa_start)
    details = dict(details0)
    rep = {"report": "openwiz-0.0.4-live-check", "dry_run": kit.dry,
           "kit_sha256": observe.file_sha256(__file__),
           "core_sha256": observe.file_sha256(core.__file__),
           "x2_sha256": observe.file_sha256(os.path.join(kit.x2, "room-cli")),
           "quick_check_sha256": observe.file_sha256(qc.__file__),
           "observe_sha256": observe.file_sha256(observe.__file__),
           "version_read": version, "groups": [], "outcome": "as_expected",
           "judged": {"rule": "the test project's sessions, quiet at the start and not updated in the %g h before "
                              "it; each judged against its own start, on every field; every other session is "
                              "reported, never judged" % a.warm_hours,
                      "sessions": len(judged),
                      "not_judged": {"recent_or_active": len({x for x in set(first["rows"]) - judged - own - exclude
                                                                           if first["rows"][x].get("project") == pa}),
                                     "outside_test_project": len({x for x in set(first["rows"]) - own - exclude
                                                                  if first["rows"][x].get("project") != pa}),
                                     "excluded_ids": len(exclude & set(first["rows"])),
                                     "own_threads": len(own & set(first["rows"]))}}}
    stop = None
    entry_fail, entry_missing = judge(baseline, first, judged)
    if entry_fail:
        stop = "at entry: a judged session changed since the sitting's start (S1)"
    elif entry_missing:
        stop = "incomplete: at entry, a judged session could not be compared"
    rep["entry"] = {"judged_changed": entry_fail, "missing_field": entry_missing}
    land0 = landing_all(kit, first)
    rep["landing_at_start"] = land0["verdict"]
    if land0["verdict"] != "as_expected":
        stop = "incomplete: the targets do not hold what the steps so far sent: " + land0["verdict"]
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
            ran = []
            for step in steps:
                if step.get("project") == "P-N" and not (kit.settings or {}).get("p_n"):
                    # R-2 needs a standard project without a remote; with none, it is never run against
                    # another project: a recorded gap (fixtures only; the orchestrator, #13, 2026-11-05).
                    srep = {"step": step["id"], "verdict": "skipped: no standard project without a GitHub remote "
                            "exists; R-2 stays a fixture-only gap", "got": {"attempts": 0, "calls": 0}}
                    grep["steps"].append(srep)
                    sys.stderr.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), step["id"], srep["verdict"]))
                    sys.stderr.flush()
                    continue
                srep = run_step(kit, step)
                grep["steps"].append(srep)
                ran.append(step)
                sys.stderr.write("[%s] %s: %s\n" % (time.strftime("%H:%M:%S"), step["id"], srep["verdict"]))
                sys.stderr.flush()
                if srep["verdict"] != "as_expected":
                    stop = "%s: %s" % (step["id"], srep["verdict"])
                    break
            expect_landing(kit, ran)
            if not settle(kit):
                stop = stop or "incomplete: a target thread did not settle within %d s" % a.idle_timeout
            snap = qc.lists(kit.ctx, "after-seq")
            land = landing_all(kit, snap)
            grep.setdefault("landing", []).append(land)
            if land["verdict"] != "as_expected":
                stop = stop or land["verdict"]
        if not stop and a.late:
            kit.arm(name + "-late")
            time.sleep(a.late)
            late = kit.writes(name + "-late")["attempts"]
            kit.disarm()
            land = landing_all(kit, qc.lists(kit.ctx, "after-late"))
            grep["late_wait"] = {"s": a.late, "attempts": late, "landing": land["verdict"]}
            if late:
                stop = "%s: a write during the late wait" % name
            elif land["verdict"] != "as_expected":
                stop = "%s, after the late wait: %s" % (name, land["verdict"])
        # The bracket: the judged sessions against the run's start, and the samples' events.
        collect_forbidden(kit)
        after = qc.lists(kit.ctx, "after-" + name)
        details_a = {s: observe.detail(kit.ctx, s, details[s]) for s in samples}
        res = {s: qc.sample_eval(kit.ctx, s, details0[s], details_a[s]) for s in samples}
        failures, missing = judge(baseline, after, judged)
        sample_fail = sum(1 for r in res.values() if r["advance"] or r["qmc_changed"])
        unreadable = sum(1 for r in res.values() if r["unreadable"]) + sum(after.get("unreadable", {}).values())
        own = own_threads(kit) | (pa_rows(after, pa) - pa_start)
        grep["outside"] = {"sessions": len(after["rows"]), "judged": len(judged),
                           "appeared_not_judged": len(set(after["rows"]) - set(first["rows"]) - own),
                           "failures": failures, "missing_field": missing,
                           "not_judged_changed": unjudged_changes(prev, after, judged | own),
                           "samples": len(samples), "samples_with_new_events": sample_fail,
                           "unreadable": unreadable}
        if failures or sample_fail:
            grep["outside"]["verdict"] = "not_as_expected: a judged session changed (S1)"
            stop = stop or "%s: a judged session outside the test's own threads changed (S1)" % name
        elif missing or unreadable:
            grep["outside"]["verdict"] = "incomplete: something judged could not be compared"
            stop = stop or "%s: incomplete outside the test's own threads" % name
        else:
            grep["outside"]["verdict"] = "as_expected"
        prev, details = after, details_a
    if not stop:
        land = landing_all(kit, qc.lists(kit.ctx, "end"))
        rep["landing_at_end"] = land["verdict"]
        rep["agent_reports"] = land.get("agent_reports")  # recorded as the agent's report, deciding nothing (L-5)
        if land["verdict"] != "as_expected":
            stop = "at the end: " + land["verdict"]
    rep["stopped"] = stop
    rep["outcome"] = "as_expected" if not stop else ("incomplete" if "incomplete" in stop else "not_as_expected")
    rep["reads"] = dict(sorted(kit.ctx.reads.items()))
    rep["duration_s"] = int(time.monotonic() - t0)
    return publish(kit, rep)  # the outcome is decided there, last, from the sitting's taint


# --------------------------------------------------------------------------
# Privacy (#152, Sol R4: every non-empty forbidden string, of any length, against every
# decoded key and string value)


TITLE_KEYS = ("id", "title", "titleFallback", "projectId", "parentThreadId", "environmentId", "environmentHostId")


def collect_forbidden(kit):
    """Every live string a report must never hold, kept in memory only: each session's id
    and title (and its project, parent, environment and host ids), each project's and
    machine's id and name, the targets' and new threads' titles, and the model names."""
    def add(v):
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
                add(r.get("gitRemoteUrl"))
    for r in kit.ctx.room_json(["machine", "list", "--json"]) or []:
        if isinstance(r, dict):
            add(r.get("id"))
            add(r.get("name"))
    for sid in sorted(own_threads(kit)):
        s = show_of(kit, sid)
        if s:
            add(s.get("title"))
    for p in ((kit.settings or {}).get("pick") or {}).values():
        add(p.get("model"))
    add(((kit.settings or {}).get("unoffered") or {}).get("model"))


PRINTED = [False]
TAINTED = ("the sitting is tainted: X2 refused %d call(s); any refusal, of any kind, at any time, taints the whole "
           "sitting (#168's R6), and only a new setup clears it")


def decide(kit, rep):
    """#168's R6, final round (the orchestrator's diagnosis): the outcome is decided here, as the
    very last thing before the report is written and the command exits, under X2's lock, from the
    sitting's ledger. Tainted (X2 refused any call, at any time) means not as expected: every
    `as_expected` verdict and outcome in the report is replaced, the refusals are named, and the
    command exits 10. There is no acknowledged state; only a new setup clears the taint."""
    led = kit.ledger()
    rep["x2_refusals"] = {"count": int(led.get("refusals", 0)), "refused": list(led.get("refused") or [])}
    if not led.get("tainted"):
        return rep
    msg = TAINTED % int(led.get("refusals", 0))

    def walk(v):
        if isinstance(v, dict):
            for k in list(v):
                if k in ("verdict", "outcome") and v[k] == "as_expected":
                    v[k] = "not_as_expected" if k == "outcome" else "not_as_expected: " + msg
                else:
                    walk(v[k])
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(rep)
    if rep.get("outcome") in (None, "as_expected"):
        rep["outcome"] = "not_as_expected"
    rep["stopped"] = "%s; %s" % (rep["stopped"], msg) if rep.get("stopped") else msg
    return rep


def finish(kit, rep, scan=False):
    """Decides the outcome (decide), then, still under X2's lock, scans, keeps and prints the report."""
    with kit.locked():
        decide(kit, rep)
        if scan:
            scan_report(kit, rep)
        print(json.dumps(rep, indent=1, sort_keys=True))
        sys.stdout.flush()
        PRINTED[0] = True
    return rep


def publish(kit, rep):
    return finish(kit, rep, scan=True)


def scan_report(kit, rep):
    """The leak scan, on every report X1 prints, over the decoded report. A hit prints
    nothing, and keeps the report on the PC only."""
    text = json.dumps(rep, indent=1, sort_keys=True)
    args = kit.args
    forbid = set(kit.forbidden) | set(kit.targets.values()) | set(kit.opids.values()) | set(kit.new) \
        | set(getattr(args, "forbid", None) or []) | set(getattr(args, "exclude_id", None) or []) \
        | {kit.work, os.path.expanduser("~"), kit.cfg["host"], kit.cfg["files"]}
    if kit.settings and kit.settings.get("p_n"):
        forbid.add(kit.settings["p_n"])
    hits = len(leaked(forbid, rep))
    if hits:
        write_private(os.path.join(kit.run, "report-blocked-%d.json" % now_ms()),
                      json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False))
        raise Stop("the report would contain %d forbidden strings; nothing printed "
                   "(kept in the work directory only)" % hits)
    n = len([f for f in os.listdir(kit.run) if f.startswith("report-")])
    write_private(os.path.join(kit.run, "report-%02d.json" % (n + 1)), text)


# --------------------------------------------------------------------------
# Commands


def cmd_texts(a):
    texts, where = load_texts(a.texts)
    rows = [{"label": k, "target": where[k], "bytes": len(texts[k].encode()), "sha256": sha(texts[k])}
            for k in sorted(texts)]
    return {"texts": rows, "all_approved": True, "outcome": "as_expected"}


def cmd_files(a):
    out = os.path.abspath(a.out)
    if os.path.exists(out) and os.listdir(out):
        raise Stop("the files directory exists and is not empty; each run needs a new one")
    os.makedirs(out, mode=0o700, exist_ok=True)
    rows = []
    for label, (name, data) in sorted(synthetic_files().items()):
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        rows.append({"label": label, "name": name, "bytes": len(data), "sha256": sha_bytes(data)})
    check_files(out)
    return {"files": rows, "all_approved": True, "outcome": "as_expected"}


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
    read_targets(a.targets)
    check_files(a.files)
    contracts = a.contracts or (os.path.join(a.checkout, "contracts") if a.checkout else os.path.join(REPO, "contracts"))
    try:
        Schemas(contracts)
    except (OSError, ValueError):
        raise Stop("the contracts can't be read: every answer is checked against them")
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
    reply = None
    if a.agent_reply:
        rtype, _, rfield = a.agent_reply.rpartition(":")
        if not rtype or not rfield:
            raise Stop("--agent-reply takes TYPE:FIELD (an event type and a field path such as data.input)")
        reply = [rtype, rfield]
    restore = json.loads(a.restore_cmd) if a.restore_cmd else None
    if restore is not None and not (isinstance(restore, list) and restore and all(isinstance(x, str) for x in restore)
                                    and os.path.isabs(restore[0]) and a.restore_log and os.path.isabs(a.restore_log)
                                    and a.restore_sha256):
        raise Stop("the confirmed launch needs an absolute command (JSON), its log and its sha256")
    # #168's R8: the sitting is set up under the approval, and inherits only what's left of it.
    if not a.approval:
        raise Stop("setup needs --approval: L-8's allowance file, made once by `approval init` and named by every setup")
    appr = os.path.abspath(a.approval)
    if not os.path.isfile(appr):
        raise Stop("the approval's file doesn't exist: setup never makes one (`approval init`, once, before the first "
                   "setup; a lost one means asking Jake)")
    with approval_locked(appr):
        ap = load_approval(appr)
        left = {k: remaining(ap, k) for k in L8}
        budget = {"spawn": left["spawn"] if a.budget_creates is None else a.budget_creates,
                  "tell": left["tell"] if a.budget_sends is None else a.budget_sends}
        for k, n in KINDS:
            if not 0 <= budget[k] <= left[k]:
                raise Stop("the approval has %d %s left: a fresh setup inherits only what's left (more needs Jake to "
                           "amend the approval)" % (left[k], n))
        os.makedirs(work, mode=0o700)
        for d in ("x2", "state", "run"):
            os.makedirs(os.path.join(work, d), mode=0o700)
        shutil.copyfile(os.path.join(HERE, "x2-shim.py"), os.path.join(work, "x2", "room-cli"))
        os.chmod(os.path.join(work, "x2", "room-cli"), 0o700)
        sitting = len(ap["sittings"]) + 1
        carried = carry_from(ap, work)  # before this sitting is listed: only the earlier ones count
        ap["sittings"].append({"n": sitting, "work": work, "t_ms": now_ms()})  # where its evidence stays
        save_approval(appr, ap)
        # The sitting's ledger (#168's R1): made here, once; X2 records every write in it, and charges
        # it on the approval it names (#168's R8).
        write_private(os.path.join(work, "x2", "ledger.json"), {
            "budget": {"spawn": 0, "tell": 0}, "used": {"spawn": 0, "tell": 0}, "approval": appr, "sitting": sitting,
            "auth": {}, "generation": 0, "tainted": False, "refusals": 0, "refused": []})  # only a new setup is untainted
    cfg = {"room_cli": os.path.abspath(a.room_cli), "openwiz": os.path.abspath(a.openwiz),
           "server": os.path.abspath(a.server) if a.server else None, "texts": os.path.abspath(a.texts),
           "plan": os.path.abspath(a.plan), "targets": os.path.abspath(a.targets), "files": os.path.abspath(a.files),
           "contracts": os.path.abspath(contracts), "port": a.port, "host": a.host, "web_root": a.web_root,
           "dry_run": a.dry_run, "access_url": a.access_url, "restore_cmd": restore, "restore_log": a.restore_log,
           "restore_sha256": a.restore_sha256.lower() if a.restore_sha256 else None,
           "agent_reply": reply, "approval": appr}
    write_private(os.path.join(work, "kit.json"), cfg)
    kit = Kit(work)
    kit.args = a
    kit.disarm()
    kit.path_guard(kit.env())
    # PATH alone is no proof: bundled-lookup binaries ignore it. One models read
    # must reach X2 as exactly one cloud-status read, successfully, with no write.
    # The budget stays zero and arm refuses writes until this proof succeeds.
    kit.arm("setup-read")
    try:
        probe = subprocess.run([kit.cfg["openwiz"], "models", "--json"], env=kit.env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=30)
        with open(os.path.join(kit.x2, "reads.log")) as f:
            reads = [json.loads(line) for line in f]
        good = (probe.returncode == 0 and len(reads) == 1
                and reads[0].get("step") == "setup-read@" + kit.tag
                and reads[0].get("kind") == "cloud status --json"
                and kit.writes("setup-read")["attempts"] == 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        good = False
    finally:
        kit.disarm()
    if not good:
        raise Stop("setup could not prove one successful openwiz models read through X2; writes stay disabled")
    with kit.locked():
        led = kit.ledger()
        if led.get("tainted"):
            raise Stop("setup could not prove a clean read through X2; writes stay disabled")
        # Save the proof before enabling the budget; any failed setup stays shut.
        cfg["read_guard"] = True
        write_private(os.path.join(work, "kit.json"), cfg)
        led["budget"] = budget
        kit.save_ledger(led)
    return {"setup": "ready", "dry_run": a.dry_run, "binary": binary,
            "carried": {"from": carried["from"], "creates": carried["creates"]} if carried else None,
            "budget": {"creates": budget["spawn"], "sends": budget["tell"]},
            "approval": approval_block(ap, sitting),
            "x2_sha256": observe.file_sha256(os.path.join(work, "x2", "room-cli")),
            "kit_sha256": observe.file_sha256(__file__),
           "core_sha256": observe.file_sha256(core.__file__), "path_guard": "room-cli on the write PATH is X2",
            "read_guard": "openwiz models: one cloud status read through X2",
            "outcome": "as_expected"}


def cmd_approval(a):
    """#168's R8: L-8's allowance across every sitting. `init` makes the approval's file once,
    with at most L-8's totals; `show` prints the cumulative totals and what's left (the run
    sheet reads it before any recovery); `amend` changes the total only with Jake's own words,
    which stay in the file and are never printed."""
    path = os.path.abspath(a.approval)
    if a.action == "init":
        want = {"spawn": L8["spawn"] if a.creates is None else a.creates, "tell": L8["tell"] if a.sends is None else a.sends}
        if any(not 0 <= want[k] <= L8[k] for k in L8):
            raise Stop("L-8 approves at most %d creates and %d sends: more needs Jake to amend the approval "
                       "(`approval amend`)" % (L8["spawn"], L8["tell"]))
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with approval_locked(path):
            if os.path.exists(path):
                raise Stop("an approval's file is made once: this one exists (every setup names it; it is never remade)")
            ap = {"schema": "kit13.approval.v1", "approval": "L-8", "total": want, "charges": [], "sittings": [],
                  "amendments": [], "t_ms": now_ms()}
            save_approval(path, ap)
    elif a.action == "amend":
        if not (a.jake_said or "").strip():
            raise Stop("changing the total needs Jake to amend the approval: --jake-said, in his own words")
        if a.creates is None or a.sends is None or a.creates < 0 or a.sends < 0:
            raise Stop("amend takes the new totals: --creates and --sends")
        with approval_locked(path):
            ap = load_approval(path)
            new = {"spawn": a.creates, "tell": a.sends}
            ap["amendments"].append({"t_ms": now_ms(), "from": dict(ap["total"]), "to": new, "jake_said": a.jake_said})
            ap["total"] = new
            save_approval(path, ap)
    else:
        ap = load_approval(path)
    return {"approval": approval_block(ap), "outcome": "as_expected"}


def cmd_settings(a):
    """Picks each harness's model and effort from today's catalogue (`openwiz models`,
    through X2, which allows no write): the first model offered, at its lowest effort,
    unless --set names one; an unoffered combination for R1; the harnesses that take
    images; and P-N, a standard project without a remote, for R2. Kept in the work
    directory (0600); only harness ids, effort labels and counts are printed."""
    kit = Kit(a.work)
    kit.args = a
    kit.arm("settings")
    outs = openwiz(kit, {"id": "settings"}, ["models", "--json"])
    w = kit.writes("settings")
    kit.disarm()
    code, rep, _ = outs[0]
    if code != 0 or contract_problem(kit, rep, "openwiz.cloud-options.v1") or w["attempts"]:
        raise Stop("openwiz models did not answer as expected (exit %s)" % code)
    offered = {h["harness"]: h for h in rep.get("harnesses", [])}
    chosen = {}
    for s in a.set or []:
        h, _, me = s.partition("=")
        m, _, e = me.rpartition("/")
        chosen[h] = (m, e)
    pick = {}
    for h in HARNESSES:
        o = offered.get(h)
        if not o or not o.get("models"):
            raise Stop("%s offers no model today" % h)
        if h in chosen:
            m, e = chosen[h]
            mm = next((x for x in o["models"] if x["model"] == m), None)
            if mm is None or e not in mm["efforts"]:
                raise Stop("the setting chosen for %s is not offered today" % h)
        else:
            mm = o["models"][0]
            m, e = mm["model"], next((x for x in EFFORT_ORDER if x in mm["efforts"]), None)
            if e is None:
                raise Stop("%s's first model offers no effort spawn takes" % h)
        pick[h] = {"model": m, "effort": e}
    unoffered = None
    for h in HARNESSES:
        own = {x["model"] for x in offered[h]["models"]}
        other = next((x["model"] for g in HARNESSES if g != h for x in offered[g]["models"] if x["model"] not in own),
                     None)
        if other:
            unoffered = {"harness": h, "model": other, "effort": "low"}
            break
    images = [h for h in HARNESSES if (offered[h].get("attachments") or {}).get("images") is True]
    projects = kit.ctx.room_json(["project", "list", "--json", "--include-personal"])
    p_n = next((p.get("id") for p in projects if isinstance(p, dict) and p.get("kind") == "standard"
                and p.get("gitRemoteUrl") is None and isinstance(p.get("id"), str) and ID_RE.match(p["id"])
                and p.get("id") != kit.targets["P-A"]), None)
    pa = next((p for p in projects if isinstance(p, dict) and p.get("id") == kit.targets["P-A"]), None)
    if pa is None or pa.get("kind") != "standard" or not isinstance(pa.get("gitRemoteUrl"), str):
        raise Stop("P-A is not a standard project with a remote (L-2)")
    kit.settings = {"pick": pick, "unoffered": unoffered, "images": images, "p_n": p_n}
    kit.save("settings.json", kit.settings)
    collect_forbidden(kit)
    return publish(kit, {"settings": {h: {"effort": p["effort"], "model": "picked"} for h, p in pick.items()},
                         "unoffered_found": unoffered is not None, "image_harnesses": images,
                         "no_remote_project_found": p_n is not None, "outcome": "as_expected"})


def cmd_map(a):
    """The targets, checked; with --show, names, models and titles on Jake's screen only."""
    kit = Kit(a.work)
    kit.args = a
    kit.disarm()
    default = kit.ctx.room_json(["thread", "list", "--json"])
    ids = {r.get("id") for r in default if isinstance(r, dict)}
    out, bad = {}, []
    for label in ("T-A", "T-B"):
        s = show_of(kit, kit.targets[label])
        if s is None:
            bad.append("%s not found" % label)
            continue
        row = {"where": "Local" if s["local"] else "Cloud", "harness": s["provider"], "status": s["status"],
               "queued": s["qmc"], "in_default_view": kit.targets[label] in ids}
        if a.show:
            row["title"] = s["title"]
        out[label] = row
        if row["where"] != ("Local" if label == "T-A" else "Cloud"):
            bad.append("%s is %s, should be %s" % (label, row["where"], "Local" if label == "T-A" else "Cloud"))
        if not (idle(s) and row["in_default_view"]):
            bad.append("%s is not idle and visible" % label)
    rows = kit.ctx.room_json(["thread", "list", "--json", "--include-hidden", "--include-archived"])
    in_pa = [r for r in rows if isinstance(r, dict) and r.get("projectId") == kit.targets["P-A"]]
    busy = [r for r in in_pa if qc.classify(observe.list_fields(r)) != "quiet"]
    out["P-A"] = {"threads": len(in_pa), "not_quiet": len(busy)}
    if busy and not a.after:
        bad.append("P-A has work in flight (L-2)")
    if a.show:
        projects = kit.ctx.room_json(["project", "list", "--json", "--include-personal"])
        out["P-A"]["name"] = next((p.get("name") for p in projects if p.get("id") == kit.targets["P-A"]), None)
        out["settings"] = kit.settings
    if bad:
        raise Stop("; ".join(bad))
    rep = {"targets": out, "map": "ok: Jake confirms each by eye", "outcome": "as_expected"}
    if a.show:
        return finish(kit, rep)  # Jake's own terminal only: never saved, never committed
    collect_forbidden(kit)
    return publish(kit, rep)


def cmd_recheck(a):
    """Lesson 6: spawn's and tell's help on today's room-cli, kept on the PC; only
    whether each flag OpenWiz passes is still listed is printed."""
    kit = Kit(a.work)
    kit.args = a
    flags = {"spawn": ("--project", "--machine", "--provider", "--model", "--reasoning-level", "--request-id",
                       "--json", "--prompt", "--file", "--image"),
             "tell": ("--mode", "--json", "--file", "--image")}
    out = {}
    for sub, want in flags.items():
        r = kit.ctx.room(["thread", sub, "--help"])
        text = (r.stdout + r.stderr).decode("utf-8", "replace")
        write_private(os.path.join(kit.run, "thread-%s-help.txt" % sub), text)
        out[sub] = {"exit": r.returncode, "help_sha256": sha(text),
                    "missing": [f for f in want if not re.search(r"(^|[\s\[,])%s([\s\]=<,]|$)" % re.escape(f), text)]}
    collect_forbidden(kit)
    ok = all(v["exit"] == 0 and not v["missing"] for v in out.values())
    return publish(kit, {"help": out, "outcome": "as_expected" if ok else
                         "not_as_expected: a flag OpenWiz passes is no longer listed; stop and re-plan"})


def cmd_parity(a):
    """S10: the CLI's and the web's new-thread records, by kind, structure only (no call)."""
    kit = Kit(a.work)
    kit.args = a
    pairs = (("created", "C2-N1", "J1-N3"), ("refused, unoffered", "C1-R1", "W2-R1"))
    out = {}
    for name, cli, web in pairs:
        rc = kit.new_record(kit.opids[cli]) if cli in kit.opids else None
        rw = kit.new_record(kit.opids[web]) if web in kit.opids else None
        if not rc or not rw:
            out[name] = {"verdict": "incomplete: a record is missing"}
            continue
        # A record carries `attachments` only when its prompt had some (the web create
        # has an image, the CLI's has none): the shapes are compared without that key.
        same = {k: v for k, v in rc["shape"].items() if k != "attachments"} == \
            {k: v for k, v in rw["shape"].items() if k != "attachments"}
        out[name] = {"cli": rc["outcome"], "web": rw["outcome"], "record_structure_equal": same,
                     "attachments_key": {"cli": "attachments" in rc["shape"], "web": "attachments" in rw["shape"]},
                     "verdict": "as_expected" if rc["outcome"] == rw["outcome"] and same else "not_as_expected"}
    verdicts = [v["verdict"] for v in out.values()]
    outcome = ("as_expected" if all(v == "as_expected" for v in verdicts) else
               "not_as_expected" if any(v == "not_as_expected" for v in verdicts) else "incomplete")
    collect_forbidden(kit)
    return publish(kit, {"parity": out, "outcome": outcome})


def cmd_receipts(a):
    """S4: the structure of every receipt X2 captured (key names and JSON types, never a
    value), by kind, against #11's spawn fixture and #10's PC-observed tell fixtures
    (#571, backported in #583). Every receipt counts (#152, Sol R9)."""
    kit = Kit(a.work)
    kit.args = a
    fixture = os.path.join(kit.cfg["contracts"], "..", "tests", "fixtures", "room-cli-v127", "new-thread",
                           "spawn-receipt-created.json")
    spawn_keys = structure(json.load(open(fixture))) if os.path.exists(fixture) else None
    send_dir = os.path.join(kit.cfg["contracts"], "..", "tests", "fixtures", "room-cli-0.43.1", "send")
    tell_shapes = {}
    for name in ("tell-sent-observed.json", "tell-queued-observed.json", "tell-steer-queued-observed.json"):
        path = os.path.join(send_dir, name)
        if os.path.exists(path):
            doc = json.load(open(path))
            tell_shapes[(doc["delivery"], doc["mode"])] = [structure(doc)]
            if doc["delivery"] == "sent":  # observed in both requested modes
                tell_shapes[("sent", "steer")] = [structure(doc)]
            elif doc["mode"] == "queue":
                # #10: a busy queue's sender is an id (agent) or null (user).
                user = json.loads(json.dumps(doc))
                user["queuedMessage"]["senderThreadId"] = None
                tell_shapes[("queued", "queue")].append(structure(user))
    kinds = {}
    for name in sorted(os.listdir(kit.x2)):
        if not (name.startswith("capture-") and name.endswith(".out")):
            continue
        base = os.path.join(kit.x2, name[:-4])
        raw = open(base + ".out", "rb").read()
        try:
            doc = json.loads(raw) if raw.strip() else None
        except ValueError:
            doc = "not_json"
        if name.startswith("capture-spawn-"):
            kind = "spawn" if isinstance(doc, dict) else "spawn:" + ("rejection" if doc is None else "not_json")
            entry = {"documented_keys": isinstance(doc, dict) and spawn_keys is not None
                     and structure(doc) == spawn_keys}
        elif isinstance(doc, dict):
            kind = "tell:" + (doc.get("delivery") if doc.get("delivery") in ("sent", "queued") else "other")
            key = (doc.get("delivery"), doc.get("mode"))
            # Malformed values never become dictionary keys (or a script error).
            expected = tell_shapes.get(key) if all(isinstance(v, str) for v in key) else None
            actual = structure(doc)
            entry = {"documented_keys": expected is not None and actual in expected}
        else:
            kind, entry = "tell:" + ("rejection" if doc is None else "not_json"), {}
        k = kinds.setdefault(kind, {"count": 0})
        k["count"] += 1
        if "documented_keys" in entry:
            k["documented_keys"] = k.get("documented_keys", True) and entry["documented_keys"]
    drift = [k for k, v in sorted(kinds.items()) if v.get("documented_keys") is False
             or k.endswith((":other", ":not_json", ":rejection"))]
    drift += ["missing: %s" % r for r in a.require.split(",") if r and r not in kinds]
    collect_forbidden(kit)
    return publish(kit, {"receipts": kinds, "drift": drift, "required": a.require.split(","),
                         "fixture_found": spawn_keys is not None,
                         "outcome": "as_expected" if not drift and spawn_keys is not None else
                         "drift: blocks the claims that use these receipts (S4)"})


def cmd_swap(a):
    """The swap (the one --write step Jake OKs): `start` checks that the port is served by
    the confirmed launch (or by nothing), then starts the supervisor and waits for X1's
    server; `end` asks it to restore the confirmed launch; the others are the run's
    fault requests and the restart."""
    kit = Kit(a.work)
    kit.args = a
    if a.action == "start":
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
        wait_for(lambda: swap_state(kit).get("state") in ("restored", "restore-failed", "restored-by-guard",
                                                          "guard-died"), 90)
    else:
        swap_control(kit, a.action)
    st = swap_state(kit)
    want = {"start": "up", "end": "restored"}.get(a.action, "up")
    ok = st.get("state") == want or (a.action == "end" and st.get("state") == "restored-by-guard")
    return finish(kit, {"swap": st.get("state"), "old_was_running": st.get("old_was_running"),
                        "error": st.get("error"), "outcome": "as_expected" if ok else "stop"})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("texts")
    s.add_argument("--texts", default=os.path.join(TICKET, "texts.tsv"))
    s = sub.add_parser("files")
    s.add_argument("--out", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--work", required=True)
    s.add_argument("--room-cli", required=True)
    s.add_argument("--openwiz", required=True)
    s.add_argument("--server")
    s.add_argument("--targets", required=True)
    s.add_argument("--files", required=True)
    s.add_argument("--contracts", help="default: the checkout's contracts/")
    s.add_argument("--texts", default=os.path.join(TICKET, "texts.tsv"))
    s.add_argument("--plan", default=os.path.join(HERE, "plan.json"))
    s.add_argument("--port", type=int, default=7370, help="the site's port (where the tunnel sends it)")
    s.add_argument("--restore-cmd", help="the confirmed launch, a JSON array (the running server's command line)")
    s.add_argument("--restore-log", help="the confirmed server's log, appended to on restore")
    s.add_argument("--restore-sha256", help="the confirmed server binary's sha256")
    s.add_argument("--host", default="openwiz.invalid", help="the public host name (never committed)")
    s.add_argument("--web-root")
    s.add_argument("--access-url", help="where the unauthenticated L-10 probe goes (default https://<host>)")
    s.add_argument("--expect-sha256")
    s.add_argument("--expect-server-sha256")
    s.add_argument("--checkout")
    s.add_argument("--expect-head")
    s.add_argument("--dry-run", action="store_true", help="the fake only: X1 presses for Jake")
    s.add_argument("--agent-reply", help="TYPE:FIELD, the agent's reply's event type and output field, once observed "
                   "(AL1's verdict needs it; without it the report is recorded as unattributed)")
    s.add_argument("--approval", help="L-8's allowance file (approval init), outside every work directory")
    s.add_argument("--budget-creates", type=int, help="at most this many spawns in the sitting (default and most: "
                   "what's left under the approval)")
    s.add_argument("--budget-sends", type=int, help="at most this many tells in the sitting (default and most: "
                   "what's left under the approval)")
    s = sub.add_parser("approval")
    s.add_argument("action", choices=("init", "show", "amend"))
    s.add_argument("--approval", required=True)
    s.add_argument("--creates", type=int, help="init: at most L-8's 4 (the default); amend: the new total")
    s.add_argument("--sends", type=int, help="init: at most L-8's 2 (the default); amend: the new total")
    s.add_argument("--jake-said", help="amend: Jake's own words, amending the approval (kept in the file, never printed)")
    s = sub.add_parser("settings")
    s.add_argument("--work", required=True)
    s.add_argument("--set", action="append", help="harness=model/effort, instead of the first offered")
    s = sub.add_parser("map")
    s.add_argument("--work", required=True)
    s.add_argument("--show", action="store_true", help="Jake's terminal only; never saved")
    s.add_argument("--after", action="store_true", help="the closing map: P-A's new threads may still run")
    s = sub.add_parser("recheck")
    s.add_argument("--work", required=True)
    s = sub.add_parser("run")
    s.add_argument("--work", required=True)
    s.add_argument("--groups", required=True)
    s.add_argument("--exclude-id", action="append")
    s.add_argument("--forbid", action="append")
    s.add_argument("--samples", type=int, default=6)
    s.add_argument("--settle", type=float, default=60)
    s.add_argument("--late", type=float, default=180)
    s.add_argument("--idle-timeout", type=float, default=900)
    s.add_argument("--poll", type=float, default=5)
    s.add_argument("--press-timeout", type=float, default=900)
    s.add_argument("--warm-hours", type=float, default=48,
                   help="sessions updated this recently before the run are Jake's: reported, not judged")
    s.add_argument("--min-judged", type=int, default=20,
                   help="fewer cold sessions than this to judge stops the run before any write")
    s.add_argument("--answers", choices=("chat", "terminal"), default="chat")
    s = sub.add_parser("swap")
    s.add_argument("--work", required=True)
    s.add_argument("action", choices=("start", "end", "stop-server", "kill-server", "start-server"))
    s.add_argument("--minutes", type=float, default=90, help="the swap's deadline: then the confirmed launch is back")
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
    s.add_argument("--require", default="spawn,tell:sent", help="the receipt kinds the run must have produced")
    a = p.parse_args(argv)
    PRINTED[0] = False
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
            if any(not g.startswith(("C", "W", "J")) for g in groups):
                raise Stop("unknown group")
            rep = run_groups(kit, groups)
        else:
            rep = {"texts": cmd_texts, "files": cmd_files, "setup": cmd_setup, "approval": cmd_approval,
                   "settings": cmd_settings,
                   "map": cmd_map, "recheck": cmd_recheck, "parity": cmd_parity, "swap": cmd_swap,
                   "receipts": cmd_receipts}[a.cmd](a)
    except Stop as e:
        print(json.dumps({"stopped": str(e)}))
        return 10
    except KeyboardInterrupt:
        print(json.dumps({"stopped": "interrupted"}))
        return 130
    except Exception as e:  # its text could hold an id: the type only
        if os.environ.get("NEW_KIT_DEBUG"):
            raise
        print(json.dumps({"stopped": "unexpected error: %s" % type(e).__name__}))
        return 11
    if not PRINTED[0]:  # setup, texts and files: no sitting to decide from yet
        print(json.dumps(rep, indent=1, sort_keys=True))
    return 0 if rep.get("outcome") == "as_expected" else 10  # #152, Sol R8: every command's outcome decides


if __name__ == "__main__":
    sys.exit(main())
