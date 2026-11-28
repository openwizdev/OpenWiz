import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "tests/driver-cases/3474/add-driver-cases.json"


def finding(case, effects):
    if case["sender"] == "non-owner" and effects:
        return "non-owner-starts-work"
    if {"copy-template", "run-tests", "run-kit"}.intersection(effects) and effects[:1] != ["api-check"]:
        return "work-before-api-check"
    if case.get("api") == "later" and effects != ["api-check", "reply-later"]:
        return "work-after-later"
    if case.get("spending") == "denied" and "run-kit" in effects:
        return "kit-without-grant"
    if "offer-publish" in effects:
        if case.get("kit") != "pass" or not case.get("publish_step"):
            return "offer-without-passing-kit-or-publish-step"
        if effects.count("offer-publish") != 1:
            return "repeated-offer"
        if "stop-started" not in effects or effects.index("offer-publish") < effects.index("stop-started"):
            return "offer-before-cleanup"
    if "publish" in effects and (
        case.get("owner_reply") != "yes" or "owner-assents" not in effects
        or effects.index("publish") < effects.index("owner-assents")
    ):
        return "publish-without-assent"
    return None


def main():
    assert CASES.is_file(), "V5: add-a-driver conversation cases are missing"
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in data["cases"]}
    assert len(cases) == len(data["cases"]) == 7
    assert set(cases) == {
        "non-owner", "missing-stop", "spending-denied", "kit-fails",
        "publish-unavailable", "offer-awaits-assent", "owner-assents",
    }
    later = cases["missing-stop"]
    assert later["reason"] == "No documented stop for one run"
    assert later["expected_effects"] == ["api-check", "reply-later"]
    assert cases["non-owner"]["expected_effects"] == []
    assert cases["spending-denied"]["expected_effects"][-2:] == [
        "request-live-kit-grant", "reply-spending-denied",
    ]
    assert cases["kit-fails"]["expected_effects"][-3:] == [
        "run-kit", "stop-started", "reply-kit-failed",
    ]
    assert cases["publish-unavailable"]["expected_effects"][-2:] == [
        "stop-started", "reply-publish-unavailable",
    ]
    assert cases["offer-awaits-assent"]["expected_effects"][-2:] == [
        "stop-started", "offer-publish",
    ]
    assert cases["owner-assents"]["expected_effects"][-3:] == [
        "offer-publish", "owner-assents", "publish",
    ]
    for case in cases.values():
        assert finding(case, case["expected_effects"]) is None, case["id"]
    controls = data["failure_controls"]
    assert len(controls) == 5
    assert {c["finding"] for c in controls} == {
        "work-before-api-check", "offer-without-passing-kit-or-publish-step",
        "repeated-offer", "publish-without-assent",
    }
    for control in controls:
        assert finding(cases[control["case"]], control["effects"]) == control["finding"]
    print("V5: 7 synthetic cases and 5 failing controls passed")


if __name__ == "__main__":
    main()
