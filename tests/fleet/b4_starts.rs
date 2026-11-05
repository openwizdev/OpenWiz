//! Spec 2's B4 (ClosedWiz#120): starting builders and reviewers through
//! 0.0.4's `new_thread`, never two for one start, and archiving finished
//! agents.
//!
//! **S2-2, never two builders per ticket** (the ticket's one acceptance
//! criterion, on fixtures): a crash between the start and its record, and
//! a timed-out start, each end with exactly one builder: the fake's
//! request-ID table counts one thread created, and the fake one `spawn`
//! call, however many starts follow. The crash is real: the start runs in
//! its own process (`fake::child_process`), which the fake kills during the
//! call or which stops itself at a write.
//!
//! Also here: a start is recorded before it's made, and an uncertain one is
//! never retried; a pending one is reconciled through 0.0.4's status read
//! before anything else; two starts at once make one call; a retry never
//! swaps the settings; each agent gets its one-line brief and exactly the
//! settings given.
//!
//! B4's other files, declared from here: `fake` (the fakes and the
//! child), `record` (the start record's strict reader and its store) and
//! `archive` (`thread archive`).
//!
//! **Fixtures only.** Fixture tests never prove live behaviour.

#[path = "b4_archive.rs"]
mod archive;
#[path = "b4_fake.rs"]
pub mod fake;
#[path = "b4_record.rs"]
mod record;

use std::os::unix::process::ExitStatusExt;
use std::sync::{Arc, Barrier};
use std::time::Duration;

use openwiz_core::fleet::starts::{
    AttemptOutcome, Next, NotCreated, Repository, StartError, StartField, StartKey, StartOutcome,
    preview_start, start_agent,
};
use openwiz_core::new_thread::request_id;
use serde_json::json;

use fake::*;

/// The fake killed the child with SIGKILL, or the child stopped itself
/// with SIGABRT: no exit code either way.
fn stopped_by(output: &std::process::Output, signal: i32) {
    assert_eq!(
        output.status.signal(),
        Some(signal),
        "the child was not stopped by signal {signal}: {:?}\n{}\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

const SIGKILL: i32 = 9;
const SIGABRT: i32 = 6;

/// One builder in all: one spawn call, one thread created.
fn one_builder(fake: &Fake) {
    assert_eq!(fake.spawn_count(), 1, "spawn calls");
    assert_eq!(fake.threads_created(), 1, "threads created");
}

/// S2-2: the fake creates the thread, prints its receipt, and kills the
/// start's process before it records anything of the outcome. Every start
/// after it reads the attempt's status first (uncertain: interrupted after
/// the dispatching mark) and never starts again.
#[test]
fn s2_2_a_crash_after_the_call_ends_with_one_builder() {
    let fake = Fake::new(
        "s2_2_crash_after_call",
        vec![json!({
            "any_spawn": true,
            "stdout_file": file("spawn-receipt-created.json"),
            "creates": true,
            "kill_parent_after_answer": true,
        })],
    );
    let request = builder(7);
    stopped_by(
        &fake.child(&request, &["op-b4-crash-1"], Crash::Never),
        SIGKILL,
    );
    one_builder(&fake);

    // Any later spawn would create another thread.
    fake.respond(vec![]);
    for _ in 0..2 {
        let report = fake.start(&request, &["op-b4-crash-2"]);
        one_builder(&fake);
        let StartOutcome::Uncertain { words } = &report.outcome else {
            panic!("not uncertain: {report:?}");
        };
        assert!(words.contains("after"), "{words}");
        assert_eq!(report.op_id, Some(op("op-b4-crash-1")));
    }
    let record = fake.record(&request).unwrap();
    assert_eq!(record.attempts().len(), 1, "no second attempt");
    assert!(matches!(
        record.attempts()[0].outcome,
        AttemptOutcome::Uncertain { .. }
    ));
}

/// S2-2: the start's process stops right after `new_thread` has created
/// the thread and recorded it, before the start record says so. The next
/// start reads the attempt's status (created), records the thread, and
/// makes no call.
#[test]
fn s2_2_a_crash_between_the_start_and_its_record_ends_with_one_builder() {
    let fake = Fake::new("s2_2_crash_before_record", vec![]);
    let request = builder(8);
    stopped_by(
        &fake.child(&request, &["op-b4-record-1"], Crash::AfterCreated),
        SIGABRT,
    );
    one_builder(&fake);
    let new_thread = fake.new_thread_record("op-b4-record-1").unwrap();
    assert_eq!(new_thread["outcome"]["kind"], "created", "{new_thread}");

    for _ in 0..2 {
        let report = fake.start(&request, &["op-b4-record-2"]);
        one_builder(&fake);
        assert_eq!(
            report.outcome,
            StartOutcome::Started {
                thread_id: THREAD.to_owned(),
                by_this_call: false,
            }
        );
    }
    let record = fake.record(&request).unwrap();
    assert_eq!(record.attempts().len(), 1, "no second attempt");
    assert_eq!(
        record.attempts()[0].outcome,
        AttemptOutcome::Created {
            thread_id: THREAD.to_owned()
        }
    );
}

/// S2-2: the fake creates the thread and never answers. The start times out
/// (uncertain); every later start finds it uncertain and makes no call.
#[test]
fn s2_2_a_timed_out_start_ends_with_one_builder() {
    let fake = Fake::new(
        "s2_2_timed_out",
        vec![json!({"any_spawn": true, "creates": true, "hang": true})],
    );
    let mut request = builder(9);
    request.budget = Duration::from_secs(3);
    let report = fake.start(&request, &["op-b4-timeout-1"]);
    let StartOutcome::Uncertain { words } = &report.outcome else {
        panic!("not uncertain: {report:?}");
    };
    assert!(words.contains("time"), "{words}");
    one_builder(&fake);

    fake.respond(vec![]);
    for _ in 0..2 {
        let again = fake.start(&request, &["op-b4-timeout-2"]);
        one_builder(&fake);
        assert!(
            matches!(again.outcome, StartOutcome::Uncertain { .. }),
            "{again:?}"
        );
    }
    assert_eq!(fake.record(&request).unwrap().attempts().len(), 1);
}

/// Recorded before it's made: a start that stops right after recording its
/// attempt has sent nothing. The next start finds no `new_thread` record
/// under that op id, so it makes the call with the same op id (the same
/// request id), once.
#[test]
fn a_start_is_recorded_before_it_is_made_and_a_crash_before_the_call_starts_it_once() {
    let fake = Fake::new("b4_recorded_first", vec![]);
    let request = builder(10);
    stopped_by(
        &fake.child(&request, &["op-b4-first-1"], Crash::AfterRecording),
        SIGABRT,
    );
    assert_eq!(fake.spawn_count(), 0, "nothing was sent");
    let left = fake.record(&request).expect("the attempt was recorded");
    assert_eq!(left.attempts()[0].op_id, op("op-b4-first-1"));
    assert!(fake.new_thread_record("op-b4-first-1").is_none());

    let report = fake.start(&request, &["op-b4-first-2"]);
    assert_eq!(
        report.outcome,
        StartOutcome::Started {
            thread_id: THREAD.to_owned(),
            by_this_call: true,
        }
    );
    one_builder(&fake);
    let spawn = &fake.spawns()[0];
    let rid = spawn[spawn.iter().position(|w| w == "--request-id").unwrap() + 1].clone();
    assert_eq!(rid, request_id(&op("op-b4-first-1")), "the same op id");
    assert_eq!(fake.record(&request).unwrap().attempts().len(), 1);
}

/// A crash during `new_thread`'s reads, before its dispatching mark,
/// created nothing: the status read says failed, and the next start makes
/// a new attempt with a new op id. One builder.
#[test]
fn a_crash_before_the_dispatching_mark_is_retried_once_with_a_new_op_id() {
    let fake = Fake::new(
        "b4_crash_before_mark",
        vec![json!({"argv": ["--version"], "stdout": "v127\n", "kill_parent": true})],
    );
    let request = builder(11);
    stopped_by(
        &fake.child(&request, &["op-b4-mark-1"], Crash::Never),
        SIGKILL,
    );
    assert_eq!(fake.spawn_count(), 0);

    fake.respond(vec![]);
    let report = fake.start(&request, &["op-b4-mark-2"]);
    assert_eq!(report.op_id, Some(op("op-b4-mark-2")));
    assert!(
        matches!(
            report.outcome,
            StartOutcome::Started {
                by_this_call: true,
                ..
            }
        ),
        "{report:?}"
    );
    one_builder(&fake);
    let record = fake.record(&request).unwrap();
    let attempts = record.attempts();
    assert_eq!(attempts.len(), 2);
    assert!(matches!(
        attempts[0].outcome,
        AttemptOutcome::NotCreated {
            status: NotCreated::Failed,
            ..
        }
    ));
    assert_eq!(attempts[1].op_id, op("op-b4-mark-2"));
}

/// Two starts of one builder at once: the start's lock lets exactly one
/// make the call; the other finds it in progress, or started.
#[test]
fn two_starts_at_once_make_one_call() {
    let fake = Fake::new(
        "b4_two_at_once",
        vec![json!({
            "any_spawn": true,
            "stdout_file": file("spawn-receipt-created.json"),
            "creates": true,
            "delay_ms": 1500,
        })],
    );
    let fake = Arc::new(fake);
    let barrier = Arc::new(Barrier::new(2));
    let handles: Vec<_> = ["op-b4-race-a", "op-b4-race-b"]
        .into_iter()
        .map(|id| {
            let (fake, barrier) = (Arc::clone(&fake), Arc::clone(&barrier));
            std::thread::spawn(move || {
                // Each start opens its own stores, as two ticks would.
                let (source, threads, starts) = (fake.source(), fake.threads(), fake.starts());
                barrier.wait();
                let next = || Ok(op(id));
                start_agent(&source, &threads, &starts, &FixedClock, &next, &builder(12))
                    .map(|report| report.outcome)
            })
        })
        .collect();
    let results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
    one_builder(&fake);
    let outcomes: Vec<StartOutcome> = results.into_iter().map(|r| r.expect("a report")).collect();
    let made = outcomes
        .iter()
        .filter(|o| {
            matches!(
                o,
                StartOutcome::Started {
                    by_this_call: true,
                    ..
                }
            )
        })
        .count();
    assert_eq!(made, 1, "{outcomes:?}");
    for o in &outcomes {
        assert!(
            matches!(o, StartOutcome::Started { .. } | StartOutcome::InProgress),
            "{o:?}"
        );
    }
}

/// Never swapped: a refused start is retried only with the settings it was
/// first recorded with. A request with another model is refused with no
/// call; the same settings make a new attempt.
#[test]
fn a_refused_start_is_retried_only_with_the_same_settings() {
    let fake = Fake::new("b4_never_swapped", vec![refused()]);
    let request = reviewer(13);
    let report = fake.start(&request, &["op-b4-swap-1"]);
    assert!(
        matches!(report.outcome, StartOutcome::NotStarted { .. }),
        "{report:?}"
    );
    assert_eq!(fake.spawn_count(), 1);
    assert_eq!(fake.threads_created(), 0);

    let mut swapped = request.clone();
    swapped.settings.model = "syn-codex-model-02".to_owned();
    let report = fake.start(&swapped, &["op-b4-swap-2"]);
    assert_eq!(
        report.outcome,
        StartOutcome::Conflicting {
            differs: vec![StartField::Model]
        }
    );
    assert_eq!(fake.spawn_count(), 1, "no call");

    fake.respond(vec![]);
    let report = fake.start(&request, &["op-b4-swap-3"]);
    assert!(
        matches!(
            report.outcome,
            StartOutcome::Started {
                by_this_call: true,
                ..
            }
        ),
        "{report:?}"
    );
    let spawns = fake.spawns();
    assert_eq!(spawns.len(), 2);
    let model =
        |argv: &Vec<String>| argv[argv.iter().position(|w| w == "--model").unwrap() + 1].clone();
    assert_eq!(model(&spawns[0]), "gpt-6.1-sol");
    assert_eq!(model(&spawns[1]), "gpt-6.1-sol");
    assert_eq!(fake.record(&request).unwrap().attempts().len(), 2);
}

/// Each agent's one call carries its one-line brief and exactly the
/// settings given (the builder and reviewer settings of `fake`), in
/// `new_thread`'s one shape. A
/// builder's start and a reviewer's are separate starts.
#[test]
fn each_agent_gets_its_one_line_brief_and_exactly_its_settings() {
    let fake = Fake::new("b4_briefs", vec![]);
    let started = fake.start(&builder(14), &["op-b4-brief-1"]);
    assert!(matches!(started.outcome, StartOutcome::Started { .. }));
    let reviewed = fake.start(&reviewer(15), &["op-b4-brief-2"]);
    assert!(matches!(reviewed.outcome, StartOutcome::Started { .. }));
    let spawn = |provider: &str, model: &str, effort: &str, op_id: &str, prompt: &str| {
        let rid = request_id(&op(op_id));
        [
            "thread",
            "spawn",
            "--project",
            PROJECT,
            "--machine",
            "cloud",
            "--provider",
            provider,
            "--model",
            model,
            "--reasoning-level",
            effort,
            "--request-id",
            rid.as_str(),
            "--json",
            "--prompt",
            prompt,
        ]
        .map(str::to_owned)
        .to_vec()
    };
    assert_eq!(
        fake.spawns(),
        vec![
            spawn(
                "claude-code",
                "claude-opus-5-5",
                "xhigh",
                "op-b4-brief-1",
                "You are the builder for #14. Read skills/build-ticket/SKILL.md and follow it.",
            ),
            spawn(
                "codex",
                "gpt-6.1-sol",
                "high",
                "op-b4-brief-2",
                "You are the reviewer for pull request #15 at \
                 0123456789abcdef0123456789abcdef01234567. Read skills/review-ticket/SKILL.md \
                 and follow it.",
            ),
        ]
    );
}

/// A started agent is never started again, and the preview (for a dry run)
/// says so without writing, locking or calling anything.
#[test]
fn a_started_agent_is_never_started_again_and_the_preview_only_reads() {
    let fake = Fake::new("b4_started_once", vec![]);
    let request = builder(16);
    assert_eq!(
        preview_start(&fake.starts(), &request).unwrap(),
        Next::Attempt
    );
    fake.start(&request, &["op-b4-once-1"]);
    let before = fake.invocations().len();
    let path = fake
        .state
        .join("starts")
        .join(format!("{}.json", request.key.id()));
    let bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        preview_start(&fake.starts(), &request).unwrap(),
        Next::Started {
            op_id: op("op-b4-once-1"),
            thread_id: THREAD.to_owned()
        }
    );
    let again = fake.start(&request, &[]);
    assert_eq!(
        again.outcome,
        StartOutcome::Started {
            thread_id: THREAD.to_owned(),
            by_this_call: false,
        }
    );
    assert_eq!(fake.invocations().len(), before, "nothing was read or sent");
    assert_eq!(std::fs::read(&path).unwrap(), bytes, "nothing was written");
    one_builder(&fake);
}

/// An op id the caller gives twice for one start is refused before it is
/// written: the record keeps one attempt per op id, so it stays readable,
/// and nothing is sent.
#[test]
fn an_op_id_used_before_is_refused_before_anything_is_written() {
    let fake = Fake::new("b4_op_id_twice", vec![refused()]);
    let request = builder(17);
    let first = fake.start(&request, &["op-b4-twice"]);
    assert!(matches!(first.outcome, StartOutcome::NotStarted { .. }));
    let before = fake.record(&request).unwrap();
    let next = || Ok(op("op-b4-twice"));
    let again = start_agent(
        &fake.source(),
        &fake.threads(),
        &fake.starts(),
        &FixedClock,
        &next,
        &request,
    );
    assert!(matches!(again, Err(StartError::OpId(_))), "{again:?}");
    assert_eq!(
        fake.record(&request),
        Some(before),
        "the record is unchanged"
    );
    assert_eq!(fake.spawn_count(), 1, "nothing more was sent");
}

/// R1, one mismatch at a time: settings and project must bind even when
/// the brief and every other field match. All disk records remain readable.
#[test]
fn reconciling_checks_each_project_and_setting_independently() {
    for (i, field) in ["project", "harness", "model", "effort"]
        .into_iter()
        .enumerate()
    {
        let fake = Fake::new(&format!("b4_binding_{field}"), vec![]);
        let request = if i < 2 { builder(220) } else { reviewer(220) };
        stopped_by(
            &fake.child(&request, &["op-b4-binding"], Crash::AfterCreated),
            SIGABRT,
        );
        one_builder(&fake);
        let mut foreign = fake.new_thread_record("op-b4-binding").unwrap();
        if field == "project" {
            foreign["binding"]["project"]["value"] = json!("prj_syn_0002");
        } else {
            foreign["binding"][field] = json!("synthetic-other");
            foreign["requested"][field] = json!("synthetic-other");
        }
        let path = fake.state.join("new-threads/op-b4-binding.json");
        let bytes = serde_json::to_vec(&foreign).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        let report = fake.start(&request, &[]);
        let StartOutcome::NotStarted { words } = &report.outcome else {
            panic!("adopted a create with another {field}: {report:?}");
        };
        assert!(words.contains("another"), "{field}: {words}");
        assert_eq!(report.op_id, Some(op("op-b4-binding")));
        let record = fake.record(&request).unwrap();
        assert_eq!(record.attempts().len(), 1);
        assert!(matches!(
            record.attempts()[0].outcome,
            AttemptOutcome::NotCreated {
                status: NotCreated::Failed,
                ..
            }
        ));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        one_builder(&fake);
    }
}

/// A refused attempt must retain its harness even when all other fields match.
#[test]
fn retries_refuse_a_changed_harness() {
    let fake = Fake::new("b4_retry_harness", vec![refused()]);
    let request = reviewer(221);
    let first = fake.start(&request, &["op-b4-retry-first"]);
    assert!(matches!(first.outcome, StartOutcome::NotStarted { .. }));
    let before = fake.record(&request).unwrap();
    let mut changed = request.clone();
    changed.settings.harness = "claude-code".to_owned();
    let report = fake.start(&changed, &["op-b4-retry-changed"]);
    assert_eq!(
        report.outcome,
        StartOutcome::Conflicting {
            differs: vec![StartField::Harness]
        }
    );
    assert_eq!(report.op_id, None);
    assert_eq!(
        preview_start(&fake.starts(), &changed).unwrap(),
        Next::Conflicting {
            differs: vec![StartField::Harness]
        }
    );
    assert_eq!(fake.record(&request), Some(before));
    assert_eq!(fake.spawn_count(), 1);
    assert_eq!(fake.threads_created(), 0);
    fake.respond(vec![]);
    let report = fake.start(&request, &["op-b4-retry-same"]);
    assert!(
        matches!(
            report.outcome,
            StartOutcome::Started {
                by_this_call: true,
                ..
            }
        ),
        "{report:?}"
    );
    assert_eq!(fake.record(&request).unwrap().attempts().len(), 2);
    assert_eq!(fake.spawn_count(), 2);
    assert_eq!(fake.threads_created(), 1);
}

/// Review R1: an op id another start used is never adopted. Ticket 201's
/// builder is created under one op id; ticket 202's start records the same
/// op id and stops before its call. Reconciling 202 finds 201's create
/// under that op id, bound to another brief: it takes nothing from it
/// and sends nothing. 202's next start makes its own
/// attempt, with a new op id, and creates 202's builder.
#[test]
fn reconciling_never_adopts_another_starts_create() {
    let fake = Fake::new("b4_r1_reconcile", vec![]);
    let (first, second) = (builder(201), builder(202));
    let report = fake.start(&first, &["op-b4-shared"]);
    assert!(matches!(report.outcome, StartOutcome::Started { .. }));
    stopped_by(
        &fake.child(&second, &["op-b4-shared"], Crash::AfterRecording),
        SIGABRT,
    );
    let report = fake.start(&second, &["op-b4-own"]);
    let StartOutcome::NotStarted { words } = &report.outcome else {
        panic!("ticket 202 took ticket 201's create: {report:?}");
    };
    assert!(words.contains("another"), "{words}");
    assert_eq!(fake.spawn_count(), 1, "nothing sent for 202 yet");
    let record = fake.record(&second).unwrap();
    assert!(matches!(
        record.attempts()[0].outcome,
        AttemptOutcome::NotCreated {
            status: NotCreated::Failed,
            ..
        }
    ));

    let report = fake.start(&second, &["op-b4-own"]);
    assert_eq!(report.op_id, Some(op("op-b4-own")));
    assert!(
        matches!(
            report.outcome,
            StartOutcome::Started {
                by_this_call: true,
                ..
            }
        ),
        "{report:?}"
    );
    assert_eq!(fake.spawn_count(), 2);
    assert_eq!(fake.threads_created(), 2, "201's builder and 202's");
}

/// Review R1, the same op id given straight to a call: `new_thread` refuses
/// the conflicting reuse with no call, so nothing was sent for this start;
/// it is not left uncertain for ever, and its next start creates its
/// builder.
#[test]
fn a_call_under_another_starts_op_id_sends_nothing_and_is_retried() {
    let fake = Fake::new("b4_r1_call", vec![]);
    let (first, second) = (builder(204), builder(205));
    fake.start(&first, &["op-b4-taken"]);
    let report = fake.start(&second, &["op-b4-taken"]);
    assert!(
        matches!(report.outcome, StartOutcome::NotStarted { .. }),
        "{report:?}"
    );
    assert_eq!(fake.spawn_count(), 1);
    let report = fake.start(&second, &["op-b4-fresh"]);
    assert!(
        matches!(
            report.outcome,
            StartOutcome::Started {
                by_this_call: true,
                ..
            }
        ),
        "{report:?}"
    );
    assert_eq!(fake.spawn_count(), 2);
}

/// Review R2: GitHub's owner and repository names ignore case, so one
/// ticket is one start however they are spelled: one record, one lock, one
/// builder.
#[test]
fn a_repository_spelled_with_other_capitals_is_the_same_start() {
    let fake = Fake::new("b4_r2_case", vec![]);
    let request = builder(203);
    fake.start(&request, &["op-b4-case-1"]);
    for spelling in [
        "Synthetic-Owner/synthetic-repo-0001",
        "synthetic-owner/Synthetic-Repo-0001",
        "SYNTHETIC-OWNER/SYNTHETIC-REPO-0001",
    ] {
        let repository = Repository::parse(spelling).expect("a repository");
        assert_eq!(repository.as_str(), REPOSITORY, "{spelling}");
        let mut other = request.clone();
        other.key = StartKey::builder(repository, number(203));
        assert_eq!(other.key, request.key, "{spelling}");
        let report = fake.start(&other, &["op-b4-case-2"]);
        assert!(
            matches!(
                report.outcome,
                StartOutcome::Started {
                    by_this_call: false,
                    ..
                }
            ),
            "{spelling}: {report:?}"
        );
    }
    one_builder(&fake);
}
