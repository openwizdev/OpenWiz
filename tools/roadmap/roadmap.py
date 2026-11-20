#!/usr/bin/env python3
"""The roadmap generator (ClosedWiz#277, spec #276, R1).

Reads GitHub's milestones over REST and rewrites only the marked, generated
parts of docs/ROADMAP.md (the Now and Next table and its picture); with
--public FILE, writes only the short public roadmap to FILE instead. See README.md beside this file.

    python3 tools/roadmap/roadmap.py [--root DIR] [--public FILE] [--public-repo OWNER/NAME]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Where release publish tags each version, unless --public-repo says otherwise.
# Every other read is of the clone the tool runs in ({owner}/{repo}).
PUBLIC_REPO = "jparker2006/OpenWiz"
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
LANES = ("Infra", "0.0.X")  # milestones that are never versions
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
NOW = ("building", "built", "live-checked")
NEXT = ("being grilled",)
ISSUE_STATES = ("open", "closed")
GITHUB_URL = re.compile(r"https://github\.com/[A-Za-z0-9._/-]+")
GRILL = re.compile(r"docs/grills/([A-Za-z0-9][A-Za-z0-9._-]*\.md)")
TICKET = re.compile(r"#([1-9][0-9]*)(?![0-9A-Za-z])")

MILESTONES_JQ = ".[] | {number, title, description, html_url}"
ISSUES_JQ = (".[] | select(.pull_request == null)"
             " | {number, state, state_reason, sub_issues: .sub_issues_summary.total, html_url}")
REFS_JQ = ".[].ref"
TICKET_JQ = "{number, state, state_reason, pull: (.pull_request != null), html_url}"

# The public roadmap's lines: only these characters, no token that mixes
# letters and digits, and no word with a capital letter in it but these. Anything else stops
# --public: a guard that can't tell a name from a word refuses both.
PUBLIC_CHARS = re.compile(r"[A-Za-z0-9 .,;:!?'\"()\-’“”—–…]")
PUBLIC_WORDS = ("You", "OpenWiz", "CloudRoom", "GitHub", "Mac", "PC")

ROADMAP_REGIONS = ("now-next", "picture")


class Fail(Exception):
    """Something could not be read or written: stop, and write nothing."""


class HalfWritten(Fail):
    """A page could not be put in place after others were: say which."""


def gh(root, path, jq, paginate=True):
    """One read through `gh api`; its standard output."""
    args = ["gh", "api", *(["--paginate"] if paginate else []), path, "--jq", jq]
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise Fail(f"could not run gh for {path}: {e}") from None
    if proc.returncode != 0:
        why = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Fail(f"gh failed reading {path} (exit {proc.returncode}): {why[0] if why else 'no message'}")
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise Fail(f"gh's answer for {path} is not UTF-8") from None


def lines_of(text, what):
    """The answer's lines; an empty answer has none, and a blank line is refused."""
    if text == "":
        return []
    if not text.endswith("\n"):
        raise Fail(f"{what}: the answer doesn't end with a newline")
    lines = text[:-1].split("\n")
    if any(line == "" for line in lines):
        raise Fail(f"{what}: a blank line in the answer")
    return lines


def no_repeats(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Fail("a repeated key")
    return dict(pairs)


def objects(text, what, shape):
    """One JSON object per line, each with exactly SHAPE's keys, each of its type."""
    out = []
    for line in lines_of(text, what):
        try:
            obj = json.loads(line, object_pairs_hook=no_repeats)
        except Fail as e:
            raise Fail(f"{what}: {e} in {line[:80]}") from None
        except ValueError:
            raise Fail(f"{what}: not JSON: {line[:80]}") from None
        if not isinstance(obj, dict) or set(obj) != set(shape):
            raise Fail(f"{what}: not exactly the keys {', '.join(sorted(shape))}: {line[:80]}")
        for key, ok in shape.items():
            if not ok(obj[key]):
                raise Fail(f"{what}: a bad {key}: {line[:80]}")
        out.append(obj)
    return out


def refs(text, what, prefix):
    out = lines_of(text, what)
    for ref in out:
        if not ref.startswith(prefix):
            raise Fail(f"{what}: a ref outside {prefix}: {ref[:80]}")
    return set(out)


def number(v):
    return type(v) is int and v > 0


def string(v):
    return type(v) is str


def url(v):
    return type(v) is str and GITHUB_URL.fullmatch(v) is not None


def read_github(root, public_repo=PUBLIC_REPO):
    milestones = objects(
        gh(root, "repos/{owner}/{repo}/milestones?state=all&per_page=100", MILESTONES_JQ),
        "milestones",
        {"number": number, "title": string, "description": lambda v: v is None or string(v), "html_url": url})
    heads = refs(gh(root, "repos/{owner}/{repo}/git/matching-refs/heads/release-", REFS_JQ),
                 "release branches", "refs/heads/release-")
    tags = refs(gh(root, f"repos/{public_repo}/git/matching-refs/tags/v", REFS_JQ),
                "public tags", "refs/tags/v")

    versions = []
    for m in milestones:
        match = VERSION.fullmatch(m["title"])
        if m["title"] in LANES:
            continue
        if not match:
            raise Fail(f"milestone {m['title']!r} is neither a version (N.N.N) nor a lane ({', '.join(LANES)})")
        versions.append((tuple(int(p) for p in match.groups()), m))
    versions.sort(key=lambda pair: pair[0])
    for (a, _), (b, m) in zip(versions, versions[1:]):
        if a == b:
            raise Fail(f"two milestones are called {m['title']}")

    out, problems = [], []
    for _, m in versions:
        issues = objects(
            gh(root, f"repos/{{owner}}/{{repo}}/issues?milestone={m['number']}&state=all&per_page=100", ISSUES_JQ),
            f"milestone {m['title']}'s issues",
            {"number": number, "state": lambda v: v in ISSUE_STATES, "state_reason": lambda v: v is None or string(v),
             "sub_issues": lambda v: type(v) is int and v >= 0, "html_url": url})
        v = version(m, issues, heads, tags, lambda n: live_check(root, m["title"], n, problems), problems)
        out.append(v)
    return out, problems


def live_check(root, title, n, problems):
    """The ticket #N, read by number wherever it is; None if it's a pull request."""
    found = objects(gh(root, f"repos/{{owner}}/{{repo}}/issues/{n}", TICKET_JQ, paginate=False),
                    f"{title}'s live-check ticket #{n}",
                    {"number": lambda v: number(v) and v == n, "state": lambda v: v in ISSUE_STATES,
                     "state_reason": lambda v: v is None or string(v), "pull": lambda v: type(v) is bool,
                     "html_url": url})
    if len(found) != 1:
        raise Fail(f"{title}'s live-check ticket #{n}: {len(found)} answers (one is needed)")
    if found[0]["pull"]:
        problems.append(f"{title}: its live-check ticket #{n} is a pull request")
        return None
    return found[0]


def version(m, issues, heads, tags, read_ticket, problems):
    """One version: its lines, links and state, as GitHub says."""
    title = m["title"]
    desc = (m["description"] or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in desc.split("\n")]
    outcome = [line for line in lines if line.startswith("You can ")]
    done = [line for line in lines if line.startswith("Done when ")]
    for found, words in ((outcome, "You can …"), (done, "Done when …")):
        if not found:
            problems.append(f'{title}: no "{words}" line in its milestone')
        elif len(found) > 1:
            problems.append(f'{title}: {len(found)} "{words}" lines in its milestone')
    grills = list(dict.fromkeys(GRILL.findall(desc)))
    specs = sorted((i for i in issues if i["sub_issues"] > 0), key=lambda i: i["number"])

    live = None
    if len(done) == 1:
        named = TICKET.search(done[0])
        if named:
            live = read_ticket(int(named.group(1)))

    if f"refs/tags/v{title}" in tags:
        state = "published"
    elif live and live["state"] == "closed" and live["state_reason"] == "completed":
        state = "live-checked"
    elif f"refs/heads/release-{title}" in heads:
        state = "built"
    elif specs:
        state = "building"
    else:
        state = "being grilled"
    return {"title": title, "url": m["html_url"], "state": state, "outcome": outcome, "done": done,
            "specs": specs, "live": live, "grills": grills}


def cell(found):
    """A line for a table cell; never a guess when there isn't exactly one."""
    if len(found) == 1:
        return found[0].replace("|", "\\|")
    return "_missing_" if not found else f"_missing ({len(found)} lines)_"


def links(v, grill_dir):
    parts = [f"[milestone]({v['url']})"]
    parts += [f"spec [#{s['number']}]({s['html_url']})" for s in v["specs"]]
    if v["live"]:
        parts.append(f"live check [#{v['live']['number']}]({v['live']['html_url']})")
    parts += [f"[grill]({grill_dir}{g})" for g in v["grills"]]
    return " · ".join(parts)


def now_next_table(versions):
    rows = ["| Horizon | Version | State | You can … | Done when … | Links |",
            "| --- | --- | --- | --- | --- | --- |"]
    for horizon, states in (("Now", NOW), ("Next", NEXT)):
        for v in versions:
            if v["state"] in states:
                rows.append(f"| {horizon} | {v['title']} | {v['state']} | {cell(v['outcome'])} | "
                            f"{cell(v['done'])} | {links(v, 'grills/')} |")
    return "\n".join(rows)


def node(v):
    return "v" + v["title"].replace(".", "_")


def picture(versions):
    lines = ["```mermaid", "flowchart LR"]
    chain = []
    for key, name, states in (("now", "Now", NOW), ("next", "Next", NEXT)):
        group = [v for v in versions if v["state"] in states]
        if group:
            lines.append(f'  subgraph {key} ["{name}"]')
            lines += [f'    {node(v)}["{v["title"]}: {v["state"]}"]' for v in group]
            lines.append("  end")
            chain += group
    if len(chain) > 1:
        lines.append("  " + " --> ".join(node(v) for v in chain))
    lines.append("```")
    return "\n".join(lines)


def public_holds(line):
    """What in LINE can't go public, or None."""
    for ch in line:
        if not PUBLIC_CHARS.fullmatch(ch):
            return f'the character "{ch}"'
    for token in re.findall(r"[A-Za-z0-9]+", line):
        if re.search(r"[A-Za-z]", token) and re.search(r"[0-9]", token):
            return f'the token "{token}", which mixes letters and digits'
    for word in re.findall(r"[A-Za-z]+", line):
        if any(c.isupper() for c in word) and word not in PUBLIC_WORDS:
            return f'the word "{word}", which isn\'t on the public word list'
    return None


def public_page(versions):
    """The short public roadmap: Now and Next, one line each, from each
    version's number, state and "You can …" line only."""
    out = ["# OpenWiz roadmap", "", "What is being built now, and what comes next."]
    for horizon, states in (("Now", NOW), ("Next", NEXT)):
        out += ["", f"## {horizon}", ""]
        group = [v for v in versions if v["state"] in states]
        for v in group:
            if len(v["outcome"]) != 1:
                raise Fail(f'--public: {v["title"]} has no single "You can …" line')
            holds = public_holds(v["outcome"][0])
            if holds:
                raise Fail(f'--public: {v["title"]}\'s "You can …" line holds {holds}')
            out.append(f"- **{v['title']}**, {v['state']}: {v['outcome'][0]}")
        if not group:
            out.append("- None right now.")
    return "\n".join(out) + "\n"


def read_page(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"could not read {path}: {e}") from None


def spans(text, names, label):
    """Where each named region's body lies, as line indexes (begin, end)."""
    lines = text.split("\n")
    found = {}
    for name in names:
        at = []
        for marker in (f"<!-- roadmap:{name}:begin -->", f"<!-- roadmap:{name}:end -->"):
            hits = [i for i, line in enumerate(lines) if line == marker]
            if len(hits) != 1:
                raise Fail(f"{label}: {len(hits)} lines are exactly {marker} (one is needed)")
            at.append(hits[0])
        if at[0] > at[1]:
            raise Fail(f"{label}: the {name} region ends before it begins")
        for other, (begin, end) in found.items():
            if not (end < at[0] or at[1] < begin):
                raise Fail(f"{label}: the {other} and {name} regions overlap")
        found[name] = tuple(at)
    return lines, found


def fill(text, bodies, label):
    """TEXT with each region's body replaced; every other line kept exactly."""
    lines, found = spans(text, list(bodies), label)
    for name, (begin, end) in sorted(found.items(), key=lambda kv: -kv[1][0]):
        lines[begin + 1:end] = bodies[name].split("\n")
    return "\n".join(lines)


def stage(path, text):
    """TEXT in a new file beside PATH, with PATH's mode; None if PATH holds TEXT already."""
    tmp = None
    try:
        exists = path.exists()
        if exists and read_page(path) == text:
            return None
        if exists:
            mode = path.stat().st_mode & 0o7777
        else:
            umask = os.umask(0o022)
            os.umask(umask)
            mode = 0o666 & ~umask
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        return tmp
    except OSError as e:
        if tmp:
            os.unlink(tmp)
        raise Fail(f"could not write {path}: {e}") from None


def write_pages(targets, new):
    """Every page staged first, then each put in place: one that can't be
    staged leaves every page as it was."""
    staged = []
    try:
        for name, path in targets.items():
            staged.append((name, path, stage(path, new[name])))
    except Fail:
        for _, _, tmp in staged:
            if tmp:
                os.unlink(tmp)
        raise
    report, done = [], []
    for i, (name, path, tmp) in enumerate(staged):
        if tmp:
            try:
                os.replace(tmp, path)
            except OSError as e:
                for _, _, rest in staged[i:]:
                    if rest:
                        os.unlink(rest)
                raise HalfWritten(f"could not write {path}: {e}; already written: {', '.join(done) or 'none'}") from None
            done.append(name)
        report.append(f"{name}: {'updated' if tmp else 'unchanged'}")
    return report


def repo_arg(value):
    if REPO.fullmatch(value) is None or value.split("/")[1] in (".", ".."):
        raise argparse.ArgumentTypeError(f"{value!r} is not OWNER/NAME")
    return value


def main(argv):
    parser = argparse.ArgumentParser(prog="roadmap.py", description=__doc__.split("\n\n")[1])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                        help="the repository's root (default: the one holding this script)")
    parser.add_argument("--public", metavar="FILE",
                        help="write only the short public roadmap, to FILE; the pages stay as they are")
    parser.add_argument("--public-repo", metavar="OWNER/NAME", type=repo_arg, default=PUBLIC_REPO,
                        help=f"the public repository whose v<version> tags mark published versions (default {PUBLIC_REPO})")
    args = parser.parse_args(argv)
    root = Path(args.root)
    pages = {"docs/ROADMAP.md": ROADMAP_REGIONS}
    try:
        if args.public:
            versions, problems = read_github(root, args.public_repo)
            new = {args.public: public_page(versions)}
            targets = {args.public: Path(args.public)}
        else:
            old = {name: read_page(root / name) for name in pages}
            for name, regions in pages.items():
                spans(old[name], regions, name)
            versions, problems = read_github(root, args.public_repo)
            new = {
                "docs/ROADMAP.md": fill(old["docs/ROADMAP.md"], {"now-next": now_next_table(versions),
                                                               "picture": picture(versions)}, "docs/ROADMAP.md"),
            }
            targets = {name: root / name for name in pages}
        report = write_pages(targets, new)
    except HalfWritten as e:
        print(f"roadmap: {e}", file=sys.stderr)
        return 1
    except Fail as e:
        print(f"roadmap: {e}; nothing written", file=sys.stderr)
        return 1
    print("\n".join(report))
    for problem in problems:
        print(f"roadmap: {problem}", file=sys.stderr)
    return 3 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
