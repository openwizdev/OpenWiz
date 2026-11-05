"""Gather reviewed changelog lines and R1's public roadmap for release check."""
import datetime
import json
from pathlib import Path
import re
import sys

from repository import repository
from check import blob, command, git_env, require, sha, shape, tree, unique

VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
GENERATED = {"CHANGELOG.md", "ROADMAP.md"}
# J6, Jake 2026-11-13: only the settled combined 0.0.6-0.0.12 release may exceed
# the five-line cap, in these sections and up to these counts; every entry stays
# verbatim, one result each. Five stays the cap for every other release
# ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6842773730)).
SETTLED_COMBINED = ("0.0.12", "0.0.11", "0.0.10", "0.0.9", "0.0.8", "0.0.7", "0.0.6")
CAP_EXCEPTIONS = {"0.0.6": 17, "0.0.8": 7, "0.0.9": 11, "0.0.11": 6, "0.0.12": 6}
ISSUE_JQ = ('{number, body, milestone: (.milestone | {number, title}), '
            'pull: (.pull_request != null), sub_issues: .sub_issues_summary.total}')


def sentence(value, label):
    require(isinstance(value, str) and value and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value) and value.splitlines() == [value]
            and value[-1] in ".!?" and not value.startswith(("#", "- ", "* ", ">")),
            f"entry: {label} must be one public sentence")
    return value


def entries(metadata, version):
    """The plan's entry: one object for the checked version, or a combined
    release's per-version list, newest first, starting at the checked version."""
    if isinstance(metadata, dict):
        validate(metadata)
        return [dict(metadata, version=version)]
    require(isinstance(metadata, list) and metadata, "entry: a combined release needs one entry per version")
    for item in metadata:
        shape(item, "version spec date tested")
        require(isinstance(item["version"], str) and re.fullmatch(VERSION, item["version"]),
                "entry: invalid version")
        validate({k: item[k] for k in ("spec", "date", "tested")})
    numbers = [tuple(map(int, item["version"].split("."))) for item in metadata]
    require(all(a > b for a, b in zip(numbers, numbers[1:])), "entry: versions must be newest first, each once")
    require(metadata[0]["version"] == version, "entry: first entry must be the checked version")
    return metadata


def validate(metadata):
    shape(metadata, "spec date tested")
    require(type(metadata["spec"]) is int and metadata["spec"] > 0, "entry: invalid spec number")
    date = metadata["date"]
    require(isinstance(date, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date),
            "entry: date must be ISO YYYY-MM-DD")
    datetime.date.fromisoformat(date)
    sentence(metadata["tested"], "tested/unproven line")


def cap(version, versions):
    """The line cap for one section of this release."""
    return CAP_EXCEPTIONS.get(version, 5) if tuple(versions) == SETTLED_COMBINED else 5


def issue(repo, number, unversioned=False):
    output = command(["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{number}", "--jq", ISSUE_JQ],
                     repo, git_env(), timeout=120)
    data = json.loads(output, object_pairs_hook=unique)
    shape(data, "number body milestone pull sub_issues")
    require(type(data["number"]) is int and data["number"] == number
            and data["pull"] is False and isinstance(data["body"], str)
            and type(data["sub_issues"]) is int and data["sub_issues"] >= 0,
            f"entry: invalid issue metadata for {number}")
    shape(data["milestone"], "number title")
    if unversioned and not (isinstance(data["milestone"]["title"], str)
                            and re.fullmatch(VERSION, data["milestone"]["title"])):
        # No milestone, or a non-version one (Design, Infra): it assigns no version.
        return dict(data, milestone=None)
    require(type(data["milestone"]["number"]) is int and data["milestone"]["number"] > 0
            and isinstance(data["milestone"]["title"], str)
            and re.fullmatch(VERSION, data["milestone"]["title"]),
            f"entry: ticket {number} has no version milestone")
    return data


def headline(body):
    sections = []
    current = None
    fence = None
    for line in body.splitlines():
        marker = re.match(r"\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            if current is not None:
                current.append(line)
            continue
        if fence is not None:
            continue
        if re.match(r"^#{1,2} ", line):
            current = None
            if line == "## Changelog headline":
                current = []
                sections.append(current)
        elif current is not None and line.strip():
            current.append(line)
    require(len(sections) == 1 and len(sections[0]) == 1, "entry: spec needs one Changelog headline")
    return sentence(sections[0][0], "headline")


def prepend(old, entry, version):
    text = old.decode("utf-8")
    headers = list(re.finditer(r"^[ ]{0,3}##[ \t]+([^\r\n]*)", text, re.M))
    preamble = text[:headers[0].start()] if headers else text
    lines = preamble.splitlines()
    require(not any(previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)
                    for previous, line in zip(lines, lines[1:])),
            "entry: unrecognized published changelog")
    wanted = tuple(map(int, version.split(".")))
    for header in headers:
        match = re.match(r"\[?"+VERSION+r"(?:\]|\s|$)", header[1])
        require(match is not None, "entry: unrecognized published version heading")
        published = tuple(int(n) for n in match.groups())
        require(published != wanted, "entry: version already published")
        require(published < wanted, "entry: version must be newer than published entries")
    if headers:
        # Keep both the preamble and every older entry's bytes, including CRLF.
        index = len(text[:headers[0].start()].encode("utf-8"))
        return old[:index] + entry.encode("utf-8") + b"\n" + old[index:]
    require(not text.strip() or text.strip() == "# Changelog", "entry: unrecognized published changelog")
    return (old.rstrip(b"\r\n") or b"# Changelog") + b"\n\n" + entry.encode("utf-8")


def version_entry(check, source, metadata, tickets, versions=()):
    """One version's section and its included sources, in numeric ticket order."""
    a = check.args
    version = metadata["version"]
    spec = issue(a.repo, metadata["spec"])
    require(spec["milestone"]["title"] == version and spec["sub_issues"] > 0,
            "entry: spec milestone/version mismatch or not a parent spec")
    title = headline(spec["body"])
    changes = []
    for number, path, data in tickets:
        if data["milestone"] is None or data["milestone"]["title"] != version:
            continue
        require(data["milestone"]["number"] == spec["milestone"]["number"]
                and data["sub_issues"] == 0, f"entry: invalid ticket milestone for {path}")
        raw = blob(a.repo, source, path)
        text = raw.decode("utf-8")
        found = re.fullmatch(r"kind: (added|changed|fixed|removed|security)\n\n([^\r\n]+)\n", text)
        require(found is not None, f"entry: invalid changelog format in {path}")
        changes.append((number, path, sentence(found[2], path), sha(raw)))
    changes.sort()
    limit = cap(version, versions)
    require(len(changes) <= limit, f"entry: more than {'five' if limit == 5 else limit} changelog lines: "
            + ", ".join(c[1] for c in changes))
    if not changes:
        # HL1: a confirmed headline with no outcome entries is its dated heading and
        # headline alone; a version with neither is refused by headline() above.
        return f'## {version} · {metadata["date"]}\n\n{title}\n', []
    # J14, Jake 2026-11-13: in the settled combined release every footer links to
    # its one published release, v0.0.12; every other release keeps its own tag
    # ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6843587744)).
    tag = SETTLED_COMBINED[0] if tuple(versions) == SETTLED_COMBINED else version
    section = (f'## {version} · {metadata["date"]}\n\n{title}\n\n'
               + "".join(f"- {c[2]}\n" for c in changes)
               + f'\n{metadata["tested"]}\n\n'
               + f"[Full release on GitHub](https://github.com/{repository(a.repo)}/releases/tag/v{tag})\n")
    return section, [{"path": c[1], "sha256": c[3], "sentence": c[2]} for c in changes]


def exclusions(rows):
    """Recorded unassigned sources: each exact path and bytes, with its reason."""
    require(isinstance(rows, list), "entry: exclusions must be a list")
    excluded = {}
    for row in rows:
        shape(row, "path sha256 reason")
        require(isinstance(row["path"], str) and re.fullmatch(r"changes/[1-9][0-9]*\.md", row["path"])
                and row["path"] not in excluded and isinstance(row["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                and isinstance(row["reason"], str) and row["reason"].strip(),
                "entry: invalid exclusion")
        excluded[row["path"]] = row["sha256"]
    return excluded


def sections(check, source, versions, excluded):
    """Every version's section, newest first, from changes/ at source."""
    a = check.args
    tickets = []
    for path in tree(a.repo, source, ["changes"]):
        if path == "changes/README.md":
            continue
        match = re.fullmatch(r"changes/([1-9][0-9]*)\.md", path)
        require(match is not None, f"entry: invalid changelog filename {path}")
        if path in excluded:
            # A recorded unassigned source: exact bytes, still without a version.
            require(sha(blob(a.repo, source, path)) == excluded[path], f"entry: excluded source changed: {path}")
            data = issue(a.repo, int(match[1]), unversioned=True)
            require(data["milestone"] is None, f"entry: excluded source has a version milestone: {path}")
            continue
        tickets.append((int(match[1]), path, issue(a.repo, int(match[1]))))
    missing = sorted(set(excluded) - set(tree(a.repo, source, ["changes"])))
    require(not missing, "entry: excluded source missing: " + ", ".join(missing))
    names = [v["version"] for v in versions]
    built = [version_entry(check, source, metadata, tickets, names) for metadata in versions]
    return [b[0] for b in built], {v["version"]: b[1] for v, b in zip(versions, built)}


def generate(check, source, base_files):
    a = check.args
    versions = entries(check.plan["entry"], a.version)
    old = blob(a.public_repo, check.plan["public_base"], "CHANGELOG.md") if "CHANGELOG.md" in base_files else b""
    # Every new version must be newer than every published one: check the
    # oldest, before any GitHub read for its spec.
    prepend(old, "", versions[-1]["version"])
    # One entry per version, newest first, each from its own spec and lines.
    text = "\n".join(sections(check, source, versions, {})[0])
    changelog = prepend(old, text, versions[-1]["version"])
    roadmap = a.staging / "ROADMAP.md"
    command([sys.executable, Path(__file__).resolve().parents[1]/"roadmap/roadmap.py",
             "--root", a.repo, "--public-repo", repository(a.repo), "--public", roadmap], a.repo, git_env(), timeout=600,
            log=a.evidence/"roadmap.log")
    check.entry_text = text
    return {"CHANGELOG.md": changelog, "ROADMAP.md": roadmap.read_bytes()}
