//! A6 (ClosedWiz#114): the contract's own `fleet` examples
//! (`contracts/fleet.v1.md`, "Examples", 2 and 3), whose builders and
//! `unplaced` are the expected values: the chain worked out from each
//! example's `reads` gives exactly the example's `builder` for every ticket,
//! and its `unplaced`.
//!
//! The reader here turns an example's read records into the model's types.
//! It is test-only and not strict (it reads the contract's own file, never
//! outside input), and OpenWiz never uses it.

use std::num::NonZeroU64;

use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::agents;
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Failed, Issue, IssueState, ListOutcome, MergedPr, Milestone,
    NonEmpty, Number, Outcome, PrFields, Project, PullRequest, Read, ReadId, ReadKind, Repository,
    Review, SourceName, Thread, Truncated, Verdict,
};
use openwiz_core::model::Timestamp;
use serde_json::Value;

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

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or_else(|| panic!("not a string: {v}"))
}

fn ne(v: &Value) -> NonEmpty {
    NonEmpty::new(s(v)).expect("not empty")
}

fn n(v: &Value) -> Number {
    NonZeroU64::new(v.as_u64().expect("a number")).expect("1 or more")
}

fn numbers(v: &Value) -> Vec<Number> {
    v.as_array().expect("a list").iter().map(n).collect()
}

fn commit(v: &Value) -> Commit {
    Commit::parse(s(v)).expect("a commit")
}

fn gap(v: &Value) -> GapKind {
    match s(v) {
        "untested_version" => GapKind::UntestedVersion,
        "command_failed" => GapKind::CommandFailed,
        "timed_out" => GapKind::TimedOut,
        "budget_exhausted" => GapKind::BudgetExhausted,
        "malformed" => GapKind::Malformed,
        "missing_field" => GapKind::MissingField,
        "wrong_type" => GapKind::WrongType,
        "not_found" => GapKind::NotFound,
        other => panic!("not a gap: {other}"),
    }
}

fn failed(o: &Value) -> Failed {
    Failed {
        gap: gap(&o["gap"]),
        reason: ne(&o["reason"]),
    }
}

fn outcome<T>(o: &Value, value: impl Fn(&Value) -> T) -> Outcome<T> {
    match s(&o["state"]) {
        "complete" => Outcome::Complete {
            value: value(&o["value"]),
        },
        "failed" => Outcome::Failed(failed(o)),
        other => panic!("not an outcome: {other}"),
    }
}

fn list<T>(o: &Value, item: impl Fn(&Value) -> T) -> ListOutcome<T> {
    let items = |v: &Value| v.as_array().expect("a list").iter().map(&item).collect();
    match s(&o["state"]) {
        "complete" => ListOutcome::Complete {
            value: items(&o["value"]),
        },
        "partial" => ListOutcome::Partial {
            gap: Truncated::Truncated,
            reason: ne(&o["reason"]),
            value: items(&o["value"]),
        },
        "failed" => ListOutcome::Failed(failed(o)),
        other => panic!("not a list outcome: {other}"),
    }
}

fn fields(v: &Value) -> PrFields {
    PrFields {
        number: n(&v["number"]),
        draft: v["draft"].as_bool().expect("a flag"),
        head_branch: ne(&v["head_branch"]),
        head_commit: commit(&v["head_commit"]),
        base_branch: ne(&v["base_branch"]),
        closes: numbers(&v["closes"]),
    }
}

fn pull_request(v: &Value) -> Option<PullRequest> {
    if v.is_null() {
        return None;
    }
    Some(match s(&v["state"]) {
        "open" => PullRequest::Open(fields(v)),
        "merged" => PullRequest::Merged(MergedPr {
            fields: fields(v),
            merge_commit: commit(&v["merge_commit"]),
            merged_at: Timestamp(v["merged_at"].as_i64().expect("a time")),
        }),
        "several" => PullRequest::Several {
            numbers: numbers(&v["numbers"]),
        },
        other => panic!("not a pull request state: {other}"),
    })
}

fn issue(v: &Value) -> Issue {
    let line = |v: &Value| v.as_str().map(|t| NonEmpty::new(t).expect("not empty"));
    Issue {
        title: s(&v["title"]).to_owned(),
        state: match s(&v["state"]) {
            "open" => IssueState::Open,
            "closed" => IssueState::Closed,
            other => panic!("not an issue state: {other}"),
        },
        milestone: (!v["milestone"].is_null()).then(|| Milestone {
            number: n(&v["milestone"]["number"]),
            title: s(&v["milestone"]["title"]).to_owned(),
        }),
        labels: v["labels"]
            .as_array()
            .expect("labels")
            .iter()
            .map(ne)
            .collect(),
        owned_paths: line(&v["owned_paths"]),
        relies_on: line(&v["relies_on"]),
        pending_question: None,
    }
}

fn thread(v: &Value) -> Thread {
    match s(&v["kind"]) {
        "cloud" => Thread::Cloud {
            thread: ne(&v["thread"]),
            project: ne(&v["project"]),
        },
        "local" => Thread::Local {
            thread: ne(&v["thread"]),
            project: ne(&v["project"]),
            branch: v["branch"]
                .as_str()
                .map(|b| NonEmpty::new(b).expect("a branch")),
        },
        other => panic!("not a thread kind: {other}"),
    }
}

/// One read record of an example, every kind.
fn read(r: &Value) -> Read {
    let id = ReadId(
        s(&r["id"])
            .strip_prefix('r')
            .and_then(|d| d.parse().ok())
            .expect("an id"),
    );
    let o = &r["outcome"];
    let kind = match s(&r["kind"]) {
        "version" => ReadKind::Version {
            source: match s(&r["source"]) {
                "github" => SourceName::Github,
                "cloudroom" => SourceName::Cloudroom,
                other => panic!("not a source: {other}"),
            },
            outcome: outcome(o, ne),
        },
        "repository" => ReadKind::Repository {
            outcome: outcome(o, |v| Repository {
                name: ne(&v["name"]),
            }),
        },
        "spec_list" => ReadKind::SpecList {
            outcome: list(o, n),
        },
        "issue" => ReadKind::Issue {
            issue: n(&r["issue"]),
            outcome: outcome(o, issue),
        },
        "sub_issues" => ReadKind::SubIssues {
            spec: n(&r["spec"]),
            outcome: list(o, n),
        },
        "blocked_by" => ReadKind::BlockedBy {
            ticket: n(&r["ticket"]),
            outcome: list(o, n),
        },
        "pr_discovery" => ReadKind::PrDiscovery {
            issue: n(&r["issue"]),
            outcome: outcome(o, pull_request),
        },
        "checks" => ReadKind::Checks {
            pr: n(&r["pr"]),
            outcome: list(o, |c| Check {
                name: ne(&c["name"]),
                result: match s(&c["result"]) {
                    "pass" => CheckResult::Pass,
                    "fail" => CheckResult::Fail,
                    "pending" => CheckResult::Pending,
                    "skipping" => CheckResult::Skipping,
                    "cancel" => CheckResult::Cancel,
                    other => panic!("not a check result: {other}"),
                },
            }),
        },
        "comments" => ReadKind::Comments {
            pr: n(&r["pr"]),
            outcome: outcome(o, |v| {
                (!v.is_null()).then(|| Review {
                    verdict: match s(&v["verdict"]) {
                        "approve" => Verdict::Approve,
                        "changes" => Verdict::Changes,
                        other => panic!("not a verdict: {other}"),
                    },
                    commit: commit(&v["commit"]),
                })
            }),
        },
        "merge_readback" => ReadKind::MergeReadback {
            pr: n(&r["pr"]),
            outcome: outcome(o, |v| v.as_bool().expect("a flag")),
        },
        "projects" => ReadKind::Projects {
            outcome: list(o, |p| Project {
                id: ne(&p["id"]),
                name: s(&p["name"]).to_owned(),
            }),
        },
        "threads" => ReadKind::Threads {
            outcome: list(o, thread),
        },
        "workspace" => ReadKind::Workspace {
            thread: ne(&r["thread"]),
            outcome: outcome(o, ne),
        },
        other => panic!("not a read kind: {other}"),
    };
    Read { id, kind }
}

/// The example's reads, through the reader, must print back as written:
/// so the reader dropped nothing the chain could read.
fn reads_of(example: &Value) -> Vec<Read> {
    let reads: Vec<Read> = example["reads"]
        .as_array()
        .expect("reads")
        .iter()
        .map(read)
        .collect();
    assert_eq!(
        serde_json::to_value(&reads).expect("prints"),
        example["reads"],
        "the reader keeps every read as written"
    );
    reads
}

/// The example's `fleet` view: its spec, each ticket's number and builder,
/// and its `unplaced`.
fn check_example(example: &Value) {
    let data = &example["data"];
    assert_eq!(data["view"], "fleet");
    let spec = n(&data["fleet"]["spec"]);
    let placements = agents::place(spec, &reads_of(example)).expect("a complete record");
    let tickets = data["tickets"].as_array().expect("tickets");
    assert!(!tickets.is_empty());
    for ticket in tickets {
        assert_eq!(
            serde_json::to_value(placements.builder(n(&ticket["number"]))).expect("prints"),
            ticket["builder"],
            "#{}'s builder",
            ticket["number"]
        );
        assert_eq!(
            serde_json::to_value(agents::reviewer()).expect("prints"),
            ticket["reviewer"],
            "#{}'s reviewer",
            ticket["number"]
        );
    }
    assert_eq!(
        serde_json::to_value(placements.unplaced()).expect("prints"),
        data["unplaced"],
        "unplaced"
    );
}

#[test]
fn a6_examples_preserve_all_original_cases() {
    let cases: [(&str, fn()); 2] = [
        (
            "the_contracts_complete_fleet_example_places_exactly_its_builders",
            the_contracts_complete_fleet_example_places_exactly_its_builders,
        ),
        (
            "the_contracts_partial_fleet_example_leaves_every_builder_unread",
            the_contracts_partial_fleet_example_leaves_every_builder_unread,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: a6_agents::examples::{name}");
        proof();
    }
}

fn the_contracts_complete_fleet_example_places_exactly_its_builders() {
    // Example 2, `fleet 901`: five threads placed, three unplaced.
    let example = &examples()[1];
    assert_eq!(example["data"]["fleet"]["spec"], 901);
    assert_eq!(example["coverage"]["state"], "complete");
    check_example(example);
}

fn the_contracts_partial_fleet_example_leaves_every_builder_unread() {
    // Example 3, `fleet 930`: one thread's branch failed, so every builder
    // and `unplaced` is unread, naming it; its other failed and partial
    // reads (checks, a blocker list, a blocker's issue and pull request)
    // are none of the chain's.
    let example = &examples()[2];
    assert_eq!(example["data"]["fleet"]["spec"], 930);
    assert_eq!(example["coverage"]["state"], "partial");
    check_example(example);
}
