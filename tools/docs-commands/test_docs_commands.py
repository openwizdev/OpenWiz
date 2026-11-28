#!/usr/bin/env python3
"""Offline acceptance tests for the Markdown command runner."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from textwrap import dedent
import unittest


TOOL = Path(__file__).with_name("docs_commands.py")


class DocsCommandsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.caller_home = self.root / "caller-home"
        self.caller_home.mkdir()
        self.caller_bin = self.root / "caller-bin"
        self.caller_bin.mkdir()

    def write(self, name, content):
        path = self.root / name
        path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
        return path

    def invoke(self, *names):
        return subprocess.run(
            [sys.executable, "-I", str(TOOL), *names],
            cwd=self.root,
            env={
                **os.environ,
                "HOME": str(self.caller_home),
                "PATH": f"{self.caller_bin}:{os.defpath}",
                "GH_TOKEN": "synthetic-secret",
                "BOAT_TOKEN": "synthetic-secret",
                "XDG_CONFIG_HOME": str(self.caller_home),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )

    def test_passing_shells_and_multiple_files(self):
        self.write("first file.md", """
            # Commands
            ```sh
            value=synthetic
            test "$(printf 'sh ran with %s' "$value")" = 'sh ran with synthetic'
            ```
            """)
        self.write("next.md", """
            ~~~~bash
            values=(synthetic)
            [[ ${values[0]} == synthetic ]]
            ~~~~
            """)
        result = self.invoke("first file.md", "next.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.splitlines(), ["PASS first file.md:2", "PASS next.md:1"])

    def test_failing_command_stops_its_block_and_other_blocks_run(self):
        self.write("commands.md", """
            ```sh
            : before failure
            false
            exit 99
            ```
            ```shell
            true
            ```
            ```bash
            false | true
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout.splitlines(), [
            "FAIL commands.md:1 (exit 1)", "PASS commands.md:6", "FAIL commands.md:9 (exit 1)",
        ])

    def test_skip_reports_its_source_and_reason(self):
        self.write("commands.md", """
            ```sh no-run: needs a signed-in test account
            exit 9
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKIP commands.md:1", result.stdout)
        self.assertIn("needs a signed-in test account", result.stdout)

    def test_missing_or_empty_skip_reasons_fail_before_execution(self):
        for info in ("sh no-run", "bash no-run:", "shell no-run:   ", "sh no-run missing-colon"):
            with self.subTest(info=info):
                sentinel = self.root / "should-never-run"
                self.write("commands.md", f"```{info}\ntouch '{sentinel}'\n```\n")
                result = self.invoke("commands.md")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("FAIL commands.md:1", result.stdout)
                self.assertIn("no-run requires a reason", result.stdout)
                self.assertFalse(sentinel.exists())

    def test_examples_in_other_fences_are_ignored_and_nested_fences_run(self):
        self.write("commands.md", """
            ````markdown
            ```sh
            exit 99
            ```
            ````

            10. Example

                ```sh
                true
                ```

            > ~~~ sh
            > true
            > ~~~

                ```sh
                exit 99
                ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.splitlines(), ["PASS commands.md:9", "PASS commands.md:13"])

    def test_missing_input_fails_and_other_files_run(self):
        self.write("commands.md", "```sh\ntrue\n```\n")
        result = self.invoke("missing.md", "commands.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL missing.md", result.stdout)
        self.assertIn("PASS commands.md:1", result.stdout)

    def test_cli_reports_status_without_exposing_child_output(self):
        self.write("commands.md", """
            ```sh
            printf 'synthetic-private-output\\n' >&2
            exit 7
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL commands.md:1 (exit 7)", result.stdout)
        self.assertNotIn("synthetic-private-output", result.stdout)

    def test_home_credentials_fakes_and_network_are_isolated(self):
        for name in ("gh", "openwiz", "room-cli", "boat", "aws"):
            executable = self.write(name, "#!/bin/sh\nprintf 'caller command ran\\n'\nexit 90\n")
            executable.rename(self.caller_bin / name)
            (self.caller_bin / name).chmod(0o755)
        home_record = self.root / "home-record"
        self.write("commands.md", f"""
            ```sh
            test "$PWD" = "$HOME"
            test "$HOME" != '{self.caller_home}'
            test "${{GH_TOKEN+x}}${{BOAT_TOKEN+x}}" = ''
            test "$XDG_CONFIG_HOME" = "$HOME/.config"
            test "$(readlink /proc/self/ns/net)" != '{os.readlink("/proc/self/ns/net")}'
            printf '%s\\n' "$HOME" > '{home_record}'
            touch "$HOME/first-block"
            {{
                gh auth login
                openwiz fleet start
                room-cli machine start
                boat new
                aws ec2 run-instances
            }} 2> "$HOME/fakes"
            test "$(cat "$HOME/fakes")" = "$(printf 'fake: %s\\n' gh openwiz room-cli boat aws)"
            ```
            ```sh
            test ! -e "$HOME/first-block"
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.splitlines(), ["PASS commands.md:1", "PASS commands.md:18"])
        home = Path(home_record.read_text(encoding="utf-8").strip())
        self.assertFalse(home.exists())
        self.assertEqual(list(self.caller_home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
