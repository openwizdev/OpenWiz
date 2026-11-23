mod support;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/schema.rs"]
mod schema;

#[path = "../support/dirs.rs"]
mod dirs;

mod p01_coverage;
mod p02_freshness;
mod p03_unknowns;
mod p04_partial_failures;
mod p04b_source_diagnostics;
mod p05_paging_and_budget;
mod p06_verified_grouping;
mod p07_bounded_output;
mod p08a_allowlist_static;
mod p09_reported_configuration;
mod p10_json_matches_text;
mod p11_visibility;
mod p12_drift;
mod t2_locate;
