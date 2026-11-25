#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

DEFAULT_MAX = '2.34'
SECTION_RE = re.compile(r"^Version needs section '\.gnu\.version_r' contains \d+ entr(?:y|ies):")
ENTRY_RE = re.compile(r'^\s*0x[0-9a-fA-F]+:\s+Name:\s+(\S+)\s+Flags:\s+(.+?)\s+Version:\s+\d+\s*$')
VERSION_RE = re.compile(r'^(\d+(?:\.\d+)+)$')


class CheckError(ValueError):
    pass


def parse_version(text):
    match = VERSION_RE.fullmatch(text.strip())
    if not match:
        raise CheckError(f'invalid glibc version: {text!r}')
    return tuple(int(part) for part in match[1].split('.'))


def compare_versions(left, right):
    width = max(len(left), len(right))
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def parse_verneed(output):
    if not isinstance(output, str) or not output.strip():
        raise CheckError('empty readelf output')
    in_section = False
    found_section = False
    entries = []
    for line in output.splitlines():
        if SECTION_RE.match(line):
            in_section = True
            found_section = True
            continue
        if not in_section:
            continue
        if not line.strip() or not line[0].isspace():
            in_section = False
            continue
        match = ENTRY_RE.match(line)
        if not match:
            if 'Name:' in line:
                raise CheckError(f'unparseable version need line: {line!r}')
            continue
        name, flags = match[1], match[2].strip()
        if not name.startswith('GLIBC_'):
            continue
        entries.append((name, parse_version(name[len('GLIBC_'):]), flags))
    if not found_section:
        raise CheckError("missing '.gnu.version_r' section in readelf output")
    if not entries:
        raise CheckError("no GLIBC_ version needs found in '.gnu.version_r'")
    return entries


def check_verneed(output, max_version=DEFAULT_MAX):
    limit = parse_version(max_version) if isinstance(max_version, str) else max_version
    entries = parse_verneed(output)
    violations = [(name, flags) for name, ver, flags in entries if compare_versions(ver, limit) > 0]
    if violations:
        limit_text = max_version if isinstance(max_version, str) else '.'.join(str(p) for p in limit)
        detail = ', '.join(f'{name} (Flags: {flags})' for name, flags in violations)
        raise CheckError(f'binary requires GLIBC > {limit_text}: {detail}')
    highest = entries[0]
    for entry in entries[1:]:
        if compare_versions(entry[1], highest[1]) > 0:
            highest = entry
    return highest


def run_readelf(binary, readelf='readelf'):
    path = Path(binary)
    if not path.is_file():
        raise CheckError(f'binary not found: {binary}')
    env = dict(os.environ, LC_ALL='C')
    try:
        proc = subprocess.run([readelf, '-W', '--version-info', str(path)],
                              capture_output=True, text=True, env=env)
    except OSError as exc:
        raise CheckError(f'failed to execute {readelf}: {exc}') from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f'exit {proc.returncode}'
        raise CheckError(f'{readelf} failed ({proc.returncode}): {detail}')
    return proc.stdout


def check_binary(binary, max_version=DEFAULT_MAX, readelf='readelf'):
    return check_verneed(run_readelf(binary, readelf=readelf), max_version=max_version)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check ELF GLIBC VERNEED ceiling.')
    parser.add_argument('--binary', required=True, help='Path to ELF binary')
    parser.add_argument('--max', dest='max_version', default=DEFAULT_MAX, help='Max allowed GLIBC version')
    parser.add_argument('--readelf', default='readelf', help='readelf executable name or path')
    args = parser.parse_args(argv)
    try:
        name, _, flags = check_binary(args.binary, max_version=args.max_version, readelf=args.readelf)
    except CheckError as exc:
        print(f'glibc-check: {exc}', file=sys.stderr)
        return 1
    print(f'glibc-check: ok ({args.binary}: max {name}, Flags: {flags}, ceiling {args.max_version})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
