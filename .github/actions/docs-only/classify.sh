#!/bin/sh
# Which jobs a change runs (#70, #86, #177). Reads the changed paths, one per
# line, on stdin, and prints the jobs to run, in the workflow's order, on one
# line: `web-build rust web-test`, some of them, or `none`. No paths at all
# runs every job. web-build runs whenever another job does: they read its
# apps/web/out.
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
# selects web-test's public-site check; toolkit (#2081) selects rust's fast
# offline toolkit checks. The corresponding row reader selects that step.
# ci.yml asks decide.sh with it set, retaining the job's every-edge rules.
# These steps have no separate prune, so every input they read must have its
# reader in the table; full runs expose missing inputs.
set -eu
HERE="$(dirname "$0")"
READS="${READS:-$HERE/ci-reads.txt}"
step="${CLASSIFY_STEP:-}"
case "$step" in
  '' | site | toolkit) ;;
  *) echo "classify: unknown step '$step'" >&2; exit 1 ;;
esac
skips=
case "$#:${1:-}" in
  0:) ;;
  2:--skips)
    case "$2" in
      web-build | rust | web-test | release) skips="$2" ;;
      *) echo "classify: unknown job '$2'" >&2; exit 1 ;;
    esac
    [ -z "$step" ] || { echo "classify: --skips is for jobs, not CLASSIFY_STEP=$step" >&2; exit 1; } ;;
  *) echo "usage: classify.sh [--skips web-build|rust|web-test|release] < paths" >&2; exit 1 ;;
esac
[ -f "$READS" ] && [ -r "$READS" ] && cat "$READS" > /dev/null || { echo "classify: $READS is missing or unreadable" >&2; exit 1; }
table="$(mktemp)"
trap 'rm -f "$table"' EXIT
# Who reads each path: the first row whose pattern (an ERE) matches the whole
# path wins. `-` is no job; `site` and `toolkit` are step readers (CLASSIFY_STEP,
# above), never jobs. A path no row matches is read by every job and the
# steps (fail closed): .github/ (the site's tests read ci.yml and this
# file) and anything new. ci/runner/cache.sh, crates/, apps/web/,
# contracts/, tests/Cargo.toml, tests/fake-room-cli/ and tests/fixtures/
# (web-test builds the server and the fake, and serves the fixtures) are
# read by every job, and the site step reads only the release proofs'
# fixture there and the app's files it copies or loads its packages from.
# So are changes/ and every other folder of tests/ and tools/, as before
# (the last row), which the site step never reads.
cat > "$table" <<'TABLE'
-               STATUS\.md|AGENTS\.md
-               private/.+
rust            \.claude/skills/(export-review|live-quick-check)/SKILL\.md
-               \.claude/skills/[^/]+/SKILL\.md
-               ci/runner/(README\.md|Dockerfile|compose\.yaml|entrypoint\.sh|test\.sh)
# X5 reuses the escape reader validator in every lane. Keep X6's other paths below.
web-build,rust,web-test ci/escapes/escapes\.py
-               ci/escapes/.+|\.github/workflows/ci-escapes\.yml
web-build,rust  ci/rust-tests\.sh
rust            skills/.+|\.claude-plugin/[^/]+|\.claude/skills/[^/]+|\.agents/skills/[^/]+
rust            docs/.+|GLOSSARY\.md
web-build,rust  tests/(attachments|checks|messaging|new-thread|proof|send-harness|support|web-api)/.+|tests/pending-ticket-2\.txt
rust,web-test   tools/install/.+
rust,web-test,site tools/release/.+
rust            tools/github-app/.+
web-build,rust,web-test,toolkit tools/live-check/.+
web-build,web-test,site apps/site/.+
rust,web-test   Cargo\.toml|Cargo\.lock
web-build,rust,web-test,site tests/fixtures/release/.+|apps/web/(package\.json|package-lock\.json|styles/tokens\.css|public/fonts/.+)
web-build,rust,web-test ci/runner/cache\.sh|crates/.+|apps/web/.+|contracts/.+|tests/Cargo\.toml|tests/fake-room-cli/.+|tests/fixtures/.+
web-build,rust,web-test changes/.+|tests/.+|tools/.+
TABLE
# Identify each file explicitly: an empty reads list has no first record.
awk -v skips="$skips" -v step="$step" '
  FILENAME == ARGV[1] { who[++rows] = $1; pat[rows] = "^(" $2 ")$"; next }
  FILENAME == ARGV[2] { listed[$0] = 1; next }
  {
    readers = "web-build,rust,web-test,site,toolkit"
    if (!($0 in listed)) for (i = 1; i <= rows; i++) if ($0 ~ pat[i]) { readers = who[i]; break }
    if (skips != "") {
      # X5 combines the old Rust tool proofs and web release proofs.
      keep = (skips == "release") ? (index("," readers ",", ",rust,") || index("," readers ",", ",web-test,")) : index("," readers ",", "," skips ",")
      if (!keep) print
      next
    }
    paths++
    n = split(readers, r, ",")
    for (i = 1; i <= n; i++) {
      # Step readers never become jobs; only their own row selects them.
      if (step == "") { if (r[i] != "site" && r[i] != "toolkit") ran[r[i]] = 1 }
      else if (r[i] == step) ran[step == "site" ? "web-test" : "rust"] = 1
    }
  }
  END {
    if (skips != "") exit 0
    if (!paths || ran["rust"] || ran["web-test"]) ran["web-build"] = 1
    if (!paths) ran["rust"] = ran["web-test"] = 1
    out = ""
    if (ran["web-build"]) out = out " web-build"
    if (ran["rust"]) out = out " rust"
    if (ran["web-test"]) out = out " web-test"
    print (out == "" ? "none" : substr(out, 2))
  }
' "$table" "$READS" -
