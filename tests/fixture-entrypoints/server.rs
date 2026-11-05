//! Test-only server: exact production dispatch, private verified fake bundle.
mod fixture;
#[path = "../../crates/server/src/main.rs"]
#[allow(dead_code)]
mod shared;

fn main() -> std::process::ExitCode {
    let fixture = fixture::Bundle::from_environment();
    shared::dispatch(fixture.discovery())
}
