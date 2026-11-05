# Shared by kit-tests.sh and dry-run.sh. SYNTHETIC ONLY; NOT A LIVE RESULT.
# Run from the repository root. Needs cargo (it builds openwiz, openwiz-server
# and the fake room-cli once, into $KIT_TARGET).
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
TICKET="$ROOT/tools/live-check/send"
SCRIPTS="$TICKET/scripts"
KIT="${KIT_SCRIPT:-$SCRIPTS/send-kit.py}"   # KIT_SCRIPT: another send-kit.py, for a red run
X2SRC="$SCRIPTS/x2-shim.py"
OBS_STUB="$ROOT/tools/live-check/test/observer-stub.py"
FIXTURES="$SOURCE_ROOT/tests/fixtures/room-cli-0.43.1"
WORK=$(mktemp -d /tmp/openwiz-kit-XXXXXX)   # never inside the repository: openwiz refuses that
trap 'cleanup' EXIT
cleanup() {
  for w in "$WORK"/*/w; do  # end any swap still up (the guard stops X1's server and restores 0.0.2)
    [ -f "$w/run/swap.json" ] && python3 "$KIT" swap --work "$w" end >/dev/null 2>&1 || true
  done
  # Sol R11: only what this run started, by recorded identity (PID, start time and command line,
  # checked again before the signal): the processes in $WORK/owned (stand-ins, helpers), and the
  # supervisors, guards and restored servers each swap recorded. Never by name or port.
  python3 - "$WORK" <<'PY' || true
import glob, json, os, signal, subprocess, sys
def ident(pid):
    r = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-o", "args=", "-p", str(pid)], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    parts = r.stdout.decode("utf-8", "replace").strip().split(None, 6)
    return None if len(parts) < 7 or parts[0].startswith("Z") else (" ".join(parts[1:6]), parts[6])
recs = []
if os.path.exists(os.path.join(sys.argv[1], "owned")):
    recs += [json.loads(l) for l in open(os.path.join(sys.argv[1], "owned")) if l.strip()]
for f in glob.glob(os.path.join(sys.argv[1], "*", "w", "run", "swap.json")):
    st = json.load(open(f))
    recs += [st[k] for k in ("supervisor", "guard", "restored_old") if isinstance(st.get(k), dict)]
for r in recs:
    cur = ident(r["pid"])
    if cur and cur == (r["lstart"], r["args"]):
        try:
            os.kill(r["pid"], signal.SIGTERM)
        except OSError:
            pass
PY
  [ -n "${KIT_KEEP_WORK:-}" ] || rm -rf "$WORK"   # KIT_KEEP_WORK=1 keeps it for a post-mortem
}
# own <pid>: record a process this run started (its identity), so cleanup may stop it, and nothing else.
own() {
  python3 - "$1" >> "$WORK/owned" <<'PY'
import json, subprocess, sys
r = subprocess.run(["ps", "-o", "lstart=", "-o", "args=", "-p", sys.argv[1]], stdout=subprocess.PIPE)
parts = r.stdout.decode("utf-8", "replace").strip().split(None, 5)
if len(parts) == 6:
    print(json.dumps({"pid": int(sys.argv[1]), "lstart": " ".join(parts[:5]), "args": parts[5]}))
PY
}
KIT_TARGET="${KIT_TARGET:-$ROOT/target}"
[ -n "${KIT_NO_BUILD:-}" ] || CARGO_TARGET_DIR="$KIT_TARGET" cargo build --manifest-path "$SOURCE_ROOT/Cargo.toml" --release --locked -q -p openwiz-cli -p openwiz-server -p openwiz-tests
OPENWIZ="$KIT_TARGET/release/openwiz"
SERVER="$KIT_TARGET/release/openwiz-server"
FAKE="$KIT_TARGET/release/fake-room-cli"
FAILED=0
fail() { echo "kit test FAILED: $1"; FAILED=1; [ -n "${KIT_KEEP_GOING:-}" ] || exit 1; }
ok() { echo "kit test ok: $1"; }

# mkworld <name> [sleep_ms] [short_ms]: a fresh fake world; prints its directory.
# Test threads: T-A thr_syn_0101 (Local, steering), T-B thr_syn_0102 (Cloud,
# steering), T-C thr_syn_0103 (Cloud, no steering).
mkworld() {
  d="$WORK/$1/world"; mkdir -p "$d/obs"
  cp "$SCRIPTS/test/world-stub.py" "$d/room-cli"; chmod 700 "$d/room-cli"
  cp "$OBS_STUB" "$d/obs/room-cli"; chmod 700 "$d/obs/room-cli"
  ln -s "$FAKE" "$d/obs/room-cli-fake"
  echo "$FIXTURES/normal/scenario.json" > "$d/obs/fake-room-cli.scenario"
  echo "$FIXTURES/send" > "$d/world-fixtures"
  # thr_syn_0004 stands for a session Jake used an hour ago: recent, so never judged.
  printf '{"sleep_ms": %s, "short_ms": %s, "recent": {"thr_syn_0004": %s}}\n' "${2:-8000}" "${3:-300}" \
    "$(( $(date +%s) * 1000 - 3600000 ))" > "$d/world-config.json"
  echo '{"thr_syn_0101":{"steer":true,"like":"thr_syn_0004"},"thr_syn_0102":{"steer":true,"like":"thr_syn_0005","cloud":true},"thr_syn_0103":{"steer":false,"like":"thr_syn_0001","cloud":true}}' > "$d/world-threads.json"
  printf 'TA=thr_syn_0101\nTB=thr_syn_0102\nTC=thr_syn_0103\n' > "$WORK/$1/threads.env"; chmod 600 "$WORK/$1/threads.env"
  echo "$d"
}

# The stand-in for Jake's 0.0.2 server: the real openwiz-server, with its own launch line
# (a host name of this run's own, so suites running side by side never touch each other's).
OLDHOST="old-$(basename "$WORK" | tr -cd 'A-Za-z0-9-').invalid"
SERVER_SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$SERVER")
oldcmd() { echo "[\"$SERVER\", \"--port\", \"$1\", \"--allowed-host\", \"$OLDHOST\"]"; }

# kitsetup <name> [extra setup args]: mkworld, then send-kit setup --dry-run into $WORK/<name>/w,
# with the stand-in's launch line as the confirmed 0.0.2 launch.
kitsetup() {
  name=$1; shift
  d=$(mkworld "$name" "${KIT_SLEEP_MS:-8000}" "${KIT_SHORT_MS:-300}")
  mkdir -p "$WORK/$name/old"
  python3 "$KIT" setup --work "$WORK/$name/w" --room-cli "$d/room-cli" --openwiz "$OPENWIZ" \
    --server "$SERVER" --threads "$WORK/$name/threads.env" --port "${KIT_PORT:-17370}" \
    --host openwiz.invalid --restore-cmd "$(oldcmd "${KIT_PORT:-17370}")" --restore-log "$WORK/$name/old/server.log" \
    --restore-sha256 "$SERVER_SHA" --dry-run --allowance "$WORK/$name/allowance" "$@" > "$WORK/$name/setup.json"
}

# x2bare <dir>: X2 alone, for the tests that call it directly: the shim, an empty sitting
# ledger, and an allowance of 23 with its empty charge journal, as setup makes them (each
# step file names it as "allowance": "<dir>/allow").
x2bare() {
  mkdir -p "$1/allow"; cp "$X2SRC" "$1/room-cli"; chmod 700 "$1/room-cli"; : > "$1/sitting.log"
  echo '{"total": 23, "approval": "L-8"}' > "$1/allow/allowance.json"; : > "$1/allow/charges.log"
}

# kitswap <name>: start the 0.0.2 stand-in on the kit's port, then the swap (X1's server takes the port).
kitswap() {
  port=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$WORK/$1/w/kit.json")
  ( cd "$WORK/$1/old" && { nohup "$SERVER" --port "$port" --allowed-host "$OLDHOST" >> server.log 2>&1 < /dev/null & echo $! > "$WORK/$1/old/pid"; } )
  own "$(cat "$WORK/$1/old/pid")"
  for i in $(seq 1 30); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$port" 2>/dev/null && break; sleep 0.2; done
  python3 "$KIT" swap --work "$WORK/$1/w" start --minutes "${KIT_SWAP_MINUTES:-20}" > "$WORK/$1/swap.json"
}
# kitunswap <name>: end the swap (0.0.2's stand-in restored), then stop the stand-in.
kitunswap() {
  python3 "$KIT" swap --work "$WORK/$1/w" end > "$WORK/$1/unswap.json" || true
  port=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$WORK/$1/w/kit.json")
  killown "$WORK/$1/w/run/swap.json" restored_old   # the 0.0.2 the guard restored: recorded, verified
}
# killown <swap.json> <key>: stop the process a swap recorded under <key>, if it is still that very process.
killown() {
  python3 - "$1" "$2" <<'PY' || true
import json, os, signal, subprocess, sys
try:
    r = json.load(open(sys.argv[1]))[sys.argv[2]]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(0)
out = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-o", "args=", "-p", str(r["pid"])], stdout=subprocess.PIPE)
parts = out.stdout.decode("utf-8", "replace").strip().split(None, 6)
if len(parts) == 7 and not parts[0].startswith("Z") and (" ".join(parts[1:6]), parts[6]) == (r["lstart"], r["args"]):
    os.kill(r["pid"], signal.SIGTERM)
PY
}

# kitrun <name> <groups> [args]: one send-kit run, short waits; report in $WORK/<name>.json, exit in $RC.
kitrun() {
  name=$1; groups=$2; shift 2
  RC=0
  python3 "$KIT" run --work "$WORK/$name/w" --groups "$groups" --settle "${KIT_SETTLE:-0.5}" \
    --late "${KIT_LATE:-0.5}" --idle-timeout 30 --busy-min 1 --poll 0.3 --press-timeout 30 --min-judged 3 "$@" \
    > "$WORK/$name.json" 2> "$WORK/$name.err" || RC=$?
}

# check <description> <python expression on report r> <file>
check() {
  if python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" "$3" 2>/dev/null
  then ok "$1"; else fail "$1"; python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1])), indent=1)[:6000])" "$3" 2>/dev/null || cat "$3"; fi
}

# plant <name> <word>: a planted fault in that world (see world-stub.py).
plant() { echo "$2" >> "$WORK/$1/world/world-plant"; }
