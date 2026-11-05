//! #805's transport-independent intake: GitHub deliveries -> L4's router, once.
//!
//! Option A reads existing webhook deliveries through the service App.
//! Callers may also supply a [`DeliverySource`]. Payloads follow documented webhook
//! payloads, through launch-fleet's number table; no payload from this
//! project's webhook has been observed. A delivery is only a hint: the router
//! re-reads current facts, and its shared relay record keeps each send at one.
use super::{Event, EventError, EventKind, EventSource, Router, Routes, route_next};
use openwiz_core::fleet::model::Number;
use openwiz_core::fleet::starts::Repository;
use openwiz_core::messaging::sha256_hex;
use openwiz_core::ops::Clock;
use serde_json::Value;
use std::fs::{self, DirBuilder, File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

/// How long a delivery stays known. GitHub documents keeping deliveries for
/// three days; one seen again after this reaches the router, which repeats no
/// relay its shared record already holds.
pub const RETAIN_MS: i64 = 14 * 86_400_000;
/// GitHub's documented webhook payload cap.
const MAX_PAYLOAD: usize = 25 * 1024 * 1024;

/// One delivery as a transport received it: GitHub's delivery id, its event
/// name and its JSON body. Authenticating it is the transport's job.
#[derive(Clone, Debug)]
pub struct Delivery {
    pub id: String,
    pub event: String,
    pub payload: Vec<u8>,
}

pub trait DeliverySource {
    /// The next delivery, or None when drained; never waits.
    fn next(&mut self) -> Result<Option<Delivery>, EventError>;
}

/// The router's hint in a delivery, or None for anything else: another
/// repository, another event, a plain issue's comment, CI naming no pull
/// request, a malformed field or id. Nothing is guessed.
pub fn parse(repository: &Repository, delivery: &Delivery) -> Option<Event> {
    if !valid_id(&delivery.id) || delivery.payload.len() > MAX_PAYLOAD {
        return None;
    }
    let body: Value = serde_json::from_slice(&delivery.payload).ok()?;
    let named = Repository::parse(body["repository"]["full_name"].as_str()?).ok()?;
    if &named != repository {
        return None;
    }
    let number = |v: &Value| v.as_u64().and_then(Number::new);
    let list = |v: &Value| -> Option<Vec<Number>> {
        v.as_array()?.iter().map(|p| number(&p["number"])).collect()
    };
    let (kind, pull_requests) = match delivery.event.as_str() {
        "pull_request_review" => (
            EventKind::PullRequestReview,
            vec![number(&body["pull_request"]["number"])?],
        ),
        "issue_comment" if body["issue"]["pull_request"].is_object() => (
            EventKind::IssueComment,
            vec![number(&body["issue"]["number"])?],
        ),
        "check_suite" => (
            EventKind::CheckSuite,
            list(&body["check_suite"]["pull_requests"])?,
        ),
        "workflow_run" => (
            EventKind::WorkflowRun,
            list(&body["workflow_run"]["pull_requests"])?,
        ),
        _ => return None,
    };
    (!pull_requests.is_empty()).then(|| Event {
        repository: repository.clone(),
        event_id: delivery.id.clone(),
        kind,
        pull_requests,
    })
}

fn valid_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
}

/// L4's [`EventSource`] over a transport: each new delivery's event, once.
/// A delivery is recorded durably before the router sees it, so neither a
/// duplicate nor a restart hands it over again. A crash after the record
/// and before the route leaves that delivery to the fleet's check-in.
pub struct Intake<'a> {
    repository: Repository,
    seen: PathBuf,
    source: &'a mut dyn DeliverySource,
    clock: &'a dyn Clock,
}

impl<'a> Intake<'a> {
    /// Uses `<state root>/events/intake/`, owner-only, and forgets deliveries
    /// older than [`RETAIN_MS`]. Any unsafe or unreadable directory refuses.
    pub fn open(
        state_root: &Path,
        repository: Repository,
        source: &'a mut dyn DeliverySource,
        clock: &'a dyn Clock,
    ) -> Result<Self, EventError> {
        let unavailable = |_| EventError::SourceUnavailable;
        let owner = fs::symlink_metadata(state_root).map_err(unavailable)?;
        if !owner.is_dir() {
            return Err(EventError::SourceUnavailable);
        }
        let events = private_dir(state_root, "events", owner.uid())?;
        let seen = private_dir(&events, "intake", owner.uid())?;
        let now = clock.now().0;
        for entry in fs::read_dir(&seen).map_err(unavailable)? {
            let path = entry.map_err(unavailable)?.path();
            // Unknown or unreadable entries stay: keeping one only dedups.
            if recorded_at(&path).is_some_and(|at| now.saturating_sub(at) > RETAIN_MS) {
                let _ = fs::remove_file(&path);
            }
        }
        Ok(Self {
            repository,
            seen,
            source,
            clock,
        })
    }

    /// True for a delivery not seen before, once it is durably recorded.
    fn claim(&self, id: &str) -> Result<bool, EventError> {
        let path = delivery_record(&self.seen, &self.repository, id);
        let record = || -> std::io::Result<bool> {
            let mut file = match OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&path)
            {
                Ok(file) => file,
                Err(e) if e.kind() == ErrorKind::AlreadyExists => return Ok(false),
                Err(e) => return Err(e),
            };
            let saved = writeln!(file, "{}", self.clock.now().0)
                .and_then(|()| file.sync_all())
                .and_then(|()| File::open(&self.seen)?.sync_all());
            if saved.is_err() {
                // Best effort: no partial record outlives its failed claim.
                let _ = fs::remove_file(&path);
            }
            saved.map(|()| true)
        };
        record().map_err(|_| EventError::SourceUnavailable)
    }
}

impl EventSource for Intake<'_> {
    fn next(&mut self) -> Result<Option<Event>, EventError> {
        loop {
            let Some(delivery) = self.source.next()? else {
                return Ok(None);
            };
            if let Some(event) = parse(&self.repository, &delivery)
                && self.claim(&delivery.id)?
            {
                return Ok(Some(event));
            }
        }
    }
}

/// Hand every available event to the router. The first error stops the
/// drain and is returned: what is left waits for the fleet's check-in.
pub fn drain(router: &Router<'_>, source: &mut dyn EventSource) -> Result<Vec<Routes>, EventError> {
    let mut routes = Vec::new();
    while let Some(next) = route_next(router, source)? {
        routes.push(next);
    }
    Ok(routes)
}

/// Makes or checks `parent/name` (0700, owned by `uid`), then syncs `parent`
/// so the entry is durable. Also when it already existed: another process
/// may have made it without its sync landing yet.
fn private_dir(parent: &Path, name: &str, uid: u32) -> Result<PathBuf, EventError> {
    let path = parent.join(name);
    match DirBuilder::new().mode(0o700).create(&path) {
        Ok(()) => {}
        Err(e) if e.kind() == ErrorKind::AlreadyExists => {}
        Err(_) => return Err(EventError::SourceUnavailable),
    }
    let meta = fs::symlink_metadata(&path).map_err(|_| EventError::SourceUnavailable)?;
    if !(meta.is_dir() && meta.uid() == uid && meta.mode() & 0o077 == 0) {
        return Err(EventError::SourceUnavailable);
    }
    File::open(parent)
        .and_then(|dir| dir.sync_all())
        .map_err(|_| EventError::SourceUnavailable)?;
    Ok(path)
}

fn recorded_at(path: &Path) -> Option<i64> {
    let mut text = String::new();
    File::open(path)
        .ok()?
        .take(32)
        .read_to_string(&mut text)
        .ok()?;
    text.strip_suffix('\n')?.parse().ok()
}

/// The optional configured delivery job, independent of the fleet check-in.
pub const JOB: &str = "github-events";
pub type Route = dyn Fn(Event, std::time::Instant) -> Result<(), EventError> + Send + Sync;

/// The production registration and fixture registration share this composition.
/// Only command execution, the router boundary and time are supplied.
pub fn register_with(
    root: &Path,
    config: &Value,
    scheduler: &mut crate::scheduler::Scheduler,
    github: openwiz_adapter_github::process::Executor,
    route: std::sync::Arc<Route>,
    clock: std::sync::Arc<dyn Clock>,
) -> Result<bool, String> {
    let Some((repository, hook)) = configured(config)? else {
        return Ok(false);
    };
    let root = root.to_owned();
    let reads = openwiz_adapter_github::events::Deliveries::new(hook, github);
    scheduler
        .register(JOB, std::num::NonZeroU64::new(10).unwrap(), move || {
            let deadline = clock.monotonic() + openwiz_core::limits::RUN_BUDGET;
            let result = (|| -> Result<(), EventError> {
                let rows = reads.list(deadline).map_err(|_| EventError::SourceUnavailable)?;
                let mut source = Polling {
                    reads: &reads,
                    rows: rows.into_iter(),
                    deadline,
                    seen: root.join("events/intake"),
                    repository: &repository,
                };
                let mut intake = Intake::open(&root, repository.clone(), &mut source, clock.as_ref())?;
                while let Some(event) = intake.next()? {
                    if clock.monotonic() >= deadline {
                        return Err(EventError::SourceUnavailable);
                    }
                    route(event, deadline)?;
                }
                Ok(())
            })();
            if result.is_err() {
                eprintln!("openwiz-service: GitHub event intake unavailable; fleet check-in remains the safety net");
            }
        })
        .map_err(str::to_owned)?;
    Ok(true)
}

struct Polling<'a> {
    reads: &'a openwiz_adapter_github::events::Deliveries,
    rows: std::vec::IntoIter<openwiz_adapter_github::events::Summary>,
    deadline: std::time::Instant,
    seen: PathBuf,
    repository: &'a Repository,
}
impl DeliverySource for Polling<'_> {
    fn next(&mut self) -> Result<Option<Delivery>, EventError> {
        for row in self.rows.by_ref() {
            if !matches!(
                row.event.as_str(),
                "pull_request_review" | "workflow_run" | "check_suite" | "issue_comment"
            ) {
                continue;
            }
            // Intake::open has already checked the private directory. A known
            // GUID needs no payload read, also across redeliveries/restarts.
            match fs::symlink_metadata(delivery_record(&self.seen, self.repository, &row.guid)) {
                Ok(_) => continue,
                Err(e) if e.kind() == ErrorKind::NotFound => {}
                Err(_) => return Err(EventError::SourceUnavailable),
            }
            let delivery = self
                .reads
                .detail(&row, self.deadline)
                .map_err(|_| EventError::SourceUnavailable)?;
            return Ok(Some(Delivery {
                id: delivery.summary.guid,
                event: delivery.summary.event,
                payload: delivery.payload,
            }));
        }
        Ok(None)
    }
}

fn delivery_record(seen: &Path, repository: &Repository, id: &str) -> PathBuf {
    seen.join(sha256_hex(
        format!("openwiz.event-intake.v1\n{}\n{id}", repository.as_str()).as_bytes(),
    ))
}

/// Register the configured production App-backed intake; absent config is off.
/// The cached App client is opened lazily, so missing credentials affect only
/// this scheduled pass. There is no personal-login executor or fallback.
pub fn register(
    root: &Path,
    config: &Value,
    scheduler: &mut crate::scheduler::Scheduler,
) -> Result<bool, String> {
    use openwiz_adapter_github::process::Executor;
    use std::sync::{Arc, Mutex};
    if configured(config)?.is_none() {
        return Ok(false);
    }
    let app_root = root.to_owned();
    let app_config = config.to_string();
    let client = Mutex::new(None::<crate::app::Client>);
    let github = Executor::supplied(Arc::new(move |call, deadline| {
        let unavailable = || openwiz_core::source::SourceError::Unavailable {
            detail: "event intake App request failed (details withheld)".into(),
        };
        let app = {
            let mut client = client.lock().map_err(|_| unavailable())?;
            if client.is_none() {
                *client = Some(
                    crate::app::Client::from_config_for_events(&app_root, &app_config)
                        .map_err(|_| unavailable())?,
                );
            }
            client.as_ref().unwrap().clone()
        };
        app.execute(call, deadline).map_err(|_| unavailable())
    }));
    register_with_sources(
        root,
        config,
        scheduler,
        crate::tick::Sources {
            github,
            room: openwiz_adapter_cloudroom::source::CloudRoomSource::from_path(),
        },
        Arc::new(openwiz_cli::SystemClock),
    )
}

/// The production facts/router composition, with explicit command sources.
/// Fixtures replace executors, never the current-world reader or relay rules.
pub fn register_with_sources(
    root: &Path,
    config: &Value,
    scheduler: &mut crate::scheduler::Scheduler,
    sources: crate::tick::Sources,
    clock: std::sync::Arc<dyn Clock>,
) -> Result<bool, String> {
    use openwiz_adapter_github::tick::TickReads;
    use openwiz_cli::fleet::tick::{Inventory, World};
    let Some((repository, _)) = configured(config)? else {
        return Ok(false);
    };
    let project = config["project"]
        .as_str()
        .ok_or("events project is invalid")?
        .to_owned();
    let state_root = root.to_owned();
    let github = sources.github.clone();
    let facts_clock = std::sync::Arc::clone(&clock);
    let route = std::sync::Arc::new(move |event: Event, deadline| {
        let unavailable = |_| EventError::SourceUnavailable;
        let gh = TickReads::with_executor(github.clone());
        let inventory = Inventory::read(&gh, deadline).map_err(unavailable)?;
        let world = World::read(&gh, Some(&sources.room), &state_root, deadline, inventory)
            .map_err(unavailable)?;
        let observed =
            Repository::parse(&world.repository.name).map_err(|_| EventError::SourceUnavailable)?;
        if observed != repository
            || world.project.as_deref() != Some(project.as_str())
            || facts_clock.monotonic() >= deadline
        {
            return Err(EventError::SourceUnavailable);
        }
        let facts = CurrentFacts {
            repository: observed,
            snapshot: world.snapshot,
        };
        let store =
            super::RelayStore::open(&state_root).map_err(|_| EventError::SourceUnavailable)?;
        let router = Router {
            repository: &repository,
            rules: &world.rules,
            facts: &facts,
            messenger: &sources.room,
            sends: store.records(),
            clock: facts_clock.as_ref(),
        };
        route_next(&router, &mut OneEvent(Some(event))).map(|_| ())
    });
    register_with(root, config, scheduler, sources.github, route, clock)
}

fn configured(config: &Value) -> Result<Option<(Repository, std::num::NonZeroU64)>, String> {
    let config = crate::document::read(crate::document::Document::Config, &config.to_string())?;
    let Some(events) = config.get("events") else {
        return Ok(None);
    };
    let hook = events["hook_id"]
        .as_u64()
        .and_then(std::num::NonZeroU64::new)
        .ok_or("events.hook_id is invalid")?;
    let repository = Repository::parse(&format!(
        "{}/{}",
        config["repository"]["owner"].as_str().unwrap(),
        config["repository"]["name"].as_str().unwrap()
    ))
    .map_err(|_| "events repository is invalid")?;
    Ok(Some((repository, hook)))
}

/// A fresh World is assembled after each hint, immediately before routing.
/// Its immutable observations serve every PR named by that single event.
struct CurrentFacts {
    repository: Repository,
    snapshot: openwiz_core::fleet::tick::Snapshot,
}
impl super::FleetReader for CurrentFacts {
    fn read_current(
        &self,
        repository: &Repository,
        _: Number,
    ) -> Result<super::Current, super::ReadError> {
        if repository != &self.repository {
            return Err(super::ReadError);
        }
        Ok(super::Current {
            repository: self.repository.clone(),
            snapshot: self.snapshot.clone(),
        })
    }
}
struct OneEvent(Option<Event>);
impl EventSource for OneEvent {
    fn next(&mut self) -> Result<Option<Event>, EventError> {
        Ok(self.0.take())
    }
}
