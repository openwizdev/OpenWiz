#!/usr/bin/env python3
"""X5: exercise real git diffs and the path table (#1486), then validate plans.

FF5's (#1335) selection rules and planted cases, carried over as #1486's
acceptance tests: each on a synthetic repository through plan.build, and the
planted cases on this tree's own table and tests.
"""
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
sys.path.insert(0, str(HERE))
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
            'tests/Cargo.toml': '[package]\nname="openwiz-tests"\nversion="0.0.0"\nautobins=false\nautotests=false\nautoexamples=false\nautobenches=false\n[[test]]\nname="checks"\npath="checks/main.rs"\n[[test]]\nname="proof"\npath="proof/main.rs"\n[[test]]\nname="fleet"\npath="fleet/main.rs"\n',
            'tests/checks/main.rs': '// synthetic checks\n',
            'tests/proof/main.rs': '// synthetic proof\n',
            'tests/fleet/main.rs': '// synthetic fleet\n',
            'docs/agents/fleet.md': 'synthetic\n', 'wizskills.lock': '{}\n', 'STATUS.md': 'synthetic\n',
            '.claude/skills/old/SKILL.md': 'synthetic\n', 'README.md': 'synthetic\n',
            'skills': 'a synthetic stand-in for the link to the installed skills\n',
            'ci/hosted/guard.sh': '# synthetic guard\n',
            **{p: '# synthetic existing input\n' for p in ('docs/github-app.md', 'docs/ROADMAP.md',
                'tools/roadmap/generate.py', 'tools/privacy-check/check.py',
                'tools/war-room/report.py', 'loops/synthetic.json',
                'tools/ci-overload/alarm.py')},
            '.github/actions/docs-only/classify.sh': (HERE / 'classify.sh').read_text(),
            '.github/actions/docs-only/ci-reads.txt': 'private/synthetic.md\n',
        }
        for name, body in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        self.commit()
        self.base = git(self.root, 'rev-parse', 'HEAD')
        self.change('docs/ROADMAP.md')

    def commit(self):
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'synthetic fixture')

    def change(self, *names):
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a') as f:
                f.write('\n# synthetic change\n')
        self.commit()

    def plan_for(self, *names):
        git(self.root, 'checkout', '-q', '--detach', self.base)
        self.change(*names)
        return self.run_plan()[0]

    def run_plan(self, **over):
        run = dict(id=9000100, attempt=1, event='pull_request', action='synchronize',
                   base_branch='main', base=self.base, head=git(self.root, 'rev-parse', 'HEAD'), pull_request=909)
        run.update(over)
        live = dict(draft=False, base={'ref': run['base_branch'], 'sha': run['base']}, head={'sha': run['head']})
        record, dispatch = self.plan.build(self.root, run, live)
        self.assertEqual(self.plan.gate.escapes.refusals(json.dumps(record)), [])
        return record, dispatch

    def assert_full(self, record, code):
        self.assertEqual(record['selection']['mode'], 'full')
        self.assertIn(code, [r['code'] for r in record['selection']['reasons']])
        for lane in [record['lanes'][k] for k in ('always', 'rust', 'site')] + record['lanes']['skills']:
            self.assertEqual(lane['decision'], 'run')
            self.assertEqual(lane['skipped'], [])
        # #1264: the web view and its export went; even a full run skips them.
        self.assertEqual(record['lanes']['web']['decision'], 'skip')
        self.assertEqual(record['builds']['web_export']['decision'], 'skip')

    # FF5's (#1335) selection rules, by path (#1486).
    def rust(self, record):
        lane = record['lanes']['rust']
        return lane['tests'] if lane['decision'] == 'run' else []

    def test_a_docs_skills_or_unread_only_pr_runs_no_rust_test(self):
        # catches: a docs-only, skills-only or unread-only PR (new files too) running the Rust lane.
        for edits in (('docs/ROADMAP.md', 'docs/cleanup/new-table.md', 'NOTES.md', 'README.md'),
                      ('.claude/skills/old/SKILL.md', '.claude/skills/new/SKILL.md', '.agents/skills/new/x'),
                      ('STATUS.md', 'private/notes/new.md')):
            with self.subTest(edits):
                record = self.plan_for(*edits)
                self.assertEqual(record['selection'], {'mode': 'selected'})
                self.assertEqual(record['lanes']['rust']['decision'], 'skip')
                self.assertEqual(record['lanes']['always']['decision'], 'run')

    def test_a_doc_pin_or_link_a_rust_test_reads_runs_only_that_test(self):
        # catches: the docs and skills skip dropping a named reader, or widening to the whole lane.
        for edit in ('docs/agents/fleet.md', 'wizskills.lock', 'skills'):
            with self.subTest(edit):
                record = self.plan_for(edit)
                self.assertEqual(self.rust(record), ['rust:test:fleet'])
                # catches (#1612 R1): a WizSkills pin move or a changed skills link skipping the
                # skill suites, which run from the pinned release.
                suites = {lane['skill']: lane['decision'] for lane in record['lanes']['skills']}
                self.assertEqual(suites, dict.fromkeys(suites, 'skip' if edit.startswith('docs/') else 'run'))

    def test_a_code_path_runs_every_rust_test_but_the_always_lane_s(self):
        # catches: a source, test or fixture change, new or modified, skipping a Rust test.
        every = ['rust:lib:openwiz-core', 'rust:test:fleet', 'rust:test:proof']
        for edit in ('crates/core/src/lib.rs', 'crates/core/src/brand_new.rs', 'tests/fixtures/new.json',
                     'tests/proof/main.rs', 'contracts/x.v1.md', 'loops/synthetic.json'):
            with self.subTest(edit):
                record = self.plan_for(edit, 'docs/ROADMAP.md')
                self.assertEqual(record['selection'], {'mode': 'selected'})
                self.assertEqual(self.rust(record), every)

    def test_a_path_no_row_knows_runs_everything(self):
        # catches: a class pattern loose enough to narrow a new folder, a lookalike or a link's neighbour.
        for path in ('new-unmapped/future.txt', 'docsx/new.md', 'apps/webx/new.md', '.claude/settings.json',
                     '.claude/skillsx/new', 'skills2/new.md', 'deployx/notes.md', 'ci/shard/new.py'):
            with self.subTest(path):
                record = self.plan_for(path, 'docs/ROADMAP.md')
                self.assert_full(record, 'unknown_path')
                self.assertEqual(record['selection']['reasons'], [{'code': 'unknown_path', 'paths': [path]}])

    def test_a_named_reader_missing_from_the_tree_runs_everything(self):
        # catches: a renamed or removed test target silently dropping a doc's only reader.
        cargo = self.root / 'tests/Cargo.toml'
        cargo.write_text(cargo.read_text().replace('[[test]]\nname="fleet"\npath="fleet/main.rs"\n', ''))
        self.commit()
        self.base = git(self.root, 'rev-parse', 'HEAD')
        record = self.plan_for('docs/agents/fleet.md')
        self.assert_full(record, 'selector_error')
        self.assertIn('rust:test:fleet', record['selection']['reasons'][0]['detail'])


    def test_selected_release_cut_keeps_every_planned_test(self):
        git(self.root, 'checkout', '-q', '--detach', self.base)
        release = self.root / 'tools/release/synthetic.py'
        release.parent.mkdir(parents=True, exist_ok=True)
        release.write_text('# synthetic release proof\n')
        self.commit()
        record, dispatch = self.run_plan()
        self.assertEqual(record['selection'], {'mode': 'selected'})
        self.assertTrue({'release:install', 'release:package', 'release:ci2-batch-contract'}
                        <= set(record['lanes']['site']['tests']))
        self.assertFalse([t for t in record['lanes']['site']['tests'] if t.startswith('site:')])
        self.assertTrue(dispatch['release'])
        self.assertEqual(record['lanes']['always']['tests'],
                         ['always:fmt', 'always:classifier', 'always:selector', 'always:checks'])
        # Exercise the actual output writer. Only the live PR read is synthetic transport.
        home = self.root.parent / 'home'
        home.mkdir()
        head = git(self.root, 'rev-parse', 'HEAD')
        event = dict(action='synchronize', number=909,
                     pull_request=dict(base={'ref': 'main', 'sha': self.base}, head={'sha': head}))
        live = dict(draft=False, base={'ref': 'main', 'sha': self.base}, head={'sha': head})
        event_path = home / 'event.json'
        output = home / 'output'
        summary = home / 'summary'
        env = dict(HOME=str(home), GITHUB_EVENT_PATH=str(event_path), GITHUB_EVENT_NAME='pull_request',
                   GITHUB_RUN_ID='9000100', GITHUB_RUN_ATTEMPT='1', GITHUB_REPOSITORY='synthetic/repo',
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
                 mock.patch.object(subprocess, 'check_output', side_effect=transport), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.plan.main([str(home / 'plan')])
            emitted = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertNotIn('site-in-release', emitted)
            # #743: launch-fleet runs in its own sharded job, never also in the skills matrix.
            skills, jobs = json.loads(emitted['skills']), json.loads(emitted['skill-jobs'])
            self.assertEqual(jobs, [s for s in skills if s != 'launch-fleet'])
            if full:
                self.assertIn('launch-fleet', skills)
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

    def test_release_readers_run_for_selected_doc_and_tool_changes(self):
        # Existing modified inputs are not map-owned; the release suites,
        # rather than the Rust map, own this observable dependency contract.
        for path in ('docs/github-app.md', 'docs/ROADMAP.md', 'tools/roadmap/generate.py',
                     'tools/privacy-check/check.py', 'tools/war-room/report.py', 'loops/synthetic.json'):
            with self.subTest(path=path):
                git(self.root, 'checkout', '-q', '--detach', self.base)
                self.change(path)
                record, dispatch = self.run_plan()
                self.assertEqual(record['selection'], {'mode': 'selected'})
                self.assertEqual(record['diff']['paths'], [path])
                self.assertTrue(dispatch['release'], path)
                self.assertIn('release:security-baseline',record['lanes']['site']['tests'])
                self.assertIn('release:ci2-batch-contract',record['lanes']['site']['tests'])
                self.assertTrue(set(self.plan.RELEASE) <= set(record['lanes']['site']['tests']))

    def test_every_full_event_and_rerun_selects_everything(self):
        cases = [({'event': 'push', 'action': None, 'pull_request': None}, 'push_main'),
                 ({'event': 'schedule', 'action': None, 'pull_request': None, 'base': None}, 'nightly'),
                 ({'event': 'merge_group', 'action': None, 'pull_request': None}, 'merge_group'),
                 ({'attempt': 2}, 'rerun'), ({'base_branch': 'release-0.1'}, 'release_branch'),
                 ({'action': 'ready_for_review'}, 'ready_for_review')]
        for context, code in cases:
            with self.subTest(code=code):
                record, dispatch = self.run_plan(**context)
                self.assert_full(record, code)
                # catches (#1486): a main push or the nightly run losing the always, rust and
                # ci jobs' full-main mode (their `trace` gate), or a PR gaining it.
                self.assertEqual(dispatch['trace'], code in ('push_main', 'nightly'))
                self.assertFalse(dispatch['planted'])

    def test_checks_source_requests_lint_without_another_rust_test_lane(self):
        self.change('tests/checks/main.rs')
        record,dispatch=self.run_plan()
        self.assertEqual(record['lanes']['rust']['decision'],'skip')
        self.assertTrue(dispatch['lint-rust'])

    def test_a_changed_runner_guard_forces_every_lane(self):
        self.change('ci/hosted/guard.sh')
        record,_=self.run_plan()
        self.assert_full(record,'ci_change')

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
                self.plan.build(self.root,run,live)
        stale={'draft':False,'base':{'ref':'main','sha':self.base},'head':{'sha':'0'*40}}
        record,_=self.plan.build(self.root,run,stale)
        self.assert_full(record,'stale_event')


# Planted cases (CI3's anti-gaming rule; FF5's planted.py CASES, with no
# tracer): a real edit in this tree, the path a diff shows for it, and the
# test that catches it (run 42330800061, and #1335's two). The table must
# narrow the plan and still run the catcher. rust:test:checks, the always
# lane's, runs in every plan. The two #1335 cases are the skip rules' own.
PLANTED = [
    ('tests/fixtures/envelopes/ls-long-complete.json', '"schema": "openwiz.inventory.v1",', None, 'rust:test:checks'),
    ('crates/adapters/github/src/fleets.rs', 'fn allows(argv: &[&str]) -> bool {', None, 'rust:test:fleet'),
    ('contracts/attachment.v1.schema.json', '"maxLength": 64,', None, 'rust:test:attachments'),
    ('docs/agents/fleet.md', '\n## Builder for small tickets\n', None, 'rust:test:fleet'),
    ('skills/setup/templates/fleet.md', '\n## Reviewer for GPT-built\n', 'wizskills.lock', 'rust:test:fleet'),
    ('tests/checks/main.rs', 'mod ', None, 'rust:test:checks'),
]


class Planted(unittest.TestCase):
    def test_every_planted_edit_still_selects_its_catcher(self):
        # catches: a path table row that skips the test reading a planted edit's file.
        spec = importlib.util.spec_from_file_location('plan', HERE / 'plan.py')
        plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plan)
        inventory = sorted(units.list_units(ROOT))
        for path, old, seen_as, catcher in PLANTED:
            with self.subTest(path):
                self.assertGreaterEqual((ROOT / path).read_text().count(old), 1, 'the planted edit is gone')
                self.assertIn(catcher, inventory)
                tests, unknown = plan.rust_tests(ROOT, [seen_as or path], inventory)
                self.assertEqual(unknown, [])
                self.assertTrue(catcher in tests or catcher == 'rust:test:checks', sorted(tests))


if __name__ == '__main__':
    unittest.main()
