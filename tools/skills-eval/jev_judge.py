import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client
import decide
import records

MARGIN_BYTES = 4096


def mode():
    if client.from_env() is None:
        return None
    return frozen_or_current(None)


def frozen_or_current(frozen):
    if frozen:
        return frozen
    root = decide.load()
    return {'model': client.MODEL, 'noul': root['noul'], 'judge': root['sites']['judge'],
            'price_usd_per_mtok': root['price_usd_per_mtok']}


def asker(settings):
    if not settings.get('judge_jev'):
        return None
    return client.from_env()


def from_response(response, frozen=None):
    frozen = frozen_or_current(frozen)
    site = frozen['judge']
    try:
        value = decide.signal(response, site, {'noul': frozen['noul']})
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
        model = frozen['model']
    return {'verdict': verdict, 'reason': reason, 'model': model}


def reserve(state, questions, frozen=None):
    frozen = frozen_or_current(frozen)
    body = {'model': frozen['model'], 'state': client.bounded(state), 'questions': questions}
    size = len(json.dumps(body, ensure_ascii=False).encode('utf-8'))
    return (size + MARGIN_BYTES) * max(frozen['price_usd_per_mtok'].values()) / 1e6


def billed(response, frozen=None):
    usage = response.get('usage') if isinstance(response, dict) else None
    if not isinstance(usage, dict) or any(k not in usage for k in ('input_tokens', 'output_tokens')):
        return None
    counts = {k: usage[k] for k in ('input_tokens', 'output_tokens')}
    if any(type(v) is not int or v < 0 for v in counts.values()):
        return None
    price = frozen_or_current(frozen)['price_usd_per_mtok']
    return sum(counts[k] * price[k] for k in counts) / 1e6, counts


def try_jev(rubric, final, ask, frozen=None, fits=lambda bound: True, hold=lambda bound: None,
            settle=lambda cost, uncertain, usage: None):
    if ask is None:
        return None
    frozen = frozen_or_current(frozen)
    state = {'rule': rubric, 'reply': final if isinstance(final, str) else ''}
    questions = frozen['judge']['questions']
    bound = reserve(state, questions, frozen)
    if not fits(bound):
        return None
    hold(bound)
    try:
        response = ask.system_one(state, questions, frozen['model'])
    except client.TypeSafeError:
        settle(0.0, bound, None)
        return None
    paid = billed(response, frozen)
    if paid is None:
        settle(0.0, bound, None)
        return None
    settle(paid[0], 0.0, paid[1])
    return from_response(response, frozen)


def parse_model_text(text):
    try:
        parsed = records.strict_json(text)
    except (TypeError, ValueError):
        return None
    if (not isinstance(parsed, dict) or set(parsed) != {'verdict', 'reason'}
            or parsed['verdict'] not in ('pass', 'fail')
            or not isinstance(parsed['reason'], str) or not parsed['reason'].strip()):
        return None
    return {'verdict': parsed['verdict'], 'reason': parsed['reason']}
