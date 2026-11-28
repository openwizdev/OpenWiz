import re
import runpy
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
SETTINGS = runpy.run_path(str(HERE.parent / "settings" / "test_fixtures.py"))
load = SETTINGS["load"]


class TelemetryFixtures(unittest.TestCase):
    def test_new_settings_keep_every_opt_in_off(self):
        for path in [HERE / "new-file.json", *sorted(SETTINGS["VALID"].glob("new-file*.json"))]:
            with self.subTest(file=path.name, fixture_set=path.parent.name):
                settings = load(path)
                self.assertIs(settings["telemetry"], False, "telemetry must default to off")
                self.assertEqual(
                    {name for name, on in settings["drivers"].items() if on}, {"local"}
                )
                self.assertEqual(
                    {name for name, on in settings["channels"].items() if on}, {"t3"}
                )
                for name, key in settings["keys"].items():
                    if key["opt_in"]:
                        self.assertIs(key["on"], False, f"opt-in key {name} must default to off")
                self.assertEqual(settings["updates"], "ask")

    def test_telemetry_is_the_only_opt_in_that_changes(self):
        new = load(HERE / "new-file.json")
        enabled = load(HERE / "telemetry-on.json")
        self.assertIs(enabled["telemetry"], True)
        snapshot = {
            field: value for field, value in new.items() if field not in {"schema", "history"}
        }
        self.assertEqual(enabled["history"], [snapshot])
        self.assertEqual(enabled["version"], new["version"] + 1)
        self.assertEqual(enabled["changed_by"], "settings tab")
        self.assertGreater(enabled["changed_at"], new["changed_at"])
        metadata = {"history", "version", "changed_by", "changed_at"}
        self.assertEqual(
            {field: value for field, value in enabled.items() if field not in metadata},
            {field: value for field, value in new.items() if field not in metadata}
            | {"telemetry": True},
        )

    def test_settings_fixtures_match_the_settings_contract(self):
        schema = load(SETTINGS["SCHEMA"])
        for name in ("new-file.json", "telemetry-on.json"):
            with self.subTest(file=name):
                self.assertEqual(SETTINGS["refusals"](load(HERE / name), schema), [])

    def test_egress_policy_has_exactly_one_telemetry_row(self):
        contract = (CONTRACTS / "telemetry.v1.md").read_text(encoding="utf-8")
        block = re.search(r"^## Egress allow-list reasons\n\n```json\n(.*?)\n```$", contract, re.M | re.S)
        self.assertIsNotNone(block, "the egress policy block is missing")
        policy = SETTINGS["json"].loads(block.group(1), object_pairs_hook=SETTINGS["pairs"])
        self.assertEqual(policy["reason_forms"], ["owner-started: <what>", "opt-in: <settings row>"])
        self.assertEqual(
            policy["opt_in_rows"],
            {
                "telemetry": "user-telemetry",
                "channels.<channel>": "owner-notifications",
                "keys.<key>.on": "credential-use",
            },
        )


if __name__ == "__main__":
    unittest.main()
