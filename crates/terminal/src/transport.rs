//! Runs the shared seam's [`ActionRequest`]s on the existing routes, once,
//! over the loopback client: typed bodies, guarded headers only with the
//! configured host, no retry. Kept outside `actions/`, which the CLI also
//! compiles for its capability document.

use serde_json::Value;

use crate::actions::{ActionRequest, TransportResult};
use crate::http::{Client, Reply, error_reason};

/// One segment of a path: the ids the routes take are letters, digits, `_`
/// and `-`; anything else is refused before dispatch.
fn segment_ok(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// Runs one action request on the existing routes, once. No retry.
pub fn execute(client: &Client, request: &ActionRequest) -> TransportResult {
    let (method, path, body, schema) = request.route();
    let ids_ok = match request {
        ActionRequest::SendPreview { target, .. } => segment_ok(target),
        ActionRequest::Send(s) => segment_ok(&s.target) && segment_ok(&s.op_id),
        ActionRequest::Lookup { target, op_id } => segment_ok(target) && segment_ok(op_id),
        ActionRequest::Options => true,
        ActionRequest::NewPreview(n) | ActionRequest::Create(n) => {
            segment_ok(&n.project_id) && segment_ok(&n.op_id)
        }
        ActionRequest::Status { op_id } => segment_ok(op_id),
    };
    if !ids_ok {
        return TransportResult::FailedBeforeDispatch {
            reason: "an id is not one path segment of letters, digits, _ or -".into(),
        };
    }
    let reply = match (method, body) {
        ("POST", Some(body)) => {
            let bytes = serde_json::to_vec(&body).unwrap_or_default();
            client.post_guarded(&path, &bytes)
        }
        _ => client.get(&path),
    };
    classify(request.is_dispatch(), schema, reply)
}

fn classify(
    write: bool,
    schema: &str,
    reply: Result<Reply, crate::http::Failure>,
) -> TransportResult {
    let invalid = |why: String| {
        let reason = format!("the answer is not a valid {schema} report ({why})");
        if write {
            // It may have happened: never a refusal, never safe to resend.
            TransportResult::UnknownAfterDispatch { reason }
        } else {
            TransportResult::Refused {
                http_status: 200,
                reason,
            }
        }
    };
    match reply {
        Err(f) if !f.dispatched => TransportResult::FailedBeforeDispatch { reason: f.reason },
        Err(f) => TransportResult::UnknownAfterDispatch { reason: f.reason },
        Ok(reply) if reply.status == 200 => match crate::json::parse(&reply.body) {
            Ok(body) => match crate::schema::validate_report(schema, &body) {
                Ok(()) => TransportResult::Report {
                    http_status: 200,
                    body,
                },
                Err(why) => invalid(why),
            },
            Err(why) => invalid(why),
        },
        Ok(reply) if write && !refused_before_effect(&reply) => {
            TransportResult::UnknownAfterDispatch {
                reason: error_reason(&reply),
            }
        }
        Ok(reply) => TransportResult::Refused {
            http_status: reply.status,
            reason: error_reason(&reply),
        },
    }
}

/// A write's failure the web API contract says happened before any effect:
/// every request refusal (4xx), `503 busy` (not claimed), and the record or
/// store being unusable (`500 record_unavailable` / `store_unavailable`:
/// "nothing was sent or created"). Anything else (`500 internal`, `502`,
/// `504`, an unreadable body) may have dispatched.
fn refused_before_effect(reply: &Reply) -> bool {
    let kind = crate::json::parse(&reply.body).ok().and_then(|v| {
        v.get("error")
            .and_then(|e| e.get("kind"))
            .and_then(Value::as_str)
            .map(str::to_owned)
    });
    match reply.status {
        400..=499 => true,
        503 => kind.as_deref() == Some("busy"),
        500 => matches!(
            kind.as_deref(),
            Some("record_unavailable" | "store_unavailable")
        ),
        _ => false,
    }
}
