//! Compiled only by the CloudRoom adapter unit-test target.
use super::*;

#[test]
fn ordinary_polling_stays_at_five_milliseconds() {
    assert_eq!(poll_interval(), Duration::from_millis(5));
}

#[test]
fn fixture_polling_is_fixed_and_process_local() {
    const CHILD: &str = "OPENWIZ_X2_POLL_SELECTION_PROOF";
    if std::env::var_os(CHILD).is_some() {
        crate::source::use_fast_polling_for_fixtures();
        assert_eq!(poll_interval(), Duration::from_millis(1));
        crate::source::use_fast_polling_for_fixtures();
        assert_eq!(poll_interval(), Duration::from_millis(1));
        return;
    }

    assert_eq!(poll_interval(), Duration::from_millis(5));
    // The opt-in belongs to one whole synthetic process. Mutating it in
    // this test's process would contaminate concurrently running tests.
    let child = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "process::tests::fixture_polling_is_fixed_and_process_local",
            "--nocapture",
        ])
        .env(CHILD, "1")
        .output()
        .unwrap();
    assert!(
        child.status.success(),
        "fixture selection failed:\n{}{}",
        String::from_utf8_lossy(&child.stdout),
        String::from_utf8_lossy(&child.stderr),
    );
    assert_eq!(poll_interval(), Duration::from_millis(5));
}

/// #1259: `READ_TIMEOUT` unless a fixture lowered it; never raised.
#[test]
fn the_read_timeout_is_read_timeout_unless_a_fixture_lowers_it() {
    assert_eq!(read_timeout_with(0), READ_TIMEOUT);
    assert_eq!(read_timeout_with(1), Duration::from_millis(1));
    assert_eq!(read_timeout_with(1_000), Duration::from_secs(1));
    assert_eq!(read_timeout_with(15_000), READ_TIMEOUT);
    assert_eq!(read_timeout_with(15_001), READ_TIMEOUT);
    assert_eq!(read_timeout_with(u64::MAX), READ_TIMEOUT);
    // Nothing in this process lowered it.
    assert_eq!(read_timeout(), READ_TIMEOUT);
}
