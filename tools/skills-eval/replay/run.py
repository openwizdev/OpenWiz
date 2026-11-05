#!/usr/bin/env python3
"""Offline paired replay preparation and event checkpoints; never launches reviewers.

Only the controller reads Git. Reviewer tools consume copied, hash-verified text
through an exact list/read protocol, with no shell, filesystem or network tool.
A manifest is a reservation for an independently isolated orchestrator transport,
not execution authority. Real source/isolation and upstream evidence review stay
with EB7; fixtures do not establish them.
"""
import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('replay_contract', HERE.parents[1] / 'factory-metrics/experiment_contract.py')
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
ARMS = C.ARMS
SCHEMA = 'openwiz.replay.checkpoint.v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def code_hash():
    paths = {'run.py': HERE / 'run.py', 'score.py': HERE / 'score.py',
             'experiment_contract.py': Path(C.__file__), 'journey.py': Path(C.J.__file__),
             'metrics.py': Path(C.J.M.__file__)}
    return C.digest({name: sha(path.read_bytes()) for name, path in paths.items()})


def context_digest(row):
    """Bind the exact original revisions, ordered material list and tool rights."""
    return C.digest({'base': row['base'], 'head': row['head'],
                     'materials': row['context']['materials'], 'tools': ['list', 'read']})


class GitSource:
    """Controller-only source: exact objects, never refs or the working tree."""
    def __init__(self, repo):
        self.repo = Path(repo).resolve(strict=True)
        self.git = shutil.which('git')
        C.require(self.git is not None, 'Git unavailable')
        # Locate object storage without invoking Git in the source repository:
        # even rev-parse there would parse its local config and includes.
        marker = self.repo / '.git'
        if marker.is_file():
            pointer = marker.read_text().strip()
            C.require(pointer.startswith('gitdir: ') and '\n' not in pointer, 'invalid Git directory pointer')
            git_dir = (self.repo / pointer[8:]).resolve(strict=True)
        elif marker.is_dir():
            git_dir = marker.resolve(strict=True)
        else:
            git_dir = self.repo  # Explicit bare object source.
        common_file = git_dir / 'commondir'
        if common_file.exists():
            pointer = common_file.read_text().strip()
            C.require(pointer and '\n' not in pointer, 'invalid common Git directory pointer')
            common = (git_dir / pointer).resolve(strict=True)
        else:
            common = git_dir
        self.objects = (common / 'objects').resolve(strict=True)
        C.require(self.objects.is_dir(), 'Git object storage unavailable')
        C.require(not (common / 'info/grafts').exists(), 'grafted history is not an original snapshot')
        self.attributes = common / 'info/attributes'
        C.require(not self.attributes.exists(), 'unversioned info/attributes can alter original diff')

    def _git(self, *args):
        env = {'PATH': os.defpath, 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_NO_REPLACE_OBJECTS': '1',
               'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_ATTR_NOSYSTEM': '1',
               'GIT_OBJECT_DIRECTORY': str(self.objects)}
        try:
            # Only object storage is shared. No source config, refs, index,
            # worktree, hooks or includes enter this controlled bare repository.
            with tempfile.TemporaryDirectory(prefix='openwiz-replay-git-') as directory:
                control = Path(directory)
                (control / 'refs').mkdir(); (control / 'objects').mkdir()
                (control / 'HEAD').write_text('ref: refs/heads/unused\n')
                (control / 'config').write_text('[core]\n    repositoryformatversion = 0\n    bare = true\n')
                result = subprocess.run([self.git, '--no-pager', '--literal-pathspecs',
                                         '--git-dir=' + directory,
                                         '-c', 'core.attributesFile=/dev/null', *args],
                                        env=env, capture_output=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('original Git object unavailable') from error
        return result.stdout

    def tree(self, commit):
        C.hex_value(commit, 40, 'original commit')
        C.require(self._git('cat-file', '-t', commit) == b'commit\n', 'snapshot is not a commit')
        tree = self._git('rev-parse', '--verify', commit + '^{tree}').decode().strip()
        C.hex_value(tree, 40, 'original tree')
        C.require(self._git('cat-file', '-t', tree) == b'tree\n', 'snapshot tree unavailable')
        return tree

    def read(self, commit, path):
        self.tree(commit)
        C.require(type(path) is str and path and '\x00' not in path and '\n' not in path,
                  'invalid original path')
        parts = path.split('/')
        C.require(all(p not in ('', '.', '..', '.git') for p in parts) and
                  not PurePosixPath(path).is_absolute(), 'invalid original path')
        entry = self._git('ls-tree', '-z', commit, '--', path)
        parts = entry.rstrip(b'\x00').split(b'\t')
        C.require(len(parts) == 2 and parts[1] == path.encode(), 'original file unavailable')
        meta = parts[0].split()
        C.require(len(meta) == 3 and meta[0] in (b'100644', b'100755') and meta[1] == b'blob',
                  'original material must be a regular blob')
        return self._git('cat-file', 'blob', meta[2].decode())

    def diff(self, base, head):
        C.require(not self.attributes.exists(), 'unversioned info/attributes can alter original diff')
        self.tree(base); self.tree(head)
        return self._git('--attr-source=' + head, 'diff', '--binary', '--full-index', '--no-ext-diff', '--no-textconv',
                         '--no-renames', '--no-color', '--no-relative', '--no-indent-heuristic',
                         '--diff-algorithm=myers', '--unified=3', '--src-prefix=a/',
                         '--dst-prefix=b/', base, head, '--')


def prepare(document, journey, source, selectors, skill_paths):
    """Resolve a frozen, unattempted manifest. Return private controller state.

    Selectors map declared hashes to {kind,path,revision}; no arbitrary path is
    ever interpreted by reviewer tools. The declared context hash must follow
    context_digest. Each frozen skill's commit/tree and actual bytes must match.
    """
    document, journey = copy.deepcopy(document), copy.deepcopy(journey)
    C.validate(document, journey)
    replay = document['replay']
    C.require(replay is not None and replay['started_at'] is None and replay['completed_at'] is None,
              'prepare requires an unattempted frozen replay')
    C.require(replay['selection'] == 'pending', 'candidate decision belongs to the real replay')
    C.fields(skill_paths, 'old candidate', 'skill paths')
    C.require(type(selectors) is dict, 'invalid material selectors')
    C.require(set(selectors) == {m['hash'] for row in replay['cohort'] for m in row['context']['materials']},
              'unknown or missing material selector')
    bundles = {}
    for row in replay['cohort']:
        C.require(row['context']['isolation'] == 'verified', 'isolation unavailable; not run')
        source.tree(row['base']); source.tree(row['head'])
        C.require(context_digest(row) == row['context_hash'], 'context manifest hash mismatch')
        materials = {}
        for item in row['context']['materials']:
            selector = selectors.get(item['hash'])
            C.fields(selector, 'kind path revision', 'material selector')
            C.require(selector['kind'] == item['kind'], 'material kind mismatch')
            if item['kind'] == 'original-diff':
                C.require(selector['path'] is None and selector['revision'] is None, 'diff selector mismatch')
                data = source.diff(row['base'], row['head'])
            else:
                C.require(selector['revision'] in (row['base'], row['head']), 'material outside original snapshot')
                data = source.read(selector['revision'], selector['path'])
            C.require(sha(data) == item['hash'], 'material byte hash mismatch')
            C.require(item['hash'] not in materials, 'duplicate material')
            materials[item['hash']] = data.decode('utf-8')
        for name in ARMS:
            arm = row['arms'][name]
            C.require(arm['status'] == 'not_run' and arm['finished_at'] is None,
                      'prepare cannot retry a previous attempt')
            revision = document['experiment']['arms'][name]['revision']
            C.require(source.tree(revision['commit']) == revision['tree'], 'skill tree mismatch')
            skill = source.read(revision['commit'], skill_paths[name])
            C.require(sha(skill) == arm['skill_hash'], 'skill byte hash mismatch')
            C.require(sha(skill) != row['context']['sealed_key_hash'], 'sealed answer key leaked as skill')
            bundles[arm['run_key']] = {'run_key': arm['run_key'], 'context_key': arm['context_key'],
                'base': row['base'], 'head': row['head'], 'context_hash': row['context_hash'],
                'settings': copy.deepcopy(document['experiment']['replay_settings']),
                'skill': skill.decode('utf-8'), 'materials': copy.deepcopy(materials),
                'descriptors': [{'hash': m['hash'], **copy.deepcopy(selectors[m['hash']])}
                                for m in row['context']['materials']]}
    state = {'schema': SCHEMA, 'code_hash': code_hash(),
             'input_hash': C.digest([document, journey, selectors]), 'initial': copy.deepcopy(document),
             'document': document, 'journey': journey, 'selectors': copy.deepcopy(selectors), 'bundles': bundles,
             'reservations': [], 'receipts': {}, 'blind_secret': secrets.token_hex(32)}
    validate_state(state)
    return state


def tool(bundle, request):
    """The complete reviewer tool protocol. No path expansion or host access."""
    C.require(type(request) is dict and type(request.get('op')) is str, 'invalid scoped tool')
    if request['op'] == 'list':
        C.fields(request, 'op', 'list request')
        return {'materials': copy.deepcopy(bundle['descriptors']), 'skill': 'skill'}
    C.require(request['op'] == 'read', 'scoped tool refused')
    C.fields(request, 'op name', 'read request')
    C.require(type(request['name']) is str, 'invalid scoped name')
    if request['name'] == 'skill': return bundle['skill']
    C.require(request['name'] in bundle['materials'], 'material outside allowlisted bundle')
    descriptor = next((d for d in bundle['descriptors'] if d['hash'] == request['name']), None)
    C.require(descriptor is not None, 'missing material descriptor')
    return {'material': copy.deepcopy(descriptor), 'text': bundle['materials'][request['name']]}


def validate_state(state):
    C.fields(state, 'schema code_hash input_hash initial document journey selectors bundles reservations receipts blind_secret', 'checkpoint')
    C.require(state['schema'] == SCHEMA and state['code_hash'] == code_hash(), 'checkpoint schema/harness changed')
    C.require(C.digest([state['initial'], state['journey'], state['selectors']]) == state['input_hash'], 'frozen input changed')
    C.validate_transition(state['initial'], state['document'], state['journey'])
    C.hex_value(state['blind_secret'], 64, 'blind secret')
    C.require(type(state['bundles']) is dict and type(state['receipts']) is dict, 'invalid checkpoint maps')
    keys = set()
    for row in state['document']['replay']['cohort']:
        C.require(context_digest(row) == row['context_hash'], 'changed context manifest')
        for name in ARMS:
            arm = row['arms'][name]; key = arm['run_key']; keys.add(key)
            b = state['bundles'].get(key)
            C.fields(b, 'run_key context_key base head context_hash settings skill materials descriptors', 'bundle')
            C.require(b['run_key'] == key and b['context_key'] == arm['context_key'] and
                      b['base'] == row['base'] and b['head'] == row['head'] and
                      b['context_hash'] == row['context_hash'], 'bundle binding mismatch')
            C.require(b['settings'] == state['document']['experiment']['replay_settings'], 'settings changed')
            C.require(type(b['skill']) is str and sha(b['skill'].encode()) == arm['skill_hash'], 'skill changed')
            C.require(type(b['materials']) is dict and set(b['materials']) ==
                      {m['hash'] for m in row['context']['materials']}, 'material coverage changed')
            expected_descriptors = []
            for material in row['context']['materials']:
                selector = state['selectors'].get(material['hash'])
                C.fields(selector, 'kind path revision', 'frozen selector')
                expected_descriptors.append({'hash': material['hash'], **selector})
            C.require(b['descriptors'] == expected_descriptors, 'material descriptor changed')
            for digest, data in b['materials'].items():
                C.require(type(data) is str and sha(data.encode()) == digest, 'material bytes changed')
    C.require(set(state['bundles']) == keys, 'bundle coverage mismatch')
    reserved = set()
    for reservation in C.array(state['reservations'], 'reservations'):
        C.fields(reservation, 'run_key at', 'reservation')
        key = reservation['run_key']; C.time(reservation['at'])
        C.require(key in keys and key not in reserved, 'duplicate/unknown reservation'); reserved.add(key)
    C.require(set(state['receipts']) <= reserved, 'unreserved receipt')
    for row in state['document']['replay']['cohort']:
        for arm in row['arms'].values():
            key = arm['run_key']; receipt = state['receipts'].get(key)
            C.require((arm['finished_at'] is not None) == (receipt is not None), 'terminal receipt missing')
            if receipt is None: continue
            C.fields(receipt, 'status report at', 'receipt')
            C.require(receipt['status'] == arm['status'] and receipt['at'] == arm['finished_at'], 'receipt changed')
            at = next(r['at'] for r in state['reservations'] if r['run_key'] == key)
            C.require(C.time(receipt['at']) >= C.time(at), 'receipt before reservation')
            if receipt['status'] == 'complete':
                C.require(type(receipt['report']) is str and sha(receipt['report'].encode()) == arm['report_hash'],
                          'review bytes changed')
            else: C.require(receipt['report'] is None, 'incomplete receipt has report')


def write_json(path, value):
    """Durably replace private state before any work can be handed out."""
    fd, tmp = tempfile.mkstemp(prefix='.checkpoint-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'checkpoint.json'

    @classmethod
    def create(cls, root, state):
        validate_state(state)
        root = Path(root)
        root.mkdir(mode=0o700)  # Exclusive creation: never overwrite another run.
        write_json(root / 'checkpoint.json', state)

    @contextmanager
    def locked(self):
        C.require(not self.root.is_symlink(), 'symlink checkpoint root')
        info = self.root.stat()
        C.require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, 'checkpoint must be owner-only')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error: raise ValueError('checkpoint busy; end turn') from error
            yield
        finally: os.close(fd)

    def _read(self):
        C.require(not self.path.is_symlink(), 'symlink checkpoint')
        state = C.read(self.path)
        validate_state(state)
        return state

    def read(self):
        with self.locked(): return self._read()

    def _save(self, before, after):
        validate_state(after)
        C.validate_transition(before['document'], after['document'], before['journey'])
        C.require(after['reservations'][:len(before['reservations'])] == before['reservations'] and
                  all(after['receipts'].get(k) == v for k, v in before['receipts'].items()),
                  'immutable reservation/receipt changed')
        write_json(self.path, after)

    def reserve(self, document, journey, limit, at):
        """One bounded event, no dispatch/wait/retry loop; uncertain stays reserved."""
        C.integer(limit, 1); C.time(at)
        with self.locked():
            before = self._read(); state = copy.deepcopy(before)
            C.require(C.digest([document, journey, state['selectors']]) == state['input_hash'], 'manifest/rubric changed on resume')
            reserved = {r['run_key'] for r in state['reservations']}
            jobs = []
            for row in state['document']['replay']['cohort']:
                for arm in row['arms'].values():
                    key = arm['run_key']
                    if key in reserved or arm['finished_at'] is not None: continue
                    if len(jobs) >= limit: break
                    state['reservations'].append({'run_key': key, 'at': at})
                    jobs.append(copy.deepcopy(state['bundles'][key]))
            if jobs:
                replay = state['document']['replay']
                if replay['started_at'] is None: replay['started_at'] = at
                C.require(C.time(at) >= C.time(replay['started_at']), 'reservation before replay start')
                self._save(before, state)
            return {'schema': 'openwiz.replay.work.v1', 'authority': 'none',
                    'checkpoint_hash': C.digest(state), 'limit': limit, 'jobs': jobs}

    def receive(self, run_key, status, report, at):
        C.choice(status, ('complete', 'error', 'uncertain', 'not_run'), 'attempt outcome')
        C.time(at)
        if status == 'complete': C.text(report, 'review report')
        else: C.require(report is None, 'incomplete attempt has report')
        receipt = {'status': status, 'report': report, 'at': at}
        with self.locked():
            before = self._read(); state = copy.deepcopy(before)
            C.require(run_key in {r['run_key'] for r in state['reservations']}, 'unreserved result')
            if run_key in state['receipts']:
                C.require(state['receipts'][run_key] == receipt, 'terminal result changed; no retry')
                return
            for row in state['document']['replay']['cohort']:
                for arm in row['arms'].values():
                    if arm['run_key'] != run_key: continue
                    arm.update(status=status, finished_at=at,
                               report_hash=sha(report.encode()) if status == 'complete' else None,
                               reported_at=at if status == 'complete' else None)
            state['receipts'][run_key] = receipt
            self._save(before, state)

    @staticmethod
    def _row(state, pr):
        C.integer(pr, 1)
        matches = [row for row in state['document']['replay']['cohort'] if row['pr'] == pr]
        C.require(len(matches) == 1, 'unknown cohort PR')
        row = matches[0]
        C.require(all(a['finished_at'] is not None for a in row['arms'].values()),
                  'both paired attempts must be terminal before key release')
        return row

    @staticmethod
    def _blind_key(state, run_key):
        return hmac.new(bytes.fromhex(state['blind_secret']), run_key.encode(), hashlib.sha256).hexdigest()

    def blind(self, pr, sealed_key_path):
        """Scorer-only surface, never a reviewer bundle. No arm/routing identity."""
        state = self.read(); row = self._row(state, pr)
        # Deliberately read only after the paired terminal gate. One read supplies
        # both hashing and parsing, so a file change cannot switch key bytes.
        data = Path(sealed_key_path).read_bytes()
        C.require(sha(data) == row['context']['sealed_key_hash'], 'sealed key hash mismatch')
        def pairs(items):
            result = {}
            for key, value in items:
                C.require(key not in result, 'duplicate sealed key field')
                result[key] = value
            return result
        def constant(_): raise ValueError('nonfinite sealed key number')
        known = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
        expected = {f['id']: f['severity'] for f in row['known']}
        seen = set()
        for finding in C.array(known, 'sealed key'):
            C.fields(finding, 'id severity root_cause location', 'sealed finding')
            C.text(finding['id'], 'sealed finding id')
            C.require(finding['id'] not in seen and expected.get(finding['id']) == finding['severity'],
                      'sealed key finding mismatch')
            seen.add(finding['id'])
            C.text(finding['root_cause'], 'sealed root cause'); C.text(finding['location'], 'sealed location')
        C.require(seen == set(expected), 'sealed key coverage mismatch')
        reviews = [{'key': self._blind_key(state, a['run_key']), 'status': a['status'],
                    'report': state['receipts'][a['run_key']]['report']} for a in row['arms'].values()]
        return {'pr': pr, 'rubric': state['document']['replay']['rubric'],
                'known': known, 'reviews': sorted(reviews, key=lambda r: r['key'])}

    def adjudicate(self, pr, decisions, at, source):
        """Append a sourced blind snapshot of canonical root-cause/location ids.

        The independent adjudicator applies the frozen matching rubric; unmatched
        reports stay unresolved. Canonical duplicates refuse, never double-score.
        """
        C.time(at)
        with self.locked():
            before = self._read(); state = copy.deepcopy(before); row = self._row(state, pr)
            C.require(type(decisions) is dict, 'invalid blind decisions')
            complete = [a for a in row['arms'].values() if a['status'] == 'complete']
            C.require(set(decisions) == {self._blind_key(state, a['run_key']) for a in complete},
                      'blind decision coverage mismatch')
            for arm in complete:
                history = arm['adjudications']
                C.require(not history or C.time(at) > C.time(history[-1]['at']), 'duplicate/older scoring checkpoint')
                history.append({'at': at, 'source': source,
                                'findings': copy.deepcopy(decisions[self._blind_key(state, arm['run_key'])])})
            C.require(bool(complete), 'no complete review to adjudicate')
            self._save(before, state)

    def report(self):
        spec = importlib.util.spec_from_file_location('replay_score', HERE / 'score.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        state = self.read()
        return module.score(state['document'], state['journey'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='op', required=True)
    init = sub.add_parser('prepare')
    for option in ('document', 'journey', 'repo', 'selectors', 'skill-paths', 'state'):
        init.add_argument('--' + option, required=True)
    reserve = sub.add_parser('reserve')
    for option in ('document', 'journey', 'state', 'at'): reserve.add_argument('--' + option, required=True)
    reserve.add_argument('--limit', type=int, required=True)
    receive = sub.add_parser('receive')
    receive.add_argument('--state', required=True); receive.add_argument('--receipt', required=True)
    for name in ('blind', 'adjudicate', 'report'):
        p = sub.add_parser(name); p.add_argument('--state', required=True)
        if name != 'report': p.add_argument('--pr', type=int, required=True)
        if name == 'blind': p.add_argument('--sealed-key', required=True)
        if name == 'adjudicate':
            for option in ('decisions', 'at', 'source'): p.add_argument('--' + option, required=True)
    args = parser.parse_args()
    try:
        store = Store(args.state); output = None
        if args.op == 'prepare':
            Store.create(args.state, prepare(C.read(args.document), C.read(args.journey), GitSource(args.repo),
                         C.read(args.selectors), C.read(args.skill_paths)))
        elif args.op == 'reserve':
            output = store.reserve(C.read(args.document), C.read(args.journey), args.limit, args.at)
        elif args.op == 'receive':
            receipt = C.read(args.receipt)
            C.fields(receipt, 'run_key status report at', 'receipt event')
            store.receive(receipt['run_key'], receipt['status'], receipt['report'], receipt['at'])
        elif args.op == 'blind': output = store.blind(args.pr, args.sealed_key)
        elif args.op == 'adjudicate': store.adjudicate(args.pr, C.read(args.decisions), args.at, args.source)
        else: output = store.report()
        if output is not None: print(json.dumps(output, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        print(f'refused: {error}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
