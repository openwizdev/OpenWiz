#!/usr/bin/env python3
"""The onboarding journey (#1108, IF8 and IF9's explanation slice), on fixtures only.

Replays journeys/first-fleet.json, a recorded synthetic conversation, against
the packaged skill: its step order comes from skills/onboard/SKILL.md, and each
tool step runs the packaged helper skills/onboard/scripts/onboard.py. The
helper reads launch-fleet's real frontier (skills/launch-fleet/scripts/fleet.sh,
with plan-graph's real revision.sh) from launch-fleet's fake gh, and drives a
recording fake openwiz (fake_openwiz.py) for the engine's tick and the fleet
view, as contracts/cli.v1.md defines those forms. No live call is possible:
the fakes refuse everything else. Fixtures prove the onboarding's gating and
its single start, never live behaviour.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SKILL = ROOT / 'skills/onboard/SKILL.md'
HELPER = ROOT / 'skills/onboard/scripts/onboard.py'
FAKE_GH = HERE / 'fake_gh.py'
REVISION = ROOT / 'skills/plan-graph/revision.sh'
JOURNEY = json.loads((HERE / 'journeys/first-fleet.json').read_text())
NOW = 1793534400  # 2026-11-01T12:00:00Z, the synthetic clock fleet.sh reads

FILES = {
    'docs/agents/fleet.md': (
        '# Fleet settings\n\nSynthetic settings.\n\n## CI checks\n\n'
        '| Check | Runs | Required on |\n| --- | --- | --- |\n| `build` | 1 | `main` |\n\n'
        'Source: synthetic.\n\n## Standing merge rules\n\n'
        '| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| `not-a-check` | none | synthetic |\n'),
    'docs/agents/triage-labels.md': (
        '# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
        '| `needs-triage` | `needs-triage` | Synthetic |\n| `needs-info` | `needs-info` | Synthetic |\n'
        '| `ready-for-agent` | `ready-for-agent` | Synthetic |\n| `ready-for-human` | `ready-for-human` | Synthetic |\n'
        '| `wontfix` | `wontfix` | Synthetic |\n'),
}


def skill_steps():
    """The journey's step names, in order, from the packaged skill's numbered sections."""
    names = re.findall(r'^## [0-9]+\. (.+)$', SKILL.read_text(), re.M)
    return [name.split()[-1].lower() for name in names]


def answers(turns):
    out = {}
    for turn in turns:
        out.update(turn.get('answers', {}))
    return out


class Journey:
    """One replay: a private folder with its state, fakes and synthetic GitHub."""

    def __init__(self, case):
        self.dir = Path(tempfile.mkdtemp(prefix='onboard-'))
        case.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / 'bin').mkdir()
        (self.dir / 'private').mkdir(mode=0o700)
        self.state = self.dir / 'private/onboard.json'
        self.options = self.dir / 'private/models.json'
        self.options.write_text(json.dumps(JOURNEY['options']))
        self.world_path = self.dir / 'world.json'
        self.script = self.dir / 'openwiz-script.json'
        self.log = self.dir / 'openwiz.log'
        self.openwiz = self.dir / 'bin/openwiz'
        self.openwiz.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, HERE / 'fake_openwiz.py'))
        gh = self.dir / 'bin/gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I -S "%s" "$@"\n' % (sys.executable, FAKE_GH))
        self.repos = self.dir / 'repos.json'
        self.repos.write_text(json.dumps({'repos': {}, 'create': 'ok'}))
        self.created_log = self.dir / 'gh-create.log'
        for path in (self.openwiz, gh):
            path.chmod(0o755)
        self.world = {'repo': JOURNEY['repo'], 'default': 'main', 'files': FILES, 'issues': [], 'pulls': []}
        self.save_world()
        self.settings = {k: answers(JOURNEY['turns'])[k] for k in ('harness', 'model', 'effort')}
        self.approval = None
        self.calls = []

    def env(self):
        env = {k: v for k, v in os.environ.items() if k in ('HOME', 'LANG', 'LC_ALL', 'TMPDIR')}
        env.update(PATH='%s:/usr/bin:/bin' % (self.dir / 'bin'), GH_REPO=self.world['repo'],
                   FAKE_GH_WORLD=str(self.world_path), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   LAUNCH_FLEET_NOW=str(NOW), LAUNCH_FLEET_CACHE=str(self.dir / 'cache'),
                   FAKE_OPENWIZ_SCRIPT=str(self.script), FAKE_OPENWIZ_LOG=str(self.log),
                   FAKE_GH_REPOS=str(self.repos), FAKE_GH_CREATE_LOG=str(self.created_log))
        return env

    def save_world(self):
        self.world_path.write_text(json.dumps(self.world))

    def plan(self, plan):
        spec = plan['spec']
        self.spec = spec['number']
        self.tickets = plan['tickets']
        self.world['issues'] = [{'number': spec['number'], 'title': spec['title'], 'state': 'OPEN', 'parent': None,
                                 'labels': [], 'body': spec['body'], 'comments': []}]
        for t in plan['tickets']:
            self.world['issues'].append({
                'number': t['number'], 'title': t['title'], 'state': 'OPEN', 'parent': spec['number'],
                'labels': ['ready-for-agent'], 'blockedBy': t['blockers'],
                'body': '## What to build\n\n%s.\n' % t['title'], 'comments': []})
        self.save_world()

    def approve(self):
        """plan-graph's approval record, with the fingerprint revision.sh gives the plan now."""
        out = subprocess.run(['sh', str(REVISION), str(self.spec)], env=self.env(), capture_output=True, check=True)
        fingerprint = hashlib.sha256(out.stdout).hexdigest()
        rows = '\n'.join('| #%d | %s | %s | ready-for-agent |' % (
            t['number'], t['title'], ', '.join('#%d' % b for b in t['blockers']) or 'none') for t in self.tickets)
        body = ('**Plan graph approved by Robin, 2026-11-01, revision 1:** approved the synthetic plan.\n'
                'Private record: https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-1\n\n'
                '| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n%s\n\nFingerprint: `%s`' % (rows, fingerprint))
        self.world['issues'][0]['comments'].append({'id': 90001, 'at': '2026-11-01T10:00:00Z', 'body': body})
        self.approval = {'comment': 90001, 'revision': 1, 'fingerprint': fingerprint}
        self.save_world()

    def title(self, n):
        return next(t['title'] for t in self.tickets if t['number'] == n)

    def rules(self, small=None, reviewer=None):
        """The rules object a dry run carries: the fleet settings setup wrote from the user's choice."""
        other = {'harness': 'claude-code', 'model': 'syn-claude-model-01', 'effort': 'high'}
        return {'builder': self.settings, 'builder_small': small or self.settings,
                'reviewer_claude': {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high'},
                'reviewer_gpt': reviewer or other,
                'ci_checks': [{'name': 'build', 'required_on': ['main']}], 'merge': 'adr_0008'}

    def tick_plan(self, numbers, settings=None, extra=(), rules=None):
        actions = [{'kind': 'start_builder', 'rule': 'frontier', 'spec': self.spec, 'ticket': n,
                    'facts': {'settings': settings or self.settings, 'title': self.title(n),
                              'approval': self.approval or {'comment': 1, 'revision': 1, 'fingerprint': '0' * 64},
                              'labels': ['ready-for-agent'], 'blockers': [], 'retry_after': None},
                    'outcome': {'state': 'planned'}} for n in numbers]
        return {'schema': 'openwiz.fleet-tick.v1', 'mode': 'dry_run', 'planned_at': NOW * 1000,
                'default_branch': 'main', 'rules': rules or self.rules(), 'actions': actions + list(extra)}

    @staticmethod
    def tick_run(plan, state):
        run = copy.deepcopy(plan)
        run['mode'] = 'run'
        for action in run['actions']:
            action['outcome'] = {'state': state} if state == 'done' else {'state': state, 'reason': 'synthetic'}
        return run

    def fleet_view(self, states):
        counts = {k: 0 for k in ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')}
        for s in states:
            counts[s] += 1
        counts.update(tickets=len(states), unknown=0)
        return {'schema': 'openwiz.fleet.v1', 'sources': {}, 'reads': [], 'coverage': {}, 'freshness': {},
                'data': {'view': 'fleet', 'repository': 'r0', 'projects': 'r1', 'threads': 'r2',
                         'fleet': {'spec': self.spec, 'issue': 'r3', 'tickets': 'r4', 'progress': {'known': counts}},
                         'tickets': [{'number': t['number'], 'state': {'known': s}} for t, s in zip(self.tickets, states)],
                         'blockers': [], 'needs_you': {'known': []}, 'unplaced': {'known': []}}}

    def queue(self, script):
        self.script.write_text(json.dumps(script))

    def helper(self, args):
        argv = [sys.executable, '-I', str(HELPER), *args, '--state', str(self.state)]
        if args[0] == 'choose':
            argv += ['--options', str(self.options)]
        if args[0] in ('launch', 'progress'):
            argv += ['--openwiz', str(self.openwiz)]
        result = subprocess.run(argv, env=self.env(), capture_output=True, text=True, cwd=self.dir, timeout=120)
        self.calls.append((args, result))
        return result

    def gh_creates(self):
        """The creation and read-back calls, as the fake gh logged them."""
        if not self.created_log.exists():
            return []
        return [json.loads(line)[:2] for line in self.created_log.read_text().splitlines()]

    def logged(self, form=None):
        if not self.log.exists():
            return []
        lines = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [line for line in lines if form is None or line['form'] == form]

    def confirmation(self):
        """The confirmation the latest preview printed: what the user said yes to."""
        for args, result in reversed(self.calls):
            found = re.findall(r'^Confirmation: ([0-9a-f]{64})$', result.stdout, re.M)
            if found:
                return found[-1]
        return '0' * 64

    def tool(self, turn, script=None):
        """Run one recorded tool step, answering the fake openwiz as the turn records."""
        turn = dict(turn, tool=[self.confirmation() if a == '@preview' else a for a in turn['tool']])
        if script is None:
            script = {}
            if 'tick_plan' in turn:
                plan = self.tick_plan(turn['tick_plan'])
                script['fleet.tick.preview'] = [{'exit': 0, 'stdout': plan}]
                if 'tick_run' in turn:
                    script['fleet.tick'] = [{'exit': 0, 'stdout': self.tick_run(plan, turn['tick_run'])}]
            if 'progress' in turn:
                script['fleet'] = [{'exit': 0, 'stdout': self.fleet_view(turn['progress'])}]
        self.queue(script)
        return self.helper(turn['tool'])

    def replay(self, until=None):
        """Every turn of the recorded journey, in order, up to step `until` (exclusive)."""
        results = []
        for turn in JOURNEY['turns']:
            if until is not None and turn['step'] == until:
                break
            if 'plan' in turn:
                self.plan(turn['plan'])
            elif turn.get('approve'):
                self.approve()
            elif 'tool' in turn:
                results.append((turn, self.tool(turn)))
        return results


def launch_yes():
    return next(t for t in JOURNEY['turns'] if t.get('tool', [None])[0] == 'launch' and '--yes' in t['tool'])


class RecordedJourney(unittest.TestCase):
    def test_the_conversation_follows_the_packaged_skill(self):
        steps = skill_steps()
        self.assertEqual(steps, ['explain', 'project', 'grill', 'agents', 'plan', 'launch', 'watch'])
        seen = [turn['step'] for turn in JOURNEY['turns']]
        self.assertEqual(sorted(set(seen), key=steps.index), steps, 'every step, and only the skill\'s')
        self.assertEqual(seen, sorted(seen, key=steps.index), 'in the skill\'s order')

    def test_every_effect_follows_its_yes_and_every_choice_is_the_users(self):
        turns = JOURNEY['turns']
        permitted = set()
        for i, turn in enumerate(turns):
            permitted |= set(turn.get('permits', []))
            if turn.get('tool', [None])[0] == 'create-repo' and '--yes' in turn['tool']:
                self.assertIn('create_repository', permitted, 'repository created only after a yes')
            if turn.get('tool', [None])[:2] == ['launch', '--spec'] and '--yes' in turn['tool']:
                self.assertIn('start_cloud_agents', permitted, 'agents start only after a yes')
            if turn.get('tool', [None])[0] == 'choose':
                said = answers(turns[:i])
                flags = dict(zip(turn['tool'][1::2], turn['tool'][2::2]))
                self.assertEqual({k[2:]: v for k, v in flags.items()}, said, 'each choice is exactly the user\'s answer')
                self.assertNotEqual(flags['--agents'], None)
        self.assertEqual(answers(turns)['agents'], 'cloud')
        self.assertEqual(JOURNEY['engine_location'], 'local', 'agent location is chosen apart from the engine')

    def test_the_plan_is_this_grills_small_first_fleet(self):
        plan = next(t['plan'] for t in JOURNEY['turns'] if 'plan' in t)
        self.assertTrue(4 <= len(plan['tickets']) <= 7)
        start = [t['number'] for t in plan['tickets'] if not t['blockers']]
        self.assertGreaterEqual(len(start), 2, 'several start at once')
        # No prewritten plan ships with the skill: none of this plan's titles,
        # and no ticket table, appear anywhere in the packaged skill folder.
        packaged = ''.join(p.read_text() for p in (ROOT / 'skills/onboard').rglob('*') if p.is_file())
        for ticket in plan['tickets']:
            self.assertNotIn(ticket['title'].split(': ', 1)[1], packaged)
        self.assertNotIn('| Ticket |', packaged)


class Launch(unittest.TestCase):
    def test_the_whole_journey_starts_only_the_approved_frontier_once(self):
        j = Journey(self)
        results = j.replay()
        for turn, result in results:
            self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
        runs = j.logged('fleet.tick')
        self.assertEqual(len(runs), 1, 'one execution')
        previews = j.logged('fleet.tick.preview')
        self.assertEqual(len(previews), 2, 'the preview, then the reviewed plan again before the yes runs it')
        reviewed = j.tick_plan([901, 902, 903])
        self.assertEqual(runs[0]['plan_sha256'], hashlib.sha256((json.dumps(reviewed) + '\n').encode()).hexdigest(),
                         'the executed plan is exactly the reviewed one')
        preview_out = next(r for turn, r in results if turn['tool'] == ['launch', '--spec', '900']).stdout
        for line in ('start 3 builders', '#901 S1: the field and its sheep', 'codex syn-codex-model-01 high', 'Cloud'):
            self.assertIn(line, preview_out)
        watch = results[-1][1].stdout
        for line in ('#901 building', '#904 blocked', '#905 blocked', '5 tickets: 3 building, 2 blocked'):
            self.assertIn(line, watch)
        mode = stat.S_IMODE(j.state.stat().st_mode)
        self.assertEqual(mode, 0o600, 'owner-only state')

    def test_repeat_and_reload_never_start_again(self):
        j = Journey(self)
        j.replay()
        before = len(j.logged())
        again = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'progress': ['building'] * 3 + ['blocked'] * 2})
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('already started', again.stdout)
        new = j.logged()[before:]
        self.assertEqual([c['form'] for c in new], ['fleet'], 'only a progress read')

    def test_missing_approval_starts_nothing_even_if_the_planner_disagrees(self):
        j = Journey(self)
        j.replay(until='launch')
        j.world['issues'][0]['comments'] = []
        j.save_world()
        for plan in ([], [901, 902, 903]):
            result = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'tick_plan': plan})
            self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
            self.assertIn('nothing started', result.stdout)
        self.assertEqual(j.logged('fleet.tick'), [])

    def test_stale_approval_starts_nothing(self):
        j = Journey(self)
        j.replay(until='launch')
        j.world['issues'][3]['body'] += 'A changed body.\n'
        j.save_world()
        result = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'tick_plan': [901, 902, 903]})
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertEqual(j.logged('fleet.tick'), [])

    def test_an_uncertain_start_is_never_retried(self):
        for make in (lambda j, plan: {'exit': 1, 'stdout': ''},
                     lambda j, plan: {'exit': 0, 'stdout': j.tick_run(plan, 'uncertain')}):
            j2 = Journey(self)
            j2.replay(until='launch')
            plan = j2.tick_plan([901, 902, 903])
            script = {'fleet.tick.preview': [{'exit': 0, 'stdout': plan}], 'fleet.tick': [make(j2, plan)]}
            self.assertEqual(j2.tool({'tool': ['launch', '--spec', '900'], 'tick_plan': [901, 902, 903]}).returncode, 12)
            first = j2.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']}, script)
            self.assertEqual(first.returncode, 6, first.stdout + first.stderr)
            self.assertIn('uncertain', first.stdout)
            second = j2.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'progress': ['building'] * 5})
            self.assertEqual(second.returncode, 6, second.stdout + second.stderr)
            self.assertEqual(len(j2.logged('fleet.tick')), 1, 'never a second execution')

    def test_a_refused_reviewed_plan_changed_nothing_and_may_be_previewed_again(self):
        j = Journey(self)
        j.replay(until='launch')
        plan = j.tick_plan([901, 902, 903])
        self.assertEqual(j.tool({'tool': ['launch', '--spec', '900'], 'tick_plan': [901, 902, 903]}).returncode, 12)
        refusal = {'schema': 'openwiz.cli-error.v1', 'command': 'fleet', 'exit_code': 1,
                   'error': {'kind': 'read_failed', 'message': 'The reviewed plan no longer matches.'}}
        first = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']},
                       {'fleet.tick.preview': [{'exit': 0, 'stdout': plan}], 'fleet.tick': [{'exit': 1, 'stdout': refusal}]})
        self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
        self.assertEqual(j.tool({'tool': ['launch', '--spec', '900'], 'tick_plan': [901, 902, 903]}).returncode, 12)
        second = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'tick_plan': [901, 902, 903], 'tick_run': 'done',
                         'progress': ['building'] * 3 + ['blocked'] * 2})
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(len(j.logged('fleet.tick')), 2)

    def test_the_plan_must_be_exactly_this_specs_frontier_with_the_users_settings(self):
        other = {'kind': 'merge', 'rule': 'adr_0008', 'spec': 950, 'ticket': 951, 'facts': {}, 'outcome': {'state': 'planned'}}
        for name, make in (
                ('a ticket off the frontier', lambda j: j.tick_plan([901, 902, 903, 904])),
                ('a frontier ticket missing', lambda j: j.tick_plan([901, 902])),
                ('another action', lambda j: j.tick_plan([901, 902, 903], extra=[other])),
                ('other settings', lambda j: j.tick_plan([901, 902, 903], settings={'harness': 'claude-code', 'model': 'syn-claude-model-01', 'effort': 'high'})),
                ('a repeated start', lambda j: j.tick_plan([901, 901, 902, 903]))):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                result = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']},
                                {'fleet.tick.preview': [{'exit': 0, 'stdout': make(j)}]})
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertEqual(j.logged('fleet.tick'), [])

    def test_local_agents_and_other_specs_start_nothing(self):
        j = Journey(self)
        j.replay(until='launch')
        result = j.helper(['choose', '--harness', 'codex', '--model', 'syn-codex-model-01', '--effort', 'high', '--agents', 'local'])
        self.assertEqual(result.returncode, 0, result.stderr)
        local = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']}, {})
        self.assertEqual(local.returncode, 5, local.stdout + local.stderr)
        self.assertIn('Local', local.stdout)
        k = Journey(self)
        k.replay(until='launch')
        other = k.tool({'tool': ['launch', '--spec', '950', '--yes', '--confirm', '@preview']}, {})
        self.assertEqual(other.returncode, 5, other.stdout + other.stderr)
        self.assertEqual(j.logged() + k.logged(), [], 'not even a read of the engine')

    def test_no_choice_no_launch_and_only_offered_choices(self):
        j = Journey(self)
        j.plan(next(t['plan'] for t in JOURNEY['turns'] if 'plan' in t))
        j.approve()
        self.assertEqual(j.helper(['spec', '--spec', '900', '--repo', JOURNEY['repo']]).returncode, 0)
        self.assertEqual(j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']}, {}).returncode, 5)
        base = ['choose', '--harness', 'codex', '--model', 'syn-codex-model-01', '--effort', 'high', '--agents', 'cloud']
        for bad, code in ((base[:-2], 2), (base[:6] + ['xhigh'] + base[7:], 5), (base[:4] + ['syn-unknown'] + base[5:], 5),
                          (base[:-1] + ['moon'], 2), (base + ['--agents', 'cloud'], 2)):
            with self.subTest(bad):
                self.assertEqual(j.helper(bad).returncode, code)
        self.assertEqual(j.logged(), [])

    def test_the_yes_binds_the_preview_the_user_saw(self):
        # R1: the user said yes to two starts; a third ticket becoming ready
        # before the yes runs must not start without a new preview and yes.
        j = Journey(self)
        j.replay(until='launch')
        j.world['issues'][1]['labels'] = ['ready-for-agent', 'held']
        j.save_world()
        shown = j.tool({'tool': ['launch', '--spec', '900'], 'tick_plan': [902, 903]})
        self.assertEqual(shown.returncode, 12, shown.stdout)
        self.assertIn('start 2 builders', shown.stdout)
        j.world['issues'][1]['labels'] = ['ready-for-agent']
        j.save_world()
        shutil.rmtree(j.dir / 'cache', ignore_errors=True)
        changed = {'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'tick_plan': [901, 902, 903],
                   'tick_run': 'done', 'progress': ['building'] * 3 + ['blocked'] * 2}
        result = j.tool(changed)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn('preview again', result.stdout)
        self.assertEqual(j.logged('fleet.tick'), [], 'no execution of effects the user never saw')
        bare = j.tool(dict(changed, tool=['launch', '--spec', '900', '--yes']))
        self.assertEqual(bare.returncode, 2, 'a yes names the preview it answers')
        self.assertEqual(j.logged('fleet.tick'), [])
        again = j.tool({'tool': ['launch', '--spec', '900'], 'tick_plan': [901, 902, 903]})
        self.assertEqual(again.returncode, 12)
        self.assertEqual(j.tool(changed).returncode, 0)
        self.assertEqual(len(j.logged('fleet.tick')), 1)

    def test_another_repository_never_runs_this_onboardings_launch(self):
        # R3: the same state and issue numbers, resumed in another repository.
        j = Journey(self)
        j.replay(until='launch')
        j.world['repo'] = 'synthetic-owner/synthetic-other'
        j.save_world()
        for turn in ({'tool': ['launch', '--spec', '900'], 'tick_plan': [901, 902, 903]},
                     {'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'tick_plan': [901, 902, 903],
                      'tick_run': 'done', 'progress': ['building'] * 5},
                     {'tool': ['progress', '--spec', '900'], 'progress': ['building'] * 5}):
            result = j.tool(turn)
            self.assertEqual(result.returncode, 5, (turn['tool'], result.stdout + result.stderr))
            self.assertIn('synthetic-owner/synthetic-sheep', result.stdout)
        self.assertEqual(j.logged(), [], 'not even a read of the engine')

    def test_every_builder_profile_the_fleet_can_use_is_the_users_choice(self):
        # R4: blocked tickets may later use the small-ticket builder; the
        # reviewer stays in the other model family.
        claude = {'harness': 'claude-code', 'model': 'syn-claude-model-01', 'effort': 'high'}
        codex = {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high'}
        for name, rules in (('small builder differs', lambda j: j.rules(small=claude)),
                            ('reviewer in the same family', lambda j: j.rules(reviewer=codex) | {'reviewer_gpt': codex}),
                            ('rules missing', lambda j: {})):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                plan = j.tick_plan([901, 902, 903])
                plan['rules'] = rules(j)
                result = j.tool({'tool': ['launch', '--spec', '900']}, {'fleet.tick.preview': [{'exit': 0, 'stdout': plan}]})
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertNotIn('Confirmation:', result.stdout)

    def test_the_demo_repository_is_created_once_and_read_back(self):
        j = Journey(self)
        j.replay(until='grill')
        self.assertEqual(j.gh_creates(), [['repo', 'view'], ['repo', 'create'], ['repo', 'view']],
                         'checked absent, created once, read back')
        self.assertEqual(json.loads(j.repos.read_text())['repos'], {JOURNEY['repo']: {'private': True}})
        preview = next(r for a, r in j.calls if a[0] == 'create-repo' and '--yes' not in a)
        for words in ('private', JOURNEY['repo'], 'your gh identity'):
            self.assertIn(words, preview.stdout)
        again = j.helper(['create-repo', '--repo', JOURNEY['repo'], '--yes'])
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'a repeat only reads')

    def test_a_lost_create_is_read_before_any_retry(self):
        # lost: created but no answer, settled by the read-back; unread: the
        # read-back itself fails, so it stays uncertain and the next run reads
        # first; fail: nothing was created, so a later yes may create it.
        for create, fails, first, second, creates in (('lost', 0, 0, 0, 1), ('lost', 2, 6, 6, 1), ('fail', 0, 5, 0, 2)):
            with self.subTest(create, fails=fails):
                j = Journey(self)
                j.repos.write_text(json.dumps({'repos': {}, 'create': create, 'fail_after_create': fails}))
                if fails:
                    yes = ['create-repo', '--repo', JOURNEY['repo'], '--yes']
                    self.assertEqual(j.helper(yes).returncode, 6, j.calls[-1][1].stdout)
                    self.assertIn('uncertain', j.calls[-1][1].stdout)
                    self.assertEqual(j.helper(yes).returncode, 6, 'the next read fails too: still uncertain, no create')
                    self.assertEqual(j.helper(yes).returncode, 0, j.calls[-1][1].stdout)
                    self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'read, never created twice')
                    continue
                yes = ['create-repo', '--repo', JOURNEY['repo'], '--yes']
                self.assertEqual(j.helper(yes).returncode, first, j.calls[-1][1].stdout)
                state = json.loads(j.repos.read_text())
                j.repos.write_text(json.dumps(dict(state, create='ok', view_fails=0)))
                self.assertEqual(j.helper(yes).returncode, second, j.calls[-1][1].stdout)
                self.assertEqual([c[1] for c in j.gh_creates()].count('create'), creates)

    def test_an_existing_or_public_repository_is_never_taken_as_the_demo(self):
        j = Journey(self)
        j.repos.write_text(json.dumps({'repos': {JOURNEY['repo']: {'private': False}}, 'create': 'ok'}))
        self.assertEqual(j.helper(['create-repo', '--repo', JOURNEY['repo']]).returncode, 12)
        result = j.helper(['create-repo', '--repo', JOURNEY['repo'], '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('already exists', result.stdout)
        self.assertNotIn(['repo', 'create'], j.gh_creates())

    def test_a_busy_state_file_is_refused(self):
        j = Journey(self)
        j.replay(until='launch')
        with open(str(j.state) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            busy = j.tool({'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview']}, {})
        self.assertEqual(busy.returncode, 7, busy.stdout + busy.stderr)
        self.assertEqual(j.logged(), [])


if __name__ == '__main__':
    unittest.main()
