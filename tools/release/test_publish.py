#!/usr/bin/env python3
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

CLI = Path(__file__).with_name("release")
REAL_GIT = shutil.which("git")
VERSION = "0.0.99"
PUBLIC = "https://github.com/example-owner/example-release.git"
CHECKS = ["plan", "open-development-privacy", "stage", "privacy", "historical-text", "links", "claims",
          "regression-proofs", "fresh-clone"]
ENTRY = ("## 0.0.99 · 2026-11-02\n\nA synthetic release.\n\n"
         "- A fixture command prints usage.\n\n"
         "Fixture-tested only; live behaviour remains unverified.\n\n"
         "[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.99)\n")

RECORDER = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
PUBLIC = @PUBLIC@
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
verbs = {"push", "clone", "fetch", "tag", "ls-remote"}
verb = next((a for a in args if a in verbs), "read")
action = "read"
if tool == "gh":
    action = "release" if args[:2] == ["release", "create"] else "gh-read"
elif verb == "push":
    action = "tag-push" if any(":refs/tags/" in a for a in args) else "main-push"
elif verb == "tag" and "-a" in args:
    action = "tag"
elif verb == "clone" and PUBLIC in args:
    action = "readback"
elif verb == "fetch" and PUBLIC in args:
    action = "readback"
row = {"tool":tool, "args":args, "action":action}
if action == "release":
    row["notes"] = pathlib.Path(args[args.index("--notes-file")+1]).read_text()
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(row)+"\n")
if os.environ.get("FAIL_ACTION") == action:
    sys.exit(42)
if tool == "gh":
    plant = os.environ.get("GH_PLANT")
    if action == "release":
        sys.exit(0)
    if args[:2] == ["api", "repos/example-owner/example-release/immutable-releases"]:
        if plant == "off":
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({"enabled": True, "enforced_by_owner": False}))
        sys.exit(0)
    if len(args) == 2 and args[0] == "api" and args[1].startswith("repos/example-owner/example-release/releases/tags/"):
        rows = [json.loads(line) for line in open(os.environ["CALLS"])]
        created = [r for r in rows if r["action"] == "release"]
        if not created:
            sys.exit(1)
        made = created[-1]["args"]
        print(json.dumps({"tag_name": made[2], "name": made[made.index("--title")+1],
                          "body": created[-1]["notes"]+("Synthetic edit" if plant == "notes" else ""),
                          "draft": plant == "final", "prerelease": "--prerelease" in made,
                          "immutable": plant != "mutable"}))
        sys.exit(0)
    sys.exit(98)
if os.environ.get("TREE_KIND") and "ls-tree" in args:
    result = subprocess.run([REAL_GIT]+args, capture_output=True)
    sys.stdout.buffer.write(result.stdout.replace(b" blob ", b" tree ", 1))
    sys.exit(result.returncode)
if "/export.git" in " ".join(args):
    if os.environ.get("CLONE_HEAD") and args[-2:] == ["rev-parse", "HEAD"]:
        print(os.environ["CLONE_HEAD"])
        sys.exit(0)
    if os.environ.get("CLONE_FILE") and "show" in args and any(":README.md" in a for a in args):
        print("Synthetic changed disposable clone bytes")
        sys.exit(0)
if "/remote.git" in " ".join(args):
    plant = os.environ.get("READBACK_PLANT")
    if plant == "hash" and "show" in args and any(":CHANGELOG.md" in a for a in args):
        print("Synthetic changed remote bytes")
        sys.exit(0)
    if plant == "files" and "ls-tree" in args:
        result = subprocess.run([REAL_GIT]+args, capture_output=True)
        if result.returncode:
            sys.exit(result.returncode)
        sys.stdout.buffer.write(result.stdout+b"100644 blob "+b"a"*40+b"\tEXTRA.txt\0")
        sys.exit(0)
mapped = [os.environ["PUBLIC_FAKE"] if a == PUBLIC else a for a in args]
if any(a.startswith(("https://", "http://", "ssh://", "git@")) for a in mapped):
    sys.exit(97)
if action == "main-push" and os.environ.get("RACE_COMMIT"):
    result = subprocess.run([REAL_GIT, "-C", os.environ["PUBLIC_FAKE"], "update-ref",
                             "refs/heads/main", os.environ["RACE_COMMIT"]])
    if result.returncode:
        sys.exit(result.returncode)
if action == "readback" and os.environ.get("READBACK_OTHER"):
    mapped = [os.environ["READBACK_OTHER"] if a == os.environ["PUBLIC_FAKE"] else a for a in mapped]
if verb == "ls-remote" and os.environ.get("TAG_MISMATCH") and "refs/tags/v0.0.99" in args:
    result = subprocess.run([REAL_GIT]+mapped, capture_output=True)
    if result.returncode:
        sys.exit(result.returncode)
    sys.stdout.buffer.write(b"0"*40+b"\trefs/tags/v0.0.99\n" if result.stdout else b"")
    sys.exit(0)
sys.exit(subprocess.run([REAL_GIT]+mapped).returncode)
'''.replace("REAL_GIT", repr(REAL_GIT)).replace("@PUBLIC@", repr(PUBLIC))


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="publish-proof-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root/"export"
        self.remote = self.root/"public.git"
        self.bin = self.root/"bin"
        self.bin.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Synthetic", GIT_COMMITTER_NAME="Synthetic",
                        GIT_AUTHOR_EMAIL="123+fixture@users.noreply.github.com",
                        GIT_COMMITTER_EMAIL="123+fixture@users.noreply.github.com")
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        (self.repo/"README.md").write_text("# Synthetic public base\n")
        self.commit()
        self.base = self.oid("HEAD")
        self.git(self.root, "clone", "--bare", self.repo, self.remote)
        self.git(self.repo, "checkout", "-qb", "export/openwiz-"+VERSION)
        (self.repo/"README.md").write_text("# Synthetic export\n")
        (self.repo/"CHANGELOG.md").write_text("# Changelog\n\n"+ENTRY+"\n## 0.0.98 · 2026-11-01\n\nOlder fixture.\n")
        self.commit()
        self.head = self.oid("HEAD")
        self.git(self.repo, "remote", "add", "origin", PUBLIC)
        self.report = self.root/"report.json"
        self.data = {
            "schema":"openwiz.release-check.v1", "version":VERSION, "status":"pass",
            "checks":[{"id":c, "status":"pass"} for c in CHECKS], "gaps":[],
            "source_head":self.head, "public_base":self.base, "export_head":self.head,
            "export_tree":self.oid("HEAD^{tree}"), "plan_sha256":"b"*64,
            "files":[{"path":p, "sha256":hashlib.sha256((self.repo/p).read_bytes()).hexdigest(),
                      "mode":"100644"} for p in ("CHANGELOG.md", "README.md")],
            "live_pending":0, "publishable":True, "scan_exceptions":[]}
        self.save()
        for name in ("git", "gh"):
            path = self.bin/name
            path.write_text(RECORDER)
            path.chmod(0o755)
        self.env.update(PATH=str(self.bin)+os.pathsep+self.env["PATH"],
                        CALLS=str(self.root/"calls.jsonl"), PUBLIC_FAKE=str(self.remote))

    def git(self, cwd, *args):
        r = subprocess.run([REAL_GIT, "-C", str(cwd), *map(str,args)], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self):
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Synthetic fixture")

    def oid(self, ref):
        return self.git(self.repo, "rev-parse", ref)

    def save(self):
        self.report.write_text(json.dumps(self.data))

    def publish(self, approval="publish "+VERSION, report=True, backfill=False, version=VERSION, **env):
        args = ["python3", str(CLI), "publish", version, "--repo", str(self.repo)]
        if approval is not None:
            args += ["--approval", approval]
        if report:
            args += ["--report", str(self.report)]
        if backfill:
            args += ["--backfill"]
        r = subprocess.run(args, env=dict(self.env, **env), capture_output=True, text=True)
        return r

    def calls(self):
        path = self.root/"calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def writes(self):
        return [r for r in self.calls() if r["action"] in ("main-push", "tag", "tag-push", "release")]

    def refused(self, result, reason):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stderr)
        self.assertEqual(self.writes(), [])

    def clear(self):
        (self.root/"calls.jsonl").unlink(missing_ok=True)

    def checked_changelog(self, text):
        (self.repo/"CHANGELOG.md").write_text(text)
        self.git(self.repo, "add", "CHANGELOG.md")
        self.git(self.repo, "commit", "--amend", "--no-edit")
        self.head = self.oid("HEAD")
        self.data.update(export_head=self.head, export_tree=self.oid("HEAD^{tree}"))
        self.data["files"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
        self.save()

    def test_explicit_report_required_before_any_call(self):
        self.refused(self.publish(report=False), "passing report is required")
        self.assertEqual(self.calls(), [])

    def test_failed_check_in_passing_report_writes_nothing(self):
        self.data["checks"][0]["status"] = "fail"
        self.save()
        self.refused(self.publish(), "failed check")

    def test_disposable_clone_head_is_rechecked(self):
        self.refused(self.publish(CLONE_HEAD=self.base), "export head moved")

    def test_disposable_clone_files_are_rechecked(self):
        self.refused(self.publish(CLONE_FILE="1"), "file hash differs from report")

    def test_non_blob_tree_entry_writes_nothing(self):
        self.refused(self.publish(TREE_KIND="1"), "symlink or submodule refused")

    def test_unknown_scan_exception_rule_writes_nothing(self):
        self.data["scan_exceptions"] = [dict(
            path="README.md", sha256=self.data["files"][1]["sha256"], rule="unknown")]
        self.save()
        self.refused(self.publish(), "unknown scan exception")

    def test_empty_checked_changelog_entry_writes_nothing(self):
        self.checked_changelog("# Changelog\n\n## 0.0.99 · 2026-11-02\n\n")
        self.refused(self.publish(), "empty checked changelog entry")

    def test_invalid_version_with_matching_report_and_entry_writes_nothing(self):
        version = "00.0.99"
        self.data["version"] = version
        self.checked_changelog((self.repo/"CHANGELOG.md").read_text().replace(VERSION, version))
        self.refused(self.publish(version=version, approval="publish "+version), "version must be N.N.N")
        self.assertEqual(self.calls(), [])

    def test_readback_descendant_with_identical_tree_stops_before_tag(self):
        self.git(self.repo, "commit", "--allow-empty", "-qm", "Synthetic descendant")
        later = self.oid("HEAD")
        self.assertEqual(self.oid("HEAD^{tree}"), self.data["export_tree"])
        other = self.root/"descendant.git"
        self.git(self.root, "clone", "--bare", self.repo, other)
        self.git(other, "update-ref", "refs/heads/main", later)
        self.git(self.repo, "checkout", "--detach", self.head)
        result = self.publish(READBACK_OTHER=str(other))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("read-back failed: remote head differs", result.stderr)
        self.assertEqual([r["action"] for r in self.writes()], ["main-push"])

    def test_gates_write_nothing(self):
        for approval in (None, "", "publish 0.0.98", "Publish "+VERSION,
                         "publish "+VERSION+"\n", " publish "+VERSION):
            with self.subTest(approval=approval):
                self.refused(self.publish(approval=approval), "approval")
                self.assertEqual(self.calls(), [])
        self.refused(self.publish(report=False), "report")
        self.report.unlink()
        self.refused(self.publish(), "report")

    def test_report_shapes_write_nothing(self):
        original = copy.deepcopy(self.data)
        variants = [([], "report"), (dict(original, status="fail"), "report"),
                    (dict(original, version="0.0.98"), "report"),
                    (dict(original, publishable=1), "report"),
                    (dict(original, live_pending=True), "report"),
                    (dict(original, checks=[]), "report"),
                    (dict(original, surprise=True), "report")]
        for key in original:
            value = copy.deepcopy(original)
            del value[key]
            variants.append((value, "report"))
        for change in ({"sha256":"0"*64}, {"mode":"120000"}, {"path":"../private"}):
            value = copy.deepcopy(original)
            value["files"][0].update(change)
            variants.append((value, "report" if change.get("sha256") != "0"*64 else "hash"))
        for data,reason in variants:
            with self.subTest(data=data):
                self.report.write_text(json.dumps(data))
                self.refused(self.publish(), reason)
                self.clear()
        self.report.write_text(json.dumps(original)[:-1]+',"status":"pass"}')
        self.refused(self.publish(), "report")

    def test_local_mismatches_write_nothing(self):
        self.data["export_head"] = self.base
        self.save()
        self.refused(self.publish(), "head")
        self.data["export_head"] = self.head
        self.data["export_tree"] = "0"*40
        self.save()
        self.clear()
        self.refused(self.publish(), "tree")
        self.data["export_tree"] = self.oid("HEAD^{tree}")
        self.save()
        (self.repo/"README.md").write_text("Uncommitted fixture\n")
        self.clear()
        self.refused(self.publish(), "clean")

    def test_same_tree_new_head_writes_nothing(self):
        self.git(self.repo, "commit", "--allow-empty", "-qm", "Synthetic later head, identical tree")
        self.assertEqual(self.oid("HEAD^{tree}"), self.data["export_tree"])
        self.refused(self.publish(), "head")

    def test_unchecked_intermediate_parent_writes_nothing(self):
        self.git(self.repo, "checkout", "--detach", self.base)
        (self.repo/"UNCHECKED.txt").write_text("Synthetic unchecked intermediate content.\n")
        self.commit()
        self.git(self.repo, "read-tree", "--reset", "-u", self.head)
        self.commit()
        self.head = self.oid("HEAD")
        self.assertEqual(self.oid("HEAD^{tree}"), self.data["export_tree"])
        self.data["export_head"] = self.head
        self.save()
        self.refused(self.publish(), "git")
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.base)
        self.assertEqual(self.git(self.remote, "tag", "--list"), "")

    def historical_publication(self):
        (self.repo/"README.md").write_text("# Synthetic later public version\n")
        (self.repo/"LATER.txt").write_text("Only the later version contains this file.\n")
        changelog = self.repo/"CHANGELOG.md"
        changelog.write_text(changelog.read_text().replace("# Changelog\n\n",
                            "# Changelog\n\n## 0.0.100 · 2026-11-03\n\nLater fixture.\n\n", 1))
        self.commit()
        later = self.oid("HEAD")
        self.git(self.repo, "push", self.remote, later+":refs/heads/main")
        self.git(self.repo, "checkout", "--detach", self.head)
        self.historical_report(later)
        return later

    def historical_report(self, main):
        self.data.update(source_head=self.head, historical={"public_main": main})
        self.save()

    def test_backfill_tags_exact_historical_commit_without_main_push(self):
        later = self.historical_publication()
        r = self.publish(backfill=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["action"] for c in self.calls() if c["action"] not in ("read", "gh-read")],
                         ["readback", "tag", "tag-push", "release"])
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), later)
        self.assertEqual(self.git(self.remote, "cat-file", "-t", "refs/tags/v"+VERSION), "tag")
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/tags/v"+VERSION+"^{}"), self.head)
        self.assertEqual(self.writes()[-1]["notes"], ENTRY)

    def test_backfill_keeps_approval_report_and_exact_head_gates(self):
        self.historical_publication()
        self.refused(self.publish(backfill=True, approval=None), "approval")
        self.refused(self.publish(backfill=True, report=False), "report")
        self.data["status"] = "fail"
        self.save()
        self.refused(self.publish(backfill=True), "report")
        self.data["status"] = "pass"
        self.save()
        self.git(self.repo, "commit", "--allow-empty", "-qm", "Synthetic different head")
        self.refused(self.publish(backfill=True), "head")

    def test_backfill_refuses_unpublished_commit_even_with_same_tree(self):
        self.git(self.repo, "push", self.remote, self.head+":refs/heads/unreleased")
        sibling = self.git(self.repo, "commit-tree", self.head+"^{tree}", "-p", self.base,
                           "-m", "Synthetic same public tree, different historical commit")
        self.git(self.repo, "push", self.remote, sibling+":refs/heads/main")
        self.assertEqual(self.git(self.remote, "rev-parse", "main^{tree}"), self.data["export_tree"])
        self.historical_report(sibling)
        r = self.publish(backfill=True)
        self.refused(r, "reachable")
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), sibling)

    def test_backfill_readback_mismatch_and_failed_steps_stop(self):
        self.historical_publication()
        sequence = ["readback", "tag", "tag-push", "release"]
        for failed in sequence:
            with self.subTest(failed=failed):
                self.git(self.remote, "update-ref", "-d", "refs/tags/v"+VERSION)
                self.clear()
                r = self.publish(backfill=True, FAIL_ACTION=failed)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("refused", r.stderr)
                self.assertEqual([c["action"] for c in self.calls() if c["action"] not in ("read", "gh-read")],
                                 sequence[:sequence.index(failed)+1])
        self.git(self.remote, "update-ref", "-d", "refs/tags/v"+VERSION)
        self.clear()
        self.refused(self.publish(backfill=True, READBACK_PLANT="hash"), "read-back")

    def test_dispatch_preserves_check_and_exposes_backfill(self):
        for command, expected in (("check", "--staging"), ("publish", "--backfill")):
            r = subprocess.run(["python3", str(CLI), command, "--help"], env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(expected, r.stdout)
        self.assertEqual(self.calls(), [])

    def test_file_list_modes_and_placeholders_write_nothing(self):
        original = copy.deepcopy(self.data)
        variants = [original["files"][:1], original["files"]*2,
                    original["files"]+[{"path":"extra.txt", "sha256":"c"*64, "mode":"100644"}],
                    [dict(original["files"][0], mode="100755"), original["files"][1]]]
        for files in variants:
            with self.subTest(files=files):
                self.data = dict(original, files=files)
                self.save()
                self.refused(self.publish(), "report")
                self.clear()
        self.data = original
        for plant in ("LIVE-PENDING", "PUBLICATION-DATE"):
            (self.repo/"README.md").write_text(plant+"\n")
            self.commit()
            self.git(self.repo, "reset", "--soft", self.base)
            self.git(self.repo, "commit", "-qm", "Synthetic placeholder")
            self.data.update(export_head=self.oid("HEAD"), export_tree=self.oid("HEAD^{tree}"))
            self.data["files"][1]["sha256"] = hashlib.sha256((self.repo/"README.md").read_bytes()).hexdigest()
            self.save()
            self.refused(self.publish(), "placeholder")
            self.clear()

    def test_source_push_config_cannot_add_refs_or_rewrite_destination(self):
        self.git(self.repo, "config", "push.followTags", "true")
        self.git(self.repo, "config", "url.https://unexpected.invalid/.insteadOf", "https://github.com/")
        self.git(self.repo, "tag", "-a", "unapproved", self.base, "-m", "Synthetic unused tag")
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git(self.remote, "tag", "--list"), "v"+VERSION)

    def test_publish_sequence_and_exact_entry(self):
        before_refs = self.git(self.repo, "show-ref")
        before_files = {p.name:p.read_bytes() for p in (self.repo/"CHANGELOG.md", self.repo/"README.md", self.report)}
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stderr)
        actions = [c["action"] for c in self.calls() if c["action"] not in ("read", "gh-read")]
        self.assertEqual(actions, ["main-push", "readback", "tag", "tag-push", "release"])
        writes = self.writes()
        for row in (writes[0], writes[2]):
            self.assertIn("--no-follow-tags", row["args"])
            self.assertFalse(any(a.startswith(("+", "--force")) for a in row["args"]))
        self.assertIn(self.head+":refs/heads/main", writes[0]["args"])
        self.assertIn("-a", writes[1]["args"])
        self.assertIn(self.head, writes[1]["args"])
        self.assertIn("refs/tags/v"+VERSION+":refs/tags/v"+VERSION, writes[2]["args"])
        self.assertEqual(writes[3]["notes"], ENTRY)
        self.assertIn("--verify-tag", writes[3]["args"])
        self.assertIn("--prerelease", writes[3]["args"])
        self.assertIn("example-owner/example-release", writes[3]["args"])
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.head)
        self.assertEqual(self.git(self.remote, "cat-file", "-t", "refs/tags/v"+VERSION), "tag")
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/tags/v"+VERSION+"^{}"), self.head)
        self.assertEqual(self.git(self.repo, "show-ref"), before_refs)
        self.assertEqual({p.name:p.read_bytes() for p in (self.repo/"CHANGELOG.md", self.repo/"README.md", self.report)}, before_files)

    def test_failures_stop(self):
        sequence = ["main-push", "readback", "tag", "tag-push", "release"]
        for failed in sequence:
            with self.subTest(failed=failed):
                self.git(self.remote, "update-ref", "refs/heads/main", self.base)
                self.git(self.remote, "update-ref", "-d", "refs/tags/v"+VERSION)
                self.clear()
                r = self.publish(FAIL_ACTION=failed)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("refused", r.stderr)
                actions = [c["action"] for c in self.calls() if c["action"] not in ("read", "gh-read")]
                self.assertEqual(actions, sequence[:sequence.index(failed)+1])

    def test_remote_refusals(self):
        self.git(self.remote, "update-ref", "refs/tags/v"+VERSION, self.base)
        self.refused(self.publish(), "tag")
        self.git(self.remote, "update-ref", "-d", "refs/tags/v"+VERSION)
        self.git(self.repo, "push", self.remote, self.head+":refs/heads/main")
        self.clear()
        self.refused(self.publish(), "base")

    def test_readback_mismatches_stop_before_tag(self):
        other = self.root/"other.git"
        self.git(self.root, "clone", "--bare", self.remote, other)
        r = self.publish(READBACK_OTHER=str(other))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("read-back", r.stderr)
        self.assertEqual([r["action"] for r in self.writes()], ["main-push"])

    def test_readback_checks_every_report_file(self):
        for plant in ("hash", "files"):
            with self.subTest(plant=plant):
                self.git(self.remote, "update-ref", "refs/heads/main", self.base)
                self.clear()
                r = self.publish(READBACK_PLANT=plant)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("read-back", r.stderr)
                self.assertEqual([r["action"] for r in self.writes()], ["main-push"])

    def test_non_fast_forward_race_stops_without_force(self):
        sibling = self.git(self.repo, "commit-tree", self.base+"^{tree}", "-p", self.base,
                           "-m", "Synthetic concurrent public change")
        self.git(self.repo, "push", self.remote, sibling+":refs/heads/concurrent")
        self.git(self.remote, "update-ref", "-d", "refs/heads/concurrent")
        r = self.publish(RACE_COMMIT=sibling)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stderr)
        self.assertEqual([r["action"] for r in self.writes()], ["main-push"])
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), sibling)

    def test_tag_readback_mismatch_stops_before_release(self):
        r = self.publish(TAG_MISMATCH="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("remote annotated tag", r.stderr)
        self.assertEqual([r["action"] for r in self.writes()], ["main-push", "tag", "tag-push"])

    def test_annotation_identity_is_checked_before_any_write(self):
        self.git(self.repo, "commit", "--amend", "--no-edit", "--author",
                 "Synthetic <fixture@example.invalid>")
        self.data["export_head"] = self.data["source_head"] = self.oid("HEAD")
        self.save()
        self.refused(self.publish(), "identity")


if __name__ == "__main__":
    unittest.main(verbosity=2)
