"""Review regressions. Only synthetic endpoints/processes and local Git."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FixtureCase = runpy.run_path(str(HERE / 'test_smoke.py'))['FixtureCase']


class Review(FixtureCase):
    def test_r2_live_tick_is_restricted_to_the_audited_plan(self):
        source = self.root / 'source'
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Synthetic',
                        '-c', 'user.email=synthetic@example.invalid',
                        'commit', '--allow-empty', '-qm', 'synthetic source'], check=True)
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        marker = self.root / 'effect'
        text = self.fake.read_text().replace("case = sys.argv[1]", "case = sys.argv[1]\nif sys.argv[1:3] == ['fleet', 'tick'] and '--dry-run' not in sys.argv:\n    (root / 'effect').write_text('tick dispatched')")
        self.fake.write_text(text)
        self.kit['artifacts'][str(self.fake)] = self.sha(self.fake)
        self.kit['artifacts'][str(HERE / 'smoke.py')] = self.sha(HERE / 'smoke.py')
        self.kit.update(mode='live', source={'checkout': str(source), 'head': head})
        plan = self.restricted_tick(self.kit['steps'][0])

        def approved():
            return hashlib.sha256(json.dumps(self.kit, sort_keys=True, ensure_ascii=True,
                separators=(',', ':')).encode()).hexdigest()
        # The restriction module is code the live run executes: it must be pinned.
        self.assertEqual(self.report(self.run_tool('--execute', approved()), 2)['reason'], 'invalid_kit')
        self.kit['artifacts'][str(HERE / 'restriction.py')] = self.sha(HERE / 'restriction.py')
        # The preview the tick would execute names the never-started ticket.
        self.replies['fleet tick --dry-run'] = {'exit': 0, 'out': json.dumps(
            dict(plan, actions=[dict(plan['actions'][0], ticket=9004)]))}
        doc = self.report(self.run_tool('--execute', approved()), 3)
        self.assertEqual(doc['reason'], 'out_of_scope')
        self.assertEqual(self.ticks(), [])
        self.assertFalse(marker.exists())
        # With the audited preview, the live tick runs once, pinned to it.
        self.restricted_tick(self.kit['steps'][0])
        self.report(self.run_tool('--execute', approved()), 0)
        self.assertEqual(self.ticks(), [['fleet', 'tick', '--expect-plan',
                                         str(self.state / 'fleet-expected-plan.json'), '--json']])
        self.assertTrue(marker.exists())

    def test_r5_nondefault_port_refuses_before_any_effect(self):
        marker = self.root / 'wrong-service-effect'
        text = self.fake.read_text().replace("case = sys.argv[1]",
            "case = sys.argv[1]\nif case == 'fleet':\n    (root / 'wrong-service-effect').write_text('dispatched')")
        self.fake.write_text(text)
        self.kit['artifacts'][str(self.fake)] = self.sha(self.fake)
        self.kit['default_terminal_port'] = '7474'
        service = {'id': 'service_before', 'claim': 'service', 'kind': 'read',
            'argv': [str(self.fake), 'status'], 'exit': 0,
            'checks': [{'path': '/schema', 'equals': 'openwiz.service-status.v1'}]}
        self.kit['steps'].insert(0, service)
        self.kit['steps'][1:1] = [{'id': 'terminal_default', 'claim': 'terminal', 'kind': 'read',
            'argv': [str(self.fake), 'terminal'], 'exit': 0,
            'checks': [{'path': '/count', 'equals': 1}]}]
        self.replies['status'] = {'exit': 0, 'out': '{"schema":"openwiz.service-status.v1","server":{"port":7474}}'}
        self.wrong_port_result = self.invoke()
        self.wrong_port_calls = self.call_list()
        self.assertFalse(marker.exists(), 'wrong-service inputs dispatched a write')
        self.assertEqual(self.report(self.wrong_port_result, 3)['reason'], 'default_terminal_port')
        self.assertEqual(self.call_list(), [])
        # A declared default port also needs the approved service's actual status.
        self.kit['default_terminal_port'] = '7370'
        self.state = self.root / 'wrong-service'
        self.assertEqual(self.report(self.invoke(), 3)['reason'], 'default_terminal_port')
        self.assertNotIn(['fleet'], self.call_list())
        self.assertFalse(marker.exists())
        self.replies['status']['out'] = '{"schema":"openwiz.service-status.v1","server":{"port":7370}}'
        self.state = self.root / 'right-service'
        self.report(self.invoke(), 0)

    def test_r6_timeout_reaps_the_real_pty_drivers_new_session(self):
        # Adopt a leaking baseline child so this regression can clean it up
        # even before the fix. Only descendants of this test can be adopted.
        libc = ctypes.CDLL(None, use_errno=True)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        pid_file = self.root / 'child-pid'
        child = self.root / 'synthetic-terminal.py'
        child.write_text('import os, pathlib, signal\n'
                         f'pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n'
                         'print("Synthetic child started", flush=True)\nsignal.pause()\n')
        driver = ROOT / 'tests/terminal/pty_drive.py'
        python = str(Path(sys.executable).resolve())
        self.kit['artifacts'].update({python: self.sha(Path(python)), str(driver): self.sha(driver), str(child): self.sha(child)})
        step = self.kit['steps'][0]
        step['kind'] = 'read'
        step['argv'] = [python, '-I', str(driver), '80', '24',
                        json.dumps([{'wait': 'Never printed', 'timeout': 30}]), python, '-I', str(child)]
        # Keep the fixture's required fleet write separate from the timed probe.
        self.kit['steps'].append({'id': 'fleet_write', 'claim': 'fleet', 'kind': 'write',
            'argv': [str(self.fake), 'fleet'], 'exit': 0,
            'checks': [{'path': '/count', 'equals': 1}]})
        result = self.invoke()
        self.assertTrue(pid_file.exists(), 'the child actually ran in the PTY')
        pid = int(pid_file.read_text())
        try:
            self.assertEqual(self.report(result, 3)['reason'], 'timeout')
            self.assertFalse(Path(f'/proc/{pid}').exists(), 'the terminal child must be gone and reaped')
        finally:
            if Path(f'/proc/{pid}').exists():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass


    def test_r3_reply_and_t3_cleanup_precede_final_ticks_once(self):
        from unittest.mock import patch
        bind = runpy.run_path(str(HERE / 'test_fixture.py'))['bind']
        template = json.loads((HERE / 'combined.template.json').read_text())
        start = next(i for i, s in enumerate(template['steps']) if s['id'] == 'fleet_repository')
        end = next(i for i, s in enumerate(template['steps']) if s['id'] == 'loops_api')
        baseline = self.kit['steps']
        self.fake.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
state_path = root / 'fleet-world.json'
s = json.loads(state_path.read_text())
code = 0
if args == ['repo', 'view', '--json', 'nameWithOwner']:
    out = {'nameWithOwner': 'synthetic-owner/synthetic-repo'}
elif args == ['help', '--agent']:
    out = {'schema': 'openwiz.cli.v1', 'kind': 'catalogue', 'commands': [
        {'name': 'fleet.tick', 'argv': ['fleet', 'tick'], 'flags': ['--dry-run', '--expect-plan', '--json']}]}
elif args[:2] == ['fleet', 'tick']:
    if '--dry-run' not in args:
        s['ticks'] += 1
        s['merged'] = min(2, s['ticks'])
        if s['merged'] == 2 and s['reply'] == 1 and s['unlabel'] == 1 and s['closed'] == 1:
            s['summary'] = 1
            s['spec_closed'] = True
    out = {'schema': 'openwiz.fleet-tick.v1', 'mode': 'dry_run' if '--dry-run' in args else 'run',
           'planned_at': 1893542400, 'default_branch': 'scratch', 'rules': {}, 'actions': []}
elif args == ['fleet-progress']:
    out = {'safe': True, 'merged': s['merged'], 'reply_needed': not s['spec_closed']}
elif args == ['fleet-final']:
    out = {'safe': True, 'merged': s['merged'], 'closed': s['spec_closed'], 'summary': s['summary']}
elif args == ['reply-readback']:
    out = {'safe': True, 'delivered': s['reply']}
elif args[0].endswith('/phone-probe.mjs'):
    if s['merged'] != 2 or s['reply']:
        code = 9
    else:
        s['reply'] += 1
    out = {'facts': ['AC6: ok, continue.'], 'errors': 0, 'writes': 1}
elif args[:2] == ['issue', 'edit']:
    s['unlabel'] += 1
    code = 0 if s['reply'] == 1 and s['merged'] == 2 else 9
    out = {}
elif args[:2] == ['issue', 'close']:
    s['close_attempts'] += 1
    if s['fail_close'] or s['unlabel'] != 1 or s['reply'] != 1:
        code = 9
    else:
        s['closed'] += 1
    out = {}
elif args[:2] == ['issue', 'view']:
    out = {'number': 9004, 'state': 'CLOSED' if s['closed'] else 'OPEN',
           'labels': [] if s['unlabel'] else [{'name': 'needs-info'}]}
else:
    out = json.loads((root / 'replies.json').read_text())[args[0]]
    code, out = out['exit'], json.loads(out['out'])
state_path.write_text(json.dumps(s))
print(json.dumps(out))
sys.exit(code)
''')
        browser = self.root / 'phone-probe.mjs'
        browser.write_text('// synthetic protocol endpoint; not a browser\n')
        config = self.root / 'phone.json'
        config.write_text('{}')
        python = str(Path(sys.executable).resolve())
        cleanup = HERE / 'cleanup.py'
        self.kit['artifacts'].update({str(self.fake): self.sha(self.fake),
            python: self.sha(Path(python)), str(browser): self.sha(browser), str(config): self.sha(config)})
        if cleanup.exists():
            self.kit['artifacts'][str(cleanup)] = self.sha(cleanup)
        inputs = {'openwiz': str(self.fake), 'gh': str(self.fake), 'python': python,
            'node': str(self.fake), 'browser_probe': str(browser), 'cleanup_probe': str(cleanup),
            'scratch_repository': 'synthetic-owner/synthetic-repo', 'scratch_branch': 'scratch',
            'fleet_scope': {'specs': [9001], 'tickets': [9002, 9003, 9004],
                            'rules': ['frontier', 'adr_0008', 'all_closed'], 'never_start': [9004]},
            'fleet_progress_argv': [str(self.fake), 'fleet-progress'],
            'fleet_progress_checks': [{'path': '/safe', 'equals': True}],
            'fleet_ready_for_reply_checks': [{'path': '/merged', 'equals': 2}, {'path': '/reply_needed', 'equals': True}],
            'fleet_reply_browser': str(config), 'fleet_reply_dom': ['AC6: ok, continue.'],
            'fleet_reply_readback_argv': [str(self.fake), 'reply-readback'],
            'fleet_reply_readback_checks': [{'path': '/safe', 'equals': True}],
            'fleet_reply_delivered_checks': [{'path': '/delivered', 'equals': 1}],
            't3_ticket': '9004', 'fleet_readback_argv': [str(self.fake), 'fleet-final'],
            'fleet_readback_checks': [{'path': '/safe', 'equals': True}],
            'fleet_complete_checks': [{'path': '/closed', 'equals': True}, {'path': '/summary', 'equals': 1}]}
        pipeline = bind(template['steps'][start:end], inputs)
        self.kit['steps'] = pipeline + [s for s in baseline if s['claim'] != 'fleet']
        self.kit['timeout_seconds'] = 10
        for fail_close in (False, True):
            with self.subTest(fail_close=fail_close):
                self.state = self.root / ('progress-' + str(fail_close))
                world = self.root / 'fleet-world.json'
                world.write_text(json.dumps({'ticks': 0, 'merged': 0, 'reply': 0, 'unlabel': 0,
                    'closed': 0, 'summary': 0, 'spec_closed': False, 'fail_close': fail_close,
                    'close_attempts': 0}))
                with patch.dict(os.environ, {'OPENWIZ_SMOKE_APP_TOKEN': 'synthetic-installation-token'}):
                    for _event in range(8):  # finite synthetic events; no CI or watcher
                        result = self.invoke()
                        if result.returncode == 0 or json.loads(result.stdout).get('reason') == 'uncertain_write':
                            break
                        self.report(result, 3)
                    self.report(result, 3 if fail_close else 0)
                    s = json.loads(world.read_text())
                    self.assertEqual((s['reply'], s['unlabel'], s['close_attempts']), (1, 1, 1))
                    self.assertEqual(s['ticks'], 2 if fail_close else 3)
                    self.assertEqual(s['spec_closed'], not fail_close)
                    repeated = self.invoke()  # reply, cleanup and final tick never duplicate
                    self.report(repeated, 3 if fail_close else 0)
                    self.assertEqual(json.loads(world.read_text()), s)


    def test_r8_cleanup_readback_is_bounded_and_never_repeats_write(self):
        helper = HERE / 'cleanup.py'
        python = str(Path(sys.executable).resolve())
        gh = self.root / 'synthetic-gh'
        gh.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
if sys.argv[1:3] == ['issue', 'edit']:
    with (root / 'cleanup-writes').open('a') as stream:
        stream.write('write\n')
    print('{}')
else:
    mode = (root / 'readback-mode').read_text()
    if mode == 'stderr':
        sys.stderr.write('synthetic noisy stderr ' * 1024)
    labels = [{'name': 'X' * 16384}] if mode == 'stdout' else []
    print(json.dumps({'number': 9004, 'state': 'OPEN', 'labels': labels}))
''')
        gh.chmod(0o700)
        wrapper = self.root / 'small-limit-runner.py'
        wrapper.write_text('import runpy\n'
            f'module=runpy.run_path({str(HERE / "smoke.py")!r})\n'
            "module['command'].__globals__['LIMIT']=4096\n"
            "raise SystemExit(module['main']())\n")
        self.kit['artifacts'].update({python: self.sha(Path(python)),
            str(helper): self.sha(helper), str(gh): self.sha(gh)})
        self.kit['steps'][0] = {'id': 'cleanup_write', 'claim': 'fleet', 'kind': 'write',
            'argv': [python, '-I', str(helper), '--gh', str(gh), '--repo',
                     'synthetic-owner/synthetic-repo', '--ticket', '9004', '--action', 'unlabel'],
            'exit': 0, 'checks': [{'path': '/state', 'equals': 'OPEN'},
                                 {'path': '/needs_info', 'equals': False}]}
        self.kit_path.write_text(json.dumps(self.kit))
        (self.root / 'replies.json').write_text(json.dumps(self.replies))
        writes = self.root / 'cleanup-writes'
        for mode in ('stdout', 'stderr', 'normal'):
            with self.subTest(mode=mode):
                if writes.exists():
                    writes.unlink()
                self.state = self.root / ('cleanup-' + mode)
                (self.root / 'readback-mode').write_text(mode)
                argv = [python, '-I', str(wrapper), '--kit', str(self.kit_path),
                        '--state', str(self.state), '--fixture']
                code = 3 if mode == 'stdout' else 0
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                doc = self.report(result, code)
                self.assertEqual(doc['reason'], 'uncertain_write' if mode == 'stdout' else 'none')
                self.assertEqual(writes.read_text().splitlines(), ['write'])
                before = self.call_list()
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                self.report(result, code)
                self.assertEqual(writes.read_text().splitlines(), ['write'])
                if mode == 'stdout':
                    # Resume may recheck the bundle but cannot dispatch a later
                    # step or repeat this unknown cleanup write/readback.
                    self.assertNotIn(['send'], self.call_list())
                    self.assertEqual(self.call_list(), before + [['ls', '--json']])


if __name__ == '__main__':
    unittest.main()
