"""The live smoke's expected-plan restriction for `openwiz fleet tick` (#2216).

#1892 (PR #2024) added `openwiz fleet tick --expect-plan PATH --json`: given
the exact reviewed `--dry-run --json` document, the tick refuses before any
effect when its own current plan differs (an extra, missing, reordered or
changed action, other rules or default branch) or when a pending start would
need recovery (contracts/fleet-tick.v1.md, "Reviewed-plan execution").

This module is the runner's only way to tick. `establish` reads the installed
binary's catalogue and refuses unless it offers the restriction, takes one
preview, validates its envelope and action fields, lets the caller audit it, then saves it
owner-only in the runner's private state. `execute` launches the pinned form
once and accepts only a run report of exactly the saved actions. It never
falls back to an unpinned tick and never retries. Every refusal is one of
REASONS; nothing here prints or keeps a raw document.

Nested rules and action facts remain opaque here: the caller's audit supplies
the kit's scope, and the reviewed product validates the whole typed plan before
effects. This wrapper never substitutes for either check.

`launch(argv) -> (exit code, stdout bytes)` is the caller's bounded command
runner; its own exceptions propagate unchanged. The caller records the attempt
durably between `establish` and `execute`: from `execute` on, a write may have
happened. Standard library only.
"""
import json
import math
import os
from pathlib import Path
import stat

REASONS = (
    'restriction_unavailable',  # the binary does not offer --expect-plan
    'invalid_plan',             # the preview was not one exact dry-run document
    'out_of_scope',             # the caller's audit refused the preview
    'unsafe_plan_dir',          # the plan cannot be saved privately
    'plan_exists',              # an earlier plan was left behind: never reused
    'tick_refused',             # the tick refused or failed before any report
    'plan_mismatch',            # the tick reported anything but the saved plan
    'uncertain_write',          # any other result: the attempt is consumed
)
PLAN_NAME = 'fleet-expected-plan.json'
LIMIT = 32 * 1024 * 1024
SCHEMA = 'openwiz.fleet-tick.v1'
FIELDS = {'schema', 'mode', 'planned_at', 'default_branch', 'rules', 'actions'}
ACTION = {'kind', 'rule', 'spec', 'ticket', 'facts', 'outcome'}
PLANNED = {'state': 'planned'}
ERROR = {'schema': 'openwiz.cli-error.v1', 'command': 'fleet.tick', 'exit_code': 1}


class Refused(Exception):
    """A refusal; its text is always one of REASONS."""

    def __init__(self, reason):
        assert reason in REASONS
        super().__init__(reason)


class Pinned:
    """A validated, saved preview and the one execution argv that reads it."""

    def __init__(self, plan, path, argv):
        self.plan, self.path, self.argv = plan, path, argv


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _constant(name):
    raise ValueError('non-finite number')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite number')
    return number


def decode(raw, reason):
    """One strict JSON document: UTF-8, no duplicate key at any depth, no NaN."""
    try:
        if type(raw) is not bytes or len(raw) > LIMIT:
            raise ValueError('not bounded bytes')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant, parse_float=_float)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refused(reason) from error


def canonical(value):
    """Key order is immaterial; array order and JSON types (1, 1.0, true) are not."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':'), allow_nan=False).encode()


def _number(value, low, high):
    return type(value) is int and low <= value <= high


def _envelope(doc, mode):
    return (type(doc) is dict and set(doc) == FIELDS and doc['schema'] == SCHEMA
            and doc['mode'] == mode and _number(doc['planned_at'], 0, 2**64 - 1)
            and type(doc['default_branch']) is str and doc['default_branch']
            and type(doc['rules']) is dict and type(doc['actions']) is list)


def _action(action):
    return (type(action) is dict and set(action) == ACTION
            and type(action['kind']) is str and type(action['rule']) is str
            and _number(action['spec'], 1, 2**53)
            and (action['ticket'] is None or _number(action['ticket'], 1, 2**53))
            and type(action['facts']) is dict and type(action['outcome']) is dict)


def available(catalogue):
    """The installed binary's own catalogue lists exactly one fleet tick with the restriction."""
    if (type(catalogue) is not dict or catalogue.get('schema') != 'openwiz.cli.v1'
            or catalogue.get('kind') != 'catalogue' or type(catalogue.get('commands')) is not list):
        return False
    ticks = [c for c in catalogue['commands'] if type(c) is dict and c.get('name') == 'fleet.tick']
    return (len(ticks) == 1 and ticks[0].get('argv') == ['fleet', 'tick']
            and type(ticks[0].get('flags')) is list and '--expect-plan' in ticks[0]['flags'])


def expected_plan(doc):
    """The preview as the reviewed plan: one exact dry run, every outcome planned."""
    if not _envelope(doc, 'dry_run') or any(
            not _action(a) or a['outcome'] != PLANNED for a in doc['actions']):
        raise Refused('invalid_plan')
    return doc


def _private_dir(directory):
    try:
        if not directory.is_absolute():
            raise OSError('relative')
        info = directory.lstat()
    except OSError as error:
        raise Refused('unsafe_plan_dir') from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refused('unsafe_plan_dir')


def save(directory, plan):
    """Create the plan file owner-only and exclusively, durably; never replace one."""
    _private_dir(directory)
    path = directory / PLAN_NAME
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as error:
        raise Refused('plan_exists') from error
    except OSError as error:
        raise Refused('unsafe_plan_dir') from error
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(plan) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        folder = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    except OSError as error:
        _discard(path)
        raise Refused('unsafe_plan_dir') from error
    return path


def _discard(path):
    # A plan that cannot be removed stays behind, and `save` then refuses
    # every later tick with `plan_exists`: failing closed, never reusing it.
    try:
        os.unlink(path)
    except OSError:
        pass


def establish(openwiz, directory, launch, audit=lambda plan: True):
    """Everything before the first possible effect; launches only read-only forms."""
    if type(openwiz) is not str or not Path(openwiz).is_absolute():
        raise Refused('restriction_unavailable')
    directory = Path(directory)
    _private_dir(directory)
    code, raw = launch([openwiz, 'help', '--agent'])
    if code != 0 or not available(decode(raw, 'restriction_unavailable')):
        raise Refused('restriction_unavailable')
    code, raw = launch([openwiz, 'fleet', 'tick', '--dry-run', '--json'])
    if code != 0:
        raise Refused('invalid_plan')
    plan = expected_plan(decode(raw, 'invalid_plan'))
    if audit(json.loads(canonical(plan))) is not True:
        raise Refused('out_of_scope')
    path = save(directory, plan)
    return Pinned(plan, path, [openwiz, 'fleet', 'tick', '--expect-plan', str(path), '--json'])


def outcome(plan, code, raw):
    """Classify one restricted execution against the saved plan."""
    if code == 1:
        doc = decode(raw, 'uncertain_write')
        if (type(doc) is dict and set(doc) == set(ERROR) | {'error'}
                and all(doc[k] == v and type(doc[k]) is type(v) for k, v in ERROR.items())
                and type(doc['error']) is dict and set(doc['error']) == {'kind', 'message'}
                and doc['error']['kind'] == 'read_failed' and type(doc['error']['message']) is str):
            raise Refused('tick_refused')
        raise Refused('uncertain_write')
    if code != 0:
        raise Refused('uncertain_write')
    doc = decode(raw, 'uncertain_write')
    if (not _envelope(doc, 'run') or len(doc['actions']) != len(plan['actions'])
            or canonical(doc['rules']) != canonical(plan['rules'])
            or doc['default_branch'] != plan['default_branch']):
        raise Refused('plan_mismatch')
    for done, planned in zip(doc['actions'], plan['actions']):
        if (not _action(done) or done['outcome'] == PLANNED
                or canonical(dict(done, outcome=PLANNED)) != canonical(planned)):
            raise Refused('plan_mismatch')
        result = done['outcome']
        if not (result == {'state': 'done'} or (
                set(result) == {'state', 'reason'}
                and type(result['state']) is str
                and result['state'] in ('refused', 'failed', 'uncertain')
                and type(result['reason']) is str and result['reason'])):
            raise Refused('uncertain_write')
    # Per-action outcomes (done, refused, failed, uncertain) are the caller's.
    return doc


def execute(pinned, launch):
    """Launch the pinned tick exactly once, then remove the saved plan."""
    try:
        code, raw = launch(pinned.argv)
    finally:
        _discard(pinned.path)
    return outcome(pinned.plan, code, raw)

