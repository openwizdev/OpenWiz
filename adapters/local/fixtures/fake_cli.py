import json, os, secrets, shutil, socket, subprocess, sys, time

sys.dont_write_bytecode = True


def refuse():
    sys.exit(2)


def since(pid):
    if not os.path.isdir('/proc/self'):
        try:
            os.kill(pid, 0)
            return 0
        except OSError:
            return None
    try:
        with open('/proc/%d/stat' % pid) as f:
            fields = f.read().rpartition(')')[2].split()
        return None if fields[0] == 'Z' else int(fields[19])
    except OSError:
        return None


def record(entry):
    with open(os.open(os.environ['FAKE_CLI_RECORD'], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), 'w') as f:
        f.write(json.dumps(entry) + '\n')


def background_service(how):
    clean = {'PATH': os.environ['PATH']}
    if how == 'via-running-hub':
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(os.environ['FAKE_CLI_HOST'])
            pid = int(s.makefile().readline())
        return [pid, since(pid)]
    r, w = os.pipe()
    if os.fork() == 0:
        os.setsid()
        pid = os.fork()
        if pid:
            os.write(w, str(pid).encode())
            os._exit(0)
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        os.execve(shutil.which('sleep', path=clean['PATH']), ['sleep', '300'], clean)
    os.close(w)
    pid = int(os.read(r, 20))
    os.close(r)
    os.wait()
    return [pid, since(pid)]


def post(model, skill, woken):
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    body = '\n'.join(['<!-- openwiz:status v1 -->', 'agent: builder', 'state: working', 'harness: Fake',
                      'model: ' + model, 'skills: %s@0.1.2' % skill,
                      'step: ' + ('woke and read the ticket again' if woken else 'started the throwaway ticket'),
                      'time: ' + now]) + '\n'
    path = os.environ['KIT_TRACKER']
    with open(path) as f:
        tracker = json.load(f)
    mine = [c for c in tracker['comments'] if c['author'] == 'example-bot[bot]' and 'agent: builder' in c['body']]
    if woken:
        mine[-1].update(body=body, updated_at=now)
    else:
        tracker['comments'].append({'id': 1 + max([c['id'] for c in tracker['comments']], default=0),
                                    'author': 'example-bot[bot]', 'updated_at': now, 'body': body})
    with open(path + '.%d' % os.getpid(), 'w') as f:
        json.dump(tracker, f)
    os.replace(path + '.%d' % os.getpid(), path)


def turn(prompt, model, session=None, announce=None, daemon=None, signed_out=None, signed_out_exit=1):
    woken = prompt.startswith('You were woken')
    skill = prompt.partition('with the ')[2].partition(' skill')[0] or refuse()
    if os.environ.get('FAKE_CLI_WORKER'):
        while os.getppid() == int(os.environ['FAKE_CLI_WORKER']):
            time.sleep(0.01)
        post(model, skill, woken)
        time.sleep(300)
        sys.exit(0)
    if signed_out and os.environ.get('FAKE_CLI_SIGNED_OUT'):
        print(signed_out, flush=True)
        sys.exit(signed_out_exit)
    if session is None:
        if woken or announce is None:
            refuse()
        session = 'fake-' + secrets.token_hex(6)
        if not os.environ.get('FAKE_CLI_QUIET'):
            print(announce(session), flush=True)
    names = [n for n in os.environ.get('FAKE_CLI_ENV', '').split(',') if n]
    entry = {'turn': 'woken' if woken else 'first', 'session': session, 'argv': sys.argv[1:],
             'env': {n: os.environ.get(n) for n in names}}
    if os.environ.get('FAKE_CLI_RECORD_ONLY'):
        record(entry)
        sys.exit(0)
    if daemon and not woken:
        entry['daemon'] = background_service(daemon)
    record(entry)
    state = os.path.join(os.environ['OPENWIZ_LOCAL_STATE'], os.environ['OPENWIZ_RUN'] + '.json')
    while True:
        try:
            with open(state) as f:
                if json.load(f).get('starting') is False:
                    break
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    subprocess.Popen([sys.executable, sys.argv[0]] + sys.argv[1:], start_new_session=True, stdin=subprocess.DEVNULL,
                     env=dict(os.environ, FAKE_CLI_WORKER=str(os.getpid())))
    sys.exit(0)
