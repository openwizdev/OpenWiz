"""Harness skills (#1361, contracts/install.v1.md "Harness skills").

Copies the selected, verified build's runtime/skills/ into one canonical folder
under the install root and into each present harness's own skills folder. It
checks every destination before writing anything; it never follows a link,
never touches a skill it didn't put there, and creates nothing for a harness
the user doesn't have. Python 3.9+, standard library only.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import stat

import install as installer

# (id, the harness folder under HOME, its plain name). The copy goes to <folder>/skills.
HARNESSES = (('claude-code', '.claude', 'Claude Code'), ('codex', '.codex', 'Codex'),
             ('cursor', '.cursor', 'Cursor'), ('opencode', '.config/opencode', 'OpenCode'),
             ('grok', '.grok', 'Grok'))
MARK = '.openwiz-skill'
MARKED = re.compile(rb'openwiz\.skill-copy\.v1\n[0-9a-f]{40}\n')  # mark()'s bytes for a verified source


def mark(source):
    return f'openwiz.skill-copy.v1\n{source}\n'.encode()


def owned_dir(path):
    """True for a real directory this user owns; False when nothing is there.
    Anything else (a link, a file, another owner) refuses."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    installer.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(),
                      f'{path} is a link or not your folder; nothing was changed')
    return True


def check(folder, names):
    """A skills folder may take these skills: no link on the way, and every
    same-named skill, staging or backup folder already there is an OpenWiz copy."""
    installer.path_guard(folder)
    if not owned_dir(folder):
        return
    for name in names:
        target = folder / name
        installer.require(ours(target), f'{target} is not an OpenWiz copy; nothing was changed')
        for path in leftovers(folder, name):
            try:
                clear = ours(path)
            except installer.Refused:
                clear = False
            installer.require(clear, f'{path} is in the way and OpenWiz did not make it; nothing was changed. '
                                     'Look inside it, and if it holds nothing you want, remove it and run this '
                                     f'again: rm -rf -- {shlex.quote(str(path))}')


def leftovers(folder, name):
    """The fixed staging and backup paths an interrupted run may leave behind."""
    return folder / f'.openwiz-stage-{name}', folder / f'.openwiz-old-{name}'


def ours(path):
    """True when nothing is there or it is an OpenWiz copy: a real folder of
    this user's holding the copy mark exactly as mark() writes it, which every
    staging folder gets first. A same-named file with other text proves nothing."""
    if not owned_dir(path):
        return True
    try:  # never through a link, and never waiting on a pipe
        fd = os.open(path / MARK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        text = os.read(fd, 64) if stat.S_ISREG(os.fstat(fd).st_mode) else b''  # one byte past the 63-byte mark
    finally:
        os.close(fd)
    return MARKED.fullmatch(text) is not None


def place(folder, skills, names, source):
    """Copy each skill through a staging folder, then swap it in."""
    folder.mkdir(mode=0o700, exist_ok=True)
    for name in names:
        (stage, old), target = leftovers(folder, name), folder / name
        for leftover in (stage, old):
            if owned_dir(leftover):
                shutil.rmtree(leftover)
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
        if owned_dir(old):
            shutil.rmtree(old)


def install_skills(build, value, root, home, codex_home=None):
    """The step's result and exit code (0 done, 5 refused with nothing changed)."""
    skills = build / 'runtime/skills'
    installer.private(skills)
    names = sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.is_symlink())
    installer.require(names, 'the selected build ships no skills')
    canonical = Path(root) / 'skills'
    rows, folders = [], [canonical]
    for harness, relative, plain in HARNESSES:
        base = Path(codex_home) if harness == 'codex' and codex_home else Path(home) / relative
        row = {'id': harness, 'path': str(base / 'skills')}
        try:
            installer.require(base.is_absolute(), f'{base} is not an absolute folder')
            installer.path_guard(base.parent)
            present = owned_dir(base)
            if present:
                check(base / 'skills', names)
                folders.append(base / 'skills')
            row.update(state='installed' if present else 'absent',
                       next=f'{plain} finds these skills next time it starts.' if present else
                       f'{plain} is not set up here ({base} is missing); install it, then run this again.')
        except installer.Refused as refusal:
            row.update(state='refused', next=str(refusal))
        rows.append(row)
    result = {'schema': 'openwiz.skills-install.v1', 'version': value['version'], 'source': value['source'],
              'canonical': str(canonical), 'skills': names, 'harnesses': rows}
    reason = 'A destination is not safe to write; nothing was changed.'
    try:
        check(canonical, names)
    except installer.Refused as refusal:
        reason = str(refusal)
    else:
        if not any(row['state'] == 'refused' for row in rows):
            reason = None
    if reason:
        return dict(result, outcome='refused', reason=reason), 5
    for folder in folders:
        place(folder, skills, names, value['source'])
    return dict(result, outcome='installed',
                reason='Copied the verified build\'s skills; absent harnesses were left alone.'), 0
