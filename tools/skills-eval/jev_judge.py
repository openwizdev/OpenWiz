import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide


def from_response(response):
    root = decide.load()
    site = root['sites']['judge']
    try:
        value = decide.signal(response, site, root)
    except client.TypeSafeError:
        return None
    if value is None:
        return None
    if value >= site['act']:
        verdict = 'pass'
        reason = site['questions']['meets_rule']['criteria']['true']
    elif value <= site['fail_at']:
        verdict = 'fail'
        reason = site['questions']['meets_rule']['criteria']['false']
    else:
        return None
    model = response.get('model') if isinstance(response, dict) else None
    if not isinstance(model, str) or not model:
        model = client.MODEL
    return {'verdict': verdict, 'reason': reason, 'model': model}


def try_jev(rubric, final, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None:
        return None
    state = {'rule': rubric, 'reply': final if isinstance(final, str) else ''}
    try:
        return from_response(ask.system_one(state, decide.questions('judge')))
    except client.TypeSafeError:
        return None


def parse_model_text(text):
    import json
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if (not isinstance(parsed, dict) or set(parsed) != {'verdict', 'reason'}
            or parsed['verdict'] not in ('pass', 'fail')
            or not isinstance(parsed['reason'], str) or not parsed['reason'].strip()):
        return None
    return {'verdict': parsed['verdict'], 'reason': parsed['reason']}
