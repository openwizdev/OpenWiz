#!/usr/bin/env python3
# A synthetic Tembo, built from the host's public API reference (docs.tembo.io/api): only the operations the
# driver uses, with their documented status codes. It also plays the run's agent: a created session or a queued
# message posts or edits one builder status note in the kit's tracker file.
import http.server
import json
import os
import re
import threading
import time
import urllib.parse

KEY_PATH = '/.openwiz/hostkey-test-key'
REPOSITORIES = [
    {'id': '00000000-0000-4000-8000-0000000000a1', 'owner': 'example', 'name': 'site-old', 'url': 'synthetic'},
    {'id': '00000000-0000-4000-8000-0000000000a2', 'owner': 'Example', 'name': 'Site', 'url': 'synthetic'},
    {'id': '00000000-0000-4000-8000-0000000000a3', 'owner': 'other', 'name': 'site', 'url': 'synthetic'},
]
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
NOTE = '\n'.join(['<!-- openwiz:status v1 -->', 'agent: builder', 'state: working', 'harness: %s', 'model: %s',
                  'skills: %s@0.1.2', 'step: %s', 'time: %s']) + '\n'


class FakeTembo:

    def __init__(self, key, tracker, repositories=REPOSITORIES, lose_start=False, served_key=None):
        self.key, self.tracker, self.repositories, self.lose_start = key, tracker, repositories, lose_start
        self.served_key = key if served_key is None else served_key
        self.requests, self.sessions = [], {}
        self.lock = threading.Lock()
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_one(self):
                size = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(size)
                if self.command == 'GET' and self.path == KEY_PATH:
                    return self.reply(200, {'key': host.served_key})
                with host.lock:
                    host.requests.append((self.command, self.path, raw, self.headers.get('Authorization')))
                    if self.headers.get('Authorization') != 'Bearer ' + host.key:
                        code, body = 401, {'error': 'Unauthorized'}
                    else:
                        try:
                            body_in = json.loads(raw) if raw else None
                        except ValueError:
                            body_in = None
                        code, body = host.route(self.command, self.path, body_in)
                self.reply(code, body)

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

    def calls(self):
        return [(m, p) for m, p, _, _ in self.requests]

    def _note(self, s, text):
        woken = s.get('note') is not None
        skill = re.search(r'with the ([a-z0-9-]+) skill', s['request']['description']).group(1)
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        harness, _, model = s['request'].get('agent', 'default:default').partition(':')
        body = NOTE % (harness, model, skill, 'woke and read the ticket again' if woken else 'started the ticket',
                       now)
        with open(self.tracker) as f:
            tracker = json.load(f)
        if not woken:
            s['note'] = 1 + max([c['id'] for c in tracker['comments']], default=0)
            tracker['comments'].append({'id': s['note'], 'author': 'example-bot[bot]', 'updated_at': now,
                                        'body': body})
        else:
            for c in tracker['comments']:
                if c['id'] == s['note']:
                    c.update(body=body, updated_at=now)
        with open(self.tracker + '.new', 'w') as f:
            json.dump(tracker, f)
        os.replace(self.tracker + '.new', self.tracker)

    def _session(self, sid):
        s = self.sessions[sid]
        return {'id': sid, 'agent': s['request'].get('agent'), 'level': s['level'], 'title': 'synthetic',
                'kind': 'session', 'sessionType': 'Chat',
                'state': {'current': s['state'], 'isQueued': False, 'isCancelled': s['state'] == 'cancelled',
                          'isCompleted': False, 'isFailed': False, 'inProgress': s['state'] == 'inProgress'}}

    def route(self, method, target, body):
        path, _, query = target.partition('?')
        q = urllib.parse.parse_qs(query)
        if method == 'GET' and path == '/v1/repositories':
            term = q.get('search', [''])[0].lower()
            items = [r for r in self.repositories if term in (r['owner'] + '/' + r['name']).lower()]
            return 200, {'items': items, 'nextCursor': None}
        if method == 'POST' and path == '/v1/sessions':
            allowed = {'agent', 'agentOptions', 'codeRepositoryIds', 'description', 'id', 'queueRightAway'}
            sid = (body or {}).get('id')
            if not isinstance(body, dict) or not set(body) <= allowed or not body.get('description') \
                    or not isinstance(sid, str) or not re.fullmatch(UUID, sid) or sid in self.sessions:
                return 400, {'error': 'synthetic validation error'}
            known = {r['id'] for r in self.repositories}
            if not set(body.get('codeRepositoryIds', [])) <= known:
                return 404, {'error': 'Repository not found'}
            self.sessions[sid] = {'request': body, 'level': 1, 'state': 'inProgress', 'messages': [],
                                  'stopped': False}
            if body.get('queueRightAway'):
                self._note(self.sessions[sid], body['description'])
            if self.lose_start:
                return 502, {'error': 'synthetic gateway error'}
            return 201, dict(self._session(sid), createdAt='2030-01-02T03:04:05Z')
        m = re.fullmatch(r'/v1/sessions/([^/]+)', path)
        if m and method in ('GET', 'DELETE'):
            s = self.sessions.get(m.group(1))
            if s is None or (method == 'DELETE' and s['level'] == 0):
                return 404, {'error': 'Session resource not found'}
            if method == 'GET':
                return 200, dict(self._session(m.group(1)), sessionToken='synthetic-session-value')
            s['level'], s['state'] = 0, 'cancelled'
            return 200, {'deleted': True, 'id': m.group(1)}
        m = re.fullmatch(r'/v1/sessions/([^/]+)/stop', path)
        if method == 'POST' and m:
            s = self.sessions.get(m.group(1))
            if s is None or s['level'] == 0:
                return 404, {'error': 'Session resource not found'}
            s['stopped'], s['state'] = q.get('cancelQueued') == ['true'], 'cancelled'
            return 200, {'cancelledSessions': 1, 'cancelledJobs': 0, 'stoppedRuntimeSessions': 1,
                         'interruptedRuntimeTurns': 1, 'cancelledRuntimeTurns': 0}
        if method == 'POST' and path == '/v1/messages':
            if not isinstance(body, dict) or not {'content', 'sessionId'} <= set(body) \
                    or not set(body) <= {'content', 'sessionId', 'deliveryMode'}:
                return 400, {'error': 'synthetic validation error'}
            s = self.sessions.get(body['sessionId'])
            if s is None or s['level'] == 0:
                return 404, {'error': 'Session resource not found'}
            s['messages'].append(body['content'])
            s['state'] = 'inProgress'
            self._note(s, body['content'])
            return 201, {'id': '00000000-0000-4000-9000-%012d' % len(s['messages']), 'sessionId': body['sessionId']}
        return 404, {'error': 'Not Found'}
