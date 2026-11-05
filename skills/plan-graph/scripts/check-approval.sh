#!/bin/sh
# Validate the posted latest approval's table before labelling or handoff.
# Read-only: gh issue/repo view and paginated gh api GETs in gh's current repo.
# Checks the public form and table, not authority, pointer provenance or
# fingerprint currentness;
# revision.sh and launch-fleet retain those checks unchanged.
# Usage: sh skills/plan-graph/scripts/check-approval.sh <spec issue number>
# Exit 0: valid table; 1: invalid table or unreadable graph; 2: bad arguments.
set -u
spec=${1:-}
case $spec in
  '' | 0* | *[!0-9]*) echo 'usage: sh check-approval.sh <spec issue number>' >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo 'usage: sh check-approval.sh <spec issue number>' >&2; exit 2; }
fail() { echo "check-approval.sh: $*" >&2; exit 1; }
work=$(mktemp -d) || fail 'cannot make a temporary folder'
trap 'rm -rf "$work"' EXIT

# Use the project mapping from the default branch, just as launch-fleet does.
# Only the operative Labels table counts, never examples or prose elsewhere.
gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/{owner}/{repo}/contents/docs/agents/triage-labels.md' > "$work/labels.md" ||
  fail 'cannot read project labels from docs/agents/triage-labels.md'
awk '/^## /{on = ($0 == "## Labels")} on && /^[|] *`[^`]+` *[|]/' \
  "$work/labels.md" > "$work/label-rows" || fail 'cannot read the project labels table'
jq -Rne '
  [inputs | capture("^\\| *`(?<role>[^`]+)` *\\| *`(?<name>[^`]*)` *\\|")
   | select(.role == "ready-for-agent" or .role == "ready-for-human")
   | {key: .role, value: .name}] as $rows
  | if ($rows | map(.key) | sort) == ["ready-for-agent", "ready-for-human"]
       and all($rows[]; .value != "")
    then $rows | from_entries else error("both ready roles must map exactly once") end
' < "$work/label-rows" > "$work/labels.json" 2> /dev/null ||
  fail 'project labels table must map ready-for-agent and ready-for-human exactly once to nonempty names'

gh issue view "$spec" --json subIssues > "$work/graph" || fail "cannot read spec #$spec's tickets"
# gh may cap a connection. Never treat a partial graph as a complete row set.
jq -es '
  def num: type == "number" and . > 0 and . == floor;
  if length != 1 then error("not one graph") else .[0].subIssues end
  | if (.totalCount | num) and (.nodes | type) == "array"
       and .totalCount == (.nodes | length) and all(.nodes[]; .number | num)
       and ([.nodes[].number] | unique | length) == .totalCount
    then [.nodes[].number] | sort else error("incomplete graph") end
' "$work/graph" > "$work/tickets" 2> /dev/null || fail "cannot read spec #$spec's complete, unique tickets"

gh api --paginate "repos/{owner}/{repo}/issues/$spec/comments?per_page=100" > "$work/comments" ||
  fail "cannot read spec #$spec's comments"
# Every page must be an array; missing fields or repeated pages are not a read.
jq -es '
  def num: type == "number" and . > 0 and . == floor;
  if length > 0 and all(.[]; type == "array") then add else error("not whole pages") end
  | if all(.[]; type == "object" and (.id | num) and (.body | type) == "string")
       and (map(.id) | unique | length) == length
    then . else error("bad comments") end
' "$work/comments" > "$work/all-comments" 2> /dev/null || fail "cannot read spec #$spec's complete comments"

# Only a positive private-repository read permits historical quoting records.
# Missing, failed or malformed visibility reads use the public form check.
private=false
if gh repo view --json isPrivate > "$work/repo" 2> /dev/null &&
   jq -es 'length == 1 and (.[0] | type == "object" and .isPrivate == true)' \
     "$work/repo" > /dev/null 2>&1; then
  private=true
fi

# Same latest-record rule as launch-fleet: first nonblank line starts with
# **Plan graph approved by; greatest comment ID wins, never an older good one.
jq -er --argjson private "$private" --slurpfile tickets "$work/tickets" --slurpfile labels "$work/labels.json" '
  def trim: sub("^\\s+"; "") | sub("\\s+$"; "");
  def public_form:
    . as $lines
    | ($lines[0] | capture("^\\*\\*Plan graph approved by (?<decider>[^,\\r\\n]+), [0-9]{4}-[0-9]{2}-[0-9]{2}, revision [1-9][0-9]*:\\*\\* (?<decision>[^\"“”]+)$") // null) as $header
    | $header != null and ($header.decision | trim | length) > 0
      and ($lines[1] // "" | test("^Private record: https://github\\.com/jparker2006/ClosedWiz/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$"))
      and all($lines[];
        (test("thr_[A-Za-z0-9][A-Za-z0-9_-]*") | not)
        and (test("^ {0,3}>") | not)
        and (if contains($header.decider // "") or contains("Jake") then
          (test(":(?:\\*\\*)?[ \\t]*\\\\?[\"“”]") | not) else true end));
  def cells:
    sub("\\s+$"; "")
    | if startswith("|") and endswith("|") then
      # A pipe is a separator only after an even run of backslashes.
      reduce (explode[]) as $char ({cells: [""], escaped: false};
        if $char == 124 and (.escaped | not) then .cells += [""]
        else .cells[-1] += ([$char] | implode) end
        | .escaped = (if $char == 92 then (.escaped | not) else false end))
      | .cells
      | if .[0] == "" and .[-1] == "" then .[1:-1] | map(trim)
        else error("approval table must end with an unescaped |") end
    else error("approval table must use launch-fleet rows beginning and ending with |") end;
  # Keep only table lines outside fenced examples (such as revision text).
  # Keep their indexes too: scattered rows are not one Markdown table.
  def table:
    reduce (to_entries[]) as $line ({fence: null, rows: []};
      if .fence != null then
        .fence as $fence
        | if ($line.value | test("^ {0,3}" + $fence.char + "{" + ($fence.size | tostring) + ",} *$"))
        then .fence = null else . end
      elif ($line.value | test("^ {0,3}(`{3,}|~{3,})")) then
        ($line.value | capture("^ {0,3}(?<f>`{3,}|~{3,})").f) as $f
        | .fence = {char: $f[0:1], size: ($f | length)}
      elif ($line.value | test("^\\s*\\|")) then .rows += [$line]
      else . end)
    | .rows;
  [.[] | select((.body | split("\n") | map(select(test("\\S"))) | first // "" | sub("^\\s+"; ""))
                | startswith("**Plan graph approved by"))] | max_by(.id)
  | if . == null then error("no posted plan graph approval") else .body end
  | split("\n") | map(rtrimstr("\r"))
  | if $private or public_form then . else error("public approval form requires a decision, date and private pointer, without quotes or thread ids") end
  | table
  | if length < 3 then error("approval table is missing") else . end
  | if (map(.key) | . == [range(.[0]; .[0] + length)]) then map(.value | cells)
    else error("approval table rows are not contiguous") end
  | if .[0] == ["Ticket", "Title", "Blocked by", "Label"] then .
    else error("approval table columns must be Ticket | Title | Blocked by | Label") end
  | if (.[1] | length) == 4 and all(.[1][]; test("^:?-{3,}:?$")) then .[2:]
    else error("approval table separator must have four columns") end
  | map(if length == 4 and (.[0] | test("^#[1-9][0-9]*$")) and .[1] != "" and .[2] != ""
              and (.[3] == "held" or .[3] == $labels[0]["ready-for-agent"] or .[3] == $labels[0]["ready-for-human"])
        then .[0][1:] | tonumber else error("approval table row needs a ticket, title, blockers and valid ready label or held") end)
  | if length == (unique | length) and sort == $tickets[0] then true
    else error("approval table tickets must equal the complete sub-issue set, each once") end
' "$work/all-comments" > /dev/null 2> "$work/error" || {
  cat "$work/error" >&2
  fail "spec #$spec's posted approval table is invalid; correct it before labelling or handoff"
}
echo "check-approval.sh: #$spec approval table is valid"
