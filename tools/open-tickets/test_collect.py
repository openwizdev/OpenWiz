#!/usr/bin/env python3
"""P8/P11 full read-only collection, provenance and planned-link completeness."""
import argparse
import hashlib
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
from test_move import fixture
CHECKER = HERE.parent / 'privacy-check/check.py'


class Collection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.world = self.root / 'world'
        self.world.write_text(json.dumps(dict(move=fixture(), created={}, comments={}, writes=0)))
        self.out = self.root / 'output'
        self.literals = self.root / 'literals'
        self.literals.write_text('synthetic-unused-literal\n')
        self.env = dict(os.environ, OPEN_TICKETS_WORLD=str(self.world), OPEN_TICKETS_LOG=str(self.root / 'calls'))

    def run_cli(self, *flags, ok=True):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'collect.py'), '--gh', str(HERE / 'fake-gh'),
            '--out', str(self.out), '--checker', str(CHECKER), '--literals', str(self.literals),
            '--snapshot-attempts', '1', *flags],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0 if ok else 1, r.stdout + r.stderr)
        if not ok:
            self.assertTrue(r.stderr.startswith('refused:'), r.stderr)
            self.assertNotIn('Traceback', r.stderr)
        return r

    def test_complete_source_operations_both_links_and_missing_link_or_row_refusal(self):
        before = self.world.read_bytes()
        self.run_cli()
        self.assertEqual(self.world.read_bytes(), before)
        self.assertEqual((self.out / 'map.dry-run.tsv').read_text(),
            'kind\tclosedwiz\topenwiz\nissue\t9001\tplanned\nissue\t9002\tplanned\nissue\t9003\tplanned\n')
        operations = json.loads((self.out / 'operations.json').read_text())
        self.assertEqual([r['closedwiz'] for r in operations], [9001, 9002, 9003])
        self.assertIn('[closing PR #9900](https://github.com/jparker2006/ClosedWiz/pull/9900)',
                      operations[1]['new']['body'])
        for row in operations:
            n = row['closedwiz']
            self.assertTrue(row['new']['body'].endswith(f'was [ClosedWiz #{n}]'
                f'(https://github.com/jparker2006/ClosedWiz/issues/{n})'))
            self.assertEqual(row['original_comment'], 'moved to [OpenWiz #${openwiz:' + str(n) + '}]'
                '(https://github.com/openwizdev/openwiz/issues/${openwiz:' + str(n) + '})')
            self.assertNotIn('ready-for-agent', row['new']['labels'])
            self.assertNotIn('ready-for-human', row['new']['labels'])
        self.run_cli('--check')
        saved = (self.out / 'operations.json').read_bytes()
        (self.out / 'operations.json').write_text(json.dumps(operations + [None]))
        self.run_cli('--check', ok=False)
        for comment in ['', 'moved to [OpenWiz #${openwiz:9002}]'
                        '(https://github.com/jparker2006/OpenWiz/issues/${openwiz:9002})']:
            operations[1]['original_comment'] = comment  # missing, or the legacy address
            (self.out / 'operations.json').write_text(json.dumps(operations))
            self.run_cli('--check', ok=False)  # the saved binding refuses first
        (self.out / 'operations.json').write_bytes(saved)
        (self.out / 'map.dry-run.tsv').write_text('kind\tclosedwiz\topenwiz\n')
        self.run_cli('--check', ok=False)

    def test_b5_saved_graph_and_provenance_are_complete_and_bound(self):
        self.run_cli()
        saved = {p.name: p.read_bytes() for p in self.out.iterdir()}
        for fault in ['parent', 'blockers', 'milestone', 'graph-reference', 'provenance', 'report']:
            with self.subTest(fault=fault):
                for name, data in saved.items():
                    (self.out / name).write_bytes(data)
                rows = json.loads(saved['operations.json'])
                if fault in ['parent', 'blockers', 'milestone']:
                    del rows[1]['new'][fault]
                elif fault == 'graph-reference':
                    rows[1]['new']['blockers'] = [{'closedwiz': 9999}]
                else:
                    name = 'provenance.json' if fault == 'provenance' else 'report.json'
                    value = json.loads(saved[name])
                    if fault == 'provenance':
                        value['source_nodes']['9001'] = '0' * 64
                    else:
                        value['operations_sha256'] = '0' * 64
                    (self.out / name).write_text(json.dumps(value))
                (self.out / 'operations.json').write_text(json.dumps(rows))
                if fault in ['parent', 'blockers', 'milestone', 'graph-reference']:
                    # Deliberately rebind the digest: the schema/ref guard must reject independently.
                    report = json.loads(saved['report.json'])
                    report['operations_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True,
                                                                          ensure_ascii=False).encode()).hexdigest()
                    (self.out / 'report.json').write_text(json.dumps(report))
                before = {p.name: p.read_bytes() for p in self.out.iterdir()}
                self.run_cli('--check', ok=False)
                self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()}, before)

    def test_partial_or_changed_source_refuses(self):
        initial = self.world.read_bytes()
        for fault in ['partial-graph', 'changed-source', 'cycle']:
            with self.subTest(fault=fault):
                Path(self.env['OPEN_TICKETS_LOG']).unlink(missing_ok=True)
                world = json.loads(initial)
                world['collect_fault'] = fault
                if fault == 'cycle':
                    world['move']['graph']['items'][2]['blockers'] = [9002]
                self.world.write_text(json.dumps(world))
                self.run_cli(ok=False)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.world.read_text(), json.dumps(world))

    def test_snapshot_retries_are_bounded_and_report_changing_objects(self):
        # A moving fleet can settle on a later pair; permanent churn must not
        # become a planned run or a watcher. Neither case was previously retried.
        initial = json.loads(self.world.read_text())
        for fault, ok in [('changed-source', True), ('always-changing-source', False),
                          ('inventory-changed', False), ('count-changed', False)]:
            with self.subTest(fault=fault):
                world = dict(initial, collect_fault=fault)
                self.world.write_text(json.dumps(world))
                before = self.world.read_bytes()
                Path(self.env['OPEN_TICKETS_LOG']).unlink(missing_ok=True)
                self.out = self.root / fault
                result = self.run_cli('--snapshot-attempts', '3', ok=ok)
                self.assertEqual(self.world.read_bytes(), before)
                if ok:
                    report = json.loads((self.out / 'report.json').read_text())
                    self.assertEqual(report['read_attempts']['limit'], 3)
                    self.assertEqual(report['read_attempts']['used'], 2)
                    self.assertEqual(len(report['read_attempts']['refusals']), 1)
                    self.run_cli('--check')
                    report['read_attempts']['used'] = 4
                    (self.out / 'report.json').write_text(json.dumps(report))
                    self.assertIn('invalid read attempt history', self.run_cli('--check', ok=False).stderr)
                else:
                    self.assertFalse(self.out.exists())
                    self.assertIn('after 3 attempts', result.stderr)
                    if fault == 'count-changed':
                        self.assertIn('"expected": 4, "observed": 3', result.stderr)
                    else:
                        self.assertIn('"number": ' + ('9003' if fault == 'inventory-changed' else '9001'), result.stderr)
                    calls = [json.loads(line) for line in Path(self.env['OPEN_TICKETS_LOG']).read_text().splitlines()]
                    # The risk contract is at most three pairs, not six more
                    # hidden retries. Count this object's actual snapshot reads.
                    if fault in ['inventory-changed', 'count-changed']:
                        self.assertEqual(sum(call[-1] == 'repos/jparker2006/ClosedWiz/issues?state=open&per_page=100'
                                             for call in calls), 3 if fault == 'count-changed' else 6)
                    else:
                        self.assertEqual(sum(call[:3] == ['issue', 'view', '9001'] for call in calls), 6)

    def test_alias_policy_is_saved_bound_and_never_applied_to_metadata(self):
        account = 'synthetic' + 'account'
        self.literals.write_text(account + '\n')
        policy = dict(schema='openwiz.body-aliases.v1', mode='dry_run_only',
            authority='https://github.com/jparker2006/ClosedWiz/issues/1283#issuecomment-6711486946',
            literals_sha256=hashlib.sha256(self.literals.read_bytes()).hexdigest(), issues=[9002],
            roles={hashlib.sha256(account.encode()).hexdigest(): 'home_account'})
        path = self.root / 'aliases.json'
        path.write_text(json.dumps(policy))
        world = json.loads(self.world.read_text())
        world['move']['bodies']['9002'] = 'Use /home/' + account + '/work.'
        self.world.write_text(json.dumps(world))
        before = self.world.read_bytes()
        self.run_cli('--body-aliases', str(path))
        self.assertEqual(self.world.read_bytes(), before)
        rows = json.loads((self.out / 'operations.json').read_text())
        self.assertIn('Use ${HOME}/work.', rows[1]['new']['body'])
        proof = json.loads((self.out / 'provenance.json').read_text())
        self.assertEqual(proof['body_aliases'], policy)
        self.run_cli('--check')  # Saved run uses its bound policy, not a new input.
        proof['body_aliases']['roles'] = {}
        (self.out / 'provenance.json').write_text(json.dumps(proof))
        self.run_cli('--check', ok=False)
        for field in ['title', 'labels', 'milestone']:
            with self.subTest(field=field):
                bad = json.loads(before)
                bad['move']['graph']['items'][1][field] = [account] if field == 'labels' else account
                self.world.write_text(json.dumps(bad))
                self.out = self.root / field
                self.run_cli('--body-aliases', str(path), ok=False)
                rows = json.loads((self.out / 'operations.json').read_text())
                self.assertEqual(rows[1]['refusal'],
                    'privacy: O3 refused proposed title/body or did not establish literal coverage')
                self.assertEqual(self.world.read_text(), json.dumps(bad))

    def test_open_authorized_private_prerequisites_are_held_and_apply_stays_refused(self):
        # Planning may represent this edge without inventing a destination or
        # completion; the write path must continue to require actual completion.
        world = json.loads(self.world.read_text())
        world['move']['graph']['items'] += [
            dict(number=1257, kind='issue', title='Synthetic migration spec', labels=[], milestone=None,
                 parent=None, blockers=[], state='open'),
            dict(number=1283, kind='issue', title='Synthetic remaining work', labels=[], milestone=None,
                 parent=1257, blockers=[], state='open')]
        world['move']['bodies'].update({'1257': 'Synthetic migration.', '1283': 'Synthetic remaining work.'})
        world['move']['graph']['items'][1]['blockers'].append(1283)
        self.world.write_text(json.dumps(world))
        before = self.world.read_bytes()
        self.run_cli()
        self.assertEqual(self.world.read_bytes(), before)
        rows = json.loads((self.out / 'operations.json').read_text())
        held = dict(closedwiz=1283, url='https://github.com/jparker2006/ClosedWiz/issues/1283',
                    state='open', status='HELD')
        self.assertEqual(rows[1]['new']['held_prerequisites'], [held])
        self.assertEqual(rows[1]['new']['blockers'], [{'closedwiz': 9003}])
        self.assertIn('HELD private prerequisites: [ClosedWiz #1283](' + held['url'] + ') (state: open).',
                      rows[1]['new']['body'])
        report = json.loads((self.out / 'report.json').read_text())
        self.assertEqual(report['held_prerequisites'], [dict(held, dependents=[9002])])
        self.run_cli('--check')
        report['held_prerequisites'] = []
        (self.out / 'report.json').write_text(json.dumps(report))
        self.assertIn('held prerequisite report differs', self.run_cli('--check', ok=False).stderr)
        plan = self.root / 'apply-plan.json'
        proposal = world['move']
        proposal['graph']['exclude'] = [1257, 1283]
        del proposal['bodies']['1257'], proposal['bodies']['1283']
        plan.write_text(json.dumps(proposal))
        result = subprocess.run([sys.executable, '-I', str(HERE / 'move.py'), '--plan', str(plan),
            '--state-dir', str(self.root / 'state'), '--map-out', str(self.root / 'map'),
            '--checker', str(CHECKER), '--literals', str(self.literals), '--gh', str(HERE / 'fake-gh'), '--apply'],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('graph: open parent or blocker has no destination', result.stderr)
        self.assertEqual(self.world.read_bytes(), before)

    def test_stale_source_is_bound_and_reported_only_for_read_only_preparation(self):
        # Option B permits a complete read-only plan, never a current-approval claim.
        # Labels and closed-child states do not alter revision-v2's canonical text.
        initial = self.world.read_bytes()
        current = 'd599cda39d0013fc600d3de6f81d2d0151a64c7d0299da651424917280ffda34'
        for shape in ['labelled', 'unlabelled', 'closed-children']:
            with self.subTest(shape=shape):
                world = json.loads(initial)
                world['collect_fault'] = 'stale-approval'
                if shape != 'labelled':
                    world['move']['graph']['items'][0]['labels'].remove('spec')
                if shape == 'closed-children':
                    world['move']['graph']['items'][1]['state'] = 'closed'
                    world['move']['graph']['items'][2]['state'] = 'closed'
                self.world.write_text(json.dumps(world))
                before = self.world.read_bytes()
                self.out = self.root / shape
                self.run_cli()
                self.assertEqual(self.world.read_bytes(), before)
                report = json.loads((self.out / 'report.json').read_text())
                self.assertEqual(report['stale_approvals'], [dict(closedwiz=9001,
                    comment=9000000001, approved_fingerprint='0' * 64,
                    current_fingerprint=current, status='approval stale')])
                proof = json.loads((self.out / 'provenance.json').read_text())['approvals']['9001']
                self.assertEqual(proof, dict(comment=9000000001, fingerprint='0' * 64,
                    current_fingerprint=current, status='approval stale'))
                self.run_cli('--check')
                report['stale_approvals'] = []
                (self.out / 'report.json').write_text(json.dumps(report))
                self.assertIn('stale approval report differs', self.run_cli('--check', ok=False).stderr)

    def test_completed_and_not_planned_closures_use_records_without_carrying_edges(self):
        # A closed-without-PR prerequisite previously stopped the entire real run.
        # Exercise both approved dispositions at the saved CLI/artifact boundary.
        initial = json.loads(self.world.read_text())
        initial['move']['graph']['items'][1]['blockers'] += [9005]
        extra = dict(initial['move']['graph']['items'][-1], number=9005, state='closed')
        initial['move']['graph']['items'].append(extra)
        initial['state_reasons'] = {'9004': 'COMPLETED', '9005': 'NOT_PLANNED'}
        records = {}
        for n, body, superseded in [(9004, 'Completed: synthetic result accepted.', None),
                                    (9005, 'Superseded by #9010.', 9010)]:
            c = 9000000000 + n
            initial['comments'][str(n)] = [dict(id=c, body=body)]
            records[str(n)] = dict(comment=c, sha256=hashlib.sha256(body.encode()).hexdigest(),
                                   superseded_by=superseded)
        record_file = self.root / 'closure-records.json'
        record_file.write_text(json.dumps(records))
        self.world.write_text(json.dumps(initial))
        before = self.world.read_bytes()
        self.run_cli('--closure-records', str(record_file))
        self.assertEqual(self.world.read_bytes(), before)
        rows = json.loads((self.out / 'operations.json').read_text())
        new = rows[1]['new']
        self.assertEqual(new['blockers'], [{'closedwiz': 9003}])
        self.assertEqual(new['completed_blockers'], [9004])
        self.assertEqual(new['dropped_blockers'], [9005])
        self.assertIn('[completion record](https://github.com/jparker2006/ClosedWiz/issues/9004#issuecomment-9000009004)', new['body'])
        self.assertNotIn('/issues/9005', new['body'])
        report = json.loads((self.out / 'report.json').read_text())
        self.assertEqual(report['dropped_blockers'], [{'closedwiz': 9005, 'dependents': [9002],
            'record': 'https://github.com/jparker2006/ClosedWiz/issues/9005#issuecomment-9000009005',
            'superseded_by': 9010}])
        self.run_cli('--check')
        # A changed/foreign/unbound record cannot authorize dropping an edge.
        for fault in ['changed-record', 'unknown-reason', 'missing-record', 'reason-changed',
                      'missing-binding', 'unused-binding']:
            with self.subTest(fault=fault):
                world = json.loads(before)
                bindings = dict(records)
                if fault == 'changed-record':
                    world['comments']['9005'][0]['body'] += ' changed'
                elif fault == 'unknown-reason':
                    world['state_reasons']['9005'] = 'UNKNOWN'
                elif fault == 'reason-changed':
                    world['state_reasons']['9005'] = 'COMPLETED'
                elif fault == 'missing-binding':
                    del bindings['9005']
                elif fault == 'unused-binding':
                    bindings['9011'] = bindings['9005']
                else:
                    world['comments']['9005'] = []
                record_file.write_text(json.dumps(bindings))
                self.world.write_text(json.dumps(world))
                old = self.out
                self.out = self.root / fault
                try:
                    self.run_cli('--closure-records', str(record_file), ok=False)
                    self.assertFalse(self.out.exists())
                finally:
                    self.out = old

    def test_authorized_excluded_closures_are_neutral_and_provenance_is_required(self):
        # The actual mover PR closes an excluded ticket. Both authorized classes
        # need neutral private links, while carried issue closures still map.
        world = json.loads(self.world.read_text())
        world['move']['graph']['items'] += [
            dict(number=1257, kind='issue', title='Synthetic migration spec', labels=[], milestone=None,
                 parent=None, blockers=[], state='open'),
            dict(number=1283, kind='issue', title='Synthetic remaining ticket', labels=[], milestone=None,
                 parent=1257, blockers=[], state='open'),
            dict(number=9010, kind='pull_request', title='Synthetic in-flight PR', labels=[], milestone=None,
                 parent=None, blockers=[], state='open')]
        world['move']['bodies'].update({'1257': 'Synthetic migration.', '1283': 'Synthetic remaining work.',
            '9010': 'Closes #9002.\nFixes #1283.\nResolves https://github.com/jparker2006/ClosedWiz/issues/1257.'})
        world['move']['pulls'] = {'9010': dict(source_base='a' * 40, observed_base='a' * 40, source_head='b' * 40)}
        self.world.write_text(json.dumps(world))
        before = self.world.read_bytes()
        self.run_cli()
        self.assertEqual(self.world.read_bytes(), before)
        rows = json.loads((self.out / 'operations.json').read_text())
        body = rows[-1]['new']['body']
        self.assertIn('Closes ${openwiz:9002}.', body)
        for n in [1257, 1283]:
            self.assertIn(f'Related private issue [ClosedWiz #{n}](https://github.com/jparker2006/ClosedWiz/issues/{n})', body)
        self.assertNotIn('Fixes', body)
        self.assertNotIn('Resolves', body)
        self.run_cli('--check')
        provenance = json.loads((self.out / 'provenance.json').read_text())
        self.assertEqual(set(provenance['excluded_targets']), {'1257', '1283'})
        provenance['excluded_targets']['1283']['parent'] = 9001
        (self.out / 'provenance.json').write_text(json.dumps(provenance))
        self.assertIn('source: ambiguous excluded-target provenance', self.run_cli('--check', ok=False).stderr)
        for fault in ['unknown', 'wrapper', 'suffix', 'wrong-route', 'carried-pr-target', 'wrong-parent', 'wrong-kind']:
            with self.subTest(fault=fault):
                bad = json.loads(before)
                if fault == 'wrong-parent':
                    bad['move']['graph']['items'][-2]['parent'] = 9001
                elif fault == 'wrong-kind':
                    bad['move']['graph']['items'][-2]['kind'] = 'pull_request'
                else:
                    bad['move']['bodies']['9010'] = {'unknown': 'Closes #9999',
                        'wrapper': 'Fixes [private](https://github.com/jparker2006/ClosedWiz/issues/1283)',
                        'wrong-route': 'Fixes https://github.com/jparker2006/ClosedWiz/pull/1283',
                        'carried-pr-target': 'Fixes #9010',
                        'suffix': 'Fixes https://github.com/jparker2006/ClosedWiz/issues/1283#issuecomment-9000'}[fault]
                self.world.write_text(json.dumps(bad))
                self.out = self.root / fault
                result = self.run_cli(ok=False)
                if fault in ['wrong-parent', 'wrong-kind']:
                    expected = ('source: ambiguous migration child provenance' if fault == 'wrong-parent'
                                else 'source: excluded target is not an issue')
                    self.assertIn(expected, result.stderr)
                else:
                    rows = json.loads((self.out / 'operations.json').read_text())
                    expected = {'unknown': 'text: closing reference has no mapped destination',
                                'wrapper': 'text: unsupported closing-reference wrapper',
                                'suffix': 'text: unsupported closing-reference suffix or token',
                                'carried-pr-target': 'text: closing reference has no mapped destination',
                                'wrong-route': 'text: closing reference is not a source issue'}[fault]
                    self.assertEqual(rows[-1]['refusal'], expected)
                self.assertEqual(self.world.read_text(), json.dumps(bad))

if __name__ == '__main__':
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--checker', type=Path, default=CHECKER)
    options, rest = p.parse_known_args()
    CHECKER = options.checker
    unittest.main(argv=[sys.argv[0], *rest])
