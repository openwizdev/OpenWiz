"""The previous plan-limit lines, and the weighted Nouls in config.json.

Keep `exact` equal to `exact_plan_limit` in `crates/cli/src/typesafe.rs`.
A plan-limit stop, ordinary work, and a sign-in problem are three questions
in one request. The weights are in the config. An uncertain Noul, a missing
key, or any error leaves the exact lines as the only match.
"""

import client
import decide

RESET = "You've hit your limit · resets "


def exact(text):
    for line in text.splitlines():
        line = line.strip()
        if line in ('Claude usage limit reached', "You've hit your limit"):
            return True
        if line.startswith(RESET) and line[len(RESET):]:
            return True
    return False


def shaped(text, recorded):
    if exact(text):
        return True
    if not isinstance(recorded, dict):
        return False
    root = decide.load()
    site = root['sites']['plan_limit']
    try:
        value = decide.signal(recorded, site, root)
    except client.TypeSafeError:
        return False
    return value is not None and value >= site['act']
