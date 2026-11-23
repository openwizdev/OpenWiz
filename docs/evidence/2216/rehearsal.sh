#!/usr/bin/env bash
# OpenWiz 0.1.1 agent rehearsal helpers (#2265, the agent half of #2226).
# Usage: rehearsal.sh machine | check | run CMD... | say TEXT | repo | candidate RUN_ID | teardown SPEC
# Everything lives under $RH (default ~/rehearsal). Raw output stays in $RH, never on GitHub.
# Every `run` and `say` is recorded with real timing (util-linux script) under $RH/demo/ for the demo video.
set -euo pipefail
RH=${RH:-$HOME/rehearsal}
USER=${USER:-$(id -un)}
OWNER=${OWNER:-}
STAMP_FILE=$RH/stamp
ALLOWED=(claude gh git python3 curl tar gzip sha256sum ldd uname crontab jq)
CLOUDROOM=(room-cli cloudroom a0 agy browser-harness cursor-agent opencode openclaw codex)

clean_env() {  # a stranger's environment: no CloudRoom or OpenWiz App variables, an allowlisted PATH
  env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" LANG=C.UTF-8 TERM=dumb \
    PATH="$RH/bin:/usr/bin:/bin" SHELL=/bin/bash "$@"
}

machine() {
  mkdir -p "$RH/bin" "$RH/logs" && chmod 700 "$RH"
  [ -f "$STAMP_FILE" ] || date -u +%Y%m%d%H%M > "$STAMP_FILE"
  # A stock Debian has cron; this sandbox image does not, and has no systemd user manager.
  command -v crontab >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq cron; }
  pgrep -x cron >/dev/null || sudo service cron start || sudo cron
  for tool in "${ALLOWED[@]}"; do
    src=$(command -v "$tool") || { echo "missing tool: $tool" >&2; exit 2; }
    ln -sfn "$(readlink -f "$src")" "$RH/bin/$tool"
  done
  echo "machine ready: $RH/bin"
}

check() {
  local bad=0
  for b in "${CLOUDROOM[@]}"; do
    if clean_env bash -c "command -v $b" >/dev/null 2>&1; then echo "FAIL on PATH: $b"; bad=1; fi
  done
  if clean_env bash -c 'env' | grep -E -q '^(ROOM_|CLOUDROOM|OPENWIZ_GITHUB_APP|CLAUDE_CODE_MESSAGING)'; then
    echo "FAIL: a CloudRoom or App variable is in the clean environment"; bad=1
  fi
  for t in claude gh git python3 crontab; do
    clean_env bash -c "command -v $t" >/dev/null || { echo "FAIL missing: $t"; bad=1; }
  done
  clean_env gh auth status >/dev/null 2>&1 || { echo "FAIL: gh is not signed in"; bad=1; }
  clean_env bash -c 'ldd --version | head -1'
  [ $bad = 0 ] && echo "clean: no CloudRoom binary or variable, claude and gh present, cron running" || exit 1
}

repo() {
  local name="openwiz-rehearsal-011-$(cat "$STAMP_FILE")"; OWNER=${OWNER:-$(gh api user --jq .login)}
  gh repo create "$OWNER/$name" --private --add-readme \
    --description "Throwaway: OpenWiz 0.1.1 rehearsal; archived after the run" >/dev/null
  echo "$OWNER/$name" > "$RH/repo"
  echo "repo: $OWNER/$name (private, throwaway)"
}

record() {  # record one step: its real UTC start, the exact command, its output with timing, its exit code
  local demo=$RH/demo n
  mkdir -p "$demo" && chmod 700 "$demo"
  n=$(printf '%03d' $(( $(find "$demo" -name '*.meta.json' | wc -l) + 1 )))
  { printf '#!/bin/bash\n'; printf '%q ' "$@"; printf '\n'; } > "$demo/$n.cmd"
  local start; start=$(date +%s.%N)
  set +e
  script -q -e -T "$demo/$n.timing" -O "$demo/$n.typescript" -c "bash $demo/$n.cmd"
  local code=$?
  set -e
  python3 -I -c 'import json,sys;print(json.dumps({"start":float(sys.argv[1]),"end":float(sys.argv[2]),"exit":int(sys.argv[3]),"argv":sys.argv[4:]}))' \
    "$start" "$(date +%s.%N)" "$code" "$@" > "$demo/$n.meta.json"
  return $code
}

candidate() {  # stage the sealed candidate's Linux files from its Packages run, then check SHA256SUMS
  local run=$1 dir=$RH/assets
  [ ! -e "$dir" ] || { echo "assets folder exists: start a new rehearsal" >&2; exit 2; }
  mkdir -m 700 "$dir"
  local target=x86_64-unknown-linux-gnu
  local artifact="openwiz-0.1.1-$target"
  gh run download "$run" --repo openwizdev/OpenWiz --name "$artifact" --dir "$dir/raw"
  local packages="$dir/raw/packages"
  cp "$packages"/{SHA256SUMS,"$artifact.tar.gz","$artifact.manifest.json","openwiz-$target.manifest.json","openwiz-$target.sha256"} "$dir/"
  rm -rf "$dir/raw" && chmod 600 "$dir"/*
  (
    cd "$dir"
    # GNU checksum records place the filename after the 64-digit digest and two separators.
    diff -u <(printf '%s\n' "$artifact.manifest.json" "$artifact.tar.gz") \
      <(LC_ALL=C cut -c67- SHA256SUMS | LC_ALL=C sort)
    sha256sum --strict -c SHA256SUMS
  )
}

teardown() {  # LV1: nothing left running, the throwaway repository archived
  local repo; repo=$(cat "$RH/repo")
  local hb=$HOME/.claude/skills/launch-fleet/scripts/heartbeat.py spec=${1:?teardown SPEC_NUMBER}
  clean_env python3 -I "$hb" remove "$repo" "$spec" || echo "heartbeat remove: see output above"
  clean_env crontab -l 2>/dev/null | grep -i openwiz && echo "WARN: an OpenWiz cron line remains" || true
  pgrep -u "$USER" -af 'claude.*-p' && echo "WARN: a builder or reviewer is still running" || true
  gh issue list --repo "$repo" --state open --json number --jq '.[].number' |
    xargs -r -n1 gh issue close --repo "$repo"
  gh repo archive "$repo" --yes
  gh repo view "$repo" --json isArchived --jq '"archived: \(.isArchived)"'
}

case ${1:-} in
  machine|check|repo|teardown) "$1" "${@:2}" ;;
  candidate) candidate "$2" ;;
  run) shift; record env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" LANG=C.UTF-8 TERM=xterm-256color \
         PATH="$RH/bin:/usr/bin:/bin" SHELL=/bin/bash "$@" ;;
  say) shift; record printf '\n\033[1;33m%s\033[0m\n' "$*" ;;
  *) sed -n 2,4p "$0"; exit 2 ;;
esac
