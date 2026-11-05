"""Command-boundary proofs. All executable responses and identifiers are synthetic."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name('smoke.py')
# The runner's own journal/replay code, loaded by path (this folder's http.py
# must not shadow the standard library), to set state as an interruption would.
import importlib.util
_SPEC = importlib.util.spec_from_file_location('live_smoke_runner_for_tests', RUNNER.resolve())
SMOKE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SMOKE)
CLAIMS = ['fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'terminal', 'json', 'send', 'new', 'app', 'read_safety']
CATALOGUE = {'schema': 'openwiz.cli.v1', 'kind': 'catalogue', 'commands': [
    {'name': 'fleet.tick', 'argv': ['fleet', 'tick'], 'flags': ['--dry-run', '--expect-plan', '--json']}]}
SCOPE = {'specs': [9001], 'tickets': [9002, 9003, 9004], 'rules': ['frontier'], 'never_start': [9004]}
ACTION = {'kind': 'start_builder', 'rule': 'frontier', 'spec': 9001, 'ticket': 9002,
          'facts': {}, 'outcome': {'state': 'planned'}}


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = self.root / 'calls'
        self.fake = self.root / 'fake-room-cli'
        self.fake.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
with (root / 'calls').open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
case = sys.argv[1]
replies = json.loads((root / 'replies.json').read_text())
key = ' '.join(sys.argv[1:4])
reply = replies[key] if key in replies else replies[case]
print(reply['out'])
print('SENSITIVE_DIAGNOSTIC', file=sys.stderr)
sys.exit(reply['exit'])
''')
        self.fake.chmod(0o700)
        self.replies = {'ls': {'exit': 0, 'out': json.dumps({
            'schema': 'openwiz.inventory.v1', 'coverage': {'state': 'complete'},
            'gaps': [], 'data': {'sessions': []}})}}
        steps = []
        for claim in CLAIMS:
            self.replies[claim] = {'exit': 0, 'out': json.dumps({
                'count': 1, 'id': 'thr_synthetic_private', 'known': True})}
            steps.append({'id': claim, 'claim': claim,
                          'kind': 'write' if claim in ('fleet', 'send', 'new') else 'read',
                          'argv': [str(self.fake), claim], 'exit': 0,
                          'checks': [{'path': '/count', 'equals': 1},
                                     {'path': '/known', 'equals': True}]})
        self.kit = {'schema': 'openwiz.live-smoke-kit.v1', 'mode': 'fixture',
                    'cwd': str(self.root), 'openwiz': str(self.fake),
                    'artifacts': {str(self.fake): self.sha(self.fake)},
                    'env': {}, 'timeout_seconds': 2, 'steps': steps}
        self.kit_path = self.root / 'kit.json'
        self.state = self.root / 'state'

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def run_tool(self, *args):
        self.kit_path.write_text(json.dumps(self.kit))
        (self.root / 'replies.json').write_text(json.dumps(self.replies))
        return subprocess.run([sys.executable, '-I', str(RUNNER),
                               '--kit', str(self.kit_path), '--state', str(self.state),
                               *args], capture_output=True, text=True, timeout=10)

    def invoke(self):
        return self.run_tool('--fixture')

    def restricted_tick(self, step, actions=(ACTION,), extra=()):
        """Make `step` the fleet tick; the fake offers #1892's restriction."""
        step['argv'] = [str(self.fake), 'fleet', 'tick', '--json']
        step['checks'] = [{'path': '/actions', 'actions_in': SCOPE}, *extra]
        plan = {'schema': 'openwiz.fleet-tick.v1', 'mode': 'dry_run', 'planned_at': 1893542400,
                'default_branch': 'scratch', 'rules': {}, 'actions': list(actions)}
        self.replies['help --agent'] = {'exit': 0, 'out': json.dumps(CATALOGUE)}
        self.replies['fleet tick --dry-run'] = {'exit': 0, 'out': json.dumps(plan)}
        self.replies['fleet'] = {'exit': 0, 'out': json.dumps(dict(
            plan, mode='run', actions=[dict(a, outcome={'state': 'done'}) for a in actions]))}
        return plan

    def rewrite_journal(self, edit):
        """Rewrite the journal's events (re-chained) and save their replay as the
        checkpoint: a consistent synthetic state, never a bare checkpoint edit."""
        _, events = SMOKE.read_journal(self.state)
        events = [edit(dict(e)) for e in events]
        prev, lines = '0' * 64, []
        for seq, event in enumerate(events):
            line = SMOKE.canonical({'seq': seq, 'prev': prev, 'event': event})
            lines.append(line + b'\n')
            prev = hashlib.sha256(line).hexdigest()
        (self.state / 'journal.jsonl').write_bytes(b''.join(lines))
        SMOKE.save(self.state, SMOKE.replay(json.loads(self.kit_path.read_text()), events))

    def ticks(self):
        """Every executing tick: only the pinned form may ever appear."""
        return [c for c in self.call_list() if c[:2] == ['fleet', 'tick'] and '--dry-run' not in c]

    def call_list(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def report(self, result, code):
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        self.assertNotIn('SENSITIVE_DIAGNOSTIC', result.stdout + result.stderr)
        self.assertNotIn('thr_synthetic_private', result.stdout + result.stderr)
        return json.loads(result.stdout)


class Smoke(FixtureCase):
    def test_complete_then_resume_never_repeats_effects(self):
        doc = self.report(self.invoke(), 0)
        self.assertEqual(doc['verdict'], 'pass')
        self.assertEqual(doc['evidence'], 'fixture')
        self.assertEqual(doc['claims'], {c: 'pass' for c in CLAIMS})
        self.assertEqual(self.call_list(), [['ls', '--json']] + [[c] for c in CLAIMS])
        self.report(self.invoke(), 0)
        self.assertEqual(self.call_list().count(['send']), 1)
        self.assertNotIn('thr_synthetic_private', (self.state / 'checkpoint.json').read_text())

    def test_bundle_refusal_has_no_effect_and_can_start_when_fixed(self):
        self.replies['ls'] = {'exit': 1, 'out': '{"schema":"openwiz.cli-error.v1"}'}
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'bundle_preflight')
        self.assertEqual(self.call_list(), [['ls', '--json']])
        self.replies['ls'] = {'exit': 0, 'out': json.dumps({
            'schema': 'openwiz.inventory.v1', 'coverage': {'state': 'complete'},
            'gaps': [], 'data': {'sessions': []}})}
        self.report(self.invoke(), 0)

    def test_dry_run_executes_nothing_and_creates_no_state(self):
        doc = self.report(self.run_tool('--dry-run'), 0)
        self.assertEqual(doc['verdict'], 'not_run')
        self.assertEqual(doc['claims'], {c: 'not_run' for c in CLAIMS})
        self.assertEqual(self.call_list(), [])
        self.assertFalse(self.state.exists())

    def test_every_promise_required_before_any_execution(self):
        for claim in CLAIMS:
            with self.subTest(claim=claim):
                original = self.kit['steps']
                self.kit['steps'] = [s for s in original if s['claim'] != claim]
                self.report(self.invoke(), 2)
                self.assertEqual(self.call_list(), [])
                self.kit['steps'] = original

    def test_wrong_fact_is_fail_and_not_retried(self):
        self.replies['send']['out'] = '{"count":2,"known":true}'
        doc = self.report(self.invoke(), 1)
        self.assertEqual(doc['claims']['send'], 'fail')
        self.assertEqual(doc['reason'], 'comparison')
        self.report(self.invoke(), 1)
        self.assertEqual(self.call_list().count(['send']), 1)
        self.assertNotIn(['new'], self.call_list())

    def test_missing_or_duplicate_or_wrong_type_fact_is_never_pass(self):
        for raw in ('{}', '{"count":1,"count":1,"known":true}',
                    '{"count":true,"known":true}', '[]', 'not-json',
                    '{"count":1,"known":true} trailing'):
            with self.subTest(raw=raw):
                self.state = self.root / ('state-' + hashlib.sha256(raw.encode()).hexdigest())
                self.replies['swarms']['out'] = raw
                self.assertNotEqual(self.report(self.invoke(), 3 if raw in ('{}', '[]', 'not-json', '{"count":1,"count":1,"known":true}', '{"count":1,"known":true} trailing') else 1)['verdict'], 'pass')

    def test_failed_write_stays_uncertain_on_resume(self):
        self.replies['send'] = {'exit': 9, 'out': '{}'}
        doc = self.report(self.invoke(), 3)
        self.assertEqual(doc['reason'], 'uncertain_write')
        self.report(self.invoke(), 3)
        self.assertEqual(self.call_list().count(['send']), 1)

    def test_event_ends_and_resume_does_not_repeat_completed_steps(self):
        self.kit['steps'].insert(1, {'id': 'next_event', 'claim': 'fleet', 'kind': 'event'})
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'next_event')
        self.assertEqual(self.call_list(), [['ls', '--json'], ['fleet']])
        self.report(self.invoke(), 0)
        self.assertEqual(self.call_list().count(['fleet']), 1)

    def test_independent_read_comparison(self):
        step = self.kit['steps'][1]
        step['checks'].append({'path': '/id', 'same_as': {'step': 'fleet', 'path': '/id'}})
        self.report(self.invoke(), 0)
        # A fresh run with mismatched independent values must fail.
        self.state = self.root / 'other-state'
        self.replies['swarms']['out'] = '{"count":1,"known":true,"id":"different"}'
        self.report(self.invoke(), 1)

    def test_unpinned_command_and_unknown_claim_refuse(self):
        self.kit['steps'][0]['argv'][0] = '/not/pinned'
        self.report(self.invoke(), 2)
        self.assertEqual(self.call_list(), [])
        self.kit['steps'][0]['argv'][0] = str(self.fake)
        self.kit['steps'][0]['claim'] = 'unknown'
        self.report(self.invoke(), 2)
        self.assertEqual(self.call_list(), [])

    def test_changed_kit_or_artifact_refuses_resume(self):
        self.report(self.invoke(), 0)
        self.kit['timeout_seconds'] = 3
        self.report(self.invoke(), 2)
        self.kit['timeout_seconds'] = 2
        self.fake.write_text(self.fake.read_text() + '\n# changed\n')
        self.report(self.invoke(), 2)

    def test_live_kit_cannot_use_fixture_mode_or_unapproved_digest(self):
        self.kit['mode'] = 'live'
        self.report(self.invoke(), 2)
        self.report(self.run_tool('--execute', '0' * 64), 2)
        self.assertEqual(self.call_list(), [])


    def test_fleet_continues_one_tick_per_event_until_readback(self):
        self.restricted_tick(self.kit['steps'][0])
        wait = {'id': 'fleet_done', 'claim': 'fleet', 'kind': 'await',
                'argv': [str(self.fake), 'done'], 'exit': 0,
                'checks': [{'path': '/safe', 'equals': True}],
                'until': [{'path': '/merged', 'equals': 2}], 'again_from': 'fleet'}
        self.replies['done'] = {'exit': 0, 'out': '{"merged":0,"safe":true}'}
        self.kit['steps'][1:1] = [{'id': 'tick_event', 'claim': 'fleet', 'kind': 'event'}, wait]
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'next_event')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'pending')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'next_event')
        self.assertEqual(len(self.ticks()), 2)
        self.replies['done']['out'] = '{"merged":2,"safe":true}'
        self.report(self.invoke(), 0)
        self.assertEqual(len(self.ticks()), 2)
        self.assertTrue(all(t[2] == '--expect-plan' for t in self.ticks()))

    def test_only_fleet_tick_can_be_repeated(self):
        self.kit['steps'].append({'id': 'repeat_send', 'claim': 'send', 'kind': 'await',
                                 'argv': [str(self.fake), 'send'], 'exit': 0,
                                 'checks': [{'path': '/count', 'equals': 2}],
                                 'again_from': 'send'})
        self.report(self.invoke(), 2)
        self.assertEqual(self.call_list(), [])

    def test_attempting_checkpoint_refuses_without_any_execution(self):
        self.kit['steps'].insert(0, {'id': 'event', 'claim': 'fleet', 'kind': 'event'})
        self.report(self.invoke(), 3)
        # Interrupted after the fsynced attempt, before anything else was saved.
        SMOKE.journal(self.state, {'kind': 'attempt', 'id': 'fleet', 'claim': 'fleet',
                                   'sittings': 0, 'fleet_started': 0})
        before = self.call_list()
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(self.call_list(), before)
        # A checkpoint edited without its journal is refused, not trusted.
        checkpoint = self.state / 'checkpoint.json'
        state = json.loads(checkpoint.read_text())
        state['steps'][1]['state'] = 'pass'
        checkpoint.write_text(json.dumps(state))
        self.assertEqual(self.report(self.invoke(), 2)['reason'], 'invalid_state')
        self.assertEqual(self.call_list(), before)

    def test_lock_contention_refuses_without_execution(self):
        import fcntl
        self.state.mkdir(mode=0o700)
        with (self.state / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.report(self.invoke(), 2)['reason'], 'runner_busy')
        self.assertEqual(self.call_list(), [])

    def test_timeout_write_cannot_be_replayed(self):
        text = self.fake.read_text().replace("case = sys.argv[1]", "case = sys.argv[1]\nif case == 'send':\n    import signal\n    signal.pause()")
        self.fake.write_text(text)
        self.kit['artifacts'][str(self.fake)] = self.sha(self.fake)
        self.kit['timeout_seconds'] = 1
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.report(self.invoke(), 3)
        self.assertEqual(self.call_list().count(['send']), 1)

    def test_wrong_await_invariant_is_failure_not_pending(self):
        self.kit['steps'].insert(1, {'id': 'safe_readback', 'claim': 'fleet',
            'kind': 'await', 'argv': [str(self.fake), 'safety'], 'exit': 0,
            'checks': [{'path': '/safe', 'equals': True}]})
        self.replies['safety'] = {'exit': 0, 'out': '{"safe":false}'}
        self.assertEqual(self.report(self.invoke(), 1)['reason'], 'comparison')
        self.assertNotIn(['send'], self.call_list())

    def test_standard_sheet_prepares_exclusively_and_dry_runs(self):
        template = json.loads(RUNNER.with_name('combined.template.json').read_text())
        inputs = {}
        def collect(value):
            if isinstance(value, dict):
                for v in value.values(): collect(v)
            elif isinstance(value, list):
                for v in value: collect(v)
            elif isinstance(value, str) and value.startswith('@'):
                name = value[1:]
                if name == 'release':
                    inputs[name] = {'scope': {'writes': {}}, 'products': [], 'coverage': [], 'risk': {}, 'gaps': []}
                elif name.endswith('_checks'):
                    inputs[name] = [{'path': '/count', 'equals': 1}]
                elif name.endswith('_argv'):
                    inputs[name] = [str(self.fake), 'readback']
                else:
                    inputs[name] = str(self.fake)
        collect(template)
        inputs.update(mode='fixture', scratch_checkout=str(self.root), port='7370', env={},
                      artifacts={str(self.fake): self.sha(self.fake)},
                      source={'checkout': str(self.root), 'head': '0' * 40},
                      fleet_scope={'specs': [9001], 'tickets': [9002, 9003, 9004],
                                   'rules': ['frontier', 'adr_0008'], 'never_start': [9004]})
        source = self.root / 'inputs.json'
        out = self.root / 'bound.json'
        source.write_text(json.dumps(inputs))
        argv = [sys.executable, '-I', str(RUNNER.with_name('prepare.py')),
                '--inputs', str(source), '--out', str(out)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['prepared'])
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(out.read_text())['default_terminal_port'], '7370')
        original = out.read_bytes()
        again = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        self.assertEqual(again.returncode, 2)
        self.assertEqual(out.read_bytes(), original)
        dry = subprocess.run([sys.executable, '-I', str(RUNNER), '--kit', str(out),
                              '--state', str(self.state), '--dry-run'],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual(json.loads(dry.stdout)['claims'], {c: 'not_run' for c in CLAIMS})
        self.assertEqual(self.call_list(), [])
        self.assertFalse(self.state.exists())

    def test_http_probe_preserves_duplicate_keys_for_the_strict_reader(self):
        import http.server
        import threading
        body = b'{"count":1,"count":2}'
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        with http.server.HTTPServer(('127.0.0.1', 0), Handler) as server:
            server.timeout = 3
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                result = subprocess.run([sys.executable, '-I', str(RUNNER.with_name('http.py')),
                    str(server.server_port), '/api/v1/loops'], capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, body)
            finally:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

    def test_uncertain_tick_stops_even_when_exit_and_selected_facts_pass(self):
        plan = self.restricted_tick(self.kit['steps'][0],
                                    extra=[{'path': '/schema', 'equals': 'openwiz.fleet-tick.v1'}])
        self.replies['fleet']['out'] = json.dumps(dict(plan, mode='run', actions=[
            dict(ACTION, outcome={'state': 'uncertain', 'reason': 'synthetic'})]))
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.report(self.invoke(), 3)
        self.assertEqual(len(self.ticks()), 1)
        self.assertNotIn(['send'], self.call_list())

    def test_fleet_sitting_and_time_caps_allow_no_more_ticks(self):
        self.restricted_tick(self.kit['steps'][0])
        wait = {'id': 'fleet_done', 'claim': 'fleet', 'kind': 'await',
                'argv': [str(self.fake), 'done'], 'exit': 0,
                'checks': [{'path': '/safe', 'equals': True}],
                'until': [{'path': '/merged', 'equals': 2}], 'again_from': 'fleet'}
        self.replies['done'] = {'exit': 0, 'out': '{"merged":0,"safe":true}'}
        self.kit['steps'][1:1] = [{'id': 'tick_event', 'claim': 'fleet', 'kind': 'event'}, wait]
        for field, value in [('sittings', 60), ('started', 1)]:
            with self.subTest(field=field):
                self.state = self.root / ('capped-' + field)
                self.report(self.invoke(), 3)
                self.report(self.invoke(), 3)
                key = 'fleet_started' if field == 'started' else field
                self.rewrite_journal(lambda e: dict(e, **{key: value}) if e['kind'] == 'attempt' else e)
                before = self.call_list()
                self.assertEqual(self.report(self.invoke(), 3)['reason'], 'fleet_limit')
                # Not even the restriction's read-only preview runs at the cap.
                new = self.call_list()[len(before):]
                self.assertTrue(set(map(tuple, new)) <= {('ls', '--json'), ('done',)}, new)

        # Expiry also bounds the final observation, not only the next write.
        self.state = self.root / 'expired-but-merged'
        self.report(self.invoke(), 3)
        self.rewrite_journal(lambda e: dict(e, fleet_started=1) if e['kind'] == 'attempt' else e)
        self.replies['done']['out'] = '{"merged":2,"safe":true}'
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'fleet_limit')

    def test_fleet_tick_executes_only_the_saved_expected_plan(self):
        self.restricted_tick(self.kit['steps'][0])
        self.report(self.invoke(), 0)
        calls = self.call_list()
        self.assertEqual(calls[1:4], [['help', '--agent'], ['fleet', 'tick', '--dry-run', '--json'],
                                      ['fleet', 'tick', '--expect-plan',
                                       str(self.state / 'fleet-expected-plan.json'), '--json']])
        self.assertNotIn(['fleet', 'tick', '--json'], calls)
        self.assertFalse((self.state / 'fleet-expected-plan.json').exists())

    def test_unestablished_restriction_refuses_before_any_tick(self):
        cases = {
            'restriction_unavailable': ('help --agent', dict(CATALOGUE, commands=[
                {'name': 'fleet.tick', 'argv': ['fleet', 'tick'], 'flags': ['--dry-run', '--json']}])),
            'out_of_scope': ('fleet tick --dry-run', None),
            'invalid_plan': ('fleet tick --dry-run', 'run'),
        }
        for reason, (key, change) in cases.items():
            with self.subTest(reason=reason):
                self.state = self.root / ('refused-' + reason)
                plan = self.restricted_tick(self.kit['steps'][0])
                if reason == 'out_of_scope':
                    change = dict(plan, actions=[dict(ACTION, ticket=9004)])
                elif reason == 'invalid_plan':
                    change = dict(plan, mode='run')
                self.replies[key] = {'exit': 0, 'out': json.dumps(change)}
                before, sends = len(self.ticks()), self.call_list().count(['send'])
                self.assertEqual(self.report(self.invoke(), 3)['reason'], reason)
                self.assertEqual(len(self.ticks()), before)
                self.assertEqual(self.call_list().count(['send']), sends)
                self.assertFalse((self.state / 'fleet-expected-plan.json').exists())
                # Nothing was consumed: once the restriction holds, the same command ticks once.
                self.restricted_tick(self.kit['steps'][0])
                self.report(self.invoke(), 0)
                self.assertEqual(len(self.ticks()), before + 1)

    def test_tick_that_departs_from_the_saved_plan_consumes_the_attempt(self):
        plan = self.restricted_tick(self.kit['steps'][0])
        self.replies['fleet']['out'] = json.dumps(dict(plan, mode='run', actions=[
            dict(ACTION, ticket=9003, outcome={'state': 'done'})]))
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(len(self.ticks()), 1)
        self.assertEqual(self.call_list().count(['fleet', 'tick', '--dry-run', '--json']), 1)

    def test_relative_state_directory_still_pins_the_plan(self):
        self.restricted_tick(self.kit['steps'][0])
        self.kit_path.write_text(json.dumps(self.kit))
        (self.root / 'replies.json').write_text(json.dumps(self.replies))
        result = subprocess.run([sys.executable, '-I', str(RUNNER), '--kit', str(self.kit_path),
                                 '--state', 'relative-state', '--fixture'],
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.report(result, 0)
        self.assertEqual(self.ticks(), [['fleet', 'tick', '--expect-plan',
                                         str(self.root / 'relative-state' / 'fleet-expected-plan.json'), '--json']])

    def test_tick_without_a_scope_audit_refuses(self):
        self.restricted_tick(self.kit['steps'][0])
        self.kit['steps'][0]['checks'] = [{'path': '/mode', 'equals': 'run'}]
        self.report(self.invoke(), 2)
        self.assertEqual(self.call_list(), [])

    def test_scope_allowlist_accepts_due_actions_and_refuses_extra_destinations(self):
        plan = {'id': 'scope', 'claim': 'fleet', 'kind': 'read',
            'argv': [str(self.fake), 'plan'], 'exit': 0,
            'checks': [{'path': '/actions', 'actions_in': {
                'specs': [9001], 'tickets': [9002, 9003, 9004],
                'rules': ['frontier', 'adr_0008'], 'never_start': [9004]}}]}
        self.kit['steps'].insert(0, plan)
        action = {'kind': 'start_builder', 'rule': 'frontier', 'spec': 9001,
                  'ticket': 9002, 'facts': {}, 'outcome': {'state': 'planned'}}
        self.replies['plan'] = {'exit': 0, 'out': json.dumps({'actions': [action]})}
        self.report(self.invoke(), 0)
        for key, value in [('spec', 9999), ('ticket', 9999), ('ticket', 9004),
                           ('rule', 'publish'), ('kind', 'publish'), ('ticket', 9002)]:
            with self.subTest(key=key, value=value):
                self.state = self.root / ('scope-' + key + str(value))
                changed = dict(action, **{key: value})
                self.replies['plan']['out'] = json.dumps({'actions': [action, changed]})
                before = self.call_list().count(['fleet'])
                self.report(self.invoke(), 1)
                self.assertEqual(self.call_list().count(['fleet']), before)

    def test_app_step_selects_installation_token_without_owner_fallback(self):
        text = self.fake.read_text().replace("print(reply['out'])", "if case == 'app':\n    import os\n    reply['out'] = json.dumps({'selected': os.environ.get('GH_TOKEN'), 'fallback': 'GITHUB_TOKEN' in os.environ})\nprint(reply['out'])")
        self.fake.write_text(text)
        self.kit['artifacts'][str(self.fake)] = self.sha(self.fake)
        step = next(s for s in self.kit['steps'] if s['claim'] == 'app')
        step['token_env'] = 'OPENWIZ_SMOKE_APP_TOKEN'
        step['checks'] = [{'path': '/selected', 'equals': 'synthetic-installation-token'},
                          {'path': '/fallback', 'equals': False}]
        from unittest.mock import patch
        with patch.dict(os.environ, {'OPENWIZ_SMOKE_APP_TOKEN': 'synthetic-installation-token',
                                     'GH_TOKEN': 'synthetic-owner-token',
                                     'GITHUB_TOKEN': 'synthetic-other-token'}):
            result = self.invoke()
            self.report(result, 0)
            self.assertNotIn('synthetic-installation-token', result.stdout + result.stderr)
        self.state = self.root / 'missing-app-token'
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-owner-token'}):
            os.environ.pop('OPENWIZ_SMOKE_APP_TOKEN', None)
            self.assertEqual(self.report(self.invoke(), 3)['reason'], 'missing_credential')


if __name__ == '__main__':
    unittest.main()
