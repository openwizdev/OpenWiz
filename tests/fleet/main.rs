//! OpenWiz 0.0.6 spec 1, seeing fleets (ClosedWiz#107): `openwiz fleets`
//! and `openwiz fleet <spec>`, read from GitHub through `gh` and joined with
//! CloudRoom's threads.
//!
//! **One file per ticket**, so no two tickets edit the same one. A3 (#111)
//! made the seams and declares every module here. Each ticket fills its
//! own file, and declares any more of its own from inside it with
//! `#[path = "a4_more.rs"] mod more;`, never here:
//! - `a3_seams`, `a3_commands`, `a3_fake_gh` and `a3_model`: A3's
//!   proofs, which stay true when later tickets fill their files. The
//!   seams exist, the new crate's dependencies point inward, each command
//!   is wired to its own file, the fake `gh` behaves as
//!   `tests/fake-gh/main.rs` says, and the core's fleet model types match
//!   the contract.
//! - `support`: the fakes and the release `openwiz`, and `schema`: the
//!   fleet schema's checker, for every ticket's tests.
//! - `a4_fleets`: A4 (#112), `openwiz fleets`; until then, its stub's
//!   proofs.
//! - `a5_fleet`: A5 (#113), `openwiz fleet <spec>`; until then, its stub's
//!   proofs.
//! - `a6_agents`: A6 (#114), a ticket's agents.
//! - `b3_writes`: spec 2's B3 (#119), the GitHub writes.
//! - `b4_starts`: spec 2's B4 (#120), starting builders and reviewers and
//!   archiving finished agents; its other files are declared from inside it.
//!
//! **Fixtures only.** Fixture tests never prove live behaviour.

mod schema;
mod support;

// Running independent cases at once (#1259).
#[path = "../support/at_once.rs"]
mod at_once;

// Real-time proofs, in full or in their fast form (#1259).
#[path = "../support/real_time.rs"]
mod real_time;

mod a3_commands;
mod a3_fake_gh;
mod a3_model;
mod a3_seams;
mod a4_fleets;
mod a5_fleet;
mod a6_agents;
mod b3_writes;
mod b4_starts;

mod b2_planner;
mod b5_tick;
mod lock_release;

mod c10_inventory;
mod c10_questions;

mod al1_titles;
