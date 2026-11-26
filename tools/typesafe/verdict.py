"""Exact `VERDICT:` lines, and the confidence gate in `canonical_verdict_line`.

Keep this equal to `crates/cli/src/typesafe.rs`. The commit comes from the
line. A Choice of approve or changes is paired with a companion Noul that
asks whether either option fits. There is no none-of-the-above option.
Low Choice confidence, or a companion Noul in the uncertain band, leaves
the line unchanged.
"""

import re

import client
import decide

SHA = re.compile(r'[0-9a-f]{40}\Z')
QUESTIONS = {
    'kind': {
        'type': 'choice',
        'instructions': 'What verdict does this review comment give?',
        'criteria': {
            'approve': 'The reviewer approves the commit.',
            'changes': 'The reviewer wants changes on the commit.',
            'not_a_verdict': 'This is not an approve or changes verdict.',
        },
    },
    'is_verdict': {
        'type': 'noul',
        'instructions': 'This comment is a reviewer\'s approve or request-changes verdict for the commit it names.',
        'criteria': {
            'true': 'The reviewer is giving a verdict on that commit.',
            'false': 'The line only mentions a verdict, or it is not one.',
        },
    },
}


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
    if not _commit(line) or not isinstance(recorded, dict):
        return None
    root = decide.load()
    site = root['sites']['verdict']
    try:
        ready = decide.choice_ready(recorded, 'kind', site['confidence'])
        companion = client.noul(recorded, 'is_verdict')
    except client.TypeSafeError:
        return None
    if ready is None or decide.uncertain_noul(companion, root):
        return None
    if companion < site['companion_yes']:
        return None
    name = ready[0]
    if name == 'approve':
        return 'APPROVE'
    if name == 'changes':
        return 'CHANGES'
    return None


def _commit(line):
    rest = line.removeprefix('VERDICT: ')
    if rest == line or ' at ' not in rest:
        return False
    _, commit = rest.split(' at ', 1)
    return SHA.fullmatch(commit) is not None
