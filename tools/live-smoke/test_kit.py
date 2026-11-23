import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FixtureCase = runpy.run_path(str(HERE / 'test_smoke.py'))['FixtureCase']
SHIP3 = ['install', 'json', 'send', 'new', 'app']
PRIVATE = 'thr_synthetic_private_input'
SCOPE = {'targets': ['synthetic-target'], 'writes': {'send': 1, 'new': 1},
         'app_permissions': [], 'spending_cents': 0}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def run(*argv, env=None, timeout=10):
    return subprocess.run([sys.executable, '-I', *map(str, argv)], capture_output=True,
                          text=True, timeout=timeout, env=env)


class Claims(FixtureCase):
    def setUp(self):
        super().setUp()
        steps = []
        for claim in SHIP3:
            self.replies[claim] = {'exit': 0, 'out': json.dumps({'count': 1, 'known': True})}
            steps.append({'id': claim, 'claim': claim, 'kind': 'write' if claim in ('send', 'new') else 'read',
                          'argv': [str(self.fake), claim], 'exit': 0,
                          'checks': [{'path': '/count', 'equals': 1}]})
        self.kit.update(claims=list(SHIP3), steps=steps)

    def test_a_narrowed_kit_reports_exactly_its_declared_claims(self):
        doc = self.report(self.invoke(), 0)
        self.assertEqual(doc['claims'], {c: 'pass' for c in SHIP3})
        self.assertEqual(self.call_list(), [['ls', '--json']] + [[c] for c in SHIP3])

    def test_declared_claims_must_match_the_steps_exactly(self):
        rows = {
            'declared, no step': (lambda: self.kit['steps'].pop(0), 'missing_claim'),
            'step outside the declaration': (lambda: self.kit['claims'].remove('install'), 'missing_claim'),
            'send without its write': (lambda: self.kit['steps'][2].update(kind='read'), 'missing_write'),
            'unknown claim': (lambda: self.kit['claims'].append('cockpit_page'), 'invalid_kit'),
            'repeated claim': (lambda: self.kit['claims'].append('json'), 'invalid_kit'),
            'empty declaration': (lambda: self.kit.update(claims=[]), 'invalid_kit'),
        }
        clean = json.loads(json.dumps(self.kit))
        for name, (change, reason) in rows.items():
            with self.subTest(name):
                self.kit = json.loads(json.dumps(clean))
                change()
                self.state = self.root / ('state-' + name.replace(' ', '-').replace(',', ''))
                self.assertEqual(self.report(self.invoke(), 2)['reason'], reason)
                self.assertEqual(self.call_list(), [])


class Coverage(FixtureCase):
    def test_a_risk_step_missing_from_coverage_refuses_before_any_step(self):
        steps = [{'id': c, 'claim': c, 'kind': 'write' if c in ('send', 'new') else 'read',
                  'argv': [str(self.fake), c], 'exit': 0, 'checks': [{'path': '/count', 'equals': 1}]}
                 for c in SHIP3]
        self.replies.update({c: {'exit': 0, 'out': json.dumps({'count': 1})} for c in SHIP3})
        release = {'scope': SCOPE, 'products': [{'product': 'cli', 'target': 'x86_64-unknown-linux-gnu'}],
                   'coverage': [{'version': '0.1.0', 'promise': 'synthetic', 'steps': ['install', 'json', 'new']}],
                   'risk': {'send': ['send'], 'new': ['new'], 'app_permissions': [], 'spending': []},
                   'gaps': ['synthetic gap']}
        self.kit.update(claims=list(SHIP3), steps=steps, release=release)
        bad = {'send outside every row': ({}, 'coverage_mismatch'),
               'risk not a dict': ({'risk': ['send']}, 'invalid_release'),
               'coverage not a list': ({'coverage': {'steps': ['send']}}, 'invalid_release'),
               'a row with no version or promise, on a missing step': (
                   {'coverage': [{'steps': ['ghost', 'new']}], 'risk': dict(release['risk'], send=['ghost'])},
                   'invalid_release')}
        for name, (change, reason) in bad.items():
            with self.subTest(name):
                self.kit['release'] = dict(release, **change)
                self.state = self.root / name.replace(' ', '-').replace(',', '')
                self.assertEqual(self.report(self.invoke(), 2)['reason'], reason)
                self.assertEqual(self.call_list(), [])
        self.kit['release'] = release
        release['coverage'][0]['steps'].append('send')
        self.state = self.root / 'covered'
        self.assertEqual(self.report(self.invoke(), 0)['claims'], {c: 'pass' for c in SHIP3})


class Port(FixtureCase):
    def pinned(self, name, text):
        path = self.root / name
        path.write_text(text)
        self.kit['artifacts'][str(path)] = self.sha(path)
        return str(path)

    def terminal(self, argv):
        step = next(s for s in self.kit['steps'] if s['claim'] == 'json')
        step['argv'] = argv

    def test_a_kit_that_asks_for_7370_refuses_before_any_effect(self):
        python = sys.executable
        self.kit['artifacts'][python] = self.sha(Path(python))
        http_probe = str(HERE / 'http.py')
        rows = {
            'legacy default port key': lambda: self.kit.update(default_terminal_port='7370'),
            'explicit ui port': lambda: self.terminal([self.kit['openwiz'], 'ui', '--port', '7370']),
            'no-argument ui': lambda: self.terminal([self.kit['openwiz'], 'ui']),
            'no-argument program through a driver': lambda: self.terminal(
                [str(self.fake), 'terminal', self.kit['openwiz']]),
            'http probe': lambda: (self.kit['artifacts'].update({http_probe: self.sha(Path(http_probe))}),
                                   self.terminal([python, '-I', http_probe, '7370', '/api/v1/loops'])),
        }
        clean = json.loads(json.dumps(self.kit))
        for name, change in rows.items():
            with self.subTest(name):
                self.kit = json.loads(json.dumps(clean))
                change()
                self.state = self.root / ('state-' + name.replace(' ', '-'))
                doc = self.report(self.invoke(), 2)
                self.assertEqual(doc['reason'], 'reserved_port')
                self.assertEqual(self.call_list(), [])
                self.assertFalse(self.state.exists())


class Inputs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / 'program'
        self.fake.write_text('#!/bin/sh\nexit 0\n')
        self.fake.chmod(0o700)
        self.run_dir = self.root / 'run'
        self.run_dir.mkdir(mode=0o700)

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def standard_records(self):
        names = set()

        def collect(value):
            if isinstance(value, dict):
                [collect(v) for v in value.values()]
            elif isinstance(value, list):
                [collect(v) for v in value]
            elif isinstance(value, str) and value.startswith('@'):
                names.add(value[1:])
        collect(json.loads((HERE / 'combined.template.json').read_text()))
        records = {}
        for name in names:
            if name == 'release_targets':
                records[name] = SCOPE['targets']
            elif name == 'release_products':
                records[name] = [{'product': 'cli', 'target': 'x86_64-unknown-linux-gnu'}]
            elif name == 'release_gaps':
                records[name] = ['synthetic gap']
            elif name == 'release_version':
                records[name] = '0.1.0'
            elif name.startswith('promise_'):
                records[name] = 'synthetic_' + name
            elif name.endswith('_checks'):
                records[name] = [{'path': '/count', 'equals': 1}]
            elif name.endswith('_argv'):
                records[name] = [str(self.fake), 'readback']
            else:
                records[name] = str(self.fake)
        openwiz = self.root / 'openwiz'
        openwiz.write_text('#!/bin/sh\nexit 0\n')
        openwiz.chmod(0o700)
        records.update(mode='fixture', cwd=str(self.root), env={},
                       send_thread=PRIVATE, openwiz=str(openwiz),
                       artifacts={str(self.fake): self.sha(self.fake), str(openwiz): self.sha(openwiz)},
                       source={'checkout': str(self.root), 'head': '0' * 40})
        return records

    def write(self, path, value, mode=0o600):
        path.write_text(json.dumps(value))
        path.chmod(mode)
        return path

    def assemble(self, *records, out=None):
        out = out or self.run_dir / 'inputs.json'
        args = [HERE / 'inputs.py', '--out', out]
        for path in records:
            args += ['--records', path]
        return run(*args), out

    def checkout_alias(self, name='outside-run', into='private'):
        checkout = self.root / ('checkout-' + name)
        subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
        (checkout / 'private').mkdir()
        alias = self.root / name
        alias.symlink_to(checkout / into if into else checkout, target_is_directory=True)
        return checkout, alias

    def test_records_assemble_one_owner_only_file(self):
        records = self.standard_records()
        first = dict(list(records.items())[:12])
        second = dict(list(records.items())[12:])
        result, out = self.assemble(self.write(self.root / 'a.json', first),
                                    self.write(self.root / 'b.json', second))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(PRIVATE, result.stdout + result.stderr)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        inputs = json.loads(out.read_text())
        self.assertEqual(inputs, records)
        self.assertEqual(json.loads(result.stdout), {'assembled': True, 'names': len(records), 'records': 2})
        refusals = {
            'shared records': ([self.write(self.root / 'shared.json', records, 0o644)], 'records_not_owner_only'),
            'conflict': ([self.write(self.root / 'c1.json', {'project': 'prj_syn_0001'}),
                          self.write(self.root / 'c2.json', {'project': 'prj_syn_0002'})], 'conflicting_record'),
        }
        checkout, alias = self.checkout_alias()
        (checkout / 'private' / 'records.json').write_text(json.dumps(records))
        (checkout / 'private' / 'records.json').chmod(0o600)
        refusals['records through an alias'] = ([alias / 'records.json'], 'inside_checkout')
        refusals['records through alias-dotdot'] = ([alias / '..' / 'private' / 'records.json'], 'inside_checkout')
        for name, (paths, reason) in refusals.items():
            with self.subTest(name):
                result, target = self.assemble(*paths, out=self.run_dir / (name.replace(' ', '-') + '.json'))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout), {'assembled': False, 'reason': reason})
                self.assertFalse(target.exists())
        for name, target, reason in (
                ('out through an alias', alias / 'inputs.json', 'inside_checkout'),
                ('out through an alias above it', self.checkout_alias('outside-root', None)[1]
                 / 'private' / 'inputs.json', 'inside_checkout'),
                ('out through alias/.. (the re-check reproduction)', alias / '..' / 'private' / 'inputs.json',
                 'inside_checkout'),
                ('.. after the deepest existing folder', self.run_dir / 'missing' / '..' / 'inputs.json',
                 'unsafe_path')):
            with self.subTest(name):
                result, _ = self.assemble(self.root / 'a.json', self.root / 'b.json', out=target)
                self.assertEqual((result.returncode, json.loads(result.stdout)),
                                 (2, {'assembled': False, 'reason': reason}))
                self.assertFalse(os.path.lexists(target))
                self.assertNotIn(PRIVATE, result.stdout)
                self.assertEqual(sorted(p.name for p in (checkout / 'private').iterdir()), ['records.json'])
        outside = self.root / 'outside-target' / 'deep'
        outside.mkdir(parents=True)
        (self.root / 'outside-target' / 'run').mkdir(mode=0o700)
        (self.root / 'outside-alias').symlink_to(outside, target_is_directory=True)
        target = self.root / 'outside-alias' / '..' / 'run' / 'inputs.json'
        result, _ = self.assemble(self.root / 'a.json', self.root / 'b.json', out=target)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads((self.root / 'outside-target' / 'run' / 'inputs.json').read_text()), records)
        result, _ = self.assemble(self.root / 'a.json', out=out)
        self.assertEqual(json.loads(result.stdout)['reason'], 'exists')
        self.assertEqual(json.loads(out.read_text()), inputs)

    def test_prepare_prints_kit_and_scope_digests_and_refuses_unsafe_inputs(self):
        inputs = self.standard_records()
        good = self.write(self.run_dir / 'inputs.json', inputs)
        out = self.run_dir / 'kit.json'
        result = run(HERE / 'prepare.py', '--inputs', good, '--out', out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(PRIVATE, result.stdout + result.stderr)
        kit = json.loads(out.read_text())
        self.assertEqual(json.loads(result.stdout), {
            'prepared': True, 'kit_sha256': hashlib.sha256(json.dumps(
                kit, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest(),
            'scope_sha256': canonical_sha(SCOPE)})
        original = out.read_bytes()
        again = run(HERE / 'prepare.py', '--inputs', good, '--out', out)
        self.assertEqual((again.returncode, out.read_bytes()), (2, original))
        checkout = self.root / 'checkout'
        subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
        (checkout / 'private').mkdir()
        rows = {
            'shared inputs': (self.write(self.run_dir / 'shared.json', inputs, 0o640), out, 'inputs_not_owner_only'),
            'inputs in a checkout': (self.write(checkout / 'private' / 'inputs.json', inputs), out, 'inside_checkout'),
            'kit in a checkout': (good, checkout / 'kit.json', 'inside_checkout'),
            'kit through an alias': (good, self.checkout_alias('kit-alias')[1] / 'kit.json', 'inside_checkout'),
            'inputs through an alias': (self.write(self.checkout_alias('inputs-alias')[1] / 'inputs.json', inputs),
                                        out, 'inside_checkout'),
            'inputs through alias-dotdot': (self.write(self.checkout_alias('dots-in')[1] / 'inputs.json', inputs)
                                        .parent / '..' / 'private' / 'inputs.json', out, 'inside_checkout'),
            'kit through alias-dotdot': (good, self.checkout_alias('dots-out')[1] / '..' / 'private' / 'kit.json',
                                     'inside_checkout'),
            'stale input': (self.write(self.run_dir / 'stale.json', dict(inputs, fleet_scope={})), out, 'unused_input'),
            'missing input': (self.write(self.run_dir / 'missing.json', {k: v for k, v in inputs.items() if k != 'install_root'}),
                              out, 'missing_input'),
            'token value': (self.write(self.run_dir / 'token.json', dict(inputs, send_op='ghs_' + 'A' * 36)),
                            out, 'credential_in_inputs'),
        }
        for name, (source, target, reason) in rows.items():
            with self.subTest(name):
                fresh = target if target != out else self.run_dir / (name.replace(' ', '-') + '-kit.json')
                result = run(HERE / 'prepare.py', '--inputs', source, '--out', fresh)
                self.assertEqual(result.returncode, 2)
                doc = json.loads(result.stdout)
                self.assertEqual((doc['prepared'], doc['reason']), (False, reason))
                self.assertNotIn(PRIVATE, result.stdout)
                self.assertFalse(os.path.lexists(fresh))
        for name in ('checkout-kit-alias', 'checkout-dots-out'):
            self.assertEqual(list((self.root / name / 'private').iterdir()), [], name)
        (self.root / 'kit-target' / 'deep').mkdir(parents=True)
        (self.root / 'kit-target' / 'run').mkdir(mode=0o700)
        (self.root / 'kit-link').symlink_to(self.root / 'kit-target' / 'deep', target_is_directory=True)
        allowed = run(HERE / 'prepare.py', '--inputs', good, '--out', self.root / 'kit-link' / '..' / 'run' / 'kit.json')
        self.assertEqual(allowed.returncode, 0, allowed.stdout)
        self.assertTrue((self.root / 'kit-target' / 'run' / 'kit.json').is_file())
        self.assertEqual(json.loads(run(HERE / 'prepare.py', '--inputs', rows['missing input'][0],
                                        '--out', self.run_dir / 'm.json').stdout)['missing'], ['install_root'])

    def test_dry_run_binds_a_synthetic_candidate_and_runs_nothing(self):
        inputs = self.standard_records()
        source = self.write(self.run_dir / 'inputs.json', inputs)
        kit_path = self.run_dir / 'kit.json'
        prepared = json.loads(run(HERE / 'prepare.py', '--inputs', source, '--out', kit_path).stdout)
        body = {'kit': {'sha256': prepared['kit_sha256'], 'scope_sha256': prepared['scope_sha256']}}
        candidate = self.write(self.run_dir / 'candidate.json', {
            'schema': 'openwiz.release-candidate.v1', 'candidate': body, 'candidate_sha256': canonical_sha(body)})
        state = self.run_dir / 'checkpoint'
        result = run(HERE / 'smoke.py', '--kit', kit_path, '--state', state, '--dry-run', '--candidate', candidate)
        self.assertEqual(result.returncode, 0, result.stdout)
        doc = json.loads(result.stdout)
        self.assertEqual((doc['verdict'], doc['reason']), ('not_run', 'dry_run'))
        self.assertEqual(doc['claims'], {c: 'not_run' for c in SHIP3})
        self.assertFalse(state.exists())
        other = dict(body, kit=dict(body['kit'], scope_sha256='0' * 64))
        wrong = self.write(self.run_dir / 'other.json', {
            'schema': 'openwiz.release-candidate.v1', 'candidate': other, 'candidate_sha256': canonical_sha(other)})
        result = run(HERE / 'smoke.py', '--kit', kit_path, '--state', state, '--dry-run', '--candidate', wrong)
        self.assertEqual((result.returncode, json.loads(result.stdout)['reason']), (2, 'candidate_mismatch'))
        self.assertFalse(state.exists())

if __name__ == '__main__':
    unittest.main()
