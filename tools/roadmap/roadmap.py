#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DESCRIPTION = """Reads GitHub's milestones over REST and writes the short public roadmap to
the --public FILE. See README.md beside this file."""

PUBLIC_REPO = "jparker2006/OpenWiz"
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
LANES = ("Infra", "0.0.X")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
NOW = ("building", "built", "live-checked")
NEXT = ("being grilled",)
ISSUE_STATES = ("open", "closed")
GITHUB_URL = re.compile(r"https://github\.com/[A-Za-z0-9._/-]+")
TICKET = re.compile(r"#([1-9][0-9]*)(?![0-9A-Za-z])")

MILESTONES_JQ = ".[] | {number, title, description, html_url}"
ISSUES_JQ = (".[] | select(.pull_request == null)"
             " | {number, state, state_reason, sub_issues: .sub_issues_summary.total, html_url}")
REFS_JQ = ".[].ref"
TICKET_JQ = "{number, state, state_reason, pull: (.pull_request != null), html_url}"

PUBLIC_CHARS = re.compile(r"[A-Za-z0-9 .,;:!?'\"()\-’“”—–…]")
PUBLIC_WORDS = ("You", "OpenWiz", "CloudRoom", "GitHub", "Mac", "PC")


class Fail(Exception):
    pass


class HalfWritten(Fail):
    pass


def gh(root, path, jq, paginate=True):
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
    return {"title": title, "state": state, "outcome": outcome}


def public_holds(line):
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


def stage(path, text):
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
    parser = argparse.ArgumentParser(prog="roadmap.py", description=DESCRIPTION)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                        help="the repository's root (default: the one holding this script)")
    parser.add_argument("--public", metavar="FILE", required=True,
                        help="write the short public roadmap to FILE")
    parser.add_argument("--public-repo", metavar="OWNER/NAME", type=repo_arg, default=PUBLIC_REPO,
                        help=f"the public repository whose v<version> tags mark published versions (default {PUBLIC_REPO})")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        versions, problems = read_github(root, args.public_repo)
        report = write_pages({args.public: Path(args.public)}, {args.public: public_page(versions)})
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
