"""Pinned PC executor. Providers are explicit capabilities supplied by T12.

There is no command-line entrypoint, environment bypass or native default.
"""
import copy
import json
from pathlib import Path
import re
import secrets
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'setup'))
import store

SCHEMA = 'openwiz.pc-activation.v1'
REASON = 'Reconcile the exact PC activation and App record before continuing.'
EFFECTS = ['Enable and start the owner user unit openwiz.service.']
BINDING_KEYS = {'owner_uid', 'unit', 'root', 'state_root', 'repository', 'project',
                'runtime', 'build', 'config_sha256', 'unit_sha256', 'app_id',
                'installation_id', 'service_issue'}


def require(value):
    store.require(value, 'PC activation contract refused')


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def integer(value, minimum=0):
    return type(value) is int and minimum <= value < 2**53


def binding(value):
    require(type(value) is dict and set(value) == BINDING_KEYS)
    require(integer(value['owner_uid']) and value['unit'] == 'openwiz.service')
    for key in ('root', 'state_root'):
        require(isinstance(value[key], str) and value[key].isascii()
                and matches(value[key], r'/[^\x00-\x1f\x7f]{1,1023}')
                and all(part not in ('', '.', '..') for part in value[key][1:].split('/')))
    require(matches(value['repository'], r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}')
            and value['repository'].split('/')[1] not in ('.', '..'))
    require(matches(value['project'], r'[A-Za-z0-9_][A-Za-z0-9_-]{0,127}'))
    require(matches(value['runtime'], r'0\.[0-9]{1,10}\.[0-9]{1,10} [0-9a-f]{40}')
            and matches(value['build'], '[0-9a-f]{40}')
            and value['runtime'].split(' ')[1] == value['build'])
    for key in ('config_sha256', 'unit_sha256'):
        require(matches(value[key], '[0-9a-f]{64}'))
    for key in ('app_id', 'installation_id', 'service_issue'):
        require(integer(value[key], 1))
    return value


def digest(value):
    return store.fingerprint('activate_engine', {'binding': value['binding'], 'revision': value['revision']})


def request(value):
    require(type(value) is dict and set(value) == {'schema', 'host', 'action', 'operation_id',
            'binding', 'revision', 'request_hash'})
    require(value['schema'] == SCHEMA and value['host'] == 'pc' and value['action'] == 'enable_start')
    require(matches(value['operation_id'], '[0-9a-f]{32}') and integer(value['revision']))
    binding(value['binding'])
    require(matches(value['request_hash'], '[0-9a-f]{64}') and value['request_hash'] == digest(value))
    return value


def journal(value):
    require(type(value) is dict and set(value) == {'schema', 'request', 'operation', 'created_at',
        'updated_at', 'started_at', 'record_at', 'record_state', 'outcome'})
    require(value['schema'] == SCHEMA + '.journal')
    pinned = request(value['request'])
    operation = value['operation']
    store.check_operation(operation)
    require(operation['kind'] == 'activate_engine' and operation['operation_id'] == pinned['operation_id']
            and operation['fingerprint'] == pinned['request_hash'] and operation['effects'] == EFFECTS
            and operation['reason'] == REASON)
    require(integer(value['created_at'], 1) and integer(value['updated_at'], value['created_at']))
    for key in ('started_at', 'record_at'):
        require(value[key] is None or integer(value[key], value['created_at'])
                and value[key] <= value['updated_at'])
    require(isinstance(value['record_state'], str)
            and value['record_state'] in ('pending', 'unsent', 'uncertain', 'confirmed'))
    require(isinstance(value['outcome'], str) and value['outcome'] in ('proposed', 'held', 'applied'))
    require(operation['phase'] not in ('uncertain', 'applied') or value['started_at'] is not None)
    require(value['outcome'] != 'applied' or operation['phase'] == 'applied'
            and value['record_state'] == 'confirmed')
    require(value['record_state'] == 'pending' or operation['phase'] == 'applied')
    require(value['record_state'] in ('pending', 'unsent') or value['record_at'] is not None)
    return value


def parse(raw):
    try:
        require(isinstance(raw, str) and len(raw.encode()) <= 16384)
        return request(json.loads(raw, object_pairs_hook=store.unique))
    except (ValueError, TypeError, KeyError, store.Refused):
        raise store.Refused('PC activation request refused') from None


def current(value, pinned, manager):
    b = pinned['binding']
    p = value['project']
    require(value['revision'] == pinned['revision'] and p is not None
            and all(p[key] == b[key] for key in ('repository', 'project', 'runtime', 'service_issue'))
            and value['app'] == {'app_id': b['app_id'], 'installation_id': b['installation_id']}
            and manager.binding() == b)


class Executor:
    def __init__(self, setup, manager, provider, clock):
        self.setup, self.manager, self.provider, self.clock = setup, manager, provider, clock
        require(Path(manager.state) == setup.state)

    def preview(self):
        def change(value, saved, save):
            if saved is not None:
                current(value, saved['request'], self.manager)
                return copy.deepcopy(saved['request'])
            b = binding(self.manager.binding())
            pinned = {'schema': SCHEMA, 'host': 'pc', 'action': 'enable_start',
                      'operation_id': secrets.token_hex(16), 'binding': b,
                      'revision': value['revision'], 'request_hash': ''}
            pinned['request_hash'] = digest(pinned)
            current(value, pinned, self.manager)
            require(not any(o['kind'] == 'activate_engine' and o['phase'] in ('uncertain', 'applied')
                            for o in value['operations']))
            operation = {'operation_id': pinned['operation_id'], 'kind': 'activate_engine',
                         'phase': 'proposed', 'fingerprint': pinned['request_hash'],
                         'effects': list(EFFECTS), 'reason': REASON}
            value['operations'] = store.retained(value['operations']) + [operation]
            now = self.clock()
            saved = {'schema': SCHEMA + '.journal', 'request': pinned, 'operation': operation,
                     'created_at': now, 'updated_at': now, 'started_at': None, 'record_at': None,
                     'record_state': 'pending', 'outcome': 'proposed'}
            save(saved)
            return copy.deepcopy(pinned)
        return self.setup.activation_transaction(change, journal)

    def evidence(self, method, pinned, now):
        challenge = secrets.token_hex(16)
        result = getattr(self.provider, method)(copy.deepcopy(pinned), challenge, now)
        fields = {'request', 'challenge', 'at'}
        fields |= {'authorized'} if method == 'authority' else {'state', 'lock'}
        require(type(result) is dict and set(result) == fields
                and request(result['request']) == pinned and result['challenge'] == challenge
                and type(result['at']) is int and result['at'] == now)
        if method == 'authority':
            require(result['authorized'] is True)
        else:
            require(isinstance(result['state'], str)
                    and result['state'] in ('healthy', 'not_applied', 'unknown')
                    and isinstance(result['lock'], str) and result['lock'] in ('held', 'free', 'unknown'))
        return result

    def execute(self, raw):
        pinned = parse(raw)
        def change(value, saved, save):
            require(saved is not None and saved['request'] == pinned)
            now = self.clock()
            require(integer(now, saved['updated_at']))
            saved['updated_at'] = now
            saved['outcome'] = 'held'
            # A provider failure never exports its body and never erases uncertainty.
            try:
                current(value, pinned, self.manager)
                self.evidence('authority', pinned, now)
                observed = self.evidence('observe', pinned, now)
            except Exception:
                save(saved)
                return copy.deepcopy(saved)
            phase = saved['operation']['phase']
            healthy = observed['state'] == 'healthy' and observed['lock'] == 'held'
            if not healthy:
                if observed['state'] != 'not_applied' or observed['lock'] != 'free' or phase == 'applied':
                    save(saved)
                    return copy.deepcopy(saved)
                # Positive non-application is scoped to this exact saved operation.
                # Persist the claim BEFORE the only supervisor effect.
                saved['operation']['phase'] = 'uncertain'
                saved['started_at'] = now
                save(saved)
                try:
                    self.provider.enable_start(copy.deepcopy(pinned))
                    observed = self.evidence('observe', pinned, now)
                    healthy = observed['state'] == 'healthy' and observed['lock'] == 'held'
                except Exception:
                    return copy.deepcopy(saved)
            # A preexisting healthy service with no saved start proves no application.
            if not healthy or saved['started_at'] is None:
                save(saved)
                return copy.deepcopy(saved)
            saved['operation']['phase'] = 'applied'
            save(saved)
            if saved['record_state'] in ('pending', 'unsent'):
                # app_record_sink confirms only after its exact comment read-back.
                # A crash or exception during delivery leaves its claim uncertain.
                saved['record_state'] = 'uncertain'
                saved['record_at'] = now
                save(saved)
                body = json.dumps({'schema': SCHEMA + '.record', 'operation_id': pinned['operation_id'],
                    'request_hash': pinned['request_hash'], 'build': pinned['binding']['build'],
                    'outcome': 'applied', 'at': saved['started_at']}, sort_keys=True, separators=(',', ':'))
                try:
                    delivery = self.provider.record(pinned['binding']['service_issue'], body)
                    if type(delivery) is str and delivery in ('confirmed', 'unsent'):
                        saved['record_state'] = delivery
                except Exception:
                    pass
            if saved['record_state'] == 'confirmed':
                saved['outcome'] = 'applied'
            save(saved)
            return copy.deepcopy(saved)
        try:
            return self.setup.activation_transaction(change, journal)
        except (OSError, ValueError, KeyError, TypeError, store.Refused):
            raise store.Refused('Reconcile protected setup state before PC activation.') from None
