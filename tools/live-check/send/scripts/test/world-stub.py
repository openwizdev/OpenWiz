#!/usr/bin/env python3
"""Test-only stand-in for room-cli with test threads that react to sends.
SYNTHETIC ONLY; NOT A LIVE RESULT.

Installed as `<D>/room-cli`. It answers in front of two fakes, so their own
checks stay in force:
- every read is passed to 0.0.1's observer stub (`<D>/obs/room-cli`, which
  answers thread log, thread count and --help for the other sessions and hands
  OpenWiz's reads to the repository's fake), and a test thread's rows are then
  overlaid with its simulated state;
- every `thread tell` is run by the repository's fake (its exact-shape check
  and its tell counter), from a fresh directory whose scenario holds the one
  answer the simulated state gives, in the receipt shapes observed live in #10:
  sent, queued behind a turn, or a steer without steering queued (the
  placeholder unsupported-mode rejection only when planted).

The test threads (`<D>/world-threads.json`: id -> {"steer": bool, "like": id,
"cloud": bool})
are new sessions, added to every list and answered by `thread show` from the
row and record of the fixture session they are `like`, with their own id and a
synthetic title. They start empty and idle. A delivered message starts a turn: `sleep 120` texts last
`sleep_ms`, others `short_ms` (`<D>/world-config.json`). A queue-mode tell to a
busy thread is queued (a queue row) and delivered when the turn ends. A steer
to a busy thread with steering joins it. `thread log` and `thread queue list`
of a test thread are answered here; the event and row shapes are synthetic.

Planted faults (`<D>/world-plant`, one word per line), to show the kit's
stop rules work:
- misroute: a tell to the first test thread lands in the second one;
- prefix: a delivered text arrives with "-- " in front;
- refuse-steer: a steer to a thread without steering is refused with the
  placeholder unsupported-mode rejection (0.43.1 queues it: observed in #10);
- steer-sent: a steer to a busy thread without steering is sent, as room-cli
  v141 did in #10's sitting 2 (receipt delivery sent, mode steer);
- touch-sample: every tell also moves thr_syn_0001's lastReadAt (a change
  outside the test threads);
- busy-stuck: a test thread never becomes idle again;
- touch-recent: every tell also moves the recent thr_syn_0004's lastReadAt (Jake
  working in his own session: reported, never judged);
- appear: from the first tell on, a new session thr_syn_0201 is listed (a thread
  Jake or a Loop starts during the run: reported, never judged).

- cold-pending: the first tell sets the cold thr_syn_0005's hasPendingInteraction;
  every later tell moves its lastReadAt (Sol R3: a judged session must stay judged);
- dup-late: every delivered message is delivered a second time `dup_ms` later
  (Sol R5: a duplicate that arrives after the landing check);
- title-nonascii: thr_syn_0005's title is non-ASCII (Sol R4).

`recent` in world-config.json maps a session id to an updatedAt (ms): that
session looks like one Jake used in the last hours.
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
STATE = os.path.join(HERE, "world.json")
FIXTURES = os.environ.get("WORLD_FIXTURES") or open(os.path.join(HERE, "world-fixtures")).read().strip()
UNSUPPORTED = "Error: HTTP 400: Unsupported mode"


def now_ms():
    return time.time_ns() // 1_000_000


def cfg():
    with open(os.path.join(HERE, "world-config.json")) as f:
        return json.load(f)


def plants():
    p = os.path.join(HERE, "world-plant")
    return set(open(p).read().split()) if os.path.exists(p) else set()


def threads():
    with open(os.path.join(HERE, "world-threads.json")) as f:
        return json.load(f)


class World:
    def __enter__(self):
        self.lock = open(STATE + ".lock", "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.s = json.load(open(STATE)) if os.path.exists(STATE) else {"threads": {}, "seq": 0}
        for tid in threads():
            self.s["threads"].setdefault(tid, {"events": [], "queue": [], "busy_until": 0,
                                               "reply_due": None, "updated": 1700000590000})
        self.advance(now_ms())
        return self

    def __exit__(self, *exc):
        with open(STATE + ".tmp", "w") as f:
            json.dump(self.s, f)
        os.replace(STATE + ".tmp", STATE)
        self.lock.close()

    def turn_ms(self, text):
        c = cfg()
        return c["sleep_ms"] if "sleep 120" in text else c["short_ms"]

    def event(self, tid, at, kind, text=None):
        t = self.s["threads"][tid]
        seq = len(t["events"]) + 1
        data = {"source": "syn-source", "initiator": "syn-initiator"}
        if text is not None:
            data["input"] = text
        t["events"].append({"id": "syn-event-%s-%d" % (tid[-4:], seq), "scope": {"kind": "syn-thread"},
                            "threadId": tid, "seq": seq, "createdAt": at, "type": kind, "data": data})
        t["updated"] = max(t["updated"], at)

    def deliver(self, tid, text, at, dup=True):
        if "prefix" in plants():
            text = "-- " + text
        if dup and "dup-late" in plants():
            self.s.setdefault("dups", []).append({"tid": tid, "text": text, "at": at + cfg().get("dup_ms", 1500)})
        self.event(tid, at, "syn-user-message", text)
        t = self.s["threads"][tid]
        t["busy_until"] = at + self.turn_ms(text)
        t["reply_due"] = t["busy_until"]

    def advance(self, now):
        for d in [d for d in self.s.get("dups", []) if d["at"] <= now]:
            self.s["dups"].remove(d)
            self.event(d["tid"], d["at"], "syn-user-message", d["text"])
        for tid, t in self.s["threads"].items():
            while True:
                if "busy-stuck" in plants() and t["busy_until"]:
                    t["busy_until"] = now + 60000
                    break
                if t["reply_due"] is not None and t["reply_due"] <= now:
                    self.event(tid, t["reply_due"], "syn-agent-message")
                    t["reply_due"] = None
                if t["busy_until"] <= now and t["queue"]:
                    q = t["queue"].pop(0)
                    self.deliver(tid, q["text"], max(t["busy_until"], q["at"]))
                    continue
                break

    def busy(self, tid, now):
        return self.s["threads"][tid]["busy_until"] > now


def run_fake(argv, response):
    """The repository's fake, from a fresh directory holding only this answer."""
    d = tempfile.mkdtemp(prefix="tell-", dir=HERE)
    try:
        os.symlink(os.readlink(os.path.join(HERE, "obs", "room-cli-fake")), os.path.join(d, "room-cli"))
        scen = dict(scenario="world-tell", responses=[dict(response, argv=argv[:-1], any_text=True)])
        with open(os.path.join(d, "scenario.json"), "w") as f:
            json.dump(scen, f)
        with open(os.path.join(d, "fake-room-cli.scenario"), "w") as f:
            f.write(os.path.join(d, "scenario.json"))
        p = subprocess.run([os.path.join(d, "room-cli")] + argv, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open(os.path.join(HERE, "fake-tells.log"), "a") as f:
            f.write(json.dumps({"exit": p.returncode}) + "\n")
        return p
    finally:
        shutil.rmtree(d, ignore_errors=True)


def tell(argv):
    tid, mode, text = argv[2], argv[4], argv[7]
    tt = threads()
    with World() as w:
        now = now_ms()
        if tid not in tt:
            return run_fake(argv, {"stderr": "Error: HTTP 404: Thread not found", "exit": 1})
        land = tid
        if "misroute" in plants():
            ids = sorted(tt)
            land = ids[1] if tid == ids[0] else tid
        t = w.s["threads"][land]
        if "touch-sample" in plants():
            w.s["touched"] = w.s.get("touched", 0) + 1
        if "touch-recent" in plants():
            w.s["touched_recent"] = w.s.get("touched_recent", 0) + 1
        if "appear" in plants():
            w.s["appeared"] = True
        if "cold-pending" in plants():
            w.s["cold_tells"] = w.s.get("cold_tells", 0) + 1
        if mode == "steer" and not tt[tid]["steer"] and "refuse-steer" in plants():
            return run_fake(argv, {"stderr": UNSUPPORTED, "exit": 1})
        # The receipts are the shapes observed live in #10 (2026-11-02), each naming the
        # requested thread and mode, as room-cli 0.43.1 did.
        queue_steer = mode == "steer" and not tt[tid]["steer"] and "steer-sent" not in plants()
        if (w.busy(land, now) and mode == "queue") or queue_steer:
            w.s["seq"] += 1
            # A Cloud thread's queued receipt has a UUID id, waitingOn null and no hardQueue,
            # whatever the mode (room-cli v141, #10 sitting 2: W1-M08, and 0.43.1's steer probe);
            # a Local thread's has a qmsg_ id and waitingOn thread-busy.
            cloud = mode == "steer" or tt[tid].get("cloud", False)
            qid = ("00000000-0000-4000-8000-%012d" if cloud else "qmsg_syn_q%04d") % w.s["seq"]
            t["queue"].append({"id": qid, "text": text, "at": now})
            name = "tell-steer-queued-observed.json" if cloud else "tell-queued-observed.json"
            receipt = json.load(open(os.path.join(FIXTURES, name)))
            receipt["threadId"] = receipt["queuedMessage"]["threadId"] = tid
            receipt["mode"] = mode
            receipt["queuedMessage"]["id"] = qid
            return run_fake(argv, {"stdout": json.dumps(receipt), "exit": 0})
        if w.busy(land, now):  # steer, with steering: joins the running turn
            w.event(land, now, "syn-user-message", ("-- " + text) if "prefix" in plants() else text)
        else:
            w.deliver(land, text, now)
        receipt = json.load(open(os.path.join(FIXTURES, "tell-sent-observed.json")))
        receipt.update(threadId=tid, mode=mode)
        return run_fake(argv, {"stdout": json.dumps(receipt), "exit": 0})


def overlay(row, t, now, show):
    busy = t["busy_until"] > now
    status = "active" if busy else "idle"
    if show:
        row["status"] = status
        row["queuedMessageCount"] = len(t["queue"])
        row.setdefault("runtime", {})["displayStatus"] = status
    else:
        row["status"] = status
        row.setdefault("runtime", {})["displayStatus"] = status
        row["queuedWork"] = "waiting" if t["queue"] else "none"
    row["updatedAt"] = t["updated"]
    row["latestAttentionAt"] = t["updated"]


def obs(argv):
    return subprocess.run([sys.executable, os.path.join(HERE, "obs", "room-cli")] + argv, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def passthrough(p):
    sys.stdout.buffer.write(p.stdout)
    sys.stderr.buffer.write(p.stderr)
    sys.stdout.flush()
    return p.returncode


def main():
    a = sys.argv[1:]
    with open(os.path.join(HERE, "world-calls.log"), "a") as f:
        f.write(json.dumps(a[:2] + [x for x in a[2:] if x.startswith("-")]) + "\n")
    tt = threads()
    if a[:2] == ["thread", "tell"] and len(a) == 8:
        return passthrough(tell(a))
    if a[:2] == ["thread", "tell"] and a[2:] == ["--help"]:
        print("Usage: room-cli thread tell <id> [--mode queue|steer|auto] [--json] [--] <message>\n"
              "Synthetic help text for the kit's tests.")
        return 0
    if a[:3] == ["thread", "queue", "list"] and len(a) == 5 and a[4] == "--json" and a[3] in tt:
        with World() as w:
            rows = [{"id": q["id"], "waitingOn": {"kind": "thread-busy"}, "text": q["text"]}
                    for q in w.s["threads"][a[3]]["queue"]]
        print(json.dumps(rows))
        return 0
    if a[:2] == ["thread", "log"] and len(a) >= 3 and a[2] in tt:
        after = int(a[a.index("--after-seq") + 1]) if "--after-seq" in a else 0
        limit = int(a[a.index("--limit") + 1])
        with World() as w:
            ev = [e for e in w.s["threads"][a[2]]["events"] if e["seq"] > after][:limit]
        print(json.dumps(ev))
        return 0
    if a[:2] == ["thread", "show"] and len(a) == 4 and a[2] in tt:
        p = obs(["thread", "show", tt[a[2]]["like"], "--json"])
        if p.returncode != 0:
            return passthrough(p)
        doc = json.loads(p.stdout)
        doc["thread"].update(id=a[2], title="Synthetic test thread", createdAt=1700000580000)
        if isinstance(doc.get("environment"), dict) and doc["environment"].get("hostId"):
            doc["environment"]["hostId"] = "mch_syn_0001"  # a connected machine
        with World() as w:
            overlay(doc["thread"], w.s["threads"][a[2]], now_ms(), True)
        print(json.dumps(doc))
        return 0
    if a == ["thread", "count", "--json"]:
        p = obs(a)
        doc = json.loads(p.stdout)
        doc["total"] += len(tt)  # every test thread is in the default view
        with World() as w:
            doc["total"] += 1 if w.s.get("appeared") else 0
        print(json.dumps(doc))
        return 0
    if a[:2] == ["thread", "output"] and len(a) == 4 and a[2] in tt:
        return passthrough(obs(["thread", "output", tt[a[2]]["like"], "--json"]))
    if a[:3] == ["thread", "list", "--json"]:
        p = obs(a)
        if p.returncode != 0:
            return passthrough(p)
        rows = json.loads(p.stdout)
        like = {r.get("id"): r for r in rows if isinstance(r, dict)}
        recent = cfg().get("recent", {})
        with World() as w:
            touched = w.s.get("touched", 0)
            cold = w.s.get("cold_tells", 0)
            for r in rows:
                if r.get("id") == "thr_syn_0001" and touched:
                    r["lastReadAt"] = r["lastReadAt"] + touched
                if r.get("id") == "thr_syn_0005" and cold:
                    r["hasPendingInteraction"] = True
                    r["lastReadAt"] = r["lastReadAt"] + cold - 1
                if r.get("id") == "thr_syn_0005" and "title-nonascii" in plants():
                    r["title"] = "\u79d8\u5bc6\u4f1a\u8b70 synthetic"
                if r.get("id") in cfg().get("titles", {}):  # Sol R4, round 2: titles a test sets
                    r["title"] = cfg()["titles"][r["id"]]
                if r.get("id") in recent:
                    r["updatedAt"] = recent[r["id"]]
                    r["lastReadAt"] = recent[r["id"]] + w.s.get("touched_recent", 0)
            if w.s.get("appeared") and "thr_syn_0005" in like:
                n = json.loads(json.dumps(like["thr_syn_0005"]))
                n.update(id="thr_syn_0201", title="Synthetic new session", updatedAt=now_ms() // 60000 * 60000)
                rows.append(n)
            for tid in sorted(tt, reverse=True):
                base = like.get(tt[tid]["like"])
                if base is None:
                    continue  # the template is not in this view
                r = json.loads(json.dumps(base))
                r.update(id=tid, title="Synthetic test thread", createdAt=1700000580000)
                if r.get("environmentHostId"):
                    r["environmentHostId"] = "mch_syn_0001"  # a connected machine
                overlay(r, w.s["threads"][tid], now_ms(), False)
                rows.insert(0, r)
        print(json.dumps(rows))
        return 0
    return passthrough(obs(a))


if __name__ == "__main__":
    sys.exit(main())
