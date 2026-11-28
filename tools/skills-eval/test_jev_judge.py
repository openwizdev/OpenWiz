#!/usr/bin/env python3
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'typesafe'))
import client
import decide
import driver
import eval as E
import jev_judge

KEY = 'synthetic-typesafe-key'
ON = {'OPENWIZ_JEV': '1', 'TYPESAFE_API_KEY': KEY}


def recorded(meets, stays):
    return {'model': 'jev-1.14.0', 'answers': {
        'meets_rule': {'type': 'noul', 'noul': meets},
        'stays_within_rule': {'type': 'noul', 'noul': stays}}}


class Billed(client.SystemOne):
    def __init__(self, response=None, error=None, usage=True):
        self.response, self.error, self.usage, self.calls = response, error, usage, []

    def system_one(self, state, questions, model=client.MODEL):
        self.calls.append({'state': state, 'questions': questions, 'model': model})
        if self.error:
            raise client.TypeSafeError(self.error)
        if self.usage is False:
            return dict(self.response)
        if self.usage is not True:
            return dict(self.response, usage=self.usage)
        return dict(self.response, usage={'input_tokens': 1000, 'output_tokens': 3})


def jev_with(ask):
    return lambda rubric, reply: jev_judge.try_jev(rubric, reply, ask)


class Judge(unittest.TestCase):
    def test_two_nouls_go_out_in_one_request_and_the_model_is_not_called(self):
        fake = client.FakeClient(recorded(0.94, 0.92)['answers'], model='jev-1.14.0')
        called = []
        verdict, stop = driver.judge('Name the file.', 'Changed client.py.', {}, lambda body: called.append(body),
                                     jev_with(fake))
        self.assertEqual(called, [])
        self.assertIsNone(stop)
        self.assertEqual(verdict['verdict'], 'pass')
        self.assertEqual(verdict['reason'], 'The reply does what the rule requires.')
        self.assertEqual(verdict['model'], 'jev-1.14.0')
        self.assertEqual(len(fake.calls), 1)
        sent = fake.calls[0]['questions']
        self.assertEqual(set(sent), {'meets_rule', 'stays_within_rule'})
        self.assertTrue(all(question['type'] == 'noul' for question in sent.values()))

    def test_an_uncertain_noul_falls_back_to_the_json_judge(self):
        fake = client.FakeClient(recorded(0.55, 0.93)['answers'])
        body = {'content': [{'type': 'text', 'text': '{"verdict": "pass", "reason": "It meets the rule."}'}],
                'stop_reason': 'end_turn'}
        verdict, stop = driver.judge('Name the file.', 'Changed client.py.', {'judge_model': 'synthetic'},
                                     lambda payload: (body, None, None), jev_with(fake))
        self.assertEqual((verdict['verdict'], verdict['model'], stop), ('pass', 'synthetic', None))

    def test_a_client_error_falls_back(self):
        body = {'content': [{'type': 'text', 'text': '{"verdict": "fail", "reason": "It does not."}'}],
                'stop_reason': 'end_turn'}
        verdict, _ = driver.judge('rule', 'reply', {'judge_model': 'synthetic'}, lambda payload: (body, None, None),
                                  jev_with(client.FakeClient(error='http')))
        self.assertEqual(verdict['verdict'], 'fail')

    def test_no_client_keeps_the_parser(self):
        text = '{"verdict": "pass", "reason": "It meets the rule."}'
        self.assertEqual(jev_judge.parse_model_text(text)['verdict'], 'pass')
        self.assertIsNone(jev_judge.parse_model_text('{"verdict": "pass", "verdict": "fail", "reason": "x"}'))
        self.assertIsNone(jev_judge.parse_model_text('not json'))
        self.assertIsNone(jev_judge.from_response(recorded(0.55, 0.93)))
        self.assertIsNone(jev_judge.try_jev('rule', 'reply', None))

    def test_a_key_without_the_opt_in_builds_no_client(self):
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': KEY}):
            os.environ.pop('OPENWIZ_JEV', None)
            self.assertIsNone(client.from_env())
            self.assertIsNone(jev_judge.mode())
            self.assertIsNone(jev_judge.asker({'judge_jev': {'model': 'x'}}))
        with mock.patch.dict(os.environ, ON):
            self.assertIsNotNone(client.from_env())
            self.assertIsNone(jev_judge.asker({'judge_jev': None}))
            self.assertIsNotNone(jev_judge.asker({'judge_jev': jev_judge.mode()}))


def synthetic_case():
    return {'id': 'syn-case', 'world': {}, 'brief': 'Say what you changed.', 'expect': {'final': 'Names the file.'}}


def actor_post(judge_text=None):
    sent = []

    def post(url, body):
        sent.append(body)
        text = judge_text if body.get('system') == driver.JUDGE else 'Changed client.py.'
        return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn',
                'usage': {'input_tokens': 100, 'output_tokens': 10}}
    return post, sent


def settings_with_jev():
    settings = json.loads((HERE / 'settings.json').read_text())
    settings.pop('provider')
    with mock.patch.dict(os.environ, ON):
        settings['judge_jev'] = jev_judge.mode()
    return settings


class Spend(unittest.TestCase):
    def run_one(self, ask, budget=20.0, judge_text='{"verdict": "fail", "reason": "It does not."}'):
        settings = settings_with_jev()
        post, sent = actor_post(judge_text)
        marks = []
        with mock.patch.object(jev_judge, 'asker', lambda s: ask if s.get('judge_jev') else None):
            t = driver.run_case(synthetic_case(), settings, (lambda p: None, lambda p: []), post, 1,
                                budget_usd=budget, checkpoint=marks.append)
        actor = driver.cost({'input_tokens': 100, 'output_tokens': 10}, settings['prices_usd_per_mtok'])
        return t, sent, marks, actor

    def test_a_jev_verdict_is_counted_in_the_run_cost(self):
        ask = Billed(recorded(0.94, 0.92))
        t, sent, marks, actor = self.run_one(ask)
        self.assertEqual(len(ask.calls), 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(t['judgment']['verdict'], 'pass')
        self.assertAlmostEqual(t['cost_usd'], actor + 1000 * 0.042 / 1e6, places=9)
        self.assertEqual(t['uncertain_usd'], 0)
        self.assertEqual(t['jev_usage'], [{'input_tokens': 1000, 'output_tokens': 3}])
        self.assertGreaterEqual(marks[-1]['uncertain_usd'], 0.0)
        self.assertIn('reservation retained', marks[-1]['error'])

    def test_an_abstention_is_still_paid_for(self):
        ask = Billed(recorded(0.55, 0.93))
        t, sent, _, actor = self.run_one(ask)
        self.assertEqual(len(sent), 2)
        self.assertEqual(t['judgment']['verdict'], 'fail')
        self.assertAlmostEqual(t['cost_usd'], 2 * actor + 1000 * 0.042 / 1e6, places=9)

    def test_a_failed_request_keeps_its_reservation(self):
        ask = Billed(error='network')
        t, _, _, actor = self.run_one(ask)
        self.assertGreater(t['uncertain_usd'], 0)
        self.assertEqual(t['jev_usage'], [None])

    def test_no_request_is_sent_past_the_cap(self):
        ask = Billed(recorded(0.94, 0.92))
        with mock.patch.object(jev_judge, 'reserve', lambda state, questions, frozen=None: 100.0):
            t, sent, _, _ = self.run_one(ask)
        self.assertEqual(ask.calls, [])
        self.assertEqual(len(sent), 2)
        self.assertEqual(t['jev_usage'], [])

    def test_a_reply_without_usage_is_a_failed_call(self):
        ask = Billed(recorded(0.94, 0.92), usage=False)
        t, sent, _, _ = self.run_one(ask)
        self.assertEqual(len(ask.calls), 1)
        self.assertEqual(len(sent), 2)
        self.assertEqual(t['judgment']['verdict'], 'fail')
        self.assertGreater(t['uncertain_usd'], 0)

    def test_incomplete_usage_is_a_failed_call(self):
        for usage in ({'input_tokens': 1000}, {'output_tokens': 3}, {'input_tokens': -1, 'output_tokens': 0}):
            with self.subTest(usage=usage):
                ask = Billed(recorded(0.94, 0.92), usage=usage)
                t, sent, _, _ = self.run_one(ask)
                self.assertEqual(len(sent), 2)
                self.assertEqual(t['judgment']['verdict'], 'fail')
                self.assertGreater(t['uncertain_usd'], 0)

    def test_the_frozen_config_decides_even_if_the_file_changes_mid_run(self):
        ask = Billed(recorded(0.8, 0.8))
        root = copy.deepcopy(decide.load())
        root['sites']['judge']['act'] = 0.95
        settings = settings_with_jev()
        post, sent = actor_post('{"verdict": "fail", "reason": "It does not."}')
        with mock.patch.object(jev_judge, 'asker', lambda s: ask), mock.patch.object(decide, 'load', lambda: root):
            t = driver.run_case(synthetic_case(), settings, (lambda p: None, lambda p: []), post, 1, budget_usd=20)
        self.assertEqual(t['judgment']['verdict'], 'pass')
        self.assertEqual(len(sent), 1)
        self.assertEqual(ask.calls[0]['model'], settings['judge_jev']['model'])

    def test_a_refused_fallback_keeps_the_failed_jev_reservation(self):
        import parallel
        ask = Billed(error='network')
        settings = settings_with_jev()
        post, sent = actor_post('{"verdict": "pass", "reason": "It does."}')
        marks = []

        def checkpoint(interim):
            marks.append(interim)
            if interim['jev_usage']:
                raise parallel.Cap(interim)
        with mock.patch.object(jev_judge, 'asker', lambda s: ask):
            try:
                driver.run_case(synthetic_case(), settings, (lambda p: None, lambda p: []), post, 1,
                                checkpoint=checkpoint)
            except parallel.Cap as capped:
                t = capped.transcript
        held = marks[-2]['reserved_usd']
        self.assertEqual(len(sent), 1)
        self.assertAlmostEqual(t['uncertain_usd'], held, places=9)
        self.assertNotIn('reserved_usd', t)
        self.assertEqual(t['stop'], 'cap')

    def test_off_by_default_never_asks(self):
        settings = settings_with_jev()
        settings['judge_jev'] = None
        post, sent = actor_post('{"verdict": "pass", "reason": "It does."}')
        with mock.patch.dict(os.environ, ON), \
                mock.patch.object(client.HttpClient, 'system_one', side_effect=AssertionError('asked')):
            t = driver.run_case(synthetic_case(), settings, (lambda p: None, lambda p: []), post, 1, budget_usd=20)
        self.assertEqual(t['judgment']['verdict'], 'pass')
        self.assertEqual(len(sent), 2)


class Identity(unittest.TestCase):
    def test_the_judge_mode_and_config_are_part_of_the_run_identity(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OPENWIZ_JEV', None)
            off = E.run_settings()
        with mock.patch.dict(os.environ, ON):
            on = E.run_settings()
            root = copy.deepcopy(decide.load())
            root['sites']['judge']['act'] = 0.95
            with mock.patch.object(decide, 'load', lambda: root):
                raised = E.run_settings()
        self.assertIsNone(off['judge_jev'])
        self.assertEqual(on['judge_jev']['judge']['act'], 0.7)
        self.assertEqual(len({E.sha(off), E.sha(on), E.sha(raised)}), 3)
        for name in ('../typesafe/client.py', '../typesafe/decide.py', '../typesafe/config.json'):
            self.assertIn(name, E.CODE)
        base = {'settings_hash': E.sha(off), 'cases_hash': 'c', 'code_hash': 'k', 'schema_hash': 's',
                'rows': [], 'passed': 0, 'runs': 0}
        with self.assertRaises(ValueError):
            E.compare(base, dict(base, settings_hash=E.sha(on)))


class Resume(unittest.TestCase):
    def refusal(self, recorded_env, resume_env):
        import tempfile
        import parallel
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, recorded_env):
                for name in ON:
                    if name not in recorded_env:
                        os.environ.pop(name, None)
                settings = E.run_settings()
            Path(folder, 'manifest.json').write_text(json.dumps({'settings': settings, 'settings_hash': E.sha(settings)}))
            with mock.patch.dict(os.environ, resume_env):
                for name in ON:
                    if name not in resume_env:
                        os.environ.pop(name, None)
                with self.assertRaises(ValueError) as refused:
                    parallel.resume(folder, None)
            return str(refused.exception)

    def test_a_parallel_resume_refuses_another_judge_mode(self):
        self.assertNotIn('settings changed', self.refusal({}, {}))
        self.assertNotIn('settings changed', self.refusal(ON, ON))
        self.assertIn('settings changed', self.refusal({}, ON))
        self.assertIn('settings changed', self.refusal(ON, {}))


class Box(unittest.TestCase):
    def test_a_box_with_no_confidence_abstains(self):
        boxed = {'answers': {'bird': {'type': 'box', 'confidence': None,
                                      'box': {'top': 0.1, 'bottom': 0.4, 'left': 0.2, 'right': 0.5}}}}
        edges, confidence = client.box(boxed, 'bird')
        self.assertEqual((edges['top'], confidence), (0.1, None))
        self.assertIsNone(decide.box_ready(boxed, 'bird', 0.5))


class Bench(unittest.TestCase):
    def test_recorded_fixture_counts(self):
        data = json.loads((HERE.parent / 'typesafe' / 'fixtures' / 'judge.json').read_text())
        n, old_hit, shaped_hit = __import__('bench', fromlist=['score_judge']).score_judge(data)
        self.assertEqual((n, old_hit, shaped_hit), (6, 4, 5))


if __name__ == '__main__':
    unittest.main()
