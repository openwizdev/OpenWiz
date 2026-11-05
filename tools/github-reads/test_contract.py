#!/usr/bin/env python3
"""C1 offline contract conformance; no network, credentials or runtime helper.

Run the proofs, or --check RECORD --current BINDING for explicit local files.
A fresh result means synthetic conformance, never verified GitHub authority.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).with_name('fixtures') / 'contract'
_spec = importlib.util.spec_from_file_location('schema_reader', ROOT / 'ci/escapes/escapes.py')
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)
SCHEMA = ROOT / 'contracts/agent-github-reads.v1.schema.json'


def schema_errors(value, kind):
    schema = J.strict_json(SCHEMA.read_text())
    errors = J.lint(schema)
    return errors or J.errors_of(schema, schema['$defs'][kind], value, '$')


def assess(record, current):
    if schema_errors(record, 'record') or schema_errors(current, 'current'):
        return 'refused', 'shape'
    request, auth, budget, result = (record[k] for k in ('request', 'auth', 'budget', 'result'))
    now, age = current['now'], current['max_age_s']
    scope = ('kind', 'host', 'installation_id', 'permissions', 'generation', 'storage')
    if (request != current['request'] or
            any(auth[k] != current['auth'][k] for k in scope) or
            set(auth['repositories']) != set(current['auth']['repositories']) or
            budget['installation_id'] != auth['installation_id']):
        return 'refused', 'binding'
    if (request['operation'] != {'rest': 'rest-read', 'graphql': 'graphql-read'}[request['api']] or
            request['repository'].split('/')[1] in ('.', '..')):
        return 'refused', 'shape'
    for a in (auth, current['auth']):
        if (a['state'] != 'active' or a['expires_at'] <= now or
                a['expires_at'] - a['verified_at'] > 3900 or
                not 0 < a['verified_at'] <= now or now - a['verified_at'] > age or
                request['repository'] not in a['repositories']):
            return 'refused', 'credential'
    shared = record['sharing']
    if shared['seam'] != 'owner-filesystem' or shared['upstream_reads'] != 1:
        return 'refused', 'sharing'
    if result['state'] != 'ok' or not result['complete'] or result['status'] not in (200, 304):
        return 'refused', 'incomplete'
    if (not 0 < result['fetched_at'] <= result['validated_at'] <= now or
            not 0 < result['read_started_at'] <= result['validated_at'] or
            (result['source'] == 'network' and result['fetched_at'] < result['read_started_at']) or
            now - result['validated_at'] > age or current['read_started_at'] > now):
        return 'refused', 'freshness'
    if ((result['source'] == 'revalidated' or result['status'] == 304) and
            not (request['api'] == 'rest' and result['source'] == 'revalidated' and result['status'] == 304 and
                 result['authenticated'] and result['etag_matched'])):
        return 'refused', 'conditional'
    if request['purpose'] == 'authority' and (
            result['source'] == 'cache' or result['read_started_at'] < current['read_started_at'] or
            min(auth['verified_at'], current['auth']['verified_at']) < current['read_started_at']):
        return 'refused', 'authority-needs-current-read'
    if not result['authenticated']:
        return 'refused', 'credential'
    # Display cache hits consume no new quota. Neither reset nor token rotation
    # replenishes an installation budget without an independently observed pool.
    if result['source'] == 'cache':
        return 'display', 'cache'
    for pool in (budget['rest'], budget['graphql']):
        if pool is None:
            return 'deferred', 'budget-unknown'
        if pool['remaining'] > pool['limit'] or pool['reserved'] > pool['limit']:
            return 'refused', 'budget'
        if (not 0 < pool['observed_at'] <= now < pool['reset_at'] or
                now - pool['observed_at'] > age):
            return 'deferred', 'budget-unknown'
        if pool['remaining'] <= pool['reserved']:
            return 'deferred', 'primary-budget'
    if max(budget['secondary_not_before'], budget['pace_not_before']) > now:
        return 'deferred', 'backoff'
    return 'fresh', 'current'


class Contract(unittest.TestCase):
    def test_schema_and_refusal_cases(self):
        """C1-auth/cache/budget/share: literal fixture decisions, not live proof."""
        base = J.strict_json((FIX / 'base.json').read_text())
        for case in J.strict_json((FIX / 'cases.json').read_text()):
            with self.subTest(case=case['name']):
                value = copy.deepcopy(base)
                for path, replacement in case['set'].items():
                    node = value
                    parts = path.split('.')
                    for part in parts[:-1]:
                        node = node[part]
                    node[parts[-1]] = replacement
                self.assertEqual(assess(value['record'], value['current']), tuple(case['expect']))

    def test_strict_wire_and_closed_shapes(self):
        """C1-secret: credentials/unknown keys and JSON coercions cannot enter records."""
        base = J.strict_json((FIX / 'base.json').read_text())
        for text in ('{"schema":1,"schema":2}', '{"now":NaN}', '{"now":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                J.strict_json(text)
        for kind, field, value in (
            ('record', 'token', 'synthetic-forbidden-value'),
            ('record', 'private_key', 'synthetic-forbidden-value'),
            ('current', 'now', True), ('current', 'now', '1000'),
        ):
            with self.subTest(kind=kind, field=field):
                item = copy.deepcopy(base[kind])
                item[field] = value
                self.assertTrue(schema_errors(item, kind))
        for field in ('auth', 'request', 'budget', 'result', 'sharing'):
            with self.subTest(field=field):
                item = copy.deepcopy(base['record'])
                item[field]['token'] = 'synthetic-forbidden-value'
                self.assertTrue(schema_errors(item, 'record'))

    def test_cli_requires_independent_binding_and_refuses_without_echoing_input(self):
        """C1-cache/secret: caller-supplied records cannot supply their own current binding."""
        base = J.strict_json((FIX / 'base.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            record, current = Path(folder) / 'record.json', Path(folder) / 'current.json'
            record.write_text(json.dumps(base['record']))
            current.write_text(json.dumps(base['current']))
            args = [sys.executable, '-I', str(Path(__file__)), '--check', str(record)]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('synthetic-forbidden-value', result.stdout + result.stderr)
            result = subprocess.run([*args, '--current', str(current)], capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, 'fresh: current'))
            record.write_text('{"token":"synthetic-forbidden-value"}')
            result = subprocess.run([*args, '--current', str(current)], capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (1, 'refused: shape'))
            self.assertNotIn('synthetic-forbidden-value', result.stdout + result.stderr)


if __name__ == '__main__':
    if '--check' in sys.argv:
        if len(sys.argv) != 5 or sys.argv[1] != '--check' or sys.argv[3] != '--current':
            print('usage: test_contract.py --check RECORD --current BINDING', file=sys.stderr)
            sys.exit(2)
        try:
            state, reason = assess(J.strict_json(Path(sys.argv[2]).read_text()),
                                   J.strict_json(Path(sys.argv[4]).read_text()))
            print(state + ': ' + reason)
            sys.exit(0 if state in ('fresh', 'display') else 1)
        except (ValueError, OSError):
            print('refused: unreadable contract input', file=sys.stderr)
            sys.exit(1)
    else:
        unittest.main()
