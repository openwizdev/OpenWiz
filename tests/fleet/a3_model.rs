//! A3 (ClosedWiz#111): the contract's model types
//! (`openwiz_core::fleet::model`), data only, match `contracts/fleet.v1.*`
//! exactly:
//! - **The contract's three examples round-trip:** each, read into the
//!   model types by this file's test-only reader and printed again, is the
//!   example itself.
//! - **Every branch of the schema is reachable:** those values, and a few
//!   more built here, validate against the schema and between them take
//!   every `oneOf` alternative, `enum` value, `type` of a list and property.
//! - **The checker itself** refuses what it exists to refuse.
//! - **The types hold no bad value:** text that must not be empty, a
//!   commit, a read id, a constant.

use std::num::NonZeroU64;

use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::fleet::model::{
    Blocker, Check, CheckResult, CloudRoomSource, Commit, Counts, Coverage, Envelope, Failed,
    Fleet, FleetView, FleetsView, Freshness, Gh, GitHubSource, Issue, IssueState, ListOutcome,
    MergedPr, Milestone, NeedsYou, NeedsYouKind, NeedsYouRisk, NonEmpty, Number, Outcome,
    PendingQuestion, PrFields, Project, PullRequest, Read, ReadId, ReadKind, Repository, Review,
    Reviewer, RoomCli, SCHEMA_ID, SchemaId, SourceName, Sources, State, Thread, Ticket, TicketCore,
    TicketState, Truncated, Unplaced, UnplacedReason, Verdict, View, WorkedOut,
};
use openwiz_core::model::{Fact, Timestamp};
use serde_json::{Value, json};

use crate::schema::{self, branches, lint, load_schema, validate, validate_with};

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/fleet.v1.md");

/// The contract's examples: every ```json block of `fleet.v1.md`.
fn examples() -> Vec<Value> {
    let text = std::fs::read_to_string(CONTRACT).expect("the fleet contract");
    let blocks: Vec<Value> = text
        .split("```json\n")
        .skip(1)
        .map(|rest| rest.split("\n```").next().expect("a closed block"))
        .map(|block| serde_json::from_str(block).expect("an example is JSON"))
        .collect();
    assert_eq!(blocks.len(), 3, "the contract has three examples");
    blocks
}

// The test-only reader: a contract example into the model types. Not
// strict (the round trip finds anything it drops or changes), and never
// used by OpenWiz itself.

fn object(v: &Value) -> &serde_json::Map<String, Value> {
    v.as_object()
        .unwrap_or_else(|| panic!("not an object: {v}"))
}

fn text(v: &Value) -> String {
    v.as_str()
        .unwrap_or_else(|| panic!("not a string: {v}"))
        .to_owned()
}

fn non_empty(v: &Value) -> NonEmpty {
    NonEmpty::new(text(v)).unwrap_or_else(|| panic!("empty: {v}"))
}

fn maybe<T>(v: &Value, read: impl Fn(&Value) -> T) -> Option<T> {
    (!v.is_null()).then(|| read(v))
}

fn list<T>(v: &Value, read: impl Fn(&Value) -> T) -> Vec<T> {
    v.as_array()
        .unwrap_or_else(|| panic!("not a list: {v}"))
        .iter()
        .map(read)
        .collect()
}

fn number(v: &Value) -> Number {
    v.as_u64()
        .and_then(NonZeroU64::new)
        .unwrap_or_else(|| panic!("not a number: {v}"))
}

fn count(v: &Value) -> u64 {
    v.as_u64().unwrap_or_else(|| panic!("not a count: {v}"))
}

fn flag(v: &Value) -> bool {
    v.as_bool().unwrap_or_else(|| panic!("not a bool: {v}"))
}

fn read_id(v: &Value) -> ReadId {
    let s = text(v);
    ReadId(
        s.strip_prefix('r')
            .and_then(|n| n.parse().ok())
            .unwrap_or_else(|| panic!("{s}")),
    )
}

fn commit(v: &Value) -> Commit {
    Commit::parse(&text(v)).unwrap_or_else(|| panic!("not a commit: {v}"))
}

/// A unit enum from its JSON string, through its own printed form.
macro_rules! label {
    ($v:expr, $all:expr $(,)?) => {{
        let v: &Value = $v;
        $all.into_iter()
            .find(|t| serde_json::to_value(t).unwrap() == *v)
            .unwrap_or_else(|| panic!("not a label: {v}"))
    }};
}

const GAPS: [GapKind; 8] = [
    GapKind::UntestedVersion,
    GapKind::CommandFailed,
    GapKind::TimedOut,
    GapKind::BudgetExhausted,
    GapKind::Malformed,
    GapKind::MissingField,
    GapKind::WrongType,
    GapKind::NotFound,
];

fn failed(v: &Value) -> Failed {
    Failed {
        gap: label!(&v["gap"], GAPS),
        reason: non_empty(&v["reason"]),
    }
}

fn outcome<T>(v: &Value, value: impl Fn(&Value) -> T) -> Outcome<T> {
    match v["state"].as_str() {
        Some("complete") => Outcome::Complete {
            value: value(&v["value"]),
        },
        Some("failed") => Outcome::Failed(failed(v)),
        _ => panic!("not an outcome: {v}"),
    }
}

fn list_outcome<T>(v: &Value, item: impl Fn(&Value) -> T) -> ListOutcome<T> {
    match v["state"].as_str() {
        Some("complete") => ListOutcome::Complete {
            value: list(&v["value"], item),
        },
        Some("partial") => ListOutcome::Partial {
            gap: label!(&v["gap"], [Truncated::Truncated]),
            reason: non_empty(&v["reason"]),
            value: list(&v["value"], item),
        },
        Some("failed") => ListOutcome::Failed(failed(v)),
        _ => panic!("not a list outcome: {v}"),
    }
}

fn issue(v: &Value) -> Issue {
    Issue {
        title: text(&v["title"]),
        state: label!(&v["state"], [IssueState::Open, IssueState::Closed]),
        milestone: maybe(&v["milestone"], |m| Milestone {
            number: number(&m["number"]),
            title: text(&m["title"]),
        }),
        labels: list(&v["labels"], non_empty),
        owned_paths: maybe(&v["owned_paths"], non_empty),
        relies_on: maybe(&v["relies_on"], non_empty),
        pending_question: maybe(&v["pending_question"], |q| PendingQuestion {
            wording: non_empty(&q["wording"]),
            link: non_empty(&q["link"]),
            asked_at: Timestamp(q["asked_at"].as_i64().expect("asked time")),
        }),
    }
}

fn pr_fields(v: &Value) -> PrFields {
    PrFields {
        number: number(&v["number"]),
        draft: flag(&v["draft"]),
        head_branch: non_empty(&v["head_branch"]),
        head_commit: commit(&v["head_commit"]),
        base_branch: non_empty(&v["base_branch"]),
        closes: list(&v["closes"], number),
    }
}

fn pull_request(v: &Value) -> PullRequest {
    match v["state"].as_str() {
        Some("open") => PullRequest::Open(pr_fields(v)),
        Some("merged") => PullRequest::Merged(MergedPr {
            fields: pr_fields(v),
            merge_commit: commit(&v["merge_commit"]),
            merged_at: Timestamp(v["merged_at"].as_i64().expect("merged_at")),
        }),
        Some("several") => PullRequest::Several {
            numbers: list(&v["numbers"], number),
        },
        _ => panic!("not a pull request: {v}"),
    }
}

fn thread(v: &Value) -> Thread {
    match v["kind"].as_str() {
        Some("cloud") => Thread::Cloud {
            thread: non_empty(&v["thread"]),
            project: non_empty(&v["project"]),
        },
        Some("local") => Thread::Local {
            thread: non_empty(&v["thread"]),
            project: non_empty(&v["project"]),
            branch: maybe(&v["branch"], non_empty),
        },
        _ => panic!("not a thread: {v}"),
    }
}

fn read(v: &Value) -> Read {
    let o = &v["outcome"];
    let kind = match v["kind"].as_str().expect("a kind") {
        "version" => ReadKind::Version {
            source: label!(&v["source"], [SourceName::Github, SourceName::Cloudroom]),
            outcome: outcome(o, non_empty),
        },
        "repository" => ReadKind::Repository {
            outcome: outcome(o, |r| Repository {
                name: non_empty(&r["name"]),
            }),
        },
        "spec_list" => ReadKind::SpecList {
            outcome: list_outcome(o, number),
        },
        "issue" => ReadKind::Issue {
            issue: number(&v["issue"]),
            outcome: outcome(o, issue),
        },
        "sub_issues" => ReadKind::SubIssues {
            spec: number(&v["spec"]),
            outcome: list_outcome(o, number),
        },
        "blocked_by" => ReadKind::BlockedBy {
            ticket: number(&v["ticket"]),
            outcome: list_outcome(o, number),
        },
        "pr_discovery" => ReadKind::PrDiscovery {
            issue: number(&v["issue"]),
            outcome: outcome(o, |p| maybe(p, pull_request)),
        },
        "checks" => ReadKind::Checks {
            pr: number(&v["pr"]),
            outcome: list_outcome(o, |c| Check {
                name: non_empty(&c["name"]),
                result: label!(
                    &c["result"],
                    [
                        CheckResult::Pass,
                        CheckResult::Fail,
                        CheckResult::Pending,
                        CheckResult::Skipping,
                        CheckResult::Cancel,
                    ],
                ),
            }),
        },
        "comments" => ReadKind::Comments {
            pr: number(&v["pr"]),
            outcome: outcome(o, |r| {
                maybe(r, |r| Review {
                    verdict: label!(&r["verdict"], [Verdict::Approve, Verdict::Changes]),
                    commit: commit(&r["commit"]),
                })
            }),
        },
        "merge_readback" => ReadKind::MergeReadback {
            pr: number(&v["pr"]),
            outcome: outcome(o, flag),
        },
        "projects" => ReadKind::Projects {
            outcome: list_outcome(o, |p| Project {
                id: non_empty(&p["id"]),
                name: text(&p["name"]),
            }),
        },
        "threads" => ReadKind::Threads {
            outcome: list_outcome(o, thread),
        },
        "workspace" => ReadKind::Workspace {
            thread: non_empty(&v["thread"]),
            outcome: outcome(o, non_empty),
        },
        other => panic!("not a read kind: {other}"),
    };
    Read {
        id: read_id(&v["id"]),
        kind,
    }
}

fn worked<T>(v: &Value, known: impl Fn(&Value) -> T) -> WorkedOut<T> {
    let map = object(v);
    assert_eq!(map.len(), 1, "one form: {v}");
    match map.iter().next().map(|(k, v)| (k.as_str(), v)) {
        Some(("known", value)) => WorkedOut::Known(known(value)),
        Some(("unread", ids)) => WorkedOut::Unread(list(ids, read_id)),
        _ => panic!("not a worked-out value: {v}"),
    }
}

const STATES: [TicketState; 7] = [
    TicketState::Ready,
    TicketState::Building,
    TicketState::InReview,
    TicketState::ChangesRequested,
    TicketState::Merged,
    TicketState::Held,
    TicketState::Blocked,
];

fn state(v: &Value) -> State {
    match object(v).iter().next().map(|(k, v)| (k.as_str(), v)) {
        Some(("known", s)) => State::Known(label!(s, STATES)),
        Some(("unread", ids)) => State::Unread(list(ids, read_id)),
        Some(("unknown", why)) => State::Unknown(non_empty(why)),
        _ => panic!("not a state: {v}"),
    }
}

fn counts(v: &Value) -> Counts {
    Counts {
        tickets: count(&v["tickets"]),
        ready: count(&v["ready"]),
        building: count(&v["building"]),
        in_review: count(&v["in_review"]),
        changes_requested: count(&v["changes_requested"]),
        merged: count(&v["merged"]),
        held: count(&v["held"]),
        blocked: count(&v["blocked"]),
        unknown: count(&v["unknown"]),
    }
}

fn fleet(v: &Value) -> Fleet {
    Fleet {
        spec: number(&v["spec"]),
        issue: read_id(&v["issue"]),
        tickets: read_id(&v["tickets"]),
        progress: worked(&v["progress"], counts),
    }
}

fn ticket_core(v: &Value) -> TicketCore {
    TicketCore {
        number: number(&v["number"]),
        issue: read_id(&v["issue"]),
        blocked_by: read_id(&v["blocked_by"]),
        pr: read_id(&v["pr"]),
        ci: maybe(&v["ci"], read_id),
        review: maybe(&v["review"], read_id),
        on_base: maybe(&v["on_base"], read_id),
        state: state(&v["state"]),
    }
}

fn ticket(v: &Value) -> Ticket {
    let reviewer = object(&v["reviewer"]);
    Ticket {
        core: ticket_core(v),
        builder: worked(&v["builder"], |b| maybe(b, non_empty)),
        reviewer: Reviewer::Undefined(non_empty(&reviewer["undefined"])),
    }
}

fn blocker(v: &Value) -> Blocker {
    Blocker {
        number: number(&v["number"]),
        issue: read_id(&v["issue"]),
        pr: read_id(&v["pr"]),
        on_base: maybe(&v["on_base"], read_id),
        fleet: worked(&v["fleet"], |f| maybe(f, number)),
        merged: worked(&v["merged"], flag),
    }
}

fn fact<T>(v: &Value, read: impl Fn(&Value) -> T) -> Fact<T> {
    if let Some(known) = v.get("known") {
        Fact::Known(read(known))
    } else {
        Fact::Unknown(text(&v["unknown"]))
    }
}

fn needs_you(v: &Value) -> WorkedOut<Vec<NeedsYou>> {
    worked(v, |items| {
        list(items, |n| NeedsYou {
            kind: label!(&n["kind"], [NeedsYouKind::NeedsInfo, NeedsYouKind::Held]),
            spec: number(&n["spec"]),
            ticket: number(&n["ticket"]),
            wording: fact(&n["wording"], non_empty),
            link: fact(&n["link"], non_empty),
            asked_at: fact(&n["asked_at"], |at| {
                Timestamp(at.as_i64().expect("asked time"))
            }),
            risk: fact(&n["risk"], |risk| {
                label!(
                    risk,
                    [
                        NeedsYouRisk::Live,
                        NeedsYouRisk::Release,
                        NeedsYouRisk::Publish
                    ]
                )
            }),
        })
    })
}

const REASONS: [UnplacedReason; 5] = [
    UnplacedReason::NoBranch,
    UnplacedReason::SharedBranch,
    UnplacedReason::NoPullRequest,
    UnplacedReason::SeveralTickets,
    UnplacedReason::SeveralIssues,
];

fn view(v: &Value) -> View {
    match v["view"].as_str() {
        Some("fleets") => View::Fleets(FleetsView {
            repository: read_id(&v["repository"]),
            specs: read_id(&v["specs"]),
            fleets: list(&v["fleets"], fleet),
            tickets: list(&v["tickets"], ticket_core),
            blockers: list(&v["blockers"], blocker),
            needs_you: needs_you(&v["needs_you"]),
        }),
        Some("fleet") => View::Fleet(FleetView {
            repository: read_id(&v["repository"]),
            projects: read_id(&v["projects"]),
            threads: read_id(&v["threads"]),
            fleet: fleet(&v["fleet"]),
            tickets: list(&v["tickets"], ticket),
            blockers: list(&v["blockers"], blocker),
            needs_you: needs_you(&v["needs_you"]),
            unplaced: worked(&v["unplaced"], |items| {
                list(items, |u| Unplaced {
                    thread: non_empty(&u["thread"]),
                    reason: label!(&u["reason"], REASONS),
                })
            }),
        }),
        _ => panic!("not a view: {v}"),
    }
}

fn envelope(v: &Value) -> Envelope {
    assert_eq!(v["schema"], SCHEMA_ID);
    let github = &v["sources"]["github"];
    Envelope {
        schema: SchemaId::V1,
        sources: Sources {
            github: GitHubSource {
                name: Gh::Gh,
                version: read_id(&github["version"]),
                tested_version: text(&github["tested_version"]),
                version_tested: flag(&github["version_tested"]),
            },
            cloudroom: maybe(&v["sources"]["cloudroom"], |c| CloudRoomSource {
                name: RoomCli::RoomCli,
                version: read_id(&c["version"]),
                tested_version: text(&c["tested_version"]),
                version_tested: flag(&c["version_tested"]),
            }),
        },
        reads: list(&v["reads"], read),
        coverage: Coverage {
            state: label!(
                &v["coverage"]["state"],
                [Completeness::Complete, Completeness::Partial],
            ),
        },
        freshness: Freshness {
            snapshot_at: Timestamp(v["freshness"]["snapshot_at"].as_i64().expect("snapshot_at")),
        },
        data: view(&v["data"]),
    }
}

#[test]
fn every_contract_example_round_trips_through_the_model_types() {
    let schema = load_schema();
    for (i, example) in examples().iter().enumerate() {
        assert_eq!(
            validate(&schema, example),
            Vec::<String>::new(),
            "example {}",
            i + 1
        );
        let printed = serde_json::to_value(envelope(example)).expect("the model prints");
        assert_eq!(&printed, example, "example {} after the round trip", i + 1);
    }
}

fn ne(s: &str) -> NonEmpty {
    NonEmpty::new(s).expect("not empty")
}

fn n(x: u64) -> Number {
    NonZeroU64::new(x).expect("not zero")
}

fn failed_read(id: u32, kind: ReadKind) -> Read {
    Read {
        id: ReadId(id),
        kind,
    }
}

/// One `fleet` envelope with every branch the examples don't take: each
/// read kind failed or partial, every enum value, both thread kinds, the
/// pull request forms, and each worked-out form.
fn every_other_branch() -> Vec<Envelope> {
    let gap = |gap: GapKind| Failed {
        gap,
        reason: ne("Synthetic reason."),
    };
    fn partial<T>(value: Vec<T>) -> ListOutcome<T> {
        ListOutcome::Partial {
            gap: Truncated::Truncated,
            reason: ne("Synthetic truncation."),
            value,
        }
    }
    let commit = Commit::parse(&"c".repeat(40)).unwrap();
    let fields = PrFields {
        number: n(990),
        draft: true,
        head_branch: ne("room/syn-x-0001"),
        head_commit: commit.clone(),
        base_branch: ne("main"),
        closes: vec![n(991)],
    };
    let mut reads = vec![
        failed_read(
            1,
            ReadKind::Version {
                source: SourceName::Github,
                outcome: Outcome::Failed(gap(GapKind::UntestedVersion)),
            },
        ),
        failed_read(
            2,
            ReadKind::Repository {
                outcome: Outcome::Failed(gap(GapKind::CommandFailed)),
            },
        ),
        failed_read(
            3,
            ReadKind::SpecList {
                outcome: partial(vec![n(990)]),
            },
        ),
        failed_read(
            4,
            ReadKind::SpecList {
                outcome: ListOutcome::Failed(gap(GapKind::TimedOut)),
            },
        ),
        failed_read(
            5,
            ReadKind::Issue {
                issue: n(991),
                outcome: Outcome::Failed(gap(GapKind::BudgetExhausted)),
            },
        ),
        failed_read(
            6,
            ReadKind::Issue {
                issue: n(992),
                outcome: Outcome::Complete {
                    value: Issue {
                        title: String::new(),
                        state: IssueState::Closed,
                        milestone: None,
                        labels: vec![],
                        owned_paths: Some(ne("synthetic/owned")),
                        relies_on: Some(ne("synthetic/relies")),
                        pending_question: None,
                    },
                },
            },
        ),
        failed_read(
            7,
            ReadKind::SubIssues {
                spec: n(990),
                outcome: ListOutcome::Failed(gap(GapKind::Malformed)),
            },
        ),
        failed_read(
            8,
            ReadKind::SubIssues {
                spec: n(993),
                outcome: partial(vec![]),
            },
        ),
        failed_read(
            9,
            ReadKind::BlockedBy {
                ticket: n(991),
                outcome: ListOutcome::Failed(gap(GapKind::MissingField)),
            },
        ),
        failed_read(
            10,
            ReadKind::PrDiscovery {
                issue: n(991),
                outcome: Outcome::Failed(gap(GapKind::WrongType)),
            },
        ),
        failed_read(
            11,
            ReadKind::PrDiscovery {
                issue: n(992),
                outcome: Outcome::Complete {
                    value: Some(PullRequest::Several {
                        numbers: vec![n(994), n(995)],
                    }),
                },
            },
        ),
        failed_read(
            12,
            ReadKind::PrDiscovery {
                issue: n(993),
                outcome: Outcome::Complete {
                    value: Some(PullRequest::Merged(MergedPr {
                        fields: fields.clone(),
                        merge_commit: commit.clone(),
                        merged_at: Timestamp(1),
                    })),
                },
            },
        ),
        failed_read(
            13,
            ReadKind::PrDiscovery {
                issue: n(996),
                outcome: Outcome::Complete {
                    value: Some(PullRequest::Open(fields)),
                },
            },
        ),
        failed_read(
            14,
            ReadKind::Checks {
                pr: n(990),
                outcome: ListOutcome::Complete {
                    value: [
                        CheckResult::Pass,
                        CheckResult::Fail,
                        CheckResult::Pending,
                        CheckResult::Skipping,
                        CheckResult::Cancel,
                    ]
                    .into_iter()
                    .enumerate()
                    .map(|(i, result)| Check {
                        name: ne(&format!("synthetic-{i}")),
                        result,
                    })
                    .collect(),
                },
            },
        ),
        failed_read(
            15,
            ReadKind::Checks {
                pr: n(994),
                outcome: partial(vec![]),
            },
        ),
        failed_read(
            16,
            ReadKind::Checks {
                pr: n(995),
                outcome: ListOutcome::Failed(gap(GapKind::NotFound)),
            },
        ),
        failed_read(
            17,
            ReadKind::Comments {
                pr: n(990),
                outcome: Outcome::Failed(gap(GapKind::CommandFailed)),
            },
        ),
        failed_read(
            18,
            ReadKind::Comments {
                pr: n(994),
                outcome: Outcome::Complete {
                    value: Some(Review {
                        verdict: Verdict::Changes,
                        commit: commit.clone(),
                    }),
                },
            },
        ),
        failed_read(
            19,
            ReadKind::Comments {
                pr: n(995),
                outcome: Outcome::Complete {
                    value: Some(Review {
                        verdict: Verdict::Approve,
                        commit,
                    }),
                },
            },
        ),
        failed_read(
            20,
            ReadKind::MergeReadback {
                pr: n(990),
                outcome: Outcome::Failed(gap(GapKind::TimedOut)),
            },
        ),
        failed_read(
            21,
            ReadKind::MergeReadback {
                pr: n(994),
                outcome: Outcome::Complete { value: false },
            },
        ),
        failed_read(
            22,
            ReadKind::Projects {
                outcome: partial(vec![]),
            },
        ),
        failed_read(
            23,
            ReadKind::Projects {
                outcome: ListOutcome::Failed(gap(GapKind::Malformed)),
            },
        ),
        failed_read(
            24,
            ReadKind::Threads {
                outcome: partial(vec![
                    Thread::Cloud {
                        thread: ne("thr_syn_0091"),
                        project: ne("prj_syn_0091"),
                    },
                    Thread::Local {
                        thread: ne("thr_syn_0092"),
                        project: ne("prj_syn_0091"),
                        branch: None,
                    },
                    Thread::Local {
                        thread: ne("thr_syn_0093"),
                        project: ne("prj_syn_0091"),
                        branch: Some(ne("room/syn-x-0002")),
                    },
                ]),
            },
        ),
        failed_read(
            25,
            ReadKind::Threads {
                outcome: ListOutcome::Failed(gap(GapKind::BudgetExhausted)),
            },
        ),
        failed_read(
            26,
            ReadKind::Workspace {
                thread: ne("thr_syn_0091"),
                outcome: Outcome::Failed(gap(GapKind::NotFound)),
            },
        ),
        failed_read(
            27,
            ReadKind::Version {
                source: SourceName::Cloudroom,
                outcome: Outcome::Complete { value: ne("v132") },
            },
        ),
    ];
    reads.sort_by_key(|r| r.id.0);
    let state_cases = [
        State::Known(TicketState::Ready),
        State::Known(TicketState::Building),
        State::Known(TicketState::InReview),
        State::Known(TicketState::ChangesRequested),
        State::Known(TicketState::Merged),
        State::Known(TicketState::Held),
        State::Known(TicketState::Blocked),
        State::Unread(vec![ReadId(5)]),
        State::Unknown(ne("Synthetic: no state settles it.")),
    ];
    let tickets = state_cases
        .into_iter()
        .enumerate()
        .map(|(i, state)| Ticket {
            core: TicketCore {
                number: n(1000 + i as u64),
                issue: ReadId(5),
                blocked_by: ReadId(9),
                pr: ReadId(10),
                ci: (i == 0).then_some(ReadId(14)),
                review: (i == 0).then_some(ReadId(17)),
                on_base: (i == 0).then_some(ReadId(20)),
                state,
            },
            builder: match i {
                0 => WorkedOut::Known(None),
                1 => WorkedOut::Known(Some(ne("thr_syn_0093"))),
                _ => WorkedOut::Unread(vec![ReadId(26)]),
            },
            reviewer: Reviewer::Undefined(ne("Synthetic: version 1 places no reviewer.")),
        })
        .collect();
    let fleet_view = Envelope {
        schema: SchemaId::V1,
        sources: Sources {
            github: GitHubSource {
                name: Gh::Gh,
                version: ReadId(1),
                tested_version: "2.100.0".to_owned(),
                version_tested: false,
            },
            cloudroom: Some(CloudRoomSource {
                name: RoomCli::RoomCli,
                version: ReadId(27),
                tested_version: "v132".to_owned(),
                version_tested: true,
            }),
        },
        reads,
        coverage: Coverage {
            state: Completeness::Partial,
        },
        freshness: Freshness {
            snapshot_at: Timestamp(0),
        },
        data: View::Fleet(FleetView {
            repository: ReadId(2),
            projects: ReadId(23),
            threads: ReadId(25),
            fleet: Fleet {
                spec: n(990),
                issue: ReadId(5),
                tickets: ReadId(7),
                progress: WorkedOut::Unread(vec![ReadId(7)]),
            },
            tickets,
            blockers: vec![
                Blocker {
                    number: n(997),
                    issue: ReadId(5),
                    pr: ReadId(12),
                    on_base: Some(ReadId(20)),
                    fleet: WorkedOut::Unread(vec![ReadId(7)]),
                    merged: WorkedOut::Unread(vec![ReadId(20)]),
                },
                Blocker {
                    number: n(998),
                    issue: ReadId(6),
                    pr: ReadId(11),
                    on_base: None,
                    fleet: WorkedOut::Known(Some(n(990))),
                    merged: WorkedOut::Known(true),
                },
            ],
            needs_you: WorkedOut::Unread(vec![ReadId(5)]),
            unplaced: WorkedOut::Known(
                REASONS
                    .into_iter()
                    .enumerate()
                    .map(|(i, reason)| Unplaced {
                        thread: ne(&format!("thr_syn_00{}", 94 + i)),
                        reason,
                    })
                    .collect(),
            ),
        }),
    };
    let fleets_view = Envelope {
        data: View::Fleets(FleetsView {
            repository: ReadId(2),
            specs: ReadId(4),
            fleets: vec![],
            tickets: [
                State::Unread(vec![ReadId(5)]),
                State::Unknown(ne("Synthetic: closed without a merge read back.")),
            ]
            .into_iter()
            .enumerate()
            .map(|(i, state)| TicketCore {
                number: n(1100 + i as u64),
                issue: ReadId(5),
                blocked_by: ReadId(9),
                pr: ReadId(10),
                ci: None,
                review: None,
                on_base: None,
                state,
            })
            .collect(),
            blockers: vec![],
            needs_you: WorkedOut::Known(vec![
                NeedsYou {
                    kind: NeedsYouKind::NeedsInfo,
                    spec: n(990),
                    ticket: n(1100),
                    wording: openwiz_core::model::Fact::Unknown(
                        "synthetic question not reported".into(),
                    ),
                    link: openwiz_core::model::Fact::Unknown("synthetic link not reported".into()),
                    asked_at: openwiz_core::model::Fact::Unknown(
                        "synthetic time not reported".into(),
                    ),
                    risk: openwiz_core::model::Fact::Unknown("synthetic risk not reported".into()),
                },
                NeedsYou {
                    kind: NeedsYouKind::Held,
                    spec: n(990),
                    ticket: n(1101),
                    wording: openwiz_core::model::Fact::Unknown(
                        "synthetic question not reported".into(),
                    ),
                    link: openwiz_core::model::Fact::Unknown("synthetic link not reported".into()),
                    asked_at: openwiz_core::model::Fact::Unknown(
                        "synthetic time not reported".into(),
                    ),
                    risk: openwiz_core::model::Fact::Unknown("synthetic risk not reported".into()),
                },
            ]),
        }),
        sources: Sources {
            cloudroom: None,
            ..fleet_view.sources.clone()
        },
        ..fleet_view.clone()
    };
    let mut fleets_unread = fleets_view.clone();
    if let View::Fleets(view) = &mut fleets_unread.data {
        view.needs_you = WorkedOut::Unread(vec![ReadId(4)]);
    }
    let mut envelopes = vec![fleet_view, fleets_view.clone(), fleets_unread];
    for risk in [
        NeedsYouRisk::Live,
        NeedsYouRisk::Release,
        NeedsYouRisk::Publish,
    ] {
        let mut enriched = fleets_view.clone();
        for read in &mut enriched.reads {
            if let ReadKind::Issue {
                outcome: Outcome::Complete { value },
                ..
            } = &mut read.kind
            {
                value.pending_question = Some(PendingQuestion {
                    wording: ne("Needs you: Synthetic question"),
                    link: ne("https://example.invalid/synthetic/issues/992#issuecomment-1"),
                    asked_at: Timestamp(1_700_000_000_000),
                });
            }
        }
        if let View::Fleets(view) = &mut enriched.data {
            view.needs_you = WorkedOut::Known(vec![NeedsYou {
                kind: NeedsYouKind::Held,
                spec: n(990),
                ticket: n(1101),
                wording: Fact::Known(ne("Needs you: Synthetic question")),
                link: Fact::Known(ne(
                    "https://example.invalid/synthetic/issues/1101#issuecomment-1",
                )),
                asked_at: Fact::Known(Timestamp(1_700_000_000_000)),
                risk: Fact::Known(risk),
            }]);
        }
        envelopes.push(enriched);
    }
    envelopes
}

#[test]
fn the_model_types_reach_every_branch_of_the_schema() {
    let schema = load_schema();
    let mut coverage = schema::Coverage::default();
    for example in examples() {
        assert_eq!(
            validate_with(&schema, &example, &mut coverage),
            Vec::<String>::new()
        );
    }
    // #129: HTTP adds the configured, verified target; CLI models omit it.
    let mut http = examples().remove(0);
    http["orchestrator"] = json!("thr_syn_0001");
    assert_eq!(
        validate_with(&schema, &http, &mut coverage),
        Vec::<String>::new()
    );
    for (i, built) in every_other_branch().into_iter().enumerate() {
        let printed = serde_json::to_value(&built).expect("the model prints");
        assert_eq!(
            validate_with(&schema, &printed, &mut coverage),
            Vec::<String>::new(),
            "built envelope {i}"
        );
    }
    let missing: Vec<_> = branches(&schema).difference(&coverage.0).cloned().collect();
    assert!(
        missing.is_empty(),
        "no value takes these branches: {missing:#?}"
    );
}

#[test]
fn the_fleet_schema_uses_only_checked_keywords() {
    let schema = load_schema();
    assert_eq!(schema["title"], SCHEMA_ID);
    assert_eq!(lint(&schema), Vec::<String>::new());
    for (why, planted) in [
        (
            "an unchecked keyword",
            json!({"type": "string", "format": "date"}),
        ),
        (
            "a pattern it can't check",
            json!({"type": "string", "pattern": "^r[0-9]+$"}),
        ),
        (
            "an unanchored pattern",
            json!({"type": "string", "pattern": "r[0-9]*"}),
        ),
        (
            "a loose additionalProperties",
            json!({"type": "object", "additionalProperties": true}),
        ),
        ("a dangling $ref", json!({"$ref": "#/$defs/does_not_exist"})),
    ] {
        let mut bad = load_schema();
        bad["$defs"]["planted"] = planted;
        assert!(!lint(&bad).is_empty(), "the lint missed {why}");
    }
}

#[test]
fn the_checker_refuses_what_the_schema_refuses() {
    let schema = load_schema();
    let good = &examples()[0];
    assert_eq!(validate(&schema, good), Vec::<String>::new());
    let pr = good["reads"]
        .as_array()
        .unwrap()
        .iter()
        .position(|r| r["outcome"]["value"]["head_commit"].is_string())
        .expect("example 1 has a pull request");
    let head = format!("/reads/{pr}/outcome/value/head_commit");
    let plants: Vec<(&str, &str, Value)> = vec![
        ("a read id without its r", "/reads/0/id", json!("1")),
        ("a read id with a letter", "/reads/0/id", json!("r1a")),
        ("a bare r", "/sources/github/version", json!("r")),
        ("an upper-case commit", &head, json!("A".repeat(40))),
        ("a short commit", &head, json!("1".repeat(39))),
        (
            "a tagged state",
            "/data/tickets/0/state",
            json!({"merged": null}),
        ),
        (
            "two forms at once",
            "/data/tickets/0/state",
            json!({"known": "ready", "unread": []}),
        ),
        (
            "another spelling",
            "/data/tickets/0/state",
            json!({"known": "MERGED"}),
        ),
        ("a number zero", "/data/fleets/0/spec", json!(0)),
        (
            "a string bool",
            "/sources/github/version_tested",
            json!("true"),
        ),
        (
            "a positional array",
            "/data/fleets/0",
            json!([901, "r4", "r5"]),
        ),
        (
            "an empty reason",
            "/data/tickets/0/state",
            json!({"unknown": ""}),
        ),
        ("another schema", "/schema", json!("openwiz.fleet.v2")),
        (
            "a CloudRoom source in fleets",
            "/sources/cloudroom",
            json!({"name": "room-cli", "version": "r1", "tested_version": "v132", "version_tested": true}),
        ),
    ];
    for (why, at, planted) in plants {
        let mut bad = good.clone();
        let slot = bad
            .pointer_mut(at)
            .unwrap_or_else(|| panic!("{why}: no {at}"));
        *slot = planted;
        if why == "a CloudRoom source in fleets" {
            // Only the view can say it's wrong: a schema-valid shape, which
            // the `view_sources` rule (A4) refuses. The schema accepts it.
            assert_eq!(validate(&schema, &bad), Vec::<String>::new(), "{why}");
            continue;
        }
        assert!(
            !validate(&schema, &bad).is_empty(),
            "the checker accepted {why}"
        );
    }
    let mut extra = good.clone();
    extra["data"]["fleets"][0]["synthetic"] = json!(1);
    assert!(!validate(&schema, &extra).is_empty(), "an extra key");
    let mut missing = good.clone();
    extra = missing.clone();
    missing["data"]["fleets"][0]
        .as_object_mut()
        .unwrap()
        .remove("progress");
    assert!(!validate(&schema, &missing).is_empty(), "a missing key");
    assert_eq!(validate(&schema, &extra), Vec::<String>::new());
}

#[test]
fn the_types_hold_no_bad_value() {
    assert_eq!(NonEmpty::new(""), None);
    assert_eq!(
        NonEmpty::new("x").map(|t| t.as_str().to_owned()),
        Some("x".to_owned())
    );
    let hex = "0123456789abcdef0123456789abcdef01234567";
    assert_eq!(
        Commit::parse(hex).map(|c| c.as_str().to_owned()),
        Some(hex.to_owned())
    );
    for bad in [
        "",
        &hex[..39],
        &format!("{hex}0"),
        &hex.to_uppercase(),
        &format!("{}g", &hex[..39]),
        &format!("{}é", &hex[..38]),
        &format!(" {}", &hex[..39]),
    ] {
        assert_eq!(Commit::parse(bad), None, "{bad:?}");
    }
    assert_eq!(serde_json::to_value(ReadId(0)).unwrap(), json!("r0"));
    assert_eq!(
        serde_json::to_value(ReadId(4_294_967_295)).unwrap(),
        json!("r4294967295")
    );
    assert_eq!(
        serde_json::to_value(SchemaId::V1).unwrap(),
        json!("openwiz.fleet.v1")
    );
    assert_eq!(serde_json::to_value(Gh::Gh).unwrap(), json!("gh"));
    assert_eq!(
        serde_json::to_value(RoomCli::RoomCli).unwrap(),
        json!("room-cli")
    );
    assert_eq!(
        serde_json::to_value(Truncated::Truncated).unwrap(),
        json!("truncated")
    );
}
