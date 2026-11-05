#!/usr/bin/env python3
"""Test-only stand-in for room-cli with a project and test threads that react to
OpenWiz 0.0.4's writes. SYNTHETIC ONLY; NOT A LIVE RESULT.

Adapted from 0.0.3's kit (PR #152 at 3a7b501, scripts/test/world-stub.py). Installed
as `<D>/room-cli`. It answers in front of two fakes, so their own checks stay in force:
- every read is passed to 0.0.1's observer stub (`<D>/obs/room-cli`, which answers
  thread log and --help for the fixture sessions and hands OpenWiz's reads to the
  repository's fake), and the project, the test threads and the new threads are
  then overlaid;
- every `thread spawn` and `thread tell` is run by the repository's fake (its
  exact-shape check, its counters, its request-ID table and its attachment upload),
  from a directory whose scenario holds the one answer the world gives.

The world (all synthetic):
- **Projects:** the fixture's projects (their remotes are not GitHub), plus P-A
  `prj_syn_0301` (standard, a synthetic GitHub remote) and `prj_syn_0302` (standard,
  no remote). `cloud status --json` is the v127 fixture catalogue.
- **Test threads** (`<D>/world-threads.json`: id -> {"like": id}): 0.0.3's T-A (Local,
  like thr_syn_0004) and T-B (Cloud, like thr_syn_0005), idle with one old event.
- **A spawn** with a new request id makes one new thread in its project, numbered
  thr_syn_0401 and up: pending, then starting after `start_ms`, then active for
  `short_ms`, then idle. Its first event is the user message carrying the prompt
  (and, with attachments, an `attachments` list of name and SHA-256). The agent's
  reply follows: when the prompt asks for SHA-256, it lists the SHA-256 of every
  attached file as the fake uploaded it; otherwise "ok". The same request id with
  the same content makes nothing new and answers the same receipt; with other
  content the fake refuses it (409).
- **A tell** to a test thread delivers the text (and attachments) as one user message
  and a reply, as above; a tell to a busy thread is queued and delivered after it.

Planted faults (`<D>/world-plant`, one word per line), to show the kit's stop rules:
- spawn-twice: a spawn makes two threads in its project;
- wrong-project: a spawn's thread lands in prj_syn_0001 (the receipt still names
  the project asked for);
- wrong-model: a new thread reports another model (thread show's execution.model);
- prompt-prefix: a delivered prompt or message arrives with "-- " in front;
- stuck-pending: a new thread never leaves pending;
- bad-hash: the agent reports a different SHA-256 for every attachment;
- no-report: the agent's reply holds no SHA-256;
- misroute: a tell to T-B lands on T-A;
- touch-outside: every write also moves the cold thr_syn_0008's lastReadAt, outside P-A
  (the factory working while the check runs: recorded, never judged; #13, 2026-11-05);
- touch-sample: every write also moves thr_syn_0001's lastReadAt (a change outside
  the test's own threads);
- touch-recent: every write also moves the recent thr_syn_0004's lastReadAt (Jake
  working in his own session: reported, never judged);
- appear: from the first write on, a new session thr_syn_0201 is listed in another
  project (a thread Jake or a Loop starts during the run: reported, never judged);
- jake-in-pa: from the first write on, a thread nobody's step made appears in P-A;
- cold-pending: the first write sets the cold thr_syn_0005's hasPendingInteraction;
- dup-late: every delivered message is delivered a second time `dup_ms` later;
- catalogue-drift: cloud status's `ready` is a string;
- pa-busy: P-A holds a running thread before anything is created (work in flight);
- help-no-request-id: thread spawn's help no longer lists --request-id.

`recent` in world-config.json maps a session id to an updatedAt (ms): that session
looks like one Jake used in the last hours. `recent_in_pa` (the plan fixture only)
places those quiet recent rows in P-A, so the 48 h guard is exercised inside its
judging scope; this is synthetic test data, never a live observation. `titles` maps an id to a title a test sets.
"""

import fcntl
import hashlib
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
FIX = open(os.path.join(HERE, "world-fixtures")).read().strip()  # tests/fixtures
V127 = os.path.join(FIX, "room-cli-v127", "new-thread")
SEND = os.path.join(FIX, "room-cli-0.43.1", "send")
P_A, P_N = "prj_syn_0301", "prj_syn_0302"
PA_COLD = ("thr_syn_0001", "thr_syn_0005", "thr_syn_0007")  # cold sessions listed in P-A (the brackets judge these)


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


def project(pid, name, remote):
    return {"id": pid, "kind": "standard", "name": name, "gitRemoteUrl": remote,
            "createdAt": 1699100600000, "updatedAt": 1699200600000, "sources": []}


class World:
    def __enter__(self):
        self.lock = open(STATE + ".lock", "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.s = json.load(open(STATE)) if os.path.exists(STATE) else {"threads": {}, "seq": 0, "new": {},
                                                                        "rids": {}, "next": 401}
        for tid in threads():
            if tid not in self.s["threads"]:
                self.s["threads"][tid] = {"events": [], "queue": [], "busy_until": 0, "reply_due": None,
                                          "reply": None, "updated": 1700000590000}
                self.event(tid, 1700000590000, "syn-old-event", "Synthetic earlier message")
        self.advance(now_ms())
        return self

    def __exit__(self, *exc):
        with open(STATE + ".tmp", "w") as f:
            json.dump(self.s, f)
        os.replace(STATE + ".tmp", STATE)
        self.lock.close()

    def event(self, tid, at, kind, text=None, attachments=None):
        t = self.s["threads"][tid]
        seq = len(t["events"]) + 1
        data = {"source": "syn-source", "initiator": "syn-initiator"}
        if text is not None:
            data["input"] = text
        if attachments:
            data["attachments"] = [{"name": a["name"], "sha256": a["sha256"]} for a in attachments]
        t["events"].append({"id": "syn-event-%s-%d" % (tid[-4:], seq), "scope": {"kind": "syn-thread"},
                            "threadId": tid, "seq": seq, "createdAt": at, "type": kind, "data": data})
        t["updated"] = max(t["updated"], at)

    def reply_text(self, text, attachments):
        if "SHA-256" not in text or "no-report" in plants():
            return "Synthetic reply: ok"
        hashes = []
        for a in attachments:
            h = a["sha256"]
            if "bad-hash" in plants():
                h = hashlib.sha256(h.encode()).hexdigest()
            hashes.append("%s %s" % (a["name"], h))
        return "Synthetic reply: " + "; ".join(hashes)

    def deliver(self, tid, text, at, attachments=(), dup=True):
        if "prefix" in plants() or "prompt-prefix" in plants():
            text = "-- " + text
        if dup and "dup-late" in plants():
            self.s.setdefault("dups", []).append({"tid": tid, "text": text, "at": at + cfg().get("dup_ms", 1500)})
        self.event(tid, at, "syn-user-message", text, list(attachments))
        t = self.s["threads"][tid]
        t["busy_until"] = at + cfg()["short_ms"]
        t["reply_due"] = t["busy_until"]
        t["reply"] = self.reply_text(text, attachments)

    def advance(self, now):
        for d in [d for d in self.s.get("dups", []) if d["at"] <= now]:
            self.s["dups"].remove(d)
            self.event(d["tid"], d["at"], "syn-user-message", d["text"])
        for tid, t in self.s["threads"].items():
            n = self.s["new"].get(tid)
            if n is not None and n.get("first") is not None and now >= n["created"] + cfg()["start_ms"] \
                    and "stuck-pending" not in plants():
                first = n.pop("first")
                self.deliver(tid, first["text"], n["created"] + cfg()["start_ms"], first["attachments"])
            while True:
                if t["reply_due"] is not None and t["reply_due"] <= now:
                    self.event(tid, t["reply_due"], "syn-agent-message", t.get("reply") or "Synthetic reply: ok")
                    t["reply_due"] = None
                if t["busy_until"] <= now and t["queue"]:
                    q = t["queue"].pop(0)
                    self.deliver(tid, q["text"], max(t["busy_until"], q["at"]), q.get("attachments", []))
                    continue
                break

    def busy(self, tid, now):
        return self.s["threads"][tid]["busy_until"] > now

    def status(self, tid, now):
        n = self.s["new"].get(tid)
        if n is not None and (n.get("first") is not None):
            return "pending" if now < n["created"] + cfg()["start_ms"] // 2 or "stuck-pending" in plants() \
                else "starting"
        return "active" if self.busy(tid, now) else "idle"


def run_fake(argv, response, where=None):
    """The repository's fake, from its own directory holding only this answer.
    `where`: a directory that persists between calls (the spawn table)."""
    d = where or tempfile.mkdtemp(prefix="write-", dir=HERE)
    try:
        link = os.path.join(d, "room-cli")
        if not os.path.exists(link):
            os.symlink(os.readlink(os.path.join(HERE, "obs", "room-cli-fake")), link)
        scen = dict(scenario="world-write", responses=[response])
        with open(os.path.join(d, "scenario.json"), "w") as f:
            json.dump(scen, f)
        with open(os.path.join(d, "fake-room-cli.scenario"), "w") as f:
            f.write(os.path.join(d, "scenario.json"))
        p = subprocess.run([link] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open(os.path.join(HERE, "fake-writes.log"), "a") as f:
            f.write(json.dumps({"kind": argv[1], "exit": p.returncode}) + "\n")
        return p
    finally:
        if where is None:
            shutil.rmtree(d, ignore_errors=True)


def attachments_of(argv, start, end):
    """The (flag, path) pairs between start and end, with each file's name and SHA-256
    read now (what the fake's upload reads at the same moment)."""
    out = []
    for flag, path in zip(argv[start:end:2], argv[start + 1:end:2]):
        try:
            digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        except OSError:
            digest = None
        out.append({"flag": flag, "name": os.path.basename(path), "sha256": digest})
    return out


def touch(w):
    for word, key in (("touch-sample", "touched"), ("touch-recent", "touched_recent"), ("cold-pending", "cold"),
                      ("touch-outside", "touched_outside")):
        if word in plants():
            w.s[key] = w.s.get(key, 0) + 1
    if "appear" in plants():
        w.s["appeared"] = True
    if "jake-in-pa" in plants():
        w.s["jake_pa"] = True


def new_thread(w, project, provider, model, effort, text, attachments, now):
    tid = "thr_syn_%04d" % w.s["next"]
    w.s["next"] += 1
    w.s["threads"][tid] = {"events": [], "queue": [], "busy_until": 0, "reply_due": None, "reply": None,
                           "updated": now}
    w.s["new"][tid] = {"project": project, "provider": provider, "model": model, "effort": effort,
                       "created": now, "first": {"text": text, "attachments": attachments}}
    return tid


def spawn(argv):
    project, provider, model, effort, rid, text = argv[3], argv[7], argv[9], argv[11], argv[13], argv[-1]
    json_at = argv.index("--json")
    attachments = attachments_of(argv, json_at + 1, len(argv) - 2)
    with World() as w:
        now = now_ms()
        known = w.s["rids"].get(rid)
        tid = known["thread"] if known else "thr_syn_%04d" % w.s["next"]
        receipt = json.load(open(os.path.join(V127, "spawn-receipt-created.json")))
        receipt.update(id=tid, projectId=project, providerId=provider, createdAt=now, updatedAt=now,
                       latestAttentionAt=now, title="Synthetic new thread %s" % tid[-4:])
        # The fake first: its exact-shape check, its request-ID table (the same id with
        # other content is refused, 409) and its upload of every attachment.
        p = run_fake(argv, {"any_spawn": True, "creates": True, "stdout": json.dumps(receipt)},
                     where=os.path.join(HERE, "spawn"))
        if p.returncode == 0 and known is None:
            lands = "prj_syn_0001" if "wrong-project" in plants() else project
            new_thread(w, lands, provider, model, effort, text, attachments, now)
            if "spawn-twice" in plants():
                new_thread(w, lands, provider, model, effort, text, attachments, now)
            w.s["rids"][rid] = {"thread": tid}
            touch(w)
        return p


def tell(argv):
    tid, mode, text = argv[2], argv[4], argv[-1]
    attachments = attachments_of(argv, 6, len(argv) - 2)
    tt = threads()
    with World() as w:
        now = now_ms()
        if tid not in tt and tid not in w.s["new"]:
            return run_fake(argv, {"argv": argv, "stderr": "Error: HTTP 404: Thread not found", "exit": 1})
        land = sorted(tt)[0] if "misroute" in plants() and tid == sorted(tt)[1] else tid
        t = w.s["threads"][land]
        touch(w)
        if w.busy(land, now) and mode == "queue":
            w.s["seq"] += 1
            qid = "qmsg_syn_%04d" % w.s["seq"]
            t["queue"].append({"id": qid, "text": text, "at": now, "attachments": attachments})
            receipt = json.load(open(os.path.join(SEND, "tell-queued-observed.json")))
            receipt.update(threadId=tid, mode=mode)
            receipt["queuedMessage"].update(id=qid, threadId=tid)
            return run_fake(argv, {"argv": argv, "stdout": json.dumps(receipt), "exit": 0})
        w.deliver(land, text, now, attachments)
        receipt = json.load(open(os.path.join(SEND, "tell-sent-observed.json")))
        receipt.update(threadId=tid, mode=mode)
        return run_fake(argv, {"argv": argv, "stdout": json.dumps(receipt), "exit": 0})


def overlay(row, t, status, show):
    row["status"] = status
    row.setdefault("runtime", {})["displayStatus"] = "idle" if status == "idle" else "active"
    if show:
        row["queuedMessageCount"] = len(t["queue"])
    else:
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


def new_row(w, tid, now):
    n = w.s["new"][tid]
    r = json.load(open(os.path.join(V127, "thread-list.json")))[0]
    r.update(id=tid, projectId=n["project"], providerId=n["provider"], title="Synthetic new thread %s" % tid[-4:],
             createdAt=n["created"], lastReadAt=None)
    overlay(r, w.s["threads"][tid], w.status(tid, now), False)
    return r


def show_new(w, tid, now):
    n = w.s["new"][tid]
    doc = json.load(open(os.path.join(V127, "thread-show-idle.json")))
    doc["thread"].update(id=tid, projectId=n["project"], providerId=n["provider"], createdAt=n["created"],
                         title="Synthetic new thread %s" % tid[-4:])
    overlay(doc["thread"], w.s["threads"][tid], w.status(tid, now), True)
    model = ("syn-other-model" if "wrong-model" in plants() else n["model"])
    doc["execution"] = {"model": model, "reasoningLevel": n["effort"]}
    return doc


def main():
    a = sys.argv[1:]
    with open(os.path.join(HERE, "world-calls.log"), "a") as f:
        f.write(json.dumps(a[:2] + [x for x in a[2:] if x.startswith("-")]) + "\n")
    tt = threads()
    if a[:2] == ["thread", "spawn"] and len(a) >= 17 and "--help" not in a:
        return passthrough(spawn(a))
    if a[:2] == ["thread", "tell"] and len(a) >= 8 and "--help" not in a:
        return passthrough(tell(a))
    if a[:2] in (["thread", "tell"], ["thread", "spawn"]) and a[2:] == ["--help"]:
        text = {"tell": "Usage: room-cli thread tell <id> [--mode queue|steer|auto] [--json] [--file <path>]..."
                        " [--image <path>]... [--] <message>",
                "spawn": "Usage: room-cli thread spawn --project <id> --machine local|cloud --provider <id>"
                         " [--model <m>] [--reasoning-level <l>] [--request-id <id>] [--json]"
                         " [--file <path>]... [--image <path>]... --prompt <text>"}[a[1]]
        if "help-no-request-id" in plants():
            text = text.replace(" [--request-id <id>]", "")
        print(text + "\nSynthetic help text for the kit's tests.")
        return 0
    if a == ["cloud", "status", "--json"]:
        doc = json.load(open(os.path.join(V127, "cloud-status.json")))
        if "catalogue-drift" in plants():
            doc["ready"] = "yes"
        print(json.dumps(doc))
        return 0
    if a == ["project", "list", "--json", "--include-personal"]:
        p = obs(a)
        if p.returncode != 0:
            return passthrough(p)
        rows = json.loads(p.stdout)
        rows += [project(P_A, "Synthetic project P-A", "https://github.com/synthetic-owner/synthetic-repo-0301.git"),
                 project(P_N, "Synthetic project no remote", None)]
        if "no-p-n" in plants():  # every standard project has a remote (the PC, #13, 2026-11-05)
            rows = [r for r in rows if not (isinstance(r, dict) and r.get("kind") == "standard"
                                            and r.get("gitRemoteUrl") is None)]
        print(json.dumps(rows))
        return 0
    with World() as w:
        now = now_ms()
        known = set(tt) | set(w.s["new"])
        if a[:2] == ["thread", "log"] and len(a) >= 3 and a[2] in known:
            after = int(a[a.index("--after-seq") + 1]) if "--after-seq" in a else 0
            limit = int(a[a.index("--limit") + 1])
            print(json.dumps([e for e in w.s["threads"][a[2]]["events"] if e["seq"] > after][:limit]))
            return 0
        if a[:2] == ["thread", "show"] and len(a) == 4 and a[2] in w.s["new"]:
            print(json.dumps(show_new(w, a[2], now)))
            return 0
        if a[:2] in (["thread", "show"], ["thread", "output"]) and len(a) == 4 and a[2] in tt:
            p = obs([a[0], a[1], tt[a[2]]["like"], "--json"])
            if p.returncode != 0 or a[1] == "output":
                return passthrough(p)
            doc = json.loads(p.stdout)
            doc["thread"].update(id=a[2], title="Synthetic test thread", createdAt=1700000580000)
            if isinstance(doc.get("environment"), dict) and doc["environment"].get("hostId"):
                doc["environment"]["hostId"] = "mch_syn_0001"  # a connected machine
            overlay(doc["thread"], w.s["threads"][a[2]], w.status(a[2], now), True)
            print(json.dumps(doc))
            return 0
        if a[:2] == ["thread", "output"] and len(a) == 4 and a[2] in w.s["new"]:
            return passthrough(obs(["thread", "output", "thr_syn_0006", "--json"]))
        if a[:3] == ["thread", "list", "--json"]:
            p = obs(a)
            if p.returncode != 0:
                return passthrough(p)
            rows = json.loads(p.stdout)
            like = {r.get("id"): r for r in rows if isinstance(r, dict)}
            c = cfg()
            for r in rows:
                sid = r.get("id")
                if sid in PA_COLD or (c.get("recent_in_pa") and sid in c.get("recent", {})):
                    r["projectId"] = P_A
                if sid == "thr_syn_0001" and w.s.get("touched"):
                    r["lastReadAt"] = r["lastReadAt"] + w.s["touched"]
                if sid == "thr_syn_0008" and w.s.get("touched_outside"):
                    r["lastReadAt"] = r["lastReadAt"] + w.s["touched_outside"]
                if sid == "thr_syn_0005" and w.s.get("cold"):
                    r["hasPendingInteraction"] = True
                if sid in c.get("titles", {}):
                    r["title"] = c["titles"][sid]
                if sid in c.get("recent", {}):
                    r["updatedAt"] = c["recent"][sid]
                    r["lastReadAt"] = c["recent"][sid] + w.s.get("touched_recent", 0)
            if w.s.get("appeared") and "thr_syn_0008" in like:
                n = json.loads(json.dumps(like["thr_syn_0008"]))
                n.update(id="thr_syn_0201", title="Synthetic new session", updatedAt=now // 60000 * 60000)
                rows.append(n)
            if "pa-busy" in plants() and "thr_syn_0002" in like:
                n = json.loads(json.dumps(like["thr_syn_0002"]))  # an active session, moved into P-A
                n.update(id="thr_syn_0203", title="Synthetic busy session in P-A", projectId=P_A)
                rows.append(n)
            if w.s.get("jake_pa") and "thr_syn_0005" in like:
                n = json.loads(json.dumps(like["thr_syn_0005"]))
                n.update(id="thr_syn_0202", title="Synthetic session in P-A", projectId=P_A,
                         updatedAt=now // 60000 * 60000)
                rows.append(n)
            for tid in sorted(w.s["new"], reverse=True):
                rows.insert(0, new_row(w, tid, now))
            for tid in sorted(tt, reverse=True):
                base = like.get(tt[tid]["like"])
                if base is None:
                    continue  # the template is not in this view
                r = json.loads(json.dumps(base))
                r.update(id=tid, title="Synthetic test thread", createdAt=1700000580000)
                if r.get("environmentHostId"):
                    r["environmentHostId"] = "mch_syn_0001"  # a connected machine
                overlay(r, w.s["threads"][tid], w.status(tid, now), False)
                rows.insert(0, r)
            print(json.dumps(rows))
            return 0
    return passthrough(obs(a))


if __name__ == "__main__":
    sys.exit(main())
