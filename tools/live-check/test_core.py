"""K1: offline proofs at the shared toolkit's public boundaries (Python 3.9)."""
import copy
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load_core():
    spec = importlib.util.spec_from_file_location("live_check_core", HERE / "core.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


class Core(unittest.TestCase):
    def test_decoded_privacy_in_keys_and_nested_values(self):
        core = load_core()
        for secret in ('Synthetic "private" title', 'Synthetic\\private', '秘密会議', 'HR', '私事'):
            for report in ({"nested": [{"title": secret}]}, {secret: "count"}):
                self.assertEqual(core.leaked({secret}, report), {secret})
        self.assertEqual(core.leaked({"HR"}, {"title": "THREE"}), set())

    def test_initial_judgment_survives_later_activity(self):
        core = load_core()
        initial = {"rows": {"thr_syn_cold": {
            "status": "idle", "display": "idle", "updatedAt": 0, "lastReadAt": 0,
            "latestAttentionAt": 0, "queuedWork": "none", "pending": False, "activity": 0}}}
        current = copy.deepcopy(initial)
        current["rows"]["thr_syn_cold"].update(pending=True)
        self.assertEqual(core.judge(initial, current, {"thr_syn_cold"}), ({"pending": 1}, 0))
        current["rows"]["thr_syn_cold"].update(lastReadAt=7)
        self.assertEqual(core.judge(initial, current, {"thr_syn_cold"}),
                         ({"lastReadAt": 1, "pending": 1}, 0))

    def test_reused_identity_never_signals_another_process(self):
        core = load_core()
        child = subprocess.Popen([sys.executable, "-c", "import signal; signal.pause()"])
        try:
            ident = core.identity(child.pid)
            self.assertIsNotNone(ident)
            self.assertFalse(core.signal_if_same(dict(ident, lstart="synthetic earlier start"), signal.SIGTERM))
            self.assertIsNone(child.poll())
            self.assertTrue(core.signal_if_same(ident, signal.SIGTERM))
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def test_schema_checks_required_nested_types_and_unknown_rules(self):
        core = load_core()
        schema = {"type": "object", "required": ["count"], "additionalProperties": False,
                  "properties": {"count": {"type": "integer"}}}
        import json
        with tempfile.TemporaryDirectory() as tmp:
            for contract in ("new-thread", "attachment", "messaging", "inventory", "prompt"):
                (Path(tmp) / (contract + ".v1.schema.json")).write_text(json.dumps(schema))
            schemas = core.Schemas(tmp)
            for value, expected in (({"count": 3}, []), ({"count": True}, ["$.count: type"]),
                                    ({}, ["$: missing count"]), ({"count": 3, "extra": 4}, ["$: extra key"])):
                self.assertEqual(schemas.problems(value, "messaging"), expected)
            (Path(tmp) / "messaging.v1.schema.json").write_text('{"unknownRule": true}')
            with self.assertRaises(core.Stop):
                core.Schemas(tmp).problems({}, "messaging")


if __name__ == "__main__":
    unittest.main()
