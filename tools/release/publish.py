#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
from check import (ALIAS, MODES, Refused, alias, changelog_entry, command, git_env, public_path, require,
                   sha, shape, unique)

from repository import repository, remote_url

DESCRIPTION = """Publish an exact checked export, only on the maintainer's `publish VERSION`.

    python3 tools/release/publish.py publish VERSION --repo EXPORT         --report EVIDENCE/report.json --approval 'publish VERSION'

The approval argument records the maintainer's actual instruction; generating
that argument is never itself approval. No retry or rollback is attempted on
failure: inspect the remote before running again after a partial publication.
The release notes are the checked commit's exact version entry in CHANGELOG.md.
No content is rewritten after release check.

With --backfill the report must come from `release check --historical` and
name the exact historical commit checked out at EXPORT. That commit must already
be reachable from public main. Only its annotated tag and release page are
created; main is never pushed. A historical report cannot publish without
--backfill, and a staged report cannot backfill.

Before any write, GitHub immutable releases must be enabled for the public
repository. After the release is created, its tag, title, notes, pre-release,
non-draft and immutable state are read back, followed by the tag object and its
peeled target. A failure stops there.
"""
CHECKS = ["plan", "open-development-privacy", "stage", "privacy", "historical-text", "links", "claims",
          "regression-proofs", "fresh-clone"]


def git(repo, *args):
    env = git_env()
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1")
    return command(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
                    "-c", "core.fsmonitor=false", "-c", "credential.helper=",
                    "-c", "credential.https://github.com.helper=!gh auth git-credential",
                    "-C", repo, *args], repo, env, timeout=120)


def blob(repo, head, path):
    return git(repo, "show", head+":"+path)


def tree(repo, head):
    entries = {}
    for row in git(repo, "ls-tree", "-rz", head).split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        mode, kind, oid = meta.split()
        path = path.decode("utf-8")
        public_path(path, product=True)
        require(kind == b"blob" and mode.decode() in MODES, "symlink or submodule refused")
        require(digest(oid.decode(), 40) and path not in entries, "invalid tree entry")
        entries[path] = (mode.decode(), oid.decode())
    return entries


def digest(value, length):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def report_at(path, version):
    try:
        data = json.loads(path.read_bytes(), object_pairs_hook=unique)
        shape(data, "schema version status checks files gaps source_head public_base export_head "
                    "export_tree plan_sha256 live_pending publishable scan_exceptions"
                    +(" historical" if isinstance(data, dict) and "historical" in data else ""))
        require(data["schema"] == "openwiz.release-check.v1" and data["version"] == version,
                "schema or version mismatch")
        require(data["status"] == "pass" and data["publishable"] is True
                and type(data["live_pending"]) is int and data["live_pending"] == 0,
                "report is not publishable")
        for key in ("source_head", "public_base", "export_head", "export_tree", "plan_sha256"):
            require(digest(data[key], 64 if key == "plan_sha256" else 40), "invalid "+key)
        require(isinstance(data["checks"], list), "checks must be an array")
        for item in data["checks"]:
            shape(item, "id status")
            require(item["status"] == "pass", "failed check")
        require([c["id"] for c in data["checks"]] == CHECKS, "incomplete check set")
        require(isinstance(data["gaps"], list) and all(isinstance(g, str) for g in data["gaps"]),
                "invalid gaps")
        require(isinstance(data["files"], list) and data["files"], "empty file list")
        seen = set()
        for item in data["files"]:
            shape(item, "path sha256 mode")
            public_path(item["path"], product=True)
            require(item["path"] not in seen, "duplicate file")
            seen.add(item["path"])
            require(digest(item["sha256"], 64) and item["mode"] in MODES
                    and (item["mode"] == "120000") == bool(ALIAS.fullmatch(item["path"])),
                    "invalid file hash or mode")
        if "historical" in data:
            shape(data["historical"], "public_main")
            require(digest(data["historical"]["public_main"], 40)
                    and data["source_head"] == data["export_head"],
                    "invalid historical report: source must be the published head")
        require(isinstance(data["scan_exceptions"], list), "invalid scan exceptions")
        for item in data["scan_exceptions"]:
            shape(item, "path sha256 rule")
            require(any(f["path"] == item["path"] and f["sha256"] == item["sha256"]
                        for f in data["files"]), "stale scan exception")
            require(item["rule"] in ("secret", "secret-hex", "personal", "identifier",
                                     "internal", "url", "historical", "site-font", "release-asset",
                                     "invalid-json"), "unknown scan exception")
        return data
    except (Refused, OSError, ValueError, TypeError) as error:
        raise Refused(f"report refused: {error}") from error


def verify_files(repo, head, data):
    require(git(repo, "rev-parse", head+"^{tree}").decode().strip() == data["export_tree"],
            "tree differs from report")
    entries = tree(repo, head)
    require(set(entries) == {f["path"] for f in data["files"]}, "file list differs from report")
    contents = {}
    for item in data["files"]:
        path = item["path"]
        value = blob(repo, head, path)
        require(sha(value) == item["sha256"], "file hash differs from report")
        require(entries[path][0] == item["mode"], "file mode differs from report")
        if item["mode"] == "120000":
            alias(path, value, entries)
        require(b"LIVE-PENDING" not in value and b"PUBLICATION-DATE" not in value,
                "pending placeholder in checked export")
        contents[path] = value
    return contents


def entry_from(contents, version):
    require("CHANGELOG.md" in contents, "checked CHANGELOG.md is required")
    return changelog_entry(contents["CHANGELOG.md"].decode("utf-8"), version)[1]


def gh_api(cwd, path):
    env = git_env()
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1")
    try:
        output = command(["gh", "api", path], cwd, env, timeout=120)
        return json.loads(output, object_pairs_hook=unique)
    except (Refused, ValueError) as error:
        raise Refused(f"cannot read {path}: {error}") from error


def immutable_releases(cwd, github):
    try:
        data = gh_api(cwd, f"repos/{github}/immutable-releases")
        require(isinstance(data, dict) and data.get("enabled") is True, "not enabled")
    except Refused as error:
        raise Refused(f"immutable releases must be enabled first: {error}") from error


def release_readback(cwd, github, tag, version, entry):
    try:
        data = gh_api(cwd, f"repos/{github}/releases/tags/{tag}")
        require(isinstance(data, dict), "release is not an object")
        body = data.get("body")
        require(data.get("tag_name") == tag and data.get("name") == "OpenWiz "+version, "tag or title differs")
        require(isinstance(body, str) and body.replace("\r\n", "\n").rstrip("\n") == entry.rstrip("\n"),
                "notes differ from the checked entry")
        require(data.get("draft") is False and data.get("prerelease") is True, "not a published pre-release")
        require(data.get("immutable") is True, "release is not immutable")
    except Refused as error:
        raise Refused(f"release read-back failed: {error}") from error


def refs(repo, remote, *names):
    output = git(repo, "ls-remote", remote, *names).decode()
    found = {}
    for line in output.splitlines():
        row = line.split("\t")
        require(len(row) == 2 and digest(row[0], 40) and row[1] in names
                and row[1] not in found, "unexpected remote ref response")
        found[row[1]] = row[0]
    return found


def publish(args):
    require(args.approval == "publish "+args.version, "exact maintainer approval is required")
    require(args.report is not None, "passing report is required")
    data = report_at(args.report, args.version)
    require(("historical" in data) == bool(args.backfill),
            "backfill needs a historical report, and a historical report needs --backfill")
    repo = args.repo.resolve(strict=True)
    github = repository(repo)
    remote = remote_url(github)
    head = data["export_head"]
    require(git(repo, "rev-parse", "HEAD").decode().strip() == head, "export head differs from report")
    require(not git(repo, "status", "--porcelain", "--untracked-files=all"), "export must be clean")
    contents = verify_files(repo, head, data)
    entry = entry_from(contents, args.version)
    git(repo, "merge-base", "--is-ancestor", data["public_base"], head)
    git(repo, "merge-base", "--is-ancestor", data["source_head"], head)
    name = git(repo, "show", "-s", "--format=%an", head).decode().strip()
    email = git(repo, "show", "-s", "--format=%ae", head).decode().strip()
    require(re.fullmatch(r"[A-Za-z .-]+", name) and
            re.fullmatch(r"[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com", email),
            "checked no-reply identity is required for annotation")

    immutable_releases(repo, github)

    with tempfile.TemporaryDirectory(prefix="release-publish-") as directory:
        scratch = Path(directory)
        work = scratch/"export.git"
        git(scratch, "clone", "--bare", "--no-local", "--no-tags", "--single-branch", repo, work)
        require(git(work, "rev-parse", "HEAD").decode().strip() == head, "export head moved")
        verify_files(work, head, data)
        tag = "v"+args.version
        tag_ref = "refs/tags/"+tag
        require(not refs(work, remote, tag_ref, tag_ref+"^{}"), "remote tag already exists")
        if not args.backfill:
            require(refs(work, remote, "refs/heads/main") == {"refs/heads/main":data["public_base"]},
                    "public base moved")
            git(work, "push", "--no-follow-tags", "--porcelain", remote, head+":refs/heads/main")
        readback = scratch/"remote.git"
        try:
            git(scratch, "clone", "--bare", "--no-local", "--no-tags", "--single-branch",
                "--branch", "main", remote, readback)
            if args.backfill:
                try:
                    git(readback, "merge-base", "--is-ancestor", head, "HEAD")
                except Refused as error:
                    raise Refused("cannot verify historical commit is reachable from public main") from error
            else:
                require(git(readback, "rev-parse", "HEAD").decode().strip() == head, "remote head differs")
            verify_files(readback, head, data)
        except Refused as error:
            raise Refused(f"read-back failed: {error}") from error
        git(work, "-c", "user.name="+name, "-c", "user.email="+email,
            "-c", "tag.gpgSign=false", "tag", "-a", tag, head, "-m", "OpenWiz "+args.version)
        git(work, "push", "--no-follow-tags", "--porcelain", remote, tag_ref+":"+tag_ref)
        tag_oid = git(work, "rev-parse", tag_ref).decode().strip()
        require(refs(work, remote, tag_ref, tag_ref+"^{}") == {tag_ref:tag_oid, tag_ref+"^{}":head},
                "remote annotated tag differs")
        notes = scratch/"entry.md"
        notes.write_text(entry, encoding="utf-8")
        env = git_env()
        env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1")
        command(["gh", "release", "create", tag, "--repo", github, "--verify-tag",
                 "--prerelease", "--title", "OpenWiz "+args.version, "--notes-file", notes],
                work, env, timeout=120)
        release_readback(work, github, tag, args.version, entry)
        require(refs(work, remote, tag_ref, tag_ref+"^{}") == {tag_ref:tag_oid, tag_ref+"^{}":head},
                "remote annotated tag moved after release")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["publish"])
    parser.add_argument("version")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--approval")
    parser.add_argument("--backfill", action="store_true",
                        help="tag and release the exact checked historical public commit; never push main")
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", args.version),
                "version must be N.N.N")
        publish(args)
    except (Refused, OSError, ValueError, TypeError) as error:
        print(f"release publish refused: {error}. If a write was attempted, inspect the remote "
              "before retrying; no later step or rollback was attempted.", file=sys.stderr)
        return 1
    print(f"release publish completed: v{args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
