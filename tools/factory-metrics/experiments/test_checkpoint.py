#!/usr/bin/env python3
"""Owning file-boundary proof: explicit offline operations survive process restart.

A serialization or stale-write bug can lose assignments or erase a stop; prior
in-memory tests cannot prove subprocess reload or strict input parsing.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fixture',HERE/'test_analysis.py')
T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)
E,C=T.E,T.C


class Checkpoint(unittest.TestCase):
    def run_cli(self,*args):
        return subprocess.run([sys.executable,'-I',str(HERE/'run.py'),*map(str,args)],
                              capture_output=True,text=True)

    def test_restart_assign_advance_analyze_and_reject_live_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);checkpoint=root/'checkpoint.json'
            d,j=T.cohort(3);assignments=d['assignments'];d['assignments']=[]
            for name,value in [('bundle',d),('journey',j),('facts',dict(eligible=True,safeguards=T.T.SAFE))]:
                (root/(name+'.json')).write_text(json.dumps(value))
            result=self.run_cli('init','--checkpoint',checkpoint,'--bundle',root/'bundle.json',
                                '--journey',root/'journey.json')
            self.assertEqual(result.returncode,0,result.stderr)
            for a in assignments:
                result=self.run_cli('assign','--checkpoint',checkpoint,'--ticket',a['ticket'],
                                    '--facts',root/'facts.json','--at',T.T.AT)
                self.assertEqual(result.returncode,0,result.stderr)
            restored,rj=E.load_checkpoint(checkpoint)
            self.assertEqual(restored['assignments'],assignments)
            (root/'bundle.json').write_text(json.dumps(restored))
            result=self.run_cli('advance','--checkpoint',checkpoint,'--bundle',root/'bundle.json',
                                '--journey',root/'journey.json','--at','2030-01-06T00:00:00Z')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIsNone(E.load_checkpoint(checkpoint)[0]['result'])
            result=self.run_cli('analyze','--checkpoint',checkpoint,'--at',T.HORIZON)
            self.assertEqual(result.returncode,0,result.stderr)
            printed=json.loads(result.stdout)
            self.assertEqual(printed['evidence_class'],'offline-only')
            self.assertEqual(E.load_checkpoint(checkpoint)[0]['result']['verdict'],'inconclusive')
            result=self.run_cli('launch_live','--checkpoint',checkpoint)
            self.assertEqual(result.returncode,2)

    def test_cross_pr_source_conflict_refuses_checkpoint_save_and_load(self):
        d,j=T.cohort(1);after=copy.deepcopy(d);next_j=copy.deepcopy(j)
        event=copy.deepcopy(next(e for e in next_j['pull_requests'][0]['events'] if C.J.rounds_of(e)))
        event['id']='e99999'
        next_j['pull_requests'][1]['events'].append(event)
        after['journey']['measurements'][1]['rounds'].append(event['id'])
        after['journey']['journey_hash']=C.digest(next_j)
        C.validate(after,next_j)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json';bad=Path(tmp)/'bad.json'
            with self.subTest(api='initial-save'), self.assertRaisesRegex(ValueError,'source'):
                E.save_checkpoint(bad,after,next_j)
            with self.subTest(api='initial-save-bytes'):
                self.assertFalse(bad.exists())
            E.save_checkpoint(path,d,j);original=path.read_bytes()
            expected=C.digest(dict(bundle=d,journey=j))
            with self.subTest(api='update-save'), self.assertRaisesRegex(ValueError,'source'):
                E.save_checkpoint(path,after,next_j,expected=expected)
            with self.subTest(api='update-save-bytes'):
                self.assertEqual(path.read_bytes(),original)
            bad.write_text(json.dumps(dict(bundle=after,journey=next_j)))
            with self.subTest(api='load'), self.assertRaisesRegex(ValueError,'source'):
                E.load_checkpoint(bad)

    def test_strict_json_failed_writes_and_assignment_history(self):
        d,j=T.cohort();before=copy.deepcopy(d)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            E.save_checkpoint(path,d,j)
            original=path.read_bytes()
            # A correct digest permits append-only deviations; rewriting a
            # frozen revision still refuses and keeps the old bytes.
            expected=C.digest(dict(bundle=d,journey=j))
            bad=copy.deepcopy(d);bad['assignments'][0]['assigned_at']='2030-01-05T00:01:00Z'
            with self.assertRaisesRegex(ValueError,'immutable'):
                E.save_checkpoint(path,bad,j,expected=expected)
            self.assertEqual(path.read_bytes(),original)
            d['deviations'].append(dict(ticket=4300,kind='overlap',material=True,source='s1',actual_revision=None))
            E.save_checkpoint(path,d,j,expected=expected)
            self.assertEqual(E.load_checkpoint(path)[0]['deviations'],d['deviations'])
            with self.assertRaisesRegex(ValueError,'changed'):
                E.save_checkpoint(path,before,j,expected=expected)
            path.write_text('{"bundle":{},"bundle":{},"journey":{}}')
            with self.assertRaisesRegex(ValueError,'duplicate'):
                E.load_checkpoint(path)
            path.write_text('{"bundle":NaN,"journey":{}}')
            with self.assertRaises(ValueError): E.load_checkpoint(path)


if __name__=='__main__': unittest.main()
