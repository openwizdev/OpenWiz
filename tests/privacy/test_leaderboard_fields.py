import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts/leaderboard.v1.schema.json"
REVIEW = ROOT / "docs/privacy/leaderboard.md"


def score_fields(definition, definitions, prefix=""):
    if "$ref" in definition:
        definition = definitions[definition["$ref"].removeprefix("#/$defs/")]
    for name, field in definition.get("properties", {}).items():
        path = f"{prefix}{name}"
        yield path
        yield from score_fields(field, definitions, prefix=f"{path}.")


class LeaderboardFieldsTest(unittest.TestCase):
    def test_review_covers_every_score_field(self):
        self.assertTrue(REVIEW.is_file(), "The leaderboard privacy review is missing")
        definitions = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]
        review = REVIEW.read_text(encoding="utf-8")
        section = review.partition("\n## Score record fields\n")[2].split("\n## ", 1)[0]
        reviewed = re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)
        self.assertCountEqual(reviewed, score_fields(definitions["score"], definitions))


if __name__ == "__main__":
    unittest.main()
