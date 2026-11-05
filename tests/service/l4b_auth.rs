//! Synthetic App boundary: fixed scopes, identity, isolated cache and child env.
use super::*;
use openwiz_adapter_github::{
    allowlist::Invocation,
    app::{Clock, Error, Exchange},
};
use openwiz_service::app::Client;
use std::{
    fs::DirBuilder,
    io::Write,
    os::unix::fs::DirBuilderExt,
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

const TOKEN: &str = "synthetic-event-installation-token";
const SERVICE_TOKEN: &str = "synthetic-service-installation-token";
const NOW: u64 = 1_893_456_000;
fn ordinary_permissions() -> Value {
    json!({"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"})
}
fn event_permissions() -> Value {
    json!({"metadata":"read","contents":"read","issues":"read","pull_requests":"read","checks":"read","actions":"read","repository_hooks":"read"})
}
struct AppTime(AtomicU64);
impl Clock for AppTime {
    fn now_s(&self) -> u64 {
        self.0.load(Ordering::SeqCst)
    }
}
struct Mint {
    calls: Mutex<Vec<Value>>,
    response: Mutex<Option<Value>>,
    deny_events: bool,
}
impl Mint {
    fn new(response: Option<Value>, deny_events: bool) -> Self {
        Self {
            calls: Mutex::new(vec![]),
            response: Mutex::new(response),
            deny_events,
        }
    }
}
impl Exchange for Mint {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        _: Instant,
    ) -> Result<Vec<u8>, Error> {
        assert_eq!(installation, 2002);
        assert_eq!(jwt.split('.').count(), 3);
        let body: Value = serde_json::from_slice(body).unwrap();
        assert_eq!(body["repositories"], json!(["synthetic-repo"]));
        self.calls.lock().unwrap().push(body.clone());
        if self.deny_events && body["permissions"] == event_permissions() {
            return Err(Error);
        }
        let response=self.response.lock().unwrap().clone().unwrap_or_else(|| {
            let event=body["permissions"]==event_permissions();
            json!({"token":if event {TOKEN} else {SERVICE_TOKEN},"expires_at":"2030-01-01T01:00:00Z","permissions":body["permissions"],"repositories":[{"full_name":REPOSITORY}],"repository_selection":"selected"})
        });
        Ok(response.to_string().into_bytes())
    }
}
fn key(root: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(root.join("service/app"))
        .unwrap();
    let path = root.join("service/app/private-key.pem");
    let output = Command::new("/usr/bin/openssl")
        .args([
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
        ])
        .arg(&path)
        .output()
        .unwrap();
    assert!(output.status.success());
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
fn gh(root: &Path) -> std::path::PathBuf {
    let program = root.join("gh");
    let script = format!(
        r#"#!/bin/sh
umask 077
export OPENWIZ_L4B_GH_ROOT={root}
export OPENWIZ_L4B_GH_ARGS={root}/args-$$
printf '%s\0' "$@" > "$OPENWIZ_L4B_GH_ARGS"
exec {exe} --exact composition::auth::gh_process --nocapture 3>&1 >/dev/null
"#,
        root = quoted(root),
        exe = quoted(&std::env::current_exe().unwrap())
    );
    assert!(
        Command::new("/bin/sh")
            .args(["-c", "printf '%s' \"$2\" > \"$1\"", "sh"])
            .arg(&program)
            .arg(script)
            .status()
            .unwrap()
            .success()
    );
    fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
    program
}
#[test]
fn gh_process() {
    let Some(root) = std::env::var_os("OPENWIZ_L4B_GH_ROOT") else {
        return;
    };
    let root = std::path::PathBuf::from(root);
    let args_path = std::path::PathBuf::from(std::env::var_os("OPENWIZ_L4B_GH_ARGS").unwrap());
    let bytes = fs::read(&args_path).unwrap();
    fs::remove_file(args_path).unwrap();
    assert_eq!(bytes.last(), Some(&0));
    let args = bytes[..bytes.len() - 1]
        .split(|b| *b == 0)
        .map(|v| std::str::from_utf8(v).unwrap())
        .collect::<Vec<_>>();
    let record = json!({"args":args,"event_token":std::env::var("GH_TOKEN").ok().as_deref()==Some(TOKEN),"ordinary_token":std::env::var("GH_TOKEN").ok().as_deref()==Some(SERVICE_TOKEN),"repository_bound":std::env::var("GH_REPO").ok().as_deref()==Some("github.com/synthetic-owner/synthetic-repo"),"host_bound":std::env::var("GH_HOST").ok().as_deref()==Some("github.com"),"no_github_token":std::env::var_os("GITHUB_TOKEN").is_none(),"no_debug":std::env::var_os("GH_DEBUG").is_none()});
    fs::write(
        root.join(format!("ghcall-{}.json", std::process::id())),
        record.to_string(),
    )
    .unwrap();
    let out = github_response(&args, false).unwrap();
    fs::OpenOptions::new()
        .write(true)
        .open("/proc/self/fd/3")
        .unwrap()
        .write_all(&out)
        .unwrap();
    std::process::exit(0);
}
fn gh_calls(root: &Path) -> Vec<Value> {
    fs::read_dir(root)
        .unwrap()
        .filter_map(|e| {
            let e = e.unwrap();
            if !e.file_name().to_str().unwrap().starts_with("ghcall-") {
                return None;
            }
            Some(serde_json::from_slice(&fs::read(e.path()).unwrap()).unwrap())
        })
        .collect()
}
fn call() -> Invocation {
    Invocation::new(&[
        "api",
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=100",
    ])
    .unwrap()
}
fn until() -> Instant {
    Instant::now() + openwiz_core::limits::RUN_BUDGET
}
fn client(root: &Path, mint: Arc<Mint>, clock: Arc<AppTime>, events: bool) -> Client {
    let open = if events {
        Client::with_exchange_for_events
    } else {
        Client::with_exchange
    };
    open(root, &config().to_string(), gh(root), mint, clock).unwrap()
}
fn valid_event_response() -> Value {
    json!({"token":TOKEN,"expires_at":"2030-01-01T01:00:00Z","permissions":event_permissions(),"repositories":[{"full_name":REPOSITORY}],"repository_selection":"selected"})
}

#[test]
fn lp3b_event_profile_requests_exact_read_scope_and_preserves_cache_deadline_and_child_binding() {
    let f = Fixture::new();
    key(&f.0);
    let mint = Arc::new(Mint::new(Some(valid_event_response()), false));
    let clock = Arc::new(AppTime(AtomicU64::new(NOW)));
    let app = client(&f.0, Arc::clone(&mint), Arc::clone(&clock), true);
    assert!(app.execute(&call(), Instant::now()).is_err());
    assert!(mint.calls.lock().unwrap().is_empty());
    assert!(gh_calls(&f.0).is_empty());
    for _ in 0..2 {
        assert!(app.clone().execute(&call(), until()).is_ok());
    }
    assert_eq!(mint.calls.lock().unwrap().len(), 1);
    assert_eq!(
        mint.calls.lock().unwrap()[0],
        json!({"repositories":["synthetic-repo"],"permissions":event_permissions()})
    );
    clock.0.store(NOW + 3301, Ordering::SeqCst);
    assert!(app.execute(&call(), until()).is_ok());
    assert_eq!(mint.calls.lock().unwrap().len(), 2);
    let calls = gh_calls(&f.0);
    assert_eq!(calls.len(), 3);
    for row in calls {
        assert_eq!(
            row,
            json!({"args":call().argv(),"event_token":true,"ordinary_token":false,"repository_bound":true,"host_bound":true,"no_github_token":true,"no_debug":true})
        );
    }
}

#[test]
fn lp3b_event_profile_refuses_each_missing_extra_wrong_permission_and_wrong_identity_without_execution()
 {
    let f = Fixture::new();
    key(&f.0);
    let good = valid_event_response();
    let mut cases = vec![];
    for name in event_permissions().as_object().unwrap().keys() {
        let mut missing = good.clone();
        missing["permissions"].as_object_mut().unwrap().remove(name);
        cases.push(missing);
        let mut wrong = good.clone();
        wrong["permissions"][name] = json!("write");
        cases.push(wrong);
    }
    let mut extra = good.clone();
    extra["permissions"]["administration"] = json!("read");
    cases.push(extra);
    let mut ordinary = good.clone();
    ordinary["permissions"] = ordinary_permissions();
    cases.push(ordinary);
    for repositories in [
        json!([]),
        json!([{"full_name":"synthetic-other/project"}]),
        json!([{"full_name":REPOSITORY},{"full_name":"synthetic-other/project"}]),
    ] {
        let mut wrong = good.clone();
        wrong["repositories"] = repositories;
        cases.push(wrong);
    }
    let mut missing_identity = good.clone();
    missing_identity
        .as_object_mut()
        .unwrap()
        .remove("repositories");
    cases.push(missing_identity);
    for repositories in [json!(null), json!([{}])] {
        let mut missing = good.clone();
        missing["repositories"] = repositories;
        cases.push(missing);
    }
    let mut selection = good.clone();
    selection["repository_selection"] = json!("unknown");
    cases.push(selection);
    let mut expires = good.clone();
    expires["expires_at"] = json!("2029-12-31T23:59:59Z");
    cases.push(expires);
    for response in cases {
        let mint = Arc::new(Mint::new(Some(response.clone()), false));
        let app = client(
            &f.0,
            Arc::clone(&mint),
            Arc::new(AppTime(AtomicU64::new(NOW))),
            true,
        );
        assert!(
            app.execute(&call(), until()).is_err(),
            "response must refuse: {response}"
        );
        assert_eq!(
            mint.calls.lock().unwrap().len(),
            1,
            "no ordinary/broader-profile fallback"
        );
        assert!(gh_calls(&f.0).is_empty());
    }
}

#[test]
fn lp3b_event_auth_denial_leaves_ordinary_tick_and_health_scope_and_cache_independent() {
    let f = Fixture::new();
    key(&f.0);
    let mint = Arc::new(Mint::new(None, true));
    let clock = Arc::new(AppTime(AtomicU64::new(NOW)));
    let ordinary = client(&f.0, Arc::clone(&mint), Arc::clone(&clock), false);
    let event = client(&f.0, Arc::clone(&mint), clock, true);
    let metadata = Invocation::new(&[
        "repo",
        "view",
        "--json",
        "defaultBranchRef,nameWithOwner,url",
    ])
    .unwrap();
    assert!(ordinary.execute(&metadata, until()).is_ok());
    assert!(event.execute(&call(), until()).is_err());
    assert!(ordinary.clone().execute(&metadata, until()).is_ok());
    let requests = mint.calls.lock().unwrap();
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[0]["permissions"], ordinary_permissions());
    assert_eq!(requests[1]["permissions"], event_permissions());
    let calls = gh_calls(&f.0);
    assert_eq!(calls.len(), 2);
    assert!(
        calls
            .iter()
            .all(|c| c["ordinary_token"] == true && c["event_token"] == false)
    );

    // An ordinary client must also refuse a token for the event scope.
    let wrong_scope = Arc::new(Mint::new(Some(valid_event_response()), false));
    let ordinary = client(
        &f.0,
        Arc::clone(&wrong_scope),
        Arc::new(AppTime(AtomicU64::new(NOW))),
        false,
    );
    assert!(ordinary.execute(&metadata, until()).is_err());
    assert_eq!(wrong_scope.calls.lock().unwrap().len(), 1);
    assert_eq!(gh_calls(&f.0).len(), 2);
}

#[test]
fn lp3b_app_authenticated_delivery_reader_and_current_world_route_one_effect() {
    for denied in [false, true] {
        let f = Fixture::new();
        key(&f.0);
        let mint = Arc::new(Mint::new(Some(valid_event_response()), denied));
        let app = client(
            &f.0,
            Arc::clone(&mint),
            Arc::new(AppTime(AtomicU64::new(NOW))),
            true,
        );
        let github = Executor::supplied(Arc::new(move |call, deadline| {
            app.execute(call, deadline).map_err(|_| {
                openwiz_core::source::SourceError::Unavailable {
                    detail: "synthetic event auth refusal".into(),
                }
            })
        }));
        let mut scheduler = Scheduler::default();
        assert!(
            intake::register_with_sources(
                &f.0,
                &config(),
                &mut scheduler,
                Sources {
                    github,
                    room: room(&f.0)
                },
                Arc::new(Time)
            )
            .unwrap()
        );
        for at in [10, 20] {
            assert_eq!(scheduler.poll(at).unwrap(), [intake::JOB]);
            scheduler.wait(intake::JOB).unwrap();
        }
        let tells = calls(&f.0)
            .into_iter()
            .filter(|a| a.get(1).is_some_and(|a| a == "tell"))
            .collect::<Vec<_>>();
        assert_eq!(tells.len(), usize::from(!denied));
        if denied {
            assert!(!f.0.join("events").exists());
            assert!(gh_calls(&f.0).is_empty());
            let requests = mint.calls.lock().unwrap();
            assert_eq!(
                requests.len(),
                2,
                "one refused mint per scheduled pass, never a fallback"
            );
            assert!(
                requests
                    .iter()
                    .all(|r| r["permissions"] == event_permissions())
            );
        } else {
            assert_eq!(tells[0][2], "thr_syn_0021");
            assert_eq!(mint.calls.lock().unwrap().len(), 1);
            let calls = gh_calls(&f.0);
            assert!(calls.iter().all(|c| c["event_token"] == true
                && c["repository_bound"] == true
                && c["host_bound"] == true
                && c["ordinary_token"] == false));
            assert_eq!(
                calls
                    .iter()
                    .filter(|c| c["args"][1]
                        == "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=100")
                    .count(),
                2
            );
            assert_eq!(
                calls
                    .iter()
                    .filter(|c| c["args"][1] == "repos/{owner}/{repo}/hooks/4101/deliveries/6101")
                    .count(),
                1
            );
        }
    }
}
