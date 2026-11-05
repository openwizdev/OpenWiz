//! Read-only deliveries for one explicitly configured existing repository hook.
//! Wire shapes are documented assumptions, not observed endpoint evidence:
//! https://docs.github.com/en/rest/repos/webhooks . No hook discovery or writes.
use crate::{
    allowlist::{Invocation, Module},
    process::Executor,
    tick,
};
use openwiz_core::source::SourceError;
use serde_json::Value;
use std::{collections::BTreeSet, num::NonZeroU64, time::Instant};

pub const ALLOWLIST: Module = Module {
    name: "events",
    allows,
};
const PREFIX: &str = "repos/{owner}/{repo}/hooks/";
/// GitHub's documented maximum page size; the granted form has no cursor.
pub const PAGE_SIZE: usize = 100;

fn positive(s: &str) -> Option<NonZeroU64> {
    if s.is_empty() || s.starts_with('0') || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse::<u64>().ok().and_then(NonZeroU64::new)
}
fn allows(argv: &[&str]) -> bool {
    let ["api", path] = argv else {
        return false;
    };
    let Some((hook, tail)) = path.strip_prefix(PREFIX).and_then(|p| p.split_once('/')) else {
        return false;
    };
    if positive(hook).is_none() {
        return false;
    }
    if let Some(size) = tail.strip_prefix("deliveries?per_page=") {
        return positive(size).is_some_and(|n| n.get() <= PAGE_SIZE as u64);
    }
    tail.strip_prefix("deliveries/")
        .and_then(positive)
        .is_some()
}

/// Only routing metadata survives the list read; no URLs or headers escape.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Summary {
    pub id: NonZeroU64,
    pub guid: String,
    pub event: String,
}
/// Payload is private transient data. Debug deliberately withholds it.
pub struct Delivery {
    pub summary: Summary,
    pub payload: Vec<u8>,
}

#[derive(Clone)]
pub struct Deliveries {
    hook: NonZeroU64,
    executor: Executor,
}
impl Deliveries {
    pub fn new(hook: NonZeroU64, executor: Executor) -> Self {
        Self { hook, executor }
    }
    pub fn list(&self, deadline: Instant) -> Result<Vec<Summary>, SourceError> {
        let value = self.read(&format!("deliveries?per_page={PAGE_SIZE}"), deadline)?;
        let rows = value.as_array().ok_or_else(malformed)?;
        if rows.len() > PAGE_SIZE {
            return Err(malformed());
        }
        let mut ids = BTreeSet::new();
        rows.iter()
            .map(|row| {
                let summary = summary(row, false)?;
                // Redeliveries can have different numeric IDs but the same GUID.
                if !ids.insert(summary.id) {
                    return Err(malformed());
                }
                Ok(summary)
            })
            .collect()
    }
    pub fn detail(&self, expected: &Summary, deadline: Instant) -> Result<Delivery, SourceError> {
        let value = self.read(&format!("deliveries/{}", expected.id), deadline)?;
        let got = summary(&value, true)?;
        if &got != expected {
            return Err(malformed());
        }
        let request =
            tick::object(&value["request"], &["headers", "payload"]).map_err(|_| malformed())?;
        let response =
            tick::object(&value["response"], &["headers", "payload"]).map_err(|_| malformed())?;
        for headers in [&request["headers"], &response["headers"]] {
            if !headers.is_null()
                && !headers
                    .as_object()
                    .is_some_and(|h| h.values().all(Value::is_string))
            {
                return Err(malformed());
            }
        }
        if !request["payload"].is_object()
            || !(response["payload"].is_null() || response["payload"].is_string())
        {
            return Err(malformed());
        }
        Ok(Delivery {
            summary: got,
            payload: request["payload"].to_string().into_bytes(),
        })
    }
    fn read(&self, suffix: &str, deadline: Instant) -> Result<Value, SourceError> {
        if Instant::now() >= deadline {
            return Err(SourceError::TimedOut { after_ms: 0 });
        }
        let path = format!("{PREFIX}{}/{suffix}", self.hook);
        let call = Invocation::new(&["api", &path]).ok_or_else(malformed)?;
        let bytes = self.executor.run(&call, deadline)?;
        if bytes.len() > crate::process::MAX_STDOUT_BYTES {
            return Err(malformed());
        }
        // Delivery durations and payloads may contain decimals. This reader
        // preserves JSON numbers while refusing duplicate keys at every depth.
        crate::decisions::document(&bytes).ok_or_else(malformed)
    }
}
fn malformed() -> SourceError {
    SourceError::Malformed {
        detail: "webhook delivery response refused (details withheld)".into(),
    }
}
fn summary(value: &Value, detail: bool) -> Result<Summary, SourceError> {
    let mut keys = vec![
        "id",
        "guid",
        "delivered_at",
        "redelivery",
        "duration",
        "status",
        "status_code",
        "event",
        "action",
        "installation_id",
        "repository_id",
    ];
    // The documented throttle field is optional, but never an arbitrary key.
    if value.get("throttled_at").is_some() {
        keys.push("throttled_at");
    }
    if detail {
        keys.extend(["url", "request", "response"]);
    }
    tick::object(value, &keys).map_err(|_| malformed())?;
    let id = value["id"]
        .as_u64()
        .and_then(NonZeroU64::new)
        .ok_or_else(malformed)?;
    let guid = value["guid"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 128
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
        })
        .ok_or_else(malformed)?;
    let event = value["event"]
        .as_str()
        .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_lowercase() || b == b'_'))
        .ok_or_else(malformed)?;
    if !value["delivered_at"].is_string()
        || !value["redelivery"].is_boolean()
        || !value["duration"].as_f64().is_some_and(|d| d >= 0.0)
        || !value["status"].is_string()
        || !value["status_code"].is_u64()
    {
        return Err(malformed());
    }
    for key in ["action", "throttled_at"] {
        if !value[key].is_null() && !value[key].is_string() {
            return Err(malformed());
        }
    }
    for key in ["installation_id", "repository_id"] {
        if !value[key].is_null() && !value[key].as_u64().is_some_and(|id| id > 0) {
            return Err(malformed());
        }
    }
    if detail && !value["url"].is_string() {
        return Err(malformed());
    }
    Ok(Summary {
        id,
        guid: guid.into(),
        event: event.into(),
    })
}
