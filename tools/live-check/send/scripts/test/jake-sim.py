#!/usr/bin/env python3
"""Test-only: plays Jake (and the runner relaying him) for X1's live phone steps.
SYNTHETIC ONLY.

    jake-sim.py <send-kit.py> <work dir> <groups> [run args...]

Runs `send-kit.py run` without --dry-run, reads its prompts on stderr and acts as
Jake would on his phone: a PRESS makes the composer's request to the port the
tunnel serves; when the step says to turn on Airplane Mode, his own connection goes
once the call has answered; Check again reads the lookup route. Each ANSWER
prompt is answered the way the runner does it: a file answer-<step>.txt in the run
directory. X1's report is printed; the exit code is X1's. Prompts go to
../prompts.log.
"""

import importlib.util
import os
import re
import socket
import subprocess
import sys
import threading
import time

kit_path, work, groups = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("kit", kit_path)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
k = kit.Kit(work)
p = subprocess.Popen([sys.executable, kit_path, "run", "--work", work, "--groups", groups, "--answers", "chat"]
                     + sys.argv[4:], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True)
last = {}       # thread label -> Jake's last op id
shown = [None]  # what the composer would show for the last press (WS-8)
prompts = []


def press(label, msg, button, offline):
    text = k.texts[msg]
    mode = "steer" if button == "Steer" else "queue"
    op = kit.web_op(mode)
    last[label] = op
    body = {"op_id": op, "mode": mode, "text": text,
            "resume_paused_queue": False, "accept_possible_duplicate": False}
    holder = {}
    if offline:  # Airplane Mode right after the press: the phone's own connection goes
        def cut():
            while not os.path.exists(os.path.join(k.x2, "answered-holding")):
                time.sleep(0.05)
            try:
                holder["conn"].sock.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError, KeyError):
                pass
        threading.Thread(target=cut, daemon=True).start()
    shown[0] = kit.post(k, label, body, holder=holder)[2]


def answer(step, word):
    with open(os.path.join(k.run, "answer-%s.txt" % step), "w") as f:
        f.write(word + "\n")


pending = []
for line in p.stderr:
    prompts.append(line.rstrip("\n"))
    m = re.search(r"PRESS: on (.*?), open (T-[ABC]) in the web page, put text (M\d\d)", line)
    if m:
        pending.append(list(m.groups()) + [None, False])
        continue
    if "Airplane Mode" in line and pending:
        pending[-1][4] = True
        continue
    m = re.search(r"^\s+and press (.+?)\.$", line)
    if m and pending:  # the PRESS block's last line: Jake presses
        device, label, msg, _, offline = pending.pop()
        threading.Thread(target=press, args=(label, msg, m.group(1), offline)).start()
        continue
    m = re.search(r"PRESS: on .*?, press (Check again|Try again) on (T-[ABC])'s pending send", line)
    if m:
        label = m.group(2)
        if m.group(1) == "Check again":  # the phone retries while its network comes back
            for _ in range(50):
                shown[0] = kit.lookup(k, label, last[label])
                if shown[0] != "uncertain":
                    break
                time.sleep(0.2)
        continue
    m = re.search(r"ANSWER (\S+): (.*)", line)
    if m:
        step, q = m.groups()
        if "Cross-site" in q:
            answer(step, "skip")
        elif "composer show" in q:
            for _ in range(600):
                if shown[0] is not None:
                    break
                time.sleep(0.1)
            answer(step, shown[0] or "uncertain")
            shown[0] = None
        continue
out = p.stdout.read()
p.wait()
sys.stdout.write(out)
with open(os.path.join(work, "..", "prompts.log"), "w") as f:
    f.write("\n".join(prompts) + "\n")
sys.exit(p.returncode)
