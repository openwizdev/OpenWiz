//! Test-only verified bundle and job injection. Production has no fixture settings.
#[path = "../../../tests/fixture-entrypoints/fixture.rs"]
mod fixture;

fn main() -> std::process::ExitCode {
    let bundle = fixture::Bundle::from_environment();
    let mut jobs = openwiz_service::scheduler::Scheduler::default();
    if let Some(path) = std::env::var_os("OPENWIZ_FIXTURE_JOB_LOG") {
        jobs.register(
            "synthetic-held-job",
            std::num::NonZeroU64::new(1).unwrap(),
            move || {
                use std::io::Write;
                use std::os::unix::fs::OpenOptionsExt;
                let mut file = std::fs::OpenOptions::new()
                    .append(true)
                    .create(true)
                    .mode(0o600)
                    .open(&path)
                    .unwrap();
                file.write_all(b"synthetic job started\n").unwrap();
                file.sync_all().unwrap();
                // Hold this run until the fixture process is killed. The runtime
                // must continue serving HTTP and local status while a job is held.
                loop {
                    std::thread::park();
                }
            },
        )
        .unwrap();
    }
    // #2039: the installed notification journey. The real dispatch runs with a
    // recording delivery in place of T4's unsupported adapter; nothing else changes.
    if let Some(dir) = std::env::var_os("OPENWIZ_FIXTURE_NOTIFICATION_JOURNEY") {
        let dir = std::path::PathBuf::from(dir);
        assert!(dir.is_absolute());
        return openwiz_service::dispatch_with_delivery(
            bundle.discovery(),
            jobs,
            std::sync::Arc::new(move || {
                (
                    Box::new(journey::Recording(dir.clone())) as Box<_>,
                    std::sync::Arc::new(|id: &openwiz_core::notifications::model::Id, _| {
                        id.as_str() == "synthetic-binding"
                    }),
                )
            }),
        );
    }
    openwiz_service::dispatch_with_jobs(bundle.discovery(), jobs)
}

/// A recording delivery boundary: every submission is appended durably to
/// `submissions.log` before its reply. The test chooses the reply with an
/// optional `reply` file: `accepted` (absent), `uncertain`, or `crash` (exit
/// after recording, so the reply is lost). Synthetic; nothing leaves the process.
mod journey {
    use openwiz_core::notifications::{boundary::DeliveryBoundary, model::*};
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;

    pub struct Recording(pub std::path::PathBuf);
    fn text(value: &str) -> Text {
        Text::new(value).unwrap()
    }
    impl DeliveryBoundary for Recording {
        fn capability(&self) -> Capability {
            Capability {
                state: CapabilityState::Ready,
                permission: Permission::Granted,
                reason: text("Synthetic recording delivery"),
                next: text("None"),
            }
        }
        fn submit(&mut self, request: &Submission) -> DeliveryOutcome {
            let mut file = std::fs::OpenOptions::new()
                .append(true)
                .create(true)
                .mode(0o600)
                .open(self.0.join("submissions.log"))
                .unwrap();
            let line = serde_json::to_string(request).unwrap();
            file.write_all(format!("{line}\n").as_bytes()).unwrap();
            file.sync_all().unwrap();
            let reply = std::fs::read_to_string(self.0.join("reply")).unwrap_or_default();
            match reply.trim() {
                "crash" => std::process::exit(70),
                "uncertain" => DeliveryOutcome {
                    state: OutcomeState::Uncertain,
                    reason: text("Synthetic lost reply"),
                },
                _ => DeliveryOutcome {
                    state: OutcomeState::Accepted,
                    reason: text("Synthetic recorded acceptance"),
                },
            }
        }
    }
}
