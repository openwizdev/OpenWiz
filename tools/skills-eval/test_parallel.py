#!/usr/bin/env python3
"""Offline proofs for scheduling the unchanged isolated driver concurrently."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))

class Parallel(unittest.TestCase):
    def load(self):
        spec=importlib.util.spec_from_file_location('parallel_eval',HERE/'parallel.py')
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_shared_cap_includes_all_in_flight_reservations(self):
        m=self.load()
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            budget=m.Budget(out, 20)
            barrier=threading.Barrier(4)
            accepted=[]
            def reserve(i):
                barrier.wait()
                interim={'cost_usd':6,'uncertain_usd':6,'usage':{},'provider_usage':[]}
                try:
                    budget.checkpoint(out/f'case{i}.r1.json',interim)
                    accepted.append(i)
                except m.Cap:
                    pass
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(reserve,range(4)))
            self.assertEqual(len(accepted),3)
            self.assertEqual(sum(json.loads(p.read_text())['cost_usd'] for p in out.glob('*.r*.json')),18)
            # Completed actual cost releases only its own reservation; unknown charges remain reserved.
            budget.finish(out/f'case{accepted[0]}.r1.json',{'cost_usd':1})
            budget.checkpoint(out/'new.r1.json',{'cost_usd':6,'uncertain_usd':6})
            self.assertEqual(sum(json.loads(p.read_text())['cost_usd'] for p in out.glob('*.r*.json')),19)

    def test_cap_preserves_known_usage_without_charging_unsent_request(self):
        m=self.load()
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);budget=m.Budget(out,20)
            budget.finish(out/'prior.r1.json',{'cost_usd':19})
            with self.assertRaises(m.Cap) as caught:
                budget.checkpoint(out/'next.r1.json',{'cost_usd':3,'uncertain_usd':2,
                    'usage':{'input_tokens':100},'provider_usage':[{'cost':1}], 'events':[], 'final':'', 'case':'next','repeat':1})
            t=caught.exception.transcript
            self.assertEqual((t['cost_usd'],t['uncertain_usd'],t['stop']),(1,0,'cap'))
            self.assertEqual(t['usage']['input_tokens'],100)
            self.assertFalse((out/'next.r1.json').exists())

if __name__=='__main__': unittest.main()
