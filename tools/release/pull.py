#!/usr/bin/env python3
"""Pull a broken latest release and open a fix-forward ticket, under the recorded grant only.

Reads the latest release's scheduled live checks and the regression reports
opened since it shipped. When either crosses the owner's threshold and the
grant reader allows pulls, it makes the previous good release latest again,
lists the bad one in the release record's pulled list and opens one
fix-forward ticket. Without the grant it leaves one Needs you note and pulls
nothing. It only reads, marks a release latest, and opens issues or comments:
it never removes a release or a tag.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

GRANT = Path(__file__).resolve().parent / "grant.py"
SCHEMA = "openwiz.hot-update.v1"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
FAILED = {"failure", "timed_out", "startup_failure"}
REASONS = ("live-check-failed", "regression-threshold")


class Refused(Exception):
    pass


def gh(*args):
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise Refused(f"gh api {args[-1] if args else ''} failed: {result.stderr.strip()[:300]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise Refused(f"gh api {args[-1]} returned no JSON") from None


def version_of(release):
    tag = release.get("tag_name")
    text = tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag
    if not isinstance(text, str) or not VERSION.fullmatch(text):
        return None
    return text


def key(version):
    return tuple(int(part) for part in version.split("."))


def read_record(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"),
                            object_pairs_hook=lambda pairs: dict(_unique(pairs)))
    except FileNotFoundError:
        raise Refused(f"no release record at {path}") from None
    except (OSError, UnicodeError, ValueError) as error:
        raise Refused(f"unreadable release record: {error}") from None
    if (not isinstance(record, dict) or set(record) != {"schema", "record", "latest", "pulled"}
            or record["schema"] != SCHEMA or record["record"] != "release-record"
            or not isinstance(record["latest"], str) or not VERSION.fullmatch(record["latest"])
            or not isinstance(record["pulled"], list)):
        raise Refused("malformed release record")
    seen = set()
    for entry in record["pulled"]:
        if (not isinstance(entry, dict) or set(entry) != {"version", "last_good", "reason"}
                or not all(isinstance(entry[k], str) and VERSION.fullmatch(entry[k])
                           for k in ("version", "last_good"))
                or entry["reason"] not in REASONS or entry["version"] in seen):
            raise Refused("malformed pulled entry in the release record")
        seen.add(entry["version"])
    return record


def _unique(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return pairs


def write_record(path, record):
    data = json.dumps(record, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def live_check(repo, workflow, shipped):
    runs = gh(f"repos/{repo}/actions/workflows/{workflow}/runs?event=schedule&status=completed&per_page=100")
    runs = [r for r in runs.get("workflow_runs", []) if r.get("created_at", "") >= shipped]
    if not runs:
        return None
    newest = max(runs, key=lambda r: r["created_at"])
    if newest.get("conclusion") in FAILED:
        return [f"Scheduled live check {newest.get('html_url')} concluded {newest['conclusion']}."]
    return None


def regressions(repo, label, shipped, threshold):
    issues = gh(f"repos/{repo}/issues?labels={label}&state=all&since={shipped}&per_page=100")
    reports = [i for i in issues if "pull_request" not in i and i.get("created_at", "") >= shipped
               and label in {lab.get("name") for lab in i.get("labels", [])}]
    if len(reports) < threshold:
        return None
    return [f"{len(reports)} `{label}` reports since it shipped (threshold {threshold}):"] + \
        [f"- {i.get('html_url')}" for i in sorted(reports, key=lambda i: i["number"])]


def granted(fleet):
    command = [sys.executable, "-I", str(GRANT), "check", "pull"]
    if fleet is not None:
        command += ["--fleet", str(fleet)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def note(repo, issue, first_line, body):
    comments = gh(f"repos/{repo}/issues/{issue}/comments?per_page=100")
    if any(str(c.get("body", "")).split("\n", 1)[0] == first_line for c in comments):
        return "already noted"
    return gh("-X", "POST", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={first_line}\n\n{body}")["html_url"]


def main():
    parser = argparse.ArgumentParser(description="Pull a broken latest release under the recorded grant.")
    parser.add_argument("--repo", required=True, help="OWNER/NAME of the public release repository")
    parser.add_argument("--record", required=True, type=Path, help="the channel's hot-update.json release record")
    parser.add_argument("--live-check", required=True, help="workflow file of the scheduled live checks")
    parser.add_argument("--threshold", required=True, type=int, help="the owner's regression report threshold")
    parser.add_argument("--label", default="regression", help="label of public regression reports")
    parser.add_argument("--notes-issue", required=True, type=int, help="issue that gets the owner's Needs you note")
    parser.add_argument("--fleet", type=Path, help="fleet file for the grant reader (default: its own)")
    args = parser.parse_args()
    if args.threshold < 1:
        parser.error("--threshold must be at least 1")
    try:
        return pull(args)
    except (Refused, subprocess.TimeoutExpired, OSError) as error:
        print(f"pull: {error}", file=sys.stderr)
        return 1


def pull(args):
    record = read_record(args.record)
    latest = gh(f"repos/{args.repo}/releases/latest")
    bad = version_of(latest)
    if bad is None:
        raise Refused("latest release has no stable version tag")
    pulled = {entry["version"] for entry in record["pulled"]}
    if bad in pulled:
        raise Refused(f"{bad} is already pulled but is still latest; pulling nothing")
    if any(entry["last_good"] == bad for entry in record["pulled"]):
        print(f"pull: {bad} was reinstated as last good; it is not pulled again automatically")
        return 0

    shipped = latest.get("published_at") or ""
    reason, evidence = None, None
    for candidate, found in (("live-check-failed", live_check(args.repo, args.live_check, shipped)),
                             ("regression-threshold", regressions(args.repo, args.label, shipped, args.threshold))):
        if found:
            reason, evidence = candidate, found
            break
    if reason is None:
        print(f"pull: {bad} is healthy")
        return 0

    releases = gh(f"repos/{args.repo}/releases?per_page=100")
    good = [(version_of(r), r) for r in releases if not r.get("draft") and not r.get("prerelease")]
    good = [(v, r) for v, r in good if v is not None and key(v) < key(bad) and v not in pulled]
    if not good:
        raise Refused(f"no good release before {bad}; pulling nothing")
    last_good, successor = max(good, key=lambda pair: key(pair[0]))

    allowed, grant_reason = granted(args.fleet)
    summary = "\n".join([f"Release {bad} crossed the pull threshold ({reason}).", *evidence])
    if not allowed:
        where = note(args.repo, args.notes_issue,
                     f"Needs you: release {bad} shows breakage ({reason}) but no recorded pull grant allows pulling it",
                     f"{summary}\n\nThe grant reader said: {grant_reason}\n"
                     f"Nothing was pulled. Pulling would make {last_good} latest again.")
        print(f"pull: {bad} not pulled without the grant; owner note {where}")
        return 2

    gh("-X", "PATCH", f"repos/{args.repo}/releases/{successor['id']}", "-f", "make_latest=true")
    record["latest"] = last_good
    record["pulled"].append({"version": bad, "last_good": last_good, "reason": reason})
    write_record(args.record, record)
    ticket = gh("-X", "POST", f"repos/{args.repo}/issues",
                "-f", f"title=Fix forward: {bad} was pulled from latest",
                "-f", "body=" + "\n".join([
                    summary, "",
                    f"{last_good} is latest again and {bad} is listed as pulled ({reason}).",
                    f"Neither release nor its tag was removed. Fix forward in the next patch after {bad}.",
                    f"Bad release: {latest.get('html_url')}", f"Last good release: {successor.get('html_url')}"]))
    print(f"pull: pulled {bad}; {last_good} is latest; fix-forward ticket {ticket.get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
