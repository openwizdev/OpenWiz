#!/usr/bin/env python3
"""CP1 verifier and an offline recording boundary. Python standard library only.

A trusted composition supplies the immutable pin and fresh independent reads.
The command accepts synthetic recordings only and has no effect transport.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys

sys.dont_write_bytecode = True
try:
    SCHEMA = json.loads((Path(__file__).resolve().parent/'checkpoint.v1.schema.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    SCHEMA = None
EFFECTS = ('spec_summary', 'all_closed')
PREFIX = 'openwiz.completion-checkpoint.'


class Held(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Held(reason)


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'CP1_malformed')
        value[key] = item
    return value


def read_json(text):
    def invalid_constant(_):
        raise Held('CP1_malformed')
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate(value, rule):
    """Validate the closed subset of JSON Schema used by the bundled contract."""
    if not rule:
        return True
    if '$ref' in rule:
        rule = SCHEMA['$defs'][rule['$ref'].removeprefix('#/$defs/')]
    if 'anyOf' in rule:
        return any(validate(value, child) for child in rule['anyOf'])
    kind = rule['type']
    types = {'object':dict, 'array':list, 'string':str, 'integer':int,
             'boolean':bool, 'null':type(None)}
    if type(value) is not types[kind]:
        return False
    if 'const' in rule and value != rule['const']:
        return False
    if 'enum' in rule and value not in rule['enum']:
        return False
    if kind == 'object':
        return (set(value) == set(rule['required'])
                and all(validate(value[k], child) for k, child in rule['properties'].items()))
    if kind == 'array':
        return (len(value) >= rule.get('minItems', 0)
                and all(validate(item, rule['items']) for item in value))
    if kind == 'integer':
        return value >= rule.get('minimum', 0)
    if kind == 'string':
        return (len(value) >= rule.get('minLength', 0)
                and ('pattern' not in rule or re.fullmatch(rule['pattern'], value) is not None))
    return True


def checked(value, definition, reason):
    require(validate(value, SCHEMA['$defs'][definition]), reason)
    return value


def items(feed, definition, key, reason):
    checked(feed, 'feed', reason)
    expected_cursor, cursors, result = None, set(), []
    for index, page in enumerate(feed['pages']):
        require(page['cursor'] == expected_cursor and page['cursor'] not in cursors, reason)
        cursors.add(page['cursor'])
        result.extend(page['items'])
        expected_cursor = page['next_cursor']
        require((expected_cursor is None) == (index == len(feed['pages']) - 1), reason)
    require(expected_cursor is None and len(result) == feed['total'], reason)
    for item in result:
        checked(item, definition, reason)
    identities = [item[key] for item in result]
    require(len(set(identities)) == len(identities), reason)
    return result


def candidate_comment(body):
    if PREFIX in body:
        return True
    # Identify escaped schema tokens before strict parsing can reject a record.
    for token in re.findall(r'"(?:[^"\\]|\\.)*"', body):
        try:
            if PREFIX in json.loads(token):
                return True
        except ValueError:
            continue
    return False


def checkpoint(pin, observation):
    comments = items(observation['comments'], 'comment', 'id', 'CP1_checkpoint')
    candidates = [c for c in comments if c['id'] == pin['checkpoint']['comment_id']
                  or candidate_comment(c['body'])]
    require(len(candidates) == 1, 'CP1_checkpoint')
    comment = candidates[0]
    require(comment['id'] == pin['checkpoint']['comment_id']
        and digest(comment['body']) == pin['checkpoint']['body_sha256']
        and comment['repository'] == pin['repository'] and comment['subject'] == pin['spec']
        and comment['author'] == pin['orchestrator']
        and comment['writer_role'] == 'orchestrator', 'CP1_checkpoint')
    try:
        record = checked(read_json(comment['body']), 'checkpoint', 'CP1_checkpoint')
    except (ValueError, Held):
        raise Held('CP1_checkpoint') from None
    require(record['repository'] == pin['repository'] and record['spec'] == pin['spec'], 'CP1_identity')
    return record


def planned_tickets(plan, spec):
    text = plan['revision_text']
    require(digest(text) == plan['fingerprint'], 'CP1_plan')
    # Revision records use literal LF; Unicode separators belong to titles.
    require(text.endswith('\n'), 'CP1_plan')
    lines = [line + '\n' for line in text[:-1].split('\n')]
    require(len(lines) >= 2 and lines[0] == 'plan-graph revision v2\n'
        and re.fullmatch('spec #' + str(spec) + r' body sha256 [0-9a-f]{64}\n', lines[1]), 'CP1_plan')
    tickets = []
    for line in lines[2:]:
        match = re.fullmatch(r'ticket #([1-9][0-9]*) blocked-by (none|#[1-9][0-9]*(?: #[1-9][0-9]*)*) body sha256 [0-9a-f]{64} title [^\r\n]+\n', line)
        require(match is not None, 'CP1_plan')
        ticket = int(match[1])
        blockers = [] if match[2] == 'none' else [int(n[1:]) for n in match[2].split()]
        require(blockers == sorted(set(blockers)) and ticket not in blockers, 'CP1_plan')
        tickets.append(ticket)
    require(tickets == sorted(set(tickets)), 'CP1_plan')
    return tickets


def verify_live(pin, record, observation):
    required = checked(observation['required_live'], 'requirements', 'CP1_live')
    require(required == pin['required_live'], 'CP1_live')
    needed = [entry['ticket'] for entry in required]
    require(needed == sorted(set(needed)), 'CP1_live')
    require([entry['ticket'] for entry in record['live']] == needed, 'CP1_live')
    comments = items(observation['live'], 'comment', 'id', 'CP1_live')
    require(len(comments) == len(needed), 'CP1_live')
    by_id = {comment['id']:comment for comment in comments}
    for requirement, reference in zip(required, record['live']):
        comment = by_id.get(reference['comment_id'])
        require(comment is not None and comment['repository'] == pin['repository']
            and comment['subject'] == requirement['ticket']
            and comment['writer_role'] == 'live_runner'
            and digest(comment['body']) == reference['body_sha256'], 'CP1_live')
        try:
            live = checked(read_json(comment['body']), 'live_result', 'CP1_live')
        except (ValueError, Held):
            raise Held('CP1_live') from None
        claims = [check['claim'] for check in live['checks']]
        require(live['repository'] == pin['repository'] and live['spec'] == pin['spec']
            and live['ticket'] == requirement['ticket'] and live['candidate'] == pin['candidate']
            and live['evidence_class'] == 'live_observation' and live['result'] == 'passed'
            and live['gaps'] == [] and claims == requirement['claims']
            and claims == sorted(set(claims))
            and all(check['result'] == 'passed' for check in live['checks']), 'CP1_live')


def verify_read(pin, observation, effect):
    checked(observation, 'observation', 'CP1_unreadable')
    require(observation['repository'] == {'name':pin['repository'], 'private':True}
            and observation['spec'] == pin['spec'], 'CP1_identity')
    record = checkpoint(pin, observation)
    checked(observation['plan'], 'plan', 'CP1_plan')
    require(record['plan'] == observation['plan'], 'CP1_plan')
    tickets = planned_tickets(observation['plan'], pin['spec'])
    require(record['candidate'] == pin['candidate'] == observation['candidate'], 'CP1_build')
    verify_live(pin, record, observation)
    follow_ups = items(observation['follow_ups'], 'follow_up', 'ticket', 'CP1_follow_ups')
    require(follow_ups == record['follow_ups']
        and [f['ticket'] for f in follow_ups] == sorted(f['ticket'] for f in follow_ups)
        and all(f['classification'] == 'polish' and 'polish' in f['labels']
            and f['labels'] == sorted(set(f['labels'])) and f['ticket'] not in tickets
            for f in follow_ups), 'CP1_follow_ups')
    planned = checked(observation['planned'], 'planned', 'CP1_planned_work')
    require([t['ticket'] for t in planned] == tickets
        and all(t['state'] == 'closed' and (t['verified_merge'] if t['kind'] == 'builder'
            else t['human_complete']) for t in planned), 'CP1_planned_work')
    if effect == 'all_closed':
        require(observation['summary_recorded'] is True
            and all(t['archived'] for t in planned)
            and all(f['state'] == 'closed' and (not f['subissue'] or f['archived'])
                    for f in follow_ups), 'CP1_tick_conditions')


def verify_completion(reader, pin, effect):
    """Re-read all bindings twice inside this call. A returned result is advisory.

    reader(nonce) must freshly read independent authoritative sources and return
    strict JSON with that nonce. T12 owns trusted production composition.
    """
    try:
        require(effect in EFFECTS, 'CP1_effect_scope')
        require(SCHEMA is not None, 'CP1_unreadable')
        checked(pin, 'pin', 'CP1_malformed')
        for _ in range(2):
            nonce = secrets.token_hex(32)
            try:
                observation = read_json(reader(nonce))
            except Exception:
                raise Held('CP1_unreadable') from None
            require(type(observation) is dict and observation.get('nonce') == nonce, 'CP1_unreadable')
            observation = dict(observation)
            del observation['nonce']
            verify_read(pin, observation, effect)
        return 'CP1_verified'
    except Held as error:
        return str(error)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return 'CP1_malformed'


def record_completion(reader, pin, effects):
    """An in-memory recording sink with no external executor or cached permit."""
    recorded = []
    reason = 'CP1_effect_scope'
    for effect in effects:
        reason = verify_completion(reader, pin, effect)
        if reason != 'CP1_verified':
            break
        recorded.append(effect)
    return {'schema':'openwiz.completion-recording.v1', 'recording_only':True,
            'reason':reason, 'effects':recorded}


def main(args):
    try:
        require(len(args) == 2 and args[0] == '--recording', 'CP1_malformed')
        recording = read_json(Path(args[1]).read_text(encoding='utf-8'))
        require(type(recording) is dict and set(recording) == {'pin','reads','effects'}
            and type(recording['reads']) is list and type(recording['effects']) is list
            and len(recording['effects']) > 0, 'CP1_malformed')
        reads = iter(recording['reads'])
        last = None
        def reader(nonce):
            nonlocal last
            last = next(reads, last)
            if last is None:
                raise OSError('synthetic read unavailable')
            return json.dumps({**last, 'nonce':nonce}, allow_nan=False)
        result = record_completion(reader, recording['pin'], recording['effects'])
    except (OSError, ValueError, TypeError, Held, RecursionError):
        result = {'schema':'openwiz.completion-recording.v1', 'recording_only':True,
                  'reason':'CP1_malformed', 'effects':[]}
    return result, 0 if result['reason'] == 'CP1_verified' else 5


if __name__ == '__main__':
    result, status = main(sys.argv[1:])
    print(json.dumps(result, separators=(',',':')))
    sys.exit(status)
