#!/usr/bin/env python3
"""One explicit local War room preparation tick. No schedule or live reads."""
import argparse
import fcntl
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import history
import page
import sources
import suite


def tick(at, history_root, page_path, read_providers):
    """Injected virtual clock and source seam. Call once, then exit.

    Duplicate ticks don't sample again. Out-of-order samples are retained but
    the page always renders the latest saved sample. A failed page write can be
    repaired by repeating the same tick without rewriting or recollecting it.
    """
    now = suite._time(at)
    sample_at = now.replace(minute=now.minute // 5 * 5, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    records = history.read_all(history_root)
    saved = next((r for r in records if r['sample_at'] == sample_at), None)
    if saved is None:
        # Never carry evidence from the future into an older tick.
        previous = next((r for r in reversed(records) if r['sample_at'] < sample_at), None)
        providers = read_providers(at, previous)
        saved = suite.compose(sample_at, providers, assembled_at=at)
        history.save(history_root, saved)
    target = Path(page_path).resolve()
    suite.require(target.suffix == '.html', 'page must be a separate HTML file')
    suite.require(target.parent.resolve() != (Path(history_root) / 'samples').resolve(), 'page cannot be a sample')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = target.with_name('.' + target.name + '.lock')
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
    # Keep the lock inode across invocations. Unlinking it would let another
    # process create a different lock while an existing holder is publishing.
    with os.fdopen(lock_fd, 'a') as publication_lock:
        fcntl.flock(publication_lock.fileno(), fcntl.LOCK_EX)
        latest = history.latest(history_root)
        html = page.render(latest)
        fd, name = tempfile.mkstemp(prefix='.page-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(html)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--at', required=True, help='explicit UTC tick time; no wall clock is read')
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--selection', required=True, type=Path)
    parser.add_argument('--history', required=True, type=Path)
    parser.add_argument('--page', required=True, type=Path)
    args = parser.parse_args()
    try:
        selection = suite._decode(args.selection.read_text(encoding='utf-8'))
        tick(args.at, args.history, args.page,
             lambda at, previous: sources.select(args.source_root, selection, at, previous))
        print('War room: complete saved sample and private local page prepared; live operation Unverified.')
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError):
        print('War room: preparation refused; prior complete history retained.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
