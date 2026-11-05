//! LP6 (#549): the loops read's fail-closed paths (`openwiz_server::loops::read`),
//! on a synthetic private checkout and state with explicit trusted context.
use openwiz_server::loops::{ReadError, read};
use openwiz_store::loops::{Context as LoopContext, Trust, storage::Storage};
use serde_json::{Value, json};
use std::{
    cell::Cell,
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

struct Trusted(bool);
impl Trust for Trusted {
    fn verify(&self, _: &Path, repository: &str, project: &str) -> bool {
        self.0 && repository == "synthetic-owner/synthetic-repo" && project == "prj_syn_example"
    }
    fn actor(&self) -> Option<String> {
        None
    }
}
fn git(root: &Path, args: &[&str]) {
    let out = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}
struct Fixture {
    root: PathBuf,
    context: LoopContext,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-lp6-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let (checkout, state) = (root.join("checkout"), root.join("state"));
        for p in [checkout.join("loops"), state.join("service")] {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(p)
                .unwrap();
        }
        fs::write(state.join("service/config.json"), "{}").unwrap();
        fs::set_permissions(
            state.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@example.invalid"],
        );
        fs::write(
            checkout.join("loops/example.json"),
            include_str!("../../loops/example.json"),
        )
        .unwrap();
        git(&checkout, &["add", "loops"]);
        git(&checkout, &["commit", "-qm", "Synthetic definition"]);
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        git(
            &checkout,
            &[
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
        );
        let context = LoopContext {
            checkout,
            state,
            repository: "synthetic-owner/synthetic-repo".to_owned(),
            project: "prj_syn_example".to_owned(),
            trust: Some(Arc::new(Trusted(true))),
        };
        Self { root, context }
    }
    fn passed(&self) {
        drop(Storage::open(&self.context.state).unwrap());
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn unavailable(why: &str) -> Result<Value, ReadError> {
    Err(ReadError::Unavailable(why.to_owned()))
}
const READ: u64 = 1_893_456_300_000;

#[test]
fn lp6_read_refuses_without_trusted_context_or_identity() {
    let mut f = Fixture::new();
    f.passed();
    f.context.trust = None;
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("trusted loop context is unavailable")
    );
    f.context.trust = Some(Arc::new(Trusted(false)));
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("loop repository or project identity is not verified")
    );
    f.context.trust = Some(Arc::new(Trusted(true)));
    f.context.project = "prj_syn_other".to_owned();
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("loop repository or project identity is not verified")
    );
}

#[test]
fn lp6_read_never_creates_state() {
    let f = Fixture::new();
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("the scheduler has not run a pass yet")
    );
    assert!(
        !f.context.state.join("service/loops").exists(),
        "the read created loop state"
    );
}

#[test]
fn lp6_read_lists_the_default_branch_definitions() {
    let f = Fixture::new();
    f.passed();
    let v = read(&f.context, READ, &Instant::now).expect("a view");
    let example: Value = serde_json::from_str(include_str!("../../loops/example.json")).unwrap();
    assert_eq!(v["schema"], "openwiz.loops-view.v1");
    assert_eq!(v["loops"].as_array().unwrap().len(), 1);
    let l = &v["loops"][0];
    assert_eq!(l["id"], example["id"]);
    assert_eq!(l["name"], example["name"]);
    assert_eq!(l["enabled"], example["enabled"]);
    assert_eq!(l["last_run"], Value::Null);
    assert_eq!(l["cost"], json!({"kind": "known", "usd_micros": 0}));
    assert_eq!(l["problem"], Value::Null);
}

#[test]
fn lp6_read_refuses_a_checkout_off_its_clean_default_branch() {
    let f = Fixture::new();
    f.passed();
    fs::write(f.context.checkout.join("loops/example.json"), "{}").unwrap();
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("loop checkout must match its clean default branch")
    );
}

#[test]
fn lp6_read_is_busy_while_a_pass_holds_the_state() {
    let f = Fixture::new();
    f.passed();
    let pass = Storage::open(&f.context.state).unwrap();
    let start = Instant::now();
    let calls = Cell::new(0u32);
    // A clock that passes the five-second wait on its third reading.
    let clock = || {
        calls.set(calls.get() + 1);
        start + Duration::from_secs(if calls.get() >= 3 { 6 } else { 0 })
    };
    assert_eq!(read(&f.context, READ, &clock), Err(ReadError::Busy));
    assert!(
        start.elapsed() < Duration::from_secs(2),
        "waited on the wall clock"
    );
    drop(pass);
    assert!(
        read(&f.context, READ, &Instant::now).is_ok(),
        "readable once the pass ends"
    );
}

#[test]
fn lp6_read_refuses_a_run_updated_before_it_started() {
    // Review 1, R5: the store checks a run's schema, not its times; the view must not serve a run that ends before it starts.
    let f = Fixture::new();
    f.passed();
    let run = json!({
        "schema": "openwiz.loops.v1", "kind": "run", "id": "run-syn-0001", "loop_id": "loop-syn-reminder",
        "definition_revision": "a".repeat(40),
        "wake": {"kind": "interval", "due_at_ms": 1_893_456_000_000u64},
        "started_at_ms": 1_893_456_060_000u64, "updated_at_ms": 1_893_456_000_000u64,
        "cost": {"kind": "known", "usd_micros": 0}, "result": {"kind": "quiet"}
    });
    Storage::open(&f.context.state)
        .unwrap()
        .save_run(&run)
        .unwrap();
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("loop run run-syn-0001 was updated before it started")
    );
}

#[test]
fn lp6_read_refuses_a_run_admitted_before_it_was_due() {
    // Review of #1717, R2: as the planner validates, a scheduled run cannot start before its occurrence is due.
    let f = Fixture::new();
    f.passed();
    let run = json!({
        "schema": "openwiz.loops.v1", "kind": "run", "id": "run-syn-0002", "loop_id": "loop-syn-reminder",
        "definition_revision": "a".repeat(40),
        "wake": {"kind": "once", "due_at_ms": 1_893_456_060_000u64},
        "started_at_ms": 1_893_456_000_000u64, "updated_at_ms": 1_893_456_000_000u64,
        "cost": {"kind": "known", "usd_micros": 0}, "result": {"kind": "quiet"}
    });
    Storage::open(&f.context.state)
        .unwrap()
        .save_run(&run)
        .unwrap();
    assert_eq!(
        read(&f.context, READ, &Instant::now),
        unavailable("loop run run-syn-0002 was admitted before it was due")
    );
}
