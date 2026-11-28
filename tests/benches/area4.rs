use std::collections::BTreeMap;
use std::hint::black_box;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_adapter_github::allowlist::Invocation;
use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::TickReads;
use openwiz_cli::fleet::tick::{Inventory, World};
use openwiz_core::envelope::Completeness;
use openwiz_core::fleet::fleets::FleetsSource;
use openwiz_core::fleet::model::{
    Commit, Counts, Coverage, Envelope, Fleet, FleetsView, Freshness, Gh, GitHubSource, Issue,
    IssueState, ListOutcome, MergedPr, Milestone, NonEmpty, Number, Outcome, PrFields, Read,
    ReadId, ReadKind, Repository, SchemaId, SourceName, Sources, State, TicketCore, TicketState,
    View, WorkedOut,
};
use openwiz_core::fleet::tick::{
    Approval, BlockerInput, ChangedFile, ContractChange, Fingerprint, FleetFacts, FleetInput,
    MergeInput, Observed, OpenPr, PlanApproval, PrInput, PrRecords, Ready, Rules, Snapshot,
    SpecRecords, TicketFacts, TicketInput, TicketRecords, plan,
};
use openwiz_core::messaging::sha256_hex;
use openwiz_core::model::Timestamp;
use openwiz_core::models::SpawnFlags;
use openwiz_core::new_thread::read::StrictJson;
use openwiz_core::source::SourceError;
use serde_json::{Value, json};

const SAMPLES: usize = 11;
const WARMUP: Duration = Duration::from_millis(30);
const FLEET_MD: &str = include_str!("../../docs/agents/fleet.md");

fn num(n: u64) -> Number {
    Number::new(n).unwrap()
}

fn ne(s: &str) -> NonEmpty {
    NonEmpty::new(s).unwrap()
}

fn commit(seed: u64) -> Commit {
    Commit::parse(&format!("{seed:040x}")).unwrap()
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h = 0xcbf2_9ce4_8422_2325_u64;
    for &b in bytes {
        h ^= u64::from(b);
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h
}

fn bench(name: &str, bytes: usize, mut f: impl FnMut() -> u64) {
    let warmup_end = Instant::now() + WARMUP;
    let mut hash = 0_u64;
    while Instant::now() < warmup_end {
        hash = black_box(f());
    }
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let start = Instant::now();
        hash = black_box(f());
        samples.push(start.elapsed().as_nanos() as u64);
    }
    samples.sort_unstable();
    let median = samples[SAMPLES / 2];
    let min = samples[0];
    let max = samples[SAMPLES - 1];
    println!(
        "{name:32} hash={hash:016x} bytes={bytes:8} median={median:12} ns  min={min:12}  max={max:12}"
    );
}

fn build_pr_list_json(count: usize) -> Vec<u8> {
    let mut rows = Vec::with_capacity(count);
    for i in 1..=count {
        let n = i as u64;
        let issue_n = n + 10_000;
        let head = format!("{:040x}", n * 3 + 1);
        let merge = format!("{:040x}", n * 3 + 2);
        let closes = json!([{
            "id": format!("I_syn_{issue_n}"),
            "number": issue_n,
            "repository": {
                "id": "R_syn_1",
                "name": "example",
                "owner": {"id": "O_syn_1", "login": "synthetic"}
            },
            "url": format!("https://example.invalid/synthetic/example/issues/{issue_n}")
        }]);
        let row = match i % 3 {
            0 => json!({
                "baseRefName": "main",
                "closingIssuesReferences": closes,
                "headRefName": format!("room/syn-{n}"),
                "headRefOid": head,
                "isDraft": false,
                "mergeCommit": {"oid": merge},
                "mergedAt": "2026-10-30T18:30:00Z",
                "number": n,
                "state": "MERGED",
                "title": format!("#{issue_n}: Synthetic merged ticket {n}")
            }),
            1 => json!({
                "baseRefName": "main",
                "closingIssuesReferences": closes,
                "headRefName": format!("room/syn-{n}"),
                "headRefOid": head,
                "isDraft": false,
                "mergeCommit": null,
                "mergedAt": null,
                "number": n,
                "state": "OPEN",
                "title": format!("#{issue_n}: Synthetic open ticket {n}")
            }),
            _ => json!({
                "baseRefName": "main",
                "closingIssuesReferences": closes,
                "headRefName": format!("room/syn-{n}"),
                "headRefOid": head,
                "isDraft": false,
                "mergeCommit": null,
                "mergedAt": null,
                "number": n,
                "state": "CLOSED",
                "title": format!("#{issue_n}: Synthetic closed ticket {n}")
            }),
        };
        rows.push(row);
    }
    serde_json::to_vec(&rows).unwrap()
}

fn build_issue_list_json(count: usize) -> Vec<u8> {
    let mut rows = Vec::with_capacity(count);
    for i in 1..=count {
        let n = i as u64;
        let blockers = if i > 1 && i % 2 == 0 {
            json!({
                "nodes": [{
                    "id": format!("I_syn_{}", n - 1),
                    "number": n - 1,
                    "state": "OPEN",
                    "title": format!("Synthetic ticket {}", n - 1),
                    "url": format!("https://example.invalid/synthetic/example/issues/{}", n - 1)
                }],
                "totalCount": 1
            })
        } else {
            json!({"nodes": [], "totalCount": 0})
        };
        rows.push(json!({
            "blockedBy": blockers,
            "body": format!("Ticket {n}\n**Owned paths:** `crates/core/src/m{n}.rs`\n**Relies on:** `contracts/open-development.v1.md`\n"),
            "id": format!("I_syn_{n}"),
            "labels": [{
                "color": "0e8a16",
                "description": "Ready",
                "id": "L_syn_1",
                "name": "ready-for-agent"
            }],
            "milestone": {
                "description": "Synthetic release",
                "dueOn": null,
                "number": 1,
                "title": "0.2.0"
            },
            "number": n,
            "state": if i % 3 == 0 { "CLOSED" } else { "OPEN" },
            "subIssues": {"nodes": [], "totalCount": 0},
            "title": format!("Synthetic ticket {n}")
        }));
    }
    serde_json::to_vec(&rows).unwrap()
}

fn build_wide_object_json(keys: usize) -> Vec<u8> {
    let mut out = String::with_capacity(keys * 14 + 2);
    out.push('{');
    for i in 0..keys {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!("\"k{i}\":{i}"));
    }
    out.push('}');
    out.into_bytes()
}

fn build_plan_graphql_issues_json(count: usize) -> Vec<u8> {
    let mut nodes = Vec::with_capacity(count);
    for i in 1..=count {
        let n = i as u64;
        let url = format!("https://github.com/synthetic/example/issues/{n}");
        nodes.push(json!({
            "number": n,
            "title": format!("Synthetic plan issue {n}"),
            "url": url,
            "state": if i % 3 == 0 { "CLOSED" } else { "OPEN" },
            "milestone": {"number": 1, "title": "0.2.0"},
            "parent": null,
            "labels": {
                "totalCount": 1,
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": [{"name": "ready-for-agent"}]
            },
            "subIssues": {
                "totalCount": 0,
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": []
            },
            "blockedBy": {
                "totalCount": 0,
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": []
            },
            "closedByPullRequestsReferences": {
                "totalCount": 0,
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": []
            }
        }));
    }
    serde_json::to_vec(&json!({
        "data": {
            "repository": {
                "issues": {
                    "totalCount": count,
                    "pageInfo": {"hasNextPage": false, "endCursor": null},
                    "nodes": nodes
                }
            }
        }
    }))
    .unwrap()
}

fn build_tick_e2e_executor(specs: usize, per_spec: usize) -> (Executor, usize) {
    let base_sha = format!("{:040x}", 1_u64);
    let mut issue_rows = Vec::new();
    let mut pr_rows = Vec::new();
    let mut responses: BTreeMap<Vec<String>, Vec<u8>> = BTreeMap::new();
    let mut comment_rows = Vec::new();
    let mut next_issue = 1_u64;
    let mut next_pr = 50_000_u64;
    let mut next_comment = 1_u64;

    for s in 0..specs {
        let spec_num = next_issue;
        next_issue += 1;
        let mut sub_nodes = Vec::new();
        let mut rev_text = format!(
            "plan-graph revision v2\nspec #{spec_num} body sha256 {}\n",
            sha256_hex(format!("Spec {spec_num}\n\n").as_bytes())
        );
        let mut table_rows =
            String::from("| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n");
        let mut ticket_nums = Vec::new();
        for t in 0..per_spec {
            let t_num = next_issue;
            next_issue += 1;
            ticket_nums.push(t_num);
            let prev = (t > 0 && t % 2 == 1).then(|| ticket_nums[t - 1]);
            let state = if t % 3 == 0 { "CLOSED" } else { "OPEN" };
            let title = format!("Synthetic ticket {s}-{t}");
            let body = format!(
                "Ticket {t_num}\n**Owned paths:** `crates/core/src/m{t_num}.rs`\n**Relies on:** nothing\n"
            );
            let blocked_nodes = match prev {
                Some(b) => json!([{
                    "id": format!("I_syn_{b}"),
                    "number": b,
                    "state": if (t - 1) % 3 == 0 { "CLOSED" } else { "OPEN" },
                    "title": format!("Synthetic ticket {s}-{}", t - 1),
                    "url": format!("https://example.invalid/synthetic/example/issues/{b}")
                }]),
                None => json!([]),
            };
            issue_rows.push(json!({
                "blockedBy": {"nodes": blocked_nodes, "totalCount": usize::from(prev.is_some())},
                "body": body,
                "id": format!("I_syn_{t_num}"),
                "labels": [{
                    "color": "0e8a16",
                    "description": "Ready",
                    "id": "L_syn_1",
                    "name": "ready-for-agent"
                }],
                "milestone": null,
                "number": t_num,
                "state": state,
                "subIssues": {"nodes": [], "totalCount": 0},
                "title": title
            }));
            sub_nodes.push(json!({
                "id": format!("I_syn_{t_num}"),
                "number": t_num,
                "state": state,
                "title": title,
                "url": format!("https://example.invalid/synthetic/example/issues/{t_num}")
            }));
            let blocked_str = prev.map_or_else(|| "none".to_owned(), |b| format!("#{b}"));
            let bhash = sha256_hex(format!("{body}\n").as_bytes());
            rev_text.push_str(&format!(
                "ticket #{t_num} blocked-by {blocked_str} body sha256 {bhash} title {title}\n"
            ));
            table_rows.push_str(&format!(
                "| #{t_num} | {title} | {blocked_str} | ready-for-agent |\n"
            ));

            if t % 3 == 0 {
                let pr_num = next_pr;
                next_pr += 1;
                let head = format!("{:040x}", pr_num * 2);
                let merge = format!("{:040x}", pr_num * 2 + 1);
                pr_rows.push(json!({
                    "baseRefName": "main",
                    "closingIssuesReferences": [{
                        "id": format!("I_syn_{t_num}"),
                        "number": t_num,
                        "repository": {
                            "id": "R_syn_1",
                            "name": "example",
                            "owner": {"id": "O_syn_1", "login": "synthetic"}
                        },
                        "url": format!("https://example.invalid/synthetic/example/issues/{t_num}")
                    }],
                    "headRefName": format!("room/syn-{t_num}"),
                    "headRefOid": head,
                    "isDraft": false,
                    "mergeCommit": {"oid": merge},
                    "mergedAt": "2026-10-30T18:30:00Z",
                    "number": pr_num,
                    "state": "MERGED",
                    "title": format!("#{t_num}: {title}")
                }));
                let compare_path = format!("repos/{{owner}}/{{repo}}/compare/{merge}...{base_sha}");
                responses.insert(
                    vec![
                        "api".into(),
                        compare_path,
                        "--jq".into(),
                        "{status: .status, behind_by: .behind_by}".into(),
                    ],
                    br#"{"status":"identical","behind_by":0}"#.to_vec(),
                );
                let cid = next_comment;
                next_comment += 1;
                comment_rows.push(json!({
                    "issue_url": format!("https://example.invalid/api/v3/repos/synthetic/example/issues/{t_num}"),
                    "id": cid,
                    "author": "jparker2006",
                    "body": "launch-fleet: archived",
                    "created": 1_793_385_000_000_u64,
                    "updated": 1_793_385_000_000_u64
                }));
            } else if t % 3 == 1 && t < 3 {
                let pr_num = next_pr;
                next_pr += 1;
                let head = format!("{:040x}", pr_num * 2);
                pr_rows.push(json!({
                    "baseRefName": "main",
                    "closingIssuesReferences": [{
                        "id": format!("I_syn_{t_num}"),
                        "number": t_num,
                        "repository": {
                            "id": "R_syn_1",
                            "name": "example",
                            "owner": {"id": "O_syn_1", "login": "synthetic"}
                        },
                        "url": format!("https://example.invalid/synthetic/example/issues/{t_num}")
                    }],
                    "headRefName": format!("room/syn-{t_num}"),
                    "headRefOid": head,
                    "isDraft": true,
                    "mergeCommit": null,
                    "mergedAt": null,
                    "number": pr_num,
                    "state": "OPEN",
                    "title": format!("#{t_num}: {title}")
                }));
                responses.insert(
                    vec![
                        "api".into(),
                        format!("repos/{{owner}}/{{repo}}/commits/{head}"),
                        "--jq".into(),
                        openwiz_adapter_github::tick::COMMIT.into(),
                    ],
                    serde_json::to_vec(&json!({"sha": head, "subject": "wip"})).unwrap(),
                );
                responses.insert(
                    vec![
                        "api".into(),
                        format!(
                            "repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100"
                        ),
                        "--paginate".into(),
                        "--jq".into(),
                        openwiz_adapter_github::tick::RUNS.into(),
                    ],
                    br#"{"total_count":0,"runs":[]}"#.to_vec(),
                );
                responses.insert(
                    vec![
                        "pr".into(),
                        "checks".into(),
                        pr_num.to_string(),
                        "--json".into(),
                        openwiz_adapter_github::tickets::CHECK_FIELDS.into(),
                    ],
                    b"[]".to_vec(),
                );
                responses.insert(
                    vec![
                        "pr".into(),
                        "view".into(),
                        pr_num.to_string(),
                        "--json".into(),
                        openwiz_adapter_github::tickets::PR_FIELDS.into(),
                    ],
                    serde_json::to_vec(&json!({
                        "baseRefName": "main",
                        "closingIssuesReferences": [{
                            "id": format!("I_syn_{t_num}"),
                            "number": t_num,
                            "repository": {"id": "R_syn_1"},
                            "url": format!("https://example.invalid/synthetic/example/issues/{t_num}")
                        }],
                        "headRefName": format!("room/syn-{t_num}"),
                        "headRefOid": head,
                        "isDraft": true,
                        "mergeCommit": null,
                        "mergedAt": null,
                        "number": pr_num,
                        "state": "OPEN"
                    }))
                    .unwrap(),
                );
            }
        }
        issue_rows.push(json!({
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": format!("Spec {spec_num}\n"),
            "id": format!("I_syn_{spec_num}"),
            "labels": [],
            "milestone": null,
            "number": spec_num,
            "state": "OPEN",
            "subIssues": {"nodes": sub_nodes, "totalCount": per_spec},
            "title": format!("spec: Synthetic fleet {s}")
        }));
        let fp = sha256_hex(rev_text.as_bytes());
        let approval_body = format!(
            "**Plan graph approved by Jake, 2026-10-30, revision 1:** Approved.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-1\n\nFingerprint: `{fp}`\n\n{table_rows}\n```text\n{rev_text}```\n"
        );
        let cid = next_comment;
        next_comment += 1;
        comment_rows.push(json!({
            "issue_url": format!("https://example.invalid/api/v3/repos/synthetic/example/issues/{spec_num}"),
            "id": cid,
            "author": "jparker2006",
            "body": approval_body,
            "created": 1_793_380_000_000_u64,
            "updated": 1_793_380_000_000_u64
        }));
    }

    let issues_bytes = serde_json::to_vec(&issue_rows).unwrap();
    let prs_bytes = serde_json::to_vec(&pr_rows).unwrap();
    let total_bytes = issues_bytes.len() + prs_bytes.len();

    responses.insert(
        vec![
            "repo".into(),
            "view".into(),
            "--json".into(),
            openwiz_adapter_github::tick::REPOSITORY_FIELDS.into(),
        ],
        br#"{"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic/example","url":"https://example.invalid/synthetic/example"}"#.to_vec(),
    );
    responses.insert(
        vec![
            "repo".into(),
            "view".into(),
            "--json".into(),
            "nameWithOwner,isPrivate".into(),
        ],
        br#"{"nameWithOwner":"synthetic/example","isPrivate":false}"#.to_vec(),
    );
    responses.insert(
        vec![
            "issue".into(),
            "list".into(),
            "--state".into(),
            "all".into(),
            "--limit".into(),
            "1000".into(),
            "--json".into(),
            "blockedBy,body,id,labels,milestone,number,state,subIssues,title".into(),
        ],
        issues_bytes,
    );
    responses.insert(
        vec![
            "pr".into(),
            "list".into(),
            "--state".into(),
            "all".into(),
            "--limit".into(),
            "1000".into(),
            "--json".into(),
            openwiz_adapter_github::fleets::PR_FIELDS.into(),
        ],
        prs_bytes,
    );
    responses.insert(
        vec![
            "api".into(),
            "repos/{owner}/{repo}/git/ref/heads/main".into(),
            "--jq".into(),
            openwiz_adapter_github::tick::REF.into(),
        ],
        serde_json::to_vec(&json!({"sha": base_sha})).unwrap(),
    );
    responses.insert(
        vec![
            "api".into(),
            format!("repos/{{owner}}/{{repo}}/contents/docs/agents/fleet.md?ref={base_sha}"),
            "--header".into(),
            "Accept: application/vnd.github.raw+json".into(),
        ],
        FLEET_MD.as_bytes().to_vec(),
    );

    let mut page = 1_usize;
    for chunk in comment_rows.chunks(100) {
        responses.insert(
            vec![
                "api".into(),
                format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}"),
                "--jq".into(),
                openwiz_adapter_github::tick::REPOSITORY_COMMENTS.into(),
            ],
            serde_json::to_vec(chunk).unwrap(),
        );
        page += 1;
    }
    if comment_rows.len().is_multiple_of(100) {
        responses.insert(
            vec![
                "api".into(),
                format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}"),
                "--jq".into(),
                openwiz_adapter_github::tick::REPOSITORY_COMMENTS.into(),
            ],
            b"[]".to_vec(),
        );
    }

    let map = Arc::new(responses);
    let exec = Executor::supplied(Arc::new(move |call: &Invocation, _: Instant| {
        map.get(call.argv())
            .cloned()
            .ok_or_else(|| SourceError::Malformed {
                detail: format!("unexpected call: {:?}", call.argv()),
            })
    }));
    (exec, total_bytes)
}

fn build_tick_snapshot(specs: usize, per_spec: usize) -> (Snapshot, Rules) {
    let flags = SpawnFlags {
        provider: "--provider".to_owned(),
        model: "--model".to_owned(),
        effort: "--reasoning-level".to_owned(),
    };
    let rules = Rules::parse(FLEET_MD, &flags).unwrap();
    let mut fleets = Vec::with_capacity(specs);
    let mut next_id = 1_u64;
    for s in 0..specs {
        let spec = num(next_id);
        next_id += 1;
        let fp = Fingerprint::parse(&format!("{:064x}", s + 1)).unwrap();
        let mut rows = BTreeMap::new();
        let mut tickets = Vec::with_capacity(per_spec);
        let mut prev_num = None;
        for t in 0..per_spec {
            let tid = num(next_id);
            next_id += 1;
            rows.insert(tid, Ready::Agent);
            let blockers = match prev_num {
                Some(b) if t % 2 == 1 => vec![BlockerInput {
                    number: b,
                    state: IssueState::Closed,
                    merged: Some(MergeInput {
                        pr: MergedPr {
                            fields: PrFields {
                                number: num(100_000 + b.get()),
                                draft: false,
                                head_branch: ne(&format!("room/syn-{b}")),
                                head_commit: commit(b.get() * 2),
                                base_branch: ne("main"),
                                closes: vec![b],
                            },
                            merge_commit: commit(b.get() * 2 + 1),
                            merged_at: Timestamp(1_793_380_000_000),
                        },
                        read_back: true,
                    }),
                }],
                _ => vec![],
            };
            let pr = match t % 3 {
                0 => Some(PrInput::Merged(MergeInput {
                    pr: MergedPr {
                        fields: PrFields {
                            number: num(100_000 + tid.get()),
                            draft: false,
                            head_branch: ne(&format!("room/syn-{tid}")),
                            head_commit: commit(tid.get() * 2),
                            base_branch: ne("main"),
                            closes: vec![tid],
                        },
                        merge_commit: commit(tid.get() * 2 + 1),
                        merged_at: Timestamp(1_793_380_000_000),
                    },
                    read_back: true,
                })),
                1 => Some(PrInput::Open(Box::new(OpenPr {
                    fields: PrFields {
                        number: num(100_000 + tid.get()),
                        draft: false,
                        head_branch: ne(&format!("room/syn-{tid}")),
                        head_commit: commit(tid.get() * 2),
                        base_branch: ne("main"),
                        closes: vec![tid],
                    },
                    subject: "green".to_owned(),
                    ci: None,
                    base_now: Some(commit(1)),
                    reports: vec![],
                    starts: vec![],
                    records: PrRecords::default(),
                }))),
                _ => None,
            };
            tickets.push(TicketInput {
                number: tid,
                facts: Observed::Complete(TicketFacts {
                    issue: Issue {
                        title: format!("Synthetic ticket {tid}"),
                        state: if t % 3 == 0 {
                            IssueState::Closed
                        } else {
                            IssueState::Open
                        },
                        milestone: None,
                        labels: vec![ne("ready-for-agent")],
                        owned_paths: Some(ne(&format!("`crates/core/src/m{tid}.rs`"))),
                        relies_on: Some(ne("`contracts/open-development.v1.md`")),
                        pending_question: None,
                    },
                    blockers,
                    pr,
                    builder: None,
                    builder_source: None,
                    reviewers: vec![],
                    starts: vec![],
                    relies_on: vec![
                        ne("contracts/open-development.v1.md"),
                        ne("crates/core/src/m*.rs"),
                    ],
                    holds: vec![],
                    held_label_comment: None,
                    question: None,
                    records: TicketRecords {
                        archived: t % 3 == 0,
                        ..Default::default()
                    },
                }),
            });
            prev_num = Some(tid);
        }
        let changes = (0..5)
            .map(|c| ContractChange {
                merged: MergeInput {
                    pr: MergedPr {
                        fields: PrFields {
                            number: num(900_000 + (s * 10 + c) as u64),
                            draft: false,
                            head_branch: ne(&format!("room/syn-c-{s}-{c}")),
                            head_commit: commit(900_000 + (s * 10 + c) as u64),
                            base_branch: ne("main"),
                            closes: vec![],
                        },
                        merge_commit: commit(950_000 + (s * 10 + c) as u64),
                        merged_at: Timestamp(1_793_390_000_000),
                    },
                    read_back: true,
                },
                files: vec![ChangedFile {
                    path: ne("crates/cli/src/other.rs"),
                    previous_path: None,
                    added: false,
                }],
            })
            .collect();
        fleets.push(FleetInput {
            spec,
            facts: Observed::Complete(FleetFacts {
                issue: Issue {
                    title: format!("spec: Synthetic {s}"),
                    state: IssueState::Open,
                    milestone: None,
                    labels: vec![],
                    owned_paths: None,
                    relies_on: None,
                    pending_question: None,
                },
                approval: Some(PlanApproval {
                    approval: Approval {
                        comment: num(1),
                        revision: num(1),
                        fingerprint: fp.clone(),
                    },
                    rows,
                    approved_at: 1_793_380_000_000,
                }),
                fingerprint_now: fp,
                tickets,
                changes,
                follow_ups: vec![],
                records: SpecRecords::default(),
            }),
        });
    }
    let snapshot = Snapshot {
        default_branch: Observed::Complete(ne("main")),
        fleets: Observed::Complete(fleets),
    };
    (snapshot, rules)
}

fn build_fleets_envelope(specs: usize, per_spec: usize) -> Envelope {
    let mut reads = Vec::new();
    let mut push = |kind: ReadKind| -> ReadId {
        let id = ReadId((reads.len() + 1) as u32);
        reads.push(Read { id, kind });
        id
    };
    let version = push(ReadKind::Version {
        source: SourceName::Github,
        outcome: Outcome::Complete {
            value: ne("2.100.0"),
        },
    });
    let repository = push(ReadKind::Repository {
        outcome: Outcome::Complete {
            value: Repository {
                name: ne("example"),
            },
        },
    });
    let mut fleets = Vec::with_capacity(specs);
    let mut tickets = Vec::with_capacity(specs * per_spec);
    let mut spec_nums = Vec::with_capacity(specs);
    let mut next_id = 1_u64;
    for s in 0..specs {
        let spec = num(next_id);
        next_id += 1;
        spec_nums.push(spec);
        let spec_issue = push(ReadKind::Issue {
            issue: spec,
            outcome: Outcome::Complete {
                value: Issue {
                    title: format!("spec: Synthetic fleet {s}"),
                    state: IssueState::Open,
                    milestone: Some(Milestone {
                        number: num(1),
                        title: "0.2.0".to_owned(),
                    }),
                    labels: vec![],
                    owned_paths: None,
                    relies_on: None,
                    pending_question: None,
                },
            },
        });
        let mut tnums = Vec::with_capacity(per_spec);
        for t in 0..per_spec {
            let tid = num(next_id);
            next_id += 1;
            tnums.push(tid);
            let issue_id = push(ReadKind::Issue {
                issue: tid,
                outcome: Outcome::Complete {
                    value: Issue {
                        title: format!("Synthetic ticket {tid}"),
                        state: IssueState::Open,
                        milestone: None,
                        labels: vec![ne("ready-for-agent")],
                        owned_paths: None,
                        relies_on: None,
                        pending_question: None,
                    },
                },
            });
            let blocked_by = push(ReadKind::BlockedBy {
                ticket: tid,
                outcome: ListOutcome::Complete { value: vec![] },
            });
            let pr = push(ReadKind::PrDiscovery {
                issue: tid,
                outcome: Outcome::Complete { value: None },
            });
            let state = match t % 4 {
                0 => State::Known(TicketState::Merged),
                1 => State::Known(TicketState::Building),
                2 => State::Known(TicketState::Ready),
                _ => State::Unknown(ne("no pull request, and no ready label: not approved yet")),
            };
            tickets.push(TicketCore {
                number: tid,
                state,
                issue: issue_id,
                blocked_by,
                pr,
                ci: None,
                review: None,
                on_base: None,
            });
        }
        let sub_id = push(ReadKind::SubIssues {
            spec,
            outcome: ListOutcome::Complete { value: tnums },
        });
        fleets.push(Fleet {
            spec,
            issue: spec_issue,
            tickets: sub_id,
            progress: WorkedOut::Known(Counts {
                tickets: per_spec as u64,
                merged: (per_spec / 4) as u64,
                ready: (per_spec / 4) as u64,
                building: (per_spec / 4) as u64,
                in_review: 0,
                changes_requested: 0,
                held: 0,
                blocked: 0,
                unknown: (per_spec - 3 * (per_spec / 4)) as u64,
            }),
        });
    }
    let specs = push(ReadKind::SpecList {
        outcome: ListOutcome::Complete { value: spec_nums },
    });
    Envelope {
        schema: SchemaId::V1,
        sources: Sources {
            github: GitHubSource {
                name: Gh::Gh,
                version,
                tested_version: "2.100.0".to_owned(),
                version_tested: true,
            },
            cloudroom: None,
        },
        reads,
        coverage: Coverage {
            state: Completeness::Complete,
        },
        freshness: Freshness {
            snapshot_at: Timestamp(1_793_400_000_000),
        },
        data: View::Fleets(FleetsView {
            repository,
            specs,
            fleets,
            tickets,
            blockers: vec![],
            needs_you: WorkedOut::Known(vec![]),
        }),
    }
}

fn static_executor(bytes: Vec<u8>) -> Executor {
    let bytes = Arc::new(bytes);
    Executor::supplied(Arc::new(move |_: &Invocation, _: Instant| {
        Ok((*bytes).clone())
    }))
}

fn main() {
    let deadline = || Instant::now() + Duration::from_secs(60);

    let (exec_200, bytes_200) = build_tick_e2e_executor(4, 50);
    let gh_200 = TickReads::with_executor(exec_200);
    bench("fleet_tick_e2e_200", bytes_200, || {
        let d = deadline();
        let inv = Inventory::read(&gh_200, d).unwrap();
        let world = World::read(&gh_200, None, Path::new("/nonexistent"), d, inv).unwrap();
        let p = plan(&world.snapshot, &world.rules, 1_793_400_000_000).unwrap();
        let bytes = serde_json::to_vec(&p).unwrap();
        fnv1a(&bytes)
    });

    let (exec_900, bytes_900) = build_tick_e2e_executor(9, 100);
    let gh_900 = TickReads::with_executor(exec_900);
    bench("fleet_tick_e2e_900", bytes_900, || {
        let d = deadline();
        let inv = Inventory::read(&gh_900, d).unwrap();
        let world = World::read(&gh_900, None, Path::new("/nonexistent"), d, inv).unwrap();
        let p = plan(&world.snapshot, &world.rules, 1_793_400_000_000).unwrap();
        let bytes = serde_json::to_vec(&p).unwrap();
        fnv1a(&bytes)
    });

    let (snap_1000, rules) = build_tick_snapshot(10, 100);
    bench("tick_plan_1000", 1000, || {
        let p = plan(&snap_1000, &rules, 1_793_400_000_000).unwrap();
        fnv1a(&serde_json::to_vec(&p).unwrap())
    });

    let (snap_5000, _) = build_tick_snapshot(50, 100);
    bench("tick_plan_5000", 5000, || {
        let p = plan(&snap_5000, &rules, 1_793_400_000_000).unwrap();
        fnv1a(&serde_json::to_vec(&p).unwrap())
    });

    let pr_json_1000 = build_pr_list_json(1000);
    let pr_len_1000 = pr_json_1000.len();
    let tick_pr_1000 = TickReads::with_executor(static_executor(pr_json_1000));
    bench("tick_pull_requests_1000", pr_len_1000, || {
        let res = tick_pr_1000.pull_requests(deadline()).unwrap();
        (res.rows.len() as u64) ^ ((res.closed.len() as u64) << 16)
    });

    let pr_json_5000 = build_pr_list_json(5000);
    let pr_len_5000 = pr_json_5000.len();
    let tick_pr_5000 = TickReads::with_executor(static_executor(pr_json_5000));
    bench("tick_pull_requests_5000", pr_len_5000, || {
        let res = tick_pr_5000.pull_requests(deadline()).unwrap();
        (res.rows.len() as u64) ^ ((res.closed.len() as u64) << 16)
    });

    let issue_json_1000 = build_issue_list_json(1000);
    let issue_len_1000 = issue_json_1000.len();
    let fleets_iss_1000 = GitHubFleets::with_executor(static_executor(issue_json_1000));
    bench("fleets_issues_1000", issue_len_1000, || {
        let res = fleets_iss_1000.issues(deadline()).unwrap();
        res.rows.len() as u64
    });

    let issue_json_5000 = build_issue_list_json(5000);
    let issue_len_5000 = issue_json_5000.len();
    let fleets_iss_5000 = GitHubFleets::with_executor(static_executor(issue_json_5000));
    bench("fleets_issues_5000", issue_len_5000, || {
        let res = fleets_iss_5000.issues(deadline()).unwrap();
        res.rows.len() as u64
    });

    let pr_json_1000b = build_pr_list_json(1000);
    let pr_len_1000b = pr_json_1000b.len();
    let fleets_pr_1000 = GitHubFleets::with_executor(static_executor(pr_json_1000b));
    bench("fleets_prs_1000", pr_len_1000b, || {
        let res = fleets_pr_1000.stock_pull_requests(deadline()).unwrap();
        res.rows.len() as u64
    });

    let pr_json_5000b = build_pr_list_json(5000);
    let pr_len_5000b = pr_json_5000b.len();
    let fleets_pr_5000 = GitHubFleets::with_executor(static_executor(pr_json_5000b));
    bench("fleets_prs_5000", pr_len_5000b, || {
        let res = fleets_pr_5000.stock_pull_requests(deadline()).unwrap();
        res.rows.len() as u64
    });

    let wide_4000 = build_wide_object_json(4000);
    let wide_len = wide_4000.len();
    let fleets_wide = GitHubFleets::with_executor(static_executor(wide_4000.clone()));
    bench("fleets_strict_wide_4000", wide_len, || {
        u64::from(fleets_wide.repository(deadline()).is_err())
    });

    bench("new_thread_strict_wide_4000", wide_len, || {
        u64::from(serde_json::from_slice::<StrictJson>(&wide_4000).is_ok())
    });

    let env_1000 = build_fleets_envelope(10, 100);
    bench("fleets_render_1000", 1000, || {
        fnv1a(openwiz_cli::fleets::render(&env_1000).as_bytes())
    });

    let env_5000 = build_fleets_envelope(50, 100);
    bench("fleets_render_5000", 5000, || {
        fnv1a(openwiz_cli::fleets::render(&env_5000).as_bytes())
    });

    let plan_1000 = build_plan_graphql_issues_json(1000);
    let plan_len_1000 = plan_1000.len();
    bench("plan_strict_issues_1000", plan_len_1000, || {
        let v: Value = openwiz_adapter_github::plan::strict(&plan_1000).unwrap();
        v["data"]["repository"]["issues"]["totalCount"]
            .as_u64()
            .unwrap()
    });
}
