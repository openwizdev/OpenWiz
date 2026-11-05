#!/usr/bin/env python3
"""X5: exercise real git diffs and signed synthetic maps, then validate plans."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'ci/select'))
import test_job as signing
import units


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


class Plans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('plan', HERE / 'plan.py')
        cls.plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plan)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 'test@example.invalid')
        git(self.root, 'config', 'user.name', 'Synthetic test')
        files = {
            'Cargo.toml': '[workspace]\nmembers=["crates/core", "tests"]\nresolver="2"\n',
            'crates/core/Cargo.toml': '[package]\nname="openwiz-core"\nversion="0.0.0"\n',
            'crates/core/src/lib.rs': '// synthetic\n',
            'tests/Cargo.toml': '[package]\nname="openwiz-tests"\nversion="0.0.0"\nautobins=false\nautotests=false\nautoexamples=false\nautobenches=false\n[[test]]\nname="checks"\npath="checks/main.rs"\n[[test]]\nname="proof"\npath="proof/main.rs"\n',
            'tests/checks/main.rs': '// synthetic checks\n',
            'tests/proof/main.rs': '// synthetic proof\n',
            'apps/web/test/unit/api.test.ts': '// synthetic unit\n',
            'skills/launch-fleet/scripts/fleet.sh': '# synthetic skill\n',
            'ci/hosted/guard.sh': '# synthetic guard\n',
            **{p: '# synthetic existing input\n' for p in ('docs/github-app.md', 'docs/ROADMAP.md',
                'tools/roadmap/generate.py', 'tools/privacy-check/check.py',
                'tools/factory-metrics/report.py', 'loops/synthetic.json', 'tools/open-tickets/test.sh', 'tools/live-check/core.py',
                'tools/ops-live/controls/kit.py', 'tools/ci-overload/alarm.py',
                'tools/ops-live/acceptance.py')},
            '.github/actions/docs-only/classify.sh': (HERE / 'classify.sh').read_text(),
            '.github/actions/docs-only/ci-reads.txt': 'private/synthetic.md\n',
        }
        for name, body in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        self.commit()
        self.base = git(self.root, 'rev-parse', 'HEAD')
        self.map = self.root.parent / 'map-cache'
        self.map.mkdir()
        mp = {'schema': 'openwiz.ci-select-map.v1', 'commit': self.base, 'units': {
            'rust:lib:openwiz-core': {'files': ['crates/core/src/lib.rs'], 'dirs': [], 'web_export': False},
            'rust:test:checks': {'files': ['tests/checks/main.rs'], 'dirs': [], 'web_export': False},
            'rust:test:proof': {'files': ['tests/proof/main.rs'], 'dirs': [], 'web_export': False},
            'web:unit:api': {'files': ['apps/web/test/unit/api.test.ts'], 'dirs': [], 'web_export': False},
        }}
        data = json.dumps(mp).encode()
        (self.map / 'map.json').write_bytes(data)
        (self.map / 'map.jwt').write_text(signing.sign(signing.claims(
            aud=signing.job.audience(data), sha=self.base), signing.KEY))
        self.change('skills/launch-fleet/scripts/fleet.sh')

    def commit(self):
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'synthetic fixture')

    def change(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as f:
            f.write('\n# synthetic change\n')
        self.commit()

    def run_plan(self, **over):
        run = dict(id=9000100, attempt=1, event='pull_request', action='synchronize',
                   base_branch='main', base=self.base, head=git(self.root, 'rev-parse', 'HEAD'), pull_request=909)
        run.update(over)
        live = dict(draft=False, base={'ref': run['base_branch'], 'sha': run['base']}, head={'sha': run['head']})
        record, dispatch = self.plan.build(self.root, run, live, self.map, signing.REPO,
                                           keys=signing.jwks(signing.KEY))
        self.assertEqual(self.plan.gate.escapes.refusals(json.dumps(record)), [])
        return record, dispatch

    def assert_full(self, record, code):
        self.assertEqual(record['selection']['mode'], 'full')
        self.assertIn(code, [r['code'] for r in record['selection']['reasons']])
        for lane in [record['lanes'][k] for k in ('always', 'rust', 'web', 'site')] + record['lanes']['skills']:
            self.assertEqual(lane['decision'], 'run')
            self.assertEqual(lane['skipped'], [])
        self.assertEqual(record['builds']['web_export']['decision'], 'run')

    def test_skill_only_has_always_and_one_skill_without_export(self):
        record, dispatch = self.run_plan()
        self.assertEqual(record['selection'], {'mode': 'selected'})
        self.assertEqual(record['builds']['web_export']['decision'], 'skip')
        for name in ('rust', 'web', 'site'):
            self.assertEqual(record['lanes'][name]['decision'], 'skip')
            self.assertTrue(record['lanes'][name]['reason'])
        running = [x['skill'] for x in record['lanes']['skills'] if x['decision'] == 'run']
        self.assertEqual(running, ['launch-fleet'])
        self.assertEqual(dispatch['skills'], ['launch-fleet'])
        self.assertEqual(record['lanes']['always']['tests'], ['always:fmt','always:classifier','always:selector','always:checks'])

    def test_selected_site_release_cut_keeps_every_planned_test(self):
        git(self.root, 'checkout', '-q', '--detach', self.base)
        site = self.root / 'apps/site/index.html'
        site.parent.mkdir(parents=True, exist_ok=True)
        site.write_text('synthetic site\n')
        self.commit()
        # A new unmeasured path must retain full fallback.
        record, _ = self.run_plan()
        self.assert_full(record, 'unknown_path')
        self.assertFalse(self.plan.combine_site_release(record))
        # Establish the modified input in the signed map's base, as a real
        # selected plan requires; no map edges or trust checks are removed.
        self.base = git(self.root, 'rev-parse', 'HEAD')
        mp = json.loads((self.map / 'map.json').read_text())
        mp['commit'] = self.base
        data = json.dumps(mp).encode()
        (self.map / 'map.json').write_bytes(data)
        (self.map / 'map.jwt').write_text(signing.sign(signing.claims(
            aud=signing.job.audience(data), sha=self.base), signing.KEY))
        self.change('apps/site/index.html')
        record, dispatch = self.run_plan()
        self.assertEqual(record['selection'], {'mode': 'selected'})
        self.assertTrue(self.plan.combine_site_release(record))
        self.assertTrue({'site:build', 'site:test', 'site:ci', 'release:install',
                         'release:package', 'release:ci2-batch-contract'} <= set(record['lanes']['site']['tests']))
        self.assertTrue(dispatch['site'])
        self.assertTrue(dispatch['release'])
        self.assertEqual(record['lanes']['always']['tests'],
                         ['always:fmt', 'always:classifier', 'always:selector', 'always:checks'])
        # Exercise the actual output writer with the same signed fixture.
        # Only the live PR read and JWKS acquisition are synthetic transport.
        home = self.root.parent / 'home'
        cache = home / '.cache/closedwiz-ci-select'
        cache.parent.mkdir(parents=True)
        cache.symlink_to(self.map, target_is_directory=True)
        head = git(self.root, 'rev-parse', 'HEAD')
        event = dict(action='synchronize', number=909,
                     pull_request=dict(base={'ref': 'main', 'sha': self.base}, head={'sha': head}))
        live = dict(draft=False, base={'ref': 'main', 'sha': self.base}, head={'sha': head})
        event_path = home / 'event.json'
        output = home / 'output'
        summary = home / 'summary'
        env = dict(HOME=str(home), GITHUB_EVENT_PATH=str(event_path), GITHUB_EVENT_NAME='pull_request',
                   GITHUB_RUN_ID='9000100', GITHUB_RUN_ATTEMPT='1', GITHUB_REPOSITORY=signing.REPO,
                   GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary),
                   GITHUB_REF_NAME='main', GITHUB_SHA=head)
        original = subprocess.check_output
        def transport(args, **kwargs):
            if args[:3] == ['sh', 'ci/retry.sh', '3']:
                return json.dumps(live)
            return original(args, **kwargs)
        for full in (False, True):
            event_path.write_text(json.dumps({'before': self.base} if full else event))
            output.write_text('')
            env['GITHUB_EVENT_NAME'] = 'push' if full else 'pull_request'
            with mock.patch.dict(os.environ, env), mock.patch.object(self.plan, 'ROOT', self.root), \
                 mock.patch.object(self.plan.job, 'fetch_jwks', return_value=signing.jwks(signing.KEY)), \
                 mock.patch.object(subprocess, 'check_output', side_effect=transport), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.plan.main([str(home / 'plan')])
            emitted = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertIs(json.loads(emitted['site-in-release']), not full)
            persisted = json.loads((home / 'plan/ci-dispatch.json').read_text())
            self.assertNotIn('site-in-release', persisted)
        for context in ({'attempt': 2}, {'action': 'ready_for_review'},
                        {'base_branch': 'release-0.1'},
                        {'event': 'push', 'action': None, 'pull_request': None},
                        {'event': 'schedule', 'action': None, 'pull_request': None, 'base': None},
                        {'event': 'merge_group', 'action': None, 'pull_request': None}):
            with self.subTest(context=context):
                full, _ = self.run_plan(**context)
                self.assertEqual(full['selection']['mode'], 'full')
                self.assertFalse(self.plan.combine_site_release(full))

    def test_release_readers_run_for_selected_doc_and_tool_changes(self):
        # Existing modified inputs are not map-owned; the release suites,
        # rather than the Rust map, own this observable dependency contract.
        for path in ('docs/github-app.md', 'docs/ROADMAP.md', 'tools/roadmap/generate.py',
                     'tools/privacy-check/check.py', 'tools/factory-metrics/report.py', 'loops/synthetic.json',
                     'tools/open-tickets/test.sh'):
            with self.subTest(path=path):
                git(self.root, 'checkout', '-q', '--detach', self.base)
                self.change(path)
                record, dispatch = self.run_plan()
                self.assertEqual(record['selection'], {'mode': 'selected'})
                self.assertEqual(record['diff']['paths'], [path])
                self.assertTrue(dispatch['release'], path)
                self.assertIn('release:open-tickets',record['lanes']['site']['tests'])
                self.assertIn('release:security-baseline',record['lanes']['site']['tests'])
                self.assertIn('release:ci2-batch-contract',record['lanes']['site']['tests'])
                self.assertTrue(set(self.plan.RELEASE) <= set(record['lanes']['site']['tests']))

    def test_ops_live_controls_is_in_full_and_affected_plans(self):
        path = 'tools/ops-live/controls/kit.py'
        for mode in ('full', 'selected'):
            with self.subTest(mode=mode):
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                else:
                    git(self.root, 'checkout', '-q', '--detach', self.base)
                    self.change(path)
                    record, dispatch = self.run_plan()
                    self.assertEqual(record['diff']['paths'], [path])
                self.assertEqual(record['selection']['mode'], mode)
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ops-live-controls'), 1)

    def test_ops_live_acceptance_is_in_full_and_affected_plans(self):
        path = 'tools/ops-live/acceptance.py'
        for mode in ('full', 'selected'):
            with self.subTest(mode=mode):
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                else:
                    git(self.root, 'checkout', '-q', '--detach', self.base)
                    self.change(path)
                    record, dispatch = self.run_plan()
                    self.assertEqual(record['diff']['paths'], [path])
                self.assertEqual(record['selection']['mode'], mode)
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ops-live-acceptance'), 1)

    def test_ci2_overload_registered_in_full_and_affected_plans(self):
        for mode in ('full', 'selected'):
            with self.subTest(mode=mode):
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                else:
                    self.change('tools/ci-overload/alarm.py')
                    record, dispatch = self.run_plan()
                self.assertEqual(record['selection']['mode'], mode)
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-overload'), 1)

    def test_ci2_read_contract_is_in_full_and_affected_plans(self):
        # C1-CI: registration survives selected readers and unknown-path fallback.
        for mode in ('full', 'affected', 'new-validator'):
            with self.subTest(mode=mode):
                git(self.root, 'checkout', '-q', '--detach', self.base)
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                elif mode == 'affected':
                    self.change('docs/github-app.md')
                    record, dispatch = self.run_plan()
                    self.assertEqual(record['selection'], {'mode': 'selected'})
                else:
                    self.change('tools/github-reads/test_contract.py')
                    record, dispatch = self.run_plan()
                    self.assert_full(record, 'unknown_path')
                    self.assertIn('tools/github-reads/test_contract.py', record['diff']['paths'])
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-read-contract'), 1)

    def test_ci2_shared_reads_is_in_full_and_affected_plans(self):
        # C8-CI: the shared read helper's proofs run wherever the read contract runs.
        for mode in ('full', 'affected', 'helper'):
            with self.subTest(mode=mode):
                git(self.root, 'checkout', '-q', '--detach', self.base)
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                elif mode == 'affected':
                    self.change('docs/github-app.md')
                    record, dispatch = self.run_plan()
                    self.assertEqual(record['selection'], {'mode': 'selected'})
                else:
                    self.change('tools/github-reads/read.py')
                    record, dispatch = self.run_plan()
                    self.assert_full(record, 'unknown_path')
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-shared-reads'), 1)

    def test_ci2_read_consumers_is_in_full_and_affected_plans(self):
        # C10-CI: the participating readers' routing proofs run wherever the helper's do.
        for mode in ('full', 'affected', 'consumer'):
            with self.subTest(mode=mode):
                git(self.root, 'checkout', '-q', '--detach', self.base)
                if mode == 'full':
                    record, dispatch = self.run_plan(attempt=2)
                elif mode == 'affected':
                    self.change('docs/github-app.md')
                    record, dispatch = self.run_plan()
                    self.assertEqual(record['selection'], {'mode': 'selected'})
                else:
                    self.change('tools/github-reads/test_consumers.py')
                    record, dispatch = self.run_plan()
                    self.assert_full(record, 'unknown_path')
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-read-consumers'), 1)

    def use_fixture_planner(self, carried):
        # O16-P-RETIRED (#2429): release:ci2-spending depends on whether the
        # planner's own tree carries tools/ci-overflow/test.py, so both cases
        # run plan.py from inside the fixture tree, never from this checkout
        # (the public tree leaves that retiring file out).
        here = self.root / '.github/actions/docs-only'
        (here / 'plan.py').write_text((HERE / 'plan.py').read_text())
        if carried:
            (self.root / 'tools/ci-overflow').mkdir(parents=True, exist_ok=True)
            (self.root / 'tools/ci-overflow/test.py').write_text('# synthetic retiring check\n')
        self.assertEqual((self.root / 'tools/ci-overflow/test.py').is_file(), carried)
        spec = importlib.util.spec_from_file_location('plan_in_fixture', here / 'plan.py')
        planner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(planner)
        saved, self.plan = self.plan, planner
        self.addCleanup(setattr, self, 'plan', saved)

    def test_ci2_spending_is_registered_in_full_and_affected_plans(self):
        self.use_fixture_planner(carried=True)
        self.change('tools/ci-overflow/overflow.py')
        for overrides in ({}, {'attempt': 2}):
            with self.subTest(overrides=overrides):
                record, dispatch = self.run_plan(**overrides)
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-spending'), 1)

    def test_ci2_spending_is_not_registered_where_its_retiring_tool_is_absent(self):
        # The public tree neither discovers (the RELEASE literal the staged
        # route reads) nor plans release:ci2-spending. Every other release id
        # stays planned even with its command target missing, so it still
        # fails the lane: the rule is this one id only.
        import ast
        self.use_fixture_planner(carried=False)
        self.change('tools/ci-overflow/overflow.py')
        discovered = next(ast.literal_eval(n.value) for n in ast.parse((HERE / 'plan.py').read_text()).body
                          if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RELEASE')
        self.assertNotIn('release:ci2-spending', discovered)
        missing_targets = {'release:ci2-overload': 'tools/ci-overload/test.py',
                           'release:ci2-shared-reads': 'tools/github-reads/test_read.py',
                           'release:ci2-read-consumers': 'tools/github-reads/test_consumers.py',
                           'release:test': 'tools/release/test.py'}
        for path in missing_targets.values():
            self.assertFalse((self.root / path).exists(), path)
        for overrides in ({}, {'attempt': 2}):
            with self.subTest(overrides=overrides):
                record, dispatch = self.run_plan(**overrides)
                self.assertTrue(dispatch['release'])
                site = record['lanes']['site']
                self.assertEqual(site['tests'].count('release:ci2-spending'), 0)
                self.assertNotIn('release:ci2-spending', [s['test'] for s in site['skipped']])
                self.assertEqual(sorted(t for t in site['tests'] if t.startswith('release:')), sorted(discovered))
                for test in missing_targets:
                    self.assertEqual(site['tests'].count(test), 1, test)

    def test_ci2_batch_contract_is_registered_in_full_plans(self):
        record, dispatch = self.run_plan(event='push', action=None, pull_request=None)
        self.assertTrue(dispatch['release'])
        self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-batch-contract'), 1)

    def test_ci2_batch_shadow_is_registered_for_full_push_and_nightly(self):
        for event in ('push', 'schedule', 'merge_group'):
            with self.subTest(event=event):
                record, dispatch = self.run_plan(event=event, action=None, pull_request=None)
                self.assertTrue(dispatch['release'])
                self.assertEqual(record['lanes']['site']['tests'].count('release:ci2-batch-shadow'), 1)

    def test_restoring_the_map_tree_after_main_drift_is_a_valid_full_run(self):
        path='skills/launch-fleet/scripts/fleet.sh'
        git(self.root, 'checkout', '-q', '-B', 'synthetic-main', self.base)
        self.change(path)
        newer_base=git(self.root, 'rev-parse', 'HEAD')
        git(self.root, 'checkout', '-qb', 'synthetic-pr')
        (self.root/path).write_text(git(self.root, 'show', self.base+':'+path)+'\n')
        self.commit()
        pr_head=git(self.root, 'rev-parse', 'HEAD')
        git(self.root, 'checkout', '-q', 'synthetic-main')
        git(self.root, 'merge', '--no-ff', '-qm', 'synthetic GitHub merge ref', 'synthetic-pr')
        self.assertEqual(git(self.root, 'diff', '--name-only', self.base, 'HEAD'), '')
        record, dispatch=self.run_plan(base=newer_base, head=pr_head)
        self.assert_full(record, 'selector_error')
        self.assertEqual(record['diff'], {'state':'read','paths':[path]})
        self.assertNotIn('empty_diff', [r['code'] for r in record['selection']['reasons']])
        self.assertIn('map-to-tested', record['selection']['reasons'][0]['detail'])
        self.assertTrue(dispatch['release'])

    def test_toolkit_requirement_is_planned_without_inventing_a_rust_test(self):
        record, dispatch=self.run_plan()
        self.assertFalse(dispatch['toolkit'])
        self.change('docs/github-app.md')
        record, dispatch=self.run_plan()
        self.assertEqual(record['selection'], {'mode':'selected'})
        self.assertEqual(record['lanes']['rust']['decision'], 'skip')
        self.assertFalse(dispatch['toolkit'])
        self.change('tools/live-check/core.py')
        record,dispatch=self.run_plan()
        self.assertTrue(dispatch['toolkit'])
        self.assertFalse(dispatch['export-rust'])
        record, dispatch=self.run_plan(attempt=2)
        self.assert_full(record, 'rerun')
        self.assertTrue(dispatch['toolkit'])

    def test_every_full_event_and_rerun_selects_everything(self):
        cases = [({'event': 'push', 'action': None, 'pull_request': None}, 'push_main'),
                 ({'event': 'schedule', 'action': None, 'pull_request': None, 'base': None}, 'nightly'),
                 ({'event': 'merge_group', 'action': None, 'pull_request': None}, 'merge_group'),
                 ({'attempt': 2}, 'rerun'), ({'base_branch': 'release-0.1'}, 'release_branch'),
                 ({'action': 'ready_for_review'}, 'ready_for_review')]
        for context, code in cases:
            with self.subTest(code=code):
                record, _ = self.run_plan(**context)
                self.assert_full(record, code)

    def test_checks_source_requests_lint_without_another_rust_test_lane(self):
        self.change('tests/checks/main.rs')
        record,dispatch=self.run_plan()
        self.assertEqual(record['lanes']['rust']['decision'],'skip')
        self.assertTrue(dispatch['lint-rust'])

    def test_runner_guard_drift_since_the_map_forces_every_lane(self):
        self.change('ci/hosted/guard.sh')
        newer_base=git(self.root,'rev-parse','HEAD')
        self.change('skills/launch-fleet/scripts/fleet.sh')
        record,_=self.run_plan(base=newer_base)
        self.assert_full(record,'ci_change')
        reason=next(r for r in record['selection']['reasons'] if r['code']=='ci_change')
        self.assertIn('ci/hosted/guard.sh',reason['paths'])

    def test_a_changed_runner_guard_forces_every_lane(self):
        self.change('ci/hosted/guard.sh')
        record,_=self.run_plan()
        self.assert_full(record,'ci_change')

    def test_full_pr_attempt_keeps_tracer_and_planted_edit_proofs(self):
        self.change('ci/select/map.json')
        self.change('ci/select/planted.py')
        self.change('ci/select/trace.py')
        for context in ({'attempt':2},{'action':'ready_for_review'},{'base_branch':'release-0.1'}):
            with self.subTest(context=context):
                record,dispatch=self.run_plan(**context)
                self.assertEqual(record['selection']['mode'],'full')
                self.assertTrue(dispatch['trace'])
                self.assertTrue(dispatch['planted'])

    def test_unknown_empty_failed_and_ci_diffs_select_everything(self):
        self.change('new-unmapped/future.txt')
        record, _ = self.run_plan()
        self.assert_full(record, 'unknown_path')
        record, _ = self.run_plan(head=self.base)
        self.assert_full(record, 'empty_diff')
        record, _ = self.run_plan(head='f' * 40)
        self.assert_full(record, 'failed_diff')
        self.change('.github/actions/docs-only/classify.sh')
        record, _ = self.run_plan()
        self.assert_full(record, 'ci_change')

    def test_draft_unreadable_or_stale_live_identity_cannot_narrow(self):
        run=dict(id=9000100,attempt=1,event='pull_request',action='opened',base_branch='main',
                 base=self.base,head=git(self.root,'rev-parse','HEAD'),pull_request=909)
        for live in (None,{'draft':'false'},{'draft':True,'base':{},'head':{}}):
            with self.assertRaises(ValueError):
                self.plan.build(self.root,run,live,self.map,signing.REPO,keys=signing.jwks(signing.KEY))
        stale={'draft':False,'base':{'ref':'main','sha':self.base},'head':{'sha':'0'*40}}
        record,_=self.plan.build(self.root,run,stale,self.map,signing.REPO,keys=signing.jwks(signing.KEY))
        self.assert_full(record,'stale_event')

    def test_unsigned_map_and_missing_metadata_cannot_narrow(self):
        (self.map / 'map.jwt').write_text('untrusted')
        record, _ = self.run_plan()
        self.assert_full(record, 'selector_error')

    def test_changed_input_invalidates_a_negative_export_trace(self):
        self.change('tests/proof/main.rs')
        record, dispatch = self.run_plan()
        self.assertEqual(record['lanes']['rust']['tests'], ['rust:test:proof'])
        self.assertTrue(dispatch['export-rust'])
        self.assertEqual(record['builds']['web_export']['decision'], 'run')
        mp = json.loads((self.map / 'map.json').read_text())
        del mp['units']['rust:test:proof']['web_export']
        data = json.dumps(mp).encode()
        (self.map / 'map.json').write_bytes(data)
        (self.map / 'map.jwt').write_text(signing.sign(signing.claims(aud=signing.job.audience(data), sha=self.base), signing.KEY))
        record, dispatch = self.run_plan()
        self.assertTrue(dispatch['export-rust'])
        self.assertEqual(record['builds']['web_export']['decision'], 'run')


if __name__ == '__main__':
    unittest.main()
