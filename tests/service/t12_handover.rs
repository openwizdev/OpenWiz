//! T12 (#2379): the packaged startup gate and the completion verifier seam.
//!
//! Bootstrap proofs run the real built `openwiz-service` from a synthetic
//! installed layout. Completion proofs drive the real controlled tick against
//! an in-memory GitHub executor and a `sh` room-cli fake. Every identity,
//! hash, comment and thread is synthetic. Fixture tests never prove live
//! behaviour: positive packaged handover and completion remain unverified.
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{process::Executor, tick::TickReads};
use openwiz_cli::fleet::tick::{self as cli, Args, Context, Control};
use openwiz_core::fleet::tick::Detail;
use openwiz_core::messaging::sha256_hex;
use serde_json::{Value, json};
use std::{
    fs::{self, DirBuilder},
    os::unix::fs::{DirBuilderExt, MetadataExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        Arc, Mutex, OnceLock,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

#[path = "../fixture-entrypoints/fixture.rs"]
mod fixture;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
const SOURCE: &str = "1212121212121212121212121212121212121212";
const HELD: &str = "completion verification is unavailable; orchestrator judgment required";

struct Temp(PathBuf);
impl Temp {
    fn new(kind: &str) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "openwiz-t12-{kind}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
        // fixture::Bundle keeps its discovery root beside the room-cli's folder.
        let _ = fs::remove_dir_all(self.0.with_extension("fixture-bundles"));
    }
}
fn private_dir(path: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
fn private_file(path: &Path, data: &[u8], mode: u32) {
    fs::write(path, data).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
}

fn service_binary() -> &'static Path {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    BUILT.get_or_init(|| {
        let out = Command::new(env!("CARGO"))
            .args([
                "build",
                "-p",
                "openwiz-service",
                "--bin",
                "openwiz-service",
                "--locked",
            ])
            .current_dir(ROOT)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        Path::new(env!("CARGO_TARGET_TMPDIR"))
            .parent()
            .unwrap()
            .join("debug/openwiz-service")
    })
}

/// The installer's own required asset list, read from the real installer.
fn required_assets() -> Vec<String> {
    let out = Command::new("/usr/bin/python3")
        .args([
            "-I",
            "-c",
            "import json,sys;sys.path.insert(0,sys.argv[1]);import install;print(json.dumps(sorted(install.REQUIRED)))",
        ])
        .arg(Path::new(ROOT).join("tools/install"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
fn python(args: &[&std::ffi::OsStr]) -> Value {
    let out = Command::new("/usr/bin/python3")
        .arg("-I")
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
fn service_config() -> Value {
    json!({"schema":"openwiz.service-config.v1",
        "repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
        "project":"prj_syn_0001","orchestrator_thread":"thr_syn_0001",
        "service_issue":9001,"github_app":{"app_id":31,"installation_id":42},
        "tick":{"every_s":300},"health":{"every_s":60},
        "server":{"port":7370,"allowed_host":null,"probe_timeout_s":10}})
}

/// An installer-valid package, installed by the real installer, selecting one
/// build, with T9's applied journal and a held run lock so that an admitted
/// start stops right after the gate.
struct Installed {
    temp: Temp,
    root: PathBuf,
    state: PathBuf,
    build: PathBuf,
    _lock: fs::File,
}
impl Installed {
    fn new() -> Self {
        let temp = Temp::new("install");
        let web = temp.0.join("web");
        private_dir(&web);
        for page in ["index.html", "setup.html"] {
            private_file(&web.join(page), b"<p>Synthetic setup.</p>", 0o600);
        }
        let tools = Path::new(ROOT).join("tools/install");
        let bundle = python(&[
            tools.join("fixture_bundle.py").as_os_str(),
            "--output".as_ref(),
            temp.0.join("bundle").as_os_str(),
            "--server".as_ref(),
            service_binary().as_os_str(),
            "--service".as_ref(),
            service_binary().as_os_str(),
            "--web".as_ref(),
            web.as_os_str(),
            "--source".as_ref(),
            SOURCE.as_ref(),
        ]);
        let root = temp.0.join("root");
        python(&[
            tools.join("install.py").as_os_str(),
            "--manifest".as_ref(),
            bundle["manifest"].as_str().unwrap().as_ref(),
            "--archive".as_ref(),
            bundle["archive"].as_str().unwrap().as_ref(),
            "--manifest-sha256".as_ref(),
            bundle["checksum"].as_str().unwrap().as_ref(),
            "--root".as_ref(),
            root.as_os_str(),
            "--target".as_ref(),
            "x86_64-unknown-linux-gnu".as_ref(),
        ]);
        let state = root.join("state");
        let build = state.join("service/builds").join(SOURCE);
        private_dir(&state.join("setup"));
        private_file(
            &state.join("service/config.json"),
            service_config().to_string().as_bytes(),
            0o600,
        );
        let lock = state.join("service/run.lock");
        private_file(&lock, b"", 0o600);
        let lock = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(lock)
            .unwrap();
        lock.try_lock().unwrap();
        let installed = Self {
            temp,
            root,
            state,
            build,
            _lock: lock,
        };
        installed.journal(|_| {});
        installed
    }
    fn manifest(&self, change: impl FnOnce(&mut Value)) {
        let path = self.build.join("install-manifest.json");
        let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        change(&mut value);
        private_file(&path, value.to_string().as_bytes(), 0o600);
    }
    /// T9's applied journal with a binding that matches this installation.
    fn journal(&self, change: impl FnOnce(&mut Value)) {
        self.write_journal(change, false);
    }
    /// The same, with request/operation hashes recomputed after the change,
    /// so only the changed binding or state field can cause a refusal.
    fn rehashed(&self, change: impl FnOnce(&mut Value)) {
        self.write_journal(change, true);
    }
    fn write_journal(&self, change: impl FnOnce(&mut Value), rehash: bool) {
        let uid = fs::metadata("/proc/self").unwrap().uid();
        let config = fs::read(self.state.join("service/config.json")).unwrap();
        let binding = json!({"owner_uid":uid,"unit":"openwiz.service",
            "root":self.root.to_str().unwrap(),"state_root":self.state.to_str().unwrap(),
            "repository":"synthetic-owner/synthetic-repo","project":"prj_syn_0001",
            "runtime":format!("0.0.99 {SOURCE}"),"build":SOURCE,
            "config_sha256":sha256_hex(&config),"unit_sha256":"b".repeat(64),
            "app_id":31,"installation_id":42,"service_issue":9001});
        let hash = sha256_hex(
            json!({"kind":"activate_engine","request":{"binding":binding,"revision":1}})
                .to_string()
                .as_bytes(),
        );
        let operation = "c".repeat(32);
        let mut value = json!({"schema":"openwiz.pc-activation.v1.journal",
            "request":{"schema":"openwiz.pc-activation.v1","host":"pc","action":"enable_start",
                "operation_id":operation,"binding":binding,"revision":1,"request_hash":hash},
            "operation":{"operation_id":operation,"kind":"activate_engine","phase":"applied",
                "fingerprint":hash,"effects":["Enable and start the owner user unit openwiz.service."],
                "reason":"Reconcile the exact PC activation and App record before continuing."},
            "created_at":5000,"updated_at":5001,"started_at":5000,"record_at":5000,
            "record_state":"confirmed","outcome":"applied"});
        change(&mut value);
        if rehash {
            let hash = sha256_hex(
                json!({"kind":"activate_engine","request":{"binding":value["request"]["binding"],"revision":value["request"]["revision"]}})
                    .to_string()
                    .as_bytes(),
            );
            value["request"]["request_hash"] = json!(hash);
            value["operation"]["fingerprint"] = json!(hash);
        }
        private_file(
            &self.state.join("setup/pc-activation.json"),
            value.to_string().as_bytes(),
            0o600,
        );
    }
    /// Runs the installed program; returns its stderr once it has exited.
    fn start(&self) -> String {
        self.start_with(&self.state)
    }
    fn start_with(&self, state: &Path) -> String {
        let mut child = Command::new(self.build.join("openwiz-service"))
            .env_clear()
            .env("HOME", &self.temp.0)
            .env("OPENWIZ_STATE_DIR", state)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let until = Instant::now() + Duration::from_secs(30);
        while child.try_wait().unwrap().is_none() {
            if Instant::now() > until {
                child.kill().unwrap();
                panic!("installed service kept running past its startup gate");
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let out = child.wait_with_output().unwrap();
        assert!(!out.status.success(), "the held run lock must stop startup");
        String::from_utf8(out.stderr).unwrap()
    }
}
fn refused(stderr: &str) -> bool {
    stderr.contains("Activation remains closed") && !stderr.contains("handover verified")
}
fn admitted(stderr: &str) -> bool {
    stderr.contains("openwiz-service: installed handover verified; login: unknown")
        && !stderr.contains("Activation remains closed")
}

#[test]
fn packaged_start_passes_only_with_verified_manifest_and_applied_activation() {
    let installed = Installed::new();
    let stderr = installed.start();
    assert!(admitted(&stderr), "{stderr}");
}

#[test]
fn packaged_start_refuses_missing_or_uncertain_activation_and_reports_login_unknown() {
    let installed = Installed::new();
    for (name, change) in [
        (
            "uncertain",
            Box::new(|v: &mut Value| {
                v["operation"]["phase"] = json!("uncertain");
                v["outcome"] = json!("held");
                v["record_state"] = json!("pending");
            }) as Box<dyn Fn(&mut Value)>,
        ),
        (
            "unconfirmed record",
            Box::new(|v: &mut Value| {
                v["record_state"] = json!("uncertain");
                v["outcome"] = json!("held");
            }),
        ),
        (
            "other build",
            Box::new(|v: &mut Value| {
                v["request"]["binding"]["build"] = json!("3".repeat(40));
            }),
        ),
        (
            "other state",
            Box::new(|v: &mut Value| {
                v["request"]["binding"]["state_root"] = json!("/synthetic/other");
            }),
        ),
        (
            "applied without a confirmed record",
            Box::new(|v: &mut Value| {
                v["record_state"] = json!("uncertain");
            }),
        ),
        (
            "tampered binding",
            Box::new(|v: &mut Value| {
                v["request"]["binding"]["project"] = json!("prj_syn_other");
            }),
        ),
        (
            "unknown field",
            Box::new(|v: &mut Value| {
                v["synthetic"] = json!(true);
            }),
        ),
        (
            "string time",
            Box::new(|v: &mut Value| {
                v["started_at"] = json!("5000");
            }),
        ),
    ] {
        if name == "tampered binding" {
            installed.journal(change);
        } else {
            installed.rehashed(change);
        }
        let stderr = installed.start();
        assert!(refused(&stderr), "{name}: {stderr}");
        assert!(stderr.contains("login: unknown"), "{name}: {stderr}");
    }
    fs::remove_file(installed.state.join("setup/pc-activation.json")).unwrap();
    assert!(refused(&installed.start()), "absent journal");
    installed.journal(|_| {});
    let path = installed.state.join("setup/pc-activation.json");
    let text = fs::read_to_string(&path).unwrap();
    private_file(
        &path,
        text.replacen("{", r#"{"outcome":"applied","#, 1).as_bytes(),
        0o600,
    );
    assert!(refused(&installed.start()), "duplicate key");
    installed.journal(|_| {});
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(refused(&installed.start()), "shared journal");
    installed.journal(|_| {});
    assert!(admitted(&installed.start()));
}

#[test]
fn packaged_start_refuses_changed_config_selection_or_installed_assets() {
    let installed = Installed::new();
    let config = installed.state.join("service/config.json");
    let mut changed = service_config();
    changed["server"]["port"] = json!(7371);
    private_file(&config, changed.to_string().as_bytes(), 0o600);
    assert!(refused(&installed.start()), "changed config");
    installed.journal(|_| {});
    assert!(admitted(&installed.start()));
    let current = installed.root.join("current");
    fs::remove_file(&current).unwrap();
    std::os::unix::fs::symlink(installed.temp.0.join("elsewhere"), &current).unwrap();
    assert!(refused(&installed.start()), "foreign selection");
    fs::remove_file(&current).unwrap();
    std::os::unix::fs::symlink(&installed.build, &current).unwrap();
    let identity = installed.build.join("runtime/openwiz-build.txt");
    let original = fs::read(&identity).unwrap();
    let mut same_length = original.clone();
    same_length[0] ^= 1;
    private_file(&identity, &same_length, 0o600);
    assert!(refused(&installed.start()), "same-length tampered asset");
    private_file(&identity, b"tampered\n", 0o600);
    assert!(refused(&installed.start()), "tampered asset");
    fs::remove_file(&identity).unwrap();
    assert!(refused(&installed.start()), "missing asset");
    private_file(&identity, &original, 0o600);
    assert!(admitted(&installed.start()));
    private_file(
        &installed.build.join("runtime/extra.txt"),
        b"unlisted\n",
        0o600,
    );
    assert!(refused(&installed.start()), "unlisted asset");
}

#[test]
fn packaged_start_refuses_a_runtime_state_other_than_the_activated_one() {
    // R1: the service runs with OPENWIZ_STATE_DIR; that exact state must be the
    // activated installation's, never another state beside an applied one.
    let installed = Installed::new();
    let other = installed.temp.0.join("other-state");
    for dir in [&other, &other.join("service"), &other.join("setup")] {
        private_dir(dir);
    }
    for file in ["service/config.json", "setup/pc-activation.json"] {
        private_file(
            &other.join(file),
            &fs::read(installed.state.join(file)).unwrap(),
            0o600,
        );
    }
    // Hold its run lock too: a regression stops at "already running", never serves.
    private_file(&other.join("service/run.lock"), b"", 0o600);
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(other.join("service/run.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    let stderr = installed.start_with(&other);
    assert!(refused(&stderr), "{stderr}");
    assert!(admitted(&installed.start()));
}

#[test]
fn packaged_start_enforces_every_t9_journal_invariant() {
    // R2: the same journal shape and bounds T9's reader enforces.
    let installed = Installed::new();
    for (name, change) in [
        (
            "null record time",
            Box::new(|v: &mut Value| v["record_at"] = Value::Null) as Box<dyn Fn(&mut Value)>,
        ),
        (
            "absent record time",
            Box::new(|v: &mut Value| {
                v.as_object_mut().unwrap().remove("record_at");
            }),
        ),
        (
            "absent start time",
            Box::new(|v: &mut Value| {
                v.as_object_mut().unwrap().remove("started_at");
            }),
        ),
        (
            "zero creation",
            Box::new(|v: &mut Value| v["created_at"] = json!(0)),
        ),
        (
            "update before creation",
            Box::new(|v: &mut Value| v["updated_at"] = json!(4999)),
        ),
        (
            "start after update",
            Box::new(|v: &mut Value| v["started_at"] = json!(5002)),
        ),
        (
            "record before creation",
            Box::new(|v: &mut Value| v["record_at"] = json!(4999)),
        ),
        (
            "unsafe time",
            Box::new(|v: &mut Value| v["updated_at"] = json!(9_007_199_254_740_992_u64)),
        ),
        (
            "other effects",
            Box::new(|v: &mut Value| v["operation"]["effects"] = json!(["Synthetic effect."])),
        ),
        (
            "other reason",
            Box::new(|v: &mut Value| v["operation"]["reason"] = json!("Synthetic reason.")),
        ),
        (
            "other operation",
            Box::new(|v: &mut Value| v["operation"]["operation_id"] = json!("d".repeat(32))),
        ),
        (
            "short operation id",
            Box::new(|v: &mut Value| {
                v["operation"]["operation_id"] = json!("c".repeat(31));
                v["request"]["operation_id"] = json!("c".repeat(31));
            }),
        ),
        (
            "unsafe app id",
            Box::new(|v: &mut Value| v["request"]["binding"]["app_id"] = json!(0)),
        ),
        (
            "dot path",
            Box::new(|v: &mut Value| {
                let root = v["request"]["binding"]["root"].as_str().unwrap().to_owned();
                v["request"]["binding"]["root"] = json!(format!("{root}/./"));
            }),
        ),
    ] {
        installed.rehashed(change);
        let stderr = installed.start();
        assert!(refused(&stderr), "{name}: {stderr}");
    }
    installed.journal(|_| {});
    assert!(admitted(&installed.start()));
}

#[test]
fn packaged_start_requires_an_installer_valid_manifest() {
    // R3: the installer's manifest contract, not only the listed hashes.
    let installed = Installed::new();
    let path = installed.build.join("install-manifest.json");
    let original = fs::read(&path).unwrap();
    for (name, change) in [
        (
            "foreign target",
            Box::new(|v: &mut Value| v["target"] = json!("foreign-target"))
                as Box<dyn Fn(&mut Value)>,
        ),
        (
            "setup API",
            Box::new(|v: &mut Value| v["setup_api"] = json!(99)),
        ),
        (
            "bundle name",
            Box::new(|v: &mut Value| v["archive"] = json!("bundle.zip")),
        ),
        (
            "bundle hash",
            Box::new(|v: &mut Value| v["archive_sha256"] = json!("z")),
        ),
        (
            "bundle size",
            Box::new(|v: &mut Value| v["archive_bytes"] = json!(0)),
        ),
        (
            "version",
            Box::new(|v: &mut Value| v["version"] = json!("1.0.0")),
        ),
        (
            "empty assets",
            Box::new(|v: &mut Value| v["assets"] = json!([])),
        ),
    ] {
        installed.manifest(change);
        assert!(refused(&installed.start()), "{name}");
        private_file(&path, &original, 0o600);
    }
    assert!(admitted(&installed.start()));
    for required in required_assets() {
        let manifest: Value = serde_json::from_slice(&original).unwrap();
        installed.manifest(|v| {
            v["assets"]
                .as_array_mut()
                .unwrap()
                .retain(|a| a["path"] != required.as_str());
        });
        let file = installed.build.join(&required);
        let saved = fs::read(&file).unwrap();
        if required != "openwiz-service" {
            fs::remove_file(&file).unwrap();
        }
        assert!(refused(&installed.start()), "without {required}");
        if required != "openwiz-service" {
            let mode = manifest["assets"]
                .as_array()
                .unwrap()
                .iter()
                .find(|a| a["path"] == required.as_str())
                .unwrap()["mode"]
                .as_str()
                .unwrap()
                .to_owned();
            private_file(&file, &saved, u32::from_str_radix(&mode, 8).unwrap());
        }
        private_file(&path, &original, 0o600);
    }
    // A consistently relisted build stamp for another version is still refused.
    let stamp = installed.build.join("runtime/openwiz-build.txt");
    let saved = fs::read(&stamp).unwrap();
    let other = format!("openwiz.package.v1\n0.0.98\n{SOURCE}\nx86_64-unknown-linux-gnu\n");
    private_file(&stamp, other.as_bytes(), 0o600);
    installed.manifest(|v| {
        for asset in v["assets"].as_array_mut().unwrap() {
            if asset["path"] == "runtime/openwiz-build.txt" {
                asset["sha256"] = json!(sha256_hex(other.as_bytes()));
                asset["bytes"] = json!(other.len());
            }
        }
    });
    assert!(refused(&installed.start()), "relabelled build stamp");
    // An unsupported target with consistently relabelled stamps is refused too.
    let foreign = format!("openwiz.package.v1\n0.0.99\n{SOURCE}\nforeign-target\n");
    let web = installed.build.join("web/openwiz-build.txt");
    let web_saved = fs::read(&web).unwrap();
    private_file(&stamp, foreign.as_bytes(), 0o600);
    private_file(&web, foreign.as_bytes(), 0o600);
    private_file(&path, &original, 0o600);
    installed.manifest(|v| {
        v["target"] = json!("foreign-target");
        for asset in v["assets"].as_array_mut().unwrap() {
            if asset["path"] == "runtime/openwiz-build.txt"
                || asset["path"] == "web/openwiz-build.txt"
            {
                asset["sha256"] = json!(sha256_hex(foreign.as_bytes()));
                asset["bytes"] = json!(foreign.len());
            }
        }
    });
    assert!(
        refused(&installed.start()),
        "foreign target, consistent stamps"
    );
    private_file(&web, &web_saved, 0o600);
    private_file(&stamp, &saved, 0o600);
    private_file(&path, &original, 0o600);
    assert!(admitted(&installed.start()));
}

#[test]
fn packaged_start_compares_every_config_identity_with_the_binding() {
    // R4: each rehashed binding mismatch refuses on its own; so does an
    // invalid config whose exact bytes the binding hashes.
    let installed = Installed::new();
    for (field, value) in [
        ("repository", json!("synthetic-owner/other-repo")),
        ("project", json!("prj_syn_other")),
        ("app_id", json!(32)),
        ("installation_id", json!(43)),
        ("service_issue", json!(9002)),
    ] {
        installed.rehashed(|v| v["request"]["binding"][field] = value.clone());
        assert!(refused(&installed.start()), "{field}");
    }
    let config = installed.state.join("service/config.json");
    private_file(&config, br#"{"synthetic":"not a service document"}"#, 0o600);
    installed.journal(|_| {});
    assert!(refused(&installed.start()), "invalid bound config");
    private_file(&config, service_config().to_string().as_bytes(), 0o600);
    installed.journal(|_| {});
    assert!(admitted(&installed.start()));
}

#[test]
fn packaged_start_requires_a_private_plain_installation_root() {
    // R5: the installer's root privacy and plain ancestry, then `current`.
    let installed = Installed::new();
    fs::set_permissions(&installed.root, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(refused(&installed.start()), "shared root");
    fs::set_permissions(&installed.root, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(admitted(&installed.start()));
    let alias = installed.temp.0.join("alias");
    std::os::unix::fs::symlink(&installed.temp.0, &alias).unwrap();
    let through = alias.join("root");
    installed.rehashed(|v| v["request"]["binding"]["root"] = json!(through.to_str().unwrap()));
    assert!(refused(&installed.start()), "symlinked root ancestor");
}

#[test]
fn source_deployment_keeps_its_prior_startup_path() {
    let temp = Temp::new("source");
    let build = temp.0.join("build");
    private_dir(&build);
    let program = build.join("openwiz-service");
    private_file(&program, &fs::read(service_binary()).unwrap(), 0o700);
    let state = temp.0.join("state");
    private_dir(&state);
    let out = Command::new(&program)
        .env_clear()
        .env("HOME", &temp.0)
        .env("OPENWIZ_STATE_DIR", &state)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(!out.status.success());
    assert!(
        !stderr.contains("Activation remains closed") && !stderr.contains("handover"),
        "{stderr}"
    );
}

// ---- completion verifier seam ----

fn completion_world(dir: &Path, summarized: bool) {
    let link = |ns: &[u64]| json!({"nodes":ns.iter().map(|n| json!({"id":format!("syn-issue-{n}"),"number":n,"state":"CLOSED","title":format!("Synthetic ticket {n}"),"url":format!("https://example.invalid/issues/{n}")})).collect::<Vec<_>>(),"totalCount":ns.len()});
    let ready = json!([{"id":"syn-label-ready-for-agent","name":"ready-for-agent","description":"Synthetic","color":"ffffff"}]);
    let issues = [
        (9, "Synthetic graph", "Synthetic graph", vec![], vec![10, 11]),
        (
            10,
            "Synthetic ticket 10",
            "**Owned paths:** `crates/example/one.rs`\n**Relies on:** nothing",
            vec![],
            vec![],
        ),
        (
            11,
            "Synthetic ticket 11",
            "**Owned paths:** `crates/example/two.rs`\n**Relies on:** nothing",
            vec![10],
            vec![],
        ),
    ]
    .map(|(n, title, body, blockers, subs)| json!({"blockedBy":link(&blockers),"body":body,"id":format!("syn-issue-{n}"),"labels":if n == 9 {json!([])} else {ready.clone()},"milestone":null,"number":n,"state":if n == 9 {"OPEN"} else {"CLOSED"},"subIssues":link(&subs),"title":title}));
    let mut comments = vec![
        json!({"id":100,"body":include_str!("fixtures/t4-completion-approval.md"),"created":1_793_400_000_000_u64,"updated":1_793_400_000_000_u64}),
    ];
    if summarized {
        comments.push(json!({"id":101,"body":"launch-fleet: spec summary: synthetic","created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64}));
    }
    fs::write(
        dir.join("world.json"),
        json!({"issues":issues,"comments":comments}).to_string(),
    )
    .unwrap();
    fs::write(dir.join("rules.md"), "## Builder\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Synthetic | `--model syn-builder` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude | `--provider claude-code` |\n| Model | Synthetic | `--model syn-reviewer` |\n| Effort | High | `--reasoning-level high` |\n## CI checks\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `rust` | tests | `main` |\n## Standing merge rules\n| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| A ticket in an approved plan graph | reviewer | The loop, as soon as the reviewer's APPROVE names that exact commit |\n## Builder for small tickets\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Synthetic small | `--model syn-small` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer for Claude-built\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Synthetic reviewer | `--model syn-reviewer` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer for GPT-built\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude | `--provider claude-code` |\n| Model | Synthetic reviewer | `--model syn-reviewer` |\n| Effort | High | `--reasoning-level high` |\n").unwrap();
    let quoted = dir.to_str().unwrap().replace('\'', "'\\''");
    let room = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{quoted}/room-calls.log'\ncase \"$*\" in\n--version) echo v127 ;;\n'project list'*) echo '[{{\"id\":\"prj_syn_0001\",\"kind\":\"standard\",\"name\":\"Synthetic project\",\"gitRemoteUrl\":\"https://github.com/synthetic-owner/synthetic-repo.git\",\"createdAt\":1700000000000,\"updatedAt\":1700000000000,\"sources\":[]}}]' ;;\n'thread list'*) echo '[]' ;;\n'thread show thr_syn_0001 --json') cat '{quoted}/thread.json' ;;\n'thread tell thr_syn_0001 '*) echo '{{\"threadId\":\"thr_syn_0001\",\"ok\":true,\"delivery\":\"sent\",\"mode\":\"queue\"}}' ;;\n*) exit 99 ;;\nesac\n"
    );
    let mut thread: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-v127/new-thread/thread-show-active.json"
    ))
    .unwrap();
    thread["thread"]["id"] = json!("thr_syn_0001");
    thread["thread"]["archivedAt"] = Value::Null;
    fs::write(dir.join("thread.json"), thread.to_string()).unwrap();
    private_file(&dir.join("room-cli"), room.as_bytes(), 0o700);
    private_dir(&dir.join("state"));
}

/// The in-memory recording GitHub of `world.json`, never a real endpoint.
fn github(dir: PathBuf) -> TickReads {
    let lock = Arc::new(Mutex::new(()));
    TickReads::with_executor(Executor::supplied(Arc::new(move |call, _| {
        let _held = lock.lock().unwrap();
        let args: Vec<&str> = call.argv().iter().map(String::as_str).collect();
        let mut calls = fs::read_to_string(dir.join("gh-calls.log")).unwrap_or_default();
        calls.push_str(&format!("{}\n", json!(args)));
        fs::write(dir.join("gh-calls.log"), calls).unwrap();
        let mut world: Value =
            serde_json::from_slice(&fs::read(dir.join("world.json")).unwrap()).unwrap();
        let url = "https://github.invalid/synthetic-owner/synthetic-repo/issues/9";
        let view = |world: &Value| json!({"comments":world["comments"].as_array().unwrap().iter().map(|c| json!({"id":format!("syn-comment-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2026-10-30T00:00:00Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("{url}#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()});
        let answer = match &args[..] {
            ["repo", "view", ..] => {
                json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"})
            }
            ["issue", "list", ..] => world["issues"].clone(),
            ["pr", "list", ..] => json!([]),
            ["api", path, ..] => {
                let path = path.strip_prefix("repos/{owner}/{repo}/").unwrap_or("");
                if path.starts_with("git/ref/heads/") {
                    json!({"sha":"a".repeat(40)})
                } else if path.starts_with("contents/docs/agents/fleet.md") {
                    let rules = fs::read_to_string(dir.join("rules.md")).unwrap();
                    return Ok(format!("{rules}\n").into_bytes());
                } else if path.starts_with("issues/comments?") {
                    let mut rows = world["comments"].clone();
                    for row in rows.as_array_mut().unwrap() {
                        row["issue_url"] = json!(
                            "https://github.invalid/api/v3/repos/synthetic-owner/synthetic-repo/issues/9"
                        );
                    }
                    rows
                } else if path.starts_with("issues/9/comments?") {
                    world["comments"].clone()
                } else if path.contains("/comments?") || path.contains("/timeline?") {
                    json!([])
                } else {
                    return Err(openwiz_core::source::SourceError::Unavailable {
                        detail: "unexpected synthetic read".into(),
                    });
                }
            }
            ["issue", "comment", "9", "--body", body] => {
                world["comments"].as_array_mut().unwrap().push(json!({"id":901,"body":body,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64}));
                fs::write(dir.join("world.json"), world.to_string()).unwrap();
                return Ok(format!("{url}#issuecomment-901\n").into_bytes());
            }
            ["issue", "view", "9", "--json", "comments"] => view(&world),
            ["issue", "view", "9", "--json", "url"] => json!({"url":url}),
            ["issue", "view", "9", "--json", "state"] => {
                json!({"state":world["issues"][0]["state"]})
            }
            ["issue", "close", "9"] => {
                world["issues"][0]["state"] = json!("CLOSED");
                fs::write(dir.join("world.json"), world.to_string()).unwrap();
                return Ok(b"closed\n".to_vec());
            }
            _ => {
                return Err(openwiz_core::source::SourceError::Unavailable {
                    detail: "unexpected synthetic call".into(),
                });
            }
        };
        Ok(format!("{answer}\n").into_bytes())
    })))
}

/// Runs one controlled tick in a fresh child, so CloudRoom discovery is
/// installed once per process without touching this test binary's others.
fn tick(dir: &Path, verifier: &str) -> Value {
    let out = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "t12_handover::completion_process", "--nocapture"])
        .env("OPENWIZ_T12_DIR", dir)
        .env("OPENWIZ_T12_VERIFIER", verifier)
        .env("OPENWIZ_FIXTURE_PROGRAM", dir.join("room-cli"))
        .env_remove("OPENWIZ_FIXTURE_ROOT")
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&fs::read(dir.join("tick.json")).unwrap()).unwrap()
}

#[test]
fn completion_process() {
    let Some(dir) = std::env::var_os("OPENWIZ_T12_DIR").map(PathBuf::from) else {
        return;
    };
    let bundle = fixture::Bundle::from_environment();
    openwiz_adapter_cloudroom::locate::install(bundle.discovery()).unwrap();
    let mut control = Control::new("prj_syn_0001", Arc::new(AtomicBool::new(false))).unwrap();
    let seen = dir.clone();
    let record = move |detail: &Detail| {
        let effect = match detail {
            Detail::SpecSummary { .. } => "spec_summary",
            Detail::AllClosed { .. } => "all_closed",
            _ => "other",
        };
        let mut log = fs::read_to_string(seen.join("verifier.log")).unwrap_or_default();
        log.push_str(effect);
        log.push('\n');
        fs::write(seen.join("verifier.log"), log).unwrap();
    };
    match std::env::var("OPENWIZ_T12_VERIFIER").unwrap().as_str() {
        "none" => {}
        "verified" => {
            control = control.with_completion_verifier(move |detail| {
                record(detail);
                Ok(())
            });
        }
        "held" => {
            control = control.with_completion_verifier(move |detail| {
                record(detail);
                Err("CP1 held: synthetic stale checkpoint")
            });
        }
        other => panic!("unknown verifier {other}"),
    }
    let mut out = Vec::new();
    cli::run_with_control(
        Args {
            due: false,
            dry_run: false,
            json: true,
        },
        Context {
            github: &github(dir.clone()),
            room: &CloudRoomSource::new(dir.join("room-cli")),
            state: &dir.join("state"),
            orchestrator: Some("thr_syn_0001"),
        },
        &mut out,
        &control,
    )
    .unwrap();
    fs::write(dir.join("tick.json"), out).unwrap();
}

fn action<'a>(doc: &'a Value, rule: &str) -> &'a Value {
    doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == rule)
        .unwrap_or_else(|| panic!("no {rule}: {doc}"))
}
fn writes(dir: &Path) -> Vec<String> {
    fs::read_to_string(dir.join("gh-calls.log"))
        .unwrap_or_default()
        .lines()
        .filter(|l| l.contains("\"comment\"") || l.contains("\"close\""))
        .map(str::to_owned)
        .collect()
}
fn verifier_calls(dir: &Path) -> Vec<String> {
    fs::read_to_string(dir.join("verifier.log"))
        .unwrap_or_default()
        .lines()
        .map(str::to_owned)
        .collect()
}

#[test]
fn without_a_verifier_completion_keeps_its_shipped_refusal() {
    for (rule, summarized) in [("spec_summary", false), ("all_closed", true)] {
        let temp = Temp::new("none");
        completion_world(&temp.0, summarized);
        let doc = tick(&temp.0, "none");
        let a = action(&doc, rule);
        assert_eq!(a["outcome"]["state"], "refused", "{doc}");
        assert_eq!(a["outcome"]["reason"], HELD, "{doc}");
        assert!(writes(&temp.0).is_empty(), "{:?}", writes(&temp.0));
    }
}

#[test]
fn a_holding_verifier_refuses_with_its_reason_at_every_effect_boundary() {
    for (rule, summarized) in [("spec_summary", false), ("all_closed", true)] {
        let temp = Temp::new("held");
        completion_world(&temp.0, summarized);
        for wake in 1..=2 {
            let doc = tick(&temp.0, "held");
            let a = action(&doc, rule);
            assert_eq!(a["outcome"]["state"], "refused", "{doc}");
            assert_eq!(
                a["outcome"]["reason"], "CP1 held: synthetic stale checkpoint",
                "{doc}"
            );
            // Re-read at each wake: no cached verdict.
            assert_eq!(verifier_calls(&temp.0), vec![rule; wake]);
        }
        assert!(writes(&temp.0).is_empty(), "{:?}", writes(&temp.0));
    }
}

#[test]
fn completion_effects_run_only_after_the_verifier_passes_that_exact_effect() {
    let temp = Temp::new("summary");
    completion_world(&temp.0, false);
    let doc = tick(&temp.0, "verified");
    assert_ne!(
        action(&doc, "spec_summary")["outcome"]["state"],
        "refused",
        "{doc}"
    );
    assert_eq!(verifier_calls(&temp.0), ["spec_summary"]);
    let written = writes(&temp.0);
    assert_eq!(written.len(), 1, "{written:?} {doc}");
    assert!(
        written[0].contains("launch-fleet: spec summary"),
        "{written:?}"
    );

    let temp = Temp::new("close");
    completion_world(&temp.0, true);
    let doc = tick(&temp.0, "verified");
    assert_ne!(
        action(&doc, "all_closed")["outcome"]["state"],
        "refused",
        "{doc}"
    );
    assert_eq!(verifier_calls(&temp.0), ["all_closed"]);
    assert!(
        writes(&temp.0).iter().any(|w| w.contains("\"close\"")),
        "{:?}",
        writes(&temp.0)
    );
}
