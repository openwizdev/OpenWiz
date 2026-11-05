//! Fleet reads (#127): the CLI operations, plus #129's optional verified
//! server-configured orchestrator target for the existing web composer.
//! The HTTP layer supplies the shared read-run slot, deadline and headers.

use std::sync::Arc;
use std::time::Instant;

use openwiz_adapter_cloudroom::{fleet as cloudroom, source::CloudRoomSource};
use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::agents;

use openwiz_core::fleet::fleets::{FleetsSource, fleets};
use openwiz_core::fleet::model::{Failed, ListOutcome as AgentList, NonEmpty, Number, Read};
use openwiz_core::fleet::tickets::{
    self, AgentReads, Agents, FleetRequest, GitHub, Placed, RepositoryAnswer, TestedVersions,
};
use openwiz_core::limits::RUN_BUDGET;
use openwiz_core::messaging::send::Messenger;
use openwiz_core::model::SessionId;
use openwiz_core::ops::Clock;
use serde::Serialize;

use crate::api;
use crate::http::Reply;

pub(crate) const LIST: &str = "/api/v1/fleets";
pub(crate) const DETAIL: &str = "/api/v1/fleets/{spec}";

/// Sources for the two fleet reads. Configured by the program, never by a
/// request. Each source uses the repository of the server's working directory.
#[derive(Clone)]
pub struct Fleets {
    pub list: Arc<dyn FleetsSource + Send>,
    pub detail: Arc<dyn GitHub>,
    pub agents: Arc<dyn Agents>,
}

impl std::fmt::Debug for Fleets {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Fleets")
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Call {
    List,
    Detail(Number),
}

/// No query, no decoding. Match the CLI's plain 1–10 digit issue number.
pub(crate) fn call(spec: Option<&str>, query: Option<&str>) -> Result<Call, &'static str> {
    if query.is_some() {
        return Err("this route takes no query");
    }
    match spec {
        None => Ok(Call::List),
        Some(text) => {
            let plain = !text.is_empty()
                && text.len() <= 10
                && !text.starts_with('0')
                && text.bytes().all(|b| b.is_ascii_digit());
            plain
                .then(|| text.parse().ok())
                .flatten()
                .map(Call::Detail)
                .ok_or("fleet: <spec> must be an issue number: 1 to 10 digits, no leading zero")
        }
    }
}

/// Run the same core operation, with the same budget and agent policy, as
/// the corresponding CLI command. Partial envelopes are successful reads.
pub(crate) fn run(
    config: Option<&Fleets>,
    messenger: Option<&dyn Messenger>,
    clock: &dyn Clock,
    call: &Call,
    configured_target: Option<&Result<Option<String>, ()>>,
) -> Reply {
    let Some(config) = config else {
        return api::error(404, "no_route", "no such route");
    };
    let deadline = clock.monotonic() + RUN_BUDGET;
    let envelope = match call {
        Call::List => fleets(config.list.as_ref(), clock, RUN_BUDGET),
        Call::Detail(spec) => {
            let envelope = tickets::fleet(
                FleetRequest { spec: *spec },
                config.detail.as_ref(),
                config.agents.as_ref(),
                TestedVersions {
                    github: openwiz_adapter_github::tickets::TESTED_VERSION,
                    cloudroom: openwiz_adapter_cloudroom::TESTED_VERSION,
                },
                clock,
                RUN_BUDGET,
            );
            if let Some(why) = tickets::fleet_unreadable(&envelope) {
                let gap = serde_json::to_value(why.gap).expect("a gap serializes");
                return api::error(
                    502,
                    "read_failed",
                    &format!(
                        "fleet: #{spec}'s tickets couldn't be read ({}): {}",
                        gap.as_str().expect("a gap is a string"),
                        clean(why.reason.as_str()),
                    ),
                );
            }
            envelope
        }
    };
    // Configuration is never taken from a request or guessed from a title.
    // The shared target reader checks the exact ID and uses the remaining
    // run budget. An unconfirmed target is omitted; fleet facts stay intact.
    let orchestrator = configured_target
        .cloned()
        .unwrap_or_else(|| {
            std::env::var("OPENWIZ_ORCHESTRATOR_THREAD_ID")
                .map(Some)
                .or_else(|e| {
                    if e == std::env::VarError::NotPresent {
                        Ok(None)
                    } else {
                        Err(())
                    }
                })
        })
        .ok()
        .flatten()
        .filter(|id| {
            let target = SessionId(id.clone());
            messenger.is_some_and(|source| {
                source.check_target_id(&target).is_ok()
                    && source
                        .read_target(&target, deadline)
                        .is_ok_and(|read| read.id == target)
            })
        });
    #[derive(Serialize)]
    struct WithTarget<T> {
        #[serde(flatten)]
        envelope: T,
        #[serde(skip_serializing_if = "Option::is_none")]
        orchestrator: Option<String>,
    }
    api::pretty(&WithTarget {
        envelope,
        orchestrator,
    })
    .map_or_else(
        || api::error(500, "internal", "the result could not be written"),
        api::ok,
    )
}

/// The CLI's one-line error rendering: control and invisible format
/// characters cannot drive a terminal or reorder the displayed reason.
fn clean(text: &str) -> String {
    text.chars()
        .map(|c| {
            let unsafe_ = c.is_control()
                || matches!(c,
            '\u{00AD}' | '\u{061C}' | '\u{180E}' | '\u{200B}'..='\u{200F}'
            | '\u{2028}'..='\u{202E}' | '\u{2060}'..='\u{206F}'
            | '\u{FEFF}' | '\u{FFF9}'..='\u{FFFB}');
            if unsafe_ {
                if c.len_utf8() >= '\u{FFFD}'.len_utf8() {
                    '\u{FFFD}'
                } else {
                    '?'
                }
            } else {
                c
            }
        })
        .collect()
}

/// Connect CloudRoom's existing fleet reads and the core's placement, as
/// the CLI does. Both share the same request budget and verified chain.
pub struct FleetAgents(pub CloudRoomSource);

impl Agents for FleetAgents {
    fn read(&self, repository: Option<&RepositoryAnswer>, deadline: Instant) -> AgentReads {
        let repository =
            repository.and_then(|r| cloudroom::Repository::parse(r.name_with_owner.as_str()));
        let Some(repository) = repository else {
            // The version is independent; selecting projects requires this
            // repository's verified identity. Never guess from its name alone.
            let version = cloudroom::version(&self.0, deadline);
            let projects = AgentList::Failed(Failed {
                gap: GapKind::BudgetExhausted,
                reason: NonEmpty::new("not read: the repository couldn't be read or identified")
                    .expect("the reason is not empty"),
            });
            return AgentReads {
                version,
                threads: cloudroom::threads(&self.0, &projects, deadline),
                projects,
                workspaces: Vec::new(),
            };
        };
        let reads = cloudroom::read(&self.0, &repository, deadline);
        AgentReads {
            version: reads.version,
            projects: reads.projects,
            threads: reads.threads,
            workspaces: reads.workspaces,
        }
    }

    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed {
        let placements = agents::place(spec, reads)
            .expect("the fleet operation records every placement read exactly once");
        Placed {
            builders: tickets.iter().map(|&t| placements.builder(t)).collect(),
            unplaced: placements.unplaced(),
        }
    }
}

// Stock joins reuse the cockpit's actual bounded enumerations and merge reads.
// These facts stay internal; the existing public fleet envelope is unchanged.
use openwiz_core::fleet::fleets::{IssueRow, Listed, PrRow, StockPr};
use openwiz_core::fleet::model::{Check, MergedPr, Repository};
use std::collections::BTreeMap;
use std::sync::Mutex;

type Captured<T> = Option<(i64, Result<T, Failed>)>;
pub(crate) struct StockReads<'a> {
    inner: &'a (dyn FleetsSource + Send),
    clock: &'a dyn Clock,
    repository: Mutex<Captured<Repository>>,
    issues: Mutex<Captured<Listed<IssueRow>>>,
    prs: Mutex<Captured<Listed<StockPr>>>,
    merges: Mutex<BTreeMap<(String, String), Result<bool, Failed>>>,
}
impl<'a> StockReads<'a> {
    pub(crate) fn new(inner: &'a (dyn FleetsSource + Send), clock: &'a dyn Clock) -> Self {
        Self {
            inner,
            clock,
            repository: Mutex::new(None),
            issues: Mutex::new(None),
            prs: Mutex::new(None),
            merges: Mutex::new(BTreeMap::new()),
        }
    }
    pub(crate) fn repository_read(&self) -> Captured<Repository> {
        self.repository
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .clone()
    }
    pub(crate) fn captured(&self) -> (Captured<Listed<IssueRow>>, Captured<Listed<StockPr>>) {
        (
            self.issues
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .clone(),
            self.prs.lock().unwrap_or_else(|p| p.into_inner()).clone(),
        )
    }
}
fn captured<T: Clone>(
    slot: &Mutex<Captured<T>>,
    clock: &dyn Clock,
    read: impl FnOnce() -> Result<T, Failed>,
) -> Result<T, Failed> {
    slot.lock()
        .unwrap_or_else(|p| p.into_inner())
        .get_or_insert_with(|| (clock.now().0, read()))
        .1
        .clone()
}
fn merge_key(p: &MergedPr) -> (String, String) {
    (
        p.merge_commit.as_str().to_owned(),
        p.fields.base_branch.as_str().to_owned(),
    )
}
impl FleetsSource for StockReads<'_> {
    fn tested_version(&self) -> &str {
        self.inner.tested_version()
    }
    fn version(&self, d: Instant) -> Result<NonEmpty, Failed> {
        self.inner.version(d)
    }
    fn repository(&self, d: Instant) -> Result<Repository, Failed> {
        captured(&self.repository, self.clock, || self.inner.repository(d))
    }
    fn issues(&self, d: Instant) -> Result<Listed<IssueRow>, Failed> {
        captured(&self.issues, self.clock, || self.inner.issues(d))
    }
    fn pull_requests(&self, d: Instant) -> Result<Listed<PrRow>, Failed> {
        self.stock_pull_requests(d).map(|p| Listed {
            rows: p.rows.into_iter().map(|p| p.pr).collect(),
            cut_short: p.cut_short,
        })
    }
    fn stock_pull_requests(&self, d: Instant) -> Result<Listed<StockPr>, Failed> {
        captured(&self.prs, self.clock, || self.inner.stock_pull_requests(d))
    }
    fn checks(&self, n: Number, d: Instant) -> Result<Vec<Check>, Failed> {
        self.inner.checks(n, d)
    }
    fn comments(&self, n: Number, d: Instant) -> Result<Vec<String>, Failed> {
        self.inner.comments(n, d)
    }
    fn on_base(&self, p: &MergedPr, d: Instant) -> Result<bool, Failed> {
        self.on_bases(std::slice::from_ref(p), d).remove(0)
    }
    fn on_bases(&self, prs: &[MergedPr], d: Instant) -> Vec<Result<bool, Failed>> {
        let mut keys = std::collections::BTreeSet::new();
        let missing: Vec<_> = {
            let cached = self.merges.lock().unwrap_or_else(|p| p.into_inner());
            prs.iter()
                .filter(|p| {
                    let k = merge_key(p);
                    !cached.contains_key(&k) && keys.insert(k)
                })
                .cloned()
                .collect()
        };
        if !missing.is_empty() {
            let results = self.inner.on_bases(&missing, d);
            let mut cache = self.merges.lock().unwrap_or_else(|p| p.into_inner());
            for (i, p) in missing.iter().enumerate() {
                cache.insert(
                    merge_key(p),
                    if results.len() == missing.len() {
                        results[i].clone()
                    } else {
                        Err(Failed {
                            gap: GapKind::Malformed,
                            reason: NonEmpty::new("Merge evidence batch is incomplete").unwrap(),
                        })
                    },
                );
            }
        }
        let cache = self.merges.lock().unwrap_or_else(|p| p.into_inner());
        prs.iter().map(|p| cache[&merge_key(p)].clone()).collect()
    }
}
