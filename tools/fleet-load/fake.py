#!/usr/bin/env python3
"""Recording, file-backed command endpoints; unknown commands fail closed.

Read responses reuse launch-fleet's existing synthetic gh. Writes only change
LOAD_WORLD inside a TemporaryDirectory. There is no real-command fallback.
"""
import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def save(path, data):
    Path(path).write_text(json.dumps(data))


def main():
    tool, *args = sys.argv[1:]
    path = os.environ['FAKE_GH_WORLD']
    world = json.loads(Path(path).read_text())
    now = int(os.environ['LAUNCH_FLEET_NOW'])
    caller = os.environ['LOAD_FLEET']
    requests, expected = [], []
    event = dict(tool=tool, args=args, now=now, fleet=caller, kind='command', cost=0)
    status = 0
    result = ''

    def effect(kind, **fields):
        event.update(kind=kind, **fields)

    def option(key):
        return args[args.index(key) + 1]

    def item(number):
        return next(x for x in world['issues'] + world['pulls'] if x['number'] == number)

    def comment(number, body):
        ident = world['_next']
        world['_next'] += 1
        item(number)['comments'].append(dict(id=ident, at=stamp(now), body=body))
        return str(ident)

    def begin(agent):
        running = sum(a.get('execution') == 'running' for a in world['_threads'].values())
        agent['execution'] = 'running' if running < 50 else 'queued'
        return agent['execution']

    if tool == 'room-cli':
        assert args[0] == 'thread'
        verb = args[1]
        if verb == 'list':
            return json.dumps([dict(id=ident, archivedAt=('synthetic' if agent['archived'] else None)) for ident, agent in world['_threads'].items()])
        if verb == 'spawn':
            assert '--parent-self' in args and '--top-level' not in args
            title = option('--title')
            if title.startswith('Review #'):
                role, number = 'reviewer', int(re.fullmatch(r'Review #([0-9]+) at [0-9a-f]+', title)[1]) - 1000
            else:
                role, number = 'builder', int(re.fullmatch(r'#([0-9]+): Synthetic', title)[1])
            ident = f'thr_synfake{world["_next"]}'
            world['_next'] += 1
            agent = dict(owner=caller, role=role, ticket=number, archived=False)
            execution = begin(agent) if os.environ.get('LOAD_SCALE') else 'running'
            agent['execution'] = execution
            world['_threads'][ident] = agent
            effect('spawn', thread=ident, role=role, ticket=number, execution=execution)
            result = json.dumps({'id': ident})
        elif verb in ('tell', 'output', 'archive'):
            ident = args[2]
            agent = world['_threads'][ident]
            assert agent['owner'] == caller, 'S1 owner: endpoint refuses a foreign agent'
            assert not agent['archived'] or verb == 'archive'
            began = False
            if verb == 'archive':
                if os.environ.get('LOAD_SCALE'):
                    assert agent['execution'] == 'idle', 'cannot archive synthetic running/queued work'
                agent['archived'] = True
            elif verb == 'tell' and os.environ.get('LOAD_SCALE') and agent['execution'] == 'idle':
                if args[3].startswith(('findings ', 'CI failed ', 're-check ')):
                    began = begin(agent) == 'running'
            effect(verb, thread=ident, role=agent['role'], ticket=agent['ticket'],
                   execution=agent['execution'], began=began)
            result = '{}'
        else:
            raise AssertionError(f'unsupported fake room-cli: {args}')
    elif tool == 'gh' and args[:2] in (['issue', 'comment'], ['pr', 'comment']):
        result = comment(int(args[2]), option('--body'))
        effect('comment')
    elif tool == 'gh' and args[:2] == ['api', '--method']:
        assert args[2] == 'PATCH' and re.fullmatch(r'repos/synthetic-owner/synthetic-repo/issues/comments/[0-9]+', args[3])
        ident = int(args[3].rsplit('/', 1)[1])
        body = option('-f')
        assert body.startswith('body=')
        target = next(c for x in world['issues'] + world['pulls'] for c in x['comments'] if c['id'] == ident)
        target.update(body=body[5:], edited=stamp(now))
        effect('edit')
    elif tool == 'gh' and args[:2] == ['issue', 'close']:
        assert len(args) == 3
        item(int(args[2]))['state'] = 'CLOSED'
        effect('close-spec', spec=int(args[2]))
    elif tool == 'gh' and args[:2] == ['pr', 'merge']:
        pull = item(int(args[2]))
        assert '--merge' in args and option('--match-head-commit') == pull['head']
        assert pull['state'] == 'OPEN'
        ci_green = ({c['name'] for c in pull['checks']} == {'build', 'test'}
                    and all(c['status'] == 'COMPLETED' and c['conclusion'] == 'SUCCESS' for c in pull['checks']))
        verdict = next((c['body'] for c in reversed(pull['comments']) if c['body'].startswith('VERDICT: ')), '')
        approved = verdict == f'VERDICT: APPROVE at {pull["head"]}'
        assert ci_green and approved, 'S2 unsafe merge: missing CI or approval'
        pull.update(state='MERGED', mergedAt=stamp(now), updatedAt=stamp(now), mergeCommit=pull['head'])
        for number in pull['closes']:
            item(number)['state'] = 'CLOSED'
        effect('merge', ticket=pull['closes'][0], head=pull['head'], ci_green=ci_green, approved=approved)
    elif tool == 'gh':
        spec = importlib.util.spec_from_file_location('fixture_gh', HERE / '../../skills/launch-fleet/scripts/fixtures/gh.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        transport_spec = importlib.util.spec_from_file_location('transport', HERE / 'transport.py')
        transport = importlib.util.module_from_spec(transport_spec)
        transport_spec.loader.exec_module(transport)
        transport.install(fixture, requests, expected)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = fixture.run(args)
        result = out.getvalue()
        if args[:2] == ['api', 'graphql']:
            rate = json.loads(result).get('data', {}).get('rateLimit', {})
            event['cost'] = rate.get('cost', 0)
        elif args[:2] == ['issue', 'view']:
            event['cost'] = 1  # Same documented accounting as FA1's revision reads.
        elif args[:2] == ['api', '--include']:
            # The next page this response's Link names (as fleet.sh reads it), for S4's pagination chain.
            head = result.replace('\r\n', '\n').split('\n\n', 1)[0]
            event['next'] = next((m[1] for line in head.split('\n') if line.lower().startswith('link:')
                                  for m in re.finditer(r'<https://api\.github\.com/([^>]+)>; *rel="next"', line)), None)
    else:
        raise AssertionError(f'unsupported fake command: {tool}')
    if tool == 'gh':
        if not requests:
            transport_spec = importlib.util.spec_from_file_location('transport', HERE / 'transport.py')
            transport = importlib.util.module_from_spec(transport_spec)
            transport_spec.loader.exec_module(transport)
            requests = transport.internal(args, world)
            expected = [len(requests)]
        event.update(http=requests, http_expected=sum(expected),
                     paginated=args[:2] == ['issue', 'view'] and args[4] == 'subIssues' or '--paginate' in args)
        if os.environ.get('LOAD_READBACK') == '1':
            pull = item(int(args[1].rsplit('/', 1)[1]))
            effect('merge-readback', ticket=pull['closes'][0], head=pull['head'], merged=pull['state'] == 'MERGED')
    if event['kind'] not in ('command', 'merge-readback'):
        save(path, world)
    event['status'] = status
    with open(os.environ['LOAD_EVENTS'], 'a') as log:
        log.write(json.dumps(event) + '\n')
    sys.stdout.write(result)
    return status


if __name__ == '__main__':
    sys.exit(main())
