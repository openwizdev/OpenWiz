#!/usr/bin/env python3
"""#1684 offline proofs. All API responses and commands are synthetic."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import driver
spec = importlib.util.spec_from_file_location('eval_cli', HERE / 'eval.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

SET = {'provider': 'openrouter', 'model': 'deepseek/deepseek-v4.1-flash',
       'judge_model': 'deepseek/deepseek-v4.1-flash', 'effort': 'high',
       'max_tokens': 16000, 'judge_max_tokens': 4000, 'max_turns': 4,
       'prices_usd_per_mtok': {'input_tokens': .051, 'output_tokens': .567,
                             'cache_creation_input_tokens': .051, 'cache_read_input_tokens': .018}}
CASE = {'id': 'synthetic', 'brief': 'Read the ticket.', 'world': {}}
SNAP = (lambda p: None, lambda p: [])


def response(text='Done.', calls=None, usage=None, finish='stop'):
    message = {'role': 'assistant', 'content': text}
    if calls:
        message['tool_calls'] = [{'id': 'call1', 'type': 'function',
                                 'function': {'name': 'shell', 'arguments': json.dumps({'command': calls})}}]
        message['reasoning_details'] = [{'type': 'reasoning.text', 'text': 'synthetic reasoning'}]
        finish = 'tool_calls'
    return {'choices': [{'message': message, 'finish_reason': finish}],
            'usage': usage if usage is not None else {'prompt_tokens': 100, 'completion_tokens': 10,
                      'prompt_tokens_details': {'cached_tokens': 20}, 'cost': .00001}}


class OpenRouter(unittest.TestCase):
    def test_request_shape_tool_roundtrip_and_usage(self):
        sent = []
        replies = [response(None, 'gh issue view 4101'), response()]
        def post(url, body):
            self.assertEqual(url, 'https://openrouter.ai/api/v1/chat/completions')
            sent.append(copy.deepcopy(body))
            return replies.pop(0)
        t = driver.run_case(CASE, SET, SNAP, post, 1, budget_usd=1)
        self.assertEqual(t['stop'], 'end_turn', t)
        b = sent[0]
        self.assertEqual(b['model'], 'deepseek/deepseek-v4.1-flash')
        self.assertEqual(b['messages'][0], {'role': 'system', 'content': driver.SYSTEM})
        self.assertEqual(b['tools'][0]['type'], 'function')
        self.assertEqual(b['tools'][0]['function']['name'], 'shell')
        self.assertEqual(b['reasoning'], {'effort': 'high'})
        self.assertEqual(b['provider']['max_price'], {'prompt': .051, 'completion': .567})
        for key in ('system', 'thinking', 'output_config', 'cache_control'):
            self.assertNotIn(key, b)
        self.assertEqual(sent[1]['messages'][-1]['role'], 'tool')
        self.assertEqual(sent[1]['messages'][-1]['tool_call_id'], 'call1')
        self.assertIn('[exit ', sent[1]['messages'][-1]['content'])
        self.assertEqual(sent[1]['messages'][-2]['reasoning_details'][0]['text'], 'synthetic reasoning')
        self.assertEqual(t['usage']['input_tokens'], 160)
        self.assertEqual(t['usage']['cache_read_input_tokens'], 40)
        self.assertEqual(t['usage']['output_tokens'], 20)
        self.assertEqual(t['provider_usage'][0]['prompt_tokens'], 100)
        self.assertEqual(t['tokenizer'], 'DeepSeek (OpenRouter provider usage; not Claude tokens)')
        self.assertEqual(t['cost_usd'], .00002)

    def test_judge_and_every_attempt_obey_cap(self):
        calls = []
        def post(url, body):
            calls.append(copy.deepcopy(body))
            return response('Done.', usage={'prompt_tokens': 100, 'completion_tokens': 10, 'cost': .01})
        c = dict(CASE, expect={'final': 'Explain your decision.'})
        t = driver.run_case(c, SET, SNAP, post, 1, budget_usd=.011)
        self.assertEqual(t['stop'], 'cap', t)
        self.assertEqual(len(calls), 1)  # actor charged .01; judge cannot reserve .002268 plus prompt
        self.assertEqual(t['cost_usd'], .01)
        calls.clear()
        t = driver.run_case(c, SET, SNAP, post, 1, budget_usd=.001)
        self.assertEqual((t['stop'], calls), ('cap', []))
        with mock.patch.object(driver.time, 'sleep'):
            def uncertain(url, body):
                calls.append(body)
                raise driver.TransportError('synthetic timeout', uncertain=True)
            t = driver.run_case(CASE, SET, SNAP, uncertain, 1, budget_usd=1)
        self.assertEqual((t['stop'], len(calls)), ('error', 1))
        self.assertGreater(t['uncertain_usd'], .009)

    def test_missing_usage_or_malformed_response_keeps_reservation(self):
        for r in ({'choices': []}, response(usage={}), response(usage={'prompt_tokens': -1, 'completion_tokens': 1})):
            with self.subTest(response=r):
                t = driver.run_case(CASE, SET, SNAP, lambda url, body: r, 1, budget_usd=1)
                self.assertEqual(t['stop'], 'error', t)
                self.assertGreater(t['uncertain_usd'], .009)

    def test_isolation_model_commands_never_spawn_real_tools(self):
        commands = ['gh issue comment 4101 --body synthetic', 'room-cli thread spawn --prompt synthetic',
                    'curl https://example.invalid', 'python3 -c "import os; os.system(\"gh auth token\")"',
                    '/usr/bin/gh auth token']
        for cmd in commands:
            with self.subTest(command=cmd):
                replies = [response(None, cmd), response()]
                with mock.patch.object(subprocess, 'run', side_effect=AssertionError('real process')), \
                     mock.patch.object(os, 'system', side_effect=AssertionError('real shell')):
                    t = driver.run_case(CASE, SET, SNAP, lambda url, body: replies.pop(0), 1, budget_usd=1)
                self.assertEqual(t['stop'], 'end_turn', t)
                self.assertEqual(len(t['provider_usage']), 2)

    def test_bearer_auth_and_fixed_endpoint(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{}'
        with mock.patch.object(driver.urllib.request, 'urlopen', return_value=Reply()) as send:
            driver.http_post('synthetic-key', 'openrouter')('https://openrouter.ai/api/v1/chat/completions', {})
            req = send.call_args.args[0]
            self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-key')
            self.assertIsNone(req.get_header('X-api-key'))
            with self.assertRaises(ValueError):
                driver.http_post('synthetic-key', 'openrouter')('https://example.invalid', {})
        self.assertEqual(send.call_count, 1)

    def test_crash_after_send_keeps_cost_and_resume_never_repeats(self):
        cid = 'i1-ci-pending-on-changed-head'
        def killed(url, body):
            raise KeyboardInterrupt('synthetic process death after request')
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'synthetic'}), \
                mock.patch.object(driver, 'http_post', return_value=killed):
            with self.assertRaises(KeyboardInterrupt):
                E.main(['run', '--out', d, '--case', cid])
            saved = json.loads(Path(d, f'{cid}.r1.json').read_text())
            self.assertEqual(saved['stop'], 'error')
            self.assertGreater(saved['uncertain_usd'], .009)
            self.assertEqual(saved['uncertain_usd'], saved['cost_usd'])
            # Limit this synthetic crash test to one repeat so resume only reads the saved record.
            man = json.loads(Path(d, 'manifest.json').read_text())
            for rep in (2, 3):
                Path(d, f'{cid}.r{rep}.json').write_text(json.dumps(dict(saved, repeat=rep)))
            with mock.patch.object(driver, 'http_post', side_effect=lambda *a: mock.Mock(side_effect=AssertionError('repeated charge'))):
                self.assertEqual(E.main(['run', '--out', d, '--case', cid]), 0)

    def test_dotenv_key_and_token_report_need_no_api(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            env = Path(d, 'key.env')
            env.write_text('OPENROUTER_API_KEY=synthetic-key\n')
            self.assertEqual(E._key(type('Args', (), {'env_file': str(env)})()), 'synthetic-key')
            out = Path(d, 'baseline')
            out.mkdir()
            Path(out, 'manifest.json').write_text(json.dumps({'settings': SET, 'revision': {'commit': 'synthetic'}}))
            tr = {'case': 'synthetic', 'repeat': 1, 'usage': {'input_tokens': 80, 'output_tokens': 10,
                  'cache_read_input_tokens': 20}, 'provider_usage': [response()['usage']], 'cost_usd': .00001}
            Path(out, 'synthetic.r1.json').write_text(json.dumps(tr))
            with mock.patch.object(driver, 'http_post', side_effect=AssertionError('token count must be free')):
                self.assertEqual(E.main(['tokens', '--results', str(out), '--out', str(Path(d, 'tokens.json'))]), 0)
            report = json.loads(Path(d, 'tokens.json').read_text())
            self.assertEqual(report['total']['input_tokens'], 100)
            self.assertEqual(report['total']['cached_input_tokens'], 20)
            self.assertEqual(report['total']['output_tokens'], 10)
            self.assertIn('not Claude', report['tokenizer'])


if __name__ == '__main__':
    unittest.main()
