"""Sanitize a recorded run's exported records into public evidence.

    python3 -I kernel/proofs/hermes/sanitize.py RAW_DIR OUT_DIR --literals LIST

Copies every text file in RAW_DIR to OUT_DIR with live identifiers replaced:
thread ids, driver run ids (numbered in order of first use), home paths,
credential shapes, email addresses other than GitHub noreply ones, and each
line of LIST (the private literals file: names, hosts, anything else private).
Then runs the privacy check on OUT_DIR; on a refusal OUT_DIR is removed.
Exit 0 written and clean, 1 privacy refusal, 2 bad input. Never writes into
RAW_DIR. Exact words are never sanitized into public form: leave them out.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECK = ROOT / 'tools' / 'privacy-check' / 'check.py'

FIXED = [
    (re.compile(r'\bthr_[A-Za-z0-9][A-Za-z0-9_-]*'), '[thread]'),
    (re.compile(r'\b(?:gh[opsur]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'), '[token]'),
    (re.compile(r'\bsk-[A-Za-z0-9_-]{12,}'), '[token]'),
    (re.compile(r'(?:/home|/Users)/[^/\s]+'), '~'),
    (re.compile(r'[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '[email]'),
]
RUN = re.compile(r'\brun-[0-9a-f]{12}\b')


def sanitize_text(text, literals=(), runs=None):
    runs = {} if runs is None else runs
    for literal in sorted((l for l in literals if l), key=len, reverse=True):
        text = text.replace(literal, '[private]')
    for pattern, replacement in FIXED:
        text = pattern.sub(replacement, text)
    return RUN.sub(lambda m: runs.setdefault(m.group(0), f'run-{len(runs) + 1:012d}'), text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('raw', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--literals', type=Path)
    args = parser.parse_args(argv)
    if args.literals is None or not args.literals.is_file():
        print('sanitize: --literals LIST is required (the private literals file)', file=sys.stderr)
        return 2
    literals = [l.strip() for l in args.literals.read_text().splitlines() if l.strip() and not l.startswith('#')]
    if not literals or not args.raw.is_dir() or args.out.exists():
        print('sanitize: need a non-empty literals list, an existing RAW_DIR and a new OUT_DIR', file=sys.stderr)
        return 2
    runs = {}
    files = sorted(p for p in args.raw.rglob('*') if p.is_file() and not p.is_symlink())
    try:
        texts = [(p, p.read_text(encoding='utf-8')) for p in files]
    except UnicodeDecodeError as e:
        print(f'sanitize: not text, leave it out: {e}', file=sys.stderr)
        return 2
    for path, text in texts:
        dest = args.out / path.relative_to(args.raw)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sanitize_text(text, literals, runs), encoding='utf-8')
    check = subprocess.run([sys.executable, '-I', str(CHECK), '--tree', str(args.out),
                            '--literals', str(args.literals), '--require-literals'])
    if check.returncode != 0:
        shutil.rmtree(args.out)
        print('sanitize: the privacy check refused; output removed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
