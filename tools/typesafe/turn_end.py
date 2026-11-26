"""Say whether a finished turn stopped on a usage limit written as text.

A plan usage limit and a rate limit are separate Nouls, sent in one
request and combined with the noisy-or weights in config.json. Structured
usage-limit events stay authoritative and never reach this module. A Noul
in the uncertain band, a missing key, or any error returns false, and the
caller keeps "finished with no tool call".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client
import decide


def usage_limit(text, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None or not isinstance(text, str) or not text.strip():
        return False
    root = decide.load()
    site = root['sites']['turn_end']
    try:
        response = ask.system_one(text, site['questions'])
        value = decide.signal(response, site, root)
    except client.TypeSafeError:
        return False
    return value is not None and value >= site['act']
