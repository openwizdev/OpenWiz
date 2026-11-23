mod fixture;
#[path = "../../crates/cli/src/main.rs"]
#[allow(
    dead_code,
    reason = "this fixture has its own main and reuses only the CLI's dispatch"
)]
mod shared;

fn main() -> std::process::ExitCode {
    let fixture = fixture::Bundle::from_environment();
    shared::dispatch(fixture.discovery())
}
