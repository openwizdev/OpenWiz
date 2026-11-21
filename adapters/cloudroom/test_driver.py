#!/usr/bin/env python3
"""The Cloudroom driver on a synthetic room-cli (fixtures/room-cli): the kit's five checks, the wake
route the fleet's GitHub events use, and the refusals that keep a run from being claimed falsely.

Run: python3 -I adapters/cloudroom/test_driver.py   (Linux: the kit watches /proc)
"""
import json
import os
import re
import secrets
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

TOKEN = 'gh' + 'p_' + 'Synthetic0Kit0Value' * 2 + '00'  # a token's shape, built here so no file holds one
PROJECT, PARENT = 'prj_syn_0001', 'thr_syn_parent'
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
                        PATH=os.pathsep.join([os.path.join(HERE, 'fixtures'), os.path.join(KIT, 'fixtures'),
                                              os.environ.get('PATH', '')]))

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
        p = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env), capture_output=True,
                           text=True, timeout=60)
        out = json.loads(p.stdout)
        schema = kit.load_schema()
        self.assertIsNone(kit.invalid(out, schema['commands'][cmd]['output'] if p.returncode == 0 else schema['error']))
        return p.returncode, out

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def test_kit_passes_all_five(self):
        # catches: a driver whose start, wake or stop doesn't reach the run's thread, or that passes a login through.
        for host in ('local', 'cloud'):
            with self.subTest(host):
                self.fresh()
                self.kit(dict(self.env, FAKE_ROOM_HOST=host))

    def kit(self, env):
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER, '--repo',
                            'example/site', '--ticket', '7', '--harness', 'fake-harness', '--model', 'Synthetic 1',
                            '--tracker', self.env['KIT_TRACKER'], '--wait', '8'],
                           env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

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
                self.assertEqual(self.call('stop', run, **env), (0, dict(run, stopped=True)))
                self.assertEqual(self.calls()[-1][:3], ['thread', 'archive', 'thr_syn_0002'])
                lists = [c for c in self.calls() if c[1] == 'list']
                if host == 'local':
                    self.assertEqual(lists, [['thread', 'list', '--json', '--project', PROJECT]])

    def test_stop_by_title_ends_only_its_own_thread(self):
        cases = [('other project', {'FAKE_ROOM_EXTRA': {'projectId': 'prj_syn_0002', 'parentThreadId': PARENT}}),
                 ('other parent', {'FAKE_ROOM_EXTRA': {'projectId': PROJECT, 'parentThreadId': 'thr_syn_else'}})]
        cases += [('reply ' + reply, {'FAKE_ROOM_LIST': reply}) for reply in
                  ('""', 'null', '{}', '{"children": {}}', '{"children": ""}', '{"children": [{}]}', '[1]')]
        cases += [('another caller', {'ROOM_THREAD_ID': 'thr_syn_else'})]
        for host in ('local', 'cloud'):
            for name, case in cases:
                with self.subTest(host=host, case=name):
                    self.fresh()
                    env = {'FAKE_ROOM_HOST': host}
                    code, lost = self.call('start', START, FAKE_ROOM_RECEIPT='Synthetic lost receipt', **env)
                    run = {'run': re.search(r'run-[0-9a-f]{12}', json.dumps(lost)).group()}
                    if 'FAKE_ROOM_EXTRA' in case:
                        twin = dict(case['FAKE_ROOM_EXTRA'], id='thr_syn_twin',
                                    title='#7: example/site builder (%s)' % run['run'])
                        case = {'FAKE_ROOM_EXTRA': json.dumps([twin])}
                    code, err = self.call('stop', run, **dict(env, **case))
                    archived = [c for c in self.calls() if c[1] == 'archive']
                    if name == 'another caller' and host == 'local':
                        self.assertEqual((code, archived), (0, [['thread', 'archive', 'thr_syn_0001']]), err)
                        continue
                    self.assertEqual((code, archived), (1, []), err)
                    self.assertEqual(self.call('stop', run, **env), (0, dict(run, stopped=True)))
                    self.assertEqual([c for c in self.calls() if c[1] == 'archive'],
                                     [['thread', 'archive', 'thr_syn_0001']])

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
                                                 ['thread', 'list', '--json'], ['thread', 'archive', 'thr_syn_0001']],
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
