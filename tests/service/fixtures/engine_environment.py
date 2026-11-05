"""Synthetic installed manager -> service-fixture environment, never a supervisor."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
state, source = map(Path, sys.argv[1:])
root = state / 'synthetic-installation'
builds = state / 'service/builds'


def load(path):
    spec = importlib.util.spec_from_file_location('synthetic_runtime_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if not root.exists():
    # Use the existing real installer/manifest verifier. Only its package bytes
    # and injected host facts are synthetic; no executable or supervisor runs.
    fixture = load(source / 'tools/install/platform/test_runtime.py').Runtime()
    fixture.setUp()
    try:
        original = fixture.manager('x86_64-unknown-linux-gnu')
        original.inspect()
        os.makedirs(root, mode=0o700)
        os.makedirs(builds, mode=0o700)
        build = builds / original.build.name
        shutil.copytree(original.build, build)
        (root / 'current').symlink_to(build)
    finally:
        fixture.doCleanups()
module = load(root / 'current/runtime/platform/runtime.py')
manager = module.Manager(root, state, system='Linux', machine='x86_64')
manager.inspect()
print(json.dumps({'environment': manager.env, 'definition': manager.definition().decode()}))
