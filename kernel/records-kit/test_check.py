#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures')

BREAKS = {
    'wrong-label': ['#2 L1: label building says what an agent is doing; read it from GitHub'],
    'held-and-ready': ['#2 L2: held beside ready-for-agent'],
    'ticket-carries-spec': ['#2 L3: a ticket carries spec'],
    'spec-lacks-label': ['#2 L3: its spec #1 lacks spec', '#4 L3: its spec #1 lacks spec'],
    'two-live-notes': ['#2 S1: 2 live builder notes: 202, 208'],
    'unreadable-note': ['#2 S2: note 208 does not read as openwiz:status v1'],
    'malformed-beside-live-note': ['#2 S2: note 208 does not read as openwiz:status v1'],
    'missing-template-part': ['#2 T1: ticket lacks ## Proof', '#2 T1: ticket lacks **Relies on:**'],
    'spec-missing-section': ['#1 T1: spec lacks ## Out of Scope'],
    'human-missing-done-by': ['#4 T1: ticket lacks ## Done by'],
    'commented-out-heading': ['#2 T1: ticket lacks ## Proof'],
    'blocker-without-reason': ['#2 B1: #3 has no reason line'],
    'blocker-not-completed': ['#2 B2: blocker #9 is closed as not_planned, not completed',
                              '#2 B2: blocker #10 is closed as duplicate, not completed'],
    'one-line-code-span': ['#1 T1: spec lacks ## Out of Scope'],
    'foreign-long-form': ['#2 B1: malformed section: line `- other-owner/site#3 real: the example shape` names '
                          'other-owner/site#3, not this repository'],
}


def run(path):
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'check.py'), '--fixture', path],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout.splitlines(), p.stderr


def valid():
    with open(os.path.join(FIXTURES, 'valid.json')) as f:
        return json.load(f)


class Kit(unittest.TestCase):
    def test_valid_trackers_pass(self):
        names = sorted(n for n in os.listdir(FIXTURES) if n.startswith('valid'))
        self.assertEqual(names, ['valid-own-long-form.json', 'valid.json'])
        for name in names:
            with self.subTest(name):
                code, out, err = run(os.path.join(FIXTURES, name))
                self.assertEqual((code, out), (0, []), err)

    def test_each_planted_break_is_reported(self):
        names = sorted(n[len('broken-'):-len('.json')] for n in os.listdir(FIXTURES) if n.startswith('broken-'))
        self.assertEqual(names, sorted(BREAKS))
        for name, want in BREAKS.items():
            with self.subTest(name):
                code, out, err = run(os.path.join(FIXTURES, 'broken-%s.json' % name))
                self.assertEqual((code, out), (1, want), err)

    def test_links_section_read_as_plan_links_reads_it(self):
        links = '## Links\n\n- #3 real: the example shape\n'
        planted = {
            'two lines': ('- #3 real: the example shape\n- #3 real: the example shape again\n',
                          ['#2 B1: #3 has more than one line']),
            'not a link line': ('- #3: the example shape\n',
                                ['#2 B1: malformed section: a line is not a link line or none']),
            'heading in a comment': ('<!--\n## Links\n-->\n- #3 real: the example shape\n',
                                     ['#2 T1: ticket lacks ## Links', '#2 B1: #3 has no reason line']),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (section, want) in planted.items():
                with self.subTest(name):
                    d = valid()
                    body = d['issues'][1]['body']
                    self.assertIn(links, body)
                    if not section.startswith('<!--'):
                        section = '## Links\n\n' + section
                    d['issues'][1]['body'] = body.replace(links, section)
                    path = os.path.join(tmp, 'links.json')
                    with open(path, 'w') as f:
                        json.dump(d, f)
                    code, out, err = run(path)
                    self.assertEqual((code, out), (1, want), err)

    def test_fences_and_comments_hide_only_what_github_hides(self):
        what, proof = 'A synthetic change.\n', '\n## Proof\n\nA fixture test.\n'
        planted = {
            'comment opener in a fence': (what, what + '\n```html\n<!--\n```\n', []),
            'fence in a comment': (proof, '\n<!--\n```\n-->\n' + proof, []),
            'opener after a closer': (proof, '\n<!-- a note --> <!--' + proof + '-->\n',
                                      ['#2 T1: ticket lacks ## Proof']),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (old, new, want) in planted.items():
                with self.subTest(name):
                    d = valid()
                    body = d['issues'][1]['body']
                    self.assertEqual(body.count(old), 1)
                    d['issues'][1]['body'] = body.replace(old, new)
                    path = os.path.join(tmp, 'hidden.json')
                    with open(path, 'w') as f:
                        json.dump(d, f)
                    code, out, err = run(path)
                    self.assertEqual((code, out), (1 if want else 0, want), err)

    def test_reader_refuses_any_other_shape(self):
        def drop(d, k):
            del d[k]
        bad = {
            'unknown top key': lambda d: d.update(extra=1),
            'missing top key': lambda d: drop(d, 'now'),
            'unknown issue key': lambda d: d['issues'][0].update(state='open'),
            'labels not a list': lambda d: d['issues'][0].update(labels='spec'),
            'number as text': lambda d: d['issues'][0].update(number='1'),
            'number as true': lambda d: d['issues'][0].update(number=True),
            'repeated number': lambda d: d['issues'][1].update(number=1),
            'bad blocker reason': lambda d: d['issues'][1]['blocked_by'][0].update(state_reason='done'),
            'open blocker with reason': lambda d: d['issues'][1]['blocked_by'][0].update(state='open'),
            'bad time': lambda d: d.update(now='2030-01-02 04:00'),
            'impossible time': lambda d: d.update(now='2030-13-02T04:00:00Z'),
            'comment author missing': lambda d: drop(d['issues'][1]['comments'][0], 'author'),
            'other tracker version': lambda d: d.update(tracker='openwiz:records-kit tracker v2'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, plant in bad.items():
                with self.subTest(name):
                    d = valid()
                    plant(d)
                    path = os.path.join(tmp, 'bad.json')
                    with open(path, 'w') as f:
                        json.dump(d, f)
                    code, out, err = run(path)
                    self.assertEqual((code, out), (2, []))
                    self.assertTrue(err.startswith('check.py: '), err)
            path = os.path.join(tmp, 'dup.json')
            with open(path, 'w') as f:
                f.write(json.dumps(valid())[:-1] + ', "now": "2030-01-02T04:00:00Z"}')
            code, out, err = run(path)
            self.assertEqual((code, out), (2, []), 'a repeated key must be refused, never replaced')


if __name__ == '__main__':
    unittest.main(verbosity=2)
