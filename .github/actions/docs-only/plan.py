#!/usr/bin/env python3
"""Write one X0 selection record and its execution prerequisites, once per run.

The signed K15 map selects tests; K16 supplies export/lint requirements.
Execution metadata is kept beside (and bound to) the contract record, never
used to make a second selection in another job.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'ci/select'))
import gate
import job
import pick
import skills
import steps
import units

ALWAYS = ['always:fmt', 'always:classifier', 'always:selector', 'always:checks']
SITE = ['site:build', 'site:test', 'site:ci']
RELEASE = ['release:test', 'release:package', 'release:install', 'release:pull',
           'release:setup-api', 'release:github-app', 'release:open-tickets', 'release:ci-runner',
           'release:ops-live-controls', 'release:ops-live-acceptance', 'release:security-baseline',
           'release:ci2-read-contract',
           'release:ci2-shared-reads',
           'release:ci2-read-consumers',
           'release:ci2-batch-contract', 'release:ci2-batch-shadow',
           'release:ci2-main-batch-admit',
           'release:ci2-overload',
           'release:product-identity']
# O16-P-RETIRED (#2429): the retiring CI overflow switch's check is registered
# only in a tree that carries its command target (ClosedWiz). The public tree
# leaves tools/ci-overflow/ out, so the literal above stays its exact set. This
# one id only: any other missing command target still fails the lane.
if (ROOT / 'tools/ci-overflow/test.py').is_file():
    RELEASE.insert(RELEASE.index('release:ci2-batch-contract'), 'release:ci2-spending')
SKIP = 'no changed path reaches it'


def text(value):
    return ' '.join(str(value).split())[:500] or 'unknown error'


def lane(all_tests, selected):
    tests = sorted(set(all_tests) & set(selected))
    if not tests:
        return {'decision': 'skip', 'reason': SKIP}
    return {'decision': 'run', 'tests': tests,
            'skipped': [{'test': t, 'reason': SKIP} for t in sorted(set(all_tests) - set(tests))]}


def combine_site_release(record):
    # Only an already validated selected PR plan shares the existing release
    # checkout. Keep both logical test sets and their independent receipts.
    tests = record['lanes']['site'].get('tests', [])
    return (record['selection']['mode'] == 'selected'
            and any(t.startswith('site:') for t in tests)
            and any(t.startswith('release:') for t in tests))


def event_reasons(run):
    return [{'code': code} for code, yes in (
        ('push_main', run['event'] == 'push'), ('nightly', run['event'] == 'schedule'),
        ('merge_group', run['event'] == 'merge_group'), ('rerun', run['attempt'] > 1),
        ('release_branch', run['base_branch'].startswith('release-')),
        ('ready_for_review', run['action'] == 'ready_for_review')) if yes]


def mandatory_ci_paths(paths):
    return sorted(p for p in paths if pick.CI_CHANGE.fullmatch(p)
                  or p.startswith('ci/hosted/') or p=='ci/escapes/escapes.py')


def legacy_readers(root, paths, step=''):
    # Known standalone skill suites do not consume release/toolkit inputs.
    # Everything else retains the conservative reader union used to prune
    # the old Rust and web release suites, including their docs and tools.
    paths=[p for p in paths if not any(p.startswith('skills/'+s+'/') for s in skills.SUITES)]
    if not paths:
        return set()
    result=subprocess.run(['sh',str(root/'.github/actions/docs-only/classify.sh')],
        input='\n'.join(paths)+'\n',capture_output=True,text=True,check=True,
        env=dict(os.environ,CLASSIFY_STEP=step,READS=str(root/'.github/actions/docs-only/ci-reads.txt')))
    if result.stdout.strip() not in ('none','web-build','web-build rust','web-build web-test','web-build rust web-test'):
        raise ValueError('unreadable legacy reader decision')
    return set(result.stdout.split())-{'none'}


def build(root, run, live, map_dir, repo, keys=None):
    root, map_dir = Path(root), Path(map_dir)
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
    diff, changes = {'state': 'not_read'}, []
    if (run['event'] == 'pull_request' and not any(r['code']=='stale_event' for r in reasons)) or not reasons:
        if subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f"{run['base']}^{{commit}}"],
                          capture_output=True).returncode:
            reasons.append({'code': 'stale_event', 'detail': 'event base is not in this clone'})
        else:
            try:
                base = subprocess.check_output(['git', '-C', str(root), 'merge-base', run['base'], run['head']],
                                               text=True, stderr=subprocess.PIPE).strip()
                changes = pick.diff(str(root), base, run['head'])
                paths = sorted({p for _, p in changes})
                if any(pick.odd_path(p) for p in paths):
                    raise ValueError('diff contains an unsafe or unrepresentable path')
                diff = {'state': 'read', 'paths': paths} if paths else {'state': 'empty'}
                if not paths:
                    reasons.append({'code': 'empty_diff'})
            except Exception as error:
                diff = {'state': 'failed', 'error': text(error)}
                reasons.append({'code': 'failed_diff'})
    # Full PR attempts still need the diff for K15's tracer/planted-edit
    # proofs. Reading it never narrows an event-forced full selection.
    ci_paths = mandatory_ci_paths(diff.get('paths',[]))
    if ci_paths:
        reasons.append({'code':'ci_change','paths':ci_paths})
    chosen = set(inventory)
    requirements = {k: 'true' for k in steps.FLAGS}
    selected_skills = list(skills.SUITES)
    if not reasons:
        try:
            data = (map_dir / 'map.json').read_bytes()
            token = (map_dir / 'map.jwt').read_text().strip()
            claims = job.verify(data, token, keys if keys is not None else job.fetch_jwks(), repo)
            mp = pick.strict_json(data.decode('utf-8'))
            known = pick.check_map(mp)
            if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', claims['sha'], 'HEAD'],
                              capture_output=True).returncode:
                raise ValueError('signed map is not an ancestor of the tested commit')
            # Include drift since the trace. All reason paths belong to the
            # recorded conservative diff, including the PR's own paths.
            drift = pick.diff(str(root), claims['sha'], 'HEAD')
            if any(pick.odd_path(p) for _, p in drift):
                raise ValueError('map-to-head diff contains an unsafe path')
            diff['paths'] = sorted(set(diff['paths']) | {p for _, p in drift})
            if not drift:
                raise ValueError('map-to-tested diff is empty while the recorded PR diff is nonempty')
            def read(path):
                try:
                    return (root / path).read_bytes()
                except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                    return None
            result = pick.select(drift, mp, inventory, read, pick.classify_nobody(str(root)))
            mandatory = mandatory_ci_paths(diff['paths'])
            if mandatory:
                result['mode']='full'
                other=[r for r in result['reasons'] if r['code']!='ci_change']
                result['reasons']=[{'code':'ci_change','paths':mandatory},*other]
            if result['mode'] == 'full':
                reasons = result['reasons']
            elif result['mode'] == 'selected':
                if not result['tests'] or not set(result['tests']) <= set(inventory):
                    raise ValueError('empty or unknown selector answer')
                chosen = set(result['tests'])
                requirements = steps.plan(result['tests'], drift, known, str(root))
                selected_skills = skills.selected(requirements['skill-tests'])
            else:
                raise ValueError('unknown selector mode')
        except Exception as error:
            reasons = [{'code': 'selector_error', 'detail': text(error)}]
    if reasons:
        chosen = set(inventory)
        requirements = {k: 'true' for k in steps.FLAGS}
        selected_skills = list(skills.SUITES)
    paths = diff.get('paths', [])
    site = bool(reasons) or requirements['build-site'] == 'true'
    try:
        readers=legacy_readers(root,paths) if not reasons else {'rust','web-test'}
        toolkit=bool(reasons) or 'rust' in legacy_readers(root,paths,step='toolkit')
    except Exception as error:
        reasons=[{'code':'selector_error','detail':text(error)}]
        chosen=set(inventory)
        requirements={k:'true' for k in steps.FLAGS}
        selected_skills=list(skills.SUITES)
        site=True
        readers={'rust','web-test'}
        toolkit=True
    release = bool(reasons) or site or bool(readers & {'rust','web-test'})
    # The whole checks binary is in the always lane (architecture, privacy,
    # contract/static checks and pending markers), exactly once in every run.
    rust_all = [t for t in inventory if t.startswith('rust:') and t != 'rust:test:checks']
    web_all = [t for t in inventory if t.startswith('web:')]
    record = {'schema': 'openwiz.ci-selection.v1', 'run': run, 'diff': diff,
        'selection': {'mode': 'full', 'reasons': reasons} if reasons else {'mode': 'selected'},
        'builds': {'web_export': {'decision': 'run'} if requirements['build-web'] == 'true' else
                   {'decision': 'skip', 'reason': 'no selected test or web input needs the export'}},
        'lanes': {'always': {'decision': 'run', 'tests': ALWAYS, 'skipped': []},
            'rust': lane(rust_all, chosen), 'web': lane(web_all, chosen),
            'site': lane(SITE + RELEASE, (SITE if site else []) + (RELEASE if release else [])),
            'skills': [dict(skill=s, **lane(['skill:' + s], ['skill:' + s] if s in selected_skills else []))
                       for s in skills.SUITES]},
        'store': {'artifact': f"ci-selection-{run['attempt']}", 'file': 'ci-selection.json'}}
    errors = gate.escapes.refusals(json.dumps(record))
    if errors:
        raise ValueError('refused generated plan: ' + '; '.join(errors))
    dispatch = {k: requirements[k] == 'true' for k in steps.FLAGS}
    dispatch.update(skills=selected_skills,
        rust=record['lanes']['rust']['decision'] == 'run', web=record['lanes']['web']['decision'] == 'run',
        site=site, release=release, toolkit=toolkit,
        trace=job.traces(run['event'], 'refs/heads/' + run['base_branch'], paths),
        planted=job.plants(run['event'], paths, (root / 'ci/select/map.json').is_file()))
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
    record, dispatch = build(ROOT, run, live, Path.home() / '.cache/closedwiz-ci-select',
                             os.environ['GITHUB_REPOSITORY'])
    out = Path(argv[0]); out.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(record, indent=2) + '\n'
    (out / 'ci-selection.json').write_text(raw)
    dispatch['plan_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    (out / 'ci-dispatch.json').write_text(json.dumps(dispatch, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for key, value in dict(dispatch, **{'site-in-release': combine_site_release(record)}).items():
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
