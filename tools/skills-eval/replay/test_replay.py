#!/usr/bin/env python3
"""P7 offline fixture proofs. Every Git object and review is synthetic.

Owning claims/bugs are recorded in the harness proof plan. The public prepare,
scoped-tool, checkpoint, blind-adjudication and scoring seams own these contracts;
EB5's validator tests did not exercise source resolution or durable dispatch.
"""
import copy
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('replay_run', HERE / 'run.py')
S = load('replay_score', HERE / 'score.py')
C = R.C
FACTORY = HERE.parents[1] / 'factory-metrics'


def literal(name):
    return C.read(HERE / 'contract-fixtures' / name)


def base_inputs():
    doc = C.read(FACTORY / 'fixtures/bottlenecks-contract/accepted.json')
    doc['replay'] = literal('paired.json')
    doc['preregistration'] = None
    doc['stages']['research'] = {'status': 'pass', 'artifact_hash': 'f' * 64,
                               'source': 's1', 'at': '2030-01-03T09:00:00Z'}
    journey = C.read(FACTORY / 'fixtures/journey/journeys.json')
    return doc, journey


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'synthetic@example.invalid')
        (self.repo / 'file.txt').write_text('original\n')
        (self.repo / 'review.md').write_text('synthetic old skill\n')
        self.base = self.commit()
        (self.repo / 'file.txt').write_text('first review\n')
        (self.repo / 'review.md').write_text('synthetic candidate skill\n')
        self.head = self.commit()
        # Later checkout content must never be read by the reviewer.
        (self.repo / 'file.txt').write_text('later fix and answer key\n')
        self.source = R.GitSource(self.repo)
        self.doc, self.journey = base_inputs()
        r = self.doc['replay']
        r.update(started_at=None, completed_at=None, selection='pending')
        r['avoided_rounds']['value'] = None
        row = r['cohort'][0]
        row.update(base=self.base, head=self.head)
        diff = self.source.diff(self.base, self.head)
        material = {'kind': 'original-diff', 'at': '2030-01-01T15:00:00Z',
                    'hash': R.sha(diff)}
        row['context']['materials'] = [material]
        self.keyfile = self.root / 'sealed-key.json'
        self.keyfile.write_text(json.dumps([
            {'id': 'F1', 'severity': 'high', 'root_cause': 'synthetic guard', 'location': 'file.txt:1'},
            {'id': 'F2', 'severity': 'medium', 'root_cause': 'synthetic error', 'location': 'file.txt:2'},
        ]))
        row['context']['sealed_key_hash'] = R.sha(self.keyfile.read_bytes())
        self.selectors = {material['hash']: {'kind': 'original-diff', 'path': None, 'revision': None}}
        row['context_hash'] = R.context_digest(row)
        e = self.doc['experiment']
        for arm, commit in [('old', self.base), ('candidate', self.head)]:
            revision = {'commit': commit, 'tree': self.source.tree(commit)}
            e['arms'][arm]['revision'] = revision
            e['arms'][arm]['cf4']['revision'] = copy.deepcopy(revision)
            e['arms'][arm]['review_hash'] = R.sha(self.source.read(commit, 'review.md'))
            row['arms'][arm].update(status='not_run', report_hash=None, reported_at=None,
                finished_at=None, adjudications=[], context_hash=row['context_hash'],
                skill_hash=e['arms'][arm]['review_hash'])
        self.doc['experiment_hash'] = C.digest(e)
        self.state = self.root / 'state'

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True).stdout.decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic snapshot')
        return self.git('rev-parse', 'HEAD')

    def prepare(self):
        return R.prepare(self.doc, self.journey, self.source, self.selectors,
                         {'old': 'review.md', 'candidate': 'review.md'})

    def refreeze(self, base, head, extra=()):
        row = self.doc['replay']['cohort'][0]
        row.update(base=base, head=head)
        digest = R.sha(self.source.diff(base, head))
        row['context']['materials'] = [
            {'kind': 'original-diff', 'at': row['first_review_at'], 'hash': digest}]
        self.selectors = {digest: {'kind': 'original-diff', 'path': None, 'revision': None}}
        for kind, path, data in extra:
            h = R.sha(data)
            row['context']['materials'].append({'kind': kind, 'at': row['first_review_at'], 'hash': h})
            self.selectors[h] = {'kind': kind, 'path': path, 'revision': head}
        row['context_hash'] = R.context_digest(row)
        for arm in row['arms'].values(): arm['context_hash'] = row['context_hash']

    def contextual_files(self):
        (self.repo / 'support').mkdir(); (self.repo / 'pkg').mkdir()
        (self.repo / 'support/helper.py').write_text('SYNTHETIC_VALUE = 7\n')
        (self.repo / 'pkg/AGENTS.md').write_text('Synthetic instructions scoped to pkg.\n')
        (self.repo / 'file.txt').write_text('original\n')
        base = self.commit()
        (self.repo / 'file.txt').write_text('first review\n')
        head = self.commit()
        self.refreeze(base, head, [
            ('original-file', 'support/helper.py', b'SYNTHETIC_VALUE = 7\n'),
            ('original-instructions', 'pkg/AGENTS.md', b'Synthetic instructions scoped to pkg.\n')])
        return head

    def create(self):
        R.Store.create(self.state, self.prepare())
        return R.Store(self.state)

    def reserve(self, store, limit=2):
        return store.reserve(self.doc, self.journey, limit, '2030-01-04T00:01:00Z')

    def finish(self, store, job, status='complete', report='synthetic finding'):
        return store.receive(job['run_key'], status, report if status == 'complete' else None,
                             '2030-01-04T00:10:00Z')


class Isolation(RepoFixture):
    def test_scoped_tools_and_fresh_bundles(self):
        prepared = self.prepare()
        old, new = prepared['bundles'].values()
        self.assertNotEqual(old['context_key'], new['context_key'])
        self.assertEqual(old['materials'], new['materials'])
        self.assertEqual(old['skill'], 'synthetic old skill\n')
        self.assertEqual(new['skill'], 'synthetic candidate skill\n')
        self.assertNotIn('known', old)
        self.assertNotIn('rubric', old)
        listing = R.tool(old, {'op': 'list'})
        self.assertEqual(len(listing['materials']), 1)
        self.assertEqual(listing['skill'], 'skill')
        names = [m['hash'] for m in listing['materials']]
        self.assertEqual(R.tool(old, {'op': 'read', 'name': 'skill'}), old['skill'])
        self.assertIn('first review', R.tool(old, {'op': 'read', 'name': names[0]})['text'])
        self.assertNotIn('later fix', json.dumps(old))
        for request in [
            {'op': 'read', 'name': '../file.txt'}, {'op': 'read', 'name': '/etc/passwd'},
            {'op': 'read', 'name': 'known'}, {'op': 'read', 'name': new['context_key']},
            {'op': 'shell', 'command': 'git log'}, {'op': 'write', 'name': 'skill'},
            {'op': 'read', 'name': 'skill', 'extra': 1}, ['list'], {'op': {'read': None}},
        ]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                R.tool(old, request)

    def test_git_refuses_missing_moving_or_wrong_object(self):
        blob = self.git('hash-object', 'file.txt')
        for commit in ['main', 'HEAD', '0' * 40, blob, '--help']:
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                self.source.tree(commit)
        for path in ['../file.txt', '/file.txt', 'a/../file.txt', '.git/config', 'file.txt/']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.source.read(self.head, path)
        (self.repo / 'link').symlink_to('/etc/passwd')
        linked = self.commit()
        with self.assertRaises(ValueError):
            self.source.read(linked, 'link')

    def test_frozen_context_refusals(self):
        mutations = [
            lambda row: row.update(head='0' * 40),
            lambda row: row['context']['materials'][0].update(at='2030-01-02T00:00:00Z'),
            lambda row: row['context']['materials'][0].update(kind='later-verdict'),
            lambda row: row['context']['materials'][0].update(hash='f' * 64),
            lambda row: row['context'].update(sealed_key_hash=row['context']['materials'][0]['hash']),
            lambda row: row['context'].update(isolation='unavailable'),
            lambda row: row['arms']['candidate'].update(context_key=row['arms']['old']['context_key']),
            lambda row: row.update(context_hash='f' * 64),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.doc)
                mutation(self.doc['replay']['cohort'][0])
                with self.assertRaises(ValueError):
                    self.prepare()
                self.doc = original
        self.doc['experiment']['arms']['old']['review_hash'] = 'f' * 64
        with self.assertRaises(ValueError):
            self.prepare()

    def test_later_material_refuses_even_with_rehashed_context(self):
        row = self.doc['replay']['cohort'][0]
        row['context']['materials'][0]['at'] = '2030-01-02T00:00:00Z'
        row['context_hash'] = R.context_digest(row)
        for arm in row['arms'].values(): arm['context_hash'] = row['context_hash']
        with self.assertRaisesRegex(ValueError, 'later material'):
            self.prepare()

    def test_skill_cannot_be_the_sealed_key(self):
        row = self.doc['replay']['cohort'][0]
        row['context']['sealed_key_hash'] = self.doc['experiment']['arms']['old']['review_hash']
        with self.assertRaisesRegex(ValueError, 'sealed'):
            self.prepare()

    def test_unknown_selector_refuses(self):
        self.selectors['f' * 64] = {'kind': 'original-file', 'path': 'file.txt', 'revision': self.head}
        with self.assertRaisesRegex(ValueError, 'selector'):
            self.prepare()

    def test_r1_prepared_diff_ignores_local_driver_and_includes(self):
        (self.repo / '.gitattributes').write_text('file.txt diff=mutable\n')
        (self.repo / 'file.txt').write_text('original\n')
        base = self.commit()
        (self.repo / 'file.txt').write_text('first review\n')
        head = self.commit()
        self.refreeze(base, head)
        for configured_by in ('local', 'include'):
            with self.subTest(configured_by=configured_by):
                if configured_by == 'local':
                    self.git('config', 'diff.mutable.binary', 'true')
                else:
                    self.git('config', '--remove-section', 'diff.mutable')
                    included = self.root / 'included-config'
                    included.write_text('[diff "mutable"]\n    binary = true\n')
                    self.git('config', 'include.path', str(included))
                # A new resolver must be as independent of source config as an
                # already constructed one. Both must produce readable material.
                for source in (self.source, R.GitSource(self.repo)):
                    diff = source.diff(base, head)
                    self.assertIn(b'+first review\n', diff)
                    self.assertNotIn(b'GIT binary patch', diff)
                    prepared = R.prepare(self.doc, self.journey, source, self.selectors,
                                         {'old': 'review.md', 'candidate': 'review.md'})
                    for bundle in prepared['bundles'].values():
                        self.assertIn('+first review\n', next(iter(bundle['materials'].values())))

    def test_r1_worktree_and_bare_sources_ignore_even_malformed_config(self):
        worktree = self.root / 'worktree'
        self.git('worktree', 'add', '--detach', str(worktree), self.head)
        bare = self.root / 'bare'
        shutil.copytree(self.repo / '.git', bare)
        # Object resolution must not even parse source-local configuration.
        (self.repo / '.git/config').write_text('malformed synthetic configuration\n')
        (bare / 'config').write_text('malformed synthetic configuration\n')
        for repo in (self.repo, worktree, bare):
            with self.subTest(source=repo.name):
                source = R.GitSource(repo)
                self.assertEqual(source.read(self.head, 'file.txt'), b'first review\n')
                self.assertIn(b'+first review\n', source.diff(self.base, self.head))

    def test_r2_unchanged_file_and_nested_instructions_keep_identity(self):
        head = self.contextual_files()
        prepared = self.prepare()
        for bundle in prepared['bundles'].values():
            listing = R.tool(bundle, {'op': 'list'})
            self.assertIsInstance(listing, dict, 'listing must expose material identities')
            descriptors = {entry['path']: entry for entry in listing['materials']}
            expected = [
                {'hash': R.sha(b'SYNTHETIC_VALUE = 7\n'), 'kind': 'original-file',
                 'path': 'support/helper.py', 'revision': head},
                {'hash': R.sha(b'Synthetic instructions scoped to pkg.\n'), 'kind': 'original-instructions',
                 'path': 'pkg/AGENTS.md', 'revision': head},
            ]
            for descriptor in expected:
                self.assertEqual(descriptors[descriptor['path']], descriptor)
                result = R.tool(bundle, {'op': 'read', 'name': descriptor['hash']})
                self.assertEqual(result['material'], descriptor)
                result['material']['path'] = 'changed response only'
                self.assertEqual(R.tool(bundle, {'op': 'read', 'name': descriptor['hash']})['material'], descriptor)
                self.assertIn('Synthetic instructions scoped to pkg.' if descriptor['kind'] == 'original-instructions'
                              else 'SYNTHETIC_VALUE = 7', result['text'])
            self.assertEqual(listing['skill'], 'skill')
            self.assertEqual(len(listing['materials']), 3)
        bundles = list(prepared['bundles'].values())
        self.assertEqual(bundles[0]['descriptors'], bundles[1]['descriptors'])

    def test_diff_ignores_mutable_checkout_attributes(self):
        original = self.source.diff(self.base, self.head)
        (self.repo / '.gitattributes').write_text('*.txt binary\n')
        self.assertEqual(self.source.diff(self.base, self.head), original)

    def test_unversioned_attributes_cannot_change_pinned_diff_after_prepare(self):
        (self.repo / '.git/info/attributes').write_text('*.txt binary\n')
        with self.assertRaisesRegex(ValueError, 'attributes'):
            self.source.diff(self.base, self.head)

    def test_original_file_material_resolves_pinned_object(self):
        row = self.doc['replay']['cohort'][0]
        h = R.sha(b'first review\n')
        row['context']['materials'].append({'kind': 'original-file', 'at': row['first_review_at'], 'hash': h})
        self.selectors[h] = {'kind': 'original-file', 'path': 'file.txt', 'revision': self.head}
        row['context_hash'] = R.context_digest(row)
        for arm in row['arms'].values(): arm['context_hash'] = row['context_hash']
        self.assertIn('first review\n', self.prepare()['bundles']['old-4201']['materials'].values())
        self.selectors[h]['revision'] = self.base
        with self.assertRaises(ValueError): self.prepare()


class Checkpoints(RepoFixture):
    def test_r2_descriptor_mutations_refuse_checkpoint_resume(self):
        self.contextual_files()
        store = self.create()
        path = self.state / 'checkpoint.json'
        original = path.read_text()
        initial = json.loads(original)
        descriptor = initial['bundles']['old-4201'].get('descriptors')
        self.assertIsInstance(descriptor, list, 'checkpoint must retain material descriptors')
        for field, value in [('hash', 'f' * 64), ('kind', 'original-instructions'),
                             ('path', 'elsewhere/helper.py'), ('revision', self.base)]:
            with self.subTest(field=field):
                mutated = json.loads(original)
                # Editing both arms equally still changes the frozen identity.
                for bundle in mutated['bundles'].values():
                    bundle['descriptors'][1][field] = value
                path.write_text(json.dumps(mutated))
                with self.assertRaisesRegex(ValueError, 'descriptor'):
                    self.reserve(store)
                path.write_text(original)
        mutated = json.loads(original)
        digest = R.sha(b'SYNTHETIC_VALUE = 7\n')
        mutated['selectors'][digest]['path'] = 'elsewhere/helper.py'
        path.write_text(json.dumps(mutated))
        with self.assertRaisesRegex(ValueError, 'frozen input'):
            self.reserve(store)
        path.write_text(original)
        jobs = self.reserve(R.Store(self.state))['jobs']
        self.assertEqual(len(jobs), 2)
        for job in jobs:
            self.assertEqual(R.tool(job, {'op': 'list'})['materials'], job['descriptors'])

    def test_bounded_reservation_resume_and_uncertain_result(self):
        store = self.create()
        first = self.reserve(store, 1)
        self.assertEqual(len(first['jobs']), 1)
        self.assertEqual(first['authority'], 'none')
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o700)
        resumed = R.Store(self.state)
        second = self.reserve(resumed, 1)
        self.assertEqual(len(second['jobs']), 1)
        self.assertNotEqual(first['jobs'][0]['run_key'], second['jobs'][0]['run_key'])
        self.assertEqual(self.reserve(resumed)['jobs'], [])
        self.finish(resumed, first['jobs'][0], 'uncertain')
        self.finish(resumed, second['jobs'][0])
        self.assertEqual(self.reserve(resumed)['jobs'], [])
        self.assertEqual(resumed.report()['rows'][0]['pair'], 'inconclusive')
        self.assertIsNone(resumed.report()['rows'][0]['arms']['old']['counts'])

    def test_save_failure_releases_no_job_and_concurrent_lock_refuses(self):
        store = self.create()
        with patch.object(R, 'write_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): self.reserve(store)
        self.assertEqual(len(self.reserve(store)['jobs']), 2)
        with store.locked():
            with self.assertRaises(ValueError): self.reserve(R.Store(self.state))

    def test_changed_inputs_and_corrupt_checkpoint_refuse_resume(self):
        store = self.create()
        for limit in [0, -1, True, 1.5]:
            with self.assertRaises(ValueError): self.reserve(store, limit)
        for mutate in [
            lambda d: d['replay'].update(selection_rules='changed cohort'),
            lambda d: d['replay']['rubric'].update(matching='new rubric'),
            lambda d: d['replay']['cohort'][0]['history'].update(independent_rounds=0),
        ]:
            changed = copy.deepcopy(self.doc); mutate(changed)
            with self.assertRaises(ValueError): store.reserve(changed, self.journey, 2, '2030-01-04T00:01:00Z')
        path = self.state / 'checkpoint.json'
        good = path.read_text()
        value = json.loads(good); value['code_hash'] = '0' * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.reserve(store)
        path.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError): self.reserve(store)
        path.write_text(good)

    def test_changed_validator_bytes_refuse_resume(self):
        # Use the public CLI in an isolated source copy. No project policy or
        # unowned file is changed; a semantic-neutral byte change must stale it.
        source = self.root / 'copy/tools'
        replay = source / 'skills-eval/replay'; replay.mkdir(parents=True)
        factory = source / 'factory-metrics'; factory.mkdir()
        for name in ('run.py', 'score.py'): shutil.copyfile(HERE / name, replay / name)
        for name in ('experiment_contract.py', 'journey.py', 'metrics.py'):
            shutil.copyfile(FACTORY / name, factory / name)
        docpath = self.root / 'document.json'; docpath.write_text(json.dumps(self.doc))
        journeypath = self.root / 'journey.json'; journeypath.write_text(json.dumps(self.journey))
        for name in ('experiment_contract.py', 'journey.py', 'metrics.py'):
            with self.subTest(dependency=name):
                statepath = self.root / ('state-' + name)
                R.Store.create(statepath, self.prepare())
                path = factory / name; original = path.read_text()
                path.write_text(original + '\n# Synthetic changed validator bytes.\n')
                result = subprocess.run([sys.executable, '-I', str(replay / 'run.py'), 'reserve',
                    '--document', str(docpath), '--journey', str(journeypath), '--state', str(statepath),
                    '--limit', '2', '--at', '2030-01-04T00:01:00Z'], capture_output=True, text=True)
                path.write_text(original)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('harness changed', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_checkpoint_rejects_material_tampering_and_invalid_receipts(self):
        store = self.create(); jobs = self.reserve(store)['jobs']
        with self.assertRaises(ValueError):
            store.receive('unknown-run', 'error', None, '2030-01-04T00:10:00Z')
        with self.assertRaises(ValueError):
            store.receive(jobs[0]['run_key'], 'error', 'invented report', '2030-01-04T00:10:00Z')
        with self.assertRaises(ValueError):
            store.receive(jobs[0]['run_key'], 'complete', 'report', '2030-01-03T00:10:00Z')
        path = self.state / 'checkpoint.json'; original = path.read_text()
        state = json.loads(original)
        bundle = state['bundles'][jobs[0]['run_key']]
        bundle['materials'][next(iter(bundle['materials']))] = 'changed synthetic material'
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'material bytes'):
            store.report()
        path.write_text(original)
        self.finish(store, jobs[0], 'not_run'); self.finish(store, jobs[1], 'uncertain')
        self.assertEqual(self.reserve(store)['jobs'], [])
        self.assertEqual(store.report()['coverage'],
                         {'cohort': 1, 'complete_pairs': 0, 'inconclusive_pairs': 1})

    def test_cli_preparation_and_resume_emit_only_reserved_bundles(self):
        paths = {}
        for name, value in [('document', self.doc), ('journey', self.journey),
                            ('selectors', self.selectors),
                            ('skill-paths', {'old': 'review.md', 'candidate': 'review.md'})]:
            paths[name] = self.root / (name + '.json')
            paths[name].write_text(json.dumps(value))
        def cli(op, *args):
            return subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), op,
                                   '--state', str(self.state), *map(str, args)],
                                  capture_output=True, text=True)
        prepared = cli('prepare', '--repo', self.repo,
                       *[part for key, value in paths.items() for part in ('--' + key, value)])
        self.assertEqual((prepared.returncode, prepared.stdout), (0, ''), prepared.stderr)
        args = ['--document', paths['document'], '--journey', paths['journey'],
                '--at', '2030-01-04T00:01:00Z', '--limit', '2']
        work = cli('reserve', *args)
        self.assertEqual(work.returncode, 0, work.stderr)
        jobs = json.loads(work.stdout)['jobs']
        self.assertEqual(len(jobs), 2)
        self.assertNotIn('sealed_key', work.stdout)
        self.assertNotIn('known', work.stdout)
        self.assertEqual(json.loads(cli('reserve', *args).stdout)['jobs'], [])
        # Output remains on the private controller boundary; no reviewer starts.
        reported = cli('report')
        self.assertEqual(reported.returncode, 0, reported.stderr)
        self.assertEqual(json.loads(reported.stdout)['coverage']['inconclusive_pairs'], 1)

    def test_both_terminal_before_blind_scoring_and_append_only_decisions(self):
        store = self.create()
        jobs = self.reserve(store)['jobs']
        self.finish(store, jobs[0], report='old synthetic report')
        with self.assertRaises(ValueError): store.blind(4201, self.keyfile)
        self.finish(store, jobs[1], report='candidate synthetic report')
        blind = store.blind(4201, self.keyfile)
        self.assertEqual(set(blind), {'pr', 'rubric', 'known', 'reviews'})
        self.assertEqual(len(blind['reviews']), 2)
        self.assertEqual(set(blind['reviews'][0]), {'key', 'status', 'report'})
        decisions = {}
        for review in blind['reviews']:
            decisions[review['key']] = [
                {'id': 'F1', 'severity': 'high', 'outcome': 'catch'},
                {'id': 'F2', 'severity': 'medium', 'outcome': 'miss'},
            ]
        store.adjudicate(4201, decisions, '2030-01-04T00:20:00Z', 's7')
        self.assertEqual(store.report()['rows'][0]['arms']['old']['counts']['catch'], 1)
        with self.assertRaises(ValueError):
            store.adjudicate(4201, decisions, '2030-01-04T00:20:00Z', 's7')
        # A later sourced snapshot can resolve a dispute without rerunning.
        store.adjudicate(4201, decisions, '2030-01-04T00:21:00Z', 's7')
        self.assertEqual(self.reserve(store)['jobs'], [])
        # Identical delivery is idempotent; changed receipt cannot overwrite.
        self.finish(store, jobs[0], report='old synthetic report')
        with self.assertRaises(ValueError): self.finish(store, jobs[0], report='changed')
        self.assertEqual(len(store.read()['document']['replay']['cohort'][0]['arms']['old']['adjudications']), 2)

    def test_key_bytes_are_sealed_until_both_terminal_and_hash_checked(self):
        store = self.create(); jobs = self.reserve(store)['jobs']
        self.finish(store, jobs[0])
        # A nonexistent file cannot be opened before the counterpart finishes.
        with self.assertRaisesRegex(ValueError, 'both paired'):
            store.blind(4201, self.root / 'missing-key')
        self.finish(store, jobs[1])
        self.keyfile.write_text('changed synthetic answer key')
        with self.assertRaisesRegex(ValueError, 'sealed key'):
            store.blind(4201, self.keyfile)

    def test_terminal_error_pair_can_score_complete_arm_but_not_select(self):
        store = self.create(); jobs = self.reserve(store)['jobs']
        self.finish(store, jobs[0]); self.finish(store, jobs[1], 'error')
        blind = store.blind(4201, self.keyfile)
        decisions = {r['key']: [
            {'id': 'F1', 'severity': 'high', 'outcome': 'catch'},
            {'id': 'F2', 'severity': 'medium', 'outcome': 'miss'},
        ] for r in blind['reviews'] if r['status'] == 'complete'}
        store.adjudicate(4201, decisions, '2030-01-04T00:20:00Z', 's7')
        result = store.report()
        self.assertEqual(result['rows'][0]['pair'], 'inconclusive')
        self.assertEqual(result['rows'][0]['arms']['old']['counts']['catch'], 1)
        self.assertIsNone(result['rows'][0]['arms']['candidate']['counts'])
        self.assertEqual(result['paired']['n'], 0)


class Scoring(unittest.TestCase):
    def setUp(self): self.doc, self.journey = base_inputs()

    def score(self): return S.score(self.doc, self.journey)

    def test_literal_paired_arithmetic_and_severity(self):
        result = self.score()
        row = result['rows'][0]
        self.assertEqual(row['pair'], 'complete')
        self.assertEqual(row['known'], {'high': 1, 'medium': 1, 'low': 0})
        self.assertEqual(row['arms']['old']['counts'],
            {'catch': 1, 'miss': 1, 'false_positive': 1, 'unmatched': 0, 'unadjudicated': 0})
        self.assertEqual(row['delta'], {'catch': 1, 'miss': -1, 'false_positive': -1})
        self.assertEqual(row['arms']['old']['severity']['medium']['miss'], 1)
        self.assertEqual(result['paired']['n'], 1)
        self.assertEqual(result['paired']['totals'], row['delta'])
        self.assertEqual(result['evidence_class'], 'fixture-or-replay-only')

    def test_partial_and_unadjudicated_are_not_zero_or_clean(self):
        self.doc['replay'] = literal('partial.json')
        row = self.score()['rows'][0]
        self.assertEqual(row['pair'], 'inconclusive')
        self.assertIsNone(row['delta'])
        self.assertIsNone(row['arms']['candidate']['counts'])
        self.doc['replay']['cohort'][0]['arms']['old']['adjudications'] = []
        row = self.score()['rows'][0]
        self.assertIsNone(row['arms']['old']['counts'])
        self.assertEqual(row['arms']['old']['resolution'], 'unadjudicated')

    def test_clean_control_and_unresolved_report(self):
        r = self.doc['replay']; r['selection'] = 'none'; r['completed_at'] = None
        row = r['cohort'][0]; row['known'] = []
        for arm in row['arms'].values(): arm['adjudications'][0]['findings'] = []
        self.assertEqual(self.score()['rows'][0]['clean_control'], {'old': 'clean', 'candidate': 'clean'})
        row['arms']['old']['adjudications'][0]['findings'] = [
            {'id': 'X1', 'severity': 'low', 'outcome': 'unmatched'}]
        report = self.score()['rows'][0]
        self.assertEqual(report['clean_control']['old'], 'unresolved')
        self.assertEqual(report['arms']['old']['counts']['false_positive'], 0)
        self.assertEqual(report['arms']['old']['counts']['unmatched'], 1)
        self.assertEqual(report['pair'], 'inconclusive')
        row['arms']['old']['adjudications'][0]['findings'][0]['outcome'] = 'false_positive'
        self.assertEqual(self.score()['rows'][0]['clean_control']['old'], 'false_positive')

    def test_duplicate_missing_pair_and_changed_rubric_refuse(self):
        for mutation in [
            lambda r: r['cohort'][0]['arms']['old']['adjudications'][0]['findings'].append(
                {'id': 'F1', 'severity': 'high', 'outcome': 'catch'}),
            lambda r: r['cohort'][0]['arms']['candidate'].update(status='not_run', report_hash=None,
                reported_at=None, finished_at=None, adjudications=[]),
            lambda r: r['rubric'].update(matching='different'),
        ]:
            with self.subTest(mutation=mutation):
                self.doc, self.journey = base_inputs(); mutation(self.doc['replay'])
                with self.assertRaises(ValueError): self.score()


if __name__ == '__main__':
    unittest.main()
