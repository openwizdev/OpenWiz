#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error

sys.dont_write_bytecode = True

DESCRIPTION = """Prepare, evaluate and publish one checked public release candidate (#1843, RL2).

    release candidate notes VERSION --repo CLONE --entry ENTRY.json --out DIR
    release candidate prepare --state DIR --repo CLONE --body BODY.json --artifacts DIR
    release candidate decide --state DIR (--ship POINTER | --changelog POINTER)
    release candidate gate --state DIR --gate NAME --receipt FILE --inputs FILE
    release candidate live --state DIR --kit FILE --smoke-state DIR --record POINTER
    release candidate evaluate --state DIR --repo CLONE
    release candidate publish --state DIR --repo CLONE --artifacts DIR
    release candidate install --state DIR --target TARGET
    release candidate status --state DIR

Every subcommand reads its private state directory, does what the current
evidence allows, records the outcome in `record.json` (an
`openwiz.release-candidate.v1` record) and prints one JSON object. It never
waits: missing evidence returns `blocked` with its reasons, and the next event
runs it again. Decisions are read from their actual private comments, never
from a caller's flag. Publication creates only the annotated tag and the
immutable release with its complete assets, from a commit already on public
`main` or on the protected public `release-<version>` branch, and reads every
byte back. An interrupted write is never repeated.
"""
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'install'))
from check import Refused, command, git_env, refuse_ranges, require, sha, unique
import entry
from install import manifest_at
from publish import git as remote_git, refs
from repository import remote_url, repository

PUBLIC = 'openwizdev/OpenWiz'
ANCHOR = '5d069b025c6eacb4123ca8241ba21345f1eae9dd'
PRIVATE = 'jparker2006/ClosedWiz'
OWNER = 'jparker2006'
SCHEMA = 'openwiz.release-candidate.v1'
ATTEMPT = re.compile(r'[1-9][0-9]*\.json')
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
PRODUCTS = ('cli', 'runtime')
METHODS = {'cli': {'embedded-record', 'native-query'}, 'runtime': {'tracked-tree'}}
RISKS = ('send', 'new', 'app_permissions', 'spending')
GATES = ('cutover', 'ci', 'privacy', 'claims', 'products', 'smoke') + RISKS
CLASSES = {'cutover': {'source-inspection'}, 'ci': {'ci'}, 'privacy': {'source-inspection', 'ci'},
           'claims': {'source-inspection', 'ci'}, 'products': {'ci'}}
CHECK_RUNS = {'ci': 'ci', 'privacy': 'privacy'}
RECEIPT = ('candidate_sha256 inputs_sha256 artifacts_sha256 kit_sha256 evidence_class status '
           'started_at finished_at evidence coverage gaps')
BODY = 'source build_id release_version included_versions changelog products artifacts kit risk'
POINTER = re.compile(r'https://github\.com/' + re.escape(PRIVATE) + r'/(?:issues|pull)/([1-9][0-9]*)'
                     r'#issuecomment-([1-9][0-9]*)')
DECISION = re.compile(r'Release decision: (ship|changelog) ([0-9a-f]{64})')
REVOKED = re.compile(r'Release decision revoked: ([1-9][0-9]*)')
WAIVABLE = {('app_permissions', '0.0.12')}
PUBLIC_NAMES = {'0.1.0': 'OpenWiz 0.01'}
WAIVER = re.compile(r'Release waiver: ([a-z_]+) v(0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))')
WAIVER_REVOKED = re.compile(r'Release waiver revoked: ([1-9][0-9]*)')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
HEADING = re.compile(r'## (' + VERSION.pattern + r') · ([0-9]{4}-[0-9]{2}-[0-9]{2})')
TARGET_MET = 1800
WORKFLOWS = {'ci': '.github/workflows/ci.yml', 'privacy': '.github/workflows/privacy.yml'}
O16, O17 = 1284, 1285
AUTHORITY = re.compile(r'Release kit authority: scope ([0-9a-f]{64})')
RISK_PATTERNS = {
    'send': ('crates/adapters/cloudroom/src/allowlist.rs', 'crates/adapters/cloudroom/src/messaging.rs',
             'crates/core/src/messaging/**', 'crates/core/src/attachment.rs'),
    'new': ('crates/adapters/cloudroom/src/allowlist.rs', 'crates/adapters/cloudroom/src/new_thread.rs',
            'crates/core/src/new_thread/**'),
    'app_permissions': ('tools/github-app/**', 'crates/adapters/github/src/allowlist.rs',
                        'crates/adapters/github/src/app.rs'),
    'spending': ()}
READ_GATES = ('cutover', 'ci', 'privacy', 'claims')


class Blocked(Exception):
    def __init__(self, reasons, status='blocked'):
        super().__init__(', '.join(reasons))
        self.reasons, self.status = list(reasons), status


def same_name(value, name):
    return isinstance(value, str) and value.isascii() and value.lower() == name.lower()


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


def today():
    return datetime.datetime.fromtimestamp(now(), datetime.timezone.utc).date().isoformat()


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
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def phase(record, name, started, finished):
    ship = record['timing']['original_ship_at']
    if ship is not None and finished >= ship:
        record['timing']['phases'].append({'name': name, 'started_at': started, 'finished_at': finished})


def section_hash(text, version):
    starts = [m.start() for m in re.finditer(r'^## ', text, re.M)]
    for index, start in enumerate(starts):
        match = HEADING.match(text, start)
        if match and match[1] == version:
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            return sha(text[start:end].rstrip('\n').encode('utf-8'))
    raise Refused(f'no section for {version}')


def notes_input(data, version):
    curated = {'curated', 'curated_sha256', 'notes_sha256', 'included'}
    require(isinstance(data, dict) and set(data) in ({'versions', 'excluded'}, curated), 'invalid entry input')
    if 'curated' in data:
        require(isinstance(data['curated'], str) and re.fullmatch(r'changes/notes/[A-Za-z0-9][A-Za-z0-9._-]*\.md',
                                                                 data['curated'])
                and digest(data['curated_sha256']) and digest(data['notes_sha256'])
                and isinstance(data['included'], list) and data['included'][:1] == [version],
                'invalid entry input')
    return data


def made_notes(data, version, read, tags, sections):
    if 'curated' in data:
        raw = read(data['curated'])
        require(sha(raw) == data['curated_sha256'], 'entry: curated notes are not the approved bytes')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise Refused('entry: curated notes are not UTF-8') from None
        _, released = entry.curated(text, data['included'], tags)
        require(sha(released.encode('utf-8')) == data['notes_sha256'],
                'entry: release notes cut from the curated file are not the approved bytes')
        return released, raw
    versions = entry.entries(data['versions'], version)
    return '\n'.join(sections(versions, entry.exclusions(data['excluded']))), None


def expected_changelog(published, notes_text, curated, tags):
    if curated is None:
        return entry.compose(published, notes_text, restate=not tags)
    if tags:
        newest = max(tags)
        text = curated.decode('utf-8')
        cut = next((m.start() for m in re.finditer(r'^## ' + VERSION.pattern + ' ', text, re.M)
                    if number('.'.join(m.groups()[:3])) <= newest), len(text))
        new = text[text.index('\n## ') + 1:cut].rstrip('\n') + '\n'
        require(HEADING.match(new) is not None and entry.prepend(published, new, HEADING.findall(new)[-1][0]) == curated,
                'entry: the curated changelog must keep the published changelog unchanged')
    return curated


def history(read, tags):
    try:
        return read(f'refs/tags/{tags[max(tags)]}^{{commit}}' if tags else ANCHOR)
    except Refused:
        return b''


def notes(args):
    repo = Path(args.repo).resolve(strict=True)
    require(same_name(repository(repo), PUBLIC), 'notes come from the public repository')
    data = notes_input(strict(Path(args.entry).read_bytes()), args.version)
    head = local_git(repo, 'rev-parse', 'HEAD').decode().strip()
    check = argparse.Namespace(args=argparse.Namespace(repo=repo))
    sources = {}

    def generated(versions, excluded):
        made, found = entry.sections(check, head, versions, excluded)
        sources.update(found)
        return made

    tags = remote_tags(repo)
    text, curated = made_notes(data, args.version, lambda path: local_git(repo, 'show', f'{head}:{path}'),
                               set(tags.values()), generated)
    published = latest_changelog(repo) if tags else history(lambda ref: local_git(repo, 'show', ref + ':CHANGELOG.md'),
                                                            tags)
    changelog = expected_changelog(published, text, curated, tags)
    out = Path(args.out)
    require(not out.exists() and out.parent.is_dir(), 'output directory must be new')
    out.mkdir(mode=0o700)
    (out / 'notes.md').write_bytes(text.encode('utf-8'))
    (out / 'CHANGELOG.md').write_bytes(changelog)
    versions = [h[0] for h in HEADING.findall(text)]
    result = {'status': 'proposed', 'commit': head, 'notes_sha256': sha(text.encode('utf-8')),
              'notes_bytes': len(text.encode('utf-8')), 'changelog_sha256': sha(changelog),
              'sections': [{'version': v, 'section_sha256': section_hash(text, v)} for v in versions]}
    if curated is None:
        (out / 'sources.json').write_text(json.dumps({'commit': head, 'versions': sources,
                                                      'excluded': data['excluded']}, indent=1) + '\n')
        for row in result['sections']:
            row['entries'] = len(sources[row['version']])
    else:
        (out / 'sources.json').write_text(json.dumps({'commit': head, 'curated': data['curated'],
                                                      'curated_sha256': sha(curated)}, indent=1) + '\n')
        result['curated_sha256'] = sha(curated)
    return result


def latest_changelog(repo):
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


def check_source(repo, body, scratch):
    source = body['source']
    keys(source, 'repository commit tree anchor', 'invalid_source')
    if source['repository'] != PUBLIC or not same_name(repository(repo), PUBLIC):
        block('private_source')
    if source['anchor'] != ANCHOR or not digest(source['commit'], 40) or not digest(source['tree'], 40):
        block('unrelated_history')
    work = Path(scratch) / 'main.git'
    remote_git(scratch, 'clone', '-q', '--bare', '--no-local', '--no-tags', '--single-branch',
               '--branch', 'main', remote_url(PUBLIC), work)
    remote_git(work, 'remote', 'set-url', 'origin', remote_url(PUBLIC))
    try:
        remote_git(work, 'cat-file', '-e', source['commit'] + '^{commit}')
        remote_git(work, 'merge-base', '--is-ancestor', source['commit'], 'HEAD')
    except Refused:
        release_source(work, body)
    try:
        remote_git(work, 'merge-base', '--is-ancestor', ANCHOR, source['commit'])
    except Refused:
        block('unrelated_history')
    if remote_git(work, 'rev-parse', source['commit'] + '^{tree}').decode().strip() != source['tree']:
        block('tree_mismatch')
    return work


def release_heads(work):
    remote_git(work, 'fetch', '-q', '--no-tags', remote_url(PUBLIC), '+refs/heads/release-*:refs/release/release-*')
    return remote_git(work, 'for-each-ref', '--format=%(refname)', 'refs/release/').decode().split()


def release_source(work, body):
    commit, version = body['source']['commit'], body.get('release_version')
    if not isinstance(version, str) or VERSION.fullmatch(version) is None:
        block('not_on_public_main')
    try:
        heads = release_heads(work)
    except Refused:
        block('release_branch_unreadable')
    own = 'refs/release/release-' + version

    def reaches(head):
        try:
            remote_git(work, 'merge-base', '--is-ancestor', commit, head)
            return True
        except Refused:
            return False
    if own not in heads or not reaches(own):
        if any(reaches(head) for head in heads if head != own):
            block('release_branch_wrong_version')
        block('not_on_release_branch' if own in heads else 'not_on_public_main')
    reasons = release_protection('refs/heads/release-' + version)
    if reasons:
        block(*reasons)


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


def check_notes(body, work, own=None, entry_input=None):
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
    tags = remote_tags(work, own)
    if tags:
        tag = tags[max(tags)]
        remote_git(work, 'fetch', '-q', '--no-tags', remote_url(PUBLIC), f'refs/tags/{tag}:refs/tags/{tag}')
    commit = body['source']['commit']
    try:
        published = history(lambda ref: remote_git(work, 'show', ref + ':CHANGELOG.md'), tags)
        curated = None
        if isinstance(entry_input, dict) and 'curated' in entry_input:
            _, curated = made_notes(notes_input(entry_input, body['release_version']), body['release_version'],
                                    lambda path: remote_git(work, 'show', f'{commit}:{path}'), set(tags.values()),
                                    None)
        expected = expected_changelog(published, text, curated, tags)
        actual = remote_git(work, 'show', commit + ':CHANGELOG.md')
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
        except Exception:
            block('artifact_manifest')
        if (value['version'] != version or value['source'] != body['source']['commit']
                or value['archive'] != archive or value['archive_sha256'] != sha(data[archive])
                or value['archive_bytes'] != len(data[archive])):
            block('artifact_manifest')
        stage(folder / manifest, folder / archive, sha(data[manifest]), target)
    return data


def stage(manifest, archive, checksum, target, keep=None):
    import install as installer
    scratch = Path(tempfile.mkdtemp(prefix='release-stage-', dir=keep))
    try:
        result = installer.install(manifest, archive, checksum, scratch / 'root', target, stage_only=True)
    except Exception:
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
        check_notes(body, work, entry_input=inputs['entry'])
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


def comment(pointer):
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


def revoked(issue, comment_id, decided_at, pattern=REVOKED):
    try:
        rows = strict(gh('api', '--paginate', '--slurp', f'repos/{PRIVATE}/issues/{issue}/comments?per_page=100'))
    except (Refused, ValueError):
        block('unreadable')
    rows = [c for page in rows for c in page] if rows and isinstance(rows[0], list) else rows
    later = False
    for c in rows:
        if (isinstance(c, dict) and isinstance(c.get('body'), str)
                and any((m := pattern.fullmatch(line)) and m[1] == comment_id for line in c['body'].splitlines())):
            at = epoch(c.get('created_at'))
            if c.get('updated_at') != c.get('created_at'):
                return True
            if at == decided_at:
                block('unreadable')
            later = later or at > decided_at
    return later


def resolve_decision(kind, pointer):
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


def resolve_waiver(pointer, body):
    issue, comment_id, data = comment(pointer)
    text = data['body']
    lines = text.splitlines()
    if (data['user'].get('login') != OWNER or not lines
            or not re.match(r'Private record: Jake, [0-9]{4}-[0-9]{2}-[0-9]{2}', lines[0])
            or data.get('updated_at') != data['created_at']):
        block('waiver_not_a_record')
    named = [line for line in lines if line.startswith('Release waiver:')]
    if not named:
        block('waiver_not_a_record')
    found = [WAIVER.fullmatch(line) for line in named]
    if len(named) != 1 or not found[0]:
        block('waiver_invalid')
    risk, version = found[0][1], found[0][2]
    if risk not in {r for r, _ in WAIVABLE}:
        block('waiver_wrong_risk')
    if version != body['release_version'] or (risk, version) not in WAIVABLE:
        block('waiver_wrong_version')
    if revoked(issue, comment_id, epoch(data['created_at']), WAIVER_REVOKED):
        block('waiver_revoked')
    return {'pointer': pointer, 'record_sha256': sha(text.encode('utf-8')),
            'decided_at': epoch(data['created_at']), 'risk': risk, 'version': version}


def current_waiver(record):
    saved = record['decisions'].get('waiver')
    if saved is None:
        return None, []
    try:
        current = resolve_waiver(saved['pointer'], record['candidate'])
    except Blocked as error:
        return None, error.reasons
    return (current, []) if current == saved else (None, ['waiver_changed'])


def applied_waiver(record):
    waiver, _ = current_waiver(record)
    if waiver is not None and record['candidate']['risk'][waiver['risk']]['required'] == 'yes':
        return waiver
    return None


def decide(args):
    state = State(args.state)
    record = state.read()
    if args.waiver:
        waiver = resolve_waiver(args.waiver, record['candidate'])
        record['decisions']['waiver'] = waiver
        state.write('record.json', record)
        return {'status': 'recorded', 'decision': 'waiver', 'waived': waiver['risk']}
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
            if not isinstance(meta, dict) or not same_name(meta.get('full_name'), PUBLIC) \
                    or meta.get('visibility') != 'public' or meta.get('archived') is not False:
                return ['unverified']
    except (Blocked, Refused, ValueError):
        return ['unreadable']
    return []


def verify_products(record, inputs, ctx):
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
            installed = {}
            for row in receipts:
                keys(row, 'target program selection', 'invalid')
                target = row['target']
                manifest = folder / f'openwiz-{version}-{target}.manifest.json'
                checksum = sha(manifest.read_bytes())
                build = stage(manifest, folder / f'openwiz-{version}-{target}.tar.gz', checksum, target, keep=scratch)
                saved = Path(scratch) / ('receipts-' + target)
                saved.mkdir()
                for kind in ('program',):
                    keys(row[kind], 'name utf8', 'invalid')
                    if not isinstance(row[kind]['name'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',
                                                                                 row[kind]['name']):
                        block('invalid')
                    (saved / row[kind]['name']).write_bytes(row[kind]['utf8'].encode('utf-8'))
                rows = rl4.verify_programs({p: (build / n).read_bytes() for p, n in rl4.PROGRAMS.items()},
                                           saved / row['program']['name'], version, source, target)
                value, _, _ = manifest_at(manifest, checksum, target)
                assets = [a for a in value['assets'] if a['path'] not in rl4.STAMPS]
                final = {'runtime': rl4.payload([a for a in value['assets'] if a['path'].startswith('runtime/')])}
                runtime = [a for a in assets if a['path'].startswith('runtime/')]
                selection = row['selection']
                if (not isinstance(selection, list) or selection != sorted(selection)
                        or any(not isinstance(pair, list) or len(pair) != 2 for pair in selection)
                        or sorted(name for _, name in selection) != sorted(a['path'] for a in runtime)):
                    return ['unverified']
                if 'install' not in installed:
                    installed['install'] = rl4.install_locked(ctx['work'], source, tempfile.mkdtemp(dir=scratch))
                rl4.verify_runtime(ctx['work'], source, {repo: (build / name).read_bytes() for repo, name in selection},
                                   installed['install'])
                rows.append({'identity': rl4.expected('runtime', version, source, target),
                             'payload_sha256': final['runtime'], 'verification': 'tracked-tree',
                             'build_receipt': {'record': 'tracked-tree', 'sha256': sha(rl4.canonical(
                                 {'source': source, 'selection': selection}))}})
                got += sorted(rows, key=lambda r: r['identity']['product'])
    except Exception:
        return ['unverified']
    return [] if got == body['products'] else ['mismatch']


def pages(path, key=None):
    data = strict(gh('api', '--paginate', '--slurp', path))
    require(isinstance(data, list), 'unexpected pages')
    rows = []
    for page in data:
        page = page.get(key) if key and isinstance(page, dict) else page
        require(isinstance(page, list), 'unexpected page')
        rows += page
    return rows


def required_check(gate, commit):
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

    def skipped(workflow):
        own = [r for r in runs if isinstance(r.get('check_suite'), dict)
               and r['check_suite'].get('id') == workflow.get('check_suite_id')]
        return bool(own) and all(r.get('status') == 'completed' and r.get('conclusion') == 'skipped' for r in own)
    trusted = [w for w in trusted if not skipped(w)]
    if not trusted:
        return ['missing'], None
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
            for part in ('runtime',):
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
    if pattern == '~ALL':
        return True
    if pattern == '~DEFAULT_BRANCH':
        return ref == 'refs/heads/' + default
    require(isinstance(pattern, str) and re.fullmatch(r'[A-Za-z0-9._/*-]+', pattern) is not None
            and '**' not in pattern, 'unevaluable ref pattern')
    return re.fullmatch('[^/]*'.join(map(re.escape, pattern.split('*'))), ref) is not None


def ruleset_applies(detail, default, ref=None):
    if detail.get('enforcement') != 'active' or detail.get('target') != 'branch':
        return False
    conditions = detail.get('conditions')
    require(isinstance(conditions, dict) and set(conditions) == {'ref_name'}, 'unevaluable ruleset conditions')
    names = conditions['ref_name']
    require(isinstance(names, dict) and set(names) <= {'include', 'exclude'}
            and all(isinstance(names.get(k, []), list) for k in ('include', 'exclude')), 'unevaluable ruleset conditions')
    ref = ref or 'refs/heads/' + default
    return (any(ref_matches(p, ref, default) for p in names.get('include', []))
            and not any(ref_matches(p, ref, default) for p in names.get('exclude', [])))


def branch_rulesets(ref=None):
    meta = gh_json(f'repos/{PUBLIC}')
    sets = [gh_json(f"repos/{PUBLIC}/rulesets/{r['id']}") for r in pages(f'repos/{PUBLIC}/rulesets?per_page=100')]
    default = meta.get('default_branch')
    require(isinstance(default, str) and re.fullmatch(r'[A-Za-z0-9._/-]+', default) is not None,
            'unreadable default branch')
    return meta, [d for d in sets if ruleset_applies(d, default, ref)]


def required_contexts(rulesets):
    return {c.get('context') for d in rulesets for rule in d.get('rules') or [] if rule.get('type') ==
            'required_status_checks' for c in (rule.get('parameters') or {}).get('required_status_checks') or []}


def release_protection(ref):
    try:
        _, applied = branch_rulesets(ref)
        types = {rule.get('type') for d in applied for rule in d.get('rules') or []}
        ok = (applied and {'ci', 'privacy'} <= required_contexts(applied) and {'non_fast_forward', 'deletion'} <= types
              and all(d.get('bypass_actors') == [] for d in applied))
    except (Blocked, Refused, ValueError, AttributeError, KeyError, TypeError):
        return ['release_ruleset_unreadable']
    return [] if ok else ['release_branch_unprotected']


def cutover_reasons():
    try:
        o16, o17 = gh_json(f'repos/{PRIVATE}/issues/{O16}'), gh_json(f'repos/{PRIVATE}/issues/{O17}')

        def held(issue):
            return any(isinstance(label, dict) and label.get('name') == 'held' for label in issue.get('labels', []))
        immutable = gh_json(f'repos/{PUBLIC}/immutable-releases')
        meta, main = branch_rulesets()
        contexts = required_contexts(main)
        ok = (o17.get('state') == 'closed' and o17.get('state_reason') == 'completed' and not held(o17)
              and not held(o16) and same_name(meta.get('full_name'), PUBLIC) and meta.get('visibility') == 'public'
              and meta.get('archived') is False and immutable.get('enabled') is True and main
              and {'ci', 'privacy'} <= contexts and all(d.get('bypass_actors') == [] for d in main))
    except (Blocked, Refused, ValueError, AttributeError, KeyError, TypeError):
        return ['unverified'], None
    if not ok:
        return ['unverified'], None
    return [], {'o17': O17, 'rulesets': sorted(d.get('id') for d in main)}


def claims_reasons(body, entry_input, work):
    commit = body['source']['commit']
    check = argparse.Namespace(args=argparse.Namespace(repo=work))
    try:
        data = notes_input(entry_input, body['release_version'])
        made, _ = made_notes(data, body['release_version'], lambda path: remote_git(work, 'show', f'{commit}:{path}'),
                             set(remote_tags(work).values()),
                             lambda versions, excluded: entry.sections(check, commit, versions, excluded)[0])
    except (Refused, ValueError, KeyError, TypeError):
        return ['unverified'], None
    if made != body['changelog']['utf8']:
        return ['mismatch'], None
    return [], {'notes_sha256': body['changelog']['sha256'], 'entry_sha256': canonical(entry_input)}


def kit_reasons(body):
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
    _, _, data = comment(record_pointer)
    return {'body': data['body'], 'created_at': epoch(data['created_at'])}


def live(args):
    state = State(args.state)
    record = state.read()
    receipts = smoke_module()
    waiver = applied_waiver(record)
    try:
        doc = receipts.produce(Path(args.kit), Path(args.smoke_state), record, args.record, waiver)
    except (receipts.Refusal, receipts.smoke.Refusal) as error:
        block(f'smoke_{error}')
    state.write('live.json', {'doc': doc, 'kit': str(Path(args.kit).resolve()),
                              'state': str(Path(args.smoke_state).resolve())})
    for gate in ('smoke',) + RISKS:
        record['gates'][gate] = doc['gates'][gate]
    state.write('record.json', record)
    return {'status': 'recorded', 'gates': {g: (doc['gates'][g] or {}).get('status') for g in ('smoke',) + RISKS}}


def live_reasons(record, saved, waiver=None):
    waived = (waiver['risk'],) if waiver else ()
    reasons = []
    risk = record['candidate']['risk']
    for name in RISKS:
        if risk[name]['required'] == 'unknown':
            reasons.append(f'{name}_unknown')
    if saved is None:
        reasons.append('smoke_missing')
        reasons += [f'{n}_live_missing' for n in RISKS if risk[n]['required'] == 'yes' and n not in waived]
        return reasons
    receipts = smoke_module()
    for gate in ('smoke',) + RISKS:
        if gate != 'smoke' and (risk[gate]['required'] != 'yes' or gate in waived):
            continue
        try:
            receipts.accept(gate, saved['doc'], record, Path(saved['kit']), Path(saved['state']), preserved,
                            waiver=waiver)
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
            check_notes(body, work, own, state.read('entry.json') if state.exists('entry.json') else None)
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
    reasons += current_waiver(record)[1]
    waiver = applied_waiver(record)
    if waiver is not None:
        made[waiver['risk']] = {'status': 'waived', 'waiver': waiver}
    reasons += live_reasons(record, live_doc(state), waiver)
    return reasons


def evaluate(args):
    repo = Path(args.repo).resolve(strict=True)
    state = State(args.state)
    record = state.read()
    started = now()
    made = {}
    reasons = reasons_for(record, state, repo, artifacts=Path(args.artifacts), literals=args.literals, made=made)
    unreadable = None
    if reasons != ['candidate_changed']:
        with tempfile.TemporaryDirectory(prefix='release-candidate-') as scratch:
            found, unreadable = first_write_reasons(record['candidate'], Path(args.artifacts), scratch)
            reasons += found
    record['gates'].update(made)
    phase(record, 'checks', started, now())
    state.write('record.json', record)
    if reasons:
        raise Blocked(reasons)
    if unreadable is not None:
        raise unreadable
    waived = sorted(g for g, r in made.items() if r and r.get('status') == 'waived')
    return dict({'status': 'ready', 'candidate_sha256': record['candidate_sha256']},
                **({'waived': waived} if waived else {}))


def tagger(work, commit):
    name = remote_git(work, 'show', '-s', '--format=%an', commit).decode().strip()
    email = remote_git(work, 'show', '-s', '--format=%ae', commit).decode().strip()
    if not re.fullmatch(r'[A-Za-z .-]+', name) or \
            not re.fullmatch(r'[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com', email):
        block('tagger_identity')
    return name, email


def public_name(version):
    return PUBLIC_NAMES.get(version, 'OpenWiz ' + version)


def release_readback(record, scratch, tag_object):
    body = record['candidate']
    tag = 'v' + body['release_version']
    commit = body['source']['commit']
    data = gh_json(f'repos/{PUBLIC}/releases/tags/{tag}')
    notes_text = body['changelog']['utf8']
    problems = []
    if not isinstance(data, dict) or data.get('tag_name') != tag or data.get('name') != public_name(body['release_version']):
        problems.append('release_identity')
        data = data if isinstance(data, dict) else {}
    remote_body = data.get('body')
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
    folder = Path(tempfile.mkdtemp(prefix='downloaded-', dir=scratch))
    gh('release', 'download', tag, '--repo', PUBLIC, '--dir', str(folder), cwd=scratch)
    got = {p.name: p.read_bytes() for p in folder.iterdir()}
    if sorted(got) != sorted(wanted) or any(sha(got[n]) != wanted[n]['sha256'] for n in got if n in wanted):
        problems.append('asset_bytes')
    found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if found.get(f'refs/tags/{tag}^{{}}') != commit or found.get(f'refs/tags/{tag}') != tag_object:
        problems.append('tag')
    return problems, found.get(f'refs/tags/{tag}'), data


def settle(record, attempt, scratch):
    body = record['candidate']
    tag = 'v' + body['release_version']
    if attempt['steps'].get('tag') == 'started':
        found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
        if found.get(f'refs/tags/{tag}^{{}}') != body['source']['commit']:
            raise Blocked(['uncertain_tag'], status='uncertain')
        if found.get(f'refs/tags/{tag}') == body['source']['commit']:
            raise Blocked(['uncertain_tag'], status='uncertain')
        if not attempt.get('tag_object') or found.get(f'refs/tags/{tag}') != attempt['tag_object']:
            raise Blocked(['uncertain_tag'], status='uncertain')
        attempt['steps']['tag'] = 'done'
    if attempt['steps'].get('release') == 'started':
        try:
            problems, _, _ = release_readback(record, scratch, attempt['tag_object'])
        except (Refused, ValueError):
            raise Blocked(['uncertain_release'], status='uncertain') from None
        if problems:
            raise Blocked(['uncertain_release'], status='uncertain')
        attempt['steps']['release'] = 'done'


def immutable_reasons():
    try:
        enabled = gh_json(f'repos/{PUBLIC}/immutable-releases')
    except (Refused, ValueError):
        enabled = None
    return [] if isinstance(enabled, dict) and enabled.get('enabled') is True else ['immutable_releases_off']


def tag_reasons(scratch, tag, own=None):
    found = refs(scratch, remote_url(PUBLIC), f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if found and (own is None or found != {f'refs/tags/{tag}': own[1], f'refs/tags/{tag}^{{}}': own[2]}):
        return ['tag_exists']
    return []


def ready(body, artifacts, scratch, tag, own=None):
    data = check_artifacts(body, artifacts)
    reasons = immutable_reasons() or tag_reasons(scratch, tag, own)
    if reasons:
        block(*reasons)
    return data


def tagging_clone(scratch, commit):
    work = Path(scratch) / 'main.git'
    remote_git(scratch, 'clone', '-q', '--bare', '--no-local', '--no-tags', '--single-branch',
               '--branch', 'main', remote_url(PUBLIC), work)
    try:
        remote_git(work, 'cat-file', '-e', commit + '^{commit}')
    except Refused:
        release_heads(work)
    return work


def tagger_reasons(scratch, commit):
    try:
        tagger(tagging_clone(scratch, commit), commit)
    except Blocked as error:
        return error.reasons
    return []


def first_write_reasons(body, artifacts, scratch):
    tag, reasons = 'v' + body['release_version'], date_reasons(body)
    try:
        check_artifacts(body, artifacts)
    except Blocked as error:
        reasons += error.reasons
    reasons += immutable_reasons()
    unreadable = None
    for read in (lambda: tag_reasons(scratch, tag),
                 lambda: tagger_reasons(scratch, body['source']['commit'])):
        try:
            reasons += read()
        except Refused as error:
            unreadable = unreadable or error
    return reasons, unreadable


def date_reasons(body):
    dates = [m[5] for m in re.finditer('^' + HEADING.pattern + '$', body['changelog']['utf8'], re.M)]
    return ['changelog_date'] if any(d != today() for d in dates) else []


def record_waived(record, state, made):
    waived = {g: r for g, r in made.items() if r and r.get('status') == 'waived'}
    if waived:
        record['gates'].update(waived)
        state.write('record.json', record)


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
            if attempt is None or attempt['steps'] != {'tag': 'done', 'release': 'done'}:
                raise Blocked(['publication_incomplete'], status='incomplete')
        else:
            if attempt is None:
                made = {}
                reasons = reasons_for(record, state, repo, artifacts=Path(args.artifacts),
                                      literals=args.literals, made=made) + date_reasons(body)
                if reasons:
                    raise Blocked(reasons)
                record_waived(record, state, made)
                ready(body, args.artifacts, scratch, tag)
                work = tagging_clone(scratch, body['source']['commit'])
                name, email = tagger(work, body['source']['commit'])
                remote_git(work, '-c', 'user.name=' + name, '-c', 'user.email=' + email, '-c', 'tag.gpgSign=false',
                           'tag', '-a', tag, body['source']['commit'], '-m', 'OpenWiz ' + body['release_version'])
                intended = remote_git(work, 'rev-parse', '--verify', f'refs/tags/{tag}').decode().strip()
                attempt = {'attempt_id': f"{record['candidate_sha256'][:16]}-{started}",
                           'candidate_sha256': record['candidate_sha256'], 'tag': tag, 'steps': {},
                           'started_at': started, 'tag_object': intended}
                attempt['steps']['tag'] = 'started'
                state.write('attempt.json', attempt)
                remote_git(work, 'push', '--no-follow-tags', '--porcelain', remote_url(PUBLIC),
                           f'refs/tags/{tag}:refs/tags/{tag}')
            settle(record, attempt, scratch)
            state.write('attempt.json', attempt)
            if attempt['steps'].get('tag') == 'done' and 'release' not in attempt['steps']:
                own = (tag, attempt['tag_object'], body['source']['commit'])
                made = {}
                reasons = (reasons_for(record, state, repo, own, Path(args.artifacts), args.literals, made)
                           + date_reasons(body))
                if reasons:
                    raise Blocked(reasons)
                record_waived(record, state, made)
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
                   '--title', public_name(body['release_version']), '--notes-file', str(notes_file), *files,
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
            'immutable': not {'unreadable', 'immutable'} & set(problems),
            'prerelease': not {'unreadable', 'prerelease'} & set(problems),
            'verified_at': verified, 'evidence': {'record': 'readback:' + tag, 'sha256': sha(evidence)}}
        prior = [p['finished_at'] for p in record['timing']['phases'] if p['name'] == 'publish']
        phase(record, 'publish', max([attempt['started_at']] + prior), verified)
        state.write('record.json', record)
        if problems:
            raise Blocked([f'readback_{p}' for p in problems], status='incomplete')
    return {'status': 'published', 'tag': tag, 'tag_object': record['publication']['tag_object']}


def fetch_release(url, limit):
    import pull
    return pull.fetch_bytes(url, limit)


def installer_entry():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader('openwiz_install_entry', str(HERE.parent / 'install' / 'install'))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def strangers_install_route(target, clean, body):
    entry_cli, fetched, steps = installer_entry(), [], []

    def fetch(url, limit):
        try:
            data = fetch_release(url, limit)
        except urllib.error.HTTPError as error:
            fetched.append({'url': url, 'status': error.code})
            raise
        except Exception:
            fetched.append({'url': url, 'status': None})
            raise
        fetched.append({'url': url, 'status': 200, 'sha256': sha(data)})
        return data

    def run(*argv):
        out = io.StringIO()
        code = entry_cli.main(list(argv), fetch=fetch, stdout=out)
        try:
            value = strict(out.getvalue())
        except ValueError:
            value = None
        steps.append({'command': argv[0], 'exit': code, 'output': value})
        return value if code == 0 and isinstance(value, dict) else None

    identity = (body['release_version'], body['source']['commit'])
    got = run('download', '--target', target, '--dir', str(clean / 'download'))
    if got is None:
        unresolved = fetched[:1] and fetched[0]['status'] == 404
        reason = 'install_latest_unresolved' if unresolved else 'install_download_refused'
    elif (got.get('version'), got.get('source')) != identity:
        reason = 'install_latest_not_candidate'
    else:
        reason = None
        root = str(clean / 'openwiz')
        for step in (('install', '--assets', str(clean / 'download'), '--target', target, '--root', root),
                     ('status', '--root', root)):
            got = run(*step)
            if got is None or got.get('outcome') != 'installed' or (got.get('version'), got.get('source')) != identity:
                reason = 'install_refused'
                break
    return reason, {'target': target, 'downloads': fetched, 'steps': steps}


def install(args):
    state = State(args.state)
    record = state.read()
    publication = record['publication']
    if not publication or publication['status'] != 'complete':
        block('publication_incomplete')
    body, target = record['candidate'], args.target
    names = {(a['role'], a['target']): a['sha256'] for a in body['artifacts']}
    with tempfile.TemporaryDirectory(prefix='openwiz-install-check-') as clean:
        clean = Path(clean).resolve()
        reason, evidence = strangers_install_route(target, clean, body)
        if reason is None:
            name = 'openwiz-' + target
            manifest = sha((clean / 'download' / (name + '.manifest.json')).read_bytes())
            archives = [f for f in (clean / 'download').iterdir() if f.name.endswith('.tar.gz')]
            archive = sha(archives[0].read_bytes()) if len(archives) == 1 else None
            if manifest != names.get(('manifest', target)) or archive != names.get(('archive', target)):
                reason = 'install_mismatch'
    verified = now()
    if reason is None and verified < publication['verified_at']:
        reason = 'install_mismatch'
    attempt = install_attempt(state, target, reason, verified, evidence)
    if reason:
        block(reason)
    record['install'] = {'route': 'install', 'version': body['release_version'], 'source': body['source']['commit'],
                         'target': target, 'manifest_sha256': manifest, 'archive_sha256': archive,
                         'verified_at': verified, 'evidence': attempt['evidence']}
    record['timing']['finished_at'] = verified
    phase(record, 'install', publication['verified_at'], verified)
    state.write('record.json', record)
    return report(record, install_attempts(state))


def install_attempt(state, target, reason, at, evidence):
    folder = state.file(f'evidence/install-{target}')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    outcome = {'status': 'blocked' if reason else 'passed', 'reasons': [reason] if reason else [], 'at': at}
    data = (json.dumps(dict(evidence, **outcome), indent=1, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
    while True:
        taken = [int(f.stem) for f in folder.iterdir() if ATTEMPT.fullmatch(f.name)]
        name = f'evidence/install-{target}/{max(taken, default=0) + 1}.json'
        try:
            fd = os.open(state.file(name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return dict(outcome, target=target, evidence={'record': name, 'sha256': sha(data)})


def install_attempts(state):
    latest = {}
    for target in TARGETS:
        folder = state.file(f'evidence/install-{target}')
        names = [f for f in folder.iterdir() if ATTEMPT.fullmatch(f.name)] if folder.is_dir() else []
        files = sorted((int(f.stem), f) for f in names)
        if files:
            data = files[-1][1].read_bytes()
            saved = strict(data)
            latest[target] = {'target': target, 'status': saved['status'], 'reasons': saved['reasons'],
                              'at': saved['at'], 'attempts': len(files),
                              'evidence': {'record': f'evidence/install-{target}/{files[-1][0]}.json',
                                           'sha256': sha(data)}}
    return [latest[t] for t in TARGETS if t in latest]


def report(record, attempts=()):
    timing = record['timing']
    ship, finished = timing['original_ship_at'], timing['finished_at']
    elapsed = finished - ship if ship is not None and finished is not None else None
    passing = all(a['status'] == 'passed' for a in attempts)
    return {'status': 'complete' if elapsed is not None and passing else 'incomplete',
            'install_attempts': list(attempts),
            'candidate_sha256': record['candidate_sha256'], 'original_ship_at': ship,
            'preparation_started_at': timing['preparation_started_at'], 'finished_at': finished,
            'elapsed_seconds': elapsed, 'target_met': None if elapsed is None else elapsed < TARGET_MET,
            'phases': timing['phases'],
            'publication': (record['publication'] or {}).get('status')}


def status(args):
    state = State(args.state)
    return report(state.read(), install_attempts(state))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='release candidate', description=DESCRIPTION,
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
    which.add_argument('--waiver', help="a recorded one-release waiver (APP-1): 'Release waiver: RISK vX.Y.Z'")
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
    made.add_argument('--target', required=True, choices=TARGETS)
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
        result, code = {'status': 'refused', 'reasons': [type(error).__name__ if not isinstance(error, Refused)
                                                         else str(error)]}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
