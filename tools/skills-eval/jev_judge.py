import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide

MARGIN_BYTES = 4096


def mode():
    if client.from_env() is None:
        return None
    root = decide.load()
    return {'model': client.MODEL, 'noul': root['noul'], 'judge': root['sites']['judge'],
            'price_usd_per_mtok': root['price_usd_per_mtok']}


def asker(settings):
    if not settings.get('judge_jev'):
        return None
    return client.from_env()


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


def reserve(state, questions):
    price = decide.load()['price_usd_per_mtok']
    body = {'model': client.MODEL, 'state': client.bounded(state), 'questions': questions}
    size = len(json.dumps(body, ensure_ascii=False).encode('utf-8'))
    return (size + MARGIN_BYTES) * max(price.values()) / 1e6


def billed(response):
    usage = response.get('usage') if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    counts = {k: usage.get(k, 0) for k in ('input_tokens', 'output_tokens')}
    if any(type(v) is not int or v < 0 for v in counts.values()) or 'input_tokens' not in usage:
        return None
    price = decide.load()['price_usd_per_mtok']
    return sum(counts[k] * price[k] for k in counts) / 1e6, counts


def try_jev(rubric, final, ask, fits=lambda bound: True, hold=lambda bound: None,
            settle=lambda cost, uncertain, usage: None):
    if ask is None:
        return None
    state = {'rule': rubric, 'reply': final if isinstance(final, str) else ''}
    questions = decide.questions('judge')
    bound = reserve(state, questions)
    if not fits(bound):
        return None
    hold(bound)
    try:
        response = ask.system_one(state, questions)
    except client.TypeSafeError:
        settle(0.0, bound, None)
        return None
    paid = billed(response)
    if paid is None:
        settle(0.0, bound, None)
    else:
        settle(paid[0], 0.0, paid[1])
    return from_response(response)


def parse_model_text(text):
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if (not isinstance(parsed, dict) or set(parsed) != {'verdict', 'reason'}
            or parsed['verdict'] not in ('pass', 'fail')
            or not isinstance(parsed['reason'], str) or not parsed['reason'].strip()):
        return None
    return {'verdict': parsed['verdict'], 'reason': parsed['reason']}
