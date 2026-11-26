"""Exact `VERDICT:` lines, and the 0.9 gate in `canonical_verdict_line`.

Keep this equal to `crates/cli/src/typesafe.rs`. The commit comes from the
line. A recorded answer never supplies one.
"""

import re

ACT = 0.9
SHA = re.compile(r'[0-9a-f]{40}\Z')


def exact(line):
    rest = line.removeprefix('VERDICT: ')
    if rest == line or ' at ' not in rest:
        return None
    word, commit = rest.split(' at ', 1)
    if SHA.fullmatch(commit) is None:
        return None
    if word in ('APPROVE', 'CHANGES'):
        return word
    return None


def shaped(line, recorded):
    found = exact(line)
    if found:
        return found
    if exact(line) is None and not _commit(line):
        return None
    answers = (recorded or {}).get('answers') or {}
    kind = answers.get('kind') or {}
    name = kind.get('choice')
    probabilities = kind.get('probabilities') or {}
    confidence = kind.get('confidence')
    noul = (answers.get('is_verdict') or {}).get('noul')
    probability = probabilities.get(name)
    if name not in ('approve', 'changes'):
        return None
    if not _high(probability) or not _high(confidence) or not _high(noul):
        return None
    return 'APPROVE' if name == 'approve' else 'CHANGES'


def _commit(line):
    rest = line.removeprefix('VERDICT: ')
    if rest == line or ' at ' not in rest:
        return False
    _, commit = rest.split(' at ', 1)
    return SHA.fullmatch(commit) is not None


def _high(value):
    return type(value) in (int, float) and value >= ACT
