//! The terminal tests' recording fixture HTTP server and helpers. Every
//! response is synthetic (`tests/fixtures/terminal/`); nothing here reads a
//! live kit or private evidence.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use openwiz_terminal::app::{App, Now};
use openwiz_terminal::config::Settings;
use openwiz_terminal::http::Client;
use openwiz_terminal::run::Shell;

pub const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
/// The fixtures' server snapshot time.
pub const T: i64 = 1_700_000_600_000;

/// Inventory envelopes live under `tests/fixtures/terminal/envelopes/`, where
/// the fixture scan checks them; the fleet and decisions bodies, whose
/// OpenWiz report words that scan's room-cli/gh vocabularies do not know, live
/// in `tests/terminal/bodies/` and are scanned by `fixtures.rs` instead.
pub const FIXTURE_DIRS: [&str; 2] = ["tests/fixtures/terminal/envelopes", "tests/terminal/bodies"];

pub fn fixture(name: &str) -> Vec<u8> {
    FIXTURE_DIRS
        .iter()
        .find_map(|dir| std::fs::read(Path::new(ROOT).join(dir).join(name)).ok())
        .unwrap_or_else(|| panic!("{name}: no such fixture"))
}

#[derive(Clone, Debug)]
pub struct Recorded {
    pub method: String,
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Recorded {
    pub fn header(&self, name: &str) -> Vec<&str> {
        self.headers
            .iter()
            .filter(|(n, _)| n.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.as_str())
            .collect()
    }
}

#[derive(Clone)]
pub struct Reply {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub delay: Duration,
    /// Raw bytes instead of a well-formed answer.
    pub raw: Option<Vec<u8>>,
}

impl Reply {
    pub fn ok(body: Vec<u8>) -> Self {
        Self {
            status: 200,
            headers: Vec::new(),
            body,
            delay: Duration::ZERO,
            raw: None,
        }
    }
    pub fn status(status: u16, kind: &str, message: &str) -> Self {
        Self {
            status,
            headers: Vec::new(),
            body: format!("{{\"error\":{{\"kind\":\"{kind}\",\"message\":\"{message}\"}}}}")
                .into_bytes(),
            delay: Duration::ZERO,
            raw: None,
        }
    }
    pub fn delayed(mut self, delay: Duration) -> Self {
        self.delay = delay;
        self
    }
    pub fn header(mut self, name: &str, value: &str) -> Self {
        self.headers.push((name.into(), value.into()));
        self
    }
}

#[derive(Default)]
struct State {
    routes: HashMap<String, Reply>,
    requests: Vec<Recorded>,
    in_flight: usize,
    max_in_flight: usize,
}

/// A loopback server that records every request and answers from its
/// table (`404` otherwise).
pub struct FixtureServer {
    pub port: u16,
    state: Arc<Mutex<State>>,
}

impl FixtureServer {
    pub fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let state = Arc::new(Mutex::new(State::default()));
        let shared = Arc::clone(&state);
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(stream) = stream else { continue };
                let shared = Arc::clone(&shared);
                std::thread::spawn(move || serve(stream, &shared));
            }
        });
        Self { port, state }
    }

    /// The usual Home: decisions, fleets and inventory.
    pub fn home() -> Self {
        let server = Self::start();
        server.route("/api/v1/decisions", Reply::ok(fixture("decisions.json")));
        server.route("/api/v1/fleets", Reply::ok(fixture("fleets.json")));
        server.route("/api/v1/inventory", Reply::ok(fixture("inventory.json")));
        server.route(
            "/api/v1/sessions/thr_syn_0301",
            Reply::ok(fixture("session-thr_syn_0301.json")),
        );
        server.route("/api/v1/fleets/9001", Reply::ok(fixture("fleet-9001.json")));
        server
    }

    pub fn route(&self, path: &str, reply: Reply) {
        self.state
            .lock()
            .unwrap()
            .routes
            .insert(path.to_owned(), reply);
    }

    pub fn requests(&self) -> Vec<Recorded> {
        self.state.lock().unwrap().requests.clone()
    }

    pub fn paths(&self) -> Vec<String> {
        self.requests().into_iter().map(|r| r.path).collect()
    }

    pub fn count(&self, path: &str) -> usize {
        self.paths().iter().filter(|p| *p == path).count()
    }

    pub fn writes(&self) -> Vec<Recorded> {
        self.requests()
            .into_iter()
            .filter(|r| r.method != "GET")
            .collect()
    }

    pub fn max_in_flight(&self) -> usize {
        self.state.lock().unwrap().max_in_flight
    }
}

fn serve(mut stream: TcpStream, state: &Arc<Mutex<State>>) {
    stream.set_read_timeout(Some(Duration::from_secs(10))).ok();
    let mut received = Vec::new();
    let mut chunk = [0u8; 4096];
    let end = loop {
        if let Some(i) = received.windows(4).position(|w| w == b"\r\n\r\n") {
            break i;
        }
        match stream.read(&mut chunk) {
            Ok(0) | Err(_) => return,
            Ok(n) => received.extend_from_slice(&chunk[..n]),
        }
    };
    let head = String::from_utf8_lossy(&received[..end]).into_owned();
    let mut lines = head.split("\r\n");
    let mut first = lines.next().unwrap_or_default().split(' ');
    let method = first.next().unwrap_or_default().to_owned();
    let path = first.next().unwrap_or_default().to_owned();
    let headers: Vec<(String, String)> = lines
        .filter_map(|l| l.split_once(':'))
        .map(|(n, v)| (n.trim().to_owned(), v.trim().to_owned()))
        .collect();
    let length: usize = headers
        .iter()
        .find(|(n, _)| n.eq_ignore_ascii_case("content-length"))
        .and_then(|(_, v)| v.parse().ok())
        .unwrap_or(0);
    let mut body = received[end + 4..].to_vec();
    while body.len() < length {
        match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => body.extend_from_slice(&chunk[..n]),
        }
    }
    let reply = {
        let mut s = state.lock().unwrap();
        s.requests.push(Recorded {
            method,
            path: path.clone(),
            headers,
            body,
        });
        s.in_flight += 1;
        s.max_in_flight = s.max_in_flight.max(s.in_flight);
        s.routes.get(&path).cloned()
    };
    let reply = reply.unwrap_or_else(|| Reply::status(404, "no_route", "no such route"));
    std::thread::sleep(reply.delay);
    let bytes = match &reply.raw {
        Some(raw) => raw.clone(),
        None => {
            let mut out = format!(
                "HTTP/1.1 {} X\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n",
                reply.status,
                reply.body.len()
            );
            for (n, v) in &reply.headers {
                out.push_str(&format!("{n}: {v}\r\n"));
            }
            out.push_str("\r\n");
            let mut out = out.into_bytes();
            out.extend_from_slice(&reply.body);
            out
        }
    };
    let _ = stream.write_all(&bytes);
    let _ = stream.flush();
    state.lock().unwrap().in_flight -= 1;
}

pub fn now(mono_ms: u64) -> Now {
    Now {
        mono_ms,
        wall_ms: T + mono_ms as i64,
    }
}

pub fn settings(port: u16, host: Option<&str>) -> Settings {
    Settings {
        port,
        allowed_host: host.map(str::to_owned),
    }
}

pub fn client(port: u16, host: Option<&str>) -> Client {
    let mut client = Client::new(&settings(port, host));
    client.deadline = Duration::from_secs(5);
    client
}

pub fn shell(server: &FixtureServer) -> Shell {
    Shell::new(
        App::new(settings(server.port, None)),
        client(server.port, None),
    )
}

pub const SETTLE: Duration = Duration::from_secs(10);
