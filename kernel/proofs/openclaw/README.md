# OpenClaw proof

Proof B1 of spec #1365, for OpenClaw: as orchestrator with the OpenWiz skills, it takes a new demo project from grill to merged pull requests, starting builders through the [local driver](../../../adapters/local/README.md). This folder holds the run's sanitized evidence and the kit to make it.

**Status: the run has not happened.** It needs Jake at his own machine and is held until he runs it. Nothing here claims it has.

| File | What |
| --- | --- |
| [demo-plan.md](demo-plan.md) | The demo project and what the run uses |
| [steps.md](steps.md) | Jake's exact steps, from sign-in to the hand-over |
| [template.md](template.md) | The evidence page, filled in after the run as `run.md` |
| [sanitize.py](sanitize.py) | Turns the run's raw records into public files, or refuses |
| [test_sanitize.py](test_sanitize.py) | Its proofs |
| `evidence/` | The sanitizer's red and green runs |

```sh
python3 -I kernel/proofs/openclaw/sanitize.py <raw folder> <out folder> --literals <private list>
python3 -I kernel/proofs/openclaw/test_sanitize.py
```

`sanitize.py` rewrites thread ids, cloud ids, home folders, email addresses and the private literals, refuses any credential, unknown file or symbolic link, and then runs OpenWiz's [privacy check](../../../tools/privacy-check/README.md) on the result; it writes nothing unless every file passes. It can't see exact words: the evidence carries none, because the grill and every approval stay in the private records repository and are linked, never copied.
