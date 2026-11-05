#!/usr/bin/env python3
"""Prepare, evaluate and publish one checked public release candidate (#1843, RL2).

    release candidate notes VERSION --repo CLONE --entry ENTRY.json --out DIR
    release candidate prepare --state DIR --repo CLONE --body BODY.json --artifacts DIR
    release candidate decide --state DIR (--ship POINTER | --changelog POINTER)
    release candidate gate --state DIR --gate NAME --receipt FILE --inputs FILE
    release candidate live --state DIR --kit FILE --smoke-state DIR --record POINTER
    release candidate evaluate --state DIR --repo CLONE
    release candidate publish --state DIR --repo CLONE --artifacts DIR
    release candidate install --state DIR --receipt FILE
    release candidate status --state DIR

Every subcommand reads its private state directory, does what the current
evidence allows, records the outcome in `record.json` (an
`openwiz.release-candidate.v1` record) and prints one JSON object. It never
waits: missing evidence returns `blocked` with its reasons, and the next event
runs it again. Decisions are read from their actual private comments, never
from a caller's flag. Publication creates only the annotated tag and the
immutable release with its complete assets, from a commit already on public
`main`, and reads every byte back. An interrupted write is never repeated.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'install'))
from check import Refused, command, git_env, refuse_ranges, require, sha, unique  # noqa: E402
import entry  # noqa: E402
from install import manifest_at  # noqa: E402
from publish import git as remote_git, refs  # noqa: E402
from repository import remote_url, repository  # noqa: E402

PUBLIC = 'openwizdev/openwiz'
ANCHOR = '5d069b025c6eacb4123ca8241ba21345f1eae9dd'
PRIVATE = 'jparker2006/ClosedWiz'
OWNER = 'jparker2006'
SCHEMA = 'openwiz.release-candidate.v1'
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
PRODUCTS = ('cli', 'runtime', 'server', 'service', 'web')
METHODS = {'cli': {'embedded-record', 'native-query'}, 'server': {'embedded-record', 'native-query'},
           'service': {'embedded-record', 'native-query'}, 'web': {'web-build'}, 'runtime': {'tracked-tree'}}
RISKS = ('send', 'new', 'app_permissions', 'spending')
GATES = ('cutover', 'ci', 'privacy', 'claims', 'products', 'smoke') + RISKS
CLASSES = {'cutover': {'source-inspection'}, 'ci': {'ci'}, 'privacy': {'source-inspection', 'ci'},
           'claims': {'source-inspection', 'ci'}, 'products': {'ci'}}
# The public required checks each gate re-reads at the exact candidate commit.
CHECK_RUNS = {'ci': 'ci', 'privacy': 'privacy'}
RECEIPT = ('candidate_sha256 inputs_sha256 artifacts_sha256 kit_sha256 evidence_class status '
           'started_at finished_at evidence coverage gaps')
BODY = 'source build_id release_version included_versions changelog products artifacts kit risk'
POINTER = re.compile(r'https://github\.com/' + re.escape(PRIVATE) + r'/(?:issues|pull)/([1-9][0-9]*)'
                     r'#issuecomment-([1-9][0-9]*)')
DECISION = re.compile(r'Release decision: (ship|changelog) ([0-9a-f]{64})')
REVOKED = re.compile(r'Release decision revoked: ([1-9][0-9]*)')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
HEADING = re.compile(r'## (' + VERSION.pattern + r') · ([0-9]{4}-[0-9]{2}-[0-9]{2})')
TARGET_MET = 1800
# The PR's named assumptions D1-D6 (orchestrator ruling on #1843, 2026-11-13),
# each in one place so it is easy to change.
# D1: only GitHub Actions check runs of these trusted workflow files count.
WORKFLOWS = {'ci': '.github/workflows/ci.yml', 'privacy': '.github/workflows/privacy.yml'}
# D3: the open-development cut-over (O17) and its rehearsal (O16), private issues.
O16, O17 = 1284, 1285
# D5: an existing kit approval, restated once in the private-record form.
AUTHORITY = re.compile(r'Release kit authority: scope ([0-9a-f]{64})')
# D6: a changed path matching a category's pattern can never be classified `no`.
# Spending has no pattern yet: its `no` rests on every row saying `no`.
RISK_PATTERNS = {
    'send': ('crates/adapters/cloudroom/src/allowlist.rs', 'crates/adapters/cloudroom/src/messaging.rs',
             'crates/core/src/messaging/**', 'crates/cli/src/send.rs', 'crates/cli/src/attach.rs',
             'crates/cli/src/attachment.rs', 'crates/server/src/send.rs', 'crates/server/src/attachments.rs',
             'crates/core/src/attachment.rs'),
    'new': ('crates/adapters/cloudroom/src/allowlist.rs', 'crates/adapters/cloudroom/src/new_thread.rs',
            'crates/core/src/new_thread/**', 'crates/cli/src/new_thread.rs', 'crates/cli/src/attach.rs',
            'crates/cli/src/attachment.rs', 'crates/server/src/new_thread.rs', 'crates/server/src/attachments.rs'),
    'app_permissions': ('tools/github-app/**', 'crates/adapters/github/src/allowlist.rs',
                        'crates/adapters/github/src/app.rs'),
    'spending': ()}
# The gates the command establishes from its own reads (D1-D4), never from a receipt.
READ_GATES = ('cutover', 'ci', 'privacy', 'claims')


class Blocked(Exception):
    """Progress needs evidence or an event: reasons, no write attempted."""

    def __init__(self, reasons, status='blocked'):
        super().__init__(', '.join(reasons))
        self.reasons, self.status = list(reasons), status


def block(*reasons):
    raise Blocked(reasons)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def strict(data):
    def constant(name):
        raise ValueError('nonfinite number')
    return json.loads(data if isinstance(data, str) else data.decode('utf-8'),
                      object_pairs_hook=unique, parse_constant=constant)


def digest(value, length=64):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{%d}' % length, value) is not None


def keys(value, names, reason):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        block(reason)


def number(text):
    return tuple(map(int, text.split('.')))


def now():
    return int(time.time())


def env():
    value = git_env()
    value.update(GH_HOST='github.com', GH_PROMPT_DISABLED='1')
    return value


def gh(*args, cwd=None):
    output = command(['gh', *args], cwd or os.getcwd(), env(), timeout=300)
    return output


def gh_json(path, cwd=None):
    return strict(gh('api', path, cwd=cwd))


def local_git(repo, *args):
    return command(['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null', '-C', repo, *args],
                   repo, git_env(), timeout=300)


# ---------------------------------------------------------------- state

class State:
    def __init__(self, path):
        self.path = Path(path)

    def file(self, name):
        return self.path / name

    def exists(self, name='record.json'):
        return self.file(name).is_file()

    def read(self, name='record.json'):
        try:
            return strict(self.file(name).read_bytes())
        except (OSError, ValueError, Refused) as error:
            raise Refused(f'unreadable state {name}') from error

    def write(self, name, value):
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self.file(name)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = target.with_name('.' + target.name + '.tmp')
        with open(temporary, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
        # The intent must survive a crash before its write is attempted.
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def phase(record, name, started, finished):
    ship = record['timing']['original_ship_at']
    if ship is not None and finished >= ship:
        record['timing']['phases'].append({'name': name, 'started_at': started, 'finished_at': finished})


# ---------------------------------------------------------------- notes

def section_hash(text, version):
    """The contract's section bytes: heading to the next version heading, trailing LF removed."""
    starts = [m.start() for m in re.finditer(r'^## ', text, re.M)]
    for index, start in enumerate(starts):
        match = HEADING.match(text, start)
        if match and match[1] == version:
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            return sha(text[start:end].rstrip('\n').encode('utf-8'))
    raise Refused(f'no section for {version}')


def notes(args):
    """Proposed notes from changes/ at the clone's HEAD, J6 caps and recorded exclusions."""
    repo = Path(args.repo).resolve(strict=True)
    require(repository(repo) == PUBLIC, 'notes come from the public repository')
    data = strict(Path(args.entry).read_bytes())
    require(isinstance(data, dict) and set(data) == {'versions', 'excluded'}, 'invalid entry input')
    versions = entry.entries(data['versions'], args.version)
    excluded = entry.exclusions(data['excluded'])
    head = local_git(repo, 'rev-parse', 'HEAD').decode().strip()
    check = argparse.Namespace(args=argparse.Namespace(repo=repo))
    sections, sources = entry.sections(check, head, versions, excluded)
    text = '\n'.join(sections)
    published = latest_changelog(repo)
    changelog = entry.prepend(published, text, versions[-1]['version'])
    out = Path(args.out)
    require(not out.exists() and out.parent.is_dir(), 'output directory must be new')
    out.mkdir(mode=0o700)
    (out / 'notes.md').write_bytes(text.encode('utf-8'))
    (out / 'CHANGELOG.md').write_bytes(changelog)
    (out / 'sources.json').write_text(json.dumps({'commit': head, 'versions': sources,
                                                  'excluded': data['excluded']}, indent=1) + '\n')
    return {'status': 'proposed', 'commit': head, 'notes_sha256': sha(text.encode('utf-8')),
            'notes_bytes': len(text.encode('utf-8')),
            'sections': [{'version': v['version'], 'section_sha256': section_hash(text, v['version']),
                          'entries': len(sources[v['version']])} for v in versions]}


def latest_changelog(repo):
    """CHANGELOG.md at the newest published v* tag on the public remote, or empty."""
    tags = published_tags(repo)
    if not tags:
        return b''
    with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
        work = Path(scratch) / 'tags.git'
        remote_git(scratch, 'init', '-q', '--bare', work)
        newest = 'v' + '.'.join(map(str, max(tags)))
        remote_git(work, 'fetch', '-q', '--no-tags', remote_url(PUBLIC),
                   f'refs/tags/{newest}:refs/tags/{newest}')
        try:
            return remote_git(work, 'show', f'refs/tags/{newest}^{{commit}}:CHANGELOG.md')
        except Refused:
            return b''


def remote_tags(cwd, own=None):
    """Published v* tags on the public remote, {version: tag name}. `own` is this
    attempt's verified (tag, tag object, commit): only that exact tag is excluded."""
    output = remote_git(cwd, 'ls-remote', '--tags', remote_url(PUBLIC)).decode()
    rows = {}
    for line in output.splitlines():
        row = line.split('\t')
        require(len(row) == 2 and digest(row[0], 40), 'unexpected remote tag response')
        rows[row[1]] = row[0]
    tags = {}
    for ref, oid in rows.items():
        match = re.fullmatch(r'refs/tags/(v(' + VERSION.pattern + r'))', ref)
        if not match:
            continue
        if own and match[1] == own[0] and oid == own[1] and rows.get(ref + '^{}') == own[2]:
            continue
        tags[number(match[2])] = match[1]
    return tags


def published_tags(cwd, own=None):
    return set(remote_tags(cwd, own))


# ---------------------------------------------------------------- prepare

def check_source(repo, body, scratch):
    source = body['source']
    keys(source, 'repository commit tree anchor', 'invalid_source')
    if source['repository'] != PUBLIC or repository(repo) != PUBLIC:
        block('private_source')
    if source['anchor'] != ANCHOR or not digest(source['commit'], 40) or not digest(source['tree'], 40):
        block('unrelated_history')
    # The public remote's own main must contain the commit: a matching tree copied
    # from private history, or a commit only in this clone, never qualifies.
    work = Path(scratch) / 'main.git'
    remote_git(scratch, 'clone', '-q', '--bare', '--no-local', '--no-tags', '--single-branch',
               '--branch', 'main', remote_url(PUBLIC), work)
    remote_git(work, 'remote', 'set-url', 'origin', remote_url(PUBLIC))
    try:
        remote_git(work, 'cat-file', '-e', source['commit'] + '^{commit}')
        remote_git(work, 'merge-base', '--is-ancestor', source['commit'], 'HEAD')
    except Refused:
        block('not_on_public_main')
    try:
        remote_git(work, 'merge-base', '--is-ancestor', ANCHOR, source['commit'])
    except Refused:
        block('unrelated_history')
    if remote_git(work, 'rev-parse', source['commit'] + '^{tree}').decode().strip() != source['tree']:
        block('tree_mismatch')
    return work


def check_versions(body, cwd, own=None):
    versions = body['included_versions']
    if not isinstance(versions, list) or not versions:
        block('invalid_versions')
    seen = []
    for item in versions:
        keys(item, 'version section_sha256 promises', 'invalid_versions')
        if (not isinstance(item['version'], str) or not VERSION.fullmatch(item['version'])
                or not digest(item['section_sha256']) or not isinstance(item['promises'], list)
                or not item['promises'] or len(set(map(str, item['promises']))) != len(item['promises'])
                or not all(isinstance(p, str) and p for p in item['promises'])):
            block('invalid_versions')
        seen.append(number(item['version']))
    if body['release_version'] != versions[0]['version'] or any(a <= b for a, b in zip(seen, seen[1:])):
        block('version_order')
    published = published_tags(cwd, own)
    if published and min(seen) <= max(published):
        block('version_order')


def check_notes(body, work, own=None):
    notes_value = body['changelog']
    keys(notes_value, 'utf8 sha256 bytes', 'invalid_changelog')
    text = notes_value['utf8']
    if not isinstance(text, str) or not text.endswith('\n'):
        block('invalid_changelog')
    raw = text.encode('utf-8')
    if notes_value['bytes'] != len(raw) or notes_value['sha256'] != sha(raw):
        block('changelog_changed')
    if 'LIVE-PENDING' in text or 'PUBLICATION-DATE' in text:
        block('changelog_placeholder')
    try:
        refuse_ranges(text)
    except Refused:
        block('changelog_range_heading')
    headings = re.findall(r'^## .*$', text, re.M)
    wanted = [v['version'] for v in body['included_versions']]
    found = []
    for heading in headings:
        match = HEADING.fullmatch(heading)
        if not match:
            block('changelog_sections')
        datetime.date.fromisoformat(match[5])
        found.append(match[1])
    if found != wanted or not text.startswith('## '):
        block('changelog_sections')
    for item in body['included_versions']:
        if section_hash(text, item['version']) != item['section_sha256']:
            block('section_changed')
    # The commit's CHANGELOG.md is the published history plus exactly these notes.
    published = b''
    tags = remote_tags(work, own)
    if tags:
        tag = tags[max(tags)]
        remote_git(work, 'fetch', '-q', '--no-tags', remote_url(PUBLIC), f'refs/tags/{tag}:refs/tags/{tag}')
        try:
            published = remote_git(work, 'show', f'refs/tags/{tag}^{{commit}}:CHANGELOG.md')
        except Refused:
            published = b''
    try:
        expected = entry.prepend(published, text, wanted[-1])
        actual = remote_git(work, 'show', body['source']['commit'] + ':CHANGELOG.md')
    except Refused:
        block('changelog_history')
    if actual != expected:
        block('changelog_history')


def check_products(body):
    products = body['products']
    if not isinstance(products, list) or len(products) != len(TARGETS) * len(PRODUCTS):
        block('products_incomplete')
    order = []
    for row in products:
        keys(row, 'identity payload_sha256 verification build_receipt', 'invalid_products')
        identity = row['identity']
        keys(identity, 'schema product version source target', 'invalid_products')
        keys(row['build_receipt'], 'record sha256', 'invalid_products')
        if (identity['schema'] != 'openwiz.product.v1' or identity['product'] not in PRODUCTS
                or identity['target'] not in TARGETS or not digest(row['payload_sha256'])
                or row['verification'] not in METHODS[identity['product']]
                or not digest(row['build_receipt']['sha256'])):
            block('invalid_products')
        if identity['version'] != body['release_version'] or identity['source'] != body['source']['commit']:
            block('product_identity_mismatch')
        order.append((identity['target'], identity['product']))
    if order != [(t, p) for t in TARGETS for p in PRODUCTS]:
        block('products_incomplete')


def expected_artifacts(version):
    rows = {'SHA256SUMS': ('checksums', None)}
    for target in TARGETS:
        rows[f'openwiz-{version}-{target}.tar.gz'] = ('archive', target)
        rows[f'openwiz-{version}-{target}.manifest.json'] = ('manifest', target)
        rows[f'openwiz-{target}.manifest.json'] = ('manifest_alias', target)
        rows[f'openwiz-{target}.sha256'] = ('manifest_checksum', target)
    return rows


def check_artifacts(body, folder):
    """The complete asset inventory, its local bytes and the install contract's links."""
    version, rows = body['release_version'], body['artifacts']
    expected = expected_artifacts(version)
    if not isinstance(rows, list) or [r.get('name') if isinstance(r, dict) else None for r in rows] != sorted(expected):
        block('artifacts_incomplete')
    for row in rows:
        keys(row, 'name role target sha256 bytes', 'invalid_artifacts')
        if (row['role'], row['target']) != expected[row['name']] or not digest(row['sha256']) \
                or type(row['bytes']) is not int or row['bytes'] <= 0:
            block('invalid_artifacts')
    folder = Path(folder)
    try:
        present = sorted(p.name for p in folder.iterdir())
    except OSError:
        block('artifacts_unreadable')
    if present != sorted(expected):
        block('artifacts_incomplete')
    data = {}
    for row in rows:
        path = folder / row['name']
        if path.is_symlink() or not path.is_file():
            block('artifacts_unreadable')
        data[row['name']] = path.read_bytes()
        if len(data[row['name']]) != row['bytes'] or sha(data[row['name']]) != row['sha256']:
            block('artifact_changed')
    sums = {}
    for line in data['SHA256SUMS'].decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in sums:
            block('artifact_links')
        sums[match[2]] = match[1]
    covered = {n for n, (role, _) in expected.items() if role in ('archive', 'manifest')}
    if set(sums) != covered or any(sha(data[n]) != h for n, h in sums.items()):
        block('artifact_links')
    for target in TARGETS:
        manifest = f'openwiz-{version}-{target}.manifest.json'
        alias = f'openwiz-{target}.manifest.json'
        archive = f'openwiz-{version}-{target}.tar.gz'
        if data[alias] != data[manifest] or \
                data[f'openwiz-{target}.sha256'] != f'{sha(data[alias])}  {alias}\n'.encode():
            block('artifact_links')
        try:
            value, _, _ = manifest_at(folder / manifest, sha(data[manifest]), target)
        except Exception:  # noqa: BLE001 - the install contract's refusal, without its text
            block('artifact_manifest')
        if (value['version'] != version or value['source'] != body['source']['commit']
                or value['archive'] != archive or value['archive_sha256'] != sha(data[archive])
                or value['archive_bytes'] != len(data[archive])):
            block('artifact_manifest')
        stage(folder / manifest, folder / archive, sha(data[manifest]), target)
    return data


def stage(manifest, archive, checksum, target, keep=None):
    """Stage one archive exactly as a user's install does: the installer's own
    format, member, mode, size and payload checks, never activated. Returns the
    staged files when `keep` names a directory for them."""
    import install as installer
    scratch = Path(tempfile.mkdtemp(prefix='release-stage-', dir=keep))
    try:
        result = installer.install(manifest, archive, checksum, scratch / 'root', target, stage_only=True)
    except Exception:  # noqa: BLE001 - the installer's refusal, without its text
        shutil.rmtree(scratch, ignore_errors=True)
        block('artifact_archive')
    if keep is None:
        shutil.rmtree(scratch, ignore_errors=True)
        return None
    return Path(result['build'])


def check_body(body):
    keys(body, BODY, 'invalid_body')
    if not digest(body['build_id']):
        block('invalid_body')
    kit = body['kit']
    keys(kit, 'sha256 scope_sha256 authority', 'invalid_kit')
    if not digest(kit['sha256']) or not digest(kit['scope_sha256']) or not isinstance(kit['authority'], str) \
            or not POINTER.fullmatch(kit['authority']):
        block('invalid_kit')
    risk = body['risk']
    keys(risk, ' '.join(RISKS), 'risk_missing')
    for name in RISKS:
        keys(risk[name], 'required reason', 'risk_missing')
        if risk[name]['required'] not in ('yes', 'no', 'unknown') or not isinstance(risk[name]['reason'], str) \
                or not risk[name]['reason'].strip():
            block('risk_missing')


def prepare(args):
    state = State(args.state)
    repo = Path(args.repo).resolve(strict=True)
    try:
        body = strict(Path(args.body).read_bytes())
    except (OSError, ValueError, Refused):
        block('invalid_body')
    check_body(body)
    inputs = {}
    for name in ('entry', 'classification'):
        try:
            inputs[name] = strict(Path(getattr(args, name)).read_bytes())
        except (OSError, ValueError, Refused):
            block(f'{name}_unreadable' if name == 'entry' else 'risk_classification_missing')
    with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
        work = check_source(repo, body, scratch)
        check_versions(body, scratch)
        check_notes(body, work)
        problems = risk_reasons(body, inputs['classification'], work)
        if problems:
            block(*problems)
    check_products(body)
    check_artifacts(body, args.artifacts)
    candidate_sha = canonical(body)
    stamp = now()
    timing = {'original_ship_at': None, 'preparation_started_at': stamp, 'phases': [], 'finished_at': None}
    decisions = {'ship': None, 'changelog': None}
    if state.exists():
        old = state.read()
        if old['candidate_sha256'] == candidate_sha:
            # The same candidate: refresh only the validated supporting inputs that
            # changed, and drop only the claims receipt built from the entry.
            changed = [n for n in ('entry', 'classification')
                       if not state.exists(f'{n}.json') or canonical(state.read(f'{n}.json')) != canonical(inputs[n])]
            if changed and state.exists('attempt.json'):
                block('publication_started')
            if 'entry' in changed:
                old['gates']['claims'] = None
                state.write('record.json', old)
            for name in changed:
                state.write(f'{name}.json', inputs[name])
            return {'status': 'prepared', 'candidate_sha256': candidate_sha, 'unchanged': not changed}
        if state.exists('attempt.json'):
            block('publication_started')
        if old['candidate']['release_version'] != body['release_version']:
            block('different_release')
        # The same release instruction keeps its original ship time and decision
        # records; evaluation decides which still bind the new candidate.
        timing, decisions = old['timing'], old['decisions']
        for name in os.listdir(state.path):
            if name in ('inputs', 'live.json'):
                target = state.file(name)
                shutil.rmtree(target) if target.is_dir() else target.unlink()
    record = {'schema': SCHEMA, 'candidate_sha256': candidate_sha, 'candidate': body, 'decisions': decisions,
              'gates': {g: None for g in GATES}, 'publication': None, 'install': None, 'timing': timing}
    state.write('entry.json', inputs['entry'])
    state.write('classification.json', inputs['classification'])
    state.write('record.json', record)
    return {'status': 'prepared', 'candidate_sha256': candidate_sha}


# ---------------------------------------------------------------- decisions and evidence

def comment(pointer):
    """An existing private comment, read through gh: body, author and times."""
    match = POINTER.fullmatch(pointer) if isinstance(pointer, str) else None
    if not match:
        block('pointer_invalid')
    try:
        data = gh_json(f'repos/{PRIVATE}/issues/comments/{match[2]}')
    except (Refused, ValueError):
        block('unreadable')
    if (not isinstance(data, dict) or not isinstance(data.get('body'), str)
            or not isinstance(data.get('user'), dict) or not isinstance(data.get('created_at'), str)
            or data.get('id') != int(match[2])
            or not str(data.get('issue_url', '')).endswith(f'/repos/{PRIVATE}/issues/{match[1]}')):
        block('unreadable')
    return match[1], match[2], data


def epoch(text):
    try:
        return int(datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ')
                   .replace(tzinfo=datetime.timezone.utc).timestamp())
    except (TypeError, ValueError):
        block('unreadable')


def revoked(issue, comment_id, decided_at):
    """A later operative revocation line for this record; an earlier one does not
    revoke it, and one whose order against the record cannot be read refuses."""
    try:
        rows = strict(gh('api', '--paginate', '--slurp', f'repos/{PRIVATE}/issues/{issue}/comments?per_page=100'))
    except (Refused, ValueError):
        block('unreadable')
    rows = [c for page in rows for c in page] if rows and isinstance(rows[0], list) else rows
    later = False
    for c in rows:
        if (isinstance(c, dict) and isinstance(c.get('body'), str)
                and any((m := REVOKED.fullmatch(line)) and m[1] == comment_id for line in c['body'].splitlines())):
            at = epoch(c.get('created_at'))
            if at == decided_at:
                block('unreadable')
            later = later or at > decided_at
    return later


def resolve_decision(kind, pointer):
    """Jake's recorded decision: the orchestrator's unedited private record form."""
    issue, comment_id, data = comment(pointer)
    body = data['body']
    lines = body.splitlines()
    if (data['user'].get('login') != OWNER or not lines
            or not re.match(r'Private record: Jake, [0-9]{4}-[0-9]{2}-[0-9]{2}', lines[0])
            or data.get('updated_at') != data['created_at']):
        block(f'{kind}_not_a_decision')
    bindings = [m[2] for m in (DECISION.fullmatch(line) for line in lines) if m and m[1] == kind]
    if len(bindings) != 1:
        block(f'{kind}_not_a_decision')
    if revoked(issue, comment_id, epoch(data['created_at'])):
        block(f'{kind}_revoked')
    return {'pointer': pointer, 'record_sha256': sha(body.encode('utf-8')),
            'decided_at': epoch(data['created_at']), 'binding_sha256': bindings[0]}


def decide(args):
    state = State(args.state)
    record = state.read()
    kind, pointer = ('ship', args.ship) if args.ship else ('changelog', args.changelog)
    decision = resolve_decision(kind, pointer)
    target = record['candidate_sha256'] if kind == 'ship' else record['candidate']['changelog']['sha256']
    if decision['binding_sha256'] != target:
        block(f'{kind}_binding_mismatch')
    record['decisions'][kind] = decision
    timing = record['timing']
    if kind == 'ship' and timing['original_ship_at'] is None:
        timing['original_ship_at'] = decision['decided_at']
    ship, notes_decision = record['decisions']['ship'], record['decisions']['changelog']
    if ship and notes_decision and notes_decision['decided_at'] > timing['original_ship_at'] \
            and not any(p['name'] == 'changelog_wait' for p in timing['phases']):
        phase(record, 'changelog_wait', timing['original_ship_at'], notes_decision['decided_at'])
    state.write('record.json', record)
    return {'status': 'recorded', 'decision': kind, 'decided_at': decision['decided_at']}


def evidence_bytes(record_pointer):
    _, _, data = comment(record_pointer)
    return data['body'].encode('utf-8')


def check_runs(commit):
    try:
        pages = strict(gh('api', '--paginate', '--slurp', f'repos/{PUBLIC}/commits/{commit}/check-runs?per_page=100'))
    except (Refused, ValueError):
        block('unreadable')
    if not isinstance(pages, list) or not pages:
        block('unreadable')
    runs = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get('check_runs'), list):
            block('unreadable')
        runs += page['check_runs']
    return runs


def gate_reasons(record, gate, receipt, inputs, ctx=None):
    """Why a non-live gate receipt does not pass for this exact candidate, or []."""
    body = record['candidate']
    if not isinstance(receipt, dict) or set(receipt) != set(RECEIPT.split()):
        return ['invalid']
    if receipt['candidate_sha256'] != record['candidate_sha256'] \
            or receipt['artifacts_sha256'] != canonical(body['artifacts']):
        return ['stale']
    if receipt['kit_sha256'] is not None or receipt['coverage'] != [] or not isinstance(receipt['gaps'], list):
        return ['invalid']
    if not isinstance(receipt['evidence_class'], str) or not isinstance(receipt['status'], str):
        return ['invalid']
    if receipt['evidence_class'] not in CLASSES[gate]:
        return ['not_' + '_or_'.join(sorted(CLASSES[gate])).replace('-', '_')]
    if receipt['status'] != 'pass':
        return [{'fail': 'failed'}.get(receipt['status'], 'uncertain' if receipt['status'] == 'uncertain'
                                       else 'incomplete')]
    if type(receipt['started_at']) is not int or type(receipt['finished_at']) is not int \
            or receipt['finished_at'] < receipt['started_at']:
        return ['incomplete']
    if not isinstance(inputs, dict) or canonical(inputs) != receipt['inputs_sha256']:
        return ['inputs_mismatch']
    if inputs.get('gate') != gate or inputs.get('candidate_sha256') != record['candidate_sha256'] \
            or inputs.get('artifacts_sha256') != receipt['artifacts_sha256']:
        return ['stale']
    if gate == 'claims' and inputs.get('notes_sha256') != body['changelog']['sha256']:
        return ['stale']
    if gate == 'products' and inputs.get('products') != body['products']:
        return ['stale']
    if gate == 'cutover' and inputs.get('repository') != PUBLIC:
        return ['stale']
    evidence = receipt['evidence']
    if not isinstance(evidence, dict) or set(evidence) != {'record', 'sha256'}:
        return ['invalid']
    try:
        if sha(evidence_bytes(evidence['record'])) != evidence['sha256']:
            return ['evidence_mismatch']
    except Blocked:
        return ['unreadable']
    try:
        if gate in CHECK_RUNS:
            runs = [r for r in check_runs(body['source']['commit'])
                    if isinstance(r, dict) and r.get('name') == CHECK_RUNS[gate]]
            if not runs:
                return ['missing']
            if any(r.get('head_sha') != body['source']['commit'] or r.get('status') != 'completed'
                   or r.get('conclusion') != 'success' for r in runs):
                return ['failed']
            if inputs.get('check_runs') != [{'name': r['name'], 'id': r.get('id')} for r in runs]:
                return ['stale']
        if gate == 'products':
            return verify_products(record, inputs, ctx)
        if gate == 'cutover':
            meta = gh_json(f'repos/{PUBLIC}')
            if not isinstance(meta, dict) or meta.get('full_name') != PUBLIC \
                    or meta.get('visibility') != 'public' or meta.get('archived') is not False:
                return ['unverified']
    except (Blocked, Refused, ValueError):
        return ['unreadable']
    return []


def verify_products(record, inputs, ctx):
    """RL4's own verifiers over each archive as the installer stages it: the
    compiled programs against their native query receipt, the web export
    against its build receipt and the runtime against the public commit's
    tracked tree. The results must be exactly the candidate's product rows."""
    import product_identity as rl4
    body = record['candidate']
    version, source = body['release_version'], body['source']['commit']
    if not ctx or ctx.get('work') is None or ctx.get('artifacts') is None:
        return ['unverified']
    receipts = inputs.get('receipts')
    if not isinstance(receipts, list) or [r.get('target') if isinstance(r, dict) else None
                                          for r in receipts] != list(TARGETS):
        return ['unverified']
    folder, got = Path(ctx['artifacts']), []
    try:
        with tempfile.TemporaryDirectory(prefix='release-products-') as scratch:
            for row in receipts:
                keys(row, 'target program web selection', 'invalid')
                target = row['target']
                manifest = folder / f'openwiz-{version}-{target}.manifest.json'
                checksum = sha(manifest.read_bytes())
                build = stage(manifest, folder / f'openwiz-{version}-{target}.tar.gz', checksum, target, keep=scratch)
                saved = Path(scratch) / ('receipts-' + target)
                saved.mkdir()
                for kind in ('program', 'web'):
                    keys(row[kind], 'name utf8', 'invalid')
                    if not isinstance(row[kind]['name'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',
                                                                                 row[kind]['name']):
                        block('invalid')
                    (saved / row[kind]['name']).write_bytes(row[kind]['utf8'].encode('utf-8'))
                rows = rl4.verify_programs({p: (build / n).read_bytes() for p, n in rl4.PROGRAMS.items()},
                                           saved / row['program']['name'], version, source, target)
                value, _, _ = manifest_at(manifest, checksum, target)
                assets = [a for a in value['assets'] if a['path'] not in rl4.STAMPS]
                # #2539: the receipt and selection checks read the stamp-free rows;
                # each payload hash reads the complete stamped inventory.
                final = {kind: rl4.payload([a for a in value['assets'] if a['path'].startswith(kind + '/')])
                         for kind in ('web', 'runtime')}
                rows.append({**rl4.verify_web([a for a in assets if a['path'].startswith('web/')],
                                              saved / row['web']['name'], version, source, target),
                             'payload_sha256': final['web']})
                runtime = [a for a in assets if a['path'].startswith('runtime/')]
                selection = row['selection']
                if (not isinstance(selection, list) or selection != sorted(selection)
                        or any(not isinstance(pair, list) or len(pair) != 2 for pair in selection)
                        or sorted(name for _, name in selection) != sorted(a['path'] for a in runtime)):
                    return ['unverified']
                rl4.verify_runtime(ctx['work'], source, {repo: (build / name).read_bytes() for repo, name in selection})
                rows.append({'identity': rl4.expected('runtime', version, source, target),
                             'payload_sha256': final['runtime'], 'verification': 'tracked-tree',
                             'build_receipt': {'record': 'tracked-tree', 'sha256': sha(rl4.canonical(
                                 {'source': source, 'selection': selection}))}})
                got += sorted(rows, key=lambda r: r['identity']['product'])
    except Exception:  # noqa: BLE001 - RL4's or the installer's refusal, without its text
        return ['unverified']
    return [] if got == body['products'] else ['mismatch']


def pages(path, key=None):
    """Every page of a paginated GitHub read, flattened."""
    data = strict(gh('api', '--paginate', '--slurp', path))
    require(isinstance(data, list), 'unexpected pages')
    rows = []
    for page in data:
        page = page.get(key) if key and isinstance(page, dict) else page
        require(isinstance(page, list), 'unexpected page')
        rows += page
    return rows


def required_check(gate, commit):
    """D1: the latest run of the trusted workflow at this exact commit, by GitHub
    Actions, succeeded, and its own check run of this name succeeded."""
    try:
        runs = [r for r in check_runs(commit) if isinstance(r, dict) and r.get('name') == gate]
        workflows = pages(f'repos/{PUBLIC}/actions/runs?head_sha={commit}&per_page=100', 'workflow_runs')
    except (Blocked, Refused, ValueError):
        return ['unreadable'], None
    if not runs:
        return ['missing'], None
    trusted = [w for w in workflows if isinstance(w, dict) and w.get('path') == WORKFLOWS[gate]
               and w.get('head_sha') == commit]
    if not trusted or any(not isinstance(r.get('app'), dict) or r['app'].get('slug') != 'github-actions'
                          for r in runs):
        return ['untrusted'], None
    latest = max(trusted, key=lambda w: (str(w.get('created_at')), w.get('run_attempt') or 0))
    own = [r for r in runs if isinstance(r.get('check_suite'), dict)
           and r['check_suite'].get('id') == latest.get('check_suite_id')]
    if (latest.get('status') != 'completed' or latest.get('conclusion') != 'success' or not own
            or any(r.get('head_sha') != commit or r.get('status') != 'completed' or r.get('conclusion') != 'success'
                   for r in own)):
        return ['failed'], None
    return [], {'workflow_run': {k: latest.get(k) for k in ('id', 'run_attempt', 'path', 'head_sha', 'conclusion',
                                                             'check_suite_id')},
                'check_runs': sorted(r.get('id') for r in own)}


def scan_artifacts(body, folder, literals):
    """D2: the existing O3 checker over every staged runtime and web file."""
    import subprocess
    if literals is None or not Path(literals).is_file():
        return ['literals_missing']
    version = body['release_version']
    with tempfile.TemporaryDirectory(prefix='release-privacy-') as scratch:
        tree = Path(scratch) / 'scan'
        tree.mkdir()
        for target in TARGETS:
            manifest = Path(folder) / f'openwiz-{version}-{target}.manifest.json'
            try:
                build = stage(manifest, Path(folder) / f'openwiz-{version}-{target}.tar.gz',
                              sha(manifest.read_bytes()), target, keep=scratch)
            except (Blocked, OSError):
                return ['unverified']
            for part in ('runtime', 'web'):
                shutil.copytree(build / part, tree / target / part)
        try:
            done = subprocess.run([sys.executable, '-I', str(HERE.parent / 'privacy-check/check.py'), '--tree', str(tree),
                                   '--literals', str(literals), '--require-literals'],
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            return ['unreadable']
    if done.returncode == 0 and done.stdout == b'literals: used\n' and not done.stderr:
        return []
    return ['finding']


def ref_matches(pattern, ref, default):
    """One ruleset ref pattern against a full ref; an unevaluable form refuses."""
    if pattern == '~ALL':
        return True
    if pattern == '~DEFAULT_BRANCH':
        return ref == 'refs/heads/' + default
    require(isinstance(pattern, str) and re.fullmatch(r'[A-Za-z0-9._/*-]+', pattern) is not None
            and '**' not in pattern, 'unevaluable ref pattern')
    # A `*` stays within one path segment, as in GitHub's ref patterns.
    return re.fullmatch('[^/]*'.join(map(re.escape, pattern.split('*'))), ref) is not None


def ruleset_applies(detail, default):
    """D3: an active branch ruleset whose include matches the default branch and
    whose exclude does not. A ref matching any exclude is outside the ruleset."""
    if detail.get('enforcement') != 'active' or detail.get('target') != 'branch':
        return False
    conditions = detail.get('conditions')
    require(isinstance(conditions, dict) and set(conditions) == {'ref_name'}, 'unevaluable ruleset conditions')
    names = conditions['ref_name']
    require(isinstance(names, dict) and set(names) <= {'include', 'exclude'}
            and all(isinstance(names.get(k, []), list) for k in ('include', 'exclude')), 'unevaluable ruleset conditions')
    ref = 'refs/heads/' + default
    return (any(ref_matches(p, ref, default) for p in names.get('include', []))
            and not any(ref_matches(p, ref, default) for p in names.get('exclude', [])))


def cutover_reasons():
    """D3: O17 completed, no hold on O16/O17, the public repository and its default-branch protection."""
    try:
        o16, o17 = gh_json(f'repos/{PRIVATE}/issues/{O16}'), gh_json(f'repos/{PRIVATE}/issues/{O17}')

        def held(issue):
            return any(isinstance(label, dict) and label.get('name') == 'held' for label in issue.get('labels', []))
        meta = gh_json(f'repos/{PUBLIC}')
        immutable = gh_json(f'repos/{PUBLIC}/immutable-releases')
        sets = [gh_json(f"repos/{PUBLIC}/rulesets/{r['id']}") for r in pages(f'repos/{PUBLIC}/rulesets?per_page=100')]
        default = meta.get('default_branch')
        require(isinstance(default, str) and re.fullmatch(r'[A-Za-z0-9._/-]+', default) is not None,
                'unreadable default branch')
        main = [d for d in sets if ruleset_applies(d, default)]
        contexts = {c.get('context') for d in main for rule in d.get('rules') or [] if rule.get('type') ==
                    'required_status_checks' for c in (rule.get('parameters') or {}).get('required_status_checks') or []}
        ok = (o17.get('state') == 'closed' and o17.get('state_reason') == 'completed' and not held(o17)
              and not held(o16) and meta.get('full_name') == PUBLIC and meta.get('visibility') == 'public'
              and meta.get('archived') is False and immutable.get('enabled') is True and main
              and {'ci', 'privacy'} <= contexts and all(d.get('bypass_actors') == [] for d in main))
    except (Blocked, Refused, ValueError, AttributeError, KeyError, TypeError):
        return ['unverified'], None
    if not ok:
        return ['unverified'], None
    return [], {'o17': O17, 'rulesets': sorted(d.get('id') for d in main)}


def claims_reasons(body, entry_input, work):
    """D4: the approved notes are exactly what changes/ at the candidate commit generates."""
    try:
        require(isinstance(entry_input, dict) and set(entry_input) == {'versions', 'excluded'}, 'invalid entry input')
        versions = entry.entries(entry_input['versions'], body['release_version'])
        check = argparse.Namespace(args=argparse.Namespace(repo=work))
        made = '\n'.join(entry.sections(check, body['source']['commit'], versions,
                                        entry.exclusions(entry_input['excluded']))[0])
    except (Refused, ValueError, KeyError, TypeError):
        return ['unverified'], None
    if made != body['changelog']['utf8']:
        return ['mismatch'], None
    return [], {'notes_sha256': body['changelog']['sha256'], 'entry_sha256': canonical(entry_input)}


def kit_reasons(body):
    """D5: the kit's existing authority names this exact scope and still applies."""
    try:
        issue, comment_id, data = comment(body['kit']['authority'])
    except Blocked:
        return ['kit_authority_unreadable']
    lines = data['body'].splitlines()
    if (data['user'].get('login') != OWNER or not lines
            or not re.match(r'Private record: Jake, [0-9]{4}-[0-9]{2}-[0-9]{2}', lines[0])
            or data.get('updated_at') != data['created_at']):
        return ['kit_authority_not_a_grant']
    if [m[1] for m in map(AUTHORITY.fullmatch, lines) if m] != [body['kit']['scope_sha256']]:
        return ['kit_authority_scope']
    try:
        if revoked(issue, comment_id, epoch(data['created_at'])):
            return ['kit_authority_revoked']
    except Blocked:
        return ['kit_authority_unreadable']
    return []


def matches(path, pattern):
    return path.startswith(pattern[:-2]) if pattern.endswith('/**') else path == pattern


def risk_reasons(body, rows, work, own=None):
    """D6: a per-path classification of the complete change since the last publication."""
    try:
        tags = remote_tags(work, own)
        base = ANCHOR
        if tags:
            tag = tags[max(tags)]
            remote_git(work, 'fetch', '-q', '--no-tags', remote_url(PUBLIC), f'refs/tags/{tag}:refs/tags/{tag}')
            base = remote_git(work, 'rev-parse', f'refs/tags/{tag}^{{commit}}').decode().strip()
        changed = remote_git(work, 'diff', '--name-only', '-z', '--no-renames', base,
                             body['source']['commit']).decode('utf-8').split('\0')
    except (Refused, UnicodeError):
        return ['risk_classification_unreadable']
    changed = {p for p in changed if p}
    if (not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != {'path', *RISKS}
                                          or not isinstance(r['path'], str)
                                          or any(r[c] not in ('yes', 'no') for c in RISKS) for r in rows)
            or len({r['path'] for r in rows}) != len(rows)):
        return ['risk_classification_invalid']
    if {r['path'] for r in rows} != changed:
        return ['risk_classification_incomplete']
    reasons = []
    for category in RISKS:
        wrong = any(r[category] == 'no' and any(matches(r['path'], p) for p in RISK_PATTERNS[category]) for r in rows)
        if wrong or (body['risk'][category]['required'] == 'no' and any(r[category] == 'yes' for r in rows)):
            reasons.append(f'{category}_classification_unsupported')
    return reasons


def read_receipt(record, gate, inputs, started):
    """The command's own receipt for a gate it established from its reads."""
    body = record['candidate']
    full = dict(inputs, gate=gate, candidate_sha256=record['candidate_sha256'],
                artifacts_sha256=canonical(body['artifacts']))
    return {'candidate_sha256': record['candidate_sha256'], 'inputs_sha256': canonical(full),
            'artifacts_sha256': full['artifacts_sha256'], 'kit_sha256': None,
            'evidence_class': 'ci' if gate in WORKFLOWS else 'source-inspection', 'status': 'pass',
            'started_at': started, 'finished_at': now(),
            'evidence': {'record': 'readback:' + gate, 'sha256': canonical(full)}, 'coverage': [], 'gaps': []}


def live_doc(state):
    return state.read('live.json') if state.exists('live.json') else None


def smoke_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('release_live_smoke_receipt',
                                                  HERE.parent / 'live-smoke' / 'receipt.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preserved(record_pointer):
    """The live run's preserved private record, for RL3's accept()."""
    _, _, data = comment(record_pointer)
    return {'body': data['body'], 'created_at': epoch(data['created_at'])}


def live(args):
    """Produce RL3's smoke and risk receipts from the approved kit and run state."""
    state = State(args.state)
    record = state.read()
    receipts = smoke_module()
    try:
        doc = receipts.produce(Path(args.kit), Path(args.smoke_state), record, args.record)
    except (receipts.Refusal, receipts.smoke.Refusal) as error:
        block(f'smoke_{error}')
    state.write('live.json', {'doc': doc, 'kit': str(Path(args.kit).resolve()),
                              'state': str(Path(args.smoke_state).resolve())})
    for gate in ('smoke',) + RISKS:
        record['gates'][gate] = doc['gates'][gate]
    state.write('record.json', record)
    return {'status': 'recorded', 'gates': {g: (doc['gates'][g] or {}).get('status') for g in ('smoke',) + RISKS}}


def live_reasons(record, saved):
    reasons = []
    risk = record['candidate']['risk']
    for name in RISKS:
        if risk[name]['required'] == 'unknown':
            reasons.append(f'{name}_unknown')
    if saved is None:
        reasons.append('smoke_missing')
        reasons += [f'{n}_live_missing' for n in RISKS if risk[n]['required'] == 'yes']
        return reasons
    receipts = smoke_module()
    for gate in ('smoke',) + RISKS:
        if gate != 'smoke' and risk[gate]['required'] != 'yes':
            continue
        try:
            receipts.accept(gate, saved['doc'], record, Path(saved['kit']), Path(saved['state']), preserved)
        except receipts.Refusal as error:
            reason = str(error)
            reasons.append(f'{gate}_live_missing' if gate != 'smoke' and reason in ('missing', 'risk_missing')
                           else f'{gate}_{reason}')
        except (Blocked, receipts.smoke.Refusal, OSError, ValueError, KeyError, TypeError):
            reasons.append(f'{gate}_unreadable')
    return reasons


def gate(args):
    state = State(args.state)
    record = state.read()
    if args.gate in READ_GATES:
        block(f'{args.gate}_read_by_the_command')
    if args.gate not in CLASSES:
        block('unknown_gate')
    try:
        receipt = strict(Path(args.receipt).read_bytes())
        inputs = strict(Path(args.inputs).read_bytes())
    except (OSError, ValueError, Refused):
        block(f'{args.gate}_unreadable')
    with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
        ctx = {'work': None, 'artifacts': Path(args.artifacts) if args.artifacts else None}
        if args.repo:
            try:
                ctx['work'] = check_source(Path(args.repo).resolve(strict=True), record['candidate'], scratch)
            except Blocked:
                pass
        reasons = gate_reasons(record, args.gate, receipt, inputs, ctx)
    if reasons:
        block(*(f'{args.gate}_{r}' for r in reasons))
    record['gates'][args.gate] = receipt
    state.write(f'inputs/{args.gate}.json', inputs)
    state.write('record.json', record)
    return {'status': 'recorded', 'gate': args.gate}


def reasons_for(record, state, repo, own=None, artifacts=None, literals=None, made=None):
    """Every reason this candidate cannot publish now; [] means ready. `made`
    receives the command's own receipts for the gates it read."""
    reasons, started = [], now()
    made = {} if made is None else made
    if canonical(record['candidate']) != record['candidate_sha256']:
        return ['candidate_changed']
    body = record['candidate']
    with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
        work = None
        try:
            work = check_source(repo, body, scratch)
            check_versions(body, scratch, own)
            check_notes(body, work, own)
        except Blocked as error:
            reasons += error.reasons
        for kind, target in (('ship', record['candidate_sha256']), ('changelog', body['changelog']['sha256'])):
            saved = record['decisions'][kind]
            if saved is None:
                reasons.append(f'{kind}_missing')
                continue
            try:
                current = resolve_decision(kind, saved['pointer'])
            except Blocked as error:
                reasons += [r if r.startswith(kind) else f'{kind}_{r}' for r in error.reasons]
                continue
            if current != saved:
                reasons.append(f'{kind}_changed')
            elif current['binding_sha256'] != target:
                reasons.append('ship_stale' if kind == 'ship' else 'changelog_changed')
        ctx = {'work': work, 'artifacts': artifacts}
        commit = body['source']['commit']
        for name in READ_GATES:
            found, inputs = ['unverified'], None
            if name == 'cutover':
                found, inputs = cutover_reasons()
            elif name in WORKFLOWS:
                found, inputs = required_check(name, commit)
                if not found and name == 'privacy':
                    found = scan_artifacts(body, artifacts, literals) if artifacts else ['unverified']
            elif work is not None:
                found, inputs = claims_reasons(body, state.read('entry.json') if state.exists('entry.json') else None,
                                               work)
            reasons += [f'{name}_{r}' for r in found]
            made[name] = None if found else read_receipt(record, name, inputs, started)
        reasons += kit_reasons(body)
        if work is not None:
            rows = state.read('classification.json') if state.exists('classification.json') else None
            reasons += risk_reasons(body, rows, work, own) if rows is not None else ['risk_classification_missing']
        for name in ('products',):
            receipt = record['gates'][name]
            if receipt is None:
                reasons.append(f'{name}_missing')
                continue
            inputs = state.read(f'inputs/{name}.json') if state.exists(f'inputs/{name}.json') else None
            reasons += [f'{name}_{r}' for r in gate_reasons(record, name, receipt, inputs, ctx)]
    reasons += live_reasons(record, live_doc(state))
    return reasons


def evaluate(args):
    repo = Path(args.repo).resolve(strict=True)
    state = State(args.state)
    record = state.read()
    started = now()
    made = {}
    reasons = reasons_for(record, state, repo, artifacts=Path(args.artifacts), literals=args.literals, made=made)
    record['gates'].update(made)
    phase(record, 'checks', started, now())
    state.write('record.json', record)
    if reasons:
        raise Blocked(reasons)
    return {'status': 'ready', 'candidate_sha256': record['candidate_sha256']}


# ---------------------------------------------------------------- publication

def tagger(work, commit):
    name = remote_git(work, 'show', '-s', '--format=%an', commit).decode().strip()
    email = remote_git(work, 'show', '-s', '--format=%ae', commit).decode().strip()
    if not re.fullmatch(r'[A-Za-z .-]+', name) or \
            not re.fullmatch(r'[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com', email):
        block('tagger_identity')
    return name, email


def release_readback(record, scratch, tag_object):
    """The remote release, tag and every downloaded asset against the candidate and the intended tag object."""
    body = record['candidate']
    tag = 'v' + body['release_version']
    commit = body['source']['commit']
    data = gh_json(f'repos/{PUBLIC}/releases/tags/{tag}')
    notes_text = body['changelog']['utf8']
    problems = []
    if not isinstance(data, dict) or data.get('tag_name') != tag or data.get('name') != 'OpenWiz ' + body['release_version']:
        problems.append('release_identity')
        data = data if isinstance(data, dict) else {}
    remote_body = data.get('body')
    # The exact approved UTF-8 bytes: no newline or whitespace normalization (contract `changelog`).
    if not isinstance(remote_body, str) or \
            remote_body.encode('utf-8', 'surrogatepass') != notes_text.encode('utf-8'):
        problems.append('notes')
    if data.get('draft') is not False or data.get('prerelease') is not True:
        problems.append('prerelease')
    if data.get('immutable') is not True:
        problems.append('immutable')
    assets = data.get('assets') if isinstance(data.get('assets'), list) else []
    wanted = {a['name']: a for a in body['artifacts']}
    if sorted(a.get('name') for a in assets if isinstance(a, dict)) != sorted(wanted) \
            or any(a.get('size') != wanted[a['name']]['bytes'] for a in assets if a.get('name') in wanted):
        problems.append('assets')
    folder = Path(tempfile.mkdtemp(prefix='downloaded-', dir=scratch))  # fresh for each read-back
    gh('release', 'download', tag, '--repo', PUBLIC, '--dir', str(folder), cwd=scratch)
    got = {p.name: p.read_bytes() for p in folder.iterdir()}
    if sorted(got) != sorted(wanted) or any(sha(got[n]) != wanted[n]['sha256'] for n in got if n in wanted):
        problems.append('asset_bytes')
    found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if found.get(f'refs/tags/{tag}^{{}}') != commit or found.get(f'refs/tags/{tag}') != tag_object:
        problems.append('tag')
    return problems, found.get(f'refs/tags/{tag}'), data


def settle(record, attempt, scratch):
    """Resume after an interrupted write: only a matching read-back settles it."""
    body = record['candidate']
    tag = 'v' + body['release_version']
    if attempt['steps'].get('tag') == 'started':
        found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
        if found.get(f'refs/tags/{tag}^{{}}') != body['source']['commit']:
            raise Blocked(['uncertain_tag'], status='uncertain')
        if found.get(f'refs/tags/{tag}') == body['source']['commit']:
            raise Blocked(['uncertain_tag'], status='uncertain')  # not the annotated tag
        if not attempt.get('tag_object') or found.get(f'refs/tags/{tag}') != attempt['tag_object']:
            raise Blocked(['uncertain_tag'], status='uncertain')  # not the annotated tag this attempt made
        attempt['steps']['tag'] = 'done'
    if attempt['steps'].get('release') == 'started':
        try:
            problems, _, _ = release_readback(record, scratch, attempt['tag_object'])
        except (Refused, ValueError):
            raise Blocked(['uncertain_release'], status='uncertain') from None
        if problems:
            raise Blocked(['uncertain_release'], status='uncertain')
        attempt['steps']['release'] = 'done'


def ready(body, artifacts, scratch, tag, own=None):
    """The pre-write checks shared by the tag and release steps."""
    data = check_artifacts(body, artifacts)
    try:
        enabled = gh_json(f'repos/{PUBLIC}/immutable-releases')
    except (Refused, ValueError):
        enabled = None
    if not isinstance(enabled, dict) or enabled.get('enabled') is not True:
        block('immutable_releases_off')
    found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if found and (own is None or found != {f'refs/tags/{tag}': own[1], f'refs/tags/{tag}^{{}}': own[2]}):
        block('tag_exists')
    return data


def publish(args):
    repo = Path(args.repo).resolve(strict=True)
    state = State(args.state)
    record = state.read()
    if record['publication'] and record['publication']['status'] == 'complete':
        return {'status': 'published', 'tag': record['publication']['tag']}
    body = record['candidate']
    tag = 'v' + body['release_version']
    started = now()
    with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
        attempt = state.read('attempt.json') if state.exists('attempt.json') else None
        if record['publication']:
            # Every write is done and was recorded incomplete: re-read only, never write.
            if attempt is None or attempt['steps'] != {'tag': 'done', 'release': 'done'}:
                raise Blocked(['publication_incomplete'], status='incomplete')
        else:
            if attempt is None:
                reasons = reasons_for(record, state, repo, artifacts=Path(args.artifacts), literals=args.literals)
                if reasons:
                    raise Blocked(reasons)
                ready(body, args.artifacts, scratch, tag)
                work = Path(scratch) / 'main.git'
                remote_git(scratch, 'clone', '-q', '--bare', '--no-local', '--no-tags', '--single-branch',
                           '--branch', 'main', remote_url(PUBLIC), work)
                name, email = tagger(work, body['source']['commit'])
                # The annotated tag object is made locally first, so the attempt persists it as
                # the intended effect; only that object settles the push.
                remote_git(work, '-c', 'user.name=' + name, '-c', 'user.email=' + email, '-c', 'tag.gpgSign=false',
                           'tag', '-a', tag, body['source']['commit'], '-m', 'OpenWiz ' + body['release_version'])
                intended = remote_git(work, 'rev-parse', '--verify', f'refs/tags/{tag}').decode().strip()
                attempt = {'attempt_id': f"{record['candidate_sha256'][:16]}-{started}",
                           'candidate_sha256': record['candidate_sha256'], 'tag': tag, 'steps': {},
                           'started_at': started, 'tag_object': intended}
                # Persist each intended effect before it; an interruption stays uncertain.
                attempt['steps']['tag'] = 'started'
                state.write('attempt.json', attempt)
                remote_git(work, 'push', '--no-follow-tags', '--porcelain', remote_url(PUBLIC),
                           f'refs/tags/{tag}:refs/tags/{tag}')
            # A started step is settled only by its own matching read-back.
            settle(record, attempt, scratch)
            state.write('attempt.json', attempt)
            if attempt['steps'].get('tag') == 'done' and 'release' not in attempt['steps']:
                # The release write is unattempted: re-check every decision, gate and
                # setting now, excluding only this attempt's own verified tag.
                own = (tag, attempt['tag_object'], body['source']['commit'])
                reasons = reasons_for(record, state, repo, own, Path(args.artifacts), args.literals)
                if reasons:
                    raise Blocked(reasons)
                data = ready(body, args.artifacts, scratch, tag, own)
                notes_file = Path(scratch) / 'notes.md'
                notes_file.write_bytes(body['changelog']['utf8'].encode('utf-8'))
                files = []
                for row in body['artifacts']:
                    path = Path(scratch) / 'assets' / row['name']
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(data[row['name']])
                    files.append(str(path))
                attempt['steps']['release'] = 'started'
                state.write('attempt.json', attempt)
                gh('release', 'create', tag, '--repo', PUBLIC, '--verify-tag', '--prerelease',
                   '--title', 'OpenWiz ' + body['release_version'], '--notes-file', str(notes_file), *files,
                   cwd=scratch)
                attempt['steps']['release'] = 'done'
                state.write('attempt.json', attempt)
        try:
            problems, tag_object, remote = release_readback(record, scratch, attempt.get('tag_object'))
        except (Refused, ValueError, OSError):
            problems, tag_object, remote = ['unreadable'], None, None
        verified = now()
        evidence = json.dumps(remote, sort_keys=True).encode('utf-8')
        state.write('evidence/readback.json', {'release': remote, 'problems': problems})
        record['publication'] = {
            'status': 'incomplete' if problems else 'complete', 'attempt_id': attempt['attempt_id'], 'tag': tag,
            'tag_object': tag_object or attempt.get('tag_object'), 'commit': body['source']['commit'],
            'notes_sha256': body['changelog']['sha256'], 'artifacts_sha256': canonical(body['artifacts']),
            # A property never read stays unverified: false, never true by absence.
            'immutable': not {'unreadable', 'immutable'} & set(problems),
            'prerelease': not {'unreadable', 'prerelease'} & set(problems),
            'verified_at': verified, 'evidence': {'record': 'readback:' + tag, 'sha256': sha(evidence)}}
        # Publishing time runs from the persisted attempt start, across failed or interrupted
        # invocations and the waits between them; a re-read continues from the last publish phase.
        prior = [p['finished_at'] for p in record['timing']['phases'] if p['name'] == 'publish']
        phase(record, 'publish', max([attempt['started_at']] + prior), verified)
        state.write('record.json', record)
        if problems:
            raise Blocked([f'readback_{p}' for p in problems], status='incomplete')
    return {'status': 'published', 'tag': tag, 'tag_object': record['publication']['tag_object']}


def install(args):
    state = State(args.state)
    record = state.read()
    publication = record['publication']
    if not publication or publication['status'] != 'complete':
        block('publication_incomplete')
    try:
        receipt = strict(Path(args.receipt).read_bytes())
    except (OSError, ValueError, Refused):
        block('install_unreadable')
    keys(receipt, 'route version source target manifest_sha256 archive_sha256 verified_at evidence', 'install_invalid')
    body = record['candidate']
    names = {(a['role'], a['target']): a['sha256'] for a in body['artifacts']}
    if (receipt['route'] not in ('install', 'update') or receipt['version'] != body['release_version']
            or receipt['source'] != body['source']['commit'] or receipt['target'] not in TARGETS
            or receipt['manifest_sha256'] != names.get(('manifest', receipt['target']))
            or receipt['archive_sha256'] != names.get(('archive', receipt['target']))):
        block('install_mismatch')
    if type(receipt['verified_at']) is not int or receipt['verified_at'] < publication['verified_at']:
        block('install_mismatch')
    keys(receipt['evidence'], 'record sha256', 'install_invalid')
    try:
        if sha(evidence_bytes(receipt['evidence']['record'])) != receipt['evidence']['sha256']:
            block('install_evidence_mismatch')
    except Blocked as error:
        if error.reasons != ['install_evidence_mismatch']:
            block('install_unreadable')
        raise
    record['install'] = receipt
    record['timing']['finished_at'] = receipt['verified_at']
    phase(record, 'install', publication['verified_at'], receipt['verified_at'])
    state.write('record.json', record)
    return report(record)


def report(record):
    timing = record['timing']
    ship, finished = timing['original_ship_at'], timing['finished_at']
    elapsed = finished - ship if ship is not None and finished is not None else None
    return {'status': 'complete' if elapsed is not None else 'incomplete',
            'candidate_sha256': record['candidate_sha256'], 'original_ship_at': ship,
            'preparation_started_at': timing['preparation_started_at'], 'finished_at': finished,
            'elapsed_seconds': elapsed, 'target_met': None if elapsed is None else elapsed < TARGET_MET,
            'phases': timing['phases'],
            'publication': (record['publication'] or {}).get('status')}


def status(args):
    return report(State(args.state).read())


def main(argv=None):
    parser = argparse.ArgumentParser(prog='release candidate', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    made = sub.add_parser('notes')
    made.add_argument('version')
    for name in ('repo', 'entry', 'out'):
        made.add_argument('--' + name, required=True)
    made = sub.add_parser('prepare')
    for name in ('state', 'repo', 'body', 'artifacts', 'entry', 'classification'):
        made.add_argument('--' + name, required=True)
    made = sub.add_parser('decide')
    made.add_argument('--state', required=True)
    which = made.add_mutually_exclusive_group(required=True)
    which.add_argument('--ship')
    which.add_argument('--changelog')
    made = sub.add_parser('gate')
    for name in ('state', 'gate', 'receipt', 'inputs'):
        made.add_argument('--' + name, required=True)
    made.add_argument('--repo')
    made.add_argument('--artifacts')
    made = sub.add_parser('live')
    for name in ('state', 'kit', 'smoke-state', 'record'):
        made.add_argument('--' + name, required=True)
    for name in ('evaluate', 'publish'):
        made = sub.add_parser(name)
        made.add_argument('--state', required=True)
        made.add_argument('--repo', required=True)
        made.add_argument('--artifacts', required=True)
        made.add_argument('--literals', required=True, help='the private O3 named-terms file (D2)')
    made = sub.add_parser('install')
    made.add_argument('--state', required=True)
    made.add_argument('--receipt', required=True)
    made = sub.add_parser('status')
    made.add_argument('--state', required=True)
    args = parser.parse_args(argv)
    actions = {'notes': notes, 'prepare': prepare, 'decide': decide, 'gate': gate, 'live': live,
               'evaluate': evaluate, 'publish': publish, 'install': install, 'status': status}
    try:
        result = actions[args.action](args)
        code = 0
    except Blocked as error:
        result, code = {'status': error.status, 'reasons': error.reasons}, 1
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        # A failed write leaves its intent recorded: inspect, never retry blindly.
        result, code = {'status': 'refused', 'reasons': [type(error).__name__ if not isinstance(error, Refused)
                                                         else str(error)]}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
