#!/bin/sh
# Tests for Sol's review of 81001d0 (PR #152, round 1): R1 to R10. SYNTHETIC
# ONLY; NOT A LIVE RESULT. Run from the repository root:
#   sh private/evidence/openwiz-0.0.3/ticket-3/scripts/test/sol-tests.sh
# KIT_KEEP_GOING=1 runs every case after a failure (for the red run).
. "$(dirname "$0")/lib.sh"
set +e   # every case below checks its own status
trap 'cleanup' EXIT
want() { [ -z "${SOL_ONLY:-}" ] || echo ",$SOL_ONLY," | grep -q ",$1,"; }  # SOL_ONLY=R2,R5: those sections only
fake_tells() { f="$WORK/$1/world/fake-tells.log"; [ -f "$f" ] && wc -l < "$f" | tr -d ' ' || echo 0; }
py() { python3 - "$KIT" "$@"; }   # py <args> <<'PY' ... : sys.argv[1] is send-kit.py
KITMOD='import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)'

if want R1; then
echo "== R1: a process is signalled only if it is still the one the kit started"
rc=0; py > "$WORK/r1.out" 2>&1 <<PY || rc=$?
$KITMOD
import subprocess, signal, time
a = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
b = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(61)"])
time.sleep(0.3)
ia = kit.identity(a.pid)
stale = dict(ia, pid=b.pid)          # a's record, but the PID now names another process (reuse)
assert kit.signal_if_same(stale, signal.SIGTERM) is False, "signalled a reused PID"
time.sleep(0.3); assert b.poll() is None, "the other process was signalled"
assert kit.signal_if_same(kit.identity(b.pid), signal.SIGTERM) is True
b.wait(5); a.kill()
assert kit.identity(b.pid) is None or kit.identity(b.pid) != stale
PY
[ "$rc" = 0 ] && ok "R1 a reused PID (another process's) is never signalled; a verified one is" || { fail "R1 rc=$rc"; tail -3 "$WORK/r1.out"; }
fi

if want R2; then
echo "== R2: sends are disarmed on every exit; the swap is restored after any failure"
D=$(mkworld r2x2); X="$WORK/r2x2/x"; x2bare "$X"
T13=$(sed -n 's/^M13\tT-A\t//p' "$TICKET/texts.tsv")
printf '{"step":"s","real_room_cli":"%s","threads":{"T-A":"thr_syn_0101","T-B":"thr_syn_0102","T-C":"thr_syn_0103"},"allowed_tell":{"thread":"T-A","mode":"queue","text_sha256":"1145b65b58abfa1b0829a65988894456e78ff71f83f757a79cb80cf47aa15bd9","max_calls":1},"fault":"capture","hold_s":0,"expires_ms":%s,"auth":"a","allowance":"%s"}' \
  "$D/room-cli" "$(( $(date +%s) * 1000 - 1000 ))" "$X/allow" > "$X/step.json"
rc=0; "$X/room-cli" thread tell thr_syn_0101 --mode queue --json -- "$T13" >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_tells r2x2)" = 0 ] && ok "R2 an armed step past its expiry (X1 crashed while armed) lets nothing through" || fail "R2 expiry rc=$rc"

kitsetup r2t >/dev/null 2>&1 || kitsetup r2t
rc=0; py "$WORK/r2t/w" > "$WORK/r2t.out" 2>&1 <<PY || rc=$?
$KITMOD
import argparse, json, os
k = kit.Kit(sys.argv[2]); k.dry = False
k.args = argparse.Namespace(press_timeout=1, answers="chat", poll=0.1, idle_timeout=5, busy_min=1)
step = next(s for g in k.plan["groups"] for s in g["steps"] if s["id"] == "P1-M06")
try:
    kit.run_step(k, step)
except Exception:
    pass
st = json.load(open(os.path.join(k.x2, "step.json")))
assert st.get("allowed_tell") in (None, {}) , "still armed after the timeout: %s" % st["step"]
PY
[ "$rc" = 0 ] && ok "R2 a press that times out leaves no send armed" || { fail "R2 timeout rc=$rc"; tail -2 "$WORK/r2t.out"; }

# The swap: a stand-in for Jake's 0.0.2 server (the real binary, its own launch line) on the origin port.
swapsetup() { # swapsetup <name> <port> [X1's server, default the real one]
  d=$(mkworld "$1"); mkdir -p "$WORK/$1/old"
  oldcmd "$2" > "$WORK/$1/old/cmd.json"
  ( cd "$WORK/$1/old" && { nohup "$SERVER" --port "$2" --allowed-host "$OLDHOST" >> "$WORK/$1/old/server.log" 2>&1 < /dev/null & echo $! > "$WORK/$1/old/pid"; } )
  own "$(cat "$WORK/$1/old/pid")"
  for i in 1 2 3 4 5 6 7 8 9 10; do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" "$2" 2>/dev/null && break; sleep 0.3; done
  python3 "$KIT" setup --work "$WORK/$1/w" --room-cli "$d/room-cli" --openwiz "$OPENWIZ" --server "${3:-$SERVER}" \
    --threads "$WORK/$1/threads.env" --port "$2" --host openwiz.invalid --dry-run \
    --restore-cmd "$(cat "$WORK/$1/old/cmd.json")" --restore-log "$WORK/$1/old/server.log" \
    --restore-sha256 "$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$SERVER")" \
    --allowance "$WORK/$1/allowance" > "$WORK/$1/setup.json" 2>&1 || true
}
old_pid() { ps -eo pid=,args= | awk -v h="--port $1 --allowed-host $OLDHOST" 'index($0, h) && !/awk/ {print $1}' | head -1; }
stubsetup() { # stubsetup <name> <port>: swapsetup with a copy of the stub as X1's server
  mkdir -p "$WORK/$1/stub"; cp "$SCRIPTS/test/stub-server.py" "$WORK/$1/stub/stub-server.py"; chmod 755 "$WORK/$1/stub/stub-server.py"
  swapsetup "$1" "$2" "$WORK/$1/stub/stub-server.py"
}
stub_pid() { ps -eo pid=,args= | awk -v h="$WORK/$1/stub/stub-server.py" 'index($0, h) && !/awk/ {print $1}' | head -1; }
healthy() { python3 -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=3); c.request('GET','/api/v1/health',headers={'Host':'127.0.0.1:%s' % sys.argv[1]}); sys.exit(0 if c.getresponse().status==200 else 1)" "$1" 2>/dev/null; }
restored() { # restored <name> <port> <state wanted>: the stub gone, the 0.0.2 stand-in back and healthy
  state() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('state'))" "$WORK/$1/w/run/swap.json" 2>/dev/null; }
  for i in $(seq 1 120); do [ -z "$(stub_pid "$1")" ] && [ -n "$(old_pid "$2")" ] && healthy "$2" && [ "$(state "$1")" = "$3" ] && break; sleep 0.5; done
  st=$(state "$1")
  [ -z "$(stub_pid "$1")" ] && [ -n "$(old_pid "$2")" ] && healthy "$2" && [ "$st" = "$3" ]
}

SW=$(( ${KIT_PORT:-17370} + 140 ))
swapsetup swapend $SW
rc=0; python3 "$KIT" swap --work "$WORK/swapend/w" start --minutes 5 > "$WORK/swapend-start.json" 2>&1 || rc=$?
up=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('swap'))" "$WORK/swapend-start.json" 2>/dev/null)
[ -z "$(old_pid $SW)" ] && [ "$up" = up ] && ok "R2 swap: the confirmed 0.0.2 stand-in stopped, X1's server up under the supervisor" || fail "R2 swap start (rc=$rc, $up)"
python3 "$KIT" swap --work "$WORK/swapend/w" end > "$WORK/swapend-end.json" 2>&1 || true
sleep 1
[ "$up" = up ] && [ -n "$(old_pid $SW)" ] && ok "R2 swap end: the 0.0.2 stand-in is running again, with its confirmed launch line" || fail "R2 swap end did not restore"
kill "$(old_pid $SW)" 2>/dev/null || true

SW=$(( ${KIT_PORT:-17370} + 150 ))
swapsetup swapcrash $SW
python3 "$KIT" swap --work "$WORK/swapcrash/w" start --minutes 5 > /dev/null 2>&1 || true
SUP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['supervisor']['pid'])" "$WORK/swapcrash/w/run/swap.json" 2>/dev/null || echo)
[ -n "$SUP" ] && kill -9 "$SUP" 2>/dev/null
for i in $(seq 1 120); do [ -n "$(old_pid $SW)" ] && break; sleep 0.5; done  # up to 60 s: the restore is slow under load
st=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['state'])" "$WORK/swapcrash/w/run/swap.json" 2>/dev/null)
[ -n "$SUP" ] && [ -n "$(old_pid $SW)" ] && [ "$st" = restored-by-guard ] \
  && ok "R2 the supervisor killed (SIGKILL): the guard stops X1's server and restores the 0.0.2 stand-in" || fail "R2 supervisor crash (state $st)"
kill "$(old_pid $SW)" 2>/dev/null || true

# Round 3: one owner. The guard is the server's parent and acts on its pipe from the supervisor,
# never on the status file; if the guard dies, the server dies with it (its wrapper reads the guard's pipe).
SW=$(( ${KIT_PORT:-17370} + 145 ))
swapsetup swapfile $SW
python3 "$KIT" swap --work "$WORK/swapfile/w" start --minutes 5 > /dev/null 2>&1 || true
SUP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['supervisor']['pid'])" "$WORK/swapfile/w/run/swap.json" 2>/dev/null || echo)
[ -n "$SUP" ] && kill -STOP "$SUP" 2>/dev/null    # the supervisor frozen; then its status file deleted
rm -f "$WORK/swapfile/w/run/swap.json"; sleep 6
served=0; healthy $SW && served=1                 # X1's server still serving: the guard took no action from the file
[ -n "$SUP" ] && kill -CONT "$SUP" 2>/dev/null; [ -n "$SUP" ] && kill "$SUP" 2>/dev/null
for i in $(seq 1 60); do [ -n "$(old_pid $SW)" ] && healthy $SW && break; sleep 0.5; done
[ -n "$SUP" ] && [ "$served" = 1 ] && [ -n "$(old_pid $SW)" ] && healthy $SW \
  && ok "R2 round 3: the guard acts on its pipe, never on the status file (deleted: no action); the supervisor stopped: 0.0.2 restored" \
  || fail "R2 round 3: guard and status file (served=$served old=$(old_pid $SW))"
kill "$(old_pid $SW)" 2>/dev/null || true

SW=$(( ${KIT_PORT:-17370} + 155 ))
swapsetup guardkill $SW
python3 "$KIT" swap --work "$WORK/guardkill/w" start --minutes 5 > /dev/null 2>&1 || true
GP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['guard']['pid'])" "$WORK/guardkill/w/run/swap.json" 2>/dev/null || echo)
up=0; healthy $SW && up=1
[ -n "$GP" ] && kill -9 "$GP" 2>/dev/null
gone=0; for i in $(seq 1 40); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" $SW 2>/dev/null || { gone=1; break; }; sleep 0.25; done
st=""; for i in $(seq 1 40); do st=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('state'))" "$WORK/guardkill/w/run/swap.json" 2>/dev/null); [ "$st" = guard-died ] && break; sleep 0.25; done
[ "$up" = 1 ] && [ "$gone" = 1 ] && [ "$st" = guard-died ] \
  && ok "R2 round 3: the guard killed (SIGKILL): X1's server dies with it (EOF on its pipe); the supervisor records guard-died (0.0.2 by hand, per HANDOFF)" \
  || fail "R2 round 3: guard killed (up=$up gone=$gone state=$st)"

# Sol's round-2 interleaving, as several kill points in the startup: the supervisor killed at each.
n=0
for delay in 0 0.3 0.8 1.5 3; do
  n=$((n+1)); SW=$(( ${KIT_PORT:-17370} + 205 + n )); name=kp$n
  swapsetup $name $SW
  python3 "$KIT" swap --work "$WORK/$name/w" start --minutes 5 > /dev/null 2>&1 &
  SUP=""; for i in $(seq 1 100); do SUP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['supervisor']['pid'])" "$WORK/$name/w/run/swap.json" 2>/dev/null) && [ -n "$SUP" ] && break; sleep 0.05; done
  sleep $delay; [ -n "$SUP" ] && kill -9 "$SUP" 2>/dev/null
  restored $name $SW restored-by-guard && ok "R2 round 3: the supervisor killed ${delay} s into the swap: X1's server stopped, 0.0.2 restored" \
    || fail "R2 round 3: supervisor killed ${delay} s in (old=$(old_pid $SW) state=$st)"
  kill "$(old_pid $SW)" 2>/dev/null || true; wait 2>/dev/null
done

SW=$(( ${KIT_PORT:-17370} + 160 ))
swapsetup swapdeadline $SW
python3 "$KIT" swap --work "$WORK/swapdeadline/w" start --minutes 0.05 > /dev/null 2>&1 || true
gone=0; [ -z "$(old_pid $SW)" ] && gone=1
for i in $(seq 1 120); do [ -n "$(old_pid $SW)" ] && break; sleep 0.5; done  # up to 60 s: the restore is slow under load
[ "$gone" = 1 ] && [ -n "$(old_pid $SW)" ] && ok "R2 the swap's deadline passes: the go expires and 0.0.2 is restored" || fail "R2 deadline did not restore"
kill "$(old_pid $SW)" 2>/dev/null || true

# Round 2: the startup window. X1's server is the stub (binds its port at once; health 503 when a
# file "bad" sits next to it). The child must be recorded, verified, before it may bind.
SW=$(( ${KIT_PORT:-17370} + 180 ))
stubsetup startcrash $SW; touch "$WORK/startcrash/stub/bad"
python3 "$KIT" swap --work "$WORK/startcrash/w" start --minutes 5 > /dev/null 2>&1 &
for i in $(seq 1 40); do [ -n "$(stub_pid startcrash)" ] && break; sleep 0.25; done
sleep 1   # the stub is up and holds the port; health has not passed
SUP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['supervisor']['pid'])" "$WORK/startcrash/w/run/swap.json" 2>/dev/null || echo)
[ -n "$SUP" ] && kill -9 "$SUP" 2>/dev/null
restored startcrash $SW restored-by-guard && ok "R2 the supervisor killed during startup (the new server bound, not yet healthy): the guard stops it and 0.0.2 answers again" \
  || fail "R2 startup crash: stub=$(stub_pid startcrash) old=$(old_pid $SW) state=$st"
kill "$(stub_pid startcrash)" 2>/dev/null; kill "$(old_pid $SW)" 2>/dev/null || true; wait 2>/dev/null

SW=$(( ${KIT_PORT:-17370} + 185 ))
stubsetup starttimeout $SW; touch "$WORK/starttimeout/stub/bad"
rc=0; python3 "$KIT" swap --work "$WORK/starttimeout/w" start --minutes 5 > "$WORK/starttimeout.json" 2>&1 || rc=$?
restored starttimeout $SW restored && [ "$rc" = 10 ] && ok "R2 the new server never healthy (startup timeout): the swap fails (exit 10), stops it, and 0.0.2 answers again" \
  || fail "R2 startup health timeout: rc=$rc stub=$(stub_pid starttimeout) old=$(old_pid $SW) state=$st"
kill "$(stub_pid starttimeout)" 2>/dev/null; kill "$(old_pid $SW)" 2>/dev/null || true

for f in kill-server:F6 stop-server:F4; do
  act=${f%%:*}; name=restart${f##*:}
  SW=$(( ${KIT_PORT:-17370} + $([ $act = kill-server ] && echo 190 || echo 195) ))
  stubsetup $name $SW
  python3 "$KIT" swap --work "$WORK/$name/w" start --minutes 5 > /dev/null 2>&1
  touch "$WORK/$name/stub/bad"     # the restart after the fault will never be healthy
  python3 "$KIT" swap --work "$WORK/$name/w" $act > /dev/null 2>&1
  rc=0; python3 "$KIT" swap --work "$WORK/$name/w" start-server > "$WORK/$name.json" 2>&1 || rc=$?
  restored $name $SW restored && [ "$rc" = 10 ] && ok "R2 a restart after ${f##*:} that never becomes healthy: stopped, 0.0.2 answers again" \
    || fail "R2 restart after ${f##*:}: rc=$rc stub=$(stub_pid $name) old=$(old_pid $SW) state=$st"
  kill "$(stub_pid $name)" 2>/dev/null; kill "$(old_pid $SW)" 2>/dev/null || true
done

SW=$(( ${KIT_PORT:-17370} + 200 ))
stubsetup restartcrash $SW
python3 "$KIT" swap --work "$WORK/restartcrash/w" start --minutes 5 > /dev/null 2>&1
touch "$WORK/restartcrash/stub/bad"
python3 "$KIT" swap --work "$WORK/restartcrash/w" kill-server > /dev/null 2>&1
python3 "$KIT" swap --work "$WORK/restartcrash/w" start-server > /dev/null 2>&1 &
for i in $(seq 1 40); do [ -n "$(stub_pid restartcrash)" ] && break; sleep 0.25; done
sleep 1
SUP=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['supervisor']['pid'])" "$WORK/restartcrash/w/run/swap.json" 2>/dev/null || echo)
[ -n "$SUP" ] && kill -9 "$SUP" 2>/dev/null
restored restartcrash $SW restored-by-guard && ok "R2 the supervisor killed while restarting after F6: the guard stops the new server and 0.0.2 answers again" \
  || fail "R2 restart crash: stub=$(stub_pid restartcrash) old=$(old_pid $SW) state=$st"
kill "$(stub_pid restartcrash)" 2>/dev/null; kill "$(old_pid $SW)" 2>/dev/null || true; wait 2>/dev/null

SW=$(( ${KIT_PORT:-17370} + 170 ))
swapsetup swapother $SW
OP=$(old_pid $SW); kill "$OP" 2>/dev/null || true; sleep 0.5
python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', $SW)); s.listen(); time.sleep(20)" &
OTHER=$!; sleep 0.5
rc=0; python3 "$KIT" swap --work "$WORK/swapother/w" start --minutes 5 > "$WORK/swapother.json" 2>&1 || rc=$?
alive=0; kill -0 $OTHER 2>/dev/null && alive=1
kill $OTHER 2>/dev/null; wait $OTHER 2>/dev/null || true
[ "$rc" = 10 ] && [ "$alive" = 1 ] && grep -q "not the confirmed launch" "$WORK/swapother.json" \
  && ok "R2 something else on the port (not the confirmed 0.0.2 launch): the swap refuses and signals nothing" || fail "R2 swap other (rc=$rc alive=$alive)"
fi

if want R3; then
echo "== R3: a judged (cold) session stays judged for the whole run, on every field"
kitsetup r3; plant r3 cold-pending; kitrun r3 C1,C2
check "R3 a cold session that turns pending (C1) and is then read-marked (C2): not as expected at C1, on 'pending'" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['outside']['failures'].get('pending',0)>=1" "$WORK/r3.json"
fi

if want R4; then
echo "== R4: the privacy scan knows titles and decodes non-ASCII"
for t in ascii nonascii; do
  kitsetup "r4$t"; [ $t = nonascii ] && plant "r4$t" title-nonascii
  rc=0; python3 - "$KIT" "$WORK/r4$t/w" "$t" > "$WORK/r4$t.out" 2>&1 <<PY || rc=$?
$KITMOD
real = kit.publish
def planted(*a, **kw):
    rep = a[1]
    rep["planted"] = "Synthetic test thread" if sys.argv[3] == "ascii" else "秘密会議 synthetic"
    return real(*a, **kw)
kit.publish = planted
sys.exit(kit.main(["run", "--work", sys.argv[2], "--groups", "C1", "--settle", "0.5", "--late", "0.5",
                   "--idle-timeout", "30", "--busy-min", "1", "--poll", "0.3", "--min-judged", "3"]))
PY
  [ "$rc" = 10 ] && grep -q forbidden "$WORK/r4$t.out" && ! grep -q "Synthetic test thread" "$WORK/r4$t.out" \
    && ! grep -q "79d8" "$WORK/r4$t.out" && ! grep -q "秘密" "$WORK/r4$t.out" \
    && ok "R4 a planted $t title in a report: nothing printed with it" || { fail "R4 $t title published (rc=$rc)"; head -c 300 "$WORK/r4$t.out"; echo; }
done
# Round 2: short titles, and titles JSON would escape: each set as a session's title and planted in a report.
i=0
for t in 'HR' '私事' 'Synthetic "private" title' 'Synthetic\private'; do
  i=$((i+1)); kitsetup "r4b$i"
  python3 - "$WORK/r4b$i/world/world-config.json" "$t" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c["titles"] = {"thr_syn_0005": sys.argv[2]}; json.dump(c, open(sys.argv[1], "w"))
PY
  rc=0; python3 - "$KIT" "$WORK/r4b$i/w" "$t" > "$WORK/r4b$i.out" 2>&1 <<PY || rc=$?
$KITMOD
real = kit.publish
def planted(*a, **kw):
    a[1]["planted"] = {"note": "a title in a value", sys.argv[3]: "and as a key"}
    return real(*a, **kw)
kit.publish = planted
sys.exit(kit.main(["run", "--work", sys.argv[2], "--groups", "C1", "--settle", "0.5", "--late", "0.5",
                   "--idle-timeout", "30", "--busy-min", "1", "--poll", "0.3", "--min-judged", "3"]))
PY
  esc=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1])[1:-1])" "$t")
  if [ "$rc" = 10 ] && grep -q forbidden "$WORK/r4b$i.out" && ! grep -qF -- "$t" "$WORK/r4b$i.out" && ! grep -qF -- "$esc" "$WORK/r4b$i.out"; then
    ok "R4 round 2: the title [$t] in a report (as a value and as a key): nothing printed with it"
  else fail "R4 round 2: the title [$t] published (rc=$rc)"; fi
done

fi

if want R5; then
echo "== R5: landing is cumulative: a duplicate that arrives later still stops the run"
kitsetup r5; plant r5 dup-late
KIT_LATE=3 kitrun r5 C1
check "R5 M13 delivered again during the late wait: not as expected" \
  "r['outcome']=='not_as_expected' and 'M13 on T-A' in r['stopped']" "$WORK/r5.json"
fi

if want R6; then
echo "== R6: L13 needs every page route to answer validly in the window"
kitsetup r6
rc=0; py "$WORK/r6/w" "$WORK/r6/world/room-cli" "$OPENWIZ" "$WORK/r6/qc" > "$WORK/r6.json" 2>"$WORK/r6.err" <<PY || rc=$?
$KITMOD
import http.client, json, os, subprocess, time
k = kit.Kit(sys.argv[2])
class Bad:   # every page request answers 500; the server still did one read (planted in X2's log)
    def __init__(self, *a, **kw): pass
    def request(self, *a, **kw):
        with open(os.path.join(k.x2, "reads.log"), "a") as f:
            f.write(json.dumps({"t_ms": time.time_ns() // 1000000, "step": "L13", "kind": "thread list --json"}) + "\n")
    def getresponse(self):
        class R:
            status = 500
            def read(self): return b'{"error": "synthetic"}'
        return R()
    def close(self): pass
http.client.HTTPConnection = Bad
real_run = subprocess.run
def run(argv, *a, **kw):
    if any(str(x).endswith("quick-check.py") for x in argv):
        time.sleep(3)
        return subprocess.CompletedProcess(argv, 0, b'{"outcome": "pass"}', b"")
    return real_run(argv, *a, **kw)
subprocess.run = run
sys.exit(kit.main(["l13", "--work", sys.argv[2], "--min-judged", "3", "--", "--room-cli", sys.argv[3],
                   "--openwiz", sys.argv[4], "--run-dir", sys.argv[5]]))
PY
check "R6 every page route answering 500 during the check: not as expected (exit $rc)" \
  "'$rc'=='10' and r['l13']['verdict'].startswith('not_as_expected')" "$WORK/r6.json"
# Round 2: a real server, with one route's HTTP 200 answer replaced by a malformed one (schema
# only; a required field missing; or another session as the target). Each must fail L13.
kitsetup r6b; kitswap r6b
# Round 3: every required field of every route, mutated to a wrong type (generated from the contracts).
rc=0; python3 "$SCRIPTS/test/gen-wrong-types.py" "$KIT" "$WORK/r6b/w" "$SOURCE_ROOT/contracts" > "$WORK/r6-gen.out" 2>&1 || rc=$?
[ "$rc" = 0 ] && ok "R6 round 3: every required field of each route's answer, given a wrong type, is rejected ($(python3 -c "import json,sys; print(', '.join('%s %d' % (json.loads(l)['route'], json.loads(l)['mutated']) for l in open(sys.argv[1]) if l.startswith('{')))" "$WORK/r6-gen.out" 2>/dev/null) fields)" \
  || { fail "R6 round 3: wrong types accepted"; cat "$WORK/r6-gen.out"; }
for case in inventory:schema-only session:schema-only preview:schema-only session:no-session preview:wrong-target inventory:no-target session:wrong-target inventory:type-title session:type-final_output preview:type-effects; do
  rc=0; python3 - "$KIT" "$WORK/r6b/w" "$WORK/r6b/world/room-cli" "$OPENWIZ" "$WORK/r6b/qc-${case%%:*}-${case##*:}" "$case" \
    > "$WORK/r6b-$case.json" 2>"$WORK/r6b-$case.err" <<PY || rc=$?
$KITMOD
import http.client, json
route, how = sys.argv[6].split(":")
Real = http.client.HTTPConnection
k = kit.Kit(sys.argv[2]); ta = k.threads["T-A"]
def which(path):
    return "preview" if path.endswith("/preview") else "session" if path.startswith("/api/v1/sessions/") else \
        "inventory" if path.startswith("/api/v1/inventory") else None
class Planted(Real):
    def request(self, method, url, *a, **kw):
        self._route = which(url)
        return Real.request(self, method, url, *a, **kw)
    def getresponse(self):
        r = Real.getresponse(self)
        if self._route != route:
            return r
        doc = json.loads(r.read())
        if how == "schema-only":
            doc = {"schema": doc["schema"]}
        elif how == "no-session":
            del doc["data"]["session"]
        elif how == "wrong-target":
            text = json.dumps(doc).replace(ta, "thr_syn_0005")
            doc = json.loads(text)
        elif how == "no-target":
            doc["data"]["sessions"] = [x for x in doc["data"]["sessions"] if x.get("id") != ta]
        elif how == "type-title":  # Sol's round-2 probes: one wrong type, everything else valid
            for x in doc["data"]["sessions"]:
                x["title"] = 17
        elif how == "type-final_output":
            doc["data"]["final_output"] = 17
        elif how == "type-effects":
            doc["effects"] = 17
        body = json.dumps(doc).encode()
        class R:
            status = 200
            def read(self): return body
        return R()
http.client.HTTPConnection = Planted
sys.exit(kit.main(["l13", "--work", sys.argv[2], "--min-judged", "3", "--", "--room-cli", sys.argv[3],
                   "--openwiz", sys.argv[4], "--run-dir", sys.argv[5], "--wait", "1"]))
PY
  rt=${case%%:*}
  check "R6 round 2: the $rt route's 200 answer with ${case##*:}: L13 not as expected (exit $rc)" \
    "'$rc'=='10' and r['l13']['verdict'].startswith('not_as_expected') and r['l13']['page_routes']['$rt']['failed']>0" "$WORK/r6b-$case.json"
done
kitunswap r6b

fi

if want R7; then
echo "== R7: the proof drivers fail on anything unexpected"
# A kit whose `parity` stops (exit 10, parity not as expected); everything else is the real kit.
mkdir -p "$WORK/r7a"; cat > "$WORK/r7a/kit.py" <<SH
import runpy, sys
if sys.argv[1:2] == ["parity"]:
    print('{"outcome": "not_as_expected", "parity": {}}'); sys.exit(10)
sys.argv[0] = "$KIT"
runpy.run_path("$KIT", run_name="__main__")
SH
rc=0; KIT_SCRIPT="$WORK/r7a/kit.py" sh "$SCRIPTS/test/dry-run.sh" > "$WORK/r7a.out" 2>&1 || rc=$?
[ "$rc" != 0 ] && grep -q "(exit 10)" "$WORK/r7a.out" && ok "R7 dry-run.sh when a step stops (parity, exit 10): the dry run fails ($rc)" || fail "R7 dry-run.sh exited $rc after a step stopped"
if ! grep -q RED_MUTANTS "$SCRIPTS/test/red-runs.sh" "$SCRIPTS/test/red-runs.py" 2>/dev/null; then fail "R7 red-runs.sh has no mutant list it checks (it would run every mutant and never fail)"; else
mkdir -p "$WORK/r7b"
echo '[{"name": "bogus", "why": "a mutation that does not apply", "file": "send-kit.py", "old": "this text is not in the kit", "new": "nor this", "suite": "kit", "must_fail": ["X2-6"]}]' > "$WORK/r7b/mutants.json"
rc=0; RED_MUTANTS="$WORK/r7b/mutants.json" RED_LOGS="$WORK/r7b" sh "$SCRIPTS/test/red-runs.sh" > "$WORK/r7b.out" 2>&1 || rc=$?
[ "$rc" != 0 ] && grep -q "does not apply" "$WORK/r7b.out" && ok "R7 red-runs.sh with a mutation that does not apply: stops nonzero ($rc)" || fail "R7 red-runs.sh went on ($rc)"
# A mutation that changes nothing a test sees (an unexpected green) must fail the runner too.
echo '[{"name": "noop", "why": "an unexpected green", "file": "send-kit.py", "old": "def sha(text):", "new": "def sha(text):  # noop", "suite": "sol", "sol_only": "R8", "must_fail": ["R8"]}]' > "$WORK/r7b/noop.json"
rc=0; RED_MUTANTS="$WORK/r7b/noop.json" RED_LOGS="$WORK/r7b" sh "$SCRIPTS/test/red-runs.sh" > "$WORK/r7c.out" 2>&1 || rc=$?
[ "$rc" != 0 ] && grep -q "UNEXPECTED" "$WORK/r7c.out" && ok "R7 red-runs.sh with a mutant that stays green: fails ($rc)" || fail "R7 red-runs.sh accepted a green mutant ($rc)"
fi
fi

if want R8; then
echo "== R8: parity failures exit nonzero"
kitsetup r8
rc=0; python3 "$KIT" parity --work "$WORK/r8/w" > "$WORK/r8.json" || rc=$?
check "R8 parity with no records: incomplete, exit 10 (got $rc)" "'$rc'=='10' and r['outcome']!='as_expected'" "$WORK/r8.json"
fi

if want R9; then
echo "== R9: every receipt's validity counts, in either order"
for order in good-bad bad-good; do
  kitsetup "r9$order"
  X="$WORK/r9$order/w/x2"
  if [ $order = good-bad ]; then g=1; b=2; else g=2; b=1; fi   # captures are read in name order
  : > "$X/capture-$g-good.out"; echo "Error: HTTP 400: Unsupported mode" > "$X/capture-$g-good.err"
  : > "$X/capture-$b-bad.out"; echo "Error: HTTP 500: synthetic server error" > "$X/capture-$b-bad.err"
  echo '{"threadId": "thr_syn_0101", "ok": true, "delivery": "sent", "mode": "queue"}' > "$X/capture-c-3.out"; : > "$X/capture-c-3.err"
  rc=0; python3 "$KIT" receipts --work "$WORK/r9$order/w" > "$WORK/r9$order.json" || rc=$?
  check "R9 a documented and an undocumented rejection ($order): drift, exit 10" \
    "'$rc'=='10' and 'rejection' in r['drift']" "$WORK/r9$order.json"
done
kitsetup r9cov
echo '{"threadId": "thr_syn_0101", "ok": true, "delivery": "sent", "mode": "queue"}' > "$WORK/r9cov/w/x2/capture-c-1.out"
rc=0; python3 "$KIT" receipts --work "$WORK/r9cov/w" > "$WORK/r9cov.json" || rc=$?
check "R9 receipts missing a required kind (no queued, no steer queued): drift, exit 10" \
  "'$rc'=='10' and any('missing' in d for d in r['drift'])" "$WORK/r9cov.json"

# #995/R1: Queue/thread-busy, Cloud Queue/null and Steer/null are observed
# shapes. The remaining combinations below are synthetic mutations.
for receipt in queue-busy steer-null queue-null queue-turn-starting steer-busy unknown-null; do
  kitsetup "r9-$receipt"
  python3 - "$FIXTURES/send" "$receipt" > "$WORK/r9-$receipt/w/x2/capture-c-1.out" <<'PY'
import json, os, sys
case = sys.argv[2]
fixture = {"steer-null": "tell-steer-queued-observed.json",
           "queue-null": "tell-cloud-queue-observed.json",
           "unknown-null": "tell-cloud-queue-observed.json"}.get(case, "tell-queued-observed.json")
doc = json.load(open(os.path.join(sys.argv[1], fixture)))
if case == "queue-turn-starting":
    doc["queuedMessage"]["waitingOn"] = {"kind": "turn-starting"}
elif case == "unknown-null":
    doc["mode"] = "unknown"
elif case == "steer-busy":
    doc["mode"] = "steer"
print(json.dumps(doc))
PY
  case "$receipt" in
    queue-busy) kind=queued:thread-busy; code=0; documented=True; drift='[]' ;;
    steer-null|queue-null) kind=queued:not-reported; code=0; documented=True; drift='[]' ;;
    *) kind=queued:other; code=10; documented=False; drift="['queued:other']" ;;
  esac
  rc=0; python3 "$KIT" receipts --work "$WORK/r9-$receipt/w" --require "$kind" > "$WORK/r9-$receipt.json" || rc=$?
  check "R9 $receipt: $kind, documented=$documented, exit $code" \
    "'$rc'=='$code' and set(r['receipts'])=={'$kind'} and r['receipts']['$kind']['count']==1 and r['receipts']['$kind']['documented_keys'] is $documented and r['drift']==$drift and (r['outcome']=='as_expected') is $documented" \
    "$WORK/r9-$receipt.json"
done
fi

if want R10; then
echo "== R10: W6's second (double-press) response is checked"
kitsetup r10; kitswap r10
rc=0; py "$WORK/r10/w" > "$WORK/r10.json" 2>"$WORK/r10.err" <<PY || rc=$?
$KITMOD
real = kit.post
seen = {}
def post(k, label, body, *a, **kw):
    n = seen[body["op_id"]] = seen.get(body["op_id"], 0) + 1
    if n == 2 and kw.get("headers") is None:
        return 500, None, "uncertain"     # the second press's answer only
    return real(k, label, body, *a, **kw)
kit.post = post
sys.exit(kit.main(["run", "--work", sys.argv[2], "--groups", "W6", "--settle", "0.5", "--late", "0.5",
                   "--idle-timeout", "30", "--busy-min", "1", "--poll", "0.3", "--min-judged", "3"]))
PY
kitunswap r10
check "R10 the double press's second answer is an error: W6 not as expected" \
  "r['outcome']=='not_as_expected' and 'second' in r['stopped']" "$WORK/r10.json"
fi

if want R11; then
echo "== R11: the suites' cleanup kills only what this run started"
U=$(mktemp -d /tmp/openwiz-unrelated-XXXXXX); cp "$SCRIPTS/test/stub-server.py" "$U/openwiz-server"; chmod 755 "$U/openwiz-server"
UP=$(( ${KIT_PORT:-17370} + 199 ))   # inside the old cleanup's port range, with a matching name
( "$U/openwiz-server" --port $UP --allowed-host unrelated.invalid > /dev/null 2>&1 < /dev/null & echo $! > "$U/pid" )
for i in $(seq 1 30); do python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),1)" $UP 2>/dev/null && break; sleep 0.1; done
rc=0; KIT_PORT=${KIT_PORT:-17370} sh -c ". \"$SCRIPTS/test/lib.sh\"; kitsetup x; kitswap x; kitunswap x" > "$WORK/r11.out" 2>&1 || rc=$?
alive=0; kill -0 "$(cat "$U/pid")" 2>/dev/null && alive=1
kill "$(cat "$U/pid")" 2>/dev/null || true; rm -rf "$U"
[ "$rc" = 0 ] && [ "$alive" = 1 ] && ok "R11 an unrelated openwiz-server in the suite's port range survives the suite's cleanup" \
  || fail "R11 the unrelated server was killed (alive=$alive, suite rc=$rc)"
# ... kitswap records the 0.0.2 stand-in it starts (one identity in the run's own list).
rc=0; KIT_PORT=${KIT_PORT:-17370} sh -c ". \"$SCRIPTS/test/lib.sh\"; kitsetup z; kitswap z; grep -c '' \"\$WORK/owned\" > \"$WORK/r11-kitswap.count\" 2>/dev/null || echo 0 > \"$WORK/r11-kitswap.count\"; kitunswap z" > "$WORK/r11c.out" 2>&1 || rc=$?
[ "$rc" = 0 ] && [ "$(cat "$WORK/r11-kitswap.count" 2>/dev/null)" = 1 ] \
  && ok "R11 kitswap records the 0.0.2 stand-in it starts" || fail "R11 kitswap did not record its stand-in (owned=$(cat "$WORK/r11-kitswap.count" 2>/dev/null))"
# ... and what the run did start is recorded and stopped: a stand-in whose swap never starts.
rc=0; KIT_PORT=${KIT_PORT:-17370} sh -c ". \"$SCRIPTS/test/lib.sh\"; kitsetup y; port=\$(python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['port'])\" \"\$WORK/y/w/kit.json\");
  ( cd \"\$WORK/y/old\" && { nohup \"\$SERVER\" --port \$port --allowed-host \"\$OLDHOST\" >> server.log 2>&1 < /dev/null & echo \$! > \"\$WORK/y/old/pid\"; } )
  own \"\$(cat \"\$WORK/y/old/pid\")\"; cat \"\$WORK/y/old/pid\" > \"$WORK/r11-standin.pid\"; grep -c '' \"\$WORK/owned\" > \"$WORK/r11-owned.count\"" > "$WORK/r11b.out" 2>&1 || rc=$?
sleep 1; SP=$(cat "$WORK/r11-standin.pid" 2>/dev/null)
gone=0; [ -n "$SP" ] && ! kill -0 "$SP" 2>/dev/null && gone=1
[ "$rc" = 0 ] && [ "$(cat "$WORK/r11-owned.count" 2>/dev/null)" = 1 ] && [ "$gone" = 1 ] \
  && ok "R11 a stand-in this run started is recorded (one identity) and stopped by the cleanup, though its swap never started" \
  || { fail "R11 own stand-in (rc=$rc owned=$(cat "$WORK/r11-owned.count" 2>/dev/null) gone=$gone)"; [ -n "$SP" ] && kill "$SP" 2>/dev/null; }
fi

if want P168; then
echo "== P168: Sol's four findings on the 0.0.4 kit (PR #168, a copy of this kit at 3a7b501), checked here"
# (1) Write authorisation across invocations: re-running a step in a new command must not send again.
kitsetup r12a; kitrun r12a C1; first=$RC
kitrun r12a C1; second=$RC
check "P168 (1): C1 run again in a new command: stopped before any send (the step's call is charged in the allowance, for every sitting); one tell in all" \
  "'$first'=='0' and '$second'=='10' and 'made their calls already' in r['stopped']" "$WORK/r12a.json"
[ "$(fake_tells r12a)" = 1 ] && ok "P168 (1): the re-run sent nothing" || fail "P168 (1): the re-run reached the fake ($(fake_tells r12a))"

# (2) A tell waiting on the writes lock while X1 disarms must not dispatch.
D=$(mkworld r12b); X="$WORK/r12b/x"; x2bare "$X"
T13=$(sed -n 's/^M13\tT-A\t//p' "$TICKET/texts.tsv")
rc=0; python3 - "$X" "$D/room-cli" "$T13" <<'PY' || rc=$?
import fcntl, json, os, subprocess, sys, time
x, real, text = sys.argv[1:]
def step(name, allow):
    s = {"step": name, "real_room_cli": real, "threads": {"T-A": "thr_syn_0101", "T-B": "thr_syn_0102", "T-C": "thr_syn_0103"},
         "allowed_tell": allow, "fault": "capture", "hold_s": 0, "expires_ms": int(time.time() * 1000) + 600000,
         "auth": name, "allowance": os.path.join(x, "allow")}
    open(os.path.join(x, "step.json.tmp"), "w").write(json.dumps(s)); os.replace(os.path.join(x, "step.json.tmp"), os.path.join(x, "step.json"))
step("armed", {"thread": "T-A", "mode": "queue", "max_calls": 1,
               "text_sha256": "1145b65b58abfa1b0829a65988894456e78ff71f83f757a79cb80cf47aa15bd9"})
lock = open(os.path.join(x, "tell.lock"), "a"); fcntl.flock(lock, fcntl.LOCK_EX)   # another writer holds the lock
p = subprocess.Popen([os.path.join(x, "room-cli"), "thread", "tell", "thr_syn_0101", "--mode", "queue", "--json", "--", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)                    # the tell has read the armed step and is waiting on the lock
step("between-steps", None)        # X1 disarms (under the same lock, as arm() does)
fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
sys.exit(0 if p.wait(20) == 97 else 1)
PY
[ "$rc" = 0 ] && [ "$(fake_tells r12b)" = 0 ] && ok "P168 (2): a tell waiting on the lock while the step is disarmed is refused, and nothing is sent" \
  || fail "P168 (2): the waiting tell dispatched after disarm (rc=$rc, fake tells $(fake_tells r12b))"

# (3) The judged set and its baseline hold for the whole sitting: a judged session that changes
# between two separate run commands fails the second.
kitsetup r12c; kitrun r12c C1
python3 - "$WORK/r12c/world/world.json" <<'PY'
import json, sys
w = json.load(open(sys.argv[1])); w["touched"] = w.get("touched", 0) + 1; json.dump(w, open(sys.argv[1], "w"))
PY
kitrun r12c C4
check "P168 (3): a judged (cold) session read-marked between two run commands: the second run fails it (the sitting's baseline)" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['outside']['failures'].get('lastReadAt',0)>=1" "$WORK/r12c.json"

# (4) A call X2 refuses (not a tell) during the run must stop it, not just be counted.
kitsetup r12d
cat > "$WORK/r12d/openwiz" <<SH
#!/bin/sh
"$OPENWIZ" "\$@"; rc=\$?
room-cli thread log thr_syn_0101 --json --limit 1 >/dev/null 2>&1   # a read off OpenWiz's allowlist
exit \$rc
SH
chmod 700 "$WORK/r12d/openwiz"
python3 - "$WORK/r12d/w/kit.json" "$WORK/r12d/openwiz" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c["openwiz"] = sys.argv[2]; json.dump(c, open(sys.argv[1], "w"))
PY
kitrun r12d C1
check "P168 (4): a call X2 refused during a step (a read off the allowlist): the run stops" \
  "r['outcome']=='not_as_expected' and 'refused' in r['stopped']" "$WORK/r12d.json"
fi

if want R12; then
echo "== R12: a tell held before its call is authorised again after the hold"
# hold <case>: arm a hold-before step with X1's own arm(), start a tell, then disarm (or let the
# step expire) during the hold; the parent stays alive throughout.
for case in disarm expiry; do
  kitsetup "r12$case"
  rc=0; python3 - "$KIT" "$WORK/r12$case/w" "$case" > "$WORK/r12$case.out" 2>&1 <<PY || rc=$?
$KITMOD
import json, os, subprocess, time
k = kit.Kit(sys.argv[2]); case = sys.argv[3]
text = k.texts["M13"]
ttl = 300 if case == "disarm" else -1.5        # expiry: the step expires 1.5 s into a three-second hold
k.arm("held", ("T-A", "queue", kit.sha(text), 1), "hold-before", 3, ttl_s=ttl)
env = k.env()
p = subprocess.Popen(["room-cli", "thread", "tell", k.threads["T-A"], "--mode", "queue", "--json", "--", text],
                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not os.path.exists(os.path.join(k.x2, "holding-before")):
    time.sleep(0.05)
if case == "disarm":
    k.disarm()                                   # X1 closes the gate during the hold
rc = p.wait(20)
k.settled_tells("held", 3)                       # X1's waiter recognises the end (no timeout)
t = k.tells("held")
print(json.dumps({"exit": rc, "calls": t["calls"], "revoked": t.get("revoked"), "attempts": t["attempts"]}))
sys.exit(0 if rc == 98 and t["calls"] == 0 and t.get("revoked") == 1 and t["attempts"] == 1 else 1)
PY
  [ "$rc" = 0 ] && [ "$(fake_tells r12$case)" = 0 ] \
    && ok "R12 a held tell whose step was $([ $case = disarm ] && echo disarmed || echo expired) during the hold: aborted with zero calls, recorded, recognised by X1" \
    || { fail "R12 held $case: dispatched or not recognised (rc=$rc, fake tells $(fake_tells r12$case))"; tail -2 "$WORK/r12$case.out"; }
done
fi

if want R12; then
echo "== R12 (#168): a held tell is not called once the sitting is tainted, or its ledger unreadable"
for case in refusal unreadable; do
  kitsetup "r12$case"
  rc=0; python3 - "$KIT" "$WORK/r12$case/w" "$case" > "$WORK/r12$case.out" 2>&1 <<PY || rc=$?
$KITMOD
import json, os, subprocess, time
k = kit.Kit(sys.argv[2]); case = sys.argv[3]
text = k.texts["M13"]
k.arm("held", ("T-A", "queue", kit.sha(text), 1), "hold-before", 3)
p = subprocess.Popen(["room-cli", "thread", "tell", k.threads["T-A"], "--mode", "queue", "--json", "--", text],
                     env=k.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not os.path.exists(os.path.join(k.x2, "holding-before")):
    time.sleep(0.05)
if case == "refusal":                            # another call, refused by X2, taints the sitting
    subprocess.run([os.path.join(k.x2, "room-cli"), "project", "attachment", "upload", "--json"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
else:                                            # the ledger can no longer be read
    with open(os.path.join(k.x2, "sitting.log"), "a") as f:
        f.write("not json\n")
rc = p.wait(20)
k.settled_tells("held", 3)
out = [json.loads(l)["outcome"] for l in open(os.path.join(k.x2, "tell.log")) if json.loads(l).get("step") == "held"]
t = k.tells("held")
print(json.dumps({"exit": rc, "calls": t["calls"], "outcomes": out, "ledger": len(k.ledger())}))
sys.exit(0 if rc == 98 and t["calls"] == 0 and out[-1] == "aborted_tainted" and k.ledger() else 1)
PY
  [ "$rc" = 0 ] && [ "$(fake_tells r12$case)" = 0 ] \
    && ok "R12 a held tell, then $([ $case = refusal ] && echo 'another call refused (the sitting tainted)' || echo 'the ledger made unreadable') during the hold: aborted with zero calls, the taint kept" \
    || { fail "R12 held tell after $case: dispatched or not recognised (rc=$rc, fake tells $(fake_tells r12$case))"; tail -2 "$WORK/r12$case.out"; }
done
fi

if want R13; then
echo "== R13: any refusal at X2 taints the whole sitting (the ledger); outcomes are decided when published"
refuse_call() { "$WORK/$1/w/x2/room-cli" project attachment upload --json > /dev/null 2>&1; }   # refused by X2, nothing called
kitsetup r13a; refuse_call r13a; kitrun r13a C1
check "R13 a refusal before the first run: the run stops on entry, before any send (exit $RC)" \
  "'$RC'=='10' and 'refused' in r['stopped'] and 'nothing was done' in r['stopped']" "$WORK/r13a.json"
[ "$(fake_tells r13a)" = 0 ] && ok "R13 before the first run: nothing sent" || fail "R13 before the first run: a tell was sent"
kitsetup r13b; kitrun r13b C1; refuse_call r13b; kitrun r13b C4
check "R13 a refusal between two phases: the next run stops on entry, before any send (exit $RC)" \
  "'$RC'=='10' and 'refused' in r['stopped'] and 'nothing was done' in r['stopped']" "$WORK/r13b.json"
[ "$(fake_tells r13b)" = 1 ] && ok "R13 between phases: only the first phase's tell was sent" || fail "R13 between phases: $(fake_tells r13b) tells"
kitsetup r13c; refuse_call r13c
rc=0; python3 "$KIT" map --work "$WORK/r13c/w" > "$WORK/r13c.json" 2>&1 || rc=$?
check "R13 a refusal, then a preparation command (map): it stops on entry (exit $rc)" "'$rc'=='10' and 'refused' in r['stopped'] and 'nothing was done' in r['stopped']" "$WORK/r13c.json"
kitsetup r13d; kitrun r13d C1
T13=$(sed -n 's/^M13\tT-A\t//p' "$TICKET/texts.tsv")
"$WORK/r13d/w/x2/room-cli" thread tell thr_syn_0101 --mode queue --json -- "$T13" > /dev/null 2>&1   # a send between phases: refused
kitrun r13d C4
check "R13 a send refused between phases (a tell, not a read): the next run stops on entry (exit $RC)" "'$RC'=='10' and 'refused' in r['stopped'] and 'nothing was done' in r['stopped']" "$WORK/r13d.json"
# The end-of-run boundary (Sol on #168): a refusal after the run's last check, during its
# final snapshot, just before the report is published. The run is X1's own main().
kitsetup r13e
rc=0; python3 - "$KIT" "$WORK/r13e/w" > "$WORK/r13e.json" 2> "$WORK/r13e.err" <<PY || rc=$?
$KITMOD
import os, subprocess
w = sys.argv[2]
real = kit.publish
def late_refusal(k, rep):          # the final snapshot's moment: after every check run_groups makes
    if rep.get("report") == "openwiz-0.0.3-live-test":
        subprocess.run([os.path.join(w, "x2", "room-cli"), "project", "attachment", "upload", "--json"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return real(k, rep)
kit.publish = late_refusal
sys.exit(kit.main(["run", "--work", w, "--groups", "C1", "--settle", "0.5", "--late", "0.5", "--idle-timeout", "30",
                   "--busy-min", "1", "--poll", "0.3", "--press-timeout", "30", "--min-judged", "3"]))
PY
check "R13 a refusal during the run's final snapshot (after its last check): the report is not as expected (exit $rc)" \
  "'$rc'=='10' and r['outcome']=='not_as_expected' and r['x2_ledger']['calls_refused']==1" "$WORK/r13e.json"
# The ledger is written under X2's lock: while X1 holds it (as publish does), a refusal waits.
kitsetup r13f
rc=0; python3 - "$KIT" "$WORK/r13f/w" > "$WORK/r13f.out" 2>&1 <<PY || rc=$?
$KITMOD
import os, subprocess, time
k = kit.Kit(sys.argv[2])
with k.lock():
    p = subprocess.Popen([os.path.join(k.x2, "room-cli"), "project", "attachment", "upload", "--json"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    assert k.ledger() == [] and p.poll() is None, "the refusal was written while the lock was held"
p.wait(10)
assert len(k.ledger()) == 1, "the refusal was not written after the lock was released"
PY
[ "$rc" = 0 ] && ok "R13 a refusal waits for X2's lock before it is written to the ledger" || { fail "R13 ledger lock (rc=$rc)"; tail -2 "$WORK/r13f.out"; }
# swap end in a tainted sitting: 0.0.2 is still restored, and the report still fails.
kitsetup r13g; kitswap r13g; refuse_call r13g
rc=0; python3 "$KIT" swap --work "$WORK/r13g/w" end > "$WORK/r13g.json" 2>&1 || rc=$?
killown "$WORK/r13g/w/run/swap.json" restored_old
check "R13 swap end in a tainted sitting: 0.0.2 restored, the report not as expected (exit $rc)" \
  "'$rc'=='10' and r['swap'] in ('restored', 'restored-by-guard') and r['outcome']=='not_as_expected'" "$WORK/r13g.json"
fi

if want ALLOW; then
echo "== ALLOW (Sol's R8 on #168): L-8's 23 sends are one allowance for every sitting, kept outside them"
A="$WORK/allow-shared"
kitsetup al1 --allowance "$A"
check "ALLOW a first sitting starts with the whole allowance" "r['allowance']=={'total': 23, 'used': 0, 'remaining': 23}" "$WORK/al1/setup.json"
kitrun al1 C1
check "ALLOW the first sitting's C1 is as expected (exit $RC)" "'$RC'=='0' and r['allowance']['used']==1" "$WORK/al1.json"
kitsetup al2 --allowance "$A"
check "ALLOW a fresh setup inherits only what is left (22 of 23)" "r['allowance']=={'total': 23, 'used': 1, 'remaining': 22}" "$WORK/al2/setup.json"
kitrun al2 C1
check "ALLOW the fresh sitting may not repeat a step already called: it stops before any send (exit $RC)" \
  "'$RC'=='10' and 'earlier sitting' in r['stopped']" "$WORK/al2.json"
[ "$(fake_tells al2)" = 0 ] && ok "ALLOW the repeated step reached nothing" || fail "ALLOW a repeated step reached the fake"
kitsetup al3 --allowance "$A"
kitrun al3 C4
check "ALLOW the fresh sitting runs the groups still to run, and the count goes on (exit $RC)" \
  "'$RC'=='0' and r['allowance']=={'total': 23, 'used': 2, 'remaining': 21}" "$WORK/al3.json"
# The allowance used up (synthetic charges for 23 other steps): X1 stops, and X2 refuses by itself.
F="$WORK/allow-full"; mkdir -p "$F"; chmod 700 "$F"
python3 - "$F" <<'PY'
import json, os, sys
d = sys.argv[1]
json.dump({"total": 23, "approval": "L-8"}, open(os.path.join(d, "allowance.json"), "w"))
with open(os.path.join(d, "charges.log"), "w") as f:
    for i in range(23):
        f.write(json.dumps({"t_ms": 0, "sitting": "earlier", "step": "S%02d" % i, "op": "reserve"}) + "\n")
PY
kitsetup al4 --allowance "$F"
check "ALLOW a setup with nothing left reports 0 remaining" "r['allowance']['remaining']==0" "$WORK/al4/setup.json"
kitrun al4 C1
check "ALLOW nothing left: the run stops before any send (exit $RC)" "'$RC'=='10' and 'allowance' in r['stopped']" "$WORK/al4.json"
rc=0; python3 - "$KIT" "$WORK/al4/w" > "$WORK/al4x.out" 2>&1 <<PY || rc=$?
$KITMOD
import subprocess
k = kit.Kit(sys.argv[2]); text = k.texts["M13"]
k.arm("direct", ("T-A", "queue", kit.sha(text), 1))   # X1's own check bypassed: X2 must refuse by itself
r = subprocess.run(["room-cli", "thread", "tell", k.threads["T-A"], "--mode", "queue", "--json", "--", text],
                   env=k.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sys.exit(0 if r.returncode == 97 else 1)
PY
[ "$rc" = 0 ] && [ "$(fake_tells al4)" = 0 ] && ok "ALLOW nothing left: X2 refuses an armed tell by itself (97), nothing reaches the fake" \
  || fail "ALLOW X2 let a tell through with nothing left (rc=$rc, fake tells $(fake_tells al4))"
# A zero-call abort returns its charge: a held tell whose parent is killed made no call.
kitsetup al5 --allowance "$WORK/allow-5"
rc=0; python3 - "$KIT" "$WORK/al5/w" > "$WORK/al5.out" 2>&1 <<PY || rc=$?
$KITMOD
import json, os, signal, subprocess, time
k = kit.Kit(sys.argv[2]); text = k.texts["M13"]
k.arm("held", ("T-A", "queue", kit.sha(text), 1), "hold-before", 2)
p = subprocess.Popen(["sh", "-c", 'room-cli thread tell "\$0" --mode queue --json -- "\$1" >/dev/null 2>&1; true',
                      k.threads["T-A"], text], env=k.env())
while not os.path.exists(os.path.join(k.x2, "holding-before")):
    time.sleep(0.05)
reserved = k.allowance()["used"]
p.send_signal(signal.SIGKILL); p.wait()
k.settled_tells("held", 2)
print(json.dumps({"reserved": reserved, "after": k.allowance()}))
sys.exit(0 if reserved == 1 and k.allowance()["used"] == 0 else 1)
PY
[ "$rc" = 0 ] && ok "ALLOW a held tell reserves its send, and a zero-call abort returns it" || { fail "ALLOW reservation (rc=$rc)"; tail -2 "$WORK/al5.out"; }
mkdir -p "$WORK/allow-7"; chmod 700 "$WORK/allow-7"; echo '{"total": 30, "approval": "L-8"}' > "$WORK/allow-7/allowance.json"
rc=0; python3 "$KIT" setup --work "$WORK/al7/w" --room-cli "$OPENWIZ" --openwiz "$OPENWIZ" --threads "$WORK/al1/threads.env" \
  --allowance "$WORK/allow-7" --dry-run > "$WORK/al7.json" 2>&1 || rc=$?
check "ALLOW an allowance with another total (not L-8's 23): setup stops (exit $rc)" "'$rc'=='10' and 'allowance' in r['stopped']" "$WORK/al7.json"
fi

if want R14; then
echo "== R14: a missing or unreadable charge journal is unknown usage, never zero usage"
mode600() { [ "$(stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1")" = 600 ]; }
A="$WORK/allow-r14"
kitsetup r14a --allowance "$A"
[ -f "$A/charges.log" ] && [ ! -s "$A/charges.log" ] && mode600 "$A/charges.log" \
  && ok "R14 a first setup creates the allowance's charge journal, empty (0600), with its manifest" \
  || fail "R14 a first setup made no empty journal"
kitrun r14a C1
check "R14 the first sitting's C1 is as expected, its send charged (exit $RC)" "'$RC'=='0' and r['allowance']['used']==1" "$WORK/r14a.json"
mv "$A/charges.log" "$WORK/r14-journal"   # Sol's partial loss: the manifest and the --allowance path stay
# Recovery: a fresh setup on the same allowance must stop for reconciliation, not start at zero.
rc=0; kitsetup r14b --allowance "$A" || rc=$?
check "R14 recovery after the journal is lost: setup stops for reconciliation, never zero usage (exit $rc)" \
  "'$rc'=='10' and 'reconcil' in r['stopped'] and 'allowance' not in r" "$WORK/r14b/setup.json"
[ ! -e "$WORK/r14b/w" ] && [ ! -e "$A/charges.log" ] \
  && ok "R14 that setup made no sitting and recreated no history" || fail "R14 setup after the loss made a sitting or a journal"
[ -e "$WORK/r14b/w/kit.json" ] && kitrun r14b C1   # Sol's repeat of the consumed C1, if a sitting was made
total=$(( $(fake_tells r14a) + $(fake_tells r14b) ))
[ "$total" = 1 ] && ok "R14 the consumed C1 is not sent again: one tell across both sittings" \
  || fail "R14 the consumed C1 was sent again ($total tells across sittings)"
# X1 in the sitting set up before the loss: the run stops before any send.
kitrun r14a C4
check "R14 a run in the earlier sitting after the loss: X1 stops for reconciliation before any send (exit $RC)" \
  "'$RC'=='10' and 'reconcil' in r['stopped']" "$WORK/r14a.json"
[ "$(fake_tells r14a)" = 1 ] && [ ! -e "$A/charges.log" ] && ok "R14 that run sent nothing and recreated no history" \
  || fail "R14 the run after the loss sent ($(fake_tells r14a) tells) or made a journal"
# Unreadable, not missing: the same stop, before the work directory is made.
cp "$WORK/r14-journal" "$A/charges.log"; echo '{"op": "reserve", "step"' >> "$A/charges.log"
rc=0; kitsetup r14c --allowance "$A" || rc=$?
check "R14 an unreadable journal: setup stops for reconciliation and makes no sitting (exit $rc)" \
  "'$rc'=='10' and 'reconcil' in r['stopped'] and not __import__('os').path.exists('$WORK/r14c/w')" "$WORK/r14c/setup.json"
# Jake's reconciliation (the journal put back whole): the history is inherited again.
mv "$WORK/r14-journal" "$A/charges.log"
kitsetup r14d --allowance "$A"
check "R14 the journal put back: a fresh setup inherits its history (22 of 23)" \
  "r['allowance']=={'total': 23, 'used': 1, 'remaining': 22}" "$WORK/r14d/setup.json"
# A journal with no manifest is history without its approval: setup stops too.
B="$WORK/allow-r14-nomanifest"; mkdir -p "$B"; chmod 700 "$B"; cp "$A/charges.log" "$B/charges.log"
rc=0; kitsetup r14e --allowance "$B" || rc=$?
check "R14 a journal without its manifest: setup stops for reconciliation (exit $rc)" \
  "'$rc'=='10' and 'reconcil' in r['stopped']" "$WORK/r14e/setup.json"

# Direct admission: X2 by itself, X1's own check bypassed, in a sitting whose journal is lost.
kitsetup r14x --allowance "$WORK/allow-r14x"
rm -f "$WORK/allow-r14x/charges.log"
rc=0; python3 - "$KIT" "$WORK/r14x/w" > "$WORK/r14x.out" 2>&1 <<PY || rc=$?
$KITMOD
import json, os, subprocess
k = kit.Kit(sys.argv[2]); text = k.texts["M13"]
k.arm("direct", ("T-A", "queue", kit.sha(text), 1))
r = subprocess.run(["room-cli", "thread", "tell", k.threads["T-A"], "--mode", "queue", "--json", "--", text],
                   env=k.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
last = [json.loads(l) for l in open(os.path.join(k.x2, "tell.log"))][-1]
print(json.dumps({"exit": r.returncode, "last": last}))
sys.exit(0 if r.returncode == 97 and last["outcome"] == "refused" and "reconcil" in last["why"] else 1)
PY
[ "$rc" = 0 ] && [ "$(fake_tells r14x)" = 0 ] && [ ! -e "$WORK/allow-r14x/charges.log" ] \
  && ok "R14 direct admission with the journal missing: X2 refuses by itself (97), nothing sent, no history made" \
  || { fail "R14 X2 admitted a tell with the journal missing (rc=$rc, fake tells $(fake_tells r14x))"; tail -2 "$WORK/r14x.out"; }
# A zero-call abort whose journal was lost during the hold returns nothing: no journal of releases alone.
kitsetup r14y --allowance "$WORK/allow-r14y"
rc=0; python3 - "$KIT" "$WORK/r14y/w" "$WORK/allow-r14y" > "$WORK/r14y.out" 2>&1 <<PY || rc=$?
$KITMOD
import os, signal, subprocess, time
k = kit.Kit(sys.argv[2]); text = k.texts["M13"]; j = os.path.join(sys.argv[3], "charges.log")
k.arm("held", ("T-A", "queue", kit.sha(text), 1), "hold-before", 2)
p = subprocess.Popen(["sh", "-c", 'room-cli thread tell "\$0" --mode queue --json -- "\$1" >/dev/null 2>&1; true',
                      k.threads["T-A"], text], env=k.env())
while not os.path.exists(os.path.join(k.x2, "holding-before")):
    time.sleep(0.05)
os.remove(j)                                  # the journal lost during the hold
p.send_signal(signal.SIGKILL); p.wait()
k.settled_tells("held", 2)
print("journal after the abort:", os.path.exists(j) and open(j).read())
sys.exit(0 if not os.path.exists(j) else 1)
PY
[ "$rc" = 0 ] && [ "$(fake_tells r14y)" = 0 ] && ok "R14 a release with the journal lost recreates no history (no negative usage)" \
  || { fail "R14 a release recreated the journal (rc=$rc)"; tail -2 "$WORK/r14y.out"; }
# A report published after the loss (a clean ledger) still fails, and is still written.
rc=0; python3 - "$KIT" "$WORK/r14y/w" > "$WORK/r14p.out" 2>&1 <<PY || rc=$?
$KITMOD
import os
k = kit.Kit(sys.argv[2]); before = len(os.listdir(k.run))
rep = kit.publish(k, {"outcome": "as_expected"})
print(rep)
sys.exit(0 if rep["outcome"] == "not_as_expected" and rep["allowance"] == "unknown" and "reconcil" in rep["stopped"]
         and not any(rep["x2_ledger"].values()) and len(os.listdir(k.run)) == before + 1 else 1)
PY
[ "$rc" = 0 ] && ok "R14 a report published with the journal lost: not as expected, usage unknown, still written" \
  || { fail "R14 report after the loss (rc=$rc)"; tail -2 "$WORK/r14p.out"; }
# Unreadable at X2 alone: a journal with a broken line admits nothing.
D=$(mkworld r14z); X="$WORK/r14z/x"; x2bare "$X"; echo 'not json' >> "$X/allow/charges.log"
T13=$(sed -n 's/^M13\tT-A\t//p' "$TICKET/texts.tsv")
printf '{"step":"s","real_room_cli":"%s","threads":{"T-A":"thr_syn_0101","T-B":"thr_syn_0102","T-C":"thr_syn_0103"},"allowed_tell":{"thread":"T-A","mode":"queue","text_sha256":"1145b65b58abfa1b0829a65988894456e78ff71f83f757a79cb80cf47aa15bd9","max_calls":1},"fault":"capture","hold_s":0,"expires_ms":%s,"auth":"a","allowance":"%s"}' \
  "$D/room-cli" "$(( $(date +%s) * 1000 + 600000 ))" "$X/allow" > "$X/step.json"
rc=0; "$X/room-cli" thread tell thr_syn_0101 --mode queue --json -- "$T13" >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_tells r14z)" = 0 ] && ok "R14 X2 alone: an unreadable journal admits nothing (97)" || fail "R14 X2 unreadable journal rc=$rc"
fi

if want R15; then
echo "== R15: C8 accepts steer on busy Claude Code as sent (room-cli v141) or queued (0.43.1), exactly as reported"
kitsetup r15sent; plant r15sent steer-sent; kitrun r15sent C8
check "R15 steer sent (the v141 shape): C8 as expected, shown as accepted" \
  "r['outcome']=='as_expected' and r['groups'][0]['steps'][1]['got']['status']=='accepted' and r['groups'][0]['steps'][1]['got']['delivery']=='accepted'" "$WORK/r15sent.json"
kitsetup r15queued; kitrun r15queued C8
check "R15 steer queued (the 0.43.1 shape): C8 as expected, shown as queued" \
  "r['outcome']=='as_expected' and r['groups'][0]['steps'][1]['got']['status']=='queued' and r['groups'][0]['steps'][1]['got']['delivery']=='queued'" "$WORK/r15queued.json"
kitsetup r15refuse; plant r15refuse refuse-steer; kitrun r15refuse C8
check "R15 steer refused: C8 not as expected" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['steps'][1]['got']['status']=='failed'" "$WORK/r15refuse.json"
rc=0; py > "$WORK/r15unit.out" 2>&1 <<PY || rc=$?
$KITMOD
import json
step = next(s for g in json.load(open(kit.os.path.join(kit.HERE, "plan.json")))["groups"] if g["id"] == "C8" for s in g["steps"] if s["id"] == "C8-M12")
e = step["expect"]
base = {"exit": 0, "effect": "asks_to_steer", "calls": 1}
good = [dict(base, status="accepted", delivery="accepted"), dict(base, status="queued", delivery="queued")]
bad = [dict(base, status="accepted", delivery="queued"), dict(base, status="queued", delivery="accepted"),
       dict(base, status="uncertain", delivery="uncertain"), dict(base, status="failed", delivery="failed"),
       dict(base, status="accepted", delivery="accepted", effect="starts_turn")]
assert all(not kit.check(e, g) for g in good), [kit.check(e, g) for g in good]
assert all(kit.check(e, b) for b in bad), [kit.check(e, b) for b in bad]
print("ok")
PY
[ "$rc" = 0 ] && grep -q '^ok$' "$WORK/r15unit.out" && ok "R15 C8-M12 accepts only the pairs sent/sent and queued/queued, with asks_to_steer; mixed, uncertain and failed fail" || { fail "R15 C8-M12 pair check"; cat "$WORK/r15unit.out"; }
fi

if want R16; then
echo "== R16: the rest of the phone part (P1b) runs in a later sitting after P1-M06 was charged in an earlier one"
A="$WORK/allow-r16"
kitsetup r16a --allowance "$A"; kitswap r16a; kitrun r16a P1; kitunswap r16a
check "R16 sitting A: P1 is P1-M06 alone, as expected, 1 send charged" \
  "r['outcome']=='as_expected' and [s['step'] for s in r['groups'][0]['steps']]==['P1-M06'] and r['allowance']['used']==1" "$WORK/r16a.json"
kitsetup r16b --allowance "$A"; kitswap r16b; kitrun r16b P1b
check "R16 sitting B (new threads, same allowance): P1b (M15, Check again, M13) as expected, F7 produced, 3 charged in all" \
  "r['outcome']=='as_expected' and [s['step'] for s in r['groups'][0]['steps']]==['P1-M15','P1-check','P1-M13'] and r['groups'][0]['steps'][0].get('fault_produced') is True and r['allowance']['used']==3" "$WORK/r16b.json"
kitrun r16b P1
check "R16 P1 again in sitting B: stopped before any send (P1-M06 is charged)" \
  "'made their calls already' in (r.get('stopped') or '') and 'nothing was sent' in r['stopped']" "$WORK/r16b.json"
[ "$(wc -l < "$A/charges.log" | tr -d ' ')" = 3 ] && ok "R16 the allowance still holds 3 charges" || fail "R16 charges after the refused P1"
kitunswap r16b
fi

[ "$FAILED" = 0 ] && echo "== all Sol R1-R10 tests ok (synthetic; not a live result)" || { echo "== Sol R1-R10 tests FAILED"; exit 1; }
