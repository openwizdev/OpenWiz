#!/usr/bin/env python3
"""Public CLI proofs for the ticket journey (#1384). All data is synthetic.

The world, worked by hand (journey-contract.md's rules):

Spec 4100 names docs/grills/2030-01-01-synthetic.md; plan graph approved,
revision 1, at 2030-01-01T09:00:00Z; its record names thread S (shared).

Ticket 4101 (complete): ready 2030-01-01T11:00Z, builder start 12:00 (thread
B). PR 4201 closes it, merged 2030-01-02T06:00Z. Verdicts: 16:00 CHANGES
(full review; R1 high Spec `Kind: fail-open`, R2 medium Standards no marker,
R3 low Sweep `Kind: made-up`), 20:00 CHANGES (re-check; R4 medium Sweep
`Kind: stale-docs`), 20:01 the same post again (duplicate), 21:00 a
self-check (not independent), next day 05:00 APPROVE (re-check 2).
Rounds 3; first-time approval false; fix rounds 2: round 1 answers R1 fixed,
R2 disputed (18:00); round 2 answers R2 fixed, R4 fixed (22:00, edited).
Findings by kind: fail-open 1, stale-docs 1, unknown 2 (R2, R3), others 0.
CI: runs 7001 (1 attempt), 7002 (2 attempts: a rerun), 7003; run 6999 was
created before the PR opened and is not its own. Attempts 4, reruns 1.
Ready to merged: 11:00 to next day 06:00 = 19 hours.
Usage, thread B: day 1 1000 tokens / 2 credits / $1, day 2 2000 / 4 / $2;
reviewer thread R (on the PR): day 1 500 / 1 / usd unreported.
Claude tokens 3500 known, credits 7 known, usd unknown; GPT unattributed.

Ticket 4102 (shared parent, open): ready, builder start (thread C), no PR.
Thread C's GPT row reports 0 / 0 / $0: three known zeros. Claude unattributed.

Ticket 4103 (missing history): no spec, label or builder record. PR 4202
closes it, unreviewed, no CI, merged 2030-01-02T02:00Z. Its PR names thread
D, which ticket 4102 also names: D (day 1 50 tokens, day 2 700) is tied to
neither, so both stay unattributed for Claude.

Spec 4100's shared thread S: claude day 1 300 tokens / 0 credits / $0 known.

Daily usage, day 1 (1 merge, PR 4203 at 23:00Z): claude 2050 tokens
(1000+500+300+200+50), 5 credits, usd unknown (R's is unreported), ratio
2050/merge. Day 2 (2 merges): claude 2700 tokens, 5 credits, $3; ratio
1350 tokens, 2.5 credits, $1.50 per merge; sandbox 1 hour, usd unknown.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get('JOURNEY_PY', HERE / 'journey.py')).resolve()
FIXTURES = HERE / 'fixtures' / 'journey'
REPO = 'example/factory'
WEB = 'https://github.com/' + REPO
BASE = 'repos/' + REPO
# Literal, independently written query contract; only these reads answer.
PRS = '''query($owner:String!,$name:String!,$cursor:String){repository(owner:$owner,name:$name){pullRequests(first:100,after:$cursor){nodes{number mergedAt closedAt closingIssuesReferences(first:100){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage endCursor}}} pageInfo{hasNextPage endCursor}}}}'''
ISSUE = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){number url createdAt closedAt body parent{number} comments(first:100,after:$cursor){nodes{databaseId url createdAt updatedAt body} pageInfo{hasNextPage endCursor}}}}}'''
LABELS = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){timelineItems(itemTypes:[LABELED_EVENT],first:100,after:$cursor){nodes{... on LabeledEvent{createdAt label{name}}} pageInfo{hasNextPage endCursor}}}}}'''
PULL = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){number url createdAt mergedAt closedAt headRefName baseRefOid headRefOid mergeCommit{oid} body comments(first:100,after:$cursor){nodes{databaseId url createdAt updatedAt body} pageInfo{hasNextPage endCursor}}}}}'''
H1, H2, H3 = 'a' * 40, 'b' * 40, 'c' * 40
BASE_OID, MERGE_OID, H4, M2 = 'd' * 40, 'e' * 40, 'f' * 40, '1' * 40
HASH = {'settings': '2' * 64, 'cases': '3' * 64, 'code': '4' * 64}
KINDS = ['missing-proof', 'stale-docs', 'spec-mismatch', 'fail-open', 'unknown']


def q(document, number=None, cursor=None):
    args = ['api', 'graphql', '-f', 'query=' + document, '-f', 'owner=example', '-f', 'name=factory']
    if number is not None:
        args += ['-F', f'number={number}']
    if cursor is not None:
        args += ['-f', 'cursor=' + cursor]
    return json.dumps(args)


def rest(path):
    return json.dumps(['api', '--method', 'GET', path])


def runs_path(branch, page):
    return f'{BASE}/actions/workflows/ci.yml/runs?branch={branch}&event=pull_request&per_page=100&page={page}'


def answer(value):
    return {'stdout': json.dumps(value), 'exit': 0}


def conn(nodes, more=False, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def comment(cid, where, at, body, updated=None):
    return {'databaseId': cid, 'url': f'{WEB}/{where}#issuecomment-{cid}', 'createdAt': at,
            'updatedAt': updated or at, 'body': body}


def issue(n, created, body, parent, comments, closed=None):
    return {'data': {'repository': {'issue': {
        'number': n, 'url': f'{WEB}/issues/{n}', 'createdAt': created, 'closedAt': closed, 'body': body,
        'parent': None if parent is None else {'number': parent}, 'comments': conn(comments)}}}}


def labels(events):
    return {'data': {'repository': {'issue': {'timelineItems': conn(
        [{'createdAt': at, 'label': {'name': name}} for at, name in events])}}}}


def pull(n, created, merged, branch, head, merge, body, comments):
    return {'data': {'repository': {'pullRequest': {
        'number': n, 'url': f'{WEB}/pull/{n}', 'createdAt': created, 'mergedAt': merged, 'closedAt': merged,
        'headRefName': branch, 'baseRefOid': BASE_OID, 'headRefOid': head,
        'mergeCommit': None if merge is None else {'oid': merge}, 'body': body, 'comments': conn(comments)}}}}


def run(rid, attempt, head, created, conclusion='success', started=None):
    return {'id': rid, 'run_attempt': attempt, 'head_sha': head, 'head_branch': 'room/4101-synthetic',
            'event': 'pull_request', 'status': 'completed', 'conclusion': conclusion, 'created_at': created,
            'run_started_at': started or created, 'html_url': f'{WEB}/actions/runs/{rid}', 'pull_requests': []}


def inventory(n, merged, tickets):
    return {'number': n, 'mergedAt': merged, 'closedAt': merged, 'closingIssuesReferences': conn(
        [{'number': t, 'repository': {'nameWithOwner': REPO}} for t in tickets])}


REVIEW1 = f'''VERDICT: CHANGES at {H1}

Full review by Codex, Sol 6.1, High. CI green on this commit: rust.

Intent: synthetic.

- **R1 [high]** `a.py:1` (Spec) The guard accepts an unknown form. Kind: fail-open. Fix: refuse it.
  Shows the break: `x` printed `0`; the ticket needs `1`. Rerun at this commit: same.
- **R2 [medium]** `b.py:2` (Standards) A test checks text, not behaviour. Fix: test the CLI.
- **R3 [low]** `c.py:3` (Sweep) A typo. Kind: made-up. Fix: spell it. Follow-up: #4999.

Next: the builder fixes R1 and R2.'''
REVIEW2 = f'''VERDICT: CHANGES at {H2}

Re-check 1 of R1, R2 and the code changed since aaaaaaa, by Codex, Sol 6.1, High.

Intent: synthetic.

- **R1 [high]** resolved at bbbbbbb: the command prints 1.
- **R2 [medium]** disputed, kept: the test still reads text.
- **R3 [low]** follow-up #4999.
- **R4 [medium]** `d.py:4` (Sweep) The README names the old flag. Kind: stale-docs. Fix: rename it.

Next: the orchestrator's diagnosis for R2; the builder fixes R4.'''
SELF = f'''VERDICT: APPROVE at {H3}

Self-check by a helper. Kind: missing-proof.

- **R9 [high]** `e.py:5` (Spec) Not a review. Kind: missing-proof. Fix: none.'''
REVIEW3 = f'''VERDICT: APPROVE at {H3}

Re-check 2 of R2, R4 and the code changed since bbbbbbb, by Codex, Sol 6.1, High.

- **R1 [high]** resolved at bbbbbbb: as before.
- **R2 [medium]** resolved at ccccccc: the CLI test.
- **R3 [low]** follow-up #4999.
- **R4 [medium]** resolved at ccccccc: renamed.

Next: none open.'''
PR_BODY = f'''Closes #4101

Experiment: build-ticket-r2
CF4: settings {HASH['settings']} cases {HASH['cases']} code {HASH['code']} revision {H1}
'''


def world():
    spec = issue(4100, '2030-01-01T08:00:00Z', 'Feeds from [the grill](docs/grills/2030-01-01-synthetic.md).', None, [
        comment(5001, 'issues/4100', '2030-01-01T09:00:00Z', '**Plan graph approved by Owner, 2030-01-01, revision 1:** "yes"'),
        comment(5002, 'issues/4100', '2030-01-01T09:05:00Z', 'launch-fleet: plan recorded, thread thr_synthshared'),
        comment(5003, 'issues/4100', '2030-01-01T09:10:00Z', 'An ordinary comment naming docs/grills/other.md.')])
    t1 = issue(4101, '2030-01-01T10:00:00Z', 'Ticket of spec #4100.', 4100, [
        comment(5101, 'issues/4101', '2030-01-01T12:00:00Z', 'launch-fleet: started, thread thr_synthbuild'),
        comment(5102, 'issues/4101', '2030-01-01T12:30:00Z', 'launch-fleet: started is quoted here, not a record'),
        comment(5103, 'issues/4101', '2030-01-01T13:00:00Z', 'ordinary')], '2030-01-02T06:00:00Z')
    t2 = issue(4102, '2030-01-01T10:30:00Z', 'Ticket of spec #4100.', 4100, [
        comment(5111, 'issues/4102', '2030-01-01T12:00:00Z', 'launch-fleet: started, thread thr_synthbuild2'),
        comment(5112, 'issues/4102', '2030-01-01T12:05:00Z', 'launch-fleet: note, thread thr_synthboth')])
    t3 = issue(4103, '2030-01-02T01:00:00Z', 'No spec.', None, [], '2030-01-02T02:00:00Z')
    p1 = pull(4201, '2030-01-01T14:00:00Z', '2030-01-02T06:00:00Z', 'room/4101-synthetic', H3, MERGE_OID, PR_BODY, [
        comment(5201, 'pull/4201', '2030-01-01T16:00:00Z', REVIEW1),
        comment(5202, 'pull/4201', '2030-01-01T17:00:00Z', f'launch-fleet: review started {H1[:7]}, thread thr_synthreview'),
        comment(5203, 'pull/4201', '2030-01-01T18:00:00Z', 'R1 fixed at bbbbbbb: the test.\nR2 disputed: it is behaviour.'),
        comment(5204, 'pull/4201', '2030-01-01T20:00:00Z', REVIEW2),
        comment(5205, 'pull/4201', '2030-01-01T20:01:00Z', REVIEW2),
        comment(5206, 'pull/4201', '2030-01-01T21:00:00Z', SELF),
        comment(5207, 'pull/4201', '2030-01-01T22:00:00Z', 'R2 fixed at ccccccc: CLI.\nR4 fixed at ccccccc: renamed.',
                '2030-01-01T22:30:00Z'),
        comment(5208, 'pull/4201', '2030-01-02T05:00:00Z', REVIEW3)])
    p2 = pull(4202, '2030-01-02T01:30:00Z', '2030-01-02T02:00:00Z', 'room/4103-synthetic', H4, M2, 'Closes #4103', [
        comment(5301, 'pull/4202', '2030-01-02T01:40:00Z', 'launch-fleet: merged, thread thr_synthboth')])
    runs = [run(6999, 1, H1, '2030-01-01T13:00:00Z'), run(7001, 1, H1, '2030-01-01T14:01:00Z'),
            run(7002, 2, H2, '2030-01-01T19:00:00Z', started='2030-01-01T19:30:00Z'), run(7003, 1, H3, '2030-01-02T04:00:00Z')]
    attempt = {'id': 7002, 'run_attempt': 1, 'head_sha': H2, 'status': 'completed', 'conclusion': 'failure',
               'created_at': '2030-01-01T19:00:00Z', 'run_started_at': '2030-01-01T19:00:00Z',
               'html_url': f'{WEB}/actions/runs/7002/attempts/1'}
    prs = [inventory(4201, '2030-01-02T06:00:00Z', [4101]), inventory(4202, '2030-01-02T02:00:00Z', [4103]),
           inventory(4203, '2030-01-01T23:00:00Z', [4999]), inventory(4204, None, [])]
    return {
        q(PRS): answer({'data': {'repository': {'pullRequests': conn(prs)}}}),
        q(ISSUE, 4100): answer(spec), q(ISSUE, 4101): answer(t1), q(ISSUE, 4102): answer(t2), q(ISSUE, 4103): answer(t3),
        q(LABELS, 4101): answer(labels([('2030-01-01T10:05:00Z', 'Infra'), ('2030-01-01T11:00:00Z', 'ready-for-agent'),
                                         ('2030-01-01T15:00:00Z', 'ready-for-agent')])),
        q(LABELS, 4102): answer(labels([('2030-01-01T11:30:00Z', 'ready-for-agent')])),
        q(LABELS, 4103): answer(labels([])),
        q(PULL, 4201): answer(p1), q(PULL, 4202): answer(p2),
        rest(runs_path('room%2F4101-synthetic', 1)): answer({'total_count': 4, 'workflow_runs': runs}),
        rest(runs_path('room%2F4103-synthetic', 1)): answer({'total_count': 0, 'workflow_runs': []}),
        rest(f'{BASE}/actions/runs/7002/attempts/1'): answer(attempt)}


def usage_files():
    def row(thread, tokens, credits, usd):
        return {'thread': thread, 'tokens': tokens, 'credits': credits, 'usd': usd}
    day1 = {'date': '2030-01-01', 'complete': True,
            'claude': [row('thr_synthbuild', 1000, 2, 1), row('thr_synthreview', 500, 1, None),
                       row('thr_synthshared', 300, 0, 0), row('thr_synthother', 200, 1, 1),
                       row('thr_synthboth', 50, 1, 1)],
            'gpt': [row('thr_synthbuild2', 0, 0, 0)], 'sandbox': {'hours': 6, 'usd': 3}}
    day2 = {'date': '2030-01-02', 'complete': True,
            'claude': [row('thr_synthbuild', 2000, 4, 2), row('thr_synthboth', 700, 1, 1)],
            'gpt': [], 'sandbox': {'hours': 1, 'usd': None}}
    return [day1, day2]


def usage_of(entry):
    return {f"{u['provider']}/{u['unit']}": (u['status'], u['value'], u['missing_days']) for u in entry['usage']}


class Journey(unittest.TestCase):
    def cli(self, *args, data=None, usage=None, tickets=(4101, 4102, 4103), raw=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'gh').symlink_to(HERE / 'fake-gh')
        (root / 'world.json').write_text(json.dumps(world() if data is None else data))
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                   FAKE_GH_WORLD=str(root / 'world.json'), FAKE_GH_LOG=str(root / 'calls'),
                   GH_TOKEN='synthetic-app-token', PYTHONDONTWRITEBYTECODE='1')
        argv = [sys.executable, '-I', str(SCRIPT), *args]
        if args and args[0] == 'collect' and not raw:
            argv += ['--repo', REPO, '--out', str(root / 'out')]
            for t in tickets:
                argv += ['--ticket', str(t)]
            for i, u in enumerate(usage_files() if usage is None else usage):
                (root / f'usage{i}.json').write_text(u if isinstance(u, str) else json.dumps(u))
                argv += ['--usage', str(root / f'usage{i}.json')]
        p = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=30)
        calls = [json.loads(s)['args'] for s in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
        out = root / 'out' / 'journeys.json'
        doc = json.loads(out.read_text()) if out.exists() else None
        return p, doc, root, calls

    def collected(self, *args, **kw):
        p, doc, root, calls = self.cli('collect', *args, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return doc, root, calls

    def consumer(self, name, doc):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'journeys.json'
        path.write_text(json.dumps(doc))
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), name, str(path)], text=True, capture_output=True, timeout=30)
        return p, (json.loads(p.stdout) if p.returncode == 0 and name != 'check' else None)

    def ticket(self, doc, n):
        return next(t for t in doc['tickets'] if t['ticket'] == n)

    def pr(self, doc, n):
        return next(p for p in doc['pull_requests'] if p['number'] == n)

    def kinds(self, events):
        return [e['kind'] for e in events]

    # P5: PR creation and commit dates cannot reveal the first successful push.
    # Existing v1 cases cover ready-time only and miss that substitution.
    def test_sourced_first_push_export_and_unknown_history(self):
        data = world()
        pr = data[q(PULL, 4201)]
        raw = json.loads(pr['stdout'])
        raw['data']['repository']['pullRequest']['comments']['nodes'].append(
            comment(8901, 'pull/4201', '2030-01-01T13:01:00Z',
                    f'First successful push: {H1} at 2030-01-01T12:00:00Z'))
        data[q(PULL, 4201)] = answer(raw)
        # Synthetic dates precede the actual collection clock.
        data = json.loads(json.dumps(data).replace('2030-', '2020-'))
        doc, root, _ = self.collected('--with-outcomes', data=data)
        side = json.loads((root/'out/outcomes.json').read_text())
        one, two = side['journey']['measurements']
        self.assertEqual(one['first_push']['at'], '2020-01-01T12:00:00Z')
        self.assertEqual(one['first_push']['kind'], 'builder-push-receipt')
        self.assertEqual(side['sources'][one['first_push']['source']], f'{WEB}/pull/4201#issuecomment-8901')
        self.assertEqual(one['merge']['status'], 'verified')
        self.assertEqual(len(one['rounds']), 3)
        self.assertEqual(len(one['helpers']), 1)
        self.assertEqual(two['first_push']['status'], 'unknown')
        self.assertEqual(one['defects']['status'], 'unknown')
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'bench', str(root/'out/journeys.json'),
                                 '--outcomes', str(root/'out/outcomes.json')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)['outcomes']
        self.assertEqual(rows[0]['first_push_to_merged_hours'], 18)
        self.assertEqual(rows[0]['builder_start_to_merged_hours'], 18)
        self.assertEqual(json.loads(result.stdout)['tickets'][0]['ready_to_merged_hours'],19)
        self.assertIsNone(rows[1]['first_push_to_merged_hours'])

    def test_receipt_ambiguity_edits_and_force_updates(self):
        for mode, expected in [('one', 'observed'), ('repeat','observed'), ('conflict','unknown'), ('edited','unknown')]:
            with self.subTest(mode=mode):
                data=world(); raw=json.loads(data[q(PULL,4201)]['stdout'])
                comments=raw['data']['repository']['pullRequest']['comments']['nodes']
                comments.append(comment(8901,'pull/4201','2030-01-01T14:00:00Z',
                    f'First successful push: {H1} at 2030-01-01T12:00:00Z',
                    '2030-01-01T15:00:00Z' if mode=='edited' else None))
                if mode in ('repeat','conflict'):
                    comments.append(comment(8902,'pull/4201','2030-01-01T15:00:00Z',
                        f'First successful push: {H1} at 2030-01-01T{12 if mode=="repeat" else 13}:00:00Z'))
                data[q(PULL,4201)]=answer(raw)
                data=json.loads(json.dumps(data).replace('2030-','2020-'))
                _,root,_=self.collected('--with-outcomes',data=data)
                side=json.loads((root/'out/outcomes.json').read_text())
                self.assertEqual(side['journey']['measurements'][0]['first_push']['status'],expected)
                if mode=='one':
                    # Force-updated head and vanished receipt cannot reset established evidence.
                    changed=copy.deepcopy(data); raw=json.loads(changed[q(PULL,4201)]['stdout'])
                    raw['data']['repository']['pullRequest']['headRefOid']=H4
                    raw['data']['repository']['pullRequest']['comments']['nodes']=[]
                    changed[q(PULL,4201)]=answer(raw)
                    _,nextroot,_=self.collected('--with-outcomes','--previous',str(root/'out'),data=changed)
                    nextside=json.loads((nextroot/'out/outcomes.json').read_text())
                    self.assertEqual(nextside['journey']['measurements'][0]['first_push'],side['journey']['measurements'][0]['first_push'])

    # P5: a rerun and its later causal fix are one root cause. A selector escape
    # has no such causal evidence. Existing review-finding tests cover neither.
    def test_defect_window_dedup_resolution_and_followup(self):
        import hashlib
        policy={'rule':'explicit-causal-fix-link-v1','followup_hours':48,
                'deduplication':'root-cause-per-merge','unknown_attribution':'retain-unknown'}
        digest=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        data=world(); raw=json.loads(data[q(PULL,4201)]['stdout'])
        cs=raw['data']['repository']['pullRequest']['comments']['nodes']
        base={'policy':digest,'root':4901,'at':'2030-01-02T07:00:00Z','attribution':'unknown',
              'evidence':f'{WEB}/actions/runs/7901','kind':'main-red','caused_by':4201}
        cs.append(comment(8901,'pull/4201','2030-01-02T08:00:00Z','EB defect: '+json.dumps(base)))
        cs.append(comment(8902,'pull/4201','2030-01-02T09:00:00Z','EB defect: '+json.dumps(base)))
        fix={**base,'kind':'later-defect-fix','at':'2030-01-02T09:00:00Z','evidence':f'{WEB}/issues/4901'}
        cs.append(comment(8903,'pull/4201','2030-01-02T10:00:00Z','EB defect: '+json.dumps(fix)))
        cs.append(comment(8904,'pull/4201','2030-01-04T06:00:00Z','EB follow-up: '+json.dumps(
            {'policy':digest,'observed_until':'2030-01-04T06:00:00Z'})))
        cs.append(comment(8905,'pull/4201','2030-01-06T06:00:00Z','EB attribution: '+json.dumps(
            {'policy':digest,'root':4901,'at':'2030-01-06T06:00:00Z','attribution':'attributable',
             'evidence':f'{WEB}/pull/4201#issuecomment-8901'})))
        # Outside the inclusive frozen window; must not become this merge's defect.
        outside={**base,'root':4902,'at':'2030-01-05T06:00:00Z','evidence':f'{WEB}/actions/runs/7902'}
        cs.append(comment(8906,'pull/4201','2030-01-05T07:00:00Z','EB defect: '+json.dumps(outside)))
        cs.append(comment(8907,'pull/4201','2030-01-02T08:00:00Z','CI-selector escape: synthetic; no skill causal link.'))
        data[q(PULL,4201)]=answer(raw)
        inv=json.loads(data[q(PRS)]['stdout'])
        inv['data']['repository']['pullRequests']['nodes'].append(inventory(4903,'2030-01-02T09:00:00Z',[4901]))
        data[q(PRS)]=answer(inv)
        for rid, at in [(7901,'2030-01-02T07:00:00Z'),(7902,'2030-01-05T06:00:00Z')]:
            data[rest(f'{BASE}/actions/runs/{rid}')]=answer({'id':rid,'event':'push','head_branch':'main',
                'conclusion':'failure','created_at':at,'run_started_at':at,'path':'.github/workflows/ci.yml','run_attempt':1})
        data=json.loads(json.dumps(data).replace('2030-','2020-'))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'policy.json'; path.write_text(json.dumps(policy))
            _,root,_=self.collected('--defect-policy',path,data=data)
            export=json.loads((root/'out/outcomes.json').read_text())
            defects=export['journey']['measurements'][0]['defects']
            self.assertEqual(defects['status'],'mature')
            self.assertEqual(len(defects['events']),1)
            self.assertEqual(defects['events'][0]['attribution'],'unknown')
            self.assertEqual(len(defects['resolutions']),1)
            result=subprocess.run([sys.executable,'-I',str(SCRIPT),'bench',str(root/'out/journeys.json'),
                '--outcomes',str(root/'out/outcomes.json')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            row=json.loads(result.stdout)['outcomes'][0]
            self.assertEqual(row['defects'],{'attributable':1,'unattributed':0,'unknown':0})
            self.assertEqual(export['journey']['measurements'][1]['defects']['status'],'unknown')

    def test_main_red_citation_requires_ci_not_an_unrelated_workflow(self):
        import hashlib
        policy={'rule':'explicit-causal-fix-link-v1','followup_hours':48,
                'deduplication':'root-cause-per-merge','unknown_attribution':'retain-unknown'}
        digest=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        data=world();raw=json.loads(data[q(PULL,4201)]['stdout'])
        raw['data']['repository']['pullRequest']['comments']['nodes'].append(comment(8901,'pull/4201',
            '2030-01-02T08:00:00Z','EB defect: '+json.dumps({'policy':digest,'root':4901,
             'at':'2030-01-02T07:00:00Z','attribution':'attributable','evidence':f'{WEB}/actions/runs/7901',
             'kind':'main-red','caused_by':4201})))
        data[q(PULL,4201)]=answer(raw)
        data[rest(f'{BASE}/actions/runs/7901')]=answer({'id':7901,'event':'push','head_branch':'main',
            'conclusion':'failure','created_at':'2030-01-02T07:00:00Z','run_started_at':'2030-01-02T07:00:00Z','path':'.github/workflows/unrelated.yml','run_attempt':1})
        data=json.loads(json.dumps(data).replace('2030-','2020-'))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
            result,doc,_,_=self.cli('collect','--defect-policy',path,data=data)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertIsNone(doc)

    def defect_world(self, kinds=('main-red','later-defect-fix'), fix_reported_first=False, hours=48):
        """Synthetic evidence: failure 07:00, its causal fix 09:00, one root."""
        import hashlib
        policy={'rule':'explicit-causal-fix-link-v1','followup_hours':hours,
                'deduplication':'root-cause-per-merge','unknown_attribution':'retain-unknown'}
        digest=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        data=json.loads(json.dumps(world()).replace('2030-','2020-'))
        raw=json.loads(data[q(PULL,4201)]['stdout'])
        cs=raw['data']['repository']['pullRequest']['comments']['nodes']
        for kind,cid,at,reported,evidence in [
            ('main-red',8901,'2020-01-02T07:00:00Z',
             '2020-01-02T11:00:00Z' if fix_reported_first else '2020-01-02T08:00:00Z',
             f'{WEB}/actions/runs/7901'),
            ('later-defect-fix',8902,'2020-01-02T09:00:00Z','2020-01-02T10:00:00Z',f'{WEB}/issues/4901')]:
            if kind in kinds:
                cs.append(comment(cid,'pull/4201',reported,'EB defect: '+json.dumps(
                    {'policy':digest,'root':4901,'at':at,'attribution':'attributable',
                     'evidence':evidence,'kind':kind,'caused_by':4201})))
        data[q(PULL,4201)]=answer(raw)
        inv=json.loads(data[q(PRS)]['stdout'])
        inv['data']['repository']['pullRequests']['nodes'].append(inventory(4903,'2020-01-02T09:00:00Z',[4901]))
        data[q(PRS)]=answer(inv)
        data[rest(f'{BASE}/actions/runs/7901')]=answer({'id':7901,'run_attempt':1,
            'head_branch':'main','event':'push','path':'.github/workflows/ci.yml',
            'created_at':'2020-01-02T07:00:00Z','run_started_at':'2020-01-02T07:00:00Z',
            'conclusion':'failure'})
        return data,policy

    # R1: main-red is a distinct harm signal even when its root also has a fix.
    def test_main_red_root_survives_reversed_reporting_and_resume(self):
        for fix_first in (False,True):
            with self.subTest(fix_reported_first=fix_first),tempfile.TemporaryDirectory() as temp:
                data,policy=self.defect_world(fix_reported_first=fix_first)
                path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                _,root,_=self.collected('--defect-policy',path,data=data)
                exported=json.loads((root/'out/outcomes.json').read_text())
                events=exported['journey']['measurements'][0]['defects']['events']
                self.assertEqual(len(events),1)
                self.assertEqual((events[0]['kind'],events[0]['at'],events[0]['attribution']),
                                 ('main-red','2020-01-02T07:00:00Z','attributable'))
                self.assertEqual(exported['sources'][events[0]['source']],f'{WEB}/pull/4201#issuecomment-8901')
                _,resumed,_=self.collected('--defect-policy',path,'--previous',root/'out',data=data)
                again=json.loads((resumed/'out/outcomes.json').read_text())
                self.assertEqual(again['journey']['measurements'][0]['defects']['events'],events)
        # An initial main-red may gain a later fix without changing the root.
        with tempfile.TemporaryDirectory() as temp:
            data,policy=self.defect_world(kinds=('main-red',))
            path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
            _,root,_=self.collected('--defect-policy',path,data=data)
            original=json.loads((root/'out/outcomes.json').read_text())['journey']['measurements'][0]['defects']['events']
            full,_=self.defect_world(fix_reported_first=True)
            _,resumed,_=self.collected('--defect-policy',path,'--previous',root/'out',data=full)
            self.assertEqual(json.loads((resumed/'out/outcomes.json').read_text())['journey']['measurements'][0]['defects']['events'],original)

    def test_main_red_canonicalization_preserves_same_root_attribution(self):
        for fix_first in (False,True):
            with self.subTest(fix_reported_first=fix_first),tempfile.TemporaryDirectory() as temp:
                data,policy=self.defect_world(fix_reported_first=fix_first)
                raw=json.loads(data[q(PULL,4201)]['stdout'])
                cs=raw['data']['repository']['pullRequest']['comments']['nodes']
                for com in cs:
                    if com['body'].startswith('EB defect: '):
                        value=json.loads(com['body'][len('EB defect: '):]);value['attribution']='unknown'
                        com['body']='EB defect: '+json.dumps(value)
                cs.append(comment(8903,'pull/4201','2020-01-03T10:00:00Z','EB attribution: '+json.dumps(
                    {'policy':value['policy'],'root':4901,'at':'2020-01-03T10:00:00Z',
                     'attribution':'attributable','evidence':f'{WEB}/pull/4201#issuecomment-8902'})))
                data[q(PULL,4201)]=answer(raw)
                path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                _,root,_=self.collected('--defect-policy',path,data=data)
                side=json.loads((root/'out/outcomes.json').read_text())
                d=side['journey']['measurements'][0]['defects']
                self.assertEqual(len(d['events']),1);self.assertEqual(d['events'][0]['kind'],'main-red')
                self.assertEqual(d['events'][0]['attribution'],'unknown')
                self.assertEqual(len(d['resolutions']),1);self.assertEqual(d['resolutions'][0]['attribution'],'attributable')
                _,out,_=self.collected('--defect-policy',path,'--previous',root/'out',data=data)
                self.assertEqual(json.loads((out/'out/outcomes.json').read_text())['journey']['measurements'][0]['defects'],d)
                # A verdict URL on the same PR is not a verified causal record
                # for this root; selecting a canonical kind must not allow it.
                bad=copy.deepcopy(data);raw=json.loads(bad[q(PULL,4201)]['stdout'])
                raw['data']['repository']['pullRequest']['comments']['nodes'][-1]['body']=cs[-1]['body'].replace(
                    '#issuecomment-8902','#issuecomment-5201')
                bad[q(PULL,4201)]=answer(raw)
                result,doc,refused,_=self.cli('collect','--defect-policy',path,data=bad)
                self.assertEqual(result.returncode,1,result.stderr);self.assertIsNone(doc)
                self.assertFalse((refused/'out').exists())

    def test_new_main_red_cannot_rewrite_an_exported_fix_root(self):
        with tempfile.TemporaryDirectory() as temp:
            data,policy=self.defect_world(kinds=('later-defect-fix',))
            path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
            _,root,_=self.collected('--defect-policy',path,data=data)
            before={p.name:p.read_bytes() for p in (root/'out').iterdir()}
            full,_=self.defect_world(fix_reported_first=True)
            result,doc,nextroot,_=self.cli('collect','--defect-policy',path,'--previous',root/'out',data=full)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertIn('contract owner',result.stderr)
            self.assertIsNone(doc);self.assertFalse((nextroot/'out').exists())
            self.assertEqual({p.name:p.read_bytes() for p in (root/'out').iterdir()},before)

    # R2: the current successful rerun cannot erase a historical failed attempt.
    def test_main_red_failed_attempt_survives_successful_reruns(self):
        with tempfile.TemporaryDirectory() as temp:
            data,policy=self.defect_world(kinds=('main-red',))
            path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
            failed=json.loads(data[rest(f'{BASE}/actions/runs/7901')]['stdout'])
            failed['created_at']='2020-01-02T06:59:00Z'
            data[rest(f'{BASE}/actions/runs/7901')]=answer(failed)
            _,root,_=self.collected('--defect-policy',path,data=data)
            original=json.loads((root/'out/outcomes.json').read_text())['journey']['measurements'][0]['defects']['events']
            data[rest(f'{BASE}/actions/runs/7901/attempts/1')]=answer(failed)
            data[rest(f'{BASE}/actions/runs/7901')]=answer({**failed,'run_attempt':2,'conclusion':'success',
                'run_started_at':'2020-01-06T07:00:00Z'})
            for extra in ([],['--previous',root/'out']):
                with self.subTest(resumed=bool(extra)):
                    _,out,calls=self.collected('--defect-policy',path,*extra,data=data)
                    side=json.loads((out/'out/outcomes.json').read_text())
                    events=side['journey']['measurements'][0]['defects']['events']
                    self.assertEqual(len(events),1);self.assertEqual(events[0]['kind'],'main-red')
                    self.assertEqual(events[0]['at'],'2020-01-02T07:00:00Z')
                    self.assertIn(f'{WEB}/actions/runs/7901/attempts/1',side['sources'].values())
                    if extra:self.assertEqual(events,original)
            # Earlier successful attempts are read before selecting failure 2;
            # the latest failure/success does not reset that earliest identity.
            for latest in ('success','failure'):
                with self.subTest(latest=latest):
                    data[rest(f'{BASE}/actions/runs/7901/attempts/1')]=answer({**failed,'conclusion':'success'})
                    data[rest(f'{BASE}/actions/runs/7901/attempts/2')]=answer({**failed,'run_attempt':2})
                    data[rest(f'{BASE}/actions/runs/7901')]=answer({**failed,'run_attempt':3,'conclusion':latest})
                    _,out,_=self.collected('--defect-policy',path,data=data)
                    side=json.loads((out/'out/outcomes.json').read_text())
                    self.assertIn(f'{WEB}/actions/runs/7901/attempts/2',side['sources'].values())

    def test_explicit_main_red_attempt_must_be_the_cited_failure(self):
        for attempt,expected in ((1,0),(2,1)):
            with self.subTest(attempt=attempt),tempfile.TemporaryDirectory() as temp:
                data,policy=self.defect_world(kinds=('main-red',))
                path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                raw=json.loads(data[q(PULL,4201)]['stdout'])
                marker=raw['data']['repository']['pullRequest']['comments']['nodes'][-1]
                marker['body']=marker['body'].replace('/actions/runs/7901','/actions/runs/7901/attempts/'+str(attempt))
                data[q(PULL,4201)]=answer(raw)
                failed=json.loads(data[rest(f'{BASE}/actions/runs/7901')]['stdout'])
                data[rest(f'{BASE}/actions/runs/7901/attempts/1')]=answer(failed)
                data[rest(f'{BASE}/actions/runs/7901')]=answer({**failed,'run_attempt':2,'conclusion':'success'})
                result,doc,out,_=self.cli('collect','--defect-policy',path,data=data)
                self.assertEqual(result.returncode,expected,result.stderr)
                if expected==0:
                    side=json.loads((out/'out/outcomes.json').read_text())
                    self.assertIn(f'{WEB}/actions/runs/7901/attempts/1',side['sources'].values())
                    self.assertEqual(side['journey']['measurements'][0]['defects']['events'][0]['kind'],'main-red')
                else:self.assertIsNone(doc)

    def test_main_red_historical_attempt_mismatches_refuse(self):
        mutations=[('missing field',lambda r:r.pop('event')),
                   ('wrong run',lambda r:r.update(id=7902)),
                   ('wrong attempt',lambda r:r.update(run_attempt=2)),
                   ('wrong branch',lambda r:r.update(head_branch='other')),
                   ('wrong event',lambda r:r.update(event='pull_request')),
                   ('wrong workflow',lambda r:r.update(path='.github/workflows/other.yml')),
                   ('wrong time',lambda r:r.update(created_at='2020-01-02T06:59:00Z')),
                   ('incomplete conclusion',lambda r:r.update(conclusion=None)),
                   ('empty conclusion',lambda r:r.update(conclusion='')),
                   ('failed read',None)]
        for name,mutate in mutations:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                data,policy=self.defect_world(kinds=('main-red',))
                path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                failed=json.loads(data[rest(f'{BASE}/actions/runs/7901')]['stdout'])
                data[rest(f'{BASE}/actions/runs/7901')]=answer({**failed,'run_attempt':3})
                data[rest(f'{BASE}/actions/runs/7901/attempts/2')]=answer({**failed,'run_attempt':2,'conclusion':'success'})
                if mutate:
                    mutate(failed);data[rest(f'{BASE}/actions/runs/7901/attempts/1')]=answer(failed)
                else:data[rest(f'{BASE}/actions/runs/7901/attempts/1')]={'stdout':'','exit':1}
                result,doc,out,calls=self.cli('collect','--defect-policy',path,data=data)
                self.assertEqual(result.returncode,1,result.stderr);self.assertIsNone(doc)
                self.assertFalse((out/'out').exists())

    # R5: a run's creation is shared by all attempts; only the selected failed
    # attempt's start can establish occurrence, chronology and window inclusion.
    # R2 used equal timestamps for every rerun, so it missed backdated failures.
    def test_main_red_selected_attempt_time_and_frozen_window(self):
        created='2020-01-02T07:00:00Z'
        failed_at='2020-01-03T07:00:00Z'
        late='2020-01-05T07:00:00Z'
        cases=[
            ('in-window rerun failure',failed_at,failed_at,'2020-01-03T08:00:00Z',None,0,1),
            ('backdated late failure',late,created,'2020-01-06T08:00:00Z',None,1,None),
            ('assertion before failure',failed_at,created,'2020-01-02T08:00:00Z',None,1,None),
            ('correct late failure',late,late,'2020-01-06T08:00:00Z',None,0,0),
            ('missing failure time',created,created,'2020-01-03T08:00:00Z',
             lambda f,c:f.pop('run_started_at'),1,None),
            ('null failure time',created,created,'2020-01-03T08:00:00Z',
             lambda f,c:f.update(run_started_at=None),1,None),
            ('invalid failure time',created,created,'2020-01-03T08:00:00Z',
             lambda f,c:f.update(run_started_at='yesterday'),1,None),
            ('failure before creation',created,created,'2020-01-03T08:00:00Z',
             lambda f,c:f.update(run_started_at='2020-01-02T06:59:00Z'),1,None),
            ('missing current time',created,created,'2020-01-03T08:00:00Z',
             lambda f,c:c.pop('run_started_at'),1,None),
            ('current before failure',failed_at,failed_at,'2020-01-03T08:00:00Z',
             lambda f,c:c.update(run_started_at=created),1,None),
            ('inconsistent run creation',failed_at,failed_at,'2020-01-03T08:00:00Z',
             lambda f,c:f.update(created_at='2020-01-02T06:59:00Z'),1,None)]
        for pinned in (False,True):
            for name,started,claimed,reported,mutate,expected,count in cases:
                with self.subTest(pinned=pinned,case=name),tempfile.TemporaryDirectory() as temp:
                    data,policy=self.defect_world(kinds=('main-red',))
                    path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                    raw=json.loads(data[q(PULL,4201)]['stdout'])
                    marker=raw['data']['repository']['pullRequest']['comments']['nodes'][-1]
                    value=json.loads(marker['body'][len('EB defect: '):]);value['at']=claimed
                    if pinned:value['evidence']+='/attempts/2'
                    marker.update(body='EB defect: '+json.dumps(value),createdAt=reported,updatedAt=reported)
                    data[q(PULL,4201)]=answer(raw)
                    first=json.loads(data[rest(f'{BASE}/actions/runs/7901')]['stdout'])
                    first['conclusion']='success'
                    failure={**first,'run_attempt':2,'conclusion':'failure','run_started_at':started}
                    current={**first,'run_attempt':3,'run_started_at':'2020-01-06T07:00:00Z'}
                    if mutate:mutate(failure,current)
                    data[rest(f'{BASE}/actions/runs/7901/attempts/1')]=answer(first)
                    data[rest(f'{BASE}/actions/runs/7901/attempts/2')]=answer(failure)
                    data[rest(f'{BASE}/actions/runs/7901')]=answer(current)
                    result,doc,out,_=self.cli('collect','--defect-policy',path,data=data)
                    self.assertEqual(result.returncode,expected,result.stderr)
                    if expected:
                        self.assertIsNone(doc);self.assertFalse((out/'out').exists())
                    else:
                        side=json.loads((out/'out/outcomes.json').read_text())
                        events=side['journey']['measurements'][0]['defects']['events']
                        self.assertEqual(len(events),count)
                        if count:
                            self.assertEqual(events[0]['at'],'2020-01-03T07:00:00Z')
                            self.assertIn(f'{WEB}/actions/runs/7901/attempts/2',side['sources'].values())

    # R3: JSON decimal numbers remain valid at read-back and resume boundaries.
    def test_decimal_defect_policy_bench_report_and_resume(self):
        for hours in (48.0,48.5,48.1):
            with self.subTest(hours=hours),tempfile.TemporaryDirectory() as temp:
                data,policy=self.defect_world(kinds=('main-red',),hours=hours)
                path=Path(temp)/'policy.json';path.write_text(json.dumps(policy))
                _,root,_=self.collected('--defect-policy',path,data=data)
                bench=subprocess.run([sys.executable,'-I',str(SCRIPT),'bench',str(root/'out/journeys.json'),
                    '--outcomes',str(root/'out/outcomes.json')],text=True,capture_output=True)
                with self.subTest(command='bench'):
                    self.assertEqual(bench.returncode,0,bench.stderr)
                    self.assertEqual(json.loads(bench.stdout)['outcomes'][0]['defects']['attributable'],1)
                report=Path(temp)/'report.json';report.write_text('last good')
                result=subprocess.run([sys.executable,'-I',str(HERE.parent/'ci-bench/trends.py'),'report',
                    str(root/'out/journeys.json'),'--outcomes',str(root/'out/outcomes.json'),
                    '--since','2020-01-01T08:00:00Z','--until','2020-01-03T08:00:00Z','--out',str(report)],
                    text=True,capture_output=True)
                with self.subTest(command='report'):
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(report.read_text())['outcomes']['defect_policy']['followup_hours'],hours)
                resumed_result,_,resumed,_=self.cli('collect','--defect-policy',path,'--previous',root/'out',data=data)
                with self.subTest(command='resume'):
                    self.assertEqual(resumed_result.returncode,0,resumed_result.stderr)
                    self.assertEqual(json.loads((resumed/'out/outcomes.json').read_text())['defect_policy']['followup_hours'],hours)

    def test_receipt_commands_at_cf4_fake_tool_boundary(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('cf4_receipt_fake',HERE.parent/'skills-eval/fakeworld.py')
        fake=importlib.util.module_from_spec(spec);spec.loader.exec_module(fake)
        readme=(HERE/'README.md').read_text()
        capture=readme.split('<!-- EB6 capture -->')[1].split('```sh')[1].split('```')[0]
        publish=readme.split('<!-- EB6 receipt -->')[1].split('```sh')[1].split('```')[0]
        for fail in (False,True):
            world={'github':{'repo':REPO,'pulls':{'4201':{'comments':[]}}},
                   'git':{'head':H1},'now':'2030-01-01T12:00:00Z'}
            if fail: world['scripts']=[{'argv':['git','push'],'kind':'write','code':1,'out':'push refused'}]
            w=fake.World(world,(lambda p:None,lambda p:[]))
            w.shell('receipt_file=/tmp/synthetic-first-push.txt; pr=4201')
            result=w.shell(capture)
            if fail:
                self.assertNotEqual(result.code,0)
                self.assertNotIn('/tmp/synthetic-first-push.txt',w.overlay)
            else:
                self.assertEqual(result.code,0,result.out)
                result=w.shell(publish)
                self.assertEqual(result.code,0,result.out)
                self.assertEqual(w.w['github']['pulls']['4201']['comments'][0]['body'],
                    f'First successful push: {H1} at 2030-01-01T12:00:00Z\n')

    # --- a complete journey, shared parent work, reviews and CI attempts ---

    def test_complete_journey_from_grill_to_merge(self):
        doc, _, calls = self.collected()
        self.assertEqual(doc['schema'], 'closedwiz.journey.v1')
        self.assertEqual(doc['history'], 'unknown')
        self.assertEqual(doc['repo'], REPO)
        spec = doc['specs'][0]
        self.assertEqual(len(doc['specs']), 1)  # shared by 4101 and 4102, once
        self.assertEqual(self.kinds(spec['events']), ['grill', 'spec', 'plan_graph'])
        grill = spec['events'][0]
        self.assertEqual((grill['path'], grill['at'], grill['completeness']),
                         ('docs/grills/2030-01-01-synthetic.md', None, 'unknown'))
        self.assertEqual(spec['events'][2]['revision'], 1)
        t1 = self.ticket(doc, 4101)
        self.assertEqual((t1['spec'], t1['state'], t1['pull_requests'], t1['gaps']), (4100, 'merged', [4201], []))
        self.assertEqual(self.kinds(t1['events']), ['ticket', 'ready', 'builder_start'])
        self.assertEqual(t1['events'][1]['at'], '2030-01-01T11:00:00Z')
        p1 = self.pr(doc, 4201)
        self.assertEqual(p1['tickets'], [4101])
        self.assertEqual(p1['revisions'], {'base': BASE_OID, 'head': H3, 'merge': MERGE_OID})
        self.assertEqual(p1['experiment'], {'tag': 'build-ticket-r2', 'cf4': {
            'settings_hash': HASH['settings'], 'cases_hash': HASH['cases'], 'code_hash': HASH['code'], 'revision': H1}})
        self.assertEqual(self.kinds(p1['events']), ['pr_opened', 'ci_attempt', 'verdict', 'fix_round', 'ci_attempt',
                                                    'ci_attempt', 'verdict', 'verdict', 'verdict', 'fix_round',
                                                    'ci_attempt', 'verdict', 'merge'])
        self.assertEqual([e['at'] for e in p1['events'] if e['kind'] == 'ci_attempt'][1:3],
                         ['2030-01-01T19:00:00Z', '2030-01-01T19:30:00Z'])
        ci = [(e['run'], e['attempt'], e['rerun'], e['conclusion']) for e in p1['events'] if e['kind'] == 'ci_attempt']
        self.assertEqual(ci, [(7001, 1, False, 'success'), (7002, 1, False, 'failure'), (7002, 2, True, 'success'),
                              (7003, 1, False, 'success')])
        verdicts = [e for e in p1['events'] if e['kind'] == 'verdict']
        self.assertEqual([(v['verdict'], v['independent'], v['duplicate_of'] is not None) for v in verdicts],
                         [('CHANGES', True, False), ('CHANGES', True, False), ('CHANGES', True, True),
                          ('APPROVE', False, False), ('APPROVE', True, False)])
        self.assertEqual(verdicts[2]['duplicate_of'], verdicts[1]['id'])
        rounds = [e for e in p1['events'] if e['kind'] == 'fix_round']
        self.assertEqual([(r['round'], r['after'], r['answers']) for r in rounds], [
            (1, verdicts[0]['id'], [{'finding': 'R1', 'answer': 'fixed'}, {'finding': 'R2', 'answer': 'disputed'}]),
            (2, verdicts[1]['id'], [{'finding': 'R2', 'answer': 'fixed'}, {'finding': 'R4', 'answer': 'fixed'}])])
        self.assertEqual(rounds[1]['completeness'], 'edited')
        findings = {f['id']: (f['severity'], f['check'], f['kind'], f['kind_evidence'], [s['status'] for s in f['statuses']])
                    for f in p1['findings']}
        self.assertEqual(findings, {
            'R1': ('high', 'Spec', 'fail-open', 'marker', ['resolved', 'resolved']),
            'R2': ('medium', 'Standards', 'unknown', 'no marker', ['disputed, kept', 'resolved']),
            'R3': ('low', 'Sweep', 'unknown', 'unrecognised marker', ['follow-up', 'follow-up']),
            'R4': ('medium', 'Sweep', 'stale-docs', 'marker', ['resolved'])})
        self.assertEqual(self.pr(doc, 4201)['state'], 'merged')
        ids = [e['id'] for part in ('specs', 'tickets', 'pull_requests') for x in doc[part] for e in x['events']]
        self.assertEqual(len(ids), len(set(ids)))
        for part in ('specs', 'tickets', 'pull_requests'):
            for x in doc[part]:
                for e in x['events']:
                    self.assertTrue(e['source'] is None or doc['sources'][e['source']].startswith('https://github.com/'))
        # Every read is one of the world's exact calls, each once.
        self.assertEqual(sorted(json.dumps(c) for c in calls), sorted(world()))

    def test_shared_parent_and_missing_history_are_explicit(self):
        doc, _, _ = self.collected()
        t2, t3 = self.ticket(doc, 4102), self.ticket(doc, 4103)
        self.assertEqual((t2['spec'], t2['state'], t2['pull_requests']), (4100, 'open', []))
        self.assertEqual(t2['gaps'], ['no pull request', 'no merge'])
        self.assertEqual((t3['spec'], t3['state']), (None, 'merged'))
        self.assertEqual(t3['gaps'], ['no ready label', 'no builder start record', 'no spec', 'no grill path',
                                      'no plan graph approval'])
        p2 = self.pr(doc, 4202)
        self.assertEqual((p2['experiment'], p2['findings']), (None, []))
        self.assertEqual(self.kinds(p2['events']), ['pr_opened', 'merge'])

    def test_bench_consumer_counts_independent_rounds_once(self):
        doc, _, _ = self.collected()
        p, bench = self.consumer('bench', doc)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(bench['schema'], 'closedwiz.journey.bench.v1')
        rows = {r['ticket']: r for r in bench['tickets']}
        r1 = rows[4101]
        self.assertEqual((r1['rounds'], r1['first_time_approval'], r1['fix_rounds'], r1['ci_attempts'], r1['reruns'],
                          r1['ready_to_merged_hours']), (3, False, 2, 4, 1, 19))
        self.assertEqual(r1['findings'], {'missing-proof': 0, 'stale-docs': 1, 'spec-mismatch': 0, 'fail-open': 1, 'unknown': 2})
        self.assertEqual(r1['usage']['claude/tokens'], 'known')
        self.assertEqual(r1['usage']['claude/usd'], 'unknown')
        self.assertEqual(r1['usage']['gpt/tokens'], 'unattributed')
        r3 = rows[4103]
        self.assertEqual((r3['state'], r3['rounds'], r3['first_time_approval'], r3['ready_to_merged_hours']),
                         ('merged', 0, None, None))
        self.assertEqual((rows[4102]['state'], rows[4102]['pull_requests'], rows[4102]['first_time_approval']), ('open', [], None))

    def test_cf4_consumer_keeps_links_apart(self):
        doc, _, _ = self.collected()
        p, cf4 = self.consumer('cf4', doc)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(cf4['schema'], 'closedwiz.journey.findings.v1')
        self.assertEqual(cf4['by_kind'], {'missing-proof': 0, 'stale-docs': 1, 'spec-mismatch': 0, 'fail-open': 1, 'unknown': 2})
        self.assertEqual([(f['key'], f['kind'], f['severity'], f['at']) for f in cf4['findings']], [
            ('F1', 'fail-open', 'high', '2030-01-01T16:00:00Z'), ('F2', 'unknown', 'medium', '2030-01-01T16:00:00Z'),
            ('F3', 'unknown', 'low', '2030-01-01T16:00:00Z'), ('F4', 'stale-docs', 'medium', '2030-01-01T20:00:00Z')])
        self.assertEqual(cf4['provenance']['F4'], f'{WEB}/pull/4201#issuecomment-5204')
        inputs = json.dumps(cf4['findings'])
        self.assertNotIn('github.com', inputs)
        self.assertNotIn('4201', inputs)

    # --- credits and tokens ---

    def test_known_unknown_zero_and_unattributed_usage(self):
        doc, _, _ = self.collected()
        u1 = usage_of(self.ticket(doc, 4101))
        self.assertEqual(u1['claude/tokens'], ('known', 3500, []))
        self.assertEqual(u1['claude/credits'], ('known', 7, []))
        self.assertEqual(u1['claude/usd'], ('unknown', None, []))
        self.assertEqual(u1['gpt/tokens'], ('unattributed', None, []))
        u2 = usage_of(self.ticket(doc, 4102))
        self.assertEqual([u2[f'gpt/{u}'] for u in ('tokens', 'credits', 'usd')], [('known', 0, [])] * 3)
        self.assertEqual(u2['claude/tokens'], ('unattributed', None, []))
        u3 = usage_of(self.ticket(doc, 4103))  # thread D is named on 4102 and 4103: neither
        self.assertEqual({v[0] for v in u3.values()}, {'unattributed'})
        us = usage_of(doc['specs'][0])
        self.assertEqual([us[f'claude/{u}'] for u in ('tokens', 'credits', 'usd')],
                         [('known', 300, []), ('known', 0, []), ('known', 0, [])])
        for entry in doc['tickets'] + doc['specs']:
            self.assertEqual([(u['provider'], u['unit']) for u in entry['usage']],
                             [(p, u) for p in ('claude', 'gpt') for u in ('tokens', 'credits', 'usd')])
            self.assertEqual({u['attribution'] for u in entry['usage']}, {'thread-record'})

    def test_daily_usage_is_a_ratio_not_ticket_cost(self):
        doc, _, _ = self.collected()
        day1, day2 = doc['daily_usage']
        self.assertEqual((day1['date'], day1['merged_prs']), ('2030-01-01', 1))
        self.assertEqual(day1['totals']['claude']['tokens'], {'total': 2050, 'per_merged_pr': 2050})
        self.assertEqual(day1['totals']['claude']['credits'], {'total': 5, 'per_merged_pr': 5})
        self.assertEqual(day1['totals']['claude']['usd'], {'total': None, 'per_merged_pr': None})
        self.assertEqual((day2['date'], day2['merged_prs']), ('2030-01-02', 2))
        self.assertEqual(day2['totals']['claude']['tokens'], {'total': 2700, 'per_merged_pr': 1350})
        self.assertEqual(day2['totals']['claude']['credits'], {'total': 5, 'per_merged_pr': 2.5})
        self.assertEqual(day2['totals']['claude']['usd'], {'total': 3, 'per_merged_pr': 1.5})
        self.assertEqual(day2['totals']['sandbox']['usd'], {'total': None, 'per_merged_pr': None})
        # The 1350 tokens/merge ratio is never any ticket's value.
        self.assertNotIn(1350, [u['value'] for t in doc['tickets'] for u in t['usage']])

    def test_absent_partial_and_invalid_usage(self):
        doc, _, _ = self.collected(usage=[])
        self.assertEqual(doc['daily_usage'], [])
        for entry in doc['tickets'] + doc['specs']:
            self.assertEqual({(u['status'], u['value']) for u in entry['usage']}, {('absent', None)})
        self.assertEqual(usage_of(self.ticket(doc, 4101))['claude/tokens'], ('absent', None, ['2030-01-01', '2030-01-02']))
        doc, _, _ = self.collected(usage=usage_files()[:1])
        self.assertEqual(usage_of(self.ticket(doc, 4101))['claude/tokens'], ('known', 1500, ['2030-01-02']))
        self.assertEqual(usage_of(self.ticket(doc, 4103))['claude/tokens'], ('absent', None, ['2030-01-02']))
        bad = usage_files()
        bad[1]['complete'] = False
        doc, _, _ = self.collected(usage=[bad[0], bad[1], '{"date": 1}'])
        self.assertEqual(doc['daily_usage'][1:], [{'date': None, 'merged_prs': None, 'totals': None}] * 2)
        self.assertEqual(usage_of(self.ticket(doc, 4101))['claude/tokens'], ('known', 1500, ['2030-01-02']))

    # --- duplicates, pagination and malformed reads ---

    def test_paginated_reads_and_identical_duplicates(self):
        w = world()
        p1 = json.loads(w[q(PULL, 4201)]['stdout'])
        nodes = p1['data']['repository']['pullRequest']['comments']['nodes']
        first = copy.deepcopy(p1)
        first['data']['repository']['pullRequest']['comments'] = conn(nodes[:4], True, 'c-next')
        second = copy.deepcopy(p1)
        # The page shift repeats comment 5204 identically on page 2.
        second['data']['repository']['pullRequest']['comments'] = conn(nodes[3:])
        w[q(PULL, 4201)], w[q(PULL, 4201, 'c-next')] = answer(first), answer(second)
        lab = json.loads(w[q(LABELS, 4101)]['stdout'])
        events = lab['data']['repository']['issue']['timelineItems']['nodes']
        w[q(LABELS, 4101)] = answer({'data': {'repository': {'issue': {'timelineItems': conn(events[:1], True, 'l-next')}}}})
        w[q(LABELS, 4101, 'l-next')] = answer({'data': {'repository': {'issue': {'timelineItems': conn(events[1:])}}}})
        key = rest(runs_path('room%2F4101-synthetic', 1))
        runs = json.loads(w[key]['stdout'])['workflow_runs']
        older = [run(6000 + i, 1, H1, '2030-01-01T12:00:00Z') for i in range(99)]
        w[key] = answer({'total_count': 103, 'workflow_runs': older + runs[:1]})
        # Page 2 lists run 6999 again (identical) after a page shift.
        w[rest(runs_path('room%2F4101-synthetic', 2))] = answer({'total_count': 103, 'workflow_runs': runs})
        doc, _, calls = self.collected(data=w)
        self.assertEqual(doc['duplicates'], 2)
        p1 = self.pr(doc, 4201)
        self.assertEqual(sum(e['kind'] == 'ci_attempt' for e in p1['events']), 4)
        self.assertEqual(sum(e['kind'] == 'verdict' for e in p1['events']), 5)
        self.assertEqual(self.ticket(doc, 4101)['events'][1]['at'], '2030-01-01T11:00:00Z')
        self.assertEqual(len(calls), len(w))

    def test_r1_a_same_head_recheck_is_its_own_round(self):
        # After a kept dispute, a re-check at the same head with a new report
        # is a new round (4 rounds, 3 fix rounds, R5 spec-mismatch); only an
        # identical repost (5205) is a duplicate.
        w = world()
        v = json.loads(w[q(PULL, 4201)]['stdout'])
        nodes = v['data']['repository']['pullRequest']['comments']['nodes']
        recheck = REVIEW2.replace('Re-check 1 of R1, R2', 'Re-check 2 of R2').replace(
            '- **R4 [medium]**', '- **R5 [medium]** `f.py:6` (Spec) Another. Kind: spec-mismatch. Fix: it.\n- **R4 [medium]**')
        nodes.insert(7, comment(5210, 'pull/4201', '2030-01-01T23:00:00Z', recheck))
        w[q(PULL, 4201)] = answer(v)
        doc, _, _ = self.collected(data=w)
        verdicts = [e for e in self.pr(doc, 4201)['events'] if e['kind'] == 'verdict']
        self.assertEqual([(e['at'][11:16], e['duplicate_of'] is not None) for e in verdicts if e['independent']],
                         [('16:00', False), ('20:00', False), ('20:01', True), ('23:00', False), ('05:00', False)])
        p, bench = self.consumer('bench', doc)
        row = next(r for r in bench['tickets'] if r['ticket'] == 4101)
        self.assertEqual((row['rounds'], row['fix_rounds']), (4, 3))
        self.assertEqual(row['findings']['spec-mismatch'], 1)
        self.assertEqual([f['id'] for f in self.pr(doc, 4201)['findings']], ['R1', 'R2', 'R3', 'R4', 'R5'])

    def test_r4_runs_bind_to_their_own_pull_request(self):
        # PR 4205 (closes 4102) is open on the same branch while 4201 is.
        w = world()
        inv = json.loads(w[q(PRS)]['stdout'])
        inv['data']['repository']['pullRequests']['nodes'].append(inventory(4205, None, [4102]))
        w[q(PRS)] = answer(inv)
        w[q(PULL, 4205)] = answer(pull(4205, '2030-01-01T14:30:00Z', None, 'room/4101-synthetic', H2, None, '', []))
        key = rest(runs_path('room%2F4101-synthetic', 1))
        data = json.loads(w[key]['stdout'])
        # Unassociated runs inside both open windows cannot be placed: refused.
        p, doc, _, _ = self.cli('collect', data=w)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('two pull requests', p.stderr)
        self.assertIsNone(doc)
        for r in data['workflow_runs']:
            r['pull_requests'] = [{'number': 4190 if r['id'] == 6999 else 4201}]  # 6999: an older PR's
        w[key] = answer(data)
        doc, _, _ = self.collected(data=w)
        attempts = {p['number']: sum(e['kind'] == 'ci_attempt' for e in p['events']) for p in doc['pull_requests']}
        self.assertEqual(attempts, {4201: 4, 4202: 0, 4205: 0})

    def test_untrustworthy_reads_fail_without_output(self):
        def mutate(kind):
            w = world()
            if kind == 'invalid-json':
                w[q(PULL, 4201)] = {'stdout': '{', 'exit': 0}
            elif kind == 'repeated-key':
                w[q(ISSUE, 4101)] = {'stdout': '{"data": 1, "data": 2}', 'exit': 0}
            elif kind == 'graphql-errors':
                w[q(ISSUE, 4100)] = answer({'errors': [{'message': 'synthetic'}], 'data': None})
            elif kind == 'failed-read':
                w[q(LABELS, 4102)] = {'stdout': '', 'exit': 1}
            elif kind == 'missing-page':
                v = json.loads(w[q(PULL, 4202)]['stdout'])
                v['data']['repository']['pullRequest']['comments']['pageInfo'] = {'hasNextPage': True, 'endCursor': 'gone'}
                w[q(PULL, 4202)] = answer(v)
            elif kind == 'repeated-cursor':
                v = json.loads(w[q(LABELS, 4103)]['stdout'])
                v['data']['repository']['issue']['timelineItems'] = conn([{'createdAt': '2030-01-02T01:00:00Z', 'label': {'name': 'x'}}], True, 'same')
                w[q(LABELS, 4103)] = w[q(LABELS, 4103, 'same')] = answer(v)
            elif kind == 'short-runs':
                key = rest(runs_path('room%2F4103-synthetic', 1))
                w[key] = answer({'total_count': 1, 'workflow_runs': []})
            elif kind == 'wrong-type':
                v = json.loads(w[q(ISSUE, 4101)]['stdout'])
                v['data']['repository']['issue']['comments']['nodes'][0]['databaseId'] = '5101'
                w[q(ISSUE, 4101)] = answer(v)
            elif kind == 'bad-time':
                v = json.loads(w[q(PULL, 4201)]['stdout'])
                v['data']['repository']['pullRequest']['mergedAt'] = 'yesterday'
                w[q(PULL, 4201)] = answer(v)
            elif kind == 'conflicting-duplicate':
                v = json.loads(w[q(ISSUE, 4102)]['stdout'])
                nodes = v['data']['repository']['issue']['comments']['nodes']
                nodes.append(dict(nodes[0], body='launch-fleet: started, thread thr_synthelse'))
                w[q(ISSUE, 4102)] = answer(v)
            elif kind == 'foreign-run':
                key = rest(runs_path('room%2F4101-synthetic', 1))
                v = json.loads(w[key]['stdout'])
                v['workflow_runs'][1]['html_url'] = 'https://evil.invalid/runs/7001'
                w[key] = answer(v)
            elif kind.startswith('missing-field'):
                _, what, field = kind.split(':')
                key = q(ISSUE, 4101) if what == 'issue' else q(PULL, 4201)
                v = json.loads(w[key]['stdout'])
                del v['data']['repository']['issue' if what == 'issue' else 'pullRequest'][field]
                w[key] = answer(v)
            elif kind == 'run-count-changes':
                key = rest(runs_path('room%2F4101-synthetic', 1))
                runs = json.loads(w[key]['stdout'])['workflow_runs']
                older = [run(6000 + i, 1, H1, '2030-01-01T12:00:00Z') for i in range(100)]
                # Page 2 brings 2 new runs but now counts 102 of the 104: runs were lost between pages.
                w[key] = answer({'total_count': 104, 'workflow_runs': older})
                w[rest(runs_path('room%2F4101-synthetic', 2))] = answer({'total_count': 102, 'workflow_runs': runs[:2]})
            elif kind == 'run-without-association':
                key = rest(runs_path('room%2F4101-synthetic', 1))
                v = json.loads(w[key]['stdout'])
                del v['workflow_runs'][1]['pull_requests']
                w[key] = answer(v)
            elif kind.startswith('later-page'):
                # Page 2 of PR 4201 names another PR, or lacks a required field.
                v = json.loads(w[q(PULL, 4201)]['stdout'])
                pr = v['data']['repository']['pullRequest']
                nodes = pr['comments']['nodes']
                first, second = copy.deepcopy(v), copy.deepcopy(v)
                first['data']['repository']['pullRequest']['comments'] = conn(nodes[:4], True, 'p-next')
                later = second['data']['repository']['pullRequest']
                later['comments'] = conn(nodes[4:])
                if kind == 'later-page-other-pr':
                    later['number'] = 9999
                else:
                    del later['headRefOid']
                w[q(PULL, 4201)], w[q(PULL, 4201, 'p-next')] = answer(first), answer(second)
            elif kind == 'wrong-pr':
                v = json.loads(w[q(PULL, 4202)]['stdout'])
                v['data']['repository']['pullRequest']['number'] = 4209
                w[q(PULL, 4202)] = answer(v)
            return w
        for kind in ['invalid-json', 'repeated-key', 'graphql-errors', 'failed-read', 'missing-page', 'repeated-cursor',
                     'short-runs', 'wrong-type', 'bad-time', 'conflicting-duplicate', 'foreign-run', 'wrong-pr',
                     'missing-field:issue:parent', 'missing-field:issue:closedAt', 'missing-field:pull:mergedAt',
                     'missing-field:pull:closedAt', 'missing-field:pull:mergeCommit', 'run-count-changes',
                     'run-without-association', 'later-page-other-pr', 'later-page-missing-field']:
            with self.subTest(kind=kind):
                p, doc, root, _ = self.cli('collect', data=mutate(kind))
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIsNone(doc)
                self.assertFalse((root / 'out').exists())
                self.assertTrue(p.stderr.startswith('journey: '), p.stderr)

    def test_bad_arguments_read_nothing(self):
        for extra in [['--repo', '../bad', '--ticket', '1', '--out', 'x'], ['--repo', REPO, '--ticket', '0', '--out', 'x'],
                      ['--repo', REPO, '--out', 'x'], ['--repo', REPO, '--ticket', 'x1', '--out', 'x']]:
            with self.subTest(extra=extra):
                p, _, _, calls = self.cli('collect', *extra, raw=True)
                self.assertEqual(p.returncode, 2)
                self.assertEqual(calls, [])

    def test_existing_output_is_refused_before_reads(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p = subprocess.run([sys.executable, '-I', str(SCRIPT), 'collect', '--repo', REPO, '--ticket', '4101', '--out', temp.name],
                           text=True, capture_output=True, timeout=30, env=dict(os.environ, PATH='/nonexistent'))
        self.assertEqual(p.returncode, 1)
        self.assertIn('already exists', p.stderr)

    # --- privacy, conformance and the fixtures ---

    def test_nothing_private_is_saved(self):
        doc, root, _ = self.collected()
        saved = (root / 'out' / 'journeys.json').read_text()
        for secret in ['thr_synth', 'synthetic-app-token', 'room/4101', 'room%2F', 'Full review by', 'guard accepts',
                       'grill](', 'ordinary', 'it is behaviour', 'Closes #4101', 'Experiment:']:
            self.assertNotIn(secret, saved)
        self.assertEqual(sorted(p.name for p in (root / 'out').iterdir()), ['journeys.json'])

    def test_fixtures_are_the_collector_and_consumer_outputs(self):
        doc, _, _ = self.collected()
        self.assertEqual(json.loads((FIXTURES / 'journeys.json').read_text()), doc)
        for name in ('bench', 'cf4'):
            p, value = self.consumer(name, doc)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads((FIXTURES / f'{name}.json').read_text()), value)

    def test_check_accepts_conforming_and_refuses_broken_documents(self):
        doc, _, _ = self.collected()
        p, _ = self.consumer('check', doc)
        self.assertEqual(p.returncode, 0, p.stderr)

        def broken(change):
            d = copy.deepcopy(doc)
            change(d)
            return d
        t1 = lambda d: next(t for t in d['tickets'] if t['ticket'] == 4101)
        p1 = lambda d: next(p for p in d['pull_requests'] if p['number'] == 4201)
        cases = {
            'extra key': lambda d: d.update(extra=1),
            'missing key': lambda d: d.pop('history'),
            'history claimed complete': lambda d: d.update(history='complete'),
            'invented kind': lambda d: p1(d)['findings'][0].update(kind='style'),
            'kind without marker': lambda d: p1(d)['findings'][1].update(kind='fail-open'),
            'zero for absent': lambda d: t1(d)['usage'][0].update(status='absent', value=0),
            'value for unattributed': lambda d: t1(d)['usage'][3].update(value=5),
            'other attribution': lambda d: t1(d)['usage'][0].update(attribution='daily-ratio'),
            'bool as int': lambda d: p1(d)['events'][1].update(attempt=True),
            'unknown source': lambda d: p1(d)['events'][0].update(source='s999'),
            'duplicate event id': lambda d: p1(d)['events'][1].update(id=p1(d)['events'][0]['id']),
            'link outside github': lambda d: d['sources'].update(s1='https://evil.invalid/x'),
            'thread id saved': lambda d: p1(d)['events'][1].update(conclusion='thr_synthbuild'),
            'duplicate ticket': lambda d: d['tickets'].append(copy.deepcopy(t1(d)) | {'events': []}),
            'duplicate spec': lambda d: d['specs'].append(copy.deepcopy(d['specs'][0]) | {'events': []}),
            'unknown event kind': lambda d: p1(d)['events'][0].update(kind='helper_check'),
            'rerun flag wrong': lambda d: p1(d)['events'][1].update(rerun=True),
            'bad commit': lambda d: p1(d)['revisions'].update(head='abc'),
            'dangling duplicate': lambda d: [e.update(duplicate_of='e9999') for e in p1(d)['events'] if e['kind'] == 'verdict'][:1],
            'usage order': lambda d: t1(d)['usage'].reverse(),
        }
        ev = lambda d: p1(d)['events']
        # Review R2: relations the bench trusts. Review R3: times and sources consumers need.
        relational = {
            'repeated PR reference': lambda d: t1(d)['pull_requests'].append(4201),
            'missing reciprocal PR link': lambda d: t1(d).update(pull_requests=[]),
            'repeated run attempt': lambda d: ev(d).insert(2, dict(ev(d)[1], id='e900')),
            'missing fix round': lambda d: ev(d).pop(3),
            'repeated fix round': lambda d: ev(d).insert(10, dict(ev(d)[9], id='e901')),
            'wrong fix ordinal': lambda d: ev(d)[3].update(round=100),
            'verdict without time': lambda d: ev(d)[6].update(at=None, completeness='unknown'),
            'merge without time': lambda d: ev(d)[12].update(at=None, completeness='unknown'),
            'pr opened without time': lambda d: ev(d)[0].update(at=None, completeness='unknown'),
            'verdict without source': lambda d: ev(d)[2].update(source=None),
            'answered fix round without source': lambda d: ev(d)[3].update(source=None),
            # Self-review 2: one run's attempts split between two PRs.
            'one run on two pull requests': lambda d: next(p for p in d['pull_requests'] if p['number'] == 4202)[
                'events'].insert(1, ev(d).pop(5)),
        }
        cases.update(relational)
        for name, change in cases.items():
            with self.subTest(case=name):
                p, _ = self.consumer('check', broken(change))
                self.assertEqual(p.returncode, 1, (name, p.stderr))
                self.assertTrue(p.stderr.startswith('journey: '), p.stderr)
        for name in ('bench', 'cf4'):
            for case in ['invented kind', *relational]:
                with self.subTest(consumer=name, case=case):
                    p, _ = self.consumer(name, broken(cases[case]))
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertTrue(p.stderr.startswith('journey: '), p.stderr)

    def test_builder_start_records_and_prose(self):
        records = [
            ('launch-fleet: started, thread thr_synthbuild', True),
            ('launch-fleet: start checked, thread thr_synthbuild, branch room/4101-synthetic', True),
            ('launch-fleet: started', True),
            ('launch-fleet: start checked, branch room/4101-synthetic', True),
            ('launch-fleet: started is quoted here, not a record', False),
            ('launch-fleet: start checked, branch room/4101-synthetic is quoted here', False),
            ('launch-fleet: start checked, branch', False),
            ('Prose mentioning a record:\nlaunch-fleet: started', False),
        ]
        for record, expected in records:
            with self.subTest(record=record):
                w = world()
                v = json.loads(w[q(ISSUE, 4101)]['stdout'])
                v['data']['repository']['issue']['comments']['nodes'][0] = comment(
                    5101, 'issues/4101', '2030-01-01T12:00:00Z', record, '2030-01-01T12:10:00Z')
                w[q(ISSUE, 4101)] = answer(v)
                doc, root, _ = self.collected(data=w)
                t1 = self.ticket(doc, 4101)
                events = [('ticket', '2030-01-01T10:00:00Z', 'complete'),
                          ('ready', '2030-01-01T11:00:00Z', 'complete')]
                if expected:
                    events.append(('builder_start', '2030-01-01T12:00:00Z', 'edited'))
                self.assertEqual([(e['kind'], e['at'], e['completeness']) for e in t1['events']], events)
                self.assertEqual(t1['gaps'], [] if expected else ['no builder start record'])
                if 'thread thr_synthbuild' in record:
                    self.assertEqual(usage_of(t1)['claude/tokens'], ('known', 3500, []))
                self.assertNotIn('room/4101', (root / 'out' / 'journeys.json').read_text())

    def test_contract_names_the_vocabulary_and_schema(self):
        text = (HERE / 'journey-contract.md').read_text()
        self.assertIn('`closedwiz.journey.v1`', text)
        table = text.split("| Kind | The grill's words |", 1)[1].split('\n\n', 1)[0]
        rows = [line.split('|')[1].strip().strip('`') for line in table.splitlines() if line.startswith('| `')]
        self.assertEqual(rows, KINDS)



# --- TL2 (#2337): stage waits against the loaded limits ----------------------
#
# Synthetic world, worked by hand; base S0 = 2030-03-01T08:00:00Z, read at
# 12:00 (minute 240). Waits are seconds; the defaults below give, with the
# limits 10/5/5/30/15 minutes:
#
# Spec 4299 approved at -30. Blocker 4300 closed +30, its PR 4400 merged +30.
# Ticket 4301: ready +0, held +5..+60, so every start gate is open from +60.
# Builder start +70 (10 min: at the goal, not missed); a second start record
# +100 is folded. Builder questions +105 and +110 while needs-info is on
# (one interval, one fold); a ruling citing the first +121 (16: missed), then
# needs-info is removed. PR 4401 (pushes: G1 +105, G2 +181, deleted after the
# merge): CI on G1 green +120; review started G1 +126 (6: missed); CHANGES at
# G1 +150 asks for R1; G2 pushed +181 (31: missed), cited by "R1 fixed at";
# G2 green +191; re-check sent G2 +195 (4: not missed); APPROVE G2 +211;
# merged +216 (5: at the goal, not missed).
# Ticket 4302: start record before its ready label (Unknown); its only
# question is edited (Unknown). PR 4402 (pushes G3 +8, G5 +24, G4 +38): G3 green
# +20 with only a "review starting" claim (Unknown) and an approval at +23
# that G5 supersedes (stale); G5 green +35, never reviewed before G4 (stale);
# G4 green +50, current, but the ticket is held from +180 (gated).
# Ticket 4303: ready +235, no builder: pending, 5 minutes so far.
# Ticket 4304: ready-for-agent is on but no label event shows when (Unknown).

STAGE_LABELS = ('query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name)'
                '{issue(number:$number){number timelineItems(itemTypes:[LABELED_EVENT,UNLABELED_EVENT],first:100,'
                'after:$cursor){nodes{__typename ... on LabeledEvent{createdAt label{name}} ... on UnlabeledEvent'
                '{createdAt label{name}}} pageInfo{hasNextPage endCursor}}}}}')
GATES = ('query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name)'
         '{issue(number:$number){number labels(first:100){nodes{name} pageInfo{hasNextPage endCursor}} '
         'blockedBy(first:100,after:$cursor){nodes{number url state closedAt} pageInfo{hasNextPage endCursor}}}}}')
G1, G2, G3, G4, G5, GM = '1a' * 20, '2b' * 20, '3c' * 20, '4d' * 20, '5e' * 20, '6f' * 20
ZERO = '0' * 40
STAGE_TICKETS = (4301, 4302, 4303, 4304)
DEFAULT_WAITS = {'builder_start': 600, 'reviewer_start': 360, 'fix_after_changes': 1860, 'merge': 300,
                 'builder_question_answer': 960}
LIMITS = {'builder_start': 10, 'reviewer_start': 5, 'merge': 5, 'fix_after_changes': 30, 'builder_question_answer': 15}


def at(minutes, seconds=0):
    from datetime import datetime, timedelta, timezone
    t = datetime(2030, 3, 1, 8, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes, seconds=seconds)
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


READ_AT = at(240)


def stage_run(rid, head, branch, started, done, conclusion='success'):
    return {'id': rid, 'run_attempt': 1, 'head_sha': head, 'head_branch': branch, 'event': 'pull_request',
            'status': 'completed', 'conclusion': conclusion, 'created_at': started, 'run_started_at': started,
            'updated_at': done, 'html_url': f'{WEB}/actions/runs/{rid}', 'pull_requests': []}


def timeline(n, events, more=False, cursor=None):
    return {'data': {'repository': {'issue': {'number': n, 'timelineItems': conn(
        [{'__typename': 'LabeledEvent' if add else 'UnlabeledEvent', 'createdAt': t, 'label': {'name': name}}
         for t, name, add in events], more, cursor)}}}}


def gates(n, current, blockers, more=False, cursor=None):
    return {'data': {'repository': {'issue': {'number': n, 'labels': conn([{'name': x} for x in current]),
                                              'blockedBy': conn([{'number': b, 'url': f'{WEB}/issues/{b}', 'state': s,
                                                                  'closedAt': c} for b, s, c in blockers], more, cursor)}}}}


def activity_path(branch):
    return rest(f'{BASE}/activity?ref=refs%2Fheads%2F{branch.replace("/", "%2F")}&per_page=100')


def activity(branch, pushes):
    """pushes: (time, before, after); newest first, as GitHub lists them."""
    rows = [{'id': 70000 + i, 'before': b, 'after': a, 'ref': f'refs/heads/{branch}', 'timestamp': t,
             'activity_type': 'push'} for i, (t, b, a) in enumerate(pushes)]
    return answer(rows[::-1])


def verdict(word, head, at_, cid, pr, review='Full review by Codex, Sol 6.1, High.'):
    body = f'VERDICT: {word} at {head}\n\n{review}\n\n- **R1 [high]** `a.py:1` (Spec) A guard. Fix: refuse.'
    return comment(cid, f'pull/{pr}', at_, body)


# plan-graph's revision.sh reads (its literal gh arguments) and the revision
# text it must print for this world, written out by hand; its SHA-256 is the
# fingerprint the approval records.
META = ('"#\\(.number)\\t\\([.blockedBy.nodes[].number] | sort | map("#" + tostring) | join(" ") | '
        'if . == "" then "none" else . end)\\t\\(.title)"')


def gh_args(*args):
    return json.dumps(list(args))


def revision_reads(titles=None):
    titles = {**{n: 'Synthetic ticket' for n in (4301, 4302, 4303, 4304)}, **(titles or {})}
    out = {gh_args('issue', 'view', '4299', '--json', 'subIssues', '--jq',
                   '.subIssues.totalCount, (.subIssues.nodes[].number)'): {'stdout': '4\n4301\n4302\n4303\n4304\n'},
           gh_args('issue', 'view', '4299', '--json', 'body', '--jq', '.body'): {'stdout': 'Synthetic spec.\n'}}
    for n, title in titles.items():
        blockers = '#4300' if n == 4301 else 'none'
        out[gh_args('issue', 'view', str(n), '--json', 'number,title,blockedBy', '--jq', META)] = {
            'stdout': f'#{n}\t{blockers}\t{title}\n'}
        out[gh_args('issue', 'view', str(n), '--json', 'body', '--jq', '.body')] = {'stdout': 'Synthetic ticket.\n'}
    return out


def fingerprint():
    import hashlib
    h = lambda text: hashlib.sha256(text.encode()).hexdigest()
    spec_body, ticket_body = h('Synthetic spec.\n'), h('Synthetic ticket.\n')
    lines = ['plan-graph revision v2', f'spec #4299 body sha256 {spec_body}']
    for n in (4301, 4302, 4303, 4304):
        blockers = '#4300' if n == 4301 else 'none'
        lines.append(f'ticket #{n} blocked-by {blockers} body sha256 {ticket_body} title Synthetic ticket')
    return h('\n'.join(lines) + '\n')


def stage_world(waits=None):
    w = dict(DEFAULT_WAITS, **(waits or {}))
    b, r, f, m, qa = (w[k] for k in ('builder_start', 'reviewer_start', 'fix_after_changes', 'merge',
                                     'builder_question_answer'))
    fix = 150 * 60 + f                 # seconds from S0: G2's push and its CI start
    green2, approve = fix + 600, fix + 1800
    merged = at(0, approve + m)
    q1 = f'{WEB}/issues/4301#issuecomment-6102'
    spec = issue(4299, at(-200), 'Synthetic spec.', None, [
        comment(6001, 'issues/4299', at(-30), '**Plan graph approved by Owner, 2030-03-01, revision 1:** yes\n\n'
                f'| #4301 | #4302 | #4303 | #4304 |\n\nFingerprint: `{fingerprint()}`')])
    t1 = issue(4301, at(-120), 'Synthetic ticket.', 4299, sorted([
        comment(6101, 'issues/4301', at(60, b), 'launch-fleet: started'),
        comment(6102, 'issues/4301', at(105), 'Builder question: which form?'),
        comment(6103, 'issues/4301', at(110), 'Builder question: and the second?'),
        comment(6104, 'issues/4301', at(105, qa), f'Orchestrator ruling on {q1}: use the first form.'),
        comment(6105, 'issues/4301', at(90, b), 'launch-fleet: started')], key=lambda c: c['createdAt']), merged)
    p1 = pull(4401, at(100), merged, 'room/4301-synthetic', G2, GM, 'Closes #4301', [
        comment(6201, 'pull/4401', at(120, r), f'launch-fleet: review started {G1}'),
        verdict('CHANGES', G1, at(150), 6202, 4401),
        comment(6203, 'pull/4401', at(1, fix), f'R1 fixed at {G2[:7]}: the guard.'),
        comment(6204, 'pull/4401', at(4, green2), f'launch-fleet: re-check sent {G2}'),
        verdict('APPROVE', G2, at(0, approve), 6205, 4401, 'Re-check 1 of R1 by Codex, Sol 6.1, High.')])
    t2 = issue(4302, at(-120), 'Synthetic ticket.', 4299, [
        comment(6301, 'issues/4302', at(-60), 'launch-fleet: started'),
        comment(6302, 'issues/4302', at(150), 'Builder question: edited later?', at(155))])
    p2 = pull(4402, at(5), None, 'room/4302-synthetic', G4, None, 'Closes #4302', [
        comment(6401, 'pull/4402', at(22), f'launch-fleet: review starting {G3}'),
        verdict('APPROVE', G3, at(23), 6402, 4402)])
    t3 = issue(4303, at(-120), 'Synthetic ticket.', 4299, [])
    t4 = issue(4304, at(-120), 'Synthetic ticket.', 4299,
               [comment(6501, 'issues/4304', at(30), 'launch-fleet: started')])
    runs1 = [stage_run(9001, G1, 'room/4301-synthetic', at(110), at(120)),
             stage_run(9002, G2, 'room/4301-synthetic', at(0, fix), at(0, green2))]
    runs2 = [stage_run(9003, G3, 'room/4302-synthetic', at(10), at(20)),
             stage_run(9004, G4, 'room/4302-synthetic', at(40), at(50)),
             stage_run(9005, G5, 'room/4302-synthetic', at(25), at(35))]
    prs = [inventory(4401, merged, [4301]), inventory(4402, None, [4302]), inventory(4400, at(30), [4300])]
    return {
        q(PRS): answer({'data': {'repository': {'pullRequests': conn(prs)}}}),
        q(ISSUE, 4299): answer(spec), **revision_reads(),
        q(ISSUE, 4301): answer(t1), q(ISSUE, 4302): answer(t2), q(ISSUE, 4303): answer(t3), q(ISSUE, 4304): answer(t4),
        q(LABELS, 4301): answer(labels([(at(0), 'ready-for-agent'), (at(5), 'held'), (at(105), 'needs-info')])),
        q(LABELS, 4302): answer(labels([(at(0), 'ready-for-agent'), (at(180), 'held')])),
        q(LABELS, 4303): answer(labels([(at(235), 'ready-for-agent')])),
        q(LABELS, 4304): answer(labels([])),
        q(PULL, 4401): answer(p1), q(PULL, 4402): answer(p2),
        rest(runs_path('room%2F4301-synthetic', 1)): answer({'total_count': 2, 'workflow_runs': runs1}),
        rest(runs_path('room%2F4302-synthetic', 1)): answer({'total_count': 3, 'workflow_runs': runs2}),
        activity_path('room/4301-synthetic'): activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(0, fix), G1, G2), (at(1, approve + m), G2, ZERO)]),
        activity_path('room/4302-synthetic'): activity('room/4302-synthetic', [
            (at(8), ZERO, G3), (at(24), G3, G5), (at(38), G5, G4)]),
        q(STAGE_LABELS, 4301): answer(timeline(4301, [
            (at(0), 'ready-for-agent', True), (at(5), 'held', True), (at(60), 'held', False),
            (at(105), 'needs-info', True), (at(105, qa + 30), 'needs-info', False)])),
        q(STAGE_LABELS, 4302): answer(timeline(4302, [(at(0), 'ready-for-agent', True), (at(180), 'held', True)])),
        q(STAGE_LABELS, 4303): answer(timeline(4303, [(at(235), 'ready-for-agent', True)])),
        q(STAGE_LABELS, 4304): answer(timeline(4304, [])),
        q(GATES, 4301): answer(gates(4301, ['ready-for-agent'], [(4300, 'CLOSED', at(30))])),
        q(GATES, 4302): answer(gates(4302, ['ready-for-agent', 'held'], [])),
        q(GATES, 4303): answer(gates(4303, ['ready-for-agent'], [])),
        q(GATES, 4304): answer(gates(4304, ['ready-for-agent'], []))}


def edit_json(data, key, change):
    value = json.loads(data[key]['stdout'])
    change(value)
    data[key] = answer(value)


def pr_comments(value):
    return value['data']['repository']['pullRequest']['comments']['nodes']


def issue_comments(value):
    return value['data']['repository']['issue']['comments']['nodes']


K = {'b1': 'builder_start:t4301', 'b2': 'builder_start:t4302', 'b3': 'builder_start:t4303', 'b4': 'builder_start:t4304',
     'q1': 'builder_question_answer:t4301:c6102', 'q2': 'builder_question_answer:t4302:c6302',
     'r1': f'reviewer_start:p4401:{G1}:{at(120)}', 'r2': f'reviewer_start:p4401:{G2}:{at(191)}',
     'f1': f'fix_after_changes:p4401:{G1}:c6202', 'm1': f'merge:p4401:{G2}:c6205:{at(211)}',
     'r3': f'reviewer_start:p4402:{G3}:{at(20)}', 'r5': f'reviewer_start:p4402:{G5}:{at(35)}',
     'r4': f'reviewer_start:p4402:{G4}:{at(50)}', 'm3': f'merge:p4402:{G3}:c6402:{at(23)}'}


class StageWaits(unittest.TestCase):
    """TL2 proofs: each stage wait sourced to GitHub records, honest Unknowns."""
    cli, collected, consumer = Journey.cli, Journey.collected, Journey.consumer

    def staged(self, data=None, as_of=READ_AT, extra=()):
        p, doc, root, calls = self.cli('collect', '--stage-waits', '--as-of', as_of, *extra,
                                       data=stage_world() if data is None else data, usage=[], tickets=STAGE_TICKETS)
        side = root / 'out' / 'stage-waits.json'
        return p, doc, (json.loads(side.read_text()) if side.exists() else None), root, calls

    def bench_stages(self, root, settings=None, side=None):
        argv = [sys.executable, '-I', str(SCRIPT), 'bench', str(root / 'out' / 'journeys.json'),
                '--stage-waits', str(side or root / 'out' / 'stage-waits.json')]
        if settings is not None:
            argv += ['--settings', str(settings)]
        p = subprocess.run(argv, text=True, capture_output=True, timeout=30)
        return p, (json.loads(p.stdout) if p.returncode == 0 else None)

    def waits(self, data=None, settings=None, as_of=READ_AT):
        p, _, _, root, _ = self.staged(data, as_of)
        self.assertEqual(p.returncode, 0, p.stderr)
        b, out = self.bench_stages(root, settings)
        self.assertEqual(b.returncode, 0, b.stderr)
        return out['stage_waits'], {w['key']: w for w in out['stage_waits']['waits']}

    def outcome(self, w, key):
        return w[key]['result'], w[key]['wait_minutes'], w[key]['gaps']

    # TL2 claim 1: all five stages benchmarked against the loaded settings with
    # sources and denominators. Bug caught: a stage silently missing, or a
    # wait measured from the ready label instead of the last gate to open.
    def test_all_five_stage_waits_against_loaded_limits(self):
        bench, w = self.waits()
        self.assertEqual(bench['settings'], {'schema': 'closedwiz.factory-limits.v1', 'minutes': LIMITS})
        self.assertEqual(bench['authority'], 'none')
        expected = {
            'b1': ('not missed', 10.0, []), 'b2': ('unknown', None, ['start record outside its gate']),
            'b3': ('pending', 5.0, []), 'b4': ('unknown', None, ['label history incomplete']),
            'q1': ('missed', 16.0, []), 'q2': ('unknown', None, ['edited record']),
            'r1': ('missed', 6.0, []), 'r2': ('not missed', 4.0, []), 'f1': ('missed', 31.0, []),
            'm1': ('not missed', 5.0, []), 'r3': ('unknown', None, ['reviewer start unconfirmed']),
            'r5': ('stale', None, ['no longer current']), 'r4': ('gated', None, ['held']),
            'm3': ('stale', None, ['no longer current'])}
        self.assertEqual({k: self.outcome(w, v) for k, v in K.items()}, expected)
        self.assertEqual(len(w), len(K))
        self.assertEqual(w[K['b1']]['folded'], 1)
        self.assertEqual(w[K['q1']]['folded'], 1)
        self.assertEqual(w[K['m1']]['tickets'], [4301])
        src = bench['sources']
        # The last gate to open (the hold's removal) is the ticket; the end is the start record.
        self.assertEqual(src[w[K['b1']]['start']], f'{WEB}/issues/4301')
        self.assertEqual(src[w[K['b1']]['end']], f'{WEB}/issues/4301#issuecomment-6101')
        self.assertEqual(src[w[K['r1']]['start']], f'{WEB}/actions/runs/9001')
        self.assertEqual(src[w[K['f1']]['end']], f'{WEB}/commit/{G2}')
        self.assertEqual([src[s] for s in w[K['f1']]['support']], [f'{WEB}/pull/4401#issuecomment-6203'])
        self.assertEqual(src[w[K['m1']]['start']], f'{WEB}/pull/4401#issuecomment-6205')
        self.assertEqual(src[w[K['m1']]['end']], f'{WEB}/pull/4401')
        self.assertEqual(src[w[K['q1']]['end']], f'{WEB}/issues/4301#issuecomment-6104')
        rows = {s['stage']: s for s in bench['stages']}
        self.assertEqual([s['stage'] for s in bench['stages']], list(LIMITS))
        zero = {'missed': 0, 'not missed': 0, 'pending': 0, 'unknown': 0, 'gated': 0, 'stale': 0}
        self.assertEqual(rows['builder_start'], {'stage': 'builder_start', 'limit_minutes': 10, 'intervals': 4,
                                                 'measured': 2, 'results': {**zero, 'not missed': 1, 'pending': 1,
                                                                            'unknown': 2}})
        self.assertEqual(rows['reviewer_start']['results'], {**zero, 'missed': 1, 'not missed': 1, 'unknown': 1,
                                                             'stale': 1, 'gated': 1})
        self.assertEqual(rows['reviewer_start']['measured'], 2)
        self.assertEqual(rows['merge']['results'], {**zero, 'not missed': 1, 'stale': 1})
        self.assertEqual(rows['fix_after_changes']['results'], {**zero, 'missed': 1})
        self.assertEqual(rows['builder_question_answer']['results'], {**zero, 'missed': 1, 'unknown': 1})
        self.assertEqual(sorted(bench['misses']), sorted([K['q1'], K['r1'], K['f1']]))

    # TL2 claim 1, threshold edges: a minute below, exactly at and one second
    # above each goal.
    def test_threshold_edges_for_every_stage(self):
        for name, delta, expected in [('below', -60, 'not missed'), ('at', 0, 'not missed'), ('above', 1, 'missed')]:
            with self.subTest(edge=name):
                waits = {k: v * 60 + delta for k, v in LIMITS.items()}
                _, w = self.waits(stage_world(waits))
                rows = {'builder_start': w[K['b1']], 'builder_question_answer': w[K['q1']],
                        'reviewer_start': next(v for k, v in w.items() if k.startswith(f'reviewer_start:p4401:{G1}')),
                        'fix_after_changes': w[K['f1']], 'merge': next(v for k, v in w.items() if k.startswith('merge:p4401'))}
                for stage, row in rows.items():
                    self.assertEqual(row['result'], expected, stage)
                    self.assertEqual(row['wait_minutes'], round((LIMITS[stage] * 60 + delta) / 60, 2), stage)

    # Settings are read per calculation: an edited goal changes the next result;
    # an invalid file refuses rather than measuring against no goal.
    def test_edited_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'limits.conf'
            path.write_text('builder_start=9\nreviewer_start=5\nmerge=5\nfix_after_changes=30\n'
                            'builder_question_answer=15\n')
            bench, w = self.waits(settings=path)
            self.assertEqual(bench['settings']['minutes']['builder_start'], 9)
            self.assertEqual((w[K['b1']]['result'], w[K['b1']]['limit_minutes']), ('missed', 9))
            path.write_text('builder_start=9\n')
            p, _, _, root, _ = self.staged()
            b, out = self.bench_stages(root, path)
            self.assertEqual(b.returncode, 1)
            self.assertEqual(b.stdout, '')

    # Virtual time: an open interval is pending below its goal and a single
    # ongoing miss above it; a read time before the records refuses.
    def test_open_intervals_in_virtual_time(self):
        _, w = self.waits(as_of=at(250))
        self.assertEqual(self.outcome(w, K['b3']), ('missed', 15.0, []))
        self.assertIsNone(w[K['b3']]['end'])
        p, _, side, root, _ = self.staged(as_of=at(200))
        self.assertEqual(p.returncode, 1)
        self.assertIsNone(side)
        self.assertFalse((root / 'out').exists())

    # R1: the builder clock starts only when every start gate is evidenced: a
    # plan approval and a verified merge for each blocker, not just labels.
    def test_builder_gate_needs_approval_and_blocker_merges(self):
        data = stage_world()
        edit_json(data, q(ISSUE, 4299), lambda v: issue_comments(v).clear())
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['no plan approval']))
        self.assertEqual(self.outcome(w, K['b3']), ('unknown', None, ['no plan approval']))
        data = stage_world()
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'].pop())
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['blocker merge unverified']))
        data = stage_world()  # The blocker's merge at +65 is the last gate: the start at +70 waited 5 minutes.
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'][-1].update(
            mergedAt=at(65), closedAt=at(65)))
        bench, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b1']), ('not missed', 5.0, []))
        self.assertEqual(bench['sources'][w[K['b1']]['start']], f'{WEB}/pull/4400')
        data = stage_world()  # An open blocker keeps the gate shut: no stage yet, and no guess.
        data[q(GATES, 4303)] = answer(gates(4303, ['ready-for-agent'], [(4300, 'OPEN', None)]))
        _, w = self.waits(data)
        self.assertNotIn(K['b3'], w)

    # R10: finished work without a start record, and a held ready ticket, stay
    # in the denominators as Unknown and gated rather than vanishing.
    def test_missing_builder_starts_stay_in_the_denominator(self):
        data = stage_world()
        edit_json(data, q(ISSUE, 4301), lambda v: issue_comments(v).__setitem__(
            slice(None), [c for c in issue_comments(v) if c['databaseId'] not in (6101, 6105)]))
        data[q(STAGE_LABELS, 4303)] = answer(timeline(4303, [(at(235), 'ready-for-agent', True),
                                                             (at(236), 'held', True)]))
        data[q(GATES, 4303)] = answer(gates(4303, ['ready-for-agent', 'held'], []))
        bench, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['no end record']))
        self.assertEqual(self.outcome(w, K['b3']), ('gated', None, ['held']))
        self.assertEqual(bench['stages'][0]['intervals'], 4)

    # R2: eligibility needs the head's push record and its current CI state; a
    # later red run ends it, and a head change with no push evidence is Unknown.
    def test_reviewer_and_merge_need_current_green_heads(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: v['data']['repository']['pullRequest'].update(
            mergedAt=None, closedAt=None, mergeCommit=None))
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'][0].update(
            mergedAt=None, closedAt=None))
        edit_json(data, q(ISSUE, 4301), lambda v: v['data']['repository']['issue'].update(closedAt=None))
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(181), G1, G2)])
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['m1']), ('missed', 29.0, []))
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].append(stage_run(9006, G2, 'room/4301-synthetic', at(212), at(220), 'failure')),
            v.update(total_count=3)))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['m1']), ('stale', None, ['no longer current']))
        data = stage_world()  # Pushes unreadable: no head can be shown current.
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [(at(181), G1, G2)])
        _, w = self.waits(data)
        heads = {k: v for k, v in w.items() if k.startswith(('reviewer_start:p4401', 'merge:p4401', 'fix'))}
        self.assertEqual({v['result'] for v in heads.values()}, {'unknown'})
        self.assertEqual({tuple(v['gaps']) for v in heads.values()}, {('head history incomplete',)})
        data = stage_world()  # G2 was pushed before the review record: the record is outside G1's gate.
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(124), G1, G2), (at(222), G2, ZERO)])
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, f'reviewer_start:p4401:{G1}:-'),
                         ('unknown', None, ['start record outside its gate']))
        self.assertEqual(self.outcome(w, f'reviewer_start:p4401:{G1}:{at(120)}'),
                         ('stale', None, ['no longer current']))

    # R3: a later CHANGES on the same head revokes an approval; only a new
    # approval opens another merge wait.
    def test_changes_revokes_an_approval(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: (v['data']['repository']['pullRequest'].update(
            mergedAt=None, closedAt=None, mergeCommit=None), pr_comments(v).append(
            verdict('CHANGES', G2, at(212), 6206, 4401, 'Re-check 2 of R1 by Codex, Sol 6.1, High.'))))
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'][0].update(
            mergedAt=None, closedAt=None))
        edit_json(data, q(ISSUE, 4301), lambda v: v['data']['repository']['issue'].update(closedAt=None))
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(181), G1, G2)])
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['m1']), ('stale', None, ['no longer current']))
        self.assertEqual(w[f'fix_after_changes:p4401:{G2}:c6206']['result'], 'pending')
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v).append(
            verdict('APPROVE', G2, at(230), 6207, 4401, 'Re-check 3 of R1 by Codex, Sol 6.1, High.')))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, f'merge:p4401:{G2}:c6207:{at(230)}'), ('missed', 10.0, []))
        self.assertEqual(self.outcome(w, K['m1']), ('stale', None, ['no longer current']))

    # R4: an edited start record says the start happened between its creation
    # and its last edit; only a result both ends agree on is reported.
    def test_edited_start_records_are_bounded(self):
        for b, edited, expected in [(480, 60, 'not missed'), (600, 60, 'unknown'), (601, 60, 'missed')]:
            with self.subTest(start=b):
                data = stage_world({'builder_start': b})
                edit_json(data, q(ISSUE, 4301), lambda v: issue_comments(v)[0].update(updatedAt=at(60, b + edited)))
                _, w = self.waits(data)
                self.assertEqual(w[K['b1']]['result'], expected)
                self.assertIsNone(w[K['b1']]['wait_minutes'])
                self.assertEqual(w[K['b1']]['wait_range_minutes'], [round(b / 60, 2), round((b + edited) / 60, 2)])
                if expected == 'unknown':
                    self.assertEqual(w[K['b1']]['gaps'], ['edited record'])

    # R5: only an unedited answer citing a finding this round asks to fix, at a
    # head pushed after the verdict, ends the fix wait.
    def test_fix_needs_a_bound_answer(self):
        for name, body, updated, expected in [
                ('other finding', f'R99 fixed at {G2[:7]}: elsewhere.', None, ('pending', 'unknown')),
                ('edited answer', f'R1 fixed at {G2[:7]}: the guard.', at(230), ('unknown', 'unknown')),
                ('old head', f'R1 fixed at {G1[:7]}: nothing new.', None, ('pending', 'unknown'))]:
            with self.subTest(name=name):
                data = stage_world()
                edit_json(data, q(PULL, 4401), lambda v: pr_comments(v)[2].update(body=body, updatedAt=updated or
                                                                                  pr_comments(v)[2]['updatedAt']))
                _, w = self.waits(data)
                self.assertEqual(w[K['f1']]['result'], expected[1], name)
                self.assertIsNone(w[K['f1']]['end'])

    # R6: a question ends only at a disposition that cites it, before needs-info
    # is removed; an acknowledgement or a ruling on something else does not.
    def test_question_needs_a_linked_disposition(self):
        for name, body in [('acknowledgement', 'Orchestrator ruling: received; still investigating.'),
                           ('other question', f'Orchestrator ruling on {WEB}/issues/4301#issuecomment-6999: no.')]:
            with self.subTest(name=name):
                data = stage_world()
                edit_json(data, q(ISSUE, 4301), lambda v: next(
                    c for c in issue_comments(v) if c['databaseId'] == 6104).update(body=body))
                _, w = self.waits(data)
                self.assertEqual(self.outcome(w, K['q1']), ('unknown', None, ['no linked disposition']))
        data = stage_world()  # Still waiting: needs-info is on and nothing cites the question.
        edit_json(data, q(ISSUE, 4301), lambda v: (
            v['data']['repository']['issue'].update(closedAt=None),
            issue_comments(v).__setitem__(slice(None), [c for c in issue_comments(v) if c['databaseId'] != 6104])))
        data[q(STAGE_LABELS, 4301)] = answer(timeline(4301, [
            (at(0), 'ready-for-agent', True), (at(5), 'held', True), (at(60), 'held', False),
            (at(105), 'needs-info', True)]))
        data[q(GATES, 4301)] = answer(gates(4301, ['ready-for-agent', 'needs-info'], [(4300, 'CLOSED', at(30))]))
        edit_json(data, q(PULL, 4401), lambda v: v['data']['repository']['pullRequest'].update(
            mergedAt=None, closedAt=None, mergeCommit=None))
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'][0].update(
            mergedAt=None, closedAt=None))
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(181), G1, G2)])
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['q1']), ('missed', 135.0, []))

    # R9: a later confirmed start resolves an earlier claim for the same head.
    def test_claim_then_confirmed_start(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v).insert(0, comment(
            6200, 'pull/4401', at(121), f'launch-fleet: review starting {G1}')))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['r1']), ('missed', 6.0, []))
        self.assertEqual(w[K['r1']]['folded'], 1)

    # R8: keys come from immutable evidence: history added later never renames
    # an interval or its miss.
    def test_keys_survive_added_history(self):
        _, before = self.waits()
        data = stage_world()
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].insert(0, stage_run(9000, G1, 'room/4301-synthetic', at(106), at(108), 'failure')),
            v.update(total_count=3)))
        _, after = self.waits(data)
        self.assertEqual({k: v['result'] for k, v in before.items()}, {k: v['result'] for k, v in after.items()})

    # Round 2, R1: only an unedited approval that names the ticket opens its gate.
    def test_approval_must_be_unedited_and_name_the_ticket(self):
        for name, change in [
                ('edited', lambda c: c.update(updatedAt=at(200))),
                ('other tickets', lambda c: c.update(body='**Plan graph approved by Owner, revision 1:** | #4399 |'))]:
            with self.subTest(name=name):
                data = stage_world()
                edit_json(data, q(ISSUE, 4299), lambda v: change(issue_comments(v)[0]))
                _, w = self.waits(data)
                self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['no plan approval']))

    # Round 3 (diagnosis), R1: only the spec's latest approval counts, and only
    # while its fingerprint matches plan-graph's current revision.
    def test_latest_approval_with_current_fingerprint(self):
        for name, change, gap in [
                ('plan changed since', lambda d: d.update(revision_reads({4303: 'Retitled ticket'})), 'approval not current'),
                ('no fingerprint', lambda d: edit_json(d, q(ISSUE, 4299), lambda v: issue_comments(v)[0].update(
                    body='**Plan graph approved by Owner, revision 1:** | #4301 | #4302 | #4303 | #4304 |')),
                 'approval not current'),
                ('a later approval is the latest', lambda d: edit_json(d, q(ISSUE, 4299), lambda v: issue_comments(v).append(
                    comment(6002, 'issues/4299', at(-10), '**Plan graph approved by Owner, revision 2:** | #4301 |\n\n'
                            'Fingerprint: `' + '0' * 64 + '`'))), 'approval not current'),
                ('revision unreadable', lambda d: d.pop(gh_args('issue', 'view', '4299', '--json', 'body', '--jq', '.body')),
                 'approval not current')]:
            with self.subTest(name=name):
                data = stage_world()
                change(data)
                _, w = self.waits(data)
                self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, [gap]))

    # Round 2, R2: a late success of a superseded attempt never reopens green
    # while the latest attempt on that head is red.
    def test_superseded_attempt_success_does_not_reopen_green(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: v['data']['repository']['pullRequest'].update(
            mergedAt=None, closedAt=None, mergeCommit=None))
        edit_json(data, q(PRS), lambda v: v['data']['repository']['pullRequests']['nodes'][0].update(
            mergedAt=None, closedAt=None))
        edit_json(data, q(ISSUE, 4301), lambda v: v['data']['repository']['issue'].update(closedAt=None))
        data[activity_path('room/4301-synthetic')] = activity('room/4301-synthetic', [
            (at(105), ZERO, G1), (at(181), G1, G2)])
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].append(stage_run(9006, G2, 'room/4301-synthetic', at(195), at(213))),
            v['workflow_runs'].append(stage_run(9007, G2, 'room/4301-synthetic', at(200), at(210), 'failure')),
            v.update(total_count=4)))
        _, w = self.waits(data)
        merges = {k: self.outcome(w, k) for k in w if k.startswith('merge:p4401')}
        self.assertEqual(merges, {f'merge:p4401:{G2}:c6205:-': ('stale', None, ['no longer current'])})

    # Round 2, R4: an edited end must lie wholly inside the window it ends.
    def test_edited_end_must_stay_inside_its_window(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v)[0].update(updatedAt=at(183)))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['r1']), ('unknown', None, ['edited record']))
        data = stage_world()  # The builder claim's last edit falls after needs-info shut the gate at +105.
        edit_json(data, q(ISSUE, 4301), lambda v: issue_comments(v)[0].update(updatedAt=at(106)))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['edited record']))

    # Round 2, R6: a linked acknowledgement is no disposition; only a recorded
    # `Disposition: answered` line ends the wait.
    def test_linked_acknowledgement_is_no_answer(self):
        link = f'{WEB}/issues/4301#issuecomment-6102'
        for body in [f'Orchestrator ruling on {link}: received; still investigating.',
                     # Round 3 (diagnosis), R6: the reviewer's reproduction, a deferral with the status line.
                     f'Orchestrator ruling on {link}: still investigating, no decision yet.\nDisposition: answered',
                     f'Orchestrator ruling on {link}: deferred to the owner.',
                     f'Orchestrator ruling on {link}: Pending the next revision.',
                     f'Orchestrator ruling on {link}:\nDisposition: answered']:
            with self.subTest(body=body):
                data = stage_world()
                edit_json(data, q(ISSUE, 4301), lambda v: next(
                    c for c in issue_comments(v) if c['databaseId'] == 6104).update(body=body))
                _, w = self.waits(data)
                self.assertEqual(self.outcome(w, K['q1']), ('unknown', None, ['no linked disposition']))

    # Round 2, R9: a claim in an earlier window keeps its uncertainty without
    # hiding a confirmed start in a later window of the same head.
    def test_claim_window_then_confirmed_window(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v).insert(0, comment(
            6200, 'pull/4401', at(121), f'launch-fleet: review starting {G1}')))
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].append(stage_run(9008, G1, 'room/4301-synthetic', at(122), at(124))),
            v.update(total_count=3)))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['r1']), ('unknown', None, ['reviewer start unconfirmed']))
        self.assertEqual(self.outcome(w, f'reviewer_start:p4401:{G1}:{at(124)}'), ('not missed', 2.0, []))

    # Round 3, R11: two runs starting in the same recorded second can't be
    # ordered; neither may open green, whichever has the higher id.
    def test_same_second_runs_open_no_green(self):
        results = []
        for red, green in [(9010, 9011), (9011, 9010)]:
            data = stage_world()
            edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
                v['workflow_runs'].append(stage_run(red, G1, 'room/4301-synthetic', at(122), at(123), 'failure')),
                v['workflow_runs'].append(stage_run(green, G1, 'room/4301-synthetic', at(122), at(124))),
                v.update(total_count=4)))
            _, w = self.waits(data)
            results.append({k: self.outcome(w, k) for k in w if k.startswith(f'reviewer_start:p4401:{G1}')})
        self.assertEqual(results[0], results[1])
        self.assertNotIn(f'reviewer_start:p4401:{G1}:{at(124)}', results[0])
        self.assertEqual(results[0][f'reviewer_start:p4401:{G1}:-'], ('unknown', None, ['start record outside its gate']))

    # Round 4, R11: a head whose only CI is two same-second runs stays in the
    # reviewer denominator as Unknown, not dropped as never green.
    def test_tied_only_ci_history_is_unknown(self):
        data = stage_world()
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].__setitem__(0, stage_run(9001, G1, 'room/4301-synthetic', at(110), at(115), 'failure')),
            v['workflow_runs'].append(stage_run(9012, G1, 'room/4301-synthetic', at(110), at(120))),
            v.update(total_count=3)))
        _, w = self.waits(data)
        rows = {k: self.outcome(w, k) for k in w if k.startswith(f'reviewer_start:p4401:{G1}')}
        self.assertEqual(rows, {f'reviewer_start:p4401:{G1}:-': ('unknown', None, ['ci order unknown'])})

    # Round 3, R12: a confirmation while CI was pending stays Unknown without
    # hiding a later confirmation inside the recovered window.
    def test_outside_confirmation_then_window_confirmation(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v).insert(0, comment(
            6199, 'pull/4401', at(123), f'launch-fleet: review started {G1}')))
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)), lambda v: (
            v['workflow_runs'].append(stage_run(9008, G1, 'room/4301-synthetic', at(122), at(124))),
            v.update(total_count=3)))
        _, w = self.waits(data)
        rows = {k: self.outcome(w, k) for k in w if k.startswith(f'reviewer_start:p4401:{G1}')}
        self.assertEqual(rows, {
            K['r1']: ('stale', None, ['no longer current']),
            f'reviewer_start:p4401:{G1}:{at(124)}': ('not missed', 2.0, []),
            f'reviewer_start:p4401:{G1}:-': ('unknown', None, ['start record outside its gate'])})

    # Round 2, R10: the hold procedure removes ready-for-agent as it adds held;
    # that held wait stays in the denominator as gated.
    def test_hold_that_removes_ready_is_gated(self):
        data = stage_world()
        data[q(STAGE_LABELS, 4303)] = answer(timeline(4303, [
            (at(235), 'ready-for-agent', True), (at(236), 'held', True), (at(236), 'ready-for-agent', False)]))
        data[q(GATES, 4303)] = answer(gates(4303, ['held'], []))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, K['b3']), ('gated', None, ['held']))

    # Overlapping and duplicate records, and a CHANGES round answered only by a
    # dispute, never invent an elapsed time or a second miss.
    def test_overlaps_duplicates_and_disputes(self):
        data = stage_world()
        edit_json(data, q(PULL, 4401), lambda v: (
            pr_comments(v)[2].update(body='R1 disputed: it is behaviour.'),
            pr_comments(v).insert(2, verdict('CHANGES', G1, at(160), 6206, 4401,
                                             'Re-check 1 of R1 by Codex, Sol 6.1, High.'))))
        _, w = self.waits(data)
        self.assertEqual([k for k in w if k.startswith('fix_after_changes')], [K['f1']])
        self.assertEqual(self.outcome(w, K['f1']), ('unknown', None, ['disputed without fix']))
        self.assertEqual(w[K['f1']]['folded'], 1)
        data = stage_world()  # The identical page item twice is one record.
        edit_json(data, q(STAGE_LABELS, 4301), lambda v: v['data']['repository']['issue']['timelineItems'][
            'nodes'].insert(1, copy.deepcopy(v['data']['repository']['issue']['timelineItems']['nodes'][0])))
        _, again = self.waits(data)
        self.assertEqual(again[K['b1']]['result'], 'not missed')

    # Missing or contradictory endpoints stay Unknown with the named gap.
    def test_missing_and_contradictory_endpoints(self):
        data = stage_world()
        edit_json(data, rest(runs_path('room%2F4301-synthetic', 1)),
                  lambda v: v['workflow_runs'][1].update(updated_at=None))  # G2's completion is unreadable
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, f'reviewer_start:p4401:{G2}:-'), ('unknown', None, ['no green completion time']))
        self.assertEqual(self.outcome(w, f'merge:p4401:{G2}:c6205:-'), ('unknown', None, ['no green completion time']))
        data = stage_world()  # The approval comes after the merge.
        edit_json(data, q(PULL, 4401), lambda v: pr_comments(v).__setitem__(
            -1, verdict('APPROVE', G2, at(239), 6205, 4401, 'Re-check 1 of R1 by Codex, Sol 6.1, High.')))
        edit_json(data, q(ISSUE, 4301), lambda v: issue_comments(v).__setitem__(slice(None), [
            c for c in issue_comments(v) if c['databaseId'] != 6104]))
        _, w = self.waits(data)
        self.assertEqual(self.outcome(w, f'merge:p4401:{G2}:c6205:-'), ('stale', None, ['no longer current']))
        self.assertEqual(self.outcome(w, K['q1']), ('unknown', None, ['no linked disposition']))

    # Complete pagination: label history and blockers on later pages count; a
    # repeated cursor or an incomplete page refuses the whole collection.
    def test_paginated_and_untrustworthy_stage_reads(self):
        data = stage_world()
        data[q(STAGE_LABELS, 4301)] = answer(timeline(4301, [(at(0), 'ready-for-agent', True),
                                                             (at(5), 'held', True)], True, 'L1'))
        data[q(STAGE_LABELS, 4301, 'L1')] = answer(timeline(4301, [
            (at(60), 'held', False), (at(105), 'needs-info', True), (at(121, 30), 'needs-info', False)]))
        data[q(GATES, 4301)] = answer(gates(4301, ['ready-for-agent'], [(4300, 'CLOSED', at(30))], True, 'B1'))
        data[q(GATES, 4301, 'B1')] = answer(gates(4301, ['ready-for-agent'], [(4297, 'CLOSED', at(31))]))
        _, w = self.waits(data)
        # The blocker on page 2 has no merged PR: the gate can't be shown open.
        self.assertEqual(self.outcome(w, K['b1']), ('unknown', None, ['blocker merge unverified']))
        self.assertEqual(w[K['q1']]['result'], 'missed')  # page 2's needs-info removal was read
        for name, change in [
            ('repeated cursor', lambda d: d.update({q(STAGE_LABELS, 4301, 'L1'): answer(
                timeline(4301, [(at(60), 'held', False)], True, 'L1'))})),
            ('incomplete page', lambda d: d.update({q(STAGE_LABELS, 4301, 'L1'): answer(
                timeline(4301, [], True, None))})),
            ('missing read', lambda d: d.pop(q(GATES, 4302))),
            ('missing activity read', lambda d: d.pop(activity_path('room/4302-synthetic'))),
            ('blocker without state', lambda d: d.update({q(GATES, 4302): answer(
                gates(4302, ['ready-for-agent'], [(4300, None, None)]))}))]:
            with self.subTest(name=name):
                bad = copy.deepcopy(data)
                change(bad)
                p, doc, side, root, _ = self.staged(bad)
                self.assertEqual(p.returncode, 1, name)
                self.assertFalse((root / 'out').exists())

    # A label history that disagrees with the current labels is Unknown.
    def test_label_history_disagreement(self):
        data = stage_world()
        data[q(GATES, 4301)] = answer(gates(4301, ['ready-for-agent', 'held'], [(4300, 'CLOSED', at(30))]))
        _, w = self.waits(data)
        self.assertEqual(w[K['b1']]['gaps'], ['label history incomplete'])
        self.assertEqual(w[K['m1']]['result'], 'unknown')

    # Existing consumers stay compatible: v1 is identical with or without the
    # stage reads, plain bench has no new key, and every read is a GET.
    def test_v1_cf4_and_bench_stay_compatible(self):
        p, doc, side, root, calls = self.staged()
        self.assertEqual(p.returncode, 0, p.stderr)
        plain, _, _ = self.collected(data=stage_world(), usage=[], tickets=STAGE_TICKETS)
        self.assertEqual(doc, plain)
        b, value = self.consumer('bench', doc)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertNotIn('stage_waits', value)
        for call in calls:
            self.assertTrue(call[:3] == ['api', '--method', 'GET'] or call[:2] == ['issue', 'view'] or
                            (call[:2] == ['api', 'graphql'] and 'mutation' not in call[3]), call)
        self.assertEqual(sorted(x.name for x in (root / 'out').iterdir()), ['journeys.json', 'stage-waits.json'])

    # Saved outputs hold facts and links only.
    def test_stage_outputs_keep_bodies_and_identities_out(self):
        p, _, _, root, _ = self.staged()
        self.assertEqual(p.returncode, 0, p.stderr)
        b, _ = self.bench_stages(root)
        for text in ((root / 'out' / 'stage-waits.json').read_text(), b.stdout):
            for secret in ['Builder question', 'Orchestrator ruling', 'the guard', 'room/43', 'room%2F', 'thr_',
                           'synthetic-app-token', 'which form', 'refs/heads', 'refs%2F']:
                self.assertNotIn(secret, text)

    # R7: check refuses a sidecar that is not bound to its journey, or whose
    # identity, clock or result its own evidence does not support.
    def test_check_refuses_broken_stage_sidecars(self):
        p, doc, side, root, _ = self.staged()
        self.assertEqual(p.returncode, 0, p.stderr)

        def run_check(value):
            path = root / 'side.json'
            path.write_text(json.dumps(value))
            return subprocess.run([sys.executable, '-I', str(SCRIPT), 'check', str(root / 'out' / 'journeys.json'),
                                   '--stage-waits', str(path)], text=True, capture_output=True, timeout=30)
        good = run_check(side)
        self.assertEqual(good.returncode, 0, good.stderr)

        def by(d, k):
            return next(i for i in d['intervals'] if i['key'] == K[k])

        def invent_end(d):
            known = by(d, 'b1')
            by(d, 'b4').update(state='ended', start=known['start'], clock_from=known['clock_from'], gaps=[])

        def copy_miss(d):
            twin = copy.deepcopy(by(d, 'r1'))
            twin['key'] = twin['key'].replace(at(120), at(119))
            d['intervals'].append(twin)

        def copy_to_new_head(d):
            twin = copy.deepcopy(by(d, 'r1'))
            twin.update(head='7' * 40, key=K['r1'].replace(G1, '7' * 40))
            d['intervals'].append(twin)

        def clock_to_end(d):
            by(d, 'r1')['clock_from'] = by(d, 'r1')['end']['at']
        cases = {
            'other journey': lambda d: d.update(journey_hash='0' * 64),
            'end on an unknown': invent_end,
            'ended without end': lambda d: by(d, 'm1').update(end=None),
            'invented stage': lambda d: by(d, 'm1').update(stage='ci_fix'),
            'gap not in vocabulary': lambda d: by(d, 'm3').update(gaps=['guessed']),
            'end before clock': lambda d: by(d, 'm1').update(clock_from=READ_AT),
            'thread id': lambda d: d['sources'].update(s999=f'{WEB}/issues/1#' + 'thr_' + 'x'),
            'repeated key': lambda d: d['intervals'].append(copy.deepcopy(d['intervals'][0])),
            'copied miss under a new key': copy_miss,
            'clock moved to the end': clock_to_end,
            'hold erased': lambda d: d['holds'].update({'4302': []}),
            'gated without its hold': lambda d: by(d, 'r4').update(state='open', gaps=[], clock_from=at(50)),
            'copied under an unobserved head': copy_to_new_head,
            'start from another head': lambda d: by(d, 'r2').update(
                start={**by(d, 'r1')['start'], 'at': at(191), 'latest': at(191)}),
            'end from another record': lambda d: by(d, 'b1').update(end=by(d, 'q1')['end']),
            # Round 3 (diagnosis), R7: the reviewer's 09:10 -> 09:01 move of builder comment 6101's endpoint.
            'endpoint moved off its journey time': lambda d: by(d, 'b1')['end'].update(at=at(61), latest=at(61)),
            'verdict start moved': lambda d: by(d, 'f1')['start'].update(at=at(149), latest=at(149)),
            'merge end moved': lambda d: by(d, 'm1')['end'].update(at=at(212), latest=at(212)),
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                bad = copy.deepcopy(side)
                change(bad)
                self.assertEqual(run_check(bad).returncode, 1, name)

    # The sanitized benchmark demonstration is the collector's and bench's output.
    def test_stage_fixtures_are_the_outputs(self):
        p, doc, side, root, _ = self.staged()
        self.assertEqual(p.returncode, 0, p.stderr)
        b, out = self.bench_stages(root)
        self.assertEqual(b.returncode, 0, b.stderr)
        folder = HERE / 'fixtures' / 'stage-waits'
        self.assertEqual(json.loads((folder / 'journeys.json').read_text()), doc)
        self.assertEqual(json.loads((folder / 'stage-waits.json').read_text()), side)
        self.assertEqual(json.loads((folder / 'bench.json').read_text()), out['stage_waits'])

    def test_contract_documents_the_stage_vocabulary(self):
        text = (HERE / 'journey-contract.md').read_text()
        self.assertIn('`closedwiz.journey.stage-waits.v1`', text)
        self.assertIn('`closedwiz.journey.stage-bench.v1`', text)
        table = text.split('| Gap | Means |', 1)[1].split('\n\n', 1)[0]
        rows = [line.split('|')[1].strip().strip('`') for line in table.splitlines() if line.startswith('| `')]
        self.assertEqual(rows, ['label history incomplete', 'head history incomplete', 'no plan approval',
                                'approval not current', 'blocker merge unverified', 'start record outside its gate',
                                'edited record',
                                'reviewer start unconfirmed', 'disputed without fix', 'no linked disposition',
                                'no green completion time', 'ci order unknown', 'no end record', 'no longer current',
                                'held'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
