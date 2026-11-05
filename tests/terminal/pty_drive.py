"""Drives one program in a pseudo-terminal for the terminal tests (standard
library only). Usage: python3 -I pty_drive.py COLS ROWS STEPS_JSON PROGRAM [ARG...]

STEPS_JSON is a list of steps: {"wait": "text", "timeout": s} waits for text on
the screen (the output replayed on a small grid: cursor positioning and clears
applied, styles ignored), since a diffing renderer may write one word in
parts; with "fresh": true, only text drawn since the last resize counts.
With "body": true, match only the current app body, excluding navigation and
the footer (22-column sidebar at >=72x12; first-row tabs otherwise), never
historical output.
{"send": "keys"} writes bytes (\\u escapes allowed); {"resize": [cols, rows]}
changes the window size (the kernel signals the child); {"sleep": s}. Prints one JSON report: exit code, the steps' results, whether
the terminal's attributes after exit equal those before, and the output.
The final 15-second quit wait keeps draining output. A forced termination
reports incomplete: true and exits this driver with status 3; a natural child
exit preserves its code in the report and exits the driver with status 0.
"""

import base64
import codecs
import fcntl
import json
import os
import select
import struct
import subprocess
import sys
import termios
import time


def winsize(fd, cols, rows):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Screen:
    """Just enough of a terminal for ratatui's output: CUP, ED, SGR and text."""

    def __init__(self, cols, rows):
        self.resize(cols, rows)
        self.row = self.col = 0
        self.carry = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def resize(self, cols, rows):
        self.cols, self.rows = max(cols, 1), max(rows, 1)
        self.grid = [[" "] * self.cols for _ in range(self.rows)]

    def feed(self, data):
        text = self.carry + self.decoder.decode(data)
        self.carry = ""
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\x1b":
                if i + 1 >= len(text):
                    self.carry = text[i:]
                    return
                if text[i + 1] == "[":
                    j = i + 2
                    while j < len(text) and not ("@" <= text[j] <= "~"):
                        j += 1
                    if j >= len(text):
                        self.carry = text[i:]
                        return
                    self.csi(text[i + 2 : j], text[j])
                    i = j + 1
                    continue
                i += 2
                continue
            if ch == "\r":
                self.col = 0
            elif ch == "\n":
                self.row = min(self.row + 1, self.rows - 1)
            elif ch >= " ":
                if self.row < self.rows and self.col < self.cols:
                    self.grid[self.row][self.col] = ch
                self.col += 1
            i += 1

    def csi(self, params, final):
        if final == "H":
            parts = [p for p in params.split(";")]
            r = int(parts[0]) if parts and parts[0].isdigit() else 1
            c = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            self.row, self.col = min(r, self.rows) - 1, min(c, self.cols) - 1
        elif final == "J" and params == "2":
            self.grid = [[" "] * self.cols for _ in range(self.rows)]

    def text(self, body=False):
        if body:
            if self.cols >= 72 and self.rows >= 12:
                return "\n".join("".join(r[22:]) for r in self.grid[:-1])
            return "\n".join("".join(r) for r in self.grid[1:-1])
        return "\n".join("".join(r) for r in self.grid)


def main():
    cols, rows, steps = int(sys.argv[1]), int(sys.argv[2]), json.loads(sys.argv[3])
    argv = sys.argv[4:]
    master, slave = os.openpty()
    winsize(slave, cols, rows)
    before = termios.tcgetattr(slave)

    def controlling():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    child = subprocess.Popen(
        argv, stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling, close_fds=True
    )
    output = bytearray()
    screen = Screen(cols, rows)

    def pump(seconds):
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            ready, _, _ = select.select([master], [], [], min(left, 0.05))
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                output.extend(data)
                screen.feed(data)

    results = []
    for step in steps:
        if "wait" in step:
            needle = step["wait"]
            end = time.monotonic() + step.get("timeout", 10)
            found = False
            while time.monotonic() < end:
                if needle in screen.text(body=step.get("body", False)) or (
                    not step.get("body")
                    and not step.get("fresh")
                    and needle.encode() in output
                ):
                    found = True
                    break
                pump(0.05)
            results.append(found)
        elif "send" in step:
            os.write(master, step["send"].encode())
            results.append(True)
        elif "resize" in step:
            winsize(master, step["resize"][0], step["resize"][1])
            screen.resize(step["resize"][0], step["resize"][1])
            results.append(True)
        elif "sleep" in step:
            pump(step["sleep"])
            results.append(True)
    end = time.monotonic() + 15
    while child.poll() is None and time.monotonic() < end:
        pump(min(0.05, max(0, end - time.monotonic())))
    incomplete = child.poll() is None
    if incomplete:
        child.kill()
    code = child.wait()
    pump(0.3)
    after = termios.tcgetattr(slave)
    os.close(slave)
    os.close(master)
    print(
        json.dumps(
            {
                "exit": code,
                "incomplete": incomplete,
                "steps": results,
                "restored": before == after,
                "output": base64.b64encode(bytes(output)).decode(),
            }
        )
    )
    return 3 if incomplete else 0


sys.exit(main())
