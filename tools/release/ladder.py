import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check import Refused, blob, command, git, git_env, require, shape, unique
from entry import sentence


REPO = "repos/openwizdev/OpenWiz"
DEFAULT_LADDER = Path(__file__).with_name("ladder.json")
VERSION = re.compile(r"0\.1\.(0|[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")
CHANGE = re.compile(r"changes/([1-9][0-9]*)\.md")
KINDS = "added changed fixed removed security".split()
STATES = ("released", "candidate", "planned")
PULLS = "pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100"


def timestamp(value):
    require(isinstance(value, str)
            and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value),
            "expected a UTC timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def patch(value):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, "version must stay on the 0.1.x release line")
    return int(match[1])


def commit_id(value):
    require(isinstance(value, str) and SHA.fullmatch(value), "invalid commit SHA")
    return value


def number(value):
    require(type(value) is int and value > 0, "invalid PR or ticket number")
    return value


def check_merges(merges):
    require(isinstance(merges, list), "merges must be an array")
    seen = set()
    for merge in merges:
        shape(merge, "pr head merge_commit changelog")
        pr = number(merge["pr"])
        require(pr not in seen, f"duplicate PR #{pr} in entry")
        seen.add(pr)
        commit_id(merge["head"])
        commit_id(merge["merge_commit"])
        require(isinstance(merge["changelog"], list), "changelog must be an array")
        tickets = set()
        for line in merge["changelog"]:
            shape(line, "ticket kind sentence")
            ticket = number(line["ticket"])
            require(ticket not in tickets and line["kind"] in KINDS, "invalid changelog row")
            tickets.add(ticket)
            sentence(line["sentence"], f"changes/{ticket}.md")


def load_ladder(path):
    entries = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    require(isinstance(entries, list) and entries, "ladder must be a nonempty array")
    previous_patch, previous_state, released = -1, 0, None
    for entry in entries:
        state = entry.get("state") if isinstance(entry, dict) else None
        require(state in STATES, "unknown ladder state")
        fields = "version state merges"
        if state == "released":
            fields += " published_at published_changelog"
        shape(entry, fields)
        current_patch = patch(entry["version"])
        require(current_patch > previous_patch and STATES.index(state) >= previous_state,
                "ladder order must advance by version with released entries first")
        previous_patch, previous_state = current_patch, STATES.index(state)
        check_merges(entry["merges"])
        if state == "released":
            published = timestamp(entry["published_at"])
            require(released is None or published > timestamp(released["published_at"]),
                    "release timestamps are out of order")
            require(isinstance(entry["published_changelog"], list), "published changelog must be an array")
            for line in entry["published_changelog"]:
                sentence(line, "published changelog")
            released = entry
    require(released is not None, "ladder needs a released entry")
    return released


def github(repo, path, *flags):
    return json.loads(command(["gh", "api", *flags, f"{REPO}/{path}"], repo, git_env(), timeout=60),
                      object_pairs_hook=unique)


def merged_pulls(repo, since, main_order):
    previous_update = None
    seen = set()
    page = 1
    while True:
        pulls = github(repo, f"{PULLS}&page={page}")
        require(isinstance(pulls, list) and len(pulls) <= 100, "invalid GitHub pull request page")
        for pull in pulls:
            require(isinstance(pull, dict), "invalid GitHub pull request")
            updated = timestamp(pull.get("updated_at"))
            require(previous_update is None or updated <= previous_update, "GitHub pull requests are out of order")
            previous_update = updated
            if updated <= since:
                return
            pr = number(pull.get("number"))
            require(pr not in seen, f"duplicate GitHub PR #{pr} across pages")
            seen.add(pr)
            require("merged_at" in pull, f"missing GitHub merge state for PR #{pr}")
            merged = pull["merged_at"]
            if merged is None or timestamp(merged) <= since:
                continue
            base = pull.get("base")
            require(pull.get("state") == "closed" and isinstance(base, dict)
                    and isinstance(base.get("ref"), str), f"invalid GitHub merge state for PR #{pr}")
            if base["ref"] != "main":
                continue
            commit = commit_id(pull.get("merge_commit_sha"))
            if commit in main_order:
                head = pull.get("head")
                require(isinstance(head, dict), f"missing head for PR #{pr}")
                yield pr, commit, commit_id(head.get("sha"))
        if len(pulls) < 100:
            return
        page += 1


def changed_paths(repo, pr, commit):
    parents = git(repo, "rev-list", "--parents", "-1", commit).split()[1:]
    if len(parents) > 1:
        paths = git(repo, "diff-tree", "--no-renames", "--diff-filter=AMT", "--name-only",
                    "-r", "-z", f"{commit}^1", commit, "--", "changes/")
        return paths.decode("utf-8").split("\0")
    pages = github(repo, f"pulls/{pr}/files?per_page=100", "--paginate", "--slurp")
    require(isinstance(pages, list) and pages and all(isinstance(page, list) for page in pages),
            f"invalid changed-file pages for PR #{pr}")
    rows = [row for page in pages for row in page]
    require(len(rows) < 3000, f"GitHub changed-file list could be truncated for PR #{pr}")
    paths = []
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("filename"), str)
                and row.get("status") in ("added", "removed", "modified", "renamed", "copied", "changed"),
                f"invalid changed file for PR #{pr}")
        path = row["filename"]
        require(path not in seen, f"duplicate changed file for PR #{pr}")
        seen.add(path)
        if row["status"] != "removed":
            paths.append(path)
    return paths


def changelog(repo, pr, commit):
    lines = []
    for path in changed_paths(repo, pr, commit):
        match = CHANGE.fullmatch(path)
        if match is None:
            continue
        text = blob(repo, commit, path).decode("utf-8")
        note = re.fullmatch(r"kind: ([a-z]+)\n\n([^\r\n]+)\n", text)
        require(note is not None and note[1] in KINDS, f"invalid changelog format in {path}")
        lines.append({"ticket": int(match[1]), "kind": note[1], "sentence": sentence(note[2], path)})
    return sorted(lines, key=lambda line: line["ticket"])


def propose(repo, released, requested):
    next_patch = patch(released["version"]) + 1
    version = f"0.1.{next_patch}"
    if requested is not None:
        require(patch(requested) == next_patch, f"next patch version is {version}")
    ref = github(repo, "git/ref/heads/main")
    require(isinstance(ref, dict) and ref.get("ref") == "refs/heads/main", "invalid GitHub main reference")
    obj = ref.get("object")
    require(isinstance(obj, dict) and obj.get("type") == "commit", "GitHub main does not name a commit")
    main = commit_id(obj.get("sha"))
    require(git(repo, "rev-parse", "--is-shallow-repository").strip() == b"false",
            "propose needs a complete git checkout")
    try:
        history = git(repo, "rev-list", "--first-parent", main).decode("ascii").splitlines()
    except Refused as error:
        raise Refused("cannot read GitHub main in this checkout; fetch origin main") from error
    main_order = {commit: index for index, commit in enumerate(reversed(history))}
    since = timestamp(released["published_at"])
    pulls = sorted(merged_pulls(repo, since, main_order), key=lambda pull: main_order[pull[1]])
    merges = [
        {"pr": pr, "merge_commit": commit, "head": head, "changelog": changelog(repo, pr, commit)}
        for pr, commit, head in pulls
    ]
    return {"version": version, "state": "candidate", "merges": merges}


def main():
    parser = argparse.ArgumentParser(description="Check the 0.1.x release ladder or print its next patch candidate.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate the ladder file")
    proposal = commands.add_parser("propose", help="print the next candidate as JSON",
                                   description="Run from an up-to-date, complete OpenWiz git checkout.")
    for command_parser in (check, proposal):
        command_parser.add_argument("--file", type=Path, default=DEFAULT_LADDER)
    proposal.add_argument("--version", help="require this version to be the next patch")
    args = parser.parse_args()
    try:
        released = load_ladder(args.file)
        if args.command == "check":
            print("ladder: ok")
        else:
            print(json.dumps(propose(Path.cwd(), released, args.version), indent=2))
    except (Refused, OSError, ValueError) as error:
        # PRIVACY: subprocess output and local paths are omitted from errors.
        message = str(error) if isinstance(error, Refused) else type(error).__name__
        print(f"ladder: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
