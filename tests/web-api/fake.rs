//! The shared proof fake, using the same program built once with optimization.
#[path = "../proof/support.rs"]
mod shared;
pub use shared::*;

pub struct Fake(shared::Fake);

impl Fake {
    pub fn new(test: &str, scenario: &str) -> Self {
        openwiz_adapter_cloudroom::source::use_fast_polling_for_fixtures();
        crate::http::server_binary();
        let fake = shared::Fake::new(test, scenario);
        let target = std::path::Path::new(env!("CARGO_TARGET_TMPDIR"))
            .parent()
            .unwrap();
        std::fs::remove_file(fake.program()).unwrap();
        std::os::unix::fs::symlink(target.join("release/fake-room-cli"), fake.program()).unwrap();
        Self(fake)
    }
}

impl std::ops::Deref for Fake {
    type Target = shared::Fake;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}
