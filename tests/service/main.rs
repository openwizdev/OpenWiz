//! OpenWiz 0.0.8 (spec #262, close the Mac for good): the always-on
//! service's proofs, one file per ticket, so no two tickets edit the same
//! one.
//!
//! Each ticket adds only its own `mod` line here (the orchestrator, on
//! ClosedWiz#268), and declares any more modules of its own from inside its
//! file with `#[path = "tN_more.rs"] mod more;`:
//! - `t3_planner`: T3 (#268), the health planner's table tests (C3).
//!
//! **Fixtures only.** Fixture tests never prove live behaviour.

mod t12_handover;
mod t2_locate;
mod t3_planner;
