"""Require a changelog line for product PRs; all GitHub calls are reads."""
import json
import os
import re
import subprocess
import sys


class Refused(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def api(*args):
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                            timeout=60, check=True)
    return json.loads(result.stdout, object_pairs_hook=unique_object)


def snapshot(value):
    require(isinstance(value, dict), "PR response is not an object")
    shas = []
    for side in ("base", "head"):
        ref = value.get(side)
        require(isinstance(ref, dict), "missing PR reference")
        sha = ref.get("sha")
        require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha),
                "invalid PR commit")
        shas.append(sha)
    labels = value.get("labels")
    require(isinstance(labels, list), "missing PR labels")
    names = []
    for label in labels:
        require(isinstance(label, dict) and isinstance(label.get("name"), str),
                "invalid PR label")
        names.append(label["name"])
    count = value.get("changed_files")
    require(type(count) is int and 0 < count <= 3000,
            "missing, empty or over-limit file count (GitHub lists at most 3000)")
    return (*shas, sorted(names), count)


def path(value):
    require(isinstance(value, str) and value and "\\" not in value
            and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and all(part not in ("", ".", "..") for part in value.split("/")),
            "invalid changed path")
    return value


def product(filename):
    # Only known nonproduct areas are exempt. New roots require a line until
    # classified here. Product trees include their manifests and assets.
    nonproduct_roots = (".github/", ".githooks/", ".agents/", ".claude/",
                        "docs/", "private/",
                        "tests/", "tools/", "ci/", "changes/")
    nonproduct_files = {"AGENTS.md", "GLOSSARY.md", "README.md", "STATUS.md",
                        ".gitignore"}
    return not (filename in nonproduct_files or filename.startswith(nonproduct_roots))


def classify(pages, expected_count):
    require(isinstance(pages, list) and pages, "missing file pages")
    seen = set()
    has_product = has_line = False
    for page in pages:
        require(isinstance(page, list) and page, "invalid or empty file page")
        for item in page:
            require(isinstance(item, dict), "changed file is not an object")
            filename = path(item.get("filename"))
            require(filename not in seen, "duplicate changed file")
            seen.add(filename)
            status = item.get("status")
            require(status in ("added", "modified", "removed", "renamed", "copied", "changed"),
                    "unknown file status")
            has_product |= product(filename)
            if status == "renamed":
                has_product |= product(path(item.get("previous_filename")))
            # A correction is allowed by changes/README.md. Deleting a line
            # never counts. Content, milestone and truth remain review gates.
            has_line |= (status != "removed" and
                         re.fullmatch(r"changes/[1-9][0-9]*\.md", filename) is not None)
    require(len(seen) == expected_count, "incomplete changed-file list")
    return has_product, has_line


def main():
    event = os.environ.get("EVENT")
    if event == "merge_group":
        print("changelog: merge group passes; PRs are checked before admission")
        return
    require(event == "pull_request", "unsupported event")
    repo = os.environ.get("REPO", "")
    number = os.environ.get("PR", "")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            and re.fullmatch(r"[1-9][0-9]*", number), "invalid repository or PR")
    endpoint = f"repos/{repo}/pulls/{number}"
    before = snapshot(api(endpoint))
    require(before[1] == os.environ.get("EVENT_HEAD"), "event head is stale")
    pages = api("--paginate", "--slurp", f"{endpoint}/files?per_page=100")
    has_product, has_line = classify(pages, before[3])
    require(snapshot(api(endpoint)) == before, "PR changed during check; rerun")
    require(not has_product or has_line or "no-changelog" in before[2],
            "product change needs changes/<ticket>.md or the reviewed no-changelog label")
    reason = ("no-changelog label" if "no-changelog" in before[2] else
              "changelog line present" if has_line else "no product change")
    print(f"changelog: pass ({reason})")


if __name__ == "__main__":
    try:
        main()
    except (Refused, ValueError, OSError, subprocess.SubprocessError) as error:
        # Never echo API bodies (or gh stderr), which may contain private data.
        message = str(error) if isinstance(error, Refused) else type(error).__name__
        print(f"changelog: refused: {message}", file=sys.stderr)
        sys.exit(1)
