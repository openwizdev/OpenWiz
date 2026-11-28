#!/usr/bin/env python3
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DRIVER = os.path.join(ROOT, 'adapters', 'openclaw', 'driver')
FAKE = os.path.join(ROOT, 'adapters', 'openclaw', 'fixtures', 'bin', 'acpx')
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}
MARKER = {'auth': {'synthetic-race-marker': 'marker'}}
CLAUDE = ['npx', '-y', '--package=@agentclientprotocol/claude-agent-acp@^0.95.0', '--', 'claude-agent-acp']
STAND_IN = '''import json, os, sys
log, work, launch = sys.argv[1], sys.argv[2], sys.argv[3]
seen = {'cwd': os.getcwd(), 'home': os.environ.get('HOME'), 'requests': [], 'replies': []}
for raw in sys.stdin:
    msg = json.loads(raw)
    if 'method' not in msg:
        seen['replies'].append(msg)
        continue
    seen['requests'].append({'method': msg.get('method'), 'cwd': (msg.get('params') or {}).get('cwd')})
    if msg.get('method') == 'session/new':
        for out in (
            {'jsonrpc': '2.0', 'id': 10, 'method': 'fs/read_text_file',
             'params': {'sessionId': 's1', 'path': os.path.join(work, 'note.txt')}},
            {'jsonrpc': '2.0', 'id': 11, 'method': 'fs/write_text_file',
             'params': {'sessionId': 's1', 'path': os.path.join(work, 'note.txt'), 'content': 'hi'}},
            {'jsonrpc': '2.0', 'id': 12, 'method': 'fs/read_text_file',
             'params': {'sessionId': 's1', 'path': os.path.join(work, '..', 'outside.txt')}},
            {'jsonrpc': '2.0', 'id': 13, 'method': 'terminal/create',
             'params': {'sessionId': 's1', 'command': 'pwd'}},
            {'jsonrpc': '2.0', 'id': 14, 'method': 'fs/write_text_file',
             'params': {'sessionId': 's1', 'path': os.path.join(launch, '.acpxrc.json'), 'content': '{}'}},
            {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'sessionId': 's1'}},
        ):
            print(json.dumps(out), flush=True)
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {}}), flush=True)
with open(log, 'w') as handle:
    json.dump(seen, handle)
'''

ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)


def owned():
    children = {}
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            with open('/proc/%s/stat' % pid) as handle:
                fields = handle.read().rpartition(')')[2].split()
        except OSError:
            continue
        if fields[0] != 'Z':
            children.setdefault(int(fields[1]), []).append(int(pid))
    found, todo = set(), [os.getpid()]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return sorted(found)


class AcpxProjectConfig(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.calls = os.path.join(self.folder, 'calls')
        self.state = os.path.join(self.folder, 'state')
        self.home = os.path.join(self.folder, 'home')
        os.mkdir(self.home)
        self.env = dict(HOME=self.home, LANG='C.UTF-8', FAKE_ACPX_CALLS=self.calls,
                        FAKE_ACPX_STATE=os.path.join(self.folder, 'acpx.json'),
                        OPENWIZ_OPENCLAW_STATE=self.state,
                        PATH=os.path.join(ROOT, 'adapters', 'openclaw', 'fixtures', 'bin') + os.pathsep + self.bare())

    def bare(self):
        bare = os.path.join(self.folder, 'bare')
        os.mkdir(bare)
        for tool in ('python3', 'sleep'):
            os.symlink(shutil.which(tool), os.path.join(bare, tool))
        return bare

    def tearDown(self):
        for pid in owned():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def seen(self):
        with open(self.calls) as handle:
            return [json.loads(line) for line in handle]

    def plant(self, folder):
        os.makedirs(folder)
        with open(os.path.join(folder, '.acpxrc.json'), 'w') as handle:
            json.dump(MARKER, handle)

    def fake(self, cwd, config_dir):
        env = dict(self.env, HOME=self.home)
        subprocess.run([sys.executable, FAKE, '--cwd', config_dir, '--agent', 'env HOME=/tmp true'],
                       cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
        return self.seen()[-1]

    def test_acpx_reads_project_config_from_cwd_not_the_process_folder(self):
        process, chosen = (os.path.join(self.folder, name) for name in ('process', 'chosen'))
        self.plant(process)
        os.mkdir(chosen)
        self.assertEqual(self.fake(process, chosen)['auth'], [])
        os.remove(self.calls)
        self.plant(os.path.join(self.folder, 'loaded'))
        self.assertEqual(self.fake(process, os.path.join(self.folder, 'loaded'))['auth'], ['synthetic-race-marker'])

    def driver(self, cmd, request, **env):
        result = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request),
                                env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        return result.returncode, json.loads(result.stdout)

    def test_a_config_written_between_the_check_and_the_read_never_reaches_acpx(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        work = os.path.join(self.state, 'work', out['run'])
        before = len(self.seen())
        code, woke = self.driver('wake', out, FAKE_ACPX_RACE=work)
        self.assertEqual(code, 0, woke)
        self.assertTrue(os.path.exists(os.path.join(work, '.acpxrc.json')))
        self.assertEqual(self.seen()[before]['auth'], [], 'acpx loaded the project config')
        self.assertNotIn('synthetic-race-marker', json.dumps(self.seen()[before]))

    def swap_adapter(self, ran, replacement):
        if ran[-len(CLAUDE):] == CLAUDE:
            return ran[:-len(CLAUDE)] + replacement
        old = ' '.join(CLAUDE)
        new = ' '.join("'" + part.replace("'", "'\\''") + "'" for part in replacement)
        return [part.replace(old, new) for part in ran]

    def test_acp_session_workspace_and_tool_requests_use_the_work_folder(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        first = self.seen()[0]
        launch = first['args'][first['args'].index('--cwd') + 1]
        work = os.path.join(self.state, 'work', out['run'])
        self.assertNotEqual(os.path.realpath(launch), os.path.realpath(work))
        agent = os.path.join(self.folder, 'stand_in.py')
        with open(agent, 'w') as handle:
            handle.write(STAND_IN)
        log = os.path.join(self.folder, 'agent.json')
        cmd = self.swap_adapter(first['ran'], [sys.executable, '-I', agent, log, work, launch])
        env = dict(os.environ, HOME=os.path.join(self.state, 'home'))
        messages = []
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=launch, env=env, text=True) as proc:
            for req in (
                {'jsonrpc': '2.0', 'id': 1, 'method': 'session/new', 'params': {'cwd': launch, 'mcpServers': []}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'session/load',
                 'params': {'sessionId': 's1', 'cwd': launch, 'mcpServers': []}},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'session/resume',
                 'params': {'sessionId': 's1', 'cwd': launch, 'mcpServers': []}},
            ):
                proc.stdin.write(json.dumps(req) + '\n')
                proc.stdin.flush()
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        self.fail(proc.stderr.read())
                    msg = json.loads(line)
                    messages.append(msg)
                    if msg.get('id') == req['id']:
                        break
            proc.stdin.close()
            stderr = proc.stderr.read()
            self.assertEqual(proc.wait(timeout=30), 0, stderr)
        with open(log) as handle:
            recorded = json.load(handle)
        self.assertEqual(recorded['cwd'], os.path.realpath(work))
        self.assertEqual(recorded['home'], self.home)
        self.assertEqual(recorded['requests'], [
            {'method': 'session/new', 'cwd': work},
            {'method': 'session/load', 'cwd': work},
            {'method': 'session/resume', 'cwd': work},
        ])
        by_id = {m['id']: m for m in messages if 'method' in m}
        for mid in (10, 11):
            rewritten = by_id[mid]['params']['path']
            self.assertTrue(rewritten.startswith(os.path.abspath(launch) + os.sep), rewritten)
            self.assertEqual(os.path.realpath(rewritten), os.path.realpath(os.path.join(work, 'note.txt')))
        self.assertFalse(by_id[12]['params']['path'].startswith(os.path.abspath(launch) + os.sep))
        self.assertEqual(by_id[13]['params']['cwd'], work)
        self.assertNotIn(14, by_id)
        self.assertEqual([r['id'] for r in recorded['replies']], [14])
        self.assertIn('error', recorded['replies'][0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
