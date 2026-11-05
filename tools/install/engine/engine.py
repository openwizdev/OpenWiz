#!/usr/bin/env python3
"""Installed engine preview, activation and status. No CloudRoom, network,
supervisor or secret calls.

PC first (#1093 revision 17): a Local selection activates through #2379's
installed handover executor and T9's PC contract, with the production provider,
which holds before any supervisor effect or App record until native observation
and owner authority exist. Cloud activation is an unresolved gap pending its
separate decision. Login is reported as unknown (LE1). No flag or environment
bypasses either.
"""
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

sys.dont_write_bytecode = True
RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME / 'setup'))
import store

HELD = ('Activation needs an explicit authorization of this preview. A Local engine activates on this PC through '
        'the installed handover and holds until native observation and owner authority exist; Cloud engine '
        'activation is an unresolved gap. Login is reported as unknown.')
CLOUD_GAP = 'Cloud engine activation is an unresolved gap pending its separate decision; nothing was activated.'
PC_HELD = ('PC activation is held: native PC observation and current owner authority are unavailable. '
           'No service was started and no App record was sent.')
PC_RECONCILE = 'Reconcile the recorded PC activation before changing the engine selection.'
JOURNAL_LIMIT = 64 * 1024
CONFIG_LIMIT = 1024 * 1024


class Changed(Exception):
    """The selection differs from the one this command was authorized for (exit 8)."""


COST_KEYS = {'source','provenance','credits','window_s','free_allowance','observed_at','allowance_at'}
MONTH_S = 30 * 86400


def number(value, positive=False):
    try:
        return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)
    except OverflowError:
        return False


def cost(evidence, now):
    unknown = {'provenance':'unknown','credits':None,'window_s':None,'monthly_projection':None,
        'free_allowance':None,'reason':'Cloud Credits are unknown; choose an engine explicitly. Provider charges are separate and unavailable.'}
    if not (type(evidence) is dict and set(evidence) == COST_KEYS
            and evidence['source'] == 'cloudroom_usage'
            and evidence['provenance'] in ('measured','estimated')
            and number(evidence['credits']) and number(evidence['window_s'], True)
            and number(evidence['free_allowance'])
            and all(type(evidence[k]) is int and 0 <= now - evidence[k] <= 3600000
                    for k in ('observed_at','allowance_at'))):
        return unknown, None
    projection = evidence['credits'] / evidence['window_s'] * MONTH_S
    if not math.isfinite(projection):
        return unknown, None
    result = {k:evidence[k] for k in ('provenance','credits','window_s','free_allowance')}
    result.update(monthly_projection=projection,
        reason=f"Recorded CloudRoom usage: {evidence['credits']} credits over {evidence['window_s']} seconds; current free allowance {evidence['free_allowance']}. Projection estimates 30 days at the observed rate. Provider charges are separate and unavailable.")
    default = None
    if evidence['provenance'] == 'measured':
        default = 'local' if projection > evidence['free_allowance'] / 10 else 'cloud'
    return result, default


def private_bytes(path, limit):
    """An owner-only, singly linked regular file read without following links."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        m = os.fstat(fd)
        store.require(stat.S_ISREG(m.st_mode) and m.st_uid == os.getuid()
                      and m.st_nlink == 1 and m.st_mode & 0o077 == 0 and m.st_size <= limit,
                      'unsafe private file')
        with os.fdopen(os.dup(fd), 'rb') as f:
            data = f.read(limit + 1)
        store.require(len(data) <= limit, 'unsafe private file')
        return data
    finally:
        os.close(fd)


def evidence(setup):
    """An explicit protected record supplied by the observation owner, never pricing constants."""
    try:
        return json.loads(private_bytes(setup.dir / 'engine-cost.json', 4096), object_pairs_hook=store.unique)
    except (OSError, ValueError, store.Refused):
        return None


def sibling(name):
    """A packaged tool beside this one in the same build; never a source checkout."""
    spec = importlib.util.spec_from_file_location('openwiz_engine_' + name.replace('/', '_')[:-3],
                                                  RUNTIME / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pc_activation(setup):
    """T9's PC journal outcome, read with T9's own strict reader."""
    path = setup.dir / 'pc-activation.json'
    try:
        path.lstat()
    except FileNotFoundError:
        return {'state':'absent','operation_id':None}
    except OSError:
        return {'state':'unreadable','operation_id':None}
    try:
        journal = sibling('pc_activation/activation.py').journal(
            json.loads(private_bytes(path, JOURNAL_LIMIT), object_pairs_hook=store.unique))
    except Exception:  # Any unreadable or invalid journal is never activation.
        return {'state':'unreadable','operation_id':None}
    return {'state':journal['outcome'],'operation_id':journal['request']['operation_id']}


def install_config(state, value):
    """Create the previewed service config once: owner-only, never replaced."""
    data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    service = state / 'service'
    store.private_directory(state, False)
    store.private_directory(service, True)
    path = service / 'config.json'
    temporary = service / f'.config.{secrets.token_hex(8)}.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)  # Atomic and exclusive: an existing file stays.
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    directory = os.open(service, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return private_bytes(path, CONFIG_LIMIT) == data


def request(value, location):
    p = value['project']
    config(value)  # Refuse an invalid service projection before saving a proposal.
    store.require(p is not None and p['runtime'] is not None, 'Prepare a project with a pinned packaged runtime first.')
    parts = (RUNTIME / 'openwiz-build.txt').read_text().splitlines()
    store.require(len(parts) == 4 and parts[0] == 'openwiz.package.v1'
        and p['runtime'] == parts[1] + ' ' + parts[2], 'The selected runtime differs from this installed package.')
    return {'location':location,'revision':value['revision'],'project':p,'app':value['app']}


def config(value):
    """Proposed input for the existing service/App updater, not another record sink."""
    p, app = value['project'], value['app']
    if not p or not app or not app['installation_id']:
        return None
    owner, name = p['repository'].split('/')
    store.require(re.fullmatch(r'[A-Za-z0-9][-A-Za-z0-9]*', owner)
        and all(re.fullmatch(r'[A-Za-z0-9_][-A-Za-z0-9_]{0,127}', p[key])
                for key in ('project','answer_thread')), 'Invalid projected service identity.')
    return {'schema':'openwiz.service-config.v1','repository':{'owner':owner,'name':name},
        'operator':p['operator'],
        'project':p['project'],'orchestrator_thread':p['answer_thread'],'service_issue':p['service_issue'],
        'github_app':app,'tick':{'every_s':300},'health':{'every_s':60},
        'server':{'port':7370,'allowed_host':None,'probe_timeout_s':10}}


def report(setup, value, measured, default, operation=None):
    selected = value.get('engine')
    if operation is None and selected:
        operation = next((o for o in value['operations'] if o['operation_id'] == selected['operation_id']), None)
    uncertain = operation is not None and operation['phase'] in ('uncertain','applied')
    pc = pc_activation(setup)
    status = ('unknown' if uncertain or pc['state'] in ('unreadable','applied') else
              'held' if pc['state'] == 'held' else 'not_activated')
    return {'schema':'openwiz.engine.v1','engine':selected,'operation':operation,
        'activation_allowed':False,'location_status':status,
        'reason':'Reconcile the exact recorded resource before another activation attempt.' if uncertain
            else PC_HELD if pc['state'] == 'held' else HELD,
        'cost':measured,'default_location':default,'service_config':config(value),
        'pc_activation':pc,'login':'unknown'}


def journaled(setup):
    """Whether a PC activation journal exists; read under the caller's setup lock."""
    try:
        (setup.dir / 'pc-activation.json').lstat()
    except FileNotFoundError:
        return False
    return True


def authorized(current, selected, desired, options):
    """The exact operation this --yes may act on, from state read under the lock."""
    if current.get('engine') != selected or request(current, selected['location']) != desired:
        raise Changed('The selection changed; preview it again.')
    store.require(options['--operation'] == selected['operation_id'],
        'The authorization does not name the current preview.')
    operation = next((o for o in current['operations'] if o['operation_id'] == options['--operation']), None)
    store.require(operation is not None and operation['fingerprint'] == selected['fingerprint'],
        'The authorization does not match the preview.')
    return operation


def held_lock(transactions):
    """One setup lock across T9's separate transactions (review R2).

    The handover's Store opens its own lock for each activation transaction;
    flock would make a second acquisition in this process wait on itself. While
    this context holds the lock, that Store's transactions run inside it.
    """
    acquire, held = transactions.locked, []
    @contextlib.contextmanager
    def locked():
        if held:
            yield
            return
        with acquire():
            held.append(True)
            try:
                yield
            finally:
                held.clear()
    transactions.locked = locked
    return locked


def refuse_runner(*_args):
    """The engine command never runs a supervisor command itself."""
    raise store.Refused('no supervisor command runs from the engine command')


def activate_pc(setup, selected, desired, options, measured, default):
    """PC first: #2379's installed handover executor with its production provider.

    Authorization, config publication and T9's preview and execute all run
    under one held setup lock, against state read inside it."""
    def held(reason, code=None):
        result = report(setup, setup.read(), measured, default)
        result['reason'] = reason
        return result, code or (6 if result['pc_activation']['state'] != 'absent' else 5)
    root = options.get('--root')
    if root is None:
        return held('Name this installation with --root to activate the Local engine on this PC; nothing was activated.')
    try:
        handover = sibling('handover/handover.py')
        runtime = handover.resolve(root, setup.state)
        store.require(Path(runtime['build']).resolve() / 'runtime' == RUNTIME, 'foreign build')
        executor = handover.executor(root, setup.state, handover.Unavailable(),
                                     lambda: int(time.time() * 1000), refuse_runner)
        store.require(Path(executor.setup.state) == setup.state, 'foreign state')
        locked = held_lock(executor.setup)
    except Exception:
        return held('This engine is not the verified selected installation that ships the PC activation '
                    'handover; nothing was activated.')
    with locked():
        current = setup.read()
        try:
            operation = authorized(current, selected, desired, options)
        except Changed:
            return held('The selection changed; preview it again. Nothing was activated.', 8)
        if any(o['kind'] == 'activate_engine' and o['phase'] in ('uncertain','applied')
               for o in current['operations']):
            return report(setup, current, measured, default), 6
        if operation['phase'] != 'proposed':
            return held(HELD, 5)
        try:
            projected = config(current)
            store.require(projected is not None, 'no projected service config')
            installed = install_config(setup.state, projected)
        except (OSError, ValueError, store.Refused):
            return held('The service configuration could not be installed privately; nothing was activated.')
        if not installed:
            return held('A different service configuration is already installed; reconcile it explicitly. '
                        'Nothing was activated.')
        try:
            executor.execute(json.dumps(executor.preview()))
        except Exception:
            return held('Reconcile the recorded PC activation and protected App setup; no service was started.')
    result = report(setup, setup.read(), measured, default)
    return result, 0 if result['pc_activation']['state'] == 'applied' else 6


def execute(command, options):
    setup = store.Store(options.get('--state-dir'))
    value = setup.read()
    now = int(time.time() * 1000)
    saved_cost = (value.get('engine') or {}).get('cost')
    credit_record = saved_cost if command == 'status' else evidence(setup)
    measured, default = cost(credit_record, now)
    uncertain = next((o for o in value['operations'] if o['kind'] == 'activate_engine' and o['phase'] in ('uncertain','applied')), None)
    if uncertain:
        return report(setup, value, measured, default, uncertain), 6
    if command == 'status':
        return report(setup, value, measured, default), 0
    if command == 'preview':
        location = options.get('--location', default)
        if location is None:
            result = report(setup, value, measured, default)
            result['reason'] = 'No measured affordable Cloud default is established; select Cloud or Local explicitly.'
            return result, 5
        desired = request(value, location)
        digest = store.fingerprint('activate_engine', desired)
        def change(current):
            # Recheck all binding facts under the same lock that saves the proposal.
            store.require(request(current, location) == desired, 'The project changed; preview it again.')
            store.require(not any(o['kind'] == 'activate_engine' and o['phase'] in ('uncertain','applied')
                for o in current['operations']), 'Reconcile the uncertain activation first.')
            operation = next((o for o in reversed(current['operations']) if o['kind'] == 'activate_engine'
                and o['fingerprint'] == digest and o['phase'] == 'proposed'), None)
            if journaled(setup):
                # T9 binds its journal to one selection. Only the exact current
                # selection's own proposal may be re-previewed, never an older one.
                selected = current.get('engine')
                if not (selected and selected['location'] == location and selected['fingerprint'] == digest
                        and operation is not None and operation['operation_id'] == selected['operation_id']):
                    raise Changed(PC_RECONCILE)
                return dict(current)
            if operation is None:
                operation = {'operation_id':secrets.token_hex(16),'kind':'activate_engine','phase':'proposed',
                    'fingerprint':digest,'effects':['Select one ' + location + ' engine for this project.',
                        'Use the pinned mechanical tick; engine location does not choose agent location.',
                        'Activation, account provisioning and spending remain separately gated.'],'reason':HELD}
                current['operations'] = store.retained(current['operations'],
                    (current.get('engine') or {}).get('operation_id')) + [operation]
            current['engine'] = {'location':location,'revision':current['revision'],
                'runtime':current['project']['runtime'],'operation_id':operation['operation_id'],
                'fingerprint':digest,'cost':credit_record if measured['provenance'] != 'unknown' else None}
            return dict(current)
        try:
            value = setup.update(change)
        except Changed:
            result = report(setup, setup.read(), measured, default)
            result['reason'] = PC_RECONCILE
            return result, 8
        return report(setup, value, measured, default), 0
    selected = value.get('engine')
    store.require(selected is not None, 'Preview this engine first.')
    desired = request(value, selected['location'])
    if store.fingerprint('activate_engine', desired) != selected['fingerprint']:
        result = report(setup, value, measured, default)
        result['reason'] = 'The project changed since preview; no activation was attempted.'
        return result, 8
    if selected['location'] == 'local':
        return activate_pc(setup, selected, desired, options, measured, default)
    def authorize(current):
        operation = authorized(current, selected, desired, options)
        if operation['phase'] == 'uncertain':
            return dict(current)
        store.require(operation['phase'] in ('proposed','refused'), 'Reconcile the recorded engine first.')
        # The named Cloud gap: refused even with valid authorization.
        operation['phase'], operation['reason'] = 'refused', CLOUD_GAP
        return dict(current)
    try:
        value = setup.update(authorize)
    except Changed:
        result = report(setup, setup.read(), measured, default)
        result['reason'] = 'The selection changed; preview it again. Nothing was activated.'
        return result, 8
    operation = next(o for o in value['operations'] if o['operation_id'] == options['--operation'])
    if operation['phase'] == 'uncertain':
        return report(setup, value, measured, default), 6
    result = report(setup, value, measured, default)
    result['reason'] = CLOUD_GAP
    return result, 5


def parse(args):
    store.require(args and args[0] in ('preview','activate','status'), 'Expected engine preview, activate or status.')
    command, options, index = args[0], {}, 1
    while index < len(args):
        flag = args[index]; index += 1
        store.require(flag not in options, 'Repeated engine option.')
        if flag in ('--state-dir','--location','--operation','--root'):
            store.require(index < len(args), 'Missing engine option value.')
            options[flag] = args[index]; index += 1
        elif flag in ('--json','--yes'):
            options[flag] = True
        else:
            raise store.Refused('Unknown engine option.')
    allowed = {'--state-dir','--json'} | ({'--location'} if command == 'preview' else
        {'--operation','--yes','--root'} if command == 'activate' else set())
    store.require(set(options) <= allowed, 'Option is not valid for this engine command.')
    store.require('--location' not in options or options['--location'] in ('cloud','local'), 'Choose cloud or local.')
    store.require(command != 'activate' or (options.get('--yes') is True and
        isinstance(options.get('--operation'),str) and re.fullmatch('[0-9a-f]{32}',options['--operation'])),
        'Activation requires --yes and the exact preview operation.')
    return command, options


def main(args):
    command = 'engine.' + args[0] if args and args[0] in ('preview','activate','status') else 'unknown'
    try:
        action, options = parse(args)
    except store.Refused:
        return {'schema':'openwiz.cli-error.v1','command':command,'exit_code':2,
            'error':{'kind':'usage','message':'Invalid engine arguments; see openwiz engine --help.'}}, 2
    try:
        return execute(action, options)
    except (store.Refused, OSError, ValueError, KeyError):
        return {'schema':'openwiz.cli-error.v1','command':command,'exit_code':10,
            'error':{'kind':'store_unavailable','message':'Engine setup state or its current selection is unavailable; nothing was activated.'}}, 10


if __name__ == '__main__':
    result, code = main(sys.argv[1:])
    print(json.dumps(result, allow_nan=False, separators=(',',':')))
    sys.exit(code)
