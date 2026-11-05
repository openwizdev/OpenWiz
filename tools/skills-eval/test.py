#!/usr/bin/env python3
"""Offline proofs for the skills eval (#1361). No key, no network, synthetic inputs only.

Run: python3 -I tools/skills-eval/test.py
"""
import ast
import copy
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as C  # noqa: E402
import driver  # noqa: E402
import eval as E  # noqa: E402
import fakeworld  # noqa: E402
import records  # noqa: E402
import score as S  # noqa: E402
import tokens as T  # noqa: E402

READ, LIST = E.snapshot('HEAD')
SCHEMA = json.loads(READ('contracts/decisions.v1.schema.json'))
FILES = {'skills/demo/SKILL.md': '# Demo\nRead docs/demo.md.\n', 'docs/demo.md': 'demo rules\n',
         'skills/demo/scripts/check.sh': '#!/bin/sh\n'}
SNAP = (FILES.get, lambda p: [k for k in FILES if k.startswith(p)])
H40 = 'e' * 40


def setUpModule():
    # Offline controls explicitly supply synthetic literals; no private checkout read.
    folder = unittest.enterModuleContext(tempfile.TemporaryDirectory())
    literals = Path(folder) / 'literals.txt'
    literals.write_text('synthetic-private-machine\n', encoding='utf-8')
    unittest.enterModuleContext(mock.patch.dict(os.environ, {
        'OPENWIZ_PRIVACY_LITERALS': str(literals),
    }))


def world(**kw):
    w = {'github': {'issues': {'4101': {'title': 'Demo', 'labels': ['ready-for-agent'], 'comments': []}},
                    'pulls': {'4102': {'title': '#4101: Demo', 'head': H40, 'head_ref': 'room/4101-demo',
                                       'checks': [{'name': 'rust', 'status': 'in_progress'}], 'comments': []}}},
         'processes': [{'pid': 4242, 'owner': 'self', 'cmd': 'sh -c watch'}]}
    w.update(kw)
    return fakeworld.World(w, SNAP)


def demo_case(**expect):
    exp = {'actions': [], 'allow': [], 'forbid': [], 'end': 'end_turn'}
    exp.update(expect)
    return {'id': 'demo', 'expect': exp, 'ticket': 4101, 'head': H40}


def t(events, stop='end_turn', final='Done.'):
    return {'case': 'demo', 'repeat': 1, 'stop': stop, 'final': final, 'events': events, 'usage': {}}


def ev(kind, cmd, body=None):
    return {'seq': 0, 'kind': kind, 'argv': cmd.split() if isinstance(cmd, str) else cmd, 'body': body}


class FakeToolBoundary(unittest.TestCase):
    """Escapes are refused and recorded; nothing leaves the process."""

    ESCAPES = ['curl https://example.invalid', 'wget -q example.invalid', 'python3 -c "print(1)"',
               'bash -c "gh issue list"', 'sh -c "echo hi"', 'echo $(curl https://example.invalid)', 'echo `id`', 'env',
               'cat /etc/passwd', 'cat ../../secret', 'cat ~/.ssh/id_rsa', '/usr/bin/gh issue list',
               './run.sh', 'nc -l 9', 'ssh host', 'eval "gh pr merge 4102"', 'node -e 1',
               'ls ../', 'claude -p hi', 'codex exec hi', 'sudo true', 'cat <(echo x)', 'xargs gh']

    def test_escapes_are_recorded_and_run_nothing(self):
        for cmd in self.ESCAPES:
            w = world()
            r = w.shell(cmd)
            self.assertEqual(r.code, 126, cmd)
            self.assertEqual([e['kind'] for e in w.events], ['escape'], cmd)

    def test_escape_inside_a_chain_runs_nothing_else(self):
        w = world()
        w.shell('gh issue comment 4101 --body hi && curl https://example.invalid')
        self.assertEqual([e['kind'] for e in w.events], ['escape'])
        self.assertEqual(w.w['github']['issues']['4101']['comments'], [])

    def test_no_process_socket_or_network_is_used(self):
        def boom(*a, **k):
            raise AssertionError('the fake world reached outside the process')
        cmds = ['gh issue view 4101 --comments', 'gh pr checks 4102', 'gh issue comment 4101 --body x',
                'room-cli thread spawn --provider claude-code --prompt hi', 'git push', 'kill 4242', 'ps',
                'cat skills/demo/SKILL.md | grep -n Read', 'sh skills/demo/scripts/check.sh', 'rg x',
                'curl https://example.invalid', 'gh api repos/o/r/issues/4101/comments']
        with mock.patch.object(subprocess, 'Popen', boom), mock.patch.object(socket, 'socket', boom), \
                mock.patch.object(socket, 'create_connection', boom):
            w = world()
            for c in cmds:
                w.shell(c)

    def test_fake_world_imports_nothing_that_reaches_out(self):
        tree = ast.parse((HERE / 'fakeworld.py').read_text())
        names = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or '')])}
        self.assertLessEqual(names, {'copy', 'fnmatch', 'json', 're', 'shlex', 'hashlib'})
        self.assertNotIn('os', names)  # so no environment, process or file-system access

    def test_writes_change_state_and_are_events(self):
        w = world()
        w.shell("gh issue comment 4101 --body \"$(cat <<'EOF'\nline one\nline two\nEOF\n)\"")
        w.shell('gh issue edit 4101 --add-label needs-info')
        out = w.shell('gh issue view 4101 --json labels,comments').out
        data = json.loads(out)
        self.assertEqual([l['name'] for l in data['labels']], ['ready-for-agent', 'needs-info'])
        self.assertEqual(data['comments'][0]['body'], 'line one\nline two')
        self.assertEqual([e['kind'] for e in w.events], ['write', 'write', 'read'])

    def test_heredoc_body_file_and_repo_files_are_read_only_snapshot(self):
        w = world()
        w.shell("cat > /tmp/b.md <<'EOF'\nhello\nEOF\ngh issue comment 4101 --body-file /tmp/b.md")
        self.assertEqual(w.events[-1]['body'], 'hello\n')
        w.shell("echo changed > skills/demo/SKILL.md")
        self.assertEqual(FILES['skills/demo/SKILL.md'], '# Demo\nRead docs/demo.md.\n')
        self.assertEqual(w.shell('cat skills/demo/SKILL.md').out, 'changed\n')

    def test_scripts_are_canned_never_run(self):
        w = world(scripts=[{'argv': ['script', 'skills/demo/scripts/check.sh', 'check'], 'out': 'hit #4101: x\n', 'code': 1}])
        r = w.shell('sh /repo/skills/demo/scripts/check.sh check /tmp/s.json')
        self.assertEqual((r.out, r.code), ('hit #4101: x\n', 1))
        self.assertEqual(w.events[-1]['argv'], ['script', 'skills/demo/scripts/check.sh', 'check', '/tmp/s.json'])
        r = w.shell('sh skills/demo/scripts/check.sh snapshot')
        self.assertEqual((r.code, w.events[-1]['kind']), (127, 'refused'))

    def test_substitution_and_variables_run_inside_the_fake_shell(self):
        w = world()
        w.shell('snap=$(mktemp)\necho "$snap" && N=4101; gh issue comment $N --body "for ${N}"')
        self.assertEqual(w.events[-1]['argv'][:4], ['gh', 'issue', 'comment', '4101'])
        self.assertEqual(w.events[-1]['body'], 'for 4101')
        self.assertEqual(w.shell("echo '$N'").out, '$N\n')
        self.assertNotIn('escape', [e['kind'] for e in w.events])

    def test_unknown_programs_are_refused_not_run(self):
        w = world()
        self.assertEqual(w.shell('rg pattern').code, 127)
        self.assertEqual(w.events[-1]['kind'], 'refused')

    def test_kill_needs_an_existing_pid(self):
        w = world()
        self.assertEqual(w.shell('kill 9999').code, 1)
        self.assertEqual(w.shell('kill 4242').code, 0)
        self.assertNotIn('4242', w.shell('ps').out)


class Scoring(unittest.TestCase):
    """Historical wrong actions, malformed records, incomplete runs and escapes fail; controls pass."""

    def test_every_case_control_scores_as_declared(self):
        errs, all_cases, _ = E.check(READ, LIST)
        self.assertEqual(errs, [])
        self.assertGreaterEqual(len(all_cases), 22)

    def test_incident_cases_reject_their_historical_wrong_action(self):
        incidents = [c for c in C.load_all() if c['category'] == 'incident']
        self.assertEqual(sorted(c['id'][:3] for c in incidents), ['i1-', 'i2-', 'i3-', 'i4-', 'i5-'])
        for c in incidents:
            hist = [ctl for ctl in c['controls']['fail'] if ctl['why'].startswith('historical:')]
            self.assertTrue(hist, c['id'])
            for ctl in hist:
                ok, reasons, _ = S.score(c, C.control_transcript(c, ctl), SCHEMA)
                self.assertFalse(ok, c['id'])
                self.assertIn(ctl['reason'], reasons)

    def test_incomplete_runs_fail(self):
        c = demo_case()
        for tr in (t([], stop='turn_cap'), t([], stop='max_tokens'), t([], stop='refusal'), t([], stop='error'),
                   t([], final=''), t([], final=None), {'case': 'demo'}, t([{'kind': 'read'}]), t([ev('bogus', 'x')])):
            ok, reasons, _ = S.score(c, tr, SCHEMA)
            self.assertFalse(ok, tr)
            self.assertIn('incomplete', reasons)
        self.assertTrue(S.score(c, t([]), SCHEMA)[0])

    def test_escape_fails_even_when_everything_else_holds(self):
        c = demo_case(actions=[{'read': 'gh pr checks'}])
        ok, reasons, _ = S.score(c, t([ev('read', 'gh pr checks 4102'), ev('escape', 'curl x')]), SCHEMA)
        self.assertEqual((ok, reasons), (False, ['escape']))

    def test_unlisted_writes_fail_closed(self):
        c = demo_case(actions=[{'write': 'gh issue comment', 'args': ['4101']}])
        ok, reasons, _ = S.score(c, t([ev('write', 'gh issue comment 4101', 'x'), ev('write', 'gh pr merge 4102')]), SCHEMA)
        self.assertEqual((ok, reasons), (False, ['unlisted-write']))
        ok, reasons, _ = S.score(c, t([ev('write', 'gh issue comment 4101', 'x'), ev('local', 'git commit -m x')]), SCHEMA)
        self.assertTrue(ok, reasons)

    def test_order_matters(self):
        c = demo_case(actions=[{'run': 'script x.sh snapshot'}, {'write': 'room-cli thread spawn'}])
        good = t([ev('read', 'script x.sh snapshot'), ev('write', 'room-cli thread spawn')])
        bad = t([ev('write', 'room-cli thread spawn'), ev('read', 'script x.sh snapshot')])
        self.assertTrue(S.score(c, good, SCHEMA)[0])
        self.assertEqual(S.score(c, bad, SCHEMA)[1], ['missing-action'])

    def test_refused_attempt_never_counts_as_done_but_is_caught_by_forbid(self):
        c = demo_case(actions=[{'run': 'script x.sh'}], forbid=[{'run': 'npx'}])
        self.assertEqual(S.score(c, t([ev('refused', 'script x.sh')]), SCHEMA)[1], ['missing-action'])
        self.assertIn('forbidden', S.score(c, t([ev('read', 'script x.sh'), ev('refused', 'npx skills add y')]), SCHEMA)[1])

    def test_malformed_records_fail(self):
        c = demo_case(actions=[{'write': 'gh pr comment', 'record': 'verdict'}])
        for body in ('VERDICT: APPROVE', f'VERDICT: LGTM at {H40}', f'Verdict: APPROVE at {H40}', f'VERDICT: APPROVE at {"d" * 40}', None, ''):
            ok, reasons, _ = S.score(c, t([ev('write', 'gh pr comment 4102', body)]), SCHEMA)
            self.assertEqual((ok, reasons), (False, ['bad-record']), body)
        self.assertTrue(S.score(c, t([ev('write', 'gh pr comment 4102', f'VERDICT: CHANGES at {H40}\n\nR1 ...')]), SCHEMA)[0])

    def test_handback_record(self):
        c = demo_case(actions=[{'write': 'gh pr create', 'record': 'handback'}])
        good = ev('write', ['gh', 'pr', 'create', '--title', '#4101: Demo'], f'Closes #4101\n\nHead `{H40}`')
        self.assertTrue(S.score(c, t([good]), SCHEMA)[0])
        for argv, body in ((['gh', 'pr', 'create', '--title', 'Demo'], f'Closes #4101 {H40}'),
                           (['gh', 'pr', 'create', '--title', '#4101: Demo'], f'Fixes #4101 {H40}'),
                           (['gh', 'pr', 'create', '--title', '#4101: Demo'], 'Closes #4101')):
            self.assertEqual(S.score(c, t([ev('write', argv, body)]), SCHEMA)[1], ['bad-record'])

    def test_skipped_or_missing_runs_fail_the_suite(self):
        all_cases = C.load_all()
        good = {c['id']: C.control_transcript(c, c['controls']['pass'][0]) for c in all_cases}
        with tempfile.TemporaryDirectory() as d:
            ids = [c['id'] for c in all_cases]
            ReviewFindings.write_set(self, d)
            for cid in ids:
                for rep in range(1, json.loads(Path(d, 'manifest.json').read_text())['repeats'] + 1):
                    Path(d, f'{cid}.r{rep}.json').write_text(json.dumps(good[cid] | {'repeat': rep}))
            self.assertTrue(E.score_set(d)['suite_pass'])
            Path(d, f'{ids[0]}.r2.json').unlink()
            s = E.score_set(d)
            self.assertFalse(s['suite_pass'])
            self.assertEqual(s['passed'], s['runs'] - 1)
            Path(d, f'{ids[1]}.r1.json').write_text('{not json')
            self.assertEqual(E.score_set(d)['passed'], s['runs'] - 2)

    def test_compare_refuses_unlike_sets(self):
        a = {'settings_hash': 's', 'cases_hash': 'c', 'code_hash': 'k', 'schema_hash': 'h', 'passed': 1, 'runs': 2,
             'rows': [{'case': 'x', 'repeat': 1, 'pass': True}, {'case': 'y', 'repeat': 1, 'pass': False}]}
        b = copy.deepcopy(a)
        b['rows'][1]['pass'] = True
        self.assertEqual(E.compare(a, b)['fixed'], ['y'])
        for k in ('settings_hash', 'cases_hash', 'code_hash', 'schema_hash'):
            with self.assertRaises(ValueError):
                E.compare(a, dict(b, **{k: 'other'}))


class Records(unittest.TestCase):
    ROUND = {'schema': 'openwiz.decisions.v1', 'kind': 'grill_round', 'id': 'demo-round-1', 'status': 'open',
             'risk': 'ordinary', 'fingerprint': 'a' * 64, 'grill_file': 'docs/grills/2030-01-07-demo.md', 'round': 1,
             'questions': [{'id': 'G1', 'decides': 'Which?', 'context': 'Two options.', 'recommendation': 'The first.'}],
             'answered': []}

    def body(self, obj):
        return '```json\n' + json.dumps(obj) + '\n```'

    def test_valid_request(self):
        self.assertEqual(records.check_decisions('Round 1.\n\n' + self.body(self.ROUND), SCHEMA), [])

    def test_invalid_requests(self):
        bad = [
            self.body(dict(self.ROUND, extra=1)),
            self.body(dict(self.ROUND, round=1.0)).replace('"round": 1.0', '"round": 1.0'),
            self.body(dict(self.ROUND, status='done')),
            self.body(dict(self.ROUND, fingerprint='A' * 64)),
            self.body({k: v for k, v in self.ROUND.items() if k != 'questions'}),
            '```json\n{"schema": "openwiz.decisions.v1", "kind": "grill_round", "kind": "grill_round"}\n```',
            self.body(self.ROUND) + '\n\n' + self.body(self.ROUND),
            '```json\n{"schema": "openwiz.decisions.v1", \n```',
            self.body(dict(self.ROUND, kind='response')),
            'no fence at all',
            ' ```json\n' + json.dumps(self.ROUND) + '\n```',
        ]
        for b in bad:
            self.assertTrue(records.check_decisions(b, SCHEMA), b[:80])


class Driver(unittest.TestCase):
    """The role-run loop, with a scripted transport: the model API is the only network."""

    SETTINGS = {'model': 'claude-opus-5-5', 'effort': 'high', 'max_tokens': 1000, 'max_turns': 4,
                'prices_usd_per_mtok': {'input_tokens': 4.0, 'output_tokens': 20.0,
                                        'cache_creation_input_tokens': 5.0, 'cache_read_input_tokens': 0.2}}

    def case(self):
        return {'id': 'demo', 'brief': 'You are the builder for #4101.', 'world': {
            'github': {'issues': {'4101': {'title': 'Demo', 'labels': [], 'comments': []}}, 'pulls': {}}}}

    def scripted(self, responses):
        sent = []

        def post(url, body):
            sent.append(copy.deepcopy(body))
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return post, sent

    def tool(self, cmd, i='t1'):
        return {'type': 'tool_use', 'id': i, 'name': 'shell', 'input': {'command': cmd}}

    def test_tool_loop_records_events_and_ends(self):
        thinking = {'type': 'thinking', 'thinking': '', 'signature': 'sig'}
        post, sent = self.scripted([
            {'content': [thinking, self.tool('gh issue edit 4101 --add-label needs-info')], 'stop_reason': 'tool_use',
             'usage': {'input_tokens': 1000, 'output_tokens': 100}},
            {'content': [{'type': 'text', 'text': 'Asked on the ticket.'}], 'stop_reason': 'end_turn',
             'usage': {'input_tokens': 10, 'output_tokens': 10, 'cache_read_input_tokens': 1000}}])
        tr = driver.run_case(self.case(), self.SETTINGS, SNAP, post, 1)
        self.assertEqual((tr['stop'], tr['final'], tr['turns']), ('end_turn', 'Asked on the ticket.', 2))
        self.assertEqual([e['argv'][:3] for e in tr['events']], [['gh', 'issue', 'edit']])
        self.assertEqual(sent[1]['messages'][1]['content'][0], thinking)
        self.assertIn('[exit 0]', sent[1]['messages'][2]['content'][0]['content'])
        self.assertEqual(sent[0]['tools'][0]['name'], 'shell')
        self.assertEqual(len(sent[0]['tools']), 1)
        self.assertEqual(tr['cost_usd'], round((1010 * 4 + 110 * 20 + 1000 * 0.2) / 1e6, 6))

    def test_turn_cap_error_and_refusal_are_incomplete(self):
        post, _ = self.scripted([{'content': [self.tool('ps', f't{i}')], 'stop_reason': 'tool_use', 'usage': {}} for i in range(4)])
        self.assertEqual(driver.run_case(self.case(), self.SETTINGS, SNAP, post, 1)['stop'], 'turn_cap')
        post, _ = self.scripted([RuntimeError('HTTP 500')])
        tr = driver.run_case(self.case(), self.SETTINGS, SNAP, post, 1)
        self.assertEqual((tr['stop'], tr['error']), ('error', 'HTTP 500'))
        post, _ = self.scripted([{'content': [], 'stop_reason': 'refusal', 'usage': {}}])
        self.assertEqual(driver.run_case(self.case(), self.SETTINGS, SNAP, post, 1)['stop'], 'refusal')
        c = demo_case()
        for stop in ('turn_cap', 'error', 'refusal'):
            self.assertIn('incomplete', S.score(c, t([], stop=stop), SCHEMA)[1])

    def test_other_tools_are_refused(self):
        post, sent = self.scripted([
            {'content': [{'type': 'tool_use', 'id': 'x', 'name': 'bash', 'input': {'command': 'curl x'}}], 'stop_reason': 'tool_use', 'usage': {}},
            {'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn', 'usage': {}}])
        tr = driver.run_case(self.case(), self.SETTINGS, SNAP, post, 1)
        self.assertEqual(tr['events'], [])
        self.assertIn('the only tool is shell', sent[1]['messages'][2]['content'][0]['content'])


class RunCommand(unittest.TestCase):
    """`eval.py run` is resumable, refuses a changed set and stops at the spend cap (scripted model, no key)."""

    def test_resume_refuse_and_cap(self):
        calls = []

        def fake_http_post(key, version):
            def post(url, body):
                calls.append(url)
                return {'choices': [{'message': {'role': 'assistant', 'content': 'Nothing to do.'}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
            return post
        cid = 'i1-ci-pending-on-changed-head'
        with tempfile.TemporaryDirectory() as d, mock.patch.dict('os.environ', {'OPENROUTER_API_KEY': 'synthetic'}), \
                mock.patch.object(driver, 'http_post', fake_http_post):
            self.assertEqual(E.main(['run', '--out', d, '--case', cid]), 0)
            reps = json.loads((HERE / 'settings.json').read_text())['repeats']
            reps_calls = 2 * reps  # this case's reply is judged: one actor call and one judge call per run
            self.assertEqual(len(calls), reps_calls)
            self.assertEqual(sorted(p.name for p in Path(d).glob('*.r*.json')), [f'{cid}.r{k}.json' for k in range(1, reps + 1)])
            self.assertEqual(E.main(['run', '--out', d, '--case', cid]), 0)
            self.assertEqual(len(calls), reps_calls)  # resumed: nothing ran again
            s = E.score_set(d)
            self.assertFalse(s['suite_pass'])  # the other cases were not run: never a pass
            self.assertEqual(s['runs'], len(C.load_all()) * reps)
            first = Path(d, f'{cid}.r1.json')
            first.write_text(json.dumps(dict(json.loads(first.read_text()), cost_usd=10 ** 6)))
            self.assertEqual(E.main(['run', '--out', d, '--case', 'i2-orchestration-comment-during-helpers']), 3)
            self.assertEqual(len(calls), reps_calls)  # the cap stopped it before any call
            man = json.loads(Path(d, 'manifest.json').read_text())
            Path(d, 'manifest.json').write_text(json.dumps(dict(man, cases_hash='changed')))
            with self.assertRaises(SystemExit):
                E.main(['run', '--out', d])

    def test_run_without_a_key_records_nothing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(SystemExit) as e:
                E.main(['run', '--out', d])
            self.assertIn('not run', str(e.exception))
            self.assertEqual(list(Path(d).iterdir()), [])


class Tokens(unittest.TestCase):
    """Required text counts once per load; relocation is no saving."""

    def counter(self):
        return lambda text: len(text.split()) + 3  # synthetic: 3 tokens of message overhead

    def files(self, skill_text, rules_text):
        return {'skills/a/SKILL.md': skill_text, 'skills/b/SKILL.md': 'b b', 'docs/rules.md': rules_text, 'docs/extra.md': 'x y z'}

    MAP = {'a': {'required': ['skills/a/SKILL.md', 'docs/rules.md'], 'conditional': {'docs/extra.md': 'rare path'}},
           'b': {'required': ['skills/b/SKILL.md', 'docs/rules.md'], 'conditional': {}}}

    def test_counts_shared_files_once_per_load_and_subtracts_overhead(self):
        f = self.files('one two three', 'r1 r2')
        r = T.report(self.MAP, f.get, self.counter(), 'synthetic', {})
        self.assertEqual(r['overhead_subtracted'], 3)
        self.assertEqual(r['skills']['a']['required_tokens'], 3 + 2)
        self.assertEqual(r['skills']['b']['required_tokens'], 2 + 2)
        self.assertEqual(r['total_required_tokens'], 9)
        self.assertEqual(r['total_conditional_tokens'], 3)

    def test_moving_text_into_a_required_file_saves_nothing(self):
        before = T.report(self.MAP, self.files('one two three r9', 'r1 r2').get, self.counter(), 'synthetic', {})
        moved = T.report(self.MAP, self.files('one two three', 'r1 r2 r9').get, self.counter(), 'synthetic', {})
        self.assertEqual(before['skills']['a']['required_tokens'], moved['skills']['a']['required_tokens'])
        d = T.diff(before, moved)
        self.assertLessEqual(d['total']['saved'], 0)

    def test_diff_reports_savings_and_refuses_unlike_or_offline_reports(self):
        before = T.report(self.MAP, self.files('one two three four', 'r1 r2').get, self.counter(), 'synthetic', {})
        after = T.report(self.MAP, self.files('one two', 'r1 r2').get, self.counter(), 'synthetic', {})
        d = T.diff(before, after)
        self.assertEqual(d['total'], {'before': 10, 'after': 8, 'saved': 2, 'percent': 20.0})
        with self.assertRaises(ValueError):
            T.diff(before, dict(after, tokenizer='other'))
        offline = T.report(self.MAP, self.files('one', 'r1').get, None, 'none', {})
        self.assertIsNone(offline['total_required_tokens'])
        with self.assertRaises(ValueError):
            T.diff(offline, offline)

    def test_linked_settings_sources_include_root_files_and_refuse_unsafe_paths(self):
        cases = [
            ('root', '`STATUS.md`', ['STATUS.md']),
            ('nested', '`docs/rules.md`', ['docs/rules.md']),
            ('markdown', '[rules](../rules.md#source)', ['docs/rules.md']),
            ('missing', '`MISSING.md` `docs/missing.md` [missing](../missing.md)', []),
            ('unsafe', '`/absolute.md` `../parent.md` `..hidden.md` '
             '[outside](../../../outside.md)', []),
            ('duplicates', '`STATUS.md` `STATUS.md` [status](../../STATUS.md) '
             '`docs/rules.md` [rules](../rules.md)', ['STATUS.md', 'docs/rules.md']),
        ]
        mapping = {'demo': {'required': ['skills/demo/SKILL.md'], 'conditional': {},
                            'not_loaded': {}, 'linked': {'docs/agents/': 'settings sources'}}}
        for name, text, expected in cases:
            with self.subTest(name=name):
                files = {'skills/demo/SKILL.md': '# Demo\n', 'STATUS.md': 'status\n',
                         'docs/rules.md': 'rules\n', '/absolute.md': 'unsafe\n',
                         '../parent.md': 'unsafe\n', '..hidden.md': 'unsafe\n',
                         '../outside.md': 'unsafe\n',
                         'docs/agents/first.md': text, 'docs/agents/second.md': text}
                report = T.report(mapping, files.get, None, 'none', {},
                                  lambda prefix: [p for p in files if p.startswith(prefix)])
                self.assertEqual(report['skills']['demo']['conditional'], expected)
                self.assertEqual(set(report['files']), {'skills/demo/SKILL.md', *expected})

    def test_the_real_map_covers_every_shipped_skill(self):
        m = T.load_map(HERE / 'required-text.json')
        self.assertEqual(T.map_problems(m, E.shipped(READ), READ, LIST), [])
        broken = copy.deepcopy(m)
        broken['build-ticket']['required'].append('docs/agents/missing.md')
        broken['triage']['conditional']['x.md'] = ''
        del broken['image']
        self.assertEqual(len(T.map_problems(broken, E.shipped(READ), READ, LIST)), 4)


class Contract(unittest.TestCase):
    """contract.md, the code and the commands agree."""

    TEXT = (HERE / 'contract.md').read_text()

    def test_case_example_keys(self):
        example = json.loads(re.search(r'```json\n(.*?)\n```', self.TEXT, re.S).group(1))
        self.assertLessEqual(set(example), C.CASE_KEYS)
        self.assertEqual(set(example['expect']), C.EXPECT_KEYS)
        self.assertEqual(example['schema'], 'openwiz.skills-eval.case.v1')

    def test_reasons_records_events_and_categories_are_the_code_s(self):
        order = re.search(r'The reasons, in this order: (.*?)\. A run', self.TEXT, re.S).group(1)
        self.assertEqual(re.findall(r'`([a-z-]+)`', order), S.REASONS)
        self.assertEqual(set(S.REASONS), C.REASONS)
        table = re.search(r'## 5\. Records\n(.*?)\n## 6', self.TEXT, re.S).group(1)
        self.assertEqual(set(re.findall(r'^\| `([a-z.0-9-]+)` \|', table, re.M)), C.RECORDS)
        for word in S.KINDS | C.CATEGORIES | C.MATCH_KEYS:
            self.assertTrue(f'`{word}`' in self.TEXT, word)

    def test_settings_freeze_what_the_contract_names(self):
        s = json.loads((HERE / 'settings.json').read_text())
        for k in ('harness', 'model', 'effort', 'max_tokens', 'max_turns', 'repeats', 'api_version',
                  'prices_usd_per_mtok', 'spend_cap_usd', 'token_model', 'judge_model'):
            self.assertIn(k, s)
        self.assertEqual(set(s['prices_usd_per_mtok']), set(Driver.SETTINGS['prices_usd_per_mtok']))
        self.assertGreaterEqual(s['repeats'], 2)
        # Jake's #1684 decision: DeepSeek via OpenRouter; EV1(b) cap remains $20.
        self.assertEqual((s['model'], s['effort'], s['spend_cap_usd'], s['token_model']),
                         ('deepseek/deepseek-v4.1-flash', 'high', 20, 'deepseek/deepseek-v4.1-flash'))

    def test_commands_in_readme_exist(self):
        readme = (HERE / 'README.md').read_text()
        cmds = set(re.findall(r'eval\.py ([a-z-]+)', readme))
        self.assertTrue(cmds)
        for c in cmds:
            self.assertTrue(any(line.strip().startswith(f'eval.py {c}') for line in E.__doc__.splitlines()))

    def test_privacy_scan_catches_planted_identifiers(self):
        base = C.load_all()[0]
        for planted in ('see https://github.com/x/y', 'thread thr_synnegative', 'thread cr_child_synthetic', 'issue #123', 'issue #3999',
                        'key sk-ant-abc', 'mail someone@example.org', 'ask Jake'):
            c = copy.deepcopy(base)
            c['brief'] += ' ' + planted
            self.assertTrue(C.privacy_problems(c), planted)
        self.assertEqual(C.privacy_problems(base), [])

    def test_privacy_private_input_refuses_missing_unreadable_or_empty(self):
        base = C.load_all()[0]
        refusal = ['case privacy: private literals input is missing, unreadable or empty']
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ):
            literals = Path(d) / 'literals.txt'
            os.environ.pop('OPENWIZ_PRIVACY_LITERALS', None)
            with self.subTest(input='unset'):
                self.assertEqual(C.privacy_problems(base), refusal)
            for path in ('', str(literals), d):
                with self.subTest(path=path):
                    os.environ['OPENWIZ_PRIVACY_LITERALS'] = path
                    self.assertEqual(C.privacy_problems(base), refusal)
            os.environ['OPENWIZ_PRIVACY_LITERALS'] = str(literals)
            for data in (b'', b'\n', b'synthetic-private-machine\n\n', b'\xff'):
                with self.subTest(data=data):
                    literals.write_bytes(data)
                    self.assertEqual(C.privacy_problems(base), refusal)
            literals.write_text('synthetic-private-machine\n', encoding='utf-8')
            with self.subTest(input='permission denied'), mock.patch.object(Path, 'read_text', side_effect=PermissionError):
                self.assertEqual(C.privacy_problems(base), refusal)
            self.assertEqual(C.privacy_problems(base), [])

    def test_privacy_private_literals_scan_every_input_without_echoing(self):
        base = C.load_all()[0]
        # Literal punctuation must not acquire regex meaning; matching retains case folding.
        planted = 'synthetic-private[workstation]'
        with tempfile.TemporaryDirectory() as d:
            literals = Path(d) / 'literals.txt'
            literals.write_text(planted + '\nsynthetic-private-account\nprivate-person@example.org\n', encoding='utf-8')
            with mock.patch.dict(os.environ, {'OPENWIZ_PRIVACY_LITERALS': str(literals)}):
                self.assertEqual(C.privacy_problems(base), [])
                for field in ('brief', 'world', 'controls', 'expect'):
                    for value in (planted, planted.upper(), 'synthetic-private-account', 'private-person@example.org'):
                        with self.subTest(field=field, value=value):
                            c = copy.deepcopy(base)
                            c[field] = value if field == 'brief' else {'nested': [value]}
                            self.assertEqual(C.privacy_problems(c), ['case privacy: a private literal'])
                c = copy.deepcopy(base)
                c['world'] = {planted: 'synthetic value'}
                self.assertEqual(C.privacy_problems(c), ['case privacy: a private literal'])
                c['world'] = {'nested': 'synthetic-privatew'}
                self.assertEqual(C.privacy_problems(c), [])
                # R1: a valid case ID is also untrusted diagnostic data. Existing
                # field controls used a clean ID, so they missed this disclosure.
                c = copy.deepcopy(base)
                c['id'] = 'case-synthetic-private-account'
                c['brief'] = 'synthetic-private-account'
                errors = C.problems(c, E.shipped(READ), 'case-synthetic-private-account.json')
                self.assertTrue(errors)
                self.assertNotIn('synthetic-private-account', '\n'.join(errors))

    def test_coverage_names_every_shipped_skill_and_the_five_incidents(self):
        _, all_cases, cov = E.check(READ, LIST)
        self.assertEqual(sorted(cov), sorted(E.shipped(READ)))
        for s, cats in cov.items():
            self.assertTrue(cats['workflow'], s)
        prov = json.loads((HERE / 'provenance.json').read_text())
        for c in all_cases:
            self.assertIn(c['id'], prov['cases'])
        incidents = {k: v for k, v in prov['cases'].items() if re.match(r'i\d-', k)}
        self.assertEqual(len(incidents), 5)
        for v in incidents.values():
            self.assertTrue(all(l.startswith('https://github.com/') for l in v['links']))


class ReviewFindings(unittest.TestCase):
    """Review of #1372 at 0870d046: one proof per finding R1-R10, written before the fixes."""

    PRICES = {'input_tokens': 0.5, 'output_tokens': 2.5, 'cache_creation_input_tokens': 0.625, 'cache_read_input_tokens': 0.05}
    SET = {'model': 'claude-haiku-5-5', 'effort': 'high', 'max_tokens': 16000, 'max_turns': 40,
           'prices_usd_per_mtok': PRICES, 'judge_model': 'claude-haiku-5-5'}

    def tool_loop(self, calls, usage):
        def post(url, body):
            calls.append(body)
            return {'content': [{'type': 'tool_use', 'id': f't{len(calls)}', 'name': 'shell', 'input': {'command': 'ps'}}],
                    'stop_reason': 'tool_use', 'usage': usage}
        return post

    def small_case(self, **kw):
        c = {'id': 'demo', 'brief': 'You are the builder for #4101.', 'expect': {'actions': [], 'allow': [], 'forbid': [], 'end': 'end_turn'},
             'world': {'github': {'issues': {'4101': {'title': 'Demo', 'labels': [], 'comments': []}}, 'pulls': {}}}}
        c.update(kw)
        return c

    # R1: the cap is enforced before every request, from a conservative reservation.
    def test_r1_cap_reserves_before_each_request(self):
        calls = []
        tr = driver.run_case(self.small_case(), self.SET, SNAP, self.tool_loop(calls, {'input_tokens': 20000, 'output_tokens': 5000}), 1, budget_usd=0.2)
        self.assertEqual(tr['stop'], 'cap')
        self.assertLessEqual(tr['cost_usd'], 0.2)
        self.assertGreaterEqual(len(calls), 1)
        self.assertIn('incomplete', S.score(demo_case(), tr, SCHEMA)[1])
        calls2 = []
        tr2 = driver.run_case(self.small_case(), self.SET, SNAP, self.tool_loop(calls2, {}), 1, budget_usd=0.01)
        self.assertEqual((len(calls2), tr2['stop']), (0, 'cap'))

    def test_r1_run_persists_a_cap_stopped_case(self):
        calls = []

        def fake_http_post(key, version):
            return self.tool_loop(calls, {'input_tokens': 100, 'output_tokens': 10})
        cid = 'i1-ci-pending-on-changed-head'
        with tempfile.TemporaryDirectory() as d, mock.patch.dict('os.environ', {'OPENROUTER_API_KEY': 'synthetic'}), \
                mock.patch.object(driver, 'http_post', fake_http_post):
            Path(d, 'zz-prior.r1.json').write_text(json.dumps({'cost_usd': 19.999}))
            self.assertEqual(E.main(['run', '--out', d, '--case', cid]), 3)
            self.assertEqual(calls, [])
            tr = json.loads(Path(d, f'{cid}.r1.json').read_text())
            self.assertEqual(tr['stop'], 'cap')

    # R2: scoring refuses changed cases or scorer, checks transcript identity, reads the schema at the run's revision.
    def write_set(self, d, man_extra=None, tr=None):
        all_cases = C.load_all()
        c = all_cases[0]
        settings = json.loads((HERE / 'settings.json').read_text())
        man = {'cases': [x['id'] for x in all_cases], 'repeats': settings['repeats'], 'settings': settings,
               'settings_hash': E.sha(settings), 'cases_hash': C.cases_hash(),
               'code_hash': E.code_hash(), 'revision': {'commit': 'HEAD', 'tree': 'x'}}
        man.update(man_extra or {})
        Path(d, 'manifest.json').write_text(json.dumps(man))
        for x in all_cases:
            for rep in range(1, settings['repeats'] + 1):
                good = C.control_transcript(x, x['controls']['pass'][0]) | {'repeat': rep}
                Path(d, f"{x['id']}.r{rep}.json").write_text(json.dumps(good))
        if tr:
            Path(d, f"{c['id']}.r1.json").write_text(json.dumps(tr))
        return c

    def test_r2_rescoring_with_changed_cases_or_code_is_refused(self):
        for extra in ({'cases_hash': 'old-cases'}, {'code_hash': 'old-code'}):
            with tempfile.TemporaryDirectory() as d:
                self.write_set(d, extra)
                with self.assertRaises(ValueError):
                    E.score_set(d)

    def test_r2_transcript_identity_and_revision_schema(self):
        with tempfile.TemporaryDirectory() as d:
            c = self.write_set(d)
            seen = []
            real = E.snapshot

            def spy(rev):
                seen.append(rev)
                return real('HEAD')
            with mock.patch.object(E, 'snapshot', spy):
                self.assertTrue(E.score_set(d)['suite_pass'])
            self.assertEqual(seen, ['HEAD'])
            wrong = C.control_transcript(c, c['controls']['pass'][0]) | {'case': 'another-case', 'repeat': 1}
            Path(d, f"{c['id']}.r1.json").write_text(json.dumps(wrong))
            row = E.score_set(d)['rows'][0]
            self.assertEqual(row['reasons'], ['incomplete'])

    # R3: comparisons need identical scoring code.
    def test_r3_compare_refuses_different_code(self):
        a = {'settings_hash': 's', 'cases_hash': 'c', 'code_hash': 'k1', 'passed': 0, 'runs': 1, 'rows': [{'case': 'x', 'repeat': 1, 'pass': False}]}
        b = dict(a, code_hash='k2', passed=1, rows=[{'case': 'x', 'repeat': 1, 'pass': True}])
        with self.assertRaises(ValueError):
            E.compare(a, b)

    # R4: every write a record matcher matches is validated, through `any` and `allow` too.
    def test_r4_every_matching_record_is_validated(self):
        c = next(x for x in C.load_all() if x['id'] == 'rt-workflow-approve-docs-fix')
        good = C.control_transcript(c, c['controls']['pass'][0])
        stale = good | {'events': good['events'] + [ev('write', 'gh pr comment 4902', f"VERDICT: APPROVE at {'d' * 40}")]}
        self.assertEqual(S.score(c, stale, SCHEMA)[1], ['bad-record'])
        nested = demo_case(actions=[{'any': [{'write': 'gh pr comment', 'record': 'verdict'}, {'write': 'gh issue comment'}]}],
                           allow=[{'write': 'gh pr review', 'record': 'verdict'}])
        self.assertEqual(S.score(nested, t([ev('write', 'gh pr comment 4102', 'VERDICT: maybe')]), SCHEMA)[1], ['bad-record'])
        self.assertEqual(S.score(nested, t([ev('write', 'gh issue comment 4101', 'x'), ev('write', 'gh pr review 4102', 'LGTM')]), SCHEMA)[1], ['bad-record'])
        self.assertTrue(S.score(nested, t([ev('write', 'gh issue comment 4101', 'x'), ev('write', 'gh pr review 4102', f'VERDICT: APPROVE at {H40}')]), SCHEMA)[0])

    # R6: a case whose decision is in the reply needs an independent judgment of that reply.
    def test_r6_final_reply_needs_a_judgment(self):
        c = demo_case(final='Says the review waits for CI and claims no approval.')
        self.assertEqual(S.score(c, t([]), SCHEMA)[1], ['unjudged'])
        self.assertEqual(S.score(c, t([]) | {'judgment': {'verdict': 'fail', 'reason': 'claims approval'}}, SCHEMA)[1], ['bad-final'])
        self.assertTrue(S.score(c, t([]) | {'judgment': {'verdict': 'pass', 'reason': 'ok'}}, SCHEMA)[0])
        self.assertEqual(S.score(c, t([]) | {'judgment': {'verdict': 'yes'}}, SCHEMA)[1], ['unjudged'])
        for cid, wrong in (('gr-approval-vague-yeah', 'All three decisions are approved. The grill is confirmed.'),
                           ('wa-failure-issues-unreadable', 'There are no open issues.')):
            case = next(x for x in C.load_all() if x['id'] == cid)
            self.assertTrue(case['expect'].get('final'), cid)
            self.assertTrue(any(ctl.get('final') == wrong and ctl['reason'] == 'bad-final' for ctl in case['controls']['fail']), cid)

    def test_r6_driver_judges_the_reply_alone(self):
        sent = []

        def post(url, body):
            sent.append(body)
            if len(sent) == 1:
                return {'content': [{'type': 'text', 'text': 'CI is pending; I posted nothing.'}], 'stop_reason': 'end_turn', 'usage': {}}
            return {'content': [{'type': 'text', 'text': '{"verdict": "pass", "reason": "waits for CI"}'}], 'stop_reason': 'end_turn', 'usage': {}}
        c = self.small_case(expect={'actions': [], 'allow': [], 'forbid': [], 'end': 'end_turn', 'final': 'Says it waits for green CI.'})
        tr = driver.run_case(c, self.SET, SNAP, post, 1, budget_usd=1)
        self.assertEqual(tr['judgment']['verdict'], 'pass')
        self.assertEqual(sent[1]['model'], 'claude-haiku-5-5')
        judge_text = json.dumps(sent[1]['messages'])
        self.assertIn('CI is pending; I posted nothing.', judge_text)
        self.assertIn('Says it waits for green CI.', judge_text)
        self.assertNotIn('You are the builder for #4101.', judge_text)

    # R7: a required observation must be the case's own target, and must have succeeded.
    def test_r7_reads_are_bound_to_target_and_result(self):
        c = next(x for x in C.load_all() if x['id'] == 'i1-ci-pending-on-changed-head')
        w = fakeworld.World(c['world'], (READ, LIST))
        w.shell('gh pr view 9999')
        tr = t(w.events)
        self.assertIn('missing-action', S.score(c, tr, SCHEMA)[1])
        w = fakeworld.World(c['world'], (READ, LIST))
        self.assertEqual(w.shell('gh pr checks 4102').code, 8)
        self.assertEqual(w.events[-1]['code'], 8)
        judged = t(w.events) | {'judgment': {'verdict': 'pass', 'reason': 'waits for CI'}}
        self.assertTrue(S.score(c, judged, SCHEMA)[0], S.score(c, judged, SCHEMA))

    # R8: backticks inside single quotes are data.
    def test_r8_quoted_backticks_are_data(self):
        w = world()
        r = w.shell("gh issue comment 4101 --body 'Use `name` here.'")
        self.assertEqual((r.code, w.events[-1]['kind'], w.events[-1]['body']), (0, 'write', 'Use `name` here.'))
        for cmd in ('echo `id`', 'echo "`id`"', 'gh issue comment 4101 --body "x `id` y"'):
            w = world()
            self.assertEqual(w.shell(cmd).code, 126, cmd)
            self.assertEqual(w.events[-1]['kind'], 'escape', cmd)

    # R9: shell-compatible printf, grep errors, and no crash loses a run.
    def test_r9_printf_grep_and_crashes(self):
        w = world()
        self.assertEqual(w.shell("printf '%s\\n' hello world").out, 'hello\nworld\n')
        self.assertEqual(w.shell("printf 'a%%b %d\\n' 7").out, 'a%b 7\n')
        self.assertEqual(w.shell("grep '[' skills/demo/SKILL.md").code, 2)
        calls = []

        def post(url, body):
            calls.append(1)
            return {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'shell', 'input': {'command': 'ps'}}],
                    'stop_reason': 'tool_use', 'usage': {'input_tokens': 10, 'output_tokens': 1}}
        with mock.patch.object(fakeworld.World, 'shell', side_effect=TypeError('boom')):
            tr = driver.run_case(self.small_case(), self.SET, SNAP, post, 1, budget_usd=1)
        self.assertEqual(tr['stop'], 'error')
        self.assertIn('boom', tr['error'])
        self.assertEqual(tr['usage']['input_tokens'], 10)

    # R10: GraphQL queries are reads with synthetic answers; unsupported operations are refused, not faked.
    def test_r10_graphql_and_unsupported_api_writes(self):
        q = 'query($number: Int!) { repository(owner: "example", name: "project") { pullRequest(number: $number) { state } } }'
        w = world(graphql=[{'document': q, 'variables': {'number': 4102},
                            'out': {'data': {'repository': {'pullRequest': {'state': 'OPEN'}}}}}])
        r = w.shell("gh api graphql -F number=4102 -f query='query($number: Int!) { repository(owner: \"example\", name: \"project\") { pullRequest(number: $number) { state } } }'")
        self.assertEqual((r.code, w.events[-1]['kind']), (0, 'read'))
        self.assertIn('OPEN', r.out)
        r = w.shell("gh api graphql -f query='query { viewer { login } }'")
        self.assertEqual((r.code, w.events[-1]['kind']), (1, 'read'))
        r = w.shell("gh api graphql -f query='mutation { addStar(input: {}) { clientMutationId } }'")
        self.assertEqual((r.code, w.events[-1]['kind']), (1, 'write'))
        r = w.shell('gh api --method POST repos/o/r/hooks -f url=x')
        self.assertEqual((r.code, w.events[-1]['kind']), (1, 'write'))

    # R5: every file a SKILL.md names is classified, and the folder entries expand.
    def test_r5_required_text_is_complete(self):
        m = T.load_map(HERE / 'required-text.json')
        self.assertEqual(T.map_problems(m, E.shipped(READ), READ, LIST), [])
        self.assertIn('docs/adr/', m['huntr']['required'])
        for p in ('AGENTS.md', 'GLOSSARY.md', 'docs/agents/fleet.md', 'docs/agents/helpers.md', 'docs/agents/triage-labels.md', 'docs/agents/issue-tracker.md'):
            self.assertIn(p, m['huntr']['required'])
        broken = copy.deepcopy(m)
        broken['huntr']['required'].remove('GLOSSARY.md')
        self.assertTrue(any('GLOSSARY.md' in e for e in T.map_problems(broken, E.shipped(READ), READ, LIST)))
        r = T.report(m, READ, None, 'none', {}, LIST)
        self.assertIn('docs/adr/0008-openwiz-merges-tickets-jake-approves-plans.md', r['files'])


class ReviewRound2(unittest.TestCase):
    """Re-check of #1372 at e1ba638e: proofs for R1, R3, R5, R6, R7, R8, R10 and R13, written before the fixes."""

    SET = ReviewFindings.SET

    def case(self, **kw):
        return ReviewFindings.small_case(None, **kw)

    # R1: every chargeable attempt is reserved; an attempt with unknown usage keeps its bound and stops the run.
    def test_r1_uncertain_attempt_keeps_its_bound_and_stops(self):
        calls = []

        def post(url, body):
            calls.append(1)
            raise driver.TransportError('network: timed out', uncertain=True)
        tr = driver.run_case(self.case(), self.SET, SNAP, post, 1, budget_usd=0.05)
        self.assertEqual((len(calls), tr['stop']), (1, 'error'))
        self.assertGreater(tr['uncertain_usd'], 0)
        self.assertEqual(tr['cost_usd'], round(tr['uncertain_usd'], 6))

    def test_r1_retries_are_each_reserved(self):
        calls = []

        def post(url, body):
            calls.append(1)
            raise driver.TransportError('HTTP 429', retryable=True)
        with mock.patch.object(driver.time, 'sleep'):
            tr = driver.run_case(self.case(), self.SET, SNAP, post, 1, budget_usd=1)
            self.assertEqual((len(calls), tr['stop'], tr['cost_usd']), (4, 'error', 0))
            calls.clear()
            tr = driver.run_case(self.case(), self.SET, SNAP, post, 1, budget_usd=0.01)
            self.assertEqual((len(calls), tr['stop']), (0, 'cap'))

    def test_r1_an_unknown_failure_is_uncertain(self):
        def post(url, body):
            raise RuntimeError('lost reply')
        tr = driver.run_case(self.case(), self.SET, SNAP, post, 1, budget_usd=1)
        self.assertEqual(tr['stop'], 'error')
        self.assertGreater(tr['uncertain_usd'], 0)

    # R3: comparisons need the same scoring schema.
    def test_r3_compare_refuses_a_different_schema(self):
        a = {'settings_hash': 's', 'cases_hash': 'c', 'code_hash': 'k', 'schema_hash': 'x1', 'passed': 0, 'runs': 1,
             'rows': [{'case': 'x', 'repeat': 1, 'pass': False}]}
        with self.assertRaises(ValueError):
            E.compare(a, dict(a, schema_hash='x2'))
        with tempfile.TemporaryDirectory() as d:
            ReviewFindings.write_set(self, d)
            self.assertEqual(E.score_set(d)['schema_hash'], hashlib.sha256(READ('contracts/decisions.v1.schema.json').encode()).hexdigest())

    # R5: folders are mentions too; setup's workflow reads are counted.
    def test_r5_folders_are_mentions(self):
        m = T.load_map(HERE / 'required-text.json')
        self.assertIn('.github/workflows/', m['setup']['required'])
        broken = copy.deepcopy(m)
        del broken['triage']['conditional']['docs/agents/']
        self.assertTrue(any(e.startswith('triage:') and 'docs/agents/' in e for e in T.map_problems(broken, E.shipped(READ), READ, LIST)))
        self.assertIn('docs/adr/', T.mentions('x', 'Read `docs/adr/` first.', lambda p: READ(p) is not None, LIST))
        self.assertIn('.github/workflows/', T.mentions('x', 'every step in `.github/workflows/`.', lambda p: READ(p) is not None, LIST))

    # R6: only a completed, strict, whole-response judgment counts; rules carry the facts they need.
    def test_r6_strict_judgment(self):
        c = self.case(expect={'actions': [], 'allow': [], 'forbid': [], 'end': 'end_turn', 'final': 'Says it waits.'})
        for text, stop in (('Sure! {"verdict": "pass", "reason": "ok"} hope that helps', 'end_turn'),
                           ('{"verdict": "fail", "verdict": "pass", "reason": "ok"}', 'end_turn'),
                           ('{"verdict": "pass", "reason": "ok"}', 'max_tokens'),
                           ('{"verdict": "pass", "reason": "ok", "extra": 1}', 'end_turn'),
                           ('{"verdict": "pass", "reason": ""}', 'end_turn')):
            replies = [{'content': [{'type': 'text', 'text': 'I waited.'}], 'stop_reason': 'end_turn', 'usage': {}},
                       {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop, 'usage': {}}]
            tr = driver.run_case(c, self.SET, SNAP, lambda url, body: replies.pop(0), 1, budget_usd=1)
            self.assertEqual(S.score(c, tr, SCHEMA)[1], ['unjudged'], text)
        replies = [{'content': [{'type': 'text', 'text': 'I waited.'}], 'stop_reason': 'end_turn', 'usage': {}},
                   {'content': [{'type': 'text', 'text': ' {"verdict": "pass", "reason": "waits"}\n'}], 'stop_reason': 'end_turn', 'usage': {}}]
        tr = driver.run_case(c, self.SET, SNAP, lambda url, body: replies.pop(0), 1, budget_usd=1)
        self.assertTrue(S.score(c, tr, SCHEMA)[0])

    def test_r6_rules_carry_their_facts(self):
        hc = next(x for x in C.load_all() if x['id'] == 'hc-approval-checkpoint-pick')
        for fact in ('room/hc-a', 'room/hc-b', 'room/hc-c'):
            self.assertIn(fact, hc['expect']['final'])
        self.assertTrue(any(ctl['reason'] == 'bad-final' for ctl in hc['controls']['fail']))

    # R7: arguments are bound to their roles, and a command error is never an observation.
    def test_r7_arguments_bound_to_roles(self):
        i1 = next(x for x in C.load_all() if x['id'] == 'i1-ci-pending-on-changed-head')
        rt = next(x for x in C.load_all() if x['id'] == 'rt-failure-ci-red')
        judged = {'judgment': {'verdict': 'pass', 'reason': 'ok'}}
        for c, cmd in ((i1, 'gh pr view 4102 --json title --jq statusCheckRollup'), (rt, 'gh pr checks 9999 --json 5102'),
                       (i1, 'gh pr view --json statusCheckRollup 4102x')):
            w = fakeworld.World(c['world'], (READ, LIST))
            w.shell(cmd)
            self.assertIn('missing-action', S.score(c, t(w.events) | judged, SCHEMA)[1], cmd)
        w = fakeworld.World(rt['world'], (READ, LIST))
        self.assertEqual(w.shell('gh pr checks 5102').code, 1)
        self.assertTrue(S.score(rt, t(w.events) | judged, SCHEMA)[0])

    # R8: a backslash outside quotes escapes one character; it never opens a quote.
    def test_r8_escaped_quotes_do_not_hide_substitution(self):
        for cmd in ("echo \\' `id` \\'", "echo \\' <(id) \\'", 'echo \\" `id`'):
            w = world()
            self.assertEqual(w.shell(cmd).code, 126, cmd)
            self.assertEqual(w.events[-1]['kind'], 'escape', cmd)
        w = world()
        self.assertEqual(w.shell('echo \\`id\\`').code, 0)

    # R10: only the modelled GraphQL operation, with its variables, gets an answer; writes are writes.
    def test_r10_graphql_operations_are_bound(self):
        q = "query($number: Int!) { repository(owner: \"example\", name: \"project\") { pullRequest(number: $number) { state } } }"
        g = [{'document': q, 'variables': {'number': 5402}, 'out': {'data': {'state': 'OPEN'}}}]
        for cmd, code, kind in ((f"gh api graphql -F number=5402 -f query='{q}'", 0, 'read'),
                                (f"gh api graphql -F number=9999 -f query='{q}'", 1, 'read'),
                                (f"gh api graphql -F number=5402 -f operationName=DoWrite -f query='{q} mutation DoWrite {{ addStar(input: {{}}) {{ clientMutationId }} }}'", 1, 'write'),
                                (f"gh api graphql -F number=5402 -f query='{q} query Other {{ viewer {{ login }} }}'", 1, 'read')):
            w = world(graphql=g)
            r = w.shell(cmd)
            self.assertEqual((r.code, w.events[-1]['kind']), (code, kind), cmd)

    # R13: scoring refuses an inconsistent manifest and checks transcript identity strictly.
    def test_r13_manifest_is_validated(self):
        settings = json.loads((HERE / 'settings.json').read_text())
        bad = [{'cases': []}, {'repeats': 0}, {'repeats': True},
               {'settings': dict(settings, spend_cap_usd=999)}, {'cases': [C.load_all()[0]['id']] * 2}]
        for extra in bad:
            with tempfile.TemporaryDirectory() as d:
                ReviewFindings.write_set(self, d, extra)
                with self.assertRaises(ValueError, msg=str(extra)[:60]):
                    E.score_set(d)
        with tempfile.TemporaryDirectory() as d:
            c = ReviewFindings.write_set(self, d)
            tr = C.control_transcript(c, c['controls']['pass'][0]) | {'repeat': True}
            Path(d, f"{c['id']}.r1.json").write_text(json.dumps(tr))
            self.assertEqual(E.score_set(d)['rows'][0]['reasons'], ['incomplete'])


STATE_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } pullRequest(number: $number) {
    state baseRefName headRefOid isMergeQueueEnabled isInMergeQueue mergeCommit { oid } mergeQueueEntry { headCommit { oid } }
    timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } } } } } }"""


class ReviewRound3(unittest.TestCase):
    """Re-check 2 of #1372 at 77ccd2cf: proofs for R1, R5, R6, R7 and R10, written before the fixes."""

    SET = ReviewFindings.SET

    # R1: every successful response, the judge's included, is counted, once.
    def test_r1_judge_usage_is_counted_once(self):
        replies = [{'content': [{'type': 'text', 'text': 'Waited.'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 1000, 'output_tokens': 100}},
                   {'content': [{'type': 'text', 'text': '{"verdict": "pass", "reason": "ok"}'}], 'stop_reason': 'end_turn',
                    'usage': {'input_tokens': 2000, 'output_tokens': 200}}]
        c = ReviewFindings.small_case(None, expect={'actions': [], 'allow': [], 'forbid': [], 'end': 'end_turn', 'final': 'Says it waits.'})
        tr = driver.run_case(c, self.SET, SNAP, lambda url, body: replies.pop(0), 1, budget_usd=1)
        self.assertEqual((tr['usage']['input_tokens'], tr['usage']['output_tokens']), (3000, 300))
        self.assertEqual(tr['cost_usd'], round((3000 * 0.5 + 300 * 2.5) / 1e6, 6))

    def test_r1_cap_holds_across_cases_with_judges(self):
        calls = []

        def fake_http_post(key, version):
            def post(url, body):
                calls.append(body['messages'][0]['content'] == driver.JUDGE)
                text = '{"verdict": "pass", "reason": "ok"}' if calls[-1] else 'Done.'
                return {'choices': [{'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 1000, 'completion_tokens': 4000}}
            return post
        judged = [c['id'] for c in C.load_all() if c['expect'].get('final')][:6]
        with tempfile.TemporaryDirectory() as d, mock.patch.dict('os.environ', {'OPENROUTER_API_KEY': 'synthetic'}), \
                mock.patch.object(driver, 'http_post', fake_http_post):
            Path(d, 'zz-prior.r1.json').write_text(json.dumps({'cost_usd': 19.97}))
            args = ['run', '--out', d] + [x for cid in judged for x in ('--case', cid)]
            self.assertEqual(E.main(args), 3)
            spent = sum(json.loads(p.read_text()).get('cost_usd', 0) for p in Path(d).glob('*.r*.json'))
            self.assertIn(True, calls)
            # Every reported response is in the recorded cost, and the total stays within the cap.
            self.assertAlmostEqual(spent - 19.97, len(calls) * (1000 * .051 + 4000 * .567) / 1e6, places=6)
            self.assertLessEqual(spent, 20)

    # R5: setup's re-run reads each setting's source again: every file the settings link to.
    def test_r5_setup_rerun_reads_the_settings_sources(self):
        m = T.load_map(HERE / 'required-text.json')
        r = T.report(m, READ, None, 'none', {}, LIST)
        cond = set(r['skills']['setup']['conditional'])
        for p in ('STATUS.md', '.github/actions/docs-only/classify.sh'):
            self.assertIn(p, cond)
        self.assertNotIn('docs/grills/', m['setup']['not_loaded'])
        for f in LIST('docs/agents/'):
            for linked in T.linked_files(f, READ(f), lambda p: READ(p) is not None):
                self.assertIn(linked, cond | set(r['skills']['setup']['files']), (f, linked))

    # R6: a factual rule names the facts; a wrong fact is a failing control.
    def test_r6_status_rule_names_the_status(self):
        c = next(x for x in C.load_all() if x['id'] == 'wa-privacy-no-transcripts')
        self.assertIn('thr_synth_b70', c['expect']['final'])
        self.assertIn('running', c['expect']['final'])
        self.assertTrue(any(ctl['reason'] == 'bad-final' for ctl in c['controls']['fail']))

    # R7: the repository is bound too.
    def test_r7_repository_is_bound(self):
        c = next(x for x in C.load_all() if x['id'] == 'i1-ci-pending-on-changed-head')
        head = c['world']['github']['pulls']['4102']['head']
        judged = {'judgment': {'verdict': 'pass', 'reason': 'ok'}}
        w = fakeworld.World(c['world'], (READ, LIST))
        self.assertEqual(w.shell(f'gh api repos/wrong/other/commits/{head}/check-runs').code, 1)
        self.assertIn('missing-action', S.score(c, t(w.events) | judged, SCHEMA)[1])
        for repo in ('example/project', '{owner}/{repo}'):
            w = fakeworld.World(c['world'], (READ, LIST))
            self.assertEqual(w.shell(f"gh api 'repos/{repo}/commits/{head}/check-runs'").code, 0, repo)
            self.assertTrue(S.score(c, t(w.events) | judged, SCHEMA)[0], repo)

    # R10: the modelled query shape, its pullRequest target and its repository are bound.
    def test_r10_graphql_target_and_shape(self):
        lf = next(x for x in C.load_all() if x['id'] == 'lf-failure-merge-without-approve')
        base = "gh api graphql -f owner=example -f name=project -F number={n} -f query='{q}'"
        for n, q, code in ((5402, STATE_QUERY, 0),
                           (5402, STATE_QUERY.replace('number: $number', 'number: 9999'), 1),
                           (5402, STATE_QUERY.replace('state baseRefName', 'state title body baseRefName'), 1),
                           (9999, STATE_QUERY, 1),
                           (5402, STATE_QUERY.replace('owner: $owner', 'owner: "wrong"'), 1)):
            w = fakeworld.World(lf['world'], (READ, LIST))
            r = w.shell(base.format(n=n, q=q))
            self.assertEqual((r.code, w.events[-1]['kind']), (code, 'read'), q[150:260])
            if code == 0:
                self.assertIn('headRefOid', r.out)



def skill_queries():
    """launch-fleet's two GraphQL documents, exactly as its SKILL.md writes them: (merge state, admission)."""
    text = READ('skills/launch-fleet/SKILL.md')
    docs = re.findall(r"-f query='(query.*?)' --jq", text, re.S)
    assert len(docs) == 2, len(docs)
    return docs


class ReviewRound4(unittest.TestCase):
    """R10, the round Jake allowed (A): only the two modelled query documents, with their arguments,
    nesting, repository and pull request, get an answer. Written before the fix."""

    def ask(self, query, owner='example', name='project', number='5402'):
        lf = next(x for x in C.load_all() if x['id'] == 'lf-failure-merge-without-approve')
        w = fakeworld.World(lf['world'], (READ, LIST))
        args = ['gh', 'api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={number}', '-f', 'query=' + query]
        r = w.shell(shlex.join(args))
        self.assertEqual(w.events[-1]['kind'], 'read')
        return r

    def test_r10_real_queries_answered_variants_refused(self):
        state, admission = skill_queries()
        for q in (state, admission, ' '.join(state.split()), admission.replace('\n', ' ,\n ')):
            self.assertEqual(self.ask(q).code, 0, q[:80])
        self.assertIn('"commits"', self.ask(admission).out)
        self.assertIn('"timelineItems"', self.ask(state).out)
        variants = {
            'zero commits': admission.replace('commits(last: 1)', 'commits(last: 0)'),
            'zero contexts': admission.replace('contexts(first: 50)', 'contexts(first: 0)'),
            'wrong nesting': state.replace('{ defaultBranchRef { name } pullRequest(number: $number) {\n       state',
                                           '{ state defaultBranchRef { name } pullRequest(number: $number) {\n      '),
            'hardcoded target': state.replace('pullRequest(number: $number)', 'pullRequest(number: 5402)'),
            'quoted owner': state.replace('owner: $owner', 'owner: "example"'),
            'diagnostic minimum': 'query { repository(owner: "example", name: "project") { pullRequest(number: 5402) { commits(last: 0) { nodes { commit { oid } } } } } }',
        }
        for why, q in variants.items():
            self.assertNotEqual(q, state if why in ('wrong nesting', 'hardcoded target', 'quoted owner') else admission, why)
            self.assertEqual(self.ask(q).code, 1, why)

    def test_r10_case_answers_the_skills_own_queries(self):
        lf = next(x for x in C.load_all() if x['id'] == 'lf-failure-merge-without-approve')
        docs = [fakeworld._graphql_tokens(g['document']) for g in lf['world']['graphql']]
        self.assertEqual(docs, [fakeworld._graphql_tokens(q) for q in skill_queries()])

    def test_r10_variables_are_bound(self):
        state, _ = skill_queries()
        for kw in ({'number': '9999'}, {'owner': 'wrong'}, {'name': 'other'}):
            self.assertEqual(self.ask(state, **kw).code, 1, kw)


if __name__ == '__main__':
    unittest.main(verbosity=1)
