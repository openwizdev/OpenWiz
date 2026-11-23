#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import resource
import runpy
import subprocess
import tempfile

DESCRIPTION = """One approved T3 cleanup write, then a separately checked readback. No retry."""

smoke = runpy.run_path(str(Path(__file__).with_name('smoke.py')))


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--gh', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--ticket', required=True)
    parser.add_argument('--action', required=True, choices=['unlabel', 'close'])
    args = parser.parse_args()
    try:
        if (not Path(args.gh).is_absolute() or not args.ticket.isascii()
                or not args.ticket.isdigit() or args.ticket.startswith('0')):
            raise ValueError()
        limit = smoke['LIMIT']
        for inherited in resource.getrlimit(resource.RLIMIT_FSIZE):
            if inherited != resource.RLIM_INFINITY:
                limit = min(limit, inherited)
        if limit < 1:
            raise ValueError()
        prefix = [args.gh, 'issue']
        target = [args.ticket, '--repo', args.repo]
        write = (prefix + ['edit'] + target + ['--remove-label', 'needs-info']
                 if args.action == 'unlabel' else prefix + ['close'] + target)
        result = subprocess.run(write, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=25)
        if result.returncode != 0:
            raise ValueError()
        with tempfile.TemporaryFile() as output:
            def bound_output():
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))

            read = subprocess.run(prefix + ['view'] + target + ['--json', 'number,state,labels'],
                                  stdin=subprocess.DEVNULL, stdout=output,
                                  stderr=subprocess.DEVNULL, timeout=25,
                                  preexec_fn=bound_output)
            if read.returncode != 0 or output.seek(0, 2) >= limit:
                raise ValueError()
            output.seek(0)
            raw = output.read(limit + 1)
            if len(raw) >= limit:
                raise ValueError()
            doc = smoke['decode'](raw)
        smoke['exact'](doc, {'number', 'state', 'labels'})
        if (type(doc['number']) is not int or doc['number'] != int(args.ticket)
                or doc['state'] not in ('OPEN', 'CLOSED') or type(doc['labels']) is not list
                or any(type(label) is not dict or type(label.get('name')) is not str for label in doc['labels'])):
            raise ValueError()
        print(json.dumps({'state': doc['state'],
                          'needs_info': any(label['name'] == 'needs-info' for label in doc['labels'])}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, smoke['Refusal']):
        print(json.dumps({'unavailable': True}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
