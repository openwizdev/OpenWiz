//! C6/C7 on synthetic fixtures. The shared client seam, never a live tick.
#![cfg(target_os = "linux")]
use openwiz_adapter_github::{
    allowlist::Invocation,
    app::{Clock, Error, Exchange},
};
use openwiz_service::app::Client;
use serde_json::{Value, json};
use std::{
    fs::{self, DirBuilder},
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

const NOW: u64 = 1_893_456_000; // 2030-01-01T00:00:00Z, independent literal.
const TOKEN: &str = "synthetic-installation-token";
#[path = "t7_deadline.rs"]
mod deadline;
#[path = "t7_fake_gh.rs"]
mod fake_gh;
#[path = "t7_forms.rs"]
mod forms;
#[path = "t7_privacy.rs"]
mod privacy;
#[path = "t7_python.rs"]
mod python;
struct Time(AtomicU64);
impl Clock for Time {
    fn now_s(&self) -> u64 {
        self.0.load(Ordering::SeqCst)
    }
}

struct Endpoint {
    port: u16,
    calls: Arc<Mutex<Vec<Value>>>,
    response: Arc<Mutex<String>>,
}
impl Exchange for Endpoint {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        _: Instant,
    ) -> Result<Vec<u8>, Error> {
        let mut socket = TcpStream::connect(("127.0.0.1", self.port)).map_err(|_| Error)?;
        socket
            .set_read_timeout(Some(Duration::from_secs(5)))
            .map_err(|_| Error)?;
        write!(socket, "POST /app/installations/{installation}/access_tokens HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {jwt}\r\nContent-Length: {}\r\n\r\n", body.len()).map_err(|_| Error)?;
        socket.write_all(body).map_err(|_| Error)?;
        let mut out = Vec::new();
        socket.read_to_end(&mut out).map_err(|_| Error)?;
        let at = out.windows(4).position(|w| w == b"\r\n\r\n").ok_or(Error)?;
        Ok(out[at + 4..].to_vec())
    }
}

fn private_dir(path: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn private_file(path: &Path, bytes: impl AsRef<[u8]>, mode: u32) {
    fs::write(path, bytes).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
}
fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.to_str().unwrap().replace('\'', "'\\''"))
}
struct Fixture {
    root: PathBuf,
    exchange: Arc<Endpoint>,
    clock: Arc<Time>,
    server: Option<thread::JoinHandle<()>>,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-t7-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        private_dir(&root.join("service/app"));
        let generated = Command::new("/usr/bin/openssl")
            .args([
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
            ])
            .arg(root.join("service/app/private-key.pem"))
            .output()
            .unwrap();
        assert!(generated.status.success());
        fs::set_permissions(
            root.join("service/app/private-key.pem"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        private_file(
            &root.join("gh"),
            format!(
                r#"#!/bin/sh
umask 077
export OPENWIZ_T7_GH_ROOT={root}
export OPENWIZ_T7_GH_ARGS={root}/args-$$
printf '%s\0' "$@" > "$OPENWIZ_T7_GH_ARGS"
exec {exe} --exact fake_gh::fixture_gh_process --nocapture 3>&1 >/dev/null
"#,
                root = shell_quote(&root),
                exe = shell_quote(&std::env::current_exe().unwrap())
            ),
            0o700,
        );
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let calls = Arc::new(Mutex::new(Vec::new()));
        let recorded = calls.clone();
        let response = Arc::new(Mutex::new(json!({"token":TOKEN,"expires_at":"2030-01-01T01:00:00Z","permissions":{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}}).to_string()));
        let reply = response.clone();
        let server = thread::spawn(move || {
            for socket in listener.incoming() {
                let mut socket = socket.unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut data = Vec::new();
                let (at, len) = loop {
                    let mut buf = [0; 1024];
                    let n = socket.read(&mut buf).unwrap();
                    if n == 0 {
                        return;
                    }
                    data.extend_from_slice(&buf[..n]);
                    if let Some(at) = data.windows(4).position(|w| w == b"\r\n\r\n") {
                        let header = std::str::from_utf8(&data[..at]).unwrap();
                        let len: usize = header
                            .lines()
                            .find_map(|l| l.strip_prefix("Content-Length: "))
                            .unwrap()
                            .parse()
                            .unwrap();
                        if data.len() >= at + 4 + len {
                            break (at, len);
                        }
                    }
                };
                let header = std::str::from_utf8(&data[..at]).unwrap();
                let jwt = header
                    .lines()
                    .find_map(|l| l.strip_prefix("Authorization: Bearer "))
                    .unwrap();
                recorded.lock().unwrap().push(json!({"path":header.lines().next().unwrap(), "jwt":jwt, "body":serde_json::from_slice::<Value>(&data[at+4..at+4+len]).unwrap()}));
                let response = reply.lock().unwrap().clone();
                write!(socket, "HTTP/1.1 201 Created\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}", response.len()).unwrap();
            }
        });
        Self {
            root,
            exchange: Arc::new(Endpoint {
                port,
                calls,
                response,
            }),
            clock: Arc::new(Time(AtomicU64::new(NOW))),
            server: Some(server),
        }
    }
    fn config(&self) -> String {
        let contract = include_str!("../../contracts/service.v1.md");
        contract
            .lines()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .find(|v| v["schema"] == "openwiz.service-config.v1")
            .unwrap()
            .to_string()
    }
    fn client(&self) -> Client {
        Client::with_exchange(
            &self.root,
            &self.config(),
            self.root.join("gh"),
            self.exchange.clone(),
            self.clock.clone(),
        )
        .unwrap()
    }
    fn gh_calls(&self) -> Vec<Value> {
        fs::read_to_string(self.root.join("calls.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        // EOF is the explicit stop signal; no sleeps or process polling.
        drop(TcpStream::connect(("127.0.0.1", self.exchange.port)).unwrap());
        self.server.take().unwrap().join().unwrap();
        fs::remove_dir_all(&self.root).unwrap();
    }
}
fn soon() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
fn call() -> Invocation {
    Invocation::new(&["issue", "view", "901", "--json", "comments"]).unwrap()
}

#[test]
fn mints_at_the_fake_endpoint_and_uses_only_the_repository_scoped_token() {
    let f = Fixture::new();
    let client = f.client();
    assert_eq!(
        client
            .execute(&call(), soon())
            .expect("the service App call must mint and execute"),
        b"{\"synthetic\":\"ok\"}\n"
    );
    let calls = f.exchange.calls.lock().unwrap();
    assert_eq!(calls.len(), 1);
    privacy::verify_signature(&f, calls[0]["jwt"].as_str().unwrap());
    assert_eq!(
        calls[0]["path"],
        "POST /app/installations/2002/access_tokens HTTP/1.1"
    );
    assert_eq!(
        calls[0]["body"],
        json!({"repositories":["synthetic-repo"],"permissions":{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}})
    );
    assert_eq!(
        f.gh_calls(),
        [
            json!({"argv":["issue","view","901","--json","comments"],"token":TOKEN,"repo":"github.com/synthetic-owner/synthetic-repo","host":"github.com","debug":null})
        ]
    );
}

#[test]
fn tick_and_health_clones_share_one_token_and_renew_five_minutes_before_expiry() {
    let f = Fixture::new();
    let tick = f.client();
    let health = tick.clone();
    tick.execute(&call(), soon()).unwrap();
    f.clock.0.store(NOW + 3299, Ordering::SeqCst);
    health.execute(&call(), soon()).unwrap();
    assert_eq!(
        f.exchange.calls.lock().unwrap().len(),
        1,
        "reuse until the refresh boundary"
    );
    let mut next: Value = serde_json::from_str(&f.exchange.response.lock().unwrap()).unwrap();
    next["token"] = json!("synthetic-renewed-token");
    next["expires_at"] = json!("2030-01-01T01:55:00Z");
    *f.exchange.response.lock().unwrap() = next.to_string();
    f.clock.0.store(NOW + 3300, Ordering::SeqCst);
    std::thread::scope(|s| {
        let a = s.spawn(|| tick.execute(&call(), soon()).unwrap());
        let b = s.spawn(|| health.execute(&call(), soon()).unwrap());
        a.join().unwrap();
        b.join().unwrap();
    });
    assert_eq!(
        f.exchange.calls.lock().unwrap().len(),
        2,
        "one shared renewal"
    );
    let seen: Vec<_> = f
        .gh_calls()
        .into_iter()
        .map(|v| v["token"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(
        seen,
        [
            TOKEN,
            TOKEN,
            "synthetic-renewed-token",
            "synthetic-renewed-token"
        ]
    );
}

#[test]
fn unsafe_key_or_state_is_refused_even_after_a_token_is_cached() {
    use std::os::unix::fs::symlink;
    for case in [
        "public-key",
        "public-app",
        "public-service",
        "public-root",
        "linked-key",
        "symlink-key",
        "symlink-app",
        "directory-key",
        "fifo-key",
        "repo-service",
        "repo-app",
    ] {
        let f = Fixture::new();
        let client = f.client();
        client.execute(&call(), soon()).unwrap();
        let key = f.root.join("service/app/private-key.pem");
        match case {
            "repo-service" | "repo-app" => {
                let directory = if case == "repo-service" {
                    "service"
                } else {
                    "service/app"
                };
                private_file(
                    &f.root.join(directory).join(".git"),
                    b"gitdir: synthetic-only",
                    0o600,
                );
            }
            "public-key" => fs::set_permissions(&key, fs::Permissions::from_mode(0o644)).unwrap(),
            "public-app" => fs::set_permissions(
                f.root.join("service/app"),
                fs::Permissions::from_mode(0o750),
            )
            .unwrap(),
            "public-service" => {
                fs::set_permissions(f.root.join("service"), fs::Permissions::from_mode(0o701))
                    .unwrap()
            }
            "public-root" => {
                fs::set_permissions(&f.root, fs::Permissions::from_mode(0o755)).unwrap()
            }
            "linked-key" => fs::hard_link(&key, f.root.join("key-alias")).unwrap(),
            "symlink-key" => {
                fs::rename(&key, f.root.join("original-key")).unwrap();
                symlink(f.root.join("original-key"), &key).unwrap();
            }
            "symlink-app" => {
                fs::rename(f.root.join("service/app"), f.root.join("original-app")).unwrap();
                symlink(f.root.join("original-app"), f.root.join("service/app")).unwrap();
            }
            "directory-key" => {
                fs::remove_file(&key).unwrap();
                private_dir(&key);
            }
            "fifo-key" => {
                fs::remove_file(&key).unwrap();
                assert!(
                    Command::new("/usr/bin/mkfifo")
                        .args(["-m", "600"])
                        .arg(&key)
                        .status()
                        .unwrap()
                        .success()
                );
            }
            _ => unreachable!(),
        }
        assert!(
            client.execute(&call(), soon()).is_err(),
            "must refuse {case}"
        );
        assert_eq!(f.gh_calls().len(), 1, "no call after {case}");
        assert_eq!(f.exchange.calls.lock().unwrap().len(), 1);
    }
}

#[test]
fn duplicate_or_unknown_token_fields_and_bad_expiry_are_refused_without_disclosure() {
    let f = Fixture::new();
    let clean: Value = serde_json::from_str(&f.exchange.response.lock().unwrap()).unwrap();
    let mut cases = vec![
        format!(
            "{{\"token\":\"synthetic-duplicate\",{}",
            &clean.to_string()[1..]
        ),
        clean.to_string().replace(
            "\"metadata\":\"read\"",
            "\"metadata\":\"write\",\"metadata\":\"read\"",
        ),
        format!(
            "{{\"unknown\":\"synthetic-sensitive-marker\",{}",
            &clean.to_string()[1..]
        ),
    ];
    for expiry in [
        "2030-01-01T01:00:+0Z",
        "2030-02-30T01:00:00Z",
        "2030-01-01T00:00:00Z",
        "2030-01-02T01:00:00Z",
    ] {
        let mut value = clean.clone();
        value["expires_at"] = json!(expiry);
        cases.push(value.to_string());
    }
    for body in cases {
        *f.exchange.response.lock().unwrap() = body;
        let result = f.client().execute(&call(), soon());
        assert!(result.is_err(), "malformed token answer must be refused");
        assert_eq!(
            format!(
                "{} {:?}",
                result.as_ref().unwrap_err(),
                result.as_ref().unwrap_err()
            ),
            "GitHub App request refused (details withheld) Error"
        );
        assert!(f.gh_calls().is_empty());
    }
}

#[test]
fn a_failed_refresh_blocks_calls_instead_of_reusing_a_token_or_personal_login() {
    let f = Fixture::new();
    let client = f.client();
    client.execute(&call(), soon()).unwrap();
    f.clock.0.store(NOW + 3300, Ordering::SeqCst);
    *f.exchange.response.lock().unwrap() = "synthetic-private-marker not JSON".to_owned();
    assert!(client.execute(&call(), soon()).is_err());
    assert_eq!(f.gh_calls().len(), 1);
    assert_eq!(f.exchange.calls.lock().unwrap().len(), 2);
    f.clock.0.store(NOW + 3600, Ordering::SeqCst);
    assert!(client.execute(&call(), soon()).is_err());
    assert_eq!(f.gh_calls().len(), 1);
    assert_eq!(
        f.exchange.calls.lock().unwrap().len(),
        3,
        "only one attempt per caller, no retry loop"
    );
}
