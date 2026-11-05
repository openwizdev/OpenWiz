#!/usr/bin/env python3
"""OpenWiz setup: prepare one project and check each connection independently (#1105).

  setup.py prepare --repository OWNER/NAME --project PRJ --operator NAME \\
      --service-issue N --answer-thread THR --harness H --model M --effort E
      Without --yes: records the proposed settings and prints their effects,
      operation id and fingerprint; nothing else is saved. With
      --yes --operation ID: saves exactly that preview's settings.
  setup.py check
      Reads CloudRoom through the installed openwiz CLI, the agents' own
      GitHub login through gh, and OpenWiz's App through GitHub's App API, and
      records one result code per component. Reads only: the App's
      installation token is minted to prove access, then discarded.

Results go to owner-only `<state>/setup/state.json` (store.py), which the
setup page reads. Output is JSON with fixed public codes: never a token, key,
provider body or URL with credentials. No personal-token fallback for the App.
Python 3.9+, standard library and /usr/bin/openssl only.
"""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402

HERE = Path(__file__).resolve().parent
# OpenWiz's established service App profile (crates/adapters/github/src/app.rs).
PROFILE = {'metadata': 'read', 'contents': 'write', 'issues': 'write',
           'pull_requests': 'write', 'checks': 'read', 'actions': 'read'}
WRITES = ('contents', 'issues', 'pull_requests')
SKILLS = ('setup', 'grill', 'plan-graph', 'launch-fleet')
API = 'https://api.github.com'
TIMEOUT = 30


def run(argv, limit=4 * 1024 * 1024):
    """One read. Returns (exit code, parsed JSON or None). Never echoes output."""
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if len(result.stdout) > limit:
        return result.returncode, None
    try:
        return result.returncode, json.loads(result.stdout, object_pairs_hook=store.unique)
    except ValueError:
        return result.returncode, None


# --- CloudRoom and the harness, through the installed openwiz CLI ---------

def check_cloudroom(openwiz, state=None):
    # #2201: with setup's CloudRoom tool beside it (runtime/cloudroom/), the
    # result is that tool's install and login code (contracts/
    # public-cloudroom-setup.v1.md): signed in only on CloudRoom's positive,
    # current account read. A runtime without the tool keeps the read below.
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
    # Review R5: only a complete live read with no gap is evidence; a partial
    # read (a supporting read failed or timed out) proves nothing.
    if (value.get('coverage') or {}).get('state') != 'complete' or value.get('gaps') != []:
        return 'cloudroom_partial'
    # Re-check R5: contracts/setup.v1.md: a successful inventory read alone
    # never verifies. No authorized read proves a current login yet, so a
    # complete read stays unknown (#1105, orchestrator question 6686776256).
    return 'cloudroom_reachable'


def check_harness(openwiz, project):
    if project is None:
        return 'harness_unselected'
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
                    # Review R5: the catalogue may be a saved copy and proves no
                    # current harness login, so it never verifies the harness.
                    return 'harness_listed'
    return 'harness_unavailable'


# --- The agents' own GitHub identity, through gh --------------------------

def gh(path):
    program = shutil.which('gh')
    if program is None:
        return None, None
    return run([program, 'api', path])


def check_identity(project):
    if project is None:
        return 'identity_unselected'
    code, user = gh('user')
    if code is None:
        return 'identity_signed_out'
    if code == 4:  # gh: authentication required
        return 'identity_signed_out'
    if code != 0 or type(user) is not dict:
        return 'identity_unreadable'
    login = user.get('login')
    if user.get('type') != 'User' or not isinstance(login, str) or login.endswith('[bot]'):
        return 'identity_bot'
    code, repo = gh(f"repos/{project['repository']}")
    if code != 0 or type(repo) is not dict:
        return 'identity_no_push' if code == 1 else 'identity_unreadable'
    permissions = repo.get('permissions')
    if type(permissions) is dict and permissions.get('push') is True:
        return 'identity_verified'
    return 'identity_no_push'


# --- Project settings: explicit, checked, never invented ------------------

def runtime_pin(runtime):
    """`<version> <source>` of the installed package's runtime, with its skills."""
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
    """`## Heading` -> its lines, up to the next `## ` heading."""
    found, name = {}, None
    for line in text.split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    return found


def table(lines):
    """The first Markdown table in LINES as rows of {header: cell}; [] if none."""
    rows = [line.strip() for line in lines if line.strip().startswith('|')]
    if len(rows) < 2 or not re.fullmatch(r'\|(\s*:?-{3,}:?\s*\|)+', rows[1]):
        return []
    split = lambda row: [cell.strip() for cell in row.strip('|').split('|')]
    header = split(rows[0])
    return [dict(zip(header, split(row))) for row in rows[2:] if len(split(row)) == len(header)]


PLACEHOLDER = re.compile(r'<[A-Za-z][^<>\n]*>')


def fleet_settings_usable(text):
    """Review R2: the setup skill's fleet settings, filled in. The builder and a
    reviewer name a harness, model and effort; at least one test command and one
    CI check; a merge rule; each with its Source line; no unfilled template
    placeholder. Empty headings or the bare template are not settings."""
    found = sections(text)
    reviewers = [name for name in found if name.startswith('Reviewer')]
    # Re-check R2: every builder table present counts, small-ticket builders included.
    builders = [name for name in found if name.startswith('Builder')]
    needed = ['Builder', 'Test commands', 'CI checks', 'Standing merge rules']
    if not reviewers or not all(name in found for name in needed):
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
    # Re-check R2: a rule is a filled table row, or the template's explicit
    # owner-waits line. Table headers and separators are scaffolding, not a rule.
    merge = found['Standing merge rules']
    rows = [row for row in table(merge) if all(cell.strip() for cell in row.values())]
    waits = any(line.strip() == 'None yet: every merge waits for the user.' for line in merge)
    return bool(rows) or waits


def check_project(openwiz, project, runtime):
    if project is None:
        return 'project_unprepared'
    if project['runtime'] is None or runtime_pin(runtime) != project['runtime']:
        return 'project_runtime_missing'
    code, issue = gh(f"repos/{project['repository']}/issues/{project['service_issue']}")
    if code is None:
        return 'project_unreadable'
    if (code != 0 or type(issue) is not dict or issue.get('state') != 'open'
            or issue.get('number') != project['service_issue'] or 'pull_request' in issue):
        return 'project_issue_refused' if code in (0, 1) else 'project_unreadable'
    code, settings = gh(f"repos/{project['repository']}/contents/docs/agents/fleet.md")
    if code != 0 or type(settings) is not dict or settings.get('encoding') != 'base64':
        return 'project_settings_missing' if code in (0, 1) else 'project_unreadable'
    try:
        text = base64.b64decode(settings.get('content', ''), validate=False).decode()
    except ValueError:
        return 'project_settings_missing'
    if not fleet_settings_usable(text):
        return 'project_settings_missing'
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
    return 'project_verified'


# --- OpenWiz's App, through GitHub's App API ------------------------------

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
    """(status, JSON or None). Never follows redirects or echoes a body."""
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
    except urllib.error.HTTPError as error:
        return error.code, None
    except (OSError, ValueError):
        return None, None
    try:
        return status, json.loads(raw, object_pairs_hook=store.unique) if len(raw) <= 1024 * 1024 else None
    except ValueError:
        return status, None


def private_file(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    info = os.fstat(fd)
    if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
            and info.st_nlink == 1 and 0 < info.st_size <= limit):
        os.close(fd)
        raise store.Refused('unsafe App file')
    return fd


def app_directory(state):
    """service/app, as tools/github-app/setup.py saves it, or None."""
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
    """RS256 JWT; OpenSSL reads the key through an inherited descriptor."""
    fd = private_file(directory, 'private-key.pem', 16384)
    try:
        now = int(time.time())
        message = b64(b'{"alg":"RS256","typ":"JWT"}') + b'.' + b64(json.dumps(
            {'iat': now - 60, 'exp': now + 540, 'iss': str(app_id)}, separators=(',', ':')).encode())
        result = subprocess.run(['/usr/bin/openssl' if Path('/usr/bin/openssl').exists() else 'openssl',
                                 'dgst', '-sha256', '-sign', f'/dev/fd/{fd}'], input=message,
                                capture_output=True, timeout=10, pass_fds=(fd,))
        store.require(result.returncode == 0, 'App signing failed')
        return (message + b'.' + b64(result.stdout)).decode('ascii')
    finally:
        os.close(fd)


def check_app(state_path, project, recorded, base):
    """(code, captured App ids or None). Never reads GH_TOKEN or gh's login."""
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
        # Security R2: an unsafe, missing or unusable key or ID, or failed signing.
        return 'app_files_unusable', None
    finally:
        os.close(directory)
    status, installations = request(base, 'GET', '/app/installations', jwt)
    if status == 401:
        return 'app_key_rejected', None
    if status != 200 or type(installations) is not list:
        return 'app_unreadable', None
    owner, name = project['repository'].split('/')
    mine = [i for i in installations if type(i) is dict and i.get('app_id') == app_id
            and isinstance((i.get('account') or {}).get('login'), str)
            and i['account']['login'].lower() == owner.lower()]
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
    # Proof of access: a token for exactly the selected repository and profile.
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
    repositories = token.get('repositories')
    if token.get('permissions') != PROFILE:
        return 'app_read_only', ids
    if (type(repositories) is not list or len(repositories) != 1 or type(repositories[0]) is not dict
            or str(repositories[0].get('full_name', '')).lower() != project['repository'].lower()):
        return 'app_wrong_repository', ids
    if not usable_token(token, time.time()):
        return 'app_token_unusable', ids
    del token  # held in memory only for this check, never written or printed
    return 'app_verified', ids


TOKEN = re.compile(r'[A-Za-z0-9._~+/-]{1,16384}=*')


def usable_token(answer, now):
    """Security R1: a bounded token and a valid expiry in the future, at most an
    hour (plus five minutes of clock drift) away, as the existing minters check."""
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


# --- Commands -------------------------------------------------------------

def default_openwiz(explicit):
    if explicit is not None:
        return Path(explicit) if Path(explicit).is_file() else None
    packaged = HERE.parent.parent / 'openwiz'  # <build>/runtime/setup/setup.py
    return packaged if packaged.is_file() else None


def default_runtime(explicit):
    if explicit is not None:
        return Path(explicit)
    return HERE.parent if (HERE.parent / 'openwiz-build.txt').is_file() else None


def check(args):
    setup = store.Store(args.state_dir)
    base = api_base(args.api_base)
    generation = setup.start_check()
    before = setup.read()
    project, revision = before['project'], before['revision']
    openwiz = default_openwiz(args.openwiz)

    def guarded(check_one, failed):
        # Security R2: a check that fails is still a result. Its fixed code is
        # saved, so it replaces this component's earlier positive evidence.
        try:
            return check_one()
        except Exception:
            return failed
    results = {'cloudroom': guarded(lambda: check_cloudroom(openwiz, setup.state), 'cloudroom_unreadable'),
               'harness': guarded(lambda: check_harness(openwiz, project), 'harness_unreadable'),
               'personal_github': guarded(lambda: check_identity(project), 'identity_unreadable'),
               'project': guarded(lambda: check_project(openwiz, project, default_runtime(args.runtime)),
                                  'project_unreadable')}
    # Local App files (key, ID, their directory or signing) that cannot be used
    # safely are a refusal of this component, never an abort.
    results['github_app'], ids = guarded(lambda: check_app(setup.state, project, before['app'], base),
                                         ('app_unreadable', None))

    def change(value):
        if value['checks']['committed'] >= generation:
            raise store.Superseded()
        value['checks']['committed'] = generation
        bound = revision
        if value['revision'] == revision and ids is not None and value['app'] != ids:
            # A captured or changed installation is a new selection.
            value['app'] = ids
            value['revision'] = bound = revision + 1
        now = int(time.time() * 1000)
        for component, code in results.items():
            value['observations'][component] = {'code': code, 'revision': bound, 'at': now}
    setup.update(change)
    print(json.dumps({'schema': 'openwiz.setup-check.v1', 'results': results}, sort_keys=True))


def prepare(args):
    setup = store.Store(args.state_dir)
    pin = runtime_pin(default_runtime(args.runtime))
    project = {'repository': args.repository, 'project': args.project, 'operator': args.operator,
               'service_issue': args.service_issue, 'answer_thread': args.answer_thread,
               'harness': args.harness, 'model': args.model, 'effort': args.effort, 'runtime': pin}
    store.check_project(project)
    effects = [f"Select {args.repository} and CloudRoom project {args.project} for your first fleet.",
               f"Record {args.operator} as the loop operator and issue #{args.service_issue} for service records.",
               f"Send answers to thread {args.answer_thread}.",
               f"Run agents on {args.harness}, {args.model}, {args.effort} effort.",
               (f"Pin packaged runtime {pin.split()[0]} (source {pin.split()[1][:12]})." if pin
                else "No packaged runtime found; project stays unverified."),
               "Save these settings in this host's owner-only OpenWiz state. Nothing is sent or created."]
    # Review R1: an applied preparation stands only while it is the saved selection.
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
                return dict(operation)  # A retry applies nothing twice.
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'check'):
        command = commands.add_parser(name)
        command.add_argument('--state-dir', help='absolute OpenWiz state directory (default: the store\'s)')
        command.add_argument('--runtime', help='installed runtime directory (default: this packaged runtime)')
    p = commands.choices['prepare']
    p.add_argument('--repository', required=True)
    p.add_argument('--project', required=True)
    p.add_argument('--operator', required=True)
    p.add_argument('--service-issue', type=int, required=True)
    p.add_argument('--answer-thread', required=True)
    p.add_argument('--harness', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--effort', required=True)
    p.add_argument('--yes', action='store_true')
    p.add_argument('--operation')
    c = commands.choices['check']
    c.add_argument('--openwiz', help='installed openwiz CLI (default: this package\'s)')
    c.add_argument('--api-base', default=API, help='GitHub API; loopback HTTP for synthetic tests only')
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
