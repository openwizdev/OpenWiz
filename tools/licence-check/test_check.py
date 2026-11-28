import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ORG = "fable-workshop"
TRACKER = f"{ORG}/library"

FAKE_GH = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["LICENCE_FIXTURE"])
world = json.loads((root / "world.json").read_text())
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as stream:
    print(json.dumps(args), file=stream)

org = "fable-workshop"
tracker = f"repos/{org}/library/issues"
prefix = ["api", "--hostname", "github.com"]
if args == prefix + ["--method", "GET", "--paginate", "--slurp", f"orgs/{org}/repos?type=public&per_page=100"]:
    print(json.dumps(world["repositories"]))
elif args == prefix + ["--method", "GET", "--paginate", "--slurp", tracker + "?state=open&per_page=100"]:
    print(json.dumps(world["issues"]))
elif args[:len(prefix) + 2] == prefix + ["--method", "GET"] and len(args) == len(prefix) + 3:
    repo = args[-1].removeprefix("repos/")
    record = next(row for page in world["repositories"] for row in page if row["full_name"] == repo)
    print(json.dumps(record))
elif args[:len(prefix) + 3] == prefix + ["--method", "GET", "--include"] and len(args) == len(prefix) + 4:
    repo = args[-1].removeprefix("repos/").removesuffix("/license")
    status, value = world["licences"][repo]
    print(f"HTTP/2.0 {status} Fixture\r\n\r\n" + json.dumps(value))
    sys.exit(0 if status == 200 else 1)
elif args[:len(prefix) + 3] == prefix + ["--method", "POST", tracker] and len(args) == len(prefix) + 7:
    assert args[-4] == "-f" and args[-3].startswith("title=licence: ")
    assert args[-2] == "-f" and args[-1].startswith("body=")
    world["issues"][0].append({"title": args[-3].removeprefix("title=")})
    (root / "world.json").write_text(json.dumps(world))
    print("{}")
else:
    print("unexpected fixture command", file=sys.stderr)
    sys.exit(3)
'''


def repository(name, private=False):
    return {"full_name": f"{ORG}/{name}", "private": private}


def licence(spdx):
    return {"license": {"spdx_id": spdx}}


class LicenceCheck(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "check.py").is_file(), "licence auditor is missing")
        self.audit = runpy.run_path(str(HERE / "check.py"))["main"]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fake = self.root / "gh"
        fake.write_text(FAKE_GH)
        fake.chmod(0o700)
        self.log = self.root / "calls.jsonl"
        self.world = {
            "repositories": [[repository("missing"), repository("hidden", True)],
                             [repository("compliant"), repository("different")]],
            "licences": {
                f"{ORG}/compliant": [200, licence("Apache-2.0")],
                f"{ORG}/different": [200, licence("MIT")],
                f"{ORG}/missing": [404, {"message": "absent in the fixture"}],
            },
            "issues": [[{"title": f"licence: {ORG}/missing is not Apache-2.0", "pull_request": {}}],
                       [{"title": f"licence: {ORG}/different is not Apache-2.0"}]],
        }
        self.save_world()

    def save_world(self):
        (self.root / "world.json").write_text(json.dumps(self.world))

    def run_check(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        env = {"PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}", "LICENCE_FIXTURE": str(self.root)}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = self.audit(list(args), organization=ORG, tracker=TRACKER)
        return result, stdout.getvalue(), stderr.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_report_reads_all_public_pages_without_writes(self):
        rc, output, errors = self.run_check()
        self.assertEqual((rc, errors), (1, ""))
        self.assertEqual(output.splitlines(), [
            "repository\tspdx\tresult",
            f"{ORG}/compliant\tApache-2.0\tpass",
            f"{ORG}/different\tMIT\tfail",
            f"{ORG}/missing\tnone\tfail",
        ])
        self.assertEqual([call[-1] for call in self.calls()[1:]], [
            f"repos/{ORG}/compliant/license", f"repos/{ORG}/different/license",
            f"repos/{ORG}/missing/license", f"repos/{ORG}/missing",
        ])
        self.assertEqual({call[4] for call in self.calls()}, {"GET"})

    def test_files_only_the_missing_title_in_the_tracker_and_repeat_skips(self):
        self.assertEqual(self.run_check("--file-issues")[0], 1)
        self.assertEqual(self.run_check("--file-issues")[0], 1)
        writes = [call for call in self.calls() if call[4] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][4:8], [
            "POST", f"repos/{TRACKER}/issues", "-f", f"title=licence: {ORG}/missing is not Apache-2.0",
        ])

    def test_fails_closed_on_rate_limit_even_when_another_gap_is_known(self):
        self.world["licences"][f"{ORG}/missing"] = [403, {"message": "untrusted raw text"}]
        self.save_world()
        rc, output, errors = self.run_check("--file-issues")
        self.assertEqual((rc, output), (2, ""))
        self.assertIn("HTTP 403", errors)
        self.assertNotIn("untrusted raw text", errors)
        self.assertEqual({call[4] for call in self.calls()}, {"GET"})

    def test_rejects_repository_outside_org_before_reading_licences(self):
        self.world["repositories"][0].append({"full_name": "imagined-other/work", "private": False})
        self.save_world()
        self.assertEqual(self.run_check("--file-issues")[0], 2)
        self.assertEqual(len(self.calls()), 1)

    def test_all_apache_returns_success(self):
        self.world["repositories"] = [[repository("compliant")]]
        self.save_world()
        self.assertEqual(self.run_check(), (0, f"repository\tspdx\tresult\n{ORG}/compliant\tApache-2.0\tpass\n", ""))


if __name__ == "__main__":
    unittest.main()
