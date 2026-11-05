//! Shared native App fixture; no live exchange or account operations.
#![allow(dead_code)]
use super::{service, update};
use openwiz_adapter_github::app::{Clock, Error, Exchange};
use serde_json::{Value, json};
use service::app::Client;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt, symlink},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::Instant,
};
pub(super) const OLD: &str = "1111111111111111111111111111111111111111";
pub(super) const NEW: &str = "2222222222222222222222222222222222222222";
const TOKEN: &str = "synthetic-engine-app-token";

struct FixedTime;
impl Clock for FixedTime {
    fn now_s(&self) -> u64 {
        1_893_456_000
    }
}
struct Tokens(String);
impl Exchange for Tokens {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        _: Instant,
    ) -> Result<Vec<u8>, Error> {
        assert_eq!(installation, 2002);
        assert_eq!(jwt.split('.').count(), 3);
        assert_eq!(
            serde_json::from_slice::<Value>(body).unwrap()["repositories"],
            json!([self.0])
        );
        Ok(json!({"token":TOKEN,"expires_at":"2030-01-01T01:00:00Z","permissions":{
            "metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}}).to_string().into_bytes())
    }
}
pub(super) struct Private(pub(super) PathBuf);
impl Drop for Private {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
pub(super) fn rows(root: &Path) -> Vec<Value> {
    fs::read_to_string(root.join("endpoint-calls.jsonl"))
        .unwrap_or_default()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}
pub(super) fn config() -> Value {
    json!({"schema":"openwiz.service-config.v1","repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
        "operator":"synthetic-owner","project":"prj_syn_engine","orchestrator_thread":"thr_syn_answer",
        "service_issue":901,"github_app":{"app_id":1001,"installation_id":2002},
        "tick":{"every_s":300},"health":{"every_s":60},"server":{"port":7370,"allowed_host":null,"probe_timeout_s":10}})
}
pub(super) fn records(root: &Path) -> update::Records {
    let client = client(root, &config().to_string()).unwrap();
    update::app_record_sink(
        901,
        "synthetic-owner/synthetic-repo",
        Arc::new(move |call, deadline| {
            client
                .execute(call, deadline)
                .map_err(|_| update::RecordError::Uncertain)
        }),
    )
    .unwrap()
}

pub(super) fn directory(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
pub(super) fn file(path: &Path, value: impl AsRef<[u8]>) {
    fs::write(path, value).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
pub(super) struct Fixture {
    pub root: Private,
    pub install: PathBuf,
    pub source: PathBuf,
    pub build: PathBuf,
}
impl Fixture {
    pub fn new(mode: &str, endpoint: &str) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = Private(std::env::temp_dir().join(format!(
            "openwiz-engine-app-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )));
        let install = root.0.join("install");
        let source = root.0.join("consumer");
        let build = root.0.join("service/builds").join(OLD);
        for path in [
            &install,
            &source,
            &build.join("runtime"),
            &root.0.join("service/app"),
        ] {
            directory(path);
        }
        file(&root.0.join("service/config.json"), config().to_string());
        file(&root.0.join("mode"), mode);
        file(
            &install.join("channel.json"),
            r#"{"schema":"openwiz.update-channel.v1","channel":"packaged"}"#,
        );
        file(
            &build.join("runtime/pull.py"),
            "Synthetic unused transport; executor records calls.",
        );
        file(
            &build.join("openwiz-service"),
            "Synthetic unexecuted selected build.",
        );
        symlink(&build, install.join("current")).unwrap();
        let key = root.0.join("service/app/private-key.pem");
        let keygen = Command::new("/usr/bin/openssl")
            .args([
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
            ])
            .arg(&key)
            .output()
            .unwrap();
        assert!(keygen.status.success());
        fs::set_permissions(key, fs::Permissions::from_mode(0o600)).unwrap();
        let quote = |p: &Path| format!("'{}'", p.to_str().unwrap().replace('\'', "'\\''"));
        let script = format!(
            "#!/bin/sh\nexport OPENWIZ_ENGINE_APP_ROOT={}\nexport OPENWIZ_ENGINE_APP_ARGS={}/args-$$\nprintf '%s\\0' \"$@\" > \"$OPENWIZ_ENGINE_APP_ARGS\"\nexec {} --exact {endpoint} --nocapture 3>&1 >/dev/null\n",
            quote(&root.0),
            quote(&root.0),
            quote(&std::env::current_exe().unwrap())
        );
        place_script(&root.0.join("gh"), &script);
        Self {
            root,
            install,
            source,
            build,
        }
    }
}
pub(super) fn app_endpoint_process() {
    let Some(root) = std::env::var_os("OPENWIZ_ENGINE_APP_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let input = PathBuf::from(std::env::var_os("OPENWIZ_ENGINE_APP_ARGS").unwrap());
    let bytes = fs::read(&input).unwrap();
    fs::remove_file(input).unwrap();
    assert_eq!(bytes.last(), Some(&0));
    let args: Vec<_> = bytes[..bytes.len() - 1]
        .split(|b| *b == 0)
        .map(|b| std::str::from_utf8(b).unwrap().to_owned())
        .collect();
    assert_eq!(std::env::var("GH_TOKEN").unwrap(), TOKEN);
    let repository = expected_repository(&root);
    let issue = fs::read_to_string(root.join("expected-issue")).unwrap_or_else(|_| "901".into());
    let url = format!("https://github.com/{repository}/issues/{issue}#issuecomment-123");
    assert_eq!(
        std::env::var("GH_REPO").unwrap(),
        format!("github.com/{repository}")
    );
    assert_eq!(std::env::var("GH_HOST").unwrap(), "github.com");
    let mode = fs::read_to_string(root.join("mode")).unwrap();
    let write = args.get(1).map(String::as_str) == Some("comment");
    OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(root.join("endpoint-calls.jsonl"))
        .unwrap()
        .write_all(
            format!(
                "{}\n",
                json!({"write":write,"issue":args[2],"repo":std::env::var("GH_REPO").unwrap()})
            )
            .as_bytes(),
        )
        .unwrap();
    let answer = if write {
        assert_eq!(&args[..4], ["issue", "comment", issue.as_str(), "--body"]);
        assert_eq!(args.len(), 5);
        file(
            &root.join("posted.json"),
            json!({"body":args[4],"url":url}).to_string(),
        );
        if mode == "lost" {
            std::process::exit(97)
        }
        format!("{url}\n")
    } else {
        assert_eq!(
            args,
            ["issue", "view", issue.as_str(), "--json", "comments"]
        );
        let posted: Value =
            serde_json::from_slice(&fs::read(root.join("posted.json")).unwrap()).unwrap();
        let comments = if mode == "missing" {
            vec![]
        } else {
            vec![json!({"id":"synthetic-comment","author":null,
            "authorAssociation":"OWNER","body":if mode=="wrong" {json!("Synthetic wrong readback")} else {posted["body"].clone()},
            "createdAt":"2030-01-01T00:00:00Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":"",
            "reactionGroups":[],"url":url,"viewerDidAuthor":true})]
        };
        json!({"comments":comments}).to_string()
    };
    let mut out = OpenOptions::new()
        .write(true)
        .open("/proc/self/fd/3")
        .unwrap();
    out.write_all(answer.as_bytes()).unwrap();
    std::process::exit(0);
}

pub(super) fn expected_repository(root: &Path) -> String {
    fs::read_to_string(root.join("expected-repository"))
        .unwrap_or_else(|_| "synthetic-owner/synthetic-repo".into())
}
pub(super) fn client(root: &Path, config: &str) -> Result<Client, Error> {
    let repository = expected_repository(root);
    let name = repository.split_once('/').unwrap().1.to_owned();
    Client::with_exchange(
        root,
        config,
        root.join("gh"),
        Arc::new(Tokens(name)),
        Arc::new(FixedTime),
    )
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
fn place_script(dst: &std::path::Path, text: &str) {
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
    let dir = PlaceDir::new("ow-place-app-support");
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
    let dir = PlaceDir::new("ow-place-app-support-early");
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
    let dir = PlaceDir::new("ow-place-app-support-late");
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
    let dir = std::env::temp_dir().join(format!("ow-place-dir-app-support-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
