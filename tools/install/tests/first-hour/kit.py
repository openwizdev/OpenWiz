#!/usr/bin/env python3
"""The first-hour live kit's offline dry run, eligibility check and result validator (#2204).

  kit.py dry-run [RECORD]            walk every step of first-hour-live-kit.md with a
                                     simulated clock and no effect, and say whether final
                                     execution is refused
  kit.py eligibility RECORD          refuse final execution while a gate, producer,
                                     graph or authority is missing (exit 0 eligible, 5 refused)
  kit.py validate RESULT --binding BINDING --eligibility RECORD
                                     check one recorded first-hour result against the
                                     kit's binding (exit 0 valid, 5 refused)

Nothing here performs a live action: every command only reads its files. A
passing dry run or validation proves the kit's shape and rules, never a live
result, an elapsed time or a usable login. Stdlib only.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
KIT = ROOT / 'tools/install/first-hour-live-kit.md'
_spec = importlib.util.spec_from_file_location('first_hour_kit_check', ROOT / 'tools/install/tests/first-hour-contract/check.py')
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

GATES = {'cloudroom_setup': 2201, 'paid_offer': 2202, 'feedback': 2203}
SCOPES = ('live', 'account', 'feedback_send', 'spending')
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
COUNTS = ('builders', 'reviewers', 'merges', 'feedback_issues', 'shares')
POINTER = re.compile(r'https://github\.com/jparker2006/ClosedWiz/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*')
HEX40, HEX64 = re.compile(r'[0-9a-f]{40}'), re.compile(r'[0-9a-f]{64}')
REPOSITORY = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}')
PRIVATE = re.compile(r'thr_[A-Za-z0-9]|prj_[A-Za-z0-9]|gh[pousr]_[A-Za-z0-9]|github_pat_|[^\s@"]+@[^\s@"]+\.[a-z]{2,}|'
                     r'-----BEGIN|/(?:home|Users)/', re.I)


def steps():
    """The kit's steps from its own table: (id, name, effect, the gate it needs or None)."""
    rows = re.findall(r'^\| (H[0-9]+) \| ([a-z-]+) \| (read|write|spend) \| (none|%s) \| (.+) \|$' % '|'.join(GATES),
                      KIT.read_text(), re.M)
    return [(s, name, effect, None if needs == 'none' else needs) for s, name, effect, needs, _ in rows]


def integer(value, low=0):
    return type(value) is int and value >= low


def exact(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def eligibility(record):
    """Every reason final execution is refused; empty means eligible."""
    if not exact(record, ('schema', 'graph', 'gates', 'authority')) or record['schema'] != 'openwiz.first-hour-kit-eligibility.v1':
        return ['The eligibility record must be openwiz.first-hour-kit-eligibility.v1 with exactly its fields.']
    out = []
    g = record['graph']
    if not (exact(g, ('revision', 'fingerprint', 'approval')) and integer(g['revision'], 1)
            and isinstance(g['fingerprint'], str) and HEX64.fullmatch(g['fingerprint'])
            and isinstance(g['approval'], str) and POINTER.fullmatch(g['approval'])):
        out.append('The approved #2194 graph revision, fingerprint and approval pointer are missing or malformed.')
    gates = record['gates']
    if not exact(gates, GATES):
        return out + ['The record must name exactly the three first-hour gates.']
    for name, ticket in GATES.items():
        producers = gates[name]
        if not isinstance(producers, list) or not producers:
            out.append('Gate %s (#%d) has no producer in the approved graph: ineligible until one is added and merged.'
                       % (name, ticket))
            continue
        for p in producers:
            ok = (exact(p, ('ticket', 'pr', 'merge_commit', 'approved_head', 'merged_at_head'))
                  and integer(p['ticket'], 1) and integer(p['pr'], 1)
                  and all(isinstance(p[k], str) and HEX40.fullmatch(p[k]) for k in ('merge_commit', 'approved_head')))
            if not ok:
                out.append('Gate %s has a malformed producer.' % name)
            elif p['merged_at_head'] is not True:
                out.append('Gate %s producer #%d has no verified merge at its approved head (a closed issue is not one).'
                           % (name, p['ticket']))
    auth = record['authority']
    if not exact(auth, SCOPES):
        return out + ['The record must name exactly the authority scopes %s.' % ', '.join(SCOPES)]
    for scope in SCOPES:
        if not (isinstance(auth[scope], str) and POINTER.fullmatch(auth[scope])):
            out.append('No recorded %s authority for these exact steps and counts.' % scope)
    return out


def verified_producers(record):
    return {name: sorted(p['ticket'] for p in record['gates'][name] if isinstance(p, dict) and p.get('merged_at_head') is True)
            for name in GATES}


def binding_errors(b):
    if not exact(b, ('schema', 'candidate', 'host', 'scope', 'counts', 'recorded', 'graph')) \
            or b['schema'] != 'openwiz.first-hour-kit-binding.v1':
        return ['The binding must be openwiz.first-hour-kit-binding.v1 with exactly its fields.']
    out = []
    c = b['candidate']
    if not (exact(c, ('version', 'source', 'target', 'manifest_sha256')) and isinstance(c['version'], str)
            and re.fullmatch(r'0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', c['version'])
            and isinstance(c['source'], str) and HEX40.fullmatch(c['source']) and c['target'] in TARGETS
            and isinstance(c['manifest_sha256'], str) and HEX64.fullmatch(c['manifest_sha256'])):
        out.append('The bound candidate is malformed.')
    h = b['host']
    if not (exact(h, ('target', 'fresh_account')) and h['fresh_account'] is True and isinstance(c, dict) and h['target'] == c.get('target')):
        out.append('The host must be a fresh account on the candidate\'s target.')
    s = b['scope']
    if not (exact(s, ('repository', 'app_repositories')) and isinstance(s['repository'], str)
            and REPOSITORY.fullmatch(s['repository']) and s['app_repositories'] == [s['repository']]):
        out.append('The scope must be one owner-authorized repository, with the App on it only.')
    n = b['counts']
    if not (exact(n, COUNTS) and all(integer(n[k]) for k in COUNTS) and n['feedback_issues'] <= 1 and n['shares'] <= 1):
        out.append('The counts are malformed or exceed one feedback issue and one share.')
    r = b['recorded']
    if not (exact(r, ('waits', 'help')) and integer(r['waits']) and integer(r['help'])):
        out.append('The recorded wait and help counts are malformed.')
    g = b['graph']
    if not (exact(g, ('revision', 'fingerprint')) and integer(g['revision'], 1) and isinstance(g['fingerprint'], str)
            and HEX64.fullmatch(g['fingerprint'])):
        out.append('The bound graph is malformed.')
    return out


def strings(value):
    """Every decoded string in a JSON value, keys included: JSON escapes never hide one from the scan."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def validate(text, binding, record):
    """(refusals, codes): every rule the result breaks against the kit, one plain line each."""
    malformed = binding_errors(binding)
    out = malformed + eligibility(record)
    report = check.check_text(text)
    codes = {'problems': report.problems, 'failures': report.failures, 'unproven': report.unproven}
    if report.problems:
        return out + ['#2200\'s checks refuse the result: ' + ', '.join(report.problems)], codes
    doc = json.loads(text)
    if doc['kind'] != 'result':
        return out + ['A kit result is a first-hour result, not a recovery case.'], codes
    if doc['proof_class'] != 'live':
        out.append('A %s document is synthetic proof, not a live observation.' % doc['proof_class'])
    if malformed:
        return out, codes
    if doc['candidate'].get('known') != binding['candidate']:
        out.append('The result is for another candidate than the bound one.')
    if doc['repository'].get('known', {}).get('full_name') != binding['scope']['repository']:
        out.append('The result is for another repository than the bound one.')
    if record.get('graph', {}).get('revision') != binding['graph']['revision'] \
            or record.get('graph', {}).get('fingerprint') != binding['graph']['fingerprint']:
        out.append('The binding names another graph revision than the eligibility record.')
    kinds = [o['kind'] for o in doc['operations']]
    starts = kinds.count('start_agent')
    limits = binding['counts']
    if starts > limits['builders'] + limits['reviewers']:
        out.append('The run started more agents than the bound builders and reviewers.')
    if kinds.count('merge') > limits['merges']:
        out.append('The run merged more than the bound merges.')
    if len(doc['waits']) != binding['recorded']['waits'] or len(doc['help']) != binding['recorded']['help']:
        out.append('The result does not keep every wait and help the run recorded.')
    if isinstance(record, dict) and exact(record.get('gates'), GATES):
        expect = verified_producers(record)
        for name, gate in doc['gates'].items():
            if sorted(gate['producers']) != expect.get(name):
                out.append('Gate %s does not match the verified producers.' % name)
    if any(PRIVATE.search(s) for s in strings(doc)):
        out.append('The result holds something that looks like an account, id, token, email or path.')
    return out, codes


def dry_run(record=None, out=sys.stdout):
    """Every step in order, with a simulated clock and no effect; then final execution's refusals."""
    refusals = eligibility(record) if record is not None else ['No eligibility record was given.']
    verified = verified_producers(record) if isinstance(record, dict) and exact(record.get('gates'), GATES) else {}
    clock = 0
    for step, name, effect, needs in steps():
        clock += 60000
        if needs is None:
            status = 'would run'
        elif verified.get(needs):
            status = 'would run (%s: producers %s)' % (needs, ', '.join('#%d' % t for t in verified[needs]))
        else:
            status = 'ineligible: gate %s has no verified producer' % needs
        print('%s %s (%s) at +%d ms: %s; no effect in a dry run' % (step, name, effect, clock, status), file=out)
    print('The dry run sets no elapsed time and observes nothing live.', file=out)
    for line in refusals:
        print('Final execution refused: ' + line, file=out)
    if not refusals:
        print('Final execution eligible within the recorded authority.', file=out)
    return 0


def main(argv):
    if argv[:1] == ['dry-run'] and len(argv) <= 2:
        return dry_run(json.loads(Path(argv[1]).read_text()) if len(argv) == 2 else None)
    if len(argv) == 2 and argv[0] == 'eligibility':
        refusals = eligibility(json.loads(Path(argv[1]).read_text()))
        for line in refusals or ['Eligible: the kit may run within its recorded authority.']:
            print(line)
        return 5 if refusals else 0
    if len(argv) == 6 and argv[0] == 'validate' and argv[2] == '--binding' and argv[4] == '--eligibility':
        refusals, codes = validate(Path(argv[1]).read_text(), json.loads(Path(argv[3]).read_text()),
                                   json.loads(Path(argv[5]).read_text()))
        print(json.dumps({'refusals': refusals, 'codes': codes}, indent=1))
        return 5 if refusals else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
