"""Judge one skills-eval reply with Jev, or leave it for the existing parser.

A Choice asks whether the reply meets the rule. The docs' starting threshold
is 0.7. Below that, or on any error, the caller keeps the prompt-and-parse
judge. Jev returns no sentence, so the reason is the criterion the choice matched.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'typesafe'))
import client

YES = 0.7
QUESTIONS = {
    'verdict': {
        'type': 'choice',
        'instructions': 'Does the reply meet the rule?',
        'criteria': {
            'pass': 'The reply meets the rule.',
            'fail': 'The reply does not meet the rule.',
        },
    },
}


def from_response(response):
    name, probability, confidence = client.choice(response, 'verdict')
    if name not in ('pass', 'fail') or probability < YES or confidence < YES:
        return None
    reason = QUESTIONS['verdict']['criteria'][name]
    model = response.get('model') if isinstance(response, dict) else None
    if not isinstance(model, str) or not model:
        model = client.MODEL
    return {'verdict': name, 'reason': reason, 'model': model}


def try_jev(rubric, final, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None:
        return None
    state = {'rule': rubric, 'reply': final if isinstance(final, str) else ''}
    try:
        return from_response(ask.system_one(state, QUESTIONS))
    except client.TypeSafeError:
        return None


def parse_model_text(text):
    """The existing judge: a JSON object with verdict and a non-empty reason, or None."""
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
