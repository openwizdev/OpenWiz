#!/usr/bin/env python3
"""#1191: approved product paths, alias links, historical verification and backfill.

Synthetic repositories only. git delegates to the real binary behind a recording
fake; cargo, npm, node and gh are fakes. Nothing here can reach a real remote.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
import test as base
import test_entry
import test_publish

VERSION = base.VERSION
ENTRY = ("## 0.0.99 · 2026-11-02\n\n"
         "Fixture-tested: The synthetic command prints usage. [Evidence](docs/evidence/check.md#fixture).\n")
OLDER = "## 0.0.98 · 2026-11-01\n\nContext: An older synthetic entry.\n"
CHANGELOG = "# Changelog\n\n"+ENTRY+"\n"+OLDER
PRODUCT = {
    "skills/alpha/SKILL.md": "# Alpha\n\nFixture-tested: A synthetic skill prints its name. [Evidence](../../docs/evidence/check.md#fixture).\n",
    "skills/alpha/scripts/run.sh": "#!/bin/sh\necho synthetic\n",
    "skills/README.md": "# Skills\n\nContext: One synthetic skill folder.\n",
    ".claude-plugin/plugin.json": '{"name":"synthetic","skills":["./skills/alpha"]}\n',
    ".claude-plugin/marketplace.json": '{"name":"synthetic","plugins":[{"name":"synthetic","source":"./"}]}\n',
    "GLOSSARY.md": "# Glossary\n\nContext: Synthetic terms only.\n",
    "docs/fleets.md": "# Fleets\n\nContext: Synthetic fleet notes.\n",
}
ALIAS = ".agents/skills/alpha"
TARGET = "../../skills/alpha"
TESTING = ("# Testing and gaps\n\n## LIVE-0.0.99\n\n"
           "Live observation — LIVE-0.0.99: a synthetic owner run held the synthetic claim; its gaps are listed here.\n")
RELEASING = "# Releasing\n\nContext: The reviewed, already-published synthetic procedure.\n"
LABELLED = re.compile(r"^(Fixture-tested|Unverified|Live-observation|Source-inspection):")


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def reviews(texts):
    """Explicit dispositions for every prose line of each Markdown document."""
    result = []
    for path, text in sorted(texts.items()):
        if not path.endswith(".md"):
            continue
        claims = []
        fenced = False
        for line in text.splitlines():
            if re.match(r"\s*(```|~~~)", line):
                fenced = not fenced
                continue
            if fenced or not line.strip() or line.startswith("#"):
                continue
            label = LABELLED.match(line)
            if label:
                claims.append({"text": line, "status": label[1].lower(),
                               "evidence": "docs/evidence/check.md#fixture"})
            elif "Live observation — " in line:
                continue  # a reviewed label form or the evidence document, bound below
            else:
                claims.append({"text": line, "status": "context", "evidence": ""})
        if path == "docs/testing.md":
            claims.append({"text": TESTING.splitlines()[-1], "status": "context", "evidence": ""})
        result.append({"path": path, "sha256": digest(text), "claims": claims})
    return result


# The real tests/Cargo.toml shape (published 5d069b02 and main): explicit targets only.
WORKSPACE = '\n[workspace]\nmembers = [\n    "crates/core",\n    "tests",\n]\n'
TESTS_MANIFEST = """[package]
name = "openwiz-tests"
version.workspace = true
edition.workspace = true
publish.workspace = true
autobins = false
autotests = false
autoexamples = false

# The fake room-cli the tests run in place of the real one.
[[bin]]
name = "fake-room-cli"
path = "fake-room-cli/main.rs"
test = false

[[test]]
name = "messaging"
path = "messaging/main.rs"

# Synthetic: the successor's target.
[[test]]
name = "new-thread"
path = "new-thread/main.rs"

[dependencies]
serde_json.workspace = true
"""


class Backfill(base.ReleaseCheck):
    def setUp(self):
        super().setUp()
        self.git(self.public,"remote","add","origin",test_publish.PUBLIC)
        self.real_git = shutil.which("git", path=os.defpath+":/usr/bin:/usr/local/bin")

    # ----- normal staging with approved product rows -----

    def product_source(self, link_target=TARGET, alias=ALIAS):
        for path, text in PRODUCT.items():
            p = self.repo/path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.repo/"skills/alpha/scripts/run.sh").chmod(0o755)
        link = self.repo/alias
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        elif link.is_dir():
            shutil.rmtree(link)
        os.symlink(link_target, link)
        if self.git(self.repo, "status", "--porcelain").stdout:
            self.commit(self.repo)
        self.replan()
        self.data["files"].append({"path": alias, "source": alias, "sha256": digest(link_target),
                                   "mode": "120000"})
        self.data["claim_reviews"] = [r for r in self.data["claim_reviews"] if r["path"] not in PRODUCT]
        self.data["claim_reviews"] += reviews({p: t for p, t in PRODUCT.items()})
        self.save_plan()

    def test_r1_product_paths_and_alias_stage_from_tracked_sources(self):
        self.product_source()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        rows = {f["path"]: f for f in report["files"]}
        for path in PRODUCT:
            self.assertIn(path, rows)
        self.assertEqual(rows[ALIAS], {"path": ALIAS, "sha256": digest(TARGET), "mode": "120000"})
        self.assertEqual(rows["skills/alpha/scripts/run.sh"]["mode"], "100755")
        export = self.stage/"export"
        listing = self.git(export, "ls-tree", "HEAD", ALIAS).stdout
        self.assertTrue(listing.startswith("120000 blob "), listing)
        self.assertEqual(self.git(export, "cat-file", "-p", "HEAD:"+ALIAS).stdout, TARGET)
        self.assertEqual(os.readlink(self.stage/"fresh"/ALIAS), TARGET)

    # catches: a source release after #555's cut refusing the tracked WizSkills
    # link, or the harness aliases that now resolve through it.
    def test_r1_the_wizskills_link_and_aliases_through_it_stage(self):
        self.product_source(".wizskills/skills", "skills")
        link = self.repo/ALIAS
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(TARGET, link)
        self.commit(self.repo)
        self.data["files"] = [f for f in self.data["files"] if not f["path"].startswith("skills/")]
        self.data["claim_reviews"] = [r for r in self.data["claim_reviews"] if not r["path"].startswith("skills/")]
        self.data["files"].append({"path": ALIAS, "source": ALIAS, "sha256": digest(TARGET), "mode": "120000"})
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        export = self.stage/"export"
        self.assertEqual(self.git(export, "cat-file", "-p", "HEAD:skills").stdout, ".wizskills/skills")
        self.assertEqual(self.git(export, "cat-file", "-p", "HEAD:"+ALIAS).stdout, TARGET)
        # The skills link must point at the install exactly, never elsewhere.
        self.outputs_clear()
        (self.repo/"skills").unlink()
        os.symlink(".wizskills/other", self.repo/"skills")
        self.commit(self.repo)
        for row in self.data["files"]:
            if row["path"] == "skills":
                row["sha256"] = digest(".wizskills/other")
        self.save_plan()
        self.refused("link")

    def test_r1_product_namespaces_need_explicit_rows_and_other_private_paths_stay_refused(self):
        cases = [("private/notes.md", "forbidden public path"),
                 ("docs/grills/synthetic.md", "private process document"),
                 ("skills/alpha/.env", "forbidden public path"),
                 ("tools/war-room/node_modules/synthetic.txt", "forbidden public path")]
        for path, reason in cases:
            with self.subTest(path=path):
                self.outputs_clear()
                self.reset_fixture()
                p = self.repo/path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("Context: Synthetic private file.\n")
                self.commit(self.repo)
                self.replan()
                self.save_plan()
                self.refused(reason)
                self.assertFalse((self.stage/"export").exists())
        # A product destination fed from a different, private source is refused.
        self.reset_fixture()
        self.outputs_clear()
        self.product_source()
        row = next(f for f in self.data["files"] if f["path"] == "GLOSSARY.md")
        (self.repo/"private").mkdir(exist_ok=True)
        (self.repo/"private/GLOSSARY.md").write_text(PRODUCT["GLOSSARY.md"])
        self.commit(self.repo)
        row["source"] = "private/GLOSSARY.md"
        self.save_plan()
        self.refused("release rows must name their own tracked path")

    def test_r2_unsafe_dangling_cyclic_and_unapproved_links_are_refused(self):
        cases = [("/home/synthetic/skills/alpha", ALIAS, "link"),
                 ("../../../skills/alpha", ALIAS, "link"),
                 ("../../skills/beta", ALIAS, "link"),
                 ("../../.agents/skills/alpha", ALIAS, "link"),
                 (".", ALIAS, "link"),
                 ("../../skills/alpha/", ALIAS, "link"),
                 (TARGET, "skills/alias", "link")]
        for target, alias, reason in cases:
            with self.subTest(target=target, alias=alias):
                self.outputs_clear()
                self.git(self.repo, "rm", "-rq", "--ignore-unmatch", ".agents", "skills/alias")
                self.product_source(target, alias)
                self.refused(reason)
        # A link the plan does not explicitly approve as mode 120000.
        self.outputs_clear()
        self.git(self.repo, "rm", "-rq", "--ignore-unmatch", ".agents", "skills/alias")
        self.product_source()
        for row in self.data["files"]:
            row.pop("mode", None)
        self.save_plan()
        self.refused("link")
        # The alias target folder must itself be exported.
        self.outputs_clear()
        self.git(self.repo,"rm","-rq","skills/alpha")
        self.commit(self.repo)
        self.data["files"] = [f for f in self.data["files"] if not f["path"].startswith("skills/alpha/")]
        self.data["claim_reviews"] = [r for r in self.data["claim_reviews"]
                                      if not r["path"].startswith("skills/alpha/")]
        self.data["files"][-1]["mode"] = "120000"
        self.save_plan()
        self.refused("dangling")

    def test_r2_submodules_are_refused(self):
        self.product_source()
        (self.repo/"skills/beta/sub").mkdir(parents=True)
        self.git(self.repo, "update-index", "--add", "--cacheinfo", "160000,"+"a"*40+",skills/beta/sub")
        self.git(self.repo, "commit", "-qm", "Synthetic submodule")
        self.data["files"].append({"path": "skills/beta/sub", "source": "skills/beta/sub", "sha256": "0"*64})
        self.save_plan()
        self.refused("open-development-privacy")
        self.assertIn("READ ",(self.evidence/"open-development-privacy.log").read_text())

    def test_r2_public_base_with_links_can_be_restaged(self):
        """A release after 0.0.5 starts from a public base that already has aliases."""
        self.product_source()
        for path, text in PRODUCT.items():
            p = self.public/path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.public/".agents/skills").mkdir(parents=True)
        os.symlink(TARGET, self.public/ALIAS)
        self.commit(self.public)
        self.base = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.data["public_base"] = self.base
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_r8_fenced_template_links_are_not_links_but_prose_links_still_resolve(self):
        fenced = "# Guide\n\n```md\n| [<topic>](<YYYY-MM-DD>-<topic>.md) | **open** |\n```\n\n~~~\n[x](missing.md)\n~~~\n"
        self.plant("docs/guide.md", fenced)
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        self.outputs_clear()
        self.plant("docs/guide.md", "# Guide\n\nFixture-tested: See [x](missing.md).\n")
        self.refused("link target missing")
        self.outputs_clear()
        self.plant("docs/guide.md", "# Guide\n\n```md\n\nFixture-tested: See [x](missing.md).\n")
        self.refused("link target missing")  # an unclosed fence hides nothing

    def test_r8_directory_links_resolve_only_to_exported_folders(self):
        self.plant("docs/guide.md", "# Guide\n\nFixture-tested: The [evidence folder](evidence/) and [docs](../docs) hold it.\n")
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        for link, reason in (("nothing/", "link target missing"), ("evidence/#fixture", "link fragment missing"),
                             ("../../outside/", "link escapes public tree")):
            with self.subTest(link=link):
                self.outputs_clear()
                self.plant("docs/guide.md", f"# Guide\n\nFixture-tested: See [x]({link}).\n")
                self.refused(reason)

    def test_r9_root_agents_guide_stays_at_its_own_release_path(self):
        guide = "# Agent guide\n\nContext: Synthetic public agent guide.\n"
        self.plant("AGENTS.md", guide)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.stage/"export/AGENTS.md").read_text(), guide)
        row = next(f for f in self.data["files"] if f["path"] == "AGENTS.md")
        for source in ("tools/release/public/AGENTS.md", "public/AGENTS.md"):
            with self.subTest(source=source):
                self.outputs_clear()
                row["source"] = source
                self.save_plan()
                self.refused("release rows must name their own tracked path")

    def test_r9_reviewed_unlabelled_claims_keep_status_and_evidence(self):
        self.plant("README.md", "# Synthetic\n\n- `openwiz` prints its usage.\n")
        review = next(r for r in self.data["claim_reviews"] if r["path"] == "README.md")
        claim = {"text": "- `openwiz` prints its usage.", "status": "fixture-tested", "label": "",
                 "evidence": "docs/evidence/check.md#fixture"}
        review["claims"] = [claim]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        for change, reason in (({"label": None}, "claim needs its public status label"),
                               ({"evidence": ""}, "claim evidence missing"),
                               ({"evidence": "docs/missing.md"}, "link target missing"),
                               ({"status": "context", "evidence": ""}, "context rows carry no label"),
                               ({"status": "live-observation"}, "live capability needs published live evidence"),
                               ({"label": " "}, "label")):
            with self.subTest(change=change):
                self.outputs_clear()
                row = dict(claim, **change)
                if row["label"] is None:
                    del row["label"]
                review["claims"] = [row]
                self.save_plan()
                self.refused(reason)

    def test_r9_username_only_urls_need_an_exact_review_and_passwords_stay_reserved(self):
        url = "https://user@github.com/a/b"
        self.plant("src/hosts.rs", f'const REJECTED: &str = "{url}";\n')
        self.refused("URL credentials")
        self.outputs_clear()
        self.allow_url("src/hosts.rs", url)
        row = next(f for f in self.data["files"] if f["path"] == "src/hosts.rs")
        self.data["scan_exceptions"].append({"path": "src/hosts.rs", "sha256": row["sha256"],
                                             "rule": "personal", "value": "user@github.com"})
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        for other, reason in (("https://user:pass@github.com/a/b", "URL credentials"),
                              ("https://user:@github.com/a/b", "URL credentials")):
            with self.subTest(url=other):
                self.outputs_clear()
                self.plant("src/hosts.rs", f'const REJECTED: &str = "{other}";\n')
                self.allow_url("src/hosts.rs", other)
                self.refused(reason)

    def regression_successors(self):
        self.regression_fixture()
        # The read/send scrub proofs now live under another name and target.
        (self.repo/"tests/messaging/environment.rs").unlink()
        (self.repo/"tests/new-thread").mkdir(parents=True)
        (self.repo/"tests/new-thread/n02_no_rewrite.rs").write_text(
            "#[test]\nfn every_call_runs_without_the_thread_context() {}\n\n"
            "fn helper_named_like_a_test() {}\n")
        (self.repo/"tests/new-thread/main.rs").write_text("mod n02_no_rewrite;\n")
        (self.repo/"tests/new-thread/n03_undeclared.rs").write_text(
            "#[test]\nfn every_call_runs_without_the_thread_context() {}\n")
        # The real shape: a workspace member with explicit [[test]] targets only.
        self.root_manifest = (self.repo/"Cargo.toml").read_text()
        (self.repo/"Cargo.toml").write_text(self.root_manifest+WORKSPACE)
        (self.repo/"tests/Cargo.toml").write_text(TESTS_MANIFEST)
        self.commit(self.repo)
        self.replan()

    def test_r10_approved_regression_successors_run_and_nothing_is_dropped(self):
        self.regression_successors()
        self.refused("0.0.3-R3: missing public regression proof")
        self.outputs_clear()
        successor = {"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                     "tests": ["every_call_runs_without_the_thread_context"]}
        self.data["regressions"] = [successor]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        calls = [json.loads(s) for s in (self.root/"calls.jsonl").read_text().splitlines()]
        exact = "n02_no_rewrite::every_call_runs_without_the_thread_context"
        runs = [(c["args"], Path(c["cwd"]).name) for c in calls if c["tool"] == "cargo" and c["args"][-1] == exact]
        # R3: the one declared test, by its full identity and --exact, never a substring filter:
        # first in the nonce scratch clone (re-check 5, Jake's ruling (a)), then unchanged.
        args = ["test", "--locked", "-p", "openwiz-tests", "--test", "new-thread", "--", "--exact", exact]
        self.assertEqual(runs, [(args, "nonce"), (args, "fresh")])
        self.assertFalse([c for c in calls if "every_read_runs_without_the_thread_context" in c["args"]])
        for change, reason in (({"id": "0.0.3-R9"}, "unknown regression id"),
                               ({"tests": ["missing_test"]}, "missing named regression"),
                               ({"tests": []}, "regression successor"),
                               ({"proof": "tests/new-thread/absent.rs"}, "missing public regression proof"),
                               ({"proof": "tools/war-room/test/x.mjs"}, "regression successor"),
                               ({"tests": ["helper_named_like_a_test"]}, "missing named regression"),
                               ({"proof": "tests/new-thread/n03_undeclared.rs"}, "not a module of its test target")):
            with self.subTest(change=change):
                self.outputs_clear()
                self.data["regressions"] = [dict(successor, **change)]
                self.save_plan()
                self.refused(reason)
        self.outputs_clear()
        self.data["regressions"] = [successor, successor]
        self.save_plan()
        self.refused("duplicate regression successor")
        # A planted failure in the successor still fails its id.
        self.outputs_clear()
        self.data["regressions"] = [successor]
        self.save_plan()
        self.plant("regression-failure.txt", exact)
        self.data["regressions"] = [successor]
        self.save_plan()
        self.refused("0.0.3-R3")

    def test_r16_successor_module_is_bound_to_its_declared_file(self):
        """Re-check R3: the declared proof file is the module that runs, lexically checked."""
        self.regression_successors()
        successor = {"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                     "tests": ["every_call_runs_without_the_thread_context"]}
        self.data["regressions"] = [successor]
        self.save_plan()
        (self.repo/"tests/new-thread/actual.rs").write_text(
            "#[test]\nfn every_call_runs_without_the_thread_context() {}\n")
        mains = {
            "path override": '#[path = "actual.rs"]\nmod n02_no_rewrite;\n',
            "cfg_attr path override": '#[cfg_attr(all(), path = "actual.rs")]\npub mod n02_no_rewrite;\n',
            "block comment": "/* mod n02_no_rewrite; */\nmod actual;\n",
            "nested block comment": "/* /* */ mod n02_no_rewrite; */\nmod actual;\n",
            "line comment": "// mod n02_no_rewrite;\nmod actual;\n",
            "multi-line block comment": "/*\nmod n02_no_rewrite;\n*/\nmod actual;\n",
            "string": 'const S: &str = "mod n02_no_rewrite;";\nmod actual;\n',
            "raw string": 'const S: &str = r#"\nmod n02_no_rewrite;\n"#;\nmod actual;\n',
            "nested": "mod outer {\n    mod n02_no_rewrite;\n}\n",
            "inline and file": "mod n02_no_rewrite;\nmod n02_no_rewrite {}\n",
            "unterminated comment": "mod n02_no_rewrite;\n/* never closed\n",
            # +1 round (orchestrator's diagnosis): an allowlist of top-level forms.
            "macro redirect": ('macro_rules! redirect {\n    (mod $name:ident;) => { #[path = "actual.rs"] mod $name; };\n}\n'
                               "redirect!(mod n02_no_rewrite;);\n"),
            "include": 'include!("actual.rs");\nmod n02_no_rewrite;\n',
            "unused macro_rules": "macro_rules! unused {\n    () => {};\n}\nmod n02_no_rewrite;\n",
            "spaced macro": "redirect ! (mod n02_no_rewrite;);\n",
            "extern crate": "extern crate core;\nmod n02_no_rewrite;\n",
            "stray token": "mod n02_no_rewrite;\n;\n",
            "dangling attribute": "mod n02_no_rewrite;\n#[allow(dead_code)]\n",
        }
        for case, main in mains.items():
            with self.subTest(case=case):
                self.outputs_clear()
                (self.repo/"tests/new-thread/main.rs").write_text(main)
                self.commit(self.repo)
                self.replan()
                self.data["regressions"] = [successor]
                self.save_plan()
                self.refused("0.0.3-R3")
                r = json.loads((self.evidence/"report.json").read_text())
                self.assertEqual(r["checks"][-1], {"id": "regression-proofs", "status": "fail",
                                                   "reason": r["checks"][-1]["reason"]})
        # A declared test that exists only in a comment is not a test.
        self.outputs_clear()
        (self.repo/"tests/new-thread/main.rs").write_text("pub mod n02_no_rewrite;\n")
        (self.repo/"tests/new-thread/n02_no_rewrite.rs").write_text(
            "/*\n#[test]\nfn every_call_runs_without_the_thread_context() {}\n*/\n")
        self.commit(self.repo)
        self.replan()
        self.data["regressions"] = [successor]
        self.save_plan()
        self.refused("missing named regression")
        # The plain, public declaration still passes.
        self.outputs_clear()
        (self.repo/"tests/new-thread/n02_no_rewrite.rs").write_text(
            "/* A synthetic proof. */\n#[test]\nfn every_call_runs_without_the_thread_context() {}\n")
        self.commit(self.repo)
        self.replan()
        self.data["regressions"] = [successor]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)

    def test_r17_successor_tests_are_real_top_level_test_items(self):
        """+1 round: a discarded test plus a macro-made passing twin never binds the proof."""
        self.regression_successors()
        successor = {"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                     "tests": ["every_call_runs_without_the_thread_context"]}
        proofs = {
            "discarded and generated": (
                "macro_rules! discard { ($($t:tt)*) => {}; }\n"
                "macro_rules! make { () => { #[test] fn every_call_runs_without_the_thread_context() {} }; }\n"
                'discard!(#[test] fn every_call_runs_without_the_thread_context() { panic!("proof"); });\n'
                "make!();\n", "item-level macro refused"),
            "inside an inline module": (
                "mod inner {\n    #[test]\n    fn every_call_runs_without_the_thread_context() {}\n}\n",
                "missing named regression"),
            "not a test": ("#[cfg(test)]\nfn every_call_runs_without_the_thread_context() {}\n",
                           "missing named regression"),
            # Re-check 3: two top-level fns of the name, cfg picks which one runs.
            "cfg-chosen twin": ('#[cfg(any())]\n#[test]\nfn every_call_runs_without_the_thread_context() { panic!("proof"); }\n'
                                "#[cfg(all())]\n#[test]\nfn every_call_runs_without_the_thread_context() {}\n",
                                "named regression declared twice"),
        }
        for case, (proof, reason) in proofs.items():
            with self.subTest(case=case):
                self.outputs_clear()
                (self.repo/"tests/new-thread/n02_no_rewrite.rs").write_text(proof)
                self.commit(self.repo)
                self.replan()
                self.data["regressions"] = [successor]
                self.save_plan()
                self.refused(reason)

    def test_r17_real_test_target_forms_still_pass(self):
        """Control: the top-level forms the real tests/*/main.rs files use (they are pruned
        from the CI job that runs this suite, so their shapes are reproduced here)."""
        self.regression_successors()
        (self.repo/"tests/new-thread/main.rs").write_text(
            "//! Synthetic test target.\n#![allow(clippy::needless_return)]\n\n"
            '#[path = "../support/forks.rs"]\nmod forks;\n#[allow(dead_code)]\nmod support;\n'
            "pub mod n02_no_rewrite;\nmod helpers {\n    pub fn ok() -> bool { matches!(1, 1) }\n}\n"
            "use std::path::{Path, PathBuf};\nconst SAMPLE: &str = \"mod n02_no_rewrite;\";\n"
            "static COUNT: [u8; 2] = [0; 2];\npub(crate) struct Probe<'a> { path: &'a Path }\n"
            "struct Unit;\nenum Kind { A, B }\ntype Paths = Vec<PathBuf>;\ntrait Seen { fn seen(&self) -> bool; }\n"
            "impl<'a> Seen for Probe<'a> { fn seen(&self) -> bool { let c = '}'; c == '{' || self.path.exists() } }\n"
            "unsafe impl Send for Unit {}\nconst fn twice(n: u8) -> u8 { n * 2 }\n"
            'extern "C" fn callback() {}\nasync fn later() { println!("{}", twice(1)); }\n')
        (self.repo/"tests/new-thread/n02_no_rewrite.rs").write_text(
            "use std::path::Path;\n\n#[test]\n#[allow(unused)]\nfn every_call_runs_without_the_thread_context() {\n"
            '    assert!(Path::new("x").to_str().is_some(), "{}", format!("ok"));\n}\n')
        self.commit(self.repo)
        self.replan()
        self.data["regressions"] = [{"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                                     "tests": ["every_call_runs_without_the_thread_context"]}]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)

    def test_r18_successor_target_is_the_file_cargo_selects(self):
        """Re-check 3 R3: the inspected main.rs must be the source Cargo builds for
        `-p openwiz-tests --test <target>`, read from the manifest, never assumed."""
        self.regression_successors()
        successor = {"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                     "tests": ["every_call_runs_without_the_thread_context"]}
        public = self.repo
        # The reviewer's probe: the approved file fails, a same-identity twin passes elsewhere.
        (public/"tests/new-thread/n02_no_rewrite.rs").write_text(
            '#[test]\nfn every_call_runs_without_the_thread_context() { panic!("proof"); }\n')
        (public/"tests/new-thread/actual.rs").write_text(
            "mod n02_no_rewrite {\n    #[test]\n    fn every_call_runs_without_the_thread_context() {}\n}\n")
        target = 'name = "new-thread"\npath = "new-thread/main.rs"\n'
        decoy = ('[package]\nname = "openwiz-tests"\nversion = "0.0.1"\nautotests = false\n\n'
                 '[[test]]\nname = "new-thread"\npath = "../../tests/new-thread/actual.rs"\n')
        cases = {
            "target path redirect": {"tests/Cargo.toml": TESTS_MANIFEST.replace("main.rs\"\n\n[dep", "actual.rs\"\n\n[dep")},
            "relative path escape": {"tests/Cargo.toml": TESTS_MANIFEST.replace(
                target, 'name = "new-thread"\npath = "../tests/new-thread/actual.rs"\n')},
            "no target entry": {"tests/Cargo.toml": TESTS_MANIFEST.replace("[[test]]\n"+target, "")},
            "auto-discovered targets": {"tests/Cargo.toml": TESTS_MANIFEST.replace("autotests = false\n", "")},
            "autotests on": {"tests/Cargo.toml": TESTS_MANIFEST.replace("autotests = false", "autotests = true")},
            "duplicate target": {"tests/Cargo.toml": TESTS_MANIFEST+"\n[[test]]\n"+target},
            "custom harness": {"tests/Cargo.toml": TESTS_MANIFEST.replace(target, target+"harness = false\n")},
            "second package of the name": {"crates/decoy/Cargo.toml": decoy},
            "package renamed": {"tests/Cargo.toml": TESTS_MANIFEST.replace('"openwiz-tests"', '"other-tests"')},
            "not a workspace member": {"Cargo.toml": self.root_manifest},
            "glob member": {"Cargo.toml": self.root_manifest+WORKSPACE.replace('"tests"', '"*"')},
            "unreadable manifest": {"tests/Cargo.toml": TESTS_MANIFEST+"[[test]\n"},
        }
        for case, files in cases.items():
            with self.subTest(case=case):
                self.outputs_clear()
                (public/"Cargo.toml").write_text(self.root_manifest+WORKSPACE)
                (public/"tests/Cargo.toml").write_text(TESTS_MANIFEST)
                shutil.rmtree(public/"crates/decoy", ignore_errors=True)
                for path, text in files.items():
                    (public/path).parent.mkdir(parents=True, exist_ok=True)
                    (public/path).write_text(text)
                self.commit(self.repo)
                self.replan()
                self.data["regressions"] = [successor]
                self.save_plan()
                self.refused("0.0.3-R3")
                r = json.loads((self.evidence/"report.json").read_text())
                self.assertEqual(r["checks"][-1]["id"], "regression-proofs")
        # Control: the real manifest shape, with the approved file passing, still passes.
        self.outputs_clear()
        (public/"Cargo.toml").write_text(self.root_manifest+WORKSPACE)
        (public/"tests/Cargo.toml").write_text(TESTS_MANIFEST)
        shutil.rmtree(public/"crates/decoy", ignore_errors=True)
        (public/"tests/new-thread/n02_no_rewrite.rs").write_text(
            "#[test]\nfn every_call_runs_without_the_thread_context() {}\n")
        self.commit(self.repo)
        self.replan()
        self.data["regressions"] = [successor]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)

    def test_r19_python_without_tomllib(self):
        """Re-check 4 R6: Python 3.9 and 3.10 have no tomllib. Ordinary checks still
        run there; only successor binding, which reads Cargo manifests, refuses."""
        shadow = self.root/"no-tomllib"
        shadow.mkdir()
        (shadow/"tomllib.py").write_text('raise ModuleNotFoundError("No module named \'tomllib\'")\n')
        r = self.check(PYTHONPATH=str(shadow))
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        self.outputs_clear()
        self.regression_successors()
        self.data["regressions"] = [{"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                                     "tests": ["every_call_runs_without_the_thread_context"]}]
        self.save_plan()
        self.refused("0.0.3-R3: regression successors need Python 3.11+", PYTHONPATH=str(shadow))

    def test_r20_the_approved_body_is_what_runs(self):
        """Re-check 5 R3, ruling (a) nonce: in a scratch clone the approved test's body
        becomes a random nonce panic, and the same --exact identity must fail printing it."""
        self.regression_successors()
        successor = {"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                     "tests": ["every_call_runs_without_the_thread_context"]}
        exact = "n02_no_rewrite::every_call_runs_without_the_thread_context"
        proof = self.repo/"tests/new-thread/n02_no_rewrite.rs"
        approved = ("use std::path::Path;\n\n#[test]\n#[allow(unused)]\n"
                    "fn every_call_runs_without_the_thread_context() {\n"
                    '    assert!(Path::new("x").to_str().is_some(), "{}", "}");\n}\n\n'
                    "#[test]\nfn another_test() { assert!(true) }\n")
        # The reviewer's probe: the attribute macro swaps the panicking approved test for a passing twin.
        cases = {
            "proof-replacing attribute": ({}, "#[replace_proof::supply]\n#[test]\n"
                                              'fn every_call_runs_without_the_thread_context() { panic!("proof"); }\n'),
            "fails without the nonce": ({"NONCE_SILENT": "1"}, approved),
            "no test result": ({"NONCE_NO_RESULT": "1"}, approved),
        }
        for case, (env, text) in cases.items():
            with self.subTest(case=case):
                self.outputs_clear()
                proof.write_text(text+f"// case: {case}\n")
                self.commit(self.repo)
                self.replan()
                self.data["regressions"] = [successor]
                self.save_plan()
                self.refused("0.0.3-R3: approved test body did not run", **env)
        # Control: a plain approved test binds; the scratch clone is gone and nothing tracked changed.
        self.outputs_clear()
        proof.write_text(approved)
        self.commit(self.repo)
        self.replan()
        self.data["regressions"] = [successor]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        log = (self.evidence/f"0.0.3-R3-{exact.replace(':', '_')}-nonce.log").read_text()
        nonce = re.search(r"panicked at n02_no_rewrite.rs:\n([0-9a-f]{32})\n", log)
        self.assertIsNotNone(nonce, log)
        self.assertNotIn(nonce[1], proof.read_text())
        self.assertFalse((self.stage/"nonce").exists())

    def test_r10_an_unused_successor_is_refused(self):
        self.data["regressions"] = [{"id": "0.0.3-R3", "proof": "tests/new-thread/n02_no_rewrite.rs",
                                     "tests": ["every_call_runs_without_the_thread_context"]}]
        self.save_plan()
        self.refused("unused regression successor")

    def test_r12_product_destinations_refuse_other_allowed_sources(self):
        """Review R1: a product file comes from its own path (AGENTS.md: the public template)."""
        self.product_source()
        readme = self.repo/"README.md"
        for path in ("GLOSSARY.md", "AGENTS.md", "skills/alpha/SKILL.md", ".claude-plugin/plugin.json",
                     "docs/fleets.md"):
            with self.subTest(path=path):
                self.outputs_clear()
                self.product_source()
                self.data["files"] = [f for f in self.data["files"] if f["path"] != path]
                self.data["claim_reviews"] = [r for r in self.data["claim_reviews"] if r["path"] != path]
                self.data["files"].append({"path": path, "source": "public/README.md",
                                           "sha256": digest(readme.read_bytes())})
                if path.endswith(".md"):
                    review = next(r for r in self.data["claim_reviews"] if r["path"] == "README.md")
                    self.data["claim_reviews"].append(dict(review, path=path))
                self.save_plan()
                self.refused("release rows must name their own tracked path")

    def test_r13_alias_destinations_must_be_links(self):
        """Review R2: .agents/skills/<name> is only ever a mode-120000 alias."""
        self.product_source()
        for mode in (None, "100644", "100755"):
            with self.subTest(mode=mode):
                self.outputs_clear()
                link = self.repo/ALIAS
                if link.is_symlink():
                    link.unlink()
                link.write_text("Synthetic regular file\n")
                if self.git(self.repo, "status", "--porcelain").stdout:
                    self.commit(self.repo)
                row = next(f for f in self.data["files"] if f["path"] == ALIAS)
                row.update(sha256=digest(link.read_bytes()))
                row.pop("mode", None)
                if mode:
                    row["mode"] = mode
                self.save_plan()
                self.refused("alias row needs mode 120000")

    def test_r13_historical_and_published_aliases_must_be_links(self):
        self.publish_history()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        row = next(f for f in report["files"] if f["path"] == ALIAS)
        row["mode"] = "100644"
        forged = self.root/"forged.json"
        forged.write_text(json.dumps(report))
        env, _ = self.backfill_tools()
        r = self.publish(env, report=forged)
        self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
        self.assertIn("invalid file hash or mode", r.stderr)
        self.assertFalse([c for c in self.publish_calls() if c["action"] in ("tag", "tag-push", "release")])

    def test_r13_a_regular_file_published_at_an_alias_path_is_refused(self):
        (self.public/".agents/skills").mkdir(parents=True)
        (self.public/ALIAS).write_text("Synthetic regular file\n")
        self.publish_history()
        self.historical_refused("alias row needs mode 120000")

    def test_r14_inline_code_with_backticks_is_not_a_fence(self):
        """Review R4: a backtick info string with a backtick is inline code, not a fence."""
        self.plant("docs/guide.md", "# Guide\n\n```x```\nFixture-tested: See [broken](missing.md).\n```\n")
        self.refused("link target missing")
        self.outputs_clear()
        self.plant("docs/guide.md", "# Guide\n\n~~~x`y\n[template](missing.md)\n~~~\n")
        r = self.check()  # a tilde fence may carry backticks in its info string
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)

    # ----- historical verification of an exact published commit -----

    def publish_history(self, changelog=CHANGELOG, extra=None):
        """Public main: base -> historical H -> later L, as the real 0.0.5 history."""
        for name, content in base.fixture_files().items():
            p = self.public/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        files = dict(PRODUCT, **{"CHANGELOG.md": changelog, "RELEASING.md": RELEASING,
                                 "docs/testing.md": TESTING,
                                 "README.md": "# Synthetic release\n\n"
                                 "Fixture-tested: This invented command prints usage. [Evidence](docs/evidence/check.md#fixture).\n\n"
                                 "**Live observation — LIVE-0.0.99:** a synthetic owner run held, with recorded gaps. [Testing](docs/testing.md#live-0099)\n"},
                     **(extra or {}))
        for path, text in files.items():
            p = self.public/path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.public/"skills/alpha/scripts/run.sh").chmod(0o755)
        (self.public/".agents/skills").mkdir(parents=True, exist_ok=True)
        if not (self.public/ALIAS).is_symlink() and not (self.public/ALIAS).exists():
            os.symlink(TARGET, self.public/ALIAS)
        self.commit(self.public)
        self.head = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        (self.public/"README.md").write_text("# Synthetic later docs\n\nContext: Later public wording.\n")
        self.commit(self.public)
        self.later = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.historical_plan()

    def published(self, ref=None):
        ref = ref or self.head
        rows = {}
        out = subprocess.run([self.real_git, "-C", self.public, "ls-tree", "-rz", ref],
                             capture_output=True, check=True).stdout
        for row in out.split(b"\0"):
            if row:
                meta, path = row.split(b"\t", 1)
                mode, _, oid = meta.split()
                data = subprocess.run([self.real_git, "-C", self.public, "cat-file", "blob", oid],
                                      capture_output=True, check=True).stdout
                rows[path.decode()] = (mode.decode(), data)
        return rows

    def historical_plan(self):
        rows = self.published()
        texts = {p: d.decode() for p, (m, d) in rows.items() if m != "120000"}
        claims = reviews(texts)
        readme = next(r for r in claims if r["path"] == "README.md")
        readme["claims"].append({"text": texts["README.md"].splitlines()[-1],
                                 "status": "live-observation", "label": "**Live observation — LIVE-0.0.99:**",
                                 "evidence": "docs/testing.md#live-0099"})
        self.data = {"schema": "openwiz.release-plan.v1", "version": VERSION, "public_base": self.base,
                     "identity": {"name": "Synthetic", "email": "123+fixture@users.noreply.github.com"},
                     "files": [{"path": p, "source": p, "sha256": digest(d), "mode": m}
                               for p, (m, d) in sorted(rows.items())],
                     "claim_reviews": claims, "live_pending": 0,
                     "evidence_documents": [{"path": "docs/testing.md", "sha256": digest(TESTING),
                                             "status": "live-observation",
                                             "label": "Live observation — LIVE-0.0.99:"}],
                     "historical": {"export_head": self.head,
                                    "changelog_heading": "## 0.0.99 · 2026-11-02",
                                    "entry_sha256": digest(ENTRY)}}
        self.save_plan()

    def historical(self, commit=None, approved="plan", literals="fixture", **env):
        approved = digest(self.plan.read_bytes()) if approved == "plan" else approved
        args = [sys.executable, self.cli, "check", VERSION, "--historical", commit or self.head,
                "--public-repo", self.public, "--plan", self.plan,
                "--staging", self.stage, "--evidence", self.evidence]
        if literals is not None:
            args += ["--literals", self.literals if literals == "fixture" else literals]
        if approved is not None:
            args += ["--approved-plan-sha256", approved]
        return base.run(args, env=dict(self.env, **env))

    def historical_refused(self, reason, **kwargs):
        refs = self.git(self.public, "show-ref").stdout
        r = self.historical(**kwargs)
        self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
        if reason == "identifier" and "open-development-privacy:" in r.stderr:
            self.assertRegex((self.evidence/"open-development-privacy.log").read_text(),r"T[13] ")
        elif reason == "not reachable from public main" and "open-development-privacy:" in r.stderr:
            self.assertIn("READ ",(self.evidence/"open-development-privacy.log").read_text())
        else:
            self.assertIn(reason, r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report.get("publishable", False))
        self.assertEqual(self.git(self.public, "show-ref").stdout, refs)

    def test_historical_named_terms_input_refusals_and_healthy_control(self):
        self.publish_history()
        for value in (None, b"", b" \n", b"synthetic-private-name\n\n", b"\xff", b"synthetic-private-name\0\n"):
            with self.subTest(value=value):
                if value is not None:
                    self.literals.write_bytes(value)
                result = self.historical(literals=None if value is None else self.literals)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("named-terms input", result.stderr)
                self.assertFalse(self.stage.exists())
                self.assertFalse(self.evidence.exists())
                self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
        loop = self.root/"input-loop"
        loop.symlink_to(loop.name)
        for path in (self.root/"synthetic-private-name-absent.txt", self.root, loop):
            result = self.historical(literals=path)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("named-terms input", result.stderr)
            self.assertNotIn(str(path), result.stdout+result.stderr)
            self.assertFalse(self.stage.exists())
            self.assertFalse(self.evidence.exists())
        self.literals.write_text("synthetic-private-name\nsynthetic.private+name\n")
        result = self.historical()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("open-development-privacy.log", "staged-privacy.log"):
            self.assertEqual((self.evidence/name).read_text(), "literals: used\n")

    def test_r3_historical_check_binds_the_exact_published_head(self):
        self.publish_history()
        refs = self.git(self.public, "show-ref").stdout
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["schema"], "openwiz.release-check.v1")
        self.assertEqual((report["status"], report["publishable"], report["live_pending"]), ("pass", True, 0))
        self.assertEqual([c["id"] for c in report["checks"]], test_publish.CHECKS)
        self.assertTrue(all(c["status"] == "pass" for c in report["checks"]))
        self.assertEqual(report["export_head"], self.head)
        self.assertEqual(report["source_head"], self.head)
        self.assertEqual(report["public_base"], self.base)
        self.assertEqual(report["export_tree"], self.git(self.public, "rev-parse", self.head+"^{tree}").stdout.strip())
        self.assertEqual(report["plan_sha256"], digest(self.plan.read_bytes()))
        self.assertEqual(report["historical"], {"public_main": self.later})
        expected = [{"path": p, "sha256": digest(d), "mode": m} for p, (m, d) in sorted(self.published().items())]
        self.assertEqual(report["files"], expected)
        self.assertEqual(self.git(self.stage/"fresh", "rev-parse", "HEAD").stdout.strip(), self.head)
        self.assertEqual(self.git(self.public, "show-ref").stdout, refs)
        calls = [json.loads(s) for s in (self.root/"calls.jsonl").read_text().splitlines()]
        self.assertFalse(any(c["tool"] == "gh" for c in calls))
        self.assertTrue(any(c["tool"] == "cargo" and c["args"][:1] == ["test"] for c in calls))

    def test_r3_historical_keeps_the_published_releasing_not_the_current_template(self):
        self.publish_history()
        row = next(f for f in self.data["files"] if f["path"] == "RELEASING.md")
        template = (base.ROOT/"tools/release/public/RELEASING.md").read_bytes()
        self.assertNotEqual(digest(template), row["sha256"])
        row["sha256"] = digest(template)
        self.save_plan()
        self.historical_refused("hash differs")

    def test_r3_historical_refuses_unapproved_unreachable_or_mismatched_inputs(self):
        self.publish_history()
        self.historical_refused("approved plan", approved=None)
        self.outputs_clear()
        self.historical_refused("approved plan", approved="0"*64)
        self.outputs_clear()
        self.historical_refused("historical commit differs from the approved plan", commit=self.later)
        # Same tree, different commit, not on main.
        sibling = self.git(self.public, "commit-tree", self.head+"^{tree}", "-p", self.base,
                           "-m", "Synthetic unpublished sibling").stdout.strip()
        self.git(self.public, "update-ref", "refs/heads/unreleased", sibling)
        self.data["historical"]["export_head"] = sibling
        self.save_plan()
        self.outputs_clear()
        self.historical_refused("not reachable from public main", commit=sibling)
        self.data["historical"]["export_head"] = "e"*40
        self.save_plan()
        self.outputs_clear()
        self.historical_refused("not reachable from public main", commit="e"*40)

    def test_r3_historical_refuses_plan_rows_that_differ_from_the_published_tree(self):
        self.publish_history()
        original = json.loads(json.dumps(self.data))
        variants = []
        stale = json.loads(json.dumps(original))
        stale["files"][0]["sha256"] = "0"*64
        variants.append((stale, "hash differs"))
        missing = json.loads(json.dumps(original))
        missing["files"] = [f for f in missing["files"] if f["path"] != "GLOSSARY.md"]
        missing["claim_reviews"] = [r for r in missing["claim_reviews"] if r["path"] != "GLOSSARY.md"]
        variants.append((missing, "allowlist does not equal"))
        extra = json.loads(json.dumps(original))
        extra["files"].append({"path": "EXTRA.md", "source": "EXTRA.md", "sha256": "0"*64, "mode": "100644"})
        variants.append((extra, "allowlist does not equal"))
        mode = json.loads(json.dumps(original))
        next(f for f in mode["files"] if f["path"] == "skills/alpha/scripts/run.sh")["mode"] = "100644"
        variants.append((mode, "mode differs"))
        alias_mode = json.loads(json.dumps(original))
        next(f for f in alias_mode["files"] if f["path"] == ALIAS)["mode"] = "100644"
        variants.append((alias_mode, "alias row needs mode 120000"))
        unbound = json.loads(json.dumps(original))
        for f in unbound["files"]:
            f.pop("mode")
        variants.append((unbound, "historical rows need their approved mode"))
        source = json.loads(json.dumps(original))
        source["files"][0]["source"] = "public/"+source["files"][0]["path"]
        variants.append((source, "historical rows name their published path"))
        claim = json.loads(json.dumps(original))
        claim["claim_reviews"] = [r for r in claim["claim_reviews"] if r["path"] != "skills/README.md"]
        variants.append((claim, "claim review missing"))
        both = json.loads(json.dumps(original))
        both["entry"] = {"spec": 1, "date": "2026-11-02", "tested": "Fixture-tested: Synthetic."}
        variants.append((both, "unexpected manifest shape"))
        base_moved = json.loads(json.dumps(original))
        base_moved["public_base"] = self.later
        variants.append((base_moved, "public base must be an ancestor"))
        for data, reason in variants:
            with self.subTest(reason=reason):
                self.outputs_clear()
                self.data = data
                self.save_plan()
                self.historical_refused(reason)

    def test_r3_existing_tag_collision_is_refused(self):
        self.publish_history()
        self.git(self.public, "tag", "-a", "v"+VERSION, self.base, "-m", "Synthetic existing tag")
        self.historical_refused("tag already exists")

    def test_r4_approved_existing_entry_binds_heading_date_and_bytes(self):
        cases = [({"changelog_heading": "## 0.0.99 · 2026-11-03"}, "approved changelog entry"),
                 ({"entry_sha256": "0"*64}, "approved changelog entry"),
                 ({"changelog_heading": "## 0.0.98 · 2026-11-01"}, "approved changelog entry")]
        for change, reason in cases:
            with self.subTest(change=change):
                self.outputs_clear()
                self.git(self.public, "reset", "-q", "--hard", self.base)
                self.publish_history()
                self.data["historical"].update(change)
                self.save_plan()
                self.historical_refused(reason)
        for text, reason in (
                ("# Changelog\n\n## 0.0.97–0.0.99 · 2026-11-02\n\nContext: Combined.\n", "combined"),
                ("# Changelog\n\n"+ENTRY+"\n"+ENTRY, "approved changelog entry"),
                ("# Changelog\n\n## 0.0.99 · PUBLICATION-DATE\n\nContext: Placeholder.\n", "approved changelog entry")):
            with self.subTest(text=text):
                self.outputs_clear()
                self.git(self.public, "reset", "-q", "--hard", self.base)
                self.publish_history(changelog=text)
                self.historical_refused(reason)

    def test_r4_pending_live_markers_never_make_a_publishable_report(self):
        self.publish_history(extra={"docs/pending.md": "# Pending\n\nContext: LIVE-PENDING\n"})
        self.historical_refused("declared placeholder count")
        self.outputs_clear()
        self.data["live_pending"] = 1
        self.save_plan()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual((report["live_pending"], report["publishable"]), (1, False))

    def test_r3_a_reviewed_malformed_json_fixture_is_still_scanned(self):
        truncated = '{"items": [{"id": "thr_syn_one"},'
        self.publish_history(extra={"tests/fixtures/truncated.json": truncated})
        self.historical_refused("invalid JSON")
        review = {"path": "tests/fixtures/truncated.json", "sha256": digest(truncated),
                  "rule": "invalid-json", "value": "tests/fixtures/truncated.json"}
        for change, reason in (({"sha256": "0"*64}, "stale scan exception"),
                               ({"value": "tests/fixtures/other.json"}, "invalid JSON"),
                               ({"rule": "secret"}, "invalid JSON")):
            with self.subTest(change=change):
                self.outputs_clear()
                self.data["scan_exceptions"] = [dict(review, **change)]
                self.save_plan()
                self.historical_refused(reason)
        self.outputs_clear()
        self.data["scan_exceptions"] = [review]
        self.save_plan()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        # The raw text is still scanned: an unreviewed private id still refuses.
        self.outputs_clear()
        self.git(self.public, "reset", "-q", "--hard", self.base)
        leaked = truncated.replace("thr_syn_one", "thr" + "_abc123")
        self.publish_history(extra={"tests/fixtures/truncated.json": leaked})
        self.data["scan_exceptions"] = [dict(review, sha256=digest(leaked))]
        self.save_plan()
        self.historical_refused("identifier")
        self.assertEqual((self.evidence/"open-development-privacy.log").read_text(),
            'T1 tree:"tests/fixtures/truncated.json":1\n'
            'T1 commit-tree-1:"tests/fixtures/truncated.json":1\nliterals: used\n')

    # ----- public live-evidence summaries and reviewed label forms -----

    def test_r5_reviewed_label_and_live_summary_document_pass_only_when_declared(self):
        self.publish_history()
        original = json.loads(json.dumps(self.data))
        readme = lambda d: next(r for r in d["claim_reviews"] if r["path"] == "README.md")["claims"][-1]
        variants = []
        undeclared = json.loads(json.dumps(original))
        undeclared["evidence_documents"] = []
        variants.append((undeclared, "live capability needs published live evidence"))
        stale = json.loads(json.dumps(original))
        stale["evidence_documents"][0]["sha256"] = "0"*64
        variants.append((stale, "evidence document"))
        absent = json.loads(json.dumps(original))
        absent["evidence_documents"][0]["label"] = "Live observation — LIVE-0.0.98:"
        variants.append((absent, "evidence document"))
        unused = json.loads(json.dumps(original))
        unused["evidence_documents"].append({"path": "RELEASING.md", "sha256": digest(RELEASING),
                                             "status": "live-observation", "label": "Context:"})
        variants.append((unused, "unused evidence document"))
        wrong = json.loads(json.dumps(original))
        readme(wrong)["status"] = "fixture-tested"
        variants.append((wrong, "label"))
        nolabel = json.loads(json.dumps(original))
        del readme(nolabel)["label"]
        variants.append((nolabel, "claim needs its public status label"))
        elsewhere = json.loads(json.dumps(original))
        readme(elsewhere)["label"] = "[Testing]"
        variants.append((elsewhere, "label"))
        context = json.loads(json.dumps(original))
        readme(context)["status"] = "context"
        readme(context)["evidence"] = ""
        variants.append((context, "context"))
        for data, reason in variants:
            with self.subTest(reason=reason):
                self.outputs_clear()
                self.data = data
                self.save_plan()
                self.historical_refused(reason)
        self.outputs_clear()
        self.data = original
        self.save_plan()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)

    # ----- backfill publication from the historical report -----

    def backfill_tools(self, **env):
        for name in ("git", "gh"):
            p = self.bin/name
            p.write_text(test_publish.RECORDER)
            p.chmod(0o755)
        for name in ("cargo", "npm", "node"):
            (self.bin/name).unlink(missing_ok=True)
        remote = self.root/"remote.git"
        subprocess.run([self.real_git, "clone", "-q", "--bare", self.public, remote], check=True)
        self.calls_path = self.root/"publish-calls.jsonl"
        return dict(self.env, CALLS=str(self.calls_path), PUBLIC_FAKE=str(remote), **env), remote

    def publish(self, env, backfill=True, approval="publish "+VERSION, report=None):
        args = [sys.executable, self.cli, "publish", VERSION, "--repo", self.stage/"export",
                "--report", report or self.evidence/"report.json", "--approval", approval]
        return base.run(args+(["--backfill"] if backfill else []), env=env)

    def publish_calls(self):
        p = self.calls_path
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []

    def test_r6_backfill_tags_the_checked_historical_head_with_zero_main_pushes(self):
        self.publish_history()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        env, remote = self.backfill_tools()
        before = {p: digest(p.read_bytes()) for p in (self.stage/"export").rglob("*")
                  if p.is_file() and ".git" not in p.parts}
        r = self.publish(env)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        actions = [c["action"] for c in self.publish_calls() if c["action"] not in ("read", "gh-read")]
        self.assertEqual(actions, ["readback", "tag", "tag-push", "release"])
        self.assertNotIn("main-push", [c["action"] for c in self.publish_calls()])
        gh = [c["args"] for c in self.publish_calls() if c["tool"] == "gh"]
        self.assertEqual(gh[0][:2], ["api", "repos/example-owner/example-release/immutable-releases"])
        self.assertEqual(gh[-1][:2], ["api", "repos/example-owner/example-release/releases/tags/v"+VERSION])
        self.assertEqual(self.git(remote, "rev-parse", "main").stdout.strip(), self.later)
        self.assertEqual(self.git(remote, "cat-file", "-t", "refs/tags/v"+VERSION).stdout.strip(), "tag")
        self.assertEqual(self.git(remote, "rev-parse", "refs/tags/v"+VERSION+"^{}").stdout.strip(), self.head)
        release = next(c for c in self.publish_calls() if c["action"] == "release")
        self.assertEqual(release["notes"], ENTRY)
        self.assertIn("--prerelease", release["args"])
        after = {p: digest(p.read_bytes()) for p in (self.stage/"export").rglob("*")
                 if p.is_file() and ".git" not in p.parts}
        self.assertEqual(after, before)

    def test_r6_backfill_refuses_non_historical_forged_or_review_only_reports(self):
        self.publish_history()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        env, remote = self.backfill_tools()
        good = json.loads((self.evidence/"report.json").read_text())
        forged = self.root/"forged.json"
        cases = []
        staged = dict(good)
        del staged["historical"]
        cases.append((staged, True, "historical report"))
        cases.append((good, False, "historical report"))
        cases.append((dict(good, schema="openwiz.release-review-check.v1"), True, "schema"))
        cases.append((dict(good, source_head=self.base), True, "historical report"))
        cases.append((dict(good, checks=good["checks"][:-1]), True, "incomplete check set"))
        cases.append((dict(good, publishable=False), True, "not publishable"))
        for data, backfill, reason in cases:
            with self.subTest(reason=reason, backfill=backfill):
                self.calls_path.unlink(missing_ok=True)
                forged.write_text(json.dumps(data))
                r = self.publish(env, backfill=backfill, report=forged)
                self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
                self.assertIn(reason, r.stderr)
                self.assertFalse([c for c in self.publish_calls()
                                  if c["action"] in ("main-push", "tag", "tag-push", "release")])
        self.assertEqual(self.git(remote, "tag", "--list").stdout, "")

    def test_r6_backfill_stops_without_immutable_releases_or_on_bad_release_readback(self):
        self.publish_history()
        r = self.historical()
        self.assertEqual(r.returncode, 0, r.stderr)
        for plant, writes, reason in (("off", [], "immutable releases"),
                                      ("mutable", ["tag", "tag-push", "release"], "release read-back"),
                                      ("notes", ["tag", "tag-push", "release"], "release read-back"),
                                      ("final", ["tag", "tag-push", "release"], "release read-back")):
            with self.subTest(plant=plant):
                shutil.rmtree(self.root/"remote.git", ignore_errors=True)
                (self.root/"publish-calls.jsonl").unlink(missing_ok=True)
                env, remote = self.backfill_tools(GH_PLANT=plant)
                r = self.publish(env)
                self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
                self.assertIn(reason, r.stderr)
                actions = [c["action"] for c in self.publish_calls()
                           if c["action"] in ("main-push", "tag", "tag-push", "release")]
                self.assertEqual(actions, writes)
                # No retry and no rollback: one release attempt at most.
                self.assertLessEqual(actions.count("release"), 1)


class FutureRelease(test_entry.EntryCheck):
    """AC3: a normal new release, product rows included, checked then published unedited."""

    def test_r7_new_release_stages_from_tracked_inputs_and_publishes_unedited(self):
        for path, text in PRODUCT.items():
            p = self.repo/path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.repo/".agents/skills").mkdir(parents=True)
        os.symlink(TARGET, self.repo/ALIAS)
        self.commit(self.repo)
        self.replan()
        self.approve()
        self.data["files"].append({"path": ALIAS, "source": ALIAS, "sha256": digest(TARGET), "mode": "120000"})
        self.data["claim_reviews"] = [r for r in self.data["claim_reviews"] if r["path"] not in PRODUCT]
        self.data["claim_reviews"] += reviews(PRODUCT)
        self.save_plan()
        before = {p: self.git(p, "status", "--porcelain").stdout for p in (self.repo, self.public)}
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual({p: self.git(p, "status", "--porcelain").stdout for p in (self.repo, self.public)}, before)
        report = self.evidence/"report.json"
        frozen = report.read_bytes()
        export = self.stage/"export"
        head = self.git(export, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.git(export, "rev-parse", "HEAD^").stdout.strip(), self.git(self.repo,"rev-parse","HEAD").stdout.strip())
        # Publish the exact checked export with the publisher's recording fakes.
        remote = self.root/"remote.git"
        subprocess.run([shutil.which("git"), "clone", "-q", "--bare", self.public, remote], check=True,
                       env=self.env)
        for name in ("git", "gh"):
            (self.bin/name).write_text(test_publish.RECORDER)
        calls = self.root/"publish-calls.jsonl"
        env = dict(self.env, CALLS=str(calls), PUBLIC_FAKE=str(remote))
        r = base.run([sys.executable, self.cli, "publish", VERSION, "--repo", export, "--report", report,
                      "--approval", "publish "+VERSION], env=env)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        rows = [json.loads(s) for s in calls.read_text().splitlines()]
        self.assertEqual([c["action"] for c in rows if c["action"] not in ("read", "gh-read")],
                         ["main-push", "readback", "tag", "tag-push", "release"])
        self.assertEqual(next(c for c in rows if c["action"] == "release")["notes"], test_entry.ENTRY)
        self.assertEqual(self.git(remote, "rev-parse", "main").stdout.strip(), head)
        self.assertEqual(self.git(remote, "ls-tree", "main", ALIAS).stdout.split()[0], "120000")
        self.assertEqual(report.read_bytes(), frozen)
        self.assertEqual(self.git(export, "status", "--porcelain").stdout, "")


class PreservedRange(test_entry.EntryCheck):
    """Review R5: an older range heading kept from the public base is refused too."""

    def test_r15_a_preserved_public_range_heading_is_refused(self):
        older = "## 0.0.97 - 0.0.98 · 2026-01-01\n\nContext: Earlier combined public entry.\n"
        (self.public/"CHANGELOG.md").write_text("# Changelog\n\n"+older)
        self.commit(self.public)
        self.base = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.data["public_base"] = self.base
        self.approve(changelog="# Changelog\n\n"+test_entry.ENTRY+"\n"+older)
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
        self.assertIn("combined version-range changelog heading refused", r.stderr)


class CombinedRelease(test_entry.EntryCheck):
    """Q4 (a): a combined release gets one generated entry per version, newest first."""

    def combined(self):
        world = self.world
        world["repos/{owner}/{repo}/issues/4200"] = {
            "number": 4200, "body": "## Changelog headline\n\nFixture-tested: You can compare exports.\n",
            "milestone": {"number": 100, "title": "0.0.100"}, "sub_issues_summary": {"total": 1}}
        world["repos/{owner}/{repo}/issues/4103"]["milestone"] = {"number": 100, "title": "0.0.100"}
        world["repos/{owner}/{repo}/git/matching-refs/heads/release-"] = [
            {"ref": "refs/heads/release-0.0.99"}, {"ref": "refs/heads/release-0.0.100"}]
        self.save_world()
        self.git(self.repo, "checkout", "-qb", "release-0.0.100")
        newer = ("## 0.0.100 · 2026-01-03\n\nFixture-tested: You can compare exports.\n\n"
                 "- Fixture-tested: You can compare exports.\n\n"
                 "Fixture-tested: Synthetic compare fixtures pass; live compare remains unverified.\n\n"
                 "[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.100)\n")
        changelog = "# Changelog\n\n"+newer+"\n"+test_entry.ENTRY+"\n"+test_entry.OLD.removeprefix("# Changelog\n\n")
        # Both milestones now have release branches, so both are built.
        roadmap = ("# OpenWiz roadmap\n\nWhat is being built now, and what comes next.\n\n## Now\n\n"
                   "- **0.0.99**, built: You can preview an export.\n"
                   "- **0.0.100**, built: You can compare exports.\n\n## Next\n\n- None right now.\n")
        self.approve(changelog=changelog, roadmap=roadmap)
        self.data["version"] = "0.0.100"
        self.data["entry"] = [
            {"version": "0.0.100", "spec": 4200, "date": "2026-01-03", "tested":
             "Fixture-tested: Synthetic compare fixtures pass; live compare remains unverified."},
            {"version": "0.0.99", "spec": 4100, "date": "2026-01-02", "tested":
             "Fixture-tested: Synthetic export fixtures pass; live export remains unverified."}]
        review = next(r for r in self.data["claim_reviews"] if r["path"] == "CHANGELOG.md")
        review["claims"].append({"text": newer[newer.index("Fixture-tested:"):newer.index("\n\n[Full release")],
                                 "status": "fixture-tested", "evidence": "docs/evidence/check.md#fixture"})
        review["claims"] = [c for c in review["claims"] if c["status"] != "context" or c["text"] in changelog]
        for line in newer.splitlines():
            if line.startswith("[Full release") and not any(line in c["text"] for c in review["claims"]):
                review["claims"].append({"text": line, "status": "context", "evidence": ""})
        self.save_plan()
        return changelog

    def test_r11_combined_release_generates_one_entry_per_version(self):
        changelog = self.combined()
        r = self.check(version="0.0.100")
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        export = self.stage/"export"
        self.assertEqual((export/"CHANGELOG.md").read_text(), changelog)
        headings = [l for l in changelog.splitlines() if l.startswith("## ")]
        self.assertEqual(headings, ["## 0.0.100 · 2026-01-03", "## 0.0.99 · 2026-01-02", "## 0.0.98 · 2026-01-01"])

    def test_r11_combined_entries_refuse_bad_order_versions_and_duplicates(self):
        self.combined()
        good = json.loads(json.dumps(self.data["entry"]))
        for entries, reason in ((list(reversed(good)), "newest first"),
                                ([good[0], dict(good[1], version="0.0.100")], "newest first"),
                                ([good[1]], "first entry must be the checked version"),
                                ([good[0], dict(good[1], version="0.0.98")], "already published"),
                                ([good[0], dict(good[1], version="0.0.97")], "newer than published"),
                                ([good[0], dict(good[1], spec=4200)], "milestone/version mismatch"),
                                ([], "entry"),
                                ([dict(good[0], extra=1)], "unexpected manifest shape")):
            with self.subTest(reason=reason, entries=entries):
                self.outputs_clear()
                self.data["entry"] = entries
                self.save_plan()
                r = self.check(version="0.0.100")
                self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
                self.assertIn(reason, r.stderr)


def load_tests(loader, tests, pattern):
    """Only this file's proofs; the inherited release-check proofs run in test.py."""
    return unittest.TestSuite([*(Backfill(name) for name in Backfill.__dict__ if name.startswith("test_")),
                               *(FutureRelease(name) for name in FutureRelease.__dict__
                                 if name.startswith("test_")),
                               *(CombinedRelease(name) for name in CombinedRelease.__dict__
                                 if name.startswith("test_")),
                               *(PreservedRange(name) for name in PreservedRange.__dict__
                                 if name.startswith("test_"))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
