# Shared by kit-tests.sh and dry-run.sh. SYNTHETIC ONLY; NOT A LIVE RESULT.
# Run from the repository root, on Linux (the reaper reads /proc). Needs cargo: it
# builds openwiz, openwiz-server and the fake room-cli once, into $KIT_TARGET.
# Adapted from 0.0.3's kit (PR #152 at 3a7b501, scripts/test/lib.sh), with #152's R11
# fixed: the cleanup stops only processes that carry this suite's own token.
set -eu
export PYTHONDONTWRITEBYTECODE=1
unset NODE_OPTIONS ROOM_CLI ROOM_SERVER_URL ROOM_THREAD_ID ROOM_PROJECT_ID HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
ROOT=$(pwd)
# Never infer a fixture source from the kit checkout: current main bypasses PATH.
: "${KIT_SOURCE_ROOT:?KIT_SOURCE_ROOT is required: name the PATH-based release source}"
SOURCE_ROOT="$KIT_SOURCE_ROOT"
# Recognise the reviewed PATH wiring at a724d383 (#583), before building or
# running anything. An unknown implementation needs review, not a live probe.
# Pin the CLI/server entrypoints, source constructor and process launcher together.
python3 - "$SOURCE_ROOT" <<'PYSOURCE' || exit 1
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
known = {
    "crates/cli/src/main.rs": "90f6061b262ebda8206d4524c639ee89e1374efda729a97990a388cf35820a9f",
    "crates/server/src/main.rs": "a2cca68b700f758e81b7f8214152b73ed98b09cd0dc4b8d7f5cca3250980e9be",
    "crates/adapters/cloudroom/src/lib.rs": "bf52d7d2ffd76a302f6ec875203f5166947927334c793d34490ec82bbe1b1951",
    "crates/adapters/cloudroom/src/source.rs": "b9bcf4ff52a07aeb58c7842f68a689ea9763ac1b886c1586e303f624c25f1ff4",
    "crates/adapters/cloudroom/src/process.rs": "e815014ca737ea4a3aeccc33f03a3203a2ce1c91c995e5ead0eb5eb20e503ae6",
}
try:
    good = root.is_absolute() and all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h
                                     for p, h in known.items())
except OSError:
    good = False
if not good:
    sys.exit("kit tests require the reviewed PATH-based release source; bundled or unknown lookup refused")
PYSOURCE
TICKET="$ROOT/tools/live-check/new"
SCRIPTS="$TICKET/scripts"
KIT="${KIT_SCRIPT:-$SCRIPTS/new-kit.py}"   # KIT_SCRIPT: another new-kit.py, for a red run
X2SRC="$SCRIPTS/x2-shim.py"
OBS_STUB="$ROOT/tools/live-check/test/observer-stub.py"
FIX="$SOURCE_ROOT/tests/fixtures"
WORK=$(mktemp -d /tmp/openwiz-kit13-XXXXXX)   # never inside the repository: openwiz refuses that
# Every process this suite starts inherits this token; the reaper stops exactly those (R11).
KIT13_OWNER=$(python3 -c "import secrets; print(secrets.token_hex(16))")
export KIT13_OWNER
trap 'cleanup' EXIT
cleanup() {
  for w in "$WORK"/*/w; do  # end any swap still up, so its supervisor restores the stand-in first
    [ -f "$w/run/swap.json" ] && python3 "$KIT" swap --work "$w" end >/dev/null 2>&1 || true
  done
  python3 "$SCRIPTS/test/reap.py" "$KIT13_OWNER" > /dev/null || true
  [ -n "${KIT_KEEP_WORK:-}" ] || rm -rf "$WORK"   # KIT_KEEP_WORK=1 keeps it for a post-mortem
}
KIT_TARGET="${KIT_TARGET:-$ROOT/target}"
# KIT_NO_BUILD=1 (the red runs): the binaries in $KIT_TARGET are used as they are.
[ -n "${KIT_NO_BUILD:-}" ] || CARGO_TARGET_DIR="$KIT_TARGET" cargo build --manifest-path "$SOURCE_ROOT/Cargo.toml" --release --locked -q -p openwiz-cli -p openwiz-server -p openwiz-tests
OPENWIZ="$KIT_TARGET/release/openwiz"
SERVER="$KIT_TARGET/release/openwiz-server"
FAKE="$KIT_TARGET/release/fake-room-cli"
FAILED=0
fail() { echo "kit test FAILED: $1"; FAILED=1; [ -n "${KIT_KEEP_GOING:-}" ] || exit 1; }
ok() { echo "kit test ok: $1"; }

# The 6 synthetic files, made once per suite (never committed: two are 10 MiB).
FILES="$WORK/files"
python3 "$KIT" files --out "$FILES" > "$WORK/files.json" 2>&1 || true

# The stand-in for Cloudflare Access in front of the public hostname (L-10), one per suite.
ACCESS_PORT=$(( ${KIT_PORT:-18370} + 60 ))
( nohup python3 "$SCRIPTS/test/access-stub.py" "$ACCESS_PORT" > /dev/null 2>&1 < /dev/null & )
ACCESS_URL="http://127.0.0.1:$ACCESS_PORT"

# mkworld <name> [short_ms] [start_ms]: a fresh fake world; prints its directory.
# P-A is prj_syn_0301 (a synthetic GitHub remote), and prj_syn_0302 has no remote.
# Test threads: T-A thr_syn_0101 (Local), T-B thr_syn_0102 (Cloud).
mkworld() {
  d="$WORK/$1/world"; mkdir -p "$d/obs" "$d/spawn"
  cp "$SCRIPTS/test/world-stub.py" "$d/room-cli"; chmod 700 "$d/room-cli"
  cp "$OBS_STUB" "$d/obs/room-cli"; chmod 700 "$d/obs/room-cli"
  ln -s "$FAKE" "$d/obs/room-cli-fake"
  echo "$FIX/room-cli-0.43.1/normal/scenario.json" > "$d/obs/fake-room-cli.scenario"
  echo "$FIX" > "$d/world-fixtures"
  # thr_syn_0004 stands for a session Jake used an hour ago: recent, so never judged.
  printf '{"short_ms": %s, "start_ms": %s, "recent": {"thr_syn_0004": %s}}\n' "${2:-600}" "${3:-500}" \
    "$(( $(date +%s) * 1000 - 3600000 ))" > "$d/world-config.json"
  echo '{"thr_syn_0101":{"like":"thr_syn_0004"},"thr_syn_0102":{"like":"thr_syn_0005"}}' > "$d/world-threads.json"
  printf 'PA=prj_syn_0301\nTA=thr_syn_0101\nTB=thr_syn_0102\n' > "$WORK/$1/targets.env"; chmod 600 "$WORK/$1/targets.env"
  echo "$d"
}

# The stand-in for Jake's running server (0.0.3's, at the time): the real openwiz-server,
# with its own launch line (a host name of this run's own).
OLDHOST="old-$(basename "$WORK" | tr -cd 'A-Za-z0-9-').invalid"
export OLDHOST  # only red-run 22's mutant reads it
SERVER_SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$SERVER")
oldcmd() { echo "[\"$SERVER\", \"--port\", \"$1\", \"--allowed-host\", \"$OLDHOST\"]"; }

# approval <name>: the approval file of that sitting's world (#168's R8: L-8's allowance, kept
# outside the sitting's work directory), made once, with L-8's totals (4 creates, 2 sends).
approval() {
  [ -e "$WORK/$1/approval.json" ] || python3 "$KIT" approval init --approval "$WORK/$1/approval.json" > "$WORK/$1/approval-init.json" || true
  echo "$WORK/$1/approval.json"
}

# kitsetup <name> [extra setup args]: mkworld, then new-kit setup --dry-run and settings.
# The port is $SETUP_PORT if set, else $KIT_PORT: each section that swaps gets its own, since
# the swap back leaves its stand-in running until the suite's cleanup.
# KIT_FROM=<other>: a fresh sitting in <other>'s world, under <other>'s approval (a recovery).
kitsetup() {
  name=$1; shift
  port=${SETUP_PORT:-${KIT_PORT:-18370}}
  if [ -n "${KIT_FROM:-}" ]; then
    d="$WORK/$KIT_FROM/world"; mkdir -p "$WORK/$name"; cp "$WORK/$KIT_FROM/targets.env" "$WORK/$name/targets.env"
    appr="$WORK/$KIT_FROM/approval.json"
  else
    d=$(mkworld "$name" "${KIT_SHORT_MS:-600}" "${KIT_START_MS:-500}")
    appr=$(approval "$name")
  fi
  mkdir -p "$WORK/$name/old"
  python3 "$KIT" setup --work "$WORK/$name/w" --room-cli "$d/room-cli" --openwiz "$OPENWIZ" --approval "$appr" \
    --server "$SERVER" --targets "$WORK/$name/targets.env" --files "$FILES" --port "$port" \
    --host openwiz.invalid --restore-cmd "$(oldcmd "$port")" --restore-log "$WORK/$name/old/server.log" \
    --restore-sha256 "$SERVER_SHA" --contracts "$SOURCE_ROOT/contracts" --access-url "${KIT_ACCESS_URL:-$ACCESS_URL}" \
    $([ -n "${KIT_NO_AGENT_REPLY:-}" ] || echo "--agent-reply syn-agent-message:data.input") \
    --dry-run "$@" > "$WORK/$name/setup.json" || true
  python3 "$KIT" settings --work "$WORK/$name/w" > "$WORK/$name/settings.json" || true
}  # never fails itself: the checks on setup.json and settings.json do (KIT_KEEP_GOING runs on)

# kitswap <name>: start the stand-in on the kit's port, then the swap (X1's server takes the port).
kitswap() {
  port=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$WORK/$1/w/kit.json")
  ( cd "$WORK/$1/old" && nohup "$SERVER" --port "$port" --allowed-host "$OLDHOST" >> server.log 2>&1 < /dev/null & )
  for i in $(seq 1 30); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$port" 2>/dev/null && break; sleep 0.2; done
  python3 "$KIT" swap --work "$WORK/$1/w" start --minutes "${KIT_SWAP_MINUTES:-20}" > "$WORK/$1/swap.json" || true
}
# kitunswap <name>: end the swap (the stand-in restored).
kitunswap() { python3 "$KIT" swap --work "$WORK/$1/w" end > "$WORK/$1/unswap.json" || true; }

# kitrun <name> <groups> [args]: one new-kit run, short waits; report in $WORK/<name>.json, exit in $RC.
kitrun() {
  name=$1; groups=$2; shift 2
  RC=0
  python3 "$KIT" run --work "$WORK/$name/w" --groups "$groups" --settle "${KIT_SETTLE:-0.3}" \
    --late "${KIT_LATE:-0.3}" --idle-timeout "${KIT_IDLE:-30}" --poll 0.3 --press-timeout 30 --min-judged 3 "$@" \
    > "$WORK/$name.json" 2> "$WORK/$name.err" || RC=$?
}

# check <description> <python expression on report r> <file>
check() {
  if python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" "$3" 2>/dev/null
  then ok "$1"; else fail "$1"; python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1])), indent=1)[:6000])" "$3" 2>/dev/null || cat "$3"; fi
}

# plant <name> <word>: a planted fault in that world (see world-stub.py).
plant() { echo "$2" >> "$WORK/$1/world/world-plant"; }
# writes <name> <kind>: how many writes of that kind reached the repository's fake.
fake_writes() {
  f="$WORK/$1/world/fake-writes.log"
  if [ -f "$f" ]; then grep -c "\"kind\": \"$2\"" "$f" || true; else echo 0; fi
}
# kitjake <name> <groups> [args]: kitrun's run, with jake-sim.py playing Jake (and the runner).
kitjake() {
  name=$1; groups=$2; shift 2
  RC=0
  python3 "$SCRIPTS/test/jake-sim.py" "$KIT" "$WORK/$name/w" "$groups" --settle "${KIT_SETTLE:-0.3}" \
    --late "${KIT_LATE:-0.3}" --idle-timeout "${KIT_IDLE:-30}" --poll 0.3 --press-timeout 30 --min-judged 3 "$@" \
    > "$WORK/$name.json" 2> "$WORK/$name.err" || RC=$?
}

# Processes and the swap, for the R2 and #168 tests.
healthy() { python3 -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=3); c.request('GET','/api/v1/health',headers={'Host':'127.0.0.1:%s' % sys.argv[1]}); sys.exit(0 if c.getresponse().status==200 else 1)" "$1" 2>/dev/null; }
answers() { python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$1" 2>/dev/null; }
# old_pid <port>: this suite's stand-in on that port (its launch line names this suite's own host name).
old_pid() { ps -eo pid=,args= | awk -v h="--port $1 --allowed-host $OLDHOST" 'index($0, h) && !/awk/ {print $1}' | head -1; }
stub_pid() { ps -eo pid=,args= | awk -v h="$WORK/$1/stub/stub-server.py" 'index($0, h) && !/awk/ {print $1}' | head -1; }
swapfield() { python3 -c "import json,sys; d=json.load(open(sys.argv[1])); v=(d.get(sys.argv[2]) or {}).get('pid') if sys.argv[2] in ('supervisor','guard') else d.get(sys.argv[2]); print('' if v is None else v)" "$WORK/$1/w/run/swap.json" "$2" 2>/dev/null || true; }
# mine <pid>: signal it only if it carries this suite's token (R11: ownership proved, never guessed).
mine() { [ -n "$1" ] && tr '\0' '\n' < "/proc/$1/environ" 2>/dev/null | grep -qx "KIT13_OWNER=$KIT13_OWNER"; }
stopmine() { for p in "$@"; do mine "$p" && kill "$p" 2>/dev/null || true; done; }
kill9mine() { mine "$1" && kill -9 "$1" 2>/dev/null || true; }
