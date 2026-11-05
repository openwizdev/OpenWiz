"""#2216 (RL3-R): the saved expected plan constrains the live-smoke fleet tick.

Every program, document and identifier here is synthetic. The fake `openwiz`
keeps the #1892 contract's two sides apart: a pinned plan is compared with the
tick's current plan before any effect, while an unpinned tick recovers,
replans and executes whatever it finds. Each case records every call the
runner made and every effect the fake carried out.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

# Load by path: this folder's http.py must never shadow the standard library
# when tools/release/test.py runs these proofs in its process.
_SPEC = importlib.util.spec_from_file_location(
    'live_smoke_restriction', Path(__file__).resolve().with_name('restriction.py'))
restriction = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(restriction)

FAKE = '''#!{python} -I
import json, pathlib, sys
root = pathlib.Path(__file__).parent
world = json.loads((root / 'world.json').read_text())
args = sys.argv[1:]
entry = {{'argv': args}}
if '--expect-plan' in args:
    # What the product read from the pinned path, at execution time.
    entry['read'] = json.loads(pathlib.Path(args[args.index('--expect-plan') + 1]).read_text())
with (root / 'calls').open('a') as log:
    log.write(json.dumps(entry) + '\\n')
reply = world.get('replies', {{}}).get(' '.join(args[:3]))
if reply is not None:
    sys.stdout.buffer.write(bytes.fromhex(reply['hex']) if 'hex' in reply else reply['out'].encode())
    sys.exit(reply['exit'])
if args == ['help', '--agent']:
    print(json.dumps(world['catalogue']))
    sys.exit(0)
if args == ['fleet', 'tick', '--dry-run', '--json']:
    print(json.dumps(world['preview']))
    sys.exit(0)
current, recovery = world['current'], world.get('recovery', [])
pinned = args[:3] == ['fleet', 'tick', '--expect-plan'] and world.get('honours_pin', True)
if pinned:
    same = all(json.dumps(entry['read'][k], sort_keys=True) == json.dumps(current[k], sort_keys=True)
               for k in ('actions', 'rules', 'default_branch'))
    if recovery or not same:
        print(json.dumps({{'schema': 'openwiz.cli-error.v1', 'command': 'fleet.tick', 'exit_code': 1,
                          'error': {{'kind': 'read_failed', 'message': 'synthetic refusal'}}}}))
        sys.exit(1)
executed = recovery + current['actions']
with (root / 'effects').open('a') as log:
    for action in executed:
        log.write(json.dumps([action['kind'], action['spec'], action['ticket']]) + '\\n')
done = [dict(a, outcome={{'state': 'done'}}) for a in executed]
print(json.dumps(dict(current, mode='run', planned_at=1793400000500, actions=done)))
'''


def action(kind, rule, spec, ticket, **facts):
    return {'kind': kind, 'rule': rule, 'spec': spec, 'ticket': ticket,
            'facts': facts, 'outcome': {'state': 'planned'}}


ARCHIVE = action('archive', 'finished', 9001, 9002, thread='thr_synthetic_builder_a')
START = action('start_builder', 'frontier', 9001, 9003,
               settings={'provider': 'synthetic', 'model': 'synthetic-model', 'effort': 'high'})
EXTRA = action('start_builder', 'frontier', 9001, 9004,
               settings={'provider': 'synthetic', 'model': 'synthetic-model', 'effort': 'high'})
RECOVERED = dict(action('start_builder', 'frontier', 9001, 9005,
                        settings={'provider': 'synthetic', 'model': 'synthetic-model', 'effort': 'high'}))


def preview(actions):
    return {'schema': 'openwiz.fleet-tick.v1', 'mode': 'dry_run', 'planned_at': 1793400000000,
            'default_branch': 'main', 'rules': {'merge': 'adr_0008'}, 'actions': actions}


def catalogue(flags):
    return {'schema': 'openwiz.cli.v1', 'kind': 'catalogue', 'flags': [], 'notes': [],
            'commands': [{'name': 'fleet.tick', 'argv': ['fleet', 'tick'], 'flags': flags},
                         {'name': 'fleet.tick.preview', 'argv': ['fleet', 'tick', '--dry-run'],
                          'flags': ['--dry-run', '--json']}]}


def changed(actions):
    actions = json.loads(json.dumps(actions))
    actions[1]['facts']['settings']['model'] = 'synthetic-other'
    return actions


class Restriction(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.openwiz = self.root / 'openwiz'
        self.openwiz.write_text(FAKE.format(python=sys.executable))
        self.openwiz.chmod(0o700)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.world = {'catalogue': catalogue(['--json', '--expect-plan']),
                      'preview': preview([ARCHIVE, START]), 'current': preview([ARCHIVE, START])}

    def launch(self, argv):
        (self.root / 'world.json').write_text(json.dumps(self.world))
        # Read the Python fixture instead of exec'ing its newly written inode:
        # overlapping subprocesses can briefly retain a writable descriptor.
        done = subprocess.run([sys.executable, '-I', *argv], cwd=self.root, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=20)
        return done.returncode, done.stdout

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def effects(self):
        path = self.root / 'effects'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def tick(self, audit=None):
        kwargs = {} if audit is None else {'audit': audit}
        pinned = restriction.establish(str(self.openwiz), self.state, self.launch, **kwargs)
        return restriction.execute(pinned, self.launch)

    def refused(self, reason, audit=None):
        with self.assertRaises(restriction.Refused) as caught:
            self.tick(audit)
        self.assertEqual(str(caught.exception), reason)
        self.assertIn(reason, restriction.REASONS)

    def assert_no_execution(self):
        self.assertEqual([c['argv'] for c in self.calls() if c['argv'][:2] == ['fleet', 'tick']
                          and '--dry-run' not in c['argv']], [], 'no execution was launched')
        self.assertEqual(self.effects(), [], 'no fleet effect')
        self.assertEqual(sorted(os.listdir(self.state)), [], 'no plan left behind')

    def assert_one_pinned_execution(self):
        """The only execution is the pinned form, reading exactly the reviewed preview."""
        executions = [c for c in self.calls() if c['argv'][:2] == ['fleet', 'tick']
                      and '--dry-run' not in c['argv']]
        self.assertEqual(len(executions), 1, 'one execution, never a retry or an unpinned tick')
        argv = executions[0]['argv']
        self.assertEqual(argv[:3], ['fleet', 'tick', '--expect-plan'])
        self.assertEqual(argv[4:], ['--json'])
        self.assertEqual(Path(argv[3]).parent, self.state, 'the plan is saved in private state')
        self.assertEqual(executions[0]['read'], self.world['preview'])
        self.assertEqual(sorted(os.listdir(self.state)), [], 'the saved plan is removed afterwards')

    # P3 (restriction part): the exact plan progresses.
    def test_exact_plan_progresses_in_order(self):
        report = self.tick()
        self.assertEqual(self.calls()[0]['argv'], ['help', '--agent'])
        self.assertEqual(self.calls()[1]['argv'], ['fleet', 'tick', '--dry-run', '--json'])
        self.assert_one_pinned_execution()
        self.assertEqual(self.effects(), [['archive', 9001, 9002], ['start_builder', 9001, 9003]])
        self.assertEqual(report['mode'], 'run')
        self.assertEqual([a['outcome'] for a in report['actions']], [{'state': 'done'}] * 2)

    def test_empty_plan_progresses_with_no_effect(self):
        self.world['preview'] = self.world['current'] = preview([])
        self.assertEqual(self.tick()['actions'], [])
        self.assert_one_pinned_execution()
        self.assertEqual(self.effects(), [])

    def test_spec_action_without_a_ticket_progresses(self):
        self.world['preview'] = self.world['current'] = preview([
            action('close', 'all_closed', 9001, None, tickets=[9002])])
        self.assertEqual(self.tick()['actions'][0]['ticket'], None)
        self.assertEqual(self.effects(), [['close', 9001, None]])
        self.assert_one_pinned_execution()

    # Additional, reordered, changed and recovery actions refuse before effects.
    def test_drift_after_the_preview_refuses_before_effects(self):
        for name, current, recovery in (
            ('additional', [ARCHIVE, START, EXTRA], []),
            ('missing', [START], []),
            ('reordered', [START, ARCHIVE], []),
            ('changed argument', changed([ARCHIVE, START]), []),
            ('recovery', [ARCHIVE, START], [dict(RECOVERED, outcome={'state': 'done'})]),
        ):
            with self.subTest(name):
                self.setUp()
                self.world['current'] = preview(current)
                self.world['recovery'] = recovery
                self.refused('tick_refused')
                self.assert_one_pinned_execution()
                self.assertEqual(self.effects(), [])

    # A tick that executes anything but the saved plan never passes.
    def test_execution_that_differs_from_the_saved_plan_never_passes(self):
        for name, current, recovery in (
            ('additional', [ARCHIVE, START, EXTRA], []),
            ('reordered', [START, ARCHIVE], []),
            ('changed argument', changed([ARCHIVE, START]), []),
            ('recovery', [ARCHIVE, START], [dict(RECOVERED, outcome={'state': 'done'})]),
        ):
            with self.subTest(name):
                self.setUp()
                self.world.update(current=preview(current), recovery=recovery, honours_pin=False)
                self.refused('plan_mismatch')
                self.assert_one_pinned_execution()

    def test_report_must_match_the_plan_exactly(self):
        run = dict(preview([dict(ARCHIVE, outcome={'state': 'done'}),
                            dict(START, outcome={'state': 'done'})]), mode='run')
        for name, report in (
            ('rules', dict(run, rules={'merge': 'none'})),
            ('default branch', dict(run, default_branch='trunk')),
            ('still planned', dict(run, actions=[ARCHIVE, START])),
            ('a dry run', dict(run, mode='dry_run')),
            ('bool for a number', dict(run, actions=[dict(ARCHIVE, spec=True), run['actions'][1]])),
            ('extra field', dict(run, extra=1)),
            ('non-object outcome', dict(run, actions=[dict(ARCHIVE, outcome=None), run['actions'][1]])),
        ):
            with self.subTest(name):
                self.setUp()
                self.world['replies'] = {'fleet tick --expect-plan': {'exit': 0, 'out': json.dumps(report) + '\n'}}
                self.refused('plan_mismatch')

    def test_unknown_execution_result_is_uncertain(self):
        refusal = {'schema': 'openwiz.cli-error.v1', 'command': 'fleet.tick', 'exit_code': 1,
                   'error': {'kind': 'read_failed', 'message': 'synthetic'}}
        for name, code, out in (
            ('usage error', 2, ''),
            ('exit 1 without a report', 1, ''),
            ('exit 1 with another kind', 1, json.dumps(dict(refusal, error={'kind': 'usage', 'message': 'x'}))),
            ('exit 1 for another command', 1, json.dumps(dict(refusal, command='fleet.tick.preview'))),
            ('exit 1 with extra field', 1, json.dumps(dict(refusal, extra=1))),
            ('exit 1 with boolean exit', 1, json.dumps(dict(refusal, exit_code=True))),
            ('exit 1 with another schema', 1, json.dumps(dict(refusal, schema='other'))),
            ('exit 1 with a message number', 1, json.dumps(dict(refusal, error={'kind': 'read_failed', 'message': 1}))),
            ('exit 1 with missing error field', 1, json.dumps(dict(refusal, error={'kind': 'read_failed'}))),
            ('exit 1 with error fields array', 1, json.dumps(dict(refusal, error=['kind', 'message']))),
            ('exit 1 with envelope fields array', 1, json.dumps(list(refusal))),
            ('exit 0 with invalid JSON', 0, '{'),
            ('exit 0 with a duplicate key', 0, '{"schema":"openwiz.fleet-tick.v1","schema":"x"}'),
            ('exit 0 with two documents', 0, '{}\n{}'),
            ('another status', 7, ''),
        ):
            with self.subTest(name):
                self.setUp()
                self.world['replies'] = {'fleet tick --expect-plan': {'exit': code, 'out': out}}
                self.refused('uncertain_write')
                self.assert_one_pinned_execution()

    # P3: a matching action list cannot turn an unknown write outcome into a
    # usable receipt. Previously only the exact planned outcome was rejected.
    def test_run_outcomes_are_classified_before_returning_a_report(self):
        for result in ({}, {'state': 'unknown'}, {'state': {'done': None}},
                       {'state': 'done', 'reason': 'extra'}, {'state': 'refused'},
                       {'state': 'failed', 'reason': ''},
                       {'state': 'failed', 'reason': 1},
                       {'state': 'uncertain', 'reason': False},
                       {'state': 'planned', 'extra': 1}):
            with self.subTest(result):
                self.setUp()
                report = dict(preview([dict(ARCHIVE, outcome=result),
                                       dict(START, outcome={'state': 'done'})]), mode='run')
                self.world['replies'] = {'fleet tick --expect-plan':
                                        {'exit': 0, 'out': json.dumps(report)}}
                self.refused('uncertain_write')
                self.assert_one_pinned_execution()
        for result in ({'state': 'done'}, {'state': 'refused', 'reason': 'synthetic'},
                       {'state': 'failed', 'reason': 'synthetic'},
                       {'state': 'uncertain', 'reason': 'synthetic'}):
            with self.subTest(result):
                self.setUp()
                report = dict(preview([dict(ARCHIVE, outcome=result),
                                       dict(START, outcome={'state': 'done'})]), mode='run')
                self.world['replies'] = {'fleet tick --expect-plan':
                                        {'exit': 0, 'out': json.dumps(report)}}
                self.assertEqual(self.tick(), report)
                self.assert_one_pinned_execution()

    # Retain refusal if the restriction cannot be established.
    def test_binary_without_the_restriction_refuses_before_any_tick(self):
        for name, world in (
            ('no --expect-plan flag', {'catalogue': catalogue(['--json'])}),
            ('no fleet.tick entry', {'catalogue': dict(catalogue([]), commands=[])}),
            ('two fleet.tick entries', {'catalogue': dict(catalogue(['--expect-plan']), commands=2 * catalogue(['--expect-plan'])['commands'][:1])}),
            ('another catalogue schema', {'catalogue': dict(catalogue(['--expect-plan']), schema='openwiz.cli.v2')}),
            ('not a catalogue object', {'catalogue': []}),
            ('another catalogue kind', {'catalogue': dict(catalogue(['--expect-plan']), kind='other')}),
            ('not a command array', {'catalogue': dict(catalogue([]), commands={})}),
            ('not an iterable command list', {'catalogue': dict(catalogue([]), commands=1)}),
            ('not a command object', {'catalogue': dict(catalogue([]), commands=[['fleet.tick']])}),
            ('another command name', {'catalogue': dict(catalogue([]), commands=[dict(catalogue(['--expect-plan'])['commands'][0], name='fleet.tick.preview')])}),
            ('another tick argv', {'catalogue': dict(catalogue([]), commands=[dict(catalogue(['--expect-plan'])['commands'][0], argv=['other'])])}),
            ('not a flags array', {'catalogue': dict(catalogue([]), commands=[dict(catalogue([])['commands'][0], flags='--expect-plan')])}),
            ('help fails', {'replies': {'help --agent': {'exit': 2, 'out': ''}}}),
            ('failed help with valid output', {'replies': {'help --agent': {'exit': 1, 'out': json.dumps(catalogue(['--expect-plan']))}}}),
            ('help is not JSON', {'replies': {'help --agent': {'exit': 0, 'out': 'usage'}}}),
        ):
            with self.subTest(name):
                self.setUp()
                self.world.update(world)
                self.refused('restriction_unavailable')
                self.assertEqual([c['argv'] for c in self.calls()], [['help', '--agent']])
                self.assert_no_execution()

    def test_invalid_preview_refuses_before_any_execution(self):
        good = preview([ARCHIVE, START])
        for name, reply in (
            ('preview failed', {'exit': 1, 'out': ''}),
            ('failed preview with valid output', {'exit': 1, 'out': json.dumps(good)}),
            ('a run, not a dry run', {'exit': 0, 'out': json.dumps(dict(good, mode='run'))}),
            ('an outcome not planned', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, outcome={'state': 'done'})]))}),
            ('another schema', {'exit': 0, 'out': json.dumps(dict(good, schema='openwiz.fleet-tick.v2'))}),
            ('an extra field', {'exit': 0, 'out': json.dumps(dict(good, extra=None))}),
            ('a missing field', {'exit': 0, 'out': json.dumps({k: v for k, v in good.items() if k != 'rules'})}),
            ('not an object', {'exit': 0, 'out': '[]'}),
            ('fields array', {'exit': 0, 'out': json.dumps(['schema', 'mode', 'planned_at', 'default_branch', 'rules', 'actions'])}),
            ('not an action array', {'exit': 0, 'out': json.dumps(dict(good, actions={}))}),
            ('not a rules object', {'exit': 0, 'out': json.dumps(dict(good, rules=[]))}),
            ('empty branch', {'exit': 0, 'out': json.dumps(dict(good, default_branch=''))}),
            ('not a branch string', {'exit': 0, 'out': json.dumps(dict(good, default_branch=True))}),
            ('not an action object', {'exit': 0, 'out': json.dumps(dict(good, actions=[[]]))}),
            ('action fields array', {'exit': 0, 'out': json.dumps(dict(good, actions=[['kind', 'rule', 'spec', 'ticket', 'facts', 'outcome']]))}),
            ('not a kind string', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, kind=True)]))}),
            ('not a rule string', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, rule=True)]))}),
            ('not a facts object', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, facts=[])]))}),
            ('not an outcome object', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, outcome=[])]))}),
            ('not a spec number', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, spec=True)]))}),
            ('not a ticket number', {'exit': 0, 'out': json.dumps(dict(good, actions=[dict(ARCHIVE, ticket=True)]))}),
            ('an action field missing', {'exit': 0, 'out': json.dumps(dict(good, actions=[{k: v for k, v in ARCHIVE.items() if k != 'facts'}]))}),
            ('a negative time', {'exit': 0, 'out': json.dumps(dict(good, planned_at=-1))}),
            ('a time past 64 bits', {'exit': 0, 'out': json.dumps(dict(good, planned_at=2**64))}),
            ('a bool time', {'exit': 0, 'out': json.dumps(dict(good, planned_at=True))}),
            ('a float time', {'exit': 0, 'out': json.dumps(dict(good, planned_at=1.5))}),
            ('a duplicate key deep inside', {'exit': 0, 'out': json.dumps(good)[:-3] + ',"facts":{}}]}'}),
            ('NaN', {'exit': 0, 'out': json.dumps(dict(good, planned_at=float('nan')))}),
            ('not UTF-8', {'exit': 0, 'hex': json.dumps(good).encode().hex().replace('6d61696e', '6d61ff6e')}),
        ):
            with self.subTest(name):
                self.setUp()
                self.world['replies'] = {'fleet tick --dry-run': reply}
                self.refused('invalid_plan')
                self.assert_no_execution()

    # P3: the public launcher boundary promises bounded bytes; neither an
    # oversized result nor an overflowed number may bypass that guard. Ordinary
    # fake subprocess output always has the right Python type and small size.
    def test_preview_transport_and_numeric_bounds_refuse(self):
        overflow = json.dumps(preview([dict(ARCHIVE, facts={'value': 'OVERFLOW'})]))
        for raw in ('{}', json.dumps(preview([])).encode() + b' ' * (32 * 1024 * 1024),
                    overflow.replace('"OVERFLOW"', '1e999').encode()):
            with self.subTest(type=type(raw).__name__, size=len(raw)):
                self.setUp()

                def launch(argv):
                    if '--dry-run' in argv:
                        return 0, raw
                    return self.launch(argv)
                with self.assertRaises(restriction.Refused) as caught:
                    restriction.establish(str(self.openwiz), self.state, launch)
                self.assertEqual(str(caught.exception), 'invalid_plan')
                self.assert_no_execution()

    def test_audit_refusal_stops_before_any_execution(self):
        seen = []

        def audit(plan):
            seen.append(plan)
            return False
        self.world['preview'] = self.world['current'] = preview([ARCHIVE, START, EXTRA])
        self.refused('out_of_scope', audit)
        self.assertEqual(seen, [self.world['preview']], 'the audit reads the exact preview')
        self.assert_no_execution()

    def test_unsafe_plan_directory_refuses_before_any_execution(self):
        def group_readable(state):
            state.chmod(0o750)

        def symlink(state):
            state.rmdir()
            (self.root / 'elsewhere').mkdir(mode=0o700)
            state.symlink_to(self.root / 'elsewhere')

        def missing(state):
            state.rmdir()

        def regular_file(state):
            state.rmdir()
            state.write_text('synthetic')
            state.chmod(0o700)

        def leftover(state):
            (state / restriction.PLAN_NAME).write_text('{}')
            (state / restriction.PLAN_NAME).chmod(0o600)
        for name, plant, reason in (('group-readable', group_readable, 'unsafe_plan_dir'),
                                    ('a symlink', symlink, 'unsafe_plan_dir'),
                                    ('missing', missing, 'unsafe_plan_dir'),
                                    ('not a directory', regular_file, 'unsafe_plan_dir'),
                                    ('an earlier plan left behind', leftover, 'plan_exists')):
            with self.subTest(name):
                self.setUp()
                plant(self.state)
                self.refused(reason)
                # An unusable directory is refused before any launch; a leftover
                # plan only once the preview exists to be saved.
                self.assertEqual([c['argv'] for c in self.calls()],
                                 [['help', '--agent'], ['fleet', 'tick', '--dry-run', '--json']]
                                 if reason == 'plan_exists' else [])
                self.assertEqual(self.effects(), [])
                if reason == 'plan_exists':
                    self.assertEqual((self.state / restriction.PLAN_NAME).read_text(), '{}', 'never replaced')

    def test_saved_plan_is_owner_only(self):
        modes = []

        def launch(argv):
            if '--expect-plan' in argv:
                modes.append(os.stat(argv[argv.index('--expect-plan') + 1]).st_mode & 0o777)
            return self.launch(argv)
        pinned = restriction.establish(str(self.openwiz), self.state, launch)
        restriction.execute(pinned, launch)
        self.assertEqual(modes, [0o600])

    def test_state_owned_by_another_user_refuses_before_launch(self):
        # The release entrypoint runs cases concurrently. Keep the OS identity
        # override in a child so parallel cases keep their real process UID.
        # Directory metadata, refusal and no-launch assertions remain real.
        proof = """
import os, runpy, sys
from unittest.mock import patch
case = runpy.run_path(sys.argv[1])['Restriction']()
try:
    case.setUp()
    with patch.object(os, 'getuid', return_value=os.getuid() + 1):
        case.refused('unsafe_plan_dir')
    case.assertEqual(case.calls(), [])
    case.assert_no_execution()
finally:
    case.doCleanups()
"""
        done = subprocess.run([sys.executable, '-I', '-c', proof, str(Path(__file__).resolve())],
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr).decode(errors='replace'))

    def test_relative_program_or_state_refuses(self):
        with self.assertRaises(restriction.Refused) as caught:
            restriction.establish('openwiz', self.state, self.launch)
        self.assertEqual(str(caught.exception), 'restriction_unavailable')
        with self.assertRaises(restriction.Refused) as caught:
            restriction.establish(self.openwiz, self.state, self.launch)
        self.assertEqual(str(caught.exception), 'restriction_unavailable')
        with self.assertRaises(restriction.Refused) as caught:
            restriction.establish(str(self.openwiz), Path(os.path.relpath(self.state)), self.launch)
        self.assertEqual(str(caught.exception), 'unsafe_plan_dir')
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
