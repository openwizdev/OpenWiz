#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main

HERE = Path(__file__).resolve().parent


class UsageCheck(TestCase):
    def check(self, mode, line, status, timeout="3", child=False):
        script = HERE / "usage_check.py"
        self.assertTrue(script.is_file(), "usage_check.py is missing")
        with TemporaryDirectory() as folder:
            child_pid = Path(folder) / "child"
            env = dict(os.environ, USAGE_FIXTURE=mode, USAGE_PID_FILE=str(child_pid))
            result = subprocess.run(
                [sys.executable, "-I", str(script), "--driver", str(HERE / "fixtures/usage/driver"),
                 "--timeout", timeout],
                env=env, capture_output=True, text=True, timeout=8,
            )
            try:
                self.assertEqual(result.stdout, line + "\n")
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.returncode, status)
                if child:
                    pid = int(child_pid.read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                if child_pid.exists():
                    try:
                        os.kill(int(child_pid.read_text()), 9)
                    except ProcessLookupError:
                        pass

    def test_valid_response(self):
        self.check("good", "usage: pass", 0)

    def test_no_usage(self):
        self.check("none", "usage: none", 0)

    def test_other_refusal_is_a_failure(self):
        self.check("refused", "usage: fail driver refused usage", 1)

    def test_unavailable_cannot_report_zero(self):
        self.check("unavailable", "usage: fail response does not match the usage schema", 1)

    def test_driver_must_return_a_response_envelope(self):
        self.check("lane", "usage: fail response does not match the usage schema", 1)

    def test_credential_output_is_not_echoed(self):
        for mode in ("stdout", "escaped", "stderr"):
            with self.subTest(mode=mode):
                self.check(mode, "usage: fail output contained a credential", 1)

    def test_child_environment_is_sampled_during_the_probe(self):
        self.check("environment", "usage: fail process environment contained a credential", 1)

    def test_detached_child_is_reported_and_reaped(self):
        self.check("leftover", "usage: fail a driver process is still running", 1, child=True)

    def test_timeout_reports_the_limit_and_reaps_children(self):
        self.check("timeout", "usage: fail driver timed out", 1, timeout="0.5", child=True)


if __name__ == "__main__":
    main()
