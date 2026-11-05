//! Same server implementation, stores, providers and guards as openwiz-server.
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{decisions::GitHubDecisions, fleets::GitHubFleets, tickets::Tickets};
use openwiz_core::{messaging::record::SendStore, new_thread::record::NewThreadStore};
use openwiz_server::{
    Attaching, Config, Creating, Decisions, FleetAgents, Fleets, Plan, SendHost, Sending,
    SystemClock, WebRoot,
};
use openwiz_store::{AttachmentStore, FileStore, NewThreadFileStore, attachments::Df};
use std::{net::TcpListener, path::Path, sync::Arc};

pub fn start(
    root: &Path,
    listener: TcpListener,
    host: Option<SendHost>,
    web: WebRoot,
) -> Result<openwiz_server::Server, String> {
    // The service's explicit answer target also governs the embedded decisions
    // and cockpit reads. A failed configuration read remains unknown; it must
    // never fall back to a different thread from the process environment.
    let target = configured_target(root);
    let sends = root.to_owned();
    let sends_read = root.to_owned();
    let creates = root.to_owned();
    let creates_read = root.to_owned();
    let attaches = root.to_owned();
    let attaches_read = root.to_owned();
    let config = Config {
        allowed_host: host.as_ref().map(|h| h.as_str().to_owned()),
        web_root: Some(web),
        sending: Some(Sending {
            messenger: Arc::new(CloudRoomSource::from_path()),
            open_store: Arc::new(move || {
                Ok(Box::new(FileStore::open(&sends)?) as Box<dyn SendStore>)
            }),
            open_store_read_only: Arc::new(move || {
                Ok(FileStore::open_read_only(&sends_read)?
                    .map(|s| Box::new(s) as Box<dyn SendStore>))
            }),
            host: host.clone(),
        }),
        creating: Some(Creating {
            client: Arc::new(CloudRoomSource::from_path()),
            open_store: Arc::new(move || {
                Ok(Box::new(NewThreadFileStore::open(&creates)?) as Box<dyn NewThreadStore>)
            }),
            open_store_read_only: Arc::new(move || {
                Ok(NewThreadFileStore::open_read_only(&creates_read)?
                    .map(|s| Box::new(s) as Box<dyn NewThreadStore>))
            }),
            host: host.clone(),
        }),
        attaching: Some(Attaching {
            open_store: Arc::new(move || AttachmentStore::open(&attaches)),
            open_store_read_only: Arc::new(move || AttachmentStore::open_read_only(&attaches_read)),
            free_space: Arc::new(Df),
            host,
        }),
        ..Config::default()
    };
    // #2039 (Q1): a tap's token resolves only through the job's protected store;
    // an unreadable store is unavailable, never another item. A pass holds the
    // store's lock, so a tap waits for it within the request's deadline.
    let mapping = openwiz_store::notifications::Store::new(root);
    let targets = openwiz_server::NotificationTargets {
        read_mapping: Arc::new(move |token, deadline| {
            use openwiz_store::notifications::Error;
            let Some(token) = openwiz_core::notifications::model::Fingerprint::new(token) else {
                return Ok(None);
            };
            loop {
                match mapping.target(&token) {
                    Ok(found) => {
                        return Ok(
                            found.map(|o| openwiz_core::notifications::policy::reference(&o.fact))
                        );
                    }
                    Err(Error::Busy) if std::time::Instant::now() < deadline => {
                        std::thread::sleep(
                            std::time::Duration::from_millis(5)
                                .min(deadline.saturating_duration_since(std::time::Instant::now())),
                        );
                    }
                    Err(_) => return Err(openwiz_server::TargetReadError::Unavailable),
                }
            }
        }),
    };
    openwiz_server::start_with_notifications_and_targets(
        listener,
        config,
        Arc::new(CloudRoomSource::from_path()),
        Arc::new(SystemClock),
        Arc::new(|line| eprintln!("openwiz-server: {line}")),
        openwiz_server::NotificationReadSources {
            targets,
            reads: openwiz_server::ReadSources {
                plan: Some(Plan::with_program(openwiz_adapter_github::PROGRAM)),
                fleets: Some(Fleets {
                    list: Arc::new(GitHubFleets::from_path()),
                    detail: Arc::new(Tickets::from_path()),
                    agents: Arc::new(FleetAgents(CloudRoomSource::from_path())),
                }),
                decisions: Some(Decisions {
                    github: GitHubDecisions::from_path()
                        .with_settings(&root.join("service/config.json")),
                    target,
                }),
            },
        },
        openwiz_server::loops::installed(root),
        // #2035: the same installed delivery factory as the job, over its store
        // (#2039: through `crate::delivery`, which a fixture may replace).
        openwiz_server::notifications::Context(Arc::new({
            let (delivery, binding) = crate::delivery();
            crate::notifications::Engine::new(
                openwiz_store::notifications::Store::new(root),
                Arc::new(crate::notifications::UnavailableSources),
                delivery,
                Arc::new(SystemClock),
                binding,
            )
        })),
    )
    .map_err(|_| "cannot start the embedded HTTP server".to_owned())
}

fn configured_target(root: &Path) -> Result<Option<String>, ()> {
    std::fs::read_to_string(root.join("service/config.json"))
        .map_err(|_| ())
        .and_then(|text| {
            crate::document::read(crate::document::Document::Config, &text).map_err(|_| ())
        })
        .and_then(|config| {
            config["orchestrator_thread"]
                .as_str()
                .map(str::to_owned)
                .ok_or(())
        })
        .map(Some)
}

#[cfg(test)]
#[path = "../../../tests/service/install_engine_target.rs"]
mod target_tests;

/// The installed API implementation with an explicitly injected offline engine.
/// This starts only the supplied loopback listener; no production intake/job is added.
pub fn start_notification_api(
    listener: TcpListener,
    config: Config,
    source: Arc<dyn openwiz_core::source::SessionSource>,
    clock: Arc<dyn openwiz_core::ops::Clock>,
    log: openwiz_server::Log,
    engine: Arc<crate::notifications::Engine>,
) -> std::io::Result<openwiz_server::Server> {
    openwiz_server::start_with_notifications(
        listener,
        config,
        source,
        clock,
        log,
        openwiz_server::ReadSources::default(),
        None,
        openwiz_server::notifications::Context(engine),
    )
}
