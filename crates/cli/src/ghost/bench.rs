use std::collections::BTreeSet;
use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::de::value::{Error as DeserializeError, StrDeserializer};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::log;

pub const SCHEMA: &str = "openwiz.ghost.v1";
const CONFIDENCE: f64 = 0.5;
const BASELINE_LATENCY_MS: f64 = 1.0;
const SLOW_LATENCY_MS: f64 = 200.0;
const AT: &str = "2026-11-24T12:00:00Z";

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum BenchSource {
    Fixtures,
    Log,
    Sent,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FixtureModel {
    Baseline,
    Slow,
    Weak,
}

impl FixtureModel {
    pub fn parse(value: Option<&str>) -> Result<Self, ()> {
        match value {
            None | Some("baseline") => Ok(Self::Baseline),
            Some("slow") => Ok(Self::Slow),
            Some("weak") => Ok(Self::Weak),
            Some(_) => Err(()),
        }
    }

    fn latency(self) -> f64 {
        match self {
            Self::Slow => SLOW_LATENCY_MS,
            Self::Baseline | Self::Weak => BASELINE_LATENCY_MS,
        }
    }
}

#[derive(Clone)]
struct Live {
    id: String,
    text: String,
    latency_ms: f64,
}

pub fn fixture_suffix(
    context_pack: &Path,
    prefix: &str,
    model: FixtureModel,
) -> Result<Option<String>, String> {
    if model == FixtureModel::Weak {
        return Ok(None);
    }
    let pack = read_json(context_pack)?;
    if log::json_has_duplicate_keys(&fs::read_to_string(context_pack).unwrap_or_default()) {
        return Err("the context pack is not valid".to_owned());
    }
    Ok(suggest(&candidates(&pack)?, prefix))
}

pub fn replay_file(
    replay_path: &Path,
    model: FixtureModel,
    log_state: Option<&Path>,
) -> Result<Value, String> {
    let text = fs::read_to_string(replay_path)
        .map_err(|_| "the replay file could not be read".to_owned())?;
    if log::json_has_duplicate_keys(&text) {
        return Err("the replay file is not valid".to_owned());
    }
    let value: Value =
        serde_json::from_str(&text).map_err(|_| "the replay file is not valid".to_owned())?;
    let (messages, context_name) = parse_replay(&value)?;
    let context = replay_path
        .parent()
        .unwrap_or(Path::new("."))
        .join(context_name);
    let pack_text = fs::read_to_string(&context)
        .map_err(|_| "the context pack could not be read".to_owned())?;
    if log::json_has_duplicate_keys(&pack_text) {
        return Err("the context pack is not valid".to_owned());
    }
    let pack: Value =
        serde_json::from_str(&pack_text).map_err(|_| "the context pack is not valid".to_owned())?;
    replay_loaded(
        &messages,
        &pack,
        None,
        model,
        BenchSource::Fixtures,
        log_state,
    )
}

pub fn replay_sent(
    replay_path: &Path,
    model: FixtureModel,
    skill: Option<&Path>,
    log_state: Option<&Path>,
) -> Result<Value, String> {
    let text = fs::read_to_string(replay_path)
        .map_err(|_| "the replay file could not be read".to_owned())?;
    if log::json_has_duplicate_keys(&text) {
        return Err("the replay file is not valid".to_owned());
    }
    let value: Value =
        serde_json::from_str(&text).map_err(|_| "the replay file is not valid".to_owned())?;
    let (messages, context_name) = parse_replay(&value)?;
    let context = replay_path
        .parent()
        .unwrap_or(Path::new("."))
        .join(context_name);
    let pack_text = fs::read_to_string(&context)
        .map_err(|_| "the context pack could not be read".to_owned())?;
    if log::json_has_duplicate_keys(&pack_text) {
        return Err("the context pack is not valid".to_owned());
    }
    let pack: Value =
        serde_json::from_str(&pack_text).map_err(|_| "the context pack is not valid".to_owned())?;
    let loaded = skill.map(read_skill).transpose()?;
    replay_loaded(
        &messages,
        &pack,
        loaded.as_ref(),
        model,
        BenchSource::Sent,
        log_state,
    )
}

pub fn report_log(path: &Path) -> Result<Value, String> {
    let events = log::read_event_file(path)?;
    report_events(&events)
}

pub fn run_with(
    args: &[OsString],
    out: &mut dyn Write,
    err: &mut dyn Write,
    env: &dyn Fn(&str) -> Option<OsString>,
) -> i32 {
    let parsed = match parse_args(args) {
        Ok(parsed) => parsed,
        Err(message) => return failure(args, 2, "usage", &message, out, err),
    };
    if parsed.help {
        let _ = writeln!(
            out,
            "openwiz ghost bench [--source fixtures|log|sent] [--replay PATH] [--json]\nReplay messages and print the ghost.v1 bench report."
        );
        return 0;
    }
    let model = match FixtureModel::parse(
        env("OPENWIZ_GHOST_FIXTURE_MODEL")
            .as_deref()
            .and_then(|v| v.to_str()),
    ) {
        Ok(model) => model,
        Err(()) => {
            return failure(
                args,
                2,
                "usage",
                "OPENWIZ_GHOST_FIXTURE_MODEL must be baseline, slow or weak.",
                out,
                err,
            );
        }
    };
    let state = log::state_dir(env).ok();
    let report = match parsed.source {
        BenchSource::Fixtures => {
            let path = parsed
                .replay
                .unwrap_or_else(|| fixtures_dir(env).join("replay-set.json"));
            replay_file(&path, model, state.as_deref())
        }
        BenchSource::Sent => {
            let path = match parsed
                .replay
                .or_else(|| state.as_ref().map(|dir| dir.join("ghost/sent.json")))
            {
                Some(path) => path,
                None => return failure(args, 1, "unavailable", "no state directory", out, err),
            };
            let skill = match ghost_home(env) {
                Ok(Some(home)) => Some(home.join("skill.json")),
                Ok(None) => None,
                Err(message) => return failure(args, 1, "unavailable", &message, out, err),
            };
            replay_sent(&path, model, skill.as_deref(), state.as_deref())
        }
        BenchSource::Log => {
            let path = match parsed
                .replay
                .or_else(|| state.as_ref().map(|dir| log::events_path(dir)))
            {
                Some(path) => path,
                None => return failure(args, 1, "unavailable", "no state directory", out, err),
            };
            report_log(&path)
        }
    };
    match report {
        Ok(report) => {
            if writeln!(out, "{report}").is_err() {
                return 1;
            }
            0
        }
        Err(message) => failure(args, 1, "unavailable", &message, out, err),
    }
}

struct Args {
    help: bool,
    source: BenchSource,
    replay: Option<PathBuf>,
}

fn parse_args(args: &[OsString]) -> Result<Args, String> {
    let mut source = BenchSource::Fixtures;
    let mut replay = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i]
            .to_str()
            .ok_or_else(|| "an argument is not valid text.".to_owned())?;
        match arg {
            "--json" => {}
            "--help" | "-h" => {
                return Ok(Args {
                    help: true,
                    source,
                    replay,
                });
            }
            "--source" => {
                i += 1;
                let value = args
                    .get(i)
                    .and_then(|v| v.to_str())
                    .ok_or_else(|| "source needs fixtures, log or sent.".to_owned())?;
                source = BenchSource::deserialize(StrDeserializer::<DeserializeError>::new(value))
                    .map_err(|_| "source must be fixtures, log or sent.".to_owned())?;
            }
            "--replay" => {
                i += 1;
                let value = args
                    .get(i)
                    .filter(|v| !v.is_empty())
                    .ok_or_else(|| "replay needs a path.".to_owned())?;
                replay = Some(PathBuf::from(value));
            }
            _ => return Err("unknown argument; see openwiz ghost bench --help.".to_owned()),
        }
        i += 1;
    }
    Ok(Args {
        help: false,
        source,
        replay,
    })
}

fn fixtures_dir(env: &dyn Fn(&str) -> Option<OsString>) -> PathBuf {
    env("OPENWIZ_GHOST_FIXTURES")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../contracts/fixtures/ghost")
        })
}

struct Message {
    surface: String,
    session_id: String,
    text: String,
}

fn parse_replay(value: &Value) -> Result<(Vec<Message>, String), String> {
    let obj = value
        .as_object()
        .ok_or_else(|| "the replay file is not valid".to_owned())?;
    if obj.len() != 4
        || value.get("schema") != Some(&json!(SCHEMA))
        || value.get("kind") != Some(&json!("replay_fixtures"))
    {
        return Err("the replay file is not valid".to_owned());
    }
    let context = value
        .get("context_fixture")
        .and_then(Value::as_str)
        .filter(|s| {
            !s.is_empty()
                && !s.contains('\0')
                && Path::new(s)
                    .components()
                    .all(|c| !matches!(c, std::path::Component::ParentDir))
        })
        .ok_or_else(|| "the replay file is not valid".to_owned())?;
    let messages = value
        .get("messages")
        .and_then(Value::as_array)
        .filter(|items| !items.is_empty())
        .ok_or_else(|| "the replay file is not valid".to_owned())?;
    let mut out = Vec::new();
    for item in messages {
        let obj = item
            .as_object()
            .filter(|obj| obj.len() == 4)
            .ok_or_else(|| "the replay file is not valid".to_owned())?;
        let id = obj
            .get("id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| "the replay file is not valid".to_owned())?;
        let _ = id;
        let surface = obj
            .get("surface")
            .and_then(Value::as_str)
            .filter(|s| is_surface(s))
            .ok_or_else(|| "the replay file is not valid".to_owned())?;
        let session_id = obj
            .get("session_id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| "the replay file is not valid".to_owned())?;
        let text = obj
            .get("text")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| "the replay file is not valid".to_owned())?;
        out.push(Message {
            surface: surface.to_owned(),
            session_id: session_id.to_owned(),
            text: text.to_owned(),
        });
    }
    Ok((out, context.to_owned()))
}

fn is_surface(value: &str) -> bool {
    matches!(
        value,
        "openwiz-app" | "t3-code" | "bb-plugin" | "cli" | "other"
    )
}

struct SkillFile {
    phrases: Vec<String>,
    codes: Vec<String>,
    never: Vec<String>,
}

fn ghost_home(env: &dyn Fn(&str) -> Option<OsString>) -> Result<Option<PathBuf>, String> {
    let Some(value) = env("OPENWIZ_GHOST_HOME").filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let path = PathBuf::from(value);
    if !path.is_absolute()
        || path
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err("OPENWIZ_GHOST_HOME must be an absolute path".to_owned());
    }
    let meta =
        fs::symlink_metadata(&path).map_err(|_| "the ghost home could not be read".to_owned())?;
    if meta.file_type().is_symlink() || !meta.is_dir() {
        return Err("the ghost home must be a directory".to_owned());
    }
    Ok(Some(path))
}

fn read_skill(path: &Path) -> Result<SkillFile, String> {
    let meta =
        fs::symlink_metadata(path).map_err(|_| "the skill file could not be read".to_owned())?;
    if meta.file_type().is_symlink() || !meta.is_file() {
        return Err("the skill file must be a regular file".to_owned());
    }
    let text =
        fs::read_to_string(path).map_err(|_| "the skill file could not be read".to_owned())?;
    if log::json_has_duplicate_keys(&text) {
        return Err("the skill file is not valid".to_owned());
    }
    let value: Value =
        serde_json::from_str(&text).map_err(|_| "the skill file is not valid".to_owned())?;
    let obj = value
        .as_object()
        .filter(|obj| obj.len() == 4)
        .ok_or_else(|| "the skill file is not valid".to_owned())?;
    for key in ["phrases", "codes", "tone", "never_suggest"] {
        if !obj.contains_key(key) {
            return Err("the skill file is not valid".to_owned());
        }
    }
    if obj.get("tone").and_then(Value::as_str).is_none() {
        return Err("the skill file is not valid".to_owned());
    }
    Ok(SkillFile {
        phrases: string_list(obj.get("phrases"))?,
        codes: string_list(obj.get("codes"))?,
        never: string_list(obj.get("never_suggest"))?,
    })
}

fn string_list(value: Option<&Value>) -> Result<Vec<String>, String> {
    let items = value
        .and_then(Value::as_array)
        .ok_or_else(|| "the skill file is not valid".to_owned())?;
    let mut out = Vec::new();
    for item in items {
        let text = item
            .as_str()
            .filter(|text| !text.is_empty())
            .ok_or_else(|| "the skill file is not valid".to_owned())?;
        if out.iter().any(|have| have == text) {
            return Err("the skill file is not valid".to_owned());
        }
        out.push(text.to_owned());
    }
    Ok(out)
}

fn replay_loaded(
    messages: &[Message],
    pack: &Value,
    skill: Option<&SkillFile>,
    model: FixtureModel,
    source: BenchSource,
    log_state: Option<&Path>,
) -> Result<Value, String> {
    let known = match skill {
        Some(skill) => skill_candidates(skill),
        None => candidates(pack)?,
    };
    let mut events = Vec::new();
    let mut surface_messages: Vec<(String, u64)> = Vec::new();
    for (index, message) in messages.iter().enumerate() {
        add_count(&mut surface_messages, &message.surface);
        events.extend(replay_message(index + 1, message, &known, model));
    }
    if let Some(state) = log_state {
        for event in &events {
            log::append_event(state, event)?;
        }
    }
    report(source, messages.len() as u64, &surface_messages, &events)
}

fn skill_candidates(skill: &SkillFile) -> Vec<String> {
    let mut out = Vec::new();
    for text in skill.phrases.iter().chain(skill.codes.iter()) {
        if !skill.never.iter().any(|blocked| blocked == text) {
            push_unique(&mut out, text);
        }
    }
    out
}

fn candidates(pack: &Value) -> Result<Vec<String>, String> {
    let mut out = Vec::new();
    let phrases = pack
        .pointer("/skill/phrases")
        .and_then(Value::as_array)
        .ok_or_else(|| "the context pack is not valid".to_owned())?;
    for phrase in phrases {
        push_unique(
            &mut out,
            phrase
                .as_str()
                .ok_or_else(|| "the context pack is not valid".to_owned())?,
        );
    }
    let grills = pack
        .pointer("/open_work/grills")
        .and_then(Value::as_array)
        .ok_or_else(|| "the context pack is not valid".to_owned())?;
    for grill in grills {
        let code = grill
            .get("code")
            .and_then(Value::as_str)
            .ok_or_else(|| "the context pack is not valid".to_owned())?;
        let recommended = grill
            .get("recommended")
            .and_then(Value::as_str)
            .ok_or_else(|| "the context pack is not valid".to_owned())?;
        push_unique(&mut out, &format!("{code} {recommended}"));
    }
    let tickets = pack
        .pointer("/open_work/tickets")
        .and_then(Value::as_array)
        .ok_or_else(|| "the context pack is not valid".to_owned())?;
    for ticket in tickets {
        for key in ["action", "title"] {
            push_unique(
                &mut out,
                ticket
                    .get(key)
                    .and_then(Value::as_str)
                    .ok_or_else(|| "the context pack is not valid".to_owned())?,
            );
        }
    }
    let specs = pack
        .pointer("/open_work/specs")
        .and_then(Value::as_array)
        .ok_or_else(|| "the context pack is not valid".to_owned())?;
    for spec in specs {
        push_unique(
            &mut out,
            spec.get("title")
                .and_then(Value::as_str)
                .ok_or_else(|| "the context pack is not valid".to_owned())?,
        );
    }
    let glossary = pack
        .get("glossary")
        .and_then(Value::as_array)
        .ok_or_else(|| "the context pack is not valid".to_owned())?;
    for term in glossary {
        push_unique(
            &mut out,
            term.get("term")
                .and_then(Value::as_str)
                .ok_or_else(|| "the context pack is not valid".to_owned())?,
        );
    }
    Ok(out)
}

fn push_unique(out: &mut Vec<String>, text: &str) {
    if !text.is_empty() && !out.iter().any(|have| have == text) {
        out.push(text.to_owned());
    }
}

fn suggest(known: &[String], prefix: &str) -> Option<String> {
    let mut best: Option<(usize, String)> = None;
    let mut tie = false;
    for candidate in known {
        let Some((len, suffix)) = longest_suffix(prefix, candidate) else {
            continue;
        };
        let current = best.as_ref().map(|(have, text)| (*have, text.clone()));
        match current {
            None => best = Some((len, suffix)),
            Some((have, _)) if len > have => {
                best = Some((len, suffix));
                tie = false;
            }
            Some((have, text)) if len == have && text != suffix => tie = true,
            _ => {}
        }
    }
    if tie {
        None
    } else {
        best.map(|(_, suffix)| suffix)
    }
}

fn longest_suffix(prefix: &str, candidate: &str) -> Option<(usize, String)> {
    let prefix: Vec<char> = prefix.chars().collect();
    let candidate: Vec<char> = candidate.chars().collect();
    let max = prefix.len().min(candidate.len().saturating_sub(1));
    for len in (2..=max).rev() {
        if prefix.ends_with(&candidate[..len]) {
            let suffix: String = candidate[len..].iter().collect();
            let words = suffix.split_whitespace().count();
            if (1..=8).contains(&words) {
                return Some((len, suffix));
            }
        }
    }
    None
}

fn replay_message(
    index: usize,
    message: &Message,
    known: &[String],
    model: FixtureModel,
) -> Vec<Value> {
    let chars: Vec<char> = message.text.chars().collect();
    let mut pos = 0;
    let mut ghost: Option<Live> = None;
    let mut seq = 0u64;
    let mut events = Vec::new();
    while pos < chars.len() {
        if let Some(live) = ghost.clone() {
            let rest: String = chars[pos..].iter().collect();
            if rest.starts_with(&live.text) {
                let n = live.text.chars().count() as u64;
                events.push(event(message, &live, "accepted_all", n));
                pos += live.text.chars().count();
                ghost = None;
                continue;
            }
            let chunk = next_word_chunk(&live.text);
            if !chunk.is_empty() && chunk != live.text && rest.starts_with(&chunk) {
                let n = chunk.chars().count();
                events.push(event(message, &live, "accepted_word", n as u64));
                pos += n;
                let remain: String = live.text.chars().skip(n).collect();
                ghost = if remain.is_empty() {
                    None
                } else {
                    Some(Live {
                        text: remain,
                        ..live
                    })
                };
                continue;
            }
            if rest
                .chars()
                .next()
                .is_some_and(|c| live.text.starts_with(c))
            {
                events.push(event(message, &live, "typed_through", 1));
                pos += 1;
                let remain: String = live.text.chars().skip(1).collect();
                ghost = if remain.is_empty() {
                    None
                } else {
                    Some(Live {
                        text: remain,
                        ..live
                    })
                };
                continue;
            }
            events.push(event(message, &live, "typed_over", 0));
            ghost = None;
        }
        pos += 1;
        if model == FixtureModel::Weak {
            continue;
        }
        let prefix: String = chars[..pos].iter().collect();
        if let Some(suffix) = suggest(known, &prefix) {
            seq += 1;
            let live = Live {
                id: format!("sug_syn_{index}_{seq}"),
                text: suffix,
                latency_ms: model.latency(),
            };
            events.push(event(message, &live, "shown", 0));
            ghost = Some(live);
        }
    }
    events
}

fn next_word_chunk(ghost: &str) -> String {
    let chars: Vec<char> = ghost.chars().collect();
    let mut i = 0;
    while i < chars.len() && chars[i].is_whitespace() {
        i += 1;
    }
    if i == chars.len() {
        return String::new();
    }
    while i < chars.len() && !chars[i].is_whitespace() {
        i += 1;
    }
    if i < chars.len() && chars[i].is_whitespace() {
        i += 1;
    }
    chars[..i].iter().collect()
}

fn event(message: &Message, live: &Live, outcome: &str, chars_accepted: u64) -> Value {
    json!({
        "schema": SCHEMA,
        "kind": "event",
        "at": AT,
        "suggestion_id": live.id,
        "session_id": message.session_id,
        "surface": message.surface,
        "outcome": outcome,
        "tier": "recall",
        "confidence": CONFIDENCE,
        "latency_ms": live.latency_ms,
        "chars_accepted": chars_accepted,
    })
}

fn report_events(events: &[Value]) -> Result<Value, String> {
    let mut sessions = Vec::new();
    let mut surface_messages: Vec<(String, u64)> = Vec::new();
    let mut seen_surface_session: BTreeSet<(String, String)> = BTreeSet::new();
    for event in events {
        log::validate_event(event)?;
        let session = event["session_id"].as_str().unwrap_or("");
        let surface = event["surface"].as_str().unwrap_or("");
        if !sessions.iter().any(|have| have == session) {
            sessions.push(session.to_owned());
        }
        if seen_surface_session.insert((surface.to_owned(), session.to_owned())) {
            add_count(&mut surface_messages, surface);
        }
    }
    report(
        BenchSource::Log,
        sessions.len() as u64,
        &surface_messages,
        events,
    )
}

fn report(
    source: BenchSource,
    messages: u64,
    surface_messages: &[(String, u64)],
    events: &[Value],
) -> Result<Value, String> {
    let mut overall = Bucket::new(messages);
    let mut tiers: Vec<(String, Bucket)> = Vec::new();
    let mut surfaces: Vec<(String, Bucket)> = surface_messages
        .iter()
        .map(|(surface, count)| (surface.clone(), Bucket::new(*count)))
        .collect();
    let mut shown = BTreeSet::new();
    for event in events {
        log::validate_event(event)?;
        let id = event["suggestion_id"].as_str().unwrap_or("").to_owned();
        let outcome = event["outcome"].as_str().unwrap_or("");
        let surface = event["surface"].as_str().unwrap_or("");
        let tier = event["tier"].as_str().unwrap_or("");
        let chars = event["chars_accepted"].as_u64().unwrap_or(0);
        let latency = event["latency_ms"].as_f64().unwrap_or(0.0);
        if outcome == "shown" {
            if !shown.insert(id.clone()) {
                return Err("the ghost event is not valid".to_owned());
            }
            overall.note_shown(latency);
            bucket_named(&mut surfaces, surface, 0).note_shown(latency);
            bucket_named(&mut tiers, tier, messages).note_shown(latency);
        } else if !shown.contains(&id) {
            return Err("the ghost event is not valid".to_owned());
        } else if matches!(outcome, "accepted_all" | "accepted_word") {
            overall.note_accept(&id, chars);
            bucket_named(&mut surfaces, surface, 0).note_accept(&id, chars);
            bucket_named(&mut tiers, tier, messages).note_accept(&id, chars);
        }
    }
    if tiers.is_empty() {
        tiers.push(("recall".to_owned(), Bucket::new(messages)));
    }
    Ok(json!({
        "schema": SCHEMA,
        "kind": "bench_report",
        "source": source,
        "messages": messages,
        "overall": overall.metrics(),
        "per_tier": tiers.iter().map(|(tier, bucket)| json!({"tier": tier, "metrics": bucket.metrics()})).collect::<Vec<_>>(),
        "per_surface": surfaces.iter().map(|(surface, bucket)| json!({"surface": surface, "metrics": bucket.metrics()})).collect::<Vec<_>>(),
    }))
}

struct Bucket {
    messages: u64,
    shown: u64,
    accepted: BTreeSet<String>,
    chars: u64,
    latencies: Vec<f64>,
}

impl Bucket {
    fn new(messages: u64) -> Self {
        Self {
            messages,
            shown: 0,
            accepted: BTreeSet::new(),
            chars: 0,
            latencies: Vec::new(),
        }
    }

    fn note_shown(&mut self, latency: f64) {
        self.shown += 1;
        self.latencies.push(latency);
    }

    fn note_accept(&mut self, id: &str, chars: u64) {
        self.accepted.insert(id.to_owned());
        self.chars += chars;
    }

    fn metrics(&self) -> Value {
        let (p50, p90) = if self.shown == 0 {
            (Value::Null, Value::Null)
        } else {
            (
                json!(percentile(&self.latencies, 0.5)),
                json!(percentile(&self.latencies, 0.9)),
            )
        };
        json!({
            "shown": self.shown,
            "accepted": self.accepted.len() as u64,
            "acceptance_rate": ratio(self.accepted.len() as u64, self.shown),
            "chars_saved_per_message": if self.messages == 0 { 0.0 } else { round4(self.chars as f64 / self.messages as f64) },
            "suggestions_per_message": if self.messages == 0 { 0.0 } else { round4(self.shown as f64 / self.messages as f64) },
            "p50_latency_ms": p50,
            "p90_latency_ms": p90,
        })
    }
}

fn bucket_named<'a>(
    groups: &'a mut Vec<(String, Bucket)>,
    name: &str,
    messages: u64,
) -> &'a mut Bucket {
    if !groups.iter().any(|(have, _)| have == name) {
        groups.push((name.to_owned(), Bucket::new(messages)));
    }
    &mut groups
        .iter_mut()
        .find(|(have, _)| have == name)
        .expect("group")
        .1
}

fn add_count(groups: &mut Vec<(String, u64)>, name: &str) {
    if let Some((_, count)) = groups.iter_mut().find(|(have, _)| have == name) {
        *count += 1;
    } else {
        groups.push((name.to_owned(), 1));
    }
}

fn ratio(part: u64, whole: u64) -> f64 {
    if whole == 0 {
        0.0
    } else {
        round4(part as f64 / whole as f64)
    }
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

fn percentile(samples: &[f64], p: f64) -> f64 {
    let mut sorted = samples.to_vec();
    sorted.sort_by(f64::total_cmp);
    let rank = (p * sorted.len() as f64).ceil() as usize;
    sorted[rank.saturating_sub(1).min(sorted.len() - 1)]
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text =
        fs::read_to_string(path).map_err(|_| "the context pack could not be read".to_owned())?;
    serde_json::from_str(&text).map_err(|_| "the context pack is not valid".to_owned())
}

fn failure(
    args: &[OsString],
    code: i32,
    kind: &str,
    message: &str,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    if args.iter().any(|arg| arg == "--json") {
        let report = json!({
            "schema": "openwiz.cli-error.v1",
            "command": "ghost",
            "exit_code": code,
            "error": { "kind": kind, "message": message }
        });
        let _ = writeln!(out, "{report}");
    } else {
        let _ = writeln!(err, "openwiz: {message}");
    }
    code
}
