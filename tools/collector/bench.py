#!/usr/bin/env python3
"""FF1 (#1331): the before bench. Red-run stub: unknowns are read as zero."""
import json
import sys

SCHEMA = 'openwiz.faster-factory.bench.v1'
RULES = ()


class Unreadable(Exception):
    pass


def gather(repo, since, until, reads):
    merges = reads.merges(since, until)['value']['pull_requests']
    return {'tickets': sorted({t for pr in merges for t in pr['tickets']})}


def measure(gathered):
    zero = {'known': 0, 'unknown': 0, 'p50': 0, 'p75': 0, 'max': 0, 'sum': 0}
    return {'tickets': [{'ticket': n, 'hours': dict.fromkeys(('builder', 'ci', 'wake', 'review', 'rework', 'total'), 0),
                         'review_rounds': 0, 'waits_minutes': {}, 'unknown': []} for n in gathered['tickets']],
            'heads': [], 'ci': {'time_to_result': None},
            'summary': {'hours': {'builder': zero}, 'review_rounds': zero, 'waits_minutes': {'merge': zero},
                        'ci_per_head': {'slowest_job_minutes': zero, 'runner_minutes': zero}}}


def main(argv, reads=None):
    args = dict(zip(argv[::2], argv[1::2]))
    measure(gather(args['--repo'], args.get('--since'), args.get('--until'), reads))
    with open(args['--out'], 'w') as f:
        json.dump({'schema': SCHEMA}, f)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
