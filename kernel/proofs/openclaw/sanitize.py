"""Turn a recorded run's raw records into public evidence, or refuse.

    python3 -I kernel/proofs/openclaw/sanitize.py <raw folder> <out folder> --literals <private list>

Reads every file under the raw folder and writes each one, rewritten, to the
same place under a new out folder:

- a CloudRoom thread id becomes `<thread>`, any other cloud id `<cloud-id>`;
- a home folder (`/home/<name>`, `/Users/<name>`) becomes `~`;
- an email address becomes `<email>`, except a GitHub noreply commit address;
- each line of the private literals list (machine, account and private
  repository names, one per line) becomes `<literal>`.

It refuses the whole run (exit 1) and writes nothing when any file holds a
credential (rotate it; never publish a hidden one), is not UTF-8 text with a
known suffix, or is a symbolic link; when the out folder already exists; or
when OpenWiz's privacy check refuses the rewritten files. A refusal names the
file and line, never the text. Exit 2: bad arguments or an unreadable literals
list. Standard library only.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
CHECK = ROOT / 'tools' / 'privacy-check' / 'check.py'
SUFFIXES = {'.md', '.txt', '.json', '.log'}
CREDENTIAL = re.compile(
    r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}'
    r'|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})'
    r'|\bBearer\s+[A-Za-z0-9._~+/=-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----')
REWRITES = [
    (re.compile(r'\bthr_[A-Za-z0-9][A-Za-z0-9_-]*'), '<thread>'),
    (re.compile(r'\b(?:(?:proj|prj|mch|usr|acct|auto)_[A-Za-z0-9]+|cr_[A-Za-z0-9-]+)'), '<cloud-id>'),
    (re.compile(r'/(?:Users|home)/[^/\s"\'`<>:;,()\[\]{}]+'), '~'),
]
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}')
NOREPLY = re.compile(r'(?:[1-9][0-9]*\+)?[A-Za-z0-9][A-Za-z0-9-]*@users\.noreply\.github\.com')


class Refused(Exception):
    pass


def literals(path):
    try:
        values = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not values or any(not v.strip() for v in values):
        return None
    return sorted(set(values), key=len, reverse=True)


def rewrite(text, names, place):
    lines = text.split('\n')
    for n, line in enumerate(lines, 1):
        if CREDENTIAL.search(line):
            raise Refused(f'{place}:{n}: a credential; rotate it, never publish it')
        for name in names:
            line = line.replace(name, '<literal>')
        for pattern, value in REWRITES:
            line = pattern.sub(value, line)
        line = EMAIL.sub(lambda m: m[0] if NOREPLY.fullmatch(m[0]) else '<email>', line)
        lines[n - 1] = line
    return '\n'.join(lines)


def sanitize(raw, out, names, literals_path):
    files = []
    for path in sorted(raw.rglob('*')):
        place = path.relative_to(raw).as_posix()
        if path.is_symlink():
            raise Refused(f'{place}: a symbolic link')
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix not in SUFFIXES:
            raise Refused(f'{place}: not a known text file ({", ".join(sorted(SUFFIXES))})')
        try:
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            raise Refused(f'{place}: not UTF-8 text')
        files.append((place, rewrite(text, names, place)))
    if not files:
        raise Refused('the raw folder holds no files')
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        stage = Path(tmp) / 'out'
        for place, text in files:
            target = stage / place
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        check = subprocess.run([sys.executable, '-I', str(CHECK), '--tree', str(stage),
                                '--literals', str(literals_path), '--require-literals'],
                               capture_output=True, text=True)
        if check.returncode != 0:
            found = [l for l in check.stdout.splitlines() if not l.startswith('literals:')]
            raise Refused('the privacy check refused the rewritten files: ' + '; '.join(found))
        stage.rename(out)
    return len(files)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('raw', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--literals', required=True)
    args = parser.parse_args(argv)
    names = literals(args.literals)
    if names is None:
        print('sanitize: the literals list is missing, empty or has a blank line', file=sys.stderr)
        return 2
    if not args.raw.is_dir() or args.raw.is_symlink():
        print('sanitize: the raw folder is not a folder', file=sys.stderr)
        return 2
    if args.out.exists() or args.out.is_symlink():
        print('sanitize: refused: the out folder already exists', file=sys.stderr)
        return 1
    try:
        count = sanitize(args.raw, args.out, names, args.literals)
    except Refused as why:
        print(f'sanitize: refused: {why}', file=sys.stderr)
        return 1
    print(f'sanitize: {count} file(s) written to {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
