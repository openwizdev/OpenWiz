"""Say whether a finished turn stopped on a usage limit written as text.

Structured usage-limit events stay authoritative. This only covers a log
that ended with no tool call. A false yes stops a run that had simply
finished, so the gate is 0.9. No key, or any error, returns false.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client

YES = 0.9
QUESTIONS = {
    'limit': {
        'type': 'noul',
        'instructions': 'The log says the model run stopped because a usage limit or rate limit was reached.',
        'criteria': {
            'true': 'A usage limit, plan limit, or rate limit stopped the run.',
            'false': 'The run finished, failed for another reason, or is not signed in.',
        },
    },
}


def usage_limit(text, ask=None):
    ask = client.from_env() if ask is None else ask
    if ask is None or not isinstance(text, str) or not text.strip():
        return False
    try:
        return client.noul(ask.system_one(text, QUESTIONS), 'limit') >= YES
    except client.TypeSafeError:
        return False
