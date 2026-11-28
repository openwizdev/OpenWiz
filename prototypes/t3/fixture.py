"""Pinned fake T3 transport. All its work and ticket notes are local JSON."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

PREFIX = "openwiz-t3-fixture-"
REPOSITORY = "example/site"
PROJECT = "prj_syn-openwiz"
CHECKOUT = "checkout"
PROVIDERS = {("codex", "gpt-6.2-sol"): "instance-syn-codex"}
AUTHOR = "example-bot[bot]"
RUN_WORK = ("provider", "terminal", "delegated-child")


def new_id(prefix):
    return prefix + uuid.uuid4().hex


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("repeated key")
        result[key] = value
    return result


def directory():
    path = Path(os.environ.get("OPENWIZ_T3_FIXTURE_DIR", ""))
    info = path.lstat()
    if not (path.is_absolute() and path.name.startswith(PREFIX)
            and path.parent.resolve() == Path(tempfile.gettempdir()).resolve()
            and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077):
        raise ValueError("invalid fixture directory")
    return path.resolve()


@contextmanager
def local_file(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd) as stream:
        info = os.fstat(fd)
        if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1):
            raise ValueError("invalid fixture file")
        yield stream


@contextmanager
def lock(path):
    with local_file(path, os.O_CREAT | os.O_RDWR) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def load(path, default):
    try:
        with local_file(path, os.O_RDONLY) as stream:
            return json.load(stream, object_pairs_hook=unique)
    except FileNotFoundError:
        return default


def save(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_note(state, thread):
    note_id = thread["note"]
    turn = thread["turn"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    model, skill = thread["model"], thread["skill"]
    step = "started the throwaway ticket" if turn == 1 else f"woke and read the ticket again (turn {turn})"
    body = ("<!-- openwiz:status v1 -->\nagent: builder\nstate: working\n"
            f"harness: Codex\nmodel: {model}\nskills: {skill}@0.1.0\nstep: {step}\ntime: {now}\n")
    state["notes"][str(note_id)] = {"id": note_id, "author": AUTHOR, "updated_at": now, "body": body}


def tracker(root, ticket, state):
    comments = [state["notes"][str(thread["note"])] for thread in state["threads"].values()
                if thread["ticket"] == ticket]
    save(root / f"tracker-{ticket}.json", {"record_authors": [AUTHOR], "comments": comments})


def start(root, state, args, message):
    found = re.fullmatch(r"Build example/site#([1-9][0-9]*) with the ([a-z0-9-]+) skill\.", message)
    if not (found and args.project == PROJECT and Path.cwd() == root / CHECKOUT
            and (args.provider, args.model) in {(i, m) for (_, m), i in PROVIDERS.items()}
            and re.fullmatch(rf"#{found[1]}: example/site builder \(run-[0-9a-f]{{32}}\)", args.title)):
        raise ValueError("start differs from the fixture map")

    thread_id = new_id("thr_syn-")
    run_id = new_id("t3-run-syn-")
    thread = {
        "ticket": int(found[1]), "skill": found[2], "title": args.title,
        "provider": args.provider, "model": args.model, "effort": "host-default",
        "project": args.project, "checkout": CHECKOUT, "kind": "top-level",
        "active": run_id, "queue": [], "work": list(RUN_WORK),
        "note": len(state["notes"]) + 1, "turn": 1, "stopped": False,
    }
    state["threads"][thread_id] = thread
    update_note(state, thread)
    return {"threadId": thread_id, "projectId": PROJECT, "runId": run_id}, thread


def advance(state, thread):
    """Simulate the active turn finishing and its queued successor taking over."""
    if thread["stopped"]:
        raise ValueError("fixture run has stopped")
    if not thread["queue"]:
        thread["active"] = None
        thread["work"].clear()
        return
    thread["work"] = list(RUN_WORK)
    thread["active"] = thread["queue"].pop(0)["runId"]
    thread["turn"] += 1
    update_note(state, thread)


def send(state, thread, args, message, advance_now):
    if thread["stopped"] or message != f"Read {REPOSITORY}#{thread['ticket']} again and edit your existing status note.":
        raise ValueError("wake differs from the fixture run")
    idle = thread["active"] is None
    receipt = {
        "threadId": args.thread, "messageId": new_id("message-syn-"), "runId": new_id("t3-run-syn-"),
        "status": "running" if idle else "queued", "delivery": "started" if idle else "queued",
    }
    thread["queue"].append({"messageId": receipt["messageId"], "runId": receipt["runId"]})
    if idle or advance_now:
        advance(state, thread)
    return receipt


def terminate_fixture(thread_id, thread, incomplete):
    thread["active"] = None
    thread["queue"].clear()
    thread["work"] = ["delegated-child"] if incomplete else []
    thread["stopped"] = not incomplete
    return {
        "threadId": thread_id, "activeRunId": thread["active"], "pendingMessages": len(thread["queue"]),
        "remainingWork": thread["work"], "preserved": True,
    }


def thread_command(words):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    verb = parser.add_subparsers(dest="command", required=True)
    launch = verb.add_parser("start", allow_abbrev=False)
    for name in ("title", "provider", "model"):
        launch.add_argument(f"--{name}", required=True)
    launch.add_argument("project")
    wake = verb.add_parser("send", allow_abbrev=False)
    wake.add_argument("thread")
    for command in (launch, wake):
        command.add_argument("--json", action="store_true", required=True)
        command.add_argument("message", choices=["-"])
    return parser.parse_args(words)


def main(words):
    root = directory()
    fault = os.environ.get("OPENWIZ_T3_FIXTURE_FAULT")
    if not words:
        raise ValueError("missing fixture operation")
    with lock(root / "fixture.lock"):
        state = load(root / "host.json", {"threads": {}, "notes": {}, "calls": []})
        if words[0] == "thread":
            args = thread_command(words[1:])
            message = sys.stdin.read()
            state["calls"].append({"argv": words, "stdin": message, "cwd": Path.cwd().name})
            if args.command == "start":
                reply, thread = start(root, state, args, message)
                operation = "start"
            else:
                thread = state["threads"][args.thread]
                reply = send(state, thread, args, message, os.environ.get("OPENWIZ_T3_FIXTURE_AUTO_ADVANCE") == "1")
                operation = "send"
        else:
            # These are fixture controls, outside the modeled CLI.
            operation, target = words
            if operation == "init-tracker":
                tracker(root, int(target), state)
                return
            thread = state["threads"][target]
            state["calls"].append({"fixture": words})
            if operation == "advance-fixture":
                advance(state, thread)
                reply = {"advanced": True}
            elif operation == "terminate-fixture":
                reply = terminate_fixture(target, thread, fault == "stop-incomplete")
            else:
                raise ValueError("unknown fixture operation")

        save(root / "host.json", state)
        tracker(root, thread["ticket"], state)
        if operation == "start" and fault == "start-partial":
            reply["runId"] = None
        if operation == "start" and fault == "start-failed":
            print("synthetic host diagnostic", file=sys.stderr)
            return 1
        if operation == "send" and fault == "send-wrong-thread":
            reply["threadId"] = new_id("thr_syn-")
        if operation == "send" and fault == "send-malformed":
            print("unreadable fixture reply")
            return
    print(json.dumps(reply))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyError, OSError, ValueError):
        sys.exit("fixture operation failed")
