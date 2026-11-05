#!/usr/bin/env python3
"""P8 graph/ready-label/read-back contract on synthetic metadata."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
GRAPH = HERE / 'graph.py'


def issue(n, title, **values):
    return dict(number=n, kind='issue', title=title, labels=[], milestone='Infra',
                parent=None, blockers=[], state='open', **values)


def snapshot():
    spec = issue(9001, 'Synthetic spec')
    spec['labels'] = ['spec', 'ready-for-human']
    ticket = issue(9002, 'Synthetic ticket')
    ticket.update(labels=['ready-for-agent', 'bug'], parent=9001, blockers=[9003, 9004])
    later = issue(9003, 'Synthetic dependency')
    later.update(parent=9001, labels=['ready-for-human', 'ready-for-agent'])
    merged = issue(9004, 'Synthetic merged dependency')
    merged['state'] = 'merged'
    return {'items': [spec, ticket, later, merged],
            'milestones': [{'title': 'Infra', 'number': 7}], 'exclude': []}


def destinations():
    return {
        '4001': {'number': 4001, 'title': 'Synthetic spec', 'labels': [{'name': 'spec'}],
                 'milestone': {'number': 7, 'title': 'Infra'}, 'parent': None,
                 'blockedBy': {'totalCount': 0, 'nodes': []}},
        '4012': {'number': 4012, 'title': 'Synthetic ticket', 'labels': [{'name': 'bug'}],
                 'milestone': {'number': 7, 'title': 'Infra'}, 'parent': {'number': 4001, 'url': 'https://github.com/synthetic-org/openwiz/issues/4001'},
                 'blockedBy': {'totalCount': 1, 'nodes': [{'number': 4033, 'url': 'https://github.com/synthetic-org/openwiz/issues/4033'}]}},
        '4033': {'number': 4033, 'title': 'Synthetic dependency', 'labels': [],
                 'milestone': {'number': 7, 'title': 'Infra'}, 'parent': {'number': 4001, 'url': 'https://github.com/synthetic-org/openwiz/issues/4001'},
                 'blockedBy': {'totalCount': 0, 'nodes': []}},
    }


class GraphContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / 'snapshot.json'
        self.input.write_text(json.dumps(snapshot()))
        self.map = self.root / 'map.tsv'
        self.map.write_text('kind\tclosedwiz\topenwiz\nissue\t9001\t4001\n'
                            'issue\t9002\t4012\nissue\t9003\t4033\n')
        self.world = self.root / 'world.json'
        self.world.write_text(json.dumps({'destinations': destinations()}))
        self.env = dict(os.environ, OPEN_TICKETS_WORLD=str(self.world),
                        OPEN_TICKETS_LOG=str(self.root / 'gh.jsonl'))

    def run_graph(self, *args, ok=True):
        r = subprocess.run([sys.executable, '-I', str(GRAPH), '--snapshot', str(self.input),
                            '--map', str(self.map), '--target', 'synthetic-org/openwiz',
                            *map(str, args)], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode == 0, ok, r.stderr or r.stdout)
        return r

    def test_p8_graph_maps_parent_blocker_milestone_and_never_ready_labels(self):
        out = self.root / 'plan.json'
        self.run_graph('--out', out)
        graph = json.loads(out.read_text())
        self.assertEqual(graph['status'], 'graph_only')
        self.assertEqual(graph['moves'], [
            {'closedwiz': 9001, 'openwiz': 4001, 'kind': 'issue', 'title': 'Synthetic spec',
             'labels': ['spec'], 'milestone': {'title': 'Infra', 'number': 7},
             'parent': None, 'blockers': [], 'merged_blockers': [], 'completed_blockers': [], 'dropped_blockers': []},
            {'closedwiz': 9002, 'openwiz': 4012, 'kind': 'issue', 'title': 'Synthetic ticket',
             'labels': ['bug'], 'milestone': {'title': 'Infra', 'number': 7},
             'parent': 4001, 'blockers': [4033], 'merged_blockers': [9004], 'completed_blockers': [], 'dropped_blockers': []},
            {'closedwiz': 9003, 'openwiz': 4033, 'kind': 'issue', 'title': 'Synthetic dependency',
             'labels': [], 'milestone': {'title': 'Infra', 'number': 7},
             'parent': 4001, 'blockers': [], 'merged_blockers': [], 'completed_blockers': [], 'dropped_blockers': []},
        ])
        self.assertFalse((self.root / 'gh.jsonl').exists())
        self.run_graph('--verify', '--gh', HERE / 'fake-gh')

    def test_p8_readback_detects_each_broken_mapping_or_ready_label(self):
        for field, value in [('parent', {'number': 9001, 'url': 'https://github.com/synthetic-org/openwiz/issues/9001'}),
                             ('blockedBy', {'totalCount': 1, 'nodes': [{'number': 9003, 'url': 'https://github.com/synthetic-org/openwiz/issues/9003'}]}),
                             ('blockedBy', {'totalCount': 1, 'nodes': []}),
                             ('milestone', {'number': 3, 'title': 'Infra'}),
                             ('title', 'Unexpected title'),
                             ('labels', [{'name': 'bug'}, {'name': 'ready-for-agent'}])]:
            with self.subTest(field=field, value=value):
                dest = destinations()
                dest['4012'][field] = value
                self.world.write_text(json.dumps({'destinations': dest}))
                r = self.run_graph('--verify', '--gh', HERE / 'fake-gh', ok=False)
                self.assertIn('read-back:', r.stderr)

    def test_p8_ambiguous_graphs_and_maps_refuse_before_output(self):
        cases = []
        for key, value in [('parent', 9999), ('blockers', [9999]), ('blockers', [9002]),
                           ('blockers', [9003, 9003]), ('milestone', 'Unknown'),
                           ('labels', ['bug', 'bug'])]:
            case = snapshot()
            case['items'][1][key] = value
            cases.append(case)
        closed = snapshot()
        closed['items'][3]['state'] = 'closed'
        cases.append(closed)
        cycle = snapshot()
        cycle['items'][2]['blockers'] = [9002]
        cases.append(cycle)
        for case in cases:
            self.input.write_text(json.dumps(case))
            self.run_graph('--out', self.root / 'refused.json', ok=False)
            self.assertFalse((self.root / 'refused.json').exists())
        self.input.write_text(json.dumps(snapshot()))
        self.map.write_text('kind\tclosedwiz\topenwiz\nissue\t9001\t4001\nissue\t9002\t4001\n')
        self.run_graph('--out', self.root / 'refused.json', ok=False)

    def test_p8_reapproval_uses_new_numbers_and_revision_v2_normalization(self):
        bodies = self.root / 'bodies.json'
        bodies.write_text(json.dumps({'9001': 'Synthetic spec body.',
                                      '9002': ' - [x] Synthetic task',
                                      '9003': 'Synthetic dependency body.'}))
        out = self.root / 'approval.json'
        self.run_graph('--out', out, '--reapproval', 9001, '--bodies', bodies)
        request = json.loads(out.read_text())['reapproval']
        self.assertEqual(request['status'], 'requires_reapproval')
        self.assertEqual(request['fingerprint'],
                         '43ff4e60df7cd0f14d2f6b02053a8b68e72a22b5f5f77944dde3bf9ede79f3ab')
        self.assertIn('ticket #4012 blocked-by #4033 body sha256', request['revision'])
        self.assertIn('| #4012 | Synthetic ticket | #4033 | held |', request['table'])
        self.assertNotIn('ready-for-agent', request['table'])
        self.assertNotIn('ready-for-human', request['table'])
        self.map.write_text('kind\tclosedwiz\topenwiz\nissue\t9001\tplanned\n'
                            'issue\t9002\tplanned\nissue\t9003\tplanned\n')
        out.unlink()
        self.run_graph('--out', out, '--reapproval', 9001, '--bodies', bodies)
        pending = json.loads(out.read_text())['reapproval']
        self.assertEqual(pending['status'], 'awaiting_destination_numbers')
        self.assertIsNone(pending['fingerprint'])
        self.assertIsNone(pending['revision'])

    def test_p8_planned_numbers_stay_symbolic_and_extra_rows_refuse(self):
        self.map.write_text('kind\tclosedwiz\topenwiz\nissue\t9001\tplanned\n'
                            'issue\t9002\tplanned\nissue\t9003\tplanned\n')
        out = self.root / 'plan.json'
        self.run_graph('--out', out)
        moves = json.loads(out.read_text())['moves']
        self.assertEqual(moves[1]['parent'], {'closedwiz': 9001})
        self.assertEqual(moves[1]['blockers'], [{'closedwiz': 9003}])
        self.run_graph('--verify', '--gh', HERE / 'fake-gh', ok=False)
        self.assertFalse((self.root / 'gh.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
