#!/usr/bin/env python3
"""Synthetic gh only: answers explicit fixture keys, never a network call."""
import json
import os
import sys

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    fields = dict(arg.split('=', 1) for arg in args if '=' in arg)
    key = 'graph:' + fields.get('number', 'prs') + ':' + fields.get('cursor', '')
elif args[:3] == ['api', '--method', 'GET']:
    key = args[3]
elif args[:1] == ['api']:
    key = args[1]
else:
    sys.exit(2)
with open(os.environ['WR8_FIXTURE'], encoding='utf-8') as stream:
    answers = json.load(stream)
if key not in answers:
    print('synthetic source unavailable', file=sys.stderr)
    sys.exit(1)
print(json.dumps(answers[key]))
