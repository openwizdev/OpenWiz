#!/usr/bin/env python3
import hashlib
import json
import sys
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
import test as base
from check import Refused
from scans import historical_text

OLD = "# Changelog\n\n## 0.0.98 · 2026-01-01\n\nContext: Earlier public entry.  \n"
ENTRY = """## 0.0.99 · 2026-01-02

Fixture-tested: You can preview an export.

- Fixture-tested: You can save a preview.
- Fixture-tested: You can cancel a preview.

Fixture-tested: Synthetic export fixtures pass; live export remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.99)
"""
CHANGELOG = "# Changelog\n\n" + ENTRY + "\n" + OLD.removeprefix("# Changelog\n\n")
ROADMAP = """# OpenWiz roadmap

What is being built now, and what comes next.

## Now

- **0.0.99**, built: You can preview an export.

## Next

- **0.0.100**, being grilled: You can compare exports.
"""


class EntryCheck(base.ReleaseCheck):
    def setUp(self):
        super().setUp()
        (self.public / "CHANGELOG.md").write_text(OLD)
        self.commit(self.public)
        self.base = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.world = {
            "repos/{owner}/{repo}/milestones?state=all&per_page=100": [
                {"number": 99, "title": "0.0.99", "description":
                 "You can preview an export.\nDone when the owner checks an export.",
                 "html_url": "https://github.com/example-owner/example-repo/milestone/99"},
                {"number": 100, "title": "0.0.100", "description":
                 "You can compare exports.\nDone when the owner compares exports.",
                 "html_url": "https://github.com/example-owner/example-repo/milestone/100"}],
            "repos/{owner}/{repo}/git/matching-refs/heads/release-": [
                {"ref": "refs/heads/release-0.0.99"}],
            "repos/example-owner/example-release/git/matching-refs/tags/v": [],
            "repos/{owner}/{repo}/issues?milestone=99&state=all&per_page=100": [],
            "repos/{owner}/{repo}/issues?milestone=100&state=all&per_page=100": [],
        }
        self.issue(4100, body="## Changelog headline\n\nFixture-tested: You can preview an export.\n",
                   sub_issues=3)
        for number, sentence, version in (
            (4101, "Fixture-tested: You can save a preview.", "0.0.99"),
            (4102, "Fixture-tested: You can cancel a preview.", "0.0.99"),
            (4103, "Fixture-tested: You can compare exports.", "0.0.100")):
            self.issue(number, version=version)
            p = self.repo / f"changes/{number}.md"
            p.parent.mkdir(exist_ok=True)
            p.write_text(f"kind: added\n\n{sentence}\n")
        self.commit(self.repo)
        self.world_path = self.root / "world.json"
        self.save_world()
        self.env["ENTRY_WORLD"] = str(self.world_path)
        (self.bin / "gh").write_text('''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["RELEASE_CALLS"], "a") as f:
    f.write(json.dumps({"tool":"gh","args":args,"cwd":os.getcwd()})+"\\n")
if os.environ.get("FAIL_GH"):
    sys.exit(94)
assert args[0] == "api" and not any(x in args for x in ("--method", "-X", "-f", "-F")), args
path = next(x for x in args if x.startswith("repos/"))
world = json.loads(open(os.environ["ENTRY_WORLD"]).read())
if path not in world:
    print("unexpected fixture read: "+path, file=sys.stderr)
    sys.exit(95)
sys.exit(subprocess.run(["/usr/bin/jq", "-cr", args[args.index("--jq")+1]],
                        input=json.dumps(world[path]), text=True).returncode)
''')
        self.replan()
        self.approve()

    def issue(self, number, version="0.0.99", body="", sub_issues=0):
        self.world[f"repos/{{owner}}/{{repo}}/issues/{number}"] = {
            "number": number, "body": body, "milestone": {"number": 99, "title": version},
            "sub_issues_summary": {"total": sub_issues}}

    def save_world(self):
        self.world_path.write_text(json.dumps(self.world))

    def approve(self, changelog=CHANGELOG, roadmap=ROADMAP):
        self.data["files"] = [f for f in self.data["files"] if not f["path"].startswith("changes/")]
        self.data["claim_reviews"] = [f for f in self.data["claim_reviews"] if not f["path"].startswith("changes/")]
        for file in sorted((self.repo/"changes").glob("*.md")):
            path = file.relative_to(self.repo).as_posix()
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            self.data["files"].append({"path":path,"source":path,"sha256":digest})
            self.data["claim_reviews"].append({"path":path,"sha256":digest,"claims":[
                {"text":line,"status":"fixture-tested" if line.startswith("Fixture-tested:") else "context",
                 "evidence":"docs/evidence/check.md#fixture"} for line in file.read_text().splitlines() if line]})
        self.data["entry"] = {"spec": 4100, "date": "2026-01-02", "tested":
            "Fixture-tested: Synthetic export fixtures pass; live export remains unverified."}
        for path, text in (("CHANGELOG.md", changelog), ("ROADMAP.md", roadmap)):
            self.data["files"] = [f for f in self.data["files"] if f["path"] != path]
            self.data["claim_reviews"] = [r for r in self.data["claim_reviews"] if r["path"] != path]
            digest = hashlib.sha256(text.encode()).hexdigest()
            self.data["files"].append({"path": path, "source": "generated/"+path, "sha256": digest})
            block = ""
            if path == "CHANGELOG.md":
                block = text[text.index("Fixture-tested:"):text.index("\n\n[Full release on GitHub]")]
            claims = ([{"text": block, "status": "fixture-tested", "evidence":
                        "docs/evidence/check.md#fixture"}] if block else [])
            claims += [
                {"text": line, "status": "context",
                 "evidence": "docs/evidence/check.md#fixture"}
                for line in text.splitlines() if line.strip() and not line.startswith("#") and line not in block]
            self.data["claim_reviews"].append({"path": path, "sha256": digest, "claims": claims})
        self.save_plan()

    def test_exact_entry_and_public_roadmap(self):
        for name in ("home", "tmp"):
            (self.root / name).mkdir()
        self.env.update(HOME=str(self.root / "home"), TMPDIR=str(self.root / "tmp"))

        def snapshot():
            return {p.relative_to(self.root).as_posix():
                    ("file", hashlib.sha256(p.read_bytes()).hexdigest()) if p.is_file() else ("directory",)
                    for p in self.root.rglob("*")
                    if not p.is_relative_to(self.stage) and not p.is_relative_to(self.evidence)
                    and p != self.root / "calls.jsonl"}

        before = {p: self.git(p, "rev-parse", "HEAD").stdout for p in (self.repo, self.public)}
        files_before = snapshot()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(snapshot(), files_before, "release check wrote outside staging and evidence")
        export = self.stage / "export"
        self.assertEqual((export / "CHANGELOG.md").read_text(), CHANGELOG)
        self.assertEqual((export / "ROADMAP.md").read_text(), ROADMAP)
        report = json.loads((self.evidence / "report.json").read_text())
        md = (self.evidence / "report.md").read_text()
        self.assertIn(ENTRY, md)
        self.assertIn(ROADMAP, md)
        for path in ("CHANGELOG.md", "ROADMAP.md"):
            row = next(f for f in report["files"] if f["path"] == path)
            self.assertEqual(row["sha256"], hashlib.sha256((export / path).read_bytes()).hexdigest())
            self.assertIn(row["sha256"], md)
        for repo, head in before.items():
            self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout, head)
            self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(any(c["tool"] == "gh" for c in calls))
        self.assertFalse(any(c["tool"] == "git" and any(a in c["args"] for a in ("push", "tag", "fetch"))
                             for c in calls))

    def test_changelog_lines_use_numeric_ticket_order(self):
        for number, sentence in (
            (9, "Fixture-tested: You can inspect a preview."),
            (10, "Fixture-tested: You can reopen a preview.")):
            self.issue(number)
            (self.repo / f"changes/{number}.md").write_text(f"kind: added\n\n{sentence}\n")
        self.commit(self.repo)
        self.save_world()
        expected = CHANGELOG.replace(
            "- Fixture-tested: You can save a preview.\n",
            "- Fixture-tested: You can inspect a preview.\n"
            "- Fixture-tested: You can reopen a preview.\n"
            "- Fixture-tested: You can save a preview.\n")
        self.approve(changelog=expected)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.stage / "export/CHANGELOG.md").read_text(), expected)

    def test_historical_scan_refuses_heading_date_different_from_plan(self):
        check = SimpleNamespace(
            args=SimpleNamespace(version=base.VERSION), plan=self.data,
            texts={"CHANGELOG.md": CHANGELOG}, used_exceptions=set(), report={})
        historical_text(check)
        check.texts["CHANGELOG.md"] = CHANGELOG.replace(
            "## 0.0.99 · 2026-01-02", "## 0.0.99 · 2026-01-03")
        with self.assertRaisesRegex(Refused, "0.0.1-R2: release needs exactly one approved dated entry"):
            historical_text(check)

    def test_sixth_line_refused_by_name(self):
        for number in (4104, 4105, 4106, 4107):
            self.issue(number)
            (self.repo / f"changes/{number}.md").write_text(
                f"kind: fixed\n\nFixture-tested: Preview case {number} passes.\n")
        self.commit(self.repo)
        self.save_world()
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertIn("more than five changelog lines", result.stderr)
        report = json.loads((self.evidence / "report.json").read_text())
        self.assertEqual(report["status"], "fail")
        reason = next(c["reason"] for c in report["checks"] if c["status"] == "fail")
        for number in (4101, 4102, 4104, 4105, 4106, 4107):
            self.assertIn(f"changes/{number}.md", result.stderr)
            self.assertIn(f"changes/{number}.md", reason)

    def test_five_lines_pass(self):
        extra = ""
        for number in (4104, 4105, 4106):
            self.issue(number)
            line = f"Fixture-tested: Preview case {number} passes."
            (self.repo / f"changes/{number}.md").write_text(f"kind: fixed\n\n{line}\n")
            extra += f"- {line}\n"
        self.commit(self.repo)
        self.save_world()
        expected = CHANGELOG.replace("- Fixture-tested: You can cancel a preview.\n",
                                    "- Fixture-tested: You can cancel a preview.\n"+extra)
        self.approve(changelog=expected)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.stage / "export/CHANGELOG.md").read_text(), expected)

    def publish_base(self, old):
        (self.public / "CHANGELOG.md").write_bytes(old.encode("utf-8"))
        self.commit(self.public)
        self.base = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.data["public_base"] = self.base
        at = old.index("## ")
        return old[:at]+ENTRY+"\n"+old[at:]

    def test_published_entries_preserved(self):
        old = "# Changelog\r\n\r\n## [0.0.98] - 2026-01-01\r\n\r\nContext: Earlier public entry.  \r\n"
        expected = self.publish_base(old)
        self.approve(changelog=expected)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        actual = (self.stage / "export/CHANGELOG.md").read_bytes()
        self.assertEqual(actual, expected.encode())
        self.assertTrue(actual.endswith(old[old.index("## "):].encode()))

    def test_existing_version_refused(self):
        expected = self.publish_base(OLD.replace("0.0.98", "0.0.99"))
        self.approve(changelog=expected)
        self.refused("version already published")

    def test_existing_bracketed_version_refused(self):
        old = OLD.replace("0.0.98 ·", "[0.0.99] -")
        expected = self.publish_base(old)
        self.approve(changelog=expected)
        self.refused("version already published")

    def test_older_version_refused(self):
        expected = self.publish_base(OLD.replace("0.0.98", "0.0.100"))
        self.approve(changelog=expected)
        self.refused("version must be newer")

    def test_generated_hash_mismatch_refused(self):
        for mismatched in ("CHANGELOG.md", "ROADMAP.md"):
            with self.subTest(mismatched=mismatched):
                self.outputs_clear()
                self.approve()
                next(f for f in self.data["files"] if f["path"] == mismatched)["sha256"] = "0"*64
                self.save_plan()
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
                self.assertIn("allowlisted source hash differs", result.stderr)
                report = json.loads((self.evidence / "report.json").read_text())
                self.assertEqual(report["status"], "fail")
                self.assertEqual(report["checks"][-1]["id"], "stage")
                self.assertEqual(report["checks"][-1]["status"], "fail")
                md = (self.evidence / "report.md").read_text()
                for path, expected in (("CHANGELOG.md", CHANGELOG), ("ROADMAP.md", ROADMAP)):
                    saved = self.stage / "generated" / path
                    self.assertTrue(saved.is_file(), f"missing generated bytes: {path}")
                    self.assertEqual(saved.read_bytes(), expected.encode("utf-8"))
                    digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
                    self.assertIn(f"{digest}  generated/{path}", md)
                    if path == mismatched:
                        self.assertIn(path, result.stderr)
                        self.assertIn(digest, result.stderr)
                        self.assertIn(digest, report["checks"][-1]["reason"])
                for repo in (self.repo, self.public):
                    self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")

    def test_stale_generated_claim_review_refused(self):
        next(r for r in self.data["claim_reviews"] if r["path"] == "ROADMAP.md")["sha256"] = "0"*64
        self.save_plan()
        self.refused("claim review is stale")

    def test_generated_private_text_refused(self):
        for bad, rule in (("Fixture-tested: You can read /private/fixture-notes.", None),
                          ('Fixture-tested: Ja' + 'ke: "synthetic decision" was recorded.', "T2")):
            with self.subTest(rule=rule):
                self.outputs_clear()
                self.world["repos/{owner}/{repo}/issues/4100"]["body"] = "## Changelog headline\n\n"+bad+"\n"
                self.save_world()
                self.approve(changelog=CHANGELOG.replace("Fixture-tested: You can preview an export.", bad))
                self.refused("privacy")
                if rule:
                    self.assertIn(rule,(self.evidence/"staged-privacy.log").read_text())

    def test_bad_inputs_fail_closed(self):
        original_world = json.loads(json.dumps(self.world))
        original_data = json.loads(json.dumps(self.data))
        cases = [
            ("bad date", lambda: self.data["entry"].update(date="2026-02-30"), "plan"),
            ("short date", lambda: self.data["entry"].update(date="2026-1-2"), "date must be ISO"),
            ("spec boolean", lambda: self.data["entry"].update(spec=True), "invalid spec"),
            ("extra field", lambda: self.data["entry"].update(headline="Guess."), "unexpected manifest shape"),
            ("newline tested", lambda: self.data["entry"].update(tested="Tested.\nUnverified."), "one public sentence"),
            ("missing tested", lambda: self.data["entry"].pop("tested"), "unexpected manifest shape"),
            ("wrong milestone", lambda: self.world["repos/{owner}/{repo}/issues/4100"]["milestone"].update(title="0.0.100"), "spec milestone/version"),
            ("missing milestone", lambda: self.world["repos/{owner}/{repo}/issues/4101"].update(milestone=None), "no version milestone"),
            ("infra milestone", lambda: self.world["repos/{owner}/{repo}/issues/4101"]["milestone"].update(title="Infra"), "no version milestone"),
            ("not a spec", lambda: self.world["repos/{owner}/{repo}/issues/4100"]["sub_issues_summary"].update(total=0), "not a parent spec"),
            ("wrong issue", lambda: self.world["repos/{owner}/{repo}/issues/4101"].update(number=4102), "invalid issue metadata"),
            ("pull request", lambda: self.world["repos/{owner}/{repo}/issues/4101"].update(pull_request={}), "invalid issue metadata"),
            ("missing headline", lambda: self.world["repos/{owner}/{repo}/issues/4100"].update(body="## Solution\n\nSomething."), "one Changelog headline"),
            ("doubled headline", lambda: self.world["repos/{owner}/{repo}/issues/4100"].update(body="## Changelog headline\n\nFirst.\n\n## Changelog headline\n\nSecond."), "one Changelog headline"),
            ("fenced headline", lambda: self.world["repos/{owner}/{repo}/issues/4100"].update(body="```md\n## Changelog headline\n\nNot the headline.\n```"), "one Changelog headline"),
            ("roadmap refused", lambda: self.world["repos/{owner}/{repo}/milestones?state=all&per_page=100"][0].update(description="You can read /private/notes.\nDone when ready."), "failed (exit 1)"),
            ("roadmap incomplete", lambda: self.world["repos/{owner}/{repo}/milestones?state=all&per_page=100"][0].update(description="You can preview an export."), "failed (exit 3)"),
        ]
        for name, change, reason in cases:
            with self.subTest(name=name):
                self.outputs_clear()
                self.world = json.loads(json.dumps(original_world))
                self.data = json.loads(json.dumps(original_data))
                change()
                self.save_world()
                self.save_plan()
                self.refused(reason)

    def test_duplicate_metadata_refused(self):
        text = self.plan.read_text().replace('"date": "2026-01-02"',
                                             '"date": "2026-01-02", "date": "2026-01-03"')
        self.plan.write_text(text)
        self.refused("duplicate manifest key")

    def test_malformed_change_refused(self):
        original = (self.repo / "changes/4101.md").read_text()
        for bad in ("kind: improved\n\nAn export.\n", "kind: fixed\n\nAn export.\nExtra.\n",
                    "kind: fixed\nversion: 0.0.99\n\nAn export.\n", "kind: fixed\n\nAn export\n",
                    "kind: fixed\n\n- An export.\n", original.rstrip("\n")):
            with self.subTest(bad=bad):
                self.outputs_clear()
                (self.repo / "changes/4101.md").write_text(bad)
                self.commit(self.repo)
                self.refused("changes/4101.md")

    def test_failed_github_read_refused(self):
        self.refused("gh api failed", FAIL_GH="1")

    def test_first_entry_without_published_changelog(self):
        (self.public / "CHANGELOG.md").unlink()
        self.commit(self.public)
        self.data["public_base"] = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        expected = "# Changelog\n\n"+ENTRY
        self.approve(changelog=expected)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.stage / "export/CHANGELOG.md").read_text(), expected)

    def test_first_entry_after_bare_changelog_title(self):
        for ending in ("", "\n", "\r\n", "\n\n", "\r\n\r\n"):
            with self.subTest(ending=repr(ending)):
                self.outputs_clear()
                (self.public / "CHANGELOG.md").write_bytes(("# Changelog"+ending).encode())
                self.commit(self.public)
                self.data["public_base"] = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
                expected = "# Changelog\n\n"+ENTRY
                self.approve(changelog=expected)
                result = self.check()
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual((self.stage / "export/CHANGELOG.md").read_bytes(), expected.encode())

    def test_missing_generated_allowlist_refused(self):
        self.data["files"] = [f for f in self.data["files"] if f["path"] != "ROADMAP.md"]
        self.save_plan()
        self.refused("generated ROADMAP.md needs its approved allowlist row")

    def test_markdown_heading_variants_refused(self):
        for prefix in ("##\t", "  ## ", "##  "):
            with self.subTest(prefix=prefix):
                self.outputs_clear()
                old = OLD.replace("## 0.0.98", prefix+"0.0.99")
                (self.public / "CHANGELOG.md").write_text(old)
                self.commit(self.public)
                self.data["public_base"] = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
                self.approve(changelog=old+ENTRY)
                self.refused("version already published")

    def test_unicode_line_separators_refused(self):
        for separator in ("\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                self.outputs_clear()
                tested = "Fixture-tested: Synthetic export fixtures pass."+separator+"Unverified: Live export remains unverified."
                self.approve(changelog=CHANGELOG.replace(
                    "Fixture-tested: Synthetic export fixtures pass; live export remains unverified.", tested))
                self.data["entry"]["tested"] = tested
                self.save_plan()
                self.refused("tested/unproven line must be one public sentence")

    def test_unrecognized_published_history_refused(self):
        old = "# Changelog\n\n0.0.99\n------\n\nContext: Earlier public entry.\n"
        (self.public / "CHANGELOG.md").write_text(old)
        self.commit(self.public)
        self.data["public_base"] = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.approve(changelog=old+ENTRY)
        self.refused("unrecognized published changelog")

    def test_setext_preamble_before_version_heading_refused(self):
        for underline, newline in (("------", "\n"), ("======", "\n"),
                                   ("   --- \t", "\n"), ("  ===\t", "\r\n")):
            with self.subTest(underline=underline, newline=repr(newline)):
                self.outputs_clear()
                old = ("# Changelog\n\n0.0.99\n"+underline+"\n\n"
                       + OLD.removeprefix("# Changelog\n\n")).replace("\n", newline)
                expected = self.publish_base(old)
                self.approve(changelog=expected)
                self.refused("unrecognized published changelog")

    def test_preamble_horizontal_rule_preserved(self):
        old = OLD.replace("# Changelog\n\n", "# Changelog\n\n---\n\n")
        expected = self.publish_base(old)
        self.approve(changelog=expected)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.stage / "export/CHANGELOG.md").read_bytes(), expected.encode())


    def prepare(self, version, specs, lines, milestones, published):
        for path in (self.repo/"changes").glob("*.md"):
            path.unlink()
        for number, kind, milestone in lines:
            title = next(t for t, n in milestones if n == milestone)
            self.world[f"repos/{{owner}}/{{repo}}/issues/{number}"] = {
                "number": number, "body": "", "milestone": {"number": milestone, "title": title},
                "sub_issues_summary": {"total": 0}}
            (self.repo/f"changes/{number}.md").write_text(
                f"kind: {kind}\n\nFixture-tested: Synthetic case {number} passes.\n")
        for number, milestone, headline in specs:
            title = next(t for t, n in milestones if n == milestone)
            self.world[f"repos/{{owner}}/{{repo}}/issues/{number}"] = {
                "number": number, "body": f"## Changelog headline\n\n{headline}\n",
                "milestone": {"number": milestone, "title": title}, "sub_issues_summary": {"total": 2}}
        word = dict(zip(("0.0.6", "0.0.7", "0.0.8", "0.0.9", "0.0.10", "0.0.11", "0.0.12", "0.0.13"),
                        ("six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen")))
        self.world["repos/{owner}/{repo}/milestones?state=all&per_page=100"] = [
            {"number": n, "title": t, "description":
             f"You can view synthetic set {word[t]}.\nDone when its synthetic check passes.",
             "html_url": f"https://github.com/example-owner/example-repo/milestone/{n}"}
            for t, n in milestones]
        self.world["repos/{owner}/{repo}/git/matching-refs/heads/release-"] = [
            {"ref": f"refs/heads/release-{t}"} for t, n in milestones]
        for t, n in milestones:
            self.world[f"repos/{{owner}}/{{repo}}/issues?milestone={n}&state=all&per_page=100"] = []
        self.save_world()
        self.git(self.repo, "checkout", "-qb", f"release-{version}")
        self.commit(self.repo)
        (self.public/"CHANGELOG.md").write_text(published)
        self.commit(self.public)
        self.data["public_base"] = self.git(self.public, "rev-parse", "HEAD").stdout.strip()

    def approve_prepared(self, version, changelog, roadmap, entry):
        self.approve(changelog=changelog, roadmap=roadmap)
        self.data["version"] = version
        self.data["entry"] = entry
        review = next(r for r in self.data["claim_reviews"] if r["path"] == "CHANGELOG.md")
        for section in changelog.split("\n## ")[1:]:
            if "[Full release on GitHub]" in section:
                review["claims"].append({"text": section[section.index("Fixture-tested:"):
                                                         section.index("\n\n[Full release")],
                                         "status": "fixture-tested", "evidence": "docs/evidence/check.md#fixture"})
        self.save_plan()

    def test_p7_combined_0_0_6_to_0_0_12_keeps_every_section_in_version_order(self):
        milestones = [("0.0.6", 2), ("0.0.7", 4), ("0.0.8", 6), ("0.0.9", 12),
                      ("0.0.10", 11), ("0.0.11", 14), ("0.0.12", 16), ("0.0.13", 17)]
        self.prepare("0.0.12", specs=[
            (4706, 2, "Fixture-tested: Version six adds synthetic sets."),
            (4707, 4, "Fixture-tested: Version seven adds synthetic helpers."),
            (4708, 6, "Fixture-tested: Version eight adds a synthetic service."),
            (4709, 12, "Fixture-tested: Version nine adds synthetic loops."),
            (4710, 11, "Fixture-tested: Version ten adds a synthetic cockpit."),
            (4711, 14, "Fixture-tested: Version eleven adds synthetic decisions."),
            (4712, 16, "Fixture-tested: Version twelve adds a synthetic terminal.")],
            lines=[(4601, "added", 16), (4602, "added", 17), (4604, "added", 11), (4606, "added", 14),
                   (4607, "added", 6), (4609, "added", 2), (4613, "fixed", 11), (4618, "added", 4),
                   (4620, "added", 12), (4625, "changed", 6), (4631, "fixed", 2), (4637, "fixed", 16),
                   (4642, "fixed", 2), (4653, "changed", 2), (4664, "security", 2)],
            milestones=milestones, published=COMBINED_BASE)
        entry = [{"version": v, "spec": 4700+int(v.split(".")[2]), "date": f"2026-02-{int(v.split('.')[2]):02d}",
                  "tested": f"Fixture-tested: Synthetic set {w} passes; live use remains unverified."}
                 for v, w in (("0.0.12", "twelve"), ("0.0.11", "eleven"), ("0.0.10", "ten"), ("0.0.9", "nine"),
                              ("0.0.8", "eight"), ("0.0.7", "seven"), ("0.0.6", "six"))]
        self.approve_prepared("0.0.12", COMBINED_CHANGELOG, COMBINED_ROADMAP, entry)
        result = self.check(version="0.0.12")
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        actual = (self.stage/"export/CHANGELOG.md").read_text()
        self.assertEqual(actual, COMBINED_CHANGELOG)
        self.assertEqual([line for line in actual.splitlines() if line.startswith("## ")],
                         ["## 0.0.12 · 2026-02-12", "## 0.0.11 · 2026-02-11", "## 0.0.10 · 2026-02-10",
                          "## 0.0.9 · 2026-02-09", "## 0.0.8 · 2026-02-08", "## 0.0.7 · 2026-02-07",
                          "## 0.0.6 · 2026-02-06", "## 0.0.5 · 2026-01-05"])
        self.assertNotIn("4602", actual)
        self.assertTrue(actual.endswith(COMBINED_BASE.removeprefix("# Changelog\n\n")))

    def test_p7_one_version_after_the_combined_release_adds_one_section(self):
        self.prepare("0.0.13", specs=[(4713, 17, "Fixture-tested: Version thirteen adds synthetic patches.")],
                     lines=[(4601, "added", 16), (4602, "fixed", 17), (4615, "added", 17)],
                     milestones=[("0.0.12", 16), ("0.0.13", 17)], published=COMBINED_CHANGELOG)
        self.world["repos/{owner}/{repo}/milestones?state=all&per_page=100"].pop(0)
        self.world["repos/{owner}/{repo}/git/matching-refs/heads/release-"].pop(0)
        self.save_world()
        self.approve_prepared("0.0.13", ONE_VERSION_CHANGELOG, ONE_VERSION_ROADMAP, {
            "spec": 4713, "date": "2026-02-13",
            "tested": "Fixture-tested: Synthetic set thirteen passes; live use remains unverified."})
        result = self.check(version="0.0.13")
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        actual = (self.stage/"export/CHANGELOG.md").read_bytes()
        self.assertEqual(actual, ONE_VERSION_CHANGELOG.encode())
        self.assertTrue(actual.endswith(COMBINED_CHANGELOG.removeprefix("# Changelog\n\n").encode()))


COMBINED_BASE = "# Changelog\n\n## 0.0.5 · 2026-01-05\n\nContext: Earlier public entry.  \n"
COMBINED_CHANGELOG = """# Changelog

## 0.0.12 · 2026-02-12

Fixture-tested: Version twelve adds a synthetic terminal.

- Fixture-tested: Synthetic case 4601 passes.
- Fixture-tested: Synthetic case 4637 passes.

Fixture-tested: Synthetic set twelve passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.11 · 2026-02-11

Fixture-tested: Version eleven adds synthetic decisions.

- Fixture-tested: Synthetic case 4606 passes.

Fixture-tested: Synthetic set eleven passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.10 · 2026-02-10

Fixture-tested: Version ten adds a synthetic cockpit.

- Fixture-tested: Synthetic case 4604 passes.
- Fixture-tested: Synthetic case 4613 passes.

Fixture-tested: Synthetic set ten passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.9 · 2026-02-09

Fixture-tested: Version nine adds synthetic loops.

- Fixture-tested: Synthetic case 4620 passes.

Fixture-tested: Synthetic set nine passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.8 · 2026-02-08

Fixture-tested: Version eight adds a synthetic service.

- Fixture-tested: Synthetic case 4607 passes.
- Fixture-tested: Synthetic case 4625 passes.

Fixture-tested: Synthetic set eight passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.7 · 2026-02-07

Fixture-tested: Version seven adds synthetic helpers.

- Fixture-tested: Synthetic case 4618 passes.

Fixture-tested: Synthetic set seven passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.6 · 2026-02-06

Fixture-tested: Version six adds synthetic sets.

- Fixture-tested: Synthetic case 4609 passes.
- Fixture-tested: Synthetic case 4631 passes.
- Fixture-tested: Synthetic case 4642 passes.
- Fixture-tested: Synthetic case 4653 passes.
- Fixture-tested: Synthetic case 4664 passes.

Fixture-tested: Synthetic set six passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.12)

## 0.0.5 · 2026-01-05

Context: Earlier public entry.  
"""
COMBINED_ROADMAP = """# OpenWiz roadmap

What is being built now, and what comes next.

## Now

- **0.0.6**, built: You can view synthetic set six.
- **0.0.7**, built: You can view synthetic set seven.
- **0.0.8**, built: You can view synthetic set eight.
- **0.0.9**, built: You can view synthetic set nine.
- **0.0.10**, built: You can view synthetic set ten.
- **0.0.11**, built: You can view synthetic set eleven.
- **0.0.12**, built: You can view synthetic set twelve.
- **0.0.13**, built: You can view synthetic set thirteen.

## Next

- None right now.
"""
ONE_VERSION_CHANGELOG = "# Changelog\n\n" + """## 0.0.13 · 2026-02-13

Fixture-tested: Version thirteen adds synthetic patches.

- Fixture-tested: Synthetic case 4602 passes.
- Fixture-tested: Synthetic case 4615 passes.

Fixture-tested: Synthetic set thirteen passes; live use remains unverified.

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.13)

""" + COMBINED_CHANGELOG.removeprefix("# Changelog\n\n")
ONE_VERSION_ROADMAP = """# OpenWiz roadmap

What is being built now, and what comes next.

## Now

- **0.0.13**, built: You can view synthetic set thirteen.

## Next

- None right now.
"""

def load_tests(loader, tests, pattern):
    return unittest.TestSuite(EntryCheck(name) for name in EntryCheck.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
