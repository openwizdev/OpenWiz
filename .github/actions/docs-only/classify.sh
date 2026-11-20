#!/bin/sh
# Which jobs a change runs (#70, #86, #177). Reads the changed paths, one per
# line, on stdin, and prints the jobs to run, in the workflow's order, on one
# line: `web-build rust web-test`, some of them, or `none`. No paths at all
# runs every job. web-build runs whenever another job does (the legacy job
# names; the web view went in #1264).
#
# With `--skips JOB`, prints instead each path JOB never reads, one per line.
# The prune deletes them before JOB runs, so no job can read a path whose
# change alone lets it skip (the skip proof): a job that needs one fails on
# every run, main's and the nightly's included, until its row says so.
#
# READS names the files under private/ that CI reads (default: ci-reads.txt
# here); every job keeps them, and a change to one runs every job. Any
# error exits non-zero. An existing, readable empty list means no private
# inputs; missing or unreadable lists are never treated as empty.
#
# CLASSIFY_STEP answers for one step instead of the jobs: site (#1251)
# selects the release proofs' step. Its row reader selects that step.
# ci.yml asks decide.sh with it set, retaining the job's every-edge rules.
# The step has no separate prune, so every input it reads must have its
# reader in the table; full runs expose missing inputs.
set -eu
HERE="$(dirname "$0")"
READS="${READS:-$HERE/ci-reads.txt}"
step="${CLASSIFY_STEP:-}"
case "$step" in
  '' | site) ;;
  *) echo "classify: unknown step '$step'" >&2; exit 1 ;;
esac
skips= tests=
case "$#:${1:-}" in
  0:) ;;
  1:--tests) tests=1 ;;
  2:--skips)
    case "$2" in
      web-build | rust | web-test | release) skips="$2" ;;
      *) echo "classify: unknown job '$2'" >&2; exit 1 ;;
    esac
    [ -z "$step" ] || { echo "classify: --skips is for jobs, not CLASSIFY_STEP=$step" >&2; exit 1; } ;;
  *) echo "usage: classify.sh [--tests | --skips web-build|rust|web-test|release] < paths" >&2; exit 1 ;;
esac
[ -z "$tests" ] || [ -z "$step" ] || { echo "classify: --tests is for jobs, not CLASSIFY_STEP=$step" >&2; exit 1; }
[ -f "$READS" ] && [ -r "$READS" ] && cat "$READS" > /dev/null || { echo "classify: $READS is missing or unreadable" >&2; exit 1; }
table="$(mktemp)"
trap 'rm -f "$table"' EXIT
# Who reads each path: the first row whose pattern (an ERE) matches the whole
# path wins. `-` is no job; `site` is a step reader (CLASSIFY_STEP, above),
# never a job. A path no row matches is read by every job and the step
# (fail closed): .github/ and anything new. ci/runner/cache.sh, crates/,
# contracts/, tests/Cargo.toml, tests/fake-room-cli/ and tests/fixtures/
# are read by every job, and the site step reads only the release proofs'
# fixture there.
# So are changes/ and every other folder of tests/ and tools/, as before
# (the last row), which the site step never reads.
#
# The second column (#1486) names the Rust tests a change to the path runs
# in a pull request's plan (plan.py): `*` every one, `-` none but the always
# lane's (rust:test:checks, which runs in every plan), or the test ids that
# read it. A doc or skill names its readers here, found by reading the Rust
# sources: a doc no Rust test reads selects nothing. A named reader needs
# `rust` in the row's jobs, or the prune deletes its file. With `--tests`,
# classify.sh prints each path's column, one per line in order: `?` for a
# path no row knows (every test).
cat > "$table" <<'TABLE'
-               -       STATUS\.md|AGENTS\.md
-               -       private/.+
rust            -       \.claude/skills/(export-review|live-quick-check)/SKILL\.md
-               -       \.claude/skills/[^/]+/SKILL\.md
-               -       ci/runner/(README\.md|Dockerfile|compose\.yaml|entrypoint\.sh|test\.sh)
# X5 reuses the escape reader validator in every lane. Keep X6's other paths below.
web-build,rust,web-test * ci/escapes/escapes\.py
-               -       ci/escapes/.+|\.github/workflows/ci-escapes\.yml
web-build,rust  *       ci/rust-tests\.sh
# tests/fleet/b2_planner.rs reads the installed skills' fleet template through the link.
rust            rust:test:fleet skills
rust            -       \.claude/skills/[^/]+|\.agents/skills/[^/]+
# tests/fleet/b2_planner.rs parses it (include_str!).
rust            rust:test:fleet docs/agents/fleet\.md
rust            -       docs/.+|GLOSSARY\.md
web-build,rust  -       tests/checks/.+
web-build,rust  *       tests/(attachments|messaging|new-thread|proof|support)/.+|tests/pending-ticket-2\.txt
rust,web-test   *       tools/install/.+
rust,web-test,site *    tools/release/.+
rust            *       tools/github-app/.+
rust,web-test   *       Cargo\.toml|Cargo\.lock
web-build,rust,web-test,site * tests/fixtures/release/.+
web-build,rust,web-test * ci/runner/cache\.sh|crates/.+|contracts/.+|tests/Cargo\.toml|tests/fake-room-cli/.+|tests/fixtures/.+
web-build,rust,web-test * changes/.+|tests/.+|tools/.+
# Read by every job, as a path no row knows; only their Rust tests are named.
web-build,rust,web-test,site * \.githooks/.+|\.gitignore|LICENSE|adapters/.+|deploy/.+|kernel/.+|loops/.+|release/.+
# The pin moves the installed skills, so it reaches the template's reader.
web-build,rust,web-test,site rust:test:fleet wizskills\.lock
web-build,rust,web-test,site - [^/]+\.md|\.claude/skills/.+|\.agents/skills/.+
TABLE
# Identify each file explicitly: an empty reads list has no first record.
awk -v skips="$skips" -v step="$step" -v tests="$tests" '
  FILENAME == ARGV[1] {
    if ($1 ~ /^#/) next
    who[++rows] = $1; ids[rows] = $2; pat[rows] = "^(" $3 ")$"; next
  }
  FILENAME == ARGV[2] { listed[$0] = 1; next }
  {
    readers = "web-build,rust,web-test,site"; rust = ($0 in listed) ? "*" : "?"
    if (!($0 in listed)) for (i = 1; i <= rows; i++) if ($0 ~ pat[i]) { readers = who[i]; rust = ids[i]; break }
    if (tests) { print rust; next }
    if (skips != "") {
      # X5 combines the old Rust tool proofs and web release proofs.
      keep = (skips == "release") ? (index("," readers ",", ",rust,") || index("," readers ",", ",web-test,")) : index("," readers ",", "," skips ",")
      if (!keep) print
      next
    }
    paths++
    n = split(readers, r, ",")
    for (i = 1; i <= n; i++) {
      # The step reader never becomes a job; only its own row selects it.
      if (step == "") { if (r[i] != "site") ran[r[i]] = 1 }
      else if (r[i] == step) ran["web-test"] = 1
    }
  }
  END {
    if (skips != "" || tests) exit 0
    if (!paths || ran["rust"] || ran["web-test"]) ran["web-build"] = 1
    if (!paths) ran["rust"] = ran["web-test"] = 1
    out = ""
    if (ran["web-build"]) out = out " web-build"
    if (ran["rust"]) out = out " rust"
    if (ran["web-test"]) out = out " web-test"
    print (out == "" ? "none" : substr(out, 2))
  }
' "$table" "$READS" -
