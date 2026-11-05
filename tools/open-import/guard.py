#!/usr/bin/env python3
"""Per-PR carriage guard: refuse added paths the importer would not classify."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LIST = 'tools/open-import/paths.json'

# The importer's own classifier, loaded rather than copied, so the guard and
# the importer cannot disagree about a path.
_spec = importlib.util.spec_from_file_location('open_import', HERE / 'import.py')
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)

HOW = """Classify each one in this pull request:
- public: add a matching `source` entry in tools/open-import/paths.json:
  the exact path, or its folder as <folder>/**;
- private or retiring: put it under an existing private class (for example private/),
  or extend the contract's private/retiring classes in tools/open-import/import.py
  for its own review."""


def classify(name, rules):
    """The importer's class for one path: public, keep, private or None (unlisted)."""
    if importer.carries(name, rules):
        return 'public'
    if importer.private_or_retired(name):
        return 'private'
    if name in rules['keep']:
        return 'keep'
    return None


def rules_at(repo, head):
    rules = json.loads(importer.git(repo, 'cat-file', 'blob', f'{head}:{LIST}'))
    if (not isinstance(rules, dict) or set(rules) != {'source', 'keep'} or
            any(not isinstance(rules[k], list) or
                any(not isinstance(v, str) for v in rules[k]) for k in rules)):
        raise ValueError('carriage list shape')
    return rules


def added(repo, base, head):
    # Paths at head that neither main nor the branch point has. Renames count
    # at their new name; deleted and modified paths are not added.
    fork = importer.git(repo, 'merge-base', base, head).decode().strip()
    known = importer.entries(repo, base).keys() | importer.entries(repo, fork).keys()
    return sorted(importer.entries(repo, head).keys() - known)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--base', required=True, help='the target branch commit (main)')
    parser.add_argument('--head', default='HEAD', help='the change as it would land')
    args = parser.parse_args()
    try:
        repo = importer.repository(args.repo)
        base, head = importer.oid(repo, args.base), importer.oid(repo, args.head)
        rules = rules_at(repo, head)
        paths = added(repo, base, head)
        unclassified = [n for n in paths if classify(n, rules) is None]
    except (importer.Refused, OSError, ValueError, UnicodeError):
        # Fail closed; never echo Git stderr or file contents.
        error = sys.exc_info()[1]
        detail = str(error) if isinstance(error, importer.Refused) else 'unreadable input or invalid shape'
        print(f'carriage guard error: {detail} (base, head or {LIST})', file=sys.stderr)
        return 2
    if unclassified:
        print(f'carriage guard: {len(unclassified)} of {len(paths)} added paths are not classified.')
        print('Unclassified added paths:')
        print('\n'.join(unclassified))
        print()
        print(HOW)
        return 1
    print(f'carriage guard: all {len(paths)} added paths are classified')
    return 0


if __name__ == '__main__':
    sys.exit(main())
