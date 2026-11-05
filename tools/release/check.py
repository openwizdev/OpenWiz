#!/usr/bin/env python3
"""Check and stage a public release branch in isolation; never publish."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys


class Refused(Exception):
    pass


def require(ok, message):
    if not ok:
        raise Refused(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate manifest key")
        value[key] = item
    return value


def shape(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys.split()), "unexpected manifest shape")


def safe_path(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.@+/-]+", value) is not None,
            "path must be a plain relative ASCII file path")
    require(all(p not in ("", ".", "..", ".git") for p in value.split("/")), "unsafe path")
    require(not value.startswith("/"), "absolute path")
    return value


# The hash-bound plan approves each public file. O2 keeps only private/ and
# grills other than their README private by class; public guidance, design and
# release-proof documents are no longer excluded as private process files.
ALIAS = re.compile(r"\.(?:agents|claude)/skills/([a-z0-9][a-z0-9-]*)")
MODES = ("100644", "100755", "120000")


def public_path(value, product=False):
    safe_path(value)
    parts = PurePosixPath(value).parts
    require(not any(p in {"private", "node_modules", "target", "out", ".next", "test-results"}
                    or p.startswith(".env") for p in parts), "forbidden public path")
    require(not value.startswith("docs/grills/") or value == "docs/grills/README.md",
            "private process document")
    return value


def git_env():
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("GIT_"):
            del env[key]
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="0")
    return env


def command(args, cwd, env, timeout=1800, log=None):
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"cannot run {args[0]}: {type(error).__name__}") from error
    if log is not None:
        log.write_bytes(result.stdout+result.stderr)
    require(result.returncode == 0, f"{args[0]} {args[1]} failed (exit {result.returncode})")
    return result.stdout


def git(repo, *args):
    return command(["git", "-c", "core.hooksPath=/dev/null", "-C", repo, *args], repo, git_env())


def tree(repo, ref, paths=None, links=False):
    """Blob entries only. With links, also mode 120000, for later alias review."""
    entries = {}
    args = ["ls-tree", "-rz", ref]+(["--", *paths] if paths is not None else [])
    for row in git(repo, *args).split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        mode, kind, oid = meta.split()
        path = path.decode("utf-8")
        safe_path(path)
        require(kind == b"blob" and mode in ((b"100644", b"100755", b"120000") if links else (b"100644", b"100755")),
                "symlink or submodule refused")
        entries[path] = (mode.decode(), oid.decode())
    return entries


def alias(path, target, paths):
    """Approved harness links: .agents or .claude skills/<name> -> ../../skills/<name>.

    The raw link bytes are compared, never dereferenced, so absolute, escaping,
    cyclic and differently spelt targets all refuse."""
    match = ALIAS.fullmatch(path)
    require(match is not None, "link: only approved .agents/skills or .claude/skills aliases may be links")
    require(target == ("../../skills/"+match[1]).encode(), f"link: {path} must point to ../../skills/{match[1]}")
    require(any(p.startswith("skills/"+match[1]+"/") for p in paths), f"link: dangling alias {path}")


def refuse_ranges(text):
    """A combined release has one entry per version: no ## A–B heading anywhere."""
    require(not any(re.match(r"[ ]{0,3}##[ \t]+\[?[0-9]+\.[0-9]+\.[0-9]+\]?\s*[–—-]\s*\[?[0-9]+\.[0-9]+\.[0-9]+", h.group())
                    for h in re.finditer(r"^[ ]{0,3}##[ \t].*$", text, re.M)),
            "combined version-range changelog heading refused")


def changelog_entry(text, version):
    """The one dated single-version entry for version, exactly as published."""
    headers = list(re.finditer(r"^## .+$", text, re.M))
    refuse_ranges(text)
    pattern = re.compile(r"## (?:"+re.escape(version)+r"|\["+re.escape(version)
                         +r"\]) (?:·|—|-) (\d{4}-\d{2}-\d{2})")
    matches = [(i, pattern.fullmatch(h.group())) for i, h in enumerate(headers)
               if pattern.fullmatch(h.group())]
    require(len(matches) == 1, "one dated checked changelog entry is required")
    index, match = matches[0]
    datetime.date.fromisoformat(match[1])
    end = headers[index+1].start() if index+1 < len(headers) else len(text)
    entry = text[headers[index].start():end].rstrip()+"\n"
    require(entry.count("\n") > 2, "empty checked changelog entry")
    return headers[index].group(), entry


def blob(repo, ref, path):
    return git(repo, "show", f"{ref}:{path}")


def load_plan(path, version):
    data = json.loads(path.read_text(), object_pairs_hook=unique)
    require(isinstance(data,dict), "plan must be an object")
    required = "schema version public_base identity files claim_reviews live_pending"
    require(not ("entry" in data and "historical" in data),
            "unexpected manifest shape: entry and historical are exclusive")
    shape(data,required+"".join(" "+k for k in ("scan_exceptions","entry","historical","evidence_documents",
                                                "regressions") if k in data))
    successors = data.get("regressions",[])
    require(isinstance(successors,list),"regression successors must be an array")
    from scans import REGRESSIONS
    defaults = {name:tests for name,_,_,tests in REGRESSIONS}
    for successor in successors:
        shape(successor,"id proof tests")
        require(successor["id"] in defaults,"unknown regression id")
        require(defaults[successor["id"]],"regression successor: browser proofs have no successor form")
        require(isinstance(successor["proof"],str)
                and re.fullmatch(r"tests/[a-z0-9-]+/[a-z0-9_]+\.rs",successor["proof"]),
                "regression successor: proof must be a public Rust test file")
        require(isinstance(successor["tests"],list) and successor["tests"]
                and all(isinstance(t,str) and re.fullmatch(r"[a-z][a-z0-9_]*",t) for t in successor["tests"])
                and len(set(successor["tests"])) == len(successor["tests"]),
                "regression successor: tests must be named Rust tests, each once")
    require(len({s["id"] for s in successors}) == len(successors),"duplicate regression successor")
    historical = "historical" in data
    if historical:
        shape(data["historical"],"export_head changelog_heading entry_sha256")
        require(isinstance(data["historical"]["export_head"],str)
                and re.fullmatch(r"[0-9a-f]{40}",data["historical"]["export_head"]),
                "historical head must be a full commit")
        require(isinstance(data["historical"]["changelog_heading"],str)
                and re.fullmatch(r"## "+re.escape(version)+r" · [0-9]{4}-[0-9]{2}-[0-9]{2}",
                                 data["historical"]["changelog_heading"]) is not None,
                "approved changelog entry: heading must be this version's dated heading")
        datetime.date.fromisoformat(data["historical"]["changelog_heading"][-10:])
        require(isinstance(data["historical"]["entry_sha256"],str)
                and re.fullmatch(r"[0-9a-f]{64}",data["historical"]["entry_sha256"]),
                "approved changelog entry: invalid hash")
    documents = data.get("evidence_documents",[])
    require(isinstance(documents,list),"evidence documents must be an array")
    for document in documents:
        shape(document,"path sha256 status label")
        public_path(document["path"])
        require(document["path"].endswith(".md") and document["status"] == "live-observation"
                and isinstance(document["label"],str) and document["label"].strip()
                and isinstance(document["sha256"],str) and re.fullmatch(r"[0-9a-f]{64}",document["sha256"]),
                "invalid evidence document")
    require(len({d["path"] for d in documents}) == len(documents),"duplicate evidence document")
    if "entry" in data:
        from entry import entries
        entries(data["entry"],version)
    exceptions = data.get("scan_exceptions",[])
    require(isinstance(exceptions,list),"scan exceptions must be an array")
    for exception in exceptions:
        shape(exception,"path sha256 rule value")
        public_path(exception["path"],product=True)
        require(all(isinstance(exception[k],str) and exception[k] for k in ("sha256","rule","value")),
                "invalid scan exception")
    require(data["schema"] == "openwiz.release-plan.v1" and data["version"] == version, "plan version mismatch")
    require(isinstance(data["public_base"], str) and re.fullmatch(r"[0-9a-f]{40}", data["public_base"]), "public base must be a full commit")
    shape(data["identity"], "name email")
    require(isinstance(data["identity"]["name"], str) and re.fullmatch(r"[A-Za-z .-]+", data["identity"]["name"]), "unsafe commit name")
    require(isinstance(data["identity"]["email"], str) and re.fullmatch(r"[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com", data["identity"]["email"]), "no-reply author and committer required")
    require(type(data["live_pending"]) is int and data["live_pending"] >= 0, "invalid placeholder count")
    require(isinstance(data["files"], list) and data["files"], "empty allowlist")
    seen = set()
    for item in data["files"]:
        shape(item, "path source sha256"+(" mode" if "mode" in item else ""))
        if historical:
            require("mode" in item, "historical rows need their approved mode")
            require(item["source"] == item["path"], "historical rows name their published path")
        require(item.get("mode","100644") in MODES, "invalid file mode")
        if item.get("mode") == "120000":
            require(ALIAS.fullmatch(item["path"]) and item["source"] == item["path"],
                    "link: only approved .agents/skills or .claude/skills aliases may be links")
        if ALIAS.fullmatch(item["path"]):
            require(item.get("mode") == "120000", "link: an .agents/skills alias row needs mode 120000")
        path = public_path(item["path"],product=True)
        if tuple(map(int,version.split("."))) < (0,0,4):
            require(not re.search(r"(?:^|/)(?:new_thread|new-thread|attachments)(?:/|\.)|/(?:attachment|prompt)\.rs$|contracts/(?:attachment|prompt)\.",path),
                    "later-version code in an early release")
        if tuple(map(int,version.split("."))) < (0,0,3):
            require("/messaging/" not in path and not path.endswith("/messaging.rs"),
                    "later-version messaging code in a read-only release")
        safe_path(item["source"])
        require(item["source"] == path or ("entry" in data and path in {"CHANGELOG.md", "ROADMAP.md"}
                and item["source"] == "generated/"+path),
                "release rows must name their own tracked path")
        require(path not in seen, "duplicate destination")
        require(not any(path.startswith(p+"/") or p.startswith(path+"/") for p in seen), "overlapping destinations")
        require(isinstance(item["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "invalid file hash")
        seen.add(path)
    if "entry" in data:
        from entry import GENERATED
        for path in GENERATED:
            require(any(f["path"] == path and f["source"] == "generated/"+path for f in data["files"]),
                    f"entry: generated {path} needs its approved allowlist row")
    return data


class Check:
    def __init__(self, args):
        self.args = args
        self.report = {"schema":"openwiz.release-check.v1", "version":args.version, "status":"fail",
                       "checks":[], "files":[], "gaps":["Semantic completeness of the claim ledger requires independent export review.",
                                                          "No live behaviour, publication approval or remote read-back is proved."]}

    def step(self, name, action):
        try:
            result = action()
        except (Refused, OSError, ValueError, KeyError, UnicodeError) as error:
            self.report["checks"].append({"id":name,"status":"fail","reason":str(error)})
            raise Refused(f"{name}: {error}") from error
        self.report["checks"].append({"id":name,"status":"pass"})
        return result

    def prepare(self):
        a = self.args
        require(a.literals is not None, "named-terms input is required (--literals PATH)")
        try:
            a.literals = a.literals.resolve(strict=True)
            self.literals = a.literals.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, UnicodeError, RuntimeError):
            raise Refused("named-terms input must be a readable UTF-8 file") from None
        require(self.literals and all(term.strip() and "\0" not in term for term in self.literals),
                "named-terms input must contain nonblank terms, one per line, without NUL")
        if a.historical:
            require(a.public_repo is not None, "historical check needs --public-repo")
            a.public_repo = a.public_repo.resolve(strict=True)
            a.repo = a.public_repo
        else:
            a.repo = a.repo.resolve(strict=True)
            require(a.public_repo is None or a.public_repo.resolve(strict=True) == a.repo,
                    "separate source-to-public export has retired; use one public release clone")
            a.public_repo = a.repo
        a.plan = a.plan.resolve(strict=True)
        for p in (a.staging, a.evidence):
            require(not p.exists() and not p.is_symlink(), "output directory already exists")
            require(p.is_absolute() and p.parent.exists(), "output parent must exist")
            require(p == p.resolve(), "output path crosses a symlink")
            require(not p.is_relative_to(a.repo) and not p.is_relative_to(a.public_repo), "output overlaps input repository")
        require(not a.staging.is_relative_to(a.evidence) and not a.evidence.is_relative_to(a.staging), "overlapping outputs")
        a.staging.mkdir(mode=0o700)
        a.evidence.mkdir(mode=0o700)
        self.export = a.staging/"export"
        self.fresh = a.staging/"fresh"

    def open_privacy(self, repo=None, head=None, log="open-development-privacy.log"):
        """O3's command scans the entire immutable release tree, not plan rows.

        The approved O3 root/anchor policy checks all newly reachable commit
        trees, messages and identities, including material deleted at the tip.
        PR text stays with CI. The operator supplies the approved private
        named-terms file; a whole private checkout is unnecessary.
        """
        repo = repo or self.args.repo
        head = head or self.args.historical or git(repo,"rev-parse","HEAD").decode().strip()
        # Only persist O3's redacted finding records and required-input receipt.
        # Python startup errors and tracebacks can reveal private tool paths.
        file_place = r'(?:tree|staged|commit-tree-[1-9][0-9]*):"(?:[^"\\\x00-\x1f]|\\(?:["\\bfnrt/]|u[0-9a-fA-F]{4}))*"(?:-path)?'
        place = rf'(?:{file_place}|history|literals|input|tree|title|body|pr-(?:title|body)|commit-[1-9][0-9]*(?:-(?:author|committer))?)'
        finding = rf'(?:T[123]|F[12]|C[123]|READ) {place}:[1-9][0-9]*\n'
        diagnostics = b"READ privacy-checker:1\n"
        passed = False
        try:
            result = subprocess.run([str(arg) for arg in (
                sys.executable, Path(__file__).resolve().parents[1]/"privacy-check/check.py",
                "--repo",repo,"--git-tree",head,"--head",head,
                "--literals",self.args.literals,"--require-literals")],
                cwd=repo,env=git_env(),stdin=subprocess.DEVNULL,capture_output=True,timeout=60)
            text = result.stdout.decode("ascii")
            if (not result.stderr and re.fullmatch(rf'(?:{finding})*literals: used\n',text)
                    and ((result.returncode == 0 and text == "literals: used\n")
                         or (result.returncode == 1 and text != "literals: used\n"))):
                diagnostics = result.stdout
                passed = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            pass  # Keep the fixed refusal; never persist raw exception/output text.
        (self.args.evidence/log).write_bytes(diagnostics)
        require(passed,"privacy checker failed")

    def privacy(self):
        from scans import scan
        scan(self)
        self.open_privacy(self.export,self.report["export_head"],"staged-privacy.log")

    def stage(self):
        a = self.args
        plan = self.plan
        branch = "release-"+a.version
        require(git(a.repo,"branch","--show-current").decode().strip() == branch, "run from the version's release branch")
        require(not git(a.repo,"status","--porcelain"), "release branch must be clean")
        source = git(a.repo,"rev-parse","HEAD").decode().strip()
        require(git(a.repo,"rev-parse","refs/heads/main").decode().strip() == plan["public_base"], "public base moved")
        git(a.repo,"merge-base","--is-ancestor",plan["public_base"],source)
        sources = tree(a.repo,source,links=True)
        base_files = tree(a.repo,plan["public_base"],links=True)
        self.generated = {}
        if "entry" in plan:
            from entry import generate
            self.generated = generate(self,source,base_files)
            for path,content in self.generated.items():
                dest = a.staging/"generated"/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(content)
        self.retain_license(base_files)
        paths = {item["path"] for item in plan["files"]}
        require(set(sources) | set(self.generated) == paths, "allowlist does not equal release tree")
        command(["git","-c","core.hooksPath=/dev/null","clone","--no-local","--no-checkout",
                 a.repo,self.export],a.staging,git_env())
        from repository import repository, remote_url
        git(self.export,"remote","set-url","origin",remote_url(repository(a.repo)))
        git(self.export,"checkout","-b","export/openwiz-"+a.version,source)
        for item in plan["files"]:
            path = item["path"]
            content = self.generated[path] if path in self.generated else blob(a.repo,source,path)
            mode = "100644" if path in self.generated else sources[path][0]
            require((mode == "120000") == (item.get("mode") == "120000"),
                    "symlink refused: mode 120000 needs its own approved alias row")
            require(sha(content) == item["sha256"],
                    f'allowlisted source hash differs: {path} (actual SHA-256: {sha(content)})')
            require(item.get("mode",mode) == mode, "allowlisted source mode differs")
            if mode == "120000":
                alias(path,content,paths)
            if path in self.generated:
                dest = self.export/path
                require(not dest.is_symlink(),"generated file cannot replace a symlink")
                dest.write_bytes(content)
                dest.chmod(0o644)
            self.report["files"].append({"path":path,"sha256":sha(content),"mode":mode})
        git(self.export,"add","--all")
        if self.generated:
            env = git_env()
            for who in ("AUTHOR","COMMITTER"):
                env[f"GIT_{who}_NAME"] = plan["identity"]["name"]
                env[f"GIT_{who}_EMAIL"] = plan["identity"]["email"]
            command(["git","-c","core.hooksPath=/dev/null","-c","commit.gpgsign=false","commit",
                     "-m",f"OpenWiz {a.version} release entry"],self.export,env)
        head = git(self.export,"rev-parse","HEAD").decode().strip()
        checked_tree = git(self.export,"write-tree").decode().strip()
        committed = tree(self.export,checked_tree,links=True)
        require(set(committed) == paths,"allowlist does not equal export tree")
        for item in self.report["files"]:
            require(sha(blob(self.export,checked_tree,item["path"])) == item["sha256"],"committed export hash differs")
            require(committed[item["path"]][0] == item["mode"],"committed export mode differs")
        self.report.update(source_head=source,public_base=plan["public_base"],export_head=head,
                           export_tree=git(self.export,"rev-parse","HEAD^{tree}").decode().strip(),
                           plan_sha256=sha(a.plan.read_bytes()))

    def retain_license(self, base_files):
        a = self.args
        plan = self.plan
        if "LICENSE" in base_files:
            license_item = next((f for f in plan["files"] if f["path"] == "LICENSE"),None)
            require(license_item and license_item["sha256"] == sha(blob(a.public_repo,plan["public_base"],"LICENSE")),
                    "public license must be retained unmodified")

    def stage_historical(self):
        """Bind an exact, already-published public commit; write nothing public.

        The published commit is its own source: every approved row names its
        published path, mode and hash, and nothing is restaged over it."""
        a = self.args
        plan = self.plan
        head = plan["historical"]["export_head"]
        require(a.historical == head, "historical commit differs from the approved plan")
        main = git(a.public_repo,"rev-parse","--verify","refs/heads/main^{commit}").decode().strip()
        try:
            git(a.public_repo,"merge-base","--is-ancestor",head,main)
        except Refused as error:
            raise Refused("historical commit is not reachable from public main") from error
        try:
            git(a.public_repo,"merge-base","--is-ancestor",plan["public_base"],head)
        except Refused as error:
            raise Refused("public base must be an ancestor of the historical commit") from error
        tag = "refs/tags/v"+a.version
        require(not git(a.public_repo,"for-each-ref",tag), "tag already exists for this version")
        self.retain_license(tree(a.public_repo,plan["public_base"],links=True))
        command(["git","-c","core.hooksPath=/dev/null","clone","--no-local","--no-checkout","--single-branch",
                 "--branch","main",a.public_repo,self.export],a.staging,git_env())
        from repository import repository, remote_url
        git(self.export,"remote","set-url","origin",remote_url(repository(a.public_repo)))
        git(self.export,"checkout","-q","-b","historical/openwiz-"+a.version,head)
        require(git(self.export,"rev-parse","HEAD").decode().strip() == head, "historical checkout differs")
        committed = tree(self.export,head,links=True)
        paths = {i["path"] for i in plan["files"]}
        require(set(committed) == paths, "allowlist does not equal export tree")
        for item in plan["files"]:
            content = blob(self.export,head,item["path"])
            mode = committed[item["path"]][0]
            require(sha(content) == item["sha256"], "published file hash differs from the approved plan")
            require(mode == item["mode"], "published file mode differs from the approved plan")
            if mode == "120000":
                alias(item["path"],content,paths)
            self.report["files"].append({"path":item["path"],"sha256":sha(content),"mode":mode})
        self.report.update(source_head=head,public_base=plan["public_base"],export_head=head,
                           export_tree=git(self.export,"rev-parse","HEAD^{tree}").decode().strip(),
                           plan_sha256=sha(a.plan.read_bytes()),historical={"public_main":main})

    def build(self):
        command(["git","-c","core.hooksPath=/dev/null","clone","--no-local","--single-branch",self.export,self.fresh],self.args.staging,git_env())
        require(git(self.fresh,"rev-parse","HEAD").decode().strip() == self.report["export_head"], "fresh clone head differs")
        env = git_env()
        home = self.args.staging/"home"
        home.mkdir()
        env.update(HOME=str(home),CARGO_HOME=str(home/"cargo"),CARGO_TARGET_DIR=str(self.args.staging/"target"),
                   RUSTUP_HOME=os.environ.get("RUSTUP_HOME",str(Path.home()/".rustup")),
                   TMPDIR=str(home/"tmp"),XDG_CACHE_HOME=str(home/"cache"),
                   npm_config_cache=str(home/"npm"),CARGO_BUILD_JOBS="2",CIRCLE_NODE_TOTAL="2",
                   NEXT_TELEMETRY_DISABLED="1",OPENWIZ_STATE_DIR=str(home/"state"))
        (home/"tmp").mkdir()
        require((self.fresh/"Cargo.toml").is_file() and (self.fresh/"Cargo.lock").is_file(), "Rust workspace and lock required")
        tasks = []
        if (self.fresh/"apps/web/package.json").exists():
            tasks.extend(("apps/web", ["npm",*cmd]) for cmd in (["ci","--ignore-scripts"],["run","build"],["run","typecheck"],["run","check"]))
        site = any(f["path"].startswith("apps/site/") for f in self.report["files"])
        if site:
            require(all((self.fresh/"apps/site"/name).is_file() for name in ("package.json","build.mjs")),
                    "site build tooling missing")
            tasks.append(("apps/site",["npm","run","build"]))
        tasks.extend((".",["cargo",*cmd]) for cmd in (["build","--workspace","--release","--locked"],
                     ["test","--workspace","--locked"],["fmt","--check"],
                     ["clippy","--workspace","--all-targets","--locked","--","-D","warnings"]))
        if (self.fresh/"apps/web/package.json").exists():
            tasks.append(("apps/web",["npm","test"]))
        if site:
            tasks.append(("apps/site",["npm","test"]))
        for index,(folder,cmd) in enumerate(tasks):
            output = command(cmd,self.fresh/folder,env,log=self.args.evidence/f"build-{index+1:02}.log")
            if cmd[:2] == ["cargo","test"]:
                require(re.search(rb"test result: ok\. [1-9][0-9]* passed",output), "no passing Rust tests observed")
            if folder == "apps/site" and cmd == ["npm","test"]:
                text = output.decode("utf-8")
                counts = re.findall(r"^(?:#|ℹ) tests (\d+)\b",text,re.M)
                passed = re.findall(r"^(?:#|ℹ) pass (\d+)\b",text,re.M)
                failed = re.findall(r"^(?:#|ℹ) fail (\d+)\b",text,re.M)
                # npm test runs the export and browser suites separately.
                require(len(counts) == 2,"site test suites incomplete")
                require(counts and counts == passed and all(int(n) > 0 for n in counts)
                        and failed == ["0"]*len(counts), "no passing site tests observed")
        for name,proof,tests,exact in self.regressions:
            try:
                if exact:
                    # An approved successor runs as its one exact test identity.
                    target = re.fullmatch(r"tests/([a-z0-9-]+)/[^/]+\.rs",proof)[1]
                    for test,identity in zip(tests,exact):
                        self.nonce_run(name,proof,target,test,identity,env)
                        out = command(["cargo","test","--locked","-p","openwiz-tests","--test",target,
                                       "--","--exact",identity],
                                      self.fresh,env,log=self.args.evidence/f"{name}-{identity.replace(':','_')}.log")
                        counts = re.findall(rb"test result: ok\. (\d+) passed",out)
                        require(sum(int(n) for n in counts) == 1,f"{name}: expected exactly one passing regression")
                elif tests:
                    target = re.fullmatch(r"tests/([a-z0-9-]+)/[^/]+\.rs",proof)[1]
                    for test in tests:
                        out = command(["cargo","test","--locked","-p","openwiz-tests","--test",target,test],
                                      self.fresh,env,log=self.args.evidence/f"{name}-{test}.log")
                        counts = re.findall(rb"test result: ok\. (\d+) passed",out)
                        require(sum(int(n) for n in counts) == 1,f"{name}: expected exactly one passing regression")
                else:
                    out = command(["node","--test","--test-reporter=tap",str(self.fresh/proof)],
                                  self.fresh/"apps/web",env,log=self.args.evidence/f"{name}.log")
                    require(re.search(rb"# tests 4\b",out) and re.search(rb"# pass 4\b",out),
                            f"{name}: expected four passing browser regressions")
            except Refused as error:
                raise Refused(f"{name}: {error}") from error
        binary = self.args.staging/"target/release/openwiz"
        output = command([binary,"--help"], self.fresh,env)
        require(output.strip(), "empty help")
        require(not any(line.rstrip(b" \t") != line for line in output.splitlines()), "0.0.3-R5: trailing whitespace in help")
        require(not git(self.fresh,"status","--porcelain","--untracked-files=no"), "fresh clone changed tracked files")

    def nonce_run(self, name, proof, target, test, identity, env):
        """Bind the approved test's body through the compiler (R3, Jake's ruling (a)).

        In a scratch clone of the export, that body becomes a panic with a random
        nonce, and the same --exact identity must fail, printing the nonce. A
        macro, build script or Cargo config that swaps or drops the body cannot
        print it. The scratch clone has its own target directory and is removed."""
        from scans import test_body
        scratch = self.args.staging/"nonce"
        command(["git","-c","core.hooksPath=/dev/null","clone","--no-local","--single-branch",self.export,scratch],
                self.args.staging,git_env())
        try:
            require(git(scratch,"rev-parse","HEAD").decode().strip() == self.report["export_head"],
                    "nonce clone head differs")
            path = scratch/proof
            text = path.read_text()
            start,end = test_body(text,test)
            nonce = secrets.token_hex(16)
            path.write_text(text[:start]+'{ panic!("'+nonce+'"); }'+text[end:])
            try:
                result = subprocess.run(["cargo","test","--locked","-p","openwiz-tests","--test",target,
                                         "--","--exact",identity],
                                        cwd=scratch,env=dict(env,CARGO_TARGET_DIR=str(self.args.staging/"nonce-target")),
                                        stdin=subprocess.DEVNULL,capture_output=True,timeout=1800)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise Refused(f"cannot run cargo: {type(error).__name__}") from error
            out = result.stdout+result.stderr
            (self.args.evidence/f"{name}-{identity.replace(':','_')}-nonce.log").write_bytes(out)
            require(result.returncode != 0 and nonce.encode() in out
                    and re.search(rb"test result: FAILED\. 0 passed; 1 failed;",result.stdout),
                    "approved test body did not run (its nonce panic was not observed)")
        finally:
            shutil.rmtree(scratch,ignore_errors=True)

    def write_report(self):
        a = self.args
        if not a.evidence.is_dir():
            return
        if "publishable" in self.report:
            # Only a passing report can be publishable, whichever step failed.
            self.report["publishable"] = self.report["publishable"] is True and self.report["status"] == "pass"
        files = sorted(self.report["files"],key=lambda i:i["path"])
        self.report["files"] = files
        (a.evidence/"report.json").write_text(json.dumps(self.report,indent=2)+"\n")
        hashes = "".join(f'{f["sha256"]}  {f["path"]}\n' for f in files)
        (a.evidence/"EXPORT-FILES.txt").write_text(hashes)
        checks = "; ".join(f'{s["id"]}: {s["status"]}' for s in self.report["checks"])
        generated = ""
        if hasattr(self, "entry_text"):
            generated = ("## Draft entry\n\n"+self.entry_text+"\n## Public roadmap\n\n"
                         +self.generated["ROADMAP.md"].decode("utf-8")+"\n")
            generated_hashes = "".join(f'{sha(content)}  generated/{path}\n'
                                       for path,content in sorted(self.generated.items()))
            generated += (f'## Generated files in `{a.staging}`\n\n```text\n'
                          +generated_hashes+"```\n\n")
        (a.evidence/"report.md").write_text(f'# OpenWiz {a.version}: release check — {self.report["status"]}\n\n'
            f'Export head: `{self.report.get("export_head","unavailable")}`. Tree: `{self.report.get("export_tree","unavailable")}`.\n\n'
            f'{checks}\n\nNo push, tag or release was requested. Independent export review and publication approval remain required.\n\n'
            f'LIVE-PENDING occurrences: {self.report.get("live_pending","not checked")}.\n\n'
            f'{generated}<details><summary>SHA-256: {len(files)} files</summary>\n\n```text\n{hashes}```\n\n</details>\n')

    def load(self):
        a = self.args
        if a.historical:
            # Historical verification uses only the exact plan bytes Jake approved.
            require(a.approved_plan_sha256 is not None and sha(a.plan.read_bytes()) == a.approved_plan_sha256,
                    "historical verification needs the approved plan's exact SHA-256")
        plan = load_plan(a.plan,a.version)
        require(("historical" in plan) == bool(a.historical),
                "historical verification needs --historical and a historical plan, together")
        return plan

    def run(self):
        self.prepare()
        try:
            self.plan = self.step("plan",self.load)
            self.step("open-development-privacy",self.open_privacy)
            self.step("stage",self.stage_historical if self.args.historical else self.stage)
            from scans import historical_text, links, claims, regression_presence
            self.step("privacy",self.privacy)
            self.step("historical-text",lambda:historical_text(self))
            self.step("links",lambda:links(self))
            self.step("claims",lambda:claims(self))
            self.step("regression-proofs",lambda:regression_presence(self))
            self.step("fresh-clone",self.build)
            self.report["status"] = "pass"
        finally:
            self.write_report()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    check = sub.add_parser("check",help="stage and check; never push, tag or publish")
    check.add_argument("version")
    check.add_argument("--public-repo",type=Path,help="public clone for historical verification only")
    for option in ("plan","staging","evidence"):
        check.add_argument("--"+option,type=Path,required=True)
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo",type=Path,help="clean release-VERSION checkout to stage from")
    source.add_argument("--historical",metavar="COMMIT",
                        help="verify this exact published public commit instead of staging")
    check.add_argument("--literals",type=Path,
                       help="required private named-terms file from the approved O3 source")
    check.add_argument("--approved-plan-sha256",metavar="SHA256",
                       help="with --historical: SHA-256 of the exact approved plan bytes")
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",args.version), "version must be N.N.N")
        require(args.historical is None or re.fullmatch(r"[0-9a-f]{40}",args.historical),
                "historical commit must be a full commit")
        require(args.historical is not None or args.approved_plan_sha256 is None,
                "--approved-plan-sha256 is for --historical")
        Check(args).run()
    except (Refused,OSError,ValueError) as error:
        print(f"release check refused: {error}",file=sys.stderr)
        return 1
    print("release check passed; report.md is in the evidence directory")
    return 0
