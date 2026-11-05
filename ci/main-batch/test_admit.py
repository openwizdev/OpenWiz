#!/usr/bin/env python3
"""C12 switch-gate proofs. All archives, identities and runs are synthetic.

Claim CS3: main per-push full work is replaced only after the whole C11 chain
verifies at this candidate, no overload pause applies and a supported admission
mechanism exists. Anything unproven, stale, changed or unknown keeps per-push
full work. The archive is built here from C6's synthetic superseded-pending
fixtures; the private C11 bytes never reach CI.
"""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / 'fixtures/contract'
REPOSITORY = 'synthetic/ci-example'
NIGHTLY_HEAD = '9' * 40
NIGHTLY_RUN = 9000300


def load_admit():
    spec = importlib.util.spec_from_file_location('admit', HERE / 'admit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_blob(data):
    # Git's own blob identity, computed independently of the code under test.
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def zipped(name, text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def nightly_plan(document):
    plan = json.loads(document['plan'])
    plan['run'].update(id=NIGHTLY_RUN, attempt=1, event='schedule', base=None, head=NIGHTLY_HEAD)
    plan['selection']['reasons'] = [{'code': 'nightly'}]
    return json.dumps(plan, indent=2)


def lane_receipts(plan_text):
    """Expected nightly receipts, written from C6's documented receipt list."""
    plan = json.loads(plan_text)
    lanes, digest = plan['lanes'], hashlib.sha256(plan_text.encode()).hexdigest()
    wanted = {'always': lanes['always']['tests'], 'web': lanes['web']['tests'],
              'build:web_export': [], 'prerequisite:toolkit': []}
    for kind in ('site', 'release'):
        tests = [t for t in lanes['site']['tests'] if t.startswith(kind + ':')]
        if tests:
            wanted[kind] = tests
    wanted.update({'skill:' + s['skill']: s['tests'] for s in lanes['skills']})
    return {lane: dict(lane=lane, tests=tests, plan_sha256=digest, run=plan['run'])
            for lane, tests in wanted.items()}


class Archive:
    """A synthetic C11-shaped private archive with its manifest and pin."""

    def __init__(self, root):
        self.root = Path(root)
        self.document = json.loads((FIXTURES / 'superseded-pending.json').read_text())
        self.context = json.loads((FIXTURES / 'superseded-pending-expected.json').read_text())
        batch = self.context['batch']
        self.files = {}
        obs = 'observation/'
        self.put(obs + 'context.json', json.dumps(self.context))
        self.put(obs + 'inventory.json', json.dumps(self.context['inventory']))
        self.put(obs + 'state.json', json.dumps(dict(
            repository=REPOSITORY, covered=batch['head'], pending=[], last=self.document)))
        self.put(obs + 'reconcile-report.json', json.dumps(dict(
            complete=True, switch_authorized=False, outcome='success', refusals=[],
            measurement=None, batch=batch, execution=self.context['execution'])))
        self.put(obs + 'reconcile-rc', 'rc=0\n')
        plan = nightly_plan(self.document)
        lanes = json.loads(plan)['lanes']
        self.nightly_inventory = [t for k in ('always', 'rust', 'web', 'site')
                                  for t in lanes[k]['tests']] + [t for s in lanes['skills'] for t in s['tests']]
        self.put(obs + 'nightly-inventory.json', json.dumps(self.nightly_inventory))
        self.put(obs + 'nightly-zips/ci-selection-1.zip', zipped('ci-selection.json', plan))
        for lane, receipt in lane_receipts(plan).items():
            name = lane.replace(':', '-')
            self.put(obs + f'nightly-zips/lane-{name}-1.zip', zipped(name + '.json', json.dumps(receipt)))
        self.put(obs + 'nightly-zips/rust-ran-1-1.zip',
                 zipped('ran-1.txt', '\n'.join(lanes['rust']['tests']) + '\n'))
        self.put(obs + 'raw/14-runN.json', json.dumps(dict(
            id=NIGHTLY_RUN, run_attempt=1, event='schedule', head_sha=NIGHTLY_HEAD, head_branch='main',
            path='.github/workflows/ci.yml', status='completed', conclusion='success')))
        self.put(obs + 'raw/15-jobsN.json', json.dumps(dict(total_count=3, jobs=[
            dict(name='changes', status='completed', conclusion='success'),
            dict(name='rust', status='completed', conclusion='skipped'),
            dict(name='ci', status='completed', conclusion='success')])))
        self.put('README.md', 'synthetic archive\n')
        self.blobs_root = self.root / 'tree'
        self.blobs = {}
        for path in ('ci/main-batch/shadow.py', 'contracts/ci-main-batch.v1.md'):
            target = self.blobs_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = (ROOT / path).read_bytes()
            target.write_bytes(data)
            self.blobs[path] = git_blob(data)
        self.seal()

    def put(self, path, data):
        data = data.encode() if isinstance(data, str) else data
        target = self.root / 'archive' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.files[path] = data

    def seal(self):
        lines = ''.join(f'{hashlib.sha256(data).hexdigest()}  ./{path}\n'
                        for path, data in sorted(self.files.items()))
        (self.root / 'archive/MANIFEST.sha256').write_text(lines)
        batch = self.context['batch']
        self.pin = dict(
            repository=REPOSITORY,
            manifest_sha256=hashlib.sha256(lines.encode()).hexdigest(),
            base=batch['base'], head=batch['head'],
            pull_requests=[m['pull_request'] for m in batch['members']],
            run=dict(id=self.context['execution']['id'], attempt=self.context['execution']['attempt']),
            nightly=dict(id=NIGHTLY_RUN, attempt=1, head=NIGHTLY_HEAD),
            blobs=dict(self.blobs))

    def edit(self, path, change):
        value = json.loads(self.files[path])
        change(value)
        self.put(path, json.dumps(value))
        self.seal()

    @property
    def path(self):
        return self.root / 'archive'


class Gate(unittest.TestCase):
    def setUp(self):
        self.admit = load_admit()
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Archive(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def chain(self, pin=None):
        return self.admit.chain_refusals(self.archive.path, self.archive.pin if pin is None else pin,
                                         self.archive.blobs_root)

    def refuses(self, clue):
        refusals = self.chain()
        self.assertTrue(refusals, clue)
        return refusals

    # The complete synthetic chain verifies; the gate itself still stays shut.
    def test_complete_chain_verifies_but_no_mechanism_keeps_per_push_full(self):
        self.assertEqual(self.chain(), [])
        decision = self.admit.decide([], dict(allowed=True, paused=False))
        self.assertEqual(decision['admission'], 'per-push-full')
        self.assertEqual(len(decision['refusals']), 1)
        self.assertIn('no supported admission mechanism', decision['refusals'][0])

    def test_only_a_named_supported_mechanism_could_admit_a_batch(self):
        # AC5: code cannot infer authority. An unnamed or invented mechanism refuses.
        for mechanism in (None, 'merge_queue', 'push_coalescing', 'controller'):
            decision = self.admit.decide([], dict(allowed=True, paused=False), mechanism)
            self.assertEqual(decision['admission'], 'per-push-full', mechanism)
        self.assertEqual(self.admit.SUPPORTED_MECHANISMS, ())

    # Archive integrity: the pin binds the reviewed bytes.
    def test_manifest_digest_must_equal_the_reviewed_pin(self):
        pin = dict(self.archive.pin, manifest_sha256='0' * 64)
        self.assertTrue(self.chain(pin))

    def test_edited_missing_or_unlisted_archive_file_refuses(self):
        (self.archive.path / 'observation/state.json').write_text('{}')
        self.refuses('edited file under an unchanged manifest')
        self.archive.put('observation/state.json', self.archive.files['observation/state.json'])
        (self.archive.path / 'observation/context.json').unlink()
        self.refuses('missing file')
        self.archive.put('observation/context.json', self.archive.files['observation/context.json'])
        (self.archive.path / 'observation/extra.json').write_text('{}')
        self.refuses('unlisted file')

    def test_manifest_path_escape_and_symlink_refuse(self):
        manifest = self.archive.path / 'MANIFEST.sha256'
        escaped = manifest.read_text() + f'{"0" * 64}  ./../outside\n'
        manifest.write_text(escaped)
        pin = dict(self.archive.pin, manifest_sha256=hashlib.sha256(escaped.encode()).hexdigest())
        self.assertTrue(self.chain(pin), 'path escape')
        self.archive.seal()
        target = self.archive.path / 'README.md'
        target.unlink()
        outside = self.archive.root / 'outside-readme'
        outside.write_text('synthetic archive\n')
        os.symlink(outside, target)
        self.refuses('symlinked archive file')

    # The combined batch: complete, current, every member and required check.
    def test_failed_cancelled_or_missing_combined_result_refuses(self):
        def outcome(result):
            return lambda state: state['last']['outcomes'][1].update(result=result)
        for result in ('failure', 'cancelled', 'skipped'):
            with self.subTest(result=result):
                self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
                self.archive.edit('observation/state.json', outcome(result))
                self.refuses(result)
        self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
        self.archive.edit('observation/state.json', lambda s: s['last']['receipts'].pop())
        self.refuses('missing receipt')

    def test_incomplete_or_refused_reconcile_report_refuses(self):
        for change in (lambda r: r.update(complete=False), lambda r: r.update(outcome='incomplete'),
                       lambda r: r['refusals'].append('GitHub read failed')):
            with self.subTest(change=change):
                self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
                self.archive.edit('observation/reconcile-report.json', change)
                self.refuses('incomplete reconcile')
        self.archive.put('observation/reconcile-rc', 'rc=1\n')
        self.archive.seal()
        self.refuses('nonzero reconcile exit')

    def test_pending_members_are_never_dropped_because_newer_work_arrived(self):
        member = self.archive.context['batch']['members'][0]
        self.archive.edit('observation/state.json', lambda s: s['pending'].append(member))
        self.refuses('pending member left uncovered')
        self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
        self.archive.edit('observation/state.json',
                          lambda s: s.update(covered=member['merge']))
        self.refuses('checkpoint not at the combined head')

    def test_batch_identity_must_match_the_reviewed_pin(self):
        for key, value in (('head', 'a' * 40), ('base', 'b' * 40), ('pull_requests', [1]),
                           ('run', dict(id=1, attempt=1)), ('repository', 'synthetic/other')):
            with self.subTest(key=key):
                self.assertTrue(self.chain(dict(self.archive.pin, **{key: value})), key)

    def test_stale_attempt_or_shortened_batch_in_context_refuses(self):
        # A consistent report/context for another attempt than the pinned one.
        for path in ('observation/context.json', 'observation/reconcile-report.json'):
            self.archive.edit(path, lambda c: c['execution'].update(attempt=2))
        self.assertIn('batch: execution differs from the reviewed pin', self.refuses('stale attempt'))
        self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))

        def shorten(state):
            state['last']['batch']['members'] = state['last']['batch']['members'][1:]
            state['last']['batch']['base'] = state['last']['batch']['members'][0]['parent']
        self.archive.edit('observation/state.json', shorten)
        self.refuses('shortened past the checkpoint')

    def test_planted_missed_work_against_the_inventory_refuses(self):
        # The independent inventory and context agree; only the plan omits it.
        self.archive.edit('observation/inventory.json', lambda i: i.append('rust:test:planted'))
        self.archive.edit('observation/context.json', lambda c: c['inventory'].append('rust:test:planted'))
        self.assertEqual(self.refuses('plan omits an inventory test'), [
            'batch: coverage: full plan omits or adds work against the independent candidate inventory'])

    # The retained nightly: its own full schedule plan, receipts and results.
    def test_nightly_must_be_full_schedule_work_with_every_receipt(self):
        nz = 'observation/nightly-zips/'
        (self.archive.path / nz / 'lane-web-1.zip').unlink()
        del self.archive.files[nz + 'lane-web-1.zip']
        self.archive.seal()
        self.refuses('missing nightly web receipt')

    def test_nightly_rust_share_must_hold_every_rust_test_once(self):
        nz = 'observation/nightly-zips/rust-ran-1-1.zip'
        plan = json.loads(nightly_plan(self.archive.document))
        tests = plan['lanes']['rust']['tests']
        self.archive.put(nz, zipped('ran-1.txt', '\n'.join(tests[1:]) + '\n'))
        self.archive.seal()
        self.refuses('rust share omits a test')
        self.archive.put(nz, zipped('ran-1.txt', '\n'.join(tests + tests[:1]) + '\n'))
        self.archive.seal()
        self.refuses('rust share duplicates a test')

    def test_nightly_failed_job_or_push_plan_refuses(self):
        self.archive.edit('observation/raw/15-jobsN.json',
                          lambda j: j['jobs'][2].update(conclusion='cancelled'))
        self.refuses('cancelled nightly job')
        self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
        self.archive.edit('observation/raw/15-jobsN.json', lambda j: j.update(total_count=4))
        self.refuses('truncated nightly job page')
        self.archive = Archive(tempfile.mkdtemp(dir=self.temp.name))
        self.archive.edit('observation/raw/14-runN.json', lambda r: r.update(event='push'))
        self.refuses('nightly inferred from a push')
        self.assertTrue(self.chain(dict(self.archive.pin, nightly=dict(
            id=NIGHTLY_RUN, attempt=1, head=self.archive.context['batch']['head']))),
            'nightly bound to the batch head')

    # Candidate binding: changed implementation restores per-push full work.
    def test_changed_implementation_since_the_proof_refuses(self):
        target = self.archive.blobs_root / 'ci/main-batch/shadow.py'
        target.write_bytes(target.read_bytes() + b'\n# changed\n')
        refusals = self.refuses('implementation changed since the proof')
        self.assertTrue(any('ci/main-batch/shadow.py' in r for r in refusals), refusals)
        target.unlink()
        self.refuses('implementation missing')

    # The C3 pause stops new batches; essential work is not this gate's concern.
    def test_overload_pause_or_unknown_refuses_a_new_batch(self):
        for overload in (dict(allowed=False, paused=True), dict(allowed=True, paused=True), None, {}):
            decision = self.admit.decide([], overload, 'anything')
            self.assertEqual(decision['admission'], 'per-push-full', overload)
            self.assertTrue(any('overload' in r for r in decision['refusals']), decision)

    # Restart and rollback: the decision is recomputed from inputs each time.
    def test_repeat_is_idempotent_and_a_later_change_rolls_back(self):
        self.assertEqual(self.chain(), self.chain())
        self.assertEqual(self.chain(), [])
        self.archive.edit('observation/state.json', lambda s: s['last']['checks'][0].update(result='failure'))
        self.assertTrue(self.chain(), 'a once-verified chain whose evidence changes refuses again')


class Command(unittest.TestCase):
    """The program as the orchestrator runs it: fail closed, never admit today."""

    def run_admit(self, *args):
        return subprocess.run([sys.executable, '-I', str(HERE / 'admit.py'), *args],
                              capture_output=True, text=True, timeout=60)

    def test_production_archive_absent_keeps_per_push_full(self):
        with tempfile.TemporaryDirectory() as temp:
            observation = Path(temp) / 'overload.json'
            shutil.copy(ROOT / 'tools/ci-overload/fixtures/healthy.json', observation)
            result = self.run_admit('--repository', 'synthetic-owner/synthetic-repo',
                                    '--archive', str(Path(temp) / 'none'), '--now', '1800000000',
                                    '--overload-input', str(observation),
                                    '--overload-state', str(Path(temp) / 'state/pause.json'))
        self.assertEqual(result.returncode, 1, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision['admission'], 'per-push-full')
        self.assertTrue(decision['refusals'])

    def test_invalid_invocation_is_exit_2(self):
        self.assertEqual(self.run_admit('--repository', 'not a repo').returncode, 2)


if __name__ == '__main__':
    unittest.main()
