#!/usr/bin/env python3
import argparse
from datetime import date
from pathlib import Path
import re
import sys

FLEET = Path(__file__).resolve().parents[2] / "docs/agents/fleet.md"
PREFIX = "Standing release grant:"
RULES = {
    f"{PREFIX} ship a 0.x.y patch after 0.2.0 launches when every release gate is green": "patch",
    f"{PREFIX} pull a broken release from latest": "pull",
}
HEADER = "| Rule | Approver |"
DIVIDER = "| --- | --- |"
ROW = re.compile(r"\|[ \t]*([^|]+?)[ \t]*\|[ \t]*([^|]+?)[ \t]*\|")
DECISION = re.compile(
    r"Jake, ([0-9]{4}-[0-9]{2}-[0-9]{2}): Approved the standing release grants listed in this table "
    r"\(\[private record\]\(https://github\.com/jparker2006/ClosedWiz/"
    r"(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*\)\)\."
)
ABSENT = "no standing release grant"
MALFORMED = "malformed standing release grant row"
NO_POINTER = "missing or invalid standing release grant decision or private-record pointer"


def visible_lines(document):
    fence = ""
    markup_end = ""
    for line in document.split("\n"):
        if fence:
            if re.fullmatch(rf" {{0,3}}{fence[0]}{{{len(fence)},}}[ \t]*", line):
                fence = ""
        elif markup_end:
            if markup_end in line.lower():
                markup_end = ""
        else:
            opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            literal = re.match(r"^ {0,3}<(pre|script|style|textarea)(?=[ \t>]|$)", line, re.IGNORECASE)
            if opening:
                fence = opening[1]
            elif "<!--" in line:
                if "-->" not in line.split("<!--", 1)[1]:
                    markup_end = "-->"
            elif literal:
                closing = f"</{literal[1].lower()}>"
                if closing not in line.lower():
                    markup_end = closing
            else:
                yield line
                continue
        yield None


def denial(document, action):
    lines = list(visible_lines(document))
    headings = [index for index, line in enumerate(lines) if line == "## Approval rules"]
    if not headings:
        return ABSENT
    if len(headings) != 1:
        return "ambiguous Approval rules section"

    section = []
    for line in lines[headings[0] + 1:]:
        if line is not None and re.match(r"^ {0,3}#{1,2}(?:[ \t]|$)", line):
            break
        section.append(line.rstrip(" \t") if line is not None else None)

    start = next((index for index, line in enumerate(section) if line != ""), len(section))
    if section[start:start + 2] != [HEADER, DIVIDER]:
        return "missing or invalid Approval rules table"

    actions = set()
    end = start + 2
    for line in section[end:]:
        if line in ("", None):
            break
        end += 1
        row = ROW.fullmatch(line)
        if row is None:
            return MALFORMED
        rule, owner = row.groups()
        if PREFIX[:-1].casefold() not in rule.casefold():
            continue
        if re.search(r"(?<![\w.])0\.x\.0(?![\w.])", rule, re.IGNORECASE):
            return "every 0.x.0 stays the owner's ship call"
        granted = RULES.get(rule)
        if granted is None or owner != "Jake" or granted in actions:
            return MALFORMED
        actions.add(granted)

    if action not in actions:
        return ABSENT

    record = next((line for line in section[end:] if line != ""), None)
    match = DECISION.fullmatch(record) if record is not None else None
    if match is None or section[end] != "":
        return NO_POINTER
    try:
        date.fromisoformat(match[1])
    except ValueError:
        return NO_POINTER
    return None


def main():
    parser = argparse.ArgumentParser(description="Check the standing release grant in the fleet's Approval rules.")
    parser.add_argument("command", choices=("check",))
    parser.add_argument("action", choices=("patch", "pull"))
    parser.add_argument("--fleet", type=Path, default=FLEET)
    args = parser.parse_args()
    try:
        document = args.fleet.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        reason = "cannot read fleet file"
    else:
        reason = denial(document, args.action)
    if reason is not None:
        print(f"{args.action}: {reason}", file=sys.stderr)
        return 1
    print(f"{args.action}: standing release grant recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
