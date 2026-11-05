//! The installed notification delivery adapter and its factory (#2035).
//!
//! **Named assumption, swap it here only** (Jake, 2026-11-13, revision 9's
//! build-ahead decision): delivery will be standard Web Push through the
//! installed app's service worker, behind `DeliveryBoundary`. T2 #2033's
//! observed binding has not landed, so this adapter positively reports
//! `unsupported`, verifies no binding and makes no I/O. Deferred until T2 plus
//! a contract and dependency decision: VAPID key distribution, the browser
//! endpoint/key route, RFC 8291 payload encryption, VAPID signing and the
//! HTTPS send. No new dependency, external program or hand-written crypto.
use super::engine::{BindingVerifier, Engine, UnavailableSources};
use openwiz_core::notifications::{
    boundary::DeliveryBoundary,
    model::{
        Capability, CapabilityState, DeliveryOutcome, OutcomeState, Permission, Submission, Text,
    },
};
use std::{path::Path, sync::Arc};

pub const ASSUMPTION: &str =
    "Standard Web Push through the installed service worker; unverified until T2 #2033";

/// Web Push under the named assumption. No transport is implemented yet.
pub struct WebPushDelivery;
impl DeliveryBoundary for WebPushDelivery {
    fn capability(&self) -> Capability {
        Capability {
            state: CapabilityState::Unsupported,
            permission: Permission::Unknown,
            reason: Text::new("Web Push delivery is not observed or implemented yet").unwrap(),
            next: Text::new("Phone delivery waits for the observed delivery binding").unwrap(),
        }
    }
    fn submit(&mut self, _request: &Submission) -> DeliveryOutcome {
        DeliveryOutcome {
            state: OutcomeState::Failed,
            reason: Text::new("No delivery attempted: Web Push transport is unsupported").unwrap(),
        }
    }
}

/// The one installed delivery factory: the adapter and its binding verifier.
/// The runtime job and the web API both take theirs from here.
pub fn installed() -> (Box<dyn DeliveryBoundary + Send>, BindingVerifier) {
    (Box::new(WebPushDelivery), Arc::new(|_, _| false))
}

/// The web API's engine: the job's protected store, this factory's adapter and
/// verifier, and no source reads (the API never runs a pass).
pub fn api_engine(root: &Path, clock: Arc<dyn openwiz_core::ops::Clock>) -> Engine {
    let (delivery, binding) = installed();
    Engine::new(
        openwiz_store::notifications::Store::new(root),
        Arc::new(UnavailableSources),
        delivery,
        clock,
        binding,
    )
}
