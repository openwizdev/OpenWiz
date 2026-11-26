"""Add required-doc names the keyword scan missed.

Each document is its own question. AGENTS.md is two questions, one for the
file and one for the project agent instructions, combined with the noisy-or
weights in config.json. All of the questions go out in one request. A Noul
in the uncertain band does not add that file. Keyword hits are kept either
way. No key, or any error, adds nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide


def extra(text, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None or not isinstance(text, str) or not text.strip():
        return set()
    root = decide.load()
    site = root['sites']['mentions']
    try:
        response = ask.system_one(text, site['questions'])
    except client.TypeSafeError:
        return set()
    found = set()
    for filename, spec in site['files'].items():
        try:
            value = decide.signal(response, spec, root)
        except client.TypeSafeError:
            continue
        if value is not None and value >= spec['act']:
            found.add(filename)
    return found
