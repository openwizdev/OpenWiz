//! A5 (ClosedWiz#113): `openwiz fleet <spec> [--json]`, one fleet's
//! tickets, on a fake `gh` ([`World`], in `a5_world.rs`).
//!
//! The proofs, from spec #107:
//! - **S1-2, only a merge read back counts as merged:** an approval, a
//!   ready pull request, a closed issue, or GitHub's own `MERGED` whose
//!   merge isn't found on the base, never shows as merged, for a ticket or
//!   a blocker;
//! - **S1-3, unknowns stay unknown, with reasons; a failed read makes the
//!   answer partial:** each read failing, each way, is recorded with its
//!   gap, and every value it reaches names exactly it;
//! - **S1-5, the `--json` output matches the contract:** every envelope
//!   these tests print passes the schema, and the contract's own example
//!   fleet comes out exactly as the contract prints it, but for the agents
//!   (A6, #114), which are recorded as not read.
//!
//! Expected values are written out, or taken from the contract's example:
//! never worked out the way the code works them out.
//!
//! **Fixtures only.** Fixture tests never prove live behaviour.

#[path = "a5_world.rs"]
mod world;

#[path = "a5_agents_cli.rs"]
mod cli_agents;

use std::process::Command;
use std::time::Duration;

use openwiz_adapter_github::allowlist;
use openwiz_core::fleet::tickets::AGENTS_NOT_READ;
use serde_json::{Value, json};

use crate::schema;
use crate::support::{fakes_on_path, left_behind, openwiz_release};
use world::{
    IssueW, OTHER_URL, PrW, World, answer, argv, checks_argv, comments_argv, compare_argv,
    issue_argv, issue_json, oid, pr_argv, pr_json,
};

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/fleet.v1.md");

/// Checks `envelope` against `contracts/fleet.v1.schema.json`.
fn conforms(envelope: &Value) {
    let errors = schema::validate(&schema::load_schema(), envelope);
    assert!(
        errors.is_empty(),
        "the envelope breaks the schema: {errors:#?}"
    );
}

/// Runs `openwiz fleet <spec> --json` on `world` and checks the envelope
/// against the schema.
fn envelope(world: &World, test: &str, spec: &str) -> Value {
    let got = world.run(test, &[spec, "--json"]).json();
    conforms(&got);
    got
}

/// The read with this id.
fn read<'a>(envelope: &'a Value, id: &str) -> &'a Value {
    envelope["reads"]
        .as_array()
        .expect("reads")
        .iter()
        .find(|r| r["id"] == id)
        .unwrap_or_else(|| panic!("no read {id}"))
}

/// Each ticket's number and state.
fn states(envelope: &Value) -> Vec<(u64, Value)> {
    envelope["data"]["tickets"]
        .as_array()
        .expect("tickets")
        .iter()
        .map(|t| (t["number"].as_u64().expect("number"), t["state"].clone()))
        .collect()
}

/// Each blocker's number and `merged`.
fn merged(envelope: &Value) -> Vec<(u64, Value)> {
    envelope["data"]["blockers"]
        .as_array()
        .expect("blockers")
        .iter()
        .map(|b| (b["number"].as_u64().expect("number"), b["merged"].clone()))
        .collect()
}

fn known(state: &str) -> Value {
    json!({"known": state})
}

fn unknown(why: &str) -> Value {
    json!({"unknown": why})
}

fn unread(ids: &[&str]) -> Value {
    json!({"unread": ids})
}

const CLOSED: &str = "closed on GitHub, and no merge was read back";
const NOT_ON_BASE: &str = "its pull request is merged, but the merge wasn't found on its base";

// ---------------------------------------------------------------------
// S1-2: only a merge read back counts as merged.
// ---------------------------------------------------------------------

/// Spec 1's tickets: an approval (2), a ready pull request (3), a closed
/// issue (4), GitHub's `MERGED` not found on the base, on a closed (5) and
/// an open (6) issue, one merge read back (7), an approval on a closed issue
/// (8), and two tickets blocked by them (9 by 2 to 6, 10 by 7).
fn merge_world() -> World {
    let mut not_on_base = PrW::merged(&[5], '5', 'b');
    not_on_base.ahead_by = 3;
    let mut not_on_base_open = PrW::merged(&[6], '6', 'c');
    not_on_base_open.ahead_by = 1;
    World::default()
        .spec(1, &[2, 3, 4, 5, 6, 7, 8, 9, 10])
        .issue(2, IssueW::ticket("Approved").closed_by(&[20]))
        .pr(20, PrW::open(&[2], '2').verdict("APPROVE", '2'))
        .issue(3, IssueW::ticket("Ready pull request").closed_by(&[30]))
        .pr(30, PrW::open(&[3], '3'))
        .issue(4, IssueW::ticket("Closed issue").closed())
        .issue(
            5,
            IssueW::ticket("Merged not on base, closed")
                .closed()
                .closed_by(&[50]),
        )
        .pr(50, not_on_base)
        .issue(
            6,
            IssueW::ticket("Merged not on base, open").closed_by(&[60]),
        )
        .pr(60, not_on_base_open)
        .issue(
            7,
            IssueW::ticket("Merged and read back")
                .closed()
                .closed_by(&[70]),
        )
        .pr(70, PrW::merged(&[7], '7', 'a'))
        .issue(
            8,
            IssueW::ticket("Approved but closed")
                .closed()
                .closed_by(&[80]),
        )
        .pr(80, PrW::open(&[8], '8').verdict("APPROVE", '8'))
        .issue(
            9,
            IssueW::ticket("Blocked by the near misses").blocked_by(&[2, 3, 4, 5, 6]),
        )
        .issue(
            10,
            IssueW::ticket("Blocked by the real merge").blocked_by(&[7]),
        )
}

#[test]
fn an_approval_a_ready_pull_request_or_a_closed_issue_never_shows_as_merged() {
    let got = envelope(&merge_world(), "merge_rules", "1");
    assert_eq!(
        states(&got),
        vec![
            (2, known("in_review")),
            (3, known("in_review")),
            (4, unknown(CLOSED)),
            (5, unknown(CLOSED)),
            (6, unknown(NOT_ON_BASE)),
            (7, known("merged")),
            (8, unknown(CLOSED)),
            (9, known("blocked")),
            (10, known("ready")),
        ]
    );
    assert_eq!(
        merged(&got),
        vec![
            (2, json!({"known": false})),
            (3, json!({"known": false})),
            (4, json!({"known": false})),
            (5, json!({"known": false})),
            (6, json!({"known": false})),
            (7, json!({"known": true})),
        ]
    );
    assert_eq!(
        got["data"]["fleet"]["progress"],
        json!({"known": {"tickets": 9, "ready": 1, "building": 0, "in_review": 2,
            "changes_requested": 0, "merged": 1, "held": 0, "blocked": 1, "unknown": 4}})
    );
}

#[test]
fn a_merge_whose_read_back_failed_is_never_merged() {
    let world = merge_world().answer(&compare_argv("main", &oid('a')), answer("", 1));
    let got = envelope(&world, "merge_read_back_failed", "1");
    // #7's merge read back is the failed read; #10 waits on it as a blocker.
    let id = got["data"]["tickets"][5]["on_base"]
        .as_str()
        .expect("#7's on_base")
        .to_owned();
    assert_eq!(read(&got, &id)["outcome"]["state"], "failed");
    assert_eq!(read(&got, &id)["outcome"]["gap"], "command_failed");
    let states = states(&got);
    assert_eq!(states[5], (7, unread(&[&id])));
    assert_eq!(states[8], (10, unread(&[&id])));
    assert_eq!(merged(&got)[5], (7, unread(&[&id])));
    assert_eq!(got["data"]["fleet"]["progress"], unread(&[&id]));
    assert_eq!(got["coverage"]["state"], "partial");
}

#[test]
fn a_base_branch_gh_isnt_given_leaves_the_merge_unread_and_runs_nothing() {
    let mut pr = PrW::merged(&[2], '2', 'a');
    pr.base = "synthetic base".to_owned();
    let world = World::default()
        .spec(1, &[2])
        .issue(2, IssueW::ticket("Odd base").closed().closed_by(&[20]))
        .pr(20, pr);
    let ran = world.run("odd_base", &["1", "--json"]);
    let got = ran.json();
    conforms(&got);
    let id = got["data"]["tickets"][0]["on_base"]
        .as_str()
        .expect("on_base")
        .to_owned();
    assert_eq!(
        read(&got, &id)["outcome"],
        json!({"state": "failed", "gap": "command_failed", "reason": "the merge of pull request \
            #20, on its base, couldn't be read: could not be run: its base branch's name isn't \
            one OpenWiz passes to gh, so nothing was run"})
    );
    assert_eq!(states(&got), vec![(2, unread(&[&id]))]);
    assert!(
        ran.calls.iter().all(|c| c[0] != "api"),
        "a compare ran: {:?}",
        ran.calls
    );
}

#[test]
fn a_blockers_open_pull_request_is_never_read_for_checks_or_a_verdict() {
    // #50 is outside the fleet and blocks #3; its pull request #500 is
    // open. No value needs its checks or comments, so neither is read.
    let mut world = small_world()
        .issue(
            50,
            IssueW::ticket("Synthetic blocker elsewhere").closed_by(&[500]),
        )
        .pr(500, PrW::open(&[50], '5').verdict("APPROVE", '5'));
    world.issues.get_mut(&3).expect("#3").blocked_by = vec![2, 50];
    let ran = world.run("blocker_open_pr", &["1", "--json"]);
    let got = ran.json();
    conforms(&got);
    let kinds: Vec<(&str, Value)> = got["reads"]
        .as_array()
        .expect("reads")
        .iter()
        .filter(|r| r["issue"] == 50 || r["pr"] == 500)
        .map(|r| {
            (
                r["kind"].as_str().expect("kind"),
                r["outcome"]["state"].clone(),
            )
        })
        .collect();
    assert_eq!(
        kinds,
        [
            ("issue", json!("complete")),
            ("pr_discovery", json!("complete"))
        ]
    );
    for argv in [checks_argv(500), comments_argv(500)] {
        assert!(!ran.calls.contains(&argv), "{argv:?} ran");
    }
    assert_eq!(merged(&got)[1], (50, json!({"known": false})));
    assert_eq!(states(&got)[1], (3, known("blocked")));
}

// ---------------------------------------------------------------------
// S1-5: the contract's own example fleet, exactly.
// ---------------------------------------------------------------------

/// The contract's examples: every ```json block of `fleet.v1.md`.
fn contract_examples() -> Vec<Value> {
    let text = std::fs::read_to_string(CONTRACT).expect("the contract");
    let examples = text.split("\n## Examples\n").nth(1).expect("its examples");
    examples
        .split("```json\n")
        .skip(1)
        .map(|rest| rest.split("\n```").next().expect("a closed block"))
        .map(|block| serde_json::from_str(block).expect("an example is JSON"))
        .collect()
}

/// The GitHub side of the contract's example 2, `fleet 901`.
fn example_world() -> World {
    let ticket = |title: &str, owned: &str, relies: &str| {
        let mut issue = IssueW::ticket(title);
        issue.body =
            format!("Synthetic body.\n**Owned paths:** {owned}\n**Relies on:** {relies}\n");
        issue
    };
    let open = |closes: u64, head: &str, digit: char| {
        let mut pr = PrW::open(&[closes], digit);
        pr.head = head.to_owned();
        pr
    };
    let merged = |closes: u64, head: &str, digit: char, merge: char| {
        let mut pr = PrW::merged(&[closes], digit, merge);
        pr.head = head.to_owned();
        pr
    };
    let mut spec = IssueW::ticket("Synthetic spec one").labels(&["spec"]);
    spec.body = "Synthetic spec body.".to_owned();
    spec.sub_issues = (902..=910).collect();
    let mut draft = open(905, "room/syn-a4-0004", '5').checks(&[]);
    draft.draft = true;
    let mut old = ticket(
        "Synthetic ticket from 0.9.0",
        "`crates/example/src/old.rs`",
        "nothing",
    )
    .closed()
    .closed_by(&[801]);
    old.milestone = Some((6, "0.9.0".to_owned()));
    let mut none = IssueW::ticket("Synthetic ticket with no milestone")
        .labels(&[])
        .closed()
        .closed_by(&[802]);
    none.milestone = None;
    none.body = "Synthetic body without the template.".to_owned();
    World::default()
        .issue(901, spec)
        .issue(
            902,
            ticket(
                "Synthetic ticket A1",
                "`contracts/example.v1.md`",
                "nothing",
            )
            .closed()
            .closed_by(&[951]),
        )
        .pr(951, merged(902, "room/syn-a1-0001", '1', '2'))
        .issue(
            903,
            ticket(
                "Synthetic ticket A2",
                "`crates/example/src/a2.rs`",
                "`contracts/example.v1.md`",
            )
            .blocked_by(&[902])
            .closed_by(&[952]),
        )
        .pr(
            952,
            open(903, "room/syn-a2-0002", '3').verdict("APPROVE", '3'),
        )
        .issue(
            904,
            ticket(
                "Synthetic ticket A3",
                "`crates/example/src/a3.rs`",
                "nothing",
            )
            .labels(&["needs-info", "ready-for-agent"])
            .closed_by(&[953]),
        )
        .pr(
            953,
            open(904, "room/syn-a3-0003", '4').verdict("CHANGES", '4'),
        )
        .issue(
            905,
            ticket(
                "Synthetic ticket A4",
                "`crates/example/src/a4.rs`",
                "nothing",
            )
            .closed_by(&[954]),
        )
        .pr(954, draft)
        .issue(
            906,
            ticket(
                "Synthetic ticket A5",
                "`crates/example/src/a5.rs`",
                "`contracts/example.v1.md`",
            )
            .blocked_by(&[902]),
        )
        .issue(
            907,
            ticket(
                "Synthetic ticket A6",
                "`crates/example/src/a6.rs`",
                "`contracts/example.v1.md`",
            )
            .labels(&["held"]),
        )
        .issue(
            908,
            ticket(
                "Synthetic ticket A7",
                "`crates/example/src/a7.rs`",
                "nothing",
            )
            .blocked_by(&[811, 812, 903]),
        )
        .issue(
            909,
            ticket(
                "Synthetic ticket A8",
                "`crates/example/src/a8.rs`",
                "nothing",
            )
            .closed(),
        )
        .issue(
            910,
            ticket(
                "Synthetic ticket A9",
                "`crates/example/src/a9.rs`",
                "nothing",
            )
            .closed_by(&[955]),
        )
        .pr(
            955,
            open(910, "room/syn-a9-0006", '6')
                .checks(&[("build", "pass"), ("test", "fail")])
                .verdict("CHANGES", '7'),
        )
        .issue(811, old)
        .pr(801, merged(811, "room/syn-old-0801", 'a', 'b'))
        .issue(812, none)
        .pr(802, merged(812, "room/syn-old-0802", 'c', 'd'))
}

/// The contract's example 2 as A5 prints it: the CloudRoom reads (r2, the
/// project and thread lists) recorded as not made, so no workspace read,
/// every builder and `unplaced` unread, and the coverage partial.
fn example_as_a5_prints_it() -> Value {
    let mut expected = contract_examples().swap_remove(1);
    assert_eq!(expected["data"]["view"], "fleet", "example 2 is fleet 901");
    let not_read = json!({"state": "failed", "gap": "budget_exhausted", "reason": AGENTS_NOT_READ});
    let reads = expected["reads"].as_array_mut().expect("reads");
    reads.retain(|r| r["kind"] != "workspace");
    for read in reads.iter_mut() {
        if read["id"] == "r2" || read["kind"] == "projects" || read["kind"] == "threads" {
            read["outcome"] = not_read.clone();
        }
    }
    assert_eq!(
        (reads.len(), &reads[47]["id"], &reads[48]["id"]),
        (49, &json!("r48"), &json!("r49"))
    );
    for ticket in expected["data"]["tickets"].as_array_mut().expect("tickets") {
        ticket["builder"] = unread(&["r48", "r49"]);
    }
    expected["data"]["unplaced"] = unread(&["r48", "r49"]);
    expected["coverage"]["state"] = json!("partial");
    expected
}

#[test]
fn the_contracts_example_fleet_comes_out_exactly_but_for_the_agents() {
    let got = envelope(&example_world(), "contract_example", "901");
    let expected = example_as_a5_prints_it();
    conforms(&expected);
    assert_eq!(got, expected);
}

#[test]
fn through_the_agents_seam_the_contracts_example_fleet_comes_out_exactly() {
    // The seam A6 (#114) fills: given the example's own CloudRoom reads and
    // placements, the view records them where the contract does (room-cli's
    // version second, the lists and branches last) and prints its builders
    // and `unplaced`: the example itself, unchanged.
    let mut world = example_world();
    world.agents = Some(std::sync::Arc::new(world::ExampleAgents));
    let got = envelope(&world, "contract_example_with_agents", "901");
    assert_eq!(got, contract_examples().swap_remove(1));
    let text = world
        .run("contract_example_with_agents_text", &["901"])
        .stdout;
    for line in [
        "  builder: thr_syn_0002",
        "  builder: none placed",
        "agents: unplaced: thr_syn_0007 (no pull request), thr_syn_0008 (no pull request), \
         thr_syn_0009 (no pull request)",
    ] {
        assert!(
            text.lines().any(|l| l == line),
            "{line:?} is not in:\n{text}"
        );
    }
}

#[test]
fn it_reads_each_thing_once_and_only_through_the_allowlist() {
    let ran = example_world().run("contract_example_calls", &["901", "--json"]);
    assert_eq!(ran.code, 0);
    let mut calls = ran.calls.clone();
    calls.sort();
    let mut expected = vec![
        argv(&["--version"]),
        argv(&["repo", "view", "--json", "nameWithOwner,url"]),
    ];
    expected.extend([901, 902, 903, 904, 905, 906, 907, 908, 909, 910, 811, 812].map(issue_argv));
    expected.extend([951, 952, 953, 954, 955, 801, 802].map(pr_argv));
    expected.extend([952, 953, 954, 955].map(checks_argv));
    expected.extend([952, 953, 954, 955].map(comments_argv));
    expected.push(compare_argv("main", &oid('2')));
    expected.push(compare_argv("main", &oid('b')));
    expected.push(compare_argv("main", &oid('d')));
    expected.sort();
    assert_eq!(calls, expected);
    for call in &ran.calls {
        let words: Vec<&str> = call.iter().map(String::as_str).collect();
        assert!(
            allowlist::allowed(&words),
            "{call:?} is not on the allowlist"
        );
    }
}

// ---------------------------------------------------------------------
// S1-3: unknowns stay unknown, with reasons; a failed read makes the
// answer partial.
// ---------------------------------------------------------------------

/// Spec 1: #2 with an approved, passing pull request #20; #3 blocked by #2.
/// Its reads: r1 gh's version, r2 room-cli's (not made), r3 the
/// repository, r4 and r5 the spec and its tickets, r6 to r10 #2 and its
/// pull request's checks and comments, r11 to r13 #3, r14 and r15 the
/// project and thread lists (not made).
fn small_world() -> World {
    World::default()
        .spec(1, &[2, 3])
        .issue(2, IssueW::ticket("Synthetic two").closed_by(&[20]))
        .pr(20, PrW::open(&[2], '2').verdict("APPROVE", '2'))
        .issue(3, IssueW::ticket("Synthetic three").blocked_by(&[2]))
}

#[test]
fn the_small_world_is_complete_on_github() {
    let got = envelope(&small_world(), "small_world", "1");
    let incomplete: Vec<&Value> = got["reads"]
        .as_array()
        .expect("reads")
        .iter()
        .filter(|r| r["outcome"]["state"] != "complete")
        .map(|r| &r["id"])
        .collect();
    assert_eq!(incomplete, [&json!("r2"), &json!("r14"), &json!("r15")]);
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, known("blocked"))]
    );
}

/// A gh answer with the first key given twice.
fn duplicate_key(value: &Value) -> String {
    let text = value.to_string();
    let first = text.split(',').next().expect("a first key");
    format!("{first},{}", &text[1..])
}

/// One way a read fails, and what it must leave.
struct Failure {
    name: &'static str,
    argv: Vec<String>,
    response: Value,
    /// The failed read's id and gap.
    read: (&'static str, &'static str),
    /// #2's and #3's states, #2's `merged` as a blocker, the progress.
    two: Value,
    three: Value,
    blocker: Value,
    progress: Value,
}

#[test]
fn each_failed_read_is_recorded_and_every_value_it_reaches_names_it() {
    let two = issue_json(2, &IssueW::ticket("Synthetic two").closed_by(&[20]));
    let mut extra = two.clone();
    extra["synthetic"] = json!("an extra key");
    let mut wrong = two.clone();
    wrong["subIssues"]["totalCount"] = json!("0");
    let mut float = two.clone();
    float["blockedBy"]["totalCount"] = json!(0.0);
    let issue_failed = |name, response, gap| Failure {
        name,
        argv: issue_argv(2),
        response,
        read: ("r6", gap),
        two: unread(&["r6", "r7", "r8"]),
        three: unread(&["r8"]),
        blocker: unread(&["r8"]),
        progress: unread(&["r6", "r7", "r8"]),
    };
    let cases = [
        issue_failed("issue_exit", answer("", 1), "command_failed"),
        issue_failed("issue_not_json", answer("{\"title\": ", 0), "malformed"),
        issue_failed(
            "issue_duplicate_key",
            answer(&duplicate_key(&two), 0),
            "malformed",
        ),
        issue_failed(
            "issue_extra_key",
            answer(&extra.to_string(), 0),
            "malformed",
        ),
        issue_failed(
            "issue_wrong_type",
            answer(&wrong.to_string(), 0),
            "malformed",
        ),
        issue_failed("issue_float", answer(&float.to_string(), 0), "malformed"),
        Failure {
            name: "pr_exit",
            argv: pr_argv(20),
            response: answer("", 1),
            read: ("r8", "command_failed"),
            two: unread(&["r8"]),
            three: unread(&["r8"]),
            blocker: unread(&["r8"]),
            progress: unread(&["r8"]),
        },
        Failure {
            name: "pr_positional",
            argv: pr_argv(20),
            response: answer("[20, \"OPEN\"]", 0),
            read: ("r8", "malformed"),
            two: unread(&["r8"]),
            three: unread(&["r8"]),
            blocker: unread(&["r8"]),
            progress: unread(&["r8"]),
        },
        Failure {
            name: "checks_exit",
            argv: checks_argv(20),
            response: answer("", 1),
            read: ("r9", "command_failed"),
            two: unread(&["r9"]),
            three: known("blocked"),
            blocker: json!({"known": false}),
            progress: unread(&["r9"]),
        },
        Failure {
            name: "checks_tagged_bucket",
            argv: checks_argv(20),
            response: answer("[{\"bucket\": {\"pass\": null}, \"name\": \"build\"}]", 0),
            read: ("r9", "malformed"),
            two: unread(&["r9"]),
            three: known("blocked"),
            blocker: json!({"known": false}),
            progress: unread(&["r9"]),
        },
        Failure {
            name: "verdict_not_review_tickets_form",
            argv: comments_argv(20),
            response: answer(
                &json!([format!("VERDICT: approve at {}", oid('2'))]).to_string(),
                0,
            ),
            read: ("r10", "malformed"),
            two: unread(&["r10"]),
            three: known("blocked"),
            blocker: json!({"known": false}),
            progress: unread(&["r10"]),
        },
        Failure {
            name: "verdict_short_commit",
            argv: comments_argv(20),
            response: answer(&json!(["VERDICT: APPROVE at 2222222"]).to_string(), 0),
            read: ("r10", "malformed"),
            two: unread(&["r10"]),
            three: known("blocked"),
            blocker: json!({"known": false}),
            progress: unread(&["r10"]),
        },
    ];
    for case in cases {
        let world = small_world().answer(&case.argv, case.response);
        let got = envelope(&world, &format!("failure_{}", case.name), "1");
        let (id, gap) = case.read;
        let failed = &read(&got, id)["outcome"];
        assert_eq!(
            (&failed["state"], &failed["gap"]),
            (&json!("failed"), &json!(gap)),
            "{}",
            case.name
        );
        let reason = failed["reason"].as_str().expect("a reason");
        assert!(
            !reason.contains("synthetic") && !reason.contains('{'),
            "{}: {reason}",
            case.name
        );
        assert_eq!(
            states(&got),
            vec![(2, case.two), (3, case.three)],
            "{}",
            case.name
        );
        assert_eq!(merged(&got), vec![(2, case.blocker)], "{}", case.name);
        assert_eq!(
            got["data"]["fleet"]["progress"], case.progress,
            "{}",
            case.name
        );
        assert_eq!(got["coverage"]["state"], "partial", "{}", case.name);
    }
}

/// A guard, planted: the change to the small world, the failed read and
/// its reason, and #2's and #3's states.
struct Plant {
    name: &'static str,
    plant: fn(&mut World),
    read: &'static str,
    reason: &'static str,
    two: Value,
    three: Value,
}

#[test]
fn each_guard_refuses_what_it_exists_for() {
    let pr_failed = |name, plant, reason| Plant {
        name,
        plant,
        read: "r8",
        reason,
        two: unread(&["r8"]),
        three: unread(&["r8"]),
    };
    let blockers_failed = |name, plant, reason| Plant {
        name,
        plant,
        read: "r12",
        reason,
        two: known("in_review"),
        three: unread(&["r12"]),
    };
    let plants = [
        blockers_failed(
            "self_block",
            |w| w.issues.get_mut(&3).expect("#3").blocked_by = vec![2, 3],
            "GitHub listed #3 as its own blocker",
        ),
        blockers_failed(
            "listed_twice",
            |w| w.issues.get_mut(&3).expect("#3").blocked_by = vec![2, 2],
            "GitHub listed one of #3's blockers twice",
        ),
        blockers_failed(
            "more_than_total",
            |w| w.issues.get_mut(&3).expect("#3").blocked_total = Some(0),
            "GitHub listed 1 of #3's blockers, more than its total of 0",
        ),
        pr_failed(
            "closes_doesnt_name_it",
            |w| w.prs.get_mut(&20).expect("#20").closes = vec![3],
            "GitHub says pull request #20 closes #2, but its closing references don't name #2",
        ),
        pr_failed(
            "closes_twice",
            |w| w.prs.get_mut(&20).expect("#20").closes = vec![2, 2],
            "GitHub listed an issue twice among pull request #20's closing references",
        ),
        pr_failed(
            "closes_elsewhere_too",
            |w| w.prs.get_mut(&20).expect("#20").closes_elsewhere = vec![2],
            "pull request #20 also closes an issue of another repository; OpenWiz reads one \
             repository",
        ),
        pr_failed(
            "names_another_pull_request",
            |w| {
                let pr = w.prs[&20].clone();
                w.answers
                    .insert(pr_argv(20), answer(&pr_json(21, &pr).to_string(), 0));
            },
            "pull request #20 couldn't be read: returned malformed output: gh's pull request \
             answer: it names another pull request",
        ),
        Plant {
            name: "check_twice",
            plant: |w| {
                w.prs.get_mut(&20).expect("#20").checks = vec![
                    ("build".into(), "pass".into()),
                    ("build".into(), "fail".into()),
                ]
            },
            read: "r9",
            reason: "GitHub listed one check of pull request #20 twice",
            two: unread(&["r9"]),
            three: known("blocked"),
        },
    ];
    for plant in plants {
        let mut world = small_world();
        (plant.plant)(&mut world);
        let got = envelope(&world, &format!("guard_{}", plant.name), "1");
        assert_eq!(
            read(&got, plant.read)["outcome"],
            json!({"state": "failed", "gap": "malformed", "reason": plant.reason}),
            "{}",
            plant.name
        );
        assert_eq!(
            states(&got),
            vec![(2, plant.two), (3, plant.three)],
            "{}",
            plant.name
        );
    }
    // The spec's own list: nothing is printed.
    for (name, sub_issues, reason) in [
        (
            "spec_self",
            vec![1, 2, 3],
            "GitHub listed #1 as its own sub-issue",
        ),
        (
            "spec_twice",
            vec![2, 3, 2],
            "GitHub listed one of #1's sub-issues twice",
        ),
    ] {
        let mut world = small_world();
        world.issues.get_mut(&1).expect("the spec").sub_issues = sub_issues;
        let ran = world.run(&format!("guard_{name}"), &["1", "--json"]);
        assert_eq!((ran.code, ran.stdout.as_str()), (1, ""), "{name}");
        assert_eq!(
            ran.stderr,
            format!("openwiz: fleet: #1's tickets couldn't be read (malformed): {reason}\n"),
            "{name}"
        );
    }
}

#[test]
fn where_rules_overlap_the_first_in_the_tables_order_wins() {
    let mut draft_changes = PrW::open(&[3], '3').verdict("CHANGES", '3');
    draft_changes.draft = true;
    let world = World::default()
        .spec(1, &[2, 3, 4, 5, 6, 7, 8, 9, 10])
        // 3 (held) before 6 (in review).
        .issue(
            2,
            IssueW::ticket("Held with an approved pull request")
                .labels(&["held", "ready-for-agent"])
                .closed_by(&[20]),
        )
        .pr(20, PrW::open(&[2], '2').verdict("APPROVE", '2'))
        // 4 (changes) before 5 (a draft).
        .issue(
            3,
            IssueW::ticket("A draft with changes asked").closed_by(&[30]),
        )
        .pr(30, draft_changes)
        // CI: failed before pending before passed; skipping counts for nothing.
        .issue(4, IssueW::ticket("Pending").closed_by(&[40]))
        .pr(
            40,
            PrW::open(&[4], '4').checks(&[("a", "pass"), ("b", "pending")]),
        )
        .issue(5, IssueW::ticket("Failed and pending").closed_by(&[50]))
        .pr(
            50,
            PrW::open(&[5], '5').checks(&[("a", "pending"), ("b", "fail")]),
        )
        .issue(6, IssueW::ticket("Cancelled").closed_by(&[60]))
        .pr(
            60,
            PrW::open(&[6], '6').checks(&[("a", "skipping"), ("b", "cancel")]),
        )
        .issue(7, IssueW::ticket("Only skipped").closed_by(&[70]))
        .pr(70, PrW::open(&[7], '7').checks(&[("a", "skipping")]))
        // One pull request closing two tickets: the same value for both,
        // its checks and comments read once.
        .issue(
            8,
            IssueW::ticket("One of two")
                .labels(&["needs-info", "held", "ready-for-agent"])
                .closed_by(&[80]),
        )
        .issue(9, IssueW::ticket("Two of two").closed_by(&[80]))
        .pr(
            80,
            PrW::open(&[8, 9], '8').checks(&[("a", "pass"), ("b", "skipping")]),
        )
        // 5: a draft is building, even with CI passed and no verdict.
        .issue(10, IssueW::ticket("A draft, CI passed").closed_by(&[100]))
        .pr(
            100,
            PrW {
                draft: true,
                ..PrW::open(&[10], 'a')
            },
        );
    let got = envelope(&world, "overlaps", "1");
    assert_eq!(
        states(&got),
        vec![
            (2, known("held")),
            (3, known("changes_requested")),
            (4, known("building")),
            (5, known("building")),
            (6, known("building")),
            (7, known("building")),
            (8, known("held")),
            (9, known("in_review")),
            (10, known("building")),
        ]
    );
    assert_eq!(
        got["data"]["needs_you"],
        json!({"known": [
            {"kind": "held", "spec": 1, "ticket": 2, "wording": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "link": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "asked_at": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "risk": {"unknown": "no explicit risk classification was reported"}},
            {"kind": "held", "spec": 1, "ticket": 8, "wording": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "link": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "asked_at": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "risk": {"unknown": "no explicit risk classification was reported"}},
            {"kind": "needs_info", "spec": 1, "ticket": 8, "wording": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "link": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "asked_at": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "risk": {"unknown": "no explicit risk classification was reported"}},
        ]})
    );
    let (eight, nine) = (&got["data"]["tickets"][6], &got["data"]["tickets"][7]);
    assert_eq!(
        (&eight["ci"], &eight["review"]),
        (&nine["ci"], &nine["review"])
    );
    let value = |t: &Value| read(&got, t["pr"].as_str().expect("pr"))["outcome"]["value"].clone();
    assert_eq!(value(eight), value(nine));
    assert_eq!(value(eight)["closes"], json!([8, 9]));
    let text = world.run("overlaps_text", &["1"]).stdout;
    for line in [
        "  pull request: #40 open; CI pending; verdict none",
        "  pull request: #50 open; CI failed; verdict none",
        "  pull request: #60 open; CI failed; verdict none",
        "  pull request: #70 open; CI none; verdict none",
        "  pull request: #80 open; CI passed; verdict none",
        "  pull request: #30 draft; CI passed; verdict CHANGES on its head",
    ] {
        assert!(
            text.lines().any(|l| l == line),
            "{line:?} is not in:\n{text}"
        );
    }
}

#[test]
fn a_read_that_hangs_times_out_and_the_rest_is_still_shown() {
    let world = small_world().answer(&checks_argv(20), json!({"hang": true}));
    let ran = world.run_within("checks_hang", &["1", "--json"], Duration::from_secs(8));
    let got = ran.json();
    conforms(&got);
    assert_eq!(read(&got, "r9")["outcome"]["gap"], "timed_out");
    assert_eq!(
        states(&got),
        vec![(2, unread(&["r9"])), (3, known("blocked"))]
    );
}

#[test]
fn a_truncated_list_is_partial_and_what_needs_it_is_unread() {
    let mut world = small_world();
    world.issues.get_mut(&1).expect("the spec").sub_total = Some(3);
    world.issues.get_mut(&3).expect("#3").blocked_total = Some(2);
    let got = envelope(&world, "truncated", "1");
    assert_eq!(
        read(&got, "r5")["outcome"],
        json!({"state": "partial", "gap": "truncated", "reason": "GitHub listed 2 of #1's 3 sub-issues", "value": [2, 3]})
    );
    assert_eq!(
        read(&got, "r12")["outcome"],
        json!({"state": "partial", "gap": "truncated", "reason": "GitHub listed 1 of #3's 2 blockers", "value": [2]})
    );
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, unread(&["r12"]))]
    );
    assert_eq!(got["data"]["fleet"]["progress"], unread(&["r5", "r12"]));
    assert_eq!(got["data"]["needs_you"], unread(&["r5"]));
    assert_eq!(got["data"]["blockers"][0]["fleet"], unread(&["r5"]));
    let text = world.run("truncated_text", &["1"]).stdout;
    assert!(
        text.lines().any(|l| l
            == "  blocked by: #2 not merged (version 0.9.1); and more, not read (GitHub listed \
                only these)"),
        "{text}"
    );
}

#[test]
fn unknown_states_carry_their_reasons() {
    let mut merged_twice = PrW::merged(&[6], '6', 'a');
    merged_twice.head = "room/syn-6b".to_owned();
    let world = World::default()
        .spec(1, &[2, 3, 4, 5, 6, 7, 8])
        .issue(
            2,
            IssueW::ticket("No ready label").labels(&["needs-triage"]),
        )
        .issue(
            3,
            IssueW::ticket("Ready for a human").labels(&["ready-for-human"]),
        )
        .issue(
            4,
            IssueW::ticket("Two open pull requests").closed_by(&[40, 41]),
        )
        .pr(40, PrW::open(&[4], '4'))
        .pr(41, PrW::open(&[4], '5'))
        .issue(
            5,
            IssueW::ticket("Closed unmerged pull request").closed_by(&[50]),
        )
        .pr(
            50,
            PrW {
                state: "CLOSED",
                ..PrW::open(&[5], '5')
            },
        )
        .issue(
            6,
            IssueW::ticket("Two merged pull requests").closed_by(&[60, 61]),
        )
        .pr(60, PrW::merged(&[6], '6', 'b'))
        .pr(61, merged_twice)
        .issue(
            7,
            IssueW::ticket("A merged and an open one").closed_by(&[70, 71]),
        )
        .pr(70, PrW::merged(&[7], '7', 'c'))
        .pr(71, PrW::open(&[7], '8'))
        .issue(8, {
            let mut issue = IssueW::ticket("Closed by another repository's pull request");
            issue.elsewhere = vec![("closedBy", 80)];
            issue
        });
    let got = envelope(&world, "unknown_reasons", "1");
    assert_eq!(
        states(&got),
        vec![
            (
                2,
                unknown("no pull request, and no ready label: not approved yet")
            ),
            (
                3,
                unknown("no pull request, every blocker merged, and ready for a human only")
            ),
            (
                4,
                unknown("several pull requests close it, so none is its own")
            ),
            (5, known("ready")),
            (
                6,
                unknown("several pull requests close it, so none is its own")
            ),
            (7, known("merged")),
            (8, known("ready")),
        ]
    );
    let pr = |ticket: usize| {
        let id = got["data"]["tickets"][ticket]["pr"]
            .as_str()
            .expect("pr")
            .to_owned();
        read(&got, &id)["outcome"]["value"].clone()
    };
    assert_eq!(pr(2), json!({"state": "several", "numbers": [40, 41]}));
    assert_eq!(
        pr(3),
        Value::Null,
        "a closed, unmerged pull request is never its"
    );
    assert_eq!(pr(4), json!({"state": "several", "numbers": [60, 61]}));
    let text = world.run("unknown_reasons_text", &["1"]);
    assert_eq!((text.code, text.stderr.as_str()), (0, ""));
    assert_eq!(
        text.stdout
            .lines()
            .filter(
                |line| *line == "  pull request: several pull requests (#60, #61): none is its own"
            )
            .count(),
        1,
        "two merged pull requests must not be described as open:\n{}",
        text.stdout
    );
    assert_eq!(pr(5)["number"], 70, "the merged one");
    assert_eq!(
        pr(6),
        Value::Null,
        "another repository's pull request is never its"
    );
    for t in [2, 4] {
        assert_eq!(
            got["data"]["tickets"][t]["ci"],
            Value::Null,
            "no checks for several"
        );
    }
}

#[test]
fn a_verdict_holds_only_for_its_commit_and_the_latest_wins() {
    let world = World::default()
        .spec(1, &[2, 3, 4])
        .issue(
            2,
            IssueW::ticket("Changes on an older commit").closed_by(&[20]),
        )
        .pr(20, PrW::open(&[2], '2').verdict("CHANGES", '9'))
        .issue(3, IssueW::ticket("Changes then approve").closed_by(&[30]))
        .pr(
            30,
            PrW::open(&[3], '3')
                .verdict("CHANGES", '3')
                .verdict("APPROVE", '3'),
        )
        .issue(4, IssueW::ticket("Approve then changes").closed_by(&[40]))
        .pr(
            40,
            PrW::open(&[4], '4')
                .verdict("APPROVE", '4')
                .verdict("CHANGES", '4'),
        );
    let got = envelope(&world, "verdicts", "1");
    assert_eq!(
        states(&got),
        vec![
            (2, known("in_review")),
            (3, known("in_review")),
            (4, known("changes_requested")),
        ]
    );
}

#[test]
fn an_item_of_another_repository_fails_its_list_never_reads_as_this_ones() {
    let mut world = small_world();
    world.issues.get_mut(&3).expect("#3").elsewhere = vec![("blockedBy", 2)];
    let got = envelope(&world, "blocker_elsewhere", "1");
    let outcome = &read(&got, "r12")["outcome"];
    assert_eq!(
        (&outcome["state"], &outcome["gap"]),
        (&json!("failed"), &json!("malformed"))
    );
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, unread(&["r12"]))]
    );

    let mut world = small_world();
    world.issues.get_mut(&1).expect("the spec").elsewhere = vec![("subIssues", 4)];
    let ran = world.run("sub_issue_elsewhere", &["1", "--json"]);
    assert_eq!((ran.code, ran.stdout.as_str()), (1, ""));
    assert_eq!(
        ran.stderr,
        "openwiz: fleet: #1's tickets couldn't be read (malformed): #1's sub-issues include an \
         issue of another repository; OpenWiz reads one repository\n"
    );
    let _ = OTHER_URL;
}

#[test]
fn the_gh_version_is_reported_never_a_gate() {
    let mut world = small_world();
    world.version_line = Some("gh version 2.101.0 (2026-10-15)".to_owned());
    let got = envelope(&world, "other_version", "1");
    assert_eq!(
        read(&got, "r1")["outcome"],
        json!({"state": "complete", "value": "2.101.0"})
    );
    assert_eq!(got["sources"]["github"]["version_tested"], false);
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, known("blocked"))]
    );

    world.version_line = Some("synthetic".to_owned());
    let got = envelope(&world, "no_version", "1");
    assert_eq!(read(&got, "r1")["outcome"]["gap"], "untested_version");
    assert_eq!(got["sources"]["github"]["version_tested"], false);
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, known("blocked"))]
    );

    let world = small_world().answer(&argv(&["--version"]), answer("", 1));
    let got = envelope(&world, "version_exit", "1");
    assert_eq!(
        read(&got, "r1")["outcome"],
        json!({"state": "failed", "gap": "untested_version", "reason": "gh --version couldn't be read: exited 1: no error output"})
    );
    assert_eq!(
        states(&got),
        vec![(2, known("in_review")), (3, known("blocked"))]
    );

    let got = envelope(&small_world(), "tested_version", "1");
    assert_eq!(got["sources"]["github"]["version_tested"], true);
}

#[test]
fn a_spec_that_cant_be_read_prints_nothing_and_exits_1() {
    let world = small_world().answer(&issue_argv(1), answer("", 1));
    let ran = world.run("spec_unreadable", &["1", "--json"]);
    assert_eq!((ran.code, ran.stdout.as_str()), (1, ""));
    assert_eq!(
        ran.stderr,
        "openwiz: fleet: #1's tickets couldn't be read (command_failed): #1 couldn't be read: \
         exited 1: no error output\n"
    );
}

#[test]
fn with_no_time_left_nothing_is_read() {
    let ran = small_world().run_within("no_budget", &["1", "--json"], Duration::ZERO);
    assert_eq!((ran.code, ran.stdout.as_str()), (1, ""));
    assert_eq!(
        ran.stderr,
        "openwiz: fleet: #1's tickets couldn't be read (budget_exhausted): #1 wasn't read: the \
         run's time ran out first\n"
    );
    assert_eq!(ran.calls, Vec::<Vec<String>>::new());
}

// ---------------------------------------------------------------------
// The command: its arguments, its text, and the program.
// ---------------------------------------------------------------------

#[test]
fn a_usage_error_reads_nothing() {
    for args in [
        &[][..],
        &["0"],
        &["01"],
        &["-1"],
        &["1.0"],
        &["#1"],
        &["12345678901"],
        &["1", "2"],
        &["1", "--json", "--json"],
        &["--help"],
        &["1", "-x"],
    ] {
        let ran = small_world().run("usage", args);
        assert_eq!((ran.code, ran.stdout.as_str()), (2, ""), "{args:?}");
        assert!(
            ran.stderr.starts_with("openwiz: fleet: "),
            "{args:?}: {}",
            ran.stderr
        );
        assert!(
            ran.stderr.ends_with(" (see openwiz --help)\n"),
            "{args:?}: {}",
            ran.stderr
        );
        assert_eq!(ran.calls, Vec::<Vec<String>>::new(), "{args:?}");
    }
}

#[test]
fn the_text_shows_the_same_facts() {
    let mut world = small_world();
    world.issues.get_mut(&3).expect("#3").labels =
        vec!["ready-for-agent".to_owned(), "needs-info".to_owned()];
    world.issues.get_mut(&2).expect("#2").title = "Synthetic \u{1b}[31mtwo\u{202e}".to_owned();
    let ran = world.run("text", &["1"]);
    assert_eq!((ran.code, ran.stderr.as_str()), (0, ""));
    let not_read = format!("budget_exhausted: {AGENTS_NOT_READ}");
    assert_eq!(
        ran.stdout,
        format!(
            "fleet #1: Synthetic spec
version: 0.9.1
progress: 0 of 2 merged; 0 ready, 0 building, 1 in review, 0 changes requested, 0 held, 1 blocked, 0 unknown
needs you: #3 needs info

#2  in review  Synthetic ?[31mtwo\u{fffd}
  pull request: #20 open; CI passed; verdict APPROVE on its head
  blocked by: none
  owned paths: `crates/example/src/synthetic-two.rs`
  relies on: nothing

#3  blocked  Synthetic three
  pull request: none
  blocked by: #2 not merged (this fleet)
  owned paths: `crates/example/src/synthetic-three.rs`
  relies on: nothing

agents: unknown (not read: r14, r15)
gh 2.100.0 (tested, live-tested 2.100.0)
partial: 3 reads incomplete
  r2 {not_read}
  r14 {not_read}
  r15 {not_read}
"
        )
    );
}

#[test]
fn the_text_names_a_blockers_version_and_what_wasnt_read() {
    let got = example_world().run("example_text", &["901"]);
    assert_eq!((got.code, got.stderr.as_str()), (0, ""));
    let lines: Vec<&str> = got.stdout.lines().collect();
    for line in [
        "fleet #901: Synthetic spec one",
        "progress: 1 of 9 merged; 1 ready, 2 building, 1 in review, 1 changes requested, 1 held, 1 blocked, 1 unknown",
        "needs you: #904 needs info, #907 held",
        "#902  merged  Synthetic ticket A1",
        "  pull request: #951 merged on GitHub; merge read back on main",
        "  blocked by: #811 merged (version 0.9.0), #812 merged (version none), #903 not merged (this fleet)",
        "#909  unknown (closed on GitHub, and no merge was read back)  Synthetic ticket A8",
        "  pull request: #955 open; CI failed; verdict CHANGES on an older commit",
        "  pull request: #954 draft; CI none; verdict none",
    ] {
        assert!(lines.contains(&line), "{line:?} is not in:\n{}", got.stdout);
    }
}

#[test]
fn the_text_never_says_none_for_a_line_it_couldnt_read() {
    let mut world = small_world();
    world.issues.get_mut(&3).expect("#3").body =
        "**Owned paths:** `a.rs`\n**Owned paths:** `b.rs`\nSynthetic, no relies-on line."
            .to_owned();
    let got = envelope(&world, "two_owned_lines", "1");
    let issue = read(&got, "r11");
    assert_eq!(
        (
            &issue["outcome"]["value"]["owned_paths"],
            &issue["outcome"]["value"]["relies_on"]
        ),
        (&Value::Null, &Value::Null)
    );
    let text = world.run("two_owned_lines_text", &["1"]).stdout;
    for line in [
        "  owned paths: unknown (not exactly one such line in its body)",
        "  relies on: unknown (not exactly one such line in its body)",
    ] {
        assert!(
            text.lines().any(|l| l == line),
            "{line:?} is not in:\n{text}"
        );
    }
}

#[test]
fn its_help_says_what_it_reads_and_how_it_exits() {
    use openwiz_cli::fleet;
    assert_eq!(fleet::USAGE, "  openwiz fleet <spec> [--json]\n");
    assert!(fleet::HELP.starts_with("fleet <spec>\n"));
    for words in [
        "gh",
        "merge commit was read back",
        "CloudRoom projects, threads and Cloud workspaces",
    ] {
        assert!(fleet::HELP.contains(words), "{words:?}");
    }
    assert_eq!(
        fleet::EXIT_CODES,
        "  0  fleet: the fleet was printed, complete or partial\n  1  fleet: the spec or its \
         ticket list couldn't be read; nothing was printed\n"
    );
}

/// #373: a real-gh-shaped empty result is complete, including with APPROVE.
#[test]
fn no_checks_reported_keeps_the_ticket_building_and_fleet_progress_known() {
    let world = small_world().answer(
        &checks_argv(20),
        json!({"exit": 1,
        "stderr": "no checks reported on the 'room/syn-2' branch\n"}),
    );
    let (dir, path) = fakes_on_path("a5-no-checks-reported");
    let scenario = dir.join("scenario.json");
    std::fs::write(&scenario, world.scenario().to_string()).unwrap();
    std::fs::write(dir.join("fake-gh.scenario"), scenario.to_str().unwrap()).unwrap();
    let out = Command::new(openwiz_release())
        .args(["fleet", "1", "--json"])
        .env("PATH", &path)
        .env("OPENWIZ_FIXTURE_PROGRAM", dir.join("room-cli"))
        .current_dir(&dir)
        .output()
        .unwrap();
    assert_eq!(
        (out.status.code(), out.stderr.as_slice()),
        (Some(0), &b""[..])
    );
    let got: Value = serde_json::from_slice(&out.stdout).unwrap();
    conforms(&got);
    let text = world.run("no_checks_reported_text", &["1"]);
    assert_eq!((text.code, text.stderr.as_str()), (0, ""));
    assert_eq!(
        text.stdout
            .lines()
            .filter(|l| *l == "  pull request: #20 open; CI none; verdict APPROVE on its head")
            .count(),
        1
    );
    assert_eq!(got["data"]["tickets"][0]["ci"], "r9");
    assert_eq!(
        read(&got, "r9")["outcome"],
        json!({"state": "complete", "value": []})
    );
    assert_eq!(
        states(&got),
        vec![(2, known("building")), (3, known("blocked"))]
    );
    assert_eq!(
        got["data"]["fleet"]["progress"],
        json!({"known": {
            "tickets": 2, "merged": 0, "ready": 0, "building": 1,
            "in_review": 0, "changes_requested": 0, "held": 0, "blocked": 1, "unknown": 0
        }})
    );
}

#[test]
fn no_checks_near_misses_leave_ticket_and_progress_unread() {
    for (i, response) in crate::a4_fleets::no_checks::failures()
        .into_iter()
        .enumerate()
    {
        let world = small_world().answer(&checks_argv(20), response);
        let ran = world.run(&format!("no_checks_near_miss_{i}"), &["1", "--json"]);
        let got = ran.json();
        conforms(&got);
        let checks = read(&got, "r9");
        assert_eq!(checks["outcome"]["state"], "failed", "case {i}");
        assert_eq!(checks["outcome"]["gap"], "command_failed", "case {i}");
        assert_eq!(
            states(&got),
            vec![(2, unread(&["r9"])), (3, known("blocked"))]
        );
        assert_eq!(got["data"]["fleet"]["progress"], unread(&["r9"]));
        let reason = checks["outcome"]["reason"].as_str().unwrap();
        assert!(
            reason.ends_with("gh error (detail withheld)")
                || reason.ends_with("gh error: HTTP 403 (detail withheld)")
                || reason.ends_with("no error output"),
            "{reason}"
        );
        assert_eq!(
            ran.calls.iter().filter(|a| **a == checks_argv(20)).count(),
            1
        );
    }
}
