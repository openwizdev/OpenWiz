import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client
import decide

TAIL_CHARS = 4000


def usage_limit(text, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None or not isinstance(text, str) or not text.strip():
        return False
    root = decide.load()
    site = root['sites']['turn_end']
    try:
        response = ask.system_one(text[-TAIL_CHARS:], site['questions'])
        value = decide.signal(response, site, root)
    except client.TypeSafeError:
        return False
    return value is not None and value >= site['act']
