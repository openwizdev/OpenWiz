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
