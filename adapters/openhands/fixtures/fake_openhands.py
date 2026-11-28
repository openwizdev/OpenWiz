#!/usr/bin/env python3
import http.server
import json
import os
import re
import threading
import time
import urllib.parse

PROFILES = [
    {'id': '00000000-0000-4000-8000-00000000000a', 'name': 'openhands-default', 'agent_kind': 'openhands',
     'scope': 'personal'},
    {'id': '00000000-0000-4000-8000-00000000000b', 'name': 'claude-synthetic', 'agent_kind': 'acp',
     'scope': 'personal', 'acp_server': 'claude-code', 'acp_model': 'Synthetic 1'},
    {'id': '00000000-0000-4000-8000-00000000000c', 'name': 'codex-synthetic', 'agent_kind': 'acp', 'scope': 'org',
     'acp_server': 'codex', 'acp_model': 'Synthetic 2'},
]
KEY_PATH = '/.openwiz/hostkey-test-key'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
NOTE = '\n'.join(['<!-- openwiz:status v1 -->', 'agent: builder', 'state: working', 'harness: %s', 'model: %s',
                  'skills: %s@0.1.2', 'step: %s', 'time: %s']) + '\n'


class FakeOpenHands:

    def __init__(self, key, tracker, starting_lookups=0, pause_after_turn=True, profiles=PROFILES, lose_start=False,
                 served_key=None):
        self.key, self.tracker, self.profiles, self.lose_start = key, tracker, profiles, lose_start
        self.served_key = key if served_key is None else served_key
        self.starting_lookups, self.pause_after_turn = starting_lookups, pause_after_turn
        self.requests, self.conversations, self.tasks, self.answers = [], {}, {}, []
        self.key_requests = 0
        self.pause_before_send = False
        self.lock = threading.Lock()
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_one(self):
                size = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(size)
                if self.command == 'GET' and self.path == KEY_PATH:
                    with host.lock:
                        host.key_requests += 1
                    return self.reply(200, {'key': host.served_key})
                with host.lock:
                    host.requests.append((self.command, self.path, raw, self.headers.get('Authorization')))
                    if self.headers.get('Authorization') != 'Bearer ' + host.key:
                        code, body = 401, {'detail': 'Not authenticated'}
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

    def _note(self, conv, text):
        conv['first'] = conv.get('first') or text
        woken = conv.get('note') is not None
        skill = re.search(r'with the ([a-z0-9-]+) skill', conv['first']).group(1)
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        body = NOTE % (conv['harness'], conv['model'], skill,
                       'woke and read the ticket again' if woken else 'started the throwaway ticket', now)
        with open(self.tracker) as f:
            tracker = json.load(f)
        if conv.get('note') is None:
            conv['note'] = 1 + max([c['id'] for c in tracker['comments']], default=0)
            tracker['comments'].append({'id': conv['note'], 'author': 'example-bot[bot]', 'updated_at': now,
                                        'body': body})
        else:
            for c in tracker['comments']:
                if c['id'] == conv['note']:
                    c.update(body=body, updated_at=now)
        with open(self.tracker + '.new', 'w') as f:
            json.dump(tracker, f)
        os.replace(self.tracker + '.new', self.tracker)

    def _task(self, cid):
        task = self.tasks[cid]
        if task['status'] != 'READY' and task['lookups'] >= self.starting_lookups:
            task['status'] = 'READY'
            task['app_conversation_id'], task['sandbox_id'] = cid, self.conversations[cid]['sandbox_id']
            if self.conversations[cid]['first']:
                self._note(self.conversations[cid], self.conversations[cid]['first'])
                if self.pause_after_turn:
                    self.conversations[cid]['sandbox_status'] = 'PAUSED'
        task['lookups'] += 1
        return {k: task[k] for k in ('id', 'status', 'app_conversation_id', 'sandbox_id', 'created_by_user_id',
                                     'request')}

    def answer(self, method, path, code, body, times=None):
        self.answers.append({'method': method, 'path': path, 'code': code, 'body': body, 'times': times})

    def route(self, method, target, body):
        path, _, query = target.partition('?')
        for a in self.answers:
            if a['method'] == method and re.fullmatch(a['path'], path) and a['times'] != 0:
                if a['times'] is not None:
                    a['times'] -= 1
                return a['code'], a['body']
        q = urllib.parse.parse_qs(query)
        if method == 'GET' and path == '/api/agent-profiles':
            return 200, {'profiles': [{k: p[k] for k in ('id', 'name', 'agent_kind', 'scope')}
                                      for p in self.profiles], 'active_agent_profile_id': self.profiles[0]['id']}
        m = re.fullmatch(r'/api/agent-profiles/([A-Za-z0-9][A-Za-z0-9._-]{0,63})', path)
        if method == 'GET' and m:
            for p in self.profiles:
                if p['name'] == m.group(1) and q.get('scope', [p['scope']]) == [p['scope']]:
                    profile = {k: v for k, v in p.items() if k != 'scope'}
                    if p['agent_kind'] == 'acp':
                        profile['secret_refs'] = ['SYNTHETIC_HARNESS_LOGIN']
                    return 200, {'name': p['name'], 'profile': profile, 'scope': p['scope']}
            return 404, {'detail': 'Not Found'}
        if method == 'POST' and path == '/api/v1/app-conversations':
            cid = body.get('conversation_id')
            profile = [p for p in self.profiles if p['id'] == body.get('agent_profile_id')]
            if not cid or not re.fullmatch(UUID, cid) or cid in self.conversations or not profile:
                return 422, {'detail': [{'msg': 'synthetic validation error'}]}
            text = body['initial_message']['content'][0]['text'] if body.get('initial_message') else None
            n = len(self.conversations)
            self.conversations[cid] = {'sandbox_id': 'sandbox-synthetic-%d' % n, 'sandbox_status': 'RUNNING',
                                       'harness': profile[0]['acp_server'], 'model': profile[0]['acp_model'],
                                       'first': text, 'messages': [], 'deleted': False, 'request': body}
            self.tasks[cid] = {'id': '00000000-0000-4000-9000-%012d' % n, 'status': 'WORKING', 'lookups': 0,
                               'app_conversation_id': None, 'sandbox_id': None, 'created_by_user_id': 'user-synthetic',
                               'request': body}
            task = self._task(cid)
            return (503, {'detail': 'synthetic gateway error'}) if self.lose_start else (200, task)
        if method == 'GET' and path == '/api/v1/app-conversations/start-tasks/search':
            cid = q.get('conversation_id__eq', [None])[0]
            return 200, {'items': [self._task(cid)] if cid in self.tasks else [], 'next_page_id': None}
        if method == 'GET' and path == '/api/v1/app-conversations':
            found = []
            for cid in q.get('ids', []):
                c = self.conversations.get(cid)
                if c is None or c['deleted'] or self.tasks[cid]['status'] != 'READY':
                    found.append(None)
                else:
                    found.append({'id': cid, 'sandbox_id': c['sandbox_id'], 'sandbox_status': c['sandbox_status'],
                                  'created_by_user_id': 'user-synthetic', 'agent_kind': 'acp',
                                  'session_api_key': 'synthetic-session-value', 'conversation_url': None})
            return 200, found
        m = re.fullmatch(r'/api/v1/app-conversations/([^/]+)/send-message', path)
        if method == 'POST' and m:
            c = self.conversations.get(m.group(1))
            if c is None or self.tasks[m.group(1)]['status'] != 'READY':
                return 404, {'detail': 'Conversation or sandbox not found'}
            if c['deleted']:
                return 410, {'detail': 'Conversation is archived'}
            if self.pause_before_send:
                c['sandbox_status'] = 'PAUSED'
                self.pause_before_send = False
            if c['sandbox_status'] != 'RUNNING':
                return 409, {'detail': 'Sandbox is not running. Resume it first'}
            c['messages'].append(body['content'][0]['text'])
            self._note(c, body['content'][0]['text'])
            if self.pause_after_turn:
                c['sandbox_status'] = 'PAUSED'
            return 200, {'success': True, 'sandbox_status': 'RUNNING', 'message': None}
        m = re.fullmatch(r'/api/v1/sandboxes/([^/]+)/(pause|resume)', path)
        if method == 'POST' and m:
            for c in self.conversations.values():
                if c['sandbox_id'] == m.group(1) and not c['deleted']:
                    c['sandbox_status'] = 'PAUSED' if m.group(2) == 'pause' else 'RUNNING'
                    return 200, {'success': True}
            return 404, {'detail': 'Item not found'}
        m = re.fullmatch(r'/api/v1/app-conversations/([^/]+)', path)
        if method == 'DELETE' and m:
            c = self.conversations.get(m.group(1))
            if c is None or c['deleted'] or self.tasks[m.group(1)]['status'] != 'READY':
                return 404, {'detail': 'Item not found'}
            c['deleted'], c['sandbox_status'] = True, 'MISSING'
            return 200, {'success': True}
        return 404, {'detail': 'Not Found'}
