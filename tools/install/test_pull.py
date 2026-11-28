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

    def _early_fixture(self, cfg):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        gh_path, cfg_path = write_fake_gh(f.base, cfg)
        old_env = os.environ.get('FAKE_PRO_GH')
        os.environ['FAKE_PRO_GH'] = cfg_path
        self.addCleanup(lambda: os.environ.pop('FAKE_PRO_GH', None) if old_env is None
                        else os.environ.__setitem__('FAKE_PRO_GH', old_env))
        return pull, f, fixture.TARGETS[2], gh_path, cfg_path, lambda name: gh_path if name == 'gh' else None

    def test_early_channel_follows_newest_semver_across_pro_and_public_and_refuses_rollback(self):
        cfg = {
            'logged_in': True, 'status': 200, 'assets': '',
            'releases': [
                {'tag_name': 'v0.1.2-rc.1', 'prerelease': True, 'draft': False},
                {'tag_name': 'v0.1.2-rc.2', 'prerelease': True, 'draft': False},
                {'tag_name': 'v0.1.3-rc.1', 'prerelease': True, 'draft': True},
                {'tag_name': 'v0.1.3', 'prerelease': False, 'draft': False},
            ],
        }
        pull, f, target, _, cfg_path, which = self._early_fixture(cfg)
        assets_root = f.base / 'pro-assets'
        cfg['assets'] = str(assets_root)
        Path(cfg_path).write_text(json.dumps(cfg))

        def populate_pro(rc_version, source):
            base = rc_version.split('-rc.', 1)[0]
            archive_name = f'openwiz-{base}-{target}.tar.gz'
            b = f.bundle(version=base, source=source, mutate=lambda m: m.update(archive=archive_name))
            raw, arch = b[0].read_bytes(), b[1].read_bytes()
            tag_dir = assets_root / ('v' + rc_version)
            tag_dir.mkdir(parents=True, exist_ok=True)
            (tag_dir / f'openwiz-{target}.sha256').write_bytes(
                f'{fixture.sha(raw)}  openwiz-{target}.manifest.json\n'.encode())
            (tag_dir / f'openwiz-{target}.manifest.json').write_bytes(raw)
            (tag_dir / f'openwiz-{base}-{target}.manifest.json').write_bytes(raw)
            (tag_dir / archive_name).write_bytes(arch)
            (tag_dir / 'SHA256SUMS').write_bytes(release_sums(raw, arch, target, base, archive_name))
            return b, raw

        def install_early(bundle, raw, rc=None):
            cmd = [sys.executable, str(HERE / 'install.py'), '--manifest', str(bundle[0]),
                   '--archive', str(bundle[1]), '--manifest-sha256', fixture.sha(raw),
                   '--root', str(f.root), '--target', target, '--channel', 'early']
            if rc:
                cmd += ['--release-version', rc]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        rc1, raw_rc1 = populate_pro('0.1.2-rc.1', '1' * 40)
        rc2, raw_rc2 = populate_pro('0.1.2-rc.2', '2' * 40)
        populate_pro('0.1.3-rc.1', '4' * 40)
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

        install_early(rc1, raw_rc1, '0.1.2-rc.1')
        self.assertEqual((f.root / 'channel.json').read_text(),
                         '{"schema":"openwiz.update-channel.v1","channel":"early"}\n')

        cand = pull.discover(target, fetch=pub_fetch, root=f.root, which=which)
        self.assertEqual((cand['version'], cand['channel'], cand['origin']), ('0.1.2-rc.2', 'early', 'early'))
        staged = pull.stage(target, cand['version'], cand['source'], cand['manifest_sha256'],
                            f.root, f.root / 'state', fetch=pub_fetch, which=which)
        self.assertEqual((staged['version'], staged['activated']), ('0.1.2-rc.2', False))
        install_early(rc2, raw_rc2, '0.1.2-rc.2')

        with self.assertRaisesRegex(pull.Refused, 'published version must advance'):
            pull.stage(target, '0.1.2-rc.1', '1' * 40, fixture.sha(raw_rc1),
                       f.root, f.root / 'state', fetch=pub_fetch, which=which)

        current_pub.update(bundle=pub_new, version='0.1.2')
        cand = pull.discover(target, fetch=pub_fetch, root=f.root, which=which)
        self.assertEqual((cand['version'], cand['channel'], cand['origin']), ('0.1.2', 'early', 'public'))
        staged = pull.stage(target, cand['version'], cand['source'], cand['manifest_sha256'],
                            f.root, f.root / 'state', fetch=pub_fetch, which=which)
        self.assertEqual((staged['version'], staged['activated']), ('0.1.2', False))
        install_early(pub_new, pub_new[0].read_bytes())
        self.assertEqual((f.root / 'channel.json').read_text(),
                         '{"schema":"openwiz.update-channel.v1","channel":"early"}\n')
        self.assertFalse((f.root / 'early-release.json').exists())

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
        pull, _, target, gh_path, cfg_path, which = self._early_fixture(
            {'logged_in': False, 'token': 'gho_synthetic_secret_123'})
        fail_fetch = lambda url, limit: self.fail('must not fetch public before Pro auth/access check: ' + url)

        with self.assertRaisesRegex(pull.Refused, 'gh auth login'):
            pull.discover(target, fetch=fail_fetch, channel='early', which=lambda _: None)

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

        env = dict(os.environ, PATH=str(Path(gh_path).parent) + os.pathsep + '/usr/bin:/bin', FAKE_PRO_GH=cfg_path)
        Path(cfg_path).write_text(json.dumps({'logged_in': False, 'token': 'gho_synthetic_secret_123'}))
        out_cli = subprocess.run([sys.executable, '-I', str(HERE / 'pull.py'), 'discover', target, '--channel', 'early'],
                                 capture_output=True, text=True, env=env)
        Path(cfg_path).write_text(json.dumps({'logged_in': True, 'status': 404, 'token': 'gho_synthetic_secret_123'}))
        pro_cli = subprocess.run([sys.executable, '-I', str(HERE / 'pull.py'), 'discover', target, '--channel', 'early'],
                                 capture_output=True, text=True, env=env)
        self.assertEqual((out_cli.returncode, pro_cli.returncode), (1, 1))
        self.assertIn('gh auth login', out_cli.stderr)
        self.assertIn('OpenWiz Pro', pro_cli.stderr)
        self.assertIn('https://openwiz.dev/pro/', pro_cli.stderr)
        self.assertNotIn('gho_synthetic_secret_123', out_cli.stderr + pro_cli.stderr)

    def test_early_discover_prefers_newer_feed_public_release_over_older_latest_and_rc(self):
        pull, f, target, _, cfg_path, which = self._early_fixture({
            'logged_in': True, 'status': 200, 'assets': '',
            'releases': [{'tag_name': 'v0.1.2-rc.1', 'prerelease': True, 'draft': False}],
        })
        old_pub = f.bundle(version='0.1.0', source='a' * 40)
        new_pub = f.bundle(version='0.1.2', source='b' * 40)
        rc_pub = f.bundle(version='0.1.2', source='c' * 40)
        rc_dir = f.base / 'pro-feed-assets/v0.1.2-rc.1'
        rc_dir.mkdir(parents=True)
        rc_raw = rc_pub[0].read_bytes()
        (rc_dir / f'openwiz-{target}.sha256').write_bytes(f'{fixture.sha(rc_raw)}  openwiz-{target}.manifest.json\n'.encode())
        (rc_dir / f'openwiz-{target}.manifest.json').write_bytes(rc_raw)
        Path(cfg_path).write_text(json.dumps({
            'logged_in': True, 'status': 200, 'assets': str(f.base / 'pro-feed-assets'),
            'releases': [{'tag_name': 'v0.1.2-rc.1', 'prerelease': True, 'draft': False}],
        }))
        seen = []

        def fetch(url, limit):
            seen.append(url)
            if url == pull.FEED:
                return ('<entry><link href="https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.0"/>'
                        '<link href="https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.2"/></entry>').encode()
            b = new_pub if '/download/v0.1.2/' in url else old_pub if '/latest/download/' in url else None
            if b is None:
                raise pull.NotFound('404 at ' + url)
            raw = b[0].read_bytes()
            return f'{fixture.sha(raw)}  openwiz-{target}.manifest.json\n'.encode() if url.endswith('.sha256') else raw

        self.assertEqual(pull.discover(target, fetch=fetch)['version'], '0.1.0')
        self.assertNotIn(pull.FEED, seen)
        early = pull.discover(target, fetch=fetch, channel='early', which=which)
        self.assertEqual((early['version'], early['origin']), ('0.1.2', 'public'))


if __name__ == '__main__':
    unittest.main()
