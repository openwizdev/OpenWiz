//! Read-only decisions endpoint. Source failures remain explicit, never empty work.
use openwiz_adapter_github::decisions::{Comment, GitHubDecisions, document};
use openwiz_core::ops::Clock;
use openwiz_core::{limits::RUN_BUDGET, messaging::sha256_hex, source::SourceError};
use openwiz_core::{messaging::send::Messenger, model::SessionId};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// Configuration is supplied by the server, never by a request comment.
#[derive(Clone, Debug)]
pub struct Decisions {
    pub github: GitHubDecisions,
    pub target: Result<Option<String>, ()>,
}

/// Exact lookup result. Only the owner's saved-proposal verifier makes it current.
#[derive(Debug)]
pub struct DecisionLookup {
    pub state: openwiz_core::notifications::model::TargetState,
    pub snapshot_at: Option<u64>,
}

impl Decisions {
    /// The same strict bounded reader, including closed records, qualified by
    /// the verified source repository. A self-hash verifies integrity only;
    /// without independent saved-proposal verification an open item stays unread.
    pub fn lookup(
        &self,
        binding: &openwiz_core::notifications::model::DecisionRef,
        clock: &dyn Clock,
    ) -> DecisionLookup {
        self.lookup_before(binding, clock, clock.monotonic() + RUN_BUDGET)
    }

    pub(crate) fn lookup_before(
        &self,
        binding: &openwiz_core::notifications::model::DecisionRef,
        clock: &dyn Clock,
        deadline: std::time::Instant,
    ) -> DecisionLookup {
        use openwiz_core::notifications::model::{SubjectKind, TargetState};
        let unread = || DecisionLookup {
            state: TargetState::Unread,
            snapshot_at: None,
        };
        let started = u64::try_from(clock.now().0).ok();
        if clock.monotonic() >= deadline {
            return unread();
        }
        let observed = |state| {
            let now = u64::try_from(clock.now().0).ok();
            match (started, now) {
                (Some(at), Some(now)) if at <= now && clock.monotonic() < deadline => {
                    DecisionLookup {
                        state: if now - at <= 70_000 {
                            state
                        } else {
                            TargetState::Unread
                        },
                        snapshot_at: Some(at),
                    }
                }
                _ => unread(),
            }
        };
        let read = self.github.read(deadline);
        let bound = binding.repository.as_str();
        // The notification contract's repository form is lowercase; compare it
        // only with the repository the source itself verified for each comment.
        let ours = |repository: &str| repository.eq_ignore_ascii_case(bound);
        let mut records: Vec<(&Comment, Value)> = Vec::new();
        let mut malformed = false;
        for comment in read.comments.iter().filter(|c| ours(&c.repository)) {
            match request(&comment.body) {
                Ok(Some(record)) => {
                    // Repeated scans of an identical request are one observation.
                    if records.iter().any(|(previous, saved)| {
                        previous.id == comment.id
                            && previous.subject == comment.subject
                            && previous.created_at == comment.created_at
                            && *saved == record
                    }) {
                        continue;
                    }
                    // A request on the wrong configured role is malformed, never missing.
                    malformed |= !proposal_bound(&record)
                        || self
                            .github
                            .private_role(&comment.repository)
                            .is_some_and(|private| {
                                private != record["kind"].as_str().unwrap().starts_with("grill_")
                            });
                    records.push((comment, record));
                }
                Ok(None) => {}
                Err(()) => malformed = true,
            }
        }
        let exact: Vec<_> = records
            .iter()
            .filter(|(comment, _)| comment.id == binding.comment_id.get())
            .collect();
        let request_count = records
            .iter()
            .filter(|(_, record)| record["id"] == binding.request_id.as_str())
            .count();
        if exact.len() > 1
            || request_count > 1
            || read
                .duplicate_ids
                .iter()
                .any(|(repository, id)| ours(repository) && *id == binding.comment_id.get())
        {
            return DecisionLookup {
                state: TargetState::Ambiguous,
                snapshot_at: None,
            };
        }
        if malformed || !read.snapshot_complete || !read.errors.is_empty() {
            return unread();
        }
        let Some((comment, record)) = exact.first() else {
            // Missing needs positive evidence that the bound repository was read.
            let configured = self.github.private_role(bound).is_some()
                || read.comments.iter().any(|c| ours(&c.repository));
            return if configured {
                observed(TargetState::Missing)
            } else {
                unread()
            };
        };
        if comment.subject != binding.subject.number.get() {
            return observed(TargetState::Changed);
        }
        let Ok(subject) = self
            .github
            .subject_in(&comment.repository, comment.subject, deadline)
        else {
            return unread();
        };
        let wants_pr = matches!(
            record["kind"].as_str(),
            Some("grill_round" | "grill_confirmation")
        );
        if wants_pr != subject.is_pull_request
            || (!wants_pr && record["spec"].as_u64() != Some(subject.number))
        {
            return unread();
        }
        if subject.is_pull_request != (binding.subject.kind == SubjectKind::PullRequest)
            || record["id"] != binding.request_id.as_str()
            || record["fingerprint"] != binding.fingerprint.as_str()
        {
            return observed(TargetState::Changed);
        }
        if record["status"] != "open" {
            return observed(TargetState::Resolved);
        }
        // Reuse the decisions owner's independent saved-grill verifier. Spec
        // and plan requests have no independent verifier and stay unread.
        if !wants_pr {
            return unread();
        }
        let file = record["grill_file"].as_str().expect("validated file");
        let Ok(saved) = self
            .github
            .grill_in(&comment.repository, comment.subject, file, deadline)
        else {
            return unread();
        };
        match saved_grill_proposal(record, &saved) {
            Some(SavedGrill {
                wording_matches,
                risk: Some(risk),
            }) => observed(if wording_matches && record["risk"] == risk {
                TargetState::Current
            } else {
                TargetState::Changed
            }),
            _ => unread(),
        }
    }
}

use crate::{api, http::Reply};

pub(crate) const ROUTE: &str = "/api/v1/decisions";

pub(crate) fn gap(kind: &str, detail: &str) -> Value {
    json!({"kind": kind, "detail": detail})
}

pub(crate) fn unknown(detail: &str) -> Value {
    json!({"unknown": detail})
}

pub(crate) fn coverage(gaps: Vec<Value>) -> Value {
    json!({"state": if gaps.is_empty() { "complete" } else { "partial" }, "gaps": gaps})
}

pub(crate) fn freshness(snapshot: Option<u64>, now: u64) -> Value {
    match snapshot {
        Some(at) if at <= now => {
            json!({"state": if now - at <= 70_000 { "fresh" } else { "stale" }, "snapshot_at": {"known": at}})
        }
        _ => json!({"state": "unknown", "snapshot_at": unknown("source snapshot unavailable")}),
    }
}

pub(crate) fn run(
    source: Option<&Decisions>,
    messenger: Option<&dyn Messenger>,
    clock: &dyn Clock,
) -> Reply {
    let started = u64::try_from(clock.now().0).ok();
    let deadline = clock.monotonic() + RUN_BUDGET;
    let mut gaps = Vec::new();
    let mut items = Vec::new();
    let mut snapshot = None;
    let mut target_gaps = vec![gap("not_found", "target source is not configured")];
    let mut target = unknown("target source is not configured");
    let mut target_snapshot = None;
    if let Some(source) = source {
        match &source.target {
            Ok(None) => {
                target = json!({"known":null});
                target_gaps.clear();
                target_snapshot = started;
            }
            Ok(Some(id))
                if !id.is_empty()
                    && id.len() <= 128
                    && !id.starts_with('-')
                    && id
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b)) =>
            {
                let id = SessionId(id.clone());
                let read = messenger
                    .ok_or_else(|| SourceError::Unavailable {
                        detail: "target reader is not configured".into(),
                    })
                    .and_then(|m| {
                        m.check_target_id(&id).map_err(|_| SourceError::InvalidId {
                            id: id.0.clone(),
                            detail: "invalid configured target".into(),
                        })?;
                        let record = m.read_target(&id, deadline)?;
                        if record.id != id {
                            return Err(SourceError::Malformed {
                                detail: "target identity mismatch".into(),
                            });
                        }
                        Ok(())
                    });
                match read {
                    Ok(()) => {
                        target = json!({"known":id.0});
                        target_gaps.clear();
                        target_snapshot = started;
                    }
                    Err(error) => {
                        target = unknown("configured orchestrator target could not be verified");
                        target_gaps = vec![source_gap(&error)];
                    }
                }
            }
            _ => {
                target = unknown("configured target has not been verified");
                target_gaps = vec![gap(
                    "malformed",
                    "configured orchestrator target is invalid",
                )];
            }
        }
        let mut subjects = BTreeMap::new();
        let mut grills = BTreeMap::new();
        let read = source.github.read_with(deadline, |comment| {
            if let Ok(Some(record)) = request(&comment.body)
                && proposal_bound(&record)
            {
                let subject = subjects
                    .entry((comment.repository.clone(), comment.subject))
                    .or_insert_with(|| {
                        source
                            .github
                            .subject_in(&comment.repository, comment.subject, deadline)
                    });
                if record["status"] == "open"
                    && matches!(
                        record["kind"].as_str(),
                        Some("grill_round" | "grill_confirmation")
                    )
                    && source.github.private_role(&comment.repository) != Some(false)
                    && subject.as_ref().is_ok_and(|s| s.is_pull_request)
                {
                    let file = record["grill_file"].as_str().expect("validated file");
                    grills
                        .entry((comment.repository.clone(), comment.subject, file.to_owned()))
                        .or_insert_with(|| {
                            source.github.grill_in(
                                &comment.repository,
                                comment.subject,
                                file,
                                deadline,
                            )
                        });
                }
            }
        });
        if read.snapshot_complete {
            snapshot = started;
        }
        gaps.extend(read.errors.iter().map(source_gap));
        let mut records: Vec<(Comment, Value)> = Vec::new();
        let mut ids = BTreeMap::<(String, String), usize>::new();
        let mut comments = BTreeMap::<(String, u64), usize>::new();
        let mut observations = BTreeMap::<(String, u64), Vec<usize>>::new();
        for comment in read.comments {
            match request(&comment.body) {
                Ok(Some(request)) => {
                    // Two source scans may observe the same request with edited
                    // surrounding prose. Keep its oldest observation; the adapter
                    // already reports churn. Distinct requests remain ambiguous.
                    if source
                        .github
                        .private_role(&comment.repository)
                        .is_some_and(|private| {
                            private != request["kind"].as_str().unwrap().starts_with("grill_")
                        })
                    {
                        gaps.push(gap(
                            "malformed",
                            "decision request is on the wrong repository role",
                        ));
                        continue;
                    }
                    let seen = observations
                        .entry((comment.repository.clone(), comment.id))
                        .or_default();
                    if seen.iter().any(|&i| {
                        let (previous, saved) = &records[i];
                        previous.subject == comment.subject
                            && previous.created_at == comment.created_at
                            && *saved == request
                    }) {
                        continue;
                    }
                    seen.push(records.len());
                    *comments
                        .entry((comment.repository.clone(), comment.id))
                        .or_default() += 1;
                    *ids.entry((
                        comment.repository.clone(),
                        request["id"].as_str().expect("validated id").to_owned(),
                    ))
                    .or_default() += 1;
                    records.push((comment, request));
                }
                Ok(None) => {}
                Err(()) => gaps.push(gap(
                    "malformed",
                    "a marked decision comment is malformed or unsupported",
                )),
            }
        }
        for (comment, request) in records {
            if ids[&(
                comment.repository.clone(),
                request["id"].as_str().expect("validated id").to_owned(),
            )] != 1
                || comments[&(comment.repository.clone(), comment.id)] != 1
                || read
                    .duplicate_ids
                    .contains(&(comment.repository.clone(), comment.id))
            {
                gaps.push(gap("malformed", "decision identity is ambiguous"));
                continue;
            }
            // Validate the immutable proposal before lifecycle filtering. A
            // malformed close cannot silently erase pending work or its gap.
            if !proposal_bound(&request) {
                gaps.push(gap(
                    "malformed",
                    "decision fingerprint does not bind its proposal",
                ));
                continue;
            }
            let subject = subjects
                .entry((comment.repository.clone(), comment.subject))
                .or_insert_with(|| {
                    source
                        .github
                        .subject_in(&comment.repository, comment.subject, deadline)
                });
            let subject = match subject {
                Ok(subject) => subject,
                Err(error) => {
                    gaps.push(source_gap(error));
                    snapshot = None;
                    continue;
                }
            };
            let kind = if subject.is_pull_request {
                "pull_request"
            } else {
                "issue"
            };
            let wants_pr = matches!(
                request["kind"].as_str(),
                Some("grill_round" | "grill_confirmation")
            );
            if wants_pr != subject.is_pull_request
                || (!wants_pr && request["spec"].as_u64() != Some(subject.number))
            {
                gaps.push(gap("malformed", "decision request is on the wrong subject"));
                continue;
            }
            if request["status"] != "open" {
                continue;
            }
            let mut unavailable = "independent saved proposal verification is unavailable";
            let proposal = if wants_pr {
                let file = request["grill_file"].as_str().expect("validated file");
                match grills
                    .entry((comment.repository.clone(), comment.subject, file.to_owned()))
                    .or_insert_with(|| {
                        source
                            .github
                            .grill_in(&comment.repository, comment.subject, file, deadline)
                    }) {
                    Ok(saved) => saved_grill_proposal(&request, saved),
                    Err(error) => {
                        gaps.push(source_gap(error));
                        None
                    }
                }
            } else {
                None
            };
            let current = if let Some(SavedGrill {
                wording_matches,
                risk: Some(risk),
            }) = proposal
            {
                json!({"known":wording_matches && request["risk"] == risk})
            } else {
                if proposal.is_some() {
                    unavailable = "independent saved risk verification is unavailable";
                }
                gaps.push(gap("unsupported", unavailable));
                snapshot = None;
                unknown(unavailable)
            };
            items.push(json!({"comment_id":comment.id,"subject":{"repository":comment.repository,"kind":kind,"number":subject.number},
                "created_at":comment.created_at,"updated_at":comment.updated_at,"current":current,"request":request}));
        }
    } else {
        gaps.push(gap("not_found", "decision source is not configured"));
    }
    items.sort_by_key(|item| {
        (
            item["created_at"].as_u64().unwrap(),
            item["subject"]["repository"].as_str().unwrap().to_owned(),
            item["subject"]["kind"].as_str().unwrap().to_owned(),
            item["subject"]["number"].as_u64().unwrap(),
            item["comment_id"].as_u64().unwrap(),
        )
    });
    let now = u64::try_from(clock.now().0).unwrap_or(0);
    let body = json!({
        "schema": "openwiz.decisions.v1", "kind": "response", "snapshot_at": now,
        "coverage": coverage(gaps),
        "freshness": freshness(snapshot, now),
        "orchestrator": {
            "coverage": coverage(target_gaps),
            "freshness": freshness(target_snapshot, now), "target": target
        },
        "items": items
    });
    api::pretty(&body).map_or_else(
        || api::error(500, "internal", "the result could not be written"),
        api::ok,
    )
}

struct SavedGrill<'a> {
    wording_matches: bool,
    risk: Option<&'a str>,
}

/// Read the saved human proposal and its independent first-line risk locator.
/// A request block or self-hash never supplies either source fact.
fn saved_grill_proposal<'a>(request: &Value, saved: &'a str) -> Option<SavedGrill<'a>> {
    if !saved.starts_with("# Grill: ")
        || saved.contains('\r')
        || saved.lines().any(|s| {
            let line = s.trim_start();
            line.starts_with("```")
                || line.starts_with("~~~")
                || (line.starts_with("## ") && line != s)
        })
    {
        return None;
    }
    let lines: Vec<_> = saved.split('\n').collect();
    let starts: Vec<_> = lines
        .iter()
        .enumerate()
        .filter_map(|(i, s)| s.starts_with("## ").then_some(i))
        .collect();
    let mut rounds = Vec::new();
    let mut summaries = Vec::new();
    for (i, &start) in starts.iter().enumerate() {
        let section = &lines[start + 1..starts.get(i + 1).copied().unwrap_or(lines.len())];
        let heading = lines[start];
        if let Some(n) = heading.strip_prefix("## Round ") {
            if n.starts_with('0') || !n.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let n = n.parse::<u64>().ok().filter(|n| *n > 0)?;
            if rounds.last().is_some_and(|(previous, _, _)| *previous >= n) {
                return None;
            }
            rounds.push((n, start, section));
        } else if heading.starts_with("## Summary") {
            let title = heading
                .strip_prefix("## Summary, corrected")
                .or_else(|| heading.strip_prefix("## Summary"))?;
            if !title.is_empty()
                && !title
                    .strip_prefix(" (shown to ")
                    .and_then(|s| s.strip_suffix(" for confirmation)"))
                    .is_some_and(|s| !s.is_empty())
            {
                return None;
            }
            summaries.push((start, section));
        }
    }
    let (section, latest) = if request["kind"] == "grill_round" {
        let n = request["round"].as_u64()?;
        let (_, _, section) = rounds.iter().find(|(round, _, _)| *round == n)?;
        (*section, rounds.last()?.0 == n)
    } else {
        let (start, section) = summaries.last()?;
        // Reopened decisions invalidate the summary before its request comment
        // is superseded. Confirmation needs a new summary after the last round.
        (
            *section,
            rounds
                .last()
                .is_none_or(|(_, round_start, _)| round_start < start),
        )
    };
    // Only the immediate physical line under this heading is the locator.
    // No trimming, searching another section, or default to ordinary.
    let first = section.first()?;
    let risk = first
        .strip_prefix("Risk: ")
        .filter(|risk| matches!(*risk, "ordinary" | "live" | "release" | "publish"));
    let wording = if first.starts_with("Risk:") {
        &section[1..]
    } else {
        section
    };
    let wording_matches = if request["kind"] == "grill_round" {
        request["questions"] == saved_questions(wording)?
    } else {
        request["summary"] == saved_summary(wording)?
    } && latest;
    Some(SavedGrill {
        wording_matches,
        risk,
    })
}

fn reply_heading(line: &str) -> bool {
    line.starts_with("**") && line.ends_with(":**")
}

fn saved_questions(lines: &[&str]) -> Option<Value> {
    let mut questions = Vec::new();
    let mut ids = std::collections::BTreeSet::new();
    let mut at = 0;
    while at < lines.len() {
        let line = lines[at];
        if line.is_empty() {
            at += 1;
            continue;
        }
        if reply_heading(line) {
            break;
        }
        let (label, context) = line.strip_prefix("**")?.split_once("** ")?;
        let (id, decides) = label.split_once(" - ")?;
        let id = id.strip_suffix(", re-asked").unwrap_or(id);
        if !question_id(id) || !ids.insert(id) || decides.is_empty() {
            return None;
        }
        let mut context = context.to_owned();
        at += 1;
        while at < lines.len() && !lines[at].starts_with("➡️ ") {
            if lines[at].starts_with("**") {
                return None;
            }
            context.push('\n');
            context.push_str(lines[at]);
            at += 1;
        }
        let recommendation = lines.get(at)?.strip_prefix("➡️ ")?;
        if context.is_empty() || recommendation.is_empty() {
            return None;
        }
        questions.push(
            json!({"id":id,"decides":decides,"context":context,"recommendation":recommendation}),
        );
        at += 1;
    }
    (1..=3).contains(&questions.len()).then(|| json!(questions))
}

fn saved_summary(lines: &[&str]) -> Option<Value> {
    let mut summary = Vec::new();
    for line in lines {
        if line.is_empty() {
            continue;
        }
        if reply_heading(line) {
            break;
        }
        let prefix = format!("{}. ", summary.len() + 1);
        let text = line.strip_prefix(&prefix)?;
        if text.is_empty() {
            return None;
        }
        summary.push(text);
    }
    (1..=10).contains(&summary.len()).then(|| json!(summary))
}

fn source_gap(error: &SourceError) -> Value {
    let kind = match error {
        SourceError::TimedOut { .. } => "timed_out",
        SourceError::Malformed { .. } | SourceError::InvalidId { .. } => "malformed",
        SourceError::NotFound { .. } => "not_found",
        _ => "command_failed",
    };
    gap(
        kind,
        "a required decision source read failed (detail withheld)",
    )
}

fn proposal_bound(request: &Value) -> bool {
    request["kind"] == "plan_approval"
        || proposal_hash(request)
            == request["fingerprint"]
                .as_str()
                .expect("validated fingerprint")
}

fn exact(v: &Value, keys: &[&str]) -> bool {
    v.as_object()
        .is_some_and(|o| o.len() == keys.len() && keys.iter().all(|k| o.contains_key(*k)))
}
fn text(v: &Value) -> bool {
    v.as_str().is_some_and(|s| !s.is_empty())
}
fn positive(v: &Value) -> Option<u64> {
    v.as_u64().filter(|n| *n > 0)
}
fn identifier(s: &str) -> bool {
    s.as_bytes().first().is_some_and(u8::is_ascii_alphanumeric)
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
}
fn question_id(s: &str) -> bool {
    let letters = s.bytes().take_while(u8::is_ascii_uppercase).count();
    (1..=2).contains(&letters)
        && s.get(letters..).is_some_and(|n| {
            !n.starts_with('0') && !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit())
        })
}
fn summary(v: &Value) -> bool {
    v.as_array().is_some_and(|a| {
        (1..=10).contains(&a.len())
            && a.iter().all(|v| {
                v.as_str()
                    .is_some_and(|s| !s.is_empty() && !s.contains(['\r', '\n']))
            })
    })
}

fn valid(v: &Value) -> bool {
    let Some(kind) = v["kind"].as_str() else {
        return false;
    };
    let mut keys = vec!["schema", "kind", "id", "status", "fingerprint", "risk"];
    match kind {
        "grill_round" => keys.extend(["grill_file", "round", "questions", "answered"]),
        "grill_confirmation" => keys.extend(["grill_file", "summary"]),
        "spec_confirmation" | "plan_approval" => {
            keys.extend(["spec", "summary", "headline", "tickets", "graph"])
        }
        _ => return false,
    }
    if !exact(v, &keys)
        || v["schema"] != "openwiz.decisions.v1"
        || !v["id"].as_str().is_some_and(identifier)
        || !matches!(
            v["status"].as_str(),
            Some("open" | "resolved" | "superseded")
        )
        || !matches!(
            v["risk"].as_str(),
            Some("ordinary" | "live" | "release" | "publish" | "unknown")
        )
        || !v["fingerprint"].as_str().is_some_and(|s| {
            s.len() == 64
                && s.bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
    {
        return false;
    }
    if kind.starts_with("grill_") {
        let file = v["grill_file"]
            .as_str()
            .and_then(|s| s.strip_prefix("docs/grills/"))
            .and_then(|s| s.strip_suffix(".md"));
        if !file.is_some_and(|s| {
            s.as_bytes().first().is_some_and(u8::is_ascii_alphanumeric)
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
        }) {
            return false;
        }
    }
    if kind == "grill_round" {
        if positive(&v["round"]).is_none() {
            return false;
        }
        let (Some(questions), Some(answered)) =
            (v["questions"].as_array(), v["answered"].as_array())
        else {
            return false;
        };
        if !(1..=3).contains(&questions.len()) {
            return false;
        }
        let mut ids = Vec::new();
        for q in questions {
            if !exact(q, &["id", "decides", "context", "recommendation"])
                || !["decides", "context", "recommendation"]
                    .iter()
                    .all(|k| text(&q[*k]))
            {
                return false;
            }
            let Some(id) = q["id"].as_str().filter(|id| question_id(id)) else {
                return false;
            };
            if ids.contains(&id) {
                return false;
            }
            ids.push(id);
        }
        let mut prior = None;
        for a in answered {
            let Some(pos) = a.as_str().and_then(|s| ids.iter().position(|&id| id == s)) else {
                return false;
            };
            if prior.is_some_and(|n| n >= pos) {
                return false;
            }
            prior = Some(pos);
        }
        return match v["status"].as_str() {
            Some("open") => answered.len() < questions.len(),
            Some("resolved") => answered.len() == questions.len(),
            _ => true,
        };
    }
    if !summary(&v["summary"]) {
        return false;
    }
    if kind == "grill_confirmation" {
        return true;
    }
    if positive(&v["spec"]).is_none() || !text(&v["headline"]) {
        return false;
    }
    let (Some(tickets), Some(graph)) = (v["tickets"].as_array(), v["graph"].as_array()) else {
        return false;
    };
    if kind == "spec_confirmation" {
        return tickets.is_empty() && graph.is_empty();
    }
    let mut previous = 0;
    let mut edges = Vec::new();
    for ticket in tickets {
        if !exact(ticket, &["number", "title", "blockers"]) || !text(&ticket["title"]) {
            return false;
        }
        let Some(n) = positive(&ticket["number"]).filter(|n| *n > previous) else {
            return false;
        };
        previous = n;
        let Some(blockers) = ticket["blockers"].as_array() else {
            return false;
        };
        let mut last = 0;
        for blocker in blockers {
            let Some(b) = positive(blocker).filter(|b| *b > last && *b != n) else {
                return false;
            };
            last = b;
            edges.push((b, n));
        }
    }
    edges.sort_unstable();
    let expected: Vec<_> = edges
        .into_iter()
        .map(|(blocker, ticket)| json!({"blocker":blocker,"ticket":ticket}))
        .collect();
    graph == &expected
}

fn proposal_hash(request: &Value) -> String {
    let mut proposal = request.clone();
    let object = proposal.as_object_mut().expect("validated request");
    for key in ["fingerprint", "status", "answered"] {
        object.remove(key);
    }
    // Value's map sorts ASCII field names; serde_json's compact UTF-8 encoding
    // uses the contract's escapes and leaves Unicode and slashes unchanged.
    sha256_hex(&serde_json::to_vec(&proposal).expect("JSON proposal"))
}

fn marker_tokens(block: &str) -> Result<bool, ()> {
    let bytes = block.as_bytes();
    let mut cursor = 0;
    let mut marked = false;
    while cursor < bytes.len() {
        if bytes[cursor] != b'"' {
            cursor += 1;
            continue;
        }
        let start = cursor;
        cursor += 1;
        loop {
            match bytes.get(cursor) {
                None => return Err(()),
                Some(b'\\') => cursor += 2,
                Some(b'"') => {
                    cursor += 1;
                    break;
                }
                _ => cursor += 1,
            }
        }
        let value: String = serde_json::from_str(&block[start..cursor]).map_err(|_| ())?;
        marked |= value.starts_with("openwiz.decisions.");
    }
    Ok(marked)
}

fn request(body: &str) -> Result<Option<Value>, ()> {
    let mut marked = body.contains("openwiz.decisions.");
    let escaped = body.contains("\\u");
    // Only Unicode escapes can hide the marker's ASCII letters. Positively
    // unrelated prose is not JSON, even when it contains quotes or fences.
    if !marked && !escaped {
        return Ok(None);
    }
    let mut blocks = Vec::new();
    let mut block = None::<String>;
    let mut other = false;
    for line in body.lines() {
        if line == "```" {
            if let Some(text) = block.take() {
                blocks.push(text);
            } else {
                other = !other;
            }
        } else if line == "```json" && block.is_none() && !other {
            block = Some(String::new());
        } else if line.trim_start().starts_with("```json") {
            return Err(());
        } else if let Some(text) = &mut block {
            text.push_str(line);
            text.push('\n');
        } else if line.starts_with("```") {
            other = true;
        }
    }
    if block.is_some() {
        return Err(());
    }
    let mut fenced_marker = false;
    for block in &blocks {
        fenced_marker |= marker_tokens(block)?;
    }
    // A request identified in a JSON fence is parsed strictly on its own.
    // Prose outside that fence is not JSON and cannot invalidate its tokens.
    // Without an identified fenced request, still inspect escaped unfenced
    // markers and fail closed when malformed tokens prevent classification.
    marked |= fenced_marker || (escaped && marker_tokens(body)?);
    if !marked {
        return Ok(None);
    }
    if blocks.len() != 1 {
        return Err(());
    }
    let v = document(blocks[0].as_bytes()).filter(valid).ok_or(())?;
    Ok(Some(v))
}
