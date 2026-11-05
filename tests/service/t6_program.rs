//! Copied into a disposable Git repository by the T6 process fixtures.
use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt, sync::Arc};
fn main() -> std::process::ExitCode {
    if std::env::args().len() == 1 && include_str!("mode") != "pass" {
        return std::process::ExitCode::FAILURE;
    }
    let root = std::path::PathBuf::from(std::env::var_os("OPENWIZ_STATE_DIR").unwrap_or_default());
    let configured_port = root.join("service/fixture-configured-port").is_file();
    struct NoNetwork;
    impl service::update::Executor for NoNetwork {
        fn run(&self, _: &service::update::Call) -> Result<String, String> {
            Err("fixture forbids network commands".to_owned())
        }
    }
    service::update::install_executor(Arc::new(NoNetwork)).unwrap();
    service::update::install_records(Arc::new(move |issue, body| {
        if issue != 901 {
            return Err(service::update::RecordError::Unsent);
        }
        if root.join("service/fixture-record-unsent").is_file() {
            return Err(service::update::RecordError::Unsent);
        }
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(root.join("service/fixture-records"))
            .map_err(|_| service::update::RecordError::Unsent)?;
        // JSON-escape without a fixture-only production dependency.
        let escaped = body
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n");
        writeln!(file, "\"{escaped}\"").map_err(|_| service::update::RecordError::Uncertain)
    }))
    .unwrap();
    let discovery = adapter::locate::Discovery::system();
    let jobs = service::scheduler::Scheduler::default();
    if configured_port {
        // The deliberate occupied-port proof exercises ordinary production
        // dispatch, including the real configured-port refusal and rollback.
        service::dispatch_with_jobs(discovery, jobs)
    } else {
        // Every start, including candidate exec and rollback, creates and hands
        // over one owned listener. No saved port is released and rebound.
        service::dispatch_with_binder(discovery, jobs, |_| {
            std::net::TcpListener::bind(("127.0.0.1", 0))
        })
    }
}
