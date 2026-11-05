#!/bin/sh
# The dry run: the whole run sheet (run-sheet.md), step by step, in order, against
# the repository's fake room-cli (behind world-stub.py), a local openwiz-server, and
# a stand-in for Jake's 0.0.2 server (the real binary with its own launch line).
# SYNTHETIC ONLY; NOT A LIVE RESULT. Jake keeps working throughout: the world has a
# session he used an hour ago, which changes during the run, and a new session
# appears (neither is judged). X1 presses for Jake in P1 (--dry-run), and every wait
# is scaled down (sleep 120 turns take 8 s; settle 2 s; late 3 s).
# Every step's exit, every report's outcome and the send count are asserted (Sol R7):
# anything unexpected makes the dry run exit 1.
# Run from the repository root:
#   sh private/evidence/openwiz-0.0.3/ticket-3/scripts/test/dry-run.sh
. "$(dirname "$0")/lib.sh"
T0=$(date +%s)
BAD=0
step() { echo; echo "== [$(( $(date +%s) - T0 )) s] $1"; }
# run <expected exit> <send-kit args...>: prints the command and its output; a different exit fails the dry run.
run() {
  want=$1; shift
  echo "\$ send-kit.py $*" | sed "s|$WORK|<W>|g"
  rc=0; python3 "$KIT" "$@" > "$WORK/last.out" 2> "$WORK/last.err" || rc=$?
  cat "$WORK/last.err" "$WORK/last.out"
  echo "(exit $rc)"
  [ "$rc" = "$want" ] || { echo "DRY RUN FAILURE: exit $rc, expected $want"; BAD=1; }
}
# expect <description> <python expression on the last report r>
expect() {
  if python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" "$WORK/last.out" 2>/dev/null
  then echo "asserted: $1"; else echo "DRY RUN FAILURE: $1"; BAD=1; fi
}

D=$(mkworld dry)
plant dry touch-recent
plant dry appear
W="$WORK/dry/w"; PORT=$(( ${KIT_PORT:-17370} + 2 ))
mkdir -p "$WORK/dry/old"
HEAD=$(git rev-parse HEAD)
OW_SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$OPENWIZ")
echo "DRY RUN of the run sheet. Fake room-cli only; nothing is sent anywhere. Head $HEAD."
echo "Jake's concurrent use, planted: every send also moves a session he used an hour ago, and a new session appears."
echo "Jake's 0.0.2 server, a stand-in: the real openwiz-server on port $PORT with its own launch line."
( cd "$WORK/dry/old" && { nohup "$SERVER" --port "$PORT" --allowed-host "$OLDHOST" >> server.log 2>&1 < /dev/null & echo $! > "$WORK/dry/old/pid"; } )
own "$(cat "$WORK/dry/old/pid")"
for i in $(seq 1 30); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$PORT" 2>/dev/null && break; sleep 0.2; done

step "A1 to A3: the texts and their hashes (scripts and binaries are checked at setup)"
run 0 texts
expect "22 approved texts" "r['all_approved'] and len(r['texts'])==22"

step "A5: setup (both binaries and the head verified; the confirmed 0.0.2 launch recorded; X2 installed)"
run 0 setup --work "$W" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --server "$SERVER" \
  --threads "$WORK/dry/threads.env" --port "$PORT" --host openwiz.invalid \
  --restore-cmd "$(oldcmd "$PORT")" --restore-log "$WORK/dry/old/server.log" --restore-sha256 "$SERVER_SHA" \
  --expect-sha256 "$OW_SHA" --expect-server-sha256 "$SERVER_SHA" --checkout "$ROOT" --expect-head "$HEAD" --dry-run --allowance "$WORK/dry/allowance"
expect "setup ready, PATH guard on X2" "r['setup']=='ready' and r['path_guard'].endswith('X2')"
expect "the allowance: L-8's 23 sends, none used yet" "r['allowance']=={'total': 23, 'used': 0, 'remaining': 23}"

step "A6: the map (T-A Local, T-B and T-C Cloud; idle, empty, visible; no id, no title)"
run 0 map --work "$W"
expect "the map as expected" "r['outcome']=='as_expected' and r['threads']['T-A']['where']=='Local'"

step "A7: L-3, thread tell's help (structure only)"
run 0 recheck --work "$W"
expect "the help read" "r['outcome']=='as_expected' and len(r['help_sha256'])==64"

step "B: the CLI groups C1 to C8 (the runner; Jake keeps working)"
run 0 run --work "$W" --groups C1,C2,C3,C4,C5,C6,C7,C8 --settle 2 --late 3 --idle-timeout 60 --busy-min 1 --poll 0.5 --press-timeout 60 --min-judged 3
expect "C1 to C8 as expected, every bracket and landing" "r['outcome']=='as_expected' and len(r['groups'])==8 and r['landing_at_end']=='as_expected' and all(g['outside']['verdict']=='as_expected' for g in r['groups'])"
expect "Jake's recent session changed and a new session appeared, neither judged" "any(g['outside']['not_judged_changed'] for g in r['groups']) and any(g['outside']['appeared_not_judged'] for g in r['groups'])"
cp "$WORK/last.out" "$WORK/cli.json"

step "C1: the swap (Jake's OK): the confirmed 0.0.2 launch stops; X1's 0.0.3 server starts under the supervisor"
run 0 swap --work "$W" start --minutes 30
expect "swap up, 0.0.2 was running" "r['swap']=='up' and r['old_was_running'] is True"

step "C2: the web groups W1 to W7 (X1 makes the composer's requests; F4 and F6 through the supervisor)"
run 0 run --work "$W" --groups W1,W2,W3,W4,W5,W6,W7 --settle 2 --late 3 --idle-timeout 60 --busy-min 1 --poll 0.5 --press-timeout 60 --min-judged 3
expect "W1 to W7 as expected" "r['outcome']=='as_expected' and len(r['groups'])==7 and r['landing_at_end']=='as_expected'"
cp "$WORK/last.out" "$WORK/web.json"

step "C3: P1, Jake's phone (in a dry run, X1 presses for him)"
run 0 run --work "$W" --groups P1,P1b --settle 2 --late 3 --idle-timeout 60 --busy-min 1 --poll 0.5 --press-timeout 60 --min-judged 3
expect "P1 and P1b as expected, F7 produced" "r['outcome']=='as_expected' and [g['group'] for g in r['groups']]==['P1','P1b'] and r['groups'][1]['steps'][0].get('fault_produced') is True"
cp "$WORK/last.out" "$WORK/phone.json"

step "C4: L10, parity from the send records (no call)"
run 0 parity --work "$W"
expect "parity as expected for all three kinds" "r['outcome']=='as_expected' and len(r['parity'])==3"

step "C5: L13, 0.0.1's quick check while the page's routes are read; recent sessions excluded by rule"
run 0 l13 --work "$W" --min-judged 3 -- --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --run-dir "$WORK/dry/qc" --wait 5 \
  --expect-sha256 "$OW_SHA" --checkout "$ROOT" --expect-head "$HEAD"
expect "L13 as expected, every page route answered validly" "r['l13']['verdict']=='as_expected' and all(v['valid']>0 and v['failed']==0 for v in r['l13']['page_routes'].values())"

step "C6: L4, the receipts' structure"
run 0 receipts --work "$W"
expect "receipts: sent, queued (thread-busy) and steer queued (not reported), all with the observed keys" "r['outcome']=='as_expected' and r['drift']==[]"

step "C7: the swap back: the supervisor stops X1's server and restores the confirmed 0.0.2 launch; the closing map"
run 0 swap --work "$W" end
expect "0.0.2 restored" "r['swap']=='restored'"
if ps -eo args= | grep -q -- "--port $PORT --allowed-host $OLDHOST"; then echo "asserted: the 0.0.2 stand-in is running again"
else echo "DRY RUN FAILURE: the 0.0.2 stand-in is not running"; BAD=1; fi
run 0 map --work "$W"
expect "the allowance: all of L-8's 23 sends used, none left (zero-call holds returned)" "r['allowance']=={'total': 23, 'used': 23, 'remaining': 0}"

step "Counts"
CALLS=$(python3 - "$W/x2/tell.log" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
by = {}
for r in rows:
    by[r["outcome"]] = by.get(r["outcome"], 0) + 1
sys.stderr.write("X2's tell log: %s\n" % dict(sorted(by.items())))
print(by.get("called", 0) + by.get("called_after_hold", 0))
PY
)
FAKE=$(wc -l < "$D/fake-tells.log" | tr -d ' ')
PLANNED=$(python3 -c "import json,sys; p=json.load(open(sys.argv[1])); print(sum(s['expect'].get('calls',0) for g in p['groups'] for s in g['steps'] if s['do'] in ('send','post','press')))" "$SCRIPTS/plan.json")
echo "calls X2 let through: $CALLS; tells that reached the fake: $FAKE; planned (plan.json): $PLANNED"
[ "$CALLS" = "$PLANNED" ] && [ "$FAKE" = "$PLANNED" ] && echo "asserted: exactly the planned $PLANNED sends" \
  || { echo "DRY RUN FAILURE: the send count is not the planned $PLANNED"; BAD=1; }
if grep -qE 'thr_syn_|op-acc-|web-[0-9a-f]{32}|openwiz\.invalid|Synthetic test thread' "$WORK/cli.json" "$WORK/web.json" "$WORK/phone.json"; then
  echo "DRY RUN FAILURE: an id, op id, host name or title in a report"; BAD=1
else echo "asserted: the run reports hold no id, op id, host name or title"; fi
step "DRY RUN $([ "$BAD" = 0 ] && echo "done: every assertion held" || echo "FAILED") (synthetic; not a live result)"
exit $BAD
