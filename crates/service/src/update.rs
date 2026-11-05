//! T6: outbound-only updates. Calls have fixed forms; no shell command string.
use std::path::Path;

/// The build/test commands, in fleet.md order. Cargo never runs concurrently.
pub const GATE: &[(&str, &[&str], &str)] = &[
    ("sh", &[".github/actions/docs-only/test.sh"], "."),
    ("npm", &["ci", "--ignore-scripts"], "apps/web"),
    ("npm", &["run", "build"], "apps/web"),
    ("npm", &["run", "typecheck"], "apps/web"),
    ("npm", &["run", "check"], "apps/web"),
    ("cargo", &["fmt", "--check"], "."),
    (
        "cargo",
        &[
            "clippy",
            "--workspace",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ],
        ".",
    ),
    ("cargo", &["build", "--workspace"], "."),
    ("cargo", &["test", "--workspace"], "."),
    (
        "cargo",
        &["test", "-p", "openwiz-tests", "--test", "checks", "pending"],
        ".",
    ),
    ("cargo", &["build", "--release"], "."),
    ("npm", &["test"], "apps/web"),
];

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct PackageCandidate {
    schema: String,
    version: String,
    source: String,
    target: String,
    manifest_sha256: String,
}

fn hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn version_numbers(value: &str) -> Option<Vec<u64>> {
    let parts: Vec<_> = value.split('.').collect();
    if parts.len() != 3
        || parts[0] != "0"
        || parts
            .iter()
            .any(|v| v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    parts.iter().map(|v| v.parse().ok()).collect()
}
fn supported_package_target(value: &str) -> bool {
    matches!(
        value,
        "aarch64-apple-darwin" | "x86_64-apple-darwin" | "x86_64-unknown-linux-gnu"
    )
}
fn native_package_target() -> Option<&'static str> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Some("aarch64-apple-darwin"),
        ("macos", "x86_64") => Some("x86_64-apple-darwin"),
        ("linux", "x86_64") => Some("x86_64-unknown-linux-gnu"),
        _ => None,
    }
}
fn packaged_channel(install: &Path) -> Result<bool, String> {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Channel {
        schema: String,
        channel: String,
    }
    let path = install.join("channel.json");
    if !path
        .try_exists()
        .map_err(|_| "cannot inspect update channel")?
        && !path.is_symlink()
    {
        return Ok(false);
    }
    private(&path, false)?;
    let bytes = fs::read(&path).map_err(|_| "cannot read update channel")?;
    if bytes.len() > 1024 {
        return Err("update channel is too large".to_owned());
    }
    let channel: Channel = serde_json::from_slice(&bytes).map_err(|_| "invalid update channel")?;
    if channel.schema != "openwiz.update-channel.v1" {
        return Err("invalid update channel".to_owned());
    }
    match channel.channel.as_str() {
        "packaged" => Ok(true),
        "source" => Ok(false),
        _ => Err("unknown update channel".to_owned()),
    }
}

/// A public negative-test seam; execution also checks these exact forms.
pub fn allows_gate(program: &Path, args: &[&str]) -> bool {
    GATE.iter()
        .any(|(p, a, _)| program == Path::new(p) && args == *a)
}

use crate::state::State;
use openwiz_core::fleet::model::Commit;
use serde_json::{Value, json};
use std::{
    fs::{self, DirBuilder, File, OpenOptions},
    io::{Read, Write},
    os::unix::{
        fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt},
        process::CommandExt,
    },
    path::{Component, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};

const UPDATE: &str = "update";

struct UpdateLock(File);
impl Drop for UpdateLock {
    fn drop(&mut self) {
        // A concurrent fork may retain the same open file until exec. Unlock
        // before closing ours so that copy cannot outlive this attempt's lock.
        let _ = self.0.unlock();
    }
}
/// Only a definitely-unsent request can be retried without reconciliation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecordError {
    Unsent,
    Uncertain,
}
pub type Records = Arc<dyn Fn(u64, &str) -> Result<(), RecordError> + Send + Sync>;
/// Explicit App executor composition; no personal-account fallback.
pub type AppRecordExecute = Arc<
    dyn Fn(&openwiz_adapter_github::allowlist::Invocation, Instant) -> Result<Vec<u8>, RecordError>
        + Send
        + Sync,
>;
pub fn app_record_sink(
    issue: u64,
    repository: &str,
    execute: AppRecordExecute,
) -> Result<Records, String> {
    use openwiz_adapter_github::allowlist::Invocation;
    let repository = openwiz_core::fleet::starts::Repository::parse(repository)
        .map_err(|_| "invalid App record repository")?;
    if issue == 0 {
        return Err("invalid service record issue".to_owned());
    }
    let prefix = format!(
        "https://github.com/{}/issues/{issue}#issuecomment-",
        repository.as_str()
    );
    Ok(Arc::new(move |asked, body| {
        if asked != issue || openwiz_adapter_github::writes::Body::parse(body).is_none() {
            return Err(RecordError::Unsent);
        }
        let issue = issue.to_string();
        let write = Invocation::new(&["issue", "comment", &issue, "--body", body])
            .ok_or(RecordError::Unsent)?;
        let read = Invocation::new(&["issue", "view", &issue, "--json", "comments"])
            .ok_or(RecordError::Unsent)?;
        let deadline = Instant::now() + Duration::from_secs(30);
        let printed = execute(&write, deadline)?;
        let printed = std::str::from_utf8(&printed).map_err(|_| RecordError::Uncertain)?;
        let url = printed.strip_suffix('\n').unwrap_or(printed);
        if !url.strip_prefix(&prefix).is_some_and(|v| {
            !v.is_empty()
                && v.bytes().all(|b| b.is_ascii_digit())
                && v.parse::<u64>().is_ok_and(|n| n > 0)
        }) {
            return Err(RecordError::Uncertain);
        }
        let bytes = execute(&read, deadline).map_err(|_| RecordError::Uncertain)?;
        let comments: AppComments =
            serde_json::from_slice(&bytes).map_err(|_| RecordError::Uncertain)?;
        let mut matching = comments.comments.iter().filter(|c| c.url == url);
        match (matching.next(), matching.next()) {
            (Some(comment), None) if comment.body == body => Ok(()),
            _ => Err(RecordError::Uncertain),
        }
    }))
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct AppComments {
    comments: Vec<AppComment>,
}
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct AppComment {
    url: String,
    body: String,
    #[serde(rename = "id")]
    _id: Value,
    #[serde(rename = "author")]
    _author: Value,
    #[serde(rename = "authorAssociation")]
    _association: Value,
    #[serde(rename = "createdAt")]
    _created: Value,
    #[serde(rename = "includesCreatedEdit")]
    _edited: Value,
    #[serde(rename = "isMinimized")]
    _minimized: Value,
    #[serde(rename = "minimizedReason")]
    _reason: Value,
    #[serde(rename = "reactionGroups")]
    _reactions: Value,
    #[serde(rename = "viewerDidAuthor")]
    _viewer: Value,
}

fn configured_records(root: &Path, config: &Value) -> Result<Records, String> {
    if let Some(records) = RECORDS.get().cloned() {
        return Ok(records);
    }
    configured_records_at(
        root,
        config,
        &installation()?,
        crate::app::Client::from_config,
    )
}

fn configured_records_at(
    root: &Path,
    config: &Value,
    install: &Path,
    make_client: impl FnOnce(
        &Path,
        &str,
    ) -> Result<crate::app::Client, openwiz_adapter_github::app::Error>,
) -> Result<Records, String> {
    // The new production composition is explicit to packaged installations.
    // Existing source installations retain their prior default and injection.
    if !packaged_channel(install)? {
        return Err("service App update records are not configured".to_owned());
    }
    let client = make_client(root, &config.to_string())
        .map_err(|_| "cannot configure the service App record client")?;
    let repository = format!(
        "{}/{}",
        config["repository"]["owner"]
            .as_str()
            .ok_or("missing record owner")?,
        config["repository"]["name"]
            .as_str()
            .ok_or("missing record repository")?
    );
    let issue = config["service_issue"]
        .as_u64()
        .ok_or("missing record issue")?;
    app_record_sink(
        issue,
        &repository,
        Arc::new(move |call, deadline| {
            client
                .execute(call, deadline)
                .map_err(|_| RecordError::Uncertain)
        }),
    )
}
static RECORDS: OnceLock<Records> = OnceLock::new();
static EXECUTOR: OnceLock<Arc<dyn Executor>> = OnceLock::new();

/// T7 installs its shared App executor. There is no personal-account fallback.
pub fn install_records(records: Records) -> Result<(), &'static str> {
    RECORDS
        .set(records)
        .map_err(|_| "service App records already installed")
}
/// Explicit dependency injection for an embedding entrypoint, never an env gate.
pub fn install_executor(executor: Arc<dyn Executor>) -> Result<(), &'static str> {
    EXECUTOR
        .set(executor)
        .map_err(|_| "update executor already installed")
}

/// An immutable outbound call. Only this module can construct one.
pub struct Call {
    program: PathBuf,
    argv: Vec<String>,
    directory: PathBuf,
    commit: Commit,
}
impl Call {
    pub fn program(&self) -> &Path {
        &self.program
    }
    pub fn argv(&self) -> &[String] {
        &self.argv
    }
    pub fn directory(&self) -> &Path {
        &self.directory
    }
    fn new(program: &str, argv: &[&str], directory: &Path, commit: &Commit) -> Self {
        Self {
            program: program.into(),
            argv: argv.iter().map(|s| (*s).to_owned()).collect(),
            directory: directory.to_owned(),
            commit: commit.clone(),
        }
    }
}

/// Recording/fault-injecting fakes use the same immutable calls as production.
pub trait Executor: Send + Sync {
    fn run(&self, call: &Call) -> Result<String, String>;
}
pub struct System;
impl Executor for System {
    fn run(&self, call: &Call) -> Result<String, String> {
        self.run_cancel(call, &std::sync::atomic::AtomicBool::new(false))
    }
}
impl System {
    /// Cancellation is also used for a controlled shutdown of an update job.
    pub fn run_cancel(
        &self,
        call: &Call,
        cancel: &std::sync::atomic::AtomicBool,
    ) -> Result<String, String> {
        let read = call.program == Path::new("git")
            || call.argv == ["--update-build"]
            || (call.program == Path::new("python3")
                && call.argv.get(1).is_some_and(|v| v == "discover"));
        let mut cmd = command(call)?;
        if read {
            cmd.stdout(Stdio::piped());
        }
        let mut child = cmd
            .spawn()
            .map_err(|_| "cannot start update command".to_owned())?;
        // Build/test output can contain credentials or repository content: never
        // retain it. Git reads are tiny and go to a private temporary file.
        let (tx, rx) = std::sync::mpsc::channel();
        if let Some(out) = child.stdout.take() {
            std::thread::spawn(move || {
                let mut bytes = Vec::new();
                let result = out.take(4097).read_to_end(&mut bytes);
                let _ = tx.send(result.map(|_| bytes));
            });
        }
        let until = Instant::now() + Duration::from_secs(if read { 60 } else { 1800 });
        loop {
            if let Some(status) = child
                .try_wait()
                .map_err(|_| "cannot wait for update command")?
            {
                stop_group(call, child.id());
                if !status.success() {
                    return Err("update command failed".to_owned());
                }
                if !read {
                    return Ok(String::new());
                }
                let bytes = rx
                    .recv_timeout(Duration::from_secs(2))
                    .map_err(|_| "update read did not finish")?
                    .map_err(|_| "update read failed")?;
                if bytes.len() > 4096 {
                    return Err("update read too large".to_owned());
                }
                return String::from_utf8(bytes).map_err(|_| "update read is not UTF-8".to_owned());
            }
            if Instant::now() >= until || cancel.load(std::sync::atomic::Ordering::SeqCst) {
                // This process group was created for this exact child. Never
                // signal a name, a user-wide pattern or another service.
                stop_group(call, child.id());
                let _ = child.kill();
                let _ = child.wait();
                return Err("update command timed out".to_owned());
            }
            std::thread::park_timeout(Duration::from_millis(10));
        }
    }
}

fn stop_group(call: &Call, pid: u32) {
    let group = format!("-{pid}");
    let stop = Call::new(
        "/bin/kill",
        &["-KILL", "--", &group],
        call.directory(),
        &call.commit,
    );
    let _ = command(&stop).and_then(|mut stop| {
        stop.status()
            .map_err(|_| "cannot stop owned update group".to_owned())
    });
}

/// A fixture can run a real fixed gate command with an explicit cancellation.
pub fn gate_call(program: &Path, argv: &[&str], directory: &Path, commit: &str) -> Option<Call> {
    if !allows_gate(program, argv) {
        return None;
    }
    Some(Call::new(
        program.to_str()?,
        argv,
        directory,
        &Commit::parse(commit)?,
    ))
}

/// Fixed forms for all three classes of outbound effects. Dynamic values are
/// typed commits or absolute paths, never shell fragments or extra flags.
pub fn allows_command(program: &Path, args: &[&str]) -> bool {
    if allows_gate(program, args) {
        return true;
    }
    if program == Path::new("python3") {
        let valid_script = |script: &str| {
            let path = Path::new(script);
            absolute(path).is_ok()
                && path.file_name().is_some_and(|v| v == "pull.py")
                && path
                    .parent()
                    .and_then(Path::file_name)
                    .is_some_and(|v| v == "runtime")
                && path
                    .parent()
                    .and_then(Path::parent)
                    .and_then(Path::file_name)
                    .and_then(|v| v.to_str())
                    .and_then(Commit::parse)
                    .is_some()
        };
        return match args {
            [script, "discover", target] => {
                valid_script(script) && supported_package_target(target)
            }
            [
                script,
                "stage",
                target,
                version,
                source,
                checksum,
                install,
                state,
            ] => {
                valid_script(script)
                    && supported_package_target(target)
                    && version_numbers(version).is_some()
                    && Commit::parse(source).is_some()
                    && hex(checksum, 64)
                    && absolute(Path::new(install)).is_ok()
                    && absolute(Path::new(state)).is_ok()
            }
            _ => false,
        };
    }
    if program == Path::new("git") {
        let Some(args) = args.strip_prefix(&[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.ext.allow=never",
        ]) else {
            return false;
        };
        return match args {
            ["init", "--bare"]
            | ["remote", "get-url", "origin"]
            | ["ls-remote", "--exit-code", "origin", "refs/heads/main"]
            | [
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "origin",
                "+refs/heads/main:refs/heads/main",
            ]
            | ["rev-parse", "--verify", "refs/heads/main^{commit}"] => true,
            ["remote", "add", "origin", url] => {
                if let Some(path) = url.strip_prefix("file://") {
                    absolute(Path::new(path)).is_ok()
                } else if let Some(path) = url
                    .strip_prefix("https://github.com/")
                    .and_then(|s| s.strip_suffix(".git"))
                {
                    let pieces: Vec<_> = path.split('/').collect();
                    pieces.len() == 2
                        && pieces.iter().all(|s| {
                            !s.is_empty()
                                && s.bytes()
                                    .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
                        })
                } else {
                    false
                }
            }
            ["merge-base", "--is-ancestor", from, to] => {
                Commit::parse(from).is_some() && Commit::parse(to).is_some()
            }
            ["clone", "--no-hardlinks", "--no-checkout", "--", from, to] => {
                absolute(Path::new(from)).is_ok() && absolute(Path::new(to)).is_ok()
            }
            ["checkout", "--detach", "--force", commit] => Commit::parse(commit).is_some(),
            _ => false,
        };
    }
    if program == Path::new("/bin/kill") {
        return matches!(args, ["-KILL", "--", group] if group.strip_prefix('-').is_some_and(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()) && p.parse::<u32>().is_ok_and(|p| p > 1)));
    }
    program.file_name().is_some_and(|s| s == "openwiz-service")
        && absolute(program).is_ok()
        && program
            .parent()
            .and_then(|p| p.file_name())
            .and_then(|s| s.to_str())
            .and_then(Commit::parse)
            .is_some()
        && (args.is_empty() || args == ["--update-build"])
}

// Handover inherits the unit's descriptors, environment and process group.
// Build/test children add their isolation only after this common validation.
fn validated_command(call: &Call) -> Result<Command, String> {
    let args: Vec<_> = call.argv.iter().map(String::as_str).collect();
    if !allows_command(call.program(), &args) {
        return Err("update command is not allowlisted".to_owned());
    }
    if call.program.is_absolute() && call.program != Path::new("/bin/kill") {
        let parent = call.program.parent().ok_or("candidate parent missing")?;
        if parent.file_name().and_then(|s| s.to_str()) != Some(call.commit.as_str()) {
            return Err("candidate path and commit disagree".to_owned());
        }
        private(parent, true)?;
        private(&call.program, false)?;
    }
    let mut cmd = Command::new(call.program());
    cmd.args(call.argv()).current_dir(call.directory());
    Ok(cmd)
}

const GATE_ENV: &[&str] = &[
    "PATH",
    "HOME",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "OPENWIZ_CHROMIUM",
];

fn command(call: &Call) -> Result<Command, String> {
    let mut cmd = validated_command(call)?;
    cmd.env_clear();
    for key in GATE_ENV {
        if let Some(value) = std::env::var_os(key) {
            cmd.env(key, value);
        }
    }
    cmd.process_group(0)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .env("OPENWIZ_SERVICE_BUILD", call.commit.as_str())
        .env("CIRCLE_NODE_TOTAL", "2")
        .env("CARGO_BUILD_JOBS", "2")
        .env("LANG", "C.UTF-8")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_CONFIG_NOSYSTEM", "1");
    Ok(cmd)
}

/// A local repository is an explicit fixture seam, never selected from config
/// or an environment variable in the production dispatch.
pub struct Updater {
    root: PathBuf,
    install: PathBuf,
    source: String,
    from: Commit,
    issue: u64,
    records: Records,
    executor: Arc<dyn Executor>,
    package_target: Option<&'static str>,
}
impl Updater {
    pub fn production(
        root: &Path,
        install: &Path,
        config: &Value,
        from: &str,
        records: Records,
    ) -> Result<Self, String> {
        crate::document::validate(crate::document::Document::Config, config)?;
        Self::new(
            root,
            install,
            format!(
                "https://github.com/{}/{}.git",
                config["repository"]["owner"].as_str().unwrap(),
                config["repository"]["name"].as_str().unwrap()
            ),
            from,
            config["service_issue"].as_u64().unwrap(),
            records,
            EXECUTOR.get().cloned().unwrap_or_else(|| Arc::new(System)),
        )
    }
    pub fn fixture(
        root: &Path,
        install: &Path,
        source: &Path,
        from: &str,
        records: Records,
        executor: Arc<dyn Executor>,
    ) -> Result<Self, String> {
        absolute(source)?;
        let mut updater = Self::new(
            root,
            install,
            format!("file://{}", source.display()),
            from,
            901,
            records,
            executor,
        )?;
        // Explicit fixture composition can model a supported target on any CI host.
        updater.package_target = Some("x86_64-unknown-linux-gnu");
        Ok(updater)
    }
    fn new(
        root: &Path,
        install: &Path,
        source: String,
        from: &str,
        issue: u64,
        records: Records,
        executor: Arc<dyn Executor>,
    ) -> Result<Self, String> {
        absolute(install)?;
        Ok(Self {
            root: root.into(),
            install: install.into(),
            source,
            from: Commit::parse(from).ok_or("invalid running build")?,
            issue,
            records,
            executor,
            package_target: native_package_target(),
        })
    }
    /// One main candidate, once. Failing candidates are not repeatedly rebuilt.
    /// A passing gate creates a pending handover, never a switched result.
    pub fn check(&self, state: &Arc<Mutex<State>>, at: u64) -> Result<bool, String> {
        crate::paths::inspect(&self.root)?;
        let lock_path = self.root.join("service/update.lock");
        if fs::symlink_metadata(&lock_path).is_ok() {
            private(&lock_path, false)?;
        }
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(&lock_path)
            .map_err(|_| "cannot open update lock")?;
        lock.try_lock()
            .map_err(|_| "an update is already running")?;
        let _lock = UpdateLock(lock);
        crate::paths::inspect(&self.root)?;
        private(&self.install, true)?;
        // A later unit restart must still enter through this running build.
        // Reject an unmanaged selection before any outbound or build effect.
        let current = json!({"from":self.from.as_str(),"to":self.from.as_str()});
        selection(&self.root, &self.install, &current, self.from.as_str())?;
        if let Some(mut pending) = read_pending(&self.root)? {
            if pending["record_claimed"] == false {
                let saved = saved_attempt(
                    state
                        .lock()
                        .map_err(|_| "service state unavailable")?
                        .snapshot(),
                    &pending,
                );
                if let Some(saved) = saved {
                    self.record(&mut pending, &saved)?;
                }
            }
            return Ok(false);
        }
        if packaged_channel(&self.install)? {
            return self.check_package(state, at);
        }
        let clone = self.root.join("service/clone");
        if !clone.exists() {
            directory(&clone)?;
            self.git(&clone, &["init", "--bare"], &self.from)?;
            self.git(
                &clone,
                &["remote", "add", "origin", &self.source],
                &self.from,
            )?;
        }
        private(&clone, true)?;
        if self.git(&clone, &["remote", "get-url", "origin"], &self.from)?
            != format!("{}\n", self.source)
        {
            return Err("update clone has the wrong origin".to_owned());
        }
        let value = self.git(
            &clone,
            &["ls-remote", "--exit-code", "origin", "refs/heads/main"],
            &self.from,
        )?;
        let to = value
            .strip_suffix("\trefs/heads/main\n")
            .and_then(Commit::parse)
            .ok_or("main did not name one full commit")?;
        if to == self.from
            || state
                .lock()
                .map_err(|_| "service state unavailable")?
                .snapshot()[UPDATE]["to"]
                == to.as_str()
        {
            return Ok(false);
        }
        let mut pending = json!({"at":at,"from":self.from.as_str(),"to":to.as_str(),"phase":"fetch","record_claimed":false});
        write_pending(&self.root, &pending)?;
        let fetch = (|| -> Result<(), String> {
            self.git(
                &clone,
                &[
                    "fetch",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "origin",
                    "+refs/heads/main:refs/heads/main",
                ],
                &to,
            )?;
            let fetched = self.git(
                &clone,
                &["rev-parse", "--verify", "refs/heads/main^{commit}"],
                &to,
            )?;
            if fetched != format!("{}\n", to.as_str()) {
                return Err("main changed during fetch".to_owned());
            }
            self.git(
                &clone,
                &[
                    "merge-base",
                    "--is-ancestor",
                    self.from.as_str(),
                    to.as_str(),
                ],
                &to,
            )?;
            Ok(())
        })();
        if fetch.is_err() {
            let result = attempt(
                &pending,
                Some(("fetch", "candidate fetch failed or main changed")),
            );
            save_attempt(state, &result)?;
            self.record(&mut pending, &result)?;
            return Ok(false);
        }
        pending["phase"] = json!("build");
        write_pending(&self.root, &pending)?;
        let build = self.root.join("service/builds").join(to.as_str());
        let mut created = false;
        let prepare = (|| -> Result<(), String> {
            directory(&self.root.join("service/builds"))?;
            private(&self.root.join("service/builds"), true)?;
            // Never overwrite an installed or previously attempted build.
            DirBuilder::new()
                .mode(0o700)
                .create(&build)
                .map_err(|_| "candidate directory already exists or cannot be made")?;
            created = true;
            let source = build.join("source");
            self.git(
                &clone,
                &[
                    "clone",
                    "--no-hardlinks",
                    "--no-checkout",
                    "--",
                    clone.to_str().ok_or("clone path is not UTF-8")?,
                    source.to_str().ok_or("build path is not UTF-8")?,
                ],
                &to,
            )?;
            self.git(
                &source,
                &["checkout", "--detach", "--force", to.as_str()],
                &to,
            )?;
            normalize(&clone)?;
            for (index, (program, args, sub)) in GATE.iter().enumerate() {
                // Compilation/setup failures are distinct from failed checks.
                let step = if [0, 3, 4, 5, 6, 8, 9, 11].contains(&index) {
                    "test"
                } else {
                    "build"
                };
                pending["phase"] = json!(step);
                write_pending(&self.root, &pending)?;
                self.executor
                    .run(&Call::new(program, args, &source.join(sub), &to))?;
            }
            pending["phase"] = json!("build");
            write_pending(&self.root, &pending)?;
            copy_file(
                &source.join("target/release/openwiz-service"),
                &build.join("openwiz-service"),
                0o700,
            )?;
            copy_web(&source.join("apps/web/out"), &build.join("web"))?;
            let identity = self.executor.run(&Call::new(
                build
                    .join("openwiz-service")
                    .to_str()
                    .ok_or("program path is not UTF-8")?,
                &["--update-build"],
                &build,
                &to,
            ))?;
            if identity != format!("{}\n", to.as_str()) {
                return Err("candidate compiled identity disagrees with main".to_owned());
            }
            Ok(())
        })();
        // No gate descendant survives completion. Only the staged program/web
        // are needed for handover; discard the checkout and all build caches.
        let cleanup = if created {
            remove_source(&build)
        } else {
            Ok(())
        };
        if cleanup.is_err() {
            pending["phase"] = json!("build");
        }
        if prepare.is_err() || cleanup.is_err() {
            let step = pending["phase"].as_str().unwrap();
            let attempt = attempt(
                &pending,
                Some((step, "candidate build or acceptance command failed")),
            );
            save_attempt(state, &attempt)?;
            self.record(&mut pending, &attempt)?;
            return Ok(false);
        }
        pending["phase"] = json!("queued");
        write_pending(&self.root, &pending)?;
        Ok(true)
    }
    fn check_package(&self, state: &Arc<Mutex<State>>, at: u64) -> Result<bool, String> {
        let target = self
            .package_target
            .ok_or("unsupported packaged update host")?;
        let running = self.root.join("service/builds").join(self.from.as_str());
        let runtime = running.join("runtime");
        private(&runtime, true)?;
        let script = runtime.join("pull.py");
        private(&script, false)?;
        let script = script.to_str().ok_or("package runtime path is not UTF-8")?;
        let output = self.executor.run(&Call::new(
            "python3",
            &[script, "discover", target],
            &running,
            &self.from,
        ))?;
        let candidate: PackageCandidate =
            serde_json::from_str(&output).map_err(|_| "invalid published package identity")?;
        if candidate.schema != "openwiz.package-candidate.v1"
            || candidate.target != target
            || version_numbers(&candidate.version).is_none()
            || !hex(&candidate.manifest_sha256, 64)
        {
            return Err("invalid published package identity".to_owned());
        }
        let to = Commit::parse(&candidate.source).ok_or("invalid published source")?;
        if to == self.from
            || state
                .lock()
                .map_err(|_| "service state unavailable")?
                .snapshot()[UPDATE]["to"]
                == to.as_str()
        {
            return Ok(false);
        }
        let mut pending = json!({"at":at,"from":self.from.as_str(),"to":to.as_str(),"phase":"fetch","record_claimed":false});
        write_pending(&self.root, &pending)?;
        let stage = (|| -> Result<(), String> {
            self.executor.run(&Call::new(
                "python3",
                &[
                    script,
                    "stage",
                    target,
                    &candidate.version,
                    to.as_str(),
                    &candidate.manifest_sha256,
                    self.install.to_str().ok_or("installation is not UTF-8")?,
                    self.root.to_str().ok_or("state path is not UTF-8")?,
                ],
                &running,
                &self.from,
            ))?;
            let build = self.root.join("service/builds").join(to.as_str());
            private(&build, true)?;
            private(&build.join("openwiz-service"), false)?;
            let output = self.executor.run(&Call::new(
                build
                    .join("openwiz-service")
                    .to_str()
                    .ok_or("candidate path is not UTF-8")?,
                &["--update-build"],
                &build,
                &to,
            ))?;
            if output != format!("{}\n", to.as_str()) {
                return Err("packaged executable identity mismatch".to_owned());
            }
            Ok(())
        })();
        if stage.is_err() {
            let result = attempt(
                &pending,
                Some(("fetch", "published package verification or staging failed")),
            );
            save_attempt(state, &result)?;
            self.record(&mut pending, &result)?;
            return Ok(false);
        }
        pending["phase"] = json!("queued");
        write_pending(&self.root, &pending)?;
        Ok(true)
    }
    fn git(&self, directory: &Path, args: &[&str], commit: &Commit) -> Result<String, String> {
        let mut fixed = vec![
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.ext.allow=never",
        ];
        fixed.extend_from_slice(args);
        let result = self
            .executor
            .run(&Call::new("git", &fixed, directory, commit));
        normalize(&self.root.join("service/clone"))?;
        result
    }
    fn record(&self, pending: &mut Value, value: &Value) -> Result<(), String> {
        if pending["record_claimed"] == true {
            return Err("update record delivery is uncertain; reconciliation required".to_owned());
        }
        // A crash after claiming is uncertain. Only an explicit guarantee that
        // no request was sent permits us to durably make it retryable again.
        pending["record_claimed"] = json!(true);
        write_pending(&self.root, pending)?;
        match (self.records)(self.issue, &record(value)) {
            Ok(()) => {}
            Err(RecordError::Unsent) => {
                pending["record_claimed"] = json!(false);
                write_pending(&self.root, pending)?;
                return Err("update record was not sent; retry pending".to_owned());
            }
            Err(RecordError::Uncertain) => {
                return Err(
                    "update record delivery is uncertain; reconciliation required".to_owned(),
                );
            }
        }
        fs::remove_file(self.root.join("service/update-pending.json"))
            .map_err(|_| "cannot finish update record")?;
        sync(&self.root.join("service"))
    }
}

fn saved_attempt(state: &Value, pending: &Value) -> Option<Value> {
    let saved = &state[UPDATE];
    ["at", "from", "to"]
        .iter()
        .all(|key| saved[key] == pending[key])
        .then(|| saved.clone())
}

/// Add delivery visibility without changing the historical attempt or state.
pub fn record_status(root: &Path, mut status: Value) -> Result<Value, String> {
    status
        .as_object_mut()
        .ok_or("invalid service status")?
        .remove("update_record");
    let pending = match read_pending(root) {
        Ok(pending) => pending,
        Err(why) => {
            // Successful delivery unlinks the journal. A status read that
            // overlaps that unlink must not treat it as a corrupt journal.
            if fs::symlink_metadata(root.join("service/update-pending.json"))
                .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
            {
                None
            } else {
                return Err(why);
            }
        }
    };
    if let Some(pending) = pending
        && saved_attempt(&status, &pending).is_some()
    {
        let (state, reason) = if pending["record_claimed"] == true {
            (
                "uncertain",
                "Update record delivery is uncertain; reconcile the service issue before clearing the pending journal",
            )
        } else {
            (
                "retrying",
                "Update record was not sent; delivery will retry on the next scheduled check",
            )
        };
        status["update_record"] = json!({"state":state,"reason":reason});
    }
    crate::document::read(crate::document::Document::Status, &status.to_string())
}

fn remove_source(build: &Path) -> Result<(), String> {
    private(build, true)?;
    match fs::remove_dir_all(build.join("source")) {
        Ok(()) => sync(build),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("cannot remove candidate checkout and build caches".to_owned()),
    }
}

fn prune_builds(root: &Path, pending: &Value) -> Result<(), String> {
    let builds = root.join("service/builds");
    private(&builds, true)?;
    for entry in fs::read_dir(&builds).map_err(|_| "cannot list staged builds")? {
        let entry = entry.map_err(|_| "cannot read staged build")?;
        let name = entry.file_name();
        let Some(commit) = name.to_str().and_then(Commit::parse) else {
            continue;
        };
        if commit.as_str() == pending["to"].as_str().unwrap()
            || commit.as_str() == pending["from"].as_str().unwrap()
            || !entry
                .file_type()
                .map_err(|_| "cannot inspect staged build")?
                .is_dir()
        {
            continue;
        }
        // Delete only private, owned commit directories. remove_dir_all never
        // follows a symlink inside an obsolete checkout to an outside target.
        private(&entry.path(), true)?;
        fs::remove_dir_all(entry.path()).map_err(|_| "cannot remove obsolete staged build")?;
    }
    sync(&builds)
}

fn attempt(pending: &Value, failure: Option<(&str, &str)>) -> Value {
    let outcome = match failure {
        Some((step, reason)) => json!({"state":"kept","step":step,"reason":reason}),
        None => json!({"state":"switched"}),
    };
    json!({"at":pending["at"],"from":pending["from"],"to":pending["to"],"outcome":outcome})
}
fn save_attempt(state: &Arc<Mutex<State>>, attempt: &Value) -> Result<(), String> {
    let mut state = state.lock().map_err(|_| "service state unavailable")?;
    let mut next = state.snapshot().clone();
    next[UPDATE] = attempt.clone();
    state.save(next)
}
pub fn record(attempt: &Value) -> String {
    let first = if attempt["outcome"]["state"] == "switched" {
        format!(
            "openwiz-service: update to {}: switched from {}",
            attempt["to"].as_str().unwrap(),
            attempt["from"].as_str().unwrap()
        )
    } else {
        format!(
            "openwiz-service: update to {}: kept {}; the {} failed: {}",
            attempt["to"].as_str().unwrap(),
            attempt["from"].as_str().unwrap(),
            attempt["outcome"]["step"].as_str().unwrap(),
            attempt["outcome"]["reason"].as_str().unwrap()
        )
    };
    let mut data = attempt.clone();
    data["schema"] = json!("openwiz.service-record.v1");
    data["kind"] = json!(UPDATE);
    format!("{first}\n\n```json\n{data}\n```")
}
fn directory(path: &Path) -> Result<(), String> {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .map_err(|_| "cannot create private update directory".to_owned())
}
fn private(path: &Path, dir: bool) -> Result<(), String> {
    let meta = fs::symlink_metadata(path).map_err(|_| "cannot inspect update path")?;
    let uid = openwiz_store::attachments::effective_uid()?;
    if meta.uid() != uid
        || meta.mode() & 0o077 != 0
        || meta.file_type().is_symlink()
        || meta.is_dir() != dir
        || (!dir && (!meta.is_file() || meta.nlink() != 1))
    {
        return Err("update path must be private, owned and have its expected type".to_owned());
    }
    Ok(())
}
fn sync(path: &Path) -> Result<(), String> {
    File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|_| "cannot sync update directory".to_owned())
}
fn write_pending(root: &Path, value: &Value) -> Result<(), String> {
    let path = root.join("service/update-pending.json");
    if fs::symlink_metadata(&path).is_ok() {
        private(&path, false)?;
    }
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let temporary = root.join("service").join(format!(
        ".update-{}-{}.tmp",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    let mut out = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(|_| "cannot create update journal")?;
    let result = (|| -> std::io::Result<()> {
        out.write_all(value.to_string().as_bytes())?;
        out.sync_all()?;
        fs::rename(&temporary, &path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
        return Err("cannot save update journal".to_owned());
    }
    sync(&root.join("service"))
}
fn read_pending(root: &Path) -> Result<Option<Value>, String> {
    use serde::de::{MapAccess, Visitor};
    struct Unique;
    impl<'de> Visitor<'de> for Unique {
        type Value = Value;
        fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str("one strict pending update object")
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
            let mut result = serde_json::Map::new();
            while let Some(key) = map.next_key::<String>()? {
                if result.contains_key(&key) {
                    return Err(serde::de::Error::custom("duplicate pending field"));
                }
                result.insert(key, map.next_value()?);
            }
            Ok(Value::Object(result))
        }
    }
    let path = root.join("service/update-pending.json");
    match fs::symlink_metadata(&path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        _ => private(&path, false)?,
    }
    let mut text = Vec::new();
    File::open(&path)
        .map_err(|_| "cannot read update journal")?
        .take(4097)
        .read_to_end(&mut text)
        .map_err(|_| "cannot read update journal")?;
    if text.len() > 4096 {
        return Err("update journal too large".to_owned());
    }
    let mut decoder = serde_json::Deserializer::from_slice(&text);
    let value = serde::Deserializer::deserialize_map(&mut decoder, Unique)
        .map_err(|_| "invalid update journal")?;
    decoder.end().map_err(|_| "extra update journal data")?;
    if value.as_object().unwrap().len() != 5
        || value["at"].as_u64().is_none()
        || value["record_claimed"].as_bool().is_none()
        || ![
            "fetch", "build", "test", "queued", "launched", "ready", "failed",
        ]
        .contains(&value["phase"].as_str().unwrap_or(""))
        || !["from", "to"]
            .iter()
            .all(|k| value[k].as_str().and_then(Commit::parse).is_some())
        || value["from"] == value["to"]
    {
        return Err("invalid update journal fields".to_owned());
    }
    Ok(Some(value))
}
fn normalize(path: &Path) -> Result<(), String> {
    let meta = fs::symlink_metadata(path).map_err(|_| "cannot inspect clone")?;
    if meta.file_type().is_symlink() {
        return Err("clone symlink refused".to_owned());
    }
    fs::set_permissions(
        path,
        fs::Permissions::from_mode(if meta.is_dir() || meta.mode() & 0o100 != 0 {
            0o700
        } else {
            0o600
        }),
    )
    .map_err(|_| "cannot protect clone")?;
    if meta.is_dir() {
        for child in fs::read_dir(path).map_err(|_| "cannot read clone")? {
            normalize(&child.map_err(|_| "cannot read clone entry")?.path())?;
        }
    }
    Ok(())
}
fn copy_file(source: &Path, to: &Path, mode: u32) -> Result<(), String> {
    if !fs::symlink_metadata(source)
        .map_err(|_| "missing candidate file")?
        .is_file()
    {
        return Err("candidate file must be regular".to_owned());
    }
    let mut input = File::open(source).map_err(|_| "cannot read candidate file")?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .open(to)
        .map_err(|_| "cannot create candidate file")?;
    std::io::copy(&mut input, &mut output).map_err(|_| "cannot stage candidate file")?;
    output
        .sync_all()
        .map_err(|_| "cannot sync candidate file".to_owned())
}
fn copy_web(source: &Path, to: &Path) -> Result<(), String> {
    if !fs::symlink_metadata(source)
        .map_err(|_| "missing candidate web export")?
        .is_dir()
    {
        return Err("web export must be a real directory".to_owned());
    }
    directory(to)?;
    for entry in fs::read_dir(source).map_err(|_| "cannot read candidate web export")? {
        let entry = entry.map_err(|_| "cannot read candidate web entry")?;
        if entry
            .file_type()
            .map_err(|_| "cannot inspect candidate web entry")?
            .is_dir()
        {
            copy_web(&entry.path(), &to.join(entry.file_name()))?;
        } else {
            copy_file(&entry.path(), &to.join(entry.file_name()), 0o600)?;
        }
    }
    sync(to)
}

fn absolute(path: &Path) -> Result<(), String> {
    if path.is_absolute()
        && path
            .components()
            .all(|c| matches!(c, Component::RootDir | Component::Normal(_)))
    {
        Ok(())
    } else {
        Err("update paths must be absolute without . or ..".to_owned())
    }
}

fn installation() -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or("HOME is required for the update installation")?;
    absolute(&home)?;
    Ok(home.join(".local/lib/openwiz"))
}

fn selection(root: &Path, install: &Path, pending: &Value, target: &str) -> Result<(), String> {
    absolute(install)?;
    for path in install.ancestors() {
        if fs::symlink_metadata(path)
            .map_err(|_| "cannot inspect installation ancestors")?
            .file_type()
            .is_symlink()
        {
            return Err("installation has a symlink ancestor".to_owned());
        }
    }
    private(install, true)?;
    let builds = root.join("service/builds");
    private(&builds, true)?;
    let from = builds.join(pending["from"].as_str().unwrap());
    let to = builds.join(pending["to"].as_str().unwrap());
    let link = install.join("current");
    let meta = fs::symlink_metadata(&link).map_err(|_| "missing owner-managed current link")?;
    let uid = openwiz_store::attachments::effective_uid()?;
    let selected = fs::read_link(&link).map_err(|_| "current must be an owner-managed link")?;
    if !meta.file_type().is_symlink() || meta.uid() != uid || (selected != from && selected != to) {
        return Err("current is not the expected owner-managed selection".to_owned());
    }
    let build = builds.join(target);
    private(&build, true)?;
    private(&build.join("openwiz-service"), false)?;
    if selected == build {
        return Ok(());
    }
    let temporary = install.join(format!(".current-{}", std::process::id()));
    std::os::unix::fs::symlink(&build, &temporary).map_err(|_| "cannot create new selection")?;
    if fs::rename(&temporary, &link).is_err() {
        let _ = fs::remove_file(&temporary);
        return Err("cannot select candidate".to_owned());
    }
    sync(install)
}

/// Startup transaction resumed only by the process holding the runtime lock.
pub struct Startup {
    updater: Option<Updater>,
    pending: Option<Value>,
    confirmed: Arc<(Mutex<bool>, std::sync::Condvar)>,
}
impl Startup {
    /// S8 is checked against a prospective result without prematurely saving it.
    pub fn preview(&self, state: &State) -> Value {
        let mut value = state.snapshot().clone();
        if let Some(pending) = &self.pending {
            value[UPDATE] = attempt(pending, None);
        }
        value
    }
    /// Called after HTTP health and the existing status socket are ready.
    pub fn confirm(&mut self, state: &mut State, port: u16) -> Result<(), String> {
        let Some(pending) = self.pending.as_mut() else {
            return Ok(());
        };
        let updater = self.updater.as_ref().unwrap();
        let (lock, wake) = &*self.confirmed;
        let mut confirmed = lock
            .lock()
            .map_err(|_| "candidate confirmation unavailable")?;
        probe(port)?;
        let result = attempt(pending, None);
        selection(
            &updater.root,
            &updater.install,
            pending,
            pending["to"].as_str().unwrap(),
        )?;
        let mut next = state.snapshot().clone();
        next[UPDATE] = result.clone();
        if state.save(next).is_err() {
            selection(
                &updater.root,
                &updater.install,
                pending,
                pending["from"].as_str().unwrap(),
            )?;
            return Err("cannot save candidate confirmation".to_owned());
        }
        pending["phase"] = json!("ready");
        write_pending(&updater.root, pending)?;
        *confirmed = true;
        wake.notify_one();
        if prune_builds(&updater.root, pending).is_err() {
            eprintln!("openwiz-service: obsolete build cleanup did not finish");
        }
        // The candidate already runs. An uncertain comment cannot turn its
        // historical confirmation into a kept result, or cause a duplicate.
        if updater.record(pending, &result).is_err() {
            eprintln!("openwiz-service: update record delivery pending; private journal retained");
        }
        Ok(())
    }
}

pub fn recover(
    root: &Path,
    config: &Value,
    build: &str,
    state: &mut State,
) -> Result<Startup, String> {
    let confirmed = Arc::new((Mutex::new(false), std::sync::Condvar::new()));
    let mut startup = Startup {
        updater: None,
        pending: None,
        confirmed: Arc::clone(&confirmed),
    };
    let Some(mut pending) = read_pending(root)? else {
        return Ok(startup);
    };
    let install = installation()?;
    let records = configured_records(root, config)?;
    let updater = Updater::production(root, &install, config, build, records)?;
    let from = pending["from"].as_str().unwrap().to_owned();
    let to = pending["to"].as_str().unwrap().to_owned();
    if build != from && build != to {
        return Err("running build does not belong to the pending attempt".to_owned());
    }
    let actual = std::env::current_exe().map_err(|_| "cannot identify running program")?;
    if actual
        != root
            .join("service/builds")
            .join(build)
            .join("openwiz-service")
    {
        return Err("pending update requires its exact staged program".to_owned());
    }
    if pending["phase"] == "queued" && build == from {
        selection(root, &install, &pending, &from)?;
        let candidate = root
            .join("service/builds")
            .join(&to)
            .join("openwiz-service");
        let launch = (|| -> Result<Command, String> {
            private(candidate.parent().unwrap(), true)?;
            private(&candidate, false)?;
            let call = Call::new(
                candidate.to_str().ok_or("candidate path is not UTF-8")?,
                &[],
                &std::env::current_dir()
                    .map_err(|_| "cannot retain the service repository directory")?,
                &Commit::parse(&to).unwrap(),
            );
            validated_command(&call)
        })();
        // exec preserves the service's unit identity; close-on-exec releases
        // the old lock/socket descriptors. The unit still supervises one process.
        if let Ok(mut program) = launch {
            pending["phase"] = json!("launched");
            write_pending(root, &pending)?;
            let _ = program.exec();
        }
        pending["phase"] = json!("failed");
        write_pending(root, &pending)?;
    }
    if build == to && pending["phase"] == "launched" {
        // Confirmation may have selected us before a crash without saving ready.
        // Keep the next unit restart safe even if this process exits first.
        selection(root, &install, &pending, &from)?;
        let watch_root = root.to_owned();
        let watch_install = install.clone();
        let watch_pending = pending.clone();
        std::thread::spawn(move || {
            let (lock, wake) = &*confirmed;
            let Ok(flag) = lock.lock() else {
                return;
            };
            let Ok((flag, _)) =
                wake.wait_timeout_while(flag, Duration::from_secs(30), |ready| !*ready)
            else {
                return;
            };
            if !*flag {
                let mut pending = watch_pending;
                pending["phase"] = json!("failed");
                let _ = selection(
                    &watch_root,
                    &watch_install,
                    &pending,
                    pending["from"].as_str().unwrap(),
                );
                let _ = write_pending(&watch_root, &pending);
                std::process::exit(1);
            }
        });
        startup.updater = Some(updater);
        startup.pending = Some(pending);
        return Ok(startup);
    }
    if build == to && pending["phase"] == "ready" {
        let result = saved_attempt(state.snapshot(), &pending)
            .ok_or("confirmed update has no matching saved attempt")?;
        if pending["record_claimed"] == false && updater.record(&mut pending, &result).is_err() {
            eprintln!("openwiz-service: update record delivery pending; private journal retained");
        }
        if prune_builds(root, &pending).is_err() {
            eprintln!("openwiz-service: obsolete build cleanup did not finish");
        }
        return Ok(startup);
    }
    if build == from {
        selection(root, &install, &pending, &from)?;
        let phase = pending["phase"].as_str().unwrap();
        if matches!(phase, "build" | "test") {
            let candidate = root.join("service/builds").join(&to);
            if candidate.exists() && remove_source(&candidate).is_err() {
                eprintln!(
                    "openwiz-service: candidate checkout and build cache cleanup did not finish"
                );
            }
        }
        let step = if matches!(phase, "fetch" | "build" | "test") {
            phase
        } else {
            "switch"
        };
        let result = saved_attempt(state.snapshot(), &pending)
            // A saved success is provisional until the ready journal is durable.
            .filter(|saved| phase == "ready" || saved["outcome"]["state"] != "switched")
            .unwrap_or_else(|| {
                attempt(
                    &pending,
                    Some((
                        step,
                        "candidate did not confirm readiness; previous build restored",
                    )),
                )
            });
        let mut value = state.snapshot().clone();
        value[UPDATE] = result.clone();
        state.save(value)?;
        if pending["record_claimed"] != true && updater.record(&mut pending, &result).is_err() {
            eprintln!("openwiz-service: update record delivery pending; private journal retained");
        }
        return Ok(startup);
    }
    Err("candidate startup has an invalid pending phase".to_owned())
}

fn probe(port: u16) -> Result<(), String> {
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};
    let mut stream = TcpStream::connect_timeout(
        &SocketAddr::from((Ipv4Addr::LOCALHOST, port)),
        Duration::from_secs(2),
    )
    .map_err(|_| "candidate health refused")?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| "cannot bound candidate health")?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| "cannot bound candidate health")?;
    stream
        .write_all(
            format!(
                "GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            )
            .as_bytes(),
        )
        .map_err(|_| "candidate health request failed")?;
    let mut response = String::new();
    stream
        .take(4097)
        .read_to_string(&mut response)
        .map_err(|_| "candidate health timed out")?;
    let (head, body) = response
        .split_once("\r\n\r\n")
        .ok_or("candidate health malformed")?;
    let body: Value = serde_json::from_str(body).map_err(|_| "candidate health malformed")?;
    if !head.starts_with("HTTP/1.1 200 ") || body["server"]["name"] != "openwiz-server" {
        return Err("candidate health wrong answer".to_owned());
    }
    Ok(())
}

/// One independent registration, retaining every job supplied by other tickets.
pub fn register(
    root: &Path,
    config: &Value,
    build: &str,
    state: Arc<Mutex<State>>,
    scheduler: &mut crate::scheduler::Scheduler,
    restart: Arc<std::sync::atomic::AtomicBool>,
) -> Result<(), String> {
    let root = root.to_owned();
    let config = config.clone();
    let build = build.to_owned();
    scheduler
        .register(
            "self-update",
            std::num::NonZeroU64::new(300).unwrap(),
            move || {
                let Ok(records) = configured_records(&root, &config) else {
                    return;
                };
                let result = installation()
                    .and_then(|install| {
                        Updater::production(&root, &install, &config, &build, records)
                    })
                    .and_then(|updater| updater.check(&state, crate::runtime::now()));
                match result {
                    Ok(true) => restart.store(true, std::sync::atomic::Ordering::SeqCst),
                    Err(_) => eprintln!(
                        "openwiz-service: self-update could not finish; old build retained"
                    ),
                    Ok(false) => {}
                }
            },
        )
        .map_err(str::to_owned)
}

#[cfg(all(test, target_os = "linux"))]
#[path = "../../../tests/service/install_engine_record_factory.rs"]
mod record_factory_tests;
