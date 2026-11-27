#!/usr/bin/env python3
import json, os, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS = os.path.dirname(HERE)
with open(os.path.join(HERE, 'row.json')) as f:
    ROW = json.load(f)
MODE = next(iter(ROW['modes']))
CANT_SET_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                   "to run it at the host's default")


def machine():
    return th.ThrowawayMachine(ROWS, 'vibe', 'vibe', os.path.join(HERE, 'fake'), MODE)


def not_installed():
    with machine() as env:
        os.remove(os.path.join(env.folder, 'bin', 'vibe'))
        path = [d for d in env.env['PATH'].split(os.pathsep) if not os.path.exists(os.path.join(d, 'vibe'))]
        env.env['PATH'] = os.pathsep.join(path)
        return env.start_refused_starting_nothing(
            lambda out: 'not installed' in out['error'] and out['next'].startswith('install vibe '))


def a_history_quoting_the_diagnostics_still_starts():
    with machine() as env:
        code, out = env.start(FAKE_VIBE_QUOTES_DIAGNOSTICS='1', FAKE_CLI_RECORD_ONLY='1')
        return code == 0 and out.get('run', '').startswith('run-')


OTHER_PROVIDERS = ('llama-cpp', 'azure openai.eu-2')


def diagnostics(provider):
    return ('Error: Missing MISTRAL_API_KEY environment variable for %s provider' % provider,
            "Error: Can't read MISTRAL_API_KEY from the system keyring for %s provider (no keyring). "
            'Unlock the system keyring or approve its prompt, or set the MISTRAL_API_KEY environment variable' % provider)


def read_as_signed_out_unless_quoted(lines):
    quoted = json.dumps([{'content': line} for line in lines], indent=2)
    return all(th.local.signed_out_by_row(ROW, line) for line in lines) and not th.local.signed_out_by_row(ROW, quoted)


def both_diagnostic_lines_read_as_signed_out():
    return read_as_signed_out_unless_quoted(diagnostics('mistral'))


def start_is_not_signed_in(**env):
    with machine() as machine_env:
        code, out = machine_env.start(FAKE_CLI_SIGNED_OUT='1', **env)
        return (code == 1 and 'the harness is not signed in' in out.get('error', '') and
                ROW['login_command'] in out.get('next', ''))


def a_locked_keyring_reads_as_not_signed_in():
    return start_is_not_signed_in(FAKE_VIBE_KEYRING='1')


def another_providers_name_reads_as_not_signed_in():
    return all(read_as_signed_out_unless_quoted(diagnostics(provider)) and
               start_is_not_signed_in(FAKE_VIBE_PROVIDER=provider) and
               start_is_not_signed_in(FAKE_VIBE_PROVIDER=provider, FAKE_VIBE_KEYRING='1')
               for provider in OTHER_PROVIDERS)


def every_effort_refused_starting_nothing():
    return all(machine_refuses(level) for level in ('low', 'medium', 'high', 'xhigh', 'max', 'off'))


def machine_refuses(level):
    with machine() as env:
        return env.start_refused_starting_nothing(lambda out: out['next'] == CANT_SET_EFFORT, effort=level,
                                                  FAKE_CLI_RECORD_ONLY='1')


def pattern_reads_the_entry_id_not_a_nested_one():
    entry = {'id': 'entry-1', 'content': 'say "session_id": "quoted-id" back', 'effect': {'session_id': 'child-id'},
             'session_id': 'root-id', 'type': 'message'}
    with tempfile.TemporaryDirectory() as state:
        th.local.STATE = state
        with open(os.path.join(state, 'run-x.log'), 'w') as f:
            f.write('Reading API keys from the system keyring\n' + json.dumps([entry], indent=2) + '\n')
        first_turn = {'output_from': 0}
        return th.local.reported_session('run-x', ROW['session'], first_turn) == 'root-id'


def main():
    ok = True
    for check in (not_installed, a_history_quoting_the_diagnostics_still_starts, both_diagnostic_lines_read_as_signed_out,
                  a_locked_keyring_reads_as_not_signed_in, another_providers_name_reads_as_not_signed_in,
                  every_effort_refused_starting_nothing,
                  pattern_reads_the_entry_id_not_a_nested_one):
        passed = check()
        print('%s %s' % ('pass' if passed else 'fail', check.__name__.replace('_', ' ')))
        ok = ok and passed
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
