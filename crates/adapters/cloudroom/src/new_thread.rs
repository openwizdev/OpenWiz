//! The CloudRoom side of new threads (OpenWiz 0.0.4, ClosedWiz#11): the
//! [`NewThreadClient`] the core calls (A1 phase 2), over the allowlist's
//! `cloud status --json` and `thread spawn` (sheet A-2) and the existing
//! reads, and the pure functions it is made of (A1 phase 1):
//!
//! - [`spawn_argv`]: the exact `thread spawn` arguments, every setting
//!   explicit, built only by the allowlist's [`Invocation::ThreadSpawn`];
//! - [`parse_projects`] and [`is_github_remote`]: the projects a create may
//!   start in (sheet A-5);
//! - [`parse_observed_threads`]: threads seen after an uncertain create,
//!   observations only;
//! - [`parse_catalogue`]: `cloud status --json`, keeping only the catalogue
//!   keys ([`CATALOGUE_KEYS`], sheet A-2) and discarding the account and
//!   everything else before anything reads it;
//! - [`spawn_receipt`] and [`spawn_error`]: the reply to the one call;
//! - [`parse_shown_thread`]: a created thread's `thread show`, for its start;
//! - [`HARNESS_PROVIDERS`] and [`CLI_REASONING_LEVELS`]: what is verified.
//!
//! **Evidence.** The `spawn` options, `cloud status`'s keys and types and
//! the CLI's effort levels were observed in spike run 3 (`room-cli` v131,
//! help and one structure-only read, 2026-10-30). The receipt, the error
//! lines and the `pending`/`starting` statuses are **source-read, not
//! observed** (ClosedWiz#11): only a live create shows them.
//!
//! Nothing `room-cli` prints reaches a reason, gap or message from here,
//! except `lastError` on a failed start, shown as CloudRoom's words.
//!
//! [`NewThreadClient`]: openwiz_core::new_thread::operation::NewThreadClient
//! [`Invocation::ThreadSpawn`]: crate::allowlist::Invocation::ThreadSpawn

use std::time::Instant;

use openwiz_core::messaging::InvalidRequest;
use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::model::{Fact, Timestamp};
use openwiz_core::new_thread::effects::ProjectCandidate;
use openwiz_core::new_thread::operation::{NewThreadClient, ObservedThread, SpawnRequest};
use openwiz_core::new_thread::options::{
    AttachmentSupport, Catalogue, CatalogueHarness, CatalogueModel,
};
use openwiz_core::new_thread::outcome::{Gap, ProviderRefusal, SpawnReply};
use openwiz_core::new_thread::start::ShownThread;
use openwiz_core::source::{SessionSource, SourceError};
use serde::de::{self, Deserialize, Deserializer, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde_json::error::Category;
use serde_json::{Map, Value};
use std::fmt;

use crate::allowlist::{InvalidSpawn, Invocation, SpawnArgs, ThreadId};
use crate::process::{self, SpawnFailure};
use crate::source::CloudRoomSource;

/// Catalogue harness ids whose `spawn --provider` id is verified, and that
/// id. Only `codex` and `claude-code` list models (spike run 3), and both
/// were seen as `providerId`s in capture V. Every other harness is
/// unavailable until its mapping is verified.
pub const HARNESS_PROVIDERS: &[(&str, &str)] =
    &[("codex", "codex"), ("claude-code", "claude-code")];

/// The effort levels `thread spawn --help` lists (spike run 3, v131). The
/// catalogue's `none`, `minimal` and `ultra` are not among them, so they are
/// never offered.
pub const CLI_REASONING_LEVELS: &[&str] = &["low", "medium", "high", "xhigh", "max"];

/// The only `cloud status` keys OpenWiz keeps (sheet A-2). Everything else,
/// the account first, is discarded before anything reads the document.
pub const CATALOGUE_KEYS: &[&str] = &["ready", "harnesses"];

/// The only keys kept on a harness row.
pub const HARNESS_KEYS: &[&str] = &[
    "id",
    "model",
    "reasoning_levels",
    "models",
    "attachments",
    "steer",
];

/// The only keys kept on a model entry.
pub const MODEL_KEYS: &[&str] = &["model", "reasoning_levels"];

/// The only keys kept on a harness's `attachments`.
pub const ATTACHMENT_KEYS: &[&str] = &["files", "images"];

/// The exact arguments of the one create, after the program name:
///
/// `thread spawn --project <id> --machine cloud --provider <p> --model <m>
/// --reasoning-level <l> --request-id <rid> --json --prompt <text>`
///
/// Every setting is explicit (spawn's own defaults are never relied on), the
/// text is one argument, byte for byte, and comes last. No other flag is
/// ever passed: no attachment, title, branch, permission or parent (N1
/// checks every flag `spawn --help` lists). A payload with any attachment
/// is refused. The words are the allowlist's ([`spawn_invocation`]).
///
/// `--prompt` takes the next argument as its value even when it starts with
/// `-` (Commander.js's greedy option-arguments): **inferred from the parser
/// observed in spike run 3, not observed for `spawn`**. Were it not so, the
/// parser refuses the arguments before any request, as it does for an
/// unknown option on `thread show` (observed).
pub fn spawn_argv(spawn: &SpawnRequest) -> Result<Vec<String>, InvalidRequest> {
    spawn_invocation(spawn).map(|invocation| invocation.argv())
}

/// The allowlisted invocation of the one create: every argument checked by
/// [`SpawnArgs::new`] (the text by `send`'s rules), and the staged
/// attachments in the core's dispatch order (B2).
pub fn spawn_invocation(spawn: &SpawnRequest) -> Result<Invocation, InvalidRequest> {
    SpawnArgs::new(
        &spawn.project_id,
        &spawn.provider,
        &spawn.model,
        &spawn.effort,
        &spawn.request_id,
        &spawn.prompt.text,
    )
    .map(|args| Invocation::ThreadSpawn(args.with_attachments(spawn.prompt.dispatch_order())))
    .map_err(|InvalidSpawn(why)| InvalidRequest(why))
}

/// The `spawn` provider id of a catalogue harness, if verified.
pub fn provider_for(harness: &str) -> Option<&'static str> {
    HARNESS_PROVIDERS
        .iter()
        .find(|(h, _)| *h == harness)
        .map(|(_, p)| *p)
}

fn drift(what: &str) -> SourceError {
    SourceError::Malformed {
        detail: format!("cloud status: {what}"),
    }
}

// The strict readers (Sol, round 1, R2), on B1's pattern: each JSON object
// is read by its own visitor straight from the text, so a key given twice is
// seen (`serde_json::Value` would keep only the last), each kept key must
// have its type, and nothing `room-cli` printed reaches an error message.

/// Refuses a key already seen at this level of an object.
fn first<E: de::Error>(seen: &mut Vec<String>, key: &str) -> Result<(), E> {
    if seen.iter().any(|k| k == key) {
        return Err(E::custom("a key given twice"));
    }
    seen.push(key.to_owned());
    Ok(())
}

fn required<T, E: de::Error>(slot: Option<T>, key: &'static str) -> Result<T, E> {
    slot.ok_or_else(|| E::missing_field(key))
}

/// `cloud status --json`'s top level: `ready` and `harnesses`, typed. Every
/// other key, the account first, is dropped unread (sheet A-2).
struct CatalogueDocument(Catalogue);

impl<'de> Deserialize<'de> for CatalogueDocument {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(CatalogueVisitor)
    }
}

struct CatalogueVisitor;

impl<'de> Visitor<'de> for CatalogueVisitor {
    type Value = CatalogueDocument;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("the cloud status object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<CatalogueDocument, A::Error> {
        let mut seen = Vec::new();
        let (mut ready, mut harnesses) = (None, None);
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            match key.as_str() {
                "ready" => ready = Some(map.next_value::<bool>()?),
                "harnesses" => {
                    harnesses = Some(map.next_value::<Option<Vec<HarnessRow>>>()?);
                }
                // Not a catalogue key: dropped unread.
                _ => {
                    map.next_value::<IgnoredAny>()?;
                }
            }
        }
        Ok(CatalogueDocument(Catalogue {
            ready: required(ready, "ready")?,
            harnesses: required(harnesses, "harnesses")?
                .map(|rows| rows.into_iter().map(|row| row.0).collect()),
        }))
    }
}

/// One harness row: [`HARNESS_KEYS`] only, typed; `id`, `model` and
/// `reasoning_levels` required, as every row had them (spike run 3). Every
/// other key is dropped unread.
struct HarnessRow(CatalogueHarness);

impl<'de> Deserialize<'de> for HarnessRow {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(HarnessVisitor)
    }
}

struct HarnessVisitor;

impl<'de> Visitor<'de> for HarnessVisitor {
    type Value = HarnessRow;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a harness object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<HarnessRow, A::Error> {
        let mut seen = Vec::new();
        let (mut id, mut model, mut levels) = (None, None, None);
        let (mut models, mut attachments, mut steer) = (None, None, None);
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            match key.as_str() {
                "id" => id = Some(map.next_value::<String>()?),
                "model" => model = Some(map.next_value::<String>()?),
                "reasoning_levels" => levels = Some(map.next_value::<Vec<String>>()?),
                "models" => models = map.next_value::<Option<Vec<ModelEntry>>>()?,
                "attachments" => attachments = map.next_value::<Option<Attachments>>()?,
                "steer" => steer = map.next_value::<Option<bool>>()?,
                _ => {
                    map.next_value::<IgnoredAny>()?;
                }
            }
        }
        let id: String = required(id, "id")?;
        // The harness's own default and levels: checked, never used.
        let _: (String, Vec<String>) = (
            required(model, "model")?,
            required(levels, "reasoning_levels")?,
        );
        Ok(HarnessRow(CatalogueHarness {
            provider: provider_for(&id).map(str::to_owned),
            id,
            models: models
                .map(|entries: Vec<ModelEntry>| entries.into_iter().map(|e| e.0).collect()),
            attachments: attachments.map(|a: Attachments| a.0),
            steer,
        }))
    }
}

/// One model entry: [`MODEL_KEYS`], both required and typed; every other
/// key is dropped unread.
struct ModelEntry(CatalogueModel);

impl<'de> Deserialize<'de> for ModelEntry {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(ModelVisitor)
    }
}

struct ModelVisitor;

impl<'de> Visitor<'de> for ModelVisitor {
    type Value = ModelEntry;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a model object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<ModelEntry, A::Error> {
        let mut seen = Vec::new();
        let (mut model, mut levels) = (None, None);
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            match key.as_str() {
                "model" => model = Some(map.next_value::<String>()?),
                "reasoning_levels" => levels = Some(map.next_value::<Vec<String>>()?),
                _ => {
                    map.next_value::<IgnoredAny>()?;
                }
            }
        }
        Ok(ModelEntry(CatalogueModel {
            model: required(model, "model")?,
            reasoning_levels: required(levels, "reasoning_levels")?,
        }))
    }
}

/// A harness's `attachments`: [`ATTACHMENT_KEYS`], both required booleans;
/// every other key is dropped unread.
struct Attachments(AttachmentSupport);

impl<'de> Deserialize<'de> for Attachments {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(AttachmentsVisitor)
    }
}

struct AttachmentsVisitor;

impl<'de> Visitor<'de> for AttachmentsVisitor {
    type Value = Attachments;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("an attachments object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Attachments, A::Error> {
        let mut seen = Vec::new();
        let (mut files, mut images) = (None, None);
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            match key.as_str() {
                "files" => files = Some(map.next_value::<bool>()?),
                "images" => images = Some(map.next_value::<bool>()?),
                _ => {
                    map.next_value::<IgnoredAny>()?;
                }
            }
        }
        Ok(Attachments(AttachmentSupport {
            files: required(files, "files")?,
            images: required(images, "images")?,
        }))
    }
}

/// The catalogue in `cloud status --json`'s stdout, read strictly: only
/// [`CATALOGUE_KEYS`] (and on each row [`HARNESS_KEYS`], [`MODEL_KEYS`] and
/// [`ATTACHMENT_KEYS`]) are read, each with its type; the account and every
/// other field are dropped unread (sheet A-2). A key given twice at any level
/// read, a kept key missing or of another type, or anything but an object is
/// drift, and gives [`SourceError::Malformed`]: no options, and nothing is
/// dispatched (N17).
pub fn parse_catalogue(stdout: &[u8]) -> Result<Catalogue, SourceError> {
    serde_json::from_slice::<CatalogueDocument>(stdout)
        .map(|document| document.0)
        .map_err(|_| {
            drift(
                "not the catalogue's shape: a key given twice, or a catalogue key missing or of \
                 another type (withheld)",
            )
        })
}

/// The start of `room-cli`'s error line for a refused create
/// (source-read, ClosedWiz#11; not observed).
pub const SPAWN_ERROR_PREFIX: &str = "Error: Failed to create thread: HTTP ";

/// The documented refusals: status, the start of the message, and what it
/// means. Only a line that starts with [`SPAWN_ERROR_PREFIX`], this status,
/// `: ` and this message start is a refusal. **Source-read, not observed.**
pub const DOCUMENTED_REFUSALS: &[(u16, &str, ProviderRefusal)] = &[
    (400, "Cloud supports new ", ProviderRefusal::Unsupported),
    (
        400,
        "This model is unavailable on Cloud",
        ProviderRefusal::ModelUnavailable,
    ),
    (
        400,
        "This reasoning level is unavailable",
        ProviderRefusal::EffortUnavailable,
    ),
    (400, "Message is too long", ProviderRefusal::MessageTooLong),
    (400, "Message is empty", ProviderRefusal::MessageEmpty),
    (404, "Project not found", ProviderRefusal::ProjectNotFound),
    (
        409,
        "Request ID was already used with different content",
        ProviderRefusal::RequestIdConflict,
    ),
    (
        503,
        "Cloud model discovery is unavailable",
        ProviderRefusal::DiscoveryUnavailable,
    ),
];

fn gap(detail: String) -> Gap {
    Gap {
        subject: "thread spawn".to_owned(),
        detail,
    }
}

fn unclear(reason: UncertainReason, detail: &str) -> SpawnReply {
    SpawnReply::Unclear {
        reason,
        gaps: vec![gap(detail.to_owned())],
    }
}

/// The reply to a call that exited non-zero, from its exit code and its
/// first non-empty stderr line. A documented refusal is refused; anything
/// else is uncertain, the safe direction. Nothing of the line is passed on.
pub fn spawn_error(exit_code: Option<i32>, stderr: &str) -> SpawnReply {
    let Some(code) = exit_code else {
        return unclear(
            UncertainReason::EndedWithoutExitCode,
            "thread spawn ended without an exit code",
        );
    };
    let line = stderr
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .unwrap_or_default();
    let refusal = (code == 1)
        .then(|| line.strip_prefix(SPAWN_ERROR_PREFIX))
        .flatten()
        .and_then(|rest| {
            DOCUMENTED_REFUSALS.iter().find(|(status, message, _)| {
                rest.strip_prefix(&status.to_string())
                    .and_then(|r| r.strip_prefix(": "))
                    .is_some_and(|r| r.starts_with(message))
            })
        });
    match refusal {
        Some((_, _, refusal)) => SpawnReply::Refused(*refusal),
        None => SpawnReply::Unclear {
            reason: UncertainReason::UndocumentedError,
            gaps: vec![gap(format!(
                "thread spawn exited {code} with an error that is not a documented refusal \
                 (its output is withheld)"
            ))],
        },
    }
}

/// What the receipt says: the new thread and its project.
struct Receipt {
    id: String,
    project_id: String,
}

impl<'de> Deserialize<'de> for Receipt {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(ReceiptVisitor)
    }
}

struct ReceiptVisitor;

impl<'de> Visitor<'de> for ReceiptVisitor {
    type Value = Receipt;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("the new thread's row")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Receipt, A::Error> {
        let mut seen = Vec::new();
        let (mut id, mut project_id) = (None, None);
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            match key.as_str() {
                "id" => id = Some(map.next_value::<String>()?),
                "projectId" => project_id = Some(map.next_value::<String>()?),
                // #949: any other key, of any type, is read only for a key
                // given twice at any depth; an additive room-cli release
                // (v155's declared row) is not drift.
                _ => {
                    map.next_value::<KeysOnce>()?;
                }
            }
        }
        Ok(Receipt {
            id: required(id, "id")?,
            project_id: required(project_id, "projectId")?,
        })
    }
}

/// Any JSON value with no key given twice in any object, at any depth. Its
/// content is not kept.
struct KeysOnce;

impl<'de> Deserialize<'de> for KeysOnce {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(KeysOnceVisitor)
    }
}

struct KeysOnceVisitor;

impl<'de> Visitor<'de> for KeysOnceVisitor {
    type Value = KeysOnce;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("JSON with no key given twice")
    }

    fn visit_bool<E: de::Error>(self, _: bool) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_i64<E: de::Error>(self, _: i64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_u64<E: de::Error>(self, _: u64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_f64<E: de::Error>(self, _: f64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_str<E: de::Error>(self, _: &str) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_unit<E: de::Error>(self) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<KeysOnce, A::Error> {
        while seq.next_element::<KeysOnce>()?.is_some() {}
        Ok(KeysOnce)
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<KeysOnce, A::Error> {
        let mut seen = Vec::new();
        while let Some(key) = map.next_key::<String>()? {
            first(&mut seen, &key)?;
            map.next_value::<KeysOnce>()?;
        }
        Ok(KeysOnce)
    }
}

/// Refuses a document that gives any key twice, at any depth: a read of it
/// through `serde_json::Value` would silently keep only the last.
fn keys_once(stdout: &[u8], read: &str) -> Result<(), SourceError> {
    serde_json::from_slice::<KeysOnce>(stdout)
        .map(|_| ())
        .map_err(|_| SourceError::Malformed {
            detail: format!("{read}: not JSON, or a key given twice"),
        })
}

/// The reply to a call that exited 0: its stdout must be the new thread's
/// row, an object read strictly for the keys OpenWiz uses: `id` and
/// `projectId`, each a string, each once, with `id` a safe id and
/// `projectId` this create's project. Any other key, of any type, is
/// accepted unread (#949), but no key may be given twice at any depth.
/// Anything else is uncertain (N17): the thread may exist, and the prompt is
/// kept. Nothing of the receipt is passed on but the thread id.
///
/// The receipt's shape is **source-read, not observed** ("`--json` prints
/// the new thread row", written with `status: "pending"`; room-cli v155's
/// declared `ThreadResponse`, #949).
pub fn spawn_receipt(stdout: &[u8], project_id: &str) -> SpawnReply {
    let unexpected = |detail: &str| {
        unclear(
            UncertainReason::UnexpectedReceipt,
            &format!("receipt drift: {detail}"),
        )
    };
    let receipt = match serde_json::from_slice::<Receipt>(stdout) {
        Ok(receipt) => receipt,
        Err(e) if e.classify() == Category::Data => {
            return unexpected(
                "the receipt is not a thread row: not an object, a key given twice, or no id or \
                 projectId string (withheld)",
            );
        }
        Err(_) => {
            return unclear(
                UncertainReason::NotJson,
                "thread spawn exited 0 with a reply that is not JSON (withheld)",
            );
        }
    };
    if ThreadId::parse(&receipt.id).is_err() {
        return unexpected(
            "the receipt has no thread id of 1 to 128 ASCII letters, digits, _ or -",
        );
    }
    if receipt.project_id != project_id {
        return unexpected("the receipt names another project");
    }
    SpawnReply::Created {
        thread_id: receipt.id,
    }
}

/// A created thread from its `thread show --json`, for its start stage and
/// reported configuration. A missing or mistyped field is unknown, with a
/// gap naming it, never its value. Fails only when the document is not the
/// thread asked for.
pub fn parse_shown_thread(stdout: &[u8], thread_id: &str) -> Result<ShownThread, SourceError> {
    keys_once(stdout, "thread show")?;
    let malformed = |detail: &str| SourceError::Malformed {
        detail: detail.to_owned(),
    };
    let doc: Value = serde_json::from_slice(stdout).map_err(|_| malformed("not JSON"))?;
    let Some(thread) = doc.get("thread").filter(|t| t.is_object()) else {
        return Err(malformed("no thread object"));
    };
    if thread.get("id").and_then(Value::as_str) != Some(thread_id) {
        return Err(malformed("it describes another thread"));
    }
    let mut problems = Vec::new();
    let mut field = |value: Option<&Value>, name: &str| match value {
        Some(Value::String(s)) => Fact::Known(s.clone()),
        Some(_) => Fact::Unknown(drifted(&mut problems, name, "has an unexpected type")),
        None => Fact::Unknown(drifted(&mut problems, name, "is missing")),
    };
    let status = field(thread.get("status"), "status");
    let provider = field(thread.get("providerId"), "providerId");
    let model = field(doc.pointer("/execution/model"), "execution.model");
    let effort = field(
        doc.pointer("/execution/reasoningLevel"),
        "execution.reasoningLevel",
    );
    let last_error = match thread.get("lastError") {
        None | Some(Value::Null) => Fact::Known(None),
        Some(Value::String(s)) => Fact::Known(Some(s.clone())),
        Some(_) => Fact::Unknown(drifted(
            &mut problems,
            "lastError",
            "has an unexpected type",
        )),
    };
    Ok(ShownThread {
        status,
        last_error,
        provider,
        model,
        effort,
        problems,
    })
}

fn drifted(problems: &mut Vec<Gap>, field: &str, what: &str) -> String {
    let detail = format!("schema drift: thread show {field} {what}");
    problems.push(Gap {
        subject: "thread show".to_owned(),
        detail: detail.clone(),
    });
    detail
}

/// The GitHub remote forms accepted: each prefix, then a path.
const GITHUB_PREFIXES: &[&str] = &[
    "https://github.com/",
    "ssh://git@github.com/",
    "git@github.com:",
];

/// Whether `url`, a project's `gitRemoteUrl`, is a GitHub remote: an
/// `https://github.com/`, `ssh://git@github.com/` or `git@github.com:` URL
/// with a path of printable ASCII after it. Anything else (another host, a
/// lookalike, a user, an empty path) is not, so the project is refused
/// (sheet A-5): the safe direction, since CloudRoom copies a project
/// without a GitHub remote from the Mac instead, a larger and different
/// effect. **Spike run 3 observed only whether `gitRemoteUrl` is null**,
/// never a host; this rule is OpenWiz's.
pub fn is_github_remote(url: &str) -> bool {
    GITHUB_PREFIXES.iter().any(|prefix| {
        url.strip_prefix(prefix).is_some_and(|path| {
            !path.is_empty() && !path.starts_with('/') && path.bytes().all(|b| b.is_ascii_graphic())
        })
    })
}

fn not_a_list(read: &str) -> SourceError {
    SourceError::Malformed {
        detail: format!("{read} is not a JSON list"),
    }
}

fn rows(stdout: &[u8], read: &str) -> Result<Vec<Value>, SourceError> {
    match serde_json::from_slice::<Value>(stdout) {
        Ok(Value::Array(rows)) => Ok(rows),
        _ => Err(not_a_list(read)),
    }
}

/// A string field, or unknown with the reason (the field's name, never its
/// value).
fn string_field(row: &Map<String, Value>, read: &str, field: &str) -> Fact<String> {
    match row.get(field) {
        Some(Value::String(s)) => Fact::Known(s.clone()),
        Some(_) => Fact::Unknown(format!(
            "schema drift: {read} {field} has an unexpected type"
        )),
        None => Fact::Unknown(format!("schema drift: {read} {field} is missing")),
    }
}

/// The projects in `project list --json --include-personal`'s stdout, for a
/// create: id, name, kind, and whether the remote is GitHub. A row with no
/// nonempty string id can't be named, and is left out. A missing or
/// mistyped kind or remote is unknown, so the project is refused. A key
/// given twice anywhere refuses the whole list: nothing is created.
pub fn parse_projects(stdout: &[u8]) -> Result<Vec<ProjectCandidate>, SourceError> {
    let read = "project list";
    // A key given twice (a `kind` or a remote) could change which project
    // may be created in: the whole list is refused instead.
    keys_once(stdout, read)?;
    Ok(rows(stdout, read)?
        .iter()
        .filter_map(Value::as_object)
        .filter_map(|row| {
            let Some(Value::String(id)) = row.get("id") else {
                return None;
            };
            if id.is_empty() {
                return None;
            }
            let github_remote = match row.get("gitRemoteUrl") {
                Some(Value::Null) => Fact::Known(false),
                Some(Value::String(url)) => Fact::Known(is_github_remote(url)),
                Some(_) => Fact::Unknown(format!(
                    "schema drift: {read} gitRemoteUrl has an unexpected type"
                )),
                None => Fact::Unknown(format!("schema drift: {read} gitRemoteUrl is missing")),
            };
            Some(ProjectCandidate {
                id: id.clone(),
                name: string_field(row, read, "name"),
                kind: string_field(row, read, "kind"),
                github_remote,
            })
        })
        .collect())
}

/// The threads in `project_id` created at or after `since`, from `thread
/// list --json`'s stdout: observations only. A thread in the project whose
/// creation time can't be read is listed, with it unknown, since it can't
/// be ruled out.
pub fn parse_observed_threads(
    stdout: &[u8],
    project_id: &str,
    since: Timestamp,
) -> Result<Vec<ObservedThread>, SourceError> {
    let read = "thread list";
    keys_once(stdout, read)?;
    Ok(rows(stdout, read)?
        .iter()
        .filter_map(Value::as_object)
        .filter(|row| row.get("projectId").and_then(Value::as_str) == Some(project_id))
        .filter_map(|row| {
            let id = row
                .get("id")
                .and_then(Value::as_str)
                .filter(|id| ThreadId::parse(id).is_ok())?;
            let created_at = match row.get("createdAt").and_then(Value::as_i64) {
                Some(at) if at < since.0 => return None,
                Some(at) => Fact::Known(Timestamp(at)),
                None => Fact::Unknown(format!(
                    "schema drift: {read} createdAt is missing or not a time"
                )),
            };
            Some(ObservedThread {
                id: id.to_owned(),
                created_at,
            })
        })
        .collect())
}

/// Drops `room-cli`'s own text from a read's error, keeping its category.
fn withheld(error: SourceError) -> SourceError {
    match error {
        SourceError::CommandFailed { exit_code, .. } => SourceError::CommandFailed {
            exit_code,
            detail: "output withheld".to_owned(),
        },
        SourceError::Unavailable { .. } => SourceError::Unavailable {
            detail: "could not be started".to_owned(),
        },
        other => other,
    }
}

impl NewThreadClient for CloudRoomSource {
    fn name(&self) -> &str {
        crate::PROGRAM
    }

    /// New's own, never the reads' (#200): `""` while no live create has
    /// passed, which no version read equals.
    fn tested_version(&self) -> &str {
        crate::NEW_TESTED_VERSION.unwrap_or("")
    }

    fn cli_levels(&self) -> &[&str] {
        CLI_REASONING_LEVELS
    }

    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        // The version read's malformed details are OpenWiz's own words.
        SessionSource::version(self, deadline).map_err(withheld)
    }

    fn projects(&self, deadline: Instant) -> Result<Vec<ProjectCandidate>, SourceError> {
        let list = Invocation::ProjectList { hidden: false };
        let out = process::run(self.program(), &list, deadline).map_err(withheld)?;
        parse_projects(&out)
    }

    fn catalogue(&self, deadline: Instant) -> Result<Catalogue, SourceError> {
        let out =
            process::run(self.program(), &Invocation::CloudStatus, deadline).map_err(withheld)?;
        parse_catalogue(&out)
    }

    fn spawn(&self, spawn: &SpawnRequest, deadline: Instant) -> SpawnReply {
        let Ok(invocation) = spawn_invocation(spawn) else {
            // Never reached: the core passes only checked values. Nothing
            // is run.
            return SpawnReply::NotStarted;
        };
        match process::run_spawn(self.program(), &invocation, deadline) {
            Ok(out) => spawn_receipt(&out, &spawn.project_id),
            Err(SpawnFailure::Exited {
                exit_code,
                first_line,
            }) => spawn_error(exit_code, &first_line),
            Err(SpawnFailure::Source(SourceError::TimedOut { .. })) => unclear(
                UncertainReason::TimedOut,
                "thread spawn did not answer in time; it was stopped and not retried",
            ),
            Err(SpawnFailure::Source(SourceError::Malformed { .. })) => unclear(
                UncertainReason::UnexpectedReceipt,
                "thread spawn printed more than OpenWiz reads",
            ),
            // The runner's own words for a program that never started.
            Err(SpawnFailure::Source(SourceError::Unavailable { detail }))
                if detail.contains("could not be started") =>
            {
                SpawnReply::NotStarted
            }
            Err(SpawnFailure::Source(_)) => unclear(
                UncertainReason::CallNotConfirmed,
                "thread spawn could not be confirmed to have run cleanly",
            ),
        }
    }

    fn show_thread(&self, thread_id: &str, deadline: Instant) -> Result<ShownThread, SourceError> {
        let id = ThreadId::parse(thread_id).map_err(|_| SourceError::InvalidId {
            id: thread_id.to_owned(),
            detail: "not a safe id".to_owned(),
        })?;
        let out = match process::run(self.program(), &Invocation::ThreadShow(id), deadline) {
            Ok(out) => out,
            Err(SourceError::CommandFailed { ref detail, .. })
                if detail.starts_with(process::NOT_FOUND_LINE) =>
            {
                return Err(SourceError::NotFound {
                    subject: thread_id.to_owned(),
                });
            }
            Err(e) => return Err(withheld(e)),
        };
        parse_shown_thread(&out, thread_id)
    }

    fn threads_since(
        &self,
        project_id: &str,
        since: Timestamp,
        deadline: Instant,
    ) -> Result<Vec<ObservedThread>, SourceError> {
        let list = Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        };
        let out = process::run(self.program(), &list, deadline).map_err(withheld)?;
        parse_observed_threads(&out, project_id, since)
    }
}
