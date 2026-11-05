#!/usr/bin/env python3
"""Test-only (Sol R6, round 3): every required field of each page route's answer, mutated
to a wrong type, must be rejected. SYNTHETIC ONLY.

    gen-wrong-types.py <send-kit.py> <work dir> <contracts dir>

Reads the three routes' real answers from the running server (the swap must be up),
walks each answer against its contract schema with a small walker of its own (an
oracle independent of the kit's validator), and for every required field picks a
value of a type the contract does not allow. Prints one JSON line per route with how
many fields were mutated and which (by path) the kit accepted. Exit 0 only if the kit
rejected every mutation, and each route had at least 5 fields to mutate."""
import copy
import http.client
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("kit", sys.argv[1])
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
k = kit.Kit(sys.argv[2])
ta = k.threads["T-A"]
inv = json.load(open(sys.argv[3] + "/inventory.v1.schema.json"))
msg = json.load(open(sys.argv[3] + "/messaging.v1.schema.json"))


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
        return any(fits(b, v, root) for b in node["oneOf"])
    if "const" in node:
        return v == node["const"]
    if "enum" in node and v not in node["enum"]:
        return False
    t = node.get("type")
    if t is not None and jtype(v) not in (t if isinstance(t, list) else [t]):
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
            if name in v:
                yield path + [name], node["properties"][name]
                yield from required_paths(v[name], node["properties"][name], root, path + [name])
    elif isinstance(v, list) and v and "items" in node:
        yield from required_paths(v[0], node["items"], root, path + [0])


def wrong(leaf, root):
    for cand in (17, "wrong-type", True, None, [], {"wrong": 1}):
        if not fits(leaf, cand, root):
            return cand
    raise SystemExit("no wrong value for a field (the oracle is broken)")


routes = (("inventory", "/api/v1/inventory", inv, {"$ref": "#/$defs/envelope"}),
          ("session", "/api/v1/sessions/%s" % ta, inv, {"$ref": "#/$defs/envelope"}),
          ("preview", "/api/v1/sessions/%s/preview" % ta, msg, {"$ref": "#/$defs/preview"}))
bad = False
for route, path, root, node in routes:
    c = http.client.HTTPConnection("127.0.0.1", k.cfg["port"], timeout=20)
    c.request("GET", path, headers={"Host": k.cfg["host"]})
    doc = json.loads(c.getresponse().read())
    assert fits(node, doc, root), "the server's own answer does not fit its contract: " + route
    assert kit.page_answer_problem(route, 200, doc, ta) is None, "the kit rejects a valid answer: " + route
    accepted, n = [], 0
    for p, leaf in required_paths(doc, node, root, []):
        d = copy.deepcopy(doc)
        cur = d
        for x in p[:-1]:
            cur = cur[x]
        cur[p[-1]] = wrong(leaf, root)
        if fits(node, d, root):
            continue  # the walker found the mutation still valid (a oneOf alternative): not a wrong type
        n += 1
        if kit.page_answer_problem(route, 200, d, ta) is None:
            accepted.append("/".join(str(x) for x in p))
    print(json.dumps({"route": route, "mutated": n, "accepted": accepted}))
    bad = bad or bool(accepted) or n < 5
sys.exit(1 if bad else 0)
