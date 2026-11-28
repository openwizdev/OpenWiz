import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "update.v1.schema.json"
VALIDATOR = HERE.parent / "value-meter" / "test_fixtures.py"

spec = importlib.util.spec_from_file_location("fixture_schema", VALIDATOR)
fixture_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_schema)


class UpdateFixtures(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), "update.v1.schema.json is missing")
        self.schema = fixture_schema.load(SCHEMA)

    def assert_valid(self, report):
        self.assertEqual(fixture_schema.errors(report, self.schema, self.schema), [])

    def assert_refused(self, report):
        self.assertTrue(fixture_schema.errors(report, self.schema, self.schema),
                        f"schema accepted {report!r}")

    def test_each_report(self):
        expected = {
            "verified": (True, None),
            "bad-checksum": (False, "checksum-invalid"),
            "bad-manifest": (False, "manifest-invalid"),
            "missing-release-record": (False, "release-record-missing"),
            "older-release": (True, "not-newer"),
        }
        self.assertEqual({path.stem for path in HERE.glob("*.json")}, set(expected))
        for name, (verified, reason) in expected.items():
            with self.subTest(name=name):
                report = fixture_schema.load(HERE / f"{name}.json")
                self.assert_valid(report)
                self.assertIs(report["verified"], verified)
                self.assertEqual(report["reason"], reason)
                if verified:
                    current, latest = (tuple(map(int, report[key].split(".")))
                                       for key in ("current", "latest"))
                    self.assertEqual(latest > current, reason is None)

    def test_refuses_unknown_fields_and_bad_values(self):
        report = fixture_schema.load(HERE / "verified.json")
        for field, value in (
            ("offer", True), ("current", "main"), ("latest", "v0.2.0"),
            ("latest", None), ("verified", "true"), ("reason", "unknown"),
            ("reason", "checksum-invalid"), ("changelog_line", None),
            ("changelog_line", "   "), ("changelog_line", "First.\nSecond."),
        ):
            with self.subTest(field=field, value=value):
                self.assert_refused(dict(report, **{field: value}))
        for field in report:
            with self.subTest(missing=field):
                self.assert_refused({key: value for key, value in report.items() if key != field})

    def test_unverified_requires_a_failure_reason_and_carries_no_changelog(self):
        report = fixture_schema.load(HERE / "bad-checksum.json")
        for reason in (None, "", "unknown", "not-newer"):
            with self.subTest(reason=reason):
                self.assert_refused(dict(report, reason=reason))
        self.assert_refused({key: value for key, value in report.items() if key != "reason"})
        self.assert_refused(dict(report, changelog_line="A release is available."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
