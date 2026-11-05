#!/usr/bin/env python3
"""Read OpenWiz settings; save a reviewed plan; apply it journalled; recover from its journal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

TARGET = "openwizdev/openwiz"
OLD_TARGET = "jparker2006/OpenWiz"
SOURCE = "jparker2006/ClosedWiz"
CHECKS = ("web-build", "rust", "web-test", "privacy")
RUNNER_VARIABLES = {"CI_RUNS_ON", "CI_RUST_RUNS_ON", "CI_WEB_RUNS_ON", "CI_SMALL_RUNS_ON"}
FIELDS = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
PLAN_FORMAT = "open-settings.plan.v1"
JOURNAL_FORMAT = "open-settings.journal.v1"
ACTION_KEYS = {"setting", "method", "path", "value", "resource", "identity", "prior", "change"}
# O1's reviewed public-after-edit milestone: author the public value rather
# than copying its private quotation. All proposed values still get checked.
PUBLIC_MILESTONE_DESCRIPTIONS = {
    "0.0.X": (
        "Polish when capacity allows: UI design, repository cleanup, public README "
        "and installation, and skill polish (spec #204).\n"
        "Jake, 2026-11-01: the polish milestone has no fixed version number or "
        "urgency ([private record](https://github.com/jparker2006/ClosedWiz/"
        "issues/204#issuecomment-6552796396))."
    ),
}


class Refusal(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON contains a repeated key")
        result[key] = value
    return result


def invalid_constant(_value):
    raise Refusal("JSON contains a non-finite number")


def api(path, method="GET", payload=None, paginate=False):
    # Explicit repo paths and GET prevent gh's cwd/field-based defaults.
    require(path.startswith("repos/"), "unexpected API path")
    if method != "GET":
        require(path.startswith((f"repos/{TARGET}/", f"repos/{OLD_TARGET}/")),
                "refusing a write outside OpenWiz")
    cmd = ["gh", "api", "--method", method, "--header", "Accept: application/vnd.github+json",
           "--header", "X-GitHub-Api-Version: 2026-03-10", path]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    if payload is not None:
        cmd += ["--input", "-"]
    try:
        proc = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                              text=True, capture_output=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise Refusal(f"{method} {path}: gh failed ({type(error).__name__})") from error
    require(proc.returncode == 0, f"{method} {path}: gh exited {proc.returncode}; stopped, no retry")
    # A write's 2xx response is never evidence that it persisted. Its read-back is.
    if method != "GET":
        return None
    try:
        return json.loads(proc.stdout, object_pairs_hook=no_duplicates, parse_constant=invalid_constant)
    except (ValueError, Refusal) as error:
        raise Refusal(f"GET {path}: invalid JSON ({error})") from error


def object_with(value, keys, location):
    require(isinstance(value, dict) and all(k in value for k in keys),
            f"{location}: missing object fields")
    return value


def positive(value):
    return type(value) is int and value > 0


def text(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value)


def pages(path, key=None):
    answer = api(path, paginate=True)
    require(isinstance(answer, list) and bool(answer), f"GET {path}: missing pages")
    items = []
    total = None
    for page in answer:
        if key:
            object_with(page, ("total_count", key), f"GET {path}")
            count = page["total_count"]
            require(type(count) is int and count >= 0 and (total is None or total == count),
                    f"GET {path}: inconsistent total_count")
            total = count
            page = page[key]
        require(isinstance(page, list) and all(isinstance(i, dict) for i in page),
                f"GET {path}: invalid page")
        items.extend(page)
    require(total is None or len(items) == total, f"GET {path}: incomplete page coverage")
    return items


def unique(items, key, location, fold=False):
    result = {}
    for item in items:
        object_with(item, (key,), location)
        value = item[key]
        require(text(value) if fold else (text(value) or positive(value)), f"{location}: invalid {key}")
        identity = value.casefold() if fold else value
        require(identity not in result, f"{location}: repeated {key}")
        result[identity] = item
    return result


def labels(repo):
    path = f"repos/{repo}/labels?per_page=100"
    result = {}
    for identity, item in unique(pages(path), "name", path, fold=True).items():
        object_with(item, ("name", "color", "description"), path)
        require(isinstance(item["color"], str) and re.fullmatch(r"[a-fA-F0-9]{6}", item["color"]),
                f"GET {path}: invalid color")
        require(item["description"] is None or isinstance(item["description"], str),
                f"GET {path}: invalid description")
        # Raw values, as written on GitHub; normal() gives the comparison view.
        result[identity] = {"name": item["name"], "color": item["color"], "description": item["description"]}
    return result


def milestones(repo):
    path = f"repos/{repo}/milestones?state=all&per_page=100"
    rows = pages(path)
    unique(rows, "number", path)
    result = {}
    for title, item in unique(rows, "title", path).items():
        object_with(item, ("title", "number", "description", "state", "due_on"), path)
        require(positive(item["number"]) and item["state"] in ("open", "closed"),
                f"GET {path}: invalid milestone")
        require(item["description"] is None or isinstance(item["description"], str),
                f"GET {path}: invalid description")
        require(item["due_on"] is None or (isinstance(item["due_on"], str) and
                re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", item["due_on"])),
                f"GET {path}: invalid due_on")
        result[title] = {"title": title, "number": item["number"],
                         "description": item["description"], "state": item["state"], "due_on": item["due_on"]}
    return result


def normal(resource, row):
    """Comparison view: label colors lower case, null descriptions as empty text."""
    if row is None or resource not in ("labels", "milestones"):
        return row
    row = dict(row, description=row["description"] or "")
    if resource == "labels":
        row["color"] = row["color"].lower()
    return row


def normal_map(rows, resource):
    return {identity: normal(resource, row) for identity, row in rows.items()}


def rulesets(repo):
    root = f"repos/{repo}/rulesets"
    listing = pages(root + "?includes_parents=true&per_page=100")
    unique(listing, "id", root)
    owned = {}
    for item in listing:
        object_with(item, ("id", "name", "source", "source_type"), root)
        require(positive(item["id"]) and text(item["name"]) and text(item["source"])
                and item["source_type"] in ("Repository", "Organization", "Enterprise"),
                f"GET {root}: invalid ruleset identity")
        if item["name"] not in ("CI must pass", "Merge queue"):
            continue
        name = item["name"]
        require(name not in owned, f"GET {root}: ambiguous managed ruleset")
        require(item["source_type"] == "Repository" and item["source"].casefold() == repo.casefold(),
                f"GET {root}: managed ruleset is inherited; cannot apply")
        detail = api(f"{root}/{item['id']}")
        object_with(detail, ("id", *FIELDS), root)
        require(detail["id"] == item["id"] and detail["name"] == name,
                f"GET {root}: ruleset changed identity")
        require(detail["target"] in ("branch", "tag", "push") and detail["enforcement"] in ("active", "disabled", "evaluate")
                and isinstance(detail["bypass_actors"], list) and isinstance(detail["conditions"], dict)
                and isinstance(detail["rules"], list), f"GET {root}: invalid ruleset fields")
        types = unique(detail["rules"], "type", root)
        for kind in ("merge_queue", "required_status_checks"):
            if kind in types:
                require(isinstance(types[kind].get("parameters"), dict), f"GET {root}: missing rule parameters")
        if "required_status_checks" in types:
            checks = types["required_status_checks"]["parameters"].get("required_status_checks")
            place = f"GET {root}: required status checks"
            require(isinstance(checks, list) and all(isinstance(c, dict) for c in checks),
                    f"{place}: invalid check list")
            for check in unique(checks, "context", place).values():
                require(text(check["context"]), f"{place}: invalid context")
                binding = check.get("integration_id")
                require(binding is None or positive(binding), f"{place}: invalid integration binding")
        if "merge_queue" in types:
            params = types["merge_queue"]["parameters"]
            timeout = params.get("check_response_timeout_minutes")
            require(positive(timeout), f"GET {root}: invalid queue timeout")
        owned[name] = detail
    return owned


def guards(repo, owner_type):
    root = f"repos/{repo}"
    runners = pages(root + "/actions/runners?per_page=100", "runners")
    unique(runners, "id", root + "/actions/runners")
    blockers = ["self-hosted runners are registered"] if runners else []
    for scope, endpoint in [("repository", "variables")] + (
            [("organization", "organization-variables")] if owner_type == "Organization" else []):
        variables = pages(f"{root}/actions/{endpoint}?per_page=30", "variables")
        for name in unique(variables, "name", endpoint, fold=True):
            if name.upper() in RUNNER_VARIABLES:
                blockers.append(f"{scope} runner variable {name.upper()} is set")
    if owner_type != "Organization":
        blockers.append("merge queue requires the O20 organization transfer")
    return blockers


def destination(repo):
    """Read and check the destination; return its resolved address and owner type."""
    root = f"repos/{repo}"
    metadata = api(root)
    object_with(metadata, ("full_name", "visibility", "default_branch", "owner"), root)
    require(isinstance(metadata["full_name"], str) and metadata["full_name"].casefold() in
            (TARGET.casefold(), OLD_TARGET.casefold()) and metadata["visibility"] == "public"
            and metadata["default_branch"] == "main", f"GET {root}: unexpected destination identity, visibility or default branch")
    object_with(metadata["owner"], ("type",), root)
    owner = metadata["owner"]["type"]
    require(owner in ("User", "Organization"), f"GET {root}: unknown repository owner type")
    # Only the documented old-address redirect to final target is accepted.
    require(metadata["full_name"].casefold() == repo.casefold() or
            (repo == OLD_TARGET and metadata["full_name"].casefold() == TARGET.casefold()),
            f"GET {root}: unexpected repository redirect")
    # Resolve the validated redirect before comparing ruleset ownership or
    # planning requests: GitHub returns the canonical source, not the alias.
    return (TARGET if metadata["full_name"].casefold() == TARGET.casefold() else OLD_TARGET), owner


def fork_policy(repo):
    root = f"repos/{repo}"
    fork = api(root + "/actions/permissions/fork-pr-contributor-approval")
    object_with(fork, ("approval_policy",), root)
    require(fork["approval_policy"] in ("first_time_contributors_new_to_github", "first_time_contributors", "all_external_contributors"),
            f"GET {root}: unknown fork approval policy")
    return fork["approval_policy"]


def snapshot(repo):
    repo, owner = destination(repo)
    blockers = guards(repo, owner)
    fork = fork_policy(repo)
    raw_labels, raw_milestones = labels(repo), milestones(repo)
    # The plan compares normalized views; the raw rows are the exact prior values.
    return {"repository": repo, "blockers": blockers, "fork": fork, "rulesets": rulesets(repo),
            "labels": normal_map(raw_labels, "labels"), "milestones": normal_map(raw_milestones, "milestones"),
            "labels_raw": raw_labels, "milestones_raw": raw_milestones,
            "source_labels": normal_map(labels(SOURCE), "labels"),
            "source_milestones": normal_map(milestones(SOURCE), "milestones")}


def desired_rules(name, existing):
    if name == "CI must pass":
        checks = [{"context": c} for c in CHECKS]
        if existing:
            for rule in existing["rules"]:
                if rule["type"] == "required_status_checks":
                    old = {c["context"]: c for c in rule["parameters"]["required_status_checks"]}
                    for check in checks:
                        binding = old.get(check["context"], {}).get("integration_id")
                        if binding is not None:
                            check["integration_id"] = binding
        rules = [{"type": "deletion"}, {"type": "non_fast_forward"},
                 {"type": "required_status_checks", "parameters": {
                     "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                     "required_status_checks": checks}}]
        include = ["refs/heads/main", "refs/heads/release-*"]
    else:
        timeout = 75
        if existing:
            for rule in existing["rules"]:
                if rule["type"] == "merge_queue":
                    timeout = max(timeout, rule["parameters"]["check_response_timeout_minutes"])
        rules = [{"type": "merge_queue", "parameters": {
            "check_response_timeout_minutes": timeout, "grouping_strategy": "ALLGREEN",
            "max_entries_to_build": 5, "max_entries_to_merge": 1, "merge_method": "MERGE",
            "min_entries_to_merge": 1, "min_entries_to_merge_wait_minutes": 0}}]
        include = ["refs/heads/main"]
    return {"name": name, "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": include, "exclude": []}}, "rules": rules}


def canonical(value):
    """Object keys and ruleset list ordering have no policy meaning."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items() if not (k == "integration_id" and v is None)}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def plan(repo, state):
    root = f"repos/{repo}"
    actions = []

    def add(name, method, path, value, resource, identity):
        actions.append({"setting": name, "method": method, "path": path,
                        "value": value, "resource": resource, "identity": identity})

    for name in ("CI must pass", "Merge queue"):
        old = state["rulesets"].get(name)
        want = desired_rules(name, old)
        current = {k: old[k] for k in FIELDS} if old else None
        if canonical(current) != canonical(want):
            add(name, "PUT" if old else "POST", root + "/rulesets" + (f"/{old['id']}" if old else ""), want, "rulesets", name)
    if state["fork"] != "all_external_contributors":
        add("fork approval", "PUT", root + "/actions/permissions/fork-pr-contributor-approval",
            {"approval_policy": "all_external_contributors"}, "fork", None)
    for identity, want in state["source_labels"].items():
        old = state["labels"].get(identity)
        if old != want:
            value = dict(want)
            if old:
                value["new_name"] = value.pop("name")
            add("label:" + want["name"], "PATCH" if old else "POST",
                root + "/labels" + ("/" + quote(old["name"], safe="") if old else ""), value, "labels", identity)
    for title, source in state["source_milestones"].items():
        want = {k: v for k, v in source.items() if k != "number"}
        if title in PUBLIC_MILESTONE_DESCRIPTIONS:
            want["description"] = PUBLIC_MILESTONE_DESCRIPTIONS[title]
        old = state["milestones"].get(title)
        current = {k: v for k, v in old.items() if k != "number"} if old else None
        if current != want:
            add("milestone:" + title, "PATCH" if old else "POST",
                root + "/milestones" + (f"/{old['number']}" if old else ""), want, "milestones", title)
    return actions


def validate_metadata(actions, literals):
    # Reuse the one privacy command, via stdin: read mode creates no files.
    body = "\n".join(str(value) for action in actions
                     if action["resource"] in ("labels", "milestones")
                     for value in action["value"].values() if isinstance(value, str))
    privacy(body, literals, "proposed metadata")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def validate_persisted(values, literals):
    """Every text value a plan file or journal would hold passes the same check."""
    privacy("\n".join(strings(values)), literals, "material the plan or journal would hold")


def privacy(body, literals, what):
    checker = Path(__file__).resolve().parent.parent / "privacy-check" / "check.py"
    cmd = [sys.executable, "-I", str(checker), "--body-file", "/dev/stdin"]
    if literals is not None:
        cmd += ["--literals", literals, "--require-literals"]
    try:
        result = subprocess.run(cmd, input=body, text=True, capture_output=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise Refusal(f"privacy checker could not run; no {what} is safe to publish") from error
    require(result.returncode == 0, f"privacy checker refused {what} or could not read its inputs")


def read_object(repo, resource, identity):
    """Fresh, validated read of one planned object; None when it does not exist."""
    if resource == "rulesets":
        return rulesets(repo).get(identity)
    if resource == "fork":
        return {"approval_policy": fork_policy(repo)}
    if resource == "labels":
        return labels(repo).get(identity)
    return milestones(repo).get(identity)


def prior_of(state, action):
    resource, identity = action["resource"], action["identity"]
    if resource == "rulesets":
        return state["rulesets"].get(identity)
    if resource == "fork":
        return {"approval_policy": state["fork"]}
    return state[resource + "_raw"].get(identity)


def plan_body(repo, state, actions):
    """The reviewable plan: each write with the complete prior object it changes."""
    rows = []
    for action in actions:
        prior = prior_of(state, action)
        rows.append(dict(action, prior=prior, change="created" if prior is None else "updated"))
    return {"format": PLAN_FORMAT, "repository": repo, "actions": rows}


def digest_of(body):
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_target(action, row):
    """Whether a read row shows the action's new value."""
    if row is None:
        return False
    resource, value = action["resource"], action["value"]
    row = normal(resource, row)
    if resource == "rulesets":
        return canonical({k: row[k] for k in FIELDS}) == canonical(value)
    if resource == "labels":
        expected = dict(value)
        if "new_name" in expected:
            expected["name"] = expected.pop("new_name")
        return row == expected
    if resource == "milestones":
        return {k: v for k, v in row.items() if k != "number"} == value
    return row == value


def is_prior(action, row):
    """Whether a read row equals the plan's prior state (absent for a creation)."""
    prior = action["prior"]
    if prior is None or row is None:
        return prior is None and row is None
    if action["resource"] == "rulesets":
        return row["id"] == prior["id"] and canonical({k: row[k] for k in FIELDS}) == canonical({k: prior[k] for k in FIELDS})
    return row == prior


def sync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, text):
    """Create an owner-only file that must not exist, synced to disk."""
    path = Path(path).absolute()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        sync_parent(path)
    except FileExistsError as error:
        raise Refusal(f"{path.name} already exists; a plan or journal is never overwritten") from error
    except OSError as error:
        raise Refusal(f"could not write {path.name} ({type(error).__name__})") from error


class Journal:
    """Append-only JSON lines; each record is synced before the next step."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        try:
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
            sync_parent(self.path)
        except FileExistsError as error:
            raise Refusal("journal already exists; each apply needs a new journal") from error
        except OSError as error:
            raise Refusal(f"journal could not be created ({type(error).__name__})") from error

    def write(self, record):
        data = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            require(os.write(self.fd, data) == len(data), "journal write was short")
            os.fsync(self.fd)
        except OSError as error:
            raise Refusal(f"journal write failed ({type(error).__name__}); stopped before the next step") from error


def strict_json(text, what):
    try:
        return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=invalid_constant)
    except (ValueError, Refusal) as error:
        raise Refusal(f"{what} is truncated, changed or not JSON") from error


def load_plan(path, digest, repo_choices):
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "plan digest must be 64 lowercase hex characters")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise Refusal(f"plan file is unreadable ({type(error).__name__})") from error
    plan_file = strict_json(text, "plan file")
    require(isinstance(plan_file, dict) and set(plan_file) == {"format", "repository", "actions", "digest"},
            "plan file has the wrong shape")
    body = {k: v for k, v in plan_file.items() if k != "digest"}
    require(plan_file["digest"] == digest and digest_of(body) == digest,
            "plan digest mismatch: the plan file changed or is not the reviewed plan")
    require(body["format"] == PLAN_FORMAT and body["repository"] in repo_choices, "plan file has the wrong format or repository")
    require(isinstance(body["actions"], list), "plan file has the wrong shape")
    root = f"repos/{body['repository']}/"
    for action in body["actions"]:
        require(isinstance(action, dict) and set(action) == ACTION_KEYS
                and action["method"] in ("POST", "PUT", "PATCH")
                and action["resource"] in ("rulesets", "fork", "labels", "milestones")
                and isinstance(action["path"], str) and action["path"].startswith(root)
                and isinstance(action["value"], dict)
                and (action["prior"] is None or isinstance(action["prior"], dict))
                and action["change"] == ("created" if action["prior"] is None else "updated"),
                "plan file has a malformed action")
    return body


def entry(index, action):
    return {"index": index, "method": action["method"], "path": action["path"], "identity": action["identity"],
            "prior": action["prior"], "value": action["value"]}


def apply_plan(repo, body, digest, journal_path, applied, literals):
    journal = Journal(journal_path)
    checked = set(strings(body["actions"]))
    journal.write({"record": "start", "format": JOURNAL_FORMAT, "plan_digest": digest, "repository": repo})
    for index, action in enumerate(body["actions"]):
        record = entry(index, action)
        journal.write(dict(record, record="intent"))
        try:
            api(action["path"], action["method"], action["value"])
            row = read_object(repo, action["resource"], action["identity"])
            require(is_target(action, row), f"read-back mismatch for {action['setting']}; stopped, no retry")
            # Read-back text not already checked with the plan is checked before it is kept.
            new = sorted(set(strings(row)) - checked)
            if new:
                validate_persisted(new, literals)
                checked.update(new)
        except Refusal:
            # The write may or may not have landed: never recorded as done.
            journal.write(dict(record, record="completion", new=None, result="unknown"))
            raise
        journal.write(dict(record, record="completion", new=row, result="done"))
        applied.append(action["setting"])
    return journal


def read_journal(path, body, digest):
    """Validate a journal against its plan; return {intended index: its completion or None}."""
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise Refusal(f"journal is unreadable ({type(error).__name__})") from error
    # A record is complete only with its newline; an unterminated tail (even
    # one cut inside a character) was being written when the run stopped,
    # before the step it guards. Complete records must be strict UTF-8.
    lines = data.split(b"\n")[:-1]
    require(bool(lines), "journal is empty")
    records = []
    for number, line in enumerate(lines):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Refusal(f"journal record {number} is not UTF-8") from error
        records.append(strict_json(text, "journal record"))
    require(records[0] == {"record": "start", "format": JOURNAL_FORMAT, "plan_digest": digest,
                           "repository": body["repository"]}, "journal does not start with this plan's record")
    actions = body["actions"]
    seen = {}
    position = 1
    for index, action in enumerate(actions):
        if position == len(records):
            break
        expected = entry(index, action)
        require(records[position] == dict(expected, record="intent"), f"journal record {position} does not match the plan")
        position += 1
        completion = None
        if position < len(records) and records[position].get("record") == "completion":
            completion = records[position]
            require(isinstance(completion, dict) and set(completion) == set(expected) | {"record", "new", "result"}
                    and {k: completion[k] for k in expected} == expected,
                    f"journal record {position} does not match the plan")
            if completion["result"] == "done":
                require(isinstance(completion["new"], dict) and is_target(action, completion["new"]),
                        f"journal record {position} does not match the plan")
            else:
                require(completion["result"] == "unknown" and completion["new"] is None,
                        f"journal record {position} has an invalid result")
            position += 1
        seen[index] = completion
        if completion is None or completion["result"] != "done":
            break
    if position < len(records):
        require(position == len(records) - 1 and len(seen) == len(actions)
                and all(c and c["result"] == "done" for c in seen.values())
                and records[position] == {"record": "end", "result": "complete"},
                f"journal record {position} does not match the plan")
    return seen


def same_object(row, journal_row, resource):
    key = {"rulesets": "id", "milestones": "number", "labels": "name"}[resource]
    return journal_row is None or row[key] == journal_row[key]


def recover(repo, body, seen):
    """Undo journalled writes newest first; return the recovery report."""
    report = {"restored": [], "removed": [], "unchanged": [], "unknown_resolved": []}
    root = f"repos/{repo}"
    for index in sorted(seen, reverse=True):
        action = body["actions"][index]
        completion = seen[index]
        resource, prior, name = action["resource"], action["prior"], action["setting"]
        row = read_object(repo, resource, action["identity"])
        if completion is None or completion["result"] != "done":
            report["unknown_resolved"].append({"setting": name, "landed": not is_prior(action, row)})
        if is_prior(action, row):
            report["unchanged"].append(name)
            continue
        if prior is None:
            require(same_object(row, completion and completion["new"], resource),
                    f"{name}: the created object was replaced since; not removing it")
            path = {"rulesets": f"{root}/rulesets/{row.get('id')}",
                    "labels": f"{root}/labels/" + quote(str(row.get("name")), safe=""),
                    "milestones": f"{root}/milestones/{row.get('number')}"}[resource]
            api(path, "DELETE")
            report["removed"].append(name)
        else:
            require(row is not None, f"{name}: the updated object is gone; cannot restore it")
            if resource == "rulesets":
                api(f"{root}/rulesets/{prior['id']}", "PUT", {k: prior[k] for k in FIELDS})
            elif resource == "fork":
                api(action["path"], "PUT", prior)
            elif resource == "labels":
                api(f"{root}/labels/" + quote(row["name"], safe=""), "PATCH",
                    {"new_name": prior["name"], "color": prior["color"], "description": prior["description"]})
            else:
                api(f"{root}/milestones/{prior['number']}", "PATCH",
                    {k: prior[k] for k in ("title", "description", "state", "due_on")})
            report["restored"].append(name)
        require(is_prior(action, read_object(repo, resource, action["identity"])),
                f"read-back after recovering {name} differs from the plan's prior state; stopped, no retry")
    for index in seen:
        action = body["actions"][index]
        require(is_prior(action, read_object(repo, action["resource"], action["identity"])),
                f"final read-back of {action['setting']} differs from the plan's prior state")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="apply one reviewed plan (--plan, --digest, --journal), journalled; requires separate live approval")
    mode.add_argument("--recover", action="store_true",
                      help="undo the journalled writes of one apply (--plan, --digest, --journal)")
    mode.add_argument("--plan-out", metavar="PATH", help="after the dry read, save its plan file (new file only)")
    parser.add_argument("--plan", metavar="PATH", help="the reviewed plan file")
    parser.add_argument("--digest", help="the reviewed plan's digest, as the dry read printed it")
    parser.add_argument("--journal", metavar="PATH", help="apply: a new journal file; recover: that apply's journal")
    parser.add_argument("--literals", help="private literal list for the shared privacy check; unreadable or empty refuses")
    parser.add_argument("--repo", choices=[TARGET, OLD_TARGET], default=TARGET,
                        help="one destination setting; old address is for pre-transfer reads")
    args = parser.parse_args()
    bound = (args.plan, args.digest, args.journal)
    if args.apply or args.recover:
        if None in bound:
            parser.error("--apply and --recover need --plan, --digest and --journal")
    elif bound != (None, None, None):
        parser.error("--plan, --digest and --journal are only for --apply or --recover")
    applied = []
    journal = None
    hint = "Earlier writes may remain; rerun a read before any new apply."
    try:
        if args.recover:
            hint = "Recovery stopped; read the cause, then run the same recovery again."
            body = load_plan(args.plan, args.digest, (TARGET, OLD_TARGET))
            repo, _ = destination(args.repo)
            require(body["repository"] == repo, "plan is for another repository")
            seen = read_journal(args.journal, body, args.digest)
            report = dict(recover(repo, body, seen), mode="recover", repository=repo, plan_digest=args.digest)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        body = load_plan(args.plan, args.digest, (TARGET, OLD_TARGET)) if args.apply else None
        state = snapshot(args.repo)
        repo = state["repository"]
        actions = plan(repo, state)
        validate_metadata(actions, args.literals)
        extra = {}
        if args.plan_out:
            saved = plan_body(repo, state, actions)
            validate_persisted(saved["actions"], args.literals)
            extra["plan_digest"] = digest_of(saved)
            write_new(args.plan_out, json.dumps(dict(saved, digest=extra["plan_digest"]), indent=2, sort_keys=True) + "\n")
        if args.apply and not state["blockers"]:
            require(body["repository"] == repo, "plan is for another repository")
            require(plan_body(repo, state, actions) == body,
                    "drift: current settings differ from the reviewed plan's prior state; review a new plan")
            extra["plan_digest"] = args.digest
            hint = "Earlier writes may remain; recover with --recover and the same plan, digest and journal."
            validate_persisted(body["actions"], args.literals)
            journal = apply_plan(repo, body, args.digest, args.journal, applied, args.literals)
            state = snapshot(repo)
            actions = plan(repo, state)
            require(not state["blockers"] and not actions, "final read-back changed; stopped, no retry")
            journal.write({"record": "end", "result": "complete"})
        report = {"mode": "apply" if args.apply else "read", "repository": state["repository"],
                  "differences": [a["setting"] for a in actions], "plan": actions,
                  "blockers": state["blockers"], "applied": applied,
                  "privacy_literals": args.literals is not None,
                  "target_only_labels": sorted(set(state["labels"]) - set(state["source_labels"])),
                  "target_only_milestones": sorted(set(state["milestones"]) - set(state["source_milestones"])),
                  **extra}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if state["blockers"] else 0
    except Refusal as error:
        print(f"open-settings: {error}. {hint}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
