//! Bound notification reads; mapping storage remains the installed engine's.
use openwiz_core::notifications::model::Reference;
use std::{sync::Arc, time::Instant};

/// Access refusal precedes source detail. No request can supply owner identity.
#[derive(Clone, Copy, Debug)]
pub enum TargetReadError {
    SignedOut,
    Denied,
    Unavailable,
}

/// Trusted protected-state reader, supplied by the existing installation.
/// This is no storage format and performs no save, registration or dispatch.
pub type ReadTargetMapping =
    Arc<dyn Fn(&str, Instant) -> Result<Option<Reference>, TargetReadError> + Send + Sync>;

#[derive(Clone)]
pub struct NotificationTargets {
    pub read_mapping: ReadTargetMapping,
}
impl std::fmt::Debug for NotificationTargets {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("NotificationTargets")
    }
}

use crate::{api, decisions::Decisions, http::Reply};
use openwiz_core::{limits::RUN_BUDGET, notifications::model::*, ops::Clock};

pub(crate) const PREFIX: &str = "/api/v1/notifications/targets/";
pub(crate) const ROUTE: &str = "/api/v1/notifications/targets/{token}";
pub(crate) const LOG_ROUTE: &str = "/api/v1/notifications/targets/*";

pub(crate) fn valid_token(token: &str) -> bool {
    token.len() == 64
        && token
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// Resolve the protected mapping before any core-run slot is taken (#2039 R1):
/// a wait for the engine's store never holds a slot that the engine's own
/// decisions recheck needs. An exhausted deadline is 504, never a missing item
/// (R2). Returns the bound reference as its canonical JSON, the core run's key.
pub(crate) fn resolve(
    targets: Option<&NotificationTargets>,
    token: &str,
    clock: &dyn Clock,
) -> Result<String, Reply> {
    let missing = || api::error(404, "no_route", "notification reference is unavailable");
    let Some(targets) = targets else {
        return Err(missing());
    };
    let deadline = clock.monotonic() + RUN_BUDGET;
    let read = (targets.read_mapping)(token, deadline);
    if clock.monotonic() >= deadline {
        return Err(api::error(
            504,
            "timed_out",
            "notification source deadline elapsed",
        ));
    }
    match read {
        Ok(Some(reference)) => serde_json::to_string(&reference)
            .map_err(|_| api::error(500, "internal", "the reference could not be read")),
        Ok(None) | Err(TargetReadError::Unavailable) => Err(missing()),
        Err(TargetReadError::SignedOut) => {
            Err(api::error(401, "signed_out", "owner access is required"))
        }
        Err(TargetReadError::Denied) => {
            Err(api::error(403, "access_denied", "owner access was refused"))
        }
    }
}

/// The core run for a resolved reference: the existing decisions lookup only.
pub(crate) fn run(decisions: Option<&Decisions>, reference: &str, clock: &dyn Clock) -> Reply {
    let Ok(reference) = serde_json::from_str::<Reference>(reference) else {
        return api::error(500, "internal", "the reference could not be read");
    };
    let deadline = clock.monotonic() + RUN_BUDGET;
    if clock.monotonic() >= deadline {
        return api::error(504, "timed_out", "notification source deadline elapsed");
    }
    let (state, snapshot, source) = match &reference {
        Reference::Decision(binding) => {
            let found = decisions.map(|d| d.lookup_before(binding, clock, deadline));
            (
                found.as_ref().map_or(TargetState::Unread, |f| f.state),
                found.and_then(|f| f.snapshot_at),
                SourceOwner::Decisions,
            )
        }
        // Durable incident-owner verification is a separate source gate. A
        // reference cannot manufacture a healthy, recovered or escalated state.
        Reference::Incident(binding) => (
            TargetState::Unread,
            None,
            match binding.source {
                RecoverySource::ServiceHealth => SourceOwner::ServiceHealth,
                RecoverySource::LoopWatchdog => SourceOwner::LoopWatchdog,
            },
        ),
        Reference::Event(binding) => (TargetState::Unread, None, binding.source),
    };
    let unavailable = || {
        Text::new("Exact source or independent currentness verification is unavailable")
            .expect("nonempty reason")
    };
    let (coverage, freshness) = if let Some(at) = snapshot {
        let now = u64::try_from(clock.now().0).ok();
        if !now.is_some_and(|now| at <= now && now - at <= 70_000) {
            return write(TargetResult {
                reference,
                state: TargetState::Unread,
                coverage: Coverage {
                    state: CoverageState::Partial,
                    gaps: vec![Gap {
                        source,
                        reason: unavailable(),
                    }],
                },
                freshness: if now.is_some_and(|now| at <= now) {
                    Freshness {
                        state: FreshnessState::Stale,
                        snapshot_at: Fact::Known(at),
                    }
                } else {
                    Freshness {
                        state: FreshnessState::Unknown,
                        snapshot_at: Fact::Unknown(unavailable()),
                    }
                },
            });
        }
        (
            Coverage {
                state: CoverageState::Complete,
                gaps: vec![],
            },
            Freshness {
                state: FreshnessState::Fresh,
                snapshot_at: Fact::Known(at),
            },
        )
    } else {
        (
            Coverage {
                state: CoverageState::Partial,
                gaps: vec![Gap {
                    source,
                    reason: unavailable(),
                }],
            },
            Freshness {
                state: FreshnessState::Unknown,
                snapshot_at: Fact::Unknown(unavailable()),
            },
        )
    };
    write(TargetResult {
        reference,
        state,
        coverage,
        freshness,
    })
}

/// Coverage and freshness are paired by construction above; the target
/// proofs check every state with the core's document consistency rules.
fn write(result: TargetResult) -> Reply {
    let document = Document {
        schema: SchemaId::V1,
        record: Record::TargetResult(result),
    };
    api::pretty(&document).map_or_else(
        || api::error(500, "internal", "the result could not be written"),
        api::ok,
    )
}
