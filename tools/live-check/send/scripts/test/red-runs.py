#!/usr/bin/env python3
"""Compatibility entrypoint for the inherited mutant inventory."""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[3]
if not os.environ.get("RED_LOGS"):
    sys.exit("set RED_LOGS to an evidence directory outside tools/live-check")
args = [sys.executable, str(root / "mutants.py"), "--profile", "send", "--logs",
        os.environ["RED_LOGS"], "--jobs", os.environ.get("RED_JOBS", "1")]
if os.environ.get("RED_MUTANTS"):
    args += ["--inventory", os.environ["RED_MUTANTS"]]
if os.environ.get("RED_ONLY"):
    args += ["--only", os.environ["RED_ONLY"]]
os.execv(sys.executable, args)
