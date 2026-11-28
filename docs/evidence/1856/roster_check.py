import importlib.util, json, pathlib, shutil, subprocess, sys, tempfile

skills = pathlib.Path(sys.argv[1]).resolve()
fleet = pathlib.Path(sys.argv[2]).resolve()
repo = 'openwizdev/OpenWiz'
scripts = skills / 'skills/launch-fleet/scripts'
sys.path.insert(0, str(scripts))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load('host', scripts / 'host.py')
ops = load('ops', scripts / 'ops-starts.py')
text = fleet.read_text()
models = ops.read_models(text)
roles = models['roles']
starts = [
    ('spec', 'launch-fleet', roles['orchestrator']['choice']),
    ('build', 'build-ticket', roles['builder']['choice']),
    ('small build', 'build-ticket', roles['small_builder']['choice']),
    ('fix claude', 'build-ticket', models['fixers']['claude']['choice']),
    ('fix gpt', 'build-ticket', models['fixers']['gpt']['choice']),
    ('review claude-built', 'review-ticket', models['reviews']['claude']['choice']),
    ('review gpt-built', 'review-ticket', models['reviews']['gpt']['choice']),
]
fails = 0
try:
    entries = host.roster(text)
except host.Outcome as e:
    print('roster:', e)
    sys.exit(1)
if entries is None:
    print('roster: none')
    sys.exit(1)
for e in entries:
    print('entry: %s | %s | %s | %s | %s' % (e['label'], e['kind'], e['driver'], ', '.join(e['roles']), e['writes_as']))
    if e['kind'] == 'bot':
        print('FAIL: bot entry %s, but no KN7 to KN9 run has passed' % e['name'])
        fails += 1
for what, skill, c in starts:
    today = ('claude' if c['provider'] == 'claude-code' else c['provider'], c['model'])
    try:
        role, picked = host.roster_start(text, entries, repo, 1856, today[0], today[1], skill)
    except host.Outcome as e:
        print('FAIL %s: %s' % (what, e))
        fails += 1
        continue
    got = (picked['start']['harness'], picked['start']['model'])
    ok = got == today and picked['driver'] == 'cloudroom' and picked['kind'] == 'harness'
    fails += not ok
    print('%s %s: today %s %s on cloudroom; roster %s %s on %s as %s, %s; token %s for %s' % (
        'ok' if ok else 'FAIL', what, today[0], today[1], got[0], got[1], picked['driver'],
        picked['note']['harness'], picked['note']['model'], picked['token']['requester'],
        ','.join(picked['token']['repositories'])))
helper = roles['builder']['choice']
picked = host.pick(entries, repo, 1856, 'helper', helper | {'model_name': helper['model']})['pick']
ok = picked and picked['kind'] == 'harness' and picked['start']['model'] == helper['model']
fails += not ok
print('%s helper: %s' % ('ok' if ok else 'FAIL', picked and picked['note']['harness']))
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    (root / 'docs/agents').mkdir(parents=True)
    shutil.copy(fleet, root / 'docs/agents/fleet.md')
    for name in ('triage-labels.md', 'issue-tracker.md', 'domain.md'):
        src = fleet.parent / name
        if src.exists():
            shutil.copy(src, root / 'docs/agents' / name)
    r = subprocess.run([sys.executable, '-I', str(skills / 'skills/setup/scripts/settings.py'), 'check', '--root', td],
                       capture_output=True, text=True)
    print('setup settings check exit %d: %s' % (r.returncode, (r.stdout + r.stderr).strip()))
print('result: %s' % ('green' if fails == 0 else '%d failing' % fails))
sys.exit(1 if fails else 0)
