#!/usr/bin/env python3
import argparse
import base64
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


def check_answering(state, results, project=None, identity=None, gh=True, openwiz=None):
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
        setup.check(argparse.Namespace(state_dir=str(state), api_base=setup.API, openwiz=openwiz, runtime=None))
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

    def test_a_relative_openwiz_override_prints_an_absolute_models_command(self):
        (self.base / 'fixture-bin').mkdir()
        (self.base / 'fixture-bin/openwiz').touch()
        results = {c: next(iter(NEXT_MUST_NAME[c])) for c in NEXT_MUST_NAME}
        results['harness'] = 'harness_unavailable'
        here = os.getcwd()
        os.chdir(self.base)
        self.addCleanup(os.chdir, here)
        step = check_answering(self.state, results, openwiz='fixture-bin/openwiz')['next']['harness']
        program = shlex.split(next(c for c in COMMAND.findall(step) if c.endswith(' models --json')))[0]
        self.assertTrue(Path(program).is_absolute(), step)
        self.assertEqual(Path(program).resolve(), (self.base / 'fixture-bin/openwiz').resolve())

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


class UnknownIsNotRefused(unittest.TestCase):
    def reads(self, answers):
        user = (0, {'type': 'User', 'login': 'synthetic-owner'}, False)
        return mock.patch.object(setup, 'github_com_read', lambda path: answers.get(path, user))

    def test_a_gh_timeout_start_failure_or_generic_exit_is_unreadable(self):
        with mock.patch.object(setup.shutil, 'which', return_value='/synthetic/gh'):
            for failure in (subprocess.TimeoutExpired('gh', 30), OSError('synthetic: cannot start')):
                with self.subTest(failure=type(failure).__name__), \
                        mock.patch.object(setup.subprocess, 'run', side_effect=failure):
                    self.assertEqual(setup.account(), ('identity_unreadable', None))
        repo = 'repos/' + PROJECT['repository']
        issue, fleet = f'{repo}/issues/7', f'{repo}/contents/docs/agents/fleet.md'
        generic, missing = (1, None, False), (1, {'message': 'Not Found'}, False)
        pushes = (0, {'permissions': {'push': True}}, False)
        for answers, code in (({repo: generic}, 'identity_unreadable'), ({repo: missing}, 'identity_no_push')):
            with self.subTest(code=code), self.reads(answers):
                self.assertEqual(setup.read_back(PROJECT['repository'])[0], code)
        local = dict(PROJECT, host='local', project=None, answer_thread=None, runtime='synthetic-pin')
        opened = (0, {'state': 'open', 'number': 7}, False)
        for answers, code in (({issue: generic}, 'project_unreadable'), ({issue: missing}, 'project_issue_refused'),
                              ({issue: opened, fleet: generic}, 'project_unreadable'),
                              ({issue: opened, fleet: missing}, 'project_settings_missing')):
            with self.subTest(code=code, answers=sorted(answers)), self.reads({repo: pushes, **answers}), \
                    mock.patch.object(setup, 'runtime_pin', return_value='synthetic-pin'):
                self.assertEqual(setup.check_project(None, local, None), code)


class CredentialShapedText(unittest.TestCase):
    def test_credential_shaped_operator_effects_and_reasons_are_refused_before_saving(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saved = setup.store.Store(str(Path(tmp.name) / 'state'))
        for secret in ('ghp_' + 'Synthetic0' * 3 + 'abcdef', '0123456789abcdef' * 2 + '01234567',
                       '-----BEGIN PRIVATE KEY-----'):
            self.assertEqual(len(secret) == 40, not secret.startswith('-'))
            for place in ('operator', 'effect', 'reason'):
                with self.subTest(place=place, secret=secret[:4]), self.assertRaises(setup.store.Refused):
                    if place == 'operator':
                        saved.update(lambda value: value.update(project=dict(PROJECT, operator=f'synthetic {secret}')))
                    else:
                        saved.propose('prepare_project', {place: secret}, [f'Select {secret}.' if place == 'effect'
                                                                           else 'Select it.'],
                                      f'Refused: {secret}' if place == 'reason' else 'Proposed.')
                self.assertNotIn(secret, json.dumps(saved.read()))
        saved.propose('prepare_project', {}, [f"Select {PROJECT['repository']} and operation {'a1' * 16}."], 'Proposed.')
        for name in ('sk-tools', 'eyJ-docs', 'AKIA-notes', 'xoxb-bot', 'ghp_pages'):
            with self.subTest(repository=name):
                done = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'setup.py'), 'prepare', '--state-dir',
                                       str(Path(tmp.name) / name), '--repository', f'synthetic-owner/{name}', '--host',
                                       'local', '--operator', f'synthetic-{name}', '--service-issue', '7', '--harness',
                                       'codex', '--model', 'synthetic-model', '--effort', 'medium'],
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual((done.returncode, json.loads(done.stdout or '{}').get('phase')), (0, 'proposed'),
                                 done.stderr)
        saved.update(lambda value: value.update(project=PROJECT))
        self.assertEqual(saved.read()['project'], PROJECT)


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


class HostFixtureCase(unittest.TestCase):
    fixtures = json.loads((HERE.parent / 'tests/setup-onboard-contract/fixtures/hosts.json').read_text())

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.state = self.base / 'state'
        self.env = {'HOME': str(self.base), 'PATH': str(self.base)}

    def invoke(self, command, *args, script='setup.py'):
        return subprocess.run([sys.executable, '-I', '-B', str(HERE / script), command,
                               '--state-dir', str(self.state), *args], capture_output=True, env=self.env,
                              timeout=30)

    def prepare_args(self, project):
        return [part for key, value in project.items() if key != 'runtime' and value is not None
                for part in ('--' + key.replace('_', '-'), str(value))]

    def saved(self):
        return json.loads((self.state / 'setup/state.json').read_text())

class HostSetup(HostFixtureCase):
    def test_prepare_matches_host_fixtures(self):
        cases = self.fixtures['prepared_projects']
        for name in ('local-without-cloudroom-ids', 'boat-without-cloudroom-ids',
                     'other-driver-without-cloudroom-ids', 'local-with-cloudroom-project',
                     'local-with-answer-thread', 'cloudroom-driver-name', 'local-uppercase-host',
                     'cloud-without-project', 'cloud-without-answer-thread'):
            with self.subTest(case=name):
                case = cases[name]
                project = case['document']
                args = self.prepare_args(project)
                preview = self.invoke('prepare', *args)
                self.assertEqual(preview.returncode == 0, case['valid'], preview.stderr)
                if not case['valid']:
                    self.assertEqual(preview.stdout, b'')
                    continue
                operation = json.loads(preview.stdout)
                self.assertEqual(operation['effects'], [
                    f"Select {project['repository']} for your first fleet, with agents on {project['host']}.",
                    f"Record {project['operator']} as the loop operator and issue #7 for service records.",
                    f"Run agents on {project['harness']}, {project['model']}, {project['effort']} effort.",
                    'No packaged runtime found; project stays unverified.',
                    "Save these settings in this host's owner-only OpenWiz state. Nothing is sent or created.",
                ])
                applied = self.invoke('prepare', *args, '--yes', '--operation', operation['operation_id'])
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertEqual(self.saved()['project'], project)

    def test_explicit_cloud_prepare_has_the_legacy_bytes_and_settings(self):
        project = self.fixtures['prepared_projects']['cloud-nine-keys']['document']
        args = self.prepare_args(project)
        preview = self.invoke('prepare', *args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        explicit = self.invoke('prepare', *args, '--host=cloud')
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(explicit.stdout, preview.stdout)
        operation = json.loads(explicit.stdout)
        applied = self.invoke('prepare', *args, '--host=cloud', '--yes', '--operation', operation['operation_id'])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.saved()['project'], project)
        self.assertEqual(self.invoke('prepare', *args, '--yes', '--operation', operation['operation_id']).stdout,
                         applied.stdout)

    def test_prepare_names_every_missing_flag_in_one_error(self):
        rest = ['--operator', 'synthetic-owner', '--service-issue', '7', '--harness', 'claude-code',
                '--model', 'synthetic-model', '--effort', 'high']
        cloud = '--repository, --project, --answer-thread'
        for host, missing in ((None, cloud), ('cloud', cloud), ('local', '--repository')):
            with self.subTest(host=host):
                done = self.invoke('prepare', *rest, *(['--host', host] if host else []))
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, b'')
                self.assertTrue(done.stderr.decode().endswith(
                    f'error: the following arguments are required: {missing}\n'), done.stderr)


class HostCheck(HostFixtureCase):
    def program(self, name, code):
        path = self.base / name
        path.write_text(f'#!{sys.executable}\n' + code)
        path.chmod(0o700)
        return path

    def prepare_check(self, fixture='local-without-cloudroom-ids', choice=None, push=True):
        project = self.fixtures['prepared_projects'][fixture]['document'].copy()
        if choice:
            project.update(choice)
        runtime = self.base / 'runtime'
        runtime.mkdir()
        (runtime / 'openwiz-build.txt').write_text('openwiz.package.v1\n0.1.1\n' + 'a' * 40 + '\nsynthetic\n')
        for name in ('setup', 'grill', 'to-tickets', 'launch-fleet'):
            skill = runtime / 'skills' / name / 'SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.touch()
        self.runtime_args = ('--runtime', str(runtime))
        args = (*self.prepare_args(project), *self.runtime_args)
        preview = self.invoke('prepare', *args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        operation = json.loads(preview.stdout)
        applied = self.invoke('prepare', *args, '--yes', '--operation', operation['operation_id'])
        self.assertEqual(applied.returncode, 0, applied.stderr)

        settings = """## Builder
| Setting | Value |
| --- | --- |
| Harness | Claude Code |
| Model | Opus |
| Effort | Medium |
Source: synthetic
## Reviewer
| Setting | Value |
| --- | --- |
| Harness | Codex |
| Model | Synthetic |
| Effort | Medium |
Source: synthetic
## Test commands
| Command |
| --- |
| test |
Source: synthetic
## CI checks
| Check |
| --- |
| ci |
Source: synthetic
## Standing merge rules
None yet: every merge waits for the user.
Source: synthetic
"""
        repo = f"repos/{project['repository']}"
        github = {
            'user': {'type': 'User', 'login': 'synthetic-owner'},
            repo: {'permissions': {'push': push}},
            f'{repo}/issues/7': {'state': 'open', 'number': 7},
            f'{repo}/contents/docs/agents/fleet.md': {
                'encoding': 'base64', 'content': base64.b64encode(settings.encode()).decode()},
        }
        self.program('gh', f'import json, sys\nprint(json.dumps({github!r}[sys.argv[2]]))\n')
        self.openwiz_calls = self.base / 'openwiz-calls'
        self.openwiz_calls.touch()
        listed = 'local-codex-only' if project['harness'] == 'codex' else 'local-claude-code-and-codex'
        options = self.fixtures['offered_lists'][listed]['document']
        self.openwiz = self.program('openwiz',
                                   'import json, sys\n'
                                   f'with open({str(self.openwiz_calls)!r}, "a") as calls:\n'
                                   '    print(json.dumps(sys.argv[1:]), file=calls)\n'
                                   f'assert sys.argv[1:] == ["models", "--json", "--host", {project["host"]!r}]\n'
                                   f'print(json.dumps({options!r}))\n')

    def checked(self):
        done = self.invoke('check', *self.runtime_args, '--openwiz', str(self.openwiz))
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual(answer['schema'], 'openwiz.setup-check.v1')
        return answer

    def test_local_check_matches_ready_host_fixture(self):
        self.prepare_check()
        self.program('claude', '')
        preview = self.invoke('skip-app', script='github_login.py')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        operation = json.loads(preview.stdout)
        applied = self.invoke('skip-app', '--yes', '--operation', operation['operation_id'],
                              script='github_login.py')
        self.assertEqual(applied.returncode, 0, applied.stderr)

        report = self.fixtures['setup_reports']['local-ready-without-cloudroom']['document']
        answer = self.checked()
        self.assertEqual(answer.get('host'), report['host'])
        cloudroom = report['components'][0]
        self.assertEqual(answer['results'], {'cloudroom': cloudroom['reason'], 'harness': 'harness_listed',
                                             'personal_github': 'identity_verified', 'github_app': 'app_missing',
                                             'project': 'project_verified'})
        self.assertEqual(answer['next']['cloudroom'], cloudroom['next'])
        self.assertIn('you skipped the App', answer['next']['github_app'])
        for line in answer['next'].values():
            self.assertNotRegex(line, r'room-cli|cloudroom/cloudroom.py|--answer-thread|--project ')
        self.assertEqual([json.loads(line) for line in self.openwiz_calls.read_text().splitlines()],
                         [['models', '--json', '--host', 'local']])

    def test_missing_harness_is_reported_even_if_list_would_offer_it(self):
        self.prepare_check()
        answer = self.checked()
        self.assertEqual(answer['results']['harness'], 'harness_not_installed')
        self.assertIn('claude', answer['next']['harness'])
        self.assertEqual(self.openwiz_calls.read_bytes(), b'')

    def test_probe_accepts_the_contract_unlisted_model_on_boat(self):
        fixture = self.fixtures['unlisted_local_set']
        self.assertIs(fixture['listed'], False)
        choice = fixture['asked']
        self.prepare_check('boat-without-cloudroom-ids',
                           {'harness': choice['provider'], 'model': choice['model'], 'effort': choice['effort']})
        self.program('codex', '')
        answer = self.checked()
        self.assertEqual(answer.get('host'), 'boat')
        self.assertEqual(answer['results']['harness'], 'harness_listed')
        self.assertEqual([json.loads(line) for line in self.openwiz_calls.read_text().splitlines()],
                         [['models', '--json', '--host', 'boat']])

    def test_project_without_push_permission_is_refused(self):
        self.prepare_check(push=False)
        self.program('claude', '')
        answer = self.checked()
        self.assertEqual(answer['results']['project'], 'project_no_write')
        self.assertEqual(answer['results']['personal_github'], 'identity_no_push')

    def test_missing_repository_is_refused_with_a_prepare_again_step(self):
        for body, code in (({'message': 'Not Found', 'status': '404'}, 'project_no_write'),
                           ({'message': 'Bad credentials', 'status': '401'}, 'project_unreadable')):
            with self.subTest(code=code):
                self.setUp()
                self.prepare_check()
                self.program('claude', '')
                self.program('gh', 'import json, sys\n'
                                   'if sys.argv[2] == "user":\n'
                                   '    print(json.dumps({"type": "User", "login": "synthetic-owner"}))\n'
                                   '    sys.exit(0)\n'
                                   f'print(json.dumps({body!r}))\n'
                                   'sys.exit(1)\n')
                answer = self.checked()
                self.assertEqual(answer['results']['project'], code)
                if code == 'project_no_write':
                    self.assertIn('prepare --repository OWNER/NAME', answer['next']['project'])
                    self.assertIn('--host local', answer['next']['project'])

    def test_non_settable_choice_names_only_local_next_steps(self):
        self.prepare_check(choice={'model': 'synthetic//demo'})
        self.program('claude', '')
        answer = self.checked()
        self.assertEqual(answer['results']['harness'], 'harness_unavailable')
        self.assertIn('models --json --host local', answer['next']['harness'])
        self.assertIn('--host local', answer['next']['harness'])
        self.assertEqual(self.openwiz_calls.read_bytes(), b'')

    def test_cloud_catalogue_cannot_verify_a_local_choice(self):
        self.prepare_check()
        self.program('claude', '')
        cloud = self.fixtures['offered_lists']['cloudroom-unmarked']['document']
        self.program('openwiz', f'import json\nprint(json.dumps({cloud!r}))\n')
        answer = self.checked()
        self.assertEqual(answer['results']['harness'], 'harness_unreadable')


if __name__ == '__main__':
    unittest.main()
