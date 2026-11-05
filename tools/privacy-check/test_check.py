#!/usr/bin/env python3
"""Synthetic black-box proofs for open development v1; no network or private reads."""
import contextlib
import importlib.util
import io
import json
import os
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
        # WZ-P4, #1409 R1's form: a concrete helper snapshot/window location
        # with its per-run suffix is private state, even under $HOME. Every
        # suffix below is synthetic; the generic templates must still pass.
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
        # WZ-P4, #1409 R2's form: the owner machine's CPU facts, however
        # written, even wrapped across comment lines. A generic explanation,
        # a public runner fact and an explicitly invented example pass.
        # Numbers are kept apart from their units so this file passes its own scan.
        three, four, ten, sixteen = '3', '4', '10', '16'
        for value in ("# above it (on the PC's runners nproc counts the host's " + sixteen + '\n# CPUs and cpu.max allows ' + three + ').',
                      "The owner's Mac has " + ten + ' cores.',
                      "The PC's runner container has a CPU quota of " + three + '.',
                      'Measured on the Mac, pinned to ' + four + ' vCPUs.',
                      # #2781: a hyphenated count is the same fact.
                      "# keep the PC's " + three + '-CPU runners busy.',
                      'The Mac has a ' + ten + '-core chip.',
                      "The owner's runner is pinned to " + four + ' - vCPUs.'):
            self.text(value, 'T3')
        for value in ("# cpus: nproc, but no more than the container's cgroup v2 cpu.max allows,\n# at its own level or any above it.",
                      'A GitHub-hosted runner has ' + four + ' CPUs.',
                      'For example, an invented PC whose host counts ' + sixteen + ' CPUs while cpu.max allows ' + three + '.',
                      "The PC's runners are listed in the private machine notes.",
                      # #2781: hyphenated counts without the owner machine, or
                      # invented, and hyphenated words that are no count, pass.
                      'A GitHub-hosted runner has ' + four + '-CPU machines.',
                      "For example, an invented PC's " + three + '-CPU runners.',
                      "The PC's multi-core build and the Mac's x86_64-cores note.",
                      "The PC's CPU-bound jobs run on the Mac's per-core queue."):
            self.text(value)

    def test_t3_machine_facts_any_case_and_bound_to_their_own_sentence(self):
        # Review R5: ordinary sentence capitals are still the owner machine.
        # Review R6: an unrelated marker on a nearby line exempts nothing;
        # only the fact's own sentence can say it is invented.
        four, sixteen = '4', '16'
        for value in ('The PC has ' + sixteen + ' cores.', 'The Mac has ' + four + ' CPUs.',
                      'THE MAC HAS ' + four + ' CPUS.',
                      '# the PC has ' + sixteen + ' cores.\n# Synthetic regression cases follow.',
                      '# Synthetic regression cases follow.\n# the PC has ' + sixteen + ' cores.',
                      'An invented example comes later. The PC has ' + sixteen + ' cores.',
                      # Re-check R6: separate comments without full stops are
                      # not one sentence, and owner context may be the sentence before.
                      '# Synthetic regression cases follow\n# the PC has ' + sixteen + ' cores',
                      '# the PC has ' + sixteen + ' cores\n# Synthetic regression cases follow',
                      'The PC is the always-on hub. Its CPU quota is ' + four + '.'):
            self.text(value, 'T3')
        for value in ('# For example, an invented PC whose host counts ' + sixteen + '\n# CPUs.',
                      'The Mac in this synthetic case has ' + four + ' CPUs.',
                      'E.g. the PC has ' + sixteen + ' cores.'):
            self.text(value)

    def test_t3_refused_locations_are_redacted_in_diagnostics(self):
        # Review R4: the refusal must not print the private value it refused,
        # for a staged directory or a Git tree.
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
            # A valid list must not hide which later input failed to read.
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
        # The import carries these exact bytes; fixture-only acceptance is not
        # proof that the representation used by CI is publicly checkable.
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
        # Execute the owning proof from an incomplete checkout, as the private
        # Privacy job did. A missing source must fail before a partial scan.
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
                runner.replace("'jparker2006/ClosedWiz'", "'openwizdev/openwiz'"),
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
            # Removing either guard must never admit a private pool for a fork
            # or for a public copy. Trailing expressions cannot escape proof.
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
        # Substitute policy data only: all history traversal is real Git.
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
        # The user-facing hook receives Git's update stream; no network push.
        head = self.git('rev-parse', 'HEAD')
        line = f'refs/heads/main {head} refs/heads/main {self.anchor}\n'
        r = subprocess.run(['sh', str(HERE.parent.parent / '.githooks/pre-push'), 'origin',
                            'https://github.com/openwizdev/openwiz.git'], cwd=self.repo,
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
        args = ['--url', 'git@github.com:openwizdev/openwiz.git', '--repo', str(self.repo),
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
        args = ['--url', 'https://github.com/openwizdev/openwiz', '--repo', str(self.repo), '--head', 'HEAD', '--base', self.anchor]
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
            with patch.dict(os.environ, GITHUB_REPOSITORY='openwizdev/openwiz', GITHUB_EVENT_NAME=kind,
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

    def test_workflow_check_name_and_repository_runner(self):
        spec = importlib.util.spec_from_file_location('workflow', HERE / 'workflow.py')
        workflow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workflow)
        path = HERE.parent.parent / '.github/workflows/privacy.yml'
        parsed = workflow.parse(path.read_text())
        self.assertEqual(parsed['jobs']['privacy']['name'], 'privacy')
        runner = parsed['jobs']['privacy']['runs-on']
        # Synthetic labels distinguish variable precedence from the default.
        for repository in ('jparker2006/ClosedWiz', 'openwizdev/openwiz', 'owner/repo'):
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
        self.assertEqual(workflow.refused_jobs(path.read_text()), [])
        self.assertIn('edited', parsed['on']['pull_request']['types'])


    def test_quoted_decider_cannot_introduce_a_blockquote(self):
        self.text('"Open for ' + DECIDER + '":\n> ordinary quoted example')

    def test_old_public_history_is_exempt_even_with_older_base(self):
        self.make_repo()
        self.git('commit', '--allow-empty', '-qm', 'clean')
        self.history(base=self.public_root)


    def test_matrix_block_scalar_cannot_hide_include_override(self):
        self.workflow('jobs:\n  test:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-latest]\n        include:\n          - note: |\n              ordinary note\n            os: self-hosted\n', 'F2')


if __name__ == '__main__':
    unittest.main()
