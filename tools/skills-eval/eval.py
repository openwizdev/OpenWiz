#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DESCRIPTION = """Skills eval command line (contract.md). Standard library only.

  eval.py check                          cases, coverage, provenance, required text, controls, ledger (offline)
  eval.py coverage                       every ledger row with its cases (offline)
  eval.py ledger [--propose]             the ledger against the pin and every branch of the checkout (offline)
  eval.py run --out DIR [--rev REV]      offline checks, then paid role runs; resumable; needs OPENROUTER_API_KEY
  eval.py score DIR                      score a results set; exit 0 only if every case passed every repeat
  eval.py compare A B                    compare two scored sets with equal settings and cases hashes
  eval.py tokens --out FILE [--rev REV] [--offline]
  eval.py token-diff BEFORE AFTER

check, coverage, ledger, run and tokens read the skills from a pinned WizSkills checkout:
--wizskills DIR --wizskills-commit SHA, or WIZSKILLS_CHECKOUT and WIZSKILLS_COMMIT.
"""

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as C
import driver
import score as S
import tokens as T

REPO = HERE.parent.parent
CODE = ['contract.md', 'fakeworld.py', 'score.py', 'records.py', 'cases.py', 'driver.py', 'tokens.py', 'eval.py']
LEDGER = HERE / 'ledger.json'
LEDGER_SCHEMA = 'openwiz.skills-eval.ledger.v1'
ROW_KEYS = {'shipped': ['status'], 'observed-used': ['status', 'used_by'],
            'historical-only': ['last_seen', 'status'], 'branch-only': ['branch', 'commit', 'status']}
FULL = re.compile(r'[0-9a-f]{40}')
PLUGIN = '.claude-plugin/plugin.json'
NO_PIN = ('no pinned WizSkills: pass --wizskills DIR --wizskills-commit SHA, '
          'or set WIZSKILLS_CHECKOUT and WIZSKILLS_COMMIT')


class Refusal(Exception):
    pass


def git(*args, repo=REPO):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True).stdout


def ok(*args, repo):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True).returncode == 0


def parse_plugin(text):
    try:
        data = json.loads(text)
    except ValueError:
        raise Refusal(f'{PLUGIN} in pinned WizSkills is not valid JSON')
    items = data.get('skills') if isinstance(data, dict) else None
    if not isinstance(items, list) or any(not isinstance(p, str) or not p.strip() for p in items):
        raise Refusal(f'{PLUGIN} in pinned WizSkills must list string skill paths')
    return [p.rsplit('/', 1)[-1] for p in items]


def resolve_rev(rev, host=None):
    host = REPO if host is None else host
    if not isinstance(rev, str) or not rev or rev.startswith('-'):
        raise Refusal(f'invalid host revision: {rev!r}')
    try:
        return git('rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}', repo=host).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        raise Refusal(f'unknown host revision: {rev}')


def pinned(checkout, commit):
    if not checkout or not commit:
        raise Refusal(NO_PIN)
    if not FULL.fullmatch(commit):
        raise Refusal('pin WizSkills by its full 40-character commit, not a branch, tag or short id')
    try:
        found = git('rev-parse', '--verify', '--quiet', f'{commit}^{{commit}}', repo=checkout).decode().strip()
        tree = git('rev-parse', f'{commit}^{{tree}}', repo=checkout).decode().strip()
        shallow = git('rev-parse', '--is-shallow-repository', repo=checkout).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        found = None
    if found != commit:
        raise Refusal(f'the WizSkills checkout does not have commit {commit[:12]}: fetch it there first')
    if shallow == 'true':
        raise Refusal('the WizSkills checkout is shallow, and the ledger reads its history: '
                      'run git fetch --unshallow there')
    if not ok('cat-file', '-e', f'{commit}:{PLUGIN}', repo=checkout):
        raise Refusal(f'commit {commit[:12]} has no {PLUGIN}: is that checkout WizSkills?')
    try:
        parse_plugin(git('cat-file', 'blob', f'{commit}:{PLUGIN}', repo=checkout).decode())
    except UnicodeDecodeError:
        raise Refusal(f'{PLUGIN} in pinned WizSkills is not valid UTF-8')
    return {'checkout': Path(checkout), 'commit': commit, 'tree': tree}


def pin_from(a):
    return pinned(getattr(a, 'wizskills', None) or os.environ.get('WIZSKILLS_CHECKOUT'),
                  getattr(a, 'wizskills_commit', None) or os.environ.get('WIZSKILLS_COMMIT'))


def tree_names(repo, rev, *paths):
    out = git('-c', 'core.quotePath=false', 'ls-tree', '-r', '-z', '--name-only', rev, *paths, repo=repo)
    return [n for n in out.decode().split('\0') if n]


def snapshot(rev, pin, host=None):
    host = REPO if host is None else host
    at = resolve_rev(rev, host)
    where = {n: (host, at, n) for n in tree_names(host, at)
             if n != 'skills' and not n.startswith(('skills/', '.wizskills/'))}
    if pin:
        for n in tree_names(pin['checkout'], pin['commit']):
            where['.wizskills/' + n] = (pin['checkout'], pin['commit'], n)
            if n.startswith('skills/'):
                where[n] = where['.wizskills/' + n]
    names = sorted(where)
    cache = {}

    def read(p):
        if p not in where:
            return None
        if p not in cache:
            repo, commit_at, name = where[p]
            try:
                cache[p] = git('cat-file', 'blob', f'{commit_at}:{name}', repo=repo).decode()
            except (UnicodeDecodeError, subprocess.CalledProcessError):
                cache[p] = None
        return cache[p]

    def lst(prefix):
        return [n for n in names if n.startswith(prefix)]
    return read, lst


def revision(rev, host=None):
    host = REPO if host is None else host
    commit = resolve_rev(rev, host)
    tree = git('rev-parse', f'{commit}^{{tree}}', repo=host).decode().strip()
    return {'commit': commit, 'tree': tree}


def wizskills_revision(pin):
    return {'commit': pin['commit'], 'tree': pin['tree']}


def skills_at(pin, ref):
    return {n.split('/')[1] for n in tree_names(pin['checkout'], ref, 'skills/')
            if n.count('/') == 2 and n.endswith('/SKILL.md')}


def skills_before(pin):
    out = git('-c', 'core.quotePath=false', 'log', '--no-renames', '--format=', '--name-only', pin['commit'],
              '--', 'skills/*/SKILL.md', repo=pin['checkout']).decode()
    return {n.split('/')[1] for n in out.splitlines() if n.count('/') == 2 and n.endswith('/SKILL.md')}


def present(pin, commit):
    return ok('cat-file', '-e', f'{commit}^{{commit}}', repo=pin['checkout'])


def has(pin, commit, path):
    return ok('cat-file', '-e', f'{commit}:{path}', repo=pin['checkout'])


def ancestor(pin, commit):
    return ok('merge-base', '--is-ancestor', commit, pin['commit'], repo=pin['checkout'])


def rows_of(ledger):
    if (not isinstance(ledger, dict) or set(ledger) != {'schema', 'skills'} or ledger['schema'] != LEDGER_SCHEMA
            or not isinstance(ledger['skills'], dict)):
        return None
    return ledger['skills']


def ledger_problems(ledger, pin, read, referenced, earlier):
    rows = rows_of(ledger)
    if rows is None:
        return ['ledger.json is not an openwiz.skills-eval.ledger.v1 object']
    at = pin['commit'][:12]
    here, listed = skills_at(pin, pin['commit']), set(shipped(read))
    before = skills_before(pin) - here
    errs = [f'{n}: on WizSkills {at} with no ledger row' for n in sorted(here - set(rows))]
    errs += [f'{n}: in the history of WizSkills {at} with no ledger row' for n in sorted(before - set(rows))]
    errs += [f"{n}: named by the eval's cases or maps with no ledger row"
             for n in sorted(set(referenced) - set(rows) - here - before)]
    errs += [f'{n}: dropped from the ledger; change its status instead of removing the row'
             for n in sorted(set(earlier) - set(rows))]
    errs += [f'{n}: {PLUGIN} lists it, but skills/{n}/SKILL.md is not at {at}' for n in sorted(listed - here)]
    for n, row in sorted(rows.items()):
        status = row.get('status') if isinstance(row, dict) else None
        if status not in ROW_KEYS:
            errs.append(f'{n}: status must be one of {sorted(ROW_KEYS)}')
            continue
        if sorted(row) != ROW_KEYS[status]:
            errs.append(f'{n}: a {status} row has exactly the keys {ROW_KEYS[status]}')
            continue
        path = f'skills/{n}/SKILL.md'
        if status in ('shipped', 'observed-used'):
            actual = ('shipped' if n in listed else 'observed-used') if n in here else None
            if actual != status:
                errs.append(f'{n}: {status}, but at {at} it is ' + (actual or f'not on WizSkills (no {path})'))
            elif status == 'observed-used':
                used_by = row['used_by']
                if not isinstance(used_by, str) or f'skills/{n}/' not in (read(used_by) or ''):
                    errs.append(f'{n}: observed-used needs used_by, a file in the snapshot that names skills/{n}/')
        elif n in here:
            errs.append(f'{n}: {status}, but {path} is at {at}')
        elif status == 'historical-only':
            seen = row['last_seen']
            if not (isinstance(seen, str) and FULL.fullmatch(seen) and present(pin, seen)):
                errs.append(f'{n}: historical-only needs last_seen, a full commit in the history of {at}')
            elif not has(pin, seen, path):
                errs.append(f'{n}: historical-only, but {path} is not at {seen[:12]}')
            elif not ancestor(pin, seen):
                errs.append(f'{n}: historical-only, but {seen[:12]} is not in the history of {at}')
        elif n in before:
            errs.append(f'{n}: was on WizSkills main before {at}, so it is historical-only, not branch-only')
        elif not (isinstance(row['branch'], str) and row['branch'].strip()
                  and isinstance(row['commit'], str) and FULL.fullmatch(row['commit'])):
            errs.append(f'{n}: branch-only needs branch and commit, a full commit that has {path}')
        elif present(pin, row['commit']) and not has(pin, row['commit'], path):
            errs.append(f"{n}: branch-only, but {path} is not at {row['commit'][:12]}")
        elif present(pin, row['commit']) and ancestor(pin, row['commit']):
            errs.append(f"{n}: branch-only, but {row['commit'][:12]} is in the history of {at}")
    return errs


def branch_skills(pin, known):
    found = {}
    refs = git('for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/remotes', repo=pin['checkout'])
    for ref in sorted(refs.decode().split()):
        if ref.endswith('/HEAD'):
            continue
        short = re.sub(r'^refs/(heads|remotes/[^/]+)/', '', ref)
        for n in sorted(skills_at(pin, ref) - set(known) - set(found)):
            found[n] = {'status': 'branch-only', 'branch': short,
                        'commit': git('rev-parse', ref, repo=pin['checkout']).decode().strip()}
    return found


def audit(ledger, pin, read):
    rows = rows_of(ledger) or {}
    errs = [f"{n}: branch-only commit {row['commit'][:12]} is not in this checkout: fetch it, "
            'or record where the skill went'
            for n, row in sorted(rows.items()) if isinstance(row, dict) and row.get('status') == 'branch-only'
            and isinstance(row.get('commit'), str) and FULL.fullmatch(row['commit']) and not present(pin, row['commit'])]
    known = set(rows) | skills_at(pin, pin['commit']) | skills_before(pin)
    errs += [f"{n}: on WizSkills branch {row['branch']} with no ledger row"
             for n, row in sorted(branch_skills(pin, known).items())]
    return errs


def last_seen(pin, name):
    path = f'skills/{name}/SKILL.md'
    gone = git('log', '-1', '-m', '--no-renames', '--format=%H', '--diff-filter=D', pin['commit'], '--', path,
               repo=pin['checkout']).decode().split()
    parents = git('rev-parse', f'{gone[0]}^@', repo=pin['checkout']).decode().split() if gone else []
    return next((p for p in parents if has(pin, p, path)), None)


def propose(ledger, pin, read, lst=None):
    rows = rows_of(ledger) or {}
    here, listed = skills_at(pin, pin['commit']), set(shipped(read))
    out = {}
    for n in sorted(here - set(rows)):
        if n in listed:
            out[n] = {'status': 'shipped'}
            continue
        users = [f'skills/{s}/SKILL.md' for s in sorted(listed) if f'skills/{n}/' in (read(f'skills/{s}/SKILL.md') or '')]
        if not users and lst is not None:
            skip = (f'skills/{n}/', '.wizskills/skills/', 'tools/skills-eval/')
            pool = [p for p in lst('skills/') if not p.startswith(f'skills/{n}/')]
            pool += [p for p in lst('') if not p.startswith(('skills/', *skip))]
            users = [p for p in pool if f'skills/{n}/' in (read(p) or '')]
        out[n] = {'status': 'observed-used', 'used_by': next(iter(users), None)}
    for n in sorted(skills_before(pin) - here - set(rows)):
        out[n] = {'status': 'historical-only', 'last_seen': last_seen(pin, n)}
    out.update(branch_skills(pin, set(rows) | here | skills_before(pin)))
    return out


def earlier_rows(rev, host=None):
    host = REPO if host is None else host
    at = resolve_rev(rev, host)
    path = LEDGER.relative_to(HERE.parent.parent).as_posix()
    names = set()
    for c in git('log', '--format=%H', at, '--', path, repo=host).decode().split():
        try:
            rows = rows_of(json.loads(git('show', f'{c}:{path}', repo=host)))
        except (subprocess.CalledProcessError, ValueError):
            continue
        names |= set(rows or {})
    return names


def load_ledger():
    try:
        return json.loads(LEDGER.read_text())
    except (OSError, ValueError):
        return None


def referenced(all_cases=None):
    all_cases = C.load_all() if all_cases is None else all_cases
    names = {s for c in all_cases if isinstance(c, dict) for s in c.get('skills') or [] if isinstance(s, str)}
    names |= set(T.load_map(HERE / 'required-text.json'))
    return names | set(json.loads((HERE / 'provenance.json').read_text()).get('not_applicable', {}))


def ledger_coverage(ledger, pin, read, all_cases, na):
    rows = rows_of(ledger) or {}
    here = skills_at(pin, pin['commit'])
    names = set(rows) | here | skills_before(pin)
    names |= {s for c in all_cases for s in c.get('skills') or [] if isinstance(s, str)}
    out = {}
    for n in sorted(names):
        row = rows.get(n) if isinstance(rows.get(n), dict) else {}
        cases = {k: sorted(c['id'] for c in all_cases if n in (c.get('skills') or []) and c.get('category') == k)
                 for k in sorted(C.CATEGORIES)}
        live = row.get('status') in ('shipped', 'observed-used') or (not row and n in here)
        missing = sorted(([] if cases['workflow'] else ['workflow'])
                         + [k for k in ('approval', 'privacy', 'failure')
                            if not cases[k] and not (na.get(n) or {}).get(k)]) if live else []
        out[n] = dict(row, status=row.get('status'), cases=cases, missing=missing)
    return out


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def code_hash():
    h = hashlib.sha256()
    for n in CODE:
        h.update(n.encode() + b'\0' + (HERE / n).read_bytes())
    return h.hexdigest()


def shipped(read):
    text = read('.wizskills/' + PLUGIN)
    if text is None:
        raise Refusal(NO_PIN)
    return parse_plugin(text)


def observed_used(ledger, pin, read):
    rows = rows_of(ledger) or {}
    here, listed = skills_at(pin, pin['commit']), set(shipped(read))
    return [n for n, row in sorted(rows.items())
            if isinstance(row, dict) and row.get('status') == 'observed-used'
            and n in here and n not in listed
            and isinstance(row.get('used_by'), str) and f'skills/{n}/' in (read(row['used_by']) or '')]


def load_cases(folder=HERE / 'cases'):
    out, errs = [], []
    for p in sorted(Path(folder).glob('*.json')):
        try:
            out.append((p.name, json.loads(p.read_text())))
        except ValueError as e:
            errs.append(f'{p.name}: {e}')
    return out, errs


def coverage(all_cases, skills):
    out = {s: {k: [] for k in sorted(C.CATEGORIES)} for s in skills}
    for c in all_cases:
        for s in c['skills']:
            if s in out:
                out[s][c['category']].append(c['id'])
    return out


def check(read, lst, pin, earlier=frozenset(), folder=HERE / 'cases'):
    skills = shipped(read)
    ledger = load_ledger()
    live = sorted(set(skills) | set(observed_used(ledger, pin, read)))
    schema_text = read('contracts/decisions.v1.schema.json')
    if schema_text is None:
        raise Refusal('host snapshot has no contracts/decisions.v1.schema.json')
    schema = json.loads(schema_text)
    loaded, errs = load_cases(folder)
    all_cases = []
    for name, c in loaded:
        all_cases.append(c)
        errs += C.problems(c, live, name)
    ids = [c.get('id') for c in all_cases]
    if len(ids) != len(set(ids)):
        errs.append('duplicate case ids')
    for c in all_cases:
        if C.problems(c, live):
            continue
        for kind in ('pass', 'fail'):
            for j, ctl in enumerate(c['controls'][kind]):
                ok, reasons, details = S.score(c, C.control_transcript(c, ctl), schema)
                if kind == 'pass' and not ok:
                    errs.append(f"{c['id']}: pass control {j} fails: {reasons} {details}")
                if kind == 'fail' and (ok or ctl['reason'] not in reasons):
                    errs.append(f"{c['id']}: fail control {j} gives {reasons}, wants {ctl['reason']}")
    cov = coverage(all_cases, live)
    prov = json.loads((HERE / 'provenance.json').read_text())
    na = prov.get('not_applicable', {})
    for s, cats in cov.items():
        if not cats['workflow']:
            errs.append(f'{s}: no workflow case')
        for k in ('approval', 'privacy', 'failure'):
            reason = (na.get(s) or {}).get(k)
            if not cats[k] and not (isinstance(reason, str) and reason.strip()):
                errs.append(f'{s}: no {k} case and no not-applicable reason')
            if cats[k] and reason:
                errs.append(f'{s}: {k} is covered and also listed not applicable')
    if sorted(prov['cases']) != sorted(ids):
        errs.append(f"provenance cases {sorted(set(prov['cases']) ^ set(ids))} do not match the case files")
    for cid, src in prov['cases'].items():
        if cid.startswith('i') and cid[1:2].isdigit():
            if not src.get('links') or not all(l.startswith('https://github.com/') for l in src['links']):
                errs.append(f'{cid}: an incident needs its GitHub links')
        elif not src.get('rule'):
            errs.append(f'{cid}: a rule case needs its skill file and line')
    incidents = [c for c in all_cases if c['category'] == 'incident']
    if len(incidents) < 5:
        errs.append(f'{len(incidents)} incident cases; the five seeds are required')
    errs += T.map_problems(T.load_map(HERE / 'required-text.json'), skills, read, lst)
    errs += ledger_problems(ledger, pin, read, referenced(all_cases), earlier)
    return errs, all_cases, cov


def pinned_snapshot(a):
    pin = pin_from(a)
    return pin, snapshot(a.rev, pin)


def cmd_check(a):
    pin, (read, lst) = pinned_snapshot(a)
    errs, all_cases, _ = check(read, lst, pin, earlier_rows(a.rev))
    for e in errs:
        print('FAIL', e)
    print(f"{'PASS' if not errs else 'FAIL'}: {len(all_cases)} cases, {len(errs)} problems "
          f"(WizSkills {pin['commit'][:12]})")
    return 0 if not errs else 1


def cmd_coverage(a):
    pin, (read, _) = pinned_snapshot(a)
    all_cases = [c for _, c in load_cases()[0]]
    ledger = load_ledger()
    na = json.loads((HERE / 'provenance.json').read_text()).get('not_applicable', {})
    print(json.dumps(ledger_coverage(ledger, pin, read, all_cases, na), indent=1))
    errs = ledger_problems(ledger, pin, read, referenced(all_cases), earlier_rows(a.rev))
    for e in errs:
        print('FAIL', e, file=sys.stderr)
    return 0 if not errs else 1


def cmd_ledger(a):
    pin, (read, lst) = pinned_snapshot(a)
    ledger = load_ledger()
    if a.propose:
        print(json.dumps(propose(ledger, pin, read, lst), indent=1, sort_keys=True))
        return 0
    errs = ledger_problems(ledger, pin, read, referenced(), earlier_rows(a.rev)) + audit(ledger, pin, read)
    for e in errs:
        print('FAIL', e)
    rows = rows_of(ledger) or {}
    counts = {k: sum(1 for r in rows.values() if isinstance(r, dict) and r.get('status') == k) for k in sorted(ROW_KEYS)}
    print(f"{'PASS' if not errs else 'FAIL'}: {len(rows)} rows {counts}, {len(errs)} problems "
          f"(WizSkills {pin['commit'][:12]})")
    return 0 if not errs else 1


def _key(a, settings=None):
    if settings is None:
        settings = json.loads((HERE / 'settings.json').read_text())
    if settings.get('provider') == 'hermes':
        problem = driver.hermes_login_problem(settings)
        if problem:
            sys.exit(f'Hermes runs are recorded as not run: {problem}')
        return None
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key and a.env_file and Path(a.env_file).exists():
        for line in Path(a.env_file).read_text().splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
    if not key:
        sys.exit('no OPENROUTER_API_KEY: paid runs are recorded as not run (contract.md, section 6)')
    return key


def cmd_run(a):
    settings = json.loads((HERE / 'settings.json').read_text())
    pin, snap = pinned_snapshot(a)
    errs, all_cases, _ = check(*snap, pin, earlier_rows(a.rev))
    if errs:
        sys.exit(f'refusing to run: eval.py check has {len(errs)} problems')
    _key(a, settings)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lock = os.open(out, os.O_RDONLY)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('results folder is already running; refusing concurrent spend')
        return run_locked(a, settings, snap, all_cases, out, pin)
    finally:
        os.close(lock)


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        f.write(json.dumps(value, indent=1) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_locked(a, settings, snap, all_cases, out, pin):
    manifest = {'schema': 'openwiz.skills-eval.results.v1', 'settings': settings, 'settings_hash': sha(settings),
                'cases_hash': C.cases_hash(), 'revision': revision(a.rev), 'wizskills': wizskills_revision(pin),
                'code_hash': code_hash(), 'cases': [c['id'] for c in all_cases], 'repeats': settings['repeats']}
    mf = out / 'manifest.json'
    if mf.exists():
        old = json.loads(mf.read_text())
        errs = manifest_problems(old)
        for k in ('settings_hash', 'cases_hash', 'revision', 'wizskills', 'code_hash', 'cases', 'repeats'):
            if old.get(k) != manifest[k]:
                errs.append(f'{k} differs')
        if errs:
            sys.exit(f"refusing to resume {mf}: {'; '.join(errs)}; start a new results set")
    else:
        write_json(mf, manifest)
    only = set(a.case or [])
    for rep in range(1, settings['repeats'] + 1):
        for c in all_cases:
            if only and c['id'] not in only:
                continue
            f = out / f"{c['id']}.r{rep}.json"
            if f.exists():
                continue
            spent = sum(json.loads(p.read_text()).get('cost_usd', 0) for p in out.glob('*.r*.json'))
            post = driver.http_post(_key(a, settings), settings.get('provider', settings['api_version']))
            t = driver.run_case(c, settings, snap, post, rep, budget_usd=settings['spend_cap_usd'] - spent,
                                checkpoint=lambda interim: write_json(f, interim))
            write_json(f, t)
            print(f"{c['id']} r{rep}: stop={t['stop']} turns={t['turns']} ${t['cost_usd']:.3f}", flush=True)
            if t['stop'] == 'cap':
                print(f"spend cap ${settings['spend_cap_usd']} reached (${spent + t['cost_usd']:.2f}); this run is kept as incomplete; stopping")
                return 3
    return 0


def manifest_problems(man):
    errs = []
    if not isinstance(man, dict):
        return ['the manifest is not an object']
    settings, ids = man.get('settings'), sorted(c['id'] for c in C.load_all())
    if not isinstance(settings, dict) or sha(settings) != man.get('settings_hash'):
        errs.append('the settings do not match their recorded hash')
    rep = man.get('repeats')
    if type(rep) is not int or rep < 1 or not isinstance(settings, dict) or rep != settings.get('repeats'):
        errs.append('repeats must be a positive integer equal to the settings\' repeats')
    if not isinstance(man.get('cases'), list) or sorted(man['cases']) != ids:
        errs.append('the case list is not exactly the current cases, each once')
    if man.get('cases_hash') != C.cases_hash() or man.get('code_hash') != code_hash():
        errs.append('the cases or the eval code changed since this set ran: score it at its own commit, or take a fresh baseline')
    if not isinstance(man.get('revision'), dict) or not man['revision'].get('commit'):
        errs.append('no revision')
    pin = man.get('wizskills')
    if (not isinstance(pin, dict) or not isinstance(pin.get('commit'), str) or not FULL.fullmatch(pin['commit'])
            or not isinstance(pin.get('tree'), str) or not FULL.fullmatch(pin['tree'])):
        errs.append('no WizSkills pin: this set ran before the eval read a pinned WizSkills; take a fresh baseline')
    return errs


def score_set(folder):
    folder = Path(folder)
    man = json.loads((folder / 'manifest.json').read_text())
    errs = manifest_problems(man)
    if errs:
        raise ValueError('; '.join(errs))
    try:
        schema_text = snapshot(man['revision']['commit'], None)[0]('contracts/decisions.v1.schema.json')
    except Refusal as err:
        raise ValueError(str(err))
    if schema_text is None:
        raise ValueError('revision snapshot has no contracts/decisions.v1.schema.json')
    schema = json.loads(schema_text)
    by_id = {c['id']: c for c in C.load_all()}
    rows, ok_all = [], True
    for cid in man['cases']:
        for rep in range(1, man['repeats'] + 1):
            f = folder / f'{cid}.r{rep}.json'
            if cid not in by_id:
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'], 'details': ['case file missing']})
                ok_all = False
                continue
            try:
                t = json.loads(f.read_text())
            except (OSError, ValueError):
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'], 'details': ['not run or unreadable']})
                ok_all = False
                continue
            if not isinstance(t, dict) or t.get('case') != cid or type(t.get('repeat')) is not int or t['repeat'] != rep:
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'],
                             'details': ['the transcript names another case or repeat']})
                ok_all = False
                continue
            ok, reasons, details = S.score(by_id[cid], t, schema)
            ok_all &= ok
            rows.append({'case': cid, 'repeat': rep, 'pass': ok, 'reasons': reasons, 'details': details,
                         'cost_usd': t.get('cost_usd'), 'stop': t.get('stop')})
    return {'schema': 'openwiz.skills-eval.score.v1', 'settings_hash': man['settings_hash'],
            'cases_hash': man['cases_hash'], 'revision': man['revision'], 'wizskills': man['wizskills'],
            'code_hash': man['code_hash'],
            'schema_hash': hashlib.sha256(schema_text.encode()).hexdigest(),
            'suite_pass': ok_all, 'runs': len(rows), 'passed': sum(r['pass'] for r in rows),
            'cost_usd': round(sum(r.get('cost_usd') or 0 for r in rows), 9), 'rows': rows}


def cmd_score(a):
    try:
        s = score_set(a.dir)
    except ValueError as err:
        print(f'refused: {err}')
        return 2
    Path(a.dir, 'score.json').write_text(json.dumps(s, indent=1) + '\n')
    print(f"suite {'PASS' if s['suite_pass'] else 'FAIL'}: {s['passed']}/{s['runs']} runs passed, ${s['cost_usd']}")
    return 0 if s['suite_pass'] else 1


def compare(a, b):
    for k in ('settings_hash', 'cases_hash', 'code_hash', 'schema_hash'):
        if a.get(k) is None or a.get(k) != b.get(k):
            raise ValueError(f'{k} differs: not comparable; take a fresh baseline')
    pa = {(r['case'], r['repeat']): r['pass'] for r in a['rows']}
    pb = {(r['case'], r['repeat']): r['pass'] for r in b['rows']}
    return {'before': f"{a['passed']}/{a['runs']}", 'after': f"{b['passed']}/{b['runs']}",
            'fixed': sorted({k[0] for k in pb if pb[k] and not pa.get(k)}),
            'broken': sorted({k[0] for k in pb if not pb[k] and pa.get(k)})}


def cmd_compare(a):
    try:
        r = compare(*(json.loads(Path(x, 'score.json').read_text()) for x in (a.a, a.b)))
    except ValueError as e:
        print(f'refused: {e}')
        return 2
    print(json.dumps(r, indent=1))
    return 0


def cmd_tokens(a):
    settings = json.loads((HERE / 'settings.json').read_text())
    if not a.offline:
        if not a.results:
            sys.exit('DeepSeek tokens need --results DIR: provider usage, not a Claude tokenizer or text estimate')
        r = T.usage_report(a.results)
        Path(a.out).write_text(json.dumps(r, indent=1) + '\n')
        print(f"DeepSeek provider tokens (not Claude tokens): {r['total']}")
        return 0
    pin, (read, lst) = pinned_snapshot(a)
    m = T.load_map(HERE / 'required-text.json')
    errs = T.map_problems(m, shipped(read), read, lst)
    if errs:
        sys.exit('\n'.join(errs))
    count, tok = None, 'none (offline: bytes only, never reported as tokens)'
    r = T.report(m, read, count, tok, revision(a.rev), lst)
    r['wizskills'] = wizskills_revision(pin)
    import datetime
    r['measured_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    Path(a.out).write_text(json.dumps(r, indent=1) + '\n')
    print(f"total required: {r['total_required_tokens']} tokens, {r['total_required_bytes']} bytes ({tok})")
    return 0


def cmd_token_diff(a):
    try:
        r = T.diff(*(json.loads(Path(x).read_text()) for x in (a.before, a.after)))
    except ValueError as e:
        print(f'refused: {e}')
        return 2
    print(json.dumps(r, indent=1))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'coverage', 'ledger', 'run', 'score', 'tokens'):
        q = sub.add_parser(name)
        q.add_argument('--rev', default='HEAD', help='the host commit (default HEAD)')
        q.add_argument('--env-file', default=None, help='a dotenv file holding OPENROUTER_API_KEY')
        if name != 'score':
            q.add_argument('--wizskills', help='a full WizSkills checkout (default $WIZSKILLS_CHECKOUT)')
            q.add_argument('--wizskills-commit', help='the pinned WizSkills commit, 40 characters (default $WIZSKILLS_COMMIT)')
        if name == 'ledger':
            q.add_argument('--propose', action='store_true', help='print rows for every skill the ledger lacks')
        if name == 'run':
            q.add_argument('--out', required=True)
            q.add_argument('--case', action='append', help='only this case (repeatable)')
        if name == 'score':
            q.add_argument('dir')
        if name == 'tokens':
            q.add_argument('--out', required=True)
            q.add_argument('--offline', action='store_true')
            q.add_argument('--results', help='results folder whose provider usage is reported; makes no API call')
    q = sub.add_parser('compare')
    q.add_argument('a')
    q.add_argument('b')
    q = sub.add_parser('token-diff')
    q.add_argument('before')
    q.add_argument('after')
    a = p.parse_args(argv)
    try:
        return {'check': cmd_check, 'coverage': cmd_coverage, 'ledger': cmd_ledger, 'run': cmd_run,
                'score': cmd_score, 'compare': cmd_compare, 'tokens': cmd_tokens, 'token-diff': cmd_token_diff}[a.cmd](a)
    except Refusal as err:
        print(f'refused: {err}')
        return 2


if __name__ == '__main__':
    sys.exit(main())
