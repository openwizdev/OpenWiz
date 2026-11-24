import os, subprocess, sys


def wrap(t, when=lambda req: True):
    launch = t.launch

    def spawn(req, run, woken):
        if not woken and when(req):
            with open(os.environ['FAKE_STARTS'], 'a') as f:
                f.write(run + '\n')
            subprocess.run([sys.executable, '-I', '-c', 'import time; time.sleep(0.5)', 'api_key=kit-fake-not-a-login'],
                           stdin=subprocess.DEVNULL, check=True, timeout=60)
        return launch(req, run, woken)
    t.launch = spawn
    return t
