#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys

sys.dont_write_bytecode = True

TITLE = 'Daily install check failed'


def gh(args):
    done = subprocess.run(['gh', *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or 'gh failed')
    return done.stdout


def json_values(text):
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, index = decoder.raw_decode(text, index)
        yield value


def open_issues(repo):
    search = 'author:app/github-actions in:title "%s"' % TITLE
    rows = json.loads(gh(['issue', 'list', '--repo', repo, '--state', 'open', '--search', search,
                          '--json', 'number,title']))
    return sorted(row['number'] for row in rows if row.get('title') == TITLE)


def failed_lines(repo, run_id, attempt):
    try:
        text = gh(['api', 'repos/%s/actions/runs/%s/attempts/%s/jobs' % (repo, run_id, attempt), '--paginate'])
        jobs = [job for value in json_values(text) for job in value.get('jobs', [])]
    except (RuntimeError, json.JSONDecodeError, AttributeError):
        return 'the jobs could not be read'
    lines = ['- `%s`: %s' % (job.get('name'), job.get('conclusion'))
             for job in jobs if job.get('name') != 'track' and job.get('conclusion') != 'success']
    return '\n'.join(lines) if lines else 'the jobs could not be read'


def failure_body(tag, failed, run):
    return ('The daily install check of the latest published release (%s) failed.\n\n'
            '%s\n\nRun: %s\n' % (tag or 'unknown', failed, run))


def main(argv):
    parser = argparse.ArgumentParser(description='Track the one daily install-check issue.')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--tag', default='')
    parser.add_argument('--run', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--run-attempt', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--rehearsal', default='')
    parser.add_argument('--linux', default='')
    parser.add_argument('--macos', default='')
    args = parser.parse_args(argv)
    open_numbers = open_issues(args.repo)
    print('release: %s; rehearsal: %s; rehearse-linux: %s; rehearse-macos: %s; open: %s' % (
        args.release, args.rehearsal or 'unknown', args.linux, args.macos,
        ' '.join(str(n) for n in open_numbers) or 'none'))
    if args.release == 'success' and args.rehearsal == 'no':
        print('neutral: %s has no tools/rehearsal/rehearse.py; the tracking issue is left as it is' % args.tag)
        return 0
    if args.release == 'success' and args.linux == 'success' and args.macos == 'success':
        for number in open_numbers:
            gh(['issue', 'comment', str(number), '--repo', args.repo,
                '--body', 'Passed on every target for %s: %s' % (args.tag, args.run)])
            gh(['issue', 'close', str(number), '--repo', args.repo, '--reason', 'completed'])
        return 0
    body = failure_body(args.tag, failed_lines(args.repo, args.run_id, args.run_attempt), args.run)
    if open_numbers:
        gh(['issue', 'comment', str(open_numbers[0]), '--repo', args.repo, '--body', body])
    else:
        gh(['issue', 'create', '--repo', args.repo, '--title', TITLE, '--body', body])
    return 1


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except RuntimeError as exc:
        sys.stderr.write('%s\n' % exc)
        sys.exit(1)
