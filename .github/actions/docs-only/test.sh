#!/bin/sh
# The per-job classifier (#86, #177): the table, the decision, the prune and
# the skip proof, on sample paths and synthetic histories, and the workflow's
# wiring, read statically. Run from anywhere:
#   sh .github/actions/docs-only/test.sh
set -u
mode=all
case "$#:${1:-}" in
  0:) ;;
  1:--always) mode=always ;;
  *) echo "usage: test.sh [--always]" >&2; exit 2 ;;
esac
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../../.."
ALL='web-build rust web-test'
fails=0
ok() { echo "ok   $*"; }
bad() { echo "FAIL $*"; fails=$((fails + 1)); }

# jobs WANT PATHS...: the jobs this change runs, in the workflow's order, or
# `none`. Nothing changed runs every job.
jobs() {
  want="$1"; shift
  got="$(printf '%s\n' "$@" | sed '/^$/d' | sh "$HERE/classify.sh" 2>&1)" || got="error: $got"
  if [ "$got" = "$want" ]; then ok "$want  <=  $*"; else bad "want '$want', got '$got':  $*"; fi
}

# Nothing any job reads: every job skips.
jobs none STATUS.md
jobs none AGENTS.md STATUS.md
jobs none private/acceptance-lessons.md
jobs none private/orchestration/HANDOFF.md
jobs none .claude/skills/builder/SKILL.md
# #1277: production CI reads no private files; synthetic nonempty lists
# below still exercise the generic exception-list behavior.
jobs none private/evidence/ci-capacity/README.md
jobs none private/evidence/openwiz-0.0.3/ticket-1/red-run.log
jobs none private/evidence/openwiz-0.0.1/ticket-3/scripts/observe.py
jobs none private/orchestration/sub/notes.md
jobs none STATUS.md private/evidence/x/y.json private/evidence/x/z.txt
jobs none private/evidence/openwiz-0.0.1/ticket-1/dependencies.md
jobs none STATUS.md private/evidence/openwiz-0.0.1/ticket-1/dependencies.md
# The runner kit: only cache.sh runs inside a job.
jobs none ci/runner/README.md
jobs none ci/runner/Dockerfile ci/runner/compose.yaml ci/runner/entrypoint.sh ci/runner/test.sh
jobs "$ALL" ci/runner/cache.sh
jobs "$ALL" ci/runner/new.sh
jobs "$ALL" ci/runner/README.md.bak
# #1251: web-build's test.sh runs ci/rust-tests.sh on fakes, so it keeps it.
jobs "web-build rust" ci/rust-tests.sh
# #1264: the escape finder and its workflow, which runs its own tests; no
# CI job reads them. A neighbour no row knows still runs every job.
jobs none ci/escapes/fixtures/gh .github/workflows/ci-escapes.yml
# X5: all lanes now read X6's validator.
jobs "$ALL" ci/escapes/escapes.py
jobs "$ALL" ci/escapes.py
jobs "$ALL" .github/workflows/ci-escapes.yml.bak

# Skills and docs (#177): the rust job's skills check and the triage test
# read them. web-build runs with rust, for the out/ that rust reads.
# #555: `skills` is one tracked link to the installed WizSkills; a path under
# it is never tracked, so it is unknown and runs every job.
jobs "web-build rust" skills
jobs "web-build rust" .claude/skills/grill
jobs "web-build rust" .agents/skills/grill
jobs "web-build rust" docs/agents/fleet.md
jobs "web-build rust" docs/grills/2026-10-31-ci-speed.md docs/adr/0010-infra-work-has-no-version.md GLOSSARY.md
jobs "web-build rust" skills STATUS.md private/evidence/x.md ci/runner/README.md
# The Rust-only tests: web-test builds only the server and the fake.
jobs "web-build rust" tests/checks/skills.rs
jobs "web-build rust" tests/proof/p01_inventory.rs tests/messaging/support.rs
jobs "web-build rust" tests/attachments/ad_static.rs tests/new-thread/main.rs tests/support/dirs.rs
jobs "web-build rust" tests/pending-ticket-2.txt
jobs "web-build rust" private/evidence/x.md tests/checks/dependencies.rs
# GitHub App fixtures (#422): only rust reads these tools.
jobs "web-build rust" tools/github-app/manifest.json
jobs "web-build rust" tools/github-app/test.py tools/github-app/mint-token.py tools/github-app/common.py
jobs "web-build rust" tools/github-app/fixtures/synthetic.json
jobs "$ALL" tools/github-app-other/test.py
jobs "$ALL" tools/github-app
# Everything else runs every job: the code, the contracts, the fixtures,
# the workflow and this action.
jobs "$ALL" tools/install/install.py tools/release/package.py
jobs "$ALL" crates/core/src/lib.rs
jobs "$ALL" STATUS.md crates/core/src/lib.rs
jobs "$ALL" Cargo.toml
jobs "$ALL" Cargo.lock
jobs "$ALL" tests/Cargo.toml
jobs "$ALL" tests/fake-room-cli/main.rs
jobs "$ALL" tests/fixtures/room-cli-0.43.1/ls-basic/scenario.json
jobs "$ALL" tests/newdir/x.rs
jobs "$ALL" tests/checks
jobs "$ALL" contracts/fleet.v1.md
jobs "$ALL" .github/workflows/ci.yml
jobs "$ALL" .github/actions/docs-only/ci-reads.txt
jobs "$ALL" skills/grill/SKILL.md crates/core/src/lib.rs
jobs "$ALL" docs/agents/fleet.md tests/fixtures/README.md
# A path no row knows runs every job (fail closed).
jobs "$ALL" README.md
jobs "$ALL" release/openwiz/README.md
jobs "$ALL" .gitignore
jobs "$ALL" newdir/x.md
jobs "$ALL" XSTATUS.md
jobs "$ALL" STATUS.md.bak
jobs "$ALL" privatex/a.md
jobs "$ALL" private
jobs "$ALL" skills/a.md
jobs "$ALL" docs
jobs "$ALL" xskills/a.md
jobs "$ALL" .claude/skills/builder/helper.sh
jobs "$ALL" .claude/settings.json
jobs "$ALL" .claude-plugin/x/y.json
jobs "$ALL" '"private/\303\251.md"'
jobs "$ALL" '"skills/\303\251.md"'
jobs "$ALL" ' private/a.md'
jobs "$ALL" ' skills/a.md'
# Nothing changed: run everything.
jobs "$ALL"
# The site step's rows (#1251): CLASSIFY_STEP=site answers whether
# the release proofs' step runs (web-test in the answer) or skips. It reads
# the release proofs (tools/release/, all copied by one test) and their
# fixture (tests/fixtures/release/), the workflow and this classifier
# (.github/, no row), and any path no row knows. The crates, the root Cargo
# files (the release proofs' are synthetic, and their cargo a fake), the
# contracts, the Rust tests, skills and docs it never reads: traced under
# strace (private/evidence/ci-quick-wins/README.md). The site copy and the
# web view it also read went in #1264.
site() {
  want="$1"; shift
  got="$(printf '%s\n' "$@" | sed '/^$/d' | CLASSIFY_STEP=site sh "$HERE/classify.sh" 2>&1)" || got="error: $got"
  case " $got " in *" web-test "*) got=runs ;; *" error: "*) ;; *) got=skips ;; esac
  if [ "$got" = "$want" ]; then ok "site step $want  <=  $*"; else bad "site step: want '$want', got '$got':  $*"; fi
}
site runs tools/release/test.py tools/release/check.py
site runs tests/fixtures/release/clean/README.md
site runs .github/workflows/ci.yml
site runs .github/actions/docs-only/classify.sh
site runs README.md
site runs newdir/x.md
site runs crates/core/src/lib.rs tools/release/check.py
site runs
site skips crates/core/src/lib.rs
site skips crates/adapters/cloudroom/src/allowlist.rs crates/cli/src/main.rs
site skips contracts/fleet.v1.md
site skips tests/Cargo.toml
site skips tests/fake-room-cli/main.rs
site skips tests/fixtures/README.md
site skips Cargo.toml
site skips Cargo.lock
site skips tests/checks/skills.rs
site skips tools/install/install.py
site skips tools/github-app/test.py
site skips ci/runner/cache.sh
site skips ci/rust-tests.sh
site skips skills docs/agents/fleet.md GLOSSARY.md
site skips STATUS.md private/evidence/x.md
# R2 on #1291: the paths no job row knows but the site never reads (traced):
# the changelog lines, every other test folder and every other tool. The
# jobs' answer for them stays every job.
site skips changes/1251.md
site skips changes/README.md
site skips tests/loops/main.rs tests/fleet/b2_cases.rs tests/cli-agent/main.rs
site skips tests/newdir/x.rs
site skips tools/war-room/test_gather.py tools/collector/steps.tsv
site skips changes/1102.md tests/loops/fixture.rs
site runs changes/1251.md tools/release/test.py
site runs tests/fixtures/release/clean/README.md tests/loops/main.rs
site runs tools/release/README.md tools/collector/steps.tsv
jobs "$ALL" changes/1251.md
jobs "$ALL" tests/loops/main.rs
jobs "$ALL" tools/war-room/test_gather.py
# The step mode leaves the jobs' own answers alone.
jobs "$ALL" crates/core/src/lib.rs
if printf 'tools/release/test.py\n' | CLASSIFY_STEP=web sh "$HERE/classify.sh" > /dev/null 2>&1; then bad "CLASSIFY_STEP accepts an unknown step"; else ok "CLASSIFY_STEP refuses an unknown step"; fi
if printf 'tools/release/test.py\n' | CLASSIFY_STEP=site sh "$HERE/classify.sh" --skips web-test > /dev/null 2>&1; then bad "CLASSIFY_STEP=site gives a prune list"; else ok "CLASSIFY_STEP=site refuses --skips"; fi
# A deliberately empty reads list is valid. File order must not turn paths
# into list entries: ordinary paths, skip mode and site mode keep their rules.
mkdir -p "${TMPDIR:-/tmp}"
noreads="$(mktemp)"
READS="$noreads" jobs "web-build rust" skills
READS="$noreads" jobs "$ALL" unknown/synthetic.rs
READS="$noreads" jobs none private/synthetic.md
READS="$noreads" jobs "$ALL"
got="$(printf '%s\n' skills/a.md STATUS.md private/synthetic.md | READS="$noreads" sh "$HERE/classify.sh" --skips rust 2>&1)" || got="error: $got"
want="$(printf '%s\n' STATUS.md private/synthetic.md)"
if [ "$got" = "$want" ]; then ok "empty reads: skip mode preserves path classification"; else bad "empty reads: skip mode got [$got]"; fi
got="$(printf 'tools/release/test.py\n' | READS="$noreads" CLASSIFY_STEP=site sh "$HERE/classify.sh" 2>&1)" || got="error: $got"
if [ "$got" = "web-build web-test" ]; then ok "empty reads: site path still runs with its build prerequisite"; else bad "empty reads: site path got [$got]"; fi
# Missing, non-file and unreadable inputs are errors, never empty lists.
for invalid in "$noreads.missing" "$(dirname "$noreads")"; do
  if printf 'skills/a.md\n' | READS="$invalid" sh "$HERE/classify.sh" > /dev/null 2>&1; then bad "missing/non-file reads input gives an answer"; else ok "missing/non-file reads input is refused"; fi
done
chmod 000 "$noreads"
if printf 'skills/a.md\n' | READS="$noreads" sh "$HERE/classify.sh" > /dev/null 2>&1; then bad "unreadable reads input gives an answer"; else ok "unreadable reads input is refused"; fi
chmod 600 "$noreads"
# A synthetic listed private path still runs every job; an unlisted one skips.
printf 'private/synthetic.md\n' > "$noreads"
READS="$noreads" jobs "$ALL" private/synthetic.md
READS="$noreads" jobs none private/other-synthetic.md
rm -f "$noreads"
if printf 'skills/a.md\n' | sh "$HERE/classify.sh" --skips nobody > /dev/null 2>&1; then bad "--skips accepts an unknown job"; else ok "--skips refuses an unknown job"; fi

# Production has no private inputs. Nonempty-list safety is tested on synthetic files below.
if [ -f "$HERE/ci-reads.txt" ] && [ ! -s "$HERE/ci-reads.txt" ]; then ok "ci-reads.txt deliberately lists no private input"; else bad "ci-reads.txt must be an existing empty file"; fi
while IFS= read -r line; do
  case "$line" in
    private/?*) [ -f "$ROOT/$line" ] || bad "ci-reads.txt: $line does not exist" ;;
    *) bad "ci-reads.txt: $line is not under private/" ;;
  esac
  # Each line is also a sparse-checkout pattern in ci.yml (#334): plain
  # names only, so the pattern matches that one file and nothing else.
  printf '%s\n' "$line" | grep -qxE 'private(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+' || bad "ci-reads.txt: $line is not a plain path (letters, digits, '.', '_', '-' and '/')"
done < "$HERE/ci-reads.txt"

# Every quoted path under private/ in what CI runs is listed (a static
# check; the prune is the enforcement). Comments quote paths in backticks.
for path in $(grep -rhoE "[\"']private/[^\"' ]+[\"']" "$ROOT/crates" "$ROOT/tests" --exclude-dir=fixtures --exclude-dir=node_modules 2>/dev/null | tr -d "\"'" | sort -u); do
  if grep -qxF "$path" "$HERE/ci-reads.txt"; then ok "read and listed: $path"; else bad "ci-reads.txt: $path is read but not listed"; fi
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
gitq() { d="$1"; shift; git -C "$d" -c user.name=synthetic -c user.email=synthetic@example.invalid "$@"; }

# Prune (#86): a run keeps only the listed files under private/.
t="$tmp/tree"
mkdir -p "$t/private/evidence/a/b" "$t/private/orchestration" "$t/crates"
for f in private/x.md private/orchestration/y.md private/evidence/a/b/keep.md private/evidence/a/b/drop.json crates/c.rs; do
  echo synthetic > "$t/$f"
done
ln -s ../crates/c.rs "$t/private/link"
git init -q "$t" && git -C "$t" add -A
printf '%s\n' private/evidence/a/b/keep.md > "$tmp/reads.txt"
for job in $ALL; do
  if (cd "$t" && sh "$HERE/prune.sh" "$tmp/reads.txt" "$job" > /dev/null 2>&1); then
    left="$(cd "$t" && find private crates \( -type f -o -type l \) | sort | tr '\n' ' ')"
    if [ "$left" = "crates/c.rs private/evidence/a/b/keep.md " ]; then ok "prune ($job) keeps only the listed files under private/"; else bad "prune ($job) left: $left"; fi
  else
    bad "prune ($job) failed"
  fi
  git -C "$t" checkout -q -- . 2> /dev/null
  echo synthetic > "$t/private/evidence/a/b/drop.json"
done
# Empty lists remove private/ completely, including from an already pruned tree.
: > "$tmp/empty-reads.txt"
for job in $ALL; do
  git -C "$t" checkout -q -- .
  if (cd "$t" && sh "$HERE/prune.sh" "$tmp/empty-reads.txt" "$job" > /dev/null 2>&1) && [ ! -e "$t/private" ] && [ -f "$t/crates/c.rs" ]; then ok "empty reads: prune ($job) removes all private files"; else bad "empty reads: prune ($job) did not remove private/"; fi
  if (cd "$t" && sh "$HERE/prune.sh" "$tmp/empty-reads.txt" "$job" > /dev/null 2>&1) && [ ! -e "$t/private" ]; then ok "empty reads: prune ($job) accepts absent private/"; else bad "empty reads: prune ($job) failed with absent private/"; fi
done
# Bad read lists must fail before deleting any private file.
git -C "$t" checkout -q -- .
for invalid in "$tmp/missing-reads.txt" "$tmp"; do
  if (cd "$t" && sh "$HERE/prune.sh" "$invalid" rust > /dev/null 2>&1); then bad "prune accepts missing/non-file reads input"; elif [ -f "$t/private/x.md" ]; then ok "prune refuses missing/non-file input before mutation"; else bad "prune mutated files before refusing input"; fi
done
chmod 000 "$tmp/empty-reads.txt"
if (cd "$t" && sh "$HERE/prune.sh" "$tmp/empty-reads.txt" rust > /dev/null 2>&1); then bad "prune accepts unreadable reads input"; elif [ -f "$t/private/x.md" ]; then ok "prune refuses unreadable input before mutation"; else bad "prune mutated files before refusing unreadable input"; fi
chmod 600 "$tmp/empty-reads.txt"
# A listed file that is missing, or one outside private/, fails the step;
# so does a job that isn't one of the three, or none.
for bad in private/evidence/missing.md crates/c.rs ../outside.md; do
  printf '%s\n' "$bad" > "$tmp/reads.txt"
  if (cd "$t" && sh "$HERE/prune.sh" "$tmp/reads.txt" rust > /dev/null 2>&1); then bad "prune accepted $bad"; else ok "prune refuses $bad"; fi
done
printf '%s\n' private/evidence/a/b/keep.md > "$tmp/reads.txt"
for job in nobody '' 'rust web-test'; do
  if (cd "$t" && sh "$HERE/prune.sh" "$tmp/reads.txt" "$job" > /dev/null 2>&1); then bad "prune accepted the job '$job'"; else ok "prune refuses the job '$job'"; fi
done

# The checkout (#334): every job checks out blobless and sparse, leaving out
# private/ but the files CI reads. ci-reads.txt can't be read before the
# checkout, so each job's checkout spells the list out, and this checks each
# one says exactly this, its patterns taken from ci-reads.txt: full history
# for decide.sh's base, no file contents until the checkout needs them, and
# non-cone patterns (a cone can't leave out a folder but a few of its files).
WORKFLOW="$ROOT/.github/workflows/ci.yml"
want_with="$(printf '%s\n' '        with:' '          persist-credentials: false' '          fetch-depth: 0' '          filter: blob:none' '          sparse-checkout-cone-mode: false' '          sparse-checkout: |' '            /*' '            !/private/'; sed 's|^|            /|' "$HERE/ci-reads.txt")"
# Each checkout step, as `job NAME` followed by its fields.
checkouts="$(awk '
  /^  [a-z][a-z0-9-]*:$/ { job = $1; sub(":", "", job); inside = 0 }
  /^      - uses: actions\/checkout@/ { print "job " job; inside = 1; next }
  inside && /^        / { print; next }
  { inside = 0 }
' "$WORKFLOW")"
for job in changes always rust release skills launch-fleet ci web-test main-light owned-paths; do
  steps="$(printf '%s\n' "$checkouts" | grep -cxF "job $job")"
  with="$(printf '%s\n' "$checkouts" | awk -v j="job $job" '/^job / { on = ($0 == j); next } on')"
  if [ "$steps" = 1 ] && [ "$with" = "$want_with" ]; then ok "ci.yml: $job checks out blobless and sparse, private/ only as ci-reads.txt lists"; else bad "ci.yml: $job has $steps checkout steps, with [$(printf '%s\n' "$with" | sed 's/^ *//' | tr '\n' ';')]"; fi
done
if [ "$(printf '%s\n' "$checkouts" | grep -c '^job ')" = 10 ]; then ok "ci.yml: ten main checkout steps (X5, launch-fleet's shards, main-light and owned-paths)"; else bad "ci.yml: $(printf '%s\n' "$checkouts" | grep -c '^job ') checkout steps"; fi
# The patterns as CI uses them: the first job's (the check above holds all
# to the same list). Keep this tied to the actual workflow: pending X5's
# update must remain a failing checkout proof, never a substituted pattern.
printf '%s\n' "$checkouts" | awk '/^job / { n++; on = 0; next } n == 1 && on { sub(/^ +/, ""); print } /^          sparse-checkout: \|$/ { on = 1 }' > "$tmp/sparse.txt"

# ci_checkout SRC DST SHA PATTERNS: SHA from the repository SRC into a new
# DST, as actions/checkout does with ci.yml's settings: every branch with full
# history and no file contents, then the patterns appended to the sparse
# file, then a checkout that fetches only the contents it writes. Then the
# remote is gone, as a private repository is to a job whose checkout kept no
# credentials, so nothing later can fetch what the checkout left out.
ci_checkout() {
  [ -s "$4" ] || { echo "ci_checkout: no sparse patterns" >&2; return 1; }
  rm -rf "$2" && git init -q "$2" && git -C "$2" remote add origin "file://$1" || return 1
  git -C "$2" -c protocol.version=2 fetch -q --no-tags --prune --no-recurse-submodules --filter=blob:none origin '+refs/heads/*:refs/remotes/origin/*' "$3" || return 1
  git -C "$2" config core.sparseCheckout true || return 1
  info="$(git -C "$2" rev-parse --absolute-git-dir)/info"
  mkdir -p "$info" && { echo; cat "$4"; } >> "$info/sparse-checkout" || return 1
  git -C "$2" checkout -q --force "$3" || return 1
  git -C "$2" remote set-url origin "file://$tmp/gone"
}
# serve DIR: let ci_checkout fetch from DIR as GitHub serves a checkout.
serve() { git -C "$1" config uploadpack.allowFilter true && git -C "$1" config uploadpack.allowAnySHA1InWant true; }

# The skip proof (#177): a change to a path lets a job skip only if that path
# is gone whenever the job runs. So a job that reads it fails on every run,
# main's and the nightly's included, instead of passing a PR it skipped.
# One sample file for each row of the table, and for paths no row knows.
SAMPLES='STATUS.md
AGENTS.md
private/orchestration/HANDOFF.md
private/evidence/openwiz-0.0.1/ticket-1/dependencies.md
private/evidence/openwiz-0.0.1/ticket-1/red-run.log
private/evidence/openwiz-0.0.4/b1/extension-table.md
.claude/skills/live-spike/SKILL.md
ci/runner/README.md
ci/runner/Dockerfile
ci/runner/cache.sh
ci/rust-tests.sh
ci/escapes/escapes.py
.github/workflows/ci-escapes.yml
skills
.claude/skills/grill
.agents/skills/grill
docs/agents/fleet.md
GLOSSARY.md
tests/checks/skills.rs
tests/pending-ticket-2.txt
tools/github-app/test.py
tools/github-app/manifest.json
Cargo.toml
Cargo.lock
tests/Cargo.toml
tests/fake-room-cli/main.rs
tests/fixtures/README.md
crates/core/src/lib.rs
contracts/fleet.v1.md
tests/checks/dependencies.md
.github/workflows/ci.yml
README.md
release/openwiz/README.md
.gitignore
newdir/x.md'
# What each job's tree keeps after its prune, written out by hand: the files
# its commands open (crates/ and tests/ for test.sh's scan, Cargo for the
# server web-test builds, skills/ and docs/ for the skills check), and every
# path no row knows.
KEEP_ANY='ci/escapes/escapes.py
ci/runner/cache.sh
tests/Cargo.toml
tests/fake-room-cli/main.rs
tests/fixtures/README.md
crates/core/src/lib.rs
contracts/fleet.v1.md
.github/workflows/ci.yml
README.md
release/openwiz/README.md
.gitignore
newdir/x.md'
KEEP_WEB_BUILD="$KEEP_ANY
tests/checks/dependencies.md
ci/rust-tests.sh
tests/checks/skills.rs
tests/pending-ticket-2.txt"
KEEP_RUST="$KEEP_WEB_BUILD
skills
.claude/skills/grill
.agents/skills/grill
docs/agents/fleet.md
GLOSSARY.md
tools/github-app/test.py
tools/github-app/manifest.json
Cargo.toml
Cargo.lock"
KEEP_WEB_TEST="$KEEP_ANY
Cargo.toml
Cargo.lock"
s="$tmp/samples"
mkdir -p "$s"
printf '%s\n' "$SAMPLES" | while IFS= read -r p; do
  mkdir -p "$s/$(dirname "$p")"
  case "$p" in
    .claude/skills/grill | .agents/skills/grill) ln -s ../../skills/grill "$s/$p" ;;
    *) echo "synthetic: $p" > "$s/$p" ;;
  esac
done
# Every file ci-reads.txt lists also exists: a job's prune names each missing
# one, so the sample tree must hold them all to reach the skip proof.
while IFS= read -r p; do [ -e "$s/$p" ] || { mkdir -p "$s/$(dirname "$p")"; echo "synthetic: $p" > "$s/$p"; }; done < "$HERE/ci-reads.txt"
git init -q "$s" && git -C "$s" add -A && gitq "$s" commit -qm samples && serve "$s"
S_HEAD="$(git -C "$s" rev-parse HEAD)"
for job in $ALL; do
  case "$job" in
    web-build) keep="$KEEP_WEB_BUILD" ;;
    rust) keep="$KEEP_RUST" ;;
    web-test) keep="$KEEP_WEB_TEST" ;;
  esac
  if ! ci_checkout "$s" "$tmp/pruned" "$S_HEAD" "$tmp/sparse.txt" > /dev/null 2>&1; then bad "skip proof ($job): the checkout failed"; continue; fi
  if ! (cd "$tmp/pruned" && sh "$HERE/prune.sh" "$HERE/ci-reads.txt" "$job" > /dev/null 2>&1); then bad "skip proof ($job): the prune failed"; continue; fi
  left="$(printf '%s\n' "$SAMPLES" | while IFS= read -r p; do [ -e "$tmp/pruned/$p" ] || [ -L "$tmp/pruned/$p" ] && echo "$p"; done | sort)"
  want="$(printf '%s\n' "$keep" | sort)"
  if [ "$left" = "$want" ]; then ok "skip proof ($job): its tree holds exactly the files it reads"; else bad "skip proof ($job): its tree holds [$(echo "$left" | tr '\n' ' ')], want [$(echo "$want" | tr '\n' ' ')]"; fi
  # The proof itself: every path whose change alone skips this job is gone.
  hidden="$(printf '%s\n' "$SAMPLES" | while IFS= read -r p; do
    case " $(printf '%s\n' "$p" | sh "$HERE/classify.sh") " in
      *" $job "*) ;;
      *) if [ -e "$tmp/pruned/$p" ] || [ -L "$tmp/pruned/$p" ]; then echo "$p"; fi ;;
    esac
  done)"
  if [ -z "$hidden" ]; then ok "skip proof ($job): every path it may skip for is gone when it runs"; else bad "skip proof ($job): it may skip for these, yet can read them: $(echo "$hidden" | tr '\n' ' ')"; fi
done

# A fake gh: logs each call, answers the PR from a JSON file through the
# caller's own --jq filter, and fails when told to: FAKE_FAIL=all fails every
# call; FAKE_FAIL=N fails the first N calls counted in FAKE_COUNT (#1309, the
# network fault a rerun passes).
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" <<'GH'
#!/bin/sh
echo "$*" >> "$GH_LOG"
case "${FAKE_FAIL:-}" in
  all) echo "gh: HTTP 502" >&2; exit 1 ;;
  [0-9])
    echo call >> "$FAKE_COUNT"
    [ "$(wc -l < "$FAKE_COUNT")" -gt "$FAKE_FAIL" ] || { echo "gh: net/http: TLS handshake timeout" >&2; exit 1; } ;;
esac
filter=.
prev=
for a in "$@"; do [ "$prev" = --jq ] && filter="$a"; prev="$a"; done
case "$*" in
  *"/pulls/"*) json="$(cat "$FAKE_PR")" ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 2 ;;
esac
printf '%s\n' "$json" | jq -r "$filter"
GH
chmod +x "$tmp/bin/gh"
# No waits between the retries here (ci/retry.sh's RETRY_WAIT); CI's are 5 s, then 10 s.
export GH_LOG="$tmp/gh.log" FAKE_PR="$tmp/pr.json" FAKE_COUNT="$tmp/gh.count" RETRY_WAIT=0

# The bounded retry (#1309): ci/retry.sh ATTEMPTS -- COMMAND runs COMMAND
# until it succeeds or has run ATTEMPTS times, then exits with its last
# status.
RETRY="$ROOT/ci/retry.sh"
cat > "$tmp/flaky" <<'FLAKY'
#!/bin/sh
echo call >> "$FLAKY_COUNT"
[ "$(wc -l < "$FLAKY_COUNT")" -gt "$FLAKY_FAILS" ] || { echo "flaky: ETIMEDOUT" >&2; exit 7; }
echo "answer $*"
FLAKY
chmod +x "$tmp/flaky"
# retry NAME WANT_STATUS WANT_CALLS WANT_OUT FAILS ARGS...: run retry.sh ARGS
# with a command that fails FAILS times first; check its status, how many
# times the command ran and its output.
retry() {
  name="$1" want_status="$2" want_calls="$3" want_out="$4" faults="$5"; shift 5
  : > "$tmp/flaky.count"
  out="$(FLAKY_COUNT="$tmp/flaky.count" FLAKY_FAILS="$faults" sh "$RETRY" "$@" 2> "$tmp/retry.err")"
  status=$?
  calls="$(wc -l < "$tmp/flaky.count" | tr -d ' ')"
  if [ "$status" = "$want_status" ] && [ "$calls" = "$want_calls" ] && [ "$out" = "$want_out" ]; then
    ok "retry: $name"
  else
    bad "retry: $name: want exit $want_status, $want_calls calls, '$want_out'; got exit $status, $calls calls, '$out' ($(tail -n 1 "$tmp/retry.err"))"
  fi
}
retry "a first success runs once" 0 1 "answer a b" 0 3 -- "$tmp/flaky" a b
retry "one network fault, then the answer" 0 2 "answer a" 1 3 -- "$tmp/flaky" a
retry "two faults, then the answer on the last attempt" 0 3 "answer a" 2 3 -- "$tmp/flaky" a
retry "every attempt failing stops at the bound with the last status" 7 3 "" 5 3 -- "$tmp/flaky" a
retry "one attempt is no retry" 7 1 "" 1 1 -- "$tmp/flaky" a

# A synthetic history: release-x is old; main has code since; PR heads
# against main: docs-only, evidence-only, skills-only, a Rust test, the web
# app, the runner kit's README.
g="$tmp/repo"
git init -q -b main "$g"
gc() { gitq "$g" commit -qm "$1"; }
mkdir -p "$g/crates" "$g/private/evidence"
echo v1 > "$g/crates/a.rs"; git -C "$g" add -A; gc r0
R0="$(git -C "$g" rev-parse HEAD)"
echo v2 > "$g/crates/a.rs"; git -C "$g" add -A; gc m1
M1="$(git -C "$g" rev-parse HEAD)"
head_from() {
  git -C "$g" checkout -q "$1"
  mkdir -p "$g/$(dirname "$2")"
  echo change > "$g/$2"; git -C "$g" add -A; gc "$2"
  git -C "$g" rev-parse HEAD
}
H1="$(head_from "$M1" STATUS.md)"
H2="$(head_from "$M1" private/evidence/x.md)"
M2="$(head_from "$M1" crates/b.rs)"
H3="$(head_from "$R0" STATUS.md)"
H4="$(head_from "$M1" skills)"
H5="$(head_from "$M1" tests/checks/skills.rs)"
H6="$(head_from "$M1" crates/core/src/app.rs)"
H7="$(head_from "$M1" ci/runner/README.md)"
UNKNOWN=0123456789abcdef0123456789abcdef01234567

# pr DRAFT BASE_REF BASE_SHA HEAD_SHA: what the live API says about the PR.
pr() { printf '{"number":1,"draft":%s,"base":{"ref":"%s","sha":"%s"},"head":{"sha":"%s"}}\n' "$@" > "$FAKE_PR"; }
# decide NAME WANT EVENT ACTION ATTEMPT EVENT_BASE_REF EVENT_BASE EVENT_HEAD:
# WANT is the three jobs' answers, in the workflow's order: each true (run
# it), false (skip it) or fail. A cheap `false` needs everything plain: a
# ready PR against main, the event's base and head the live ones, a first
# attempt, not ready_for_review, and no changed path the job reads. A push
# to main and the nightly run (schedule) always run every job.
decide() {
  name="$1" want="$2"; shift 2
  got=
  for job in $ALL; do
    one="$(cd "$g" && PATH="$tmp/bin:$PATH" JOB="$job" EVENT="$1" ACTION="$2" RUN_ATTEMPT="$3" EVENT_BASE_REF="$4" EVENT_BASE="$5" EVENT_HEAD="$6" REPO=owner/repo PR=1 sh "$HERE/decide.sh" 2> "$tmp/decide.err")" || one=fail
    got="${got:+$got }$one"
  done
  if [ "$got" = "$want" ]; then ok "decide: $name: $want"; else bad "decide: $name: want $want, got $got ($(tail -n 1 "$tmp/decide.err"))"; fi
}
pr false main "$M1" "$H1"
decide "docs-only against main" "false false false" pull_request synchronize 1 main "$M1" "$H1"
pr false main "$R0" "$H1"
decide "a code change against main" "true true true" pull_request synchronize 1 main "$R0" "$H1"
pr false main "$M1" "$H2"
decide "evidence-only against main" "false false false" pull_request opened 1 main "$M1" "$H2"
decide "ready_for_review on an evidence-only diff runs everything" "true true true" pull_request ready_for_review 1 main "$M1" "$H2"
# Per job (#177): each runs only when a path it reads changed.
pr false main "$M1" "$H4"
decide "skills-only against main: web-build and rust" "true true false" pull_request synchronize 1 main "$M1" "$H4"
decide "skills-only, reopened" "true true false" pull_request reopened 1 main "$M1" "$H4"
pr false main "$M1" "$H5"
decide "a Rust test against main: web-build and rust" "true true false" pull_request opened 1 main "$M1" "$H5"
pr false main "$M1" "$H6"
decide "core code against main: every job" "true true true" pull_request synchronize 1 main "$M1" "$H6"
pr false main "$M1" "$H7"
decide "the runner kit's README against main: no job" "false false false" pull_request synchronize 1 main "$M1" "$H7"
# Round 2: reruns, other bases, and an event that is not the live PR.
pr false main "$M1" "$H2"
decide "a rerun of an opened run on a now-ready evidence-only PR runs everything" "true true true" pull_request opened 2 main "$M1" "$H2"
decide "a rerun of a converted_to_draft run, now ready, runs everything" "true true true" pull_request converted_to_draft 3 main "$M1" "$H2"
decide "no run attempt runs everything" "true true true" pull_request opened '' main "$M1" "$H2"
decide "a run attempt that is not a number runs everything" "true true true" pull_request opened x main "$M1" "$H2"
pr false main "$M1" "$H4"
decide "a rerun of a skills-only run runs every job" "true true true" pull_request synchronize 2 main "$M1" "$H4"
pr false release-x "$R0" "$H3"
decide "a docs-only PR to release-* runs everything" "true true true" pull_request opened 1 release-x "$R0" "$H3"
pr false main "$M2" "$H1"
decide "an event base SHA that is not the live one runs everything" "true true true" pull_request synchronize 1 main "$M1" "$H1"
pr false release-x "$R0" "$H1"
decide "after a retarget to an older base: runs everything" "true true true" pull_request reopened 1 release-x "$R0" "$H1"
decide "a rerun of a run from before a retarget runs everything" "true true true" pull_request synchronize 2 main "$M1" "$H1"
decide "a first run whose base ref is no longer the PR's runs everything" "true true true" pull_request synchronize 1 main "$M1" "$H1"
pr false main "$M1" "$H2"
decide "a run whose head is no longer the PR's runs everything" "true true true" pull_request synchronize 1 main "$M1" "$H1"
pr false main "$UNKNOWN" "$H2"
decide "a live base this clone does not have runs everything" "true true true" pull_request synchronize 1 main "$UNKNOWN" "$H2"
pr false release-null-fix "$R0" "$H3"
decide "a ready PR to release-null-fix (a valid name) runs everything" "true true true" pull_request opened 1 release-null-fix "$R0" "$H3"
pr false main-null "$M1" "$H1"
decide "a base named main-null runs everything" "true true true" pull_request synchronize 1 main-null "$M1" "$H1"
# Drafts and bad answers fail.
pr true main "$M1" "$H2"
decide "a draft fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
decide "a draft fails, even on ready_for_review's rerun" "fail fail fail" pull_request ready_for_review 2 main "$M1" "$H2"
printf '{"draft":false,"base":null,"head":{"sha":"%s"}}\n' "$H2" > "$FAKE_PR"
decide "no base in the answer fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":false,"base":{"ref":"","sha":"%s"},"head":{"sha":"%s"}}\n' "$M1" "$H2" > "$FAKE_PR"
decide "an empty base ref in the answer fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":null}\n' > "$FAKE_PR"
decide "no draft state in the answer fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":"false","base":{"ref":"main","sha":"%s"},"head":{"sha":"%s"}}\n' "$M1" "$H2" > "$FAKE_PR"
decide "a draft state that is a string fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":false,"base":{"ref":"main","sha":7},"head":{"sha":"%s"}}\n' "$H2" > "$FAKE_PR"
decide "a base SHA that is a number fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":false,"base":{"ref":"main","sha":"%s"}}\n' "$M1" > "$FAKE_PR"
decide "no head in the answer fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
printf '{"draft":false,"base":{"ref":"main","sha":"%s"},"head":{"sha":"%s"}}\n' "$M1 x" "$H2" > "$FAKE_PR"
decide "a base SHA with a space fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
pr false main "$M1" "$H2"
FAKE_FAIL=all decide "an API error fails" "fail fail fail" pull_request synchronize 1 main "$M1" "$H2"
# The PR read retries a network fault (#1309), at most 3 times, and still
# fails closed: a read that never succeeds is never a skip.
# reread NAME FAILS WANT WANT_CALLS: each job's answer and its gh calls.
reread() {
  name="$1" faults="$2" want="$3" want_calls="$4"
  got='' calls=''
  for job in $ALL; do
    : > "$FAKE_COUNT"; : > "$GH_LOG"
    one="$(cd "$g" && PATH="$tmp/bin:$PATH" FAKE_FAIL="$faults" JOB="$job" EVENT=pull_request ACTION=synchronize RUN_ATTEMPT=1 EVENT_BASE_REF=main EVENT_BASE="$M1" EVENT_HEAD="$H2" REPO=owner/repo PR=1 sh "$HERE/decide.sh" 2> "$tmp/decide.err")" || one=fail
    got="${got:+$got }$one"
    calls="${calls:+$calls }$(grep -c '^api ' "$GH_LOG")"
  done
  if [ "$got" = "$want" ] && [ "$calls" = "$want_calls" ]; then ok "decide: $name: $want, gh calls $calls"; else bad "decide: $name: want $want with gh calls $want_calls, got $got with $calls ($(tail -n 1 "$tmp/decide.err"))"; fi
}
pr false main "$M1" "$H2"
reread "one TLS timeout reading the PR, then the answer" 1 "false false false" "2 2 2"
reread "two faults, then the answer on the third read" 2 "false false false" "3 3 3"
reread "three faults: fails after exactly three reads" 3 "fail fail fail" "3 3 3"
reread "every read failing: fails after three reads, never a skip" all "fail fail fail" "3 3 3"
pr true main "$M1" "$H2"
reread "a draft, read once, still fails at once" 1 "fail fail fail" "2 2 2"
pr false main "$M1" "$H2"
# The plain case for the test selector (#432): with DECIDE_PLAIN set,
# decide.sh writes `plain` there only once every check has passed, and
# removes a file left from before; every other answer leaves no file, so the
# selector can't narrow the tests. plain NAME WANT EVENT ACTION ATTEMPT
# EVENT_BASE_REF EVENT_BASE EVENT_HEAD: WANT is `plain` or `none`.
plain() {
  name="$1" want="$2"; shift 2
  echo stale > "$tmp/plain"
  (cd "$g" && PATH="$tmp/bin:$PATH" DECIDE_PLAIN="$tmp/plain" JOB=rust EVENT="$1" ACTION="$2" RUN_ATTEMPT="$3" EVENT_BASE_REF="$4" EVENT_BASE="$5" EVENT_HEAD="$6" REPO=owner/repo PR=1 sh "$HERE/decide.sh" > /dev/null 2>&1) || true
  if [ -f "$tmp/plain" ]; then got="$(cat "$tmp/plain")"; else got=none; fi
  if [ "$got" = "$want" ]; then ok "decide: the selector's plain case: $name: $want"; else bad "decide: the selector's plain case: $name: want $want, got $got"; fi
}
pr false main "$M1" "$H5"
plain "a ready PR's push against main" plain pull_request synchronize 1 main "$M1" "$H5"
plain "opened" plain pull_request opened 1 main "$M1" "$H5"
plain "reopened" plain pull_request reopened 1 main "$M1" "$H5"
plain "docs-only (its jobs skip)" plain pull_request synchronize 1 main "$M1" "$H5"
plain "ready_for_review" none pull_request ready_for_review 1 main "$M1" "$H5"
plain "a rerun" none pull_request synchronize 2 main "$M1" "$H5"
plain "an odd attempt" none pull_request synchronize x main "$M1" "$H5"
plain "a stale event base" none pull_request synchronize 1 main "$R0" "$H5"
plain "a stale event head" none pull_request synchronize 1 main "$M1" "$H4"
plain "an event base ref other than main" none pull_request synchronize 1 release-x "$M1" "$H5"
plain "a push to main" none push '' 1 '' "$M1" "$H5"
plain "the nightly run" none schedule '' 1 '' '' "$M1"
plain "a merge group" none merge_group checks_requested 1 '' "$M1" "$H5"
pr false release-x "$R0" "$H5"
plain "a PR to release-*" none pull_request synchronize 1 release-x "$R0" "$H5"
pr true main "$M1" "$H5"
plain "a draft" none pull_request synchronize 1 main "$M1" "$H5"
pr false main "$UNKNOWN" "$H5"
plain "a live base this clone does not have" none pull_request synchronize 1 main "$UNKNOWN" "$H5"
pr false main "$M1" "$H5"
FAKE_FAIL=all plain "an API error" none pull_request synchronize 1 main "$M1" "$H5"
pr false main "$M1" "$H2"
# decide.sh without ci/retry.sh beside it (a broken checkout): fails, never skips.
mkdir -p "$tmp/alone/.github/actions/docs-only"
cp "$HERE/decide.sh" "$HERE/classify.sh" "$HERE/ci-reads.txt" "$tmp/alone/.github/actions/docs-only/"
alone=
for job in $ALL; do
  one="$(cd "$g" && PATH="$tmp/bin:$PATH" JOB="$job" EVENT=pull_request ACTION=synchronize RUN_ATTEMPT=1 EVENT_BASE_REF=main EVENT_BASE="$M1" EVENT_HEAD="$H2" REPO=owner/repo PR=1 sh "$tmp/alone/.github/actions/docs-only/decide.sh" 2> /dev/null)" || one=fail
  alone="${alone:+$alone }$one"
done
if [ "$alone" = "fail fail fail" ]; then ok "decide: no ci/retry.sh fails every job"; else bad "decide: no ci/retry.sh answered $alone"; fi
# Always on main (#177): every push and the nightly run, first attempt or not.
decide "a docs-only push to main runs everything" "true true true" push '' 1 '' "$M1" "$H1"
decide "a skills-only push to main runs everything" "true true true" push '' 1 '' "$M1" "$H4"
decide "a push of code" "true true true" push '' 1 '' "$R0" "$H1"
decide "a rerun of a docs-only push runs everything" "true true true" push '' 2 '' "$M1" "$H1"
decide "the nightly run runs everything" "true true true" schedule '' 1 '' '' "$M1"
decide "a rerun of the nightly run runs everything" "true true true" schedule '' 2 '' '' "$M1"
# Merge groups (#190): the merge queue re-tests a pull request on top of the
# latest main just before it lands, so a merge group always runs every job,
# whatever changed, on every attempt. It has no pull request to read: the
# action passes no PR, base ref or base for it, and its head is the group's.
: > "$GH_LOG"
decide "a docs-only merge group runs everything" "true true true" merge_group checks_requested 1 '' '' "$H1"
decide "an evidence-only merge group runs everything" "true true true" merge_group checks_requested 1 '' '' "$H2"
decide "a skills-only merge group runs everything" "true true true" merge_group checks_requested 1 '' '' "$H4"
decide "the runner kit's README in a merge group runs everything" "true true true" merge_group checks_requested 1 '' '' "$H7"
decide "a rerun of a merge group runs everything" "true true true" merge_group checks_requested 2 '' '' "$H1"
pr false main "$M1" "$H1"
decide "a merge group with an event base and ref, as a pull request has, runs everything" "true true true" merge_group checks_requested 1 main "$M1" "$H1"
decide "a merge group with another action runs everything" "true true true" merge_group destroyed 1 '' '' "$H1"
decide "a merge group with no action, attempt or head runs everything" "true true true" merge_group '' '' '' '' ''
pr true main "$M1" "$H1"
decide "a merge group runs everything even when the live answer says draft" "true true true" merge_group checks_requested 1 main "$M1" "$H1"
FAKE_FAIL=all decide "a merge group runs everything even when GitHub's API fails" "true true true" merge_group checks_requested 1 '' '' "$H1"
: > "$GH_LOG"
never=
for job in $ALL; do
  one="$(cd "$g" && PATH="$tmp/bin:$PATH" FAKE_FAIL=all JOB="$job" EVENT=merge_group ACTION=checks_requested RUN_ATTEMPT=1 EVENT_BASE_REF='' EVENT_BASE='' EVENT_HEAD="$H1" REPO=owner/repo PR='' sh "$HERE/decide.sh" 2> /dev/null)" || one=fail
  never="$never$one "
done
if [ "$never" = "true true true " ] && [ ! -s "$GH_LOG" ]; then ok "decide: a merge group never reads a pull request"; else bad "decide: a merge group answered [$never] and read GitHub [$(tr '\n' ';' < "$GH_LOG")]"; fi
decide "an unknown event fails" "fail fail fail" workflow_dispatch '' 1 main "$M1" "$H2"
decide "no event fails" "fail fail fail" '' '' 1 main "$M1" "$H2"
decide "an event named like a merge group fails" "fail fail fail" merge_group_x checks_requested 1 '' '' "$H1"
# A job that isn't one of the three fails, whatever the event.
for job in nobody '' web; do
  pr false main "$M1" "$H1"
  for event in pull_request push schedule merge_group; do
    if (cd "$g" && PATH="$tmp/bin:$PATH" JOB="$job" EVENT="$event" ACTION=synchronize RUN_ATTEMPT=1 EVENT_BASE_REF=main EVENT_BASE="$M1" EVENT_HEAD="$H1" REPO=owner/repo PR=1 sh "$HERE/decide.sh" > /dev/null 2>&1); then
      bad "decide accepted the job '$job' on $event"
    else
      ok "decide refuses the job '$job' on $event"
    fi
  done
done
# The site step (#1251): the release proofs' step runs only when a changed path is one it reads, asked as decide.sh asks for
# web-test, with classify.sh answering for the site's rows only
# (CLASSIFY_STEP=site). Every edge decide.sh runs everything for (a push to
# main, the nightly run, a merge group, a rerun, ready_for_review, another
# base, a stale base or head) runs it too: one decision, one place.
H8="$(head_from "$M1" tests/fixtures/release/clean/README.md)"
H9="$(head_from "$M1" tools/release/test.py)"
H10="$(head_from "$M1" crates/c.rs)"
site_decide() {
  name="$1" want="$2"; shift 2
  got="$(cd "$g" && PATH="$tmp/bin:$PATH" CLASSIFY_STEP=site JOB=web-test EVENT="$1" ACTION="$2" RUN_ATTEMPT="$3" EVENT_BASE_REF="$4" EVENT_BASE="$5" EVENT_HEAD="$6" REPO=owner/repo PR=1 sh "$HERE/decide.sh" 2> "$tmp/decide.err")" || got=fail
  if [ "$got" = "$want" ]; then ok "site step: $name: $want"; else bad "site step: $name: want $want, got $got ($(tail -n 1 "$tmp/decide.err"))"; fi
}
pr false main "$M1" "$H8"
site_decide "the release fixture against main runs it" true pull_request synchronize 1 main "$M1" "$H8"
pr false main "$M1" "$H9"
site_decide "the release proofs against main run it" true pull_request synchronize 1 main "$M1" "$H9"
pr false main "$M1" "$H6"
site_decide "core code against main skips it" false pull_request synchronize 1 main "$M1" "$H6"
site_decide "a rerun of core code runs it" true pull_request synchronize 2 main "$M1" "$H6"
site_decide "ready_for_review on core code runs it" true pull_request ready_for_review 1 main "$M1" "$H6"
pr false main "$M1" "$H10"
site_decide "a crate against main skips it" false pull_request opened 1 main "$M1" "$H10"
pr false main "$M2" "$H10"
site_decide "a crate whose event base is not the live one runs it" true pull_request synchronize 1 main "$M1" "$H10"
pr false release-x "$M1" "$H10"
site_decide "a crate against release-x runs it" true pull_request opened 1 release-x "$M1" "$H10"
site_decide "a push of a crate to main runs it" true push '' 1 '' "$M1" "$H10"
site_decide "the nightly run runs it" true schedule '' 1 '' '' "$M1"
site_decide "a merge group of a crate runs it" true merge_group checks_requested 1 '' '' "$H10"
pr true main "$M1" "$H8"
site_decide "a draft fails" fail pull_request synchronize 1 main "$M1" "$H8"

# On the checkout CI makes (#334): decide.sh's diff needs only commits and
# trees, so a blobless, sparse clone whose remote is gone gives the same
# answers as the full one.
serve "$g"
full_g="$g"
for case in "docs-only:false false false:$M1:$H1" "skills-only:true true false:$M1:$H4" "core code:true true true:$M1:$H6" "a code change:true true true:$R0:$H1"; do
  IFS=: read -r name want base head <<EOF
$case
EOF
  if ci_checkout "$full_g" "$tmp/gsparse" "$head" "$tmp/sparse.txt" > /dev/null 2>&1; then
    pr false main "$base" "$head"
    g="$tmp/gsparse"
    decide "on CI's checkout, $name" "$want" pull_request synchronize 1 main "$base" "$head"
    g="$full_g"
  else
    bad "decide on CI's checkout, $name: the checkout failed"
  fi
done

# The skip proof, end to end: a job that reads a file it may skip for fails
# its run on main, as the action runs it (decide, then the prune, then the
# job's step), while a step reading a file it does read passes.
# run_on_main JOB FILE [EVENT]: check out as CI does (#334), decide as a push
# to main (or EVENT, as the action passes it: a merge group has no base),
# prune, then read FILE. Exit 0 when it read FILE, 1 when it couldn't, 2 when
# the checkout, decide or the prune failed.
run_on_main() {
  ci_checkout "$s" "$tmp/run" "$S_HEAD" "$tmp/sparse.txt" > /dev/null 2>&1 || return 2
  (
    cd "$tmp/run" || exit 1
    base="$(git rev-parse HEAD)" action=''
    [ "${3:-push}" != merge_group ] || base='' action=checks_requested
    code="$(JOB="$1" EVENT="${3:-push}" ACTION="$action" RUN_ATTEMPT=1 EVENT_BASE_REF='' EVENT_BASE="$base" EVENT_HEAD="$(git rev-parse HEAD)" REPO=owner/repo PR='' sh "$HERE/decide.sh" 2> /dev/null)" || exit 2
    [ "$code" = true ] || exit 2
    sh "$HERE/prune.sh" "$HERE/ci-reads.txt" "$1" > /dev/null 2>&1 || exit 2
    cat "$2" > /dev/null 2>&1
  )
}
# The run must get as far as the read: exit 2 (the checkout, decide or the
# prune failed) proves nothing about the skip proof.
for case in 'web-test skills' 'web-test docs/agents/fleet.md' 'web-test tests/checks/skills.rs' 'web-build GLOSSARY.md' 'web-build Cargo.lock' 'rust STATUS.md' 'rust private/orchestration/HANDOFF.md' 'web-test private/evidence/openwiz-0.0.1/ticket-1/red-run.log' 'rust ci/runner/README.md'; do
  # shellcheck disable=SC2086 # two words, split on purpose
  set -- $case
  run_on_main "$1" "$2"
  case $? in 1) ok "skip proof: $1 reading $2, which it may skip for, fails on main" ;; 0) bad "skip proof: $1 read $2, which it may skip for, and passed on main" ;; *) bad "skip proof: $1 on main: the checkout, decide or the prune failed" ;; esac
done
for case in 'web-test crates/core/src/lib.rs' 'web-test Cargo.lock' 'rust skills' 'web-build tests/checks/skills.rs' 'rust tests/checks/dependencies.md'; do
  # shellcheck disable=SC2086 # two words, split on purpose
  set -- $case
  if run_on_main "$1" "$2"; then ok "control: $1 reading $2, which it reads, passes on main"; else bad "control: $1 reading $2, which it reads, failed on main"; fi
done
# A merge group (#190) runs the same prune: a job still can't read a path it
# may skip for, and still reads what it does.
for case in 'web-test skills' 'rust STATUS.md' 'web-build GLOSSARY.md'; do
  # shellcheck disable=SC2086 # two words, split on purpose
  set -- $case
  run_on_main "$1" "$2" merge_group
  case $? in 1) ok "skip proof: $1 reading $2, which it may skip for, fails in a merge group" ;; 0) bad "skip proof: $1 read $2, which it may skip for, and passed in a merge group" ;; *) bad "skip proof: $1 in a merge group: the checkout, decide or the prune failed" ;; esac
done
for case in 'web-test crates/core/src/lib.rs' 'rust skills' 'web-build tests/checks/skills.rs'; do
  # shellcheck disable=SC2086 # two words, split on purpose
  set -- $case
  if run_on_main "$1" "$2" merge_group; then ok "control: $1 reading $2, which it reads, passes in a merge group"; else bad "control: $1 reading $2, which it reads, failed in a merge group"; fi
done

# #2724: a cold single-shard lane must prepare the CLI even when lint/build
# was skipped for an unrelated change. Execute both real workflow scripts;
# fake only external builders/test consumers, which require the executable.
if python3 -I - "$HERE" <<'PY_SINGLE_SHARD'
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import test_lanes
import test_workflow

consumer = '''#!PYTHON
import os
from pathlib import Path
import subprocess
import sys
args = sys.argv[1:]
if Path(sys.argv[0]).name == 'cargo':
    if args[:1] == ['build'] and '--bins' in args:
        if os.environ.get('BUILD_FAIL'): sys.exit(9)
        binary = Path('target/debug/openwiz')
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text('#!/bin/sh\\nexit 0\\n')
        binary.chmod(0o755)
elif '--only' in args:
    if 'rust:test:loops' not in ' '.join(args): sys.exit(8)
    binary = Path('target/debug/openwiz')
    if not binary.is_file():
        sys.exit('missing target/debug/openwiz before selected loop tests')
    subprocess.run([str(binary.resolve())], check=True)
    Path('consumed').write_text('loops ran with the prepared CLI')
else:
    os.execv(sys.executable, [sys.executable, *args])
'''.replace('PYTHON', sys.executable)

for job in ('rust',):
    steps = [s for s in re.split(r'(?=^      - )', test_workflow.jobs()[job], flags=re.M)
             if s.startswith('      - name: Run cargo test --workspace\n')]
    assert len(steps) == 1, f'{job}: expected one test step'
    script = steps[0].split('        run: |\n', 1)[1]
    script = '\n'.join(line[10:] for line in script.splitlines())
    for case, overrides in [('normal', {}), ('failed build', {'BUILD_FAIL': '1'})]:
        fixture = test_lanes.Lanes('test_every_planned_job_and_skill_member_passed')
        fixture.setUp()
        try:
            root = fixture.path
            plan = fixture.plan
            plan['run'].update(event='pull_request', action='synchronize',
                               base='1' * 40, pull_request=909)
            plan['diff'] = {'state': 'read', 'paths': ['skills/triage/SKILL.md']}
            plan['selection'] = {'mode': 'selected'}
            plan['lanes']['rust']['tests'] = ['rust:test:loops']
            raw = json.dumps(plan)
            (root/'ci-selection.json').write_text(raw)
            fixture.dispatch.update(**{'lint-rust': False},
                                    plan_sha256=hashlib.sha256(raw.encode()).hexdigest())
            (root/'ci-dispatch.json').write_text(json.dumps(fixture.dispatch))
            (root/'.github').symlink_to(test_workflow.ROOT/'.github', target_is_directory=True)
            (root/'ci-plan').symlink_to(root, target_is_directory=True)
            bin = root/'bin'
            bin.mkdir()
            for name in ('cargo', 'sh', 'python3'):
                (bin/name).write_text(consumer)
                (bin/name).chmod(0o755)
            env = dict(os.environ, PATH=str(bin) + os.pathsep + os.environ['PATH'],
                       RUNNER_TEMP=str(root), SHARDS='1', SHARD='1',
                       GITHUB_RUN_ID=str(plan['run']['id']), GITHUB_RUN_ATTEMPT='1',
                       GITHUB_EVENT_NAME='pull_request', **overrides)
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script],
                                    cwd=root, env=env, capture_output=True, text=True)
            if case == 'failed build':
                assert result.returncode != 0 and 'exit status 9' in result.stderr, result.stderr
                assert not (root/'consumed').exists(), 'tests ran after a failed build'
            else:
                assert result.returncode == 0, f'{job} {case}: {result.stderr}'
                assert (root/'consumed').read_text() == 'loops ran with the prepared CLI'
            print(f'ok   single-shard {job}: {case}')
        finally:
            fixture.doCleanups()
PY_SINGLE_SHARD
then ok "single-shard Rust binary prerequisites"; else bad "single-shard Rust binary prerequisites"; fi

# Rust runner's orchestration proofs are unrelated to the classifier's
# always-run set. Keep them in the ordinary full command and in the release
# lane; --always retains classifier/selector/workflow proofs without them.
if [ "$mode" = all ]; then
  if sh "$HERE/test_rust_runner.sh"; then ok "Rust runner fixtures"; else bad "Rust runner fixtures"; fi
fi

# X5 moves workflow boundary coverage to executable plan/dispatch/gate proofs.
# The classifier, prune/checkout, live-event decider and Rust-runner fixture
# cases above retain their coverage; no lane re-runs the action's decision.
for proof in test_gate.py test_plan.py test_lanes.py test_execution.py test_release_prune.py test_workflow.py; do
  if python3 -I "$HERE/$proof"; then ok "X5: $proof"; else bad "X5: $proof"; fi
done
# WM1 (#1056): the war room's split checker, on its synthetic trees (fast, offline).
if python3 -I "$ROOT/ci/wizroom/test_split.py"; then ok "WM1: split checker"; else bad "WM1: split checker"; fi
if python3 -I "$ROOT/tools/collector/test_runtime.py"; then ok "WM2: shared runtime equivalence"; else bad "WM2: shared runtime equivalence"; fi
if node --test "$ROOT/.github/workflows/ci.test.mjs" "$ROOT/.github/workflows/ci-safety-watch.test.mjs"; then
  ok "CI nightly admission and push/PR coalescing"
else bad "CI concurrency or safety watcher"; fi
if [ "$fails" -ne 0 ]; then echo "$fails failed"; exit 1; fi
echo "all ok"
