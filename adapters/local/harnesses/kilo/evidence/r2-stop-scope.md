# R2: Kilo stop platform scope

The README stop entry and the row's daemon field must both scope the stop
guarantee to Linux under HR1, describe the detached persistent process that
can outlive stop on macOS, and point to live check #2443. The existing
harness fixtures exercise cleanup but do not check the platform claim.

Run from the repository root:

```sh
sed -n '/^```python$/,/^```$/p' adapters/local/harnesses/kilo/evidence/r2-stop-scope.md |
  sed '1d;$d' | env -u OPENWIZ_GITHUB_APP_KEY python3 -I -
```

```python
import json
from pathlib import Path

row = Path("adapters/local/harnesses/kilo")
stop = next(line for line in (row / "README.md").read_text().splitlines()
            if line.startswith("- **Stop:**"))
daemon = json.loads((row / "row.json").read_text())["daemon"]
required = ("Linux", "HR1", "macOS", "detached persistent background process",
            "may outlive stop", "#2443")
failed = False
for label, claim in (("README stop", stop), ("row daemon", daemon)):
    missing = [term for term in required if term not in claim]
    if missing:
        print(f"fail {label}: missing {', '.join(missing)}")
        failed = True
    else:
        print(f"pass {label}: states the HR1 platform scope and live check")
raise SystemExit(1 if failed else 0)
```

## Red run

```text
fail README stop: missing Linux, HR1, macOS, detached persistent background process, may outlive stop, #2443
fail row daemon: missing Linux, HR1, macOS, detached persistent background process, may outlive stop, #2443
exit 1
```

## Green run

```text
pass README stop: states the HR1 platform scope and live check
pass row daemon: states the HR1 platform scope and live check
exit 0
```

Both harness commands ran on Linux with 40 refusal stubs first on PATH.

```text
$ env -u OPENWIZ_GITHUB_APP_KEY python3 -I adapters/local/test_harnesses.py
rows in adapters/local/harnesses: kilo
pass kilo: the contract, the folder, the kit's five checks, and the session, env, background process and effort checks
exit 0
$ env -u OPENWIZ_GITHUB_APP_KEY python3 -I adapters/local/harnesses/kilo/test_row.py
exit 0
```
