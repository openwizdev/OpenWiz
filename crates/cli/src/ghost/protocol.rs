use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const SCHEMA_ID: &str = "openwiz.ghost.v1";
pub const DEFAULT_PORT: u16 = 17417;
pub const MAX_BODY_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Surface {
    #[serde(rename = "openwiz-app")]
    OpenwizApp,
    #[serde(rename = "t3-code")]
    T3Code,
    #[serde(rename = "bb-plugin")]
    BbPlugin,
    #[serde(rename = "cli")]
    Cli,
    #[serde(rename = "other")]
    Other,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Tier {
    Recall,
    SmallModel,
    Draft,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Shown,
    AcceptedAll,
    AcceptedWord,
    TypedThrough,
    Dismissed,
    TypedOver,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BenchSource {
    Fixtures,
    Log,
    Sent,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TurnRole {
    User,
    Agent,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RefusalCode {
    InvalidRequest,
    MissingToken,
    InvalidToken,
    InvalidPairingCode,
    HostNotAllowed,
    OriginNotAllowed,
    UnknownRoute,
    MethodNotAllowed,
    PayloadTooLarge,
    NotImplemented,
    Unavailable,
}

impl RefusalCode {
    pub fn status_code(self) -> u16 {
        match self {
            Self::InvalidRequest => 400,
            Self::MissingToken | Self::InvalidToken | Self::InvalidPairingCode => 401,
            Self::HostNotAllowed | Self::OriginNotAllowed => 403,
            Self::UnknownRoute => 404,
            Self::MethodNotAllowed => 405,
            Self::PayloadTooLarge => 413,
            Self::NotImplemented => 501,
            Self::Unavailable => 503,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RefusalBody {
    pub code: RefusalCode,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RefusalEnvelope {
    pub refusal: RefusalBody,
}

impl RefusalEnvelope {
    pub fn new(code: RefusalCode, message: impl Into<String>) -> Self {
        Self {
            refusal: RefusalBody {
                code,
                message: message.into(),
            },
        }
    }

    pub fn into_response(self) -> (u16, Value) {
        let status = self.refusal.code.status_code();
        let body = serde_json::to_value(self).expect("refusal serializes");
        (status, body)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Turn {
    pub role: TurnRole,
    pub text: String,
    pub asks_user: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SkillContext {
    pub phrases: Vec<String>,
    pub tone: String,
    pub never_suggest: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GlossaryEntry {
    pub term: String,
    pub meaning: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SpecEntry {
    pub number: u64,
    pub title: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TicketEntry {
    pub number: u64,
    pub title: String,
    pub action: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GrillEntry {
    pub code: String,
    pub question: String,
    pub recommended: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OpenWork {
    pub specs: Vec<SpecEntry>,
    pub tickets: Vec<TicketEntry>,
    pub grills: Vec<GrillEntry>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConversationContext {
    pub session_id: String,
    pub agent: String,
    pub turns: Vec<Turn>,
}

impl Default for ConversationContext {
    fn default() -> Self {
        Self {
            session_id: "default".to_owned(),
            agent: "orchestrator".to_owned(),
            turns: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContextPack {
    pub schema: String,
    pub kind: String,
    pub revision: String,
    pub skill: SkillContext,
    pub glossary: Vec<GlossaryEntry>,
    pub open_work: OpenWork,
    pub conversation: ConversationContext,
}

impl ContextPack {
    pub fn empty(revision: impl Into<String>) -> Self {
        Self {
            schema: SCHEMA_ID.to_owned(),
            kind: "context_pack".to_owned(),
            revision: revision.into(),
            skill: SkillContext::default(),
            glossary: Vec::new(),
            open_work: OpenWork::default(),
            conversation: ConversationContext::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairRequest {
    pub code: String,
    pub surface: Surface,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairResponse {
    pub schema: String,
    pub token: String,
    pub surface: Surface,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HealthRequest {}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TiersStatus {
    pub recall: bool,
    pub small_model: bool,
    pub draft: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HealthResponse {
    pub schema: String,
    pub status: String,
    pub version: String,
    pub tiers: TiersStatus,
    pub logging_enabled: bool,
    pub context_revision: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContextRequest {
    #[serde(default)]
    pub if_revision: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContextResponse {
    pub schema: String,
    pub revision: String,
    pub unchanged: bool,
    pub pack: Option<ContextPack>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TurnsRequest {
    pub session_id: String,
    pub agent: String,
    pub turns: Vec<Turn>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TurnsResponse {
    pub schema: String,
    pub revision: String,
    pub draft_queued: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Suggestion {
    pub id: String,
    pub text: String,
    pub full_text: String,
    pub tier: Tier,
    pub confidence: f64,
    pub latency_ms: f64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompleteRequest {
    pub session_id: String,
    pub surface: Surface,
    pub prefix: String,
    pub seq: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompleteResponse {
    pub schema: String,
    pub seq: u64,
    pub suggestion: Option<Suggestion>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DraftRequest {
    pub session_id: String,
    pub surface: Surface,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Draft {
    pub id: String,
    pub text: String,
    pub precomputed: bool,
    pub latency_ms: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DraftResponse {
    pub schema: String,
    pub draft: Option<Draft>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub schema: String,
    pub kind: String,
    pub at: String,
    pub suggestion_id: String,
    pub session_id: String,
    pub surface: Surface,
    pub outcome: Outcome,
    pub tier: Tier,
    pub confidence: f64,
    pub latency_ms: f64,
    pub chars_accepted: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FeedbackResponse {
    pub schema: String,
    pub recorded: bool,
    pub logged: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BenchRequest {
    pub source: BenchSource,
    pub surface: Surface,
    #[serde(default)]
    pub replay_path: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StdioResponse {
    pub id: Option<String>,
    pub status: u16,
    pub body: Value,
}

pub fn validate_host(host: &str) -> bool {
    let trimmed = host.trim();
    if trimmed == "127.0.0.1" || trimmed == "localhost" {
        return true;
    }
    if let Some(port) = trimmed
        .strip_prefix("127.0.0.1:")
        .or_else(|| trimmed.strip_prefix("localhost:"))
    {
        return valid_port(port);
    }
    false
}

pub fn validate_origin(origin: &str) -> bool {
    if origin == "https://openwiz.dev"
        || origin == "http://localhost"
        || origin == "http://127.0.0.1"
    {
        return true;
    }
    if let Some(port) = origin
        .strip_prefix("http://localhost:")
        .or_else(|| origin.strip_prefix("http://127.0.0.1:"))
    {
        return valid_port(port);
    }
    if let Some(label) = origin
        .strip_prefix("https://")
        .and_then(|rest| rest.strip_suffix(".wizsite.pages.dev"))
    {
        return valid_dns_label(label);
    }
    false
}

fn valid_port(port: &str) -> bool {
    !port.is_empty()
        && !port.starts_with('0')
        && port.bytes().all(|b| b.is_ascii_digit())
        && port.parse::<u16>().is_ok()
}

fn valid_dns_label(label: &str) -> bool {
    let bytes = label.as_bytes();
    if bytes.is_empty() || bytes.len() > 63 {
        return false;
    }
    let is_alnum = |b: u8| b.is_ascii_lowercase() || b.is_ascii_digit();
    if !is_alnum(bytes[0]) || !is_alnum(bytes[bytes.len() - 1]) {
        return false;
    }
    bytes.iter().all(|&b| is_alnum(b) || b == b'-')
}

pub fn is_valid_utc_timestamp(value: &str) -> bool {
    let b = value.as_bytes();
    if b.len() != 20 {
        return false;
    }
    let digits = [0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18];
    digits.iter().all(|&i| b[i].is_ascii_digit())
        && b[4] == b'-'
        && b[7] == b'-'
        && b[10] == b'T'
        && b[13] == b':'
        && b[16] == b':'
        && b[19] == b'Z'
}

pub fn validate_pair_request(req: &PairRequest) -> Result<(), &'static str> {
    if req.code.is_empty() {
        return Err("code must be a non-empty string.");
    }
    Ok(())
}

pub fn validate_context_request(req: &ContextRequest) -> Result<(), &'static str> {
    if let Some(rev) = &req.if_revision
        && rev.is_empty()
    {
        return Err("if_revision must be non-empty when present.");
    }
    Ok(())
}

pub fn validate_turns_request(req: &TurnsRequest) -> Result<(), &'static str> {
    if req.session_id.is_empty() {
        return Err("session_id must be a non-empty string.");
    }
    if req.agent.is_empty() {
        return Err("agent must be a non-empty string.");
    }
    if req.turns.len() > 3 {
        return Err("turns must contain at most 3 entries.");
    }
    Ok(())
}

pub fn validate_complete_request(req: &CompleteRequest) -> Result<(), &'static str> {
    if req.session_id.is_empty() {
        return Err("session_id must be a non-empty string.");
    }
    Ok(())
}

pub fn validate_draft_request(req: &DraftRequest) -> Result<(), &'static str> {
    if req.session_id.is_empty() {
        return Err("session_id must be a non-empty string.");
    }
    Ok(())
}

pub fn validate_event(event: &Event) -> Result<(), &'static str> {
    if event.schema != SCHEMA_ID {
        return Err("event schema must be openwiz.ghost.v1.");
    }
    if event.kind != "event" {
        return Err("event kind must be \"event\".");
    }
    if !is_valid_utc_timestamp(&event.at) {
        return Err("event at must be an RFC 3339 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ).");
    }
    if event.suggestion_id.is_empty() || event.session_id.is_empty() {
        return Err("suggestion_id and session_id must be non-empty strings.");
    }
    if !event.confidence.is_finite() || !(0.0..=1.0).contains(&event.confidence) {
        return Err("confidence must be in [0, 1].");
    }
    if !event.latency_ms.is_finite() || event.latency_ms < 0.0 {
        return Err("latency_ms must be >= 0.");
    }
    Ok(())
}

pub fn validate_bench_request(req: &BenchRequest, is_http: bool) -> Result<(), &'static str> {
    if let Some(path) = &req.replay_path {
        if is_http {
            return Err("replay_path is not allowed over HTTP.");
        }
        if path.is_empty() {
            return Err("replay_path must be non-empty when present.");
        }
    }
    if is_http && req.source == BenchSource::Sent {
        return Err("bench over HTTP accepts only source \"fixtures\" or \"log\".");
    }
    Ok(())
}
