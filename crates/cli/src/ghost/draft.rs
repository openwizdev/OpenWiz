use std::fmt;
use std::fs;
use std::io::{self, BufRead, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Instant;

use serde::Deserialize;
use serde::de::{self, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value, json};

const SCHEMA: &str = "openwiz.ghost.v1";
const MAX_LINE: usize = 1 << 20;
const MAX_HARNESS_BYTES: usize = 65_536;
const SURFACES: &[&str] = &["openwiz-app", "t3-code", "bb-plugin", "cli", "other"];
const STDIO_ROUTES: &[&str] = &[
    "health", "context", "turns", "complete", "draft", "feedback", "bench",
];

const INVALID: &str = "The request does not match ghost.v1.";
const UNKNOWN: &str = "Route is not a ghost.v1 stdio route.";
const NOT_YET: &str = "This ghost route is not built yet.";
const UNAVAILABLE: &str = "The configured draft harness is unavailable.";
const TOO_BIG: &str = "The request is larger than 1 MiB.";

pub fn serve(
    settings: &[u8],
    pack: &[u8],
    mut input: impl BufRead,
    mut output: impl Write,
) -> io::Result<()> {
    let mut engine = Engine::new(settings, pack);
    loop {
        match read_limited(&mut input, MAX_LINE)? {
            None => return Ok(()),
            Some(Line::TooBig) => {
                write_reply(
                    &mut output,
                    &Reply::error(Value::Null, 413, "payload_too_large", TOO_BIG),
                )?;
            }
            Some(Line::Bytes(bytes)) => {
                let Ok(line) = String::from_utf8(bytes) else {
                    write_reply(
                        &mut output,
                        &Reply::error(Value::Null, 400, "invalid_request", INVALID),
                    )?;
                    continue;
                };
                if line.trim().is_empty() {
                    continue;
                }
                let reply = engine.handle(line.trim());
                write_reply(&mut output, &reply)?;
            }
        }
    }
}

enum Line {
    TooBig,
    Bytes(Vec<u8>),
}

fn read_limited(input: &mut impl BufRead, cap: usize) -> io::Result<Option<Line>> {
    let mut buf = Vec::new();
    loop {
        let data = input.fill_buf()?;
        if data.is_empty() {
            if buf.is_empty() {
                return Ok(None);
            }
            return Ok(Some(Line::Bytes(buf)));
        }
        if let Some(i) = data.iter().position(|byte| *byte == b'\n') {
            if buf.len() + i > cap {
                input.consume(i + 1);
                return Ok(Some(Line::TooBig));
            }
            buf.extend_from_slice(&data[..=i]);
            input.consume(i + 1);
            return Ok(Some(Line::Bytes(buf)));
        }
        if buf.len() + data.len() > cap {
            drain_line(input)?;
            return Ok(Some(Line::TooBig));
        }
        buf.extend_from_slice(data);
        let n = data.len();
        input.consume(n);
    }
}

fn drain_line(input: &mut impl BufRead) -> io::Result<()> {
    loop {
        let data = input.fill_buf()?;
        if data.is_empty() {
            return Ok(());
        }
        if let Some(i) = data.iter().position(|byte| *byte == b'\n') {
            input.consume(i + 1);
            return Ok(());
        }
        let n = data.len();
        input.consume(n);
    }
}

struct Reply {
    id: Value,
    status: u16,
    body: Value,
}

impl Reply {
    fn error(id: Value, status: u16, code: &str, message: &str) -> Self {
        Self {
            id,
            status,
            body: json!({"refusal": {"code": code, "message": message}}),
        }
    }
}

fn write_reply(output: &mut impl Write, reply: &Reply) -> io::Result<()> {
    let line = json!({"id": reply.id, "status": reply.status, "body": reply.body});
    writeln!(output, "{line}")?;
    output.flush()
}

struct Engine {
    cli: Option<PathBuf>,
    pack: Option<Value>,
    next_id: u64,
    slot: Option<Slot>,
}

struct Slot {
    key: String,
    session_id: String,
    state: State,
}

enum State {
    Running(thread::JoinHandle<Outcome>),
    Ready(Outcome),
}

struct Outcome {
    id: String,
    text: Option<String>,
    latency_ms: f64,
}

impl Engine {
    fn new(settings: &[u8], pack: &[u8]) -> Self {
        Self {
            cli: configured_cli(settings),
            pack: load_pack(pack),
            next_id: 0,
            slot: None,
        }
    }

    fn handle(&mut self, line: &str) -> Reply {
        let Ok(value) = parse_unique(line.as_bytes()) else {
            return Reply::error(Value::Null, 400, "invalid_request", INVALID);
        };
        let Some(env) = envelope(&value) else {
            return Reply::error(Value::Null, 400, "invalid_request", INVALID);
        };
        let id = Value::String(env.id);
        if env.route == "pair" {
            return Reply::error(id, 404, "unknown_route", UNKNOWN);
        }
        if !STDIO_ROUTES.contains(&env.route.as_str()) {
            return Reply::error(id, 400, "invalid_request", INVALID);
        }
        let (status, body) = match env.route.as_str() {
            "turns" => self.on_turns(&env.body),
            "draft" => self.on_draft(&env.body),
            _ => (501, refusal("not_implemented", NOT_YET)),
        };
        Reply { id, status, body }
    }

    fn on_turns(&mut self, body: &Value) -> (u16, Value) {
        let Some(req) = parse_turns(body) else {
            return (400, refusal("invalid_request", INVALID));
        };
        let Some(revision) = self.revision() else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        if !req.asks {
            return (200, turns_body(&revision, false));
        }
        let Some(cli) = self.cli.clone() else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        let Some(pack) = self.pack.clone() else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        let key = format!(
            "{}\n{}\n{}",
            req.session_id,
            req.agent,
            serde_json::to_string(&req.turns).unwrap_or_default()
        );
        if self.slot.as_ref().is_some_and(|slot| slot.key == key) {
            return (200, turns_body(&revision, true));
        }
        let Ok(prompt) = serde_json::to_vec(&json!({
            "schema": SCHEMA,
            "kind": "draft_prompt",
            "pack": pack,
            "session_id": req.session_id,
            "agent": req.agent,
            "turns": req.turns,
        })) else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        self.settle();
        let id = self.alloc_id();
        let session_id = req.session_id;
        let handle = thread::spawn(move || match run_harness(&cli, &prompt) {
            Ok((text, latency_ms)) => Outcome {
                id,
                text: Some(text),
                latency_ms,
            },
            Err(()) => Outcome {
                id,
                text: None,
                latency_ms: 0.0,
            },
        });
        self.slot = Some(Slot {
            key,
            session_id,
            state: State::Running(handle),
        });
        (200, turns_body(&revision, true))
    }

    fn on_draft(&mut self, body: &Value) -> (u16, Value) {
        let Some(session_id) = parse_draft(body) else {
            return (400, refusal("invalid_request", INVALID));
        };
        let queued = self
            .slot
            .as_ref()
            .is_some_and(|slot| slot.session_id == session_id);
        if !queued {
            return (200, json!({"schema": SCHEMA, "draft": null}));
        }
        self.settle();
        let Some(slot) = self.slot.as_ref() else {
            return (200, json!({"schema": SCHEMA, "draft": null}));
        };
        let State::Ready(outcome) = &slot.state else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        let Some(text) = outcome.text.clone() else {
            return (503, refusal("unavailable", UNAVAILABLE));
        };
        (
            200,
            json!({
                "schema": SCHEMA,
                "draft": {
                    "id": outcome.id,
                    "text": text,
                    "precomputed": true,
                    "latency_ms": outcome.latency_ms,
                }
            }),
        )
    }

    fn revision(&self) -> Option<String> {
        self.pack
            .as_ref()
            .and_then(|pack| pack.get("revision"))
            .and_then(Value::as_str)
            .filter(|revision| !revision.is_empty())
            .map(str::to_owned)
    }

    fn alloc_id(&mut self) -> String {
        self.next_id += 1;
        format!("drf-{}", self.next_id)
    }

    fn settle(&mut self) {
        let Some(slot) = self.slot.as_mut() else {
            return;
        };
        if !matches!(slot.state, State::Running(_)) {
            return;
        }
        let state = std::mem::replace(
            &mut slot.state,
            State::Ready(Outcome {
                id: "drf-0".to_owned(),
                text: None,
                latency_ms: 0.0,
            }),
        );
        let State::Running(handle) = state else {
            return;
        };
        slot.state = State::Ready(match handle.join() {
            Ok(outcome) => outcome,
            Err(_) => Outcome {
                id: "drf-0".to_owned(),
                text: None,
                latency_ms: 0.0,
            },
        });
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        self.settle();
    }
}

fn turns_body(revision: &str, queued: bool) -> Value {
    json!({
        "schema": SCHEMA,
        "revision": revision,
        "draft_queued": queued,
    })
}

fn refusal(code: &str, message: &str) -> Value {
    json!({"refusal": {"code": code, "message": message}})
}

struct TurnsReq {
    session_id: String,
    agent: String,
    turns: Value,
    asks: bool,
}

fn parse_turns(body: &Value) -> Option<TurnsReq> {
    let obj = exact(body, &["session_id", "agent", "turns"])?;
    let session_id = non_empty(obj.get("session_id")?)?.to_owned();
    let agent = non_empty(obj.get("agent")?)?.to_owned();
    let turns = obj.get("turns")?;
    let list = turns.as_array()?;
    if list.len() > 3 {
        return None;
    }
    for turn in list {
        let turn_obj = exact(turn, &["role", "text", "asks_user"])?;
        let role = turn_obj.get("role")?.as_str()?;
        if role != "user" && role != "agent" {
            return None;
        }
        turn_obj.get("text")?.as_str()?;
        turn_obj.get("asks_user")?.as_bool()?;
    }
    let asks = list
        .last()
        .and_then(|turn| turn.get("asks_user"))
        .and_then(Value::as_bool)
        == Some(true);
    Some(TurnsReq {
        session_id,
        agent,
        turns: turns.clone(),
        asks,
    })
}

fn parse_draft(body: &Value) -> Option<String> {
    let obj = exact(body, &["session_id", "surface"])?;
    let session_id = non_empty(obj.get("session_id")?)?.to_owned();
    let surface = obj.get("surface")?.as_str()?;
    if !SURFACES.contains(&surface) {
        return None;
    }
    Some(session_id)
}

struct Envelope {
    id: String,
    route: String,
    body: Value,
}

fn envelope(value: &Value) -> Option<Envelope> {
    let obj = exact(value, &["id", "route", "body"])?;
    let id = non_empty(obj.get("id")?)?.to_owned();
    let route = non_empty(obj.get("route")?)?.to_owned();
    let body = obj.get("body")?.as_object()?.clone();
    Some(Envelope {
        id,
        route,
        body: Value::Object(body),
    })
}

fn configured_cli(bytes: &[u8]) -> Option<PathBuf> {
    let value = parse_unique(bytes).ok()?;
    let obj = exact(&value, &["cli"])?;
    let path = PathBuf::from(non_empty(obj.get("cli")?)?);
    cli_allowed(&path).then_some(path)
}

fn cli_allowed(path: &Path) -> bool {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return false;
    }
    let Ok(meta) = fs::metadata(path) else {
        return false;
    };
    meta.is_file() && meta.permissions().mode() & 0o111 != 0
}

fn load_pack(bytes: &[u8]) -> Option<Value> {
    let value = parse_unique(bytes).ok()?;
    if !value.is_object() {
        return None;
    }
    non_empty(value.get("revision")?)?;
    Some(value)
}

fn exact<'a>(value: &'a Value, keys: &[&str]) -> Option<&'a Map<String, Value>> {
    let obj = value.as_object()?;
    if obj.len() != keys.len() || keys.iter().any(|key| !obj.contains_key(*key)) {
        return None;
    }
    Some(obj)
}

fn non_empty(value: &Value) -> Option<&str> {
    value.as_str().filter(|text| !text.is_empty())
}

fn run_harness(cli: &Path, prompt: &[u8]) -> Result<(String, f64), ()> {
    let started = Instant::now();
    let mut child = Command::new(cli)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| ())?;
    let Some(stdin) = child.stdin.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(());
    };
    let Some(stdout) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(());
    };
    let Some(stderr) = child.stderr.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(());
    };
    let prompt = prompt.to_vec();
    let writer = thread::spawn(move || {
        let mut stdin = stdin;
        let ok = stdin.write_all(&prompt).is_ok();
        drop(stdin);
        ok
    });
    let out_thread = thread::spawn(move || read_capped(stdout, MAX_HARNESS_BYTES));
    let err_thread = thread::spawn(move || read_capped(stderr, MAX_HARNESS_BYTES));
    let status = child.wait();
    let wrote = writer.join().unwrap_or(false);
    let out = out_thread.join();
    let _ = err_thread.join();
    let out = match out {
        Ok(Ok(bytes)) => bytes,
        _ => return Err(()),
    };
    if !wrote || !status.map_err(|_| ())?.success() {
        return Err(());
    }
    Ok((
        harness_text(&out)?,
        started.elapsed().as_secs_f64() * 1000.0,
    ))
}

fn read_capped(mut reader: impl Read, cap: usize) -> Result<Vec<u8>, ()> {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    loop {
        let n = match reader.read(&mut tmp) {
            Ok(0) => return Ok(buf),
            Ok(n) => n,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(()),
        };
        if buf.len() + n > cap {
            loop {
                match reader.read(&mut tmp) {
                    Ok(0) => return Err(()),
                    Ok(_) => {}
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(_) => return Err(()),
                }
            }
        }
        buf.extend_from_slice(&tmp[..n]);
    }
}

fn harness_text(bytes: &[u8]) -> Result<String, ()> {
    let text = std::str::from_utf8(bytes).map_err(|_| ())?.trim();
    let value = parse_unique(text.as_bytes())?;
    let obj = exact(&value, &["text"]).ok_or(())?;
    non_empty(obj.get("text").ok_or(())?)
        .map(str::to_owned)
        .ok_or(())
}

fn parse_unique(bytes: &[u8]) -> Result<Value, ()> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let Unique(value) = Unique::deserialize(&mut deserializer).map_err(|_| ())?;
    deserializer.end().map_err(|_| ())?;
    Ok(value)
}

struct Unique(Value);

impl<'de> Deserialize<'de> for Unique {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(Once)
    }
}

struct Once;

impl<'de> Visitor<'de> for Once {
    type Value = Unique;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("JSON with each key once")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<Unique, A::Error> {
        let mut map = Map::new();
        while let Some((key, Unique(value))) = access.next_entry::<String, Unique>()? {
            if map.insert(key, value).is_some() {
                return Err(de::Error::custom("duplicate key"));
            }
        }
        Ok(Unique(Value::Object(map)))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<Unique, A::Error> {
        let mut values = Vec::new();
        while let Some(Unique(value)) = access.next_element()? {
            values.push(value);
        }
        Ok(Unique(Value::Array(values)))
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Unique, E> {
        Ok(Unique(Value::Bool(value)))
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Unique, E> {
        Ok(Unique(Value::from(value)))
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Unique, E> {
        Ok(Unique(Value::from(value)))
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Unique, E> {
        serde_json::Number::from_f64(value)
            .map(|number| Unique(Value::Number(number)))
            .ok_or_else(|| de::Error::custom("number"))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Unique, E> {
        Ok(Unique(Value::String(value.to_owned())))
    }

    fn visit_unit<E: de::Error>(self) -> Result<Unique, E> {
        Ok(Unique(Value::Null))
    }
}
