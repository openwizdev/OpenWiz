#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
CLI = HERE / 'check.py'
THREAD = 'thr_' + 'planted42'
DECIDER = 'Ja' + 'ke'
BAD_MAIL = 'robin' + '@' + 'mail.invalid'
PRIVATE_MAIL = '12345+robin-synthetic@users.noreply.github.com'


class Check(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root / 'tree'
        self.tree.mkdir()

    def call(self, *args):
        return subprocess.run([sys.executable, '-I', str(CLI), *map(str, args)],
                              capture_output=True, text=True)

    def verdict(self, result, rule=None):
        self.assertEqual(result.returncode, 1 if rule else 0, result.stdout + result.stderr)
        if rule:
            self.assertIn(rule + ' ', result.stdout)

    def text(self, value, rule=None):
        for seam in ('tree', 'title-file', 'body-file'):
            with self.subTest(seam=seam, value=value):
                path = self.tree / 'note.md'
                path.write_text(value)
                result = self.call('--tree', self.tree) if seam == 'tree' else self.call('--' + seam, path)
                self.verdict(result, rule)
                if rule:
                    self.assertNotIn(value, result.stdout)

    def test_t1(self):
        for suffix in ('a', '0', 'planted_42-a'):
            self.text('@thr_' + suffix, 'T1')
        for value in ('thr_synfixture', 'thr_webfixture', 'thr_', 'wordthr_a', 'room/synthetic-branch'):
            self.text(value)

    def test_t2(self):
        for quote in ('"', '“', '”', '\\"'):
            self.text('**Approved by ' + DECIDER + ':** ' + quote + 'planted', 'T2')
            self.text(DECIDER + ', in a thread: ' + quote + 'planted', 'T2')
        self.text('**' + DECIDER + ':**\n> planted', 'T2')
        self.text(DECIDER + ':\n> planted', 'T2')
        self.text('"Open for ' + DECIDER + '"\nA quote: "ordinary text"')
        self.text(DECIDER + ' approved the decision ([private record](https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001)).')

    def test_t3_ids(self):
        for prefix in ('proj', 'prj', 'mch', 'usr', 'acct', 'auto', 'cr'):
            self.text(prefix + '_' + ('12345678-abcd' if prefix == 'cr' else 'planted42'), 'T3')
            self.text(prefix + '_synfixture ' + prefix + '_webfixture')

    def test_t3_homes(self):
        for prefix in ('/home/', '/Users/'):
            for name in ('plantedname', 'notexample', 'runner-extra'):
                self.text(prefix + name + '/file', 'T3')
            for name in ('runner', 'cache', 'token', 'secret', 'someone', 'synthetic42', 'example42'):
                self.text(prefix + name + '/file')

    def test_t3_emails(self):
        for value in (BAD_MAIL, 'someone@' + 'example.com.evil', 'test@' + 'github.com'):
            self.text(value, 'T3')
        for domain in ('example.com', 'example.org', 'example.net', 'example.invalid', 'domain.example'):
            self.text('robin@' + domain)
        self.text(PRIVATE_MAIL + ' noreply@github.com git@github.com user@github.com pass@github.com')

    def test_t3_helper_state_locations(self):
        store = '$HOME/.openwiz/helper-checks/synthetic-owner/widgets/12/'
        for value in (store + 'snapshot.' + 'aB3xQ9' + '/state.json',
                      'window: `window.' + 'Zq81Kp' + '/state.json` in the same parent',
                      '~/.openwiz/helper-checks/synthetic-owner/widgets/12/window.' + 'pQ2rSt',
                      'Durable snapshot: `' + store + 'snapshot.' + 'r4' + '/state.json`'):
            self.text(value, 'T3')
        for value in ('$HOME/.openwiz/helper-checks/<owner>/<repo>/<ticket>/snapshot.*/state.json',
                      'the check saves both compared states in `window.*/state.json`',
                      'mktemp -d "$store/snapshot.XXXXXX", then snapshot.XXXXXX/state.json',
                      '.openwiz/helper-checks/<owner>/<repo>/<ticket>/window.<run>/state.json',
                      'write window.json and snapshot.json beside the log'):
            self.text(value)

    def test_t3_owner_machine_facts(self):
        three, four, ten, sixteen = '3', '4', '10', '16'
        for value in ("# above it (on the PC's runners nproc counts the host's " + sixteen + '\n# CPUs and cpu.max allows ' + three + ').',
                      "The owner's Mac has " + ten + ' cores.',
                      "The PC's runner container has a CPU quota of " + three + '.',
                      'Measured on the Mac, pinned to ' + four + ' vCPUs.',
                      "# keep the PC's " + three + '-CPU runners busy.',
                      'The Mac has a ' + ten + '-core chip.',
                      "The owner's runner is pinned to " + four + ' - vCPUs.'):
            self.text(value, 'T3')
        for value in ("# cpus: nproc, but no more than the container's cgroup v2 cpu.max allows,\n# at its own level or any above it.",
                      'A GitHub-hosted runner has ' + four + ' CPUs.',
                      'For example, an invented PC whose host counts ' + sixteen + ' CPUs while cpu.max allows ' + three + '.',
                      "The PC's runners are listed in the private machine notes.",
                      'A GitHub-hosted runner has ' + four + '-CPU machines.',
                      "For example, an invented PC's " + three + '-CPU runners.',
                      "The PC's multi-core build and the Mac's x86_64-cores note.",
                      "The PC's CPU-bound jobs run on the Mac's per-core queue."):
            self.text(value)

    def test_t3_machine_facts_any_case_and_bound_to_their_own_sentence(self):
        four, sixteen = '4', '16'
        for value in ('The PC has ' + sixteen + ' cores.', 'The Mac has ' + four + ' CPUs.',
                      'THE MAC HAS ' + four + ' CPUS.',
                      '# the PC has ' + sixteen + ' cores.\n# Synthetic regression cases follow.',
                      '# Synthetic regression cases follow.\n# the PC has ' + sixteen + ' cores.',
                      'An invented example comes later. The PC has ' + sixteen + ' cores.',
                      '# Synthetic regression cases follow\n# the PC has ' + sixteen + ' cores',
                      '# the PC has ' + sixteen + ' cores\n# Synthetic regression cases follow',
                      'The PC is the always-on hub. Its CPU quota is ' + four + '.'):
            self.text(value, 'T3')
        for value in ('# For example, an invented PC whose host counts ' + sixteen + '\n# CPUs.',
                      'The Mac in this synthetic case has ' + four + ' CPUs.',
                      'E.g. the PC has ' + sixteen + ' cores.'):
            self.text(value)

    def test_t3_refused_locations_are_redacted_in_diagnostics(self):
        suffix, fact = 'aB3xQ9', 'the PC has ' + '16' + ' cores'
        names = ('helpers/snapshot.' + suffix + '/state.json', 'notes/' + fact + '.md')
        for name in names:
            path = self.tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('clean\n')
        result = self.call('--tree', self.tree)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout.count('T3 '), 2, result.stdout)
        self.make_repo()
        for name in names:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('clean\n')
        self.git('add', '.')
        rc, out, err = self.scan_git('--git-tree', self.git('write-tree'))[:3]
        self.assertEqual((rc, out.count('T3 ')), (1, 2), out)
        for output in (result.stdout + result.stderr, out + err):
            self.assertNotIn(suffix, output)
            self.assertNotIn('16 cores', output)

    def test_literals_and_unreadable_inputs(self):
        literals = self.root / 'literals.txt'
        literals.write_text('planted-machine\n')
        note = self.tree / 'note'
        note.write_text('a planted-machine appears')
        r = self.call('--tree', self.tree, '--literals', literals, '--require-literals')
        self.verdict(r, 'T3')
        self.assertNotIn('planted-machine', r.stdout)
        self.assertIn('literals: used', r.stdout)
        self.verdict(self.call('--tree', self.tree, '--require-literals'), 'READ')
        self.verdict(self.call('--title-file', self.root / 'absent'), 'READ')
        self.verdict(self.call('--tree', self.tree, '--literals', self.root / 'absent'), 'READ')
        self.verdict(self.call('--tree', self.root / 'absent'), 'READ')

        clean = self.root / 'synthetic-clean.txt'
        clean.write_text('Synthetic ordinary documentation.\n')
        empty = self.root / 'synthetic-empty.txt'
        empty.touch()
        invalid = self.root / 'synthetic-invalid.txt'
        invalid.write_bytes(b'\xffsynthetic-input-value')
        blank = self.root / 'synthetic-blank.txt'
        blank.write_text(' \n')
        empty_tree = self.root / 'synthetic-empty-tree'
        empty_tree.mkdir()
        absent = self.root / 'synthetic-unreadable-name'
        note.write_text(clean.read_text())
        rows = [
            ('clean-title', ['--title-file', clean], None),
            ('empty-title', ['--title-file', empty], None),
            ('clean-body', ['--body-file', clean], None),
            ('empty-body', ['--body-file', empty], None),
            ('clean-tree', ['--tree', self.tree], None),
            ('empty-tree', ['--tree', empty_tree], None),
            ('combined', ['--tree', self.tree, '--title-file', clean, '--body-file', clean], None),
            ('missing-title', ['--title-file', absent], 'title'),
            ('missing-body', ['--body-file', absent], 'body'),
            ('missing-tree', ['--tree', absent], 'tree'),
            ('file-as-tree', ['--tree', clean], 'tree'),
            ('directory-as-title', ['--title-file', self.tree], 'title'),
            ('invalid-title', ['--title-file', invalid], 'title'),
            ('invalid-body', ['--body-file', invalid], 'body'),
            ('missing-literals', ['--title-file', clean, '--literals', absent], 'literals'),
            ('empty-literals', ['--title-file', clean, '--literals', empty], 'literals'),
            ('blank-literals', ['--title-file', clean, '--literals', blank], 'literals'),
            ('invalid-literals', ['--title-file', clean, '--literals', invalid], 'literals'),
            ('required-literals', ['--title-file', clean, '--require-literals'], 'literals'),
            ('combined-missing-title', ['--tree', self.tree, '--title-file', absent, '--body-file', clean], 'title'),
            ('combined-missing-body', ['--tree', self.tree, '--title-file', clean, '--body-file', absent], 'body'),
            ('no-input', [], 'input'),
            ('missing-repo', ['--git-tree', 'HEAD'], 'input'),
        ]
        for name, args, role in rows:
            for used in (False, True):
                if '--literals' in args or '--require-literals' in args:
                    options = ['--require-literals'] if used else []
                    report = 'not used'
                else:
                    options = ['--literals', literals, '--require-literals'] if used else []
                    report = 'used' if used else 'not used'
                with self.subTest(case=name, literals=used):
                    r = self.call(*args, *options)
                    output = (f'READ {role}:1\n' if role else '') + f'literals: {report}\n'
                    self.assertEqual((r.returncode, r.stdout, r.stderr), (int(role is not None), output, ''))

    def test_private_paths(self):
        for name in ('private/empty', 'private/nested/file', 'docs/grills/planted.md', 'docs/grills/README.md/child'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / name
                path.parent.mkdir(parents=True)
                path.touch()
                self.verdict(self.call('--tree', folder), 'F1')
        path = self.tree / 'docs/grills/README.md'
        path.parent.mkdir(parents=True)
        path.write_text('Mentions private/machines.md as words.')
        self.verdict(self.call('--tree', self.tree))
        (self.tree / 'private').symlink_to(self.root / 'absent')
        self.verdict(self.call('--tree', self.tree), 'F1')

    def test_binary_and_symlink(self):
        (self.tree / 'image.png').write_bytes(b'\x89PNG\0' + THREAD.encode())
        self.verdict(self.call('--tree', self.tree))
        (self.tree / 'link').symlink_to(THREAD)
        self.verdict(self.call('--tree', self.tree), 'T1')

    def test_contract_bad_block_exception(self):
        for name, rule in (('contracts/open-development.v1.md', None), ('other.md', 'T1')):
            folder = self.root / name.replace('/', '_')
            folder.mkdir()
            path = folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('```bad\n' + THREAD + '\n```\n```good\nclean\n```\n')
            self.verdict(self.call('--tree', folder), rule)
            if rule is None:
                path.write_text('```bad\n' + THREAD + '\n```\n```good\n' + THREAD + '\n```\n')
                self.verdict(self.call('--tree', folder), 'T1')

    def test_runtime_root_maps_only_the_contract_at_an_archive_runtime_path(self):
        bad = '```bad\n' + THREAD + '\n```\n'
        for name, roots, rule in (('t1/runtime/contracts/open-development.v1.md', ('t1',), None),
                                  ('t2/runtime/contracts/open-development.v1.md', ('t1', 't2'), None),
                                  ('t1/runtime/contracts/open-development.v1.md', (), 'T1'),
                                  ('other/runtime/contracts/open-development.v1.md', ('t1',), 'T1'),
                                  ('t1/contracts/open-development.v1.md', ('t1',), 'T1'),
                                  ('t1/runtime/runtime/contracts/open-development.v1.md', ('t1',), 'T1'),
                                  ('t1/runtime/skills/contracts/open-development.v1.md', ('t1',), 'T1'),
                                  ('t1/runtime/other.md', ('t1',), 'T1')):
            with self.subTest(name=name, roots=roots):
                folder = self.root / ('rt-' + name.replace('/', '_') + '-'.join(roots))
                (folder / name).parent.mkdir(parents=True)
                (folder / name).write_text(bad)
                args = [x for root in roots for x in ('--runtime-root', root)]
                self.verdict(self.call('--tree', folder, *args), rule)
                if rule is None:
                    (folder / name).write_text(bad + THREAD + '\n')
                    self.verdict(self.call('--tree', folder, *args), 'T1')

    def test_runtime_root_keeps_every_other_rule_and_needs_a_tree(self):
        folder = self.root / 'rt-rules'
        (folder / 't1/runtime/private').mkdir(parents=True)
        (folder / 't1/runtime/private/note.md').write_text('clean\n')
        self.verdict(self.call('--tree', folder, '--runtime-root', 't1'))
        (folder / 't1/runtime/note.md').write_text(BAD_MAIL + '\n')
        self.verdict(self.call('--tree', folder, '--runtime-root', 't1'), 'T3')
        for root in ('', 'a/b', '.', '..'):
            with self.subTest(root=root):
                self.verdict(self.call('--tree', self.tree, '--runtime-root', root), 'READ')
        self.verdict(self.call('--title-file', folder / 't1/runtime/private/note.md', '--runtime-root', 't1'), 'READ')

    def workflow(self, body, rule=None):
        path = self.tree / '.github/workflows/test.yml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        self.verdict(self.call('--tree', self.tree), rule)

    def test_hosted_workflows(self):
        labels = ('ubuntu-latest', 'ubuntu-24.04', 'ubuntu-slim', 'macos-15', 'macos-15-intel')
        for label in labels:
            for runner in (label, '[' + label + ']', "'" + label + "'"):
                self.workflow('on: push\njobs:\n  test:\n    runs-on: ' + runner + '\n    steps:\n      - run: echo ok\n')
        for variable in ('CI_RUNS_ON', 'CI_RUST_RUNS_ON'):
            self.workflow("jobs:\n  test:\n    runs-on: ${{ vars." + variable + " || 'ubuntu-24.04' }}\n")
        self.workflow('jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-latest, macos-15]\n')
        self.workflow('jobs:\n  test:\n    runs-on:\n      - ubuntu-latest\n')
        local = self.tree / '.github/workflows/local.yml'
        local.write_text('jobs:\n  reusable:\n    runs-on: ubuntu-latest\n')
        self.workflow('jobs:\n  test:\n    uses: ./.github/workflows/local.yml\n')

    def test_refused_workflows(self):
        for runner in ('self-hosted', '[self-hosted, Linux, X64]', 'unknown', '[ubuntu-latest, macos-15]',
                       '{group: planted}', '${{ inputs.runner }}',
                       "${{ vars.OTHER || 'ubuntu-latest' }}", "${{ vars.CI_RUNS_ON || 'unknown' }}"):
            self.workflow('jobs:\n  test:\n    runs-on: ' + runner + '\n', 'F2')
        for body in (
            'jobs:\n  test:\n    uses: someone/repo/.github/workflows/x.yml@main\n',
            'jobs:\n  test:\n    runs-on: ubuntu-latest\n    runs-on: self-hosted\n',
            'jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-latest]\n        include:\n          - os: self-hosted\n',
            'jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: ["${{ inputs.runner }}"]\n',
            'jobs: ${{ inputs.jobs }}\n',
            'jobs: {test: {runs-on: self-hosted}}\n',
            'jobs:\n  test: &job\n    runs-on: ubuntu-latest\n  other:\n    <<: *job\n    runs-on: self-hosted\n',
            'jobs:\n  test:\n    runs-on: |\n      self-hosted\n',
        ):
            self.workflow(body, 'F2')

    def test_actual_repository_workflows_pass_f2(self):
        folder = self.tree / '.github/workflows'
        folder.mkdir(parents=True)
        sources = HERE.parent.parent / '.github/workflows'
        for required in ('ci.yml', 'privacy.yml'):
            self.assertTrue((sources / required).is_file(),
                            'missing required workflow input: ' + required)
        for source in sources.iterdir():
            if source.suffix in ('.yml', '.yaml'):
                (folder / source.name).write_bytes(source.read_bytes())
        self.verdict(self.call('--tree', self.tree))

    def test_actual_workflow_proof_requires_both_inputs(self):
        for missing in ('ci.yml', 'privacy.yml'):
            with self.subTest(missing=missing):
                checkout = self.root / missing
                tools = checkout / 'tools/privacy-check'
                shutil.copytree(HERE, tools)
                workflows = checkout / '.github/workflows'
                shutil.copytree(HERE.parent.parent / '.github/workflows', workflows)
                (workflows / missing).unlink()
                result = subprocess.run([
                    sys.executable, '-I', str(tools / 'test_check.py'),
                    'Check.test_actual_repository_workflows_pass_f2',
                ], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('missing required workflow input: ' + missing,
                              result.stdout + result.stderr)

    def test_private_runner_branch_is_proved_unreachable_in_public(self):
        prefix = ("${{ github.event_name == 'pull_request' && "
                  "github.event.pull_request.head.repo.full_name != github.repository "
                  "&& 'ubuntu-24.04' || github.repository == 'jparker2006/ClosedWiz' && (")
        suffix = " || 'namespace-profile-closedwiz-rust') || 'ubuntu-24.04' }}"
        for route in ('vars.CI_RUST_RUNS_ON', 'vars.CI_WEB_RUNS_ON',
                      'vars.CI_SMALL_RUNS_ON || vars.CI_WEB_RUNS_ON'):
            runner = prefix + route + suffix
            with self.subTest(route=route):
                self.workflow('jobs:\n  test:\n    runs-on: ' + runner + '\n')
            mutants = [
                runner.replace("github.repository == 'jparker2006/ClosedWiz'", "github.repository != 'jparker2006/ClosedWiz'"),
                runner.replace("'jparker2006/ClosedWiz'", "'openwizdev/OpenWiz'"),
                runner.replace("'jparker2006/ClosedWiz'", "'owner/repo'"),
                runner.replace(" && (", " && ").replace(") ||", " ||"),
                runner.replace("head.repo.full_name !=", "head.repo.full_name =="),
                runner.replace("github.event_name == 'pull_request'", "github.event_name == 'push'"),
                runner.replace(route, 'vars.OTHER'),
                runner.replace("'ubuntu-24.04' || github.repository", "'self-hosted' || github.repository"),
            ]
            for label in ('self-hosted', 'namespace-profile-closedwiz-rust', 'unknown'):
                mutants.append(runner.replace("|| 'ubuntu-24.04' }}", "|| '" + label + "' }}"))
                mutants.append("${{ " + route + " || '" + label + "' }}")
            mutants.extend([
                "${{ github.repository == 'jparker2006/ClosedWiz' && (" + route + suffix,
                "${{ " + route + suffix,
                runner[:-3] + " || vars.CI_WEB_RUNS_ON }}",
            ])
            for mutant in mutants:
                with self.subTest(route=route, mutant=mutant):
                    self.workflow('jobs:\n  test:\n    runs-on: ' + mutant + '\n', 'F2')

    def git(self, *args, **env):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True,
                                       env={**os.environ, **self.git_env, **env}, stderr=subprocess.DEVNULL).strip()

    def make_repo(self):
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git_env = dict(GIT_AUTHOR_NAME='Synthetic', GIT_COMMITTER_NAME='Synthetic',
                            GIT_AUTHOR_EMAIL=PRIVATE_MAIL, GIT_COMMITTER_EMAIL=PRIVATE_MAIL,
                            GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q')
        self.git('commit', '--allow-empty', '-qm', 'synthetic root')
        self.public_root = self.git('rev-parse', 'HEAD')
        self.git('commit', '--allow-empty', '-qm', 'synthetic anchor')
        self.anchor = self.git('rev-parse', 'HEAD')
        spec = importlib.util.spec_from_file_location('privacy', CLI)
        self.checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.checker)

    def history(self, rule=None, base=None):
        out = io.StringIO()
        with patch.multiple(self.checker, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
            rc = self.checker.main(['--repo', str(self.repo), '--base', base or self.anchor, '--head', 'HEAD'])
        self.assertEqual(rc, 1 if rule else 0, out.getvalue())
        if rule:
            self.assertIn(rule + ' ', out.getvalue())

    def scan_git(self, *args):
        children, start = [], subprocess.Popen
        def spawn(*a, **kw):
            child = start(*a, **kw)
            children.append(child)
            return child
        out, err = io.StringIO(), io.StringIO()
        with patch.object(subprocess, 'Popen', spawn), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.checker.main(['--repo', str(self.repo), *args])
        for child in children:
            self.assertIsNotNone(child.poll(), 'Git child was not reaped')
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    self.assertTrue(stream.closed, 'Git pipe was not closed')
        return rc, out.getvalue(), err.getvalue(), len(children)

    def test_git_tree_blob_process_budget(self):
        self.make_repo()
        for i in range(8):
            (self.repo / str(i)).write_text('synthetic file ' + str(i))
        self.git('add', '.')
        tree = self.git('write-tree')
        self.assertEqual(self.scan_git('--git-tree', tree), (0, 'literals: not used\n', '', 3))
        self.git('commit', '-qm', 'synthetic files')
        with patch.multiple(self.checker, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor):
            self.assertEqual(self.scan_git('--git-tree', tree, '--head', 'HEAD', '--base', self.anchor),
                             (0, 'literals: not used\n', '', 14))

    def test_git_blob_verdicts_and_framing(self):
        self.make_repo()
        for name, data in (
            ('.github/workflows/binary.yml', b'\0'),
            ('.github/workflows/caller.yml', b'jobs:\n  test:\n    uses: ./.github/workflows/absent.yml\n'),
            ('.github/workflows/hosted.yml', b'jobs:\n  test:\n    runs-on: ubuntu-latest\n'),
            ('a-empty', b''), ('b-raw', b'ordinary'), ('c-image', b'\x89PNG\0' + THREAD.encode()),
            ('contracts/open-development.v1.md', ('```bad\n' + THREAD + '\n```\n').encode()),
            ('other.md', ('```bad\n' + THREAD + '\n```\n').encode()),
            ('private/empty', b''), ('unknown', b'\xff'),
        ):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.repo / 'b-raw').chmod(0o755)
        (self.repo / 'd-link').symlink_to(THREAD)
        self.git('add', '.')
        tree = self.git('write-tree')
        self.git('replace', self.git('rev-parse', ':d-link'), self.git('rev-parse', ':b-raw'))
        self.assertEqual(self.scan_git('--git-tree', tree)[:3], (1,
            'F2 tree:".github/workflows/binary.yml":1\nT1 tree:"d-link":1\n'
            'T1 tree:"other.md":2\nF1 tree:"private/empty":1\nREAD tree:"unknown":1\n'
            'F2 tree:".github/workflows/caller.yml":1\nliterals: not used\n', ''))

    def test_missing_and_corrupt_git_blobs(self):
        self.make_repo()
        (self.repo / 'note').write_text('ordinary')
        self.git('add', '.')
        tree = self.git('write-tree')
        sha = self.git('rev-parse', ':note')
        obj = self.repo / '.git/objects' / sha[:2] / sha[2:]
        obj.unlink()
        for corrupt in (False, True):
            if corrupt:
                obj.write_bytes(b'synthetic corrupt object ' + THREAD.encode())
            self.assertEqual(self.scan_git('--git-tree', tree)[:3],
                             (1, 'READ input:1\nliterals: not used\n', ''))
        self.assertEqual(self.scan_git('--git-tree', '0' * 40),
                         (1, 'READ input:1\nliterals: not used\n', '', 1))
        (self.repo / '.git/objects' / tree[:2] / tree[2:]).unlink()
        self.assertEqual(self.scan_git('--git-tree', tree)[:3],
                         (1, 'READ input:1\nliterals: not used\n', ''))

    def test_git_batch_faults_refuse_and_reap(self):
        self.make_repo()
        (self.repo / 'note').write_text('ordinary')
        self.git('add', '.')
        tree = self.git('write-tree')
        start = subprocess.Popen
        for response, status in (
            (b'@ missing\n', 0), (b'0' * 40 + b' blob 0\n\n', 0),
            (b'@ tree 0\n\n', 0), (b'@ blob -1\n', 0), (b'@ blob nope\n', 0),
            (b'@ blob 9223372036854775808\n', 0),
            (b'@ blob 2\nx', 0), (b'@ blob 1\nx!', 0), (b'@ blob 0\n\n', 1),
            (b'@ blob 0\n\n', 'timeout'),
        ):
            def faulty(command, **kw):
                if command[-1] == '--batch':
                    script = ('import sys; sha=sys.stdin.buffer.readline().strip(); '
                              'sys.stderr.write(' + repr(THREAD) + '); '
                              'sys.stdout.buffer.write(' + repr(response) + '.replace(b"@",sha)); '
                              'sys.stdout.buffer.flush(); sys.exit(' + str(1 if status == 1 else 0) + ')')
                    command = [sys.executable, '-I', '-c', script]
                child = start(command, **kw)
                if status == 'timeout' and command[0] == sys.executable:
                    wait = child.wait
                    def timed_out(timeout=None):
                        if timeout is not None:
                            raise subprocess.TimeoutExpired('synthetic batch', timeout)
                        return wait()
                    child.wait = timed_out
                return child
            with self.subTest(response=response, status=status), patch.object(subprocess, 'Popen', faulty):
                self.assertEqual(self.scan_git('--git-tree', tree)[:3],
                                 (1, 'READ input:1\nliterals: not used\n', ''))

    def test_clean_history_and_commit_emails(self):
        self.make_repo()
        for email in (PRIVATE_MAIL, 'robin@users.noreply.github.com', 'noreply@github.com'):
            self.git('commit', '--allow-empty', '-qm', 'clean', GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_EMAIL=email)
        self.history()
        self.verdict(self.call('--repo', self.repo, '--base', self.anchor, '--head', 'HEAD'), 'C1')

    def test_bad_intermediate_commit_messages(self):
        self.make_repo()
        for text, rule in ((THREAD, 'T1'), (DECIDER + ': "planted"', 'T2'), (BAD_MAIL, 'T3')):
            self.git('reset', '--soft', self.anchor)
            self.git('commit', '--allow-empty', '-qm', 'subject\n\n' + text)
            self.git('commit', '--allow-empty', '-qm', 'clean head')
            self.history(rule)

    def test_bad_author_or_committer(self):
        self.make_repo()
        for key in ('GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL'):
            for email in (BAD_MAIL, 'robin@example.com', 'git@github.com', '@users.noreply.github.com'):
                self.git('reset', '--soft', self.anchor)
                self.git('commit', '--allow-empty', '-qm', 'clean', **{key: email})
                self.history('C3')

    def test_merged_private_ancestry_and_replace_objects(self):
        self.make_repo()
        self.git('checkout', '--orphan', 'private-branch')
        self.git('commit', '--allow-empty', '-qm', 'synthetic private root')
        private = self.git('rev-parse', 'HEAD')
        self.git('checkout', '--detach', self.anchor)
        self.git('merge', '--allow-unrelated-histories', '--no-ff', '-m', 'merged branch', private)
        merged = self.git('rev-parse', 'HEAD')
        self.history('C1')
        self.git('replace', merged, self.anchor)
        self.history('C1')

    def test_missing_anchor_shallow_grafts_and_reads(self):
        self.make_repo()
        self.git('checkout', '--detach', self.public_root)
        self.history('C1', self.public_root)
        self.git('checkout', '--detach', self.anchor)
        (self.repo / '.git/info/grafts').write_text(self.anchor + '\n')
        self.history('C1')
        (self.repo / '.git/info/grafts').unlink()
        (self.repo / '.git/shallow').write_text(self.anchor + '\n')
        self.history('C1')
        (self.repo / '.git/shallow').unlink()
        self.verdict(self.call('--repo', self.repo, '--head', 'missing', '--base', self.anchor), 'READ')


    def test_hook_rejects_private_ancestry_before_fast_checks(self):
        self.make_repo()
        head = self.git('rev-parse', 'HEAD')
        line = f'refs/heads/main {head} refs/heads/main {self.anchor}\n'
        r = subprocess.run(['sh', str(HERE.parent.parent / '.githooks/pre-push'), 'origin',
                            'https://github.com/openwizdev/OpenWiz.git'], cwd=self.repo,
                           input=line, text=True, capture_output=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('C1 ', r.stdout + r.stderr)
        self.assertNotIn('cargo fmt', r.stdout + r.stderr)

    def test_ci_private_noop_never_opens_event_or_tree(self):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'ci.py')], cwd=self.root,
                           env={**os.environ, 'GITHUB_REPOSITORY': 'jparker2006/ClosedWiz',
                                'GITHUB_EVENT_PATH': str(self.root / 'absent')}, capture_output=True, text=True)
        self.verdict(r)
        self.assertIn('private repository: no public scan', r.stdout)


    def test_allowed_emails_in_quoted_text(self):
        self.text("'noreply@github.com' and 'git@github.com'")

    def test_intermediate_private_file_cannot_hide_behind_clean_head(self):
        self.make_repo()
        path = self.repo / 'planted.txt'
        path.write_text(THREAD)
        self.git('add', '.')
        self.git('commit', '-qm', 'add file')
        path.unlink()
        self.git('add', '-u')
        self.git('commit', '-qm', 'remove file')
        out = io.StringIO()
        with patch.multiple(self.checker, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
            rc = self.checker.main(['--repo', str(self.repo), '--base', self.anchor, '--head', 'HEAD', '--git-tree', 'HEAD'])
        self.assertEqual(rc, 1, out.getvalue())
        self.assertIn('T1 ', out.getvalue())

    def test_local_reusable_workflow_must_be_present(self):
        self.workflow('jobs:\n  test:\n    uses: ./.github/workflows/absent.yml\n', 'F2')


    def load_adapter(self, name):
        spec = importlib.util.spec_from_file_location('privacy_' + name, HERE / (name + '.py'))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        return adapter

    def test_hook_checks_git_tree_not_uncommitted_files_and_reads_literals(self):
        self.make_repo()
        hook = self.load_adapter('hook')
        path = self.repo / 'note'
        path.write_text('clean')
        self.git('add', '.')
        self.git('commit', '-qm', 'public change')
        path.write_text(THREAD)
        args = ['--url', 'git@github.com:openwizdev/OpenWiz.git', '--repo', str(self.repo),
                '--base', self.anchor, '--head', 'HEAD']
        def run(extra=()):
            out = io.StringIO()
            with patch.multiple(hook.check, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
                rc = hook.main(args + list(extra))
            return rc, out.getvalue()
        self.assertEqual(run()[0], 0)
        self.git('add', '.')
        self.git('commit', '-qm', 'planted file')
        path.write_text('clean uncommitted fix')
        rc, out = run()
        self.assertEqual(rc, 1, out)
        self.assertIn('T1 ', out)
        private = self.repo.parent / 'ClosedWiz'
        private.mkdir()
        rc, out = run(['--literals', str(private / 'absent-list')])
        self.assertEqual(rc, 1)
        self.assertIn('READ ', out)
        self.assertIn('literals: not used', out)

    def test_hook_literals_are_explicit_and_ignore_a_private_named_sibling(self):
        self.make_repo()
        hook = self.load_adapter('hook')
        (self.repo / 'note').write_text('SYNTHETIC_LITERAL_MARKER')
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic public change')
        guessed = self.repo.parent / 'ClosedWiz/private/evidence/open-development/privacy-check'
        guessed.mkdir(parents=True)
        (guessed / 'literals.txt').write_text('SYNTHETIC_LITERAL_MARKER\n')
        args = ['--url', 'https://github.com/openwizdev/OpenWiz', '--repo', str(self.repo), '--head', 'HEAD', '--base', self.anchor]
        def run(extra):
            out = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch.multiple(hook.check, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
                rc = hook.main(args + extra)
            return rc, out.getvalue()
        rc, out = run([])
        self.assertEqual(rc, 0, out)
        self.assertIn('literals: not used', out)
        explicit = self.root / 'synthetic-private-list.txt'
        explicit.write_text('SYNTHETIC_LITERAL_MARKER\n')
        rc, out = run(['--literals', str(explicit)])
        self.assertEqual(rc, 1, out)
        self.assertIn('literals: used', out)
        rc, out = run(['--literals', str(self.root / 'absent-list')])
        self.assertEqual(rc, 1, out)
        self.assertIn('READ ', out)

    def test_ci_public_event_inputs(self):
        self.make_repo()
        adapter = self.load_adapter('ci')
        self.git('commit', '--allow-empty', '-qm', 'clean public commit')
        head = self.git('rev-parse', 'HEAD')
        event_path = self.root / 'event.json'
        def run(kind, event):
            event_path.write_text(event if isinstance(event, str) else json.dumps(event))
            out = io.StringIO()
            with patch.dict(os.environ, GITHUB_REPOSITORY='openwizdev/OpenWiz', GITHUB_EVENT_NAME=kind,
                            GITHUB_EVENT_PATH=str(event_path)), contextlib.chdir(self.repo), patch.multiple(
                                adapter.check, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
                rc = adapter.main()
            return rc, out.getvalue()
        pr = dict(base={'sha': self.anchor}, head={'sha': head}, title='clean title', body='clean body')
        for kind, event in (
            ('pull_request', {'pull_request': pr}),
            ('push', {'before': self.anchor, 'after': head}),
            ('push', {'before': '0' * 40, 'after': head}),
            ('merge_group', {'merge_group': {'base_sha': self.anchor, 'head_sha': head}}),
        ):
            rc, out = run(kind, event)
            self.assertEqual(rc, 0, out)
        for key in ('title', 'body'):
            for text, rule in ((THREAD, 'T1'), (DECIDER + ': "planted"', 'T2'), (BAD_MAIL, 'T3')):
                rc, out = run('pull_request', {'pull_request': {**pr, key: text}})
                self.assertEqual(rc, 1, out)
                self.assertIn(rule + ' pr-' + key, out)
        for kind, event in (
            ('pull_request', {'pull_request': {**pr, 'body': []}}),
            ('pull_request', '{"pull_request": null, "pull_request": ' + json.dumps(pr) + '}'),
            ('push', {'before': 'missing', 'after': head}),
            ('unexpected', {}),
        ):
            rc, out = run(kind, event)
            self.assertEqual(rc, 1, out)
            self.assertIn('READ ', out)

    def published_main(self):
        self.make_repo()
        self.git('commit', '--allow-empty', '-qm', 'published\n\n' + THREAD)
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.git('checkout', '-qb', 'topic')
        self.git('commit', '--allow-empty', '-qm', 'clean pushed commit')

    def test_first_push_scans_from_merge_base_with_destination_main(self):
        self.published_main()
        hook = self.root / 'hook-root'
        (hook / '.githooks').mkdir(parents=True)
        shutil.copy(HERE.parent.parent / '.githooks/pre-push', hook / '.githooks/pre-push')
        shutil.copytree(HERE, hook / 'tools/privacy-check', ignore=shutil.ignore_patterns('__pycache__', 'test_*'))
        policy = hook / 'tools/privacy-check/check.py'
        text = policy.read_text()
        for name, value in (('PUBLIC_ROOT', self.public_root), ('PUBLIC_ANCHOR', self.anchor)):
            text, count = re.subn(name + " = '[0-9a-f]{40}'", name + " = '" + value + "'", text)
            self.assertEqual(count, 1)
        policy.write_text(text)
        remotes = self.root / 'remotes'
        url = lambda name: 'ssh://synthetic.invalid/' + name + '.git'
        adapter = hook / 'tools/privacy-check/hook.py'
        text, count = re.subn(r'PUBLIC_URLS = \([^)]*\)', 'PUBLIC_URLS = ' + repr(tuple(url(x) for x in ('published', 'fresh', 'empty', 'ahead'))), adapter.read_text())
        self.assertLessEqual(count, 1)
        adapter.write_text(text)
        ssh = self.root / 'fake-ssh'
        reached = self.root / 'reached'
        ssh.write_text('#!/bin/sh\nfor a; do cmd=$a; done\nsub=${cmd%% *}\neval "set -- ${cmd#* }"\n'
                       'echo "$1" >> "' + str(reached) + '"\n'
                       'exec git "${sub#git-}" "' + str(remotes) + '$1"\n')
        ssh.chmod(0o755)
        self.git('config', 'core.sshCommand', str(ssh))
        published, fresh = self.git('rev-parse', 'refs/remotes/origin/main'), self.anchor
        for name, main in (('published', published), ('fresh', fresh), ('empty', None), ('other', published)):
            subprocess.run(['git', 'init', '-q', '--bare', str(remotes / (name + '.git'))], check=True)
            if main:
                self.git('push', '-q', str(remotes / (name + '.git')), main + ':refs/heads/main')
        (self.root / 'home').mkdir()
        clean = {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
                 'HOME': str(self.root / 'home'), 'XDG_CONFIG_HOME': str(self.root / 'home'),
                 'XDG_CACHE_HOME': str(self.root / 'cache')}
        def push(name, **env):
            line = 'refs/heads/topic {} refs/heads/topic {}\n'.format(self.git('rev-parse', 'HEAD'), '0' * 40)
            r = subprocess.run(['sh', str(hook / '.githooks/pre-push'), 'origin', url(name)],
                               cwd=self.repo, input=line, text=True, capture_output=True, env={**clean, **env})
            return r.returncode, r.stdout + r.stderr
        self.git('remote', 'add', 'origin', url('published'))
        rc, out = push('published')
        self.assertEqual(rc, 0, out)
        self.assertIn('range: from the merge-base with upstream', out)
        self.git('commit', '--allow-empty', '-qm', 'pushed\n\n' + THREAD)
        self.assertEqual(push('published')[0], 1)
        self.git('reset', '-q', '--hard', 'HEAD~1')
        cases = (
            ('split push URL', 'fresh', [('remote.origin.url', str(remotes / 'published.git')),
                                         ('remote.origin.pushurl', url('fresh'))]),
            ('retargeted URL, stale ref', 'fresh', [('remote.origin.url', url('fresh'))]),
            ('destination has no main', 'empty', [('remote.origin.url', url('empty'))]),
            ('URL Git would rewrite', 'empty', [('remote.origin.url', url('empty')),
                                                ('url.' + url('published') + '.insteadOf', url('empty'))]),
        )
        ssh_value = str(ssh)
        overrides = (
            ('git -c core.sshCommand', {'GIT_CONFIG_PARAMETERS': "'core.sshcommand'='" + ssh_value + "'"}),
            ('GIT_CONFIG_COUNT', {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.sshCommand', 'GIT_CONFIG_VALUE_0': ssh_value}),
            ('GIT_SSH_COMMAND', {'GIT_SSH_COMMAND': ssh_value}),
            ('GIT_SSH', {'GIT_SSH': ssh_value}),
            ('GIT_DIR', {'GIT_DIR': str(self.repo / '.git')}),
        )
        self.git('config', 'remote.origin.url', url('published'))
        for case, env in overrides + (('off-allowlist URL', None),):
            with self.subTest(case=case):
                rc, out = push('other') if env is None else push('published', **env)
                self.assertEqual(rc, 1, out)
                self.assertIn('T1 ', out)
                self.assertNotIn('range: from the merge-base', out)
        self.git('config', '--unset-all', 'remote.origin.url')
        for case, name, config in cases:
            with self.subTest(case=case):
                for key, value in config:
                    self.git('config', key, value)
                self.assertEqual(self.git('rev-parse', 'refs/remotes/origin/main'), published)
                rc, out = push(name)
                self.assertEqual(rc, 1, out)
                self.assertIn('T1 ', out)
                for key, _ in config:
                    self.git('config', '--unset-all', key)
        ahead = str(remotes / 'ahead.git')
        subprocess.run(['git', 'init', '-q', '--bare', ahead], check=True)
        self.git('push', '-q', ahead, published + ':refs/heads/main')
        moved = self.git('-C', ahead, 'commit-tree', published + '^{tree}', '-p', published, '-m', 'merged later')
        self.git('-C', ahead, 'update-ref', 'refs/heads/main', moved)
        self.git('config', 'remote.origin.url', url('ahead'))
        rc, out = push('ahead')
        self.assertEqual(rc, 0, out)
        self.assertIn('range: from the merge-base with upstream', out)
        self.git('commit', '--allow-empty', '-qm', 'pushed\n\n' + THREAD)
        self.assertEqual(push('ahead')[0], 1)
        self.git('reset', '-q', '--hard', 'HEAD~1')
        other = remotes / 'other.git'
        bundle = self.root / 'other.bundle'
        self.git('-C', str(other), 'bundle', 'create', '-q', str(bundle), 'refs/heads/main')
        (self.root / 'bundles').write_text('[bundle]\n\tversion = 1\n\tmode = all\n\theuristic = creationToken\n'
                                           '[bundle "b"]\n\turi = ' + bundle.as_uri() + '\n\tcreationToken = 1\n')
        side_cases = (
            ('promisor remote', [('core.repositoryformatversion', '1'), ('extensions.partialClone', 'spy'),
                                 ('remote.spy.url', url('other')), ('remote.spy.promisor', 'true')]),
            ('bundle source', [('fetch.bundleURI', (self.root / 'bundles').as_uri())]),
            ('per-URL remote setting', [('remote.' + url('ahead') + '.promisor', 'true')]),
        )
        for n, (case, config) in enumerate(side_cases):
            with self.subTest(case=case):
                step = self.git('-C', ahead, 'commit-tree', published + '^{tree}', '-p', moved, '-m', 'merged %d' % n)
                self.git('-C', ahead, 'update-ref', 'refs/heads/main', step)
                for key, value in config:
                    self.git('config', key, value)
                reached.unlink(missing_ok=True)
                try:
                    rc, out = push('ahead')
                    self.assertNotIn('/other.git', reached.read_text() if reached.exists() else '')
                    self.assertEqual(self.git('for-each-ref', 'refs/bundles'), '')
                    if case == 'per-URL remote setting':
                        self.assertEqual(rc, 1, out)
                        self.assertIn('T1 ', out)
                finally:
                    for key, _ in reversed(config):
                        self.git('config', '--unset-all', key)
                    for ref in self.git('for-each-ref', '--format=%(refname)', 'refs/bundles').split():
                        self.git('update-ref', '-d', ref)

    def test_first_push_narrowing_allowlist(self):
        hook = self.load_adapter('hook')
        canonical = 'https://github.com/openwizdev/OpenWiz'
        for url in ('https://github.com/openwizdev/OpenWiz', 'https://github.com/openwizdev/OpenWiz.git',
                    'git@github.com:openwizdev/OpenWiz', 'git@github.com:openwizdev/OpenWiz.git',
                    'https://github.com/openwizdev/openwiz', 'https://github.com/openwizdev/openwiz.git',
                    'git@github.com:openwizdev/openwiz', 'git@github.com:openwizdev/openwiz.git'):
            with self.subTest(url=url):
                self.assertTrue(hook.narrowable(url, {}))
        for url in ('https://github.com/OpenWizDev/openwiz', 'https://github.com/openwizdev/OPENWIZ',
                    'https://github.com/openwizdev/openwiz/', 'https://github.com/openwizdev/openwiz.git.git',
                    'ssh://git@github.com/openwizdev/openwiz.git', 'http://github.com/openwizdev/openwiz',
                    'https://github.com/openwizdev/openwiz-fork', 'https://github.com/jparker2006/ClosedWiz', ''):
            with self.subTest(url=url):
                self.assertFalse(hook.narrowable(url, {}))
        def scoped(*keys, **extra):
            env = {'GIT_CONFIG_COUNT': str(len(keys))}
            for i, key in enumerate(keys):
                env['GIT_CONFIG_KEY_%d' % i], env['GIT_CONFIG_VALUE_%d' % i] = key, 'synthetic'
            return {**env, **extra}
        allowed = (
            scoped('hook.synthetic.command', 'hook.synthetic.event', 'hook.synthetic.event'),
            scoped('hook.synthetic.command', GIT_EXEC_PATH='/synthetic', GIT_PREFIX='', GIT_EDITOR='true'),
        )
        for env in allowed:
            with self.subTest(env=env):
                self.assertTrue(hook.narrowable(canonical, env))
        refused = (
            scoped('core.hooksPath'),
            scoped('hook.synthetic.command', 'core.sshCommand'),
            scoped('url.synthetic.insteadOf'),
            scoped('Hook.synthetic.command'),
            scoped('xhook.synthetic.command'),
            scoped('core.hook.synthetic'),
            scoped('hook'),
            scoped('hook.synthetic.command', GIT_CONFIG_KEY_1='core.sshCommand', GIT_CONFIG_VALUE_1='synthetic'),
            {'GIT_CONFIG_KEY_0': 'hook.synthetic.command', 'GIT_CONFIG_VALUE_0': 'synthetic'},
            {'GIT_CONFIG_COUNT': '1'},
            {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'hook.synthetic.command'},
            {**scoped('hook.synthetic.command'), 'GIT_CONFIG_COUNT': ' 1'},
            {**scoped('hook.synthetic.command'), 'GIT_CONFIG_COUNT': '+1'},
            {'GIT_CONFIG_PARAMETERS': "'hook.synthetic.command'='synthetic'"},
            scoped('hook.synthetic.command', GIT_CONFIG_GLOBAL='/synthetic'),
            scoped('hook.synthetic.command', GIT_SSH_COMMAND='synthetic'),
            {'GIT_DIR': '/synthetic'},
        )
        for env in refused:
            with self.subTest(env=env):
                self.assertFalse(hook.narrowable(canonical, env))

    def test_ci_new_ref_push_scans_from_merge_base_with_main(self):
        self.published_main()
        adapter = self.load_adapter('ci')
        event_path = self.root / 'event.json'
        def run(ref):
            event = {'before': '0' * 40, 'after': self.git('rev-parse', 'HEAD'), 'ref': ref}
            event_path.write_text(json.dumps(event))
            out = io.StringIO()
            with patch.dict(os.environ, GITHUB_REPOSITORY='openwizdev/openwiz', GITHUB_EVENT_NAME='push',
                            GITHUB_EVENT_PATH=str(event_path)), contextlib.chdir(self.repo), patch.multiple(
                                adapter.check, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
                return adapter.main(), out.getvalue()
        rc, out = run('refs/heads/topic')
        self.assertEqual(rc, 0, out)
        rc, out = run('refs/heads/main')
        self.assertEqual(rc, 1, out)
        self.assertIn('T1 ', out)

    def test_ci_pull_request_scans_from_merge_base_with_base_branch(self):
        self.published_main()
        adapter = self.load_adapter('ci')
        event_path = self.root / 'event.json'
        def run(base, ref='main'):
            pr = dict(base={'sha': base, 'ref': ref}, head={'sha': self.git('rev-parse', 'HEAD')},
                      title='clean title', body='clean body')
            event_path.write_text(json.dumps({'pull_request': pr}))
            out = io.StringIO()
            with patch.dict(os.environ, GITHUB_REPOSITORY='openwizdev/OpenWiz', GITHUB_EVENT_NAME='pull_request',
                            GITHUB_EVENT_PATH=str(event_path)), contextlib.chdir(self.repo), patch.multiple(
                                adapter.check, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
                return adapter.main(), out.getvalue()
        absent = 'f' * 40
        for base in (self.anchor, absent):
            with self.subTest(base=base):
                rc, out = run(base)
                self.assertEqual(rc, 0, out)
                self.assertIn('range: from the merge-base with upstream', out)
        self.git('commit', '--allow-empty', '-qm', 'pr commit\n\n' + THREAD)
        rc, out = run(self.anchor)
        self.assertEqual(rc, 1, out)
        self.assertIn('T1 commit-1', out)
        self.git('reset', '-q', '--hard', 'HEAD~1')
        for ref in ('missing', '../main', None):
            with self.subTest(ref=ref):
                rc, out = run(absent, ref)
                self.assertEqual(rc, 1, out)
                self.assertIn('T1 ', out)
                self.assertNotIn('READ ', out)
                self.assertIn('scanning from the public anchor', out)

    def test_workflow_check_name_and_repository_runner(self):
        spec = importlib.util.spec_from_file_location('workflow', HERE / 'workflow.py')
        workflow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workflow)
        path = HERE.parent.parent / '.github/workflows/privacy.yml'
        parsed = workflow.parse(path.read_text())
        self.assertEqual(parsed['jobs']['privacy']['name'], 'privacy')
        runner = parsed['jobs']['privacy']['runs-on']
        for repository in ('jparker2006/ClosedWiz', 'openwizdev/OpenWiz', 'owner/repo'):
            for event, head, trusted in (
                ('push', '', True),
                ('pull_request', repository, True),
                ('merge_group', '', True),
                ('pull_request', 'fork/repo', False),
            ):
                for small, web, expected in (
                    ('small-pool', 'web-pool', 'small-pool'),
                    ('', 'web-pool', 'web-pool'),
                    ('small-pool', '', 'small-pool'),
                    ('', '', 'namespace-profile-closedwiz-rust'),
                ):
                    with self.subTest(repository=repository, event=event, head=head,
                                      small=small, web=web):
                        expression = runner[3:-2].strip()
                        for key, value in {
                            'github.event_name': event,
                            'github.event.pull_request.head.repo.full_name': head,
                            'github.repository': repository,
                            'vars.CI_SMALL_RUNS_ON': small,
                            'vars.CI_WEB_RUNS_ON': web,
                        }.items():
                            expression = expression.replace(key, repr(value))
                        actual = eval(expression.replace('&&', ' and ').replace('||', ' or '),
                                      {'__builtins__': {}}, {})
                        self.assertEqual(actual, expected if trusted and repository ==
                                         'jparker2006/ClosedWiz' else 'ubuntu-24.04')
        self.assertEqual(parsed['permissions'], {'contents': 'read'})
        self.assertEqual(set(parsed['on']), {'push', 'pull_request', 'merge_group'})
        self.assertEqual(parsed['on']['push'], {'branches': ['main']})
        self.assertFalse({'branches', 'branches-ignore', 'paths', 'paths-ignore'} & set(parsed['on']['pull_request']))
        self.assertEqual(parsed['on']['merge_group'], {'types': ['checks_requested']})
        self.assertEqual(workflow.refused_jobs(path.read_text()), [])
        self.assertIn('edited', parsed['on']['pull_request']['types'])


    def test_quoted_decider_cannot_introduce_a_blockquote(self):
        self.text('"Open for ' + DECIDER + '":\n> ordinary quoted example')

    def test_old_public_history_is_exempt_even_with_older_base(self):
        self.make_repo()
        self.git('commit', '--allow-empty', '-qm', 'clean')
        self.history(base=self.public_root)


    def commit_files(self, message, files):
        for name, data in files.items():
            path = self.repo / name
            if data is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git('add', '-A')
        self.git('commit', '-qm', message)

    def scan_range(self):
        out = io.StringIO()
        with patch.multiple(self.checker, PUBLIC_ROOT=self.public_root, PUBLIC_ANCHOR=self.anchor), contextlib.redirect_stdout(out):
            rc = self.checker.main(['--repo', str(self.repo), '--base', self.anchor, '--head', 'HEAD'])
        return rc, out.getvalue()

    def test_range_reads_each_unchanged_blob_once(self):
        self.make_repo()
        self.commit_files('synthetic files', {'a.md': b'synthetic a', 'b.md': b'synthetic b', 'same.md': b'synthetic b'})
        for n in range(4):
            self.commit_files('synthetic edit', {'c.md': b'synthetic edit ' + str(n).encode()})
        reads, read = [], self.checker.BlobReader.read
        def counted(reader, sha):
            reads.append(sha)
            return read(reader, sha)
        with patch.object(self.checker.BlobReader, 'read', counted):
            self.assertEqual(self.scan_range(), (0, 'literals: not used\n'))
        self.assertEqual(len(reads), len(set(reads)), 'a blob was read again in the same run')
        self.assertEqual(len(reads), 6)

    def test_range_findings_repeat_for_every_commit_and_path(self):
        self.make_repo()
        planted = (THREAD + '\n').encode()
        bad = ('```bad\n' + THREAD + '\n```\n').encode()
        runner = b'jobs:\n  test:\n    runs-on: self-hosted\n'
        caller = b'jobs:\n  test:\n    uses: ./.github/workflows/local.yml\n'
        local = b'jobs:\n  reusable:\n    runs-on: ubuntu-latest\n'
        self.commit_files('synthetic 1', {'planted.md': planted, 'contracts/open-development.v1.md': bad,
                                          'docs/runner.yml': runner, '.github/workflows/caller.yml': caller})
        self.commit_files('synthetic 2', {'copy.md': planted, 'other.md': bad,
                                          '.github/workflows/runner.yml': runner,
                                          '.github/workflows/local.yml': local})
        self.commit_files('synthetic 3', {'planted.md': None, 'copy.md': None, 'other.md': None,
                                          '.github/workflows/runner.yml': None})
        self.assertEqual(self.scan_range(), (1,
            'F2 commit-tree-2:".github/workflows/runner.yml":1\n'
            'T1 commit-tree-2:"copy.md":1\n'
            'T1 commit-tree-2:"other.md":2\n'
            'T1 commit-tree-2:"planted.md":1\n'
            'T1 commit-tree-3:"planted.md":1\n'
            'F2 commit-tree-3:".github/workflows/caller.yml":1\n'
            'literals: not used\n'))

    def test_matrix_block_scalar_cannot_hide_include_override(self):
        self.workflow('jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-latest]\n        include:\n          - note: |\n              ordinary note\n            os: self-hosted\n', 'F2')


if __name__ == '__main__':
    unittest.main()
