#!/usr/bin/env python3
"""The 0.0.13 live kit's offline dry run and result validator (#1109, IF10 instrumentation).

  live-kit-test.py                       run the kit's offline proofs
  live-kit-test.py dry-run               walk every step of live-kit.md with a simulated clock
  live-kit-test.py validate RESULT --candidate CANDIDATE
                                         check one recorded result against the bound candidate

Nothing here performs a live action: the dry run has no effect and the
validator only reads two files. A passing dry run or validation proves the
kit's shape and its timer and result rules, never a live result or an elapsed
time. Python 3.9+, standard library only.
"""
import json
from pathlib import Path
import re
import sys
import unittest

KIT = Path(__file__).resolve().with_name('live-kit.md')
LIMIT_MS = 600_000
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
KEYS = {'schema', 'candidate', 'attempt', 'platform', 'line_submitted_at_ms', 'fleet_running_at_ms',
        'elapsed_ms', 'plan_tickets', 'builders_concurrent', 'waits', 'help', 'choices', 'credits',
        'steps', 'outcome', 'reasons'}
PRIVATE = re.compile(r'thr_[A-Za-z0-9]|prj_[A-Za-z0-9]|gh[pousr]_[A-Za-z0-9]|github_pat_|[^\s@]+@[^\s@]+\.[a-z]{2,}|'
                     r'-----BEGIN|/' r'home/|/' r'Users/', re.I)


def steps():
    """The kit's steps, from its own table: (id, name, effect)."""
    rows = re.findall(r'^\| (K[0-9]+) \| ([a-z-]+) \| (read|write|spend) \| (.+) \|$', KIT.read_text(), re.M)
    return [(step, name, effect) for step, name, effect, _ in rows]


def integer(value):
    return type(value) is int and value >= 0


def hexadecimal(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def candidate_valid(value):
    """A usable candidate identity: exact fields, version syntax, full commit and
    tree, and one SHA-256 manifest hash for each declared target."""
    return (isinstance(value, dict) and set(value) == {'version', 'source', 'tree', 'manifests'}
            and isinstance(value['version'], str) and re.fullmatch(r'0\.[0-9]+\.[0-9]+', value['version']) is not None
            and hexadecimal(value['source'], 40) and hexadecimal(value['tree'], 40)
            and isinstance(value['manifests'], dict) and set(value['manifests']) == set(TARGETS)
            and all(hexadecimal(h, 64) for h in value['manifests'].values()))


def validate(result, candidate):
    """Every rule the result breaks, one plain line each; empty means valid."""
    if not isinstance(result, dict) or set(result) != KEYS:
        return ['The result must have exactly the kit\'s fields.']
    out = []
    if result['schema'] != 'openwiz.live-kit-result.v1':
        out.append('The result schema is not openwiz.live-kit-result.v1.')
    if not candidate_valid(candidate):
        out.append('The bound candidate is not a complete identity (version, full source and tree, a manifest hash per target).')
    elif not candidate_valid(result['candidate']):
        out.append('The result\'s candidate is not a complete identity (version, full source and tree, a manifest hash per target).')
    elif result['candidate'] != candidate:
        out.append('The result is not for the bound candidate.')
    if result['attempt'] != 1:
        out.append('Only attempt 1 is timed; the timer is never restarted.')
    if result['platform'] not in TARGETS:
        out.append('The platform is not a declared target.')
    start, stop, elapsed = result['line_submitted_at_ms'], result['fleet_running_at_ms'], result['elapsed_ms']
    if not integer(start):
        out.append('The start time is missing.')
    ran = stop is not None
    if ran and not (integer(stop) and integer(start) and integer(elapsed) and stop >= start and elapsed == stop - start):
        out.append('The elapsed time must be exactly stop minus start, with nothing subtracted.')
    if not ran and elapsed is not None:
        out.append('A fleet that never ran has no elapsed time.')
    tickets, builders = result['plan_tickets'], result['builders_concurrent']
    if not (integer(tickets) and 4 <= tickets <= 7):
        out.append('The plan must have 4 to 7 tickets.')
    if not (integer(builders) and integer(tickets) and builders <= tickets):
        out.append('Concurrent builders cannot exceed the plan\'s tickets.')
    if not (isinstance(result['waits'], list) and all(isinstance(w, dict) and set(w) == {'kind', 'ms'}
            and isinstance(w['kind'], str) and integer(w['ms']) for w in result['waits'])):
        out.append('Waits must be recorded as kind and ms.')
    if not (isinstance(result['help'], list) and all(isinstance(h, dict) and set(h) == {'kind'}
            and isinstance(h['kind'], str) for h in result['help'])):
        out.append('Help must be recorded as kind.')
    choices = result['choices']
    if not (isinstance(choices, dict) and set(choices) == {'agents', 'engine'}
            and all(choices[k] in ('cloud', 'local') for k in choices)):
        out.append('Choices must name agents and engine as cloud or local.')
    credits = result['credits']
    if not (isinstance(credits, dict) and set(credits) == {'provenance', 'value'}
            and credits['provenance'] in ('measured', 'estimated', 'unknown')
            and ((credits['value'] is None) if credits['provenance'] == 'unknown'
                 else (type(credits['value']) in (int, float) and credits['value'] >= 0))):
        out.append('Credits need a named provenance, and unknown credits carry no number.')
    kit = [step for step, _, _ in steps()]
    rows = result['steps']
    if not (isinstance(rows, list) and [r.get('step') if isinstance(r, dict) else None for r in rows] == kit
            and all(set(r) == {'step', 'outcome'} and r['outcome'] in ('pass', 'fail', 'gap') for r in rows)):
        out.append('The result must record every step once, in order, as pass, fail or gap.')
        rows = []
    outcome = result['outcome']
    if outcome not in ('pass', 'fail', 'gap'):
        out.append('The outcome must be pass, fail or gap.')
    if outcome == 'pass':
        if not ran:
            out.append('A fleet that never ran cannot pass.')
        elif not (integer(elapsed) and elapsed < LIMIT_MS):
            out.append('A pass needs an integer elapsed time under ten minutes.')
        if not (integer(builders) and builders >= 4):
            out.append('A pass needs at least four builders running at once.')
        if not rows or any(r['outcome'] != 'pass' for r in rows):
            out.append('A pass needs every step passed; a gap stays a gap.')
    if not (isinstance(result['reasons'], list) and result['reasons']
            and all(isinstance(r, str) and r.strip() for r in result['reasons'])):
        out.append('The result needs at least one plain reason.')
    if PRIVATE.search(json.dumps(result)):
        out.append('The result holds what looks like a private value; record sanitized aggregates only.')
    return out


def dry_run(clock=None, out=sys.stdout):
    """Every step, in order, with no effect, and a result from a simulated clock."""
    import itertools
    clock = clock or itertools.count(1_800_000_000_000, 30_000).__next__
    start = stop = None
    for step, name, effect in steps():
        now = clock()
        if name == 'install-line':
            start = now
        if name == 'fleet-running':
            stop = now
        out.write('%s %s: dry run, no effect (%s step, simulated clock %d)\n' % (step, name, effect, now))
    return result_fixture(line_submitted_at_ms=start, fleet_running_at_ms=stop, elapsed_ms=stop - start,
                          credits={'provenance': 'unknown', 'value': None}, outcome='gap',
                          steps=[{'step': s, 'outcome': 'gap'} for s, _, _ in steps()],
                          reasons=['Dry run only: no step ran and no time was measured.'])


def candidate_fixture():
    return {'version': '0.0.13', 'source': 'a' * 40, 'tree': 'b' * 40,
            'manifests': {target: c * 64 for target, c in zip(TARGETS, 'cde')}}


def result_fixture(**changes):
    value = {'schema': 'openwiz.live-kit-result.v1', 'candidate': candidate_fixture(), 'attempt': 1,
             'platform': 'x86_64-unknown-linux-gnu', 'line_submitted_at_ms': 1_800_000_000_000,
             'fleet_running_at_ms': 1_800_000_420_000, 'elapsed_ms': 420_000, 'plan_tickets': 5,
             'builders_concurrent': 4, 'waits': [{'kind': 'plan approval', 'ms': 90_000}],
             'help': [], 'choices': {'agents': 'cloud', 'engine': 'local'},
             'credits': {'provenance': 'measured', 'value': 41},
             'steps': [{'step': step, 'outcome': 'pass'} for step, _, _ in steps()],
             'outcome': 'pass', 'reasons': ['Four builders ran within ten minutes.']}
    value.update(changes)
    return value


class Kit(unittest.TestCase):

    def assertRefused(self, result, words):
        problems = validate(result, candidate_fixture())
        self.assertTrue(any(words in p for p in problems), (words, problems))

    def test_the_kit_names_its_bounded_steps_in_order(self):
        self.assertEqual([s for s, _, _ in steps()], ['K%d' % n for n in range(1, 12)])
        names = [n for _, n, _ in steps()]
        self.assertLess(names.index('discovery'), names.index('install-line'), 'discovery comes first')
        self.assertLess(names.index('install-line'), names.index('fleet-running'))
        self.assertEqual(names[-1], 'cleanup')

    def test_a_complete_result_inside_ten_minutes_passes(self):
        self.assertEqual(validate(result_fixture(), candidate_fixture()), [])

    def test_elapsed_is_exactly_stop_minus_start(self):
        # Subtracting the recorded wait would claim 330 s; the rule refuses it.
        self.assertRefused(result_fixture(elapsed_ms=330_000), 'elapsed')

    def test_over_ten_minutes_cannot_pass(self):
        late = result_fixture(fleet_running_at_ms=1_800_000_600_001, elapsed_ms=600_001)
        self.assertRefused(late, 'ten minutes')
        self.assertEqual(validate(dict(late, outcome='fail', steps=[
            dict(s, outcome='fail' if s['step'] == 'K7' else 'pass') for s in late['steps']]),
            candidate_fixture()), [])

    def test_exactly_ten_minutes_is_not_under_ten_minutes(self):
        # IF10: under ten minutes. 600 000 ms is a miss; 599 999 ms passes.
        self.assertRefused(result_fixture(fleet_running_at_ms=1_800_000_600_000, elapsed_ms=600_000), 'ten minutes')
        self.assertEqual(validate(result_fixture(fleet_running_at_ms=1_800_000_599_999, elapsed_ms=599_999),
                                  candidate_fixture()), [])

    def test_elapsed_is_an_integer_number_of_milliseconds(self):
        # A JSON float equal to stop minus start must not slip past the deadline.
        self.assertRefused(result_fixture(fleet_running_at_ms=1_800_000_600_001, elapsed_ms=600_001.0), 'elapsed')
        self.assertRefused(result_fixture(elapsed_ms=420_000.0), 'elapsed')
        self.assertRefused(result_fixture(elapsed_ms=True), 'elapsed')

    def test_a_malformed_candidate_is_refused_even_when_both_sides_agree(self):
        good = candidate_fixture()
        bad = [{}, None, [], dict(good, version='0.0'), dict(good, version='1.0.0'), dict(good, source='a' * 39),
               dict(good, tree='B' * 40), dict(good, source=None), dict(good, manifests={}),
               dict(good, manifests={t: h for t, h in good['manifests'].items() if t != 'x86_64-apple-darwin'}),
               dict(good, manifests=dict(good['manifests'], **{'x86_64-apple-darwin': 'c' * 63})),
               dict(good, manifests=dict(good['manifests'], **{'riscv64-unknown-linux-gnu': 'f' * 64})),
               dict(good, extra=1)]
        for candidate in bad:
            problems = validate(result_fixture(candidate=candidate), candidate)
            self.assertTrue(any('candidate' in p for p in problems), (candidate, problems))

    def test_a_restarted_timer_or_second_attempt_cannot_pass(self):
        self.assertRefused(result_fixture(attempt=2), 'attempt')

    def test_fewer_than_four_builders_or_a_plan_outside_four_to_seven_cannot_pass(self):
        self.assertRefused(result_fixture(builders_concurrent=3), 'four builders')
        self.assertRefused(result_fixture(plan_tickets=8, builders_concurrent=8), 'plan')
        self.assertRefused(result_fixture(plan_tickets=3, builders_concurrent=3), 'plan')
        self.assertRefused(result_fixture(builders_concurrent=6), 'plan')

    def test_a_fleet_that_never_ran_is_a_fail_with_no_time(self):
        never = result_fixture(fleet_running_at_ms=None, elapsed_ms=None)
        self.assertRefused(never, 'never ran')
        self.assertEqual(validate(dict(never, outcome='fail', builders_concurrent=0, steps=[
            dict(s, outcome='fail' if s['step'] == 'K7' else 'pass') for s in never['steps']]),
            candidate_fixture()), [])

    def test_the_result_is_bound_to_its_candidate(self):
        for key, value in (('source', 'f' * 40), ('tree', 'f' * 40), ('version', '0.0.14')):
            self.assertRefused(result_fixture(candidate=dict(candidate_fixture(), **{key: value})), 'candidate')

    def test_a_pass_needs_every_step_passed_and_a_gap_stays_a_gap(self):
        gapped = result_fixture(steps=[dict(s, outcome='gap' if s['step'] == 'K10' else 'pass')
                                       for s in result_fixture()['steps']])
        self.assertRefused(gapped, 'every step')
        self.assertRefused(result_fixture(steps=result_fixture()['steps'][:-1]), 'every step')

    def test_unknown_credits_carry_no_number_and_provenance_is_named(self):
        self.assertRefused(result_fixture(credits={'provenance': 'unknown', 'value': 12}), 'credits')
        self.assertRefused(result_fixture(credits={'provenance': 'guessed', 'value': 12}), 'credits')
        self.assertEqual(validate(result_fixture(credits={'provenance': 'unknown', 'value': None}),
                                  candidate_fixture()), [])

    def test_unknown_or_missing_fields_are_refused(self):
        extra = result_fixture()
        extra['transcript'] = 'synthetic'
        self.assertRefused(extra, 'fields')
        missing = result_fixture()
        del missing['waits']
        self.assertRefused(missing, 'fields')

    def test_private_values_are_refused(self):
        for value in ('thr_' + 'abc123', 'someone@example.com', 'ghs_abc', '/' + 'home/someone/x'):
            self.assertRefused(result_fixture(reasons=['Synthetic %s.' % value]), 'private')

    def test_escaped_private_values_are_refused_by_the_cli(self):
        # #2800: these already pass; the CLI decodes before the json.dumps scan.
        # Exercise files through the CLI so a future raw-text scan is caught.
        import subprocess
        import tempfile

        expected = 'The result holds what looks like a private value; record sanitized aggregates only.\n'
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / 'result.json'
            candidate_path = Path(directory) / 'candidate.json'
            candidate_path.write_text(json.dumps(candidate_fixture()))
            for value, character in (('someone@example.com', '@'),
                                     ('/home/synthetic-user/evidence', '/'), ('thr_syn0001', 't')):
                # Solidus escaping alone hides only the home path. The email and
                # thread id hold no slash, so their solidus case also escapes one
                # of their own characters, or a raw-text scan would still see them.
                document = result_fixture(reasons=['Synthetic / evidence: ' + value])
                text = json.dumps(document)
                one = text.replace(value, value.replace(character, r'\u%04x' % ord(character), 1))
                spellings = {
                    'one-unicode': one,
                    'solidus': (text if '/' in value else one).replace('/', r'\/'),
                    'all-unicode': text.replace(value, ''.join(r'\u%04x' % ord(c) for c in value)),
                }
                for name, encoded in spellings.items():
                    with self.subTest(value=value, spelling=name):
                        self.assertNotEqual(encoded, text)
                        self.assertEqual(json.loads(encoded), document, 'the same decoded result')
                        result_path.write_text(encoded)
                        result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                                                 'validate', str(result_path), '--candidate', str(candidate_path)],
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, expected, ''))

    def test_the_dry_run_walks_every_step_without_effects_and_validates(self):
        lines = []

        class Out:
            def write(self, text):
                lines.append(text)

        result = dry_run(clock=iter(range(1_800_000_000_000, 1_900_000_000_000, 30_000)).__next__, out=Out())
        text = ''.join(lines)
        for step, name, _ in steps():
            self.assertIn('%s %s: dry run, no effect' % (step, name), text)
        self.assertEqual(validate(result, result['candidate']), [])
        self.assertEqual(result['elapsed_ms'], result['fleet_running_at_ms'] - result['line_submitted_at_ms'])


def main(argv):
    if not argv:
        unittest.main(argv=[sys.argv[0]])
        return 0
    if argv == ['dry-run']:
        result = dry_run()
        print(json.dumps(result, indent=2))
        return 0
    if len(argv) == 4 and argv[0] == 'validate' and argv[2] == '--candidate':
        problems = validate(json.loads(Path(argv[1]).read_text()), json.loads(Path(argv[3]).read_text()))
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
