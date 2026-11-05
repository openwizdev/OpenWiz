#!/usr/bin/env python3
"""#559: relay review and CI events to recorded builders, quietly, over CLI doors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

# The installed fleet and this repository tool share the public-fact resolver.
import importlib.util
sys.dont_write_bytecode = True
_record_spec = importlib.util.spec_from_file_location("fleet_records", Path(__file__).resolve().parents[2] / "skills/launch-fleet/scripts/records.py")
fleet_records = importlib.util.module_from_spec(_record_spec)
_record_spec.loader.exec_module(fleet_records)


class Fail(Exception):
    pass


def require(ok, why):
    if not ok:
        raise Fail(why)


def once(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "repeated JSON key")
        result[key] = value
    return result


def decode(text):
    try:
        return json.loads(text, object_pairs_hook=once)
    except (ValueError, UnicodeError):
        raise Fail("invalid JSON response or state") from None


def obj(value, fields):
    require(isinstance(value, dict) and all(k in value and type(value[k]) is t
            for k, t in fields.items()), "unexpected response shape")
    return value


def positive(value):
    require(type(value) is int and value > 0, "invalid event number")
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


# A review event comes only from the reviewer's report. Its lead line is the
# reviewer-only marker: review-ticket's `VERDICT:` line, or a `Findings` block
# that carries a finding line (`R<n>: ...` / `R<n> [sev] ...`). A builder's
# status reply to a finding (`R1 fixed at abc1234: ...`, `R1: fixed at
# abc1234`, `R2 disputed: ...`, a `## Findings: addressed` summary) is not a
# report, so it is a non-event for its own builder. A finding whose description
# merely contains a status word (`... resolved at startup ...`) is a report.
VERDICT = re.compile(r"^VERDICT: (?:APPROVE|CHANGES) at ([0-9a-f]{40})(?:\s|$)")
FINDINGS_HEADING = re.compile(r"^#*[ \t]*Findings\b[ \t]*:?[ \t]*")
FINDING_LINE = re.compile(r"^(?:#+[ \t]*)?(?:[-*]\s+)?(?:\*\*)?R[0-9]+(?:\*\*)?\s*(?::|\[(?:low|medium|high)\])(?:\*\*)?\s*:?")
# A status reply names its state then a commit, a clause or the end of its line
# (`fixed at <sha>`, `disputed:`, `resolved.`), optionally after a qualifier
# (`now fixed at ...`). A finding's prose carries on (`Resolved hostnames ...`,
# `... resolved at startup ...`, `Fixed in-memory buffers ...`), so a status
# word inside a description is not a reply.
REPLY_TAIL = re.compile(r"^(?:(?:now|still|all|already|fully|been|being|is|are|was|were|has|have|had)\s+)*"
                        r"(fixed|addressed|resolved|disputed)\b(?=\s*(?:at\b|[:;.,]|[\u2014\u2013]|$))")


def _finding_tails(text):
    """The text after each finding line, outside fenced code blocks."""
    tails, fenced = [], False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = FINDING_LINE.match(stripped)
        if match:
            tails.append(stripped[match.end():])
    return tails


def _reply_tail(chunk):
    """True when the text after a marker is a status reply, not a description."""
    first = chunk.splitlines()[0] if chunk.splitlines() else ""
    return bool(REPLY_TAIL.match(re.sub(r"[*_`~]", "", first).lstrip().lower()))


def _has_report(tails):
    """True when a finding line carries a description that is not a reply."""
    return any(tail.strip() and not _reply_tail(tail) for tail in tails)


def report_marker(text):
    """True when a body begins with a reviewer-only report or findings marker."""
    lead = text.lstrip()
    heading = FINDINGS_HEADING.match(lead)
    if heading:
        return _has_report(_finding_tails(lead[heading.end():]))
    line = FINDING_LINE.match(lead)
    if line:
        return _has_report([lead[line.end():]])
    return False


def save(path, state):
    """Atomic, durable replacement, including the directory entry before any tell."""
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(state, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def cache_body(path, value):
    """Retain the fields collection reads, including on legacy full-body 304s."""
    route = path.split("?", 1)[0].split("/", 3)[-1]
    if route == "pulls":
        fields = {"number": None, "state": None, "body": None, "head": {"sha": None}}
    elif route == "issues":
        fields = {"number": None, "state": None, "labels": {"name": None}, "pull_request": {}}
    elif re.fullmatch(r"issues/[1-9][0-9]*/parent", route):
        fields = {"number": None}
    elif re.fullmatch(r"(?:issues|pulls)/[1-9][0-9]*/(?:comments|reviews)", route):
        fields = {"id": None, "body": None, "state": None, "commit_id": None}
    elif route == "actions/runs":
        fields = {"total_count": None, "workflow_runs": {
            "id": None, "run_attempt": None, "head_sha": None,
            "status": None, "conclusion": None}}
    else:
        raise Fail("unknown cached REST route")

    def keep(item, shape):
        # Preserve missing fields and wrong types for the existing validators.
        if type(item) is list:
            return [keep(row, shape) for row in item]
        if type(item) is dict:
            return {key: item[key] if nested is None else keep(item[key], nested)
                    for key, nested in shape.items() if key in item}
        return item

    return keep(value, fields)


class Reader:
    def __init__(self, repo, state):
        self.repo = repo
        self.cache = state["cache"]
        self.answers = {}
        self.locks = {}
        self.guard = threading.Lock()
        self.deadline = time.monotonic() + 50
        self.env = dict(os.environ)
        if self.env.get("REVIEW_RELAY_GH_TOKEN"):
            self.env["GH_TOKEN"] = self.env["REVIEW_RELAY_GH_TOKEN"]

    def command(self, args, what):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "check exceeded its time budget")
        try:
            return subprocess.run(args, capture_output=True, text=True, env=self.env,
                                  timeout=min(10, remaining))
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise Fail("could not run " + what) from None

    def thread_rows(self):
        with self.lock(("threads",)):
            if not hasattr(self, "threads"):
                result = self.command(["room-cli", "thread", "list", "--include-archived", "--include-hidden", "--json"], "room-cli list")
                require(result.returncode == 0, "could not read CloudRoom threads")
                self.threads = decode(result.stdout)
                require(type(self.threads) is list, "unexpected CloudRoom thread list")
                ids = set()
                for thread in self.threads:
                    obj(thread, {"id": str})
                    require(thread["id"] not in ids, "duplicate CloudRoom thread")
                    require("archivedAt" in thread and (thread["archivedAt"] is None or type(thread["archivedAt"]) is str), "unknown thread archive state")
                    ids.add(thread["id"])
            return self.threads

    def is_private(self):
        with self.lock(("privacy",)):
            if not hasattr(self, "private"):
                r = self.command(["gh", "repo", "view", self.repo, "--json", "isPrivate", "--jq", ".isPrivate"], "repository privacy")
                self.private = r.returncode == 0 and r.stdout.strip() == "true"
            return self.private

    def lock(self, key):
        with self.guard:
            return self.locks.setdefault(key, threading.Lock())

    def get(self, path, absent=False):
        key = (path, absent)
        with self.lock(("get", key)):
            if key not in self.answers:
                self.answers[key] = self._get(path, absent)
            return self.answers[key]

    def _get(self, path, absent=False):
        require(path.startswith("repos/" + self.repo + "/"), "REST link left the repository")
        route = path.split("?", 1)[0]
        require(re.fullmatch(r"[A-Za-z0-9_./-]+", route)
                and all(part not in (".", "..") for part in route.split("/")),
                "unsafe GitHub REST path")
        old = self.cache.get(path)
        args = ["gh", "api", "--method", "GET", "--include", path,
                "--header", "Accept: application/vnd.github+json"]
        if old and old["etag"]:
            args += ["--header", "If-None-Match: " + old["etag"]]
        result = self.command(args, "gh")
        raw = result.stdout.replace("\r\n", "\n")
        header, separator, body = raw.partition("\n\n")
        lines = header.splitlines()
        status = re.fullmatch(r"HTTP/[0-9.]+ ([0-9]{3})(?: .*)?", lines[0] if lines else "")
        require(status and separator, "could not read GitHub HTTP status")
        code = int(status[1])
        if code == 404 and absent:
            self.cache.pop(path, None)
            return None, None
        if code == 304:
            # gh api exits 1 for 304; the status and our cached entity decide it.
            require(result.returncode in (0, 1) and old is not None and old["etag"]
                    and not body.strip(), "invalid conditional response")
            old["body"] = cache_body(path, old["body"])
            return old["body"], old["next"]
        require(result.returncode == 0 and code == 200, "could not read GitHub")
        headers = {}
        for line in lines[1:]:
            key, colon, value = line.partition(":")
            require(colon, "invalid GitHub HTTP header")
            key = key.lower()
            require(key not in headers or key not in ("etag", "link"), "repeated GitHub HTTP header")
            headers[key] = value.strip()
        next_path = None
        for target, rel in re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', headers.get("link", "")):
            if rel == "next":
                parsed = urlsplit(target)
                require(parsed.scheme == "https" and parsed.netloc == "api.github.com"
                        and not parsed.fragment, "unsafe GitHub pagination link")
                require(next_path is None, "duplicate next page")
                # Link headers use /repositories/<id>/..., but the next request
                # stays on our original named route. The link only advertises
                # the next page, never a new destination or filter.
                suffix = route[len("repos/" + self.repo):]
                require(parsed.path == "/" + route
                        or re.fullmatch(r"/repositories/[1-9][0-9]*" + re.escape(suffix), parsed.path),
                        "pagination changed its REST route")
                query = parse_qsl(path.split("?", 1)[1], strict_parsing=True)
                advertised = parse_qsl(parsed.query, strict_parsing=True)
                require(len(dict(query)) == len(query) and len(dict(advertised)) == len(advertised),
                        "duplicate pagination parameter")
                current = dict(query)
                require(re.fullmatch(r"[1-9][0-9]*", current.get("page", "")), "invalid current page")
                expected = dict(current, page=str(int(current["page"]) + 1))
                require(dict(advertised) == expected, "pagination changed its page or filters")
                next_path = route + "?" + urlencode([(k, expected[k]) for k, _ in query])
        value = cache_body(path, decode(body))
        self.cache[path] = {"etag": headers.get("etag"), "body": value, "next": next_path}
        return value, next_path

    def one(self, suffix, absent=False):
        value, link = self.get("repos/" + self.repo + "/" + suffix, absent)
        require(link is None, "unexpected pagination on an object")
        return value

    def pages(self, suffix, field=None):
        path = "repos/" + self.repo + "/" + suffix
        path += ("&" if "?" in path else "?") + "per_page=100&page=1"
        seen, rows, count = set(), [], None
        while path:
            require(path not in seen, "repeated GitHub page")
            seen.add(path)
            value, path = self.get(path)
            if field:
                obj(value, {field: list, "total_count": int})
                require(value["total_count"] >= 0, "invalid page count")
                require(count is None or count == value["total_count"], "page count changed during read")
                count = value["total_count"]
                value = value[field]
            require(type(value) is list, "expected a GitHub list")
            rows.extend(value)
        if field:
            require(len(rows) == count, "partial GitHub list")
        return rows

def comments(rows, nullable=False):
    ids = set()
    for row in rows:
        obj(row, {"id": int})
        require("body" in row and (type(row["body"]) is str or nullable and row["body"] is None),
                "unexpected comment body")
        positive(row["id"])
        require(row["id"] not in ids, "duplicate comment across pages")
        ids.add(row["id"])
    return rows


def builder(reader, n, ticket):
    if ticket is None:
        return None
    obj(ticket, {"number": int, "state": str, "labels": list})
    require(ticket["number"] == n, "wrong ticket returned")
    labels = {obj(label, {"name": str})["name"] for label in ticket["labels"]}
    if ticket["state"] != "open" or "ready-for-agent" not in labels or "held" in labels:
        return None
    records = comments(reader.pages(f"issues/{n}/comments"))
    parent = reader.one(f"issues/{n}/parent", absent=True)
    if parent is None:
        approved = any(re.search(r"(?m)^\s*\*\*Approved on its own by [^\n]+:\*\*", c["body"]) for c in records)
    else:
        obj(parent, {"number": int})
        approvals = [c for c in comments(reader.pages(f'issues/{positive(parent["number"])}/comments'))
                     if c["body"].lstrip().startswith("**Plan graph approved by ")]
        latest = max(approvals, key=lambda c: c["id"], default={"body": ""})
        approved = any(re.fullmatch(rf"\|\s*#{n}\s*\|.*\|\s*ready-for-agent\s*\|\s*", line)
                       for line in latest["body"].splitlines())
    if not approved or any(c["body"].splitlines()[0] == "launch-fleet: archived" for c in records if c["body"]):
        return None
    found = []
    for record in sorted(records, key=lambda c: c["id"]):
        line = record["body"].splitlines()[0] if record["body"] else ""
        legacy = re.fullmatch(r"launch-fleet: (?:started, thread (thr_[A-Za-z0-9_-]+)|"
                              r"start checked, thread (thr_[A-Za-z0-9_-]+), branch [A-Za-z0-9._/-]+)", line)
        public = re.fullmatch(r"launch-fleet: (?:started|start checked, branch ([A-Za-z0-9._/-]+))", line)
        if legacy:
            if not reader.is_private():
                return None
            found.append(legacy[1] or legacy[2])
        elif public:
            target, reason = fleet_records.builder_thread(n, public[1], reader.thread_rows(), fleet_records.private_state(reader.repo))
            if reason:
                return None
            found.append(target)
    return found[0] if len(found) == 1 else None


def closing_tickets(body, repo):
    refs = re.findall(r"(?im)\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+"
                      r"(#[1-9][0-9]*|https://github\.com/[^\s)]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*)", body)
    result = set()
    for ref in refs:
        if ref.startswith("#"):
            result.add(int(ref[1:]))
        else:
            match = re.fullmatch(re.escape(repo) + r"#([1-9][0-9]*)", ref)
            url = re.fullmatch(r"https://github\.com/" + re.escape(repo) + r"/issues/([1-9][0-9]*)", ref)
            if match or url:
                result.add(int((match or url)[1]))
    return sorted(result)


def collect(reader):
    events, targets = [], {}
    pulls = reader.pages("pulls?state=open")
    for pull in pulls:
        obj(pull, {"number": int, "state": str, "head": dict})
        positive(pull["number"])
        sha = obj(pull["head"], {"sha": str})["sha"]
        require(re.fullmatch(r"[0-9a-f]{40}", sha), "invalid PR head")
        require(pull.get("body") is None or type(pull["body"]) is str, "invalid PR body")
    if not any(closing_tickets(p.get("body") or "", reader.repo) for p in pulls):
        return []
    tickets = {}
    for ticket in reader.pages("issues?state=open&labels=ready-for-agent"):
        obj(ticket, {"number": int, "state": str, "labels": list})
        n = positive(ticket["number"])
        require(n not in tickets, "duplicate ticket across pages")
        if "pull_request" not in ticket:
            tickets[n] = ticket

    def collect_pull(pull):
        found = []
        n, sha = pull["number"], pull["head"]["sha"]
        if pull["state"] != "open":
            return found
        owners = set()
        for ticket in closing_tickets(pull["body"] or "", reader.repo):
            with reader.lock(("builder", ticket)):
                if ticket not in targets:
                    targets[ticket] = builder(reader, ticket, tickets.get(ticket))
                if targets[ticket]:
                    owners.add(targets[ticket])
        if not owners:
            return found
        prefix = f"PR #{n} at {sha}: "
        for kind, suffix in (("comment", f"issues/{n}/comments"), ("review", f"pulls/{n}/reviews"),
                             ("inline", f"pulls/{n}/comments")):
            for row in comments(reader.pages(suffix), nullable=kind == "review"):
                text = row["body"] or ""
                if (not text or row.get("state") == "PENDING"
                        or kind != "comment" and row.get("commit_id", sha) != sha):
                    continue
                verdict = VERDICT.match(text)
                if verdict:
                    if verdict[1] != sha:
                        # A report for another head is not this head's.
                        continue
                    what = "review verdict"
                elif report_marker(text):
                    what = "review findings"
                else:
                    # A builder's reply, or trivial review or inline chatter,
                    # carries no reviewer-only marker: it is no event.
                    continue
                identity = f"{n}/{kind}/{row['id']}/{digest(text)}"
                for owner in sorted(owners):
                    found.append((identity + "/" + owner, owner, prefix + f"new {what}; read the report on GitHub."))
        runs = reader.pages(f"actions/runs?head_sha={sha}", "workflow_runs")
        for run in runs:
            obj(run, {"id": int, "run_attempt": int, "head_sha": str, "status": str})
            positive(run["id"])
            positive(run["run_attempt"])
            require(run["status"] in ("queued", "in_progress", "completed", "waiting", "requested", "pending"),
                    "unknown CI run status")
            require("conclusion" in run and (run["conclusion"] is None or type(run["conclusion"]) is str
                    and run["conclusion"] in ("success", "failure", "neutral", "cancelled", "skipped",
                                               "timed_out", "action_required", "startup_failure", "stale")),
                    "unknown CI run conclusion")
            if run["head_sha"] != sha or run["status"] != "completed" or run.get("conclusion") not in ("failure", "success", "timed_out", "action_required", "startup_failure"):
                continue
            identity = f"{n}/run/{run['id']}/{run['run_attempt']}"
            message = prefix + f"CI {run['conclusion']} (run {run['id']}, attempt {run['run_attempt']}); read the run on GitHub."
            for owner in sorted(owners):
                found.append((identity + "/" + owner, owner, message))
        return found

    with ThreadPoolExecutor(max_workers=8) as pool:
        for found in pool.map(collect_pull, pulls):
            events.extend(found)
    # Complete and validate every read before any notification is possible.
    active = {t["id"] for t in reader.thread_rows() if t["archivedAt"] is None} if events else set()
    return [event for event in events if event[1] in active]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo), "invalid repository")
        require(args.state_dir.is_absolute(), "state directory must be absolute")
        require(not args.state_dir.is_symlink(), "state directory cannot be a symlink")
        args.state_dir = args.state_dir.resolve()
        require(all(not (parent / ".git").exists() for parent in (args.state_dir, *args.state_dir.parents)),
                "state directory must be outside a checkout")
        args.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        require(args.state_dir.stat().st_uid == os.getuid() and args.state_dir.stat().st_mode & 0o077 == 0,
                "state directory must be private")
        lock_fd = os.open(args.state_dir / "lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            path = args.state_dir / "state.json"
            require(not path.is_symlink(), "state file cannot be a symlink")
            state = decode(path.read_bytes()) if path.exists() else {"repo": args.repo, "cache": {}, "sent": []}
            obj(state, {"repo": str, "cache": dict, "sent": list})
            require(set(state) == {"repo", "cache", "sent"} and state["repo"] == args.repo,
                    "state belongs to another repository or format")
            require(all(type(item) is str for item in state["sent"]), "invalid delivery markers")
            for entry in state["cache"].values():
                require(type(entry) is dict and set(entry) == {"etag", "body", "next"}, "invalid cached response")
                require(entry["etag"] is None or type(entry["etag"]) is str and "\n" not in entry["etag"]
                        and "\r" not in entry["etag"], "invalid cached entity tag")
                require(entry["next"] is None or type(entry["next"]) is str, "invalid cached page link")
            reader = Reader(args.repo, state)
            try:
                events = collect(reader)
            except Exception:
                # Workers have joined before collect raises. Preserve successful
                # reads, but never deliver a partial check.
                save(path, state)
                raise
            # Only a complete check establishes which pages are still needed.
            requested = {path for path, _ in reader.answers}
            for cached_path in list(state["cache"]):
                if cached_path not in requested:
                    del state["cache"][cached_path]
            save(path, state)
            for identity, owner, message in events:
                if identity in state["sent"]:
                    continue
                state["sent"].append(identity)
                save(path, state)
                # Reserve first: a timeout or crash must never repeat an uncertain tell.
                result = reader.command(["room-cli", "thread", "tell", owner, message], "room-cli tell")
                require(result.returncode == 0, "builder delivery uncertain; fleet check-in must handle it")
        return 0
    except Fail as error:
        print(f"review-relay: {error}.")
        return 1
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        # Never copy stderr, API bodies, tokens or thread content into loop output.
        print("review-relay: check or delivery failed; inspect configuration and use fleet check-in.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
