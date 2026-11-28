#!/usr/bin/env python3
import copy
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parents[1] / 'room.v1.md'
SCHEMA = HERE.parents[1] / 'room.v1.schema.json'
VERSION = 'openwiz.room.v1'
KEYWORDS = frozenset('''$schema $id $defs $ref title description oneOf anyOf allOf not if then else
    type const enum minLength pattern minimum maximum exclusiveMaximum minItems maxItems uniqueItems
    items contains required properties additionalProperties'''.split())
TYPES = {'object': (dict,), 'array': (list,), 'string': (str,), 'boolean': (bool,), 'null': (type(None),),
         'integer': (int,), 'number': (int, float)}
NEEDS_OWNER = {'spec-to-approve', 'pr-ready-to-merge', 'release', 'key-needed', 'setting-proposal',
               'decision-request', 'grant-request'}
FIXED_COVERS = {'budget.figures', 'budget.draw-calls', 'budget.triangles', 'budget.fps-floor', 'budget.fallback',
                'access.text', 'access.reduced-motion', 'public.no-names', 'public.no-ids', 'public.no-controls',
                'unavailable.never-empty'}
LIKENESS = re.compile(r'\b(?:' + '|'.join('''jarvis friday ultron stark marvel avengers star\\W?wars r2-d2 c-3po
    hal\\W?9000 skynet terminator tron star\\W?trek holodeck cortana siri alexa wall-e baymax pixar disney
    matrix halo blade\\W?runner replicant alfred batman jeeves bender data\\W?soong claude codex openai
    anthropic gemini chatgpt gpt copilot'''.split()) + r')\b', re.I)
PRIVATE = re.compile(
    r'/(?:Users|home)/|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.|\bgh[pousr]_[A-Za-z0-9]|\bsk-[A-Za-z0-9]')


def pattern_holds(pattern, value):
    if pattern.endswith('$') and not pattern.endswith('\\$'):
        pattern = pattern[:-1] + r'\Z'
    return re.search(pattern, value) is not None


def matches(value, rule, schema):
    if type(rule) is bool:
        return rule
    if set(rule) - KEYWORDS:
        raise AssertionError(f'unsupported fixture-validator keywords: {sorted(set(rule) - KEYWORDS)}')
    if '$ref' in rule:
        ref = rule['$ref']
        assert ref.startswith('#/$defs/'), ref
        if not matches(value, schema['$defs'][ref.removeprefix('#/$defs/')], schema):
            return False
    if 'type' in rule:
        kinds = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        if not any(isinstance(value, TYPES[kind]) and (kind in ('boolean', 'null') or type(value) is not bool)
                   for kind in kinds):
            return False
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']):
        return False
    if 'enum' in rule and not any(type(value) is type(item) and value == item for item in rule['enum']):
        return False
    if 'allOf' in rule and not all(matches(value, part, schema) for part in rule['allOf']):
        return False
    if 'oneOf' in rule and sum(matches(value, part, schema) for part in rule['oneOf']) != 1:
        return False
    if 'anyOf' in rule and not any(matches(value, part, schema) for part in rule['anyOf']):
        return False
    if 'not' in rule and matches(value, rule['not'], schema):
        return False
    if 'if' in rule:
        branch = rule.get('then', True) if matches(value, rule['if'], schema) else rule.get('else', True)
        if not matches(value, branch, schema):
            return False
    if isinstance(value, str):
        return len(value) >= rule.get('minLength', 0) and pattern_holds(rule.get('pattern', ''), value)
    if isinstance(value, (int, float)) and type(value) is not bool:
        return (value >= rule.get('minimum', value) and value <= rule.get('maximum', value)
                and ('exclusiveMaximum' not in rule or value < rule['exclusiveMaximum']))
    if isinstance(value, list):
        return (rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', len(value))
                and (not rule.get('uniqueItems') or len({json.dumps(item, sort_keys=True) for item in value}) == len(value))
                and all(matches(item, rule.get('items', True), schema) for item in value)
                and ('contains' not in rule or any(matches(item, rule['contains'], schema) for item in value)))
    if isinstance(value, dict):
        props = rule.get('properties', {})
        extra = rule.get('additionalProperties', True)
        return (set(rule.get('required', ())) <= value.keys()
                and all(matches(item, props.get(key, extra), schema) for key, item in value.items()))
    return True


def mutate(record, case):
    record = copy.deepcopy(record)
    parent = record
    for key in case['at'][:-1]:
        parent = parent[key]
    if 'value' in case:
        parent[case['at'][-1]] = case['value']
    else:
        del parent[case['at'][-1]]
    return record


def reader_rules(scene):
    found = []
    families = [station['family'] for station in scene['stations'] or []]
    if len(set(families)) != len(families):
        found.append('a family has two stations')
    names = [figure['name'] for figure in scene['figures'] or []]
    if len(set(names)) != len(names):
        found.append('two figures share a name')
    for figure in scene['figures'] or []:
        if figure['station'] not in families:
            found.append(f'{figure["name"]} stands at no station')
    lanes = [(pr['repository'], pr['number']) for lane in (scene['pipeline'] or {}).values() for pr in lane]
    if len(set(lanes)) != len(lanes):
        found.append('a pull request sits in two lanes')
    sources = [entry['source'] for entry in scene['unavailable']]
    if len(set(sources)) != len(sources):
        found.append('a source is listed twice')
    return found


class RoomContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), f'{SCHEMA.name} is missing')
        self.assertTrue(CONTRACT.is_file(), f'{CONTRACT.name} is missing')
        self.schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        self.contract = CONTRACT.read_text(encoding='utf-8')
        self.good = json.loads((HERE / 'valid.json').read_text(encoding='utf-8'))
        self.cases = json.loads((HERE / 'broken.json').read_text(encoding='utf-8'))
        self.readme = (HERE / 'README.md').read_text(encoding='utf-8')
        blocks = re.findall(r'(?ms)^```json\n(.*?)^```$', self.contract)
        self.assertEqual(len(blocks), 1, 'the contract pins one json block')
        self.pin = json.loads(blocks[0])

    def valid(self, record):
        return matches(record, self.schema, self.schema)

    def covers(self):
        defs = self.schema['$defs']
        wanted = set(FIXED_COVERS)
        wanted |= {f'scene.{key}' for key in defs['owner_scene']['properties']}
        wanted |= {f'public.{key}' for key in defs['public_scene']['properties']}
        wanted |= {f'mode.{mode}' for mode in self.pin['modes']}
        wanted |= {f'steer.{line["title"]}' for line in defs['steer_line']['oneOf']}
        wanted |= {f'theme.{key}' for key in defs['theme']['properties']}
        return wanted

    def test_the_schema_accepts_every_valid_record(self):
        self.assertEqual(self.schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(self.schema['$id'], 'https://openwiz.dev/contracts/room.v1.schema.json')
        self.assertEqual(self.schema['title'], VERSION)
        self.assertEqual(self.pin['schema'], VERSION)
        for name, record in self.good.items():
            with self.subTest(fixture=name):
                self.assertEqual(record['schema'], VERSION)
                self.assertTrue(self.valid(record))
                self.assertIn(f'`{name}`', self.readme)

    def test_the_schema_refuses_each_broken_record(self):
        names = set()
        for case in self.cases:
            with self.subTest(fixture=case['case']):
                self.assertNotIn(case['case'], names)
                names.add(case['case'])
                self.assertIn(case['valid'], self.good)
                self.assertIn(f'| {case["case"]} | `{case["valid"]}` | {case["covers"]} |', self.readme)
                self.assertFalse(self.valid(mutate(self.good[case['valid']], case)))
        self.assertEqual(set(re.findall(r'^\| ([a-z][\w-]+) \| `', self.readme, re.M)), names)

    def test_every_field_mode_steer_line_budget_rule_and_theme_field_has_a_broken_row(self):
        covered = {case['covers'] for case in self.cases}
        self.assertEqual(self.covers() - covered, set())
        self.assertEqual(set(self.pin['modes']), {'owner', 'public'})
        self.assertEqual(set(self.pin['steer_lines']), {line['title'] for line in self.schema['$defs']['steer_line']['oneOf']})
        for title in self.pin['steer_lines']:
            with self.subTest(steer=title):
                self.assertTrue(self.valid(self.good[f'steer-{title}']))

    def test_a_public_scene_with_any_name_id_or_control_is_refused(self):
        public = self.good['public-scene']
        owner = self.good['owner-scene']
        self.assertEqual(set(public), set(self.schema['$defs']['public_scene']['properties']))
        self.assertEqual(set(public) - {'schema', 'mode', 'read_at'},
                         {'prs_merged_total', 'prs_merged_7d', 'drivers_verified', 'agents_running'})
        leaks = {key: owner[key] for key in owner if key not in public}
        leaks.update(name=owner['figures'][0]['name'], id=owner['beacons'][0]['id'],
                     ticket=owner['figures'][0]['ticket'], taps=owner['beacons'][1]['taps'],
                     line=owner['beacons'][1]['taps'][0]['line'], controls=True)
        for key, value in leaks.items():
            with self.subTest(leak=key):
                self.assertFalse(self.valid(dict(public, **{key: value})))
        for number in ('prs_merged_total', 'prs_merged_7d', 'drivers_verified', 'agents_running'):
            for value in (owner['figures'][0]['name'], owner['beacons'][0]['id'], [4101], {'ticket': 4101}):
                with self.subTest(number=number, value=value):
                    self.assertFalse(self.valid(dict(public, **{number: value})))

    def test_beacons_are_the_needs_owner_kinds_with_their_tap_lines(self):
        beacon_kinds = {part['properties']['kind']['const'] for part in self.schema['$defs']['beacon']['oneOf']}
        self.assertEqual(beacon_kinds, NEEDS_OWNER)
        self.assertEqual({beacon['kind'] for beacon in self.good['owner-scene']['beacons']}, NEEDS_OWNER)
        taps = [tap for beacon in self.good['owner-scene']['beacons'] for tap in beacon['taps']]
        taps += [tap for figure in self.good['owner-scene']['figures'] for tap in figure['taps']]
        used = set()
        for tap in taps:
            with self.subTest(line=tap['line']):
                self.assertTrue(self.valid(dict(self.good['steer-pause'], line=tap['line'])))
                used |= {title for title in self.pin['steer_lines']
                         if matches(tap['line'], self.schema['$defs'][f'line_{title}'], self.schema)}
        self.assertEqual(used, set(self.pin['steer_lines']))

    def test_the_contract_pins_the_budget_and_the_default_look(self):
        caps = self.pin['phone_budget']
        rules = self.schema['$defs']['frame']['allOf'][0]['then']['properties']
        self.assertEqual(caps, {'max_figures': rules['figures_drawn']['maximum'],
                                'max_draw_calls': rules['draw_calls']['maximum'],
                                'max_triangles': rules['triangles']['maximum'],
                                'min_fps': rules['fps']['minimum'], 'below_floor': '2d'})
        self.assertEqual(caps['min_fps'], 30)
        self.assertEqual(self.pin['default_theme'], self.good['theme-default'])
        self.assertEqual(self.pin['default_theme']['look'], 'holo-butler')
        self.assertIs(self.pin['default_theme']['sound']['on'], False)
        self.assertEqual(self.pin['scene_file'], '.openwiz/room.v1.json')
        self.assertEqual(self.pin['sources'], {'stations': 'states', 'figures': 'states', 'pipeline': 'states',
                                               'meters': 'usage', 'requests': 'requests', 'beacons': 'feed'})
        sources = self.schema['$defs']['unavailable']['items']['properties']['source']['enum']
        self.assertEqual(set(sources), set(self.pin['sources'].values()))

    def test_reader_rules_hold_on_the_valid_scenes(self):
        for name in ('owner-scene', 'owner-scene-unavailable'):
            with self.subTest(fixture=name):
                self.assertEqual(reader_rules(self.good[name]), [])
        scene = copy.deepcopy(self.good['owner-scene'])
        scene['figures'][1]['station'] = 'gamma'
        scene['stations'].append(dict(scene['stations'][0]))
        scene['pipeline']['merge'].append(dict(scene['pipeline']['build'][0]))
        self.assertTrue(self.valid(scene))
        self.assertEqual(len(reader_rules(scene)), 3)

    def test_no_trademarked_name_or_private_value_appears(self):
        texts = {path.name: path.read_text(encoding='utf-8')
                 for path in (CONTRACT, SCHEMA, HERE / 'README.md', HERE / 'valid.json', HERE / 'broken.json')}
        for name, text in texts.items():
            with self.subTest(file=name):
                self.assertIsNone(LIKENESS.search(text))
                self.assertIsNone(PRIVATE.search(text))
        self.assertTrue(LIKENESS.search('a butler named Jarvis'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
