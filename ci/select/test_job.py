#!/usr/bin/env python3
"""The CI side of the selector (#432, K15): where a map comes from, and
what each job is told. Synthetic keys, tokens, repositories and maps only.

  python3 -I ci/select/test_job.py
"""
import base64
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job  # noqa: E402
import pick  # noqa: E402

REPO = 'example-owner/example-repo'
ISS = 'https://token.actions.githubusercontent.com'


def prime(bits, rng):
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and is_prime(n, rng):
            return n


def is_prime(n, rng):
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(24):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def keypair(seed):
    """A synthetic 2048-bit RSA key, made fresh here: (n, e, d)."""
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = prime(1024, rng), prime(1024, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def sign(claims, key, kid='k1', header=None):
    n, _, d = key
    head = b64(json.dumps(header or {'alg': 'RS256', 'kid': kid, 'typ': 'JWT'}).encode())
    body = b64(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    digest = job.DIGEST_INFO + hashlib.sha256(f'{head}.{body}'.encode()).digest()
    em = b'\x00\x01' + b'\xff' * (k - 3 - len(digest)) + b'\x00' + digest
    sig = pow(int.from_bytes(em, 'big'), d, n).to_bytes(k, 'big')
    return f'{head}.{body}.{b64(sig)}'


def jwks(key, kid='k1'):
    n, e, _ = key
    return {'keys': [{'kty': 'RSA', 'kid': kid, 'alg': 'RS256', 'use': 'sig',
                      'n': b64(n.to_bytes((n.bit_length() + 7) // 8, 'big')),
                      'e': b64(e.to_bytes(3, 'big'))}]}


KEY = keypair(1)
OTHER = keypair(2)
COMMIT = 'c' * 40
MAP = json.dumps({'schema': pick.MAP_SCHEMA, 'commit': COMMIT,
                  'units': {'rust:test:proof': {'files': ['tests/proof/main.rs'], 'dirs': []}}}).encode()


def claims(**over):
    c = {'iss': ISS, 'aud': job.audience(MAP), 'repository': REPO, 'ref': 'refs/heads/main', 'ref_type': 'branch',
         'event_name': 'push', 'workflow_ref': f'{REPO}/.github/workflows/ci.yml@refs/heads/main', 'sha': COMMIT,
         'run_id': '123', 'iat': 1_700_000_000, 'exp': 1_700_000_300}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


class Provenance(unittest.TestCase):
    def check(self, token, data=MAP, keys=None):
        return job.verify(data, token, keys or jwks(KEY), REPO)

    # #783: a manual dispatch from main is trusted like the nightly run.
    def test_a_push_the_nightly_run_or_a_dispatch_on_main_is_accepted(self):
        for event in ('push', 'schedule', 'workflow_dispatch'):
            with self.subTest(event):
                self.assertEqual(self.check(sign(claims(event_name=event), KEY))['event_name'], event)

    def test_every_other_source_is_refused(self):
        refused = {
            'a pull request\'s run': sign(claims(ref='refs/pull/7/merge', event_name='pull_request'), KEY),
            'a pull request event on main': sign(claims(event_name='pull_request'), KEY),
            'a workflow_dispatch from another branch': sign(claims(event_name='workflow_dispatch', ref='refs/heads/feature'), KEY),
            'a workflow_dispatch from a tag': sign(claims(event_name='workflow_dispatch', ref='refs/tags/main', ref_type='tag'), KEY),
            'a workflow_dispatch of ci.yml from another branch': sign(claims(
                event_name='workflow_dispatch', workflow_ref=f'{REPO}/.github/workflows/ci.yml@refs/heads/x'), KEY),
            'another event on main': sign(claims(event_name='workflow_run'), KEY),
            'another branch': sign(claims(ref='refs/heads/feature'), KEY),
            'a tag': sign(claims(ref='refs/tags/main', ref_type='tag'), KEY),
            'another repository': sign(claims(repository='someone/else'), KEY),
            'another workflow': sign(claims(workflow_ref=f'{REPO}/.github/workflows/other.yml@refs/heads/main'), KEY),
            'ci.yml from another branch': sign(claims(workflow_ref=f'{REPO}/.github/workflows/ci.yml@refs/heads/x'), KEY),
            'another issuer': sign(claims(iss='https://example.invalid'), KEY),
            'a map it wasn\'t signed for': sign(claims(aud=job.audience(MAP + b' ')), KEY),
            'a token for another commit': sign(claims(sha='d' * 40), KEY),
            'no sha': sign(claims(sha=None), KEY),
            'a token issued in the future': sign(claims(iat=4_000_000_000), KEY),
            'another key': sign(claims(), OTHER),
            'a key id the issuer doesn\'t list': sign(claims(), KEY, kid='k9'),
            'alg none': sign(claims(), KEY, header={'alg': 'none', 'kid': 'k1'}),
            'HS256': sign(claims(), KEY, header={'alg': 'HS256', 'kid': 'k1'}),
            'two parts': '.'.join(sign(claims(), KEY).split('.')[:2]),
            'not base64': 'a.b.c!',
            'empty': '',
        }
        for what, token in refused.items():
            with self.subTest(what):
                with self.assertRaises(job.Untrusted):
                    self.check(token)

    def test_a_tampered_map_or_signature_is_refused(self):
        token = sign(claims(), KEY)
        with self.assertRaises(job.Untrusted):
            self.check(token, data=MAP.replace(b'proof', b'proog'))
        head, body, sig = token.split('.')
        raw = bytearray(base64.urlsafe_b64decode(sig + '=='))
        raw[-1] ^= 1
        with self.assertRaises(job.Untrusted):
            self.check(f'{head}.{body}.{b64(bytes(raw))}')
        forged = b64(json.dumps(claims(event_name='schedule')).encode())
        with self.assertRaises(job.Untrusted):
            self.check(f'{head}.{forged}.{sig}')

    def test_claims_with_a_repeated_key_are_refused(self):
        n, _, _ = KEY
        good = sign(claims(), KEY)
        head, body, _ = good.split('.')
        text = json.dumps(claims())[:-1] + ', "event_name": "push"}'
        token = sign(json.loads(text), KEY)  # a well-formed control
        self.check(token)
        raw_body = b64(text.replace('"event_name": "push", ', '"event_name": "pull_request", ', 1).encode())
        k = (n.bit_length() + 7) // 8
        digest = job.DIGEST_INFO + hashlib.sha256(f'{head}.{raw_body}'.encode()).digest()
        em = b'\x00\x01' + b'\xff' * (k - 3 - len(digest)) + b'\x00' + digest
        sig = pow(int.from_bytes(em, 'big'), KEY[2], n).to_bytes(k, 'big')
        with self.assertRaises(job.Untrusted):
            self.check(f'{head}.{raw_body}.{b64(sig)}')

    def test_a_short_key_is_refused(self):
        small = keypair(3)
        n = small[0]
        short = (n >> 1100, small[1], small[2])
        with self.assertRaises(job.Untrusted):
            job.rsa_verify(short[0], short[1], b'x', b'\x00' * ((short[0].bit_length() + 7) // 8))


class Repo(unittest.TestCase):
    """A synthetic repository, a map traced on main, and its signed token."""

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.root)])
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 't@example.invalid')
        self.git('config', 'user.name', 't')
        for rel, text in {'tests/proof/main.rs': 'a\n', 'docs/a.md': 'a\n', 'crates/core/src/lib.rs': 'a\n',
                          'skills/image/scripts/screenshot.py': 'a\n', 'skills/triage/find-work.sh': 'a\n', 'skills/launch-fleet/scripts/fleet.sh': 'a\n',
                          'apps/web/test/unit/api.test.ts': 'a\n'}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        self.git('add', '-A')
        self.git('commit', '-qm', 'traced')
        self.traced = self.git('rev-parse', 'HEAD')
        self.maps = self.root.parent / (self.root.name + '-map')
        self.maps.mkdir()
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.maps)])
        self.units = self.root.parent / (self.root.name + '-units.txt')
        self.units.write_text('rust:test:proof\nrust:test:checks\nrust:lib:openwiz-core\nweb:unit:api\n')
        self.addCleanup(self.units.unlink)
        self.write_map()
        self.plain = self.root.parent / (self.root.name + '-plain')
        self.plain.write_text('plain\n')
        self.addCleanup(lambda: self.plain.unlink(missing_ok=True))

    def write_map(self, commit=None, event='push', sign_with=KEY):
        data = json.dumps({'schema': pick.MAP_SCHEMA, 'commit': commit or self.traced, 'units': {
            'rust:test:proof': {'files': ['tests/proof/main.rs'], 'dirs': []},
            'rust:lib:openwiz-core': {'files': ['crates/core/src/lib.rs'], 'dirs': []},
            'web:unit:api': {'files': ['apps/web/test/unit/api.test.ts'], 'dirs': []},
        }}).encode()
        (self.maps / 'map.json').write_bytes(data)
        token = sign(claims(aud=job.audience(data), sha=commit or self.traced, event_name=event), sign_with)
        (self.maps / 'map.jwt').write_text(token)

    def change(self, rel, text='b\n'):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)
        self.git('add', '-A')
        self.git('commit', '-qm', 'change ' + rel)

    def select(self):
        out = self.root.parent / (self.root.name + '-out')
        out.write_text('')
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        answer = job.select(plain=str(self.plain), map_dir=str(self.maps), root=str(self.root), repo=REPO,
                            keys=jwks(KEY), units_file=str(self.units), classify=False, github_output=str(out))
        lines = dict(line.split('=', 1) for line in out.read_text().splitlines())
        return answer, lines

    def test_a_trusted_map_selects_the_change_s_readers(self):
        self.change('tests/proof/main.rs')
        answer, out = self.select()
        self.assertEqual(out['selection'], 'selected', answer)
        self.assertEqual(out['rust-tests'], 'rust:test:checks rust:test:proof')
        self.assertEqual(out['web-tests'], 'none')
        self.assertEqual(out['web-files'], 'none')

    def test_k16_docs_skip_unneeded_steps_but_main_runs_every_step(self):
        self.change('docs/a.md')
        # Synthetic trace: checks reads no web export. Its own sources remain
        # the map's file dependency; this does not supply the selection answer.
        data = json.loads((self.maps / 'map.json').read_bytes())
        data['units']['rust:test:checks'] = {
            'files': ['tests/checks/main.rs'], 'dirs': [], 'web_export': False}
        for unit in data['units'].values():
            unit.setdefault('web_export', False)
        raw = json.dumps(data).encode()
        (self.maps / 'map.json').write_bytes(raw)
        (self.maps / 'map.jwt').write_text(sign(claims(aud=job.audience(raw), sha=self.traced), KEY))
        _, out = self.select()
        self.assertEqual(out['selection'], 'selected')
        for key in ('build-web', 'lint-rust', 'export-rust', 'export-web', 'build-site', 'image-skills'):
            self.assertEqual(out[key], 'false', (key, out))
        self.assertEqual(out['skill-tests'], 'none')
        self.plain.unlink()  # main/nightly do not get decide.sh's plain marker
        _, full = self.select()
        for key in ('build-web', 'lint-rust', 'export-rust', 'export-web', 'build-site', 'image-skills'):
            self.assertEqual(full[key], 'true', (key, full))
        self.assertEqual(full['skill-tests'], 'all')

    def test_k16_one_skill_folder_selects_its_suite(self):
        self.change('skills/triage/find-work.sh')
        _, out = self.select()
        self.assertEqual(out['skill-tests'], 'triage')

    def test_k16_launch_fleet_folder_selects_its_suite(self):
        self.change('skills/launch-fleet/scripts/fleet.sh')
        _, out = self.select()
        self.assertEqual(out['skill-tests'], 'launch-fleet')

    def test_k16_unrelated_change_selects_no_skill_suite(self):
        self.change('docs/a.md')
        _, out = self.select()
        self.assertEqual(out['skill-tests'], 'none')

    def test_k16_selector_change_selects_all_skill_suites(self):
        self.change('ci/select/job.py')
        _, out = self.select()
        self.assertEqual(out['skill-tests'], 'all')

    def metadata(self, **flags):
        data = json.loads((self.maps / 'map.json').read_bytes())
        data['units']['rust:test:checks'] = {'files': ['tests/checks/main.rs'], 'dirs': []}
        for uid, unit in data['units'].items():
            unit['web_export'] = flags.get(uid, False)
        raw = json.dumps(data).encode()
        (self.maps / 'map.json').write_bytes(raw)
        (self.maps / 'map.jwt').write_text(sign(claims(aud=job.audience(raw), sha=self.traced), KEY))

    def test_k16_selected_export_reader_needs_producer_and_its_download(self):
        self.metadata(**{'rust:test:proof': True})
        self.change('tests/proof/main.rs')
        _, out = self.select()
        self.assertEqual((out['build-web'], out['export-rust'], out['export-web']), ('true', 'true', 'false'))
        self.assertEqual(out['lint-rust'], 'true')

    def test_k16_web_reader_and_nonreader(self):
        self.metadata(**{'web:unit:api': True})
        self.change('apps/web/test/unit/api.test.ts')
        _, out = self.select()
        self.assertEqual((out['build-web'], out['export-rust'], out['export-web']), ('true', 'false', 'true'))
        # That negative trace describes the old test. This changed test may
        # start reading the export, so its download must remain scheduled.
        self.metadata()
        _, out = self.select()
        self.assertEqual((out['build-web'], out['export-rust'], out['export-web']), ('true', 'false', 'true'))

    def test_k16_changed_source_can_add_an_export_dependency(self):
        # CS7: old negative metadata must not suppress a new prerequisite.
        # Existing positive-reader tests never change a nonreader into a reader.
        self.metadata()
        self.change('apps/web/test/unit/api.test.ts',
                    "import fs from 'node:fs'; fs.readFileSync('out/index.html');\n")
        _, out = self.select()
        self.assertEqual(out['web-tests'], 'web:unit:api')
        self.assertEqual((out['build-web'], out['export-web']), ('true', 'true'))
        # The real tiny reader succeeds only when that scheduled artifact exists.
        (self.root / 'apps/web/out').mkdir()
        (self.root / 'apps/web/out/index.html').write_text('synthetic export')
        proc = subprocess.run(['node', '--input-type=module', '-e',
                               "import fs from 'node:fs'; fs.readFileSync('out/index.html');"],
                              cwd=self.root / 'apps/web', capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_k16_old_maps_and_unmapped_tests_keep_the_export(self):
        self.change('docs/a.md')
        _, out = self.select()  # old map, no export metadata, checks absent
        self.assertEqual((out['build-web'], out['export-rust']), ('true', 'true'))
        self.metadata()
        self.units.write_text(self.units.read_text() + 'rust:test:new-proof\n')
        _, out = self.select()  # new test absent from the trusted map
        self.assertEqual((out['build-web'], out['export-rust']), ('true', 'true'))

    def test_k16_malformed_export_metadata_runs_everything(self):
        self.change('docs/a.md')
        self.metadata(**{'rust:test:proof': 'false'})
        self.full('selector_error')

    def test_k16_image_suite_selects_its_browser_dependencies(self):
        self.change('skills/image/scripts/screenshot.py')
        _, out = self.select()
        self.assertEqual((out['skill-tests'], out['image-skills']), ('image', 'true'))

    def test_drift_on_main_since_the_trace_is_part_of_the_change(self):
        self.change('crates/core/src/lib.rs')  # merged to main after the trace
        self.change('tests/proof/main.rs')  # the pull request's own change
        _, out = self.select()
        self.assertEqual(out['rust-tests'], 'rust:lib:openwiz-core rust:test:checks rust:test:proof')

    def test_web_tests_are_named_by_file_for_the_runner(self):
        self.change('apps/web/test/unit/api.test.ts')
        _, out = self.select()
        self.assertEqual(out['web-tests'], 'web:unit:api')
        self.assertEqual(out['web-files'], 'test/unit/api.test.ts')

    def full(self, why):
        answer, out = self.select()
        self.assertEqual(out, {'selection': 'full', 'rust-tests': 'all', 'web-tests': 'all', 'web-files': 'all',
                               'skill-tests': 'all', 'build-web': 'true', 'lint-rust': 'true', 'export-rust': 'true',
                               'export-web': 'true', 'build-site': 'true', 'image-skills': 'true'})
        self.assertIn(why, answer['detail'])

    def test_no_plain_case_runs_everything(self):
        self.change('tests/proof/main.rs')
        self.plain.unlink()
        self.full('not the plain case')

    def test_no_map_runs_everything(self):
        self.change('tests/proof/main.rs')
        (self.maps / 'map.json').unlink()
        self.full('no map')

    def test_no_token_runs_everything(self):
        self.change('tests/proof/main.rs')
        (self.maps / 'map.jwt').unlink()
        self.full('no map')

    def test_a_map_from_a_pull_request_runs_everything(self):
        self.change('tests/proof/main.rs')
        self.write_map(event='pull_request')
        self.full('untrusted')

    def test_a_map_signed_by_another_key_runs_everything(self):
        self.change('tests/proof/main.rs')
        self.write_map(sign_with=OTHER)
        self.full('untrusted')

    def test_a_map_edited_after_signing_runs_everything(self):
        self.change('tests/proof/main.rs')
        data = (self.maps / 'map.json').read_bytes()
        (self.maps / 'map.json').write_bytes(data.replace(b'"dirs": []', b'"dirs": [ ]', 1))
        self.full('untrusted')

    def test_a_map_from_a_commit_that_is_not_an_ancestor_runs_everything(self):
        self.git('checkout', '-q', '-b', 'side')
        self.change('docs/a.md', 'side\n')
        side = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        self.change('tests/proof/main.rs')
        self.write_map(commit=side)
        self.full('not an ancestor')

    def test_a_map_from_a_commit_not_in_the_clone_runs_everything(self):
        self.change('tests/proof/main.rs')
        self.write_map(commit='e' * 40)
        self.full('not an ancestor')

    def test_a_selector_answer_of_everything_is_passed_on(self):
        self.change('.github/workflows/ci.yml')
        answer, out = self.select()
        self.assertEqual(out['selection'], 'full')
        self.assertIn('ci_change', answer['detail'])

    def test_a_crash_runs_everything(self):
        out = self.root.parent / (self.root.name + '-crash')
        out.write_text('')
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        answer = job.select(plain=str(self.plain), map_dir=str(self.maps), root=str(self.root), repo=REPO,
                            keys=None, units_file=str(self.units), classify=False, github_output=str(out),
                            fetch_keys=lambda: (_ for _ in ()).throw(OSError('no network')))
        self.assertEqual(out.read_text(), 'selection=full\nrust-tests=all\nweb-tests=all\nweb-files=all\n'
                         'skill-tests=all\nbuild-web=true\nlint-rust=true\nexport-rust=true\n'
                         'export-web=true\nbuild-site=true\nimage-skills=true\n')
        self.assertIn('no network', answer['detail'])


class Trace(unittest.TestCase):
    """Which runs trace their tests to make a map."""

    def test_a_push_the_nightly_run_or_a_dispatch_on_main_traces(self):
        for event in ('push', 'schedule', 'workflow_dispatch'):
            self.assertTrue(job.traces(event, 'refs/heads/main', []))

    def test_a_pull_request_traces_only_when_it_changes_the_tracer(self):
        self.assertFalse(job.traces('pull_request', 'refs/pull/1/merge', ['ci/select/pick.py', 'docs/a.md']))
        for path in ('ci/select/trace.py', 'ci/select/resolve.py', 'ci/select/map.py', 'ci/select/units.py'):
            self.assertTrue(job.traces('pull_request', 'refs/pull/1/merge', ['docs/a.md', path]))

    def test_nothing_else_traces(self):
        self.assertFalse(job.traces('push', 'refs/heads/other', []))
        self.assertFalse(job.traces('merge_group', 'refs/heads/gh-readonly-queue/main/x', ['ci/select/trace.py']))
        self.assertFalse(job.traces('schedule', 'refs/heads/other', []))
        self.assertFalse(job.traces('workflow_dispatch', 'refs/heads/other', []))
        self.assertFalse(job.traces('workflow_dispatch', 'refs/tags/main', ['ci/select/trace.py']))


class Planted(unittest.TestCase):
    """The planted-edit proof (planted.py): when it runs, and its verdict."""

    def test_only_a_pull_request_that_changes_it_plants_edits(self):
        self.assertTrue(job.plants('pull_request', ['docs/a.md', 'ci/select/planted.py']))
        self.assertFalse(job.plants('pull_request', ['ci/select/pick.py']))
        self.assertFalse(job.plants('pull_request', ['ci/select/planted.py'], has_map=False))
        for event in ('push', 'schedule', 'merge_group'):
            self.assertFalse(job.plants(event, ['ci/select/planted.py']))

    def test_a_skipped_test_that_fails_is_hidden_and_a_picked_one_caught(self):
        import planted
        v = planted.verdict({'a', 'b'}, {'a': 1, 'b': 0, 'c': 0, 'd': 101})
        self.assertEqual(v, {'caught_by': ['a'], 'hidden': ['d']})
        self.assertEqual(planted.verdict({'a'}, {'a': 0, 'b': 0}), {'caught_by': [], 'hidden': []})

    def test_the_planted_run_writes_its_records_into_a_folder_that_isn_t_there_yet(self):
        """Review R9 on #1579: after a fallback deleted select-records/ (or no
        trace made it), planted.py still writes its records. Runs the real
        main() on a synthetic tree; only the test runs themselves are stubbed."""
        import planted
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'f.txt'), 'w') as f:
                f.write('old\n')
            with open(os.path.join(tmp, 'map.json'), 'w') as f:
                json.dump({'schema': pick.MAP_SCHEMA, 'commit': COMMIT,
                           'units': {'rust:test:x': {'files': ['f.txt'], 'dirs': []}}}, f)
            saved = (planted.CASES, planted.HERE, planted.trace.commands, planted.trace.plain_run, os.getcwd())
            planted.CASES = [('f.txt', 'old', 'new', ('rust',))]
            planted.HERE = tmp
            planted.trace.commands = lambda lane, root, threads: {'rust:test:x': (['true'], root)}
            planted.trace.plain_run = lambda argv, cwd, env, log: (1, 0.0)
            out = os.path.join(tmp, 'select-records', 'planted-rust.jsonl')
            try:
                os.chdir(tmp)
                rc = planted.main(['rust', out])
            finally:
                planted.CASES, planted.HERE, planted.trace.commands, planted.trace.plain_run, cwd = saved
                os.chdir(cwd)
            self.assertEqual(rc, 0)
            with open(out) as f:
                row = json.loads(f.read())
            self.assertEqual((row['path'], row['caught_by'], row['hidden']), ('f.txt', ['rust:test:x'], []))
            with open(os.path.join(tmp, 'f.txt')) as f:
                self.assertEqual(f.read(), 'old\n')

    def run_planted(self, catchers, results):
        """planted.main() on a synthetic tree with one case whose edit
        `catchers` lanes must catch; each test's exit status from `results`."""
        import planted
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'f.txt'), 'w') as f:
                f.write('old\n')
            with open(os.path.join(tmp, 'map.json'), 'w') as f:
                json.dump({'schema': pick.MAP_SCHEMA, 'commit': COMMIT,
                           'units': {'rust:test:x': {'files': ['f.txt'], 'dirs': []}}}, f)
            saved = (planted.CASES, planted.HERE, planted.trace.commands, planted.trace.plain_run, os.getcwd())
            planted.CASES = [('f.txt', 'old', 'new', catchers)]
            planted.HERE = tmp
            planted.trace.commands = lambda lane, root, threads: {u: ([u], root) for u in results}
            planted.trace.plain_run = lambda argv, cwd, env, log: (results[argv[0]], 0.0)
            try:
                os.chdir(tmp)
                return planted.main(['rust', os.path.join(tmp, 'out.jsonl')])
            finally:
                planted.CASES, planted.HERE, planted.trace.commands, planted.trace.plain_run, cwd = saved
                os.chdir(cwd)

    def test_an_edit_its_lane_must_catch_and_nothing_does_fails(self):
        """Self-review on #1579: a planted edit no test catches proves nothing."""
        self.assertEqual(self.run_planted(('rust',), {'rust:test:x': 0, 'rust:test:y': 0}), 1)

    def test_an_edit_its_lane_catches_passes(self):
        self.assertEqual(self.run_planted(('rust',), {'rust:test:x': 1, 'rust:test:y': 0}), 0)

    def test_an_edit_another_lane_must_catch_passes_here(self):
        self.assertEqual(self.run_planted(('web',), {'rust:test:x': 0, 'rust:test:y': 0}), 0)

    def test_every_case_names_the_lanes_that_must_catch_it(self):
        import planted
        for case in planted.CASES:
            with self.subTest(case[0]):
                self.assertEqual(len(case), 4)
                self.assertTrue(case[3] and set(case[3]) <= {'rust', 'web'})

    def test_every_case_edits_its_file_exactly_once(self):
        import planted
        root = HERE.parent.parent
        for path, old, new, *_ in planted.CASES:
            with self.subTest(path):
                self.assertEqual((root / path).read_text().count(old), 1)
                self.assertNotEqual(old, new)


if __name__ == '__main__':
    unittest.main()
