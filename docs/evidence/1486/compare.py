#!/usr/bin/env python3
"""#1486 AC2: ci/select's plan against the path table's, on FF5's (#1335) cases.

  python3 -I docs/evidence/1486/compare.py OLD_TREE NEW_TREE > compare.log

OLD_TREE is a checkout of main before #1486 (ci/select/ and its signed map);
NEW_TREE is #1486's. Each case is one pull request on the synthetic repository
of FF5's PullRequestPlan (ci/select/test_pick.py), in this tree's layout, whose map has FF5's
readers: rust:lib:openwiz-core reads crates/core/src/lib.rs, rust:test:fleet
reads tests/fleet/main.rs, docs/agents/fleet.md and wizskills.lock, and
rust:test:checks (the always lane's) is unmapped. Prints each plan's mode
and Rust tests, and `same` or `DIFF`. Evidence only: nothing runs it in CI.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

OLD, NEW = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
CASES = [
    # FF5's PullRequestPlan cases.
    ('docs-only', ['docs/ROADMAP.md', 'docs/cleanup/new-table.md', 'NOTES.md']),
    ('skills-only', ['.claude/skills/old/SKILL.md', '.claude/skills/new/SKILL.md', '.agents/skills/new/x']),
    ('a doc a test reads', ['docs/agents/fleet.md']),
    ('a pin move', ['wizskills.lock']),
    # FF5's rules (pick.py 1-10), one case each.
    ('5: a path no job reads', ['STATUS.md', 'private/notes/x.md']),
    ('6: a modified source', ['crates/core/src/lib.rs']),
    ('6: a modified file no test reads', ['docs/adr/0001.md']),
    ('8: a new source', ['crates/core/src/brand_new.rs']),
    ('8: a new file under tools/', ['tools/brand-new/run.py']),
    ('8: a new top-level folder', ['new-unmapped/future.txt']),
    ('9: a new doc beside the class', ['docsx/new.md']),
    ('4: a CI path', ['.github/workflows/ci.yml']),
    ('10: a test of its own', ['tests/fleet/main.rs']),
    ('the checks test', ['tests/checks/main.rs']),
]
FILES = {
    'Cargo.toml': '[workspace]\nmembers=["crates/core", "tests"]\n',
    'crates/core/Cargo.toml': '[package]\nname="openwiz-core"\n', 'crates/core/src/lib.rs': '//\n',
    'tests/Cargo.toml': '[package]\nname="openwiz-tests"\nautobins=false\nautotests=false\n'
                        'autoexamples=false\nautobenches=false\n[[test]]\nname="checks"\npath="checks/main.rs"\n'
                        '[[test]]\nname="fleet"\npath="fleet/main.rs"\n',
    'tests/checks/main.rs': '//\n', 'tests/fleet/main.rs': '//\n', 'docs/adr/0001.md': 'synthetic\n',
    'docs/agents/fleet.md': 'synthetic\n', 'docs/ROADMAP.md': 'synthetic\n', 'STATUS.md': 'synthetic\n',
    'wizskills.lock': '{}\n', '.claude/skills/old/SKILL.md': 'synthetic\n',
    '.github/actions/docs-only/ci-reads.txt': '', '.github/workflows/ci.yml': 'synthetic\n',
}


def load(tree, name):
    spec = importlib.util.spec_from_file_location(name, tree / '.github/actions/docs-only/plan.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Synthetic', '-c',
                                    'user.email=synthetic@example.invalid', *args], text=True).strip()


def plan(tree, module, edits, folder):
    root = folder / 'repo'
    for name, body in dict(FILES, **{'.github/actions/docs-only/classify.sh':
                                     (tree / '.github/actions/docs-only/classify.sh').read_text()}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body)
    git(root, 'init', '-q')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'base')
    base = git(root, 'rev-parse', 'HEAD')
    for name in edits:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        with (root / name).open('a') as f:
            f.write('synthetic change\n')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'change')
    run = dict(id=9000100, attempt=1, event='pull_request', action='synchronize', base_branch='main',
               base=base, head=git(root, 'rev-parse', 'HEAD'), pull_request=909)
    live = dict(draft=False, base={'ref': 'main', 'sha': base}, head={'sha': run['head']})
    if module is new:
        return module.build(root, run, live)[0]
    mp = {'schema': 'openwiz.ci-select-map.v1', 'commit': base, 'units': {
        'rust:lib:openwiz-core': {'files': ['crates/core/src/lib.rs'], 'dirs': []},
        'rust:test:fleet': {'files': ['tests/fleet/main.rs', 'docs/agents/fleet.md', 'wizskills.lock'], 'dirs': []}}}
    data = json.dumps(mp).encode()
    (folder / 'maps').mkdir()
    (folder / 'maps/map.json').write_bytes(data)
    token = signing.sign(signing.claims(aud=signing.job.audience(data), sha=base), signing.KEY)
    (folder / 'maps/map.jwt').write_text(token)
    return module.build(root, run, live, folder / 'maps', signing.REPO, keys=signing.jwks(signing.KEY))[0]


def answer(record):
    lane = record['lanes']['rust']
    mode = record['selection']['mode']
    if mode == 'full':
        mode += ' (' + ', '.join(r['code'] for r in record['selection']['reasons']) + ')'
    return mode, lane['tests'] if lane['decision'] == 'run' else []


sys.path.insert(0, str(OLD / 'ci/select'))
import test_job as signing  # noqa: E402
old, new = load(OLD, 'old_plan'), load(NEW, 'new_plan')
print('case | ci/select: mode, rust lane | path table: mode, rust lane | same?')
for name, edits in CASES:
    answers = []
    for tree, module in ((OLD, old), (NEW, new)):
        with tempfile.TemporaryDirectory() as folder:
            answers.append(answer(plan(tree, module, edits, Path(folder))))
    print(f'{name} | {answers[0][0]}, {answers[0][1]} | {answers[1][0]}, {answers[1][1]} | '
          + ('same' if answers[0] == answers[1] else 'DIFF'))
