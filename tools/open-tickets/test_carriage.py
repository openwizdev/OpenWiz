#!/usr/bin/env python3
"""P8/P11: real reviewed O14 patch seam, fake GitHub publication, synthetic Git."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_move as moves
from test_move import fixture

CHECKER = HERE.parent / 'privacy-check/check.py'
IMPORTER = HERE.parent / 'open-import/import.py'


class Carriage(moves.MoveContract):
    # Reuse the issue boundary helpers, not their tests.
    def setUp(self):
        super().setUp()
        self.source = self.repo('source', 'old\n')
        self.public = self.repo('public', 'old\n')
        self.base = self.git(self.public, 'rev-parse', 'HEAD').strip()
        self.source_base = self.git(self.source, 'rev-parse', 'HEAD').strip()
        (self.source / 'crates/core/src/lib.rs').write_text('public change\n')
        (self.source / 'private').mkdir()
        (self.source / 'private/record').write_text('synthetic private record\n')
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-qm', 'private source message')
        self.source_head = self.git(self.source, 'rev-parse', 'HEAD').strip()
        self.checker = self.root / 'checker.py'
        self.checker.write_text('import sys\nsys.dont_write_bytecode=True\n' +
            f'sys.path.insert(0, {str(CHECKER.parent)!r})\nimport check\n' +
            f'check.PUBLIC_ROOT={self.base!r}\ncheck.PUBLIC_ANCHOR={self.base!r}\n' +
            'sys.exit(check.main())\n')
        self.patch = self.root / 'patch'
        result = subprocess.run([sys.executable, '-I', str(IMPORTER), 'patch', '--source', str(self.source),
            '--source-base', self.source_base, '--commit', self.source_head, '--destination', str(self.public),
            '--checker', str(self.checker), '--literals', str(self.literals), '--output', str(self.patch)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.digest = json.loads(result.stdout)['binding_sha256']
        proposal = fixture()
        proposal['graph']['items'].append(dict(number=9010, kind='pull_request', title='Synthetic PR',
            labels=['bug,triage', 'ready-for-agent'], milestone='Infra', parent=None, blockers=[], state='open'))
        proposal['bodies']['9010'] = 'Ja' 'ke: "synthetic PR words"\nBuilder thr_synpatch1.'
        proposal['pulls'] = {'9010': dict(source_base=self.source_base, source_head=self.source_head, observed_base=self.source_base,
            destination=str(self.public), patch_dir=str(self.patch), binding_sha256=self.digest)}
        self.plan.write_text(json.dumps(proposal))
        self.world.write_text(json.dumps(dict(move=proposal, created={}, comments={}, writes=0,
                                             refs={}, public_base=self.base)))

    def repo(self, name, content):
        root = self.root / name
        root.mkdir()
        self.git(root, 'init', '-qb', 'main')
        self.git(root, 'config', 'user.name', 'Synthetic')
        self.git(root, 'config', 'user.email', 'synthetic@users.noreply.github.com')
        p = root / 'crates/core/src/lib.rs'
        p.parent.mkdir(parents=True)
        p.write_text(content)
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-qm', 'synthetic baseline')
        return root

    def git(self, root, *args):
        r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def run_move(self, *args, ok=True, importer=None):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'move.py'), '--plan', str(self.plan),
            '--state-dir', str(self.state), '--map-out', str(self.map), '--checker', str(self.checker),
            '--literals', str(self.literals), '--importer', str(importer or IMPORTER), '--git', str(HERE / 'fake-git'),
            '--gh', str(HERE / 'fake-gh'), *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def test_pr_public_patch_links_metadata_provenance_and_resume(self):
        initial = self.world.read_text()
        self.run_move('--apply')
        complete = json.loads(self.world.read_text())
        saved_map = self.map.read_bytes()
        for fault in ['was', 'moved', 'map']:
            world = json.loads(json.dumps(complete))
            if fault == 'was':
                world['created']['4004']['body'] = 'public edit without origin'
            elif fault == 'moved':
                world['comments']['9010'] = world['comments']['9010'][:1]
            else:
                self.map.write_bytes(saved_map.replace(b'pull_request\t9010\t4004\n', b''))
            self.world.write_text(json.dumps(world))
            before = self.world.read_bytes()
            self.run_move('--verify', ok=False)
            self.assertEqual(self.world.read_bytes(), before)
            self.map.write_bytes(saved_map)
        effects = complete['writes']
        for stop in [None, *range(1, effects + 1)]:
            with self.subTest(after_effect=stop):
                world = json.loads(initial)
                if stop is not None:
                    world['stop_after_write'] = stop
                self.world.write_text(json.dumps(world))
                self.state = self.root / ('state-' + str(stop))
                self.map = self.root / ('map-' + str(stop))
                if stop is not None:
                    self.run_move('--apply', ok=False)
                self.run_move('--apply')
                self.run_move('--verify')
                world = json.loads(self.world.read_text())
                self.assertEqual(world['move'], json.loads(self.plan.read_text()))
                self.assertEqual(len(world['created']), 4)
                self.assertEqual(len(world['refs']), 1)
                pr = world['created']['4004']
                self.assertIn('pull_request', pr)
                self.assertEqual(pr['labels'], [{'name': 'bug,triage'}])
                self.assertEqual(pr['milestone'], {'title': 'Infra', 'number': 7})
                self.assertTrue(pr['body'].endswith('was [ClosedWiz #9010]'
                    '(https://github.com/jparker2006/ClosedWiz/pull/9010)'))
                self.assertNotIn('thr_', pr['body'])
                self.assertNotIn('synthetic PR words', pr['body'])
                self.assertIn('1. "synthetic PR words"', world['comments']['9010'][0]['body'])
                self.assertEqual(world['comments']['9010'][1]['body'],
                    'moved to [OpenWiz #4004](https://github.com/openwizdev/openwiz/pull/4004)')
                self.assertIn('pull_request\t9010\t4004\n', self.map.read_text())
                commit = pr['headRefOid']
                self.assertEqual(self.git(self.public, 'show', '-s', '--format=%P', commit).strip(), self.base)
                self.assertEqual(self.git(self.public, 'show', commit + ':crates/core/src/lib.rs'), 'public change\n')
                self.assertEqual(self.git(self.public, 'ls-tree', '-r', '--name-only', commit).strip(), 'crates/core/src/lib.rs')
                absent = subprocess.run(['git', '-C', str(self.public), 'cat-file', '-e', self.source_head], capture_output=True)
                self.assertNotEqual(absent.returncode, 0)
                self.assertEqual(self.git(self.public, 'rev-parse', 'HEAD').strip(), self.base)
                self.assertEqual(self.git(self.public, 'status', '--porcelain'), '')
                before = self.world.read_bytes()
                pr['headRefOid'] = self.source_head
                self.world.write_text(json.dumps(world))
                self.run_move('--verify', ok=False)
                self.world.write_bytes(before)

    def test_b1_diverged_pr_binds_observed_tip_and_patch_merge_base_separately(self):
        tree = self.git(self.source, 'rev-parse', self.source_base + '^{tree}').strip()
        observed = self.git(self.source, 'commit-tree', tree, '-p', self.source_base, '-m', 'base advances independently').strip()
        proposal = json.loads(self.plan.read_text())
        proposal['pulls']['9010']['observed_base'] = observed
        self.plan.write_text(json.dumps(proposal))
        world = json.loads(self.world.read_text())
        world['move'] = proposal
        self.world.write_text(json.dumps(world))
        self.run_move('--apply')
        self.run_move('--verify')
        world = json.loads(self.world.read_text())
        world['move']['pulls']['9010']['observed_base'] = self.source_base
        self.world.write_text(json.dumps(world))
        before = self.world.read_bytes()
        self.run_move('--apply', ok=False)
        self.assertEqual(self.world.read_bytes(), before)

    def test_b2_completed_pr_metadata_preserves_later_public_removal(self):
        self.run_move('--apply')
        world = json.loads(self.world.read_text())
        world['created']['4004'].update(labels=[], milestone=None)
        self.world.write_text(json.dumps(world))
        before = self.world.read_bytes()
        self.run_move('--apply', ok=False)
        self.assertEqual(self.world.read_bytes(), before)

    def test_r1_uncertain_pr_metadata_removed_after_response_loss_is_not_replayed(self):
        world = json.loads(self.world.read_text())
        world['stop_after_write'] = 18
        self.world.write_text(json.dumps(world))
        self.run_move('--apply', ok=False)
        world = json.loads(self.world.read_text())
        self.assertEqual(world['writes'], 18)
        self.assertEqual(world['created']['4004']['labels'], [{'name': 'bug,triage'}])
        self.assertEqual(world['created']['4004']['milestone'], {'number': 7, 'title': 'Infra'})
        world['created']['4004'].update(labels=[], milestone=None)
        self.world.write_text(json.dumps(world))
        before, journal = self.world.read_bytes(), (self.state / 'state.json').read_bytes()
        self.run_move('--apply', ok=False)
        self.assertEqual(self.world.read_bytes(), before)
        self.assertEqual((self.state / 'state.json').read_bytes(), journal)

    def test_b6_closing_references_map_and_unresolved_closures_refuse(self):
        proposal = json.loads(self.plan.read_text())
        prose = ('\nfix (a formatting typo) before retry.\nfix `command_name` output.\n'
                 'fix (ordinary prose) and `another_command`.\n'
                 'Fixes ((nested ordinary prose)).\nFixes (the `command_name` output).')
        proposal['bodies']['9010'] += '\nCloses #9002. Fixes jparker2006/ClosedWiz#9003.\nResolves: https://github.com/jparker2006/ClosedWiz/issues/9002.\nFixes closes #9003.' + prose
        self.plan.write_text(json.dumps(proposal))
        world = json.loads(self.world.read_text())
        world['move'] = proposal
        self.world.write_text(json.dumps(world))
        self.run_move('--apply')
        body = json.loads(self.world.read_text())['created']['4004']['body']
        with self.subTest(mapped=True):
            self.assertIn('Closes #4002. Fixes #4003.', body)
            self.assertIn('Resolves: #4002.', body)
            self.assertIn('Fixes closes #4003.', body)
            self.assertIn(prose, body)
        for index, text in enumerate(['Closes #9999', 'Resolves jparker2006/ClosedWiz#9999',
                     'Fixes https://github.com/jparker2006/ClosedWiz/pull/9002',
                     'Fixes https://github.com/jparker2006/ClosedWiz/issues/9010', 'Fixes #9010',
                     'Fixes https://github.com/jparker2006/ClosedWiz/issues/9999',
                     'Fixes https://github.com/jparker2006/ClosedWiz/issues/9002#issuecomment-9003',
                     'Fixes https://github.com/jparker2006/ClosedWiz/issues/9002?query=synthetic',
                     'Fixes <https://github.com/jparker2006/ClosedWiz/issues/9002>',
                     'Fixes [issue](https://github.com/jparker2006/ClosedWiz/issues/9002)',
                     'Fixes (https://github.com/jparker2006/ClosedWiz/issues/9002)',
                     'Closes #9002suffix', 'Closes #9002#issuecomment-9003',
                     'Fixes [bug][ref]\n\n[ref]: https://github.com/jparker2006/ClosedWiz/issues/9002',
                     'Fixes [ref]\n\n[ref]: https://github.com/jparker2006/ClosedWiz/issues/9002',
                     'Fixes [bug][]\n\n[bug]: https://github.com/jparker2006/ClosedWiz/issues/9002',
                     'Fixes (#9002)', 'Fixes `#9002`', 'Fixes (unknown #9999)',
                     'Fixes (ordinary prose) #9002', 'Fixes `command` #9999',
                     'Fixes (unclosed prose', 'Fixes `unclosed_command',
                     'Fixes ((unclosed prose)', 'Fixes (ordinary prose)suffix',
                     'Fixes ((#9002))', 'Fixes (the `command` output) #9999',
                     'Fixes (``x``` y`)',
                     'Fixes `command`suffix']):
            with self.subTest(unresolved=text):
                self.unresolved_reference_case(proposal, text, index)

    def test_excluded_closing_binding_is_rechecked_before_effects_and_verify(self):
        # Consume the read-only collector's actual binding, then exercise the
        # future fake-gh write boundary and a changed native parent/body.
        proposal = json.loads(self.plan.read_text())
        proposal['graph']['items'] += [
            dict(number=1257, kind='issue', title='Synthetic migration', labels=[], milestone=None,
                 parent=None, blockers=[], state='open'),
            dict(number=1283, kind='issue', title='Synthetic remaining ticket', labels=[], milestone=None,
                 parent=1257, blockers=[], state='open')]
        proposal['graph']['exclude'] = [1257, 1283]
        proposal['bodies']['9010'] = 'Closes #9002.\nFixes #1283.\nResolves jparker2006/ClosedWiz#1257.'
        source = json.loads(json.dumps(proposal))
        source['bodies'].update({'1257': 'Synthetic migration body.', '1283': 'Synthetic remaining body.'})
        world = json.loads(self.world.read_text())
        world['move'] = source
        self.world.write_text(json.dumps(world))
        out = self.root / 'collected'
        r = subprocess.run([sys.executable, '-I', str(HERE / 'collect.py'), '--gh', str(HERE / 'fake-gh'),
            '--out', str(out), '--checker', str(self.checker), '--literals', str(self.literals)],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        proposal['excluded_targets'] = json.loads((out / 'provenance.json').read_text())['excluded_targets']
        self.plan.write_text(json.dumps(proposal))
        initial = self.world.read_bytes()
        bad = json.loads(initial)
        bad['move']['graph']['items'][-1]['parent'] = 9001
        self.world.write_text(json.dumps(bad))
        before = self.world.read_bytes()
        self.assertIn('source: ambiguous migration child provenance', self.run_move('--apply', ok=False).stderr)
        self.assertEqual(self.world.read_bytes(), before)
        self.world.write_bytes(initial)
        self.run_move('--apply')
        applied = json.loads(self.world.read_text())
        body = applied['created']['4004']['body']
        self.assertIn('Closes #4002.', body)
        for n in [1257, 1283]:
            self.assertIn(f'Related private issue [ClosedWiz #{n}](https://github.com/jparker2006/ClosedWiz/issues/{n})', body)
        self.assertEqual(applied['move'], source)
        self.run_move('--verify')
        applied['move']['bodies']['1283'] += ' changed'
        self.world.write_text(json.dumps(applied))
        before = self.world.read_bytes()
        journal = (self.state / 'state.json').read_bytes()
        self.assertIn('source: excluded-target binding changed', self.run_move('--verify', ok=False).stderr)
        self.assertEqual(self.world.read_bytes(), before)
        self.assertEqual((self.state / 'state.json').read_bytes(), journal)

    def unresolved_reference_case(self, proposal, text, index):
        proposal['bodies']['9010'] = text
        self.plan.write_text(json.dumps(proposal))
        world = dict(move=proposal, created={}, comments={}, writes=0, refs={}, public_base=self.base)
        self.world.write_text(json.dumps(world))
        self.state = self.root / ('unresolved-' + str(index))
        self.map = self.root / ('unresolved-map-' + str(index))
        before = self.world.read_bytes()
        self.run_move('--apply', ok=False)
        self.assertEqual(self.world.read_bytes(), before)

    def test_b7_real_publisher_does_not_follow_unreviewed_tags(self):
        receiver = self.root / 'receiver'
        receiver.mkdir()
        self.git(receiver, 'init', '--bare', '-q')
        self.git(self.public, 'tag', '-a', 'synthetic-unreviewed-tag', '-m', 'synthetic unchecked tag message', self.base)
        self.git(self.public, 'config', 'push.followTags', 'true')
        world = json.loads(self.world.read_text())
        world['receiver'] = str(receiver)
        self.world.write_text(json.dumps(world))
        self.run_move('--apply')
        refs = self.git(receiver, 'for-each-ref', '--format=%(refname)').splitlines()
        world = json.loads(self.world.read_text())
        self.assertEqual(refs, ['refs/heads/' + world['created']['4004']['headRefName']])

    def test_b7_publisher_ignores_destination_url_rewrites(self):
        receiver = self.root / 'intended-receiver'
        diverted = self.root / 'diverted-receiver'
        for repo in [receiver, diverted]:
            repo.mkdir()
            self.git(repo, 'init', '--bare', '-q')
        self.git(self.public, 'config', 'url.' + str(diverted) + '.insteadOf', str(receiver))
        world = json.loads(self.world.read_text())
        world['receiver'] = str(receiver)
        self.world.write_text(json.dumps(world))
        self.run_move('--apply')
        world = json.loads(self.world.read_text())
        expected = ['refs/heads/' + world['created']['4004']['headRefName']]
        self.assertEqual(self.git(receiver, 'for-each-ref', '--format=%(refname)').splitlines(), expected)
        self.assertEqual(self.git(diverted, 'for-each-ref', '--format=%(refname)'), '')

    def test_pr_tampered_binding_source_or_missing_seam_refuses_before_effects(self):
        original = self.plan.read_text()
        binding = self.patch / 'binding.json'
        for change in ['digest', 'source', 'missing']:
            proposal = json.loads(original)
            if change == 'digest':
                proposal['pulls']['9010']['binding_sha256'] = '0' * 64
            elif change == 'source':
                proposal['pulls']['9010']['source_head'] = self.source_base
            else:
                proposal.pop('pulls')
            self.plan.write_text(json.dumps(proposal))
            before = self.world.read_bytes()
            self.run_move('--apply', ok=False)
            self.assertEqual(self.world.read_bytes(), before)
            self.assertFalse(self.state.exists())
        self.plan.write_text(original)
        binding.write_bytes(binding.read_bytes() + b' ')
        self.run_move('--apply', ok=False)
        self.assertFalse(self.state.exists())


    def test_pr_changed_carriage_list_refuses_before_reapplication(self):
        # The pinned importer beside a valid list other than the one the reviewed
        # binding was prepared under: the handoff itself refuses, before O14 runs.
        importer = self.root / 'changed-list/import.py'
        importer.parent.mkdir()
        importer.write_bytes(IMPORTER.read_bytes())
        rules = json.loads((IMPORTER.parent / 'paths.json').read_text())
        rules['keep'].append('docs/synthetic-unreviewed.md')
        (importer.parent / 'paths.json').write_text(json.dumps(rules))
        before = self.world.read_bytes()
        r = self.run_move('--apply', ok=False, importer=importer)
        self.assertIn('PR handoff: importer or carriage list differs from reviewed O14 delivery', r.stderr)
        self.assertEqual(self.world.read_bytes(), before)
        self.assertFalse(self.state.exists())

# Only PR-owning contracts run here; issue contracts remain owned by test_move.py.
for name in list(moves.MoveContract.__dict__):
    if name.startswith('test_'):
        setattr(Carriage, name, None)

if __name__ == '__main__':
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--checker', type=Path, default=CHECKER)
    p.add_argument('--importer', type=Path, default=IMPORTER)
    options, rest = p.parse_known_args()
    CHECKER, IMPORTER = options.checker, options.importer
    unittest.main(argv=[sys.argv[0], *rest])
