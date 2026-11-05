//! `openwiz-terminal`: the visual terminal app (OpenWiz 0.0.12, T3, #1098).
//! A thin client of an already running local `openwiz-server`: it reads the
//! existing routes over loopback HTTP and never starts a server, runs
//! `room-cli` or `gh`, or adds a route. The only crate that may use the
//! approved visual pair, `ratatui` and `crossterm` (grill C3).

pub mod actions;
pub mod app;
pub mod config;
pub mod http;
pub mod json;
pub mod model;
pub mod render;
pub mod run;
pub mod sanitize;
pub mod schema;
pub mod transport;

/// Re-exported for the fixture tests' test backend, so no other crate
/// declares the visual pair.
pub use ratatui;
