#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memo

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'tools' / 'memo' / 'memo.py'


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length)
        self.server.seen.append((self.path, self.headers.get('Authorization'), body))
        if self.server.mode == 'hang':
            self.server.wait.wait(5)
            return
        if self.server.mode == 'fail':
            payload = b'no'
            status = 500
        elif self.server.mode == 'empty':
            payload = json.dumps({'choices': [{'message': {'content': '  '}}]}).encode()
            status = 200
        elif self.server.mode == 'garbage':
            payload = b'{'
            status = 200
        else:
            payload = json.dumps({
                'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic memory answer.'}}],
            }).encode()
            status = 200
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class Server:
    def __init__(self, mode='ok'):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.mode = mode
        self.httpd.seen = []
        self.httpd.wait = threading.Event()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self):
        host, port = self.httpd.server_address
        return f'http://{host}:{port}/v1'

    def close(self):
        self.httpd.wait.set()
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()


def write_settings(folder, **overrides):
    data = memo.defaults()
    data.update(overrides)
    path = Path(folder) / 'memo.json'
    path.write_text(json.dumps(data, sort_keys=True) + '\n', encoding='utf-8')
    return path


def run_tool(args, env=None):
    result = subprocess.run(
        [sys.executable, '-I', str(TOOL), *args],
        capture_output=True, text=True, env=env, cwd=REPO)
    return result.returncode, result.stdout, result.stderr


class MemoTests(unittest.TestCase):
    def test_shipped_settings_are_experimental_and_off(self):
        settings = memo.read_settings(REPO / 'docs' / 'agents' / 'memo.json')
        self.assertEqual(settings['schema'], 'openwiz.memo.v1')
        self.assertTrue(settings['experimental'])
        self.assertFalse(settings['enabled'])
        self.assertEqual(settings['fallback'], 'retrieval')
        self.assertIsNone(settings['api_key_env'])

    def test_settings_refuse_a_bad_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'memo.json'
            path.write_text('{"schema": "openwiz.memo.v1", "enabled": "yes"}\n', encoding='utf-8')
            with self.assertRaises(memo.GiveUp):
                memo.read_settings(path)
            data = memo.defaults()
            data['experimental'] = False
            path.write_text(json.dumps(data) + '\n', encoding='utf-8')
            with self.assertRaises(memo.GiveUp):
                memo.read_settings(path)
            data = memo.defaults()
            data['endpoint'] = 'http://user:secret@127.0.0.1:8000/v1'
            path.write_text(json.dumps(data) + '\n', encoding='utf-8')
            with self.assertRaises(memo.GiveUp):
                memo.read_settings(path)
            data = memo.defaults()
            data['corpus'] = '/tmp/corpus'
            path.write_text(json.dumps(data) + '\n', encoding='utf-8')
            with self.assertRaises(memo.GiveUp):
                memo.read_settings(path)
            path.write_text(
                '{"schema": "openwiz.memo.v1", "schema": "openwiz.memo.v1"}\n', encoding='utf-8')
            with self.assertRaises(memo.GiveUp) as caught:
                memo.read_settings(path)
            self.assertIn('duplicate', caught.exception.message)

    def test_disabled_settings_use_retrieval_and_skip_the_endpoint(self):
        server = Server()
        self.addCleanup(server.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'docs' / 'fleet.md').write_text(
                'The fleet merges approved pull requests.\n', encoding='utf-8')
            (root / '.openwiz' / 'brain' / 'decisions').mkdir(parents=True)
            (root / '.openwiz' / 'brain' / 'decisions' / 'colour.md').write_text(
                'The grill confirmed the synthetic colour blue.\n', encoding='utf-8')
            settings = write_settings(root, enabled=False, endpoint=server.endpoint)
            loaded = memo.read_settings(settings)
            report = memo.ask(root, loaded, 'fleet merges approved pull requests')
            self.assertEqual(report['backend'], 'retrieval')
            self.assertEqual(report['fallback_reason'], 'disabled')
            self.assertEqual(report['provenance'], ['docs/fleet.md'])
            self.assertIn('fleet merges approved pull requests', report['answer'])
            brain = memo.ask(root, loaded, 'grill confirmed synthetic colour')
            self.assertEqual(brain['provenance'], ['.openwiz/brain/decisions/colour.md'])
            self.assertEqual(server.httpd.seen, [])

    def test_a_memory_answer_has_no_provenance(self):
        server = Server()
        self.addCleanup(server.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = write_settings(
                root, enabled=True, endpoint=server.endpoint, api_key_env='OPENWIZ_MEMO_API_KEY')
            loaded = memo.read_settings(settings)
            os.environ['OPENWIZ_MEMO_API_KEY'] = 'synthetic-memo-key'
            self.addCleanup(os.environ.pop, 'OPENWIZ_MEMO_API_KEY', None)
            report = memo.ask(root, loaded, 'Where is the synthetic fleet?')
            self.assertEqual(report['backend'], 'memo')
            self.assertIsNone(report['fallback_reason'])
            self.assertIsNone(report['provenance'])
            self.assertEqual(report['sources'], [])
            self.assertEqual(report['answer'], 'Synthetic memory answer.')
            path, authorization, body = server.httpd.seen[0]
            self.assertEqual(path, '/v1/chat/completions')
            self.assertEqual(authorization, 'Bearer synthetic-memo-key')
            sent = json.loads(body)
            self.assertEqual(sent['model'], 'memo')
            self.assertEqual(sent['temperature'], 0)
            self.assertNotIn('claude', body.decode())
            self.assertNotIn('codex', body.decode())
            self.assertEqual(sent['messages'][1]['content'], 'Where is the synthetic fleet?')
            self.assertNotIn('synthetic-memo-key', json.dumps(report))

    def test_endpoint_failures_fall_back_to_retrieval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'docs' / 'note.md').write_text(
                'Builders open a pull request when the ticket is done.\n', encoding='utf-8')
            for mode, reason in (('fail', 'endpoint_error'), ('empty', 'empty'), ('garbage', 'endpoint_error')):
                server = Server(mode)
                self.addCleanup(server.close)
                loaded = memo.read_settings(write_settings(root, enabled=True, endpoint=server.endpoint))
                report = memo.ask(root, loaded, 'Builders open a pull request')
                self.assertEqual(report['backend'], 'retrieval', mode)
                self.assertEqual(report['fallback_reason'], reason, mode)
                self.assertEqual(report['provenance'], ['docs/note.md'])

    def test_a_closed_port_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'docs' / 'note.md').write_text('Synthetic coverage text stays here.\n', encoding='utf-8')
            loaded = memo.read_settings(write_settings(
                root, enabled=True, endpoint='http://127.0.0.1:9/v1', timeout_seconds=1))
            report = memo.ask(root, loaded, 'totally-unmatched-question')
            self.assertEqual(report['backend'], 'retrieval')
            self.assertEqual(report['fallback_reason'], 'endpoint_error')
            self.assertEqual(report['answer'], 'The corpus does not cover that question.')

    def test_status_names_any_executive_and_the_default_backend(self):
        code, out, err = run_tool(['status', '--root', str(REPO)])
        self.assertEqual((code, err), (0, ''))
        report = json.loads(out)
        self.assertFalse(report['enabled'])
        self.assertEqual(report['backend'], 'retrieval')
        self.assertEqual(report['executive'], 'any')
        self.assertIsNone(report['memo_provenance'])
        self.assertTrue(report['experimental'])

    def test_the_command_refuses_a_blank_question(self):
        code, out, err = run_tool(['ask', '--root', str(REPO), '   '])
        self.assertEqual(code, 2)
        self.assertEqual(err, '')
        self.assertEqual(json.loads(out)['error']['kind'], 'usage')

    def test_build_plan_does_not_train_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            corpus = Path(folder) / 'docs'
            corpus.mkdir()
            (corpus / 'page.md').write_text('Synthetic page.\n', encoding='utf-8')
            out = Path(folder) / 'out'
            code, stdout, err = run_tool(['build', '--corpus', str(corpus), '--out', str(out)])
            self.assertEqual((code, err), (0, ''))
            plan = json.loads(stdout)
            self.assertEqual(plan['pin'], memo.PIN)
            self.assertEqual(plan['license'], 'MIT')
            self.assertFalse(plan['trains'])
            self.assertEqual(plan['synthesis'], list(memo.SYNTHESIS))
            self.assertEqual(plan['documents'], 1)
            self.assertFalse(out.exists())

    def test_the_output_folder_must_sit_outside_the_corpus(self):
        with tempfile.TemporaryDirectory() as folder:
            corpus = Path(folder) / 'docs'
            corpus.mkdir()
            (corpus / 'page.md').write_text('Synthetic page.\n', encoding='utf-8')
            code, stdout, err = run_tool([
                'build', '--corpus', str(corpus), '--out', str(corpus / 'out'), '--execute'])
            self.assertEqual(code, 2)
            self.assertEqual(err, '')
            self.assertIn('outside the corpus', json.loads(stdout)['error']['message'])
            self.assertFalse((corpus / 'out').exists())

    def test_execute_stages_the_upstream_script_without_running_it(self):
        with tempfile.TemporaryDirectory() as folder:
            corpus = Path(folder) / 'docs'
            corpus.mkdir()
            (corpus / 'nested').mkdir()
            (corpus / 'nested' / 'page.md').write_text('Synthetic page.\n', encoding='utf-8')
            out = Path(folder) / 'out'
            code, stdout, err = run_tool([
                'build', '--corpus', str(corpus), '--out', str(out), '--execute'])
            self.assertEqual((code, err), (0, ''))
            report = json.loads(stdout)
            self.assertFalse(report['trains'])
            self.assertIsNone(report['script_exit'])
            self.assertEqual((out / 'corpus' / 'nested' / 'page.md').read_text(encoding='utf-8'),
                             'Synthetic page.\n')
            script = (out / 'memo-build.sh').read_text(encoding='utf-8')
            self.assertIn(memo.PIN, script)
            self.assertIn('https://github.com/arunv3rma/MeMo.git', script)
            self.assertIn('sft_training/sft_lora_pipeline.py', script)
            self.assertIn('OPENWIZ_MEMO_TRAIN', script)
            self.assertFalse((out / 'MeMo').exists())

    def test_train_stays_off_without_the_gpu_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            corpus = Path(folder) / 'docs'
            corpus.mkdir()
            (corpus / 'page.md').write_text('Synthetic page.\n', encoding='utf-8')
            out = Path(folder) / 'out'
            env = os.environ.copy()
            env.pop('OPENWIZ_MEMO_TRAIN', None)
            code, stdout, err = run_tool(
                ['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual(code, 2)
            self.assertEqual(err, '')
            body = json.loads(stdout)
            self.assertEqual(body['error']['kind'], 'usage')
            self.assertFalse((out / 'MeMo').exists())
            self.assertIn('memo-build.sh', os.listdir(out))

    def test_train_invokes_the_upstream_command_only_when_asked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root / 'docs'
            corpus.mkdir()
            (corpus / 'page.md').write_text('Synthetic page.\n', encoding='utf-8')
            out = root / 'out'
            log = root / 'fake.log'
            bindir = root / 'bin'
            bindir.mkdir()
            (bindir / 'git').write_text(
                '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$MEMO_FAKE_LOG"\n'
                'if [ "$1" = init ]; then mkdir -p "$2/sft_training"; fi\nexit 0\n',
                encoding='utf-8')
            (bindir / 'accelerate').write_text(
                '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$MEMO_FAKE_LOG"\nexit 0\n',
                encoding='utf-8')
            os.chmod(bindir / 'git', 0o755)
            os.chmod(bindir / 'accelerate', 0o755)
            env = os.environ.copy()
            env['OPENWIZ_MEMO_TRAIN'] = '1'
            env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')
            env['MEMO_FAKE_LOG'] = str(log)
            missing = run_tool(
                ['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual(missing[0], 2)
            self.assertFalse(missing[2])
            self.assertFalse(json.loads(missing[1])['trains'])
            self.assertEqual(json.loads(missing[1])['script_exit'], 2)
            self.assertFalse(log.exists())
            (out / 'reflection-qa.json').write_text('{}\n', encoding='utf-8')
            code, stdout, err = run_tool(
                ['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual((code, err), (0, ''))
            report = json.loads(stdout)
            self.assertTrue(report['trains'])
            self.assertEqual(report['script_exit'], 0)
            recorded = log.read_text(encoding='utf-8')
            self.assertIn(memo.PIN, recorded)
            self.assertIn('sft_lora_pipeline.py', recorded)
            self.assertNotIn('synthetic-memo-key', recorded)


if __name__ == '__main__':
    unittest.main()
