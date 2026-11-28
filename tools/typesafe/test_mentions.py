#!/usr/bin/env python3
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'skills-eval'))
import bench
import client
import jev_mentions
import tokens

ON = {'OPENWIZ_JEV': '1', 'TYPESAFE_API_KEY': 'synthetic-typesafe-key'}


class Counting(client.SystemOne):
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model=client.MODEL):
        self.calls.append((state, sorted(questions)))
        return {'model': client.MODEL, 'answers': {}}


class Mentions(unittest.TestCase):
    def test_recorded_counts(self):
        data = json.loads((HERE / 'fixtures' / 'mentions.json').read_text())
        self.assertEqual(bench.score_mentions(data), (7, 4, 6))

    def test_no_client_adds_nothing(self):
        self.assertEqual(jev_mentions.extra('Follow the project agent instructions.', None), set())

    def test_the_offline_scan_never_asks_even_with_the_opt_in_and_key(self):
        text = 'Follow the project instructions and read `docs/x.md`.'
        with mock.patch.dict(os.environ, ON), \
                mock.patch.object(client.HttpClient, 'system_one', side_effect=AssertionError('asked')):
            found = tokens.mentions('syn', text, lambda p: p == 'docs/x.md')
            errs = tokens.map_problems({}, [], lambda p: None, lambda p: [])
        self.assertEqual(found, {'docs/x.md', 'AGENTS.md'})
        self.assertEqual(errs, [])

    def test_an_explicit_hook_is_the_only_way_jev_adds_a_file(self):
        found = tokens.mentions('syn', 'Read the decision record.', lambda p: False,
                                extra=lambda text: {'docs/adr/'})
        self.assertEqual(found, {'docs/adr/'})


class Live(unittest.TestCase):
    def test_live_runs_every_fixture_set_mentions_included(self):
        fake = Counting()
        out = io.StringIO()
        with mock.patch.object(client, 'from_env', lambda: fake), redirect_stdout(out):
            self.assertEqual(bench.main(['--live']), 0)
        printed = out.getvalue()
        for name in bench.LIVE.values():
            self.assertIn(f'{name[0]} live:', printed)
        schemas = {json.loads(p.read_text())['schema'] for p in bench.FIXTURES.glob('*.json')}
        self.assertEqual(schemas, set(bench.LIVE))
        mention_questions = sorted(json.loads((HERE / 'config.json').read_text())['sites']['mentions']['questions'])
        sent = [state for state, questions in fake.calls if questions == mention_questions]
        self.assertEqual(len(sent), 7)

    def test_live_without_the_opt_in_sends_nothing(self):
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': 'synthetic-typesafe-key'}), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            os.environ.pop('OPENWIZ_JEV', None)
            self.assertEqual(bench.main(['--live']), 2)

    def test_eval_mentions_needs_the_flag(self):
        import eval as E
        with mock.patch.dict(os.environ, ON), self.assertRaises(SystemExit) as stopped:
            E.main(['mentions'])
        self.assertIn('--jev', str(stopped.exception.code))


if __name__ == '__main__':
    unittest.main()
