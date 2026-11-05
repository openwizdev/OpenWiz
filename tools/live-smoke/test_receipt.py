"""#1844 (RL3): candidate-bound smoke and risk receipts from the runner's checkpoint.

Every program, candidate, kit, pointer and identifier here is synthetic. The
fake `openwiz` is written once at import, before tools/release/test.py starts
its threads, so no case executes a file another thread may still hold open.
Fixture results stay fixture evidence: only a live-mode checkpoint of the
approved kit, bound to the exact candidate, can satisfy a live gate.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, file):
    # Load by path: this folder's http.py must never shadow the standard library.
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load('live_smoke_runner_for_receipts', 'smoke.py')
receipt = _load('live_smoke_receipt', 'receipt.py')

_BIN = tempfile.TemporaryDirectory(prefix='receipt-fake-')
FAKE = Path(_BIN.name) / 'openwiz'
FAKE.write_text('''#!{python} -I
import json, os, pathlib, sys
here = pathlib.Path(os.getcwd())
args = sys.argv[1:]
with (here / 'calls').open('a') as log:
    log.write(json.dumps(args) + '\\n')
replies = json.loads((here / 'replies.json').read_text())
reply = replies.get(' '.join(args)) or replies.get(' '.join(args[:3])) or replies[args[0]]
print(reply['out'])
sys.exit(reply['exit'])
'''.format(python=sys.executable))
FAKE.chmod(0o700)
FAKE_SHA = hashlib.sha256(FAKE.read_bytes()).hexdigest()
RUNNER = HERE / 'smoke.py'

CATALOGUE = {'schema': 'openwiz.cli.v1', 'kind': 'catalogue', 'commands': [
    {'name': 'fleet.tick', 'argv': ['fleet', 'tick'], 'flags': ['--dry-run', '--expect-plan', '--json']}]}
SCOPE = {'specs': [9001], 'tickets': [9002, 9003, 9004], 'rules': ['frontier'], 'never_start': [9004]}
ACTION = {'kind': 'start_builder', 'rule': 'frontier', 'spec': 9001, 'ticket': 9002,
          'facts': {}, 'outcome': {'state': 'planned'}}
PLAN = {'schema': 'openwiz.fleet-tick.v1', 'mode': 'dry_run', 'planned_at': 1893542400,
        'default_branch': 'scratch', 'rules': {}, 'actions': [ACTION]}
READS = ('swarms', 'service', 'loops', 'cockpit', 'decisions', 'terminal', 'json', 'app', 'read_safety')
FLEET_ROW = ['fleet_tick'] + list(READS)
GAP = 'Synthetic gap: no real phone radio, WebKit or Mac observation.'


def contract_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


class Receipts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.kit_path = self.root / 'kit.json'
        steps = [{'id': 'fleet_tick', 'claim': 'fleet', 'kind': 'write',
                  'argv': [str(FAKE), 'fleet', 'tick', '--json'], 'exit': 0,
                  'checks': [{'path': '/actions', 'actions_in': SCOPE}]}]
        steps += [{'id': claim, 'claim': claim, 'kind': 'read', 'argv': [str(FAKE), claim],
                   'exit': 0, 'checks': [{'path': '/count', 'equals': 1}]} for claim in READS]
        steps += [{'id': claim + '_once', 'claim': claim, 'kind': 'write', 'argv': [str(FAKE), claim],
                   'exit': 0, 'checks': [{'path': '/count', 'equals': 1}]} for claim in ('send', 'new')]
        self.kit = {'schema': 'openwiz.live-smoke-kit.v1', 'mode': 'fixture', 'cwd': str(self.root),
                    'openwiz': str(FAKE), 'artifacts': {str(FAKE): FAKE_SHA}, 'env': {},
                    'timeout_seconds': 5, 'steps': steps,
                    'release': {
                        'scope': {'targets': ['synthetic-scratch'],
                                  'writes': {'fleet': 1, 'send': 1, 'new': 1},
                                  'app_permissions': ['issues:write'], 'spending_cents': 0},
                        'products': [{'product': 'cli', 'target': 'x86_64-unknown-linux-gnu'}],
                        'coverage': [
                            {'version': '0.0.99', 'promise': 'synthetic_fleet', 'steps': FLEET_ROW},
                            {'version': '0.0.99', 'promise': 'synthetic_send', 'steps': ['send_once', 'new_once']}],
                        'risk': {'send': ['send_once'], 'new': ['new_once'], 'app_permissions': ['app'],
                                 'spending': []},
                        'gaps': [GAP]}}
        replies = {claim: {'exit': 0, 'out': '{"count":1}'} for claim in READS + ('send', 'new')}
        replies.update({
            'ls --json': {'exit': 0, 'out': json.dumps({'schema': 'openwiz.inventory.v1',
                          'coverage': {'state': 'complete'}, 'gaps': []})},
            'help --agent': {'exit': 0, 'out': json.dumps(CATALOGUE)},
            'fleet tick --dry-run': {'exit': 0, 'out': json.dumps(PLAN)},
            'fleet tick --expect-plan': {'exit': 0, 'out': json.dumps(dict(
                PLAN, mode='run', actions=[dict(ACTION, outcome={'state': 'done'})]))}})
        (self.root / 'replies.json').write_text(json.dumps(replies))
        with open(ROOT / 'tests/fixtures/release/candidate/synthetic-ready.json', 'rb') as stream:
            self.candidate = json.load(stream)
        self.candidate['candidate']['included_versions'][0]['promises'] = ['synthetic_fleet', 'synthetic_send']
        self.candidate['candidate']['risk']['send'] = {'required': 'yes', 'reason': 'Synthetic send change.'}
        self.candidate['candidate']['risk']['new'] = {'required': 'yes', 'reason': 'Synthetic new change.'}
        for product in self.candidate['candidate']['products']:
            if product['identity'] == dict(product['identity'], product='cli', target='x86_64-unknown-linux-gnu'):
                product['payload_sha256'] = FAKE_SHA
        self.bind()

    def live(self):
        source = self.root / 'source'
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Synthetic',
                        '-c', 'user.email=synthetic@example.invalid',
                        'commit', '--allow-empty', '-qm', 'synthetic source'], check=True)
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        self.kit.update(mode='live', source={'checkout': str(source), 'head': head})
        for pinned in (RUNNER, HERE / 'restriction.py'):
            self.kit['artifacts'][str(pinned)] = hashlib.sha256(pinned.read_bytes()).hexdigest()
        self.bind()

    def bind(self):
        """The approved kit and its scope, as the candidate records them."""
        self.kit_path.write_text(json.dumps(self.kit))
        self.candidate['candidate']['kit']['sha256'] = smoke.digest(self.kit)
        self.candidate['candidate']['kit']['scope_sha256'] = contract_sha(self.kit['release']['scope'])
        self.reseal()

    def reseal(self):
        self.candidate['candidate_sha256'] = contract_sha(self.candidate['candidate'])

    def checkpoint(self, states=None, finished=1893542580):
        """A runner checkpoint for this kit, as smoke.py saves it."""
        self.state.mkdir(mode=0o700, exist_ok=True)
        state = smoke.initial(self.kit)
        for item, value in zip(state['steps'], states or ['pass'] * len(self.kit['steps'])):
            item['state'] = value
        state['times'] = {'started': 1893542400, 'finished': finished}
        state['candidate'] = self.candidate['candidate_sha256']
        state['writes'] = {'fleet': 1, 'send': 1, 'new': 1}
        smoke.save(self.state, state)

    def produce(self, record='synthetic:smoke-run'):
        return receipt.produce(self.kit_path, self.state, self.candidate, record)

    def refused(self, reason, call, *args):
        with self.assertRaises(receipt.Refusal) as caught:
            call(*args)
        self.assertEqual(str(caught.exception), reason)

    def execute(self, *mode, candidate=None):
        """One sitting of the runner, bound to the (current) candidate."""
        path = self.root / 'candidate.json'
        path.write_text(json.dumps(self.candidate if candidate is None else candidate))
        mode = mode or ('--execute', smoke.digest(self.kit))
        result = subprocess.run([sys.executable, '-I', str(RUNNER), '--kit', str(self.kit_path),
                                 '--state', str(self.state), *mode, '--candidate', str(path)],
                                capture_output=True, text=True, timeout=60)
        return result.returncode, json.loads(result.stdout)

    def ran(self, *mode):
        code, report = self.execute(*mode)
        self.assertEqual((code, report['verdict']), (0, 'pass'), report)

    def replies(self, **changes):
        path = self.root / 'replies.json'
        replies = json.loads(path.read_text())
        replies.update(changes)
        path.write_text(json.dumps(replies))

    def resolver(self, doc, created_at=None, line=None):
        """A synthetic private record holding the receipts' preserve line."""
        body = 'Synthetic run record.\n' + (doc['preserve'] if line is None else line) + '\n'
        at = doc['gates']['smoke']['finished_at'] if created_at is None else created_at
        return lambda record: {'body': body, 'created_at': at}

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(c) for c in path.read_text().splitlines()] if path.exists() else []

    # AC1: source/build/artifact/kit identities and per-promise outcomes.
    def test_live_run_yields_candidate_bound_smoke_and_risk_receipts(self):
        self.live()
        code, report = self.execute()
        self.assertEqual((code, report['evidence'], report['verdict']), (0, 'live', 'pass'), report)
        self.assertEqual(self.execute()[0], 0)  # resume repeats nothing
        ticks = [c for c in map(json.loads, (self.root / 'calls').read_text().splitlines())
                 if c[:2] == ['fleet', 'tick'] and '--dry-run' not in c]
        self.assertEqual([c[2] for c in ticks], ['--expect-plan'])
        doc = self.produce()
        smoke_gate = doc['gates']['smoke']
        self.assertEqual(smoke_gate['candidate_sha256'], self.candidate['candidate_sha256'])
        self.assertEqual(smoke_gate['artifacts_sha256'], contract_sha(self.candidate['candidate']['artifacts']))
        self.assertEqual(smoke_gate['kit_sha256'], self.candidate['candidate']['kit']['sha256'])
        self.assertEqual((smoke_gate['evidence_class'], smoke_gate['status']), ('live', 'pass'))
        self.assertEqual(smoke_gate['coverage'], [
            {'version': '0.0.99', 'promise': 'synthetic_fleet', 'outcome': 'pass'},
            {'version': '0.0.99', 'promise': 'synthetic_send', 'outcome': 'pass'}])
        self.assertIn(GAP, smoke_gate['gaps'])
        self.assertIn(receipt.PC_GAP, smoke_gate['gaps'])
        self.assertLessEqual(smoke_gate['started_at'], smoke_gate['finished_at'])
        self.assertEqual(doc['gates']['send']['coverage'],
                         [{'version': '0.0.99', 'promise': 'synthetic_send', 'outcome': 'pass'}])
        self.assertIsNone(doc['gates']['app_permissions'])
        self.assertIsNone(doc['gates']['spending'])
        for gate in ('smoke', 'send', 'new'):
            receipt.accept(gate, doc, self.candidate, self.kit_path, self.state, self.resolver(doc))
        inputs = doc['inputs']['smoke']
        self.assertEqual(contract_sha(inputs), smoke_gate['inputs_sha256'])
        self.assertEqual(inputs['tested_products'], [
            {'product': 'cli', 'target': 'x86_64-unknown-linux-gnu', 'payload_sha256': FAKE_SHA}])
        self.assertEqual(inputs['restriction'], 'expect-plan')
        self.assertEqual(inputs['writes_consumed'], {'fleet': 1, 'new': 1, 'send': 1})
        journal = (self.state / 'journal.jsonl').read_bytes()
        self.assertEqual(smoke_gate['evidence']['sha256'], hashlib.sha256(journal).hexdigest())
        self.assertNotIn(str(self.root), json.dumps(doc))

    def test_fixture_dry_run_and_incomplete_receipts_never_pass_a_live_gate(self):
        self.ran('--fixture')
        doc = self.produce()
        self.assertEqual((doc['gates']['smoke']['evidence_class'], doc['gates']['smoke']['status']),
                         ('fixture', 'pass'))
        self.refused('not_live', receipt.accept, 'smoke', doc, self.candidate, self.kit_path, self.state)
        self.refused('not_live', receipt.accept, 'send', doc, self.candidate, self.kit_path, self.state)

        self.state = self.root / 'never-run'
        doc = self.produce()
        self.assertEqual((doc['gates']['smoke']['evidence_class'], doc['gates']['smoke']['status'],
                          doc['gates']['smoke']['finished_at']), ('dry-run', 'incomplete', None))
        self.refused('not_live', receipt.accept, 'smoke', doc, self.candidate, self.kit_path, self.state)

        self.live()
        good = (self.root / 'replies.json').read_text()
        # An unknown send result, a wrong read and an event that ends the sitting.
        cases = {'uncertain': {'send': {'exit': 9, 'out': '{}'}},
                 'fail': {'swarms': {'exit': 0, 'out': '{"count":2}'}},
                 'incomplete': None}
        for status, change in cases.items():
            with self.subTest(status=status):
                (self.root / 'replies.json').write_text(good)
                kit = copy.deepcopy(self.kit)
                if change:
                    self.replies(**change)
                else:
                    self.kit['steps'].insert(5, {'id': 'pause', 'claim': 'json', 'kind': 'event'})
                    self.bind()
                self.state = self.root / ('partial-' + status)
                self.assertNotEqual(self.execute()[0], 0)
                doc = self.produce()
                self.assertEqual(doc['gates']['smoke']['status'], status)
                self.assertIsNone(doc['gates']['smoke']['finished_at'])
                self.refused('not_pass', receipt.accept, 'smoke', doc, self.candidate, self.kit_path, self.state)
                self.kit = kit
                self.bind()

    def test_stale_or_rebound_receipts_refuse(self):
        self.live()
        self.ran()
        doc = self.produce()
        receipt.accept('smoke', doc, self.candidate, self.kit_path, self.state, self.resolver(doc))
        changes = {
            'artifact': lambda c: c['candidate']['artifacts'][0].update(sha256='e' * 64),
            'source': lambda c: c['candidate']['source'].update(commit='3' * 40),
            'build': lambda c: c['candidate'].update(build_id='d' * 64),
            'product': lambda c: c['candidate']['products'][0].update(payload_sha256='c' * 64),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                other = copy.deepcopy(self.candidate)
                change(other)
                other['candidate_sha256'] = contract_sha(other['candidate'])
                self.refused('stale', receipt.accept, 'smoke', doc, other, self.kit_path, self.state)
        unsealed = copy.deepcopy(self.candidate)
        unsealed['candidate']['build_id'] = 'd' * 64
        self.refused('stale', receipt.accept, 'smoke', doc, unsealed, self.kit_path, self.state)
        forged = copy.deepcopy(doc)
        forged['inputs']['smoke']['coverage'] = []
        self.refused('inputs_mismatch', receipt.accept, 'smoke', forged, self.candidate, self.kit_path, self.state)
        forged = copy.deepcopy(doc)
        forged['gates']['smoke']['coverage'] = forged['gates']['smoke']['coverage'][:1]
        self.refused('coverage_mismatch', receipt.accept, 'smoke', forged, self.candidate, self.kit_path, self.state)
        forged = copy.deepcopy(doc)
        forged['gates']['smoke']['gaps'] = [GAP]
        self.refused('gaps_missing', receipt.accept, 'smoke', forged, self.candidate, self.kit_path, self.state)
        rekit = copy.deepcopy(self.candidate)
        rekit['candidate']['kit']['sha256'] = 'b' * 64
        rekit['candidate_sha256'] = contract_sha(rekit['candidate'])
        self.refused('stale', receipt.accept, 'smoke', doc, rekit, self.kit_path, self.state)

    def test_receipt_must_match_its_evidence_not_just_its_own_fields(self):
        self.ran('--fixture')
        forged = self.produce()
        for gate in ('smoke', 'send'):
            forged['gates'][gate]['evidence_class'] = forged['inputs'][gate]['evidence_class'] = 'live'
            forged['gates'][gate]['inputs_sha256'] = contract_sha(forged['inputs'][gate])
            self.refused('evidence_mismatch', receipt.accept, gate, forged, self.candidate,
                         self.kit_path, self.state)
        self.live()
        self.state = self.root / 'live-state'
        self.ran()
        doc = self.produce()
        receipt.accept('smoke', doc, self.candidate, self.kit_path, self.state, self.resolver(doc))
        state = smoke.load_state(self.state, self.kit)
        state['steps'][10]['state'] = 'incomplete'
        state['times']['finished'] = 0
        smoke.save(self.state, state)  # the evidence no longer shows a pass
        self.refused('evidence_mismatch', receipt.accept, 'smoke', doc, self.candidate,
                     self.kit_path, self.state)

    def test_kit_must_be_the_candidates_approved_kit_and_cover_every_promise(self):
        self.live()
        self.checkpoint()
        self.candidate['candidate']['kit']['sha256'] = 'b' * 64
        self.reseal()
        self.refused('kit_mismatch', self.produce)
        self.bind()
        self.candidate['candidate']['kit']['scope_sha256'] = 'b' * 64
        self.reseal()
        self.refused('scope_mismatch', self.produce)
        self.bind()
        for promises in (['synthetic_fleet'], ['synthetic_fleet', 'synthetic_send', 'synthetic_extra']):
            with self.subTest(promises=promises):
                self.candidate['candidate']['included_versions'][0]['promises'] = promises
                self.reseal()
                self.refused('coverage_mismatch', self.produce)
        self.candidate['candidate']['included_versions'][0]['promises'] = ['synthetic_fleet', 'synthetic_send']
        self.reseal()
        for product in self.candidate['candidate']['products']:
            if product['identity']['target'] == 'x86_64-unknown-linux-gnu' and product['identity']['product'] == 'cli':
                product['payload_sha256'] = 'c' * 64
        self.reseal()
        self.refused('product_mismatch', self.produce)

    # AC2: risk categories need matching bounded coverage; approval invents nothing.
    def test_risk_needs_matching_bounded_live_coverage(self):
        self.live()
        self.ran()
        self.candidate['candidate']['risk']['spending'] = {'required': 'unknown', 'reason': 'Synthetic unreadable diff.'}
        self.reseal()
        self.refused('risk_unknown', self.produce)
        self.candidate['candidate']['risk']['spending'] = {'required': 'yes', 'reason': 'Synthetic spending change.'}
        self.reseal()
        self.refused('risk_missing', self.produce)
        self.candidate['candidate']['risk']['spending'] = {'required': 'no', 'reason': 'Synthetic: none.'}
        self.reseal()
        self.state = self.root / 'bound-to-spending-no'
        self.ran()
        doc = self.produce()
        self.assertIsNone(doc['gates']['spending'])
        self.refused('missing', receipt.accept, 'spending', doc, self.candidate, self.kit_path, self.state)
        mismatched = {'send': ['new_once'], 'new': ['send_once'], 'app_permissions': ['send_once'],
                      'spending': ['app']}
        for category, steps in mismatched.items():
            with self.subTest(category=category):
                kit = copy.deepcopy(self.kit)
                self.kit['release']['risk'][category] = steps
                self.bind()
                self.checkpoint()
                self.refused('risk_mismatch', self.produce)
                self.kit = kit
                self.bind()
        self.kit['release']['risk']['send'] = []
        self.bind()
        self.checkpoint()
        self.refused('risk_missing', self.produce)

    def test_scope_bounds_writes_spending_and_grants(self):
        self.live()
        bad = {'unbounded spending': ('spending_cents', None),
               'negative spending': ('spending_cents', -1),
               'no targets': ('targets', []),
               'grant wildcard': ('app_permissions', ['*'])}
        for name, (field, value) in bad.items():
            with self.subTest(name=name):
                kit = copy.deepcopy(self.kit)
                self.kit['release']['scope'][field] = value
                self.bind()
                self.checkpoint()
                self.refused('invalid_scope', self.produce)
                self.kit = kit
        self.kit['release']['scope']['writes']['send'] = 0
        self.bind()
        self.checkpoint()
        self.refused('scope_exceeded', self.produce)
        self.kit['release']['scope']['writes'] = {'fleet': 1, 'new': 1}
        self.bind()
        self.checkpoint()
        self.refused('scope_exceeded', self.produce)

    # AC3: changed inputs refuse; nothing here retries or waits.
    def test_changed_kit_or_tested_bytes_refuse(self):
        self.live()
        self.checkpoint()
        self.kit['timeout_seconds'] = 6
        self.bind()
        self.refused('kit_changed', self.produce)
        self.kit['timeout_seconds'] = 5
        self.bind()
        self.kit['artifacts'][str(RUNNER)] = 'f' * 64
        self.kit_path.write_text(json.dumps(self.kit))
        self.refused('artifact_changed', self.produce)

    def test_command_line_prints_receipts_and_checks_one_gate(self):
        self.live()
        self.ran()
        candidate = self.root / 'candidate.json'
        candidate.write_text(json.dumps(self.candidate))
        made = subprocess.run([sys.executable, '-I', str(HERE / 'receipt.py'), 'produce',
                               '--kit', str(self.kit_path), '--state', str(self.state),
                               '--candidate', str(candidate), '--record', 'synthetic:smoke-run'],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        receipts = self.root / 'receipts.json'
        receipts.write_text(made.stdout)
        self.assertEqual(json.loads(made.stdout)['schema'], 'openwiz.live-smoke-receipts.v1')
        # The command line resolves only a real private-record pointer, never a synthetic one.
        for gate, code, verdict in (('smoke', 1, {'gate': 'smoke', 'accepted': False, 'reason': 'evidence_unresolved'}),
                                    ('spending', 1, {'gate': 'spending', 'accepted': False, 'reason': 'missing'})):
            checked = subprocess.run([sys.executable, '-I', str(HERE / 'receipt.py'), 'check',
                                      '--gate', gate, '--receipts', str(receipts),
                                      '--candidate', str(candidate), '--kit', str(self.kit_path),
                                      '--state', str(self.state)],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual((checked.returncode, json.loads(checked.stdout)), (code, verdict))
        bad = subprocess.run([sys.executable, '-I', str(HERE / 'receipt.py'), 'produce',
                              '--kit', str(self.kit_path), '--state', str(self.state),
                              '--candidate', str(candidate), '--record', str(self.root)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual((bad.returncode, json.loads(bad.stdout)),
                         (2, {'schema': 'openwiz.live-smoke-receipts.v1', 'refused': 'invalid_record'}))
        self.assertNotIn(str(self.root), bad.stdout + bad.stderr)

    # Review round 1 (R1-R5).
    def test_r1_a_run_is_bound_to_one_sealed_candidate(self):
        self.live()
        other = copy.deepcopy(self.candidate)
        other['candidate']['kit']['sha256'] = 'b' * 64
        other['candidate_sha256'] = contract_sha(other['candidate'])
        code, report = self.execute(candidate=other)
        self.assertEqual((code, report['reason']), (2, 'candidate_mismatch'))
        self.assertEqual(self.calls(), [])
        self.ran()
        for name, change in {'build': lambda c: c.update(build_id='d' * 64),
                             'source': lambda c: c['source'].update(commit='3' * 40),
                             'artifact': lambda c: c['artifacts'][0].update(sha256='e' * 64),
                             'untested product': lambda c: c['products'][0].update(payload_sha256='c' * 64)}.items():
            with self.subTest(change=name):
                changed = copy.deepcopy(self.candidate)
                change(changed['candidate'])
                changed['candidate_sha256'] = contract_sha(changed['candidate'])
                # Regenerating receipts for the changed candidate refuses: it was never run.
                self.refused('candidate_changed', receipt.produce, self.kit_path, self.state, changed,
                             'synthetic:smoke-run')
                before = len(self.calls())
                code, report = self.execute(candidate=changed)
                self.assertEqual((code, report['reason']), (2, 'candidate_changed'))
                self.assertEqual(len(self.calls()), before)
        self.state = self.root / 'unbound'
        subprocess.run([sys.executable, '-I', str(RUNNER), '--kit', str(self.kit_path), '--state',
                        str(self.state), '--execute', smoke.digest(self.kit)], capture_output=True, timeout=60)
        self.refused('unbound_run', self.produce)

    def test_r2_live_fleet_writes_are_only_the_canonical_tick_or_reviewed_probes(self):
        self.live()
        wrapper = self.root / 'wrapper'
        wrapper.write_text('#!/bin/sh\nexec %s fleet tick --json\n' % FAKE)
        wrapper.chmod(0o700)
        self.kit['artifacts'][str(wrapper)] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
        self.kit['steps'][0]['argv'] = [str(wrapper)]
        self.bind()
        code, report = self.execute()
        self.assertEqual((code, report['reason']), (2, 'invalid_kit'))
        self.assertEqual(self.calls(), [])

    def test_r3_tick_audit_covers_exactly_the_whole_action_array(self):
        self.live()
        for path in ('/actions/0/facts/blockers', '/actions/0', ''):
            with self.subTest(path=path):
                self.kit['steps'][0]['checks'] = [{'path': path, 'actions_in': SCOPE}]
                self.bind()
                code, report = self.execute()
                self.assertEqual((code, report['reason']), (2, 'invalid_kit'))
                self.assertEqual(self.calls(), [])

    def test_r4_a_checkpoint_alone_is_not_live_evidence(self):
        self.live()
        self.checkpoint()  # all-pass, but nothing ever ran
        self.refused('evidence_missing', self.produce)
        self.state = self.root / 'ran'
        self.ran()
        doc = self.produce()
        receipt.accept('smoke', doc, self.candidate, self.kit_path, self.state, self.resolver(doc))
        journal = self.state / 'journal.jsonl'
        lines = journal.read_bytes().splitlines(keepends=True)
        for name, edited in {'dropped': lines[:3] + lines[4:],
                             'rewritten': lines[:-2] + [lines[-2].replace(b'"pass"', b'"fail"'), lines[-1]],
                             'truncated': lines[:-1]}.items():
            with self.subTest(edit=name):
                journal.write_bytes(b''.join(edited))
                self.refused('evidence_mismatch', self.produce)
        journal.write_bytes(b''.join(lines))
        self.produce()

    def test_r5_write_scope_bounds_consumed_attempts_before_dispatch(self):
        self.live()
        self.kit['steps'][1:1] = [
            {'id': 'tick_event', 'claim': 'fleet', 'kind': 'event'},
            {'id': 'done', 'claim': 'fleet', 'kind': 'await', 'argv': [str(FAKE), 'done'], 'exit': 0,
             'checks': [{'path': '/count', 'equals': 1}], 'until': [{'path': '/merged', 'equals': 2}],
             'again_from': 'fleet_tick'}]
        self.bind()
        self.replies(done={'exit': 0, 'out': '{"count":1,"merged":0}'})
        ticks = lambda: sum('--expect-plan' in c for c in self.calls())
        self.assertEqual(self.execute()[1]['reason'], 'next_event')
        self.assertEqual(self.execute()[1]['reason'], 'pending')
        self.assertEqual(self.execute()[1]['reason'], 'write_limit')  # before a second effect
        self.assertEqual(ticks(), 1)
        self.assertEqual(self.execute()[1]['reason'], 'write_limit')
        self.assertEqual(ticks(), 1)
        self.kit['release']['scope']['writes']['fleet'] = 2
        self.bind()
        self.state = self.root / 'two-ticks'
        self.replies(done={'exit': 0, 'out': '{"count":1,"merged":0}'})
        self.assertEqual(self.execute()[1]['reason'], 'next_event')
        self.assertEqual(self.execute()[1]['reason'], 'pending')
        self.assertEqual(self.execute()[1]['reason'], 'next_event')
        self.replies(done={'exit': 0, 'out': '{"count":1,"merged":2}'})
        self.ran()
        doc = self.produce()
        self.assertEqual(doc['inputs']['smoke']['writes_consumed'], {'fleet': 2, 'new': 1, 'send': 1})
        receipt.accept('smoke', doc, self.candidate, self.kit_path, self.state, self.resolver(doc))

    # Review round 2 (R2, R4, R6).
    def test_r2_round2_a_probe_shaped_wrapper_is_not_a_reviewed_probe(self):
        self.live()
        wrapper = self.root / 'wrapper'
        wrapper.write_text('#!/bin/sh\nexec %s fleet tick --json\n' % FAKE)
        wrapper.chmod(0o700)
        python = str(Path(sys.executable).resolve())
        probes = (str(HERE / 'browser.mjs'), str(HERE / 'cleanup.py'))
        pins = {str(wrapper): hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                python: hashlib.sha256(Path(python).read_bytes()).hexdigest()}
        for probe in probes:
            pins[probe] = hashlib.sha256(Path(probe).read_bytes()).hexdigest()
        cleanup = ['-I', probes[1], '--gh', python, '--repo', 'synthetic-owner/synthetic-repo',
                   '--ticket', '9004', '--action', 'close']
        cases = {'browser-shaped wrapper': [str(wrapper), probes[0], 'phone-reply'],
                 'cleanup-shaped wrapper': [str(wrapper)] + cleanup,
                 'cleanup with a wrapper gh': [python] + cleanup[:3] + [str(wrapper)] + cleanup[4:],
                 'cleanup with extra arguments': [python] + cleanup + ['--extra']}
        for name, argv in cases.items():
            with self.subTest(case=name):
                self.state = self.root / ('probe-' + name.replace(' ', '-'))
                self.kit['artifacts'].update(pins)
                self.kit['steps'][0].update(argv=argv, checks=[{'path': '/count', 'equals': 1}])
                self.bind()
                code, report = self.execute()
                self.assertEqual((code, report['reason']), (2, 'invalid_kit'))
                self.assertEqual(self.calls(), [])
        # The whole reviewed invocation under the runner's own interpreter is accepted.
        self.kit['steps'][0].update(argv=[python] + cleanup)
        self.bind()
        code, report = self.execute('--dry-run')
        self.assertEqual((code, report['verdict']), (0, 'not_run'), report)

    def forge(self, exit_code=None, observed=True):
        """A complete journal for the all-pass checkpoint, written by hand."""
        self.checkpoint()
        smoke.journal(self.state, dict(kind='start', kit=smoke.digest(self.kit),
                                       candidate=self.candidate['candidate_sha256'], mode='live',
                                       source=self.kit['source']['head'], runner=smoke.file_hash(RUNNER),
                                       restriction=smoke.file_hash(smoke.RESTRICTION)))
        for step in self.kit['steps']:
            if step['kind'] == 'write':
                smoke.journal(self.state, dict(kind='attempt', id=step['id'], claim=step['claim'],
                                               sittings=0, fleet_started=0))
            event = dict(kind='step', id=step['id'], state='pass', facts={}, reason='none', pending=False,
                         exit=step['exit'] if exit_code is None else exit_code, output_sha256='a' * 64)
            if observed:
                event['observed'] = [{'actions': [dict(ACTION, outcome={'state': 'done'})]}
                                     if 'actions_in' in c else {'digest': smoke.digest(c['equals'])}
                                     for c in step['checks']]
            smoke.journal(self.state, event)
        smoke.journal(self.state, {'kind': 'finish'})
        try:  # a consistent forgery also rewrites the checkpoint to match
            smoke.save(self.state, smoke.replay(self.kit, smoke.read_journal(self.state)[1]))
        except smoke.Refusal:
            pass

    def test_r4_round2_a_reconstructed_journal_needs_its_observations_and_a_preserved_record(self):
        self.live()
        self.forge(exit_code=9)  # every recorded exit is wrong for its step
        self.refused('evidence_mismatch', self.produce)
        self.state = self.root / 'no-observations'
        self.refused('evidence_mismatch', lambda: (self.forge(observed=False), self.produce()))
        # Even a consistent hand-made journal passes only with its preserved record.
        self.state = self.root / 'consistent'
        self.forge()
        doc = self.produce('synthetic:never-existed')
        self.refused('evidence_unresolved', receipt.accept, 'smoke', doc, self.candidate, self.kit_path, self.state)
        for name, resolver in {'other digest': self.resolver(doc, line=doc['preserve'].replace('journal=', 'journal=0')),
                               'record predates the run': self.resolver(doc, created_at=doc['gates']['smoke']['finished_at'] - 1)}.items():
            with self.subTest(record=name):
                self.refused('evidence_unresolved', receipt.accept, 'smoke', doc, self.candidate,
                             self.kit_path, self.state, resolver)

    def test_r6_an_interrupted_transition_is_adopted_never_repeated(self):
        self.live()
        self.kit['release']['scope']['writes']['fleet'] = 2
        self.kit['steps'][1:1] = [
            {'id': 'tick_event', 'claim': 'fleet', 'kind': 'event'},
            {'id': 'done', 'claim': 'fleet', 'kind': 'await', 'argv': [str(FAKE), 'done'], 'exit': 0,
             'checks': [{'path': '/count', 'equals': 1}], 'until': [{'path': '/merged', 'equals': 2}],
             'again_from': 'fleet_tick'}]
        self.bind()
        self.replies(done={'exit': 0, 'out': '{"count":1,"merged":0}'})
        self.assertEqual(self.execute()[1]['reason'], 'next_event')
        self.assertEqual(self.execute()[1]['reason'], 'pending')
        # The next sitting's readback decided to repeat and journaled it, then stopped
        # before saving the checkpoint. Meanwhile the condition completed.
        smoke.journal(self.state, {'kind': 'repeat', 'id': 'done', 'again_from': 'fleet_tick',
                                   'exit': 0, 'output_sha256': 'a' * 64})
        self.replies(done={'exit': 0, 'out': '{"count":1,"merged":2}'})
        self.assertEqual(self.execute()[1]['reason'], 'next_event')  # the recorded repeat: one more tick
        self.ran()
        self.assertEqual(sum('--expect-plan' in c for c in self.calls()), 2)
        doc = self.produce()
        self.assertEqual(doc['inputs']['smoke']['writes_consumed'], {'fleet': 2, 'new': 1, 'send': 1})
        receipt.accept('smoke', doc, self.candidate, self.kit_path, self.state, self.resolver(doc))
        # Two unapplied events are not an interruption: refused, nothing runs.
        smoke.journal(self.state, {'kind': 'finish'})
        smoke.journal(self.state, {'kind': 'finish'})
        before = len(self.calls())
        self.assertEqual(self.execute()[1]['reason'], 'invalid_state')
        self.assertEqual(len(self.calls()), before)


if __name__ == '__main__':
    unittest.main()
