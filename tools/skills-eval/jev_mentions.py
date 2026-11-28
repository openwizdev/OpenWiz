import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide


def extra(text, ask, already=frozenset()):
    if ask is None or not isinstance(text, str) or not text.strip():
        return set()
    root = decide.load()
    site = root['sites']['mentions']
    open_files = {name: spec for name, spec in site['files'].items() if name not in already}
    needed = {term['question'] for spec in open_files.values() for term in spec['terms']}
    if not needed:
        return set()
    try:
        response = ask.system_one(text, {name: q for name, q in site['questions'].items() if name in needed})
    except client.TypeSafeError:
        return set()
    found = set()
    for filename, spec in open_files.items():
        try:
            value = decide.signal(response, spec, root)
        except client.TypeSafeError:
            continue
        if value is not None and value >= spec['act']:
            found.add(filename)
    return found
