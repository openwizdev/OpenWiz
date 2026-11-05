#!/bin/sh
# The jobs' side of the PC's cache store (#180). ci.yml runs it:
#
#   cache.sh restore NAME PATH...   unpack cache NAME from the store into the
#                                   PATHs, if this runner has a store and it
#                                   holds NAME; else a cold start
#   cache.sh save NAME PATH...      pack the PATHs as cache NAME and leave it,
#                                   with the token GitHub signs for this job,
#                                   for this runner's root to judge
#
# Each PATH is absolute, under $HOME, and the same in a cache's save and its
# restore. A runner without a store (GitHub's own, or the PC before its
# update) restores and saves nothing; on GitHub's own runners it never reads
# or writes a store, whatever the environment says (they use GitHub's cache,
# through ci.yml's steps and ci/hosted/guard.sh).
#
# Jobs only read the store. Whether a save is kept is the runner's decision,
# made as root after the job (entrypoint.sh, keep): only when GitHub's
# signature on the token says this job is a push or the nightly run on main
# of this repository. A pull request can change this script and ci.yml, but
# not that, so nothing it runs can write a cache a later job reads.
set -eu

usage() { echo "cache.sh: usage: cache.sh restore|save NAME PATH... (NAME: a-z, 0-9 and -; each PATH absolute, under \$HOME)" >&2; exit 2; }
fail() { echo "cache.sh: $*" >&2; exit 1; }

[ "$#" -ge 3 ] || usage
verb="$1" name="$2"
shift 2
case "$verb" in restore | save) ;; *) usage ;; esac
case "$name" in '' | -* | *[!a-z0-9-]*) usage ;; esac
# GitHub's own runners use GitHub's cache (ci/hosted, #1265), never the PC's store.
if [ "${RUNNER_ENVIRONMENT:-}" = github-hosted ]; then echo "cache $name: a GitHub-hosted runner, so not the PC's store: nothing $([ "$verb" = restore ] && echo restored || echo saved)"; exit 0; fi
# A runner without a store: nothing to do, whatever its layout.
if [ "$verb" = restore ] && [ -z "${CLOSEDWIZ_CACHE:-}" ]; then echo "cache $name: no store on this runner, a cold start"; exit 0; fi
if [ "$verb" = save ] && { [ -z "${CLOSEDWIZ_CACHE_OUT:-}" ] || [ -z "${CLOSEDWIZ_CACHE_AUDIENCE:-}" ]; }; then echo "cache $name: no store on this runner, nothing saved"; exit 0; fi
home="${HOME:?}"
for path; do
  case "$path" in "$home"/?*) ;; *) echo "cache.sh: $path is not under \$HOME ($home)" >&2; exit 2 ;; esac
  case "/${path#"$home"/}/" in */../* | */./* | *//*) echo "cache.sh: $path is not under \$HOME ($home)" >&2; exit 2 ;; esac
done
# From here, "$@" holds the PATHs relative to $HOME.
n=$#
for path; do set -- "$@" "${path#"$home"/}"; done
shift "$n"

restore() {
  file="$CLOSEDWIZ_CACHE/$name.tar.zst"
  if [ ! -f "$file" ]; then echo "cache $name: not in the store yet, a cold start"; return 0; fi
  kept="$(date -u -r "$file" '+%Y-%m-%d %H:%M UTC')"
  # Unpacked aside first, so an unreadable cache leaves nothing half-restored.
  tmp="$(mktemp -d "$home/.cache-restore.XXXXXX")"
  if tar --zstd -xf "$file" -C "$tmp"; then
    for rel; do
      [ -e "$tmp/$rel" ] || continue
      mkdir -p "$(dirname "$home/$rel")"
      rm -rf -- "${home:?}/$rel"
      mv -- "$tmp/$rel" "$home/$rel"
    done
    echo "cache $name: restored (kept $kept)"
  else
    echo "cache $name: unreadable, a cold start"
  fi
  rm -rf -- "$tmp"
}

save() {
  out="$CLOSEDWIZ_CACHE_OUT" aud="$CLOSEDWIZ_CACHE_AUDIENCE"
  if [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]; then
    fail "no OIDC token to ask GitHub for: ci.yml needs permissions: id-token: write"
  fi
  for rel; do [ -e "$home/$rel" ] || fail "$home/$rel is missing: nothing saved"; done
  tar --zstd -cf "$out/.$name.tmp" -C "$home" -- "$@"
  mv -f -- "$out/.$name.tmp" "$out/$name.tar.zst"
  # GitHub signs which repository, branch and event this job is, for this
  # runner's one-time audience; the runner checks that before it keeps it.
  curl -fsS --retry 3 --max-time 30 -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
    "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=$aud" | jq -er '.value | strings' > "$out/.token.tmp"
  mv -f -- "$out/.token.tmp" "$out/token"
  echo "cache $name: left for the runner, which keeps it only for a push or the nightly run on main"
}

"$verb" "$@"
