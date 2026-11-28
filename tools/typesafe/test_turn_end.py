#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench
import client
import turn_end


class _Yes:
    def system_one(self, state, questions, model=client.MODEL):
        self.questions = questions
        return {'model': model, 'answers': {
            'plan_limit': {'type': 'noul', 'noul': 0.96},
            'rate_limit': {'type': 'noul', 'noul': 0.05}}}


class _Uncertain:
    def system_one(self, state, questions, model=client.MODEL):
        return {'model': model, 'answers': {
            'plan_limit': {'type': 'noul', 'noul': 0.96},
            'rate_limit': {'type': 'noul', 'noul': 0.5}}}


class TurnEnd(unittest.TestCase):
    def test_recorded_counts(self):
        data = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'turn_end.json').read_text())
        self.assertEqual(bench.score_turn_end(data), (6, 4, 5))

    def test_a_missing_or_blank_key_never_asks_even_with_the_opt_in(self):
        from unittest import mock
        for key in (None, '', '   '):
            env = {'OPENWIZ_JEV': '1'} if key is None else {'OPENWIZ_JEV': '1', 'TYPESAFE_API_KEY': key}
            with self.subTest(key=key), mock.patch.dict(os.environ, env), \
                    mock.patch.object(client.HttpClient, 'system_one', side_effect=AssertionError('asked')):
                if key is None:
                    os.environ.pop('TYPESAFE_API_KEY', None)
                self.assertFalse(turn_end.usage_limit('Claude usage limit reached, please wait'))

    def test_fake_client_sends_both_questions_and_a_clear_yes_acts(self):
        fake = _Yes()
        self.assertTrue(turn_end.usage_limit('Claude usage limit reached', fake))
        self.assertEqual(set(fake.questions), {'plan_limit', 'rate_limit'})

    def test_only_the_tail_of_a_long_log_is_sent(self):
        seen = []

        class Seen:
            def system_one(self, state, questions, model=client.MODEL):
                seen.append(state)
                raise client.TypeSafeError('network')

        log = 'x' * 9000 + 'y' * turn_end.TAIL_CHARS
        self.assertFalse(turn_end.usage_limit(log, Seen()))
        self.assertEqual(seen, ['y' * turn_end.TAIL_CHARS])

    def test_a_key_without_the_opt_in_never_asks(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': 'synthetic-typesafe-key'}), \
                mock.patch.object(client.HttpClient, 'system_one', side_effect=AssertionError('asked')):
            os.environ.pop('OPENWIZ_JEV', None)
            self.assertFalse(turn_end.usage_limit('Claude usage limit reached, please wait'))

    def test_a_credential_in_the_log_is_never_sent(self):
        seen = []

        class Seen:
            def system_one(self, state, questions, model=client.MODEL):
                seen.append(state)
                return _Yes().system_one(state, questions)

        log = 'Claude usage limit reached, please wait\nGH_TOKEN=ghp_' + 'x' * 36
        self.assertFalse(turn_end.usage_limit(log, Seen()))
        self.assertEqual(seen, [])

    def test_no_credential_check_means_no_request(self):
        seen = []

        class Seen:
            def system_one(self, state, questions, model=client.MODEL):
                seen.append(state)
                return _Yes().system_one(state, questions)

        from unittest import mock
        with mock.patch.object(turn_end, 'kit_check', lambda: None):
            self.assertFalse(turn_end.usage_limit('Claude usage limit reached, please wait', Seen()))
        self.assertEqual(seen, [])

    def test_event_lines_are_neither_sent_nor_read_as_a_sign_in(self):
        fake = _Yes()
        seen = []
        original = fake.system_one

        def record(state, questions, model=client.MODEL):
            seen.append(state)
            return original(state, questions, model)
        fake.system_one = record
        log = ('{"event": "queued", "conversation": "c0ffee401-0000"}\n'
               'Claude usage limit reached, please wait\n'
               '{"event": "turn_end", "data": {"tools": []}}\n')
        self.assertTrue(turn_end.usage_limit(log, fake))
        self.assertEqual(seen, ['Claude usage limit reached, please wait'])

    def test_a_sign_in_line_is_not_sent(self):
        self.assertIsNone(turn_end.state('not signed in: run login', lambda text: False))

    def test_an_uncertain_factor_falls_back(self):
        self.assertFalse(turn_end.usage_limit('maybe a limit', _Uncertain()))


if __name__ == '__main__':
    unittest.main()
