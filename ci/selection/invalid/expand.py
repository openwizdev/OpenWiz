"""The invalid CI selection plans, from cases.json (ci/selection/README.md).

Each case is a valid plan (`base`, in ../valid/) with one planted break:
`drop` removes the member at each JSON pointer, then `set` writes each
pointer's value (a last `-` appends to a list). A `raw` case can't be a
parsed plan plus one edit, so its plan is the file of its name here.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text())


def _at(doc, pointer):
    *keys, last = pointer.split("/")[1:]
    for key in keys:
        doc = doc[int(key)] if isinstance(doc, list) else doc[key]
    return doc, (int(last) if isinstance(doc, list) and last != "-" else last)


def plan(name):
    """The text of one case's plan, as a run would keep it."""
    case = CASES[name]
    if case.get("raw"):
        return (HERE / name).read_text()
    doc = json.loads((HERE.parent / "valid" / case["base"]).read_text())
    for pointer in case.get("drop", []):
        parent, key = _at(doc, pointer)
        del parent[key]
    for pointer, value in case.get("set", {}).items():
        parent, key = _at(doc, pointer)
        if key == "-":
            parent.append(value)
        else:
            parent[key] = value
    return json.dumps(doc, indent=2) + "\n"
