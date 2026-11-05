#!/usr/bin/env python3
"""C12 switch gate: verify the whole C11 chain before any main batch admission.

Offline and finite. It reads the private C11 archive the orchestrator names,
this checkout's implementation files and C3's overload guard; it makes no
network call, writes nothing but C3's own pause state, cancels nothing and
admits no merge. The answer is `batch` only when the archive matches the
reviewed pin, the implementation is unchanged since the proof, no overload
pause applies and a supported admission mechanism is named in this file.
Anything else, including any doubt, is `per-push-full`: today's behaviour.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / '.github/actions/docs-only'))
sys.path.insert(0, str(ROOT / 'tools/ci-overload'))
import gate
from test_contract import coverage_refusals

escapes = gate.escapes
MAX_FILES = 1000
MAX_BYTES = 64 * 1024 * 1024
WORKFLOW = '.github/workflows/ci.yml'

# No mechanism the C6 contract accepts exists on this repository: no merge
# queue, and ordinary push coalescing is shadow observation only. Adding one
# here needs Jake's recorded decision on #2319; code cannot infer it (AC5).
SUPPORTED_MECHANISMS = ()

# The reviewed C11b chain (#2318, docs/evidence/ci2-batch-proof.md, APPROVE on
# #2482 at e735765f): the private archive's manifest digest, the batch and the
# retained nightly, and every coverage implementation file at candidate C.
PIN = dict(
    repository='jparker2006/ClosedWiz',
    manifest_sha256='18a6a889195bf1036ca643f77cb5c90924bf0e4806478718e78bdd7ab1598d04',
    base='d4431b827a318ef729b68c6c2edfc6889ef83c0f',
    head='057e0b219a6ed4449c9d09da70379569530e70bc',
    pull_requests=[2442, 2257],
    run=dict(id=43351370135, attempt=1),
    nightly=dict(id=43271573219, attempt=1, head='19cd51ce919602d6389fbd6aa83b197fb6753993'),
    blobs={
        'ci/main-batch/shadow.py': '1eaedd7c15c82f9f05ee9bb1c456d0718def245d',
        'ci/main-batch/test_contract.py': '4d90ae71f423ce107e7cdf52a4f17d5f95deabb7',
        'contracts/ci-main-batch.v1.schema.json': 'ea2430ec422710a9245894c1c99219e70d5464d1',
        'contracts/ci-main-batch.v1.md': '7aac7704c378b6fbfd1dea66e81100433a7463f6',
        'contracts/ci-selection.v1.schema.json': '6fd261eb1c1a35b1c5ab1c73e3d7ce3f979f8647',
        'ci/escapes/escapes.py': '2d0ee3bfcb0a2bd7b5469406deee6e04aed705c5',
        '.github/actions/docs-only/gate.py': '586dadb9d53029902694ebd3a293e683ed648c33',
        '.github/actions/docs-only/run.py': 'bb7431837beb6ede15ad53ada951ab393bd93da0',
        '.github/actions/docs-only/plan.py': '9373864f7fde9081ea9acfa762679672a64ab168',
        WORKFLOW: '3623ce9f2faaaefe60fe15e29b745bf6a43fd9a3',
    })


def need(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    need(not path.is_symlink() and path.is_file(), 'not a regular archive file: ' + path.name)
    return path


def manifest(archive, pin):
    """Every archive file, exactly as the reviewed manifest lists it."""
    raw = regular(archive / 'MANIFEST.sha256').read_bytes()
    need(len(raw) <= MAX_BYTES, 'manifest exceeds byte bound')
    need(hashlib.sha256(raw).hexdigest() == pin['manifest_sha256'], 'manifest differs from the reviewed pin')
    listed = {}
    for line in raw.decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  \./([^\0]+)', line)
        need(match, 'malformed manifest line')
        parts = match.group(2).split('/')
        need(all(p not in ('', '.', '..') for p in parts), 'manifest path escapes the archive')
        need(match.group(2) not in listed, 'duplicate manifest path')
        listed[match.group(2)] = match.group(1)
    need(0 < len(listed) <= MAX_FILES, 'manifest file bound')
    present = set()
    for folder, dirs, files in os.walk(archive):
        for name in dirs + files:
            need(not (Path(folder) / name).is_symlink(), 'symlink in archive: ' + name)
        present.update(str((Path(folder) / name).relative_to(archive)) for name in files)
    present.discard('MANIFEST.sha256')
    need(present == set(listed), 'archive files differ from the manifest')
    data, total = {}, 0
    for name, digest in listed.items():
        body = regular(archive / name).read_bytes()
        total += len(body)
        need(total <= MAX_BYTES, 'archive exceeds byte bound')
        need(hashlib.sha256(body).hexdigest() == digest, 'archive file differs from its manifest: ' + name)
        data[name] = body
    return data


def document(data, name):
    need(name in data, 'archive lacks ' + name)
    return escapes.strict_json(data[name].decode('utf-8'))


def member(data, name, inner=None):
    need(name in data, 'archive lacks ' + name)
    with zipfile.ZipFile(io.BytesIO(data[name])) as archive:
        names = archive.namelist()
        need(len(names) == len(set(names)), 'duplicate zip member')
        if inner is None:
            need(len(names) == 1, 'receipt artifact must hold one file')
            inner = names[0]
        info = archive.getinfo(inner)
        need(info.file_size <= MAX_BYTES, 'zip member exceeds byte bound')
        return archive.read(info).decode('utf-8')


def batch_refusals(data, pin):
    """C11's complete combined batch: report, state, context and coverage."""
    obs = 'observation/'
    need(data.get(obs + 'reconcile-rc') == b'rc=0\n', 'reconcile did not exit 0')
    report = document(data, obs + 'reconcile-report.json')
    context = document(data, obs + 'context.json')
    state = document(data, obs + 'state.json')
    need(report.get('complete') is True and report.get('outcome') == 'success'
         and report.get('refusals') == [] and report.get('switch_authorized') is False,
         'reconcile report is not one complete, unrefused shadow result')
    batch, execution = context['batch'], context['execution']
    need(report.get('batch') == batch and report.get('execution') == execution,
         'reconcile report and context differ')
    need(batch['repository'] == pin['repository'] and batch['base'] == pin['base']
         and batch['head'] == pin['head']
         and [m['pull_request'] for m in batch['members']] == pin['pull_requests'],
         'batch differs from the reviewed pin')
    need(execution['workflow'] == WORKFLOW and execution['id'] == pin['run']['id']
         and execution['attempt'] == pin['run']['attempt'], 'execution differs from the reviewed pin')
    inventory = document(data, obs + 'inventory.json')
    need(type(inventory) is list and sorted(inventory) == sorted(context['inventory']),
         'candidate inventory differs from the context')
    need(type(state) is dict and set(state) == {'repository', 'covered', 'pending', 'last'},
         'unexpected state fields')
    need(state['repository'] == pin['repository'] and state['covered'] == pin['head'],
         'state is not covered at the combined head')
    need(state['pending'] == [], 'pending members remain uncovered')
    errors = coverage_refusals(json.dumps(state['last']), context)
    need(not errors, 'coverage: ' + '; '.join(errors))


def nightly_refusals(data, pin):
    """The retained full nightly: its own plan, receipts, inventory and jobs."""
    obs, nz = 'observation/', 'observation/nightly-zips/'
    want = pin['nightly']
    need(want['head'] != pin['head'], 'nightly must not be the batch head')
    text = member(data, nz + 'ci-selection-1.zip', 'ci-selection.json')
    errors = escapes.refusals(text)
    need(not errors, 'nightly plan: ' + '; '.join(errors))
    plan = escapes.strict_json(text)
    run, lanes = plan['run'], plan['lanes']
    need(run['id'] == want['id'] and run['attempt'] == want['attempt'] and run['head'] == want['head']
         and run['event'] == 'schedule' and run['base'] is None and run['base_branch'] == 'main'
         and plan['selection'] == {'mode': 'full', 'reasons': [{'code': 'nightly'}]},
         'nightly plan is not the pinned full schedule run')
    groups = [lanes[k] for k in ('always', 'rust', 'web', 'site')] + lanes['skills']
    need(all(g['decision'] == 'run' and g['skipped'] == [] for g in groups)
         and plan['builds']['web_export']['decision'] == 'run', 'nightly plan skips work')
    tests = [t for g in groups for t in g['tests']]
    inventory = document(data, obs + 'nightly-inventory.json')
    need(len(tests) == len(set(tests)) and type(inventory) is list and sorted(tests) == sorted(inventory),
         'nightly plan differs from its inventory')
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    expected = {'always': lanes['always']['tests'], 'web': lanes['web']['tests'],
                'build:web_export': [], 'prerequisite:toolkit': []}
    for kind in ('site', 'release'):
        group = [t for t in lanes['site']['tests'] if t.startswith(kind + ':')]
        if group:
            expected[kind] = group
    expected.update({'skill:' + s['skill']: s['tests'] for s in lanes['skills']})
    receipts = {}
    for name in sorted(n for n in data if n.startswith(nz + 'lane-')):
        receipt = escapes.strict_json(member(data, name))
        need(type(receipt) is dict and receipt.get('lane') not in receipts, 'duplicate nightly receipt')
        receipts[receipt['lane']] = receipt
    need(set(receipts) == set(expected), 'missing or foreign nightly receipt')
    for lane, receipt in receipts.items():
        need(set(receipt) == {'lane', 'tests', 'plan_sha256', 'run'} and receipt['plan_sha256'] == digest
             and receipt['run'] == run and len(receipt['tests']) == len(set(receipt['tests']))
             and sorted(receipt['tests']) == sorted(expected[lane]),
             'nightly receipt does not bind the exact plan, run and tests: ' + lane)
    ran = Counter()
    for name in sorted(n for n in data if n.startswith(nz + 'rust-ran-')):
        ran.update(line for line in member(data, name).splitlines() if line)
    need(ran == Counter(lanes['rust']['tests']), 'nightly Rust shares do not hold each Rust test once')
    actual = document(data, obs + 'raw/14-runN.json')
    need(actual['id'] == want['id'] and actual['run_attempt'] == want['attempt']
         and actual['head_sha'] == want['head'] and actual['event'] == 'schedule'
         and actual['head_branch'] == 'main' and actual['path'] == WORKFLOW
         and actual['status'] == 'completed' and actual['conclusion'] == 'success',
         'nightly run is not the pinned successful schedule run')
    jobs = document(data, obs + 'raw/15-jobsN.json')
    need(jobs['total_count'] == len(jobs['jobs']), 'nightly job page is incomplete')
    need(all(j['status'] == 'completed' and j['conclusion'] in ('success', 'skipped') for j in jobs['jobs']),
         'nightly has unfinished, failed or cancelled jobs')
    need([j['conclusion'] for j in jobs['jobs'] if j['name'] in ('changes', 'ci')] == ['success'] * 2,
         'nightly changes and ci results are not each one success')


def blob_refusals(root, pin):
    """Candidate binding: the proof holds only for unchanged implementation."""
    refusals = []
    for path, blob in sorted(pin['blobs'].items()):
        target = Path(root) / path
        try:
            data = regular(target).read_bytes()
        except (OSError, ValueError):
            refusals.append('implementation file missing since the proof: ' + path)
            continue
        if hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest() != blob:
            refusals.append('implementation changed since the proof: ' + path)
    return refusals


def chain_refusals(archive, pin, root):
    """Every reason the C11 chain does not verify here; empty only if it all does."""
    refusals = []
    try:
        data = manifest(Path(archive), pin)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, escapes.Fail) as error:
        return ['archive: ' + str(error)] + blob_refusals(root, pin)
    for part in (batch_refusals, nightly_refusals):
        try:
            part(data, pin)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError,
                RecursionError, zipfile.BadZipFile, escapes.Fail) as error:
            refusals.append(part.__name__.split('_')[0] + ': ' + str(error))
    return refusals + blob_refusals(root, pin)


def decide(chain, overload, mechanism=None):
    """`batch` needs a verified chain, no pause and a supported mechanism."""
    refusals = list(chain)
    if type(overload) is not dict or overload.get('allowed') is not True or overload.get('paused') is not False:
        refusals.append('overload pause applies or is unknown: no new merge batch')
    if mechanism not in SUPPORTED_MECHANISMS:
        refusals.append('no supported admission mechanism: per-push full work stays (stop for Jake)')
    return dict(admission='per-push-full' if refusals else 'batch', refusals=refusals,
                admitted_work='unchanged: nothing is cancelled and admitted work finishes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--overload-input', required=True, type=Path)
    parser.add_argument('--overload-state', required=True, type=Path)
    parser.add_argument('--now', type=int)
    parser.add_argument('--max-age', type=int, default=60)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('invalid repository')
    import alarm
    now = args.now if args.now is not None else int(alarm.time.time())
    overload = alarm.decision(SimpleNamespace(repository=args.repository, input=args.overload_input,
                                              state=args.overload_state, now=now,
                                              max_age=args.max_age, action='merge-batch'))
    chain = chain_refusals(args.archive, PIN, ROOT)
    if args.repository != PIN['repository']:
        chain.insert(0, 'repository differs from the reviewed pin')
    result = decide(chain, overload)
    print(json.dumps(dict(result, overload=overload), sort_keys=True))
    return 0 if result['admission'] == 'batch' else 1


if __name__ == '__main__':
    sys.exit(main())
