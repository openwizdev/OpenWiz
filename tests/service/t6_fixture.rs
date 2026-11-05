#![allow(dead_code)]
use openwiz_service::{
    state::State,
    update::{self, Call, Executor, System},
};
use serde_json::Value;
use std::{
    fs::{self, DirBuilder, OpenOptions},
    io::Write,
    os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Output},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../..");
fn output(command: &mut Command) -> Output {
    command.output().unwrap()
}
// A separate `cp` writes the executable (#2700), so concurrent forks in this
// multithreaded parent, including System executors and direct test commands,
// cannot inherit a writable descriptor for it.
fn executable(path: &Path, program: &[u8]) {
    place_script(path, program);
}
pub fn directory(path: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
pub fn file(path: &Path, value: impl AsRef<[u8]>) {
    fs::write(path, value).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
fn copy_tree(source: &Path, destination: &Path) {
    directory(destination);
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &destination.join(entry.file_name()));
        } else {
            file(
                &destination.join(entry.file_name()),
                fs::read(entry.path()).unwrap(),
            );
        }
    }
}
fn copy_product(repo: &Path) {
    for name in [
        "core",
        "store",
        "server",
        "cli",
        "adapters/cloudroom",
        "adapters/github",
        "service",
        "terminal",
    ] {
        let source = Path::new(ROOT).join("crates").join(name);
        let destination = repo.join("product/crates").join(name);
        copy_tree(&source.join("src"), &destination.join("src"));
        let manifest = fs::read_to_string(source.join("Cargo.toml")).unwrap();
        let mut result = String::new();
        let mut skip = false;
        for line in manifest.lines() {
            if line.starts_with('[') {
                skip = matches!(line, "[[test]]" | "[[example]]");
            }
            if !skip {
                result.push_str(line);
                result.push('\n');
                if name == "service" && line == "[package]" {
                    result.push_str("autobins = false\nautoexamples = false\nautotests = false\n");
                }
            }
        }
        file(&destination.join("Cargo.toml"), result);
        if source.join("build.rs").is_file() {
            file(
                &destination.join("build.rs"),
                fs::read(source.join("build.rs")).unwrap(),
            );
        }
    }
    directory(&repo.join("product/tools/install/platform"));
    file(
        &repo.join("product/tools/install/platform/security.py"),
        include_bytes!("../../tools/install/platform/security.py"),
    );
    directory(&repo.join("product/tests/support"));
    file(
        &repo.join("product/tests/support/cloudroom_process_tests.rs"),
        include_bytes!("../support/cloudroom_process_tests.rs"),
    );
    directory(&repo.join("product/tests/service"));
    file(
        &repo.join("product/tests/service/t7_transport.rs"),
        include_bytes!("t7_transport.rs"),
    );
    for (name, bytes) in [
        (
            "install_engine_record_factory.rs",
            include_bytes!("install_engine_record_factory.rs").as_slice(),
        ),
        (
            "install_engine_app_support.rs",
            include_bytes!("install_engine_app_support.rs").as_slice(),
        ),
        (
            "install_engine_target.rs",
            include_bytes!("install_engine_target.rs").as_slice(),
        ),
    ] {
        file(&repo.join("product/tests/service").join(name), bytes);
    }
    directory(&repo.join("product/contracts"));
    file(
        &repo.join("product/contracts/service.v1.md"),
        include_bytes!("../../contracts/service.v1.md"),
    );
    file(
        &repo.join("product/contracts/service.v1.schema.json"),
        include_bytes!("../../contracts/service.v1.schema.json"),
    );
    file(
        &repo.join("product/contracts/loops.v1.schema.json"),
        include_bytes!("../../contracts/loops.v1.schema.json"),
    );
    file(
        &repo.join("product/contracts/cli.v1.schema.json"),
        include_bytes!("../../contracts/cli.v1.schema.json"),
    );
}
pub struct Recording {
    pub calls: Mutex<Vec<String>>,
    pub loose_modes: std::sync::atomic::AtomicBool,
}
impl Executor for Recording {
    fn run(&self, call: &Call) -> Result<String, String> {
        self.calls.lock().unwrap().push(format!(
            "{} {}",
            call.program().display(),
            call.argv().join(" ")
        ));
        // The Rust CI job has no Node/npm on PATH. Its synthetic web gate is
        // a recording fake; Git, Cargo and the compiled service stay real.
        if call.program() == Path::new("npm") {
            let args: Vec<_> = call.argv().iter().map(String::as_str).collect();
            match args.as_slice() {
                ["run", "build"] => {
                    directory(&call.directory().join("out"));
                    file(
                        &call.directory().join("out/index.html"),
                        "<html>synthetic candidate</html>",
                    );
                }
                ["ci", "--ignore-scripts"] | ["run", "typecheck"] | ["run", "check"] | ["test"] => {
                }
                _ => return Err("unrecognized synthetic npm call".to_owned()),
            }
            return Ok(String::new());
        }
        let result = System.run(call).inspect_err(|_| {
            eprintln!(
                "fixture command failed: {} {:?}",
                call.program().display(),
                call.argv()
            )
        });
        if self.loose_modes.load(Ordering::SeqCst) && call.program() == Path::new("git") {
            for (name, mode) in [("objects", 0o755), ("config", 0o644)] {
                let path = call.directory().join(name);
                if path.exists() {
                    fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
                }
            }
        }
        result
    }
}
pub struct Fixture {
    pub temp: PathBuf,
    pub root: PathBuf,
    pub repo: PathBuf,
    pub install: PathBuf,
    pub executor: Arc<Recording>,
}
impl Fixture {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let temp = std::env::temp_dir().join(format!(
            "ow-t6-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let root = temp.join("state");
        let repo = temp.join("repository");
        let install = temp.join("home/.local/lib/openwiz");
        for p in [
            &root.join("service"),
            &repo.join("src"),
            &repo.join("proof/tests"),
            &repo.join("apps/web"),
            &repo.join(".github/actions/docs-only"),
            &install,
        ] {
            directory(p);
        }
        let mut config: Value = include_str!("../../contracts/service.v1.md")
            .lines()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .find(|v| v["schema"] == "openwiz.service-config.v1")
            .unwrap();
        config["server"]["allowed_host"] = Value::Null;
        // The fixture program binds port zero itself and transfers that live
        // listener. This configured value is used only by explicit bind-failure
        // proofs; normal HTTP clients read the actual port from runtime status.
        file(&root.join("service/config.json"), config.to_string());
        file(
            &repo.join("Cargo.toml"),
            "[workspace]\nmembers = [\"proof\"]\n[workspace.package]\nversion = \"0.0.1-dev\"\nedition = \"2024\"\nrust-version = \"1.99.1\"\npublish = false\n[workspace.dependencies]\nserde = { version = \"1\", features = [\"derive\"] }\nserde_json = \"1\"\n[workspace.lints.rust]\nunsafe_code = \"forbid\"\n[package]\nname = \"synthetic-service\"\nversion = \"0.0.0\"\nedition = \"2024\"\n[[bin]]\nname = \"openwiz-service\"\npath = \"src/main.rs\"\n[dependencies]\nservice = { package = \"openwiz-service\", path = \"product/crates/service\" }\nadapter = { package = \"openwiz-adapter-cloudroom\", path = \"product/crates/adapters/cloudroom\" }\n",
        );
        copy_product(&repo);
        file(&repo.join("src/main.rs"), include_str!("t6_program.rs"));
        file(
            &repo.join(".gitignore"),
            "/target/\n/apps/web/out/\n/apps/web/node_modules/\n",
        );
        file(&repo.join("src/mode"), "pass");
        file(
            &repo.join("proof/Cargo.toml"),
            "[package]\nname = \"openwiz-tests\"\nversion = \"0.0.0\"\nedition = \"2024\"\n",
        );
        directory(&repo.join("proof/src"));
        file(
            &repo.join("proof/src/lib.rs"),
            "//! Synthetic proof package.\n",
        );
        file(
            &repo.join("proof/tests/checks.rs"),
            "#[test]\nfn pending() { assert_eq!(include_str!(\"../verdict\"), \"pass\"); }\n",
        );
        file(&repo.join("proof/verdict"), "pass");
        file(&repo.join(".github/actions/docs-only/test.sh"), "exit 0\n");
        file(
            &repo.join("apps/web/package.json"),
            r#"{"name":"synthetic-web","version":"0.0.0","scripts":{"build":"node build.mjs","typecheck":"node -e ''","check":"node -e ''","test":"node -e ''"}}"#,
        );
        file(
            &repo.join("apps/web/package-lock.json"),
            r#"{"name":"synthetic-web","version":"0.0.0","lockfileVersion":3,"packages":{"":{"name":"synthetic-web","version":"0.0.0"}}}"#,
        );
        file(
            &repo.join("apps/web/build.mjs"),
            "import fs from 'node:fs'; const temporary = fs.mkdtempSync('synthetic-web-'); fs.chmodSync(temporary, 0o700); fs.writeFileSync(`${temporary}/index.html`, '<html>synthetic candidate</html>', { mode: 0o600 }); fs.rmSync('out', { recursive: true, force: true }); fs.renameSync(temporary, 'out');\n",
        );
        let f = Self {
            temp,
            root,
            repo,
            install,
            executor: Arc::new(Recording {
                calls: Mutex::new(vec![]),
                loose_modes: std::sync::atomic::AtomicBool::new(false),
            }),
        };
        let formatted = output(
            Command::new("rustfmt")
                .args(["--edition", "2024"])
                .arg(f.repo.join("src/main.rs"))
                .arg(f.repo.join("proof/tests/checks.rs")),
        );
        assert!(formatted.status.success(), "fixture source must format");
        f.git(&["init", "-q", "-b", "main"]);
        f.git(&["config", "user.name", "Synthetic Owner"]);
        f.git(&["config", "user.email", "synthetic@example.invalid"]);
        f.git(&["add", "."]);
        f.git(&["commit", "-qm", "synthetic initial"]);
        let old = f.head();
        directory(&f.build(&old).join("web"));
        executable(
            &f.build(&old).join("openwiz-service"),
            b"#!/bin/sh\nexit 1\n",
        );
        file(
            &f.build(&old).join("web/index.html"),
            "<html>synthetic old page</html>",
        );
        std::os::unix::fs::symlink(f.build(&old), f.install.join("current")).unwrap();
        f
    }
    pub fn git(&self, args: &[&str]) -> String {
        // Fixed dates make each synthetic commit the same in every fixture,
        // so one compiled program per commit serves the whole binary.
        let result = output(
            Command::new("git")
                .args(args)
                .env("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
                .env("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")
                .current_dir(&self.repo),
        );
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        String::from_utf8(result.stdout).unwrap().trim().to_owned()
    }
    pub fn head(&self) -> String {
        self.git(&["rev-parse", "HEAD"])
    }
    /// The real release program of this repository's clean HEAD, with build
    /// identity `identity` (#1253). Each pair is compiled once per test
    /// binary, then copied. The compile runs in one fixed workspace under
    /// Cargo's target tmp dir, locked across processes: a checkout rewrites
    /// only changed files, so Cargo's own freshness check rebuilds only what
    /// changed since the last compile there, in this run or an earlier one.
    fn compiled(&self, identity: &str) -> Arc<Vec<u8>> {
        type Cell = Arc<std::sync::OnceLock<Arc<Vec<u8>>>>;
        static BUILT: Mutex<Vec<(String, String, Cell)>> = Mutex::new(Vec::new());
        assert!(
            self.git(&["status", "--porcelain", "--untracked-files=no"])
                .is_empty(),
            "only a committed tree can be compiled once and shared"
        );
        let head = self.head();
        let cell = {
            let mut built = BUILT.lock().unwrap_or_else(|e| e.into_inner());
            match built.iter().find(|(h, i, _)| *h == head && i == identity) {
                Some((_, _, cell)) => Arc::clone(cell),
                None => {
                    let cell = Cell::default();
                    built.push((head.clone(), identity.to_owned(), Arc::clone(&cell)));
                    cell
                }
            }
        };
        Arc::clone(cell.get_or_init(|| {
            let work = Path::new(env!("CARGO_TARGET_TMPDIR")).join("t6-update-programs");
            directory(&work);
            let lock = OpenOptions::new()
                .create(true)
                .truncate(false)
                .write(true)
                .mode(0o600)
                .open(work.join("lock"))
                .unwrap();
            lock.lock().unwrap();
            let tree = work.join("source");
            let git = |args: &[&str]| {
                let out = output(Command::new("git").args(args).current_dir(&tree));
                assert!(
                    out.status.success(),
                    "{}",
                    String::from_utf8_lossy(&out.stderr)
                );
                String::from_utf8(out.stdout).unwrap().trim().to_owned()
            };
            if !tree.join(".git").is_dir() {
                directory(&tree);
                git(&["init", "-q"]);
            }
            git(&[
                "fetch",
                "-q",
                "--no-tags",
                self.repo.to_str().unwrap(),
                &head,
            ]);
            git(&["checkout", "-q", "--force", "--detach", &head]);
            // Only the commit is compiled: drop anything untracked, but keep
            // the lock file Cargo wrote, so a warm build needs no index.
            git(&["clean", "-q", "-f", "-d", "-x", "-e", "/Cargo.lock"]);
            assert_eq!(git(&["rev-parse", "HEAD"]), head);
            let left = git(&["status", "--porcelain"]);
            assert!(left.is_empty() || left == "?? Cargo.lock", "{left}");
            let out = output(
                Command::new(env!("CARGO"))
                    .args(["build", "--release", "--target-dir"])
                    .arg(work.join("target"))
                    .env("OPENWIZ_SERVICE_BUILD", identity)
                    .env("CARGO_BUILD_JOBS", "2")
                    .current_dir(&tree),
            );
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
            Arc::new(fs::read(work.join("target/release/openwiz-service")).unwrap())
        }))
    }
    pub fn install_old(&self, old: &str) {
        let program = self.compiled(old);
        directory(&self.build(old).join("web"));
        executable(&self.build(old).join("openwiz-service"), &program);
        file(
            &self.build(old).join("web/index.html"),
            "<html>synthetic old page</html>",
        );
        assert_eq!(
            fs::read_link(self.install.join("current")).unwrap(),
            self.build(old)
        );
    }
    pub fn start(&self) -> Running {
        let diagnostics = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(self.temp.join("process.log"))
            .unwrap();
        Running(
            Command::new(self.install.join("current/openwiz-service"))
                .env("OPENWIZ_STATE_DIR", &self.root)
                .env("HOME", self.temp.join("home"))
                .current_dir(&self.repo)
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(diagnostics)
                .spawn()
                .unwrap(),
        )
    }
    /// Keep a conflicting address owned while exercising startup or recovery.
    pub fn occupy_configured_port(&self) -> std::net::TcpListener {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let path = self.root.join("service/config.json");
        let mut config: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        config["server"]["port"] = serde_json::json!(listener.local_addr().unwrap().port());
        file(&path, config.to_string());
        listener
    }
    pub fn status(&self) -> Value {
        let until = std::time::Instant::now() + std::time::Duration::from_secs(15);
        loop {
            if let Ok(status) = openwiz_service::runtime::status(&self.root) {
                return status;
            }
            assert!(
                std::time::Instant::now() < until,
                "service never ready: {}",
                fs::read_to_string(self.temp.join("process.log")).unwrap_or_default()
            );
            std::thread::park_timeout(std::time::Duration::from_millis(10));
        }
    }
    pub fn reject_inbound_update(&self) {
        use std::io::{Read, Write};
        let port = self.status()["server"]["port"].as_u64().unwrap() as u16;
        for (method, status) in [("GET", "404 Not Found"), ("POST", "405 Method Not Allowed")] {
            let mut connection = std::net::TcpStream::connect(("127.0.0.1", port)).unwrap();
            connection
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            write!(connection, "{method} /api/v1/update HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").unwrap();
            let mut response = String::new();
            connection.read_to_string(&mut response).unwrap();
            assert!(
                response.starts_with(&format!("HTTP/1.1 {status}\r\n")),
                "{response}"
            );
        }
    }
    pub fn only_existing_http_listener(&self, running: &Running) {
        let pid = running.0.id();
        let sockets: std::collections::BTreeSet<_> = fs::read_dir(format!("/proc/{pid}/fd"))
            .unwrap()
            .filter_map(|entry| fs::read_link(entry.ok()?.path()).ok())
            .filter_map(|path| {
                path.to_str()?
                    .strip_prefix("socket:[")?
                    .strip_suffix(']')
                    .map(str::to_owned)
            })
            .collect();
        let table = |name: &str| fs::read_to_string(format!("/proc/{pid}/net/{name}")).unwrap();
        let port = self.status()["server"]["port"].as_u64().unwrap();
        only_listener(&table("tcp"), &table("tcp6"), &sockets, port).unwrap();
    }
    pub fn merge(&self, verdict: &str) -> String {
        self.git(&["checkout", "-qb", "synthetic-topic"]);
        file(&self.repo.join("proof/verdict"), verdict);
        file(&self.repo.join("synthetic-change"), verdict);
        self.git(&["add", "."]);
        self.git(&["commit", "-qm", "synthetic candidate"]);
        self.git(&["checkout", "-q", "main"]);
        self.git(&[
            "merge",
            "--no-ff",
            "-qm",
            "synthetic approved merge",
            "synthetic-topic",
        ]);
        self.git(&["branch", "-D", "synthetic-topic"]);
        self.head()
    }
    pub fn sink(&self) -> update::Records {
        let path = self.root.join("service/fixture-records");
        Arc::new(move |issue, body| {
            assert_eq!(issue, 901);
            let mut out = OpenOptions::new()
                .create(true)
                .append(true)
                .mode(0o600)
                .open(&path)
                .map_err(|_| update::RecordError::Unsent)?;
            out.write_all(serde_json::to_string(body).unwrap().as_bytes())
                .map_err(|_| update::RecordError::Uncertain)?;
            out.write_all(b"\n")
                .map_err(|_| update::RecordError::Uncertain)?;
            Ok(())
        })
    }
    pub fn state(&self) -> Arc<Mutex<State>> {
        Arc::new(Mutex::new(State::load(&self.root, 1000).unwrap()))
    }
    pub fn updater(&self, from: &str) -> update::Updater {
        update::Updater::fixture(
            &self.root,
            &self.install,
            &self.repo,
            from,
            self.sink(),
            self.executor.clone(),
        )
        .unwrap()
    }
    pub fn build(&self, commit: &str) -> PathBuf {
        self.root.join("service/builds").join(commit)
    }
    pub fn pending(&self) -> Value {
        serde_json::from_slice(&fs::read(self.root.join("service/update-pending.json")).unwrap())
            .unwrap()
    }
    pub fn records(&self) -> Vec<String> {
        fs::read_to_string(self.root.join("service/fixture-records"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
    pub fn gate(&self) -> Vec<String> {
        self.executor
            .calls
            .lock()
            .unwrap()
            .iter()
            .filter(|s| !s.starts_with("git ") && !s.contains("--update-build"))
            .cloned()
            .collect()
    }
}
pub struct Running(pub std::process::Child);
impl Running {
    pub fn exited(&mut self) {
        let until = std::time::Instant::now() + std::time::Duration::from_secs(15);
        while self.0.try_wait().unwrap().is_none() {
            assert!(std::time::Instant::now() < until, "candidate did not exit");
            std::thread::park_timeout(std::time::Duration::from_millis(10));
        }
    }
}
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if std::thread::panicking() {
            eprintln!("failed fixture: {}", self.temp.display());
            return;
        }
        let _ = fs::remove_dir_all(&self.temp);
    }
}

/// The service's listening (`0A`) TCP entries in one `/proc/<pid>/net/tcp*`
/// table, by local address, kept only when their inode is one of `sockets`.
fn listening(
    table: &str,
    sockets: &std::collections::BTreeSet<String>,
) -> Result<Vec<String>, String> {
    let mut lines = table.lines();
    if !lines
        .next()
        .is_some_and(|header| header.trim_start().starts_with("sl "))
    {
        return Err(format!("unrecognised /proc TCP table: {table:?}"));
    }
    let mut listeners = Vec::new();
    for line in lines {
        let parts: Vec<_> = line.split_whitespace().collect();
        if parts.len() < 10 {
            return Err(format!("unrecognised /proc TCP line: {line:?}"));
        }
        if parts[3] == "0A" && sockets.contains(parts[9]) {
            listeners.push(parts[1].to_owned());
        }
    }
    Ok(listeners)
}
/// The existing loopback HTTP listener (`127.0.0.1:port`) is the service's
/// only TCP listener: its only listening entry in `tcp`, and none in `tcp6`.
pub fn only_listener(
    tcp: &str,
    tcp6: &str,
    sockets: &std::collections::BTreeSet<String>,
    port: u64,
) -> Result<(), String> {
    let v4 = listening(tcp, sockets)?;
    if v4 != [format!("0100007F:{port:04X}")] {
        return Err(format!(
            "IPv4 listeners {v4:?}, expected only 127.0.0.1:{port}"
        ));
    }
    let v6 = listening(tcp6, sockets)?;
    if !v6.is_empty() {
        return Err(format!("IPv6 listeners {v6:?}, expected none"));
    }
    Ok(())
}

#[cfg(test)]
mod listener {
    use super::only_listener;
    const HEADER: &str = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode";
    const HEADER6: &str = "  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode";
    /// One synthetic table line: local address, state, inode.
    fn line(local: &str, state: &str, inode: &str) -> String {
        format!(
            "   0: {local} 00000000:0000 {state} 00000000:00000000 00:00000000 00000000  1000        0 {inode} 1 0000000000000000 100 0 0 10 0"
        )
    }
    fn table(header: &str, lines: &[String]) -> String {
        let mut text = format!("{header}\n");
        for line in lines {
            text.push_str(line);
            text.push('\n');
        }
        text
    }
    /// The service owns inodes 1001 and 1002; 2001 is another process's.
    fn check(tcp: &[String], tcp6: &[String]) -> Result<(), String> {
        let sockets = ["1001", "1002"].map(str::to_owned).into();
        only_listener(&table(HEADER, tcp), &table(HEADER6, tcp6), &sockets, 7370)
    }
    /// 127.0.0.1:7370, listening, the service's socket.
    fn http() -> String {
        line("0100007F:1CCA", "0A", "1001")
    }
    const ANY6: &str = "00000000000000000000000000000000:1F90";
    const LOOP6: &str = "00000000000000000000000001000000:1CCA";

    #[test]
    fn the_existing_loopback_listener_alone_passes() {
        assert_eq!(check(&[http()], &[]), Ok(()));
    }
    #[test]
    fn a_planted_ipv6_listener_of_the_service_is_refused() {
        for local in [ANY6, LOOP6] {
            let result = check(&[http()], &[line(local, "0A", "1002")]);
            assert!(
                result.as_ref().is_err_and(|e| e.contains("IPv6")),
                "{local}: {result:?}"
            );
        }
    }
    #[test]
    fn ipv6_entries_outside_the_inode_filter_or_not_listening_pass() {
        let tcp6 = [line(ANY6, "0A", "2001"), line(LOOP6, "01", "1002")];
        assert_eq!(check(&[http()], &tcp6), Ok(()));
    }
    #[test]
    fn the_ipv4_rule_still_refuses_extra_or_missing_listeners() {
        let extra = line("00000000:1F90", "0A", "1002");
        assert!(check(&[http(), extra], &[]).is_err());
        assert!(check(&[], &[]).is_err());
        assert!(check(&[line("0100007F:1CCB", "0A", "1001")], &[]).is_err());
    }
    #[test]
    fn an_unrecognised_table_is_refused() {
        let sockets = ["1001"].map(str::to_owned).into();
        let tcp = table(HEADER, &[http()]);
        assert!(only_listener(&tcp, "", &sockets, 7370).is_err());
        assert!(
            only_listener(
                &tcp,
                &format!("{HEADER6}\n   0: short 0A\n"),
                &sockets,
                7370
            )
            .is_err()
        );
    }
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2700, as
/// #2583, #2559 and #1754).
fn place(src: &std::path::Path, dst: &std::path::Path) {
    // `cp` would copy into a directory and succeed (#2721).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &std::path::Path, dst: &std::path::Path) -> std::process::Child {
    use std::process::Stdio;
    std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cp runs")
}
/// Waits for `place`'s `cp` to succeed, then makes `dst` executable, owner-only.
fn placed(cp: std::process::Child, dst: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &std::path::Path, text: &[u8]) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &std::path::Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (
        std::path::Path::new("/proc/self/fd"),
        std::path::Path::new("/proc/self/fdinfo"),
    );
    let target = std::fs::metadata(path).unwrap();
    std::fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = std::fs::metadata(fds.join(&fd)).ok()?;
            let info = std::fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2700 (as #2583): this binary's fakes are placed while other test threads
/// fork. The copy is held mid-way on a FIFO, where this process must hold no
/// writer for the placed file; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_a_fake_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = PlaceDir::new("ow-place-t6-fixture");
    let program = dir.0.join("placed");
    let held = writers_mid_copy(&dir.0, &program);
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = std::process::Command::new(&program).output().unwrap();
    assert!(run.status.success());
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2723 (as #2699): the proof above fails, never hangs, when its copier fails
/// before opening the FIFO. Here `cp` cannot stat a destination under a
/// regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let dir = PlaceDir::new("ow-place-t6-fixture-early");
    let file = dir.0.join("file");
    std::fs::write(&file, "").unwrap();
    writers_mid_copy(&dir.0, &file.join("placed"));
}
/// #2723 (as #2707), #2750: a copier still waiting on the FIFO when a proof
/// fails is killed and reaped as its `Copy` unwinds, never left behind. With no
/// writer started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let dir = PlaceDir::new("ow-place-t6-fixture-late");
    let fifo = dir.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = dir.0.join("placed");
    let cp = copier(&fifo, &program);
    let pid = cp.id();
    let unwound = std::panic::catch_unwind(move || {
        let _copy = Copy {
            source: None,
            cp: Some(cp),
            program,
            until: std::time::Instant::now(),
        };
        panic!("the proof failed while its copier waited");
    });
    assert!(unwound.is_err());
    let left = std::fs::metadata(format!("/proc/{pid}")).map(|_| ());
    assert_eq!(
        left.map_err(|e| e.kind()),
        Err(std::io::ErrorKind::NotFound),
        "the copier was left running or unreaped after the proof unwound"
    );
}
/// An owner-only scratch directory for one FIFO proof, removed when dropped,
/// even by a failing proof.
#[cfg(target_os = "linux")]
struct PlaceDir(std::path::PathBuf);
#[cfg(target_os = "linux")]
impl PlaceDir {
    fn new(prefix: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
#[cfg(target_os = "linux")]
impl Drop for PlaceDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
/// Places a script at `program` as `place` does, from a FIFO in `dir` this
/// process writes, and returns how many writers this process held for
/// `program` while the copy was held mid-way. One deadline, set before the
/// FIFO opens, bounds every wait.
#[cfg(target_os = "linux")]
fn writers_mid_copy(dir: &std::path::Path, program: &std::path::Path) -> usize {
    use std::time::{Duration, Instant};
    let fifo = dir.join("source.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while std::fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
        copy.check("the copy started");
    }
    let held = writers(program);
    copy.write(b"printf 'PLACED\\n'\n");
    copy.finish();
    held
}
/// `place`'s `cp` copying a FIFO to `program`, and this process's writer for
/// that FIFO. Dropped, even by a failing proof, it closes the writer, so the
/// copier reads its end, then kills a copier still running after a short
/// grace and reaps it (#2707).
#[cfg(target_os = "linux")]
struct Copy {
    source: Option<std::fs::File>,
    cp: Option<std::process::Child>,
    program: std::path::PathBuf,
    until: std::time::Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &std::path::Path, program: &std::path::Path, until: std::time::Instant) -> Self {
        let mut copy = Self {
            source: None,
            cp: Some(copier(fifo, program)),
            program: program.to_owned(),
            until,
        };
        // Opening blocks until a reader has the FIFO open, so it runs on its
        // own thread while this one watches the copier and the deadline.
        let opening = {
            let fifo = fifo.to_owned();
            std::thread::spawn(move || std::fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || std::time::Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = std::fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        copy.source = Some(opening.join().unwrap().unwrap());
        copy
    }
    fn ended(&mut self) -> bool {
        self.cp
            .as_mut()
            .is_none_or(|cp| cp.try_wait().unwrap().is_some())
    }
    /// Fails if the copier has ended or `until` has passed; else waits a moment.
    fn check(&mut self, waiting_for: &str) {
        assert!(!self.ended(), "the copier ended before {waiting_for}");
        assert!(
            std::time::Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(
                std::time::Instant::now() < self.until,
                "the copier never finished"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        placed(self.cp.take().unwrap(), &self.program);
    }
}
#[cfg(target_os = "linux")]
impl Drop for Copy {
    fn drop(&mut self) {
        drop(self.source.take());
        // The copier ends soon after its end of file: a short grace past a
        // missed deadline, never an unbounded wait.
        let now = std::time::Instant::now();
        let until = self.until.max(now + std::time::Duration::from_secs(1));
        while !self.ended() && std::time::Instant::now() < until {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}
/// #2721: a directory at the exact destination is refused, as the child
/// writer's `cat > "$1"` refused it, instead of `cp` placing the program
/// inside that directory and reporting success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-place-dir-t6-fixture-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, b"#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
