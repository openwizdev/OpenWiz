#!/usr/bin/env python3
"""The OpenWiz CI bench (historical K1 #332, spec #330, CS1): PRs an hour, measured.

    bench.py collect --since T --until T --out DIR   read a window from GitHub (gh api, GET only)
    bench.py measure DIR --robots N --label TEXT     write DIR/point.json from DIR's jobs
    bench.py chart [--baseline DIR] DIR... --out OUT draw the windows against the baseline
    bench.py factory --since T --until T --out DIR   read the factory benches' history into DIR (#1359)

T is a UTC time, YYYY-MM-DDTHH:MM:SSZ; a window holds the CI runs created at
or after --since and before --until. Python 3 standard library only, and gh.
See README.md here for what each number means.
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
import importlib.util
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = HERE / "steps.tsv"
ROOT = HERE.parents[1]
BASELINE = ROOT / "private" / "evidence" / "infra-ci-scale" / "bench" / "baseline"
SCHEMA = "closedwiz.ci-bench.v1"
WORKFLOW = "ci.yml"
BASE_BRANCH = "main"
PAGE = 100
API_LIMIT = 1000

CATEGORIES = ["web", "setup", "rust", "build", "skills"]
NAMES = {"web": "Web tests", "setup": "Setup and teardown", "rust": "Rust tests", "build": "Build, lint, typecheck",
         "skills": "Skill tests"}
CODE_STEPS = {"Run npm test", "Run cargo test --workspace", "Run npm run build"}
# The reconstructed rule counted the docs-only classifier as setup.
LEGACY_SETUP = {"The docs-only classifier"}
CODE_RULE = ("successful code runs: push and pull_request runs that succeeded and in which"
             " `Run npm test`, `Run cargo test --workspace` or `Run npm run build` succeeded;"
             " robot time is each job's whole time on its runner")
LEGACY_RULE = ("reconstructed: runs in which `Run npm test` lasted more than 10 s, any event or"
               " conclusion; robot time is the sum of step durations only, with"
               " `The docs-only classifier` counted as setup")

JOB_KEYS = {"completed_at", "conclusion", "created_at", "event", "name", "run", "run_concl", "runner_name",
            "started_at", "steps"}
STEP_KEYS = {"completed_at", "conclusion", "name", "started_at"}
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class Fail(Exception):
    pass


# ---------------------------------------------------------------- reading

def trends_module():
    spec = importlib.util.spec_from_file_location("bench_trends", HERE / "trends.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module




def strict_json(text, where):
    """JSON with no repeated key and no NaN or Infinity."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Fail(f"{where}: repeated key '{k}'")
            out[k] = v
        return out

    def constant(name):
        raise ValueError(name)

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError:
        raise Fail(f"{where}: not JSON")


def read_file(path):
    try:
        return Path(path).read_text()
    except OSError as e:
        raise Fail(f"cannot read {path}: {e.strerror}")


def need(obj, key, where):
    if key not in obj:
        raise Fail(f"{where}: missing '{key}'")
    return obj[key]


def as_int(obj, key, where):
    v = need(obj, key, where)
    if type(v) is not int:
        raise Fail(f"{where}: '{key}' is not an integer")
    return v


def as_str(obj, key, where, null=False):
    v = need(obj, key, where)
    if v is None and null:
        return v
    if type(v) is not str:
        raise Fail(f"{where}: '{key}' is not a string")
    return v


def as_time(obj, key, where, null=False):
    v = need(obj, key, where)
    if v is None and null:
        return v
    if type(v) is not str or not TIME.fullmatch(v):
        raise Fail(f"{where}: '{key}' is not a UTC time")
    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise Fail(f"{where}: '{key}' is not a UTC time")
    return v


def as_obj(v, where):
    if type(v) is not dict:
        raise Fail(f"{where}: not an object")
    return v


def as_list(v, where):
    if type(v) is not list:
        raise Fail(f"{where}: not a list")
    return v


def exact(obj, keys, where):
    if set(obj) != keys:
        raise Fail(f"{where}: keys are {sorted(obj)}, expected {sorted(keys)}")


def secs(t):
    return parsed_secs(t)


@lru_cache(maxsize=8192)
def parsed_secs(t):
    # Only successful, context-free conversions are retained. A bounded LRU
    # also caps memory for high-cardinality windows and direct module callers.
    return int(datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def read_window(d):
    where = f"{d}/window.json"
    w = as_obj(strict_json(read_file(Path(d) / "window.json"), where), where)
    exact(w, {"since", "until"}, where)
    since, until = as_time(w, "since", where), as_time(w, "until", where)
    if secs(until) <= secs(since):
        raise Fail(f"{where}: the window ends before it starts")
    return since, until


def read_merged(d, since, until):
    where = f"{d}/merged.json"
    prs = as_list(strict_json(read_file(Path(d) / "merged.json"), where), where)
    seen, times = set(), {}
    for i, pr in enumerate(prs):
        at = f"{where} item {i + 1}"
        as_obj(pr, at)
        exact(pr, {"merged_at", "number"}, at)
        n, merged = as_int(pr, "number", at), as_time(pr, "merged_at", at)
        if n in seen:
            raise Fail(f"{where}: PR {n} is listed twice")
        seen.add(n)
        if not secs(since) <= secs(merged) < secs(until):
            raise Fail(f"{where}: PR {n} merged outside the window")
        times[n] = merged
    return times


def read_jobs(d, allow_timing_gaps=False):
    where = f"{d}/jobs.jsonl"
    jobs = []
    for i, line in enumerate(read_file(Path(d) / "jobs.jsonl").splitlines()):
        at = f"{where} line {i + 1}"
        job = as_obj(strict_json(line, at), at)
        exact(job, JOB_KEYS | (set(job) & {"runner_labels", "run_created_at", "id", "run_attempt", "collected_attempt"}), at)
        for k in set(job) & {"id", "run_attempt", "collected_attempt"}:
            as_int(job, k, at)
        if "run_created_at" in job:
            as_time(job, "run_created_at", at)
        if "runner_labels" in job:
            labels = as_list(job["runner_labels"], at)
            if any(type(x) is not str for x in labels):
                raise Fail(f"{at}: runner labels must be strings")
        as_int(job, "run", at)
        for k in ("event", "name"):
            as_str(job, k, at)
        for k in ("run_concl", "conclusion", "runner_name"):
            as_str(job, k, at, null=True)
        for k in ("created_at", "started_at", "completed_at"):
            as_time(job, k, at)
        # GitHub shows a job that never got a runner (none, and no steps)
        # ending up to a second before it started: it ran for no time.
        if secs(job["completed_at"]) < secs(job["started_at"]) and not never_ran(job):
            if allow_timing_gaps and job.get("run_concl") in ("failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale", "neutral", "skipped"):
                job["timing_unknown"] = True
            else:
                raise Fail(f"{at}: job {job['name']} ends before it starts")
        for j, step in enumerate(as_list(job["steps"], at)):
            st = f"{at} step {j + 1}"
            as_obj(step, st)
            exact(step, STEP_KEYS, st)
            as_str(step, "name", st)
            as_str(step, "conclusion", st, null=True)
            a, b = as_time(step, "started_at", st, null=True), as_time(step, "completed_at", st, null=True)
            if a is not None and b is not None and secs(b) < secs(a):
                raise Fail(f"{st}: step '{step['name']}' ends before it starts")
        jobs.append(job)
    return jobs


def never_ran(job):
    return not job["steps"] and not job["runner_name"]


def read_table(path):
    rows = []
    for i, line in enumerate(read_file(path).splitlines()):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] not in CATEGORIES or not parts[1]:
            raise Fail(f"{path} line {i + 1}: not '<category><TAB><step name>'")
        pattern = "".join(".*" if c == "*" else re.escape(c) for c in parts[1])
        rows.append((parts[0], re.compile(pattern)))
    if not rows:
        raise Fail(f"{path}: no rows")
    return rows


def category(table, step, job):
    name = re.sub(r"@\S+", "", step)
    hits = [cat for cat, pat in table if pat.fullmatch(name)]
    if len(hits) != 1:
        how = "matches no row" if not hits else f"matches {len(hits)} rows"
        raise Fail(f"step '{step}' (job {job}) {how} of {STEPS}")
    return hits[0]


# ---------------------------------------------------------------- measuring


def duration(step):
    if step["started_at"] is None or step["completed_at"] is None:
        return 0
    return secs(step["completed_at"]) - secs(step["started_at"])


def nearest_rank(values, p):
    ordered = sorted(values)
    return ordered[math.ceil(p * len(ordered)) - 1]


def cohort(runs, table, legacy, robots, rule):
    """Robot time per run in one cohort. The reconstructed rule counts step
    durations only; successful code runs count each job's whole time, the
    time no step covers going to setup."""
    if not runs:
        return None
    cats = dict.fromkeys(CATEGORIES, 0)
    waiting = robot = 0
    walls = []
    for jobs in runs:
        for job in jobs:
            # A job that never got a runner (none, and no steps) used no
            # robot and waited for none, however long GitHub shows it.
            if never_ran(job):
                continue
            started, done = secs(job["started_at"]), secs(job["completed_at"])
            # A job carried over from an earlier attempt started before it
            # was created: it waited for nothing in this one.
            waiting += max(0, started - secs(job["created_at"]))
            covered = 0
            for step in job["steps"]:
                d = duration(step)
                covered += d
                cat = "setup" if legacy and step["name"] in LEGACY_SETUP else category(table, step["name"], job["name"])
                cats[cat] += d
            if legacy:
                robot += covered
            else:
                if covered > done - started:
                    raise Fail(f"run {job['run']} job {job['name']}: its steps last longer than the job")
                cats["setup"] += done - started - covered
                robot += done - started
        walls.append((max(secs(j["completed_at"]) for j in jobs) - min(secs(j.get("run_created_at", j["created_at"])) for j in jobs)) / 60)
    n = len(runs)
    per_run = robot / n / 60

    def m(x):
        return round(x / n / 60, 4)

    return {
        "rule": rule,
        "runs": n,
        "robot_seconds": robot,
        "robot_minutes_per_run": round(per_run, 4),
        "prs_per_hour": round(robots * 60 / per_run, 4),
        "categories": {k: m(cats[k]) for k in CATEGORIES},
        "split": {"waiting": m(waiting), "setup": m(cats["setup"]), "running": m(robot - cats["setup"])},
        "queued_to_done": {"median": round(statistics.median(walls), 4), "p90": round(nearest_rank(walls, 0.9), 4),
                           "max": round(max(walls), 4)},
    }


def measure(d, robots, label, prices=None, allow_empty=False, allow_timing_gaps=False):
    since, until = read_window(d)
    jobs = read_jobs(d, allow_timing_gaps)
    merged_times = read_merged(d, since, until)
    numbers = sorted(merged_times)
    merged = len(numbers)
    facts = read_factory(d, since, until) if (Path(d) / "factory.json").exists() else None
    found = read_escapes(d, since, until) if (Path(d) / "escapes.json").exists() else None
    table = read_table(STEPS)
    for job in jobs:
        for step in job["steps"]:
            category(table, step["name"], job["name"])
    runs = {}
    for job in jobs:
        runs.setdefault(job["run"], []).append(job)
    for rid, js in runs.items():
        if len({j["event"] for j in js}) != 1:
            raise Fail(f"run {rid} has jobs of two events")
        origins = {j.get("run_created_at") for j in js}
        if len(origins) != 1:
            raise Fail(f"run {rid} has inconsistent run creation times")
        if (None not in origins and js[0]["run_concl"] == "success"
                and secs(next(iter(origins))) > max(secs(j["completed_at"]) for j in js)):
            raise Fail(f"run {rid} was created after its last job completed")
        if len({j["run_concl"] for j in js}) != 1:
            raise Fail(f"run {rid} has jobs of two run conclusions")
    order = sorted(runs)
    code = [runs[r] for r in order
            if runs[r][0]["event"] in ("push", "pull_request") and runs[r][0]["run_concl"] == "success"
            and any(s["name"] in CODE_STEPS and s["conclusion"] == "success" for j in runs[r] for s in j["steps"])]
    legacy = [runs[r] for r in order
              if any(s["name"] == "Run npm test" and duration(s) > 10 for j in runs[r] for s in j["steps"])
              and not any(j.get("timing_unknown") for j in runs[r])]
    if not code and not allow_empty:
        raise Fail("no successful code runs in the window")
    hours = (secs(until) - secs(since)) / 3600
    point = {
        "schema": SCHEMA,
        "label": label,
        "since": since,
        "until": until,
        "hours": round(hours, 4),
        "robots": robots,
        "runs": len(runs),
        "jobs": len(jobs),
        "merged_prs": merged,
        "merged_per_hour": round(merged / hours, 4),
        "code_runs": cohort(code, table, False, robots, CODE_RULE),
        "legacy": cohort(legacy, table, True, robots, LEGACY_RULE),
        "cost": costs(jobs, code, read_prices(prices or HERE / "prices.tsv")),
    }
    if all("run_created_at" in j for j in jobs):
        point["latency_basis"] = "workflow created to last job completed"
    if facts is not None:
        if sorted(p["number"] for p in facts["prs"]) != numbers:
            raise Fail("factory.json and merged.json: merged PRs differ; collect the window again")
        point["factory"] = factory_point(facts, since, until)
    if (Path(d) / "journey-report.json").exists():
        T = trends_module()
        try:
            result = strict_json(read_file(Path(d) / "journey-report.json"), "journey report")
            T.validate(result)
            if (result["since"], result["until"]) != (since, until):
                raise Fail("journey report differs from the measured window")
            point["journey"] = result
        except T.J.ReadError as error:
            raise Fail(str(error))
    if found is not None:
        point["escapes"] = escapes_point(found)
    point["buckets"] = buckets(since, until, robots, table, runs, code, merged_times, facts, jobs)
    write(Path(d) / "point.json", json.dumps(point, indent=2) + "\n")
    c, lg = point["code_runs"], point["legacy"]
    if facts is not None:
        f = point["factory"]
        print(f"{label}: factory: {f['merged_prs']} merged, {f['first_review']['reviewed_prs']} reviewed,"
              f" {f['reruns']['total']} reruns, main red {show(f['main_red']['red_minutes'], '{:.0f}')} min")
    if "escapes" in point:
        print(f"{label}: selector escapes {escapes_cell(point)}")
    if c is None:
        print(f"{label}: no successful code runs; daily cost recorded")
        return
    print(f"{label}: {c['prs_per_hour']:.1f} PRs an hour of capacity on {robots} robots"
          f" ({c['robot_minutes_per_run']:.2f} robot-minutes per code run, {c['runs']} successful code runs);"
          f" {point['merged_per_hour']:.1f} merged an hour")
    if lg:
        print(f"  reconstructed rule: {lg['prs_per_hour']:.1f} PRs an hour"
              f" ({lg['robot_minutes_per_run']:.2f} robot-minutes per code run, {lg['runs']} runs)")


def write(path, text):
    fd, tmp = tempfile.mkstemp(dir=Path(path).parent, prefix=".bench-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


# ---------------------------------------------------------------- collecting


def gh(path):
    """One read: `gh api <path>`, a GET with no other flag."""
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode != 0:
        first = (r.stderr.strip().splitlines() or [""])[0]
        raise Fail(f"gh api {path} failed (exit {r.returncode}): {first}")
    return strict_json(r.stdout, f"gh api {path}")


def pages(path, key, what, read=None):
    """Every item of a paged list whose answers say their total_count."""
    items, total, page = [], None, 1
    while total is None or len(items) < total:
        where = f"gh api {path}&page={page}"
        ans = as_obj((read or gh)(f"{path}&page={page}"), where)
        count, got = as_int(ans, "total_count", where), as_list(need(ans, key, where), where)
        if total is None:
            total = count
            if total > API_LIMIT:
                raise Fail(f"the window holds more than {API_LIMIT} {what}, the API's limit: split it")
        elif count != total:
            raise Fail(f"{where}: total_count changed between pages")
        if not got and len(items) < total:
            raise Fail(f"{where}: fewer {what} than total_count ({len(items)} of {total})")
        items += [(item, where) for item in got]
        page += 1
    if len(items) > total:
        raise Fail(f"gh api {path}: more {what} than total_count ({len(items)} of {total})")
    return items



# WR8 exact pool selectors, separate from historical pricing precedence.
ACTIVITY_POOLS = {"closedwiz-pc", "self-hosted", "ubuntu-24.04", "ubuntu-22.04",
                  "ubuntu-latest", "ubuntu-slim", "blacksmith-2vcpu-ubuntu-2404"}


def activity_pool(labels):
    if not labels or set(labels) - ACTIVITY_POOLS - {"Linux", "linux", "X64", "x64"}:
        return None
    selected = set(labels) & ACTIVITY_POOLS
    if "closedwiz-pc" in selected:
        selected.discard("self-hosted")
    if len(selected) != 1 or runner_kind({"runner_labels": labels}) == "unknown":
        return None
    return next(iter(selected))


def current_activity(since, until, *, repo, read):
    """WR8's injected current observation; never changes completed collect.

    All ci.yml runs (including old active ones), bounded by the existing API
    limit. Two equal enumerations bracket jobs; two equal job reads and a run
    reread reject changing attempts/membership/status rather than infer a pool.
    No runner inventory endpoint, clock, output file or implicit live reader.
    """
    base = f"repos/{repo}"
    path = f"{base}/actions/workflows/{WORKFLOW}/runs?per_page={PAGE}"

    def runs():
        result = {}
        for value, where in pages(path, "workflow_runs", "runs", read):
            as_obj(value, where)
            rid = as_int(value, "id", where)
            attempt = as_int(value, "run_attempt", where)
            if rid <= 0 or attempt <= 0 or rid in result:
                raise Fail("current runs: duplicate or invalid identity")
            result[rid] = {"id": rid, "run_attempt": attempt,
                           "status": as_str(value, "status", where),
                           "conclusion": as_str(value, "conclusion", where, null=True),
                           "created_at": as_time(value, "created_at", where)}
            if secs(result[rid]["created_at"]) > secs(until):
                raise Fail("current run created after observation")
        return result

    before, seen, jobs, priced, cost_ids = runs(), set(), [], [], []
    for rid, run in sorted(before.items()):
        if run["status"] == "completed" and not since <= run["created_at"] < until:
            continue
        if run["status"] not in ("completed", "in_progress", "queued", "waiting", "pending", "requested"):
            raise Fail("current run status unavailable")
        job_path = f"{base}/actions/runs/{rid}/jobs?per_page={PAGE}"
        rows = pages(job_path, "jobs", "jobs", read)
        if [v for v, _ in rows] != [v for v, _ in pages(job_path, "jobs", "jobs", read)]:
            raise Fail("current jobs changed during observation")
        for value, where in rows:
            as_obj(value, where)
            jid = as_int(value, "id", where)
            if jid <= 0 or jid in seen or as_int(value, "run_id", where) != rid:
                raise Fail("current jobs: duplicate or invalid identity")
            seen.add(jid)
            if as_int(value, "run_attempt", where) != run["run_attempt"]:
                raise Fail("current job attempt changed or carried over")
            status = as_str(value, "status", where)
            if status not in ("completed", "in_progress", "queued"):
                raise Fail("current job status unavailable")
            labels = value.get("labels")
            if labels is not None and (type(labels) is not list or any(type(x) is not str for x in labels)):
                raise Fail("current job labels unavailable")
            jobs.append({"id": jid, "run": rid, "attempt": run["run_attempt"],
                         "status": status, "pool": activity_pool(labels)})
            if run["status"] == "completed":
                if status != "completed":
                    raise Fail("completed current run contains an unfinished job")
                item = {"runner_labels": labels if activity_pool(labels) else [],
                        "runner_name": as_str(value, "runner_name", where, null=True),
                        "steps": as_list(need(value, "steps", where), where),
                        "started_at": as_time(value, "started_at", where, null=True),
                        "completed_at": as_time(value, "completed_at", where, null=True)}
                if not never_ran(item):
                    if (item["started_at"] is None or item["completed_at"] is None
                            or item["completed_at"] < item["started_at"] or item["completed_at"] > until):
                        raise Fail("completed current job timing unavailable")
                priced.append(item)
                cost_ids.append(jid)
        again = as_obj(read(f"{base}/actions/runs/{rid}"), "current run reread")
        if any(again.get(k) != v for k, v in run.items()):
            raise Fail("current run changed during observation")
    if runs() != before:
        raise Fail("current run enumeration changed during observation")
    prices = read_prices(HERE / "prices.tsv")
    return {"runs": sorted(before), "jobs": jobs, "cost_jobs": cost_ids,
            "cost": costs(priced, [], prices)}


def collect(since, until, out, workers=1):
    if shutil.which("gh") is None:
        raise Fail("gh is not on PATH")
    base = "repos/{owner}/{repo}"
    runs = {}
    for run, where in pages(f"{base}/actions/workflows/{WORKFLOW}/runs?created={since}..{until}"
                            f"&status=completed&per_page={PAGE}", "workflow_runs", "runs"):
        as_obj(run, where)
        rid = as_int(run, "id", where)
        at = f"{where} run {rid}"
        if rid in runs:
            raise Fail(f"{at}: listed twice")
        if as_str(run, "status", at) != "completed":
            raise Fail(f"{at}: not completed")
        runs[rid] = (as_str(run, "event", at), as_str(run, "conclusion", at, null=True), as_time(run, "created_at", at),
                     as_int(run, "run_attempt", at))
    # The API's range includes its end; the window doesn't.
    keep = sorted(r for r, (_, _, created, _) in runs.items() if secs(since) <= secs(created) < secs(until))
    def collect_run(rid):
        lines = []
        event, concl, _, attempt = runs[rid]
        for job, where in pages(f"{base}/actions/runs/{rid}/jobs?per_page={PAGE}", "jobs", "jobs"):
            at = f"{where} run {rid} job"
            as_obj(job, at)
            steps = []
            for step in as_list(need(job, "steps", at), at):
                as_obj(step, at)
                steps.append({"completed_at": as_time(step, "completed_at", at, null=True),
                              "conclusion": as_str(step, "conclusion", at, null=True),
                              "name": as_str(step, "name", at),
                              "started_at": as_time(step, "started_at", at, null=True)})
            record = {"completed_at": as_time(job, "completed_at", at),
                      "conclusion": as_str(job, "conclusion", at, null=True),
                      "created_at": as_time(job, "created_at", at), "event": event, "name": as_str(job, "name", at),
                      "run": rid, "run_concl": concl, "runner_name": as_str(job, "runner_name", at, null=True),
                      "started_at": as_time(job, "started_at", at), "steps": steps,
                      # Identity, so the factory benches reuse exactly this
                      # attempt's jobs and nothing else (#1359).
                      "id": as_int(job, "id", at), "run_attempt": as_int(job, "run_attempt", at),
                      "collected_attempt": attempt}
            record["run_created_at"] = runs[rid][2]
            if "labels" in job:
                labels = as_list(job["labels"], at)
                if any(type(x) is not str for x in labels):
                    raise Fail(f"{at}: runner labels must be strings")
                record["runner_labels"] = labels
            lines.append(json.dumps(record, sort_keys=True))
        # The jobs are the latest attempt's when they were read: if a rerun
        # came between the list and them, they belong to another attempt
        # than the conclusion above. Read the run again; it must not have
        # changed (#383 R2).
        where = f"gh api {base}/actions/runs/{rid}"
        again = as_obj(gh(f"{base}/actions/runs/{rid}"), where)
        if as_int(again, "id", where) != rid:
            raise Fail(f"{where}: run {rid} read again is run {again['id']}")
        before = (attempt, "completed", concl)
        after = (as_int(again, "run_attempt", where), as_str(again, "status", where),
                 as_str(again, "conclusion", where, null=True))
        if after != before:
            raise Fail(f"{where}: run {rid} changed while it was read (attempt, status, conclusion: {before} then"
                       f" {after}); read the window again once its reruns have finished")
        return lines

    if workers == 1:
        lines = [line for group in map(collect_run, keep) for line in group]
    else:
        # Two independent run reads at most; results retain run order.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            lines = [line for group in pool.map(collect_run, keep) for line in group]
    merged, page = {}, 1
    while True:
        where = f"gh api pulls page {page}"
        got = as_list(gh(f"{base}/pulls?state=closed&base={BASE_BRANCH}&sort=updated&direction=desc"
                         f"&per_page={PAGE}&page={page}"), where)
        older = False
        for pr in got:
            as_obj(pr, where)
            n = as_int(pr, "number", where)
            at = f"{where} PR {n}"
            at_merge = as_time(pr, "merged_at", at, null=True)
            if secs(as_time(pr, "updated_at", at)) < secs(since):
                older = True
            if at_merge is not None and secs(since) <= secs(at_merge) < secs(until):
                merged[n] = at_merge
        # Newest first by update, and a merge updates a PR: once one was last
        # updated before the window, no later page holds a merge inside it.
        if len(got) < PAGE or older:
            break
        page += 1
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / "window.json", json.dumps({"since": since, "until": until}, indent=2, sort_keys=True) + "\n")
    write(out / "jobs.jsonl", "".join(line + "\n" for line in lines))
    write(out / "merged.json", json.dumps([{"merged_at": merged[n], "number": n} for n in sorted(merged)],
                                          indent=2, sort_keys=True) + "\n")
    print(f"collected {len(keep)} runs, {len(lines)} jobs and {len(merged)} merged PRs into {out}")


# ---------------------------------------------------------------- charting

# GitHub's dark page and its text tokens. Jake, 2026-11-06: option B,
# no scales, every value labelled (private record):
# https://github.com/jparker2006/ClosedWiz/issues/1331#issuecomment-6674069137
SURFACE, INK, INK2, MUTED = "#0d1117", "#f0f6fc", "#9198a1", "#7d8590"
AXIS = "#3d444d"
# A one-step-off-surface hairline for the factory and bucket charts (#1359, #1264), which keep
# their scales; the CI charts Jake picked on #1331 (option B) draw no gridlines.
GRID = "#21262d"
# The dataviz skill's dark categorical steps, in a passing adjacent order for
# each chart against #0d1117 (its validate_palette.js; checkpoint/palette record):
# https://github.com/jparker2006/ClosedWiz/issues/1331#issuecomment-6674038293
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"
# Status colours, only on a change's arrow, always beside its words.
WORSE, BETTER = "#ec835a", "#0ca30c"
CAT_COLOR = {"web": BLUE, "setup": ORANGE, "rust": AQUA, "build": YELLOW, "skills": MAGENTA}
SPLIT = [("waiting", "Waiting", VIOLET), ("setup", "Setup", ORANGE), ("running", "Running", AQUA)]
GOALS = [("Tonight", 10, 25),
         ("This week", 3, 80),
         ("North star", 1, 500)]
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
WIDTH, LEFT, RIGHT = 820, 170, 760
BAR, GAP, GROUP_GAP = 14, 3, 18


POINT_KEYS = {"schema", "label", "since", "until", "hours", "robots", "runs", "jobs", "merged_prs", "merged_per_hour",
              "code_runs", "legacy"}
COHORT_KEYS = {"rule", "runs", "robot_seconds", "robot_minutes_per_run", "prs_per_hour", "categories", "split",
               "queued_to_done"}
NUMBERS = {"categories": set(CATEGORIES), "split": {"waiting", "setup", "running"},
           "queued_to_done": {"median", "p90", "max"}}


def as_num(obj, key, where):
    v = need(obj, key, where)
    if type(v) not in (int, float):
        raise Fail(f"{where}: '{key}' is not a number")
    if not math.isfinite(v) or v < 0:
        raise Fail(f"{where}: '{key}' must be finite and nonnegative")
    return v


def read_cohort(c, where):
    as_obj(c, where)
    exact(c, COHORT_KEYS, where)
    as_str(c, "rule", where)
    for k in ("runs", "robot_seconds"):
        as_int(c, k, where)
    for k in ("robot_minutes_per_run", "prs_per_hour"):
        as_num(c, k, where)
    for k, keys in NUMBERS.items():
        part = as_obj(c[k], f"{where} {k}")
        exact(part, keys, f"{where} {k}")
        for n in keys:
            as_num(part, n, f"{where} {k}")


def read_point(d):
    """A point.json, every field `chart` reads, each of its own type."""
    where = f"{d}/point.json"
    p = as_obj(strict_json(read_file(Path(d) / "point.json"), where), where)
    if p.get("schema") != SCHEMA:
        raise Fail(f"{where}: schema is not {SCHEMA}")
    exact(p, POINT_KEYS | (set(p) & {"cost", "latency_basis", "factory", "buckets", "escapes", "journey"}), where)
    if "journey" in p:
        T = trends_module()
        try:
            T.validate(p["journey"])
            if (p["journey"]["since"], p["journey"]["until"]) != (p["since"], p["until"]):
                raise Fail("journey report differs from point window")
        except T.J.ReadError as error:
            raise Fail(str(error))
    if "escapes" in p:
        validate_escapes(p["escapes"], f"{where} escapes")
    if "factory" in p:
        validate_factory(p["factory"], f"{where} factory")
    if "buckets" in p:
        validate_buckets(p["buckets"], f"{where} buckets")
    if "latency_basis" in p and p["latency_basis"] != "workflow created to last job completed":
        raise Fail(f"{where}: unknown latency basis")
    as_str(p, "label", where)
    for k in ("since", "until"):
        as_time(p, k, where)
    for k in ("robots", "runs", "jobs", "merged_prs"):
        as_int(p, k, where)
    for k in ("hours", "merged_per_hour"):
        as_num(p, k, where)
    if p["code_runs"] is not None:
        read_cohort(p["code_runs"], f"{where} code_runs")
    if "cost" in p:
        validate_cost(p["cost"], where)
    if p["legacy"] is not None:
        if type(p["legacy"]) is not dict:
            raise Fail(f"{where}: 'legacy' is not an object or null")
        read_cohort(p["legacy"], f"{where} legacy")
    return p


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def nice_max(v):
    """A round axis end at or above v, and its tick step."""
    raw = max(v, 1e-9) / 5
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    return step * math.ceil(v / step), step


def bar_path(x, y, w, h, round_end=True):
    """A bar from the baseline at x: square there, a 4px rounded data end."""
    r = min(4, w / 2, h / 2) if round_end else 0
    if w <= 0:
        return ""
    return (f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z")


def text(x, y, s, size=12, fill=INK, anchor="start", weight=None, cls=None):
    c = f' class="{cls}"' if cls else ""
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text{c} x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"{a}{w}>{esc(s)}</text>'


def svg_open(height, title, subtitle):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}"'
            f' font-family="{FONT}" fill="{INK}" role="img">',
            f"<title>{esc(title)}</title>",
            f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>',
            text(0, 22, title, 18, INK, weight=600), text(0, 42, subtitle, 13, INK2)]


def legend(items, y):
    out, x = [], 0
    for name, color in items:
        width = 15 + 6.6 * len(name) + 22
        if x + width > WIDTH:
            x, y = 0, y + 18
        out.append(f'<rect x="{x:.1f}" y="{y - 10}" width="10" height="10" rx="2" fill="{color}"/>')
        out.append(text(x + 15, y, name, 12, INK2))
        x += width
    return out


def day_name(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d:%a} {d:%b} {d.day}"


def short_label(p):
    """A row's (name, note): 'Sun Nov 1', a baseline, or a partial day's UTC hours."""
    label, iso = p["label"], p["label"][:10]
    if re.fullmatch(r"\d{4}-\d\d-\d\d", iso):
        if label == f"{iso} PST":
            return day_name(iso), ""
        if label.startswith(f"{iso} PST checkpoint"):
            return day_name(iso) + " so far", label.split("(", 1)[1].rstrip(")") if "(" in label else ""
        if label == f"{iso} baseline":
            return "Baseline " + day_name(iso)[4:], ""
    return (label if len(label) <= 26 else label[:25] + "…"), ""


def row_label(y, p, note=""):
    name, extra = short_label(p)
    note = note or extra
    if not note:
        return [text(LEFT - 12, y + 5, name, 13, INK, "end", cls="row")]
    return [text(LEFT - 12, y - 2, name, 13, INK, "end", cls="row"), text(LEFT - 12, y + 13, note, 11, MUTED, "end")]


def baseline_line(top, bottom):
    """The zero line: the only rule a chart keeps once its scale is gone."""
    return [f'<line x1="{LEFT}" x2="{LEFT}" y1="{top}" y2="{bottom}" stroke="{AXIS}"/>']


def chart_prs(points):
    base = points[0]
    target = 10 * (base["legacy"] or base["code_runs"])["prs_per_hour"]
    groups = []
    for i, p in enumerate(points):
        bars = []
        if i == 0 and p["legacy"]:
            bars.append(("capacity, reconstructed rule", p["legacy"]["prs_per_hour"], AQUA))
        bars.append(("capacity, successful code runs", p["code_runs"]["prs_per_hour"], BLUE))
        bars.append(("merged", p["merged_per_hour"], ORANGE))
        groups.append((p, bars))
    top = 112
    bottom = top + sum(len(b) * (BAR + GAP) - GAP + GROUP_GAP for _, b in groups) - GROUP_GAP + 6
    # The axis fits the bars; the 10x target is a note, never a stretched axis.
    vmax, _ = nice_max(max(v for _, b in groups for _, v, _ in b) * 1.08)
    out = svg_open(bottom + 24, "PRs an hour",
                   f"Capacity (robots × 60 ÷ robot-minutes per code run) and PRs actually merged, against the"
                   f" {base['label']}")
    out += legend([("Capacity, reconstructed rule (baseline)", AQUA), ("Capacity, successful code runs", BLUE),
                   ("Merged", ORANGE)], 70)
    out += baseline_line(top - 6, bottom)
    y = top
    for p, bars in groups:
        out += row_label(y + (len(bars) * (BAR + GAP) - GAP) / 2, p)
        for name, v, color in bars:
            w = (RIGHT - LEFT) * v / vmax
            out.append(f'<g><title>{esc(p["label"])}, {name}: {v:.1f} PRs an hour</title>'
                       f'<path d="{bar_path(LEFT, y, w, BAR)}" fill="{color}"/></g>')
            out.append(text(LEFT + w + 6, y + 11.5, f"{v:.1f}", 12, INK, cls="value"))
            y += BAR + GAP
        y += GROUP_GAP - GAP
    out.append(f'<g><title>10x the baseline: {target:.1f} PRs an hour</title>'
               + text(RIGHT, 94, f"10× the baseline: {target:.1f} an hour, off scale →", 12, INK2, "end",
                      cls="off-scale") + "</g>")
    return "\n".join(out + ["</svg>"]) + "\n"


def stacked_rows(points):
    """(label, robots and hours, rule name, cohort) for each bar: the
    baseline's two rules side by side, then each window's code runs."""
    rows = []
    for i, p in enumerate(points):
        if i == 0 and p["legacy"]:
            rows.append((p, "reconstructed rule", p["legacy"]))
        rows.append((p, "successful code runs", p["code_runs"]))
    return rows


def chart_stacked(points, title, subtitle, parts, unit, noun):
    rows = stacked_rows(points)
    top, pitch = 96, BAR + 26
    bottom = top + len(rows) * pitch - 12
    totals = [sum(v for v, _, _ in parts(c)) for _, _, c in rows]
    vmax, _ = nice_max(max(totals) * 1.08)
    out = svg_open(bottom + 24, title, f"{subtitle} ({unit})")
    out += legend([(name, color) for _, name, color in parts(rows[0][2])], 70)
    out += baseline_line(top - 6, bottom)
    for k, ((p, rule, c), total) in enumerate(zip(rows, totals)):
        y = top + k * pitch + 4
        # Name the rule only where the baseline shows both.
        two = rule == "reconstructed rule" or (k and rows[k - 1][1] == "reconstructed rule")
        out += row_label(y + BAR / 2, p, rule if two else "")
        x = LEFT
        segs = [(v, name, color) for v, name, color in parts(c) if v > 0]
        for j, (v, name, color) in enumerate(segs):
            w = (RIGHT - LEFT) * v / vmax
            last = j == len(segs) - 1
            draw = w if last else max(w - 2, 0)
            out.append(f'<g><title>{esc(p["label"])}, {rule}, {name}: {v:.2f} {noun}</title>'
                       f'<path d="{bar_path(x, y, draw, BAR, round_end=last)}" fill="{color}"/></g>')
            label = f"{v:.1f}"
            if draw >= 7 * len(label) + 10:  # only where it fits; the table has the rest
                out.append(text(x + 4, y + 11, label, 11, "#ffffff", cls="inner"))
            x += w
        out.append(text(x + 6, y + 11.5, f"{total:.2f}", 12, INK, weight=600, cls="value"))
    return "\n".join(out + ["</svg>"]) + "\n"


def md_cell(s):
    return str(s).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def bench_md(points):
    base = points[0]
    out = ["# CI bench", "",
           f"PRs an hour first, the headline. The first point is the {base['label']}"
           f" ({base['since']} to {base['until']}). Made by `tools/ci-bench/bench.py chart`; every number is in the"
           " tables below.", "",
           *headline_table(points), "",
           "![PRs an hour](prs-per-hour.svg)", "",
           "![Robot-minutes per code run](robot-minutes.svg)", "",
           "![Where a code run's time goes](time-split.svg)", "",
           "## PRs an hour", "",
           "| Window | Dates | Robots | Capacity, reconstructed rule | Capacity, successful code runs | Merged |",
           "| --- | --- | --- | --- | --- | --- |"]
    for i, p in enumerate(points):
        legacy = f"{p['legacy']['prs_per_hour']:.2f}" if i == 0 and p["legacy"] else "–"
        out.append(f"| {md_cell(p['label'])} | {p['since']} to {p['until']} | {p['robots']} | {legacy} |"
                   f" {p['code_runs']['prs_per_hour']:.2f} | {p['merged_per_hour']:.2f}"
                   f" ({p['merged_prs']} in {p['hours']:.1f} h) |")
    out += ["", "## Robot-minutes per code run", "",
            "| Window | Rule | Code runs | Robot-minutes | " + " | ".join(NAMES[k] for k in CATEGORIES) + " |",
            "| --- | --- | --- | --- | " + " | ".join("---" for _ in CATEGORIES) + " |"]
    for p, rule, c in stacked_rows(points):
        name = "reconstructed" if rule == "reconstructed rule" else rule
        out.append(f"| {md_cell(p['label'])} | {name} | {c['runs']} | {c['robot_minutes_per_run']:.2f} | "
                   + " | ".join(f"{c['categories'][k]:.2f}" for k in CATEGORIES) + " |")
    out += ["", "## Where a code run's time goes (minutes per code run)", "",
            "| Window | Rule | Waiting | Setup | Running | Queued to done: median | p90 | max |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p, rule, c in stacked_rows(points):
        name = "reconstructed" if rule == "reconstructed rule" else rule
        s, q = c["split"], c["queued_to_done"]
        out.append(f"| {md_cell(p['label'])} | {name} | {s['waiting']:.2f} | {s['setup']:.2f} | {s['running']:.2f} |"
                   f" {q['median']:.2f} | {q['p90']:.2f} | {q['max']:.2f} |")
    out += ["", "## How it counts", "",
            f"- **Successful code runs**, every window: {CODE_RULE}.",
            f"- **Reconstructed rule**, the baseline only: {LEGACY_RULE}. It reproduces the baseline as first"
            " recorded (10.34 robot-minutes per code PR); the script that first selected it is lost.",
            "- **The correction:** on the same baseline data, successful code runs give 10.37, not 10.34. The two"
            " rules pick different runs (failed and cancelled runs, and runs with only Rust tests) and count"
            " different time (job overhead between steps). New windows are compared on successful code runs.",
            "- **Capacity** is robots × 60 ÷ robot-minutes per code run: PRs an hour if each PR needed one code"
            " run. A code run is not a PR: a PR can have several runs, and pushes to `main` are runs too."
            " **Merged** counts PRs merged into `main` in the window, an hour at a time.",
            "- **Waiting** is a job's time from created to started (0 for a job carried over from an earlier"
            " attempt); **setup** is every step that isn't a test, plus a job's time no step covers (step"
            " durations only, for the reconstructed rule); **running** is the tests and checks"
            " (`tools/ci-bench/steps.tsv`). **Queued to done** is a run's first job created to its last job"
            " done; p90 is the nearest rank.", ""]
    return "\n".join(out)


def chart(baseline, dirs, out):
    points = [read_point(d) for d in [baseline] + list(dirs)]
    if any(p["code_runs"] is None for p in points):
        raise Fail("chart requires successful code runs; dashboard records empty days")
    files = {
        "prs-per-hour.svg": chart_prs(points),
        "robot-minutes.svg": chart_stacked(
            points, "Robot-minutes per code run", "Where each code run's robot time goes, by category",
            lambda c: [(c["categories"][k], NAMES[k], CAT_COLOR[k]) for k in CATEGORIES],
            "robot-minutes per code run", "robot-minutes"),
        "time-split.svg": chart_stacked(
            points, "Where a code run's time goes",
            "Each job's waiting for a robot, its setup and its tests, added up per code run",
            lambda c: [(c["split"][k], name, color) for k, name, color in SPLIT], "minutes per code run", "minutes"),
        "bench.md": bench_md(points),
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        write(out / name, text)
    print(f"charted {len(points)} windows into {out}")


# ---------------------------------------------------------------- step coverage and costs (#1252)


def check_steps(workflow):
    """Read this repository's steps subset, refusing unnamed multiline runs.

    Explicit names are API names; otherwise GitHub prefixes uses/run with Run.
    Parse step entries, not name/run words inside scripts or comments.
    """
    table = read_table(STEPS)
    entries = re.split(r"(?m)^      - ", read_file(workflow))[1:]
    if not entries:
        raise Fail(f"{workflow}: no steps found")
    for entry in entries:
        fields = {}
        for line in entry.splitlines():
            match = re.match(r"^(?:        )?(name|run|uses):\s*(.*?)\s*$", line)
            if match:
                fields[match[1]] = re.sub(r"\s+#.*$", "", match[2]).strip("\"'")
        if "name" in fields:
            name = re.sub(r"\$\{\{.*?\}\}", "*", fields["name"])
        elif "uses" in fields:
            name = "Run " + fields["uses"]
        elif "run" in fields and fields["run"] not in ("|", ">", "|-", ">-"):
            name = "Run " + fields["run"]
        else:
            raise Fail(f"{workflow}: step needs an explicit name")
        category(table, name, str(workflow))
    print(f"covered {len(entries)} CI steps")


def runner_kind(job):
    labels = set(job.get("runner_labels", []))
    # Only observed PC and published standard SKU labels are recognised.
    # Never guess a price from an arbitrary runner name or a generic Linux tag.
    jog = [x for x in labels if x == "jog" or x.startswith("jog-")]
    if jog:
        return jog[0] if len(jog) == 1 and jog[0] in {"jog-4vcpu", "jog-8vcpu", "jog-16vcpu"} else "unknown"
    blacksmith = [x for x in labels if x.startswith("blacksmith-")]
    if blacksmith:
        return blacksmith[0] if len(blacksmith) == 1 else "unknown"
    if labels & {"closedwiz-pc", "self-hosted"}:
        return "self-hosted"
    if "ubuntu-slim" in labels:
        return "github-hosted-slim"
    if labels & {"ubuntu-24.04", "ubuntu-22.04", "ubuntu-latest"} and not labels & {"ARM64", "arm64"}:
        return "github-hosted"
    return "unknown"


def read_prices(path):
    columns = ["runner_kind", "compute_usd_per_minute", "platform_usd_per_minute", "source_url", "verified_on"]
    reader = csv.DictReader(read_file(path).splitlines(), delimiter="\t")
    if reader.fieldnames != columns:
        raise Fail(f"{path}: invalid price table columns")
    prices = {}
    for row in reader:
        kind = row["runner_kind"]
        if not kind or kind in prices or set(row) != set(columns) or any(v is None for v in row.values()):
            raise Fail(f"{path}: invalid or repeated price row")
        if not re.fullmatch(r"https://\S+", row["source_url"]):
            raise Fail(f"{path}: price needs a source URL")
        try:
            datetime.strptime(row["verified_on"], "%Y-%m-%d")
            for key in columns[1:3]:
                row[key] = None if row[key] == "unknown" else float(row[key])
                if row[key] is not None and (not math.isfinite(row[key]) or row[key] < 0):
                    raise ValueError()
        except ValueError:
            raise Fail(f"{path}: invalid price or date")
        prices[kind] = row
    return prices


def costs(jobs, code, prices):
    def subtotal(selected):
        minutes, billed, total, unknown = {}, {}, 0, 0
        for job in selected:
            if job.get("timing_unknown"):
                unknown = math.inf
                continue
            if never_ran(job):
                continue
            kind = runner_kind(job)
            seconds = secs(job["completed_at"]) - secs(job["started_at"])
            elapsed = seconds / 60
            # GitHub bills each hosted job rounded up to a whole minute.
            # Jog publishes per-second billing; other third-party estimates
            # retain the existing conservative whole-minute unit.
            charged = elapsed if kind in {"jog-4vcpu", "jog-8vcpu", "jog-16vcpu"} else math.ceil(elapsed)
            minutes[kind] = minutes.get(kind, 0) + elapsed
            billed[kind] = billed.get(kind, 0) + charged
            row = prices.get(kind)
            rate = None if row is None or any(row[k] is None for k in
                       ("compute_usd_per_minute", "platform_usd_per_minute")) else (
                       row["compute_usd_per_minute"] + row["platform_usd_per_minute"])
            if rate is None and elapsed:
                unknown += elapsed
            elif rate is not None:
                total += charged * rate
        return ({k: round(v, 4) for k, v in sorted(minutes.items())}, billed,
                None if unknown else round(total, 6), None if math.isinf(unknown) else round(unknown, 4))
    minutes, billed, total, unknown = subtotal(jobs)
    code_total = subtotal([j for run in code for j in run])[2]
    result = {"runner_minutes": minutes, "billed_minutes": billed, "window_usd": total,
            "per_code_run_usd": None if code_total is None or not code else round(code_total / len(code), 6),
            "unknown_minutes": unknown, "prices": list(prices.values())}
    unknown_jobs = sum(bool(j.get("timing_unknown")) for j in jobs)
    if unknown_jobs:
        result["unknown_jobs"] = unknown_jobs
    return result


def validate_cost(cost, where):
    as_obj(cost, where)
    exact(cost, {"runner_minutes", "billed_minutes", "window_usd", "per_code_run_usd", "unknown_minutes", "prices"} | (set(cost) & {"unknown_jobs"}), where)
    if "unknown_jobs" in cost:
        as_int(cost, "unknown_jobs", where)
    for key in ("window_usd", "per_code_run_usd", "unknown_minutes"):
        if cost[key] is not None:
            as_num(cost, key, where)
    for key in ("runner_minutes", "billed_minutes"):
        for kind in as_obj(cost[key], where):
            as_num(cost[key], kind, where)
    for row in as_list(cost["prices"], where):
        as_obj(row, where)
        exact(row, {"runner_kind", "compute_usd_per_minute", "platform_usd_per_minute", "source_url", "verified_on"}, where)
        for key in ("runner_kind", "source_url", "verified_on"):
            as_str(row, key, where)
        for key in ("compute_usd_per_minute", "platform_usd_per_minute"):
            if row[key] is not None:
                as_num(row, key, where)


def pst_window(now=None):
    instant = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc)
    pst = timezone(timedelta(hours=-8))
    end = instant.astimezone(pst).replace(hour=0, minute=0, second=0, microsecond=0)
    return tuple(t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for t in (end - timedelta(days=1), end))


def money(v):
    return "unknown" if v is None else f"${v:.4f}"


def merged_cost(point):
    total = point.get("cost", {}).get("window_usd")
    return None if total is None or not point["merged_prs"] else total / point["merged_prs"]


def day_change(points, value, currency=False):
    if len(points) < 2 or points[-2]["until"] != points[-1]["since"]:
        return "unknown"
    previous, current = value(points[-2]), value(points[-1])
    if previous is None or current is None:
        return "unknown"
    delta = current - previous
    return f'{"+" if delta >= 0 else "−"}${abs(delta):.4f}' if currency else f'{delta:+.2f}'


def headline_table(points, days=None):
    metrics = [lambda p: p["code_runs"]["queued_to_done"]["median"] if p["code_runs"] else None,
               lambda p: p["code_runs"]["prs_per_hour"] if p["code_runs"] else None,
               lambda p: p.get("cost", {}).get("window_usd"),
               merged_cost, lambda p: p.get("cost", {}).get("per_code_run_usd")]
    rows = ['| Window | Minutes per PR (median) | PRs/hour capacity | Window cost | USD/merged PR | USD/code run |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
    for p in points:
        values = [money(fn(p)) if i >= 2 else show(fn(p), '{:.2f}') for i, fn in enumerate(metrics)]
        rows.append(f'| {md_cell(esc(p["label"]))} | ' + ' | '.join(values) + ' |')
    days = daily_points(points) if days is None else days
    rows.append('| Day-over-day (latest full PST day) | ' + ' | '.join(
        day_change(days, fn, i >= 2) for i, fn in enumerate(metrics)) + ' |')
    rows += ['', 'Window cost = total window CI spend. USD/merged PR = window cost / PRs merged in that window; '
             'includes failures, docs-only and scheduled runs. USD/code run averages only successful code-run spend. '
             'These are list-rate estimates before free minutes, not invoices or attributed PR costs. '
             'Zero merges or missing prices stay unknown. Day-over-day compares adjacent complete PST days only.']
    return rows


def runner_spend(cost, kind):
    row = next((r for r in cost.get("prices", []) if r["runner_kind"] == kind), None)
    if row is None or any(row[k] is None for k in ("compute_usd_per_minute", "platform_usd_per_minute")):
        return None
    return cost["billed_minutes"][kind] * (row["compute_usd_per_minute"] + row["platform_usd_per_minute"])


def chart_minutes(points):
    # Baseline plus daily/checkpoint medians, every value on its point.
    top, bottom, left, right = 96, 276, 20, 790
    ymax, _ = nice_max(max(p["code_runs"]["queued_to_done"]["median"] for p in points) * 1.08)
    out = svg_open(330, "Minutes per PR, every window",
                   "Median per successful code run, one run per PR assumed · the baseline counts from first job created")
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>')
    coords, marks = [], []
    for i, p in enumerate(points):
        v = p["code_runs"]["queued_to_done"]["median"]
        x = left + 40 + (right - left - 80) * i / max(1, len(points) - 1)
        y = bottom - (bottom - top) * v / ymax
        coords.append((x, y))
        latest = i == len(points) - 1
        name, note = short_label(p)
        marks.append(f'<g><title>{esc(p["label"])}: {v:.2f} minutes</title><circle cx="{x:.1f}" cy="{y:.1f}"'
                     f' r="{6 if latest else 4}" fill="{BLUE}" stroke="{SURFACE}" stroke-width="2"/></g>')
        marks.append(text(x, y - 12, f"{v:.1f}", 15 if latest else 12, INK, "middle", 600 if latest else None,
                          cls="value"))
        marks.append(text(x, bottom + 20, name, 12, INK2, "middle"))
        if note:
            marks.append(text(x, bottom + 36, note, 11, MUTED, "middle"))
    out.append(polyline(coords, BLUE))
    out += marks
    return "\n".join(out + ["</svg>"]) + "\n"


def polyline(coords, color):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    return (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"'
            f' stroke-linecap="round"/>')


def dashboard(baseline, dirs, out):
    base = read_point(baseline)
    pairs = sorted([(read_point(d), d) for d in dirs], key=lambda pair: (pair[0]["since"], pair[0]["until"], pair[0]["label"]))
    points = [p for p, _ in pairs]
    all_points = [base] + points
    measured_points = [p for p in all_points if p["code_runs"] is not None]
    daily = daily_points(points)
    latest = daily[-1] if daily else (points[-1] if points else base)
    def minutes(p):
        return "unknown" if p["code_runs"] is None else f'{p["code_runs"]["queued_to_done"]["median"]:.2f}'
    def capacity(p):
        return "unknown" if p["code_runs"] is None else f'{p["code_runs"]["prs_per_hour"]:.2f}'
    md = ['# CI benchmarks', '', '![Daily CI metrics](daily-metrics.svg)', '',
          *headline_table([base, latest], daily), '',
          'Latest full PST day against the Nov 1 baseline. Timing and capacity goals:', '',
          '| Goal | Minutes per PR | PRs/hour capacity | USD/merged PR | USD/code run |',
          '| --- | ---: | ---: | ---: | ---: |']
    md += [f'| {name} | < {minutes} | {capacity}+ | — | — |' for name, minutes, capacity in GOALS]
    md += ['',
           '## Day by day and checkpoints', '',
           '| Window | UTC bounds (PST = UTC−08:00) | Robots | Code runs | Minutes/PR | Capacity/hour | Merged/hour | Cost/code run | Window cost | Selector escapes |',
           '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for p in all_points:
        c = p.get('cost', {})
        n = p['code_runs']['runs'] if p['code_runs'] else 'no successful code runs'
        md.append(f'| {md_cell(esc(p["label"]))} | {p["since"]} – {p["until"]} | {p["robots"]} | {n} | {minutes(p)} | {capacity(p)} | {p["merged_per_hour"]:.2f} | {money(c.get("per_code_run_usd"))} | {money(c.get("window_usd"))} | {escapes_cell(p)} |')
    md += ['', 'Selector escapes: failing tests on a full run of CI on `main` that a merged pull request\'s CI plan skipped, '
           'each reported once on an issue (#1264), counted in the window its CI attempt started in. 0 means every '
           'failed attempt was judged and none was an escape; "unknown" means an attempt could not be judged (no '
           'readable plan, a failure that names no test, a finder run missing or failed, still running) or the window '
           'was not counted. Never 0 for unknown.']
    md += ['', '## Factory benches', '',
           'Four day-over-day benches of the whole factory, not only CI (#1359): every full PST day. '
           '"unknown" means it could not be computed for that day, never 0.', '']
    for name, title, _, _ in FACTORY_CHARTS:
        md += [f'![{title}]({name})', '']
    md += ['| Day | Merged | Ready→merged median (h) | p90 (h) | First-review approvals | Rounds/PR | Main red (min) | Reruns | Runner wait median (min) | p90 (min) |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |']
    md += [factory_row(p) for p in daily]
    md += [''] + FACTORY_NOTES
    md += ['', '[Journey cohorts, finding kinds, credits and tagged experiments](journey-trends.md).']
    md += ['', 'Every bench, the CI ones too, in [1-hour and 6-hour buckets](buckets.md), each value with its sample size.']
    md += ['', '![PRs an hour](prs-per-hour.svg)', '', '![Robot minutes](robot-minutes.svg)', '',
           '![Time split](time-split.svg)', '', '![Minutes per PR over days](minutes-per-pr.svg)', '',
           '## Cost and limits', '',
           'Costs are USD list-rate estimates before included/free minutes, not invoices. '
           'Jog bills by the second; GitHub-hosted jobs round each job up to a whole minute, as do other third-party estimates here. '
           'PC compute here is incremental runner-provider spend ($0); electricity, hardware, maintenance and storage are excluded. '
           'The proposed self-hosted platform fee is postponed per current GitHub docs. '
           'Unknown runner, price or job duration means unknown total, never $0. '
           'Backfill records invalid durations in unsuccessful runs as timing gaps; successful-run timing anomalies still fail closed. '
           'Cost/code run counts successful code runs only; '
           'window cost includes every collected job, including failures, docs-only and scheduled runs. '
           'The collection includes the latest attempt of completed CI runs created inside the window; earlier attempts and '
           'still-running jobs are not billed here. Re-run a window after it settles. '
           'Daily rows use fixed PST, including summer; labelled checkpoints may overlap days and are never added together. '
           'A code run is a proxy for one PR: repeated runs and main pushes mean this is capacity, not actual PR throughput. '
           'Robots is an explicit capacity assumption; mixed-provider capacity is an estimate. '
           'New daily latency is workflow creation to last job completion, an explicit push-to-result proxy: '
           'GitHub does not provide the original push-event timestamp here. The historical baseline uses first-job creation instead. '
           'Daily capacity uses the supplied robot count as a consistent assumption, not a verified historic fleet size. '
           'Missing successful code runs stay unknown and break the daily lines.', '',
           'See [bench.md](bench.md) for the reconstructed baseline correction and all timing tables.', '',
           '| Window | Runner kind | Runner minutes | Billed minutes | USD |', '| --- | --- | ---: | ---: | ---: |']
    sources = set()
    for p in all_points:
        cost = p.get('cost', {})
        if cost.get('unknown_jobs'):
            md.append(f'| {md_cell(esc(p["label"]))} | unknown duration ({cost["unknown_jobs"]} unsuccessful-run jobs) | unknown | unknown | unknown |')
        for kind, value in cost.get('runner_minutes', {}).items():
            md.append(f'| {md_cell(esc(p["label"]))} | {md_cell(esc(kind))} | {value:.4f} | {cost["billed_minutes"][kind]:.4f} | {money(runner_spend(cost, kind))} |')
        for row in cost.get('prices', []):
            sources.add((row['runner_kind'], row['source_url'], row['verified_on'], row['compute_usd_per_minute'], row['platform_usd_per_minute']))
    md += ['', '| Price kind | Compute/min | Platform/min | Source, verified |', '| --- | ---: | ---: | --- |']
    for kind, url, date, compute, platform in sorted(sources, key=str):
        md.append(f'| {md_cell(esc(kind))} | {money(compute)} | {money(platform)} | [{esc(date)}]({url}) |')
    # Preserve the chart command's existing four-file interface.
    chart(baseline, [d for p, d in pairs if p["code_runs"] is not None], out)
    write(Path(out) / 'README.md', '\n'.join(md) + '\n')
    write(Path(out) / 'minutes-per-pr.svg', chart_minutes(measured_points))
    write(Path(out) / 'daily-metrics.svg', chart_daily(daily))
    for name, title, subtitle, panels in FACTORY_CHARTS:
        write(Path(out) / name, chart_days(daily, title, subtitle, panels))
    write_buckets(daily, out)
    trends_module().write_dashboard(SimpleNamespace(**globals()), daily, out, windows=points)


# ---------------------------------------------------------------- daily history (#1252)


def day_date(text):
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            raise ValueError()
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise Fail(f"invalid PST day: {text}")


def backfill(start, through, now, out, robots):
    first = day_date(start)
    yesterday = day_date(pst_window(now)[0][:10])
    last = day_date(through) if through else yesterday
    if last > yesterday or first > last:
        raise Fail("backfill needs complete PST days, from start through yesterday at the latest")
    out = Path(out)
    current = first
    while current <= last:
        following = current + timedelta(days=1)
        since, until = f"{current}T08:00:00Z", f"{following}T08:00:00Z"
        dest = out / str(current)
        if (dest / "point.json").exists():
            point = read_point(dest)
            if (point["since"], point["until"], point["robots"], point["label"], point.get("latency_basis")) != (
                    since, until, robots, f"{current} PST", "workflow created to last job completed"):
                raise Fail(f"{dest}: cached point differs from requested day, robots or latency basis")
            if "factory" in point and "buckets" in point:
                print(f"resume {current}: validated daily point", flush=True)
            else:
                # Measured before the factory benches or their buckets
                # (#1359): add them from the same day's collected jobs.
                print(f"collecting factory history for PST day {current}", flush=True)
                factory_collect(since, until, dest)
                measure(dest, robots, f"{current} PST", allow_empty=True, allow_timing_gaps=True)
        else:
            print(f"collecting PST day {current}", flush=True)
            collect(since, until, dest, workers=2)
            factory_collect(since, until, dest)
            measure(dest, robots, f"{current} PST", allow_empty=True, allow_timing_gaps=True)
        current = following
    print(f"backfill complete: {(last-first).days+1} PST days, {first} through {last}", flush=True)


def daily_points(points):
    """One calendar-day point per PST date; partial checkpoints stay separate."""
    days = {}
    for p in points:
        if (p.get("latency_basis") != "workflow created to last job completed" or p["hours"] != 24
                or not p["since"].endswith("T08:00:00Z") or secs(p["until"]) - secs(p["since"]) != 86400):
            continue
        key = p["since"][:10]
        if key not in days or p["label"] == f"{key} PST":
            days[key] = p
    return [days[key] for key in sorted(days)]


def daily_panel(points, x0, title, unit, value, goal, lower_is_better):
    """One headline metric: its latest day large, then every day on a labelled line.
    No scale: a zero line, the values on their points, tonight's goal as the
    only line when it is in range, the later goals as a note."""
    out = [text(x0, 78, title, 14, INK, weight=600)]
    known = [p for p in points if p["code_runs"] is not None]
    if known:
        last = known[-1]
        v = value(last)
        out.append(text(x0, 134, f"{v:.1f}", 52, INK, weight=600, cls="hero"))
        out.append(text(x0 + 31 * len(f"{v:.1f}") + 12, 134, unit, 18, INK2))
        line = esc(day_name(last["since"]))
        if len(known) > 1:
            prev = known[-2]
            d = v - value(prev)
            when = day_name(prev["since"])[:3]
            if round(d, 1) == 0:
                line += f" · same as {when}"
            else:
                worse = (d > 0) == lower_is_better
                line += (f' · <tspan fill="{WORSE if worse else BETTER}">{"▲" if d > 0 else "▼"}</tspan>'
                         f' {abs(d):.1f} {"worse" if worse else "better"} than {when}')
        out.append(f'<text x="{x0}" y="160" font-size="13" fill="{INK2}">{line}</text>')
        g = goal(GOALS[0])
        # "Under 10" is < 10 and "25+" is >= 25: exactly 10 minutes is not yet met.
        met = v < g if lower_is_better else v >= g
        gap = abs(v - g)
        status = "met" if met else (f"{gap:.1f} to go" if round(gap, 1) > 0 else "not yet")
        out.append(text(x0, 180, (f"Tonight's goal: under {g:g}" if lower_is_better else f"Tonight's goal: {g:g}+")
                        + f" · {status}", 13, INK2))
    else:
        out.append(text(x0, 134, "unknown", 32, INK2, cls="hero"))
    top, bottom, left, right = 228, 408, x0 + 32, x0 + 317
    ymax, _ = nice_max((max((value(p) for p in known), default=0) or 1) * 1.08)
    def y_of(v):
        return bottom - (bottom - top) * v / ymax
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>')
    tonight, g = GOALS[0][0], goal(GOALS[0])
    later = ", ".join(f"{name.lower()} {goal((name, m, c)):g}" for name, m, c in GOALS[1:])
    if g <= ymax:
        y = y_of(g)
        out.append(f'<line class="goal-line" x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK2}"'
                   f' stroke-dasharray="6 4"><title>{tonight}: {g:g} {unit}</title></line>')
        out.append(text(right + 6, y + 4, f"{tonight} {g:g}", 11, INK2))
        note = f"then {later} {unit}"
    else:
        every = f"{tonight.lower()} {g:g}, {later} {unit}"
        note = ("off scale: " if all(goal(x) > ymax for x in GOALS) else "goals: ") + every
    out.append(text(right, 214, note, 11, INK2, "end", cls="off-scale"))
    lines, segment = [], []
    for i, p in enumerate(points):
        x = left + (right - left) * (i / (len(points) - 1) if len(points) > 1 else 0.5)
        date = p["since"][:10]
        out.append(text(x, bottom + 20, day_name(date), 12, INK2, "middle"))
        if p["code_runs"] is None:
            if segment:
                lines.append(polyline(segment, BLUE))
                segment = []
            out.append(text(x, bottom - 8, "unknown", 11, MUTED, "middle"))
            continue
        v = value(p)
        y = y_of(v)
        segment.append((x, y))
        latest = p is known[-1]
        out.append(f'<g class="metric-point"><title>{date}: {v:.2f} {unit}; {p["robots"]} robots assumed</title>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{6 if latest else 4}" fill="{BLUE}" stroke="{SURFACE}"'
                   f' stroke-width="2"/></g>')
        out.append(text(x, y - 12, f"{v:.1f}", 15 if latest else 12, INK, "middle", 600 if latest else None,
                        cls="value"))
    if segment:
        lines.append(polyline(segment, BLUE))
    return lines + out


def cost_panel(points, x0, title, value):
    out = ['<g transform="translate(0 440)">', text(x0, 78, title, 14, INK, weight=600)]
    latest = value(points[-1])
    out.append(text(x0, 134, money(latest), 44 if latest is not None else 32,
                    INK, weight=600, cls="cost-hero"))
    change = day_change(points, value, currency=True)
    out.append(text(x0, 160, f'{day_name(points[-1]["since"])} · day-over-day {change}', 13, INK2))
    out.append(text(x0, 180, 'List-rate USD before free minutes', 13, INK2))
    top, bottom, left, right = 228, 408, x0 + 32, x0 + 317
    ymax, _ = nice_max((max((value(p) for p in points if value(p) is not None), default=0) or 1) * 1.08)
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>')
    segment = []
    previous = None
    for i, p in enumerate(points):
        x = left + (right - left) * (i / (len(points) - 1) if len(points) > 1 else 0.5)
        out.append(text(x, bottom + 20, day_name(p["since"]), 12, INK2, "middle"))
        v = value(p)
        if v is None or (previous is not None and previous["until"] != p["since"]):
            if segment:
                out.append(polyline(segment, BLUE))
                segment = []
        previous = p
        if v is None:
            out.append(text(x, bottom - 8, 'unknown', 11, MUTED, 'middle'))
            continue
        y = bottom - (bottom - top) * v / ymax
        segment.append((x, y))
        out.append(f'<g class="cost-point"><title>{p["since"][:10]}: {money(v)}</title>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{BLUE}"/></g>')
        out.append(text(x, y - 12, money(v), 12, INK, 'middle'))
    if segment:
        out.append(polyline(segment, BLUE))
    return out + ['</g>']


def chart_daily(points):
    out = svg_open(970, "Daily CI metrics", "One point per fixed PST day · time, capacity and CI spend")
    if not points:
        out += [text(0, 100, "No full PST days measured yet. Run the daily backfill.", 14), "</svg>"]
        return "\n".join(out) + "\n"
    out += daily_panel(points, 0, "Minutes per PR (median)", "min",
                       lambda p: p["code_runs"]["queued_to_done"]["median"], lambda g: g[1], True)
    out += daily_panel(points, 425, "PRs an hour of capacity", "PRs/hour",
                       lambda p: p["code_runs"]["prs_per_hour"], lambda g: g[2], False)
    out += cost_panel(points, 0, "USD per merged PR", merged_cost)
    out += cost_panel(points, 425, "USD per code run", lambda p: p.get("cost", {}).get("per_code_run_usd"))
    robots = ", ".join(str(n) for n in sorted({p["robots"] for p in points}))
    out += [text(0, 914, "Minutes: workflow created → last job done (push-to-result proxy);"
                 " one successful code run per PR assumed.", 12, MUTED),
            text(0, 932, f"Capacity assumes {robots} robots; not a verified historic fleet size."
                 " Unknown days break the lines.", 12, MUTED),
            text(0, 950, "USD/merged PR: all window CI spend ÷ merges; USD/code run: successful code-run spend only.", 12, MUTED),
            "</svg>"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- factory benches (#1359)
# Four day-over-day measures of the whole factory, from GitHub's history:
# merged PRs and ticket ready to merged, first-review approvals and review
# rounds, minutes main was red and CI reruns by cause, and runner wait.
# factory.json (local) keeps PR, ticket and run numbers but no comment or
# log text; point.json keeps aggregate numbers only.

READY_LABEL = "ready-for-agent"
APPROVAL_RECORD = "**Approved"
VERDICT_LINE = re.compile(r"VERDICT: (APPROVE|CHANGES)\b")
# A finished attempt of a push run on main: green or red. Cancelled, skipped
# and the rest say nothing about main.
RUN_VERDICT = {"success": "green", "failure": "red", "timed_out": "red", "startup_failure": "red"}
FAILED_ATTEMPT = {"failure", "timed_out", "startup_failure"}
# A failed job's log, in GitHub's and the tools' words: the audit's runner
# and network faults (#1309), then a failed test (#1308).
NETWORK_LOG = re.compile("|".join([
    r"The runner has received a shutdown signal", r"lost communication with the server", r"\bETIMEDOUT\b",
    r"\bECONNRESET\b", r"\bEAI_AGAIN\b", r"Could not resolve host", r"TLS handshake timeout",
    r"The requested URL returned error: 5\d\d", r"Connection reset by peer", r"\bi/o timeout\b"]))
TEST_LOG = re.compile(r"test result: FAILED|[ℹ#] fail [1-9]|FAILED \((?:failures|errors)=")
CAUSES = ("flaky", "runner_network", "after_pass", "after_cancel", "unknown")
LOOKBACK = 86400
HISTORY_QUERY = (
    "query($owner: String!, $repo: String!, $cursor: String) { repository(owner: $owner, name: $repo) {"
    " nameWithOwner pullRequests(states: MERGED, baseRefName: \"" + BASE_BRANCH + "\","
    " orderBy: {field: UPDATED_AT, direction: DESC}, first: 50, after: $cursor) {"
    " pageInfo { hasNextPage endCursor } nodes { number mergedAt updatedAt"
    " comments(first: 100) { pageInfo { hasNextPage } nodes { body createdAt } }"
    " closingIssuesReferences(first: 10) { pageInfo { hasNextPage } nodes { number repository { nameWithOwner }"
    " timelineItems(itemTypes: [LABELED_EVENT], first: 100) { pageInfo { hasNextPage }"
    " nodes { ... on LabeledEvent { createdAt label { name } } } }"
    " comments(first: 100) { pageInfo { hasNextPage } nodes { body createdAt } } } } } } } }")


def utc_text(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_graphql(cursor):
    """One page of merged history: the literal query above, never a mutation."""
    args = ["gh", "api", "graphql", "-F", "owner={owner}", "-F", "repo={repo}", "-f", f"query={HISTORY_QUERY}"]
    if cursor is not None:
        args += ["-f", f"cursor={cursor}"]
    r = subprocess.run(args, capture_output=True, text=True)
    where = "gh api graphql" + (f" after {cursor}" if cursor else "")
    if r.returncode != 0:
        raise Fail(f"{where} failed (exit {r.returncode})")
    ans = as_obj(strict_json(r.stdout, where), where)
    if "errors" in ans:
        raise Fail(f"{where}: a partial answer (errors)")
    return ans, where


def gh_log(job):
    """A failed job's log, classified and dropped; None when it can't be read
    (expired, gone or a failed read): its cause stays unknown."""
    r = subprocess.run(["gh", "api", "--allow-escape-sequences", f"repos/{{owner}}/{{repo}}/actions/jobs/{job}/logs"],
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None


def first_page(c, where):
    as_obj(c, where)
    info = as_obj(need(c, "pageInfo", where), where)
    more = need(info, "hasNextPage", where)
    if type(more) is not bool:
        raise Fail(f"{where}: 'hasNextPage' is not a boolean")
    return [as_obj(n, where) for n in as_list(need(c, "nodes", where), where)], more


def ticket_ready(issue, number, where):
    """The first ready-for-agent label, else the first approval record."""
    events, more = first_page(need(issue, "timelineItems", where), where)
    ready = []
    for e in events:
        label = need(e, "label", where)
        if label is not None and as_str(as_obj(label, where), "name", where) == READY_LABEL:
            ready.append(as_time(e, "createdAt", where))
    if ready:
        return {"number": number, "ready_at": min(ready, key=secs), "ready": "label"}
    if more:
        return {"number": number, "ready_at": None, "ready": "incomplete"}
    comments, more = first_page(need(issue, "comments", where), where)
    approvals = [as_time(c, "createdAt", where) for c in comments
                 if as_str(c, "body", where).startswith(APPROVAL_RECORD)]
    if approvals:
        return {"number": number, "ready_at": min(approvals, key=secs), "ready": "approval"}
    return {"number": number, "ready_at": None, "ready": "incomplete" if more else "none"}


def history_pr(node, repo, where):
    n = as_int(node, "number", where)
    at = f"{where} PR {n}"
    comments, more_comments = first_page(need(node, "comments", at), at)
    verdicts = []
    for c in sorted(comments, key=lambda c: secs(as_time(c, "createdAt", at))):
        match = VERDICT_LINE.match(as_str(c, "body", at))
        if match:
            verdicts.append(match[1])
    issues, more_issues = first_page(need(node, "closingIssuesReferences", at), at)
    tickets = {}
    for issue in issues:
        t = as_int(issue, "number", at)
        # Only this repository's tickets; another's has no ready label here.
        if as_str(as_obj(need(issue, "repository", at), at), "nameWithOwner", at) != repo:
            continue
        if t in tickets:
            raise Fail(f"{at}: ticket {t} is linked twice")
        tickets[t] = ticket_ready(issue, t, f"{at} ticket {t}")
    return n, {"number": n, "merged_at": as_time(node, "mergedAt", at), "verdicts": verdicts,
               "verdicts_complete": not more_comments, "tickets": [tickets[t] for t in sorted(tickets)],
               "tickets_complete": not more_issues}


def read_history(since, until):
    """The merged history: each PR merged into main in the window, its
    verdicts in order and its tickets' ready times."""
    prs, cursor, cursors = {}, None, set()
    while True:
        ans, where = gh_graphql(cursor)
        data = as_obj(need(ans, "data", where), where)
        repo_obj = as_obj(need(data, "repository", where), where)
        repo = as_str(repo_obj, "nameWithOwner", where)
        conn = as_obj(need(repo_obj, "pullRequests", where), where)
        nodes, more = first_page(conn, where)
        end = as_str(conn["pageInfo"], "endCursor", where, null=True)
        older = False
        for node in nodes:
            merged, updated = as_time(node, "mergedAt", where), as_time(node, "updatedAt", where)
            if secs(updated) < secs(since):
                older = True
            if not secs(since) <= secs(merged) < secs(until):
                continue
            n, record = history_pr(node, repo, where)
            if n in prs:
                raise Fail(f"{where}: PR {n} is listed twice")
            prs[n] = record
        # Newest update first, and a merge updates a PR: once one was last
        # updated before the window, no later page holds a merge inside it.
        if not more or older:
            break
        if end is None or end in cursors:
            raise Fail(f"{where}: a repeated or missing cursor")
        cursors.add(end)
        cursor = end
    return [prs[n] for n in sorted(prs)]


def listed_runs(path, start, until, read, main=False):
    runs = {}
    for run, where in pages(path, "workflow_runs", "runs", read):
        as_obj(run, where)
        rid = as_int(run, "id", where)
        at = f"{where} run {rid}"
        if rid in runs:
            raise Fail(f"{at}: listed twice")
        if main and (as_str(run, "event", at) != "push" or as_str(run, "head_branch", at, null=True) != BASE_BRANCH):
            raise Fail(f"{at}: not a push run on {BASE_BRANCH}")
        record = {"id": rid, "status": as_str(run, "status", at), "conclusion": as_str(run, "conclusion", at, null=True),
                  "created": as_time(run, "created_at", at), "attempt": as_int(run, "run_attempt", at),
                  "started": as_time(run, "run_started_at", at), "updated": as_time(run, "updated_at", at)}
        if record["attempt"] < 1:
            raise Fail(f"{at}: run_attempt below 1")
        # The API's range includes its end; the window doesn't.
        if secs(start) <= secs(record["created"]) < secs(until):
            runs[rid] = record
    return runs


def attempt_state(run, k, read):
    """An attempt's status, conclusion and start (its own run_started_at)."""
    if k == run["attempt"]:
        return run["status"], run["conclusion"], run["started"]
    path = f"repos/{{owner}}/{{repo}}/actions/runs/{run['id']}/attempts/{k}"
    where = f"gh api {path}"
    a = as_obj(read(path), where)
    if as_int(a, "id", where) != run["id"] or as_int(a, "run_attempt", where) != k:
        raise Fail(f"{where}: read as another run or attempt")
    return (as_str(a, "status", where), as_str(a, "conclusion", where, null=True),
            as_time(a, "run_started_at", where))


def attempt_jobs(rid, k, read):
    out = []
    for job, where in pages(f"repos/{{owner}}/{{repo}}/actions/runs/{rid}/attempts/{k}/jobs?per_page={PAGE}",
                            "jobs", "jobs", read):
        as_obj(job, where)
        out.append({"id": as_int(job, "id", where), "conclusion": as_str(job, "conclusion", where, null=True),
                    "completed_at": as_time(job, "completed_at", where, null=True),
                    "created_at": as_time(job, "created_at", where),
                    "started_at": as_time(job, "started_at", where, null=True),
                    # A job that never got a runner has none and no steps.
                    "ran": bool(as_str(job, "runner_name", where, null=True)) or bool(as_list(need(job, "steps", where), where)),
                    "attempt": as_int(job, "run_attempt", where), "where": where})
    return out


def attempt_finished(rid, k, read):
    """A finished attempt ends when its last job does; None if it has none."""
    jobs = attempt_jobs(rid, k, read)
    for job in jobs:
        if job["completed_at"] is None:
            raise Fail(f"{job['where']}: a finished attempt has a job with no completion")
    return utc_text(max(secs(job["completed_at"]) for job in jobs)) if jobs else None


def read_main(since, until, read):
    """Every green or red attempt of main's push runs that could set main's
    state in the window: the window's runs, and the look-back's newest first
    until one had finished green or red before the window starts."""
    start = utc_text(secs(since) - LOOKBACK)
    runs = listed_runs(f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs?event=push&branch={BASE_BRANCH}"
                       f"&created={start}..{until}&per_page={PAGE}", start, until, read, main=True)
    observations, untimed, carry = [], 0, False
    for run in sorted(runs.values(), key=lambda r: (secs(r["created"]), r["id"]), reverse=True):
        found = []
        for k in range(1, run["attempt"] + 1):
            status, conclusion, _ = attempt_state(run, k, read)
            if status != "completed" or conclusion not in RUN_VERDICT:
                continue
            finished = attempt_finished(run["id"], k, read)
            if finished is None:
                untimed += 1
                continue
            found.append({"run": run["id"], "attempt": k, "created_at": run["created"], "finished_at": finished,
                          "verdict": RUN_VERDICT[conclusion]})
        observations += found
        if secs(run["created"]) < secs(since) and any(secs(o["finished_at"]) < secs(since) for o in found):
            carry = True
            break
    observations.sort(key=lambda o: (secs(o["finished_at"]), o["run"], o["attempt"]))
    return {"observations": observations, "carry_in": carry, "untimed": untimed}


def rerun_cause(rid, prev, prev_conclusion, conclusion, read):
    # A rerun of a passed attempt (a re-test) or a cancelled one is no fault.
    if prev_conclusion == "success":
        return "after_pass"
    if prev_conclusion == "cancelled":
        return "after_cancel"
    if prev_conclusion not in FAILED_ATTEMPT:
        return "unknown"
    failed = [job["id"] for job in attempt_jobs(rid, prev, read) if job["conclusion"] in ("failure", "timed_out")]
    logs = [gh_log(job) for job in failed]
    if any(text is not None and NETWORK_LOG.search(text) for text in logs):
        return "runner_network"
    # Flaky only when every failed job's log is readable and shows a failed
    # test, and the rerun passed: one unexplained failure makes it unknown.
    if failed and conclusion == "success" and all(text is not None and TEST_LOG.search(text) for text in logs):
        return "flaky"
    return "unknown"


# GitHub reruns a workflow run up to 30 days after its first run, so every
# rerun of the window belongs to a run created at most 30 days before it.
RERUN_LOOKBACK_DAYS = 30


def collected_attempts(jobs):
    """jobs.jsonl's complete attempts: (run, attempt) -> that attempt's own
    jobs, from records collect wrote with their identity. Only the attempt
    collect read (its run's latest then) is complete; older records, without
    identity, reuse nothing."""
    out = {}
    for j in jobs:
        if "id" in j and j["run_attempt"] == j["collected_attempt"]:
            out.setdefault((j["run"], j["run_attempt"]), []).append(
                {"id": j["id"], "created_at": j["created_at"], "started_at": j["started_at"],
                 "ran": not never_ran(j), "attempt": j["run_attempt"]})
    return out


def read_attempts(since, until, read, collected=None):
    """Every attempt of a ci.yml run that started in the window, by its own
    start: the window's runs and any run of the 30 days before it updated
    inside it (a run listing holds at most 1,000, so a day at a time). Each
    rerun (attempt 2 on) with why the attempt before it ended; and the
    created-to-started wait of every job created in the window, once each
    (by run and job id), from each attempt's own job list: reused from
    jobs.jsonl when that exact attempt was collected, otherwise read."""
    collected = collected or {}
    s, u = secs(since), secs(until)
    edges = [s - 86400 * d for d in range(RERUN_LOOKBACK_DAYS, 0, -1)] + [s, u]
    runs = {}
    for a, b in zip(edges, edges[1:]):
        part = listed_runs(f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs?created={utc_text(a)}.."
                           f"{utc_text(b)}&per_page={PAGE}", utc_text(a), utc_text(b), read)
        if set(part) & set(runs):
            raise Fail(f"run {min(set(part) & set(runs))} is listed on two days")
        runs.update(part)
    reruns, attempts, waits, seen = [], [], [], set()
    for run in sorted(runs.values(), key=lambda r: (secs(r["created"]), r["id"])):
        today = secs(run["created"]) >= s
        if not today and secs(run["updated"]) < s:
            continue
        n = run["attempt"]
        states = {k: attempt_state(run, k, read) for k in range(1, n + 1)}
        for k in range(1, n + 1):
            if s <= secs(states[k][2]) < u:
                attempts.append({"run": run["id"], "attempt": k, "started_at": states[k][2]})
        for k in range(2, n + 1):
            if s <= secs(states[k][2]) < u:
                reruns.append({"run": run["id"], "attempt": k, "started_at": states[k][2],
                               "cause": rerun_cause(run["id"], k - 1, states[k - 1][1], states[k][1], read)})
        for k in range(1, n + 1):
            own = collected.get((run["id"], k))
            for job in own if own is not None else attempt_jobs(run["id"], k, read):
                # A job carried over from an earlier attempt is that one's.
                if (job["ran"] and job["attempt"] == k and job["started_at"] is not None
                        and s <= secs(job["created_at"]) < u and (run["id"], job["id"]) not in seen):
                    seen.add((run["id"], job["id"]))
                    waits.append({"created_at": job["created_at"], "started_at": job["started_at"]})
    return reruns, attempts, waits


def factory_collect(since, until, out):
    if shutil.which("gh") is None:
        raise Fail("gh is not on PATH")
    cache = {}

    def read(path):
        if path not in cache:
            cache[path] = gh(path)
        return cache[path]

    history, main = read_history(since, until), read_main(since, until, read)
    out = Path(out)
    jobs_file = out / "jobs.jsonl"
    collected = collected_attempts(read_jobs(out, allow_timing_gaps=True)) if jobs_file.exists() else {}
    reruns, attempts, waits = read_attempts(since, until, read, collected)
    facts = {"since": since, "until": until, "prs": history, "main": main, "reruns": reruns, "attempts": attempts,
             "jobs": waits}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / "factory.json", json.dumps(facts, indent=2, sort_keys=True) + "\n")
    print(f"collected {len(facts['prs'])} merged PRs, {len(facts['main']['observations'])} main verdicts and"
          f" {len(facts['reruns'])} reruns into {out}")


def read_factory(d, since, until):
    where = f"{d}/factory.json"
    f = as_obj(strict_json(read_file(Path(d) / "factory.json"), where), where)
    exact(f, {"since", "until", "prs", "main", "reruns", "attempts", "jobs"}, where)
    if (as_time(f, "since", where), as_time(f, "until", where)) != (since, until):
        raise Fail(f"{where}: not this window's")
    for i, pr in enumerate(as_list(f["prs"], where)):
        at = f"{where} PR {i + 1}"
        exact(as_obj(pr, at), {"number", "merged_at", "verdicts", "verdicts_complete", "tickets", "tickets_complete"}, at)
        as_int(pr, "number", at)
        if not secs(since) <= secs(as_time(pr, "merged_at", at)) < secs(until):
            raise Fail(f"{at}: merged outside the window")
        if any(v not in ("APPROVE", "CHANGES") for v in as_list(pr["verdicts"], at)):
            raise Fail(f"{at}: unknown verdict")
        for t in as_list(pr["tickets"], at):
            exact(as_obj(t, at), {"number", "ready_at", "ready"}, at)
            as_int(t, "number", at)
            if (t["ready"] in ("label", "approval")) != (as_time(t, "ready_at", at, null=True) is not None) or \
                    t["ready"] not in ("label", "approval", "none", "incomplete"):
                raise Fail(f"{at}: bad ready record")
        for k in ("verdicts_complete", "tickets_complete"):
            if type(need(pr, k, at)) is not bool:
                raise Fail(f"{at}: '{k}' is not a boolean")
    main = as_obj(f["main"], f"{where} main")
    exact(main, {"observations", "carry_in", "untimed"}, f"{where} main")
    if type(main["carry_in"]) is not bool:
        raise Fail(f"{where} main: 'carry_in' is not a boolean")
    as_int(main, "untimed", f"{where} main")
    for o in as_list(main["observations"], f"{where} main"):
        at = f"{where} main observation"
        exact(as_obj(o, at), {"run", "attempt", "created_at", "finished_at", "verdict"}, at)
        as_int(o, "run", at), as_int(o, "attempt", at), as_time(o, "created_at", at), as_time(o, "finished_at", at)
        if o["verdict"] not in ("green", "red"):
            raise Fail(f"{at}: unknown verdict")
    for r in as_list(f["reruns"], where):
        at = f"{where} rerun"
        exact(as_obj(r, at), {"run", "attempt", "started_at", "cause"}, at)
        as_int(r, "run", at), as_time(r, "started_at", at)
        if as_int(r, "attempt", at) < 2 or r["cause"] not in CAUSES:
            raise Fail(f"{at}: bad rerun")
    for a in as_list(f["attempts"], where):
        at = f"{where} attempt"
        exact(as_obj(a, at), {"run", "attempt", "started_at"}, at)
        as_int(a, "run", at), as_int(a, "attempt", at), as_time(a, "started_at", at)
    for j in as_list(f["jobs"], where):
        at = f"{where} job"
        exact(as_obj(j, at), {"created_at", "started_at"}, at)
        as_time(j, "created_at", at), as_time(j, "started_at", at)
    return f


def spread(values, digits=4):
    if not values:
        return None, None
    return round(statistics.median(values), digits), round(nearest_rank(values, 0.9), digits)


def main_red(main, since, until):
    """Minutes main's newest-pushed finished run was red. Its state is the
    green or red attempt with the newest push (run creation, then run, then
    attempt) among those finished by then; unknown until one has."""
    def key(o):
        return secs(o["created_at"]), o["run"], o["attempt"]

    s, u = secs(since), secs(until)
    best = None
    for o in main["observations"]:
        if secs(o["finished_at"]) < s and (best is None or key(o) > key(best)):
            best = o
    t, red, unknown = s, 0, 0
    inside = sorted((o for o in main["observations"] if s <= secs(o["finished_at"]) < u),
                    key=lambda o: (secs(o["finished_at"]),) + key(o))
    for at, o in [(secs(o["finished_at"]), o) for o in inside] + [(u, None)]:
        if best is None:
            unknown += at - t
        elif best["verdict"] == "red":
            red += at - t
        if o is not None and (best is None or key(o) > key(best)):
            best = o
        t = at
    untimed = main["untimed"]
    return {"red_minutes": None if unknown or untimed else round(red / 60, 2),
            "unknown_minutes": round(unknown / 60, 2), "untimed_verdicts": untimed, "verdicts": len(inside)}


def first_closers(prs):
    """Each ticket's first merged closing PR (a PR whose closing tickets are
    all known), so a ticket counts once however its PRs are split."""
    first = {}
    for p in sorted(prs, key=lambda p: (secs(p["merged_at"]), p["number"])):
        if p["tickets_complete"]:
            for t in p["tickets"]:
                first.setdefault(t["number"], p["number"])
    return first


def factory_point(facts, since, until, first=None):
    """The factory record of [since, until): PRs by merge, reruns and
    attempts by start, waits by the job's creation, main red within it.
    `first` is the whole day's ticket owners, for a bucket of it."""
    s, u = secs(since), secs(until)

    def inside(t):
        return s <= secs(t) < u

    prs = [p for p in facts["prs"] if inside(p["merged_at"])]
    first = first_closers(prs) if first is None else first
    hours, unknown, unlinked = [], 0, 0
    for p in prs:
        if not p["tickets_complete"]:
            unknown += max(1, len(p["tickets"]))
            continue
        if not p["tickets"]:
            unlinked += 1
        for t in p["tickets"]:
            if first.get(t["number"]) != p["number"]:
                continue
            if t["ready_at"] is None or secs(t["ready_at"]) > secs(p["merged_at"]):
                unknown += 1
            else:
                hours.append((secs(p["merged_at"]) - secs(t["ready_at"])) / 3600)
    median, p90 = spread(hours)
    reviewed = [p for p in prs if p["verdicts"]]
    complete = [p for p in reviewed if p["verdicts_complete"]]
    first_approve = sum(p["verdicts"][0] == "APPROVE" for p in reviewed)
    waits = [(secs(j["started_at"]) - secs(j["created_at"])) / 60 for j in facts["jobs"]
             if inside(j["created_at"]) and secs(j["started_at"]) >= secs(j["created_at"])]
    wait_median, wait_p90 = spread(waits)
    causes = [r["cause"] for r in facts["reruns"] if inside(r["started_at"])]
    return {
        "merged_prs": len(prs),
        "ready_to_merged_hours": {"tickets": len(hours), "median": median, "p90": p90, "unknown_tickets": unknown,
                                  "unlinked_prs": unlinked},
        "first_review": {"reviewed_prs": len(reviewed), "first_approve": first_approve,
                         "share": round(first_approve / len(reviewed), 4) if reviewed else None,
                         "rounds_per_pr": round(sum(len(p["verdicts"]) for p in complete) / len(complete), 4)
                         if complete else None,
                         "rounds_prs": len(complete),
                         "unreviewed_prs": sum(not p["verdicts"] and p["verdicts_complete"] for p in prs),
                         "unknown_prs": sum(not p["verdicts"] and not p["verdicts_complete"] for p in prs)},
        "main_red": main_red(facts["main"], since, until),
        "reruns": {"total": len(causes), **{c: causes.count(c) for c in CAUSES},
                   "attempts": sum(inside(a["started_at"]) for a in facts["attempts"])},
        "runner_wait_minutes": {"jobs": len(waits), "median": wait_median, "p90": wait_p90},
    }


FACTORY_SHAPE = {
    "ready_to_merged_hours": ({"tickets", "unknown_tickets", "unlinked_prs"}, {"median", "p90"}),
    "first_review": ({"reviewed_prs", "first_approve", "rounds_prs", "unreviewed_prs", "unknown_prs"},
                     {"share", "rounds_per_pr"}),
    "main_red": ({"untimed_verdicts", "verdicts"}, {"red_minutes", "unknown_minutes"}),
    "reruns": ({"total", "attempts", *CAUSES}, set()),
    "runner_wait_minutes": ({"jobs"}, {"median", "p90"}),
}


def validate_factory(f, where):
    as_obj(f, where)
    exact(f, {"merged_prs"} | set(FACTORY_SHAPE), where)
    as_int(f, "merged_prs", where)
    for part, (counts, numbers) in FACTORY_SHAPE.items():
        at = f"{where} {part}"
        exact(as_obj(f[part], at), counts | numbers, at)
        for k in counts:
            as_int(f[part], k, at)
        for k in numbers:
            if f[part][k] is not None:
                as_num(f[part], k, at)
    if f["main_red"]["unknown_minutes"] is None:
        raise Fail(f"{where} main_red: 'unknown_minutes' is not a number")


def factory_of(p):
    return p.get("factory")


def show(v, fmt="{:.2f}"):
    return "unknown" if v is None else fmt.format(v)


def factory_row(p):
    f = factory_of(p)
    cells = [md_cell(esc(p["label"])), str(p["merged_prs"])]
    if f is None:
        return "| " + " | ".join(cells + ["unknown"] * 8) + " |"
    r, v, m, n, w = (f["ready_to_merged_hours"], f["first_review"], f["main_red"], f["reruns"],
                     f["runner_wait_minutes"])
    approvals = "unknown" if v["share"] is None else f"{v['share']:.0%} ({v['first_approve']} of {v['reviewed_prs']})"
    reruns = (f"{n['total']} ({n['flaky']} flaky, {n['runner_network']} runner/network, {n['after_pass']} after a pass,"
              f" {n['after_cancel']} after a cancel, {n['unknown']} unknown)")
    cells += [show(r["median"]), show(r["p90"]), approvals, show(v["rounds_per_pr"]), show(m["red_minutes"], "{:.0f}"),
              reruns, show(w["median"]), show(w["p90"])]
    return "| " + " | ".join(cells) + " |"


def factory_value(path):
    def get(p):
        v = factory_of(p)
        for k in path:
            if v is None:
                return None
            v = v[k]
        return v
    return get


FACTORY_CHARTS = [
    ("factory-throughput.svg", "Factory throughput", "Merged PRs a day, and how long a ticket took from ready to merged", [
        ("Merged PRs per day", "PRs", "count", [("Merged into main", BLUE, lambda p: p["merged_prs"], "{:.0f}", "PRs merged")]),
        ("Hours from ticket ready to merged", "hours", "line", [
            ("Median", BLUE, factory_value(["ready_to_merged_hours", "median"]), "{:.1f}", "h median"),
            ("p90", ORANGE, factory_value(["ready_to_merged_hours", "p90"]), "{:.1f}", "h p90")])]),
    ("factory-reviews.svg", "Factory reviews", "Merged PRs whose first verdict approved, and verdicts per reviewed merged PR", [
        ("First-review approvals", "% of reviewed", "line", [
            ("First verdict APPROVE", AQUA, lambda p: None if factory_value(["first_review", "share"])(p) is None
             else 100 * factory_value(["first_review", "share"])(p), "{:.0f}%", "first-review approvals")]),
        ("Review rounds per reviewed merged PR", "rounds", "line", [
            ("Rounds", VIOLET, factory_value(["first_review", "rounds_per_pr"]), "{:.2f}", "rounds a PR")])]),
    ("factory-main.svg", "Main red and CI reruns", "Minutes main's latest finished push run was red, and reruns by cause", [
        ("Minutes main was red", "minutes", "line", [
            ("Red", ORANGE, factory_value(["main_red", "red_minutes"]), "{:.0f}", "min red")]),
        ("CI reruns per day, by cause", "reruns", "stack", [
            ("Flaky test (#1308)", MAGENTA, factory_value(["reruns", "flaky"]), "{:.0f}", "flaky reruns"),
            ("Runner/network (#1309)", BLUE, factory_value(["reruns", "runner_network"]), "{:.0f}",
             "runner/network reruns"),
            ("After a pass", AQUA, factory_value(["reruns", "after_pass"]), "{:.0f}", "reruns after a pass"),
            ("After a cancel", YELLOW, factory_value(["reruns", "after_cancel"]), "{:.0f}", "reruns after a cancel"),
            ("Unknown", VIOLET, factory_value(["reruns", "unknown"]), "{:.0f}", "unknown-cause reruns")])]),
    ("factory-runner-wait.svg", "Runner wait", "Minutes each CI job waited for a runner (created to started), apart from run time", [
        ("Runner wait per job", "minutes", "line", [
            ("Median", BLUE, factory_value(["runner_wait_minutes", "median"]), "{:.2f}", "min median wait"),
            ("p90", ORANGE, factory_value(["runner_wait_minutes", "p90"]), "{:.2f}", "min p90 wait")])]),
]


def chart_days(points, title, subtitle, panels, grid=True):
    """Aligned date panels in the daily chart's style: lines, whole-number
    lines ("count") or bars stacked by series ("stack"). An unknown value
    breaks its line and says unknown, never 0. No goal is set for these."""
    height = 110 + 310 * len(panels)
    out = svg_open(height, title, subtitle)
    if not points:
        out += ['<text x="24" y="100" font-size="14">No full PST days measured yet. Run the daily backfill.</text>', '</svg>']
        return '\n'.join(out) + '\n'
    origin, end = secs(points[0]['since']), secs(points[-1]['since'])

    def x(p):
        return 78 + 650 * (secs(p['since']) - origin) / max(86400, end - origin)

    for panel, (ptitle, unit, kind, series) in enumerate(panels):
        top, bottom = 125 + panel * 310, 325 + panel * 310
        if kind == "stack":
            observed = [sum(s[2](p) or 0 for s in series) for p in points]
        else:
            observed = [s[2](p) for s in series for p in points if s[2](p) is not None]
        ymax, tick = nice_max((max(observed + ([1] if grid else [0])) or 1) * 1.15)
        if kind != "line" and tick < 1:
            ymax, tick = math.ceil(ymax), 1
        out.append(f'<text x="24" y="{top - 45}" font-size="16" font-weight="600" fill="{INK}">{esc(ptitle)}</text>')
        lx = 24
        for name, color, _, _, _ in series:
            out.append(f'<rect x="{lx}" y="{top - 33}" width="10" height="10" rx="2" fill="{color}"/>')
            out.append(f'<text x="{lx + 15}" y="{top - 24}" font-size="12" fill="{INK2}">{esc(name)}</text>')
            lx += 15 + 7 * len(name) + 22
        if not grid:
            out.append(f'<line x1="65" x2="750" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>')
        for n in range(int(round(ymax / tick)) + 1) if grid else ():
            v = n * tick
            y = bottom - (bottom - top) * v / ymax
            out.append(f'<line x1="65" x2="750" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
            out.append(f'<text x="55" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="{MUTED}">{v:g}</text>')
        out.append(f'<text x="750" y="{bottom + 36}" text-anchor="end" font-size="11" fill="{MUTED}">{esc(unit)}</text>')
        for p in points:
            px, date = x(p), p['since'][:10]
            out.append(f'<text x="{px:.1f}" y="{bottom + 21}" text-anchor="middle" font-size="11" fill="{MUTED}">{date}</text>')
            if all(s[2](p) is None for s in series):
                out.append(f'<text x="{px:.1f}" y="{bottom - 8}" text-anchor="middle" font-size="11" fill="{INK2}">unknown</text>')
            elif kind == "stack":
                y, total = bottom, 0
                for name, color, value, fmt, words in series:
                    v = value(p) or 0
                    h = (bottom - top) * v / ymax
                    if v:
                        out.append(f'<g class="metric-point"><title>{date}: {fmt.format(v)} {esc(words)}</title>'
                                   f'<rect x="{px - 14:.1f}" y="{y - h:.1f}" width="28" height="{h:.1f}" fill="{color}"/></g>')
                    y, total = y - h, total + v
                out.append(f'<text x="{px:.1f}" y="{y - 6:.1f}" text-anchor="middle" font-size="12" fill="{INK}">{total:g}</text>')
        if kind == "stack":
            continue
        for i, (name, color, value, fmt, words) in enumerate(series):
            segment = []
            for p in points + [None]:
                v = None if p is None else value(p)
                if v is None:
                    if segment:
                        out.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2"/>')
                    segment = []
                    continue
                px, py = x(p), bottom - (bottom - top) * v / ymax
                segment.append(f'{px:.1f},{py:.1f}')
                out.append(f'<g class="metric-point"><title>{p["since"][:10]}: {fmt.format(v)} {esc(words)}</title>'
                           f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}"/></g>')
                # The first series labels above its points, the second below
                # unless that would reach the date axis.
                dy = -10 if i == 0 or py + 18 > bottom - 4 else 18
                out.append(f'<text x="{px:.1f}" y="{py + dy:.1f}" text-anchor="middle" font-size="12" fill="{INK}">'
                           f'{fmt.format(v)}</text>')
    out += [f'<text x="24" y="{height - 20}" font-size="12" fill="{INK2}">Fixed PST days. Unknown values break the lines;'
            ' they are never drawn as 0. No goal is set for these benches yet.</text>', '</svg>']
    return '\n'.join(out) + '\n'


FACTORY_NOTES = [
    "- **Merged** counts PRs merged into `main` in the PST day. **Ready to merged** runs from a ticket's first"
    " `ready-for-agent` label (or, without one, its first `**Approved` record) to the merge of its first"
    " closing PR that day; tickets without either, or whose history runs past one page, are unknown and"
    " PRs that close no ticket of this repository are counted apart (unlinked).",
    "- **First-review approvals** is the share of merged PRs with a `VERDICT:` comment whose first one says"
    " APPROVE; **rounds** is their `VERDICT:` comments per PR. PRs merged without a verdict (docs-only merges)"
    " are left out and counted.",
    "- **Main red** is the minutes, within the day, that the green or red attempt of `main`'s push runs with the"
    " newest push, among those finished, was red. Cancelled and skipped runs say nothing; a day that starts"
    " with no known state, or a finished attempt with no job times, is unknown.",
    "- **Reruns** are `ci.yml` attempts after a run's first that started in the day, by the attempt's own"
    " start, including reruns of runs created up to 30 days before (GitHub's rerun limit). A rerun's cause is the attempt before it,"
    " read from its failed jobs' logs: runner or network when a log names a runner shutdown or a network"
    " fault (#1309); flaky when the rerun passed and every failed job's log is readable and shows a failed"
    " test (#1308); after a pass (a re-test) or after a cancel when the attempt before it passed or was"
    " cancelled; otherwise, including expired logs, failures that are not all tests and failures that failed"
    " again, unknown.",
    "- **Runner wait** is each `ci.yml` job's created to started, by the job's own creation, for jobs of every"
    " attempt that got a runner, each job once (a job carried over from an earlier attempt counts in its"
    " own); run time is shown in the CI tables above.",
    "- Only aggregate numbers are published: no PR, ticket, run or thread numbers, and no comment or log text.",
]


# ---------------------------------------------------------------- buckets (#1359, BN2)
# Every bench in 1-hour and 6-hour buckets of the window, each with its sample
# size: a run, a job and a rerun by its run's creation, a PR by its merge, a
# main verdict by its finish; main red counts the minutes inside the bucket.

BUCKET_SIZES = (("1h", 1), ("6h", 6))
BUCKET_CI = {"code_runs", "minutes_per_pr", "prs_per_hour", "merged_prs"}


def buckets(since, until, robots, table, runs, code, merged_times, facts, jobs):
    created = {rid: min(secs(j.get("run_created_at", j["created_at"])) for j in js) for rid, js in runs.items()}
    owners = first_closers(facts["prs"]) if facts is not None else None
    out = {}
    for name, hours in BUCKET_SIZES:
        rows, start = [], secs(since)
        while start < secs(until):
            end = min(start + 3600 * hours, secs(until))

            def inside(t):
                return start <= t < end

            selected = [r for r in code if inside(created[r[0]["run"]])]
            c = cohort(selected, table, False, robots, CODE_RULE)
            row = {"start": utc_text(start), "end": utc_text(end),
                   "ci": {"code_runs": len(selected), "minutes_per_pr": c["queued_to_done"]["median"] if c else None,
                          "prs_per_hour": c["prs_per_hour"] if c else None,
                          "merged_prs": sum(inside(secs(t)) for t in merged_times.values())}}
            if facts is not None:
                row["factory"] = factory_point(facts, row["start"], row["end"], owners)
            rows.append(row)
            start = end
        out[name] = rows
    return out


def validate_buckets(b, where):
    as_obj(b, where)
    exact(b, {name for name, _ in BUCKET_SIZES}, where)
    for name, _ in BUCKET_SIZES:
        for i, row in enumerate(as_list(b[name], where)):
            at = f"{where} {name} {i + 1}"
            as_obj(row, at)
            exact(row, {"start", "end", "ci"} | (set(row) & {"factory"}), at)
            if secs(as_time(row, "end", at)) <= secs(as_time(row, "start", at)):
                raise Fail(f"{at}: ends before it starts")
            ci = as_obj(row["ci"], at)
            exact(ci, BUCKET_CI, at)
            as_int(ci, "code_runs", at), as_int(ci, "merged_prs", at)
            for k in ("minutes_per_pr", "prs_per_hour"):
                if ci[k] is not None:
                    as_num(ci, k, at)
            if "factory" in row:
                validate_factory(row["factory"], f"{at} factory")


def pst_clock(t, start):
    """A bucket edge in fixed PST; a day's end reads 24:00."""
    local = datetime.fromtimestamp(t - 8 * 3600, timezone.utc)
    if not start and local.hour == 0 and local.minute == 0:
        return "24:00"
    return local.strftime("%Y-%m-%d %H:%M" if start else "%H:%M")


def with_n(value, n, fmt="{:.2f}", noun=""):
    return f"{show(value, fmt)} (n={n}{noun})"


BUCKET_HEAD = ["| Bucket (PST) | Minutes/PR | PRs/hour capacity | Merged | Ready→merged median (h) |"
               " Ready→merged p90 (h) | First-review approvals | Rounds/PR | Main red (min) | Reruns |"
               " Runner wait median (min) | Runner wait p90 (min) |",
               "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
BUCKET_COLUMNS = 11


def bucket_row(row):
    ci, f = row["ci"], row.get("factory")
    cells = [f'{pst_clock(secs(row["start"]), True)}–{pst_clock(secs(row["end"]), False)} PST',
             with_n(ci["minutes_per_pr"], ci["code_runs"]), with_n(ci["prs_per_hour"], ci["code_runs"]),
             str(ci["merged_prs"])]
    if f is None:
        return "| " + " | ".join(cells + ["unknown"] * (BUCKET_COLUMNS - 3)) + " |"
    r, v, m, n, w = (f["ready_to_merged_hours"], f["first_review"], f["main_red"], f["reruns"],
                     f["runner_wait_minutes"])
    cells += [with_n(r["median"], r["tickets"]), with_n(r["p90"], r["tickets"]),
              with_n(v["share"], v["reviewed_prs"], "{:.0%}"), with_n(v["rounds_per_pr"], v["rounds_prs"]),
              with_n(m["red_minutes"], m["verdicts"], "{:.0f}"), f'{n["total"]} (n={n["attempts"]} attempts)',
              with_n(w["median"], w["jobs"]), with_n(w["p90"], w["jobs"])]
    return "| " + " | ".join(cells) + " |"


def bucket_value(*path):
    def get(row):
        v = row
        for k in path:
            if v is None:
                return None
            v = v.get(k) if isinstance(v, dict) else None
        return v
    return get


def share_pct(row):
    v = bucket_value("factory", "first_review", "share")(row)
    return None if v is None else 100 * v


BUCKET_PANELS = [
    ("Minutes per PR (median)", BLUE, bucket_value("ci", "minutes_per_pr"), bucket_value("ci", "code_runs"), "{:.2f}"),
    ("PRs an hour of capacity", AQUA, bucket_value("ci", "prs_per_hour"), bucket_value("ci", "code_runs"), "{:.1f}"),
    ("Merged PRs", BLUE, bucket_value("ci", "merged_prs"), bucket_value("ci", "merged_prs"), "{:.0f}"),
    ("Ready to merged, median hours", ORANGE, bucket_value("factory", "ready_to_merged_hours", "median"),
     bucket_value("factory", "ready_to_merged_hours", "tickets"), "{:.1f}"),
    ("Ready to merged, p90 hours", ORANGE, bucket_value("factory", "ready_to_merged_hours", "p90"),
     bucket_value("factory", "ready_to_merged_hours", "tickets"), "{:.1f}"),
    ("First-review approvals (%)", AQUA, share_pct, bucket_value("factory", "first_review", "reviewed_prs"), "{:.0f}%"),
    ("Main red minutes", ORANGE, bucket_value("factory", "main_red", "red_minutes"),
     bucket_value("factory", "main_red", "verdicts"), "{:.0f}"),
    ("CI reruns", MAGENTA, bucket_value("factory", "reruns", "total"), bucket_value("factory", "reruns", "attempts"),
     "{:.0f}"),
    ("Runner wait, median minutes", VIOLET, bucket_value("factory", "runner_wait_minutes", "median"),
     bucket_value("factory", "runner_wait_minutes", "jobs"), "{:.2f}"),
    ("Runner wait, p90 minutes", VIOLET, bucket_value("factory", "runner_wait_minutes", "p90"),
     bucket_value("factory", "runner_wait_minutes", "jobs"), "{:.2f}"),
]
THIN = 3


def chart_buckets(rows, title, subtitle, hour_labels):
    """One small panel per bench over the buckets, each point's sample size
    beneath it; a bucket with fewer than 3 samples is a hollow (thin) mark.
    Unknown breaks the line and is never drawn as 0."""
    pitch, plot = 190, 110
    height = 100 + pitch * len(BUCKET_PANELS) + 30
    out = svg_open(height, title, subtitle)
    if not rows:
        out += ['<text x="24" y="100" font-size="14">No bucketed full PST days measured yet.</text>', '</svg>']
        return '\n'.join(out) + '\n'
    t0, t1 = secs(rows[0]["start"]), secs(rows[-1]["end"])

    def x(row):
        return 78 + 650 * ((secs(row["start"]) + secs(row["end"])) / 2 - t0) / (t1 - t0)

    for k, (name, color, value, size, fmt) in enumerate(BUCKET_PANELS):
        top = 105 + k * pitch
        bottom = top + plot
        known = [value(r) for r in rows if value(r) is not None]
        ymax, tick = nice_max(max(known + [1]) * 1.15)
        out.append(f'<text x="24" y="{top - 12}" font-size="14" font-weight="600" fill="{INK}">{esc(name)}</text>')
        for n in range(int(round(ymax / tick)) + 1):
            y = bottom - plot * n * tick / ymax
            out.append(f'<line x1="65" x2="750" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
            out.append(f'<text x="55" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="{MUTED}">{n * tick:g}</text>')
        segment = []
        for r in rows + [None]:
            v = None if r is None else value(r)
            if v is None:
                if segment:
                    out.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="1.5"/>')
                segment = []
                if r is None:
                    continue
            px = x(r)
            n = size(r)
            label = f'{pst_clock(secs(r["start"]), True)}–{pst_clock(secs(r["end"]), False)} PST'
            out.append(f'<text x="{px:.1f}" y="{bottom + 13}" text-anchor="middle" font-size="8" fill="{MUTED}">'
                       f'n={"?" if n is None else n}</text>')
            if v is None:
                out.append(f'<g><title>{label}: unknown (n={"?" if n is None else n})</title>'
                           f'<text x="{px:.1f}" y="{bottom - 4}" text-anchor="middle" font-size="8" fill="{INK2}">?</text></g>')
                continue
            py = bottom - plot * v / ymax
            segment.append(f'{px:.1f},{py:.1f}')
            thin = n is None or n < THIN
            mark = (f'<circle class="thin" cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{SURFACE}" stroke="{color}" stroke-width="1.5"/>'
                    if thin else f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}"/>')
            out.append(f'<g class="metric-point"><title>{label}: {fmt.format(v)} (n={n})</title>{mark}</g>')
        for r in rows:
            start = secs(r["start"])
            local = datetime.fromtimestamp(start - 8 * 3600, timezone.utc)
            if (hour_labels and local.hour % 3 == 0) or (not hour_labels and local.hour == 0):
                text = local.strftime("%H:00" if hour_labels else "%Y-%m-%d")
                tx = 78 + 650 * (start - t0) / (t1 - t0)
                out.append(f'<text x="{tx:.1f}" y="{bottom + 25}" font-size="9" fill="{MUTED}">{text}</text>')
    out += [f'<text x="24" y="{height - 16}" font-size="11" fill="{INK2}">Fixed PST. n = code runs, merged PRs, tickets,'
            ' reviewed PRs, main verdicts, attempts or jobs in the bucket; hollow marks have n &lt; 3; ? is unknown.</text>',
            '</svg>']
    return '\n'.join(out) + '\n'


def day_buckets(p, size, hours):
    """A day's buckets, or unknown ones (start and end only) if it has none,
    so a chart's lines break there instead of joining its neighbours."""
    if "buckets" in p:
        return p["buckets"][size]
    s, u = secs(p["since"]), secs(p["until"])
    return [{"start": utc_text(t), "end": utc_text(min(t + 3600 * hours, u))} for t in range(s, u, 3600 * hours)]


def write_buckets(daily, out):
    six = [row for p in daily for row in day_buckets(p, "6h", 6)]
    one = day_buckets(daily[-1], "1h", 1) if daily else []
    last = daily[-1]["label"] if daily else "none"
    md = ["# CI benchmarks in buckets", "",
          "Every bench in 1-hour and 6-hour buckets of each full PST day (fixed PST, UTC−08:00), each value with"
          " its sample size n: code runs for the CI benches, tickets, reviewed PRs, main verdicts, attempts started"
          " in the bucket (reruns) or jobs (runner wait). Merged PRs are their own count. A bucket with n < 3 is a hollow mark on the"
          " charts, so a thin hour can't mislead; unknown is never 0. Days measured before the buckets (#1359)"
          " read unknown. Main red counts the minutes inside each bucket; its n is the verdicts finished in it.", "",
          "![Every bench in 6-hour buckets](buckets-6h.svg)", "",
          f"![Every bench in 1-hour buckets, {esc(last)}](buckets-1h.svg)", "",
          "## 6-hour buckets", ""] + BUCKET_HEAD
    for size, title in (("6h", None), ("1h", "## 1-hour buckets")):
        if title:
            md += ["", title, ""] + BUCKET_HEAD
        for p in daily:
            if "buckets" not in p:
                md.append(f'| {md_cell(esc(p["label"]))} | ' + " | ".join(["unknown"] * BUCKET_COLUMNS) + " |")
                continue
            md += [bucket_row(row) for row in p["buckets"][size]]
    write(Path(out) / "buckets.md", "\n".join(md) + "\n")
    write(Path(out) / "buckets-6h.svg", chart_buckets(six, "Every bench in 6-hour buckets",
                                                      "Full PST days; each point's sample size beneath it", False))
    write(Path(out) / "buckets-1h.svg", chart_buckets(one, f"Every bench in 1-hour buckets: {last}",
                                                      "The latest full PST day; each point's sample size beneath it", True))


# ---------------------------------------------------------------- main


# ---------------------------------------------------------------- selector escapes (#1264)

# The escape finder (ci/escapes/escapes.py) runs once for each failed attempt
# of a full CI run on main, named for that attempt, and opens one issue per
# new escape whose first line is this marker. An escape counts in the window
# its attempt started in, as reruns do (read_attempts): a run of the 30 days
# before can have its failed attempt in the window. escapes.json (local)
# keeps run, attempt, PR and test ids; point.json keeps the counts only.
ESCAPES_WORKFLOW = "ci-escapes.yml"
ESCAPES_TITLE = "Selector escapes in CI run {run} attempt {attempt}"
ESCAPE_BOT = "github-actions[bot]"
ESCAPE_MARKER = re.compile(r"<!-- openwiz\.ci-escape\.v1 run=([1-9][0-9]*) attempt=([1-9][0-9]*) pr=([1-9][0-9]*)"
                           r" test=([A-Za-z0-9_.:-]+) -->")
ESCAPES_KEYS = {"since", "until", "attempts", "failed_attempts", "escapes", "unknown"}
ESCAPE_POINT_KEYS = {"count", "attempts", "failed_attempts", "unknown"}


def escape_marker(body):
    """(run, attempt, pr, test) from an issue body's first line only: a path
    the finder quotes below it could hold the same text."""
    first = body.split("\n", 1)[0].rstrip("\r") if type(body) is str else ""
    m = ESCAPE_MARKER.fullmatch(first)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)) if m else None


def full_runs(since, until):
    """main's push and nightly CI runs created in the window or the 30 days
    before it, a day per list (one list holds at most 1,000)."""
    s, u = secs(since), secs(until)
    edges = [s - 86400 * d for d in range(RERUN_LOOKBACK_DAYS, 0, -1)] + [s, u]
    runs = {}
    for a, b in zip(edges, edges[1:]):
        path = (f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs?branch={BASE_BRANCH}"
                f"&created={utc_text(a)}..{utc_text(b)}&per_page={PAGE}")
        for run, where in pages(path, "workflow_runs", "runs"):
            as_obj(run, where)
            rid = as_int(run, "id", where)
            at = f"{where} run {rid}"
            event, branch = as_str(run, "event", at), as_str(run, "head_branch", at, null=True)
            record = {"id": rid, "status": as_str(run, "status", at), "conclusion": as_str(run, "conclusion", at, null=True),
                      "attempt": as_int(run, "run_attempt", at), "started": as_time(run, "run_started_at", at),
                      "updated": as_time(run, "updated_at", at), "created": as_time(run, "created_at", at)}
            if record["attempt"] < 1:
                raise Fail(f"{at}: run_attempt below 1")
            # The API's range includes its end; the day doesn't.
            if not (event in ("push", "schedule") and branch == BASE_BRANCH and a <= secs(record["created"]) < b):
                continue
            if rid in runs:
                raise Fail(f"{at}: listed twice")
            runs[rid] = record
    return runs


def escapes_collect(since, until, out):
    """DIR/escapes.json: each attempt of a full CI run on main that started
    in the window, the failed ones, each escape the finder reported for one
    of them, and every reason the count is unknown: an attempt still running,
    one that ended in neither success, failure nor a cancel, or a failed one
    whose finder run is missing, still running or failed."""
    if shutil.which("gh") is None:
        raise Fail("gh is not on PATH")
    s, u = secs(since), secs(until)
    unknown, started, failed = [], 0, []
    for run in sorted(full_runs(since, until).values(), key=lambda r: (secs(r["created"]), r["id"])):
        # A run of the look-back days can only have an attempt in the window
        # if it changed in it.
        if secs(run["created"]) < s and secs(run["updated"]) < s:
            continue
        for k in range(1, run["attempt"] + 1):
            status, conclusion, start = attempt_state(run, k, gh)
            if not s <= secs(start) < u:
                continue
            started += 1
            if status != "completed":
                unknown.append(f"CI run {run['id']} attempt {k} on main is still {status}")
            elif conclusion == "failure":
                failed.append([run["id"], k])
            elif conclusion not in ("success", "cancelled", "skipped"):
                # A cancel tested nothing: the next full run tests the same commits.
                unknown.append(f"CI run {run['id']} attempt {k} on main ended {conclusion}: not judged")
    found = []
    if failed:
        finders = {}
        # A finder run starts when its CI attempt ends: up to a day after the window.
        path = (f"repos/{{owner}}/{{repo}}/actions/workflows/{ESCAPES_WORKFLOW}/runs?event=workflow_run"
                f"&created={since}..{utc_text(u + 86400)}&per_page={PAGE}")
        for run, where in pages(path, "workflow_runs", "runs"):
            as_obj(run, where)
            rid = as_int(run, "id", where)
            at = f"{where} run {rid}"
            title = as_str(run, "display_title", at)
            finders.setdefault(title, []).append((rid, as_str(run, "status", at), as_str(run, "conclusion", at, null=True)))
        judged = set()
        for rid, k in failed:
            runs = finders.get(ESCAPES_TITLE.format(run=rid, attempt=k), [])
            if not runs:
                unknown.append(f"CI run {rid} attempt {k} failed, and no escape finder ran for it")
                continue
            _, status, conclusion = max(runs)
            if (status, conclusion) != ("completed", "success"):
                unknown.append(f"the escape finder for CI run {rid} attempt {k} is {status}, {conclusion}: unknown")
                continue
            judged.add((rid, k))
        if judged:
            seen = set()
            for page in range(1, API_LIMIT // PAGE + 1):
                where = f"gh api issues page {page}"
                got = as_list(gh(f"repos/{{owner}}/{{repo}}/issues?state=all&since={since}&per_page={PAGE}&page={page}"), where)
                for issue in got:
                    as_obj(issue, where)
                    user = issue.get("user")
                    key = escape_marker(issue.get("body")) if type(user) is dict and user.get("login") == ESCAPE_BOT else None
                    if key and key[:2] in judged and key not in seen:
                        seen.add(key)
                        found.append(list(key))
                if len(got) < PAGE:
                    break
            else:
                raise Fail(f"more than {API_LIMIT} issues since {since}: split the window")
    facts = {"since": since, "until": until, "attempts": started, "failed_attempts": failed,
             "escapes": sorted(found), "unknown": unknown}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / "escapes.json", json.dumps(facts, indent=2, sort_keys=True) + "\n")
    count = "unknown" if unknown else len(found)
    print(f"escapes: {count}, from {len(failed)} failed of {started} full-run attempts on main into {out}")


def read_escapes(d, since, until):
    where = f"{d}/escapes.json"
    e = as_obj(strict_json(read_file(Path(d) / "escapes.json"), where), where)
    exact(e, ESCAPES_KEYS, where)
    if (as_time(e, "since", where), as_time(e, "until", where)) != (since, until):
        raise Fail(f"{where}: its window is not window.json's")
    started = as_int(e, "attempts", where)
    failed = as_list(e["failed_attempts"], where)
    if any(not (type(f) is list and len(f) == 2 and all(type(n) is int and n > 0 for n in f)) for f in failed) \
            or len({tuple(f) for f in failed}) != len(failed) or len(failed) > started:
        raise Fail(f"{where}: failed_attempts is not a list of distinct [run, attempt]")
    for item in as_list(e["escapes"], where):
        if not (type(item) is list and len(item) == 4 and item[:2] in failed and type(item[2]) is int
                and type(item[3]) is str):
            raise Fail(f"{where}: an escape is not [failed run, attempt, pull request, test]")
    if any(type(u) is not str for u in as_list(e["unknown"], where)):
        raise Fail(f"{where}: unknown is not a list of reasons")
    return e


def escapes_point(e):
    """Counts only: unknown is never 0."""
    return {"count": None if e["unknown"] else len(e["escapes"]), "attempts": e["attempts"],
            "failed_attempts": len(e["failed_attempts"]), "unknown": len(e["unknown"])}


def validate_escapes(e, where):
    as_obj(e, where)
    exact(e, ESCAPE_POINT_KEYS, where)
    for k in ("attempts", "failed_attempts", "unknown"):
        if as_int(e, k, where) < 0:
            raise Fail(f"{where}: '{k}' is negative")
    if (e["count"] is None) != (e["unknown"] > 0) or (e["count"] is not None and (type(e["count"]) is not int or e["count"] < 0)):
        raise Fail(f"{where}: 'count' is a whole number exactly when nothing is unknown")
    if e["failed_attempts"] > e["attempts"]:
        raise Fail(f"{where}: more failed attempts than attempts")


def escapes_cell(p):
    e = p.get("escapes")
    return "unknown" if e is None or e["count"] is None else str(e["count"])


def utc(text):
    if not TIME.fullmatch(text):
        raise argparse.ArgumentTypeError(f"not a UTC time YYYY-MM-DDTHH:MM:SSZ: {text}")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a UTC time: {text}")
    return text


def robots(text):
    if not re.fullmatch(r"[1-9][0-9]{0,3}", text):
        raise argparse.ArgumentTypeError(f"not a whole number of robots from 1: {text}")
    return int(text)


def label(text):
    if not text.strip():
        raise argparse.ArgumentTypeError("the label is empty")
    return text


def main(argv):
    try:
        return dispatch(argv)
    finally:
        # Backfill may measure many days in one command. Keep reuse bounded
        # during it, and release timestamps on success, refusal or bad arguments.
        parsed_secs.cache_clear()


def dispatch(argv):
    ap = argparse.ArgumentParser(prog="bench.py", description="The CI bench: PRs an hour, measured.")
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-window", help="validate a checkpoint before reading GitHub")
    v.add_argument("--since", type=utc, required=True)
    v.add_argument("--until", type=utc, required=True)
    v.add_argument("--label", type=label, required=True)
    v.add_argument("--robots", type=robots, required=True)
    back = sub.add_parser("backfill", help="measure each full fixed-PST day, resuming validated points")
    back.add_argument("--start-day", default="2026-11-01")
    back.add_argument("--through-day")
    back.add_argument("--now", type=utc, help="clock for reproducible bounds")
    back.add_argument("--out", required=True)
    back.add_argument("--robots", type=robots, required=True)
    c = sub.add_parser("collect", help="read a window's CI jobs and merged PRs from GitHub")
    c.add_argument("--since", type=utc, required=True)
    c.add_argument("--until", type=utc, required=True)
    c.add_argument("--out", required=True)
    fc = sub.add_parser("factory", help="read a window's merged history, main's runs and reruns into DIR/factory.json")
    fc.add_argument("--since", type=utc, required=True)
    fc.add_argument("--until", type=utc, required=True)
    fc.add_argument("--out", required=True)
    es = sub.add_parser("escapes", help="read a window's failed full runs on main and their escapes into DIR/escapes.json")
    es.add_argument("--since", type=utc, required=True)
    es.add_argument("--until", type=utc, required=True)
    es.add_argument("--out", required=True)
    m = sub.add_parser("measure", help="write DIR/point.json")
    m.add_argument("dir")
    m.add_argument("--robots", type=robots, required=True)
    m.add_argument("--label", type=label, required=True)
    m.add_argument("--prices", default=str(HERE / "prices.tsv"))
    m.add_argument("--allow-timing-gaps", action="store_true", help="record unknown cost for invalid durations in unsuccessful runs")
    m.add_argument("--allow-empty", action="store_true", help="record a day with no successful code runs")
    check = sub.add_parser("check-steps", help="require coverage of every operative CI step")
    check.add_argument("--workflow", default=str(ROOT / ".github/workflows/ci.yml"))
    day = sub.add_parser("day-window", help="print last full fixed PST day as UTC bounds")
    day.add_argument("--now", type=utc)
    dash = sub.add_parser("dashboard", help="write GitHub README and five charts")
    dash.add_argument("dirs", nargs="*")
    dash.add_argument("--baseline", default=str(BASELINE))
    dash.add_argument("--out", required=True)
    k = sub.add_parser("chart", help="draw windows against the baseline")
    k.add_argument("--baseline", default=str(BASELINE))
    k.add_argument("dirs", nargs="*")
    k.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.command in ("collect", "validate-window", "factory", "escapes") and secs(args.until) <= secs(args.since):
        {"factory": fc, "escapes": es}.get(args.command, c).error("--until must be after --since")
    try:
        if args.command == "backfill":
            backfill(args.start_day, args.through_day, args.now, args.out, args.robots)
        elif args.command == "validate-window":
            return 0
        elif args.command == "collect":
            collect(args.since, args.until, args.out)
        elif args.command == "factory":
            factory_collect(args.since, args.until, args.out)
        elif args.command == "escapes":
            escapes_collect(args.since, args.until, args.out)
        elif args.command == "measure":
            measure(args.dir, args.robots, args.label, args.prices, args.allow_empty, args.allow_timing_gaps)
        elif args.command == "check-steps":
            check_steps(args.workflow)
        elif args.command == "day-window":
            print(" ".join(pst_window(args.now)))
        elif args.command == "dashboard":
            dashboard(args.baseline, args.dirs, args.out)
        else:
            chart(args.baseline, args.dirs, args.out)
    except Fail as e:
        print(f"bench: {e}", file=sys.stderr)
        if args.command in ("collect", "factory", "escapes"):
            print("bench: nothing written", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
