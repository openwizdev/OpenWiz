#!/usr/bin/env python3
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

SCHEMA = 'openwiz.setup-onboard.v1'
FOLDER = '.openwiz/brain'
BRANCH = 'openwiz/brain'
LABEL = 'openwiz'
LABELS = ((LABEL, '5319e7', 'OpenWiz specs and tickets'),
          ('spec', 'c5def5', 'The issue is a spec'),
          ('ready-for-agent', '0e8a16', 'Fully specified, ready for an agent to take unattended'),
          ('ready-for-human', '1d76db', 'Requires human implementation'),
          ('needs-info', 'd4c5f9', 'Waiting on reporter for more information'),
          ('held', 'fef2c0', "Held: waits for the user's approval"))
BASIS = 'github_repository_read'
SUFFIX = '-brain'
TIMEOUT = 60
JOURNAL = 'openwiz.init-journal.v1'
MAX_JOURNAL = 16
ASSUMPTIONS = ['A command outcome is not a live proof; live brain creation is observed only under its own kit.']
HEX32 = re.compile('[0-9a-f]{32}')
ORDER = ('create_companion', 'link_companion', 'create_label', 'open_pull_request')


class Exit(Exception):
    def __init__(self, code, document):
        super().__init__(code)
        self.code, self.document = code, document


def error(code, kind, message):
    return Exit(code, {'schema': 'openwiz.cli-error.v1', 'command': 'init', 'exit_code': code,
                       'error': {'kind': kind, 'message': message}})


class GitHub:
    def __init__(self):
        self.program = shutil.which('gh')
        if self.program is None:
            raise error(1, 'unavailable', 'GitHub CLI (gh) is not installed or not on PATH; sign in with gh first.')

    def call(self, method, path, body=None):
        argv = [self.program, 'api', '--include', '-X', method, path]
        if body is not None:
            argv += ['--input', '-']
        try:
            result = subprocess.run(argv, input=None if body is None else json.dumps(body).encode(),
                                    stdin=subprocess.DEVNULL if body is None else None,
                                    capture_output=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        head, _, raw = result.stdout.replace(b'\r\n', b'\n').partition(b'\n\n')
        status = re.match(rb'HTTP/[0-9.]+ ([0-9]{3})', head)
        if status is None:
            return None, None
        status = int(status.group(1))
        try:
            value = json.loads(raw, object_pairs_hook=store.unique) if raw.strip() else None
        except ValueError:
            value = None
        return status, value


def quote(path):
    return urllib.parse.quote(path, safe='/')


def same(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def visibility_of(repository, value):
    if type(value) is not dict or not same(value.get('full_name'), repository):
        return None
    visibility, private = value.get('visibility'), value.get('private')
    if visibility == 'private' and private is True:
        return 'private'
    if visibility == 'public' and private is False:
        return 'public'
    return None


def files(brain):
    settings = {'schema': 'openwiz.brain-settings.v1', 'brain_location': brain['location'],
                'code_repository': brain['code_repository'], 'brain_repository': brain['brain_repository'],
                'folder': FOLDER, 'factory_label': LABEL,
                'decision_repositories': brain['decision_repositories']}
    where = ('this repository, which is private' if brain['location'] == 'in_repository'
             else f"this private companion of {brain['code_repository']}")
    return {
        f'{FOLDER}/README.md': (
            '# OpenWiz brain\n\n'
            f"The factory's private, human-readable records for {brain['code_repository']} live here, in {where}.\n\n"
            '- `grills/`: design grills and their confirmed decisions.\n'
            '- `decisions/`: decision records; public records carry only summaries and pointers here.\n'
            '- `settings.json`: the one factory-settings record.\n\n'
            'Specs and tickets stay GitHub issues, with sub-issues, blocking links and the '
            f'`{LABEL}` label. Credentials, machine details, runtime state and thread identifiers never go here.\n\n'
            'To move the brain later, change `brain_location` through `openwiz init`, which proposes the move '
            'through a visible pull request in the same way.\n'),
        f'{FOLDER}/settings.json': json.dumps(settings, indent=2, sort_keys=True) + '\n',
        f'{FOLDER}/grills/README.md': '# Grills\n\nOne file per grill: its questions and the confirmed answers.\n',
        f'{FOLDER}/decisions/README.md': '# Decisions\n\nOne file per decision, with its date and source.\n',
    }


def brain_for(repository, visibility, owner, name):
    if visibility == 'private':
        return {'location': 'in_repository', 'code_repository': repository, 'code_visibility': 'private',
                'brain_repository': repository, 'brain_visibility': {'known': 'private'},
                'visibility_basis': BASIS, 'folder': FOLDER, 'setting': 'brain_location',
                'decision_repositories': None}
    companion = f'{owner}/{name}{SUFFIX}'
    return {'location': 'companion', 'code_repository': repository, 'code_visibility': 'public',
            'brain_repository': companion, 'brain_visibility': {'known': 'private'},
            'visibility_basis': BASIS, 'folder': FOLDER, 'setting': 'brain_location',
            'decision_repositories': {'public': {'owner': owner, 'name': name},
                                      'private': {'owner': owner, 'name': name + SUFFIX}}}


def marker(code):
    return f'OpenWiz private brain for {code}'


def link(code):
    return f'https://github.com/{code}'


class Plan:
    def __init__(self, gh, repository):
        self.gh = gh
        self.requested = repository
        self.missing = []
        self.visibility = None
        self.reason = 'GitHub did not answer the visibility read.'
        self.brain = None
        self.refusal = None
        status, value = gh.call('GET', f'repos/{repository}')
        if status is None:
            return
        if status != 200:
            self.reason = f'GitHub refused the repository read (HTTP {status}).'
            return
        self.visibility = visibility_of(repository, value)
        if self.visibility is None:
            self.reason = 'GitHub gave no single private or public visibility for the repository.'
            return
        self.repository = value['full_name']
        self.code = value
        owner, name = self.repository.split('/')
        self.owner_type = (value.get('owner') or {}).get('type')
        self.brain = brain_for(self.repository, self.visibility, owner, name)
        self.content = files(self.brain)
        if not (value.get('permissions') or {}).get('push'):
            self.refusal = ('no_push_access', 'Your GitHub login cannot push to the repository; nothing was written.')
        elif self.visibility == 'public' and len(name + SUFFIX) > 100:
            self.refusal = ('companion_name_unsafe',
                            'The private companion name would be too long for GitHub; nothing was written.')
        elif self.visibility == 'public' and self.owner_type not in ('User', 'Organization'):
            self.refusal = ('companion_owner_unknown', 'The repository owner could not be read; nothing was written.')
        elif self.visibility == 'public' and self.owner_type == 'User':
            status, user = gh.call('GET', 'user')
            if status != 200 or type(user) is not dict or not same(user.get('login'), owner):
                self.refusal = ('companion_owner_mismatch', 'Only the repository owner can create its private '
                                'companion; nothing was written.')

    def request(self):
        return {'repository': self.repository, 'visibility': self.visibility,
                'location': self.brain['location'], 'brain_repository': self.brain['brain_repository'],
                'labels': [list(label) for label in LABELS], 'branch': BRANCH,
                'files': {p: hashlib.sha256(t.encode()).hexdigest() for p, t in sorted(self.content.items())}}

    def companion(self):
        status, value = self.gh.call('GET', f"repos/{self.brain['brain_repository']}")
        if status == 404:
            return False
        if status != 200 or type(value) is not dict:
            raise Unread()
        if (not same(value.get('full_name'), self.brain['brain_repository'])
                or visibility_of(value.get('full_name'), value) != 'private'
                or value.get('description') != marker(self.repository)):
            raise Refusal('companion_conflict', 'A repository with the companion name exists and is not this '
                          "project's private brain; nothing was written.")
        self.companion_repo = value
        return True

    def linked(self):
        if not self.companion():
            return False
        return self.companion_repo.get('homepage') == link(self.repository)

    def destination(self):
        b = self.brain['brain_repository']
        status, value = self.gh.call('GET', f'repos/{b}')
        if status is None:
            raise Unread()
        if (status != 200 or type(value) is not dict or visibility_of(b, value) != 'private'
                or not isinstance(value.get('default_branch'), str)
                or (self.brain['location'] == 'companion' and value.get('description') != marker(self.repository))):
            raise Refusal('brain_not_private', f"{b} no longer reads back as this project's private brain; "
                          'nothing more was written.')
        return value

    def proposal(self):
        found = self.pull()
        if found is None:
            raise Unread()
        if found['state'] == 'closed':
            raise Refusal('proposal_closed', f"The brain proposal on {self.brain['brain_repository']} was closed; "
                          'init does not reopen or replace it.')
        return found

    def missing_labels(self):
        missing = []
        for name, _, _ in LABELS:
            status, _ = self.gh.call('GET', f'repos/{self.repository}/labels/{quote(name)}')
            if status not in (200, 404):
                raise Unread()
            if status == 404:
                missing.append(name)
        return missing

    def label(self):
        return not self.missing_labels()

    def pull(self):
        owner = self.brain['brain_repository'].split('/')[0]
        status, value = self.gh.call(
            'GET', f"repos/{self.brain['brain_repository']}/pulls?state=all&head={owner}:{BRANCH}")
        if status == 404 and self.brain['location'] == 'companion':
            return None
        if status != 200 or type(value) is not list:
            raise Unread()
        for item in value:
            if type(item) is dict and (item.get('head') or {}).get('ref') == BRANCH and type(item.get('number')) is int:
                state = ('merged' if item.get('merged_at') else 'closed') if item.get('state') == 'closed' else 'open'
                return {'number': item['number'], 'state': state}
        return None


class Unread(Exception):
    pass


class Refusal(Exception):
    def __init__(self, code, line):
        super().__init__(code)
        self.code, self.line = code, line


def journal_read(setup):
    path = setup.dir / 'init.json'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {'schema': JOURNAL, 'operations': {}}
    try:
        info = os.fstat(fd)
        store.require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0 and info.st_nlink == 1
                      and info.st_size <= store.MAX_BYTES, 'init journal is unsafe')
        with os.fdopen(os.dup(fd), 'rb') as handle:
            value = json.loads(handle.read(store.MAX_BYTES + 1), object_pairs_hook=store.unique)
    finally:
        os.close(fd)
    store.require(type(value) is dict and value.get('schema') == JOURNAL and set(value) == {'schema', 'operations'}
                  and type(value['operations']) is dict, 'init journal is invalid')
    for key, entry in value['operations'].items():
        store.require(HEX32.fullmatch(key) and type(entry) is dict and set(entry) == {'rows', 'pull', 'wrote'}
                      and type(entry['rows']) is list and type(entry['wrote']) is bool, 'init journal is invalid')
        for row in entry['rows']:
            store.require(type(row) is dict and set(row) == {'kind', 'repository', 'phase', 'effect_count',
                                                            'attempts', 'reconciliation'}
                          and row['kind'] in ORDER, 'init journal is invalid')
    return value


def journal_write(setup, value):
    operations = value['operations']
    while len(operations) > MAX_JOURNAL:
        operations.pop(next(iter(operations)))
    setup._write(setup.dir / 'init.json', value)


def result(plan, operation, outcome, reason_code, line, entry=None):
    entry = entry or {'rows': [], 'pull': None, 'wrote': False}
    known = plan.visibility is not None
    pulls = []
    if entry['pull'] is not None and plan.brain is not None:
        pulls = [{'repository': plan.brain['brain_repository'], 'number': entry['pull']['number'],
                  'visible': True, 'state': entry['pull']['state']}]
    return {'schema': SCHEMA, 'kind': 'init_result', 'proof_class': 'recording',
            'synthetic_assumptions': ASSUMPTIONS, 'private_record': None,
            'operation_id': operation['operation_id'], 'fingerprint': operation['fingerprint'],
            'repository': {'full_name': plan.repository if known else plan.requested,
                           'visibility': {'known': plan.visibility} if known else {'unknown': plan.reason},
                           'basis': BASIS},
            'outcome': outcome, 'reason_code': reason_code,
            'brain': plan.brain if outcome != 'refused' else None,
            'private_content_written': 'brain_repository' if entry['wrote'] else 'none',
            'placement_question': False, 'report_line': line,
            'effects': [dict(r) for r in entry['rows']], 'pull_requests': pulls}


def report(brain):
    kind = 'in-repository' if brain['location'] == 'in_repository' else 'private companion'
    return f"Brain: {kind} {brain['brain_repository']} in {FOLDER}; change it with the brain_location setting."


def disclosed(plan, rows):
    b, code = plan.brain['brain_repository'], plan.repository
    text = {'create_companion': f'Create the private repository {b} for the brain.',
            'link_companion': f'Link {b} to {code} (its homepage), exposing nothing in {code}.',
            'create_label': f'Create the labels {", ".join(plan.missing)} on {code} for specs and tickets; '
                            'labels already there are kept as they are.',
            'open_pull_request': f'Open a visible pull request on {b} proposing {FOLDER} (records only).'}
    return [text[r['kind']] for r in rows] or [f'Reuse the existing brain proposal on {b}; nothing new is written.']


def needed(plan):
    rows = []
    b, code = plan.brain['brain_repository'], plan.repository

    def row(kind, repository):
        rows.append({'kind': kind, 'repository': repository, 'phase': 'proposed', 'effect_count': 0,
                     'attempts': 0, 'reconciliation': 'none'})
    if plan.brain['location'] == 'companion':
        present = plan.companion()
        if not present:
            row('create_companion', b)
        if not present or plan.companion_repo.get('homepage') != link(code):
            row('link_companion', b)
    plan.missing = plan.missing_labels()
    if plan.missing:
        row('create_label', code)
    existing = plan.pull() if plan.brain['location'] == 'in_repository' or plan.companion() else None
    if existing is not None and existing['state'] == 'closed':
        raise Refusal('proposal_closed', f'The brain proposal on {b} was closed; reopen or merge it, '
                      'nothing was written.')
    if existing is None:
        row('open_pull_request', b)
    return rows, existing


def refuse(setup, plan, code, line, fingerprint_request):
    operation = setup.propose('prepare_project', fingerprint_request, ['Write nothing: ' + line[:280]],
                              'Refused before any effect.')
    if operation['phase'] == 'proposed':
        operation = setup.settle(operation['operation_id'], 'refused', line[:300])
    raise Exit(5, result(plan, operation, 'refused', code, line))


def preview(setup, plan):
    request = plan.request()
    try:
        rows, existing = needed(plan)
    except Refusal as refusal:
        refuse(setup, plan, refusal.code, refusal.line, {**request, 'refused': refusal.code})
    except Unread:
        raise error(1, 'read_failed', 'GitHub did not answer a read; nothing was saved or written.')
    operation = setup.propose('prepare_project', request, disclosed(plan, rows),
                              'Proposed: confirm with openwiz init --yes --operation.',
                              lambda value: (value.get('brain') or {}).get('brain_repository') == plan.brain['brain_repository'])
    with setup.locked():
        journal = journal_read(setup)
        entry = journal['operations'].get(operation['operation_id'])
        if entry is None:
            entry = {'rows': rows, 'pull': existing, 'wrote': False}
            journal['operations'][operation['operation_id']] = entry
            journal_write(setup, journal)
    phase = operation['phase']
    if phase == 'applied':
        return current(plan, operation, entry)
    if phase == 'uncertain':
        raise Exit(6, result(plan, operation, 'uncertain', 'effect_uncertain',
                             'An earlier apply is uncertain; apply the same operation to reconcile it.', entry))
    return result(plan, operation, 'proposed', 'brain_previewed', report(plan.brain), entry)


def current(plan, operation, entry):
    try:
        plan.destination()
        entry['pull'] = plan.proposal()
    except Refusal as refusal:
        raise Exit(5, result(plan, operation, 'refused', refusal.code, refusal.line, entry))
    except Unread:
        raise error(1, 'read_failed', 'GitHub did not answer a read; nothing was written.')
    return result(plan, operation, 'applied', 'brain_current', report(plan.brain), entry)


def apply(setup, plan, operation_id):
    request = plan.request()
    with setup.locked():
        value = setup._read()
        digest = store.fingerprint('prepare_project', request)
        matches = [o for o in value['operations'] if o['operation_id'] == operation_id]
        if len(matches) != 1 or matches[0]['kind'] != 'prepare_project' or matches[0]['fingerprint'] != digest \
                or matches[0]['phase'] == 'refused':
            stale = {'operation_id': operation_id, 'fingerprint': digest}
            raise Exit(8, result(plan, stale, 'refused', 'operation_stale',
                                 'That operation is unknown, refused or no longer matches GitHub; preview again.'))
        operation = matches[0]
        journal = journal_read(setup)
        entry = journal['operations'].get(operation_id)
        store.require(entry is not None, 'the init journal lost this operation; preview again')
        if operation['phase'] == 'applied':
            return current(plan, operation, entry)

        def save(phase=None, reason=None, brain=False):
            if phase is not None:
                operation['phase'], operation['reason'] = phase, reason
            if brain:
                value['brain'] = plan.brain
                value['revision'] += 1
            store.validate(value)
            journal_write(setup, journal)
            setup._write(setup.file, value)

        def stop(code, outcome, reason_code, line):
            if outcome == 'uncertain':
                save('uncertain', line)
            elif operation['phase'] != 'uncertain' or not any(r['phase'] == 'uncertain' for r in entry['rows']):
                save('refused', line)
            raise Exit(code, result(plan, operation, outcome, reason_code, line, entry))

        for kind in ORDER:
            row = next((r for r in entry['rows'] if r['kind'] == kind), None)
            if row is None or row['phase'] == 'applied':
                continue
            try:
                done = effect(plan, row, entry, journal, save)
            except Refusal as refusal:
                stop(5, 'refused', refusal.code, refusal.line)
            except Unread:
                stop(6, 'uncertain', 'effect_uncertain',
                     'A GitHub reply was lost; apply the same operation to reconcile it before anything else.')
            if done is None:
                stop(6, 'uncertain', 'effect_uncertain',
                     'A GitHub reply was lost; apply the same operation to reconcile it before anything else.')
        try:
            plan.destination()
            entry['pull'] = plan.proposal()
        except Refusal as refusal:
            stop(5, 'refused', refusal.code, refusal.line)
        except Unread:
            stop(6, 'uncertain', 'effect_uncertain',
                 'A GitHub read was lost; apply the same operation to reconcile it before anything else.')
        save('applied', 'Brain proposed. Merge its pull request to accept it.', brain=True)
        return result(plan, operation, 'applied', 'brain_proposed', report(plan.brain), entry)


def proposed(plan):
    found = plan.pull()
    if found is not None and found['state'] == 'closed':
        plan.proposal()
    return found is not None


def effect(plan, row, entry, journal, save):
    present = {'create_companion': plan.companion, 'link_companion': plan.linked,
               'create_label': plan.label, 'open_pull_request': lambda: proposed(plan)}[row['kind']]
    if row['attempts'] > 0:
        row['reconciliation'] = 'provider_read_back'
    if present():
        if row['kind'] == 'open_pull_request':
            entry['pull'] = plan.pull()
        if row['attempts'] == 0:
            entry['rows'].remove(row)
        else:
            row['phase'], row['effect_count'] = 'applied', 1
        save()
        return True
    row['attempts'] += 1
    row['phase'] = 'uncertain'
    save()
    try:
        status = write(plan, row, entry, save)
    except Refusal:
        row['phase'] = 'refused'
        raise
    if status is None:
        return None
    if status in range(200, 300):
        row['phase'], row['effect_count'] = 'applied', 1
        save()
        return True
    row['phase'] = 'refused'
    raise Refusal('companion_denied' if row['kind'] == 'create_companion' else 'effect_denied',
                  f"GitHub refused {row['kind'].replace('_', ' ')} (HTTP {status}); no private content "
                  'was published.')


def write(plan, row, entry, save):
    gh, b, code = plan.gh, plan.brain['brain_repository'], plan.repository
    kind = row['kind']
    if kind == 'create_companion':
        owner, name = b.split('/')
        path = 'user/repos' if plan.owner_type == 'User' else f'orgs/{owner}/repos'
        return gh.call('POST', path, {'name': name, 'private': True, 'description': marker(code),
                                      'auto' '_init': True, 'has_issues': False, 'has_wiki': False})[0]
    if kind == 'link_companion':
        return gh.call('PATCH', f'repos/{b}', {'homepage': link(code)})[0]
    if kind == 'create_label':
        missing = plan.missing_labels()
        for name, color, description in LABELS:
            if name not in missing:
                continue
            status = gh.call('POST', f'repos/{code}/labels',
                             {'name': name, 'color': color, 'description': description})[0]
            if status is None or status >= 500:
                return None
            if status == 422:
                status, _ = gh.call('GET', f'repos/{code}/labels/{quote(name)}')
                if status == 200:
                    continue
                if status != 404:
                    return None
                return 422
            if status not in range(200, 300):
                return status
        return 201
    base = plan.destination()['default_branch']
    status, ref = gh.call('GET', f'repos/{b}/git/ref/heads/{quote(BRANCH)}')
    if status == 404:
        status, head = gh.call('GET', f'repos/{b}/git/ref/heads/{quote(base)}')
        sha = ((head or {}).get('object') or {}).get('sha') if type(head) is dict else None
        if status != 200 or not isinstance(sha, str):
            return None
        status, _ = gh.call('POST', f'repos/{b}/git/refs', {'ref': f'refs/heads/{BRANCH}', 'sha': sha})
        if status not in (200, 201):
            return status
    elif status != 200:
        return None
    for path, text in plan.content.items():
        status, found = gh.call('GET', f'repos/{b}/contents/{quote(path)}?ref={quote(BRANCH)}')
        if status == 200:
            try:
                current = base64.b64decode((found or {}).get('content', ''), validate=False).decode()
            except (ValueError, AttributeError):
                current = None
            if current != text:
                raise Refusal('owner_work_conflict', f'{path} on {b} already holds other content; '
                              'init never overwrites it, nothing more was written.')
            continue
        if status != 404:
            return None
        entry['wrote'] = True
        save()
        status, _ = gh.call('PUT', f'repos/{b}/contents/{quote(path)}',
                            {'message': f'Propose OpenWiz brain: {path}', 'branch': BRANCH,
                             'content': base64.b64encode(text.encode()).decode()})
        if status is None or status >= 500:
            return None
        if status not in (200, 201):
            return status
    body = (f'OpenWiz proposes its private brain folder `{FOLDER}` for {code}: plain records only '
            '(grills, decisions and one settings record). Merge to accept it, or close it to decline.')
    status, value = gh.call('POST', f'repos/{b}/pulls', {'title': 'Propose the OpenWiz brain', 'head': BRANCH,
                                                         'base': base, 'body': body})
    if status in range(200, 300) and type(value) is dict and type(value.get('number')) is int:
        entry['pull'] = {'number': value['number'], 'state': 'open'}
    elif status is not None and status < 500:
        return status
    else:
        return None
    return status


def parse(argv):
    options, flags = {}, set()
    items = list(argv)
    while items:
        arg = items.pop(0)
        if arg in ('--repository', '--state-dir', '--operation'):
            if arg in options or not items:
                raise error(2, 'usage', 'Each option takes one value, once; see openwiz init --help.')
            options[arg] = items.pop(0)
        elif arg in ('--json', '--yes'):
            if arg in flags:
                raise error(2, 'usage', 'Each flag occurs once; see openwiz init --help.')
            flags.add(arg)
        else:
            raise error(2, 'usage', 'Unknown init argument; see openwiz init --help.')
    if ('--yes' in flags) != ('--operation' in options):
        raise error(2, 'usage', '--yes needs --operation from the preview, and --operation needs --yes.')
    if '--operation' in options and not HEX32.fullmatch(options['--operation']):
        raise error(2, 'usage', 'The operation id is 32 lowercase hexadecimal characters.')
    repository = options.get('--repository')
    if repository is not None and (not store.REPOSITORY.fullmatch(repository)
                                   or repository.split('/')[1] in ('.', '..')):
        raise error(2, 'usage', 'The repository is OWNER/NAME.')
    return options, flags


def main(argv):
    options, flags = parse(argv)
    try:
        setup = store.Store(options.get('--state-dir'))
        saved = setup.read()
    except (store.Refused, OSError):
        raise error(10, 'store_unavailable', 'The private setup state is unusable; nothing was read or written.')
    repository = options.get('--repository') or (saved['project'] or {}).get('repository')
    if repository is None:
        raise error(2, 'usage', 'No repository: pass --repository OWNER/NAME or prepare the project first.')
    plan = Plan(GitHub(), repository)
    if plan.visibility is None:
        refuse(setup, plan, 'visibility_unknown', 'Nothing was written: the repository visibility could not be read.',
               {'repository': repository, 'refused': 'visibility_unknown'})
    if plan.refusal is not None:
        refuse(setup, plan, plan.refusal[0], plan.refusal[1], {**plan.request(), 'refused': plan.refusal[0]})
    if '--yes' in flags:
        return apply(setup, plan, options['--operation'])
    return preview(setup, plan)


if __name__ == '__main__':
    try:
        document, code = main(sys.argv[1:]), 0
    except Exit as done:
        document, code = done.document, done.code
    except store.Refused:
        document, code = error(10, 'store_unavailable', 'The private setup state is unusable.').document, 10
    except (OSError, ValueError):
        document, code = error(1, 'read_failed', 'Init could not complete safely; nothing more was written.').document, 1
    print(json.dumps(document, sort_keys=True))
    sys.exit(code)
