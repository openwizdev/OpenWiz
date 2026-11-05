//! Shared default App client for tick/health, with an isolated event-read factory.
use openwiz_adapter_github::{
    allowlist::Invocation,
    app::{App, Clock, CurlExchange, Error, Exchange, Identity, SystemClock},
};
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};

#[derive(Clone)]
pub struct Client(Arc<App>);
impl Client {
    /// Construct once, then clone for the tick and health jobs. No mint until execute.
    pub fn from_config(root: &Path, config: &str) -> Result<Self, Error> {
        Self::with_exchange(
            root,
            config,
            PathBuf::from(openwiz_adapter_github::PROGRAM),
            Arc::new(CurlExchange),
            Arc::new(SystemClock),
        )
    }
    /// Event intake alone opts into its fixed read-only authentication profile.
    pub fn from_config_for_events(root: &Path, config: &str) -> Result<Self, Error> {
        Self::with_exchange_for_events(
            root,
            config,
            PathBuf::from(openwiz_adapter_github::PROGRAM),
            Arc::new(CurlExchange),
            Arc::new(SystemClock),
        )
    }
    pub fn with_exchange_for_events(
        root: &Path,
        config: &str,
        gh: PathBuf,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, Error> {
        Self::with_profile(root, config, gh, exchange, clock, true)
    }
    pub fn with_exchange(
        root: &Path,
        config: &str,
        gh: PathBuf,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, Error> {
        Self::with_profile(root, config, gh, exchange, clock, false)
    }
    fn with_profile(
        root: &Path,
        config: &str,
        gh: PathBuf,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
        events: bool,
    ) -> Result<Self, Error> {
        let config =
            crate::document::read(crate::document::Document::Config, config).map_err(|_| Error)?;
        let identity = Identity {
            app_id: config["github_app"]["app_id"].as_u64().ok_or(Error)?,
            installation_id: config["github_app"]["installation_id"]
                .as_u64()
                .ok_or(Error)?,
            repository: format!(
                "{}/{}",
                config["repository"]["owner"].as_str().ok_or(Error)?,
                config["repository"]["name"].as_str().ok_or(Error)?
            ),
        };
        let open = if events {
            App::open_for_events
        } else {
            App::open
        };
        Ok(Self(Arc::new(open(root, identity, gh, exchange, clock)?)))
    }
    pub fn execute(&self, call: &Invocation, deadline: Instant) -> Result<Vec<u8>, Error> {
        self.0.execute(call, deadline)
    }
}
