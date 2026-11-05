#!/usr/bin/env python3
"""Test-only: plays Jake (and the runner relaying him) for X1's hands-on J steps.
SYNTHETIC ONLY. Adapted from 0.0.3's kit (PR #152 at 3a7b501).

    jake-sim.py <new-kit.py> <work dir> <groups> [run args...]

Runs `new-kit.py run`, reads its prompts on stderr, and acts as Jake would:
- a `PRESS <step>` prompt: unless the work directory was set up with --dry-run (where
  X1 presses for him), it makes the page's requests for that step, as Jake's browser
  would, through the kit's own `jake_press`;
- an `ANSWER <step>-<key>` prompt: it answers the way the runner does, with a file
  answer-<step>-<key>.txt in the run directory, saying what a page that behaves as
  accepted shows. These answers are a stand-in's, never Jake's.

JAKE_SIM_SAY="J1-N3-shown=refused,..." makes it say something else for those keys (to
show the kit stops on what Jake says); JAKE_SIM_TYPO=N3 makes it paste that text with a
trailing space (X2 refuses the write; the group then reruns cleanly). X1's report is printed; the exit code is X1's.
Prompts go to <work>/../prompts.log.
"""

import importlib.util
import os
import re
import subprocess
import sys
import threading

sys.dont_write_bytecode = True
kit_path, work, groups = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("kit", kit_path)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
k = kit.Kit(work)
steps = {s["id"]: s for g in k.plan["groups"] for s in g["steps"]}
# What a page that behaves as accepted shows, by step and question.
SAYS = {"J1-N3-shown": "created", "J1-N3-details": "opened", "J2-A2-shown": "sent", "J3-tray-over": "refused",
        "J3-tray-heic": "refused", "J3-tray-svg": "glyph", "J4-cut-tray": "failed-kept", "J5-chrome-launcher": "works",
        "J5-chrome-heic_photo": "skip", "J6-accept-launcher": "accept", "J6-accept-tray": "accept"}
for pair in filter(None, os.environ.get("JAKE_SIM_SAY", "").split(",")):
    key, _, word = pair.partition("=")
    SAYS[key] = word
for lab in filter(None, os.environ.get("JAKE_SIM_TYPO", "").split(",")):
    k.texts[lab] += " "  # Jake pastes that text with a trailing space
p = subprocess.Popen([sys.executable, kit_path, "run", "--work", work, "--groups", groups, "--answers", "chat"]
                     + sys.argv[4:], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True)
prompts = []


class Args:  # what jake_press needs of X1's arguments
    answers = "chat"
    press_timeout = 30


k.args = Args()
for line in p.stderr:
    prompts.append(line.rstrip("\n"))
    m = re.match(r">>> PRESS (\S+):", line)
    if m and not k.dry:
        threading.Thread(target=kit.jake_press, args=(k, steps[m.group(1)])).start()
        continue
    m = re.match(r">>> ANSWER (\S+):", line)
    if m:
        with open(os.path.join(k.run, "answer-%s.txt" % m.group(1)), "w") as f:
            f.write(SAYS.get(m.group(1), "unknown") + "\n")
out = p.stdout.read()
p.wait()
with open(os.path.join(os.path.dirname(work), "prompts.log"), "w") as f:
    f.write("\n".join(prompts) + "\n")
sys.stdout.write(out)
sys.exit(p.returncode)
