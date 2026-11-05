//! LP3 injected-router proofs. Synthetic source, current fleet reads and sends;
//! no production transport or legacy check-in is exercised here.
#[path = "l4_relay.rs"]
mod shared_relay;
#[path = "l4_support.rs"]
mod support;

use openwiz_core::fleet::model::{CheckResult, Review, Verdict};
use openwiz_core::fleet::tick::{Observed, PrInput, Problem, ReportComment, Reviewer};
use openwiz_core::messaging::send::{SendResult, Status};
use openwiz_service::{events::*, route_event};
use support::*;

#[test]
fn lp3_owner_source_to_recorded_builder_is_immediate_for_every_event_kind() {
    for kind in [
        EventKind::PullRequestReview,
        EventKind::WorkflowRun,
        EventKind::CheckSuite,
        EventKind::IssueComment,
    ] {
        let fixture = Fixture::new();
        let fake = Fake::new(snapshot());
        let store = fixture.store();
        let router = router(&fake, &store);
        let mut source = Source::new(event(kind, "synthetic-delivery-1"));
        let routes = route_event(&router, &mut source).unwrap().unwrap();
        assert_eq!(routes.len(), 1);
        assert_eq!(routes[0].0, n(1901));
        let RouteResult::Send(report) = &routes[0].1 else {
            panic!("expected the recorded builder: {routes:?}");
        };
        assert_eq!(report.status, Status::Accepted);
        assert!(matches!(
            report.result,
            SendResult::Outcome {
                replayed: false,
                ..
            }
        ));
        assert_eq!(
            fake.calls(),
            [(
                "thr_syn_builder".into(),
                format!(
                    "CI failed for pull request #1901 at {} (ci). Read the failed job log, fix it, and hand back a new green head.",
                    "a".repeat(40)
                )
            )]
        );
        assert_eq!(*fake.trace.lock().unwrap(), ["facts", "tell"]);
        // There is no timer or periodic poll between source receipt and tell.
        assert!(route_event(&router, &mut source).unwrap().is_none());
        assert_eq!(fake.calls().len(), 1);
    }
}

#[test]
fn lp3_current_findings_go_to_builder_and_recheck_to_recorded_reviewer() {
    for recheck in [false, true] {
        let fixture = Fixture::new();
        let mut current = snapshot();
        for check in &mut pr(&mut current).ci.as_mut().unwrap().checks {
            check.result = CheckResult::Pass;
        }
        let reviewed = if recheck { 'c' } else { 'a' };
        pr(&mut current).reports.push(ReportComment {
            comment: n(6001),
            text: format!("VERDICT: CHANGES at {}", reviewed.to_string().repeat(40)),
        });
        ticket(&mut current).reviewers.push(Reviewer {
            pr: n(1901),
            agent: agent("thr_syn_reviewer"),
            head: commit(reviewed),
            last_activity_at: 2_000_000,
            given_up: false,
            output: Some(Review {
                verdict: Verdict::Changes,
                commit: commit(reviewed),
            }),
        });
        let fake = Fake::new(current);
        let store = fixture.store();
        let routes = route_event(
            &router(&fake, &store),
            &mut Source::new(event(EventKind::IssueComment, "synthetic-review")),
        )
        .unwrap()
        .unwrap();
        assert!(
            matches!(&routes[0].1, RouteResult::Send(report) if report.status == Status::Accepted),
            "{routes:?}"
        );
        let (target, message) = if recheck {
            (
                "thr_syn_reviewer",
                format!(
                    "Re-check pull request #1901 at {}: read skills/review-ticket/SKILL.md, Re-checks.",
                    "a".repeat(40)
                ),
            )
        } else {
            (
                "thr_syn_builder",
                format!(
                    "The review of pull request #1901 at {} asks for changes: read the report there. Fix or dispute each open finding, then hand back a new green head.",
                    "a".repeat(40)
                ),
            )
        };
        assert_eq!(fake.calls(), [(target.into(), message)]);
    }
}

#[test]
fn lp3_unknown_ambiguous_archived_and_unread_owners_return_to_checkin() {
    for case in [
        "missing",
        "missing-builder-with-reviewer",
        "archived",
        "unread",
        "ambiguous",
        "several-closes",
        "several-prs",
    ] {
        let fixture = Fixture::new();
        let mut current = snapshot();
        match case {
            "missing" => ticket(&mut current).builder = None,
            "missing-builder-with-reviewer" => {
                ticket(&mut current).builder = None;
                ticket(&mut current).reviewers.push(Reviewer {
                    pr: n(1901),
                    agent: agent("thr_syn_reviewer"),
                    head: commit('a'),
                    last_activity_at: 2_000_000,
                    given_up: false,
                    output: None,
                });
            }
            "archived" => ticket(&mut current).builder.as_mut().unwrap().archived = true,
            "unread" => {
                fleet(&mut current).tickets[0].facts = Observed::Unread(vec![Problem::Agents])
            }
            "ambiguous" => {
                let mut duplicate = fleet(&mut current).tickets[0].clone();
                duplicate.number = n(902);
                fleet(&mut current).tickets.push(duplicate);
            }
            "several-closes" => pr(&mut current).fields.closes.push(n(902)),
            "several-prs" => {
                ticket(&mut current).pr = Some(PrInput::Several(vec![n(1901), n(1902)]))
            }
            _ => unreachable!(),
        }
        let fake = Fake::new(current);
        let store = fixture.store();
        let routes = route_event(
            &router(&fake, &store),
            &mut Source::new(event(EventKind::PullRequestReview, case)),
        )
        .unwrap()
        .unwrap();
        assert!(
            matches!(routes[0].1, RouteResult::CheckIn(_)),
            "{case}: {routes:?}"
        );
        assert_eq!(fake.calls().len(), 0, "{case}");
    }
}

#[test]
fn lp3_duplicates_and_different_hints_share_one_durable_semantic_relay() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let mut ids = Vec::new();
    for (kind, id) in [
        (EventKind::WorkflowRun, "first"),
        (EventKind::WorkflowRun, "first"),
        (EventKind::CheckSuite, "second"),
        (EventKind::IssueComment, "third"),
    ] {
        // Reopen the real file store and reconstruct the router on every hint.
        let store = fixture.store();
        let routes = route_event(&router(&fake, &store), &mut Source::new(event(kind, id)))
            .unwrap()
            .unwrap();
        let RouteResult::Send(report) = &routes[0].1 else {
            panic!("{routes:?}")
        };
        assert_eq!(report.status, Status::Accepted);
        ids.push(report.op_id.clone());
    }
    assert_eq!(
        fake.calls().len(),
        1,
        "different GitHub deliveries can describe the same due relay"
    );
    assert!(ids.iter().all(|id| id == &ids[0]));
    assert_eq!(
        std::fs::read_dir(fixture.0.join("sends"))
            .unwrap()
            .filter(|e| e
                .as_ref()
                .unwrap()
                .path()
                .extension()
                .is_some_and(|x| x == "json"))
            .count(),
        1
    );
    assert_eq!(
        *fake.trace.lock().unwrap(),
        ["facts", "tell", "facts", "facts", "facts"]
    );
}

#[test]
fn lp3_old_hint_uses_fresh_head_and_a_new_head_has_its_own_relay() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    for head in ['a', 'c'] {
        let mut current = fake.current.lock().unwrap();
        pr(&mut current).fields.head_commit = commit(head);
        pr(&mut current).ci.as_mut().unwrap().head_commit = commit(head);
        drop(current);
        let routes = route_event(
            &router,
            &mut Source::new(event(EventKind::WorkflowRun, "same-late-hint")),
        )
        .unwrap()
        .unwrap();
        assert!(
            matches!(&routes[0].1, RouteResult::Send(report) if report.status == Status::Accepted),
            "{routes:?}"
        );
    }
    assert_eq!(fake.calls().len(), 2);
    assert!(fake.calls()[0].1.contains(&"a".repeat(40)));
    assert!(fake.calls()[1].1.contains(&"c".repeat(40)));
    // A late hint cannot re-send a relay the current fleet records settled.
    pr(&mut fake.current.lock().unwrap())
        .records
        .ci_sent
        .push(commit('c'));
    let routes = route_event(
        &router,
        &mut Source::new(event(EventKind::PullRequestReview, "late")),
    )
    .unwrap()
    .unwrap();
    assert!(matches!(routes[0].1, RouteResult::Quiet));
    assert_eq!(fake.calls().len(), 2);
}

// A test-binary subprocess exits without destructors while owning the real
// store lock. Only synthetic paths explicitly supplied by the parent are used.
#[test]
fn lp3_crash_child() {
    let Some(stage) = std::env::var_os("OPENWIZ_L4_CRASH_STAGE") else {
        return;
    };
    let root = std::path::PathBuf::from(std::env::var_os("OPENWIZ_L4_CRASH_ROOT").unwrap());
    let store = openwiz_store::FileStore::open(&root).unwrap();
    let mut fake = Fake::new(snapshot());
    fake.crash = Some((stage.to_str().unwrap().into(), root.join("provider-call")));
    route_event(
        &router(&fake, &store),
        &mut Source::new(event(EventKind::WorkflowRun, "before-crash")),
    )
    .unwrap();
    panic!("child must stop at its selected crash boundary");
}

#[test]
fn lp3_crash_boundaries_recover_without_a_second_dispatch() {
    use openwiz_core::messaging::send::{Delivery, FailReason};
    for stage in ["claim", "dispatch", "receipt"] {
        let fixture = Fixture::new();
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "lp3_crash_child", "--nocapture"])
            .env("OPENWIZ_L4_CRASH_STAGE", stage)
            .env("OPENWIZ_L4_CRASH_ROOT", &fixture.0)
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(73),
            "{stage}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(fixture.0.join("provider-call").exists(), stage == "receipt");
        let fake = Fake::new(snapshot());
        for id in ["after-crash", "repeated-recovery"] {
            let store = fixture.store();
            let routes = route_event(
                &router(&fake, &store),
                &mut Source::new(event(EventKind::CheckSuite, id)),
            )
            .unwrap()
            .unwrap();
            let RouteResult::Send(report) = &routes[0].1 else {
                panic!("{stage}: {routes:?}")
            };
            let SendResult::Outcome {
                delivery,
                replayed: true,
                recovered: true,
            } = &report.result
            else {
                panic!("{stage}: recovery must retain the saved identity: {report:?}")
            };
            match (stage, delivery) {
                (
                    "claim",
                    Delivery::Failed {
                        reason: FailReason::InterruptedBeforeDispatch,
                        ..
                    },
                ) => {}
                ("dispatch" | "receipt", Delivery::Uncertain { .. }) => {}
                _ => panic!("{stage}: {delivery:?}"),
            }
        }
        assert_eq!(
            fake.calls().len(),
            0,
            "{stage}: recovery must never redispatch"
        );
    }
}

#[test]
fn lp3_missed_event_can_be_reconciled_at_the_local_seam_once() {
    // This is the injected recovery seam, not the legacy production check-in.
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    let RouteResult::Send(first) = router.route_pr(n(1901)) else {
        panic!("missed hint was not reconciled")
    };
    assert_eq!(first.status, Status::Accepted);
    let routes = route_event(
        &router,
        &mut Source::new(event(EventKind::CheckSuite, "arrives-later")),
    )
    .unwrap()
    .unwrap();
    let RouteResult::Send(late) = &routes[0].1 else {
        panic!("{routes:?}")
    };
    assert_eq!(first.op_id, late.op_id);
    assert!(matches!(
        late.result,
        SendResult::Outcome { replayed: true, .. }
    ));
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3_uncertainty_survives_restart_and_a_later_positive_provider_reply() {
    use openwiz_core::messaging::send::{Delivery, TellReply, UncertainReason};
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    *fake.reply.lock().unwrap() = TellReply::Unclear {
        reason: UncertainReason::TimedOut,
        gaps: vec![],
    };
    let mut op = None;
    for id in ["lost-ack", "repeated-hint"] {
        let store = fixture.store();
        let routes = route_event(
            &router(&fake, &store),
            &mut Source::new(event(EventKind::WorkflowRun, id)),
        )
        .unwrap()
        .unwrap();
        let RouteResult::Send(report) = &routes[0].1 else {
            panic!("{routes:?}")
        };
        assert_eq!(report.status, Status::Uncertain);
        assert!(matches!(
            report.result,
            SendResult::Outcome {
                delivery: Delivery::Uncertain { .. },
                ..
            }
        ));
        if let Some(previous) = &op {
            assert_eq!(previous, &report.op_id);
        }
        op = Some(report.op_id.clone());
        *fake.reply.lock().unwrap() = TellReply::Sent;
    }
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3_current_guards_refuse_stale_ineligible_or_unread_facts() {
    for case in [
        "old-ci",
        "draft",
        "closed",
        "other-base",
        "not-handback",
        "unread",
        "other-repository",
        "other-ticket",
        "pending-ci",
    ] {
        let fixture = Fixture::new();
        let mut current = snapshot();
        match case {
            "old-ci" => pr(&mut current).ci.as_mut().unwrap().head_commit = commit('c'),
            "draft" => pr(&mut current).fields.draft = true,
            "closed" => {
                ticket(&mut current).issue.state = openwiz_core::fleet::model::IssueState::Closed
            }
            "other-base" => pr(&mut current).fields.base_branch = text("scratch"),
            "not-handback" => pr(&mut current).subject = "Still building".into(),
            "other-ticket" => pr(&mut current).fields.closes = vec![n(902)],
            "pending-ci" => {
                pr(&mut current).ci.as_mut().unwrap().checks[1].result = CheckResult::Pending
            }
            _ => {}
        }
        let fake = Fake::new(current);
        if case == "unread" {
            *fake.unread.lock().unwrap() = true;
        }
        if case == "other-repository" {
            *fake.returned_repository.lock().unwrap() =
                openwiz_core::fleet::starts::Repository::parse("synthetic/other").unwrap();
        }
        let store = fixture.store();
        let result = router(&fake, &store).route_pr(n(1901));
        assert!(
            !matches!(result, RouteResult::Send(_)),
            "{case}: {result:?}"
        );
        assert_eq!(fake.calls().len(), 0, "{case}");
    }
}

#[test]
fn lp3_invalid_or_failed_source_performs_no_reads_or_writes() {
    struct Broken;
    impl EventSource for Broken {
        fn next(&mut self) -> Result<Option<Event>, EventError> {
            Err(EventError::SourceUnavailable)
        }
    }
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    assert_eq!(
        route_event(&router, &mut Broken).unwrap_err(),
        EventError::SourceUnavailable
    );
    for case in ["foreign", "blank", "nul"] {
        let mut hint = event(EventKind::WorkflowRun, "synthetic");
        match case {
            "foreign" => {
                hint.repository =
                    openwiz_core::fleet::starts::Repository::parse("synthetic/other").unwrap()
            }
            "blank" => hint.event_id = " ".into(),
            "nul" => hint.event_id = "bad\0id".into(),
            _ => unreachable!(),
        }
        assert_eq!(
            route_event(&router, &mut Source::new(hint)).unwrap_err(),
            EventError::InvalidHint
        );
    }
    assert!(fake.trace.lock().unwrap().is_empty());
    assert_eq!(fake.calls().len(), 0);
}

#[test]
fn lp3_a_failed_durable_save_never_reaches_the_provider() {
    let fixture = Fixture::new();
    drop(fixture.store());
    let store = openwiz_store::FileStore::open_read_only(&fixture.0)
        .unwrap()
        .unwrap();
    let fake = Fake::new(snapshot());
    assert!(matches!(
        router(&fake, &store).route_pr(n(1901)),
        RouteResult::CheckIn(CheckInReason::DispatchUnresolved)
    ));
    assert_eq!(fake.calls().len(), 0);
}

#[test]
fn lp3_concurrent_routers_share_the_durable_claim() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let first_store = fixture.store();
    let second_store = fixture.store();
    let (started, waiting) = std::sync::mpsc::channel();
    let (release, held) = std::sync::mpsc::channel();
    *fake.hold.lock().unwrap() = Some((started, held));
    std::thread::scope(|scope| {
        let first = scope.spawn(|| router(&fake, &first_store).route_pr(n(1901)));
        waiting
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap();
        let second = router(&fake, &second_store).route_pr(n(1901));
        release.send(()).unwrap();
        assert!(
            matches!(second, RouteResult::Send(report) if matches!(report.result, SendResult::InProgress { .. }))
        );
        assert!(
            matches!(first.join().unwrap(), RouteResult::Send(report) if report.status == Status::Accepted)
        );
    });
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3_one_hint_can_name_two_prs_without_duplicate_rows_or_shared_send_ids() {
    let fixture = Fixture::new();
    let mut current = snapshot();
    let mut second = fleet(&mut current).tickets[0].clone();
    second.number = n(902);
    let Observed::Complete(facts) = &mut second.facts else {
        panic!("complete")
    };
    facts.builder = Some(agent("thr_syn_builder2"));
    facts.builder_source.as_mut().unwrap().thread = text("thr_syn_builder2");
    let Some(PrInput::Open(pr)) = &mut facts.pr else {
        panic!("open")
    };
    pr.fields.number = n(1902);
    pr.fields.closes = vec![n(902)];
    fleet(&mut current).tickets.push(second);
    let fake = Fake::new(current);
    let store = fixture.store();
    let mut hint = event(EventKind::WorkflowRun, "multi-pr");
    hint.pull_requests = vec![n(1902), n(1901), n(1901)];
    let routes = route_event(&router(&fake, &store), &mut Source::new(hint))
        .unwrap()
        .unwrap();
    assert_eq!(
        routes.iter().map(|(number, _)| *number).collect::<Vec<_>>(),
        [n(1901), n(1902)]
    );
    assert!(routes.iter().all(|(_,result)| matches!(result, RouteResult::Send(report) if report.status == Status::Accepted)));
    assert_eq!(
        fake.calls()
            .iter()
            .map(|(target, _)| target.as_str())
            .collect::<Vec<_>>(),
        ["thr_syn_builder", "thr_syn_builder2"]
    );
}

fn unresolved_after(change: &str) {
    use openwiz_core::messaging::send::{TellReply, UncertainReason};
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    *fake.reply.lock().unwrap() = TellReply::Unclear {
        reason: UncertainReason::TimedOut,
        gaps: vec![],
    };
    let store = fixture.store();
    let router = router(&fake, &store);
    let RouteResult::Send(first) = router.route_pr(n(1901)) else {
        panic!("first send")
    };
    assert_eq!(first.status, Status::Uncertain);
    if change == "checks" {
        pr(&mut fake.current.lock().unwrap())
            .ci
            .as_mut()
            .unwrap()
            .checks[0]
            .result = CheckResult::Fail;
    } else {
        pr(&mut fake.current.lock().unwrap())
            .records
            .ci_sent
            .push(commit('a'));
    }
    let result = router.route_pr(n(1901));
    let RouteResult::Send(second) = result else {
        panic!("{change}: uncertainty hidden by {result:?}")
    };
    assert_eq!(second.op_id, first.op_id);
    assert_eq!(second.status, Status::Uncertain, "{change}");
    assert!(matches!(
        second.result,
        SendResult::Outcome { replayed: true, .. }
    ));
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3_uncertainty_survives_changed_checks() {
    unresolved_after("checks");
}

#[test]
fn lp3_uncertainty_survives_external_relay_record() {
    unresolved_after("external-record");
}

#[test]
fn lp3_recorded_planner_warning_still_returns_invalid_facts_to_checkin() {
    let fixture = Fixture::new();
    let mut current = snapshot();
    ticket(&mut current)
        .issue
        .labels
        .push(text("ready-for-agent"));
    ticket(&mut current)
        .records
        .looked
        .push("duplicate label".into());
    let fake = Fake::new(current);
    let store = fixture.store();
    assert!(matches!(
        router(&fake, &store).route_pr(n(1901)),
        RouteResult::CheckIn(CheckInReason::FactsUnread)
    ));
    assert_eq!(fake.calls().len(), 0);
}

fn ci_passes_and_recheck_is_due(fake: &Fake) {
    let mut current = fake.current.lock().unwrap();
    for check in &mut pr(&mut current).ci.as_mut().unwrap().checks {
        check.result = CheckResult::Pass;
    }
    pr(&mut current).reports.push(ReportComment {
        comment: n(6001),
        text: format!("VERDICT: CHANGES at {}", "c".repeat(40)),
    });
    ticket(&mut current).reviewers.push(Reviewer {
        pr: n(1901),
        agent: agent("thr_syn_reviewer"),
        head: commit('c'),
        last_activity_at: 2_000_000,
        given_up: false,
        output: Some(Review {
            verdict: Verdict::Changes,
            commit: commit('c'),
        }),
    });
}

#[test]
fn r1_uncertain_ci_relay_does_not_block_a_reviewer_recheck_at_the_same_head() {
    use openwiz_core::messaging::send::{TellReply, UncertainReason};
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    *fake.reply.lock().unwrap() = TellReply::Unclear {
        reason: UncertainReason::TimedOut,
        gaps: vec![],
    };
    let store = fixture.store();
    let router = router(&fake, &store);
    assert!(
        matches!(router.route_pr(n(1901)), RouteResult::Send(report) if report.status == Status::Uncertain)
    );
    ci_passes_and_recheck_is_due(&fake);
    *fake.reply.lock().unwrap() = TellReply::Sent;
    for _ in 0..2 {
        let result = router.route_pr(n(1901));
        assert!(
            matches!(result, RouteResult::Send(report) if report.target.id.0 == "thr_syn_reviewer" && report.status == Status::Accepted)
        );
    }
    assert_eq!(
        fake.calls()
            .iter()
            .map(|(target, _)| target.as_str())
            .collect::<Vec<_>>(),
        ["thr_syn_builder", "thr_syn_reviewer"]
    );
}

#[test]
fn r1_in_progress_ci_relay_does_not_block_a_reviewer_recheck_at_the_same_head() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let first_store = fixture.store();
    let second_store = fixture.store();
    let (started, waiting) = std::sync::mpsc::channel();
    let (release, held) = std::sync::mpsc::channel();
    *fake.hold.lock().unwrap() = Some((started, held));
    std::thread::scope(|scope| {
        let first = scope.spawn(|| router(&fake, &first_store).route_pr(n(1901)));
        waiting
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap();
        ci_passes_and_recheck_is_due(&fake);
        let result = router(&fake, &second_store).route_pr(n(1901));
        release.send(()).unwrap();
        first.join().unwrap();
        assert!(
            matches!(result, RouteResult::Send(report) if report.target.id.0 == "thr_syn_reviewer" && report.status == Status::Accepted)
        );
    });
    assert_eq!(
        fake.calls()
            .iter()
            .map(|(target, _)| target.as_str())
            .collect::<Vec<_>>(),
        ["thr_syn_builder", "thr_syn_reviewer"]
    );
}
