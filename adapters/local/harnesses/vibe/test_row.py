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


def both_diagnostic_lines_read_as_signed_out():
    lines = ('Error: Missing MISTRAL_API_KEY environment variable for mistral provider',
             "Error: Can't read MISTRAL_API_KEY from the system keyring for mistral provider (no keyring)")
    quoted = json.dumps([{'content': line} for line in lines], indent=2)
    return all(th.local.signed_out_by_row(ROW, line) for line in lines) and not th.local.signed_out_by_row(ROW, quoted)


def off_refused():
    with machine() as env:
        return env.start_refused_starting_nothing(lambda out: out['next'] == th.CANT_SET_EFFORT, effort='off',
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
                  off_refused, pattern_reads_the_entry_id_not_a_nested_one):
        passed = check()
        print('%s %s' % ('pass' if passed else 'fail', check.__name__.replace('_', ' ')))
        ok = ok and passed
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
