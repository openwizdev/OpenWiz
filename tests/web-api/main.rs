//! OpenWiz 0.0.2 ticket 1: proof tests for `openwiz-server`, written before
//! the server. See `contracts/web-api.v1.md`.
//!
//! - A3 the server listens on loopback only and refuses foreign `Host`s;
//! - A4 only `GET` on the three allowlisted routes, and only the core's
//!   list and show, with the same reads as the CLI;
//! - A5 queries, heads, bodies, connections and core runs are bounded,
//!   identical requests share one run, and slow clients time out;
//! - A6 every inventory and session body equals `openwiz … --json` for
//!   the same options;
//! - A7 security headers, no CORS, no cache, and nothing leaked in errors
//!   or logs, including no `room-cli` diagnostic text (since the merge of
//!   #21);
//!
//! - A8 the web page, from one `--web-root` directory: an allowlist that
//!   matches the export, contained, `GET` and `HEAD` only, page headers
//!   (#46).
//!
//! OpenWiz 0.0.3 #9, the one write:
//!
//! - W1 exactly one mutation route; W2 owner identity is never read from a
//!   request (the tunnel checks it); W3 cross-site requests are refused;
//!   W4 the send is bounded and never logged; W5 every answer is the CLI's
//!   `--json`; W6 sends are never coalesced; W15 a restart never sends
//!   again, and the server and the CLI share one send record (U9).
//!
//! OpenWiz 0.0.4 #12 (A2), the new-thread routes:
//!
//! - U1 exactly the new routes, and no retry route; U2 owner identity is
//!   never read from a request; U3 cross-site creates are refused; U4 the
//!   create is bounded and never logged; U5 every answer is the CLI's
//!   `--json`; U6 creates are never coalesced; U9 the preview shows the
//!   core's effects and creates nothing; U11 an uncertain create stays
//!   uncertain and a status read never creates; U12 a repeat is one call.
//!   U7, U8, U10, U13 to U15 and the page's halves of U9, U11 and U12 are
//!   the web's (`apps/web/test/`).
//!
//! OpenWiz 0.0.4 #16 (B3), the attachment routes:
//!
//! - AW1 exactly the planned routes, and no route returns an attachment's
//!   bytes; AW2 owner only and no cross-site upload or removal, each
//!   refusal staging nothing; AW3 uploads are bounded (size, framing,
//!   time, two at a time, low disk, the name) and never logged; AW4 every
//!   answer is the CLI's `--json`, and no attachment rule is worked out in
//!   the server or the web; AW5 the server's gate (the core's) refuses a
//!   forged send or create with an attachment that is not ready, with zero
//!   calls. AW5's page half and AW6 to AW11 are the web's
//!   (`apps/web/test/`).
//!
//! A1, A2 and A9 are not fixture tests: see the evidence README.
//! Fixture tests never prove live behaviour.

mod fake;

#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod schema;

#[path = "../new-thread/pattern.rs"]
mod pattern;

#[allow(dead_code)]
#[path = "../support/dirs.rs"]
mod dirs;

// Waiting out a forked child's copy of a file (#176).
#[allow(dead_code)]
#[path = "../support/forks.rs"]
mod forks;

// Reading the fake's call counters (#176).
#[allow(dead_code)]
#[path = "../support/counter.rs"]
mod counter;

// Running independent cases at once (#1259).
#[path = "../support/at_once.rs"]
mod at_once;

mod http;

#[path = "../messaging/support.rs"]
mod msg;

mod send_support;

mod new_support;

mod a3_loopback;
mod a4_no_mutation;
mod a5_bounds;
mod a6_semantics;
mod a7_headers_and_logs;
mod a7_source_diagnostics;
mod a8_web_page;
mod contract;
mod w15_no_redispatch;
mod w1_one_mutation;
mod w2_owner;
mod w3_cross_site;
mod w4_bounds;
mod w5_same_operation;
mod w6_never_coalesced;

mod u01_new_routes;
mod u02_u03_owner_and_cross_site;
mod u04_bounds;
mod u05_same_operation;
mod u06_u12_never_coalesced;
mod u09_u11_preview_and_status;

#[path = "../attachments/staging.rs"]
mod staging;

mod attach_support;

mod aw01_routes;
mod aw02_owner_and_cross_site;
mod aw03_bounds;
mod aw03_streaming;
mod aw04_same_operation;
mod aw05_gate;

mod c3_routes;

mod c3_binary;
mod c3_bounds;
mod c3_semantics;
mod e11_decisions_bounds;
mod e11_decisions_guards;
mod e11_decisions_records;
mod e11_decisions_review;
mod e11_decisions_routes;
mod e11_decisions_support;
#[path = "c3_support.rs"]
mod support;

mod e11_plan_bounds;
mod e11_plan_graph;
mod e11_plan_partial;
mod e11_plan_reads;
mod e11_plan_review;
mod e11_plan_routes;
mod e11_plan_states;
mod e11_plan_support;

mod c10_cockpit_cases;
mod c10_cockpit_review;
mod c10_cockpit_route;
mod c10_cockpit_support;

mod lp6_loops_read;
mod lp6_loops_route;

mod notification_target;
mod ready_stock;

#[path = "../support/real_time.rs"]
mod real_time;

// Start the real five-second lock proof early so its wait overlaps the other
// independent cases. Its complete assertion body stays in lp6_loops_route.
mod a0_lock_wait {
    #[test]
    fn lp6_get_loops_is_busy_while_a_pass_holds_the_state() {
        crate::lp6_loops_route::lp6_get_loops_is_busy_while_a_pass_holds_the_state();
    }
}
