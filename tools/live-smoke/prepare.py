#!/usr/bin/env python3
"""Bind the combined run sheet to approved private inputs, offline."""
import argparse
import json
import os
from pathlib import Path
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
smoke = runpy.run_path(str(HERE / 'smoke.py'))


def bind(value, inputs):
    if isinstance(value, str) and value.startswith('@'):
        return inputs[value[1:]]
    if isinstance(value, list):
        return [bind(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: bind(item, inputs) for key, item in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        inputs = smoke['decode'](args.inputs.read_bytes())
        template = smoke['decode']((HERE / 'combined.template.json').read_bytes())
        kit = bind(template, inputs)
        # Refuse overwrite, including a symlink. A kit changes only by explicit
        # preparation of a new file and gets a different reviewed digest.
        with tempfile.TemporaryDirectory(dir=args.out.parent) as private:
            staged = Path(private) / 'kit.json'
            fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(kit, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            kit = smoke['load_kit'](staged)
            smoke['verify_artifacts'](kit)
            os.link(staged, args.out)  # exclusive: never follows/replaces output
        print(json.dumps({'kit_sha256': smoke['digest'](kit), 'prepared': True}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, smoke['Refusal']):
        print(json.dumps({'prepared': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
