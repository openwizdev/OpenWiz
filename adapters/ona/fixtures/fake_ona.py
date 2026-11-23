#!/usr/bin/env python3
import http.server
import json
import os
import re
import threading
import time
import uuid

KEY_PATH = '/.openwiz/hostkey-test-key'
CODEX = '00000000-0000-0000-0000-000000007800'
AGENT = '/api/gitpod.v1.AgentService/'
ENVIRONMENT = '/api/gitpod.v1.EnvironmentService/'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
MODELS = ('GPT_5_5', 'GPT_5_4', 'GPT_5_4_MINI', 'GPT_5_3_CODEX', 'GPT_5_3_CODEX_SPARK', 'GPT_5_2', 'GPT_5_6_SOL',
          'GPT_5_6_TERRA', 'GPT_5_6_LUNA', 'GPT_6_ASTRA', 'GPT_6_SOL', 'GPT_6_LUNA', 'GPT_6_1_SOL')
EFFORTS = ('LOW', 'MEDIUM', 'HIGH', 'EXTRA_HIGH', 'MAX', 'ULTRA')
NOTE = '\n'.join(['<!-- openwiz:status v1 -->', 'agent: builder', 'state: working', 'harness: codex', 'model: %s',
                  'skills: %s@0.1.2', 'step: %s', 'time: %s']) + '\n'


def error(status, code, message):
    return status, {'code': code, 'message': message}


class FakeOna:

    def __init__(self, key, tracker, served_key=None, idle_phase='PHASE_WAITING_FOR_INPUT', lose_send=False,
                 refuse_efforts=()):
        self.key, self.tracker, self.idle_phase, self.lose_send = key, tracker, idle_phase, lose_send
        self.served_key = key if served_key is None else served_key
        self.refuse_efforts = refuse_efforts
        self.requests, self.runs, self.environments = [], {}, {}
        self.lock = threading.Lock()
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_one(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                if self.command == 'GET' and self.path == KEY_PATH:
                    return self.reply(200, {'key': host.served_key})
                with host.lock:
                    host.requests.append((self.command, self.path, raw, self.headers.get('Authorization')))
                    if self.headers.get('Authorization') != 'Bearer ' + host.key:
                        code, body = error(401, 'unauthenticated', 'synthetic: the token is not valid')
                    elif self.command != 'POST' or self.headers.get('Content-Type') != 'application/json':
                        code, body = error(415, 'invalid_argument', 'synthetic: send a JSON POST')
                    else:
                        try:
                            body_in = json.loads(raw)
                        except ValueError:
                            body_in = None
                        if not isinstance(body_in, dict):
                            code, body = error(400, 'invalid_argument', 'synthetic: the body is not an object')
                        else:
                            code, body = host.route(self.path, body_in)
                self.reply(code, body)

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PUT = handle_one

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def calls(self):
        return [p for _, p, _, _ in self.requests]

    def bodies(self, method):
        return [json.loads(b) for _, p, b, _ in self.requests if p == AGENT + method]

    def _note(self, run, text):
        run['first'] = run.get('first') or text
        woken = run.get('note') is not None
        skill = re.search(r'with the ([a-z0-9-]+) skill', run['first']).group(1)
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        body = NOTE % (run['model'], skill, 'woke and read the ticket again' if woken else
                       'started the throwaway ticket', now)
        with open(self.tracker) as f:
            tracker = json.load(f)
        if not woken:
            run['note'] = 1 + max([c['id'] for c in tracker['comments']], default=0)
            tracker['comments'].append({'id': run['note'], 'author': 'example-bot[bot]', 'updated_at': now,
                                        'body': body})
        else:
            for c in tracker['comments']:
                if c['id'] == run['note']:
                    c.update(body=body, updated_at=now)
        with open(self.tracker + '.new', 'w') as f:
            json.dump(tracker, f)
        os.replace(self.tracker + '.new', self.tracker)

    def _run(self, body, fields):
        if set(body) - fields:
            return None, error(400, 'invalid_argument', 'synthetic: unknown field')
        rid = body.get('agentExecutionId')
        if not (isinstance(rid, str) and re.fullmatch(UUID, rid)):
            return None, error(400, 'invalid_argument', 'synthetic: agent_execution_id must be a UUID')
        if rid not in self.runs:
            return None, error(404, 'not_found', 'synthetic: agent execution not found')
        return self.runs[rid], None

    def route(self, path, body):
        if path == AGENT + 'StartAgent':
            if set(body) - {'agentId', 'codeContext', 'name', 'codexSettings'}:
                return error(400, 'invalid_argument', 'synthetic: unknown field')
            settings = body.get('codexSettings') or {}
            context = (body.get('codeContext') or {}).get('contextUrl') or {}
            if body.get('agentId') != CODEX or not re.fullmatch(r'https://github\.com/[^/]+/[^/]+',
                                                                 context.get('url') or ''):
                return error(400, 'invalid_argument', 'synthetic: the Codex agent and a context URL are required')
            if set(settings) - {'model', 'reasoningEffort'} or \
                    settings.get('model') not in ['CODEX_OPEN_AI_MODEL_' + m for m in MODELS] or \
                    settings.get('reasoningEffort', 'CODEX_REASONING_EFFORT_MEDIUM') not in \
                    ['CODEX_REASONING_EFFORT_' + e for e in EFFORTS]:
                return error(400, 'invalid_argument', 'synthetic: codex_settings are not defined values')
            if settings.get('reasoningEffort') in self.refuse_efforts:
                return error(403, 'permission_denied', 'synthetic: your organization limits reasoning effort')
            rid, env = str(uuid.uuid4()), str(uuid.uuid4())
            self.environments[env] = 'ENVIRONMENT_PHASE_RUNNING'
            self.runs[rid] = {'phase': 'PHASE_PENDING', 'environment': env, 'messages': [], 'start': body,
                              'model': settings['model'], 'effort': settings.get('reasoningEffort')}
            return 200, {'agentExecutionId': rid}
        if path == AGENT + 'GetAgentExecution':
            run, failed = self._run(body, {'agentExecutionId'})
            if failed:
                return failed
            return 200, {'agentExecution': {
                'id': body['agentExecutionId'],
                'metadata': {'name': run['start']['name'], 'annotations': {}},
                'spec': {'agentId': CODEX, 'codeContext': run['start']['codeContext'],
                         'codexSettings': run['start'].get('codexSettings', {})},
                'status': {'phase': run['phase'], 'conversationUrl': 'https://app.ona.com/synthetic',
                           'usedEnvironments': [{'environmentId': run['environment'], 'createdByAgent': True},
                                                {'environmentId': '00000000-0000-4000-8000-00000000e0e0'}]}}}
        if path == AGENT + 'SendToAgentExecution':
            run, failed = self._run(body, {'agentExecutionId', 'userInput'})
            if failed:
                return failed
            if run['phase'] == 'PHASE_STOPPED':
                return error(400, 'failed_precondition', 'synthetic: the agent execution is not active')
            inputs = (body.get('userInput') or {}).get('inputs') or []
            if set(body['userInput']) != {'id', 'inputs'} or len(inputs) != 1 or \
                    set(inputs[0]) != {'text'} or set(inputs[0]['text']) != {'content'}:
                return error(400, 'invalid_argument', 'synthetic: user_input is not one text input')
            text = inputs[0]['text']['content']
            run['messages'].append(text)
            self._note(run, text)
            run['phase'] = self.idle_phase
            if self.lose_send:
                return error(503, 'unavailable', 'synthetic: the gateway lost the answer')
            return 200, {}
        if path == AGENT + 'StopAgentExecution':
            run, failed = self._run(body, {'agentExecutionId'})
            if failed:
                return failed
            run['phase'] = 'PHASE_STOPPED'
            return 200, {}
        if path == ENVIRONMENT + 'StopEnvironment':
            if set(body) != {'environmentId'} or body['environmentId'] not in self.environments:
                return error(404, 'not_found', 'synthetic: environment not found')
            self.environments[body['environmentId']] = 'ENVIRONMENT_PHASE_STOPPED'
            return 200, {}
        return error(404, 'unimplemented', 'synthetic: no such method')
