#!/usr/bin/env python3
"""First-hour recovery documents and their codes, for #2222's fault cases.

  codes.py check        stdin: a JSON list of documents; stdout: each one's codes,
                        as #2200's checks give them (first-hour-contract/check.py,
                        loaded by path, as its docstring asks of consumers).
  codes.py owner-cases  runs the owner-state fault cases through the existing
                        interfaces and prints each one's document, codes and what
                        it observed: setup_interrupted through the remote-access
                        setup tool (tools/install/access/access.py) and its
                        recording provider; update_rejected through the
                        installer (tools/install/install.py) on a synthetic bundle.

Stdlib only. Everything runs in a private temporary directory with synthetic
values; nothing reaches a network, an account or a real installation.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[5]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load('first_hour_check', ROOT / 'tools/install/tests/first-hour-contract/check.py')

ASSUMPTIONS = [
    'Synthetic recording-provider fault case at the owner-state seam (#2222): every id, path, digest and route is invented.',
    'No installed candidate, CloudRoom, GitHub or provider account was observed: this proves behaviour at the contract seam only; #2204 reruns it on the installed journey.',
]


def codes(document):
    r = check.check(document)
    return {'problems': r.problems, 'failures': r.failures, 'unproven': r.unproven}


def recovery(interruption, before, after, operations, explanation):
    return {'schema': 'openwiz.first-hour.v1', 'kind': 'recovery', 'verdict': 'unverified',
            'proof_class': 'recording', 'synthetic_assumptions': ASSUMPTIONS, 'private_record': None,
            'candidate': {'unknown': 'no installed candidate: a recording at the owner-state seam'},
            'case': {'interruption': interruption, 'before': before, 'after': after,
                     'operations': operations, 'explanation': explanation}}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def pending_items(value):
    """Every saved setup operation, read back: its id and request fingerprint."""
    return [{'kind': 'pending_operation', 'id': o['operation_id'], 'content': o['fingerprint'],
             'basis': 'owner_state_read_back'} for o in value['operations']]


def setup_interrupted(base):
    """configure_access: its one verification run stops before any reply; resuming reuses its id."""
    sys.path.insert(0, str(ROOT / 'tools/install/access'))
    sys.path.insert(0, str(ROOT / 'tools/install/access/fixtures'))
    import access
    from provider import Recording, credentials, selected
    state, plan_file, secret_file = base / 'state', base / 'plan.json', base / 'secrets.json'
    p, secrets = selected(), credentials()
    for path, value in ((plan_file, p), (secret_file, secrets)):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    provider = Recording(p, secrets)
    read = lambda: access.store.Store(str(state)).read()
    provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': read()['operations']}
    runs = []

    def tool(*args):
        return access.execute(['configure', '--state-dir', str(state), '--plan', str(plan_file), *args],
                              http=provider, local=provider.local)

    def apply(operation_id):
        calls = len(provider.calls)
        try:
            return tool('--yes', '--operation', operation_id, '--secrets', str(secret_file))['operation']
        except SystemExit:
            return None
        finally:
            if len(provider.calls) > calls:
                runs.append(len(provider.calls) - calls)

    proposed = tool()['operation']
    before = pending_items(read())
    calls_before_apply = len(provider.calls)
    provider.interrupt = True
    lost = apply(proposed['operation_id'])
    at_interruption = read()
    phase_before = next(o['phase'] for o in at_interruption['operations'] if o['operation_id'] == proposed['operation_id'])
    # The process starts again (a fresh store over the same directory): the preview reuses the id.
    provider.interrupt = False
    again = tool()['operation']
    resumed = apply(again['operation_id'])
    final = read()
    after = pending_items(final)
    op = next(o for o in final['operations'] if o['operation_id'] == proposed['operation_id'])
    applied = sum(1 for o in final['operations'] if o['fingerprint'] == proposed['fingerprint'] and o['phase'] == 'applied')
    operations = [{'operation_id': proposed['operation_id'], 'kind': 'configure_access',
                   'phase_before': phase_before, 'phase_after': op['phase'], 'effect_count': applied,
                   'attempts': len(runs), 'reconciliation': 'provider_read_back' if len(runs) > 1 else 'none'}]
    document = recovery('setup_interrupted', before, after, operations, {
        'what_happened': 'The access check stopped before any reply; its saved operation stayed uncertain, and the resumed check reused the same operation id and read the exact route back.',
        'took_effect': 'yes' if applied else ('unknown' if op['phase'] == 'uncertain' else 'no'),
        'next_action': 'Nothing to repeat: the route is recorded as checked; phone readiness still needs current evidence.'})
    document['synthetic_assumptions'] = ASSUMPTIONS + [
        "configure_access makes no provider write: its effect is the owner-state record of the checked route, counted once per applied settlement; each verification run that reached the recording provider is one attempt, and every run after the first re-reads the provider's exact route."]
    observed = {'calls_before_apply': calls_before_apply, 'lost_reply_returned': lost is not None,
                'same_operation_id': again['operation_id'] == proposed['operation_id'],
                'resumed_phase': None if resumed is None else resumed['phase'],
                'operations_saved': len(final['operations']),
                'provider_writes': sum(1 for c in provider.calls if c[0] not in ('GET', 'local-read'))}
    return document, observed


def update_rejected(base):
    """A refused update of an installed candidate: the last good build stays selected, owner work stays."""
    sys.path.insert(0, str(ROOT / 'tools/install'))
    sys.path.insert(0, str(ROOT / 'tools/install/setup'))
    import fixture_bundle
    import install
    import store
    root = base / 'installed'
    # A private, owned directory whatever the runner's umask: install.py refuses any other root (install.v1).
    root.mkdir(mode=0o700)
    good = fixture_bundle.create(base / 'good', source='1' * 40)
    target = 'x86_64-unknown-linux-gnu'
    with contextlib.redirect_stdout(io.StringIO()):
        install.install(good['manifest'], good['archive'], good['checksum'], root, target)
    current = os.readlink(root / 'current')
    owner = store.Store(str(root / 'state'))
    owner.propose('prepare_project', {'repository': 'syn-owner/syn-first-hour', 'project': 'prj_syn_0001'},
                  ['Synthetic: save the selected project.'], 'Proposed: confirm with --yes --operation.')

    def inventory():
        value = owner.read()
        return [{'kind': 'setup_state', 'id': 'setup/state.json', 'content': canonical_sha(value),
                 'basis': 'owner_state_read_back'}] + pending_items(value)

    before = inventory()
    update = fixture_bundle.create(base / 'update', source='2' * 40)
    Path(update['archive']).write_bytes(Path(update['archive']).read_bytes() + b'synthetic corruption')
    refused = None
    try:
        install.install(update['manifest'], update['archive'], update['checksum'], root, target)
    except install.Refused as error:
        refused = str(error)
    after = inventory()
    proposal = owner.read()['operations'][0]
    operations = [{'operation_id': proposal['operation_id'], 'kind': 'prepare_project', 'phase_before': 'proposed',
                   'phase_after': proposal['phase'], 'effect_count': 0, 'attempts': 0, 'reconciliation': 'none'}]
    document = recovery('update_rejected', before, after, operations, {
        'what_happened': 'The update was refused before activation; the last good build stays selected and the saved setup state and its proposal are unchanged.',
        'took_effect': 'no',
        'next_action': 'Keep using the selected build; get a verified update before installing again.'})
    observed = {'update_refused': refused, 'last_good_selected': os.readlink(root / 'current') == current,
                'update_build_absent': not (root / 'state/service/builds' / ('2' * 40)).exists()}
    return document, observed


def owner_cases():
    results = []
    for name, case in (('setup_interrupted', setup_interrupted), ('update_rejected', update_rejected)):
        with tempfile.TemporaryDirectory(prefix='openwiz-first-hour-') as temp:
            base = Path(temp)
            os.chmod(base, 0o700)
            with contextlib.redirect_stdout(io.StringIO()):
                document, observed = case(base)
        results.append({'name': name, 'document': document, 'codes': codes(document), 'observed': observed})
    return results


def main():
    command = sys.argv[1] if len(sys.argv) == 2 else None
    if command == 'check':
        print(json.dumps([codes(d) for d in json.loads(sys.stdin.read())]))
    elif command == 'owner-cases':
        print(json.dumps(owner_cases()))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
