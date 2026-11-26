#!/usr/bin/env python3
import json, os, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
MODE = 'default-profile'
NEXT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
        "at the host's default")
HOOK_NOTICE = json.dumps({'type': 'hook_notice', 'kind': 'info', 'conversation_id': None,
                          'local_conversation_id': 'local-0000', 'action_id': None, 'text': 'a hook ran'},
                         separators=(',', ':'))
PROMPT = 'Use the build-ticket skill on example/site#7 with the build-ticket skill'
failed = []


def check(what, ok):
    print('%s %s: %s' % ('pass' if ok else 'fail', NAME, what))
    if not ok:
        failed.append(what)


def without_oz(path):
    return os.pathsep.join(d for d in path.split(os.pathsep) if not os.path.exists(os.path.join(d, 'oz')))


def stop_all(env):
    for run in env.runs():
        env.driver('stop', {'run': run[:-len('.json')]})


with th.ThrowawayMachine(ROWS, NAME, mode=MODE) as env:
    gh_only = os.pathsep.join([os.path.join(env.folder, 'bin'), without_oz(env.env['PATH'])])
    before = env.runs()
    code, out = env.start(PATH=gh_only)
    check('not installed is a D3 error whose next says to install oz, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness oz is not installed here'
          and 'install oz' in out.get('next', '') and env.runs() == before)

for how, line in (('client', 'You are not logged in'), ('server', 'Failed to authenticate with server'),
                  ('invalid', 'Your credentials are invalid'), ('june', 'You are not logged in -'),
                  ('june-invalid', 'Your credentials are invalid')):
    with th.ThrowawayMachine(ROWS, NAME, 'oz', FAKE, MODE) as env:
        code, out = env.start(FAKE_CLI_SIGNED_OUT='1', OZ_FAKE_SIGNED_OUT=how)
        check('not signed in (%s: "%s ...") is a D3 error that says so, and its next names oz login' % (how, line),
              code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
              and 'oz login' in out.get('next', ''))
        stop_all(env)

with th.ThrowawayMachine(ROWS, NAME, 'oz', FAKE, MODE) as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_PRELUDE=HOOK_NOTICE)
    woke = env.driver('wake', out) if code == 0 else (1, {})
    env.driver('stop', out)
    turns = env.records()
    first = turns[0]['argv'] if turns else []
    check('start runs `oz agent run --output-format json --model <m> --prompt <prompt>`',
          code == 0 and first[:-1] == ['agent', 'run', '--output-format', 'json', '--model', 'synthetic-1', '--prompt'])
    second = turns[1]['argv'] if len(turns) > 1 else []
    check('wake runs `oz agent run --conversation <id> --model <m> --prompt <prompt>` with the start\'s conversation id',
          woke[0] == 0 and len(turns) == 2 and
          second[:-1] == ['agent', 'run', '--conversation', turns[0]['session'], '--model', 'synthetic-1', '--prompt'])
    check('the conversation id comes from the conversation_started line, past a hook_notice whose conversation_id '
          'is null', len(turns) == 2 and turns[1]['session'] == turns[0]['session'] != 'local-0000')

refused = {
    'an --api-key flag': ['agent', 'run', '--api-key', 'synthetic', '--prompt', PROMPT],
    'an --effort flag': ['agent', 'run', '--effort', 'high', '--prompt', PROMPT],
    'a --reasoning flag': ['agent', 'run', '--reasoning', 'high', '--prompt', PROMPT],
    'no --prompt': ['agent', 'run', '--output-format', 'json'],
    'a bare prompt': ['agent', 'run', PROMPT],
    'an option where --model needs its value': ['agent', 'run', '--model', '--bogus', '--prompt', PROMPT],
    'an option where --prompt needs its value': ['agent', 'run', '--prompt', '--model'],
    'a repeated --prompt': ['agent', 'run', '--prompt', PROMPT, '--prompt', PROMPT],
    'an --output-format oz does not have': ['agent', 'run', '--output-format', 'stream-json', '--prompt', PROMPT],
    'run-cloud': ['agent', 'run-cloud', '--prompt', PROMPT],
    'a top-level run': ['run', '--prompt', PROMPT],
}
for what, argv in refused.items():
    try:
        code = subprocess.run([FAKE] + argv, env=dict(os.environ, FAKE_CLI_LIB=os.path.join(HERE, '..', '..', 'fixtures')),
                              capture_output=True, text=True, timeout=30).returncode
    except OSError:
        code = None
    check('the fake exits 2 on %s' % what, code == 2)

with th.ThrowawayMachine(ROWS, NAME, 'oz', FAKE, MODE) as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        check('effort %s is refused with the fixed next, starting nothing' % level,
              env.start_refused_starting_nothing(lambda out: out['next'] == NEXT, effort=level,
                                                 FAKE_CLI_RECORD_ONLY='1'))

sys.exit(1 if failed else 0)
