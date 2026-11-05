#!/bin/sh
# Prune (#86, #177): run from the repository root of a git checkout, on a
# job's code run, before anything is built. $1 lists the files under
# private/ that CI reads; $2 is the job (web-build, rust, web-test or their release reader union).
# 1. Deletes everything under private/ except the files listed in $1, so no
#    CI step can read the rest. A test that starts reading another file
#    under private/ then fails until that file is listed. A listed path that
#    is not an existing file under private/ fails the step.
# 2. The skip proof: deletes every tracked file the job never reads
#    (classify.sh --skips), so the job can't read a path whose change alone
#    lets it skip. A job that needs one fails on every run, main's and the
#    nightly's included, until classify.sh's table says it reads it.
set -eu
reads="$1"
job="${2:-}" # classify.sh also accepts the release reader union
[ -f "$reads" ] && [ -r "$reads" ] && cat "$reads" > /dev/null || { echo "prune: $reads is missing or unreadable" >&2; exit 1; }
keep="$(mktemp -d)"
tracked="$(mktemp)"
skipped="$(mktemp)"
trap 'rm -rf "$keep" "$tracked" "$skipped"' EXIT
while IFS= read -r path; do
  case "$path" in
    private/*..* | private/*//* ) echo "prune: unsafe path: $path" >&2; exit 1 ;;
    private/?*) ;;
    *) echo "prune: not under private/: $path" >&2; exit 1 ;;
  esac
  if [ ! -f "$path" ] || [ -L "$path" ]; then echo "prune: no such file: $path (each checkout's sparse-checkout list in ci.yml must name it, #334)" >&2; exit 1; fi
  mkdir -p "$keep/$(dirname "$path")"
  cp -p "$path" "$keep/$path"
done < "$reads"
rm -rf private
[ ! -d "$keep/private" ] || cp -Rp "$keep/private" private
echo "prune: private/ now holds only:"
if [ -d private ]; then find private -type f | sort; fi
# git quotes a path with unusual bytes; no row matches a quoted path, so
# every job reads it and it is never on this list.
git ls-files > "$tracked"
READS="$reads" sh "$(dirname "$0")/classify.sh" --skips "$job" < "$tracked" > "$skipped"
gone=0
while IFS= read -r path; do
  if [ -e "$path" ] || [ -L "$path" ]; then rm -f -- "$path"; gone=$((gone + 1)); fi
done < "$skipped"
echo "prune: deleted the $gone other tracked files $job never reads (classify.sh)"
