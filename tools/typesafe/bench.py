#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'skills-eval'))
import client
import decide
import jev_judge
import plan_limit
import verdict

FIXTURES = HERE / 'fixtures'


def judge_case(row):
    old = jev_judge.parse_model_text(row['old_model_text'])
    try:
        shaped = jev_judge.from_response(row['recorded'])
    except client.TypeSafeError:
        shaped = None
    if shaped is None:
        shaped = old
    return old, shaped


def score_judge(data):
    old_hit = shaped_hit = 0
    for row in data['cases']:
        old, shaped = judge_case(row)
        old_hit += int(old is not None and old['verdict'] == row['expected'])
        shaped_hit += int(shaped is not None and shaped['verdict'] == row['expected'])
    return len(data['cases']), old_hit, shaped_hit


def score_plan_limit(data):
    old_hit = shaped_hit = 0
    for row in data['cases']:
        old_hit += int(plan_limit.exact(row['text']) == row['expected'])
        shaped_hit += int(plan_limit.shaped(row['text'], row['recorded']) == row['expected'])
    return len(data['cases']), old_hit, shaped_hit


def score_verdict(data):
    old_hit = shaped_hit = 0
    for row in data['cases']:
        old_hit += int(verdict.exact(row['line']) == row['expected'])
        shaped_hit += int(verdict.shaped(row['line'], row['recorded']) == row['expected'])
    return len(data['cases']), old_hit, shaped_hit


HANDLERS = {
    'openwiz.typesafe-bench.judge.v1': ('judge', score_judge),
    'openwiz.typesafe-bench.plan-limit.v1': ('plan-limit', score_plan_limit),
    'openwiz.typesafe-bench.verdict.v1': ('verdict', score_verdict),
}


def report(path, data):
    name, score = HANDLERS[data['schema']]
    n, old_hit, shaped_hit = score(data)
    print(f'{name}: {n} recorded cases')
    print(f'  previous logic correct: {old_hit}/{n}')
    print(f'  jev-shaped decision correct: {shaped_hit}/{n}')
    print('  recorded answers are fixture input, not a live Jev call')
    return n, old_hit, shaped_hit


def main(argv):
    live = '--live' in argv
    paths = sorted(FIXTURES.glob('*.json'))
    if not paths:
        print('bench: no fixtures', file=sys.stderr)
        return 1
    for path in paths:
        data = json.loads(path.read_text())
        if data.get('schema') not in HANDLERS:
            print(f'bench: unknown schema in {path.name}', file=sys.stderr)
            return 1
        report(path, data)
    if not live:
        print('live: skipped (pass --live with OPENWIZ_JEV=1 and TYPESAFE_API_KEY set)')
        return 0
    ask = client.from_env()
    if ask is None:
        print('live: OPENWIZ_JEV=1 or TYPESAFE_API_KEY is unset; no request was sent', file=sys.stderr)
        return 2
    for path in paths:
        data = json.loads(path.read_text())
        if data['schema'] != 'openwiz.typesafe-bench.judge.v1':
            continue
        hit = sent = 0
        for row in data['cases']:
            if 'rule' not in row or 'reply' not in row:
                continue
            sent += 1
            decided = jev_judge.try_jev(row['rule'], row['reply'], ask)
            hit += int(decided is not None and decided['verdict'] == row['expected'])
        print(f'judge live: {hit}/{sent} matched the fixture label')
    for path in paths:
        data = json.loads(path.read_text())
        if data['schema'] != 'openwiz.typesafe-bench.plan-limit.v1':
            continue
        hit = 0
        for row in data['cases']:
            response = None
            if not plan_limit.exact(row['text']):
                try:
                    response = ask.system_one(row['text'][-4000:], decide.questions('plan_limit'))
                except client.TypeSafeError:
                    response = None
            hit += int(plan_limit.shaped(row['text'], response) == row['expected'])
        print(f'plan-limit live: {hit}/{len(data["cases"])} matched the fixture label')
    for path in paths:
        data = json.loads(path.read_text())
        if data['schema'] != 'openwiz.typesafe-bench.verdict.v1':
            continue
        hit = 0
        for row in data['cases']:
            state = verdict.sent_state(row['line'])
            response = None
            if state is not None:
                try:
                    response = ask.system_one(state, decide.questions('verdict'))
                except client.TypeSafeError:
                    response = None
            hit += int(verdict.shaped(row['line'], response) == row['expected'])
        print(f'verdict live: {hit}/{len(data["cases"])} matched the fixture label')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
