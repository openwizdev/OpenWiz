//! Offline notification engine seam. Production source registration is #2034.
pub mod delivery;
pub mod engine;
pub mod sources;
pub use engine::{Batch, Engine, Sources, UnavailableSources};
