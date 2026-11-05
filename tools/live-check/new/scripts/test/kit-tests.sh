#!/bin/sh
# Tests X2 (x2-shim.py) and X1 (new-kit.py) on the repository's fake room-cli, behind
# world-stub.py. SYNTHETIC ONLY; NOT A LIVE RESULT. Nothing is created, sent or
# uploaded anywhere: every write goes to the fake. Run from the repository root:
#   KIT_SOURCE_ROOT=/absolute/release-checkout KIT_TARGET=/tmp/kit13-release-target \
#     sh private/evidence/openwiz-0.0.4/ticket-13/scripts/test/kit-tests.sh
# About 8 minutes. KIT_KEEP_GOING=1 runs every case after a failure (for a red run).
# KIT_ONLY=guards,pc,x2,x1,plan,scope,nopn,faults,live,sol,r168 runs those sections only.
only() { [ -z "${KIT_ONLY:-}" ] || echo ",$KIT_ONLY," | grep -q ",$1,"; }
if only guards; then
  python3 "$(dirname "$0")/source-guard-tests.py" || exit 1
  [ "${KIT_ONLY:-}" != guards ] || exit 0
fi
. "$(dirname "$0")/lib.sh"

check "the 6 synthetic files are made with their approved SHA-256" "r['all_approved'] and len(r['files'])==6" "$WORK/files.json"

# ---------------------------------------------------------------- PC receipt shapes (#10, #571/#583)
if only pc; then
kitsetup pc-receipts
python3 - "$KIT" "$WORK/pc-receipts/w" "$FIX" <<'PYPC' && ok "PC receipts: observed sent, busy queue (agent or user), steer queue; old and drifted shapes fail closed; every capture counts" || fail "PC receipts"
import copy, json, os, subprocess, sys
kit, work, fixtures = sys.argv[1:]
x2 = os.path.join(work, "x2")
send = os.path.join(fixtures, "room-cli-0.43.1", "send")
def load(name):
    return json.load(open(os.path.join(send, name)))
def capture(doc, name="a"):
    with open(os.path.join(x2, "capture-tell-%s-1.out" % name), "w") as f:
        json.dump(doc, f)
def report(doc, good):
    capture(doc)
    kind = "tell:" + doc["delivery"]
    p = subprocess.run([sys.executable, kit, "receipts", "--work", work, "--require", kind],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    r = json.loads(p.stdout)
    assert p.returncode == (0 if good else 10), (kind, good, p.returncode, r)
    assert (r["drift"] == []) == good, r
sent = load("tell-sent-observed.json")
queued = load("tell-queued-observed.json")
steer = load("tell-steer-queued-observed.json")
report(sent, True)
sent_steer = copy.deepcopy(sent); sent_steer["mode"] = "steer"; report(sent_steer, True)
report(queued, True)
user = copy.deepcopy(queued)
user["queuedMessage"].update(initiator="user", senderThreadId=None)
report(user, True)
report(steer, True)
report({"delivery": "sent"}, False)
report({"delivery": "queued", "queuedMessage": {}}, False)
for field in ("threadId", "ok", "mode"):
    bad = copy.deepcopy(sent); del bad[field]; report(bad, False)
    bad = copy.deepcopy(sent); bad[field] = []; report(bad, False)
bad = copy.deepcopy(sent); bad["extra"] = "synthetic"; report(bad, False)
bad = copy.deepcopy(sent); bad["mode"] = "other"; report(bad, False)
for doc in (sent, queued, user, steer):
    for mode in ("queue:user", "queue:agent", "", "QUEUE", "other"):
        bad = copy.deepcopy(doc); bad["mode"] = mode; report(bad, False)
for field in ("hardQueue", "waitingOn", "senderThreadId"):
    bad = copy.deepcopy(queued); del bad["queuedMessage"][field]; report(bad, False)
    bad = copy.deepcopy(queued); bad["queuedMessage"][field] = 1; report(bad, False)
bad = copy.deepcopy(queued); bad["queuedMessage"]["extra"] = True; report(bad, False)
bad = copy.deepcopy(steer); bad["queuedMessage"]["hardQueue"] = False; report(bad, False)
# A good capture must never hide another capture's drift, in either order.
for a, b in ((sent, {"delivery": "sent"}), ({"delivery": "sent"}, sent)):
    capture(a); capture(b, "z")
    p = subprocess.run([sys.executable, kit, "receipts", "--work", work, "--require", "tell:sent"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    r = json.loads(p.stdout)
    assert p.returncode == 10 and r["receipts"]["tell:sent"]["count"] == 2 and "tell:sent" in r["drift"], r
PYPC
fi

# ---------------------------------------------------------------- X2, alone
if only x2; then
echo "== X2: the call-counting shim, called directly"
D=$(mkworld x2)
X="$WORK/x2/x"; mkdir -p "$X"; cp "$X2SRC" "$X/room-cli"; chmod 700 "$X/room-cli"
ST="$WORK/x2/st/attachments"; mkdir -p "$ST/att-x1" "$ST/att-x2"
cp "$FILES/syn-small.png" "$ST/att-x1/syn-small.png"; cp "$FILES/syn-notes.txt" "$ST/att-x2/syn-notes.txt"
T=$(sed -n 's/^N4\tP-A\t//p' "$TICKET/texts.tsv")
SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$T")
F1=c43c8b8aeeb4288c7a38e12c1220121e473c7903af32771f28982fbf2a99feb0
F4=8273ca0844b7468654f3eb840aba94785f5d0e08f9c83332cac6820a8ba7b673
RID=ow1-0123456789abcdef0123456789abcdef01234567
# x2step <name> <allowed write JSON or null> [fault] [hold s] [ttl ms]: the step's write is
# authorised under its own name; the ledger (made once, a budget of 99) is X2's, as setup makes it,
# and names the approval file (#168's R8: made once, outside the sitting, a total of 99 each).
# X2_DIR=<dir> X2_SITTING=<n>: another sitting's X2, under the same approval.
APPROVAL="$WORK/x2/approval.json"
x2step() {
  python3 - "${X2_DIR:-$X}" "$D/room-cli" "$1" "$2" "${3:-capture}" "${4:-0}" "${5:-600000}" "$APPROVAL" "${X2_SITTING:-1}" <<'PY'
import json, os, sys, time
x, real, name, allow, fault, hold, ttl, appr, sitting = sys.argv[1:]
if not os.path.exists(appr):
    open(appr, "w").write(json.dumps({"schema": "kit13.approval.v1", "approval": "L-8", "total": {"spawn": 99, "tell": 99},
                                      "charges": [], "sittings": [], "amendments": []}))
led = os.path.join(x, "ledger.json")
if not os.path.exists(led):
    open(led, "w").write(json.dumps({"budget": {"spawn": 99, "tell": 99}, "used": {"spawn": 0, "tell": 0}, "auth": {}, "generation": 1,
                                     "approval": appr, "sitting": int(sitting)}))
if os.environ.get("X2_KEEP_TAINT") is None:  # each X2-alone scenario is its own sitting: no taint carried over
    d = json.load(open(led)); d.update(tainted=False, refusals=0, refused=[]); open(led, "w").write(json.dumps(d))
allow = json.loads(allow)
if isinstance(allow, dict):
    allow.setdefault("auth", name)
step = {"step": name, "real_room_cli": real, "targets": {"P-A": "prj_syn_0301", "T-A": "thr_syn_0101", "T-B": "thr_syn_0102"},
        "allowed_write": allow, "fault": fault, "hold_s": float(hold), "expires_ms": time.time_ns() // 1000000 + int(ttl),
        "generation": 1}
open(x + "/step.json", "w").write(json.dumps(step))
PY
}
spawn_allow() { echo "{\"kind\":\"spawn\",\"target\":\"P-A\",\"provider\":\"codex\",\"model\":\"syn-codex-model-01\",\"effort\":\"low\",\"text_sha256\":\"$SHA\",\"attachments\":${1:-[]},\"max_calls\":1}"; }
spawn() { # spawn <project> <provider> <model> <effort> [attachment pairs...]: the prompt is $T
  p=$1; h=$2; m=$3; e=$4; shift 4
  "${X2_DIR:-$X}/room-cli" thread spawn --project "$p" --machine cloud --provider "$h" --model "$m" --reasoning-level "$e" \
    --request-id "$RID" --json "$@" --prompt "$T"
}
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = 0 ] && ok "X2-1 no step file: refused (97), nothing reaches the fake" || fail "X2-1 rc=$rc"

x2step s2 "$(spawn_allow)"
out=$(spawn prj_syn_0301 codex syn-codex-model-01 low); rc=$?
[ "$rc" = 0 ] && [ "$(fake_writes x2 spawn)" = 1 ] && echo "$out" | grep -q '"projectId": "prj_syn_0301"' \
  && ok "X2-2 the step's one spawn reaches the fake once, its receipt passes through" || fail "X2-2 rc=$rc"
cap=$(ls "$X"/capture-spawn-s2-*.out 2>/dev/null | head -1)
[ -n "$cap" ] && grep -q '"projectId"' "$cap" && [ "$(stat -c %a "$cap")" = 600 ] \
  && ok "X2-2 the receipt is kept (0600) for S4's structure" || fail "X2-2 capture file"
grep -q '"outcome": "called"' "$X/writes.log" && grep -q '"target": "P-A"' "$X/writes.log" && grep -q "$SHA" "$X/writes.log" \
  && ! grep -qE "prj_syn_|thr_syn_|syn-codex-model|OpenWiz acceptance|/tmp/" "$X/writes.log" \
  && ok "X2-2 writes.log: label, kind and hashes; never an id, the text, a model or a path" || fail "X2-2 writes.log"
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = 1 ] && ok "X2-3 a second spawn in the same step (a redispatch): refused and counted" || fail "X2-3 rc=$rc"

x2step s4 "$(spawn_allow | sed 's/"max_calls":1/"max_calls":99/')"
n0=$(fake_writes x2 spawn); bad=0; fails=""
# try <call...>: the call must be refused (97). Each try is a fresh sitting (TRY_STEP, TRY_ALLOW), so
# the guard under test refuses it, never the taint an earlier try left (#168's R6, final round).
TRY_STEP=s4; TRY_ALLOW=$(spawn_allow | sed 's/"max_calls":1/"max_calls":99/')
try() { x2step "$TRY_STEP" "$TRY_ALLOW"; rc=0; "$@" >/dev/null 2>&1 || rc=$?; [ "$rc" = 97 ] || { bad=1; fails="$fails [$*]"; }; }
try spawn prj_syn_0001 codex syn-codex-model-01 low
try spawn prj_syn_0301 claude-code syn-codex-model-01 low
try spawn prj_syn_0301 codex syn-codex-model-02 low
try spawn prj_syn_0301 codex syn-codex-model-01 high
try spawn prj_syn_0301 codex syn-codex-model-01 low --image "$ST/att-x1/syn-small.png"
try "$X/room-cli" thread spawn --project prj_syn_0301 --machine local --provider codex --model syn-codex-model-01 --reasoning-level low --request-id "$RID" --json --prompt "$T"
try "$X/room-cli" thread spawn --project prj_syn_0301 --machine cloud --provider codex --model syn-codex-model-01 --reasoning-level low --request-id "$RID" --json --parent-self --prompt "$T"
try "$X/room-cli" thread spawn --project prj_syn_0301 --machine cloud --provider codex --model syn-codex-model-01 --reasoning-level low --request-id "$RID" --json --prompt "$T "
try "$X/room-cli" thread tell thr_syn_0102 --mode queue --json -- "$T"
try "$X/room-cli" thread log thr_syn_0102 --json --limit 5
try "$X/room-cli" project attachment upload --json
[ "$bad" = 0 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] \
  && ok "X2-4 another project, harness, model, effort, text or attachment, a local machine, a flag, a tell, a log read or an upload: each refused, nothing reaches the fake" \
  || fail "X2-4$fails"
[ "$(grep -c '"outcome": "refused"' "$X/writes.log")" -ge 9 ] && ok "X2-4 each refused write is counted" || fail "X2-4 counted"

tell_allow() { echo "{\"kind\":\"tell\",\"target\":\"T-B\",\"mode\":\"queue\",\"text_sha256\":\"$SHA\",\"attachments\":[{\"flag\":\"--file\",\"sha256\":\"$F4\",\"size\":70},{\"flag\":\"--image\",\"sha256\":\"$F1\",\"size\":133}],\"max_calls\":${1:-1}}"; }
x2step s5 "$(tell_allow 9)"
n0=$(fake_writes x2 tell); bad=0; fails=""; TRY_STEP=s5; TRY_ALLOW=$(tell_allow 9)
try "$X/room-cli" thread tell thr_syn_0102 --mode queue --json --image "$ST/att-x1/syn-small.png" --file "$ST/att-x2/syn-notes.txt" -- "$T"
try "$X/room-cli" thread tell thr_syn_0102 --mode queue --json --file "$ST/att-x2/syn-notes.txt" -- "$T"
try "$X/room-cli" thread tell thr_syn_0101 --mode queue --json --file "$ST/att-x2/syn-notes.txt" --image "$ST/att-x1/syn-small.png" -- "$T"
try "$X/room-cli" thread tell thr_syn_0102 --mode steer --json --file "$ST/att-x2/syn-notes.txt" --image "$ST/att-x1/syn-small.png" -- "$T"
cp "$ST/att-x1/syn-small.png" "$WORK/x2/keep.png"; printf 'x' >> "$ST/att-x1/syn-small.png"
try "$X/room-cli" thread tell thr_syn_0102 --mode queue --json --file "$ST/att-x2/syn-notes.txt" --image "$ST/att-x1/syn-small.png" -- "$T"
cp "$WORK/x2/keep.png" "$ST/att-x1/syn-small.png"
[ "$bad" = 0 ] && [ "$(fake_writes x2 tell)" = "$n0" ] \
  && ok "X2-5 attachments: another order, one missing, another thread, Steer, or other bytes at the path: each refused" || fail "X2-5 refusals$fails"
x2step s5b "$(tell_allow)"  # a fresh sitting: those refusals tainted the one before (#168's R6, final round)
rc=0; "$X/room-cli" thread tell thr_syn_0102 --mode queue --json --file "$ST/att-x2/syn-notes.txt" --image "$ST/att-x1/syn-small.png" -- "$T" >/dev/null 2>&1 || rc=$?
[ "$rc" = 0 ] && [ "$(fake_writes x2 tell)" = $((n0 + 1)) ] \
  && ok "X2-5 the step's tell with its exact attachments (files first, then images) reaches the fake once" || fail "X2-5 rc=$rc"

x2step s6 "$(spawn_allow)" hold-before 3
n0=$(fake_writes x2 spawn)
python3 - "$X/room-cli" "$T" "$RID" <<'PY'
import subprocess, sys, time, os, signal
x, t, rid = sys.argv[1:]
p = subprocess.Popen(["sh", "-c", '"$0" thread spawn --project prj_syn_0301 --machine cloud --provider codex --model syn-codex-model-01 --reasoning-level low --request-id "$2" --json --prompt "$1" >/dev/null 2>&1; true', x, t, rid])
d = os.path.dirname(x)
end = time.monotonic() + 15  # bounded: a broken X2 that never holds must fail this check, never hang it
while not os.path.exists(os.path.join(d, "holding-before")) and time.monotonic() < end:
    time.sleep(0.05)
p.send_signal(signal.SIGKILL); p.wait()
time.sleep(4)
PY
[ "$(fake_writes x2 spawn)" = "$n0" ] && grep -q '"outcome": "aborted_parent_gone"' "$X/writes.log" \
  && ok "X2-6 hold-before, parent killed during the hold: aborted, nothing reaches the fake (the server killed before the call)" || fail "X2-6"

x2step s7 "$(spawn_allow)" hold-after 2
t0=$(date +%s); out=$(spawn prj_syn_0301 codex syn-codex-model-01 low 2>/dev/null); t1=$(date +%s)
[ -f "$X/answered-holding" ] && echo "$out" | grep -q projectId && [ $((t1 - t0)) -ge 2 ] \
  && ok "X2-7 hold-after: called, marker written, the receipt held back $((t1 - t0)) s (the CLI killed mid-create)" || fail "X2-7"

x2step s8 "$(spawn_allow)" capture 0 -1000
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && tail -1 "$X/writes.log" | grep -q "expired" && ok "X2-8 an expired step: refused" || fail "X2-8 rc=$rc"

python3 - "$X/ledger.json" <<'PY' || true
import json, sys
led = json.load(open(sys.argv[1])); led["budget"]["spawn"] = led["used"]["spawn"]; json.dump(led, open(sys.argv[1], "w"))
PY
x2step s10 "$(spawn_allow)"
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && tail -1 "$X/writes.log" | grep -q "budget" && ok "X2-10 the sitting's create budget used up: refused by X2 itself, whatever the step allows" || fail "X2-10 rc=$rc"
mv "$X/ledger.json" "$WORK/x2/ledger.keep"; x2step s11 "$(spawn_allow)"; rm -f "$X/ledger.json"
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && tail -1 "$X/writes.log" | grep -q "ledger" && ok "X2-11 no ledger: every write refused" || fail "X2-11 rc=$rc"
mv "$WORK/x2/ledger.keep" "$X/ledger.json"

# #168's R2, round 2: after a hold, the write is judged again under the lock, on everything:
# expiry and the payload, as at the first admission. Its reservation is kept, and given back
# only on an abort before room-cli (zero calls, proven).
held_spawn() { # held_spawn <python action while X2 holds>: one spawn through X2; prints X2's exit code
  rm -f "$X/holding-before"
  python3 - "$X" "$T" "$RID" "$1" <<'PY'
import fcntl, os, subprocess, sys, time
x, t, rid, action = sys.argv[1:]
p = subprocess.Popen([os.path.join(x, "room-cli"), "thread", "spawn", "--project", "prj_syn_0301", "--machine", "cloud",
                      "--provider", "codex", "--model", "syn-codex-model-01", "--reasoning-level", "low", "--request-id", rid,
                      "--json", "--prompt", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
end = time.monotonic() + 15
while not os.path.exists(os.path.join(x, "holding-before")) and time.monotonic() < end:
    time.sleep(0.05)
if action == "lock":  # take X2's lock before the hold ends, and keep it past the expiry
    lock = open(os.path.join(x, "writes.lock"), "a"); fcntl.flock(lock, fcntl.LOCK_EX)
    time.sleep(3.5); fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
print(p.wait(30))
PY
}
calls_of() { python3 -c "import json,sys; print((json.load(open(sys.argv[1]))['auth'].get(sys.argv[2]) or {}).get('calls', 0))" "$X/ledger.json" "$1"; }
python3 - "$X/ledger.json" <<'PY' || true
import json, sys  # X2-10 left the create budget used up: these checks need room in it
led = json.load(open(sys.argv[1])); led["budget"]["spawn"] = led["used"]["spawn"] + 10; json.dump(led, open(sys.argv[1], "w"))
PY
n0=$(fake_writes x2 spawn)
x2step s12 "$(spawn_allow)" hold-before 3 1000   # the step expires 1 s in; the hold lasts 3 s
rc=$(held_spawn none)
[ "$rc" = 98 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q '"outcome": "aborted_expired"' && [ "$(calls_of s12)" = 0 ] \
  && ok "X2-12 the step expires during the hold: aborted before room-cli, nothing reaches the fake, the reservation given back" || fail "X2-12 rc=$rc calls=$(calls_of s12)"
x2step s13 "$(spawn_allow)" hold-before 1 3000   # it expires 3 s in; the hold ends at 1 s, then X2 waits for its lock
rc=$(held_spawn lock)
[ "$rc" = 98 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q '"outcome": "aborted_expired"' && [ "$(calls_of s13)" = 0 ] \
  && ok "X2-13 the step expires while X2 waits for its second lock: aborted, nothing reaches the fake, the reservation given back" || fail "X2-13 rc=$rc calls=$(calls_of s13)"
x2step s14 "$(tell_allow)" hold-before 2
n1=$(fake_writes x2 tell); rm -f "$X/holding-before"; cp "$ST/att-x1/syn-small.png" "$WORK/x2/keep14.png"
( rc=0; "$X/room-cli" thread tell thr_syn_0102 --mode queue --json --file "$ST/att-x2/syn-notes.txt" --image "$ST/att-x1/syn-small.png" -- "$T" > /dev/null 2>&1 || rc=$?
  echo "$rc" > "$WORK/x2/rc14" ) &   # set -e holds in the subshell too: the exit code is caught, never fatal
i=0; until [ -e "$X/holding-before" ] || [ "$i" -ge 300 ]; do sleep 0.05; i=$((i + 1)); done
printf 'x' >> "$ST/att-x1/syn-small.png"; wait
cp "$WORK/x2/keep14.png" "$ST/att-x1/syn-small.png"
[ "$(cat "$WORK/x2/rc14")" = 98 ] && [ "$(fake_writes x2 tell)" = "$n1" ] && tail -1 "$X/writes.log" | grep -q '"outcome": "aborted_changed"' \
  && ok "X2-14 an attached file changes during the hold: aborted before room-cli, nothing reaches the fake" || fail "X2-14 rc=$(cat "$WORK/x2/rc14")"

# #168's R6, final round: any refusal taints the whole sitting, in the ledger, under the lock.
x2step s15 "$(spawn_allow)"
rc=0; "$X/room-cli" project attachment upload --json >/dev/null 2>&1 || rc=$?
python3 - "$X/ledger.json" "$rc" <<'PY' && ok "X2-15 a refused call of any kind taints the sitting's ledger, naming the refusal (never a value)" || fail "X2-15"
import json, sys
led = json.load(open(sys.argv[1]))
assert sys.argv[2] == "97" and led.get("tainted") is True and led.get("refusals") == 1, led
r = led["refused"][0]
assert r["kind"] == "other" and "allowlist" in r["why"] and r["step"] == "s15", r
PY
n0=$(fake_writes x2 spawn)
X2_KEEP_TAINT=1 x2step s16 "$(spawn_allow)"
rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q "tainted" \
  && ok "X2-16 in a tainted sitting X2 admits no write, even one its step allows" || fail "X2-16 rc=$rc"

# #168's R6, after the final round (Jake's (a)): a write X2 already admitted and holding before
# its call is judged again after the hold on the ledger too: if the sitting was tainted in the
# meantime, or its ledger can't be read, it is aborted before room-cli (zero calls, proven), its
# reservation goes back, and the taint stays.
held_write() { # held_write <spawn|tell> <taint|garble|kill|disarm>: one held write through X2; prints its exit code
  rm -f "$X/holding-before"
  python3 - "$X" "$T" "$RID" "$ST" "$1" "$2" <<'PY'
import json, os, signal, subprocess, sys, time
x, t, rid, st, kind, action = sys.argv[1:]
shim = os.path.join(x, "room-cli")
if kind == "spawn":
    argv = [shim, "thread", "spawn", "--project", "prj_syn_0301", "--machine", "cloud", "--provider", "codex", "--model",
            "syn-codex-model-01", "--reasoning-level", "low", "--request-id", rid, "--json", "--prompt", t]
else:
    argv = [shim, "thread", "tell", "thr_syn_0102", "--mode", "queue", "--json", "--file", st + "/att-x2/syn-notes.txt",
            "--image", st + "/att-x1/syn-small.png", "--", t]
p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
end = time.monotonic() + 15  # bounded: an X2 that never holds fails the check, never hangs it
while not os.path.exists(os.path.join(x, "holding-before")) and time.monotonic() < end:
    time.sleep(0.05)
led = os.path.join(x, "ledger.json")
if action == "taint":  # another call, refused while the write holds: the sitting is tainted
    r = subprocess.run([shim, "project", "attachment", "upload", "--json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert r.returncode == 97, r.returncode
elif action == "garble":  # the ledger can't be read when the hold ends
    keep = open(led).read()
    open(led + ".keep", "w").write(keep)
    open(led, "w").write("{not json")
elif action == "kill":  # X2 itself killed during its hold: zero calls, but nothing proves it
    os.kill(p.pid, signal.SIGKILL)
elif action == "disarm":  # X1 disarms during the hold (a new generation): zero calls, proven
    sp = os.path.join(x, "step.json")
    step = json.load(open(sp))
    step.update(generation=int(step.get("generation", 0)) + 1, allowed_write=None)
    open(sp, "w").write(json.dumps(step))
rc = p.wait(30)
if action == "garble":
    os.replace(led + ".keep", led)
print(rc)
PY
}
outcomes_of() { python3 -c "import json,sys; print(','.join(json.loads(l)['outcome'] for l in open(sys.argv[1]) if json.loads(l).get('step')==sys.argv[2]))" "$X/writes.log" "$1"; }
charges_of() { python3 -c "import json,sys; print(','.join(c.get('state','?') for c in json.load(open(sys.argv[1])).get('charges',[]) if c.get('auth')==sys.argv[2]) or 'none')" "$APPROVAL" "$1"; }
tainted_now() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('tainted') is True)" "$X/ledger.json"; }
n0=$(fake_writes x2 spawn)
x2step s17 "$(spawn_allow)" hold-before 2
rc=$(held_write spawn taint)
[ "$rc" = 98 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && [ "$(outcomes_of s17)" = "holding,aborted_tainted" ] && [ "$(calls_of s17)" = 0 ] \
  && [ "$(charges_of s17)" = released ] && [ "$(tainted_now)" = True ] \
  && ok "X2-17 a spawn holding when another call taints the sitting: aborted after the hold, nothing reaches the fake, its reservation back, the taint kept" \
  || fail "X2-17 rc=$rc outcomes=$(outcomes_of s17) calls=$(calls_of s17) charges=$(charges_of s17) tainted=$(tainted_now)"
n1=$(fake_writes x2 tell)
x2step s18 "$(tell_allow)" hold-before 2
rc=$(held_write tell taint)
[ "$rc" = 98 ] && [ "$(fake_writes x2 tell)" = "$n1" ] && [ "$(outcomes_of s18)" = "holding,aborted_tainted" ] && [ "$(calls_of s18)" = 0 ] \
  && [ "$(charges_of s18)" = released ] && [ "$(tainted_now)" = True ] \
  && ok "X2-18 a tell (with its attachments) holding when another call taints the sitting: aborted after the hold, nothing reaches the fake, its reservation back, the taint kept" \
  || fail "X2-18 rc=$rc outcomes=$(outcomes_of s18) calls=$(calls_of s18) charges=$(charges_of s18) tainted=$(tainted_now)"
x2step s19 "$(spawn_allow)" hold-before 2
n0=$(fake_writes x2 spawn); rc=$(held_write spawn garble)
[ "$rc" = 98 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && [ "$(outcomes_of s19)" = "holding,aborted_no_ledger" ] && [ "$(charges_of s19)" = released ] \
  && ok "X2-19 a spawn holding when the ledger can't be read: aborted after the hold, nothing reaches the fake, its charge on the approval released" \
  || fail "X2-19 rc=$rc outcomes=$(outcomes_of s19) charges=$(charges_of s19)"

# #168's R8: L-8's allowance spans every sitting under the approval, in its own file outside
# the sitting. Two sittings' X2s, each with its own ledger (and room in its own budget), one approval.
Y="$WORK/x2/y"; mkdir -p "$Y"; cp "$X2SRC" "$Y/room-cli"; chmod 700 "$Y/room-cli"
python3 - "$APPROVAL" <<'PY' || true
import json, sys  # one create left under the approval: what X2 charged so far, plus one
a = json.load(open(sys.argv[1]))
a["total"]["spawn"] = 1 + sum(1 for c in a["charges"] if c.get("kind") == "spawn" and c.get("state") != "released")
json.dump(a, open(sys.argv[1], "w"))
PY
X2_DIR="$Y" X2_SITTING=2 x2step s20 "$(spawn_allow)"
n0=$(fake_writes x2 spawn); rc=0; X2_DIR="$Y" spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
x2step s20b "$(spawn_allow)"
rc2=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc2=$?
[ "$rc" = 0 ] && [ "$rc2" = 97 ] && [ "$(fake_writes x2 spawn)" = $((n0 + 1)) ] && tail -1 "$X/writes.log" | grep -q "approval" \
  && ok "X2-20 one create left under the approval: sitting 2's spawn passes, then sitting 1's is refused by X2, though its own budget has room" \
  || fail "X2-20 rc=$rc rc2=$rc2 spawns=$(fake_writes x2 spawn)"
python3 - "$APPROVAL" <<'PY' || true
import json, sys  # room again (as if Jake amended the total): only the step's own record can refuse it now
a = json.load(open(sys.argv[1])); a["total"]["spawn"] = 99; json.dump(a, open(sys.argv[1], "w"))
PY
x2step s20 "$(spawn_allow)"
n0=$(fake_writes x2 spawn); rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q "under this approval" \
  && ok "X2-20 a step's write made in sitting 2 is refused in sitting 1 under the same approval: never repeated" || fail "X2-20 repeat rc=$rc"
# X2-21 on its own three steps: X2 killed during its hold; a call made; a hold aborted by a disarm.
n0=$(fake_writes x2 spawn)
x2step s21 "$(spawn_allow)" hold-before 3
rc=$(held_write spawn kill)
x2step s21c "$(spawn_allow)"
spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || true
x2step s21d "$(spawn_allow)" hold-before 2
rc2=$(held_write spawn disarm)
[ "$(fake_writes x2 spawn)" = $((n0 + 1)) ] && [ "$rc2" = 98 ] && [ "$(charges_of s21)" = reserved ] && [ "$(charges_of s21c)" = dispatched ] \
  && [ "$(charges_of s21d)" = released ] \
  && ok "X2-21 X2 killed during its hold: its charge stays (nothing proves zero calls); a call made stays charged; only a proven zero-call abort is released" \
  || fail "X2-21 s21=$(charges_of s21) s21c=$(charges_of s21c) s21d=$(charges_of s21d) rc2=$rc2 spawns=$(fake_writes x2 spawn)"
python3 "$KIT" approval show --approval "$APPROVAL" > "$WORK/x2/show.json" || true
check "X2-21 the approval's report counts the uncertain charge as charged, and what's left is the total less every charge" \
  "r['outcome']=='as_expected' and r['approval']['uncertain']['creates']==1 and r['approval']['remaining']['creates']==99-r['approval']['charged']['creates']" "$WORK/x2/show.json"
python3 - "$APPROVAL" <<'PY' || true
import json, sys  # the total set to exactly the charges, the uncertain one included: none left
a = json.load(open(sys.argv[1]))
a["total"]["spawn"] = sum(1 for c in a["charges"] if c.get("kind") == "spawn" and c.get("state") != "released")
json.dump(a, open(sys.argv[1], "w"))
PY
x2step s21b "$(spawn_allow)"
n0=$(fake_writes x2 spawn); rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q "allowance" \
  && ok "X2-21 the uncertain charge counts against the allowance: with it none is left, and X2 refuses the next spawn" || fail "X2-21 uncertain counted rc=$rc"
python3 - "$APPROVAL" <<'PY' || true
import json, sys
a = json.load(open(sys.argv[1])); a["total"]["spawn"] = 99; json.dump(a, open(sys.argv[1], "w"))
PY
python3 - "$X/ledger.json" <<'PY' || true
import json, sys
led = json.load(open(sys.argv[1])); led["approval"] += ".missing"; json.dump(led, open(sys.argv[1], "w"))
PY
x2step s22 "$(spawn_allow)"
n0=$(fake_writes x2 spawn); rc=0; spawn prj_syn_0301 codex syn-codex-model-01 low >/dev/null 2>&1 || rc=$?
[ "$rc" = 97 ] && [ "$(fake_writes x2 spawn)" = "$n0" ] && tail -1 "$X/writes.log" | grep -q "approval" \
  && ok "X2-22 an approval file X2 can't read: the write is refused" || fail "X2-22 rc=$rc"
python3 - "$X/ledger.json" <<'PY' || true
import json, sys
led = json.load(open(sys.argv[1])); led["approval"] = led["approval"][:-len(".missing")]; json.dump(led, open(sys.argv[1], "w"))
PY

x2step s9 null
out=$("$X/room-cli" cloud status --json) && echo "$out" | grep -q '"harnesses"' && grep -q '"kind": "cloud status --json"' "$X/reads.log" \
  && ok "X2-9 cloud status --json passes as a read, logged by kind" || fail "X2-9"
fi

# ---------------------------------------------------------------- X1 basics
if only x1; then
echo "== X1: setup, settings, map and the contracts"
python3 "$KIT" texts > "$WORK/texts.json" || true
check "texts: 15 approved, each by label, target and SHA-256" "r['all_approved'] and len(r['texts'])==15" "$WORK/texts.json"
rc=0; python3 "$KIT" files --out "$FILES" > "$WORK/files2.json" || rc=$?
check "files: a directory that is not empty is refused (exit $rc)" "'$rc'=='10' and 'not empty' in r['stopped']" "$WORK/files2.json"

kitsetup ok-setup
check "setup: a clean setup is ready; the PATH guard and X2's hash are reported" "r['setup']=='ready' and r['path_guard'].endswith('X2') and len(r['x2_sha256'])==64" "$WORK/ok-setup/setup.json"
check "setup: one models read proves openwiz reaches X2 before writes are enabled" \
  "r['setup']=='ready' and r['read_guard']=='openwiz models: one cloud status read through X2'" "$WORK/ok-setup/setup.json"
# A bypassing executable simulates the bundled lookup without invoking it.
# Failed setup must not leave a sitting that a later command can arm.
for behavior in bypass wrong-read failed-read; do
  D=$(mkworld "probe-$behavior"); appr=$(approval "probe-$behavior")
  case "$behavior" in
    bypass) printf '#!/bin/sh\nexit 0\n' > "$WORK/probe-$behavior/openwiz" ;;
    wrong-read) printf '#!/bin/sh\nexec room-cli --version\n' > "$WORK/probe-$behavior/openwiz" ;;
    failed-read) printf '#!/bin/sh\nroom-cli cloud status --json >/dev/null\nexit 7\n' > "$WORK/probe-$behavior/openwiz" ;;
  esac
  chmod 700 "$WORK/probe-$behavior/openwiz"
  rc=0
  python3 "$KIT" setup --work "$WORK/probe-$behavior/w" --room-cli "$D/room-cli" \
    --openwiz "$WORK/probe-$behavior/openwiz" --approval "$appr" \
    --targets "$WORK/probe-$behavior/targets.env" --files "$FILES" --contracts "$SOURCE_ROOT/contracts" \
    --dry-run > "$WORK/probe-$behavior.json" || rc=$?
  check "setup: $behavior cannot prove the X2 read (exit $rc)" \
    "'$rc'=='10' and 'read through X2' in r['stopped']" "$WORK/probe-$behavior.json"
  python3 - "$KIT" "$WORK/probe-$behavior/w" <<'PYGUARD' && ok "setup: failed read proof leaves writes disabled" || fail "setup: failed read proof leaves writes enabled"
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1])
kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
ledger = json.load(open(os.path.join(sys.argv[2], "x2", "ledger.json")))
assert ledger["budget"] == {"spawn": 0, "tell": 0}, ledger
assert ledger["used"] == {"spawn": 0, "tell": 0}, ledger
try:
    k = kit.Kit(sys.argv[2])
    k.arm("test-write", {"kind": "spawn", "auth": "C2-N1", "max_calls": 1})
except (kit.Stop, FileNotFoundError):
    pass
else:
    raise AssertionError("a failed setup armed a write")
PYGUARD
done
check "settings: both harnesses picked, an unoffered combination, the image harnesses and P-N found" \
  "r['outcome']=='as_expected' and set(r['settings'])=={'codex','claude-code'} and r['unoffered_found'] and r['no_remote_project_found'] and r['image_harnesses']" "$WORK/ok-setup/settings.json"
grep -qE 'syn-(codex|claude)-model|prj_syn|thr_syn' "$WORK/ok-setup/settings.json" && fail "settings: a model name or id printed" || ok "settings: no model name or id printed"

setup_fails() { # setup_fails <name> <description> <expected stop words> <setup args...>
  name=$1; desc=$2; words=$3; shift 3
  D=$(mkworld "$name"); rc=0
  python3 "$KIT" setup --work "$WORK/$name/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" \
    --targets "$WORK/$name/targets.env" --files "$FILES" --contracts "$SOURCE_ROOT/contracts" --dry-run "$@" > "$WORK/$name.json" || rc=$?
  check "$desc: setup stops (exit $rc)" "'$rc'=='10' and '$words' in r['stopped']" "$WORK/$name.json"
  [ ! -e "$WORK/$name/w" ] || fail "$desc: a work directory was made"
}
sed 's/reply with the word ok, then stop/reply with the word OK, then stop/' "$TICKET/texts.tsv" > "$WORK/bad-texts.tsv"
setup_fails bad-text "a changed text" "not approved" --texts "$WORK/bad-texts.tsv"
D=$(mkworld bad-mode); chmod 644 "$WORK/bad-mode/targets.env"; rc=0
python3 "$KIT" setup --work "$WORK/bad-mode/w" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --targets "$WORK/bad-mode/targets.env" \
  --files "$FILES" --contracts "$SOURCE_ROOT/contracts" --dry-run > "$WORK/bad-mode.json" || rc=$?
check "a targets file others can read: setup stops (exit $rc)" "'$rc'=='10' and 'chmod 600' in r['stopped']" "$WORK/bad-mode.json"
mkdir -p "$WORK/bad-files"; cp "$FILES"/* "$WORK/bad-files/"; printf 'x' >> "$WORK/bad-files/syn-notes.txt"
setup_fails bad-files "a changed synthetic file" "F4" --files "$WORK/bad-files"
setup_fails bad-sha "a binary with another sha256" "sha256" --expect-sha256 0000000000000000000000000000000000000000000000000000000000000000
setup_fails no-contracts "no contracts" "contracts" --contracts "$WORK/nowhere"
D=$(mkworld in-repo); rc=0
python3 "$KIT" setup --work "$TICKET/should-not-exist" --room-cli "$D/room-cli" --openwiz "$OPENWIZ" --targets "$WORK/in-repo/targets.env" \
  --files "$FILES" --contracts "$SOURCE_ROOT/contracts" --dry-run > "$WORK/in-repo.json" || rc=$?
check "a work directory inside a repository: setup stops (exit $rc)" "'$rc'=='10' and 'repository' in r['stopped']" "$WORK/in-repo.json"
[ ! -e "$TICKET/should-not-exist" ] || fail "in-repo: a directory was made"

rc=0; python3 "$KIT" map --work "$WORK/ok-setup/w" > "$WORK/map.json" || rc=$?
check "map: T-A Local, T-B Cloud, idle and visible; P-A quiet" "'$rc'=='0' and r['targets']['T-A']['where']=='Local' and r['targets']['T-B']['where']=='Cloud' and r['targets']['P-A']['not_quiet']==0" "$WORK/map.json"
grep -qE 'thr_syn|prj_syn|Synthetic test thread|Synthetic project' "$WORK/map.json" && fail "map: an id or title printed" || ok "map: no id or title printed"
kitsetup busy-pa; plant busy-pa pa-busy; rc=0
python3 "$KIT" map --work "$WORK/busy-pa/w" > "$WORK/busy-pa-map.json" || rc=$?
check "map: P-A with work in flight stops (exit $rc)" "'$rc'=='10' and 'work in flight' in r['stopped']" "$WORK/busy-pa-map.json"
kitrun busy-pa C0
check "run: P-A with work in flight stops before anything is created" "r['stopped'] and 'work in flight' in r['stopped']" "$WORK/busy-pa.json"
rc=0; python3 "$KIT" recheck --work "$WORK/ok-setup/w" > "$WORK/recheck.json" || rc=$?
check "recheck: every flag OpenWiz passes is still in spawn's and tell's help (exit $rc)" "'$rc'=='0' and r['help']['spawn']['missing']==[] and r['help']['tell']['missing']==[]" "$WORK/recheck.json"
kitsetup no-rid; plant no-rid help-no-request-id; rc=0
python3 "$KIT" recheck --work "$WORK/no-rid/w" > "$WORK/no-rid.json" || rc=$?
check "recheck: a help without --request-id stops (exit $rc)" "'$rc'=='10' and r['help']['spawn']['missing']==['--request-id']" "$WORK/no-rid.json"
kitsetup drift; plant drift catalogue-drift; rc=0
python3 "$KIT" settings --work "$WORK/drift/w" > "$WORK/drift-settings.json" || rc=$?
check "settings: a drifted catalogue stops (exit $rc)" "'$rc'=='10' and 'models' in r['stopped']" "$WORK/drift-settings.json"

python3 - "$KIT" "$SOURCE_ROOT" <<'PY' && ok "contracts: every committed envelope is valid; wrong types, nesting and unknown keywords are caught (#152 R6)" || fail "contracts"
import copy, glob, importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
s = kit.Schemas(os.path.join(sys.argv[2], "contracts"))
envs = sorted(glob.glob(os.path.join(sys.argv[2], "tests", "fixtures", "envelopes", "*.json")))
assert envs
for f in envs:
    assert s.problems(json.load(open(f)), "inventory") == [], f
inv = json.load(open([f for f in envs if "show" not in os.path.basename(f) and "session" not in os.path.basename(f)][0]))
assert inv["data"]["sessions"], "an inventory with sessions"
bad = copy.deepcopy(inv); bad["data"]["sessions"][0]["title"] = 17
assert s.problems(bad, "inventory"), "a session title as an integer"
bad = copy.deepcopy(inv); bad["coverage"] = "complete"
assert s.problems(bad, "inventory"), "coverage as a string"
bad = copy.deepcopy(inv); bad["extra"] = 1
assert s.problems(bad, "inventory"), "an extra key"
nt = s.docs["new-thread"]
for d in ("report", "preview", "status_read", "options"):
    assert d in nt["$defs"], d
for doc, contract, dfn in ((17, "new-thread", "report"), ({"schema": "openwiz.new-thread.v1"}, "new-thread", "report"),
                           ({"schema": "openwiz.cloud-options.v1"}, "new-thread", "options")):
    assert s.problems(doc, contract, dfn), (contract, dfn)
try:
    s._check(1, {"unevaluatedProperties": False}, nt, "$", [])
    raise SystemExit("an unknown keyword passed")
except kit.Stop:
    pass
assert s.problems(True, "new-thread", "op_id") and s.problems(1, "new-thread", "sha256")  # a bool is never an integer or string
PY
fi

# ---------------------------------------------------------------- the whole plan
if only plan; then
echo "== X1: the whole plan, with Jake's concurrent use planted (a recent session changes; a new session appears)"
kitsetup plan; plant plan touch-recent; plant plan appear
python3 - "$WORK/plan/world" <<'PYRECENT' && ok "the plan's recent session is quiet inside P-A: the 48 h rule is exercised" || fail "recent P-A fixture"
import json, pathlib, subprocess, sys
world = pathlib.Path(sys.argv[1])
path = world / "world-config.json"
config = json.loads(path.read_text())
config["recent_in_pa"] = True  # Synthetic plan-only projection, not a live observation.
path.write_text(json.dumps(config))
rows = json.loads(subprocess.check_output([str(world / "room-cli"), "thread", "list", "--json",
                                         "--include-hidden", "--include-archived"]))
row = next(r for r in rows if r["id"] == "thr_syn_0004")
assert row["projectId"] == "prj_syn_0301"
assert row["updatedAt"] == config["recent"]["thr_syn_0004"]
assert row["status"] == row["runtime"]["displayStatus"] == "idle"
assert row["queuedWork"] == "none" and row["hasPendingInteraction"] is False
assert sum(row["activity"].values()) == 0
PYRECENT
kitrun plan C0,C1,C2,C3,C4,C5; cp "$WORK/plan.json" "$WORK/plan-cli.json"
check "the CLI part C0 to C5: every step, bracket and landing as expected" "r['outcome']=='as_expected' and len(r['groups'])==6 and r['landing_at_end']=='as_expected' and all(g['outside']['verdict']=='as_expected' for g in r['groups'])" "$WORK/plan-cli.json"
check "Jake's recent session changed and a new session appeared: reported, never judged" "any(g['outside']['not_judged_changed'] for g in r['groups']) and any(g['outside']['appeared_not_judged'] for g in r['groups'])" "$WORK/plan-cli.json"
check "S2 and S5: each new thread's harness, model and effort as requested, its stages read until idle" "all(s['got'].get(k) is True for g in r['groups'] for s in g['steps'] if s['step'] in ('C2-N1','C3-N2','C4-N4') for k in ('provider_as_requested','model_as_requested','effort_as_requested','in_p_a','started'))" "$WORK/plan-cli.json"
check "AL1: the agent's report of A-1's two files, read only from the reply shape named at setup: matches (recorded, deciding nothing)" "r['agent_reports']['T-B|A1']['verdict']=='matches' and len(r['agent_reports'])==1" "$WORK/plan-cli.json"
kitswap plan
check "the swap: up, the stand-in was running" "r['swap']=='up' and r['old_was_running'] is True" "$WORK/plan/swap.json"
kitrun plan W1,W2,W3,W4; cp "$WORK/plan.json" "$WORK/plan-web.json"
check "the web part W1 to W4 (reads, refusals, probes, the cut upload, the server killed): as expected" "r['outcome']=='as_expected' and len(r['groups'])==4" "$WORK/plan-web.json"
if python3 "$SCRIPTS/test/gen-wrong-types.py" "$KIT" "$WORK/plan/w" "$SOURCE_ROOT/contracts" > "$WORK/wrong-types.out" 2>&1; then
  ok "R6 every required field of 12 real answers (7 routes, 5 CLI reports) mutated to a wrong type, by an independent walker: each rejected"
  sed 's/^/   /' "$WORK/wrong-types.out"
else fail "R6 generated wrong types"; cat "$WORK/wrong-types.out"; fi
kitjake plan J1,J2,J3,J4,J5,J6; cp "$WORK/plan.json" "$WORK/plan-jake.json"
check "Jake's part J1 to J6 (X1 presses in a dry run, a stand-in answers): as expected; every agent's report recorded, each matches" "r['outcome']=='as_expected' and len(r['groups'])==6 and len(r['agent_reports'])==3 and all(v['verdict']=='matches' for v in r['agent_reports'].values())" "$WORK/plan-jake.json"
rc=0; python3 "$KIT" parity --work "$WORK/plan/w" > "$WORK/parity.json" || rc=$?
check "S10 parity: CLI and web give the same outcome and record shape (exit $rc)" "'$rc'=='0' and r['outcome']=='as_expected' and len(r['parity'])==2" "$WORK/parity.json"
rc=0; python3 "$KIT" receipts --work "$WORK/plan/w" > "$WORK/receipts.json" || rc=$?
check "S4 receipts: every spawn receipt has #11's fixture structure; tells documented (exit $rc)" "'$rc'=='0' and r['receipts']['spawn']['count']==4 and r['receipts']['spawn']['documented_keys'] and r['drift']==[]" "$WORK/receipts.json"
kitunswap plan
check "the swap back: the stand-in restored" "r['swap']=='restored'" "$WORK/plan/unswap.json"
python3 - "$WORK/plan/w/x2/writes.log" "$SCRIPTS/plan.json" <<'PY' && ok "X2 let through exactly the planned writes: 4 spawns (N1, N2, N4, N3) and 2 tells (A1, A2)" || fail "planned writes"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
calls = [r for r in rows if r["outcome"] in ("called", "called_after_hold")]
plan = json.load(open(sys.argv[2]))
want = sum(s["expect"].get("calls", 0) for g in plan["groups"] for s in g["steps"])
assert len(calls) == want == 6, (len(calls), want)
assert sorted(r["kind"] for r in calls) == ["spawn"] * 4 + ["tell"] * 2
PY
[ "$(fake_writes plan spawn)" = 4 ] && [ "$(fake_writes plan tell)" = 2 ] && ok "the fake got exactly 4 spawns and 2 tells" || fail "fake writes: $(fake_writes plan spawn) spawns, $(fake_writes plan tell) tells"
if grep -qE 'thr_syn_|prj_syn_|op-acc-|web-[0-9a-f]{32}|openwiz\.invalid|Synthetic (test thread|new thread|project)|syn-(codex|claude)-model|/tmp/' "$WORK"/plan-*.json "$WORK/parity.json" "$WORK/receipts.json"; then
  fail "a report holds an id, op id, host name, title, model name or path"
else ok "no report holds an id, op id, host name, title, model name or path"; fi
fi

# ---------------------------------------------------------------- scope and carry-over
if only scope; then
echo "== X1: brackets judge only the test's own threads and project; a fresh sitting carries the landing (#13)"
kitsetup sc; plant sc touch-outside; kitrun sc C0,C1,C2
check "scope: a cold session outside P-A changes during C2: recorded, never judged; C0 to C2 as expected" \
  "r['outcome']=='as_expected' and any((g['outside'].get('not_judged_changed') or {}).get('lastReadAt') for g in r['groups'])" "$WORK/sc.json"
check "scope: only P-A's cold sessions are judged (3 in the fake world), and the rule names the test project" \
  "r['judged']['sessions']==3 and 'test project' in r['judged']['rule']" "$WORK/sc.json"
KIT_FROM=sc kitsetup sc2; unset KIT_FROM; kitrun sc2 C3  # sh keeps a prefix assignment after a function call
check "carry: a fresh sitting under the same approval and targets starts from the earlier sittings' landing; C3 as expected" \
  "r['outcome']=='as_expected' and r['landing_at_start']=='as_expected' and r['groups'][0]['steps'][0]['verdict']=='as_expected'" "$WORK/sc2.json"
check "carry: the fresh sitting's setup names the sittings it carried from" "(r.get('carried') or {}).get('from')==[1]" "$WORK/sc2/setup.json"
KIT_FROM=sc kitsetup sc3; unset KIT_FROM; kitrun sc3 C4
check "carry: a third sitting counts inherited creates once, not twice" "r['outcome']=='as_expected' and r['landing_at_start']=='as_expected'" "$WORK/sc3.json"
KIT_FROM=sc kitsetup sc4; unset KIT_FROM
kitrun sc3 C5
check "carry: the prior sitting can finish its two sends after a sibling setup" "r['outcome']=='as_expected'" "$WORK/sc3.json"
kitrun sc4 C0
check "carry: run entry includes a sibling's writes completed after setup" "r['outcome']=='as_expected' and r['landing_at_start']=='as_expected'" "$WORK/sc4.json"
fi

# ---------------------------------------------------------------- no P-N
if only nopn; then
echo "== X1: no standard project without a remote (R-2 skipped as a gap)"
# R-2 needs P-N, a standard project without a remote. With none (the PC, #13), C1-R2 is skipped as a
# recorded gap, never run against another project, and C1's other refusals still run.
kitsetup no-pn; plant no-pn no-p-n; python3 "$KIT" settings --work "$WORK/no-pn/w" > "$WORK/no-pn/settings.json" || true; kitrun no-pn C0,C1
check "no P-N: settings say so, C1-R2 is skipped as a gap, C0 and C1 otherwise as expected, 0 writes" \
  "r['outcome']=='as_expected' and [s['step'] for g in r['groups'] for s in g['steps'] if s['verdict'].startswith('skipped')]==['C1-R2'] and all(s['verdict']=='as_expected' for g in r['groups'] for s in g['steps'] if s['step']!='C1-R2')" "$WORK/no-pn.json"
check "no P-N: settings report no_remote_project_found false" "r['no_remote_project_found'] is False" "$WORK/no-pn/settings.json"
[ "$(fake_writes no-pn spawn)" = 0 ] && ok "no P-N: the fake got no spawn" || fail "no P-N: spawns $(fake_writes no-pn spawn)"
kitsetup with-pn; kitrun with-pn C0,C1  # #1065 R1: with a P-N, R-2 runs (never skipped)
check "with P-N: C1-R2 runs and is refused with zero calls (project_no_github_remote), nothing skipped" \
  "r['outcome']=='as_expected' and not [s for g in r['groups'] for s in g['steps'] if s['verdict'].startswith('skipped')] and [s for g in r['groups'] for s in g['steps'] if s['step']=='C1-R2' and s['verdict']=='as_expected']" "$WORK/with-pn.json"
fi

# ---------------------------------------------------------------- planted faults
if only faults; then
echo "== X1: each planted fault stops the run at the right place"
fault() { # fault <plant> <groups> <description> <python expression on report r>
  kitsetup "f-$1"; plant "f-$1" "$1"; kitrun "f-$1" "$2"
  check "$3 (plant $1)" "r['outcome']!='as_expected' and ($4)" "$WORK/f-$1.json"
}
fault spawn-twice C0,C1,C2 "one spawn makes two threads: stops at C2 (S1)" "'P-A gained 2 threads, expected 1' in r['stopped']"
fault wrong-project C0,C1,C2 "a thread in another project: stops at C2-N1 (S1)" "r['stopped'].startswith('C2-N1') and 'in_p_a is false' in r['stopped']"
fault wrong-model C0,C1,C2 "another model reported: stops at C2-N1 (S2)" "r['stopped'].startswith('C2-N1') and 'model_as_requested is false' in r['stopped']"
fault prompt-prefix C0,C1,C2 "the prompt arrives altered: stops at C2's landing (S11)" "'N1 arrived wrapped' in r['stopped']"
fault touch-sample C0,C1,C2 "a change in a judged session (moved by the first create): stops at C2's bracket (S1)" "r['stopped'].startswith('C2') and 'judged session' in r['stopped']"
fault cold-pending C0,C1,C2 "a cold session turns pending: stops (judged against its start, #152 R3)" "'judged session' in r['stopped']"
fault jake-in-pa C0,C1,C2 "a thread in P-A that no step made: stops (a false alarm if it was Jake)" "'no step made' in r['stopped']"
for f in bad-hash:differs no-report:absent; do  # AL1 is the agent's report, recorded as just that (L-5): it decides nothing
  kitsetup "f-${f%%:*}"; plant "f-${f%%:*}" "${f%%:*}"; kitrun "f-${f%%:*}" C0,C1,C2,C3,C4,C5
  check "the agent's report ${f%%:*}: recorded as ${f##*:}, and the run as expected (AL1 informs, never decides; plant ${f%%:*})" \
    "r['outcome']=='as_expected' and r['agent_reports']['T-B|A1']['verdict']=='${f##*:}'" "$WORK/f-${f%%:*}.json"
done
fault misroute C0,C1,C2,C3,C4,C5 "A-1 lands on T-A: stops at C5 (AL1)" "'A1 on T-A: 1, expected 0' in r['stopped']"
fault dup-late C0,C1,C2 "a duplicate that arrives after the step's own landing check: caught by a later one (#152 R5)" "'N1 twice in one new thread' in r['stopped']"
KIT_IDLE=4 fault stuck-pending C0,C1,C2 "a thread that never starts: stops at C2-N1 (S5)" "r['stopped'].startswith('C2-N1') or 'settle' in r['stopped']"
echo "== X1: a write outside the plan (Jake's page, say) reaching X2 stops the run"
kitsetup stray
# The strays start once the run has reported its first step (never a race with its start),
# and go on through C1 and C2: each lands in a step (refused there) or between steps.
( i=0; until grep -q "C0-models:" "$WORK/stray.err" 2>/dev/null || [ "$i" -ge 600 ]; do sleep 0.1; i=$((i + 1)); done
  for i in $(seq 1 30); do "$WORK/stray/w/x2/room-cli" thread spawn --project prj_syn_0301 --machine cloud --provider codex --model syn-codex-model-01 \
    --reasoning-level low --request-id ow1-0123456789abcdef0123456789abcdef01234567 --json --prompt "Synthetic stray write" >/dev/null 2>&1; sleep 0.2; done ) &
kitrun stray C0,C1,C2; wait
check "a stray write during the run: refused by X2, counted, and the run stops" "r['outcome']!='as_expected' and ('outside the plan' in r['stopped'] or 'refused' in r['stopped'])" "$WORK/stray.json"
called=$(grep -c '"outcome": "called"' "$WORK/stray/w/x2/writes.log" || true)
[ "$(fake_writes stray spawn)" = "$called" ] && ok "no stray write reached the fake: it got only the $called spawn(s) the steps allowed" \
  || fail "the fake got $(fake_writes stray spawn) spawns, X2 allowed $called"
fi

# ---------------------------------------------------------------- the live path
if only live; then
echo "== X1: the live path (no --dry-run): jake-sim presses as Jake's browser would, and answers"
livesetup() { # livesetup <name> <port>: a sitting without --dry-run (jake-sim presses for Jake)
  d=$(mkworld "$1"); mkdir -p "$WORK/$1/old"
  python3 "$KIT" setup --work "$WORK/$1/w" --room-cli "$d/room-cli" --openwiz "$OPENWIZ" --server "$SERVER" --targets "$WORK/$1/targets.env" --approval "$(approval "$1")" \
    --files "$FILES" --port "$2" --host openwiz.invalid --restore-cmd "$(oldcmd "$2")" --agent-reply syn-agent-message:data.input \
    --restore-log "$WORK/$1/old/server.log" --restore-sha256 "$SERVER_SHA" --contracts "$SOURCE_ROOT/contracts" > "$WORK/$1/setup.json" || true
  python3 "$KIT" settings --work "$WORK/$1/w" > "$WORK/$1/settings.json" || true
  kitswap "$1"
}
livesetup livetypo $(( ${KIT_PORT:-18370} + 8 ))
JAKE_SIM_TYPO=N3 kitjake livetypo J1
check "live path: N-3 pasted with a trailing space: X2 refuses it, nothing is created, J1 is not as expected and the sitting tainted" "r['outcome']!='as_expected' and r['stopped'].startswith('J1-N3') and r['groups'][0]['steps'][0]['got'].get('calls')==0 and r['x2_refusals']['count']>=1" "$WORK/livetypo.json"
kitjake livetypo J1
check "live path: J1 again in that sitting: X1 arms nothing (the taint stays; only a new setup clears it)" "r['outcome']!='as_expected' and 'arms no write' in r['stopped']" "$WORK/livetypo.json"
kitunswap livetypo
livesetup live $(( ${KIT_PORT:-18370} + 7 ))
kitjake live J1,J2,J3,J4,J5,J6
check "live path: a fresh sitting, Jake's presses (phone create with an image, desktop send of 10 MiB, the tray, the cut upload, Chrome) as expected, N-3 in exactly one new thread" "r['outcome']=='as_expected' and len(r['groups'])==6 and any(c.get('msg')=='N3' and c.get('threads')==1 for c in r['groups'][0]['landing'][-1]['checked'])" "$WORK/live.json"
grep -q ">>> PRESS J1-N3" "$WORK/live/prompts.log" && grep -q ">>> ANSWER J1-N3-shown" "$WORK/live/prompts.log" && ok "live path: the prompts reach the runner" || fail "live path: prompts"
JAKE_SIM_SAY="J3-tray-svg=rendered" kitjake live J3
check "live path: Jake saying the SVG rendered stops J3 (AL10)" "r['outcome']=='not_as_expected' and r['stopped'].startswith('J3-tray') and 'said_svg' in r['stopped']" "$WORK/live.json"
kitunswap live
fi

# ---------------------------------------------------------------- #152's findings, re-proved here
if only sol; then
echo "== #152's findings (Sol), re-proved on this kit"
python3 - "$KIT" <<'PY' && ok "R1: a reused or changed PID is never signalled" || fail "R1"
import importlib.util, subprocess, sys, time
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
p = subprocess.Popen(["sleep", "30"])
ident = kit.identity(p.pid)
assert ident and kit.same_process(ident)
other = dict(ident, lstart="Mon Jan  1 00:00:00 2001")
assert not kit.signal_if_same(other, 15) and p.poll() is None
assert not kit.signal_if_same(dict(ident, args="sleep 31"), 15) and p.poll() is None
assert kit.stop_verified(ident) and p.wait(5) is not None
PY
# R2, one owner (the orchestrator's design for #152, as #152 has it at e7568d4): the guard is X1's
# server's parent and acts on its pipe from the supervisor, never on the status file; if the guard
# dies, the server dies with it. Each case on its own port, with a stand-in for Jake's server.
swapsetup() { # swapsetup <name> <port> [stub]: kitsetup on that port, the stand-in started; "stub": X1's server is the stub
  SETUP_PORT=$2; kitsetup "$1"; SETUP_PORT=
  if [ "${3:-}" = stub ]; then
    mkdir -p "$WORK/$1/stub"; cp "$SCRIPTS/test/stub-server.py" "$WORK/$1/stub/stub-server.py"; chmod 755 "$WORK/$1/stub/stub-server.py"
    python3 -c "import json,sys; p=sys.argv[1]; c=json.load(open(p)); c['server']=sys.argv[2]; json.dump(c, open(p,'w'))" \
      "$WORK/$1/w/kit.json" "$WORK/$1/stub/stub-server.py"
  fi
  ( cd "$WORK/$1/old" && nohup "$SERVER" --port "$2" --allowed-host "$OLDHOST" >> server.log 2>&1 < /dev/null & )
  for i in $(seq 1 30); do healthy "$2" && break; sleep 0.2; done
}
restored() { # restored <name> <port> <state wanted>: no stub left, the stand-in back and healthy, the state recorded
  for i in $(seq 1 120); do [ -z "$(stub_pid "$1")" ] && [ -n "$(old_pid "$2")" ] && healthy "$2" && [ "$(swapfield "$1" state)" = "$3" ] && break; sleep 0.5; done
  st=$(swapfield "$1" state)
  [ -z "$(stub_pid "$1")" ] && [ -n "$(old_pid "$2")" ] && healthy "$2" && [ "$st" = "$3" ]
}
B=${KIT_PORT:-18370}

SW=$((B + 30)); swapsetup r2crash $SW
python3 "$KIT" swap --work "$WORK/r2crash/w" start --minutes 5 > /dev/null 2>&1 || true
SUP=$(swapfield r2crash supervisor); kill9mine "$SUP"
restored r2crash $SW restored-by-guard && ok "R2 the supervisor killed (SIGKILL) with the swap up: the guard stops X1's server and restores the stand-in" \
  || fail "R2 supervisor killed: state=$st old=$(old_pid $SW)"
stopmine "$(old_pid $SW)"

SW=$((B + 31)); swapsetup r2file $SW
python3 "$KIT" swap --work "$WORK/r2file/w" start --minutes 5 > /dev/null 2>&1 || true
SUP=$(swapfield r2file supervisor); { mine "$SUP" && kill -STOP "$SUP" || true; }   # the supervisor frozen; then its status file deleted
rm -f "$WORK/r2file/w/run/swap.json"; sleep 6
served=0; healthy $SW && [ -z "$(old_pid $SW)" ] && served=1         # X1's server still serving: no action from the file
{ mine "$SUP" && kill -CONT "$SUP" && kill "$SUP" || true; }
for i in $(seq 1 60); do [ -n "$(old_pid $SW)" ] && healthy $SW && break; sleep 0.5; done
[ "$served" = 1 ] && [ -n "$(old_pid $SW)" ] && healthy $SW \
  && ok "R2 the guard acts on its pipe, never on the status file (deleted: no action); the supervisor stopped: the stand-in restored" \
  || fail "R2 guard and status file: served=$served old=$(old_pid $SW)"
stopmine "$(old_pid $SW)"

SW=$((B + 32)); swapsetup r2guard $SW
python3 "$KIT" swap --work "$WORK/r2guard/w" start --minutes 5 > /dev/null 2>&1 || true
GP=$(swapfield r2guard guard); up=0; healthy $SW && up=1
kill9mine "$GP"
gone=0; for i in $(seq 1 40); do answers $SW || { gone=1; break; }; sleep 0.25; done
for i in $(seq 1 40); do st=$(swapfield r2guard state); [ "$st" = guard-died ] && break; sleep 0.25; done
[ "$up" = 1 ] && [ "$gone" = 1 ] && [ "$st" = guard-died ] \
  && ok "R2 the guard killed (SIGKILL): X1's server dies with it (EOF on its pipe), and the state says guard-died (Jake's server by hand, per HANDOFF)" \
  || fail "R2 guard killed: up=$up gone=$gone state=$st"
stopmine $(ps -eo pid=,args= | awk -v w="$WORK/r2guard/" 'index($0, w) && !/awk/ {print $1}')

n=0
for delay in 0 0.3 0.8 1.5 3; do   # Sol's interleaving on #152, as kill points through the swap's start
  n=$((n + 1)); SW=$((B + 32 + n)); name=r2kp$n; swapsetup $name $SW
  python3 "$KIT" swap --work "$WORK/$name/w" start --minutes 5 > /dev/null 2>&1 &
  SUP=""; for i in $(seq 1 100); do SUP=$(swapfield $name supervisor); [ -n "$SUP" ] && break; sleep 0.05; done
  sleep $delay; kill9mine "$SUP"
  restored $name $SW restored-by-guard && ok "R2 the supervisor killed ${delay} s into the swap's start: X1's server stopped, the stand-in restored" \
    || fail "R2 supervisor killed ${delay} s in: state=$st old=$(old_pid $SW)"
  stopmine "$(old_pid $SW)"; wait 2>/dev/null
done

SW=$((B + 40)); swapsetup r2startcrash $SW stub; touch "$WORK/r2startcrash/stub/bad"
python3 "$KIT" swap --work "$WORK/r2startcrash/w" start --minutes 5 > /dev/null 2>&1 &
for i in $(seq 1 40); do [ -n "$(stub_pid r2startcrash)" ] && break; sleep 0.25; done
sleep 1; SUP=$(swapfield r2startcrash supervisor); kill9mine "$SUP"   # the stub holds the port, not healthy
restored r2startcrash $SW restored-by-guard && ok "R2 the supervisor killed during startup (the new server bound, never healthy): stopped, the stand-in answers again" \
  || fail "R2 startup crash: stub=$(stub_pid r2startcrash) old=$(old_pid $SW) state=$st"
stopmine "$(old_pid $SW)"; wait 2>/dev/null

SW=$((B + 41)); swapsetup r2timeout $SW stub; touch "$WORK/r2timeout/stub/bad"
rc=0; python3 "$KIT" swap --work "$WORK/r2timeout/w" start --minutes 5 > /dev/null 2>&1 || rc=$?
restored r2timeout $SW restored && [ "$rc" = 10 ] && ok "R2 a server that never becomes healthy: the swap fails (exit 10), stops it, and the stand-in answers again" \
  || fail "R2 startup timeout: rc=$rc stub=$(stub_pid r2timeout) old=$(old_pid $SW) state=$st"
stopmine "$(old_pid $SW)"

for f in kill-server:F6 stop-server:F4; do
  act=${f%%:*}; name=r2re${f##*:}; SW=$((B + $([ $act = kill-server ] && echo 42 || echo 43)))
  swapsetup $name $SW stub
  python3 "$KIT" swap --work "$WORK/$name/w" start --minutes 5 > /dev/null 2>&1 || true
  touch "$WORK/$name/stub/bad"   # the restart after the fault never becomes healthy
  python3 "$KIT" swap --work "$WORK/$name/w" $act > /dev/null 2>&1 || true
  rc=0; python3 "$KIT" swap --work "$WORK/$name/w" start-server > /dev/null 2>&1 || rc=$?
  restored $name $SW restored && [ "$rc" = 10 ] && ok "R2 a restart after ${f##*:} that never becomes healthy: stopped, the stand-in answers again" \
    || fail "R2 restart after ${f##*:}: rc=$rc stub=$(stub_pid $name) old=$(old_pid $SW) state=$st"
  stopmine "$(old_pid $SW)"
done

SW=$((B + 44)); swapsetup r2recrash $SW stub
python3 "$KIT" swap --work "$WORK/r2recrash/w" start --minutes 5 > /dev/null 2>&1 || true
touch "$WORK/r2recrash/stub/bad"
python3 "$KIT" swap --work "$WORK/r2recrash/w" kill-server > /dev/null 2>&1 || true
python3 "$KIT" swap --work "$WORK/r2recrash/w" start-server > /dev/null 2>&1 &
for i in $(seq 1 40); do [ -n "$(stub_pid r2recrash)" ] && break; sleep 0.25; done
sleep 1; SUP=$(swapfield r2recrash supervisor); kill9mine "$SUP"
restored r2recrash $SW restored-by-guard && ok "R2 the supervisor killed while restarting after F6: the new server stopped, the stand-in answers again" \
  || fail "R2 restart crash: stub=$(stub_pid r2recrash) old=$(old_pid $SW) state=$st"
stopmine "$(old_pid $SW)"; wait 2>/dev/null

SW=$((B + 45)); swapsetup r2other $SW
stopmine "$(old_pid $SW)"; sleep 0.5
python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', $SW)); s.listen(); time.sleep(20)" &
OTHER=$!; sleep 0.5
rc=0; python3 "$KIT" swap --work "$WORK/r2other/w" start --minutes 5 > "$WORK/r2other.json" 2>&1 || rc=$?
alive=0; kill -0 $OTHER 2>/dev/null && alive=1
kill $OTHER 2>/dev/null; wait $OTHER 2>/dev/null || true
[ "$rc" = 10 ] && [ "$alive" = 1 ] && grep -q "not the confirmed launch" "$WORK/r2other.json" \
  && ok "R2 something else on the port (not the confirmed launch): the swap refuses and signals nothing" || fail "R2 swap other: rc=$rc alive=$alive"
# R4: every forbidden string, of any length, decoded; nothing printed.
kitsetup r4
python3 - "$WORK/r4/world/world-config.json" <<'PY' || true
import json, sys
c = json.load(open(sys.argv[1]))
c["titles"] = {"thr_syn_0001": "HR", "thr_syn_0005": "私事", "thr_syn_0006": 'Synthetic "private" title',
               "thr_syn_0008": "Synthetic\\private"}
json.dump(c, open(sys.argv[1], "w"))
PY
python3 - "$KIT" "$WORK/r4/w" <<'PY' && ok "R4: titles HR, 2 CJK characters, quotes and a backslash, as values and keys: blocked, never printed" || fail "R4"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2]); k.args = None
kit.collect_forbidden(k)
for t in ("HR", "私事", 'Synthetic "private" title', "Synthetic\\private"):
    for rep in ({"x": "a %s b" % t}, {t: 1}, {"x": [t]}):
        try:
            kit.publish(k, rep)
            raise SystemExit("published %r" % (rep,))
        except kit.Stop:
            pass
kit.publish(k, {"x": "a harmless report"})
PY
# R8 and R9: parity and receipts exit 10 when not as expected; every receipt counts.
kitsetup r8; rc=0
python3 "$KIT" parity --work "$WORK/r8/w" > "$WORK/r8-parity.json" || rc=$?
check "R8: parity with no records exits 10, incomplete" "'$rc'=='10' and r['outcome']=='incomplete'" "$WORK/r8-parity.json"
rc=0; python3 "$KIT" receipts --work "$WORK/r8/w" > "$WORK/r8-receipts.json" || rc=$?
check "R8: receipts with none captured exit 10, the missing kinds as drift" "'$rc'=='10' and 'missing: spawn' in r['drift']" "$WORK/r8-receipts.json"
X="$WORK/r8/w/x2"
mkdir -p "$X"
cp "$FIX/room-cli-v127/new-thread/spawn-receipt-created.json" "$X/capture-spawn-a-1.out"
cp "$FIX/room-cli-v127/new-thread/spawn-receipt-drift-no-id.json" "$X/capture-spawn-b-2.out"
cp "$FIX/room-cli-0.43.1/send/tell-sent.json" "$X/capture-tell-c-3.out"
rc=0; python3 "$KIT" receipts --work "$WORK/r8/w" > "$WORK/r9.json" || rc=$?
check "R9: one undocumented spawn receipt after a documented one is drift (exit $rc)" "'$rc'=='10' and 'spawn' in r['drift'] and r['receipts']['spawn']['count']==2" "$WORK/r9.json"
mv "$X/capture-spawn-a-1.out" "$X/capture-spawn-z-9.out" || true
rc=0; python3 "$KIT" receipts --work "$WORK/r8/w" > "$WORK/r9b.json" || rc=$?
check "R9: in the other order too (exit $rc)" "'$rc'=='10' and 'spawn' in r['drift']" "$WORK/r9b.json"
# R11: the cleanup stops only what this suite started.
port=$(( ${KIT_PORT:-18370} + 11 ))
# A token of this check's own, so the reaper here stops only this check's process, never the
# suite's other helpers (the Access stand-in, the stand-ins): the suite's cleanup uses the suite's.
R11_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
env -u KIT13_OWNER "$SERVER" --port "$port" --allowed-host "$OLDHOST" > /dev/null 2>&1 &
other=$!
sleep 0.5; KIT13_OWNER=$R11_TOKEN sleep 30 & mine=$!
n=$(python3 "$SCRIPTS/test/reap.py" "$R11_TOKEN") || true
if kill -0 "$other" 2>/dev/null && ! kill -0 "$mine" 2>/dev/null; then ok "R11: an openwiz-server on this suite's port range that it didn't start survives; its own process is stopped"
else fail "R11: other alive=$(kill -0 "$other" 2>/dev/null && echo yes || echo no), mine alive=$(kill -0 "$mine" 2>/dev/null && echo yes || echo no)"; fi
kill "$other" 2>/dev/null || true; wait "$other" 2>/dev/null || true
fi

# ---------------------------------------------------------------- Sol's review of #168 (round 1)
if only r168; then
echo "== Sol's #168 findings: one sitting (R1, R3), admission under the lock (R2), the agent's own reply (R4), the UI gate (R5), any refusal (R6), Access (R7), L-8's allowance across sittings (R8)"
P=${KIT_PORT:-18370}
r168() { [ -z "${KIT_R168:-}" ] || echo ",$KIT_R168," | grep -q ",$1,"; }  # KIT_R168=R2,R6: those findings only
if r168 R1; then
# R1: a consumed write is never dispatched again, in any later invocation; the run's budget holds.
kitsetup rb
for i in 1 2 3 4 5; do kitrun rb C2; cp "$WORK/rb.json" "$WORK/rb-$i.json"; echo "$RC" > "$WORK/rb-$i.rc"; done
check "R1 C2 run once: as expected, one spawn" "r['outcome']=='as_expected'" "$WORK/rb-1.json"
check "R1 C2 run again four times in the same sitting: X1 stops each before arming (exit 10), naming the write already made" \
  "all(json.load(open('$WORK/rb-%d.json' % i)).get('outcome')!='as_expected' and 'already made' in json.load(open('$WORK/rb-%d.json' % i)).get('stopped','') and open('$WORK/rb-%d.rc' % i).read().strip()=='10' for i in (2,3,4,5))" "$WORK/rb-5.json"
[ "$(fake_writes rb spawn)" = 1 ] && ok "R1 five runs of C2: exactly one spawn reached the fake" || fail "R1 five runs of C2: $(fake_writes rb spawn) spawns reached the fake"
kitsetup rc
( i=0; until grep -q '"outcome": "called"' "$WORK/rc/w/x2/writes.log" 2>/dev/null || [ "$i" -ge 600 ]; do sleep 0.05; i=$((i + 1)); done
  for p in $(ps -eo pid=,args= | awk -v w="--work $WORK/rc/w --groups C2" 'index($0, w) && !/awk/ {print $1}'); do mine "$p" && kill -9 "$p" 2>/dev/null; done ) &
kitrun rc C2; wait
kitrun rc C2
check "R1 X1 killed right after C2-N1's spawn was admitted, then C2 again: the re-entry stops (exit $RC)" "r['outcome']!='as_expected' and '$RC'=='10'" "$WORK/rc.json"
[ "$(fake_writes rc spawn)" = 1 ] && ok "R1 crash and re-entry: exactly one spawn reached the fake" || fail "R1 crash and re-entry: $(fake_writes rc spawn) spawns"
python3 - "$KIT" "$WORK/rc/w" <<'PY' && ok "R1 after the crash, C2-N1's write is recorded as made: arming it again is refused, whatever else stops the run first" || fail "R1 crash: C2-N1 could be armed again"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2]); k.args = None
h, m, e = kit.create_settings(k, {"harness": "claude-code"})
step = {"id": "C2-N1", "msg": "N1", "attach": []}
try:
    k.arm("C2-N1", kit.write_for(k, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, k.texts["N1"]))
except kit.Stop as x:
    assert "already made" in str(x), str(x)
else:
    raise SystemExit("armed again")
finally:
    k.disarm()
PY
kitsetup rbud
python3 - "$SCRIPTS/plan.json" "$WORK/rbud/plan-extra.json" <<'PY' || true
import json, sys
p = json.load(open(sys.argv[1]))
extra = [{"id": "C9-%s" % m, "seq": i + 1, "do": "create", "msg": m, "harness": "codex",
          "expect": {"exit": 0, "status": "created", "attempts": 1, "calls": 1, "land": 1}} for i, m in enumerate(("N5", "N6"))]
p["groups"].append({"id": "C9", "claims": ["test only: two creates past the budget"], "steps": extra})
json.dump(p, open(sys.argv[2], "w"))
PY
python3 -c "import json,sys; p=sys.argv[1]; c=json.load(open(p)); c['plan']=sys.argv[2]; json.dump(c, open(p,'w'))" "$WORK/rbud/w/kit.json" "$WORK/rbud/plan-extra.json"
kitrun rbud C2,C3,C4,C9
check "R1 the run's budget (4 creates): the fifth create stops before any dispatch" "r['outcome']!='as_expected' and r['stopped'].startswith('C9-N6') and 'budget' in r['stopped']" "$WORK/rbud.json"
[ "$(fake_writes rbud spawn)" = 4 ] && ok "R1 the budget: exactly 4 spawns reached the fake" || fail "R1 the budget: $(fake_writes rbud spawn) spawns"
fi

if r168 R2; then
# R2: a call that waits for X2's lock is judged on the step as it is when it gets the lock.
kitsetup ra
python3 - "$KIT" "$WORK/ra/w" <<'PY' && ok "R2 a spawn waiting on X2's lock while X1 disarms: refused, zero calls" || fail "R2 admission after disarm"
import importlib.util, os, subprocess, sys, time
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2]); k.args = None; k.settings = k._load("settings.json", None)
h, m, e = kit.create_settings(k, {"harness": "codex"})
text = k.texts["N4"]
step = {"id": "T-race", "msg": "N4", "attach": []}
k.arm("T-race", dict(kit.write_for(k, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, text), auth="T-race"), ttl_s=120)
argv = [os.path.join(k.x2, "room-cli"), "thread", "spawn", "--project", k.targets["P-A"], "--machine", "cloud", "--provider", h,
        "--model", m, "--reasoning-level", e, "--request-id", "ow1-" + "0" * 40, "--json", "--prompt", text]
import fcntl
held = k.locked() if hasattr(k, "locked") else None  # the kit's own (re-entrant) hold of X2's lock, if it has one
if held:
    held.__enter__()
else:
    lock = open(os.path.join(k.x2, "writes.lock"), "a"); fcntl.flock(lock, fcntl.LOCK_EX)
p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(1.5)
assert p.poll() is None, "X2 did not wait for the lock"
k.disarm()  # X1 moves on while the call waits
if held:
    held.__exit__(None, None, None)
else:
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
out, err = p.communicate(timeout=30)
assert p.returncode == 97, p.returncode
PY
kitsetup ra2  # a sitting of its own: the first case's refusal taints its sitting
python3 - "$KIT" "$WORK/ra2/w" <<'PY' && ok "R2 a spawn whose step expires while it waits on X2's lock: refused, zero calls" || fail "R2 expiry while waiting"
import importlib.util, os, subprocess, sys, time, fcntl
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2]); k.args = None; k.settings = k._load("settings.json", None)
h, m, e = kit.create_settings(k, {"harness": "codex"})
text = k.texts["N4"]
step = {"id": "T-exp", "msg": "N4", "attach": []}
k.arm("T-exp", dict(kit.write_for(k, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, text), auth="T-exp"), ttl_s=1)
argv = [os.path.join(k.x2, "room-cli"), "thread", "spawn", "--project", k.targets["P-A"], "--machine", "cloud", "--provider", h,
        "--model", m, "--reasoning-level", e, "--request-id", "ow1-" + "1" * 40, "--json", "--prompt", text]
held = k.locked() if hasattr(k, "locked") else None
if held:
    held.__enter__()
else:
    lock = open(os.path.join(k.x2, "writes.lock"), "a"); fcntl.flock(lock, fcntl.LOCK_EX)
p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(2.5)  # past the step's expiry, while X2 waits
if held:
    held.__exit__(None, None, None)
else:
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
p.communicate(timeout=30)
assert p.returncode == 97, p.returncode
PY
[ "$(fake_writes ra spawn)" = 0 ] && [ "$(fake_writes ra2 spawn)" = 0 ] && ok "R2 neither waiting spawn reached the fake" || fail "R2 waiting spawns reached the fake: $(fake_writes ra spawn) and $(fake_writes ra2 spawn)"
fi

if r168 R3; then
# R3: the judged set and its baselines are the sitting's, from its first run, through every later one.
kitsetup rs
kitrun rs C0; cp "$WORK/rs.json" "$WORK/rs-1.json"
python3 - "$WORK/rs/world/world.json" <<'PY' || true
import json, sys
w = json.load(open(sys.argv[1])); w["cold"] = 1; json.dump(w, open(sys.argv[1], "w"))
PY
kitrun rs C1
check "R3 a judged (cold) session turns pending between two runs of the sitting: the second run stops (exit $RC)" "r['outcome']!='as_expected' and 'judged' in r['stopped'] and '$RC'=='10'" "$WORK/rs.json"
kitsetup rs2
kitrun rs2 C0
python3 - "$WORK/rs2/world/world.json" <<'PY' || true
import json, sys
w = json.load(open(sys.argv[1])); w["touched"] = 1; json.dump(w, open(sys.argv[1], "w"))
PY
kitrun rs2 C1
check "R3 a judged session's lastReadAt moves between two runs: the second run stops (exit $RC)" "r['outcome']!='as_expected' and 'judged' in r['stopped'] and '$RC'=='10'" "$WORK/rs2.json"
fi

if r168 R4; then
# R4, round 2 (the sheet itself, L-5: the agent's report "is recorded as just that"): AL1 decides
# nothing. It records what was found and where (event type, field), and says "matches" only when
# the event is positively the agent's reply, by the reply shape named at setup; otherwise
# "unattributed". Upload, system and tool metadata never stand in.
python3 - "$KIT" <<'PY' && ok "R4 the agent's report: only the named reply's own field counts; metadata, later system or nested upload events never match; no reply shape named: unattributed" || fail "R4 impersonation"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
h = "c43c8b8aeeb4288c7a38e12c1220121e473c7903af32771f28982fbf2a99feb0"
w = "0" * 64
reply = ("syn-agent-message", "data.input")
user = {"seq": 1, "type": "syn-user-message", "data": {"input": "prompt", "attachments": [{"name": "syn-small.png", "sha256": h}]}}
def agent(seq, text): return {"seq": seq, "type": "syn-agent-message", "data": {"input": text}}
cases = [
    ("the prompt's own metadata, an agent that can't read it", [user, agent(2, "Synthetic reply: I can't read it.")], "absent"),
    ("a later system event carrying the hash", [user, {"seq": 2, "type": "syn-system", "data": {"sha256": h}}], "absent"),
    ("a later nested upload record", [user, {"seq": 2, "type": "syn-upload", "data": {"upload": {"files": [{"sha256": h}]}}}], "absent"),
    ("the hash in the reply's other field", [user, {"seq": 2, "type": "syn-agent-message", "data": {"input": "ok", "meta": h}}], "absent"),
    ("correct metadata, a wrong agent report", [user, {"seq": 2, "type": "syn-system", "data": {"sha256": h}}, agent(3, "syn-small.png " + w)], "differs"),
    ("the agent's own correct report", [user, agent(2, "syn-small.png " + h)], "matches"),
]
for name, ev, want in cases:
    got = kit.agent_report(ev, "prompt", [h], reply)
    assert got["verdict"] == want, (name, got)
    got = kit.agent_report(ev, "prompt", [h], None)
    assert got["verdict"] == "unattributed", (name, got)
got = kit.agent_report(cases[1][1], "prompt", [h], None)
assert got["found"] == [{"type": "syn-system", "field": "data.sha256", "expected": 1, "other": 0}], got["found"]
PY
for f in no-report:absent bad-hash:differs none:matches; do
  plant=${f%%:*}; want=${f##*:}; name=r4$plant
  off=$(case $plant in no-report) echo 0;; bad-hash) echo 1;; *) echo 2;; esac)  # outside $((...)): sh parses "$((P" there as a subshell
  SETUP_PORT=$((P + 70 + off)); kitsetup $name; SETUP_PORT=
  [ "$plant" = none ] || plant $name $plant
  kitswap $name; kitjake $name J1
  check "R4 N-3 with the agent's report $plant: recorded as $want, and J1 as expected (it decides nothing)" \
    "r['outcome']=='as_expected' and r['agent_reports']['P-A|N3']['verdict']=='$want'" "$WORK/$name.json"
  kitunswap $name
done
SETUP_PORT=$((P + 76)); KIT_NO_AGENT_REPLY=1 kitsetup r4unnamed; SETUP_PORT=
kitswap r4unnamed; kitjake r4unnamed J1
check "R4 no reply shape named at setup: N-3's report is unattributed (found, never matched), J1 as expected" \
  "r['outcome']=='as_expected' and r['agent_reports']['P-A|N3']['verdict']=='unattributed' and r['agent_reports']['P-A|N3']['found']" "$WORK/r4unnamed.json"
kitunswap r4unnamed
fi

if r168 R5; then
# R5: either UI rejected is a failed UI gate (exit 10).
for say in "J6-accept-launcher=changes" "J6-accept-tray=changes" "J6-accept-launcher=changes,J6-accept-tray=changes"; do
  name=r5$(echo "$say" | tr -cd 'a-z' | cut -c1-24); kitsetup $name
  JAKE_SIM_SAY="$say" kitjake $name J6
  check "R5 Jake says $say: the UI gate fails (exit $RC)" "r['outcome']!='as_expected' and '$RC'=='10'" "$WORK/$name.json"
done
fi

if r168 R6; then
# R6: any call X2 refuses fails its step or the run, whatever its kind, and between runs too.
kitsetup r6
( i=0; until grep -q "C0-models:" "$WORK/r6.err" 2>/dev/null || [ "$i" -ge 600 ]; do sleep 0.05; i=$((i + 1)); done
  "$WORK/r6/w/x2/room-cli" project attachment upload --json > /dev/null 2>&1 || true ) &
kitrun r6 C0,C1; wait
check "R6 an upload attempt (not a spawn or tell) refused by X2 during the run: the run stops (exit $RC)" "r['outcome']!='as_expected' and '$RC'=='10'" "$WORK/r6.json"
kitsetup r6b
kitrun r6b C0
"$WORK/r6b/w/x2/room-cli" thread log thr_syn_0102 --json --limit 5 > /dev/null 2>&1 || true
kitrun r6b C1
check "R6 a refusal between two runs of the sitting: the next run stops (exit $RC)" "r['outcome']!='as_expected' and 'refus' in r['stopped'] and '$RC'=='10'" "$WORK/r6b.json"
# Round 2: refusals are counted from setup, never acknowledged by starting the sitting.
kitsetup r6c
"$WORK/r6c/w/x2/room-cli" project attachment upload --json > /dev/null 2>&1 || true   # after settings, before the first run
kitrun r6c C0
check "R6 a refusal before the sitting's first run: that run stops at entry (exit $RC)" "r['outcome']!='as_expected' and 'refus' in r['stopped'] and '$RC'=='10'" "$WORK/r6c.json"
printf '#!/bin/sh\n[ -e "%s" ] || { : > "%s"; room-cli project attachment upload --json > /dev/null 2>&1; }\nexec "%s" "$@"\n' \
  "$WORK/r6d.once" "$WORK/r6d.once" "$OPENWIZ" > "$WORK/r6d-openwiz"; chmod 700 "$WORK/r6d-openwiz"
kitsetup r6d --openwiz "$WORK/r6d-openwiz"
check "R6 a call refused during settings (preparation): settings stops (exit 10), naming the refusal" "'refus' in r.get('stopped','')" "$WORK/r6d/settings.json"
rc=0; python3 "$KIT" settings --work "$WORK/r6d/w" > "$WORK/r6d-settings2.json" || rc=$?
check "R6 settings again in that sitting: still stops (exit $rc): the earlier refusal is never acknowledged" "'$rc'=='10' and 'refus' in r.get('stopped','')" "$WORK/r6d-settings2.json"
# Final round (the orchestrator's diagnosis): a refusal at the very end of a run, during the final
# snapshot (Sol's probe) or right before the report is published, taints the outcome too; and a
# tainted sitting arms no write again. The runs are this kit's own main(), one call of X2 injected.
for at in final-snapshot publish; do
  kitsetup r6$at
  python3 - "$KIT" "$WORK/r6$at/w" "$at" > "$WORK/r6$at-end.json" 2> "$WORK/r6$at-end.err" <<'PY' || true
import importlib.util, os, subprocess, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
work, at = sys.argv[2], sys.argv[3]
def stray():  # one call X2 refuses, as an asynchronous stray would make it
    subprocess.run([os.path.join(work, "x2", "room-cli"), "project", "attachment", "upload", "--json"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if at == "final-snapshot":
    real = kit.qc.lists
    def lists(ctx, name):
        if name == "end":
            stray()
        return real(ctx, name)
    kit.qc.lists = lists
else:
    real = kit.publish
    def publish(k, rep):
        stray()
        return real(k, rep)
    kit.publish = publish
rc = kit.main(["run", "--work", work, "--groups", "C0", "--settle", "0.3", "--late", "0.3", "--idle-timeout", "30",
               "--poll", "0.3", "--press-timeout", "30", "--min-judged", "3"])
sys.stderr.write("exit %d\n" % rc)
PY
  check "R6 a refusal $([ $at = publish ] && echo 'right before the report is published' || echo 'during the final snapshot (Sol'"'"'s end-of-run probe)'): $(tail -1 "$WORK/r6$at-end.err"), not as expected, the refusal named" \
    "r['outcome']=='not_as_expected' and r['x2_refusals']['count']==1 and 'refus' in r['stopped'] and open('$WORK/r6$at-end.err').read().strip().endswith('exit 10')" "$WORK/r6$at-end.json"
done
kitsetup r6g
"$WORK/r6g/w/x2/room-cli" project attachment upload --json > /dev/null 2>&1 || true
kitrun r6g C2
check "R6 a tainted sitting: X1 arms no write (C2 stops before arming, naming the taint)" "r['outcome']!='as_expected' and r['stopped'].startswith('C2-N1: incomplete: the sitting is tainted') and 'arms no write' in r['stopped']" "$WORK/r6g.json"
[ "$(fake_writes r6g spawn)" = 0 ] && ok "R6 the tainted sitting: no spawn reached the fake" || fail "R6 the tainted sitting: $(fake_writes r6g spawn) spawns"
# After the final round (Jake's (a)), Sol's held-write probe, through X1's own arm: C2-N1 armed
# with a hold before its call; another call refused during the hold taints the sitting; the held
# spawn is aborted after the hold, nothing reaches the fake, its reservation goes back (in the
# ledger and on the approval), and the taint stays.
kitsetup r6h
python3 - "$KIT" "$WORK/r6h/w" > "$WORK/r6h-held.json" 2> "$WORK/r6h-held.err" <<'PY' || true
import importlib.util, json, os, subprocess, sys
spec = importlib.util.spec_from_file_location("kit", sys.argv[1]); kit = importlib.util.module_from_spec(spec); spec.loader.exec_module(kit)
x = kit.Kit(sys.argv[2])
step = next(s for g in x.plan["groups"] for s in g["steps"] if s["id"] == "C2-N1")
h, m, e = kit.create_settings(x, step)
text = x.texts["N1"]
x.arm(step["id"], kit.write_for(x, step, "spawn", "P-A", {"provider": h, "model": m, "effort": e}, text),
      fault="hold-before", hold_s=2, ttl_s=15)
shim = os.path.join(x.x2, "room-cli")
p = subprocess.Popen([shim, "thread", "spawn", "--project", x.targets["P-A"], "--machine", "cloud", "--provider", h, "--model", m,
                      "--reasoning-level", e, "--request-id", "ow1-" + "4" * 40, "--json", "--prompt", text],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert kit.wait_for(lambda: os.path.exists(os.path.join(x.x2, "holding-before")), 10, 0.02)
up = subprocess.run([shim, "project", "attachment", "upload", "--json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
tainted = json.load(open(os.path.join(x.x2, "ledger.json"))).get("tainted")
out, _ = p.communicate(timeout=15)
led = json.load(open(os.path.join(x.x2, "ledger.json")))
appr = json.load(open(led["approval"])) if os.path.exists(str(led.get("approval"))) else {}
print(json.dumps({"upload_rc": up.returncode, "tainted_before_dispatch": tainted, "held_rc": p.returncode, "receipt": bool(out.strip()),
                  "outcomes": [json.loads(l)["outcome"] for l in open(os.path.join(x.x2, "writes.log"))],
                  "calls": (led["auth"].get("C2-N1") or {}).get("calls"), "tainted_after": led.get("tainted"),
                  "charges": [c.get("state") for c in appr.get("charges", []) if c.get("auth") == "C2-N1"]}))
PY
check "R6 Sol's held-write probe: a refusal during C2-N1's hold taints the sitting; the held spawn is aborted after it (exit 98), no receipt, its reservation back, the taint kept" \
  "r['upload_rc']==97 and r['tainted_before_dispatch'] is True and r['held_rc']==98 and not r['receipt'] and r['outcomes']==['holding','aborted_tainted'] and r['calls']==0 and r['tainted_after'] is True and r['charges']==['released']" "$WORK/r6h-held.json"
[ "$(fake_writes r6h spawn)" = 0 ] && ok "R6 Sol's held-write probe: no spawn reached the fake" || fail "R6 Sol's held-write probe: $(fake_writes r6h spawn) spawns"
fi

if r168 R7; then
# R7: an unauthenticated, otherwise valid create must meet Access, never the app.
SETUP_PORT=$((P + 72)); KIT_ACCESS_URL="http://127.0.0.1:$((P + 72))" kitsetup r7; SETUP_PORT=
kitswap r7
kitrun r7 W2
check "R7 no Access layer (the public URL is X1's own server): the owner-only proof fails" "r['outcome']!='as_expected' and r['stopped'].startswith('W2-probes')" "$WORK/r7.json"
kitunswap r7
# An "Access" that lets the request through to the app (minus its Origin): the app's own 403
# is in the edge's status set, so only the reached-the-app check can tell them apart.
( nohup python3 "$SCRIPTS/test/access-stub.py" $((P + 74)) $((P + 75)) > /dev/null 2>&1 < /dev/null & )
SETUP_PORT=$((P + 75)); KIT_ACCESS_URL="http://127.0.0.1:$((P + 74))" kitsetup r7fwd; SETUP_PORT=
kitswap r7fwd
kitrun r7fwd W2
check "R7 a request that reaches the app through a leaky edge (the app answers its own 403): the owner-only proof fails" "r['outcome']!='as_expected' and r['stopped'].startswith('W2-probes')" "$WORK/r7fwd.json"
kitunswap r7fwd
SETUP_PORT=$((P + 73)); kitsetup r7ok; SETUP_PORT=
kitswap r7ok
kitrun r7ok W2
check "R7 with the Access stand-in: a valid page-shaped create without a login gets Access's answer and never reaches the app" "r['outcome']=='as_expected' and r['groups'][0]['steps'][-1]['got']['probes']['public, no login'] in (302, 401, 403)" "$WORK/r7ok.json"
kitunswap r7ok
fi

if r168 R8; then
# R8 (Jake's (a)): L-8's allowance (4 creates, 2 sends) spans every sitting under the approval. It
# is kept in its own file, outside every sitting's work directory: X2 charges each write there, a
# fresh setup inherits only what's left, a charge goes back only when zero calls are proven, and
# only Jake amending the approval raises the total.
extraplan() { # extraplan <name> <msg...>: test-only creates C9-<msg> added to that sitting's plan
  n=$1; shift
  python3 - "$SCRIPTS/plan.json" "$WORK/$n/plan-extra.json" "$@" <<'PY' || true
import json, sys
p = json.load(open(sys.argv[1]))
extra = [{"id": "C9-%s" % m, "seq": i + 1, "do": "create", "msg": m, "harness": "codex",
          "expect": {"exit": 0, "status": "created", "attempts": 1, "calls": 1, "land": 1}} for i, m in enumerate(sys.argv[3:])]
p["groups"].append({"id": "C9", "claims": ["test only: creates past the allowance"], "steps": extra})
json.dump(p, open(sys.argv[2], "w"))
PY
  python3 -c "import json,sys; p=sys.argv[1]; c=json.load(open(p)); c['plan']=sys.argv[2]; json.dump(c, open(p,'w'))" "$WORK/$n/w/kit.json" "$WORK/$n/plan-extra.json" || true
}
rrsetup() { # rrsetup <name> [setup args]: a setup in rr's world, its exit in $RC
  mkdir -p "$WORK/$1"; cp "$WORK/rr/targets.env" "$WORK/$1/targets.env"; n=$1; shift; RC=0
  python3 "$KIT" setup --work "$WORK/$n/w" --room-cli "$WORK/rr/world/room-cli" --openwiz "$OPENWIZ" --targets "$WORK/$n/targets.env" \
    --files "$FILES" --contracts "$SOURCE_ROOT/contracts" --dry-run "$@" > "$WORK/$n.json" || RC=$?
}
rc=0; python3 "$KIT" approval init --approval "$WORK/r8a/approval.json" --creates 5 > "$WORK/r8a-init.json" || rc=$?
check "R8 an approval made with more than L-8's 4 creates: refused (exit $rc)" "'$rc'=='10' and 'amend' in r['stopped']" "$WORK/r8a-init.json"
[ ! -e "$WORK/r8a/approval.json" ] && ok "R8 init above L-8's totals: no approval file made" || fail "R8 init above L-8's totals: a file was made"
kitsetup rr
rc=0; python3 "$KIT" approval init --approval "$WORK/rr/approval.json" > "$WORK/rr-init2.json" || rc=$?
check "R8 an approval file is made once: init on it again is refused (exit $rc)" "'$rc'=='10' and 'once' in r['stopped']" "$WORK/rr-init2.json"
check "R8 setup: the approval's totals and what's left (4 creates, 2 sends), sitting 1, and the sitting's budget is what's left" \
  "r['approval']['total']=={'creates':4,'sends':2} and r['approval']['remaining']=={'creates':4,'sends':2} and r['approval']['sitting']==1 and r['budget']=={'creates':4,'sends':2}" "$WORK/rr/setup.json"
kitrun rr C2,C3,C4
check "R8 sitting 1: C2 to C4 as expected" "r['outcome']=='as_expected'" "$WORK/rr.json"
"$WORK/rr/w/x2/room-cli" project attachment upload --json > /dev/null 2>&1 || true   # sitting 1 tainted: a recovery is needed
rc=0; python3 "$KIT" approval show --approval "$WORK/rr/approval.json" > "$WORK/rr-show.json" || rc=$?
check "R8 before any recovery, the cumulative totals and what's left: 3 creates charged (N-1, N-2, N-4, each by step and sitting), 1 create and 2 sends left" \
  "'$rc'=='0' and r['approval']['charged']=={'creates':3,'sends':0} and r['approval']['remaining']=={'creates':1,'sends':2} and sorted((m['step'],m['sitting']) for m in r['approval']['made'])==[('C2-N1',1),('C3-N2',1),('C4-N4',1)]" "$WORK/rr-show.json"
grep -qE 'prj_syn|thr_syn|ow1-|op-acc-|/tmp/' "$WORK/rr-show.json" && fail "R8 the approval's report: an id, op id or path printed" || ok "R8 the approval's report: no id, op id or path printed"
rrsetup rr0
check "R8 a setup naming no approval: refused (exit $RC)" "'$RC'=='10' and '--approval' in r['stopped']" "$WORK/rr0.json"
rrsetup rr0b --approval "$WORK/rr0b/none.json"
check "R8 a setup naming an approval file that doesn't exist: refused (exit $RC); setup never makes one" "'$RC'=='10' and 'approval' in r['stopped']" "$WORK/rr0b.json"
rrsetup rr0c --approval "$WORK/rr/approval.json" --budget-creates 2
check "R8 a fresh setup asking for more than is left (2 creates, 1 left): refused (exit $RC)" "'$RC'=='10' and 'left' in r['stopped']" "$WORK/rr0c.json"
[ ! -e "$WORK/rr0/w" ] && [ ! -e "$WORK/rr0b/w" ] && [ ! -e "$WORK/rr0b/none.json" ] && [ ! -e "$WORK/rr0c/w" ] \
  && ok "R8 the refused setups made no work directory and no approval file" || fail "R8 a refused setup made something"
KIT_FROM=rr kitsetup rr2; unset KIT_FROM
check "R8 a fresh setup under the same approval inherits only what's left: 1 create, 2 sends; sitting 2" \
  "r['budget']=={'creates':1,'sends':2} and r['approval']['remaining']=={'creates':1,'sends':2} and r['approval']['sitting']==2" "$WORK/rr2/setup.json"
kitrun rr2 C2,C3
check "R8 Sol's recovery: the fresh sitting never repeats a completed create: C2 stops before arming, naming C2-N1 made in sitting 1; X2 refused nothing" \
  "r['outcome']!='as_expected' and r['stopped'].startswith('C2-N1') and 'under this approval' in r['stopped'] and 'sitting 1' in r['stopped'] and r['x2_refusals']['count']==0" "$WORK/rr2.json"
[ "$(fake_writes rr spawn)" = 3 ] && ok "R8 Sol's recovery: 3 spawns across both sittings, none repeated" || fail "R8 Sol's recovery: $(fake_writes rr spawn) spawns"
KIT_FROM=rr kitsetup rr3; unset KIT_FROM   # set up before sitting 2 uses its create: it inherits 1 too
extraplan rr2 N5 N6; extraplan rr3 N6
kitrun rr2 C9
check "R8 the one create left: sitting 2 makes C9-N5; C9-N6 then stops before arming" "r['stopped'].startswith('C9-N6') and 'budget' in r['stopped']" "$WORK/rr2.json"
kitrun rr3 C9
check "R8 sitting 3, set up with 1 create inherited: C9-N6 stops before arming, the approval's allowance used up by sitting 2" \
  "r['outcome']!='as_expected' and r['stopped'].startswith('C9-N6') and 'allowance' in r['stopped'] and r['x2_refusals']['count']==0" "$WORK/rr3.json"
[ "$(fake_writes rr spawn)" = 4 ] && ok "R8 L-8's 4 creates across three sittings: exactly 4 spawns" || fail "R8 across three sittings: $(fake_writes rr spawn) spawns"
rc=0; python3 "$KIT" approval amend --approval "$WORK/rr/approval.json" --creates 5 --sends 2 > "$WORK/rr-amend0.json" || rc=$?
check "R8 raising the total without Jake's own words: refused (exit $rc)" "'$rc'=='10' and 'Jake' in r['stopped']" "$WORK/rr-amend0.json"
rc=0; python3 "$KIT" approval amend --approval "$WORK/rr/approval.json" --creates 5 --sends 2 --jake-said "synthetic words: one more create is fine" > "$WORK/rr-amend.json" || rc=$?
check "R8 Jake amending the approval raises the total: 5 creates, 1 left; recorded, his words never printed" \
  "'$rc'=='0' and r['approval']['total']=={'creates':5,'sends':2} and r['approval']['remaining']=={'creates':1,'sends':2} and r['approval']['amendments']==1 and 'synthetic words' not in json.dumps(r)" "$WORK/rr-amend.json"
grep -q "synthetic words: one more create is fine" "$WORK/rr/approval.json" && ok "R8 the amendment keeps Jake's words in the approval file (on the Mac only)" || fail "R8 the amendment's words"
kitrun rr3 C9
check "R8 after Jake's amendment, sitting 3 makes the one more create" "r['outcome']=='as_expected'" "$WORK/rr3.json"
rc=0; python3 "$KIT" approval show --approval "$WORK/rr/approval.json" > "$WORK/rr-show2.json" || rc=$?
check "R8 the approval keeps every made write by step and sitting: N-1, N-2, N-4 (1), N-5 (2), N-6 (3); nothing left" \
  "sorted((m['step'],m['sitting']) for m in r['approval']['made'])==[('C2-N1',1),('C3-N2',1),('C4-N4',1),('C9-N5',2),('C9-N6',3)] and r['approval']['remaining']=={'creates':0,'sends':2}" "$WORK/rr-show2.json"
[ "$(fake_writes rr spawn)" = 5 ] && ok "R8 after the amendment: exactly 5 spawns in all" || fail "R8 after the amendment: $(fake_writes rr spawn) spawns"
fi
fi

echo
[ "$FAILED" = 0 ] && echo "kit tests: all passed (synthetic; not a live result)" || { echo "kit tests: FAILED"; exit 1; }
