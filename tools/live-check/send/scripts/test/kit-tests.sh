#!/bin/sh
# Tests X2 (x2-shim.py) and X1 (send-kit.py) on the repository's fake room-cli,
# behind world-stub.py. SYNTHETIC ONLY; NOT A LIVE RESULT. Nothing is sent
# anywhere: every "send" goes to the fake. Run from the repository root:
#   sh private/evidence/openwiz-0.0.3/ticket-3/scripts/test/kit-tests.sh
# About 6 minutes (X2's holds are real seconds). KIT_KEEP_GOING=1 runs every
# case after a failure (for a red run).
only() { [ -z "${KIT_ONLY:-}" ] || echo ",$KIT_ONLY," | grep -q ",$1,"; }
. "$(dirname "$0")/lib.sh"

fake_tells() { f="$WORK/$1/world/fake-tells.log"; [ -f "$f" ] && wc -l < "$f" | tr -d ' ' || echo 0; }

if only x2; then
# ---------------------------------------------------------------- X2, alone
echo "== X2: the call-counting shim, called directly"
D=$(mkworld x2)
X="$WORK/x2/x"; x2bare "$X"
T13=$(sed -n 's/^M13\tT-A\t//p' "$TICKET/texts.tsv")
SHA13=1145b65b58abfa1b0829a65988894456e78ff71f83f757a79cb80cf47aa15bd9
step() { # step <name> <thread|-> <mode> <fault> <hold> [max]: each case its own clean ledger
  : > "$X/sitting.log"
  if [ "$2" = - ]; then allow=null; else allow="{\"thread\":\"$2\",\"mode\":\"$3\",\"text_sha256\":\"$SHA13\",\"max_calls\":${6:-1}}"; fi
  printf '{"step":"%s","real_room_cli":"%s","threads":{"T-A":"thr_syn_0101","T-B":"thr_syn_0102","T-C":"thr_syn_0103"},"allowed_tell":%s,"fault":"%s","hold_s":%s,"expires_ms":%s,"auth":"%s","allowance":"%s"}' \
    "$1" "$D/room-cli" "$allow" "$4" "$5" "$(( $(date +%s) * 1000 + 600000 ))" "a-$1" "$X/allow" > "$X/step.json"
}
tell() { "$X/room-cli" thread tell "$1" --mode "$2" --json -- "$3"; }

rc=0; tell thr_syn_0101 queue "$T13" >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_tells x2)" = 0 ] && ok "X2-1 no step file: refused (97), nothing reaches the fake" || fail "X2-1 rc=$rc"

step s2 T-A queue capture 0
out=$(tell thr_syn_0101 queue "$T13"); rc=$?
[ "$rc" = 0 ] && [ "$(fake_tells x2)" = 1 ] && echo "$out" | grep -q '"delivery": "sent"' \
  && ok "X2-2 capture: the approved tell reaches the fake once, its receipt passes through" || fail "X2-2 rc=$rc"
cap=$(ls "$X"/capture-s2-*.out 2>/dev/null | head -1)
[ -n "$cap" ] && grep -q '"delivery": "sent"' "$cap" && [ "$(stat -c %a "$cap" 2>/dev/null || stat -f %Lp "$cap")" = 600 ] \
  && ok "X2-2 capture: the receipt is kept (0600) for L4's structure" || fail "X2-2 capture file"
grep -q '"outcome": "called"' "$X/tell.log" && grep -q '"thread": "T-A"' "$X/tell.log" && grep -q "$SHA13" "$X/tell.log" \
  && ! grep -q "thr_syn_" "$X/tell.log" && ! grep -q "OpenWiz acceptance" "$X/tell.log" \
  && ok "X2-2 tell.log: label, mode and hash; never the id or the text" || fail "X2-2 tell.log"

rc=0; tell thr_syn_0101 queue "$T13" >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_tells x2)" = 1 ] && ok "X2-3 a second tell in the same step (a resend): refused and counted" || fail "X2-3 rc=$rc"

step s4 T-A queue capture 0 9
n0=$(fake_tells x2); bad=0
for args in "thr_syn_0102 queue" "thr_syn_0101 steer" "thr_syn_0001 queue"; do
  rc=0; tell $args "$T13" >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
done
rc=0; tell thr_syn_0101 queue "$T13 " >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
rc=0; "$X/room-cli" thread tell thr_syn_0101 --mode queue --json --file /tmp/x -- "$T13" >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
rc=0; "$X/room-cli" thread tell thr_syn_0101 --mode auto --json -- "$T13" >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
rc=0; "$X/room-cli" thread spawn --json >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
rc=0; "$X/room-cli" thread log thr_syn_0101 --json --limit 5 >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || bad=1
[ "$bad" = 0 ] && [ "$(fake_tells x2)" = "$n0" ] \
  && ok "X2-4 another thread, mode, text, flag (--file, auto), command or a non-OpenWiz read: each refused, nothing reaches the fake" \
  || fail "X2-4"
[ "$(grep -c '"outcome": "refused"' "$X/tell.log")" -ge 5 ] && ok "X2-4 each refused tell is counted" || fail "X2-4 counted"

step s5 - queue capture 0
out=$("$X/room-cli" thread show thr_syn_0101 --json) && echo "$out" | grep -q '"id": "thr_syn_0101"' \
  && grep -q '"kind": "thread show T-A --json"' "$X/reads.log" && ! grep -q thr_syn "$X/reads.log" \
  && ok "X2-5 an allowlisted read passes through, logged by kind with the label, never the id" || fail "X2-5"

step s6 T-A queue hold-before 3
n0=$(fake_tells x2)
python3 - "$X/room-cli" "$T13" <<'PY'
import subprocess, sys, time, os, signal
p = subprocess.Popen(["sh", "-c", 'exec 3>&-; "$0" thread tell thr_syn_0101 --mode queue --json -- "$1" >/dev/null 2>&1; true',
                      sys.argv[1], sys.argv[2]])
d = os.path.dirname(sys.argv[1])
while not os.path.exists(os.path.join(d, "holding-before")):
    time.sleep(0.05)
p.send_signal(signal.SIGKILL); p.wait()
time.sleep(4)
PY
[ "$(fake_tells x2)" = "$n0" ] && grep -q '"outcome": "aborted_parent_gone"' "$X/tell.log" \
  && ok "X2-6 hold-before, parent killed during the hold: aborted, nothing reaches the fake (F3b, F6)" || fail "X2-6"

rm -f "$X/holding-before"; step s7 T-A queue hold-before 1
rc=0; tell thr_syn_0101 queue "$T13" >/dev/null 2>&1 || rc=$?
[ "$rc" = 0 ] && [ "$(fake_tells x2)" = $((n0 + 1)) ] && grep -q '"outcome": "called_after_hold"' "$X/tell.log" \
  && ok "X2-7 hold-before, parent alive: called once after the hold" || fail "X2-7 rc=$rc"

step s8 T-A queue hold-after 2
t0=$(date +%s); out=$(tell thr_syn_0101 queue "$T13"); t1=$(date +%s)
[ -f "$X/answered-holding" ] && echo "$out" | grep -q delivery && [ $((t1 - t0)) -ge 2 ] \
  && ok "X2-8 hold-after: called, marker written, the receipt held back $((t1 - t0)) s (F2, F3a, F4, F5, F7)" || fail "X2-8"

step s9 T-A queue capture 0; n0=$(fake_tells x2)
echo '{"kind": "refused"}' >> "$X/sitting.log"
rc=0; tell thr_syn_0101 queue "$T13" >/dev/null 2>&1 || rc=$?
rm -f "$X/sitting.log"
rc2=0; tell thr_syn_0101 queue "$T13" >/dev/null 2>&1 || rc2=$?
[ "$rc" = 97 ] && [ "$rc2" = 97 ] && [ "$(fake_tells x2)" = "$n0" ] \
  && ok "X2-9 a tainted sitting ledger, or a missing one, admits no tell: refused (97), nothing reaches the fake (R13)" || fail "X2-9 rc=$rc rc2=$rc2"

fi

if only setup; then
# ---------------------------------------------------------------- X1
echo "== X1: its web requests are the composer's (apps/web on main)"
python3 - "$KIT" "$SOURCE_ROOT/apps/web/src/api.ts" "$SOURCE_ROOT/apps/web/src/composer.ts" <<'PY' && ok "op ids web-<32 hex>-q1/-s1 and the headers Accept, X-Requested-With, Content-Type, X-OpenWiz-Send, as in apps/web" || fail "composer shape"
import importlib.util, re, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
api, comp = open(sys.argv[2]).read(), open(sys.argv[3]).read()
assert re.fullmatch(r"web-[0-9a-f]{32}-q1", kit.web_op("queue")) and re.fullmatch(r"web-[0-9a-f]{32}-s1", kit.web_op("steer"))
assert "mode === 'queue' ? 'q' : 's'" in comp and "web-${" in comp
src = open(sys.argv[1]).read()
for h in ("Accept", "X-Requested-With", "Content-Type", "X-OpenWiz-Send"):
    assert re.search(r"['\"]?%s['\"]?\s*:" % re.escape(h), api), h
    assert '"%s"' % h in src, h
PY

echo "== X1: setup refuses what is not approved"
kitsetup ok-setup && ok "setup: a clean setup is ready, the PATH guard sees X2" || fail "setup"
check "setup: the PATH guard and X2's hash are reported" "r['setup']=='ready' and r['path_guard'].endswith('X2') and len(r['x2_sha256'])==64" "$WORK/ok-setup/setup.json"
D=$(mkworld bad-text); sed 's/reply with the word ok\./reply with the word OK./' "$TICKET/texts.tsv" > "$WORK/bad-text/texts.tsv"
rc=0; python3 "$KIT" setup --work "$WORK/bad-text/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" \
  --threads "$WORK/bad-text/threads.env" --texts "$WORK/bad-text/texts.tsv" --dry-run > "$WORK/bad-text.json" || rc=$?
check "a changed text: setup stops (exit $rc), naming no text" "'$rc'=='10' and 'not approved' in r['stopped']" "$WORK/bad-text.json"
D=$(mkworld bad-mode); chmod 644 "$WORK/bad-mode/threads.env"
rc=0; python3 "$KIT" setup --work "$WORK/bad-mode/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" \
  --threads "$WORK/bad-mode/threads.env" --dry-run > "$WORK/bad-mode.json" || rc=$?
check "a threads file others can read: setup stops (exit $rc)" "'$rc'=='10' and 'chmod 600' in r['stopped']" "$WORK/bad-mode.json"
D=$(mkworld in-repo)
rc=0; python3 "$KIT" setup --work "$TICKET/should-not-exist" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" \
  --threads "$WORK/in-repo/threads.env" --dry-run > "$WORK/in-repo.json" || rc=$?
check "a work directory inside a repository: setup stops (exit $rc)" "'$rc'=='10' and 'repository' in r['stopped']" "$WORK/in-repo.json"
[ ! -e "$TICKET/should-not-exist" ] || fail "in-repo: a directory was made"
D=$(mkworld bad-sha)
rc=0; python3 "$KIT" setup --work "$WORK/bad-sha/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" \
  --threads "$WORK/bad-sha/threads.env" --dry-run --expect-sha256 0000000000000000000000000000000000000000000000000000000000000000 \
  > "$WORK/bad-sha.json" || rc=$?
check "a binary whose sha256 is not the expected one: setup stops (exit $rc)" "'$rc'=='10' and 'sha256' in r['stopped']" "$WORK/bad-sha.json"

echo "== X1: the map, for Jake's eyes"
rc=0; python3 "$KIT" map --work "$WORK/ok-setup/w" > "$WORK/map.json" || rc=$?
check "map: T-A Local, T-B and T-C Cloud, idle, empty, visible; no title, no id" \
  "r['threads']['T-A']['where']=='Local' and r['threads']['T-B']['where']=='Cloud' and all(t['status']=='idle' and t['events']==0 and t['in_default_view'] for t in r['threads'].values()) and 'title' not in r['threads']['T-A']" "$WORK/map.json"
grep -q thr_syn "$WORK/map.json" && fail "map printed an id" || ok "map printed no id"
printf 'TA=thr_syn_0102\nTB=thr_syn_0101\nTC=thr_syn_0103\n' > "$WORK/ok-setup/threads.env"
rc=0; python3 "$KIT" map --work "$WORK/ok-setup/w" > "$WORK/map-swap.json" || rc=$?
check "map: T-A and T-B swapped (a Cloud thread as T-A): stops (exit $rc)" "'$rc'=='10' and 'T-A is Cloud' in r['stopped']" "$WORK/map-swap.json"
printf 'TA=thr_syn_0101\nTB=thr_syn_0102\nTC=thr_syn_0103\n' > "$WORK/ok-setup/threads.env"
rc=0; python3 "$KIT" recheck --work "$WORK/ok-setup/w" > "$WORK/recheck.json" || rc=$?
check "recheck (L-3): thread tell's help, structure only" "r['shows_double_dash'] is True and len(r['help_sha256'])==64" "$WORK/recheck.json"

fi

if only faults; then
echo "== X1: the planted faults stop the run"
kitsetup misroute; plant misroute misroute; kitrun misroute C1
check "a message landing in another test thread: not as expected (L1), the run stops after C1" \
  "r['outcome']=='not_as_expected' and 'M13 on T-A: 0, expected 1' in r['groups'][0]['landing'][0]['verdict'] and 'M13 on T-B: 1, expected 0' in r['groups'][0]['landing'][0]['verdict'] and len(r['groups'])==1" "$WORK/misroute.json"
kitsetup prefix; plant prefix prefix; kitrun prefix C1
check "the dash text arriving with '-- ' in front: not as expected (L11, L-3: stop on any surprise)" \
  "r['outcome']=='not_as_expected' and 'wrapped' in r['groups'][0]['landing'][0]['verdict'] and r['groups'][0]['landing'][0]['checked'][0]['wrapped']==[{'prefix_bytes':3,'suffix_bytes':0}]" "$WORK/prefix.json"
kitsetup touch; plant touch touch-sample; kitrun touch C1
check "a change outside the test threads during a group: not as expected (L1)" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['outside']['failures'].get('lastReadAt')==1" "$WORK/touch.json"
kitsetup refuse; plant refuse refuse-steer; kitrun refuse C8
check "a steer without steering refused, not queued as observed: not as expected (L3), nothing else run" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['steps'][1]['verdict'].startswith('not_as_expected') and r['groups'][0]['steps'][1]['got']['status']=='failed'" "$WORK/refuse.json"
kitsetup stuck; plant stuck busy-stuck; kitrun stuck C2
check "a test thread that never becomes idle: incomplete, the next send is never made" \
  "r['outcome']=='incomplete' and 'did not settle' in r['stopped'] and len(r['groups'][0]['steps'])==1 and r['groups'][0]['steps'][0]['got']['attempts']==1" "$WORK/stuck.json"

# A resend: openwiz behind a wrapper that calls room-cli a second time after it.
kitsetup resend
cat > "$WORK/resend/openwiz" <<SH
#!/bin/sh
"$OPENWIZ" "\$@"; rc=\$?
for last; do :; done
room-cli thread tell "\$2" --mode queue --json -- "\$last" >/dev/null 2>&1
exit \$rc
SH
chmod 700 "$WORK/resend/openwiz"
python3 - "$WORK/resend/w/kit.json" "$WORK/resend/openwiz" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c["openwiz"] = sys.argv[2]; json.dump(c, open(sys.argv[1], "w"))
PY
kitrun resend C1
check "a resend after the call: X2 refuses it, counts it, the run stops; the fake saw one tell" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['steps'][0]['got']['refused']==1 and 'resend' in r['groups'][0]['steps'][0]['verdict']" "$WORK/resend.json"
[ "$(fake_tells resend)" = 1 ] && ok "resend: the second call never reached the fake" || fail "resend reached the fake"

kitsetup noshim; rm "$WORK/noshim/w/x2/room-cli"; kitrun noshim C1
check "X2 missing (or not the reviewed shim): stops before any read or send (exit $RC)" "'$RC'=='10' and 'X2 is missing' in r['stopped']" "$WORK/noshim.json"
[ "$(fake_tells noshim)" = 0 ] && ok "noshim: nothing reached the fake" || fail "noshim reached the fake"

# A probe that would send (every header right): X2 allows no tell in the probe step, so it is refused and counted.
kitsetup probe-leak; kitswap probe-leak
rc=0; python3 - "$KIT" "$WORK/probe-leak/w" > "$WORK/probe-leak.json" 2>"$WORK/probe-leak.err" <<'PY' || rc=$?
import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
kit.PROBES = kit.PROBES + (("every header right (planted)", {}, 403),)
sys.exit(kit.main(["run", "--work", sys.argv[2], "--groups", "W7", "--settle", "0.5", "--late", "0.5",
                   "--idle-timeout", "30", "--busy-min", "1", "--poll", "0.3", "--min-judged", "3"]))
PY
kitunswap probe-leak
check "a probe that would send: X2 refuses it, it is counted, L9 not as expected" \
  "r['outcome']=='not_as_expected' and r['groups'][0]['steps'][0]['got']['attempts']==1" "$WORK/probe-leak.json"
[ "$(fake_tells probe-leak)" = 0 ] && ok "probe-leak: nothing reached the fake" || fail "probe-leak reached the fake"

fi

if only quiet; then
echo "== X1: Jake keeps working: what his activity can and cannot confuse"
kitsetup recent; plant recent touch-recent; plant recent appear; kitrun recent C1
check "Jake working in a recent session, and a new session appearing, during a group: reported, not judged; as expected" \
  "r['outcome']=='as_expected' and r['groups'][0]['outside']['not_judged_changed'].get('lastReadAt')==1 and r['groups'][0]['outside']['appeared_not_judged']==1 and r['groups'][0]['outside']['failures']=={}" "$WORK/recent.json"
check "the judged set is explicit: the rule, how many sessions are judged, and how many are not (recent or active, excluded, test)" \
  "r['judged']['rule'].startswith('quiet at the start and not updated in the 48') and r['judged']['sessions']>=3 and r['judged']['not_judged']['recent_or_active']>=3 and r['judged']['not_judged']['test_threads']==3" "$WORK/recent.json"
kitsetup floor; kitrun floor C1 --min-judged 50
check "fewer cold sessions to judge than the floor (Jake used nearly everything recently): stops before any send (exit $RC)" \
  "'$RC'=='10' and 'at least 50 are needed' in r['stopped']" "$WORK/floor.json"
[ "$(fake_tells floor)" = 0 ] && ok "floor: nothing reached the fake" || fail "floor reached the fake"
kitsetup stray
python3 - "$WORK/stray/w" "$WORK/stray/world/room-cli" <<'PY' &
import json, os, subprocess, sys, time
w = sys.argv[1]
log = os.path.join(w, "x2", "tell.log")
while not (os.path.exists(log) and '"C1-M13"' in open(log).read()
           and json.load(open(os.path.join(w, "x2", "step.json")))["step"] == "between-steps"):
    time.sleep(0.05)
subprocess.run([os.path.join(w, "x2", "room-cli"), "thread", "tell", "thr_syn_0001", "--mode", "queue", "--json", "--",
                "a send from the web page between steps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
kitrun stray C1
check "a send between steps (Jake's own composer, during the swap): X2 refuses it, nothing reaches a thread, and the run stops" \
  "r['outcome']=='not_as_expected' and 'outside the plan' in r['stopped'] and r['groups'][0]['outside']['tells_between_steps']==1" "$WORK/stray.json"
[ "$(fake_tells stray)" = 1 ] && ok "stray: only C1's own tell reached the fake" || fail "stray reached the fake"

# The leak scan: a planted id in the report prints nothing with it.
kitsetup leak
rc=0; python3 - "$KIT" "$WORK/leak/w" > "$WORK/leak.out" 2>&1 <<'PY' || rc=$?
import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
real = kit.publish
def planted(k, rep):
    rep["planted"] = "thr_syn_0101"
    return real(k, rep)
kit.publish = planted
sys.exit(kit.main(["run", "--work", sys.argv[2], "--groups", "C1", "--settle", "0.5", "--late", "0.5",
                   "--idle-timeout", "30", "--busy-min", "1", "--poll", "0.3", "--min-judged", "3"]))
PY
[ "$rc" = 10 ] && grep -q forbidden "$WORK/leak.out" && ! grep -q thr_syn_0101 "$WORK/leak.out" \
  && ok "a planted id in the report: nothing printed with it (exit 10)" || { fail "leak scan rc=$rc"; cat "$WORK/leak.out"; }
ls "$WORK/leak/w/run"/report-blocked-*.json >/dev/null 2>&1 \
  && ok "the blocked report is kept in the run directory only, so no evidence is lost" || fail "blocked report not kept"

fi

if only whole; then
echo "== X1: the whole plan on the fake world is as expected (the dry run's groups)"
kitsetup clean; kitrun clean C1,C2,C3,C4,C5,C6,C7,C8
check "C1 to C8: every step and every bracket as expected; no X2 refusal" \
  "r['outcome']=='as_expected' and len(r['groups'])==8 and all(s['verdict']=='as_expected' for g in r['groups'] for s in g['steps']) and all(g['outside']['verdict']=='as_expected' for g in r['groups'])" "$WORK/clean.json"
kitswap clean
check "the swap: the confirmed 0.0.2 stand-in stopped, X1's server up under the supervisor" "r['swap']=='up' and r['old_was_running'] is True" "$WORK/clean/swap.json"
kitrun clean-web W1,W2,W3,W4,W5,W6,W7,P1,P1b --work "$WORK/clean/w"
check "W1 to W7 and P1 (X1 also pressing for Jake): every step as expected; F4 to F7 uncertain, then resolved without a second call" \
  "r['outcome']=='as_expected' and len(r['groups'])==9 and all(s['verdict']=='as_expected' for g in r['groups'] for s in g['steps'])" "$WORK/clean-web.json"
python3 "$KIT" parity --work "$WORK/clean/w" > "$WORK/parity.json"
check "L10 parity: CLI and web give the same outcome class and record structure, per kind" \
  "all(v['verdict']=='as_expected' for v in r['parity'].values())" "$WORK/parity.json"
python3 "$KIT" receipts --work "$WORK/clean/w" > "$WORK/receipts.json"
check "L4 receipts: sent, queued (thread-busy) and steer queued (not reported) captured, each with exactly the observed keys; no value" \
  "r['outcome']=='as_expected' and r['receipts']['sent']['documented_keys'] and r['receipts']['queued:thread-busy']['documented_keys'] and r['receipts']['queued:not-reported']['documented_keys'] and 'rejection' not in r['receipts'] and r['receipts']['queued:thread-busy']['structure']['queuedMessage']['id']=='str'" "$WORK/receipts.json"
grep -qE 'qmsg_syn|00000000-0000-4000|thr_syn' "$WORK/receipts.json" && fail "a receipt value reached the receipts report" || ok "the receipts report holds no value"
RC=0; python3 "$KIT" l13 --work "$WORK/clean/w" --min-judged 3 -- --room-cli "$WORK/clean/world/room-cli" --openwiz "$OPENWIZ" \
  --run-dir "$WORK/clean/qc" --wait 3 > "$WORK/l13.json" || RC=$?
check "L13: the quick check passes judging the cold sessions and the test threads; the recent session is excluded by rule; page reads counted inside the window; no tell" \
  "r['l13']['verdict']=='as_expected' and r['l13']['judged']['excluded_as_recent_or_active']>=3 and r['l13']['judged']['sessions']>=6 and r['l13']['page_reads_in_window'].get('thread list --json',0)>0 and r['l13']['attempts']==0" "$WORK/l13.json"
kitunswap clean
check "the swap back: 0.0.2's stand-in restored" "r['swap']=='restored' and r['outcome']=='as_expected'" "$WORK/clean/unswap.json"
if grep -lE 'thr_syn_|op-acc-|web-[0-9a-f]{32}|openwiz\.invalid' "$WORK/clean.json" "$WORK/clean-web.json" "$WORK/parity.json"; then
  fail "an id, op id or the host name reached a report"; else ok "the reports hold no id, op id or host name"; fi

fi

if only live; then
echo "== X1: the live path (no --dry-run): Jake's phone steps answered through the runner (jake-sim.py plays both)"
D=$(mkworld live); mkdir -p "$WORK/live/old"
ACCESS_PORT=$(( ${KIT_PORT:-17370} + 20 ))
python3 -c "
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):  # a stand-in for Access: every request is sent to a login
    def do_POST(self):
        self.send_response(302); self.send_header('Location', '/login'); self.send_header('Content-Length', '0'); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()" "$ACCESS_PORT" &
ACCESS=$!; own $ACCESS
python3 "$KIT" setup --work "$WORK/live/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --server "$SERVER" \
  --threads "$WORK/live/threads.env" --port "${KIT_PORT:-17370}" --host openwiz.invalid \
  --access-url "http://127.0.0.1:$ACCESS_PORT" --restore-cmd "$(oldcmd "${KIT_PORT:-17370}")" \
  --restore-log "$WORK/live/old/server.log" --restore-sha256 "$SERVER_SHA" --allowance "$WORK/live/allowance" > /dev/null
kitswap live
RC=0; python3 "$SCRIPTS/test/jake-sim.py" "$KIT" "$WORK/live/w" W3,W7,P1,P1b --settle 0.5 --late 0.5 \
  --idle-timeout 30 --busy-min 1 --poll 0.3 --press-timeout 30 --min-judged 3 > "$WORK/live.json" || RC=$?
kitunswap live
kill $ACCESS 2>/dev/null || true
check "live path: W3, W7 (the unauthenticated public probe gets Access's 302; the cross-site page skipped) and P1 (three phone presses, Airplane Mode, Check again), as expected" \
  "r['outcome']=='as_expected' and len(r['groups'])==4 and all(s['verdict']=='as_expected' for g in r['groups'] for s in g['steps']) and r['groups'][1]['steps'][0]['got']['probes']['public, no login']==302 and r['groups'][3]['steps'][0]['fault_produced'] is True" "$WORK/live.json"
grep -q "exactly:" "$WORK/live/prompts.log" && grep -q "turn on Airplane Mode" "$WORK/live/prompts.log" && grep -q "ANSWER P1-M06: What does the composer show" "$WORK/live/prompts.log" \
  && grep -q "cross-site-probe.html" "$WORK/live/prompts.log" && grep -q "starts a turn and may wake" "$WORK/live/prompts.log" \
  && ok "the phone prompts name the device, the text exactly, the effect line to read, Airplane Mode, and ask for answers through the runner" || fail "prompts"

fi

[ "$FAILED" = 0 ] && echo "== all kit tests ok (synthetic; not a live result)" || { echo "== kit tests FAILED"; exit 1; }
