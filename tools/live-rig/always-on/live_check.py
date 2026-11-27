#!/usr/bin/env python3
import argparse, fcntl, json, os, re, signal, subprocess, sys, tempfile, threading, time, urllib.parse

CHECKS = ('version', 'start', 'wake', 'stop', 'token')
KIT_LINE = re.compile(r'(pass|fail) (%s): (.*)' % '|'.join(CHECKS))
VOLATILE = ((re.compile(r'\brun-[0-9a-f]{12}\b'), 'run-<id>'), (re.compile(r'\bnote \d+'), 'note <n>'),
            (re.compile(r'\bprocess(es)? \d+(, \d+)*'), 'process <pid>'))
DAILY_SECONDS = 23 * 3600
INTERRUPT_GRACE_SECONDS = 60
NEEDED = ('driver', 'checkout', 'repo', 'ticket', 'harness', 'model', 'receipts')


class Rig(Exception):
    pass


def run(cmd, cwd=None, timeout=600):
    try:
        done = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, '', '%s: %s' % (cmd[0], type(e).__name__)


def redact(text):
    home = os.path.expanduser('~')
    return text.replace(home, '~') if len(home) > 1 else text


def last_line(text):
    lines = [x for x in text.strip().splitlines() if x.strip()]
    return redact(lines[-1]) if lines else 'no output'


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise Rig('the config is one JSON object')
    return load_config_dict(cfg)


def load_config_dict(cfg):
    missing = [k for k in NEEDED if k not in cfg]
    if missing:
        raise Rig('the config lacks ' + ', '.join(missing))
    if not re.fullmatch(r'[\w.-]+/[\w.-]+#\d+', cfg['receipts']) or not re.fullmatch(r'[\w.-]+/[\w.-]+',
                                                                                         cfg['repo']):
        raise Rig('repo is owner/name and receipts is owner/name#number')
    if type(cfg['ticket']) is not int or cfg['ticket'] < 1:
        raise Rig('ticket is the number of the throwaway ticket')
    cfg = dict({'tools': [cfg['driver']], 'about': '', 'wait': 900, 'skill': 'build-ticket', 'kit_timeout': 3600,
                'state': '~/.local/state/openwiz-live-rig/' + cfg['driver']}, **cfg)
    return dict(cfg, checkout=os.path.expanduser(cfg['checkout']), state=os.path.expanduser(cfg['state']))


def update(checkout, driver):
    code, out, _ = run(['git', '-C', checkout, 'status', '--porcelain'])
    if code or out.strip():
        raise Rig('the checkout is not a clean git checkout, so the rig did not move it')
    for step in (['fetch', '--quiet', 'origin', 'main'], ['checkout', '--quiet', '--detach', 'FETCH_HEAD']):
        code, _, err = run(['git', '-C', checkout] + step, timeout=300)
        if code:
            raise Rig('git %s failed: %s' % (step[0], last_line(err)))
    head = run(['git', '-C', checkout, 'rev-parse', 'HEAD'])[1].strip()
    commit = run(['git', '-C', checkout, 'log', '-1', '--format=%H %cs %s', '--', 'adapters/' + driver])[1].strip()
    if not commit:
        raise Rig('main has no adapters/%s' % driver)
    return head, commit


def versions(tools):
    found = []
    for tool in tools:
        code, out, err = run([tool, '--version'], timeout=120)
        first = next((x.strip() for x in (out + err).splitlines() if x.strip()), '')
        found.append(redact(first)[:120] if code == 0 and first else '%s: no version (exit %d)' % (tool, code))
    return found


def offline(checkout, driver):
    began = time.monotonic()
    code, out, err = run([sys.executable, '-I', 'adapters/%s/test_driver.py' % driver], cwd=checkout, timeout=1800)
    text = out + err
    summary = re.findall(r'^Ran \d+ tests? in [0-9.]+s$', text, re.M)[-1:] + re.findall(r'^(?:OK|FAILED).*$', text,
                                                                                         re.M)[-1:]
    return {'verdict': 'pass' if code == 0 else 'fail', 'summary': ', '.join(summary) or 'exit %d' % code,
            'took': time.monotonic() - began,
            'tail': '' if code == 0 else redact('\n'.join(text.strip().splitlines()[-20:]))}


def kit(cfg):
    cmd = [sys.executable, '-I', 'kernel/driver-kit/kit.py', '--driver', 'adapters/%s/driver' % cfg['driver'],
           '--repo', cfg['repo'], '--ticket', str(cfg['ticket']), '--harness', cfg['harness'], '--model',
           cfg['model'], '--skill', cfg['skill'], '--wait', str(cfg['wait'])]
    lines, timed_out, began = [], [], time.monotonic()
    with tempfile.TemporaryFile(mode='w+') as err:
        proc = subprocess.Popen(cmd, cwd=cfg['checkout'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=err, text=True, start_new_session=True)

        def signal_kit(send, sig):
            timed_out.append(sig)
            try:
                send(proc.pid, sig)
            except OSError:
                pass
        timers = [threading.Timer(cfg['kit_timeout'], signal_kit, (os.kill, signal.SIGINT)),
                  threading.Timer(cfg['kit_timeout'] + INTERRUPT_GRACE_SECONDS, signal_kit,
                                  (os.killpg, signal.SIGKILL))]
        for t in timers:
            t.start()
        with proc.stdout:
            for raw in proc.stdout:
                lines.append((time.monotonic() - began, raw.rstrip('\n')))
        code = proc.wait()
        for t in timers:
            t.cancel()
        err.seek(0)
        stderr = redact(err.read().strip())
    return {'exit': code, 'lines': lines, 'stderr': stderr, 'took': time.monotonic() - began,
            'timed_out': bool(timed_out)}


def checks(lines):
    found, last = {}, 0.0
    for at, text in lines:
        m = KIT_LINE.fullmatch(text)
        if m:
            found[m.group(2)] = {'verdict': m.group(1), 'what': redact(m.group(3)), 'at': at, 'took': at - last}
            last = at
    return found


def snapshot(repo):
    code, out, err = run(['gh', 'api', '--paginate', 'repos/%s/branches?per_page=100' % repo, '--jq', '.[].name'])
    if code:
        raise Rig('gh could not list the branches of %s: %s' % (repo, last_line(err)))
    branches = set(out.split())
    code, out, err = run(['gh', 'pr', 'list', '--repo', repo, '--state', 'open', '--limit', '500', '--json',
                          'number,headRefName,title,body'])
    if code:
        raise Rig('gh could not list the pull requests of %s: %s' % (repo, last_line(err)))
    return branches, {p['number']: p for p in json.loads(out)}


def strays(before, after, ticket):
    names_ticket = re.compile(r'(^|[/_-])%d([/_-]|$)' % ticket)
    cites_ticket = re.compile(r'(#|/issues/)%d\b' % ticket)
    prs = [p for n, p in sorted(after[1].items()) if n not in before[1] and (
        names_ticket.search(p['headRefName']) or cites_ticket.search(p['title'] + '\n' + (p['body'] or '')))]
    heads = {p['headRefName'] for p in prs}
    return prs, sorted(b for b in after[0] - before[0] if names_ticket.search(b) or b in heads)


def clean(repo, prs, branches, dry):
    done = []
    for p in prs:
        code, _, err = (0, '', '') if dry else run(['gh', 'pr', 'close', str(p['number']), '--repo', repo,
                                                    '--comment', 'Closed by the live-check rig: a driver kit run '
                                                    'opened it on a throwaway ticket.'])
        done.append(('would close' if dry else 'closed') + ' pull request #%d' % p['number'] if code == 0 else
                    'could not close pull request #%d: %s' % (p['number'], last_line(err)))
    for b in branches:
        ref = 'repos/%s/git/refs/heads/%s' % (repo, urllib.parse.quote(b, safe='/'))
        code, _, err = (0, '', '') if dry else run(['gh', 'api', '-X', 'DELETE', ref])
        done.append(('would delete' if dry else 'deleted') + ' branch `%s`' % b if code == 0 else
                    'could not delete branch `%s`: %s' % (b, last_line(err)))
    return done


def normal(text):
    for pattern, put in VOLATILE:
        text = pattern.sub(put, text)
    return text


def signature(result):
    if 'rig' in result:
        return {'rig': normal(result['rig'])}
    sig = {'offline': result['offline']['verdict'], 'kit_exit': result['kit']['exit']}
    for name in CHECKS:
        c = result['checks'].get(name)
        sig[name] = 'missing' if c is None else 'pass' if c['verdict'] == 'pass' else 'fail: ' + normal(c['what'])
    if result['kit']['timed_out']:
        sig['kit'] = 'timed out'
    elif result['kit']['exit'] == 2:
        sig['kit'] = normal(last_line(result['kit']['stderr']))
    return sig


def why_post(sig, state, now):
    if not state:
        return 'first run'
    if state.get('signature') != sig:
        return 'the result changed since the last receipt'
    if now - state.get('posted_at', 0) >= DAILY_SECONDS:
        return 'daily receipt, the result is unchanged'
    return None


def seconds(x):
    return '%.1f s' % x


def receipt(cfg, r, why, note):
    out = ['<!-- openwiz:live-check v1 %s -->' % cfg['driver']]
    when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(r['at']))
    if 'rig' in r:
        out += ['**Live check, `%s` driver: the rig could not run** (%s)' % (cfg['driver'], when), '',
                '```text', r['rig'], '```']
    else:
        passed = [n for n in CHECKS if r['checks'].get(n, {}).get('verdict') == 'pass']
        failed = [n for n in CHECKS if n not in passed]
        out += ['**Live check, `%s` driver: %d of %d checks pass**%s · %s' % (
            cfg['driver'], len(passed), len(CHECKS), ' (failed: %s)' % ', '.join(failed) if failed else '', when), '']
        sha, _, rest = r['driver_commit'].partition(' ')
        rest = rest if len(rest) <= 90 else rest[:87] + '...'
        out += ['- **Driver:** `adapters/%s` at %s (%s); `main` at %s' % (cfg['driver'], sha, rest, r['head']),
                '- **Harness / model:** `%s` / `%s`' % (cfg['harness'], cfg['model'])]
        out += ['- **Host:** ' + '; '.join(r['versions'] + ([cfg['about']] if cfg['about'] else []))]
        out += ['- **Ticket:** %s#%d, skill `%s`, kit `--wait %d`' % (cfg['repo'], cfg['ticket'], cfg['skill'],
                                                                      cfg['wait']),
                '- **Offline tests:** %s, %s (%s)' % (r['offline']['verdict'], r['offline']['summary'],
                                                      seconds(r['offline']['took'])),
                '- **Kit:** exit %d%s, %s in all' % (r['kit']['exit'], ', timed out and interrupted' if
                                                     r['kit']['timed_out'] else '', seconds(r['kit']['took'])), '',
                '| Check | Result | Took | At |', '| --- | --- | --- | --- |']
        for n in CHECKS:
            c = r['checks'].get(n)
            verdict = 'missing' if c is None else 'pass' if c['verdict'] == 'pass' else '**fail**' + (
                ' (not run)' if c['what'].startswith('not run') else '')
            out.append('| %s | %s | %s | %s |' % (n, verdict, seconds(c['took']) if c else '-',
                                                    seconds(c['at']) if c else '-'))
        bad = [t for _, t in r['kit']['lines'] if t.startswith('fail ') or not KIT_LINE.fullmatch(t)]
        if bad or r['kit']['stderr']:
            out += ['', '**Failures and kit messages, exact:**', '', '```text'] + [redact(t) for t in bad] + (
                [r['kit']['stderr']] if r['kit']['stderr'] else []) + ['```']
        if r['offline']['tail']:
            out += ['', '**Offline test output (last lines):**', '', '```text', r['offline']['tail'], '```']
        out += ['', '**Cleanup on %s:** %s.' % (cfg['repo'], '; '.join(r['cleanup']) if r['cleanup'] else
                                                  'the run created no branch or pull request')]
    out += ['', '**Posted because:** %s. Run took %s. The rig repeats every 6 hours and posts when the result '
            'changes, or once a day.' % (why, seconds(r['took']))]
    if note:
        out += ['', note.strip()]
    return '\n'.join(out) + '\n'


def private(checkout, path):
    code, out, err = run([sys.executable, '-I', 'tools/privacy-check/check.py', '--body-file', path], cwd=checkout)
    return None if code == 0 else last_line(out + err)


def post(cfg, path):
    repo, _, number = cfg['receipts'].partition('#')
    code, out, err = run(['gh', 'issue', 'comment', number, '--repo', repo, '--body-file', path])
    if code:
        raise Rig('gh could not post the receipt: ' + last_line(err))
    return last_line(out)


def saved(path, value=None):
    if value is None:
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    with open(path + '.new', 'w') as f:
        json.dump(value, f)
    os.replace(path + '.new', path)
    return value


def live_check(cfg, dry):
    r = {'at': time.time()}
    began = time.monotonic()
    try:
        r['head'], r['driver_commit'] = update(cfg['checkout'], cfg['driver'])
        r['versions'] = versions(cfg['tools'])
        before = snapshot(cfg['repo'])
        r['offline'] = offline(cfg['checkout'], cfg['driver'])
        r['kit'] = kit(cfg)
        r['checks'] = checks(r['kit']['lines'])
    except Rig as e:
        r = {'at': r['at'], 'rig': redact(str(e))}
    if 'rig' not in r:
        try:
            r['cleanup'] = clean(cfg['repo'], *strays(before, snapshot(cfg['repo']), cfg['ticket']), dry)
        except Rig as e:
            r['cleanup'] = ['could not look for branches or pull requests the run left: %s' % e]
    r['took'] = time.monotonic() - began
    return r


def main(argv):
    ap = argparse.ArgumentParser(prog='live_check.py')
    ap.add_argument('--config', required=True, help='the box config, as README.md shows')
    ap.add_argument('--dry-run', action='store_true', help='print the receipt; post, close and delete nothing')
    ap.add_argument('--force', action='store_true', help='post a receipt even when nothing changed')
    ap.add_argument('--note', help='a Markdown file added at the end of this run\'s receipt')
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        note = ''
        if args.note:
            with open(args.note) as f:
                note = f.read()
    except (OSError, ValueError, Rig) as e:
        print('live_check.py: %s' % e, file=sys.stderr)
        return 2
    os.makedirs(cfg['state'], mode=0o700, exist_ok=True)
    with open(os.path.join(cfg['state'], 'lock'), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('live-check %s: another run holds the lock, so this one did nothing' % cfg['driver'])
            return 0
        r = live_check(cfg, args.dry_run)
        sig, state = signature(r), saved(os.path.join(cfg['state'], 'state.json'))
        why = 'asked for by hand' if args.force else why_post(sig, state, time.time())
        body = receipt(cfg, r, why or 'not posted, unchanged', note)
        path = os.path.join(cfg['state'], 'last-receipt.md')
        with open(path, 'w') as f:
            f.write(body)
        outcome, failed = 'no receipt: unchanged since %s' % state.get('url'), 'rig' in r
        if why and args.dry_run:
            outcome = 'dry run, receipt not posted (%s)' % why
        elif why:
            try:
                refusal = private(cfg['checkout'], path)
                if refusal:
                    raise Rig('the privacy check refused the receipt: ' + refusal)
                url = post(cfg, path)
                saved(os.path.join(cfg['state'], 'state.json'), {'signature': sig, 'posted_at': time.time(),
                                                                 'url': url})
                outcome = 'receipt posted: %s (%s)' % (url, why)
            except Rig as e:
                outcome, failed = 'receipt NOT posted: %s' % e, True
        with open(os.path.join(cfg['state'], 'history.jsonl'), 'a') as f:
            f.write(json.dumps({'at': r['at'], 'signature': sig, 'outcome': outcome}) + '\n')
    passed = sum(v == 'pass' for k, v in sig.items() if k in CHECKS)
    print('live-check %s: %s; %s' % (cfg['driver'], sig['rig'] if 'rig' in sig else '%d of %d checks pass, offline '
                                     'tests %s' % (passed, len(CHECKS), sig['offline']), outcome))
    if args.dry_run:
        print(body)
    return 2 if failed else 0 if passed == len(CHECKS) and sig.get('offline') == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
