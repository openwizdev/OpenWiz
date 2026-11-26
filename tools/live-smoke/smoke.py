#!/usr/bin/env python3
import argparse
import ctypes
import fcntl
import hashlib
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

DESCRIPTION = """Bounded, resumable combined live-smoke run sheets. Standard library only."""

CLAIMS = ('fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'json', 'send', 'new', 'app', 'read_safety', 'install')
COMBINED = CLAIMS[:11]


def kit_claims(kit):
    return tuple(kit['claims']) if 'claims' in kit else COMBINED
LIMIT = 32 * 1024 * 1024
SITTINGS, FLEET_SECONDS = 60, 10800


class Refusal(Exception):
    pass


JOURNAL = 'journal.jsonl'
PROBES = (str(Path(__file__).resolve().with_name('cleanup.py')),)


RESERVED_PORT = 7370


def refuse_reserved_port(kit, argv):
    ports = []
    for index, arg in enumerate(argv):
        following = argv[index + 1] if index + 1 < len(argv) else None
        if arg == '--port' and following is not None:
            ports.append(following)
        elif arg.startswith('--port='):
            ports.append(arg[len('--port='):])
        elif Path(arg).is_absolute() and Path(arg).name == 'http.py' and following is not None:
            ports.append(following)
        rest = argv[index + 1:]
        explicit = any(r == '--port' or r.startswith('--port=') for r in rest)
        if ((arg == kit['openwiz'] and (not rest or (rest[0] == 'ui' and rest != ['ui', '--json'] and not explicit)))
                or (Path(arg).name == 'openwiz-terminal' and not explicit)):
            raise Refusal('reserved_port')
    if any(re.fullmatch('[0-9]{1,5}', port) and int(port) == RESERVED_PORT for port in ports):
        raise Refusal('reserved_port')


def retired(kit, argv):
    if argv[1:3] != ['fleet', 'tick'] and argv[1:2] != ['engine']:
        return False
    if argv[0] == kit['openwiz']:
        return True
    try:
        if os.path.samefile(argv[0], kit['openwiz']):
            return True
    except (OSError, TypeError, ValueError):
        return True
    pinned = kit['artifacts'].get(argv[0])
    return pinned is not None and pinned == kit['artifacts'].get(kit['openwiz'])


def in_block(kit, index):
    ids = {s['id']: i for i, s in enumerate(kit['steps'])}
    return any('again_from' in s and ids.get(s['again_from'], i) <= index < i
               for i, s in enumerate(kit['steps']))


def _elf(path, name=None):
    try:
        real = Path(path).resolve(strict=True)
        with open(real, 'rb') as stream:
            magic = stream.read(4)
    except OSError:
        return False
    return magic == b'\x7fELF' and (name is None or re.fullmatch(name, real.name) is not None)


def reviewed_probe(argv):
    if (len(argv) == 11 and argv[1:4] == ['-I', PROBES[0], '--gh'] and argv[5] == '--repo'
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
    if type(kit) is dict and 'default_terminal_port' in kit:
        raise Refusal('reserved_port')
    base = {'schema', 'mode', 'cwd', 'openwiz', 'artifacts', 'env', 'timeout_seconds', 'steps'}
    if (type(kit) is not dict or not base <= set(kit)
            or not set(kit) - base <= {'source', 'claims', 'release'}):
        raise Refusal('invalid_kit')
    if 'claims' in kit and (type(kit['claims']) is not list or not kit['claims']
                            or any(c not in CLAIMS for c in kit['claims'])
                            or len(set(kit['claims'])) != len(kit['claims'])):
        raise Refusal('invalid_kit')
    if kit['schema'] != 'openwiz.live-smoke-kit.v1' or kit['mode'] not in ('fixture', 'live'):
        raise Refusal('invalid_kit')
    if not isinstance(kit['cwd'], str) or not Path(kit['cwd']).is_absolute() or not Path(kit['cwd']).is_dir():
        raise Refusal('invalid_kit')
    if not integer(kit['timeout_seconds'], 1, 70):
        raise Refusal('invalid_kit')
    if type(kit['artifacts']) is not dict or not kit['artifacts']:
        raise Refusal('invalid_kit')
    for name, sha in kit['artifacts'].items():
        if not Path(name).is_absolute() or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise Refusal('invalid_kit')
    if kit['openwiz'] not in kit['artifacts']:
        raise Refusal('invalid_kit')
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
        if str(Path(__file__).resolve()) not in kit['artifacts'] or 'source' not in kit:
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
                  | ({'token_env'} if 'token_env' in step else set())
                  | ({'timeout_seconds'} if 'timeout_seconds' in step else set())
                  | ({'teardown'} if 'teardown' in step else set()))
            if 'token_env' in step and step['token_env'] != 'OPENWIZ_SMOKE_APP_TOKEN':
                raise Refusal('invalid_kit')
            if 'teardown' in step and (step['teardown'] is not True or step['kind'] != 'read'):
                raise Refusal('invalid_kit')
            if 'timeout_seconds' in step and (not (step['kind'] == 'write' or step.get('teardown'))
                                              or not integer(step['timeout_seconds'], 1, 130)):
                raise Refusal('invalid_kit')
            if step['kind'] not in ('read', 'write', 'await'):
                raise Refusal('invalid_kit')
            argv = step['argv']
            if type(argv) is not list or not argv or any(not isinstance(a, str) or '\0' in a for a in argv):
                raise Refusal('invalid_kit')
            if retired(kit, argv):
                raise Refusal('retired_command')
            if argv[0] not in kit['artifacts'] or not os.access(argv[0], os.X_OK):
                raise Refusal('invalid_kit')
            for arg in argv[1:]:
                if Path(arg).is_absolute() and Path(arg).is_file() and arg not in kit['artifacts']:
                    raise Refusal('invalid_kit')
            refuse_reserved_port(kit, argv)
            if not integer(step['exit'], 0, 255) or type(step['checks']) is not list or not step['checks']:
                raise Refusal('invalid_kit')
            if 'until' in step and (step['kind'] != 'await' or type(step['until']) is not list or not step['until']):
                raise Refusal('invalid_kit')
            for check in step['checks'] + step.get('until', []):
                if type(check) is not dict or set(check) not in (
                    {'path', 'equals'}, {'path', 'same_as'}, {'path', 'one_of'}
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
            if (kit['mode'] == 'live' and step['claim'] == 'fleet' and step['kind'] == 'write'
                    and not reviewed_probe(step['argv'])):
                raise Refusal('invalid_kit')
            claims.add(step['claim'])
        ids.add(step['id'])
        if 'again_from' in step:
            if step['kind'] != 'await' or 'until' not in step or step['claim'] != 'fleet' or step['again_from'] not in ids - {step['id']}:
                raise Refusal('invalid_kit')
            start = next(i for i, s in enumerate(kit['steps']) if s['id'] == step['again_from'])
            block = kit['steps'][start:kit['steps'].index(step)]
            if (any(s['claim'] != 'fleet' or 'again_from' in s or s['kind'] == 'write' for s in block)
                    or not any(s['kind'] == 'event' for s in block)):
                raise Refusal('invalid_kit')
    marks = [bool(s.get('teardown')) for s in kit['steps']]
    if any(marks) and (marks != sorted(marks) or any(s['kind'] == 'event' for s in kit['steps'])):
        raise Refusal('invalid_kit')
    if claims != set(kit_claims(kit)):
        raise Refusal('missing_claim')
    for claim in {'send', 'new'} & claims:
        if not any(s['claim'] == claim and s['kind'] == 'write' for s in kit['steps']):
            raise Refusal('missing_write')
    if 'release' in kit:
        section = release_section(kit)
        if not {s for ids in section['risk'].values() for s in ids} <= {s for r in section['coverage'] for s in r['steps']}:
            raise Refusal('coverage_mismatch')
    return kit


def release_section(kit):
    import importlib.util
    spec = importlib.util.spec_from_file_location('live_smoke_receipt', Path(__file__).resolve().with_name('receipt.py'))
    receipt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receipt)
    try:
        return receipt.release_section(kit)
    except receipt.Refusal as error:
        if str(error) == 'scope_exceeded':
            return kit['release']
        raise Refusal(str(error)) from error


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
    return [int(pid) for pid in Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()]


def enable_containment():
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
    env = dict(os.environ, **kit['env'])
    env.pop('OPENWIZ_SMOKE_APP_TOKEN', None)
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise Refusal('missing_credential')
        env['GH_TOKEN'] = token
        env.pop('GITHUB_TOKEN', None)
    enable_containment()
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
    seen = []
    for check in checks:
        value = pointer(doc, check['path'])
        if 'one_of' in check:
            seen.append({'value': value})
        else:
            seen.append({'digest': digest(value)})
    return seen


def apply(kit, state, event):
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
    elif kind == 'step':
        item.update(state=event['state'], facts=event['facts'])
        if step['kind'] == 'event' and in_block(kit, index):
            state['fleet'].update(sittings=state['fleet']['sittings'] + 1,
                                  started=state['fleet']['started'] or event['at'])
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
    state = initial(kit)
    sha = re.compile('[0-9a-f]{64}')
    ids = {s['id']: i for i, s in enumerate(kit['steps'])}
    for n, event in enumerate(events):
        kind = event.get('kind')
        if (n == 0) != (kind == 'start'):
            raise Refusal('evidence_mismatch')
        if kind == 'start':
            if set(event) != {'kind', 'kit', 'candidate', 'mode', 'runner', 'source', 'at'}:
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
        closing = any(s.get('teardown') and i['state'] != 'not_run' for s, i in zip(kit['steps'], state['steps']))
        before = (bool(step.get('teardown')) and any(state['writes'].values())
                  or all(i['state'] == 'pass' for i in state['steps'][:index]) and not closing)
        pending = state['fleet']['pending']
        if kind == 'attempt':
            if (set(event) != {'kind', 'id', 'claim', 'at'}
                    or step['kind'] != 'write' or event['claim'] != step['claim'] or item['state'] != 'not_run'
                    or not before or pending):
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
                ok = item['state'] in ('not_run', 'incomplete') and before and not pending
            if step['kind'] == 'event':
                ok = (ok and event['state'] == 'pass'
                      and not (in_block(kit, index) and state['fleet']['sittings'] >= SITTINGS))
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
    if (not integer(state['fleet']['sittings'], 0, SITTINGS)
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
                                'missing_credential',
                                'process_containment_unavailable', 'process_containment_failed'):
        raise Refusal('invalid_state')
    return state


def report(kit, state, verdict, reason):
    claims = {}
    for claim in kit_claims(kit):
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


def assess(doc, step, state, ids):
    compare(doc, step['checks'], state, ids)
    try:
        compare(doc, step.get('until', []), state, ids)
    except Refusal as error:
        if str(error) == 'comparison':
            raise Refusal('pending') from error
        raise


def record(path, kit, state, event):
    apply(kit, state, journal(path, event))
    save(path, state)


def reconcile(path, kit, state):
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
    private_dir(path)
    fd = os.open(path / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refusal('runner_busy') from error
        state = reconcile(path, kit, load_state(path, kit))
        bound = bind_candidate(kit, candidate) if candidate is not None else None
        started = (path / JOURNAL).exists()
        if started and state['candidate'] != bound:
            raise Refusal('candidate_changed')
        if not started:
            record(path, kit, state, {
                'kind': 'start', 'kit': digest(kit), 'candidate': bound, 'mode': kit['mode'],
                'runner': file_hash(Path(__file__).resolve()),
                'source': kit['source']['head'] if 'source' in kit else None})
        doc, code = steps(path, kit, state)
        if code and any(state['writes'].values()):
            for index, step in enumerate(kit['steps']):
                if (doc['reason'] != 'teardown' and step.get('teardown')
                        and state['steps'][index]['state'] in ('not_run', 'incomplete')):
                    if not dispatch(path, kit, state, index):
                        break
            ends = [i['state'] for s, i in zip(kit['steps'], state['steps']) if s.get('teardown')]
            if 'fail' in ends:
                return report(kit, state, 'fail', 'teardown'), 1
            if any(e != 'pass' for e in ends):
                return report(kit, state, 'incomplete', 'teardown'), 3
        return doc, code


def dispatch(path, kit, state, index):
    step, seen = kit['steps'][index], {}
    ids = {s['id']: i for i, s in enumerate(kit['steps'])}
    try:
        verify_artifacts(kit)
        code, doc = command(dict(kit, timeout_seconds=step.get('timeout_seconds', kit['timeout_seconds'])),
                            step['argv'], step.get('token_env'), seen)
        if code != step['exit']:
            raise Refusal('command_failed')
        assess(doc, step, state, ids)
    except (Refusal, subprocess.TimeoutExpired) as error:
        reason = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else str(error)
        record(path, kit, state, dict(seen, kind='step', id=step['id'], facts={}, pending=False,
                                      state='fail' if reason == 'comparison' else 'incomplete', reason=reason))
        return False
    record(path, kit, state, dict(seen, kind='step', id=step['id'], state='pass', facts={}, reason='none',
                                  pending=False, observed=observe(doc, step['checks'])))
    return True


def steps(path, kit, state):
    if all(item['state'] == 'pass' for item in state['steps']):
        verify_artifacts(kit)
        if not state['times']['finished']:
            record(path, kit, state, {'kind': 'finish'})
        return report(kit, state, 'pass', 'none'), 0
    if any(s.get('teardown') and i['state'] != 'not_run' for s, i in zip(kit['steps'], state['steps'])):
        return report(kit, state, 'incomplete', 'torn_down'), 3
    if any(s['state'] == 'fail' for s in state['steps']):
        return report(kit, state, 'fail', 'comparison'), 1
    if any(s['state'] == 'attempting' for s in state['steps']):
        return report(kit, state, 'incomplete', 'uncertain_write'), 3
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
            and not 0 <= int(time.time()) - state['fleet']['started'] < FLEET_SECONDS):
        return report(kit, state, 'incomplete', 'fleet_limit'), 3
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
            if state['fleet']['sittings'] >= SITTINGS:
                return report(kit, state, 'incomplete', 'fleet_limit'), 3
            record(path, kit, state, dict(seen, kind='repeat', id=step['id'], again_from=step['again_from']))
        else:
            record(path, kit, state, dict(seen, kind='step', id=step['id'], state='pass', facts={},
                                          reason='none', pending=False,
                                          observed=observe(doc, step['checks'] + step.get('until', []))))
    for index, step in enumerate(kit['steps']):
        item = state['steps'][index]
        if item['state'] == 'pass':
            continue
        if step.get('teardown'):
            if not dispatch(path, kit, state, index):
                failed = state['steps'][index]['state'] == 'fail'
                return report(kit, state, 'fail' if failed else 'incomplete', 'teardown'), 1 if failed else 3
            continue
        if step['kind'] == 'event':
            if in_block(kit, index) and state['fleet']['sittings'] >= SITTINGS:
                return report(kit, state, 'incomplete', 'fleet_limit'), 3
            record(path, kit, state, {'kind': 'step', 'id': step['id'], 'state': 'pass', 'facts': {},
                                      'reason': state['reason'], 'pending': False})
            return report(kit, state, 'incomplete', 'next_event'), 3
        if item['state'] == 'incomplete' and step['kind'] == 'write':
            return report(kit, state, 'incomplete', 'uncertain_write'), 3
        verify_artifacts(kit)
        seen = {}
        if step['kind'] == 'write':
            if ('release' in kit and state['writes'].get(step['claim'], 0)
                    >= kit['release']['scope']['writes'].get(step['claim'], 0)):
                return report(kit, state, 'incomplete', 'write_limit'), 3
            record(path, kit, state, {'kind': 'attempt', 'id': step['id'], 'claim': step['claim']})
        try:
            code, doc = command(dict(kit, timeout_seconds=step.get('timeout_seconds', kit['timeout_seconds'])),
                                step['argv'], step.get('token_env'), seen)
            if code != step['exit']:
                raise Refusal('command_failed')
            assess(doc, step, state, ids)
            facts = {}
            for later in kit['steps'][index + 1:]:
                for check in later.get('checks', []) + later.get('until', []):
                    ref = check.get('same_as')
                    if ref and ref['step'] == step['id']:
                        facts[digest(ref['path'])] = digest(pointer(doc, ref['path']))
            record(path, kit, state, dict(seen, kind='step', id=step['id'], state='pass', facts=facts,
                                          reason='none', pending=False,
                                          observed=observe(doc, step['checks'] + step.get('until', []))))
        except (Refusal, subprocess.TimeoutExpired) as error:
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
    parser = argparse.ArgumentParser(description=DESCRIPTION)
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
            if args.candidate:
                bind_candidate(kit, decode(args.candidate.read_bytes()))
            doc, code = report(kit, initial(kit), 'not_run', 'dry_run'), 0
        else:
            candidate = decode(args.candidate.read_bytes()) if args.candidate else None
            doc, code = run(kit, args.state, candidate)
    except (Refusal, OSError, TypeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, Refusal) else 'invalid_input'
        doc, code = {'schema': 'openwiz.live-smoke.v1', 'verdict': 'incomplete', 'reason': reason}, 2
    print(json.dumps(doc, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
