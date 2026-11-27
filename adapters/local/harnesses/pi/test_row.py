#!/usr/bin/env python3
import importlib.machinery, importlib.util, json, os, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.join(HERE, '..', '..', 'fixtures')
DRIVER = os.path.join(HERE, '..', '..', 'driver')
ID = '0b6f3c2e-5a7d-4e1f-9c3b-2d8a6e4f1a07'
START = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE = 'You were woken: take up example/site#7 again, with the build-ticket skill. Edit your own status note there; ' \
       'post no second one.'
REFUSED = {
    'a --session-id that starts with a dot': ['-p', '--mode', 'json', '--session-id', '.' + ID, '--model', 'm', '--', START],
    'a --session-id with a slash': ['-p', '--mode', 'json', '--session-id', 'a/b', '--model', 'm', '--', START],
    '--session-id with --continue': ['-c', '--session-id', ID, '-p', '--', WAKE],
    'a wake that passes --model again, which re-resolves the saved model': ['--session-id', ID, '-p', '--model', 'm',
                                                                           '--', WAKE],
    'a start with an empty --model, which pi skips': ['-p', '--mode', 'json', '--session-id', ID, '--model', '', '--',
                                                       START],
    'a start with a blank --model': ['-p', '--mode', 'json', '--session-id', ID, '--model', ' ', '--', START],
    'an unknown --mode': ['-p', '--mode', 'yaml', '--session-id', ID, '--model', 'm', '--', START],
    'a prompt that starts with @, which pi reads as a file': ['-p', '--mode', 'json', '--session-id', ID, '--model', 'm',
                                                             '--', '@' + START],
    'an unknown short option': ['-p', '-x', '--mode', 'json', '--session-id', ID, '--model', 'm', '--', START],
    'a start with no prompt': ['-p', '--mode', 'json', '--session-id', ID, '--model', 'm', '--'],
    'a wake with no session id': ['-p', '--', WAKE],
    'a wake prompt on a start line': ['-p', '--mode', 'json', '--session-id', ID, '--model', 'm', '--', WAKE],
    'a start prompt on a wake line': ['--session-id', ID, '-p', '--', START],
}
HELP = 'Use /login to log into a provider via OAuth or API key. See:\n  /pi/docs/providers.md\n  /pi/docs/models.md'
NO_KEY = 'No API key found for anthropic.'
EXPIRED = 'Authentication failed for "anthropic". Credentials may have expired or network is unavailable. ' \
          "Run '/login anthropic' to re-authenticate."
AMBIGUOUS = 'Model "sonnet" is ambiguous across providers: amazon-bedrock/sonnet, anthropic/sonnet. ' \
            'No matching provider is authenticated. Use --provider or provider/model.'
SIGNED_OUT = {
    'the missing-key error as print mode writes it': NO_KEY + '\n\n' + HELP + '\n',
    'the missing-key error for an unknown provider': 'No API key found for the selected model.\n\n' + HELP + '\n',
    'the expired-login error as print mode writes it': EXPIRED + '\n',
    'the ambiguous-model diagnostic in its Error: line': 'Error: ' + AMBIGUOUS + '\n',
    'the ambiguous-model diagnostic in red': '\x1b[31mError: ' + AMBIGUOUS + '\x1b[39m\n',
}


def event(kind, text):
    if kind == 'message_end':
        return json.dumps({'type': kind, 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}})
    return json.dumps({'type': kind, 'toolName': 'bash', 'result': {'content': [{'type': 'text', 'text': text}]}})


ACCEPTED = {
    'an assistant message that quotes the missing-key error': event('message_end', NO_KEY + '\n\n' + HELP),
    'an assistant message that says the missing-key error exists': event(
        'message_end', 'Fixed: pi printed "%s" when the variable was unset.' % NO_KEY),
    'tool output that quotes the expired-login error': event('tool_execution_end', EXPIRED),
    'tool output that quotes the ambiguous-model diagnostic': event('tool_execution_end', 'Error: ' + AMBIGUOUS),
}
failures = []


def check(what, ok):
    print('%s pi row: %s' % ('pass' if ok else 'fail', what))
    if not ok:
        failures.append(what)


env = dict(os.environ, FAKE_CLI_LIB=LIB)
for what, argv in sorted(REFUSED.items()):
    p = subprocess.run([sys.executable, FAKE] + argv, env=env, capture_output=True, text=True, timeout=30)
    check('the fake exits 2 on ' + what, p.returncode == 2)
with open(os.path.join(HERE, 'row.json')) as f:
    row = json.load(f)
local = importlib.util.module_from_spec(importlib.util.spec_from_loader(
    'openwiz_local_driver', importlib.machinery.SourceFileLoader('openwiz_local_driver', DRIVER)))
local.__spec__.loader.exec_module(local)


def first_turn_signed_out(log):
    return bool(local.SIGNED_OUT.search(log) or local.signed_out_by_row(row, log))


for what, log in sorted(SIGNED_OUT.items()):
    check("the driver's first-turn check reads " + what + ' as signed out', first_turn_signed_out(log))
for what, line in sorted(ACCEPTED.items()):
    check("the driver's first-turn check accepts " + what, not first_turn_signed_out(line + '\n'))
sys.exit(1 if failures else 0)
