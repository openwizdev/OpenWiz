#!/usr/bin/env python3
"""The tests the selector picks from (#432, K15), listed from the tree.

  python3 -I ci/select/units.py [ROOT]    # one test id per line

Ids are the CI selection record's (contracts/ci-selection.v1.md, "Test ids"):
- `rust:lib:<package>`: every test of one workspace package other than
  openwiz-tests (`cargo test -p <package>`: its library, binaries and doc
  tests, a superset of the contract's `--lib`);
- `rust:test:<target>`: one openwiz-tests `[[test]]` target
  (`cargo test -p openwiz-tests --test <target>`);
- `web:unit:<name>`, `web:browser:<name>`: one file of apps/web's
  `test/unit/**/*.test.ts` or `test/browser/**/*.test.mjs` (package.json's
  globs), by its name without folder or extension.

Anything this can't account for is an error (the selector then runs
everything): a workspace member it can't read, an openwiz-tests target
`cargo test` would run that isn't a `[[test]]`, two files with one name.
"""
import glob
import os
import re
import sys
import tomllib

NAME = re.compile(r'[A-Za-z0-9._-]+')
TESTS_PACKAGE = 'openwiz-tests'
UNIT_GLOB = 'apps/web/test/unit/**/*.test.ts'
BROWSER_GLOB = 'apps/web/test/browser/**/*.test.mjs'


class UnitError(Exception):
    pass


def _toml(path):
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise UnitError(f'{path}: {e}') from e


def _name(kind, name):
    if not NAME.fullmatch(name):
        raise UnitError(f'an odd {kind} name {name!r}')
    return name


def rust_units(root):
    """The Rust test ids, and for each, its cargo arguments."""
    ws = _toml(os.path.join(root, 'Cargo.toml')).get('workspace', {})
    members = ws.get('members')
    if not isinstance(members, list) or not members or ws.get('exclude'):
        raise UnitError('Cargo.toml: workspace.members is not a plain list')
    out = {}
    for member in members:
        if not isinstance(member, str) or any(c in member for c in '*?[') or member.startswith('/') \
                or '..' in member.split('/'):
            raise UnitError(f'Cargo.toml: an odd member {member!r}')
        manifest = _toml(os.path.join(root, member, 'Cargo.toml'))
        name = manifest.get('package', {}).get('name')
        if not isinstance(name, str):
            raise UnitError(f'{member}/Cargo.toml: no package name')
        if name != TESTS_PACKAGE:
            uid = 'rust:lib:' + _name('package', name)
            out[uid] = ['-p', name]
            continue
        pkg = manifest['package']
        for key in ('autobins', 'autotests', 'autoexamples', 'autobenches'):
            if pkg.get(key) is not False:
                raise UnitError(f'{member}/Cargo.toml: {key} must be false, so every target is listed')
        if 'lib' in manifest or os.path.exists(os.path.join(root, member, 'src/lib.rs')):
            raise UnitError(f'{member}/Cargo.toml: a library target, which no test id names')
        for kind in ('bin', 'example', 'bench'):
            for t in manifest.get(kind, []):
                if t.get('test', kind == 'bin') is not False:
                    raise UnitError(f'{member}/Cargo.toml: [[{kind}]] {t.get("name")!r} has tests')
        for t in manifest.get('test', []):
            if t.get('test', True) is not True or t.get('harness', True) is not True:
                raise UnitError(f'{member}/Cargo.toml: [[test]] {t.get("name")!r} is not a plain test target')
            uid = 'rust:test:' + _name('target', t.get('name', ''))
            if uid in out:
                raise UnitError(f'two test targets named {uid}')
            out[uid] = ['-p', name, '--test', t['name']]
    return out


def web_units(root):
    """The web test ids, and for each, its file under apps/web."""
    out = {}
    for kind, pattern, suffix in (('unit', UNIT_GLOB, '.test.ts'), ('browser', BROWSER_GLOB, '.test.mjs')):
        for path in sorted(glob.glob(pattern, root_dir=root, recursive=True)):
            uid = f'web:{kind}:' + _name('file', os.path.basename(path)[:-len(suffix)])
            if uid in out:
                raise UnitError(f'two files named {uid}: {out[uid]} and {path}')
            out[uid] = path[len('apps/web/'):]
    return out


def list_units(root):
    units = {**rust_units(root), **web_units(root)}
    if not units:
        raise UnitError('no tests found')
    return units


if __name__ == '__main__':
    for uid in sorted(list_units(sys.argv[1] if len(sys.argv) > 1 else '.')):
        print(uid)
