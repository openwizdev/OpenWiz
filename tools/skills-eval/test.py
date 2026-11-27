#!/usr/bin/env python3
import argparse
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as C
spec = importlib.util.spec_from_file_location('eval_cli', HERE / 'eval.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
IDENTITY = ['-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false']
PIN_ENV = ('WIZSKILLS_CHECKOUT', 'WIZSKILLS_COMMIT')


def setUpModule():
    folder = unittest.enterModuleContext(tempfile.TemporaryDirectory())
    literals = Path(folder) / 'literals.txt'
    literals.write_text('synthetic-private-machine\n', encoding='utf-8')
    unittest.enterModuleContext(mock.patch.dict(os.environ, {
        'OPENWIZ_PRIVACY_LITERALS': str(literals),
    }))


class Contract(unittest.TestCase):
    def test_privacy_scan_catches_planted_identifiers(self):
        base = C.load_all()[0]
        for planted in ('see https://github.com/x/y', 'thread thr_synnegative', 'thread cr_child_synthetic', 'issue #123', 'issue #3999',
                        'key sk-ant-abc', 'mail someone@example.org', 'ask Jake'):
            c = copy.deepcopy(base)
            c['brief'] += ' ' + planted
            self.assertTrue(C.privacy_problems(c), planted)
        self.assertEqual(C.privacy_problems(base), [])

    def test_privacy_private_input_refuses_missing_unreadable_or_empty(self):
        base = C.load_all()[0]
        refusal = ['case privacy: private literals input is missing, unreadable or empty']
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ):
            literals = Path(d) / 'literals.txt'
            os.environ.pop('OPENWIZ_PRIVACY_LITERALS', None)
            with self.subTest(input='unset'):
                self.assertEqual(C.privacy_problems(base), refusal)
            for path in ('', str(literals), d):
                with self.subTest(path=path):
                    os.environ['OPENWIZ_PRIVACY_LITERALS'] = path
                    self.assertEqual(C.privacy_problems(base), refusal)
            os.environ['OPENWIZ_PRIVACY_LITERALS'] = str(literals)
            for data in (b'', b'\n', b'synthetic-private-machine\n\n', b'\xff'):
                with self.subTest(data=data):
                    literals.write_bytes(data)
                    self.assertEqual(C.privacy_problems(base), refusal)
            literals.write_text('synthetic-private-machine\n', encoding='utf-8')
            with self.subTest(input='permission denied'), mock.patch.object(Path, 'read_text', side_effect=PermissionError):
                self.assertEqual(C.privacy_problems(base), refusal)
            self.assertEqual(C.privacy_problems(base), [])


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *IDENTITY, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo, files, message):
    for name, text in files.items():
        path = Path(repo, name)
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


def plugin(*names):
    return json.dumps({'name': 'wizskills', 'skills': [f'./skills/{n}' for n in names]})


class FakeWizSkills:
    def __init__(self, root):
        self.path = Path(root, 'wizskills')
        self.path.mkdir()
        git(self.path, 'init', '-q', '-b', 'main')
        self.first = commit(self.path, {'.claude-plugin/plugin.json': plugin('alpha', 'gone'),
                                        'skills/alpha/SKILL.md': 'alpha\n', 'skills/gone/SKILL.md': 'gone\n',
                                        'contracts/decisions.v1.schema.json': '{}\n'}, 'first')
        self.main = commit(self.path, {'.claude-plugin/plugin.json': plugin('alpha', 'beta'),
                                       'skills/alpha/SKILL.md': 'alpha reads `skills/helper/SKILL.md`\n',
                                       'skills/beta/SKILL.md': 'beta\n', 'skills/helper/SKILL.md': 'helper\n',
                                       'skills/gone/SKILL.md': None}, 'second')
        git(self.path, 'checkout', '-q', '-b', 'side')
        self.side = commit(self.path, {'skills/side/SKILL.md': 'side\n'}, 'side')
        git(self.path, 'checkout', '-q', 'main')
        self.pin = E.pinned(str(self.path), self.main)

    def rows(self):
        return {'alpha': {'status': 'shipped'}, 'beta': {'status': 'shipped'},
                'helper': {'status': 'observed-used', 'used_by': 'skills/alpha/SKILL.md'},
                'gone': {'status': 'historical-only', 'last_seen': self.first},
                'side': {'status': 'branch-only', 'branch': 'side', 'commit': self.side}}

    def ledger(self, rows=None):
        return {'schema': 'openwiz.skills-eval.ledger.v1', 'skills': self.rows() if rows is None else rows}


def no_pin_env():
    return {k: v for k, v in os.environ.items() if k not in PIN_ENV + ('OPENROUTER_API_KEY',)}


def cli(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(HERE / 'eval.py'), *args], capture_output=True, text=True,
                          env=no_pin_env() if env is None else env, timeout=120)


class Pinned(unittest.TestCase):
    def setUp(self):
        self.root = unittest.TestCase.enterContext(self, tempfile.TemporaryDirectory())
        self.ws = FakeWizSkills(self.root)

    def test_coverage_without_a_pin_refuses_and_names_the_flags(self):
        done = cli('coverage')
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn('no pinned WizSkills', done.stdout)
        self.assertIn('--wizskills-commit', done.stdout)
        self.assertNotIn('Traceback', done.stderr)

    def test_a_pin_is_a_full_commit_that_the_checkout_holds(self):
        for checkout, commit_id, why in ((str(self.ws.path), 'main', 'full 40-character commit'),
                                         (str(self.ws.path), self.ws.main[:12], 'full 40-character commit'),
                                         (str(self.ws.path), 'f' * 40, 'does not have commit'),
                                         (str(Path(self.root, 'missing')), self.ws.main, 'does not have commit'),
                                         ('', self.ws.main, 'no pinned WizSkills'),
                                         (str(self.ws.path), '', 'no pinned WizSkills')):
            with self.subTest(commit=commit_id, why=why), self.assertRaises(E.Refusal) as refused:
                E.pinned(checkout, commit_id)
            self.assertIn(why, str(refused.exception))
        bare = Path(self.root, 'other')
        bare.mkdir()
        git(bare, 'init', '-q', '-b', 'main')
        other = commit(bare, {'README.md': 'not wizskills\n'}, 'other')
        with self.assertRaises(E.Refusal) as refused:
            E.pinned(str(bare), other)
        self.assertIn('.claude-plugin/plugin.json', str(refused.exception))
        shallow = Path(self.root, 'shallow')
        subprocess.run(['git', 'clone', '-q', '--depth', '1', self.ws.path.as_uri(), str(shallow)], check=True)
        with self.assertRaises(E.Refusal) as refused:
            E.pinned(str(shallow), self.ws.main)
        self.assertIn('shallow', str(refused.exception))

    def test_the_flag_pin_wins_over_the_environment(self):
        flags = argparse.Namespace(wizskills=str(self.ws.path), wizskills_commit=self.ws.main)
        with mock.patch.dict(os.environ, {'WIZSKILLS_CHECKOUT': '/nowhere', 'WIZSKILLS_COMMIT': 'a' * 40}):
            self.assertEqual(E.pin_from(flags)['commit'], self.ws.main)
        unset = argparse.Namespace(wizskills=None, wizskills_commit=None)
        with mock.patch.dict(os.environ, {'WIZSKILLS_CHECKOUT': str(self.ws.path), 'WIZSKILLS_COMMIT': self.ws.first}):
            self.assertEqual(E.pin_from(unset)['commit'], self.ws.first)

    def test_the_snapshot_is_the_host_with_wizskills_installed_at_the_pin(self):
        read, lst = E.snapshot('HEAD', self.ws.pin)
        self.assertEqual(read('skills/beta/SKILL.md'), 'beta\n')
        self.assertIsNone(read('skills/gone/SKILL.md'))
        self.assertEqual(json.loads(read('.wizskills/.claude-plugin/plugin.json'))['name'], 'wizskills')
        self.assertEqual(read('AGENTS.md'), (HERE.parent.parent / 'AGENTS.md').read_text(encoding='utf-8'))
        self.assertEqual(sorted(lst('skills/')), ['skills/alpha/SKILL.md', 'skills/beta/SKILL.md',
                                                   'skills/helper/SKILL.md'])
        self.assertNotIn('skills', lst(''))
        self.assertEqual(E.shipped(read), ['alpha', 'beta'])

    def test_a_snapshot_without_a_pin_has_no_skills(self):
        read, lst = E.snapshot('HEAD', None)
        self.assertEqual(lst('skills/'), [])
        with self.assertRaises(E.Refusal):
            E.shipped(read)

    def test_run_checks_offline_before_it_looks_for_a_key(self):
        done = cli('run', '--out', str(Path(self.root, 'results')), '--wizskills', str(self.ws.path),
                   '--wizskills-commit', self.ws.main)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('refusing to run: eval.py check has', done.stdout + done.stderr)
        self.assertNotIn('OPENROUTER_API_KEY', done.stdout + done.stderr)
        self.assertFalse(Path(self.root, 'results', 'manifest.json').exists())

    def test_a_results_set_records_the_wizskills_pin(self):
        manifest = {'settings': {}, 'settings_hash': E.sha({}), 'repeats': 1, 'cases': [],
                    'cases_hash': C.cases_hash(), 'code_hash': E.code_hash(), 'revision': {'commit': 'c'}}
        self.assertIn('no WizSkills pin', ' '.join(E.manifest_problems(manifest)))
        manifest['wizskills'] = {'commit': self.ws.main, 'tree': git(self.ws.path, 'rev-parse', 'HEAD^{tree}')}
        self.assertNotIn('no WizSkills pin', ' '.join(E.manifest_problems(manifest)))
        self.assertEqual(E.wizskills_revision(self.ws.pin), manifest['wizskills'])


class Ledger(unittest.TestCase):
    def setUp(self):
        self.root = unittest.TestCase.enterContext(self, tempfile.TemporaryDirectory())
        self.ws = FakeWizSkills(self.root)
        self.read = E.snapshot('HEAD', self.ws.pin)[0]

    def problems(self, ledger, referenced=(), earlier=()):
        return E.ledger_problems(ledger, self.ws.pin, self.read, set(referenced), set(earlier))

    def test_a_ledger_that_matches_the_pin_has_no_problems(self):
        self.assertEqual(self.problems(self.ws.ledger(), referenced={'alpha', 'gone'}), [])
        self.assertEqual(E.audit(self.ws.ledger(), self.ws.pin, self.read), [])

    def test_every_skill_on_the_pin_needs_a_row(self):
        for name in ('alpha', 'beta', 'helper'):
            rows = self.ws.rows()
            del rows[name]
            with self.subTest(name=name):
                self.assertEqual([p for p in self.problems(self.ws.ledger(rows)) if p.startswith(name + ':')],
                                 [f'{name}: on WizSkills {self.ws.main[:12]} with no ledger row'])

    def test_a_skill_removed_from_main_needs_a_historical_row(self):
        rows = self.ws.rows()
        del rows['gone']
        self.assertIn(f'gone: in the history of WizSkills {self.ws.main[:12]} with no ledger row',
                      self.problems(self.ws.ledger(rows)))
        rows['gone'] = {'status': 'historical-only', 'last_seen': self.ws.main}
        self.assertIn(f'gone: historical-only, but skills/gone/SKILL.md is not at {self.ws.main[:12]}',
                      self.problems(self.ws.ledger(rows)))

    def test_a_status_must_match_the_pin(self):
        cases = {'beta': {'status': 'historical-only', 'last_seen': self.ws.first},
                 'helper': {'status': 'shipped'}, 'alpha': {'status': 'observed-used', 'used_by': 'skills/beta/SKILL.md'},
                 'gone': {'status': 'shipped'}, 'side': {'status': 'historical-only', 'last_seen': self.ws.side}}
        for name, row in cases.items():
            with self.subTest(name=name):
                rows = dict(self.ws.rows(), **{name: row})
                self.assertTrue([p for p in self.problems(self.ws.ledger(rows)) if p.startswith(name + ':')],
                                row)

    def test_observed_used_names_a_file_that_loads_it(self):
        for used_by in (None, 'skills/beta/SKILL.md', 'skills/nowhere.md'):
            rows = dict(self.ws.rows(), helper={'status': 'observed-used', 'used_by': used_by})
            with self.subTest(used_by=used_by):
                self.assertTrue([p for p in self.problems(self.ws.ledger(rows)) if p.startswith('helper:')])

    def test_a_branch_only_row_is_checked_where_the_checkout_can_see_it(self):
        for row in ({'status': 'branch-only', 'branch': 'side', 'commit': self.ws.first},
                    {'status': 'branch-only', 'branch': '', 'commit': self.ws.side},
                    {'status': 'branch-only', 'branch': 'side'}):
            rows = dict(self.ws.rows(), side=row)
            with self.subTest(row=row):
                self.assertTrue([p for p in self.problems(self.ws.ledger(rows)) if p.startswith('side:')])
        rows = dict(self.ws.rows(), gone={'status': 'branch-only', 'branch': 'side', 'commit': self.ws.side})
        self.assertTrue([p for p in self.problems(self.ws.ledger(rows)) if p.startswith('gone:')])

    def test_the_audit_finds_a_branch_skill_with_no_row(self):
        rows = self.ws.rows()
        del rows['side']
        self.assertEqual(self.problems(self.ws.ledger(rows)), [])
        self.assertEqual(E.audit(self.ws.ledger(rows), self.ws.pin, self.read),
                         ['side: on WizSkills branch side with no ledger row'])
        self.assertEqual(E.propose(self.ws.ledger(rows), self.ws.pin, self.read),
                         {'side': {'status': 'branch-only', 'branch': 'side', 'commit': self.ws.side}})

    def test_a_name_the_eval_uses_needs_a_row(self):
        self.assertEqual(self.problems(self.ws.ledger(), referenced={'alpha', 'plan-graph'}),
                         ["plan-graph: named by the eval's cases or maps with no ledger row"])

    def test_a_row_is_never_dropped(self):
        rows = self.ws.rows()
        self.assertEqual(self.problems(self.ws.ledger(rows), earlier={'alpha', 'old-name'}),
                         ['old-name: dropped from the ledger; change its status instead of removing the row'])

    def test_earlier_rows_come_from_every_committed_version_of_the_ledger(self):
        host = Path(self.root, 'host')
        host.mkdir()
        git(host, 'init', '-q', '-b', 'main')
        path = 'tools/skills-eval/ledger.json'
        commit(host, {path: json.dumps(self.ws.ledger(dict(self.ws.rows(), extra={'status': 'shipped'})))}, 'one')
        commit(host, {path: json.dumps(self.ws.ledger())}, 'two')
        commit(host, {'README.md': 'later\n'}, 'three')
        self.assertEqual(E.earlier_rows('HEAD', host), {'alpha', 'beta', 'helper', 'gone', 'side', 'extra'})

    def test_a_malformed_ledger_is_one_problem(self):
        for ledger in ([], {'skills': {}}, {'schema': 'openwiz.skills-eval.ledger.v1', 'skills': []},
                       {'schema': 'openwiz.skills-eval.ledger.v1', 'skills': {}, 'extra': 1}):
            with self.subTest(ledger=ledger):
                self.assertEqual(self.problems(ledger), ['ledger.json is not an openwiz.skills-eval.ledger.v1 object'])
        rows = dict(self.ws.rows(), beta={'status': 'shipped', 'note': 'x'})
        self.assertIn("beta: a shipped row has exactly the keys ['status']", self.problems(self.ws.ledger(rows)))
        rows = dict(self.ws.rows(), beta={'status': 'retired'})
        self.assertTrue([p for p in self.problems(self.ws.ledger(rows)) if p.startswith('beta: status')])

    def test_coverage_lists_every_row_and_every_unledgered_skill(self):
        rows = self.ws.rows()
        del rows['beta']
        case = {'id': 'synthetic-alpha', 'skills': ['alpha'], 'category': 'workflow'}
        cov = E.ledger_coverage(self.ws.ledger(rows), self.ws.pin, self.read, [case], {})
        self.assertEqual(sorted(cov), ['alpha', 'beta', 'gone', 'helper', 'side'])
        self.assertEqual(cov['alpha']['status'], 'shipped')
        self.assertEqual(cov['alpha']['cases']['workflow'], ['synthetic-alpha'])
        self.assertEqual(cov['alpha']['missing'], ['approval', 'failure', 'privacy'])
        self.assertEqual(cov['beta']['status'], None)
        self.assertEqual(cov['gone']['status'], 'historical-only')
        self.assertEqual(cov['gone']['missing'], [])
        self.assertEqual(cov['side']['branch'], 'side')


@unittest.skipUnless(all(os.environ.get(k) for k in PIN_ENV), 'set WIZSKILLS_CHECKOUT and WIZSKILLS_COMMIT')
class CommittedLedger(unittest.TestCase):
    def test_the_committed_ledger_describes_the_pinned_wizskills(self):
        pin = E.pin_from(argparse.Namespace(wizskills=None, wizskills_commit=None))
        read = E.snapshot('HEAD', pin)[0]
        ledger = json.loads((HERE / 'ledger.json').read_text())
        self.assertEqual(E.ledger_problems(ledger, pin, read, E.referenced(), E.earlier_rows('HEAD')), [])
        self.assertEqual(E.audit(ledger, pin, read), [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
