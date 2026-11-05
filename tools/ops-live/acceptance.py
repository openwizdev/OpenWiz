#!/usr/bin/env python3
"""Offline kit gate and result validator for #2190's bounded acceptance kit (OB8).

python3 -I tools/ops-live/acceptance.py kit <kit.json>
python3 -I tools/ops-live/acceptance.py results <kit.json> <results.json>

Exit 0: consistent; 1: refused (every refusal on stderr); 2: usage or an
unreadable file. Reads only the named files: no network, GitHub, room-cli,
thread or write. A pass is never permission and never a live result: a live
claim still needs its observed evidence read back and independently reviewed.
The kit's controls are checked by #2219's controls/kit.py, unchanged.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True

_SPEC = importlib.util.spec_from_file_location(
    "controls_kit", Path(__file__).resolve().parent / "controls" / "kit.py")
controls = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(controls)
Refused = controls.Refused
read = controls.read
POINTER = controls.POINTER
MISSING = object()

KIT_FORMAT = "ops-live-kit/1"
RESULTS_FORMAT = "ops-live-results/1"
CLAIMS = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")
# The named #2244 assumption: until its findings are recorded, these are Unknown
# and the claims below stay Unverified with their effects refused.
DISCOVERY = ("lost_start_lookup", "independent_wakes", "reviewer_own_output")
DISCOVERY_AFFECTS = ("P3", "P4", "P5", "P7")
MEASURES = ("grant_wait_ms", "review_start_delay_ms", "oldest_pending_message_age_ms",
            "release_delay_ms", "recovery_time_ms", "duplicate_starts",
            "incorrect_grants", "incorrect_releases")
# ops-dispatch v1 intent actions and completion states.
ACTIONS = ("builder_start", "review_start", "delivery", "hold_release", "merge", "grant", "audit")
COMPLETIONS = ("completed", "superseded", "uncertain", "reconciled_not_executed",
               "disabled", "refused")
ROUTED = ("builder_start", "review_start", "delivery")  # completion needs the recipient's ACK
EVIDENCE_CLASSES = ("fixture", "observation", "review")
KIT_TOP = ("format", "status", "discovery_2244", "controls", "read_back", "host_roles",
           "cloud_exposure", "permitted_effects", "claims", "measures")
RESULTS_TOP = ("format", "kit", "live", "window", "threads", "operations", "fencing",
               "reviewer_output", "cleanup", "claims", "measures", "gaps")


def _text(value):
    return isinstance(value, str) and controls._printable(value)


def _hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _keys(doc, keys, path, out):
    if not isinstance(doc, dict):
        out.append(f"{path}: not an object")
        return False
    for key in doc:
        if key not in keys:
            out.append(f"{(path + '.') if path else ''}{key}: unknown key")
    for key in keys:
        if key not in doc:
            out.append(f"{(path + '.') if path else ''}{key}: missing")
    return True


# ---- the kit ---------------------------------------------------------------

def check_kit(doc):
    """Every refusal of a prepared or authorized kit; empty is a pass."""
    out = []
    if not _keys(doc, KIT_TOP, "", out):
        return ["kit: not an object"]
    if doc.get("format", MISSING) is not MISSING and doc["format"] != KIT_FORMAT:
        out.append(f"format: not {KIT_FORMAT}")
    if "controls" in doc:
        out += [f"controls.{r}" for r in controls.check(doc["controls"])]
    discovery = doc.get("discovery_2244")
    if "discovery_2244" in doc and _keys(discovery, ("record", "affects") + DISCOVERY,
                                         "discovery_2244", out):
        record = discovery.get("record")
        if record is not None and (not isinstance(record, str) or not POINTER.fullmatch(record)):
            out.append("discovery_2244.record: not a private-record comment pointer")
        for name in DISCOVERY:
            if discovery.get(name, "unknown") not in ("unknown", "observed", "absent"):
                out.append(f"discovery_2244.{name}: not unknown, observed or absent")
        if discovery.get("affects") != list(DISCOVERY_AFFECTS):
            out.append("discovery_2244.affects: not exactly " + ", ".join(DISCOVERY_AFFECTS))
    if "read_back" in doc and _keys(doc["read_back"], controls.CLASSES, "read_back", out):
        for name, value in doc["read_back"].items():
            if value is not None and not _hex64(value):
                out.append(f"read_back.{name}: not null or a sha256 digest")
    if "host_roles" in doc and _keys(doc["host_roles"], ("primary", "standby", "builder", "reviewer"),
                                     "host_roles", out):
        for name, value in doc["host_roles"].items():
            if not _text(value):
                out.append(f"host_roles.{name}: not a non-empty printable ASCII string")
    if "cloud_exposure" in doc and not _text(doc["cloud_exposure"]):
        out.append("cloud_exposure: not a non-empty printable ASCII string")
    effects = doc.get("permitted_effects")
    if "permitted_effects" in doc:
        if not isinstance(effects, list) or not effects:
            out.append("permitted_effects: not a non-empty list")
        else:
            for i, effect in enumerate(effects):
                if not _text(effect) or effect.split()[0] not in ACTIONS:
                    out.append(f"permitted_effects[{i}]: not a contract action")
            if "merge" in _permitted(doc) and not _granted(doc, "merge"):
                out.append("permitted_effects: merge without a merge grant")
    if "claims" in doc and doc["claims"] != list(CLAIMS):
        out.append("claims: not exactly P1-P8")
    if "measures" in doc and doc["measures"] != list(MEASURES):
        out.append("measures: not exactly the eight measures")
    status = doc.get("status")
    if status not in ("prepared", "authorized") and "status" in doc:
        out.append("status: not prepared or authorized")
    if status == "authorized" and not out:
        out += [f"status: authorized but live gate closed: {r}" for r in live_gate(doc)]
    return out


def _granted(kit, name):
    controls_doc = kit.get("controls")
    permissions = controls_doc.get("permissions") if isinstance(controls_doc, dict) else None
    entry = permissions.get(name) if isinstance(permissions, dict) else None
    return isinstance(entry, dict) and entry.get("granted") is True


def _permitted(kit):
    effects = kit.get("permitted_effects")
    return {e.split()[0] for e in effects if _text(e)} if isinstance(effects, list) else set()


def live_gate(doc):
    """Why no live, machine, write, activation, spending or merge step may start.

    Offline only: a digest in read_back says an agent read the record back; this
    function cannot read it again. Empty means the gate is open on paper.
    """
    reasons = []
    for name in controls.CLASSES:
        entry = doc["controls"]["permissions"][name]
        if not entry["needed"]:
            continue
        if not entry["granted"]:
            reasons.append(f"permission {name}: not granted")
        elif doc["read_back"][name] is None:
            reasons.append(f"permission {name}: record not read back")
    discovery = doc["discovery_2244"]
    if discovery["record"] is None:
        reasons.append("discovery_2244: #2244 findings not recorded")
    for name in DISCOVERY:
        if discovery[name] == "unknown":
            reasons.append(f"discovery_2244.{name}: unknown")
    return reasons


def _unknown_2244(kit):
    d = kit["discovery_2244"]
    return d["record"] is None or any(d[name] != "observed" for name in DISCOVERY)


# ---- the results -----------------------------------------------------------

def _evidence(entry, path, out):
    if not _keys(entry, ("evidence_class", "source", "digest"), path, out):
        return None
    if entry.get("evidence_class") not in EVIDENCE_CLASSES:
        out.append(f"{path}.evidence_class: not fixture, observation or review")
    if not _hex64(entry.get("digest")):
        out.append(f"{path}.digest: not a sha256 digest")
    source = entry.get("source")
    if entry.get("evidence_class") == "fixture":
        if not (_text(source) and source.startswith("fixture:")):
            out.append(f"{path}: fixture without a fixture: source")
    elif not (isinstance(source, str) and POINTER.fullmatch(source)):
        out.append(f"{path}: {entry.get('evidence_class')} without a private-record pointer")
    return entry


def _evidence_list(parent, path, out):
    value = parent.get("evidence", [])
    if not isinstance(value, list):
        out.append(f"{path}.evidence: not a list")
        return []
    return [e for i, e in enumerate(value) if _evidence(e, f"{path}.evidence[{i}]", out)]


def _observed(entries):
    return any(e.get("evidence_class") == "observation" and isinstance(e.get("source"), str)
               and POINTER.fullmatch(e["source"]) for e in entries)


def _time(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _intervals(items, path, window, out, alias=None):
    """Valid (start, end) spans, refusing impossible or out-of-window times."""
    spans, seen = [], set()
    for i, item in enumerate(items):
        p = f"{path}[{i}]"
        if alias:
            name = item.get(alias)
            if not _text(name):
                out.append(f"{p}.{alias}: not a non-empty printable ASCII string")
            elif name in seen:
                out.append(f"{p}: duplicate alias")
            else:
                seen.add(name)
        start, end = item.get("start"), item.get("end")
        if not _time(start):
            out.append(f"{p}.start: not a time in milliseconds")
            continue
        if end is None:
            out.append(f"{p}: never ended")
            end = window[1] if window else start
        elif not _time(end):
            out.append(f"{p}.end: not a time in milliseconds")
            continue
        elif end < start:
            out.append(f"{p}: ends before it starts")
            continue
        if window and (start < window[0] or end > window[1]):
            out.append(f"{p}: outside the run window")
        spans.append((start, end))
    return spans


def _peak(spans):
    events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans],
                    key=lambda ev: (ev[0], ev[1]))  # an end at t frees before a start at t
    peak = active = 0
    for _, step in events:
        active += step
        peak = max(peak, active)
    return peak


def _bounds(spans, count, bound, path, out):
    peak = _peak(spans)
    if peak > bound["active"]:
        out.append(f"{path}: {peak} active at once exceeds {bound['active']}")
    if count > bound["total"]:
        out.append(f"{path}: {count} exceeds total {bound['total']}")


def check_results(kit_text, doc):
    """Every refusal of a results document against its kit; empty is a pass."""
    try:
        kit = read(kit_text)
    except Refused as refused:
        return [f"kit: {refused}"]
    kit_out = check_kit(kit)
    if kit_out:
        return [f"kit: {r}" for r in kit_out]
    out = []
    if not _keys(doc, RESULTS_TOP, "", out):
        return ["results: not an object"]
    if doc.get("format") != RESULTS_FORMAT:
        out.append(f"format: not {RESULTS_FORMAT}")
    if doc.get("kit") != hashlib.sha256(kit_text.encode()).hexdigest():
        out.append("kit: digest does not match the kit")
    live = doc.get("live")
    if type(live) is not bool:
        out.append("live: not true or false")
    elif live and kit["status"] != "authorized":
        out.append("live: kit is not authorized")
    limits = kit["controls"]["limits"]

    window = None
    w = doc.get("window")
    if _keys(w, ("start", "end"), "window", out):
        if not (_time(w.get("start")) and _time(w.get("end"))) or w["end"] < w["start"]:
            out.append("window: not a start and end in milliseconds")
        else:
            window = (w["start"], w["end"])
            if w["end"] - w["start"] > limits["duration_minutes"] * 60_000:
                out.append(f"window: longer than {limits['duration_minutes']} minutes")

    threads = doc.get("threads")
    if not isinstance(threads, list):
        out.append("threads: not a list")
        threads = []
    for i, t in enumerate(threads):
        if _keys(t, ("alias", "role", "start", "end"), f"threads[{i}]", out) and \
                not (_text(t.get("role")) and t["role"] in kit["host_roles"]):
            out.append(f"threads[{i}].role: not a kit host role")
    threads = [t for t in threads if isinstance(t, dict)]
    _bounds(_intervals(threads, "threads", window, out, alias="alias"), len(threads),
            limits["threads"], "threads", out)

    operations = doc.get("operations")
    if not isinstance(operations, list):
        out.append("operations: not a list")
        operations = []
    ops = []
    bound = {}  # intent_id -> operation_key: one immutable intent, one stable key
    for i, op in enumerate(operations):
        p = f"operations[{i}]"
        if not _keys(op, ("operation_key", "intent_id", "action", "start", "end",
                          "completion", "ack"), p, out):
            continue
        ops.append((i, op))
        intent, key = op.get("intent_id"), op.get("operation_key")
        if _text(intent) and _hex64(key):
            if bound.setdefault(intent, key) != key:
                out.append(f"{p}: intent {intent} bound to another operation key")
        if not _hex64(op.get("operation_key")):
            out.append(f"{p}.operation_key: not a sha256 digest")
        if not _text(op.get("intent_id")):
            out.append(f"{p}.intent_id: not a non-empty printable ASCII string")
        action, completion = op.get("action"), op.get("completion")
        if action not in ACTIONS:
            out.append(f"{p}.action: not a contract action")
        if completion not in COMPLETIONS:
            out.append(f"{p}.completion: not a contract completion state")
        ack = op.get("ack")
        if ack is not None and _keys(ack, ("operation_key", "intent_id", "recipient", "evidence"),
                                     f"{p}.ack", out):
            if (ack.get("operation_key"), ack.get("intent_id")) != \
                    (op.get("operation_key"), op.get("intent_id")):
                out.append(f"{p}.ack: names another operation")
            if not _text(ack.get("recipient")):
                out.append(f"{p}.ack.recipient: not a non-empty printable ASCII string")
            entry = _evidence(ack.get("evidence"), f"{p}.ack.evidence", out)
            if entry is not None and not _observed([entry]):
                out.append(f"{p}.ack: not observed")
        if completion != "completed":
            continue
        if action in ACTIONS and action not in _permitted(kit):
            out.append(f"{p}: {action} is not a permitted effect")
        if action in ROUTED and ack is None:
            out.append(f"{p}: completed {action} without an acknowledgement")
    _bounds(_intervals([op for _, op in ops], "operations", window, out), len(ops),
            limits["operations"], "operations", out)
    completed = {}
    for _, op in ops:
        if op.get("completion") == "completed" and _hex64(op.get("operation_key")):
            completed.setdefault(op.get("operation_key"), []).append(op)
    duplicates = [k for k, v in completed.items() if len(v) > 1]
    for key in duplicates:
        out.append(f"operations: duplicate completed effect {key}")
    duplicate_starts = sum(len(v) - 1 for v in completed.values()
                           if v[0].get("action") == "builder_start")

    fencing = doc.get("fencing")
    boundary = None
    if _keys(fencing, ("boundary", "evidence"), "fencing", out):
        boundary = fencing.get("boundary")
        if boundary not in ("effect", "advisory", "unknown"):
            out.append("fencing.boundary: not effect, advisory or unknown")
        if boundary == "effect" and not _observed(_evidence_list(fencing, "fencing", out)):
            out.append("fencing: effect boundary not observed")
    reviewer = doc.get("reviewer_output")
    access = None
    if _keys(reviewer, ("access", "evidence"), "reviewer_output", out):
        access = reviewer.get("access")
        if access not in ("verified", "absent", "unknown"):
            out.append("reviewer_output.access: not verified, absent or unknown")
        if access == "verified" and not _observed(_evidence_list(reviewer, "reviewer_output", out)):
            out.append("reviewer_output: access not observed")
            access = "unobserved"
    for i, op in ops:
        if op.get("action") == "merge" and op.get("completion") == "completed" and access != "verified":
            out.append(f"operations[{i}]: merge without verified reviewer-output access")

    steps = kit["controls"]["restoration"] + kit["controls"]["cleanup"]
    cleanup = doc.get("cleanup")
    if not isinstance(cleanup, list):
        out.append("cleanup: not a list")
        cleanup = []
    accounted = set()
    for i, item in enumerate(cleanup):
        p = f"cleanup[{i}]"
        if not _keys(item, ("step", "state", "evidence"), p, out):
            continue
        step = item.get("step")
        if not _text(step) or step not in steps:
            out.append(f"{p}: not a kit restoration or cleanup step")
        elif step in accounted:
            out.append(f"{p}: duplicate step")
        else:
            accounted.add(step)
        if item.get("state") not in ("done", "accounted"):
            out.append(f"{p}: not done or accounted for")
        if not _evidence_list(item, p, out):
            out.append(f"{p}: no evidence")
    for step in steps:
        if step not in accounted:
            out.append(f"cleanup: missing {step}")

    claims = doc.get("claims")
    if not isinstance(claims, list) or [c.get("claim") if isinstance(c, dict) else None
                                        for c in claims] != list(CLAIMS):
        out.append("claims: not exactly P1-P8 in order")
        claims = [c for c in claims if isinstance(c, dict)] if isinstance(claims, list) else []
    acked_delivery = any(op.get("action") == "delivery" and op.get("completion") == "completed"
                         and op.get("ack") is not None for _, op in ops)
    for i, claim in enumerate(claims):
        if not _keys(claim, ("claim", "status", "evidence"), f"claims[{i}]", out):
            continue
        name, status = claim.get("claim"), claim.get("status")
        evidence = _evidence_list(claim, f"claims[{i}]", out)
        if status not in ("pass", "fail", "partial", "unverified"):
            out.append(f"claims[{i}].status: not pass, fail, partial or unverified")
        if status != "pass":
            continue
        if live is not True:
            out.append(f"claims {name}: pass without a live run")
        if not _observed(evidence):
            out.append(f"claims {name}: pass without observed live evidence")
        if name in DISCOVERY_AFFECTS and _unknown_2244(kit):
            out.append(f"claims {name}: pass while #2244 findings are unknown")
        if name == "P4" and not acked_delivery:
            out.append("claims P4: pass without an acknowledged delivery")
        if name == "P5":
            if boundary != "effect":
                out.append(f"claims P5: pass with {boundary} fencing")
            if duplicates:
                out.append("claims P5: pass with a duplicate effect")
        if name == "P7" and access != "verified":
            out.append(f"claims P7: pass with {access} reviewer-output access")
        if name == "P8" and any(t.get("end") is None for t in threads):
            out.append("claims P8: pass with a thread that never ended")

    gaps = doc.get("gaps")
    if not isinstance(gaps, list) or not all(_text(g) for g in gaps):
        out.append("gaps: not a list of printable ASCII strings")
        gaps = []
    measures = doc.get("measures")
    if _keys(measures, MEASURES, "measures", out):
        for name in MEASURES:
            m = measures.get(name)
            p = f"measures.{name}"
            if not _keys(m, ("value", "denominator"), p, out):
                continue
            value, denominator = m.get("value"), m.get("denominator")
            if value is None:
                if not any(name in g for g in gaps):
                    out.append(f"{p}: unmeasured but not in gaps")
                continue
            if not _time(value):
                out.append(f"{p}.value: not a non-negative integer")
            if not _time(denominator) or denominator < 1:
                out.append(f"{p}: value without a positive denominator")
            if name == "duplicate_starts" and value != duplicate_starts:
                out.append(f"{p}: {value} but {duplicate_starts} duplicate builder start recorded")
    return out


def summary(doc):
    lines = [f"{c['claim']}: {c['status']}" for c in doc["claims"]]
    return lines + ["consistent results (offline only): every pass still needs its "
                    "observed evidence read back and independent evidence review"]


# ---- the command -----------------------------------------------------------

USAGE = "usage: acceptance.py kit <kit.json> | results <kit.json> <results.json>"


def _load(path):
    return Path(path).read_bytes().decode("utf-8")


def main(argv):
    if not argv or (argv[0], len(argv)) not in (("kit", 2), ("results", 3)):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        texts = [_load(p) for p in argv[1:]]
    except (OSError, UnicodeDecodeError):
        print("error: cannot read a named file as UTF-8", file=sys.stderr)
        return 2
    lines = []
    try:
        if argv[0] == "kit":
            kit = read(texts[0])
            refusals = check_kit(kit)
            if not refusals:
                gate = live_gate(kit)
                lines = [f"pass: kit {kit['status']} (offline only; no live claim)",
                         "live gate: " + ("open on paper; re-read every record before any step"
                                          if not gate else "closed")]
                lines += [f"  {r}" for r in gate]
        else:
            doc = read(texts[1])
            refusals = check_results(texts[0], doc)
            if not refusals:
                lines = summary(doc)
    except Refused as refused:
        refusals = [str(refused)]
    for refusal in refusals:
        print(f"refused: {refusal}", file=sys.stderr)
    if refusals:
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
