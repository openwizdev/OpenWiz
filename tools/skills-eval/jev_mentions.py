"""Add required-doc names the keyword scan missed.

A false yes makes a skill look like it named a file it did not, so the gate
is 0.9, above the docs' 0.7 starting point. Keyword hits are kept either way.
No key, or any error, adds nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client

YES = 0.9
QUESTIONS = {
    'agents': {
        'type': 'noul',
        'instructions': 'The text tells the reader to follow AGENTS.md or the project agent instructions.',
        'criteria': {
            'true': 'It points the reader at those instructions.',
            'false': 'It does not.',
        },
    },
    'glossary': {
        'type': 'noul',
        'instructions': 'The text tells the reader to use the glossary.',
        'criteria': {
            'true': 'It points the reader at the glossary.',
            'false': 'It does not, even if the letters appear inside another word.',
        },
    },
    'adr': {
        'type': 'noul',
        'instructions': 'The text tells the reader to read an architecture decision record.',
        'criteria': {
            'true': 'It points the reader at an ADR.',
            'false': 'It does not.',
        },
    },
}
FILES = {'agents': 'AGENTS.md', 'glossary': 'GLOSSARY.md', 'adr': 'docs/adr/'}


def extra(text, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None or not isinstance(text, str) or not text.strip():
        return set()
    try:
        response = ask.system_one(text, QUESTIONS)
        return {FILES[name] for name in FILES if client.noul(response, name) >= YES}
    except client.TypeSafeError:
        return set()
