#!/usr/bin/env python3
import copy
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parents[1] / 'persona.v1.md'
SCHEMA = HERE.parents[1] / 'persona.v1.schema.json'
VERSION = 'openwiz.persona.v1'
RULES = ('persona', 'theme', 'style-only', 'facts', 'two-faces', 'originality')
KEYWORDS = frozenset('''$schema $id $defs $ref title description oneOf not type const enum
    minLength maxLength pattern minItems maxItems uniqueItems items required properties
    propertyNames additionalProperties minimum maximum'''.split())
FACTS = 'Fleet fixture-fleet: 3 of 4 tickets merged.\nTicket 4102 failed: 2 tests red.'
NEXT = 'openwiz fleet show fixture-fleet --ticket 4102'


def kind_ok(value, kind):
    if kind == 'number':
        return type(value) in (int, float)
    if kind == 'integer':
        return type(value) is int
    return type(value) is {'object': dict, 'array': list, 'string': str, 'boolean': bool}[kind]


def matches(value, rule, schema):
    if type(rule) is bool:
        return rule
    if set(rule) - KEYWORDS:
        raise AssertionError(f'unsupported fixture-validator keywords: {sorted(set(rule) - KEYWORDS)}')
    if '$ref' in rule and not matches(value, schema['$defs'][rule['$ref'].removeprefix('#/$defs/')], schema):
        return False
    if 'type' in rule and not kind_ok(value, rule['type']):
        return False
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']):
        return False
    if 'enum' in rule and value not in rule['enum']:
        return False
    if 'oneOf' in rule and sum(matches(value, part, schema) for part in rule['oneOf']) != 1:
        return False
    if 'not' in rule and matches(value, rule['not'], schema):
        return False
    if type(value) in (int, float):
        return rule.get('minimum', value) <= value <= rule.get('maximum', value)
    if isinstance(value, str):
        return (rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', len(value))
                and re.search(rule.get('pattern', ''), value) is not None)
    if isinstance(value, list):
        return (rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', len(value))
                and (not rule.get('uniqueItems') or len({json.dumps(v, sort_keys=True) for v in value}) == len(value))
                and all(matches(item, rule.get('items', True), schema) for item in value))
    if isinstance(value, dict):
        props = rule.get('properties', {})
        extra = rule.get('additionalProperties', True)
        return (set(rule.get('required', ())) <= value.keys()
                and all(matches(key, rule.get('propertyNames', True), schema)
                        and matches(item, props.get(key, extra), schema) for key, item in value.items()))
    return True


def render(template, facts, command):
    return re.sub(r'\{(facts|next)\}', lambda m: facts if m[1] == 'facts' else command, template)


def broken(good, case):
    record = copy.deepcopy(good[case['valid']])
    parent = record
    for key in case['at'][:-1]:
        parent = parent[key]
    if 'value' in case:
        parent[case['at'][-1]] = case['value']
    else:
        del parent[case['at'][-1]]
    return record


class PersonaFixtures(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), f'{SCHEMA.name} is missing')
        self.assertTrue(CONTRACT.is_file(), f'{CONTRACT.name} is missing')
        self.schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        self.good = json.loads((HERE / 'valid.json').read_text(encoding='utf-8'))
        self.cases = json.loads((HERE / 'broken.json').read_text(encoding='utf-8'))
        self.readme = (HERE / 'README.md').read_text(encoding='utf-8')

    def test_schema_accepts_every_valid_fixture_and_contract_example(self):
        self.assertEqual(self.schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(self.schema['$id'], 'https://openwiz.dev/contracts/persona.v1.schema.json')
        self.assertEqual(tuple(self.good), RULES)
        for name, record in self.good.items():
            with self.subTest(fixture=name):
                self.assertEqual(record['schema'], VERSION)
                self.assertTrue(record['id'].startswith('fixture-'))
                self.assertTrue(matches(record, self.schema, self.schema))
        examples = [json.loads(b) for b in re.findall(r'(?ms)^```json\n(.*?)^```$', CONTRACT.read_text(encoding='utf-8'))]
        self.assertCountEqual(examples, [self.good['persona'], self.good['theme']])

    def test_schema_refuses_every_broken_fixture_and_each_rule_has_one(self):
        names = set()
        for case in self.cases:
            with self.subTest(fixture=case['case']):
                self.assertNotIn(case['case'], names)
                names.add(case['case'])
                self.assertIn(f"| {case['case']} | `{case['valid']}` |", self.readme)
                self.assertFalse(matches(broken(self.good, case), self.schema, self.schema))
        self.assertEqual(set(re.findall(r'^\| ([a-z][\w-]+) \| `', self.readme, re.M)), names)
        self.assertEqual({case['valid'] for case in self.cases}, set(RULES))

    def test_a_persona_that_adds_rules_or_permissions_is_refused(self):
        for field in ('rules', 'permissions', 'tools', 'facts', 'safety', 'json_output'):
            with self.subTest(field=field):
                self.assertFalse(matches(dict(self.good['style-only'], **{field: 'x'}), self.schema, self.schema))

    def test_every_valid_persona_keeps_the_facts_block_and_next_command_byte_for_byte(self):
        for name, record in self.good.items():
            if record['kind'] != 'persona':
                continue
            for field in ('frame', 'error_style'):
                with self.subTest(persona=name, field=field):
                    lines = render(record[field], FACTS, NEXT).split('\n')
                    at = lines.index(FACTS.split('\n')[0])
                    self.assertEqual(lines[at:at + 2], FACTS.split('\n'))
                    self.assertEqual(lines.count(NEXT), 1)
                    self.assertGreater(lines.index(NEXT), at + 1)

    def test_the_contract_documents_the_room_field_for_the_immersive_room(self):
        text = CONTRACT.read_text(encoding='utf-8')
        self.assertRegex(text, r'`room`[^\n]*immersive room')
        for field in ('palette', 'lighting', 'mood'):
            self.assertIn(f'`{field}`', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
