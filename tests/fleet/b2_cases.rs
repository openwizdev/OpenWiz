use super::RULES;
use crate::md3_models::{fixture, flags};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Issue, IssueState, MergedPr, NonEmpty, Number, PrFields, Review,
    Verdict,
};
use openwiz_core::fleet::tick::*;
use openwiz_core::model::Timestamp;
use serde_json::{Value, json};
use std::collections::BTreeMap;

const NOW: u64 = 2_000_000;
fn n(x: u64) -> Number {
    Number::new(x).unwrap()
}
fn text(s: &str) -> NonEmpty {
    NonEmpty::new(s).unwrap()
}
fn commit(c: char) -> Commit {
    Commit::parse(&c.to_string().repeat(40)).unwrap()
}
fn fp(c: char) -> Fingerprint {
    Fingerprint::parse(&c.to_string().repeat(64)).unwrap()
}
fn agent(s: &str) -> Agent {
    Agent {
        thread: text(s),
        archived: false,
    }
}
fn issue() -> Issue {
    Issue {
        title: "Synthetic ticket".into(),
        state: IssueState::Open,
        milestone: None,
        labels: vec![text("ready-for-agent")],
        owned_paths: None,
        relies_on: None,
        pending_question: None,
    }
}
fn fields() -> PrFields {
    PrFields {
        number: n(1901),
        draft: false,
        head_branch: text("syn-branch"),
        head_commit: commit('a'),
        base_branch: text("main"),
        closes: vec![n(901)],
    }
}
fn merged(number: u64) -> MergeInput {
    let mut fields = fields();
    fields.number = n(number);
    fields.closes = vec![n(number - 1000)];
    MergeInput {
        pr: MergedPr {
            fields,
            merge_commit: commit('c'),
            merged_at: Timestamp(10),
        },
        read_back: true,
    }
}
fn ready() -> TicketFacts {
    TicketFacts {
        issue: issue(),
        blockers: vec![],
        pr: None,
        builder: None,
        builder_source: None,
        reviewers: vec![],
        starts: vec![],
        relies_on: vec![],
        holds: vec![],
        held_label_comment: None,
        question: None,
        records: TicketRecords::default(),
    }
}
fn open() -> OpenPr {
    OpenPr {
        fields: fields(),
        subject: "Synthetic green".into(),
        ci: Some(CheckRun {
            head_commit: commit('a'),
            base_commit: commit('b'),
            checks: ["web-build", "rust", "web-test"]
                .into_iter()
                .map(|s| Check {
                    name: text(s),
                    result: CheckResult::Pass,
                })
                .collect(),
        }),
        base_now: Some(commit('b')),
        reports: vec![],
        starts: vec![],
        records: PrRecords::default(),
    }
}
fn reviewing() -> TicketFacts {
    let mut t = ready();
    t.builder = Some(agent("syn-builder"));
    t.builder_source = Some(BuilderSource {
        thread: text("syn-builder"),
        branch: text("syn-branch"),
        family: BuilderFamily::Gpt,
        plan_limit: false,
    });
    t.pr = Some(PrInput::Open(Box::new(open())));
    t
}
fn reviewer() -> Reviewer {
    Reviewer {
        pr: n(1901),
        agent: agent("syn-reviewer"),
        head: commit('a'),
        last_activity_at: NOW,
        given_up: false,
        output: Some(Review {
            verdict: Verdict::Approve,
            commit: commit('a'),
        }),
    }
}
fn approved() -> TicketFacts {
    let mut t = reviewing();
    let p = pr(&mut t);
    p.reports.push(ReportComment {
        comment: n(5901),
        text: format!("VERDICT: APPROVE at {}", commit('a').as_str()),
    });
    t.reviewers.push(reviewer());
    t
}
fn pr(t: &mut TicketFacts) -> &mut OpenPr {
    match t.pr.as_mut().unwrap() {
        PrInput::Open(p) => p,
        _ => panic!("open"),
    }
}
fn snapshot(t: TicketFacts) -> Snapshot {
    let f = FleetFacts {
        issue: issue(),
        approval: Some(PlanApproval {
            approval: Approval {
                comment: n(5000),
                revision: n(1),
                fingerprint: fp('d'),
            },
            rows: BTreeMap::from([(n(901), Ready::Agent)]),
            approved_at: 0,
        }),
        fingerprint_now: fp('d'),
        tickets: vec![TicketInput {
            number: n(901),
            facts: Observed::Complete(t),
        }],
        changes: vec![],
        follow_ups: vec![],
        records: SpecRecords::default(),
    };
    Snapshot {
        default_branch: Observed::Complete(text("main")),
        fleets: Observed::Complete(vec![FleetInput {
            spec: n(900),
            facts: Observed::Complete(f),
        }]),
    }
}
fn fleet(s: &mut Snapshot) -> &mut FleetFacts {
    let Observed::Complete(fs) = &mut s.fleets else {
        panic!("fleets")
    };
    let Observed::Complete(f) = &mut fs[0].facts else {
        panic!("fleet")
    };
    f
}
fn ticket(s: &mut Snapshot) -> &mut TicketFacts {
    let Observed::Complete(t) = &mut fleet(s).tickets[0].facts else {
        panic!("ticket")
    };
    t
}
fn run(s: &Snapshot) -> Value {
    run_at(s, NOW)
}
fn run_at(s: &Snapshot, now: u64) -> Value {
    run_with(s, RULES, now)
}
fn run_with(s: &Snapshot, source: &str, now: u64) -> Value {
    let value =
        serde_json::to_value(plan(s, &Rules::parse(source, &flags()).unwrap(), now).expect("plan"))
            .unwrap();
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/fleet-tick.v1.schema.json")).unwrap();
    assert_eq!(crate::schema::lint(&schema), Vec::<String>::new());
    let errors = crate::schema::validate(&schema, &value);
    assert!(errors.is_empty(), "{errors:?}\n{value}");
    assert_eq!(value["schema"], "openwiz.fleet-tick.v1");
    assert_eq!(value["mode"], "dry_run");
    assert_eq!(value["planned_at"], now);
    value
}
fn rules(v: &Value) -> Vec<&str> {
    v["actions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["rule"].as_str().unwrap())
        .collect()
}
fn expect(s: &Snapshot, expected: &[&str]) -> Value {
    let v = run(s);
    assert_eq!(rules(&v), expected);
    v
}

#[test]
fn b2_authority_contracts_preserve_all_proofs() {
    let cases: [(&str, fn()); 13] = [
        (
            "b2_contract_matching_and_lowest_hit_each_tick",
            b2_contract_matching_and_lowest_hit_each_tick,
        ),
        (
            "b2_default_branch_validation_refuses_malformed_nonempty_snapshots",
            b2_default_branch_validation_refuses_malformed_nonempty_snapshots,
        ),
        (
            "b2_doubtful_contract_placement_prevents_merge",
            b2_doubtful_contract_placement_prevents_merge,
        ),
        (
            "b2_doubtful_contract_placement_withholds_review_starts",
            b2_doubtful_contract_placement_withholds_review_starts,
        ),
        (
            "b2_every_missing_merge_condition_gives_zero_merges",
            b2_every_missing_merge_condition_gives_zero_merges,
        ),
        (
            "b2_frontier_exact_facts_and_idle",
            b2_frontier_exact_facts_and_idle,
        ),
        (
            "b2_frontier_gates_and_verified_cross_version_blockers",
            b2_frontier_gates_and_verified_cross_version_blockers,
        ),
        (
            "b2_human_ticket_pr_uses_the_same_merge_conditions",
            b2_human_ticket_pr_uses_the_same_merge_conditions,
        ),
        (
            "b2_manual_merge_row_means_none",
            b2_manual_merge_row_means_none,
        ),
        (
            "b2_person_ready_has_only_the_conditions_the_contract_names",
            b2_person_ready_has_only_the_conditions_the_contract_names,
        ),
        (
            "b2_relays_do_not_grant_start_or_merge_authority",
            b2_relays_do_not_grant_start_or_merge_authority,
        ),
        (
            "b2_release_default_starts_nothing",
            b2_release_default_starts_nothing,
        ),
        (
            "b2_unknown_and_duplicate_inputs_fail_closed",
            b2_unknown_and_duplicate_inputs_fail_closed,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: b2_planner::cases::{name}");
        proof();
    }
}

fn b2_frontier_exact_facts_and_idle() {
    let value = expect(&snapshot(ready()), &["frontier"]);
    assert_eq!(
        value["actions"],
        json!([{"kind":"start_builder","rule":"frontier","spec":900,"ticket":901,"facts":{"settings":{"harness":"codex","model":"syn-builder","effort":"high"},"title":"Synthetic ticket","approval":{"comment":5000,"revision":1,"fingerprint":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},"labels":["ready-for-agent"],"blockers":[],"retry_after":null},"outcome":{"state":"planned"}}])
    );
    let mut t = ready();
    t.issue.labels.clear();
    expect(&snapshot(t), &[]);
    let s = Snapshot {
        default_branch: Observed::Complete(text("main")),
        fleets: Observed::Complete(vec![]),
    };
    expect(&s, &[]);
}

fn b2_default_branch_validation_refuses_malformed_nonempty_snapshots() {
    let rules = Rules::parse(RULES, &flags()).unwrap();
    for branch in [
        " ",
        "syn branch",
        "syn\tbranch",
        "syn\nbranch",
        "syn\0branch",
        "-syn",
        "syn-é",
        &"a".repeat(256),
    ] {
        let mut s = snapshot(ready());
        s.default_branch = Observed::Complete(text(branch));
        assert_eq!(
            plan(&s, &rules, NOW),
            Err(PlanError::InvalidSnapshot),
            "{branch:?}"
        );
    }
    for branch in ["main", "syn/topic", "syn..topic", &"a".repeat(255)] {
        let mut s = snapshot(ready());
        s.default_branch = Observed::Complete(text(branch));
        let planned = plan(&s, &rules, NOW).expect("valid default branch");
        assert_eq!(planned.default_branch.as_str(), branch);
        assert_eq!(planned.actions.len(), 1);
        assert!(matches!(planned.actions[0].detail, Detail::Frontier { .. }));
    }
}

fn b2_every_missing_merge_condition_gives_zero_merges() {
    expect(&snapshot(approved()), &["adr_0008"]);
    type Spoil = fn(&mut Snapshot);
    let cases: &[(&str, Spoil)] = &[
        ("no approval", |s| fleet(s).approval = None),
        ("stale approval", |s| fleet(s).fingerprint_now = fp('e')),
        ("not in approved graph", |s| {
            fleet(s).approval.as_mut().unwrap().rows.clear();
        }),
        ("no verdict", |s| pr(ticket(s)).reports.clear()),
        ("changes", |s| {
            pr(ticket(s)).reports[0].text = format!("VERDICT: CHANGES at {}", commit('a').as_str())
        }),
        ("old approve", |s| {
            pr(ticket(s)).reports[0].text = format!("VERDICT: APPROVE at {}", commit('c').as_str())
        }),
        ("no reviewer", |s| ticket(s).reviewers.clear()),
        ("reviewer did not say it", |s| {
            ticket(s).reviewers[0].output = None
        }),
        ("reviewer output old", |s| {
            ticket(s).reviewers[0].output.as_mut().unwrap().commit = commit('c')
        }),
        ("reviewer output changes", |s| {
            ticket(s).reviewers[0].output.as_mut().unwrap().verdict = Verdict::Changes
        }),
        ("reviewer given up", |s| {
            ticket(s).reviewers[0].given_up = true
        }),
        ("draft", |s| pr(ticket(s)).fields.draft = true),
        ("other base", |s| {
            pr(ticket(s)).fields.base_branch = text("scratch")
        }),
        ("release base", |s| {
            pr(ticket(s)).fields.base_branch = text("release-0.0.6")
        }),
        ("release default", |s| {
            s.default_branch = Observed::Complete(text("release-0.0.6"));
            pr(ticket(s)).fields.base_branch = text("release-0.0.6");
        }),
        ("closed spec", |s| fleet(s).issue.state = IssueState::Closed),
        ("closed ticket", |s| {
            ticket(s).issue.state = IssueState::Closed
        }),
        ("wrong closing link", |s| {
            pr(ticket(s)).fields.closes = vec![n(999)]
        }),
        ("no CI", |s| pr(ticket(s)).ci = None),
        ("CI old head", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().head_commit = commit('c')
        }),
        ("missing required check", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks.pop();
        }),
        ("check fail", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks[0].result = CheckResult::Fail
        }),
        ("check cancel", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks[0].result = CheckResult::Cancel
        }),
        ("check pending", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks[0].result = CheckResult::Pending
        }),
        ("required skipped", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks[0].result = CheckResult::Skipping
        }),
        ("duplicate check", |s| {
            let p = pr(ticket(s));
            let c = p.ci.as_ref().unwrap().checks[0].clone();
            p.ci.as_mut().unwrap().checks.push(c);
        }),
        ("extra pending", |s| {
            pr(ticket(s)).ci.as_mut().unwrap().checks.push(Check {
                name: text("extra"),
                result: CheckResult::Pending,
            })
        }),
        ("base changed", |s| {
            pr(ticket(s)).base_now = Some(commit('c'))
        }),
        ("base unread", |s| pr(ticket(s)).base_now = None),
        ("blocked merge", |s| {
            pr(ticket(s)).records.merge_blocked.push(commit('a'))
        }),
        ("malformed latest", |s| {
            pr(ticket(s)).reports.push(ReportComment {
                comment: n(5902),
                text: "VERDICT: APPROVE at short".into(),
            })
        }),
    ];
    for (name, spoil) in cases {
        let mut s = snapshot(approved());
        spoil(&mut s);
        let v = run(&s);
        assert!(!rules(&v).contains(&"adr_0008"), "{name}: {v}");
    }
    let s = snapshot(approved());
    for source in [
        RULES.replace("| A ticket", "| Another ticket"),
        RULES.replace("`main`, `release-*`", "`scratch`"),
    ] {
        let v =
            serde_json::to_value(plan(&s, &Rules::parse(&source, &flags()).unwrap(), NOW).unwrap())
                .unwrap();
        assert!(!rules(&v).contains(&"adr_0008"));
    }
    let mut t = approved();
    pr(&mut t).subject = "Synthetic fix".into();
    expect(&snapshot(t), &["adr_0008"]);
}

fn b2_frontier_gates_and_verified_cross_version_blockers() {
    let mut t = ready();
    t.blockers.push(BlockerInput {
        number: n(801),
        state: IssueState::Closed,
        merged: Some(merged(1801)),
    });
    let v = expect(&snapshot(t.clone()), &["frontier"]);
    assert_eq!(
        v["actions"][0]["facts"]["blockers"],
        json!([{"number":801,"pr":1801,"merge_commit":"cccccccccccccccccccccccccccccccccccccccc"}])
    );
    for state in [IssueState::Open, IssueState::Closed] {
        let mut b = t.clone();
        b.blockers[0].state = state;
        b.blockers[0].merged.as_mut().unwrap().read_back = false;
        expect(&snapshot(b), &[]);
    }
    let mut b = t.clone();
    b.blockers[0].merged = None;
    expect(&snapshot(b), &[]);
    let mut b = t;
    b.blockers[0].merged.as_mut().unwrap().pr.fields.base_branch = text("release-0.0.5");
    expect(&snapshot(b), &[]);
    for label in [
        "needs-info",
        "needs-triage",
        "ready-for-human",
        "wontfix",
        "held",
    ] {
        let mut t = ready();
        t.issue.labels.push(text(label));
        let v = run(&snapshot(t));
        assert!(!rules(&v).contains(&"frontier"), "{label}");
    }
    let mut t = ready();
    t.builder = Some(agent("syn-builder"));
    expect(&snapshot(t), &[]);
    let mut t = ready();
    t.pr = Some(PrInput::Open(Box::new(open())));
    let v = run(&snapshot(t));
    assert!(!rules(&v).contains(&"frontier"));
    let mut s = snapshot(ready());
    fleet(&mut s).fingerprint_now = fp('e');
    expect(&s, &["re_approve"]);
    let mut s = snapshot(ready());
    fleet(&mut s).approval = None;
    expect(&s, &[]);
    let mut s = snapshot(ready());
    fleet(&mut s).approval.as_mut().unwrap().rows.clear();
    expect(&s, &[]);
    let mut s = snapshot(ready());
    let mut f = fleet(&mut s).clone();
    f.tickets[0].number = n(911);
    f.approval.as_mut().unwrap().rows = BTreeMap::from([(n(911), Ready::Agent)]);
    if let Observed::Complete(fs) = &mut s.fleets {
        fs.insert(
            0,
            FleetInput {
                spec: n(910),
                facts: Observed::Complete(f),
            },
        );
    }
    let v = run(&s);
    assert_eq!(rules(&v), ["frontier", "frontier"]);
    assert_eq!(v["actions"][0]["ticket"], 901);
    assert_eq!(v["actions"][1]["ticket"], 911);
}

fn start(state: StartState) -> Start {
    Start {
        id: openwiz_core::messaging::OpId::parse("syn-start-901").unwrap(),
        state,
        logged: false,
    }
}
#[test]
fn b2_review_and_lifecycle_contracts_preserve_all_proofs() {
    let cases: [(&str, fn()); 22] = [
        (
            "b2_a_merge_must_close_the_exact_ticket_or_blocker",
            b2_a_merge_must_close_the_exact_ticket_or_blocker,
        ),
        (
            "b2_actions_and_fact_lists_have_the_contract_order",
            b2_actions_and_fact_lists_have_the_contract_order,
        ),
        (
            "b2_an_earlier_start_without_review_is_not_a_recheck",
            b2_an_earlier_start_without_review_is_not_a_recheck,
        ),
        (
            "b2_archived_reviewers_are_never_quiet_reviewers",
            b2_archived_reviewers_are_never_quiet_reviewers,
        ),
        (
            "b2_close_archive_summary_and_unlock_only_after_readback",
            b2_close_archive_summary_and_unlock_only_after_readback,
        ),
        (
            "b2_finding_ids_have_no_zero_or_leading_zero",
            b2_finding_ids_have_no_zero_or_leading_zero,
        ),
        (
            "b2_findings_and_judgment_records_are_independent",
            b2_findings_and_judgment_records_are_independent,
        ),
        (
            "b2_holds_questions_people_and_notifications",
            b2_holds_questions_people_and_notifications,
        ),
        (
            "b2_lifecycle_missing_conditions_and_exact_once_records",
            b2_lifecycle_missing_conditions_and_exact_once_records,
        ),
        (
            "b2_look_record_does_not_prove_the_spec_is_archived",
            b2_look_record_does_not_prove_the_spec_is_archived,
        ),
        (
            "b2_missing_review_and_send_conditions",
            b2_missing_review_and_send_conditions,
        ),
        (
            "b2_r1_unrecognised_round_status_still_relays_findings",
            b2_r1_unrecognised_round_status_still_relays_findings,
        ),
        (
            "b2_r2_quiet_reviewers_follow_their_own_head",
            b2_r2_quiet_reviewers_follow_their_own_head,
        ),
        (
            "b2_r3_blocked_merge_look_records_apply_to_one_head",
            b2_r3_blocked_merge_look_records_apply_to_one_head,
        ),
        (
            "b2_r3_quiet_look_records_apply_to_one_episode",
            b2_r3_quiet_look_records_apply_to_one_episode,
        ),
        (
            "b2_recorded_review_starts_allow_rechecks_and_closed_merged_agents_archive",
            b2_recorded_review_starts_allow_rechecks_and_closed_merged_agents_archive,
        ),
        (
            "b2_review_lifecycle_and_record_suppression",
            b2_review_lifecycle_and_record_suppression,
        ),
        (
            "b2_starts_never_duplicate_and_failures_are_logged_once",
            b2_starts_never_duplicate_and_failures_are_logged_once,
        ),
        (
            "b2_summary_excludes_closed_unapproved_subissues",
            b2_summary_excludes_closed_unapproved_subissues,
        ),
        (
            "b2_summary_waits_for_ambiguous_pull_requests",
            b2_summary_waits_for_ambiguous_pull_requests,
        ),
        (
            "b2_summary_waits_for_closed_tickets_with_unverified_merges",
            b2_summary_waits_for_closed_tickets_with_unverified_merges,
        ),
        (
            "b2_verified_merge_closes_even_without_a_current_plan_row",
            b2_verified_merge_closes_even_without_a_current_plan_row,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: b2_planner::cases::{name}");
        proof();
    }
}

fn b2_starts_never_duplicate_and_failures_are_logged_once() {
    for state in [StartState::Pending, StartState::Uncertain] {
        let mut t = ready();
        t.starts.push(start(state));
        expect(&snapshot(t), &["look"]);
    }
    let mut t = ready();
    t.starts.push(start(StartState::Started {
        thread: text("syn-builder"),
    }));
    expect(&snapshot(t), &["look"]);
    for state in [
        StartState::Refused {
            reason: StartReason::Refused,
        },
        StartState::Failed {
            reason: StartReason::Interrupted,
        },
    ] {
        let mut t = ready();
        t.starts.push(start(state));
        let v = expect(&snapshot(t.clone()), &["frontier", "builder_refused"]);
        assert_eq!(
            v["actions"][0]["facts"]["retry_after"]["start"],
            "syn-start-901"
        );
        t.starts[0].logged = true;
        expect(&snapshot(t), &["frontier"]);
    }
    let mut t = reviewing();
    pr(&mut t).starts.push(start(StartState::Uncertain));
    expect(&snapshot(t), &["look"]);
    let mut t = reviewing();
    pr(&mut t).starts.push(start(StartState::Refused {
        reason: StartReason::Refused,
    }));
    expect(&snapshot(t), &["first_review", "reviewer_refused"]);
}

fn b2_review_lifecycle_and_record_suppression() {
    expect(&snapshot(reviewing()), &["first_review"]);
    let mut t = reviewing();
    let mut r = reviewer();
    r.given_up = true;
    t.reviewers.push(r);
    expect(&snapshot(t), &["fresh_review"]);
    let mut t = reviewing();
    let mut r = reviewer();
    r.head = commit('c');
    t.reviewers.push(r);
    pr(&mut t).reports.push(ReportComment {
        comment: n(5900),
        text: format!("VERDICT: CHANGES at {}", commit('c').as_str()),
    });
    expect(&snapshot(t.clone()), &["re_check"]);
    pr(&mut t).records.recheck_sent.push(commit('a'));
    expect(&snapshot(t), &[]);
    let mut t = reviewing();
    let mut r = reviewer();
    r.output = None;
    t.reviewers.push(r);
    expect(&snapshot(t.clone()), &[]);
    t.reviewers[0].last_activity_at = NOW - 1_800_000;
    expect(&snapshot(t), &["look"]);
    for subject in ["evergreen", "greener", "greenish", "green_thing", "grëen"] {
        let mut t = reviewing();
        pr(&mut t).subject = subject.into();
        expect(&snapshot(t), &[]);
    }
    for subject in ["GREEN", "fix: green!", "green-fix"] {
        let mut t = reviewing();
        pr(&mut t).subject = subject.into();
        expect(&snapshot(t), &["first_review"]);
    }
    let mut t = reviewing();
    pr(&mut t).ci.as_mut().unwrap().checks.push(Check {
        name: text("optional"),
        result: CheckResult::Skipping,
    });
    expect(&snapshot(t), &["first_review"]);
    let mut t = reviewing();
    pr(&mut t).fields.draft = true;
    expect(&snapshot(t), &[]);
    let mut s = snapshot(reviewing());
    fleet(&mut s).fingerprint_now = fp('e');
    expect(&s, &[]);
}

fn changes() -> TicketFacts {
    let mut t = reviewing();
    t.reviewers.push(reviewer());
    pr(&mut t).reports.push(ReportComment{comment:n(5901),text:format!("VERDICT: CHANGES at {}\n- **R10 [medium]** disputed, kept: Synthetic\n- **R2 [high]** still open after 2 rounds: Synthetic\n- **R3 [low]** still open after 1 rounds: Synthetic\n- **R1 [medium]** new: Synthetic",commit('a').as_str())});
    t
}
fn b2_findings_and_judgment_records_are_independent() {
    let v = expect(
        &snapshot(changes()),
        &["review_findings", "disputed", "diagnosis"],
    );
    assert_eq!(v["actions"][1]["facts"]["findings"], json!(["R10"]));
    assert_eq!(
        v["actions"][2]["facts"]["findings"],
        json!([{"id":"R2","rounds":2}])
    );
    assert_eq!(
        v["actions"][0]["facts"]["verdict"],
        v["actions"][1]["facts"]["verdict"]
    );
    let mut t = changes();
    pr(&mut t).records.findings_sent.push(commit('a'));
    expect(&snapshot(t.clone()), &["disputed", "diagnosis"]);
    pr(&mut t).records.dispute_asked.push(commit('a'));
    expect(&snapshot(t.clone()), &["diagnosis"]);
    pr(&mut t).records.diagnosis_asked.push(commit('a'));
    expect(&snapshot(t), &[]);
    let mut t = changes();
    pr(&mut t).records.diagnosis_asked.push(commit('a'));
    expect(&snapshot(t), &["review_findings", "disputed"]);
    let mut t = changes();
    pr(&mut t).records.findings_sent.push(commit('c'));
    expect(&snapshot(t), &["review_findings", "disputed", "diagnosis"]);
    let mut t = changes();
    pr(&mut t).ci.as_mut().unwrap().checks[0].result = CheckResult::Fail;
    expect(
        &snapshot(t.clone()),
        &["ci_failed", "disputed", "diagnosis"],
    );
    pr(&mut t).records.ci_sent.push(commit('a'));
    expect(&snapshot(t), &["disputed", "diagnosis"]);
    let mut t = changes();
    pr(&mut t).reports.push(ReportComment {
        comment: n(5902),
        text: format!("VERDICT: APPROVE at {}", commit('a').as_str()),
    });
    pr(&mut t).reports.reverse();
    expect(&snapshot(t), &["adr_0008"]);
}

fn change(number: u64, path: &str) -> ContractChange {
    let mut m = merged(number);
    m.pr.merged_at = Timestamp(100);
    m.pr.fields.closes = vec![n(800)];
    ContractChange {
        merged: m,
        files: vec![ChangedFile {
            path: text(path),
            previous_path: None,
            added: false,
        }],
    }
}
fn b2_doubtful_contract_placement_prevents_merge() {
    let mut t = approved();
    t.builder = None;
    t.relies_on = vec![text("contracts/synthetic.md")];
    let mut s = snapshot(t);
    expect(&s, &["adr_0008"]);
    fleet(&mut s)
        .changes
        .push(change(1800, "contracts/synthetic.md"));
    let reason = "contract change has no verified builder";
    let value = expect(&s, &["look"]);
    assert_eq!(value["actions"][0]["facts"]["reason"], reason);
    ticket(&mut s).records.looked.push(reason.into());
    expect(&s, &[]);

    ticket(&mut s).issue.labels = vec![text("needs-info")];
    ticket(&mut s).question = Some(n(5100));
    expect(&s, &["needs_info"]);
    ticket(&mut s).builder = Some(agent("syn-builder"));
    expect(&s, &["contract_changed", "adr_0008", "needs_info"]);
}

fn b2_doubtful_contract_placement_withholds_review_starts() {
    for rule in ["first_review", "fresh_review", "re_check"] {
        let mut t = reviewing();
        t.builder = None;
        t.relies_on = vec![text("contracts/synthetic.md")];
        match rule {
            "fresh_review" => {
                let mut r = reviewer();
                r.given_up = true;
                t.reviewers.push(r);
            }
            "re_check" => {
                let mut r = reviewer();
                r.head = commit('c');
                t.reviewers.push(r);
                pr(&mut t).reports.push(ReportComment {
                    comment: n(5900),
                    text: format!("VERDICT: CHANGES at {}", commit('c').as_str()),
                });
            }
            _ => {}
        }
        let mut s = snapshot(t);
        if rule == "re_check" {
            expect(&s, &[rule]);
        } else {
            let value = expect(&s, &["look"]);
            assert_eq!(
                value["actions"][0]["facts"]["reason"],
                "builder family unknown or conflicting"
            );
        }
        fleet(&mut s)
            .changes
            .push(change(1800, "contracts/synthetic.md"));
        let value = expect(&s, &["look"]);
        assert_eq!(
            value["actions"][0]["facts"]["reason"],
            "contract change has no verified builder"
        );
    }
}

fn b2_contract_matching_and_lowest_hit_each_tick() {
    let mut s = snapshot(ready());
    ticket(&mut s).relies_on = vec![text("contracts/example.v1.*")];
    fleet(&mut s).changes = vec![
        change(1951, "contracts/example.v1.md"),
        change(1950, "contracts/example.v1.schema.json"),
    ];
    let v = expect(&s, &["contract_hold"]);
    assert_eq!(v["actions"][0]["facts"]["merged"]["number"], 1950);
    let h = Hold {
        comment: n(5100),
        merged: MergeFact {
            number: n(1950),
            merge_commit: commit('c'),
        },
        files: vec![text("contracts/example.v1.schema.json")],
        notified: true,
    };
    ticket(&mut s).holds.push(h);
    ticket(&mut s).issue.labels = vec![text("held")];
    let v = expect(&s, &["contract_hold"]);
    assert_eq!(v["actions"][0]["facts"]["merged"]["number"], 1951);
    ticket(&mut s).builder = Some(agent("syn-builder"));
    let v = expect(&s, &["contract_changed"]);
    assert_eq!(v["actions"][0]["facts"]["merged"]["number"], 1951);
    for (pattern, path, hit) in [
        ("contracts/", "contracts/deep/file.md", true),
        ("contracts/*.md", "contracts/example.md", true),
        ("contracts/*.md", "contracts/deep/example.md", false),
        ("contracts/x.md", "contracts/x.md", true),
        ("contracts/x.md", "contracts/x.md.extra", false),
        ("contracts/a+b.md", "contracts/aaab.md", false),
    ] {
        let mut s = snapshot(ready());
        ticket(&mut s).relies_on = vec![text(pattern)];
        fleet(&mut s).changes = vec![change(1950, path)];
        expect(
            &s,
            if hit {
                &["contract_hold"]
            } else {
                &["frontier"]
            },
        );
    }
    for spoil in [0, 1, 2, 3, 4] {
        let mut s = snapshot(ready());
        ticket(&mut s).relies_on = vec![text("contracts/")];
        let mut c = change(1950, "contracts/a.md");
        match spoil {
            0 => c.files[0].added = true,
            1 => c.merged.read_back = false,
            2 => c.merged.pr.merged_at = Timestamp(0),
            3 => c.merged.pr.fields.closes = vec![n(901)],
            _ => c.merged.pr.fields.base_branch = text("scratch"),
        }
        fleet(&mut s).changes = vec![c];
        expect(&s, &["frontier"]);
    }
    let mut s = snapshot(ready());
    ticket(&mut s).relies_on = vec![text("contracts/old.md")];
    let mut c = change(1950, "contracts/new.md");
    c.files[0].previous_path = Some(text("contracts/old.md"));
    fleet(&mut s).changes = vec![c];
    expect(&s, &["contract_hold"]);
}

fn b2_holds_questions_people_and_notifications() {
    let mut t = ready();
    t.issue.labels = vec![text("held")];
    t.holds.push(Hold {
        comment: n(4999),
        merged: MergeFact {
            number: n(1950),
            merge_commit: commit('c'),
        },
        files: vec![text("contracts/a.md")],
        notified: false,
    });
    t.held_label_comment = Some(n(4998));
    expect(&snapshot(t.clone()), &["release", "held"]);
    t.holds[0].notified = true;
    expect(&snapshot(t.clone()), &["release"]);
    t.held_label_comment = Some(n(5001));
    expect(&snapshot(t.clone()), &[]);
    t.held_label_comment = Some(n(4998));
    let mut s = snapshot(t);
    fleet(&mut s).fingerprint_now = fp('e');
    expect(&s, &[]);
    let mut t = ready();
    t.issue.labels = vec![text("needs-info"), text("ready-for-agent")];
    t.question = Some(n(5100));
    expect(&snapshot(t.clone()), &["needs_info"]);
    t.records.question_passed = Some(n(5100));
    expect(&snapshot(t.clone()), &[]);
    t.question = Some(n(5101));
    expect(&snapshot(t), &["needs_info"]);
    let mut t = ready();
    t.issue.labels = vec![text("ready-for-human")];
    let mut s = snapshot(t);
    fleet(&mut s)
        .approval
        .as_mut()
        .unwrap()
        .rows
        .insert(n(901), Ready::Human);
    expect(&s, &["person_ready"]);
    ticket(&mut s).records.person_notified = true;
    expect(&s, &[]);
    let mut s = snapshot(ready());
    fleet(&mut s).fingerprint_now = fp('e');
    expect(&s, &["re_approve"]);
    fleet(&mut s).records.approval_notified.push(fp('e'));
    expect(&s, &[]);
}

fn b2_close_archive_summary_and_unlock_only_after_readback() {
    let mut t = ready();
    t.pr = Some(PrInput::Merged(merged(1901)));
    expect(&snapshot(t.clone()), &["merged"]);
    if let Some(PrInput::Merged(m)) = &mut t.pr {
        m.read_back = false;
    }
    let v = run(&snapshot(t));
    assert!(!rules(&v).contains(&"merged"));
    let mut t = approved();
    t.issue.state = IssueState::Closed;
    let mut s = snapshot(t);
    fleet(&mut s).records.summary_written = true;
    let v = expect(&s, &["finished"]);
    assert_eq!(
        v["actions"][0]["facts"]["threads"],
        json!([{"thread":"syn-builder","role":"builder"},{"thread":"syn-reviewer","role":"reviewer"}])
    );
    ticket(&mut s).builder.as_mut().unwrap().archived = true;
    ticket(&mut s).reviewers[0].agent.archived = true;
    ticket(&mut s).records.archived = true;
    expect(&s, &["all_closed"]);
    fleet(&mut s).records.summary_written = false;
    expect(&s, &["spec_summary"]);
    fleet(&mut s).follow_ups = vec![n(999)];
    let v = expect(&s, &["spec_summary"]);
    assert_eq!(v["actions"][0]["facts"]["follow_ups"], json!([999]));
    fleet(&mut s).records.summary_written = true;
    expect(&s, &[]);
    fleet(&mut s).tickets.clear();
    fleet(&mut s).approval.as_mut().unwrap().rows.clear();
    expect(&s, &[]);
    let mut s = snapshot(ready());
    ticket(&mut s).blockers.push(BlockerInput {
        number: n(800),
        state: IssueState::Open,
        merged: Some(merged(1800)),
    });
    expect(&s, &[]);
    ticket(&mut s).blockers[0].state = IssueState::Closed;
    expect(&s, &["frontier"]);
}

fn b2_summary_excludes_closed_unapproved_subissues() {
    let mut closed = ready();
    closed.issue.state = IssueState::Closed;
    let mut s = snapshot(closed.clone());
    fleet(&mut s).tickets.push(TicketInput {
        number: n(902),
        facts: Observed::Complete(closed),
    });
    fleet(&mut s).tickets.push(TicketInput {
        number: n(903),
        facts: Observed::Complete(ready()),
    });
    let v = expect(&s, &["spec_summary"]);
    assert_eq!(v["actions"][0]["facts"]["follow_ups"], json!([903]));
    fleet(&mut s).records.summary_written = true;
    expect(&s, &[]);
    let Observed::Complete(t) = &mut fleet(&mut s).tickets[2].facts else {
        panic!("ticket")
    };
    t.issue.state = IssueState::Closed;
    let v = expect(&s, &["all_closed"]);
    assert_eq!(v["actions"][0]["facts"]["tickets"], json!([901, 902, 903]));
}

fn b2_unknown_and_duplicate_inputs_fail_closed() {
    for problem in [
        Problem::Issue,
        Problem::Approval,
        Problem::Graph,
        Problem::Blockers,
        Problem::PullRequest,
        Problem::Checks,
        Problem::Reports,
        Problem::Agents,
        Problem::Starts,
        Problem::Records,
        Problem::Contracts,
        Problem::FollowUps,
    ] {
        let mut s = snapshot(approved());
        fleet(&mut s).tickets[0].facts = Observed::Unread(vec![problem]);
        expect(&s, &["look"]);
    }
    let mut s = snapshot(approved());
    fleet(&mut s).tickets[0].facts =
        Observed::Unread(vec![Problem::Reports, Problem::Checks, Problem::Reports]);
    let v = expect(&s, &["look"]);
    assert_eq!(
        v["actions"][0]["facts"]["reason"],
        "checks unread; reports unread"
    );
    let mut t = approved();
    t.pr = Some(PrInput::Several(vec![n(1901), n(1902)]));
    expect(&snapshot(t), &["look"]);
    let mut t = approved();
    let r = t.reviewers[0].clone();
    t.reviewers.push(r);
    expect(&snapshot(t), &["look"]);
    let mut s = snapshot(ready());
    let t = fleet(&mut s).tickets[0].clone();
    fleet(&mut s).tickets.push(t);
    assert!(plan(&s, &Rules::parse(RULES, &flags()).unwrap(), NOW).is_err());
    let mut s = snapshot(ready());
    s.fleets = Observed::Unread(vec![Problem::Graph]);
    assert!(plan(&s, &Rules::parse(RULES, &flags()).unwrap(), NOW).is_err());
    let mut s = snapshot(ready());
    s.default_branch = Observed::Unread(vec![Problem::Issue]);
    assert!(plan(&s, &Rules::parse(RULES, &flags()).unwrap(), NOW).is_err());
}

fn b2_release_default_starts_nothing() {
    let mut s = snapshot(ready());
    s.default_branch = Observed::Complete(text("release-0.0.6"));
    expect(&s, &[]);
}

fn b2_recorded_review_starts_allow_rechecks_and_closed_merged_agents_archive() {
    let mut t = reviewing();
    let mut r = reviewer();
    r.head = commit('c');
    r.output = Some(Review {
        verdict: Verdict::Approve,
        commit: commit('c'),
    });
    t.reviewers.push(r);
    pr(&mut t).starts.push(start(StartState::Started {
        thread: text("syn-reviewer"),
    }));
    expect(&snapshot(t.clone()), &["re_check"]);
    t.reviewers[0].given_up = true;
    expect(&snapshot(t.clone()), &["fresh_review"]);
    t.issue.state = IssueState::Closed;
    t.pr = Some(PrInput::Merged(merged(1901)));
    let mut s = snapshot(t);
    fleet(&mut s).records.summary_written = true;
    let v = expect(&s, &["finished"]);
    assert_eq!(
        v["actions"][0]["facts"]["threads"],
        json!([{"thread":"syn-builder","role":"builder"},{"thread":"syn-reviewer","role":"reviewer"}])
    );
}

fn b2_person_ready_has_only_the_conditions_the_contract_names() {
    let mut t = ready();
    t.issue.labels = vec![text("ready-for-human"), text("needs-info")];
    let mut s = snapshot(t);
    fleet(&mut s)
        .approval
        .as_mut()
        .unwrap()
        .rows
        .insert(n(901), Ready::Human);
    expect(&s, &["person_ready"]);
}

fn b2_missing_review_and_send_conditions() {
    type Spoil = fn(&mut TicketFacts);
    let review_cases: &[(&str, Spoil)] = &[
        ("not handback", |t| pr(t).subject = "Synthetic fix".into()),
        ("draft", |t| pr(t).fields.draft = true),
        ("other base", |t| pr(t).fields.base_branch = text("scratch")),
        ("no closing link", |t| pr(t).fields.closes.clear()),
        ("CI absent", |t| pr(t).ci = None),
        ("CI old head", |t| {
            pr(t).ci.as_mut().unwrap().head_commit = commit('c')
        }),
        ("missing required", |t| {
            pr(t).ci.as_mut().unwrap().checks.pop();
        }),
        ("required skipping", |t| {
            pr(t).ci.as_mut().unwrap().checks[0].result = CheckResult::Skipping
        }),
        ("pending optional", |t| {
            pr(t).ci.as_mut().unwrap().checks.push(Check {
                name: text("extra"),
                result: CheckResult::Pending,
            })
        }),
    ];
    for (name, spoil) in review_cases {
        for mode in [0, 1, 2] {
            let mut t = reviewing();
            if mode > 0 {
                let mut r = reviewer();
                r.given_up = mode == 1;
                r.head = commit('c');
                t.reviewers.push(r);
            }
            spoil(&mut t);
            let v = run(&snapshot(t));
            assert!(
                !v["actions"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|a| a["kind"] == "start_reviewer"),
                "{name} mode {mode}"
            );
        }
    }
    for (name, spoil) in review_cases {
        let mut t = changes();
        spoil(&mut t);
        let v = run(&snapshot(t));
        assert!(!rules(&v).contains(&"review_findings"), "{name}");
    }
    for result in [
        CheckResult::Pass,
        CheckResult::Pending,
        CheckResult::Skipping,
    ] {
        let mut t = reviewing();
        pr(&mut t).ci.as_mut().unwrap().checks[0].result = result;
        assert!(!rules(&run(&snapshot(t))).contains(&"ci_failed"));
    }
    let mut t = changes();
    t.builder = None;
    let v = run(&snapshot(t));
    assert!(!rules(&v).contains(&"review_findings"));
    let mut t = changes();
    pr(&mut t).reports[0].text = format!("VERDICT: CHANGES at {}", commit('c').as_str());
    let v = run(&snapshot(t));
    assert!(
        !rules(&v)
            .iter()
            .any(|r| ["review_findings", "disputed", "diagnosis"].contains(r))
    );
}

fn b2_lifecycle_missing_conditions_and_exact_once_records() {
    let mut t = ready();
    t.blockers.push(BlockerInput {
        number: n(801),
        state: IssueState::Open,
        merged: Some(merged(1801)),
    });
    expect(&snapshot(t), &[]);
    let mut s = snapshot(ready());
    fleet(&mut s).fingerprint_now = fp('e');
    ticket(&mut s).issue.labels.push(text("held"));
    expect(&s, &[]);
    let mut t = ready();
    t.issue.labels = vec![text("needs-info")];
    expect(&snapshot(t.clone()), &[]);
    t.question = Some(n(5100));
    t.issue.labels.clear();
    expect(&snapshot(t), &[]);
    let h = Hold {
        comment: n(5000),
        merged: MergeFact {
            number: n(1950),
            merge_commit: commit('c'),
        },
        files: vec![text("contracts/a.md")],
        notified: true,
    };
    for mode in [0, 1, 2] {
        let mut t = ready();
        t.holds.push(h.clone());
        t.held_label_comment = Some(n(4999));
        if mode != 0 {
            t.issue.labels = vec![text("held")];
        }
        let mut s = snapshot(t);
        if mode == 1 {
            fleet(&mut s).approval.as_mut().unwrap().approval.comment = n(4999);
        }
        let v = run(&s);
        assert!(!rules(&v).contains(&"release"), "mode {mode}");
    }
    let mut t = reviewing();
    pr(&mut t).ci.as_mut().unwrap().checks[0].result = CheckResult::Cancel;
    expect(&snapshot(t.clone()), &["ci_failed"]);
    pr(&mut t).records.ci_sent.push(commit('a'));
    expect(&snapshot(t), &[]);
    let mut t = ready();
    t.starts.push(start(StartState::Refused {
        reason: StartReason::Refused,
    }));
    let mut second = start(StartState::Failed {
        reason: StartReason::Interrupted,
    });
    second.id = openwiz_core::messaging::OpId::parse("syn-start-902").unwrap();
    t.starts.push(second);
    let v = expect(&snapshot(t.clone()), &["frontier", "builder_refused"]);
    assert_eq!(v["actions"][1]["facts"]["start"], "syn-start-901");
    t.starts[0].logged = true;
    let v = expect(&snapshot(t), &["frontier", "builder_refused"]);
    assert_eq!(v["actions"][1]["facts"]["start"], "syn-start-902");
    let mut t = ready();
    t.pr = Some(PrInput::Several(vec![n(1901), n(1902)]));
    let v = expect(&snapshot(t.clone()), &["look"]);
    t.records
        .looked
        .push(v["actions"][0]["facts"]["reason"].as_str().unwrap().into());
    expect(&snapshot(t), &[]);
    let mut s = snapshot(ready());
    fleet(&mut s).tickets[0].facts = Observed::Unread(vec![Problem::Issue]);
    fleet(&mut s).records.summary_written = true;
    expect(&s, &["look"]);
}

fn b2_actions_and_fact_lists_have_the_contract_order() {
    let mut t = changes();
    pr(&mut t).reports[0].text = format!(
        "VERDICT: CHANGES at {}\n- **R10 [medium]** disputed, kept: Synthetic\n- **R2 [high]** disputed, kept: Synthetic\n- **R11 [high]** still open after 2 rounds: Synthetic\n- **R3 [medium]** still open after 4 rounds: Synthetic",
        commit('a').as_str()
    );
    let v = expect(&snapshot(t), &["review_findings", "disputed", "diagnosis"]);
    assert_eq!(v["actions"][1]["facts"]["findings"], json!(["R2", "R10"]));
    assert_eq!(
        v["actions"][2]["facts"]["findings"],
        json!([{"id":"R3","rounds":4},{"id":"R11","rounds":2}])
    );
    let mut s = snapshot(ready());
    let mut other = fleet(&mut s).tickets[0].clone();
    other.number = n(902);
    fleet(&mut s).tickets.insert(0, other);
    fleet(&mut s)
        .approval
        .as_mut()
        .unwrap()
        .rows
        .insert(n(902), Ready::Agent);
    let v = expect(&s, &["frontier", "frontier"]);
    assert_eq!(v["actions"][0]["ticket"], 901);
    assert_eq!(v["actions"][1]["ticket"], 902);
    let mut s = snapshot(ready());
    ticket(&mut s).blockers = vec![
        BlockerInput {
            number: n(802),
            state: IssueState::Closed,
            merged: Some(merged(1802)),
        },
        BlockerInput {
            number: n(801),
            state: IssueState::Closed,
            merged: Some(merged(1801)),
        },
    ];
    let v = expect(&s, &["frontier"]);
    assert_eq!(v["actions"][0]["facts"]["blockers"][0]["number"], 801);
    assert_eq!(v["actions"][0]["facts"]["blockers"][1]["number"], 802);
    let mut s = snapshot(ready());
    ticket(&mut s).relies_on = vec![text("contracts/")];
    let mut c = change(1950, "contracts/z.md");
    c.files.push(ChangedFile {
        path: text("contracts/a.md"),
        previous_path: None,
        added: false,
    });
    fleet(&mut s).changes = vec![c];
    let v = expect(&s, &["contract_hold"]);
    assert_eq!(
        v["actions"][0]["facts"]["files"],
        json!(["contracts/a.md", "contracts/z.md"])
    );
}

fn b2_human_ticket_pr_uses_the_same_merge_conditions() {
    let mut t = approved();
    t.issue.labels = vec![text("ready-for-human")];
    let mut s = snapshot(t);
    fleet(&mut s)
        .approval
        .as_mut()
        .unwrap()
        .rows
        .insert(n(901), Ready::Human);
    expect(&s, &["adr_0008", "person_ready"]);
}

fn b2_verified_merge_closes_even_without_a_current_plan_row() {
    let mut t = ready();
    t.pr = Some(PrInput::Merged(merged(1901)));
    let mut s = snapshot(t);
    fleet(&mut s).approval = None;
    expect(&s, &["merged"]);
}

fn b2_finding_ids_have_no_zero_or_leading_zero() {
    for id in ["R0", "R01"] {
        let mut t = changes();
        pr(&mut t).reports[0].text = format!(
            "VERDICT: CHANGES at {}\n- **{id} [medium]** disputed, kept: Synthetic",
            commit('a').as_str()
        );
        expect(&snapshot(t), &["look"]);
    }
}

fn b2_an_earlier_start_without_review_is_not_a_recheck() {
    let mut t = reviewing();
    let mut r = reviewer();
    r.head = commit('c');
    r.output = None;
    t.reviewers.push(r);
    expect(&snapshot(t), &[]);
}

fn b2_look_record_does_not_prove_the_spec_is_archived() {
    let mut t = ready();
    t.issue.state = IssueState::Closed;
    t.starts.push(start(StartState::Pending));
    t.records.looked.push("start outcome unsettled".into());
    let mut s = snapshot(t);
    fleet(&mut s).records.summary_written = true;
    expect(&s, &[]);
}

fn b2_manual_merge_row_means_none() {
    let manual = RULES.replace(
        "The loop, as soon as the reviewer's APPROVE names that exact commit and all checks pass",
        "The user only",
    );
    let rules = Rules::parse(&manual, &flags()).expect("manual merge policy is valid");
    assert_eq!(serde_json::to_value(rules).unwrap()["merge"], "none");
}

fn b2_a_merge_must_close_the_exact_ticket_or_blocker() {
    let mut m = merged(1901);
    m.pr.fields.closes = vec![n(999)];
    let mut t = ready();
    t.pr = Some(PrInput::Merged(m));
    expect(&snapshot(t), &[]);
    let mut m = merged(1801);
    m.pr.fields.closes = vec![n(999)];
    let mut t = ready();
    t.blockers = vec![BlockerInput {
        number: n(801),
        state: IssueState::Closed,
        merged: Some(m),
    }];
    expect(&snapshot(t), &[]);
}

fn b2_archived_reviewers_are_never_quiet_reviewers() {
    let mut t = reviewing();
    t.issue.state = IssueState::Closed;
    t.builder.as_mut().unwrap().archived = true;
    let mut r = reviewer();
    r.agent.archived = true;
    r.output = None;
    r.last_activity_at = 0;
    t.reviewers.push(r);
    t.records.archived = true;
    let mut s = snapshot(t);
    fleet(&mut s).records.summary_written = true;
    expect(&s, &["all_closed"]);
}

fn b2_relays_do_not_grant_start_or_merge_authority() {
    fn authority(s: &mut Snapshot, case: &str) {
        match case {
            "current" => {}
            "stale" => fleet(s).fingerprint_now = fp('e'),
            "dropped" => fleet(s).approval.as_mut().unwrap().rows.clear(),
            "absent" => fleet(s).approval = None,
            _ => unreachable!(),
        }
    }
    for case in ["current", "stale", "dropped", "absent"] {
        let authorised = case == "current";
        let mut question = ready();
        question.issue.labels = vec![text("needs-info")];
        question.question = Some(n(5100));
        let mut refused_builder = ready();
        refused_builder.issue.labels.clear();
        refused_builder.starts.push(start(StartState::Refused {
            reason: StartReason::Refused,
        }));
        let mut failed_ci = reviewing();
        pr(&mut failed_ci).ci.as_mut().unwrap().checks[0].result = CheckResult::Fail;
        let mut refused_reviewer = reviewing();
        pr(&mut refused_reviewer)
            .starts
            .push(start(StartState::Failed {
                reason: StartReason::Interrupted,
            }));
        let relays: Vec<(&str, TicketFacts, &[&str])> = vec![
            ("question", question, &["needs_info"]),
            ("builder refusal", refused_builder, &["builder_refused"]),
            (
                "findings",
                changes(),
                &["review_findings", "disputed", "diagnosis"],
            ),
            ("CI failure", failed_ci, &["ci_failed"]),
            (
                "reviewer refusal",
                refused_reviewer,
                if authorised {
                    &["first_review", "reviewer_refused"]
                } else {
                    &["reviewer_refused"]
                },
            ),
        ];
        for (name, facts, expected) in relays {
            let mut s = snapshot(facts);
            authority(&mut s, case);
            let value = run(&s);
            assert_eq!(rules(&value), expected, "{case}: {name}");
            if !authorised {
                assert!(
                    value["actions"].as_array().unwrap().iter().all(|a| ![
                        "start_builder",
                        "start_reviewer",
                        "merge"
                    ]
                    .contains(&a["kind"].as_str().unwrap())),
                    "{case}: {name}"
                );
            }
            fleet(&mut s).tickets[0].facts = Observed::Unread(vec![Problem::Records]);
            expect(&s, &["look"]);
        }
        let mut recheck = reviewing();
        let mut r = reviewer();
        r.head = commit('c');
        r.output = Some(Review {
            verdict: Verdict::Changes,
            commit: commit('c'),
        });
        recheck.reviewers.push(r);
        for (facts, allowed) in [
            (ready(), "frontier"),
            (reviewing(), "first_review"),
            (recheck, "re_check"),
            (approved(), "adr_0008"),
        ] {
            let mut s = snapshot(facts);
            authority(&mut s, case);
            let value = run(&s);
            assert_eq!(
                rules(&value).contains(&allowed),
                authorised,
                "{case}: {allowed}"
            );
            if !authorised {
                assert!(
                    value["actions"].as_array().unwrap().iter().all(|a| ![
                        "start_builder",
                        "start_reviewer",
                        "merge"
                    ]
                    .contains(&a["kind"].as_str().unwrap())),
                    "{case}: {allowed}"
                );
            }
        }
    }
}

fn b2_r1_unrecognised_round_status_still_relays_findings() {
    for (status, diagnose) in [
        ("still open after 1 round: Synthetic", false),
        ("still open after two rounds: Synthetic", false),
        ("still open after 2 round: Synthetic", false),
        ("still open after 2 rounds : Synthetic", false),
        ("still open after -2 rounds: Synthetic", false),
        ("still open after +2 rounds: Synthetic", false),
        ("still open after 2.0 rounds: Synthetic", false),
        ("still open after ２ rounds: Synthetic", false),
        ("still open after  2 rounds: Synthetic", false),
        ("still open after 0 rounds: Synthetic", false),
        ("still open after 1 rounds: Synthetic", false),
        ("still open after 2 rounds: Synthetic", true),
        ("still open after 3 rounds: Synthetic", true),
        ("new: Synthetic", false),
        ("resolved: Synthetic", false),
    ] {
        let mut t = changes();
        pr(&mut t).reports[0].text = format!(
            "VERDICT: CHANGES at {}\n- **R1 [medium]** {status}",
            commit('a').as_str()
        );
        let expected: &[&str] = if diagnose {
            &["review_findings", "diagnosis"]
        } else {
            &["review_findings"]
        };
        expect(&snapshot(t.clone()), expected);
        t.records.looked.push("malformed finding rounds".into());
        expect(&snapshot(t), expected);
    }
}

fn b2_r2_quiet_reviewers_follow_their_own_head() {
    for (name, earlier, elapsed, given_up, evidence, other_pr, expected) in [
        (
            "earlier head at deadline",
            true,
            1_800_000,
            false,
            "none",
            false,
            "look",
        ),
        (
            "earlier head past deadline",
            true,
            1_800_001,
            false,
            "none",
            false,
            "look",
        ),
        (
            "earlier head before deadline",
            true,
            1_799_999,
            false,
            "none",
            false,
            "",
        ),
        (
            "current head at deadline",
            false,
            1_800_000,
            false,
            "none",
            false,
            "look",
        ),
        (
            "own output names earlier head",
            true,
            1_800_000,
            false,
            "output",
            false,
            "re_check",
        ),
        (
            "latest report names earlier head",
            true,
            1_800_000,
            false,
            "report",
            false,
            "re_check",
        ),
        (
            "output names another head",
            true,
            1_800_000,
            false,
            "wrong_output",
            false,
            "look",
        ),
        (
            "given up",
            true,
            1_800_000,
            true,
            "none",
            false,
            "fresh_review",
        ),
        (
            "reviewer of another PR",
            true,
            1_800_000,
            false,
            "none",
            true,
            "first_review",
        ),
    ] {
        let mut t = reviewing();
        let mut r = reviewer();
        r.head = if earlier { commit('c') } else { commit('a') };
        r.last_activity_at = NOW - elapsed;
        r.given_up = given_up;
        r.output = None;
        if evidence == "output" || evidence == "wrong_output" {
            r.output = Some(Review {
                verdict: Verdict::Changes,
                commit: if evidence == "output" {
                    r.head.clone()
                } else {
                    commit('b')
                },
            });
        }
        if evidence == "report" {
            pr(&mut t).reports.push(ReportComment {
                comment: n(5900),
                text: format!("VERDICT: CHANGES at {}", r.head.as_str()),
            });
        }
        if other_pr {
            r.pr = n(1902);
        }
        t.reviewers.push(r);
        let value = run(&snapshot(t));
        let expected: Vec<&str> = if expected.is_empty() {
            vec![]
        } else {
            vec![expected]
        };
        assert_eq!(rules(&value), expected, "{name}");
    }
}

fn b2_r3_quiet_look_records_apply_to_one_episode() {
    let mut t = reviewing();
    let mut r = reviewer();
    r.output = None;
    r.last_activity_at = 200_000;
    t.reviewers.push(r);
    let mut s = snapshot(t);
    let first = expect(&s, &["look"]);
    let recorded = first["actions"][0]["facts"]["reason"]
        .as_str()
        .unwrap()
        .to_owned();
    ticket(&mut s).records.looked.push(recorded);
    expect(&s, &[]);
    for (head, activity, now, expected_reason) in [
        (
            'a',
            2_000_001,
            3_800_001,
            "reviewer quiet for 30 minutes on aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa since 2000001",
        ),
        (
            'c',
            200_000,
            2_000_000,
            "reviewer quiet for 30 minutes on cccccccccccccccccccccccccccccccccccccccc since 200000",
        ),
    ] {
        let mut next = s.clone();
        let t = ticket(&mut next);
        t.reviewers[0].head = commit(head);
        t.reviewers[0].last_activity_at = activity;
        pr(t).fields.head_commit = commit(head);
        pr(t).ci.as_mut().unwrap().head_commit = commit(head);
        let value = run_at(&next, now);
        assert_eq!(rules(&value), ["look"], "next episode on {head}");
        assert_eq!(value["actions"][0]["facts"]["reason"], expected_reason);
        ticket(&mut next)
            .records
            .looked
            .push(expected_reason.into());
        assert_eq!(rules(&run_at(&next, now)), Vec::<&str>::new());
    }
}

fn b2_r3_blocked_merge_look_records_apply_to_one_head() {
    let mut t = approved();
    pr(&mut t).records.merge_blocked.push(commit('a'));
    let mut s = snapshot(t);
    let first = expect(&s, &["look"]);
    let recorded = first["actions"][0]["facts"]["reason"]
        .as_str()
        .unwrap()
        .to_owned();
    ticket(&mut s).records.looked.push(recorded);
    expect(&s, &[]);
    let t = ticket(&mut s);
    let p = pr(t);
    p.fields.head_commit = commit('c');
    p.ci.as_mut().unwrap().head_commit = commit('c');
    p.reports[0].text = format!("VERDICT: APPROVE at {}", commit('c').as_str());
    p.records.merge_blocked.push(commit('c'));
    t.reviewers[0].head = commit('c');
    t.reviewers[0].output.as_mut().unwrap().commit = commit('c');
    let value = expect(&s, &["look"]);
    let expected_reason =
        "merge blocked on the approved head cccccccccccccccccccccccccccccccccccccccc";
    assert_eq!(value["actions"][0]["facts"]["reason"], expected_reason);
    ticket(&mut s).records.looked.push(expected_reason.into());
    expect(&s, &[]);
}

fn b2_summary_waits_for_closed_tickets_with_unverified_merges() {
    for planned in [true, false] {
        for invalid in 0..3 {
            let mut t = ready();
            t.issue.state = IssueState::Closed;
            let mut m = merged(1901);
            match invalid {
                0 => m.read_back = false,
                1 => m.pr.fields.base_branch = text("scratch"),
                _ => m.pr.fields.closes = vec![n(902)],
            }
            t.pr = Some(PrInput::Merged(m));
            let mut s = snapshot(t);
            if !planned {
                fleet(&mut s).approval.as_mut().unwrap().rows =
                    BTreeMap::from([(n(902), Ready::Human)]);
                let mut closed = ready();
                closed.issue.state = IssueState::Closed;
                fleet(&mut s).tickets.push(TicketInput {
                    number: n(902),
                    facts: Observed::Complete(closed),
                });
            }
            expect(&s, &[]);
            ticket(&mut s).pr = Some(PrInput::Merged(merged(1901)));
            let v = expect(&s, &["spec_summary"]);
            assert_eq!(
                v["actions"][0]["facts"],
                json!({"merged": [{"ticket": 901, "pr": 1901}], "follow_ups": []})
            );
        }
    }
}

fn b2_summary_waits_for_ambiguous_pull_requests() {
    let mut t = ready();
    t.issue.state = IssueState::Closed;
    let v = expect(&snapshot(t.clone()), &["spec_summary"]);
    assert_eq!(
        v["actions"][0]["facts"],
        json!({"merged": [], "follow_ups": []})
    );
    t.pr = Some(PrInput::Merged(merged(1901)));
    let v = expect(&snapshot(t.clone()), &["spec_summary"]);
    assert_eq!(
        v["actions"][0]["facts"],
        json!({"merged": [{"ticket": 901, "pr": 1901}], "follow_ups": []})
    );
    t.pr = Some(PrInput::Several(vec![n(1901), n(1902)]));
    let mut s = snapshot(t);
    let v = expect(&s, &["look"]);
    assert_eq!(v["actions"][0]["ticket"], 901);
    assert_eq!(
        v["actions"][0]["facts"]["reason"],
        "more than one open pull request"
    );
    ticket(&mut s)
        .records
        .looked
        .push("more than one open pull request".into());
    expect(&s, &[]);
    ticket(&mut s).records.looked.clear();
    let mut independent = ready();
    independent.issue.state = IssueState::Closed;
    independent.builder = Some(agent("syn-independent-builder"));
    fleet(&mut s).tickets.push(TicketInput {
        number: n(902),
        facts: Observed::Complete(independent),
    });
    let v = expect(&s, &["look", "finished"]);
    assert_eq!(v["actions"][0]["ticket"], 901);
    assert_eq!(v["actions"][1]["ticket"], 902);
    assert_eq!(
        v["actions"][1]["facts"]["threads"],
        json!([{"thread": "syn-independent-builder", "role": "builder"}])
    );
}

#[test]
fn md3_models_table_reviews_wait_or_fall_back_to_the_builder() {
    let agent = |harness: &str, model: &str, effort: &str| json!({"harness": harness, "model": model, "effort": effort});
    let opus = agent("claude-code", "claude-opus-5-5", "medium");
    let sol = agent("codex", "gpt-6.2-sol", "medium");
    let high = agent("claude-code", "claude-opus-5-5", "high");
    for (case, family, given_up, rule, settings) in [
        (
            "one-table",
            BuilderFamily::Claude,
            false,
            "first_review",
            Some(&sol),
        ),
        (
            "one-table",
            BuilderFamily::Gpt,
            false,
            "first_review",
            Some(&opus),
        ),
        (
            "one-table",
            BuilderFamily::Gpt,
            true,
            "fresh_review",
            Some(&opus),
        ),
        (
            "same-family",
            BuilderFamily::Gpt,
            false,
            "first_review",
            Some(&high),
        ),
        ("same-family", BuilderFamily::Claude, false, "look", None),
        ("same-family", BuilderFamily::Claude, true, "look", None),
    ] {
        let mut t = reviewing();
        if let Some(source) = t.builder_source.as_mut() {
            source.family = family;
        }
        if given_up {
            let mut r = reviewer();
            r.given_up = true;
            t.reviewers.push(r);
        }
        let v = run_with(&snapshot(t), &fixture(case), NOW);
        let name = format!("{case} {family:?} given up {given_up}");
        assert_eq!(rules(&v), [rule], "{name}");
        let facts = &v["actions"][0]["facts"];
        match settings {
            Some(want) => assert_eq!(&facts["settings"], want, "{name}"),
            None => assert_eq!(
                facts["reason"], "review waits: no other-family reviewer",
                "{name}"
            ),
        }
    }
    let namespaced = fixture("one-table").replacen("--model gpt-6.2-sol", "--model vendor/demo", 1);
    assert!(Rules::parse(&namespaced, &flags()).is_ok());
    let mut t = reviewing();
    if let Some(source) = t.builder_source.as_mut() {
        source.family = BuilderFamily::Claude;
    }
    let v = run_with(&snapshot(t), &namespaced, NOW);
    assert_eq!(v["actions"][0]["facts"]["settings"]["model"], "vendor/demo");
}
