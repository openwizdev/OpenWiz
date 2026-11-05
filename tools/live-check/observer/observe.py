#!/usr/bin/env python3
"""OpenWiz 0.0.1 ticket 3 (#4): the live acceptance observer. READ-ONLY.

It runs the procedures in ../procedures.md: the pre-flight discovery, the
P8(b) brackets (control, `ls`, `ls -l`, `show`, P4, inventory, settle, late),
the P1, P2, P3, P4 and P6 comparisons, and a sanitized report.

Never run it against a real room-cli until Jake has approved procedures.md
and each observer read it lists. As committed, it has been run only against
the repository's fake room-cli and the synthetic stub in test/.

Rules it enforces in code:
- every room-cli call it makes itself is checked against OBSERVER_READS
  before it starts; nothing else can be started;
- OpenWiz runs with a shim first on PATH that logs each call's arguments and
  start time and refuses anything outside OpenWiz's allowlist;
- the run directory (mode 0700, on the machine it runs on) holds only the
  fields compared, with their ids, and the shim's call logs; titles,
  purposes, final output, event content and OpenWiz's printed output are
  analysed in memory and never stored;
- the report holds counts, timings, versions, outcome classes and per-run
  ordinals only, and is refused if it contains any id, project or machine
  id, the host name, the user name or the home path;
- HMAC-SHA-256 with a per-run random key is used only for equality on that
  machine and for ordering ordinals; no HMAC value is ever reported;
- the M3 step (`requests`) runs a loopback logging proxy only for that step;
  it keeps, per request, only the method and the route template (ids as
  :id), never a header, body, query value or token.

Python 3.9 or later, standard library only.
"""

import argparse
import concurrent.futures
import getpass
import hashlib
import hmac
import http.client
import http.server
import json
import shutil
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse

TESTED_VERSION = "0.43.1"
SCRIPT_VERSION = "ticket-3-observer-2"
READ_TIMEOUT_S = 30
# Sol's sweep: the bounded wait for every admitted request to finish before an
# after-state (finding 1), and the drain's absolute deadline (finding 4).
QUIESCE_S = READ_TIMEOUT_S
DRAIN_S = 2 * READ_TIMEOUT_S
ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}\Z")  # match(): anchored at both ends
# Event labels (type, initiator, source) are reported only if Jake approved
# that exact value (`run --approve-label`); every other value is `other`. No
# capture recorded event labels, so none is approved in advance.
APPROVED_LABELS = set()
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]{0,40}")
ENV_RE = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]{2,40}\b")
QUIET = ("idle", "error")
# The fields that decide whether a session is quiet (not_quiet), besides COMPARED.
QUIET_FIELDS = ("queuedWork", "pending", "activity")
COMPARED = ("status", "display", "updatedAt", "lastReadAt", "latestAttentionAt",
            "qmc", "last_seq", "queuedWork", "pending", "activity")
LIST_VIEWS = (("default", []), ("hidden", ["--include-hidden"]),
              ("archived", ["--include-archived"]),
              ("both", ["--include-hidden", "--include-archived"]))
# OpenWiz's flags for each P1 view, and which rows it then leaves out.
OPENWIZ_VIEWS = (("default", []), ("hidden", ["--hidden"]), ("archived", ["-a"]),
                 ("both", ["-a", "--hidden"]))
HELP_TARGETS = ([], ["thread"], ["thread", "list"], ["thread", "show"],
                ["thread", "output"], ["thread", "count"], ["thread", "log"],
                ["project"], ["project", "list"], ["machine"], ["machine", "list"],
                ["status"])
PAGE = 200
# thread log (procedures §7.2, §7.3). Phase 1 found, and M2 confirmed in the
# client's code, that `--limit N` keeps the OLDEST N events and `--after-seq S`
# gives the oldest events numbered above S. The last number is therefore found
# by a search over --after-seq (find_last_seq), and later snapshots read only
# the events after the previous snapshot's number (last_after).
LOG_WINDOW = 100      # events per read (--limit 100); room-cli asks the server for at most 100 at a time
SEARCH_BUDGET = 48    # reads per session for the search: enough for about 10^9 events
NEW_PAGES = 10        # windows of new events read before a session counts as unreadable
LOG_CHECK_SESSIONS = 20
SEQ_ARG = re.compile(r"[1-9][0-9]{0,11}")
# Environment variables that M2 found change which client runs (ROOM_CLI
# re-executes another program) or what `--version` prints (BB_APP_VERSION).
CLIENT_HOOKS = ("BB_APP_VERSION", "ROOM_CLI")
# Node's own: NODE_OPTIONS can preload code into the client; NODE_USE_ENV_PROXY
# makes its fetch honour the proxy variables, which could route requests off
# loopback. Both stop, and so does any proxy variable (parent's B F1 diagnosis,
# point 4): traffic must go to the loopback server, or through M3's proxy only.
NODE_HOOKS = ("NODE_OPTIONS", "NODE_USE_ENV_PROXY")
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
ENDPOINT_CHECK = [False]
# The only bracket outcome after which the run goes on. A change in any
# excluded session, the runner's own included, stops the run before the next
# OpenWiz call (excluded_changes_need_attribution): being excluded names a
# possible source, not the cause of each change. A bracket in which nothing
# quiet was compared is incomplete, never quiet.
CONTINUE = ("no_unexplained_change",)
# Brackets whose OpenWiz calls read sessions by id: each must read at least one
# session that was quiet at the bracket's start.
BY_ID = ("ls-l", "show", "inventory")
RUNNER = "the runner's own session"
MAX_EVENT_SESSIONS = 100  # excluded sessions whose new events are read, per bracket
LS_L_PAGE = 100
MISSING = "__missing__"
# The `thread show` keys capture C recorded. Only these are named in the
# report; any other key is compared under "unlisted keys".
SHOW_KEYS = frozenset(
    ["thread.%s" % k for k in (
        "id", "projectId", "providerId", "title", "titleFallback", "status", "visibility",
        "executionTarget", "environmentId", "parentThreadId", "sectionId",
        "sourceThreadId", "originKind", "originPluginId", "archivedAt", "pinnedAt",
        "deletedAt", "lastReadAt", "latestAttentionAt", "createdAt", "updatedAt",
        "activeBackgroundAgentCount", "queuedMessageCount", "canSpawnChild", "purpose",
        "runtime")]
    + ["execution.model", "execution.reasoningLevel", "environment", "pendingTodos"])


class Stop(Exception):
    """A stop rule: the run ends here and the report says why."""


# --------------------------------------------------------------------------
# What may be started


def observer_allowed(argv):
    """The observer reads in procedures.md, section 'Observer reads'."""
    a = list(argv)
    if a == ["--version"]:
        return True
    if a and a[-1] == "--help" and a[:-1] in [list(t) for t in HELP_TARGETS]:
        return True
    if a[:3] == ["thread", "list", "--json"] and a[3:] in [v for _, v in LIST_VIEWS]:
        return True
    if a == ["thread", "count", "--json"]:
        return True
    if (len(a) == 4 and a[0] == "thread" and a[1] in ("show", "output")
            and ID_RE.match(a[2]) and a[3] == "--json"):
        return True
    if (len(a) in (6, 8) and a[:2] == ["thread", "log"] and ID_RE.match(a[2])
            and not a[2].startswith("-") and a[3] == "--json"):
        rest = a[4:]
        if len(rest) == 4 and rest[0] == "--after-seq" and SEQ_ARG.fullmatch(rest[1]):
            rest = rest[2:]
        if (len(rest) == 2 and rest[0] == "--limit" and re.fullmatch(r"[0-9]{1,3}", rest[1])
                and 1 <= int(rest[1]) <= LOG_WINDOW):
            return True
    if a in (["project", "list", "--json", "--include-personal"],
             ["project", "list", "--json", "--include-personal", "--hidden"],
             ["machine", "list", "--json"]):
        return True
    # O9 is recommended declined: status --json only with preflight --endpoint-check.
    return a == ["status", "--json"] and ENDPOINT_CHECK[0]


def openwiz_allowed(argv):
    """OpenWiz's own allowlist (crates/adapters/cloudroom/src/allowlist.rs)."""
    a = list(argv)
    if a == ["--version"] or a == ["machine", "list", "--json"]:
        return True
    if a[:3] == ["thread", "list", "--json"] and a[3:] in [v for _, v in LIST_VIEWS]:
        return True
    if a in (["project", "list", "--json", "--include-personal"],
             ["project", "list", "--json", "--include-personal", "--hidden"]):
        return True
    return (len(a) == 4 and a[0] == "thread" and a[1] in ("show", "output")
            and bool(ID_RE.match(a[2])) and not a[2].startswith("-")
            and a[3] == "--json")


def read_kind(argv):
    """The read's name with ids and numbers removed, for counts and gaps."""
    a = list(argv)
    if (len(a) >= 3 and a[0] == "thread" and a[1] in ("show", "output", "log")
            and not a[2].startswith("-")):
        return " ".join([a[0], a[1]] + [x for x in a[3:] if x.startswith("-")])
    return " ".join(a)


SHIM = '''#!{python}
# OpenWiz ticket-3 shim: logs each call, refuses anything outside OpenWiz's
# allowlist, otherwise becomes the real room-cli (exec, so no extra process).
import json, os, sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, {scripts!r})
from observe import openwiz_allowed
argv = sys.argv[1:]
ok = openwiz_allowed(argv)
entry = {{"t": time.time_ns() // 1000000, "argv": argv, "refused": not ok}}
if ok and os.environ.get("ROOM_SERVER_URL"):
    # Sol N-R1 round 2: this call's own token in its base URL, logged before the
    # call starts, so the proxy credits each request to this call only.
    entry["token"] = os.urandom(16).hex()
    os.environ["ROOM_SERVER_URL"] = os.environ["ROOM_SERVER_URL"].rstrip("/") + "/c/" + entry["token"]
line = json.dumps(entry) + "\\n"
fd = os.open(os.environ["OPENWIZ_SHIM_LOG"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(fd, line.encode())
os.close(fd)
if not ok:
    sys.stderr.write("openwiz ticket-3 shim: refused, not on OpenWiz's allowlist\\n")
    sys.exit(97)
real = os.environ["OPENWIZ_SHIM_REAL"]
if argv[:2] != ["project", "list"]:
    os.execv(real, [real] + argv)
# P6 needs the project ids of OpenWiz's own project-list reads: run it as a
# child, pass its output through unchanged, and keep only the ids.
import subprocess
p = subprocess.run([real] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
sys.stdout.buffer.write(p.stdout)
sys.stdout.buffer.flush()
try:
    ids = sorted(r["id"] for r in json.loads(p.stdout)
                 if isinstance(r, dict) and isinstance(r.get("id"), str))
except Exception:
    ids = None
line = json.dumps({{"t": time.time_ns() // 1000000, "project_ids": ids}}) + "\\n"
fd = os.open(os.environ["OPENWIZ_SHIM_LOG"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(fd, line.encode())
os.close(fd)
sys.exit(p.returncode)
'''


# --------------------------------------------------------------------------
# The run directory and the run's context


def now_ms():
    return time.time_ns() // 1_000_000


def write_private(path, data):
    """Written whole or not at all: a temporary file, then renamed over the
    target (an interrupted save never leaves a partial file)."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f, sort_keys=True)
    os.replace(tmp, path)


def load(path):
    with open(path) as f:
        return json.load(f)


class Ctx:
    def __init__(self, room_cli, run_dir, concurrency=4, timeout=READ_TIMEOUT_S):
        self.room_cli = os.path.abspath(room_cli)
        self.run_dir = os.path.abspath(run_dir)
        self.concurrency = concurrency
        self.timeout = timeout
        self.reads = {}
        self.latency = {}
        self.lock = threading.Lock()
        # Sol N-R1: in a run, every observer call goes through its own proxy,
        # with its own call token (round 2).
        self.obs_proxy, self.obs_env, self.obs_wrap, self.missing = None, None, None, {}
        self.phase = None  # the capture or bracket each observer call belongs to (final round)
        key_path = os.path.join(self.run_dir, "hmac.key")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                self.key = f.read()
        else:
            self.key = os.urandom(32)
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(self.key)

    def mac(self, value):
        """Keyed digest for equality on this machine only. Never reported."""
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self.key, data, hashlib.sha256).hexdigest()

    def room(self, argv, env=None, wrap=None):
        if self.obs_proxy is not None:
            if self.obs_proxy.latched:
                raise Stop("observer M3: " + self.obs_proxy.latched)
            env = env if env is not None else self.obs_env
            wrap = wrap if wrap is not None else self.obs_wrap
        if not observer_allowed(argv):
            raise Stop("observer refused its own read outside OBSERVER_READS: "
                       + " ".join(list(argv)[:2]))
        kind = read_kind(argv)
        token = None
        if self.obs_proxy is not None:
            token = os.urandom(16).hex()
            self.obs_proxy.open_call(token, phase=self.phase, argv=argv)
            env = dict(env, ROOM_SERVER_URL=self.obs_proxy.url + "/c/" + token)
        t0 = time.monotonic()
        try:
            r = subprocess.run(list(wrap or []) + [self.room_cli] + list(argv),
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired:
            raise Stop("observer read timed out after %ss: %s" % (self.timeout, kind))
        finally:
            got = self.obs_proxy.close_call(token) if token else []
        with self.lock:
            self.reads[kind] = self.reads.get(kind, 0) + 1
            self.latency.setdefault(kind, []).append(int((time.monotonic() - t0) * 1000))
        if self.obs_proxy is not None:
            # A call that failed (other than a not-found) is stopped by its caller,
            # under that clearer reason; one that completed needs its own request,
            # among those that carried its token (Sol N-R1 round 2).
            if (r.returncode == 0 or b"HTTP 404" in r.stderr) and \
                    calls_without_requests([(argv, got)]):
                with self.lock:
                    self.missing[kind] = self.missing.get(kind, 0) + 1
                self.obs_proxy.latch("a call without its proxied request (%s)" % kind)
            if self.obs_proxy.latched:
                raise Stop("observer M3: " + self.obs_proxy.latched)
        return r

    def room_json(self, argv, not_found_ok=False):
        r = self.room(argv)
        if r.returncode != 0:
            if not_found_ok and b"HTTP 404" in r.stderr:
                return None
            raise Stop("observer read exited %d: %s" % (r.returncode, read_kind(argv)))
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise Stop("observer read printed no JSON: " + read_kind(argv))

    def save(self, name, data):
        write_private(os.path.join(self.run_dir, name), data)

    def counts(self):
        return {"reads_by_kind": dict(sorted(self.reads.items())),
                "median_ms_by_kind": {k: int(statistics.median(v))
                                      for k, v in sorted(self.latency.items())}}


def make_run_dir(path):
    if os.path.exists(path):
        raise Stop("the run directory already exists; each run needs a new one")
    os.makedirs(path, mode=0o700)
    os.chmod(path, 0o700)


# --------------------------------------------------------------------------
# Reading CloudRoom's own view


def get(d, *path):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return MISSING
        d = d[p]
    return d


def typed(value, kind):
    """The value if it has the type capture C recorded, else MISSING. A null,
    absent or mistyped compared field makes a bracket incomplete, never quiet."""
    if kind is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = isinstance(value, kind)
    return value if ok else MISSING


def list_fields(row):
    activity = get(row, "activity")
    total = (sum(activity.values()) if isinstance(activity, dict) and activity
             and all(typed(v, int) != MISSING for v in activity.values()) else MISSING)
    return {
        "status": typed(get(row, "status"), str),
        "display": typed(get(row, "runtime", "displayStatus"), str),
        "updatedAt": typed(get(row, "updatedAt"), int),
        "lastReadAt": typed(get(row, "lastReadAt"), int),
        "latestAttentionAt": typed(get(row, "latestAttentionAt"), int),
        "queuedWork": typed(get(row, "queuedWork"), str),
        "pending": typed(get(row, "hasPendingInteraction"), bool),
        "activity": total,
        "cloud": get(row, "executionTarget") == "cloud",
        "host": isinstance(get(row, "environmentHostId"), str),
        "archived": get(row, "archivedAt") not in (None, MISSING),
        "hidden": get(row, "visibility") not in ("visible",),
        "visibility_known": get(row, "visibility") in ("visible", "hidden"),
        "project": get(row, "projectId"),
        "parent": get(row, "parentThreadId"),
        "env": isinstance(get(row, "environmentId"), str),
    }


def seqs_of(rows, after):
    """The sequence numbers of one thread log read. MISSING unless every event
    has an integer seq, they ascend, and after --after-seq S all are above S:
    anything else means the read does not behave as M2 and the pre-flight found."""
    seqs = [typed(e.get("seq"), int) if isinstance(e, dict) else MISSING for e in rows]
    if MISSING in seqs or any(b <= a for a, b in zip(seqs, seqs[1:])):
        return MISSING
    if after is not None and seqs and seqs[0] <= after:
        return MISSING
    return seqs


def log_rows(ctx, sid, after=None, limit=LOG_WINDOW):
    """One thread log read: the oldest `limit` events, or the oldest `limit`
    numbered above `after`. None if the session is not found."""
    argv = ["thread", "log", sid, "--json"]
    if after is not None:
        argv += ["--after-seq", str(after)]
    rows = ctx.room_json(argv + ["--limit", str(limit)], not_found_ok=True)
    if rows is not None and not isinstance(rows, list):
        raise Stop("observer read thread log printed no array")
    return rows


def log_seqs(ctx, sid, after=None, limit=LOG_WINDOW):
    if after is not None and after < 1:
        return MISSING  # --after-seq takes 1 or more; numbers below 1 are unsupported
    rows = log_rows(ctx, sid, after, limit)
    return None if rows is None else seqs_of(rows, after)


def find_last_seq(read, budget=SEARCH_BUDGET):
    """The highest event sequence number of one session, and the reads it took.

    `read(after)` gives the numbers of the oldest LOG_WINDOW events (after
    None) or of the oldest LOG_WINDOW numbered above `after`, None when the
    session is not found, or MISSING. A window with fewer than LOG_WINDOW
    events holds the end, so the search gallops --after-seq forward, then
    halves the gap. It gives "gone", None (an empty log) or a number that
    exists; MISSING for a malformed read or when the budget runs out, never a
    guess. Events appended meanwhile can only make the result lower than the
    newest number, never higher, so a later snapshot sees them as a change."""
    reads = 0

    def step(after):
        nonlocal reads
        reads += 1
        got = read(after)
        if got not in (None, MISSING) and got and after is not None and got[0] <= after:
            return MISSING  # not strictly after
        return got

    got = step(None)
    if got is None or got == MISSING:
        return ("gone" if got is None else MISSING), reads
    if len(got) < LOG_WINDOW:
        return (got[-1] if got else None), reads
    lo, hi, gap = got[-1], None, LOG_WINDOW  # an event at lo; none above hi
    while reads < budget:
        if hi is None:
            after = lo + gap
        elif hi - lo <= LOG_WINDOW:
            after = lo
        else:
            after = (lo + hi) // 2
        got = step(after)
        if got is None or got == MISSING:
            return ("gone" if got is None else MISSING), reads
        if not got:
            if after == lo:
                return lo, reads
            hi = after
        elif len(got) < LOG_WINDOW:
            return got[-1], reads
        else:
            lo = got[-1]
            if hi is None:
                gap *= 2
            elif lo == hi:
                return lo, reads
            elif lo > hi:  # events were appended during the search
                hi, gap = None, LOG_WINDOW
    return MISSING, reads


def last_after(read, prev, pages=NEW_PAGES):
    """The highest number, given the previous snapshot's (None: an empty log):
    one read when nothing is new, else pages forward. "gone", or MISSING for a
    malformed read or more than `pages` windows of new events."""
    last = prev
    for _ in range(pages):
        got = read(last)
        if got is None:
            return "gone"
        if got == MISSING or (got and last is not None and got[0] <= last):
            return MISSING
        if got:
            last = got[-1]
        if len(got) < LOG_WINDOW:
            return last
    return MISSING


def detail(ctx, sid, prev=None):
    show = ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
    if show is None:
        return {"gone": True, "log_reads": 0}
    n = [0]

    def read(after):
        n[0] += 1
        return log_seqs(ctx, sid, after)

    # After S0, only the events after the previous snapshot's number are read.
    known = (isinstance(prev, dict) and not prev.get("gone", True)
             and prev.get("last_seq", MISSING) != MISSING)
    last = last_after(read, prev["last_seq"]) if known else find_last_seq(read)[0]
    if last == "gone":
        return {"gone": True, "log_reads": n[0]}
    return {
        "gone": False,
        "qmc": typed(get(show, "thread", "queuedMessageCount"), int),
        "model": get(show, "execution", "model"),
        "effort": get(show, "execution", "reasoningLevel"),
        "last_seq": last,
        "log_reads": n[0],
    }


def snapshot(ctx, name, prev=None):
    snap = {"name": name, "started_ms": now_ms(), "views": {}, "rows": {}}
    for view, flags in LIST_VIEWS:
        rows = ctx.room_json(["thread", "list", "--json"] + flags)
        if not isinstance(rows, list):
            raise Stop("observer thread list printed no array")
        ids = []
        for row in rows:
            sid = row.get("id") if isinstance(row, dict) else None
            if not isinstance(sid, str) or not ID_RE.match(sid):
                snap.setdefault("unreadable", {}).setdefault(view, 0)
                snap["unreadable"][view] += 1
                continue
            ids.append(sid)
            snap["rows"].setdefault(sid, list_fields(row))
        snap["views"][view] = ids
    for key, flags in (("projects", []), ("projects_hidden", ["--hidden"])):
        rows = ctx.room_json(["project", "list", "--json", "--include-personal"] + flags)
        snap[key] = sorted(r["id"] for r in rows
                           if isinstance(r, dict) and isinstance(r.get("id"), str))
    rows = ctx.room_json(["machine", "list", "--json"])
    snap["machines"] = sorted(r["id"] for r in rows
                              if isinstance(r, dict) and isinstance(r.get("id"), str))
    ids = sorted(snap["rows"])
    before = (prev or {}).get("details", {})
    with concurrent.futures.ThreadPoolExecutor(max_workers=ctx.concurrency) as pool:
        details = list(pool.map(lambda s: detail(ctx, s, before.get(s)), ids))
    snap["details"] = dict(zip(ids, details))
    snap["log_reads"] = sum(d.get("log_reads", 0) for d in details)
    snap["ended_ms"] = now_ms()
    ctx.save("snapshot-%s.json" % name, snap)
    return snap


def sample_record(ctx, sid, snap):
    """Per-key digests of a sample's full detail, output and recent events: the
    events numbered above (the snapshot's last number - 20), at most 40."""
    show = ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
    out = ctx.room_json(["thread", "output", sid, "--json"], not_found_ok=True)
    last = snap["details"].get(sid, {}).get("last_seq")
    log = log_rows(ctx, sid, last - 20 if isinstance(last, int) and last > 20 else None, 40)
    rec, unlisted = {}, {}
    if isinstance(show, dict):
        for top, value in show.items():
            if isinstance(value, dict) and top in ("thread", "execution"):
                for k, v in value.items():
                    key = "%s.%s" % (top, k)
                    if key in SHOW_KEYS:
                        rec[key] = ctx.mac(v)
                    else:
                        unlisted[key] = v
            elif top in SHOW_KEYS:
                rec[top] = ctx.mac(value)
            else:
                unlisted[top] = value
        # Keys capture C did not record are compared together, never named.
        rec["unlisted keys"] = ctx.mac(unlisted)
    else:
        rec["show"] = "gone"
    rec["output"] = ctx.mac(out)
    if log is not None and not isinstance(log, list):
        raise Stop("observer thread log printed no array")
    events = [(e.get("seq"), e.get("type"), e.get("createdAt"))
              for e in (log or []) if isinstance(e, dict)]
    rec["log.recent"] = ctx.mac(events)
    return rec


def poll_fields(ctx, sid):
    show = ctx.room_json(["thread", "show", sid, "--json"], not_found_ok=True)
    if show is None:
        return "gone"
    return [get(show, "thread", k) for k in
            ("status", "updatedAt", "lastReadAt", "latestAttentionAt",
             "queuedMessageCount")] + [get(show, "thread", "runtime", "displayStatus")]


class Poller:
    """Polls the samples during OpenWiz's calls, to catch a transient wake."""

    def __init__(self, ctx, samples, interval):
        self.ctx, self.samples, self.interval = ctx, samples, interval
        self.first, self.changes, self.error = {}, [], None
        self.done = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        try:
            while not self.done.is_set():
                for sid in self.samples:
                    v = poll_fields(self.ctx, sid)
                    if sid not in self.first:
                        self.first[sid] = v
                    elif v != self.first[sid]:
                        self.changes.append({"id": sid, "t": now_ms()})
                        self.first[sid] = v
                self.ready.set()
                self.done.wait(self.interval)
        except Stop as e:
            self.error = str(e)
        except Exception as e:  # never let a poller crash look like a quiet poll
            self.error = "poller failed: %s" % type(e).__name__
        finally:
            self.ready.set()

    def __enter__(self):
        # The baseline is taken before OpenWiz's first call.
        self.thread.start()
        self.ready.wait()
        return self

    def __exit__(self, *exc):
        self.done.set()
        self.thread.join()


# --------------------------------------------------------------------------
# Running OpenWiz behind the shim


def run_openwiz(ctx, openwiz, label, args, extra_env=None, wrap=None, proxy=None):
    shim_dir = os.path.join(ctx.run_dir, "shim")
    if not os.path.isdir(shim_dir):
        os.makedirs(shim_dir, mode=0o700)
        scripts = os.path.dirname(os.path.abspath(__file__))
        write_private(os.path.join(shim_dir, "room-cli"),
                      SHIM.format(python=sys.executable, scripts=scripts))
        os.chmod(os.path.join(shim_dir, "room-cli"), 0o700)
    log_path = os.path.join(ctx.run_dir, "shim-%s.log" % label)
    env = dict(os.environ)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    env["OPENWIZ_SHIM_REAL"] = ctx.room_cli
    env["OPENWIZ_SHIM_LOG"] = log_path
    env.update(extra_env or {})
    if proxy is not None:
        env["ROOM_SERVER_URL"] = proxy.url  # the shim adds each call's token
        proxy.open_shim(log_path, phase=label)
    start = now_ms()
    try:
        p = subprocess.run(list(wrap or []) + [openwiz] + list(args), env=env,
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except subprocess.TimeoutExpired:
        raise Stop("openwiz did not finish in 120 s: " + label)
    finally:
        # Every token of this invocation is retired: a late request latches.
        credited = proxy.close_shim() if proxy is not None else {}
    end = now_ms()
    calls, project_ids, per_call = [], [], []
    if os.path.exists(log_path):
        with open(log_path) as f:
            for entry in (json.loads(line) for line in f if line.strip()):
                if "argv" in entry:
                    # The token stays in memory: each call's own requests, for M3.
                    token = entry.pop("token", None)
                    calls.append(entry)
                    per_call.append(credited.get(token, []) if token else [])
                else:
                    project_ids.append(entry["project_ids"])
    # OpenWiz's printed output stays in this process's memory only (RAW); the
    # run record that is saved, even on an error, holds its byte counts.
    RAW[label] = (p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    return {"label": label, "args": list(args), "exit": p.returncode,
            "start": start, "end": end, "calls": calls, "project_ids": project_ids,
            "stdout_bytes": len(p.stdout), "stderr_bytes": len(p.stderr), "_requests": per_call}


RAW = {}


def out_of(run):
    return RAW.get(run["label"], ("", ""))[0]


def err_of(run):
    return RAW.get(run["label"], ("", ""))[1]


def envelope(run):
    try:
        return json.loads(out_of(run))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Comparing snapshots: P8(b) parts 2 and 3


def merged(snap, sid):
    row = dict(snap["rows"].get(sid, {}))
    d = snap["details"].get(sid, {})
    row["qmc"] = d.get("qmc", MISSING)
    row["last_seq"] = d.get("last_seq", MISSING)
    row["model"] = d.get("model", MISSING)
    row["effort"] = d.get("effort", MISSING)
    row["gone"] = d.get("gone", True) or sid not in snap["rows"]
    return row


def not_quiet(row):
    """Why a session counts as already active at a bracket's start, or None."""
    for field in ("status", "display"):
        if row.get(field) not in QUIET:
            return "%s not idle or error" % field
    if row.get("queuedWork") != "none":
        return "queued work"
    if row.get("pending") is not False:
        return "pending interaction"
    if row.get("activity") != 0:
        return "background activity"
    if row.get("qmc") not in (0,):
        return "queued messages"
    return None


def individually_read(runs):
    """Session ids OpenWiz read by id in these runs, with each call's time."""
    out = {}
    for run in runs:
        for call in run["calls"]:
            a = call["argv"]
            if len(a) >= 3 and a[0] == "thread" and a[1] in ("show", "output"):
                out.setdefault(a[2], []).append(call["t"])
    return out


def new_events(ctx, sid, before_seq, after_seq):
    """The events numbered above the before snapshot's last number (at most 50,
    oldest first), up to the after snapshot's."""
    delta = after_seq - (before_seq or 0)
    after = before_seq if isinstance(before_seq, int) and before_seq >= 1 else None
    log = log_rows(ctx, sid, after, 50) or []
    events, seen = [], []
    for e in log:
        if not isinstance(e, dict) or not isinstance(e.get("seq"), int):
            continue
        seen.append(e["seq"])
        if (before_seq is not None and e["seq"] <= before_seq) or e["seq"] > after_seq:
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        events.append({
            "type": label(e.get("type")),
            "initiator": label(data.get("initiator")),
            "source": label(data.get("source")),
            "createdAt": e.get("createdAt") if isinstance(e.get("createdAt"), int) else None,
        })
    more = len(log) >= 50 and bool(seen) and max(seen) < after_seq
    return {"delta": delta, "read": len(events), "more": more, "events": events}


def label(value):
    if value is None:
        return "absent"
    return value if isinstance(value, str) and value in APPROVED_LABELS else "other"


def capture_differences(a, b, recs_a, recs_b):
    """Sol's sweep, finding 1, final round: every field in which two captures
    differ, counted by field name (never an id): the views, project and machine
    lists, every list field and detail field of every session (read counts
    aside), and every sample key."""
    diff = {}

    def add(key):
        diff[key] = diff.get(key, 0) + 1

    for key in ("views", "projects", "projects_hidden", "machines", "unreadable"):
        if a.get(key) != b.get(key):
            add(key)
    for sid in set(a["rows"]) | set(b["rows"]):
        if (sid in a["rows"]) != (sid in b["rows"]):
            add("session listed in only one")
            continue
        for f in set(a["rows"][sid]) | set(b["rows"][sid]):
            if a["rows"][sid].get(f, MISSING) != b["rows"][sid].get(f, MISSING):
                add(f)
        da = {k: v for k, v in a["details"].get(sid, {}).items() if k != "log_reads"}
        db = {k: v for k, v in b["details"].get(sid, {}).items() if k != "log_reads"}
        for f in set(da) | set(db):
            if da.get(f, MISSING) != db.get(f, MISSING):
                add("detail." + f)
    for sid in set(recs_a) | set(recs_b):
        ra, rb = recs_a.get(sid, {}), recs_b.get(sid, {})
        for k in set(ra) | set(rb):
            if ra.get(k) != rb.get(k):
                add("sample." + k)
    return diff


LIST_KEYS = ("views", "projects", "projects_hidden", "machines", "unreadable")


def difference_text(diff):
    """The fields two captures differ in, as words: per field, the number of
    sessions it changed in (lists: just that it changed). Never an id."""
    return ", ".join(("%s changed" % f) if f in LIST_KEYS else ("%s changed in %d sessions" % (f, n))
                     for f, n in sorted(diff.items()))


def bracket(ctx, name, before, after, runs, exclude, samples_before=None,
            samples_after=None, poll=None):
    read_by_id = individually_read(runs)
    ids = sorted(set(before["rows"]) | set(after["rows"]))
    res = {"name": name, "compared": len(ids), "unchanged": 0, "excluded": {},
           "unexplained": [], "events": [], "refused_calls": 0,
           "runs": runs, "before": before["name"], "after": after["name"]}
    res["fields_missing"] = 0
    res["active_read_unchanged"] = 0
    res["excluded_changed"] = []
    res["excluded_events_not_read"] = 0
    res["unreadable_rows"] = sum(sum(s.get("unreadable", {}).values())
                                 for s in (before, after))
    for run in runs:
        res["refused_calls"] += sum(1 for c in run["calls"] if c.get("refused"))
    for sid in ids:
        b, a = merged(before, sid), merged(after, sid)
        # A field the snapshot could not read would make the comparison, or
        # the quiet test, vacuous: the bracket is incomplete, never quiet.
        # So would a session still in thread list whose detail read (thread show,
        # thread log) is unavailable (Sol S9): missing proof, never unchanged.
        no_detail = any(sid in snap["rows"] and snap["details"].get(sid, {}).get("gone", True)
                        for snap in (before, after))
        if no_detail or any(r.get(f, MISSING) == MISSING for r in (b, a) if not r["gone"]
                            for f in COMPARED + QUIET_FIELDS):
            res["fields_missing"] += 1
        changed = [f for f in COMPARED if b.get(f, MISSING) != a.get(f, MISSING)]
        if b["gone"] != a["gone"]:
            changed.append("appeared" if b["gone"] else "disappeared")
        why = None
        if sid in read_by_id:
            # A session OpenWiz read by id is never excluded, not even the
            # runner's own: any change in it is unexplained (procedures §9).
            pass
        elif sid in exclude:
            why = RUNNER
        elif not b["gone"]:
            why = not_quiet(b)
            why = ("already active at bracket start: " + why) if why else None
        if not changed:
            if why is None and sid in read_by_id and not_quiet(b):
                # Already active and read by id: not excluded, but never
                # counted as unchanged, so never evidence.
                res["active_read_unchanged"] += 1
            elif why is None and not no_detail:
                res["unchanged"] += 1
            elif why is not None:
                res["excluded"][why] = res["excluded"].get(why, 0) + 1
            # else: unavailable detail, accounted for by fields_missing alone (Sol S10)
            continue
        if why is not None:
            # Being active is a reason to exclude, not a cause: the change is
            # listed, with its events, until Jake attributes it (never a pass).
            res["excluded"][why] = res["excluded"].get(why, 0) + 1
            res["excluded_changed"].append({"id": sid, "reason": why, "fields": changed})
        else:
            res["unexplained"].append({"id": sid, "fields": changed,
                                       "read_by_openwiz": sid in read_by_id})
        bs, as_ = b.get("last_seq"), a.get("last_seq")
        if isinstance(as_, int) and (not isinstance(bs, int) or as_ > bs):
            if why is not None and len(res["events"]) >= MAX_EVENT_SESSIONS:
                res["excluded_events_not_read"] += 1
                continue
            ev = new_events(ctx, sid, bs if isinstance(bs, int) else None, as_)
            ev.update({"id": sid, "excluded": why, "read_times": read_by_id.get(sid, [])})
            res["events"].append(ev)
    res["samples_changed"] = []
    if samples_before and samples_after:
        for sid, rec in samples_before.items():
            other = samples_after.get(sid, {})
            keys = sorted(k for k in set(rec) | set(other) if rec.get(k) != other.get(k))
            if keys:
                res["samples_changed"].append({"id": sid, "keys": keys})
    res["poll_changes"] = list(poll.changes) if poll else []
    res["poll_error"] = poll.error if poll else None
    problems = (len(res["unexplained"]) + len(res["samples_changed"])
                + len(res["poll_changes"]) + res["refused_calls"])
    if problems:
        res["outcome"] = "unexplained_change"
    elif res["poll_error"]:
        res["outcome"] = "incomplete: " + res["poll_error"]
    elif res["fields_missing"]:
        res["outcome"] = ("incomplete: %d sessions lack a compared field"
                          % res["fields_missing"])
    elif res["unreadable_rows"]:
        res["outcome"] = ("incomplete: %d thread list rows without a readable id"
                          % res["unreadable_rows"])
    elif not ids:
        res["outcome"] = "incomplete: no session to compare"
    elif res["excluded_changed"]:
        res["outcome"] = "excluded_changes_need_attribution"
    elif not res["unchanged"]:
        res["outcome"] = "incomplete: no quiet session to compare"
    elif name in BY_ID and not any(
            sid in read_by_id and not merged(before, sid)["gone"]
            and not not_quiet(merged(before, sid)) for sid in ids):
        res["outcome"] = "incomplete: no quiet session read by id"
    else:
        res["outcome"] = "no_unexplained_change"
    return res


# --------------------------------------------------------------------------
# P1, P2, P3, P4 and P6


def order_key(row, sid):
    u = row.get("updatedAt")
    return (0, -u, sid) if isinstance(u, int) else (1, 0, sid)


def default_order(snap):
    rows = snap["rows"]
    return sorted(snap["views"]["default"], key=lambda s: order_key(rows[s], s))


def expected_view(snap, view):
    """The observer's rows for a view, less those OpenWiz leaves out."""
    hidden_ok = view in ("hidden", "both")
    archived_ok = view in ("archived", "both")
    out = set()
    for sid in snap["views"][view]:
        r = snap["rows"][sid]
        if r["visibility_known"] and r["hidden"] and not hidden_ok:
            continue
        if r["archived"] and not archived_ok:
            continue
        out.add(sid)
    return out


def moved(before, after, sid):
    b, a = before["rows"].get(sid), after["rows"].get(sid)
    return b is None or a is None or b.get("updatedAt") != a.get("updatedAt")


def p1(before, after, runs, count_total):
    out = {}
    for view, _ in OPENWIZ_VIEWS:
        counts_run = runs.get(("count", view))
        env = envelope(counts_run) if counts_run else None
        c = (env or {}).get("coverage", {}).get("counts") or {}
        exp_b, exp_a = expected_view(before, view), expected_view(after, view)
        stable = exp_b & exp_a
        seen, dups = [], 0
        for run in runs.get(("pages", view), []):
            for s in (envelope(run) or {}).get("data", {}).get("sessions", []):
                seen.append(s["id"])
        union = set(seen)
        dups_all = [s for s in union if seen.count(s) > 1]
        dups = sum(1 for s in dups_all if not moved(before, after, s))
        missing = stable - union
        extra = union - (exp_b | exp_a)
        listed_obs = tuple(len(s["views"][view]) + s.get("unreadable", {}).get(view, 0)
                           for s in (before, after))
        identity = (c.get("listed") is not None and c.get("listed") ==
                    c.get("unreadable", 0) + c.get("excluded_hidden", 0)
                    + c.get("excluded_archived", 0) + c.get("matched", 0))
        out[view] = {
            "observer_rows_before": listed_obs[0], "observer_rows_after": listed_obs[1],
            "openwiz_counts": {k: c.get(k) for k in ("listed", "unreadable",
                               "excluded_hidden", "excluded_archived", "matched")},
            "identity_holds": identity,
            "listed_matches_observer": c.get("listed") in listed_obs,
            "pages": len(runs.get(("pages", view), [])),
            "in_both": len(union & (exp_b | exp_a)),
            "duplicates_explained_by_change": len(dups_all) - dups,
            "duplicates_unexplained": dups,
            "only_in_observer_explained_by_change":
                sum(1 for s in missing if moved(before, after, s)),
            "only_in_observer_unexplained":
                sum(1 for s in missing if not moved(before, after, s)),
            "only_in_openwiz": len(extra),
            "changed_between_bracket_reads": len(
                (exp_b ^ exp_a) | {s for s in stable if moved(before, after, s)}),
        }
        r = out[view]
        r["outcome"] = ("consistent" if env and identity and r["listed_matches_observer"]
                        and not dups and not r["only_in_observer_unexplained"]
                        and not extra else "inconsistent")
    out["thread_count"] = {
        "total": count_total,
        "matches_default_view": count_total in (len(before["views"]["default"]),
                                                len(after["views"]["default"])),
    }
    if not out["thread_count"]["matches_default_view"]:
        out["thread_count"]["outcome"] = "inconsistent"
    return out


def has_reason(why):
    """An unknown's reason: a non-empty string (Sol's sweep, finding 6 round 2)."""
    return isinstance(why, str) and why.strip() != ""


def fact(f):
    if isinstance(f, dict) and "known" in f:
        return ("known", f["known"])
    return ("unknown", f.get("unknown") if isinstance(f, dict) else None)


def age_class(kind, up, akind, age, snap_at):
    """Sol's sweep, finding 5: every known update time needs its age, exactly
    snapshot_at minus the update time, as OpenWiz computes it. Accounted for
    explicitly: an update time in the future gives a negative age (its own
    count); an age that does not fit OpenWiz's 64-bit integer is unknown with
    OpenWiz's exact reason. An unknown update time has no known age."""
    if kind != "known":
        if akind == "known":
            return "age_without_update"
        return "age_unknown_with_update" if has_reason(age) else "age_missing"
    if not isinstance(up, int) or isinstance(up, bool) or not isinstance(snap_at, int):
        return "age_inconsistent"
    want = snap_at - up
    if akind == "known":
        if not isinstance(age, int) or isinstance(age, bool) or age != want:
            return "age_inconsistent"
        return "age_future" if want < 0 else "age_consistent"
    if not -2 ** 63 <= want < 2 ** 63 and \
            age == "the update time %d is too far from the snapshot to give an age" % up:
        return "age_unavailable"
    return "age_missing"


def p2_p3(before, after, runs):
    p2 = {"runs": 0, "snapshot_in_run_window": 0, "version_tested": 0,
          "openwiz_rows": 0, "rows_not_in_observer": 0, "rows": 0, "updated_equal": 0, "updated_differs_changed": 0,
          "updated_differs_unexplained": 0, "updated_unknown": 0,
          "age_consistent": 0, "age_future": 0, "age_unavailable": 0, "age_inconsistent": 0,
          "age_missing": 0, "age_without_update": 0, "age_unknown_with_update": 0}
    fields = ("status", "parent", "updatedAt", "model", "effort")
    p3 = {f: {"known_equal": 0, "known_differs_changed": 0, "known_differs_unexplained": 0,
              "unknown_where_raw_lacks_it": 0, "unknown_where_raw_has_it": 0,
              "unknown_without_reason": 0,
              "known_where_raw_lacks_it": 0, "unknown_by_design": 0} for f in fields}
    for run in runs:
        env = envelope(run)
        if not env:
            continue
        p2["runs"] += 1
        snap_at = env.get("freshness", {}).get("snapshot_at")
        if isinstance(snap_at, int) and run["start"] <= snap_at <= run["end"]:
            p2["snapshot_in_run_window"] += 1
        src = env.get("source", {})
        if (fact(src.get("version")) == ("known", TESTED_VERSION)
                and src.get("version_tested") is True
                and src.get("tested_version") == TESTED_VERSION):
            p2["version_tested"] += 1
        long_listing = "-l" in run["args"]
        for s in env.get("data", {}).get("sessions", []):
            sid = s["id"]
            p2["openwiz_rows"] += 1
            raws = [r for r in (merged(before, sid), merged(after, sid)) if not r["gone"]]
            if not raws:
                p2["rows_not_in_observer"] += 1  # never skipped silently
                continue
            changed = moved(before, after, sid)
            p2["rows"] += 1
            kind, up = fact(s.get("updated_at"))
            if kind == "unknown":
                p2["updated_unknown"] += 1
            elif any(up == r.get("updatedAt") for r in raws):
                p2["updated_equal"] += 1
            else:
                p2["updated_differs_changed" if changed
                   else "updated_differs_unexplained"] += 1
            akind, age = fact(s.get("age_ms"))
            p2[age_class(kind, up, akind, age, snap_at)] += 1
            conf = s.get("reported_configuration", {})
            ours = {"status": fact(s.get("status")), "parent": fact(s.get("parent")),
                    "updatedAt": fact(s.get("updated_at")),
                    "model": fact(conf.get("model")), "effort": fact(conf.get("effort"))}
            for f in fields:
                k, v = ours[f]
                # Sol's sweep, finding 6 round 2: an unknown needs its reason, a
                # non-empty string (model and effort outside `ls -l` may be absent).
                present = f not in ("model", "effort") or long_listing or conf.get(f) is not None
                if k == "unknown" and present and not has_reason(v):
                    p3[f]["unknown_without_reason"] += 1
                raw = [r.get(f, MISSING) for r in raws]
                has = [x for x in raw if x is not MISSING and x != MISSING
                       and (x is not None or f == "parent")]
                if f in ("model", "effort") and not long_listing:
                    p3[f]["unknown_by_design" if k == "unknown"
                          else "known_where_raw_lacks_it"] += 1
                    continue
                if k == "unknown":
                    p3[f]["unknown_where_raw_has_it" if has
                          else "unknown_where_raw_lacks_it"] += 1
                elif not has:
                    p3[f]["known_where_raw_lacks_it"] += 1
                elif v in has:
                    p3[f]["known_equal"] += 1
                else:
                    p3[f]["known_differs_changed" if changed
                          else "known_differs_unexplained"] += 1
    p2["outcome"] = ("consistent" if p2["runs"] and p2["rows"]
                     and p2["rows"] == p2["openwiz_rows"]
                     and p2["snapshot_in_run_window"] == p2["runs"]
                     and p2["version_tested"] == p2["runs"]
                     and not p2["updated_differs_unexplained"]
                     and not p2["age_inconsistent"] and not p2["age_missing"]
                     and not p2["age_without_update"] else "inconsistent")
    bad = sum(p3[f][k] for f in fields for k in
              ("known_differs_unexplained", "unknown_where_raw_has_it",
               "known_where_raw_lacks_it", "unknown_without_reason"))
    p3["outcome"] = ("consistent" if p2["runs"] and p2["rows"]
                     and not p2["rows_not_in_observer"] and not bad else "inconsistent")
    return p2, p3


def _unsafe_for_terminal(c):
    o = ord(c)
    return (unicodedata.category(c) == "Cc" or c in "\u00ad\u061c\u180e\ufeff"
            or 0x200B <= o <= 0x200F or 0x2028 <= o <= 0x202E or 0x2060 <= o <= 0x206F
            or 0xFFF9 <= o <= 0xFFFB)


def clean_text(text):
    """OpenWiz's one-line `clean` (crates/cli): each unsafe character becomes
    U+FFFD, or `?` where U+FFFD would take more bytes."""
    return "".join(("\ufffd" if len(c.encode("utf-8", "surrogatepass")) >= 3 else "?")
                   if _unsafe_for_terminal(c) else c for c in text)


def text_fact(f, known):
    """A fact as `ls -l` prints it: known(value), or `unknown (reason)`; None if
    the JSON value has no printable form (a mismatch)."""
    if isinstance(f, dict) and set(f) == {"known"}:
        return known(f["known"])
    if isinstance(f, dict) and set(f) == {"unknown"} and has_reason(f["unknown"]):
        return "unknown (%s)" % clean_text(f["unknown"])
    return None


def text_age(ms):
    """OpenWiz's `age`: the whole number of the largest unit it reaches."""
    sign, secs = ("-" if ms < 0 else ""), abs(ms) // 1000
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return "%s%d%s" % (sign, secs // size, unit)
    return "%s%ds" % (sign, secs)


def _string(v):
    return clean_text(v) if isinstance(v, str) else None


def _location(v):
    if v == {"kind": "cloud"}:
        return "cloud"
    if isinstance(v, dict) and v.get("kind") == "local" and set(v) == {"kind", "machine"}:
        machine = text_fact(v["machine"], _string)
        return None if machine is None else "local on " + machine
    return None


def row_prefix(s):
    """The start of a session's `ls -l` row, rendered from its JSON, field by
    field, every value included (Sol's sweep, finding 6)."""
    parts = [text_fact(s.get("status"), _string),
             text_fact(s.get("age_ms"), lambda v: text_age(v) if isinstance(v, int)
                       and not isinstance(v, bool) else None),
             text_fact(s.get("location"), _location),
             text_fact(s.get("parent"), lambda v: "none" if v is None else _string(v))]
    if None in parts or not isinstance(s.get("id"), str):
        return None
    return "%s · status %s · age %s · location %s · parent %s" % ((clean_text(s["id"]),) + tuple(parts))


def p3_text(text_run, json_run):
    """`ls -l` text against `ls -l --json` (Sol's sweep, finding 6): each row's
    status, age, location and parent are exactly what the JSON gives, every
    field present with its value, known values as printed, unknowns as
    `unknown (<the JSON's reason>)`."""
    env = envelope(json_run) or {}
    rows = {s["id"]: s for s in env.get("data", {}).get("sessions", [])}
    res = {"rows_matched": 0, "agree": 0, "disagree": 0, "text_rows_not_in_json": 0}
    seen = set()
    for line in out_of(text_run).splitlines():
        if not line.startswith("  "):
            continue
        parts = line.strip().split(" · ")
        sid = parts[0]
        if not ID_RE.match(sid) or len(parts) < 5:
            continue
        if sid not in rows:
            res["text_rows_not_in_json"] += 1
            continue
        if sid in seen:
            res["text_rows_duplicated"] = res.get("text_rows_duplicated", 0) + 1
            continue
        seen.add(sid)
        res["rows_matched"] += 1
        want = row_prefix(rows[sid])
        body = line[2:]
        ok = want is not None and (body == want or body.startswith(want + " · "))
        res["agree" if ok else "disagree"] += 1
    res["json_rows_not_in_text"] = len(set(rows) - seen)
    res.setdefault("text_rows_duplicated", 0)
    whole = (not res["text_rows_not_in_json"] and not res["json_rows_not_in_text"]
             and not res["text_rows_duplicated"])
    res["outcome"] = ("consistent" if res["rows_matched"] and whole and not res["disagree"]
                      else "inconsistent" if res["disagree"] or not whole
                      else "incomplete: no row in both runs")
    return res


def p4(run, missing_id):
    calls = [c["argv"] for c in run["calls"]]
    expected = [["--version"], ["thread", "show", missing_id, "--json"]]
    res = {"exit": run["exit"], "stdout_empty": out_of(run) == "",
           # Sol's sweep, finding 7: exactly OpenWiz's line for the requested id, with
           # its one newline (writeln!), nothing else.
           "stderr_is_one_not_found_line":
               err_of(run) == "openwiz: session %s not found\n" % clean_text(missing_id),
           "reads": [read_kind(a) for a in calls],
           "reads_exactly_version_then_thread_show": calls == expected}
    res["outcome"] = ("consistent" if res["exit"] == 3 and res["stdout_empty"]
                      and res["stderr_is_one_not_found_line"]
                      and res["reads_exactly_version_then_thread_show"] else "inconsistent")
    return res


UNGROUPED = (("not_in_project_list", re.compile(
                r"^project (\S+) is not in the project list read in this run$")),
             ("project_list_failed", re.compile(r"^project (\S+) cannot be verified: .+$")),
             ("project_unknown", re.compile(r"^project unknown \((.+)\)$")))


def p6(before, after, runs):
    """Grouping against the project ids of OpenWiz's own project-list reads in
    the same run (captured by the shim), and, as a cross-check, the observer's."""
    res = {"runs": 0, "runs_without_own_project_list": 0,
           "grouped": 0, "grouped_in_same_run_list": 0, "grouped_not_in_same_run_list": 0,
           "grouped_not_in_observer_lists": 0, "ungrouped": {},
           "ungrouped_without_reason": 0, "not_in_list_but_same_run_list_has_it": 0,
           "grouped_under_another_project": 0, "project_assignment_unresolved": 0,
           "ungrouped_reason_unsupported": {},
           "project_lists_changed_in_bracket": (before["projects"] != after["projects"]
                                                or before["projects_hidden"]
                                                != after["projects_hidden"])}
    for run in runs:
        env = envelope(run)
        if not env:
            continue
        res["runs"] += 1
        lists = run.get("project_ids") or []
        if not lists or any(x is None for x in lists):
            res["runs_without_own_project_list"] += 1
            continue
        own = set().union(*[set(x) for x in lists])
        observer = set(before["projects"]) & set(after["projects"])
        if "--hidden" in run["args"]:
            observer |= set(before["projects_hidden"]) & set(after["projects_hidden"])
        for s in env.get("data", {}).get("sessions", []):
            g = s.get("group", {})
            # The session's own project, from CloudRoom's view around the run.
            pb = before["rows"].get(s["id"], {}).get("project", MISSING)
            pa = after["rows"].get(s["id"], {}).get("project", MISSING)
            source = pb if pb == pa and isinstance(pb, str) and pb != MISSING else None
            if g.get("kind") == "project":
                res["grouped"] += 1
                if source is None:
                    res["project_assignment_unresolved"] += 1
                elif g.get("id") != source:
                    res["grouped_under_another_project"] += 1
                res["grouped_in_same_run_list" if g.get("id") in own
                    else "grouped_not_in_same_run_list"] += 1
                if g.get("id") not in observer:
                    res["grouped_not_in_observer_lists"] += 1
                continue
            reason = g.get("reason") or ""
            if not reason.strip():
                res["ungrouped_without_reason"] += 1
            m = next(((c, rx.match(reason)) for c, rx in UNGROUPED if rx.match(reason)), ("other", None))
            cls = m[0]
            res["ungrouped"][cls] = res["ungrouped"].get(cls, 0) + 1
            raw = before["rows"].get(s["id"], {}).get("project")
            if cls == "not_in_project_list" and raw in own:
                res["not_in_list_but_same_run_list_has_it"] += 1
            # Sol's sweep, finding 8: each reason's premise, from the session's
            # own project id around the run and this invocation's own project list.
            if pb != pa:
                res["project_assignment_unresolved"] += 1
            known_id = isinstance(pb, str) and pb != MISSING
            supported = {
                # the reader could not know the id: none was reported as a string
                "project_unknown": not known_id,
                # its own id, absent from this invocation's own project list
                "not_in_project_list": known_id and m[1] is not None and m[1].group(1) == pb
                                       and pb not in own,
                # only after a failed project list, and such a run is not counted here
                "project_list_failed": False,
            }.get(cls, False)
            if not supported:
                res["ungrouped_reason_unsupported"][cls] = \
                    res["ungrouped_reason_unsupported"].get(cls, 0) + 1
    res["outcome"] = ("consistent" if res["runs"] and not res["runs_without_own_project_list"]
                      and res["grouped"] + sum(res["ungrouped"].values())
                      and not res["grouped_not_in_same_run_list"]
                      and not res["grouped_under_another_project"]
                      and not res["project_assignment_unresolved"]
                      and not res["ungrouped_without_reason"]
                      and not res["not_in_list_but_same_run_list_has_it"]
                      and not res["ungrouped_reason_unsupported"]
                      and "other" not in res["ungrouped"] else "inconsistent")
    return res


# --------------------------------------------------------------------------
# M3: request observation through a loopback logging proxy (procedures §7.1)

# The static route segments of room-cli 0.43.1's client (M2's route table). A
# path segment is kept only if it is one of these; anything else becomes :id,
# so a template can hold no id, name or value.
ROUTE_WORDS = frozenset("""
api v1 threads events wait count running output timeline turn-summary-details
default-execution-options child-summary conversation-outline read unread open send
retry stop compact context clear plan cancel goal tabs thread-storage files location
paths unarchive unpin pin pin-order move pane-action prompt-history queued-messages
order interactions resolve respond archive-all edit-message fork plugin-metadata
resolve-mentions search thread-sections sidebar-bootstrap environments
archive-threads actions diff branches file patch pull-request status system
execution-options restart environment-providers machine-providers providers
installable state config reload cli-skills install attention usage-limits version
hosts enrollment-command join-codes directory clone-default-path provider-clis
exist pick-folder resume retry-cleanup retry-update reconcile suspend projects
attachments copy content commands skills sources settings themes appearance
preferences ui machine-environment experiments general keyboard terminals close
input resize cloudroom workspace teleport share retry-start retry-copy open-file
import bb sessions export bug-reports vm run mcp sign-in logout mac-access previews
check plugins plugin marketplaces list write mkdir remove
""".split())
# Words that name an effect (procedures §7.1), matched per hyphenated word.
EFFECT_WORDS = frozenset("""
read unread seen ack mark wake resume start send message messages queue queued
open retry stop archive unarchive pin unpin move fork compact clear cancel respond
resolve markread wakeup touch
""".split())
# What M2 found each read asks the server for (method, route template), from
# room-cli 0.43.1's own code on the Mac, narrowed by hand to the flags OpenWiz and
# the observer use (procedures §7.1's table). Conditional paths are included:
# thread show reads the environment only if the session has one, the cloud status
# only for a cloud session, the default execution options only for a local one,
# and the output only for a session in error. Left out on purpose, as the
# record's routes these flags never take: thread show's environments/:id/diff and
# /status (only --git-diff, --work-status), thread log's /timeline (only the text
# formats), thread list's /projects (only the table output). M2_ROUTES is context
# per read; what the proxy forwards at all is FORWARD_ROUTES below, and a request
# to any other route is blocked (403) and stops the step (Jake: fail closed).
M2_ROUTES = {
    "--version": set(),
    "thread list --json": {("GET", "/api/v1/threads")},
    "project list --json": {("GET", "/api/v1/projects")},
    "machine list --json": {("GET", "/api/v1/hosts")},
    "thread show --json": {("GET", "/api/v1/threads/:id"),
                           ("GET", "/api/v1/environments/:id/pull-request"),
                           ("GET", "/api/v1/environments/:id"),
                           ("GET", "/api/v1/system/environment-providers"),
                           ("GET", "/api/v1/threads/:id/timeline"),
                           ("GET", "/api/v1/cloudroom/threads/:id"),
                           ("GET", "/api/v1/threads/:id/default-execution-options"),
                           ("GET", "/api/v1/threads/:id/output")},
    "thread output --json": {("GET", "/api/v1/threads/:id/output")},
    "thread count --json": {("GET", "/api/v1/threads/count")},
    "thread log --json": {("GET", "/api/v1/threads/:id/events")},
}
HOP_HEADERS = frozenset(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                         "te", "trailer", "trailers", "transfer-encoding", "upgrade", "host",
                         "content-length"])


def route_template(path):
    """The route template of a request path: static words kept, every other
    segment :id. The query is never part of it."""
    if not path.startswith("/"):
        path = urllib.parse.urlsplit(path).path
    segs = [x for x in path.split("?", 1)[0].split("/") if x]
    return "/" + "/".join(x if x in ROUTE_WORDS else ":id" for x in segs)


def decoded_segments(path):
    """The path's segments after decoding the WHOLE path (so `%2F` splits and
    `%3F` cannot hide a query), the query cut first on the raw `?`."""
    if not path.startswith("/"):
        path = urllib.parse.urlsplit(path).path
    return urllib.parse.unquote(path.split("?", 1)[0]).split("/")[1:]


def write_like_raw(method, path):
    """Whether a request is write-like, decided on its method and decoded path,
    before templating (Jake's B F1 rounds): a method other than GET or HEAD, or
    an effect word in any segment. Words are the parts of a segment between
    non-alphanumeric characters or at a camelCase step (F3), so `wake;x=1`,
    `wake#x` and `mark_seen` hold their effect word, while an id such as
    thr_syn_9pin2k does not hold "pin". An extra layer under FORWARD_ROUTES."""
    if method not in ("GET", "HEAD"):
        return True
    words = set()
    for seg in decoded_segments(path):
        seg = re.sub(r"([a-z])([A-Z])", r"\1 \2", seg)
        words |= {w.lower() for w in re.split(r"[^A-Za-z0-9]+", seg) if w}
    return bool(words & EFFECT_WORDS)


# The ONLY requests the M3 proxy forwards (Jake's "fail closed" decision on B F1,
# 2026-10-26, made exact by his "canonical only" decision, 2026-10-27): a request
# already in exact canonical form, forwarded as exactly the bytes checked. No
# decoding happens, so what is checked is what is sent.
#
# Each entry: (route template, the pattern of its :id slot, the query names it
# may carry with the exact shape of each value). Hand-reviewed; every template is
# a route procedures §7.1's table (M2's route table, narrowed to the flags OpenWiz
# and the observer use) lists for an allowlisted or approved observer read; the
# self-test checks the templates equal M2_ROUTES' union. The query names and
# values are the ones the client's code builds for those flags (M2, the builder's
# reading on the Mac, 2026-10-25): thread list sends archived=false unless
# --include-archived, and includeHidden=true with --include-hidden; project list
# includePersonal=true, and hidden=true with --hidden; machine list
# includeCreating=true; thread log limit=<n>, and afterSeq=<n> with --after-seq;
# thread show's to-do summary summaryOnly=true; the rest no query.
#
# Id prefixes. THREAD_ID: room-cli 0.43.1's launcher rewrites an `@thread:`
# mention only before `thr_[A-Za-z0-9_-]+` (M2, the builder's reading of the
# client's code on the Mac, 2026-10-25), and every thread id the captures and the
# fixtures hold has it. ENV_ID: the `env_` prefix is this repository's convention
# (the fixtures, repo-scan.sh); no capture recorded an environment id's value, so
# it is an assumption: if wrong, every environment read is refused and the step
# stops (fail closed), never forwarded.
THREAD_ID = r"thr_[A-Za-z0-9_-]{1,124}"
ENV_ID = r"env_[A-Za-z0-9_-]{1,124}"
_BOOL = r"true|false"
FORWARD_ROUTES = (
    ("/api/v1/threads", None, {"archived": _BOOL, "includeHidden": _BOOL}),            # thread list --json (O3; OpenWiz)
    ("/api/v1/projects", None, {"includePersonal": _BOOL, "hidden": _BOOL}),           # project list --json --include-personal [--hidden] (O5; OpenWiz)
    ("/api/v1/hosts", None, {"includeCreating": _BOOL}),                               # machine list --json (O5; OpenWiz)
    ("/api/v1/threads/:id", THREAD_ID, {}),                                            # thread show <id> --json: the session (O6; OpenWiz)
    ("/api/v1/environments/:id", ENV_ID, {}),                                          # thread show: its environment, if it has one
    ("/api/v1/environments/:id/pull-request", ENV_ID, {}),                             # thread show: its pull request
    ("/api/v1/system/environment-providers", None, {}),                                # thread show: its environment's provider
    ("/api/v1/threads/:id/timeline", THREAD_ID, {"summaryOnly": r"true"}),             # thread show: its to-do summary
    ("/api/v1/cloudroom/threads/:id", THREAD_ID, {}),                                  # thread show: a cloud session's status
    ("/api/v1/threads/:id/default-execution-options", THREAD_ID, {}),                  # thread show: a local session's options
    ("/api/v1/threads/:id/output", THREAD_ID, {}),                                     # thread output <id> --json (O8; OpenWiz); show in error
    ("/api/v1/threads/count", None, {}),                                               # thread count --json (observer, O4)
    ("/api/v1/threads/:id/events", THREAD_ID, {"limit": r"[0-9]{1,4}",
                                               "afterSeq": r"[0-9]{1,12}"}),           # thread log <id> --json [--after-seq] (observer, O7, O12)
)
# Sol N-R1: two proxies, two lists. OpenWiz's own reads never request thread
# count or thread log; the observer's reads (O3-O8, O12) need all 13 routes.
OPENWIZ_ROUTES = tuple(e for e in FORWARD_ROUTES
                       if e[0] not in ("/api/v1/threads/count", "/api/v1/threads/:id/events"))
OBSERVER_ROUTES = FORWARD_ROUTES
CANONICAL_PATH = re.compile(r"/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")
QUERY_PAIR = re.compile(r"([A-Za-z]+)=([A-Za-z0-9_-]+)")


# URL-rewrite headers some servers honour (F7): refused, so the route served is
# the one checked.
REWRITE_HEADER = re.compile(r"x-(original|rewrite|forwarded|envoy-original)-(url|uri|path|prefix)")


def forward_refusal(method, target, headers=(), raw_target=None, routes=FORWARD_ROUTES):
    """Why the proxy must refuse this request, or None if it may forward it as
    is. Canonical only: GET or HEAD; an origin-form target in plain ASCII
    (no %, ;, #, \\, no empty, . or .. segment); a fully anchored match of one
    FORWARD_ROUTES template, each :id with its prefix; only that route's query
    names, each once, with its exact value shape; no method-override header;
    and not write-like (an extra layer)."""
    if method not in ("GET", "HEAD"):
        return "method"
    # F3: the target as it came on the request line, before Python's server
    # rewrote it (a leading // becomes /), must be the one checked.
    if raw_target is not None and raw_target != target:
        return "target rewritten before the check"
    for name, value in headers:
        low = name.lower()
        if "method" in low:
            return "method-override header"
        if REWRITE_HEADER.fullmatch(low):
            return "URL-rewrite header"
        # F1: a GET or HEAD carries no body: no Transfer-Encoding, no Content-Length above 0.
        if low == "transfer-encoding" or (low == "content-length" and value.strip() != "0"):
            return "request body"
    path, sep, query = target.partition("?")
    if not CANONICAL_PATH.fullmatch(path):
        return "target not in canonical origin form"
    segs = path.split("/")[1:]
    if any(x in (".", "..") for x in segs):
        return "dot segment"
    for template, id_pattern, allowed in routes:
        parts = template.split("/")[1:]
        if len(parts) == len(segs) and all(
                re.fullmatch(id_pattern, x) if p == ":id" else x == p for p, x in zip(parts, segs)):
            break
    else:
        return "route not on the forward list"
    if sep:
        names = []
        for pair in query.split("&"):
            m = QUERY_PAIR.fullmatch(pair)
            if not m or m.group(1) not in allowed or not re.fullmatch(allowed[m.group(1)], m.group(2)):
                return "query not in its canonical form"
            names.append(m.group(1))
        if len(names) != len(set(names)):
            return "query not in its canonical form"
    if write_like_raw(method, target):
        return "write-like"
    return None


def forward_ok(method, target, headers=(), routes=FORWARD_ROUTES):
    return forward_refusal(method, target, headers, routes=routes) is None


# The route each read always requests first (M2), to check per call that every
# call reached the proxy (Jake's round, R2). By-id reads must carry their own id.
ALWAYS_ROUTE = {
    "thread list --json": ("GET", "/api/v1/threads"),
    "project list --json": ("GET", "/api/v1/projects"),
    "machine list --json": ("GET", "/api/v1/hosts"),
    "thread count --json": ("GET", "/api/v1/threads/count"),
    "thread show --json": ("GET", "/api/v1/threads/:id"),
    "thread output --json": ("GET", "/api/v1/threads/:id/output"),
    "thread log --json": ("GET", "/api/v1/threads/:id/events"),
}


def always_route(kind):
    for key, route in ALWAYS_ROUTE.items():
        if kind == key or kind.startswith(key + " "):
            return route
    return None


def calls_without_requests(calls):
    """{read kind: number of calls} that should have reached the server but have
    no proxied request of their own. calls: (argv, the (method, route, ids) of
    the requests that carried that call's token). Each call is checked against
    its own requests only (Sol N-R1 round 2): its always-route, with its own id
    for a by-id read. Another call's surplus request never counts."""
    missing = {}
    for argv, got in calls:
        kind = read_kind(argv)
        route = always_route(kind)
        if route is None:
            continue  # --version and help make no request by design
        sid = (argv[2] if len(argv) >= 3 and argv[0] == "thread"
               and argv[1] in ("show", "output", "log") else None)
        if not any((m, r) == route and (sid is None or sid in ids) for m, r, ids in got):
            missing[kind] = missing.get(kind, 0) + 1
    return missing


# Sol N-R1 round 2: each room-cli call's base URL is the proxy's URL plus
# /c/<its own token> (32 lowercase hex). The prefix must be exactly this; the
# rest of the target is what the canonical checks see and what is forwarded.
CALL_TOKEN = re.compile(r"/c/([0-9a-f]{32})(/.*)", re.S)


def split_call_token(target):
    """(token, the target without the prefix), or (None, target) if the target
    does not start with exactly /c/<token>/."""
    m = CALL_TOKEN.fullmatch(target)
    return (m.group(1), m.group(2)) if m else (None, target)


def m2_routes(kind):
    if kind.endswith("--help"):
        return set()
    for key, routes in M2_ROUTES.items():
        if kind == key or kind.startswith(key + " "):
            return routes
    return set()


# Sol's sweep, finding 1, final round: each call's planned read. Every route of
# its read kind (M2) may be used once per call, except a thread log's events page
# (the client pages once when 100 or more events remain) and an environment
# (thread show reads it twice, as M2 shows); a by-id read's thread ids must all
# be its own session's. Anything else is unplanned, or a duplicate.
PLAN_LIMITS = {("GET", "/api/v1/threads/:id/events"): 2, ("GET", "/api/v1/environments/:id"): 2}


def call_plan(argv, phase):
    a = list(argv)
    sid = a[2] if len(a) >= 3 and a[0] == "thread" and a[1] in ("show", "output", "log") else None
    return {"phase": phase, "routes": m2_routes(read_kind(a)), "sid": sid}


def plan_refusal(plan, used, method, route, path):
    """Why a request breaks its call's plan, or None. used: the call's requests
    already dispatched, as (method, route, ids)."""
    segs = path.split("?", 1)[0].split("/")
    thread_ids = {segs[i] for i in range(1, len(segs))
                  if segs[i - 1] == "threads" and segs[i] not in ROUTE_WORDS}
    if (method, route) not in plan["routes"] or not thread_ids <= ({plan["sid"]} if plan["sid"] else set()):
        return "an unplanned request outside its call's planned read"
    if sum(1 for m, r, _ in used if (m, r) == (method, route)) >= PLAN_LIMITS.get((method, route), 1):
        return "a duplicate request beyond its call's planned read"
    return None


def m2_unlisted(kind, requests):
    """The requests M2 does not list for this read."""
    allowed = m2_routes(kind)
    return [q for q in requests if (q["method"], q["route"]) not in allowed]


def loopback_upstream(url):
    """(host, port) of a loopback http URL with a port and no path; else Stop."""
    m = re.fullmatch(r"http:/{2}(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})/?", url.strip())
    if not m or not 1 <= int(m.group(2)) <= 65535:
        raise Stop("the upstream is not loopback http with a port: the proxy forwards only to "
                   "the local server (decision D2)")
    return m.group(1).strip("[]"), int(m.group(2))


class _ProxyServer(http.server.ThreadingHTTPServer):
    # Sol T3 and the sweep (findings 1, 4): every accepted connection is tracked
    # from accept to close, so the run can wait until none is open (quiescence,
    # drain), with a deadline after which they are cancelled. The handler threads
    # are daemons only so a cancelled one can never keep the process alive.
    daemon_threads = True
    block_on_close = False

    def process_request(self, request, client_address):
        with self.proxy.gate:
            self.proxy.active[request] = None  # registered before its thread starts
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._done(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._done(request)

    def _done(self, request):
        with self.proxy.gate:
            self.proxy.active.pop(request, None)
            self.proxy.idle.notify_all()

    def handle_error(self, request, client_address):
        # Never print a traceback: an exception's text could hold a header value.
        with self.proxy.lock:
            self.proxy.errors += 1
        self.proxy.latch("a proxy handler error")  # Sol N-R2


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = READ_TIMEOUT_S  # an idle connection cannot hold the drain open

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.forward
        raise AttributeError(name)

    def log_message(self, *args):
        pass  # the default would print the request line, query values included

    def forward(self):
        proxy = self.server.proxy
        method = self.command if self.command in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE",
                                                  "OPTIONS") else "<other>"
        # Classified on the raw path first; only the template is kept (F1). The
        # raw path's other segments (ids) are held in memory for the per-call
        # check (R2), never logged or saved.
        # Canonical only (Jake, 2026-10-27): checked on the raw request target and
        # headers, and the very same target is what is forwarded below.
        line = self.raw_requestline.decode("latin-1").rstrip("\r\n").split(" ")
        raw_target = line[1] if len(line) == 3 else ""
        # Sol N-R1 round 2: the call token comes off first, then every check runs
        # on the rest, which is all that is forwarded. A missing, unknown or
        # reused token refuses the request and latches.
        token, path = split_call_token(self.path)
        _, raw_rest = split_call_token(raw_target)
        write = write_like_raw(method, path)
        h = self.headers
        why = proxy.token_refusal(token, method, route_template(path), path)
        # F3: a request line Python's server rewrote (raw != self.path) never
        # matches, as the whole raw target then differs from the checked one.
        blocked = why is not None or forward_refusal(
            self.command, path, list(h.items()), raw_rest if raw_target == self.path else raw_target,
            routes=proxy.routes) is not None
        if h.get("Upgrade") or "upgrade" in h.get("Connection", "").lower():
            with proxy.lock:
                proxy.upgrades += 1
            proxy.latch("an upgrade request")  # Sol N-R2
            blocked = True
        self.close_connection = True
        resp = data = None
        if not blocked:
            if proxy._pause_before_dispatch:
                proxy._pause_before_dispatch()  # test-only: forces the interleaving
            target = path  # exactly the bytes forward_refusal checked
            dropped = HOP_HEADERS | {x.strip().lower() for x in h.get("Connection", "").split(",")}
            conn = http.client.HTTPConnection(proxy.host, proxy.upstream_port,
                                              timeout=READ_TIMEOUT_S)
            with proxy.gate:
                proxy.active[self.request] = conn  # so a drain deadline can cancel it
            try:
                # Sol S3, round 2, and T1: admission, the token, the latch and the
                # start of dispatch are atomic. Under the one lock that latch(),
                # token validation and retirement all take, the latch and the
                # token are re-checked right before the request is sent upstream,
                # so nothing is dispatched once the latch is set or its call has
                # ended; the request is credited to its call at that moment, so a
                # call that ends while its response is in flight keeps it.
                with proxy.gate:
                    if proxy.latched:
                        blocked = True
                    else:
                        why = proxy.token_refusal(token, method, route_template(path), path)
                        blocked = why is not None
                    if not blocked:
                        proxy.credit(token, method, route_template(path), path)
                        conn.putrequest(self.command, target, skip_host=True,
                                        skip_accept_encoding=True)
                        conn.putheader("Host", proxy.netloc)
                        for k, v in h.items():
                            if k.lower() not in dropped:
                                conn.putheader(k, v)
                        conn.endheaders()
                if not blocked:
                    if proxy._pause_after_dispatch:
                        proxy._pause_after_dispatch()  # test-only: forces the interleaving
                    resp = conn.getresponse()
                    data = resp.read()
            except (OSError, http.client.HTTPException):
                with proxy.lock:
                    proxy.errors += 1
                proxy.latch("an upstream error")  # Sol N-R2
                proxy.record(method, route_template(path), write, path, False)
                self.send_error(502)
                return
            finally:
                conn.close()
        proxy.record(method, route_template(path), write, path, blocked)
        if blocked:
            # NEVER forwarded (Jake: fail closed): no valid call token, outside the
            # proxy's list, write-like, or after the latch; answered here, and it
            # stops the run.
            proxy.latch(why or "a blocked request")
            self.send_error(403)
            return
        self.send_response_only(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in HOP_HEADERS:
                self.send_header(k, v)
        length = resp.getheader("Content-Length") if self.command == "HEAD" else None
        self.send_header("Content-Length", length if length is not None else str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


class Proxy:
    """M3: a loopback logging proxy for one step. It forwards each request to
    the upstream unchanged, except the Host header (set to the upstream's) and
    hop-by-hop headers, and returns the upstream's response unchanged. It keeps,
    per request, only the step's label, the method and the route template:
    never a header, body, query value or token, in memory or anywhere else."""

    def __init__(self, upstream, latch=True, routes=FORWARD_ROUTES):
        # latch=False only in the unit tests that check each request's own
        # classification; observe.py itself never sets it.
        self.latching = latch
        self.routes = routes
        # Admission, call tokens (their validation and retirement), the latch and
        # the start of dispatch (Sol S3 round 2, T1)
        self.gate = threading.RLock()
        self._pause_before_dispatch = self._pause_after_dispatch = None  # test-only hooks
        # Open connections (client socket: its upstream connection, if any), and a
        # condition on the gate signalled when one closes (Sol's sweep, 1 and 4).
        self.active, self.idle, self.drain = {}, threading.Condition(self.gate), None
        # Sol N-R1 round 2: the open calls, by token, each with its own requests
        # ((method, route, ids), in memory only); tokens of ended calls; and, for
        # OpenWiz, the shim log whose tokens the current invocation may use.
        self.calls, self.retired, self.shim_log = {}, set(), None
        # Final round: each registered call's plan (phase, routes, session), and the
        # phase in which requests are admitted now (None: none).
        self.plans, self.phase = {}, None
        self.host, self.upstream_port = loopback_upstream(upstream)
        self.netloc = "%s:%d" % ("[::1]" if self.host == "::1" else self.host, self.upstream_port)
        self.log, self.errors, self.upgrades, self.label = [], 0, 0, None
        self.latched = None  # the first failure's reason, once set nothing more is forwarded
        self.lock = threading.Lock()
        self.server = _ProxyServer(("127.0.0.1", 0), _ProxyHandler)
        self.server.proxy = self
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        """Stops accepting, then waits for every open connection (Sol T3), at most
        DRAIN_S in all (Sol's sweep, finding 4): on expiry the remaining ones are
        cancelled (their client and upstream sockets shut), the proxy latches,
        and its drain is `incomplete`. Safe on a proxy that never started, and
        when called again after an interrupt."""
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.wait_idle(DRAIN_S):
            self.drain = self.drain or "complete"
        else:
            self.cancel_open()
            self.latch("a connection still open at the drain deadline (cancelled)")
            self.wait_idle(5)
            self.drain = "incomplete"
        if self.thread.ident is not None:
            self.thread.join()

    def wait_idle(self, timeout):
        """True once no connection is open (every admitted request has finished,
        its response read to the end), False if one still is after timeout."""
        with self.idle:
            return self.idle.wait_for(lambda: not self.active, timeout)

    def cancel_open(self):
        with self.gate:
            open_now = list(self.active.items())
        for client, conn in open_now:
            for sock in (client, getattr(conn, "sock", None)):
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    def totals(self, start=0, end=None):
        """Counts over every request this proxy saw (or those logged between two
        marks), from its complete log (Sol T3), those outside any OpenWiz call
        included."""
        with self.lock:
            log = self.log[start:end]
        return {"requests": len(log),
                "blocked_requests": sum(1 for e in log if e["blocked"]),
                "write_like_requests": sum(1 for e in log if e["write_like"]),
                "unlisted_get_requests": sum(1 for e in log if e["blocked"] and not e["write_like"]),
                "requests_outside_openwiz_calls": sum(1 for e in log if e["label"] is None)}

    def record(self, method, route, write=True, raw_path="", blocked=True):
        with self.lock:
            self.log.append({"label": self.label, "method": method, "route": route,
                             "write_like": bool(write), "blocked": bool(blocked)})

    def credit(self, token, method, route, raw_path):
        """Credits a request to its call; called under the gate as it is dispatched."""
        ids = frozenset(x for x in decoded_segments(raw_path or "/") if x and x not in ROUTE_WORDS)
        with self.gate:
            self.calls[token].append((method, route, ids))

    def open_call(self, token, phase=None, argv=None):
        """An observer call starts: its token may be used until close_call; with
        argv, only in `phase` and only for its planned read (final round)."""
        with self.gate:
            self.calls[token] = []
            if argv is not None:
                self.plans[token] = call_plan(argv, phase)

    def close_call(self, token):
        """The call ended: its requests; its token is refused from now on."""
        with self.gate:
            self.retired.add(token)
            return self.calls.pop(token, [])

    def open_shim(self, log_path, phase=None):
        """An OpenWiz invocation starts: the tokens its shim logs may be used, in
        this invocation's phase, each for its own call's planned read."""
        with self.gate:
            self.shim_log, self.phase = log_path, phase

    def close_shim(self):
        """The invocation ended: {token: its requests}; all its tokens retired."""
        with self.gate:
            calls, self.calls, self.shim_log, self.phase = self.calls, {}, None, None
            self.retired.update(calls)
            return calls

    def token_refusal(self, token, method=None, route=None, path=None):
        """Why a request with this call token is refused, or None. With the
        request's method, route and path, it must also fit its call's phase and
        planned read (Sol's sweep, finding 1, final round)."""
        if token is None:
            return "a request without a call token"
        with self.gate:
            if token in self.retired:
                return "a request with a reused call token"
            if token not in self.calls and self.shim_log and os.path.exists(self.shim_log):
                # The shim writes each call's line, in one write, before the call
                # starts; only a line still being written by another call can be
                # partial, and it is skipped.
                with open(self.shim_log) as f:
                    for line in f:
                        e = json.loads(line) if line.endswith("\n") else {}
                        t = e.get("token")
                        if t and t not in self.retired:
                            self.calls.setdefault(t, [])
                            if self.phase is not None:  # a run's invocation: planned
                                self.plans.setdefault(t, call_plan(e.get("argv") or [], self.phase))
            if token not in self.calls:
                return "a request with an unknown call token"
            plan = self.plans.get(token)
            if plan is not None:
                if plan["phase"] is None or plan["phase"] != self.phase:
                    return "a request with an out-of-phase call token"
                if method is not None:
                    return plan_refusal(plan, self.calls[token], method, route, path)
        return None

    def take(self, label):
        """One label's requests, each with its flags (filtered per request, by
        identity, never by comparing templates: F5)."""
        with self.lock:
            return [dict(e) for e in self.log if e["label"] == label]

    def latch(self, reason):
        with self.gate:
            if self.latching and not self.latched:
                self.latched = reason



EGRESS_PROFILE = """(version 1)
(allow default)
(deny network-outbound)
(allow network-outbound (remote ip "localhost:%d"))"""


def paths_exercised(rows, done_ok):
    """Which kinds of session OpenWiz read by id, through the proxy, in calls that
    exited as expected; by name only (the paths a read takes differ by session)."""
    rows = [rows[x] for x in done_ok if x in rows]
    have = {
        "a cloud session": any(r.get("cloud") for r in rows),
        "a local session": any(r.get("host") for r in rows),
        "a session in error (thread show also reads its output)":
            any(r.get("status") == "error" for r in rows),
        "a session with an environment (its environment and pull-request reads)":
            any(r.get("env") for r in rows),
        "a session without an environment": any(not r.get("env") for r in rows),
        "a hidden session": any(r.get("hidden") and r.get("visibility_known") for r in rows),
        "an archived session": any(r.get("archived") for r in rows),
    }
    return {"exercised": sorted(k for k, v in have.items() if v),
            "not_exercised": sorted(k for k, v in have.items() if not v)}


def observer_record(ctx, obs):
    """M3 for the observer's own reads (Sol N-R1), by read kind and by route
    template; counts only, no id."""
    with obs.lock:
        log = [dict(e) for e in obs.log]
    by_route = {}
    for e in log:
        k = "%s %s" % (e["method"], e["route"])
        by_route[k] = by_route.get(k, 0) + 1
    strip = lambda e: {"method": e["method"], "route": e["route"]}  # noqa: E731
    return {"calls_by_kind": dict(sorted(ctx.reads.items())),
            "requests_by_route": dict(sorted(by_route.items())),
            "blocked": [strip(e) for e in log if e["blocked"]],
            "write_like": [strip(e) for e in log if e["write_like"]],
            "unlisted_get_requests": sum(1 for e in log if e["blocked"] and not e["write_like"]),
            "calls_without_requests": dict(sorted(ctx.missing.items())),
            "latched": obs.latched, "drain": obs.drain, "upstream_errors": obs.errors,
            "upgrades_refused": obs.upgrades}


def m3_record(proxy, label, run):
    """What the proxy saw for one OpenWiz call (all its shim's room-cli reads),
    compared with the shim's log of read kinds (§7.1 (c)). Templates and counts
    only; the ids the per-call check uses stay in the proxy's memory."""
    full = proxy.take(label)
    strip = lambda e: {"method": e["method"], "route": e["route"]}  # noqa: E731
    got = [strip(e) for e in full]
    kinds = [read_kind(c["argv"]) for c in run["calls"]]
    explained = set().union(*[m2_routes(k) for k in kinds]) if kinds else set()
    return {
        "requests": [{"method": m, "route": r} for m, r in sorted({(q["method"], q["route"]) for q in got})],
        "request_count": len(got),
        "blocked": [strip(e) for e in full if e["blocked"]],
        "write_like": [strip(e) for e in full if e["write_like"]],
        "unlisted_get_count": sum(1 for e in full if e["blocked"] and not e["write_like"]),
        "requests_not_explained_by_reads": [q for q in got if (q["method"], q["route"]) not in explained],
        "calls_without_requests": calls_without_requests(
            [(c["argv"], got) for c, got in zip(run["calls"], run.pop("_requests"))
             if not c.get("refused")]),
    }


# --------------------------------------------------------------------------
# Subcommands


def client_environment():
    """The client-changing variables M2 found, as set / unset (never their
    values). ROOM_CLI or BB_APP_VERSION set stops: the inspected client might not
    be the one that runs, or `--version` might not be its version."""
    env = {k: ("set" if os.environ.get(k) else "unset")
           for k in CLIENT_HOOKS + NODE_HOOKS + PROXY_VARS + ("ROOM_SERVER_URL",)}
    hooks = [k for k in CLIENT_HOOKS + NODE_HOOKS + PROXY_VARS if env[k] == "set"]
    if hooks:
        raise Stop("%s is set in the environment: it changes which client runs, what "
                   "--version says, or where its requests go (M2, D18); unset it"
                   % ", ".join(hooks))
    if env["ROOM_SERVER_URL"] == "set":
        loopback_upstream(os.environ["ROOM_SERVER_URL"])  # Stop unless loopback http
        env["ROOM_SERVER_URL"] = "set (loopback http)"
    return env


def check_version(ctx):
    client_environment()
    return version_from(ctx.room(["--version"]))


def version_from(r):
    """The pin check on a --version read's result (R10: one place for it)."""
    found = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode != 0 or found != TESTED_VERSION:
        shown = found if re.match(r"^[0-9][0-9A-Za-z.+-]{0,30}$", found) else "unreadable"
        raise Stop("room-cli %s is untested (tested: %s); changing the pin is Jake's "
                   "decision" % (shown, TESTED_VERSION))
    return found


def executable_class(path):
    real = os.path.realpath(path)
    with open(real, "rb") as f:
        head = f.read(256)
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        return "mach-o"
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:2] == b"#!":
        words = head[2:].split(b"\n", 1)[0].split()
        names = [os.path.basename(w.decode("ascii", "replace")) for w in words]
        name = names[-1] if names and names[0] == "env" else (names[0] if names else "")
        return "script (%s)" % (name if re.match(r"^[a-z0-9.+-]{1,20}$", name) else "other")
    return "other"


def cmd_preflight(a):
    ENDPOINT_CHECK[0] = bool(a.endpoint_check)
    environment = client_environment()
    make_run_dir(a.run_dir)
    ctx = Ctx(a.room_cli, a.run_dir, a.concurrency)
    pre = {"script": SCRIPT_VERSION, "script_sha256": file_sha256(__file__),
           "environment": environment, "room_cli_version": check_version(ctx),
           "room_cli_executable": executable_class(ctx.room_cli), "help": {}}
    for target in HELP_TARGETS:
        r = ctx.room(list(target) + ["--help"])
        text = (r.stdout + r.stderr).decode("utf-8", "replace")
        pre["help"][" ".join(target) or "room-cli"] = {
            "exit": r.returncode, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "flags": sorted(set(FLAG_RE.findall(text))),
            "env_names": sorted(set(ENV_RE.findall(text))),
            "mentions": sorted(w for w in ("debug", "verbose", "trace", "mark", "read",
                                           "wake", "send", "start", "resume")
                               if re.search(r"\b%s" % w, text, re.I)),
        }
    rows = ctx.room_json(["thread", "list", "--json", "--include-hidden",
                          "--include-archived"])
    if not isinstance(rows, list):
        raise Stop("observer thread list printed no array")
    now = now_ms()
    ups = [r.get("updatedAt") for r in rows if isinstance(r, dict)
           and isinstance(r.get("updatedAt"), int)]
    pre["sessions_all_views"] = len(rows)
    pre["timestamps_look_like_ms"] = bool(ups) and all(
        now - 10 * 365 * 86_400_000 <= u <= now + 86_400_000 for u in ups)
    pre["log_method"] = log_method(ctx, rows)
    pre["log_limit_semantics"] = pre["log_method"]["limit"]
    if a.endpoint_check:
        status = ctx.room_json(["status", "--json"])
        url = status.get("serverUrl") if isinstance(status, dict) else None
        m = re.match(r"^(https?)://(\[::1\]|127\.[0-9.]+|localhost)(:[0-9]+)?(/|$)",
                     url or "")
        pre["endpoint"] = ("loopback (%s)" % m.group(1)) if m else (
            "not loopback" if url else "unknown")
    # D8: S0 reads each session's show once and searches its log; every later
    # snapshot reads show and the log after the previous number once each.
    n, search = pre["sessions_all_views"], pre["log_method"]["search_reads"]
    pre["estimated_reads"] = {
        "lists": 4 + 3,
        "s0": 4 + 3 + n * (1 + (search["median"] if search else 1)),
        "per_later_snapshot": 4 + 3 + 2 * n}
    pre.update(ctx.counts())
    ctx.save("preflight.json", pre)
    return {"preflight": pre}


def raw_seqs(ctx, sid, after, limit):
    """The numbers one read returns, in its order, for the pre-flight's checks."""
    rows = log_rows(ctx, sid, after, limit)
    if rows is None:
        return None
    seqs = [typed(e.get("seq"), int) if isinstance(e, dict) else MISSING for e in rows]
    return MISSING if MISSING in seqs else seqs


def log_method(ctx, rows):
    """Proves, live, what find_last_seq relies on, on up to LOG_CHECK_SESSIONS
    sessions (procedures §7.2): `--limit` keeps the oldest events; `--after-seq S`
    gives the events above S, oldest first; and the search's result L is
    confirmed by two reads (an event at L, none above L). It also measures the
    search's reads (D8). `run` refuses unless `proven` is true."""
    res = {"sessions_examined": 0, "limit": "undetermined (no session with 3 or more events)",
           "after_seq": "undetermined (no session with 3 or more events)",
           "window": "undetermined (no examined session with %d or more events)" % LOG_WINDOW,
           "numbering": "from 1", "search_confirmed": 0, "search_failed": 0}
    costs, lasts = [], []
    for row in rows[:3 * LOG_CHECK_SESSIONS]:
        sid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(sid, str) or not ID_RE.match(sid) or sid.startswith("-"):
            continue
        if res["sessions_examined"] >= LOG_CHECK_SESSIONS and not res["window"].startswith(
                "undetermined"):
            break  # 20 examined, and the window is settled
        if res["sessions_examined"] >= 3 * LOG_CHECK_SESSIONS:
            break
        res["sessions_examined"] += 1
        last, reads = find_last_seq(lambda after: log_seqs(ctx, sid, after))
        costs.append(reads)
        one, three = raw_seqs(ctx, sid, None, 1), raw_seqs(ctx, sid, None, 3)
        if last == "gone" or None in (one, three):
            continue  # the session went away meanwhile
        if last == MISSING or MISSING in (one, three):
            res["search_failed"] += 1
            continue
        if last is None:
            continue  # an empty log
        lasts.append(last)
        if three and three[0] < 1:
            res["numbering"] = "below 1 (--after-seq cannot be given 0)"
            break
        if len(three) < 3:
            continue
        if one != three[:1] or three != sorted(set(three)):
            res["limit"] = "not oldest first (--limit 1 is not the first of --limit 3)"
            break
        res["limit"] = "oldest first"
        a, b, c = three
        nxt = raw_seqs(ctx, sid, b, 1)
        if nxt is None:
            continue  # the session went away meanwhile
        res["after_seq"] = {(c,): "strictly after, oldest first", (b,): "inclusive (it returns the "
                            "event at S)", (a,): "ignored (it returns the oldest event)"}.get(
                                tuple(nxt) if nxt != MISSING else None, "other")
        if res["after_seq"] != "strictly after, oldest first":
            break
        above, at = raw_seqs(ctx, sid, last, 1), raw_seqs(ctx, sid, last - 1, 1)
        if None in (above, at):
            continue  # the session went away meanwhile (verification C4)
        if last >= 2 and above == [] and at == [last]:
            res["search_confirmed"] += 1
        else:
            res["search_failed"] += 1
        if res["window"].startswith("undetermined"):
            # The search reads LOG_WINDOW events at a time: a server that gave fewer
            # would make a short window look like the end (Haiku A R4). Proven only
            # by a session whose oldest-LOG_WINDOW read is full. A server with a
            # smaller window leaves it undetermined (so not proven), and its short
            # first window makes the search's confirmation fail too.
            got = raw_seqs(ctx, sid, None, LOG_WINDOW)
            if got not in (None, MISSING) and len(got) == LOG_WINDOW:
                res["window"] = "%d events per read" % LOG_WINDOW
    res["search_reads"] = ({"median": statistics.median_low(costs), "max": max(costs),
                            "sessions": len(costs)} if costs else None)
    res["last_seq"] = ({"median": statistics.median_low(lasts), "max": max(lasts)}
                       if lasts else None)
    res["proven"] = (res["limit"] == "oldest first"
                     and res["after_seq"] == "strictly after, oldest first"
                     and res["window"] == "%d events per read" % LOG_WINDOW
                     and res["numbering"] == "from 1"
                     and res["search_confirmed"] >= 1 and res["search_failed"] == 0)
    return res


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def choose_samples(snap, exclude):
    order = default_order(snap)
    page = set(order[:LS_L_PAGE])
    picks = {}
    for sid in order:
        r = merged(snap, sid)
        if (sid in exclude or r["gone"] or not_quiet(r) or r["status"] != "idle"
                or r["display"] != "idle"):
            continue
        kind = "cloud" if r["cloud"] else ("local" if r["host"] else None)
        if kind is None:
            continue
        where = "on_page" if sid in page else "off_page"
        picks.setdefault("%s_%s" % (kind, where), sid)
    return picks


def cmd_run(a):
    ctx = Ctx(a.room_cli, a.run_dir, a.concurrency)
    pre = load(os.path.join(ctx.run_dir, "preflight.json"))
    method = pre.get("log_method") or {}
    if method.get("proven") is not True:
        raise Stop("the last event sequence number cannot be read: the pre-flight did not "
                   "prove the thread log method (limit: %s; after-seq: %s; confirmed %s, "
                   "failed %s)" % (method.get("limit"), method.get("after_seq"),
                                   method.get("search_confirmed"), method.get("search_failed")))
    if os.path.exists(os.path.join(ctx.run_dir, "run.json")):
        raise Stop("this run directory already has a run; use a new one")
    exclude = set(a.exclude_id or [])
    APPROVED_LABELS.update(a.approve_label or [])
    # M3 (procedures §7.1, Sol S1): OpenWiz's own calls in the brackets go through
    # the loopback logging proxy; the observer's reads stay direct. The upstream is
    # the server room-cli itself would use (M2's rule).
    client_environment()
    from_env = os.environ.get("ROOM_SERVER_URL")
    loopback_upstream(from_env or a.upstream_default)
    if a.egress_sandbox and not os.access(a.sandbox_exec, os.X_OK):
        raise Stop("--egress-sandbox: sandbox-exec is not available (decision D21)")
    proxy = Proxy(from_env or a.upstream_default, routes=OPENWIZ_ROUTES)
    # Sol N-R1: a second proxy, on its own loopback port, for the observer's own
    # room-cli calls, from the first call before S0 onwards (attribution by port).
    try:
        obs = Proxy(from_env or a.upstream_default, routes=OBSERVER_ROUTES)
    except BaseException:
        proxy.__exit__(None, None, None)  # Sol's sweep, finding 3: nothing left open
        raise
    t0 = now_ms()
    # Until the sequence ends, the run counts as stopped: an interrupt (Ctrl-C)
    # or an unexpected error still saves what was measured.
    run = {"started_ms": t0, "brackets": [], "checks": {},
           "approved_labels": sorted(APPROVED_LABELS),
           "stopped": "interrupted before the end of the sequence"}

    # Inputs finish() needs, kept outside the record so a retried save computes
    # the same record (Sol's sweep, finding 3 round 2): S0's rows (coverage).
    keep = {"rows": {}}

    def finish():
        """Builds and saves run.json; idempotent, so it can be retried."""
        outs = [o for b in run["brackets"] for o in b.get("runs", [])]
        done_ok = {c["argv"][2] for o in outs if o["exit"] in (0, 3) for c in o["calls"]
                   if len(c["argv"]) >= 3 and c["argv"][1] in ("show", "output")}
        run["m3"] = {
            "upstream": "loopback http (%s)" % ("from ROOM_SERVER_URL" if from_env
                                                else "the M2 default"),
            "egress_sandbox": ("on (sandbox-exec: every OpenWiz call in the brackets, with its "
                               "children, reaches the network only at the OpenWiz proxy's "
                               "loopback port, and every observer call only at the observer "
                               "proxy's)" if a.egress_sandbox
                               else "off (decision D21 not taken)"),
            # Sol T3: from the proxy's complete log, after it is drained.
            **proxy.totals(),
            "upstream_errors": proxy.errors, "upgrades_refused": proxy.upgrades,
            "latched": proxy.latched, "drain": proxy.drain,
            "paths": paths_exercised(keep["rows"], done_ok),
            "observer": observer_record(ctx, obs)}
        run["ended_ms"] = now_ms()
        run.update(ctx.counts())
        ctx.save("run.json", run)
        return {"run": "saved"}

    def latch_stop(where):
        """Sol T3: a latch on either proxy, at any time, stops the run."""
        if proxy.latched:
            return "%s: M3 %s" % (where, proxy.latched)
        if obs.latched:
            return "%s: observer M3: %s" % (where, obs.latched)
        return None

    def boundary(where, phase):
        """Sol's sweep, finding 1, final round: a phase boundary. Both proxies are
        drained (every admitted request finished, at most QUIESCE_S each) and no
        observer call may be open; then the observer proxy admits only calls of
        `phase` (None: none). A breach latches and stops the run, as does any
        observer latch; an OpenWiz latch from inside a bracket stops it after that
        bracket's after-state (Sol S3)."""
        breach = False
        for p in (proxy, obs):
            if not p.wait_idle(QUIESCE_S):
                p.latch("a request still in flight at a phase boundary")
                breach = True
        with obs.gate:
            if obs.calls:
                obs.latch("a call still open at a phase boundary")
                breach = True
            obs.phase = phase
        ctx.phase = phase
        if breach or obs.latched:
            raise Stop(latch_stop(where))

    def capture(name, where, prev):
        """One capture (a full snapshot and the sample records) in its own phase,
        drained before and after."""
        boundary(where, name)
        snap = snapshot(ctx, name, prev)
        recs = {s: sample_record(ctx, s, snap) for s in samples}
        boundary(where, None)
        return snap, recs

    def compare(name, *args, **kwargs):
        """A bracket comparison; the new-event reads it makes for changed sessions
        are observer calls, so they get their own phase, drained like any."""
        boundary("bracket " + name, "events " + name)
        b = bracket(ctx, name, *args, **kwargs)
        boundary("bracket " + name, None)
        return b

    def junction(name, before, after, recs_before, recs_after, why):
        """Two consecutive captures with no OpenWiz call between them must be
        equal in every field (a fixed point); compared as a bracket too, for the
        record."""
        b = compare(name, before, after, [], exclude, recs_before, recs_after)
        diff = capture_differences(before, after, recs_before, recs_after)
        b["fixed_point"] = {"equal": not diff, "differences": diff}
        run["brackets"].append(b)
        if diff:
            raise Stop("bracket %s: %s: %s (%s; outcome: %s)"
                       % (name, why[0], difference_text(diff), why[1], b["outcome"]))
        if b["outcome"] not in CONTINUE:
            raise Stop("bracket %s: %s" % (name, b["outcome"]))
        if latch_stop("bracket " + name):  # no OpenWiz call here: any latch stops
            raise Stop(latch_stop("bracket " + name))

    # D21 (approved): every OpenWiz call, with its children, may reach the network
    # only at the OpenWiz proxy's loopback port; every observer call only at the
    # observer proxy's.
    wrap = ([a.sandbox_exec, "-p", EGRESS_PROFILE % proxy.port] if a.egress_sandbox else None)
    ctx.obs_proxy = obs
    ctx.obs_env = dict(os.environ)  # Ctx.room sets each call's ROOM_SERVER_URL
    ctx.obs_wrap = ([a.sandbox_exec, "-p", EGRESS_PROFILE % obs.port] if a.egress_sandbox else None)
    try:
        proxy.__enter__()
        obs.__enter__()
        check_version(ctx)
        # S0, first contact: its own phase; the samples are chosen from it.
        samples = []
        boundary("capture S0", "S0")
        s0 = snapshot(ctx, "S0")
        keep["rows"] = s0["rows"]
        picks = choose_samples(s0, exclude)
        run["samples"] = picks
        samples[:] = sorted(set(picks.values()))
        missing = [k for k in ("cloud_on_page", "local_on_page", "cloud_off_page",
                               "local_off_page") if k not in picks]
        run["samples_missing"] = missing
        if not s0["rows"]:
            raise Stop("S0 has no session")
        needed = [k for k in missing if k.endswith("on_page")
                  or len(s0["views"]["default"]) > LS_L_PAGE]
        unaccepted = [k for k in needed if k not in (a.accept_missing_sample or [])]
        if unaccepted:
            raise Stop("no quiet idle session for sample %s (decision D12)"
                       % ", ".join(unaccepted))
        recs = {s: sample_record(ctx, s, s0) for s in samples}
        boundary("capture S0", None)
        # The warm-up and the control (C0), Jake's "continue" round: S0, W1, the
        # control wait, W2, with no OpenWiz call, must all be equal in every field.
        # Any difference, a once-only one included, means the observer's reads (the
        # same reads OpenWiz makes) changed something: it stops the run. Nothing
        # is settled, tolerated or exempted.
        w1, recs_w1 = capture("W1", "bracket warm-up", s0)
        junction("warm-up", s0, w1, recs, recs_w1,
                 ("observer not neutral", "S0 and W1, no OpenWiz call between them"))
        time.sleep(a.control_wait)
        w2, recs_w2 = capture("W2", "bracket control", w1)
        junction("control", w1, w2, recs_w1, recs_w2,
                 ("observer not neutral", "W1 and W2, no OpenWiz call between them"))
        missing_id = "thr_synopenwizp4_" + os.urandom(6).hex()
        if any(missing_id in s["rows"] for s in (s0, w1, w2)):
            raise Stop("the synthetic nonexistent id exists")
        shows = [k for k in ("cloud_on_page", "local_on_page", "cloud_off_page",
                             "local_off_page") if k in picks]
        show_targets = []
        for kind in ("cloud", "local"):
            k = next((x for x in shows if x.startswith(kind)), None)
            if k:
                show_targets.append(picks[k])
        plan = [("ls", [["ls"]]), ("ls-l", [["ls", "-l"]]),
                ("show", [["show", s] for s in show_targets]),
                ("p4", [["show", missing_id]]), ("inventory", None)]
        prev, prev_recs = w2, recs_w2
        mark = 0  # the OpenWiz proxy's log position where the next bracket's M3 totals start
        for name, runs_args in plan:
            if runs_args is None:
                runs_args = inventory_plan()
            outs, count_total = [], None
            aborted = 0
            # The bracket's own phase: the poller's and thread count's observer reads.
            boundary("bracket " + name, "bracket " + name)
            with Poller(ctx, samples, a.poll_interval) as poll:
                for i, args in enumerate(runs_args):
                    if proxy.latched or poll.error or poll.changes or any(
                            r["exit"] != expected_exits(name, [r])["expected"] for r in outs):
                        aborted = len(runs_args) - i  # stop calling; take the after-state
                        break
                    label = "%s-%02d" % (name, i)
                    proxy.label = label
                    r = run_openwiz(ctx, a.openwiz, label, args, wrap=wrap, proxy=proxy)
                    r["m3"] = m3_record(proxy, label, r)
                    proxy.label = None  # a later request belongs to no OpenWiz call
                    # Each invocation is a phase: drained before the next one.
                    if not proxy.wait_idle(QUIESCE_S):
                        proxy.latch("a request still in flight at a phase boundary")
                    # The latch (Sol S3): a blocked request (latched by the proxy), a
                    # call without its proxied request, or an unexpected exit.
                    if r["m3"]["calls_without_requests"]:
                        proxy.latch("a call without its proxied request (%s)" % ", ".join(
                            sorted(r["m3"]["calls_without_requests"])))
                    if r["exit"] != expected_exits(name, [r])["expected"]:
                        proxy.latch("an OpenWiz run exited other than expected")
                    outs.append(r)
                    if name == "inventory" and args[:2] == ["ls", "--json"] \
                            and "--offset" not in args and count_total is None:
                        c = ctx.room_json(["thread", "count", "--json"])
                        count_total = c.get("total") if isinstance(c, dict) else None
                    if name == "inventory":
                        more = next_page(outs[-1], args)
                        if more:
                            runs_args.insert(i + 1, more)
            try:
                snap, recs_n = capture(name, "bracket " + name, prev)
            except Stop:
                # No after-state can certify this bracket's calls: they are kept,
                # sanitized like any bracket's, without a bracket outcome.
                run["unfinished_bracket"] = {
                    "name": name, "runs": outs,
                    "outcome": "incomplete: no after-state (the run stopped first)"}
                raise
            b = compare(name, prev, snap, outs, exclude, prev_recs, recs_n, poll)
            b["expected_exits"] = expected_exits(name, outs)
            b["aborted_calls"] = aborted
            off_page = [picks[k] for k in ("cloud_off_page", "local_off_page") if k in picks]
            b["off_page_samples_read_by_id"] = len(set(off_page) & set(individually_read(outs)))
            if name in ("ls", "ls-l") and b["off_page_samples_read_by_id"]:
                b["outcome"] = "incomplete: an off-page sample was read by id"
            # Every request the proxy logged since the previous bracket ended
            # (Sol T3), not only those inside this bracket's OpenWiz calls.
            with proxy.lock:
                end = len(proxy.log)
            b["m3"] = {"latched": proxy.latched, **proxy.totals(mark, end)}
            mark = end
            run["brackets"].append(b)
            if proxy.latched and not b["expected_exits"]["unexpected"]:
                # The after-state is taken and saved; nothing more is called. (A latch
                # from an unexpected exit stops below, under that clearer reason.)
                raise Stop("bracket %s: M3 %s" % (name, proxy.latched))
            if name == "p4":
                run["checks"]["P4"] = (p4(outs[0], missing_id) if outs else
                                       {"outcome": "incomplete: the P4 call was not made"})
            if name == "inventory":
                inv = {}
                for r in outs:
                    view = view_of(r["args"])
                    if "--limit" in r["args"] and r["args"][r["args"].index("--limit") + 1] == "0":
                        inv[("count", view)] = r
                    elif "-l" not in r["args"]:
                        inv.setdefault(("pages", view), []).append(r)
                run["checks"]["P1"] = p1(prev, snap, inv, count_total)
                json_runs = [r for r in outs if "--json" in r["args"]]
                run["checks"]["P2"], run["checks"]["P3"] = p2_p3(prev, snap, json_runs)
                text = next(r for r in outs if r["args"] == ["ls", "-l"])
                lj = next(r for r in outs if r["args"] == ["ls", "-l", "--json"])
                run["checks"]["P3"]["text"] = p3_text(text, lj)
                run["checks"]["P6"] = p6(prev, snap, [r for r in outs if "--json" in r["args"]
                                                      and view_of(r["args"]) in
                                                      ("default", "hidden")])
            if b["outcome"] not in CONTINUE:
                raise Stop("bracket %s: %s" % (name, b["outcome"]))
            # A failed claim stops the run too, once the after-state is taken.
            if b["expected_exits"]["unexpected"]:
                raise Stop("bracket %s: openwiz exited other than %d"
                           % (name, b["expected_exits"]["expected"]))
            if b["aborted_calls"]:
                raise Stop("bracket %s: OpenWiz calls aborted on a poll change or error"
                           % name)
            failed = failed_checks(run["checks"])
            if failed:
                raise Stop("bracket %s: %s not consistent" % (name, ", ".join(failed)))
            prev, prev_recs = snap, recs_n
        # The end (finding 1, final round): settle, then the final capture F after
        # the late wait; each must equal the capture before it in every field.
        # F is the last observation; nothing is admitted after it.
        time.sleep(a.settle)
        s_settle, recs_s = capture("settle", "bracket settle", prev)
        junction("settle", prev, s_settle, prev_recs, recs_s,
                 ("not a fixed point", "the last after-state and settle"))
        time.sleep(max(0, a.late - a.settle))
        s_final, recs_f = capture("final", "bracket final", s_settle)
        junction("final", s_settle, s_final, recs_s, recs_f,
                 ("not a fixed point", "settle and the final capture"))
        run["stopped"] = None
    except Stop as e:
        run["stopped"] = str(e)
    except Exception as e:  # a script defect: keep the type only, never its text
        run["stopped"] = "unexpected error: %s" % type(e).__name__
    finally:
        # Sol T3: success is declared only here, after both proxies are stopped
        # and drained (no handler still running), with both latches checked at
        # this final point and every total recomputed from the complete logs. An
        # earlier stop keeps its own (first) reason; the latches are in the record.
        # Sol's sweep, finding 3: finalization survives an interrupt or an error in
        # any step: each proxy's exit is tried (an interrupted one once more), the
        # evidence is saved (retried after an interrupt), and only then does the
        # interrupt go on to main(), which prints a fixed message.
        interrupted, failed = False, []
        for p in (proxy, obs):
            for _ in range(2):
                try:
                    p.__exit__(None, None, None)
                    break
                except KeyboardInterrupt:
                    interrupted = True
                except Exception as e:  # never its text: it could hold a path
                    failed.append(type(e).__name__)
                    break
        if run["stopped"] is None:
            # After the drain: any latch, on either proxy, stops the run (T3).
            run["stopped"] = ("interrupted during shutdown" if interrupted else
                              "shutdown: a proxy did not stop (%s)" % ", ".join(failed) if failed
                              else latch_stop("shutdown"))
        for _ in range(3):
            try:
                finish()
                break
            except KeyboardInterrupt:
                # The interruption is recorded before the save is retried (round 2).
                interrupted = True
                if run["stopped"] is None:
                    run["stopped"] = "interrupted during shutdown"
        if interrupted:
            raise KeyboardInterrupt
    return {"run": "saved", "stopped": run["stopped"]}


def failed_checks(checks):
    """The claims (P1, P2, P3, P4, P6) whose outcome is not `consistent`."""
    failed = []
    for claim, v in sorted(checks.items()):
        if claim == "P1":
            ok = (all(v[view]["outcome"] == "consistent" for view, _ in OPENWIZ_VIEWS)
                  and v["thread_count"]["matches_default_view"] is True)
        elif claim == "P3":
            ok = v["outcome"] == "consistent" and v["text"]["outcome"] == "consistent"
        else:
            ok = v["outcome"] == "consistent"
        if not ok:
            failed.append(claim)
    return failed


def inventory_plan():
    plan = []
    for _, flags in OPENWIZ_VIEWS:
        plan.append(["ls"] + flags + ["--json", "--limit", "0"])
        plan.append(["ls"] + flags + ["--json", "--limit", str(PAGE), "--offset", "0"])
    plan += [["ls", "-l", "--json"], ["ls", "-l"]]
    return plan


def view_of(args):
    flags = [x for x in args if x in ("-a", "--hidden")]
    return {(): "default", ("--hidden",): "hidden", ("-a",): "archived"}.get(
        tuple(sorted(flags)), "both")


def next_page(run, args):
    if "--offset" not in args:
        return None
    env = envelope(run)
    shown = (((env or {}).get("coverage") or {}).get("counts") or {}).get("shown", 0)
    if shown < PAGE:
        return None
    i = args.index("--offset")
    offset = int(args[i + 1]) + PAGE
    if offset > 50 * PAGE:
        raise Stop("more than 50 pages in one view")
    return args[:i + 1] + [str(offset)]


def expected_exits(name, outs):
    want = 3 if name == "p4" else 0
    return {"expected": want, "unexpected": sum(1 for r in outs if r["exit"] != want)}


# --------------------------------------------------------------------------
# The sanitized report


def cmd_report(a):
    run_dir = os.path.abspath(a.run_dir)
    pre = load(os.path.join(run_dir, "preflight.json"))
    path = os.path.join(run_dir, "run.json")
    run = load(path) if os.path.exists(path) else None
    forbidden_strings = forbidden(run_dir, a)
    ordinals = Ordinals(run_dir, run)
    rep = {"report": "openwiz-0.0.1-ticket-3-live", "script": SCRIPT_VERSION,
           "script_sha256": file_sha256(__file__), "head": a.head,
           "openwiz_sha256": file_sha256(a.openwiz) if a.openwiz else None,
           "preflight": pre, "run": sanitize_run(run, ordinals) if run else "not run"}
    text = json.dumps(rep, indent=1, sort_keys=True)
    hits = [i for i, s in enumerate(forbidden_strings) if leaks(s, text)]
    if hits:
        raise Stop("the report would contain %d forbidden strings; nothing printed"
                   % len(hits))
    write_private(os.path.join(run_dir, "report.json"), text)
    return rep


class Ordinals:
    def __init__(self, run_dir, run):
        ctx_key = open(os.path.join(run_dir, "hmac.key"), "rb").read()
        ids = set()
        for name in os.listdir(run_dir):
            if name.startswith("snapshot-"):
                ids |= set(load(os.path.join(run_dir, name))["rows"])
        ranked = sorted(ids, key=lambda s: hmac.new(ctx_key, s.encode(),
                                                    hashlib.sha256).hexdigest())
        self.map = {s: "s%04d" % (i + 1) for i, s in enumerate(ranked)}
        self.roles = {}
        for role, sid in ((run or {}).get("samples") or {}).items():
            self.roles[sid] = role

    def of(self, sid):
        o = self.map.get(sid, "s-unlisted")
        return o + (" (%s)" % self.roles[sid] if sid in self.roles else "")


def sanitize_args(args, ordinals):
    out = []
    for x in args:
        if x.startswith("thr_synopenwizp4_"):
            out.append("<nonexistent id>")
        elif x in ordinals.map:
            out.append("<" + ordinals.of(x) + ">")
        elif re.match(r"^(ls|show|-l|-a|--hidden|--json|--limit|--offset|[0-9]{1,5})$", x):
            out.append(x)
        else:
            out.append("<other>")
    return out


def call_session(argv, o):
    if len(argv) < 3 or argv[0] != "thread" or argv[1] not in ("show", "output"):
        return None
    if argv[2].startswith("thr_synopenwizp4_"):
        return "<nonexistent id>"
    return o.of(argv[2])


def sanitize_run(run, o):
    t0 = run["started_ms"]
    out = {"stopped": run["stopped"], "duration_ms": run["ended_ms"] - t0,
           "approved_labels": run.get("approved_labels", []),
           "samples": {k: o.of(v) for k, v in (run.get("samples") or {}).items()},
           "samples_missing": run.get("samples_missing"),
           "reads_by_kind": run.get("reads_by_kind"),
           "median_ms_by_kind": run.get("median_ms_by_kind"),
           "checks": run.get("checks"), "late": None, "brackets": [], "m3": run.get("m3")}
    if run.get("late"):
        out["late"] = {"outcome": run["late"]["outcome"],
                       "samples_changed": [o.of(s) for s in run["late"]["samples_changed"]]}

    def sanitize_runs(rs):
        return [{"args": sanitize_args(r["args"], o), "exit": r["exit"],
                 "start_ms": r["start"] - t0, "duration_ms": r["end"] - r["start"],
                 "reads": [{"t_ms": c["t"] - t0,
                            "read": read_kind(c["argv"]) if openwiz_allowed(
                                c["argv"]) else "<not on the allowlist>",
                            "session": call_session(c["argv"], o),
                            "refused": c.get("refused", False)}
                           for c in r["calls"]], "m3": r.get("m3")} for r in rs]

    if run.get("unfinished_bracket"):
        u = run["unfinished_bracket"]
        out["unfinished_bracket"] = {"name": u["name"], "outcome": u["outcome"],
                                     "openwiz_runs": sanitize_runs(u["runs"])}
    for b in run["brackets"]:
        runs = sanitize_runs(b["runs"])
        events = []
        for e in b["events"]:
            reads = e["read_times"]
            for ev in e["events"]:
                t = ev["createdAt"]
                before = [r for r in reads if t is not None and r <= t]
                events.append({"session": o.of(e["id"]), "excluded": e["excluded"],
                               "type": ev["type"], "initiator": ev["initiator"],
                               "source": ev["source"],
                               "t_ms": (t - t0) if t is not None else None,
                               "ms_after_openwiz_read_of_session":
                                   (t - max(before)) if before else None})
            if e.get("more"):
                events.append({"session": o.of(e["id"]), "not_read": "more than %d" % e["read"]})
        out["brackets"].append({
            "name": b["name"], "outcome": b["outcome"], "compared": b["compared"],
            "unchanged": b["unchanged"], "excluded": b["excluded"],
            "fields_missing": b.get("fields_missing"),
            "unexplained": [{"session": o.of(u["id"]), "fields": u["fields"],
                             "read_by_openwiz": u["read_by_openwiz"]}
                            for u in b["unexplained"]],
            "excluded_changed": [{"session": o.of(x["id"]), "reason": x["reason"],
                                  "fields": x["fields"]}
                                 for x in b.get("excluded_changed", [])],
            "excluded_events_not_read": b.get("excluded_events_not_read", 0),
            "active_read_unchanged": b.get("active_read_unchanged", 0),
            "aborted_calls": b.get("aborted_calls", 0),
            "events": events, "refused_calls": b["refused_calls"],
            "samples_changed": [{"session": o.of(s["id"]), "keys": s["keys"]}
                                for s in b["samples_changed"]],
            "poll_changes": [{"session": o.of(p["id"]), "t_ms": p["t"] - t0}
                             for p in b["poll_changes"]],
            "expected_exits": b.get("expected_exits"), "m3": b.get("m3"),
            "fixed_point": b.get("fixed_point"), "openwiz_runs": runs})
    return out


def forbidden(run_dir, a):
    found = set()
    for name in os.listdir(run_dir):
        if not name.startswith("snapshot-"):
            continue
        s = load(os.path.join(run_dir, name))
        found |= set(s["rows"]) | set(s["projects"]) | set(s["projects_hidden"])
        found |= set(s["machines"])
        for r in s["rows"].values():
            for k in ("project", "parent"):
                if isinstance(r.get(k), str) and r[k] != MISSING:
                    found.add(r[k])
    for v in (socket.gethostname(), getpass.getuser(), os.path.expanduser("~"), run_dir,
              os.path.abspath(a.room_cli) if a.room_cli else None,
              os.path.abspath(a.openwiz) if a.openwiz else None):
        if v:
            found.add(v)
    found |= set(a.exclude_id or []) | set(a.forbid or [])
    return sorted(found)


def leaks(value, text):
    if len(value) >= 6:
        return value in text
    return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value),
                     text) is not None


# --------------------------------------------------------------------------
# Offline self-test (synthetic values only; no room-cli)


def cmd_selftest(_a):
    assert observer_allowed(["thread", "list", "--json"])
    assert observer_allowed(["thread", "log", "thr_syn_0001", "--json", "--limit", "1"])
    for bad in (["thread", "send", "thr_syn_0001"], ["thread", "stop", "x"],
                ["thread", "show", "--json", "--json"], ["thread", "log", "x", "--json",
                 "--limit", "101"], ["thread", "list", "--json", "--work-status"],
                ["mac", "run", "true"], ["thread", "archive", "x"], ["project", "create"],
                ["thread", "show", "a b", "--json"], ["thread", "list"]):
        assert not observer_allowed(bad), bad
    assert openwiz_allowed(["thread", "output", "thr_syn_0001", "--json"])
    assert not openwiz_allowed(["thread", "log", "thr_syn_0001", "--json", "--limit", "1"])
    assert not openwiz_allowed(["thread", "count", "--json"])
    assert not openwiz_allowed(["thread", "show", "-x", "--json"])
    assert seqs_of([{"seq": 3}, {"seq": 7}], None) == [3, 7] and seqs_of([], None) == []
    assert seqs_of([{"seq": 3}, {"x": 1}], None) == MISSING
    for v in ("user_message", "jake", "acct_syn_alice", "usr_syn_alice", "private.title"):
        assert label(v) == "other", v
    APPROVED_LABELS.add("user_message")
    assert label("user_message") == "user_message" and label("user_messages") == "other"
    APPROVED_LABELS.discard("user_message")
    assert label(None) == "absent" and label({"x": 1}) == "other"
    assert typed(True, int) == MISSING and typed(None, str) == MISSING and typed(3, int) == 3
    assert seqs_of([{"seq": "7"}], None) == MISSING and seqs_of([{"seq": 2}, "x"], None) == MISSING
    row = list_fields({"status": None, "runtime": {"displayStatus": "idle"}, "activity": {}})
    assert row["status"] == MISSING and row["activity"] == MISSING
    # S8: a duplicated text row is not one-for-one
    RAW["t"] = ("  thr_syn_0001 · status idle · age 1s · location cloud · parent none\n" * 2, "")
    RAW["j"] = (json.dumps({"data": {"sessions": [{"id": "thr_syn_0001",
        "status": {"known": "idle"}, "age_ms": {"known": 1000},
        "location": {"known": {"kind": "cloud"}}, "parent": {"known": None}}]}}), "")
    t = p3_text({"label": "t"}, {"label": "j"})
    assert t["text_rows_duplicated"] == 1 and t["outcome"] == "inconsistent", t
    # S7: grouped under an existing but different project
    snap = {"rows": {"thr_syn_0001": {"project": "prj_syn_a"}}, "projects": ["prj_syn_a",
            "prj_syn_b"], "projects_hidden": []}
    RAW["g"] = (json.dumps({"data": {"sessions": [{"id": "thr_syn_0001", "group": {
        "kind": "project", "id": "prj_syn_b", "name": {"known": "B"}}}]}}), "")
    g = p6(snap, snap, [{"label": "g", "args": ["ls", "--json"],
                         "project_ids": [["prj_syn_a", "prj_syn_b"]]}])
    assert g["grouped_under_another_project"] == 1 and g["outcome"] == "inconsistent", g
    RAW.clear()
    # Sol S1 round 3 (parent diagnosis): brackets where nothing observable was
    # compared are incomplete, and any excluded change stops the run.
    def row(status="idle", read=1):
        return {"status": status, "display": status, "updatedAt": 1, "lastReadAt": read,
                "latestAttentionAt": 1, "queuedWork": "none", "pending": False,
                "activity": 0}

    def snap(name, rows):
        return {"name": name, "rows": rows, "unreadable": {},
                "details": {k: {"gone": False, "qmc": 0, "last_seq": 5} for k in rows}}

    def by_id(sid):
        return [{"calls": [{"t": 0, "argv": ["thread", "show", sid, "--json"]}]}]

    import tempfile
    tmp = tempfile.mkdtemp()

    def bracket(*args):
        """Every synthetic bracket result must survive the run record's own
        save-and-load (write_private, load) unchanged (Sol S10)."""
        r = globals()["bracket"](*args)
        path = os.path.join(tmp, "bracket.json")
        write_private(path, r)
        if load(path) != r:
            raise AssertionError("bracket result does not round-trip through the run record")
        return r

    act, quiet, runner = "thr_syn_act", "thr_syn_quiet", "thr_syn_runner"
    checks = {}
    b = snap("b", {act: row("active")})  # (B) every session excluded, none changed
    checks["B"] = bracket(None, "ls", b, b, [], set())["outcome"] == \
        "incomplete: no quiet session to compare"
    b = snap("b", {act: row("active"), quiet: row()})  # (D) active read by id, unchanged
    r = bracket(None, "ls-l", b, b, by_id(act), set())
    checks["D"] = (r["outcome"] == "incomplete: no quiet session read by id"
                   and r.get("active_read_unchanged") == 1)
    b = snap("b", {quiet: row()})  # (C) a show bracket with no target
    checks["C"] = bracket(None, "show", b, b, [], set())["outcome"] == \
        "incomplete: no quiet session read by id"
    b = snap("b", {runner: row("active"), quiet: row()})  # (A) the runner changed
    a = snap("a", {runner: row("active", read=2), quiet: row()})
    o = bracket(None, "ls", b, a, [], {runner})["outcome"]
    checks["A"] = o == "excluded_changes_need_attribution" and o not in CONTINUE
    failed = sorted(k for k, ok in checks.items() if not ok)
    if failed:
        sys.stderr.write("selftest: S1 round-3 checks failed: %s\n" % ", ".join(failed))
    assert not failed
    # Sol S9: a session still in thread list whose detail read is not found in
    # both snapshots is missing proof, never unchanged.
    lost = "thr_syn_lost"
    b = snap("b", {lost: row(), quiet: row()})
    b["details"][lost] = {"gone": True}
    r = bracket(None, "ls-l", b, b, by_id(quiet), set())
    if not (r["outcome"].startswith("incomplete: ") and r["unchanged"] == 1
            and r["fields_missing"] == 1):
        sys.stderr.write("selftest: S9 check failed: %s, unchanged %d, fields_missing %d\n"
                         % (r["outcome"], r["unchanged"], r["fields_missing"]))
        raise AssertionError("S9")
    # Sol S10: the S9 case plus an unchanged active session: only string
    # exclusion reasons, and the result saves and loads.
    b = snap("b", {lost: row(), quiet: row(), act: row("active")})
    b["details"][lost] = {"gone": True}
    r = bracket(None, "ls-l", b, b, by_id(quiet), set())
    assert all(isinstance(k, str) for k in r["excluded"]), "S10: a non-string exclusion reason"
    assert r["outcome"].startswith("incomplete: ") and r["fields_missing"] == 1, "S10"
    assert sum(r["excluded"].values()) == 1, "S10: the lost session was counted as excluded"
    shutil.rmtree(tmp)
    assert not observer_allowed(["thread", "log", "x", "--json", "--limit", "\u00b2"])
    quiet = {"status": "idle", "display": "idle", "queuedWork": "none", "pending": False,
             "activity": 0, "qmc": 0}
    assert not_quiet(quiet) is None
    assert not_quiet(dict(quiet, status="active")).startswith("status")
    assert not_quiet(dict(quiet, qmc=1)) == "queued messages"
    assert leaks("thr_syn_0001", "x thr_syn_0001 y") and not leaks("jp", "ajpb")
    assert leaks("jp", "user jp here")
    assert read_kind(["thread", "show", "thr_syn_0001", "--json"]) == "thread show --json"
    assert read_kind(["thread", "log", "--help"]) == "thread log --help"
    assert view_of(["ls", "-a", "--hidden", "--json"]) == "both"
    # The forward allowlist is exactly the routes §7.1 lists for the reads (M2_ROUTES).
    assert {r for v in M2_ROUTES.values() for _, r in v} == {t for t, _, _ in FORWARD_ROUTES}, \
        "FORWARD_ROUTES"
    return {"selftest": "ok"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "run", "report"):
        s = sub.add_parser(name)
        s.add_argument("--run-dir", required=True)
        s.add_argument("--room-cli", required=(name != "report"),
                       help="absolute path of the room-cli to observe (never looked up)")
        s.add_argument("--concurrency", type=int, default=4)
        s.add_argument("--exclude-id", action="append",
                       help="the runner's own session (repeatable); never reported")
        if name == "preflight":
            s.add_argument("--endpoint-check", action="store_true",
                           help="also read room-cli status --json (needs Jake's approval)")
        if name in ("run", "report"):
            s.add_argument("--openwiz", required=(name == "run"))
        if name == "run":
            s.add_argument("--control-wait", type=float, default=10)
            s.add_argument("--poll-interval", type=float, default=2)
            s.add_argument("--settle", type=float, default=120)
            s.add_argument("--late", type=float, default=600)
            s.add_argument("--approve-label", action="append",
                           help="an event label value Jake approved for the report "
                                "(repeatable); every other value is reported as other")
            s.add_argument("--upstream-default", required=True,
                           help="M3: the server URL room-cli uses when ROOM_SERVER_URL is unset, "
                                "as M2 recorded it (loopback http only)")
            s.add_argument("--egress-sandbox", action="store_true",
                           help="decision D21: run every bracketed OpenWiz call under sandbox-exec, "
                                "outbound network only to the proxy's loopback port")
            s.add_argument("--sandbox-exec", default="/usr/bin/sandbox-exec", help=argparse.SUPPRESS)
            s.add_argument("--accept-missing-sample", action="append",
                           choices=["cloud_on_page", "local_on_page", "cloud_off_page",
                                    "local_off_page"],
                           help="Jake's decision D12: run without this sample kind")
        if name == "report":
            s.add_argument("--head", required=True, help="the exact commit tested")
            s.add_argument("--forbid", action="append",
                           help="another string the report must not hold (Jake's login, "
                                "names, ...); repeatable; never reported")
    sub.add_parser("selftest")
    a = p.parse_args(argv)
    try:
        result = {"preflight": cmd_preflight, "run": cmd_run, "report": cmd_report,
                  "selftest": cmd_selftest}[a.cmd](a)
    except Stop as e:
        print(json.dumps({"stopped": str(e)}))
        return 10
    except KeyboardInterrupt:  # Sol's sweep, finding 3: a fixed message, no traceback
        print(json.dumps({"stopped": "interrupted"}))
        return 130
    except Exception as e:  # its message could hold an id: print the type only
        print(json.dumps({"stopped": "unexpected error: %s" % type(e).__name__}))
        return 11
    # A run that stopped, or failed, after saving its evidence still exits
    # non-zero, so a caller (procedures §11 step 5) sees the stop.
    if isinstance(result, dict) and result.get("stopped"):
        print(json.dumps(result, indent=1, sort_keys=True))
        return 11 if str(result["stopped"]).startswith("unexpected error") else 10
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # one outside main()'s own handler (argument parsing)
        print(json.dumps({"stopped": "interrupted"}))
        sys.exit(130)
