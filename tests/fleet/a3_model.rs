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
use serde_json::Value;

use crate::schema::{load_schema, validate};

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/fleet.v1.md");

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
