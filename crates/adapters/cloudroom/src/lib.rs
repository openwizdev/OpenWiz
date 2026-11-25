pub mod allowlist;
pub mod fleet;
pub mod locate;
pub mod loop_files;
pub mod messaging;
pub mod new_thread;
mod process;
pub mod source;

pub use process::{KEPT_ENV, SCRUBBED_ENV, SCRUBBED_ENV_PREFIX, is_scrubbed};

pub const PROGRAM: &str = "room-cli";

pub const TESTED_VERSION: &str = "v127";

pub const SEND_TESTED_VERSION: Option<&str> = None;

pub const NEW_TESTED_VERSION: Option<&str> = None;
