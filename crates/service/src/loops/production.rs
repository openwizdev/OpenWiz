//! L12: the existing Runner, installation binding and setup-owned LP1 inputs.
use super::{Approval, Config, Runner, Services, approval::InstalledApproval, limits};
use crate::{
    document::{self, Document},
    paths,
    scheduler::Scheduler,
};
use openwiz_core::{loops::Limits, new_thread::operation::NewThreadClient, ops::Clock};
use openwiz_store::{NewThreadFileStore, loops::config::installed};
use serde_json::Value;
use std::{
    fs::{self, OpenOptions},
    io::Read,
    num::NonZeroU64,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
    sync::Arc,
};

const REFUSED: &str = "production loop inputs are unavailable or invalid";

/// Sources already supplied by the installed runtime. Recording fixtures may
/// replace the checkout, command client and clock, never approvals or limits.
pub struct Sources {
    pub checkout: PathBuf,
    pub client: Arc<dyn NewThreadClient>,
    pub clock: Arc<dyn Clock>,
}

/// Reuse the watchdog's current-directory checkout and configured tick cadence.
/// Absence of a loops record registers nothing. No installation or activation.
pub fn register(root: &Path, config: &Value, scheduler: &mut Scheduler) -> Result<bool, String> {
    register_with_sources(
        root,
        config,
        scheduler,
        Sources {
            checkout: std::env::current_dir().map_err(|_| REFUSED)?,
            client: Arc::new(openwiz_adapter_cloudroom::source::CloudRoomSource::from_path()),
            clock: Arc::new(openwiz_cli::SystemClock),
        },
    )
}

pub fn register_with_sources(
    root: &Path,
    config: &Value,
    scheduler: &mut Scheduler,
    sources: Sources,
) -> Result<bool, String> {
    let current = protected_config(root)?;
    if current.get("loops").is_none() {
        return Ok(false);
    }
    let repository = format!(
        "{}/{}",
        config["repository"]["owner"].as_str().ok_or(REFUSED)?,
        config["repository"]["name"].as_str().ok_or(REFUSED)?
    );
    let project = config["project"].as_str().ok_or(REFUSED)?.to_owned();
    let every = config["tick"]["every_s"]
        .as_u64()
        .and_then(NonZeroU64::new)
        .ok_or(REFUSED)?;
    let approval = Arc::new(Installed {
        root: root.to_owned(),
        checkout: sources.checkout.clone(),
        repository: repository.clone(),
        project: project.clone(),
        every,
        verifier: InstalledApproval::new(
            sources.checkout.clone(),
            root.to_owned(),
            repository,
            project,
        ),
    });
    let limits = approval.inputs()?;
    let new_threads = Arc::new(NewThreadFileStore::open(root).map_err(|_| REFUSED)?);
    Runner::new(
        Config {
            checkout: sources.checkout,
            state: root.to_owned(),
            limits: Some(limits),
        },
        Services {
            clock: sources.clock,
            client: sources.client,
            new_threads,
            approval: Some(approval),
        },
    )
    .register(scheduler, every)?;
    Ok(true)
}

struct Installed {
    root: PathBuf,
    checkout: PathBuf,
    repository: String,
    project: String,
    every: NonZeroU64,
    verifier: InstalledApproval,
}
impl Installed {
    fn inputs(&self) -> Result<Limits, String> {
        let config = protected_config(&self.root)?;
        document::validate_loop_config(&config).map_err(|_| REFUSED)?;
        if config["project"] != self.project
            || config["tick"]["every_s"].as_u64() != Some(self.every.get())
            || format!(
                "{}/{}",
                config["repository"]["owner"].as_str().ok_or(REFUSED)?,
                config["repository"]["name"].as_str().ok_or(REFUSED)?
            ) != self.repository
        {
            return Err(REFUSED.into());
        }
        let limits = limits::read(config.to_string().as_bytes()).map_err(|_| REFUSED)?;
        let context = installed(&self.checkout, &self.root).map_err(|_| REFUSED)?;
        if context.repository != self.repository
            || context.project != self.project
            || !context
                .trust
                .as_ref()
                .is_some_and(|trust| trust.verify(&self.checkout, &self.repository, &self.project))
        {
            return Err(REFUSED.into());
        }
        Ok(limits)
    }
}
impl Approval for Installed {
    fn verify(&self, definition: &Value, revision: &str) -> bool {
        // Re-read both records at every existing Runner effect boundary, so
        // revocation during a check/preview cannot retain cached capacities.
        self.inputs().is_ok() && self.verifier.verify(definition, revision)
    }
}

fn protected_config(root: &Path) -> Result<Value, String> {
    paths::inspect(root).map_err(|_| REFUSED)?;
    let path = root.join("service/config.json");
    let before = fs::symlink_metadata(&path).map_err(|_| REFUSED)?;
    // Same assessed no-follow/nonblocking flags as L10 and attachment metadata.
    let nonblock = if cfg!(target_vendor = "apple") {
        0x0004
    } else {
        0o4000
    };
    let nofollow = if cfg!(target_vendor = "apple") {
        0x0100
    } else if cfg!(any(target_arch = "arm", target_arch = "aarch64")) {
        0o100000
    } else {
        0o400000
    };
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(nonblock | nofollow)
        .open(&path)
        .map_err(|_| REFUSED)?;
    let opened = file.metadata().map_err(|_| REFUSED)?;
    #[cfg(target_vendor = "apple")]
    let uid =
        openwiz_store::attachments::owner_uid_from_private_state(root).map_err(|_| REFUSED)?;
    #[cfg(not(target_vendor = "apple"))]
    let uid = openwiz_store::attachments::effective_uid().map_err(|_| REFUSED)?;
    let same = |m: &fs::Metadata| {
        m.is_file()
            && !m.file_type().is_symlink()
            && m.nlink() == 1
            && m.uid() == uid
            && m.mode() & 0o077 == 0
            && m.dev() == before.dev()
            && m.ino() == before.ino()
    };
    if !same(&opened) {
        return Err(REFUSED.into());
    }
    let mut text = String::new();
    file.read_to_string(&mut text).map_err(|_| REFUSED)?;
    let after = fs::symlink_metadata(path).map_err(|_| REFUSED)?;
    if !same(&after)
        || opened.len() != after.len()
        || opened.mtime() != after.mtime()
        || opened.mtime_nsec() != after.mtime_nsec()
        || opened.ctime() != after.ctime()
        || opened.ctime_nsec() != after.ctime_nsec()
    {
        return Err(REFUSED.into());
    }
    paths::inspect(root).map_err(|_| REFUSED)?;
    document::read(Document::Config, &text).map_err(|_| REFUSED.into())
}
