//! Guarded local notification settings/status. No delivery or work route.
use crate::{
    SendHost, Shared, api,
    http::{Head, Reply},
    send,
};
use openwiz_core::notifications::model::*;
use openwiz_store::notifications::Error;
use std::{
    net::TcpStream,
    sync::{Arc, mpsc},
    time::Instant,
};

pub const STATUS: &str = "/api/v1/notifications/status";
pub const PREFERENCES: &str = "/api/v1/notifications/preferences";
pub const SUBSCRIPTION: &str = "/api/v1/notifications/subscription";
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Read {
    Status,
    Preferences,
    Subscription,
}
impl Read {
    pub fn path(self) -> &'static str {
        match self {
            Self::Status => STATUS,
            Self::Preferences => PREFERENCES,
            Self::Subscription => SUBSCRIPTION,
        }
    }
    fn allow(self) -> &'static str {
        match self {
            Self::Status => "GET",
            Self::Preferences => "GET, PUT",
            Self::Subscription => "GET, PUT, DELETE",
        }
    }
}
/// Trusted installed context; the HTTP caller cannot choose its state or sources.
pub trait Api: Send + Sync {
    fn read(&self, route: Read, now: u64, deadline: Instant) -> Result<Document, Error>;
    fn write(
        &self,
        request: Document,
        remove: bool,
        now: u64,
        deadline: Instant,
    ) -> Result<Document, Error>;
}
#[derive(Clone)]
pub struct Context(pub Arc<dyn Api>);
impl std::fmt::Debug for Context {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("NotificationContext")
    }
}
pub(crate) fn result(result: Result<Document, Error>) -> Reply {
    match result {
        Ok(document) if openwiz_core::notifications::model::Document::check(&document).is_ok() => {
            api::pretty(&document).map_or_else(|| failure(Error::Unavailable), api::ok)
        }
        Ok(_) => failure(Error::Unavailable),
        Err(e) => failure(e),
    }
}
fn failure(error: Error) -> Reply {
    let (status, kind, why) = match error {
        Error::OperationConflict => (
            409,
            "operation_conflict",
            "This operation id binds a different notification write",
        ),
        Error::GenerationConflict => (
            409,
            "generation_conflict",
            "Notification preferences or subscription have changed",
        ),
        Error::SubscriptionUnavailable => (
            409,
            "subscription_unavailable",
            "No current verified protected binding is available",
        ),
        Error::Busy | Error::Unavailable => (
            503,
            "state_unavailable",
            "Protected notification state is unavailable; no new effect was admitted",
        ),
    };
    let mut reply = api::error(status, kind, why);
    if error == Error::Busy {
        reply
            .extra
            .push(("Retry-After", crate::RETRY_AFTER_SECS.to_string()));
    }
    reply
}
pub(crate) fn read(context: Option<&Context>, route: Read, now: i64) -> Reply {
    let Some(context) = context else {
        return failure(Error::Unavailable);
    };
    let Ok(now) = u64::try_from(now) else {
        return failure(Error::Unavailable);
    };
    result(context.0.read(
        route,
        now,
        Instant::now() + openwiz_core::limits::RUN_BUDGET,
    ))
}
/// Host syntax and routing checks have already run in the common responder.
#[allow(clippy::too_many_arguments)]
pub(crate) fn respond(
    head: &Head,
    stream: &mut TcpStream,
    shared: &Shared,
    route: Read,
    host: &str,
    query: Option<&str>,
    deadline: Instant,
) -> Reply {
    let writing = match (route, head.method.as_str()) {
        (_, "GET") => false,
        (Read::Preferences | Read::Subscription, "PUT") | (Read::Subscription, "DELETE") => true,
        _ => {
            let mut reply =
                api::error(405, "method_not_allowed", "Unsupported notification method");
            reply.extra.push(("Allow", route.allow().to_owned()));
            return reply;
        }
    };
    if !writing {
        let lengths = head.values("Content-Length");
        let empty = match lengths.as_slice() {
            [] => true,
            [length] => !length.is_empty() && length.bytes().all(|b| b == b'0'),
            _ => false,
        };
        if !empty || !head.values("Transfer-Encoding").is_empty() {
            return api::error(400, "bad_request", "GET takes no body");
        }
        if query.is_some() {
            return api::error(400, "invalid_request", "This route takes no query");
        }
        return shared.runs.call(
            api::Call::NotificationRead(route),
            deadline,
            &shared.config.limits,
            &crate::core(shared),
        );
    }
    let Some(site) = shared
        .config
        .allowed_host
        .as_deref()
        .filter(|site| site.eq_ignore_ascii_case(host) && SendHost::new(site).is_ok())
    else {
        return api::error(
            421,
            "misdirected",
            "Notification writes require the configured public host",
        );
    };
    if query.is_some() {
        return api::error(400, "invalid_request", "This route takes no query");
    }
    if let Some(reply) = send::cross_site(head, site, "a notification preference write") {
        return reply;
    }
    let len = match send::length(
        head,
        &shared.config.limits,
        "a notification preference write",
    ) {
        Ok(n) => n,
        Err(reply) => return reply,
    };
    let timeout = shared
        .config
        .limits
        .body_timeout
        .min(deadline.saturating_duration_since(Instant::now()));
    let body = match send::read_body(stream, &head.rest, len, timeout) {
        Ok(b) => b,
        Err(reply) => return reply,
    };
    let document = match serde_json::from_slice::<Document>(&body) {
        Ok(document) if openwiz_core::notifications::model::Document::check(&document).is_ok() => {
            document
        }
        _ => {
            return api::error(
                400,
                "invalid_request",
                "Expected a strict notification write document",
            );
        }
    };
    if !matches!(
        (route, &document.record),
        (Read::Preferences, Record::PreferenceWrite(_))
            | (Read::Subscription, Record::SubscriptionWrite(_))
    ) {
        return api::error(
            400,
            "invalid_request",
            "Wrong notification record for this route",
        );
    }
    let Some(context) = shared.notifications.clone() else {
        return failure(Error::Unavailable);
    };
    let Ok(now) = u64::try_from(shared.clock.now().0) else {
        return failure(Error::Unavailable);
    };
    let slots = shared.sends.clone();
    if !slots.take(
        shared.config.limits.max_sends,
        deadline.min(Instant::now() + shared.config.limits.slot_wait),
    ) {
        return api::busy(&shared.config.limits);
    }
    let (tx, rx) = mpsc::channel();
    let remove = head.method == "DELETE";
    let worker_slots = slots.clone();
    if std::thread::Builder::new()
        .name("openwiz-server notification write".into())
        .spawn(move || {
            let reply = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                result(context.0.write(document, remove, now, deadline))
            }))
            .unwrap_or_else(|_| failure(Error::Unavailable));
            worker_slots.give();
            let _ = tx.send(reply);
        })
        .is_err()
    {
        slots.give();
        return failure(Error::Unavailable);
    }
    rx.recv_timeout(deadline.saturating_duration_since(Instant::now()))
        .unwrap_or_else(|_| {
            api::error(
                504,
                "deadline",
                "Notification write did not settle before the deadline; retain its operation id",
            )
        })
}
