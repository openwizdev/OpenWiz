#!/usr/bin/env python3
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import setup

DOWNLOAD_PAGE = 'https://www.cloudroom.dev/download'
PROJECT = {'repository': 'synthetic-owner/synthetic-consumer', 'project': 'prj_synthetic',
           'operator': 'synthetic-owner', 'service_issue': 7, 'answer_thread': 'synthetic-answer-thread',
           'harness': 'claude-code', 'model': 'synthetic-model', 'effort': 'high', 'runtime': None}

NEXT_MUST_NAME = {
    'cloudroom': {
        'cloudroom_not_installed': 'cloudroom/cloudroom.py install',
        'cloudroom_installing': 'setup/setup.py check',
        'cloudroom_installed': 'cloudroom/cloudroom.py sign-in',
        'cloudroom_reused': 'cloudroom/cloudroom.py sign-in',
        'cloudroom_install_failed': 'cloudroom/cloudroom.py install',
        'cloudroom_install_uncertain': 'cloudroom/cloudroom.py install',
        'cloudroom_install_declined': 'cloudroom/cloudroom.py install',
        'cloudroom_checksum_mismatch': DOWNLOAD_PAGE,
        'cloudroom_unsupported': DOWNLOAD_PAGE,
        'cloudroom_destination_blocked': '~/Applications/Cloudroom.AppImage',
        'cloudroom_login_missing': 'cloudroom/cloudroom.py sign-in',
        'cloudroom_login_unknown': 'cloudroom/cloudroom.py sign-in',
        'cloudroom_login_verified': 'None',
        'cloudroom_missing': DOWNLOAD_PAGE,
        'cloudroom_unreadable': 'setup/setup.py check',
        'cloudroom_partial': 'setup/setup.py check',
        'cloudroom_reachable': 'None',
    },
    'harness': {
        'harness_unselected': 'setup/setup.py prepare',
        'harness_unreadable': 'cloudroom/cloudroom.py sign-in',
        'harness_unavailable': 'models --json',
        'harness_listed': 'None',
    },
    'personal_github': {
        'identity_unselected': 'setup/setup.py prepare',
        'identity_signed_out': 'setup/github_login.py sign-in',
        'identity_unreadable': 'gh auth status',
        'identity_bot': 'gh auth login --web',
        'identity_no_push': 'gh auth login --web',
        'identity_account_mismatch': 'setup/github_login.py skip-app',
        'identity_verified': 'None',
    },
    'project': {
        'project_unprepared': 'setup/setup.py prepare',
        'project_runtime_missing': 'setup/setup.py prepare',
        'project_unreadable': 'gh auth status',
        'project_issue_refused': 'setup/setup.py prepare',
        'project_settings_missing': 'docs/agents/fleet.md',
        'project_answer_refused': 'setup/setup.py prepare',
        'project_verified': 'None',
    },
    'github_app': {
        'app_missing': 'github-app/setup.py --repo',
        'app_files_unusable': 'setup/github_login.py skip-app',
        'app_not_installed': 'github-app/setup.py --repo',
        'app_key_rejected': 'private-key.pem',
        'app_unreadable': 'setup/setup.py check',
        'app_revoked': 'github-app/setup.py --repo',
        'app_suspended': 'https://github.com/settings/installations',
        'app_all_repositories': 'https://github.com/settings/installations',
        'app_read_only': 'https://github.com/settings/installations',
        'app_permissions_mismatch': 'https://github.com/settings/installations',
        'app_wrong_repository': 'https://github.com/settings/installations',
        'app_token_unusable': 'setup/setup.py check',
        'app_verified': 'None',
    },
}
COMMAND = re.compile(r'`([^`]+)`')


def tools_by_folder_without_state(step):
    def short(match):
        words = shlex.split(match.group(1))
        if words[:2] == ['python3', '-I']:
            if '--state-dir' in words:
                at = words.index('--state-dir')
                del words[at:at + 2]
            words = ['/'.join(Path(words[2]).parts[-2:])] + words[3:]
        return ' '.join(words)
    return COMMAND.sub(short, step)


def check_answering(state, results, project=None, identity=None, gh=True):
    reads = {'cloudroom': 'check_cloudroom', 'harness': 'check_harness', 'personal_github': 'check_identity',
             'project': 'check_project'}
    with contextlib.ExitStack() as stack:
        for component, name in reads.items():
            stack.enter_context(mock.patch.object(setup, name, return_value=results[component]))
        stack.enter_context(mock.patch.object(setup, 'check_app', return_value=(results['github_app'], None)))
        if project is not None:
            real = setup.store.Store.read
            stack.enter_context(mock.patch.object(setup.store.Store, 'read', lambda self: {
                **real(self), 'project': project, 'identity': identity}))
        if not gh:
            stack.enter_context(mock.patch.object(setup.shutil, 'which', lambda name: None))
        out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        setup.check(argparse.Namespace(state_dir=str(state), api_base=setup.API, openwiz=None, runtime=None))
    answer = json.loads(out.getvalue())
    unittest.TestCase().assertIn('next', answer, 'check prints a next step beside its codes')
    return answer


class EveryCodeHasANextStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state with space'

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_code_prints_a_one_line_next_naming_its_command_or_step(self):
        for project in (None, PROJECT):
            for component, codes in NEXT_MUST_NAME.items():
                for code, names in codes.items():
                    with self.subTest(project=project is not None, component=component, code=code):
                        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
                        results[component] = code
                        answer = check_answering(self.state, results, project)
                        self.assertEqual(answer['results'], results, 'the codes are unchanged')
                        self.assertEqual(sorted(answer['next']), sorted(NEXT_MUST_NAME), 'one next per component')
                        step = answer['next'][component]
                        self.assertIsInstance(step, str)
                        self.assertTrue(step and '\n' not in step, step)
                        self.assertIn(names, tools_by_folder_without_state(step))
                        for command in COMMAND.findall(step):
                            words = shlex.split(command)
                            if words[:2] == ['python3', '-I']:
                                self.assertTrue(Path(words[2]).is_file(), f'{command}: no such tool')
                                self.assertIn('--state-dir', words, f'{command}: names this state')
                                self.assertEqual(words[words.index('--state-dir') + 1], str(self.state))

    def test_an_unknown_code_still_gets_a_next_step(self):
        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
        results['project'] = 'project_from_a_newer_build'
        answer = check_answering(self.state, results)
        self.assertIn('setup/setup.py check', answer['next']['project'])

    def test_the_printed_check_command_runs_through_a_shell_on_the_same_state(self):
        self.state = self.base / "it's a state"
        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
        results['cloudroom'] = 'cloudroom_installing'
        step = check_answering(self.state, results)['next']['cloudroom']
        command, = COMMAND.findall(step)
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.base / 'home')}
        done = subprocess.run(['sh', '-c', command], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['schema'], 'openwiz.setup-check.v1')
        record = json.loads((self.state / 'setup/state.json').read_text())
        self.assertEqual(record['checks']['committed'], 2, 'the second check saved to the same state')

    def test_help_names_no_setup_page(self):
        done = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'setup.py'), '--help'],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0)
        self.assertNotIn('setup page', done.stdout)
        self.assertIn('next', done.stdout)


SKIPPED = {'selected': 'personal_login', 'app_choice': 'skip', 'acting_login': 'synthetic-owner',
           'repository': PROJECT['repository']}


class GitHubStepsFromTheReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'state'

    def tearDown(self):
        self.tmp.cleanup()

    def step(self, component, code, **given):
        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
        results.update({component: code, **given.pop('results', {})})
        return tools_by_folder_without_state(check_answering(self.state, results, PROJECT, **given)['next'][component])

    def test_r1_signed_out_without_gh_installs_gh_before_signing_in(self):
        step = self.step('personal_github', 'identity_signed_out', gh=False)
        self.assertIn('https://cli.github.com', step)
        self.assertLess(step.index('https://cli.github.com'), step.index('setup/github_login.py sign-in'))
        self.assertNotIn('https://cli.github.com', self.step('personal_github', 'identity_signed_out'))

    def test_r2_a_skipped_app_stays_skipped(self):
        step = self.step('github_app', 'app_missing', identity=SKIPPED,
                         results={'personal_github': 'identity_verified'})
        self.assertTrue(step.startswith('None:'), step)
        for offer in ('github-app/setup.py', 'skip-app'):
            self.assertNotIn(offer, step)
        other = {**SKIPPED, 'repository': 'synthetic-owner/another'}
        self.assertIn('github-app/setup.py --repo', self.step('github_app', 'app_missing', identity=other))

    def test_r3_a_newly_chosen_account_is_recorded_by_skip_app(self):
        step = self.step('personal_github', 'identity_account_mismatch', identity=SKIPPED)
        self.assertIn('gh auth switch', step)
        self.assertIn('setup/github_login.py skip-app', step)
        self.assertNotIn('sign-in', step)

    def test_r4_a_rejected_app_key_is_replaced_not_reconnected(self):
        step = self.step('github_app', 'app_key_rejected')
        self.assertNotIn('github-app/setup.py', step)
        self.assertIn('private-key.pem', step)
        self.assertIn('setup/github_login.py skip-app', step)


class IntelMac(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        spec = importlib.util.spec_from_file_location('cloudroom_2143', HERE.parent / 'cloudroom/cloudroom.py')
        self.cloudroom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cloudroom)

    def tearDown(self):
        self.tmp.cleanup()

    def host(self):
        home = self.base / 'Users/synthetic'
        home.mkdir(parents=True, exist_ok=True)
        return self.cloudroom.Host('Darwin', 'x86_64', home=home, root=self.base)

    def test_an_intel_mac_without_cloudroom_is_sent_to_the_download_page(self):
        code = self.cloudroom.status(self.host(), self.base / 'state')['code']
        self.assertEqual(code, 'cloudroom_unsupported')
        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
        results['cloudroom'] = code
        step = check_answering(self.base / 'state', results)['next']['cloudroom']
        self.assertIn(DOWNLOAD_PAGE, step)
        self.assertIn('Intel Mac', step)

    def test_an_intel_mac_with_cloudroom_installed_by_hand_is_reused(self):
        (self.base / 'Applications/Cloudroom.app').mkdir(parents=True)
        self.assertEqual(self.cloudroom.status(self.host(), self.base / 'state')['code'], 'cloudroom_reused')


if __name__ == '__main__':
    unittest.main()
