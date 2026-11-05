#!/usr/bin/env python3
"""Read-only privacy check for openwiz.open-development.v1."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow import Unknown, refused_jobs, parse

DECIDERS = ('Jake',)
PUBLIC_ROOT = 'f099f9e0cbd3fc2a8ce3edf981235c953ee2dec7'
PUBLIC_ANCHOR = '5d069b025c6eacb4123ca8241ba21345f1eae9dd'
THREAD = re.compile(r'\bthr_[A-Za-z0-9][A-Za-z0-9_-]*')
CLOUD_ID = re.compile(r'\b(?:(?:proj|prj|mch|usr|acct|auto)_[A-Za-z0-9]+|cr_(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}|(?:syn|web)[A-Za-z0-9]*))')
HOME = re.compile(r'/(?:Users|home)/([^/\s"\'`<>:;,()\[\]{}]+)')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}')
# WZ2 (#2630), the two forms #1409's export review found: a concrete helper
# snapshot/window location with its per-run suffix (an all-X mktemp template,
# `*` or `<run>` is generic), and an owner machine's CPU facts, even wrapped
# over two comment lines, unless the text says the example is invented.
HELPER_STATE = re.compile(r'\b(?:snapshot|window)\.([A-Za-z0-9]+)/state\.json\b'
                          r'|helper-checks/\S*?\b(?:snapshot|window)\.([A-Za-z0-9]+)')
CPU_FACT = re.compile(r'\b[0-9]+(?:\.[0-9]+)?[\s-]*(?:v?CPUs?|cores?)\b'
                      r'|\b(?:cpu\.max|CPU quota|quota)\b[^.;]*?\b[0-9]+\b', re.IGNORECASE)
OWNER_MACHINE = re.compile(r"\b(?:the PC|PC's|the Mac|Mac's|owner's|owner machine|host's|"
                           + '|'.join(re.escape(x) + "'s" for x in DECIDERS) + r')(?![A-Za-z0-9])', re.IGNORECASE)
INVENTED = re.compile(r'\b(?:for example|e\.g\.|invented|hypothetical|synthetic|imagine)', re.IGNORECASE)
# Abbreviations whose dot does not end a sentence, masked before splitting.
ABBREVIATION = re.compile(r'\b(?:e\.g|i\.e|etc|vs|cf)\.', re.IGNORECASE)
SENTENCE_END = re.compile(r'[.!?](?=\s|$)')
COMMENT = re.compile(r'^\s*(?:#+|//+|/?\*+|>+|--)?\s*')
COMMIT_EMAIL = re.compile(r'(?:[1-9][0-9]*\+[A-Za-z0-9][A-Za-z0-9-]*|[A-Za-z0-9][A-Za-z0-9-]*)@users\.noreply\.github\.com|noreply@github\.com')


class Unreadable(Exception):
    pass


class Checker:
    def __init__(self, literals=()):
        self.literals = literals
        self.findings = 0
        self.references = []

    def refuse(self, rule, place, line=1):
        # No source snippets, paths, job names, Git stderr or exception text:
        # even a file name or an error can itself contain a private value.
        print(f'{rule} {place}:{line}')
        self.findings += 1

    def text(self, text, place, contract=False):
        skip = False
        previous = ''
        previous_named = False
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            if contract and re.fullmatch(r'```bad[ \t]*', line):
                skip = True
                previous = ''
                previous_named = False
                continue
            if skip:
                if re.fullmatch(r'```[ \t]*', line):
                    skip = False
                continue
            if any(not m[0].startswith(('thr_syn', 'thr_web')) for m in THREAD.finditer(line)):
                self.refuse('T1', place, n)
            # Only names outside double quoted spans can introduce a record.
            name_positions = []
            quoted = False
            names = '|'.join(re.escape(x) for x in DECIDERS)
            for match in re.finditer(r'["“”]|\b(?:' + names + r')\b', line):
                if match[0] in ('"', '“', '”'):
                    quoted = not quoted
                elif not quoted:
                    name_positions.append(match.start())
            if any(re.search(r'^[^"“”]*:(?:\*\*)?\s*\\?["“”]', line[pos:]) for pos in name_positions):
                self.refuse('T2', place, n)
            if line.lstrip().startswith('>') and previous_named and re.search(r':(?:\*\*)?\s*$', previous):
                self.refuse('T2', place, n)
            bad_id = any(not re.match(r'^(?:proj|prj|mch|usr|acct|auto|cr)_(?:syn|web)', m[0]) for m in CLOUD_ID.finditer(line))
            bad_home = any(m[1] not in {'runner', 'cache', 'token', 'secret', 'someone'} and
                           not m[1].startswith(('synthetic', 'example')) for m in HOME.finditer(line))
            bad_email = any(not allowed_email(m[0]) for m in EMAIL.finditer(line))
            if (bad_id or bad_home or bad_email or helper_state(line)
                    or machine_fact(lines, n) or any(x in line for x in self.literals)):
                self.refuse('T3', place, n)
            previous = line
            previous_named = bool(name_positions)
        if skip:
            self.refuse('READ', place)

    def file(self, name, data, place):
        if name == 'private' or name.startswith('private/') or (name.startswith('docs/grills/') and name != 'docs/grills/README.md'):
            self.refuse('F1', place)
        self.text(name, place + '-path')
        if b'\0' in data:
            if is_workflow(name):
                self.refuse('F2', place)
            return  # Binary contents require review.
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            # Known binary signatures only; unknown encodings fail closed.
            if data.startswith((b'\x89PNG', b'\xff\xd8\xff', b'GIF8', b'%PDF-', b'RIFF', b'\x00\x00')) and not is_workflow(name):
                return
            self.refuse('READ', place)
            return
        self.text(text, place, name == 'contracts/open-development.v1.md')
        if is_workflow(name):
            try:
                if refused_jobs(text):
                    self.refuse('F2', place)
                for job in parse(text)['jobs'].values():
                    if isinstance(job, dict) and isinstance(job.get('uses'), str) and job['uses'].startswith('./'):
                        self.references.append((job['uses'][2:], place))
            except (Unknown, RecursionError):
                self.refuse('F2', place)


def helper_state(line):
    return any(not re.fullmatch('X+', m[1] or m[2]) for m in HELPER_STATE.finditer(line))


def machine_fact(lines, n):
    # A CPU fact ending on line n (it may start on the line before), with the
    # owner machine named nearby (this line or its neighbours, any sentence).
    # Only the fact's own statement can say it is invented: its sentence,
    # within the lines the fact itself spans, so a separate comment line never
    # qualifies it. Comment marks are removed first.
    previous = COMMENT.sub('', lines[n - 2]) if n > 1 else ''
    current = COMMENT.sub('', lines[n - 1])
    following = COMMENT.sub('', lines[n]) if n < len(lines) else ''
    text = previous + ' ' + current
    start, end = len(previous) + 1, len(text)
    masked = ABBREVIATION.sub(lambda m: m[0].replace('.', '_'), text)
    near = text + ' ' + following
    for fact in CPU_FACT.finditer(masked):
        if not start < fact.end() <= end:
            continue
        low = 0 if fact.start() < start else start
        before = [m.end() for m in SENTENCE_END.finditer(masked, low, fact.start())]
        after = SENTENCE_END.search(masked, fact.end(), end)
        statement = text[before[-1] if before else low:after.end() if after else end]
        if OWNER_MACHINE.search(near) and not INVENTED.search(statement):
            return True
    return False


def safe_place(name, literals):
    import json
    return json.dumps(redact(name, literals), ensure_ascii=True)


def redact(name, literals=()):
    """A location with every private form this check refuses replaced, for
    any report that must name a file without printing a private value."""
    redacted = THREAD.sub('<thread>', name)
    redacted = CLOUD_ID.sub('<id>', redacted)
    redacted = HOME.sub('<home>', redacted)
    redacted = EMAIL.sub('<email>', redacted)
    redacted = HELPER_STATE.sub('<helper-state>', redacted)
    if machine_fact([redacted], 1):
        redacted = '<machine-fact>'
    for literal in literals:
        redacted = redacted.replace(literal, '<literal>')
    if 'Jake' in redacted and any(x in redacted for x in ('"', '“', '”', '>')):
        redacted = '<quoted-path>'
    return redacted


def is_workflow(name):
    return re.fullmatch(r'\.github/workflows/[^/]+\.ya?ml', name) is not None


def allowed_email(value):
    local, domain = value.rsplit('@', 1)
    return (domain in {'example.com', 'example.org', 'example.net', 'example.invalid'} or domain.endswith('.example') or
            domain == 'users.noreply.github.com' or
            (domain == 'github.com' and local in {'noreply', 'git', 'user', 'pass'}))


def git_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    return env


def git(repo, *args):
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(repo), *args],
                            env=git_environment(), capture_output=True)
    if result.returncode:
        raise Unreadable()
    return result.stdout


class BlobReader:
    """One lazy child per scan; every path still receives its own check."""

    def __init__(self, repo):
        self.repo, self.process = repo, None

    def read(self, sha):
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise Unreadable()
        if self.process is None:
            self.process = subprocess.Popen(
                ['git', '--no-replace-objects', '-C', str(self.repo), 'cat-file', '--batch'],
                env=git_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
        child = self.process
        child.stdin.write(sha.encode('ascii') + b'\n')
        child.stdin.flush()
        header = child.stdout.readline().split()
        if len(header) != 3 or header[:2] != [sha.encode('ascii'), b'blob'] or not header[2].isdigit():
            raise Unreadable()
        size = int(header[2])
        data = child.stdout.read(size)
        if len(data) != size or child.stdout.read(1) != b'\n':
            raise Unreadable()
        return data

    def close(self):
        if self.process is None:
            return
        child = self.process
        try:
            child.stdin.close()
            if child.wait(timeout=10):
                raise Unreadable()
        except subprocess.TimeoutExpired:
            raise Unreadable() from None
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()


def commit(repo, ref):
    value = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise Unreadable()
    return value


def history(checker, repo, base, head):
    head = commit(repo, head)
    base = commit(repo, base) if base else None
    if git(repo, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        checker.refuse('C1', 'history')
        return
    graft = git(repo, 'rev-parse', '--git-path', 'info/grafts').decode().strip()
    graft = Path(graft) if Path(graft).is_absolute() else Path(repo) / graft
    if os.path.lexists(graft):
        checker.refuse('C1', 'history')
        return
    roots = git(repo, 'rev-list', '--max-parents=0', head).decode().splitlines()
    try:
        git(repo, 'merge-base', '--is-ancestor', PUBLIC_ANCHOR, head)
        anchored = True
    except Unreadable:
        anchored = False
    if roots != [PUBLIC_ROOT] or not anchored:
        checker.refuse('C1', 'history')
        return []
    # No base means a new remote ref: check everything after the approved
    # public anchor. Old public history is explicitly exempt from C2/C3.
    if base is None:
        base = commit(repo, PUBLIC_ANCHOR)
    hashes = git(repo, 'rev-list', head, '^' + base, '^' + PUBLIC_ANCHOR).decode().splitlines()
    for index, sha in enumerate(hashes, 1):
        data = git(repo, 'cat-file', 'commit', sha).decode('utf-8')
        headers, message = data.split('\n\n', 1)
        checker.text(message, f'commit-{index}')
        for role in ('author', 'committer'):
            rows = [line for line in headers.splitlines() if line.startswith(role + ' ')]
            if len(rows) != 1:
                checker.refuse('C3', f'commit-{index}-{role}')
                continue
            email = re.fullmatch(r'.* <([^<>]*)> [0-9]+ [+-][0-9]{4}', rows[0])
            if not email or not COMMIT_EMAIL.fullmatch(email[1]):
                checker.refuse('C3', f'commit-{index}-{role}')
    return hashes


def directory_files(root):
    if not root.is_dir() or root.is_symlink():
        raise Unreadable()
    def walk(folder):
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda x: x.name):
                relative = Path(entry.path).relative_to(root).as_posix()
                if relative == '.git':
                    continue
                if entry.is_symlink():
                    yield relative, os.readlink(entry.path).encode()
                elif entry.is_dir(follow_symlinks=False):
                    yield from walk(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    yield relative, Path(entry.path).read_bytes()
                else:
                    raise Unreadable()
    yield from walk(root)


def git_files(repo, ref, blobs):
    tree = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{tree}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', tree):
        raise Unreadable()
    for entry in git(repo, 'ls-tree', '-rz', '--full-tree', tree).split(b'\0'):
        if not entry:
            continue
        info, name = entry.split(b'\t', 1)
        mode, kind, sha = info.decode().split()
        if kind != 'blob' or mode not in {'100644', '100755', '120000'}:
            raise Unreadable()
        yield name.decode('utf-8'), blobs.read(sha)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, help='explicit staged public directory; symlinks are not followed')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--git-tree', help='Git tree/ref to scan without checkout')
    parser.add_argument('--base', help='range exclusion; default is the approved public anchor')
    parser.add_argument('--head', help='commit whose ancestry and new messages/identities are checked')
    parser.add_argument('--title-file', type=Path)
    parser.add_argument('--body-file', type=Path)
    parser.add_argument('--literals', type=Path)
    parser.add_argument('--require-literals', action='store_true', help='required for importer and mover')
    args = parser.parse_args(argv)
    checker = Checker()
    input_role = 'literals'
    try:
        if args.require_literals and not args.literals:
            raise Unreadable()
        if args.literals:
            values = args.literals.read_text(encoding='utf-8').splitlines()
            if not values or any(not x.strip() for x in values):
                raise Unreadable()
            checker.literals = values
        input_role = 'input'
        if not any((args.tree, args.git_tree, args.head, args.title_file, args.body_file)):
            raise Unreadable()
        if (args.head or args.git_tree or args.base) and not args.repo:
            raise Unreadable()
        if args.base and not args.head:
            raise Unreadable()
        commits = history(checker, args.repo, args.base, args.head) if args.head else []
        blobs = BlobReader(args.repo)
        trees = []
        if args.tree:
            trees.append(('staged', directory_files(args.tree)))
        if args.git_tree:
            trees.append(('tree', git_files(args.repo, args.git_tree, blobs)))
        # A later deletion does not remove material from published history.
        # Scan every newly reachable commit tree as well as the proposed tip.
        refs = list(dict.fromkeys(([commit(args.repo, args.head)] if args.head else []) + (commits or [])))
        for index, ref in enumerate(refs, 1):
            trees.append((f'commit-tree-{index}', git_files(args.repo, ref, blobs)))
        with closing(blobs):
            for tree_place, entries in trees:
                input_role = 'tree' if tree_place == 'staged' else 'input'
                known = set()
                checker.references = []
                for index, (name, data) in enumerate(entries, 1):
                    known.add(name)
                    checker.file(name, data, tree_place + ':' + safe_place(name, checker.literals))
                for target, place in checker.references:
                    if target not in known:
                        checker.refuse('F2', place)
        for name in ('title', 'body'):
            path = getattr(args, name + '_file')
            if path:
                input_role = name
                checker.text(path.read_text(encoding='utf-8'), 'pr-' + name)
    except (OSError, ValueError, OverflowError, UnicodeError, Unreadable, RecursionError):
        checker.refuse('READ', input_role)
    print('literals: ' + ('used' if checker.literals else 'not used'))
    return int(bool(checker.findings))


if __name__ == '__main__':
    sys.exit(main())
