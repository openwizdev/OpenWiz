#!/usr/bin/env python3
"""The installed first hour through a verified merge, on recording providers (#2204).

`Attempt(case)` runs one attempt, synthetic throughout:

1. #1109's cold-consumer install journey, unchanged
   (tools/install/tests/journey/test_journey.py): the actual install entry, the
   installed setup tool and the installed onboarding helper. Only its recorded
   conversation is swapped for first-hour.json: one fresh small idea on the
   owner's own selected repository (the one setup prepared), not the demo,
   with no prepared plan.
2. The join this ticket adds: the fleet's builders, independent review, CI and
   the merge, decided at every step by the installed launch-fleet frontier
   (`runtime/skills/launch-fleet/scripts/fleet.sh spec`) reading a recording
   GitHub (launch-fleet's fake gh world) and a recording CloudRoom (a fake
   `room-cli thread list`). The recording providers make each effect the
   frontier asks for and count every call, effect and read-back.
3. The fault cases of #2222 rerun at this journey's own seams, with the same
   comparisons (drafts, setup state, identities, branch and commit content,
   pending records, effect and call counts), each a first-hour `recovery`
   document, and all of them joined into the attempt's `result` document.

The documents' codes come from #2200's checks (first-hour-contract/check.py,
through #2222's providers/codes.py). A recording is never a pass.

  journey.py setup-interrupted --runtime DIR --state DIR
      one child process: the installed runtime's access setup (runtime/access/
      access.py and its runtime/setup/store.py), with #2222's recording access
      provider; prints the recovery document and what it observed.

Stdlib only. Nothing reaches a network, an account or a real installation.
"""
import base64
import calendar
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CONVERSATION = json.loads((HERE / 'first-hour.json').read_text(encoding='utf-8'))
REPO = CONVERSATION['repo']
METHOD = 'test_from_the_line_to_a_first_fleet_on_a_cold_consumer'
FAMILY = {'codex': 'gpt', 'claude-code': 'claude'}
SEAT_HARNESS = {'codex': 'codex', 'claude-code': 'claude_code'}

ASSUMPTIONS = [
    'Synthetic recording-provider first hour on the installed journey (#2204): every id, digest, time, repository, '
    'thread, pull request and account is invented; GitHub and CloudRoom are recording providers.',
    "The release, install, setup and onboarding are #1109's fixture journey: no installed candidate was "
    'published, no person opened the instruction and no real time was measured, so the clock is unknown.',
    "Builder and reviewer runs are the recording CloudRoom's threads, read back: no real harness login ran.",
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


codes_module = load('first_hour_journey_codes', HERE / 'providers/codes.py')


def codes(document):
    """#2200's codes for one document, as #2222's providers report them."""
    return codes_module.codes(document)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def intent(kind, key):
    """One owner intent's operation id: 32 hex digits, the same however often it is tried."""
    return sha(f'openwiz.first-hour-journey.v1\n{kind}\n{key}')[:32]


def fingerprint(kind, request):
    """setup.v1's form: SHA-256 of the kind and the canonical request."""
    return sha(canonical({'kind': kind, 'request': request}))


def at(minute):
    """A recorded time, 2026-11-01T11:MM:00Z, as (ISO, milliseconds). The onboarding's clock is 12:00."""
    iso = '2026-11-01T11:%02d:00Z' % minute
    return iso, calendar.timegm(time.strptime(iso, '%Y-%m-%dT%H:%M:%SZ')) * 1000


def work(kind, ident, content, basis):
    return {'kind': kind, 'id': ident, 'content': content, 'basis': basis}


def recovery(interruption, before, after, operations, explanation, assumptions=ASSUMPTIONS):
    return {'schema': 'openwiz.first-hour.v1', 'kind': 'recovery', 'verdict': 'unverified',
            'proof_class': 'recording', 'synthetic_assumptions': list(assumptions), 'private_record': None,
            'candidate': {'unknown': 'a recording on the fixture journey: no published candidate'},
            'case': {'interruption': interruption, 'before': before, 'after': after,
                     'operations': operations, 'explanation': explanation}}


class Lost(Exception):
    """A reply that never came back: the effect may or may not have happened."""


class CloudRoom:
    """The recording CloudRoom: threads it started, read back by `room-cli thread list`."""

    def __init__(self, folder):
        self.file = folder / 'threads.json'
        self.bin = folder / 'cloudroom-bin'
        self.bin.mkdir(mode=0o700)
        self.threads = []
        self.calls = {}
        self.faults = []
        self.save()
        program = self.bin / 'room-cli'
        program.write_text('#!/bin/sh\n# Recording CloudRoom: answers only the thread list fleet.sh reads.\n'
                           '[ "$1 $2" = "thread list" ] || exit 9\n'
                           'exec /usr/bin/python3 -I -c "import sys; sys.stdout.write(open(sys.argv[1]).read())" '
                           '"$FIRST_HOUR_THREADS"\n')
        program.chmod(0o700)

    def save(self):
        self.file.write_text(json.dumps(self.threads))

    def start(self, op, title, branch, harness):
        """One agent start: the thread exists once this returns or the fault stops the reply."""
        self.calls[op] = self.calls.get(op, 0) + 1
        fault = self.faults.pop(0) if self.faults else None
        thread = 'thr_syn_first_hour_%02d' % (len(self.threads) + 1)
        self.threads.append({'id': thread, 'title': title, 'branch': branch, 'harness': harness})
        self.save()
        if fault == 'stop_after_effect':
            raise Lost(op)
        return thread

    def matching(self, prefix):
        """The provider's exact resource, read back: every thread whose title starts with `prefix`."""
        return [t for t in json.loads(self.file.read_text()) if t['title'].startswith(prefix)]


class GitHub:
    """The recording GitHub: the onboarding journey's fake gh world, where the fleet's writes land."""

    def __init__(self, journey):
        self.j = journey
        self.j.world.setdefault('pulls', [])
        self.j.world.setdefault('refs', [])
        self.calls, self.effects, self.reads = {}, {}, {}
        self.faults = []
        self.ids = 95000
        self.trees = {}
        self.merge_commits = {}
        self.j.save_world()

    def issue(self, number):
        return next(i for i in self.j.world['issues'] if i['number'] == number)

    def pull(self, number):
        return next(p for p in self.j.world['pulls'] if p['number'] == number)

    def comment(self, item, body, minute):
        self.ids += 1
        item['comments'].append({'id': self.ids, 'at': at(minute)[0], 'body': body})
        self.j.save_world()
        return self.ids

    def push(self, branch, files):
        """A builder's push: one commit on its own branch; the commit and tree ids are the content's digests."""
        tree = hashlib.sha1(canonical(files).encode()).hexdigest()
        head = hashlib.sha1(('commit\n' + tree + '\n' + branch).encode()).hexdigest()
        self.trees[head] = tree
        self.j.world['refs'].append(branch)
        self.j.save_world()
        return head, tree

    def open_pull(self, number, ticket, head, subject, minute):
        self.j.world['pulls'].append({
            'number': number, 'state': 'OPEN', 'draft': False, 'base': 'main', 'head': head, 'headline': subject,
            'message': subject, 'committed': at(minute)[0], 'closes': [ticket], 'rollup': 'PENDING', 'checks': [],
            'mergedAt': None, 'updatedAt': at(minute)[0], 'comments': [],
            'files': [{'filename': 'tools/links.py', 'status': 'added'}]})
        self.j.save_world()

    def ci(self, number, conclusion, minute):
        p = self.pull(number)
        p['checks'] = [{'name': 'build', 'status': 'COMPLETED', 'conclusion': conclusion,
                        'startedAt': at(minute)[0], 'run': at(minute - 1)[0], 'runId': 7000 + minute}]
        p['rollup'] = conclusion
        self.j.save_world()

    def read_pull(self, op, number):
        """The pull request read back by its number: state, head and merge time."""
        self.reads[op] = self.reads.get(op, 0) + 1
        p = self.pull(number)
        return {'state': p['state'], 'head': p['head'], 'merged_at': p['mergedAt']}

    def merge(self, op, number, head, minute):
        """`gh pr merge --merge --match-head-commit HEAD`: merges only that head, once."""
        self.calls[op] = self.calls.get(op, 0) + 1
        fault = self.faults.pop(0) if self.faults else None
        p = self.pull(number)
        if fault == 'revoked':
            return 'refused: the App can no longer write to this repository'
        if p['state'] == 'MERGED':
            return 'already merged'
        if p['head'] != head:
            return 'refused: the head moved'
        p.update(state='MERGED', mergedAt=at(minute)[0], updatedAt=at(minute)[0])
        for ticket in p['closes']:
            self.issue(ticket)['state'] = 'CLOSED'
        self.effects[op] = self.effects.get(op, 0) + 1
        self.merge_commits[number] = hashlib.sha1(('merge\n' + head).encode()).hexdigest()
        self.j.save_world()
        if fault == 'lose_reply':
            raise Lost(op)
        return 'merged'


class RevokedAppAPI:
    """GitHub's App API after the owner removed the App's installation: no installation for this owner."""

    def __init__(self, case):
        requests = self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append(('GET', self.path))
                body = json.dumps([] if self.path == '/app/installations' else {'message': 'synthetic'}).encode()
                self.send_response(200 if self.path == '/app/installations' else 404)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        case.addCleanup(self.server.server_close)
        case.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]


class Attempt:
    """One installed first hour through a verified merge, with its fault cases on the way."""

    PR = 930

    def __init__(self, case, mutate=None):
        self.case = case
        self.mutate = mutate or {}
        # #637: the explicit App skip is its own attempt; every owner-equivalent
        # step the installed tools take at Connect is recorded where it happens.
        self.conversation = skipped_conversation() if self.mutate.get('skip_app') else CONVERSATION
        self.tool_actions = []
        self.recording_actions = True
        self.install_journey = load('first_hour_install_journey', ROOT / 'tools/install/tests/journey/test_journey.py')
        self.notes = {}
        self.cases = []
        self.frontiers = []
        self._install()
        self.cloudroom = CloudRoom(self.j.dir)
        self.github = GitHub(self.j)
        self._fleet()
        self._review()
        self._merge()
        self._after_merge()
        self.result = self._result()

    # 1. #1109's journey, unchanged, with this attempt's conversation.
    def _install(self):
        ij_module = self.install_journey
        captured = {}
        original_consumer, original_module = ij_module.Consumer, ij_module.module

        def consumer(case):
            captured['consumer'] = c = original_consumer(case)
            run, merge_brain = c.run, c.merge_brain

            def recorded_run(argv, check=None):
                self._owner_yes(argv)
                return run(argv, check)

            def recorded_merge(name):
                self._owner_step('tap', 'brain_merge', "The owner's merge of init's visible brain pull request (an agent stand-in).")
                return merge_brain(name)
            c.run, c.merge_brain = recorded_run, recorded_merge
            return c

        def module(name, path):
            value = original_module(name, path)
            if name == 'onboard_journey':
                value.JOURNEY = self.conversation
                base = value.Journey

                class Journey(base):
                    def __init__(inner, case):
                        super().__init__(case)
                        captured['onboarding'] = inner

                    def plan(inner, plan):
                        # The grill skill saves the confirmed spec with its public confirmation record,
                        # after the user's separate "Confirmed." and before any plan exists.
                        super().plan(plan)
                        inner.world['issues'][0]['comments'].append({
                            'id': 89001, 'at': '2026-11-01T09:50:00Z',
                            'body': '**Spec confirmed by Robin, 2026-11-01:** confirmed the synthetic spec.\n'
                                    'Private record: https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-2'})
                        inner.save_world()

                value.Journey = Journey
                self.onboard_module = value
            return value

        ij = ij_module.InstallJourney(METHOD)
        self.case.addCleanup(ij.doCleanups)
        connect_app = ij.connect_app

        def recorded_connect_app():
            # #1109's stand-in for the App's manifest flow: Create and Install are the
            # owner's two taps on GitHub, and its key steps follow the installed route.
            self._owner_step('app_manifest', 'create_app', 'Create on the App manifest page (an agent stand-in).')
            self._owner_step('app_manifest', 'install_app', 'Install on the selected repository only (an agent stand-in).')
            self._owner_step('key_route', 'key_route', 'The key steps of the installed secret route.')
            return connect_app()
        ij.connect_app = recorded_connect_app
        ij_module.Consumer, ij_module.module = consumer, module
        try:
            getattr(ij, METHOD)()
        finally:
            ij_module.Consumer, ij_module.module = original_consumer, original_module
        self.recording_actions = False
        self.ij, self.c, self.j = ij, captured['consumer'], captured['onboarding']
        self.build, self.state = ij.build, ij.state
        self.fleet_sh = self.build / 'runtime/skills/launch-fleet/scripts/fleet.sh'
        self.manifest = self._manifest()

    def _manifest(self):
        for name in os.listdir(self.c.downloads):
            if name.endswith('.manifest.json'):
                return (self.c.downloads / name).read_bytes()
        raise AssertionError('the downloaded manifest is missing')

    def env(self):
        env = self.j.env()
        env['PATH'] = '%s:%s' % (self.cloudroom.bin, env['PATH'])
        env['FIRST_HOUR_THREADS'] = str(self.cloudroom.file)
        return env

    def frontier(self, label):
        """The installed launch-fleet frontier for this spec, as its due lines."""
        result = subprocess.run(['sh', str(self.fleet_sh), 'spec', str(self.j.spec)], env=self.env(),
                                capture_output=True, text=True, timeout=120)
        self.case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.frontiers.append((label, lines))
        return lines

    def ticket(self, number):
        return next(t for t in self.j.tickets if t['number'] == number)

    def rules(self):
        return self.j.rules()

    # 2. The fleet: the fleet thread's starts land on CloudRoom and GitHub.
    def _fleet(self):
        self.case.assertEqual(len(self.j.spawns()), 1, 'the fleet thread started once')
        if self.mutate.get('tick_start'):
            # A known way to fail (J87 Q1): a stale instruction also starts work through the engine's tick.
            self.c.run([str(self.build / 'openwiz'), 'fleet', 'tick', '--spec', str(self.j.spec)])
        self.started = [t['number'] for t in self.j.tickets if not t['blockers']]
        self.builder_ops = {}
        for n in self.started:
            op = intent('start_agent', f'{REPO}#{n}:builder')
            self.builder_ops[n] = op
            branch = 'room/%d-%s' % (n, re.sub(r'[^a-z0-9]+', '-', self.ticket(n)['title'].split(': ', 1)[1].lower()).strip('-'))
            self.cloudroom.start(op, '#%d: %s' % (n, self.ticket(n)['title']), branch, self.j.settings['harness'])
            self.github.comment(self.github.issue(n), 'launch-fleet: started', 45)
        self.agents_running = self.frontier('fleet started')
        self._repeat_approval()

    def _onboarding_state(self):
        return work('setup_state', 'onboard/state.json', sha(canonical(json.loads(self.j.state.read_text()))),
                    'owner_state_read_back')

    def _start_work(self, ops):
        return [work('pending_operation', op, fingerprint('start_agent', request), 'provider_read_back')
                for op, request in ops]

    def builder_request(self, n):
        return {'repository': REPO, 'ticket': n, 'role': 'builder', 'settings': self.j.settings}

    def builder_observation(self, n, before, after):
        op = self.builder_ops[n]
        threads = self.cloudroom.matching('#%d: ' % n)
        return {'operation_id': op, 'kind': 'start_agent', 'phase_before': before, 'phase_after': after,
                'effect_count': len(threads), 'attempts': len(self.j.spawns()),
                'reconciliation': 'provider_read_back'}

    def _repeat_approval(self):
        """The approved launch is pressed again (a reload, a repeated yes): one execution, no second start."""
        ops = [(self.builder_ops[n], self.builder_request(n)) for n in sorted(self.builder_ops)]
        before = [self._onboarding_state()] + self._start_work(ops)
        digest = self.j.confirmation()
        self.j.queue({'fleet': [{'exit': 0, 'stdout': self.j.fleet_view(['building'] * 3 + ['blocked'] * 2)}]})
        again = self.j.helper(['launch', '--spec', str(self.j.spec), '--yes', '--confirm', digest])
        self.notes['repeat_launch'] = (again.returncode, again.stdout)
        if self.mutate.get('second_tick'):
            self.j.spawns = (lambda spawns: lambda: spawns() + spawns()[:1])(self.j.spawns)
        after = [self._onboarding_state()] + self._start_work(ops)
        operations = [self.builder_observation(n, 'applied', 'applied') for n in sorted(self.builder_ops)]
        self.cases.append(recovery('repeat_approval', before, after, operations, {
            'what_happened': 'The approved launch was confirmed again after it had run: the fleet thread started '
                             'once, and the repeat only read its record.',
            'took_effect': 'yes',
            'next_action': 'Nothing to repeat: the three builders started once.'}))

    # 3. Review: a green hand-back, the independent reviewer, its verdict at the exact head.
    def _review(self):
        n = 921
        title = self.ticket(n)['title'].split(': ', 1)[1]
        self.branch = next(t['branch'] for t in self.cloudroom.matching('#%d: ' % n))
        self.head, self.tree = self.github.push(self.branch, {'tools/links.py': 'synthetic: ' + title})
        self.github.open_pull(self.PR, n, self.head, '#%d: %s, green' % (n, title), 47)
        self.github.ci(self.PR, 'FAILURE' if self.mutate.get('ci_red') else 'SUCCESS', 49)
        self.review_due = self.frontier('green hand-back')
        reviewer = self.rules()['reviewer_' + FAMILY[self.j.settings['harness']]]
        self.reviewer_settings = reviewer
        self.review_op = intent('start_agent', f'{REPO}#{self.PR}@{self.head}:reviewer')
        self.review_request = {'repository': REPO, 'pull_request': self.PR, 'head': self.head, 'role': 'reviewer',
                               'settings': reviewer}
        due = 'review #%d for #%d at %s: first review' % (self.PR, n, self.head)
        if due not in self.review_due:
            self.merge_due = self.frontier('no review due')
            return
        self._process_restart(reviewer)
        verdict = 'CHANGES' if self.mutate.get('changes') else 'APPROVE'
        approved_head = '0' * 40 if self.mutate.get('stale_verdict') else self.head
        self.github.comment(self.github.pull(self.PR), 'VERDICT: %s at %s\n\nSynthetic review.' % (verdict, approved_head), 54)
        self.merge_due = self.frontier('approved')

    def _pending(self, op, kind, request, basis='provider_read_back'):
        return work('pending_operation', op, fingerprint(kind, request), basis)

    def _repository_work(self):
        return [work('branch', self.branch, self.head, 'repository_read_back'),
                work('commit', self.head, self.tree, 'repository_read_back')]

    def _process_restart(self, reviewer):
        """The fleet thread stops just after CloudRoom started the reviewer, before its record; it reconciles by op id."""
        pull = self.github.pull(self.PR)
        claim = self.github.comment(pull, 'launch-fleet: review starting %s' % self.head, 50)
        before = self._repository_work() + [self._pending(self.review_op, 'start_agent', self.review_request)]
        title = 'Review #%d at %s' % (self.PR, self.head[:7])
        self.cloudroom.faults.append('stop_after_effect')
        try:
            self.cloudroom.start(self.review_op, title, None, reviewer['harness'])
        except Lost:
            pass
        phase_before = 'uncertain'
        # Restarted: before anything else, read the exact resource by its title.
        found = self.cloudroom.matching(title)
        if not found or self.mutate.get('blind_restart'):
            self.cloudroom.start(self.review_op, title, None, reviewer['harness'])
        found = self.cloudroom.matching(title)
        for c in pull['comments']:
            if c['id'] == claim:
                c['body'] = 'launch-fleet: review started %s' % self.head
        self.github.j.save_world()
        after = self._repository_work() + [self._pending(self.review_op, 'start_agent', self.review_request)]
        self.reviewer_threads = found
        operations = [{'operation_id': self.review_op, 'kind': 'start_agent', 'phase_before': phase_before,
                       'phase_after': 'applied', 'effect_count': len(found),
                       'attempts': self.cloudroom.calls[self.review_op],
                       'reconciliation': 'none' if self.mutate.get('blind_restart') else 'provider_read_back'}]
        self.cases.append(recovery('process_restart', before, after, operations, {
            'what_happened': 'The fleet thread stopped after CloudRoom started the reviewer and before it recorded the '
                             'start. On restart it read the reviewer thread back by its title first: it was there, '
                             'so it recorded the start and started nothing again.',
            'took_effect': 'yes',
            'next_action': 'Nothing to repeat: one reviewer is reviewing that exact head.'}))

    # 4. The merge: refused while the App's access is revoked, then once, its reply lost and read back.
    def _merge(self):
        n = 921
        self.merge_op = intent('merge', f'{REPO}#{self.PR}@{self.head}')
        self.merge_request = {'repository': REPO, 'pull_request': self.PR, 'match_head_commit': self.head}
        self.merged = None
        due = 'merge #%d for #%d at %s: APPROVE and CI green' % (self.PR, n, self.head)
        if due not in self.merge_due:
            return
        tool = [sys.executable, '-I', '-B', str(self.build / 'runtime/setup/setup.py')]
        check = lambda base: json.loads(self.c.run([*tool, 'check', '--state-dir', str(self.state), '--api-base', base], 0).stdout)['results']
        work_now = lambda: ([self._onboarding_state()] + self._repository_work()
                            + [self._pending(self.merge_op, 'merge', self.merge_request)])
        # Revoked: the owner removed the App's installation; the merge is refused before any effect.
        before = work_now()
        self.github.faults.append('revoked')
        said = self.github.merge(self.merge_op, self.PR, self.head, 55)
        revoked = RevokedAppAPI(self.case)
        self.notes['revoked'] = (said, check(revoked.base)['github_app'])
        self.cases.append(recovery('revoked_access', before, work_now(), [
            {'operation_id': self.merge_op, 'kind': 'merge', 'phase_before': 'proposed', 'phase_after': 'refused',
             'effect_count': self.github.effects.get(self.merge_op, 0), 'attempts': self.github.calls[self.merge_op],
             'reconciliation': 'none'}], {
            'what_happened': "GitHub refused the merge: the App's installation was removed. Nothing merged; the "
                             'branch, its commit, the approval and the pending merge stayed.',
            'took_effect': 'no',
            'next_action': 'Reconnect the GitHub App to this repository in setup; the merge then runs once.'}))
        # Reconnected: setup reads the App back as verified.
        self.notes['reconnected'] = check(self.install_journey.AppAPI(self.case).base)['github_app']
        # The merge again, after reading the pull request back: its reply is lost after the effect.
        before = work_now()
        read = self.github.read_pull(self.merge_op, self.PR)
        self.case.assertEqual((read['state'], read['head']), ('OPEN', self.head))
        self.github.faults.append('lose_reply')
        try:
            self.github.merge(self.merge_op, self.PR, self.head, 57)
        except Lost:
            pass
        if self.mutate.get('blind_merge_retry'):
            self.github.merge(self.merge_op, self.PR, self.head, 58)
            self.github.reads.pop(self.merge_op)
        else:
            self.merged = self.github.read_pull(self.merge_op, self.PR)
        self.merged = {'state': self.github.pull(self.PR)['state'], 'head': self.github.pull(self.PR)['head'],
                       'merged_at': self.github.pull(self.PR)['mergedAt']} if self.merged is None else self.merged
        self.cases.append(recovery('lost_reply', before, work_now(), [self.merge_observation('refused')], {
            'what_happened': "The merge's reply was lost. Before anything else the pull request was read back: it "
                             'was merged at the approved head, so nothing was sent again.',
            'took_effect': 'yes',
            'next_action': 'Nothing to repeat: the pull request merged once.'}))

    def merge_observation(self, before):
        return {'operation_id': self.merge_op, 'kind': 'merge', 'phase_before': before,
                'phase_after': 'applied' if self.github.effects.get(self.merge_op) else 'refused',
                'effect_count': self.github.effects.get(self.merge_op, 0), 'attempts': self.github.calls[self.merge_op],
                'reconciliation': 'provider_read_back' if self.github.reads.get(self.merge_op) else 'none'}

    # 5. After the merge: the frontier reads it back; a refused update and an interrupted setup keep the work.
    def _after_merge(self):
        self.after_merge = self.frontier('merged')
        self._update_rejected()
        self._setup_interrupted()

    def _setup_records(self):
        value = json.loads((self.state / 'setup/state.json').read_text())
        return value

    def _update_rejected(self):
        ij_module = self.install_journey
        inventory = lambda: ([work('setup_state', 'setup/state.json', sha(canonical(self._setup_records())), 'owner_state_read_back'),
                              self._onboarding_state()] + self._repository_work())
        before = inventory()
        current = os.readlink(self.c.root / 'current')
        bad = ij_module.release(self.c.dir / 'update', source='2' * 40, tamper=True)
        downloads = self.c.dir / 'update-downloads'
        out = io.StringIO()
        code = ij_module.entry().main(['download', '--target', ij_module.TARGET, '--dir', str(downloads)],
                                      fetch=ij_module.Transport(bad), stdout=out)
        self.case.assertEqual(code, 0, out.getvalue())
        refused = self.c.entry('install', '--assets', str(downloads), '--target', ij_module.TARGET,
                               '--root', str(self.c.root), check=5)
        self.notes['update'] = {'outcome': json.loads(refused.stdout)['outcome'],
                                'last_good_selected': os.readlink(self.c.root / 'current') == current,
                                'update_build_absent': not (self.c.root / 'state/service/builds' / ('2' * 40)).exists()}
        self.cases.append(recovery('update_rejected', before, inventory(), [], {
            'what_happened': 'A tampered update was refused before activation: the last good build stays selected, '
                             'and the saved setup, the onboarding record and the merged branch are unchanged.',
            'took_effect': 'no',
            'next_action': 'Keep using the selected build; install a verified update later.'}))

    def _setup_interrupted(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__)), 'setup-interrupted',
                                 '--runtime', str(self.build / 'runtime'), '--state', str(self.state)],
                                capture_output=True, text=True, timeout=120)
        self.case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.notes['setup_interrupted'] = value['observed']
        self.cases.append(value['document'])

    # 6. The attempt's result document.
    def _stage(self, ident, state, evidence, reason):
        return {'id': ident, 'state': state, 'evidence': evidence, 'reason': reason}

    def _result(self):
        ij_module = self.install_journey
        manifest = json.loads(self.manifest)
        setup = self._setup_records()
        rules = self.rules()
        pull = self.github.pull(self.PR)
        e = lambda basis, minute, detail: {'basis': basis, 'at_ms': at(minute)[1], 'detail': detail}
        line = '> ' + ij_module.LINE + '\n'
        installed_skill = (self.build / 'runtime/skills/install/SKILL.md').read_text()
        harness_code = self._component(setup, 'harness')
        approval = next(c for c in self.j.world['issues'][0]['comments'] if c['id'] == 90001)
        confirmation = next(c for c in self.j.world['issues'][0]['comments'] if c['id'] == 89001)
        stages = [
            self._stage('public_instruction', 'verified' if line in installed_skill else 'missing',
                        [e('instruction_opened', 0, 'The public install line resolves to the packaged install skill.')],
                        'The install line resolves to the installed skill (recording: nobody opened it).'),
            self._stage('install', 'verified', [e('install_result', 2, 'install.v1 result: activated, verified build.')],
                        'The actual install entry installed and activated the verified synthetic build.'),
            self._stage('connections', 'verified' if harness_code == 'harness_verified' else 'unknown',
                        [e('harness_listed', 5, 'setup.v1 says the harness is listed, not that its login is usable.')],
                        'Setup observed: ' + ', '.join('%s %s' % (k, self._component(setup, k)) for k in
                                                       ('cloudroom', 'harness', 'personal_github', 'github_app', 'project'))
                        + '; a listed harness is not a usable login.'),
            self._stage('idea', 'verified' if json.loads(self.j.state.read_text()).get('repo') == REPO else 'missing',
                        [e('idea_saved', 9, 'The onboarding record saved the fresh idea\'s spec for the selected repository.')],
                        'A fresh idea for the owner\'s selected repository, from this grill.'),
            self._stage('spec_confirmation', 'verified', [e('decision_saved', 10, 'The saved spec confirmation, read back.')],
                        'Confirmed separately, before any plan existed (comment %d).' % confirmation['id']),
            self._stage('plan_approval', 'verified' if self._approval_current() else 'failed',
                        [e('decision_saved', 12, 'The saved approval of the exact current plan revision, read back.')],
                        'Approved separately, with a fingerprint matching the current plan (comment %d).' % approval['id']),
            self._stage('fleet', 'verified' if len(self.cloudroom.matching('#')) >= 3 else 'missing',
                        [e('agents_running', 45, 'The approved frontier\'s three builders run, read back from CloudRoom.')],
                        'The fleet thread started the approved frontier once.'),
        ]
        verdict = self._verdict(pull)
        green = pull['rollup'] == 'SUCCESS' and all(c['conclusion'] == 'SUCCESS' for c in pull['checks'])
        merged = self.merged is not None and self.merged['state'] == 'MERGED' and self.merged['head'] == self.head
        closed = pull['state'] != 'OPEN'
        stages += [
            self._stage('review', 'verified' if verdict == 'APPROVE' else ('failed' if verdict else 'missing'),
                        [e('review_approve_exact_head', 54, 'An independent APPROVE naming the pull request\'s head.')] if verdict == 'APPROVE' else [],
                        'The other family\'s reviewer approved the exact head.' if verdict == 'APPROVE' else 'No APPROVE at the exact head.'),
            self._stage('ci', 'verified' if green else 'failed',
                        [e('ci_green_exact_head', 49, 'Every required check green on that head.')] if green else [],
                        'The required check is green on the head.' if green else 'A required check failed on the head.'),
            self._stage('merge', 'verified' if merged else 'missing',
                        [e('merge_read_back', 58, 'GitHub reads the pull request back as merged at the approved head.')] if merged
                        else ([e('pr_closed', 58, 'Closed, not read back as merged at the approved head.')] if closed else []),
                        'Merged at the approved head, read back.' if merged else 'No verified merge.'),
        ]
        builder_threads = self.cloudroom.matching('#%d: ' % 921)
        seat = lambda settings, threads, extra: {
            'harness': SEAT_HARNESS[settings['harness']], 'model': settings['model'], 'effort': settings['effort'],
            'location': CONVERSATION and json.loads(self.j.state.read_text())['choices']['agents'],
            'usable': 'verified' if any(t['harness'] == settings['harness'] for t in threads) else 'unknown',
            'evidence': [e('harness_run_observed', 50, 'The recording CloudRoom ran that harness for this attempt.')]
                        if any(t['harness'] == settings['harness'] for t in threads) else [],
            'extra_prerequisites': extra}
        operations = self._setup_operations(setup)
        operations += [{'operation_id': self.builder_ops[n], 'kind': 'start_agent', 'phase': 'applied',
                        'effect_count': len(self.cloudroom.matching('#%d: ' % n)),
                        'attempts': len(self.j.spawns()), 'reconciliation': 'provider_read_back'}
                       for n in sorted(self.builder_ops)]
        if self.review_op in self.cloudroom.calls:
            operations.append({'operation_id': self.review_op, 'kind': 'start_agent', 'phase': 'applied',
                               'effect_count': len(getattr(self, 'reviewer_threads', [])),
                               'attempts': self.cloudroom.calls[self.review_op],
                               'reconciliation': 'none' if self.mutate.get('blind_restart') else 'provider_read_back'})
        if self.merge_op in self.github.calls:
            o = self.merge_observation('refused')
            operations.append({'operation_id': o['operation_id'], 'kind': 'merge', 'phase': o['phase_after'],
                               'effect_count': o['effect_count'], 'attempts': o['attempts'],
                               'reconciliation': o['reconciliation']})
        operations += [self._access_operation(setup)] if self._access_operation(setup) else []
        retained = ([work('setup_state', 'setup/state.json', sha(canonical(setup)), 'owner_state_read_back'),
                     self._onboarding_state()] + self._repository_work()
                    + [work('pending_operation', o['operation_id'], f, 'owner_state_read_back')
                       for o, f in self._setup_pending(setup)]
                    + self._start_work([(self.builder_ops[n], self.builder_request(n)) for n in sorted(self.builder_ops)]))
        if self.review_op in self.cloudroom.calls:
            retained.append(self._pending(self.review_op, 'start_agent', self.review_request))
        if self.merge_op in self.github.calls:
            retained.append(self._pending(self.merge_op, 'merge', self.merge_request))
        return {
            'schema': 'openwiz.first-hour.v1', 'kind': 'result', 'verdict': 'unverified', 'proof_class': 'recording',
            'synthetic_assumptions': ASSUMPTIONS, 'private_record': None,
            'candidate': {'known': {'version': manifest['version'], 'source': manifest['source'],
                                    'target': manifest['target'], 'manifest_sha256': hashlib.sha256(self.manifest).hexdigest()}},
            'repository': {'known': {'full_name': self.j.world['repo'], 'selected_by_owner': True}},
            'clock': {'started_at_ms': {'unknown': 'a recording measures no first-hour time'},
                      'ended_at_ms': {'unknown': 'a recording measures no first-hour time'}, 'limit_ms': 3600000},
            'stages': stages,
            'builder': seat(self.j.settings, builder_threads, []),
            'reviewer': seat(self.reviewer_settings, getattr(self, 'reviewer_threads', []),
                             ['A sign-in for the other family\'s harness, explained before the plan started.']),
            'waits': [], 'help': [],
            'retained_work': retained,
            'operations': operations,
            'interruptions': [c['case'] for c in self.cases],
            'findings': [],
            'gaps': [{'claim': 'PR1', 'reason': 'A recording: the timed live first hour is #2207.'},
                     {'claim': 'PR2', 'reason': 'Usable Codex and Claude Code logins are observed only live (#2207).'},
                     {'claim': 'PR4', 'reason': 'Browser restart and removal have no installed seam here; see the README.'}],
            'gates': {'cloudroom_setup': {'decision_ticket': 2201, 'state': 'unresolved', 'producers': []},
                      'paid_offer': {'decision_ticket': 2202, 'state': 'settled', 'producers': [2293]},
                      'feedback': {'decision_ticket': 2203, 'state': 'settled', 'producers': [2292]}},
            'ten_minute_fleet': {'owner': 1110, 'state': 'unmeasured', 'elapsed_ms': None},
        }

    def _component(self, setup, name):
        return ((setup.get('observations') or {}).get(name) or {}).get('code')

    def _approval_current(self):
        out = subprocess.run(['sh', str(self.onboard_module.REVISION), str(self.j.spec)], env=self.j.env(),
                             capture_output=True, check=True)
        return hashlib.sha256(out.stdout).hexdigest() == self.j.approval['fingerprint']

    def _verdict(self, pull):
        verdicts = [c for c in pull['comments'] if c['body'].startswith('VERDICT: ')]
        if not verdicts:
            return None
        m = re.match(r'VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})', verdicts[-1]['body'])
        if not m or m[2] != pull['head']:
            return None
        return m[1]

    def _setup_pending(self, setup):
        return [(o, o['fingerprint']) for o in setup['operations']]

    def _setup_operations(self, setup):
        """The setup operations #1109's journey saved (setup's prepare and init of the project), read back."""
        return [{'operation_id': o['operation_id'], 'kind': o['kind'], 'phase': o['phase'],
                 'effect_count': 1 if o['phase'] == 'applied' else 0, 'attempts': 1 if o['phase'] == 'applied' else 0,
                 'reconciliation': 'none'} for o in setup['operations'] if o['kind'] != 'configure_access']

    def _access_operation(self, setup):
        found = [o for o in setup['operations'] if o['kind'] == 'configure_access']
        if not found:
            return None
        observed = self.cases[-1]['case']['operations'][0]
        return {'operation_id': found[0]['operation_id'], 'kind': 'configure_access', 'phase': found[0]['phase'],
                'effect_count': observed['effect_count'], 'attempts': observed['attempts'],
                'reconciliation': observed['reconciliation']}

    # 7. The 0.0.16 receipt (#637): the same attempt's owner actions, fleet start and merge,
    # bound to this result document, with the key and brain faults at the installed seams.
    def _owner_yes(self, argv):
        """An installed tool's `--yes` at Connect: the owner's yes to exactly that proposal."""
        if not self.recording_actions or '--yes' not in argv:
            return
        words = [str(a) for a in argv]
        tool = next((Path(w).name for w in words if w.endswith(('.py', '/openwiz'))), '')
        stage = {('setup.py', 'prepare'): 'prepare_project', ('github_login.py', 'skip-app'): 'skip_app',
                 ('github_login.py', 'sign-in'): 'github_sign_in', ('openwiz', 'init'): 'init'}
        found = next((v for (t, sub), v in stage.items() if t == tool and sub in words), 'other_yes')
        self._owner_step('sign_in' if found == 'github_sign_in' else 'confirmation', found,
                         "The owner's yes to the installed %s proposal (an agent stand-in)." % found)

    def _owner_step(self, kind, stage, detail):
        """One owner-equivalent step an installed tool or the journey took for the owner: it counts like a tap."""
        if self.recording_actions:
            self.tool_actions.append((kind, stage, detail))

    def owner_actions(self, key_steps):
        """Every owner-equivalent interaction, one entry each, in the attempt's order: the
        conversation's own turns, and at its Connect step each stand-in the installed tools took."""
        found, turns = [], self.conversation['turns']
        for i, turn in enumerate(turns):
            if 'setup' in turn:
                for kind, stage, detail in self.tool_actions:
                    if kind == 'key_route':
                        found += [('protected_paste' if step == 'paste_protected_prompt' else 'key_step', step,
                                   'Owner step %s of the installed secret route (an agent stand-in).' % step,
                                   'agent_for_owner') for step in key_steps]
                    else:
                        found.append((kind, stage, detail, 'agent_for_owner'))
            elif 'user' in turn:
                following = turns[i + 1] if i + 1 < len(turns) else {}
                if turn.get('confirms') == 'spec':
                    kind, stage = 'confirmation', 'spec_confirmation'
                elif following.get('approve'):
                    kind, stage = 'approval', 'plan_approval'
                elif 'permits' in turn:
                    kind, stage = 'spending_approval', 'launch'
                elif turn['user'] in ('Confirm.', 'Confirmed.', 'Yes.'):
                    kind, stage = 'confirmation', turn['step']
                else:
                    kind, stage = 'typed_choice', turn['step']
                found.append((kind, stage, "The owner's recorded %s turn and its submission." % turn['step'], 'owner'))
        return [{'at_ms': at(i)[1], 'kind': kind, 'actor': actor, 'stage': stage, 'detail': detail}
                for i, (kind, stage, detail, actor) in enumerate(found)]

    def capability(self, env=None, store=None):
        """The installed App tool's secret_capability document for this attempt's state: no network, no write."""
        argv = [sys.executable, '-I', '-B', str(self.build / 'runtime/github-app/setup.py'), '--agent-for',
                REPO.split('/')[0], '--capability', '--state-dir', str(self.state)] + (
            ['--secret-store', str(store)] if store else [])
        result = subprocess.run(argv, cwd=self.c.project, env=dict(self.c.env(), **(env or {})),
                                capture_output=True, text=True, timeout=60)
        self.case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def fleet_start(self):
        """How the first fleet started, read back: CloudRoom's spawns, the spec's fleet record and the engine's log."""
        # The recording fleet thread's first wake (its builders started in _fleet) also leaves launch-fleet's
        # fleet record on the spec; written only for the receipt, so the first-hour attempt reads as before.
        self.j.fleet_record()
        spawns = [a for a in self.j.spawns() if a[:2] == ['thread', 'spawn']]
        titles = [a[a.index('--title') + 1] for a in spawns if '--title' in a]
        comments = next(i for i in self.j.world['issues'] if i['number'] == self.j.spec)['comments']
        loops = [int(n) for c in comments for n in re.findall(r'^launch-fleet: fleet active, loop fleet-([0-9]+)$',
                                                               c['body'], re.M)]
        said = [int(m) for _, r in self.j.calls for m in re.findall(r'every ([0-9]+) minutes', r.stdout)]
        engine = self.c.engine_log.read_text().splitlines() if self.c.engine_log.exists() else []
        activations = sum(1 for line in engine if line.startswith('openwiz engine'))
        ticks = sum(1 for line in engine if line.startswith('openwiz fleet tick'))
        threads = sum(1 for t in titles if t.startswith('Fleet #%d: ' % self.j.spec))
        route = 'engine' if activations else ('fleet_tick' if ticks else ('launch_fleet' if threads else 'none'))
        return {'schema': 'openwiz.first-merge-kit-fleet.v1', 'proof_class': 'recording', 'private_record': None,
                'route': route, 'fleet_threads': threads,
                'loop': {'spec': loops[0], 'every_minutes': said[-1]} if loops == [self.j.spec] and said else None,
                'engine_activations': activations, 'tick_starts': ticks, 'builders': len(self.builder_ops),
                'reviewers': len(getattr(self, 'reviewer_threads', []))}

    def first_merge(self):
        """The recording `first_merge_receipt`, bound to this attempt's exact result document."""
        if getattr(self, 'receipt', None) is not None:
            return self.receipt
        skip = bool(self.mutate.get('skip_app'))
        self.result_text = json.dumps(self.result, indent=1) + '\n'
        self.fleet = self.fleet_start()
        self.capability_doc = None if skip else self.capability()
        key_steps = [] if skip else [s['step'] for s in self.capability_doc['steps']
                                     if s['actor'] == 'owner' and s['counted']]
        log = self.owner_actions(key_steps)
        pull = self.github.pull(self.PR)
        verdicts = [re.match(r'VERDICT: APPROVE at ([0-9a-f]{40})', c['body']) for c in pull['comments']]
        reviewed = [m[1] for m in verdicts if m][-1:] or ['0' * 40]
        green = pull['rollup'] == 'SUCCESS' and all(c['conclusion'] == 'SUCCESS' for c in pull['checks'])
        merged = self.merged is not None and self.merged['state'] == 'MERGED' and self.merged['head'] == self.head
        when = calendar.timegm(time.strptime(pull['mergedAt'], '%Y-%m-%dT%H:%M:%SZ')) * 1000 if pull['mergedAt'] else 0
        brain_only = all(f['filename'].startswith('.openwiz/') for f in pull['files'])
        idea = next(t['user'] for t in self.conversation['turns'] if t['step'] == 'project' and 'user' in t)
        route = 'not_used' if skip else self.capability_doc['route']
        self.receipt = {
            'schema': 'openwiz.setup-onboard.v1', 'kind': 'first_merge_receipt', 'proof_class': 'recording',
            'synthetic_assumptions': ASSUMPTIONS + RECEIPT_ASSUMPTIONS, 'private_record': None, 'verdict': 'unverified',
            'binding': {'first_hour_result_sha256': sha(self.result_text), 'candidate': self.result['candidate'],
                        'repository': {'known': self.result['repository']['known']['full_name']},
                        'merge': {'pull_request': self.PR, 'head': self.head,
                                  'merge_commit': self.github.merge_commits.get(self.PR, '0' * 40),
                                  'merged_at_ms': when, 'basis': 'merge_read_back' if merged else 'pr_closed',
                                  'change': 'init_only' if brain_only else 'implementation',
                                  'reviewed_head': reviewed[0], 'ci_green_head': self.head if green else '0' * 40}},
            'instruction': self.install_journey.LINE, 'idea': idea,
            'clock': {'started_at_ms': {'unknown': 'a recording measures no time'},
                      'ended_at_ms': {'unknown': 'a recording measures no time'},
                      'limit_ms': 1800000, 'rule': 'strictly_less_than'},
            'actions': {'count': {'known': len(log)}, 'limit': 5, 'log': log},
            'identity': 'personal_login' if skip else 'app', 'app_registration': 'skipped' if skip else 'created',
            'secret_route': route, 'secret_route_observed': False,
            'decisions': {'spec_confirmation': self._stage_state('spec_confirmation') == 'verified',
                          'plan_approval': self._stage_state('plan_approval') == 'verified'},
            'waits': [{k: w[k] for k in ('kind', 'started_at_ms', 'ended_at_ms', 'detail')} for w in self.result['waits']],
            'help': [{k: h[k] for k in ('at_ms', 'source', 'detail')} for h in self.result['help']],
            'freshness': {'machine': 'unknown', 'repository': 'unknown', 'seeded_openwiz_state': True,
                          'initial_record': 'missing'}}
        codes_report = receipt_checks.check(self.receipt)
        self.receipt['verdict'] = 'fail' if codes_report.failures else 'unverified'
        return self.receipt

    def _stage_state(self, ident):
        return next(s['state'] for s in self.result['stages'] if s['id'] == ident)

    def _owner_work(self):
        app = self.state / 'service/app/app.json'
        return ([work('setup_state', 'setup/state.json', sha(canonical(self._setup_records())), 'owner_state_read_back'),
                 self._onboarding_state()] + self._repository_work()
                + ([work('setup_state', 'service/app/app.json', sha(app.read_text()), 'owner_state_read_back')]
                   if app.exists() else []))

    def key_faults(self):
        """The key's delivery faults through the installed App tool on this attempt's own state: each
        route's capability as delivered, and a lost key never registering a replacement App."""
        before = self._owner_work()
        connects = lambda: sum(1 for o in self._setup_records()['operations'] if o['kind'] == 'connect_app')
        registrations = connects()
        key = base64.b64encode(b'synthetic key bytes, not a key\n').decode()
        folder = Path(tempfile.mkdtemp(prefix='first-hour-key-', dir=self.c.dir))
        sink = folder / 'secret-sink'
        sink.write_text('#!/bin/sh\ncat > /dev/null\n')
        sink.chmod(0o700)
        docs = {'none': self.capability(),
                'delivered': self.capability({'OPENWIZ_GITHUB_APP_KEY': key, 'OPENWIZ_GITHUB_APP_ID': '1001'}),
                'foreign_id': self.capability({'OPENWIZ_GITHUB_APP_KEY': key, 'OPENWIZ_GITHUB_APP_ID': '1002'}),
                'key_only': self.capability({'OPENWIZ_GITHUB_APP_KEY': key}),
                'agent_save': self.capability(store=sink)}
        again = subprocess.run([sys.executable, '-I', '-B', str(self.build / 'runtime/github-app/setup.py'),
                                '--agent-for', REPO.split('/')[0], '--state-dir', str(self.state)],
                               cwd=self.c.project, env=self.c.env(), capture_output=True, text=True, timeout=60)
        after = self._owner_work()
        self.key_notes = {'reregister_exit': again.returncode, 'reregister_said': again.stderr,
                          'registrations': (registrations, connects())}
        self.key_case = recovery('refused_access', before, after, [], {
            'what_happened': 'The App key arrived missing, partial or with another App id, and once only through an '
                             'unobserved agent-side store: each was reported as it is, and a run without the key was '
                             'refused instead of registering a second App. Setup, onboarding and the merged branch stayed.',
            'took_effect': 'no',
            'next_action': 'Deliver the existing App\'s key through the protected prompt; never register again.'})
        return docs

    def companion_check(self):
        """The separate public-code check: installed init on a copy of this attempt's state for a public repository,
        its companion creation's reply lost once, then resumed."""
        folder = Path(tempfile.mkdtemp(prefix='first-hour-companion-', dir=self.c.dir))
        state = folder / 'state'
        shutil.copytree(self.state, state)
        public = REPO.split('/')[0] + '/synthetic-public'
        self.c.github(public)
        world = json.loads(self.c.world.read_text())
        world['repos'][public.lower()].update(private=False, visibility='public')
        world['faults'].append({'method': 'POST', 'path': 'user/repos', 'mode': 'lose', 'times': 1})
        self.c.world.write_text(json.dumps(world))
        init = lambda *args: self.c.run([str(self.build / 'openwiz'), 'init', '--repository', public,
                                         '--state-dir', str(state), '--json', *args])
        preview = json.loads(init().stdout)
        op = preview['operation_id']
        pending = lambda: [work('pending_operation', o['operation_id'], o['fingerprint'], 'owner_state_read_back')
                           for o in json.loads((state / 'setup/state.json').read_text())['operations']
                           if o['operation_id'] == op]
        before = pending()
        first = init('--yes', '--operation', op)
        phase = next(o['phase'] for o in json.loads((state / 'setup/state.json').read_text())['operations']
                     if o['operation_id'] == op)
        second = init('--yes', '--operation', op)
        created = [c for c in json.loads(self.c.world.read_text())['log'] if c == ['POST', 'user/repos']]
        final = json.loads(second.stdout)
        self.companion = {'preview': preview, 'first_exit': first.returncode, 'phase_after_lost_reply': phase,
                          'final': final, 'creates': len(created),
                          'companion': json.loads(self.c.world.read_text())['repos'].get(public.lower() + '-brain')}
        self.companion_case = recovery('lost_reply', before, pending(), [
            {'operation_id': op, 'kind': 'prepare_project', 'phase_before': phase, 'phase_after': 'applied',
             'effect_count': len(created), 'attempts': 2, 'reconciliation': 'provider_read_back'}], {
            'what_happened': "The private companion's creation reply was lost. The resumed init read the companion "
                             'back before any other call, then linked it and proposed the brain once.',
            'took_effect': 'yes',
            'next_action': 'Nothing to repeat: one private companion, linked to the public code.'})
        return self.companion


def skipped_conversation():
    """The same recorded first hour with the owner's explicit App skip at Connect (#637's skip-App check)."""
    value = json.loads(json.dumps(CONVERSATION))
    for turn in value['turns']:
        if turn.get('setup') == 'app':
            turn['setup'] = 'personal_login'
        if turn.get('answers', {}).get('app_choice') == 'create':
            turn['answers']['app_choice'] = 'skip'
            turn['user'] = 'Skip the App; use my own login. Codex, syn-codex-model-01, high.'
    return value


RECEIPT_ASSUMPTIONS = [
    "Every owner action is a recorded conversation turn or an installed tool's stand-in at Connect; no person "
    'tapped anything, and the key steps are the installed route\'s documented owner steps, not observed.',
    'The recording repository holds filled fleet settings before setup (seeded state); its machine and freshness '
    'are not a supported fresh machine.',
    'The merge commit is a digest the recording GitHub derives from the merged head.',
]
receipt_checks = load('first_hour_journey_receipt_checks', ROOT / 'tools/install/tests/setup-onboard-contract/check.py')

def setup_interrupted(runtime, state):
    """configure_access on the installed runtime and the journey's own setup state; stopped, then resumed."""
    sys.path.insert(0, str(runtime / 'access'))
    sys.path.insert(0, str(ROOT / 'tools/install/access/fixtures'))
    import access
    from provider import Recording, credentials, selected
    assert Path(access.__file__).resolve().parent == (runtime / 'access').resolve(), 'the installed access tool'
    assert Path(access.store.__file__).resolve().parent == (runtime / 'setup').resolve(), 'the installed store'
    base = Path(os.environ.get('TMPDIR', '/tmp'))
    folder = Path(__import__('tempfile').mkdtemp(prefix='first-hour-access-', dir=base))
    try:
        plan_file, secret_file = folder / 'plan.json', folder / 'secrets.json'
        p, secrets = selected(), credentials()
        for path, value in ((plan_file, p), (secret_file, secrets)):
            path.write_text(json.dumps(value))
            path.chmod(0o600)
        provider = Recording(p, secrets)
        read = lambda: access.store.Store(str(state)).read()
        provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': read()['operations']}
        runs = []

        def tool(*args):
            with __import__('contextlib').redirect_stdout(io.StringIO()):
                return access.execute(['configure', '--state-dir', str(state), '--plan', str(plan_file), *args],
                                      http=provider, local=provider.local)

        def apply(operation_id):
            calls = len(provider.calls)
            try:
                return tool('--yes', '--operation', operation_id, '--secrets', str(secret_file))['operation']
            except SystemExit:
                return None
            finally:
                if len(provider.calls) > calls:
                    runs.append(len(provider.calls) - calls)

        pending = lambda value, oid: [{'kind': 'pending_operation', 'id': o['operation_id'], 'content': o['fingerprint'],
                                       'basis': 'owner_state_read_back'} for o in value['operations'] if o['operation_id'] == oid]
        proposed = tool()['operation']
        oid = proposed['operation_id']
        setup_kept = lambda value: [{'kind': 'pending_operation', 'id': o['operation_id'], 'content': o['fingerprint'],
                                     'basis': 'owner_state_read_back'} for o in value['operations'] if o['kind'] != 'configure_access']
        before = pending(read(), oid) + setup_kept(read())
        calls_before_apply = len(provider.calls)
        provider.interrupt = True
        lost = apply(oid)
        phase_before = next(o['phase'] for o in read()['operations'] if o['operation_id'] == oid)
        provider.interrupt = False
        again = tool()['operation']
        resumed = apply(again['operation_id'])
        final = read()
        op = next(o for o in final['operations'] if o['operation_id'] == oid)
        applied = sum(1 for o in final['operations'] if o['fingerprint'] == proposed['fingerprint'] and o['phase'] == 'applied')
        operations = [{'operation_id': oid, 'kind': 'configure_access', 'phase_before': phase_before,
                       'phase_after': op['phase'], 'effect_count': applied, 'attempts': len(runs),
                       'reconciliation': 'provider_read_back' if len(runs) > 1 else 'none'}]
        prepare = [o for o in final['operations'] if o['kind'] != 'configure_access']
        operations += [{'operation_id': o['operation_id'], 'kind': o['kind'], 'phase_before': o['phase'],
                        'phase_after': o['phase'], 'effect_count': 1 if o['phase'] == 'applied' else 0,
                        'attempts': 1 if o['phase'] == 'applied' else 0, 'reconciliation': 'none'} for o in prepare]
        document = recovery('setup_interrupted', before, pending(final, oid) + setup_kept(final), operations, {
            'what_happened': 'The phone-access check stopped before any reply; its saved operation stayed uncertain, '
                             'and the resumed check reused the same operation id. The project setup was untouched.',
            'took_effect': 'yes' if applied or prepare else 'no',
            'next_action': 'Nothing to repeat: the access route is recorded as checked.'},
            ASSUMPTIONS + ["configure_access makes no provider write: its effect is the owner-state record of the "
                           "checked route; each verification run that reached #2222's recording access provider is one attempt."])
        observed = {'calls_before_apply': calls_before_apply, 'lost_reply_returned': lost is not None,
                    'same_operation_id': again['operation_id'] == oid,
                    'resumed_phase': None if resumed is None else resumed['phase'],
                    'provider_writes': sum(1 for c in provider.calls if c[0] not in ('GET', 'local-read'))}
        return {'document': document, 'observed': observed}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main(argv):
    if len(argv) == 5 and argv[0] == 'setup-interrupted' and argv[1] == '--runtime' and argv[3] == '--state':
        print(json.dumps(setup_interrupted(Path(argv[2]), Path(argv[4]))))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
