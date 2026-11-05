#!/usr/bin/env python3
"""Selector escapes, found and reported (#1264, X6 of spec #1256, H5).

When a full CI run on `main` (a push or the nightly run) fails, this reads
the tests that failed and the CI selection plans (contracts/ci-selection.v1.md,
#1405) of the pull requests merged since the last green full run. A failing
test that a pull request's plan skipped is an **escape**: it is reported on
one issue, labelled needs-triage, naming the pull request, the test and the
changed paths the selector's map missed a link from. A failing test that
every plan ran is an ordinary red `main`. Anything it can't read or bind
(no plan, a log that names no test, a history it can't follow) is
**unknown**, never "no escape".

    python3 -I ci/escapes/escapes.py find --run <CI run id> --attempt <k> [--summary FILE]

Exit 0: every failing test was judged (escapes reported, or none). Exit 1:
unknown (what it found is still reported). Exit 2: not a failed full run of
CI on main, or a bad command line. Every read is `gh api <path>`, a GET;
its one write is `gh api -X POST repos/{owner}/{repo}/issues`, once per new
escape. Python 3 standard library and `gh` only. See README.md here.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = ROOT / "contracts" / "ci-selection.v1.schema.json"
NAME = "openwiz.ci-selection.v1"
WORKFLOW = ".github/workflows/ci.yml"
MAIN = "main"
R = "repos/{owner}/{repo}"
PAGE = 100
MAX_PAGES = 10
BOT = "github-actions[bot]"
LABEL = "needs-triage"
MAX_ZIP = 4 << 20
MAX_PLAN = 1 << 20
MAX_PATHS = 30
# The one issue per escape starts with this line, and only its first line
# counts (a path quoted below could hold the same text): the finder's own key
# (pr, test) for "reported once", and the bench's (tools/ci-bench) count by
# the CI attempt that found it.
MARKER = "<!-- openwiz.ci-escape.v1 run={run} attempt={attempt} pr={pr} test={test} -->"
MARKER_RE = re.compile(r"^<!-- openwiz\.ci-escape\.v1 run=([1-9][0-9]*) attempt=([1-9][0-9]*) pr=([1-9][0-9]*)"
                       r" test=([A-Za-z0-9_.:-]+) -->\Z")


def marker(body):
    """(run, attempt, pr, test) from an issue body's first line, or None."""
    m = MARKER_RE.match(body.split("\n", 1)[0].rstrip("\r")) if isinstance(body, str) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)) if m else None


# The steps whose failures name their tests in the job's log, as cargo does.
# Seam for X5 (#1262): its lanes' test steps join this set when they log the
# same way; every other failed step stays unknown.
TEST_STEPS = {"Run cargo test --workspace"}
TEST_NAME = re.compile(r"[A-Za-z0-9_.:-]+")


class Fail(Exception):
    """A read failed, or an answer can't be trusted."""


class NotFullRun(Exception):
    """The run is not a failed full run of CI on main."""


# ---------------------------------------------------------------- the plan


def strict_json(text):
    """JSON with each key once (rule 1) and no NaN or Infinity."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"the key {k!r} is repeated")
            out[k] = v
        return out

    def constant(word):
        raise ValueError(f"{word} is not JSON")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def schema():
    return strict_json(SCHEMA.read_text())


KEYWORDS = {"$ref", "oneOf", "const", "enum", "type", "required", "additionalProperties", "properties", "items",
            "minItems", "uniqueItems", "pattern", "minLength", "maxLength", "minimum"}
ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs"}
TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def resolve(root, ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise Fail(f"an unsupported $ref {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise Fail(f"a $ref that resolves to nothing: {ref}")
        node = node[part]
    return node


def regex(pattern):
    """A schema pattern, anchored as JSON Schema means it: `$` is the very
    end, never before a final newline as in Python."""
    if not (pattern.startswith("^") and pattern.endswith("$")) or "$" in pattern[:-1]:
        raise Fail(f"a pattern this reader can't anchor: {pattern}")
    return re.compile(pattern[:-1] + r"\Z")


def lint(s):
    """Every keyword the reader doesn't understand, or can't apply as written."""
    errors = []

    def walk(node, at):
        if not isinstance(node, dict):
            errors.append(f"{at}: not a schema object")
            return
        for k in node:
            if k not in KEYWORDS | ANNOTATIONS:
                errors.append(f"{at}: unknown keyword {k}")
        if "type" in node and node["type"] not in TYPES:
            errors.append(f"{at}: an unknown type {node['type']!r}")
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            errors.append(f"{at}: additionalProperties other than false")
        if "uniqueItems" in node and node["uniqueItems"] is not True:
            errors.append(f"{at}: uniqueItems other than true")
        for k in ("$ref", "pattern"):
            if k in node:
                try:
                    resolve(s, node[k]) if k == "$ref" else regex(node[k])
                except (Fail, re.error, AttributeError) as e:
                    errors.append(f"{at}: {e}")
        for k in ("properties", "$defs"):
            for name, sub in node.get(k, {}).items():
                walk(sub, f"{at}/{k}/{name}")
        for i, sub in enumerate(node.get("oneOf", [])):
            walk(sub, f"{at}/oneOf/{i}")
        if "items" in node:
            walk(node["items"], f"{at}/items")

    walk(s, "#")
    return errors


def canon(v):
    return json.dumps(v, sort_keys=True)


def is_type(v, t):
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "integer": type(v) is int, "number": type(v) in (int, float), "boolean": type(v) is bool,
            "null": v is None}[t]


def check(root, node, v, at, out):
    if "$ref" in node:
        check(root, resolve(root, node["$ref"]), v, at, out)
    if "oneOf" in node:
        passed = sum(1 for b in node["oneOf"] if not errors_of(root, b, v, at))
        if passed != 1:
            out.append(f"{at}: matches {passed} of its {len(node['oneOf'])} forms, not exactly one")
    if "const" in node and canon(v) != canon(node["const"]):
        out.append(f"{at}: expected {canon(node['const'])}")
    if "enum" in node and canon(v) not in {canon(e) for e in node["enum"]}:
        out.append(f"{at}: not one of {canon(node['enum'])}")
    if "type" in node and not is_type(v, node["type"]):
        out.append(f"{at}: not of type {node['type']}")
        return
    if isinstance(v, dict):
        for k in node.get("required", []):
            if k not in v:
                out.append(f"{at}: no {k}")
        props = node.get("properties", {})
        for k, sub in v.items():
            if k in props:
                check(root, props[k], sub, f"{at}.{k}", out)
            elif node.get("additionalProperties") is False:
                out.append(f"{at}: a field it doesn't have: {k}")
    if isinstance(v, list):
        if len(v) < node.get("minItems", 0):
            out.append(f"{at}: fewer than {node['minItems']} items")
        if node.get("uniqueItems") and len({canon(i) for i in v}) != len(v):
            out.append(f"{at}: an item given twice")
        if "items" in node:
            for i, item in enumerate(v):
                check(root, node["items"], item, f"{at}[{i}]", out)
    if isinstance(v, str):
        if "pattern" in node and not regex(node["pattern"]).search(v):
            out.append(f"{at}: does not match {node['pattern']}")
        if len(v) < node.get("minLength", 0):
            out.append(f"{at}: shorter than {node['minLength']}")
        if "maxLength" in node and len(v) > node["maxLength"]:
            out.append(f"{at}: longer than {node['maxLength']}")
    if type(v) in (int, float) and "minimum" in node and v < node["minimum"]:
        out.append(f"{at}: below {node['minimum']}")


def errors_of(root, node, v, at):
    out = []
    check(root, node, v, at, out)
    return out


def schema_errors(plan):
    """The schema's refusals. A plan refused at the top is checked again
    against the one form its selection.mode names, so the error names the
    field, as tests/checks/ci_selection.rs does."""
    s = schema()
    errors = errors_of(s, s, plan, "$")
    mode = plan.get("selection", {}).get("mode") if isinstance(plan, dict) and isinstance(plan.get("selection"), dict) else None
    if errors and mode in ("full", "selected"):
        errors = errors_of(s, s["$defs"][mode], plan, "$") or errors
    return errors


def rules(plan):
    """The contract's rules 2 to 9, on a plan the schema accepts."""
    out = []
    run = plan["run"]
    event, attempt, base_branch = run["event"], run["attempt"], run["base_branch"]
    if plan["store"]["artifact"] != f"ci-selection-{attempt}":
        out.append(f"rule 2: {plan['store']['artifact']} is not ci-selection-{attempt}")
    pr_run = event == "pull_request"
    if pr_run != (type(run["pull_request"]) is int):
        out.append(f"rule 3: run.pull_request is {canon(run['pull_request'])} on a {event} run")
    if pr_run != isinstance(run["action"], str):
        out.append(f"rule 3: run.action is {canon(run['action'])} on a {event} run")
    if pr_run and run["base"] is None:
        out.append("rule 3: run.base is null on a pull_request run")
    if isinstance(run["base"], str) and set(run["base"]) == {"0"}:
        out.append("rule 3: run.base is all zeros")
    if base_branch != MAIN and not base_branch.startswith("release-"):
        out.append(f"rule 3: run.base_branch {base_branch} is neither main nor release-*")
    reasons = plan["selection"].get("reasons", [])
    codes = [r["code"] for r in reasons]
    happened = {"push_main": event == "push", "nightly": event == "schedule", "merge_group": event == "merge_group",
                "rerun": attempt > 1, "ready_for_review": run["action"] == "ready_for_review",
                "release_branch": base_branch.startswith("release-")}
    for code, yes in happened.items():
        if (code in codes) != yes:
            out.append(f"rule 4: {code} exactly when it happened")
    if event == "push" and base_branch != MAIN:
        out.append(f"rule 4: a push into {base_branch}, not main")
    diff = plan["diff"]["state"]
    no_diff = {"push_main", "nightly", "merge_group", "rerun", "release_branch", "ready_for_review", "stale_event"}
    if diff == "not_read" and not no_diff & set(codes):
        out.append("rule 5: a not_read diff with no reason that needs no diff")
    for code, state in (("empty_diff", "empty"), ("failed_diff", "failed")):
        if (code in codes) != (diff == state):
            out.append(f"rule 5: {code} exactly when diff.state is {state}")
    changed = set(plan["diff"].get("paths", []))
    for r in reasons:
        if "paths" in r:
            if diff != "read":
                out.append(f"rule 5: {r['code']} with a diff that is {diff}, not read")
            for p in r["paths"]:
                if p not in changed:
                    out.append(f"rule 5: {r['code']} names {p}, not in diff.paths")
    if len(set(codes)) != len(codes):
        out.append("rule 9: a reason code given twice")
    lanes = plan["lanes"]
    each = [("always", lanes["always"], ["always:"]), ("rust", lanes["rust"], ["rust:lib:", "rust:test:"]),
            ("web", lanes["web"], ["web:unit:", "web:browser:"]), ("site", lanes["site"], ["site:", "release:"])]
    skills = set()
    for lane in lanes["skills"]:
        if lane["skill"] in skills:
            out.append(f"rule 8: the skill {lane['skill']} has two lanes")
        skills.add(lane["skill"])
        each.append(("skills", lane, [f"skill:{lane['skill']}:", f"skill:{lane['skill']}"]))
    seen = set()
    for name, lane, forms in each:
        ids = list(lane.get("tests", [])) + [s["test"] for s in lane.get("skipped", [])]
        for i in ids:
            if i in seen:
                out.append(f"rule 6: {i} is in the plan twice")
            seen.add(i)
            fits = any(len(i) > len(f) and i.startswith(f) if f.endswith(":") else i == f for f in forms)
            if not fits:
                out.append(f"rule 7: {i} is not a test of the {name} lane")
    return out


def refusals(text):
    """Every refusal of a plan's text; empty means the contract accepts it."""
    try:
        plan = strict_json(text)
    except (ValueError, RecursionError) as e:
        return [f"rule 1: {e}" if "repeated" in str(e) else f"schema: not JSON ({e})"]
    errors = [f"schema: {e}" for e in schema_errors(plan)]
    return errors or rules(plan)


# ---------------------------------------------------------------- finding a plan


def lookup(pr, head, runs, fetch):
    """The contract's "Reading a merged pull request's plan": the plan that
    holds for pull request `pr` at head `head`, as {"run", "attempt",
    "plan"}, or why it is unknown (a string). `runs` are the CI runs, each
    {"id", "workflow", "event", "head_sha", "pull_requests": [numbers] or
    None when unreadable, "attempt": its last}; fetch(run, artifact) is the
    artifact's ci-selection.json text, or None when it has none."""
    same = [r for r in runs if r["workflow"] == WORKFLOW and r["event"] == "pull_request" and r["head_sha"] == head]
    if any(r["pull_requests"] is None for r in same):
        return "a CI run at its head has no readable pull request association"
    mine = [r for r in same if pr in r["pull_requests"]]
    if not mine:
        return "no CI run of it at its head"
    run = max(mine, key=lambda r: r["id"])
    attempt = run["attempt"]
    if not attempt:
        return f"CI run {run['id']} has no attempt"
    artifact = f"ci-selection-{attempt}"
    text = fetch(run, artifact)
    if text is None:
        return f"CI run {run['id']} attempt {attempt} kept no {artifact}"
    bad = refusals(text)
    if bad:
        return f"CI run {run['id']}'s plan is refused ({bad[0]})"
    plan = strict_json(text)
    bound = [(plan["run"]["pull_request"], pr), (plan["run"]["head"], head), (plan["run"]["id"], run["id"]),
             (plan["run"]["attempt"], attempt), (plan["store"]["artifact"], artifact)]
    if any(canon(got) != canon(want) for got, want in bound):
        return f"CI run {run['id']}'s {artifact} holds another run's plan"
    return {"run": run["id"], "attempt": attempt, "plan": plan}


def read_case(case, folder):
    """lookup() on one of the contract's read cases (ci/selection/reads/)."""
    runs = []
    for r in case["runs"]:
        last = max(r["attempts"], key=lambda a: a["attempt"]) if r.get("attempts") else None
        prs = r.get("pull_requests")
        runs.append({"id": r["id"], "workflow": r["workflow"], "event": r["event"], "head_sha": r["head_sha"],
                     "pull_requests": prs if isinstance(prs, list) else None,
                     "attempt": last["attempt"] if last else None, "artifacts": last["artifacts"] if last else {}})

    def fetch(run, artifact):
        rel = run["artifacts"].get(artifact)
        return None if rel is None else (Path(folder) / rel).read_text()

    got = lookup(case["pull_request"], case["head"], runs, fetch)
    return "unknown" if isinstance(got, str) else {"run": got["run"], "attempt": got["attempt"]}


def verdict(plan, test):
    """("ran", None), ("skipped", its reason) or ("unknown", why), for one
    test id in one plan."""
    if plan["selection"]["mode"] == "full":
        return "ran", None
    kind, _, rest = test.partition(":")
    lanes = plan["lanes"]
    if kind == "skill":
        skill = rest.split(":", 1)[0]
        found = [lane for lane in lanes["skills"] if lane["skill"] == skill]
        if not found:
            return "unknown", f"the plan has no lane for the skill {skill}"
        lane = found[0]
    else:
        key = {"always": "always", "rust": "rust", "web": "web", "site": "site", "release": "site"}.get(kind)
        if key is None:
            return "unknown", f"no lane holds {test}"
        lane = lanes[key]
    if lane["decision"] == "skip":
        return "skipped", lane["reason"]
    skipped = {s["test"]: s["reason"] for s in lane["skipped"]}
    whole = f"skill:{rest.split(':', 1)[0]}" if kind == "skill" else None
    if test in lane["tests"] or whole in lane["tests"]:
        return "ran", None
    if test in skipped:
        return "skipped", skipped[test]
    if whole in skipped:
        return "skipped", skipped[whole]
    return "unknown", f"the plan names no {test}"


# ---------------------------------------------------------------- reading a log


STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ")
COLOUR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RERUN = re.compile(r"^error: \w+ failed, to rerun pass `([^`]*)`$")
MANY = re.compile(r"^error: \d+ targets failed:$")
LISTED = re.compile(r"^\s+`([^`]*)`$")
# Only the wrapper can authenticate structure. Its fresh 256-bit nonce is
# never passed to invocations. Public rust-tests labels and GitHub groups
# inside their output are just payload; no payload-derived cutoff is used.
FRAME_WORD = "rust-tests-frame:"
FRAME = re.compile(r"^rust-tests-frame:([0-9a-f]{64}) (.*)$")
BESIDE = re.compile(r"^rust-tests: (.+), beside the Rust tests: ")
MODE = re.compile(r"^rust-tests: (one command, cargo test --workspace|every target at once): ")
HEADER = re.compile(r"^== rust-tests: (.+)$")
EXITED = re.compile(r"^rust-tests: cargo test --workspace exited ([0-9]+) after [0-9]+ s$")
UNREAD = re.compile(r"^rust-tests: (.+): its log can't be read$")
STATUS = re.compile(r"^rust-tests: (.+): (ok|FAILED \(exit [^)]*\))$")
TOOK = re.compile(r"^rust-tests: (.+) took ([0-9]+|\?) s$")
END = re.compile(r"^rust-tests: peak memory ")
ONE = "cargo test --workspace"
FAST = "every target at once"


class Shape(Exception):
    """ci/rust-tests.sh's output, not in the shape the script prints."""


def framed_region(lines):
    """One complete wrapper run. Reject foreign, malformed, duplicate or
    truncated frames anywhere in the job, including after an alleged end.
    Legacy logs without private framing are unknown, never parsed loosely."""
    frames = []
    for i, line in enumerate(lines):
        if FRAME_WORD not in line:
            continue
        m = FRAME.fullmatch(line)
        if not m:
            raise Shape(line)
        frames.append((m.group(1), m.group(2), i))
    if not frames:
        raise Shape("no authenticated run")
    nonce = frames[0][0]
    if any(f[0] != nonce for f in frames):
        raise Shape("foreign nonce")
    if frames[0][1] != "begin" or frames[-1][1] != "end":
        raise Shape("missing begin/end frame")
    if sum(f[1] == "begin" for f in frames) != 1 or sum(f[1] == "end" for f in frames) != 1:
        raise Shape("duplicate begin/end frame")
    return lines[frames[0][2] + 1:frames[-1][2]], nonce


def tokens(region, nonce):
    """Only authenticated wrapper lines supply structure and exit status."""
    out = []
    prefix = f"{FRAME_WORD}{nonce} "
    for i, line in enumerate(region):
        if not line.startswith(prefix):
            continue
        control = line[len(prefix):]
        for kind, pattern in (("header", HEADER), ("beside", BESIDE), ("mode", MODE), ("exited", EXITED),
                              ("unread", UNREAD), ("status", STATUS), ("took", TOOK), ("end", END)):
            m = pattern.match(control)
            if m:
                out.append((kind, m.group(1) if m.groups() else None, i,
                            m.group(2) if kind == "status" else None))
                break
        else:
            raise Shape(control)
    return out


def grammar(toks, region):
    """ci/rust-tests.sh's run, read in the order the script prints it:
        [beside A] mode
        one command:    == cargo test --workspace, its output, exited N
        every target:   (== N, [N: its log can't be read], its output)...,
                        N: ok|FAILED for each N in the same order, took
                        (or none of these, when the build before them failed)
        [== A, [A: its log can't be read], its output, A took S s, A: ok|FAILED]
        peak memory
    Returns ({name: (failed, output lines)}, the suite beside: (name, failed)
    or None, the sections whose log can't be read); raises Shape otherwise."""
    pos = 0

    def peek(kind=None, name=None):
        t = toks[pos] if pos < len(toks) else None
        return t if t and (kind is None or t[0] == kind) and (name is None or t[1] == name) else None

    def take(kind, name=None):
        nonlocal pos
        t = peek(kind, name)
        if t is None:
            raise Shape(region[toks[pos][2]] if pos < len(toks) else "its end")
        pos += 1
        return t

    def unread(name):
        return [take("unread", name)[1]] if peek("unread", name) else []

    along = take("beside")[1] if peek("beside") else None
    mode, sections, cannot = take("mode")[1], {}, []
    if mode.startswith("one command"):
        head, exited = take("header", ONE), take("exited")
        sections[ONE] = (exited[1] != "0", region[head[2] + 1:exited[2]])
    else:
        heads = []
        while peek("header") and peek("header")[1] != along:
            head = take("header")
            if head[1] in [h[1] for h in heads]:
                raise Shape(region[head[2]])
            cannot += unread(head[1])
            heads.append(head)
        if heads:
            states = [take("status", h[1]) for h in heads]
            take("took", FAST)
            for i, head in enumerate(heads):
                stop = heads[i + 1][2] if i + 1 < len(heads) else states[0][2]
                sections[head[1]] = (states[i][3] != "ok", region[head[2] + 1:stop])
    beside = None
    if along is not None:
        take("header", along)
        cannot += unread(along)
        take("took", along)
        beside = (along, take("status", along)[3] != "ok")
    take("end")
    if pos != len(toks):
        raise Shape(region[toks[pos][2]])
    return sections, beside, cannot


def hints(lines):
    """cargo's rerun hints in one invocation's output: `-p X --test Y` and
    the like, each one, and each of a no-fail-fast list."""
    out, listing = [], False
    for line in lines:
        if listing and LISTED.match(line):
            out.append(LISTED.match(line).group(1))
            continue
        listing = bool(MANY.match(line))
        if RERUN.match(line):
            out.append(RERUN.match(line).group(1))
    return out


def failing_tests(text):
    """Test ids from failed, authenticated Cargo invocations, plus unknowns.
    Only a complete wrapper frame supplies sections and statuses. Plain
    labels, hints in passing invocations, and GitHub group markers cannot
    supply structure. A failed section's hints must name its own target;
    the alongside suite never names Rust tests."""
    lines = [COLOUR.sub("", STAMP.sub("", raw.rstrip("\r"))) for raw in text.splitlines()]
    try:
        region, nonce = framed_region(lines)
        sections, beside, cannot = grammar(tokens(region, nonce), region)
    except Shape as e:
        return set(), [f"ci/rust-tests.sh's output is not in its own shape at: {str(e)[:160]}"]
    unknown = [f"rust-tests: {name}: its log can't be read" for name in cannot]
    if beside and beside[1]:
        unknown.append(f"rust-tests: {beside[0]}: failed, with no test named")
    ids = set()
    for name, (failed, output) in sections.items():
        if not failed:
            continue
        found = hints(output)
        if not found:
            unknown.append(f"rust-tests: {name}: failed, with no test named")
        for a in found:
            m = re.fullmatch(r"-p (\S+) --lib", a) or re.fullmatch(r"-p (\S+) --test (\S+)", a)
            if not m or not all(TEST_NAME.fullmatch(n) for n in m.groups()):
                unknown.append(f"rust-tests: {name}: a failure it can't name: {a}")
            elif name == ONE or (name == "crates" and len(m.groups()) == 1) or \
                    (len(m.groups()) == 2 and m.groups() == ("openwiz-tests", name)):
                ids.add(f"rust:lib:{m.group(1)}" if len(m.groups()) == 1 else f"rust:test:{m.group(2)}")
            else:
                unknown.append(f"rust-tests: {name}: a hint that isn't its own: {a}")
    if not ids and not unknown:
        unknown.append("the log names no failing test")
    return ids, list(dict.fromkeys(unknown))


# ---------------------------------------------------------------- GitHub


class GitHub:
    """`gh api` reads, each made once; and the one write."""

    def __init__(self):
        self.cache = {}

    def call(self, args, stdin=None):
        r = subprocess.run(["gh", *args], input=stdin, capture_output=True)
        if r.returncode != 0:
            first = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[0]
            raise Fail(f"gh {' '.join(args)} failed (exit {r.returncode}): {first}")
        return r.stdout

    def raw(self, args):
        key = " ".join(args)
        if key not in self.cache:
            self.cache[key] = self.call(args)
        return self.cache[key]

    def get(self, path):
        try:
            return strict_json(self.raw(["api", path]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise Fail(f"gh api {path}: not JSON ({e})")

    def log(self, job):
        return self.raw(["api", "--allow-escape-sequences", f"{R}/actions/jobs/{job}/logs"]).decode("utf-8", "replace")

    def post_issue(self, issue):
        out = self.call(["api", "-X", "POST", f"{R}/issues", "--input", "-"], json.dumps(issue).encode())
        try:
            number = strict_json(out.decode("utf-8")).get("number")
        except (ValueError, UnicodeDecodeError, AttributeError):
            number = None
        if type(number) is not int:
            raise Fail("the new issue's answer has no number")
        return number


def need(obj, key, kind, where):
    if not isinstance(obj, dict) or key not in obj:
        raise Fail(f"{where}: no {key}")
    v = obj[key]
    ok = {"int": type(v) is int, "str": isinstance(v, str), "list": isinstance(v, list), "dict": isinstance(v, dict),
          "str?": v is None or isinstance(v, str)}[kind]
    if not ok:
        raise Fail(f"{where}: {key} is not {kind}")
    return v


def counted(gh, path, key, stop=None):
    """A list whose pages say their total_count, page by page; stop(items)
    may end it early."""
    items, total = [], None
    for page in range(1, MAX_PAGES + 1):
        where = f"{path}&page={page}"
        ans = gh.get(where)
        count, got = need(ans, "total_count", "int", where), need(ans, key, "list", where)
        if total is None:
            total = count
        elif count != total:
            raise Fail(f"{where}: total_count changed between pages")
        if not got and len(items) < total:
            raise Fail(f"{where}: {len(items)} of {total} {key}")
        items += got
        if len(items) >= total or (stop and stop(items)):
            return items
    raise Fail(f"{path}: more than {MAX_PAGES} pages")


def runs_at(gh, head):
    """Every CI pull_request run at a head, as lookup() reads them."""
    out = []
    for r in counted(gh, f"{R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={head}&per_page={PAGE}",
                     "workflow_runs"):
        where = f"CI run {r.get('id') if isinstance(r, dict) else '?'}"
        prs = r.get("pull_requests") if isinstance(r, dict) else None
        numbers = None
        if isinstance(prs, list) and all(isinstance(p, dict) and type(p.get("number")) is int for p in prs):
            numbers = [p["number"] for p in prs]
        out.append({"id": need(r, "id", "int", where), "workflow": need(r, "path", "str", where),
                    "event": need(r, "event", "str", where), "head_sha": need(r, "head_sha", "str", where),
                    "pull_requests": numbers, "attempt": need(r, "run_attempt", "int", where)})
    return out


def fetch_plan(gh, run, artifact):
    """A run's ci-selection.json from its artifact, or None when it has none."""
    path = f"{R}/actions/runs/{run['id']}/artifacts?name={artifact}&per_page={PAGE}"
    found = [a for a in counted(gh, path, "artifacts") if isinstance(a, dict) and a.get("name") == artifact]
    if not found:
        return None
    if len(found) > 1:
        raise Fail(f"CI run {run['id']} has {len(found)} artifacts named {artifact}")
    a = found[0]
    if a.get("expired") is not False:
        raise Fail(f"CI run {run['id']}'s {artifact} has expired")
    size = need(a, "size_in_bytes", "int", artifact)
    if size > MAX_ZIP:
        raise Fail(f"CI run {run['id']}'s {artifact} is {size} bytes")
    data = gh.raw(["api", f"{R}/actions/artifacts/{need(a, 'id', 'int', artifact)}/zip"])
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("ci-selection.json")
            if info.file_size > MAX_PLAN:
                raise Fail(f"{artifact}'s ci-selection.json is {info.file_size} bytes")
            return z.read(info).decode("utf-8")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
        raise Fail(f"CI run {run['id']}'s {artifact}: {e}")


# ---------------------------------------------------------------- the finder


def code(text):
    """Inline code that no text can break out of, so a path or a reason
    never becomes a mention, a link or markup."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(2, longest + 1)
    return f"{fence} {text} {fence}"


def link(text, path):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) and re.fullmatch(r"https://[A-Za-z0-9.-]+", server):
        return f"[{text}]({server}/{repo}/{path})"
    return f"{text} ({path})"


def issue_for(run, e):
    paths = e["plan"]["diff"]["paths"]
    shown = [f"- {code(p)}" for p in paths[:MAX_PATHS]]
    if len(paths) > MAX_PATHS:
        shown.append(f"- and {len(paths) - MAX_PATHS} more, in the plan")
    body = "\n".join([
        MARKER.format(run=run["id"], attempt=run["run_attempt"], pr=e["pr"], test=e["test"]),
        "A test that a pull request's CI plan skipped failed on a full run of CI on `main`: a **selector escape**"
        " (spec #1256, H5).",
        "",
        f"- **Test:** {code(e['test'])}",
        f"- **Pull request:** #{e['pr']}, merged as {e['merge']}",
        f"- **Its plan:** {link('CI run ' + str(e['run']), 'actions/runs/' + str(e['run']))}, attempt {e['attempt']},"
        f" skipped it: {code(e['reason'])}",
        f"- **Failed in:** {link('CI run ' + str(run['id']), 'actions/runs/' + str(run['id']))}"
        f" ({run['event']}, `main` at {run['head_sha']})",
        "",
        "The selector's map missed a link from one of the pull request's changed paths to this test:",
        "",
        *shown,
        "",
        "Fix the selector: add the missing link to its map, with a fixture for it. Found by `ci/escapes/escapes.py`.",
    ])
    return {"title": f"Selector escape: {e['test']}, skipped by #{e['pr']}", "body": body, "labels": [LABEL]}


def failed_run(gh, rid, attempt):
    """The failed attempt itself, never the run's later state: a rerun may
    have started since."""
    where = f"CI run {rid} attempt {attempt}"
    run = gh.get(f"{R}/actions/runs/{rid}/attempts/{attempt}")
    fields = {k: need(run, k, t, where) for k, t in (("id", "int"), ("path", "str"), ("event", "str"),
                                                     ("head_branch", "str?"), ("head_sha", "str"), ("status", "str"),
                                                     ("conclusion", "str?"), ("run_attempt", "int"),
                                                     ("created_at", "str"), ("run_started_at", "str"))}
    if not (fields["id"] == rid and fields["run_attempt"] == attempt and fields["path"] == WORKFLOW and fields["event"] in ("push", "schedule")
            and fields["head_branch"] == MAIN and fields["status"] == "completed" and fields["conclusion"] == "failure"):
        raise NotFullRun(f"CI run {rid} attempt {attempt} is not a failed full run of CI on main ({fields['path']}, {fields['event']},"
                         f" {fields['head_branch']}, {fields['status']}, {fields['conclusion']})")
    return fields


def failures(gh, run, unknown):
    """The failing tests of the run's last attempt; each failure it can't
    name goes to `unknown`."""
    jobs = counted(gh, f"{R}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page={PAGE}", "jobs")
    ids, failed = set(), 0
    for job in jobs:
        name = need(job, "name", "str", "a job")
        conclusion = need(job, "conclusion", "str?", name)
        if conclusion in ("success", "skipped", "neutral"):
            continue
        failed += 1
        if conclusion != "failure":
            unknown.append(f"{name}: {conclusion}")
            continue
        steps = [s for s in need(job, "steps", "list", name) if isinstance(s, dict) and s.get("conclusion") == "failure"]
        if not steps:
            unknown.append(f"{name}: failed with no failed step")
        for s in steps:
            if s.get("name") not in TEST_STEPS:
                unknown.append(f"{name}: {s.get('name')} failed, and names no test this finder can read")
        if any(s.get("name") in TEST_STEPS for s in steps):
            try:
                text = gh.log(need(job, "id", "int", name))
            except Fail:
                unknown.append(f"{name}: its log can't be read")
                continue
            found, doubts = failing_tests(text)
            ids |= found
            unknown += [f"{name}: {d}" for d in doubts]
    if not failed:
        unknown.append("the run failed, but none of its jobs did")
    return ids


def when(text, where):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        raise Fail(f"{where}: not a UTC time: {text!r}")


def ended(gh, rid, k):
    """When an attempt ended: its last job's completion."""
    where = f"CI run {rid} attempt {k}"
    jobs = counted(gh, f"{R}/actions/runs/{rid}/attempts/{k}/jobs?per_page={PAGE}", "jobs")
    try:
        return max(when(j.get("completed_at") if isinstance(j, dict) else None, where) for j in jobs)
    except (Fail, ValueError):
        raise Fail(f"{where}: when it ended can't be read")


def last_green(gh, run):
    """The newest green full run of CI on main, by creation, whose green
    attempt ended before this failed attempt started: an attempt that went
    green later proves nothing about it. Each run's attempts are read newest
    first (this run's own, only those before it); the answer is the run and
    that attempt, or unknown."""
    cutoff = when(run["run_started_at"], "the failed attempt's start")
    seen, total = 0, None
    for page in range(1, MAX_PAGES + 1):
        where = f"{R}/actions/workflows/ci.yml/runs?branch=main&per_page={PAGE}&page={page}"
        ans = gh.get(where)
        count, got = need(ans, "total_count", "int", where), need(ans, "workflow_runs", "list", where)
        total = count if total is None else total
        for r in got:
            if not (isinstance(r, dict) and r.get("path") == WORKFLOW and r.get("event") in ("push", "schedule")
                    and r.get("head_branch") == MAIN):
                continue
            rid = need(r, "id", "int", where)
            if when(need(r, "created_at", "str", where), where) >= cutoff:
                continue
            latest = need(r, "run_attempt", "int", where)
            for k in range(run["run_attempt"] - 1 if rid == run["id"] else latest, 0, -1):
                if k == latest:
                    state = (r.get("status"), r.get("conclusion"))
                else:
                    a = gh.get(f"{R}/actions/runs/{rid}/attempts/{k}")
                    if need(a, "id", "int", "an attempt") != rid or need(a, "run_attempt", "int", "an attempt") != k:
                        raise Fail(f"CI run {rid} attempt {k} read as another run or attempt")
                    state = (a.get("status"), a.get("conclusion"))
                if state == ("completed", "success") and ended(gh, rid, k) < cutoff:
                    return {"id": rid, "attempt": k, "head_sha": need(r, "head_sha", "str", where),
                            "created_at": need(r, "created_at", "str", where)}
        seen += len(got)
        if seen >= total or not got:
            break
    raise Fail(f"no green full run of CI on main ended before CI run {run['id']} attempt {run['run_attempt']} started")


def merged_since(gh, green, run):
    """The pull requests merged into main from the green run's head to the
    failing run's, oldest first: [(number, head, merge commit)]."""
    base, head = green["head_sha"], run["head_sha"]
    commits, total = {}, None
    for page in range(1, MAX_PAGES + 1):
        where = f"{R}/compare/{base}...{head}?per_page={PAGE}&page={page}"
        ans = gh.get(where)
        status = need(ans, "status", "str", where)
        if status != "ahead":
            raise Fail(f"main at {head} is not ahead of the last green full run's {base} ({status})")
        count, got = need(ans, "total_commits", "int", where), need(ans, "commits", "list", where)
        if total is None:
            total = count
        elif count != total:
            raise Fail(f"{where}: total_commits changed between pages")
        for c in got:
            commits[need(c, "sha", "str", where)] = [need(p, "sha", "str", where) for p in need(c, "parents", "list", where)]
        if len(commits) >= total or not got:
            break
    if len(commits) != total:
        raise Fail(f"the compare lists {len(commits)} of its {total} commits")
    chain, at = [], head
    while at != base:
        if at not in commits or not commits[at] or len(chain) > len(commits):
            raise Fail(f"main's first-parent history from {head} doesn't reach {base}")
        chain.append(at)
        at = commits[at][0]
    prs = []
    for merge in reversed(chain):
        pulls = gh.get(f"{R}/commits/{merge}/pulls?per_page={PAGE}")
        if not isinstance(pulls, list):
            raise Fail(f"{merge}: its pull requests are not a list")
        mine = [p for p in pulls if isinstance(p, dict) and p.get("merged_at") and p.get("merge_commit_sha") == merge
                and isinstance(p.get("base"), dict) and p["base"].get("ref") == MAIN]
        if len(mine) != 1:
            raise Fail(f"{merge}: no merged pull request" if not mine else f"{merge}: {len(mine)} merged pull requests")
        p = mine[0]
        prs.append((need(p, "number", "int", merge), need(need(p, "head", "dict", merge), "sha", "str", merge), merge))
    return prs


def find(gh, rid, attempt):
    """(result, summary lines): result is "escapes (n)", "none" or "unknown"."""
    run = failed_run(gh, rid, attempt)
    unknown, lines, escapes = [], [], []
    try:
        ids = failures(gh, run, unknown)
    except Fail as e:
        ids = set()
        unknown.append(str(e))
    lines.append(f"- Failed: CI run {run['id']} ({run['event']}, `main` at {run['head_sha']}, attempt {run['run_attempt']}).")
    lines.append("- Failing tests: " + (", ".join(code(t) for t in sorted(ids)) if ids else "none named"))
    prs, plans, green, history = [], {}, None, False
    if ids:
        try:
            green = last_green(gh, run)
            lines.append(f"- The last green full run: CI run {green['id']} attempt {green['attempt']},"
                         f" at {green['head_sha']}, ended before this attempt started.")
            if green["head_sha"] == run["head_sha"]:
                lines.append("- no pull request merged since the last green full run: the same commit.")
            else:
                prs = merged_since(gh, green, run)
                lines.append("- Pull requests merged since: " + ", ".join(f"#{n}" for n, _, _ in prs) + ".")
            history = True
        except Fail as e:
            unknown.append(str(e))
        for number, head, _ in prs:
            try:
                got = lookup(number, head, runs_at(gh, head), lambda r, a: fetch_plan(gh, r, a))
            except Fail as e:
                got = str(e)
            plans[number] = got
            if isinstance(got, str):
                unknown.append(f"#{number}: no readable plan ({got})")
    if history:
        for test in sorted(ids):
            skipped_by, doubts = [], []
            for number, head, merge in prs:
                got = plans.get(number)
                if isinstance(got, str) or got is None:
                    doubts.append(f"#{number}")
                    continue
                kind, why = verdict(got["plan"], test)
                if kind == "skipped":
                    skipped_by.append(number)
                    escapes.append({"test": test, "pr": number, "reason": why, "plan": got["plan"], "run": got["run"],
                                    "attempt": got["attempt"], "merge": merge})
                elif kind == "unknown":
                    doubts.append(f"#{number}")
                    unknown.append(f"{test} in #{number}'s plan: {why}")
            if skipped_by:
                lines.append(f"- {code(test)}: an escape, skipped by " + ", ".join(f"#{n}" for n in skipped_by) + ".")
            elif doubts:
                lines.append(f"- {code(test)}: unknown: no readable answer from " + ", ".join(doubts) + ".")
            else:
                lines.append(f"- {test}: ran in every plan: not an escape.")
    if escapes:
        try:
            report(gh, run, green, escapes, lines)
        except Fail as e:
            unknown.append(f"reporting the escapes: {e}")
    lines += [f"- Unknown: {u}" for u in dict.fromkeys(unknown)]
    if unknown:
        return "unknown", lines
    return (f"escapes ({len(escapes)})" if escapes else "none"), lines


def report(gh, run, green, escapes, lines):
    """One issue per escape, once: an issue the finder opened for the same
    pull request and test stands."""
    reported = {}
    for page in range(1, 2 * MAX_PAGES + 1):
        got = gh.get(f"{R}/issues?state=all&since={green['created_at']}&per_page={PAGE}&page={page}")
        if not isinstance(got, list):
            raise Fail("the issues are not a list")
        for issue in got:
            user = issue.get("user") if isinstance(issue, dict) else None
            found = marker(issue.get("body")) if isinstance(user, dict) and user.get("login") == BOT else None
            if found:
                reported.setdefault(found[2:], issue.get("number"))
        if len(got) < PAGE:
            break
    else:
        raise Fail("more issues since the last green full run than it reads")
    for e in escapes:
        key = (e["pr"], e["test"])
        if key in reported:
            lines.append(f"- {code(e['test'])} skipped by #{e['pr']}: already reported in #{reported[key]}.")
            continue
        reported[key] = gh.post_issue(issue_for(run, e))
        lines.append(f"- {code(e['test'])} skipped by #{e['pr']}: reported in #{reported[key]}.")
    n = len(escapes)
    lines.append(f"- {n} escape{'' if n == 1 else 's'} reported.")


def positive(text):
    if not re.fullmatch(r"[1-9][0-9]{0,18}", text):
        raise argparse.ArgumentTypeError("a CI run id, a whole number from 1")
    return int(text)


def main(argv):
    ap = argparse.ArgumentParser(prog="escapes.py", description="Selector escapes in one failed full CI run on main.")
    sub = ap.add_subparsers(dest="command", required=True)
    f = sub.add_parser("find", help="judge one failed full run, and report each new escape on an issue")
    f.add_argument("--run", type=positive, required=True)
    f.add_argument("--attempt", type=positive, required=True, help="the attempt that failed")
    f.add_argument("--summary", help="also append the summary here (the run's $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv)
    gh = GitHub()
    try:
        result, lines = find(gh, args.run, args.attempt)
    except NotFullRun as e:
        print(f"escapes: {e}", file=sys.stderr)
        return 2
    except Fail as e:
        result, lines = "unknown", [f"- Unknown: {e}"]
    text = "\n".join([f"## Selector escapes in CI run {args.run} attempt {args.attempt}", "", f"Result: {result}", "", *lines]) + "\n"
    sys.stdout.write(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as out:
            out.write(text)
    return 1 if result == "unknown" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
