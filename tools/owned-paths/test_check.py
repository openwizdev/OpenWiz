#!/usr/bin/env python3
"""The owned-paths check's proofs (#1418): python3 -I tools/owned-paths/test_check.py

Each fixture is one synthetic pull request, its linked tickets and their comments. The
check runs as CI runs it, against a fake `gh` that answers its GraphQL reads from the
fixture, so the reads, the parsing and the verdict are proved together.
"""
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


def run(scenario):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'gh').write_text(FAKE_GH)
        (tmp / 'gh').chmod(0o755)
        env = dict(os.environ, PATH=f'{tmp}{os.pathsep}{os.environ["PATH"]}',
                   FAKE_GH_SCENARIO=str(FIXTURES / f'{scenario}.json'),
                   FAKE_GH_FLEET=str(FIXTURES / 'fleet.md'), FAKE_GH_LOG=str(tmp / 'log'))
        r = subprocess.run([sys.executable, '-I', str(CHECK), '--repo', 'example/project', '--pr', '42'],
                           capture_output=True, text=True, env=env, timeout=60)
        calls = [json.loads(l) for l in (tmp / 'log').read_text().splitlines()] if (tmp / 'log').exists() else []
        return r, calls


class Check(unittest.TestCase):
    def verdict(self, scenario):
        s = json.loads((FIXTURES / f'{scenario}.json').read_text())
        r, calls = run(scenario)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, s['exit'], out)
        for line in s['out']:
            self.assertIn(line, out)
        for line in s.get('absent', []):
            self.assertNotIn(line, out)
        for call in calls:
            self.assertEqual(call[:2], ['api', 'graphql'], 'every read is GraphQL')
        return out

    # catches: a file outside every owned path passing, or a failure that names no file or ticket
    def test_a_file_outside_the_owned_paths_fails_naming_file_and_ticket(self):
        self.verdict('outside')

    # catches: a false failure on shared bullets, globs, folders written with or without their slash
    def test_files_inside_owned_paths_shared_paths_and_globs_pass(self):
        self.verdict('inside')

    # catches: a record author's grant ignored, a stranger's or another repository's grant trusted,
    # or a path merely mentioned in a comment treated as granted
    def test_record_author_grants_cover_their_paths_and_no_one_elses_do(self):
        self.verdict('grants')

    # catches: the fleet's standing supporting edits (own changelog, evidence, registry rows)
    # failing, or another ticket's changelog line passing
    def test_the_standing_supporting_edit_rule_covers_its_paths_only(self):
        self.verdict('standing')

    # catches: ordinary non-ticket work blocked, or a bare mention treated as a link
    def test_a_pull_request_with_no_linked_ticket_passes_with_a_note(self):
        self.verdict('no-ticket')

    # catches: a "Part of" pull request escaping the check, another repository's ticket or
    # half of a split ticket counted here
    def test_part_of_links_are_checked_and_other_repositories_are_noted(self):
        self.verdict('part-of')

    # catches: a pull request against a release branch (no closing references) escaping the check
    def test_a_closing_keyword_in_the_body_links_the_ticket(self):
        self.verdict('regex-close')

    # catches: a pull request closing two tickets failing on the second ticket's paths
    def test_two_linked_tickets_own_the_union_of_their_paths(self):
        self.verdict('two-tickets')

    # catches: a linked bug report without owned paths failing every file
    def test_a_linked_issue_without_owned_paths_passes_with_a_note(self):
        self.verdict('spec-only')

    # catches: files after the first page of 100 never checked
    def test_every_page_of_changed_files_is_checked(self):
        self.verdict('pages')

    # catches: an unreadable pull request passing as if it linked no ticket
    def test_an_unreadable_pull_request_is_an_error_not_a_pass(self):
        self.verdict('unreadable')


if __name__ == '__main__':
    unittest.main()
