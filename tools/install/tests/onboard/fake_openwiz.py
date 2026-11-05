#!/usr/bin/env python3
"""A recording fake of the installed `openwiz` for the onboarding journey (#1108).

It answers only the agent-CLI forms the onboarding helper uses, as
contracts/cli.v1.md names them, from a scripted queue in $FAKE_OPENWIZ_SCRIPT
(JSON: {"<form>": [{"exit": N, "stdout": <text or JSON value>}, ...]}), one
answer per call, in order. It logs every call to $FAKE_OPENWIZ_LOG as one JSON
line. It never delegates to a real openwiz, room-cli or gh. Any other form, or
a form with no answer left, exits 99 so the test sees the unexpected call.

Forms: `fleet.tick.preview` (fleet tick --dry-run --json), `fleet.tick`
(fleet tick --expect-plan PATH --json; the log keeps the plan file's SHA-256)
and `fleet` (fleet <spec> --json). All values are synthetic.
"""
import hashlib
import json
import os
import sys


def form(argv):
    if argv == ['fleet', 'tick', '--dry-run', '--json']:
        return 'fleet.tick.preview', None
    if len(argv) == 5 and argv[:3] == ['fleet', 'tick', '--expect-plan'] and argv[4] == '--json':
        return 'fleet.tick', argv[3]
    if len(argv) == 3 and argv[0] == 'fleet' and argv[1].isdigit() and argv[2] == '--json':
        return 'fleet', None
    return None, None


def main():
    argv = sys.argv[1:]
    name, plan = form(argv)
    entry = {'argv': argv, 'form': name}
    if plan is not None:
        try:
            with open(plan, 'rb') as handle:
                entry['plan_sha256'] = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            entry['plan_sha256'] = None
    with open(os.environ['FAKE_OPENWIZ_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(entry, sort_keys=True) + '\n')
    script_path = os.environ['FAKE_OPENWIZ_SCRIPT']
    with open(script_path, encoding='utf-8') as handle:
        script = json.load(handle)
    queue = script.get(name) if name else None
    if not queue:
        sys.stderr.write('fake openwiz: unexpected call\n')
        return 99
    answer = queue.pop(0)
    with open(script_path, 'w', encoding='utf-8') as handle:
        json.dump(script, handle)
    out = answer.get('stdout', '')
    if not isinstance(out, str):
        out = json.dumps(out) + '\n'
    sys.stdout.write(out)
    return answer['exit']


if __name__ == '__main__':
    sys.exit(main())
