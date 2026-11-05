#!/usr/bin/env python3
"""CLI proofs with real Git and O3, synthetic repositories, no network."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CLI = HERE / 'import.py'
CHECKER = HERE.parent / 'privacy-check/check.py'

# OQ1's exact reviewed carriage, independent of the importer's policy file.
REVIEWED_CARRIAGE = (
    'ci/shard/README.md',
    'ci/shard/shard.py',
    'ci/shard/test.py',
    'ci/shard/times.tsv',
    'tools/live-smoke/README.md',
    'tools/live-smoke/browser.mjs',
    'tools/live-smoke/cleanup.py',
    'tools/live-smoke/combined.template.json',
    'tools/live-smoke/http.py',
    'tools/live-smoke/prepare.py',
    'tools/live-smoke/prove_port.py',
    'tools/live-smoke/smoke.py',
    'tools/live-smoke/test_fixture.py',
    'tools/live-smoke/test_review.py',
    'tools/live-smoke/test_smoke.py',
)

# #2405's classification of every path the real importer reported unlisted on
# pinned main 67c7e6e6 (166 paths; the PR lists each one). One entry per carried
# group: (sample path, class, reason). Every group is public: none is under
# private/, under docs/grills/ or in a retiring kit (PC runner, CI overflow
# switch, PC capacity), the contract's only private and retiring classes.
CLASSIFIED_2405 = (
    ('ci/main-batch/shadow.py', 'public', 'C7 combined-main shadow code, tests and synthetic fixtures'),
    ('docs/evidence/ci2-pr-cuts.md', 'public', 'docs: CI2 evidence summaries with private-record pointers'),
    ('docs/security/public-release-review.md', 'public', 'docs: the public release security review'),
    ('docs/spikes/ops-dispatch.md', 'public', 'docs: the ops dispatch discovery report'),
    ('tools/ci-overload/alarm.py', 'public', 'CS5 queue and API overload guard, not the retiring CI overflow switch'),
    ('tools/ci2-live/batch-kit.md', 'public', 'C11 offline observation kit and its test'),
    ('tools/github-reads/read.py', 'public', 'C8 agent GitHub reads code, tests and fixtures'),
    ('tools/live-smoke/restriction.py', 'public', 'live smoke expected-plan restriction code'),
    ('tools/live-smoke/test_restriction.py', 'public', 'its synthetic test'),
    ('tools/notifications/discovery-kit.md', 'public', 'notification discovery kit, schema and tests'),
    ('tools/ops-live/controls/kit.py', 'public', 'OB8a offline kit controls, tests and synthetic fixtures'),
    ('tools/war-room/suite.py', 'public', 'war room contract, adapters, tests and fixtures'),
)
CARRIED = REVIEWED_CARRIAGE + tuple(row[0] for row in CLASSIFIED_2405)

# #2428: the source's plugin manifests replace the destination's, byte for
# byte; the destination fixture holds different, older manifests.
SOURCE_MANIFESTS = {
    '.claude-plugin/plugin.json':
        b'{"name":"synthetic","skills":["./skills/one","./skills/two"]}\n',
    '.claude-plugin/marketplace.json':
        b'{"name":"synthetic","plugins":[{"name":"synthetic","source":"./"}]}\n',
}


class Import(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
        for key in list(self.env):
            if key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
                del self.env[key]
        self.env.pop('GIT_CONFIG_COUNT', None)
        self.source = self.repo('source', {
            'crates/core/src/lib.rs': b'pub const VALUE: u8 = 42;\n',
            'README.md': b'source readme must not replace public readme\n',
            'private/evidence/secret': b'not for carriage\n',
            'tools/ci-overflow/retired': b'not for carriage\n',
            **SOURCE_MANIFESTS,
        })
        self.public = self.repo('public', {
            'README.md': b'public readme\n', 'LICENSE': b'public license\n',
            '.claude-plugin/plugin.json': b'{"name":"synthetic"}\n',
            '.claude-plugin/marketplace.json': b'{"name":"old synthetic"}\n',
            'crates/core/src/lib.rs': b'old\n', 'obsolete': b'delete this\n',
        })
        self.base = self.git(self.public, 'rev-parse', 'HEAD').strip()
        self.head = self.git(self.source, 'rev-parse', 'HEAD').strip()
        # Same real O3 implementation; synthetic history constants only here,
        # as in O3's own fixtures. Production has no history-policy override.
        self.checker = self.root / 'checker.py'
        self.checker.write_text(
            'import sys\nsys.dont_write_bytecode = True\n'
            f'sys.path.insert(0, {str(CHECKER.parent)!r})\n'
            'import check\n'
            f'check.PUBLIC_ROOT = {self.base!r}\n'
            f'check.PUBLIC_ANCHOR = {self.base!r}\n'
            'sys.exit(check.main())\n')
        self.literals = self.root / 'literals'
        self.literals.write_text('planted-machine\n')

    def git(self, repo, *args, data=None, ok=True):
        r = subprocess.run(['git', '-C', str(repo), *args], input=data,
                           capture_output=True, env=self.env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr.decode())
        return r.stdout.decode() if ok else r

    def repo(self, name, files):
        repo = self.root / name
        repo.mkdir()
        self.git(repo, 'init', '-q', '-b', 'main')
        self.git(repo, 'config', 'user.name', 'Synthetic')
        self.git(repo, 'config', 'user.email', 'synthetic@users.noreply.github.com')
        for name, data in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.commit(repo)
        return repo

    def commit(self, repo):
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', 'synthetic input')
        return self.git(repo, 'rev-parse', 'HEAD').strip()

    def call(self, command='tree', *extra):
        args = [sys.executable, '-I', str(CLI), command,
                '--destination', str(self.public), '--checker', str(self.checker),
                '--literals', str(self.literals)]
        if command != 'apply-patch':
            args += ['--source', str(self.source), '--commit', self.head]
        else:
            args += ['--binding-sha256', self.binding]
        return subprocess.run(args + list(map(str, extra)), env=self.env,
                              capture_output=True, text=True)

    def success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def snapshot(self, repo):
        return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in repo.rglob('*') if p.is_file()}

    def test_tree_parent_bytes_preservation_repeat_and_no_private_objects(self):
        carried = {name: f'synthetic carriage: {name}\n'.encode()
                   for name in CARRIED}
        excluded = ('docs/grills/synthetic.md', 'tools/pc-capacity/retired',
                    'ci/runner/retired')
        for name, data in {**carried, **dict.fromkeys(excluded, b'not for carriage\n')}.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.head = self.commit(self.source)
        before = self.snapshot(self.public)
        a = self.success(self.call())
        b = self.success(self.call())
        self.assertEqual(before, self.snapshot(self.public))
        self.assertEqual((a['tree'], a['commit']), (b['tree'], b['commit']))
        saved = self.success(self.call('tree', '--write-local'))
        self.assertEqual(a['commit'], saved['commit'])
        commit = saved['commit']
        self.assertEqual(self.git(self.public, 'show', '-s', '--format=%P', commit).strip(), self.base)
        self.assertEqual(self.git(self.public, 'rev-list', '--max-parents=0', commit).strip(), self.base)
        self.assertNotEqual(self.base, self.head)
        self.assertNotEqual(self.git(self.public, 'cat-file', '-e', self.head, ok=False).returncode, 0)
        names = self.git(self.public, 'ls-tree', '-r', '--name-only', commit).splitlines()
        self.assertEqual(names, sorted([*SOURCE_MANIFESTS, 'LICENSE', 'README.md',
                                        'crates/core/src/lib.rs', *CARRIED]))
        for name, data in {**carried, **SOURCE_MANIFESTS}.items():
            self.assertEqual(self.git(self.public, 'show', commit + ':' + name).encode(), data)
        self.assertEqual(self.git(self.public, 'show', commit + ':README.md'), 'public readme\n')
        self.assertEqual(self.git(self.public, 'show', commit + ':crates/core/src/lib.rs'), 'pub const VALUE: u8 = 42;\n')
        self.assertEqual(self.git(self.public, 'rev-parse', 'HEAD').strip(), self.base)
        self.assertEqual(self.git(self.public, 'status', '--porcelain'), '')
        self.assertIn('literals: used', saved['privacy'])

    def test_planted_private_content_refuses_before_destination_changes(self):
        for name in ('crates/core/src/lib.rs', *CARRIED):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            for content, rule in [(b'planted-machine\n', 'T3'),
                                  (('thr_' + 'planted42\n').encode(), 'T1')]:
                with self.subTest(path=name, rule=rule):
                    path.write_bytes(content)
                    self.head = self.commit(self.source)
                    before = self.snapshot(self.public)
                    r = self.call('tree', '--write-local')
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn(rule, r.stdout + r.stderr)
                    self.assertEqual(before, self.snapshot(self.public))
            path.write_text('synthetic clean content\n')

    def test_unlisted_path_refuses(self):
        for name in ('not-reviewed.txt', 'ci/shard/sixteenth.py',
                     'tools/live-smoke/sixteenth.py',
                     # #2405 near misses: a new tool, docs folder or sibling
                     # of a listed folder still needs its own review.
                     'tools/new-tool/run.py', 'docs/new-folder/notes.md',
                     'ci/main-batch-next/run.py', 'tools/war-room-next/run.py',
                     'tools/ops-live-extra.md',
                     # #2405 R1: an unclassified file inside a folder whose
                     # classified paths are listed still refuses.
                     'ci/main-batch/unclassified.py', 'docs/evidence/unclassified.bin',
                     'docs/security/unclassified.md', 'docs/spikes/unclassified.md',
                     'tools/ci-overload/unclassified.py', 'tools/ci2-live/unclassified.md',
                     'tools/github-reads/unclassified.py',
                     'tools/notifications/unclassified.py',
                     'tools/ops-live/controls/unclassified.py',
                     'tools/war-room/unclassified.py'):
            with self.subTest(path=name):
                base = self.head
                path = self.source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('public-looking but unreviewed')
                self.head = self.commit(self.source)
                before = self.snapshot(self.public)
                r = self.call('tree', '--write-local')
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('unlisted source paths: 1;', r.stderr)
                self.assertEqual(before, self.snapshot(self.public))
                output = self.root / 'unlisted-patch'
                r = self.call('patch', '--source-base', base, '--output', output)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('unlisted', r.stderr)
                self.assertFalse(output.exists())
                self.assertEqual(before, self.snapshot(self.public))
                path.unlink()
                self.head = self.commit(self.source)

    def test_planted_private_ancestry_refuses(self):
        self.git(self.public, 'fetch', '--no-tags', str(self.source), 'main')
        self.git(self.public, 'merge', '--allow-unrelated-histories', '-s', 'ours', '--no-edit', 'FETCH_HEAD')
        before = self.snapshot(self.public)
        r = self.call('tree', '--write-local')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('C1', r.stdout + r.stderr)
        self.assertEqual(before, self.snapshot(self.public))

    def test_no_network_or_hooks_and_dry_run_changes_no_input(self):
        marker = self.root / 'network-write'
        hooks = self.root / 'hooks'
        hooks.mkdir()
        hook = hooks / 'pre-push'
        hook.write_text(f'#!/bin/sh\ntouch {marker}\nexit 99\n')
        hook.chmod(0o755)
        for repo in (self.source, self.public):
            self.git(repo, 'config', 'core.hooksPath', str(hooks))
            self.git(repo, 'remote', 'add', 'origin', 'ext::false')
            self.git(repo, 'config', 'protocol.ext.allow', 'always')
        source_before, public_before = self.snapshot(self.source), self.snapshot(self.public)
        self.success(self.call())
        self.assertFalse(marker.exists())
        self.assertEqual(source_before, self.snapshot(self.source))
        self.assertEqual(public_before, self.snapshot(self.public))

    def test_git_transport_boundary_all_operations(self):
        real_git = subprocess.check_output(['which', 'git'], text=True).strip()
        binaries = self.root / 'bin'
        binaries.mkdir()
        log = self.root / 'git-log'
        wrapper = binaries / 'git'
        wrapper.write_text('#!' + sys.executable + '\nimport json, os, sys\n'
                           f'with open({str(log)!r}, "a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                           f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n')
        wrapper.chmod(0o755)
        self.env['PATH'] = str(binaries) + os.pathsep + self.env['PATH']
        # Instrument only importer children; fixture setup uses the real Git.
        original_git = self.git
        def fixture_git(repo, *args, **kwargs):
            with patch.dict(self.env, {'PATH': os.environ['PATH']}):
                return original_git(repo, *args, **kwargs)
        with patch.object(self, 'git', fixture_git):
            self.success(self.call())
            self.success(self.call('tree', '--write-local'))
            output, _ = self.patch()
            self.success(self.call('apply-patch', '--patch-dir', output, '--write-local'))
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertGreater(len(commands), 0)
        forbidden = {'push', 'fetch', 'clone', 'pull', 'send-pack', 'receive-pack', 'ls-remote'}
        self.assertFalse(any(any(word in forbidden for word in command) for command in commands))

    def test_missing_literals_or_checker_refuses(self):
        for absent in (self.literals, self.checker):
            saved = absent.read_bytes()
            absent.unlink()
            before = self.snapshot(self.public)
            r = self.call('tree', '--write-local')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(before, self.snapshot(self.public))
            absent.write_bytes(saved)

    def patch(self):
        base = self.head
        (self.source / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 43;\n')
        self.head = self.commit(self.source)
        # Public base already has the imported original source content.
        self.git(self.public, 'show', self.base + ':README.md')
        (self.public / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 42;\n')
        self.commit(self.public)
        self.base = self.git(self.public, 'rev-parse', 'HEAD').strip()
        output = self.root / 'patch-output'
        result = self.success(self.call('patch', '--source-base', base, '--output', output))
        self.binding = result['binding_sha256']
        return output, result

    def test_patch_roundtrip_bound_to_destination_and_bytes(self):
        output, planned = self.patch()
        before = self.snapshot(self.public)
        result = self.success(self.call('apply-patch', '--patch-dir', output))
        self.assertEqual(result['tree'], planned['tree'])
        self.assertEqual(before, self.snapshot(self.public))
        saved = self.success(self.call('apply-patch', '--patch-dir', output, '--write-local'))
        self.assertEqual(self.git(self.public, 'show', saved['commit'] + ':crates/core/src/lib.rs'), 'pub const VALUE: u8 = 43;\n')
        self.assertNotEqual(self.git(self.public, 'cat-file', '-e', self.head, ok=False).returncode, 0)
        # Drift must refuse, without changing anything else.
        (self.public / 'LICENSE').write_text('updated public license\n')
        self.commit(self.public)
        before = self.snapshot(self.public)
        r = self.call('apply-patch', '--patch-dir', output, '--write-local')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('binding', r.stderr)
        self.assertEqual(before, self.snapshot(self.public))

    def test_reviewed_carriage_patch_excludes_private_retired(self):
        base = self.head
        excluded = ('private/evidence/secret', 'docs/grills/synthetic.md',
                    'tools/ci-overflow/retired', 'tools/pc-capacity/retired',
                    'ci/runner/retired')
        for name in (*CARRIED, *excluded):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic changed content\n')
        self.head = self.commit(self.source)
        output = self.root / 'reviewed-patch'
        before = self.snapshot(self.public)
        result = self.success(self.call('patch', '--source-base', base, '--output', output))
        binding = json.loads((output / 'binding.json').read_text())
        self.assertEqual(binding['paths'], sorted(CARRIED))
        self.assertEqual(binding['excluded'], len(excluded))
        self.binding = result['binding_sha256']
        self.success(self.call('apply-patch', '--patch-dir', output))
        self.assertEqual(before, self.snapshot(self.public))
        applied = self.success(self.call('apply-patch', '--patch-dir', output, '--write-local'))
        names = self.git(self.public, 'ls-tree', '-r', '--name-only', applied['commit']).splitlines()
        self.assertEqual(names, sorted([*SOURCE_MANIFESTS, 'LICENSE', 'README.md',
                                        'crates/core/src/lib.rs', 'obsolete', *CARRIED]))
        for name in CARRIED:
            self.assertEqual(self.git(self.public, 'show', applied['commit'] + ':' + name),
                             'synthetic changed content\n')

    def test_patch_tampering_refuses(self):
        output, _ = self.patch()
        patch = output / 'public.patch'
        patch.write_bytes(patch.read_bytes() + b'planted tamper\n')
        r = self.call('apply-patch', '--patch-dir', output, '--write-local')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('binding', r.stderr)

    def test_patch_private_or_unlisted_changes_refuse(self):
        base = self.head
        for name in ('private/evidence/secret', 'tools/ci-overflow/retired', 'unlisted'):
            path = self.source / name
            path.write_text('changed\n')
            self.head = self.commit(self.source)
            r = self.call('patch', '--source-base', base, '--output', self.root / 'refused')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('carriage', r.stderr)
            self.assertFalse((self.root / 'refused').exists())

    def test_modes_binary_symlinks_and_dirty_inputs(self):
        binary = self.source / 'crates/core/image.png'
        binary.write_bytes(b'\x89PNG\0\xff\x01')
        script = self.source / 'crates/core/run.sh'
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        (self.source / 'crates/core/link').symlink_to('src')
        self.head = self.commit(self.source)
        (self.source / 'crates/core/src/lib.rs').write_text('uncommitted must be ignored')
        (self.public / 'README.md').write_text('uncommitted destination must survive')
        self.git(self.public, 'add', 'README.md')
        before_source = self.snapshot(self.source)
        before_public = self.snapshot(self.public)
        a = self.success(self.call())
        self.assertEqual(before_source, self.snapshot(self.source))
        self.assertEqual(before_public, self.snapshot(self.public))
        b = self.success(self.call('tree', '--write-local'))
        self.assertEqual(a['tree'], b['tree'])
        self.assertEqual(self.git(self.public, 'show', b['commit'] + ':crates/core/src/lib.rs'), 'pub const VALUE: u8 = 42;\n')
        tree = self.git(self.public, 'ls-tree', '-r', b['commit'])
        self.assertIn('120000 blob', tree)
        self.assertIn('100755 blob', tree)
        self.assertEqual((self.public / 'README.md').read_text(), 'uncommitted destination must survive')
        self.assertEqual(self.git(self.public, 'diff', '--name-only', '--cached'), 'README.md\n')

    def test_symlink_escape_cycle_and_dangling_refuse(self):
        link = self.source / 'crates/core/link'
        for target in ('/etc/passwd', '../../private/evidence/secret', '../../../escape', 'link', 'absent'):
            with self.subTest(target=target):
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
                self.head = self.commit(self.source)
                before = self.snapshot(self.public)
                r = self.call('tree', '--write-local')
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertEqual(before, self.snapshot(self.public))

    def test_patch_link_to_unchanged_public_directory(self):
        base = self.head
        (self.source / 'crates/core/link').symlink_to('src')
        self.head = self.commit(self.source)
        (self.public / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 42;\n')
        self.commit(self.public)
        result = self.success(self.call('patch', '--source-base', base, '--output', self.root / 'links'))
        self.assertEqual(result['status'], 'checked')

    def test_patch_removed_private_text_refuses(self):
        path = self.source / 'crates/core/src/lib.rs'
        path.write_text('planted-machine\n')
        base = self.commit(self.source)
        path.write_text('clean\n')
        self.head = self.commit(self.source)
        r = self.call('patch', '--source-base', base, '--output', self.root / 'removed')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('T3', r.stdout + r.stderr)
        self.assertFalse((self.root / 'removed').exists())

    def test_patch_output_cannot_modify_input_repository(self):
        base = self.head
        (self.source / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 43;\n')
        self.head = self.commit(self.source)
        (self.public / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 42;\n')
        self.commit(self.public)
        for repo in (self.public, self.source):
            before = self.snapshot(repo)
            r = self.call('patch', '--source-base', base, '--output', repo / 'patch-output')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(before, self.snapshot(repo))

    def test_patch_ignores_source_diff_presentation_settings(self):
        self.git(self.source, 'config', 'diff.noprefix', 'true')
        self.git(self.source, 'config', 'diff.mnemonicPrefix', 'true')
        output, result = self.patch()
        reapplied = self.success(self.call('apply-patch', '--patch-dir', output))
        self.assertEqual(reapplied['tree'], result['tree'])

    def test_import_can_replace_preexisting_public_text(self):
        # The existing public baseline is already published; check the proposed
        # tree/range, rather than requiring old text being replaced to pass.
        (self.public / 'crates/core/src/lib.rs').write_text('planted-machine\n')
        self.base = self.commit(self.public)
        result = self.success(self.call('tree', '--write-local'))
        self.assertEqual(self.git(self.public, 'show', result['commit'] + ':crates/core/src/lib.rs'),
                         'pub const VALUE: u8 = 42;\n')

    def test_symlink_expands_components_before_parent_traversal(self):
        (self.source / 'docs').mkdir()
        (self.source / 'docs/marker').write_text('synthetic marker\n')
        (self.source / 'crates/alias').symlink_to('../docs')
        link = self.source / 'crates/link'
        cases = [('alias/../../README.md', False),
                 ('alias/../README.md', True),
                 ('alias/../crates/alias/../README.md', True)]
        for target, allowed in cases:
            with self.subTest(target=target):
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
                self.head = self.commit(self.source)
                before = self.snapshot(self.public)
                result = self.call()
                self.assertEqual(result.returncode, 0 if allowed else 1, result.stdout + result.stderr)
                self.assertEqual(before, self.snapshot(self.public))

    def test_patch_output_is_outside_roots_with_subdirectory_inputs(self):
        base = self.head
        (self.source / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 43;\n')
        self.head = self.commit(self.source)
        (self.public / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 42;\n')
        self.commit(self.public)
        for option, repo in [('--source', self.source), ('--destination', self.public)]:
            with self.subTest(option=option):
                before = self.snapshot(repo)
                result = self.call('patch', '--source-base', base, '--output', repo / 'patch-output',
                                   option, repo / 'crates')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(before, self.snapshot(repo))
                external = self.root / ('external-' + option.removeprefix('--'))
                self.success(self.call('patch', '--source-base', base, '--output', external,
                                       option, repo / 'crates'))

    def test_workflow_patch_retains_unchanged_reusable_context(self):
        reusable = ('on: workflow_call\njobs:\n  check:\n    runs-on: ubuntu-24.04\n'
                    '    steps:\n      - run: echo synthetic\n')
        caller = ('name: synthetic-one\non: push\njobs:\n  call:\n'
                  '    uses: ./.github/workflows/reusable.yml\n')
        for repo in (self.source, self.public):
            workflows = repo / '.github/workflows'
            workflows.mkdir(parents=True)
            (workflows / 'reusable.yml').write_text(reusable)
            (workflows / 'caller.yml').write_text(caller)
            self.commit(repo)
        base = self.git(self.source, 'rev-parse', 'HEAD').strip()
        path = self.source / '.github/workflows/caller.yml'
        path.write_text(caller.replace('synthetic-one', 'synthetic-two'))
        self.head = self.commit(self.source)
        output = self.root / 'workflow-patch'
        result = self.success(self.call('patch', '--source-base', base, '--output', output))
        self.binding = result['binding_sha256']
        applied = self.success(self.call('apply-patch', '--patch-dir', output, '--write-local'))
        self.assertEqual(applied['tree'], result['tree'])
        self.assertEqual(self.git(self.public, 'show', applied['commit'] + ':.github/workflows/caller.yml'),
                         caller.replace('synthetic-one', 'synthetic-two'))
        # Context is actual public files, not a waiver of missing dependencies.
        path.write_text(caller.replace('reusable.yml', 'missing.yml'))
        self.head = self.commit(self.source)
        refused = self.root / 'missing-workflow'
        result = self.call('patch', '--source-base', base, '--output', refused)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('F2', result.stdout + result.stderr)
        self.assertFalse(refused.exists())

    def test_repository_root_whitespace_never_selects_a_different_clone(self):
        for option, decoy in [('--source', self.source), ('--destination', self.public)]:
            with self.subTest(option=option):
                target = self.root / (decoy.name + ' ')
                self.git(self.root, 'clone', '-q', '--no-hardlinks', str(decoy), str(target))
                self.git(target, 'config', 'user.name', 'Synthetic')
                self.git(target, 'config', 'user.email', 'synthetic@users.noreply.github.com')
                file = 'crates/core/src/lib.rs' if option == '--source' else 'README.md'
                content = 'pub const VALUE: u8 = 44;\n' if option == '--source' else 'public trailing-space clone\n'
                (target / file).write_text(content)
                target_head = self.commit(target)
                decoy_before = self.snapshot(decoy)
                target_before = self.snapshot(target)
                extra = ['--commit', target_head] if option == '--source' else []
                result = self.success(self.call('tree', '--write-local', option, target, *extra))
                self.assertEqual(decoy_before, self.snapshot(decoy))
                destination = self.public if option == '--source' else target
                self.assertEqual(self.git(destination, 'show', result['commit'] + ':' + file), content)
                if option == '--source':
                    self.assertEqual(target_before, self.snapshot(target))
                else:
                    self.assertEqual(result['destination_base'], target_head)
                    self.assertEqual(self.git(target, 'rev-parse', 'HEAD').strip(), target_head)

    def test_patch_output_is_outside_every_registered_worktree(self):
        base = self.head
        (self.source / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 43;\n')
        self.head = self.commit(self.source)
        (self.public / 'crates/core/src/lib.rs').write_text('pub const VALUE: u8 = 42;\n')
        self.commit(self.public)
        for option, primary in [('--source', self.source), ('--destination', self.public)]:
            linked = self.root / (primary.name + '-linked')
            sibling = self.root / (primary.name + '-sibling\nwith space ')
            self.git(primary, 'worktree', 'add', '-q', '--detach', str(linked), 'HEAD')
            self.git(primary, 'worktree', 'add', '-q', '--detach', str(sibling), 'HEAD')
            alias = self.root / (primary.name + '-sibling-alias')
            alias.symlink_to(sibling, target_is_directory=True)
            observed = [self.source, self.public, linked, sibling]
            for label, root in [('primary', primary), ('sibling', sibling), ('alias', alias)]:
                with self.subTest(input=option, output=label):
                    before = [self.snapshot(repo) for repo in observed]
                    output = root / ('private-binding-' + label)
                    result = self.call('patch', '--source-base', base, '--output', output,
                                       option, linked)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('outside input repositories', result.stderr)
                    self.assertFalse(output.exists())
                    self.assertEqual(before, [self.snapshot(repo) for repo in observed])
            # This is outside every registered worktree and Git directory.
            external = self.root / (primary.name + '-external-patch')
            before = [self.snapshot(repo) for repo in observed]
            result = self.success(self.call('patch', '--source-base', base, '--output', external,
                                            option, linked))
            self.assertEqual(before, [self.snapshot(repo) for repo in observed])
            binding = json.loads((external / 'binding.json').read_text())
            self.assertEqual(binding['source_base'], base)
            self.assertEqual(binding['source_head'], self.head)
            self.binding = result['binding_sha256']
            reapplied = self.success(self.call('apply-patch', '--patch-dir', external))
            self.assertEqual(reapplied['tree'], result['tree'])

    def test_patch_refuses_unreadable_or_malformed_worktree_inventory(self):
        base = self.head
        self.patch()
        sibling = self.root / 'hidden-sibling'
        self.git(self.public, 'worktree', 'add', '-q', '--detach', str(sibling), 'HEAD')
        real_git = subprocess.check_output(['which', 'git'], text=True).strip()
        binaries = self.root / 'bin'
        binaries.mkdir()
        wrapper = binaries / 'git'
        self.env['PATH'] = str(binaries) + os.pathsep + self.env['PATH']
        hidden = b'worktree ' + os.fsencode(self.public) + b'\0worktree ' + os.fsencode(sibling) + b'\0\0'
        cases = [(b'', 0, self.root), (b'not-a-record\0\0', 0, self.root),
                 (b'worktree relative\0bare\0\0', 0, self.root),
                 (b'worktree /synthetic\0bare\0', 0, self.root), (b'', 7, self.root),
                 (hidden, 0, sibling)]
        for index, (answer, status, output_root) in enumerate(cases):
            with self.subTest(index=index):
                wrapper.write_text('#!' + sys.executable + '\nimport os, sys\n'
                                   'if "worktree" in sys.argv and "list" in sys.argv:\n'
                                   f'    sys.stdout.buffer.write({answer!r}); sys.exit({status})\n'
                                   f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n')
                wrapper.chmod(0o755)
                before = [self.snapshot(repo) for repo in (self.source, self.public, sibling)]
                output = output_root / ('malformed-' + str(index))
                result = self.call('patch', '--source-base', base, '--output', output)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertFalse(output.exists())
                self.assertEqual(before, [self.snapshot(repo) for repo in (self.source, self.public, sibling)])


if __name__ == '__main__':
    unittest.main()
