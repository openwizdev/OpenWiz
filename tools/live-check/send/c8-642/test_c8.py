"""C8's current observed pairs; supersedes #642's historical queued-only diff guard.

The original historical test remains under its immutable evidence path. Later
live observations (#1004) explicitly permit exactly two pairs, never their mix.
"""
import importlib.util
import json
from pathlib import Path
import unittest

KIT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("send_kit", KIT / "scripts/send-kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class C8(unittest.TestCase):
    def test_only_observed_status_delivery_pairs_are_accepted(self):
        plan = json.loads((KIT / "scripts/plan.json").read_text())
        group = next(g for g in plan["groups"] if g["id"] == "C8")
        self.assertEqual(len(group["steps"]), 2)
        step = group["steps"][1]
        self.assertEqual((step["id"], step["msg"], step["thread"], step["mode"], step["need"]),
                         ("C8-M12", "M12", "T-C", "steer", "busy"))
        for status, delivery, accepted in (("accepted", "accepted", True), ("queued", "queued", True),
                                            ("accepted", "queued", False), ("queued", "accepted", False),
                                            ("failed", "queued", False), ("uncertain", "accepted", False)):
            got = {"exit": 0, "status": status, "delivery": delivery, "effect": "asks_to_steer", "calls": 1}
            with self.subTest(status=status, delivery=delivery):
                self.assertEqual(kit.check(step["expect"], got) == [], accepted)


if __name__ == "__main__":
    unittest.main()
