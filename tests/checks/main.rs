#[path = "../support/schema.rs"]
mod schema;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/dirs.rs"]
mod dirs;

mod cli_build_script;
mod dependencies;
mod evidence_outside_crates;
mod fixture_scan;
mod schema_conformance;
mod skills;
mod strict_json;
mod test_floor;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/place.rs"]
mod place;

mod loops_schema;
mod market_publish;
#[path = "../new-thread/pattern.rs"]
mod pattern;
