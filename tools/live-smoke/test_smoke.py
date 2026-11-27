import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name('smoke.py')
import importlib.util
_SPEC = importlib.util.spec_from_file_location('live_smoke_runner_for_tests', RUNNER.resolve())
SMOKE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SMOKE)
CLAIMS = ['fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'json', 'send', 'new', 'app', 'read_safety']


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
        self.base_kit = json.loads(json.dumps(self.kit))
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

    def fleet_block(self):
        self.kit['steps'][0].update(kind='read', argv=[str(self.fake), 'fleet', '9001', '--json'])
        wait = {'id': 'fleet_done', 'claim': 'fleet', 'kind': 'await',
                'argv': [str(self.fake), 'done'], 'exit': 0,
                'checks': [{'path': '/safe', 'equals': True}],
                'until': [{'path': '/merged', 'equals': 2}], 'again_from': 'fleet'}
        self.replies['fleet 9001 --json'] = {'exit': 0, 'out': '{"count":1,"known":true}'}
        self.replies['done'] = {'exit': 0, 'out': '{"merged":0,"safe":true}'}
        self.kit['steps'][1:1] = [{'id': 'fleet_event', 'claim': 'fleet', 'kind': 'event'}, wait]

    def fleet_reads(self):
        return self.call_list().count(['fleet', '9001', '--json'])

    def rewrite_journal(self, edit, events=None):
        if events is None:
            _, events = SMOKE.read_journal(self.state)
        events = [edit(dict(e)) for e in events]
        prev, lines = '0' * 64, []
        for seq, event in enumerate(events):
            line = SMOKE.canonical({'seq': seq, 'prev': prev, 'event': event})
            lines.append(line + b'\n')
            prev = hashlib.sha256(line).hexdigest()
        (self.state / 'journal.jsonl').write_bytes(b''.join(lines))
        SMOKE.save(self.state, SMOKE.replay(json.loads(self.kit_path.read_text()), events))

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

    def test_completed_run_without_teardown_still_runs_inventory_preflight_on_resume(self):
        good_ls = dict(self.replies['ls'])
        doc = self.report(self.invoke(), 0)
        self.assertEqual((doc['verdict'], doc['reason']), ('pass', 'none'))
        self.replies['ls'] = {'exit': 1, 'out': '{"schema":"openwiz.cli-error.v1"}'}
        doc = self.report(self.invoke(), 3)
        self.assertEqual((doc['verdict'], doc['reason']), ('incomplete', 'bundle_preflight'))
        self.assertEqual(self.call_list().count(['ls', '--json']), 2)
        self.assertEqual(self.call_list().count(['send']), 1)
        _, events = SMOKE.read_journal(self.state)
        self.rewrite_journal(lambda event: event, events[:-1])
        doc = self.report(self.invoke(), 3)
        self.assertEqual((doc['verdict'], doc['reason']), ('incomplete', 'bundle_preflight'))
        self.assertEqual(json.loads((self.state / 'checkpoint.json').read_text())['times']['finished'], 0)
        self.replies['ls'] = good_ls
        doc = self.report(self.invoke(), 0)
        self.assertEqual((doc['verdict'], doc['reason']), ('pass', 'none'))
        _, resumed = SMOKE.read_journal(self.state)
        self.assertEqual([event['kind'] for event in resumed].count('finish'), 1)
        self.assertEqual(self.call_list().count(['send']), 1)

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


    def test_retired_engine_commands_refuse_before_any_step(self):
        forms = {'tick': ['fleet', 'tick', '--json'],
                 'pinned tick': ['fleet', 'tick', '--expect-plan', '/synthetic/plan.json', '--json'],
                 'tick preview': ['fleet', 'tick', '--dry-run', '--json'],
                 'engine status': ['engine', 'status', '--json'],
                 'engine activate': ['engine', 'activate']}
        for name, args in forms.items():
            for kind in ('write', 'read'):
                with self.subTest(form=name, kind=kind):
                    self.state = self.root / ('retired-' + name.replace(' ', '-') + '-' + kind)
                    self.kit['steps'][0].update(kind=kind, argv=[str(self.fake), *args])
                    self.assertEqual(self.report(self.invoke(), 2)['reason'], 'retired_command')
                    self.assertEqual(self.report(self.run_tool('--dry-run'), 2)['reason'], 'retired_command')
                    self.assertEqual(self.call_list(), [])

    def test_retired_commands_refuse_through_any_alias_of_the_pinned_program(self):
        aliases = {'symlink': lambda a: a.symlink_to(self.fake),
                   'hardlink': lambda a: os.link(self.fake, a),
                   'copy': lambda a: (a.write_bytes(self.fake.read_bytes()), a.chmod(0o700))}
        forms = {'tick': ['fleet', 'tick', '--json'], 'engine': ['engine', 'activate']}
        for name, make in aliases.items():
            alias = self.root / ('alias-' + name)
            make(alias)
            for form, args in forms.items():
                for place in ('block read', 'await'):
                    with self.subTest(alias=name, form=form, place=place):
                        self.kit = json.loads(json.dumps(self.base_kit))
                        self.fleet_block()
                        self.kit['artifacts'][str(alias)] = self.sha(self.fake)
                        index = 0 if place == 'block read' else 2
                        self.kit['steps'][index]['argv'] = [str(alias), *args]
                        self.state = self.root / ('alias-%s-%s-%s' % (name, form, place.replace(' ', '-')))
                        self.assertEqual(self.report(self.invoke(), 2)['reason'], 'retired_command')
                        self.assertEqual(self.call_list(), [])
        self.kit = json.loads(json.dumps(self.base_kit))
        missing = str(self.root / 'missing-program')
        self.kit['artifacts'][missing] = '0' * 64
        self.kit['steps'][0]['argv'] = [missing, 'fleet', 'tick', '--json']
        self.state = self.root / 'alias-unreadable'
        self.assertEqual(self.report(self.invoke(), 2)['reason'], 'retired_command')
        self.assertEqual(self.call_list(), [])

    def test_fleet_block_rereads_once_per_event_until_readback(self):
        self.fleet_block()
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'next_event')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'pending')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'next_event')
        self.assertEqual(self.fleet_reads(), 2)
        self.replies['done']['out'] = '{"merged":2,"safe":true}'
        doc = self.report(self.invoke(), 0)
        self.assertEqual(doc['claims']['fleet'], 'pass')
        self.assertEqual(self.fleet_reads(), 2)
        self.assertEqual(self.call_list().count(['send']), 1)
        self.assertFalse(any(c[:2] == ['fleet', 'tick'] for c in self.call_list()))

    def test_no_write_can_be_repeated(self):
        self.kit['steps'].append({'id': 'repeat_send', 'claim': 'send', 'kind': 'await',
                                 'argv': [str(self.fake), 'send'], 'exit': 0,
                                 'checks': [{'path': '/count', 'equals': 2}],
                                 'again_from': 'send'})
        self.report(self.invoke(), 2)
        self.assertEqual(self.call_list(), [])
        self.kit['steps'].pop()
        self.fleet_block()
        self.kit['steps'][0]['kind'] = 'write'
        self.assertEqual(self.report(self.invoke(), 2)['reason'], 'invalid_kit')
        self.assertEqual(self.call_list(), [])

    def test_attempting_checkpoint_refuses_without_any_execution(self):
        self.kit['steps'].insert(0, {'id': 'event', 'claim': 'fleet', 'kind': 'event'})
        self.report(self.invoke(), 3)
        SMOKE.journal(self.state, {'kind': 'attempt', 'id': 'fleet', 'claim': 'fleet'})
        before = self.call_list()
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'uncertain_write')
        self.assertEqual(self.call_list(), before)
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

    def test_fleet_sitting_and_time_caps_allow_no_more_sittings(self):
        self.fleet_block()
        for field in ('sittings', 'started'):
            with self.subTest(field=field):
                self.state = self.root / ('capped-' + field)
                for reason in ('next_event', 'pending', 'next_event'):
                    self.assertEqual(self.report(self.invoke(), 3)['reason'], reason)
                if field == 'sittings':
                    self.rewrite_journal(lambda e: e)
                    _, events = SMOKE.read_journal(self.state)
                    events = events + events[3:7] * 58
                    self.rewrite_journal(lambda e: e, events)
                    state = json.loads((self.state / 'checkpoint.json').read_text())
                    self.assertEqual(state['fleet']['sittings'], 60)
                else:
                    self.rewrite_journal(lambda e: dict(e, at=1) if e.get('id') == 'fleet_event' else e)
                before = self.fleet_reads()
                if field == 'sittings':
                    self.assertEqual(self.report(self.invoke(), 3)['reason'], 'pending')
                self.assertEqual(self.report(self.invoke(), 3)['reason'], 'fleet_limit')
                self.assertEqual(self.report(self.invoke(), 3)['reason'], 'fleet_limit')
                self.assertEqual(self.fleet_reads(), before)

        self.state = self.root / 'expired-but-merged'
        self.report(self.invoke(), 3)
        self.rewrite_journal(lambda e: dict(e, at=1) if e.get('id') == 'fleet_event' else e)
        self.replies['done']['out'] = '{"merged":2,"safe":true}'
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'fleet_limit')

        self.state = self.root / 'capped-sittings'
        _, events = SMOKE.read_journal(self.state)
        with self.assertRaises(SMOKE.Refusal):
            SMOKE.replay(json.loads(self.kit_path.read_text()), events + events[3:7])

    def test_only_a_write_step_may_wait_longer_up_to_130_seconds(self):
        text = self.fake.read_text().replace("case = sys.argv[1]", "case = sys.argv[1]\nif case == 'new':\n    import time\n    time.sleep(3)")
        self.fake.write_text(text)
        self.kit['artifacts'][str(self.fake)] = self.sha(self.fake)
        new = next(s for s in self.kit['steps'] if s['id'] == 'new')
        for name, (step, value) in {'above 130': (new, 131), 'on a read': (self.kit['steps'][3], 5),
                                    'not an integer': (new, '5')}.items():
            with self.subTest(name):
                step['timeout_seconds'] = value
                self.state = self.root / name.replace(' ', '-')
                self.assertEqual(self.report(self.invoke(), 2)['reason'], 'invalid_kit')
                self.assertEqual(self.call_list(), [])
                del step['timeout_seconds']
        new['timeout_seconds'] = 5
        self.state = self.root / 'slow-write'
        self.assertEqual(self.report(self.invoke(), 0)['claims']['new'], 'pass')
        self.assertEqual(self.call_list().count(['new']), 1)

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


class ShippedCommands(unittest.TestCase):
    def test_every_openwiz_step_in_the_template_is_a_shipped_command(self):
        root = RUNNER.resolve().parents[2]
        catalogue = json.loads((root / 'crates/cli/src/agent-catalogue.json').read_text())
        shipped = [c['argv'] for c in catalogue['commands']]
        template = json.loads(RUNNER.with_name('combined.template.json').read_text())
        for step in template['steps']:
            argv = step.get('argv')
            if not isinstance(argv, list):
                continue
            self.assertNotIn('@pty_driver', argv, step['id'])
            if argv[0] != '@openwiz':
                continue
            words = [a for a in argv[1:] if not a.startswith(('-', '@'))]
            self.assertTrue(any(words[:len(c)] == c for c in shipped),
                            f"{step['id']}: openwiz {' '.join(argv[1:])} is not a shipped command")


FAKE_DRIVER = """#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
root = pathlib.Path(__file__).parent
state = pathlib.Path(os.environ['OPENWIZ_CLOUDROOM_STATE'])
cmd = sys.argv[1]
body = sys.stdin.read()
with (root / 'driver-calls').open('a') as log:
    log.write(json.dumps([cmd, json.loads(body) if body else None, os.environ.get('ROOM_PROJECT_ID'),
                          shutil.which('room-cli')]) + '\\n')
if cmd == 'version':
    out = {'driver': 'cloudroom', 'records': ['openwiz:records v1'], 'can': ['start', 'wake', 'stop']}
elif cmd == 'start':
    req = json.loads(body)
    assert type(req['ticket']) is int
    (state / 'run-0123456789ab.json').write_text(json.dumps({'thread': 'synthetic-child-thread', 'request': req}))
    (root / 'room-state').write_text(json.dumps({'projectId': os.environ['ROOM_PROJECT_ID'], 'archived': False}))
    if (root / 'lose-start').exists():
        sys.exit(1)
    out = {'run': 'run-0123456789ab'}
elif cmd == 'wake' and (root / 'refuse-wake').exists():
    print(json.dumps({'error': 'Cloudroom did not take the wake: synthetic refusal', 'next': 'leave the run'}))
    sys.exit(1)
elif cmd == 'wake':
    if not (root / 'no-delivery').exists():
        with (root / 'room-log').open('a') as log:
            log.write('You were woken for example/throwaway#7: read the ticket again\\n')
    out = {'run': json.loads(body)['run'], 'woke': True}
elif cmd == 'stop':
    (root / 'room-state').write_text(json.dumps({'projectId': 'proj_synthetic', 'archived': True}))
    record = state / (json.loads(body)['run'] + '.json')
    record.write_text(json.dumps(dict(json.loads(record.read_text()), archived=True)))
    out = {'run': json.loads(body)['run'], 'stopped': True}
print(json.dumps(out))
"""
FAKE_ROOM = """#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
assert sys.argv[1:3] in (['thread', 'show'], ['thread', 'log']) and sys.argv[3] == 'synthetic-child-thread', sys.argv
with (root / 'room-calls').open('a') as log:
    log.write(json.dumps(sys.argv[1:3]) + '\\n')
state = dict(json.loads((root / 'room-state').read_text()), id='synthetic-child-thread')
if sys.argv[2] == 'log':
    text = (root / 'room-log').read_text() if (root / 'room-log').exists() else ''
    if text and (root / 'host-local').exists():
        text = '[message from thread:synthetic-parent]\\n\\n%s\\n── Worked for (1ms) ──\\n' % text
    print(text)
elif not (root / 'host-local').exists():
    print(json.dumps(state))
elif '--json' not in sys.argv:
    print('ID  TITLE  STATUS\\n%s  synthetic  idle' % state['id'])
else:
    print(json.dumps({'thread': {'id': state['id'], 'title': 'synthetic', 'projectId': state['projectId'],
                                 'parentThreadId': None, 'providerId': 'claude-code', 'status': 'idle',
                                 'createdAt': 1700000000000, 'updatedAt': 1700000000000, 'deletedAt': None,
                                 'archivedAt': 1700000000000 if state['archived'] else None},
                      'environment': {}, 'execution': {}, 'pendingTodos': []}))
"""
FAKE_CLI = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:1] == ['status']:
    out = {'schema': 'openwiz.install-status.v1', 'outcome': 'installed', 'channel': 'packaged', 'version': '0.1.0',
           'source': 'synthetic-source', 'target': 'synthetic-target', 'build': 'synthetic-build'}
elif args == ['help', '--agent']:
    out = {'schema': 'openwiz.cli.v1', 'kind': 'catalogue', 'commands': ['synthetic']}
elif args == ['ls', '--json']:
    out = {'schema': 'openwiz.inventory.v1', 'coverage': {'state': 'complete'}, 'gaps': [], 'data': {'sessions': []}}
elif args[:1] == ['show']:
    out = {'schema': 'openwiz.inventory.v1', 'data': {'session': {'id': args[1]}}}
elif args == ['api', '/installation/repositories']:
    out = {'total_count': 1, 'repositories': [{'full_name': 'example/throwaway'}]}
print(json.dumps(out))
"""
DRIVER_STEPS = {'new_preview': 'version', 'new_once': 'start', 'send_once': 'wake', 'driver_stop': 'stop'}
TEARDOWN = ['driver_stop', 'stop_status']


def template():
    return json.loads(RUNNER.with_name('combined.template.json').read_text())


class Sheet(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {'OPENWIZ_CLOUDROOM_STATE': str(self.root / 'state')}

    def program(self, name, text, folder=None):
        path = (folder or self.root) / name
        path.write_text(text)
        path.chmod(0o700)
        return str(path)

    def bound(self):
        cli = self.program('openwiz', FAKE_CLI)
        programs = {'openwiz': cli, 'gh': cli, 'install_entry': cli,
                    'driver': self.program('driver', FAKE_DRIVER), 'room_cli': self.program('room-cli', FAKE_ROOM)}
        (self.root / 'state').mkdir(exist_ok=True)
        inputs = dict(programs, mode='fixture', cwd=str(self.root), python=sys.executable,
                      artifacts={p: FixtureCase.sha(Path(p)) for p in set(programs.values()) | {sys.executable}},
                      source={'checkout': str(self.root), 'head': '0' * 40}, env=self.env,
                      install_root='/synthetic/root', install_state='/synthetic/state', install_build='synthetic-build',
                      release_version='0.1.0', release_source='synthetic-source', release_target='synthetic-target',
                      release_targets=['x86_64-unknown-linux-gnu'],
                      release_products=[{'product': 'cli', 'target': 'x86_64-unknown-linux-gnu'}],
                      release_gaps=['synthetic gap'], promise_install='synthetic_install',
                      promise_drivers='synthetic_drivers', promise_app='synthetic_app',
                      expected_catalogue_commands=['synthetic'], send_thread='synthetic-show-thread',
                      project='proj_synthetic', driver_repository='example/throwaway', driver_ticket='7',
                      driver_skill='synthetic-skill', harness='claude', model='synthetic-model',
                      app_repository='example/throwaway')
        return runpy_path('prepare.py')['bind'](template(), inputs)

    def run_sheet(self, kit=None, code=0):
        path = self.root / 'kit.json'
        path.write_text(json.dumps(kit or self.bound()))
        result = subprocess.run([sys.executable, '-I', str(RUNNER), '--kit', str(path),
                                 '--state', str(self.root / 'checkpoint'), '--fixture'],
                                capture_output=True, text=True, timeout=60,
                                env=dict({k: v for k, v in os.environ.items() if k != 'ROOM_PROJECT_ID'},
                                         OPENWIZ_SMOKE_APP_TOKEN='synthetic-installation-token'))
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('synthetic-child-thread', result.stdout + result.stderr)
        return json.loads(result.stdout)

    def driver_calls(self):
        log = self.root / 'driver-calls'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def archived(self):
        return json.loads((self.root / 'room-state').read_text())['archived']

    def test_bound_sheet_loads_and_its_release_section_is_accepted(self):
        kit = self.bound()
        path = self.root / 'kit.json'
        path.write_text(json.dumps(kit))
        SMOKE.load_kit(path)
        section = runpy_path('receipt.py')['release_section'](kit)
        self.assertEqual(section['scope']['writes'], {'send': 1, 'new': 1})
        self.assertEqual(section['scope']['spending_cents'], 0)

    def test_every_step_passes_on_a_local_and_a_cloud_room_cli(self):
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.setUp()
                if host == 'local':
                    (self.root / 'host-local').write_text('')
                doc = self.run_sheet()
                self.assertEqual(doc['claims'], {c: 'pass' for c in template()['claims']})
                self.assertEqual([c[0] for c in self.driver_calls()], ['version', 'start', 'wake', 'stop'])
                self.assertTrue(self.archived())

    def test_a_refused_wake_fails_send_on_both_room_clis_and_still_tears_down(self):
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.setUp()
                (self.root / 'refuse-wake').write_text('')
                if host == 'local':
                    (self.root / 'host-local').write_text('')
                doc = self.run_sheet(code=3)
                self.assertEqual((doc['reason'], doc['claims']['send']), ('uncertain_write', 'incomplete'))
                self.assertEqual([c[0] for c in self.driver_calls()], ['version', 'start', 'wake', 'stop'])
                self.assertTrue(self.archived())

    def test_driver_steps_start_wake_and_stop_one_run_through_the_runner(self):
        doc = self.run_sheet()
        self.assertEqual(doc['claims'], {c: 'pass' for c in template()['claims']})
        calls = self.driver_calls()
        self.assertEqual([c[0] for c in calls], ['version', 'start', 'wake', 'stop'])
        self.assertEqual(calls[1][1], {'repository': 'example/throwaway', 'ticket': 7, 'skill': 'synthetic-skill',
                                       'harness': 'claude', 'model': 'synthetic-model'})
        self.assertEqual([c[1] for c in calls[2:]], [{'run': 'run-0123456789ab'}] * 2)
        self.assertEqual(json.loads((self.root / 'room-calls').read_text().splitlines()[1]), ['thread', 'log'])
        self.assertTrue(self.archived())

    def test_the_driver_starts_only_in_the_approved_project_with_the_pinned_room_cli(self):
        decoy = self.root / 'decoy'
        decoy.mkdir()
        self.program('room-cli', FAKE_ROOM, decoy)
        self.env['PATH'] = str(decoy) + os.pathsep + os.environ.get('PATH', '')
        self.run_sheet()
        pinned = str(self.root / 'room-cli')
        self.assertEqual({(c[2], c[3]) for c in self.driver_calls()}, {('proj_synthetic', pinned)})
        (self.root / 'checkpoint').rename(self.root / 'first-checkpoint')
        (self.root / 'driver-calls').unlink()
        (self.root / 'driver-run.json').unlink()
        for run in (self.root / 'state').iterdir():
            run.unlink()
        self.env['ROOM_PROJECT_ID'] = 'proj_synthetic_stale'
        self.assertEqual(self.run_sheet(code=3)['reason'], 'command_failed')
        self.assertEqual(self.driver_calls(), [])

    def test_a_wake_the_thread_never_shows_fails_send_and_still_tears_down(self):
        (self.root / 'no-delivery').write_text('')
        kit = self.bound()
        ack = next(s for s in kit['steps'] if s['id'] == 'send_ack')
        ack['argv'][-1] = '1'
        doc = self.run_sheet(kit, code=1)
        self.assertEqual(doc['claims']['send'], 'fail')
        self.assertEqual([c[0] for c in self.driver_calls()], ['version', 'start', 'wake', 'stop'])
        self.assertTrue(self.archived())

    def test_teardown_stops_a_start_whose_answer_was_lost_and_runs_once(self):
        (self.root / 'lose-start').write_text('')
        doc = self.run_sheet(code=3)
        self.assertEqual(doc['reason'], 'uncertain_write')
        self.assertFalse((self.root / 'driver-run.json').exists())
        self.assertEqual([c[0] for c in self.driver_calls()], ['version', 'start', 'stop'])
        self.assertEqual(self.driver_calls()[2][1], {'run': 'run-0123456789ab'})
        self.assertTrue(self.archived())
        self.run_sheet(code=3)
        self.assertEqual(len(self.driver_calls()), 3)

    def test_a_reused_driver_folder_refuses_before_any_write_and_stops_nothing(self):
        (self.root / 'state').mkdir()
        other = {'thread': 'synthetic-other-thread', 'archived': False,
                 'request': {'repository': 'example/other', 'ticket': 9, 'skill': 'synthetic-skill',
                             'harness': 'claude', 'model': 'synthetic-model'}}
        (self.root / 'state' / 'run-aaaaaaaaaaaa.json').write_text(json.dumps(other))
        self.assertEqual(self.run_sheet(code=3)['reason'], 'command_failed')
        self.assertEqual(self.driver_calls(), [])
        self.assertFalse((self.root / 'room-calls').exists())
        self.assertEqual(json.loads((self.root / 'state' / 'run-aaaaaaaaaaaa.json').read_text()), other)
        events = [json.loads(line)['event']['kind'] for line in
                  (self.root / 'checkpoint' / 'journal.jsonl').read_text().splitlines()]
        self.assertNotIn('attempt', events)

    def test_teardown_stops_only_the_runs_this_kit_started(self):
        kit = self.bound()
        (self.root / 'no-delivery').write_text('')
        ack = next(s for s in kit['steps'] if s['id'] == 'send_ack')
        ack['argv'][-1] = '1'
        other = {'thread': 'synthetic-other-thread', 'archived': False,
                 'request': {'repository': 'example/other', 'ticket': 9, 'skill': 'synthetic-skill',
                             'harness': 'claude', 'model': 'synthetic-model'}}
        status = next(s for s in kit['steps'] if s['id'] == 'new_status')
        late = self.root / 'state' / 'run-bbbbbbbbbbbb.json'
        wake = next(s for s in kit['steps'] if s['id'] == 'send_once')
        wake_index = kit['steps'].index(wake)
        plant = {'id': 'plant', 'claim': 'send', 'kind': 'read', 'exit': 0,
                 'argv': [status['argv'][0], '-I', '-c',
                          'import json,sys;open(sys.argv[1],"w").write(sys.argv[2]);print(json.dumps({"ok":True}))',
                          str(late), json.dumps(other)],
                 'checks': [{'path': '/ok', 'equals': True}]}
        kit['steps'].insert(wake_index, plant)
        kit['release']['coverage'][1]['steps'].append('plant')
        self.run_sheet(kit, code=1)
        self.assertEqual([c[0] for c in self.driver_calls()], ['version', 'start', 'wake', 'stop'])
        self.assertEqual(self.driver_calls()[3][1], {'run': 'run-0123456789ab'})
        self.assertEqual(json.loads(late.read_text()), other)

    def test_driver_steps_call_only_driver_v1_commands_on_the_pinned_driver(self):
        contract = (RUNNER.resolve().parents[2] / 'kernel/driver.v1.md').read_text()
        commands = set(re.findall(r'^\| `([a-z]+)` \|', contract, re.M))
        self.assertTrue({'version', 'start', 'wake', 'stop'} <= commands, commands)
        steps = {s['id']: s for s in template()['steps']}
        for step in steps.values():
            if '@driver' in step['argv']:
                self.assertEqual(step['argv'][:4], ['@python', '-I', '-c', step['argv'][3]], step['id'])
                self.assertIn(step['argv'][4], commands, step['id'])
        self.assertEqual({i: steps[i]['argv'][4] for i in DRIVER_STEPS}, DRIVER_STEPS)
        self.assertEqual(sorted(s['id'] for s in steps.values() if s['kind'] == 'write'), ['new_once', 'send_once'])
        self.assertEqual([s['id'] for s in template()['steps'] if s.get('teardown')], TEARDOWN)
        self.assertEqual([s['id'] for s in template()['steps']][-2:], TEARDOWN)
        self.assertGreater(steps['new_once']['timeout_seconds'], 100)
        self.assertGreater(steps['driver_stop']['timeout_seconds'], 100)

    def test_every_risk_step_has_a_coverage_row(self):
        release = template()['release']
        covered = {step for row in release['coverage'] for step in row['steps']}
        for category in ('send', 'new', 'app_permissions'):
            self.assertTrue(release['risk'][category], category)
            self.assertLessEqual(set(release['risk'][category]), covered, category)
        self.assertEqual(release['risk']['spending'], [])


class Teardown(FixtureCase):
    def setUp(self):
        super().setUp()
        claims = ['json', 'new', 'loops', 'service']
        self.kit['steps'] = sorted((s for s in self.kit['steps'] if s['claim'] in claims),
                                   key=lambda s: claims.index(s['claim']))
        self.kit['steps'][-1].update(teardown=True, timeout_seconds=5)
        self.kit['claims'] = claims

    def test_teardown_runs_after_a_failure_and_closes_the_run(self):
        self.replies['loops'] = {'exit': 9, 'out': '{}'}
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'command_failed')
        self.assertEqual(self.call_list(), [['ls', '--json'], ['json'], ['new'], ['loops'], ['service']])
        self.replies['loops'] = {'exit': 0, 'out': json.dumps({'count': 1, 'known': True})}
        doc = self.report(self.invoke(), 3)
        self.assertEqual((doc['claims']['service'], doc['claims']['loops']), ('pass', 'incomplete'))
        self.assertEqual(self.call_list().count(['loops']), 1)
        self.assertEqual(self.call_list().count(['service']), 1)
        self.state = self.root / 'no-write'
        self.replies['json'] = {'exit': 9, 'out': '{}'}
        self.report(self.invoke(), 3)
        self.assertEqual(self.call_list().count(['service']), 1)

    def test_a_passed_teardown_finishes_on_resume_instead_of_torn_down(self):
        doc = self.report(self.invoke(), 0)
        self.assertEqual((doc['verdict'], doc['reason']), ('pass', 'none'))
        calls = self.call_list()
        doc = self.report(self.invoke(), 0)
        self.assertEqual((doc['verdict'], doc['reason']), ('pass', 'none'))
        self.assertEqual(self.call_list(), calls)
        _, events = SMOKE.read_journal(self.state)
        self.assertEqual([event['kind'] for event in events].count('finish'), 1)
        self.rewrite_journal(lambda event: event, events[:-1])
        checkpoint = json.loads((self.state / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['times']['finished'], 0)
        self.assertTrue(all(step['state'] == 'pass' for step in checkpoint['steps']))
        doc = self.report(self.invoke(), 0)
        self.assertEqual((doc['verdict'], doc['reason']), ('pass', 'none'))
        _, resumed = SMOKE.read_journal(self.state)
        self.assertEqual(resumed[-1]['kind'], 'finish')
        self.assertEqual([event['kind'] for event in resumed].count('finish'), 1)
        self.assertEqual(self.call_list(), calls)

    def test_a_teardown_must_be_a_read_at_the_end_within_130_seconds(self):
        rows = {'a write': lambda s: s[1].update(teardown=True), 'not at the end': lambda s: s[0].update(teardown=True),
                'above 130': lambda s: s[3].update(timeout_seconds=131),
                'not true': lambda s: s[3].update(teardown='yes')}
        for name, change in rows.items():
            with self.subTest(name):
                self.kit = json.loads(json.dumps(self.base_kit))
                self.setUp()
                change(self.kit['steps'])
                self.assertEqual(self.report(self.invoke(), 2)['reason'], 'invalid_kit')
                self.assertEqual(self.call_list(), [])


def runpy_path(name):
    import runpy
    return runpy.run_path(str(RUNNER.with_name(name)))


if __name__ == '__main__':
    unittest.main()
