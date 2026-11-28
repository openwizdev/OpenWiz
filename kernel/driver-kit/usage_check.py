#!/usr/bin/env python3
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
from tempfile import TemporaryFile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent.parent / "contracts"
SCHEMA = CONTRACTS / "usage.v1.schema.json"
REQUEST = {"accounts": [{"label": "demo", "harness": "claude"}]}
SELF = os.getpid()

spec = importlib.util.spec_from_file_location("driver_kit", HERE / "kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


def children(pid):
    try:
        tasks = list(Path(f"/proc/{pid}/task").iterdir())
    except FileNotFoundError:
        return
    for task in tasks:
        try:
            row = (task / "children").read_text(encoding="ascii")
        except FileNotFoundError:
            continue
        yield from map(int, row.split())


def process_issue():
    # PRIVACY: inspect only descendants of this check, with the kit's pinned process handle.
    seen = {SELF}
    pending = [(pid, SELF) for pid in children(SELF)]
    while pending:
        pid, parent = pending.pop()
        if pid in seen:
            continue
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
            fields = stat.rpartition(")")[2].split()
            since = fields[19]
            if fields[0] in "ZX" or int(fields[1]) != parent:
                continue
            seen.add(pid)
            env, _ = kit.Kit.details(pid, tries=1, since=since)
            descendants = list(children(pid))
            if kit.Kit.running(pid, since):
                pending.extend((child, pid) for child in descendants)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            return "could not inspect a driver process"
        for entry in env:
            name, _, value = entry.partition("=")
            if kit.holds_credential(value) and os.environ.get(name) != value:
                return "process environment contained a credential"
    return None


def has_children():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return False
        if pid == 0:
            return True


def clean_up():
    deadline = time.monotonic() + 2
    while has_children():
        if time.monotonic() >= deadline:
            raise TimeoutError
        for pid in children(SELF):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
        time.sleep(kit.SAMPLE_SECONDS)


def check_answer(status, stdout, stderr, schema, errors):
    # SECURITY: output and validator diagnostics can contain arbitrary driver data.
    if kit.holds_credential(stdout) or kit.holds_credential(stderr):
        return "fail output contained a credential"
    try:
        answer = kit.parse(stdout)
    except ValueError:
        return "fail driver did not print one JSON value"
    if any(kit.holds_credential(text) for text in kit.texts(answer)):
        return "fail output contained a credential"
    if status == 1 and not kit.invalid(answer, kit.load_schema()["error"]):
        return "none" if answer["error"] == "unknown command" else "fail driver refused usage"
    if status != 0:
        return "fail driver exited unsuccessfully"
    if errors(answer, schema["$defs"]["response"], schema):
        return "fail response does not match the usage schema"
    return "pass"


def check(driver, timeout):
    process_tree = Path(f"/proc/{SELF}/task/{SELF}/children")
    if not sys.platform.startswith("linux") or not process_tree.is_file() or not kit.enable_subreaper():
        return "fail process monitoring requires Linux with subreaping"
    schema = kit.parse(SCHEMA.read_text(encoding="utf-8"))
    errors = runpy.run_path(str(CONTRACTS / "fixtures/settings/test_fixtures.py"))["errors"]
    with TemporaryFile() as request, TemporaryFile() as out, TemporaryFile() as err:
        request.write(json.dumps(REQUEST).encode("utf-8"))
        request.seek(0)
        deadline = time.monotonic() + timeout
        process = subprocess.Popen([driver, "usage"], stdin=request, stdout=out, stderr=err, start_new_session=True)
        try:
            issue = None
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "fail driver timed out"
                issue = issue or process_issue()
                try:
                    process.wait(timeout=min(remaining, kit.SAMPLE_SECONDS))
                except subprocess.TimeoutExpired:
                    continue
            if time.monotonic() > deadline:
                return "fail driver timed out"
            issue = issue or process_issue()
            if issue:
                return "fail " + issue
            if has_children():
                return "fail a driver process is still running"
            out.seek(0)
            err.seek(0)
            return check_answer(process.returncode, out.read().decode("utf-8"),
                                err.read().decode("utf-8", errors="replace"), schema, errors)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            clean_up()


def seconds(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("the timeout must be positive and finite")
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True, type=Path)
    parser.add_argument("--timeout", type=seconds, default=120, help="driver time limit in seconds")
    args = parser.parse_args()
    try:
        result = check(str(args.driver.absolute()), args.timeout)
    except UnicodeError:
        result = "fail driver output is not UTF-8"
    except (TimeoutError, subprocess.TimeoutExpired):
        result = "fail could not clean up driver processes"
    except (OSError, ValueError, AssertionError, LookupError, OverflowError, RecursionError, kit.Unusable):
        result = "fail could not complete usage check"
    print("usage: " + result)
    return int(result.startswith("fail "))


if __name__ == "__main__":
    sys.exit(main())
