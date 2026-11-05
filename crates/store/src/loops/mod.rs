//! Local, durable switches for OpenWiz definitions. No CloudRoom loop calls.
pub mod config;
pub mod document;
mod paths;
pub mod repository;
pub mod storage;
pub use paths::inspect as inspect_state;
pub use paths::read_service_state;

use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};

/// Supplied by trusted local wiring, never parsed from a request. Verification
/// binds this checkout to the configured repository and project. The operator
/// must come from a separately trusted source, never a definition's owner.
pub trait Trust: Send + Sync {
    fn verify(&self, checkout: &Path, repository: &str, project: &str) -> bool;
    fn actor(&self) -> Option<String>;
}
#[derive(Debug, PartialEq, Eq)]
pub enum SwitchError {
    Busy,
    Refused(String),
}
impl From<String> for SwitchError {
    fn from(reason: String) -> Self {
        Self::Refused(reason)
    }
}
impl From<&str> for SwitchError {
    fn from(reason: &str) -> Self {
        Self::Refused(reason.to_owned())
    }
}
impl std::fmt::Display for SwitchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Busy => f.write_str("a loop pass is running; retry the loop switch"),
            Self::Refused(reason) => f.write_str(reason),
        }
    }
}
#[derive(Clone)]
pub struct Context {
    pub checkout: PathBuf,
    pub state: PathBuf,
    pub repository: String,
    pub project: String,
    pub trust: Option<Arc<dyn Trust>>,
}
/// Maximum time a switch waits for an existing scheduler pass. This never
/// retries the switch write; only acquiring its shared state lock is retried.
pub const SWITCH_LOCK_WAIT: Duration = Duration::from_secs(30);
impl Context {
    /// Wait with the caller's monotonic clock, then record its current wall time.
    pub fn switch_with_clock(
        &self,
        target: &str,
        enabled: bool,
        clock: &dyn openwiz_core::ops::Clock,
    ) -> Result<Value, SwitchError> {
        self.switch_with_deadline(target, enabled, clock, None)
    }
    /// Bound a switch by the caller's deadline as well as the lock budget.
    pub fn switch_with_clock_until(
        &self,
        target: &str,
        enabled: bool,
        clock: &dyn openwiz_core::ops::Clock,
        deadline: Instant,
    ) -> Result<Value, SwitchError> {
        self.switch_with_deadline(target, enabled, clock, Some(deadline))
    }
    fn switch_with_deadline(
        &self,
        target: &str,
        enabled: bool,
        clock: &dyn openwiz_core::ops::Clock,
        deadline: Option<Instant>,
    ) -> Result<Value, SwitchError> {
        self.switch_when(
            target,
            enabled,
            &|| {
                u64::try_from(clock.now().0)
                    .map_err(|_| SwitchError::from("loop clock precedes epoch"))
            },
            &|| clock.monotonic(),
            deadline,
        )
    }
    pub fn switch(&self, target: &str, enabled: bool, at_ms: u64) -> Result<Value, String> {
        self.switch_when(target, enabled, &|| Ok(at_ms), &Instant::now, None)
            .map_err(|error| error.to_string())
    }
    fn switch_when(
        &self,
        target: &str,
        enabled: bool,
        at: &dyn Fn() -> Result<u64, SwitchError>,
        monotonic: &dyn Fn() -> Instant,
        request_deadline: Option<Instant>,
    ) -> Result<Value, SwitchError> {
        at()?;
        self.resolve(target)?;
        let deadline = monotonic()
            .checked_add(SWITCH_LOCK_WAIT)
            .ok_or("loop switch deadline is unavailable")?;
        let deadline = request_deadline.map_or(deadline, |request| request.min(deadline));
        let check_request = || {
            if request_deadline.is_some_and(|request| monotonic() >= request) {
                Err(SwitchError::Busy)
            } else {
                Ok(())
            }
        };
        check_request()?;
        let mut retry = || {
            let left = deadline.saturating_duration_since(monotonic());
            if left.is_zero() {
                return false;
            }
            std::thread::sleep(left.min(Duration::from_millis(100)));
            monotonic() < deadline
        };
        let state = storage::Storage::open_with_retry(&self.state, &mut retry)?;
        // Repeat all authority and identity reads under the scheduler's lock.
        let (definition, actor) = self.resolve(target)?;
        let at_ms = at()?;
        let mut saved = state.switch_state()?;
        if saved
            .events
            .last()
            .is_some_and(|event| event["at_ms"].as_u64().unwrap() > at_ms)
        {
            return Err("loop switch clock went backwards".into());
        }
        let event = serde_json::json!({
            "loop_id": definition.value["id"], "definition_revision": definition.revision,
            "repository": self.repository, "project": self.project,
            "enabled": enabled, "actor": actor, "at_ms": at_ms
        });
        saved.enabled.insert(
            definition.value["id"].as_str().unwrap().to_owned(),
            Value::Bool(enabled),
        );
        saved.events.push(event.clone());
        check_request()?;
        state.save_switch_state(&saved)?;
        Ok(event)
    }
    fn resolve(&self, target: &str) -> Result<(repository::Definition, String), String> {
        let trust = self
            .trust
            .as_ref()
            .ok_or("trusted loop context is unavailable")?;
        if openwiz_core::fleet::starts::Repository::parse(&self.repository).is_err()
            || !valid_project(&self.project)
            || !trust.verify(&self.checkout, &self.repository, &self.project)
        {
            return Err("loop repository or project identity is not verified".to_owned());
        }
        let actor = trust
            .actor()
            .filter(|actor| valid_actor(actor))
            .ok_or("trusted loop operator is unavailable")?;
        if target.trim().is_empty() || target.contains('\0') {
            return Err("a loop needs an exact name or identity".to_owned());
        }
        let definitions = repository::Repository(self.checkout.clone()).current()?;
        let mut matches = definitions
            .into_iter()
            .filter(|d| d.value["id"] == target || d.value["name"] == target);
        let definition = matches.next().ok_or("no such OpenWiz loop")?;
        if matches.next().is_some() {
            return Err("ambiguous OpenWiz loop target".to_owned());
        }
        if definition.value["action"]["project"]["kind"] != "id"
            || definition.value["action"]["project"]["value"] != self.project
        {
            return Err("loop does not belong to the verified project".to_owned());
        }
        Ok((definition, actor))
    }
}
fn valid_actor(actor: &str) -> bool {
    !actor.trim().is_empty() && !actor.contains('\0')
}
fn valid_project(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && !id.starts_with('-')
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
