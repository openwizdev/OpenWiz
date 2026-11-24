#!/usr/bin/env python3
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_install as fixture

HERE = Path(__file__).resolve().parent
PREFIX = 'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/'

FAKE_GH = '''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path

cfg = json.loads(Path(os.environ['FAKE_PRO_GH']).read_text())
args = sys.argv[1:]
if cfg.get('log'):
    with open(cfg['log'], 'a') as f:
        f.write(json.dumps(args) + '\\n')
if args[:2] == ['auth', 'token']:
    if not cfg.get('logged_in', True):
        print('not logged into any GitHub hosts; run gh auth login', file=sys.stderr)
        sys.exit(1)
    print(cfg.get('token', 'gho_synthetic_token_never_logged'))
    sys.exit(0)
if args[:2] == ['api', 'repos/openwizpro/WizPro/releases']:
    code = cfg.get('status', 200)
    if code == 404:
        print('gh: Not Found (HTTP 404)', file=sys.stderr)
        sys.exit(1)
    if code == 401:
        print('gh: Bad credentials (HTTP 401)', file=sys.stderr)
        sys.exit(1)
    print(json.dumps(cfg.get('releases', [])))
    sys.exit(0)
if args[:2] == ['release', 'download']:
    tag = args[2]
    repo = args[args.index('--repo') + 1]
    pattern = args[args.index('--pattern') + 1]
    output = args[args.index('--output') + 1]
    if repo != 'openwizpro/WizPro' or cfg.get('status', 200) == 404:
        print('gh: Not Found (HTTP 404)', file=sys.stderr)
        sys.exit(1)
    src = Path(cfg['assets']) / tag / pattern
    if not src.is_file():
        print('gh: release asset not found (HTTP 404)', file=sys.stderr)
        sys.exit(1)
    shutil.copyfile(src, output)
    sys.exit(0)
print('unexpected fake gh call: ' + ' '.join(args), file=sys.stderr)
sys.exit(2)
'''


def write_fake_gh(base, cfg):
    bin_dir = base / 'fake-gh-bin'
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / 'gh'
    gh.write_text(FAKE_GH)
    gh.chmod(0o700)
    cfg_path = base / 'fake-pro-gh.json'
    cfg_path.write_text(json.dumps(cfg))
    return str(gh), str(cfg_path)


def release_sums(raw, archive, target=fixture.TARGETS[2], version='0.0.99', archive_name='bundle.tar.gz'):
    return ('%s  openwiz-%s-%s.manifest.json\n%s  %s\n'
            % (fixture.sha(raw), version, target, fixture.sha(archive), archive_name)).encode()


class Pull(unittest.TestCase):
    def test_published_upgrade_stages_verified_files_keeps_selection_and_refuses_rollback(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        old = f.bundle(version='0.0.98')
        f.run_install(old)
        before = (f.root / 'current').readlink()
        new = f.bundle(source='2' * 40)
        raw = new[0].read_bytes()
        digest = fixture.sha(raw)
        target = fixture.TARGETS[2]
        calls = []
        def fetch(url, limit):
            calls.append(url)
            if url.endswith('.sha256'):
                return (digest + '  openwiz-' + target + '.manifest.json\n').encode()
            if url.endswith('.manifest.json'):
                return raw
            if url.endswith('.tar.gz'):
                return new[1].read_bytes()
            if url == PREFIX + 'SHA256SUMS':
                return release_sums(raw, new[1].read_bytes())
            self.fail('unexpected transport URL ' + url)
        candidate = pull.discover(target, fetch=fetch)
        self.assertEqual(candidate['source'], '2' * 40)
        pull.stage(target, '0.0.99', '2' * 40, digest, f.root, f.root / 'state', fetch=fetch)
        self.assertEqual((f.root / 'current').readlink(), before)
        self.assertTrue((f.root / 'state/service/builds' / ('2' * 40) / 'runtime/install.py').exists())
        self.assertEqual(calls, [
            'https://github.com/openwizdev/OpenWiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.sha256',
            'https://github.com/openwizdev/OpenWiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/openwiz-0.0.99-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/bundle.tar.gz',
            'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/SHA256SUMS',
        ])
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.98', '2' * 40, digest, f.root, f.root / 'state', fetch=fetch)
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.99', '2' * 40, '0' * 64, f.root, f.root / 'state', fetch=fetch)
        self.assertEqual((f.root / 'current').readlink(), before)

    def test_stage_refuses_a_release_whose_files_do_not_match_its_sha256sums(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.run_install(f.bundle(version='0.0.98'))
        before = (f.root / 'current').readlink()
        new = f.bundle(source='2' * 40)
        raw, archive = new[0].read_bytes(), new[1].read_bytes()
        target, other = fixture.TARGETS[2], fixture.sha(b'synthetic other bytes')
        manifest_line = 'openwiz-0.0.99-%s.manifest.json' % target
        cases = [
            ('archive differs', release_sums(raw, b'synthetic other bytes'), 'SHA256SUMS does not match bundle.tar.gz'),
            ('manifest differs', release_sums(b'synthetic other bytes', archive),
             'SHA256SUMS does not match ' + manifest_line),
            ('archive unlisted', ('%s  %s\n' % (fixture.sha(raw), manifest_line)).encode(),
             'SHA256SUMS does not list bundle.tar.gz'),
            ('manifest unlisted', ('%s  bundle.tar.gz\n' % fixture.sha(archive)).encode(),
             'SHA256SUMS does not list ' + manifest_line),
            ('malformed', release_sums(raw, archive) + b'not a checksum line\n', 'invalid SHA256SUMS line'),
            ('duplicate', release_sums(raw, archive) + ('%s  bundle.tar.gz\n' % other).encode(),
             'invalid SHA256SUMS line'),
        ]
        for name, sums, refusal in cases:
            with self.subTest(name):
                def fetch(url, limit):
                    if url == PREFIX + 'SHA256SUMS':
                        return sums
                    return archive if url == PREFIX + 'bundle.tar.gz' else raw
                with self.assertRaisesRegex(pull.Refused, '^' + re.escape(refusal) + '$'):
                    pull.stage(target, '0.0.99', '2' * 40, fixture.sha(raw), f.root, f.root / 'state', fetch=fetch)
                self.assertEqual((f.root / 'current').readlink(), before)
                self.assertFalse((f.root / 'state/service/builds' / ('2' * 40)).exists())


    def test_pre_ap11_selected_build_reports_status_and_upgrades_to_a_cli_only_candidate(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target, legacy = fixture.TARGETS[2], 'a' * 40
        identity = f'openwiz.package.v1\n0.0.98\n{legacy}\n{target}\n'.encode()
        programs = ('openwiz', 'openwiz-service', 'openwiz-server')
        files = {path: b'Synthetic runtime\n' for path in fixture.REQUIRED}
        files.update({path: b'#!/bin/sh\nexit 0\n' for path in programs})
        files.update({'web/index.html': b'<h1>Synthetic</h1>', 'web/setup.html': b'<h1>Synthetic</h1>',
                      'web/openwiz-build.txt': identity, 'runtime/openwiz-build.txt': identity})
        mode = lambda path: '0700' if path in programs or path.endswith('.sh') else '0600'
        raw = json.dumps({'schema': 'openwiz.install.v1', 'version': '0.0.98', 'source': legacy,
                          'target': target, 'setup_api': 1, 'archive': 'bundle.tar.gz',
                          'archive_sha256': '0' * 64, 'archive_bytes': 1,
                          'assets': [{'path': path, 'sha256': fixture.sha(data), 'bytes': len(data),
                                      'mode': mode(path)} for path, data in sorted(files.items())]}).encode()
        build = f.root / 'state/service/builds' / legacy
        for folder in (f.root, f.root / 'state', f.root / 'state/service', build.parent, build):
            folder.mkdir(mode=0o700)
            folder.chmod(0o700)
        for path, data in {**files, 'install-manifest.json': raw}.items():
            for folder in reversed((build / path).relative_to(build).parents[:-1]):
                (build / folder).mkdir(mode=0o700, exist_ok=True)
                (build / folder).chmod(0o700)
            (build / path).write_bytes(data)
            (build / path).chmod(int(mode(path), 8))
        (f.root / 'channel.json').write_bytes(b'{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')
        (f.root / 'channel.json').chmod(0o600)
        (f.root / 'current').symlink_to(build)

        def status():
            result = subprocess.run([sys.executable, str(HERE / 'install'), 'status', '--root', str(f.root)],
                                    capture_output=True, text=True)
            return result.returncode, json.loads(result.stdout)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, legacy, '0.0.98'), value)

        legacy_raw = raw.replace(legacy.encode(), b'3' * 40).replace(b'0.0.98', b'0.0.99')
        with self.assertRaisesRegex(pull.Refused, 'unknown asset role'):
            pull.stage(target, '0.0.99', '3' * 40, fixture.sha(legacy_raw), f.root, f.root / 'state',
                       fetch=lambda url, limit: legacy_raw)

        new = f.bundle(source='2' * 40)
        new_raw, archive = new[0].read_bytes(), new[1].read_bytes()
        fetched = []
        def fetch(url, limit):
            fetched.append(url)
            if url.endswith('SHA256SUMS'):
                return release_sums(new_raw, archive)
            return archive if url.endswith('.tar.gz') else new_raw
        staged = pull.stage(target, '0.0.99', '2' * 40, fixture.sha(new_raw), f.root, f.root / 'state', fetch=fetch)
        self.assertEqual(fetched[-2:], [PREFIX + 'bundle.tar.gz', PREFIX + 'SHA256SUMS'])
        self.assertEqual(((f.root / 'current').readlink(), staged['activated']), (build, False))
        f.run_install(new)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, '2' * 40, '0.0.99'), value)

    def test_pre_0_2_0_skill_layout_selected_build_reports_status_and_upgrades(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target, old = fixture.TARGETS[2], 'b' * 40
        identity = f'openwiz.package.v1\n0.0.98\n{old}\n{target}\n'.encode()
        files = {path: b'Synthetic runtime\n' for path in fixture.REQUIRED if path != 'runtime/skills/to-tickets/SKILL.md'}
        files['runtime/skills/plan-graph/SKILL.md'] = b'Synthetic runtime\n'
        files['openwiz'] = b'#!/bin/sh\nexit 0\n'
        files['runtime/openwiz-build.txt'] = identity
        mode = lambda path: '0700' if path == 'openwiz' or path.endswith('.sh') else '0600'
        raw = json.dumps({'schema': 'openwiz.install.v1', 'version': '0.0.98', 'source': old,
                          'target': target, 'setup_api': 1, 'archive': 'bundle.tar.gz',
                          'archive_sha256': '0' * 64, 'archive_bytes': 1,
                          'assets': [{'path': path, 'sha256': fixture.sha(data), 'bytes': len(data),
                                      'mode': mode(path)} for path, data in sorted(files.items())]}).encode()
        build = f.root / 'state/service/builds' / old
        for folder in (f.root, f.root / 'state', f.root / 'state/service', build.parent, build):
            folder.mkdir(mode=0o700)
            folder.chmod(0o700)
        for path, data in {**files, 'install-manifest.json': raw}.items():
            for folder in reversed((build / path).relative_to(build).parents[:-1]):
                (build / folder).mkdir(mode=0o700, exist_ok=True)
                (build / folder).chmod(0o700)
            (build / path).write_bytes(data)
            (build / path).chmod(int(mode(path), 8))
        (f.root / 'channel.json').write_bytes(b'{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')
        (f.root / 'channel.json').chmod(0o600)
        (f.root / 'current').symlink_to(build)

        def status():
            result = subprocess.run([sys.executable, str(HERE / 'install'), 'status', '--root', str(f.root)],
                                    capture_output=True, text=True)
            return result.returncode, json.loads(result.stdout)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, old, '0.0.98'), value)

        old_raw = raw.replace(old.encode(), b'3' * 40).replace(b'0.0.98', b'0.0.99')
        with self.assertRaisesRegex(pull.Refused, 'incomplete program or skill runtime'):
            pull.stage(target, '0.0.99', '3' * 40, fixture.sha(old_raw), f.root, f.root / 'state',
                       fetch=lambda url, limit: old_raw)

        new = f.bundle(source='2' * 40)
        new_raw, archive = new[0].read_bytes(), new[1].read_bytes()
        staged = pull.stage(target, '0.0.99', '2' * 40, fixture.sha(new_raw), f.root, f.root / 'state',
                            fetch=lambda url, limit: release_sums(new_raw, archive) if url.endswith('SHA256SUMS')
                            else archive if url.endswith('.tar.gz') else new_raw)
        self.assertEqual(((f.root / 'current').readlink(), staged['activated']), (build, False))
        f.run_install(new)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, '2' * 40, '0.0.99'), value)

    def test_early_channel_follows_newest_semver_across_pro_and_public_and_refuses_rollback(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target = fixture.TARGETS[2]
        assets_root = f.base / 'pro-assets'

        def populate_pro(version, source):
            b = f.bundle(version=version, source=source)
            raw, arch = b[0].read_bytes(), b[1].read_bytes()
            tag_dir = assets_root / ('v' + version)
            tag_dir.mkdir(parents=True, exist_ok=True)
            (tag_dir / f'openwiz-{target}.sha256').write_bytes(
                f'{fixture.sha(raw)}  openwiz-{target}.manifest.json\n'.encode())
            (tag_dir / f'openwiz-{target}.manifest.json').write_bytes(raw)
            (tag_dir / f'openwiz-{version}-{target}.manifest.json').write_bytes(raw)
            (tag_dir / 'bundle.tar.gz').write_bytes(arch)
            (tag_dir / 'SHA256SUMS').write_bytes(release_sums(raw, arch, target, version))
            return b, raw, arch

        rc1, raw_rc1, _ = populate_pro('0.1.2-rc.1', '1' * 40)
        rc2, raw_rc2, _ = populate_pro('0.1.2-rc.2', '2' * 40)
        rc3, raw_rc3, _ = populate_pro('0.1.3-rc.1', '4' * 40)
        pub_old = f.bundle(version='0.1.1', source='a' * 40)
        pub_new = f.bundle(version='0.1.2', source='3' * 40)
        current_pub = {'bundle': pub_old, 'version': '0.1.1'}

        def pub_fetch(url, limit):
            b = current_pub['bundle']
            raw, arch = b[0].read_bytes(), b[1].read_bytes()
            if url.endswith('.sha256'):
                return f'{fixture.sha(raw)}  openwiz-{target}.manifest.json\n'.encode()
            if url.endswith('.manifest.json'):
                return raw
            if url.endswith('.tar.gz'):
                return arch
            if url.endswith('SHA256SUMS'):
                return release_sums(raw, arch, target, current_pub['version'])
            raise pull.NotFound('404 at ' + url)

        cfg = {
            'logged_in': True, 'status': 200, 'assets': str(assets_root),
            'releases': [
                {'tag_name': 'v0.1.2-rc.1', 'prerelease': True, 'draft': False},
                {'tag_name': 'v0.1.2-rc.2', 'prerelease': True, 'draft': False},
                {'tag_name': 'v0.1.3-rc.1', 'prerelease': True, 'draft': True},
                {'tag_name': 'v0.1.3', 'prerelease': False, 'draft': False},
            ],
        }
        gh_path, cfg_path = write_fake_gh(f.base, cfg)
        old_env = os.environ.get('FAKE_PRO_GH')
        os.environ['FAKE_PRO_GH'] = cfg_path
        self.addCleanup(lambda: os.environ.pop('FAKE_PRO_GH', None) if old_env is None
                        else os.environ.__setitem__('FAKE_PRO_GH', old_env))
        which = lambda name: gh_path if name == 'gh' else None

        res = subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(rc1[0]),
                              '--archive', str(rc1[1]), '--manifest-sha256', fixture.sha(raw_rc1),
                              '--root', str(f.root), '--target', target, '--channel', 'early'],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual((f.root / 'channel.json').read_text(),
                         '{"schema":"openwiz.update-channel.v1","channel":"early"}\n')

        cand = pull.discover(target, fetch=pub_fetch, root=f.root, which=which)
        self.assertEqual((cand['version'], cand['channel'], cand['origin']), ('0.1.2-rc.2', 'early', 'early'))
        staged = pull.stage(target, cand['version'], cand['source'], cand['manifest_sha256'],
                            f.root, f.root / 'state', fetch=pub_fetch, which=which)
        self.assertEqual((staged['version'], staged['activated']), ('0.1.2-rc.2', False))
        subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(rc2[0]),
                        '--archive', str(rc2[1]), '--manifest-sha256', fixture.sha(raw_rc2),
                        '--root', str(f.root), '--target', target, '--channel', 'early'],
                       check=True, capture_output=True)

        current_pub.update(bundle=pub_new, version='0.1.2')
        cand = pull.discover(target, fetch=pub_fetch, root=f.root, which=which)
        self.assertEqual((cand['version'], cand['channel'], cand['origin']), ('0.1.2', 'early', 'public'))
        staged = pull.stage(target, cand['version'], cand['source'], cand['manifest_sha256'],
                            f.root, f.root / 'state', fetch=pub_fetch, which=which)
        self.assertEqual((staged['version'], staged['activated']), ('0.1.2', False))
        subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(pub_new[0]),
                        '--archive', str(pub_new[1]), '--manifest-sha256', fixture.sha(pub_new[0].read_bytes()),
                        '--root', str(f.root), '--target', target, '--channel', 'early'],
                       check=True, capture_output=True)
        self.assertEqual((f.root / 'channel.json').read_text(),
                         '{"schema":"openwiz.update-channel.v1","channel":"early"}\n')

        with self.assertRaisesRegex(pull.Refused, 'published version must advance'):
            pull.stage(target, '0.1.2-rc.2', '2' * 40, fixture.sha(raw_rc2),
                       f.root, f.root / 'state', fetch=pub_fetch, which=which)

        cfg['releases'].append({'tag_name': 'v0.1.3-rc.1', 'prerelease': True, 'draft': False})
        Path(cfg_path).write_text(json.dumps(cfg))
        cand = pull.discover(target, fetch=pub_fetch, root=f.root, which=which)
        self.assertEqual((cand['version'], cand['origin']), ('0.1.3-rc.1', 'early'))
        staged = pull.stage(target, cand['version'], cand['source'], cand['manifest_sha256'],
                            f.root, f.root / 'state', fetch=pub_fetch, which=which)
        self.assertEqual((staged['version'], staged['source']), ('0.1.3-rc.1', '4' * 40))

    def test_early_channel_refusals_for_missing_gh_logged_out_and_no_pro_access(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target = fixture.TARGETS[2]
        fail_fetch = lambda url, limit: self.fail('must not fetch public before Pro auth/access check: ' + url)

        with self.assertRaisesRegex(pull.Refused, 'gh auth login'):
            pull.discover(target, fetch=fail_fetch, channel='early', which=lambda _: None)

        gh_path, cfg_path = write_fake_gh(f.base, {'logged_in': False, 'token': 'gho_synthetic_secret_123'})
        old_env = os.environ.get('FAKE_PRO_GH')
        os.environ['FAKE_PRO_GH'] = cfg_path
        self.addCleanup(lambda: os.environ.pop('FAKE_PRO_GH', None) if old_env is None
                        else os.environ.__setitem__('FAKE_PRO_GH', old_env))
        which = lambda name: gh_path if name == 'gh' else None

        with self.assertRaises(pull.Refused) as ctx:
            pull.discover(target, fetch=fail_fetch, channel='early', which=which)
        self.assertIn('gh auth login', str(ctx.exception))
        self.assertNotIn('gho_synthetic_secret_123', str(ctx.exception))

        Path(cfg_path).write_text(json.dumps({'logged_in': True, 'status': 404, 'token': 'gho_synthetic_secret_123'}))
        with self.assertRaises(pull.Refused) as ctx:
            pull.discover(target, fetch=fail_fetch, channel='early', which=which)
        self.assertIn('OpenWiz Pro', str(ctx.exception))
        self.assertIn('https://openwiz.dev/pro/', str(ctx.exception))
        self.assertNotIn('gho_synthetic_secret_123', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
