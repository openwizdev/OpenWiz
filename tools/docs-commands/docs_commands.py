#!/usr/bin/env python3

import argparse
from collections.abc import Iterator
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile


SHELLS = {"sh": ("/bin/sh", "-e"), "bash": ("/bin/bash", "-e", "-o", "pipefail")}
SHELLS["shell"] = SHELLS["sh"]
QUOTE = re.compile(r" {0,3}>[ \t]?")
LIST = re.compile(r" {0,3}(?:[-+*]|[0-9]{1,9}[.)])(?: {1,4}(?! )| )")
FENCE = re.compile(r"( {0,3})(`{3,}|~{3,})(.*)")
NO_RUN = re.compile(r"no-run(?=$|[:\s])")
SYSTEM_PATH = "/usr/bin:/bin"
FAKES = (
    "aws", "az", "boat", "boat-dev", "docker", "flyctl", "gcloud", "gh",
    "kubectl", "openwiz", "podman", "room-cli", "ssh", "terraform",
)
TIMEOUT = 30


def strip_list_and_quote_prefixes(line: str, containers: list[int | None]) -> tuple[str, int]:
    for depth, indent in enumerate(containers):
        if indent is None:
            quote = QUOTE.match(line)
            if quote is None:
                return line, depth
            line = line[quote.end():]
        elif line.startswith(" " * indent) or not line.strip():
            line = line[indent:]
        else:
            return line, depth
    return line, len(containers)


def shell_fences(markdown: str) -> Iterator[tuple[int, str, str, str]]:
    containers: list[int | None] = []
    fence = None
    for number, line in enumerate(markdown.split("\n"), 1):
        content, depth = strip_list_and_quote_prefixes(line, containers)
        if fence is not None:
            opening, indent, marker, language, info, body = fence
            closing = content.lstrip(" ")
            closes = (
                len(content) - len(closing) <= 3
                and closing.startswith(marker)
                and not closing.rstrip(" \t").strip(marker[0])
            )
            if depth == len(containers) and not closes:
                stripped = min(indent, len(content) - len(closing))
                if language in SHELLS:
                    body.append(content[stripped:])
                continue
            if language in SHELLS:
                yield opening, language, info, "\n".join(body) + "\n"
            fence = None
            if depth == len(containers):
                continue

        del containers[depth:]
        while match := (QUOTE.match(content) or LIST.match(content)):
            prefix = match.group()
            containers.append(None if ">" in prefix else len(prefix))
            content = content[match.end():]

        match = FENCE.fullmatch(content)
        if match is None:
            continue
        indent, marker, info = match.groups()
        if marker[0] == "`" and "`" in info:
            continue
        words = info.strip().split(maxsplit=1)
        language = words[0].lower() if words else ""
        fence = number, len(indent), marker, language, words[1] if len(words) > 1 else "", []

    if fence is not None:
        opening, _, _, language, info, body = fence
        if language in SHELLS:
            yield opening, language, info, "\n".join(body) + "\n"


def run_shell(shell: tuple[str, ...], body: str) -> int:
    unshare = shutil.which("unshare", path=SYSTEM_PATH)
    if unshare is None:
        raise OSError("Linux unshare is needed to run a block offline")

    with tempfile.TemporaryDirectory(prefix="docs-commands-") as temporary:
        root = Path(temporary)
        home, bin_dir, temp_dir = root / "home", root / "bin", root / "tmp"
        for directory in (home, bin_dir, temp_dir):
            directory.mkdir()
        fake = bin_dir / "fake-command"
        fake.write_text('#!/bin/sh\nprintf "fake: %s\\n" "${0##*/}" >&2\n', encoding="utf-8")
        fake.chmod(0o755)
        for name in FAKES:
            (bin_dir / name).symlink_to(fake.name)
        script = root / "block.sh"
        script.write_text(body, encoding="utf-8")

        result = subprocess.run(
            [unshare, "--user", "--map-current-user", "--net", "--pid", "--fork",
             "--mount-proc", "--kill-child", "/bin/sh", "-c",
             'printf "ready\\n"; exec "$@" >/dev/null 2>&1',
             "docs-commands", *shell, str(script)],
            cwd=home,
            env={
                "HOME": str(home),
                "PATH": f"{bin_dir}:{SYSTEM_PATH}",
                "TMPDIR": str(temp_dir),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C.UTF-8",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT,
        )
        if result.stdout != b"ready\n":
            raise OSError("could not start the offline Linux sandbox")
        return result.returncode


def report_block(location: str, language: str, info: str, body: str) -> bool:
    if NO_RUN.match(info):
        reason = info.removeprefix("no-run:").strip() if info.startswith("no-run:") else ""
        if reason:
            print(f"SKIP {location} ({reason})")
            return True
        print(f"FAIL {location} (no-run requires a reason after 'no-run:')")
        return False

    try:
        status = run_shell(SHELLS[language], body)
    except subprocess.TimeoutExpired:
        print(f"FAIL {location} (timed out after {TIMEOUT}s)")
        return False
    except OSError as error:
        print(f"FAIL {location} ({error})")
        return False

    print(f"FAIL {location} (exit {status})" if status else f"PASS {location}")
    return status == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run shell fences from Markdown files on an offline Linux CI runner.",
    )
    parser.add_argument("markdown", nargs="+", help="Markdown files to check")
    args = parser.parse_args()

    failures = 0
    for filename in args.markdown:
        try:
            markdown = Path(filename).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            print(f"FAIL {filename} ({error})")
            failures += 1
            continue
        for number, language, info, body in shell_fences(markdown):
            failures += not report_block(f"{filename}:{number}", language, info, body)
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
