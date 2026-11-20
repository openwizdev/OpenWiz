//! Foundation checks that pass in ticket 1: the approved dependency set, the
//! fixture scan, schema conformance and the pending list.
//! OpenWiz 0.0.5 (ClosedWiz#96) adds the skills folder's static check.

#[path = "../support/schema.rs"]
mod schema;

#[allow(dead_code)]
#[path = "../support/dirs.rs"]
mod dirs;

mod cli_build_script;
mod dependencies;
mod evidence_outside_crates;
mod fixture_scan;
mod pending;
mod plan_decisions_schema_conformance;
mod plan_links;
mod schema_conformance;
mod skills;
mod strict_json;

#[allow(dead_code)]
#[path = "../support/place.rs"]
mod place;

// LP1 contract conformance (ClosedWiz#543), using the existing extensions.
mod loops_schema;
#[path = "../new-thread/pattern.rs"]
mod pattern;
