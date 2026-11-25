//! Small-model tier for ghost text.
//!
//! Talks to a local llama-server or Ollama over plain loopback HTTP (raw
//! completion, no chat template). The context pack is rendered once, in stable
//! order, and only the typed prefix changes per keystroke, so the server's
//! prefix cache can survive. GS2's engine declares `pub mod blend;` and
//! `pub mod model;` in `ghost/mod.rs` (a file this ticket does not own) and
//! calls [`answer`] from `complete`. The interface tests compile the two
//! modules as siblings, which is the same layout.

use std::io::{ErrorKind, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

pub use super::blend::Tier;
use super::blend::{self, Blended, ModelDraft, RecallHit};

pub const DEFAULT_MODEL: &str = "Qwen3-0.6B-Q4_K_M";
pub const MAX_PREDICT: u32 = 8;
pub const DEFAULT_LOGPROB_GATE: f64 = -0.35;
pub const DEFAULT_CONFIDENCE: f64 = 0.30;
const RESPONSE_LIMIT: usize = 1024 * 1024;
const READ_SLICE: Duration = Duration::from_millis(20);
const CONNECT_TIMEOUT: Duration = Duration::from_millis(200);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Backend {
    LlamaServer,
    Ollama,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Settings {
    pub base_url: String,
    pub backend: Backend,
    pub model: String,
    pub max_tokens: u32,
    pub logprob_gate: f64,
    pub confidence_threshold: f64,
}

impl Settings {
    pub fn llama(base_url: impl Into<String>) -> Self {
        Self::with_backend(base_url.into(), Backend::LlamaServer)
    }

    pub fn ollama(base_url: impl Into<String>) -> Self {
        Self::with_backend(base_url.into(), Backend::Ollama)
    }

    /// Ghost settings JSON. A missing server, a non-loopback URL, or a body
    /// that is not JSON yields settings that never dial out.
    pub fn from_json(text: &str) -> Self {
        let Ok(value) = serde_json::from_str::<Value>(text) else {
            return Self::off();
        };
        let backend = match value.get("model_backend").and_then(Value::as_str) {
            Some("ollama") => Backend::Ollama,
            _ => Backend::LlamaServer,
        };
        let mut settings = Self::with_backend(
            value
                .get("model_base_url")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned(),
            backend,
        );
        if let Some(model) = value.get("model").and_then(Value::as_str)
            && !model.is_empty()
        {
            settings.model = model.to_owned();
        }
        if let Some(gate) = value.get("logprob_gate").and_then(Value::as_f64)
            && gate.is_finite()
        {
            settings.logprob_gate = gate;
        }
        if let Some(threshold) = value.get("confidence_threshold").and_then(Value::as_f64)
            && (0.0..=1.0).contains(&threshold)
        {
            settings.confidence_threshold = threshold;
        }
        if let Some(tokens) = value.get("max_tokens").and_then(Value::as_u64) {
            settings.max_tokens = u32::try_from(tokens)
                .unwrap_or(MAX_PREDICT)
                .clamp(1, MAX_PREDICT);
        }
        if endpoint(&settings.base_url).is_none() {
            settings.base_url.clear();
        }
        settings
    }

    fn with_backend(base_url: String, backend: Backend) -> Self {
        Self {
            base_url,
            backend,
            model: DEFAULT_MODEL.to_owned(),
            max_tokens: MAX_PREDICT,
            logprob_gate: DEFAULT_LOGPROB_GATE,
            confidence_threshold: DEFAULT_CONFIDENCE,
        }
    }

    fn off() -> Self {
        Self::with_backend(String::new(), Backend::LlamaServer)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Turn {
    pub role: String,
    pub text: String,
    pub asks_user: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ContextPack {
    pub phrases: Vec<String>,
    pub tone: String,
    pub never_suggest: Vec<String>,
    pub glossary: Vec<(String, String)>,
    pub specs: Vec<(u64, String)>,
    pub tickets: Vec<(u64, String, String)>,
    pub grills: Vec<(String, String, String)>,
    pub session_id: String,
    pub agent: String,
    pub turns: Vec<Turn>,
}

impl ContextPack {
    pub fn from_value(value: &Value) -> Option<Self> {
        let skill = value.get("skill")?;
        let open = value.get("open_work")?;
        let conversation = value.get("conversation")?;
        Some(Self {
            phrases: strings(skill.get("phrases")?)?,
            tone: skill.get("tone")?.as_str()?.to_owned(),
            never_suggest: strings(skill.get("never_suggest")?)?,
            glossary: glossary(value.get("glossary")?)?,
            specs: spec_rows(open.get("specs")?)?,
            tickets: ticket_rows(open.get("tickets")?)?,
            grills: grill_rows(open.get("grills")?)?,
            session_id: conversation.get("session_id")?.as_str()?.to_owned(),
            agent: conversation.get("agent")?.as_str()?.to_owned(),
            turns: turns(conversation.get("turns")?)?,
        })
    }
}

/// The bytes that stay identical across keystrokes of one message.
pub fn cached_prefix(pack: &ContextPack) -> String {
    let mut out = String::new();
    out.push_str("skill\n");
    for phrase in &pack.phrases {
        push_line(&mut out, "phrase", phrase);
    }
    push_line(&mut out, "tone", &pack.tone);
    for phrase in &pack.never_suggest {
        push_line(&mut out, "never", phrase);
    }
    out.push_str("glossary\n");
    for (term, meaning) in &pack.glossary {
        out.push_str("term: ");
        out.push_str(term);
        out.push_str(" = ");
        out.push_str(meaning);
        out.push('\n');
    }
    out.push_str("open_work\n");
    for (number, title) in &pack.specs {
        out.push_str(&format!("spec: {number} {title}\n"));
    }
    for (number, title, action) in &pack.tickets {
        out.push_str(&format!("ticket: {number} {title} | {action}\n"));
    }
    for (code, question, recommended) in &pack.grills {
        out.push_str(&format!("grill: {code} {recommended} | {question}\n"));
    }
    out.push_str("conversation\n");
    push_line(&mut out, "session", &pack.session_id);
    push_line(&mut out, "agent", &pack.agent);
    for turn in &pack.turns {
        let asks = if turn.asks_user { "true" } else { "false" };
        out.push_str(&format!("turn: {} asks={asks}: {}\n", turn.role, turn.text));
    }
    out.push('\n');
    out
}

#[derive(Clone, Debug)]
pub struct Session {
    state: Arc<Mutex<State>>,
}

#[derive(Debug)]
struct State {
    seq: u64,
    prefix: String,
    live: bool,
}

impl Session {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(State {
                seq: 0,
                prefix: String::new(),
                live: false,
            })),
        }
    }

    /// Record that the user has typed `prefix` without starting a completion.
    /// A reply still in flight for an older prefix is then stale.
    pub fn note_typed(&self, prefix: &str) {
        let mut state = lock(&self.state);
        state.prefix = prefix.to_owned();
        state.live = true;
    }

    fn begin(&self, seq: u64, prefix: &str) -> bool {
        let mut state = lock(&self.state);
        if state.live && seq < state.seq {
            return false;
        }
        state.live = true;
        state.seq = seq;
        state.prefix = prefix.to_owned();
        true
    }

    fn stale(&self, seq: u64, prefix: &str) -> bool {
        let state = lock(&self.state);
        !state.live || state.seq != seq || state.prefix != prefix
    }
}

impl Default for Session {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Suggestion {
    pub id: String,
    pub text: String,
    pub full_text: String,
    pub tier: Tier,
    pub confidence: f64,
    pub latency_ms: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Answer {
    Suggestion(Suggestion),
    /// The gate held both tiers back. Not an error.
    None,
    /// A newer seq superseded this call, or the user has typed past its prefix.
    Dropped,
}

/// One keystroke. Never errors when the model server is absent: the reply is
/// recall, or [`Answer::None`] when recall is not confident either.
pub fn answer(
    session: &Session,
    settings: &Settings,
    pack: &ContextPack,
    typed: &str,
    seq: u64,
    recall: Option<RecallHit>,
) -> Answer {
    if !session.begin(seq, typed) {
        return Answer::Dropped;
    }
    let started = Instant::now();
    let cached = cached_prefix(pack);
    let (prompt, stripped_space) = compose(&cached, typed);
    let draft = fetch(settings, &prompt, || session.stale(seq, typed));
    if session.stale(seq, typed) {
        return Answer::Dropped;
    }
    let draft = draft.and_then(|mut draft| {
        draft.text = continuation(&draft.text, stripped_space);
        draft.text = finish_text(&draft.text, draft.stopped_limit)?;
        Some(ModelDraft {
            text: draft.text,
            mean_logprob: draft.mean_logprob,
        })
    });
    let blended = blend::blend(
        draft.as_ref(),
        recall.as_ref(),
        settings.confidence_threshold,
        settings.logprob_gate,
        &pack.never_suggest,
    );
    let latency_ms = started.elapsed().as_secs_f64() * 1000.0;
    match blended {
        Some(blended) => Answer::Suggestion(suggestion(typed, blended, seq, latency_ms)),
        None => Answer::None,
    }
}

struct RawDraft {
    text: String,
    mean_logprob: f64,
    stopped_limit: bool,
}

fn suggestion(prefix: &str, blended: Blended, seq: u64, latency_ms: f64) -> Suggestion {
    let id = match blended.tier {
        Tier::Recall => format!("r{seq}"),
        Tier::SmallModel => format!("m{seq}"),
    };
    Suggestion {
        id,
        full_text: format!("{prefix}{}", blended.text),
        text: blended.text,
        tier: blended.tier,
        confidence: blended.confidence,
        latency_ms,
    }
}

fn compose(cached: &str, typed: &str) -> (String, bool) {
    match typed.strip_suffix(' ') {
        Some(rest) => (format!("{cached}{rest}"), true),
        None => (format!("{cached}{typed}"), false),
    }
}

fn continuation(raw: &str, stripped_space: bool) -> String {
    if stripped_space {
        raw.strip_prefix(' ').unwrap_or(raw).to_owned()
    } else {
        raw.to_owned()
    }
}

/// Cut at a newline or sentence end, drop a length-capped partial last word,
/// and keep at most eight words. A single leading space is part of the suffix.
fn finish_text(raw: &str, stopped_limit: bool) -> Option<String> {
    let (cut_nl, newline_cut) = match raw.split_once('\n') {
        Some((head, _)) => (head, true),
        None => (raw, false),
    };
    let (cut, sentence_cut) = match cut_nl.find(['.', '!', '?']) {
        Some(index) => (&cut_nl[..=index], true),
        None => (cut_nl, false),
    };
    let mut text = cut.trim_end().to_owned();
    if stopped_limit && !newline_cut && !sentence_cut {
        match text.rsplit_once(' ') {
            Some((head, _)) => text = head.trim_end().to_owned(),
            None => return None,
        }
    }
    if text.is_empty() {
        return None;
    }
    let leading = if text.starts_with(' ') { " " } else { "" };
    let words: Vec<&str> = text.split_whitespace().take(MAX_PREDICT as usize).collect();
    if words.is_empty() {
        return None;
    }
    Some(format!("{leading}{}", words.join(" ")))
}

fn fetch(settings: &Settings, prompt: &str, mut cancel: impl FnMut() -> bool) -> Option<RawDraft> {
    let (addr, host) = endpoint(&settings.base_url)?;
    if cancel() {
        return None;
    }
    let body = request_body(settings, prompt);
    let bytes = body.as_bytes();
    let path = match settings.backend {
        Backend::LlamaServer => "/completion",
        Backend::Ollama => "/api/generate",
    };
    let payload = match post(&addr, &host, path, bytes, &mut cancel) {
        Ok(payload) => payload,
        Err(Call::Cancelled) => return None,
        Err(Call::Unavailable) => return None,
    };
    if cancel() {
        return None;
    }
    let value: Value = serde_json::from_slice(&payload).ok()?;
    decode(&value, settings.backend)
}

fn request_body(settings: &Settings, prompt: &str) -> String {
    let predict = settings.max_tokens.clamp(1, MAX_PREDICT);
    let stop = ["\n", ".", "!", "?"];
    let value = match settings.backend {
        Backend::LlamaServer => json!({
            "prompt": prompt,
            "n_predict": predict,
            "temperature": 0,
            "cache_prompt": true,
            "stop": stop,
            "n_probs": 1,
            "stream": false,
        }),
        Backend::Ollama => json!({
            "model": settings.model,
            "prompt": prompt,
            "raw": true,
            "stream": false,
            "options": {
                "num_predict": predict,
                "temperature": 0,
                "stop": stop,
            },
        }),
    };
    value.to_string()
}

enum Call {
    Cancelled,
    Unavailable,
}

fn post(
    addr: &SocketAddr,
    host: &str,
    path: &str,
    body: &[u8],
    cancel: &mut impl FnMut() -> bool,
) -> Result<Vec<u8>, Call> {
    if cancel() {
        return Err(Call::Cancelled);
    }
    let mut stream =
        TcpStream::connect_timeout(addr, CONNECT_TIMEOUT).map_err(|_| Call::Unavailable)?;
    stream.set_nodelay(true).map_err(|_| Call::Unavailable)?;
    stream
        .set_read_timeout(Some(READ_SLICE))
        .map_err(|_| Call::Unavailable)?;
    stream
        .set_write_timeout(Some(CONNECT_TIMEOUT))
        .map_err(|_| Call::Unavailable)?;
    let head = format!(
        "POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream
        .write_all(head.as_bytes())
        .and_then(|()| stream.write_all(body))
        .map_err(|_| Call::Unavailable)?;
    let mut acc = Vec::new();
    loop {
        if cancel() {
            let _ = stream.shutdown(std::net::Shutdown::Both);
            return Err(Call::Cancelled);
        }
        let mut buf = [0u8; 2048];
        match stream.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                acc.extend_from_slice(&buf[..n]);
                if acc.len() > RESPONSE_LIMIT {
                    return Err(Call::Unavailable);
                }
                if let Some(body) = http_body(&acc) {
                    return status_ok(&acc).then_some(body).ok_or(Call::Unavailable);
                }
            }
            Err(error)
                if error.kind() == ErrorKind::TimedOut || error.kind() == ErrorKind::WouldBlock => {
            }
            Err(_) => return Err(Call::Unavailable),
        }
    }
    let body = http_body(&acc).ok_or(Call::Unavailable)?;
    status_ok(&acc).then_some(body).ok_or(Call::Unavailable)
}

fn status_ok(bytes: &[u8]) -> bool {
    let line = bytes.split(|&b| b == b'\n').next().unwrap_or_default();
    let text = String::from_utf8_lossy(line);
    text.split_whitespace().nth(1) == Some("200")
}

fn http_body(bytes: &[u8]) -> Option<Vec<u8>> {
    let end = bytes.windows(4).position(|window| window == b"\r\n\r\n")?;
    let header = String::from_utf8(bytes[..end].to_vec()).ok()?;
    let length = content_length(&header)?;
    let body = &bytes[end + 4..];
    if body.len() < length {
        return None;
    }
    Some(body[..length].to_vec())
}

fn content_length(header: &str) -> Option<usize> {
    header.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse().ok())
            .flatten()
    })
}

fn endpoint(url: &str) -> Option<(SocketAddr, String)> {
    let rest = url.strip_prefix("http://")?;
    let authority = match rest.split_once('/') {
        Some((authority, "")) => authority,
        Some(_) => return None,
        None => rest,
    };
    if authority.is_empty() || authority.contains('@') {
        return None;
    }
    let (host, port) = authority.rsplit_once(':')?;
    if host != "127.0.0.1" && host != "localhost" {
        return None;
    }
    let port: u16 = port.parse().ok()?;
    if port == 0 {
        return None;
    }
    Some((
        SocketAddr::from((Ipv4Addr::LOCALHOST, port)),
        format!("{host}:{port}"),
    ))
}

fn decode(value: &Value, backend: Backend) -> Option<RawDraft> {
    match backend {
        Backend::LlamaServer => {
            let text = value.get("content")?.as_str()?.to_owned();
            let mean = llama_mean(value.get("completion_probabilities")?)?;
            let stopped_limit = value
                .get("stopped_limit")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            Some(RawDraft {
                text,
                mean_logprob: mean,
                stopped_limit,
            })
        }
        Backend::Ollama => {
            let text = value.get("response")?.as_str()?.to_owned();
            let mean = ollama_mean(value.get("logprobs")?)?;
            Some(RawDraft {
                text,
                mean_logprob: mean,
                stopped_limit: false,
            })
        }
    }
}

fn llama_mean(tokens: &Value) -> Option<f64> {
    let tokens = tokens.as_array()?;
    let mut sum = 0.0;
    let mut count = 0.0;
    for token in tokens {
        let top = token.get("probs")?.as_array()?.first()?;
        sum += token_logprob(top)?;
        count += 1.0;
    }
    (count > 0.0).then_some(sum / count)
}

fn ollama_mean(tokens: &Value) -> Option<f64> {
    let tokens = tokens.as_array()?;
    let mut sum = 0.0;
    let mut count = 0.0;
    for token in tokens {
        sum += token.get("logprob")?.as_f64()?;
        count += 1.0;
    }
    (count > 0.0).then_some(sum / count)
}

fn token_logprob(top: &Value) -> Option<f64> {
    if let Some(logprob) = top.get("logprob").and_then(Value::as_f64) {
        return logprob.is_finite().then_some(logprob);
    }
    let prob = top.get("prob")?.as_f64()?;
    (prob > 0.0 && prob.is_finite()).then(|| prob.ln())
}

fn push_line(out: &mut String, label: &str, value: &str) {
    out.push_str(label);
    out.push_str(": ");
    out.push_str(value);
    out.push('\n');
}

fn strings(value: &Value) -> Option<Vec<String>> {
    value
        .as_array()?
        .iter()
        .map(|item| item.as_str().map(str::to_owned))
        .collect::<Option<Vec<_>>>()
}

fn glossary(value: &Value) -> Option<Vec<(String, String)>> {
    value
        .as_array()?
        .iter()
        .map(|item| {
            Some((
                item.get("term")?.as_str()?.to_owned(),
                item.get("meaning")?.as_str()?.to_owned(),
            ))
        })
        .collect()
}

fn spec_rows(value: &Value) -> Option<Vec<(u64, String)>> {
    value
        .as_array()?
        .iter()
        .map(|item| {
            Some((
                item.get("number")?.as_u64()?,
                item.get("title")?.as_str()?.to_owned(),
            ))
        })
        .collect()
}

fn ticket_rows(value: &Value) -> Option<Vec<(u64, String, String)>> {
    value
        .as_array()?
        .iter()
        .map(|item| {
            Some((
                item.get("number")?.as_u64()?,
                item.get("title")?.as_str()?.to_owned(),
                item.get("action")?.as_str()?.to_owned(),
            ))
        })
        .collect()
}

fn grill_rows(value: &Value) -> Option<Vec<(String, String, String)>> {
    value
        .as_array()?
        .iter()
        .map(|item| {
            Some((
                item.get("code")?.as_str()?.to_owned(),
                item.get("question")?.as_str()?.to_owned(),
                item.get("recommended")?.as_str()?.to_owned(),
            ))
        })
        .collect()
}

fn turns(value: &Value) -> Option<Vec<Turn>> {
    value
        .as_array()?
        .iter()
        .map(|item| {
            Some(Turn {
                role: item.get("role")?.as_str()?.to_owned(),
                text: item.get("text")?.as_str()?.to_owned(),
                asks_user: item.get("asks_user")?.as_bool()?,
            })
        })
        .collect()
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poison| poison.into_inner())
}
