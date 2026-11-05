#!/usr/bin/env python3
"""Test-only (#152's R6, as the orchestrator directed): every required field of every
answer the kit checks, mutated to a wrong type, must be rejected. SYNTHETIC ONLY.
Adapted from 0.0.3's kit (PR #152 at e7568d4, scripts/test/gen-wrong-types.py).

    gen-wrong-types.py <new-kit.py> <work dir> <contracts dir>

The answers are real: the read routes the launcher and tray use, from the running swap
server (cloud options, an upload's add report, the attachment list, a removal, the
inventory, a new-thread preview, N-1's status), and the CLI reports the run kept
(N-1's create, R-1's refusal, N-4's status, A-1's send, R-3's attach failure). Each is
walked against its contract with a small walker of this file's own (an oracle that
shares no code with the kit's validator); for every required field it picks a value of a
type the contract does not allow, and asks the kit. Prints one JSON line per answer: how
many fields were mutated, and which (by path) the kit accepted. Exit 0 only if the kit
rejected every mutation and each answer had at least 5 fields to mutate.
"""
import copy
import glob
import http.client
import importlib.util
import json
import os
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("kit", sys.argv[1])
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2])
roots = {n: json.load(open(os.path.join(sys.argv[3], "%s.v1.schema.json" % n)))
         for n in ("new-thread", "attachment", "messaging", "inventory")}
DEFS = {"openwiz.new-thread.v1": ("new-thread", "report"), "openwiz.new-thread-preview.v1": ("new-thread", "preview"),
        "openwiz.new-thread-status.v1": ("new-thread", "status_read"),
        "openwiz.cloud-options.v1": ("new-thread", "options"), "openwiz.messaging.v1": ("messaging", "report"),
        "openwiz.attachment-add.v1": ("attachment", "add_report"),
        "openwiz.attachment-list.v1": ("attachment", "list_report"),
        "openwiz.attachment-remove.v1": ("attachment", "remove_report"), "openwiz.inventory.v1": ("inventory", None)}


def resolve(node, root):
    while isinstance(node, dict) and "$ref" in node:
        node = root["$defs"][node["$ref"].split("/")[-1]]
    return node


def jtype(v):
    return ("null" if v is None else "boolean" if isinstance(v, bool) else "integer" if isinstance(v, int)
            else "number" if isinstance(v, float) else "string" if isinstance(v, str)
            else "array" if isinstance(v, list) else "object")


def fits(node, v, root):
    node = resolve(node, root)
    if "oneOf" in node:
        return sum(1 for b in node["oneOf"] if fits(b, v, root)) == 1
    if "const" in node:
        return jtype(v) == jtype(node["const"]) and v == node["const"]
    if "enum" in node and not any(jtype(v) == jtype(e) and v == e for e in node["enum"]):
        return False
    t = node.get("type")
    if t is not None:
        ok = [t] if isinstance(t, str) else t
        if jtype(v) not in ok and not (jtype(v) == "integer" and "number" in ok):
            return False
    if isinstance(v, dict):
        props = node.get("properties", {})
        if not all(r in v for r in node.get("required", [])):
            return False
        if node.get("additionalProperties") is False and any(x not in props for x in v):
            return False
        return all(fits(props[x], v[x], root) for x in v if x in props)
    if isinstance(v, list) and "items" in node:
        return all(fits(node["items"], x, root) for x in v)
    return True


def required_paths(v, node, root, path):
    node = resolve(node, root)
    if "oneOf" in node:
        branch = next((b for b in node["oneOf"] if fits(b, v, root)), None)
        if branch is not None:
            yield from required_paths(v, branch, root, path)
        return
    if isinstance(v, dict):
        for name in node.get("required", []):
            if name in v and name in node.get("properties", {}):
                yield path + [name], node["properties"][name]
                yield from required_paths(v[name], node["properties"][name], root, path + [name])
    elif isinstance(v, list) and v and "items" in node:
        yield from required_paths(v[0], node["items"], root, path + [0])


def wrong(leaf, root):
    for cand in (17, "wrong-type", True, None, [], {"wrong": 1}):
        if not fits(leaf, cand, root):
            return cand
    raise SystemExit("no wrong value for a field (the oracle is broken)")


def ask(method, path, body=None, headers=None):
    st, doc = kit.request(k, method, path, body, headers)
    assert st == 200, "%s %s answered %s" % (method, path, st)
    return doc


answers = []
pa = k.targets["P-A"]
h, m, e = kit.create_settings(k, {"harness": "codex"})
answers.append(("route cloud-options", ask("GET", "/api/v1/cloud-options")))
add = kit.upload(k, "F1")[1]
answers.append(("route upload (add report)", add))
answers.append(("route attachments (list, one staged)", ask("GET", "/api/v1/attachments")))
staged = kit.ready_attachment(add)
answers.append(("route removal", ask("DELETE", "/api/v1/attachments/%s" % staged["id"])))
answers.append(("route inventory", ask("GET", "/api/v1/inventory")))
answers.append(("route new-thread preview", ask("POST", "/api/v1/projects/%s/threads/preview" % pa, {
    "op_id": kit.web_op(), "harness": h, "model": m, "effort": e, "text": k.texts["N3"], "attachments": []})))
answers.append(("route status of N-1", ask("GET", "/api/v1/new-threads/%s" % k.opids["C2-N1"])))
for step in ("C2-N1", "C1-R1", "C4-N4-status", "C5-A1", "C1-R3"):
    f = os.path.join(k.run, "out-%s-0.json" % step)
    answers.append(("CLI %s" % step, json.load(open(f))))
bad = False
for name, doc in answers:
    contract, dfn = DEFS[doc["schema"]]
    root = roots[contract]
    node = {"$ref": "#/$defs/%s" % dfn} if dfn else {"$ref": root["$ref"]}
    assert fits(node, doc, root), "the real answer does not fit its contract: " + name
    assert kit.contract_problem(k, doc, doc["schema"]) is None, "the kit rejects a valid answer: " + name
    accepted, n = [], 0
    for p, leaf in required_paths(doc, node, root, []):
        d = copy.deepcopy(doc)
        cur = d
        for x in p[:-1]:
            cur = cur[x]
        cur[p[-1]] = wrong(leaf, root)
        if fits(node, d, root):
            continue  # still valid for the walker (another oneOf branch): not a wrong type
        n += 1
        if kit.contract_problem(k, d, doc["schema"]) is None:
            accepted.append("/".join(str(x) for x in p))
    print(json.dumps({"answer": name, "mutated": n, "accepted": accepted}))
    bad = bad or bool(accepted) or n < 5
sys.exit(1 if bad else 0)
