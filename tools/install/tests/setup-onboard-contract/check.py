import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
SCHEMA_TEXT = (ROOT / 'contracts/setup-onboard.v1.schema.json').read_text()

LIMIT_MS = 1800000
ACTION_LIMIT = 5
LOGIN_BASES = ('github_account_read_back', 'repository_access_read_back')
APP_BASIS = 'installation_token_read_back'
UPSTREAM_BASIS = 'cloudroom_save_observed'
DELIVERY_BASIS = 'delivered_app_id_matches'
VISIBILITY_BASIS = 'github_repository_read'
MERGE_BASIS = 'merge_read_back'
FALLBACK_STEPS = ('open_app_settings', 'generate_key', 'encode_key', 'paste_protected_prompt', 'delete_download')
PREPARED = ('prepared_plan', 'private_instruction')
CREDENTIALS = [re.compile(p) for p in (
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}',
    r'\bgithub_pat_[A-Za-z0-9_]{20,}',
    r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.',
    r'OPENWIZ_GITHUB_APP_KEY[ \t]*=[ \t]*\S',
)]

P, F, U = 'problem', 'failure', 'unproven'
CODES = {
    'not_strict_json': P, 'schema': P, 'synthetic_live': P, 'synthetic_unlabelled': P,
    'live_without_private_record': P, 'leaked_credential': P,
    'login_weak_evidence': P, 'app_weak_evidence': P, 'stale_evidence:<which>': P, 'skip_not_chosen': P,
    'silent_identity_switch': P, 'selection_without_choice': P, 'skipped_app_verified': P,
    'user_app_not_private': P, 'factory_app_not_explicit': P, 'cross_account_private_app': P,
    'all_repositories_installation': P, 'repository_not_installed': P, 'identity_ready_inconsistent': P,
    'upstream_weak_evidence': P, 'agent_save_unavailable': P, 'no_paste_route_inconsistent': P,
    'fallback_step_missing:<step>': P, 'owner_step_uncounted:<step>': P, 'converted_key_kept': P,
    'fallback_download_unrecorded': P, 'delivery_weak_evidence': P, 'secret_success_claimed': P,
    'authorization_mismatch': P, 'preview_authorized': P,
    'visibility_unverified_init': P, 'brain_placement_mismatch': P, 'brain_visibility_mismatch': P,
    'brain_not_private': P, 'companion_same_repository': P, 'in_repository_mismatch': P,
    'brain_pair_mismatch': P, 'unexpected_companion': P, 'outcome_brain_missing': P,
    'brain_change_not_visible': P, 'report_line_missing_location': P, 'phase_effect_mismatch:<kind>': P,
    'duplicate_effect_row:<kind>:<repository>': P,
    'clock_order': P, 'clock_not_merge': P, 'outside_clock:<list>:<index>': P, 'action_count_mismatch': P,
    'merge_weak_evidence': P, 'secret_steps_uncounted': P, 'app_steps_uncounted': P,
    'identity_route_inconsistent': P, 'non_live_pass': P, 'unproven_pass': P, 'failure_not_reported': P,
    'key_download_retained': F, 'duplicate_app_registration': F, 'secret_store_failed': F,
    'private_content_published': F, 'duplicate_effect:<kind>': F, 'blind_retry:<kind>': F,
    'thirty_minutes_missed': F, 'actions_exceeded': F, 'init_only_merge': F,
    'not_live': U, 'key_download_unknown': U, 'delivery_unverified': U, 'effect_uncertain:<kind>': U,
    'outcome_uncertain': U, 'clock_unknown': U, 'action_count_unknown': U, 'candidate_unknown': U,
    'repository_unknown': U, 'prepared_help': U, 'not_fresh:<which>': U, 'seeded_state': U,
    'initial_record_missing': U, 'decision_unsaved:<decision>': U, 'secret_route_unobserved': U,
}


class Report:
    def __init__(self, problems=(), failures=(), unproven=()):
        self.problems = sorted(set(problems))
        self.failures = sorted(set(failures))
        self.unproven = sorted(set(unproven))


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate key')
    return dict(pairs)


def _refuse_number(text):
    raise ValueError('not an integer: ' + text)


def strict_json(text):
    return json.loads(text, object_pairs_hook=_pairs, parse_float=_refuse_number,
                      parse_constant=_refuse_number)


SCHEMA = strict_json(SCHEMA_TEXT)


def _is(value, kind):
    return {'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str), 'boolean': isinstance(value, bool), 'null': value is None,
            'integer': isinstance(value, int) and not isinstance(value, bool),
            'number': isinstance(value, (int, float)) and not isinstance(value, bool)}[kind]


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _anchored(pattern):
    return pattern[:-1] + r'\Z' if pattern.endswith('$') and not pattern.endswith('\\$') else pattern


def schema_errors(value, schema, root, path='$'):
    if schema is True:
        return []
    if '$ref' in schema:
        name = schema['$ref']
        if not name.startswith('#/$defs/'):
            return [f'{path}: unsupported $ref']
        return schema_errors(value, root['$defs'][name[8:]], root, path)
    errors = []
    if 'type' in schema:
        kinds = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(_is(value, k) for k in kinds):
            return [f'{path}: not {schema["type"]}']
    if 'const' in schema and not _equal(value, schema['const']):
        errors.append(f'{path}: not the constant')
    if 'enum' in schema and not any(_equal(value, e) for e in schema['enum']):
        errors.append(f'{path}: not in enum')
    if isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 1 << 30):
            errors.append(f'{path}: length')
        if 'pattern' in schema and not re.search(_anchored(schema['pattern']), value):
            errors.append(f'{path}: pattern')
    if _is(value, 'number'):
        if 'minimum' in schema and value < schema['minimum']:
            errors.append(f'{path}: below minimum')
        if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
            errors.append(f'{path}: not above exclusive minimum')
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 1 << 30):
            errors.append(f'{path}: item count')
        if 'items' in schema:
            for i, item in enumerate(value):
                errors += schema_errors(item, schema['items'], root, f'{path}[{i}]')
        if 'contains' in schema and not any(not schema_errors(v, schema['contains'], root, path) for v in value):
            errors.append(f'{path}: contains nothing required')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}: missing {key}')
        for key, item in value.items():
            if key in props:
                errors += schema_errors(item, props[key], root, f'{path}.{key}')
            elif schema.get('additionalProperties') is False:
                errors.append(f'{path}: extra key {key}')
    for sub in schema.get('allOf', []):
        errors += schema_errors(value, sub, root, path)
    if 'anyOf' in schema and all(schema_errors(value, s, root, path) for s in schema['anyOf']):
        errors.append(f'{path}: matches none of anyOf')
    if 'oneOf' in schema and sum(not schema_errors(value, s, root, path) for s in schema['oneOf']) != 1:
        errors.append(f'{path}: does not match exactly one of oneOf')
    if 'not' in schema and not schema_errors(value, schema['not'], root, path):
        errors.append(f'{path}: matches not')
    if 'if' in schema and not schema_errors(value, schema['if'], root, path) and 'then' in schema:
        errors += schema_errors(value, schema['then'], root, path)
    return errors


def credential_shapes(text):
    return [p.pattern for p in CREDENTIALS if p.search(text)]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def check_text(text):
    try:
        doc = strict_json(text)
    except ValueError:
        return Report(['not_strict_json'])
    return check(doc)


def check(doc):
    if schema_errors(doc, SCHEMA, SCHEMA):
        return Report(['schema'])
    p, f, u = [], [], []
    live = doc['proof_class'] == 'live'
    if not live:
        u.append('not_live')
    if live and doc['synthetic_assumptions']:
        p.append('synthetic_live')
    if not live and not doc['synthetic_assumptions']:
        p.append('synthetic_unlabelled')
    if live and doc['private_record'] is None:
        p.append('live_without_private_record')
    if any(credential_shapes(text) for text in _strings(doc)):
        p.append('leaked_credential')
    {'identity_selection': _identity, 'secret_capability': _secret, 'init_request': _request,
     'init_result': _init, 'brain_reference': lambda d, p, f, u: _brain(d['brain'], p),
     'first_merge_receipt': _receipt}[doc['kind']](doc, p, f, u)
    if doc['kind'] == 'first_merge_receipt':
        if f and doc['verdict'] != 'fail':
            p.append('failure_not_reported')
        if doc['verdict'] == 'pass':
            if not live:
                p.append('non_live_pass')
            if u:
                p.append('unproven_pass')
    return Report(p, f, u)


def _owner(repository):
    return repository.split('/')[0].lower()


def _established(evidence, bases, revision, name, weak, p):
    if not all(any(e['basis'] == b for e in evidence) for b in bases):
        p.append(weak)
    elif not all(any(e['basis'] == b and e['revision'] == revision for e in evidence) for b in bases):
        p.append('stale_evidence:' + name)


def _identity(doc, p, f, u):
    revision, login, app = doc['check_revision'], doc['personal_login'], doc['app']
    if login['state'] == 'verified':
        _established(login['evidence'], LOGIN_BASES, revision, 'personal_login', 'login_weak_evidence', p)
    if app is not None:
        if app['state'] == 'verified':
            _established(app['evidence'], (APP_BASIS,), revision, 'app', 'app_weak_evidence', p)
        if app['mode'] == 'user' and (app['visibility'] != 'private' or app['visibility_setting'] != 'user_default'):
            p.append('user_app_not_private')
        if app['mode'] == 'factory' and (app['visibility'] != 'public'
                                         or app['visibility_setting'] != 'explicit_factory'):
            p.append('factory_app_not_explicit')
        installation = app['installation']
        if app['mode'] == 'user':
            owner = app['owner_account'].lower()
            owners = {_owner(doc['repository'])}
            if installation is not None:
                owners |= {installation['account'].lower()} | {_owner(r) for r in installation['repositories']}
            if owners != {owner}:
                p.append('cross_account_private_app')
        if installation is not None and installation['repository_selection'] != 'selected':
            p.append('all_repositories_installation')
        covered = installation is not None and any(
            r.lower() == doc['repository'].lower() for r in installation['repositories'])
        if app['state'] == 'verified' and not covered:
            p.append('repository_not_installed')
        if doc['app_choice'] == 'skip' and app['state'] == 'verified':
            p.append('skipped_app_verified')
    if doc['selection_basis'] == 'fallback':
        p.append('silent_identity_switch')
    elif doc['selected'] != 'unselected' and doc['selection_basis'] == 'none':
        p.append('selection_without_choice')
    if doc['selected'] == 'personal_login' and doc['app_choice'] != 'skip':
        p.append('skip_not_chosen')
    app_ok = app is not None and app['state'] == 'verified'
    ready = login['state'] == 'verified' and (
        (doc['selected'] == 'app' and doc['app_choice'] in ('create', 'reuse') and app_ok)
        or (doc['selected'] == 'personal_login' and doc['app_choice'] == 'skip'))
    if doc['ready'] != ready:
        p.append('identity_ready_inconsistent')


def _secret(doc, p, f, u):
    upstream, steps = doc['upstream'], doc['steps']
    if upstream['state'] == 'observed_supported' and not any(
            e['basis'] == UPSTREAM_BASIS for e in upstream['evidence']):
        p.append('upstream_weak_evidence')
    for s in steps:
        if s['actor'] == 'owner' and not s['counted']:
            p.append('owner_step_uncounted:' + s['step'])
    key_file = doc['intermediate_key_file']
    if doc['route'] == 'agent_save':
        if upstream['state'] != 'observed_supported':
            p.append('agent_save_unavailable')
        if (doc['converted_key'] != 'stored_by_agent_save' or key_file != 'none'
                or not steps or any(s['step'] != 'agent_save' or s['actor'] != 'agent' for s in steps)):
            p.append('no_paste_route_inconsistent')
    else:
        owned = {s['step'] for s in steps if s['actor'] == 'owner'}
        for step in FALLBACK_STEPS:
            if step not in owned:
                p.append('fallback_step_missing:' + step)
        if doc['converted_key'] != 'discarded':
            p.append('converted_key_kept')
        if key_file == 'none':
            p.append('fallback_download_unrecorded')
    if key_file == 'owner_download_retained':
        f.append('key_download_retained')
    elif key_file == 'unknown':
        u.append('key_download_unknown')
    delivery = doc['delivery']
    delivered = delivery['state'] == 'verified'
    if delivered and not any(e['basis'] == DELIVERY_BASIS for e in delivery['evidence']):
        p.append('delivery_weak_evidence')
    if doc['outcome'] == 'stored' and not delivered:
        p.append('secret_success_claimed')
    if doc['outcome'] == 'failed' or delivery['state'] == 'refused':
        f.append('secret_store_failed')
    elif doc['outcome'] == 'uncertain' or delivery['state'] in ('missing', 'unknown', 'uncertain'):
        u.append('delivery_unverified')
    if doc['app_registrations'] > 1:
        f.append('duplicate_app_registration')


def _request(doc, p, f, u):
    auth = doc['authorization']
    if doc['mode'] == 'preview':
        if auth is not None:
            p.append('preview_authorized')
    elif auth is None or (auth['operation_id'], auth['fingerprint']) != (doc['operation_id'], doc['fingerprint']):
        p.append('authorization_mismatch')


def _same(a, b):
    return a.lower() == b.lower()


def _brain(brain, p):
    code, home = brain['code_repository'], brain['brain_repository']
    if (brain['code_visibility'] == 'private') != (brain['location'] == 'in_repository'):
        p.append('brain_placement_mismatch')
    if brain['brain_visibility'] != {'known': 'private'} or brain['visibility_basis'] != VISIBILITY_BASIS:
        p.append('brain_not_private')
    pair = brain['decision_repositories']
    if brain['location'] == 'companion':
        if _same(code, home):
            p.append('companion_same_repository')
        expected = {'public': code, 'private': home}
        if pair is None or any(not _same(pair[role]['owner'] + '/' + pair[role]['name'], expected[role])
                               for role in expected):
            p.append('brain_pair_mismatch')
    else:
        if not _same(code, home):
            p.append('in_repository_mismatch')
        if pair is not None:
            p.append('brain_pair_mismatch')


def _init(doc, p, f, u):
    repo, brain, outcome = doc['repository'], doc['brain'], doc['outcome']
    visibility = repo['visibility'].get('known') if repo['basis'] == VISIBILITY_BASIS else None
    effects = doc['effects']
    if visibility is None:
        if (outcome != 'refused' or brain is not None or doc['private_content_written'] != 'none'
                or any(e['effect_count'] for e in effects)):
            p.append('visibility_unverified_init')
    else:
        if brain is not None:
            if brain['code_visibility'] != visibility:
                p.append('brain_visibility_mismatch')
            if not _same(brain['code_repository'], repo['full_name']) or \
                    (visibility == 'private') != (brain['location'] == 'in_repository'):
                p.append('brain_placement_mismatch')
        if visibility == 'private' and any(e['kind'] in ('create_companion', 'link_companion') for e in effects):
            p.append('unexpected_companion')
        if visibility == 'public' and doc['private_content_written'] == 'code_repository':
            f.append('private_content_published')
    if brain is not None:
        _brain(brain, p)
    if outcome in ('proposed', 'applied') and brain is None:
        p.append('outcome_brain_missing')
    if brain is not None and outcome == 'applied' and not any(
            pr['visible'] and pr['state'] in ('open', 'merged') and _same(pr['repository'], brain['brain_repository'])
            for pr in doc['pull_requests']):
        p.append('brain_change_not_visible')
    if brain is not None and outcome in ('proposed', 'applied'):
        words = {w.strip('.,;:()') for w in doc['report_line'].split()}
        if not any(_same(w, brain['brain_repository']) for w in words):
            p.append('report_line_missing_location')
    seen = set()
    for e in effects:
        key = (e['kind'], e['repository'].lower())
        if key in seen:
            p.append(f"duplicate_effect_row:{e['kind']}:{e['repository']}")
        seen.add(key)
        phase = e['phase']
        if ((phase == 'applied') != (e['effect_count'] >= 1) and phase != 'uncertain') or \
                (e['attempts'] == 0 and phase in ('applied', 'uncertain')):
            p.append('phase_effect_mismatch:' + e['kind'])
        if e['effect_count'] > 1:
            f.append('duplicate_effect:' + e['kind'])
        if e['attempts'] > 1 and e['reconciliation'] != 'provider_read_back':
            f.append('blind_retry:' + e['kind'])
        if phase == 'uncertain':
            u.append('effect_uncertain:' + e['kind'])
        if e['kind'] == 'merge_pull_request':
            made = [c for c in effects if c['kind'] == 'create_companion' and _same(c['repository'], e['repository'])]
            states = [pr['state'] for pr in doc['pull_requests'] if _same(pr['repository'], e['repository'])]
            if (visibility != 'public' or not made or (e['attempts'] and made[0]['phase'] != 'applied')
                    or (phase == 'applied' and states != ['merged'])):
                p.append('phase_effect_mismatch:merge_pull_request')
    if outcome == 'uncertain':
        u.append('outcome_uncertain')


def _receipt(doc, p, f, u):
    binding, clock, actions = doc['binding'], doc['clock'], doc['actions']
    merge = binding['merge']
    if 'unknown' in binding['candidate']:
        u.append('candidate_unknown')
    if 'unknown' in binding['repository']:
        u.append('repository_unknown')
    start, end = clock['started_at_ms'].get('known'), clock['ended_at_ms'].get('known')
    timed = start is not None and end is not None
    if not timed:
        u.append('clock_unknown')
    elif end < start:
        p.append('clock_order')
        timed = False
    else:
        if end != merge['merged_at_ms']:
            p.append('clock_not_merge')
        if end - start >= LIMIT_MS:
            f.append('thirty_minutes_missed')

    def inside(t):
        return not timed or start <= t <= end

    log = actions['log']
    for i, a in enumerate(log):
        if not inside(a['at_ms']):
            p.append(f'outside_clock:action:{i}')
    for i, w in enumerate(doc['waits']):
        if w['ended_at_ms'] < w['started_at_ms'] or not (inside(w['started_at_ms']) and inside(w['ended_at_ms'])):
            p.append(f'outside_clock:wait:{i}')
    for i, h in enumerate(doc['help']):
        if not inside(h['at_ms']):
            p.append(f'outside_clock:help:{i}')
        if h['source'] in PREPARED:
            u.append('prepared_help')
    count = actions['count'].get('known')
    if count is None:
        u.append('action_count_unknown')
    else:
        if count != len(log):
            p.append('action_count_mismatch')
        if count > ACTION_LIMIT:
            f.append('actions_exceeded')
    if merge['basis'] != MERGE_BASIS or merge['reviewed_head'] != merge['head'] or merge['ci_green_head'] != merge['head']:
        p.append('merge_weak_evidence')
    if merge['change'] == 'init_only':
        f.append('init_only_merge')
    kinds = [a['kind'] for a in log]
    route, registration = doc['secret_route'], doc['app_registration']
    if route == 'protected_paste' and (kinds.count('key_step') < 4 or kinds.count('protected_paste') < 1):
        p.append('secret_steps_uncounted')
    if registration == 'created' and kinds.count('app_manifest') < 2:
        p.append('app_steps_uncounted')
    if doc['identity'] == 'personal_login':
        consistent = registration == 'skipped' and route == 'not_used'
    else:
        consistent = registration != 'skipped' and (registration == 'reused' or route != 'not_used')
    if not consistent:
        p.append('identity_route_inconsistent')
    if route != 'not_used' and not doc['secret_route_observed']:
        u.append('secret_route_unobserved')
    for name in ('spec_confirmation', 'plan_approval'):
        if not doc['decisions'][name]:
            u.append('decision_unsaved:' + name)
    fresh = doc['freshness']
    for which in ('machine', 'repository'):
        if fresh[which] != 'fresh':
            u.append('not_fresh:' + which)
    if fresh['seeded_openwiz_state']:
        u.append('seeded_state')
    if fresh['initial_record'] != 'recorded':
        u.append('initial_record_missing')
