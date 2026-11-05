#!/usr/bin/env python3
"""Installed engine handover (#2379). Python standard library only.

Resolves only the verified selected installation and composes its own packaged
PC executor and completion verifier. Login is reported as unknown (LE1). No
source checkout, PATH, environment or flag selects another runtime. This module
supplies no native observer, owner-authority source, trusted completion reader,
credit source or network adapter: those stay unavailable and therefore hold.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The verifier that ships beside this file; never the runtime it inspects.
install = _load('openwiz_handover_install', TOOLS / 'install.py')
HANDOVER_RUNTIME = install.HANDOVER_RUNTIME
JOURNAL_LIMIT = 64 * 1024
CREDIT_LIMIT = 4096
PROJECTION_LABEL = 'estimate: 30 days at the observed rate'
VERSION = r'0\.[0-9]{1,10}\.[0-9]{1,10}'


class Refused(Exception):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def resolve(root, state_root=None):
    """The exact verified build that `<root>/current` selects, or a refusal."""
    root = Path(root)
    state = Path(state_root) if state_root else root / 'state'
    try:
        install.path_guard(root)
        install.path_guard(state)
        install.private(root)
        link = root / 'current'
        require(link.is_symlink() and link.lstat().st_uid == os.getuid(), 'no verified installed selection')
        build = Path(os.readlink(link))
        require(build.is_absolute() and build.parent == state / 'service/builds'
                and install.digest(build.name, 40), 'foreign installed selection')
        install.private(build)
        manifest = build / 'install-manifest.json'
        install.private(manifest, False)
        raw = manifest.read_bytes()
        target = json.loads(raw, object_pairs_hook=install.unique)['target']
        value, assets, raw = install.manifest_at(manifest, sha(raw), target)
        require(value['source'] == build.name, 'installed identity mismatch')
        install.verify_installed(build, assets, raw)
    except (install.Refused, OSError, ValueError, KeyError, TypeError):
        raise Refused('installed runtime is missing or unverified') from None
    return {'root': str(root), 'state_root': str(state), 'build': str(build),
            'version': value['version'], 'source': value['source'], 'target': value['target'],
            'runtime': value['version'] + ' ' + value['source'], 'assets': frozenset(assets)}


def modules(runtime):
    """Load the packaged handover tools from the resolved build only."""
    require(set(HANDOVER_RUNTIME) <= runtime['assets'], 'installed handover runtime is missing')
    build = Path(runtime['build']).resolve()
    tag = runtime['source']
    saved = sys.modules.get('store')
    try:
        store = _load('openwiz_store_' + tag, build / 'runtime/setup/store.py')
        # Packaged tools `import store`; bind it to this build for their load only.
        sys.modules['store'] = store
        loaded = {'store': store,
                  'platform': _load('openwiz_platform_' + tag, build / 'runtime/platform/runtime.py'),
                  'activation': _load('openwiz_activation_' + tag, build / 'runtime/pc_activation/activation.py'),
                  'checkpoint': _load('openwiz_checkpoint_' + tag, build / 'runtime/completion/checkpoint.py'),
                  'engine': _load('openwiz_engine_' + tag, build / 'runtime/engine/engine.py')}
    except Exception:
        raise Refused('installed handover runtime is unreadable') from None
    finally:
        if saved is None:
            sys.modules.pop('store', None)
        else:
            sys.modules['store'] = saved
    require(all(Path(m.__file__).resolve().is_relative_to(build) for m in loaded.values())
            and loaded['activation'].store is store and loaded['engine'].store is store,
            'installed handover runtime is not self-contained')
    return loaded


def manager(runtime, state, runner, system=None, machine=None):
    """The packaged PC manager. Its supervisor runner is always injected."""
    return modules(runtime)['platform'].PcManager(runtime['root'], state, runner, system, machine)


class Unavailable:
    """Production provider until native observation and owner authority exist.

    Every capability refuses, so the packaged executor saves a held outcome
    and performs no supervisor effect or App record delivery.
    """
    def _refuse(self, *_args):
        raise Refused('native PC observation and current owner authority are unavailable')

    authority = observe = enable_start = record = _refuse


def executor(root, state, provider, clock, runner, system=None, machine=None):
    runtime = resolve(root, state)
    loaded = modules(runtime)
    pc = loaded['platform'].PcManager(runtime['root'], state, runner, system, machine)
    return loaded['activation'].Executor(loaded['store'].Store(state), pc, provider, clock)


def _private_bytes(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_nlink == 1
                and meta.st_mode & 0o077 == 0 and meta.st_size <= limit, 'private file refused')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(limit + 1)
        require(len(data) <= limit, 'private file refused')
        return data
    finally:
        os.close(fd)


def activation(runtime, state, loaded):
    """`absent`, `unreadable`, `held` or `verified` for the T9 journal."""
    path = Path(state) / 'setup/pc-activation.json'
    try:
        path.lstat()
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'unreadable'
    try:
        journal = loaded['activation'].journal(
            json.loads(_private_bytes(path, JOURNAL_LIMIT), object_pairs_hook=loaded['store'].unique))
        raw = _private_bytes(Path(state) / 'service/config.json', 1024 * 1024)
        config = json.loads(raw, object_pairs_hook=loaded['store'].unique)
    except Exception:
        return 'unreadable'
    binding = journal['request']['binding']
    try:
        owner = config['repository']['owner'] + '/' + config['repository']['name']
        current = {'owner_uid': os.geteuid(), 'unit': 'openwiz.service', 'root': runtime['root'],
                   'state_root': str(state), 'build': runtime['source'], 'runtime': runtime['runtime'],
                   'config_sha256': sha(raw), 'repository': owner, 'project': config['project'],
                   'app_id': config['github_app']['app_id'],
                   'installation_id': config['github_app']['installation_id'],
                   'service_issue': config['service_issue']}
    except (KeyError, TypeError):
        return 'held'
    # T9's journal reader makes `applied` imply a confirmed App record read-back.
    applied = journal['outcome'] == 'applied'
    return 'verified' if applied and all(binding[k] == v for k, v in current.items()) else 'held'


def status(root, state=None):
    """The installed handover report. Login is never inferred: always unknown."""
    report = {'schema': 'openwiz.installed-handover.v1', 'runtime': None, 'activation': 'unreadable',
              'login': 'unknown', 'completion': 'held', 'cloud': 'unresolved',
              'handover_allowed': False, 'next_steps': []}
    state = Path(state) if state else Path(root) / 'state'
    try:
        runtime = resolve(root, state)
    except Refused:
        report['next_steps'] = ['Reinstall a verified OpenWiz release; no source or PATH program is used.']
        return report
    report['runtime'] = {k: runtime[k] for k in ('version', 'source', 'target')}
    try:
        report['activation'] = activation(runtime, state, modules(runtime))
    except Refused:
        report['next_steps'] = ['Install a release that ships the handover runtime.']
        return report
    report['handover_allowed'] = report['activation'] == 'verified'
    report['next_steps'] = {
        'absent': ['Preview PC activation, then authorize that exact operation.'],
        'unreadable': ['Repair private setup state; nothing is treated as activated.'],
        'held': ['Reconcile the exact recorded PC activation and App record before continuing.'],
        'verified': [],
    }[report['activation']] + [
        'Login is reported as unknown.',
        'Completion effects stay held until a trusted completion reader exists.',
        'Cloud engine activation remains an unresolved #1106 gap.']
    return report


def _no_reader(_nonce):
    raise Refused('no trusted completion reader is available')


def completion(root, pin, effect, reader=None, state=None):
    """The installed T10 verifier, re-run at each effect. Unreadable holds."""
    try:
        loaded = modules(resolve(root, state))
    except Refused:
        return 'CP1_unreadable'
    return loaded['checkpoint'].verify_completion(reader or _no_reader, pin, effect)


def _integer(value):
    return type(value) is int and 0 <= value < 2**53


def _credits(value):
    try:
        return value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0)
    except OverflowError:
        return False


def _exact(value, keys):
    return type(value) is dict and set(value) == set(keys)


def credit_shape(value):
    """Exactly `contract.v1.schema.json#/$defs/credit_evidence`."""
    return (_exact(value, ('schema', 'candidate', 'interval', 'usage', 'allowance'))
        and value['schema'] == 'openwiz.credit-evidence.v1'
        and _exact(value['candidate'], ('version', 'source'))
        and type(value['candidate']['version']) is str
        and re.fullmatch(VERSION, value['candidate']['version']) is not None
        and type(value['candidate']['source']) is str
        and re.fullmatch('[0-9a-f]{40}', value['candidate']['source']) is not None
        and _exact(value['interval'], ('started_at', 'ended_at'))
        and all(_integer(value['interval'][k]) for k in ('started_at', 'ended_at'))
        and _exact(value['usage'], ('source', 'provenance', 'credits', 'observed_at'))
        and value['usage']['source'] == 'cloudroom_usage'
        and value['usage']['provenance'] in ('measured', 'estimated', 'unknown')
        and _credits(value['usage']['credits']) and _integer(value['usage']['observed_at'])
        and _exact(value['allowance'], ('source', 'credits', 'observed_at'))
        and value['allowance']['source'] == 'cloudroom_plan'
        and _credits(value['allowance']['credits']) and _integer(value['allowance']['observed_at']))


def _engine():
    # #2001's cost reader and default policy, shipped beside this file.
    saved = sys.modules.get('store')
    try:
        sys.modules['store'] = _load('openwiz_handover_store', TOOLS / 'setup/store.py')
        return _load('openwiz_handover_engine', TOOLS / 'engine/engine.py')
    finally:
        if saved is None:
            sys.modules.pop('store', None)
        else:
            sys.modules['store'] = saved


def credit(value, now, candidate):
    """Validate one #1110 credit-evidence record offline; never a live source."""
    result = {'schema': 'openwiz.credit-handoff.v1', 'candidate': candidate, 'provenance': 'unknown',
              'credits': None, 'window_s': None, 'free_allowance': None, 'monthly_projection': None,
              'policy_branch': 'explicit_choice', 'provider_charges': 'separate_unavailable',
              'reason': 'Cloud Credits are unknown; choose an engine explicitly.'}
    if not (credit_shape(value) and _integer(now) and value['candidate'] == candidate):
        return result
    interval, usage, allowance = value['interval'], value['usage'], value['allowance']
    if not (interval['started_at'] < interval['ended_at'] <= usage['observed_at'] <= now
            and allowance['observed_at'] <= now and usage['provenance'] != 'unknown'
            and usage['credits'] is not None and allowance['credits'] is not None):
        return result
    measured, default = _engine().cost({
        'source': 'cloudroom_usage', 'provenance': usage['provenance'], 'credits': usage['credits'],
        'window_s': (interval['ended_at'] - interval['started_at']) / 1000,
        'free_allowance': allowance['credits'], 'observed_at': usage['observed_at'],
        'allowance_at': allowance['observed_at']}, now)
    if measured['provenance'] == 'unknown':
        return result
    result.update(provenance=measured['provenance'], credits=measured['credits'],
                  window_s=measured['window_s'], free_allowance=measured['free_allowance'],
                  monthly_projection={'credits': measured['monthly_projection'], 'label': PROJECTION_LABEL},
                  policy_branch=default or 'explicit_choice', reason=measured['reason'])
    return result


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    report = commands.add_parser('status', help='report the installed handover; reads only')
    report.add_argument('--root', required=True)
    report.add_argument('--state-root')
    check = commands.add_parser('credit', help='validate one #1110 credit-evidence record offline')
    check.add_argument('evidence')
    check.add_argument('--now', type=int, required=True)
    check.add_argument('--version', required=True)
    check.add_argument('--source', required=True)
    args = parser.parse_args(argv)
    if args.command == 'status':
        result = status(args.root, args.state_root)
        print(json.dumps(result, separators=(',', ':')))
        return 0 if result['handover_allowed'] else 5
    candidate = {'version': args.version, 'source': args.source}
    try:
        value = json.loads(Path(args.evidence).read_bytes()[:CREDIT_LIMIT + 1].decode('utf-8')
                           if Path(args.evidence).stat().st_size <= CREDIT_LIMIT else '',
                           object_pairs_hook=install.unique)
    except (OSError, ValueError, install.Refused):
        value = None
    result = credit(value, args.now, candidate)
    print(json.dumps(result, separators=(',', ':'), allow_nan=False))
    return 0 if result['policy_branch'] in ('cloud', 'local') else 5


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
