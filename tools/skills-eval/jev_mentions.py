import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide


def extra(text, ask):
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
