#!/usr/bin/env bash
# OpenWiz 0.1.1 agent rehearsal helpers (#2265, the agent half of #2226).
# Usage: rehearsal.sh machine | check | run CMD... | repo | candidate RUN_ID | teardown SPEC
# Everything lives under $RH (default ~/rehearsal). Raw output stays in $RH, never on GitHub.
set -euo pipefail
RH=${RH:-$HOME/rehearsal}
OWNER=${OWNER:-$(gh api user --jq .login)}
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
  local name="openwiz-rehearsal-011-$(cat "$STAMP_FILE")"
  gh repo create "$OWNER/$name" --private --add-readme \
    --description "Throwaway: OpenWiz 0.1.1 rehearsal; archived after the run" >/dev/null
  echo "$OWNER/$name" > "$RH/repo"
  echo "repo: $OWNER/$name (private, throwaway)"
}

candidate() {  # stage the sealed candidate's Linux files from its Packages run, then check SHA256SUMS
  local run=$1 dir=$RH/assets
  [ ! -e "$dir" ] || { echo "assets folder exists: start a new rehearsal" >&2; exit 2; }
  mkdir -m 700 "$dir"
  gh run download "$run" --repo openwizdev/OpenWiz --dir "$dir/raw"
  find "$dir/raw" -type f \( -name 'openwiz-*x86_64-unknown-linux-gnu*' -o -name SHA256SUMS \) \
    -exec cp {} "$dir/" \;
  rm -rf "$dir/raw" && chmod 600 "$dir"/*
  (cd "$dir" && grep -F 'x86_64-unknown-linux-gnu' SHA256SUMS | sha256sum -c -)
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
  run) shift; clean_env "$@" ;;
  *) sed -n 2,4p "$0"; exit 2 ;;
esac
