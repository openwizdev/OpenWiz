#!/usr/bin/env python3
import copy
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parents[1] / 'context-engine.v1.md'
SCHEMA = CONTRACT.with_suffix('.schema.json')
VERSION = 'openwiz.context-engine.v1'
KEYWORDS = frozenset('''$schema $id $defs $ref title description oneOf anyOf not type const enum
    minLength pattern minItems uniqueItems items required properties propertyNames additionalProperties'''.split())
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}


def matches(value, rule, schema):
    if type(rule) is bool:
        return rule
    if set(rule) - KEYWORDS:
        raise AssertionError(f'unsupported fixture-validator keywords: {sorted(set(rule) - KEYWORDS)}')
    if '$ref' in rule:
        ref = rule['$ref']
        assert ref.startswith('#/$defs/')
        if not matches(value, schema['$defs'][ref.removeprefix('#/$defs/')], schema):
            return False
    if 'type' in rule and type(value) is not TYPES[rule['type']]:
        return False
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']):
        return False
    if 'enum' in rule and value not in rule['enum']:
        return False
    if 'oneOf' in rule and sum(matches(value, part, schema) for part in rule['oneOf']) != 1:
        return False
    if 'anyOf' in rule and not any(matches(value, part, schema) for part in rule['anyOf']):
        return False
    if 'not' in rule and matches(value, rule['not'], schema):
        return False
    if isinstance(value, str):
        return len(value) >= rule.get('minLength', 0) and re.search(rule.get('pattern', ''), value) is not None
    if isinstance(value, list):
        return (len(value) >= rule.get('minItems', 0)
                and (not rule.get('uniqueItems') or len({json.dumps(item, sort_keys=True) for item in value}) == len(value))
                and all(matches(item, rule.get('items', True), schema) for item in value))
    if isinstance(value, dict):
        props = rule.get('properties', {})
        extra = rule.get('additionalProperties', True)
        return (set(rule.get('required', ())) <= value.keys()
                and all(matches(key, rule.get('propertyNames', True), schema)
                        and matches(item, props.get(key, extra), schema) for key, item in value.items()))
    return True


class ContractFixtures(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), f'{SCHEMA.name} is missing')
        self.schema = json.loads(SCHEMA.read_text())
        self.good = json.loads((HERE / 'valid.json').read_text())

    def test_schema_reads_the_contract_examples_and_accepts_valid_records(self):
        # comment-ok: catches: a documented example or supported record that its schema refuses.
        self.assertEqual(self.schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(self.schema['$id'], 'https://openwiz.dev/contracts/context-engine.v1.schema.json')
        for name, record in self.good.items():
            with self.subTest(fixture=name):
                self.assertEqual(record['schema'], VERSION)
                self.assertTrue(matches(record, self.schema, self.schema))
        examples = [json.loads(block) for block in re.findall(r'(?ms)^~~~json\n(.*?)^~~~$', CONTRACT.read_text())]
        self.assertCountEqual(examples, list(self.good.values()))

    def test_schema_refuses_each_broken_record_for_a_documented_rule(self):
        # comment-ok: catches: a permissive schema that admits a broken privacy, layout or ledger record.
        cases = json.loads((HERE / 'broken.json').read_text())
        readme = (HERE / 'README.md').read_text()
        names = set()
        for case in cases:
            name, base, path = case['case'], case['valid'], case['at']
            with self.subTest(fixture=name):
                self.assertNotIn(name, names)
                names.add(name)
                self.assertIn(f'| {name} | \x60{base}\x60 |', readme)
                record = copy.deepcopy(self.good[base])
                parent = record
                for key in path[:-1]:
                    parent = parent[key]
                if 'value' in case:
                    parent[path[-1]] = case['value']
                else:
                    del parent[path[-1]]
                self.assertFalse(matches(record, self.schema, self.schema))
        self.assertEqual(set(re.findall(r'^\| ([a-z][\w-]+) \| \x60', readme, re.M)), names)

    def test_unredacted_secret_shapes_are_refused_and_markers_are_accepted(self):
        # comment-ok: catches: a known secret shape landing on disk or a kind marker being treated as a secret again.
        vectors = json.loads((HERE / 'redaction.json').read_text())
        kinds = {vector['kind'] for vector in vectors}
        self.assertEqual(kinds, {'token', 'key', 'password'})
        for vector in vectors:
            with self.subTest(vector=vector['name']):
                record = dict(self.good['transcript'], text=''.join(vector['before']))
                self.assertFalse(matches(record, self.schema, self.schema))
                record['text'] = vector['after']
                self.assertTrue(matches(record, self.schema, self.schema))


if __name__ == '__main__':
    unittest.main(verbosity=2)
