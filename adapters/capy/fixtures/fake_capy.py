#!/usr/bin/env python3
# External: the routes and shapes follow Capy's endpoint schemas (https://docs.capy.ai/api-reference/overview), and a message
# unarchives and wakes an archived thread (https://docs.capy.ai/threads#archive-is-dormant).
import http.server
import json
import os
import re
import threading
import time

KEY_PATH = '/.openwiz/hostkey-test-key'
PROJECTS = [
    {'id': 'project_synthetic1', 'name': 'Site', 'description': None, 'code': 'SITE', 'visibility': 'org',
     'repos': [{'repoFullName': 'Example/Site', 'baseBranch': 'main', 'mode': 'primary'}],
     'createdAt': '2030-01-01T00:00:00Z', 'updatedAt': '2030-01-01T00:00:00Z'},
    {'id': 'project_synthetic2', 'name': 'Other', 'description': None, 'code': 'OTH', 'visibility': 'org',
     'repos': [{'repoFullName': 'example/other', 'baseBranch': 'main', 'mode': 'lazy'}],
     'createdAt': '2030-01-01T00:00:00Z', 'updatedAt': '2030-01-01T00:00:00Z'},
]
MODELS = [
    {'id': 'anthropic/claude-synthetic-1', 'name': 'Claude Synthetic 1', 'billing': 'Claude Code',
     'route': 'member_seat', 'reasoningModes': ['low', 'medium', 'high'], 'fast': False, 'pro': False,
     'ultrafast': False},
    {'id': 'openai/gpt-synthetic-2', 'name': 'GPT Synthetic 2', 'billing': 'Codex', 'route': 'member_seat',
     'reasoningModes': ['none', 'low', 'medium', 'high', 'xhigh'], 'fast': False, 'pro': False, 'ultrafast': False},
]
REASONING = ['none', 'instant', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
CREATE = {'requestId', 'projectId', 'title', 'message', 'environmentVariables', 'model', 'machineSize', 'device',
          'authorId', 'visibility', 'personal', 'pullRequestAuthor', 'captainId'}
SEND = {'text', 'files', 'model', 'delivery', 'clientKey', 'editOf', 'switchTo', 'pullRequestAuthor'}
NOTE = '\n'.join(['<!-- openwiz:status v1 -->', 'agent: builder', 'state: working', 'harness: Capy', 'model: %s',
                  'skills: %s@0.1.2', 'step: %s', 'time: %s']) + '\n'


def tag(name, **fields):
    return dict({'_tag': 'capy/' + name}, **fields)


def tracker(folder):
    path = os.path.join(folder, 'tracker.json')
    old = '<!-- openwiz:status v1 -->\nagent: builder\nstate: stopped\nharness: Fake\nmodel: m\n' \
          'skills: build-ticket@0.1.2\nstep: an earlier run\ntime: 2030-01-02T03:04:05Z\n'
    with open(path, 'w') as f:
        json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': [
            {'id': 1, 'author': 'example-bot[bot]', 'updated_at': '2030-01-02T03:04:05Z', 'body': old}]}, f)
    return path


class FakeCapy:

    def __init__(self, key, tracker, projects=PROJECTS, models=MODELS, lose_creates=0, served_key=None, answers=(),
                 replay=None, throttle=(), widen=None):
        self.key, self.tracker, self.projects, self.models = key, tracker, projects, models
        self.answers = list(answers)
        self.served_key = key if served_key is None else served_key
        self.lose_creates, self.replay, self.throttle, self.widen = lose_creates, replay, list(throttle), widen
        self.hold, self.held, self.release = None, threading.Event(), threading.Event()
        self.requests, self.threads, self.by_request = [], {}, {}
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
                        code, body = 401, tag('Unauthorized')
                    else:
                        try:
                            code, body = host.route(self.command, self.path, json.loads(raw) if raw else None)
                        except ValueError:
                            code, body = 400, tag('InvalidRequest', message='synthetic: unreadable JSON')
                    held = host.hold == (self.command, self.path)
                    host.hold = None if held else host.hold
                if held:
                    host.held.set()
                    host.release.wait(60)
                if code is not None:
                    self.reply(code, host.widened(body))

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PATCH = do_PUT = handle_one

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def widened(self, value):
        if isinstance(value, list):
            return [self.widened(v) for v in value]
        if isinstance(value, dict) and self.widen:
            return dict({k: self.widened(v) for k, v in value.items()}, **self.widen)
        return value

    def calls(self):
        return [(m, p) for m, p, _, _ in self.requests]

    def bodies(self, method, path):
        return [json.loads(b) for m, p, b, _ in self.requests if (m, p) == (method, path)]

    def _note(self, t, step):
        skill = re.search(r'with the ([a-z0-9-]+) skill', t['create']['message']).group(1)
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        body = NOTE % (t['create'].get('model', {}).get('modelId', 'default'), skill, step, now)
        with open(self.tracker) as f:
            tracker = json.load(f)
        if t['note'] is None:
            t['note'] = 1 + max([c['id'] for c in tracker['comments']], default=0)
            tracker['comments'].append({'id': t['note'], 'author': 'example-bot[bot]', 'updated_at': now,
                                        'body': body})
        else:
            for c in tracker['comments']:
                if c['id'] == t['note']:
                    c.update(body=body, updated_at=now)
        with open(self.tracker + '.new', 'w') as f:
            json.dump(tracker, f)
        os.replace(self.tracker + '.new', self.tracker)

    def _thread(self, t):
        return {'id': t['id'], 'projectId': t['create']['projectId'], 'authorId': 'user_synthetic',
                'previousAuthorId': None, 'title': t['create'].get('title'), 'titleCustom': True,
                'status': 'archived' if t['archived'] else t['status'], 'archived': t['archived'],
                'lastModelId': t['create'].get('model', {}).get('modelId'), 'queuedAt': None, 'linearIssue': None,
                'pullRequestAuthor': None,
                'usage': {'llmCredits': 0, 'imageCredits': 0, 'vmCredits': 0, 'totalCredits': 0},
                'createdAt': '2030-01-01T00:00:00Z', 'updatedAt': '2030-01-01T00:00:00Z', 'lastActivityAt': None,
                'hasUnreads': False, 'mentionCount': 0, 'owed': False, 'member': True}

    def _receipt(self, t):
        t['events'] += 1
        return {'id': '01SYNTHETIC%015d' % (len(self.threads) * 1000 + t['events']), 'deduped': False}

    def route(self, method, target, body):
        path = target.partition('?')[0]
        for m, pattern, code, reply in self.answers:
            if m == method and re.fullmatch(pattern, path):
                return code, reply
        if method == 'GET' and path == '/api/v1/projects':
            return 200, {'items': self.projects}
        if method == 'GET' and path == '/api/v1/models':
            return 200, {'items': self.models, 'default': {'modelId': self.models[0]['id'], 'source': 'org',
                                                           'skipped': []}}
        if method == 'POST' and path == '/api/v1/threads':
            if not isinstance(body, dict) or set(body) - CREATE or not {'requestId', 'projectId', 'message'} <= set(
                    body):
                return 400, tag('InvalidRequest', message='synthetic: not a CreateThreadRequest')
            if self.throttle:
                return 429, tag('RateLimited', retryAfterSeconds=self.throttle.pop(0))
            if self.replay and body['requestId'] in self.by_request:
                return self.replay
            if body['projectId'] not in [p['id'] for p in self.projects]:
                return 404, tag('ProjectNotFound', projectId=body['projectId'])
            model = body.get('model')
            if model is not None and model.get('reasoningMode', 'none') not in REASONING:
                return 400, tag('InvalidRequest', message='synthetic: not a ModelSelection')
            if model is not None:
                found = [m for m in self.models if m['id'] == model.get('modelId')]
                if not found or model.get('reasoningMode', found[0]['reasoningModes'][0]) not in found[0][
                        'reasoningModes']:
                    return 400, {'_tag': 'ModelSelection.Rejected', 'message': 'synthetic: cannot run',
                                 'candidates': [], 'modelId': model.get('modelId')}
            t = self.by_request.get(body['requestId'])
            if t is None:
                t = {'id': 'jam_01SYNTHETIC%013d' % len(self.threads), 'create': body, 'status': 'working',
                     'archived': False, 'messages': [], 'interrupts': 0, 'note': None, 'events': 0}
                self.threads[t['id']] = self.by_request[body['requestId']] = t
                self._note(t, 'started the throwaway ticket')
            if self.lose_creates:
                self.lose_creates -= 1
                return 503, {'_tag': 'synthetic/Unavailable'}
            return 200, self._thread(t)
        m = re.fullmatch(r'/api/v1/threads/([^/]+)(/messages?|/interrupt|/archive)?', path)
        t = self.threads.get(m.group(1)) if m else None
        if m and t is None:
            return 404, tag('ThreadNotFound', threadId=m.group(1))
        if method == 'GET' and m and not m.group(2):
            return 200, self._thread(t)
        if method == 'GET' and m and m.group(2) == '/messages':
            items = [{'id': '01SYNTHETIC%015d' % index, 'source': 'user', 'text': message['text'],
                      'clientKey': message.get('clientKey'), 'createdAt': '2030-01-01T00:00:00Z'}
                     for index, message in enumerate(t['messages'])]
            return 200, {'items': items, 'cursor': None, 'beforeCursor': None}
        if method == 'POST' and m and m.group(2) == '/message':
            if not isinstance(body, dict) or set(body) - SEND or not isinstance(body.get('text'), str):
                return 400, tag('InvalidRequest', message='synthetic: not a SendMessageRequest')
            t['messages'].append(body)
            t['archived'], t['status'] = False, 'working'
            self._note(t, 'woke and read the ticket again')
            return 200, self._receipt(t)
        if method == 'POST' and m and m.group(2) == '/interrupt':
            t['interrupts'] += 1
            t['status'] = 'idle'
            return 200, self._receipt(t)
        if method == 'POST' and m and m.group(2) == '/archive':
            t['archived'] = True
            return 200, dict(self._thread(t), automation=None)
        return 404, {'_tag': 'synthetic/RouteNotFound'}
