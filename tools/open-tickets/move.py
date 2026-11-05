#!/usr/bin/env python3
"""Ticket mover preparation, dry-run by default.

--apply is a separately gated future cut-over; installing this tool grants no
live or public-write permission. Proofs use synthetic GitHub publication only.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan import Refusal, exact, number, parse_json, require, DEFAULT_TARGET, inventory  # noqa: E402
from graph import (prepare, verify, validate_snapshot, label_names, milestone_value,
                   parent_number, blocker_numbers, reapproval)  # noqa: E402
from source import (Source as SourceReader, merged as verified_merge, closure,
                    validate_closure_record, validate_merge_proofs, excluded_targets,
                    validate_excluded_targets)  # noqa: E402
from carriage import Patch  # noqa: E402
from text import CHECKER, SOURCE, check_text, private_record, transform  # noqa: E402

PRIVATE = 'jparker2006/ClosedWiz'
PUBLIC = 'https://github.com/openwizdev/openwiz'  # the contract's final address; no legacy fallback


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def map_bytes(mapping, kinds=None):
    return ('kind\tclosedwiz\topenwiz\n' + ''.join(
        f"{(kinds or {}).get(old, 'issue')}\t{old}\t{mapping[old]}\n" for old in sorted(mapping))).encode()


def planned_bytes(graph):
    return ('kind\tclosedwiz\topenwiz\n' + ''.join(
        f"{item['kind']}\t{item['number']}\tplanned\n"
        for item in sorted(graph['items'], key=lambda row: row['number'])
        if item['state'] == 'open' and item['number'] not in graph['exclude'])).encode()


def atomic(path, data):
    # Intent and its directory entry must survive a stop before any remote effect.
    fd, name = tempfile.mkstemp(prefix='.openwiz-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root, readonly):
    if not readonly:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'lock').open('rb' if readonly else 'a+b') as stream:
        fcntl.flock(stream, (fcntl.LOCK_SH if readonly else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        yield


class Mover:
    def __init__(self, args, proposal):
        require(type(proposal) is dict, 'proposal: invalid object')
        proposal = dict(proposal)
        proposal.setdefault('target', DEFAULT_TARGET)
        proposal.setdefault('pulls', {})
        proposal.setdefault('approvals', {})
        proposal.setdefault('closures', {})
        proposal.setdefault('merges', {})
        proposal.setdefault('excluded_targets', {})
        exact(proposal, ['graph', 'bodies', 'target', 'date', 'pulls', 'approvals', 'closures', 'merges',
                         'excluded_targets'], 'proposal')
        self.args, self.proposal = args, proposal
        self.state = None
        self.target = proposal['target']
        self.items, _ = validate_snapshot(proposal['graph'])
        validate_excluded_targets(proposal['excluded_targets'], proposal['graph']['exclude'])
        self.private_targets = {int(n): proof['url'] for n, proof in proposal['excluded_targets'].items()}
        exact(proposal['merges'], [str(n) for n, item in self.items.items()
              if item['state'] == 'merged'], 'proposal merge bindings')
        for proofs in proposal['merges'].values():
            validate_merge_proofs(proofs)
        exact(proposal['closures'], [str(n) for n, item in self.items.items()
              if item['state'] in {'completed', 'not_planned'}], 'proposal closure bindings')
        for n, proof in proposal['closures'].items():
            exact(proof, ['state', 'comment', 'sha256', 'superseded_by'], 'proposal closure proof')
            validate_closure_record({k: v for k, v in proof.items() if k != 'state'})
            require(proof['state'] == self.items[int(n)]['state'] and
                    ((proof['superseded_by'] is None) == (proof['state'] == 'completed')) and
                    proof['superseded_by'] != int(n), 'proposal: closure reason and proof differ')
        self.planned = prepare(proposal['graph'], planned_bytes(proposal['graph']), self.target)
        self.kinds = {row['closedwiz']: row['kind'] for row in self.planned['moves']}
        exact(proposal['pulls'], [str(n) for n, kind in self.kinds.items() if kind == 'pull_request'], 'PR handoffs')
        self.patches = {int(n): Patch(args, descriptor) for n, descriptor in proposal['pulls'].items()}
        require(not any(row['closedwiz'] == 1257 for row in self.planned['moves']),
                'proposal: migration spec cannot move')
        exact(proposal['bodies'], [str(row['closedwiz']) for row in self.planned['moves']], 'proposal bodies')
        drafts = {}
        for row in self.planned['moves']:
            n = row['closedwiz']
            body, quotes = transform(proposal['bodies'][str(n)], self.pointer(n, 1), n, row['kind'],
                                     row['merged_blockers'], closing_map=self.closing_mapping(),
                                     completed=self.completion_records(row), merge_proofs=proposal['merges'],
                                     private_targets=self.private_targets)
            drafts[str(n)] = body
            check_text(row['title'], '\n'.join(row['labels']), args.checker, args.literals)
            private_record(1, proposal['date'], quotes)  # validate the date even without quotes
            check_text(row['title'], body, args.checker, args.literals)
        require(type(proposal['approvals']) is dict, 'proposal: invalid approval bindings')
        for n, approval in proposal['approvals'].items():
            require(type(n) is str and re.fullmatch('[1-9][0-9]*', n), 'proposal: invalid approval spec')
            exact(approval, ['comment', 'fingerprint'], 'approval binding')
            require(number(approval['comment']) and type(approval['fingerprint']) is str and
                    re.fullmatch('[0-9a-f]{64}', approval['fingerprint']), 'proposal: invalid approval provenance')
            reapproval(self.planned, proposal['graph'], int(n), drafts)
        self.hash = hashlib.sha256(canonical(proposal)).hexdigest()
        self.path = args.state_dir / 'state.json'
        protected = [self.path, args.state_dir / 'lock', args.state_dir / 'reapproval.json', args.plan, args.checker, args.literals]
        require(args.map_out.resolve() not in {path.resolve() for path in protected},
                'map: output aliases state or input')
        self.state = None

    def pointer(self, old, comment):
        kind = 'pull' if self.kinds[old] == 'pull_request' else 'issues'
        return f'{SOURCE}/{kind}/{old}#issuecomment-{comment}'

    def call(self, args, payload=None):
        result = subprocess.run([self.args.gh, *args], input=payload,
                                capture_output=True, text=True, check=False)
        require(result.returncode == 0, 'gh: effect/read outcome unconfirmed; inspect and resume')
        return result.stdout

    def get_pages(self, endpoint):
        value = parse_json(self.call(['api', '--method', 'GET', '--paginate', '--slurp', endpoint]))
        require(type(value) is list and value and all(type(page) is list for page in value),
                'gh: incomplete paginated read')
        return [row for page in value for row in page]

    def comments(self, old):
        rows = self.get_pages(f'repos/{PRIVATE}/issues/{old}/comments?per_page=100')
        require(all(type(row) is dict and number(row.get('id')) and type(row.get('body')) is str
                    for row in rows), 'gh: invalid comment read')
        require(len({row['id'] for row in rows}) == len(rows), 'gh: duplicate comment read')
        return rows

    def find(self, old, identity=None):
        rows = self.get_pages(f'repos/{self.target}/issues?state=all&per_page=100')
        require(all(type(row) is dict and number(row.get('number')) and type(row.get('body')) is str
                    for row in rows), 'gh: invalid target inventory')
        require(len({row['number'] for row in rows}) == len(rows), 'gh: duplicate target inventory')
        was = self.was(old)
        matches = [row for row in rows if row['body'].endswith(was) and
                   ('pull_request' in row) == (self.kinds[old] == 'pull_request')]
        require(len(matches) <= 1, 'resume: ambiguous destination; no create retry')
        if matches and identity is not None:
            row = next(row for row in self.planned['moves'] if row['closedwiz'] == old)
            expected = self.creation(row, identity['nonce'])
            actual = matches[0]
            require(actual.get('title') == expected['title'] and actual['body'] == expected['body'],
                    'resume: creation identity or payload differs; no adoption')
            if old in self.patches:
                self.check_pr(row, identity['nonce'], new=actual['number'])
            else:
                require(label_names(actual.get('labels'), 'resume') == expected['labels'] and
                        milestone_value(actual.get('milestone'), 'resume') == row['milestone'],
                        'resume: creation metadata differs; no adoption')
        return matches[0]['number'] if matches else None

    def was(self, old):
        kind = 'pull' if self.kinds[old] == 'pull_request' else 'issues'
        return f'was [ClosedWiz #{old}]({SOURCE}/{kind}/{old})'

    @staticmethod
    def moved(new, kind='issue'):
        path = 'pull' if kind == 'pull_request' else 'issues'
        return f'moved to [OpenWiz #{new}]({PUBLIC}/{path}/{new})'

    def load(self, readonly=False):
        if self.path.exists():
            self.state = parse_json(self.path.read_text(encoding='utf-8'))
            exact(self.state, ['version', 'fingerprint', 'mapping', 'inflight', 'creations', 'phases'], 'state')
            require(type(self.state['version']) is int and self.state['version'] == 5 and
                    self.state['fingerprint'] == self.hash and type(self.state['mapping']) is dict,
                    'state: different or invalid proposal')
        else:
            require(not readonly, 'state: no completed move to verify')
            self.state = {'version': 5, 'fingerprint': self.hash, 'mapping': {}, 'inflight': None, 'creations': {}, 'phases': {}}
        allowed = {str(row['closedwiz']) for row in self.planned['moves']}
        mapping = self.state['mapping']
        require(set(mapping) <= allowed and all(number(v) for v in mapping.values()) and
                len(set(mapping.values())) == len(mapping), 'state: invalid destination map')
        phases = self.state['phases']
        require(type(phases) is dict and set(phases) <= set(mapping), 'state: invalid phase ownership')
        for old, values in phases.items():
            required = {'body', 'parent', 'graph', 'metadata', 'complete'}
            required |= {'blocker:' + str(mapping[str(n)]) for n in self.items[int(old)]['blockers'] if str(n) in mapping}
            require(type(values) is list and all(type(v) is str for v in values) and
                    values == sorted(set(values)) and set(values) <= required and
                    ('complete' not in values or set(values) == required), 'state: invalid completed phases')
        intent = self.state['inflight']
        if intent is not None:
            require(type(intent) is dict and type(intent.get('kind')) is str and
                    intent['kind'] in {'create', 'publish', 'comment', 'edit'} and number(intent.get('old')) and
                    str(intent['old']) in allowed, 'state: invalid intent')
            keys = {'kind', 'old'}
            if intent['kind'] == 'comment':
                keys.add('digest')
            if intent['kind'] == 'edit':
                keys |= {'resource', 'intended', 'request', 'digest'}
            if intent['kind'] in {'create', 'publish'}:
                keys |= {'nonce', 'digest'}
            require(set(intent) == keys, 'state: invalid intent fields')
            if intent['kind'] == 'comment':
                require(type(intent['digest']) is str and re.fullmatch(r'[0-9a-f]{64}', intent['digest']),
                        'state: invalid comment intent')

        creations = self.state['creations']
        pending = {str(intent['old'])} if intent and intent['kind'] in {'create', 'publish'} else set()
        require(type(creations) is dict and set(mapping) | pending <= set(creations) <= allowed,
                'state: creation ownership missing')
        for old, identity in creations.items():
            exact(identity, ['nonce', 'digest'], 'state creation')
            require(type(identity['nonce']) is str and re.fullmatch(r'[0-9a-f]{32}', identity['nonce']) and
                    type(identity['digest']) is str, 'state: invalid creation identity')
            row = next(row for row in self.planned['moves'] if str(row['closedwiz']) == old)
            digest = hashlib.sha256(canonical(self.creation(row, identity['nonce']))).hexdigest()
            require(identity['digest'] == digest, 'state: creation payload binding differs')
        if intent and intent['kind'] == 'edit':
            self.edit_details(intent)
        if pending:
            require({key: intent[key] for key in ['nonce', 'digest']} == creations[str(intent['old'])],
                    'state: pending creation differs')

    def map_guard(self):
        require(self.args.map_out.parent.is_dir() and not self.args.map_out.is_symlink(),
                'map: unavailable or symlink output')
        if self.args.map_out.exists():
            require(self.path.exists(), 'map: existing output has no matching move state')
            saved = self.args.map_out.read_bytes()
            expected = map_bytes({int(n): v for n, v in self.state['mapping'].items()}, self.kinds)
            rows, known = saved.splitlines(keepends=True), expected.splitlines(keepends=True)
            require(rows and rows[0] == known[0] and len(set(rows)) == len(rows) and
                    saved == known[0] + b''.join(row for row in known[1:] if row in rows[1:]),
                    'map: existing output does not belong to this move state')

    def reconcile(self):
        intent = self.state['inflight']
        if intent is None:
            return
        old = intent['old']
        if intent['kind'] == 'publish':
            row = next(row for row in self.planned['moves'] if row['closedwiz'] == old)
            self.check_branch(old, intent['nonce'], required=True)
            self.settled()
        elif intent['kind'] == 'create':
            found = self.find(old, intent)
            require(found is not None, 'resume: create outcome unknown; no automatic retry')
            require(found not in self.state['mapping'].values(), 'resume: duplicate destination')
            self.state['mapping'][str(old)] = found
            self.settled()
        elif intent['kind'] == 'comment':
            matches = [row for row in self.comments(old) if
                       hashlib.sha256(row['body'].encode()).hexdigest() == intent['digest']]
            require(len(matches) == 1, 'resume: comment outcome unknown or ambiguous; no automatic retry')
            row = next(row for row in self.mapped_plan()['moves'] if row['closedwiz'] == old)
            self.validate_comments(row, complete=False)
            self.settled()
        else:
            self.reconcile_edit()


    def save(self):
        atomic(self.path, canonical(self.state) + b'\n')

    def intent(self, kind, old, body=None, identity=None, edit=None):
        self.state['inflight'] = {'kind': kind, 'old': old}
        if kind in {'create', 'publish'}:
            self.state['inflight'].update(identity)
            self.state['creations'][str(old)] = identity
        if kind == 'edit':
            require(edit is not None, 'state: edit requires exact resource binding')
            self.state['inflight'].update(edit)
        if kind == 'comment':
            self.state['inflight']['digest'] = hashlib.sha256(body.encode()).hexdigest()
        self.save()

    def settled(self):
        require(not self.state['inflight'] or self.state['inflight']['kind'] != 'edit',
                'state: an edit must reconcile its own outcome')
        self.state['inflight'] = None
        self.save()

    def original_matches(self):
        current = inventory(self.args.gh, self.target)
        scope = [{'number': row['closedwiz'], 'kind': row['kind']} for row in self.planned['moves']]
        require(scope == current['moves'], 'source: proposal does not cover the complete current move scope')
        require(set(self.proposal['graph']['exclude']) <= {1257, *current['remaining']},
                'source: unauthorized proposal exclusion')
        for n, item in self.items.items():
            if item['state'] == 'merged':
                require(verified_merge(self.args.gh, n) == self.proposal['merges'][str(n)],
                        'source: merge proof changed')
            elif item['state'] in {'completed', 'not_planned'}:
                proof = self.proposal['closures'][str(n)]
                require(closure(self.args.gh, n, {str(n): {k: v for k, v in proof.items() if k != 'state'}}) == proof,
                        'source: closure disposition changed')
        source = SourceReader(self.args.gh)
        for row in self.planned['moves']:
            source.node(row['closedwiz'], row['kind'])
        require(excluded_targets(source, current, self.private_targets) == self.proposal['excluded_targets'],
                'source: excluded-target binding changed')
        approvals = source.approved_graphs(self.kinds)
        require(approvals == self.proposal['approvals'], 'source: approval provenance differs')
        for row in self.planned['moves']:
            old = row['closedwiz']
            node = source.nodes[old]
            actual, expected = node['item'], self.items[old]
            require(actual['state'] == 'open' and actual['title'] == row['title'] and
                    node['body'] == self.proposal['bodies'][str(old)] and
                    actual['labels'] == sorted(expected['labels']) and actual['milestone'] == expected['milestone'] and
                    actual['parent'] == expected['parent'] and actual['blockers'] == sorted(expected['blockers']),
                    'source: changed since proposal; no effect authorized by this snapshot')
            if row['kind'] == 'pull_request':
                descriptor = self.patches[old].descriptor
                require(node['range'] == {key: descriptor[key] for key in ['observed_base', 'source_base', 'source_head']},
                        'source: PR range or merge base changed')

    def closing_mapping(self):
        return {row['closedwiz']: (self.state['mapping'].get(str(row['closedwiz']), 'planned')
                                  if self.state else 'planned') for row in self.planned['moves'] if row['kind'] == 'issue'}

    def completion_records(self, row):
        return {n: self.proposal['closures'][str(n)]['comment'] for n in row['completed_blockers']}

    def marked(self, old, phase):
        return phase in self.state['phases'].get(str(old), [])

    def confirmed(self, old, phase):
        require(self.state['inflight'] is None, 'state: phase cannot clear an unsettled effect')
        self.state['phases'][str(old)] = sorted(set(self.state['phases'].get(str(old), [])) | {phase})
        self.state['inflight'] = None
        self.save()

    def preflight_comments(self):
        for row in self.planned['moves']:
            old = row['closedwiz']
            if str(old) in self.state['mapping']:
                mapped = dict(row, openwiz=self.state['mapping'][str(old)])
                self.validate_comments(mapped, complete=self.marked(old, 'complete'))
            else:
                comments = self.comments(old)
                require(not any(c['body'].startswith(('moved to ', '**Private record for OpenWiz #'))
                                for c in comments), 'source: conflicting existing migration comments')

    @staticmethod
    def branch(old, nonce):
        return f'openwiz-move-{old}-{nonce}'

    def check_branch(self, old, nonce, required):
        patch = self.patches[old]
        branch = self.branch(old, nonce)
        base = parse_json(self.call(['api', '--method', 'GET', f'repos/{self.target}/commits/main']))
        require(base.get('sha') == patch.binding['destination_base'], 'PR publish: remote main differs')
        refs = parse_json(self.call(['api', '--method', 'GET',
                                    f'repos/{self.target}/git/matching-refs/heads/{branch}']))
        require(type(refs) is list, 'PR publish: invalid branch read')
        if not required:
            require(not refs, 'PR publish: unowned branch exists')
        else:
            require(len(refs) == 1 and refs[0].get('ref') == 'refs/heads/' + branch and
                    refs[0].get('object', {}).get('sha') == patch.checked['commit'],
                    'PR publish: outcome unknown or branch differs; no retry')

    def check_pr(self, row, nonce, new=None):
        old = row['closedwiz']
        self.check_branch(old, nonce, required=True)
        fields = 'number,state,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository'
        value = parse_json(self.call(['pr', 'view', str(new or row['openwiz']), '--repo', self.target,
                                     '--json', fields]))
        require(value == dict(number=new or row['openwiz'], state='OPEN', headRefName=self.branch(old, nonce),
                             headRefOid=self.patches[old].checked['commit'], baseRefName='main',
                             baseRefOid=self.patches[old].binding['destination_base'], isCrossRepository=False),
                'PR publish: PR kind, head, base or repository differs')

    def pr_metadata(self, row, body):
        labels = label_names(self.read_field(row['openwiz'], 'labels'), 'PR metadata')
        milestone = milestone_value(self.read_field(row['openwiz'], 'milestone'), 'PR metadata')
        if self.marked(row['closedwiz'], 'metadata'):
            require((labels, milestone) == (row['labels'], row['milestone']),
                    'PR metadata: confirmed public metadata changed; no overwrite')
            return
        require((labels, milestone) in [( [], None), (row['labels'], row['milestone'])],
                'PR metadata: subsequent public work differs; no overwrite')
        if (labels, milestone) != (row['labels'], row['milestone']):
            check_text(row['title'], body, self.args.checker, self.args.literals)
            payload = {'labels': row['labels'], 'milestone': None if row['milestone'] is None else row['milestone']['number']}
            self.perform_edit(row, 'metadata', {'labels': row['labels'], 'milestone': row['milestone']},
                ['api', '--method', 'PATCH', f"repos/{self.target}/issues/{row['openwiz']}", '--input', '-'],
                canonical(payload).decode())
            verify({'target': self.target, 'moves': [row]}, self.args.gh)
        self.confirmed(row['closedwiz'], 'metadata')

    def creation(self, row, nonce):
        body = ('Migration preparation pending.\n\n<!-- openwiz-move ' + nonce + ' -->\n\n' +
                self.was(row['closedwiz']))
        if row['kind'] == 'pull_request':
            return {'title': row['title'], 'body': body, 'base': 'main',
                    'head': self.branch(row['closedwiz'], nonce)}
        return {'title': row['title'], 'body': body, 'labels': row['labels'],
                'milestone': None if row['milestone'] is None else row['milestone']['number']}

    def create(self, row):
        old = row['closedwiz']
        require(self.find(old) is None, 'resume: existing destination has no matching creation intent; no adoption')
        existing = self.state['creations'].get(str(old))
        nonce = existing['nonce'] if existing else secrets.token_hex(16)
        payload = self.creation(row, nonce)
        identity = {'nonce': nonce, 'digest': hashlib.sha256(canonical(payload)).hexdigest()}
        check_text(row['title'], payload['body'], self.args.checker, self.args.literals)
        if old in self.patches:
            if existing is None:
                self.check_branch(old, nonce, required=False)
                self.intent('publish', old, identity=identity)
                self.patches[old].publish(self.branch(old, nonce), self.target)
                self.check_branch(old, nonce, required=True)
                self.settled()
            else:
                self.check_branch(old, nonce, required=True)
        self.intent('create', old, identity=identity)
        self.call(['api', '--method', 'POST', f"repos/{self.target}/{'pulls' if old in self.patches else 'issues'}", '--input', '-'],
                  canonical(payload).decode('utf-8'))
        found = self.find(old, self.state['inflight'])
        require(found is not None, 'resume: create outcome unconfirmed; no automatic retry')
        require(found not in self.state['mapping'].values(), 'resume: duplicate destination')
        self.state['mapping'][str(old)] = found
        self.settled()

    @staticmethod
    def matching_comment(existing, body, prefix, complete=False):
        family = [row for row in existing if row['body'].startswith(prefix)]
        require(all(row['body'] == body for row in family) and len(family) <= 1,
                'read-back: conflicting or duplicate migration comments')
        if complete and body is not None:
            require(len(family) == 1, 'read-back: required migration comment absent')
        return family

    def validate_comments(self, row, complete):
        old = row['closedwiz']
        _, quotes = transform(self.proposal['bodies'][str(old)], self.pointer(old, 1), old, row['kind'],
                              closing_map=self.closing_mapping(), private_targets=self.private_targets)
        record = private_record(row['openwiz'], self.proposal['date'], quotes) if quotes else None
        existing = self.comments(old)
        self.matching_comment(existing, record, '**Private record for OpenWiz #', complete)
        self.matching_comment(existing, self.moved(row['openwiz'], row['kind']), 'moved to ', complete)

    def comment_once(self, old, body):
        existing = self.comments(old)
        prefix = 'moved to ' if body.startswith('moved to ') else '**Private record for OpenWiz #'
        matches = self.matching_comment(existing, body, prefix)
        if not matches:
            require(not (self.state['inflight'] and self.state['inflight']['kind'] == 'comment'),
                    'resume: comment outcome still unknown; no automatic retry')
            if body.startswith('moved to '):
                require(not any(row['body'].startswith('moved to ') for row in existing),
                        'resume: conflicting moved comment')
            else:
                require(not any(row['body'].startswith('**Private record for OpenWiz #') for row in existing),
                        'resume: conflicting private record')
            self.intent('comment', old, body)
            self.call(['api', '--method', 'POST', f'repos/{PRIVATE}/issues/{old}/comments', '--input', '-'],
                      json.dumps({'body': body}))
            matches = self.matching_comment(self.comments(old), body, prefix)
            require(len(matches) == 1, 'resume: source comment outcome unconfirmed')
        self.settled()
        return matches[0]['id']

    def final_body(self, row, readonly):
        old, new = row['closedwiz'], row['openwiz']
        _, quotes = transform(self.proposal['bodies'][str(old)], self.pointer(old, 1), old, row['kind'],
                              closing_map=self.closing_mapping(), private_targets=self.private_targets)
        pointer = self.pointer(old, 1)
        if quotes:
            record = private_record(new, self.proposal['date'], quotes)
            if readonly:
                matches = self.matching_comment(self.comments(old), record, '**Private record for OpenWiz #')
                require(len(matches) == 1, 'read-back: private record absent or duplicated')
                comment = matches[0]['id']
            else:
                comment = self.comment_once(old, record)
            pointer = self.pointer(old, comment)
        body, _ = transform(self.proposal['bodies'][str(old)], pointer, old, row['kind'], row['merged_blockers'],
                            closing_map=self.closing_mapping(), completed=self.completion_records(row),
                            merge_proofs=self.proposal['merges'], private_targets=self.private_targets)
        check_text(row['title'], body, self.args.checker, self.args.literals)
        return body

    def mapped_plan(self):
        mapping = {int(n): dest for n, dest in self.state['mapping'].items()}
        return prepare(self.proposal['graph'], map_bytes(mapping, self.kinds), self.target)

    def command(self, new):
        old = next(int(n) for n, dest in self.state['mapping'].items() if dest == new)
        return 'pr' if self.kinds[old] == 'pull_request' else 'issue'

    def read_body(self, new):
        actual = parse_json(self.call([self.command(new), 'view', str(new), '--repo', self.target,
                                      '--json', 'number,body']))
        exact(actual, ['number', 'body'], 'read-back')
        require(number(actual['number']) and actual['number'] == new and type(actual['body']) is str,
                'read-back: invalid public body')
        return actual['body']

    def check(self):
        require(self.state['inflight'] is None, 'read-back: unsettled remote effect')
        self.original_matches()
        mapped = self.mapped_plan()
        require(self.args.map_out.read_bytes() == map_bytes({int(n): v for n, v in self.state['mapping'].items()}, self.kinds),
                'read-back: missing or inconsistent mapping row')
        verify(mapped, self.args.gh)
        require(all(self.marked(row['closedwiz'], 'complete') for row in mapped['moves']),
                'read-back: incomplete move phases')
        for row in mapped['moves']:
            self.verify_row(row)

    def verify_row(self, row):
        verify({'target': self.target, 'moves': [row]}, self.args.gh)
        self.validate_comments(row, complete=True)
        if row['kind'] == 'pull_request':
            self.check_pr(row, self.state['creations'][str(row['closedwiz'])]['nonce'])
        expected = self.final_body(row, readonly=True)
        require(self.read_body(row['openwiz']) == expected, 'read-back: body/origin link differs')

    def read_field(self, new, field):
        actual = parse_json(self.call([self.command(new), 'view', str(new), '--repo', self.target, '--json', field]))
        exact(actual, [field], 'read-back')
        return actual[field]

    @staticmethod
    def edit_digest(edit):
        return hashlib.sha256(canonical({key: edit[key] for key in ['resource', 'intended', 'request']})).hexdigest()

    def edit_details(self, edit):
        resource, intended, request = edit['resource'], edit['intended'], edit['request']
        require(type(resource) is str and resource in {'body', 'parent', 'blockedBy', 'metadata'},
                'state: invalid edit resource')
        exact(request, ['args', 'payload'], 'edit request')
        require(type(request['args']) is list and all(type(v) is str for v in request['args']) and
                (request['payload'] is None or type(request['payload']) is str) and
                type(edit['digest']) is str and edit['digest'] == self.edit_digest(edit),
                'state: edit request/payload binding differs')
        row = next(row for row in self.mapped_plan()['moves'] if row['closedwiz'] == edit['old'])
        prefix = ['pr' if row['kind'] == 'pull_request' else 'issue', 'edit', str(row['openwiz']), '--repo', self.target]
        payload = None
        if resource == 'body':
            require(type(intended) is str, 'state: invalid intended body')
            args, payload, phase = prefix + ['--body-file', '-'], intended, 'body'
        elif resource == 'parent':
            require(row['kind'] == 'issue' and number(intended) and intended == row['parent'],
                    'state: invalid intended parent')
            args, phase = prefix + ['--parent', str(intended)], 'parent'
        elif resource == 'blockedBy':
            require(row['kind'] == 'issue' and type(intended) is list and all(number(n) for n in intended) and
                    intended == sorted(set(intended)) and set(intended) <= set(row['blockers']) and
                    request['args'] and re.fullmatch('[1-9][0-9]*', request['args'][-1]),
                    'state: invalid intended blockers')
            added = int(request['args'][-1])
            require(added in intended, 'state: edited blocker absent from intended result')
            args, phase = prefix + ['--add-blocked-by', str(added)], 'blocker:' + str(added)
        else:
            require(row['kind'] == 'pull_request' and intended == {'labels': row['labels'], 'milestone': row['milestone']},
                    'state: invalid intended metadata')
            args = ['api', '--method', 'PATCH', f"repos/{self.target}/issues/{row['openwiz']}", '--input', '-']
            payload = canonical({'labels': row['labels'],
                'milestone': None if row['milestone'] is None else row['milestone']['number']}).decode()
            phase = 'metadata'
        require(request == {'args': args, 'payload': payload}, 'state: edit does not match its resource/request')
        return row, phase

    def reconcile_edit(self):
        edit = self.state['inflight']
        require(edit is not None and edit['kind'] == 'edit', 'state: no exact edit to reconcile')
        row, phase = self.edit_details(edit)
        new, resource = row['openwiz'], edit['resource']
        if resource == 'body':
            require(edit['intended'] == self.final_body(row, readonly=True), 'state: intended body differs from proposal')
            actual = self.read_body(new)
        elif resource == 'parent':
            actual = parent_number(self.read_field(new, 'parent'), self.target, 'edit read-back')
        elif resource == 'blockedBy':
            actual = blocker_numbers(self.read_field(new, 'blockedBy'), self.target, 'edit read-back')
        else:
            value = parse_json(self.call(['pr', 'view', str(new), '--repo', self.target, '--json', 'labels,milestone']))
            exact(value, ['labels', 'milestone'], 'edit metadata read-back')
            actual = {'labels': label_names(value['labels'], 'edit read-back'),
                      'milestone': milestone_value(value['milestone'], 'edit read-back')}
        require(actual == edit['intended'], 'resume: edit outcome absent or ambiguous; no retry or phase clearance')
        # The confirmation and clearance share this single durable write.
        self.state['phases'][str(row['closedwiz'])] = sorted(set(self.state['phases'].get(str(row['closedwiz']), [])) | {phase})
        self.state['inflight'] = None
        self.save()

    def perform_edit(self, row, resource, intended, args, payload=None):
        require(self.state['inflight'] is None, 'state: another remote effect remains unsettled')
        edit = {'resource': resource, 'intended': intended, 'request': {'args': args, 'payload': payload}}
        edit['digest'] = self.edit_digest(edit)
        self.edit_details(dict(edit, old=row['closedwiz']))
        self.intent('edit', row['closedwiz'], edit=edit)
        self.call(args, payload)
        self.reconcile_edit()

    def edit(self, row, body, flags, payload=None, intended=None):
        check_text(row['title'], body, self.args.checker, self.args.literals)
        if flags == ['--body-file', '-']:
            resource, intended = 'body', body
            require(payload == body, 'edit: body payload differs')
        elif flags == ['--parent', str(row['parent'])]:
            resource, intended = 'parent', row['parent']
        else:
            require(len(flags) == 2 and flags[0] == '--add-blocked-by', 'edit: unsupported resource')
            resource = 'blockedBy'
        args = ['pr' if row['kind'] == 'pull_request' else 'issue', 'edit', str(row['openwiz']), '--repo', self.target, *flags]
        self.perform_edit(row, resource, intended, args, payload)

    def apply_row(self, row):
        old, new = row['closedwiz'], row['openwiz']
        if self.marked(old, 'complete'):
            self.verify_row(row)
            return
        current_body = self.read_body(new)
        identity = self.state['creations'][str(row['closedwiz'])]
        placeholder = self.creation(row, identity['nonce'])['body']
        self.validate_comments(row, complete=False)
        if self.marked(old, 'body'):
            require(current_body == self.final_body(row, readonly=True),
                    'read-back: confirmed public body changed; no overwrite')
        if current_body != placeholder:
            expected = self.final_body(row, readonly=True)
            require(current_body == expected, 'read-back: public body changed; no overwrite')
        is_pr = row['kind'] == 'pull_request'
        if is_pr:
            self.check_pr(row, identity['nonce'])
            if self.marked(old, 'metadata'):
                self.pr_metadata(row, current_body)
        else:
            require(label_names(self.read_field(new, 'labels'), 'metadata') == row['labels'] and
                    milestone_value(self.read_field(new, 'milestone'), 'metadata') == row['milestone'],
                    'read-back: public metadata differs; no overwrite')
            self.confirmed(old, 'metadata')
        parent = None if is_pr else parent_number(self.read_field(new, 'parent'), self.target, 'read-back')
        ns = [] if is_pr else blocker_numbers(self.read_field(new, 'blockedBy'), self.target, 'read-back')
        if self.marked(old, 'parent'):
            require(parent == row['parent'], 'read-back: confirmed parent changed; no overwrite')
        require(all(not self.marked(old, 'blocker:' + str(n)) or n in ns for n in row['blockers']),
                'read-back: confirmed blocker changed; no overwrite')
        if self.marked(old, 'graph'):
            require(parent == row['parent'] and sorted(ns) == sorted(row['blockers']),
                    'read-back: confirmed public graph changed; no overwrite')
        require(parent is None or parent == row['parent'], 'read-back: conflicting parent; no overwrite')
        require(set(ns) <= set(row['blockers']), 'read-back: conflicting blockers; no overwrite')
        body = self.final_body(row, readonly=False)
        if current_body != body:
            self.edit(row, body, ['--body-file', '-'], body)
            require(self.read_body(new) == body, 'read-back: public body update unconfirmed')
        self.confirmed(old, 'body')
        if parent != row['parent']:
            self.edit(row, body, ['--parent', str(row['parent'])])
            require(parent_number(self.read_field(new, 'parent'), self.target, 'read-back') == row['parent'],
                    'read-back: parent update unconfirmed')
        self.confirmed(old, 'parent')
        for present in ns:
            self.confirmed(old, 'blocker:' + str(present))
        for blocker in sorted(set(row['blockers']) - set(ns)):
            self.edit(row, body, ['--add-blocked-by', str(blocker)], intended=sorted(ns + [blocker]))
            ns.append(blocker)
            require(blocker_numbers(self.read_field(new, 'blockedBy'), self.target, 'read-back') == sorted(ns),
                    'read-back: blocker update unconfirmed')
            self.confirmed(old, 'blocker:' + str(blocker))
        self.confirmed(old, 'graph')
        if is_pr:
            self.pr_metadata(row, body)
        verify({'target': self.target, 'moves': [row]}, self.args.gh)
        self.settled()
        self.comment_once(row['closedwiz'], self.moved(new, row['kind']))
        self.confirmed(old, 'complete')

    def apply(self):
        self.original_matches()
        self.load()
        self.map_guard()
        self.preflight_comments()
        self.reconcile()
        for row in self.planned['moves']:
            if str(row['closedwiz']) not in self.state['mapping']:
                self.create(row)
            atomic(self.args.map_out, map_bytes({int(n): v for n, v in self.state['mapping'].items()}, self.kinds))
        for row in self.mapped_plan()['moves']:
            self.apply_row(row)
        self.check()
        # Only local requests are prepared. No approval or readiness is posted.
        bodies = {str(row['closedwiz']): self.final_body(row, readonly=True) for row in self.mapped_plan()['moves']}
        requests = {n: reapproval(self.mapped_plan(), self.proposal['graph'], int(n), bodies)
                    for n in self.proposal['approvals']}
        atomic(self.args.state_dir / 'reapproval.json', canonical(requests) + b'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--map-out', required=True, type=Path)
    parser.add_argument('--checker', type=Path, default=CHECKER)
    parser.add_argument('--literals', required=True, type=Path)
    parser.add_argument('--gh', default='gh')
    parser.add_argument('--importer', type=Path, default=Path(__file__).resolve().parent.parent / 'open-import/import.py')
    parser.add_argument('--git', default='git')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    try:
        mover = Mover(args, parse_json(args.plan.read_text(encoding='utf-8')))
        if args.apply or args.verify:
            with locked(args.state_dir, readonly=args.verify):
                if args.verify:
                    mover.load(readonly=True)
                    mover.check()
                else:
                    mover.apply()
            print('pass: issue/PR graph, bodies, public patch heads, cross-links and map read back')
        else:
            print(json.dumps({'status': 'dry_run', 'issues': len(mover.planned['moves']), 'target': mover.target,
                              'PR_carriage': 'checked_local_artifacts', 'snapshot_provenance': 'unverified'}))
    except (Refusal, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, Refusal) else 'unreadable or invalid input'
        print('refused: ' + reason, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
