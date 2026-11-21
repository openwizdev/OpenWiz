#!/usr/bin/env python3
import hashlib
import json
import shlex
import sys
import unittest

sys.dont_write_bytecode = True
import test as base
from test_open import OpenRelease
from test_entry import EntryCheck

PRIVATE = 'https://github.com/jparker2006/ClosedWiz/'


class ReviewFixes(OpenRelease):
    def setUp(self):
        super().setUp()
        self.history_anchor = self.base
        self.save_plan()

    def document(self, text):
        path = self.repo/'docs/decision.md'
        path.write_text(text)
        self.commit(self.repo)
        self.replan()
        review = next(r for r in self.data['claim_reviews'] if r['path'] == 'docs/decision.md')
        review['claims'] = [{'text':line,'status':'context','evidence':''}
                            for line in text.splitlines() if line.strip() and not line.startswith('#')]
        self.save_plan()

    def test_r1_complete_public_development_tree(self):
        paths = ['docs/grills/README.md','STATUS.md','tools/war-room/AGENTS.md','design-rules.md',
                 'tools/war-room/design-rules.md','tools/release/synthetic/check.md',
                 'tests/checks/evidence-synthetic/check.md','docs/fleets/README.md',
                 '.claude/skills/export-synthetic/SKILL.md','docs/GLOSSARY.md','skills/synthetic/SKILL.md']
        for name in paths:
            path = self.repo/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# Public document\n\nContext: Synthetic public guidance.\n')
        alias = '.claude/skills/synthetic'
        (self.repo/alias).symlink_to('../../skills/synthetic')
        self.commit(self.repo)
        self.replan()
        self.data['files'].append({'path':alias,'source':alias,'mode':'120000',
                                  'sha256':hashlib.sha256(b'../../skills/synthetic').hexdigest()})
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual({r['path'] for r in json.loads((self.evidence/'report.json').read_text())['files']},
                         set(base.fixture_files()) | set(paths) | {alias})

    def test_r1_private_classes_still_refuse(self):
        for name in ['private/synthetic.md','docs/grills/synthetic.md']:
            with self.subTest(name=name):
                self.outputs_clear()
                path = self.repo/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('')
                self.commit(self.repo)
                result = self.check()
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('F1 ',(self.evidence/'open-development-privacy.log').read_text())

    def test_r3_deleted_private_ancestor_is_refused(self):
        path = self.repo/'private/synthetic.txt'
        path.parent.mkdir()
        path.write_text('Synthetic private ancestor.\n')
        self.commit(self.repo)
        self.git(self.repo,'rm','private/synthetic.txt')
        self.commit(self.repo)
        self.assertEqual(self.git(self.repo,'status','--porcelain').stdout,'')
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('F1 commit-tree-',(self.evidence/'open-development-privacy.log').read_text())
        self.assertFalse((self.stage/'export').exists())

    def test_r3_new_commit_identity_is_checked(self):
        self.git(self.repo,'-c','user.name=Synthetic','commit','--allow-empty','-qm','Synthetic invalid author',
                 '--author','Synthetic <person@example.invalid>')
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('C3 ',(self.evidence/'open-development-privacy.log').read_text())

    def test_r4_contract_pointers_and_crosslinks_pass(self):
        forms = [f'Context: Source: Robin, 2030-01-01: decision ([private record]({PRIVATE}issues/9001#issuecomment-9000001)).',
                 f'Private record: {PRIVATE}pull/9002#issuecomment-9000002',
                 f'was [ClosedWiz #9003]({PRIVATE}issues/9003)',
                 f'was [ClosedWiz #9004]({PRIVATE}pull/9004)',
                 'moved to [OpenWiz #9005](https://github.com/example-owner/example-release/issues/9005)']
        self.document('# Decision\n\n'+'\n\n'.join(forms)+'\n')
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        self.outputs_clear()
        self.data['scan_exceptions'] = [{'path':'docs/decision.md','rule':'url',
            'value':PRIVATE+'issues/9001#issuecomment-9000001',
            'sha256':hashlib.sha256((self.repo/'docs/decision.md').read_bytes()).hexdigest()}]
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(json.loads((self.evidence/'report.json').read_text())['scan_exceptions']),1)

    def test_r4_malformed_or_unrelated_private_links_refuse(self):
        forms = [f'Context: \\[private record]({PRIVATE}issues/9001#issuecomment-9000001).',
                 f'Context: [private record]({PRIVATE}issues/09001#issuecomment-9000001).',
                 f'Context: [private record]({PRIVATE}issues/9001#issuecomment-0).',
                 f'Context: [private record]({PRIVATE}issues/9001).',
                 f'Context: [private record]({PRIVATE}blob/main/private/synthetic.md).',
                 f'Context: [other]({PRIVATE}issues/9001#issuecomment-9000001).',
                 f'was [ClosedWiz #9001]({PRIVATE}issues/9002)',
                 f'was [ClosedWiz #9001]({PRIVATE}issues/9001) extra',
                 f'Context: [private record]({PRIVATE}issues/9001#issuecomment-9000001). Other {PRIVATE}issues/9001#issuecomment-9000001',
                 f'was [ClosedWiz #09001]({PRIVATE}issues/9001)']
        for text in forms:
            with self.subTest(text=text):
                self.outputs_clear()
                self.document('# Decision\n\n'+text+'\n')
                result = self.check()
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('private',result.stderr)

    def test_r3_foreign_root_is_refused(self):
        foreign = self.root/'foreign'
        foreign.mkdir()
        self.git(foreign,'init','-q','-b','main')
        (foreign/'synthetic.txt').write_text('Synthetic foreign history.\n')
        self.commit(foreign)
        self.git(self.repo,'fetch',str(foreign),'main')
        self.git(self.repo,'merge','-q','--allow-unrelated-histories','-s','ours','--no-edit','FETCH_HEAD')
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('C1 ',(self.evidence/'open-development-privacy.log').read_text())


class ReviewEntries(EntryCheck):
    def test_r3_generated_entry_commit_identity_is_checked(self):
        delegate = self.bin/'recorded-git'
        (self.bin/'git').rename(delegate)
        real = shlex.quote(str(delegate))
        (self.bin/'git').write_text('#!/bin/sh\n'
            'if [ "${PWD##*/}" = export ]; then\n'
            '  previous=\n  for arg in "$@"; do\n'
            '    if [ "$arg" = commit ] && [ "$previous" != cat-file ]; then\n'
            '      exec '+real+' "$@" --author "Synthetic <person@example.invalid>"\n'
            '    fi\n    previous=$arg\n  done\nfi\nexec '+real+' "$@"\n')
        (self.bin/'git').chmod(0o755)
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('privacy:',result.stderr)
        self.assertIn('C3 ',(self.evidence/'staged-privacy.log').read_text())
        report = json.loads((self.evidence/'report.json').read_text())
        self.assertEqual(report['checks'][-1]['id'],'privacy')
        self.assertEqual(report['checks'][-2],{'id':'stage','status':'pass'})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (ReviewFixes,ReviewEntries) for name in cls.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
