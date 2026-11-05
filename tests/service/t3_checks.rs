//! Every check, through a run of passes: healthy (nothing due), broken (its
//! fix), broken after two tries (one "Needs you", then quiet), and fixed
//! (quiet again, then the incident ends). Then the rules around them:
//! a try still running, failed and interrupted tries, a fault back within
//! the hour, unknown and unread, gone subjects, the tick's schedule and the
//! takeover's second try.

use openwiz_core::health::model::{
    CloudRoomSeen, Gap, Known, Listed, Outcome, Seen, ServerBroken, ThreadSeen,
};
use openwiz_core::model::Timestamp;
use serde_json::{Value, json};

use super::{
    HOUR, LOOP_ID, LOOP_NAME, MINUTE, NEW_THREAD, Run, SPEC, T0, THREAD, assert_nothing_due, fixes,
    healthy, healthy_results, needs_you, results, seen_loop, seen_thread, text, unread,
};

/// When the stalled tick's run started: one schedule (300 s) before `T0`,
/// so from `T0` on its next run is due.
const RUN: i64 = T0 - 300_000;

/// One way one check can be broken.
struct Case {
    name: &'static str,
    /// Makes the healthy service's subject broken.
    break_it: fn(&mut Seen),
    /// The pass's results while it is broken.
    results: Value,
    /// The incident's check and subject fields.
    subject: Value,
    /// Its broken observation.
    broken: Value,
    /// The first try's fix, for `i1`. `None`: the check has no fix.
    fix: Option<Value>,
}

/// The healthy results with result `index` replaced.
fn with(replace: &[(usize, Value)]) -> Value {
    let mut all = healthy_results();
    for (index, value) in replace {
        all[*index] = value.clone();
    }
    all
}

fn the_loop() -> Value {
    json!({"id": "loop_syn_0001", "name": "launch-fleet synthetic-owner/synthetic-repo"})
}

fn cases() -> Vec<Case> {
    let server = |name, what: &str, broken: fn(&mut Seen)| Case {
        name,
        break_it: broken,
        results: with(&[(
            4,
            json!({"check": "server", "observed": {"state": "broken", "what": what}}),
        )]),
        subject: json!({"check": "server"}),
        broken: json!({"state": "broken", "what": what}),
        fix: Some(json!({"fix": "restart_server", "incident": "i1", "try": 1})),
    };
    let thread = |name, what: &str, broken: fn(&mut Seen)| Case {
        name,
        break_it: broken,
        results: with(&[(
            3,
            json!({"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "broken", "what": what}}),
        )]),
        subject: json!({"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201"}),
        broken: json!({"state": "broken", "what": what}),
        fix: Some(
            json!({"fix": "take_over_fleet_thread", "incident": "i1", "try": 1, "spec": 900, "thread": "thr_syn_0201"}),
        ),
    };
    vec![
        Case {
            name: "loop paused",
            break_it: |seen| seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]),
            results: with(&[(
                1,
                json!({"check": "loop", "loop": the_loop(), "observed": {"state": "broken", "what": "paused"}}),
            )]),
            subject: json!({"check": "loop", "loop": the_loop()}),
            broken: json!({"state": "broken", "what": "paused"}),
            fix: Some(
                json!({"fix": "resume_loop", "incident": "i1", "try": 1, "loop": the_loop()}),
            ),
        },
        Case {
            name: "tick stalled",
            break_it: |seen| seen.tick_running_since = Some(Timestamp(RUN)),
            results: with(&[(
                2,
                json!({"check": "tick", "observed": {"state": "broken", "what": "stalled", "run_started_at": RUN}}),
            )]),
            subject: json!({"check": "tick"}),
            broken: json!({"state": "broken", "what": "stalled", "run_started_at": RUN}),
            fix: Some(json!({"fix": "restart_tick", "incident": "i1", "try": 1})),
        },
        thread("fleet thread not found", "not_found", |seen| {
            seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::NotFound)])
        }),
        thread("fleet thread archived", "archived", |seen| {
            seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)])
        }),
        server("server refused", "refused", |seen| {
            seen.server = Known::Broken(ServerBroken::Refused)
        }),
        server("server timed out", "timed_out", |seen| {
            seen.server = Known::Broken(ServerBroken::TimedOut)
        }),
        server("server wrong answer", "wrong_answer", |seen| {
            seen.server = Known::Broken(ServerBroken::WrongAnswer)
        }),
        Case {
            name: "cloudroom not running",
            break_it: |seen| seen.cloudroom = CloudRoomSeen::NotRunning,
            results: with(&[
                (
                    0,
                    json!({"check": "cloudroom", "observed": {"state": "broken", "what": "not_running"}}),
                ),
                (
                    1,
                    json!({"check": "loop", "unread": {"gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so its loops can't be read"}}),
                ),
                (
                    3,
                    json!({"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "unknown", "gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so the thread can't be read"}}),
                ),
            ]),
            subject: json!({"check": "cloudroom"}),
            broken: json!({"state": "broken", "what": "not_running"}),
            fix: None,
        },
    ]
}

fn broken(case: &Case) -> Seen {
    let mut seen = healthy();
    (case.break_it)(&mut seen);
    seen
}

/// The case's fix for `incident` and `attempt`.
fn fix(case: &Case, incident: &str, attempt: u8) -> Value {
    let mut fix = case.fix.clone().expect("the check has a fix");
    fix["incident"] = json!(incident);
    fix["try"] = json!(attempt);
    fix
}

fn saved(at: i64, outcome: Value) -> Value {
    json!({"at": at, "outcome": outcome, "comment": null})
}

/// The case's incident, printed: `tries` as given (ignored when the check
/// has no fix), the rest from the arguments.
fn incident(
    case: &Case,
    id: &str,
    opened_at: i64,
    healthy_since: Value,
    tries: Value,
    needs: Value,
) -> Value {
    let mut incident = case.subject.clone();
    incident["id"] = json!(id);
    incident["opened_at"] = json!(opened_at);
    incident["broken"] = case.broken.clone();
    incident["healthy_since"] = healthy_since;
    if case.fix.is_some() {
        incident["tries"] = tries;
    }
    incident["needs_you"] = needs;
    incident
}

/// The outcome a settled try shows: a takeover's names its new thread.
fn done(case: &Case) -> Value {
    if case.subject["check"] == "fleet_thread" {
        json!({"state": "done", "thread": NEW_THREAD})
    } else {
        json!({"state": "done"})
    }
}

#[test]
fn t3_check_transitions_preserve_each_original_proof() {
    let cases: [(&str, fn()); 3] = [
        (
            "every_check_broken_gets_its_fix_twice_then_one_needs_you_then_quiet",
            every_check_broken_gets_its_fix_twice_then_one_needs_you_then_quiet,
        ),
        (
            "every_check_fixed_is_quiet_again",
            every_check_fixed_is_quiet_again,
        ),
        ("healthy_makes_nothing_due", healthy_makes_nothing_due),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: t3_planner::checks::{name}");
        proof();
    }
}

fn healthy_makes_nothing_due() {
    let mut run = Run::default();
    let pass = run.pass(&healthy(), T0);
    assert_eq!(results(&pass), healthy_results());
    assert_nothing_due(&pass, "healthy");
    assert_eq!(run.incidents_json(), json!([]));
    assert_eq!(run.incidents.next_incident.get(), 1);

    let pass = run.pass(&healthy(), T0 + MINUTE);
    assert_eq!(results(&pass), healthy_results());
    assert_nothing_due(&pass, "healthy again");
    assert_eq!(run.incidents_json(), json!([]));
}

/// Broken: its fix; still broken: the second try; then one "Needs you";
/// then quiet. Healthy for an hour: it ends; broken again: a new incident.
fn every_check_broken_gets_its_fix_twice_then_one_needs_you_then_quiet() {
    for case in cases() {
        let name = case.name;
        let mut run = Run::default();
        let seen = broken(&case);
        let p1 = T0 + MINUTE;

        assert_nothing_due(&run.pass(&healthy(), T0), name);

        // Broken: an incident opens, and its fix's first try is due.
        let pass = run.pass(&seen, p1);
        assert_eq!(
            results(&pass),
            case.results,
            "{name}: the broken pass's results"
        );
        let first = saved(p1, json!(null));
        if case.fix.is_some() {
            assert_eq!(
                fixes(&pass),
                json!([fix(&case, "i1", 1)]),
                "{name}: the first try"
            );
        } else {
            assert_eq!(fixes(&pass), json!([]), "{name}: no fix");
        }
        assert_eq!(needs_you(&pass), json!([]), "{name}: no Needs you yet");
        assert_eq!(
            run.incidents_json(),
            json!([incident(
                &case,
                "i1",
                p1,
                json!(null),
                json!({"first": first, "second": null}),
                json!(null)
            )]),
            "{name}: the opened incident"
        );
        assert_eq!(
            run.incidents.next_incident.get(),
            2,
            "{name}: next incident"
        );

        let p3 = if case.fix.is_some() {
            // Still broken while the first try runs: nothing is due.
            assert_nothing_due(&run.pass(&seen, p1 + MINUTE / 2), name);
            run.settle(&Outcome::Done);

            // Still broken: the second try.
            let p2 = p1 + MINUTE;
            let pass = run.pass(&seen, p2);
            assert_eq!(
                fixes(&pass),
                json!([fix(&case, "i1", 2)]),
                "{name}: the second try"
            );
            assert_eq!(needs_you(&pass), json!([]), "{name}: no Needs you yet");
            assert_eq!(
                run.incidents_json(),
                json!([incident(
                    &case,
                    "i1",
                    p1,
                    json!(null),
                    json!({"first": saved(p1, done(&case)), "second": saved(p2, json!(null))}),
                    json!(null)
                )]),
                "{name}: both tries saved"
            );

            assert_nothing_due(&run.pass(&seen, p2 + MINUTE / 2), name);
            run.settle(&Outcome::Done);
            p2 + MINUTE
        } else {
            p1 + MINUTE
        };

        // Still broken after its tries (or its first pass, with no fix):
        // one "Needs you".
        let pass = run.pass(&seen, p3);
        assert_eq!(fixes(&pass), json!([]), "{name}: no third try");
        assert_eq!(needs_you(&pass), json!(["i1"]), "{name}: one Needs you");
        let tries =
            json!({"first": saved(p1, done(&case)), "second": saved(p1 + MINUTE, done(&case))});
        let needs = json!({"at": p3, "op_id": "op-needs-you-1", "comment": null});
        assert_eq!(
            run.incidents_json(),
            json!([incident(
                &case,
                "i1",
                p1,
                json!(null),
                tries.clone(),
                needs.clone()
            )]),
            "{name}: the Needs you, saved"
        );

        // Then quiet, however long it stays broken.
        for k in 1..=3 {
            assert_nothing_due(&run.pass(&seen, p3 + k * MINUTE), name);
        }
        assert_nothing_due(&run.pass(&seen, p3 + 2 * HOUR), name);

        // Healthy: still open, quiet, until an hour after it was first seen
        // healthy.
        let p6 = p3 + 3 * HOUR;
        let pass = run.pass(&healthy(), p6);
        assert_eq!(results(&pass), healthy_results(), "{name}: healthy again");
        assert_nothing_due(&pass, name);
        assert_eq!(
            run.incidents_json(),
            json!([incident(
                &case,
                "i1",
                p1,
                json!(p6),
                tries.clone(),
                needs.clone()
            )]),
            "{name}: healthy since"
        );
        assert_nothing_due(&run.pass(&healthy(), p6 + HOUR - 1), name);
        assert_eq!(
            run.incidents.incidents.len(),
            1,
            "{name}: open until the hour is up"
        );
        assert_nothing_due(&run.pass(&healthy(), p6 + HOUR), name);
        assert_eq!(
            run.incidents_json(),
            json!([]),
            "{name}: the incident ended"
        );

        // Broken again, after it ended: a new incident, with its own tries.
        let p9 = p6 + HOUR + MINUTE;
        let pass = run.pass(&seen, p9);
        if case.fix.is_some() {
            assert_eq!(
                fixes(&pass),
                json!([fix(&case, "i2", 1)]),
                "{name}: a new first try"
            );
        } else {
            assert_eq!(fixes(&pass), json!([]), "{name}: no fix");
        }
        assert_eq!(
            needs_you(&pass),
            json!([]),
            "{name}: no Needs you for the new one"
        );
        assert_eq!(
            run.incidents_json(),
            json!([incident(
                &case,
                "i2",
                p9,
                json!(null),
                json!({"first": saved(p9, json!(null)), "second": null}),
                json!(null)
            )]),
            "{name}: the new incident"
        );
    }
}

/// Fixed by its first try: no second try and no "Needs you"; quiet, and
/// the incident ends an hour after it was first seen healthy.
fn every_check_fixed_is_quiet_again() {
    for case in cases() {
        let name = case.name;
        let mut run = Run::default();
        let p1 = T0;
        run.pass(&broken(&case), p1);
        run.settle(&Outcome::Done);

        let p2 = p1 + MINUTE;
        let pass = run.pass(&healthy(), p2);
        assert_eq!(results(&pass), healthy_results(), "{name}: fixed");
        assert_nothing_due(&pass, name);
        let first = if case.fix.is_some() {
            json!({"first": saved(p1, done(&case)), "second": null})
        } else {
            json!(null)
        };
        assert_eq!(
            run.incidents_json(),
            json!([incident(&case, "i1", p1, json!(p2), first, json!(null))]),
            "{name}: healthy since the fix"
        );

        for at in [p2 + MINUTE, p2 + 30 * MINUTE, p2 + HOUR - 1] {
            assert_nothing_due(&run.pass(&healthy(), at), name);
            assert_eq!(
                run.incidents.incidents.len(),
                1,
                "{name}: open within the hour"
            );
        }
        assert_nothing_due(&run.pass(&healthy(), p2 + HOUR), name);
        assert_eq!(
            run.incidents_json(),
            json!([]),
            "{name}: ended after the hour"
        );
        assert_nothing_due(&run.pass(&healthy(), p2 + HOUR + MINUTE), name);
        assert_eq!(
            run.incidents.next_incident.get(),
            2,
            "{name}: one incident in all"
        );
    }
}

/// A fault back within the hour is the same incident, with the tries it
/// already had.
#[test]
fn t3_incident_memory_preserves_each_original_proof() {
    let cases: [(&str, fn()); 4] = [
        (
            "a_fault_back_after_its_needs_you_stays_quiet",
            a_fault_back_after_its_needs_you_stays_quiet,
        ),
        (
            "a_fault_back_within_the_hour_is_the_same_incident",
            a_fault_back_within_the_hour_is_the_same_incident,
        ),
        (
            "a_gone_subject_ends_its_incident_only_when_its_list_was_read",
            a_gone_subject_ends_its_incident_only_when_its_list_was_read,
        ),
        (
            "unknown_and_unread_change_nothing",
            unknown_and_unread_change_nothing,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: t3_planner::checks::{name}");
        proof();
    }
}

fn a_fault_back_within_the_hour_is_the_same_incident() {
    for case in cases() {
        let name = case.name;
        let mut run = Run::default();
        let seen = broken(&case);
        let p1 = T0;
        run.pass(&seen, p1);
        run.settle(&Outcome::Done);
        run.pass(&healthy(), p1 + MINUTE);

        let p3 = p1 + MINUTE + 59 * MINUTE;
        let pass = run.pass(&seen, p3);
        if case.fix.is_some() {
            assert_eq!(
                fixes(&pass),
                json!([fix(&case, "i1", 2)]),
                "{name}: the second try"
            );
            assert_eq!(needs_you(&pass), json!([]), "{name}");
            let tries = json!({"first": saved(p1, done(&case)), "second": saved(p3, json!(null))});
            assert_eq!(
                run.incidents_json(),
                json!([incident(&case, "i1", p1, json!(null), tries, json!(null))]),
                "{name}: the same incident, healthy_since cleared"
            );
            run.settle(&Outcome::Done);
            let pass = run.pass(&seen, p3 + MINUTE);
            assert_eq!(fixes(&pass), json!([]), "{name}");
            assert_eq!(
                needs_you(&pass),
                json!(["i1"]),
                "{name}: then its Needs you"
            );
        } else {
            assert_eq!(fixes(&pass), json!([]), "{name}");
            assert_eq!(needs_you(&pass), json!(["i1"]), "{name}: its Needs you");
        }
        assert_nothing_due(&run.pass(&seen, p3 + 2 * MINUTE), name);
        assert_eq!(
            run.incidents.next_incident.get(),
            2,
            "{name}: still one incident"
        );
    }
}

/// A try counts once it is due and saved, whatever its outcome.
#[test]
fn t3_fix_records_preserve_each_original_proof() {
    let cases: [(&str, fn()); 9] = [
        (
            "a_renamed_loop_keeps_its_incident_under_its_new_name",
            a_renamed_loop_keeps_its_incident_under_its_new_name,
        ),
        (
            "a_server_incident_keeps_its_latest_broken_observation",
            a_server_incident_keeps_its_latest_broken_observation,
        ),
        (
            "a_takeovers_second_try_names_the_thread_last_found_gone",
            a_takeovers_second_try_names_the_thread_last_found_gone,
        ),
        (
            "a_try_with_no_outcome_makes_nothing_due",
            a_try_with_no_outcome_makes_nothing_due,
        ),
        (
            "cloudroom_down_hides_the_loops_and_threads",
            cloudroom_down_hides_the_loops_and_threads,
        ),
        (
            "failed_and_interrupted_tries_count",
            failed_and_interrupted_tries_count,
        ),
        (
            "no_incident_opens_once_the_numbers_run_out",
            no_incident_opens_once_the_numbers_run_out,
        ),
        (
            "the_tick_is_stalled_once_its_next_run_is_due",
            the_tick_is_stalled_once_its_next_run_is_due,
        ),
        (
            "two_broken_subjects_get_one_incident_each",
            two_broken_subjects_get_one_incident_each,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: t3_planner::checks::{name}");
        proof();
    }
}

fn failed_and_interrupted_tries_count() {
    for case in cases().into_iter().filter(|case| case.fix.is_some()) {
        let name = case.name;
        let mut run = Run::default();
        let seen = broken(&case);
        run.pass(&seen, T0);
        run.settle(&Outcome::Failed {
            gap: Gap::CommandFailed,
            reason: text("room-cli refused"),
        });
        let pass = run.pass(&seen, T0 + MINUTE);
        assert_eq!(
            fixes(&pass),
            json!([fix(&case, "i1", 2)]),
            "{name}: a failed first try counts"
        );
        run.settle(&Outcome::Interrupted);
        let pass = run.pass(&seen, T0 + 2 * MINUTE);
        assert_eq!(fixes(&pass), json!([]), "{name}: no third try");
        assert_eq!(
            needs_you(&pass),
            json!(["i1"]),
            "{name}: an interrupted second try counts"
        );
        let failed =
            json!({"state": "failed", "gap": "command_failed", "reason": "room-cli refused"});
        assert_eq!(
            run.incidents_json()[0]["tries"],
            json!({"first": saved(T0, failed), "second": saved(T0 + MINUTE, json!({"state": "interrupted"}))}),
            "{name}: both outcomes kept"
        );
    }
}

/// The tick is stalled when a run is still going at its next run's time,
/// `tick.every_s` after it started, and not a millisecond before.
fn the_tick_is_stalled_once_its_next_run_is_due() {
    let stalled = |started: i64| json!({"check": "tick", "observed": {"state": "broken", "what": "stalled", "run_started_at": started}});
    let healthy_tick = json!({"check": "tick", "observed": {"state": "healthy"}});
    for (started, expected) in [
        (T0 - 299_999, healthy_tick.clone()),
        (T0 - 300_000, stalled(T0 - 300_000)),
        (T0 - 300_001, stalled(T0 - 300_001)),
        (T0 - 3 * HOUR, stalled(T0 - 3 * HOUR)),
        (T0, healthy_tick.clone()),
    ] {
        let mut seen = healthy();
        seen.tick_running_since = Some(Timestamp(started));
        let pass = Run::default().pass(&seen, T0);
        assert_eq!(results(&pass)[2], expected, "a run started at {started}");
    }
    let pass = Run::default().pass(&healthy(), T0);
    assert_eq!(results(&pass)[2], healthy_tick, "no run going");
}

/// Unknown or unread: no try is due, nothing heals and nothing ends.
fn unknown_and_unread_change_nothing() {
    // Unknown opens nothing.
    let mut seen = healthy();
    seen.fleet_threads = Listed::Read(vec![seen_thread(
        SPEC,
        THREAD,
        ThreadSeen::Unknown(unread(Gap::TimedOut, "thread show didn't answer in time")),
    )]);
    let mut run = Run::default();
    let pass = run.pass(&seen, T0);
    assert_eq!(
        results(&pass)[3],
        json!({"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "unknown", "gap": "timed_out", "reason": "thread show didn't answer in time"}})
    );
    assert_nothing_due(&pass, "unknown");
    assert_eq!(run.incidents_json(), json!([]), "unknown opens no incident");

    // A paused loop and an archived fleet thread, each with its first try.
    let mut broken = healthy();
    broken.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]);
    broken.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)]);
    let mut run = Run::default();
    run.pass(&broken, T0);
    run.settle(&Outcome::Done);
    let before = run.incidents_json();
    assert_eq!(run.incidents.incidents.len(), 2);

    // The loop list unread, the thread unknown: nothing changes.
    let mut blind = broken.clone();
    blind.loops = Listed::Unread(unread(Gap::CommandFailed, "room-cli loop list failed"));
    blind.fleet_threads = Listed::Read(vec![seen_thread(
        SPEC,
        THREAD,
        ThreadSeen::Unknown(unread(Gap::CommandFailed, "thread show failed")),
    )]);
    let pass = run.pass(&blind, T0 + MINUTE);
    assert_eq!(
        results(&pass)[1],
        json!({"check": "loop", "unread": {"gap": "command_failed", "reason": "room-cli loop list failed"}})
    );
    assert_nothing_due(&pass, "unread and unknown");
    assert_eq!(
        run.incidents_json(),
        before,
        "unread and unknown change nothing"
    );

    // The specs' records unread: nothing changes either.
    let mut blind = broken.clone();
    blind.fleet_threads = Listed::Unread(unread(
        Gap::CommandFailed,
        "the specs' records couldn't be read",
    ));
    let pass = run.pass(&blind, T0 + 2 * MINUTE);
    assert_eq!(
        results(&pass),
        with(&[
            (
                1,
                json!({"check": "loop", "loop": the_loop(), "observed": {"state": "broken", "what": "paused"}})
            ),
            (
                3,
                json!({"check": "fleet_thread", "unread": {"gap": "command_failed", "reason": "the specs' records couldn't be read"}})
            ),
        ])
    );
    // The loop is still broken: its second try.
    assert_eq!(
        fixes(&pass),
        json!([{"fix": "resume_loop", "incident": "i1", "try": 2, "loop": the_loop()}])
    );
    assert_eq!(
        run.incidents_json()[1],
        before[1],
        "the thread's incident is unchanged"
    );

    // Healthy, then unknown for hours: unknown never ends it; the next
    // healthy pass an hour after healthy_since does.
    let mut run = Run::default();
    let mut thread_broken = healthy();
    thread_broken.fleet_threads =
        Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)]);
    run.pass(&thread_broken, T0);
    run.settle(&Outcome::Done);
    run.pass(&healthy(), T0 + MINUTE);
    assert_eq!(run.incidents_json()[0]["healthy_since"], json!(T0 + MINUTE));
    let mut unknown = healthy();
    unknown.fleet_threads = Listed::Read(vec![seen_thread(
        SPEC,
        THREAD,
        ThreadSeen::Unknown(unread(Gap::TimedOut, "thread show didn't answer in time")),
    )]);
    for at in [T0 + HOUR, T0 + 2 * HOUR, T0 + 3 * HOUR] {
        assert_nothing_due(&run.pass(&unknown, at), "unknown");
        assert_eq!(run.incidents.incidents.len(), 1, "unknown ends nothing");
        assert_eq!(
            run.incidents_json()[0]["healthy_since"],
            json!(T0 + MINUTE),
            "nor heals"
        );
    }
    assert_nothing_due(&run.pass(&healthy(), T0 + 3 * HOUR + MINUTE), "healthy");
    assert_eq!(run.incidents_json(), json!([]), "the healthy pass ends it");
}

/// While CloudRoom isn't running, a paused loop and a gone fleet thread are
/// unread and unknown: only CloudRoom's incident opens.
fn cloudroom_down_hides_the_loops_and_threads() {
    let mut seen = healthy();
    seen.cloudroom = CloudRoomSeen::NotRunning;
    seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]);
    seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)]);
    let mut run = Run::default();
    let pass = run.pass(&seen, T0);
    assert_eq!(
        results(&pass),
        with(&[
            (
                0,
                json!({"check": "cloudroom", "observed": {"state": "broken", "what": "not_running"}})
            ),
            (
                1,
                json!({"check": "loop", "unread": {"gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so its loops can't be read"}}),
            ),
            (
                3,
                json!({"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "unknown", "gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so the thread can't be read"}}),
            ),
        ])
    );
    assert_nothing_due(&pass, "CloudRoom down");
    assert_eq!(
        run.incidents_json(),
        json!([{"id": "i1", "check": "cloudroom", "opened_at": T0, "broken": {"state": "broken", "what": "not_running"}, "healthy_since": null, "needs_you": null}])
    );
}

/// A subject that is gone ends its incident, but only when its check's
/// list was read in full.
fn a_gone_subject_ends_its_incident_only_when_its_list_was_read() {
    let mut broken = healthy();
    broken.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]);
    broken.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::NotFound)]);
    let start = || {
        let mut run = Run::default();
        run.pass(&broken, T0);
        run.settle(&Outcome::Done);
        assert_eq!(run.incidents.incidents.len(), 2);
        run
    };
    let check_of = |run: &Run| -> Vec<String> {
        run.incidents_json()
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i["check"].as_str().unwrap().to_owned())
            .collect()
    };

    // The loop list, read in full, without the loop: its incident ends.
    let mut run = start();
    let mut gone = broken.clone();
    gone.loops = Listed::Read(vec![]);
    let pass = run.pass(&gone, T0 + MINUTE);
    assert_eq!(results(&pass)[1]["check"], "tick", "no loop result");
    assert_eq!(
        check_of(&run),
        ["fleet_thread"],
        "the loop's incident ended"
    );

    // The spec closed (its records read in full, without it): its
    // incident ends, even while CloudRoom is down.
    let mut run = start();
    let mut gone = broken.clone();
    gone.fleet_threads = Listed::Read(vec![]);
    run.pass(&gone, T0 + MINUTE);
    assert_eq!(check_of(&run), ["loop"], "the thread's incident ended");
    let mut run = start();
    let mut gone = broken.clone();
    gone.cloudroom = CloudRoomSeen::NotRunning;
    gone.fleet_threads = Listed::Read(vec![]);
    run.pass(&gone, T0 + MINUTE);
    assert_eq!(
        check_of(&run),
        ["loop", "cloudroom"],
        "the closed spec's ended, the loop's stayed"
    );

    // Unread: nothing ends.
    let mut run = start();
    let mut blind = broken.clone();
    blind.loops = Listed::Unread(unread(Gap::Malformed, "room-cli loop list wasn't JSON"));
    blind.fleet_threads = Listed::Unread(unread(
        Gap::CommandFailed,
        "the specs' records couldn't be read",
    ));
    run.pass(&blind, T0 + MINUTE);
    assert_eq!(
        check_of(&run),
        ["loop", "fleet_thread"],
        "unread ends nothing"
    );
}

/// A takeover's second try names the fleet thread last found gone: the one
/// the spec's records name now.
fn a_takeovers_second_try_names_the_thread_last_found_gone() {
    let mut run = Run::default();
    let mut seen = healthy();
    seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)]);
    run.pass(&seen, T0);
    run.settle(&Outcome::Done);

    // The records now name the new thread, and it is gone too.
    seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, NEW_THREAD, ThreadSeen::NotFound)]);
    let pass = run.pass(&seen, T0 + MINUTE);
    assert_eq!(
        fixes(&pass),
        json!([{"fix": "take_over_fleet_thread", "incident": "i1", "try": 2, "spec": 900, "thread": "thr_syn_0202"}])
    );
    let incident = &run.incidents_json()[0];
    assert_eq!(
        incident["thread"], "thr_syn_0202",
        "the thread last found gone"
    );
    assert_eq!(
        incident["broken"],
        json!({"state": "broken", "what": "not_found"}),
        "its latest broken observation"
    );
    assert_eq!(
        incident["tries"]["first"]["outcome"],
        json!({"state": "done", "thread": "thr_syn_0202"})
    );
}

/// A server's next broken observation refreshes the same incident, keeping
/// its opening time and the first try's outcome (service contract, The state).
fn a_server_incident_keeps_its_latest_broken_observation() {
    let mut run = Run::default();
    let mut seen = healthy();
    seen.server = Known::Broken(ServerBroken::Refused);
    run.pass(&seen, T0);
    let first = run.incidents_json();
    assert_eq!(first.as_array().unwrap().len(), 1);
    assert_eq!(first[0]["id"], "i1");
    assert_eq!(
        first[0]["broken"],
        json!({"state": "broken", "what": "refused"})
    );
    run.settle(&Outcome::Done);

    seen.server = Known::Broken(ServerBroken::TimedOut);
    let pass = run.pass(&seen, T0 + MINUTE);
    assert_eq!(
        fixes(&pass),
        json!([{"fix": "restart_server", "incident": "i1", "try": 2}])
    );
    assert_eq!(
        run.incidents_json(),
        json!([{
            "id": "i1", "check": "server", "opened_at": T0,
            "broken": {"state": "broken", "what": "timed_out"},
            "healthy_since": null,
            "tries": {
                "first": {"at": T0, "outcome": {"state": "done"}, "comment": null},
                "second": {"at": T0 + MINUTE, "outcome": null, "comment": null}
            },
            "needs_you": null
        }])
    );
    assert_eq!(run.incidents.next_incident.get(), 2, "the same incident");
}

/// Two subjects broken in one pass: one incident each, numbered in the
/// results' order, and one fix each.
fn two_broken_subjects_get_one_incident_each() {
    let mut seen = healthy();
    seen.tick_running_since = Some(Timestamp(RUN));
    seen.server = Known::Broken(ServerBroken::Refused);
    seen.fleet_threads = Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Archived)]);
    let mut run = Run::default();
    let pass = run.pass(&seen, T0);
    assert_eq!(
        fixes(&pass),
        json!([
            {"fix": "restart_tick", "incident": "i1", "try": 1},
            {"fix": "take_over_fleet_thread", "incident": "i2", "try": 1, "spec": 900, "thread": "thr_syn_0201"},
            {"fix": "restart_server", "incident": "i3", "try": 1}
        ])
    );
    assert_eq!(run.incidents.next_incident.get(), 4);
}

/// After its "Needs you", a fault back within the hour is the same
/// incident, and stays quiet: no third try, no second "Needs you" (S4).
fn a_fault_back_after_its_needs_you_stays_quiet() {
    for case in cases() {
        let name = case.name;
        let mut run = Run::default();
        let seen = broken(&case);
        let mut at = T0;
        loop {
            let pass = run.pass(&seen, at);
            run.settle(&Outcome::Done);
            at += MINUTE;
            if needs_you(&pass) == json!(["i1"]) {
                break;
            }
            assert!(
                at < T0 + 10 * MINUTE,
                "{name}: a Needs you within a few passes"
            );
        }
        let before = run.incidents_json();

        assert_nothing_due(&run.pass(&healthy(), at), name);
        assert_eq!(
            run.incidents_json()[0]["healthy_since"],
            json!(at),
            "{name}"
        );
        for k in 1..=3 {
            let pass = run.pass(&seen, at + 30 * MINUTE + k * MINUTE);
            assert_nothing_due(&pass, name);
        }
        assert_eq!(
            run.incidents_json(),
            before,
            "{name}: the same incident, its tries and its Needs you"
        );
        assert_eq!(
            run.incidents.next_incident.get(),
            2,
            "{name}: no new incident"
        );
    }
}

/// Once no number is left for a new incident, none opens and nothing is
/// due: an incident's id is always below `next_incident` (S2).
fn no_incident_opens_once_the_numbers_run_out() {
    let mut seen = healthy();
    seen.server = Known::Broken(ServerBroken::Refused);
    let mut run = Run::from(openwiz_core::health::model::Incidents {
        next_incident: super::number(u64::MAX),
        incidents: vec![],
    });
    for k in 0..3 {
        assert_nothing_due(&run.pass(&seen, T0 + k * MINUTE), "no number left");
        assert_eq!(run.incidents_json(), json!([]));
        assert_eq!(run.incidents.next_incident.get(), u64::MAX);
    }
}

/// A loop renamed while it stays OpenWiz's and broken is the same subject,
/// by its id: the incident and its second try carry the name it has now.
fn a_renamed_loop_keeps_its_incident_under_its_new_name() {
    let renamed = "launch-fleet synthetic-owner/synthetic-repo (PC hub)";
    let mut run = Run::default();
    let mut seen = healthy();
    seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]);
    run.pass(&seen, T0);
    run.settle(&Outcome::Done);

    seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, renamed, true)]);
    let pass = run.pass(&seen, T0 + MINUTE);
    let the_loop = json!({"id": "loop_syn_0001", "name": renamed});
    assert_eq!(
        fixes(&pass),
        json!([{"fix": "resume_loop", "incident": "i1", "try": 2, "loop": the_loop}])
    );
    assert_eq!(
        run.incidents_json()[0]["loop"],
        the_loop,
        "the incident names it as it is now"
    );
    assert_eq!(run.incidents.next_incident.get(), 2, "the same incident");
}

/// A try saved with no outcome makes nothing due, whichever try it is,
/// even in a state the planner itself never writes (a first try with no
/// outcome beside a second).
fn a_try_with_no_outcome_makes_nothing_due() {
    use openwiz_core::health::model::{Fault, Incident, IncidentId, Incidents, SavedTry, Tries};
    let saved = |at: i64, outcome: Option<Outcome>| SavedTry {
        at: Timestamp(at),
        outcome,
        comment: None,
    };
    for tries in [
        Tries::One(saved(T0, None)),
        Tries::Two(saved(T0, Some(Outcome::Done)), saved(T0 + MINUTE, None)),
        Tries::Two(saved(T0, None), saved(T0 + MINUTE, Some(Outcome::Done))),
        Tries::Two(saved(T0, None), saved(T0 + MINUTE, None)),
    ] {
        let mut run = Run::from(Incidents {
            next_incident: super::number(2),
            incidents: vec![Incident {
                id: IncidentId(super::number(1)),
                fault: Fault::Server {
                    broken: ServerBroken::Refused,
                    tries: tries.clone(),
                },
                opened_at: Timestamp(T0),
                healthy_since: None,
                needs_you: None,
            }],
        });
        let mut seen = healthy();
        seen.server = Known::Broken(ServerBroken::Refused);
        let before = run.incidents_json();
        let pass = run.pass(&seen, T0 + 2 * MINUTE);
        assert_nothing_due(&pass, &format!("{tries:?}"));
        assert_eq!(run.incidents_json(), before, "{tries:?}: nothing saved");
    }
}
