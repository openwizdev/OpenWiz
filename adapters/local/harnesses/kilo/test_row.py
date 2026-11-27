#!/usr/bin/env python3
import os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as h

ROWS = os.path.dirname(HERE)
FAKE = os.path.join(HERE, 'fake')


def without_any_agent_cli(env):
    # SAFETY: only the machine's own bin folder and PATH folders that hold no agent CLI, real or stub.
    keep = [d for d in os.environ.get('PATH', '').split(os.pathsep)
            if d and not any(os.path.exists(os.path.join(d, c)) for c in h.STUBS)]
    return os.pathsep.join([os.path.join(env.folder, 'bin')] + keep)


def not_installed():
    with h.ThrowawayMachine(ROWS, 'kilo', mode='default') as env:
        says = lambda out: out['error'] == 'harness kilo is not installed here' and \
            out['next'] == 'install kilo on this machine and sign in to it yourself, then start again'
        return env.start_refused_starting_nothing(says, PATH=without_any_agent_cli(env))


# External: Kilo's own signed-out lines: a 401 through a gateway, no saved login, and the gateway code read from
# a JSON error line's responseBody,
# https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/provider/error.ts
# https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/cloud/auth.ts
# https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/kilo-errors.ts
GATEWAY = '{"type":"error","timestamp":0,"sessionID":"fake-signed-out","error":{"name":"APIError","data":' \
          '{"message":"Payment Required","statusCode":402,"responseBody":"{\\"error\\":{\\"code\\":\\"%s\\"}}"}}}'
SIGNED_OUT = ['Error: Unauthorized: request was blocked by a gateway or proxy. Your authentication token may be '
              'missing or expired \u2014 try running `kilo auth login <your provider URL>` to re-authenticate.',
              'Error: Kilo credentials are required; run `kilo auth login`',
              GATEWAY % 'PAID_MODEL_AUTH_REQUIRED']
# External: the free-model limit says "Or come back later", so it isn't a sign-in,
# https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/kilo-errors.ts
USAGE_LIMIT = GATEWAY % 'PROMOTION_MODEL_LIMIT_REACHED'


def not_signed_in():
    with h.ThrowawayMachine(ROWS, 'kilo', 'kilo', FAKE, 'default', ['KILO_NO_DAEMON']) as env:
        for line in SIGNED_OUT:
            code, out = env.start(FAKE_CLI_SIGNED_OUT='1', FAKE_KILO_SIGNED_OUT_LINE=line)
            if code == 0:
                env.driver('stop', out)
            if code != 1 or h.kit.invalid(out, h.ERROR) is not None or env.records() or \
                    'the harness is not signed in' not in out['error'] or 'kilo auth login' not in out['next']:
                return False
        code, out = env.start(FAKE_CLI_SIGNED_OUT='1', FAKE_KILO_SIGNED_OUT_LINE=USAGE_LIMIT)
        if code == 0:
            env.driver('stop', out)
        return code == 1 and 'the harness failed' in out.get('error', '') and \
            'kilo auth login' not in out.get('next', '')


failed = [name for name, check in (('not installed: a D3 error whose next says to install and sign in', not_installed),
                                    ('not signed in: each of Kilo\'s signed-out lines is a D3 error saying so, whose '
                                     'next names kilo auth login; its free-model limit is not',
                                     not_signed_in)) if not check()]
for name in failed:
    print('fail kilo test_row.py: ' + name)
sys.exit(1 if failed else 0)
