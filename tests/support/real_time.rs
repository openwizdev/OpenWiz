//! Real-time proofs, in full or in their fast form (#1259, approved on the
//! ticket: option (a) of the builder's question, 2026-11-06).
//!
//! A few proofs must wait out real product limits (`RUN_BUDGET`,
//! `READ_TIMEOUT`), which no test can shorten. Each runs its fast form,
//! with the same logic assertions on shorter synthetic delays, only on the
//! first attempt of a pull request to `main` on GitHub Actions, read from
//! GitHub's own variables, each exactly. Everything else runs the full
//! real-time proof: a local run, a push to `main`, the nightly run, a rerun,
//! a pull request to `release-*`, a merge group, and any missing or odd
//! value. `OPENWIZ_TESTS_FULL`, set to anything, always selects the full
//! proofs.

#![allow(dead_code)]

use std::time::{Duration, Instant};

/// Which form a real-time proof runs in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Form {
    /// The real-time proof, with the product's real limits.
    Full,
    /// The same logic on shorter synthetic delays: a first-attempt pull
    /// request to `main` only.
    Fast,
}

/// The form for this run, from the environment.
pub fn form() -> Form {
    form_in(&|name| std::env::var_os(name).map(|v| v.to_string_lossy().into_owned()))
}

/// The form for an environment given as a lookup, so the rule is tested.
pub fn form_in(var: &dyn Fn(&str) -> Option<String>) -> Form {
    if var("OPENWIZ_TESTS_FULL").is_some() {
        return Form::Full;
    }
    let is = |name: &str, want: &str| var(name).as_deref() == Some(want);
    if is("GITHUB_ACTIONS", "true")
        && is("GITHUB_EVENT_NAME", "pull_request")
        && is("GITHUB_BASE_REF", "main")
        && is("GITHUB_RUN_ATTEMPT", "1")
    {
        Form::Fast
    } else {
        Form::Full
    }
}

/// `full` for the full proof, else `fast`; says on stderr which ran.
pub fn pick<T>(proof: &str, full: T, fast: T) -> T {
    match form() {
        Form::Full => full,
        Form::Fast => {
            eprintln!(
                "{proof}: fast form on a first-attempt pull request to main; the \
                 real-time proof runs in full everywhere else (#1259)"
            );
            fast
        }
    }
}

/// How many times its measured ordinary read a scaled duration allows.
pub const SLACK: u32 = 4;

/// `nominal`, or `SLACK` times `measured` when that is longer, never above
/// `cap` (#2645).
pub fn scale(nominal: Duration, measured: Duration, cap: Duration) -> Duration {
    nominal.max(measured.saturating_mul(SLACK)).min(cap)
}

/// A deadline or timeout with room for this host's load (#2645). A proof
/// holds one read until `nominal` runs out, and its other reads must still
/// finish inside it. On a loaded runner they can take longer than a short
/// synthetic duration allows. `calibrate` runs one ordinary, unheld read of
/// the same kind first, and the result is [`scale`] of its wall time. The
/// held read still waits out the whole duration, so a 503, 504 or timeout
/// still means a real deadline miss. `cap` keeps the duration below the
/// product limit that would change the outcome.
pub fn scaled(proof: &str, nominal: Duration, cap: Duration, calibrate: impl FnOnce()) -> Duration {
    let started = Instant::now();
    calibrate();
    let measured = started.elapsed();
    let duration = scale(nominal, measured, cap);
    eprintln!(
        "{proof}: {duration:?} (nominal {nominal:?}, an ordinary read took {measured:?}, \
         slack x{SLACK}, cap {cap:?}; #2645)"
    );
    duration
}

/// The scaling rule, on literal durations.
#[test]
fn a_scaled_duration_covers_the_measured_read_within_its_cap() {
    let ms = Duration::from_millis;
    let cases = [
        // (nominal, measured, cap, expected)
        (ms(2000), ms(0), ms(20000), ms(2000)),
        (ms(2000), ms(100), ms(20000), ms(2000)),
        (ms(2000), ms(500), ms(20000), ms(2000)),
        (ms(2000), ms(501), ms(20000), ms(2004)),
        (ms(2000), ms(1300), ms(20000), ms(5200)),
        (ms(2000), ms(9000), ms(20000), ms(20000)),
        (ms(1000), ms(250), ms(15000), ms(1000)),
        (ms(1000), ms(1000), ms(15000), ms(4000)),
        (ms(10000), ms(3000), ms(20000), ms(12000)),
        (ms(2000), Duration::MAX, ms(20000), ms(20000)),
    ];
    for (nominal, measured, cap, expected) in cases {
        assert_eq!(
            scale(nominal, measured, cap),
            expected,
            "{nominal:?} {measured:?} {cap:?}"
        );
    }
}

/// The context matrix: only the exact first-attempt pull request to `main`
/// gets the fast form.
#[test]
fn only_a_first_attempt_pull_request_to_main_gets_the_fast_form() {
    let pr = [
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_BASE_REF", "main"),
        ("GITHUB_RUN_ATTEMPT", "1"),
    ];
    let form_of = |vars: &[(&str, &str)]| {
        let vars: Vec<(String, String)> = vars
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        form_in(&|name| vars.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone()))
    };
    let with = |name: &str, value: Option<&str>| {
        let mut vars: Vec<(&str, &str)> = pr.iter().copied().filter(|(k, _)| *k != name).collect();
        if let Some(value) = value {
            vars.push((name, value));
        }
        form_of(&vars)
    };
    assert_eq!(form_of(&pr), Form::Fast, "a first-attempt PR to main");
    assert_eq!(form_of(&[]), Form::Full, "a local run");
    let mut full_too = pr.to_vec();
    full_too.push(("OPENWIZ_TESTS_FULL", ""));
    assert_eq!(form_of(&full_too), Form::Full, "an explicit full run wins");
    for (name, value) in [
        ("GITHUB_ACTIONS", None),
        ("GITHUB_ACTIONS", Some("false")),
        ("GITHUB_ACTIONS", Some("TRUE")),
        ("GITHUB_EVENT_NAME", None),
        ("GITHUB_EVENT_NAME", Some("push")),
        ("GITHUB_EVENT_NAME", Some("schedule")),
        ("GITHUB_EVENT_NAME", Some("workflow_dispatch")),
        ("GITHUB_EVENT_NAME", Some("merge_group")),
        ("GITHUB_EVENT_NAME", Some("pull_request_target")),
        ("GITHUB_EVENT_NAME", Some("Pull_request")),
        ("GITHUB_BASE_REF", None),
        ("GITHUB_BASE_REF", Some("")),
        ("GITHUB_BASE_REF", Some("release-0.0.7")),
        ("GITHUB_BASE_REF", Some("main-null")),
        ("GITHUB_BASE_REF", Some(" main")),
        ("GITHUB_RUN_ATTEMPT", None),
        ("GITHUB_RUN_ATTEMPT", Some("2")),
        ("GITHUB_RUN_ATTEMPT", Some("01")),
        ("GITHUB_RUN_ATTEMPT", Some("")),
    ] {
        assert_eq!(with(name, value), Form::Full, "{name}={value:?}");
    }
}
