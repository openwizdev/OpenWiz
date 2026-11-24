#!/usr/bin/env python3
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

DESCRIPTION = "OpenWiz setup: prepare one project and check each connection independently (#1105).\n\n  setup.py prepare --repository OWNER/NAME --project PRJ --operator NAME \\\n      --service-issue N --answer-thread THR --harness H --model M --effort E\n      With --host NAME other than cloud, omit --project and --answer-thread.\n      Without --yes: records the proposed settings and prints their effects,\n      operation id and fingerprint; nothing else is saved. With\n      --yes --operation ID: saves exactly that preview's settings.\n  setup.py check\n      Reads CloudRoom through the installed openwiz CLI, the agents' own\n      GitHub login through gh, and OpenWiz's App through GitHub's App API, and\n      records one result code per component. Reads only: the App's\n      installation token is minted to prove access, then discarded. Beside\n      each code it prints one `next` line: the exact command to run, or the\n      person's step (#2143).\n\nResults go to owner-only `<state>/setup/state.json` (store.py). Output is JSON with fixed public codes: never a token, key,\nprovider body or URL with credentials. No personal-token fallback for the App.\nPython 3.9+, standard library and /usr/bin/openssl only.\n"

HERE = Path(__file__).resolve().parent
PROFILE = {'metadata': 'read', 'contents': 'write', 'issues': 'write',
           'pull_requests': 'write', 'checks': 'read', 'actions': 'read'}
WRITES = ('contents', 'issues', 'pull_requests')
SKILLS = ('setup', 'grill', 'to-tickets', 'launch-fleet')
API = 'https://api.github.com'
OPENSSL = '/usr/bin/openssl'
TIMEOUT = 30


def run(argv, limit=4 * 1024 * 1024, env=None):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if len(result.stdout) > limit:
        return result.returncode, None
    try:
        return result.returncode, json.loads(result.stdout, object_pairs_hook=store.unique)
    except ValueError:
        return result.returncode, None


def check_cloudroom(openwiz, state=None):
    tool = HERE.parent / 'cloudroom/cloudroom.py'
    if state is not None and tool.is_file():
        spec = importlib.util.spec_from_file_location('openwiz_cloudroom', tool)
        cloudroom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cloudroom)
        return cloudroom.status(cloudroom.Host(), state)['code']
    if openwiz is None:
        return 'cloudroom_missing'
    code, value = run([str(openwiz), 'ls', '--json', '--limit', '1'])
    if code != 0 or type(value) is not dict or value.get('schema') != 'openwiz.inventory.v1':
        return 'cloudroom_unreadable'
    if (value.get('coverage') or {}).get('state') != 'complete' or value.get('gaps') != []:
        return 'cloudroom_partial'
    return 'cloudroom_reachable'


HARNESS_PROGRAMS = {'claude-code': 'claude', 'codex': 'codex'}


def check_harness(openwiz, project):
    if project is None:
        return 'harness_unselected'
    if 'host' in project:
        return check_local_harness(openwiz, project)
    if openwiz is None:
        return 'harness_unreadable'
    code, value = run([str(openwiz), 'models', '--json'])
    if code not in (0, 13) or type(value) is not dict or value.get('schema') != 'openwiz.cloud-options.v1':
        return 'harness_unreadable'
    if value.get('state', {}).get('kind') != 'offered':
        return 'harness_unreadable'
    for harness in value.get('harnesses', []):
        if type(harness) is dict and harness.get('harness') == project['harness']:
            for model in harness.get('models', []):
                if (type(model) is dict and model.get('model') == project['model']
                        and project['effort'] in model.get('efforts', [])):
                    return 'harness_listed'
    return 'harness_unavailable'


def check_local_harness(openwiz, project):
    harness = project['harness']
    program = HARNESS_PROGRAMS.get(harness)
    if (program is None or not re.fullmatch(rf'{MODEL_ID}(?:/{MODEL_ID})*', project['model'])
            or not re.fullmatch(MODEL_ID, project['effort'])):
        return 'harness_unavailable'
    if shutil.which(program) is None:
        return 'harness_not_installed'
    if openwiz is None:
        return 'harness_unreadable'
    code, value = run([str(openwiz), 'models', '--json', '--host', project['host']])
    if (code != 0 or type(value) is not dict or value.get('schema') != 'openwiz.cloud-options.v1'
            or value.get('source') != 'local' or value.get('state') != {'kind': 'offered'}
            or type(value.get('harnesses')) is not list):
        return 'harness_unreadable'
    if any(type(entry) is dict and entry.get('harness') == harness and entry.get('provider') == harness
           for entry in value['harnesses']):
        return 'harness_listed'
    return 'harness_unreadable'


def gh(path):
    program = shutil.which('gh')
    if program is None:
        return None, None
    return run([program, 'api', path])


def github_com(path):
    return github_com_read(path)[:2]


UNAUTHENTICATED = re.compile(rb'gh: [^\n]* \(HTTP 401\)\n?')


def github_com_read(path):
    program = shutil.which('gh')
    if program is None:
        return None, None, True
    try:
        result = subprocess.run([program, 'api', path], stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=TIMEOUT, env={**os.environ, 'GH_HOST': 'github.com'})
    except (OSError, subprocess.TimeoutExpired):
        return None, None, False
    try:
        value = json.loads(result.stdout, object_pairs_hook=store.unique) if len(result.stdout) <= 4 * 1024 * 1024 else None
    except (ValueError, store.Refused):
        value = None
    return result.returncode, value, result.returncode == 1 and UNAUTHENTICATED.fullmatch(result.stderr) is not None


def not_found(code, value):
    return code == 1 and type(value) is dict and value.get('message') == 'Not Found'


def account():
    code, user, unauthenticated = github_com_read('user')
    if code == 4 or unauthenticated:
        return 'identity_signed_out', None
    if code != 0 or type(user) is not dict:
        return 'identity_unreadable', None
    login = user.get('login')
    if user.get('type') != 'User' or not isinstance(login, str) or login.endswith('[bot]'):
        return 'identity_bot', None
    if store.LOGIN.fullmatch(login) is None:
        return 'identity_unreadable', None
    return None, login


def read_back(repository):
    failure, login = account()
    if failure is not None:
        return failure, None
    code, repo = github_com(f'repos/{repository}')
    if code != 0 or type(repo) is not dict:
        return ('identity_no_push' if not_found(code, repo) else 'identity_unreadable'), login
    permissions = repo.get('permissions')
    if type(permissions) is dict and permissions.get('push') is True:
        return 'identity_verified', login
    return 'identity_no_push', login


def check_identity(project, identity=None):
    if project is None:
        return 'identity_unselected'
    code, login = read_back(project['repository'])
    saved = identity or {}
    chosen = saved.get('acting_login') if saved.get('repository') == project['repository'] else None
    if code == 'identity_verified' and chosen is not None and login.lower() != chosen.lower():
        return 'identity_account_mismatch'
    return code


def runtime_pin(runtime):
    if runtime is None:
        return None
    try:
        identity = (Path(runtime) / 'openwiz-build.txt').read_text()
    except OSError:
        return None
    parts = identity.split('\n')
    if (len(parts) != 5 or parts[0] != 'openwiz.package.v1' or parts[4] != ''
            or not re.fullmatch(r'0\.[0-9]{1,10}\.[0-9]{1,10}', parts[1]) or not re.fullmatch('[0-9a-f]{40}', parts[2])):
        return None
    if not all((Path(runtime) / 'skills' / name / 'SKILL.md').is_file() for name in SKILLS):
        return None
    return f'{parts[1]} {parts[2]}'


def sections(text):
    found, name = {}, None
    for line in text.split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    return found


def table(lines):
    rows = [line.strip() for line in lines if line.strip().startswith('|')]
    if len(rows) < 2 or not re.fullmatch(r'\|(\s*:?-{3,}:?\s*\|)+', rows[1]):
        return []
    split = lambda row: [cell.strip() for cell in row.strip('|').split('|')]
    header = split(rows[0])
    return [dict(zip(header, split(row))) for row in rows[2:] if len(split(row)) == len(header)]


PLACEHOLDER = re.compile(r'<[A-Za-z][^<>\n]*>')
MODELS_HEADER = ['Role', 'Harness', 'Model', 'Effort', '`room-cli thread spawn` flags']
MODEL_ID = r'[A-Za-z0-9._-]+'
MODEL_FLAGS = re.compile(r'`--provider %s --model %s(?:/%s)* --reasoning-level %s`' % ((MODEL_ID,) * 4))


def models_usable(text, body):
    if sum(line.startswith('## ') and line[3:].strip() == 'Models' for line in text.split('\n')) != 1:
        return False
    rows = []
    for line in body:
        if line.startswith('|'):
            rows.append([cell.strip() for cell in line.strip()[1:-1].split('|')] if line.strip().endswith('|') else None)
        elif rows:
            break
    if len(rows) < 2 or rows[0] != MODELS_HEADER or rows[1] != ['---'] * 5 or None in rows:
        return False
    names = [row[0] if len(row) == 5 else None for row in rows[2:]]
    if names[:3] != ['Orchestrator', 'Builder', 'Reviewer'] or names[3:] not in (
            [], ['Small builder'], ['Fixer'], ['Small builder', 'Fixer']):
        return False
    for role, harness, model, effort, flags in rows[2:]:
        if harness == 'follows Builder':
            if role not in ('Small builder', 'Fixer') or model or effort or flags:
                return False
            continue
        if not (harness and model and effort) or not MODEL_FLAGS.fullmatch(flags):
            return False
    return True


def fleet_settings_usable(text):
    found = sections(text)
    reviewers = [name for name in found if name.startswith('Reviewer')]
    builders = [name for name in found if name.startswith('Builder')]
    needed = ['Test commands', 'CI checks', 'Standing merge rules']
    if 'Models' in found:
        if not models_usable(text, found['Models']):
            return False
        needed.insert(0, 'Models')
        builders = reviewers = []
    elif not reviewers:
        return False
    else:
        needed.insert(0, 'Builder')
    if not all(name in found for name in needed):
        return False
    for name in needed + builders + reviewers:
        body = found[name]
        if any(PLACEHOLDER.search(line) for line in body):
            return False
        if not any(line.startswith('Source: ') and len(line) > len('Source: ') for line in body):
            return False
    for name in builders + reviewers:
        values = {row.get('Setting'): row.get('Value', '') for row in table(found[name])}
        if not all(values.get(key) for key in ('Harness', 'Model', 'Effort')):
            return False
    if not any(row.get('Command', '').strip('`') for row in table(found['Test commands'])):
        return False
    if not any(row.get('Check', '').strip('`') for row in table(found['CI checks'])):
        return False
    merge = found['Standing merge rules']
    rows = [row for row in table(merge) if all(cell.strip() for cell in row.values())]
    waits = any(line.strip() == 'None yet: every merge waits for the user.' for line in merge)
    return bool(rows) or waits


def check_brain(brain, repository, read=gh):
    if brain is None or brain['code_repository'].lower() != repository.lower():
        return 'project_verified'
    home = brain['brain_repository']
    code, repo = read(f'repos/{home}')
    if code is None:
        return 'project_unreadable'
    if code != 0 or type(repo) is not dict or not str(repo.get('full_name', '')).lower() == home.lower() \
            or repo.get('private') is not True or repo.get('visibility') != 'private':
        return 'project_settings_missing' if code == 0 or not_found(code, repo) else 'project_unreadable'
    code, record = read(f"repos/{home}/contents/{brain['folder']}/settings.json")
    if code != 0 or type(record) is not dict or record.get('encoding') != 'base64':
        return 'project_settings_missing' if code == 0 or not_found(code, record) else 'project_unreadable'
    try:
        settings = json.loads(base64.b64decode(record.get('content', ''), validate=False),
                              object_pairs_hook=store.unique)
    except ValueError:
        return 'project_settings_missing'
    if (type(settings) is not dict or settings.get('brain_location') != brain['location']
            or str(settings.get('code_repository', '')).lower() != brain['code_repository'].lower()
            or str(settings.get('brain_repository', '')).lower() != home.lower()):
        return 'project_settings_missing'
    return 'project_verified'


def check_project(openwiz, project, runtime, brain=None):
    if project is None:
        return 'project_unprepared'
    if project['runtime'] is None or runtime_pin(runtime) != project['runtime']:
        return 'project_runtime_missing'
    repository = project['repository']
    local = 'host' in project
    read = github_com if local else gh
    if local:
        code, repo = read(f'repos/{repository}')
        if not_found(code, repo):
            return 'project_no_write'
        if code != 0 or type(repo) is not dict:
            return 'project_unreadable'
        permissions = repo.get('permissions')
        if type(permissions) is not dict or type(permissions.get('push')) is not bool:
            return 'project_unreadable'
        if not permissions['push']:
            return 'project_no_write'
    code, issue = read(f"repos/{repository}/issues/{project['service_issue']}")
    if code is None:
        return 'project_unreadable'
    if (code != 0 or type(issue) is not dict or issue.get('state') != 'open'
            or issue.get('number') != project['service_issue'] or 'pull_request' in issue):
        return 'project_issue_refused' if code == 0 or not_found(code, issue) else 'project_unreadable'
    code, settings = read(f'repos/{repository}/contents/docs/agents/fleet.md')
    if code != 0 or type(settings) is not dict or settings.get('encoding') != 'base64':
        return 'project_settings_missing' if code == 0 or not_found(code, settings) else 'project_unreadable'
    try:
        text = base64.b64decode(settings.get('content', ''), validate=False).decode()
    except ValueError:
        return 'project_settings_missing'
    if not fleet_settings_usable(text):
        return 'project_settings_missing'
    if local:
        return check_brain(brain, repository, read)
    if openwiz is None:
        return 'project_unreadable'
    code, thread = run([str(openwiz), 'show', project['answer_thread'], '--json'])
    if code == 3:
        return 'project_answer_refused'
    if code != 0 or type(thread) is not dict:
        return 'project_unreadable'
    group = (thread.get('data') or {}).get('session', {}).get('group', {})
    if group.get('kind') != 'project' or group.get('id') != project['project']:
        return 'project_answer_refused'
    return check_brain(brain, project['repository'])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def api_base(value):
    if value != API:
        parts = urllib.parse.urlsplit(value)
        store.require(parts.scheme == 'http' and parts.hostname == '127.0.0.1' and parts.port is not None
                      and parts.netloc == f'127.0.0.1:{parts.port}' and not parts.path
                      and not parts.query and not parts.fragment,
                      'only the GitHub API, or loopback HTTP for synthetic tests, is accepted')
    return value


def request(base, method, path, jwt, body=None):
    return linked_request(base, method, path, jwt, body)[:2]


def linked_request(base, method, path, jwt, body=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'OpenWiz-setup',
               'X-GitHub-Api-Version': '2022-11-28', 'Authorization': 'Bearer ' + jwt}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    call = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(call, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read(1024 * 1024 + 1)
            link = response.headers.get('Link')
    except urllib.error.HTTPError as error:
        return error.code, None, None
    except (OSError, ValueError):
        return None, None, None
    try:
        return status, json.loads(raw, object_pairs_hook=store.unique) if len(raw) <= 1024 * 1024 else None, link
    except ValueError:
        return status, None, link


NEXT = re.compile(r'<([^<>]*)>\s*;\s*rel="next"')
PAGES = 100


def read_installations(base, jwt):
    found, path = [], '/app/installations'
    origin = urllib.parse.urlsplit(base)[:2]
    for _ in range(PAGES):
        status, page, link = linked_request(base, 'GET', path, jwt)
        if status != 200 or type(page) is not list:
            return status, None
        found.extend(page)
        following = NEXT.search(link or '')
        if following is None:
            if re.search(r'\bnext\b', re.sub(r'<[^<>]*>', '', link or ''), re.IGNORECASE):
                return None, None
            return status, found
        parts = urllib.parse.urlsplit(following.group(1))
        if parts[:3] != (*origin, '/app/installations') or parts.fragment:
            return None, None
        path = f'{parts.path}?{parts.query}'
    return None, None


def private_file(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    info = os.fstat(fd)
    if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
            and info.st_nlink == 1 and 0 < info.st_size <= limit):
        os.close(fd)
        raise store.Refused('unsafe App file')
    return fd


def app_directory(state):
    fd = None
    try:
        fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in ('service', 'app'):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            store.require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, 'unsafe App directory')
        return fd
    except FileNotFoundError:
        if fd is not None:
            os.close(fd)
        return None


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def sign_jwt(directory, app_id):
    fd = private_file(directory, 'private-key.pem', 16384)
    try:
        now = int(time.time())
        message = b64(b'{"alg":"RS256","typ":"JWT"}') + b'.' + b64(json.dumps(
            {'iat': now - 60, 'exp': now + 540, 'iss': str(app_id)}, separators=(',', ':')).encode())
        store.require(os.path.isfile(OPENSSL), 'App signing failed')
        result = subprocess.run([OPENSSL, 'dgst', '-sha256', '-sign', f'/dev/fd/{fd}'], input=message,
                                capture_output=True, timeout=10, pass_fds=(fd,), env={})
        store.require(result.returncode == 0, 'App signing failed')
        return (message + b'.' + b64(result.stdout)).decode('ascii')
    finally:
        os.close(fd)


def check_app(state_path, project, recorded, base):
    try:
        directory = app_directory(state_path)
    except (store.Refused, OSError):
        return 'app_files_unusable', None
    if directory is None:
        return 'app_missing', None
    try:
        try:
            fd = private_file(directory, 'app.json', 1024)
        except FileNotFoundError:
            return 'app_missing', None
        with os.fdopen(fd, 'rb') as handle:
            config = json.loads(handle.read(1025), object_pairs_hook=store.unique)
        store.require(type(config) is dict and set(config) == {'app_id'} and store.positive(config['app_id']),
                      'invalid app.json')
        app_id = config['app_id']
        if project is None:
            return 'app_not_installed', {'app_id': app_id, 'installation_id': None}
        jwt = sign_jwt(directory, app_id)
    except (store.Refused, OSError, ValueError, subprocess.SubprocessError):
        return 'app_files_unusable', None
    finally:
        os.close(directory)
    status, installations = read_installations(base, jwt)
    if status == 401:
        return 'app_key_rejected', None
    if status != 200 or type(installations) is not list:
        return 'app_unreadable', None
    owner, name = project['repository'].split('/')
    mine = [i for i in installations if type(i) is dict and i.get('app_id') == app_id
            and isinstance((i.get('account') or {}).get('login'), str)
            and i['account']['login'].lower() == owner.lower()]
    if len(mine) == 1:
        status, found = request(base, 'GET', '/app', jwt)
        if status == 401:
            return 'app_key_rejected', None
        if status != 200 or type(found) is not dict or found.get('id') != app_id:
            return 'app_unreadable', None
        app_owner = (found.get('owner') or {}).get('login')
        if not isinstance(app_owner, str) or app_owner.lower() != owner.lower():
            mine = []
    if len(mine) != 1 or not store.positive(mine[0].get('id')):
        had = recorded is not None and recorded.get('installation_id') is not None
        return ('app_revoked' if had else 'app_not_installed'), {'app_id': app_id, 'installation_id': None}
    installation = mine[0]
    ids = {'app_id': app_id, 'installation_id': installation['id']}
    if installation.get('suspended_at') is not None:
        return 'app_suspended', ids
    if installation.get('repository_selection') != 'selected':
        return 'app_all_repositories', ids
    granted = installation.get('permissions')
    if granted != PROFILE:
        if type(granted) is dict and any(granted.get(k) != 'write' for k in WRITES):
            return 'app_read_only', ids
        return 'app_permissions_mismatch', ids
    status, token = request(base, 'POST', f"/app/installations/{installation['id']}/access_tokens", jwt,
                            {'repositories': [name], 'permissions': PROFILE})
    if status == 404:
        return 'app_revoked', {'app_id': app_id, 'installation_id': None}
    if status == 401:
        return 'app_key_rejected', ids
    if status == 422:
        return 'app_wrong_repository', ids
    if status != 201 or type(token) is not dict:
        return 'app_unreadable', ids
    code = proof_code(token, project['repository'])
    if isinstance(token.get('token'), str) and TOKEN.fullmatch(token['token']):
        try:
            request(base, 'DELETE', '/installation/token', token['token'])
        except Exception:
            pass
    del token
    return code, ids


def proof_code(token, repository):
    repositories = token.get('repositories')
    if token.get('permissions') != PROFILE:
        return 'app_read_only'
    if (token.get('repository_selection') != 'selected' or type(repositories) is not list
            or len(repositories) != 1 or type(repositories[0]) is not dict
            or str(repositories[0].get('full_name', '')).lower() != repository.lower()):
        return 'app_wrong_repository'
    if not usable_token(token, time.time()):
        return 'app_token_unusable'
    return 'app_verified'


TOKEN = re.compile(r'[A-Za-z0-9._~+/-]{1,16384}=*')


def usable_token(answer, now):
    token, expiry = answer.get('token'), answer.get('expires_at')
    if not isinstance(token, str) or TOKEN.fullmatch(token) is None or len(token) > 16384:
        return False
    if not isinstance(expiry, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', expiry) is None:
        return False
    try:
        at = datetime.strptime(expiry, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return False
    return 0 < at - now <= 3600 + 300


def default_openwiz(explicit):
    if explicit is not None:
        return Path(explicit).absolute() if Path(explicit).is_file() else None
    packaged = HERE.parent.parent / 'openwiz'
    return packaged if packaged.is_file() else None


def default_runtime(explicit):
    if explicit is not None:
        return Path(explicit)
    return HERE.parent if (HERE.parent / 'openwiz-build.txt').is_file() else None


DOWNLOAD_PAGE = 'https://www.cloudroom.dev/download'
INSTALLATIONS = 'https://github.com/settings/installations'


def next_steps(results, state, project, openwiz, identity=None):
    host = (project or {}).get('host', 'cloud')
    where = ['--state-dir', shlex.quote(str(state))]
    app_tool = HERE.parent / 'github-app/setup.py'
    if not app_tool.is_file():
        app_tool = HERE.parent.parent / 'github-app/setup.py'

    def tool(path, *words):
        return '`' + ' '.join(['python3', '-I', shlex.quote(str(path)), *words, *where]) + '`'

    def prepare(**changed):
        values = {'repository': 'OWNER/NAME', 'project': 'PRJ', 'operator': 'LOGIN', 'service_issue': 'N',
                  'answer_thread': 'THR', 'harness': 'HARNESS', 'model': 'MODEL', 'effort': 'EFFORT'}
        if project is not None:
            values.update({key: str(project[key]) for key in values})
        values.update(changed)
        if host != 'cloud':
            del values['project'], values['answer_thread']
            values['host'] = host
        return tool(HERE / 'setup.py', 'prepare', *[word for key, value in values.items() for word in (
            '--' + key.replace('_', '-'), shlex.quote(value))])

    repository = project['repository'] if project is not None else 'OWNER/NAME'
    again = tool(HERE / 'setup.py', 'check')
    cloudroom = HERE.parent / 'cloudroom/cloudroom.py'
    sign_in = f"Sign in to CloudRoom in its own window with {tool(cloudroom, 'sign-in')}, then run {again} again."
    preview = tool(cloudroom, 'install')
    app = tool(app_tool, '--repo', shlex.quote(repository))
    gh_login = "Sign in to GitHub as yourself with `gh auth login --web`"
    skip_app = tool(HERE / 'github_login.py', 'skip-app')
    choose_personal = f'or act as your personal GitHub login instead: preview {skip_app}, then confirm with --yes --operation and the id it prints'
    skipped = (project is not None and type(identity) is dict and identity.get('app_choice') == 'skip'
               and identity.get('repository') == project['repository'])
    models = '`' + (shlex.quote(str(openwiz)) if openwiz is not None else 'openwiz') + ' models --json`'
    steps = {
        'cloudroom_not_installed': f'Preview installing CloudRoom with {preview}, then confirm with --yes --operation and the id it prints.',
        'cloudroom_installing': f'A CloudRoom install is running: when it ends, run {again} again.',
        'cloudroom_installed': sign_in,
        'cloudroom_reused': sign_in,
        'cloudroom_install_failed': f'The install failed: run {preview} for its operation id, then retry it with --yes --operation and that id.',
        'cloudroom_install_uncertain': f'An earlier install may have finished: run {preview} for its operation id, then reconcile it with --yes --operation and that id.',
        'cloudroom_install_declined': f'You declined the install: to install CloudRoom after all, run {preview} for a new preview.',
        'cloudroom_checksum_mismatch': f"Nothing was installed: the download did not match CloudRoom's published checksum. Run {preview} later for a new preview, or install CloudRoom yourself from {DOWNLOAD_PAGE}.",
        'cloudroom_unsupported': f"CloudRoom publishes no installer OpenWiz can check for this computer (an Intel Mac, for example): install CloudRoom yourself from {DOWNLOAD_PAGE} if it offers one here ({tool(cloudroom, 'install', '--yes')} opens that page), open it once, sign in, then run {again} again.",
        'cloudroom_destination_blocked': f'Something else is at ~/Applications/Cloudroom.AppImage: move it away yourself, then run {preview} again.',
        'cloudroom_login_missing': sign_in,
        'cloudroom_login_unknown': sign_in,
        'cloudroom_login_verified': 'None: CloudRoom is installed and signed in.',
        'cloudroom_missing': f'This build has no CloudRoom tool or openwiz CLI: install CloudRoom yourself from {DOWNLOAD_PAGE}, open it once, sign in, then run {again} again.',
        'cloudroom_unreadable': f'CloudRoom could not be read: open the CloudRoom app, sign in, then run {again} again.',
        'cloudroom_partial': f'CloudRoom answered only in part: wait a minute, then run {again} again.',
        'cloudroom_reachable': 'None: CloudRoom is reachable.',
        'harness_unselected': f'Choose the harness, model and effort when you prepare the project: {prepare()}.',
        'harness_unreadable': f"CloudRoom's models could not be read: sign in to CloudRoom with {tool(cloudroom, 'sign-in')}, then run {again} again.",
        'harness_unavailable': f'CloudRoom does not offer that harness, model and effort now: list what it offers with {models}, then prepare again with one of them: {prepare(harness="HARNESS", model="MODEL", effort="EFFORT")}.',
        'harness_listed': 'None: CloudRoom offers the chosen harness, model and effort.',
        'identity_unselected': f"Prepare the project first: {prepare()}. Then this check reads your agents' GitHub login.",
        'identity_signed_out': f"Preview GitHub's browser sign-in with {tool(HERE / 'github_login.py', 'sign-in')}, then run it again with --yes.",
        'identity_unreadable': f'GitHub could not be read: check `gh auth status`, then run {again} again.',
        'identity_bot': f'{gh_login}, not as a bot or organisation, then run {again} again.',
        'identity_no_push': f'The signed-in GitHub account cannot push to {repository}: {gh_login[0].lower() + gh_login[1:]} with an account that can, or ask its owner for write access.',
        'identity_account_mismatch': f"gh is signed in as another account than the one you chose: switch back with `gh auth switch`, or record this account instead: preview {skip_app}, then confirm with --yes --operation and the id it prints.",
        'identity_verified': 'None: your agents can push with this GitHub login.',
        'project_unprepared': f'Choose the project for your first fleet: {prepare()}, then confirm with --yes --operation and the id it prints.',
        'project_runtime_missing': f'The project is pinned to another OpenWiz build: prepare it again from this build with {prepare()}.',
        'project_unreadable': f'GitHub or CloudRoom could not be read for the project: check `gh auth status` and the CloudRoom sign-in, then run {again} again.',
        'project_issue_refused': f'That issue is not an open issue in {repository}: open one for service records, then prepare again with its number: {prepare(service_issue="N")}.',
        'project_settings_missing': f"{repository} has no usable fleet settings (docs/agents/fleet.md, and the brain's settings after init): ask your agent to run the setup skill there, then run {again} again.",
        'project_answer_refused': f"That answer thread is not in the project's CloudRoom project: pick one that is, then prepare again: {prepare(answer_thread='THR')}.",
        'project_verified': 'None: the project is ready.',
        'app_missing': (f'None: you skipped the App for {repository}, so your personal GitHub login acts instead.' if skipped else
                        f"Connect OpenWiz's GitHub App with {app}, then confirm with --yes --operation and the id it prints; or skip the App with {skip_app}."),
        'app_files_unusable': f"The App's files in the state's service/app folder (app.json and private-key.pem) must be yours and private (mode 0600): fix them, then run {again} again; {choose_personal}.",
        'app_not_installed': f'Install the App on {repository}: run {app} and follow Install the App.',
        'app_key_rejected': f"GitHub rejected the App's key: generate a new private key in your App's settings at https://github.com/settings/apps, save it as service/app/private-key.pem in the state (yours, mode 0600), then run {again} again; {choose_personal}.",
        'app_unreadable': f"GitHub's App API could not be read: wait a minute, then run {again} again.",
        'app_revoked': f'The App is no longer installed for {repository}: install it again with {app}.',
        'app_suspended': f'The App is suspended: unsuspend it at {INSTALLATIONS}, then run {again} again.',
        'app_all_repositories': f'The App can reach every repository: at {INSTALLATIONS} choose Only select repositories and pick {repository}, then run {again} again.',
        'app_read_only': f"The App lacks write access: accept OpenWiz's requested permissions at {INSTALLATIONS}, then run {again} again.",
        'app_permissions_mismatch': f"The App's permissions differ from OpenWiz's profile: accept the requested permissions at {INSTALLATIONS}, then run {again} again.",
        'app_wrong_repository': f"The App can't reach {repository}: add it to the App's selected repositories at {INSTALLATIONS}, then run {again} again.",
        'app_token_unusable': f'GitHub returned an unusable App token: run {again} again; if it repeats, {choose_personal}.',
        'app_verified': 'None: the App can act on the project.',
    }
    if host != 'cloud':
        program = HARNESS_PROGRAMS.get(project['harness'], 'the chosen harness')
        local_models = models[:-1] + f' --host {host}`'
        choose = prepare(harness='HARNESS', model='MODEL', effort='EFFORT')
        steps.update({
            'cloudroom_not_needed': f'None: your agents run on {host}, not CloudRoom, so CloudRoom is not needed.',
            'harness_listed': 'None: the chosen harness is installed and the model and effort can be selected.',
            'harness_not_installed': f'Install {program} and put it on PATH, then run {again} again.',
            'harness_unreadable': f'The installed harness choices could not be read: try {local_models}, then run {again} again.',
            'harness_unavailable': f'That harness, model or effort cannot be selected: see {local_models}, then prepare again: {choose}.',
            'project_unreadable': f'GitHub could not be read for the project: check `gh auth status`, then run {again} again.',
            'project_no_write': f"The signed-in GitHub account cannot push to {repository}, or cannot see it: if OWNER/NAME is wrong, prepare again with the right one: {prepare(repository='OWNER/NAME')}; otherwise {gh_login[0].lower() + gh_login[1:]} with an account that can push, or ask its owner for write access.",
        })
    unknown = f'This build does not know that code: run {again} again; if it repeats, reinstall OpenWiz.'
    found = {component: steps.get(code, unknown) for component, code in results.items()}
    if shutil.which('gh') is None:
        for component in ('personal_github', 'project'):
            if '`gh ' in found[component] or 'github_login.py' in found[component]:
                found[component] = f'Install the GitHub CLI from https://cli.github.com first, then: {found[component]}'
    return found


def check(args):
    setup = store.Store(args.state_dir)
    base = api_base(args.api_base)
    generation = setup.start_check()
    before = setup.read()
    project, revision = before['project'], before['revision']
    openwiz = default_openwiz(args.openwiz)

    def guarded(check_one, failed):
        try:
            return check_one()
        except Exception:
            return failed
    host = (project or {}).get('host', 'cloud')
    results = {'cloudroom': 'cloudroom_not_needed' if host != 'cloud' else
               guarded(lambda: check_cloudroom(openwiz, setup.state), 'cloudroom_unreadable'),
               'harness': guarded(lambda: check_harness(openwiz, project), 'harness_unreadable'),
               'personal_github': guarded(lambda: check_identity(project, before.get('identity')),
                                          'identity_unreadable'),
               'project': guarded(lambda: check_project(openwiz, project, default_runtime(args.runtime),
                                                        before.get('brain')), 'project_unreadable')}
    results['github_app'], ids = guarded(lambda: check_app(setup.state, project, before['app'], base),
                                         ('app_unreadable', None))

    def change(value):
        if value['checks']['committed'] >= generation:
            raise store.Superseded()
        value['checks']['committed'] = generation
        bound = revision
        if value['revision'] == revision and ids is not None and value['app'] != ids:
            value['app'] = ids
            value['revision'] = bound = revision + 1
        now = int(time.time() * 1000)
        for component, code in results.items():
            value['observations'][component] = {'code': code, 'revision': bound, 'at': now}
    setup.update(change)
    report = {'schema': 'openwiz.setup-check.v1', 'results': results,
              'next': next_steps(results, setup.state, project, openwiz, before.get('identity'))}
    if host != 'cloud':
        report['host'] = host
    print(json.dumps(report, sort_keys=True))


def prepare(args):
    setup = store.Store(args.state_dir)
    pin = runtime_pin(default_runtime(args.runtime))
    project = {'repository': args.repository, 'project': args.project, 'operator': args.operator,
               'service_issue': args.service_issue, 'answer_thread': args.answer_thread,
               'harness': args.harness, 'model': args.model, 'effort': args.effort, 'runtime': pin}
    if args.host != 'cloud':
        project['host'] = args.host
    store.check_project(project)
    operator = f"Record {args.operator} as the loop operator and issue #{args.service_issue} for service records."
    if args.host == 'cloud':
        effects = [f"Select {args.repository} and CloudRoom project {args.project} for your first fleet.",
                   operator, f"Send answers to thread {args.answer_thread}."]
    else:
        effects = [f"Select {args.repository} for your first fleet, with agents on {args.host}.", operator]
    effects += [f"Run agents on {args.harness}, {args.model}, {args.effort} effort.",
                (f"Pin packaged runtime {pin.split()[0]} (source {pin.split()[1][:12]})." if pin
                 else "No packaged runtime found; project stays unverified."),
                "Save these settings in this host's owner-only OpenWiz state. Nothing is sent or created."]
    def current(value):
        return value['project'] == project
    if not args.yes:
        operation = setup.propose('prepare_project', project, effects, 'Proposed: confirm with --yes --operation.',
                                  current)
    else:
        store.require(args.operation is not None, '--yes needs --operation from the preview')

        def change(value):
            operation = setup.authorized(value, args.operation, 'prepare_project', project, current)
            if operation['phase'] == 'applied':
                return dict(operation)
            store.require(operation['phase'] == 'proposed', 'that operation is not awaiting confirmation')
            if value['project'] != project:
                value['project'] = project
                value['revision'] += 1
            operation['phase'] = 'applied'
            operation['reason'] = 'Saved. Run the setup check to verify each setting.'
            return dict(operation)
        operation = setup.update(change)
    print(json.dumps(operation, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'check'):
        command = commands.add_parser(name)
        command.add_argument('--state-dir', help='absolute OpenWiz state directory (default: the store\'s)')
        command.add_argument('--runtime', help='installed runtime directory (default: this packaged runtime)')
    p = commands.choices['prepare']
    p.add_argument('--repository', required=True)
    cloud_only = [p.add_argument('--project')]
    p.add_argument('--operator', required=True)
    p.add_argument('--service-issue', type=int, required=True)
    cloud_only.append(p.add_argument('--answer-thread'))
    p.add_argument('--host', default='cloud', help='where the agents run (default: cloud)')
    p.add_argument('--harness', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--effort', required=True)
    p.add_argument('--yes', action='store_true')
    p.add_argument('--operation')
    c = commands.choices['check']
    c.add_argument('--openwiz', help='installed openwiz CLI (default: this package\'s)')
    c.add_argument('--api-base', default=API, help='GitHub API; loopback HTTP for synthetic tests only')
    if sys.argv[1:2] == ['prepare']:
        host = argparse.ArgumentParser(add_help=False, exit_on_error=False)
        host.add_argument('--host', default='cloud')
        try:
            cloud = host.parse_known_args(sys.argv[2:])[0].host == 'cloud'
        except argparse.ArgumentError:
            cloud = False
        for action in cloud_only:
            action.required = cloud
    args = parser.parse_args()
    (prepare if args.command == 'prepare' else check)(args)


if __name__ == '__main__':
    try:
        main()
    except store.Superseded:
        print('openwiz-setup: superseded: a newer check saved its results first; this check saved nothing',
              file=sys.stderr)
        sys.exit(7)
    except store.Refused as refusal:
        print(f'openwiz-setup: refused: {refusal}', file=sys.stderr)
        sys.exit(5)
    except (OSError, ValueError, StopIteration):
        print('openwiz-setup: refused: setup state or a check could not be completed safely', file=sys.stderr)
        sys.exit(5)
