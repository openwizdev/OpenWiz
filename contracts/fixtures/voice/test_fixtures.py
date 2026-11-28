#!/usr/bin/env python3
"""Offline proof for the voice v1 contract using synthetic inputs."""

import json
from pathlib import Path
import re
import runpy
import unittest

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
SCHEMA = CONTRACTS / "voice.v1.schema.json"
DOC = CONTRACTS / "voice.v1.md"
VALIDATOR = runpy.run_path(str(HERE.parent / "value-meter" / "test_fixtures.py"))
load = VALIDATOR["load"]
errors = VALIDATOR["errors"]


def exact(kind, context, policy):
    text = context.get("transcript", "").strip()
    if kind == "command_or_text":
        value = "command" if text.startswith(policy["wake_phrase"]) else "text"
    elif kind == "route":
        prefix = re.match(r"to ([^:]+): ", text)
        matches = [(target, name) for target, name in context.get("targets", [])
                   if prefix and prefix[1] == name]
        if len(matches) == 1:
            target, name = matches[0]
            return {"value": target, "name": name}
        value = "focused"
    elif kind == "term_fix":
        heard = context.get("heard")
        matches = set(context.get("terms", {}).get(heard, []))
        if len(matches) == 1 and heard not in matches:
            return {"value": "replace", "heard": heard, "term": matches.pop()}
        value = "keep"
    else:
        if kind != "respeak":
            raise ValueError("unknown decision")
        value = "append"
    return {"value": value}


def choose(schema, policy, kind, context, jev, answer):
    if (jev and not errors(answer, schema, schema) and answer["kind"] == kind
            and answer["confidence"] >= policy["confidence_floors"][kind]):
        return {key: value for key, value in answer.items() if key not in ("kind", "confidence")}
    return exact(kind, context, policy)


def permits(policy, voice, telemetry, transfer):
    channel, recipient, payload = transfer
    if not voice["enabled"] or payload not in policy["network"].get(channel, ()):
        return False
    if channel == "speech":
        return bool(recipient) and voice["model"] == "cloud:" + recipient
    if channel == "jev":
        return voice["jev"] and recipient == "jev"
    return channel == "telemetry" and telemetry and recipient == "telemetry"


class VoiceContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), "voice.v1.schema.json is missing")
        self.assertTrue(DOC.is_file(), "voice.v1.md is missing")
        self.schema = load(SCHEMA)
        block = re.search(r"^## Decision and transfer policy\n\n```json\n(.*?)^```$", DOC.read_text(encoding="utf-8"),
                          re.M | re.S)
        self.assertIsNotNone(block, "voice policy block is missing")
        self.policy = json.loads(block[1])
        self.cases = load(HERE / "decisions.json")

    def test_every_known_answer_matches_its_closed_shape(self):
        for answer in self.cases["answers"]:
            with self.subTest(answer=answer):
                self.assertEqual(errors(answer, self.schema, self.schema), [])
                for changed in (
                    {**answer, "value": "syn_unknown"},
                    {**answer, "kind": "syn_unknown"},
                    {**answer, "extra": "syn_extra"},
                    {**answer, "confidence": -0.01},
                    {**answer, "confidence": 1.01},
                    {**answer, "confidence": True},
                    {key: value for key, value in answer.items() if key != "confidence"},
                ):
                    self.assertTrue(errors(changed, self.schema, self.schema), changed)

    def test_answer_fields_are_specific_to_the_value(self):
        for answer in self.cases["invalid"]:
            with self.subTest(answer=answer):
                self.assertTrue(errors(answer, self.schema, self.schema))

    def test_jev_off_low_confidence_or_invalid_answers_use_exact_rules(self):
        for case in self.cases["fallbacks"]:
            with self.subTest(case=case["case"]):
                kind, context, high = case["kind"], case["context"], case["answer"]
                low = {**high, "confidence": case["low"]}
                wrong = {**high, "value": "syn_unknown"}
                for jev, answer in ((False, high), (True, low), (True, wrong)):
                    self.assertEqual(choose(self.schema, self.policy, kind, context, jev, answer), case["exact"])
                self.assertEqual(choose(self.schema, self.policy, kind, context, True, high), case["accepted"])

    def test_exact_rules_cover_other_outcomes(self):
        for case in self.cases["exact"]:
            with self.subTest(case=case["case"]):
                self.assertEqual(exact(case["kind"], case["context"], self.policy), case["expected"])

    def test_defaults_and_opt_in_transfer(self):
        defaults = self.policy["defaults"]
        self.assertEqual(defaults, {"voice": {"enabled": False, "model": "local", "jev": False}, "telemetry": False})
        for case in load(HERE / "network.json"):
            with self.subTest(case=case["case"]):
                voice = {**defaults["voice"], **case["voice"]}
                telemetry = case.get("telemetry", defaults["telemetry"])
                self.assertEqual(permits(self.policy, voice, telemetry, case["transfer"]), case["permitted"])


if __name__ == "__main__":
    unittest.main()
