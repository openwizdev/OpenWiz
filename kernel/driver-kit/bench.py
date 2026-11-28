#!/usr/bin/env python3
import argparse
import importlib.machinery
import importlib.util
import os
import secrets
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, '..', '..', 'adapters', 'boat', 'driver')
MARKED = 10


def load_kit(path):
    spec = importlib.util.spec_from_loader('kit', importlib.machinery.SourceFileLoader('kit', path))
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    return kit


def median_ms(scan, rounds):
    for _ in range(5):
        scan()
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        scan()
        times.append(time.perf_counter() - start)
    return statistics.median(times) * 1000


def row(kit, extra, rounds):
    args = argparse.Namespace(driver=DRIVER, harness='fake-harness', repo='example/site', ticket=7,
                              skill='build-ticket', model='m', wait=8, effort='medium', tracker=None)
    k = kit.Kit(args, None)
    marked = dict(os.environ, OPENWIZ_KIT_RUN=k.mark.partition('=')[2])
    children = []
    try:
        for i in range(max(extra, 1)):
            children.append(subprocess.Popen(['sleep', '600'], env=marked if i < MARKED else os.environ))
        time.sleep(0.3)
        canary = ('devin', 'kit-canary-' + secrets.token_hex(16))
        visible = sum(1 for p in os.listdir('/proc') if p.isdigit()) if kit.PROC else len(k.ps('-o', 'stat='))
        return visible, median_ms(k.scan, rounds), median_ms(lambda: k.scan(canary), rounds)
    finally:
        for child in children:
            child.kill()
            child.wait()


def main(argv):
    ap = argparse.ArgumentParser(prog='bench.py', description="times one of the kit's process scans")
    ap.add_argument('--kit', default=os.path.join(HERE, 'kit.py'), help='the kit.py to time (default this one)')
    ap.add_argument('--processes', default='0,50,200,400', help='extra idle processes per row, comma-separated')
    ap.add_argument('--rounds', type=int, default=40, help='timed scans per row')
    args = ap.parse_args(argv)
    kit = load_kit(os.path.abspath(args.kit))
    print('| Processes | Scan | Scan with the key check |')
    print('| ---: | ---: | ---: |')
    for extra in (int(n) for n in args.processes.split(',')):
        visible, plain, keyed = row(kit, extra, args.rounds)
        print('| %d | %.2f ms | %.2f ms |' % (visible, plain, keyed), flush=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
