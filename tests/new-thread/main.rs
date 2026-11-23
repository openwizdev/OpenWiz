mod support;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/schema.rs"]
mod schema;

#[path = "../support/dirs.rs"]
mod dirs;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/forks.rs"]
mod forks;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/counter.rs"]
mod counter;

mod contract_tables;
mod n04_offered_only;
mod n05_honest_options;
mod n06_outcome_mapping;
mod n07_requested_and_reported;
mod n08_start_stages;
mod n11_op_id_binding;
mod n14_prompt_seam;
mod n16_allowlist;
mod n17_drift;
mod n18_report;
mod n19_status_read_only;
mod pattern;
