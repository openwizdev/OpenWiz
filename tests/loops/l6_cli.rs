//! LP5 command seam, explicit trusted fixture context only.
use super::fixture::Fixture;
use openwiz_core::{model::Timestamp, ops::Clock};
use std::{ffi::OsString, time::Instant};
pub struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(3000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
#[test]
fn cli_off_and_on_call_the_shared_writer_and_print_the_saved_audit() {
    let f = Fixture::new();
    for (command, enabled) in [("off", false), ("on", true)] {
        let mut out = vec![];
        let mut err = vec![];
        let code = openwiz_cli::loops::run(
            &[command, "loop-syn-reminder", "--json"].map(OsString::from),
            Some(&f.context),
            &FixedClock,
            &mut out,
            &mut err,
        );
        assert_eq!(code, 0, "{}", String::from_utf8_lossy(&err));
        let audit: serde_json::Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(audit["enabled"], enabled);
        assert_eq!(audit["actor"], "synthetic-operator");
        assert_eq!(audit["at_ms"], 3000);
        assert!(err.is_empty());
    }
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 2);
}

#[test]
fn malformed_cli_forms_and_missing_trust_save_nothing() {
    use std::os::unix::ffi::OsStringExt;
    let f = Fixture::new();
    for args in [
        vec![],
        vec!["off"],
        vec!["pause", "loop-syn-reminder"],
        vec!["on", "loop-syn-reminder", "extra"],
        vec!["off", "loop-syn-reminder", "--json", "--json"],
        vec!["off", " "],
    ] {
        let args: Vec<_> = args.into_iter().map(OsString::from).collect();
        assert_eq!(
            openwiz_cli::loops::run(
                &args,
                Some(&f.context),
                &FixedClock,
                &mut vec![],
                &mut vec![]
            ),
            2
        );
    }
    let args = [OsString::from("off"), OsString::from_vec(vec![0xff])];
    assert_eq!(
        openwiz_cli::loops::run(
            &args,
            Some(&f.context),
            &FixedClock,
            &mut vec![],
            &mut vec![]
        ),
        2
    );
    assert_eq!(
        openwiz_cli::loops::run(
            &["off", "loop-syn-reminder"].map(OsString::from),
            None,
            &FixedClock,
            &mut vec![],
            &mut vec![]
        ),
        1
    );
    assert!(!f.context.state.join("service/loops").exists());
    let mut out = vec![];
    assert_eq!(
        openwiz_cli::loops::run(
            &[OsString::from("--help")],
            None,
            &FixedClock,
            &mut out,
            &mut vec![]
        ),
        0
    );
    assert!(String::from_utf8(out).unwrap().contains("loop off <name>"));
}

#[test]
fn r1_cli_reports_a_running_pass_and_retry_without_writing() {
    use super::l6_switches::ExpiredClock;
    use openwiz_cli::state::loops::storage::Storage;
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let _lock = Storage::open(&f.context.state).unwrap();
    for command in ["off", "on"] {
        let mut out = vec![];
        let mut err = vec![];
        assert_eq!(
            openwiz_cli::loops::run(
                &[command, "loop-syn-reminder"].map(OsString::from),
                Some(&f.context),
                &ExpiredClock::new(),
                &mut out,
                &mut err
            ),
            1
        );
        let message = String::from_utf8(err).unwrap();
        assert!(
            message.contains("running") && message.contains("retry"),
            "{message}"
        );
        assert!(out.is_empty());
        assert_eq!(f.saved(), before);
    }
}
