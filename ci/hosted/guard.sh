#!/bin/sh
# The runner guard (#1265): every CI job's first step after its checkout, on
# every runner, before the docs step or anything else the change ships runs.
#
# 1. A fork's pull request never runs on a runner that is not GitHub's own.
#    ci.yml's runner choice already sends one to ubuntu-24.04; this fails the
#    job if that choice is ever lost. Trusted: a push, the nightly run, a
#    merge group, a manual run, and a pull request whose head is this
#    repository. Anything else (a fork, an unknown head, another event) is
#    untrusted, and an untrusted run on a runner that is not GitHub's own, or
#    whose kind is unknown, exits 1.
#    A tripwire, not the wall: a pull request can change ci.yml and this
#    script. The wall is the repository's settings (ci/runner/README.md).
# 2. GitHub's cache, the trust rule the PC's store has: only a push or the
#    nightly run on main may save it; everything else only restores. It is
#    used on GitHub's own runners and on one trusted hosted service, Jog
#    (#2467, service.sh). Jog stays "not GitHub's own" for rule 1, so a
#    fork's pull request still fails there, and saves stay main-only.
#
# Reads GITHUB_EVENT_NAME, GITHUB_REF, GITHUB_REPOSITORY, RUNNER_ENVIRONMENT
# (github-hosted or self-hosted, as GitHub sets it), RUNNER_NAME,
# JOG_RUNNER_SCOPE and HEAD_REPO (ci.yml's
# github.event.pull_request.head.repo.full_name). Appends to $GITHUB_OUTPUT:
#   hosted=true|false   this is one of GitHub's own runners
#   save=true|false     this job may save GitHub's cache
#   service=github|jog|none   whose runner: GitHub's, Jog's, or another
#                       (the PC, Namespace); GitHub's cache is used unless none
# Exits 2 when it can't read what it needs.
set -eu
fail() { echo "runner guard: $*" >&2; exit 2; }
out="${GITHUB_OUTPUT:-}" repo="${GITHUB_REPOSITORY:-}"
[ -n "$out" ] || fail "GITHUB_OUTPUT is not set"
[ -n "$repo" ] || fail "GITHUB_REPOSITORY is not set"
event="${GITHUB_EVENT_NAME:-}" ref="${GITHUB_REF:-}" head="${HEAD_REPO:-}" kind="${RUNNER_ENVIRONMENT:-}"

# shellcheck source=service.sh
. "$(dirname "$0")/service.sh"
service="$(runner_service)" hosted=false
[ "$service" = github ] && hosted=true
case "$event" in
  push | schedule | merge_group | workflow_dispatch) trusted=true from="this repository" ;;
  pull_request) if [ -n "$head" ] && [ "$head" = "$repo" ]; then trusted=true from="this repository"; else trusted=false from="${head:-an unknown repository}"; fi ;;
  *) trusted=false from="${head:-an unknown repository}" ;;
esac
if [ "$trusted" = false ] && [ "$hosted" = false ]; then
  echo "runner guard: ${event:-an unknown event} from $from on a ${kind:-unknown} runner: only GitHub's own runners may run it" >&2
  exit 1
fi
save=false
if [ "$service" != none ] && [ "$ref" = refs/heads/main ]; then
  case "$event" in push | schedule) save=true ;; esac
fi
printf 'hosted=%s\nsave=%s\nservice=%s\n' "$hosted" "$save" "$service" >> "$out"
echo "runner guard: ${event:-an unknown event} from $from on a ${kind:-unknown} runner ($service): ok; GitHub's cache: $([ "$service" = none ] && echo "not used" || { [ "$save" = true ] && echo "restore and save" || echo "restore only"; })"
