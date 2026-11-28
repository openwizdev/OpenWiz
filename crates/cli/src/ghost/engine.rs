use std::collections::HashMap;
use std::time::Instant;

use serde_json::Value;

use super::context::ContextStore;
use super::pairing::PairingStore;
use super::protocol::{
    BenchRequest, CompleteRequest, CompleteResponse, ContextPack, ContextRequest, ContextResponse,
    DraftRequest, Event, FeedbackResponse, HealthRequest, HealthResponse, Outcome, PairRequest,
    PairResponse, RefusalCode, RefusalEnvelope, SCHEMA_ID, Suggestion, Surface, Tier, TiersStatus,
    TurnsRequest, TurnsResponse, validate_bench_request, validate_complete_request,
    validate_context_request, validate_draft_request, validate_event, validate_pair_request,
    validate_turns_request,
};
use super::recall::CONFIDENCE_THRESHOLD;

#[derive(Clone, Debug, Default)]
pub struct FeedbackCounters {
    pub total: u64,
    pub chars_accepted: u64,
    pub by_outcome: HashMap<Outcome, u64>,
    pub by_tier: HashMap<Tier, u64>,
    pub by_surface: HashMap<Surface, u64>,
}

impl FeedbackCounters {
    pub fn record(&mut self, event: &Event) {
        self.total += 1;
        self.chars_accepted = self.chars_accepted.saturating_add(event.chars_accepted);
        *self.by_outcome.entry(event.outcome).or_insert(0) += 1;
        *self.by_tier.entry(event.tier).or_insert(0) += 1;
        *self.by_surface.entry(event.surface).or_insert(0) += 1;
    }

    pub fn outcome_count(&self, outcome: Outcome) -> u64 {
        self.by_outcome.get(&outcome).copied().unwrap_or(0)
    }
}

pub struct GhostEngine {
    context: ContextStore,
    pairing: PairingStore,
    counters: FeedbackCounters,
    session_seqs: HashMap<String, u64>,
    next_suggestion_id: u64,
    confidence_threshold: f64,
}

impl GhostEngine {
    pub fn new(context: ContextStore, pairing: PairingStore) -> Self {
        Self {
            context,
            pairing,
            counters: FeedbackCounters::default(),
            session_seqs: HashMap::new(),
            next_suggestion_id: 1,
            confidence_threshold: CONFIDENCE_THRESHOLD,
        }
    }

    pub fn with_context_pack(pack: ContextPack, pairing: PairingStore) -> Self {
        Self::new(ContextStore::from_pack(pack), pairing)
    }

    pub fn system_default() -> Self {
        let pairing = PairingStore::default_file_path()
            .and_then(|p| PairingStore::from_file(p).ok())
            .unwrap_or_else(PairingStore::in_memory);
        Self::new(ContextStore::system_default(), pairing)
    }

    pub fn pairing_mut(&mut self) -> &mut PairingStore {
        &mut self.pairing
    }

    pub fn context(&self) -> &ContextStore {
        &self.context
    }

    pub fn context_mut(&mut self) -> &mut ContextStore {
        &mut self.context
    }

    pub fn counters(&self) -> &FeedbackCounters {
        &self.counters
    }

    pub fn dispatch(&mut self, route: &str, body: Value, is_http: bool) -> (u16, Value) {
        match route {
            "pair" => {
                if !is_http {
                    return RefusalEnvelope::new(
                        RefusalCode::UnknownRoute,
                        "pair is HTTP-only and not available over stdio.",
                    )
                    .into_response();
                }
                self.handle_pair(body)
            }
            "health" => self.handle_health(body),
            "context" => self.handle_context(body),
            "turns" => self.handle_turns(body),
            "complete" => self.handle_complete(body),
            "draft" => self.handle_draft(body),
            "feedback" => self.handle_feedback(body),
            "bench" => self.handle_bench(body, is_http),
            _ => RefusalEnvelope::new(
                RefusalCode::UnknownRoute,
                format!("unknown ghost.v1 route {route:?}."),
            )
            .into_response(),
        }
    }

    fn handle_pair(&mut self, body: Value) -> (u16, Value) {
        let req: PairRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid pair request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_pair_request(&req) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }
        match self.pairing.exchange_code(&req.code, req.surface) {
            Ok(Some(token)) => ok_json(&PairResponse {
                schema: SCHEMA_ID.to_owned(),
                token,
                surface: req.surface,
            }),
            Ok(None) => RefusalEnvelope::new(
                RefusalCode::InvalidPairingCode,
                "pairing code is unknown, expired, or already used.",
            )
            .into_response(),
            Err(e) => RefusalEnvelope::new(
                RefusalCode::Unavailable,
                format!("pairing store error: {e}"),
            )
            .into_response(),
        }
    }

    fn handle_health(&self, body: Value) -> (u16, Value) {
        if let Err(e) = serde_json::from_value::<HealthRequest>(body) {
            return RefusalEnvelope::new(
                RefusalCode::InvalidRequest,
                format!("invalid health request: {e}"),
            )
            .into_response();
        }
        ok_json(&HealthResponse {
            schema: SCHEMA_ID.to_owned(),
            status: "ok".to_owned(),
            version: env!("CARGO_PKG_VERSION").to_owned(),
            tiers: TiersStatus {
                recall: true,
                small_model: false,
                draft: false,
            },
            logging_enabled: false,
            context_revision: self.context.revision().to_owned(),
        })
    }

    fn handle_context(&self, body: Value) -> (u16, Value) {
        let req: ContextRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid context request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_context_request(&req) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }
        let current = self.context.revision().to_owned();
        if req.if_revision.as_deref() == Some(current.as_str()) {
            return ok_json(&ContextResponse {
                schema: SCHEMA_ID.to_owned(),
                revision: current,
                unchanged: true,
                pack: None,
            });
        }
        ok_json(&ContextResponse {
            schema: SCHEMA_ID.to_owned(),
            revision: current,
            unchanged: false,
            pack: Some(self.context.pack().clone()),
        })
    }

    fn handle_turns(&mut self, body: Value) -> (u16, Value) {
        let req: TurnsRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid turns request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_turns_request(&req) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }
        let revision = self
            .context
            .update_turns(req.session_id, req.agent, req.turns)
            .to_owned();

        ok_json(&TurnsResponse {
            schema: SCHEMA_ID.to_owned(),
            revision,
            draft_queued: false,
        })
    }

    fn handle_complete(&mut self, body: Value) -> (u16, Value) {
        let req: CompleteRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid complete request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_complete_request(&req) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }

        if let Some(&last_seq) = self.session_seqs.get(&req.session_id)
            && req.seq < last_seq
        {
            return ok_json(&CompleteResponse {
                schema: SCHEMA_ID.to_owned(),
                seq: req.seq,
                suggestion: None,
            });
        }
        self.session_seqs.insert(req.session_id.clone(), req.seq);

        let started = Instant::now();
        let recall_match = self
            .context
            .recall()
            .complete(&req.prefix, self.confidence_threshold);
        let latency_ms = started.elapsed().as_secs_f64() * 1000.0;

        let suggestion = recall_match.map(|m| {
            let id = format!("sug_{:04}", self.next_suggestion_id);
            self.next_suggestion_id += 1;
            Suggestion {
                id,
                text: m.text,
                full_text: m.full_text,
                tier: Tier::Recall,
                confidence: m.confidence,
                latency_ms,
            }
        });

        ok_json(&CompleteResponse {
            schema: SCHEMA_ID.to_owned(),
            seq: req.seq,
            suggestion,
        })
    }

    fn handle_draft(&self, body: Value) -> (u16, Value) {
        let req: DraftRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid draft request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_draft_request(&req) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }

        RefusalEnvelope::new(
            RefusalCode::NotImplemented,
            "draft tier is not built yet (see #3153).",
        )
        .into_response()
    }

    fn handle_feedback(&mut self, body: Value) -> (u16, Value) {
        let event: Event = match serde_json::from_value(body) {
            Ok(e) => e,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid feedback event: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_event(&event) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }
        self.counters.record(&event);

        ok_json(&FeedbackResponse {
            schema: SCHEMA_ID.to_owned(),
            recorded: true,
            logged: false,
        })
    }

    fn handle_bench(&self, body: Value, is_http: bool) -> (u16, Value) {
        let req: BenchRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => {
                return RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    format!("invalid bench request: {e}"),
                )
                .into_response();
            }
        };
        if let Err(why) = validate_bench_request(&req, is_http) {
            return RefusalEnvelope::new(RefusalCode::InvalidRequest, why).into_response();
        }

        RefusalEnvelope::new(
            RefusalCode::NotImplemented,
            "bench is not built yet (see #3152).",
        )
        .into_response()
    }
}

fn ok_json<T: serde::Serialize>(value: &T) -> (u16, Value) {
    (
        200,
        serde_json::to_value(value).expect("response serializes"),
    )
}
