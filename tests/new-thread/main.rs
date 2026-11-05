//! The OpenWiz 0.0.4 new-thread proof cases (ClosedWiz#11), each written
//! before the behaviour. A1 phase 1: N1 (the argument builder), N2, N4 to
//! N8, N11, N14 and N17 to N19. A1 phase 2: N1 end to end, N3, N9, N10 (the
//! refusal half only: there is no retry, sheet A-3), N12, N13, N15, N16,
//! N18's CLI half and N5's, and the record kind (`record_store`).
//!
//! **Fixtures only.** Phase 1's proofs run the core against an in-memory
//! record store and a fake client that answers through the adapter's own
//! parsers. Phase 2's run the release `openwiz`, the in-process CLI and the
//! self-exec `harness` against the repository's fake `room-cli`, with
//! scenarios the tests write (`fake`), the synthetic
//! `room-cli-v127/new-thread` stdout files and a private state directory.
//! Nothing is created live, and fixture tests never prove live behaviour.
//!
//! `structure` holds the checks that are not one N case; `project_names`
//! and `schema_parity` answer Sol's phase 1 round 1 (`pattern` is their
//! schema checker), and `contract_tables` its round 2.

mod fake;
mod harness;
mod support;

#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod schema;

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

mod boundary_readers;
mod contract_tables;
mod inspect_claim_race;
mod n01_end_to_end;
mod n01_exact_invocation;
mod n02_no_rewrite;
mod n03_existing_projects;
mod n04_offered_only;
mod n05_honest_options;
mod n06_outcome_mapping;
mod n07_requested_and_reported;
mod n08_start_stages;
mod n09_lost_acknowledgement;
mod n10_no_retry;
mod n11_op_id_binding;
mod n12_cross_process_claim;
mod n13_crash_recovery;
mod n14_prompt_seam;
mod n15_nothing_else_changes;
mod n16_allowlist;
mod n17_drift;
mod n18_cli;
mod n18_report;
mod n19_status_read_only;
mod pattern;
mod project_names;
mod record_load;
mod record_store;
mod schema_parity;
mod structure;

// B2 (ClosedWiz#15): attachments in new_thread (AD1, AD4, AD6, AD7, AD9,
// AD10, AD13).
#[path = "../attachments/staging.rs"]
mod staging;

mod ad_new_thread_attachments;
