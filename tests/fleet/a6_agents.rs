#[path = "a6_reads.rs"]
mod reads;

use std::num::NonZeroU64;

use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::agents::{self, Needed, Placements, REVIEWER_REASON, RecordError};
use openwiz_core::fleet::model::{
    Commit, Failed, ListOutcome, MergedPr, NonEmpty, Number, Outcome, PrFields, Project,
    PullRequest, Read, ReadId, ReadKind, SourceName, Thread, Truncated, WorkedOut,
};
use openwiz_core::model::Timestamp;
use serde_json::{Value, json};

fn n(x: u64) -> Number {
    NonZeroU64::new(x).expect("a number is 1 or more")
}

fn ne(s: &str) -> NonEmpty {
    NonEmpty::new(s).expect("not empty")
}

const SPEC: u64 = 940;

#[derive(Clone)]
enum Pr {
    None,
    Open {
        number: u64,
        head: &'static str,
        closes: &'static [u64],
        draft: bool,
    },
    Merged {
        number: u64,
        head: &'static str,
        closes: &'static [u64],
    },
    Several(&'static [u64]),
}

fn open(number: u64, head: &'static str, closes: &'static [u64]) -> Pr {
    Pr::Open {
        number,
        head,
        closes,
        draft: false,
    }
}

#[derive(Clone)]
enum Row {
    Cloud(&'static str, String),
    Local(&'static str, Option<&'static str>),
}

fn cloud(id: &'static str, branch: &str) -> Row {
    Row::Cloud(id, branch.to_owned())
}

#[derive(Clone, Default)]
struct Fleet {
    tickets: Vec<(u64, Pr)>,
    threads: Vec<Row>,
}

impl Fleet {
    fn ticket(mut self, number: u64, pr: Pr) -> Self {
        self.tickets.push((number, pr));
        self
    }

    fn thread(mut self, row: Row) -> Self {
        self.threads.push(row);
        self
    }

    fn reads(&self) -> Vec<Read> {
        let mut reads = Vec::new();
        let mut push = |kind: ReadKind| {
            let id = ReadId(u32::try_from(reads.len()).expect("few reads") + 1);
            reads.push(Read { id, kind });
        };
        push(ReadKind::SubIssues {
            spec: n(SPEC),
            outcome: ListOutcome::Complete {
                value: self.tickets.iter().map(|(t, _)| n(*t)).collect(),
            },
        });
        for (ticket, pr) in &self.tickets {
            push(ReadKind::PrDiscovery {
                issue: n(*ticket),
                outcome: Outcome::Complete {
                    value: pull_request(pr),
                },
            });
        }
        push(ReadKind::Projects {
            outcome: ListOutcome::Complete {
                value: vec![Project {
                    id: ne("prj_syn_0001"),
                    name: "Synthetic project".to_owned(),
                }],
            },
        });
        push(ReadKind::Threads {
            outcome: ListOutcome::Complete {
                value: self.threads.iter().map(thread).collect(),
            },
        });
        for row in &self.threads {
            if let Row::Cloud(id, branch) = row {
                push(ReadKind::Workspace {
                    thread: ne(id),
                    outcome: Outcome::Complete {
                        value: NonEmpty::new(branch.clone()).expect("a branch"),
                    },
                });
            }
        }
        reads
    }

    fn place(&self) -> Placements {
        agents::place(n(SPEC), &self.reads()).expect("a complete record")
    }
}

fn fields(number: u64, head: &str, closes: &[u64], draft: bool) -> PrFields {
    PrFields {
        number: n(number),
        draft,
        head_branch: ne(head),
        head_commit: Commit::parse(&"1".repeat(40)).expect("a commit"),
        base_branch: ne("main"),
        closes: closes.iter().map(|&c| n(c)).collect(),
    }
}

fn pull_request(pr: &Pr) -> Option<PullRequest> {
    match pr {
        Pr::None => None,
        Pr::Open {
            number,
            head,
            closes,
            draft,
        } => Some(PullRequest::Open(fields(*number, head, closes, *draft))),
        Pr::Merged {
            number,
            head,
            closes,
        } => Some(PullRequest::Merged(MergedPr {
            fields: fields(*number, head, closes, false),
            merge_commit: Commit::parse(&"2".repeat(40)).expect("a commit"),
            merged_at: Timestamp(1_793_385_000_000),
        })),
        Pr::Several(numbers) => Some(PullRequest::Several {
            numbers: numbers.iter().map(|&x| n(x)).collect(),
        }),
    }
}

fn thread(row: &Row) -> Thread {
    match row {
        Row::Cloud(id, _) => Thread::Cloud {
            thread: ne(id),
            project: ne("prj_syn_0001"),
        },
        Row::Local(id, branch) => Thread::Local {
            thread: ne(id),
            project: ne("prj_syn_0001"),
            branch: branch.map(ne),
        },
    }
}

fn printed(builder: &WorkedOut<Option<NonEmpty>>) -> Value {
    serde_json::to_value(builder).expect("prints")
}

fn builders(fleet: &Fleet, placements: &Placements) -> Vec<(u64, Value)> {
    fleet
        .tickets
        .iter()
        .map(|(t, _)| (*t, printed(&placements.builder(n(*t)))))
        .collect()
}

fn unplaced(placements: &Placements) -> Value {
    serde_json::to_value(placements.unplaced()).expect("prints")
}

const HEAD: &str = "room/syn-a6-0941";

fn the_pr() -> Pr {
    open(971, HEAD, &[941])
}

#[test]
fn a6_placement_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 14] = [
        (
            "a_branch_named_after_a_ticket_places_nothing_without_its_pull_request",
            a_branch_named_after_a_ticket_places_nothing_without_its_pull_request,
        ),
        (
            "a_failed_ticket_or_thread_list_requires_nothing_it_would_have_listed",
            a_failed_ticket_or_thread_list_requires_nothing_it_would_have_listed,
        ),
        (
            "a_local_thread_a_merged_or_a_draft_pull_request_places_like_any_other",
            a_local_thread_a_merged_or_a_draft_pull_request_places_like_any_other,
        ),
        (
            "a_pull_request_that_is_no_tickets_places_nothing",
            a_pull_request_that_is_no_tickets_places_nothing,
        ),
        (
            "a_read_the_chain_does_not_require_never_makes_it_unread",
            a_read_the_chain_does_not_require_never_makes_it_unread,
        ),
        (
            "a_required_read_missing_from_the_record_or_on_it_twice_is_refused",
            a_required_read_missing_from_the_record_or_on_it_twice_is_refused,
        ),
        (
            "an_incomplete_read_behind_the_chain_leaves_every_builder_and_unplaced_unread",
            an_incomplete_read_behind_the_chain_leaves_every_builder_and_unplaced_unread,
        ),
        (
            "every_builder_and_unplaced_the_chain_gives_matches_the_schema",
            every_builder_and_unplaced_the_chain_gives_matches_the_schema,
        ),
        (
            "every_missing_link_places_nothing_with_its_reason",
            every_missing_link_places_nothing_with_its_reason,
        ),
        ("no_chain_places_a_reviewer", no_chain_places_a_reviewer),
        (
            "only_the_exact_head_branch_places_a_thread",
            only_the_exact_head_branch_places_a_thread,
        ),
        (
            "several_incomplete_reads_are_named_once_each_in_the_order_of_reads",
            several_incomplete_reads_are_named_once_each_in_the_order_of_reads,
        ),
        (
            "the_first_reason_that_applies_is_the_one_given",
            the_first_reason_that_applies_is_the_one_given,
        ),
        (
            "the_read_rule_fleet_is_complete_and_placed",
            the_read_rule_fleet_is_complete_and_placed,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: a6_agents::{name}");
        proof();
    }
}

fn only_the_exact_head_branch_places_a_thread() {
    let exact = Fleet::default()
        .ticket(941, the_pr())
        .thread(cloud("thr_syn_0041", HEAD));
    let placements = exact.place();
    assert_eq!(placements.builder(n(941)), known_thread("thr_syn_0041"));
    assert_eq!(unplaced(&placements), json!({"known": []}));

    let near_misses = [
        "room/syn-a6-0941 ",
        " room/syn-a6-0941",
        "room/syn-a6-0941\n",
        "Room/syn-a6-0941",
        "ROOM/SYN-A6-0941",
        "room/syn-a6-094",
        "room/syn-a6-09411",
        "room/syn-a6-0941/",
        "room/syn-a6-0941-2",
        "refs/heads/room/syn-a6-0941",
        "origin/room/syn-a6-0941",
        "room\\syn-a6-0941",
        "room/syn-a6-O941",
        "room/syn-a6\u{2010}0941",
        "room/syn-a6-0941\u{200b}",
        "room//syn-a6-0941",
        "syn-a6-0941",
        "room/syn-a6-0941.git",
    ];
    for branch in near_misses {
        let fleet = Fleet::default()
            .ticket(941, the_pr())
            .thread(cloud("thr_syn_0041", branch));
        let placements = fleet.place();
        assert_eq!(
            builders(&fleet, &placements),
            [(941, json!({"known": null}))],
            "{branch:?}"
        );
        assert_eq!(
            unplaced(&placements),
            json!({"known": [{"thread": "thr_syn_0041", "reason": "no_pull_request"}]}),
            "{branch:?}"
        );
    }
}

fn known_thread(id: &str) -> WorkedOut<Option<NonEmpty>> {
    WorkedOut::Known(Some(ne(id)))
}

fn a_branch_named_after_a_ticket_places_nothing_without_its_pull_request() {
    let fleet = Fleet::default()
        .ticket(941, Pr::None)
        .ticket(942, open(972, "room/syn-unrelated-0001", &[942]))
        .thread(cloud("thr_syn_0041", "room/941-synthetic-ticket-a6"))
        .thread(cloud("thr_syn_0042", "room/syn-unrelated-0001"))
        .thread(cloud("thr_syn_0043", "room/942-synthetic-ticket-a6"));
    let placements = fleet.place();
    assert_eq!(
        builders(&fleet, &placements),
        [
            (941, json!({"known": null})),
            (942, json!({"known": "thr_syn_0042"}))
        ]
    );
    assert_eq!(
        unplaced(&placements),
        json!({"known": [
            {"thread": "thr_syn_0041", "reason": "no_pull_request"},
            {"thread": "thr_syn_0043", "reason": "no_pull_request"}
        ]})
    );
}

fn a_local_thread_a_merged_or_a_draft_pull_request_places_like_any_other() {
    let fleet = Fleet::default()
        .ticket(941, the_pr())
        .ticket(
            942,
            Pr::Merged {
                number: 972,
                head: "room/syn-a6-0942",
                closes: &[942],
            },
        )
        .ticket(
            943,
            Pr::Open {
                number: 973,
                head: "room/syn-a6-0943",
                closes: &[943],
                draft: true,
            },
        )
        .thread(Row::Local("thr_syn_0041", Some(HEAD)))
        .thread(cloud("thr_syn_0042", "room/syn-a6-0942"))
        .thread(cloud("thr_syn_0043", "room/syn-a6-0943"));
    let placements = fleet.place();
    assert_eq!(
        builders(&fleet, &placements),
        [
            (941, json!({"known": "thr_syn_0041"})),
            (942, json!({"known": "thr_syn_0042"})),
            (943, json!({"known": "thr_syn_0043"}))
        ]
    );
    assert_eq!(unplaced(&placements), json!({"known": []}));
}

struct Case {
    what: &'static str,
    fleet: Fleet,
    builders: Vec<(u64, Value)>,
    unplaced: Value,
}

fn check(cases: Vec<Case>) {
    for case in cases {
        let placements = case.fleet.place();
        assert_eq!(
            builders(&case.fleet, &placements),
            case.builders,
            "{}: builders",
            case.what
        );
        assert_eq!(
            unplaced(&placements),
            case.unplaced,
            "{}: unplaced",
            case.what
        );
    }
}

fn none() -> Value {
    json!({"known": null})
}

fn every_missing_link_places_nothing_with_its_reason() {
    check(vec![
        Case {
            what: "no pull request closes the ticket",
            fleet: Fleet::default()
                .ticket(941, Pr::None)
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "no_pull_request"}]}),
        },
        Case {
            what: "several open pull requests: none is the ticket's",
            fleet: Fleet::default()
                .ticket(941, Pr::Several(&[971, 972]))
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "no_pull_request"}]}),
        },
        Case {
            what: "a local thread with no branch",
            fleet: Fleet::default()
                .ticket(941, the_pr())
                .thread(Row::Local("thr_syn_0041", None)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "no_branch"}]}),
        },
        Case {
            what: "two threads on the head branch: which one built it can't be told",
            fleet: Fleet::default()
                .ticket(941, the_pr())
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(Row::Local("thr_syn_0042", Some(HEAD))),
            builders: vec![(941, none())],
            unplaced: json!({"known": [
                {"thread": "thr_syn_0041", "reason": "shared_branch"},
                {"thread": "thr_syn_0042", "reason": "shared_branch"}
            ]}),
        },
        Case {
            what: "one pull request closes two of the fleet's tickets",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[941, 942]))
                .ticket(942, open(971, HEAD, &[941, 942]))
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none()), (942, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "several_tickets"}]}),
        },
        Case {
            what: "two tickets' pull requests from one branch",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[941]))
                .ticket(
                    942,
                    Pr::Merged {
                        number: 972,
                        head: HEAD,
                        closes: &[942],
                    },
                )
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none()), (942, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "several_tickets"}]}),
        },
        Case {
            what: "the pull request also closes an issue outside the fleet",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[777, 941]))
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "several_issues"}]}),
        },
        Case {
            what: "the pull request also closes a ticket whose own pull request is another",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[941, 942]))
                .ticket(942, open(972, "room/syn-a6-0942", &[942]))
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(cloud("thr_syn_0042", "room/syn-a6-0942")),
            builders: vec![(941, none()), (942, json!({"known": "thr_syn_0042"}))],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "several_issues"}]}),
        },
        Case {
            what: "a reviewer's thread: its branch heads no pull request",
            fleet: Fleet::default()
                .ticket(941, the_pr())
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(cloud("thr_syn_0051", "room/941-synthetic-review")),
            builders: vec![(941, json!({"known": "thr_syn_0041"}))],
            unplaced: json!({"known": [{"thread": "thr_syn_0051", "reason": "no_pull_request"}]}),
        },
        Case {
            what: "no threads at all",
            fleet: Fleet::default().ticket(941, the_pr()),
            builders: vec![(941, none())],
            unplaced: json!({"known": []}),
        },
    ]);
}

fn a_pull_request_that_is_no_tickets_places_nothing() {
    let fleet = Fleet::default()
        .ticket(941, Pr::None)
        .thread(cloud("thr_syn_0041", "room/syn-blocker-0840"));
    let mut reads = fleet.reads();
    let id = ReadId(u32::try_from(reads.len()).expect("few") + 1);
    reads.push(Read {
        id,
        kind: ReadKind::PrDiscovery {
            issue: n(840),
            outcome: Outcome::Complete {
                value: pull_request(&open(870, "room/syn-blocker-0840", &[840])),
            },
        },
    });
    let placements = agents::place(n(SPEC), &reads).expect("on the record");
    assert_eq!(printed(&placements.builder(n(941))), none());
    assert_eq!(printed(&placements.builder(n(840))), none());
    assert_eq!(
        unplaced(&placements),
        json!({"known": [{"thread": "thr_syn_0041", "reason": "no_pull_request"}]})
    );
}

fn the_first_reason_that_applies_is_the_one_given() {
    check(vec![
        Case {
            what: "a shared branch that heads no pull request: shared_branch first",
            fleet: Fleet::default()
                .ticket(941, Pr::None)
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(cloud("thr_syn_0042", HEAD)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [
                {"thread": "thr_syn_0041", "reason": "shared_branch"},
                {"thread": "thr_syn_0042", "reason": "shared_branch"}
            ]}),
        },
        Case {
            what: "a shared branch that heads several tickets' pull requests: shared_branch first",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[941, 942]))
                .ticket(942, open(971, HEAD, &[941, 942]))
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(cloud("thr_syn_0042", HEAD)),
            builders: vec![(941, none()), (942, none())],
            unplaced: json!({"known": [
                {"thread": "thr_syn_0041", "reason": "shared_branch"},
                {"thread": "thr_syn_0042", "reason": "shared_branch"}
            ]}),
        },
        Case {
            what: "several tickets, one of whose pull requests closes other issues too: several_tickets first",
            fleet: Fleet::default()
                .ticket(941, open(971, HEAD, &[777, 941]))
                .ticket(942, open(972, HEAD, &[942]))
                .thread(cloud("thr_syn_0041", HEAD)),
            builders: vec![(941, none()), (942, none())],
            unplaced: json!({"known": [{"thread": "thr_syn_0041", "reason": "several_tickets"}]}),
        },
        Case {
            what: "a thread with no branch beside threads that share one: each its own reason",
            fleet: Fleet::default()
                .ticket(941, the_pr())
                .thread(Row::Local("thr_syn_0040", None))
                .thread(cloud("thr_syn_0041", HEAD))
                .thread(Row::Local("thr_syn_0042", None))
                .thread(cloud("thr_syn_0043", HEAD)),
            builders: vec![(941, none())],
            unplaced: json!({"known": [
                {"thread": "thr_syn_0040", "reason": "no_branch"},
                {"thread": "thr_syn_0041", "reason": "shared_branch"},
                {"thread": "thr_syn_0042", "reason": "no_branch"},
                {"thread": "thr_syn_0043", "reason": "shared_branch"}
            ]}),
        },
    ]);
}

#[test]
fn a_thread_is_placed_at_most_once_and_every_thread_is_listed_once() {
    let prs = [
        Pr::None,
        open(971, "room/syn-p-0001", &[941]),
        open(971, "room/syn-p-0001", &[941, 942]),
        open(972, "room/syn-p-0002", &[942]),
        open(973, "room/syn-p-0001", &[777, 942]),
        Pr::Several(&[971, 972]),
    ];
    let branches = [
        Row::Local("x", None),
        cloud("x", "room/syn-p-0001"),
        cloud("x", "room/syn-p-0002"),
        cloud("x", "room/syn-p-0003"),
    ];
    let ids = ["thr_syn_0061", "thr_syn_0062", "thr_syn_0063"];
    let mut fleets = 0;
    for a in &prs {
        for b in &prs {
            for i in 0..branches.len().pow(3) {
                let mut fleet = Fleet::default()
                    .ticket(941, a.clone())
                    .ticket(942, b.clone());
                for (k, id) in ids.iter().enumerate() {
                    let row = match &branches[i / branches.len().pow(k as u32) % branches.len()] {
                        Row::Local(_, branch) => Row::Local(id, *branch),
                        Row::Cloud(_, branch) => Row::Cloud(id, branch.clone()),
                    };
                    fleet = fleet.thread(row);
                }
                let placements = fleet.place();
                let mut seen: Vec<String> = Vec::new();
                for (_, builder) in builders(&fleet, &placements) {
                    if let Some(id) = builder["known"].as_str() {
                        seen.push(id.to_owned());
                    }
                }
                let listed = unplaced(&placements);
                for entry in listed["known"].as_array().expect("known") {
                    seen.push(entry["thread"].as_str().expect("an id").to_owned());
                }
                seen.sort();
                assert_eq!(seen, ids, "each thread once: {}", listed);
                fleets += 1;
            }
        }
    }
    assert_eq!(fleets, 6 * 6 * 64);
}

type Spoil = fn(&mut Read);

fn fail(read: &mut Read) {
    let failed = || Failed {
        gap: GapKind::CommandFailed,
        reason: ne("a synthetic read failed"),
    };
    match &mut read.kind {
        ReadKind::SubIssues { outcome, .. } => *outcome = ListOutcome::Failed(failed()),
        ReadKind::PrDiscovery { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::Projects { outcome } => *outcome = ListOutcome::Failed(failed()),
        ReadKind::Threads { outcome } => *outcome = ListOutcome::Failed(failed()),
        ReadKind::Workspace { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::BlockedBy { outcome, .. } => *outcome = ListOutcome::Failed(failed()),
        ReadKind::Issue { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::Checks { outcome, .. } => *outcome = ListOutcome::Failed(failed()),
        ReadKind::Comments { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::MergeReadback { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::Version { outcome, .. } => *outcome = Outcome::Failed(failed()),
        ReadKind::Repository { outcome } => *outcome = Outcome::Failed(failed()),
        ReadKind::SpecList { outcome } => *outcome = ListOutcome::Failed(failed()),
    }
}

fn truncate(read: &mut Read) {
    fn partial<T: Clone>(outcome: &mut ListOutcome<T>) {
        let ListOutcome::Complete { value } = outcome else {
            panic!("only a complete list is truncated here");
        };
        *outcome = ListOutcome::Partial {
            gap: Truncated::Truncated,
            reason: ne("a synthetic list was cut short"),
            value: value.clone(),
        };
    }
    match &mut read.kind {
        ReadKind::SubIssues { outcome, .. } => partial(outcome),
        ReadKind::Projects { outcome } => partial(outcome),
        ReadKind::Threads { outcome } => partial(outcome),
        _ => panic!("not a list read the chain requires"),
    }
}

fn two_tickets() -> Fleet {
    Fleet::default()
        .ticket(941, the_pr())
        .ticket(942, Pr::None)
        .thread(cloud("thr_syn_0041", HEAD))
        .thread(Row::Local("thr_syn_0049", Some("room/syn-local-0049")))
        .thread(cloud("thr_syn_0042", "room/syn-x-0042"))
}

fn every_value(fleet: &Fleet, reads: &[Read]) -> Vec<Value> {
    let placements = agents::place(n(SPEC), reads).expect("on the record");
    let mut values: Vec<Value> = fleet
        .tickets
        .iter()
        .map(|(t, _)| printed(&placements.builder(n(*t))))
        .collect();
    values.push(unplaced(&placements));
    values
}

fn id_of(reads: &[Read], at: usize) -> String {
    format!("r{}", reads[at].id.0)
}

fn the_read_rule_fleet_is_complete_and_placed() {
    let fleet = two_tickets();
    let reads = fleet.reads();
    let kinds: Vec<&str> = reads.iter().map(|r| kind(&r.kind)).collect();
    assert_eq!(
        kinds,
        [
            "sub_issues",
            "pr_discovery",
            "pr_discovery",
            "projects",
            "threads",
            "workspace",
            "workspace"
        ]
    );
    assert_eq!(
        every_value(&fleet, &reads),
        [
            json!({"known": "thr_syn_0041"}),
            json!({"known": null}),
            json!({"known": [
                {"thread": "thr_syn_0049", "reason": "no_pull_request"},
                {"thread": "thr_syn_0042", "reason": "no_pull_request"}
            ]})
        ]
    );
}

fn kind(kind: &ReadKind) -> &'static str {
    match kind {
        ReadKind::Version { .. } => "version",
        ReadKind::Repository { .. } => "repository",
        ReadKind::SpecList { .. } => "spec_list",
        ReadKind::Issue { .. } => "issue",
        ReadKind::SubIssues { .. } => "sub_issues",
        ReadKind::BlockedBy { .. } => "blocked_by",
        ReadKind::PrDiscovery { .. } => "pr_discovery",
        ReadKind::Checks { .. } => "checks",
        ReadKind::Comments { .. } => "comments",
        ReadKind::MergeReadback { .. } => "merge_readback",
        ReadKind::Projects { .. } => "projects",
        ReadKind::Threads { .. } => "threads",
        ReadKind::Workspace { .. } => "workspace",
    }
}

fn an_incomplete_read_behind_the_chain_leaves_every_builder_and_unplaced_unread() {
    let fleet = two_tickets();
    let cases: [(usize, Spoil); 9] = [
        (0, fail),
        (0, truncate),
        (1, fail),
        (2, fail),
        (3, fail),
        (3, truncate),
        (4, truncate),
        (5, fail),
        (6, fail),
    ];
    for (at, spoil) in cases {
        let mut reads = fleet.reads();
        spoil(&mut reads[at]);
        let unread = json!({"unread": [id_of(&reads, at)]});
        assert_eq!(
            every_value(&fleet, &reads),
            [unread.clone(), unread.clone(), unread],
            "read {at} ({})",
            kind(&reads[at].kind)
        );
    }
}

fn several_incomplete_reads_are_named_once_each_in_the_order_of_reads() {
    let fleet = two_tickets();
    let mut reads = fleet.reads();
    for at in [6, 1, 3] {
        fail(&mut reads[at]);
    }
    truncate(&mut reads[4]);
    let unread = json!({"unread": ["r2", "r4", "r5", "r7"]});
    assert_eq!(
        every_value(&fleet, &reads),
        [unread.clone(), unread.clone(), unread]
    );

    let mut shuffled = reads.clone();
    shuffled.reverse();
    let unread = json!({"unread": ["r7", "r5", "r4", "r2"]});
    assert_eq!(
        every_value(&fleet, &shuffled),
        [unread.clone(), unread.clone(), unread]
    );
}

fn a_failed_ticket_or_thread_list_requires_nothing_it_would_have_listed() {
    let fleet = two_tickets();

    let mut reads = fleet.reads();
    fail(&mut reads[0]);
    let without_prs: Vec<Read> = reads
        .iter()
        .filter(|r| !matches!(r.kind, ReadKind::PrDiscovery { .. }))
        .cloned()
        .collect();
    let unread = json!({"unread": ["r1"]});
    assert_eq!(
        every_value(&fleet, &without_prs),
        [unread.clone(), unread.clone(), unread]
    );

    let mut reads = fleet.reads();
    fail(&mut reads[4]);
    let without_branches: Vec<Read> = reads
        .iter()
        .filter(|r| !matches!(r.kind, ReadKind::Workspace { .. }))
        .cloned()
        .collect();
    let unread = json!({"unread": ["r5"]});
    assert_eq!(
        every_value(&fleet, &without_branches),
        [unread.clone(), unread.clone(), unread]
    );
}

fn a_read_the_chain_does_not_require_never_makes_it_unread() {
    let fleet = two_tickets();
    let mut reads = fleet.reads();
    let next = |reads: &Vec<Read>| ReadId(u32::try_from(reads.len()).expect("few") + 1);
    let failed = || Failed {
        gap: GapKind::NotFound,
        reason: ne("a synthetic read failed"),
    };
    let others = vec![
        ReadKind::Version {
            source: SourceName::Cloudroom,
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::Repository {
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::Issue {
            issue: n(SPEC),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::Issue {
            issue: n(941),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::BlockedBy {
            ticket: n(941),
            outcome: ListOutcome::Failed(failed()),
        },
        ReadKind::Checks {
            pr: n(971),
            outcome: ListOutcome::Failed(failed()),
        },
        ReadKind::Comments {
            pr: n(971),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::MergeReadback {
            pr: n(971),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::PrDiscovery {
            issue: n(840),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::SubIssues {
            spec: n(930),
            outcome: ListOutcome::Failed(failed()),
        },
        ReadKind::Workspace {
            thread: ne("thr_syn_0099"),
            outcome: Outcome::Failed(failed()),
        },
        ReadKind::Workspace {
            thread: ne("thr_syn_0049"),
            outcome: Outcome::Failed(failed()),
        },
    ];
    for kind in others {
        let id = next(&reads);
        reads.push(Read { id, kind });
    }
    assert_eq!(
        every_value(&fleet, &reads),
        every_value(&fleet, &fleet.reads())
    );
}

fn a_required_read_missing_from_the_record_or_on_it_twice_is_refused() {
    let fleet = two_tickets();
    let needed = [
        (0, Needed::SubIssues(n(SPEC))),
        (1, Needed::PrDiscovery(n(941))),
        (2, Needed::PrDiscovery(n(942))),
        (3, Needed::Projects),
        (4, Needed::Threads),
        (5, Needed::Workspace(ne("thr_syn_0041"))),
        (6, Needed::Workspace(ne("thr_syn_0042"))),
    ];
    for (at, need) in needed {
        let mut reads = fleet.reads();
        reads.remove(at);
        assert_eq!(
            agents::place(n(SPEC), &reads),
            Err(RecordError::Missing(need.clone())),
            "without read {at}"
        );
        let mut reads = fleet.reads();
        let mut copy = reads[at].clone();
        copy.id = ReadId(99);
        fail(&mut copy);
        reads.push(copy);
        assert_eq!(
            agents::place(n(SPEC), &reads),
            Err(RecordError::Repeated(need)),
            "read {at} twice"
        );
    }
}

fn no_chain_places_a_reviewer() {
    assert_eq!(
        serde_json::to_value(agents::reviewer()).expect("prints"),
        json!({"undefined": "no verified chain places a reviewer in version 1"})
    );
    assert_eq!(
        REVIEWER_REASON,
        "no verified chain places a reviewer in version 1"
    );
}

pub(crate) fn sub_schema(pointer: &str) -> Value {
    let schema = crate::schema::load_schema();
    let mut sub = serde_json::Map::new();
    sub.insert("$defs".to_owned(), schema["$defs"].clone());
    sub.insert("$ref".to_owned(), json!(pointer));
    Value::Object(sub)
}

fn every_builder_and_unplaced_the_chain_gives_matches_the_schema() {
    let builder = sub_schema("#/$defs/ticket/properties/builder");
    let unplaced_schema = sub_schema("#/$defs/fleet_view/properties/unplaced");
    for bad in [
        json!({"known": ""}),
        json!({"known": 1}),
        json!("thr_syn_0001"),
        json!({"unread": ["x1"]}),
    ] {
        assert!(!crate::schema::validate(&builder, &bad).is_empty(), "{bad}");
    }
    for bad in [
        json!({"known": [{"thread": "thr_syn_0001", "reason": "no_match"}]}),
        json!({"known": [{"thread": "thr_syn_0001"}]}),
        json!({"known": [["thr_syn_0001", "no_branch"]]}),
    ] {
        assert!(
            !crate::schema::validate(&unplaced_schema, &bad).is_empty(),
            "{bad}"
        );
    }

    let mut values: Vec<(Value, Value)> = Vec::new();
    let fleet = two_tickets();
    let mut spoiled = vec![fleet.reads()];
    for at in 0..fleet.reads().len() {
        let mut reads = fleet.reads();
        fail(&mut reads[at]);
        spoiled.push(reads);
    }
    for reads in spoiled {
        let placements = agents::place(n(SPEC), &reads).expect("on the record");
        for (t, _) in &fleet.tickets {
            values.push((builder.clone(), printed(&placements.builder(n(*t)))));
        }
        values.push((unplaced_schema.clone(), unplaced(&placements)));
    }
    for fleet in [
        Fleet::default()
            .ticket(941, open(971, HEAD, &[941, 942]))
            .ticket(942, open(971, HEAD, &[941, 942]))
            .thread(Row::Local("thr_syn_0040", None))
            .thread(cloud("thr_syn_0041", HEAD))
            .thread(cloud("thr_syn_0042", HEAD))
            .thread(cloud("thr_syn_0043", "room/syn-x")),
        Fleet::default()
            .ticket(941, open(971, HEAD, &[777, 941]))
            .ticket(942, the_pr())
            .thread(cloud("thr_syn_0041", HEAD)),
        Fleet::default()
            .ticket(941, the_pr())
            .thread(cloud("thr_syn_0041", HEAD)),
    ] {
        let placements = fleet.place();
        for (t, _) in &fleet.tickets {
            values.push((builder.clone(), printed(&placements.builder(n(*t)))));
        }
        values.push((unplaced_schema.clone(), unplaced(&placements)));
    }
    assert_eq!(values.len(), 8 * 3 + 3 + 3 + 2);
    for (schema, value) in values {
        assert_eq!(
            crate::schema::validate(&schema, &value),
            Vec::<String>::new(),
            "{value}"
        );
    }
}
