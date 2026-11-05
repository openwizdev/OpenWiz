#!/usr/bin/env python3
"""Reject unsafe fixture sources before any build or binary runs. Synthetic only."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path.cwd()
LIB = Path(__file__).resolve().with_name("lib.sh")
failed = False
with tempfile.TemporaryDirectory(prefix="kit13-source-guards-") as tmp:
    tmp = Path(tmp)
    # The old lib reaches cargo. This stand-in records that mistake and exits;
    # neither a production openwiz nor any room-cli can run in these probes.
    cargo = tmp / "cargo"
    cargo.write_text('#!/bin/sh\ntouch "$KIT13_BUILD_MARKER"\nexit 89\n')
    cargo.chmod(0o700)
    for name, source, words in (("missing", None, "KIT_SOURCE_ROOT is required"),
                                ("bundled", ROOT, "PATH-based release source"),
                                ("unknown", tmp, "PATH-based release source")):
        marker = tmp / (name + ".built")
        env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ["PATH"],
                   KIT13_BUILD_MARKER=str(marker))
        for key in ("KIT_SOURCE_ROOT", "KIT_NO_BUILD", "KIT_KEEP_WORK"):
            env.pop(key, None)
        if source is not None:
            env["KIT_SOURCE_ROOT"] = str(source)
        p = subprocess.run(["sh", "-c", '. "$1"', "guard-test", str(LIB)], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        good = p.returncode != 0 and words in p.stderr.decode() and not marker.exists()
        print("kit test %s: source guard %s refuses before build or binary execution" %
              ("ok" if good else "FAILED", name), flush=True)
        failed |= not good
raise SystemExit(1 if failed else 0)
