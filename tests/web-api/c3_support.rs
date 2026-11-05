//! Reuse the existing fleet fake and generated A5 worlds, at the HTTP seam.
#![allow(dead_code)]
#[path = "../fleet/support.rs"]
mod fleet_support;
pub use fleet_support::*;
#[path = "../fleet/schema.rs"]
pub mod fleet_schema;
#[path = "../fleet/a5_world.rs"]
pub mod world;

use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use openwiz_adapter_github::{fleets::GitHubFleets, tickets::Tickets};
use openwiz_core::fleet::model::{Check, Commit, NonEmpty, Number};
use openwiz_core::fleet::tickets::{GitHub, IssueAnswer, PrAnswer, RepositoryAnswer};
use openwiz_core::limits::{READ_TIMEOUT, RUN_BUDGET};
use openwiz_core::source::SourceError;
use openwiz_server::{Config, FleetAgents, Fleets};

use crate::fake::{self, Fake};
use crate::http::TestServer;

fn list_source(fake: &FakeGh) -> GitHubFleets {
    list_source_timing_out_after(fake, list_timeout())
}

fn list_source_timing_out_after(fake: &FakeGh, timeout: std::time::Duration) -> GitHubFleets {
    GitHubFleets::with_executor(
        openwiz_adapter_github::process::Executor::program_for_fixtures(fake.program(), timeout),
    )
}

/// The list's read timeout, once per run: every read but the hung one must
/// finish inside it on a busy host too (#2645), so it is scaled to one
/// unheld fleet list timed now. The adapter keeps it at or below its own
/// 15-second read timeout.
fn list_timeout() -> std::time::Duration {
    static TIMEOUT: std::sync::OnceLock<std::time::Duration> = std::sync::OnceLock::new();
    *TIMEOUT.get_or_init(|| {
        crate::real_time::scaled(
            "c3_list_hang",
            crate::real_time::pick(
                "c3_list_hang",
                std::time::Duration::from_secs(15),
                std::time::Duration::from_secs(1),
            ),
            std::time::Duration::from_secs(15),
            || {
                let fake = FakeGh::new(
                    "c3-list-timeout-calibrate",
                    &Path::new(FIXTURES).join("fleets/complete/scenario.json"),
                );
                let room = Fake::new("c3-list-timeout-calibrate-room", "normal");
                let fleets = Fleets {
                    list: Arc::new(list_source_timing_out_after(&fake, READ_TIMEOUT)),
                    detail: Arc::new(Tickets::new(fake.program())),
                    agents: Arc::new(FleetAgents(room.source())),
                };
                let server = serve(&room, fleets, Config::default());
                assert_eq!(server.get("/api/v1/fleets").status, 200);
            },
        )
    })
}

pub fn sources(fake: &FakeGh, room: &Fake) -> Fleets {
    Fleets {
        list: Arc::new(list_source(fake)),
        detail: Arc::new(Tickets::new(fake.program())),
        agents: Arc::new(FleetAgents(room.source())),
    }
}

pub fn serve(fake: &Fake, fleets: Fleets, config: Config) -> TestServer {
    let listener = openwiz_server::bind(0).unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let lines = log.clone();
    let server = openwiz_server::start_with_fleets(
        listener,
        config,
        Arc::new(fake.source()),
        Arc::new(fake::clock()),
        Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
        Some(fleets),
    )
    .unwrap();
    let addr = server.local_addr();
    TestServer { server, addr, log }
}

pub fn world_fake(name: &str, world: &world::World) -> FakeGh {
    let fake = FakeGh::new(
        name,
        Path::new(FIXTURES)
            .join("fleets/complete/scenario.json")
            .as_path(),
    );
    let scenario = fake.dir.join("scenario.json");
    fs::write(&scenario, world.scenario().to_string()).unwrap();
    fake.set_scenario(&scenario);
    fake
}

/// Synthetic assumption: the source's own failure reason contains controls.
/// The real adapter discards raw tool diagnostics before this seam.
pub struct UncleanTicketList(pub Tickets);

impl GitHub for UncleanTicketList {
    fn version(&self, d: Instant) -> Result<String, SourceError> {
        self.0.version(d)
    }
    fn repository(&self, d: Instant) -> Result<RepositoryAnswer, SourceError> {
        self.0.repository(d)
    }
    fn issue(&self, n: Number, _d: Instant) -> Result<IssueAnswer, SourceError> {
        assert_eq!(n.get(), 901, "only the synthetic spec should be read");
        Err(SourceError::Malformed {
            detail: "synthetic\nline\u{0001}control\u{202e}bidi".to_owned(),
        })
    }
    fn pull_request(&self, _n: Number, _d: Instant) -> Result<PrAnswer, SourceError> {
        panic!("no PR read after the spec ticket list fails")
    }
    fn checks(&self, _n: Number, _d: Instant) -> Result<Vec<Check>, SourceError> {
        panic!("no checks read after the spec ticket list fails")
    }
    fn verdict_comments(&self, _n: Number, _d: Instant) -> Result<Vec<String>, SourceError> {
        panic!("no verdict read after the spec ticket list fails")
    }
    fn on_base(&self, _c: &Commit, _b: &NonEmpty, _d: Instant) -> Result<bool, SourceError> {
        panic!("no merge readback after the spec ticket list fails")
    }
}

pub fn cli(fake: &FakeGh, room: &Fake, spec: Option<&str>) -> (i32, Vec<u8>, String) {
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let args: Vec<OsString> = spec
        .into_iter()
        .chain(["--json"])
        .map(OsString::from)
        .collect();
    let code = match spec {
        None => openwiz_cli::fleets::run_with(
            &args,
            &list_source(fake),
            &fake::clock(),
            RUN_BUDGET,
            &mut out,
            &mut err,
        ),
        Some(_) => openwiz_cli::fleet::run_with(
            &Tickets::new(fake.program()),
            &FleetAgents(room.source()),
            &fake::clock(),
            RUN_BUDGET,
            &args,
            &mut out,
            &mut err,
        ),
    };
    (code, out, String::from_utf8(err).unwrap())
}
