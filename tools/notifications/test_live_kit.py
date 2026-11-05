#!/usr/bin/env python3
"""Offline result-validator interface and synthetic cases (#2231), and the
live kit's offline dry run with its cases (#2039). No live steps run here.
"""
import copy
import json
import importlib.util
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent



def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def non_integer(_):
        raise ValueError('non-integer JSON number')

    return json.loads(text, object_pairs_hook=pairs, parse_float=non_integer,
                      parse_constant=non_integer)


def validate_result(result_text, binding_text):
    """Validate an offline record, never execute or authorize its kit.

    BINDING is separately read by the kit owner from its approved kit and installed
    candidate. This checker cannot authenticate that provenance or the artifacts
    named by evidence digests. Independent review must inspect those records.
    Valid records may retain Unverified scope. No earlier-version gate is read.
    """
    result, binding = strict_json(result_text), strict_json(binding_text)
    schema = strict_json((HERE / 'live-kit-result.schema.json').read_text())
    # Reuse the repository's standard-library schema subset, not a new package.
    path = HERE.parent / 'skills-eval' / 'records.py'
    spec = importlib.util.spec_from_file_location('notification_schema_records', path)
    records = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(records)
    if (records.schema_errors(result, schema, schema) or
            records.schema_errors(binding, schema['$defs']['binding'], schema)):
        raise ValueError('result or binding shape')
    for field in ('candidate', 'kit_sha256', 'caps'):
        if result[field] != binding[field]:
            raise ValueError('external binding mismatch')
    for key, count in result['counts'].items():
        if count > binding['caps'][key]:
            raise ValueError('approved numerical cap exceeded')
    if binding['caps']['test_answers'] > 1 or binding['caps']['engine_restarts'] > 1:
        raise ValueError('kit answer or restart bound exceeded')

    gaps = set()
    for name, proof in result['proofs'].items():
        if proof['state'] == 'verified':
            if proof['candidate'] != binding['candidate']:
                raise ValueError('proof candidate mismatch')
        else:
            gaps.add(name + '_not_verified')
    for name in ('phone', 'native_mac'):
        observation = result[name]
        if observation['state'] == 'verified':
            if observation['candidate'] != binding['candidate']:
                raise ValueError('observation candidate mismatch')
            if result['proofs']['live_observation']['state'] != 'verified':
                raise ValueError('device observation needs live evidence')
        else:
            gaps.add(observation['gap'])
    if result['cleanup']['state'] != 'complete':
        gaps.add('cleanup_incomplete')
    service = result['service']
    service_verified = (service['cockpit_closed'] and service['dispatch'] == 'accepted'
                        and service['authenticated_bound_open'])
    observed_delivery = (service['dispatch'] != 'not_attempted'
                         or result['phone']['state'] == 'verified')
    if observed_delivery and not result['counts']['notification_submissions']:
        raise ValueError('delivery observation without a counted submission')
    if result['counts']['test_answers'] > result['counts']['cloudroom_sends']:
        raise ValueError('answer without a counted send')
    if not service_verified:
        gaps.add('service_not_verified')
    if set(result['gaps']) != gaps:
        raise ValueError('missing or inconsistent explicit gaps')
    verified = (service_verified and result['phone']['state'] == 'verified'
                and result['proofs']['live_observation']['state'] == 'verified'
                and result['proofs']['independent_review']['state'] == 'verified'
                and result['cleanup']['state'] == 'complete')
    if result['pa8'] == 'verified' and not verified:
        raise ValueError('PA8 real-phone evidence incomplete')
    return result['pa8']


KIT_PLAN_KEYS = ('schema', 'candidate', 'engine_host', 'origin', 'delivery_binding',
                 'installation', 'resources', 'phone', 'caps', 'bounds', 'forbidden_effects',
                 'privacy', 'stop', 'result_schema')
RESOURCES = ('decision_subject', 'incident_source', 'optional_category',
             'answer_thread', 'stock_project', 'stock_ticket', 'stock_label',
             'browser_context')
# Exact `owner/repo#number` references for the records the kit writes to.
RECORD = r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+#[1-9][0-9]*'
# Spec ceilings no kit revision can widen: one confirmed test answer, one engine
# restart, one send for it, no CloudRoom starts, no retries or forbidden effect.
CEILINGS = {'test_answers': 1, 'engine_restarts': 1, 'cloudroom_sends': 1,
            'cloudroom_starts': 0, 'retries': 0}


def validate_kit(plan_text, kit):
    """Check a private plan offline against KIT's own template; run nothing.

    Returns the review report with the binding #2231's --validate consumes.
    The kit's template is the single source of the approved caps and bounds.
    """
    import hashlib
    import re

    def require(condition):
        if not condition:
            raise ValueError('incomplete or out-of-scope live-kit plan')

    def known(value):
        require(type(value) is str and 0 < len(value) <= 256 and value.isascii())
        require(value == value.strip() and all(32 <= ord(c) < 127 for c in value))
        require(value.lower() not in {'unknown', 'unverified', 'todo', 'tbd', 'none'})
        require(not any(c in value for c in '<>'))

    def numbers(value, expected):
        require(type(value) is dict and set(value) == set(expected))
        require(all(type(value[k]) is int and value[k] == expected[k] for k in expected))

    plan = strict_json(plan_text)
    template = strict_json(kit.split('```live-kit-plan\n')[1].split('\n```')[0])
    for field in ('caps', 'bounds', 'forbidden_effects'):
        for key, ceiling in CEILINGS.items():
            if key in template[field]:
                require(template[field][key] <= ceiling)
        if field == 'forbidden_effects':
            require(set(template[field].values()) == {0})
    require(type(plan) is dict and tuple(sorted(plan)) == tuple(sorted(KIT_PLAN_KEYS)))
    for key in ('schema', 'privacy', 'stop', 'result_schema'):
        require(plan[key] == template[key])
    candidate = plan['candidate']
    require(type(candidate) is dict and set(candidate) == {'version', 'head', 'tree'})
    require(candidate['version'] == template['candidate']['version'])
    for key in ('head', 'tree'):
        require(type(candidate[key]) is str and re.fullmatch(r'[0-9a-f]{40}', candidate[key]))
    for key in ('engine_host', 'delivery_binding'):
        known(plan[key])
    known(plan['origin'])
    origin = re.fullmatch(r'https://[a-z0-9]+(?:[.-][a-z0-9]+)*(?::([1-9][0-9]{0,4}))?',
                          plan['origin'])
    require(origin is not None and int(origin.group(1) or 443) <= 65535)
    resources = plan['resources']
    require(type(resources) is dict and set(resources) == set(RESOURCES))
    for value in resources.values():
        known(value)
    for key in ('decision_subject', 'stock_ticket'):
        require(re.fullmatch(RECORD, resources[key]) is not None)
    # R6: preferences and the subscription are installation-wide, so only a
    # named, existing isolated test installation is admissible.
    installation = plan['installation']
    require(type(installation) is dict
            and set(installation) == {'kind', 'state_owner', 'port', 'provenance',
                                      'local_status', 'origin_route'})
    require(installation['kind'] == 'isolated-test')
    for key in ('state_owner', 'provenance', 'local_status', 'origin_route'):
        known(installation[key])
    require(type(installation['port']) is int and 1 <= installation['port'] <= 65535)
    phone = plan['phone']
    require(type(phone) is dict and set(phone) == {'availability', 'device', 'gap'})
    if phone['availability'] == 'available':
        known(phone['device'])
        require(phone['gap'] is None)
    else:
        require(phone['availability'] == 'unavailable' and phone['device'] is None)
        known(phone['gap'])
    for field in ('caps', 'bounds', 'forbidden_effects'):
        numbers(plan[field], template[field])
    canonical = json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {'status': 'offline_valid_for_review', 'live_authority': False,
            'phone_display': 'Unverified',
            'plan_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
            'binding': {'candidate': candidate,
                        'kit_sha256': hashlib.sha256(kit.encode()).hexdigest(),
                        'caps': plan['caps']}}


def synthetic_result():
    """Hand-worked result; all hashes and observations are synthetic."""
    candidate = {'version': '0.0.15', 'head': 'a' * 40, 'tree': 'b' * 40}
    proof = {'state': 'verified', 'candidate': candidate, 'evidence_sha256': 'c' * 64}
    caps = {'notification_submissions': 4, 'github_records': 2,
            'github_comments': 3, 'cloudroom_sends': 1, 'cloudroom_starts': 0,
            'test_answers': 1, 'engine_restarts': 1, 'cleanup_actions': 8,
            'elapsed_seconds': 300}
    result = {
        'schema': 'openwiz.notification-live-result.v1',
        'candidate': candidate, 'kit_sha256': 'd' * 64,
        'proofs': {
            'fixture_test': copy.deepcopy(proof),
            'live_observation': copy.deepcopy(proof),
            'independent_review': copy.deepcopy(proof)},
        'caps': caps, 'counts': dict(caps),
        'forbidden_effects': {'normal_preference_changes': 0, 'merges': 0,
            'tags': 0, 'purchases': 0, 'publications': 0, 'access_changes': 0,
            'blind_retries': 0},
        'service': {'cockpit_closed': True, 'dispatch': 'accepted',
                    'authenticated_bound_open': True},
        'phone': {'state': 'verified', 'evidence_class': 'live_observation',
            'client': 'actual_supported_phone', 'candidate': copy.deepcopy(candidate),
            'cockpit_closed': True, 'background_display': True, 'tap': True,
            'authenticated_bound_current_item': True, 'evidence_sha256': 'e' * 64},
        'native_mac': {'state': 'unverified', 'gap': 'native_mac_not_observed'},
        'cleanup': {'state': 'complete', 'test_resources_remaining': 0,
                    'test_choices_restored': True},
        'pa8': 'verified', 'gaps': ['native_mac_not_observed']}
    binding = {'candidate': copy.deepcopy(candidate), 'kit_sha256': 'd' * 64,
               'caps': copy.deepcopy(caps)}
    return result, binding


class ResultValidator(unittest.TestCase):
    def check_result(self, result, binding):
        return validate_result(json.dumps(result), json.dumps(binding))

    def test_result_integrity_positive_and_explicit_gaps(self):
        result, binding = synthetic_result()
        self.assertEqual(self.check_result(result, binding), 'verified')
        result['phone'] = {'state': 'unverified', 'client': 'emulated_chromium',
                           'gap': 'emulation_only'}
        result['pa8'] = 'unverified'
        result['gaps'].append('emulation_only')
        self.assertEqual(self.check_result(result, binding), 'unverified')

    def test_phone_pass_requires_actual_background_display_and_bound_tap(self):
        for key, value in (
            ('client', 'emulated_chromium'), ('client', 'transport_acceptance'),
            ('evidence_class', 'fixture_test'), ('evidence_class', 'independent_review'),
            ('cockpit_closed', False), ('background_display', False), ('tap', False),
            ('authenticated_bound_current_item', False), ('evidence_sha256', ''),
        ):
            result, binding = synthetic_result()
            result['phone'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check_result(result, binding)
        result, binding = synthetic_result()
        result['phone'] = {'state': 'unverified', 'client': 'none', 'gap': 'phone_not_observed'}
        result['gaps'].append('phone_not_observed')
        with self.assertRaises(ValueError):
            self.check_result(result, binding)

    def test_candidate_binding_at_every_evidence_boundary(self):
        for location in ('candidate', 'phone', 'native_mac', 'fixture_test',
                         'live_observation', 'independent_review'):
            for field, changed in (('version', '0.0.16'), ('head', 'f' * 40), ('tree', 'f' * 40)):
                result, binding = synthetic_result()
                if location == 'candidate': target = result['candidate']
                elif location in result['proofs']: target = result['proofs'][location]['candidate']
                else:
                    if location == 'native_mac':
                        result['native_mac'] = {'state': 'verified', 'client': 'native_macos',
                            'evidence_class': 'live_observation', 'candidate': copy.deepcopy(binding['candidate']),
                            'install': True, 'ls': True, 'show': True, 'evidence_sha256': 'e' * 64}
                        result['gaps'] = []
                    target = result[location]['candidate']
                target[field] = changed
                with self.subTest(location=location, field=field), self.assertRaises(ValueError):
                    self.check_result(result, binding)
        result, binding = synthetic_result()
        result['kit_sha256'] = 'f' * 64
        with self.assertRaises(ValueError): self.check_result(result, binding)

    def test_external_caps_and_strict_numbers(self):
        for key in synthetic_result()[1]['caps']:
            for fault in ('over', 'inflate', 'bool', 'float', 'negative', 'missing'):
                result, binding = synthetic_result()
                if fault == 'over': result['counts'][key] += 1
                elif fault == 'inflate':
                    result['caps'][key] += 1
                    result['counts'][key] += 1
                elif fault == 'missing': del result['counts'][key]
                else: result['counts'][key] = {'bool': True, 'float': 0.0, 'negative': -1}[fault]
                with self.subTest(key=key, fault=fault), self.assertRaises(ValueError):
                    self.check_result(result, binding)
        for key in synthetic_result()[0]['forbidden_effects']:
            result, binding = synthetic_result()
            result['forbidden_effects'][key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check_result(result, binding)

    def test_proof_classes_cleanup_and_mac_do_not_launder_gaps(self):
        for proof in ('fixture_test', 'live_observation', 'independent_review'):
            result, binding = synthetic_result()
            result['proofs'][proof] = {'state': 'unverified', 'gap': 'not_observed'}
            result['gaps'].append(proof + '_not_verified')
            if proof == 'fixture_test':
                # A fixture is not a prerequisite to the real-phone observation.
                self.assertEqual(self.check_result(result, binding), 'verified')
            else:
                with self.assertRaises(ValueError): self.check_result(result, binding)
                result['pa8'] = 'unverified'
                if proof == 'live_observation':
                    result['phone'] = {'state': 'unverified', 'client': 'none',
                                       'gap': 'phone_not_observed'}
                    result['gaps'].append('phone_not_observed')
                self.assertEqual(self.check_result(result, binding), 'unverified')
        for key, value in (('test_resources_remaining', 1), ('test_choices_restored', False)):
            result, binding = synthetic_result()
            result['cleanup'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check_result(result, binding)
        result, binding = synthetic_result()
        result['native_mac'] = {'state': 'verified', 'client': 'emulated_chromium',
            'evidence_class': 'live_observation', 'candidate': binding['candidate'],
            'install': True, 'ls': True, 'show': True, 'evidence_sha256': 'e' * 64}
        with self.assertRaises(ValueError): self.check_result(result, binding)
        result, binding = synthetic_result()
        result['gaps'] = []
        with self.assertRaises(ValueError): self.check_result(result, binding)

    def test_const_types_and_zero_submission_cannot_prove_display(self):
        for field in ('cockpit_closed', 'background_display', 'tap',
                      'authenticated_bound_current_item'):
            result, binding = synthetic_result()
            result['phone'][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check_result(result, binding)
        result, binding = synthetic_result()
        result['counts']['notification_submissions'] = 0
        with self.assertRaises(ValueError): self.check_result(result, binding)
        result, binding = synthetic_result()
        for candidate in (result['candidate'], binding['candidate'],
                          result['phone']['candidate'],
                          *(p['candidate'] for p in result['proofs'].values())):
            candidate['version'] = '0.0.15\n'
        with self.assertRaises(ValueError): self.check_result(result, binding)

    def test_honest_incomplete_records_and_native_mac_observation(self):
        result, binding = synthetic_result()
        result['native_mac'] = {'state': 'verified', 'client': 'native_macos',
            'evidence_class': 'live_observation', 'candidate': copy.deepcopy(binding['candidate']),
            'install': True, 'ls': True, 'show': True, 'evidence_sha256': 'e' * 64}
        result['gaps'] = []
        self.assertEqual(self.check_result(result, binding), 'verified')
        result, binding = synthetic_result()
        result['cleanup'] = {'state': 'incomplete', 'test_resources_remaining': 1,
            'test_choices_restored': False, 'gap': 'cleanup_incomplete'}
        result['gaps'].append('cleanup_incomplete')
        with self.assertRaises(ValueError): self.check_result(result, binding)
        result['pa8'] = 'unverified'
        self.assertEqual(self.check_result(result, binding), 'unverified')
        for dispatch in ('not_attempted', 'pending', 'accepted', 'failed', 'uncertain'):
            result, binding = synthetic_result()
            result['phone'] = {'state': 'unverified', 'client': 'none', 'gap': 'dispatch_only'}
            result['service']['dispatch'] = dispatch
            result['pa8'] = 'unverified'
            result['gaps'].append('dispatch_only')
            if dispatch != 'accepted': result['gaps'].append('service_not_verified')
            with self.subTest(dispatch=dispatch):
                self.assertEqual(self.check_result(result, binding), 'unverified')

    def test_all_record_objects_reject_missing_and_extra_keys(self):
        baseline, binding = synthetic_result()
        def objects(value, path=()):
            if isinstance(value, dict):
                yield path, value
                for key, child in value.items():
                    yield from objects(child, path + (key,))
        for path, value in objects(baseline):
            for field in (*value, 'unrecognized_private_content'):
                result = copy.deepcopy(baseline)
                target = result
                for key in path: target = target[key]
                if field in value: del target[field]
                else: target[field] = 'synthetic private text'
                with self.subTest(path=path, field=field), self.assertRaises(ValueError):
                    self.check_result(result, binding)
        for path, value in objects(binding):
            for field in (*value, 'unrecognized'):
                altered = copy.deepcopy(binding)
                target = altered
                for key in path: target = target[key]
                if field in value: del target[field]
                else: target[field] = 0
                with self.subTest(binding=path, field=field), self.assertRaises(ValueError):
                    self.check_result(baseline, altered)

    def test_strict_wire_and_sanitized_cli(self):
        result, binding = synthetic_result()
        text = json.dumps(result)
        for bad in (text.replace('"version": "0.0.15"', '"version": "0.0.16", "version": "0.0.15"', 1),
                    text.replace('"notification_submissions": 4', '"notification_submissions": NaN', 1),
                    '[]', text[:-1] + ', "private": "synthetic secret"}'):
            with self.subTest(bad=bad[:30]), self.assertRaises(ValueError):
                validate_result(bad, json.dumps(binding))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'result.json').write_text(text)
            (path / 'binding.json').write_text(json.dumps(binding))
            args = [sys.executable, '-I', str(HERE / 'test_live_kit.py'), '--validate',
                    str(path / 'result.json'), '--binding', str(path / 'binding.json')]
            passed = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual((passed.returncode, passed.stdout.strip()),
                             (0, 'valid result record; PA8=verified'), passed.stderr)
            (path / 'result.json').write_text('{"synthetic secret": 0}')
            failed = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual((failed.returncode, failed.stderr.strip()), (1, 'invalid result record'))
            self.assertNotIn('synthetic secret', failed.stdout + failed.stderr)


# Kit dry-run cases (#2039). Synthetic plans only; nothing is contacted or run.
def kit_plan():
    """A completed synthetic plan; these hosts and resources do not exist."""
    return {
        'schema': 'openwiz.notification-live-kit-plan.v1',
        'candidate': {'version': '0.0.15', 'head': 'a' * 40, 'tree': 'b' * 40},
        'engine_host': 'synthetic-engine',
        'origin': 'https://cockpit.example.invalid',
        'delivery_binding': 'synthetic-binding-record',
        'installation': {'kind': 'isolated-test', 'state_owner': 'synthetic-test-state',
                         'port': 7399, 'provenance': 'synthetic-install-record',
                         'local_status': 'synthetic-status-record',
                         'origin_route': 'synthetic-route-record'},
        'resources': {
            'decision_subject': 'synthetic/test-repo#1', 'incident_source': 'synthetic-health',
            'optional_category': 'merge', 'answer_thread': 'synthetic-answer-thread',
            'stock_project': 'synthetic-stock', 'stock_ticket': 'synthetic/test-repo#2',
            'stock_label': 'ready-for-agent', 'browser_context': 'synthetic-tab'},
        'phone': {'availability': 'available', 'device': 'synthetic-phone', 'gap': None},
        'caps': {'notification_submissions': 4, 'github_records': 1, 'github_comments': 4,
                 'cloudroom_sends': 1, 'cloudroom_starts': 0, 'test_answers': 1,
                 'engine_restarts': 1, 'cleanup_actions': 6, 'elapsed_seconds': 1800},
        'bounds': {'api_reads': 40, 'request_s': 10, 'response_bytes': 65536, 'retries': 0},
        'forbidden_effects': {'normal_preference_changes': 0, 'merges': 0, 'tags': 0,
            'purchases': 0, 'publications': 0, 'access_changes': 0, 'blind_retries': 0},
        'privacy': 'owner-only-sanitized',
        'stop': 'first-refusal-no-retry',
        'result_schema': 'openwiz.notification-live-result.v1'}


def kit_text():
    return (HERE / 'live-kit.md').read_text()


class KitDryRun(unittest.TestCase):
    """PA8 kit integrity: an incomplete, widened or unbound plan never reaches
    Jake's OK as a bounded kit, and the binding it emits is the one #2231 checks."""

    def check(self, plan, kit=None):
        return validate_kit(json.dumps(plan), kit_text() if kit is None else kit)

    def test_complete_plan_emits_the_binding_the_result_validator_accepts(self):
        import hashlib
        import socket
        from unittest.mock import patch
        with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('write')):
            report = self.check(kit_plan())
        self.assertEqual((report['status'], report['live_authority'], report['phone_display']),
                         ('offline_valid_for_review', False, 'Unverified'))
        self.assertRegex(report['plan_sha256'], r'^[0-9a-f]{64}$')
        binding = report['binding']
        self.assertEqual(binding['kit_sha256'],
                         hashlib.sha256((HERE / 'live-kit.md').read_bytes()).hexdigest())
        self.assertEqual(binding['candidate'], kit_plan()['candidate'])
        self.assertEqual(binding['caps'], kit_plan()['caps'])
        # A run inside these caps validates under #2231; one over them does not.
        result, _ = synthetic_result()
        result.update(candidate=copy.deepcopy(binding['candidate']),
                      kit_sha256=binding['kit_sha256'], caps=copy.deepcopy(binding['caps']),
                      counts=copy.deepcopy(binding['caps']))
        for record in (result['phone'], *result['proofs'].values()):
            record['candidate'] = copy.deepcopy(binding['candidate'])
        self.assertEqual(validate_result(json.dumps(result), json.dumps(binding)), 'verified')
        result['counts']['notification_submissions'] += 1
        with self.assertRaises(ValueError):
            validate_result(json.dumps(result), json.dumps(binding))

    def test_shipped_template_refuses_until_private_values_are_filled(self):
        raw = kit_text().split('```live-kit-plan\n')[1].split('\n```')[0]
        with self.assertRaises(ValueError):
            validate_kit(raw, kit_text())

    def test_missing_extra_placeholder_and_mistyped_values_refuse(self):
        cases = []
        for key in kit_plan():
            plan = kit_plan()
            del plan[key]
            cases.append(plan)
        plan = kit_plan()
        plan['command'] = ['room-cli', 'thread', 'spawn']
        cases.append(plan)
        for key in ('engine_host', 'origin', 'delivery_binding'):
            for bad in (None, '', 'unknown', 'TBD', '<fill-me>', True, 'x\n'):
                plan = kit_plan()
                plan[key] = bad
                cases.append(plan)
        for key in kit_plan()['resources']:
            for bad in (None, '', 'todo'):
                plan = kit_plan()
                plan['resources'][key] = bad
                cases.append(plan)
            plan = kit_plan()
            del plan['resources'][key]
            cases.append(plan)
        for key, bad in (('head', 'A' * 40), ('head', None), ('tree', 'b' * 39),
                         ('version', '0.0.16')):
            plan = kit_plan()
            plan['candidate'][key] = bad
            cases.append(plan)
        for key, bad in (('schema', 'openwiz.notification-live-kit-plan.v2'),
                         ('privacy', 'public-logs'), ('stop', 'retry'),
                         ('result_schema', 'other')):
            plan = kit_plan()
            plan[key] = bad
            cases.append(plan)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self.check(plan)
        for bad in ('[]', '{"schema": 1, "schema": 2}',
                    json.dumps(kit_plan()).replace('"retries": 0', '"retries": 0.0')):
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                validate_kit(bad, kit_text())

    def test_caps_bounds_and_effects_are_exactly_the_kit_declared_values(self):
        for field in ('caps', 'bounds', 'forbidden_effects'):
            for key in kit_plan()[field]:
                for fault in ('more', 'less', 'bool', 'missing'):
                    plan = kit_plan()
                    value = plan[field][key]
                    if fault == 'more': plan[field][key] = value + 1
                    elif fault == 'less':
                        if value == 0: continue
                        plan[field][key] = value - 1
                    elif fault == 'bool': plan[field][key] = bool(value)
                    else: del plan[field][key]
                    with self.subTest(field=field, key=key, fault=fault), \
                         self.assertRaises(ValueError):
                        self.check(plan)
            plan = kit_plan()
            plan[field]['extra'] = 0
            with self.subTest(field=field, fault='extra'), self.assertRaises(ValueError):
                self.check(plan)

    def test_a_kit_declaring_wider_effects_refuses_even_when_the_plan_matches(self):
        # The spec allows at most one confirmed test answer and one engine
        # restart, no CloudRoom starts (no fleet) and no forbidden effect.
        for key, value in (('test_answers', 2), ('engine_restarts', 2),
                           ('cloudroom_starts', 1), ('cloudroom_sends', 2),
                           ('retries', 1), ('merges', 1), ('purchases', 1)):
            kit = kit_text().replace('"%s": %d' % (key, kit_plan_value(key)),
                                     '"%s": %d' % (key, value), 1)
            self.assertNotEqual(kit, kit_text(), key)
            plan = kit_plan()
            for field in ('caps', 'bounds', 'forbidden_effects'):
                if key in plan[field]: plan[field][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(plan, kit)

    def test_origin_is_one_exact_authenticated_https_origin(self):
        for origin in ('https://cockpit.example.invalid:8443', 'https://a.example.invalid'):
            plan = kit_plan()
            plan['origin'] = origin
            self.assertEqual(self.check(plan)['status'], 'offline_valid_for_review')
        for origin in ('http://cockpit.example.invalid', 'http://127.0.0.1:7370',
                       'https://user:secret' + '@cockpit.example.invalid',
                       'https://cockpit.example.invalid/', 'https://cockpit.example.invalid?x',
                       'https://cockpit.example.invalid#x', 'https://COCKPIT.example.invalid',
                       'https://cockpit.example.invalid:0', 'https://cockpit.example.invalid:65536',
                       'https://cockpit.example.invalid\n--insecure', 'https://'):
            plan = kit_plan()
            plan['origin'] = origin
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.check(plan)

    def test_missing_phone_is_a_named_gap_and_never_a_pass(self):
        plan = kit_plan()
        plan['phone'] = {'availability': 'unavailable', 'device': None,
                         'gap': 'No supported phone available'}
        self.assertEqual(self.check(plan)['phone_display'], 'Unverified')
        for phone in ({'availability': 'unknown', 'device': None, 'gap': None},
                      {'availability': 'available', 'device': None, 'gap': None},
                      {'availability': 'available', 'device': 'synthetic', 'gap': 'x'},
                      {'availability': 'unavailable', 'device': 'synthetic', 'gap': 'x'},
                      {'availability': 'unavailable', 'device': None, 'gap': None},
                      {'availability': 'emulated', 'device': 'chromium', 'gap': None}):
            plan = kit_plan()
            plan['phone'] = phone
            with self.subTest(phone=phone), self.assertRaises(ValueError):
                self.check(plan)

    def test_every_kit_byte_and_plan_byte_is_bound(self):
        report = self.check(kit_plan())
        edited = kit_text().replace('Run each step once', 'Run each step twice', 1)
        self.assertNotEqual(edited, kit_text())
        changed = self.check(kit_plan(), edited)
        self.assertNotEqual(changed['binding']['kit_sha256'], report['binding']['kit_sha256'])
        plan = kit_plan()
        plan['resources']['answer_thread'] = 'synthetic-other-thread'
        self.assertNotEqual(self.check(plan)['plan_sha256'], report['plan_sha256'])

    def test_the_kit_runs_only_its_offline_commands(self):
        # Steps after the OK are prose for T8; the only runnable block is offline.
        blocks = [b.split('\n```')[0] for b in kit_text().split('```sh\n')[1:]]
        self.assertEqual(blocks, [
            'python3 -I tools/notifications/test_live_kit.py\n'
            'python3 -I tools/notifications/test_live_kit.py --check-kit '
            '/private/run/live-kit-plan.json'])

    def test_plan_must_bind_an_existing_isolated_test_installation(self):
        # R6: the kit's preference and subscription writes are installation-
        # wide, so only a named isolated test installation is admissible.
        report = self.check(kit_plan())
        cases = []
        for kind in (None, '', 'normal', 'shared', 'unknown', 'isolated', 'isolated-test ', True):
            plan = kit_plan()
            plan['installation']['kind'] = kind
            cases.append(plan)
        for key in ('kind', 'state_owner', 'port', 'provenance', 'local_status', 'origin_route'):
            plan = kit_plan()
            del plan['installation'][key]
            cases.append(plan)
        for key in ('state_owner', 'provenance', 'local_status', 'origin_route'):
            for bad in (None, '', 'unknown', '<fill-me>'):
                plan = kit_plan()
                plan['installation'][key] = bad
                cases.append(plan)
        for port in (None, 0, 65536, -1, True, '7399', 7399.0):
            plan = kit_plan()
            plan['installation']['port'] = port
            cases.append(plan)
        plan = kit_plan()
        plan['installation']['shared_with'] = 'normal'
        cases.append(plan)
        plan = kit_plan()
        del plan['installation']
        cases.append(plan)
        for plan in cases:
            with self.subTest(installation=plan.get('installation')), self.assertRaises(ValueError):
                self.check(plan)
        plan = kit_plan()
        plan['installation']['state_owner'] = 'synthetic-other-state'
        self.assertNotEqual(self.check(plan)['plan_sha256'], report['plan_sha256'])

    def test_the_stock_write_and_decision_subject_name_exact_records(self):
        # R7: step 13 and cleanup change one label on one ticket; the plan must
        # name both exactly, and the digest binds them.
        report = self.check(kit_plan())
        for key, bad in (('stock_ticket', 'synthetic-stock'), ('stock_ticket', 'synthetic/test-repo'),
                         ('stock_ticket', 'synthetic/test-repo#0'),
                         ('stock_ticket', 'synthetic/test-repo#02'),
                         ('stock_ticket', 'synthetic/test-repo#2 '), ('stock_ticket', '/repo#2'),
                         ('stock_ticket', 'a/b/c#2'), ('stock_ticket', None),
                         ('decision_subject', 'synthetic-subject'), ('stock_label', ''),
                         ('stock_label', 'TBD'), ('stock_label', None)):
            plan = kit_plan()
            plan['resources'][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                self.check(plan)
        for key, other in (('stock_ticket', 'synthetic/test-repo#3'), ('stock_label', 'other-label')):
            plan = kit_plan()
            plan['resources'][key] = other
            self.assertNotEqual(self.check(plan)['plan_sha256'], report['plan_sha256'])

    def test_step_one_verifies_the_installation_through_its_bound_evidence(self):
        # R6 (re-check): health and notification status carry no state owner
        # or port. Step 1 must check the existing chain the plan binds: install
        # provenance, the root-scoped local service status, and origin routing.
        first = self.steps()[0].split('|')[2]
        for field in ('provenance', 'local_status', 'origin_route'):
            self.assertIn('`%s`' % field, first)
        self.assertIn('`openwiz-service status --json`', first)
        prerequisites = kit_text().split('## Prerequisites')[1].split('\n## ')[0]
        self.assertNotIn('status must report', prerequisites)

    def steps(self):
        section = kit_text().split('## Steps after the OK')[1].split('\n## ')[0]
        return [row for row in section.splitlines() if re.match(r'^\| [0-9]+ \|', row)]

    def test_phone_tap_is_observed_before_its_request_changes(self):
        # R4: the phone's current-item tap is only possible while the alerted
        # request is still current, before supersession or resolution.
        rows = self.steps()
        self.assertEqual([int(r.split('|')[1]) for r in rows], list(range(1, len(rows) + 1)))
        phone = [i for i, r in enumerate(rows) if r.split('|')[2].strip().startswith('Phone')]
        changed = [i for i, r in enumerate(rows) if '`superseded`' in r.split('|')[2]]
        resolved = [i for i, r in enumerate(rows) if '`resolved`' in r.split('|')[2]]
        self.assertEqual((len(phone), len(changed), len(resolved)), (1, 1, 1))
        self.assertLess(phone[0], changed[0])
        self.assertLess(phone[0], resolved[0])
        self.assertIn('current decision card', rows[phone[0]].split('|')[3])

    def test_cleanup_lists_exactly_its_capped_actions(self):
        # R3: every cleanup write is counted, and the preference restore is a
        # fresh forward write, never a rollback of the generation.
        section = kit_text().split('## Cleanup')[1].split('\n## ')[0]
        actions = re.findall(r'^[0-9]+\. (.*(?:\n   .*)*)', section, re.M)
        template = strict_json(kit_text().split('```live-kit-plan\n')[1].split('\n```')[0])
        self.assertEqual(len(actions), template['caps']['cleanup_actions'])
        restore = [a for a in actions if '`categories`' in a]
        self.assertEqual(len(restore), 1)
        self.assertIn('fresh', restore[0])
        self.assertIn('plus one', restore[0])
        self.assertIn('incomplete', section)
        # R3 (re-check): the baseline is what this run's own last successful
        # preference write returned, never a later read that may hold another
        # actor's change; a differing current state refuses the restore.
        self.assertIn("last successful preference write returned", restore[0])
        self.assertNotIn('last read back', section)
        # R7 (re-check): every cleanup action undoes only an effect this run
        # confirmed; skipped or uncertain effects get no cleanup write.
        for action in actions:
            self.assertTrue(action.startswith('If this run'), action)
        self.assertIn('uncertain', section)

    def test_check_kit_cli_reports_binding_and_refuses_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            path.write_text(json.dumps(kit_plan()))
            args = [sys.executable, '-I', str(HERE / 'test_live_kit.py'), '--check-kit', str(path)]
            passed = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertEqual(json.loads(passed.stdout), self.check(kit_plan()))
            path.write_text('{"engine_host": "synthetic-private-marker"}')
            failed = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(json.loads(failed.stdout), {'status': 'refused', 'live_authority': False})
            self.assertNotIn('synthetic-private-marker', failed.stdout + failed.stderr)


def kit_plan_value(key):
    plan = kit_plan()
    for field in ('caps', 'bounds', 'forbidden_effects'):
        if key in plan[field]:
            return plan[field][key]
    raise KeyError(key)


if __name__ == '__main__':
    if '--check-kit' in sys.argv:
        import argparse
        parser = argparse.ArgumentParser(description='Offline kit dry run; no live actions.')
        parser.add_argument('--check-kit', type=Path, required=True, metavar='PLAN')
        args = parser.parse_args()
        try:
            report = validate_kit(args.check_kit.read_text(), (HERE / 'live-kit.md').read_text())
        except (ValueError, OSError, UnicodeError, RecursionError, KeyError, IndexError,
                TypeError, AttributeError):
            print(json.dumps({'status': 'refused', 'live_authority': False}))
            sys.exit(2)
        print(json.dumps(report, sort_keys=True))
    elif '--validate' in sys.argv:
        import argparse
        parser = argparse.ArgumentParser(description='Offline result integrity; no live actions.')
        parser.add_argument('--validate', type=Path, required=True, metavar='RESULT')
        parser.add_argument('--binding', type=Path, required=True,
                            help='separately read candidate/kit digest/caps JSON')
        args = parser.parse_args()
        try:
            state = validate_result(args.validate.read_text(), args.binding.read_text())
        except (ValueError, OSError, UnicodeError, RecursionError):
            print('invalid result record', file=sys.stderr)
            sys.exit(1)
        print('valid result record; PA8=' + state)
    else:
        unittest.main()
