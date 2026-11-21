from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time

SCHEMA = 'openwiz.setup-state.v1'
KINDS = ('connect_app', 'prepare_project', 'activate_engine', 'configure_access')
PHASES = ('proposed', 'applied', 'refused', 'uncertain')
COMPONENTS = ('cloudroom', 'harness', 'personal_github', 'github_app', 'project', 'engine', 'remote_access')
MAX_OPERATIONS = 64
MAX_BYTES = 256 * 1024
TEXT = re.compile(r'[^\x00-\x1f\x7f-\x9f]{1,300}')
CODE = re.compile(r'[a-z][a-z_]{0,39}')
REPOSITORY = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}')
CLOUD_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
SETTING = re.compile(r'[A-Za-z0-9_.:/-]{1,128}')
CREDENTIAL = re.compile(r'(?<![A-Za-z0-9])(?:gh[pousr]_|github_pat_|sk-|xox[abprs]-|AKIA|eyJ)')
LOGIN = re.compile(r'[A-Za-z0-9-]{1,39}')
SELECTED = ('app', 'personal_login', 'unselected')
APP_CHOICES = ('create', 'reuse', 'skip', 'undecided')


class Refused(Exception):
    pass


class Superseded(Exception):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'setup state has a duplicate key')
        result[key] = value
    return result


def positive(value):
    return type(value) is int and 0 < value < 2 ** 53


def text(value):
    return isinstance(value, str) and TEXT.fullmatch(value) is not None and value.strip() == value


def check_project(value):
    if value is None:
        return
    require(type(value) is dict and set(value) == {
        'repository', 'project', 'operator', 'service_issue', 'answer_thread',
        'harness', 'model', 'effort', 'runtime'}, 'invalid project settings')
    require(isinstance(value['repository'], str) and REPOSITORY.fullmatch(value['repository'])
            and value['repository'].split('/')[1] not in ('.', '..'), 'invalid repository')
    for key in ('project', 'answer_thread'):
        require(isinstance(value[key], str) and CLOUD_ID.fullmatch(value[key]), 'invalid CloudRoom id')
    require(text(value['operator']) and len(value['operator']) <= 100, 'invalid operator')
    require(positive(value['service_issue']), 'invalid service issue')
    for key in ('harness', 'model', 'effort'):
        require(isinstance(value[key], str) and SETTING.fullmatch(value[key])
                and not CREDENTIAL.search(value[key]), 'invalid agent setting')
    require(value['runtime'] is None or (isinstance(value['runtime'], str) and
            re.fullmatch(r'0\.[0-9]{1,10}\.[0-9]{1,10} [0-9a-f]{40}', value['runtime'])), 'invalid runtime pin')


def check_identity(value):
    if value is None:
        return
    require(type(value) is dict and set(value) == {'selected', 'app_choice', 'acting_login', 'repository'},
            'invalid identity choice')
    require(value['selected'] in SELECTED and value['app_choice'] in APP_CHOICES, 'invalid identity choice')
    require(isinstance(value['repository'], str) and REPOSITORY.fullmatch(value['repository'])
            and value['repository'].split('/')[1] not in ('.', '..'), 'invalid repository')
    skipped = value['selected'] == 'personal_login'
    require(skipped == (value['app_choice'] == 'skip'), 'only an explicit App skip selects the personal login')
    require((isinstance(value['acting_login'], str) and LOGIN.fullmatch(value['acting_login']) is not None)
            if skipped else value['acting_login'] is None, 'invalid acting login')


BRAIN = {'location', 'code_repository', 'code_visibility', 'brain_repository', 'brain_visibility',
         'visibility_basis', 'folder', 'setting', 'decision_repositories'}


def check_brain(value):
    if value is None:
        return
    require(type(value) is dict and set(value) == BRAIN, 'invalid brain reference')
    code, home = value['code_repository'], value['brain_repository']
    for name in (code, home):
        require(isinstance(name, str) and REPOSITORY.fullmatch(name) and name.split('/')[1] not in ('.', '..'),
                'invalid brain repository')
    require(value['folder'] == '.openwiz/brain' and value['setting'] == 'brain_location'
            and value['visibility_basis'] == 'github_repository_read'
            and value['brain_visibility'] == {'known': 'private'}, 'invalid brain reference')
    pair = value['decision_repositories']
    if value['location'] == 'in_repository':
        require(value['code_visibility'] == 'private' and code.lower() == home.lower() and pair is None,
                'an in-repository brain must be the private code repository')
    else:
        require(value['location'] == 'companion' and value['code_visibility'] == 'public'
                and code.lower() != home.lower(), 'a companion brain must be a separate repository for public code')
        role = lambda r: type(r) is dict and set(r) == {'owner', 'name'} and all(isinstance(v, str) for v in r.values())
        require(type(pair) is dict and set(pair) == {'public', 'private'} and role(pair['public'])
                and role(pair['private'])
                and f"{pair['public']['owner']}/{pair['public']['name']}".lower() == code.lower()
                and f"{pair['private']['owner']}/{pair['private']['name']}".lower() == home.lower(),
                'the decisions pair must match the companion brain')


def check_operation(value):
    require(type(value) is dict and set(value) == {
        'operation_id', 'kind', 'phase', 'fingerprint', 'effects', 'reason'}, 'invalid operation')
    require(isinstance(value['operation_id'], str) and re.fullmatch('[0-9a-f]{32}', value['operation_id']),
            'invalid operation id')
    require(value['kind'] in KINDS and value['phase'] in PHASES, 'invalid operation kind or phase')
    require(isinstance(value['fingerprint'], str) and re.fullmatch('[0-9a-f]{64}', value['fingerprint']),
            'invalid fingerprint')
    require(type(value['effects']) is list and 1 <= len(value['effects']) <= 8 and
            all(text(e) for e in value['effects']), 'invalid effects')
    require(text(value['reason']), 'invalid reason')


def validate(value):
    required = {'schema', 'revision', 'checks', 'project', 'app', 'observations', 'operations'}
    require(type(value) is dict and required <= set(value) <= required | {'engine', 'identity', 'brain'},
            'invalid setup state')
    require(value['schema'] == SCHEMA, 'unsupported setup state')
    require(type(value['revision']) is int and 0 <= value['revision'] < 2 ** 53, 'invalid revision')
    checks = value['checks']
    require(type(checks) is dict and set(checks) == {'started', 'committed'} and
            all(type(checks[k]) is int for k in checks) and
            0 <= checks['committed'] <= checks['started'] < 2 ** 53, 'invalid check generations')
    check_project(value['project'])
    check_identity(value.get('identity'))
    app = value['app']
    require(app is None or (type(app) is dict and set(app) == {'app_id', 'installation_id'} and
            positive(app['app_id']) and (app['installation_id'] is None or positive(app['installation_id']))),
            'invalid App ids')
    observations = value['observations']
    require(type(observations) is dict and set(observations) <= set(COMPONENTS), 'invalid observations')
    for item in observations.values():
        require(type(item) is dict and set(item) == {'code', 'revision', 'at'} and
                isinstance(item['code'], str) and CODE.fullmatch(item['code']) and
                type(item['revision']) is int and 0 <= item['revision'] < 2 ** 53 and positive(item['at']),
                'invalid observation')
    operations = value['operations']
    require(type(operations) is list and len(operations) <= MAX_OPERATIONS, 'invalid operations')
    for operation in operations:
        check_operation(operation)
    require(len({o['operation_id'] for o in operations}) == len(operations), 'duplicate operation id')
    check_brain(value.get('brain'))
    engine = value.get('engine')
    if engine is not None:
        require(type(engine) is dict and set(engine) == {'location','revision','runtime','operation_id','fingerprint','cost'}, 'invalid engine')
        require(engine['location'] in ('cloud','local') and type(engine['revision']) is int
                and 0 <= engine['revision'] < 2 ** 53, 'invalid engine selection')
        require(isinstance(engine['runtime'],str) and re.fullmatch(r'0\.[0-9]{1,10}\.[0-9]{1,10} [0-9a-f]{40}',engine['runtime']), 'invalid engine runtime')
        require(isinstance(engine['operation_id'],str) and re.fullmatch('[0-9a-f]{32}',engine['operation_id'])
                and isinstance(engine['fingerprint'],str) and re.fullmatch('[0-9a-f]{64}',engine['fingerprint']), 'invalid engine binding')
        require(any(o['operation_id'] == engine['operation_id'] and o['kind'] == 'activate_engine'
                    and o['fingerprint'] == engine['fingerprint'] for o in operations), 'missing engine operation')
        cost = engine['cost']
        if cost is not None:
            require(type(cost) is dict and set(cost) == {'source','provenance','credits','window_s','free_allowance','observed_at','allowance_at'}
                    and cost['source'] == 'cloudroom_usage' and cost['provenance'] in ('measured','estimated'), 'invalid engine cost')
            require(all(type(cost[k]) in (int,float) and abs(cost[k]) <= 1.7976931348623157e308 and math.isfinite(cost[k])
                        and (cost[k] > 0 if k == 'window_s' else cost[k] >= 0)
                        for k in ('credits','window_s','free_allowance'))
                    and all(type(cost[k]) is int and 0 <= cost[k] < 2 ** 53
                            for k in ('observed_at','allowance_at')), 'invalid engine measurement')
    return value


def empty():
    return {'schema': SCHEMA, 'revision': 0, 'checks': {'started': 0, 'committed': 0}, 'project': None, 'app': None,
            'observations': {}, 'operations': []}


def retained(operations, protected_engine=None):
    operations = list(operations)
    protected = ({protected_engine} if protected_engine is not None else
                 {o['operation_id'] for o in operations if o['kind'] == 'activate_engine'})
    while len(operations) >= MAX_OPERATIONS:
        for phases in (('applied', 'refused'), ('proposed',)):
            drop = next((o for o in operations if o['phase'] in phases
                         and o['operation_id'] not in protected), None)
            if drop is not None:
                operations.remove(drop)
                break
        else:
            raise Refused('too many unresolved setup operations; reconcile the uncertain ones first')
    return operations


def fingerprint(kind, request):
    data = json.dumps({'kind': kind, 'request': request}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode()).hexdigest()


def state_path(explicit):
    if explicit is not None:
        path = Path(explicit)
    elif os.environ.get('OPENWIZ_STATE_DIR'):
        path = Path(os.environ['OPENWIZ_STATE_DIR'])
    else:
        home = os.environ.get('HOME', '')
        require(Path(home).is_absolute(), 'no absolute HOME or OPENWIZ_STATE_DIR')
        xdg = os.environ.get('XDG_STATE_HOME', '')
        if os.uname().sysname == 'Darwin':
            path = Path(home) / 'Library/Application Support/openwiz'
        else:
            path = (Path(xdg) if xdg and Path(xdg).is_absolute() else Path(home) / '.local/state') / 'openwiz'
    require(path.is_absolute() and '..' not in path.parts, 'state directory must be absolute')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'state directory must not be a symlink')
        require(not (parent / '.git').exists(), 'state directory must be outside every repository')
        require(not ((parent / 'HEAD').exists() and ((parent / 'objects').exists() or (parent / 'config').exists())),
                'state directory must be outside every repository')
    return path


def private_directory(path, create):
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(path)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
            'setup state must be an owner-only directory')


class Store:
    def __init__(self, state_dir):
        self.state = state_path(state_dir)
        self.dir = self.state / 'setup'
        self.file = self.dir / 'state.json'

    def _read(self):
        try:
            fd = os.open(self.file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return empty()
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
                    and info.st_nlink == 1 and info.st_size <= MAX_BYTES, 'setup state file is unsafe')
            with os.fdopen(os.dup(fd), 'rb') as handle:
                data = handle.read(MAX_BYTES + 1)
        finally:
            os.close(fd)
        try:
            return validate(json.loads(data, object_pairs_hook=unique))
        except ValueError:
            raise Refused('setup state is not valid JSON')

    def read(self):
        if not self.dir.exists():
            return empty()
        private_directory(self.state, False)
        private_directory(self.dir, False)
        return self._read()

    @contextmanager
    def locked(self):
        private_directory(self.state, True)
        private_directory(self.dir, True)
        lock = os.open(self.dir / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                    'setup lock is unsafe')
            fcntl.flock(lock, fcntl.LOCK_EX)
            named = os.lstat(self.dir / '.lock')
            require((named.st_dev, named.st_ino) == (info.st_dev, info.st_ino),
                    'setup lock changed')
            yield
        finally:
            os.close(lock)

    def _write(self, path, value):
        data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        require(len(data) <= MAX_BYTES, 'setup state is too large')
        temporary = self.dir / f'.state.{secrets.token_hex(8)}.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        directory = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def update(self, change):
        with self.locked():
            value = self._read()
            result = change(value)
            validate(value)
            self._write(self.file, value)
            return result

    def activation_transaction(self, change, validator):
        with self.locked():
            value = self._read()
            path = self.dir / 'pc-activation.json'
            journal = None
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                pass
            else:
                try:
                    info = os.fstat(fd)
                    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                            and info.st_size <= MAX_BYTES, 'PC activation journal is unsafe')
                    with os.fdopen(os.dup(fd), 'rb') as handle:
                        journal = validator(json.loads(handle.read(MAX_BYTES + 1), object_pairs_hook=unique))
                finally:
                    os.close(fd)

            def save(record):
                validator(record)
                operation = record['operation']
                previous = next((o for o in value['operations']
                                 if o['operation_id'] == operation['operation_id']), None)
                require(previous is not None and previous['kind'] == 'activate_engine'
                        and previous['fingerprint'] == operation['fingerprint'],
                        'PC activation operation is missing or changed')
                require(previous['phase'] not in ('applied', 'refused')
                        or previous['phase'] == operation['phase'],
                        'PC activation conflicts with a terminal setup operation')
                previous.update(operation)
                validate(value)
                self._write(path, record)
                self._write(self.file, value)

            return change(value, journal, save)

    def propose(self, kind, request, effects, reason, current=lambda value: True):
        digest = fingerprint(kind, request)

        def change(value):
            for operation in reversed(value['operations']):
                if operation['kind'] != kind or operation['fingerprint'] != digest:
                    continue
                if operation['phase'] in ('proposed', 'uncertain'):
                    return dict(operation)
                if operation['phase'] == 'applied' and current(value):
                    return dict(operation)
            operation = {'operation_id': secrets.token_hex(16), 'kind': kind, 'phase': 'proposed',
                         'fingerprint': digest, 'effects': list(effects), 'reason': reason}
            value['operations'] = retained(value['operations'], (value.get('engine') or {}).get('operation_id')) + [operation]
            return dict(operation)
        return self.update(change)

    def authorized(self, value, operation_id, kind, request, current=lambda value: True):
        digest = fingerprint(kind, request)
        matches = [o for o in value['operations'] if o['operation_id'] == operation_id]
        require(len(matches) == 1, 'unknown setup operation; preview it first')
        operation = matches[0]
        require(operation['kind'] == kind and operation['fingerprint'] == digest,
                'the request changed since its preview; preview it again')
        require(operation['phase'] != 'applied' or current(value),
                'that operation was applied, but the selection has changed since; preview it again')
        require(operation['phase'] != 'refused', 'that operation was refused; preview it again')
        return operation

    def settle(self, operation_id, phase, reason, also=None, claim=False):
        require(phase in ('applied', 'refused', 'uncertain'), 'invalid phase')

        def change(value):
            operation = next(o for o in value['operations'] if o['operation_id'] == operation_id)
            require(operation['phase'] in (('proposed',) if claim else ('proposed', 'uncertain')),
                    'the operation was already claimed or settled')
            require(not (operation['phase'] == 'uncertain' and phase == 'refused'),
                    'an uncertain operation needs reconciliation, not a refusal')
            operation['phase'] = phase
            operation['reason'] = reason
            if also:
                also(value)
            return dict(operation)
        return self.update(change)

    def start_check(self):
        def change(value):
            value['checks']['started'] += 1
            return value['checks']['started']
        return self.update(change)

    def observe(self, results, revision, at=None):
        now = at if at is not None else int(time.time() * 1000)

        def change(value):
            for component, code in results.items():
                require(component in COMPONENTS and CODE.fullmatch(code), 'invalid observation')
                value['observations'][component] = {'code': code, 'revision': revision, 'at': now}
        self.update(change)
