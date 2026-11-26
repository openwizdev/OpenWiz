"""The previous plan-limit lines, and the same 0.9 noul gate the Rust caller uses.

Keep `exact` equal to `exact_plan_limit` in `crates/cli/src/typesafe.rs`.
"""

ACT = 0.9
RESET = "You've hit your limit · resets "
QUESTION = {
    'limit': {
        'type': 'noul',
        'instructions': 'The session output says this Claude run stopped because its plan usage limit was reached.',
        'criteria': {
            'true': 'The text says a plan, quota, or rate limit stopped the run and it should wait.',
            'false': 'The text is ordinary work, a normal failure, or a sign-in problem.',
        },
    },
}


def exact(text):
    for line in text.splitlines():
        line = line.strip()
        if line in ('Claude usage limit reached', "You've hit your limit"):
            return True
        if line.startswith(RESET) and line[len(RESET):]:
            return True
    return False


def shaped(text, recorded):
    return exact(text) or (recorded is not None and recorded >= ACT)
