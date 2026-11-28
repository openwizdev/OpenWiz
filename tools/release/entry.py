import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import datetime
import json
import re

from repository import repository
from check import Refused, blob, command, git, git_env, require, sha, shape, tree, unique

VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
GENERATED = {"CHANGELOG.md", "ROADMAP.md"}
# J6, Jake 2026-11-13: only the settled combined 0.0.6-0.0.12 release may exceed
# the five-line cap, in these sections and up to these counts; every entry stays
# verbatim, one result each. Five stays the cap for every other release
# ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6842773730)).
SETTLED_COMBINED = ("0.0.12", "0.0.11", "0.0.10", "0.0.9", "0.0.8", "0.0.7", "0.0.6")
CAP_EXCEPTIONS = {"0.0.6": 17, "0.0.8": 7, "0.0.9": 11, "0.0.11": 6, "0.0.12": 6}
CHANGE = r"changes/(closedwiz-)?([1-9][0-9]*)\.md"
MOVED_SCHEMA = "openwiz.moved-changes.v1"
WAS = r"was \[?ClosedWiz #{}(?![0-9])"
NEW, UNDER = "**What's new for you**", "**Under the hood**"
PUBLIC_LINK = re.compile(r"https://github\.com/openwizdev/openwiz(?:[/?#][^\s()<>\]]*)?", re.I)
ISSUE_JQ = ('{number, body, milestone: (.milestone | {number, title}), '
            'pull: (.pull_request != null), sub_issues: .sub_issues_summary.total}')


def sentence(value, label):
    require(isinstance(value, str) and value and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value) and value.splitlines() == [value]
            and value[-1] in ".!?" and not value.startswith(("#", "- ", "* ", ">")),
            f"entry: {label} must be one public sentence")
    return value


def entries(metadata, version):
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


def preamble_check(preamble):
    lines = preamble.splitlines()
    require(not any(previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)
                    for previous, line in zip(lines, lines[1:])),
            "entry: unrecognized published changelog")


def prepend(old, entry, version):
    text = old.decode("utf-8")
    headers = list(re.finditer(r"^[ ]{0,3}##[ \t]+([^\r\n]*)", text, re.M))
    preamble_check(text[:headers[0].start()] if headers else text)
    wanted = tuple(map(int, version.split(".")))
    for header in headers:
        match = re.match(r"\[?"+VERSION+r"(?:\]|\s|$)", header[1])
        require(match is not None, "entry: unrecognized published version heading")
        published = tuple(int(n) for n in match.groups())
        require(published != wanted, "entry: version already published")
        require(published < wanted, "entry: version must be newer than published entries")
    if headers:
        index = len(text[:headers[0].start()].encode("utf-8"))
        return old[:index] + entry.encode("utf-8") + b"\n" + old[index:]
    require(not text.strip() or text.strip() == "# Changelog", "entry: unrecognized published changelog")
    return (old.rstrip(b"\r\n") or b"# Changelog") + b"\n\n" + entry.encode("utf-8")


def version_entry(check, source, metadata, tickets, versions=()):
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
    require(isinstance(rows, list), "entry: exclusions must be a list")
    excluded = {}
    for row in rows:
        shape(row, "path sha256 reason")
        require(isinstance(row["path"], str) and re.fullmatch(CHANGE, row["path"])
                and row["path"] not in excluded and isinstance(row["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                and isinstance(row["reason"], str) and row["reason"].strip(),
                "entry: invalid exclusion")
        excluded[row["path"]] = row["sha256"]
    return excluded


def moved(doc):
    require(isinstance(doc, dict) and set(doc) == {"schema", "moved"} and doc["schema"] == MOVED_SCHEMA
            and isinstance(doc["moved"], list), "entry: invalid moved-number map")
    rows = {}
    for row in doc["moved"]:
        require(isinstance(row, dict) and set(row) == {"closedwiz", "openwiz", "sha256"}
                and type(row["closedwiz"]) is int and row["closedwiz"] > 0 and row["closedwiz"] not in rows
                and (row["openwiz"] is None or type(row["openwiz"]) is int and row["openwiz"] > 0)
                and isinstance(row["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
                "entry: invalid moved-number map")
        rows[row["closedwiz"]] = (row["openwiz"], row["sha256"])
    targets = [t for t, _ in rows.values() if t is not None]
    require(len(targets) == len(set(targets)), "entry: invalid moved-number map")
    return rows


MOVED = moved(json.loads((Path(__file__).resolve().parent / "moved.json").read_text(), object_pairs_hook=unique))


def source_lines(check, source, excluded, only=None, allow_moved_renames=False):
    a = check.args
    paths = tree(a.repo, source, ["changes"])
    universe = paths if only is None else only
    lines = {}
    for path in universe:
        if path != "changes/README.md" and not path.startswith("changes/notes/"):
            lines[path] = re.fullmatch(CHANGE, path)
            require(lines[path] is not None, f"entry: invalid changelog filename {path}")
            if only is not None:
                require(path in paths, f"entry: missing changelog source {path}")
    tickets = []
    for path, match in lines.items():
        number = int(match[2])
        old = bool(match[1]) or (number in MOVED and f"changes/closedwiz-{number}.md" not in paths)
        lookup = number
        if old:
            require(number in MOVED, f"entry: {path}: ClosedWiz #{number} is not in the moved-number map")
            lookup = MOVED[number][0]
            if allow_moved_renames and match[1]:
                require(sha(blob(a.repo, source, path)) == MOVED[number][1],
                        f"entry: {path} does not match the moved ClosedWiz #{number} line")
                continue
            require(match[1] or sha(blob(a.repo, source, path)) == MOVED[number][1],
                    f"entry: {path} is not the moved ClosedWiz #{number} line: rename the moved line "
                    f"changes/closedwiz-{number}.md, or record its new bytes in the moved-number map")
        if path in excluded:
            require(sha(blob(a.repo, source, path)) == excluded[path], f"entry: excluded source changed: {path}")
            if lookup is not None:
                data = moved_issue(a.repo, lookup, number if old else None, unversioned=True)
                require(data["milestone"] is None, f"entry: excluded source has a version milestone: {path}")
            continue
        require(lookup is not None, f"entry: {path}: ClosedWiz #{number} has no OpenWiz ticket: "
                "record it as an exclusion")
        tickets.append((number, path, moved_issue(a.repo, lookup, number if old else None)))
    return paths, tickets


def changed_changelog_paths(repo, base, source, directory):
    output = git(repo, "diff", "--name-only", "--diff-filter=ACMR", "-M", base, source, "--", directory)
    return [line for line in output.decode("utf-8").splitlines() if line]


def sections(check, source, versions, excluded):
    paths, tickets = source_lines(check, source, excluded)
    missing = sorted(set(excluded) - set(paths))
    require(not missing, "entry: excluded source missing: " + ", ".join(missing))
    names = [v["version"] for v in versions]
    built = [version_entry(check, source, metadata, tickets, names) for metadata in versions]
    return [b[0] for b in built], {v["version"]: b[1] for v, b in zip(versions, built)}


def moved_issue(repo, number, closedwiz=None, unversioned=False):
    data = issue(repo, number, unversioned)
    require(closedwiz is None or re.search(WAS.format(closedwiz), data["body"]),
            f"entry: OpenWiz #{number} does not say it was ClosedWiz #{closedwiz}")
    return data


def curated(text, included, tags=()):
    require(isinstance(text, str) and "\r" not in text and text.endswith("\n") and not text.endswith("\n\n"),
            "entry: curated notes are LF text ending in one newline")
    lines = text[:-1].split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    require(starts, "entry: curated notes have no version section")
    preamble = lines[:starts[0]]
    require(preamble[:2] == ["# Changelog", ""] and preamble[-1] == ""
            and all(line and not line.startswith(("#", "- ")) for line in preamble[2:-1]),
            "entry: curated notes start with # Changelog and at most one plain paragraph")
    published = max((tuple(map(int, t[1:].split("."))) for t in tags if re.fullmatch("v" + VERSION, t)), default=None)
    found, fresh = [], len(lines)
    for k, start in enumerate(starts):
        end = starts[k + 1] - 1 if k + 1 < len(starts) else len(lines)
        require(k + 1 == len(starts) or lines[end] == "", "entry: curated sections are separated by one blank line")
        old = re.match(r"## " + VERSION + " ", lines[start])
        if published and old and tuple(map(int, old.groups())) <= published:
            fresh = min(fresh, start)
            found.append(".".join(old.groups()))
        else:
            found.append(curated_section(lines[start:end]))
    numbers = [tuple(map(int, v.split("."))) for v in found]
    require(all(x > y for x, y in zip(numbers, numbers[1:])), "entry: curated versions must be newest first, each once")
    require(isinstance(included, list) and included and found[:len(included)] == included,
            "entry: curated notes must start with the included versions, in order")
    text, whole = "\n".join(lines[:fresh]) + "\n", text
    require(not re.search(r"<[A-Za-z/!]|^ {0,3}\[[^\]]*\]:", re.sub(r"`[^`\n]*`", "", text), re.M),
            "entry: curated notes allow only inline links")
    for target in re.findall(r"\]\(([^)]*)\)", text):
        require(PUBLIC_LINK.fullmatch(target), f"entry: curated link is not to openwizdev/OpenWiz: {target}")
    for token in re.findall(r"(?i)(?:[a-z][a-z0-9+.-]*:)?//[^\s()<>\]]*|www\.[^\s()<>\]]*|mailto:[^\s()<>\]]*"
                            r"|github\.com[^\s()<>\]]*", text):
        require(PUBLIC_LINK.fullmatch(token), f"entry: curated link is not to openwizdev/OpenWiz: {token}")
    for tag in re.findall(r"(?i)/releases/tag/([^\s()<>\]/?#]+)", text):
        require(tag == "v" + included[0] or tag in tags, f"entry: curated link to a tag that will not exist: {tag}")
    offset = [0]
    for line in lines:
        offset.append(offset[-1] + len(line) + 1)
    end = offset[starts[len(included)]] if len(found) > len(included) else len(whole)
    return found, whole[offset[starts[0]]:end].rstrip("\n") + "\n"


def curated_section(lines):
    match = re.fullmatch(r"## " + VERSION + r" · ([0-9]{4}-[0-9]{2}-[0-9]{2})", lines[0])
    require(match is not None, f"entry: invalid curated heading: {lines[0]}")
    version = ".".join(match.groups()[:3])
    try:
        datetime.date.fromisoformat(match[4])
    except ValueError:
        raise Refused(f"entry: invalid curated heading: {lines[0]}") from None
    rest = lines[1:]
    require(len(rest) >= 2 and rest[0] == "" and re.fullmatch(r"\*\*[^*\s][^*]*[^*\s]\*\*", rest[1])
            and rest[1] not in (NEW, UNDER), f"entry: {version} needs its bold headline here")
    del rest[:2]

    def part(title, low, high):
        name = title.strip("*")
        require(rest[:3] == ["", title, ""], f"entry: {version} needs {name} here")
        del rest[:3]
        found = []
        while rest and rest[0].startswith("- "):
            found.append(sentence(rest.pop(0)[2:], f"{version} {name} line"))
        require(low <= len(found) <= high, f"entry: {version} {name} needs {low} to {high} lines")
        return found

    require(not any("fixture" in line.lower() for line in part(NEW, 2, 4)),
            f"entry: {version} What's new for you carries a fixture caveat: say it once in the footer")
    require(len(rest) >= 2 and rest[0] == "" and rest[1] != UNDER,
            f"entry: {version} needs one footer line after What's new for you")
    sentence(rest[1], f"{version} footer")
    del rest[:2]
    part(UNDER, 1, 5)
    if rest:
        require(len(rest) == 2 and rest[0] == "" and re.fullmatch(r"\[[^\[\]]+\]\([^()\s]+\)", rest[1]),
                f"entry: {version} has text after Under the hood")
    require(sum(line.removeprefix("- ").startswith("Tested ") for line in lines) <= 1,
            f"entry: {version} says how it was tested more than once")
    return version


def compose(old, text, restate=False):
    oldest = re.findall(r"^## " + VERSION + " ", text, re.M)[-1]
    if restate:
        s = old.decode("utf-8")
        headers = list(re.finditer(r"^[ ]{0,3}##[ \t]+([^\r\n]*)", s, re.M))
        kept = []
        for header in headers:
            match = re.match(r"\[?" + VERSION + r"(?:\]|\s|$)", header[1])
            require(match is not None, "entry: unrecognized published version heading")
            if tuple(int(n) for n in match.groups()) < tuple(map(int, oldest)):
                kept.append(header)
        if headers:
            at = lambda h: len(s[:h.start()].encode("utf-8"))
            preamble = old[:at(headers[0])]
            if not kept:
                preamble_check(preamble.decode("utf-8"))
                return preamble.rstrip(b"\r\n") + b"\n\n" + text.encode("utf-8")
            old = preamble + old[at(kept[0]):]
    return prepend(old, text, ".".join(oldest))


def generate(check, source, base_files):
    a = check.args
    versions = entries(check.plan["entry"], a.version)
    old = blob(a.public_repo, check.plan["public_base"], "CHANGELOG.md") if "CHANGELOG.md" in base_files else b""
    prepend(old, "", versions[-1]["version"])
    text = "\n".join(sections(check, source, versions, {})[0])
    changelog = prepend(old, text, versions[-1]["version"])
    roadmap = a.staging / "ROADMAP.md"
    command([sys.executable, Path(__file__).resolve().parents[1]/"roadmap/roadmap.py",
             "--root", a.repo, "--public-repo", repository(a.repo), "--public", roadmap], a.repo, git_env(), timeout=600,
            log=a.evidence/"roadmap.log")
    check.entry_text = text
    return {"CHANGELOG.md": changelog, "ROADMAP.md": roadmap.read_bytes()}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="entry.py", description="Check changes/ lines for a version milestone.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", help="with a changes directory, check lines that differ from this commit")
    parser.add_argument("--source", default="HEAD")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    repo = str(Path(args.repo).resolve())
    selected = []
    for path in args.paths:
        normalized = path[2:] if path.startswith("./") else path
        if normalized in {"changes", "changes/"} or normalized.endswith("/"):
            require(args.base, "entry: checking a changes directory needs --base")
            selected.extend(changed_changelog_paths(repo, args.base, args.source, normalized.rstrip("/")))
        else:
            selected.append(normalized)
    ordered = []
    for path in selected:
        if path == "changes/README.md" or path.startswith("changes/notes/"):
            continue
        if path not in ordered:
            ordered.append(path)
    if not ordered:
        print("entry: pass (no changed changelog line)")
        return 0
    check = argparse.Namespace(args=argparse.Namespace(repo=repo))
    source_lines(check, args.source, {}, only=ordered, allow_moved_renames=True)
    noun = "changelog line" if len(ordered) == 1 else "changelog lines"
    print(f"entry: pass ({len(ordered)} {noun})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as error:
        print(error, file=sys.stderr)
        sys.exit(1)
