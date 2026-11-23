#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHECK = HERE / 'check.py'
CONTRACTS = HERE.parent.parent / 'contracts'
FIXTURES = CONTRACTS / 'fixtures' / 'comments'
SCHEMA = json.loads((CONTRACTS / 'comments.v1.schema.json').read_text())
EXPECTED = json.loads((FIXTURES / 'expected.json').read_text())
PIN = '0123456789abcdef0123456789abcdef01234567'
LANGUAGES = {'rust.rs', 'python.py', 'shell.sh', 'yaml.yml', 'toml.toml', 'javascript.js', 'css.css', 'html.html'}


class Repo:
    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'synthetic@example.com')
        self.write('README.md', 'synthetic\n')
        self.commit()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def copy(self, source, dest):
        shutil.copytree(source, self.root / dest, dirs_exist_ok=True)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'synthetic')
        return self.git('rev-parse', 'HEAD')

    def check(self, *args):
        run = subprocess.run([sys.executable, '-I', str(CHECK), *args], cwd=self.root,
                             capture_output=True, text=True)
        return run.returncode, run.stdout, run.stderr


def failures(stdout):
    found = set()
    for line in stdout.splitlines():
        m = re.match(r'^(.+?):(\d+): ([a-z-]+): ', line)
        if m:
            found.add((m.group(1), int(m.group(2)), m.group(3)))
    return found


def validate(value, schema, root=SCHEMA, where='report'):
    if '$ref' in schema:
        return validate(value, root['$defs'][schema['$ref'].split('/')[-1]], root, where)
    if 'oneOf' in schema:
        errors = [validate(value, s, root, where) for s in schema['oneOf']]
        return [] if any(not e for e in errors) else [f'{where}: matches no option']
    kinds = {'object': dict, 'array': list, 'string': str, 'integer': int, 'null': type(None)}
    kind = schema.get('type')
    if kind and not (isinstance(value, kinds[kind]) and not (kind == 'integer' and isinstance(value, bool))):
        return [f'{where}: not {kind}']
    errors = []
    if 'const' in schema and value != schema['const']:
        errors.append(f'{where}: not {schema["const"]}')
    if 'pattern' in schema and not re.search(schema['pattern'], value):
        errors.append(f'{where}: does not match {schema["pattern"]}')
    if 'minimum' in schema and value < schema['minimum']:
        errors.append(f'{where}: below {schema["minimum"]}')
    if kind == 'array':
        for i, item in enumerate(value):
            errors += validate(item, schema.get('items', {}), root, f'{where}[{i}]')
    if kind == 'object':
        props = schema.get('properties', {})
        errors += [f'{where}: missing {k}' for k in schema.get('required', []) if k not in value]
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], root, f'{where}.{key}')
            elif isinstance(schema.get('additionalProperties'), dict):
                errors += validate(item, schema['additionalProperties'], root, f'{where}.{key}')
            elif schema.get('additionalProperties') is False:
                errors.append(f'{where}: unexpected {key}')
    return errors


class Diff(unittest.TestCase):
    def test_each_allowed_kind_passes_and_each_disallowed_kind_fails_at_its_line(self):
        self.assertEqual(set(EXPECTED['cases']), LANGUAGES)
        repo = Repo(self)
        base = repo.git('rev-parse', 'HEAD')
        repo.copy(FIXTURES / 'cases', 'cases')
        repo.commit()
        code, out, err = repo.check('diff', '--base', base)
        self.assertEqual(code, 1, err)
        for name, case in EXPECTED['cases'].items():
            with self.subTest(name):
                got = {(line, kind) for path, line, kind in failures(out) if path == f'cases/{name}'}
                self.assertEqual(got, {tuple(f) for f in case['failures']})

    def test_doc_comments_pass_only_under_a_published_docs_path(self):
        repo = Repo(self)
        base = repo.git('rev-parse', 'HEAD')
        repo.copy(FIXTURES / 'cases', 'cases')
        repo.commit()
        code, out, err = repo.check('diff', '--base', base, '--docs', 'cases/')
        self.assertEqual(code, 1, err)
        for name, case in EXPECTED['cases'].items():
            with self.subTest(name):
                got = {(line, kind) for path, line, kind in failures(out) if path == f'cases/{name}'}
                want = {tuple(f) for f in case['failures'] if f[0] not in case['docs']}
                self.assertEqual(got, want)

    def test_the_escape_tag_passes_only_with_a_reason(self):
        repo = Repo(self)
        base = repo.git('rev-parse', 'HEAD')
        repo.write('a.py', 'X = 1  # comment-ok:   \nY = 2  # comment-ok: the synthetic loader reads this line\n')
        repo.write('b.rs', '// comment-ok:\t\nfn b() {}\n/* comment-ok: the synthetic macro scans this */\nfn c() {}\n')
        repo.commit()
        code, out, _ = repo.check('diff', '--base', base)
        self.assertEqual(code, 1)
        self.assertEqual(failures(out), {('a.py', 1, 'escape-tag-reason'), ('b.rs', 1, 'escape-tag-reason')})

    def test_only_added_lines_fail(self):
        repo = Repo(self)
        repo.write('src/old.rs', '// Old narration stays until its cut.\nfn old() {}\n')
        repo.write('src/old.py', '# Old narration.\nX = 1\n')
        base = repo.commit()
        repo.write('src/old.rs', '// Old narration stays until its cut.\nfn old() {}\nfn new() {}\n')
        repo.write('src/old.py', '# Old narration.\nX = 1\nY = 2\n')
        repo.commit()
        code, out, err = repo.check('diff', '--base', base)
        self.assertEqual((code, failures(out)), (0, set()), out + err)
        repo.write('src/old.rs', '// Old narration stays until its cut.\nfn old() {}\nfn new() {}\n// New narration.\nfn newer() {}\n')
        repo.commit()
        code, out, _ = repo.check('diff', '--base', base)
        self.assertEqual((code, failures(out)), (1, {('src/old.rs', 4, 'comment')}))

    def test_quoted_paths_and_undecodable_files_fail_closed(self):
        repo = Repo(self)
        base = repo.git('rev-parse', 'HEAD')
        repo.write('odd "name".py', '# New narration.\nX = 1\n')
        (repo.root / 'latin.rs').write_bytes(b'// caf\xe9 narration\nfn f() {}\n')
        repo.commit()
        code, out, _ = repo.check('diff', '--base', base)
        self.assertEqual((code, failures(out)), (1, {('odd "name".py', 1, 'comment'), ('latin.rs', 1, 'unreadable')}))

    def test_excluded_files_never_fail(self):
        repo = Repo(self)
        base = repo.git('rev-parse', 'HEAD')
        repo.copy(FIXTURES / 'tree', '.')
        repo.commit()
        code, out, _ = repo.check('diff', '--base', base, '--exclude', 'src/**')
        self.assertEqual((code, failures(out)), (0, set()), out)


class Count(unittest.TestCase):
    def tree(self):
        repo = Repo(self)
        repo.copy(FIXTURES / 'tree', '.')
        return repo, repo.commit()

    def count(self, repo, *args):
        code, out, err = repo.check('count', *args)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(validate(report, SCHEMA), [])
        return report

    def test_count_matches_the_known_tree(self):
        repo, head = self.tree()
        report = self.count(repo)
        self.assertIsNone(report['before'])
        after = report['after']
        self.assertEqual(after['rev'], head)
        want = EXPECTED['tree']
        self.assertEqual({k: after[k] for k in want}, want)

    def test_cases_count_their_comment_lines(self):
        repo = Repo(self)
        repo.copy(FIXTURES / 'cases', 'cases')
        repo.commit()
        by_file = self.count(repo, '--by-file')['after'].get('by_file')
        self.assertEqual(by_file, {f'cases/{n}': c['comment_lines'] for n, c in EXPECTED['cases'].items()})

    def test_before_and_after_are_counted_the_same_way(self):
        repo, before = self.tree()
        repo.write('src/main.rs', (repo.root / 'src/main.rs').read_text().replace(' // add', ''))
        after = repo.commit()
        report = self.count(repo, '--before', before, 'src/')
        self.assertEqual(report['paths'], ['src/'])
        got = [((t or {}).get('rev'), (t or {}).get('comment_lines')) for t in (report['before'], report['after'])]
        self.assertEqual(got, [(before, 7), (after, 6)])
        self.assertEqual(self.count(repo, '--at', before, 'src/main.rs')['after']['comment_lines'], 3)



REVIEW_CASES = {
    'R1 a Unicode Rust identifier': ({}, {'src/u.rs': 'fn caf\u00e9() {}\n// New narration.\n'}, [], {('src/u.rs', 2, 'comment')}),
    'R2 an added line that starts with "++ "': (
        {'a.rs': 'fn a() {}\nfn b() {}\nfn c() {}\nfn d() {}\n'},
        {'a.rs': '/* Example output:\n++ out */\nfn a() {}\nfn b() {}\nfn c() {}\nfn d() {}\n// New narration.\n'},
        [], {('a.rs', 1, 'comment'), ('a.rs', 7, 'comment')}, 3),
    'R3 a newline in a path': ({}, {'odd\nname.py': '# New narration.\n'}, [], {('"odd\\nname.py"', 1, 'comment')}),
    'R3 a non-UTF-8 path byte': ({}, {b'\xffbad.py': '# New narration.\n'}, [], {('"\\377bad.py"', 1, 'comment')}),
    'R4 a deletion-only edit to a non-UTF-8 file': (
        {'latin.rs': b'fn a() {}\n// caf\xe9\nfn b() {}\n'}, {'latin.rs': b'fn a() {}\n// caf\xe9\n'}, [], set()),
    'R5 a here-string, a bitshift and an escaped space': (
        {}, {'s.sh': 'cat <<< word\n# New narration.\necho $((1 << 2))\n# More narration.\necho word\\ #fragment\n'},
        [], {('s.sh', 2, 'comment'), ('s.sh', 4, 'comment')}),
    'R6 YAML quotes across lines and inside plain values': (
        {}, {'c.yml': 'title: "First line\n  # still the title\n  end"\nname: The \'title # New narration\n'},
        [], {('c.yml', 4, 'comment')}),
    'R7 a TOML closing run of four quotes': (
        {}, {'c.toml': "message = \'\'\'The word is \'quoted\'\'\'\' # New narration\n"}, [], {('c.toml', 1, 'comment')}),
    'R8 HTML attributes and script attributes': (
        {}, {'p.html': '<div title="<!-- example -->">OK</div>\n<script data-type="application/json">\n// New narration.\n</script>\n'},
        [], {('p.html', 3, 'comment')}),
    'R9 doc markers by language': (
        {}, {'docs/site.css': '/** Narration */\nbody {}\n', 'docs/a.js': '/*! Narration */\nlet a;\n', 'docs/b.rs': '/*! Crate docs */\nfn b() {}\n'},
        ['--docs', 'docs/'], {('docs/site.css', 1, 'comment'), ('docs/a.js', 1, 'comment')}),
    'R10 quoted pins, only on a workflow uses field': (
        {}, {'.github/workflows/w.yml': 'jobs:\n  a:\n    steps:\n      - uses: "owner/tool@PIN" # v2.1.0\n      - uses: \'owner/x@PIN\' # v3\n',
             'config.yml': 'note: uses: owner/tool@PIN # v1\n'},
        [], {('config.yml', 1, 'comment')}),
    'R11 directive reasons and directive-like strings': (
        {}, {'d.py': 'x = 1  # noqa: F841 #no-reason\n"""noqa -- formatter details."""\ny = 2  # noqa: F841 # the synthetic rule misfires\n'},
        [], {('d.py', 1, 'directive-reason'), ('d.py', 2, 'comment')}),
    '#1920 comment-shaped text in a title and a textarea': (
        {}, {'t.html': '<title>Docs // <!-- example --></title>\n<TEXTAREA rows="2"><!-- example -->\n</textarea>\n<!-- New narration. -->\n'},
        [], {('t.html', 4, 'comment')}),
    '#1921 a line continuation at a word boundary and inside a word': (
        {}, {'w.sh': 'echo ready \\\n# New narration\necho ready\\\n#fragment\n'}, [], {('w.sh', 2, 'comment')}),
    '#1967 case as a literal argument in a substitution': (
        {}, {'k.sh': 'word="$(echo case)" # check this directive\nword="$(echo esac)" # New narration\n'},
        [], {('k.sh', 1, 'comment'), ('k.sh', 2, 'comment')}),
    'R1 of #2311 a near-match before the closing tag': (
        {}, {'n.html': '<title></title-example><!-- literal sample --></title>\n<!-- New narration. -->\n'
                       '<style></style-x>body {} /* More narration. */</style>\n'},
        [], {('n.html', 2, 'comment'), ('n.html', 3, 'comment')}),
    'R2 of #2311 a literal case on a continued line': (
        {}, {'c.sh': 'word="$(echo \\\ncase)" # actual narration\n'}, [], {('c.sh', 2, 'comment')}),
    '#1968 a backtick in an inner double quote of a substitution': (
        {}, {'b.sh': 'word="$(printf \'%s\' "`printf \'%s\' value # literal`")" # comment after unsure nesting\n# New narration.\n'},
        [], {('b.sh', 2, 'comment')}),
}


class Review(unittest.TestCase):
    def repo_with(self, before, after):
        repo = Repo(self)
        for files in (before, after):
            for name, body in files.items():
                path = repo.root / os.fsdecode(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                body = body.replace('PIN', PIN) if isinstance(body, str) else body
                path.write_bytes(body.encode() if isinstance(body, str) else body)
            if files is before:
                base = repo.commit() if before else repo.git('rev-parse', 'HEAD')
        repo.commit()
        return repo, base

    def test_each_reviewed_break_is_read_right_by_both_modes(self):
        for name, (before, after, args, want, *lines) in REVIEW_CASES.items():
            with self.subTest(name):
                repo, base = self.repo_with(before, after)
                code, out, err = repo.check('diff', '--base', base, *args)
                self.assertEqual((code, failures(out)), (1 if want else 0, want), err)
                code, out, err = repo.check('count', '--before', base, *args)
                self.assertEqual(code, 0, err)
                report = json.loads(out)
                self.assertEqual(validate(report, SCHEMA), [])
                self.assertEqual(report['after']['disallowed_lines'] - report['before']['disallowed_lines'],
                                 lines[0] if lines else len(want), err)

if __name__ == '__main__':
    unittest.main(verbosity=2)
