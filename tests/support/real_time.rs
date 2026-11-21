#![allow(
    dead_code,
    reason = "included by more than one test target, and each uses only part of it"
)]

use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Form {
    Full,
    Fast,
}

pub fn form() -> Form {
    form_in(&|name| std::env::var_os(name).map(|v| v.to_string_lossy().into_owned()))
}

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

pub const SLACK: u32 = 4;

pub fn scale(nominal: Duration, measured: Duration, cap: Duration) -> Duration {
    nominal.max(measured.saturating_mul(SLACK)).min(cap)
}

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
