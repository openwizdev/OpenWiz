//! #2034: production notification source bindings over existing owners.
//!
//! Decisions come from the existing decisions route (decisions.v1 response),
//! read over the service's own loopback API, so its currentness, wording, risk
//! and configured-target rules stay in one place. Incidents come from the
//! health owner's saved state; only its explicit Needs you is an escalation.
//! Optional event categories stay unavailable until their owners publish a
//! positively bound stable identity. Nothing here decides recovery or answers.
use super::engine::{Batch, Sources};
use openwiz_core::{
    messaging::sha256_hex,
    notifications::{grouping, model::*},
    ops::Clock,
};
use openwiz_store::notifications::{Error, Observation, text};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{ErrorKind, Read as _, Write},
    net::{Ipv4Addr, SocketAddr, TcpStream},
    sync::{Arc, Mutex},
    time::Instant,
};

/// Returns the existing decisions route's exact response document.
pub type DecisionsRead = Arc<dyn Fn(Instant) -> Result<Value, Error> + Send + Sync>;
/// Returns the health owner's current published service state document.
pub type HealthRead = Arc<dyn Fn() -> Result<Value, Error> + Send + Sync>;

const DECISIONS_UNREAD: &str = "Current decisions route is unread; no decision is eligible";
const HEALTH_UNREAD: &str = "Health owner state or its last completed pass is unread";
const MAX_RESPONSE: usize = 16 * 1024 * 1024;

/// One marked comment as the existing decisions scan read it.
#[derive(Clone, Debug)]
pub struct CommentRecord {
    pub repository: String,
    pub id: u64,
    pub subject: u64,
    pub body: String,
}
/// A complete, unambiguous decisions comment scan, or an error. Used only to
/// find the exact remembered request's own terminal status.
pub type CommentsRead = Arc<dyn Fn(Instant) -> Result<Vec<CommentRecord>, Error> + Send + Sync>;

/// Facts previously seen for still-open groups. Terminal evidence is sought
/// only for these, and only from their own exact source records.
#[derive(Default)]
struct Memory {
    decisions: BTreeMap<Vec<u8>, Observation>,
    /// The incident's last observation, its saved healthy-since mark and,
    /// for a watchdog incident, its exact problem (`broken`): the recovery evidence.
    incidents: BTreeMap<Vec<u8>, (Observation, Option<u64>, Option<Value>)>,
    /// Terminal facts emitted in the current pass; forgotten once it completes.
    closing: BTreeSet<Vec<u8>>,
}

/// Production `Sources` for the installed engine. Construction reads only the
/// already validated service configuration; reads happen on each pass.
pub struct Installed {
    repository: Repository,
    owner: Id,
    decisions: DecisionsRead,
    health: HealthRead,
    comments: CommentsRead,
    clock: Arc<dyn Clock>,
    memory: Mutex<Memory>,
    /// Owner-only durable copy of the recovery evidence, so a restart after
    /// the owner removes a healed incident can still close its group.
    evidence: Option<std::path::PathBuf>,
}

impl Installed {
    pub fn new(
        config: &Value,
        decisions: DecisionsRead,
        health: HealthRead,
        comments: CommentsRead,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, String> {
        let repository = config["repository"]["owner"]
            .as_str()
            .zip(config["repository"]["name"].as_str())
            .and_then(|(o, n)| Repository::new(format!("{o}/{n}").to_ascii_lowercase()))
            .ok_or("notification repository is invalid")?;
        // The incident owner is the durable recovery-state namespace: the
        // configured project this service's saved incidents belong to.
        let owner = config["project"]
            .as_str()
            .and_then(Id::new)
            .ok_or("notification incident owner is invalid")?;
        Ok(Self {
            repository,
            owner,
            decisions,
            health,
            comments,
            clock,
            memory: Mutex::default(),
            evidence: None,
        })
    }
    /// Keep recovery evidence in `service/notifications/recovery-evidence.json`
    /// under this state root (0600, atomic replace). Without it, evidence lives
    /// for the process only.
    pub fn durable(mut self, root: &std::path::Path) -> Self {
        self.evidence = Some(root.join("service/notifications/recovery-evidence.json"));
        self
    }
    /// Remember the persisted open groups (after a restart), so their exact
    /// terminal evidence is still sought. Closed groups are never reopened.
    pub fn seed<'a>(&self, open: impl IntoIterator<Item = &'a Observation>) {
        let Ok(mut memory) = self.memory.lock() else {
            return;
        };
        for o in open {
            let key = grouping::key(&o.fact);
            match &o.fact {
                SourceFact::Decision(_) => {
                    memory.decisions.entry(key).or_insert_with(|| o.clone());
                }
                SourceFact::Incident(_) => {
                    memory
                        .incidents
                        .entry(key)
                        .or_insert_with(|| (o.clone(), None, None));
                }
                SourceFact::Event(_) => {}
            }
        }
        // Restore saved evidence only for groups that are still open.
        for (key, since, kind) in self
            .evidence
            .as_deref()
            .map(load_evidence)
            .unwrap_or_default()
        {
            if let Some(entry) = memory.incidents.get_mut(&key) {
                entry.1 = since;
                entry.2 = kind;
            }
        }
    }
    fn save_evidence(&self, memory: &Memory) {
        if let Some(path) = &self.evidence {
            let rows: Vec<_> = memory
                .incidents
                .iter()
                .filter(|(_, (_, since, kind))| since.is_some() || kind.is_some())
                .map(|(key, (_, since, kind))| {
                    json!({"key": hex(key), "healthy_since": since, "watchdog_problem": kind})
                })
                .collect();
            let doc = json!({"schema": EVIDENCE_SCHEMA, "incidents": rows});
            if write_private(path, doc.to_string().as_bytes()).is_err() {
                eprintln!("openwiz-service: notification recovery evidence was not saved");
            }
        }
    }
    /// Called after a pass whose observations were durably saved.
    pub fn settle(&self) {
        if let Ok(mut memory) = self.memory.lock() {
            for key in std::mem::take(&mut memory.closing) {
                memory.decisions.remove(&key);
                memory.incidents.remove(&key);
            }
            self.save_evidence(&memory);
        }
    }
    fn now(&self) -> Result<u64, Error> {
        u64::try_from(self.clock.now().0).map_err(|_| Error::Unavailable)
    }
    fn decisions(&self, deadline: Instant, lifecycle: bool) -> Read {
        let mut read = match (self.decisions)(deadline) {
            Ok(doc) => decision_facts(&doc).unwrap_or_else(|| Read::unread(DECISIONS_UNREAD)),
            Err(_) => Read::unread(DECISIONS_UNREAD),
        };
        if !read.complete() {
            return read;
        }
        let Ok(mut memory) = self.memory.lock() else {
            return Read::unread(DECISIONS_UNREAD);
        };
        let current: BTreeSet<_> = read
            .observations
            .iter()
            .map(|o| grouping::key(&o.fact))
            .collect();
        for o in &read.observations {
            memory.decisions.insert(grouping::key(&o.fact), o.clone());
        }
        // The complete open list omits resolved/superseded requests. Absence
        // closes nothing: only the same comment's own terminal record does.
        let absent: Vec<_> = memory
            .decisions
            .iter()
            .filter(|(k, _)| !current.contains(*k))
            .map(|(k, o)| (k.clone(), o.clone()))
            .collect();
        if !lifecycle || absent.is_empty() {
            return read;
        }
        let (Ok(comments), Ok(now)) = ((self.comments)(deadline), self.now()) else {
            read.gaps.push(text(
                "Decision lifecycle records are unread; earlier requests stay open",
            ));
            return read;
        };
        for (key, remembered) in absent {
            let SourceFact::Decision(d) = &remembered.fact else {
                continue;
            };
            if let Some(state) = terminal_decision(&d.binding, &comments) {
                let mut closed = d.clone();
                closed.state = state;
                closed.current = Fact::Known(false);
                closed.coverage = coverage(&[], SourceOwner::Decisions);
                closed.freshness = Freshness {
                    state: FreshnessState::Fresh,
                    snapshot_at: Fact::Known(now),
                };
                read.observations.push(Observation {
                    fact: SourceFact::Decision(closed),
                    content_binding: remembered.content_binding.clone(),
                });
                memory.closing.insert(key);
            }
        }
        read
    }
    fn incidents(&self) -> Read {
        match (self.health)() {
            Ok(state) => self
                .incident_facts(&state)
                .unwrap_or_else(|| Read::unread(HEALTH_UNREAD)),
            Err(_) => Read::unread(HEALTH_UNREAD),
        }
    }
}

/// One owner's read: facts plus that owner's own coverage and freshness.
struct Read {
    observations: Vec<Observation>,
    /// Gaps that make the whole owner read incomplete.
    gaps: Vec<Text>,
    /// Gaps of single items only: reported in coverage, but they leave the
    /// owner's other, independently current items eligible.
    local: Vec<Text>,
    freshness: Freshness,
}
impl Read {
    fn unread(reason: &str) -> Self {
        Self {
            observations: vec![],
            gaps: vec![text(reason)],
            local: vec![],
            freshness: unknown_freshness(),
        }
    }
    fn complete(&self) -> bool {
        self.gaps.is_empty() && self.freshness.state == FreshnessState::Fresh
    }
}

fn unknown_freshness() -> Freshness {
    Freshness {
        state: FreshnessState::Unknown,
        snapshot_at: Fact::Unknown(text("No complete current source snapshot")),
    }
}
fn coverage(gaps: &[Text], source: SourceOwner) -> Coverage {
    Coverage {
        state: if gaps.is_empty() {
            CoverageState::Complete
        } else {
            CoverageState::Partial
        },
        gaps: gaps
            .iter()
            .map(|reason| Gap {
                source,
                reason: reason.clone(),
            })
            .collect(),
    }
}

impl Sources for Installed {
    fn read(&self, deadline: Instant) -> Result<Batch, Error> {
        let decisions = self.decisions(deadline, true);
        let incidents = self.incidents();
        let mut gaps = coverage(&decisions.gaps, SourceOwner::Decisions).gaps;
        gaps.extend(coverage(&incidents.gaps, SourceOwner::ServiceHealth).gaps);
        gaps.extend(coverage(&incidents.local, SourceOwner::ServiceHealth).gaps);
        if decisions.freshness.state != FreshnessState::Fresh && decisions.gaps.is_empty() {
            gaps.push(Gap {
                source: SourceOwner::Decisions,
                reason: text("Decisions snapshot is not fresh"),
            });
        }
        if incidents.freshness.state != FreshnessState::Fresh && incidents.gaps.is_empty() {
            gaps.push(Gap {
                source: SourceOwner::ServiceHealth,
                reason: text("Health owner's last completed pass is not fresh"),
            });
        }
        let freshness = match (
            &decisions.freshness.snapshot_at,
            &incidents.freshness.snapshot_at,
        ) {
            (Fact::Known(a), Fact::Known(b)) => Freshness {
                state: if decisions.freshness.state == FreshnessState::Fresh
                    && incidents.freshness.state == FreshnessState::Fresh
                {
                    FreshnessState::Fresh
                } else {
                    FreshnessState::Stale
                },
                snapshot_at: Fact::Known(*a.min(b)),
            },
            _ => unknown_freshness(),
        };
        let sources = Category::ALL
            .into_iter()
            .map(|category| category_status(category, &decisions, &incidents))
            .collect();
        let mut observations = decisions.observations;
        observations.extend(incidents.observations);
        Ok(Batch {
            observations,
            sources,
            coverage: Coverage {
                state: if gaps.is_empty() {
                    CoverageState::Complete
                } else {
                    CoverageState::Partial
                },
                gaps,
            },
            freshness,
        })
    }

    /// Re-reads the owning source; never echoes the input. Absence, ambiguity
    /// or an unread owner is an error, so the engine cancels with zero effects.
    fn recheck(&self, original: &Observation, deadline: Instant) -> Result<Observation, Error> {
        let read = match original.fact {
            SourceFact::Decision(_) => self.decisions(deadline, false),
            SourceFact::Incident(_) => self.incidents(),
            SourceFact::Event(_) => return Err(Error::Unavailable),
        };
        let key = grouping::key(&original.fact);
        let mut found = read
            .observations
            .into_iter()
            .filter(|o| grouping::key(&o.fact) == key);
        match (found.next(), found.next()) {
            (Some(current), None) => Ok(current),
            _ => Err(Error::Unavailable),
        }
    }
}

fn category_status(category: Category, decisions: &Read, incidents: &Read) -> CategoryStatus {
    let (available, reason) = match category {
        Category::Decision if decisions.complete() => (
            Fact::Known(true),
            "Existing decisions route read completely; each request still needs independent currentness",
        ),
        Category::Decision => (
            Fact::Unknown(text(DECISIONS_UNREAD)),
            "Independent saved wording/current proposal or configured answer-target verification unavailable",
        ),
        Category::RecoveryEscalation if incidents.complete() => (
            Fact::Known(true),
            "Health owner's explicit Needs you escalation after its existing recovery limits",
        ),
        Category::RecoveryEscalation => (
            Fact::Unknown(text(HEALTH_UNREAD)),
            "No explicit owning escalation; active repair, unread health or watchdog fault alone is insufficient",
        ),
        _ => (
            Fact::Known(false),
            "This build binds no positively current stable source for this optional category",
        ),
    };
    CategoryStatus {
        category,
        available,
        reason: text(reason),
    }
}

/// Project the decisions.v1 response. None means its shape is not the route's.
fn decision_facts(doc: &Value) -> Option<Read> {
    if doc["schema"] != "openwiz.decisions.v1" || doc["kind"] != "response" {
        return None;
    }
    let freshness: Freshness = serde_json::from_value(doc["freshness"].clone()).ok()?;
    let mut gaps = Vec::new();
    if doc["coverage"]["state"] != "complete" || doc["coverage"]["gaps"] != json!([]) {
        gaps.push(text(
            "Decisions route reports a coverage gap; requests are not independently current",
        ));
    }
    let target = &doc["orchestrator"]["target"];
    let target_known = doc["orchestrator"]["coverage"]["state"] == "complete"
        && doc["orchestrator"]["freshness"]["state"] == "fresh"
        && target["known"].is_string();
    if !target_known {
        gaps.push(text("Configured answer target is not verified current"));
    }
    let mut observations = Vec::new();
    for item in doc["items"].as_array()? {
        let Some(fact) = decision_fact(item, &gaps, &freshness) else {
            gaps.push(text("A decisions route item has an unsupported identity"));
            continue;
        };
        // The binding covers exact saved wording/risk (the whole request), its
        // subject/comment identity and the verified answer target.
        let bound = json!({"subject":item["subject"],"comment_id":item["comment_id"],
            "created_at":item["created_at"],"request":item["request"],"target":target});
        observations.push(Observation {
            fact: SourceFact::Decision(fact),
            content_binding: Fingerprint::new(sha256_hex(bound.to_string().as_bytes()))?,
        });
    }
    // A gap found while projecting applies to every item of this read.
    for o in &mut observations {
        if let SourceFact::Decision(d) = &mut o.fact {
            d.coverage = coverage(&gaps, SourceOwner::Decisions);
            if !gaps.is_empty() {
                d.current = match &d.current {
                    Fact::Known(true) => Fact::Unknown(text("Decisions read is incomplete")),
                    other => other.clone(),
                };
            }
        }
    }
    Some(Read {
        observations,
        gaps,
        local: vec![],
        freshness,
    })
}

fn decision_fact(item: &Value, gaps: &[Text], freshness: &Freshness) -> Option<DecisionFact> {
    let request = &item["request"];
    let kind = match item["subject"]["kind"].as_str()? {
        "issue" => SubjectKind::Issue,
        "pull_request" => SubjectKind::PullRequest,
        _ => return None,
    };
    let risk = match request["risk"].as_str()? {
        "ordinary" => Risk::Ordinary,
        "live" => Risk::Live,
        "release" => Risk::Release,
        "publish" => Risk::Publish,
        "unknown" => Risk::Unknown,
        _ => return None,
    };
    if request["status"] != "open" {
        return None;
    }
    let current = match &item["current"] {
        Value::Object(o) if o.len() == 1 && o["known"].is_boolean() => {
            Fact::Known(o["known"].as_bool()?)
        }
        Value::Object(o) if o.len() == 1 && o["unknown"].is_string() => Fact::Unknown(text(
            "Decisions route reports this request's currentness as unknown",
        )),
        _ => return None,
    };
    // An unknown fact needs a gap; the route always reports one alongside it.
    if matches!(current, Fact::Unknown(_)) && gaps.is_empty() {
        return None;
    }
    Some(DecisionFact {
        binding: DecisionRef {
            repository: Repository::new(item["subject"]["repository"].as_str()?)?,
            subject: Subject {
                kind,
                number: item["subject"]["number"].as_u64()?.try_into().ok()?,
            },
            comment_id: item["comment_id"].as_u64()?.try_into().ok()?,
            request_id: RequestId::new(request["id"].as_str()?)?,
            fingerprint: Fingerprint::new(request["fingerprint"].as_str()?)?,
        },
        state: RequestState::Open,
        current,
        risk,
        coverage: coverage(gaps, SourceOwner::Decisions),
        freshness: freshness.clone(),
    })
}

/// The subject an incident's latest health result must positively describe.
#[derive(Clone, Debug, PartialEq, Eq)]
enum Target {
    Check(&'static str),
    Loop(String),
    FleetThread(u64),
    Watchdog(String),
}
impl Target {
    /// Derived from the notification subject alone, so remembered and seeded
    /// incidents bind to the same result as fresh ones.
    fn of(binding: &IncidentRef) -> Option<Self> {
        let subject = binding.subject.as_str();
        Some(match (binding.source, subject) {
            (RecoverySource::LoopWatchdog, s) => {
                Self::Watchdog(s.strip_prefix("watchdog-")?.into())
            }
            (_, "cloudroom") => Self::Check("cloudroom"),
            (_, "tick") => Self::Check("tick"),
            (_, "server") => Self::Check("server"),
            (_, s) if s.starts_with("loop-") => Self::Loop(s["loop-".len()..].into()),
            (_, s) => Self::FleetThread(s.strip_prefix("fleet-thread-")?.parse().ok()?),
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Observed {
    Broken,
    Healthy,
    Unread,
}

/// The subject's own result in the last completed pass. An unread list, an
/// unknown observation or a missing row is Unread, never Broken or Healthy.
fn latest(results: &[Value], target: &Target, problem: Option<&Value>) -> Observed {
    let state = |r: &Value| match r["observed"]["state"].as_str() {
        Some("broken") => Observed::Broken,
        Some("healthy") => Observed::Healthy,
        _ => Observed::Unread,
    };
    let one = |check: &str, matches: &dyn Fn(&Value) -> bool| {
        if results
            .iter()
            .any(|r| r["check"] == check && r.get("unread").is_some())
        {
            return Observed::Unread;
        }
        let mut found = results.iter().filter(|r| r["check"] == check && matches(r));
        match (found.next(), found.next()) {
            (Some(r), None) => state(r),
            _ => Observed::Unread,
        }
    };
    match target {
        Target::Check(check) => one(check, &|_| true),
        Target::Loop(id) => one("loop", &|r| r["loop"]["id"] == id.as_str()),
        Target::FleetThread(spec) => one("fleet_thread", &|r| r["spec"] == *spec),
        Target::Watchdog(loop_id) => {
            // Bound to the incident's exact problem. Unknown evidence matches
            // its loop and fault kind; another kind of the loop is unrelated.
            let Some(problem) = problem else {
                return Observed::Unread;
            };
            let kind = &problem["what"];
            let mut found = results.iter().filter(|r| r["check"] == "watchdog");
            let (Some(r), None) = (found.next(), found.next()) else {
                return Observed::Unread;
            };
            let named = |rows: &Value, field: &dyn Fn(&Value) -> &Value, want: &Value| {
                rows.as_array().is_none_or(|rows| {
                    rows.iter()
                        .any(|p| p["loop_id"] == loop_id.as_str() && field(p) == want)
                })
            };
            if r["snapshot_unknown"] != false || named(&r["unknown"], &|p| &p["kind"], kind) {
                Observed::Unread
            } else if named(&r["open"], &|p| &p["broken"], problem) {
                Observed::Broken
            } else {
                Observed::Healthy
            }
        }
    }
}
impl Installed {
    /// Project the health owner's saved incidents, each bound to its own
    /// subject's latest result. None means the state is not a service state
    /// document. Freshness is the last completed health pass.
    fn incident_facts(&self, state: &Value) -> Option<Read> {
        if state["schema"] != "openwiz.service-state.v1" {
            return None;
        }
        let mut gaps = Vec::new();
        let pass_at = state["last_pass"]["at"].as_u64();
        let freshness = match (pass_at, self.now().ok()) {
            (Some(at), Some(now)) if at <= now => Freshness {
                state: if now - at <= 70_000 {
                    FreshnessState::Fresh
                } else {
                    FreshnessState::Stale
                },
                snapshot_at: Fact::Known(at),
            },
            _ => {
                gaps.push(text(HEALTH_UNREAD));
                unknown_freshness()
            }
        };
        let empty = vec![];
        let results = state["last_pass"]["results"].as_array().unwrap_or(&empty);
        let mut memory = self.memory.lock().ok()?;
        let mut observations = Vec::new();
        let mut present = BTreeSet::new();
        let mut local = Vec::new();
        let mut changed = false;
        for incident in state["incidents"].as_array()? {
            let Some((binding, saved_escalation)) =
                incident_ref(incident, &self.repository, &self.owner)
            else {
                let gap = text("A saved incident has no stable notification identity");
                if !local.contains(&gap) {
                    local.push(gap);
                }
                continue;
            };
            let kind = (binding.source == RecoverySource::LoopWatchdog)
                .then(|| incident["broken"].clone())
                .filter(Value::is_object);
            let observed = Target::of(&binding)
                .map_or(Observed::Unread, |t| latest(results, &t, kind.as_ref()));
            // This incident's own uncertainty stays its own; other incidents
            // of the same pass remain independently eligible.
            let mut own = gaps.clone();
            if observed == Observed::Unread {
                let gap =
                    text("An incident's subject is unread or unknown in the last health pass");
                own.push(gap.clone());
                if !local.contains(&gap) {
                    local.push(gap);
                }
            }
            let escalated = saved_escalation && observed == Observed::Broken;
            let fact = IncidentFact {
                binding,
                state: if escalated {
                    IncidentState::Escalated
                } else {
                    IncidentState::Repairing
                },
                owner_escalated: if observed == Observed::Unread {
                    Fact::Unknown(text(
                        "The incident's subject is unread in the last health pass",
                    ))
                } else {
                    Fact::Known(escalated)
                },
                coverage: coverage(&own, SourceOwner::ServiceHealth),
                freshness: freshness.clone(),
            };
            // Observations may change during one incident; its identity does not.
            let bound = json!({"incident": incident["id"], "opened_at": incident["opened_at"],
                "check": incident["check"]});
            let observation = Observation {
                fact: SourceFact::Incident(fact),
                content_binding: Fingerprint::new(sha256_hex(bound.to_string().as_bytes()))?,
            };
            let key = grouping::key(&observation.fact);
            present.insert(key.clone());
            let since = incident["healthy_since"].as_u64();
            let evidence = |e: &(Observation, Option<u64>, Option<Value>)| (e.1, e.2.clone());
            changed |= memory.incidents.get(&key).map(evidence) != Some((since, kind.clone()));
            memory
                .incidents
                .insert(key, (observation.clone(), since, kind));
            observations.push(observation);
        }
        // The owner drops an incident only after its own healing rule: healthy
        // for HEALTHY_FOR_MS (watchdog: its problem no longer open). Absence
        // alone heals nothing; recovery needs that rule positively observed.
        if gaps.is_empty() && freshness.state == FreshnessState::Fresh {
            let at = pass_at?;
            let healed: Vec<_> = memory
                .incidents
                .iter()
                .filter(|(k, _)| !present.contains(*k))
                .filter_map(|(k, (o, since, kind))| {
                    let SourceFact::Incident(i) = &o.fact else {
                        return None;
                    };
                    let target = Target::of(&i.binding)?;
                    // Watchdog: its exact problem (loop and kind) is positively
                    // no longer open; without the saved kind there is no rule.
                    let rule = if matches!(target, Target::Watchdog(_)) {
                        kind.is_some()
                    } else {
                        since.is_some_and(|s| {
                            at.saturating_sub(s)
                                >= openwiz_core::health::HEALTHY_FOR_MS.unsigned_abs()
                        })
                    };
                    (rule && latest(results, &target, kind.as_ref()) == Observed::Healthy)
                        .then(|| (k.clone(), o.clone()))
                })
                .collect();
            for (key, o) in healed {
                let SourceFact::Incident(mut i) = o.fact else {
                    continue;
                };
                i.state = IncidentState::Recovered;
                i.owner_escalated = Fact::Known(false);
                i.coverage = coverage(&[], SourceOwner::ServiceHealth);
                i.freshness = freshness.clone();
                observations.push(Observation {
                    fact: SourceFact::Incident(i),
                    content_binding: o.content_binding,
                });
                memory.closing.insert(key);
            }
        }
        if changed {
            self.save_evidence(&memory);
        }
        Some(Read {
            observations,
            gaps,
            local,
            freshness,
        })
    }
}

/// The remembered request's own comment, read in a complete scan: exactly one
/// such comment on the same subject, exactly one fenced decisions record with
/// the same id and fingerprint, whose status is terminal. Anything else is
/// no evidence, so the group stays open.
fn terminal_decision(binding: &DecisionRef, comments: &[CommentRecord]) -> Option<RequestState> {
    let mut found = comments.iter().filter(|c| {
        c.id == binding.comment_id.get()
            && c.repository
                .eq_ignore_ascii_case(binding.repository.as_str())
    });
    let (Some(comment), None) = (found.next(), found.next()) else {
        return None;
    };
    if comment.subject != binding.subject.number.get() {
        return None;
    }
    let mut blocks = Vec::new();
    let mut block = None::<String>;
    for line in comment.body.lines() {
        match (&mut block, line) {
            (None, "```json") => block = Some(String::new()),
            (Some(_), "```") => blocks.push(block.take()?),
            (Some(text), line) => {
                text.push_str(line);
                text.push('\n');
            }
            (None, _) => {}
        }
    }
    let ([record], None) = (blocks.as_slice(), block) else {
        return None;
    };
    let record = openwiz_adapter_github::decisions::document(record.as_bytes())?;
    if record["schema"] != "openwiz.decisions.v1"
        || record["id"] != binding.request_id.as_str()
        || record["fingerprint"] != binding.fingerprint.as_str()
    {
        return None;
    }
    match record["status"].as_str()? {
        "resolved" => Some(RequestState::Resolved),
        "superseded" => Some(RequestState::Superseded),
        _ => None,
    }
}

/// Project one saved incident's existing identity and saved escalation. Only
/// the saved Needs you of an incident not marked healthy-since is a saved
/// escalation; whether it is still current depends on the subject's latest
/// result. This adds no recovery rule. The id is bound to its opening time,
/// so a reset state's reused `i1` never joins an older incident.
fn incident_ref(
    incident: &Value,
    repository: &Repository,
    owner: &Id,
) -> Option<(IncidentRef, bool)> {
    let id = incident["id"].as_str()?;
    let opened = incident["opened_at"].as_u64()?;
    let (source, subject) = match incident["check"].as_str()? {
        "watchdog" => (
            RecoverySource::LoopWatchdog,
            format!("watchdog-{}", incident["loop_id"].as_str()?),
        ),
        "loop" => (
            RecoverySource::ServiceHealth,
            format!("loop-{}", incident["loop"]["id"].as_str()?),
        ),
        "fleet_thread" => (
            RecoverySource::ServiceHealth,
            format!("fleet-thread-{}", incident["spec"].as_u64()?),
        ),
        check @ ("tick" | "server" | "cloudroom") => (RecoverySource::ServiceHealth, check.into()),
        _ => return None,
    };
    let escalated = incident["needs_you"].is_object() && incident["healthy_since"].is_null();
    Some((
        IncidentRef {
            repository: repository.clone(),
            owner: owner.clone(),
            source,
            subject: Id::new(subject)?,
            incident: Id::new(format!("{id}-{opened}"))?,
        },
        escalated,
    ))
}

/// The installed decisions read: the service's own loopback decisions route,
/// with the loopback Host it accepts. No body, query or credential is sent.
/// Every connect, write and read is bounded by the same absolute deadline.
pub fn loopback_decisions(port: u16) -> DecisionsRead {
    Arc::new(move |deadline: Instant| {
        let left = || {
            let left = deadline.saturating_duration_since(Instant::now());
            (!left.is_zero()).then_some(left).ok_or(Error::Unavailable)
        };
        let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
        let mut stream =
            TcpStream::connect_timeout(&addr, left()?).map_err(|_| Error::Unavailable)?;
        stream
            .set_write_timeout(Some(left()?))
            .map_err(|_| Error::Unavailable)?;
        write!(
            stream,
            "GET /api/v1/decisions HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        )
        .map_err(|_| Error::Unavailable)?;
        let mut raw = Vec::new();
        let mut chunk = [0u8; 64 * 1024];
        loop {
            // Recompute the absolute remainder before every read, so a
            // trickling reply cannot extend the pass past its budget.
            stream
                .set_read_timeout(Some(left()?))
                .map_err(|_| Error::Unavailable)?;
            match stream.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) if raw.len() + n <= MAX_RESPONSE => raw.extend_from_slice(&chunk[..n]),
                Ok(_) => return Err(Error::Unavailable),
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(_) => return Err(Error::Unavailable),
            }
        }
        left()?;
        let at = raw
            .windows(4)
            .position(|w| w == b"\r\n\r\n")
            .ok_or(Error::Unavailable)?;
        let head = std::str::from_utf8(&raw[..at]).map_err(|_| Error::Unavailable)?;
        let mut lines = head.split("\r\n");
        if !lines
            .next()
            .is_some_and(|status| status.starts_with("HTTP/1.1 200 "))
            || lines.any(|h| h.to_ascii_lowercase().starts_with("transfer-encoding:"))
        {
            return Err(Error::Unavailable);
        }
        openwiz_adapter_github::decisions::document(&raw[at + 4..]).ok_or(Error::Unavailable)
    })
}

/// The installed lifecycle read: the existing decisions comment scan, used
/// only when complete and error-free. Comments seen twice in one scan are
/// dropped, so an ambiguous record can never close a group.
pub fn installed_comments(config: &std::path::Path) -> CommentsRead {
    let github =
        openwiz_adapter_github::decisions::GitHubDecisions::from_path().with_settings(config);
    Arc::new(move |deadline| {
        let read = github.read(deadline);
        if !read.snapshot_complete || !read.errors.is_empty() {
            return Err(Error::Unavailable);
        }
        Ok(read
            .comments
            .into_iter()
            .filter(|c| !read.duplicate_ids.contains(&(c.repository.clone(), c.id)))
            .map(|c| CommentRecord {
                repository: c.repository,
                id: c.id,
                subject: c.subject,
                body: c.body,
            })
            .collect())
    })
}

const EVIDENCE_SCHEMA: &str = "openwiz.notification-recovery-evidence.v1";
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn unhex(text: &str) -> Option<Vec<u8>> {
    text.len()
        .is_multiple_of(2)
        .then(|| {
            (0..text.len())
                .step_by(2)
                .map(|i| u8::from_str_radix(text.get(i..i + 2)?, 16).ok())
                .collect()
        })
        .flatten()
}
/// Strictly read saved evidence. Anything unreadable, unsafe or off-shape is
/// no evidence: groups then stay open (absence never becomes recovery).
fn load_evidence(path: &std::path::Path) -> Vec<(Vec<u8>, Option<u64>, Option<Value>)> {
    use std::os::unix::fs::MetadataExt;
    let safe = std::fs::symlink_metadata(path).is_ok_and(|m| {
        m.is_file()
            && m.nlink() == 1
            && m.mode() & 0o077 == 0
            && openwiz_store::attachments::effective_uid().is_ok_and(|uid| uid == m.uid())
    });
    let Some(doc) = safe
        .then(|| std::fs::read(path).ok())
        .flatten()
        .and_then(|b| openwiz_adapter_github::decisions::document(&b))
    else {
        return vec![];
    };
    let exact = |v: &Value, keys: &[&str]| {
        v.as_object()
            .is_some_and(|o| o.len() == keys.len() && keys.iter().all(|k| o.contains_key(*k)))
    };
    if !exact(&doc, &["schema", "incidents"]) || doc["schema"] != EVIDENCE_SCHEMA {
        return vec![];
    }
    let rows = doc["incidents"].as_array().map(|rows| {
        rows.iter()
            .map(|r| {
                if !exact(r, &["key", "healthy_since", "watchdog_problem"]) {
                    return None;
                }
                let since = match &r["healthy_since"] {
                    Value::Null => None,
                    v => Some(v.as_u64()?),
                };
                let kind = match &r["watchdog_problem"] {
                    Value::Null => None,
                    v if v["state"] == "broken"
                        && matches!(
                            v["what"].as_str(),
                            Some("missed" | "stuck" | "disabled_by_failures")
                        ) =>
                    {
                        Some(v.clone())
                    }
                    _ => return None,
                };
                Some((unhex(r["key"].as_str()?)?, since, kind))
            })
            .collect::<Option<Vec<_>>>()
    });
    rows.flatten().unwrap_or_default()
}
/// Owner-only atomic replace, synced before and after the rename.
fn write_private(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let dir = path
        .parent()
        .ok_or_else(|| std::io::Error::other("no directory"))?;
    let temp = dir.join(format!(".recovery-evidence-{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        std::fs::rename(&temp, path)?;
        std::fs::File::open(dir)?.sync_all()
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    result
}
