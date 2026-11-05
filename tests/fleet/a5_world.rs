//! A5's test world (ClosedWiz#113): a synthetic GitHub, written as a fake
//! `gh` scenario, and `openwiz fleet` run against it.
//!
//! A [`World`] holds issues and pull requests; [`World::scenario`] writes
//! the answer to every call `openwiz fleet` may make, in `gh`'s own shapes
//! (A1's spike, #109),
//! so a test changes only the facts it is about. [`World::answer`] replaces
//! one call's answer, to make it fail or misbehave.
//!
//! The scenarios are written here, into the test's own directory, not kept
//! under `tests/fixtures/github/`: a verdict comment (`VERDICT: APPROVE at
//! <commit>`) is a value the fixture scan doesn't accept. Every value is
//! synthetic.

#![allow(dead_code)]

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use openwiz_adapter_github::tickets::{
    CHECK_FIELDS, COMPARE_JQ, ISSUE_FIELDS, PR_FIELDS, Tickets, VERDICTS_JQ,
};
use openwiz_core::fleet::model::{
    NonEmpty, Number, Outcome, Project, Read, ReadKind, Thread, Unplaced, UnplacedReason, WorkedOut,
};
use openwiz_core::fleet::tickets::{AgentReads, Agents, NotRead, Placed, RepositoryAnswer};
use openwiz_core::model::Timestamp;
use openwiz_core::ops::Clock;
use serde_json::{Value, json};

use crate::support::FakeGh;

/// The repository's synthetic address; its items are under it.
pub const REPO_URL: &str = "https://example.invalid/synthetic/repo";
/// Another repository's.
pub const OTHER_URL: &str = "https://example.invalid/synthetic/other";
/// The repository as `gh repo view` names it: owner and name.
pub const NAME_WITH_OWNER: &str = "synthetic-owner/example-repo";

/// When every test run starts: the contract examples' snapshot.
pub const SNAPSHOT_AT: i64 = 1_793_437_200_000;

/// A fixed wall clock; real monotonic time, for the budget.
pub struct FixedClock;

impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(SNAPSHOT_AT)
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

/// One synthetic issue.
#[derive(Clone, Debug)]
pub struct IssueW {
    pub title: String,
    pub closed: bool,
    pub milestone: Option<(u64, String)>,
    pub labels: Vec<String>,
    pub body: String,
    pub sub_issues: Vec<u64>,
    /// GitHub's own total, when it differs from the nodes listed.
    pub sub_total: Option<u64>,
    pub blocked_by: Vec<u64>,
    pub blocked_total: Option<u64>,
    /// Pull requests that close it, by number, in this repository.
    pub closed_by: Vec<u64>,
    /// Nodes or references in another repository: `(field, number)`, with
    /// field `subIssues`, `blockedBy` or `closedBy`.
    pub elsewhere: Vec<(&'static str, u64)>,
}

impl IssueW {
    /// An open ticket, ready for an agent, with the template lines.
    pub fn ticket(title: &str) -> Self {
        Self {
            title: title.to_owned(),
            closed: false,
            milestone: Some((7, "0.9.1".to_owned())),
            labels: vec!["ready-for-agent".to_owned()],
            body: format!(
                "Synthetic body.\n**Owned paths:** `crates/example/src/{}.rs`\n**Relies on:** nothing\n",
                title.to_lowercase().replace(' ', "-")
            ),
            sub_issues: vec![],
            sub_total: None,
            blocked_by: vec![],
            blocked_total: None,
            closed_by: vec![],
            elsewhere: vec![],
        }
    }

    pub fn labels(mut self, labels: &[&str]) -> Self {
        self.labels = labels.iter().map(|l| (*l).to_owned()).collect();
        self
    }

    pub fn closed(mut self) -> Self {
        self.closed = true;
        self
    }

    pub fn blocked_by(mut self, blockers: &[u64]) -> Self {
        self.blocked_by = blockers.to_vec();
        self
    }

    pub fn closed_by(mut self, prs: &[u64]) -> Self {
        self.closed_by = prs.to_vec();
        self
    }
}

/// One synthetic pull request.
#[derive(Clone, Debug)]
pub struct PrW {
    /// `OPEN`, `CLOSED` or `MERGED`.
    pub state: &'static str,
    pub draft: bool,
    pub head: String,
    pub head_oid: String,
    pub base: String,
    pub closes: Vec<u64>,
    /// Issues of another repository it closes too.
    pub closes_elsewhere: Vec<u64>,
    pub merge_oid: Option<String>,
    pub merged_at: Option<String>,
    /// `gh pr checks`' rows: name and bucket.
    pub checks: Vec<(String, String)>,
    /// The comment bodies that start `VERDICT: `, oldest first.
    pub verdicts: Vec<String>,
    /// The compare's `ahead_by`: 0 when the merge is on the base.
    pub ahead_by: u64,
}

/// A commit as the contract's examples write one: one hex digit, 40 times.
pub fn oid(digit: char) -> String {
    std::iter::repeat_n(digit, 40).collect()
}

impl PrW {
    /// An open, ready pull request with passing checks and no verdict,
    /// closing `closes`.
    pub fn open(closes: &[u64], digit: char) -> Self {
        Self {
            state: "OPEN",
            draft: false,
            head: format!("room/syn-{}", closes.first().copied().unwrap_or(0)),
            head_oid: oid(digit),
            base: "main".to_owned(),
            closes: closes.to_vec(),
            closes_elsewhere: vec![],
            merge_oid: None,
            merged_at: None,
            checks: vec![
                ("build".to_owned(), "pass".to_owned()),
                ("test".to_owned(), "pass".to_owned()),
            ],
            verdicts: vec![],
            ahead_by: 0,
        }
    }

    /// A merged pull request whose merge is on the base.
    pub fn merged(closes: &[u64], digit: char, merge_digit: char) -> Self {
        Self {
            state: "MERGED",
            merge_oid: Some(oid(merge_digit)),
            merged_at: Some("2026-10-30T18:30:00Z".to_owned()),
            ..Self::open(closes, digit)
        }
    }

    pub fn verdict(mut self, word: &str, digit: char) -> Self {
        self.verdicts.push(format!(
            "VERDICT: {word} at {}\n\nSynthetic report.",
            oid(digit)
        ));
        self
    }

    pub fn checks(mut self, rows: &[(&str, &str)]) -> Self {
        self.checks = rows
            .iter()
            .map(|(n, b)| ((*n).to_owned(), (*b).to_owned()))
            .collect();
        self
    }
}

/// A synthetic GitHub.
#[derive(Clone, Default)]
pub struct World {
    pub issues: BTreeMap<u64, IssueW>,
    pub prs: BTreeMap<u64, PrW>,
    /// Answers that replace the world's, by argv.
    pub answers: BTreeMap<Vec<String>, Value>,
    /// `gh --version`'s first line, when not the tested one.
    pub version_line: Option<String>,
    /// The CloudRoom side, when not A5's [`NotRead`].
    pub agents: Option<std::sync::Arc<dyn Agents>>,
}

/// One fake answer: stdout and exit code.
pub fn answer(stdout: &str, exit: u8) -> Value {
    json!({"stdout": stdout, "exit": exit})
}

impl World {
    pub fn issue(mut self, number: u64, issue: IssueW) -> Self {
        self.issues.insert(number, issue);
        self
    }

    pub fn pr(mut self, number: u64, pr: PrW) -> Self {
        self.prs.insert(number, pr);
        self
    }

    /// A spec with these tickets.
    pub fn spec(self, number: u64, tickets: &[u64]) -> Self {
        let mut spec = IssueW::ticket("Synthetic spec");
        spec.labels = vec![];
        spec.body = "Synthetic spec body.".to_owned();
        spec.sub_issues = tickets.to_vec();
        self.issue(number, spec)
    }

    /// Replaces the answer to `argv`.
    pub fn answer(mut self, argv: &[String], response: Value) -> Self {
        self.answers.insert(argv.to_vec(), response);
        self
    }

    /// Every call's answer, as a fake gh scenario.
    pub fn scenario(&self) -> Value {
        let mut responses: BTreeMap<Vec<String>, Value> = BTreeMap::new();
        let version = self
            .version_line
            .clone()
            .unwrap_or_else(|| "gh version 2.100.0 (2026-09-03)".to_owned());
        responses.insert(
            argv(&["--version"]),
            json!({"stdout": format!("{version}\nhttps://example.invalid/synthetic/release\n")}),
        );
        responses.insert(
            argv(&["repo", "view", "--json", "nameWithOwner,url"]),
            json!({"stdout": json!({"nameWithOwner": NAME_WITH_OWNER, "url": REPO_URL}).to_string()}),
        );
        for (&n, issue) in &self.issues {
            responses.insert(
                issue_argv(n),
                json!({"stdout": issue_json(n, issue).to_string()}),
            );
        }
        for (&n, pr) in &self.prs {
            responses.insert(pr_argv(n), json!({"stdout": pr_json(n, pr).to_string()}));
            let checks: Vec<Value> = pr
                .checks
                .iter()
                .map(|(name, bucket)| json!({"bucket": bucket, "name": name}))
                .collect();
            responses.insert(
                checks_argv(n),
                json!({"stdout": Value::from(checks).to_string()}),
            );
            responses.insert(
                comments_argv(n),
                json!({"stdout": json!(pr.verdicts).to_string()}),
            );
            if let Some(merge) = &pr.merge_oid {
                responses.insert(
                    compare_argv(&pr.base, merge),
                    json!({"stdout": json!({"ahead_by": pr.ahead_by}).to_string()}),
                );
            }
        }
        for (argv, response) in &self.answers {
            responses.insert(argv.clone(), response.clone());
        }
        let responses: Vec<Value> = responses
            .into_iter()
            .map(|(argv, mut response)| {
                response["argv"] = json!(argv);
                response
            })
            .collect();
        json!({
            "scenario": "a5-world",
            "description": "Synthetic GitHub for openwiz fleet (A5, #113)",
            "synthetic_assumptions": [
                "repo view --json nameWithOwner,url, closedByPullRequestsReferences, the verdict bodies' --jq and the compare's direction are not A1's forms; the builder observed their structure live on #113's PR"
            ],
            "responses": responses,
        })
    }

    /// Runs `openwiz fleet <args>` in-process on this world: (exit code,
    /// stdout, stderr, the calls gh received).
    pub fn run(&self, test: &str, args: &[&str]) -> Ran {
        self.run_within(test, args, Duration::from_secs(30))
    }

    pub fn run_within(&self, test: &str, args: &[&str], budget: Duration) -> Ran {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .join("a5-world")
            .join(test);
        let _ = fs::remove_dir_all(&dir);
        DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .expect("the scenario's directory");
        let scenario = dir.join("scenario.json");
        fs::write(&scenario, self.scenario().to_string()).expect("write the scenario");
        let fake = FakeGh::new(&format!("a5-{test}"), &scenario);
        let args: Vec<OsString> = args.iter().map(OsString::from).collect();
        let (mut out, mut err) = (Vec::new(), Vec::new());
        let agents: &dyn Agents = match &self.agents {
            Some(agents) => agents.as_ref(),
            None => &NotRead,
        };
        let code = openwiz_cli::fleet::run_with(
            &Tickets::new(fake.program()),
            agents,
            &FixedClock,
            budget,
            &args,
            &mut out,
            &mut err,
        );
        // Every envelope printed is kept beside the fake's log, so the
        // contract's own check (A2's check.py) can judge it too.
        if code == 0 && out.starts_with(b"{") {
            fs::write(fake.dir.join("envelope.json"), &out).expect("keep the envelope");
        }
        Ran {
            code,
            stdout: String::from_utf8(out).expect("UTF-8 stdout"),
            stderr: String::from_utf8(err).expect("UTF-8 stderr"),
            calls: fake.invocations(),
            dir: fake.dir,
        }
    }
}

/// What a run gave.
pub struct Ran {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
    pub calls: Vec<Vec<String>>,
    pub dir: PathBuf,
}

impl Ran {
    /// stdout as JSON, after checking the run printed one envelope.
    pub fn json(&self) -> Value {
        assert_eq!(
            (self.code, self.stderr.as_str()),
            (0, ""),
            "the run failed:\n{}",
            self.stdout
        );
        serde_json::from_str(&self.stdout).expect("stdout is JSON")
    }
}

pub fn argv(words: &[&str]) -> Vec<String> {
    words.iter().map(|w| (*w).to_owned()).collect()
}

pub fn issue_argv(n: u64) -> Vec<String> {
    argv(&["issue", "view", &n.to_string(), "--json", ISSUE_FIELDS])
}

pub fn pr_argv(n: u64) -> Vec<String> {
    argv(&["pr", "view", &n.to_string(), "--json", PR_FIELDS])
}

pub fn checks_argv(n: u64) -> Vec<String> {
    argv(&["pr", "checks", &n.to_string(), "--json", CHECK_FIELDS])
}

pub fn comments_argv(n: u64) -> Vec<String> {
    argv(&[
        "pr",
        "view",
        &n.to_string(),
        "--json",
        "comments",
        "--jq",
        VERDICTS_JQ,
    ])
}

pub fn compare_argv(base: &str, merge: &str) -> Vec<String> {
    let path = format!("repos/{{owner}}/{{repo}}/compare/{base}...{merge}");
    argv(&["api", &path, "--jq", COMPARE_JQ])
}

/// A relationship node, as `gh issue view` gives one.
fn node(n: u64, url: &str) -> Value {
    json!({
        "id": format!("synthetic-node-{n}"),
        "number": n,
        "state": "OPEN",
        "title": "Synthetic node",
        "url": format!("{url}/issues/{n}"),
    })
}

fn relation(numbers: &[u64], total: Option<u64>, elsewhere: &[u64]) -> Value {
    let mut nodes: Vec<Value> = numbers.iter().map(|&n| node(n, REPO_URL)).collect();
    nodes.extend(elsewhere.iter().map(|&n| node(n, OTHER_URL)));
    let listed = nodes.len() as u64;
    json!({"nodes": nodes, "totalCount": total.unwrap_or(listed)})
}

/// A closing reference to a pull request or issue.
fn reference(n: u64, url: &str, kind: &str) -> Value {
    json!({
        "id": format!("synthetic-ref-{n}"),
        "number": n,
        "repository": {"id": "synthetic-repo", "name": "synthetic", "owner": {"id": "synthetic-owner", "login": "synthetic-owner"}},
        "url": format!("{url}/{kind}/{n}"),
    })
}

/// `gh issue view N --json` ISSUE_FIELDS, in gh's shape.
pub fn issue_json(_n: u64, issue: &IssueW) -> Value {
    let elsewhere = |field: &str| -> Vec<u64> {
        issue
            .elsewhere
            .iter()
            .filter(|(f, _)| *f == field)
            .map(|(_, n)| *n)
            .collect()
    };
    let mut closed_by: Vec<Value> = issue
        .closed_by
        .iter()
        .map(|&n| reference(n, REPO_URL, "pull"))
        .collect();
    closed_by.extend(
        elsewhere("closedBy")
            .iter()
            .map(|&n| reference(n, OTHER_URL, "pull")),
    );
    json!({
        "blockedBy": relation(&issue.blocked_by, issue.blocked_total, &elsewhere("blockedBy")),
        "body": issue.body,
        "closedByPullRequestsReferences": closed_by,
        "comments": [],
        "labels": issue.labels.iter().map(|name| json!({
            "color": "ededed",
            "description": "Synthetic label",
            "id": "synthetic-label",
            "name": name,
        })).collect::<Vec<_>>(),
        "milestone": issue.milestone.as_ref().map(|(number, title)| json!({
            "description": "Synthetic milestone",
            "dueOn": null,
            "number": number,
            "title": title,
        })),
        "state": if issue.closed { "CLOSED" } else { "OPEN" },
        "subIssues": relation(&issue.sub_issues, issue.sub_total, &elsewhere("subIssues")),
        "title": issue.title,
    })
}

/// `gh pr view N --json` PR_FIELDS, in gh's shape.
pub fn pr_json(n: u64, pr: &PrW) -> Value {
    let mut closes: Vec<Value> = pr
        .closes
        .iter()
        .map(|&i| reference(i, REPO_URL, "issues"))
        .collect();
    closes.extend(
        pr.closes_elsewhere
            .iter()
            .map(|&i| reference(i, OTHER_URL, "issues")),
    );
    json!({
        "baseRefName": pr.base,
        "closingIssuesReferences": closes,
        "headRefName": pr.head,
        "headRefOid": pr.head_oid,
        "isDraft": pr.draft,
        "mergeCommit": pr.merge_oid.as_ref().map(|oid| json!({"oid": oid})),
        "mergedAt": pr.merged_at,
        "number": n,
        "state": pr.state,
    })
}

fn text(value: &str) -> NonEmpty {
    NonEmpty::new(value).expect("not empty")
}

/// The CloudRoom side of the contract's example 2 (`fleet 901`), as A6's
/// reads and chain would give it: its reads, and the builders and unplaced
/// threads the example prints. It checks it was asked for this repository,
/// and that `place` was given the records, in the contract's order.
pub struct ExampleAgents;

impl Agents for ExampleAgents {
    fn read(&self, repository: Option<&RepositoryAnswer>, _deadline: Instant) -> AgentReads {
        let repository = repository.expect("the repository was read");
        assert_eq!(repository.name_with_owner.as_str(), NAME_WITH_OWNER);
        let cloud = |n: u32| Thread::Cloud {
            thread: text(&format!("thr_syn_{n:04}")),
            project: text("prj_syn_0001"),
        };
        let mut threads: Vec<Thread> = (2..=8).map(cloud).collect();
        threads.push(Thread::Local {
            thread: text("thr_syn_0009"),
            project: text("prj_syn_0001"),
            branch: Some(text("room/syn-local-0009")),
        });
        let branches = [
            "room/syn-a1-0001",
            "room/syn-a2-0002",
            "room/syn-a3-0003",
            "room/syn-a4-0004",
            "room/syn-a9-0006",
            "room/syn-x-0007",
            "room/syn-x-0008",
        ];
        AgentReads {
            version: Outcome::Complete {
                value: text("v132"),
            },
            projects: openwiz_core::fleet::model::ListOutcome::Complete {
                value: vec![Project {
                    id: text("prj_syn_0001"),
                    name: "Synthetic project".to_owned(),
                }],
            },
            threads: openwiz_core::fleet::model::ListOutcome::Complete { value: threads },
            workspaces: branches
                .iter()
                .enumerate()
                .map(|(i, branch)| {
                    let n = u32::try_from(i).expect("small") + 2;
                    (
                        text(&format!("thr_syn_{n:04}")),
                        Outcome::Complete {
                            value: text(branch),
                        },
                    )
                })
                .collect(),
        }
    }

    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed {
        assert_eq!(spec.get(), 901);
        let kinds: Vec<&str> = reads
            .iter()
            .map(|r| match r.kind {
                ReadKind::Projects { .. } => "projects",
                ReadKind::Threads { .. } => "threads",
                ReadKind::Workspace { .. } => "workspace",
                _ => "github",
            })
            .collect();
        assert_eq!(
            kinds[47..],
            [
                "projects",
                "threads",
                "workspace",
                "workspace",
                "workspace",
                "workspace",
                "workspace",
                "workspace",
                "workspace"
            ]
        );
        let builder = |ticket: u64| match ticket {
            902 => Some("thr_syn_0002"),
            903 => Some("thr_syn_0003"),
            904 => Some("thr_syn_0004"),
            905 => Some("thr_syn_0005"),
            910 => Some("thr_syn_0006"),
            _ => None,
        };
        Placed {
            builders: tickets
                .iter()
                .map(|t| WorkedOut::Known(builder(t.get()).map(text)))
                .collect(),
            unplaced: WorkedOut::Known(
                [7, 8, 9]
                    .map(|n| Unplaced {
                        thread: text(&format!("thr_syn_{n:04}")),
                        reason: UnplacedReason::NoPullRequest,
                    })
                    .to_vec(),
            ),
        }
    }
}
