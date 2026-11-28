import importlib.machinery
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import client
import decide

TAIL_CHARS = 4000
SIGNED_OUT = re.compile(r'sign|login|auth|401|unauthori[sz]ed|expired', re.I)
URL_CREDENTIAL = re.compile(r'[a-z][a-z0-9+.-]*://[^\s/@]*:[^\s/@]*@', re.I)
KIT = HERE.parents[1] / 'kernel' / 'driver-kit' / 'kit.py'


def kit_check():
    try:
        loader = importlib.machinery.SourceFileLoader('openwiz_turn_end_kit', str(KIT))
        spec = importlib.util.spec_from_loader('openwiz_turn_end_kit', loader)
        kit = importlib.util.module_from_spec(spec)
        loader.exec_module(kit)
        return kit.holds_credential
    except Exception:
        return None


def prose(raw):
    lines = []
    for line in raw.splitlines():
        try:
            if isinstance(json.loads(line), (dict, list)):
                continue
        except ValueError:
            pass
        if line.strip():
            lines.append(line.strip())
    return '\n'.join(lines)


def state(raw, holds_credential=None):
    if not isinstance(raw, str):
        return None
    text = prose(raw)
    if not text or SIGNED_OUT.search(text):
        return None
    check = kit_check() if holds_credential is None else holds_credential
    if check is None or check(text) or URL_CREDENTIAL.search(text):
        return None
    return text[-TAIL_CHARS:]


def usage_limit(raw, ask=None, holds_credential=None):
    sent = state(raw, holds_credential)
    if sent is None:
        return False
    ask = client.from_env() if ask is None else ask
    if ask is None:
        return False
    root = decide.load()
    site = root['sites']['turn_end']
    try:
        response = ask.system_one(sent, site['questions'])
        value = decide.signal(response, site, root)
    except client.TypeSafeError:
        return False
    return value is not None and value >= site['act']
