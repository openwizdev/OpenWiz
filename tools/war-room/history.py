#!/usr/bin/env python3
"""Immutable complete five-minute samples. No clock, pruning or collector."""
import json
import os
from pathlib import Path
import tempfile

import suite
from sources import safe_record


def _name(sample_at):
    suite.compose(sample_at)  # Validate before using any part as a file name.
    return sample_at.replace(':', '-') + '.json'


def read_all(root):
    """WR7 seam: sorted validated records; absent boundaries remain absent."""
    records = []
    for path in sorted((Path(root) / 'samples').glob('*.json')):
        record = suite.load(path)
        safe_record(record)
        suite.require(path.name == _name(record['sample_at']), 'history identity differs from file')
        records.append(record)
    return records


def latest(root):
    records = read_all(root)
    return records[-1] if records else None


def save(root, record):
    """Atomic create-if-absent, with durable bytes before visibility.

    There is deliberately no mutable latest file: max(sample_id) is the latest
    pointer, including across concurrent and out-of-order writers. An interrupted
    temporary file is never a sample. Identical duplicates return False.
    """
    safe_record(record)
    wire = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
    directory = Path(root) / 'samples'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    target = directory / _name(record['sample_at'])
    fd, name = tempfile.mkstemp(prefix='.sample-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(wire)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, target)
        except FileExistsError:
            suite.require(suite.load(target) == record, 'sample identity already has a different payload')
            return False
        # Persist the directory entry, too. An error is reported, never retried
        # as a fresh observation; a complete visible sample can be read on restart.
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    finally:
        os.unlink(name)
