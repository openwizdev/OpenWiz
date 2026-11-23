#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHECK = HERE / 'check.py'
FIXTURES = HERE / 'fixtures'

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
log = os.environ['FAKE_GH_LOG']
with open(log, 'a') as f:
    f.write(json.dumps(args) + '\n')
s = json.load(open(os.environ['FAKE_GH_SCENARIO']))
if args[:2] != ['api', 'graphql']:
    sys.exit('fake gh: only graphql reads: ' + ' '.join(args))
fields = dict(a.split('=', 1) for a in args[2:] if '=' in a)
query = fields['query']
if 'pullRequest(' in query:
    if s['pr'] is None:
        sys.exit('fake gh: not found')
    pr = dict(s['pr'])
    pages = pr.pop('files')
    after = fields.get('files', '')
    cursors = [None] + [p['pageInfo']['endCursor'] for p in pages]
    i = cursors.index(after or None) if (after or None) in cursors else len(pages)
    pr['files'] = pages[i] if i < len(pages) else {'pageInfo': {'hasNextPage': False, 'endCursor': after}, 'nodes': []}
    if fields.get('comments'):
        pr['comments'] = {'pageInfo': {'hasNextPage': False, 'endCursor': fields['comments']}, 'nodes': []}
    print(json.dumps({'data': {'repository': {'pullRequest': pr}}}))
elif 'issueOrPullRequest(' in query:
    node = s['issues'].get(fields['number'])
    if node is None:
        sys.exit('fake gh: not found')
    print(json.dumps({'data': {'repository': {'issueOrPullRequest': node}}}))
elif 'object(' in query:
    print(json.dumps({'data': {'repository': {'object': {'text': open(os.environ['FAKE_GH_FLEET']).read()}}}}))
else:
    sys.exit('fake gh: unknown query')
'''


def run(scenario, data=None):
    data = data or json.loads((FIXTURES / f'{scenario}.json').read_text())
    fleet = data.get('fleet')
    fleet = HERE.parents[1] / fleet if fleet else FIXTURES / 'fleet.md'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'scenario.json').write_text(json.dumps(data))
        (tmp / 'gh').write_text(FAKE_GH)
        (tmp / 'gh').chmod(0o755)
        env = dict(os.environ, PATH=f'{tmp}{os.pathsep}{os.environ["PATH"]}',
                   FAKE_GH_SCENARIO=str(tmp / 'scenario.json'),
                   FAKE_GH_FLEET=str(fleet), FAKE_GH_LOG=str(tmp / 'log'))
        r = subprocess.run([sys.executable, '-I', str(CHECK), '--repo', 'example/project', '--pr', '42'],
                           capture_output=True, text=True, env=env, timeout=60)
        calls = [json.loads(l) for l in (tmp / 'log').read_text().splitlines()] if (tmp / 'log').exists() else []
        return r, calls


class Check(unittest.TestCase):
    def verdict(self, scenario, s=None):
        s = s or json.loads((FIXTURES / f'{scenario}.json').read_text())
        r, calls = run(scenario, s)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, s['exit'], out)
        for line in s['out']:
            self.assertIn(line, out)
        for line in s.get('absent', []):
            self.assertNotIn(line, out)
        for call in calls:
            self.assertEqual(call[:2], ['api', 'graphql'], 'every read is GraphQL')
        return out

    def test_a_file_outside_the_owned_paths_fails_naming_file_and_ticket(self):
        self.verdict('outside')

    def test_files_inside_owned_paths_shared_paths_and_globs_pass(self):
        self.verdict('inside')

    def test_record_author_grants_cover_their_paths_and_no_one_elses_do(self):
        self.verdict('grants')

    def test_the_standing_supporting_edit_rule_covers_its_paths_only(self):
        self.verdict('standing')

    def test_this_projects_evidence_rule_admits_only_the_linked_tickets_folder(self):
        self.verdict('standing-project')

    def test_a_pull_request_with_no_linked_ticket_passes_with_a_note(self):
        self.verdict('no-ticket')

    def test_part_of_links_are_checked_and_other_repositories_are_noted(self):
        self.verdict('part-of')

    def test_a_closing_keyword_in_the_body_links_the_ticket(self):
        self.verdict('regex-close')

    def test_two_linked_tickets_own_the_union_of_their_paths(self):
        self.verdict('two-tickets')

    def test_a_linked_issue_without_owned_paths_passes_with_a_note(self):
        self.verdict('spec-only')

    def test_every_page_of_changed_files_is_checked(self):
        self.verdict('pages')

    def test_and_its_tests_admits_the_test_files_beside_x_naming_x(self):
        self.verdict('its-tests')

    def test_and_its_tests_admits_nothing_else(self):
        self.verdict('its-tests-not')

    def test_an_annotation_before_an_exclusion_admits_no_tests(self):
        s = json.loads((FIXTURES / 'its-tests.json').read_text())
        s['issues']['7']['body'] = (
            '## Owned paths\n\n'
            '- `tools/install/harness.py` and its tests (installer) are excluded from this change\n'
            '- `tools/release/test.py` and its tests in `example/project` (shared) are excluded from this change\n'
            '- `tools/install/setup/init.py`, plus its tests (shared: the staging only)\n'
            '- `crates/core/src/widget.rs` and its tests in `example/project` (the runner)\n'
            '- `tools/plain/run.py` and its tests (review notes (CI))\n'
            '- `tools/excluded/run.py` and its tests (notes (CI)) are excluded from this change\n')
        s['pr']['files'][0]['nodes'] = [{'path': p} for p in (
            'crates/core/src/widget_tests.rs', 'tools/install/harness.py', 'tools/install/setup/init.test.mjs',
            'tools/install/test_install.py', 'tools/release/test_release.py', 'tools/plain/test_run.py',
            'tools/excluded/test_run.py')]
        s['exit'], s['absent'] = 1, ['tests of `tools/install/harness.py`', 'tests of `tools/release/test.py`',
                                     'tests of `tools/excluded/run.py`']
        s['out'] = ['owned: crates/core/src/widget_tests.rs (tests of `crates/core/src/widget.rs`)',
                    'owned: tools/install/harness.py (by `tools/install/harness.py`)',
                    'owned: tools/install/setup/init.test.mjs (tests of `tools/install/setup/init.py`)',
                    'owned: tools/plain/test_run.py (tests of `tools/plain/run.py`)',
                    'OUT: tools/install/test_install.py (ticket #7)', 'OUT: tools/release/test_release.py (ticket #7)',
                    'OUT: tools/excluded/test_run.py (ticket #7)', 'owned-paths: 3 file(s) outside']
        self.verdict('annotated-exclusion', s)

    def test_an_unreadable_pull_request_is_an_error_not_a_pass(self):
        self.verdict('unreadable')


if __name__ == '__main__':
    unittest.main()
