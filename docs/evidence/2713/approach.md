# #2713 approach note

Ticket LR12 of spec #2474: the VPS bootstrap's follow-ups from #2646's final re-check (R7, R8, R9, rehearsal #2583 problem 4). Owned: `kernel/live-rig/vps/bootstrap.sh`, `kernel/live-rig/vps/test_bootstrap.py`; evidence here.

## Approach

1. **R8 first (one lock per prefix).** A real (non-dry) run takes an exclusive `flock` on `<prefix>/lib/openwiz-vps/lock` before its first stamp check and holds it until the last stamp and wheel cleanup are done. A second run for the same prefix says on stderr that it is waiting, then reads the stamps the first run wrote, so it either finds the pin already there or repins from a quiet tree. The kernel drops the lock when a run dies, so an interrupted run never wedges the next. The shared `staged/` launcher and the "remove every other wheel" cleanup stay, and are now safe because only one run per prefix is inside them. A dry run takes no lock, so it still writes nothing.
2. **R7 (hash before reuse).** The wheel cache path is still named by the pinned sha256, but a cached file is reused only after its own bytes hash to that pin. On a mismatch the verified download replaces it atomically (`.part` then `os.replace`) before anything imports it. If that replacement fails, the tool is refused with the reason, nothing is probed or published, and the active launcher and the wheel it imports are untouched.
3. **Problem 4 (an existing tool it didn't install).** One rule for every kind: if `<prefix>/bin/<tool>` exists and this bootstrap has no stamp for it, it is kept, never run, and named in a `left out` line saying why and how to install the pinned one. An installer-kind tool (Hermes) is never re-run over an existing launcher either. A tool with this bootstrap's stamp at another pin is a repin, as today. The `--version` call on an existing `hermes` goes away.
4. **R9.** The digest-path comment goes.

## Threats

- Cached bytes that were never checked get imported (R7): tampering, a partial write from a crash, or a stale file at a reused digest path.
- Two runs for one prefix interleave (R8): one deletes the other's wheel or staged launcher, a traceback after validation, or a stamp and launcher that name different wheels.
- The bootstrap executes a program it didn't install (problem 4), by absolute path, where PATH stubs can't guard it.
- A tool someone installed by hand is replaced silently (problem 4).
- A failed recovery leaves the working tool broken.
- Out of scope: another program, running as the same user, rewriting files under the prefix while the bootstrap holds the lock. The lock is advisory and only bootstrap runs honour it.

## What the tests can and can't prove

Can: with fixture downloads (`file://` only, dead proxies, refusing agent-CLI stubs first on PATH), that a corrupt cache entry is never imported and a valid download is published in its place; that a failed recovery leaves the launcher and its wheel byte-identical and still working; that two overlapping repins, with the first paused inside its version probe, both exit 0 and leave a stamp, launcher and wheel that agree and hash to the pin; that an existing unstamped launcher of every kind is kept and never run; that the comment is gone.

Can't: that the lock holds across machines or on a network filesystem (flock is local); real downloads, the real Hermes installer or a real VPS (the spec leaves those to the operator's live session); syscall-level network denial (this sandbox can't create a network namespace, so tests rely on `file://` URLs and dead proxies); timing beyond the one synchronised interleaving the overlap test forces.
