#!/usr/bin/env python3
"""Write one X0 selection record and its execution prerequisites, once per run.

A pull request's plain case (decide.sh's) narrows the Rust lane by path
(#1486): classify.sh's table names the Rust tests each changed path reaches.
Execution metadata is kept beside (and bound to) the contract record, never
used to make a second selection in another job.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import gate
import skills
import units

ALWAYS = ['always:fmt', 'always:classifier', 'always:selector', 'always:checks']
RELEASE = ['release:test', 'release:package', 'release:install', 'release:pull',
           'release:github-app', 'release:ci-runner',
           'release:security-baseline',
           'release:security-candidate',
           'release:ci2-batch-contract', 'release:ci2-batch-shadow',
           'release:ci2-main-batch-admit',
           'release:ci2-overload',
           'release:product-identity',
           'release:setup-onboard-contract',
           'release:test-value',
           'release:test-value-unread-fixtures',
           'release:setup-onboard-init',
           'release:setup-onboard-login',
           'release:setup-onboard-journey',
           'release:fleet-load']
# O16-P-RETIRED (#2429): the retiring CI overflow switch's check is registered
# only in a tree that carries its command target (ClosedWiz). The public tree
# leaves tools/ci-overflow/ out, so the literal above stays its exact set. This
# one id only: any other missing command target still fails the lane.
if (ROOT / 'tools/ci-overflow/test.py').is_file():
    RELEASE.insert(RELEASE.index('release:ci2-batch-contract'), 'release:ci2-spending')
SKIP = 'no changed path reaches it'
# CI and the toolchain (the contract's `ci_change`): the workflows and the
# classifier, the runner kit and CI's scripts, the workspace manifest and
# every lockfile, and toolchain pins. Never under private/, which no job reads.
CI_CHANGE = re.compile(r'(?!private/)(?:\.github/.+|ci/runner/.+|ci/[^/]+|ci/hosted/.+|ci/escapes/escapes\.py'
                       r'|Cargo\.toml|Cargo\.lock|(.+/)?package-lock\.json'
                       r'|rust-toolchain(\.toml)?|\.nvmrc|\.node-version|\.tool-versions)')
FLAGS = ('lint-rust', 'build-site', 'image-skills')


def text(value):
    return ' '.join(str(value).split())[:500] or 'unknown error'


def lane(all_tests, selected):
    tests = sorted(set(all_tests) & set(selected))
    if not tests:
        return {'decision': 'skip', 'reason': SKIP}
    return {'decision': 'run', 'tests': tests,
            'skipped': [{'test': t, 'reason': SKIP} for t in sorted(set(all_tests) - set(tests))]}


def event_reasons(run):
    return [{'code': code} for code, yes in (
        ('push_main', run['event'] == 'push'), ('nightly', run['event'] == 'schedule'),
        ('merge_group', run['event'] == 'merge_group'), ('rerun', run['attempt'] > 1),
        ('release_branch', run['base_branch'].startswith('release-')),
        ('ready_for_review', run['action'] == 'ready_for_review')) if yes]


def mandatory_ci_paths(paths):
    return sorted(p for p in paths if CI_CHANGE.fullmatch(p))


def odd_path(path):
    """A path the plan refuses to reason about."""
    return (not path or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in path))


def changed(root, base, head):
    """Every path that differs between the two commits, or raises (a failed diff)."""
    out = subprocess.run(['git', '-C', str(root), 'diff', '--no-renames', '--no-ext-diff', '-z', '--name-only',
                          base, head, '--'], capture_output=True, check=True).stdout
    return sorted({p.decode('utf-8', errors='surrogateescape') for p in out.split(b'\0') if p})


def classify(root, paths, *args, step=''):
    return subprocess.run(['sh', str(root / '.github/actions/docs-only/classify.sh'), *args],
        input='\n'.join(paths) + '\n', capture_output=True, text=True, check=True,
        env=dict(os.environ, CLASSIFY_STEP=step, READS=str(root / '.github/actions/docs-only/ci-reads.txt'))).stdout


def rust_tests(root, paths, inventory):
    """The Rust tests the paths reach by classify.sh's table, and the paths no row knows."""
    answers = classify(root, paths, '--tests').splitlines()
    if len(answers) != len(paths):
        raise ValueError('classify.sh gave no answer for every path')
    every = {t for t in inventory if t.startswith('rust:')}
    tests, unknown = set(), []
    for path, answer in zip(paths, answers):
        if answer == '?':
            unknown.append(path)
        elif answer == '*':
            tests |= every
        elif answer != '-':
            named = set(answer.split(','))
            if not named <= every:
                raise ValueError('the path table names a test that is not in the tree: ' + answer)
            tests |= named
    return tests, unknown


def steps(paths, root):
    """K16's step requirements: Rust lint, the release proofs' step, skill suites."""
    suites = sorted({p.split('/')[1] for p in paths if p.startswith('skills/') and p.count('/') > 1} & set(skills.SUITES))
    if any(p in ('wizskills.lock', 'skills') for p in paths):
        suites = sorted(skills.SUITES)  # the pin or the link moves every installed suite (#1612 R1)
    lint = any(p.endswith('.rs') or p.startswith('crates/') or p in ('Cargo.toml', 'Cargo.lock', 'tests/Cargo.toml')
               for p in paths)
    site = classify(root, paths, step='site').strip()
    if site not in ('none', 'web-build', 'web-build web-test'):
        raise ValueError('no site decision from classify.sh')
    values = (lint, 'web-test' in site.split(), 'image' in suites)
    return {**{k: 'true' if v else 'false' for k, v in zip(FLAGS, values)},
            'skill-tests': ' '.join(suites) if suites else 'none'}


def legacy_readers(root, paths, step=''):
    # Known standalone skill suites do not consume release inputs.
    # Everything else retains the conservative reader union used to prune
    # the old Rust and web release suites, including their docs and tools.
    paths=[p for p in paths if not any(p.startswith('skills/'+s+'/') for s in skills.SUITES)]
    if not paths:
        return set()
    result=classify(root,paths,step=step)
    if result.strip() not in ('none','web-build','web-build rust','web-build web-test','web-build rust web-test'):
        raise ValueError('unreadable legacy reader decision')
    return set(result.split())-{'none'}


def build(root, run, live):
    root = Path(root)
    inventory = sorted(units.list_units(root))
    reasons = event_reasons(run)
    if run['event'] == 'pull_request':
        if (not isinstance(live, dict) or type(live.get('draft')) is not bool
                or not isinstance(live.get('base'), dict) or not isinstance(live.get('head'), dict)):
            raise ValueError('unreadable live pull request')
        if live['draft']:
            raise ValueError('draft pull request: no acceptance plan')
        actual = (live['base'].get('ref'), live['base'].get('sha'), live['head'].get('sha'))
        if not all(isinstance(x, str) and x for x in actual):
            raise ValueError('unreadable live pull request identity')
        if actual != (run['base_branch'], run['base'], run['head']):
            reasons.append({'code': 'stale_event', 'detail': 'live PR base or head differs from its event'})
    diff = {'state': 'not_read'}
    if (run['event'] == 'pull_request' and not any(r['code']=='stale_event' for r in reasons)) or not reasons:
        if subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f"{run['base']}^{{commit}}"],
                          capture_output=True).returncode:
            reasons.append({'code': 'stale_event', 'detail': 'event base is not in this clone'})
        else:
            try:
                base = subprocess.check_output(['git', '-C', str(root), 'merge-base', run['base'], run['head']],
                                               text=True, stderr=subprocess.PIPE).strip()
                paths = changed(root, base, run['head'])
                if any(odd_path(p) for p in paths):
                    raise ValueError('diff contains an unsafe or unrepresentable path')
                diff = {'state': 'read', 'paths': paths} if paths else {'state': 'empty'}
                if not paths:
                    reasons.append({'code': 'empty_diff'})
            except Exception as error:
                diff = {'state': 'failed', 'error': text(error)}
                reasons.append({'code': 'failed_diff'})
    ci_paths = mandatory_ci_paths(diff.get('paths',[]))
    if ci_paths:
        reasons.append({'code':'ci_change','paths':ci_paths})
    chosen = set(inventory)
    requirements = {k: 'true' for k in FLAGS}
    selected_skills = list(skills.SUITES)
    if not reasons:
        try:
            chosen, unknown = rust_tests(root, diff['paths'], inventory)
            if unknown:
                reasons = [{'code': 'unknown_path', 'paths': unknown}]
            else:
                requirements = steps(diff['paths'], root)
                selected_skills = skills.selected(requirements['skill-tests'])
        except Exception as error:
            reasons = [{'code': 'selector_error', 'detail': text(error)}]
    if reasons:
        chosen = set(inventory)
        requirements = {k: 'true' for k in FLAGS}
        selected_skills = list(skills.SUITES)
    paths = diff.get('paths', [])
    # The site lane holds only the release proofs since the site copy went
    # (#1264); `build-site` is a change to their inputs.
    release_inputs = bool(reasons) or requirements['build-site'] == 'true'
    try:
        readers=legacy_readers(root,paths) if not reasons else {'rust','web-test'}
    except Exception as error:
        reasons=[{'code':'selector_error','detail':text(error)}]
        chosen=set(inventory)
        requirements={k:'true' for k in FLAGS}
        selected_skills=list(skills.SUITES)
        release_inputs=True
        readers={'rust','web-test'}
    release = bool(reasons) or release_inputs or bool(readers & {'rust','web-test'})
    # The whole checks binary is in the always lane (architecture, privacy,
    # contract/static checks and pending markers), exactly once in every run.
    rust_all = [t for t in inventory if t.startswith('rust:') and t != 'rust:test:checks']
    web_all = [t for t in inventory if t.startswith('web:')]
    record = {'schema': 'openwiz.ci-selection.v1', 'run': run, 'diff': diff,
        'selection': {'mode': 'full', 'reasons': reasons} if reasons else {'mode': 'selected'},
        'builds': {'web_export': {'decision': 'skip', 'reason': 'the web view and its export went in #1264'}},
        'lanes': {'always': {'decision': 'run', 'tests': ALWAYS, 'skipped': []},
            'rust': lane(rust_all, chosen), 'web': lane(web_all, chosen),
            'site': lane(RELEASE, RELEASE if release else []),
            'skills': [dict(skill=s, **lane(['skill:' + s], ['skill:' + s] if s in selected_skills else []))
                       for s in skills.SUITES]},
        'store': {'artifact': f"ci-selection-{run['attempt']}", 'file': 'ci-selection.json'}}
    errors = gate.escapes.refusals(json.dumps(record))
    if errors:
        raise ValueError('refused generated plan: ' + '; '.join(errors))
    dispatch = {k: requirements[k] == 'true' for k in FLAGS}
    # Nothing traces or plants since #1486. ci.yml's always, rust and ci jobs
    # still read `trace` as a main push's or the nightly run's full mode.
    dispatch.update(skills=selected_skills,
        rust=record['lanes']['rust']['decision'] == 'run', release=release,
        trace=run['event'] in ('push', 'schedule') and run['base_branch'] == 'main', planted=False)
    return record, dispatch


def run_context(env, event):
    kind = env['GITHUB_EVENT_NAME']
    pr = event.get('pull_request') if kind == 'pull_request' else None
    group = event.get('merge_group') if kind == 'merge_group' else None
    if pr is not None:
        branch, base, head = pr['base']['ref'], pr['base']['sha'], pr['head']['sha']
    elif group is not None:
        branch, base, head = group['base_ref'].removeprefix('refs/heads/'), group['base_sha'], group['head_sha']
    else:
        branch, base, head = env['GITHUB_REF_NAME'], event.get('before'), env['GITHUB_SHA']
    if base == '0' * 40:
        base = None
    return dict(id=int(env['GITHUB_RUN_ID']), attempt=int(env['GITHUB_RUN_ATTEMPT']), event=kind,
        action=event.get('action') if pr is not None else None, base_branch=branch, base=base,
        head=head, pull_request=event['number'] if pr is not None else None)


def main(argv):
    if len(argv) != 1:
        raise ValueError('usage: plan.py OUTPUT_DIRECTORY')
    event = gate.escapes.strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    run = run_context(os.environ, event)
    live = None
    if run['event'] == 'pull_request':
        raw = subprocess.check_output(['sh', 'ci/retry.sh', '3', '--', 'gh', 'api',
            f"repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{run['pull_request']}"], text=True)
        live = gate.escapes.strict_json(raw)
    record, dispatch = build(ROOT, run, live)
    out = Path(argv[0]); out.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(record, indent=2) + '\n'
    (out / 'ci-selection.json').write_text(raw)
    dispatch['plan_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    (out / 'ci-dispatch.json').write_text(json.dumps(dispatch, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for key, value in dict(dispatch, **{
                'skill-jobs': [s for s in dispatch['skills'] if s not in skills.SHARDED]}).items():
            f.write(key + '=' + json.dumps(value, separators=(',', ':')) + '\n')
    lines = [f"CI selection: {record['selection']['mode']}"]
    for name in ('always', 'rust', 'web', 'site'):
        entry = record['lanes'][name]
        lines.append(f"{name}: " + (', '.join(entry['tests']) if entry['decision'] == 'run' else 'skipped: ' + entry['reason']))
        lines += [f"  skipped {s['test']}: {s['reason']}" for s in entry.get('skipped', [])]
    for entry in record['lanes']['skills']:
        lines.append('skill ' + entry['skill'] + ': ' + ('run' if entry['decision'] == 'run' else 'skipped: ' + entry['reason']))
    if reasons := record['selection'].get('reasons'):
        lines.append('Full run: ' + ', '.join(r['code'] for r in reasons))
    summary = '\n'.join(lines) + '\n'
    print(summary)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write('### CI plan\n\n```text\n' + summary + '```\n')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception as error:
        print('plan: ' + text(error), file=sys.stderr)
        sys.exit(1)
