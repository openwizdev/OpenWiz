const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

#[test]
fn onboard_journey_fixtures_pass() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/onboard/test_journey.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the onboarding journey");
    assert!(
        result.status.success(),
        "onboarding journey failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_contract_passes() {
    let result = std::process::Command::new("python3")
        .args([
            "-I",
            "tools/install/tests/setup-onboard-contract/test_contract.py",
        ])
        .current_dir(ROOT)
        .output()
        .expect("run the setup-onboard contract checks");
    assert!(
        result.status.success(),
        "setup-onboard contract checks failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_init_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/init/test_init.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the init runtime proofs");
    assert!(
        result.status.success(),
        "init runtime proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_login_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "-B", "tools/install/setup/test_github_login.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the setup GitHub login proofs");
    assert!(
        result.status.success(),
        "setup GitHub login proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn install_journey_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/journey/test_journey.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the install journey");
    assert!(
        result.status.success(),
        "install journey failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
