#!/usr/bin/env python3
"""Publish validated aggregate points to the hardcoded ci-benchmarks branch.

No main checkout changes. No raw GitHub records, runner names or run/PR IDs.
The caller authenticates git (in Actions: GH_TOKEN and gh auth setup-git).
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bench', HERE / 'bench.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
BRANCH = 'ci-benchmarks'


def git(repo, *args, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if result.returncode not in allowed:
        # Do not echo auth-bearing remote URLs or credential-helper output.
        raise bench.Fail(f'git {args[0]} failed (exit {result.returncode}); publication stopped')
    return result


def publish(source, repo, baseline):
    points = [bench.read_point(item) for item in source]
    base = bench.read_point(baseline)
    remote = git(repo, 'remote', 'get-url', 'origin').stdout.strip()
    with tempfile.TemporaryDirectory(prefix='ci-bench-publish-') as temp:
        work = Path(temp)
        git(work, 'init', '-q')
        git(work, 'config', 'user.name', 'CI benchmarks')
        git(work, 'config', 'user.email', 'ci-benchmarks@users.noreply.github.com')
        git(work, 'remote', 'add', 'origin', remote)
        exists = git(work, 'ls-remote', '--exit-code', '--heads', 'origin', f'refs/heads/{BRANCH}', allowed=(0, 2))
        if exists.returncode == 0:
            git(work, 'fetch', '-q', 'origin', f'refs/heads/{BRANCH}')
            git(work, 'checkout', '-q', '-b', BRANCH, 'FETCH_HEAD')
        else:
            git(work, 'checkout', '-q', '--orphan', BRANCH)
        # A data branch holds only this known aggregate format. Refuse a
        # surprising file or symlink before it can influence writes.
        top = {'README.md', 'bench.md', 'prs-per-hour.svg', 'robot-minutes.svg', 'time-split.svg', 'minutes-per-pr.svg', 'daily-metrics.svg',
               'factory-throughput.svg', 'factory-reviews.svg', 'factory-main.svg', 'factory-runner-wait.svg',
               'buckets.md', 'buckets-6h.svg', 'buckets-1h.svg',
               'journey-trends.md', 'journey-reviews.svg', 'journey-findings.svg'}
        for path in work.rglob('*'):
            rel = path.relative_to(work)
            if rel.parts[0] == '.git':
                continue
            valid = str(rel) in top or str(rel) == 'baseline/point.json' or (
                len(rel.parts) == 3 and rel.parts[0] == 'windows' and rel.parts[2] == 'point.json'
                and len(rel.parts[1]) == 24 and all(c in '0123456789abcdef' for c in rel.parts[1]))
            if path.is_symlink() or (path.is_file() and not valid):
                raise bench.Fail('ci-benchmarks contains unexpected files; publication stopped')
        targets = [(work/'baseline/point.json', base)]
        for point in points:
            key = hashlib.sha256(json.dumps([point['since'], point['until'], point['label']]).encode()).hexdigest()[:24]
            targets.append((work/'windows'/key/'point.json', point))
        for target, data in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            bench.write(target, json.dumps(data, indent=2, sort_keys=True)+'\n')
        directories = sorted((work/'windows').iterdir())
        bench.dashboard(work/'baseline', directories, work)
        git(work, 'add', '--all')
        changed = git(work, 'diff', '--cached', '--quiet', allowed=(0, 1)).returncode
        if not changed:
            print('ci-benchmarks already contains this measurement')
            return
        git(work, 'commit', '-q', '-m', 'Update CI benchmarks')
        if git(work, 'symbolic-ref', '--short', 'HEAD').stdout.strip() != BRANCH:
            raise bench.Fail('refusing publication outside ci-benchmarks')
        if exists.returncode == 0:
            git(work, 'pull', '--rebase', 'origin', BRANCH)
        git(work, 'push', 'origin', 'HEAD:refs/heads/ci-benchmarks')
        head = git(work, 'rev-parse', 'HEAD').stdout.strip()
        print(f'published ci-benchmarks at {head}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, nargs='+', help='one or more measured window directories')
    parser.add_argument('--repo', default=str(bench.ROOT), help='source checkout with origin remote')
    parser.add_argument('--baseline', default=str(bench.BASELINE))
    args = parser.parse_args()
    try:
        publish(args.source, args.repo, args.baseline)
    except (bench.Fail, OSError) as error:
        print(f'publish: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
