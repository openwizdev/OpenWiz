"""Synthetic subprocess proofs for the PTY driver; standard library only.

No application, backend, live reads, sleeps or external dependencies.
"""

import base64
import json
from pathlib import Path
import subprocess
import sys
import unittest

DRIVER = Path(__file__).with_name("pty_drive.py")


class DriverTests(unittest.TestCase):
    def drive(self, child, steps, cols=120, rows=40, driver_exit=0):
        run = subprocess.run(
            [sys.executable, "-I", str(DRIVER), str(cols), str(rows),
             json.dumps(steps), sys.executable, "-I", "-c", child],
            capture_output=True, timeout=25, check=False,
        )
        self.assertEqual(run.returncode, driver_exit, run.stderr.decode())
        report = json.loads(run.stdout)
        return report, base64.b64decode(report.pop("output"))

    def test_quit_drains_one_mib_and_captures_cleanup(self):
        report, output = self.drive(r'''
import os, termios, tty
before = termios.tcgetattr(0)
tty.setraw(0)
os.write(1, b"\x1b[?1049h\x1b[?25lREADY")
assert os.read(0, 1) == b"q"
os.write(1, b"QUIT-ACK\n")
data = b"X" * (1024 * 1024)
while data:
    data = data[os.write(1, data):]
os.write(1, b"\x1b[?1049l\x1b[?25h")
termios.tcsetattr(0, termios.TCSANOW, before)
''', [{"wait": "READY"}, {"send": "q"}])
        # Exact independent byte stream: a partial drain cannot pass.
        expected = (b"\x1b[?1049h\x1b[?25lREADYQUIT-ACK\n" + b"X" * (1024 * 1024)
                    + b"\x1b[?1049l\x1b[?25h")
        self.assertEqual(report["steps"], [True, True])
        self.assertIn(b"QUIT-ACK", output)
        self.assertEqual(report["exit"], 0, "quitting child blocked on PTY output")
        self.assertTrue(report["restored"])
        self.assertEqual(output, expected)
        self.assertFalse(report["incomplete"])

    def test_forced_termination_is_incomplete_even_with_restored_attributes(self):
        report, _ = self.drive(r'''
import os
os.write(1, b"READY")
os.read(0, 1)
''', [{"wait": "READY"}], driver_exit=3)
        self.assertEqual(report["steps"], [True])
        self.assertEqual(report["exit"], -9)
        self.assertTrue(report["restored"])
        self.assertTrue(report["incomplete"])

    def test_nonzero_natural_exit_is_preserved(self):
        report, _ = self.drive("raise SystemExit(7)", [])
        self.assertEqual(report["exit"], 7)
        self.assertFalse(report["incomplete"])

    def test_body_wait_rejects_history_sidebar_tabs_and_footer(self):
        for cols, rows, draw in [
            (120, 40, b"\x1b[1;1HOLD-BODY\x1b[2J\x1b[1;1HSessions\x1b[40;23HFleets"),
            (40, 10, b"\x1b[2;1HOLD-BODY\x1b[2J\x1b[1;1HSessions\x1b[10;1HFleets"),
        ]:
            with self.subTest(cols=cols):
                child = ("import os, tty; tty.setraw(0); os.write(1, " + repr(draw)
                         + "); assert os.read(0, 1) == b'q'")
                report, _ = self.drive(child, [
                    {"wait": "Sessions"},
                    {"wait": "OLD-BODY", "body": True, "timeout": 0.15},
                    {"wait": "Sessions", "body": True, "timeout": 0.15},
                    {"wait": "Fleets", "body": True, "timeout": 0.15},
                    {"send": "q"},
                ], cols, rows)
                self.assertEqual(report["steps"], [True, False, False, False, True])

    def test_body_wait_observes_current_wide_and_narrow_body(self):
        for cols, rows, cup in [(120, 40, b"\x1b[1;23H"), (40, 10, b"\x1b[2;1H")]:
            with self.subTest(cols=cols):
                child = ("import os, tty; tty.setraw(0); os.write(1, " + repr(cup + b"Sessions")
                         + "); assert os.read(0, 1) == b'q'")
                report, _ = self.drive(child, [
                    {"wait": "Sessions", "body": True}, {"send": "q"},
                ], cols, rows)
                self.assertEqual(report["steps"], [True, True])
                self.assertEqual(report["exit"], 0)

    def test_detail_wait_binds_the_selected_synthetic_id(self):
        report, _ = self.drive(r'''
import os, tty
tty.setraw(0)
os.write(1, b"\x1b[1;23HSession\x1b[2;23HSynthetic title\x1b[3;23Hthr_syn_other")
assert os.read(0, 1) == b"n"
os.write(1, b"\x1b[2J\x1b[1;23HSession\x1b[2;23HSynthetic title\x1b[3;23Hthr_syn_selected")
assert os.read(0, 1) == b"q"
''', [
            {"wait": "Synthetic title", "body": True},
            {"wait": "thr_syn_selected", "body": True, "timeout": 0.15},
            {"send": "n"},
            {"wait": "thr_syn_selected", "body": True},
            {"send": "q"},
        ])
        self.assertEqual(report["steps"], [True, False, True, True, True])
        self.assertEqual(report["exit"], 0)


if __name__ == "__main__":
    unittest.main()
