import os, re, shutil, subprocess, sys, tempfile
src = sys.argv[1]
cases = [
 ('R5', 'test_fixture_install_into_home_prefix',
  "    env = {name: os.environ[name] for name in PASSED_ON if name in os.environ}\n", "    env = dict(os.environ)\n"),
 ('R6', 'test_wrong_version_keeps_the_working_tool',
  "        check_version(tool, staged)\n    except Refused:", "        os.replace(staged, dst)\n        check_version(tool, dst)\n    except Refused:"),
 ('R2 prefix', 'test_home_only_installer_is_refused_under_another_prefix',
  "if tool.get('home_only') and prefix != home_prefix:", "if False:"),
 ('R2 launcher', 'test_existing_launcher_is_never_replaced',
  "if tool['kind'] == 'installer' and os.path.lexists(dst):", "if False:"),
 ('R4', 'test_dry_run_prints_every_step_and_writes_nothing',
  "installed, there, left, available, failed, work = 0, 0, [], set(), False, None",
  "installed, there, left, available, failed, work = 0, 0, [], set(), False, tempfile.mkdtemp(prefix='openwiz-vps-')"),
 ('R1', 'test_real_tools_plan_offline_on_refusing_downloads',
  "prefix, dry, key = opts['prefix'], opts['dry'], platform_key()", "prefix, dry, key = opts['prefix'], False, platform_key()"),
]
for label, test, old, new in cases:
    d = tempfile.mkdtemp()
    shutil.copytree(src, os.path.join(d, 'vps'))
    p = os.path.join(d, 'vps', 'bootstrap.sh')
    s = open(p).read()
    assert s.count(old) == 1, label
    open(p, 'w').write(s.replace(old, new))
    r = subprocess.run([sys.executable, '-I', os.path.join(d, 'vps', 'test_bootstrap.py'), 'BootstrapTest.' + test],
                       capture_output=True, text=True)
    lines = [l for l in r.stderr.splitlines() if l.startswith(('AssertionError', 'FAILED', 'OK'))]
    print('%s reverted, %s: exit %d' % (label, test, r.returncode))
    for l in lines:
        print('  ' + re.sub(r'/tmp/[^ \'"]*', '<tmp>', l)[:300])
    shutil.rmtree(d)
