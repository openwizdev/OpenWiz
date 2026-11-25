#!/usr/bin/env python3
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import re
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-gnu')
SOURCE = '1' * 40
REQUIRED = ['runtime/openwiz-build.txt', 'openwiz', 'runtime/skills/setup/SKILL.md', 'runtime/skills/grill/SKILL.md',
            'runtime/skills/to-tickets/SKILL.md', 'runtime/skills/launch-fleet/SKILL.md',
            'runtime/skills/launch-fleet/scripts/fleet.sh', 'runtime/install.py', 'runtime/pull.py']
SETUP_TOOLS = ['runtime/setup/setup.py', 'runtime/setup/store.py', 'runtime/setup/github_login.py',
               'runtime/github-app/setup.py',
               'runtime/github-app/app.py', 'runtime/github-app/manifest.json',
               'runtime/setup/init.py']
REQUIRED += SETUP_TOOLS
CLOUDROOM_TOOL = 'runtime/cloudroom/cloudroom.py'
REQUIRED += [CLOUDROOM_TOOL]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Bundles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-if1-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'installed'
        self.counter = 0

    def bundle(self, target=TARGETS[2], source=SOURCE, mutate=None, extra=None, version='0.0.99', omit=None, override=None):
        self.counter += 1
        files = {path: (b'#!/bin/sh\nexit 0\n' if path == 'openwiz' else b'Synthetic runtime\n')
                 for path in REQUIRED if path != omit}
        files.update(override or {})
        identity = f'openwiz.package.v1\n{version}\n{source}\n{target}\n'.encode()
        files['runtime/openwiz-build.txt'] = identity
        manifest = {'schema': 'openwiz.install.v1', 'version': version, 'source': source,
                    'target': target, 'setup_api': 1, 'archive': 'bundle.tar.gz',
                    'archive_sha256': '', 'archive_bytes': 0,
                    'assets': [{'path': path, 'sha256': sha(data), 'bytes': len(data),
                                'mode': '0700' if path == 'openwiz' or path.endswith('.sh') else '0600'}
                               for path, data in sorted(files.items())]}
        archive = self.base / f'archive-{self.counter}.tar.gz'
        with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(path)
                info.size = len(data)
                info.mode = 0o700 if path == 'openwiz' or path.endswith('.sh') else 0o600
                tar.addfile(info, io.BytesIO(data))
            if extra:
                info = tarfile.TarInfo(extra[0])
                if extra[1] == 'symlink':
                    info.type, info.linkname = tarfile.SYMTYPE, '/tmp/synthetic-escape'
                    tar.addfile(info)
                else:
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b'x'))
        manifest['archive_sha256'] = sha(archive.read_bytes())
        manifest['archive_bytes'] = archive.stat().st_size
        if mutate:
            mutate(manifest)
        path = self.base / f'manifest-{self.counter}.json'
        path.write_text(json.dumps(manifest))
        return path, archive, files

    def run_install(self, bundle, target=TARGETS[2], ok=True):
        manifest, archive, _ = bundle
        result = subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(manifest),
                                 '--archive', str(archive), '--manifest-sha256', sha(manifest.read_bytes()),
                                 '--root', str(self.root), '--target', target],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        if ok:
            return json.loads(result.stdout)
        return result

    def installed(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and not p.is_symlink()}


class Install(Bundles):
    def test_all_targets_install_matching_assets_and_repeat_without_build_tools(self):
        for target in TARGETS:
            with self.subTest(target=target):
                self.root = self.base / target
                b = self.bundle(target)
                result = self.run_install(b, target)
                self.assertNotIn('setup_url', result)
                self.assertEqual(result['source'], SOURCE)
                self.assertEqual(result['target'], target)
                selected = self.root / 'current'
                self.assertTrue(selected.is_symlink())
                for path, data in b[2].items():
                    self.assertEqual((selected / path).read_bytes(), data)
                settings = self.root / 'owner-settings.json'
                settings.write_text('synthetic owner settings')
                before = self.installed()
                self.run_install(b, target)
                self.assertEqual(self.installed(), before)
                self.assertEqual((self.root / 'channel.json').read_text(),
                                 '{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')

    def test_corruption_and_manifest_refusals_preserve_last_good_and_settings(self):
        self.run_install(self.bundle())
        (self.root / 'owner-settings.json').write_text('synthetic settings')
        before = self.installed()
        old = os.readlink(self.root / 'current')
        mutations = [lambda m: m.update(target='unsupported'),
                     lambda m: m.update(source='bad'),
                     lambda m: m.update(setup_api=2),
                     lambda m: m.update(unknown=True),
                     lambda m: m['assets'].append(m['assets'][0]),
                     lambda m: m['assets'].pop(),
                     lambda m: m['assets'][0].update(sha256='0' * 64),
                     lambda m: m['assets'][0].update(path='../escape'),
                     lambda m: m.update(archive_bytes=m['archive_bytes'] + 1)]
        for change in mutations:
            with self.subTest(change=change):
                self.run_install(self.bundle(source='2' * 40, mutate=change), ok=False)
                self.assertEqual(self.installed(), before)
                self.assertEqual(os.readlink(self.root / 'current'), old)
        b = self.bundle(source='2' * 40)
        b[1].write_bytes(b[1].read_bytes() + b'corrupt')
        self.run_install(b, ok=False)
        self.assertEqual(self.installed(), before)

    def test_a_bundle_without_any_setup_tool_is_refused(self):
        self.root = self.base / 'complete'
        self.run_install(self.bundle())
        for path in SETUP_TOOLS:
            with self.subTest(missing=path):
                self.root = self.base / ('missing-' + path.replace('/', '-'))
                self.run_install(self.bundle(omit=path), ok=False)
                self.assertFalse((self.root / 'current').exists())

    def test_a_bundle_without_the_cloudroom_tool_is_refused(self):
        self.root = self.base / 'without-cloudroom'
        self.run_install(self.bundle(omit=CLOUDROOM_TOOL), ok=False)
        self.assertFalse((self.root / 'current').exists())

    def test_duplicate_json_keys_and_unsafe_archive_members_are_refused(self):
        self.run_install(self.bundle())
        before = self.installed()
        b = self.bundle(source='2' * 40)
        b[0].write_text(b[0].read_text().replace('"schema":', '"schema":"duplicate","schema":'))
        self.run_install(b, ok=False)
        for member in [('../escape', 'file'), ('/tmp/escape', 'file'),
                       ('runtime/escape', 'symlink'), ('web/index.html', 'file')]:
            self.run_install(self.bundle(source='2' * 40, extra=member), ok=False)
        self.assertEqual(self.installed(), before)

    def test_private_path_and_existing_foreign_selection_refusals(self):
        b = self.bundle()
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        self.run_install(b, ok=False)
        self.root.chmod(0o700)
        os.symlink(self.base, self.root / 'current')
        self.run_install(b, ok=False)
        self.assertEqual(os.readlink(self.root / 'current'), str(self.base))

    def test_program_runtime_identity_cannot_be_relabelled_as_another_version(self):
        self.run_install(self.bundle())
        before = self.installed()
        self.run_install(self.bundle(source='2' * 40, mutate=lambda m: m.update(version='0.0.100')), ok=False)
        self.assertEqual(self.installed(), before)

    def test_existing_source_install_is_not_silently_migrated_to_packaged(self):
        self.run_install(self.bundle())
        (self.root / 'channel.json').unlink()
        before = self.installed()
        selected = (self.root / 'current').readlink()
        self.run_install(self.bundle(source='2' * 40), ok=False)
        self.assertEqual(self.installed(), before)
        self.assertEqual((self.root / 'current').readlink(), selected)

    def test_disk_permission_and_interrupted_activation_keep_last_good(self):
        spec = importlib.util.spec_from_file_location('installer', HERE / 'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.run_install(self.bundle())
        before = os.readlink(self.root / 'current')
        b = self.bundle(source='2' * 40)
        args = dict(manifest=b[0], archive=b[1], manifest_sha256=sha(b[0].read_bytes()),
                    root=self.root, target=TARGETS[2])
        with self.assertRaises(installer.Refused):
            installer.install(**args, free_bytes=lambda _: 0)
        def denied(*_):
            raise PermissionError('synthetic refusal')
        for failure in (denied, lambda *_: (_ for _ in ()).throw(InterruptedError('synthetic crash'))):
            with self.assertRaises((OSError, installer.Refused)):
                installer.install(**args, activate=failure)
            self.assertEqual(os.readlink(self.root / 'current'), before)
        self.run_install(b)
        self.assertEqual(os.readlink(self.root / 'current'), str(self.root / 'state/service/builds' / ('2' * 40)))

    def test_refused_install_ends_with_the_help_line_and_success_has_none(self):
        spec = importlib.util.spec_from_file_location('installer', HERE / 'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.assertEqual(installer.INSTALL_HELP, 'Stuck? Free 15-min setup help: https://openwiz.dev/help/')
        good = self.bundle()
        ok = subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(good[0]),
                             '--archive', str(good[1]), '--manifest-sha256', sha(good[0].read_bytes()),
                             '--root', str(self.root), '--target', TARGETS[2]], capture_output=True, text=True)
        self.assertEqual((ok.returncode, ok.stderr), (0, ''))
        bad = self.run_install(self.bundle(source='2' * 40, mutate=lambda m: m.update(target='unsupported')), ok=False)
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(bad.stderr.splitlines(), [
            'openwiz-install: refused; last-good selection and owner settings retained',
            installer.INSTALL_HELP,
        ])


SKILLS = {'runtime/skills/grill/SKILL.md': b'---\nname: grill\n---\nSynthetic grill.\n',
          'runtime/skills/setup/SKILL.md': b'---\nname: setup\n---\nSynthetic setup.\n',
          'runtime/skills/launch-fleet/scripts/fleet.sh': b'#!/bin/sh\necho synthetic fleet\n'}
BUILD_TOOLS = ('cargo', 'rustc', 'rustup', 'node', 'npm', 'npx')
REPO = 'synthetic-owner/synthetic-app'


def contract_harnesses():
    text = (ROOT / 'contracts/install.v1.md').read_text()
    return re.findall(r'^\| `([a-z-]+)` \| `~/([^`]+)`', text, re.M)


def snapshot(folder):
    out = {}
    for path in sorted(Path(folder).rglob('*')) if Path(folder).exists() else ():
        info = path.lstat()
        key = str(path.relative_to(folder))
        out[key] = ('link' if path.is_symlink() else
                    (path.read_bytes(), info.st_mode & 0o777) if path.is_file() else 'dir')
    return out


def skill_files(folder, skip=()):
    return {k: v for k, v in snapshot(folder).items()
            if v != 'dir' and Path(k).name != '.openwiz-skill' and Path(k).parts[0] not in skip}


class HarnessSkills(Bundles):
    def setUp(self):
        super().setUp()
        self.run_install(self.bundle(override=SKILLS))
        self.home = self.base / 'home'
        self.home.mkdir()

    def skills(self, home=None, env=None):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'install'), 'skills', '--root', str(self.root)],
                                capture_output=True, text=True,
                                env={'PATH': os.environ['PATH'], 'HOME': str(home or self.home), **(env or {})})
        return result.returncode, json.loads(result.stdout or '{}')

    def test_skills_reach_the_canonical_folder_and_every_named_harness(self):
        harnesses = contract_harnesses()
        schema = json.loads((ROOT / 'contracts/install.v1.schema.json').read_text())
        self.assertEqual([h for h, _ in harnesses], schema['$defs']['harness']['enum'])
        for _, folder in harnesses:
            (self.home / folder).mkdir(parents=True)
        mine = self.home / '.claude/skills/mine/SKILL.md'
        mine.parent.mkdir(parents=True)
        mine.write_bytes(b'The owner skill.\n')
        code, result = self.skills()
        self.assertEqual(code, 0, result)
        shipped = skill_files(self.root / 'current/runtime/skills')
        self.assertEqual(shipped['launch-fleet/scripts/fleet.sh'], (SKILLS['runtime/skills/launch-fleet/scripts/fleet.sh'], 0o700))
        self.assertEqual(skill_files(self.root / 'skills'), shipped)
        for _, folder in harnesses:
            with self.subTest(folder=folder):
                self.assertEqual(skill_files(self.home / folder / 'skills', skip=('mine',)), shipped)
        self.assertEqual({r['id']: r['state'] for r in result['harnesses']}, {h: 'installed' for h, _ in harnesses})
        self.assertEqual(mine.read_bytes(), b'The owner skill.\n')
        before = snapshot(self.home), snapshot(self.root / 'skills')
        self.assertEqual(self.skills()[0], 0)
        self.assertEqual((snapshot(self.home), snapshot(self.root / 'skills')), before)

    def test_absent_harness_is_reported_and_an_unsafe_destination_is_skipped_on_its_own(self):
        (self.home / '.claude').mkdir()
        (self.home / '.codex').mkdir()
        code, result = self.skills(env={'CODEX_HOME': str(self.home / 'codex-elsewhere')})
        self.assertEqual(code, 0, result)
        self.assertEqual({r['id']: r['state'] for r in result['harnesses']},
                         {'claude-code': 'installed', 'codex': 'absent', 'cursor': 'absent',
                          'opencode': 'absent', 'grok': 'absent'})
        self.assertTrue(all(r['next'] for r in result['harnesses']))
        self.assertEqual(snapshot(self.home / '.codex'), {})
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['.claude', '.codex'])
        (self.base / 'dotfiles').mkdir()
        for case in ('foreign', 'link'):
            with self.subTest(case=case):
                home = self.base / ('home-' + case)
                (home / '.claude/skills').mkdir(parents=True)
                (home / '.cursor').mkdir()
                if case == 'foreign':
                    (home / '.claude/skills/grill').mkdir()
                    (home / '.claude/skills/grill/SKILL.md').write_bytes(b'The owner grill.\n')
                else:
                    os.symlink(self.base / 'dotfiles', home / '.grok')
                (self.root / 'skills/grill/SKILL.md').write_bytes(b'stale\n')
                owner = snapshot(home / '.claude/skills/grill')
                code, result = self.skills(home=home)
                self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
                rows = {r['id']: r for r in result['harnesses']}
                self.assertEqual(skill_files(home / '.cursor/skills'), skill_files(self.root / 'current/runtime/skills'))
                self.assertEqual(skill_files(self.root / 'skills'), skill_files(self.root / 'current/runtime/skills'))
                if case == 'foreign':
                    self.assertEqual(rows['claude-code']['state'], 'partial')
                    self.assertEqual([s['skill'] for s in rows['claude-code']['skipped']], ['grill'])
                    self.assertEqual(snapshot(home / '.claude/skills/grill'), owner)
                else:
                    self.assertEqual((rows['claude-code']['state'], rows['grok']['state']), ('installed', 'refused'))
                self.assertEqual(snapshot(self.base / 'dotfiles'), {})

    def test_a_user_entry_at_the_staging_or_backup_path_is_kept_and_only_that_skill_is_skipped(self):
        for name in ('.openwiz-stage-grill', '.openwiz-old-grill'):
            for kind in ('dir', 'file', 'fake-mark'):
                with self.subTest(name=name, kind=kind):
                    home = self.base / f'home{name}-{kind}'
                    shutil.rmtree(self.root / 'skills', ignore_errors=True)
                    entry = home / '.claude/skills' / name
                    if kind in ('dir', 'fake-mark'):
                        entry.mkdir(parents=True)
                        (entry / 'notes.md').write_bytes(b'Synthetic owner notes.\n')
                        if kind == 'fake-mark':
                            (entry / '.openwiz-skill').write_bytes(b'Synthetic unrelated text.\n')
                    else:
                        entry.parent.mkdir(parents=True)
                        entry.write_bytes(b'Synthetic owner notes.\n')
                    before = snapshot(entry) if entry.is_dir() else entry.read_bytes()
                    code, result = self.skills(home=home)
                    self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
                    self.assertEqual(snapshot(entry) if entry.is_dir() else entry.read_bytes(), before)
                    self.assertFalse((home / '.claude/skills/grill').exists())
                    self.assertEqual(skill_files(home / '.claude/skills', skip=(name,)),
                                     skill_files(self.root / 'current/runtime/skills', skip=('grill',)))

    def test_the_skip_names_the_unmarked_folder_and_prints_a_working_remove_command(self):
        home = self.base / "home it's here"
        entry = home / '.claude/skills/.openwiz-stage-grill'
        entry.mkdir(parents=True)
        (entry / 'notes.md').write_bytes(b'Synthetic owner notes.\n')
        code, result = self.skills(home=home)
        self.assertEqual(code, 0, result)
        text = {r['id']: r for r in result['harnesses']}['claude-code']['skipped'][0]['next']
        self.assertTrue(text.startswith(f'{entry} '), text)
        self.assertIn('Look inside it', text)
        command = text.split('run this again: ', 1)[1]
        subprocess.run(['sh', '-c', command], check=True, cwd=self.base)
        self.assertFalse(entry.exists())
        self.assertEqual(self.skills(home=home)[1].get('outcome'), 'installed')

    def test_leftovers_of_an_interrupted_run_are_cleaned_up(self):
        (self.home / '.claude').mkdir()
        self.assertEqual(self.skills()[0], 0)
        folder = self.home / '.claude/skills'
        shutil.copytree(folder / 'grill', folder / '.openwiz-stage-grill')
        os.rename(folder / 'grill', folder / '.openwiz-old-grill')
        code, result = self.skills()
        self.assertEqual(code, 0, result)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted(p.name for p in (self.root / 'current/runtime/skills').iterdir()))
        self.assertEqual(skill_files(folder), skill_files(self.root / 'current/runtime/skills'))


def built_openwiz():
    subprocess.run(['cargo', 'build', '-p', 'openwiz-cli', '--bin', 'openwiz', '--locked'], cwd=ROOT, check=True)
    meta = subprocess.run(['cargo', 'metadata', '--format-version', '1', '--no-deps'], cwd=ROOT,
                          capture_output=True, check=True)
    return Path(json.loads(meta.stdout)['target_directory']) / 'debug/openwiz'


class InstalledCommand(Bundles):
    def test_installed_openwiz_sets_up_a_repository_label_and_records_without_build_tools(self):
        override = {'openwiz': built_openwiz().read_bytes()}
        for name in ('init.py', 'store.py'):
            override['runtime/setup/' + name] = (HERE / 'setup' / name).read_bytes()
        self.run_install(self.bundle(override=override))
        tools = self.base / 'bin'
        tools.mkdir()
        shutil.copy(HERE / 'tests/init/fake_gh.py', tools / 'gh')
        (tools / 'gh').chmod(0o700)
        for tool in BUILD_TOOLS:
            (tools / tool).write_text('#!/bin/sh\necho "$0" >> %s\nexit 1\n' % (self.base / 'build-tools.log'))
            (tools / tool).chmod(0o700)
        world = self.base / 'world.json'
        world.write_text(json.dumps({'user': {'login': 'synthetic-owner', 'type': 'User'}, 'faults': [], 'log': [],
                                     'repos': {REPO: {'full_name': REPO, 'private': True, 'visibility': 'private',
                                                      'default_branch': 'main', 'permissions': {'push': True},
                                                      'owner': {'login': 'synthetic-owner', 'type': 'User'},
                                                      'description': None, 'homepage': None, 'labels': [],
                                                      'pulls': [], 'branches': {'main': {}}}}}))
        env = {'PATH': '%s:/usr/bin:/bin' % tools, 'HOME': str(self.base / 'home'),
               'OPENWIZ_STATE_DIR': str(self.base / 'state'), 'FAKE_GH_WORLD': str(world)}

        def openwiz(*args):
            out = subprocess.run([str(self.root / 'current/openwiz'), 'init', '--repository', REPO, '--json', *args],
                                 capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            return json.loads(out.stdout)
        preview = openwiz()
        applied = openwiz('--yes', '--operation', preview['operation_id'])
        self.assertEqual((applied['kind'], applied['outcome']), ('init_result', 'applied'))
        repo = json.loads(world.read_text())['repos'][REPO]
        self.assertEqual(sorted(repo['labels']), sorted(['openwiz', 'spec', 'ready-for-agent', 'ready-for-human', 'needs-info', 'held']))
        self.assertTrue(any(path.startswith('.openwiz/brain/') for branch in repo['branches'].values()
                            for path in branch), repo['branches'])
        self.assertFalse((self.base / 'build-tools.log').exists())


if __name__ == '__main__':
    unittest.main()
