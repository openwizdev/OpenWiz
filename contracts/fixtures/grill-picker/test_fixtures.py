#!/usr/bin/env python3
"""Offline fixture proof with a Draft 2020-12 validator."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "grill-picker.v1.schema.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def broken_record(valid, case):
    record = deepcopy(valid[case["valid"]])
    parent = record
    for key in case["at"][:-1]:
        parent = parent[key]
    key = case["at"][-1]
    if "swap" in case:
        left, right = case["swap"]
        parent[key][left], parent[key][right] = parent[key][right], parent[key][left]
    elif "value" in case:
        parent[key] = case["value"]
    else:
        del parent[key]
    return record


def card_error(card):
    ids = [option["id"] for option in card["options"]]
    if len(ids) != len(set(ids)):
        return "duplicate_option_id"
    return None


def answer_error(card, answer):
    if answer["context"] != card["context"]:
        return "context_mismatch"
    ids = {option["id"] for option in card["options"]}
    chosen = answer["chosen_option_ids"]
    if not ids.issuperset(chosen):
        return "unknown_option_id"
    if "notes" in answer and not card["notes"]:
        return "notes_disabled"
    if "other" in answer and not card["other"]:
        return "other_disabled"
    if not card["multi"] and len(chosen) + ("other" in answer) > 1:
        return "too_many_choices"
    return None


def leaf_errors(errors):
    for error in errors:
        if error.context:
            yield from leaf_errors(error.context)
        else:
            yield error


class GrillPickerFixtures(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEMA.is_file(), f"{SCHEMA.name} is missing")
        schema = read_json(SCHEMA)
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
        self.valid = {}
        for name, fixture in read_json(HERE / "valid.json").items():
            if "from" in fixture:
                record = dict(self.valid[fixture["from"]], **fixture["set"])
                for key in fixture.get("omit", []):
                    del record[key]
            else:
                record = fixture
            self.valid[name] = record

    def test_valid_cards_and_answers(self):
        # comment-ok: catches: rejecting supported single, multi or free-text answers and empty notes.
        for name, record in self.valid.items():
            with self.subTest(fixture=name):
                self.validator.validate(record)
                if record["kind"] == "card":
                    self.assertIsNone(card_error(record))
        for card, answer in (
            ("multi_card", "exact_answer"),
            ("single_card", "single_answer"),
            ("single_other_card", "other_only_answer"),
            ("multi_card", "empty_note_answer"),
        ):
            with self.subTest(card=card, answer=answer):
                self.assertIsNone(answer_error(self.valid[card], self.valid[answer]))

    def test_broken_fixtures(self):
        # comment-ok: catches: accepting malformed cards or replies, including a second-place recommendation.
        for name, case in read_json(HERE / "broken.json").items():
            with self.subTest(fixture=name):
                record = broken_record(self.valid, case)
                if "keyword" in case:
                    at = case["at"]
                    if "swap" in case:
                        at = [*at, 0, "recommended"]
                    elif "value" not in case:
                        at = at[:-1]
                    keywords = {
                        error.validator
                        for error in leaf_errors(self.validator.iter_errors(record))
                        if list(error.absolute_path) == at
                    }
                    self.assertIn(case["keyword"], keywords)
                else:
                    self.validator.validate(record)
                    if "card" in case:
                        error = answer_error(self.valid[case["card"]], record)
                    else:
                        error = card_error(record)
                    self.assertEqual(error, case["rule"])

    def test_saved_reply_preserves_owner_text_and_choice_order(self):
        # comment-ok: catches: trimming, newline or Unicode normalization, and sorting selections.
        answer = self.valid["exact_answer"]
        self.validator.validate(answer)
        payload = json.dumps(answer, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        line = (HERE / "saved-reply.txt").read_bytes()
        self.assertEqual(line, b"> " + payload + b"\n")
        restored = json.loads(line.removeprefix(b"> ").removesuffix(b"\n"))
        self.assertEqual(restored["notes"].encode("utf-8"), b"  cafe\xcc\x81\t\r\n\n> line  \r")
        self.assertEqual(restored["other"].encode("utf-8"),
                         b"\t\xe7\xb4\xab \xf0\x9f\x92\xa1\xe2\x80\xa8\nopenwiz decision answer v1\n  ")
        self.assertEqual(restored["chosen_option_ids"], ["gold", "blue"])
        self.assertEqual(restored["at"], "2030-03-04T05:06:07.123Z")


if __name__ == "__main__":
    unittest.main(verbosity=2)
