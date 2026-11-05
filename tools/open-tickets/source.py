"""Current read-only source provenance. Never save source payloads or comments."""
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from graph import blocker_numbers, label_names, milestone_value, parent_number
from plan import exact, number, parse_json, require, SOURCE, SPEC


def read_batch(function, values, *, parallel=False):
    values = list(values)
    if parallel and len(values) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(values))) as pool:
            return list(pool.map(function, values))
    return [function(value) for value in values]


def call(gh, *args):
    result = subprocess.run([gh, *args], capture_output=True, text=True)
    require(result.returncode == 0, 'source: read failed')
    return parse_json(result.stdout)


def pages(gh, endpoint):
    value = call(gh, 'api', '--method', 'GET', '--paginate', '--slurp', endpoint)
    require(type(value) is list and value and all(type(page) is list for page in value),
            'source: invalid pages')
    return [row for page in value for row in page]


def merged(gh, n):
    value = call(gh, 'issue', 'view', str(n), '--repo', SOURCE, '--json',
                 'number,state,closedByPullRequestsReferences')
    exact(value, ['number', 'state', 'closedByPullRequestsReferences'], 'merge source')
    require(value['number'] == n and value['state'] == 'CLOSED' and
            type(value['closedByPullRequestsReferences']) is list and value['closedByPullRequestsReferences'],
            f'source: closed blocker #{n} has no verified merge')
    proofs = []
    for ref in value['closedByPullRequestsReferences']:
        require(type(ref) is dict and number(ref.get('number')) and
                ref.get('url') == f"https://github.com/{SOURCE}/pull/{ref['number']}",
                'source: foreign merge reference')
        pr = call(gh, 'pr', 'view', str(ref['number']), '--repo', SOURCE, '--json',
                  'number,state,mergeCommit,baseRefName,url')
        require(pr.get('number') == ref['number'] and pr.get('state') == 'MERGED' and
                pr.get('baseRefName') == 'main' and pr.get('url') == ref['url'] and
                type(pr.get('mergeCommit')) is dict and
                re.fullmatch('[0-9a-f]{40}', pr['mergeCommit'].get('oid', '')),
                'source: blocker PR is not merged into source main')
        oid = pr['mergeCommit']['oid']
        comparison = call(gh, 'api', '--method', 'GET', f'repos/{SOURCE}/compare/{oid}...main')
        require(comparison.get('status') in {'ahead', 'identical'} and comparison.get('behind_by') == 0,
                'source: blocker merge is not reachable from current main')
        proofs.append({'pull_request': ref['number'], 'merge': oid})
    return proofs


def validate_closure_record(record):
    exact(record, ['comment', 'sha256', 'superseded_by'], 'closure record')
    require(number(record['comment']) and type(record['sha256']) is str and
            re.fullmatch('[0-9a-f]{64}', record['sha256']) and
            (record['superseded_by'] is None or number(record['superseded_by'])),
            'source: invalid closure record')


def validate_merge_proofs(proofs):
    require(type(proofs) is list and proofs, 'source: missing merge provenance')
    for proof in proofs:
        exact(proof, ['pull_request', 'merge'], 'merge proof')
        require(number(proof['pull_request']) and type(proof['merge']) is str and
                re.fullmatch('[0-9a-f]{40}', proof['merge']), 'source: invalid merge proof')
    require(len({p['pull_request'] for p in proofs}) == len(proofs), 'source: duplicate merge proof')


def closure(gh, n, records):
    """A reason is native; a non-merge completion/supersession record is explicitly bound.

    Never infer completion from comment prose or select the latest comment.
    Operator bindings contain identities/hashes only, never private quotations.
    """
    value = call(gh, 'issue', 'view', str(n), '--repo', SOURCE, '--json',
                 'number,state,stateReason,closedByPullRequestsReferences')
    exact(value, ['number', 'state', 'stateReason', 'closedByPullRequestsReferences'], 'closure source')
    require(value['number'] == n and value['state'] == 'CLOSED' and
            type(value['stateReason']) is str and value['stateReason'] in {'COMPLETED', 'NOT_PLANNED'} and
            type(value['closedByPullRequestsReferences']) is list, 'source: unknown closure disposition')
    if value['closedByPullRequestsReferences']:
        require(value['stateReason'] == 'COMPLETED', 'source: conflicting closure disposition')
        return dict(state='merged', proofs=merged(gh, n))
    require(str(n) in records, f'source: closed blocker #{n} needs a bound closure record')
    record = records[str(n)]
    validate_closure_record(record)
    completed = value['stateReason'] == 'COMPLETED'
    require((record['superseded_by'] is None) == completed and record['superseded_by'] != n,
            'source: closure reason and record differ')
    comments = pages(gh, f'repos/{SOURCE}/issues/{n}/comments?per_page=100')
    require(all(type(c) is dict and number(c.get('id')) and type(c.get('body')) is str for c in comments) and
            len({c['id'] for c in comments}) == len(comments), 'source: incomplete closure comments')
    matches = [c for c in comments if c['id'] == record['comment']]
    require(len(matches) == 1 and hashlib.sha256(matches[0]['body'].encode()).hexdigest() == record['sha256'],
            'source: closure record missing or changed')
    return dict(state='completed' if completed else 'not_planned', **record)


def body_hash(body):
    value = re.sub(r'^([ \t]*[-*+][ \t]+)\[[xX]\](?=[ \t\r]|$)', r'\1[ ]', body + '\n', flags=re.MULTILINE)
    return hashlib.sha256(value.encode()).hexdigest()


def validate_excluded_targets(bindings, authorized, nodes=None):
    require(type(bindings) is dict, 'source: invalid excluded-target bindings')
    for n, proof in bindings.items():
        require(type(n) is str and re.fullmatch('[1-9][0-9]*', n) and int(n) in authorized,
                'source: unbound excluded target')
        exact(proof, ['url', 'parent', 'source_sha256'], 'excluded-target proof')
        require(proof['url'] == f'https://github.com/{SOURCE}/issues/{n}' and
                (proof['parent'] is None or number(proof['parent'])) and
                proof['parent'] != int(n) and (int(n) == SPEC or proof['parent'] == SPEC) and
                type(proof['source_sha256']) is str and re.fullmatch('[0-9a-f]{64}', proof['source_sha256']),
                'source: ambiguous excluded-target provenance')
        if nodes is not None:
            require(nodes.get(n) == proof['source_sha256'], 'source: excluded-target digest differs')


def excluded_targets(source, inv, requested=None):
    requested = set(inv['excluded']) if requested is None else set(requested)
    require(requested <= set(inv['excluded']), 'source: unauthorized excluded target')
    if not requested:
        return {}
    root = source.node(SPEC)
    require(root['children'] == inv['remaining'], 'source: ambiguous migration child provenance')
    kinds = {r['number']: r['kind'] for r in inv['scope']}
    result = {}
    for n in sorted(requested):
        require(kinds.get(n) == 'issue', 'source: excluded target is not an issue')
        node = source.node(n)
        require(node['item']['state'] == 'open' and (n == SPEC or
                (n in inv['remaining'] and node['item']['parent'] == SPEC)),
                'source: excluded target is not a remaining migration ticket')
        result[str(n)] = dict(url=f'https://github.com/{SOURCE}/issues/{n}', parent=node['item']['parent'],
            source_sha256=hashlib.sha256(json.dumps(node, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    validate_excluded_targets(result, inv['excluded'])
    return result


def revision(spec, nodes):
    node = nodes[spec]
    children = node['children']
    value = f'plan-graph revision v2\nspec #{spec} body sha256 {body_hash(node["body"])}\n'
    for n in sorted(children):
        child = nodes[n]
        blockers = ' '.join('#' + str(v) for v in child['item']['blockers']) or 'none'
        value += (f'ticket #{n} blocked-by {blockers} body sha256 {body_hash(child["body"])} '
                  f'title {child["item"]["title"]}\n')
    return hashlib.sha256(value.encode()).hexdigest()


def approval_subjects(nodes, moving):
    moving = set(moving)
    return {n for n in moving if nodes[n]['item']['kind'] == 'issue' and
            ('spec' in nodes[n]['item']['labels'] or nodes[n]['children'])} | {
        node['item']['parent'] for node in nodes.values() if node['item']['parent'] in moving and
        nodes[node['item']['parent']]['item']['kind'] == 'issue'}


class Source:
    def __init__(self, gh):
        self.gh, self.nodes = gh, {}

    def node(self, n, kind='issue'):
        if n in self.nodes:
            require(self.nodes[n]['item']['kind'] == kind, 'source: conflicting kind')
            return self.nodes[n]
        fields = 'number,title,body,state,labels,milestone'
        fields += ',parent,blockedBy,subIssues' if kind == 'issue' else ',baseRefOid,headRefOid'
        value = call(self.gh, 'issue' if kind == 'issue' else 'pr', 'view', str(n), '--repo', SOURCE, '--json', fields)
        exact(value, fields.split(','), 'source node')
        require(number(value['number']) and value['number'] == n and type(value['title']) is str and
                value['title'].strip() and type(value['body']) is str and value['state'] in {'OPEN', 'CLOSED', 'MERGED'},
                'source: invalid node')
        milestone = milestone_value(value['milestone'], 'source')
        item = dict(number=n, kind=kind, title=value['title'], labels=label_names(value['labels'], 'source'),
                    milestone=None if milestone is None else milestone['title'], parent=None, blockers=[],
                    state=value['state'].lower())
        node = dict(item=item, body=value['body'], children=[], range=None)
        if kind == 'issue':
            item['parent'] = parent_number(value['parent'], SOURCE, 'source')
            item['blockers'] = blocker_numbers(value['blockedBy'], SOURCE, 'source')
            node['children'] = blocker_numbers(value['subIssues'], SOURCE, 'source')
        else:
            require(all(type(value[k]) is str and re.fullmatch('[0-9a-f]{40}', value[k])
                        for k in ['baseRefOid', 'headRefOid']), 'source: invalid PR range')
            comparison = call(self.gh, 'api', '--method', 'GET',
                              f"repos/{SOURCE}/compare/{value['baseRefOid']}...{value['headRefOid']}")
            merge_base = comparison.get('merge_base_commit', {}).get('sha')
            require(type(merge_base) is str and re.fullmatch('[0-9a-f]{40}', merge_base),
                    'source: PR merge base unavailable')
            node['range'] = dict(observed_base=value['baseRefOid'], source_base=merge_base,
                                 source_head=value['headRefOid'])
        self.nodes[n] = node
        return node

    def approved_graphs(self, moving, *, preparation=False):
        expanded = set()
        while True:
            subjects = approval_subjects(self.nodes, moving)
            pending = subjects - expanded
            if not pending:
                break
            children = sorted({child for n in pending for child in self.nodes[n]['children']})
            read_batch(self.node, children, parallel=preparation)
            expanded.update(pending)
        result = {}
        approvals = read_batch(lambda n: (n, self.approval(n, preparation=preparation)),
                               sorted(subjects), parallel=preparation)
        for n, approval in approvals:
            if approval:
                result[str(n)] = approval
        return result

    def approval(self, spec, *, preparation=False):
        comments = pages(self.gh, f'repos/{SOURCE}/issues/{spec}/comments?per_page=100')
        require(all(type(row) is dict and number(row.get('id')) and type(row.get('body')) is str for row in comments)
                and len({r['id'] for r in comments}) == len(comments), 'source: incomplete approval comments')
        approvals = [row for row in comments if row['body'].startswith('**Plan graph approved by ')]
        if not approvals:
            return None
        latest = max(approvals, key=lambda row: row['id'])
        found = re.findall(r'Fingerprint:\s*`([0-9a-f]{64})`', latest['body'])
        require(len(found) == 1,
                f'source: approved graph #{spec} fingerprint is stale or unreadable')
        current = revision(spec, self.nodes)
        proof = dict(comment=latest['id'], fingerprint=found[0])
        if preparation:
            return dict(**proof, current_fingerprint=current,
                        status='approval current' if found[0] == current else 'approval stale')
        require(found[0] == current, f'source: approved graph #{spec} fingerprint is stale or unreadable')
        return proof
