#!/usr/bin/env python3
"""Test-only stand-in for room-cli, for testing observe.py. SYNTHETIC ONLY.

The repository's fake room-cli answers OpenWiz's allowlisted reads, and
refuses everything else. The observer also needs `thread log`,
`thread count`, `status` and `--help`. This stub answers those itself with
invented values, and hands every other call to the repository's fake (a
symlink `room-cli-fake` next to it), so the fake's own allowlist and fixtures
stay in force.

Event logs (synthetic). `thread log <id> --json [--after-seq S] --limit N`
behaves as room-cli 0.43.1's help and client code say (procedures §7.1, M2):
the OLDEST N events, or the oldest N whose sequence number is greater than S.
Each synthetic session has its own log shape, so the observer's search meets
every case: thr_syn_0001 250 events, 0002 10, 0003 none, 0004 1234 sparse
(1, 4, 7, ...), 0005 exactly 100, 0006 5, 0007 101, 0008 3; any other id 10.

When ROOM_SERVER_URL is set (the observer's M3 step points it at its proxy),
the stub first makes the HTTP requests that M2 found the real client makes
for that read, with a planted Authorization header, cookie and query value,
then answers as usual from the fake.

Environment switches, to show the observer's stop rules work:
- STUB_VERSION: print this as `--version` instead of asking the fake;
- STUB_LOG_NEWEST=1: `thread log --limit N` (without --after-seq) returns
  the newest N events (not what the help says);
- STUB_AFTER_SEQ=inclusive: `--after-seq S` also returns the event at S;
- STUB_AFTER_SEQ=ignored: `--after-seq` is ignored (the oldest N);
- STUB_LOG_FEW=1: every log has at most 2 events;
- STUB_PAGE_CAP=N: every thread log read returns at most N events, whatever
  --limit says (a server with a smaller window);
- STUB_MUTATE=openwiz-show: a `thread show` that comes from OpenWiz (through
  the shim, so OPENWIZ_SHIM_LOG is set) adds an event to that session;
- STUB_MUTATE=openwiz-show-3: the same, but three events each time;
- STUB_MUTATE=openwiz-show-60: the same, but sixty events each time;
- STUB_MUTATE=openwiz-show-active: the same, but only for the two synthetic
  sessions that are already active (thr_syn_0002 and thr_syn_0006);
- STUB_MUTATE=openwiz-list-active: an OpenWiz `thread list` adds an event to
  the already-active thr_syn_0002 (a list read with an effect);
- STUB_MUTATE=openwiz-list-fails: OpenWiz's `thread list` exits 1, so
  `openwiz ls` exits 1 (the observer's own reads still answer);
- STUB_MUTATE=observer-output-runner: an observer's `thread output` (not
  OpenWiz's) adds an event to thr_syn_0002, standing in for the runner;
- STUB_MUTATE=any-output: any `thread output` adds an event to that session;
- STUB_MUTATE=show-marks-read: with ROOM_SERVER_URL set, `thread show` also
  posts a mark-read (POST /api/v1/threads/<id>/read) with a planted body;
- STUB_MUTATE=show-extra-get: with ROOM_SERVER_URL set, `thread show` also
  makes a GET that M2 does not list (/api/v1/threads/<id>/conversation-outline);
- STUB_MUTATE=show-get-wake: `thread show` also makes GETs to
  /api/v1/threads/<id>/wake and .../mark-read (effect words outside the
  client's route words);
- STUB_MUTATE=show-fails: the observer's own `thread show` of an existing
  session exits 1 before any request;
- STUB_MUTATE=openwiz-skip-proxy: reads that come from OpenWiz (through the
  shim) send no request to ROOM_SERVER_URL (what skipping the proxy looks like);
- STUB_MUTATE=openwiz-skip-one-show: only the second `thread show` that comes
  from OpenWiz skips ROOM_SERVER_URL (one call among several of its kind);
- STUB_MUTATE=missing-500: `thread show` of the nonexistent id fails with an
  HTTP 500 instead of the expected 404;
- STUB_MUTATE=openwiz-skip-project-list: `project list` from OpenWiz (the
  shim's child) sends no request to ROOM_SERVER_URL;
- STUB_MUTATE=observer-skip-count: the observer's `thread count` sends no
  request to ROOM_SERVER_URL;
- STUB_MUTATE=direct-list-fails: `thread list --json` run without
  ROOM_SERVER_URL exits 1;
- STUB_MUTATE=observer-show-marks-read: the observer's own `thread show`
  posts a mark-read (the show-* mutations above apply only to OpenWiz's calls);
- STUB_MUTATE=observer-skip-log: the observer's `thread log` sends no request
  to ROOM_SERVER_URL;
- STUB_MUTATE=observer-list-fails: the observer's `thread list` exits 1;
- STUB_MUTATE=allowed-get-marks-read: an OpenWiz `thread show` sends only the
  allowed GETs, but "the server" marks that session read: its `lastReadAt` in
  every later `thread list` is one higher (Sol S1: an effect M3 cannot see,
  which the bracket must catch);
- STUB_MUTATE=observer-log-pages-then-skip: the observer's first `thread log`
  of each session sends its request twice (a read that pages), and its second
  sends none (Sol N-R1 round 2: the surplus must not cover the skipped call);
- STUB_MUTATE=openwiz-output-covered-by-show: an OpenWiz `thread show` also
  reads that session's output (as the real client does for a session in
  error), and OpenWiz's `thread output` sends no request;
- STUB_MUTATE=openwiz-list-marks-active: an OpenWiz `thread list` moves the
  already-active thr_syn_0002's lastReadAt (quick-check: listed separately);
- STUB_DROP_FIELD=<field>: the observer's thread list rows of the unchanged,
  hidden thr_syn_0007 lack that field (quick check: unknown activity);
- STUB_VIEW_SKEW=<id>: in the observer's thread list views without
  --include-hidden (default, archived), that session's lastReadAt differs from
  the combined list's (quick check: views_disagree by class);
- STUB_MUTATE=qc-after-transition: from OpenWiz's first list read on, the
  observer's narrower views show the quiet thr_syn_0004 running, and the
  combined view idle with background activity (Sol's views-fix probe);
- STUB_LOG_EMPTY=1: every log starts empty (appended events still count);
- STUB_MUTATE=qc-unknown-activity / qc-hidden-view-change / qc-openwiz-show-fails /
  qc-no-qmc / qc-bad-id: the quick check's cases that must never pass (an
  unreadable activity on a changed session; a change seen only in the hidden
  views; OpenWiz's thread show failing; an unreadable queue count; an
  unreadable row id);
- STUB_EXEC_LOG=<file>: every call appends its arguments to <file> (to show
  whether the client ran at all);
- STUB_MUTATE=observer-show-touches-always / -once: every observer `thread
  show` of a synthetic session (always), or only the first per session (once),
  moves that session's lastReadAt;
- STUB_MUTATE=drop-base-path: requests ignore ROOM_SERVER_URL's path (a client
  that drops the run's /c/<token> prefix).
"""

import fcntl
import http.client
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
STATE = os.path.join(HERE, "stub-state.json")
BASE_TIME = 1700000000000
# (events, step between sequence numbers) per synthetic session
SHAPES = {"thr_syn_0001": (250, 1), "thr_syn_0002": (10, 1), "thr_syn_0003": (0, 1),
          "thr_syn_0004": (1234, 3), "thr_syn_0005": (100, 1), "thr_syn_0006": (5, 1),
          "thr_syn_0007": (101, 1), "thr_syn_0008": (3, 1)}
PLANTED_AUTH = "synthetic-planted-authorization-0001"
PLANTED_COOKIE = "synthetic-planted-cookie-0001"
PLANTED_QUERY = "synthetic-planted-query-value-0001"
PLANTED_BODY = "synthetic-planted-body-0001"


def bump(sid, n=1):
    with open(STATE + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.load(open(STATE)) if os.path.exists(STATE) else {}
        state[sid] = state.get(sid, 0) + n
        with open(STATE + ".tmp", "w") as f:
            json.dump(state, f)
        os.replace(STATE + ".tmp", STATE)  # readers without the lock never see a partial file
        return state[sid]


def seqs_of(sid):
    """The session's sequence numbers, oldest first: its shape, then the
    events the switches above appended."""
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    count, step = SHAPES.get(sid, (10, 1))
    if os.environ.get("STUB_LOG_EMPTY"):
        count = 0  # every log starts empty; appended events still count
    if os.environ.get("STUB_LOG_FEW"):
        count = min(count, 2)
    count += state.get(sid, 0)
    return [1 + i * step for i in range(count)]


def seqs_count(key):
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    return state.get(key, 0)


def log_events(sid, after, n):
    seqs = seqs_of(sid)
    mode = os.environ.get("STUB_AFTER_SEQ", "")
    if after is not None and mode != "ignored":
        seqs = [s for s in seqs if (s >= after if mode == "inclusive" else s > after)]
        seqs = seqs[:n]
    elif os.environ.get("STUB_LOG_NEWEST"):
        seqs = seqs[-n:]
    else:
        seqs = seqs[:n]
    if os.environ.get("STUB_PAGE_CAP"):
        seqs = seqs[:int(os.environ["STUB_PAGE_CAP"])]
    return [{"id": "evt_syn_%d" % s, "scope": {"kind": "thread"}, "threadId": sid, "seq": s,
             "createdAt": BASE_TIME + s, "type": "synthetic_event",
             "data": {"initiator": "synthetic", "input": "synthetic"}} for s in seqs]


def requests_for(argv):
    """The requests M2 found room-cli 0.43.1 makes for this read (synthetic ids),
    in the canonical form the M3 proxy accepts: the query names and values the
    client's code builds for these flags, nothing else (Jake's "canonical only"
    round: a planted query parameter would now be refused, so it is tested in
    unit-tests.py instead)."""
    if argv[:2] == ["thread", "list"]:
        hidden, archived = "--include-hidden" in argv, "--include-archived" in argv
        query = [] if archived else ["archived=false"]
        query += ["includeHidden=true"] if hidden else []
        return [("GET", "/api/v1/threads" + ("?" + "&".join(query) if query else ""), None)]
    if argv[:2] == ["project", "list"]:
        return [("GET", "/api/v1/projects?includePersonal=true"
                 + ("&hidden=true" if "--hidden" in argv else ""), None)]
    if argv[:2] == ["machine", "list"]:
        return [("GET", "/api/v1/hosts?includeCreating=true", None)]
    if argv[:2] == ["thread", "count"]:
        return [("GET", "/api/v1/threads/count", None)]
    if len(argv) < 3 or argv[0] != "thread" or argv[2].startswith("-"):
        return []
    sid = urllib.parse.quote(argv[2], safe="")
    if argv[1] == "output":
        return [("GET", "/api/v1/threads/%s/output" % sid, None)]
    if argv[1] == "log":
        after = ("afterSeq=%s&" % argv[argv.index("--after-seq") + 1]) if "--after-seq" in argv else ""
        return [("GET", "/api/v1/threads/%s/events?%slimit=2" % (sid, after), None)]
    if argv[1] != "show":
        return []
    out = [("GET", "/api/v1/threads/%s" % sid, None)]
    if argv[2].startswith("thr_synopenwizp4_"):
        return out
    env = "/api/v1/environments/env_syn_0001"
    out += [("GET", env + "/pull-request", None), ("GET", env, None),
            ("GET", "/api/v1/threads/%s/timeline?summaryOnly=true" % sid, None),
            ("GET", ("/api/v1/cloudroom/threads/%s" % sid) if argv[2] in
             ("thr_syn_0001", "thr_syn_0003", "thr_syn_0005", "thr_syn_0006")
             else "/api/v1/threads/%s/default-execution-options" % sid, None),
            ("GET", env, None)]
    # The show-* mutations model OpenWiz's calls (through the shim); the
    # observer-show-marks-read variant models the observer's own (Sol N-R1).
    mutate = os.environ.get("STUB_MUTATE", "")
    from_shim = "OPENWIZ_SHIM_LOG" in os.environ
    if not from_shim and mutate == "observer-show-marks-read":
        mutate = "show-marks-read"
    elif not from_shim:
        mutate = ""
    if mutate == "show-get-wake":
        out += [("GET", "/api/v1/threads/%s/wake" % sid, None),
                ("GET", "/api/v1/threads/%s/mark-read" % sid, None)]
    if mutate == "show-extra-get":
        out.append(("GET", "/api/v1/threads/%s/conversation-outline" % sid, None))
    if mutate == "openwiz-output-covered-by-show":
        out.append(("GET", "/api/v1/threads/%s/output" % sid, None))
    if mutate == "show-marks-read":
        out.append(("POST", "/api/v1/threads/%s/read" % sid,
                    json.dumps({"token": PLANTED_BODY}).encode()))
    return out


def send_requests(argv, times=1):
    # The base URL's path (the run's per-call token, /c/<token>) comes first,
    # as the real client builds ${baseUrl}/api/v1/... (M2).
    url = urllib.parse.urlsplit(os.environ["ROOM_SERVER_URL"])
    for method, path, body in requests_for(argv) * times:
        if os.environ.get("STUB_MUTATE") != "drop-base-path":
            path = url.path.rstrip("/") + path
        c = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        headers = {"Authorization": "Bearer " + PLANTED_AUTH,
                   "Cookie": "c=" + PLANTED_COOKIE, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        c.request(method, path, body=body, headers=headers)
        c.getresponse().read()
        c.close()


def main():
    argv = sys.argv[1:]
    if os.environ.get("STUB_EXEC_LOG"):  # a test that must see whether the client ran at all
        with open(os.environ["STUB_EXEC_LOG"], "a") as f:
            f.write(json.dumps(argv) + "\n")
    mutate = os.environ.get("STUB_MUTATE", "")
    if (mutate == "show-fails" and "OPENWIZ_SHIM_LOG" not in os.environ
            and argv[:2] == ["thread", "show"] and argv[2].startswith("thr_syn_")):
        sys.stderr.write("Error: synthetic failure\n")
        return 1
    from_shim = "OPENWIZ_SHIM_LOG" in os.environ
    skip = (mutate == "openwiz-skip-proxy" and from_shim
            or mutate == "openwiz-skip-project-list" and from_shim and argv[:2] == ["project", "list"]
            or mutate == "observer-skip-count" and not from_shim and argv[:2] == ["thread", "count"]
            or mutate == "observer-skip-log" and not from_shim and argv[:2] == ["thread", "log"])
    if mutate == "observer-list-fails" and not from_shim and argv[:2] == ["thread", "list"]:
        sys.stderr.write("Error: synthetic failure\n")
        return 1
    if (mutate == "direct-list-fails" and not os.environ.get("ROOM_SERVER_URL")
            and argv == ["thread", "list", "--json"]):
        sys.stderr.write("Error: synthetic failure\n")
        return 1
    if (mutate == "openwiz-skip-one-show" and "OPENWIZ_SHIM_LOG" in os.environ
            and argv[:2] == ["thread", "show"]):
        bump("__shows__")
        skip = seqs_count("__shows__") == 2
    times = 1
    if mutate == "observer-log-pages-then-skip" and not from_shim and argv[:2] == ["thread", "log"]:
        times = {1: 2, 2: 0}.get(bump("pages:" + argv[2]), 1)
    if mutate == "openwiz-output-covered-by-show" and from_shim and argv[:2] == ["thread", "output"]:
        skip = True
    if os.environ.get("ROOM_SERVER_URL") and not skip:
        send_requests(argv, times)
    if (mutate == "missing-500" and argv[:2] == ["thread", "show"]
            and argv[2].startswith("thr_synopenwizp4_")):
        sys.stderr.write("Error: HTTP 500: synthetic failure\n")
        return 1
    if argv == ["--version"] and os.environ.get("STUB_VERSION"):
        print(os.environ["STUB_VERSION"])
        return 0
    if argv and argv[-1] == "--help":
        print("synthetic stub help: --json --limit --include-hidden --include-archived")
        return 0
    if argv == ["status", "--json"]:
        print(json.dumps({"serverUrl": "http://127.0.0.1:1/", "dataDir": "/synthetic"}))
        return 0
    if argv == ["thread", "count", "--json"]:
        fake_dir = os.path.dirname(os.path.realpath(
            open(os.path.join(HERE, "fake-room-cli.scenario")).read().strip()))
        rows = json.load(open(os.path.join(fake_dir, "thread-list.json")))
        print(json.dumps({"total": len(rows)}))
        return 0
    if len(argv) in (6, 8) and argv[:2] == ["thread", "log"] and argv[-2] == "--limit":
        after = int(argv[5]) if argv[4] == "--after-seq" else None
        print(json.dumps(log_events(argv[2], after, int(argv[-1])), indent=2))
        return 0
    if (mutate in ("openwiz-show", "openwiz-show-3", "openwiz-show-60")
            and "OPENWIZ_SHIM_LOG" in os.environ and argv[:2] == ["thread", "show"]):
        bump(argv[2], {"openwiz-show-3": 3, "openwiz-show-60": 60}.get(mutate, 1))
    if (mutate == "openwiz-show-active" and "OPENWIZ_SHIM_LOG" in os.environ
            and argv[:2] == ["thread", "show"] and argv[2] in ("thr_syn_0002", "thr_syn_0006")):
        bump(argv[2])
    from_openwiz = "OPENWIZ_SHIM_LOG" in os.environ
    # Quick check, Sol's sweep: the cases that must never pass.
    if mutate == "qc-unknown-activity" and from_openwiz and argv[:2] == ["thread", "list"]:
        bump("read:thr_syn_0001")  # a change in a session whose activity is unreadable
    if mutate == "qc-after-transition" and from_openwiz and argv[:2] == ["thread", "list"]:
        bump("transition")  # from OpenWiz's first list read on, the after reads see the transition
    if mutate == "qc-hidden-view-change" and from_openwiz and argv[:2] == ["thread", "list"]:
        bump("hread:thr_syn_0001")  # a change seen only in the --include-hidden views
    if (mutate == "qc-openwiz-show-fails" and from_openwiz and argv[:2] == ["thread", "show"]
            and argv[2].startswith("thr_syn_")):
        sys.stderr.write("Error: synthetic failure\n")
        return 1
    if mutate == "qc-no-qmc" and not from_openwiz and argv[:2] == ["thread", "show"]:
        import subprocess
        p = subprocess.run([os.path.join(HERE, "room-cli-fake")] + argv, stdout=subprocess.PIPE)
        doc = json.loads(p.stdout) if p.returncode == 0 else None
        if isinstance(doc, dict) and isinstance(doc.get("thread"), dict):
            doc["thread"].pop("queuedMessageCount", None)  # an unreadable queue count
            print(json.dumps(doc))
            return 0
        sys.stdout.buffer.write(p.stdout)
        return p.returncode
    if mutate == "openwiz-list-marks-active" and from_openwiz and argv[:2] == ["thread", "list"]:
        bump("read:thr_syn_0002")  # an already-active session's lastReadAt moves (quick check)
    if mutate == "openwiz-list-active" and from_openwiz and argv[:2] == ["thread", "list"]:
        bump("thr_syn_0002")
    if mutate == "openwiz-list-fails" and from_openwiz and argv[:2] == ["thread", "list"]:
        sys.stderr.write("Error: HTTP 500: synthetic failure\n")
        return 1
    if mutate == "observer-output-runner" and not from_openwiz and argv[:2] == ["thread", "output"]:
        bump("thr_syn_0002")
    if mutate == "any-output" and argv[:2] == ["thread", "output"]:
        bump(argv[2])
    # Finding 1, final round: an observer read with an effect on the session it
    # reads. "always": every observer thread show moves lastReadAt (not
    # idempotent); "once": only the first one per session does (idempotent).
    if (mutate in ("observer-show-touches-always", "observer-show-touches-once") and not from_openwiz
            and argv[:2] == ["thread", "show"] and argv[2].startswith("thr_syn_")):
        if mutate.endswith("always") or bump("touched:" + argv[2]) == 1:
            bump("read:" + argv[2])
    if (mutate == "allowed-get-marks-read" and from_openwiz
            and argv[:2] == ["thread", "show"] and argv[2].startswith("thr_syn_")):
        bump("read:" + argv[2])
    fake = os.path.join(HERE, "room-cli-fake")
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    marks = {k[5:]: v for k, v in state.items() if k.startswith("read:")}
    if "--include-hidden" in argv:
        for k, v in state.items():
            if k.startswith("hread:"):
                marks[k[6:]] = marks.get(k[6:], 0) + v
    drop = os.environ.get("STUB_DROP_FIELD") if not from_openwiz else None
    skew = os.environ.get("STUB_VIEW_SKEW") if not from_openwiz and "--include-hidden" not in argv else None
    transition = (mutate == "qc-after-transition" and not from_openwiz and state.get("transition"))
    if argv[:2] == ["thread", "list"] and (marks or drop or skew or transition
                                           or mutate in ("qc-unknown-activity", "qc-bad-id")):
        import subprocess
        p = subprocess.run([fake] + argv, stdout=subprocess.PIPE)
        rows = json.loads(p.stdout)
        for row in rows:
            if row.get("id") in marks and isinstance(row.get("lastReadAt"), int):
                row["lastReadAt"] += marks[row["id"]]
            if mutate == "qc-unknown-activity" and row.get("id") == "thr_syn_0001":
                row.pop("activity", None)  # its activity cannot be read
            if drop and row.get("id") == "thr_syn_0007":
                row.pop(drop, None)  # an unchanged session whose activity cannot be read
            if transition and row.get("id") == "thr_syn_0004":
                # Sol's probe: quiet before; in the after reads a narrower view shows it
                # running, and the combined view idle again with background activity.
                if "--include-hidden" in argv:
                    row["activity"] = dict(row.get("activity") or {}, activeBackgroundCommandCount=1)
                else:
                    row["status"] = "running"
                    row.setdefault("runtime", {})["displayStatus"] = "running"
            if skew and row.get("id") == skew and isinstance(row.get("lastReadAt"), int):
                row["lastReadAt"] += 1000  # this session's row differs between views
        if mutate == "qc-bad-id":
            for row in rows:
                if row.get("id") == "thr_syn_0007":
                    row["id"] = "thr_syn_0007!"  # an id the id rule cannot read
        print(json.dumps(rows))
        return p.returncode
    os.execv(fake, [fake] + argv)


if __name__ == "__main__":
    sys.exit(main())
