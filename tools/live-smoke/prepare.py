#!/usr/bin/env python3
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import tempfile

DESCRIPTION = """Bind the combined run sheet to approved private inputs, offline."""

HERE = Path(__file__).resolve().parent
smoke = runpy.run_path(str(HERE / 'smoke.py'))
TEMPLATE = HERE / 'combined.template.json'
CREDENTIAL = re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----')


class Refused(Exception):
    def __init__(self, reason, **detail):
        super().__init__(reason)
        self.doc = dict(detail, reason=reason)


def bind(value, inputs):
    if isinstance(value, str) and value.startswith('@'):
        return inputs[value[1:]]
    if isinstance(value, list):
        return [bind(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: bind(item, inputs) for key, item in value.items()}
    return value


def names(value):
    if isinstance(value, str) and value.startswith('@'):
        return {value[1:]}
    if isinstance(value, list):
        return set().union(*map(names, value)) if value else set()
    if isinstance(value, dict):
        return names(list(value.values()))
    return set()


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)


def in_work_tree(path):
    return any((folder / '.git').exists() for folder in [path, *path.parents])


def resolve_private(path):
    text = os.fspath(path)
    if not os.path.isabs(text):
        raise Refused('unsafe_path')
    parts = text.split('/')
    depth = len(parts)
    while depth > 1 and not os.path.lexists('/'.join(parts[:depth])):
        depth -= 1
    rest = [part for part in parts[depth:] if part not in ('', '.')]
    if '..' in rest:
        raise Refused('unsafe_path')
    for index in range(1, depth + 1):
        if in_work_tree(Path(os.path.realpath('/'.join(parts[:index]) or '/'))):
            raise Refused('inside_checkout')
    resolved = Path(os.path.realpath('/'.join(parts[:depth]) or '/')).joinpath(*rest)
    if in_work_tree(resolved):
        raise Refused('inside_checkout')
    return resolved


def owner_only(path, reason):
    if not path.is_absolute():
        raise Refused(reason)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Refused(reason)


def private_output(path):
    if not path.is_absolute():
        raise Refused('inside_checkout')
    return resolve_private(path)


def read_private(path, reason):
    owner_only(path, reason)
    resolved = resolve_private(path)
    owner_only(resolved, reason)
    value = smoke['decode'](resolved.read_bytes())
    if type(value) is not dict:
        raise Refused('invalid_input')
    if any(CREDENTIAL.search(text) for text in strings(value)):
        raise Refused('credential_in_inputs')
    return value


@contextlib.contextmanager
def write_exclusive(out, text):
    with tempfile.TemporaryDirectory(dir=out.parent) as private:
        staged = Path(private) / out.name
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        yield staged
        os.link(staged, out)


def prepare(inputs_path, out):
    out = private_output(out)
    inputs = read_private(inputs_path, 'inputs_not_owner_only')
    template = smoke['decode'](TEMPLATE.read_bytes())
    wanted = names(template)
    if wanted - inputs.keys():
        raise Refused('missing_input', missing=sorted(wanted - inputs.keys()))
    if inputs.keys() - wanted:
        raise Refused('unused_input', unused=sorted(inputs.keys() - wanted))
    with write_exclusive(out, json.dumps(bind(template, inputs), indent=2) + '\n') as staged:
        kit = smoke['load_kit'](staged)
        smoke['verify_artifacts'](kit)
    result = {'prepared': True, 'kit_sha256': smoke['digest'](kit)}
    if 'release' in kit:
        result['scope_sha256'] = smoke['contract_sha'](kit['release'].get('scope'))
    return result


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--inputs', required=True, type=Path, help='absolute owner-only inputs file (inputs.py)')
    parser.add_argument('--out', required=True, type=Path, help='absolute new kit path, outside any checkout')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.inputs, args.out)))
        return 0
    except Refused as error:
        print(json.dumps(dict(error.doc, prepared=False)))
    except smoke['Refusal'] as error:
        print(json.dumps({'prepared': False, 'reason': str(error)}))
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'prepared': False, 'reason': 'invalid_input'}))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
