"""Stub for the red run: copies the raw folder unchanged."""
import argparse
import shutil
import sys

p = argparse.ArgumentParser()
p.add_argument('raw')
p.add_argument('out')
p.add_argument('--literals', required=True)
a = p.parse_args()
shutil.copytree(a.raw, a.out, symlinks=True)
sys.exit(0)
