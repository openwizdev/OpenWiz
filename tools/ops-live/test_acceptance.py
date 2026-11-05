#!/usr/bin/env python3
"""Red/green proofs for the offline result validator (#2190, OB8).

python3 -I tools/ops-live/test_acceptance.py

Every case is synthetic. The prepared kit is the real tools/ops-live/kit.json;
an "authorized" kit is a synthetic copy whose pointers name no real comment.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("acceptance", HERE / "acceptance.py")
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)

KIT_TEXT = (HERE / "kit.json").read_text()
POINTER = "https://github.com/jparker2006/ClosedWiz/issues/4001#issuecomment-{}"
DIGEST = "ab" * 32
MINUTE = 60_000
START = 1_800_000_000_000


def observed(n=1):
    return {"evidence_class": "observation", "source": POINTER.format(9000 + n),
            "digest": DIGEST}


def fixture():
    return {"evidence_class": "fixture", "source": "fixture:synthetic", "digest": DIGEST}


def authorized_kit():
    """A synthetic kit with every needed permission granted and read back."""
    kit = json.loads(KIT_TEXT)
    kit["status"] = "authorized"
    for n, (name, entry) in enumerate(kit["controls"]["permissions"].items()):
        if entry["needed"]:
            entry["granted"] = True
            entry["record"] = POINTER.format(100 + n)
            kit["read_back"][name] = DIGEST
    kit["discovery_2244"].update(record=POINTER.format(200), lost_start_lookup="observed",
                                 independent_wakes="observed", reviewer_own_output="observed")
    return kit


def text(doc):
    return json.dumps(doc, indent=2)


def digest(kit_text):
    return hashlib.sha256(kit_text.encode()).hexdigest()


def live_results(kit_text):
    """A consistent, fully passing synthetic live result for an authorized kit."""
    kit = json.loads(kit_text)
    steps = kit["controls"]["restoration"] + kit["controls"]["cleanup"]

    def op(n, action, ack=True):
        key = f"{n:064x}"
        return {"operation_key": key, "intent_id": f"intent-{n}", "action": action,
                "start": START + n * MINUTE, "end": START + n * MINUTE + 30_000,
                "completion": "completed",
                "ack": {"operation_key": key, "intent_id": f"intent-{n}",
                        "recipient": "builder-span", "evidence": observed(n)} if ack else None}

    return {
        "format": "ops-live-results/1",
        "kit": digest(kit_text),
        "live": True,
        "window": {"start": START, "end": START + 60 * MINUTE},
        "threads": [
            {"alias": "builder-a", "role": "builder", "start": START, "end": START + 50 * MINUTE},
            {"alias": "reviewer-a", "role": "reviewer", "start": START + 5 * MINUTE,
             "end": START + 40 * MINUTE},
            {"alias": "standby-a", "role": "standby", "start": START + 10 * MINUTE,
             "end": START + 20 * MINUTE},
        ],
        "operations": [op(1, "builder_start"), op(3, "delivery"), op(5, "review_start"),
                       op(7, "grant", ack=False), op(9, "hold_release", ack=False)],
        "fencing": {"boundary": "effect", "evidence": [observed(20)]},
        "reviewer_output": {"access": "verified", "evidence": [observed(21)]},
        "cleanup": [{"step": s, "state": "done", "evidence": [observed(30 + i)]}
                    for i, s in enumerate(steps)],
        "claims": [{"claim": c, "status": "pass", "evidence": [observed(40 + i)]}
                   for i, c in enumerate(kit["claims"])],
        "measures": {m: {"value": 1, "denominator": 1} for m in kit["measures"]}
                    | {"duplicate_starts": {"value": 0, "denominator": 1}},
        "gaps": [],
    }


def prepared_results():
    """What an honest run against the prepared kit can say: nothing is proven."""
    doc = live_results(KIT_TEXT)
    doc["live"] = False
    doc["threads"], doc["operations"] = [], []
    doc["fencing"] = {"boundary": "unknown", "evidence": []}
    doc["reviewer_output"] = {"access": "unknown", "evidence": []}
    doc["cleanup"] = [dict(c, state="accounted") for c in doc["cleanup"]]
    for claim in doc["claims"]:
        claim.update(status="unverified", evidence=[])
    doc["measures"] = {m: {"value": None, "denominator": None} for m in doc["measures"]}
    doc["gaps"] = ["no live run: every measure is unmeasured"] + [
        f"{m} unmeasured" for m in doc["measures"]]
    return doc


def refusals(kit_text, doc):
    return acceptance.check_results(kit_text, acceptance.read(text(doc)))


class Kit(unittest.TestCase):
    """AC1: absent authority leaves only a prepared kit."""

    def test_prepared_kit_passes_and_its_live_gate_is_closed(self):
        kit = acceptance.read(KIT_TEXT)
        self.assertEqual(acceptance.check_kit(kit), [])
        reasons = acceptance.live_gate(kit)
        for needed in ("machine", "live", "write", "activation", "spending"):
            self.assertIn(f"permission {needed}: not granted", reasons)
        self.assertIn("discovery_2244: #2244 findings not recorded", reasons)
        self.assertIn("discovery_2244.independent_wakes: unknown", reasons)

    def test_authorized_kit_without_authority_is_refused(self):
        cases = []
        kit = json.loads(KIT_TEXT)
        kit["status"] = "authorized"
        cases.append(("no grants", kit, "permission live: not granted"))
        kit = authorized_kit()
        kit["read_back"]["write"] = None
        cases.append(("no read-back", kit, "permission write: record not read back"))
        kit = authorized_kit()
        kit["discovery_2244"]["reviewer_own_output"] = "unknown"
        cases.append(("#2244 unknown", kit, "discovery_2244.reviewer_own_output: unknown"))
        kit = authorized_kit()
        kit["discovery_2244"]["record"] = None
        cases.append(("#2244 unrecorded", kit, "discovery_2244: #2244 findings not recorded"))
        for name, kit, reason in cases:
            with self.subTest(name):
                self.assertIn(f"status: authorized but live gate closed: {reason}",
                              acceptance.check_kit(kit))
        self.assertEqual(acceptance.check_kit(authorized_kit()), [])
        self.assertEqual(acceptance.live_gate(authorized_kit()), [])

    def test_kit_shape_is_strict(self):
        cases = []
        for key in ("controls", "discovery_2244", "claims", "measures", "read_back"):
            kit = json.loads(KIT_TEXT)
            del kit[key]
            cases.append((f"no {key}", kit, f"{key}: missing"))
        kit = json.loads(KIT_TEXT)
        kit["controls"]["limits"]["threads"]["active"] = 0
        cases.append(("controls refused", kit, "controls.limits.threads.active: not a positive integer"))
        kit = json.loads(KIT_TEXT)
        kit["claims"] = ["P1", "P2"]
        cases.append(("claims", kit, "claims: not exactly P1-P8"))
        kit = json.loads(KIT_TEXT)
        kit["discovery_2244"]["affects"] = ["P3", "P4"]
        cases.append(("assumption narrowed", kit, "discovery_2244.affects: not exactly P3, P4, P5, P7"))
        kit = json.loads(KIT_TEXT)
        kit["permitted_effects"].append("merge on a test-owned pull request")
        cases.append(("merge without grant", kit, "permitted_effects: merge without a merge grant"))
        kit = json.loads(KIT_TEXT)
        kit["permitted_effects"].append("deploy to production")
        cases.append(("unknown effect", kit, "permitted_effects[6]: not a contract action"))
        kit = json.loads(KIT_TEXT)
        kit["surprise"] = 1
        cases.append(("unknown key", kit, "surprise: unknown key"))
        for name, kit, reason in cases:
            with self.subTest(name):
                self.assertIn(reason, acceptance.check_kit(kit))
        with self.assertRaises(acceptance.Refused):
            acceptance.read('{"format": 1, "format": 2}')


class Results(unittest.TestCase):
    """AC2: offline red-first result validation."""

    def setUp(self):
        self.kit_text = text(authorized_kit())

    def test_consistent_results_pass(self):
        self.assertEqual(refusals(self.kit_text, live_results(self.kit_text)), [])
        self.assertEqual(refusals(KIT_TEXT, prepared_results()), [])

    def test_fabricated_concurrency(self):
        cases = []
        doc = live_results(self.kit_text)
        doc["threads"].append({"alias": "builder-b", "role": "builder",
                               "start": START + 12 * MINUTE, "end": START + 15 * MINUTE})
        cases.append(("four active threads", doc, "threads: 4 active at once exceeds 3"))
        doc = live_results(self.kit_text)
        doc["threads"] += [{"alias": f"t-{i}", "role": "builder", "start": START + (51 + i) * MINUTE,
                            "end": START + (51 + i) * MINUTE + 1} for i in range(4)]
        cases.append(("seven threads", doc, "threads: 7 exceeds total 6"))
        doc = live_results(self.kit_text)
        doc["operations"][1]["start"] = doc["operations"][0]["start"] + 1
        doc["operations"][2]["start"] = doc["operations"][0]["start"] + 2
        cases.append(("three active operations", doc, "operations: 3 active at once exceeds 2"))
        doc = live_results(self.kit_text)
        doc["threads"][0]["start"] = START - 1
        cases.append(("before the window", doc, "threads[0]: outside the run window"))
        doc = live_results(self.kit_text)
        doc["threads"][1]["end"] = doc["threads"][1]["start"] - 1
        cases.append(("ends before it starts", doc, "threads[1]: ends before it starts"))
        doc = live_results(self.kit_text)
        doc["window"]["end"] = START + 181 * MINUTE
        cases.append(("too long", doc, "window: longer than 180 minutes"))
        doc = live_results(self.kit_text)
        doc["threads"][2]["alias"] = "builder-a"
        cases.append(("one thread counted twice", doc, "threads[2]: duplicate alias"))
        for name, doc, reason in cases:
            with self.subTest(name):
                self.assertIn(reason, refusals(self.kit_text, doc))

    def test_missing_acknowledgements(self):
        cases = []
        doc = live_results(self.kit_text)
        doc["operations"][1]["ack"] = None
        cases.append(("no ack", doc, "operations[1]: completed delivery without an acknowledgement"))
        doc = live_results(self.kit_text)
        doc["operations"][1]["ack"]["operation_key"] = "f" * 64
        cases.append(("another key", doc, "operations[1].ack: names another operation"))
        doc = live_results(self.kit_text)
        doc["operations"][2]["ack"]["intent_id"] = "intent-99"
        cases.append(("another intent", doc, "operations[2].ack: names another operation"))
        doc = live_results(self.kit_text)
        doc["operations"][1]["ack"]["evidence"] = fixture()
        cases.append(("fixture ack", doc, "operations[1].ack: not observed"))
        doc = live_results(self.kit_text)
        doc["operations"] = [o for o in doc["operations"] if o["action"] != "delivery"]
        cases.append(("P4 with no delivery", doc, "claims P4: pass without an acknowledged delivery"))
        for name, doc, reason in cases:
            with self.subTest(name):
                self.assertIn(reason, refusals(self.kit_text, doc))

    def test_advisory_only_fencing(self):
        for boundary in ("advisory", "unknown"):
            doc = live_results(self.kit_text)
            doc["fencing"]["boundary"] = boundary
            with self.subTest(boundary):
                self.assertIn(f"claims P5: pass with {boundary} fencing", refusals(self.kit_text, doc))
        doc = live_results(self.kit_text)
        doc["fencing"]["evidence"] = [fixture()]
        self.assertIn("fencing: effect boundary not observed", refusals(self.kit_text, doc))
        doc = live_results(self.kit_text)
        doc["operations"].append(dict(doc["operations"][0], start=START + 55 * MINUTE,
                                      end=START + 56 * MINUTE))
        self.assertIn("operations: duplicate completed effect " + doc["operations"][0]["operation_key"],
                      refusals(self.kit_text, doc))

    def test_one_intent_bound_to_two_operation_keys(self):
        # R1: a second completed start of the same immutable intent under a
        # changed key must not dodge duplicate accounting (ops-dispatch v1).
        doc = live_results(self.kit_text)
        again = copy.deepcopy(doc["operations"][0])
        again["operation_key"] = again["ack"]["operation_key"] = "f" * 64
        again.update(start=START + 55 * MINUTE, end=START + 56 * MINUTE)
        doc["operations"].append(again)
        self.assertIn("operations[5]: intent intent-1 bound to another operation key",
                      refusals(self.kit_text, doc))
        # Distinct intents with distinct keys stay consistent.
        doc = live_results(self.kit_text)
        other = copy.deepcopy(doc["operations"][0])
        other.update(intent_id="intent-11", start=START + 55 * MINUTE, end=START + 56 * MINUTE)
        other["operation_key"] = "f" * 64
        other["ack"].update(operation_key="f" * 64, intent_id="intent-11")
        doc["operations"].append(other)
        self.assertEqual(refusals(self.kit_text, doc), [])

    def test_absent_reviewer_output_access(self):
        for access in ("absent", "unknown"):
            doc = live_results(self.kit_text)
            doc["reviewer_output"]["access"] = access
            with self.subTest(access):
                self.assertIn(f"claims P7: pass with {access} reviewer-output access",
                              refusals(self.kit_text, doc))
        kit = authorized_kit()
        kit["controls"]["permissions"]["merge"].update(needed=True, granted=True, record=POINTER.format(300))
        kit["read_back"]["merge"] = DIGEST
        kit["permitted_effects"].append("merge of a test-owned pull request")
        kit_text = text(kit)
        doc = live_results(kit_text)
        doc["operations"].append({"operation_key": "e" * 64, "intent_id": "intent-m", "action": "merge",
                                  "start": START + 55 * MINUTE, "end": START + 56 * MINUTE,
                                  "completion": "completed", "ack": None})
        self.assertEqual(refusals(kit_text, doc), [])
        doc["reviewer_output"] = {"access": "verified", "evidence": [fixture()]}
        self.assertIn("reviewer_output: access not observed", refusals(kit_text, doc))
        doc["reviewer_output"]["access"] = "absent"
        self.assertIn("operations[5]: merge without verified reviewer-output access",
                      refusals(kit_text, doc))

    def test_unpermitted_effects(self):
        doc = live_results(self.kit_text)
        doc["operations"].append({"operation_key": "e" * 64, "intent_id": "intent-m", "action": "merge",
                                  "start": START + 55 * MINUTE, "end": START + 56 * MINUTE,
                                  "completion": "completed", "ack": None})
        self.assertIn("operations[5]: merge is not a permitted effect", refusals(self.kit_text, doc))

    def test_incomplete_cleanup(self):
        cases = []
        doc = live_results(self.kit_text)
        doc["cleanup"][0]["state"] = "pending"
        cases.append(("pending", doc, "cleanup[0]: not done or accounted for"))
        doc = live_results(self.kit_text)
        doc["cleanup"].pop()
        cases.append(("missing step", doc,
                      "cleanup: missing account for every test-owned branch and claim ref; refs are never deleted or reused"))
        doc = live_results(self.kit_text)
        doc["cleanup"][1]["evidence"] = []
        cases.append(("no evidence", doc, "cleanup[1]: no evidence"))
        doc = live_results(self.kit_text)
        doc["cleanup"].append(dict(doc["cleanup"][0]))
        cases.append(("twice", doc, "cleanup[6]: duplicate step"))
        doc = live_results(self.kit_text)
        doc["cleanup"][2]["step"] = "something else"
        cases.append(("unknown step", doc, "cleanup[2]: not a kit restoration or cleanup step"))
        doc = live_results(self.kit_text)
        doc["threads"][2]["end"] = None
        cases.append(("thread never ended", doc, "threads[2]: never ended"))
        for name, doc, reason in cases:
            with self.subTest(name):
                self.assertIn(reason, refusals(self.kit_text, doc))

    def test_false_live_passes(self):
        cases = []
        doc = prepared_results()
        doc["claims"][0].update(status="pass", evidence=[observed()])
        cases.append(("pass without a live run", KIT_TEXT, doc, "claims P1: pass without a live run"))
        doc = prepared_results()
        doc["live"] = True
        cases.append(("live under a prepared kit", KIT_TEXT, doc, "live: kit is not authorized"))
        doc = live_results(self.kit_text)
        doc["claims"][0]["evidence"] = [fixture()]
        cases.append(("fixture-only pass", self.kit_text, doc, "claims P1: pass without observed live evidence"))
        doc = live_results(self.kit_text)
        doc["claims"][5]["evidence"] = [dict(observed(), evidence_class="review")]
        cases.append(("review-only pass", self.kit_text, doc, "claims P6: pass without observed live evidence"))
        doc = live_results(self.kit_text)
        doc["claims"][1]["evidence"] = [dict(observed(), source="fixture:looks-live")]
        cases.append(("observation from a fixture", self.kit_text, doc,
                      "claims[1].evidence[0]: observation without a private-record pointer"))
        kit = authorized_kit()
        kit["discovery_2244"]["independent_wakes"] = "unknown"
        kit["status"] = "prepared"
        kit_text = text(kit)
        doc = live_results(kit_text)
        doc["live"] = False
        cases.append(("#2244 still unknown", kit_text, doc, "claims P3: pass while #2244 findings are unknown"))
        doc = live_results(self.kit_text)
        doc["kit"] = "0" * 64
        cases.append(("another kit", self.kit_text, doc, "kit: digest does not match the kit"))
        doc = live_results(self.kit_text)
        doc["claims"] = doc["claims"][:7]
        cases.append(("claim dropped", self.kit_text, doc, "claims: not exactly P1-P8 in order"))
        doc = live_results(self.kit_text)
        doc["measures"]["recovery_time_ms"] = {"value": 5, "denominator": None}
        cases.append(("no denominator", self.kit_text, doc,
                      "measures.recovery_time_ms: value without a positive denominator"))
        doc = live_results(self.kit_text)
        doc["measures"]["release_delay_ms"] = {"value": None, "denominator": None}
        cases.append(("silent gap", self.kit_text, doc, "measures.release_delay_ms: unmeasured but not in gaps"))
        doc = live_results(self.kit_text)
        doc["operations"].append(dict(doc["operations"][0], start=START + 55 * MINUTE,
                                      end=START + 56 * MINUTE))
        cases.append(("duplicates under-reported", self.kit_text, doc,
                      "measures.duplicate_starts: 0 but 1 duplicate builder start recorded"))
        for name, kit_text, doc, reason in cases:
            with self.subTest(name):
                self.assertIn(reason, refusals(kit_text, doc))

    def test_results_shape_is_strict(self):
        doc = live_results(self.kit_text)
        doc["effects_enabled"] = True
        self.assertIn("effects_enabled: unknown key", refusals(self.kit_text, doc))
        doc = live_results(self.kit_text)
        doc["live"] = 1
        self.assertIn("live: not true or false", refusals(self.kit_text, doc))
        doc = live_results(self.kit_text)
        doc["operations"][0]["completion"] = "done"
        self.assertIn("operations[0].completion: not a contract completion state",
                      refusals(self.kit_text, doc))


class WrongTypes(unittest.TestCase):
    """A wrong-typed value anywhere is refused, never a crash or a pass."""

    def test_every_node_replaced(self):
        kit_text = text(authorized_kit())

        def paths(node, here=()):
            yield here
            items = node.items() if isinstance(node, dict) else \
                enumerate(node) if isinstance(node, list) else ()
            for key, child in items:
                yield from paths(child, here + (key,))

        base = live_results(kit_text)
        for path in list(paths(base))[1:]:
            for value in (None, [], {}, [1], 1.5, True):
                doc = copy.deepcopy(base)
                parent = doc
                for key in path[:-1]:
                    parent = parent[key]
                if type(parent[path[-1]]) is type(value) and parent[path[-1]] == value:
                    continue
                parent[path[-1]] = value
                with self.subTest(path=path, value=value):
                    result = refusals(kit_text, doc)
                    if value != [] or path[-1] not in ("gaps", "evidence", "threads", "operations"):
                        self.assertNotEqual(result, [])


class Command(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "acceptance.py"), *args],
                              capture_output=True, text=True)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp, "results.json")
            results.write_text(text(prepared_results()))
            ok = self.run_cli("kit", str(HERE / "kit.json"))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("live gate: closed", ok.stdout)
            ok = self.run_cli("results", str(HERE / "kit.json"), str(results))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("P5: unverified", ok.stdout)
            bad = prepared_results()
            bad["claims"][4]["status"] = "pass"
            results.write_text(text(bad))
            refused = self.run_cli("results", str(HERE / "kit.json"), str(results))
            self.assertEqual(refused.returncode, 1)
            self.assertIn("refused: claims P5: pass without a live run", refused.stderr)
            self.assertEqual(self.run_cli("kit").returncode, 2)
            self.assertEqual(self.run_cli("kit", str(Path(tmp, "absent.json"))).returncode, 2)


if __name__ == "__main__":
    unittest.main()
