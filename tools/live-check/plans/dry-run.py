#!/usr/bin/env python3
"""Run version plans on the inherited synthetic kits; never a live entrypoint."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROFILES = {"send": "0.0.3", "new": "0.0.4"}
# Runtime durations, intermediate busy samples and paths are not stable outcomes.
VOLATILE = {"ms", "stages"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def reports(text):
    """Read complete top-level reports, without mistaking nested JSON for reports."""
    decoder = json.JSONDecoder()
    position = 0
    result = []
    while position < len(text):
        start = text.find("\n{", position)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(text[start + 1:])
        except ValueError:
            position = start + 2
            continue
        position = start + 1 + length
        if isinstance(value, dict) and "groups" in value:
            result.append(value)
    return result


def project(text):
    rows = []
    for report in reports(text):
        if report["outcome"] != "as_expected" or report["landing_at_end"] != "as_expected":
            raise ValueError("run or landing outcome changed")
        for group in report["groups"]:
            if group["outside"]["verdict"] != "as_expected":
                raise ValueError("outside-session outcome changed")
            for step in group["steps"]:
                rows.append([group["group"], step["step"], step["do"],
                             step["verdict"], stable(step.get("got", {}))])
    return rows


def read_plan(profile, path):
    plan = read_json(path)
    recorded = read_json(HERE / (PROFILES[profile] + ".recorded.json"))
    if (not isinstance(plan["budget"], dict) or
            any(type(v) is not int for v in plan["budget"].values()) or
            plan["budget"] != recorded["budget"]):
        raise ValueError("budget differs from the recorded allowance")
    actual = [[g["id"], s["id"], s["do"]] for g in plan["groups"] for s in g["steps"]]
    expected = [s[:3] for s in recorded["steps"]]
    if actual != expected:
        raise ValueError("ordered steps differ from the recorded dry run")
    body = json.dumps(plan["groups"], sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(body).hexdigest() != recorded["groups_sha256"]:
        raise ValueError("operative step bodies differ from the reviewed kit plan")
    return plan, recorded



def canonical_row(row):
    group, step, action, verdict, observation = row
    got = dict(observation)
    if (group, step, action) in (("C7", "C7-race", "send"), ("C3", "C3-N2", "create")):
        # These two reviewed races allow completed replays or in-progress
        # losers. Scheduling cannot change their single call or final landing.
        count = 4 if action == "send" else 2
        exits = got.pop("exit_list")
        if len(exits) != count or 0 not in exits or any(code not in (0, 7) for code in exits):
            raise ValueError("invalid race exits: " + repr(exits))
        if action == "send":
            code = got["exit"]
            if code != exits[0]:
                raise ValueError("race first child exit disagrees")
            fields = (got["status"], got["delivery"], got["effect"], got["replayed"], got["recovered"])
            allowed = (("accepted", "accepted", "starts_turn", False, False),
                       ("accepted", "accepted", "starts_turn", True, False)) if code == 0 else (
                       ("in_progress", None, "unknown", None, None),)
            if fields not in allowed:
                raise ValueError("invalid race first child outcome: " + repr(fields))
            for key in ("exit", "status", "delivery", "effect", "replayed", "recovered"):
                del got[key]
        got["processes"] = count
    return [group, step, action, verdict, got]


def compare(text, recorded):
    actual = [canonical_row(row) for row in project(text)]
    expected = [canonical_row(row) for row in recorded["steps"]]
    if actual != expected:
        for index, (got, want) in enumerate(zip(actual, expected)):
            if got != want:
                raise ValueError("recorded step %d differs: got %r; expected %r" % (index, got, want))
        raise ValueError("recorded step count differs: got %d, expected %d" %
                         (len(actual), len(expected)))
    return {"steps": len(actual), "calls": sum(s[4].get("calls", 0) for s in actual),
            "outcome": "as_expected"}


def run(profile, path, log):
    plan, recorded = read_plan(profile, path)
    scripts = ROOT / "tools/live-check" / profile / "scripts"
    source = Path(os.environ["KIT_SOURCE_ROOT"]).resolve()
    # The original lib verifies the pinned PATH source before running any binary.
    # Keep its fixtures, ownership cleanup and all run-sheet assertions intact.
    harness = (scripts / "test/dry-run.sh").read_text()

    def replace_once(old, new):
        nonlocal harness
        if harness.count(old) != 1:
            raise ValueError("inherited harness seam changed: " + old)
        harness = harness.replace(old, new)

    replace_once('. "$(dirname "$0")/lib.sh"', ". " + shlex.quote(str(scripts / "test/lib.sh")))
    # Verify the checkout that produced the fixture binaries, not the moving
    # toolkit checkout. The inherited checks still enforce its exact HEAD.
    replace_once('HEAD=$(git rev-parse HEAD)', 'HEAD=$(git -C "$SOURCE_ROOT" rev-parse HEAD)')
    if harness.count('--checkout "$ROOT"') != (2 if profile == "send" else 1):
        raise ValueError("inherited checkout seam changed")
    harness = harness.replace('--checkout "$ROOT"', '--checkout "$SOURCE_ROOT"')
    setup = "run 0 setup --plan " + shlex.quote(str(path))
    if profile == "new":
        setup += " --contracts " + shlex.quote(str(source / "contracts"))
        setup += " --budget-creates %d --budget-sends %d" % (plan["budget"]["creates"], plan["budget"]["sends"])
    else:
        # Send uses its existing external manifest rather than a budget flag.
        allowance = shlex.quote(json.dumps({"total": plan["budget"]["sends"], "approval": "L-8"}))
        setup = ('mkdir -m 700 "$WORK/dry/allowance"\n'
                 "(umask 077; printf '%s\n' " + allowance + ' > "$WORK/dry/allowance/allowance.json"; '
                 ': > "$WORK/dry/allowance/charges.log")\n') + setup
    replace_once('run 0 setup --work "$W"', setup + ' --work "$W"')
    with tempfile.TemporaryDirectory(prefix="lt2-plan-") as directory:
        driver = Path(directory) / "dry-run.sh"
        driver.write_text(harness)
        env = dict(os.environ, KIT_SCRIPT=str(scripts / (profile + "-kit.py")),
                   KIT_NO_BUILD="1", PYTHONDONTWRITEBYTECODE="1")
        with Path(log).open("w") as output:
            result = subprocess.run(["sh", str(driver)], cwd=ROOT, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            raise ValueError("inherited dry run exited %d; see %s" % (result.returncode, log))
    return compare(Path(log).read_text(), recorded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--plan", type=Path, help="candidate version plan (including planted faults)")
    parser.add_argument("--log", type=Path, required=True, help="complete inherited run log")
    args = parser.parse_args()
    path = (args.plan or HERE / (PROFILES[args.profile] + ".json")).resolve()
    try:
        result = run(args.profile, path, args.log)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
