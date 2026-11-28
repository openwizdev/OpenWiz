#!/usr/bin/env python3
import json
import os
import shutil
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
ENV_KEYS = (
    'OPENWIZ_MEMO_ENABLED', 'OPENWIZ_MEMO_ENDPOINT', 'OPENWIZ_MEMO_API_KEY',
    'OPENWIZ_MEMO_MODEL', 'OPENWIZ_MEMO_TRAIN', 'OPENWIZ_MEMO_WANDB',
    'WANDB_MODE', 'WANDB_DISABLED', 'WANDB_API_KEY',
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append((self.path, self.headers.get('Authorization'), body))
        if self.server.mode == 'truncated':
            self.wfile.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n20\r\npartial')
            self.wfile.flush()
            self.close_connection = True
            return
        responses = {
            'fail': (b'no', 500),
            'empty': (json.dumps({'choices': [{'message': {'content': '  '}}]}).encode(), 200),
            'garbage': (b'{', 200),
            'ok': (json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic memory answer.'}}]}).encode(), 200),
        }
        payload, status = responses[self.server.mode]
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, fmt, *args):
        return


class Server:
    def __init__(self, mode='ok'):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.mode, self.httpd.seen = mode, []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self):
        host, port = self.httpd.server_address
        return f'http://{host}:{port}/v1'

    def close(self):
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(extra)
    return env


def write_settings(path, **overrides):
    data = dict(memo.defaults(), **overrides)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, sort_keys=True) + '\n', encoding='utf-8')
    return target


def write_docs(root, files):
    for rel, text in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def run_tool(args, env=None):
    res = subprocess.run(
        [sys.executable, '-I', str(TOOL), *args],
        capture_output=True, text=True, env=clean_env() if env is None else env, cwd=REPO)
    return res.returncode, res.stdout, res.stderr


def make_fake_bins(root, head=memo.PIN, dirty=False, include_git=True):
    bindir = Path(root) / 'bin'
    bindir.mkdir(parents=True, exist_ok=True)
    status_out = ' M sft_training/sft_lora_pipeline.py' if dirty else ''
    scripts = {
        'accelerate': (
            '#!/bin/sh\n'
            'printf \'accelerate %s\\n\' "$*" >> "$MEMO_FAKE_LOG"\n'
            'printf \'env WANDB_MODE=%s WANDB_DISABLED=%s WANDB_API_KEY=%s\\n\' '
            '"${WANDB_MODE:-}" "${WANDB_DISABLED:-}" "${WANDB_API_KEY:-}" >> "$MEMO_FAKE_LOG"\n'
            'exit 0\n'
        ),
    }
    if include_git:
        scripts['git'] = (
            '#!/bin/sh\n'
            'printf \'git %s\\n\' "$*" >> "$MEMO_FAKE_LOG"\n'
            'if [ "$1" = init ]; then\n'
            '  mkdir -p "$2/.git" "$2/sft_training"\n'
            '  : > "$2/sft_training/sft_lora_pipeline.py"\n'
            '  : > "$2/sft_training/accelerate_config.yaml"\n'
            '  exit 0\n'
            'fi\n'
            'if [ "$1" = -C ]; then\n'
            '  dir="$2"; shift 2\n'
            '  case "$1 $2" in\n'
            '    "rev-parse --show-toplevel") printf \'%s\\n\' "$dir" ;;\n'
            f'    "rev-parse --verify") printf \'%s\\n\' "{head}" ;;\n'
            f'    "remote get-url") printf \'%s\\n\' "{memo.UPSTREAM}" ;;\n'
            f'    "status --porcelain") [ -n "{status_out}" ] && printf \'%s\\n\' "{status_out}" || true ;;\n'
            '  esac\n'
            'fi\nexit 0\n'
        )
    for name, body in scripts.items():
        path = bindir / name
        path.write_text(body, encoding='utf-8')
        os.chmod(path, 0o755)
    return bindir


class MemoTests(unittest.TestCase):
    def test_shipped_settings_are_experimental_and_off(self):
        s = memo.read_settings(REPO / 'docs' / 'agents' / 'memo.json')
        self.assertEqual((s['schema'], s['experimental'], s['enabled'], s['endpoint'], s['fallback'], s['api_key_env']),
                         ('openwiz.memo.v1', True, False, None, 'retrieval', None))

    def test_settings_refuse_bad_shape_non_loopback_http_and_bad_ipv6(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'memo.json'
            for raw in ('{"schema": "openwiz.memo.v1", "enabled": "yes"}\n',
                        '{"schema": "openwiz.memo.v1", "schema": "openwiz.memo.v1"}\n'):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(memo.GiveUp):
                    memo.read_settings(path)
            for override in (
                {'experimental': False}, {'endpoint': 'http://user:secret@127.0.0.1:8000/v1'},
                {'endpoint': 'http://memo.example.com/v1'}, {'endpoint': 'http://192.0.2.1:8000/v1'},
                {'endpoint': 'http://[::1/v1'}, {'endpoint': 'http://127.0.0.1:99999/v1'},
                {'api_key_env': 'UNRELATED_SECRET'}, {'corpus': '/tmp/corpus'},
            ):
                write_settings(path, **override)
                with self.assertRaises(memo.GiveUp, msg=str(override)):
                    memo.read_settings(path)
            write_settings(path, endpoint='http://[::1/v1')
            code, out, err = run_tool(['status', '--settings', str(path)])
            self.assertEqual((code, err, json.loads(out)['error']['kind']), (2, '', 'usage'))
            for ok in ('https://memo.example.com/v1', 'http://127.0.0.1:8000/v1',
                       'http://[::1]:8000/v1', 'http://localhost:8000/v1'):
                memo.check_endpoint(ok)

    def test_checkout_settings_cannot_enable_redirect_or_steal_credentials(self):
        attacker, operator = Server(), Server()
        self.addCleanup(attacker.close)
        self.addCleanup(operator.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_docs(root, {'docs/note.md': 'Local checkout note stays local.\n'})
            cfg = root / 'docs' / 'agents' / 'memo.json'
            write_settings(cfg, enabled=True, endpoint=attacker.endpoint, api_key_env='UNRELATED_SECRET')
            env = clean_env(UNRELATED_SECRET='synthetic-other-secret', OPENWIZ_MEMO_API_KEY='synthetic-memo-key')
            code, out, err = run_tool(['ask', '--root', str(root), 'local checkout note'], env=env)
            self.assertEqual((code, err, attacker.httpd.seen), (2, '', []))
            write_settings(cfg, enabled=True, endpoint=attacker.endpoint, api_key_env='OPENWIZ_MEMO_API_KEY')
            code, out, err = run_tool(['ask', '--root', str(root), 'local checkout note'], env=env)
            rep = json.loads(out)
            self.assertEqual((code, err, rep['backend'], rep['fallback_reason'], attacker.httpd.seen),
                             (0, '', 'retrieval', 'disabled', []))
            code, out, err = run_tool(['status', '--root', str(root)], env=env)
            st = json.loads(out)
            self.assertEqual((code, err, st['enabled'], st['endpoint']), (0, '', False, None))
            code, out, err = run_tool(['ask', '--root', str(root), 'local checkout note'],
                                      env=clean_env(OPENWIZ_MEMO_ENABLED='1'))
            self.assertEqual((code, err, attacker.httpd.seen), (2, '', []))
            op_env = clean_env(OPENWIZ_MEMO_ENABLED='1', OPENWIZ_MEMO_ENDPOINT=operator.endpoint,
                               OPENWIZ_MEMO_API_KEY='synthetic-memo-key')
            code, out, err = run_tool(['ask', '--root', str(root), 'local checkout note'], env=op_env)
            self.assertEqual((code, err, json.loads(out)['backend'], attacker.httpd.seen), (0, '', 'memo', []))
            self.assertEqual(operator.httpd.seen[0][1], 'Bearer synthetic-memo-key')

    def test_disabled_settings_use_retrieval_and_skip_the_endpoint(self):
        server = Server()
        self.addCleanup(server.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_docs(root, {
                'docs/fleet.md': 'The fleet merges approved pull requests.\n',
                '.openwiz/brain/decisions/colour.md': 'The grill confirmed the synthetic colour blue.\n',
            })
            loaded = memo.read_settings(write_settings(root / 'memo.json', enabled=False, endpoint=server.endpoint))
            rep = memo.ask(root, loaded, 'fleet merges approved pull requests', env={})
            self.assertEqual((rep['backend'], rep['fallback_reason'], rep['provenance']),
                             ('retrieval', 'disabled', ['docs/fleet.md']))
            brain = memo.ask(root, loaded, 'grill confirmed synthetic colour', env={})
            self.assertEqual((brain['provenance'], server.httpd.seen), (['.openwiz/brain/decisions/colour.md'], []))

    def test_a_memory_answer_has_no_provenance(self):
        server = Server()
        self.addCleanup(server.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            loaded = memo.read_settings(write_settings(root / 'memo.json', api_key_env='OPENWIZ_MEMO_API_KEY'))
            env = {'OPENWIZ_MEMO_ENABLED': '1', 'OPENWIZ_MEMO_ENDPOINT': server.endpoint,
                   'OPENWIZ_MEMO_API_KEY': 'synthetic-memo-key'}
            rep = memo.ask(root, loaded, 'Where is the synthetic fleet?', env=env)
            self.assertEqual((rep['backend'], rep['fallback_reason'], rep['provenance'], rep['sources'], rep['answer']),
                             ('memo', None, None, [], 'Synthetic memory answer.'))
            path, auth, body = server.httpd.seen[0]
            sent = json.loads(body)
            self.assertEqual((path, auth, sent['model'], sent['temperature']),
                             ('/v1/chat/completions', 'Bearer synthetic-memo-key', 'memo', 0))
            self.assertNotIn('synthetic-memo-key', json.dumps(rep))

    def test_endpoint_failures_and_truncated_chunk_fall_back_to_retrieval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_docs(root, {'docs/note.md': 'Builders open a pull request when the ticket is done.\n'})
            loaded = memo.read_settings(write_settings(root / 'memo.json'))
            for mode, reason in (('fail', 'endpoint_error'), ('empty', 'empty'),
                                 ('garbage', 'endpoint_error'), ('truncated', 'endpoint_error')):
                server = Server(mode)
                self.addCleanup(server.close)
                env = {'OPENWIZ_MEMO_ENABLED': '1', 'OPENWIZ_MEMO_ENDPOINT': server.endpoint}
                rep = memo.ask(root, loaded, 'Builders open a pull request', env=env)
                self.assertEqual((rep['backend'], rep['fallback_reason'], rep['provenance']),
                                 ('retrieval', reason, ['docs/note.md']), mode)

    def test_a_closed_port_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_docs(root, {'docs/note.md': 'Synthetic coverage text stays here.\n'})
            loaded = memo.read_settings(write_settings(root / 'memo.json', timeout_seconds=1))
            env = {'OPENWIZ_MEMO_ENABLED': '1', 'OPENWIZ_MEMO_ENDPOINT': 'http://127.0.0.1:9/v1'}
            rep = memo.ask(root, loaded, 'totally-unmatched-question', env=env)
            self.assertEqual((rep['backend'], rep['fallback_reason'], rep['answer']),
                             ('retrieval', 'endpoint_error', 'The corpus does not cover that question.'))

    def test_retrieval_refuses_symlinked_roots_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sibling = base / 'sibling'
            write_docs(sibling, {'note.md': 'Sibling secret alpha token stays private.\n'})
            root = base / 'repo'
            (root / '.openwiz').mkdir(parents=True)
            os.symlink(sibling, root / 'docs')
            os.symlink(sibling, root / '.openwiz' / 'brain')
            rep = memo.ask(root, memo.defaults(), 'Sibling secret alpha token', env={})
            self.assertEqual(rep['provenance'], [])
            self.assertNotIn('Sibling secret', rep['answer'])
            (root / 'docs').unlink()
            (root / 'docs').mkdir()
            os.symlink(sibling, root / 'docs' / 'sub')
            self.assertEqual(memo.ask(root, memo.defaults(), 'Sibling secret alpha token', env={})['provenance'], [])

    def test_retrieval_keeps_text_past_800_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            long_para = ('filler ' * 140) + 'uniquetailmarker900 appears past eight hundred.\n\n'
            grouped = ('alpha ' * 85) + '\n\n' + ('beta ' * 85) + 'uniquegroupmarker1000 survives grouping.\n'
            write_docs(root, {'docs/long.md': long_para + grouped})
            for needle in ('uniquetailmarker900', 'uniquegroupmarker1000'):
                rep = memo.ask(root, memo.defaults(), needle, env={})
                self.assertEqual(rep['provenance'], ['docs/long.md'], needle)
                self.assertIn(needle, rep['answer'])

    def test_status_and_blank_question(self):
        code, out, err = run_tool(['status', '--root', str(REPO)])
        rep = json.loads(out)
        self.assertEqual((code, err, rep['enabled'], rep['backend'], rep['executive'], rep['memo_provenance']),
                         (0, '', False, 'retrieval', 'any', None))
        code, out, err = run_tool(['ask', '--root', str(REPO), '   '])
        self.assertEqual((code, err, json.loads(out)['error']['kind']), (2, '', 'usage'))

    def test_build_plan_overlap_and_unmanaged_output_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root / 'docs'
            write_docs(corpus, {'page.md': 'Synthetic page.\n'})
            out = root / 'out'
            code, stdout, err = run_tool(['build', '--corpus', str(corpus), '--out', str(out)])
            plan = json.loads(stdout)
            self.assertEqual((code, err, plan['pin'], plan['license'], plan['trains'], plan['documents']),
                             (0, '', memo.PIN, 'MIT', False, 1))
            self.assertFalse(out.exists())
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(corpus / 'out'), '--execute'])
            self.assertEqual((code, err, (corpus / 'out').exists()), (2, '', False))
            parent_out = root / 'build'
            write_docs(parent_out, {'corpus/original.md': 'Keep original corpus.\n'})
            code, _, err = run_tool(['build', '--corpus', str(parent_out / 'corpus'), '--out', str(parent_out), '--execute'])
            self.assertEqual((code, err), (2, ''))
            self.assertEqual((parent_out / 'corpus' / 'original.md').read_text(encoding='utf-8'), 'Keep original corpus.\n')
            unmanaged = root / 'existing'
            write_docs(unmanaged, {'keep.txt': 'keep\n', 'corpus/precious.md': 'precious\n'})
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(unmanaged), '--execute'])
            self.assertEqual((code, err, (unmanaged / 'memo-build.sh').exists()), (2, '', False))
            self.assertEqual((unmanaged / 'corpus' / 'precious.md').read_text(encoding='utf-8'), 'precious\n')

    def test_execute_stages_script_and_docs_match_prepared_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            corpus, out = Path(folder) / 'docs', Path(folder) / 'out'
            write_docs(corpus, {'nested/page.md': 'Synthetic page.\n'})
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--execute'])
            self.assertEqual((code, err), (0, ''))
            self.assertEqual((out / 'corpus' / 'nested' / 'page.md').read_text(encoding='utf-8'), 'Synthetic page.\n')
            script = (out / 'memo-build.sh').read_text(encoding='utf-8')
            for token in (memo.PIN, memo.UPSTREAM, 'sft_training/sft_lora_pipeline.py', 'OPENWIZ_MEMO_TRAIN', 'WANDB_MODE=disabled'):
                self.assertIn(token, script)
            self.assertFalse((out / 'MeMo').exists())
            self.assertIn('independently prepared', (REPO / 'docs' / 'memo.md').read_text(encoding='utf-8'))

    def test_train_switch_checked_before_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root / 'docs'
            write_docs(corpus, {'page.md': 'Synthetic page.\n'})
            fresh, staged = root / 'fresh', root / 'staged'
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(fresh), '--train'])
            self.assertEqual((code, err, fresh.exists()), (2, '', False))
            write_docs(staged, {'corpus/keep.md': 'old\n', 'plan.json': '{"sentinel": true}\n'})
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(staged), '--train'])
            self.assertEqual((code, err), (2, ''))
            self.assertEqual((staged / 'corpus' / 'keep.md').read_text(encoding='utf-8'), 'old\n')
            self.assertEqual((staged / 'plan.json').read_text(encoding='utf-8'), '{"sentinel": true}\n')

    def test_train_verifies_pinned_checkout_and_disables_wandb_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus, out, log = root / 'docs', root / 'out', root / 'fake.log'
            write_docs(corpus, {'page.md': 'Synthetic page.\n'})
            bindir = make_fake_bins(root)
            env = clean_env(OPENWIZ_MEMO_TRAIN='1', WANDB_API_KEY='synthetic-wandb-key',
                            PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''), MEMO_FAKE_LOG=str(log))
            missing = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual((missing[0], missing[2], log.exists()), (2, '', False))
            (out / 'reflection-qa.json').write_text('[]\n', encoding='utf-8')
            write_docs(out / 'MeMo', {'sft_training/sft_lora_pipeline.py': '', 'sft_training/accelerate_config.yaml': ''})
            bad_non_git = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual((bad_non_git[0], bad_non_git[2], log.exists()), (2, '', False))
            real_git_bin = make_fake_bins(root / 'realgit', include_git=False)
            real_env = dict(env, PATH=str(real_git_bin) + os.pathsep + os.environ.get('PATH', ''))
            subprocess.run(['git', 'init', '-q', str(out / 'MeMo')], check=True)
            subprocess.run(['git', '-C', str(out / 'MeMo'), 'remote', 'add', 'origin', memo.UPSTREAM], check=True)
            subprocess.run(['git', '-C', str(out / 'MeMo'), '-c', 'user.name=Synthetic',
                            '-c', 'user.email=synthetic@example.com', 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(out / 'MeMo'), '-c', 'user.name=Synthetic',
                            '-c', 'user.email=synthetic@example.com', 'commit', '-qm', 'wrong pin'], check=True)
            bad_real = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=real_env)
            self.assertEqual((bad_real[0], bad_real[2], log.exists()), (2, '', False))
            dirty_env = dict(env, PATH=str(make_fake_bins(root / 'dirty', dirty=True)) + os.pathsep + os.environ.get('PATH', ''))
            bad_dirty = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=dirty_env)
            self.assertEqual((bad_dirty[0], bad_dirty[2]), (2, ''))
            self.assertNotIn('accelerate', log.read_text(encoding='utf-8'))
            log.unlink()
            shutil.rmtree(out / 'MeMo')
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'], env=env)
            self.assertEqual((code, err), (0, ''))
            rec = log.read_text(encoding='utf-8')
            self.assertIn(memo.PIN, rec)
            self.assertIn('--report_to none', rec)
            self.assertNotIn('--wandb_run_name', rec)
            self.assertIn('WANDB_MODE=disabled WANDB_DISABLED=true WANDB_API_KEY=\n', rec)
            self.assertNotIn('synthetic-wandb-key', rec)
            log.unlink()
            code, _, err = run_tool(['build', '--corpus', str(corpus), '--out', str(out), '--train'],
                                    env=dict(env, OPENWIZ_MEMO_WANDB='1'))
            self.assertEqual((code, err), (0, ''))
            opt = log.read_text(encoding='utf-8')
            self.assertIn('--report_to wandb --wandb_run_name openwiz-memo', opt)
            self.assertIn('WANDB_API_KEY=synthetic-wandb-key', opt)


if __name__ == '__main__':
    unittest.main()
