#!/usr/bin/env python3
"""#1481 (OB6) adapter proofs: the relay's existing collector reads ops inbox records.

python3 -I tools/review-relay/test_inbox.py

Reuses relay.py's Reader/pagination and test.py's synthetic world and fake gh
unchanged; nothing here calls GitHub or CloudRoom or writes anywhere but a
temporary folder.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay_tests = load(HERE / 'test.py', 'relay_fixture_world')
adapter = load(HERE / 'inbox.py', 'relay_inbox')
EXAMPLES = json.loads((ROOT / 'skills/launch-fleet/test/ops-protocol/examples.json').read_text())
REPO = relay_tests.REPO
PR_COMMENTS = relay_tests.COMMENTS            # repos/example/synthetic/issues/71/comments, page 1
PAGE2 = PR_COMMENTS.replace('&page=1', '&page=2')


def intent(created_ms):
    value = copy.deepcopy(EXAMPLES['intent'])
    value.update(repository=REPO, subject={'kind': 'pull_request', 'number': 71}, ticket=41,
                 created_at=created_ms, action='delivery', destination='reviewer',
                 assignment='review-span-800', prior_verdict=901, head=relay_tests.SHA)
    value['operation_key'] = adapter.effects.operation_key(value)
    return value


def row(n, record=None, at='2030-01-01T00:02:00Z', body=None):
    body = body if body is not None else 'Ops record.\n\n```json\n' + json.dumps(record) + '\n```\n'
    return {'id': n, 'body': body, 'created_at': at, 'updated_at': at}


class Adapter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.world = relay_tests.world()  # the relay's own synthetic fixture world
        for item in self.world['api'][PR_COMMENTS]:
            item.setdefault('created_at', '2030-01-01T00:01:00Z')
        self.record = intent(1893456120000)   # 2030-01-01T00:02:00Z
        self.world['api'][PR_COMMENTS].append(row(902, self.record))
        os.environ.update(PATH=str(HERE / 'fixtures') + os.pathsep + os.environ['PATH'],
                          RELAY_WORLD=str(self.root / 'world.json'), RELAY_CALLS=str(self.root / 'calls.jsonl'),
                          GH_TOKEN='synthetic-owner-login')
        os.environ.pop('REVIEW_RELAY_GH_TOKEN', None)
        self.start = {'created_at': 0, 'comment': 0}

    def read(self, cursor=None):
        Path(os.environ['RELAY_WORLD']).write_text(json.dumps(self.world))
        reader = adapter.relay.Reader(REPO, {'cache': {}})
        return adapter.read(reader, 'pull_request', 71, cursor or self.start)

    def calls(self):
        path = Path(os.environ['RELAY_CALLS'])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_reads_bound_records_through_the_existing_collector_read_only(self):
        result = self.read()
        self.assertEqual((result['complete'], result['records'], result['gaps']), (True, [self.record], []))
        self.assertEqual(result['cursor'], {'created_at': 1893456120000, 'comment': 902})
        self.assertTrue(self.calls())
        self.assertTrue(all(c['args'][:3] == ['api', '--method', 'GET'] for c in self.calls()), self.calls())

    def test_all_pages_are_read_and_a_failed_page_keeps_the_cursor(self):
        later = intent(1893456180000)
        later.update(id='intent-2', sequence=2)
        later['operation_key'] = adapter.effects.operation_key(later)
        self.world['next'] = {PR_COMMENTS: PAGE2}
        self.world['api'][PAGE2] = [row(903, later, at='2030-01-01T00:03:00Z')]
        self.assertEqual(self.read()['records'], [self.record, later])
        self.world['fail'] = PAGE2
        old = {'created_at': 7, 'comment': 8}
        result = self.read(old)
        self.assertEqual((result['complete'], result['cursor'], result['records']), (False, old, []))
        self.assertEqual(len(result['gaps']), 1)

    def test_unbound_or_malformed_records_are_gaps_never_authority(self):
        other = copy.deepcopy(self.record)
        other['subject'] = {'kind': 'issue', 'number': 71}
        other['operation_key'] = adapter.effects.operation_key(other)
        self.world['api'][PR_COMMENTS] += [
            row(903, other),                                                   # wrong container kind
            row(904, body='```json\n{"schema": "openwiz.ops-dispatch.v1"}\n```'),  # malformed
            row(905, self.record, at='2030-01-01T00:09:00Z'),                  # time disagrees with source
        ]
        # R4: an affected ops record that cannot be read or bound makes the whole read incomplete.
        old = {'created_at': 7, 'comment': 8}
        result = self.read(old)
        self.assertEqual((result['complete'], result['cursor'], result['records']), (False, old, []))
        self.assertEqual([gap.split(':')[0] for gap in result['gaps']], ['comment 903', 'comment 904', 'comment 905'])

    def test_r4_unrelated_json_is_not_an_ops_record(self):
        self.world['api'][PR_COMMENTS].append(row(906, body='Notes\n\n```json\n{"tool": "other"}\n```'))
        self.world['api'][PR_COMMENTS].append(row(907, body='VERDICT: see openwiz.ops-dispatch.v1 records above.'))
        result = self.read()
        self.assertEqual((result['complete'], result['records'], result['gaps']), (True, [self.record], []))

    def transport(self, created_ms):
        value = copy.deepcopy(EXAMPLES['transport'])
        value.update({k: copy.deepcopy(self.record[k]) for k in ('repository', 'spec', 'ticket', 'subject',
                                                                 'operation_key', 'approval', 'rule')},
                     id='transport-9', intent_id=self.record['id'], created_at=created_ms,
                     state='uncertain', receipt_digest=None)
        return value

    def test_r4_an_escaped_schema_record_is_still_read(self):
        unsure = self.transport(1893456120000)
        raw = json.dumps(unsure).replace('openwiz.ops-dispatch.v1', 'openwiz.ops-dispatch.v\\u0031')
        self.world['api'][PR_COMMENTS].append(row(903, body='Ops record.\n\n```json\n' + raw + '\n```\n'))
        result = self.read()
        self.assertEqual((result['complete'], [r['kind'] for r in result['records']]), (True, ['intent', 'transport']))
        self.assertEqual(result['records'][1]['state'], 'uncertain')

    def test_r4_unterminated_or_indented_fences_make_the_read_incomplete(self):
        raw = json.dumps(self.transport(1893456120000))
        old = {'created_at': 7, 'comment': 8}
        for body in ('Ops record.\n\n```json\n' + raw + '\n',
                     'Ops record.\n\n```json\n' + raw + '\n   ```\n',
                     'Ops record.\n\n  ```json\n' + raw + '\n```\n',
                     '```json\n' + raw.replace('openwiz.ops-dispatch.v1', 'openwiz.ops-dispatch.v\\u0031')[:-1] + '\n'):
            with self.subTest(body=body[:40]):
                world = copy.deepcopy(self.world)
                self.world['api'][PR_COMMENTS].append(row(903, body=body))
                result = self.read(old)
                self.assertEqual((result['complete'], result['cursor'], result['records']), (False, old, []))
                self.assertEqual(len(result['gaps']), 1)
                self.world = world

    def test_r4_a_duplicate_key_record_is_a_gap_through_the_cli(self):
        # #2479: a later duplicate "schema" must not hide an uncertainty record from the inbox.
        raw = json.dumps(self.transport(1893456120000))[:-1] + ', "schema":"other"}'
        self.world['api'][PR_COMMENTS].append(row(903, body='Ops record.\n\n```json\n' + raw + '\n```\n'))
        Path(os.environ['RELAY_WORLD']).write_text(json.dumps(self.world))
        run = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'inbox.py'), '--repo', REPO,
                              '--kind', 'pull_request', '--number', '71'],
                             capture_output=True, text=True, timeout=60)
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual((result['complete'], result['cursor'], result['records']),
                         (False, {'created_at': 0, 'comment': 0}, []))
        self.assertEqual(result['gaps'], ['comment 903: duplicate JSON key'])

    def test_ordinary_comments_are_not_records(self):
        result = self.read()
        self.assertNotIn(901, [r.get('id') for r in result['records']])
        self.assertEqual(result['gaps'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
