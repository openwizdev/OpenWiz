import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import tempfile

import install as installer

HARNESSES = (('claude-code', '.claude', 'Claude Code'), ('codex', '.codex', 'Codex'),
             ('cursor', '.cursor', 'Cursor'), ('opencode', '.config/opencode', 'OpenCode'),
             ('grok', '.grok', 'Grok'))
MARK = '.openwiz-skill'
MARKED = re.compile(rb'openwiz\.skill-copy\.v1\n[0-9a-f]{40}\n')


def mark(source):
    return f'openwiz.skill-copy.v1\n{source}\n'.encode()


def owned_dir(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    installer.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(),
                      f'{path} is a link or not your folder; nothing was changed')
    return True


def row_next(plain, skipped, skill_names, notes):
    skills = sum(1 for item in skipped if item.get('skill') in skill_names)
    folders = len(skipped) - skills
    if not skills and not folders:
        text = f'{plain} finds these skills next time it starts.'
    else:
        parts = []
        if skills:
            parts.append(f'{plain} did not get {skills} skill(s)')
        if folders:
            parts.append(f'{plain} kept {folders} folder(s)')
        text = '; '.join(parts) + '; each one below says why and what to do.'
    if notes:
        text += ' ' + ' '.join(notes)
    return text


def keep_folder(folder, name, plain):
    target = folder / name
    blocked, why = None, None
    try:
        installer.path_guard(folder)
        if not owned_dir(folder):
            return None
        if not ours(target):
            blocked, why = target, 'own'
        else:
            for path in leftovers(folder, name):
                try:
                    clear = ours(path)
                except installer.Refused:
                    clear = False
                if not clear:
                    blocked, why = path, 'leftover'
                    break
    except installer.Refused:
        blocked, why = target, 'link'
    if blocked is None:
        return None
    if why == 'own':
        message = (f'{blocked} is your own folder, not OpenWiz\'s copy, so {plain}\'s OpenWiz skills read yours '
                   f'instead; move or rename it, then run this again.')
    elif why == 'leftover':
        message = (f'{blocked} is in the way and OpenWiz did not make it, so {plain}\'s OpenWiz skills read yours '
                   f'instead. Look inside it, and if it holds nothing you want, remove it and run this again: '
                   f'rm -rf -- {shlex.quote(str(blocked))}')
    else:
        message = (f'{blocked} is a link or not your folder, so {plain}\'s OpenWiz skills read yours instead; '
                   f'move it away, then run this again.')
    return {'skill': name, 'path': str(blocked), 'next': message}


def unexpected_files(target, source):
    if not owned_dir(target) or not ours(target):
        return []
    shipped = {path.relative_to(source).as_posix() for path in source.rglob('*') if path.is_file()}
    extra = []
    for path in sorted(target.rglob('*')):
        if not path.is_file() or path.name == MARK:
            continue
        rel = path.relative_to(target).as_posix()
        if rel not in shipped:
            extra.append(rel)
    return extra


def clash(folder, name, plain):
    target = folder / name
    if not ours(target):
        return (f'{target} is your own {name} skill, not an OpenWiz copy, so {plain} keeps it and does not get '
                f'OpenWiz\'s {name}. To use OpenWiz\'s, move or rename yours, then run this again.')
    for path in leftovers(folder, name):
        try:
            clear = ours(path)
        except installer.Refused:
            clear = False
        if not clear:
            return (f'{path} is in the way and OpenWiz did not make it, so {plain} does not get OpenWiz\'s {name}. '
                    'Look inside it, and if it holds nothing you want, remove it and run this again: '
                    f'rm -rf -- {shlex.quote(str(path))}')
    return None


def check(folder, names, plain):
    installer.path_guard(folder)
    if not owned_dir(folder):
        return []
    skipped = []
    for name in names:
        try:
            reason = clash(folder, name, plain)
        except installer.Refused:
            reason = (f'{folder / name} is a link or not your folder, so {plain} keeps it and does not get '
                      f'OpenWiz\'s {name}. To use OpenWiz\'s, move it away, then run this again.')
        if reason:
            skipped.append({'skill': name, 'path': str(folder / name), 'next': reason})
    return skipped


def leftovers(folder, name):
    return folder / f'.openwiz-stage-{name}', folder / f'.openwiz-old-{name}'


def ours(path):
    if not owned_dir(path):
        return True
    try:
        fd = os.open(path / MARK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        text = os.read(fd, 64) if stat.S_ISREG(os.fstat(fd).st_mode) else b''
    finally:
        os.close(fd)
    return MARKED.fullmatch(text) is not None


def discard(path, plain, name, landed):
    try:
        shutil.rmtree(path)
    except OSError as error:
        done = f'{plain} got OpenWiz\'s {name}, but' if landed else f'{plain} did not get OpenWiz\'s {name}:'
        quoted = shlex.quote(str(path))
        return (f'{done} OpenWiz could not delete {path}, a copy it set aside ({error.strerror}). Delete it '
                f'with chmod -R u+rwx -- {quoted} && rm -rf -- {quoted}, then run this again.')
    return None


def place(folder, skills, name, source, plain):
    folder.mkdir(mode=0o700, exist_ok=True)
    (stage, old), target = leftovers(folder, name), folder / name
    for leftover in (stage, old):
        if owned_dir(leftover):
            trouble = discard(leftover, plain, name, False)
            if trouble:
                return False, trouble
    stage.mkdir(mode=0o700)
    fd = os.open(stage / MARK, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(mark(source))
    for path in sorted((skills / name).rglob('*')):
        if path.is_dir() or path == skills / name / MARK:
            continue
        copy = stage / path.relative_to(skills / name)
        copy.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     stat.S_IMODE(path.lstat().st_mode))
        with os.fdopen(fd, 'wb') as handle:
            handle.write(path.read_bytes())
    if owned_dir(target):
        os.rename(target, old)
    os.rename(stage, target)
    return True, discard(old, plain, name, True) if owned_dir(old) else None


def guard_parent(base, plain):
    try:
        installer.path_guard(base.parent)
    except installer.Refused:
        culprit = next((p for p in (base.parent, *base.parent.parents)
                        if p.is_symlink() or (p.exists() and not p.is_dir())), base.parent)
        raise installer.Refused(f'{culprit} is a link or not a folder, so OpenWiz will not write {plain}\'s skills '
                                f'through it; nothing was changed. Make {culprit} a real folder, or move {base} away '
                                f'if you don\'t use {plain}, then run this again.') from None


def unreadable(path, plain, error):
    culprit = next((p for p in reversed((path, *path.parents)) if not os.access(p, os.X_OK)), path.parent)
    return (f'OpenWiz could not look inside {culprit} ({error.strerror}), so it cannot tell what is in {plain}\'s '
            f'folder; nothing was changed. Give yourself access with chmod u+rx -- {shlex.quote(str(culprit))}, '
            'then run this again.')


def copy(folder, skills, wanted, source, plain):
    placed, notes, cleanup, unwritable = [], [], [], None
    for name in wanted:
        try:
            landed, trouble = place(folder, skills, name, source, plain)
        except (OSError, installer.Refused) as error:
            landed, trouble = False, None
            unwritable = unwritable or (error.strerror if isinstance(error, OSError) and error.strerror
                                        else str(error))
        if landed:
            placed.append(name)
        if trouble:
            (cleanup if landed else notes).append(trouble)
    if unwritable:
        notes.insert(0, f'OpenWiz could not write {folder} ({unwritable}), so {plain} got {len(placed)} of '
                        f'{len(wanted)} skills. Make it writable with chmod u+rwx -- {shlex.quote(str(folder))}, '
                        'then run this again.')
    return placed, ' '.join(notes) or None, ' '.join(cleanup) or None


BESIDE = ('contracts', '.claude-plugin')


def manifest(names):
    return (json.dumps({'name': 'openwiz', 'skills': ['./skills/' + n for n in names]}, indent=2) + '\n').encode()


def beside(base, build, names, source, plain):
    with tempfile.TemporaryDirectory(prefix='openwiz-beside-') as temporary:
        plugin = Path(temporary) / '.claude-plugin'
        plugin.mkdir()
        (plugin / 'plugin.json').write_bytes(manifest(names))
        origins = {'contracts': build / 'runtime', '.claude-plugin': Path(temporary)}
        skipped, notes = [], []
        for name in BESIDE:
            origin = origins[name] / name
            if not origin.is_dir():
                continue
            try:
                found = keep_folder(base, name, plain)
                if found:
                    skipped.append(found)
                    continue
                extra = unexpected_files(base / name, origin)
                landed, trouble = place(base, origins[name], name, source, plain)
                if extra and landed:
                    listed = ', '.join(extra)
                    notes.append(f'{base / name} is OpenWiz\'s marked copy and was replaced whole; it held extra '
                                 f'file(s) that are not in this build: {listed}.')
                if not landed:
                    skipped.append({'skill': name, 'path': str(base / name),
                                    'next': trouble or f'OpenWiz could not write {base / name}, so {plain}\'s '
                                                       f'skills cannot read it. Make {base} writable, then run '
                                                       f'this again.'})
            except (OSError, installer.Refused) as error:
                why = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
                skipped.append({'skill': name, 'path': str(base / name),
                                'next': f'OpenWiz could not write {base / name} ({why}), so {plain}\'s skills cannot '
                                        f'read it. Make {base} writable, then run this again.'})
        return skipped, notes


def install_skills(build, value, root, home, codex_home=None):
    skills = build / 'runtime/skills'
    installer.private(skills)
    names = sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.is_symlink())
    installer.require(names, 'the selected build ships no skills')
    canonical = Path(root) / 'skills'
    rows = []
    for harness, relative, plain in HARNESSES:
        base = Path(codex_home) if harness == 'codex' and codex_home else Path(home) / relative
        row = {'id': harness, 'path': str(base / 'skills')}
        try:
            installer.require(base.is_absolute(), f'{base} is not an absolute folder')
            try:
                present = owned_dir(base)
            except NotADirectoryError:
                present = False
            if not present:
                row.update(state='absent', next=f'{plain} is not set up here ({base} is missing), so it got no '
                                                f'skills; install {plain}, then run this again.')
            else:
                guard_parent(base, plain)
                skipped = check(base / 'skills', names, plain)
                wanted = [n for n in names if n not in {s['skill'] for s in skipped}]
                placed, failed, cleanup = (copy(base / 'skills', skills, wanted, value['source'], plain) if wanted
                                           else ([], None, None))
                failed = ' '.join(filter(None, (failed, cleanup))) or None
                notes = []
                if placed and not failed:
                    folder_skipped, notes = beside(base, build, names, value['source'], plain)
                    skipped += folder_skipped
                row.update(state='installed' if len(placed) == len(names) and not skipped
                           else 'partial' if placed else 'refused',
                           next=failed or row_next(plain, skipped, names, notes))
                if skipped:
                    row['skipped'] = skipped
        except installer.Refused as refusal:
            row.update(state='refused', next=str(refusal))
        except OSError as error:
            row.update(state='refused', next=unreadable(Path(error.filename or base), plain, error))
        rows.append(row)
    result = {'schema': 'openwiz.skills-install.v1', 'version': value['version'], 'source': value['source'],
              'canonical': str(canonical), 'skills': names, 'harnesses': rows}
    if not any(row['state'] in ('installed', 'partial') for row in rows):
        return dict(result, outcome='refused', reason='No agent here took OpenWiz\'s skills (see each row), so '
                                                      'the canonical folder was not written either.'), 5
    whole = all(row['state'] in ('installed', 'absent') for row in rows)
    placed, cleanup, notes = [], None, []
    try:
        skipped = check(canonical, names, 'OpenWiz\'s own skills folder')
        placed, failed, cleanup = copy(canonical, skills, [n for n in names if n not in {s['skill'] for s in skipped}],
                                       value['source'], 'OpenWiz\'s own skills folder')
        if placed and not failed:
            folder_skipped, notes = beside(Path(root), build, names, value['source'], 'OpenWiz\'s own skills folder')
            skipped += folder_skipped
    except installer.Refused as refusal:
        skipped, failed = [], (f'{canonical} is a link or not a folder of yours ({refusal}), so OpenWiz did not '
                               'write its own copy there; the agents above still got their skills. Make it a real '
                               'folder, or move it away, then run this again.')
    except OSError as error:
        skipped, failed = [], unreadable(Path(error.filename or canonical), 'OpenWiz', error)
    if skipped:
        result['canonical_skipped'] = skipped
    if failed:
        result['canonical_refused'] = failed
    if cleanup:
        result['canonical_cleanup'] = cleanup
    whole = whole and len(placed) == len(names) and not skipped
    reason = ('Copied the skills into every agent here.' if whole else
              'Copied the skills where it was safe; the rows say what was skipped and why.')
    if notes:
        reason = reason + ' ' + ' '.join(notes)
    return dict(result, outcome='installed' if whole else 'partial', reason=reason), 0
