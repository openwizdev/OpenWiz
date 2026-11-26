#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load('setup_onboard_check', HERE / 'check.py')
CONTRACT = (ROOT / 'contracts/setup-onboard.v1.md').read_text()
SCHEMA = json.loads((ROOT / 'contracts/setup-onboard.v1.schema.json').read_text())
SETUP_SCHEMA = json.loads((ROOT / 'contracts/setup.v1.schema.json').read_text())
IDENTITY = (ROOT / 'contracts/github-identity.v1.md').read_text()
CASES_PATH = HERE / 'fixtures/cases.json'
CASES = json.loads(CASES_PATH.read_text())
EXAMPLES, VARIANTS, VIEWS = CASES['examples'], CASES['variants'], CASES['setup_views']
POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001'
RECEIPT = 'receipt-skip-app-under-limit'
EVALUATED = {'$schema', '$defs', '$ref', 'title', 'description', 'type', 'const', 'enum',
             'minLength', 'maxLength', 'pattern', 'minimum', 'exclusiveMinimum', 'minItems',
             'maxItems', 'items', 'contains', 'required', 'properties', 'additionalProperties',
             'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then'}
PLANTED = ['ghs_' + 'S' * 36, 'github_pat_' + 'S' * 30, '-----BEGIN RSA PRIVATE KEY-----',
           'eyJ' + 'a' * 12 + '.' + 'b' * 12 + '.' + 'c' * 12, 'OPENWIZ_GITHUB_APP_KEY=' + 'c3ludGhldGlj']


def _at(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def apply(doc, variant):
    doc = copy.deepcopy(doc)
    for path, value in variant.get('set', []):
        _at(doc, path[:-1])[path[-1]] = copy.deepcopy(value)
    for path, value in variant.get('append', []):
        _at(doc, path).append(copy.deepcopy(value))
    for path in variant.get('delete', []):
        del _at(doc, path[:-1])[path[-1]]
    return doc


def document(name):
    if name in EXAMPLES:
        return copy.deepcopy(EXAMPLES[name]['document'])
    variant = VARIANTS[name]
    return apply(EXAMPLES[variant['base']]['document'], variant)


def live(doc):
    doc = copy.deepcopy(doc)
    doc.update(proof_class='live', synthetic_assumptions=[], private_record=POINTER)
    if doc['kind'] == 'first_merge_receipt':
        doc['verdict'] = 'pass'
        doc['secret_route_observed'] = doc['secret_route'] != 'not_used'
    return doc


def report(doc):
    r = check.check(doc)
    return {'problems': r.problems, 'failures': r.failures, 'unproven': r.unproven}


def every_code(r):
    return [c for key in ('problems', 'failures', 'unproven') for c in r[key]]


def keywords(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key in ('properties', '$defs'):
                for sub in value.values():
                    keywords(sub, found)
            elif key not in ('const', 'enum'):
                keywords(value, found)
    elif isinstance(node, list):
        for item in node:
            keywords(item, found)
    return found


def table_codes():
    section = CONTRACT.split('## Codes', 1)[1].split('\n## ', 1)[0]
    return {m.group(1): m.group(2) for m in re.finditer(r'^\| `([a-z_:<>]+)` \| (problem|failure|unproven) \|', section, re.M)}


def generic(code):
    head, _, rest = code.partition(':')
    return head if not rest else head + ':<' + ('kind>' if head in ('duplicate_effect', 'blind_retry', 'effect_uncertain', 'phase_effect_mismatch') else
                                               'kind>:<repository>' if head == 'duplicate_effect_row' else
                                               'step>' if head in ('fallback_step_missing', 'owner_step_uncounted') else
                                               'list>:<index>' if head == 'outside_clock' else
                                               'decision>' if head == 'decision_unsaved' else
                                               'which>' if head in ('stale_evidence', 'not_fresh') else 'x>')


class Fixtures(unittest.TestCase):
    def test_each_example_gives_exactly_its_codes(self):
        for name, example in EXAMPLES.items():
            with self.subTest(example=name):
                self.assertEqual(report(example['document']), example['expect'])

    def test_each_variant_gives_exactly_its_codes(self):
        for name, variant in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(report(document(name)), variant['expect'])

    def test_every_example_is_clean_once_live_in_memory(self):
        for name in EXAMPLES:
            with self.subTest(example=name):
                self.assertEqual(report(live(document(name))), {'problems': [], 'failures': [], 'unproven': []})

    def test_strict_json(self):
        text = json.dumps(EXAMPLES[RECEIPT]['document'])
        self.assertEqual(check.check_text(text).problems, [])
        self.assertEqual(check.check_text(text).unproven, ['not_live'])
        for bad in (text[:-1] + ', "kind": "init_request"}', text.replace('"count": {"known": 5}', '"count": {"known": 5.0}'),
                    '{"kind": NaN}', 'not json'):
            with self.subTest(bad=bad[-40:]):
                self.assertEqual(check.check_text(bad).problems, ['not_strict_json'])


    def test_patterns_end_at_the_end_of_the_string(self):
        for name, path in (('init-request-preview', ['repository']), ('identity-user-app', ['app', 'owner_account']),
                           ('init-request-apply', ['operation_id'])):
            with self.subTest(example=name):
                doc = document(name)
                _at(doc, path[:-1])[path[-1]] += '\n'
                self.assertEqual(report(doc)['problems'], ['schema'])


class Limits(unittest.TestCase):
    def receipt(self, **change):
        doc = live(document(RECEIPT))
        for key, value in change.items():
            doc[key] = value
        return doc

    def test_just_under_thirty_minutes_with_five_actions_passes(self):
        doc = self.receipt()
        self.assertEqual(doc['clock']['ended_at_ms']['known'] - doc['clock']['started_at_ms']['known'], 1799999)
        self.assertEqual(doc['actions']['count'], {'known': 5})
        self.assertEqual(report(doc), {'problems': [], 'failures': [], 'unproven': []})

    def test_exactly_thirty_minutes_fails(self):
        doc = self.receipt()
        doc['clock']['ended_at_ms'] = {'known': 1800000}
        doc['binding']['merge']['merged_at_ms'] = 1800000
        r = report(doc)
        self.assertIn('thirty_minutes_missed', r['failures'])
        self.assertIn('failure_not_reported', r['problems'])
        doc['verdict'] = 'fail'
        self.assertEqual(report(doc), {'problems': [], 'failures': ['thirty_minutes_missed'], 'unproven': []})

    def test_a_sixth_action_fails(self):
        doc = self.receipt()
        doc['actions']['log'].append(dict(doc['actions']['log'][0], at_ms=5500, kind='tap'))
        doc['actions']['count'] = {'known': 6}
        self.assertIn('actions_exceeded', report(doc)['failures'])

    def test_an_unknown_or_missing_count_never_passes(self):
        doc = self.receipt()
        doc['actions']['count'] = {'unknown': 'Not kept.'}
        r = report(doc)
        self.assertIn('action_count_unknown', r['unproven'])
        self.assertIn('unproven_pass', r['problems'])
        del doc['actions']['count']
        self.assertEqual(report(doc)['problems'], ['schema'])


class Credentials(unittest.TestCase):
    def test_planted_credentials_are_refused_wherever_they_appear(self):
        spots = {'identity-skip-app': ['personal_login', 'evidence', 0, 'detail'],
                 'secret-protected-paste': ['delivery', 'evidence', 0, 'detail'],
                 'init-private': ['report_line'],
                 RECEIPT: ['idea']}
        for name, path in spots.items():
            for secret in PLANTED:
                with self.subTest(example=name, shape=secret[:6]):
                    doc = document(name)
                    _at(doc, path[:-1])[path[-1]] = 'Synthetic ' + secret
                    self.assertIn('leaked_credential', report(doc)['problems'])

    def test_app_key_assignments_are_refused_with_any_horizontal_spacing(self):
        name, value = 'OPENWIZ_GITHUB_APP_KEY', 'c3ludGhldGlj'
        nonempty = [f'{name}={value}', f'{name} = {value}', f'{name} ={value}', f'{name}= {value}',
                    f'{name}   =   {value}', f'export {name} = {value}']
        empty = [f'{name}=', f'{name} =', f'{name} = ', f'{name}  =  ']
        for example, path in (('secret-protected-paste', ['delivery', 'evidence', 0, 'detail']),
                              (RECEIPT, ['idea'])):
            for text, refused in [(t, True) for t in nonempty] + [(t, False) for t in empty]:
                with self.subTest(example=example, text=text):
                    doc = document(example)
                    _at(doc, path[:-1])[path[-1]] = text
                    problems = check.check_text(json.dumps(doc)).problems
                    self.assertEqual(problems, ['leaked_credential'] if refused else [])

    def test_committed_contract_and_fixtures_hold_no_credential(self):
        for path in (CASES_PATH, ROOT / 'contracts/setup-onboard.v1.md',
                     ROOT / 'contracts/setup-onboard.v1.schema.json'):
            with self.subTest(path=path.name):
                self.assertEqual(check.credential_shapes(path.read_text()), [])

    def test_fixture_accounts_and_repositories_are_synthetic(self):
        text = CASES_PATH.read_text()
        for owner in re.findall(r'"([A-Za-z0-9-]{1,39})/[A-Za-z0-9_.-]+"', text):
            if owner not in ('github.com',):
                self.assertTrue(owner.lower().startswith('synthetic'), owner)
        self.assertNotIn('jparker2006', text)
        self.assertNotIn('openwizdev', text.replace('github.com/openwizdev/openwiz', ''))


class Schemas(unittest.TestCase):
    def test_schemas_use_only_evaluated_keywords(self):
        for name, schema in (('setup-onboard', SCHEMA), ('setup', SETUP_SCHEMA)):
            with self.subTest(schema=name):
                found = keywords(schema, set())
                self.assertEqual(found - EVALUATED, set())

    def test_setup_views_follow_the_expanded_setup_schema(self):
        for name, view in VIEWS.items():
            with self.subTest(view=name):
                errors = check.schema_errors(view['document'], SETUP_SCHEMA, SETUP_SCHEMA)
                self.assertEqual(not errors, view['valid'], errors)

    def test_setup_identity_and_brain_agree_with_this_contract(self):
        props = SETUP_SCHEMA['properties']
        selection = SCHEMA['$defs']['identity_selection']['properties']
        self.assertEqual(props['identity']['properties']['selected'], selection['selected'])
        self.assertEqual(props['identity']['properties']['app_choice'], selection['app_choice'])
        brain = SCHEMA['$defs']['brain']['properties']
        view = [s for s in props['brain']['oneOf'] if s.get('type') == 'object']
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]['properties']['location'], brain['location'])
        self.assertEqual(view[0]['properties']['folder'], brain['folder'])
        self.assertNotIn('identity', SETUP_SCHEMA['required'])
        self.assertNotIn('brain', SETUP_SCHEMA['required'])

    def test_secret_names_are_the_identity_pin(self):
        pins = re.findall(r'^```json\n(.*?)^```$', IDENTITY, re.M | re.S)
        self.assertEqual(len(pins), 1, 'github-identity.v1 keeps exactly one JSON pin')
        pin = json.loads(pins[0])
        secret = SCHEMA['$defs']['secret_capability']['properties']
        self.assertEqual(secret['secret']['properties']['name'], {'const': pin['secret']['name']})
        self.assertEqual(secret['secret']['properties']['holds'], {'const': pin['secret']['holds']})
        self.assertEqual(secret['app_id_variable'], {'const': pin['public_ids']['app_id']})
        self.assertEqual(pin['app']['visibility'], 'public', 'the factory App stays public')


HOSTS_PATH = HERE / 'fixtures/hosts.json'
HOSTS = json.loads(HOSTS_PATH.read_text())
NEW_THREAD = json.loads((ROOT / 'contracts/new-thread.v1.schema.json').read_text())


class Hosts(unittest.TestCase):
    def assert_cases(self, cases, schema, root):
        for name, case in cases.items():
            with self.subTest(case=name):
                errors = check.schema_errors(case['document'], schema, root)
                self.assertEqual(not errors, case['valid'], errors)

    def test_setup_reports_follow_the_host_rules(self):
        self.assert_cases(HOSTS['setup_reports'], SETUP_SCHEMA, SETUP_SCHEMA)

    def test_prepared_projects_need_cloudroom_ids_only_for_the_cloud_host(self):
        self.assertIn('prepared_project', SETUP_SCHEMA.get('$defs', {}))
        self.assert_cases(HOSTS['prepared_projects'], {'$ref': '#/$defs/prepared_project'}, SETUP_SCHEMA)

    def test_prepared_projects_refuse_what_the_store_refuses(self):
        store = _load('setup_store', ROOT / 'tools/install/setup/store.py')
        edges = [('operator', v) for v in ('', ' ', '\t', ' Synthetic', 'Synthetic ', 'Synthetic\n', 'Syn\x00thetic',
                                           'Syn\x85thetic', '\xa0Synthetic', 'Synthetic\u3000', 'S',
                                           'Synthetic  Operator', 'S' * 100, 'S' * 101, '\ufeffSynthetic',
                                           'Synthetic\ufeff', 'Syn\ufeffthetic')]
        edges += [('repository', 'synthetic-owner/' + v) for v in ('.', '..', '...', '.github', '..x', 'x..', '-', '_')]
        edges += [('service_issue', v) for v in (0, 1, 2 ** 53 - 1, 2 ** 53, 2 ** 63)]
        for base in ('cloud-nine-keys', 'local-without-cloudroom-ids'):
            for key, value in edges:
                with self.subTest(shape=base, key=key, value=value):
                    doc = dict(HOSTS['prepared_projects'][base]['document'], **{key: value})
                    try:
                        store.check_project(doc)
                        stored = True
                    except store.Refused:
                        stored = False
                    errors = check.schema_errors(doc, {'$ref': '#/$defs/prepared_project'}, SETUP_SCHEMA)
                    self.assertEqual(not errors, stored, errors)

    def test_operator_edges_follow_the_store_at_every_code_point(self):
        store = _load('setup_store', ROOT / 'tools/install/setup/store.py')
        shapes = SETUP_SCHEMA['$defs']['prepared_project']['oneOf']
        patterns = [shape['properties']['operator']['pattern'] for shape in shapes]
        self.assertEqual(len(patterns), 2)
        for pattern in patterns:
            self.assertIsNone(re.search(r'\\[sSdDwWbB]', pattern), 'engine-dependent class')
            edge = re.compile(pattern)
            wrong = [hex(ord(c)) for c in map(chr, range(sys.maxunicode + 1)) for v in (c + 'S', 'S' + c)
                     if (edge.fullmatch(v) is not None) != store.text(v)]
            self.assertEqual(wrong, [])

    def test_models_host_selects_the_offered_source(self):
        schema = SETUP_SCHEMA.get('$defs', {}).get('models_host_selection', {})
        for name, case in HOSTS['models_host_selection'].items():
            with self.subTest(case=name):
                options = HOSTS['offered_lists'][case['options']]['document']
                selection = dict(case['document'])
                if 'source' in options:
                    selection['source'] = options['source']
                errors = check.schema_errors(selection, schema, SETUP_SCHEMA)
                self.assertEqual(not errors, case['valid'], errors)

    def test_offered_lists_mark_only_the_local_source(self):
        self.assert_cases(HOSTS['offered_lists'], {'$ref': '#/$defs/options'}, NEW_THREAD)

    def test_the_local_source_offers_the_current_choices(self):
        found = {(h['provider'], m['model'], e)
                 for h in HOSTS['offered_lists']['local-claude-code-and-codex']['document']['harnesses']
                 for m in h['models'] for e in m['efforts']}
        self.assertEqual(found, {('claude-code', 'claude-opus-5-5', 'medium'), ('codex', 'gpt-6.2-sol', 'medium')})

    def test_successful_local_set_can_report_an_unlisted_model(self):
        doc = HOSTS['unlisted_local_set']
        options = HOSTS['offered_lists']['local-codex-only']['document']
        models = [m['model'] for h in options['harnesses'] if h['provider'] == doc['asked']['provider']
                  for m in h['models']]
        self.assertTrue(models)
        self.assertNotIn(doc['asked']['model'], models)
        self.assertIs(doc['listed'], False)
        schema = json.loads((ROOT / 'contracts/models.v1.schema.json').read_text())
        report_schema = {'$ref': '#/$defs/set_report'}
        self.assertEqual(check.schema_errors(doc, report_schema, schema), [])
        self.assertTrue(check.schema_errors(dict(doc, listed=True), report_schema, schema))

    def test_host_fixtures_hold_no_credential_and_only_synthetic_accounts(self):
        text = HOSTS_PATH.read_text()
        self.assertEqual(check.credential_shapes(text), [])
        for owner in re.findall(r'"([A-Za-z0-9-]{1,39})/[A-Za-z0-9_.-]+"', text):
            self.assertTrue(owner.startswith('synthetic'), owner)


class CodeTable(unittest.TestCase):
    def test_the_contract_table_is_the_checker_vocabulary(self):
        self.assertEqual(table_codes(), check.CODES)

    def test_every_emitted_code_is_in_the_table_and_every_code_is_exercised(self):
        table = table_codes()
        seen = set()
        cases = [document(n) for n in list(EXAMPLES) + list(VARIANTS)]
        for doc in cases:
            r = report(doc)
            for key, kind in (('problems', 'problem'), ('failures', 'failure'), ('unproven', 'unproven')):
                for code in r[key]:
                    self.assertEqual(table.get(generic(code)), kind, code)
                    seen.add(generic(code))
        seen |= {'not_strict_json', 'leaked_credential'}
        self.assertEqual(set(table) - seen, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
