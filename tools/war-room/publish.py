#!/usr/bin/env python3
"""The War room page (WR9): one tick, drawn and published to the branch `war-room`.

  python3 -I publish.py publish --remote URL --at UTC [--source-root DIR --selection FILE]
  python3 -I publish.py collect --remote URL --at UTC [--source-root DIR --selection FILE]
  python3 -I publish.py preview --out DIR --at UTC [--source-root DIR --selection FILE]

Like the board: the branch's saved samples are carried forward, WR2's tick
(main.tick) saves at most one new sample and renders the latest, chromium
draws it twice (the page, and one 400 px column for a phone), a privacy scan
reads every file, and only `refs/heads/war-room` is pushed. A failed read,
render or scan publishes nothing, so the branch keeps its last good state and
time. `collect` is the five-minute tick alone: it adds only the new sample.
A selected artifact that cannot be read refuses the run. publish.sh runs the tests first. With no selection every bench stays
Unknown with its prerequisite. The caller authenticates git.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import main  # noqa: E402
import page  # noqa: E402
import sources  # noqa: E402
import suite  # noqa: E402

BRANCH = 'war-room'
PICTURES = ('war-room.png', 'war-room-phone.png')
SAMPLE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z\.json')
PNG = b'\x89PNG\r\n\x1a\n'
WIDTH, PHONE_WIDTH = 1200, 400
# Device px: the drawn picture's height (CSS height times scale). A full gathered page is over
# 20,000 CSS px; headless chromium drew and painted 45,626 device px whole (#2432 R1), so this
# bound leaves room and still refuses a runaway page.
MAX_HEIGHT = 65000
# #2565: headless chromium's default tile memory left the lower part of a tall, dense page
# unpainted (blank from about 46,700 px at 1200 wide), so the screenshot gets enough to paint
# every tile of a picture within MAX_HEIGHT.
TILE_MEMORY = '--force-gpu-mem-available-mb=4096'
# The same credential/id forms sources.safe_record refuses inside a record.
TOKEN = re.compile(r'(?i)(?:\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}|authorization\s*:|bearer\s+'
                   r'|-----BEGIN .*PRIVATE KEY|\bthr_[A-Za-z0-9_-]+)')
# A picture has no links to follow, and a closed <details> would hide the bench inventory.
# #2565: each value's card keeps what tells it from a card with the same label (its window,
# freshness, statistic and dimensions); its provenance, interval, prerequisites and evidence links
# stay in its published sample. The full gathered page was 57,625 CSS px tall with them, far past
# MAX_HEIGHT on the phone picture.
DRAW_CSS = 'nav,.metric .source,.metric .interval,.metric .prerequisite,.metric .links{display:none}'
# One column a phone reads at a glance: the same content, tighter.
PHONE_CSS = ('body{font-size:14px;line-height:1.35}main{padding:14px}h1{font-size:26px}'
             'h2{font-size:19px;margin:22px 0 6px}h3{font-size:15px;margin:0 0 4px}'
             'article,.provider{padding:10px;margin:8px 0}.metric strong{font-size:20px}'
             '.detail{font-size:11px;margin:2px 0;line-height:1.3}header p{margin:6px 0}')


class Fail(Exception):
    pass


def git(work, *args, ok=(0,)):
    out = subprocess.run(['git', '-C', str(work), *args], capture_output=True, text=True)
    if out.returncode not in ok:
        # Never echo an auth-bearing remote URL or a credential helper's output.
        raise Fail('git %s failed (exit %d)' % (args[0], out.returncode))
    return out


def chromium():
    for name in ('chromium', 'chromium-browser', 'google-chrome'):
        found = shutil.which(name)
        if found:
            return found
    raise Fail('no chromium to draw the picture')


def drawable(html, phone):
    """The page as drawn: no refresh, the inventory open, a height probe allowed."""
    edits = [('<meta http-equiv="refresh" content="300">', ''),
             ("default-src 'none';", "default-src 'none'; script-src 'unsafe-inline';"),
             ('<details>', '<details open>'),
             ('</style>', DRAW_CSS + (PHONE_CSS if phone else '') + '</style>'),
             ('</body>', '<script>onload=()=>document.body.dataset.h=document.documentElement.scrollHeight</script></body>')]
    for old, new in edits:
        if html.count(old) != 1:
            raise Fail('the page changed shape')
        html = html.replace(old, new)
    return html


def draw(html, png, width, scale=1):
    with tempfile.TemporaryDirectory(prefix='war-room-draw-') as d:
        path = os.path.join(d, 'page.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        base = [chromium(), '--headless=new', '--no-sandbox', '--disable-gpu', '--user-data-dir=' + os.path.join(d, 'chr'),
                '--hide-scrollbars']
        try:
            dom = subprocess.run(base + ['--window-size=%d,800' % width, '--dump-dom', 'file://' + path],
                                 check=True, capture_output=True, text=True, timeout=90).stdout
            found = re.search(r'data-h="([0-9]+)"', dom)
            height = int(found.group(1)) if found else 0
            if height <= 0:
                raise Fail('chromium measured no picture')
            if height * scale > MAX_HEIGHT:
                raise Fail('the page is too tall to draw')
            subprocess.run(base + [TILE_MEMORY, '--window-size=%d,%d' % (width, height), '--force-device-scale-factor=%d' % scale,
                                   '--screenshot=' + os.path.abspath(png), 'file://' + path],
                           check=True, capture_output=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as e:
            raise Fail('chromium did not draw the picture: %s' % type(e).__name__)
    with open(png, 'rb') as f:
        if f.read(8) != PNG:
            raise Fail('chromium wrote no picture')


def readme(record, saved, at):
    rows = []
    for provider in record['providers']:
        metrics = provider['metrics']
        measured = sum(m['value'] is not None for m in metrics)
        rows.append('| %s | %s | %d of %d |' % (page.NAMES[provider['slot']], provider['state'], measured, len(metrics)))
    return '\n'.join([
        '# War room', '',
        '**Last good render:** %s (UTC), sample %s, %d saved samples.' % (at, record['sample_at'], saved), '',
        'Published by `.github/workflows/war-room.yml` on `main`; a failed test, read or render publishes nothing, '
        'so this page keeps its last good state and time. Live sources, five-minute operation and complete history '
        'remain Unverified.', '',
        # A phone gets the one-column picture; GitHub keeps <picture>'s media query.
        '<picture><source media="(max-width: 700px)" srcset="war-room-phone.png">'
        '<img alt="The War room" src="war-room.png"></picture>', '',
        'On a phone, [the one-column picture](war-room-phone.png).', '',
        '## Benches', '',
        'Every bench in the saved sample, with its state and how many of its values are measured. '
        'Unknown is never zero; the picture names each bench\'s prerequisite, and each value\'s '
        'prerequisites, provenance and evidence are in its saved sample.', '',
        '| Bench | State | Measured |', '| --- | --- | --- |', *rows, '',
        'Saved samples are in `samples/`, one per five-minute boundary sampled; a boundary not sampled stays absent.', ''])


def text_scan(text, checker):
    checker.text(text, 'published')
    if TOKEN.search(text):
        checker.findings += 1


def scan(tree, page_html):
    """Every published file, and the page the pictures are drawn from, or Fail."""
    base = sources.native('tools/privacy-check/check.py')

    class Quiet(base.Checker):
        def refuse(self, *args, **kwargs):
            self.findings += 1
    checker = Quiet()
    tree = Path(tree)
    text_scan(page_html, checker)
    for path in sorted(tree.rglob('*')):
        name = path.relative_to(tree).as_posix()
        if path.is_symlink() or not (path.is_file() or name == 'samples'):
            raise Fail('unexpected file on the page')
        if name == 'samples':
            continue
        if name in PICTURES:
            if path.read_bytes()[:8] != PNG:
                raise Fail('a picture is not a picture')
        elif name == 'README.md':
            text_scan(path.read_text(encoding='utf-8'), checker)
        elif name.startswith('samples/') and SAMPLE.fullmatch(name[8:]):
            text_scan(path.read_text(encoding='utf-8'), checker)
            try:
                sources.safe_record(suite.load(path))
            except (ValueError, OSError):
                checker.findings += 1
        else:
            raise Fail('unexpected file on the page')
    if checker.findings:
        raise Fail('the privacy scan refused a published file')


def selection_reader(source_root, selection):
    if selection is None:
        chosen, root = [], None  # nothing selected: nothing is read
    else:
        chosen, root = suite._decode(Path(selection).read_text(encoding='utf-8')), source_root

    def read(at, previous):
        providers = sources.select(root, chosen, at, previous)
        # WR2 keeps a failed artifact as partial evidence; a publication refuses it instead,
        # so the branch keeps its last good state and time.
        for s, p in zip(chosen, providers):
            if p == sources._failed(s['slot'], previous, at):
                raise Fail('a selected source could not be read')
        return providers
    return read


def tick(history, at, read):
    """One WR2 tick on `history`. The page's path."""
    page_path = Path(history).parent / 'page' / 'page.html'
    main.tick(at, history, page_path, read)
    return page_path


def render(out, history, at, read):
    """One tick on `history`, then README.md and both pictures in `out`. The page's HTML."""
    page_path = tick(history, at, read)
    record = main.history.latest(history)
    html = page_path.read_text(encoding='utf-8')
    draw(drawable(html, False), os.path.join(out, PICTURES[0]), WIDTH)
    draw(drawable(html, True), os.path.join(out, PICTURES[1]), PHONE_WIDTH, scale=2)
    saved = len(main.history.read_all(history))
    with open(os.path.join(out, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(readme(record, saved, at))
    return html


def publish(remote, at, read, draw_page=True):
    """One tick and, with draw_page, the README and pictures; push only war-room.
    Without draw_page (the five-minute collection) only a new sample is added."""
    with tempfile.TemporaryDirectory(prefix='war-room-') as tmp:
        work, history = Path(tmp) / 'branch', Path(tmp) / 'private' / 'history'
        work.mkdir()
        git(work, 'init', '-q')
        git(work, 'config', 'user.name', 'The War room')
        git(work, 'config', 'user.email', 'war-room@users.noreply.github.com')
        git(work, 'remote', 'add', 'origin', remote)
        exists = git(work, 'ls-remote', '--exit-code', '--heads', 'origin', 'refs/heads/' + BRANCH, ok=(0, 2)).returncode == 0
        names = []
        if exists:
            git(work, 'fetch', '-q', 'origin', 'refs/heads/' + BRANCH)
            # Before anything is written: only plain files with the page's own names, never a link.
            for entry in git(work, 'ls-tree', '-r', '-z', 'FETCH_HEAD').stdout.split('\0'):
                if not entry:
                    continue
                meta, name = entry.split('\t', 1)
                if meta.split()[:2] != ['100644', 'blob'] or not (
                        name in ('README.md', *PICTURES) or (name.startswith('samples/') and SAMPLE.fullmatch(name[8:]))):
                    raise Fail('the branch holds an unexpected file')
                names.append(name)
            # A saved sample is immutable: changed, removed or renamed in any commit, merges
            # included (-m compares a merge with each parent), and nothing is published on top.
            if git(work, 'log', '-m', '--format=', '--name-only', '--diff-filter=DMRT', 'FETCH_HEAD', '--', 'samples').stdout.strip():
                raise Fail('a saved sample was rewritten on the branch')
            git(work, 'checkout', '-q', '-B', BRANCH, 'FETCH_HEAD')
        else:
            git(work, 'checkout', '-q', '--orphan', BRANCH)
        # Carry the saved samples forward, byte for byte, into a private history.
        samples = history / 'samples'
        samples.mkdir(parents=True, mode=0o700)
        before = {}
        for name in names:
            if name.startswith('samples/'):
                path = work / name
                if path.is_symlink() or not path.is_file():
                    raise Fail('the branch holds an unexpected file')
                before[path.name] = path.read_bytes()
                (samples / path.name).write_bytes(before[path.name])
        if draw_page:
            html = render(work, history, at, read)
        else:
            html = tick(history, at, read).read_text(encoding='utf-8')
        (work / 'samples').mkdir(exist_ok=True)
        for path in sorted(samples.glob('*.json')):
            data = path.read_bytes()
            if path.name in before:
                if before[path.name] != data:
                    raise Fail('a saved sample changed')
            else:
                (work / 'samples' / path.name).write_bytes(data)
        scan_tree = Path(tmp) / 'scan'
        shutil.copytree(work, scan_tree, symlinks=True, ignore=shutil.ignore_patterns('.git'))
        scan(scan_tree, html)
        git(work, 'add', '--all')
        status = git(work, 'status', '--porcelain').stdout.splitlines()
        if any(line[3:].startswith('samples/') and not line.startswith('A ') for line in status):
            raise Fail('a saved sample would be rewritten')
        if not draw_page and any(not line[3:].startswith('samples/') for line in status):
            raise Fail('a collection changes only samples')
        if not status:
            return None  # this boundary was already collected
        git(work, 'commit', '-q', '-m', 'Redraw the War room' if draw_page else 'Collect a War room sample')
        if git(work, 'symbolic-ref', '--short', 'HEAD').stdout.strip() != BRANCH:
            raise Fail('refusing to publish outside war-room')
        git(work, 'push', '-q', 'origin', 'HEAD:refs/heads/' + BRANCH)
        return git(work, 'rev-parse', 'HEAD').stdout.strip()


def cli(argv):
    parser = argparse.ArgumentParser(description='The War room page (WR9).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('publish', 'collect', 'preview'):
        p = sub.add_parser(name)
        p.add_argument('--at', required=True, help='explicit UTC run time; no wall clock is read')
        p.add_argument('--source-root', type=Path)
        p.add_argument('--selection', type=Path)
        if name != 'preview':
            p.add_argument('--remote', required=True)
        else:
            p.add_argument('--out', required=True, type=Path)
    a = parser.parse_args(argv)
    try:
        if (a.source_root is None) != (a.selection is None):
            raise Fail('--source-root and --selection go together')
        suite._time(a.at)
        read = selection_reader(a.source_root, a.selection)
        if a.cmd == 'publish':
            print('published war-room at %s' % publish(a.remote, a.at, read))
        elif a.cmd == 'collect':
            head = publish(a.remote, a.at, read, draw_page=False)
            print('collected into war-room at %s' % head if head else 'boundary already collected')
        else:
            a.out.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='war-room-preview-') as tmp:
                html = render(a.out, Path(tmp) / 'history', a.at, read)
                scan(a.out, html)
            print((a.out / 'README.md').read_text(encoding='utf-8'))
    except (Fail, ValueError, OSError, UnicodeError, RecursionError) as e:
        # Only the reason class: a source error can carry a private value.
        print('war-room: %s; nothing published' % (e if isinstance(e, Fail) else type(e).__name__), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]))
