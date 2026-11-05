//! Nothing outside OpenWiz's own loops and fleet threads is ever a fix
//! (#268's second acceptance criterion). A loop is OpenWiz's only by the
//! contract's rule ("OpenWiz's loops"), and a fleet thread only when an open
//! spec's records name it. Every other loop is never a subject: it gets no
//! result, no incident and no fix, and never shows in the plan.

use openwiz_core::health::is_openwiz_loop;
use openwiz_core::health::model::{
    CloudRoomSeen, Gap, Known, Listed, Outcome, Seen, ServerBroken, ThreadSeen,
};
use openwiz_core::model::Timestamp;
use serde_json::json;

use super::{
    LOOP_ID, LOOP_NAME, MINUTE, Run, SPEC, T0, THREAD, assert_nothing_due, contract_text, fixes,
    healthy, needs_you, repository, results, seen_loop, seen_thread,
};

/// The contract's table of loop names, with the repository
/// `synthetic-owner/synthetic-repo`, row by row.
const CONTRACT_NAMES: [(&str, bool); 9] = [
    ("launch-fleet synthetic-owner/synthetic-repo", true),
    ("launch-fleet synthetic-owner/synthetic-repo (PC hub)", true),
    ("launch-fleet #900 synthetic-owner/synthetic-repo", true),
    ("launch-fleet synthetic-owner/other-repo", false),
    ("launch-fleet synthetic-owner/synthetic-repo-2", false),
    ("launch-fleet synthetic-owner/Synthetic-Repo", false),
    ("Launch-fleet synthetic-owner/synthetic-repo", false),
    ("nightly launch-fleet synthetic-owner/synthetic-repo", false),
    ("launch-fleet", false),
];

/// More names, by the same rule: it starts `launch-fleet ` (a space, not
/// another blank), and one word, split at each space, is exactly the
/// repository.
const MORE_NAMES: [(&str, bool); 9] = [
    ("launch-fleet  synthetic-owner/synthetic-repo", true),
    ("launch-fleet synthetic-owner/synthetic-repo nightly", true),
    ("launch-fleet\tsynthetic-owner/synthetic-repo", false),
    (" launch-fleet synthetic-owner/synthetic-repo", false),
    ("launch-fleet synthetic-owner/synthetic-repo\u{a0}", false),
    ("launch-fleet synthetic-owner/synthetic-repo/x", false),
    ("launch-fleet other-owner/synthetic-repo", false),
    ("launch-fleet (synthetic-owner/synthetic-repo)", false),
    ("", false),
];

/// The test's table is the contract's: each row is there, and the
/// contract's table has no other row.
#[test]
fn t3_owned_subjects_preserve_each_original_proof() {
    let cases: [(&str, fn()); 6] = [
        (
            "a_list_that_names_one_subject_twice_is_unread",
            a_list_that_names_one_subject_twice_is_unread,
        ),
        (
            "a_loop_that_stops_being_openwiz_is_dropped",
            a_loop_that_stops_being_openwiz_is_dropped,
        ),
        (
            "among_many_paused_loops_only_openwiz_ones_get_fixes",
            among_many_paused_loops_only_openwiz_ones_get_fixes,
        ),
        (
            "every_fix_in_every_combination_is_for_openwiz_own",
            every_fix_in_every_combination_is_for_openwiz_own,
        ),
        (
            "only_openwiz_loop_names_are_openwiz_loops",
            only_openwiz_loop_names_are_openwiz_loops,
        ),
        (
            "the_names_are_the_contracts_table",
            the_names_are_the_contracts_table,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: t3_planner::owned::{name}");
        proof();
    }
}

fn the_names_are_the_contracts_table() {
    let contract = contract_text();
    let start = contract
        .find("| Loop name | OpenWiz's? |")
        .expect("the contract's table of loop names");
    let rows: Vec<&str> = contract[start..]
        .lines()
        .skip(2)
        .take_while(|line| line.starts_with('|'))
        .collect();
    assert_eq!(
        rows.len(),
        CONTRACT_NAMES.len(),
        "the contract's rows: {rows:#?}"
    );
    for ((name, ours), row) in CONTRACT_NAMES.iter().zip(&rows) {
        let verdict = if *ours { "Yes" } else { "No" };
        assert!(
            row.starts_with(&format!("| `{name}` | {verdict}")),
            "the contract's row {row:?} isn't {name:?}: {verdict}"
        );
    }
}

fn only_openwiz_loop_names_are_openwiz_loops() {
    for (name, ours) in CONTRACT_NAMES.iter().chain(&MORE_NAMES) {
        assert_eq!(is_openwiz_loop(name, &repository()), *ours, "{name:?}");
    }
}

/// A paused loop of each name, alone in the loop list: OpenWiz's is
/// resumed; any other gets no result, no incident and no fix, and its id
/// and name never show in the plan.
#[test]
fn a_paused_loop_that_isnt_openwiz_is_never_a_subject() {
    let loop_id = "loop_syn_0009";
    for (name, ours) in CONTRACT_NAMES.iter().chain(&MORE_NAMES) {
        let mut seen = healthy();
        seen.loops = Listed::Read(vec![seen_loop(loop_id, name, true)]);
        let mut run = Run::default();
        for k in 0..4 {
            let pass = run.pass(&seen, T0 + k * MINUTE);
            run.settle(&Outcome::Done);
            if *ours {
                let the_loop = json!({"id": loop_id, "name": name});
                assert_eq!(
                    results(&pass)[1],
                    json!({"check": "loop", "loop": the_loop, "observed": {"state": "broken", "what": "paused"}}),
                    "{name:?}"
                );
                let expected = match k {
                    0 | 1 => {
                        json!([{"fix": "resume_loop", "incident": "i1", "try": k + 1, "loop": the_loop}])
                    }
                    _ => json!([]),
                };
                assert_eq!(fixes(&pass), expected, "{name:?}, pass {k}");
            } else {
                assert_eq!(
                    results(&pass).as_array().unwrap().len(),
                    4,
                    "{name:?}: no loop result"
                );
                assert!(
                    results(&pass)
                        .as_array()
                        .unwrap()
                        .iter()
                        .all(|r| r["check"] != "loop"),
                    "{name:?}: no loop result"
                );
                assert_nothing_due(&pass, name);
                assert_eq!(run.incidents_json(), json!([]), "{name:?}: no incident");
                let printed = format!("{}{}", json_of!(&pass), run.incidents_json());
                assert!(
                    !printed.contains(loop_id),
                    "{name:?}: its id shows: {printed}"
                );
                if !name.is_empty() {
                    assert!(
                        !printed.contains(name),
                        "{name:?}: its name shows: {printed}"
                    );
                }
            }
        }
    }
}

/// Every loop of the table paused at once: only OpenWiz's three are
/// resumed, each twice, then each gets its "Needs you"; the others never
/// show.
fn among_many_paused_loops_only_openwiz_ones_get_fixes() {
    let ids: Vec<String> = (0..CONTRACT_NAMES.len())
        .map(|k| format!("loop_syn_01{k:02}"))
        .collect();
    let mut seen = healthy();
    seen.loops = Listed::Read(
        CONTRACT_NAMES
            .iter()
            .zip(&ids)
            .map(|((name, _), id)| seen_loop(id, name, true))
            .collect(),
    );
    let ours: Vec<serde_json::Value> = CONTRACT_NAMES
        .iter()
        .zip(&ids)
        .filter(|((_, ours), _)| *ours)
        .map(|((name, _), id)| json!({"id": id, "name": name}))
        .collect();
    assert_eq!(ours.len(), 3);
    let mut run = Run::default();
    for (k, attempt) in [(0, Some(1)), (1, Some(2)), (2, None), (3, None)] {
        let pass = run.pass(&seen, T0 + k * MINUTE);
        run.settle(&Outcome::Done);
        let loop_results: Vec<_> = results(&pass)
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["check"] == "loop")
            .map(|r| r["loop"].clone())
            .collect();
        assert_eq!(
            loop_results, ours,
            "pass {k}: a result for each of OpenWiz's loops only"
        );
        let expected: Vec<_> = match attempt {
            Some(attempt) => ours
                .iter()
                .enumerate()
                .map(|(n, the_loop)| json!({"fix": "resume_loop", "incident": format!("i{}", n + 1), "try": attempt, "loop": the_loop}))
                .collect(),
            None => vec![],
        };
        assert_eq!(fixes(&pass), json!(expected), "pass {k}");
        let expected_needs = if k == 2 {
            json!(["i1", "i2", "i3"])
        } else {
            json!([])
        };
        assert_eq!(needs_you(&pass), expected_needs, "pass {k}");
        let printed = format!("{}{}", json_of!(&pass), run.incidents_json());
        for ((name, ours), id) in CONTRACT_NAMES.iter().zip(&ids) {
            if !ours {
                assert!(
                    !printed.contains(id.as_str()),
                    "pass {k}: {name:?}'s id shows"
                );
            }
        }
    }
}

/// A loop renamed so it is no longer OpenWiz's is gone: its incident ends,
/// and it gets no more tries.
fn a_loop_that_stops_being_openwiz_is_dropped() {
    let mut seen = healthy();
    seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, true)]);
    let mut run = Run::default();
    run.pass(&seen, T0);
    run.settle(&Outcome::Done);
    assert_eq!(run.incidents.incidents.len(), 1);

    let renamed = "launch-fleet synthetic-owner/other-repo";
    seen.loops = Listed::Read(vec![seen_loop(LOOP_ID, renamed, true)]);
    for k in 1..4 {
        let pass = run.pass(&seen, T0 + k * MINUTE);
        assert_nothing_due(&pass, "renamed");
        assert_eq!(run.incidents_json(), json!([]), "its incident ended");
        let printed = json_of!(&pass).to_string();
        assert!(
            !printed.contains(LOOP_ID) && !printed.contains(renamed),
            "{printed}"
        );
    }
}

/// Two loops that share one id make the list malformed, so the check is
/// unread and nothing is resumed, whoever's they are; likewise two
/// records for one spec.
fn a_list_that_names_one_subject_twice_is_unread() {
    let other = "launch-fleet synthetic-owner/other-repo";
    for loops in [
        vec![
            seen_loop(LOOP_ID, LOOP_NAME, true),
            seen_loop(LOOP_ID, LOOP_NAME, true),
        ],
        vec![
            seen_loop(LOOP_ID, other, false),
            seen_loop(LOOP_ID, LOOP_NAME, true),
        ],
        vec![
            seen_loop(LOOP_ID, LOOP_NAME, true),
            seen_loop(LOOP_ID, other, true),
        ],
    ] {
        let mut seen = healthy();
        seen.loops = Listed::Read(loops);
        let mut run = Run::default();
        let pass = run.pass(&seen, T0);
        assert_eq!(
            results(&pass)[1],
            json!({"check": "loop", "unread": {"gap": "malformed", "reason": "room-cli loop list named one loop id twice"}})
        );
        assert_nothing_due(&pass, "one id twice");
        assert_eq!(run.incidents_json(), json!([]));
    }

    let mut seen = healthy();
    seen.fleet_threads = Listed::Read(vec![
        seen_thread(SPEC, THREAD, ThreadSeen::Archived),
        seen_thread(SPEC, "thr_syn_0299", ThreadSeen::NotFound),
    ]);
    let mut run = Run::default();
    let pass = run.pass(&seen, T0);
    assert_eq!(
        results(&pass)[3],
        json!({"check": "fleet_thread", "unread": {"gap": "malformed", "reason": "the open specs' records named one spec twice"}})
    );
    assert_nothing_due(&pass, "one spec twice");
    assert_eq!(run.incidents_json(), json!([]));
}

/// Every combination of what a pass can see, each through four passes from
/// no incidents (its first try, its second, its "Needs you", then quiet):
/// each fix is one of the four, and each fix's subject is one this pass saw
/// as OpenWiz's (`Run::pass` checks it, on every pass of every test).
fn every_fix_in_every_combination_is_for_openwiz_own() {
    let foreign = "launch-fleet synthetic-owner/other-repo";
    let mut passes = 0;
    let mut kinds = std::collections::BTreeSet::new();
    for cloudroom in [CloudRoomSeen::Running, CloudRoomSeen::NotRunning] {
        for loops in [
            vec![seen_loop(LOOP_ID, LOOP_NAME, false)],
            vec![seen_loop(LOOP_ID, LOOP_NAME, true)],
            vec![
                seen_loop("loop_syn_0009", foreign, true),
                seen_loop(LOOP_ID, LOOP_NAME, false),
            ],
            vec![
                seen_loop("loop_syn_0009", foreign, true),
                seen_loop(LOOP_ID, LOOP_NAME, true),
            ],
        ] {
            for tick in [None, Some(Timestamp(T0 - 600_000))] {
                for thread in [
                    ThreadSeen::Present,
                    ThreadSeen::NotFound,
                    ThreadSeen::Archived,
                    ThreadSeen::Unknown(super::unread(Gap::CommandFailed, "thread show failed")),
                ] {
                    for server in [
                        Known::Healthy,
                        Known::Broken(ServerBroken::Refused),
                        Known::Broken(ServerBroken::TimedOut),
                        Known::Broken(ServerBroken::WrongAnswer),
                    ] {
                        let seen = Seen {
                            cloudroom,
                            loops: Listed::Read(loops.clone()),
                            tick_running_since: tick,
                            fleet_threads: Listed::Read(vec![seen_thread(
                                SPEC,
                                THREAD,
                                thread.clone(),
                            )]),
                            server,
                        };
                        let mut run = Run::default().without_schema();
                        for k in 0..4 {
                            let pass = run.pass(&seen, T0 + k * MINUTE);
                            for fix in fixes(&pass).as_array().unwrap() {
                                kinds.insert(fix["fix"].as_str().unwrap().to_owned());
                            }
                            run.settle(&Outcome::Done);
                            let printed = format!("{}{}", json_of!(&pass), run.incidents_json());
                            assert!(
                                !printed.contains("loop_syn_0009"),
                                "the foreign loop shows: {printed}"
                            );
                            assert!(
                                !printed.contains(foreign),
                                "the foreign loop shows: {printed}"
                            );
                            passes += 1;
                        }
                    }
                }
            }
        }
    }
    assert_eq!(passes, 2 * 4 * 2 * 4 * 4 * 4);
    // The sweep reaches every fix, so its checks aren't vacuous.
    assert_eq!(
        kinds.into_iter().collect::<Vec<_>>(),
        [
            "restart_server",
            "restart_tick",
            "resume_loop",
            "take_over_fleet_thread"
        ]
    );
}
