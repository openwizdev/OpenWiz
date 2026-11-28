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
            printf 'sh ran with %s\\n' "$value"
            ```
            """)
        self.write("next.md", """
            ~~~~bash
            values=(synthetic)
            printf 'bash ran with %s\\n' "${values[0]}"
            ~~~~
            """)
        result = self.invoke("first file.md", "next.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS first file.md:2", result.stdout)
        self.assertIn("PASS next.md:1", result.stdout)
        self.assertIn("sh ran with synthetic", result.stdout)
        self.assertIn("bash ran with synthetic", result.stdout)

    def test_failing_command_stops_its_block_and_other_blocks_run(self):
        self.write("commands.md", """
            ```sh
            printf 'before failure\\n'
            false
            printf 'should never run\\n'
            ```
            ```shell
            printf 'next block ran\\n'
            ```
            ```bash
            false | true
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL commands.md:1", result.stdout)
        self.assertIn("before failure", result.stdout)
        self.assertNotIn("should never run", result.stdout)
        self.assertIn("PASS commands.md:6", result.stdout)
        self.assertIn("next block ran", result.stdout)
        self.assertIn("FAIL commands.md:9", result.stdout)

    def test_skip_reports_its_source_and_reason(self):
        self.write("commands.md", """
            ```sh no-run: needs a signed-in test account
            printf 'should never run\\n'
            exit 9
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKIP commands.md:1", result.stdout)
        self.assertIn("needs a signed-in test account", result.stdout)
        self.assertNotIn("should never run", result.stdout)

    def test_missing_or_empty_skip_reasons_fail_before_execution(self):
        for info in ("sh no-run", "bash no-run:", "shell no-run:   ", "sh no-run missing-colon"):
            with self.subTest(info=info):
                self.write("commands.md", f"```{info}\nprintf 'should never run\\n'\n```\n")
                result = self.invoke("commands.md")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("FAIL commands.md:1", result.stdout)
                self.assertIn("no-run requires a reason", result.stdout)
                self.assertNotIn("should never run", result.stdout)

    def test_examples_in_other_fences_are_ignored_and_nested_fences_run(self):
        self.write("commands.md", """
            ````markdown
            ```sh
            printf 'should never run\\n'
            ```
            ````

            10. Example

                ```sh
                printf 'list block ran\\n'
                ```

            > ~~~ sh
            > printf 'quoted block ran\\n'
            > ~~~

                ```sh
                printf 'should never run\\n'
                ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("should never run", result.stdout)
        self.assertIn("PASS commands.md:9", result.stdout)
        self.assertIn("list block ran", result.stdout)
        self.assertIn("PASS commands.md:13", result.stdout)
        self.assertIn("quoted block ran", result.stdout)

    def test_missing_input_fails_and_other_files_run(self):
        self.write("commands.md", "```sh\ntrue\n```\n")
        result = self.invoke("missing.md", "commands.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL missing.md", result.stdout)
        self.assertIn("PASS commands.md:1", result.stdout)

    def test_home_credentials_fakes_and_network_are_isolated(self):
        for name in ("gh", "openwiz", "room-cli", "boat", "aws"):
            executable = self.write(name, "#!/bin/sh\nprintf 'caller command ran\\n'\nexit 90\n")
            executable.rename(self.caller_bin / name)
            (self.caller_bin / name).chmod(0o755)
        self.write("commands.md", f"""
            ```sh
            test "$PWD" = "$HOME"
            test "$HOME" != '{self.caller_home}'
            test "${{GH_TOKEN+x}}${{BOAT_TOKEN+x}}" = ''
            test "$XDG_CONFIG_HOME" = "$HOME/.config"
            test "$(readlink /proc/self/ns/net)" != '{os.readlink("/proc/self/ns/net")}'
            printf '%s\\n' "$HOME"
            touch "$HOME/first-block"
            gh auth login
            openwiz fleet start
            room-cli machine start
            boat new
            aws ec2 run-instances
            ```
            ```sh
            test ! -e "$HOME/first-block"
            ```
            """)
        result = self.invoke("commands.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        for name in ("gh", "openwiz", "room-cli", "boat", "aws"):
            self.assertIn(f"fake: {name}\n", result.stdout)
        self.assertNotIn("caller command ran", result.stdout)
        self.assertIn("PASS commands.md:15", result.stdout)
        homes = [Path(line[2:]) for line in result.stdout.splitlines() if line.startswith("| /")]
        self.assertEqual(len(homes), 1, result.stdout)
        self.assertFalse(homes[0].exists())
        self.assertEqual(list(self.caller_home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
