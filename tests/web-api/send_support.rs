//! Helpers for the send routes (#9): an in-process server with the send
//! record and the fake `room-cli` of a messaging test (`SendFake`), the
//! fixed clock `openwiz send`'s proofs use, and a raw `POST` client.

#![allow(dead_code)]

use openwiz_core::messaging::effects::TargetRecord;
use openwiz_core::messaging::send::{Messenger, TellReply};
use openwiz_core::messaging::{InvalidRequest, Mode};
use openwiz_core::model::SessionId;
use openwiz_core::source::SourceError;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use openwiz_core::messaging::record::{SendStore, StoreError};
use openwiz_server::{Config, Limits, Log, OpenStore, OpenStoreReadOnly, SendHost, Sending};
use openwiz_store::FileStore;
use serde_json::{Value, json};

use crate::http::{Response, TestServer};
use crate::msg::{self, SendFake};

/// The synthetic public host name the send route is served on.
pub const HOST: &str = "openwiz.example";
pub const ORIGIN: &str = "https://openwiz.example";

/// The send route of `id`.
pub fn messages(id: &str) -> String {
    format!("/api/v1/sessions/{id}/messages")
}

/// The send record and provider of `fake`, opened as `openwiz send` opens
/// them.
pub fn sending(fake: &SendFake) -> Sending {
    let state = fake.state.clone();
    let read_only = fake.state.clone();
    let open_store: OpenStore =
        Arc::new(move || Ok(Box::new(FileStore::open(&state)?) as Box<dyn SendStore>));
    let open_store_read_only: OpenStoreReadOnly =
        Arc::new(move || -> Result<Option<Box<dyn SendStore>>, StoreError> {
            let store = FileStore::open_read_only(&read_only)?;
            Ok(store.map(|s| Box::new(s) as Box<dyn SendStore>))
        });
    Sending {
        messenger: Arc::new(fake.source()),
        open_store,
        open_store_read_only,
        host: Some(SendHost::new(HOST).expect("a send host")),
    }
}

/// The config of a send server: the public host name, the send record.
pub fn send_config(fake: &SendFake, limits: Limits) -> Config {
    Config {
        allowed_host: Some(HOST.to_owned()),
        web_root: None,
        limits,
        sending: Some(sending(fake)),
        creating: None,
        attaching: None,
    }
}

/// An in-process server over `fake`, with the messaging proofs' clock.
pub fn serve_config(fake: &SendFake, config: Config) -> TestServer {
    let listener = openwiz_server::bind(0).expect("bind loopback");
    let log = Arc::new(Mutex::new(Vec::new()));
    let lines = log.clone();
    let sink: Log = Arc::new(move |line: &str| lines.lock().unwrap().push(line.to_owned()));
    let server = openwiz_server::start(
        listener,
        config,
        Arc::new(fake.source()),
        Arc::new(msg::clock()),
        sink,
    )
    .expect("start the server");
    let addr = server.local_addr();
    TestServer { server, addr, log }
}

pub fn serve_send(fake: &SendFake) -> TestServer {
    serve_config(fake, send_config(fake, Limits::default()))
}

pub fn serve_send_limits(fake: &SendFake, limits: Limits) -> TestServer {
    serve_config(fake, send_config(fake, limits))
}

/// The headers a same-origin page sends with a send, `Host` first.
pub fn good_headers() -> Vec<(String, String)> {
    [
        ("Host", HOST),
        ("Origin", ORIGIN),
        ("Sec-Fetch-Site", "same-origin"),
        ("X-OpenWiz-Send", "1"),
        ("Content-Type", "application/json"),
        ("X-Requested-With", "XMLHttpRequest"),
    ]
    .iter()
    .map(|(n, v)| ((*n).to_owned(), (*v).to_owned()))
    .collect()
}

/// `headers` with `name` removed (case-insensitive).
pub fn without(headers: &[(String, String)], name: &str) -> Vec<(String, String)> {
    headers
        .iter()
        .filter(|(n, _)| !n.eq_ignore_ascii_case(name))
        .cloned()
        .collect()
}

/// `headers` with `name` set to `value` (replacing any).
pub fn with(headers: &[(String, String)], name: &str, value: &str) -> Vec<(String, String)> {
    let mut out = without(headers, name);
    out.push((name.to_owned(), value.to_owned()));
    out
}

/// A send body.
pub fn body(op_id: &str, mode: &str, text: &str) -> Value {
    json!({ "op_id": op_id, "mode": mode, "text": text })
}

/// The raw request: `method target`, the headers, `Content-Length` for the
/// body (unless `length` is `false`), and the body.
pub fn raw(
    method: &str,
    target: &str,
    headers: &[(String, String)],
    body: &[u8],
    length: bool,
) -> Vec<u8> {
    let mut out = format!("{method} {target} HTTP/1.1\r\n");
    for (n, v) in headers {
        out.push_str(&format!("{n}: {v}\r\n"));
    }
    if length {
        out.push_str(&format!("Content-Length: {}\r\n", body.len()));
    }
    out.push_str("\r\n");
    let mut out = out.into_bytes();
    out.extend_from_slice(body);
    out
}

/// `POST` `body` to the send route of `id` with `headers`.
pub fn post(s: &TestServer, id: &str, headers: &[(String, String)], body: &[u8]) -> Response {
    s.send(&raw("POST", &messages(id), headers, body, true))
}

/// A same-origin send of `value` to `id`.
pub fn send_json(s: &TestServer, id: &str, value: &Value) -> Response {
    post(s, id, &good_headers(), value.to_string().as_bytes())
}

/// `GET target` with the public host name.
pub fn get_public(s: &TestServer, target: &str) -> Response {
    s.send(&raw(
        "GET",
        target,
        &[("Host".to_owned(), HOST.to_owned())],
        b"",
        false,
    ))
}

/// No response carries a CORS header.
pub fn assert_no_cors(what: &str, r: &Response) {
    for (name, _) in &r.headers {
        assert!(
            !name.to_ascii_lowercase().starts_with("access-control-"),
            "{what}: {name}"
        );
    }
}

/// The `openwiz send` arguments for a body, as the contract maps them.
pub fn cli_args(id: &str, value: &Value) -> Vec<String> {
    let mut args = vec![
        "--op-id".to_owned(),
        value["op_id"].as_str().expect("op_id").to_owned(),
    ];
    if value["mode"] == "steer" {
        args.push("--steer".to_owned());
    }
    if value["resume_paused_queue"] == true {
        args.push("--resume-paused-queue".to_owned());
    }
    if value["accept_possible_duplicate"] == true {
        args.push("--accept-possible-duplicate".to_owned());
    }
    args.push("--json".to_owned());
    args.push("--".to_owned());
    args.push(id.to_owned());
    args.push(value["text"].as_str().expect("text").to_owned());
    args
}

/// `openwiz send` in-process for `args`: (exit, stdout, stderr).
pub fn cli(fake: &SendFake, args: &[String]) -> (i32, String, String) {
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    fake.cli(&args, "")
}

/// Holds a real fake-provider tell until the test has checked the occupied slot.
/// Delegates the eventual call unchanged; the test chooses when it may finish.
pub struct HeldTell {
    source: openwiz_adapter_cloudroom::source::CloudRoomSource,
    state: Mutex<(usize, bool)>,
    changed: std::sync::Condvar,
}
impl HeldTell {
    pub fn wait_held(&self) {
        self.wait_held_calls(1);
    }
    pub fn wait_held_calls(&self, calls: usize) {
        let (state, _) = self
            .changed
            .wait_timeout_while(
                self.state.lock().unwrap(),
                std::time::Duration::from_secs(10),
                |s| s.0 < calls,
            )
            .unwrap();
        assert_eq!(
            state.0, calls,
            "the expected tells never reached their gate"
        );
    }
    pub fn open(&self) {
        self.state.lock().unwrap_or_else(|p| p.into_inner()).1 = true;
        self.changed.notify_all();
    }
}
impl Messenger for HeldTell {
    fn name(&self) -> &str {
        Messenger::name(&self.source)
    }
    fn tested_version(&self) -> &str {
        Messenger::tested_version(&self.source)
    }
    fn check_target_id(&self, id: &SessionId) -> Result<(), InvalidRequest> {
        Messenger::check_target_id(&self.source, id)
    }
    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        Messenger::version(&self.source, deadline)
    }
    fn read_target(&self, id: &SessionId, deadline: Instant) -> Result<TargetRecord, SourceError> {
        Messenger::read_target(&self.source, id, deadline)
    }
    fn tell(&self, id: &SessionId, mode: Mode, text: &str, deadline: Instant) -> TellReply {
        let mut state = self.state.lock().unwrap();
        state.0 += 1;
        self.changed.notify_all();
        let (state, _) = self
            .changed
            .wait_timeout_while(state, std::time::Duration::from_secs(10), |s| !s.1)
            .unwrap();
        assert!(state.1, "the test did not release its tell");
        drop(state);
        Messenger::tell(&self.source, id, mode, text, deadline)
    }
}

pub struct ReleaseTell(pub Arc<HeldTell>);
impl Drop for ReleaseTell {
    fn drop(&mut self) {
        self.0.open();
    }
}

pub fn serve_held_tell(fake: &SendFake, limits: Limits) -> (TestServer, Arc<HeldTell>) {
    let gate = Arc::new(HeldTell {
        source: fake.source(),
        state: Mutex::new((0, false)),
        changed: std::sync::Condvar::new(),
    });
    let mut config = send_config(fake, limits);
    config.sending.as_mut().unwrap().messenger = gate.clone();
    (serve_config(fake, config), gate)
}
