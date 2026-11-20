#!/usr/bin/env python3
"""Finite C7 evidence capture and independently reconciled shadow coverage.

Capture is local and always incomplete. Reconcile reads GitHub only when
explicitly invoked under the separate C11 authority; it never admits work.
"""
import argparse
import contextlib
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / '.github/actions/docs-only'))
import run as executor
from test_contract import coverage_refusals

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 4
MAX_READS = 128
MAX_MEMBERS = 16
strict_json = executor.gate.escapes.strict_json


def need(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, keys):
    need(type(value) is dict and set(value) == set(keys.split()), 'unexpected evidence fields')


def positive(value):
    need(type(value) is int and value > 0, 'positive nonempty integer ID required')
    return value


def load(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    need(len(raw) <= MAX_BYTES, 'evidence exceeds byte bound')
    return strict_json(raw.decode('utf-8'))


def atomic(path, value):
    """Private local state only. A completed proof is saved with its checkpoint."""
    path = Path(path)
    raw = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    need(len(raw) <= MAX_BYTES, 'state exceeds byte bound')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.shadow-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def counted(gh, path, key):
    rows, total = [], None
    for page in range(1, MAX_PAGES+1):
        answer = gh.get(path+f'&page={page}')
        count, block = answer.get('total_count'), answer.get(key)
        need(type(count) is int and 0 <= count <= MAX_PAGES*100 and type(block) is list,
             'unreadable or oversized pagination')
        need(total is None or count == total, 'pagination changed')
        total = count
        need(len(block) <= 100 and (block or len(rows) == total), 'partial pagination')
        rows.extend(block)
        need(len(rows) <= total, 'pagination exceeds total')
        if len(rows) == total:
            return rows
    raise ValueError('pagination bound reached')


class BranchNotProtected(ValueError):
    """GitHub's exact 404 answer for a branch without legacy protection."""


class GitHub:
    """Existing gh authentication, GET only, no retries, cache or token changes."""
    def __init__(self, repository):
        need(type(repository) is str and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository),
             'repository identity required')
        self.repository, self.reads = repository, 0
        self.deadline = time.monotonic()+600

    def raw(self, path):
        need(type(path) is str and not path.startswith(('/', '-')) and '..' not in path
             and not any(c in path for c in ('\n', '\r', '#', ':')), 'unsafe read path')
        self.reads += 1
        need(self.reads <= MAX_READS, 'read bound reached')
        remaining = self.deadline-time.monotonic()
        need(remaining > 0, 'finite observation time bound reached')
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
            f'repos/{self.repository}'+('/'+path if path else '')], capture_output=True, timeout=min(15, remaining))
        need(len(result.stdout) <= MAX_BYTES, 'API response exceeds byte bound')
        if result.returncode != 0:
            answer = None
            with contextlib.suppress(ValueError, UnicodeDecodeError, RecursionError):
                answer = strict_json(result.stdout.decode('utf-8'))
            if (type(answer) is dict and answer.get('status') == '404'
                    and answer.get('message') == 'Branch not protected'):
                raise BranchNotProtected(path)
            raise ValueError('GitHub read failed; no fallback or retry')
        return result.stdout

    def get(self, path):
        return strict_json(self.raw(path).decode('utf-8'))

    def packet(self, rid, attempt, head):
        positive(rid); positive(attempt)
        name = f'main-shadow-{attempt}'
        rows = counted(self, f'actions/runs/{rid}/artifacts?per_page=100', 'artifacts')
        found = [row for row in rows if row.get('name') == name]
        need(len(found) == 1, 'missing or duplicate shadow artifact')
        artifact = found[0]
        need(artifact.get('expired') is False and type(artifact.get('size_in_bytes')) is int
             and 0 < artifact['size_in_bytes'] <= MAX_BYTES, 'expired or oversized shadow artifact')
        association = artifact.get('workflow_run', {})
        need(association.get('id') == rid and association.get('head_sha') == head,
             'artifact association differs from current execution')
        raw = self.raw(f"actions/artifacts/{positive(artifact.get('id'))}/zip")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            need(archive.namelist() == ['observation.json'], 'unexpected artifact members')
            need(archive.getinfo('observation.json').file_size <= MAX_BYTES, 'expanded artifact bound')
            return strict_json(archive.read('observation.json').decode('utf-8'))


def capture(folder, needs, receipts, destination):
    """Preserve the exact finish inputs; never claim a terminal ci outcome."""
    with contextlib.redirect_stdout(io.StringIO()):
        executor.finish(folder, needs, receipts)
    plan, _ = executor.load(folder)
    event = load(os.environ['GITHUB_EVENT_PATH'])
    binding = executor.planner.run_context(os.environ, event)
    need(binding == plan['run'] and binding['event'] in ('push', 'merge_group')
         and binding['base_branch'] == 'main' and plan['selection']['mode'] == 'full',
         'capture needs exact full combined main event')
    repository = event.get('repository', {}).get('full_name')
    need(repository == os.environ['GITHUB_REPOSITORY'], 'event repository differs')
    if binding['event'] == 'push':
        need(event.get('after') == binding['head'] and event.get('ref') == 'refs/heads/main',
             'push association differs')
    shares = []
    for path in sorted((Path(receipts).parent/'rust-ran').glob('ran-*.txt')):
        match = re.fullmatch(r'ran-([1-9][0-9]*)\.txt', path.name)
        need(match is not None, 'unknown Rust share file')
        need(path.stat().st_size <= MAX_BYTES, 'Rust share byte bound')
        shares.append(dict(shard=int(match[1]), tests=path.read_text().split()))
    rust_job = [name for name in ('rust',) if load(needs).get(name, {}).get('result') == 'success']
    need(len(rust_job) == 1, 'unknown active Rust job')
    validate_shares(shares, plan['lanes']['rust']['tests'])
    packet = dict(plan=(Path(folder)/'ci-selection.json').read_bytes().decode('utf-8'),
        receipts=[load(path) for path in sorted(Path(receipts).glob('*.json'))],
        event=dict(repository=repository, run=binding), rust=dict(job=rust_job[0], shares=shares),
        complete=False, reason='terminal checks pending')
    atomic(destination, packet)
    return packet


def inventory_at_candidate(head):
    """Use the trusted candidate planner's inventory, never the evidence's list."""
    actual = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain=v1'], text=True)
    need(actual == head and not dirty, 'standalone reader requires the clean exact candidate checkout')
    planner = executor.planner
    units = planner.units.list_units(ROOT)
    return sorted(planner.ALWAYS + [t for t in units if t != 'rust:test:checks']
                  + planner.SITE + planner.RELEASE + ['skill:'+s for s in planner.skills.SUITES])


def graph(gh, context):
    batch = context['batch']
    need(gh.get('').get('full_name') == batch['repository'], 'canonical repository differs')
    for member in batch['members']:
        commit = gh.get('commits/'+member['merge'])
        parents = commit.get('parents')
        need(commit.get('sha') == member['merge'] and type(parents) is list and len(parents) == 2
             and [p.get('sha') for p in parents] == [member['parent'], member['head']],
             'unknown main merge association or first-parent gap')
        pr = gh.get('pulls/'+str(positive(member['pull_request'])))
        need(type(pr.get('number')) is int and pr['number'] == member['pull_request'] and pr.get('merged') is True
             and pr.get('merge_commit_sha') == member['merge'] and pr.get('head', {}).get('sha') == member['head']
             and pr.get('base', {}).get('ref') == 'main'
             and pr.get('base', {}).get('repo', {}).get('full_name') == batch['repository'],
             'unknown merged PR association')


def protection(gh):
    try:
        legacy = gh.get('branches/main/protection/required_status_checks')
    except BranchNotProtected:
        # Ruleset-only main: an empty legacy set. Rules below must still require ci.
        legacy = dict(contexts=[], checks=[])
    names, apps = set(), {}
    need(type(legacy.get('contexts')) is list and type(legacy.get('checks')) is list,
         'unreadable legacy required checks')
    names.update(legacy['contexts'])
    entries = list(legacy['checks'])
    for page in range(1, MAX_PAGES+1):
        rules = gh.get(f'rules/branches/main?per_page=100&page={page}')
        need(type(rules) is list and len(rules) <= 100, 'unreadable effective branch rules')
        for rule in rules:
            if rule.get('type') == 'required_status_checks':
                checks = rule.get('parameters', {}).get('required_status_checks')
                need(type(checks) is list, 'unreadable effective required checks')
                entries.extend(dict(context=c['context'], app_id=c.get('integration_id')) for c in checks)
            else:
                need(rule.get('type') in ('creation', 'update', 'deletion', 'non_fast_forward',
                    'required_linear_history', 'required_signatures', 'pull_request',
                    'required_deployments', 'merge_queue', 'code_scanning', 'max_file_path_length',
                    'file_path_restriction', 'file_extension_restriction', 'max_file_size'),
                    'unsupported protection rule; stop for disposition')
        if len(rules) < 100:
            break
    else:
        raise ValueError('effective rule pagination bound')
    for entry in entries:
        name, app = entry.get('context'), entry.get('app_id')
        need(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.:-]+', name), 'required check name')
        need(app is None or type(app) is int and app > 0, 'required check application')
        names.add(name)
        if app is not None:
            need(name not in apps or apps[name] == app, 'conflicting required check applications')
            apps[name] = app
    need(names and 'ci' in names, 'ci is not in complete protection inputs')
    return sorted(names), apps


def current_run(gh, rid, attempt, head, repository, event=None):
    run = gh.get(f'actions/runs/{positive(rid)}')
    need(type(run.get('id')) is int and type(run.get('run_attempt')) is int
         and run['id'] == rid and run['run_attempt'] == attempt and type(attempt) is int
         and run.get('head_sha') == head and run.get('head_branch') == 'main'
         and run.get('repository', {}).get('full_name') == repository
         and run.get('event') in ('push', 'merge_group') and (event is None or run['event'] == event),
         'run identity or current attempt differs')
    need(run.get('status') == 'completed' and run.get('conclusion') == 'success',
         'current workflow is unfinished or unsuccessful')
    wid = positive(run.get('workflow_id'))
    rows = counted(gh, f'actions/workflows/{wid}/runs?head_sha={head}&per_page=100', 'workflow_runs')
    for row in rows:
        need(type(row) is dict and type(row.get('id')) is int and row['id'] > 0
             and row.get('head_sha') == head and type(row.get('event')) is str
             and type(row.get('head_branch')) is str, 'unreadable current-run association')
    matching = [r for r in rows if r['event'] == run['event'] and r['head_branch'] == 'main']
    need(matching and max(r['id'] for r in matching) == rid
         and len({r['id'] for r in matching}) == len(matching), 'superseded or ambiguous execution')
    chosen = next(r for r in matching if r['id'] == rid)
    need(type(chosen.get('run_attempt')) is int and chosen['run_attempt'] == attempt,
         'run listing and independently read current attempt differ')
    return run


def jobs_for(gh, run, head):
    rows = counted(gh, f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100", 'jobs')
    seen = set()
    for row in rows:
        need(type(row) is dict and type(row.get('id')) is int and row['id'] > 0
             and row['id'] not in seen and row.get('run_id') == run['id']
             and row.get('run_attempt', run['run_attempt']) == run['run_attempt'] and row.get('head_sha') == head
             and type(row.get('name')) is str, 'job identity/attempt differs or is duplicated')
        seen.add(row['id'])
    return rows


def successful(job):
    need(job.get('status') == 'completed' and job.get('conclusion') == 'success',
         'required work is missing, pending, failed or cancelled')


def validate_shares(shares, inventory):
    need(type(shares) is list and 0 < len(shares) <= 100, 'missing Rust matrix shares')
    tests, numbers = [], []
    for share in shares:
        exact(share, 'shard tests')
        numbers.append(positive(share['shard']))
        need(type(share['tests']) is list and all(type(t) is str for t in share['tests']), 'invalid Rust share')
        tests.extend(share['tests'])
    need(sorted(numbers) == list(range(1, len(shares)+1)) and sorted(tests) == sorted(inventory)
         and len(set(tests)) == len(tests), 'incomplete or duplicate Rust matrix coverage')


def facts(gh, context, packet):
    graph(gh, context)
    head, execution = context['batch']['head'], context['execution']
    names, apps = protection(gh)
    need(names == sorted(c['name'] for c in context['required_checks']), 'required check inventory differs')
    run = current_run(gh, execution['id'], execution['attempt'], head,
                      context['batch']['repository'], execution['event'])
    need(run.get('path') == execution['workflow'], 'not the CI workflow')
    need(gh.packet(execution['id'], execution['attempt'], head) == packet,
         'packet differs from the authenticated current-attempt artifact')
    jobs = jobs_for(gh, run, head)
    by_name = {}
    for job in jobs:
        need(job['name'] not in by_name, 'duplicate actual job name')
        by_name[job['name']] = job
    def one(name):
        need(name in by_name, 'missing actual job: '+name)
        successful(by_name[name])
        return by_name[name]
    for name in ('changes', 'always'):
        one(name)
    # #743: release and each sharded skill run as members 1 to N of a matrix.
    def members(prefix):
        names = [j['name'] for j in jobs if re.fullmatch(re.escape(prefix)+r' \([1-9][0-9]*\)', j['name'])]
        need(sorted(int(n[len(prefix)+2:-1]) for n in names) == list(range(1, len(names)+1)) and names,
             'missing '+prefix+' matrix member')
        for name in names:
            one(name)
    members('release')
    plan = strict_json(packet['plan'])
    exact(packet['rust'], 'job shares')
    need(packet['rust']['job'] == 'rust', 'unknown Rust job')
    validate_shares(packet['rust']['shares'], plan['lanes']['rust']['tests'])
    rust = [j for j in jobs if re.fullmatch(r'rust \([1-9][0-9]*\)', j['name'])]
    need(rust, 'missing Rust matrix')
    prefix = packet['rust']['job']
    need({j['name'] for j in rust} == {f'{prefix} ({s["shard"]})' for s in packet['rust']['shares']},
         'missing or mixed Rust matrix member')
    for job in rust:
        successful(job)
    sharded = executor.planner.skills.SHARDED
    for skill in sorted({s['skill'] for s in plan['lanes']['skills']} & set(sharded)):
        members(skill)
    skills = {f"skills ({s['skill']})" for s in plan['lanes']['skills'] if s['skill'] not in sharded}
    need({j['name'] for j in jobs if j['name'].startswith('skills (')} == skills,
         'missing or foreign skill matrix member')
    for name in skills:
        one(name)
    checks, observed_runs = [], {run['id']}
    for check in context['required_checks']:
        cr = current_run(gh, check['id'], check['attempt'], head, context['batch']['repository'])
        cj = jobs if cr['id'] == run['id'] else jobs_for(gh, cr, head)
        found = [j for j in cj if j['name'] == check['name']]
        need(len(found) == 1, 'missing or ambiguous required check')
        successful(found[0])
        suite = gh.get(f"check-suites/{positive(cr.get('check_suite_id'))}")
        need(suite.get('head_sha') == head and (check['name'] not in apps
             or suite.get('app', {}).get('id') == apps[check['name']]), 'required check application differs')
        checks.append(dict(check, head=head, result='success'))
        if cr['id'] not in observed_runs:
            jobs.extend(cj); observed_runs.add(cr['id'])
    outcomes = [dict(name='changes', result='success')]
    outcomes += [dict(name=r['lane'], result='success') for r in packet['receipts']]
    return (dict(schema='openwiz.ci-main-batch.v1', batch=context['batch'], execution=execution,
                 plan=packet['plan'], receipts=packet['receipts'], outcomes=outcomes, checks=checks),
            jobs, (names, apps))


def measurement(context, jobs):
    sys.path.insert(0, str(ROOT/'tools/collector'))
    import required
    queues, ends = [], []
    for job in jobs:
        # A skipped row never queued; its placeholder clocks are not a wait.
        if (job.get('conclusion') != 'skipped' and job.get('created_at') is not None
                and job.get('started_at') is not None):
            seconds = (required.clock(job['started_at'])-required.clock(job['created_at'])).total_seconds()
            need(seconds >= 0, 'reversed job queue clock')
            queues.append(seconds)
        is_required = any(c['name'] == job['name'] and c['id'] == job['run_id'] for c in context['required_checks'])
        if is_required and job.get('completed_at') is not None:
            required.clock(job['completed_at']); ends.append(job['completed_at'])
    return dict(batch=dict(id=context['batch']['head'], base=context['batch']['base'],
        head=context['batch']['head'], members=[m['merge'] for m in context['batch']['members']],
        source='combined-shadow'), jobs=len(jobs), job_queue_seconds=required.summary(queues),
        required_result_at=max(ends) if ends else None, push_to_required_seconds=None,
        whole_bill_usd=None, gaps=['actual push timestamp and whole-bill cost require independent C4 evidence'])


def reconcile(gh, packet, context, state, inventory):
    """Return a decision and next private local state; never write or admit CI."""
    next_state = copy.deepcopy(state)
    report = dict(complete=False, switch_authorized=False, outcome='incomplete', refusals=[],
                  measurement=None)
    try:
        exact(packet, 'plan receipts event rust complete reason')
        exact(packet['event'], 'repository run')
        need(packet['complete'] is False and packet['reason'] == 'terminal checks pending', 'capture claimed authority')
        schema = strict_json((HERE / 'fixtures/combined-coverage.schema.json').read_text())
        errors = executor.gate.escapes.errors_of(schema, schema['$defs']['context'], context, '$context')
        need(not errors, 'invalid independent C6 context')
        batch = context['batch']
        report.update(batch=copy.deepcopy(batch), execution=copy.deepcopy(context['execution']))
        need(0 < len(batch['members']) <= MAX_MEMBERS, 'batch member bound')
        exact(state, 'repository covered pending last')
        need(state['repository'] == batch['repository'] == packet['event']['repository'], 'repository differs')
        need(sorted(inventory) == sorted(context['inventory']), 'trusted candidate inventory differs')
        replay = state['covered'] == batch['head'] and state['last'] is not None
        need((state['covered'] == batch['base'] and context['previous_head'] == state['covered'])
             or (replay and state['last']['batch'] == batch), 'checkpoint overlap or gap')
        members = batch['members']
        parent = batch['base']
        for member in members:
            need(member['parent'] == parent and member['merge'] != parent, 'ordered batch has a gap or overlap')
            parent = member['merge']
        need(parent == batch['head'] and all(len({m[k] for m in members}) == len(members)
             for k in ('pull_request', 'head', 'merge')), 'ambiguous batch membership')
        need(type(state['pending']) is list and state['pending'] == members[:len(state['pending'])],
             'pending membership was shortened, reordered or replaced')
        binding = packet['event']['run']
        need(binding['head'] == batch['head'] and binding['base'] == context['execution']['event_base']
             and binding['base_branch'] == 'main' and binding['event'] == context['execution']['event']
             and binding['id'] == context['execution']['id'] and binding['attempt'] == context['execution']['attempt'],
             'independent event/run association differs')
        graph(gh, context)
        if not replay:
            next_state['pending'] = copy.deepcopy(members)
        document, jobs, protections = facts(gh, context, packet)
        errors = coverage_refusals(json.dumps(document), context)
        need(not errors, '; '.join(errors))
        second, second_jobs, second_protections = facts(gh, context, packet)
        need(second == document and second_jobs == jobs and second_protections == protections,
             'independent facts changed during reconciliation')
        if replay:
            need(state['last'] == document, 'competing covered history')
        report['measurement'] = measurement(context, jobs)
        next_state.update(covered=batch['head'], pending=[], last=copy.deepcopy(document))
        report.update(complete=True, outcome='success')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report['refusals'] = [str(error)]
    return report, next_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    cap = sub.add_parser('capture')
    for name in ('folder', 'needs', 'receipts', 'destination'):
        cap.add_argument(name, type=Path)
    read = sub.add_parser('reconcile', help='C11 separately authorized finite invocation only')
    for name in ('packet', 'context', 'state'):
        read.add_argument(name, type=Path)
    read.add_argument('--checkpoint', help='independently verified initial covered head; never inferred')
    args = parser.parse_args()
    try:
        if args.mode == 'capture':
            capture(args.folder, args.needs, args.receipts, args.destination)
            print('shadow: incomplete; terminal checks pending')
            return 0
        packet, context = load(args.packet), load(args.context)
        inventory = inventory_at_candidate(context['batch']['head'])
        # Nonblocking local lock. Busy/unknown state ends this finite pass.
        with args.state.with_suffix('.lock').open('a+b') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.state.exists():
                state = load(args.state)
            else:
                need(args.checkpoint == context['previous_head'], 'verified bootstrap checkpoint required')
                state = dict(repository=context['batch']['repository'], covered=args.checkpoint, pending=[], last=None)
            report, after = reconcile(GitHub(context['batch']['repository']), packet, context, state, inventory)
            atomic(args.state, after)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report['complete'] else 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError) as error:
        print('shadow: '+str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
