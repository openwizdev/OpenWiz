#!/usr/bin/env python3
"""Bounded, resumable combined live-smoke run sheets. Standard library only."""
import argparse
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

CLAIMS = ('fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'terminal', 'json', 'send', 'new', 'app', 'read_safety')
LIMIT = 32 * 1024 * 1024
RULE_KINDS = {
    'frontier': 'start_builder', 'first_review': 'start_reviewer',
    'fresh_review': 'start_reviewer', 're_check': 'start_reviewer',
    'review_findings': 'send_findings', 'ci_failed': 'send_findings',
    'contract_changed': 'send_findings', 'adr_0008': 'merge',
    'merged': 'close', 'all_closed': 'close', 'contract_hold': 'hold',
    'release': 'hold', 'finished': 'archive', 'builder_refused': 'log_refused_start',
    'reviewer_refused': 'log_refused_start', 'needs_info': 'wake',
    'disputed': 'wake', 'diagnosis': 'wake', 'look': 'wake',
    'held': 'needs_you', 're_approve': 'needs_you', 'person_ready': 'needs_you',
    'spec_summary': 'needs_you', 'restart': 'wake',
}


class Refusal(Exception):
    pass


# #2216's expected-plan restriction, loaded by path: under `python3 -I` this
# folder is not on sys.path, and its http.py must never shadow the stdlib.
RESTRICTION = Path(__file__).resolve().with_name('restriction.py')
_SPEC = importlib.util.spec_from_file_location('live_smoke_restriction', RESTRICTION)
restriction = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(restriction)


JOURNAL = 'journal.jsonl'
# The reviewed probe scripts a live fleet-claim write may run besides the
# canonical tick (the AC6 phone reply and T3 cleanup). Anything else, such as
# a wrapper that could run an unpinned tick, is refused before any step.
PROBES = (str(Path(__file__).resolve().with_name('browser.mjs')),
          str(Path(__file__).resolve().with_name('cleanup.py')))


def is_tick(kit, step):
    return step.get('kind') == 'write' and step.get('argv') == [kit['openwiz'], 'fleet', 'tick', '--json']


def _elf(path, name=None):
    """A real compiled program (not a script that could run anything else)."""
    try:
        real = Path(path).resolve(strict=True)
        with open(real, 'rb') as stream:
            magic = stream.read(4)
    except OSError:
        return False
    return magic == b'\x7fELF' and (name is None or re.fullmatch(name, real.name) is not None)


def reviewed_probe(argv):
    """The whole reviewed invocation: a real interpreter running this folder's
    probe with exactly its arguments. A pinned wrapper is never an interpreter."""
    if len(argv) == 3 and argv[1] == PROBES[0]:
        return _elf(argv[0], r'node[0-9.]*')
    if (len(argv) == 11 and argv[1:4] == ['-I', PROBES[1], '--gh'] and argv[5] == '--repo'
            and argv[7] == '--ticket' and argv[9] == '--action' and argv[10] in ('unlabel', 'close')):
        try:
            same = Path(argv[0]).resolve(strict=True) == Path(sys.executable).resolve(strict=True)
        except OSError:
            return False
        return same and _elf(argv[0]) and _elf(argv[4])
    return False


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Refusal('invalid_json')
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refusal('invalid_json')))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refusal('invalid_json') from error


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def contract_sha(value):
    """The release-candidate contract's canonical JSON digest."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def file_hash(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise Refusal('invalid_kit')


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def pointer(value, path):
    if not isinstance(path, str) or (path and not path.startswith('/')):
        raise Refusal('invalid_kit')
    for token in path.split('/')[1:] if path else []:
        if re.search(r'~(?![01])', token):
            raise Refusal('invalid_kit')
        token = token.replace('~1', '/').replace('~0', '~')
        try:
            if type(value) is dict:
                value = value[token]
            elif type(value) is list and re.fullmatch(r'0|[1-9][0-9]*', token):
                value = value[int(token)]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError) as error:
            raise Refusal('missing_fact') from error
    return value


def load_kit(path):
    kit = decode(path.read_bytes())
    base = {'schema', 'mode', 'cwd', 'openwiz', 'artifacts', 'env', 'timeout_seconds', 'steps'}
    if (type(kit) is not dict or not base <= set(kit)
            or not set(kit) - base <= {'source', 'default_terminal_port', 'release'}):
        raise Refusal('invalid_kit')
    if kit['schema'] != 'openwiz.live-smoke-kit.v1' or kit['mode'] not in ('fixture', 'live'):
        raise Refusal('invalid_kit')
    if not isinstance(kit['cwd'], str) or not Path(kit['cwd']).is_absolute() or not Path(kit['cwd']).is_dir():
        raise Refusal('invalid_kit')
    if not integer(kit['timeout_seconds'], 1, 70):
        raise Refusal('invalid_kit')
    if 'default_terminal_port' in kit:
        port = kit['default_terminal_port']
        if type(port) is not str or not re.fullmatch('[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
            raise Refusal('invalid_kit')
    if type(kit['artifacts']) is not dict or not kit['artifacts']:
        raise Refusal('invalid_kit')
    for name, sha in kit['artifacts'].items():
        if not Path(name).is_absolute() or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise Refusal('invalid_kit')
    if kit['openwiz'] not in kit['artifacts']:
        raise Refusal('invalid_kit')
    # receipt.py checks the whole release section; the runner enforces its
    # write bounds before each dispatch, so their shape is checked here too.
    if 'release' in kit and (
            type(kit['release']) is not dict or type(kit['release'].get('scope')) is not dict
            or type(kit['release']['scope'].get('writes')) is not dict
            or any(k not in CLAIMS or not integer(v, 0, 1000)
                   for k, v in kit['release']['scope']['writes'].items())):
        raise Refusal('invalid_kit')
    if type(kit['env']) is not dict or any(
        not re.fullmatch('[A-Z][A-Z0-9_]*', k) or not isinstance(v, str) or '\0' in v
        for k, v in kit['env'].items()
    ):
        raise Refusal('invalid_kit')
    if {'GH_TOKEN', 'GITHUB_TOKEN', 'OPENWIZ_SMOKE_APP_TOKEN'} & kit['env'].keys():
        raise Refusal('credential_in_kit')
    if kit['mode'] == 'live':
        if any(k.startswith('OPENWIZ_FIXTURE') for k in os.environ.keys() | kit['env'].keys()):
            raise Refusal('fixture_environment')
        if ({str(Path(__file__).resolve()), str(RESTRICTION)} - kit['artifacts'].keys()
                or 'source' not in kit):
            raise Refusal('invalid_kit')
        exact(kit['source'], {'checkout', 'head'})
        if not Path(kit['source']['checkout']).is_absolute() or not re.fullmatch('[0-9a-f]{40}', kit['source']['head']):
            raise Refusal('invalid_kit')
    if type(kit['steps']) is not list or not 1 <= len(kit['steps']) <= 1000:
        raise Refusal('invalid_kit')
    ids, claims = set(), set()
    for step in kit['steps']:
        if type(step) is not dict or step.get('claim') not in CLAIMS:
            raise Refusal('invalid_kit')
        if not isinstance(step.get('id'), str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}', step['id']) or step['id'] in ids:
            raise Refusal('invalid_kit')
        if step.get('kind') == 'event':
            exact(step, {'id', 'claim', 'kind'})
        else:
            keys = {'id', 'claim', 'kind', 'argv', 'exit', 'checks'}
            exact(step, keys | ({'again_from'} if 'again_from' in step else set())
                  | ({'until'} if 'until' in step else set())
                  | ({'token_env'} if 'token_env' in step else set()))
            if 'token_env' in step and step['token_env'] != 'OPENWIZ_SMOKE_APP_TOKEN':
                raise Refusal('invalid_kit')
            if step['kind'] not in ('read', 'write', 'await'):
                raise Refusal('invalid_kit')
            argv = step['argv']
            if type(argv) is not list or not argv or any(not isinstance(a, str) or '\0' in a for a in argv):
                raise Refusal('invalid_kit')
            if argv[0] not in kit['artifacts'] or not os.access(argv[0], os.X_OK):
                raise Refusal('invalid_kit')
            # Pin scripts and private probe inputs as well as their interpreters.
            for arg in argv[1:]:
                if Path(arg).is_absolute() and Path(arg).is_file() and arg not in kit['artifacts']:
                    raise Refusal('invalid_kit')
            if not integer(step['exit'], 0, 255) or type(step['checks']) is not list or not step['checks']:
                raise Refusal('invalid_kit')
            if 'until' in step and (step['kind'] != 'await' or type(step['until']) is not list or not step['until']):
                raise Refusal('invalid_kit')
            for check in step['checks'] + step.get('until', []):
                if type(check) is not dict or set(check) not in (
                    {'path', 'equals'}, {'path', 'same_as'}, {'path', 'actions_in'}, {'path', 'one_of'}
                ):
                    raise Refusal('invalid_kit')
                validate_pointer(check['path'])
                if 'one_of' in check:
                    values = check['one_of']
                    if (type(values) is not list or not values or any(type(v) is not str for v in values)
                            or len(values) != len(set(values))):
                        raise Refusal('invalid_kit')
                if 'same_as' in check:
                    exact(check['same_as'], {'step', 'path'})
                    if check['same_as']['step'] not in ids:
                        raise Refusal('invalid_kit')
                    validate_pointer(check['same_as']['path'])
                if 'actions_in' in check:
                    scope = check['actions_in']
                    exact(scope, {'specs', 'tickets', 'rules', 'never_start'})
                    for field in ('specs', 'tickets', 'never_start'):
                        values = scope[field]
                        if (type(values) is not list or any(not integer(v, 1, 2**53) for v in values)
                                or len(values) != len(set(values))):
                            raise Refusal('invalid_kit')
                    if (not scope['specs'] or not scope['tickets'] or type(scope['rules']) is not list
                            or not scope['rules'] or any(r not in RULE_KINDS for r in scope['rules'])
                            or not set(scope['never_start']) <= set(scope['tickets'])):
                        raise Refusal('invalid_kit')
            # A tick runs only as the saved plan the scope audit accepted; the
            # audit covers the whole ordered action array, never a part of it.
            if is_tick(kit, step) and not any('actions_in' in c and c['path'] == '/actions'
                                              for c in step['checks']):
                raise Refusal('invalid_kit')
            if any('actions_in' in c and c['path'] != '/actions' for c in step['checks']):
                raise Refusal('invalid_kit')
            if (kit['mode'] == 'live' and step['claim'] == 'fleet' and step['kind'] == 'write'
                    and not is_tick(kit, step) and not reviewed_probe(step['argv'])):
                raise Refusal('invalid_kit')
            claims.add(step['claim'])
        ids.add(step['id'])
        if 'again_from' in step:
            if step['kind'] != 'await' or 'until' not in step or step['claim'] != 'fleet' or step['again_from'] not in ids - {step['id']}:
                raise Refusal('invalid_kit')
            start = next(i for i, s in enumerate(kit['steps']) if s['id'] == step['again_from'])
            block = kit['steps'][start:kit['steps'].index(step)]
            writes = [s for s in block if s['kind'] == 'write']
            if (any(s['claim'] != 'fleet' or 'again_from' in s for s in block)
                    or len(writes) != 1
                    or writes[0]['argv'] != [kit['openwiz'], 'fleet', 'tick', '--json']
                    or not any(s['kind'] == 'event' for s in block)):
                raise Refusal('invalid_kit')
    if claims != set(CLAIMS):
        raise Refusal('missing_claim')
    for claim in ('fleet', 'send', 'new'):
        if not any(s['claim'] == claim and s['kind'] == 'write' for s in kit['steps']):
            raise Refusal('missing_write')
    if 'default_terminal_port' in kit:
        service = next((i for i, s in enumerate(kit['steps']) if s['id'] == 'service_before'), None)
        first_write = next(i for i, s in enumerate(kit['steps']) if s['kind'] == 'write')
        if service is None or service >= first_write or kit['steps'][service]['kind'] != 'read':
            raise Refusal('invalid_kit')
    return kit


def validate_pointer(path):
    if not isinstance(path, str) or (path and not path.startswith('/')) or re.search(r'~(?![01])', path):
        raise Refusal('invalid_kit')


def verify_artifacts(kit):
    for path, sha in kit['artifacts'].items():
        if file_hash(path) != sha:
            raise Refusal('artifact_changed')
    if kit['mode'] == 'live':
        source = kit['source']
        head = subprocess.run(['/usr/bin/git', '-C', source['checkout'], 'rev-parse', 'HEAD'],
                              capture_output=True, timeout=5, check=True).stdout.decode().strip()
        clean = subprocess.run(['/usr/bin/git', '-C', source['checkout'], 'diff', '--quiet', 'HEAD'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode
        if head != source['head'] or clean != 0:
            raise Refusal('source_changed')


def owned_children():
    """Only this process's adopted/direct children, never a machine-wide scan."""
    return [int(pid) for pid in Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()]


def enable_containment():
    # Linux subreaper ownership survives descendants' setsid/double-fork. It
    # needs no cgroup delegation or privileged namespace. pidfds bind signals
    # to process identities, so a recycled numeric pid is never killed.
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0 or owned_children():
            raise OSError()
        fd = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(fd, 0)
        finally:
            os.close(fd)
    except (OSError, AttributeError) as error:
        raise Refusal('process_containment_unavailable') from error


def reap_owned():
    deadline = time.monotonic() + 5
    while owned_children():
        for pid in owned_children():
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                if pid in owned_children():
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(fd)
        # Killing the driver reparents its separate-session children here.
        # Repeat until every owned descendant is killed AND reaped, including
        # ones that forked during exit. No orphan is handed to an unrelated init.
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                break
        if time.monotonic() >= deadline:
            raise Refusal('process_containment_failed')


def launch(kit, argv, token_env=None):
    """Never persist diagnostics. Bound output, duration and owned descendants."""
    env = dict(os.environ, **kit['env'])
    env.pop('OPENWIZ_SMOKE_APP_TOKEN', None)
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise Refusal('missing_credential')
        env['GH_TOKEN'] = token
        env.pop('GITHUB_TOKEN', None)
    enable_containment()  # refusal is before Popen, not after a leaking child
    with tempfile.TemporaryFile() as output:
        import resource

        def limits():
            if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
                raise OSError('process containment unavailable')
            resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))

        child = subprocess.Popen(argv, cwd=kit['cwd'], env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.DEVNULL,
                                 start_new_session=True, preexec_fn=limits)
        try:
            code = child.wait(timeout=kit['timeout_seconds'])
        finally:
            reap_owned()
            child.wait()
        output.seek(0)
        raw = output.read(LIMIT + 1)
        if len(raw) >= LIMIT:
            raise Refusal('output_limit')
        return code, raw


def command(kit, argv, token_env=None, seen=None):
    code, raw = launch(kit, argv, token_env)
    if seen is not None:
        seen.update(exit=code, output_sha256=hashlib.sha256(raw).hexdigest())
    if argv[0] == kit['openwiz'] and not raw.endswith(b'\n'):
        raise Refusal('invalid_json')
    return code, decode(raw)


def journal(path, event):
    """Append one hash-chained observation, durably, before it is relied on.

    The journal is the run's evidence: step outcomes, exit codes and output
    digests (never raw output), each line naming the previous line's digest.
    receipt.py refuses a checkpoint it does not match.
    """
    target = path / JOURNAL
    prev, seq = '0' * 64, 0
    if target.exists():
        lines = target.read_bytes().splitlines()
        if lines:
            prev, seq = hashlib.sha256(lines[-1]).hexdigest(), len(lines)
    event = dict(event, at=int(time.time()))
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'ab') as stream:
        stream.write(canonical({'seq': seq, 'prev': prev, 'event': event}) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return event


def read_journal(path):
    """The journal's bytes and events, with its hash chain checked."""
    target = path / JOURNAL
    info = target.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refusal('evidence_mismatch')
    raw = target.read_bytes()
    lines = raw.splitlines()
    if not lines or not raw.endswith(b'\n'):
        raise Refusal('evidence_mismatch')
    events, prev = [], '0' * 64
    for seq, line in enumerate(lines):
        try:
            entry = decode(line)
        except Refusal as error:
            raise Refusal('evidence_mismatch') from error
        if (type(entry) is not dict or set(entry) != {'seq', 'prev', 'event'} or entry['seq'] != seq
                or entry['prev'] != prev or type(entry['event']) is not dict
                or not integer(entry['event'].get('at'), 0, 2**53) or canonical(entry) != line):
            raise Refusal('evidence_mismatch')
        events.append(entry['event'])
        prev = hashlib.sha256(line).hexdigest()
    return raw, events


def observe(doc, checks):
    """What each check compared, bounded: a digest, a listed string or the actions."""
    seen = []
    for check in checks:
        value = pointer(doc, check['path'])
        if 'one_of' in check:
            seen.append({'value': value})
        elif 'actions_in' in check:
            seen.append({'actions': value})
        else:
            seen.append({'digest': digest(value)})
    return seen


def apply(kit, state, event):
    """The one place a journaled transition changes run state."""
    kind = event['kind']
    if kind == 'start':
        state['candidate'] = event['candidate']
        state['times']['started'] = event['at']
        return
    if kind == 'finish':
        state['times']['finished'] = event['at']
        return
    index = next(i for i, s in enumerate(kit['steps']) if s['id'] == event['id'])
    item, step = state['steps'][index], kit['steps'][index]
    if kind == 'attempt':
        item['state'] = 'attempting'
        state['writes'][step['claim']] = state['writes'].get(step['claim'], 0) + 1
        state['fleet'].update(sittings=event['sittings'], started=event['fleet_started'])
    elif kind == 'step':
        item.update(state=event['state'], facts=event['facts'])
        state['reason'] = event['reason']
        state['fleet']['pending'] = event['pending']
    elif kind == 'repeat':
        start = next(i for i, s in enumerate(kit['steps']) if s['id'] == step['again_from'])
        for other in state['steps'][start:index + 1]:
            other.update(state='not_run', facts={})
        state['fleet']['pending'] = False


def _evaluates(kit, step, observed, state):
    checks = step['checks'] + step.get('until', [])
    if type(observed) is not list or len(observed) != len(checks):
        return False
    ids = {s['id']: i for i, s in enumerate(kit['steps'])}
    for check, seen in zip(checks, observed):
        if type(seen) is not dict:
            return False
        if 'one_of' in check:
            if set(seen) != {'value'} or type(seen['value']) is not str or seen['value'] not in check['one_of']:
                return False
        elif 'actions_in' in check:
            try:
                compare({'actions': seen.get('actions')}, [check], state, ids)
            except Refusal:
                return False
        elif 'equals' in check:
            if seen != {'digest': digest(check['equals'])}:
                return False
        else:
            ref = check['same_as']
            expected = state['steps'][ids[ref['step']]]['facts'].get(digest(ref['path']))
            if expected is None or seen != {'digest': expected}:
                return False
    return True


def replay(kit, events):
    """Rebuild run state from the journal, refusing any event the runner could
    not have recorded: out of order, a pass with a wrong exit or an observation
    that fails the step's own checks, or an attempt that was never made."""
    state = initial(kit)
    sha = re.compile('[0-9a-f]{64}')
    ids = {s['id']: i for i, s in enumerate(kit['steps'])}
    for n, event in enumerate(events):
        kind = event.get('kind')
        if (n == 0) != (kind == 'start'):
            raise Refusal('evidence_mismatch')
        if kind == 'start':
            if set(event) != {'kind', 'kit', 'candidate', 'mode', 'runner', 'restriction', 'source', 'at'}:
                raise Refusal('evidence_mismatch')
            apply(kit, state, event)
            continue
        if state['times']['finished']:
            raise Refusal('evidence_mismatch')
        if kind == 'finish':
            if set(event) != {'kind', 'at'} or any(i['state'] != 'pass' for i in state['steps']):
                raise Refusal('evidence_mismatch')
            apply(kit, state, event)
            continue
        index = ids.get(event.get('id'))
        if index is None:
            raise Refusal('evidence_mismatch')
        step, item = kit['steps'][index], state['steps'][index]
        before = all(i['state'] == 'pass' for i in state['steps'][:index])
        pending = state['fleet']['pending']
        if kind == 'attempt':
            if (set(event) != {'kind', 'id', 'claim', 'sittings', 'fleet_started', 'at'}
                    or step['kind'] != 'write' or event['claim'] != step['claim'] or item['state'] != 'not_run'
                    or not before or pending or not integer(event['sittings'], 0, 60)
                    or not integer(event['fleet_started'], 0, 2**53)):
                raise Refusal('evidence_mismatch')
        elif kind == 'step':
            if (not {'kind', 'id', 'state', 'facts', 'reason', 'pending', 'at'} <= set(event)
                    or not set(event) <= {'kind', 'id', 'state', 'facts', 'reason', 'pending', 'at',
                                          'exit', 'output_sha256', 'observed'}
                    or event['state'] not in ('pass', 'fail', 'incomplete') or type(event['facts']) is not dict
                    or type(event['pending']) is not bool or type(event['reason']) is not str):
                raise Refusal('evidence_mismatch')
            readback = pending and 'again_from' in step and item['state'] == 'incomplete'
            if step['kind'] == 'write':
                ok = item['state'] == 'attempting'
            elif readback:
                ok = event['state'] in ('pass', 'fail')
            else:
                # A read or await that ended incomplete is simply run again.
                ok = item['state'] in ('not_run', 'incomplete') and before and not pending
            if step['kind'] == 'event':
                ok = ok and event['state'] == 'pass'
            elif event['state'] == 'pass':
                ok = (ok and event.get('exit') == step['exit'] and type(event.get('exit')) is int
                      and sha.fullmatch(str(event.get('output_sha256')))
                      and _evaluates(kit, step, event.get('observed'), state))
            if event['pending'] and not (event['state'] == 'incomplete' and 'again_from' in step):
                ok = False
            if not ok:
                raise Refusal('evidence_mismatch')
        elif kind == 'repeat':
            if (set(event) != {'kind', 'id', 'again_from', 'exit', 'output_sha256', 'at'}
                    or not pending or item['state'] != 'incomplete' or event['again_from'] != step.get('again_from')
                    or event['exit'] != step['exit'] or not sha.fullmatch(str(event['output_sha256']))):
                raise Refusal('evidence_mismatch')
        else:
            raise Refusal('evidence_mismatch')
        apply(kit, state, event)
    return state


def bind_candidate(kit, candidate):
    """The sealed candidate this run tests: its kit and scope are this kit's."""
    if (type(candidate) is not dict or candidate.get('schema') != 'openwiz.release-candidate.v1'
            or type(candidate.get('candidate')) is not dict
            or contract_sha(candidate['candidate']) != candidate.get('candidate_sha256')):
        raise Refusal('candidate_mismatch')
    bound = candidate['candidate'].get('kit')
    if (type(bound) is not dict or bound.get('sha256') != digest(kit) or 'release' not in kit
            or bound.get('scope_sha256') != contract_sha(kit['release'].get('scope'))):
        raise Refusal('candidate_mismatch')
    return candidate['candidate_sha256']


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refusal('unsafe_state')


def save(path, state):
    fd, tmp = tempfile.mkstemp(dir=path, prefix='.checkpoint-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(state) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path / 'checkpoint.json')
        directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def initial(kit):
    return {'schema': 'openwiz.live-smoke-checkpoint.v1', 'kit': digest(kit),
            'steps': [{'state': 'not_run', 'facts': {}} for _ in kit['steps']],
            'reason': 'none', 'fleet': {'sittings': 0, 'started': 0, 'pending': False},
            'times': {'started': 0, 'finished': 0}, 'candidate': None, 'writes': {}}


def load_state(path, kit):
    target = path / 'checkpoint.json'
    if not target.exists():
        return initial(kit)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > LIMIT:
            raise Refusal('unsafe_state')
        state = decode(stream.read())
    exact(state, {'schema', 'kit', 'steps', 'reason', 'fleet', 'times', 'candidate', 'writes'})
    if ((state['candidate'] is not None and (type(state['candidate']) is not str
                                             or not re.fullmatch('[0-9a-f]{64}', state['candidate'])))
            or type(state['writes']) is not dict
            or any(k not in CLAIMS or not integer(v, 0, 2**53) for k, v in state['writes'].items())):
        raise Refusal('invalid_state')
    exact(state['fleet'], {'sittings', 'started', 'pending'})
    exact(state['times'], {'started', 'finished'})
    if (not all(integer(state['times'][k], 0, 2**53) for k in ('started', 'finished'))
            or (state['times']['finished'] and state['times']['finished'] < state['times']['started'])):
        raise Refusal('invalid_state')
    if (not integer(state['fleet']['sittings'], 0, 60)
            or not integer(state['fleet']['started'], 0, 2**53)
            or type(state['fleet']['pending']) is not bool):
        raise Refusal('invalid_state')
    if state['schema'] != 'openwiz.live-smoke-checkpoint.v1' or state['kit'] != digest(kit):
        raise Refusal('kit_changed')
    if type(state['steps']) is not list or len(state['steps']) != len(kit['steps']):
        raise Refusal('invalid_state')
    for item in state['steps']:
        exact(item, {'state', 'facts'})
        if item['state'] not in ('not_run', 'attempting', 'pass', 'fail', 'incomplete') or type(item['facts']) is not dict:
            raise Refusal('invalid_state')
        if any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v)
               for pair in item['facts'].items() for v in pair):
            raise Refusal('invalid_state')
    if state['fleet']['pending'] and sum(
        'again_from' in s and item['state'] == 'incomplete'
        for s, item in zip(kit['steps'], state['steps'])
    ) != 1:
        raise Refusal('invalid_state')
    if state['reason'] not in ('none', 'comparison', 'uncertain_write', 'missing_fact',
                                'invalid_json', 'command_failed', 'timeout', 'output_limit', 'pending',
                                'missing_credential', 'default_terminal_port',
                                'process_containment_unavailable', 'process_containment_failed'):
        raise Refusal('invalid_state')
    return state


def report(kit, state, verdict, reason):
    claims = {}
    for claim in CLAIMS:
        items = [item['state'] for step, item in zip(kit['steps'], state['steps'])
                 if step['claim'] == claim and step['kind'] != 'event']
        claims[claim] = ('fail' if 'fail' in items else 'pass' if all(s == 'pass' for s in items)
                         else 'incomplete' if any(s != 'not_run' for s in items) else 'not_run')
    return {'schema': 'openwiz.live-smoke.v1', 'evidence': kit['mode'],
            'kit_sha256': digest(kit), 'verdict': verdict, 'reason': reason,
            'claims': claims, 'steps_passed': sum(s['state'] == 'pass' for s in state['steps'])}


def compare(doc, checks, state, ids):
    for check in checks:
        value = pointer(doc, check['path'])
        if 'one_of' in check:
            if type(value) is not str or value not in check['one_of']:
                raise Refusal('comparison')
            continue
        if 'actions_in' in check:
            scope = check['actions_in']
            if type(value) is not list:
                raise Refusal('missing_fact')
            builders = set()
            for action in value:
                if (type(action) is not dict or set(action) != {'kind', 'rule', 'spec', 'ticket', 'facts', 'outcome'}
                        or type(action['facts']) is not dict or type(action['outcome']) is not dict):
                    raise Refusal('missing_fact')
                if (type(action['spec']) is not int or action['spec'] not in scope['specs']
                        or (action['ticket'] is not None and (type(action['ticket']) is not int
                            or action['ticket'] not in scope['tickets']))
                        or not isinstance(action['rule'], str) or action['rule'] not in scope['rules']
                        or action['kind'] != RULE_KINDS[action['rule']]
                        or (action['kind'] == 'start_builder' and action['ticket'] is None)
                        or (action['kind'] == 'start_builder' and action['ticket'] in scope['never_start'])):
                    raise Refusal('comparison')
                if action['kind'] == 'start_builder':
                    key = (action['spec'], action['ticket'])
                    if key in builders:
                        raise Refusal('comparison')
                    builders.add(key)
                if type(doc) is dict and doc.get('mode') == 'dry_run' and action['outcome'] != {'state': 'planned'}:
                    raise Refusal('comparison')
            continue
        actual = digest(value)
        if 'equals' in check:
            expected = digest(check['equals'])
        else:
            ref = check['same_as']
            other = state['steps'][ids[ref['step']]]
            key = digest(ref['path'])
            if key not in other['facts']:
                raise Refusal('missing_fact')
            expected = other['facts'][key]
        if actual != expected:
            raise Refusal('comparison')


def audit(plan, step, state, ids):
    """The step's scope allowlist, applied to the preview before it is saved."""
    try:
        compare(plan, [c for c in step['checks'] if 'actions_in' in c], state, ids)
    except Refusal:
        return False
    return True


def assess(doc, step, state, ids):
    compare(doc, step['checks'], state, ids)
    try:
        compare(doc, step.get('until', []), state, ids)
    except Refusal as error:
        if str(error) == 'comparison':
            raise Refusal('pending') from error
        raise


def record(path, kit, state, event):
    """Journal first (the evidence), then apply it and save the checkpoint (its cache)."""
    apply(kit, state, journal(path, event))
    save(path, state)


def reconcile(path, kit, state):
    """The checkpoint must be the journal's replay, or lag it by one event that
    an interruption left unapplied; then that event is adopted, never redone."""
    if not (path / JOURNAL).exists():
        if state != initial(kit):
            raise Refusal('invalid_state')
        return state
    try:
        _, events = read_journal(path)
        replayed = replay(kit, events)
        if replayed == state:
            return state
        if replay(kit, events[:-1]) == state:
            save(path, replayed)
            return replayed
    except Refusal as error:
        raise Refusal('invalid_state') from error
    raise Refusal('invalid_state')


def run(kit, path, candidate=None):
    # No-argument TUI always uses 7370. Never connect to a different service
    # merely because the explicit UI probe was given another valid port.
    if kit.get('default_terminal_port', '7370') != '7370':
        return report(kit, initial(kit), 'incomplete', 'default_terminal_port'), 3
    private_dir(path)
    fd = os.open(path / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refusal('runner_busy') from error
        state = reconcile(path, kit, load_state(path, kit))
        # One run tests one sealed candidate, bound before its first step and
        # required unchanged on every resume. An unbound run binds nothing later.
        bound = bind_candidate(kit, candidate) if candidate is not None else None
        started = (path / JOURNAL).exists()
        if started and state['candidate'] != bound:
            raise Refusal('candidate_changed')
        if not started:
            record(path, kit, state, {
                'kind': 'start', 'kit': digest(kit), 'candidate': bound, 'mode': kit['mode'],
                'runner': file_hash(Path(__file__).resolve()), 'restriction': file_hash(RESTRICTION),
                'source': kit['source']['head'] if 'source' in kit else None})
        if any(s['state'] == 'fail' for s in state['steps']):
            return report(kit, state, 'fail', 'comparison'), 1
        if any(s['state'] == 'attempting' for s in state['steps']):
            return report(kit, state, 'incomplete', 'uncertain_write'), 3
        # The real inventory path runs bundle discovery; help/version do not.
        try:
            code, doc = command(kit, [kit['openwiz'], 'ls', '--json'])
            good = (code == 0 and type(doc) is dict and doc.get('schema') == 'openwiz.inventory.v1'
                    and pointer(doc, '/coverage/state') == 'complete' and doc.get('gaps') == [])
        except Refusal as error:
            if str(error) in ('process_containment_unavailable', 'process_containment_failed'):
                return report(kit, state, 'incomplete', str(error)), 3
            good = False
        except subprocess.TimeoutExpired:
            good = False
        if not good:
            return report(kit, state, 'incomplete', 'bundle_preflight'), 3
        ids = {s['id']: i for i, s in enumerate(kit['steps'])}
        if (state['fleet']['started']
                and any('again_from' in s and item['state'] != 'pass'
                        for s, item in zip(kit['steps'], state['steps']))
                and not 0 <= int(time.time()) - state['fleet']['started'] < 10800):
            return report(kit, state, 'incomplete', 'fleet_limit'), 3
        # A completed, known tick may be followed by another tick on a later
        # event. Check its readback first: a merge that arrived between sittings
        # must not cause an unnecessary tick. No other write is repeatable.
        if state['fleet']['pending']:
            index = next(i for i, s in enumerate(kit['steps'])
                         if 'again_from' in s and state['steps'][i]['state'] == 'incomplete')
            step = kit['steps'][index]
            seen = {}
            try:
                code, doc = command(kit, step['argv'], step.get('token_env'), seen)
                if code != step['exit']:
                    raise Refusal('command_failed')
                assess(doc, step, state, ids)
            except Refusal as error:
                if str(error) == 'comparison':
                    record(path, kit, state, dict(seen, kind='step', id=step['id'], state='fail',
                                                  facts={}, reason='comparison', pending=False))
                    return report(kit, state, 'fail', 'comparison'), 1
                if str(error) != 'pending':
                    return report(kit, state, 'incomplete', str(error)), 3
                record(path, kit, state, dict(seen, kind='repeat', id=step['id'], again_from=step['again_from']))
            else:
                record(path, kit, state, dict(seen, kind='step', id=step['id'], state='pass', facts={},
                                              reason='none', pending=False,
                                              observed=observe(doc, step['checks'] + step.get('until', []))))
        for index, step in enumerate(kit['steps']):
            item = state['steps'][index]
            if item['state'] == 'pass':
                continue
            if step['kind'] == 'event':
                record(path, kit, state, {'kind': 'step', 'id': step['id'], 'state': 'pass', 'facts': {},
                                          'reason': state['reason'], 'pending': False})
                return report(kit, state, 'incomplete', 'next_event'), 3
            if item['state'] == 'incomplete' and step['kind'] == 'write':
                return report(kit, state, 'incomplete', 'uncertain_write'), 3
            verify_artifacts(kit)
            pinned, seen = None, {}
            if step['kind'] == 'write':
                # The approved scope bounds consumed attempts, repeats included.
                if ('release' in kit and state['writes'].get(step['claim'], 0)
                        >= kit['release']['scope']['writes'].get(step['claim'], 0)):
                    return report(kit, state, 'incomplete', 'write_limit'), 3
                repeated = any(s.get('again_from') in ids
                               and ids[s['again_from']] <= index < i
                               for i, s in enumerate(kit['steps']))
                fleet, now = state['fleet'], int(time.time())
                if repeated and (fleet['sittings'] >= 60
                                 or (fleet['started'] and not 0 <= now - fleet['started'] < 10800)):
                    return report(kit, state, 'incomplete', 'fleet_limit'), 3
                if is_tick(kit, step):
                    # Before any effect: the binary must offer --expect-plan and
                    # its one preview must pass the step's scope audit; otherwise
                    # refuse here, consuming nothing. The saved plan then
                    # constrains the tick itself, including recovery (#1892, #2216).
                    try:
                        pinned = restriction.establish(
                            kit['openwiz'], Path(os.path.abspath(path)),
                            lambda argv: launch(kit, argv, step.get('token_env')),
                            lambda plan: audit(plan, step, state, ids))
                    except (Refusal, restriction.Refused) as error:
                        return report(kit, state, 'incomplete', str(error)), 3
                    except subprocess.TimeoutExpired:
                        return report(kit, state, 'incomplete', 'timeout'), 3
                # Durable BEFORE any effect; this attempt is never replayed.
                record(path, kit, state, {
                    'kind': 'attempt', 'id': step['id'], 'claim': step['claim'],
                    'sittings': fleet['sittings'] + (1 if repeated else 0),
                    'fleet_started': (fleet['started'] or now) if repeated else fleet['started']})
            try:
                if pinned:
                    def observed(argv):
                        code, raw = launch(kit, argv, step.get('token_env'))
                        seen.update(exit=code, output_sha256=hashlib.sha256(raw).hexdigest())
                        return code, raw
                    code, doc = 0, restriction.execute(pinned, observed)
                else:
                    code, doc = command(kit, step['argv'], step.get('token_env'), seen)
                if code != step['exit']:
                    raise Refusal('command_failed')
                if 'default_terminal_port' in kit and step['id'] == 'service_before':
                    if (pointer(doc, '/schema') != 'openwiz.service-status.v1'
                            or pointer(doc, '/server/port') != 7370):
                        raise Refusal('default_terminal_port')
                if is_tick(kit, step):
                    if (type(doc) is not dict or doc.get('schema') != 'openwiz.fleet-tick.v1'
                            or doc.get('mode') != 'run' or type(doc.get('actions')) is not list
                            or any(type(a) is not dict or a.get('outcome') != {'state': 'done'}
                                   for a in doc['actions'])):
                        raise Refusal('uncertain_write')
                assess(doc, step, state, ids)
                # Retain only hashes of facts later comparisons require.
                facts = {}
                for later in kit['steps'][index + 1:]:
                    for check in later.get('checks', []) + later.get('until', []):
                        ref = check.get('same_as')
                        if ref and ref['step'] == step['id']:
                            facts[digest(ref['path'])] = digest(pointer(doc, ref['path']))
                record(path, kit, state, dict(seen, kind='step', id=step['id'], state='pass', facts=facts,
                                              reason='none', pending=False,
                                              observed=observe(doc, step['checks'] + step.get('until', []))))
            except (Refusal, restriction.Refused, subprocess.TimeoutExpired) as error:
                # A restricted tick that refused or departed from its plan has
                # still consumed its attempt: it is never launched again.
                reason = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else str(error)
                if step['kind'] == 'write' and reason != 'comparison':
                    reason = 'uncertain_write'
                failed = reason == 'comparison'
                record(path, kit, state, dict(seen, kind='step', id=step['id'],
                                              state='fail' if failed else 'incomplete', facts={}, reason=reason,
                                              pending=reason == 'pending' and 'again_from' in step))
                return report(kit, state, 'fail' if failed else 'incomplete', reason), 1 if failed else 3
        verify_artifacts(kit)
        if not state['times']['finished']:
            record(path, kit, state, {'kind': 'finish'})
        return report(kit, state, 'pass', 'none'), 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--candidate', type=Path,
                        help='the sealed release candidate this run tests (needed for receipts)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--fixture', action='store_true')
    mode.add_argument('--execute', metavar='APPROVED_KIT_SHA256')
    args = parser.parse_args()
    try:
        kit = load_kit(args.kit)
        verify_artifacts(kit)
        if args.fixture and kit['mode'] != 'fixture':
            raise Refusal('mode_mismatch')
        if args.execute and (kit['mode'] != 'live' or args.execute != digest(kit)):
            raise Refusal('approval_mismatch')
        if args.dry_run:
            doc, code = report(kit, initial(kit), 'not_run', 'dry_run'), 0
        else:
            candidate = decode(args.candidate.read_bytes()) if args.candidate else None
            doc, code = run(kit, args.state, candidate)
    except (Refusal, OSError, TypeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Never interpolate an exception: it may contain private argv/paths/output.
        reason = str(error) if isinstance(error, Refusal) else 'invalid_input'
        doc, code = {'schema': 'openwiz.live-smoke.v1', 'verdict': 'incomplete', 'reason': reason}, 2
    print(json.dumps(doc, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
