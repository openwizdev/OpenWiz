#!/usr/bin/env python3
"""OpenWiz 0.0.1 ticket 3 (#4): the quick live check (Jake's "simplify", D23).

Read-only, standard-library Python. It replaces the full observer run of
procedures §6 and §7 with one before-and-after comparison around a few OpenWiz
runs, honest about its limits (quick-check.md). It reuses observe.py's proven
helpers, from the same folder: the list fields, the last-sequence search, the
shim that logs OpenWiz's own room-cli reads, P1, P4, P6 and the leak check. No
proxy, no call tokens.

    quick-check.py run --room-cli <abs path> --openwiz <abs path> --run-dir <new dir>
                       [--exclude-id <id> ...] [--forbid <string> ...] [--wait 120] [--samples 20]

1. Before: every session's list fields (thread list, the four views), both
   project lists, the machine list; and, for up to 20 quiet idle samples (cloud
   and local), thread show (queuedMessageCount) and the last event number.
2. OpenWiz: ls, ls -l, show <sample> for 3 samples, show <a nonexistent id>
   (P4), then the P1 inventory (counts and pages per view; P6 on its JSON).
3. Wait (default 120 s), then the after snapshot, and each sample's new events.
4. Compare: a change in a compared field, or a new event in a sample, is a
   failure, unless the session was already active before (listed separately)
   or excluded. Report: structure only (fields and counts, never an id).

Exit 0: pass. 10: a failure, an inconsistent P-check, or a stop. 11: a script
error (its type only). The version read is recorded, never a gate (#37, (b)).
"""

import argparse
import json
import os
import re
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe  # noqa: E402

COMPARED = ("status", "display", "updatedAt", "lastReadAt", "latestAttentionAt")
SAMPLES = 20
SHOWS = 3
READ_BUDGET = 1000


def _known(value, kind):
    return isinstance(value, kind) and not (kind is int and isinstance(value, bool)) \
        and value != observe.MISSING


def classify(row):
    """"active" (observed activity), "quiet", or "unknown" (a field that decides
    it cannot be read: never taken as active or quiet; Sol's sweep, 1)."""
    status, display = row.get("status"), row.get("display")
    if not (_known(status, str) and _known(display, str)):
        return "unknown"
    if status not in observe.QUIET or display not in observe.QUIET:
        return "active"
    queued, pending, activity = row.get("queuedWork"), row.get("pending"), row.get("activity")
    if not (_known(queued, str) and _known(pending, bool) and _known(activity, int)):
        return "unknown"
    return "active" if queued != "none" or pending or activity != 0 else "quiet"


def lists(ctx, name):
    """Every session's list fields, by view, and the project and machine lists.
    The fields compared are the combined (hidden and archived) list's; the
    narrower views are read for P1, and any row of theirs that differs from the
    combined list's, or is missing from it, is counted (Sol's sweep, 5)."""
    snap = {"name": name, "views": {}, "rows": {}, "details": {}}
    per_view = {}
    for view, flags in observe.LIST_VIEWS:
        rows = ctx.room_json(["thread", "list", "--json"] + flags)
        if not isinstance(rows, list):
            raise observe.Stop("thread list printed no array")
        ids = []
        for row in rows:
            sid = row.get("id") if isinstance(row, dict) else None
            if not isinstance(sid, str) or not observe.ID_RE.match(sid):
                snap.setdefault("unreadable", {}).setdefault(view, 0)
                snap["unreadable"][view] += 1
                continue
            ids.append(sid)
            per_view.setdefault(view, {})[sid] = observe.list_fields(row)
        snap["views"][view] = ids
    snap["rows"] = dict(per_view.get("both", {}))
    disagree = set()
    for view, rows in per_view.items():
        for sid, fields in rows.items():
            if sid not in snap["rows"]:
                snap["rows"][sid] = fields
                disagree.add(sid)
            elif fields != snap["rows"][sid]:
                disagree.add(sid)
    snap["views_disagree"] = sorted(disagree)  # in memory and the private run directory only
    for key, flags in (("projects", []), ("projects_hidden", ["--hidden"])):
        rows = ctx.room_json(["project", "list", "--json", "--include-personal"] + flags)
        snap[key] = sorted(r["id"] for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str))
    rows = ctx.room_json(["machine", "list", "--json"])
    snap["machines"] = sorted(r["id"] for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str))
    return snap


def choose_samples(snap, exclude, n=SAMPLES):
    """Up to n quiet idle sessions, cloud and local alternately, in OpenWiz's own
    order (so the first ones are on the ls -l page)."""
    rows = snap["rows"]
    quiet = [s for s in observe.default_order(snap)
             if s not in exclude and classify(rows[s]) == "quiet"
             and rows[s].get("status") == "idle" and rows[s].get("display") == "idle"]
    cloud = [s for s in quiet if rows[s].get("cloud")]
    local = [s for s in quiet if rows[s].get("host") and not rows[s].get("cloud")]
    out = []
    for i in range(n):
        for kind in (cloud, local):
            if i < len(kind) and len(out) < n:
                out.append(kind[i])
    rest = [s for s in quiet if s not in out]
    return out + rest[:max(0, n - len(out))]


def version_record(ctx):
    """The version read, recorded only (never a gate): the text if it is a bare
    version, else that it was not, and the first version-like token in it."""
    r = ctx.room(["--version"])
    text = r.stdout.decode("utf-8", "replace").strip()
    if re.fullmatch(r"[0-9]+(\.[0-9]+)*", text):
        return {"exit": r.returncode, "version": text}
    m = re.search(r"\b[0-9]+\.[0-9]+\.[0-9]+\b", text)
    return {"exit": r.returncode, "version": None, "text": "not a bare version (not printed)",
            "version_like_token": m.group(0) if m else None}


def compare(before, after, exclude):
    failures, active, excluded, unclassified, missing = {}, {}, {}, {}, 0

    def add(d, k):
        d[k] = d.get(k, 0) + 1

    for sid in sorted(set(before["rows"]) | set(after["rows"])):
        b, a = before["rows"].get(sid), after["rows"].get(sid)
        if b is None or a is None:
            changed = ["appeared" if b is None else "disappeared"]
        else:
            changed = [f for f in COMPARED if b.get(f, observe.MISSING) != a.get(f, observe.MISSING)]
            if any(b.get(f, observe.MISSING) == observe.MISSING for f in COMPARED):
                missing += sid not in exclude
        for f in changed:
            if sid in exclude:
                add(excluded, f)
            elif b is not None and classify(b) == "active":
                add(active, f)
            elif b is not None and classify(b) == "unknown":
                add(unclassified, f)  # cannot be judged: incomplete, never a pass
            else:
                add(failures, f)
    return failures, active, excluded, unclassified, missing


def sample_eval(ctx, sid, d_b, d_a):
    """One sample, before and after: unreadable (gone, a queue count or last
    number that cannot be read, or a number that went down), its sequence
    advance, and the new events actually read (at most 50: truncation is
    reported). An empty log's last number is None, counted as 0 (Sol's sweep,
    2, 7, 8)."""
    def seq(d):
        v = d.get("last_seq")
        return 0 if v is None else v if _known(v, int) else observe.MISSING

    b, a = seq(d_b), seq(d_a)
    unreadable = (d_b.get("gone", True) or d_a.get("gone", True) or observe.MISSING in (a, b)
                  or not _known(d_b.get("qmc"), int) or not _known(d_a.get("qmc"), int)
                  or a < b)
    res = {"unreadable": bool(unreadable), "advance": 0, "observed": 0, "truncated": False,
           "types": [], "qmc_changed": False}
    if unreadable:
        return res
    res["qmc_changed"] = d_a["qmc"] != d_b["qmc"]
    if a > b:
        ev = observe.new_events(ctx, sid, d_b.get("last_seq"), a)
        res.update(advance=a - b, observed=ev["read"], truncated=bool(ev["more"]),
                   types=[e["type"] for e in ev["events"]])
    return res


def build_report(run, version, before, after, exclude, samples, sample_res, runs, checks, reads,
                 binary=None):
    failures, active, excluded, unclassified, missing = compare(before, after, exclude)
    sample_fail = sum(1 for r in sample_res.values() if r["advance"] or r["qmc_changed"])
    runs_failed = sum(1 for r in runs if r["exit"] != r["expected_exit"])
    refused = sum(1 for r in runs for c in r["calls"] if c.get("refused"))
    unreadable_rows = sum(sum(s.get("unreadable", {}).values()) for s in (before, after))
    # Finding 1, round 2: a non-excluded session whose activity cannot be read,
    # before or after, makes the result incomplete, changed or not.
    unclassified_sessions = sum(
        1 for sid in set(before["rows"]) | set(after["rows"]) if sid not in exclude
        and any(classify(s["rows"][sid]) == "unknown" for s in (before, after) if sid in s["rows"]))
    # Jake's "fix and rerun" (2026-10-29), and Sol's review of it: a session
    # whose rows differ between views, in either snapshot, is classed by its
    # combined-list row in the BEFORE snapshot, exactly as the before/after
    # comparison classes a change: excluded; already active before (reported, not
    # judged); or else judged (quiet, unknown, or absent before: incomplete). A
    # session quiet before stays judged however it looks in the after reads.
    views_disagree = {"quiet": 0, "active": 0, "excluded": 0}
    for snap in (before, after):
        for sid in snap["views_disagree"]:
            cls = ("excluded" if sid in exclude else
                   "active" if sid in before["rows"] and classify(before["rows"][sid]) == "active"
                   else "quiet")
            views_disagree[cls] += 1
    inconsistent = (any(c.get("outcome") == "inconsistent" for c in checks.values())
                    or any(v.get("outcome") == "inconsistent" for v in checks.get("P1", {}).values()
                           if isinstance(v, dict)))
    # Sol's sweep: anything that cannot be compared is incomplete, never a pass.
    outcome = ("failure" if failures or sample_fail or inconsistent or runs_failed or refused
               else "incomplete" if (missing or unclassified or unclassified_sessions
                                     or unreadable_rows or views_disagree["quiet"]
                                     or any(r["unreadable"] for r in sample_res.values()))
               else "pass")
    return {
        "report": "openwiz-0.0.1-quick-check", "script_sha256": observe.file_sha256(__file__),
        "observe_sha256": observe.file_sha256(observe.__file__), "outcome": outcome,
        "version_read": version,
        "openwiz_binary": binary or {"sha256_matches": None, "head": None, "head_matches": None},
        "sessions": {"before": len(before["rows"]), "after": len(after["rows"]),
                     "active_before": sum(1 for r in before["rows"].values() if classify(r) == "active"),
                     "unclassified_before": sum(1 for r in before["rows"].values()
                                                if classify(r) == "unknown")},
        "compared_fields": list(COMPARED),
        "failures": failures,
        "changed_while_active": dict(sorted(active.items())),
        "changed_unclassified": dict(sorted(unclassified.items())),
        "sessions_unclassified": unclassified_sessions,
        "unreadable_rows": unreadable_rows,
        "views_disagree": views_disagree,
        "openwiz_runs_failed": runs_failed,
        "openwiz_refused_reads": refused,
        "excluded": {"given": len(exclude), "present": len(set(exclude) & set(before["rows"])),
                     "changed": dict(sorted(excluded.items()))},
        "sessions_missing_a_compared_field": missing,
        "samples": {"count": len(samples),
                    "cloud": sum(1 for s in samples if before["rows"][s].get("cloud")),
                    "local": sum(1 for s in samples if not before["rows"][s].get("cloud")),
                    "read_by_openwiz_show": min(SHOWS, len(samples)),
                    "with_new_events": sum(1 for r in sample_res.values() if r["advance"]),
                    "sequence_advance": sum(r["advance"] for r in sample_res.values()),
                    "events_observed": sum(r["observed"] for r in sample_res.values()),
                    "events_truncated": sum(1 for r in sample_res.values() if r["truncated"]),
                    "new_event_types": sorted({t for r in sample_res.values() for t in r["types"]}),
                    "queued_message_count_changed": sum(1 for r in sample_res.values() if r["qmc_changed"]),
                    "unreadable": sum(1 for r in sample_res.values() if r["unreadable"]),
                    "failed": sample_fail},
        "openwiz_runs": [{"args": safe_args(r["args"]), "exit": r["exit"], "expected_exit": r["expected_exit"],
                          "reads": len(r["calls"]), "refused_reads": sum(1 for c in r["calls"] if c.get("refused"))}
                         for r in runs],
        "checks": checks,
        "reads": reads,
        "wait_s": run["wait_s"], "duration_s": run["duration_s"],
    }


def safe_args(args):
    """OpenWiz's arguments with every session id replaced by a placeholder."""
    return ["<nonexistent id>" if x.startswith("thr_synopenwizp4_") else
            x if x in ("ls", "show") or x.startswith("-") or x.isdigit() else "<session>"
            for x in args]


def cmd_run(a):
    if os.environ.get("ROOM_SERVER_URL"):
        raise observe.Stop("ROOM_SERVER_URL is set: quick-check runs room-cli against its default "
                           "server only; unset it")
    if os.path.exists(a.run_dir):
        raise observe.Stop("the run directory exists; each run needs a new one")
    # Finding 9: the prebuilt binary and its checkout are verified, not rebuilt.
    binary = {"sha256_matches": None, "head": None, "head_matches": None}
    if a.expect_sha256:
        if observe.file_sha256(a.openwiz) != a.expect_sha256.lower():
            raise observe.Stop("the openwiz binary's sha256 is not the expected one")
        binary["sha256_matches"] = True
    if a.checkout:
        import subprocess
        head = subprocess.run(["git", "-C", a.checkout, "rev-parse", "HEAD"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode().strip()
        if a.expect_head and head != a.expect_head:
            raise observe.Stop("the checkout's head is not the expected one")
        binary["head"], binary["head_matches"] = head, (head == a.expect_head) if a.expect_head else None
    os.makedirs(a.run_dir, mode=0o700)
    t0 = time.monotonic()
    ctx = observe.Ctx(a.room_cli, a.run_dir, a.concurrency)
    exclude = set(a.exclude_id or [])
    version = version_record(ctx)
    # 1. Before
    before = lists(ctx, "before")
    samples = choose_samples(before, exclude, a.samples)
    if not samples:
        raise observe.Stop("no quiet idle session to sample")
    details_b = {s: observe.detail(ctx, s) for s in samples}
    ctx.save("before.json", before)
    # 2. OpenWiz
    missing_id = "thr_synopenwizp4_" + os.urandom(6).hex()
    if missing_id in before["rows"]:
        raise observe.Stop("the synthetic nonexistent id exists")
    plan = [["ls"], ["ls", "-l"]] + [["show", s] for s in samples[:SHOWS]] + [["show", missing_id]]
    plan += observe.inventory_plan()[:-2]  # its counts and pages (P1, P6); ls -l ran above
    runs, count_total = [], None
    i = 0
    while i < len(plan):
        args = plan[i]
        r = observe.run_openwiz(ctx, a.openwiz, "qc-%02d" % i, args)
        r["expected_exit"] = 3 if args == ["show", missing_id] else 0  # Sol's sweep, 4
        runs.append(r)
        if args[:2] == ["ls", "--json"] and "--offset" not in args and count_total is None \
                and observe.view_of(args) == "default":
            c = ctx.room_json(["thread", "count", "--json"])
            count_total = c.get("total") if isinstance(c, dict) else None
        more = observe.next_page(r, args)
        if more:
            plan.insert(i + 1, more)
        i += 1
    # 3. Wait, then after
    time.sleep(a.wait)
    after = lists(ctx, "after")
    sample_res = {s: sample_eval(ctx, s, details_b[s], observe.detail(ctx, s, details_b[s]))
                  for s in samples}
    ctx.save("after.json", after)
    # 4. Checks and report
    shows = [r for r in runs if r["args"][:1] == ["show"]]
    inv = {}
    json_runs = []
    for r in runs:
        if r["args"][:1] != ["ls"] or "--json" not in r["args"]:
            continue
        view = observe.view_of(r["args"])
        if "--limit" in r["args"] and r["args"][r["args"].index("--limit") + 1] == "0":
            inv[("count", view)] = r
        elif "-l" not in r["args"]:
            inv.setdefault(("pages", view), []).append(r)
            json_runs.append(r)
    checks = {"P1": observe.p1(before, after, inv, count_total),
              "P4": observe.p4(shows[-1], missing_id),
              "P6": observe.p6(before, after, json_runs)}  # every view's pages (Sol's sweep, 6)
    observer_reads = sum(ctx.reads.values())
    openwiz_reads = sum(len(r["calls"]) for r in runs)
    reads = {"observer": observer_reads, "openwiz": openwiz_reads,
             "total": observer_reads + openwiz_reads,
             "within_budget": observer_reads + openwiz_reads <= READ_BUDGET,
             "observer_by_kind": dict(sorted(ctx.reads.items()))}
    run = {"wait_s": a.wait, "duration_s": int(time.monotonic() - t0)}
    rep = build_report(run, version, before, after, exclude, samples, sample_res, runs, checks, reads,
                       binary)
    text = json.dumps(rep, indent=1, sort_keys=True)
    forbid = set(before["rows"]) | set(after["rows"]) | set(before["projects"]) | set(before["projects_hidden"])
    forbid |= set(after["projects"]) | set(after["projects_hidden"]) | set(before["machines"])
    for snap in (before, after):
        for r in snap["rows"].values():
            for k in ("project", "parent"):
                if isinstance(r.get(k), str) and r[k] != observe.MISSING:
                    forbid.add(r[k])
    forbid |= exclude | set(a.forbid or []) | {a.run_dir, os.path.expanduser("~"),
                                               os.path.abspath(a.room_cli), os.path.abspath(a.openwiz)}
    hits = sum(1 for v in forbid if v and observe.leaks(v, text))
    if hits:
        raise observe.Stop("the report would contain %d forbidden strings; nothing printed" % hits)
    observe.write_private(os.path.join(a.run_dir, "report.json"), text)
    return rep


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--room-cli", required=True)
    s.add_argument("--openwiz", required=True)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--exclude-id", action="append", help="excluded and listed as such; never reported")
    s.add_argument("--forbid", action="append", help="another string the report must not hold")
    s.add_argument("--wait", type=float, default=120)
    s.add_argument("--samples", type=int, default=SAMPLES)
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--expect-sha256", help="the openwiz binary's expected SHA-256; any other stops the check")
    s.add_argument("--checkout", help="the checkout the binary was built from (its head is recorded)")
    s.add_argument("--expect-head", help="its expected head; any other stops the check")
    a = p.parse_args(argv)
    try:
        rep = cmd_run(a)
    except observe.Stop as e:
        print(json.dumps({"stopped": str(e)}))
        return 10
    except KeyboardInterrupt:
        print(json.dumps({"stopped": "interrupted"}))
        return 130
    except Exception as e:  # its text could hold an id: the type only
        print(json.dumps({"stopped": "unexpected error: %s" % type(e).__name__}))
        return 11
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 0 if rep["outcome"] == "pass" else 10


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(json.dumps({"stopped": "interrupted"}))
        sys.exit(130)
