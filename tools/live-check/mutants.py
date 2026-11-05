#!/usr/bin/env python3
"""Run both inherited mutant inventories in isolated copies of the toolkit.

Every edit must apply once; each suite must fail its named cases and only its
listed knock-ons. No working source or shared build output is mutated. Builds
must finish before this runner starts (KIT_NO_BUILD is always set for suites).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def target(tool, name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or (tool / path).is_symlink():
        raise ValueError("mutation target must stay inside the toolkit")
    return tool / path


def load_inventory(profile, path):
    items = json.loads(Path(path).read_text())
    if not isinstance(items, list) or not items:
        raise ValueError("mutant inventory must be a nonempty array")
    for mutant in items:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", mutant["name"]):
            raise ValueError("unsafe mutant name")
        if "changes" in mutant or "delete" in mutant:
            continue
        # Compatibility with the original RED_MUTANTS protocol. Shared functions
        # moved; a custom probe must still mutate the function actually executed.
        changes = []
        for old, new in mutant.get("edits") or [[mutant["old"], mutant["new"]]]:
            candidates = [profile + "/scripts/" + mutant["file"], "core.py"]
            matches = [name for name in candidates if target(HERE, name).is_file()
                       and target(HERE, name).read_text().count(old) == 1]
            if len(matches) != 1:
                raise ValueError("mutant %s does not apply exactly once" % mutant["name"])
            changes.append({"file": matches[0], "old": old, "new": new})
        mutant["changes"] = changes
    return items


def apply(tool, mutant):
    for name in mutant.get("delete", []):
        target(tool, name).unlink()
    for edit in mutant.get("changes", []):
        path = target(tool, edit["file"])
        text = path.read_text()
        count = text.count(edit["old"])
        if count != 1:
            raise ValueError("%s: edit matches %d times" % (mutant["name"], count))
        path.write_text(text.replace(edit["old"], edit["new"]))


def verdict(mutant, code, output):
    failed = [line[len("kit test FAILED: "):] for line in output.splitlines()
              if line.startswith("kit test FAILED: ")]
    missing = [case for case in mutant["must_fail"] if not any(case in f for f in failed)]
    allowed = mutant["must_fail"] + mutant.get("may_fail", [])
    unlisted = [f for f in failed if not any(case in f for case in allowed)]
    # The inherited absent-kit control predates named cases: require the actual
    # missing driver diagnostic, never an unrelated early setup/build failure.
    absent = bool(mutant.get("delete")) and any(
        Path(name).name in output for name in mutant["delete"]) and any(
        diagnostic in output for diagnostic in ("can't open file", "cannot stat"))
    if code == 0 or missing or unlisted or (not failed and not absent):
        raise ValueError("UNEXPECTED result: exit=%s missing=%s unlisted=%s named_failures=%d" %
                         (code, missing, unlisted, len(failed)))
    return len(failed)


def fingerprint():
    digest = hashlib.sha256()
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(HERE)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run_one(item, logs, target, snapshot, resume=False):
    index, profile, mutant = item
    name = profile + "-" + mutant["name"]
    snapshot += ":" + hashlib.sha256(json.dumps(mutant, sort_keys=True).encode()).hexdigest()
    log = logs / (name + ".log")
    result_path = logs / (name + ".json")
    if resume:
        try:
            previous = json.loads(result_path.read_text())
            if (isinstance(previous, dict) and previous.get("snapshot") == snapshot
                    and previous.get("ok") is True and isinstance(previous.get("line"), str)
                    and previous.get("log_sha256") == hashlib.sha256(log.read_bytes()).hexdigest()):
                return previous["line"], True
        except (OSError, ValueError):
            pass  # Missing, partial or damaged evidence must be executed again.
    try:
        # Revoke any prior proof before touching its log or starting a new attempt.
        # An interruption or runner error can never leave an older success reusable.
        result_path.unlink(missing_ok=True)
        log.write_text("")
        with tempfile.TemporaryDirectory(prefix="live-check-mutant-") as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            tool = root / "tools" / "live-check"
            shutil.copytree(HERE, tool, ignore=shutil.ignore_patterns("__pycache__"))
            # Legacy tests inspect the selected release's contracts/UI/fixtures.
            source = Path(os.environ["KIT_SOURCE_ROOT"])
            for part in ("contracts", "tests", "apps"):
                (root / part).symlink_to(source / part, target_is_directory=True)
            apply(tool, mutant)
            script = ("sol-tests.sh" if mutant.get("suite") == "sol" else "kit-tests.sh")
            env = dict(os.environ, KIT_KEEP_GOING="1", KIT_NO_BUILD="1", KIT_TARGET=str(target),
                       KIT_ONLY=mutant.get("only", ""), SOL_ONLY=mutant.get("sol_only", ""),
                       KIT_PORT=str(21000 + index * 250))
            env.update(mutant.get("env") or {})
            proc = subprocess.run(["sh", str(tool / profile / "scripts" / "test" / script)],
                                  cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=1800)
            output = proc.stdout.decode("utf-8", "replace").replace(tmp, "<mutant-tree>")
            log.write_text(output + "\n(suite exit %d)\n" % proc.returncode)
            count = verdict(mutant, proc.returncode, output)
            line = "%s: %d named failures; red as required" % (name, count)
            result_path.write_text(json.dumps({"snapshot": snapshot, "ok": True, "line": line,
                                               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}) + "\n")
            print(line, flush=True)
            return line, True
    except Exception as error:
        with log.open("a") as f:
            f.write("\nMUTATION RUNNER ERROR: %s\n" % error)
        line = "%s: FAILED: %s" % (name, error)
        result_path.write_text(json.dumps({"snapshot": snapshot, "ok": False, "line": line}) + "\n")
        return line, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("send", "new", "both"), default="both")
    parser.add_argument("--only", help="comma-separated mutant names (unknown names refused)")
    parser.add_argument("--inventory", type=Path, help="legacy RED_MUTANTS override for one profile")
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=1)
    parser.add_argument("--resume", action="store_true", help="reuse successful results for this exact toolkit/source")
    args = parser.parse_args()
    profiles = ("send", "new") if args.profile == "both" else (args.profile,)
    if args.inventory and len(profiles) != 1:
        parser.error("a custom inventory requires one profile")
    items = [(profile, m) for profile in profiles
             for m in load_inventory(profile, args.inventory or HERE / profile / "scripts/test/red-mutants.json")]
    source = os.environ.get("KIT_SOURCE_ROOT")
    if not source or not Path(source).is_absolute():
        parser.error("KIT_SOURCE_ROOT must name the reviewed release checkout")
    target = Path(os.environ.get("KIT_TARGET", str(Path(source) / "target"))).resolve()
    for binary in ("openwiz", "openwiz-server", "fake-room-cli"):
        if not os.access(target / "release" / binary, os.X_OK):
            parser.error("build the reviewed release fixtures first: " + binary)
    selected = set(args.only.split(",")) if args.only else None
    if selected:
        unknown = selected - {m["name"] for _, m in items}
        if unknown:
            parser.error("unknown mutants: " + ",".join(sorted(unknown)))
        items = [(p, m) for p, m in items if m["name"] in selected]
    args.logs.mkdir(parents=True, exist_ok=True)
    if args.logs.resolve() == HERE or HERE in args.logs.resolve().parents:
        parser.error("logs must be outside the toolkit")
    snapshot = fingerprint() + ":" + subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"]).decode().strip()
    # Preflight every selected mutation before any suite, without modifying source.
    with tempfile.TemporaryDirectory(prefix="live-check-preflight-") as tmp:
        for index, (profile, mutant) in enumerate(items):
            tool = Path(tmp) / str(index)
            shutil.copytree(HERE, tool)
            apply(tool, mutant)
            shutil.rmtree(tool)
    batch = [(i, p, m) for i, (p, m) in enumerate(items)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda item: run_one(item, args.logs, target, snapshot, args.resume), batch))
    for line, ok in results:
        if not ok:
            print(line, flush=True)
    (args.logs / "summary.txt").write_text("\n".join(line for line, _ in results) + "\n")
    return 0 if len(results) == len(items) and all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
