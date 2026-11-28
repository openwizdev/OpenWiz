use std::collections::BTreeMap;
use std::hint::black_box;
use std::time::{Duration, Instant};

use openwiz_core::fleet::fleets::{FleetsSource, IssueRow, Link, Links, Listed, PrFacts, PrRow};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Failed, Issue, IssueState, MergedPr, NonEmpty, Number, PrFields,
    Repository,
};
use openwiz_core::fleet::tick::*;
use openwiz_core::model::Timestamp;
use openwiz_core::models::SpawnFlags;
use openwiz_core::ops::Clock;

const PER_SPEC: u64 = 100;
const NOW: u64 = 2_000_000;
const RULES: &str = "## Builder
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-builder` |
| Effort | Synthetic | `--reasoning-level high` |
## Reviewer for GPT-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider claude-code` |
| Model | Synthetic | `--model syn-reviewer` |
| Effort | Synthetic | `--reasoning-level high` |
## Builder for small tickets
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-small` |
| Effort | Synthetic | `--reasoning-level high` |
## Reviewer for Claude-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-gpt-reviewer` |
| Effort | Synthetic | `--reasoning-level high` |
## CI checks
| Check | Runs | Required on |
| --- | --- | --- |
| `web-build` | Synthetic | `main`, `release-*` |
| `rust` | Synthetic | `main`, `release-*` |
| `web-test` | Synthetic | `main`, `release-*` |
## Standing merge rules
| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph | Synthetic | The loop, as soon as the reviewer's APPROVE names that exact commit and all checks pass |
";

fn median_ns(mut call: impl FnMut()) -> u128 {
    let mut iters = 1u32;
    loop {
        let start = Instant::now();
        for _ in 0..iters {
            call();
        }
        if start.elapsed() >= Duration::from_millis(30) || iters >= 50_000 {
            let mut samples = Vec::with_capacity(11);
            for _ in 0..11 {
                let start = Instant::now();
                for _ in 0..iters {
                    call();
                }
                samples.push(start.elapsed().as_nanos() / u128::from(iters));
            }
            samples.sort_unstable();
            return samples[5];
        }
        iters = iters.saturating_mul(2);
    }
}

fn report(name: &str, bytes: usize, ns: u128) {
    println!(
        "BENCH {name} out_bytes={bytes} median_ns={ns} out_fnv1a={:016x}",
        OUT.with(|o| *o.borrow())
    );
}

thread_local! {
    static OUT: std::cell::RefCell<u64> = const { std::cell::RefCell::new(0) };
}

fn fingerprint(bytes: &[u8]) -> usize {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h = (h ^ u64::from(*b)).wrapping_mul(0x0000_0100_0000_01b3);
    }
    OUT.with(|o| *o.borrow_mut() = h);
    bytes.len()
}

fn n(x: u64) -> Number {
    Number::new(x).expect("positive")
}
fn text(s: impl Into<String>) -> NonEmpty {
    NonEmpty::new(s).expect("not empty")
}
fn commit(seed: u64) -> Commit {
    Commit::parse(&format!("{seed:040x}")).expect("forty hex digits")
}
fn link(number: u64) -> Link {
    Link {
        number: n(number),
        id: text(format!("I_syn{number}")),
    }
}

struct Synthetic {
    issues: Vec<IssueRow>,
    prs: Vec<PrRow>,
}

impl Synthetic {
    fn new(specs: u64) -> Self {
        let mut issues = Vec::new();
        let mut prs = Vec::new();
        for s in 0..specs {
            let spec = s + 1;
            let first = specs + 1 + s * PER_SPEC;
            let tickets: Vec<u64> = (first..first + PER_SPEC).collect();
            issues.push(IssueRow {
                number: n(spec),
                id: text(format!("I_syn{spec}")),
                title: format!("Synthetic spec {spec}"),
                state: IssueState::Open,
                milestone: None,
                labels: vec![],
                body: String::new(),
                sub_issues: Links {
                    nodes: tickets.iter().map(|t| link(*t)).collect(),
                    total: PER_SPEC,
                },
                blocked_by: Links {
                    nodes: vec![],
                    total: 0,
                },
            });
            for (i, &t) in tickets.iter().enumerate() {
                let blocked = i % 2 == 1;
                let closed = i % 3 == 1;
                issues.push(IssueRow {
                    number: n(t),
                    id: text(format!("I_syn{t}")),
                    title: format!("Synthetic ticket {t}"),
                    state: if closed {
                        IssueState::Closed
                    } else {
                        IssueState::Open
                    },
                    milestone: None,
                    labels: if i % 4 == 0 {
                        vec![text("ready-for-agent")]
                    } else {
                        vec![]
                    },
                    body: "## Owned paths\n\n- `crates/core/`\n".into(),
                    sub_issues: Links {
                        nodes: vec![],
                        total: 0,
                    },
                    blocked_by: Links {
                        nodes: if blocked { vec![link(t - 1)] } else { vec![] },
                        total: u64::from(blocked),
                    },
                });
                let facts = PrFacts {
                    number: n(1_000_000 + t),
                    draft: false,
                    head_branch: text(format!("syn-{t}")),
                    head_commit: commit(t),
                    base_branch: text("main"),
                    closes: vec![link(t)],
                };
                match i % 3 {
                    0 => prs.push(PrRow::Open(facts)),
                    1 => prs.push(PrRow::Merged {
                        facts,
                        merge_commit: commit(t + 7),
                        merged_at: Timestamp(1_000),
                    }),
                    _ => prs.push(PrRow::Closed {
                        number: n(1_000_000 + t),
                    }),
                }
            }
        }
        Self { issues, prs }
    }
}

impl FleetsSource for Synthetic {
    fn tested_version(&self) -> &str {
        "gh version 2.83.1"
    }
    fn version(&self, _: Instant) -> Result<NonEmpty, Failed> {
        Ok(text("gh version 2.83.1"))
    }
    fn repository(&self, _: Instant) -> Result<Repository, Failed> {
        Ok(Repository {
            name: text("synthetic/example"),
        })
    }
    fn issues(&self, _: Instant) -> Result<Listed<IssueRow>, Failed> {
        Ok(Listed {
            rows: self.issues.clone(),
            cut_short: false,
        })
    }
    fn pull_requests(&self, _: Instant) -> Result<Listed<PrRow>, Failed> {
        Ok(Listed {
            rows: self.prs.clone(),
            cut_short: false,
        })
    }
    fn checks(&self, _: Number, _: Instant) -> Result<Vec<Check>, Failed> {
        Ok(["rust", "web-build"]
            .into_iter()
            .map(|name| Check {
                name: text(name),
                result: CheckResult::Pass,
            })
            .collect())
    }
    fn comments(&self, pr: Number, _: Instant) -> Result<Vec<String>, Failed> {
        Ok(vec![format!(
            "VERDICT: APPROVE at {}",
            commit(pr.get() - 1_000_000).as_str()
        )])
    }
    fn on_base(&self, _: &MergedPr, _: Instant) -> Result<bool, Failed> {
        Ok(true)
    }
}

struct Fixed(Instant);
impl Clock for Fixed {
    fn now(&self) -> Timestamp {
        Timestamp(1_800_000_000_000)
    }
    fn monotonic(&self) -> Instant {
        self.0
    }
}

fn issue(title: String, closed: bool, labels: Vec<NonEmpty>) -> Issue {
    Issue {
        title,
        state: if closed {
            IssueState::Closed
        } else {
            IssueState::Open
        },
        milestone: None,
        labels,
        owned_paths: None,
        relies_on: None,
        pending_question: None,
    }
}

fn fields(t: u64) -> PrFields {
    PrFields {
        number: n(1_000_000 + t),
        draft: false,
        head_branch: text(format!("syn-{t}")),
        head_commit: commit(t),
        base_branch: text("main"),
        closes: vec![n(t)],
    }
}

fn merged(t: u64) -> MergeInput {
    MergeInput {
        pr: MergedPr {
            fields: fields(t),
            merge_commit: commit(t + 7),
            merged_at: Timestamp(10),
        },
        read_back: true,
    }
}

fn ticket(t: u64, i: u64) -> TicketFacts {
    let mut facts = TicketFacts {
        issue: issue(
            format!("Synthetic ticket {t}"),
            i % 4 == 2,
            vec![text("ready-for-agent")],
        ),
        blockers: vec![],
        pr: None,
        builder: None,
        builder_source: None,
        reviewers: vec![],
        starts: vec![],
        relies_on: vec![text("kernel/driver.v1.md"), text("crates/core/src/*.rs")],
        holds: vec![],
        held_label_comment: None,
        question: None,
        records: TicketRecords::default(),
    };
    match i % 4 {
        0 => {}
        1 => {
            facts.builder = Some(Agent {
                thread: text(format!("syn-builder-{t}")),
                archived: false,
            });
            facts.pr = Some(PrInput::Open(Box::new(OpenPr {
                fields: fields(t),
                subject: format!("Synthetic {t}"),
                ci: Some(CheckRun {
                    head_commit: commit(t),
                    base_commit: commit(1),
                    checks: ["web-build", "rust", "web-test"]
                        .into_iter()
                        .map(|s| Check {
                            name: text(s),
                            result: CheckResult::Pass,
                        })
                        .collect(),
                }),
                base_now: Some(commit(1)),
                reports: vec![ReportComment {
                    comment: n(9_000_000 + t),
                    text: format!("VERDICT: APPROVE at {}", commit(t).as_str()),
                }],
                starts: vec![],
                records: PrRecords::default(),
            })));
        }
        2 => facts.pr = Some(PrInput::Merged(merged(t))),
        _ => {
            facts.blockers = vec![BlockerInput {
                number: n(t - 1),
                state: IssueState::Open,
                merged: None,
            }];
        }
    }
    facts
}

fn snapshot(specs: u64) -> Snapshot {
    let mut fleets = Vec::new();
    for s in 0..specs {
        let spec = s + 1;
        let first = specs + 1 + s * PER_SPEC;
        let tickets: Vec<TicketInput> = (0..PER_SPEC)
            .map(|i| TicketInput {
                number: n(first + i),
                facts: Observed::Complete(ticket(first + i, i)),
            })
            .collect();
        let changes = (0..5)
            .map(|c| ContractChange {
                merged: MergeInput {
                    pr: MergedPr {
                        fields: PrFields {
                            number: n(2_000_000 + spec * 10 + c),
                            draft: false,
                            head_branch: text(format!("syn-contract-{c}")),
                            head_commit: commit(3_000_000 + spec * 10 + c),
                            base_branch: text("main"),
                            closes: vec![],
                        },
                        merge_commit: commit(4_000_000 + spec * 10 + c),
                        merged_at: Timestamp(5),
                    },
                    read_back: true,
                },
                files: (0..10)
                    .map(|f| ChangedFile {
                        path: text(format!("docs/synthetic/{c}/{f}.md")),
                        previous_path: None,
                        added: false,
                    })
                    .collect(),
            })
            .collect();
        fleets.push(FleetInput {
            spec: n(spec),
            facts: Observed::Complete(FleetFacts {
                issue: issue(format!("Synthetic spec {spec}"), false, vec![]),
                approval: Some(PlanApproval {
                    approval: Approval {
                        comment: n(8_000_000 + spec),
                        revision: n(1),
                        fingerprint: Fingerprint::parse(&"d".repeat(64)).expect("64 hex"),
                    },
                    rows: tickets
                        .iter()
                        .map(|t| (t.number, Ready::Agent))
                        .collect::<BTreeMap<_, _>>(),
                    approved_at: 100,
                }),
                fingerprint_now: Fingerprint::parse(&"d".repeat(64)).expect("64 hex"),
                tickets,
                changes,
                follow_ups: vec![],
                records: SpecRecords::default(),
            }),
        });
    }
    Snapshot {
        default_branch: Observed::Complete(text("main")),
        fleets: Observed::Complete(fleets),
    }
}

fn main() {
    let clock = Fixed(Instant::now());
    for specs in [10, 50] {
        let source = Synthetic::new(specs);
        let tickets = specs * PER_SPEC;
        let bytes = fingerprint(
            &serde_json::to_vec(&openwiz_core::fleet::fleets::fleets(
                &source,
                &clock,
                Duration::from_secs(3600),
            ))
            .expect("encodes"),
        );
        let ns = median_ns(|| {
            black_box(openwiz_core::fleet::fleets::fleets(
                black_box(&source),
                &clock,
                Duration::from_secs(3600),
            ));
        });
        report(&format!("fleet_walk_{tickets}"), bytes, ns);
    }
    let flags = SpawnFlags {
        provider: "--provider".into(),
        model: "--model".into(),
        effort: "--reasoning-level".into(),
    };
    let rules = Rules::parse(RULES, &flags).expect("synthetic rules");
    for specs in [10, 50] {
        let snapshot = snapshot(specs);
        let tickets = specs * PER_SPEC;
        let planned = plan(&snapshot, &rules, NOW).expect("plans");
        let bytes = fingerprint(&serde_json::to_vec(&planned).expect("encodes"));
        let ns = median_ns(|| {
            black_box(plan(black_box(&snapshot), &rules, NOW).expect("plans"));
        });
        report(&format!("tick_plan_{tickets}"), bytes, ns);
        let ns = median_ns(|| {
            let doc = serde_json::to_value(black_box(&planned)).expect("encodes");
            let mut out = Vec::new();
            serde_json::to_writer_pretty(&mut out, &doc).expect("writes");
            black_box(out);
        });
        report(&format!("tick_plan_json_{tickets}"), bytes, ns);
    }
}
