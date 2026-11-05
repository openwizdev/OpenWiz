#!/bin/sh
# The dry run: the whole run sheet (run-sheet.md), step by step, in order, against the
# repository's fake room-cli (behind world-stub.py), a local openwiz-server, and a
# stand-in for Jake's running server (the real binary with its own launch line).
# SYNTHETIC ONLY; NOT A LIVE RESULT. Jake keeps working throughout: the world has a
# session he used an hour ago, which changes during the run, and a new session appears
# (neither is judged). X1 presses for Jake in J1 to J6 (--dry-run) and jake-sim.py
# answers for him (a stand-in's answers, never Jake's); every wait is scaled down.
# Every step's exit, every report's outcome and the write counts are asserted (#152's
# R7): anything unexpected makes the dry run exit 1. Run from the repository root:
#   sh private/evidence/openwiz-0.0.4/ticket-13/scripts/test/dry-run.sh
. "$(dirname "$0")/lib.sh"
T0=$(date +%s)
BAD=0
step() { echo; echo "== [$(( $(date +%s) - T0 )) s] $1"; }
# run <expected exit> <new-kit args...>: prints the command and its output; a different exit fails the dry run.
run() {
  want=$1; shift
  echo "\$ new-kit.py $*" | sed "s|$WORK|<W>|g"
  rc=0; python3 "$KIT" "$@" > "$WORK/last.out" 2> "$WORK/last.err" || rc=$?
  cat "$WORK/last.err" "$WORK/last.out" | sed "s|$WORK|<W>|g"
  echo "(exit $rc)"
  [ "$rc" = "$want" ] || { echo "DRY RUN FAILURE: exit $rc, expected $want"; BAD=1; }
}
# jake <expected exit> <run args...>: as run, with jake-sim.py answering for Jake.
jake() {
  want=$1; shift
  echo "\$ jake-sim.py new-kit.py $*" | sed "s|$WORK|<W>|g"
  rc=0; python3 "$SCRIPTS/test/jake-sim.py" "$KIT" "$@" > "$WORK/last.out" 2> "$WORK/last.err" || rc=$?
  cat "$WORK/dry/prompts.log" "$WORK/last.out" 2>/dev/null | sed "s|$WORK|<W>|g"
  echo "(exit $rc)"
  [ "$rc" = "$want" ] || { echo "DRY RUN FAILURE: exit $rc, expected $want"; BAD=1; }
}
# expect <description> <python expression on the last report r>
expect() {
  if python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" "$WORK/last.out" 2>/dev/null
  then echo "asserted: $1"; else echo "DRY RUN FAILURE: $1"; BAD=1; fi
}
WAITS="--settle 1 --late 2 --idle-timeout 60 --poll 0.5 --press-timeout 60 --min-judged 3"

D=$(mkworld dry)
plant dry touch-recent
plant dry appear
W="$WORK/dry/w"; PORT=$(( ${KIT_PORT:-18370} + 2 ))
mkdir -p "$WORK/dry/old"
HEAD=$(git rev-parse HEAD)
OW_SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$OPENWIZ")
echo "DRY RUN of the run sheet. Fake room-cli only; nothing is created, sent or uploaded anywhere. Head $HEAD."
echo "Jake's concurrent use, planted: every write also moves a session he used an hour ago, and a new session appears."
echo "Jake's running server, a stand-in: the real openwiz-server on port $PORT with its own launch line."
( cd "$WORK/dry/old" && nohup "$SERVER" --port "$PORT" --allowed-host "$OLDHOST" >> server.log 2>&1 < /dev/null & )
for i in $(seq 1 30); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$PORT" 2>/dev/null && break; sleep 0.2; done

step "A3: the texts and their hashes (the scripts and binaries are checked at setup)"
run 0 texts
expect "15 approved texts" "r['all_approved'] and len(r['texts'])==15"

step "A4: the 6 synthetic files (L-7), made and checked"
rm -rf "$WORK/dry-files"
run 0 files --out "$WORK/dry-files"
expect "6 files, each with its approved SHA-256" "r['all_approved'] and [f['bytes'] for f in r['files']]==[133,10485760,10485761,70,231,88]"

step "A6: the approval (L-8's allowance, made once, outside every sitting), setup (both binaries and the head verified; the confirmed launch recorded; X2 installed), then settings"
APPROVAL="$WORK/dry/approval/L-8.json"
run 0 approval init --approval "$APPROVAL"
expect "the approval, made once: 4 creates and 2 sends, nothing charged" "r['approval']['total']=={'creates':4,'sends':2} and r['approval']['remaining']=={'creates':4,'sends':2} and r['approval']['made']==[]"
run 0 setup --work "$W" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --server "$SERVER" --approval "$APPROVAL" \
  --targets "$WORK/dry/targets.env" --files "$WORK/dry-files" --checkout "$ROOT" --expect-head "$HEAD" \
  --port "$PORT" --host openwiz.invalid --restore-cmd "$(oldcmd "$PORT")" --restore-log "$WORK/dry/old/server.log" \
  --restore-sha256 "$SERVER_SHA" --expect-sha256 "$OW_SHA" --expect-server-sha256 "$SERVER_SHA" --access-url "$ACCESS_URL" --agent-reply syn-agent-message:data.input --dry-run
expect "setup ready, both binaries and the head verified, PATH guard on X2; sitting 1 inherits the whole allowance" "r['setup']=='ready' and r['path_guard'].endswith('X2') and r['binary']=={'openwiz':'sha256 matches','openwiz-server':'sha256 matches','head':'$HEAD'} and r['approval']['sitting']==1 and r['budget']=={'creates':4,'sends':2}"
run 0 settings --work "$W"
expect "settings: both harnesses, an unoffered combination, the image harnesses, P-N" "r['outcome']=='as_expected' and set(r['settings'])=={'codex','claude-code'} and r['unoffered_found'] and r['image_harnesses'] and r['no_remote_project_found']"

step "A7: lesson 6 (spawn's and tell's help, structure only), then the map"
run 0 recheck --work "$W"
expect "every flag OpenWiz passes is still listed" "r['outcome']=='as_expected' and r['help']['spawn']['missing']==[] and r['help']['tell']['missing']==[]"
run 0 map --work "$W"
expect "T-A Local, T-B Cloud, idle; P-A quiet; no id or title" "r['outcome']=='as_expected' and r['targets']['T-A']['where']=='Local' and r['targets']['P-A']['not_quiet']==0"

step "B: the CLI groups C0 to C5 (the runner; Jake keeps working)"
run 0 run --work "$W" --groups C0,C1,C2,C3,C4,C5 $WAITS
expect "C0 to C5 as expected, every bracket and landing" "r['outcome']=='as_expected' and len(r['groups'])==6 and r['landing_at_end']=='as_expected' and all(g['outside']['verdict']=='as_expected' for g in r['groups'])"
expect "Jake's recent session changed and a new session appeared, neither judged" "any(g['outside']['not_judged_changed'] for g in r['groups']) and any(g['outside']['appeared_not_judged'] for g in r['groups'])"
expect "AL1 after C5: the agent's report of A-1's files, from the reply shape named at setup, recorded: matches (it decides nothing)" "r['agent_reports']['T-B|A1']['verdict']=='matches'"
cp "$WORK/last.out" "$WORK/cli.json"

step "C1: the swap (Jake's OK): the confirmed launch stops; X1's 0.0.4 server starts under the supervisor"
run 0 swap --work "$W" start --minutes 30
expect "swap up, the confirmed launch was running" "r['swap']=='up' and r['old_was_running'] is True"

step "C2: the web groups W1 to W4 (X1 makes the page's requests; the server killed through the supervisor)"
run 0 run --work "$W" --groups W1,W2,W3,W4 $WAITS
expect "W1 to W4 as expected" "r['outcome']=='as_expected' and len(r['groups'])==4 and r['landing_at_end']=='as_expected'"
cp "$WORK/last.out" "$WORK/web.json"

step "D: Jake's hands-on J1 to J6 (in a dry run X1 presses for him, and a stand-in answers)"
jake 0 "$W" J1,J2,J3,J4,J5,J6 $WAITS
expect "J1 to J6 as expected; every agent's report recorded, each matches" "r['outcome']=='as_expected' and len(r['groups'])==6 and sorted(r['agent_reports'])==['P-A|N3','T-A|A2','T-B|A1'] and all(v['verdict']=='matches' for v in r['agent_reports'].values())"
cp "$WORK/last.out" "$WORK/jake.json"

step "E1: S10, parity from the records (no call)"
run 0 parity --work "$W"
expect "parity as expected for created and refused" "r['outcome']=='as_expected' and len(r['parity'])==2"

step "E2: S4, the receipts' structure"
run 0 receipts --work "$W"
expect "4 spawn receipts with #11's fixture structure; the tells documented" "r['outcome']=='as_expected' and r['drift']==[] and r['receipts']['spawn']['count']==4"

step "E3: the swap back: the supervisor stops X1's server and restores the confirmed launch; the closing map"
run 0 swap --work "$W" end
expect "the confirmed launch restored" "r['swap']=='restored'"
if python3 -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=2); c.request('GET','/api/v1/health',headers={'Host':'127.0.0.1:%s'%sys.argv[1]}); sys.exit(0 if c.getresponse().status==200 else 1)" "$PORT"; then
  echo "asserted: the stand-in for Jake's server answers again"; else echo "DRY RUN FAILURE: the stand-in is not answering"; BAD=1; fi
run 0 map --work "$W" --after
expect "T-A and T-B idle" "r['outcome']=='as_expected' and r['targets']['P-A']['threads']>=4"

step "E4: the staged copies: nothing left (AL7), nothing from J3 to J5"
rc=0; OPENWIZ_STATE_DIR="$W/state" PATH="$W/x2:$PATH" "$OPENWIZ" attachment ls --json > "$WORK/last.out" || rc=$?
cat "$WORK/last.out"; echo "(exit $rc)"
[ "$rc" = 0 ] || { echo "DRY RUN FAILURE: attachment ls exited $rc"; BAD=1; }
expect "no staged attachment left" "r['attachments']==[] and r['broken']==[]"

step "Counts"
python3 - "$W/x2/writes.log" "$SCRIPTS/plan.json" <<'PY' || BAD=1
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
by = {}
for r in rows:
    k = "%s %s" % (r.get("kind"), r["outcome"])
    by[k] = by.get(k, 0) + 1
print("X2's write log: %s" % dict(sorted(by.items())))
calls = [r for r in rows if r["outcome"] in ("called", "called_after_hold")]
plan = json.load(open(sys.argv[2]))
planned = sum(s["expect"].get("calls", 0) for g in plan["groups"] for s in g["steps"])
print("writes X2 let through: %d (%d spawns, %d tells); planned (plan.json): %d" % (
    len(calls), sum(r["kind"] == "spawn" for r in calls), sum(r["kind"] == "tell" for r in calls), planned))
ok = len(calls) == planned == 6 and sum(r["kind"] == "spawn" for r in calls) == 4
print("asserted: exactly the planned 4 spawns and 2 tells" if ok else "DRY RUN FAILURE: the write count is not the planned one")
sys.exit(0 if ok else 1)
PY
run 0 approval show --approval "$APPROVAL"
expect "the approval: 4 creates and 2 sends charged, each by its step, in sitting 1; none uncertain; nothing left" "r['approval']['charged']=={'creates':4,'sends':2} and r['approval']['uncertain']=={'creates':0,'sends':0} and r['approval']['remaining']=={'creates':0,'sends':0} and sorted((m['step'],m['sitting']) for m in r['approval']['made'])==[('C2-N1',1),('C3-N2',1),('C4-N4',1),('C5-A1',1),('J1-N3',1),('J2-A2',1)]"
echo "spawns that reached the fake: $(fake_writes dry spawn); tells: $(fake_writes dry tell)"
[ "$(fake_writes dry spawn)" = 4 ] && [ "$(fake_writes dry tell)" = 2 ] && echo "asserted: the fake got exactly 4 spawns and 2 tells" \
  || { echo "DRY RUN FAILURE: the fake's write count"; BAD=1; }
if grep -qE 'thr_syn_|prj_syn_|op-acc-|web-[0-9a-f]{32}|openwiz\.invalid|Synthetic (test thread|new thread|project)|syn-(codex|claude)-model|/tmp/' "$WORK/cli.json" "$WORK/web.json" "$WORK/jake.json"; then
  echo "DRY RUN FAILURE: an id, op id, host name, title, model name or path in a report"; BAD=1
else echo "asserted: the run reports hold no id, op id, host name, title, model name or path"; fi
step "DRY RUN $([ "$BAD" = 0 ] && echo "done: every assertion held" || echo "FAILED") (synthetic; not a live result)"
exit $BAD
