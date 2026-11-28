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
                                extra=lambda text, found: {'docs/adr/'})
        self.assertEqual(found, {'docs/adr/'})


class Unresolved(unittest.TestCase):
    def test_only_questions_for_files_the_keywords_missed_are_sent(self):
        fake = Counting()
        jev_mentions.extra('Use the glossary and the project agent instructions.', fake, frozenset({'GLOSSARY.md'}))
        self.assertEqual(fake.calls[0][1], ['adr', 'agents_file', 'project_instructions'])

    def test_no_request_when_the_keywords_found_every_file(self):
        fake = Counting()
        every = frozenset({'AGENTS.md', 'GLOSSARY.md', 'docs/adr/'})
        self.assertEqual(jev_mentions.extra('Read AGENTS.md, the glossary and the ADRs.', fake, every), set())
        self.assertEqual(fake.calls, [])


class Command(unittest.TestCase):
    def test_eval_mentions_runs_end_to_end_on_a_skills_checkout(self):
        import tempfile
        import eval as E
        fake = Counting()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            name = sorted(tokens.load_map(HERE.parent / 'skills-eval' / 'required-text.json'))[0]
            (root / '.claude-plugin').mkdir()
            (root / '.claude-plugin' / 'plugin.json').write_text(json.dumps({'skills': [f'./skills/{name}']}))
            (root / 'skills' / name).mkdir(parents=True)
            (root / 'skills' / name / 'SKILL.md').write_text('Follow the project agent instructions.\n')
            with mock.patch.dict(os.environ, ON), mock.patch.object(client, 'from_env', lambda: fake), \
                    redirect_stdout(io.StringIO()) as out:
                code = E.main(['mentions', '--jev', '--skills', folder])
        self.assertIn(code, (0, 1))
        self.assertEqual([state for state, _ in fake.calls], ['Follow the project agent instructions.\n'])
        self.assertIn('mentions:', out.getvalue())

    def test_eval_mentions_needs_a_skills_checkout(self):
        import eval as E
        with mock.patch.dict(os.environ, ON), self.assertRaises(SystemExit) as stopped:
            E.main(['mentions', '--jev'])
        self.assertIn('--skills', str(stopped.exception.code))


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
        config = json.loads((HERE / 'config.json').read_text())['sites']
        mention_questions = set(config['mentions']['questions'])
        sent = [state for state, questions in fake.calls if set(questions) <= mention_questions]
        rows = json.loads((HERE / 'fixtures' / 'mentions.json').read_text())['cases']
        open_rows = [r['text'] for r in rows if tokens.named_docs(r['text']) != set(config['mentions']['files'])]
        self.assertEqual(sent, open_rows)
        verdict_questions = set(config['verdict']['questions'])
        verdict_sent = [state for state, questions in fake.calls if set(questions) == verdict_questions]
        verdict_rows = json.loads((HERE / 'fixtures' / 'verdict.json').read_text())['cases']
        import verdict
        self.assertEqual(verdict_sent, [verdict.sent_state(r['line']) for r in verdict_rows
                                        if verdict.sent_state(r['line']) is not None])
        turn_questions = set(config['turn_end']['questions'])
        turn_sent = [state for state, questions in fake.calls if set(questions) == turn_questions]
        self.assertTrue(turn_sent)
        self.assertFalse(any('sign' in state.lower() for state in turn_sent))

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
