#!/usr/bin/env python3

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "contracts" / "fixtures" / "ghost" / "bench-baseline.json"


def fail(message, code):
    print(f"ghost bench: {message}", file=sys.stderr)
    return code


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    return float(value)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(error) from error


def measure(report):
    if not isinstance(report, dict):
        raise ValueError
    overall = report.get("overall")
    if not isinstance(overall, dict):
        raise ValueError
    latency = overall.get("p90_latency_ms")
    if latency is not None:
        latency = number(latency)
    return latency, number(overall["acceptance_rate"]), number(overall["chars_saved_per_message"])


def check(report_path, baseline_path):
    try:
        report = load(report_path)
        baseline = load(baseline_path)
        if not isinstance(baseline, dict):
            raise ValueError
        latency, acceptance, saved = measure(report)
        limit = number(baseline["p90_latency_ms_max"])
        acceptance_min = number(baseline["acceptance_rate_min"])
        saved_min = number(baseline["chars_saved_per_message_min"])
    except (ValueError, KeyError, TypeError):
        return fail("the report or the baseline could not be read", 2)
    if latency is not None and latency > limit:
        return fail(f"p90 {latency} ms is above {limit} ms", 1)
    if acceptance < acceptance_min:
        return fail(f"acceptance {acceptance} is below the baseline {acceptance_min}", 1)
    if saved < saved_min:
        return fail(f"characters saved per message {saved} is below the baseline {saved_min}", 1)
    print("ghost bench: passed")
    return 0


def main(argv):
    if argv == ["check"] or (len(argv) == 3 and argv[0] == "check" and argv[1] == "--baseline"):
        return fail("usage: python3 -I ci/ghost-bench.py check REPORT.json [--baseline PATH]", 2)
    if len(argv) == 2 and argv[0] == "check":
        return check(argv[1], BASELINE)
    if len(argv) == 4 and argv[0] == "check" and argv[2] == "--baseline":
        return check(argv[1], argv[3])
    return fail("usage: python3 -I ci/ghost-bench.py check REPORT.json [--baseline PATH]", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
