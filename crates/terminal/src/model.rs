//! The read snapshots the screens show, parsed from the existing routes'
//! bodies: `openwiz.inventory.v1` (inventory and session detail),
//! `openwiz.fleet.v1` (fleets and fleet detail) and `openwiz.decisions.v1`.
//! A wrong type, a missing field or an unknown variant in anything shown is
//! an error, never an empty list. Unknown facts stay unknown, with their
//! reason; nothing here invents a risk, wording, time or identity.

use std::collections::BTreeMap;

use serde_json::Value;

/// A value the source reported, or why it is not known.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fact<T> {
    Known(T),
    Unknown(String),
}

impl<T> Fact<T> {
    pub fn known(&self) -> Option<&T> {
        match self {
            Fact::Known(v) => Some(v),
            Fact::Unknown(_) => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Coverage {
    Complete,
    Partial,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Gap {
    pub kind: String,
    pub subject: Option<String>,
    pub detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Session {
    pub id: String,
    pub title: Fact<String>,
    pub provider: Fact<String>,
    pub status: Fact<String>,
    /// `cloud`, or `local` with its machine.
    pub location: Fact<String>,
    /// The project's id and reported name; `None` when ungrouped.
    pub project: Option<(String, Fact<String>)>,
    pub archived: Fact<bool>,
    pub hidden: Fact<bool>,
    pub recap: Fact<Option<String>>,
    pub model: Fact<String>,
    pub effort: Fact<String>,
    pub updated_at: Fact<i64>,
    /// When the session started, only as the source reports it (optional).
    pub started_at: Fact<i64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Inventory {
    pub coverage: Coverage,
    pub snapshot_at: i64,
    pub gaps: Vec<Gap>,
    pub sessions: Vec<Session>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionDetail {
    pub coverage: Coverage,
    pub snapshot_at: i64,
    pub gaps: Vec<Gap>,
    pub session: Session,
    /// `Known(None)`: no final output yet.
    pub final_output: Fact<Option<String>>,
    /// `Known(None)`: no reported error.
    pub reported_error: Fact<Option<String>>,
}

/// The fleet ticket states (`ticket_state`), plus `unknown`.
pub const TICKET_STATES: [&str; 8] = [
    "ready",
    "building",
    "in_review",
    "changes_requested",
    "merged",
    "held",
    "blocked",
    "unknown",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fleet {
    pub spec: u64,
    pub title: Fact<String>,
    /// Ticket counts by state, in [`TICKET_STATES`] order, with the total.
    pub progress: Fact<(u64, [u64; 8])>,
}

/// A fleet-only Needs you fact: a held or needs-info ticket. It carries no
/// answerable proposal (terminal contract: none is invented from labels).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FleetNeed {
    pub kind: String,
    pub spec: u64,
    pub ticket: u64,
    /// The ticket's newest pending question's first line, as written (#539).
    pub wording: Fact<String>,
    pub link: Fact<String>,
    pub asked_at: Fact<i64>,
    /// `live`, `release` or `publish` only when explicitly reported.
    pub risk: Fact<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fleets {
    pub coverage: Coverage,
    pub snapshot_at: i64,
    /// The reasons of the failed or partial reads.
    pub gaps: Vec<Gap>,
    pub fleets: Vec<Fleet>,
    pub needs_you: Fact<Vec<FleetNeed>>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Ticket {
    pub number: u64,
    pub title: Fact<String>,
    pub state: Fact<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FleetDetail {
    pub coverage: Coverage,
    pub snapshot_at: i64,
    pub gaps: Vec<Gap>,
    pub fleet: Fleet,
    pub tickets: Vec<Ticket>,
    pub needs_you: Fact<Vec<FleetNeed>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Freshness {
    Fresh,
    Stale,
    Unknown,
}

/// One open decision record, as the decisions route reported it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decision {
    pub repository: String,
    pub comment_id: u64,
    pub subject_kind: String,
    pub subject_number: u64,
    pub updated_at: i64,
    pub current: Fact<bool>,
    pub kind: String,
    pub id: String,
    pub fingerprint: String,
    pub risk: String,
    /// A confirmation's own words: its headline and summary lines. Empty for
    /// a grill round, whose questions are [`Decision::questions`].
    pub wording: Vec<String>,
    /// A grill round's unanswered questions, in order; answered ones are not
    /// listed (they need nothing more).
    pub questions: Vec<Question>,
    /// The record unchanged, for the answer action's binding.
    pub record: Value,
}

/// One grill question, exactly as recorded.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Question {
    pub id: String,
    pub decides: String,
    pub context: String,
    pub recommendation: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decisions {
    pub snapshot_at: i64,
    pub coverage: Coverage,
    pub gaps: Vec<Gap>,
    pub freshness: Freshness,
    pub source_snapshot_at: Fact<i64>,
    pub target: Fact<Option<String>>,
    pub target_coverage: Coverage,
    pub target_freshness: Freshness,
    /// When the configured target was verified (its own source time).
    pub target_snapshot_at: Fact<i64>,
    pub items: Vec<Decision>,
}

type R<T> = Result<T, String>;

fn get<'a>(v: &'a Value, key: &str) -> R<&'a Value> {
    v.as_object()
        .ok_or_else(|| format!("{key}: the parent is not an object"))?
        .get(key)
        .ok_or_else(|| format!("{key} is missing"))
}
fn string(v: &Value, key: &str) -> R<String> {
    get(v, key)?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("{key} is not a string"))
}
fn int(v: &Value, key: &str) -> R<i64> {
    get(v, key)?
        .as_i64()
        .ok_or_else(|| format!("{key} is not an integer"))
}
fn uint(v: &Value, key: &str) -> R<u64> {
    get(v, key)?
        .as_u64()
        .ok_or_else(|| format!("{key} is not a nonnegative integer"))
}
fn array<'a>(v: &'a Value, key: &str) -> R<&'a Vec<Value>> {
    get(v, key)?
        .as_array()
        .ok_or_else(|| format!("{key} is not an array"))
}
fn schema(v: &Value, expected: &str) -> R<()> {
    if string(v, "schema")? == expected {
        Ok(())
    } else {
        Err(format!("the body is not {expected}"))
    }
}

/// `{"known": x}` or `{"unknown": reason}`; `parse` reads `x`.
fn fact<T>(v: &Value, key: &str, parse: impl Fn(&Value) -> R<T>) -> R<Fact<T>> {
    let v = get(v, key)?;
    let object = v
        .as_object()
        .ok_or_else(|| format!("{key} is not a fact"))?;
    if object.len() != 1 {
        return Err(format!("{key} is not a fact"));
    }
    if let Some(known) = object.get("known") {
        return parse(known)
            .map(Fact::Known)
            .map_err(|e| format!("{key}: {e}"));
    }
    if let Some(reason) = object.get("unknown") {
        let reason = reason
            .as_str()
            .filter(|r| !r.is_empty())
            .ok_or_else(|| format!("{key}: the unknown reason is not text"))?;
        return Ok(Fact::Unknown(reason.to_owned()));
    }
    if let Some(unread) = object.get("unread") {
        let ids = unread
            .as_array()
            .ok_or_else(|| format!("{key}: unread is not a list"))?;
        return Ok(Fact::Unknown(format!(
            "unread: {} incomplete read(s)",
            ids.len()
        )));
    }
    Err(format!("{key} has an unknown variant"))
}
fn as_string(v: &Value) -> R<String> {
    v.as_str()
        .map(str::to_owned)
        .ok_or_else(|| "not a string".into())
}
fn as_bool(v: &Value) -> R<bool> {
    v.as_bool().ok_or_else(|| "not a boolean".into())
}
fn as_int(v: &Value) -> R<i64> {
    v.as_i64().ok_or_else(|| "not an integer".into())
}

fn coverage_state(v: &Value) -> R<Coverage> {
    match string(v, "state")?.as_str() {
        "complete" => Ok(Coverage::Complete),
        "partial" => Ok(Coverage::Partial),
        _ => Err("coverage.state has an unknown variant".into()),
    }
}

fn inventory_gaps(v: &Value) -> R<Vec<Gap>> {
    array(v, "gaps")?
        .iter()
        .map(|g| {
            Ok(Gap {
                kind: string(g, "kind")?,
                subject: match get(g, "subject")? {
                    Value::Null => None,
                    Value::String(s) => Some(s.clone()),
                    _ => return Err("gap.subject is not a string".into()),
                },
                detail: string(g, "detail")?,
            })
        })
        .collect()
}

fn session(v: &Value) -> R<Session> {
    let location = fact(v, "location", |l| match string(l, "kind")?.as_str() {
        "cloud" => Ok("cloud".to_owned()),
        "local" => Ok(match fact(l, "machine", as_string)? {
            Fact::Known(m) => format!("local · {m}"),
            Fact::Unknown(_) => "local".to_owned(),
        }),
        _ => Err("location.kind has an unknown variant".into()),
    })?;
    let group = get(v, "group")?;
    let project = match string(group, "kind")?.as_str() {
        "project" => Some((string(group, "id")?, fact(group, "name", as_string)?)),
        "ungrouped" => None,
        _ => return Err("group.kind has an unknown variant".into()),
    };
    let recap = fact(v, "recap", |r| match string(r, "kind")?.as_str() {
        "purpose_as_reported" => Ok(Some(string(r, "text")?)),
        "no_recap_yet" => Ok(None),
        _ => Err("recap.kind has an unknown variant".into()),
    })?;
    let configuration = get(v, "reported_configuration")?;
    Ok(Session {
        id: string(v, "id")?,
        title: fact(v, "title", as_string)?,
        provider: fact(v, "provider", as_string)?,
        status: fact(v, "status", as_string)?,
        location,
        project,
        archived: fact(v, "archived", as_bool)?,
        hidden: fact(v, "hidden", as_bool)?,
        recap,
        model: fact(configuration, "model", as_string)?,
        effort: fact(configuration, "effort", as_string)?,
        updated_at: fact(v, "updated_at", as_int)?,
        started_at: match v.get("started_at") {
            Some(_) => fact(v, "started_at", as_int)?,
            None => Fact::Unknown("not reported by this server".into()),
        },
    })
}

fn envelope(v: &Value) -> R<(Coverage, i64, Vec<Gap>, &Value)> {
    schema(v, "openwiz.inventory.v1")?;
    Ok((
        coverage_state(get(v, "coverage")?)?,
        int(get(v, "freshness")?, "snapshot_at")?,
        inventory_gaps(v)?,
        get(v, "data")?,
    ))
}

pub fn inventory(v: &Value) -> R<Inventory> {
    let (coverage, snapshot_at, gaps, data) = envelope(v)?;
    Ok(Inventory {
        coverage,
        snapshot_at,
        gaps,
        sessions: array(data, "sessions")?
            .iter()
            .map(session)
            .collect::<R<_>>()?,
    })
}

pub fn session_detail(v: &Value) -> R<SessionDetail> {
    let (coverage, snapshot_at, gaps, data) = envelope(v)?;
    Ok(SessionDetail {
        coverage,
        snapshot_at,
        gaps,
        session: session(get(data, "session")?)?,
        final_output: fact(data, "final_output", |o| {
            match string(o, "kind")?.as_str() {
                "reported" => Ok(Some(string(o, "text")?)),
                "no_final_output_yet" => Ok(None),
                _ => Err("final_output.kind has an unknown variant".into()),
            }
        })?,
        reported_error: fact(data, "reported_error", |e| match e {
            Value::Null => Ok(None),
            _ => Ok(Some(string(e, "text")?)),
        })?,
    })
}

/// The fleet envelope's reads, by id: issue titles and failed reads.
struct Reads<'a>(BTreeMap<&'a str, &'a Value>);

impl<'a> Reads<'a> {
    fn of(v: &'a Value) -> R<Self> {
        let mut map = BTreeMap::new();
        for read in array(v, "reads")? {
            let id = get(read, "id")?
                .as_str()
                .ok_or("a read id is not a string")?;
            if map.insert(id, read).is_some() {
                return Err("a read id repeats".into());
            }
        }
        Ok(Self(map))
    }

    fn gaps(&self) -> R<Vec<Gap>> {
        let mut gaps = Vec::new();
        for (id, read) in &self.0 {
            let outcome = get(read, "outcome")?;
            match string(outcome, "state")?.as_str() {
                "complete" => {}
                "failed" | "partial" => gaps.push(Gap {
                    kind: string(outcome, "gap")?,
                    subject: Some(format!("{} {id}", string(read, "kind")?)),
                    detail: string(outcome, "reason")?,
                }),
                _ => return Err("a read outcome has an unknown variant".into()),
            }
        }
        Ok(gaps)
    }

    fn title(&self, id: &Value) -> R<Fact<String>> {
        let id = id.as_str().ok_or("a read id is not a string")?;
        let read = self.0.get(id).ok_or("a read id does not resolve")?;
        let outcome = get(read, "outcome")?;
        match string(outcome, "state")?.as_str() {
            "complete" => Ok(Fact::Known(string(get(outcome, "value")?, "title")?)),
            _ => Ok(Fact::Unknown(string(outcome, "reason")?)),
        }
    }
}

fn fleet_envelope<'a>(v: &'a Value, view: &str) -> R<(Coverage, i64, Reads<'a>, &'a Value)> {
    schema(v, "openwiz.fleet.v1")?;
    let data = get(v, "data")?;
    if string(data, "view")? != view {
        return Err(format!("the fleet body is not the {view} view"));
    }
    Ok((
        coverage_state(get(v, "coverage")?)?,
        int(get(v, "freshness")?, "snapshot_at")?,
        Reads::of(v)?,
        data,
    ))
}

fn fleet(v: &Value, reads: &Reads) -> R<Fleet> {
    let progress = fact(v, "progress", |c| {
        let mut counts = [0u64; 8];
        for (i, state) in TICKET_STATES.iter().enumerate() {
            counts[i] = uint(c, state)?;
        }
        Ok((uint(c, "tickets")?, counts))
    })?;
    Ok(Fleet {
        spec: uint(v, "spec")?,
        title: reads.title(get(v, "issue")?)?,
        progress,
    })
}

fn needs(v: &Value) -> R<Fact<Vec<FleetNeed>>> {
    fact(v, "needs_you", |list| {
        list.as_array()
            .ok_or("needs_you is not a list")?
            .iter()
            .map(|n| {
                let kind = string(n, "kind")?;
                if !matches!(kind.as_str(), "needs_info" | "held") {
                    return Err("needs_you.kind has an unknown variant".into());
                }
                Ok(FleetNeed {
                    kind,
                    spec: uint(n, "spec")?,
                    ticket: uint(n, "ticket")?,
                    wording: fact(n, "wording", as_string)?,
                    link: fact(n, "link", as_string)?,
                    asked_at: fact(n, "asked_at", as_int)?,
                    risk: fact(n, "risk", |r| {
                        let r = as_string(r)?;
                        if matches!(r.as_str(), "live" | "release" | "publish") {
                            Ok(r)
                        } else {
                            Err("risk has an unknown variant".into())
                        }
                    })?,
                })
            })
            .collect()
    })
}

pub fn fleets(v: &Value) -> R<Fleets> {
    let (coverage, snapshot_at, reads, data) = fleet_envelope(v, "fleets")?;
    Ok(Fleets {
        coverage,
        snapshot_at,
        gaps: reads.gaps()?,
        fleets: array(data, "fleets")?
            .iter()
            .map(|f| fleet(f, &reads))
            .collect::<R<_>>()?,
        needs_you: needs(data)?,
    })
}

pub fn fleet_detail(v: &Value) -> R<FleetDetail> {
    let (coverage, snapshot_at, reads, data) = fleet_envelope(v, "fleet")?;
    let tickets = array(data, "tickets")?
        .iter()
        .map(|t| {
            Ok(Ticket {
                number: uint(t, "number")?,
                title: reads.title(get(t, "issue")?)?,
                state: fact(t, "state", |s| {
                    let s = as_string(s)?;
                    if TICKET_STATES[..7].contains(&s.as_str()) {
                        Ok(s)
                    } else {
                        Err("state has an unknown variant".into())
                    }
                })?,
            })
        })
        .collect::<R<_>>()?;
    Ok(FleetDetail {
        coverage,
        snapshot_at,
        gaps: reads.gaps()?,
        fleet: fleet(get(data, "fleet")?, &reads)?,
        tickets,
        needs_you: needs(data)?,
    })
}

fn decision_coverage(v: &Value) -> R<(Coverage, Vec<Gap>)> {
    let state = coverage_state(v)?;
    let gaps = array(v, "gaps")?
        .iter()
        .map(|g| {
            Ok(Gap {
                kind: string(g, "kind")?,
                subject: None,
                detail: string(g, "detail")?,
            })
        })
        .collect::<R<Vec<_>>>()?;
    if (state == Coverage::Complete) != gaps.is_empty() {
        return Err("decisions coverage and its gaps disagree".into());
    }
    Ok((state, gaps))
}

fn freshness(v: &Value) -> R<(Freshness, Fact<i64>)> {
    let state = match string(v, "state")?.as_str() {
        "fresh" => Freshness::Fresh,
        "stale" => Freshness::Stale,
        "unknown" => Freshness::Unknown,
        _ => return Err("freshness.state has an unknown variant".into()),
    };
    Ok((state, fact(v, "snapshot_at", as_int)?))
}

const RISKS: [&str; 5] = ["ordinary", "live", "release", "publish", "unknown"];

fn decision(v: &Value) -> R<Decision> {
    let subject = get(v, "subject")?;
    let subject_kind = string(subject, "kind")?;
    if !matches!(subject_kind.as_str(), "issue" | "pull_request") {
        return Err("subject.kind has an unknown variant".into());
    }
    let request = get(v, "request")?;
    let kind = string(request, "kind")?;
    let risk = string(request, "risk")?;
    if !RISKS.contains(&risk.as_str()) {
        return Err("risk has an unknown variant".into());
    }
    if string(request, "status")? != "open" {
        return Err("an item is not open".into());
    }
    let (wording, questions) = match kind.as_str() {
        "grill_round" => {
            let answered: Vec<String> = array(request, "answered")?
                .iter()
                .map(as_string)
                .collect::<R<_>>()?;
            let mut pending = Vec::new();
            for q in array(request, "questions")? {
                let question = Question {
                    id: string(q, "id")?,
                    decides: string(q, "decides")?,
                    context: string(q, "context")?,
                    recommendation: string(q, "recommendation")?,
                };
                if !answered.contains(&question.id) {
                    pending.push(question);
                }
            }
            (Vec::new(), pending)
        }
        "grill_confirmation" | "spec_confirmation" | "plan_approval" => {
            let mut words = Vec::new();
            for key in ["headline", "summary"] {
                match request.get(key) {
                    Some(Value::String(s)) => words.push(s.clone()),
                    Some(Value::Array(lines)) => {
                        for line in lines {
                            words.push(as_string(line)?);
                        }
                    }
                    Some(_) => return Err(format!("{key} is not text")),
                    None => {}
                }
            }
            (words, Vec::new())
        }
        _ => return Err("request.kind has an unknown variant".into()),
    };
    Ok(Decision {
        repository: string(subject, "repository")?,
        comment_id: uint(v, "comment_id")?,
        subject_kind,
        subject_number: uint(subject, "number")?,
        updated_at: int(v, "updated_at")?,
        current: fact(v, "current", as_bool)?,
        kind,
        id: string(request, "id")?,
        fingerprint: string(request, "fingerprint")?,
        risk,
        wording,
        questions,
        record: request.clone(),
    })
}

pub fn decisions(v: &Value) -> R<Decisions> {
    schema(v, "openwiz.decisions.v1")?;
    if string(v, "kind")? != "response" {
        return Err("the decisions body is not a response".into());
    }
    let (coverage, gaps) = decision_coverage(get(v, "coverage")?)?;
    let (source_freshness, source_snapshot_at) = freshness(get(v, "freshness")?)?;
    let orchestrator = get(v, "orchestrator")?;
    let (target_coverage, _) = decision_coverage(get(orchestrator, "coverage")?)?;
    let (target_freshness, target_snapshot_at) = freshness(get(orchestrator, "freshness")?)?;
    Ok(Decisions {
        snapshot_at: int(v, "snapshot_at")?,
        coverage,
        gaps,
        freshness: source_freshness,
        source_snapshot_at,
        target: fact(orchestrator, "target", |t| match t {
            Value::Null => Ok(None),
            _ => as_string(t).map(Some),
        })?,
        target_coverage,
        target_freshness,
        target_snapshot_at,
        items: array(v, "items")?.iter().map(decision).collect::<R<_>>()?,
    })
}
