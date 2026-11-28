#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "kernel" / "driver-kit" / "schema.json"
REQUEST = {
    "repository": "example/site",
    "ticket": 7,
    "skill": "build-ticket",
    "harness": "codex",
    "model": "gpt-6.2-sol",
}


class Lifecycle(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="openwiz-t3-fixture-")
        self.addCleanup(workspace.cleanup)
        self.state = Path(workspace.name).resolve()
        self.env = {
            "PATH": os.pathsep.join((str(Path(sys.executable).parent), os.defpath)),
            "TMPDIR": tempfile.gettempdir(),
            "OPENWIZ_T3_FIXTURE_DIR": str(self.state),
        }

    def execute(self, command, payload, *, fault=None, env=None):
        entry = HERE / "driver"
        call_env = (self.env if env is None else env).copy()
        if fault is not None:
            call_env["OPENWIZ_T3_FIXTURE_FAULT"] = fault
        try:
            return subprocess.run(
                [str(entry), command], input=payload, capture_output=True, env=call_env, timeout=10,
            )
        except FileNotFoundError:
            self.fail(f"expected an executable driver for {command}; prototypes/t3/driver is missing")

    def answer(self, result, status):
        self.assertEqual(result.returncode, status, (result.stdout, result.stderr))
        self.assertEqual(result.stderr, b"")
        response = json.loads(result.stdout)
        if status == 1:
            self.assertEqual(set(response), {"error", "next"})
            for field in response.values():
                self.assertIsInstance(field, str)
                self.assertTrue(0 < len(field) <= 300)
                self.assertFalse(any(ord(char) < 32 for char in field))
        return response

    def call(self, command, payload=None, *, status=0, fault=None):
        data = b"" if payload is None else json.dumps(payload).encode()
        return self.answer(self.execute(command, data, fault=fault), status)

    def state_file(self, name):
        return json.loads((self.state / name).read_bytes())

    def host(self):
        return self.state_file("host.json")

    def fixture(self, operation, target):
        subprocess.run([sys.executable, "-I", str(HERE / "fixture.py"), operation, str(target)],
                       env=self.env, capture_output=True, check=True, timeout=10)

    def test_version_and_verbatim_schema(self):
        self.assertEqual(self.call("version"), {
            "driver": "t3-fixture", "records": ["openwiz:records v1"], "can": ["start", "wake", "stop"],
        })
        result = self.execute("schema", b"")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, SCHEMA.read_bytes(), b""))
        self.call("archive", status=1)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_executable_lifecycle(self):
        started = self.call("start", REQUEST)
        self.assertRegex(started["run"], r"^run-[0-9a-f]{32}$")
        self.assertEqual(set(started), {"run"})
        thread_id, thread = next(iter(self.host()["threads"].items()))
        title = f"#7: example/site builder ({started['run']})"
        self.assertNotEqual(started["run"], thread_id)
        self.assertEqual({
            "checkout": thread["checkout"], "project": thread["project"], "kind": thread["kind"],
            "provider": thread["provider"], "model": thread["model"], "effort": thread["effort"],
            "title": thread["title"],
        }, {
            "checkout": "checkout", "project": "prj_syn-openwiz", "kind": "top-level",
            "provider": "instance-syn-codex", "model": "gpt-6.2-sol", "effort": "host-default",
            "title": title,
        })
        self.assertEqual(self.host()["calls"], [{
            "argv": ["thread", "start", "--json", "--title", title,
                     "--provider", "instance-syn-codex", "--model", "gpt-6.2-sol", "prj_syn-openwiz", "-"],
            "stdin": "Build example/site#7 with the build-ticket skill.", "cwd": "checkout",
        }])
        note, = self.state_file("tracker-7.json")["comments"]
        self.assertEqual(note["id"], thread["note"])
        self.assertIn("skills: build-ticket@", note["body"])

        self.assertEqual(self.call("wake", started), {**started, "woke": True})
        self.assertEqual(self.host()["calls"][-1], {
            "argv": ["thread", "send", "--json", thread_id, "-"],
            "stdin": "Read example/site#7 again and edit your existing status note.", "cwd": self.state.name,
        })
        threads = self.host()["threads"]
        self.assertEqual(set(threads), {thread_id})
        queued, = threads[thread_id]["queue"]
        self.assertEqual(threads[thread_id]["active"], thread["active"])
        self.assertNotEqual(queued["runId"], thread["active"])
        self.assertEqual(self.state_file("tracker-7.json")["comments"], [note])
        self.fixture("advance-fixture", thread_id)
        self.assertEqual(self.host()["threads"][thread_id]["active"], queued["runId"])
        edited, = self.state_file("tracker-7.json")["comments"]
        self.assertEqual(edited["id"], note["id"])
        self.assertNotEqual(edited["body"], note["body"])

        self.call("wake", started)
        unrelated = self.call("start", {**REQUEST, "ticket": 8})
        unrelated_id = self.state_file("runs.json")[unrelated["run"]]["thread"]
        unrelated_before = self.host()["threads"][unrelated_id]
        unrelated_tracker = self.state_file("tracker-8.json")
        expected_stop = {**started, "stopped": True}
        self.assertEqual(self.call("stop", started), expected_stop)
        host = self.host()
        stopped = host["threads"][thread_id]
        self.assertTrue(stopped["stopped"])
        self.assertIsNone(stopped["active"])
        self.assertEqual((stopped["work"], stopped["queue"]), ([], []))
        self.assertEqual(stopped["note"], edited["id"])
        self.assertEqual(self.state_file("tracker-7.json")["comments"], [edited])
        self.assertEqual(host["threads"][unrelated_id], unrelated_before)
        self.assertEqual(self.state_file("tracker-8.json"), unrelated_tracker)
        self.assertEqual(self.call("stop", started), expected_stop)
        self.assertIn("error", self.call("wake", started, status=1))
        self.assertEqual(self.host(), host)
        self.call("wake", unrelated)
        self.call("stop", unrelated)

        fresh = self.call("start", REQUEST)
        self.assertNotEqual(fresh, started)
        fresh_id = self.state_file("runs.json")[fresh["run"]]["thread"]
        self.assertEqual(self.host()["threads"][fresh_id]["title"], f"#7: example/site builder ({fresh['run']})")
        self.call("stop", fresh)

    def test_invalid_requests_never_touch_fixture(self):
        raw = json.dumps(REQUEST).encode()
        invalid_starts = [
            b"[" * 2000 + b"]" * 2000, b"", b"[]", b"null", b"{}", b"\xff", raw + b"{}",
            raw[:-1] + b', "ticket": 7}', raw[:-1] + b', "token": "fake-canary"}',
        ]
        for fields in [
            {"ticket": True}, {"ticket": 7.0}, {"ticket": "7"}, {"ticket": 0}, {"ticket": float("nan")},
            {"skill": "bad skill"}, {"harness": "codex\n"}, {"repository": "invalid"},
            {"model": []}, {"effort": False}, {"effort": "Medium"}, {"model": "a" * 101},
        ]:
            invalid_starts.append(json.dumps({**REQUEST, **fields}).encode())
        for invalid in invalid_starts:
            with self.subTest(input=invalid):
                self.answer(self.execute("start", invalid), 1)
        for command in ("wake", "stop"):
            for invalid in (b'{"run":true}', b'{"run":"a","run":"b"}', b'{"run":"a","extra":1}', b'{"run":"a/b"}'):
                self.answer(self.execute(command, invalid), 1)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_mapping_and_effort_refusal(self):
        for fields in (
            {"repository": "example/another"}, {"harness": "another"}, {"model": "another"},
        ):
            self.assertIn("no fixture", self.call("start", {**REQUEST, **fields}, status=1)["error"])
        refused = self.call("start", {**REQUEST, "effort": "medium"}, status=1)
        self.assertIn("effort medium for codex", refused["error"])
        self.assertEqual(refused["next"],
                         "this host can't set effort: remove the effort for this harness in your Models table "
                         "or Roster to run it at the host's default")
        self.assertEqual(list(self.state.iterdir()), [])

    def test_credential_shaped_fields_are_refused_privately(self):
        canary = "sk-" + "a" * 16
        for name in ("skill", "effort"):
            response = self.execute("start", json.dumps({**REQUEST, name: canary}).encode())
            self.assertNotIn(canary.encode(), response.stdout + response.stderr)
            self.answer(response, 1)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_malformed_state_returns_a_v1_error(self):
        for value in ([], {"run-invalid": {}}, {"run-" + "0" * 32: {"ticket": True, "state": "active"}}):
            (self.state / "runs.json").write_text(json.dumps(value))
            self.call("start", REQUEST, status=1)
        self.assertFalse((self.state / "host.json").exists())

    def test_idle_wake_starts_a_turn_and_edits_the_current_note(self):
        started = self.call("start", REQUEST)
        thread_id, = self.host()["threads"]
        self.fixture("advance-fixture", thread_id)
        self.assertIsNone(self.host()["threads"][thread_id]["active"])
        self.call("wake", started)
        thread = self.host()["threads"][thread_id]
        self.assertIsNotNone(thread["active"])
        self.assertEqual((thread["turn"], thread["queue"]), (2, []))
        note, = self.state_file("tracker-7.json")["comments"]
        self.assertEqual(note["id"], thread["note"])
        updated = datetime.fromisoformat(note["updated_at"].replace("Z", "+00:00"))
        self.assertLess(abs((datetime.now(timezone.utc) - updated).total_seconds()), 60)
        self.call("stop", started)

    def test_stop_survives_a_missing_or_replaced_checkout(self):
        checkout = self.state / "checkout"
        for ticket in (7, 8):
            started = self.call("start", {**REQUEST, "ticket": ticket})
            checkout.rmdir()
            if ticket == 8:
                checkout.symlink_to(self.state, target_is_directory=True)
            for _ in range(2):
                self.assertEqual(self.call("stop", started), {**started, "stopped": True})
            stopped = self.host()["threads"][self.state_file("runs.json")[started["run"]]["thread"]]
            self.assertEqual(stopped["work"], [])

    def test_missing_or_symlinked_workspace(self):
        raw = json.dumps(REQUEST).encode()
        env = self.env.copy()
        del env["OPENWIZ_T3_FIXTURE_DIR"]
        self.answer(self.execute("start", raw, env=env), 1)
        (self.state / "driver.lock").symlink_to(SCHEMA)
        self.answer(self.execute("start", raw), 1)
        self.assertEqual(list(self.state.iterdir()), [self.state / "driver.lock"])

    def test_unknown_run_never_reaches_fixture(self):
        for command in ("wake", "stop"):
            response = self.call(command, {"run": "run-unknown"}, status=1)
            self.assertIn("unknown fixture run", response["error"])
        self.assertFalse((self.state / "host.json").exists())

    def test_ambiguous_starts_are_fenced(self):
        for ticket, fault in enumerate(("start-partial", "start-failed"), start=7):
            with self.subTest(fault=fault):
                payload = {**REQUEST, "ticket": ticket}
                answer = self.call("start", payload, fault=fault, status=1)
                self.assertIn("unverified", answer["error"])
                self.assertNotIn("diagnostic", json.dumps(answer))
                host = self.host()
                self.assertEqual(len(host["threads"]), ticket - 6)
                self.assertIn("unresolved", self.call("start", payload, status=1)["error"])
                self.assertEqual(self.host(), host)

    def test_ambiguous_wake_is_fenced_but_stop_is_possible(self):
        for ticket, fault in enumerate(("send-wrong-thread", "send-malformed"), start=7):
            with self.subTest(fault=fault):
                started = self.call("start", {**REQUEST, "ticket": ticket})
                thread_id = self.state_file("runs.json")[started["run"]]["thread"]
                answer = self.call("wake", started, fault=fault, status=1)
                self.assertIn("unverified", answer["error"])
                host = self.host()
                self.assertEqual(len(host["threads"][thread_id]["queue"]), 1)
                self.call("wake", started, status=1)
                self.assertEqual(self.host(), host)
                self.call("stop", started)
                self.assertEqual(self.host()["threads"][thread_id]["queue"], [])

    def test_stop_requires_verified_child_cleanup(self):
        started = self.call("start", REQUEST)
        self.call("wake", started)
        refused = self.call("stop", started, fault="stop-incomplete", status=1)
        self.assertIn("termination is unverified", refused["error"])
        host = self.host()
        thread, = host["threads"].values()
        self.assertEqual(thread["work"], ["delegated-child"])
        self.assertFalse(thread["stopped"])
        self.call("wake", started, status=1)
        self.assertEqual(self.host(), host)
        self.assertEqual(self.call("stop", started), {**started, "stopped": True})
        thread, = self.host()["threads"].values()
        self.assertEqual(thread["work"], [])
        self.assertTrue(thread["stopped"])

    def race(self, requests):
        ready = Barrier(len(requests))

        def invoke(request):
            command, value = request
            ready.wait(timeout=10)
            return self.execute(command, json.dumps(value).encode())

        with ThreadPoolExecutor(max_workers=len(requests)) as workers:
            return list(workers.map(invoke, requests))

    def test_concurrent_start_keeps_one_thread(self):
        results = self.race([("start", REQUEST)] * 4)
        self.assertEqual(sorted(result.returncode for result in results), [0, 1, 1, 1])
        started = self.answer(next(result for result in results if result.returncode == 0), 0)
        self.assertEqual(len(self.host()["threads"]), 1)
        self.call("stop", started)

    def test_each_acknowledged_wake_queues_one_followup(self):
        started = self.call("start", REQUEST)
        for result in self.race([("wake", started)] * 4):
            self.assertEqual(self.answer(result, 0), {**started, "woke": True})
        host = self.host()
        self.assertEqual([call["argv"][1] for call in host["calls"]], ["start"] + ["send"] * 4)
        thread, = host["threads"].values()
        self.assertEqual(len({message["messageId"] for message in thread["queue"]}), 4)
        self.call("stop", started)

    def test_concurrent_wake_and_stop_never_send_after_stop(self):
        started = self.call("start", REQUEST)
        results = self.race([("wake", started), ("stop", started), ("wake", started), ("stop", started)])
        for result in results[1::2]:
            self.assertEqual(self.answer(result, 0), {**started, "stopped": True})
        for result in results[::2]:
            self.assertIn(result.returncode, (0, 1))
            self.answer(result, result.returncode)
        host = self.host()
        thread, = host["threads"].values()
        self.assertEqual((thread["stopped"], thread["queue"], thread["work"]), (True, [], []))
        kinds = [call["argv"][1] if "argv" in call else call["fixture"][0] for call in host["calls"]]
        wakes = sum(result.returncode == 0 for result in results[::2])
        self.assertEqual(kinds, ["start"] + ["send"] * wakes + ["terminate-fixture"])
        self.call("wake", started, status=1)
        self.assertEqual(self.host(), host)


if __name__ == "__main__":
    unittest.main()
