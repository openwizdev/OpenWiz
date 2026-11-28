import re

import client
import decide

SHA = re.compile(r'[0-9a-f]{40}\Z')
MAX_WORD_CHARS = 40


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
    if len(line.removeprefix('VERDICT: ').split(' at ', 1)[0]) > MAX_WORD_CHARS:
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


def sent_state(line):
    if exact(line) or not _commit(line):
        return None
    word = line.removeprefix('VERDICT: ').split(' at ', 1)[0]
    if len(word) > MAX_WORD_CHARS:
        return None
    return f'VERDICT: {word}'
