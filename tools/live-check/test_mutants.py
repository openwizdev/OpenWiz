"""The evidence runner must reject false proof, even an always-passing suite."""
import importlib.util
import json
import os
import subprocess
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("mutants", Path(__file__).with_name("mutants.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Evidence(unittest.TestCase):
    def test_verdict_requires_named_failures_and_no_unlisted_failures(self):
        mutant = {"must_fail": ["guard"], "may_fail": ["knock-on"]}
        self.assertEqual(runner.verdict(mutant, 1, "kit test FAILED: guard"), 1)
        self.assertEqual(runner.verdict(mutant, 1, "kit test FAILED: guard\nkit test FAILED: knock-on"), 2)
        for code, output in ((0, ""), (0, "kit test FAILED: guard"), (1, "build failed"),
                             (1, "kit test FAILED: other"),
                             (1, "kit test FAILED: guard\nkit test FAILED: unlisted")):
            with self.subTest(code=code, output=output), self.assertRaises(ValueError):
                runner.verdict(mutant, code, output)

    def test_missing_control_requires_its_own_diagnostic(self):
        mutant = {"delete": ["send/scripts/send-kit.py"], "must_fail": [], "may_fail": [""]}
        self.assertEqual(runner.verdict(mutant, 2, "python3: can't open file 'send-kit.py'"), 0)
        with self.assertRaises(ValueError):
            runner.verdict(mutant, 2, "KIT_SOURCE_ROOT is required")

    def test_mutation_must_apply_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "core.py"
            mutant = {"name": "synthetic", "changes": [{"file": "core.py", "old": "guard", "new": "broken"}]}
            for source in ("missing", "guard guard"):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    runner.apply(root, mutant)
                self.assertEqual(path.read_text(), source)
            path.write_text("guard")
            runner.apply(root, mutant)
            self.assertEqual(path.read_text(), "broken")
            escaped = {"name": "escape", "changes": [
                {"file": "../outside.py", "old": "guard", "new": "broken"}]}
            with self.assertRaisesRegex(ValueError, "inside the toolkit"):
                runner.apply(root, escaped)

    def fixture_runner(self, root):
        tool = root / "tool"
        suite = tool / "send/scripts/test/kit-tests.sh"
        suite.parent.mkdir(parents=True)
        suite.write_text('echo run >> "$KIT_SOURCE_ROOT/attempts"\ncase "$(cat "$KIT_SOURCE_ROOT/mode")" in\n  green) exit 0 ;;\n  timeout) exec cat "$KIT_SOURCE_ROOT/blocked" ;;\nesac\nprintf \'kit test FAILED: guard\\n\'\nexit 1\n')
        (tool / "proof.txt").write_text("intact")
        source = root / "source"
        source.mkdir()
        for name in ("contracts", "tests", "apps"):
            (source / name).mkdir()
        (source / "mode").write_text("red")
        os.mkfifo(source / "blocked")
        logs = root / "logs"
        logs.mkdir()
        mutant = {"name": "synthetic", "must_fail": ["guard"], "changes": [
            {"file": "proof.txt", "old": "intact", "new": "broken"}]}
        return tool, source, logs, (0, "send", mutant)

    def test_resume_executes_again_after_a_failed_fresh_retry(self):
        for failure in ("green", "timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                tool, source, logs, item = self.fixture_runner(Path(tmp))
                original_run = subprocess.run

                def short_timeout(*args, **kwargs):
                    if (source / "mode").read_text() == "timeout":
                        kwargs["timeout"] = 0.1
                    return original_run(*args, **kwargs)

                with patch.object(runner, "HERE", tool), patch.dict(
                        os.environ, KIT_SOURCE_ROOT=str(source)), patch.object(
                            runner.subprocess, "run", side_effect=short_timeout):
                    self.assertTrue(runner.run_one(item, logs, source, "snapshot")[1])
                    (source / "mode").write_text(failure)
                    self.assertFalse(runner.run_one(item, logs, source, "snapshot")[1])
                    latest = (logs / "send-synthetic.log").read_text()
                    self.assertIn("UNEXPECTED result: exit=0" if failure == "green"
                                  else "timed out", latest)
                    record = json.loads((logs / "send-synthetic.json").read_text())
                    self.assertIs(record.get("ok"), False)
                    attempts = (source / "attempts").read_text()
                    (source / "mode").write_text("red")
                    self.assertTrue(runner.run_one(item, logs, source, "snapshot", True)[1])
                    self.assertEqual((source / "attempts").read_text(), attempts + "run\n")

    def test_resume_reuses_only_an_intact_successful_proof(self):
        for damage in ("none", "log", "missing-log", "json", "shape", "missing-digest"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as tmp:
                tool, source, logs, item = self.fixture_runner(Path(tmp))
                with patch.object(runner, "HERE", tool), patch.dict(
                        os.environ, KIT_SOURCE_ROOT=str(source)):
                    self.assertTrue(runner.run_one(item, logs, source, "snapshot")[1])
                    log = logs / "send-synthetic.log"
                    metadata = logs / "send-synthetic.json"
                    if damage == "log":
                        log.write_text("unrelated replacement log")
                    elif damage == "missing-log":
                        log.unlink()
                    elif damage == "json":
                        metadata.write_text("{")
                    elif damage == "shape":
                        metadata.write_text("[]")
                    elif damage == "missing-digest":
                        record = json.loads(metadata.read_text())
                        record.pop("log_sha256", None)
                        metadata.write_text(json.dumps(record))
                    before = (source / "attempts").read_text()
                    self.assertTrue(runner.run_one(item, logs, source, "snapshot", True)[1])
                    self.assertEqual((source / "attempts").read_text(),
                                     before if damage == "none" else before + "run\n")

    def test_legacy_custom_inventory_follows_the_extracted_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutants.json"
            path.write_text(json.dumps([{"name": "noop", "file": "send-kit.py",
                                         "old": "def sha(text):", "new": "def sha(text):  # noop",
                                         "suite": "sol", "must_fail": ["R8"]}]))
            items = runner.load_inventory("send", path)
            self.assertEqual(items[0]["changes"][0]["file"], "core.py")
            path.write_text(json.dumps([{"name": "bogus", "file": "send-kit.py",
                                         "old": "this text is not in the kit", "new": "nor this",
                                         "suite": "kit", "must_fail": ["X2-6"]}]))
            with self.assertRaisesRegex(ValueError, "does not apply"):
                runner.load_inventory("send", path)


if __name__ == "__main__":
    unittest.main()
