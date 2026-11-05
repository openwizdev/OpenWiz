//! CI may install Python only after cargo test. The Rust proofs must not need it.
use super::*;

#[test]
fn fixture_runs_when_the_test_host_has_no_python_on_path() {
    let root = std::env::temp_dir().join(format!("ow-t7-no-python-{}", std::process::id()));
    private_dir(&root);
    let out = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "mints_at_the_fake_endpoint_and_uses_only_the_repository_scoped_token",
            "--nocapture",
        ])
        .env_clear()
        .env("PATH", &root)
        .output()
        .unwrap();
    fs::remove_dir_all(root).unwrap();
    assert!(
        out.status.success(),
        "mint/signature fixture must not require Python: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}
