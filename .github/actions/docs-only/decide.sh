#!/bin/sh
# Decide (#70, #86, #177): one job's first answer. Run in the full-history
# checkout; prints `true` (run this job) or `false` (skip it: its steps don't
# run, and its check passes), or fails the job. Env: JOB (web-build, rust or
# web-test), EVENT, ACTION, RUN_ATTEMPT, REPO, PR, EVENT_BASE_REF,
# EVENT_BASE and EVENT_HEAD (the event's), and GH_TOKEN.
#
# A PR is read live, not from the event. A draft fails, so none of its
# required checks can show as passed (a skipped job counts as success).
# A cheap `false` needs everything plain:
# - the first attempt (every rerun runs everything);
# - a PR: ready, against main, the event's base SHA and head the live ones,
#   and not `ready_for_review` (marking ready runs everything);
# - then classify.sh finds no changed path this job reads, judged on the
#   diff against that base.
# Always on main (#177): a push to main (the only branch CI runs on for
# pushes) and the nightly run (schedule, on main) run every job. So does a
# merge group (#190): the merge queue's re-test of a pull request on top of
# the latest main, just before it lands; it reads no pull request.
# Anything else runs everything. Any other event or job, or an API answer
# whose fields are not of the expected types, fails.
# The PR read is retried (#1309): up to 3 reads, 5 s then 10 s apart
# (ci/retry.sh), for a network fault a rerun would pass. A read that never
# succeeds still fails, so it can never skip a job.
# With DECIDE_PLAIN set to a file (#432, the action), decide.sh writes
# `plain` there once every check above has passed, and only then: the test
# selector (ci/select/) may narrow the tests only on that plain case. Any
# other answer leaves the file absent, so it can never narrow one.
set -eu
HERE="$(dirname "$0")"
RETRY="$HERE/../../../ci/retry.sh"
fail() { echo "::error::$*" >&2; exit 1; }
full() { echo "decide: $*: the full acceptance set" >&2; echo true; exit 0; }
[ -z "${DECIDE_PLAIN:-}" ] || rm -f -- "$DECIDE_PLAIN"
case "${JOB:-}" in
  web-build | rust | web-test) ;;
  *) fail "decide: unknown job '${JOB:-}'" ;;
esac
case "$EVENT" in
  push) full "a push to main: always every job" ;;
  schedule) full "the nightly run: always every job" ;;
  merge_group) full "a merge group: always every job" ;;
  pull_request)
    live="$(sh "$RETRY" 3 -- gh api "repos/$REPO/pulls/$PR" --jq '
      if (.draft | type) == "boolean" and (.base.ref | type) == "string"
        and (.base.sha | type) == "string" and (.head.sha | type) == "string"
      then "\(.draft) \(.base.ref) \(.base.sha) \(.head.sha)"
      else error("unexpected types") end')"
    # shellcheck disable=SC2086 # four words, split on purpose
    set -- $live
    [ "$#" -eq 4 ] || fail "decide: unexpected answer '$live'"
    draft="$1" ref="$2" base="$3" head="$4"
    case "$draft" in
      false) ;;
      true) fail "PR #$PR is a draft: the acceptance set does not run. Mark it ready for review to start a full run." ;;
      *) fail "decide: unexpected draft state '$draft'" ;;
    esac
    echo "decide: PR #$PR, ready for review, against $ref @ $base, head $head" >&2
    ;;
  *) fail "decide: unknown event '$EVENT'" ;;
esac
[ "$RUN_ATTEMPT" = 1 ] || full "attempt '$RUN_ATTEMPT', not the first"
[ "$ACTION" != ready_for_review ] || full "ready_for_review"
[ "$ref" = main ] || full "the base is $ref, not main"
[ "$EVENT_BASE_REF" = main ] || full "the event's base is $EVENT_BASE_REF, not main"
[ "$EVENT_BASE" = "$base" ] || full "the event's base $EVENT_BASE is not the live $base"
[ "$EVENT_HEAD" = "$head" ] || full "the event's head $EVENT_HEAD is not the live $head"
git cat-file -e "$EVENT_BASE^{commit}" 2>/dev/null || full "base $EVENT_BASE is not in this clone"
[ -z "${DECIDE_PLAIN:-}" ] || echo plain > "$DECIDE_PLAIN"
changed="$(mktemp)"
trap 'rm -f "$changed"' EXIT
git diff --no-renames --name-only "$EVENT_BASE...$EVENT_HEAD" > "$changed"
cat "$changed" >&2
jobs="$(sh "$HERE/classify.sh" < "$changed")"
echo "decide: this change runs: $jobs" >&2
case " $jobs " in
  *" $JOB "*) echo true ;;
  *) echo "decide: $JOB reads none of it: skipped" >&2; echo false ;;
esac
