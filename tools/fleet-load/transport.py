"""Synthetic gh transport expansion, deliberately not a live gh traffic model.

The existing fake supplies responses. We record each response page it emits;
revision CLI reads and CLI writes have explicit synthetic internal exchanges.
No network client or real-command fallback exists.
"""
import json
import math


def response(api, page=1, cost=0, rows=1):
    return dict(api=api, page=page, cost=cost, rows=rows)


def install(fixture, requests, expected):
    original_pages, original_rest, original_graphql = fixture.pages, fixture.rest, fixture.graphql

    def pages(items, size):
        count = max(1, math.ceil(len(items or []) / int(size)))
        expected.append(count)
        for n in range(count):
            requests.append(response('rest', n + 1, rows=len((items or [])[n * int(size):(n + 1) * int(size)])))
        return original_pages(items, size)

    def rest(*args):
        before = len(requests)
        result = original_rest(*args)
        if len(requests) == before:
            requests.append(response('rest'))
            expected.append(1)
        return result

    def graphql(*args):
        result = original_graphql(*args)
        cost = json.loads(result)['data']['rateLimit']['cost']
        requests.append(response('graphql', cost=cost))
        expected.append(1)
        return result

    fixture.pages, fixture.rest, fixture.graphql = pages, rest, graphql


def internal(args, world):
    if args[:2] == ['issue', 'view']:
        item = next(i for i in world['issues'] if i['number'] == int(args[2]))
        if args[4] == 'subIssues':
            count = sum(i.get('parent') == item['number'] for i in world['issues'])
            # Fixed internal page size of 7 in this recording executor.
            return [response('graphql', p + 1, 1, min(7, max(0, count - p * 7)))
                    for p in range(max(1, math.ceil(count / 7)))]
        return [response('graphql', cost=1)]
    if args[:2] in (['issue', 'comment'], ['pr', 'comment'], ['issue', 'close']):
        # Synthetic object resolution followed by mutation, never one CLI = one HTTP.
        return [response('graphql', cost=1), response('graphql', cost=1)]
    if args[:2] == ['pr', 'merge']:
        return [response('graphql', cost=1), response('graphql', cost=1), response('rest')]
    if args[:3] == ['api', '--method', 'PATCH']:
        return [response('rest')]
    if args == ['repo', 'view', '--json', 'isPrivate', '--jq', '.isPrivate']:
        # fleet.sh's repository-privacy question (#1273): one synthetic GraphQL read.
        return [response('graphql', cost=1)]
    raise AssertionError('unmodelled synthetic transport: ' + repr(args))
