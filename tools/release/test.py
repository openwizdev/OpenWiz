#!/usr/bin/env python3
"""Outside-in release check proofs, with synthetic repositories and recording tools."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from html import escape
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools/release/release"
FIXTURE = ROOT / "tests/fixtures/release/clean/README.md"


def fixture_files():
    return {name: content.replace("SYNTHETIC_ENV_PREFIX", "env_")
            for name, content in re.findall(
                r"^## ([^\n]+)\n\n```text\n(.*?)^```", FIXTURE.read_text(), re.M|re.S)}


def copy_fixture(dest):
    for name,content in fixture_files().items():
        path = dest/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)

VERSION = "0.0.99"


def run(args, cwd=None, env=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True)


class ReleaseCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="release-proof-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        self.public = self.root / "public"
        self.stage = self.root / "staging"
        self.evidence = self.root / "evidence"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Explicit private operator input; never part of the fixture release tree.
        self.literals = self.root/"named-terms.txt"
        self.literals.write_text("synthetic-private-name\nsynthetic.private+name\n")
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Synthetic", GIT_COMMITTER_NAME="Synthetic",
                        GIT_AUTHOR_EMAIL="123+fixture@users.noreply.github.com",
                        GIT_COMMITTER_EMAIL="123+fixture@users.noreply.github.com")
        for p in (self.public,):
            p.mkdir()
            self.git(p, "init", "-q", "-b", "main")
        (self.public / "README.md").write_text("# Public base\n")
        self.commit(self.public)
        self.base = self.git(self.public, "rev-parse", "HEAD").stdout.strip()
        self.git(self.root, "clone", "-q", self.public, self.repo)
        self.git(self.repo, "remote", "set-url", "origin", "https://github.com/example-owner/example-release.git")
        self.git(self.repo, "checkout", "-qb", f"release-{VERSION}")
        copy_fixture(self.repo)
        self.commit(self.repo)
        self.plan = self.root / "plan.json"
        # An isolated copy substitutes synthetic Git policy anchors, exactly as
        # O3's own history fixtures do. Production has no anchor override.
        self.cli = self.root/"fixture-tools/release/release"
        shutil.copytree(CLI.parent,self.cli.parent,ignore=shutil.ignore_patterns("__pycache__","evidence"))
        shutil.copytree(ROOT/"tools/privacy-check",self.cli.parent.parent/"privacy-check",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT/"tools/roadmap",self.cli.parent.parent/"roadmap",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.replan()
        # Record every external invocation, delegate git only to the real binary.
        # Each call appends one JSON line to RELEASE_CALLS. git and gh are
        # shell scripts and the others start Python without site or pathlib:
        # a check runs git about 28 times, and a Python start for each one
        # was most of this suite's time.
        record = """#!/bin/sh
json() {
  case $1 in
    *[\\"\\\\]*|*[[:cntrl:]]*) ;;
    *) printf '"%s"' "$1"; return ;;
  esac
  s=$1 out=
  while [ -n "$s" ]; do
    rest=${s#?} c=${s%"$rest"} s=$rest
    case $c in
      [\\"\\\\]) out=$out\\\\$c ;;
      [[:cntrl:]]) out=$out$(printf '\\\\u%04x' "'$c") ;;
      *) out=$out$c ;;
    esac
  done
  printf '"%s"' "$out"
}
cwd=$(pwd -P)
{ printf '{"tool":'; json "${0##*/}"; printf ',"args":['; sep=
  for a in "$@"; do printf %s "$sep"; json "$a"; sep=,; done
  printf '],"cwd":'; json "$cwd"; printf '}\\n'; } >> "$RELEASE_CALLS"
"""
        git = record+"""for a in "$@"; do
  case $a in push|tag|fetch) exit 97 ;; esac
done
last= previous=
for a in "$@"; do previous=$last last=$a; done
if [ "$previous $last" != "add --all" ] || [ "${cwd##*/}" != export ] \\
    || [ -z "$EXTRA_EXPORT_FILE$FLIP_EXPORT_MODE" ]; then
  exec REAL_GIT "$@"
fi
REAL_GIT "$@" || exit
if [ -n "$EXTRA_EXPORT_FILE" ]; then
  printf 'Synthetic unlisted file\\n' > unexpected.txt
  REAL_GIT add unexpected.txt || exit
fi
if [ -n "$FLIP_EXPORT_MODE" ]; then
  REAL_GIT update-index --chmod=+x README.md || exit
fi
""".replace("REAL_GIT", "'"+shutil.which("git")+"'")
        recorder = '''#!RUNNING_PYTHON -IS
import json, os, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["RELEASE_CALLS"], "a") as f:
    f.write(json.dumps({"tool":name,"args":args,"cwd":os.getcwd()})+"\\n")
if os.environ.get("FAIL_TOOL") == name:
    print("synthetic tool failure",file=sys.stderr)
    sys.exit(42)
if name == "npm" and os.path.basename(os.getcwd()) == "site":
    phase = "test" if args == ["test"] else "build"
    if os.environ.get("FAIL_SITE") == phase:
        print("synthetic site failure",file=sys.stderr)
        sys.exit(44)
    if phase == "test":
        n = 0 if os.environ.get("ZERO_SITE_TESTS") else 1
        for suite in range(1 if os.environ.get("PARTIAL_SITE_TESTS") else 2):
            print(f"# tests {n}\\n# pass {n}\\n# fail 0")
if name == "cargo":
    if args[:1] == ["build"]:
        if os.environ.get("DIRTY_BUILD"):
            with open("Cargo.toml","a") as f:
                f.write("\\n# Synthetic build changed a tracked file\\n")
        target = os.path.join(os.environ["CARGO_TARGET_DIR"],"release")
        os.makedirs(target, exist_ok=True)
        binary = os.path.join(target,"openwiz")
        with open(binary,"w") as f:
            if os.environ.get("HELP_TRAILING"):
                f.write("#!/bin/sh\\nprintf 'Usage: openwiz --help \\\\n'\\n")
            else:
                f.write("#!/bin/sh\\nprintf 'Usage: openwiz --help\\\\n'\\n")
        os.chmod(binary, 0o755)
    if args[:1] == ["test"]:
        plant = "regression-failure.txt"
        if os.path.exists(plant) and open(plant).read() in args:
            print("synthetic regression failure",file=sys.stderr)
            sys.exit(43)
        if "--exact" in args:
            # Like a compiler, the fake runs the approved body: a nonce panic in
            # the target's sources fails, printing the nonce, unless a
            # proof-replacing attribute macro discards that body (review R3).
            import re
            folder = os.path.join("tests", args[args.index("--test")+1])
            for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
                text = open(os.path.join(folder, f)).read()
                nonce = re.search(r'panic!\\("([0-9a-f]{32})"\\)', text)
                if nonce and "#[replace_proof::supply]" not in text:
                    if os.environ.get("NONCE_NO_RESULT"):
                        print("error[E0425]: synthetic compile error", file=sys.stderr)
                        sys.exit(101)
                    shown = "another panic" if os.environ.get("NONCE_SILENT") else nonce[1]
                    print(f"---- {args[-1]} stdout ----\\npanicked at {f}:\\n{shown}\\n\\n"
                          "test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out")
                    sys.exit(101)
        if os.environ.get("REGRESSION_ZERO") and args[-1] not in ("--locked",):
            print("test result: ok. 0 passed; 0 failed")
            sys.exit(0)
        n = 0 if os.environ.get("ZERO_TESTS") else 1
        print(f"test result: ok. {n} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out")
if name == "node":
    plant = "../../regression-failure.txt"
    if os.path.exists(plant) and open(plant).read() == "browser":
        sys.exit(43)
    tests = os.environ.get("BROWSER_TESTS","4")
    passed = os.environ.get("BROWSER_PASSED","4")
    print(f"# tests {tests}\\n# pass {passed}\\n# fail 0")
'''.replace("RUNNING_PYTHON", sys.executable)
        for name,script in (("git",git),("gh",record+"exit 98\n"),
                            ("cargo",recorder),("npm",recorder),("node",recorder)):
            p = self.bin / name
            p.write_text(script)
            p.chmod(0o755)
        self.env.update(PATH=str(self.bin)+os.pathsep+self.env["PATH"],
                        RELEASE_CALLS=str(self.root/"calls.jsonl"))

    def git(self, repo, *args):
        r = run([shutil.which("git"), "-C", repo, *args], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def commit(self, repo):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "Synthetic fixture")

    def replan(self):
        files = []
        reviews = []
        for p in sorted((self.repo).rglob("*")):
            if ".git" in p.relative_to(self.repo).parts or not p.is_file():
                continue
            path = p.relative_to(self.repo).as_posix()
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            files.append({"path":path,"source":path,"sha256":digest})
            if p.suffix == ".md":
                reviews.append({"path":path,"sha256":digest,"claims":[
                    {"text":line,"status":("context" if line.startswith("kind:") else line.split(":",1)[0].lower()),
                     "evidence":"docs/evidence/check.md#fixture"}
                    for line in p.read_text().splitlines()
                    if line.startswith(("Fixture-tested:", "Unverified:", "Live-observation:", "Source-inspection:", "Context:", "kind:"))]})
        self.data = {"schema":"openwiz.release-plan.v1","version":VERSION,"public_base":self.base,
                     "identity":{"name":"Synthetic","email":"123+fixture@users.noreply.github.com"},
                     "files":files,"claim_reviews":reviews,"live_pending":0}
        self.save_plan()

    def reset_fixture(self):
        for path in self.repo.iterdir():
            if path.name == ".git":
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        copy_fixture(self.repo)

    def save_plan(self):
        # Reconcile fixture main before taking any no-write snapshots.
        if self.repo != self.public and self.data["public_base"] == self.git(self.public,"rev-parse","main").stdout.strip():
            if self.git(self.repo,"rev-parse","main").stdout.strip() != self.data["public_base"]:
                self.git(self.repo,"fetch",str(self.public),"main:main")
                self.git(self.repo,"merge","-q","-s","ours","--no-edit","main")
        self.plan.write_text(json.dumps(self.data))
        history = self.data.get("historical")
        repo = self.public if history else self.repo
        head = self.head if history else "HEAD"
        root = self.git(repo,"rev-list","--max-parents=0",head).stdout.strip()
        anchor = getattr(self,"history_anchor",None) or self.git(repo,"rev-parse",head+"^").stdout.strip()
        policy = (ROOT/"tools/privacy-check/check.py").read_text()
        policy = re.sub(r"^PUBLIC_ROOT = .*",f"PUBLIC_ROOT = {root!r}",policy,flags=re.M)
        policy = re.sub(r"^PUBLIC_ANCHOR = .*",f"PUBLIC_ANCHOR = {anchor!r}",policy,flags=re.M)
        (self.cli.parent.parent/"privacy-check/check.py").write_text(policy)

    def check(self, version=VERSION, literals="fixture", **env):
        inputs = [] if literals is None else ["--literals", self.literals if literals == "fixture" else literals]
        return run([sys.executable, self.cli, "check", version, "--repo", self.repo,
                    "--plan", self.plan,
                    "--staging", self.stage,"--evidence",self.evidence, *inputs],
                   env=dict(self.env, **env))

    def test_named_terms_input_refuses_before_output_creation(self):
        for value in (None, b"", b"\n", b" \t\n", b"synthetic-private-name\n\n", b"\xff", b"synthetic-private-name\0\n"):
            with self.subTest(value=value):
                self.outputs_clear()
                if value is not None:
                    self.literals.write_bytes(value)
                result = self.check(literals=None if value is None else self.literals)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("named-terms input", result.stderr)
                self.assertFalse(self.stage.exists())
                self.assertFalse(self.evidence.exists())
                self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
        loop = self.root/"input-loop"
        loop.symlink_to(loop.name)
        for path in (self.root/"synthetic-private-name-absent.txt", self.root, loop):
            with self.subTest(path=path.name):
                result = self.check(literals=path)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("named-terms input", result.stderr)
                self.assertNotIn(str(path), result.stdout+result.stderr)
                self.assertFalse(self.stage.exists())
                self.assertFalse(self.evidence.exists())

    def test_named_terms_input_stays_outside_release_outputs(self):
        # R1: a valid private output location must not appear in CLI diagnostics.
        self.evidence = self.root/"synthetic-private-name"
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in (self.stage, self.evidence):
            for item in path.rglob("*"):
                if item.is_file():
                    self.assertNotEqual(item.name, self.literals.name)
                    self.assertNotIn(b"synthetic-private-name", item.read_bytes())
                    self.assertNotIn(b"synthetic.private+name", item.read_bytes())
        self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
        self.assertNotIn("synthetic.private+name", result.stdout+result.stderr)
        self.assertEqual(result.stdout, "release check passed; report.md is in the evidence directory\n")
        for name in ("open-development-privacy.log", "staged-privacy.log"):
            self.assertEqual((self.evidence/name).read_text(), "literals: used\n")

    def test_named_terms_preserve_literal_case_insensitive_refusal_and_exceptions(self):
        # Uppercase bypasses O3's case-sensitive text rule, so this owns the
        # release scanner's existing case-insensitive substring contract.
        self.plant("src/named.txt", "prefix-SYNTHETIC.PRIVATE+NAME-suffix\n")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("internal: src/named.txt", result.stderr)
        self.assertNotIn("SYNTHETIC.PRIVATE+NAME", result.stdout+result.stderr)
        self.outputs_clear()
        self.data["scan_exceptions"] = [{"path": "src/named.txt", "rule": "internal",
            "sha256": hashlib.sha256((self.repo/"src/named.txt").read_bytes()).hexdigest(),
            "value": "SYNTHETIC.PRIVATE+NAME"}]
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.outputs_clear()
        self.data["scan_exceptions"][0]["value"] = "SYNTHETICxPRIVATExNAME"
        self.save_plan()
        self.refused("internal: src/named.txt")
        self.outputs_clear()
        self.plant("src/named.txt", "prefix-SYNTHETICxPRIVATENAME-suffix\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_clean_tree_report_hashes_and_no_publication_or_input_write(self):
        home = self.root/"home"
        temp = self.root/"tmp"
        home.mkdir()
        temp.mkdir()
        self.env.update(HOME=str(home),TMPDIR=str(temp))

        def snapshot():
            files = {}
            for p in self.root.rglob("*"):
                if p.is_relative_to(self.stage) or p.is_relative_to(self.evidence) or p == self.root/"calls.jsonl":
                    continue
                if p.is_symlink():
                    value = ("link",os.readlink(p))
                elif p.is_file():
                    value = ("file",hashlib.sha256(p.read_bytes()).hexdigest())
                else:
                    value = ("directory",)
                files[p.relative_to(self.root).as_posix()] = value
            return files

        before = snapshot()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["version"], VERSION)
        export = self.stage/"export"
        self.assertEqual(self.git(export,"branch","--show-current").stdout.strip(), "export/openwiz-"+VERSION)
        self.assertEqual(self.git(export,"rev-parse","HEAD").stdout.strip(), report["source_head"])
        self.assertEqual(report["export_head"], self.git(export,"rev-parse","HEAD").stdout.strip())
        paths = self.git(export,"ls-tree","-r","--name-only","HEAD").stdout.splitlines()
        self.assertEqual(paths, sorted(f["path"] for f in self.data["files"]))
        self.assertCountEqual([f["path"] for f in report["files"]],paths,"report file coverage")
        manifest = "".join(
            f'{hashlib.sha256((export/path).read_bytes()).hexdigest()}  {path}\n'
            for path in paths)
        self.assertEqual((self.evidence/"EXPORT-FILES.txt").read_text(),manifest,"export manifest")
        self.assertEqual(snapshot(),before,"release check wrote outside staging and evidence")
        for item in report["files"]:
            digest = hashlib.sha256((export/item["path"]).read_bytes()).hexdigest()
            self.assertEqual(item["sha256"],digest)
            self.assertIn(digest, (self.evidence/"report.md").read_text())
        calls = [json.loads(s) for s in (self.root/"calls.jsonl").read_text().splitlines()]
        self.assertTrue(any(c["tool"]=="cargo" and c["args"][0]=="test" for c in calls))
        self.assertFalse(any(c["tool"]=="gh" for c in calls))
        self.assertFalse(any(c["tool"]=="git" and any(a in c["args"] for a in ("push","tag","fetch")) for c in calls))
        for c in calls:
            if c["tool"] in ("cargo","npm","node"):
                self.assertTrue(Path(c["cwd"]).is_relative_to(self.stage), c)


    def plant(self, path, content):
        p = self.repo/path
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(content)
        self.commit(self.repo)
        self.replan()

    def outputs_clear(self):
        for p in (self.stage,self.evidence):
            if p.exists():
                shutil.rmtree(p)

    def refused(self, finding, **env):
        r = self.check(**env)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        if finding in {"identifier", "personal", "URL credentials"} and "open-development-privacy:" in r.stderr:
            log = (self.evidence/"open-development-privacy.log").read_text()
            self.assertRegex(log, r"T[13] ")
        else:
            self.assertIn(finding,r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["status"],"fail")
        self.assertTrue(any(c["status"]=="fail" for c in report["checks"]))

    def test_historical_wording_and_claim_plants(self):
        cases = [
            ("0.0.1-R1", "Live-observation: This command lists real CloudRoom sessions."),
            ("0.0.1-R3", "Fixture-tested: Provider, purpose, model and effort: it reads each session on the page once more to get them."),
            ("0.0.1-D1", "Fixture-tested: `openwiz ls` lists every thread."),
            ("0.0.1-D2", "Fixture-tested: `--json` works on every command."),
            ("0.0.1-D3", "Fixture-tested: It never wakes or marks a thread read."),
            ("0.0.1-D4", "Fixture-tested: Works with whatever room-cli version CloudRoom ships."),
            ("0.0.3-R2", "Fixture-tested: Before you send, it shows the effects."),
        ]
        for finding,text in cases:
            with self.subTest(finding=finding):
                self.outputs_clear()
                self.plant("README.md","# Synthetic\n\n"+text+"\n")
                self.refused(finding)

    def test_historical_date_identity_help_and_count(self):
        self.plant("CHANGELOG.md","# Changelog\n\n## 0.0.99 — unreleased\n")
        self.refused("0.0.1-R2")
        self.outputs_clear()
        self.plant("CHANGELOG.md",fixture_files()["CHANGELOG.md"])
        self.data["identity"]["email"] = "synthetic@example.invalid"
        self.save_plan()
        self.refused("no-reply")
        self.outputs_clear()
        self.replan()
        self.plant("README.md","# Synthetic\n\nUnverified: "+"LIVE-PENDING "*36+"\n")
        self.data["live_pending"] = 35
        self.save_plan()
        self.refused("0.0.3-R6")
        self.outputs_clear()
        self.data["live_pending"] = 36
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode,0,r.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["live_pending"],36)
        self.assertIn("LIVE-PENDING occurrences: 36",(self.evidence/"report.md").read_text())
        self.outputs_clear()
        self.refused("0.0.3-R5",HELP_TRAILING="1")

    def test_privacy_scan_every_file_and_bad_links(self):
        cases = [
            ("secret", "ghp_"+"SYNTHETICVALUE"*3),
            ("personal", "/Users/synthetic-owner/notes"),
            ("identifier", "thr_syntheticprivate123"),
            ("private-link", "https://github.com/synthetic/ClosedWiz/issues/7"),
            ("private-link", "https://private.example.net/account"),
            ("private-link: private URL", "Fixture-tested: https://github.com/%252570rivate/synthetic"),
            ("internal", "Sol round 3, ticket 123, sheet WS-5"),
            ("link", "[missing](missing.md)"),
            ("link", "[missing anchor](docs/evidence/check.md#absent)"),
            ("link", "<img src=\"missing.png\">"),
            ("link", "[broken][ref]\n\n[ref]: missing.md"),
            ("claim", "This command works with a real account."),
            ("claim", "#This command works with a real account."),
        ]
        for finding,text in cases:
            with self.subTest(finding=finding):
                self.outputs_clear()
                self.plant("README.md","# Synthetic\n\n"+text+"\n")
                self.refused(finding)
        self.outputs_clear()
        self.plant("README.md",fixture_files()["README.md"])
        # Read to EOF: the plant is after a full megabyte of ordinary text in a non-doc file.
        self.plant("src/note.txt",("x"*99+"\n")*11_000+"\nghp_"+"SYNTHETICVALUE"*3)
        self.refused("secret")

    def test_public_rust_environment_names_pass_without_scan_exceptions(self):
        source = fixture_files()["src/main.rs"]
        for name in ("env_host", ".env_remove(", ".env_clear(", "ENV_LOG_FILE", "ENV_PREFIXES"):
            self.assertIn(name, source, "the clean fixture must retain the reported Rust names")
        self.plant("src/main.rs", source + """
fn env_host() {
    let env_host = None::<String>;
    let mut command = std::process::Command::new("synthetic");
    command.env_remove("SYNTHETIC").env_clear();
    let _ = env_host;
}
const ENV_LOG_FILE: &str = "environment.log";
const ENV_PREFIXES: &[&str] = &["SYNTHETIC_"];
fn env_configuration_value() {}
""")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_numeric_colour_literals_pass_without_scan_exceptions(self):
        for path, template in (
            ("tools/war-room/styles/fixture.css", ".fixture {{ color: {colour}; }}"),
            ("docs/assets/fixture.svg", '<svg><path fill="{colour}"/></svg>'),
            ("tools/war-room/test/fixture.mjs", "const style = {{ background: '{colour}' }};"),
            ("tools/war-room/src/fixture.tsx", 'const style = {{ color: "{colour}" }};'),
            ("tools/war-room/fixture.html", '<div style="color: {colour};"></div>'),
            ("docs/assets/fixture.svg", '<svg style="fill: {colour};"/>'),
            ("docs/assets/fixture.svg", '<svg><style>path {{ fill: {colour}; }}</style></svg>'),
            ("tools/war-room/styles/fixture.css", ".fixture {{ border: 1px solid {colour}; }}"),
        ):
            for colour in ("#123", "#1234", "#151719", "#12345678"):
                with self.subTest(path=path, colour=colour):
                    self.outputs_clear()
                    self.reset_fixture()
                    self.plant(path, template.format(colour=colour) + "\n")
                    result = self.check()
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_settings_local_ignore_entries_pass_without_scan_exceptions(self):
        self.plant(".gitignore", "settings.local\n.claude/settings.local.json\n/.claude/settings.local.json\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_literal_exemptions_keep_privacy_guards(self):
        cases = [
            ("identifier", "src/ids.txt", prefix + "_abcdefghij")
            for prefix in ("thr", "prj", "mch", "evt", "env", "usr", "acct", "ses", "org")
        ] + [
            ("identifier", "src/ids.txt", prefix + "_abcdefghi")
            for prefix in ("thr", "prj", "mch", "evt", "env", "usr", "acct", "ses", "org")
        ] + [
            ("identifier", "src/ids.txt", "THR_short"),
            ("identifier", "src/ids.txt", "thr" + "_short_suffix"),
            ("identifier", "src/ids.txt", "env_host"),
            ("identifier", "src/ids.txt", "env_syntheticprivate123"),
            ("internal", "src/note.txt", "#123"),
            ("internal", "src/lib.rs", "//! Background: #613 explains this module."),
            ("internal", "src/note.txt", "Fill: #1234 tracks the rollout."),
            ("internal", "tools/war-room/test/fixture.mjs", "// stroke = #613 regression"),
            ("internal", "tools/war-room/test/fixture.mjs", 'export const message = "Background: #613 explains this module.";'),
            ("internal", "tools/war-room/test/fixture.mjs", 'export const message = "Background: \'#613\' explains this module.";'),
            ("internal", "tools/war-room/test/fixture.mjs", "export const message = `Background: '#613' explains this module.`;"),
            ("internal", "tools/war-room/test/fixture.mjs", "export const pattern = /Background: '#613' explains this module./;"),
            ("internal", "tools/war-room/test/fixture.mjs", "const style = { background: '#613 explains this module.' };"),
            ("internal", "tools/war-room/test/fixture.mjs", "const issue = '#123';"),
            ("internal", "tools/war-room/styles/fixture.css", ".fixture { color: #12345; }"),
            ("internal", "docs/assets/fixture.svg", '<svg fill="#1234567"/>'),
            ("internal", "tools/war-room/test/fixture.mjs", "const style = { color: '#123456789' };"),
            ("internal", "tools/war-room/styles/fixture.css", "/* PR #123 */"),
            ("internal", "tools/war-room/styles/fixture.css", "/* see #123 */"),
            ("internal", "tools/war-room/styles/fixture.css", "/* color: #123 */"),
            ("internal", "docs/assets/fixture.svg", "<svg><text>See issue #123 </text></svg>"),
            ("internal", "docs/assets/fixture.svg", "<svg><text>color: #123 </text></svg>"),
            ("internal", "docs/assets/fixture.svg", '<svg><!-- <path fill="#123"/> --></svg>'),
            ("internal", "docs/assets/fixture.svg", '<svg><path data-note="color: #123 "/></svg>'),
            ("personal", "src/host.txt", "settings.local"),
            ("personal", ".gitignore", "server.local\n"),
            ("personal", ".gitignore", "# connect to settings.local\n"),
        ]
        for rule, path, text in cases:
            with self.subTest(rule=rule, path=path, text=text):
                self.outputs_clear()
                # Every plant is independent, including paths left by prior cases.
                self.reset_fixture()
                self.plant(path, text + "\n")
                self.refused(rule)
                if text == "thr" + "_short_suffix":
                    self.assertEqual((self.evidence/"open-development-privacy.log").read_text(),
                        'T1 tree:"src/ids.txt":1\nT1 commit-tree-1:"src/ids.txt":1\nliterals: used\n')

    def test_invalid_inputs_and_checks_fail_closed(self):
        for tool in ("cargo",):
            with self.subTest(tool=tool):
                self.outputs_clear()
                self.refused("failed (exit 42)",FAIL_TOOL=tool)
        self.outputs_clear()
        self.refused("no passing Rust tests",ZERO_TESTS="1")
        self.outputs_clear()
        self.data["files"][0]["sha256"] = "0"*64
        self.save_plan()
        self.refused("hash differs")
        self.outputs_clear()
        self.replan()
        self.data["files"][0]["path"] = "../outside"
        self.save_plan()
        self.refused("unsafe path")
        self.outputs_clear()
        self.replan()
        self.data["files"].append(self.data["files"][0])
        self.save_plan()
        self.refused("duplicate destination")
        self.outputs_clear()
        self.replan()
        self.data["claim_reviews"] = []
        self.save_plan()
        self.refused("claim")

    def test_missing_regression_proofs_fail(self):
        required = [
            ("0.0.3-R3","crates/adapters/cloudroom/src/process.rs"),
        ]
        for finding,path in required:
            with self.subTest(finding=finding):
                self.outputs_clear()
                self.reset_fixture()
                self.plant(path,"// Synthetic feature whose public proof is absent.\n")
                self.refused(finding)


    def test_no_python_cache_written_outside_outputs(self):
        # Copy the command so this proof does not depend on an existing pyc cache.
        runner = self.root/"runner"
        shutil.copytree(CLI.parent,runner,ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.cli.parent.parent/"privacy-check",self.root/"privacy-check",ignore=shutil.ignore_patterns("__pycache__"))
        result = run(["python3",runner/"release","check",VERSION,"--repo",self.repo,
                      "--plan",self.plan,"--staging",self.stage,
                      "--evidence",self.evidence,"--literals",self.literals],env=self.env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((runner/"__pycache__").exists(),"check wrote outside staging and evidence")

    def test_checker_uses_running_python_without_python_on_path(self):
        self.env["PATH"] = str(self.bin)
        self.assertIsNone(shutil.which("python3",path=self.env["PATH"]))
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        self.outputs_clear()
        (self.bin/"cargo").unlink()
        self.refused("cannot run cargo")

    def test_missing_tools_duplicate_keys_bad_binary_and_symlink(self):
        (self.bin/"cargo").unlink()
        # Deliberately hide any installed cargo as well.
        self.env["PATH"] = str(self.bin)+":/usr/bin:/bin"
        self.refused("cannot run cargo")
        self.outputs_clear()
        self.plan.write_text(self.plan.read_text().replace('"schema":', '"schema":"duplicate", "schema":',1))
        self.refused("duplicate manifest key")
        self.outputs_clear()
        self.replan()
        p = self.repo/"unknown.bin"
        p.write_bytes(b"\x00\xff\x80synthetic binary")
        self.commit(self.repo)
        self.replan()
        self.refused("binary")
        self.outputs_clear()
        p.unlink()
        (self.repo/"shortcut").symlink_to("README.md")
        self.commit(self.repo)
        self.replan()
        self.refused("symlink")

    def test_fresh_clone_failure_keeps_output_and_stops(self):
        self.refused("failed (exit 42)",FAIL_TOOL="cargo")
        logs = list(self.evidence.glob("build-*.log"))
        self.assertEqual(len(logs),1)
        self.assertIn("synthetic tool failure",logs[0].read_text())

    def regression_fixture(self):
        proofs = {
            "crates/adapters/cloudroom/src/process.rs":"// Synthetic process\n",
            "tests/messaging/environment.rs":"fn every_read_runs_without_the_thread_context() {}\nfn every_call_of_a_send_runs_without_the_thread_context() {}\n",
        }
        for path,text in proofs.items():
            p = self.repo/path
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(text)
        self.commit(self.repo)
        self.replan()

    def test_public_regressions_run_and_refuse_planted_failures(self):
        self.regression_fixture()
        r = self.check()
        self.assertEqual(r.returncode,0,r.stderr)
        cases = [("0.0.3-R3","every_read_runs_without_the_thread_context"),
                 ("0.0.3-R3","every_call_of_a_send_runs_without_the_thread_context")]
        # The fake evaluates the planted tree, simulating each exported public
        # regression failing. These prove orchestration, not product behaviour.
        for finding,test in cases:
            with self.subTest(finding=finding,test=test):
                self.outputs_clear()
                self.plant("regression-failure.txt",test)
                self.refused(finding)
        self.outputs_clear()
        self.plant("regression-failure.txt","no failure")
        self.refused("exactly one passing regression",REGRESSION_ZERO="1")

    def test_named_regressions_cannot_be_missing_from_existing_proof_files(self):
        cases = [
            ("tests/messaging/environment.rs","every_read_runs_without_the_thread_context"),
            ("tests/messaging/environment.rs","every_call_of_a_send_runs_without_the_thread_context"),
        ]
        for path,name in cases:
            with self.subTest(name=name):
                self.outputs_clear()
                self.regression_fixture()
                proof = self.repo/path
                self.plant(path,proof.read_text().replace("fn "+name+"(","fn renamed_regression("))
                self.refused("missing named regression")

    def test_named_regression_cargo_calls_are_locked(self):
        self.regression_fixture()
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        calls = [json.loads(line) for line in (self.root/"calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["args"] for c in calls if c["tool"] == "cargo" and "-p" in c["args"]],
                         [["test","--locked","-p","openwiz-tests","--test","messaging",name] for name in (
                             "every_read_runs_without_the_thread_context",
                             "every_call_of_a_send_runs_without_the_thread_context")])

    def test_cargo_build_and_clippy_are_locked(self):
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        calls = [json.loads(line) for line in (self.root/"calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["args"] for c in calls if c["tool"] == "cargo"], [
            ["build","--workspace","--release","--locked"], ["test","--workspace","--locked"],
            ["fmt","--check"], ["clippy","--workspace","--all-targets","--locked","--","-D","warnings"]])

    def test_export_refuses_an_extra_committed_file(self):
        self.refused("allowlist does not equal export tree",EXTRA_EXPORT_FILE="1")

    def test_export_refuses_changed_committed_mode(self):
        self.refused("committed export mode differs",FLIP_EXPORT_MODE="1")

    def test_fresh_clone_refuses_a_build_that_changes_tracked_files(self):
        self.refused("fresh clone changed tracked files",DIRTY_BUILD="1")

    def test_existing_outputs_are_refused_before_any_write(self):
        for output,other in ((self.stage,self.evidence),(self.evidence,self.stage)):
            with self.subTest(output=output.name):
                self.outputs_clear()
                output.mkdir()
                sentinel = output/"keep.txt"
                sentinel.write_text("Synthetic existing output\n")
                result = self.check()
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertIn("output directory already exists",result.stderr)
                self.assertEqual(list(output.iterdir()),[sentinel])
                self.assertEqual(sentinel.read_text(),"Synthetic existing output\n")
                self.assertFalse(other.exists())

    def test_outputs_inside_input_repositories_are_refused_before_any_write(self):
        for repo in (self.repo,):
            for attribute in ("stage","evidence"):
                with self.subTest(repo=repo.name,output=attribute):
                    original = getattr(self,attribute)
                    nested = repo/".git"/"release-output"
                    setattr(self,attribute,nested)
                    try:
                        result = self.check()
                    finally:
                        setattr(self,attribute,original)
                    self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                    self.assertIn("output overlaps input repository",result.stderr)
                    self.assertFalse(nested.exists())
                    self.assertFalse(self.stage.exists())
                    self.assertFalse(self.evidence.exists())

    def test_messaging_is_refused_before_version_0_0_3(self):
        self.git(self.repo,"branch","-m","release-0.0.2")
        self.plant("CHANGELOG.md",fixture_files()["CHANGELOG.md"].replace(VERSION,"0.0.2"))
        paths = ("crates/x/src/messaging/mod.rs","crates/x/src/messaging.rs")
        for path in paths:
            with self.subTest(path=path):
                self.outputs_clear()
                shutil.rmtree(self.repo/"crates",ignore_errors=True)
                self.plant(path,"// Synthetic messaging feature\n")
                self.data["version"] = "0.0.2"
                self.save_plan()
                self.refused("later-version messaging code in a read-only release",version="0.0.2")

    def test_public_license_cannot_be_changed(self):
        original = "Synthetic license fixture retained verbatim.\n"
        (self.public/"LICENSE").write_text(original)
        self.commit(self.public)
        self.base = self.git(self.public,"rev-parse","HEAD").stdout.strip()
        self.plant("LICENSE",original)
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        self.outputs_clear()
        self.plant("LICENSE","Synthetic changed license.\n")
        self.refused("public license must be retained unmodified")

    def test_claim_review_hash_status_and_evidence_fail_closed(self):
        self.data["claim_reviews"][0]["sha256"] = "f"*64
        self.save_plan()
        self.refused("claim review is stale")
        self.outputs_clear()
        self.replan()
        self.data["claim_reviews"][0]["claims"][0]["status"] = "formally-proven"
        self.save_plan()
        self.refused("claim status unknown")
        self.outputs_clear()
        self.replan()
        self.data["claim_reviews"][0]["claims"][0]["evidence"] = "https://private.example.net/proof"
        self.save_plan()
        self.refused("relative public evidence")


    def test_exact_hash_bound_scan_exceptions(self):
        # Public scan tests legitimately contain synthetic planted values.
        # An exception is one exact match in one exact reviewed file revision.
        self.plant("src/scan-test.txt","/Users/synthetic-owner\n")
        self.refused("personal")
        self.outputs_clear()
        digest = hashlib.sha256((self.repo/"src/scan-test.txt").read_bytes()).hexdigest()
        self.data["scan_exceptions"] = [{"path":"src/scan-test.txt","sha256":digest,
                                       "rule":"personal","value":"/Users/synthetic-owner"}]
        self.save_plan()
        r = self.check()
        self.assertEqual(r.returncode,0,r.stderr)
        self.outputs_clear()
        self.data["scan_exceptions"][0]["sha256"] = "f"*64
        self.save_plan()
        self.refused("stale scan exception")
        self.outputs_clear()
        self.data["scan_exceptions"][0]["sha256"] = digest
        self.data["scan_exceptions"][0]["value"] = "/Users/synthetic-other-owner"
        self.save_plan()
        self.refused("personal")
        self.assertEqual(json.loads((self.evidence/"report.json").read_text())["checks"][-1],
                         {"id": "privacy", "status": "fail", "reason": "personal: src/scan-test.txt"})

    def test_unreviewed_secret_hex_and_encoded_json(self):
        self.plant("src/hex.txt","1234567890abcdef"*4)
        self.refused("secret-hex")
        self.outputs_clear()
        (self.repo/"src/hex.txt").unlink()
        self.plant("src/encoded.json",'{"value":"thr_\\u0073yntheticprivate123"}\n')
        self.refused("identifier")


    def test_git_attributes_cannot_change_reported_export_bytes(self):
        # Same-path tracked attributes differ only in the source's local override.
        # The public clone has no override and normalizes the approved CRLF blob.
        (self.repo/".gitattributes").write_text("*.txt text eol=lf\n")
        info = self.repo/".git/info/attributes"
        info.write_text("normalization.txt -text\n")
        (self.repo/"normalization.txt").write_bytes(b"synthetic\r\n")
        self.commit(self.repo)
        self.assertEqual(self.git(self.repo,"status","--porcelain").stdout,"")
        self.replan()
        self.refused("committed export hash differs")
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["checks"][-1]["id"],"stage")

    def test_angle_destination_with_spaces_cannot_skip_link_check(self):
        self.plant("README.md","# Synthetic\n\nFixture-tested: [missing](<missing file.md>).\n")
        self.refused("link target missing")


    def test_unlisted_release_symlinks_are_refused(self):
        p = self.repo/"private-helper-link"
        p.symlink_to("public/README.md")
        self.commit(self.repo)
        r = self.check()
        self.assertEqual(r.returncode,1,r.stderr)
        self.assertIn("allowlist does not equal release tree",r.stderr)

    def test_later_version_code_and_removed_public_license_are_refused(self):
        self.plant("crates/core/src/new_thread/mod.rs","// Synthetic later-version capability\n")
        self.plant("CHANGELOG.md",fixture_files()["CHANGELOG.md"].replace("0.0.99","0.0.3"))
        self.git(self.repo,"branch","-m","release-0.0.3")
        self.data["version"] = "0.0.3"
        self.save_plan()
        r = self.check(version="0.0.3")
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn("later-version",r.stderr)

    def test_public_license_cannot_be_removed_or_changed(self):
        (self.public/"LICENSE").write_text("Synthetic license fixture retained verbatim.\n")
        self.commit(self.public)
        self.base = self.git(self.public,"rev-parse","HEAD").stdout.strip()
        self.replan()
        self.refused("public license")


    def test_effects_wording_in_decisions_is_rejected_but_page_scope_passes(self):
        original = ("Fixture-tested: **Effects before sending.** Sending starts a turn on an idle thread "
                    "and may wake it; that is said before you press. A queue that appears paused is "
                    "resumed only when you say so, and the effect is shown first.")
        for text in (original, "Fixture-tested: That is said before you press.",
                     "Fixture-tested: The effect is shown first."):
            with self.subTest(text=text):
                self.outputs_clear()
                self.plant("docs/decisions.md","# Decisions\n\n"+text+"\n")
                self.refused("0.0.3-R2")
        self.outputs_clear()
        fixed = ("Fixture-tested: **Effects before sending.** Sending starts a turn on an idle thread "
                 "and may wake it. On the page, the message box says so before you press; in the terminal, "
                 "`openwiz send --preview` says so without sending, and `openwiz send` prints the effects "
                 "with its report, after sending. A queue that appears paused is resumed only when you "
                 "say so: the page shows that effect first, and `openwiz send` refuses without "
                 "`--resume-paused-queue`.")
        self.plant("docs/decisions.md","# Decisions\n\n"+fixed+"\n")
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)


    def allow_url(self, path, url):
        row = next(f for f in self.data["files"] if f["path"] == path)
        self.data["scan_exceptions"] = [{"path":path,"sha256":row["sha256"],
                                        "rule":"url","value":url}]
        self.save_plan()

    def test_reviewed_urls_are_exact_hash_bound_exceptions(self):
        cases = [
            ("docs/assets/diagram.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>\n',
             "http://www.w3.org/2000/svg"),
            ("tools/war-room/package-lock.json", '{"funding":{"url":"https://opencollective.com/libvips"}}\n',
             "https://opencollective.com/libvips"),
            ("contracts/fixture.schema.json", '{"$schema":"https://json-schema.org/draft/2020-12/schema"}\n',
             "https://json-schema.org/draft/2020-12/schema"),
            ("src/template.rs", 'const TEMPLATE: &str = "http://{}";\n', "http://{}"),
            ("src/template.mjs", 'const origin = `http://${req.headers.host}`;\n', "http://${req.headers.host}"),
            ("docs/links.md", '# Links\n\nFixture-tested: [Public documentation](https://docs.github.com/en).\n',
             "https://docs.github.com/en"),
        ]
        for path,text,url in cases:
            with self.subTest(path=path):
                self.outputs_clear()
                self.reset_fixture()
                self.plant(path,text)
                self.refused("private-link: unreviewed host")
                self.outputs_clear()
                self.allow_url(path,url)
                result = self.check()
                self.assertEqual(result.returncode,0,result.stderr)
                report = json.loads((self.evidence/"report.json").read_text())
                self.assertEqual(report["scan_exceptions"],[{k:v for k,v in self.data["scan_exceptions"][0].items() if k != "value"}])

    def test_url_exception_decoding_and_angle_destinations_agree(self):
        path = "docs/links.md"
        cases = [
            ("https://docs.github.com/synthetic%2520path", "https://docs.github.com/synthetic%20path"),
            ("https://docs.github.com/synthetic)path", "https://docs.github.com/synthetic)path"),
            ("https://docs.github.com/synthetic)%2520path?a=1&amp;b=2",
             "https://docs.github.com/synthetic)%20path?a=1&b=2"),
        ]
        for source,reviewed in cases:
            with self.subTest(url=source):
                self.outputs_clear()
                self.plant(path,f'# Links\n\nFixture-tested: [Synthetic](<{source}>).\n')
                self.allow_url(path,reviewed)
                result = self.check()
                self.assertEqual(result.returncode,0,result.stderr)
                report = json.loads((self.evidence/"report.json").read_text())
                self.assertEqual(report["status"],"pass")
                self.assertEqual(len(report["scan_exceptions"]),1)
                self.outputs_clear()
                self.allow_url(path,reviewed+"-other")
                self.refused("private-link: unreviewed host")

    def test_reviewed_destination_does_not_hide_other_urls(self):
        path = "docs/links.md"
        reviewed = "https://docs.github.com/synthetic)path"
        cases = [
            f'[Synthetic](<{reviewed}>) and {other}.'
            for other in ("https://docs.github.com/synthetic", reviewed+"-other")
        ]+[
            "[S](<https://github.com/a)https://intranet.synthetic-corp.net/x>)",
            "[S](https://github.com/a%20https://intranet.synthetic-corp.net/x)",
            "[S](<https://github.com/a https://intranet.synthetic-corp.net/x>)",
            "[S](<HTTPS://github.com/a)https://intranet.synthetic-corp.net/x>)",
        ]
        for markdown in cases:
            with self.subTest(markdown=markdown):
                self.outputs_clear()
                self.plant(path,f'# Links\n\nFixture-tested: {markdown}\n')
                if reviewed in markdown:
                    self.allow_url(path,reviewed)
                self.refused("private-link: unreviewed host")

    def test_url_exceptions_cannot_authorize_private_or_credential_urls(self):
        cases = [
            ("https://user:pass@github.com/synthetic", "URL credentials"),
            ("ftp://github.com/synthetic", "unknown scheme"),
            ("javascript:synthetic", "unknown scheme"),
            ("https://docs.github.com/ClosedWiz", "private URL"),
            ("https://docs.github.com/private/synthetic", "private URL"),
            ("https://docs.github.com/Users/synthetic", "private URL"),
            ("https://docs.github.com/home/synthetic", "private URL"),
            ("https://docs.github.com/%70rivate/synthetic", "private URL"),
        ]
        for url,reason in cases:
            with self.subTest(url=url):
                self.outputs_clear()
                self.plant("docs/links.md",f'# Links\n\nFixture-tested: [Synthetic]({url}).\n')
                self.allow_url("docs/links.md",url)
                self.refused("private-link: "+reason)

    def test_reviewed_url_exceptions_refuse_stale_duplicate_or_unused_entries(self):
        url = "http://www.w3.org/2000/svg"
        path = "docs/assets/diagram.svg"
        self.plant(path,f'<svg xmlns="{url}"/>\n')
        self.allow_url(path,url)
        exception = dict(self.data["scan_exceptions"][0])
        cases = [
            ([dict(exception,sha256="f"*64)], "stale scan exception"),
            ([dict(exception,path="src/absent.rs")], "stale scan exception"),
            ([exception,exception], "duplicate scan exception"),
            ([dict(exception,value=url+"-other")], "private-link: unreviewed host"),
            ([exception,dict(exception,value="https://docs.github.com/unused")], "unused scan exception"),
        ]
        for entries,reason in cases:
            with self.subTest(reason=reason):
                self.outputs_clear()
                self.data["scan_exceptions"] = entries
                self.save_plan()
                self.refused(reason)


    def test_unpublished_claim_guard_has_public_live_evidence(self):
        self.plant("docs/evidence/check.md", "# Evidence\n\n## Fixture\n\n"
                   "Live-observation: Synthetic invented observation for a guard fixture.\n")
        self.plant("README.md", "# Synthetic\n\nLive-observation: This command lists real CloudRoom "
                   "sessions; the records are not published.\n")
        self.refused("0.0.1-R1: live capability has unpublished evidence")


    def allow_historical(self, path, value):
        row = next(f for f in self.data["files"] if f["path"] == path)
        self.data["scan_exceptions"] = [{"path":path,"sha256":row["sha256"],
                                        "rule":"historical","value":value}]
        self.save_plan()

    def test_uncertainty_about_read_effects_is_not_an_absolute_claim(self):
        cases = [
            ("README.md", "Unverified: That is not proof that a read can never wake a session or mark it read."),
            ("docs/evidence/check.md", "Unverified: That a read can never wake a thread or mark it read is not proven."),
        ]
        for path,text in cases:
            with self.subTest(path=path):
                self.outputs_clear()
                if path == "docs/evidence/check.md":
                    text = "# Evidence\n\n## Fixture\n\n"+text+"\n"
                else:
                    text = "# Synthetic\n\n"+text+"\n"
                self.plant(path,text)
                result = self.check()
                self.assertEqual(result.returncode,0,result.stderr)
        for text in ("It never wakes or marks a thread read.","OpenWiz never wakes a session.",
                     "Reads never wake a session.","It never marks a thread read."):
            with self.subTest(absolute=text):
                self.outputs_clear()
                self.plant("README.md","# Synthetic\n\nFixture-tested: "+text+"\n")
                self.refused("0.0.1-D3")

    def test_historical_wording_exception_requires_exact_approval(self):
        path = "docs/interface.md"
        self.plant(path,"# Interface\n\nFixture-tested: It never wakes, launches, resumes or messages.\n")
        self.refused("0.0.1-D3")
        self.outputs_clear()
        self.allow_historical(path,"It never wakes")
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads((self.evidence/"report.json").read_text())
        self.assertEqual(report["scan_exceptions"],[{k:v for k,v in self.data["scan_exceptions"][0].items() if k != "value"}])

    def test_historical_exceptions_refuse_stale_duplicate_and_unused_entries(self):
        path = "docs/interface.md"
        self.plant(path,"# Interface\n\nFixture-tested: It never wakes, launches, resumes or messages.\n")
        self.allow_historical(path,"It never wakes")
        entry = dict(self.data["scan_exceptions"][0])
        other = next(f for f in self.data["files"] if f["path"] == "README.md")
        cases = [
            ([dict(entry,sha256="0"*64)], "stale scan exception"),
            ([dict(entry,path="README.md",sha256=other["sha256"])], "0.0.1-D3"),
            ([dict(entry,path="src/absent.rs")], "stale scan exception"),
            ([entry,entry], "duplicate scan exception"),
            ([dict(entry,value="it never wakes")], "0.0.1-D3"),
            ([dict(entry,value="It never wakes, launches")], "0.0.1-D3"),
            ([entry,dict(entry,value="Unused historical wording")], "unused scan exception"),
        ]
        for entries,reason in cases:
            with self.subTest(reason=reason):
                self.outputs_clear()
                self.data["scan_exceptions"] = entries
                self.save_plan()
                self.refused(reason)

    def test_reserved_credential_urls_need_exact_review(self):
        for host in ("example.invalid","synthetic.example","example.com"):
            with self.subTest(host=host):
                self.outputs_clear()
                url = f"https://synthetic-user:synthetic-pass@{host}/v1/threads"
                self.plant("src/diag.rs",f'const SYNTHETIC_URL: &str = "{url}";\n')
                self.refused("URL credentials")
                self.outputs_clear()
                self.allow_url("src/diag.rs",url)
                if host == "example.com":
                    # The existing personal-data rule also sees this email-shaped
                    # substring. Its separate, exact review remains required.
                    self.data["scan_exceptions"].append(dict(self.data["scan_exceptions"][0],
                        rule="personal",value="synthetic-pass@example.com"))
                    self.save_plan()
                result = self.check()
                self.assertEqual(result.returncode,0,result.stderr)
                self.outputs_clear()
                self.data["scan_exceptions"][0]["value"] = url+"-other"
                self.save_plan()
                self.refused("URL credentials")
                self.outputs_clear()
                self.allow_url("src/diag.rs",url)
                self.data["scan_exceptions"][0]["sha256"] = "f"*64
                self.save_plan()
                self.refused("stale scan exception")

    def test_credential_url_exceptions_cannot_extend_reserved_domain_scope(self):
        for host in ("github.com","notexample.com","example.com.attacker.invalid.test", "example.invalid.test", "example.example.test"):
            with self.subTest(host=host):
                self.outputs_clear()
                url = f"https://synthetic-user:synthetic-pass@{host}/synthetic"
                self.plant("src/diag.rs",f'const SYNTHETIC_URL: &str = "{url}";\n')
                self.allow_url("src/diag.rs",url)
                self.refused("URL credentials")
        for url,reason in (("ftp://synthetic-user:synthetic-pass@example.invalid/synthetic","unknown scheme"),
                           ("https://synthetic-user:synthetic-pass@example.invalid/private/synthetic","private URL")):
            with self.subTest(url=url):
                self.outputs_clear()
                self.plant("src/diag.rs",f'const SYNTHETIC_URL: &str = "{url}";\n')
                self.allow_url("src/diag.rs",url)
                self.refused(reason)


    def test_historical_exception_does_not_replace_date_or_evidence_checks(self):
        path = "docs/interface.md"
        self.plant(path,"# Interface\n\nFixture-tested: It never wakes, launches, resumes or messages.\n")
        self.plant("CHANGELOG.md","# Changelog\n\n## 0.0.99 — unreleased\n")
        self.allow_historical(path,"It never wakes")
        self.refused("0.0.1-R2")
        self.outputs_clear()
        self.plant("CHANGELOG.md",fixture_files()["CHANGELOG.md"])
        self.plant("README.md","# Synthetic\n\nLive-observation: This command lists real CloudRoom sessions.\n")
        self.allow_historical(path,"It never wakes")
        self.refused("0.0.1-R1: live capability needs published live evidence")


def live_smoke_receipts():
    """#1844's candidate-bound smoke/risk receipt proofs, loaded by path like
    the restriction proofs; their fake program is written once, at import."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "live_smoke_test_receipt", Path(__file__).resolve().parents[1]/"live-smoke"/"test_receipt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tests(loader, tests, pattern):
    """CI runs this file: include the entry, publish and backfill proofs too."""
    import test_backfill, test_candidate, test_entry, test_publish, test_open, test_review
    for module in (test_entry, test_publish, test_backfill, test_open, test_review, live_smoke_receipts(),
                   test_candidate):
        tests.addTests(loader.loadTestsFromModule(module))
    return tests


# Include export-wording regressions in the existing CI entrypoint.
from test_export_review import ExportFindings

def cpus():
    """The CPUs this process may use: its affinity, capped by a cgroup v2 quota."""
    count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            count = min(count, max(1, int(quota)//int(period)))
    except (OSError, ValueError):
        pass
    return count


def main():
    """Run the cases at once and print each case's time.

    Two threads per CPU, at most 8: a case mostly waits on its subprocesses
    and the file system (measured: 3 threads on 3 CPUs took 17 s, 6 took 10 s),
    and 8 keeps memory small on a 2 GiB runner.

    The cases are independent: each has its own temporary directory, recording
    tools and environment, and changes no process-wide state. With arguments
    (a case name, -k), this is plain unittest, one case after another.
    """
    if len(sys.argv) > 1:
        unittest.main(verbosity=2)
    tests = [test for case in (ReleaseCheck, ExportFindings)
             for test in unittest.defaultTestLoader.loadTestsFromTestCase(case)]
    # CI runs this file only: the entry, publish and backfill proofs run here too.
    import test_backfill, test_candidate, test_entry, test_publish, test_open, test_review

    def flat(suite):
        for item in suite:
            yield from (flat(item) if isinstance(item, unittest.TestSuite) else (item,))
    # #1843: the checked public release command's proofs (test_candidate).
    for module in (test_entry, test_publish, test_backfill, test_open, test_review, live_smoke_receipts(),
                   test_candidate):
        tests += list(flat(unittest.defaultTestLoader.loadTestsFromModule(module)))
    if not tests:
        print("no release proofs found", file=sys.stderr)
        return 1

    def run(test):
        result = unittest.TestResult()
        began = time.monotonic()
        test.run(result)
        return test, result, time.monotonic()-began

    began = time.monotonic()
    workers = min(8, 2*cpus())
    print(f"Running {len(tests)} tests on {workers} threads", file=sys.stderr, flush=True)
    problems, failed = [], 0
    with ThreadPoolExecutor(workers) as pool:
        for done in as_completed([pool.submit(run, test) for test in tests]):
            test, result, seconds = done.result()
            status = "ERROR" if result.errors else "ok" if result.wasSuccessful() else "FAIL"
            failed += status != "ok"
            problems += [("ERROR", case, trace) for case, trace in result.errors]
            problems += [("FAIL", case, trace) for case, trace in result.failures]
            problems += [("UNEXPECTED SUCCESS", case, "") for case in result.unexpectedSuccesses]
            print(f"{test._testMethodName} ({test.id()}) ... {status} ({seconds:.2f} s)", file=sys.stderr, flush=True)
    for status, case, trace in problems:
        print(f"{'='*70}\n{status}: {case}\n{'-'*70}\n{trace}", file=sys.stderr)
    print(f"{'-'*70}\nRan {len(tests)} tests in {time.monotonic()-began:.3f}s\n", file=sys.stderr)
    print(f"FAILED ({failed} of {len(tests)} tests)" if failed else "OK", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
