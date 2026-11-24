#!/usr/bin/env python3
"""The Cloudroom driver on a synthetic room-cli (fixtures/room-cli): the kit's five checks, the wake
route the fleet's GitHub events use, and the refusals that keep a run from being claimed falsely.

Run: python3 -I adapters/cloudroom/test_driver.py   (Linux: the kit watches /proc)
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
sys.path.insert(0, KIT)
import kit  # noqa: E402
import test_kit  # noqa: E402 -- the kit's folder goes on sys.path above, so this import must follow it

_spec = importlib.util.spec_from_loader('cloudroom_driver', importlib.machinery.SourceFileLoader('cloudroom_driver',
                                                                                                DRIVER))
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)

TOKEN = 'gh' + 'p_' + 'Synthetic0Kit0Value' * 2 + '00'  # a token's shape, built here so no file holds one
PROJECT, PARENT = 'prj_syn_0001', 'thr_syn_parent'
CANT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
        "at the host's default")
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude', 'model': 'Opus 5.5'}


class Driver(unittest.TestCase):
    def setUp(self):
        self.folder, self.mark = tempfile.mkdtemp(), secrets.token_hex(8)
        self.log = os.path.join(self.folder, 'room.log')
        tracker = os.path.join(self.folder, 'tracker.json')
        with open(tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.env = dict(os.environ, KIT_TRACKER=tracker, KIT_TEST=self.mark, GH_TOKEN=TOKEN, ROOM_PROJECT_ID=PROJECT, ROOM_THREAD_ID=PARENT,
                        FAKE_ROOM_LOG=self.log, OPENWIZ_CLOUDROOM_STATE=os.path.join(self.folder, 'state'),
                        PATH=test_kit.pinned_path(self.folder, os.path.join(HERE, 'fixtures'),
                                                  os.path.join(KIT, 'fixtures')))

    def tearDown(self):
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass

    def fresh(self):
        self.tearDown()
        self.setUp()

    def call(self, cmd, request, **env):
        env = dict(self.env, **env)
        test_kit.no_real_harness(env['PATH'])
        p = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request), env=env, capture_output=True,
                           text=True, timeout=60)
        out = json.loads(p.stdout)
        schema = kit.load_schema()
        self.assertIsNone(kit.invalid(out, schema['commands'][cmd]['output'] if p.returncode == 0 else schema['error']))
        return p.returncode, out

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def test_kit_passes_all_five(self):
        # catches: a driver whose start, wake or stop doesn't reach the run's thread, or that passes a login through.
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.fresh()
                self.kit(dict(self.env, FAKE_ROOM_HOST=host))

    def kit(self, env):
        test_kit.no_real_harness(env['PATH'])
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER, '--repo',
                            'example/site', '--ticket', '7', '--harness', 'fake-harness', '--model', 'Synthetic 1',
                            '--tracker', self.env['KIT_TRACKER'], '--wait', '8'],
                           env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: medium reached a process the run started',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

    def started(self):
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        return sorted(os.listdir(state)) if os.path.isdir(state) else []

    def test_an_effort_reaches_room_cli_as_reasoning_level(self):
        for harness, model, effort, provider in (('claude', 'Opus 5.5', 'medium', 'claude-code'),
                                                 ('codex', 'Synthetic 1', 'high', 'codex'),
                                                 ('fake-harness', 'Synthetic 1', 'medium', 'fake-harness')):
            with self.subTest(harness):
                self.fresh()
                code, out = self.call('start', dict(START, harness=harness, model=model, effort=effort))
                spawns = [c for c in self.calls() if c[:2] == ['thread', 'spawn']]
                self.assertEqual([c[c.index('--reasoning-level'):][:2] for c in spawns if '--reasoning-level' in c],
                                 [['--reasoning-level', effort]], out)
                self.assertEqual((code, len(spawns)), (0, 1), out)
                self.assertEqual(spawns[0].count('--reasoning-level'), 1)
                self.assertEqual(spawns[0][5:7], ['--provider', provider])
                with open(self.log + '.threads') as f:
                    self.assertEqual(json.load(f)['thr_syn_0001']['reasoning'], effort)
                if harness == 'fake-harness':
                    self.assertTrue(self.a_turn_holds('FAKE_ROOM_REASONING_LEVEL=' + effort), 'no turn ran at ' + effort)

    def a_turn_holds(self, entry, wait=10):
        end = time.time() + wait
        while time.time() < end:
            for pid in filter(str.isdigit, os.listdir('/proc')):
                try:
                    with open('/proc/%s/environ' % pid, 'rb') as f:
                        env = f.read().split(b'\0')
                except OSError:
                    continue
                if ('KIT_TEST=' + self.mark).encode() in env and entry.encode() in env:
                    return True
            time.sleep(0.05)
        return False

    def test_no_effort_runs_at_the_hosts_default(self):
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        self.assertEqual([c[:2] for c in self.calls()], [['thread', 'spawn']])
        self.assertNotIn('--reasoning-level', self.calls()[0])

    def test_an_effort_it_cannot_set_is_refused_and_starts_nothing(self):
        cases = {'a provider with no levels': dict(harness='pi', model='Synthetic 1', effort='medium'),
                 'a level the model does not list': dict(effort='ultra'),
                 'a level only Synthetic 1 lists': dict(effort='xhigh'),
                 'a level only Opus 5.5 lists': dict(harness='codex', model='Synthetic 1', effort='low'),
                 'a model Cloudroom does not list': dict(model='Synthetic Unlisted', effort='medium')}
        for name, case in cases.items():
            with self.subTest(name):
                self.fresh()
                code, out = self.call('start', dict(START, **case))
                self.assertEqual(code, 1, out)
                self.assertEqual(out['next'], CANT)
                self.assertIn(case.get('harness', 'claude'), out['error'])
                self.assertIn(case['effort'], out['error'])
                self.assertEqual(self.calls(), [['provider', 'models', driver.provider(dict(START, **case)), '--json']],
                                 'a refused effort reached spawn')
                self.assertEqual(self.started(), [], 'a refused start saved a run')

    def test_a_start_whose_levels_cannot_be_read_starts_nothing(self):
        for effort, env in (('medium', {'FAKE_ROOM_REFUSE': 'models', 'FAKE_ROOM_SAY': 'Synthetic: not signed in'}),
                            ('medium', {'FAKE_ROOM_MODELS': 'Synthetic plain table'}), ('Medium', {})):
            with self.subTest(effort=effort, env=env):
                self.fresh()
                code, out = self.call('start', dict(START, effort=effort), **env)
                self.assertEqual(code, 1, out)
                self.assertNotIn('Synthetic', json.dumps(out))
                self.assertNotEqual(out['next'], CANT)
                self.assertNotIn(['thread', 'spawn'], [c[:2] for c in self.calls()])
                self.assertEqual(self.started(), [])

    def lookup_failed(self, harness='gemini', said='room-cli gave an error the driver does not repeat'):
        return {'error': 'Cloudroom did not list the levels of harness %s: %s; nothing was saved or started'
                         % (harness, said),
                'next': 'check `room-cli provider models %s`, then start again' % driver.provider(dict(harness=harness))}

    def test_a_lookup_diagnostic_never_reaches_the_answer(self):
        credential = 'GH_TOKEN=synthetic-demo-credential-' + self.mark
        line = 'Unknown provider gemini. See room-cli provider list.'
        says = {'a mismatched name carrying it': 'Unknown provider %s. See room-cli provider list.\n' % credential,
                'after the right line': line + ' ' + credential + '\n',
                'before the right line': credential + ' ' + line + '\n',
                'on the next line': line + '\n' + credential + '\n',
                'the credential on stdout, the right line on stderr': line + '\n'}
        for name, say in says.items():
            with self.subTest(name):
                self.fresh()
                code, out = self.call('start', dict(START, harness='gemini', effort='medium'), FAKE_ROOM_MODELS_SAY=say,
                                      FAKE_ROOM_MODELS_OUT=credential if 'stdout' in name else '')
                self.assertEqual((code, out), (1, self.lookup_failed()))
                self.assertNotIn('synthetic-demo-credential', json.dumps(out))
                self.assertEqual(self.calls(), [['provider', 'models', 'gemini', '--json']])
                self.assertEqual(self.started(), [])

    def test_an_unknown_provider_gets_the_exact_refusal(self):
        for harness, say in (('gemini', None), ('gemini', 'Unknown provider gemini. See room-cli provider list.'),
                             ('synthetic-harness', None), ('claude', 'Unknown provider claude-code. See room-cli '
                                                                     'provider list.\n')):
            with self.subTest(harness=harness, say=say):
                self.fresh()
                code, out = self.call('start', dict(START, harness=harness, effort='medium'),
                                      **({} if say is None else {'FAKE_ROOM_MODELS_SAY': say}))
                self.assertEqual((code, out), (1, {
                    'error': "Cloudroom does not know harness %s, so it can't set effort medium for it; nothing was "
                             'saved or started' % harness, 'next': CANT}))
                self.assertEqual(self.calls(), [['provider', 'models', driver.provider(dict(harness=harness)), '--json']])
                self.assertEqual(self.started(), [])

    def test_a_credential_shaped_harness_with_an_effort_never_reaches_the_lookup(self):
        value = 'sk' + '-synthetic0marker0value00' + self.mark
        code, out = self.call('start', dict(START, harness=value, effort='medium'))
        self.assertEqual(code, 1, out)
        self.assertIn('harness looks like a credential', out['error'])
        self.assertNotIn(value, json.dumps(out))
        self.assertEqual((self.calls(), self.started()), ([], []))

    def test_a_genuine_lookup_failure_keeps_its_fixed_words(self):
        line = 'Unknown provider %s. See room-cli provider list.\n'
        cases = {'another provider': (dict(FAKE_ROOM_MODELS_SAY=line % 'codex'), None),
                 'a longer name': (dict(FAKE_ROOM_MODELS_SAY=line % 'gemini2'), None),
                 'a shorter name': (dict(FAKE_ROOM_MODELS_SAY=line % 'gemin'), None),
                 'another case': (dict(FAKE_ROOM_MODELS_SAY=line % 'Gemini'), None),
                 "Cloudroom's name for a harness that has one": (dict(FAKE_ROOM_MODELS_SAY=line % 'gemini'), 'claude'),
                 'the harness name for a provider Cloudroom names otherwise': (
                     dict(FAKE_ROOM_MODELS_SAY=line % 'claude'), 'claude'),
                 'another exit code': (dict(FAKE_ROOM_MODELS_SAY=line % 'gemini', FAKE_ROOM_MODELS_EXIT='2'), None),
                 'an answer on stdout too': (dict(FAKE_ROOM_MODELS_SAY=line % 'gemini', FAKE_ROOM_MODELS_OUT='[]'), None),
                 'the line on stdout only': (dict(FAKE_ROOM_MODELS_SAY='', FAKE_ROOM_MODELS_OUT=line % 'gemini'), None),
                 'no answer': (dict(FAKE_ROOM_MODELS_SAY=''), None),
                 'signed out': (dict(FAKE_ROOM_MODELS_SAY='Synthetic: not signed in\n'), None)}
        for name, (env, harness) in cases.items():
            with self.subTest(name):
                self.fresh()
                harness = harness or 'gemini'
                code, out = self.call('start', dict(START, harness=harness, effort='medium'), **env)
                said = ('room-cli is not signed in' if name == 'signed out' else
                        'room-cli gave no answer' if name == 'no answer' else
                        'room-cli gave an error the driver does not repeat')
                self.assertEqual((code, out), (1, self.lookup_failed(harness, said)))
                self.assertNotEqual(out['next'], CANT)
                self.assertNotIn(['thread', 'spawn'], [c[:2] for c in self.calls()])
                self.assertEqual(self.started(), [])

    def test_version_lists_effort_and_the_readme_says_how(self):
        self.assertIn('effort', self.call('version', {})[1]['can'])
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        login = lines.index('Login: held by Cloudroom')
        self.assertRegex(lines[login + 1] if lines[login + 1] else lines[login + 2],
                         r'^Effort: passed as `--reasoning-level <effort>`')
        self.assertIn('--reasoning-level <effort>', next(l for l in lines if l.startswith('| `start` |')))

    def test_wake_is_the_fleet_routes_queued_delivery(self):
        # catches: a wake that steers (interrupts) instead of queueing, passes its text as an argument, answers
        # woke when Cloudroom refused the message, shows the thread id in an error, or reaches Cloudroom after stop.
        code, out = self.call('start', START)
        self.assertEqual(code, 0)
        run, spawn = out['run'], self.calls()[0]
        self.assertEqual(spawn[:5] + spawn[5:9], ['thread', 'spawn', '--parent-self', '--project', PROJECT,
                                                  '--provider', 'claude-code', '--model', 'Opus 5.5'])
        thread = 'thr_syn_0001'
        self.assertEqual(self.call('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        tell = self.calls()[-1]
        self.assertEqual(tell[:6], ['thread', 'tell', thread, '--mode', 'queue', '--message-file'])
        self.assertEqual(len(tell), 7)
        self.assertFalse(os.path.exists(tell[6]), 'the message file is left behind')
        for cmd, refuse in (('wake', 'tell'), ('stop', 'archive')):
            code, out = self.call(cmd, {'run': run}, FAKE_ROOM_REFUSE=refuse)
            self.assertEqual(code, 1)
            self.assertNotIn(thread, json.dumps(out), "Cloudroom's refusal showed the run's thread")
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a run being stopped took a wake')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.calls()[-1], ['thread', 'archive', thread])
        before = len(self.calls())
        self.assertEqual(self.call('wake', {'run': run})[0], 1)
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(len(self.calls()), before, 'a stopped run reached Cloudroom again')

    def test_reads_a_local_and_a_cloud_room_cli(self):
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.fresh()
                env = {'FAKE_ROOM_HOST': host}
                code, out = self.call('start', START, **env)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.call('wake', out, **env), (0, dict(out, woke=True)))
                self.assertEqual(self.call('stop', out, **env), (0, dict(out, stopped=True)))
                self.assertEqual(self.calls()[-1][:3], ['thread', 'archive', 'thr_syn_0001'])
                code, lost = self.call('start', START, FAKE_ROOM_RECEIPT='Synthetic lost receipt', **env)
                self.assertEqual(code, 1, lost)
                run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(lost)).group()}
                if host == 'cloud':
                    self.assertEqual(self.call('stop', run, **env)[0], 1)
                    self.assertEqual(self.calls()[-1][1], 'list', 'a Cloud row names no project')
                    continue
                self.assertEqual(self.call('stop', run, **env), (0, dict(run, stopped=True)))
                self.assertEqual(self.calls()[-1][:3], ['thread', 'archive', 'thr_syn_0002'])
                lists = [c for c in self.calls() if c[1] == 'list']
                if host == 'local':
                    self.assertEqual(lists, [['thread', 'list', '--json', '--project', PROJECT]])

    def test_stop_by_title_ends_only_its_own_thread(self):
        cases = [('other project', {'FAKE_ROOM_EXTRA': {'projectId': 'prj_syn_0002', 'parentThreadId': PARENT}}),
                 ('other parent', {'FAKE_ROOM_EXTRA': {'projectId': PROJECT, 'parentThreadId': 'thr_syn_else'}}),
                 ('two in scope', {'FAKE_ROOM_EXTRA': {'projectId': PROJECT, 'parentThreadId': PARENT}}),
                 ('only a twin', {'FAKE_ROOM_EXTRA': {'projectId': 'prj_syn_0002', 'parentThreadId': PARENT},
                                  'ARCHIVED_FIRST': True})]
        cases += [('reply ' + reply, {'FAKE_ROOM_LIST': reply}) for reply in
                  ('""', 'null', '{}', '{"children": {}}', '{"children": ""}', '{"children": [{}]}', '[1]')]
        cases += [('another caller', {'ROOM_THREAD_ID': 'thr_syn_else'}),
                  ('own row without parent', {'ROWS': [{'id': 'thr_syn_0001', 'projectId': PROJECT},
                                                       {'id': 'thr_syn_twin', 'projectId': PROJECT,
                                                        'parentThreadId': PARENT}]}),
                  ('row without scope', {'ROWS': [{'id': 'thr_syn_0001'}]}),
                  ('malformed parent', {'ROWS': [{'id': 'thr_syn_0001', 'projectId': PROJECT,
                                                  'parentThreadId': {'id': PARENT}},
                                                 {'id': 'thr_syn_twin', 'projectId': PROJECT,
                                                  'parentThreadId': PARENT}]}),
                  ('conflicting parents', {'ROWS': [{'id': 'thr_syn_0001', 'projectId': PROJECT,
                                                     'parentThreadId': PARENT, 'parent': 'thr_syn_else'}]}),
                  ('project not a string', {'ROWS': [{'id': 'thr_syn_0001', 'projectId': 7,
                                                      'parentThreadId': PARENT}]})]
        for host in ('local', 'cloud'):
            for name, case in cases:
                with self.subTest(host=host, case=name):
                    self.fresh()
                    env = {'FAKE_ROOM_HOST': host}
                    code, lost = self.call('start', START, FAKE_ROOM_RECEIPT='Synthetic lost receipt', **env)
                    run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(lost)).group()}
                    if 'ROWS' in case:
                        title = '#7: example/site builder (%s)' % run['run']
                        case = {'FAKE_ROOM_LIST': json.dumps([dict(row, title=title) for row in case['ROWS']])}
                    if case.get('ARCHIVED_FIRST'):
                        self.archive_by_hand('thr_syn_0001')
                    if 'FAKE_ROOM_EXTRA' in case:
                        twin = dict(case['FAKE_ROOM_EXTRA'], id='thr_syn_twin',
                                    title='#7: example/site builder (%s)' % run['run'])
                        case = {'FAKE_ROOM_EXTRA': json.dumps([twin])}
                    code, err = self.call('stop', run, **dict(env, **case))
                    archived = [c for c in self.calls() if c[1] == 'archive']
                    if host == 'cloud':
                        self.assertEqual((code, archived), (1, []), err)
                        continue
                    if name == 'another caller':
                        self.assertEqual((code, archived), (0, [['thread', 'archive', 'thr_syn_0001']]), err)
                        continue
                    self.assertEqual((code, archived), (1, []), err)
                    if name == 'only a twin':
                        continue
                    self.assertEqual(self.call('stop', run, **env), (0, dict(run, stopped=True)))
                    self.assertEqual([c for c in self.calls() if c[1] == 'archive'],
                                     [['thread', 'archive', 'thr_syn_0001']])

    def files_holding(self, marker):
        found = []
        for root, _, names in os.walk(self.folder):
            for name in names:
                try:
                    with open(os.path.join(root, name), errors='replace') as f:
                        if marker in f.read():
                            found.append(os.path.join(root, name))
                except OSError:
                    pass
        return found

    def test_a_credential_shaped_start_field_is_refused_before_anything_starts(self):
        cases = (('model', 'sk-' + 'Synthetic0Marker' * 2), ('model', 'token: synthetic0marker'),
                 ('model', 'AKIA' + 'SYNTHETIC0MARK00'), ('repository', TOKEN + '/site'),
                 ('skill', 'sk-synthetic0marker0value00'), ('harness', 'sk-synthetic0marker0value00'))
        for host in ('local', 'cloud'):
            for field, value in cases:
                with self.subTest(host=host, field=field, value=value):
                    self.fresh()
                    code, err = self.call('start', dict(START, **{field: value}), FAKE_ROOM_HOST=host)
                    self.assertEqual(code, 1, err)
                    self.assertIn(field, err['error'])
                    self.assertIn('credential', err['error'])
                    self.assertNotIn(value, json.dumps(err))
                    self.assertFalse(os.path.exists(self.log), 'room-cli ran')
                    self.assertEqual((self.runs(), self.files_holding(value)), ([], []))
        alone = tempfile.mkdtemp()
        with open(DRIVER) as f, open(os.path.join(alone, 'driver'), 'w') as g:
            g.write(f.read())
        p = subprocess.run([sys.executable, os.path.join(alone, 'driver'), 'start'], input=json.dumps(START),
                           env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('credential check is missing', json.loads(p.stdout)['error'])
        self.assertFalse(os.path.exists(self.log), 'room-cli ran without the credential check')

    def test_room_cli_diagnostics_never_reach_the_drivers_answer(self):
        marker = 'sk-' + 'Synthetic0Room0Marker' + self.mark
        says = (('Synthetic diagnostic ' + marker, 'does not repeat'),
                ('Synthetic: not signed in, token: ' + marker, 'not signed in'), ('', 'gave no answer'))
        for host in ('local', 'cloud'):
            for refuse in ('spawn', 'tell', 'archive', 'list'):
                for say, words in says:
                    with self.subTest(host=host, refuse=refuse, say=words):
                        self.fresh()
                        env = {'FAKE_ROOM_HOST': host}
                        bad = dict(env, FAKE_ROOM_REFUSE=refuse, FAKE_ROOM_SAY=say or ' ')
                        if refuse == 'spawn':
                            code, err = self.call('start', START, **bad)
                        else:
                            code, out = self.call('start', START, **dict(
                                env, FAKE_ROOM_RECEIPT='Synthetic lost receipt') if refuse == 'list' else env)
                            run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(out)).group()}
                            code, err = self.call('wake' if refuse == 'tell' else 'stop', run, **bad)
                        self.assertEqual(code, 1, err)
                        self.assertNotIn(marker, json.dumps(err))
                        self.assertNotIn('Synthetic', json.dumps(err))
                        self.assertIn(words, err['error'])

    def test_a_credential_shaped_thread_id_is_never_kept_or_passed(self):
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.fresh()
                receipt = json.dumps({'id': 'thr_' + TOKEN, 'projectId': PROJECT})
                code, err = self.call('start', START, FAKE_ROOM_HOST=host, FAKE_ROOM_RECEIPT=receipt)
                self.assertEqual(code, 1, err)
                self.assertIn('names no thread', err['error'])
                self.assertNotIn(TOKEN, json.dumps(err))
                self.assertEqual(self.files_holding(TOKEN), [])
                run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(err)).group()}
                row = {'id': 'thr_' + TOKEN, 'title': '#7: example/site builder (%s)' % run['run'],
                       'projectId': PROJECT, 'parentThreadId': PARENT}
                code, err = self.call('stop', run, FAKE_ROOM_HOST=host, FAKE_ROOM_LIST=json.dumps([row]))
                self.assertEqual(code, 1, err)
                self.assertIn(run['run'], err['next'])
                self.assertNotIn(TOKEN, json.dumps([err, [c for c in self.calls() if c[1] == 'archive']]))
                self.call('stop', run, FAKE_ROOM_HOST=host)
                self.assertNotIn(TOKEN, json.dumps(self.calls()))

    def test_a_kit_lost_during_spawn_never_claims_nothing_started(self):
        tree = tempfile.mkdtemp()
        for part in ('adapters/cloudroom', 'kernel'):
            shutil.copytree(os.path.join(HERE, '..', '..', part), os.path.join(tree, part))
        driver = os.path.join(tree, 'adapters/cloudroom/driver')
        kit_file = os.path.join(tree, 'kernel/driver-kit/kit.py')
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.fresh()
                shutil.copy(os.path.join(KIT, 'kit.py'), kit_file)
                env = dict(self.env, FAKE_ROOM_HOST=host)
                p = subprocess.run([sys.executable, driver, 'start'], input=json.dumps(START), capture_output=True,
                                   text=True, timeout=60, env=dict(env, FAKE_ROOM_GONE=kit_file))
                self.assertFalse(os.path.exists(kit_file))
                found = re.search(r'run-[0-9a-f]{12}', p.stdout)
                self.assertTrue(found, p.stdout)
                p = subprocess.run([sys.executable, driver, 'stop'], input=json.dumps({'run': found.group()}),
                                   capture_output=True, text=True, timeout=60, env=env)
                self.assertEqual([c for c in self.calls() if c[1] == 'archive'],
                                 [['thread', 'archive', 'thr_syn_0001']],
                                 'the builder spawned while the kit went missing still runs: ' + p.stdout)

    def archive_by_hand(self, thread):
        with open(self.log + '.threads') as f:
            threads = json.load(f)
        threads[thread]['archived'] = True
        with open(self.log + '.threads', 'w') as f:
            json.dump(threads, f)

    def test_start_refuses_a_run_cloudroom_did_not_make(self):
        # catches: a run id answered for a thread that doesn't exist, isn't safe to address, or is in another
        # project; and a missing project or room-cli reported as a crash instead of an error with next.
        receipt = {'id': 'thr_syn_0001', 'projectId': PROJECT}
        cases = {'no project': {'ROOM_PROJECT_ID': ''}, 'no room-cli': {'PATH': os.path.join(KIT, 'fixtures')},
                 'refused': {'FAKE_ROOM_REFUSE': 'spawn'}, 'not JSON': {'FAKE_ROOM_RECEIPT': 'Synthetic text'},
                 'no id': {'FAKE_ROOM_RECEIPT': json.dumps({'projectId': PROJECT})},
                 'unsafe id': {'FAKE_ROOM_RECEIPT': json.dumps(dict(receipt, id='thr_syn; rm -rf ~'))},
                 'other project': {'FAKE_ROOM_RECEIPT': json.dumps(dict(receipt, projectId='prj_syn_0002'))}}
        for name, env in cases.items():
            with self.subTest(name):
                self.assertEqual(self.call('start', START, **env)[0], 1)
                for run in self.runs():  # a run kept so stop can reach what it may have started is never woken
                    self.assertEqual(self.call('wake', {'run': run})[0], 1)
                self.assertNotIn('tell', [c[1] for c in self.calls()] if os.path.exists(self.log) else [])

    def runs(self):
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        return [f[:-5] for f in os.listdir(state) if f.endswith('.json')] if os.path.isdir(state) else []
    def test_start_that_cannot_save_its_run_never_says_retry(self):
        # catches: a start whose run can't be saved answering "retry", which starts a second builder for the
        # ticket while the first has no run id that `stop` can reach.
        state, blocker = self.env['OPENWIZ_CLOUDROOM_STATE'], os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        code, out = self.call('start', START, OPENWIZ_CLOUDROOM_STATE=os.path.join(blocker, 'state'))
        self.assertEqual((code, os.path.exists(self.log)), (1, False), 'it spawned with nowhere to keep the run')
        self.assertNotIn('retry', json.dumps(out))
        code, out = self.call('start', START, FAKE_ROOM_BREAK=state)
        self.assertEqual((code, [c[1] for c in self.calls()]), (1, ['spawn', 'archive']), 'its thread runs on')
        self.assertIn('unknown', out['error'])
        self.assertIn('room-cli thread list', out['next'])
        self.assertNotIn('retry', json.dumps(out))

    def test_a_start_it_could_not_finish_stays_starting(self):
        # catches: a start whose final save fails leaving a live thread no `stop` can reach, or a record a later
        # wake on the run id from the error uses to reach that thread (R5).
        if os.geteuid() == 0:
            self.skipTest('root ignores a read-only folder')
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        self.env['FAKE_ROOM_HOST'] = 'local'
        code, out = self.call('start', START, FAKE_ROOM_READONLY=state, FAKE_ROOM_REFUSE='archive')
        os.chmod(state, 0o700)
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        self.assertRegex(json.dumps(out), r'run-[0-9a-f]{12}', 'the error names no run for stop to reach')
        run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(out)).group()}
        code, err = self.call('wake', run)
        self.assertEqual(code, 1)
        self.assertIn('never finished starting', err['error'])
        self.assertNotIn('tell', [c[1] for c in self.calls()], 'a wake reached the thread of a run never started')
        before = len(self.calls())
        self.assertEqual(self.call('stop', run), (0, dict(run, stopped=True)))
        self.assertEqual(self.calls()[before:], [['thread', 'list', '--json', '--project', PROJECT],
                                                 ['thread', 'archive', 'thr_syn_0001']],
                         'stop did not find and end the thread by its title')

    def test_stop_that_cannot_save_ends_the_thread_and_leaves_nothing_to_wake(self):
        # catches: a stop whose save fails answering "retry" and leaving a live record that a later wake uses to
        # reach the archived thread (R3).
        code, out = self.call('start', START)
        os.mkdir(os.path.join(self.env['OPENWIZ_CLOUDROOM_STATE'], out['run'] + '.json.new'))
        code, err = self.call('stop', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertEqual(self.calls()[-1], ['thread', 'archive', 'thr_syn_0001'])
        self.assertEqual(self.call('wake', out)[0], 1)
        self.assertNotIn('tell', [c[1] for c in self.calls()], 'a wake reached the stopped run')

    def test_a_stop_waits_for_a_wake_in_progress(self):
        # catches: a stop that archives the thread while a wake is still delivering to it, so the wake answers
        # woke for a run that has ended (the per-run lock).
        code, out = self.call('start', START)
        hold = os.path.join(self.folder, 'hold')
        wake = subprocess.Popen([sys.executable, DRIVER, 'wake'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                env=dict(self.env, FAKE_ROOM_HOLD=hold))
        wake.stdin.write(json.dumps(out).encode())
        wake.stdin.close()
        for _ in range(3000):  # until the wake is inside its tell
            if os.path.exists(hold + '.held'):
                break
            time.sleep(0.01)
        stop = subprocess.Popen([sys.executable, DRIVER, 'stop'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                env=self.env)
        stop.stdin.write(json.dumps(out).encode())
        stop.stdin.close()
        try:  # without a lock the stop finishes now; with one it waits for the wake
            stop.wait(3)
        except subprocess.TimeoutExpired:
            pass
        open(hold, 'w').close()
        self.assertEqual([wake.wait(30), stop.wait(30)], [0, 0])
        self.assertEqual([c[1] for c in self.calls()], ['spawn', 'tell', 'told', 'archive'])

    def test_a_stop_that_could_not_save_keeps_the_run_unwakeable_once_writes_recover(self):
        # catches: a stop whose save and archive both fail leaving the old live record, so once the state folder
        # is writable again the next GitHub event wakes the builder the operator stopped (#1705).
        if os.geteuid() == 0:
            self.skipTest('root ignores a read-only folder')
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        os.chmod(state, 0o500)
        try:
            code, err = self.call('stop', out, FAKE_ROOM_REFUSE='archive')
        finally:
            os.chmod(state, 0o700)
        self.assertEqual(code, 1, err)
        code, err = self.call('wake', out)
        self.assertEqual(code, 1, 'a wake reached a builder whose stop never finished')
        self.assertNotIn('tell', [c[1] for c in self.calls()])
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.calls()[-1], ['thread', 'archive', 'thr_syn_0001'])

    def test_a_stop_that_could_write_nothing_still_keeps_the_run_unwakeable(self):
        # catches: a stop whose state folder AND lock file both refuse writes, with the archive refused, leaving
        # the lock saying live, so once writes recover the next wake tells the builder (#1705, re-check).
        if os.geteuid() == 0:
            self.skipTest('root ignores read-only files')
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        code, out = self.call('start', START)
        lockfile = os.path.join(state, out['run'] + '.lock')
        os.chmod(lockfile, 0o400)
        os.chmod(state, 0o500)
        try:
            code, err = self.call('stop', out, FAKE_ROOM_REFUSE='archive')
        finally:
            os.chmod(state, 0o700)
            os.chmod(lockfile, 0o600)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertEqual(self.call('wake', out)[0], 1, 'a wake reached a builder whose stop never finished')
        self.assertNotIn('tell', [c[1] for c in self.calls()])
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.calls()[-1], ['thread', 'archive', 'thr_syn_0001'])

    def test_a_wake_refuses_a_run_whose_lock_file_was_lost(self):
        # catches: after a stop that could not save and whose archive was refused, storage recovery keeping the
        # live run record but losing the lock file, and a wake recreating an empty lock and telling the builder.
        if os.geteuid() == 0:
            self.skipTest('root ignores read-only files')
        state = self.env['OPENWIZ_CLOUDROOM_STATE']
        code, out = self.call('start', START)
        lockfile = os.path.join(state, out['run'] + '.lock')
        os.chmod(lockfile, 0o400)
        os.chmod(state, 0o500)
        try:
            self.assertEqual(self.call('stop', out, FAKE_ROOM_REFUSE='archive')[0], 1)
        finally:
            os.chmod(state, 0o700)
        os.remove(lockfile)  # recovery kept the run record, not the lock file
        self.assertEqual(self.call('wake', out)[0], 1, 'a wake reached a builder whose lock file was lost')
        self.assertNotIn('tell', [c[1] for c in self.calls()])
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.calls()[-1], ['thread', 'archive', 'thr_syn_0001'])

    def test_a_wake_goes_on_only_when_the_lock_file_reads_live(self):
        for text in ('', 'lives', 'Live', 'live\n'):
            with self.subTest(text=text):
                self.fresh()
                code, out = self.call('start', START)
                self.assertEqual(code, 0, out)
                with open(os.path.join(self.env['OPENWIZ_CLOUDROOM_STATE'], out['run'] + '.lock'), 'w') as f:
                    f.write(text)
                self.assertEqual(self.call('wake', out)[0], 1, 'a wake took a lock file reading %r' % text)
                self.assertNotIn('tell', [c[1] for c in self.calls()])

    def test_stop_finds_its_thread_by_title_when_the_run_record_is_lost(self):
        cases = {'own child': ({}, 0), 'cloud': ({'FAKE_ROOM_HOST': 'cloud'}, 0),
                 'another caller': ({'ROOM_THREAD_ID': 'thr_syn_else'}, 1), 'two titled': ({'TWIN': 1}, 1),
                 'cloud, another caller': ({'FAKE_ROOM_HOST': 'cloud', 'ROOM_THREAD_ID': 'thr_syn_else'}, 1),
                 'cloud, two titled': ({'FAKE_ROOM_HOST': 'cloud', 'TWIN': 1}, 1),
                 'cloud, another project': ({'FAKE_ROOM_HOST': 'cloud', 'ROOM_PROJECT_ID': 'prj_syn_0002'}, 1)}
        for name, (env, want) in cases.items():
            with self.subTest(name):
                self.fresh()
                state = self.env['OPENWIZ_CLOUDROOM_STATE']
                env = dict({'FAKE_ROOM_HOST': 'local'}, **env)
                twin = env.pop('TWIN', None)
                code, out = self.call('start', START, FAKE_ROOM_BREAK=state, FAKE_ROOM_REFUSE='archive',
                                      FAKE_ROOM_HOST=env['FAKE_ROOM_HOST'])
                self.assertEqual(code, 1, out)
                run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(out)).group()}
                os.remove(state)
                os.mkdir(state)
                if twin:
                    env['FAKE_ROOM_EXTRA'] = json.dumps([{'id': 'thr_syn_twin', 'projectId': PROJECT,
                                                          'parentThreadId': PARENT,
                                                          'title': '#8: example/other builder (%s)' % run['run']}])
                code, err = self.call('stop', run, **env)
                archived = [c for c in self.calls() if c[1] == 'archive'][1:]
                self.assertEqual((code, archived), (want, [['thread', 'archive', 'thr_syn_0001']] if not want else []),
                                 err)
                if want:
                    self.assertIn(run['run'], json.dumps(err))
                else:
                    before = len(self.calls())
                    self.assertEqual(self.call('stop', run, **env), (0, dict(run, stopped=True)),
                                     'a retried stop of a recovered run is not answered as stopped')
                    self.assertNotIn('archive', [c[1] for c in self.calls()[before:]])
                self.assertEqual(self.call('wake', run)[0], 1)
                self.assertNotIn('tell', [c[1] for c in self.calls()])

    def test_no_provider_on_the_callers_path_is_ever_started(self):
        outside = os.path.join(self.folder, 'outside')
        ran = os.path.join(self.folder, 'provider-ran')
        os.mkdir(outside)
        with open(os.path.join(outside, 'claude-code'), 'w') as f:
            f.write('#!/bin/sh\ntouch %s\n' % ran)
        os.chmod(os.path.join(outside, 'claude-code'), 0o700)
        old = os.environ['PATH']
        os.environ['PATH'] = outside + os.pathsep + old
        try:
            self.fresh()
        finally:
            os.environ['PATH'] = old
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        with open(self.log + '.threads') as f:
            self.assertEqual(json.load(f)['thr_syn_0001']['turns'], [],
                             "the fake room-cli started a provider from the caller's PATH")
        self.assertFalse(os.path.exists(ran))
        self.assertIsNone(shutil.which('claude-code', path=self.env['PATH']))

    def test_a_failed_room_cli_command_is_named_by_fixed_words(self):
        signed_out, other, silent = 'room-cli is not signed in', 'room-cli gave an error the driver does not repeat', \
            'room-cli gave no answer'
        cases = [('', 'Synthetic: not signed in', signed_out), ('', 'Synthetic: please log in again', signed_out),
                 (json.dumps({'error': 'Synthetic: signed out'}), '', signed_out),
                 ('', 'Synthetic request expired', other), ('', 'Synthetic 401 from a mirror', other),
                 (json.dumps({'error': 'Synthetic request expired'}), '', other),
                 ('Synthetic plain diagnostic', '', other), (json.dumps({'ok': False}), '', other),
                 ('', '', silent), (' \n', '\t', silent), (json.dumps({'error': ' '}), '', silent)]
        for out, err, want in cases:
            with self.subTest(out=out, err=err):
                self.assertEqual(driver.room_said(out, err), want)

    def test_every_drivers_readme_names_its_platforms(self):
        adapters = os.path.join(HERE, '..')
        readmes = sorted(os.path.join(adapters, d, 'README.md') for d in os.listdir(adapters)
                         if os.path.isfile(os.path.join(adapters, d, 'driver')))
        self.assertIn(os.path.join(adapters, 'cloudroom', 'README.md'), readmes)
        for path in readmes:
            with self.subTest(path):
                with open(path) as f:
                    self.assertRegex(f.read(), r'\*\*Platforms:\*\* (Linux|macOS)[^\n]*, Python 3\.[0-9]+ or later')

    def test_a_start_whose_cleanup_archive_times_out_still_names_its_run(self):
        run, calls = 'run-0123456789ab', []
        old = driver.STATE, driver.saved, driver.spawn, driver.room
        driver.STATE = self.env['OPENWIZ_CLOUDROOM_STATE']

        def saved(name, state=None):
            if state and state['thread']:
                raise OSError('Synthetic full disk')
            return old[1](name, state)

        def room(*args):
            calls.append(args)
            raise driver.Unknown('room-cli thread archive did not answer within 100 seconds; its outcome is unknown',
                                 'read `room-cli thread list` before you do anything again, so nothing happens twice')
        driver.saved, driver.spawn, driver.room = saved, lambda *a: 'thr_syn_0001', room
        try:
            with self.assertRaises(driver.Unknown) as e:
                driver.start(START, run, kit.holds_credential)
        finally:
            driver.STATE, driver.saved, driver.spawn, driver.room = old
        self.assertEqual(calls, [('thread', 'archive', 'thr_syn_0001')])
        self.assertIn(run, e.exception.args[0])
        self.assertIn('stop %s' % run, e.exception.args[1])


    def test_a_provider_qualified_model_reaches_spawn(self):
        code, out = self.call('start', dict(START, model='openrouter/anthropic/claude-sonnet-4.6'))
        self.assertEqual(code, 0, out)
        spawn = self.calls()[0]
        self.assertEqual(spawn[spawn.index('--model') + 1], 'openrouter/anthropic/claude-sonnet-4.6')


if __name__ == '__main__':
    unittest.main(verbosity=2)
