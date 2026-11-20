"""Tests for sanitize.py on the synthetic fixture: python3 -I kernel/proofs/grok-bot/test_sanitize.py"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = json.loads((HERE / 'fixtures' / 'raw.json').read_text())


def build(raw):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'raw.json'
        out = Path(d) / 'run.md'
        src.write_text(json.dumps(raw))
        done = subprocess.run([sys.executable, '-I', str(HERE / 'sanitize.py'), 'build', str(src), '--out', str(out)],
                              capture_output=True, text=True)
        return done, out.read_text() if out.exists() else ''


class Sanitize(unittest.TestCase):
    def test_full_run_keeps_every_record_form_and_covers_every_stage(self):
        # catches: a record form dropped, so the evidence can't show a stage the run did reach
        done, run = build(RAW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('stages: ok', done.stdout)
        for kept in ('builder done, Claude Code, Opus 5.5 Medium, build-ticket@0.2.0: handed back the pull request',
                     'reviewer done, Codex, Sol 6.2 Medium, review-ticket@0.2.0: approved the exact head',
                     'VERDICT: APPROVE at bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                     'launch-fleet: started',
                     'plan graph approved, 2030-01-02, revision 1',
                     'merged at 2030-01-02T04:00:00Z as aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                     '[private record](https://github.com/example-owner/demo-private/issues/3#issuecomment-111)'):
            self.assertIn(kept, run)

    def test_prose_and_exact_words_never_reach_the_evidence(self):
        # catches: a blacklist sanitizer that copies bodies through and misses unmarked words
        done, run = build(RAW)
        self.assertNotIn('PLANTED', run)
        self.assertNotIn('Robin', run)
        self.assertIn('comment, body dropped', run)

    def test_a_note_with_a_private_value_is_withheld_whole(self):
        # catches: field-by-field copying that lets a thread id in a step through
        raw = copy.deepcopy(RAW)
        note = raw['items'][1]['comments'][2]
        note['body'] = note['body'].replace('THREAD', 'thr' + '_PLANTED01')  # split so the privacy check passes this file
        done, run = build(raw)
        self.assertNotIn('thr_', run)
        self.assertIn('status note withheld: private value', run)

    def test_a_note_from_someone_else_is_discussion(self):
        # catches: trusting the marker instead of the record-author list
        done, run = build(RAW)
        self.assertNotIn('STRANGER', run)
        self.assertEqual(run.count('builder done'), 1)

    def test_a_missing_stage_fails_and_is_named(self):
        # catches: a run that never merged being reported as end to end
        raw = copy.deepcopy(RAW)
        raw['items'][2]['merged_at'] = None
        done, _ = build(raw)
        self.assertEqual(done.returncode, 1)
        self.assertIn('stages missing: merged', done.stdout)

    def test_a_private_title_is_withheld(self):
        # catches: titles copied without the same guard as notes
        raw = copy.deepcopy(RAW)
        raw['items'][1]['title'] = 'Fix /home/someone/demo build'
        done, run = build(raw)
        self.assertNotIn('/home/', run)
        self.assertIn('title withheld', run)


if __name__ == '__main__':
    unittest.main()
