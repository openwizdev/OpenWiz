#!/usr/bin/env python3
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
PROMPT = 'Do the task with the ship skill.'
SID = 'fake-0123456789ab'
START = ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--trust', '--auto-approve',
         '--thinking', 'low']
REFUSED = {
    'api key flag': ['--api-key', 'synthetic-canary-0000-2918', *START],
    'api key equals': ['--prompt', PROMPT, '--api-key=synthetic-canary-0000-2918'],
    'thinking on resume': ['--prompt', 'You were woken to continue.', '--output', 'streaming', '--resume', SID,
                           '--trust', '--auto-approve', '--thinking', 'low'],
    'model on resume': ['--prompt', 'You were woken to continue.', '--output', 'streaming', '--model', 'devstral-2',
                        '--resume', SID, '--trust', '--auto-approve'],
    'unlisted thinking': ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--trust',
                          '--auto-approve', '--thinking', 'turbo'],
    'yolo alias': ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--trust', '--yolo'],
    'text output': ['--prompt', PROMPT, '--output', 'text', '--model', 'devstral-2', '--trust', '--auto-approve'],
    'missing trust': ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--auto-approve'],
    'setup': ['--setup'],
}
failed = 0
for name, argv in REFUSED.items():
    run = subprocess.run([sys.executable, '-I', FAKE, *argv], capture_output=True, text=True)
    if run.returncode != 2:
        failed += 1
        print('fail %s: exited %s, not 2' % (name, run.returncode))
print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
