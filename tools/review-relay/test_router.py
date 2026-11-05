#!/usr/bin/env python3
"""#1456 router regressions against the finite pass runner (`loop.sh --pass`).

The stored router wrapper detached its router, read only process existence from
a PID file and truncated its result after printing it. These cases replay the
original synthetic reproductions on the real runner seam: a router exiting 23,
an unrelated living PID, a hung or over-age pass, a healthy concurrent pass and
a result whose delivery was lost. Synthetic commands only; no GitHub, CloudRoom
or live router. Virtual time comes from LAUNCH_FLEET_NOW; only the hung case
waits for the runner's own one-second deadline.
"""
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
LOOP = ROOT / 'skills/launch-fleet/scripts/loop.sh'
NOW = 1793534400


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie is not a surviving pass; read its state where /proc exists.
    stat = Path(f'/proc/{pid}/stat')
    return not (stat.exists() and stat.read_text().split(') ', 1)[1].startswith('Z'))


class FinitePass(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / 'state'
        self.marker = self.tmp / 'ran'

    def env(self, now=NOW):
        return dict(os.environ, LAUNCH_FLEET_NOW=str(now))

    def run_pass(self, command, seconds=30, now=NOW):
        return subprocess.run(['sh', str(LOOP), '--pass', str(self.state), str(seconds), '--', 'sh', '-c', command],
                              capture_output=True, text=True, timeout=60, env=self.env(now))

    def ack(self, result):
        return subprocess.run(['sh', str(LOOP), '--ack', str(self.state), result],
                              capture_output=True, text=True, timeout=30, env=self.env())

    def results(self, out):
        return [line.split()[1].rstrip(':') for line in out.splitlines() if line.startswith('result ')]

    def test_router_exit_23_is_visible_and_kept_until_acknowledged(self):
        # Original reproduction 1: one stderr diagnostic, then exit 23.
        first = self.run_pass('echo synthetic-router-diagnostic >&2; exit 23')
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertIn('pass failed: exit 23', first.stdout)
        self.assertNotIn('synthetic-router-diagnostic', first.stdout)
        [result] = self.results(first.stdout)
        # The loop's delivery of that output may have been lost: a later healthy
        # pass delivers the same pending result again instead of clearing it.
        again = self.run_pass(f': > {self.marker}')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.results(again.stdout), [result])
        self.assertIn('pass failed: exit 23', again.stdout)
        self.assertEqual(self.ack(result).returncode, 0)
        self.assertEqual(self.ack(result).returncode, 0, 'a repeated acknowledgement is idempotent')
        self.assertEqual(self.ack('unknown-result').returncode, 2)
        quiet = self.run_pass(':')
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ''))

    def test_router_output_is_a_pending_result_until_acknowledged(self):
        first = self.run_pass('echo ASK synthetic due line')
        self.assertEqual(first.returncode, 0, first.stderr)
        [result] = self.results(first.stdout)
        self.assertIn('ASK synthetic due line', first.stdout)
        self.assertIn('ASK synthetic due line', self.run_pass(':').stdout)
        self.ack(result)
        self.assertEqual(self.run_pass(':').stdout, '')

    def test_unrelated_living_pid_cannot_suppress_the_pass(self):
        # Original reproduction 2: the old guard trusted any living PID.
        bystander = subprocess.Popen(['sleep', '30'])
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.kill)
        self.state.mkdir(mode=0o700)
        for name in ('.router.pid', 'pid', 'lock'):
            (self.state / name).write_text(f'{bystander.pid}\n')
        (self.state / 'started').write_text(f'{NOW - 500} {NOW - 500}-{bystander.pid} 1\n')
        done = self.run_pass(f': > {self.marker}')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(self.marker.exists(), 'a stale PID or start mark suppressed the pass')
        self.assertEqual(done.stdout, '')

    def test_hung_pass_is_stopped_reported_and_leaves_no_process(self):
        pids = self.tmp / 'pids'
        hung = self.run_pass(f'sleep 300 & echo $! > {pids}; echo $$ >> {pids}; wait', seconds=1)
        self.assertEqual(hung.returncode, 1, hung.stderr)
        self.assertIn('pass over deadline: stopped after 1 s', hung.stdout)
        for pid in map(int, pids.read_text().split()):
            self.assertFalse(alive(pid), 'a process from the pass survived it')

    def hold(self, now):
        # A healthy pass that is still running: it holds the lock until released.
        gate = self.tmp / 'gate'
        os.mkfifo(gate)
        holder = subprocess.Popen(['sh', str(LOOP), '--pass', str(self.state), '60', '--', 'sh', '-c',
                                   f'echo held; read line < {gate}'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env(now))
        for _ in range(200):
            if (self.state / 'started').exists():
                break
            time.sleep(0.05)
        self.assertTrue((self.state / 'started').exists(), 'holder never started')

        def release():
            with open(gate, 'w') as end:
                end.write('go\n')
            return holder.communicate(timeout=30)
        return holder, release

    def test_healthy_concurrent_pass_is_not_duplicated(self):
        holder, release = self.hold(NOW)
        second = self.run_pass(f': > {self.marker}', now=NOW + 10)
        self.assertEqual((second.returncode, second.stdout), (0, ''), second.stderr)
        self.assertFalse(self.marker.exists(), 'a second pass ran beside a healthy one')
        out, _ = release()
        self.assertEqual(holder.returncode, 0)
        self.assertIn('held', out)

    def test_over_age_pass_is_reported_once_per_pass(self):
        holder, release = self.hold(NOW)
        late = self.run_pass(f': > {self.marker}', now=NOW + 60 + 61)
        self.assertEqual(late.returncode, 1, late.stderr)
        self.assertFalse(self.marker.exists(), 'an over-age pass still holds the work')
        self.assertIn('pass overdue: running 121 s, past its 60-second deadline', late.stdout)
        [result] = self.results(late.stdout)
        self.ack(result)
        later = self.run_pass(':', now=NOW + 300)
        self.assertNotIn('pass overdue', later.stdout, 'an acknowledged overdue pass was reported again')
        self.assertEqual(later.returncode, 1, 'the scheduler still sees the overdue pass')
        release()

    def test_r1_background_child_of_a_successful_pass_does_not_survive(self):
        child = self.tmp / 'child'
        done = self.run_pass(f'sleep 300 & echo $! > {child}')
        self.assertEqual(done.returncode, 0, done.stderr)
        pid = int(child.read_text())
        self.addCleanup(lambda: alive(pid) and os.kill(pid, 9))
        self.assertFalse(alive(pid), 'a background child outlived its pass')
        after = self.run_pass(f': > {self.marker}')
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertTrue(self.marker.exists(), 'a leftover child suppressed the next pass')

    def test_r1_session_escapes_do_not_survive_a_successful_pass(self):
        # Review round 2: a child that starts a new session, with and without
        # closing the inherited lock, is still a descendant of the pass.
        for close in ('exec 9>&-; ', ''):
            with self.subTest(closes_lock=bool(close)):
                child = self.tmp / f'child{len(close)}'
                gate = self.tmp / f'gate{len(close)}'
                os.mkfifo(gate)
                done = self.run_pass(f'setsid sh -c \'{close}echo $$ > {child}; echo ready > {gate}; exec sleep 300\' & '
                                     f'read ready < {gate}')
                pid = int(child.read_text())
                self.addCleanup(lambda pid=pid: alive(pid) and os.kill(pid, 9))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertFalse(alive(pid), 'a session escape outlived its pass')
                self.marker.unlink(missing_ok=True)
                after = self.run_pass(f': > {self.marker}', now=NOW + 5)
                self.assertEqual((after.returncode, after.stdout), (0, ''), after.stderr)
                self.assertTrue(self.marker.exists())

    def start_escape(self, seconds=30):
        # A command whose session-escaped child closes the lock; both report their PIDs.
        gate = self.tmp / 'gate'
        os.mkfifo(gate)
        fd = os.open(gate, os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, fd)
        command = ('exec 9>&-; setsid sh -c \'echo $$ > "$1"; exec sleep 300\' sh ' + str(self.tmp / 'child') +
                   f' & sleep 0.2; echo "$$ $PPID $(cat {self.tmp / "child"})" > {gate}; wait')
        runner = subprocess.Popen(['sh', str(LOOP), '--pass', str(self.state), str(seconds), '--', 'sh', '-c', command],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env())
        self.addCleanup(lambda: runner.poll() is None and runner.kill())
        for _ in range(200):
            try:
                pids = [int(pid) for pid in os.read(fd, 4096).split()]
                break
            except BlockingIOError:
                time.sleep(0.05)
        else:
            self.fail('the command did not start')
        for pid in pids:
            self.addCleanup(lambda pid=pid: alive(pid) and os.kill(pid, 9))
        return runner, pids

    def test_r1_terminated_supervisor_still_cleans_up_session_escapes(self):
        # Review round 3 (the reviewer's probe): SIGTERM to the supervisor.
        runner, (command, supervisor, child) = self.start_escape()
        os.kill(supervisor, signal.SIGTERM)
        out, err = runner.communicate(timeout=30)
        self.assertEqual(runner.returncode, 1, err)
        self.assertIn('pass failed: exit 143', out)
        self.assertFalse(alive(command), 'the command outlived its terminated supervisor')
        self.assertFalse(alive(child), 'a session escape outlived its terminated supervisor')
        after = self.run_pass(f': > {self.marker}', now=NOW + 5)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertTrue(self.marker.exists())

    def test_r1_killed_supervisor_leftovers_are_reaped_before_the_next_pass(self):
        # SIGKILL cannot be trapped: the next pass reaps what the dead pass recorded.
        runner, (command, supervisor, child) = self.start_escape()
        # Wait on an explicit state: the supervisor has recorded the escaped child.
        pids = self.state / 'pids'
        for _ in range(200):
            if pids.exists() and str(child) in pids.read_text().split():
                break
            time.sleep(0.05)
        else:
            self.fail('the pass never recorded its descendants')
        os.kill(supervisor, signal.SIGKILL)
        out, err = runner.communicate(timeout=30)
        self.assertEqual(runner.returncode, 1, err)
        self.assertIn('pass failed: exit 137', out)
        after = self.run_pass(f'kill -0 {child} && exit 9; : > {self.marker}', now=NOW + 5)
        self.assertFalse(alive(child), 'a session escape outlived the next pass')
        self.assertFalse(alive(command), 'the command outlived the next pass')
        self.assertTrue(self.marker.exists(), 'the next pass ran beside a leftover process')
        self.assertIn('pass reaped: ', after.stdout)
        self.assertIn(str(child), after.stdout)
        self.assertEqual(after.returncode, 1, 'a reaped pass must stay visible to the scheduler')

    def test_r1_unknown_lock_holder_is_reported_not_silent(self):
        # A process outside any recorded pass holds the lock: report it, never go quiet.
        self.state.mkdir(mode=0o700)
        lock = open(self.state / 'lock', 'a')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        later = self.run_pass(f': > {self.marker}', now=NOW + 5)
        self.assertEqual(later.returncode, 1, later.stderr)
        self.assertFalse(self.marker.exists())
        self.assertIn('pass lock held with no running pass', later.stdout)

    def test_r2_runner_killed_before_recording_keeps_its_output(self):
        # The command prints due work, then the runner itself dies before it spools.
        dead = self.run_pass('echo synthetic-due; kill -9 "$(ps -o ppid= -p "$PPID" | tr -d " ")"')
        self.assertEqual(dead.returncode, -9, dead.stdout)
        self.assertNotIn('synthetic-due', dead.stdout)
        # Wait on an explicit state: the dead runner's command releases the lock.
        for _ in range(200):
            if subprocess.run(['flock', '-n', str(self.state / 'lock'), 'true']).returncode == 0:
                break
            time.sleep(0.05)
        recovered = self.run_pass(f': > {self.marker}', now=NOW + 300)
        self.assertEqual(recovered.returncode, 1, recovered.stderr)
        self.assertTrue(self.marker.exists())
        self.assertIn('synthetic-due', recovered.stdout)
        self.assertIn('pass interrupted: its runner ended before recording the outcome', recovered.stdout)
        [result] = self.results(recovered.stdout)
        self.assertIn('synthetic-due', self.run_pass(':', now=NOW + 400).stdout, 'kept until acknowledged')
        self.ack(result)
        self.assertEqual(self.run_pass(':', now=NOW + 500).stdout, '')

    def test_r3_failed_result_write_fails_the_pass_and_is_recovered(self):
        fake = self.tmp / 'bin'
        fake.mkdir()
        (fake / 'mv').write_text('#!/bin/sh\ncase "$*" in *pending*) exit 1 ;; esac\nexec /bin/mv "$@"\n')
        (fake / 'mv').chmod(0o755)
        env = dict(self.env(), PATH=f'{fake}:{os.environ["PATH"]}')
        broken = subprocess.run(['sh', str(LOOP), '--pass', str(self.state), '30', '--', 'sh', '-c',
                                 'echo synthetic-due'], capture_output=True, text=True, timeout=60, env=env)
        self.assertNotEqual(broken.returncode, 0, 'a lost result reported success')
        recovered = self.run_pass(':', now=NOW + 300)
        self.assertIn('synthetic-due', recovered.stdout)
        self.assertEqual(len(self.results(recovered.stdout)), 1)

    def test_r4_pending_results_are_delivered_beside_a_healthy_holder(self):
        first = self.run_pass('echo synthetic-due')
        [result] = self.results(first.stdout)
        holder, release = self.hold(NOW)
        beside = self.run_pass(f': > {self.marker}', now=NOW + 10)
        self.assertEqual(beside.returncode, 0, beside.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.results(beside.stdout), [result])
        release()

    def test_bad_arguments_refuse_without_running(self):
        for args in (['relative', '5', '--', 'true'], [str(self.state), '0', '--', 'true'],
                     [str(self.state), 'x', '--', 'true'], [str(self.state), '5', 'true']):
            with self.subTest(args=args):
                done = subprocess.run(['sh', str(LOOP), '--pass', *args], capture_output=True, text=True)
                self.assertEqual((done.returncode, done.stdout), (2, ''))
        self.assertEqual(self.ack('../escape').returncode, 2)


if __name__ == '__main__':
    unittest.main()
