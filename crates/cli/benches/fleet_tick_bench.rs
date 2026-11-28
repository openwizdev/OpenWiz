use std::collections::HashMap;
use std::hint::black_box;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use openwiz_adapter_github::allowlist::Invocation;
use openwiz_adapter_github::process::Execute;
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::TickReads;
use openwiz_cli::fleet::tick::{Inventory, World};
use openwiz_core::fleet::tick;
use openwiz_core::messaging::sha256_hex;
use openwiz_core::source::SourceError;
use serde_json::{Value, json};

const REPO: &str = "synthetic-owner/synthetic-repo";
const REPO_URL: &str = "https://github.com/synthetic-owner/synthetic-repo";
const AUTHOR: &str = "synthetic-bot";
const BASE_SHA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const NOW_MS: u64 = 1_760_000_000_000;

const FLEET_MD: &str = "\
# Fleet settings

## Models

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `ci` | Full suite | `main` |

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `synthetic-bot` |

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph | The reviewer above | The loop, as soon as the reviewer's APPROVE names that exact commit |
";

struct Fixture {
    answers: HashMap<Vec<String>, Vec<u8>>,
    calls: Arc<AtomicUsize>,
}

impl Fixture {
    fn executor(&self) -> (TickReads, Arc<AtomicUsize>) {
        let answers = self.answers.clone();
        let calls = Arc::new(AtomicUsize::new(0));
        let counter = calls.clone();
        let handler: Arc<Execute> = Arc::new(move |call: &Invocation, _| {
            counter.fetch_add(1, Ordering::Relaxed);
            answers
                .get(call.argv())
                .cloned()
                .ok_or_else(|| SourceError::Unavailable {
                    detail: format!("unmocked call: {:?}", call.argv()),
                })
        });
        (TickReads::with_executor(Executor::supplied(handler)), calls)
    }
}

fn sha(n: u64) -> String {
    format!("{n:040x}")
}

fn body_hash_v2(body: &str) -> String {
    let mut normalized = String::new();
    for part in body.split_inclusive('\n') {
        let mut line = part.to_owned();
        let b = line.as_bytes();
        let indent = b.iter().take_while(|c| matches!(c, b' ' | b'\t')).count();
        if b.get(indent)
            .is_some_and(|c| matches!(c, b'-' | b'*' | b'+'))
        {
            let mut pos = indent + 1;
            while b.get(pos).is_some_and(|c| matches!(c, b' ' | b'\t')) {
                pos += 1;
            }
            if pos > indent + 1
                && matches!(b.get(pos..pos + 3), Some(b"[x]" | b"[X]"))
                && b.get(pos + 3)
                    .is_none_or(|c| matches!(c, b' ' | b'\t' | b'\r' | b'\n'))
            {
                line.replace_range(pos + 1..pos + 2, " ");
            }
        }
        normalized.push_str(&line);
    }
    normalized.push('\n');
    sha256_hex(normalized.as_bytes())
}

fn build_fixture(fleets: usize, tickets_per_fleet: usize, extra_merged_prs: usize) -> Fixture {
    let mut issues: Vec<Value> = Vec::new();
    let mut prs: Vec<Value> = Vec::new();
    let mut all_comments: Vec<Value> = Vec::new();
    let mut answers: HashMap<Vec<String>, Vec<u8>> = HashMap::new();

    let mut next_issue = 1u64;
    let mut next_pr = 50_000u64;
    let mut next_comment = 100_000u64;

    let mut open_prs: Vec<(u64, String, u64)> = Vec::new();
    let mut merged_commits: Vec<String> = Vec::new();

    for f in 0..fleets {
        let spec_num = next_issue;
        next_issue += 1;
        let spec_id = format!("I_spec_{spec_num}");
        let spec_body = format!(
            "## Spec {f}\n\nGoal for synthetic fleet {f}.\n- [x] first item\n- [ ] second item\n"
        );
        let mut sub_nodes = Vec::new();
        let mut rev_text = format!(
            "plan-graph revision v2\nspec #{spec_num} body sha256 {}\n",
            body_hash_v2(&spec_body)
        );
        let mut table_rows = String::new();
        let mut prev_closed_ticket: Option<(u64, String)> = None;

        for t in 0..tickets_per_fleet {
            let num = next_issue;
            next_issue += 1;
            let id = format!("I_ticket_{num}");
            let title = format!("Synthetic ticket {f}-{t}");
            let body = format!(
                "## Goal\n\nImplement part {t} of fleet {f}.\n\n**Owned paths:** `crates/cli/src/`\n**Relies on:** nothing\n\n## Acceptance\n- [x] builds cleanly\n- [ ] tests pass\n"
            );
            let is_closed = t % 4 == 0;
            let state = if is_closed { "CLOSED" } else { "OPEN" };
            let blocker = if !is_closed && t % 4 == 1 {
                prev_closed_ticket.clone()
            } else {
                None
            };
            let blocked_nodes = match &blocker {
                Some((bnum, bid)) => vec![json!({
                    "id": bid,
                    "number": bnum,
                    "state": "CLOSED",
                    "title": format!("Blocker {bnum}"),
                    "url": format!("{REPO_URL}/issues/{bnum}")
                })],
                None => vec![],
            };
            let blocked_text = match &blocker {
                Some((bnum, _)) => format!("#{bnum}"),
                None => "none".to_owned(),
            };
            let labels = if is_closed {
                vec![]
            } else {
                vec![
                    json!({"color": "0e8a16", "description": "ready", "id": "L1", "name": "ready-for-agent"}),
                ]
            };
            issues.push(json!({
                "blockedBy": {"nodes": blocked_nodes, "totalCount": usize::from(blocker.is_some())},
                "body": body,
                "id": id,
                "labels": labels,
                "milestone": null,
                "number": num,
                "state": state,
                "subIssues": {"nodes": [], "totalCount": 0},
                "title": title,
            }));
            sub_nodes.push(json!({
                "id": id,
                "number": num,
                "state": state,
                "title": title,
                "url": format!("{REPO_URL}/issues/{num}"),
            }));
            rev_text.push_str(&format!(
                "ticket #{num} blocked-by {blocked_text} body sha256 {} title {title}\n",
                body_hash_v2(&body)
            ));
            table_rows.push_str(&format!(
                "| #{num} | {title} | {blocked_text} | ready-for-agent |\n"
            ));

            if is_closed {
                let pr_num = next_pr;
                next_pr += 1;
                let head = sha(pr_num);
                let merge = sha(pr_num + 1_000_000);
                merged_commits.push(merge.clone());
                prs.push(json!({
                    "baseRefName": "main",
                    "closingIssuesReferences": [{
                        "id": id,
                        "number": num,
                        "repository": {"id": "R1", "name": "synthetic-repo", "owner": {"id": "O1", "login": "synthetic-owner"}},
                        "url": format!("{REPO_URL}/issues/{num}")
                    }],
                    "headRefName": format!("room/syn-{num}"),
                    "headRefOid": head,
                    "isDraft": false,
                    "mergeCommit": {"oid": merge},
                    "mergedAt": "2026-11-20T00:00:00Z",
                    "number": pr_num,
                    "state": "MERGED",
                    "title": format!("#{num}: {title}")
                }));
                let cid = next_comment;
                next_comment += 1;
                all_comments.push(json!({
                    "issue_url": format!("https://api.github.com/repos/{REPO}/issues/{num}"),
                    "id": cid,
                    "author": AUTHOR,
                    "body": "launch-fleet: archived",
                    "created": NOW_MS - 10_000,
                    "updated": NOW_MS - 10_000,
                }));
                prev_closed_ticket = Some((num, id));
            } else if t % 3 == 1 {
                let pr_num = next_pr;
                next_pr += 1;
                let head = sha(pr_num);
                prs.push(json!({
                    "baseRefName": "main",
                    "closingIssuesReferences": [{
                        "id": id,
                        "number": num,
                        "repository": {"id": "R1", "name": "synthetic-repo", "owner": {"id": "O1", "login": "synthetic-owner"}},
                        "url": format!("{REPO_URL}/issues/{num}")
                    }],
                    "headRefName": format!("room/syn-{num}"),
                    "headRefOid": head,
                    "isDraft": false,
                    "mergeCommit": null,
                    "mergedAt": null,
                    "number": pr_num,
                    "state": "OPEN",
                    "title": format!("#{num}: {title}")
                }));
                let cid = next_comment;
                next_comment += 1;
                all_comments.push(json!({
                    "issue_url": format!("https://api.github.com/repos/{REPO}/issues/{pr_num}"),
                    "id": cid,
                    "author": AUTHOR,
                    "body": format!("VERDICT: APPROVE at {head}\n\nLooks good."),
                    "created": NOW_MS - 5_000,
                    "updated": NOW_MS - 5_000,
                }));
                open_prs.push((pr_num, head, num));
            }
        }

        let fp = sha256_hex(rev_text.as_bytes());
        let approval_body = format!(
            "**Plan graph approved by Jake, revision 1:** \"go\"\n\n\
             Fingerprint: `{fp}`\n\n\
             | Ticket | Title | Blocked by | Label |\n\
             | --- | --- | --- | --- |\n\
             {table_rows}\n\
             ```text\n{rev_text}```\n"
        );
        let cid = next_comment;
        next_comment += 1;
        all_comments.push(json!({
            "issue_url": format!("https://api.github.com/repos/{REPO}/issues/{spec_num}"),
            "id": cid,
            "author": AUTHOR,
            "body": approval_body,
            "created": NOW_MS - 50_000,
            "updated": NOW_MS - 50_000,
        }));

        issues.push(json!({
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": spec_body,
            "id": spec_id,
            "labels": [],
            "milestone": null,
            "number": spec_num,
            "state": "OPEN",
            "subIssues": {"nodes": sub_nodes, "totalCount": tickets_per_fleet},
            "title": format!("Synthetic spec {f}"),
        }));
    }

    for extra in 0..extra_merged_prs {
        let pr_num = next_pr;
        next_pr += 1;
        let head = sha(pr_num);
        let merge = sha(pr_num + 2_000_000);
        prs.push(json!({
            "baseRefName": "main",
            "closingIssuesReferences": [],
            "headRefName": format!("room/historic-{extra}"),
            "headRefOid": head,
            "isDraft": false,
            "mergeCommit": {"oid": merge},
            "mergedAt": "2026-10-01T00:00:00Z",
            "number": pr_num,
            "state": "MERGED",
            "title": format!("Historic merged PR {extra}")
        }));
    }

    let put = |map: &mut HashMap<Vec<String>, Vec<u8>>, argv: &[&str], body: Vec<u8>| {
        map.insert(argv.iter().map(|s| (*s).to_owned()).collect(), body);
    };

    put(
        &mut answers,
        &[
            "repo",
            "view",
            "--json",
            openwiz_adapter_github::tick::REPOSITORY_FIELDS,
        ],
        serde_json::to_vec(&json!({
            "defaultBranchRef": {"name": "main"},
            "nameWithOwner": REPO,
            "url": REPO_URL,
        }))
        .unwrap(),
    );
    put(
        &mut answers,
        &["repo", "view", "--json", "nameWithOwner,isPrivate"],
        serde_json::to_vec(&json!({"nameWithOwner": REPO, "isPrivate": true})).unwrap(),
    );
    put(
        &mut answers,
        &[
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "blockedBy,body,id,labels,milestone,number,state,subIssues,title",
        ],
        serde_json::to_vec(&issues).unwrap(),
    );
    put(
        &mut answers,
        &[
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            openwiz_adapter_github::fleets::PR_FIELDS,
        ],
        serde_json::to_vec(&prs).unwrap(),
    );
    put(
        &mut answers,
        &[
            "api",
            "repos/{owner}/{repo}/git/ref/heads/main",
            "--jq",
            openwiz_adapter_github::tick::REF,
        ],
        serde_json::to_vec(&json!({"sha": BASE_SHA})).unwrap(),
    );
    let fleet_path =
        format!("repos/{{owner}}/{{repo}}/contents/docs/agents/fleet.md?ref={BASE_SHA}");
    put(
        &mut answers,
        &[
            "api",
            &fleet_path,
            "--header",
            "Accept: application/vnd.github.raw+json",
        ],
        FLEET_MD.as_bytes().to_vec(),
    );

    let mut page = 1usize;
    for chunk in all_comments.chunks(100) {
        let p = format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}");
        put(
            &mut answers,
            &[
                "api",
                &p,
                "--jq",
                openwiz_adapter_github::tick::REPOSITORY_COMMENTS,
            ],
            serde_json::to_vec(chunk).unwrap(),
        );
        page += 1;
    }
    if all_comments.len().is_multiple_of(100) {
        let p = format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}");
        put(
            &mut answers,
            &[
                "api",
                &p,
                "--jq",
                openwiz_adapter_github::tick::REPOSITORY_COMMENTS,
            ],
            b"[]".to_vec(),
        );
    }

    for merge in &merged_commits {
        let cmp = format!("repos/{{owner}}/{{repo}}/compare/{merge}...{BASE_SHA}");
        put(
            &mut answers,
            &[
                "api",
                &cmp,
                "--jq",
                "{status: .status, behind_by: .behind_by}",
            ],
            serde_json::to_vec(&json!({"status": "ahead", "behind_by": 0})).unwrap(),
        );
    }

    for (pr_num, head, ticket_num) in &open_prs {
        let commit_path = format!("repos/{{owner}}/{{repo}}/commits/{head}");
        put(
            &mut answers,
            &[
                "api",
                &commit_path,
                "--jq",
                openwiz_adapter_github::tick::COMMIT,
            ],
            serde_json::to_vec(
                &json!({"sha": head, "subject": format!("#{ticket_num}: green: done")}),
            )
            .unwrap(),
        );
        let runs_path =
            format!("repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100");
        let run_id = pr_num + 900_000;
        put(
            &mut answers,
            &[
                "api",
                &runs_path,
                "--paginate",
                "--jq",
                openwiz_adapter_github::tick::RUNS,
            ],
            serde_json::to_vec(&json!({
                "total_count": 1,
                "runs": [{
                    "id": run_id,
                    "head_sha": head,
                    "event": "pull_request",
                    "run_attempt": 1,
                    "updated": NOW_MS - 3_000,
                    "prs": [{"number": pr_num, "head": head, "base": BASE_SHA}]
                }]
            }))
            .unwrap(),
        );
        let jobs_path = format!(
            "repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
        );
        put(
            &mut answers,
            &[
                "api",
                &jobs_path,
                "--paginate",
                "--jq",
                openwiz_adapter_github::tick::JOBS,
            ],
            serde_json::to_vec(&json!({
                "total_count": 1,
                "jobs": [{
                    "id": run_id + 1,
                    "name": "ci",
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": head,
                    "run_id": run_id
                }]
            }))
            .unwrap(),
        );
        let pr_s = pr_num.to_string();
        put(
            &mut answers,
            &["pr", "checks", &pr_s, "--json", "bucket,name"],
            serde_json::to_vec(&json!([{"bucket": "pass", "name": "ci"}])).unwrap(),
        );
        put(
            &mut answers,
            &[
                "pr",
                "view",
                &pr_s,
                "--json",
                openwiz_adapter_github::tickets::PR_FIELDS,
            ],
            serde_json::to_vec(&json!({
                "baseRefName": "main",
                "closingIssuesReferences": [{
                    "id": format!("I_ticket_{ticket_num}"),
                    "number": ticket_num,
                    "repository": {"id": "R1", "name": "synthetic-repo", "owner": {"id": "O1", "login": "synthetic-owner"}},
                    "url": format!("{REPO_URL}/issues/{ticket_num}")
                }],
                "headRefName": format!("room/syn-{ticket_num}"),
                "headRefOid": head,
                "isDraft": false,
                "mergeCommit": null,
                "mergedAt": null,
                "number": pr_num,
                "state": "OPEN"
            }))
            .unwrap(),
        );
    }

    Fixture {
        answers,
        calls: Arc::new(AtomicUsize::new(0)),
    }
}

fn time_median(mut f: impl FnMut() -> usize) -> (u128, u128, u128, usize) {
    let warm = Instant::now();
    let mut last = 0usize;
    while warm.elapsed() < Duration::from_millis(30) {
        last = black_box(f());
    }
    let mut samples = Vec::with_capacity(11);
    for _ in 0..11 {
        let t0 = Instant::now();
        last = black_box(f());
        samples.push(t0.elapsed().as_nanos());
    }
    samples.sort_unstable();
    (samples[5], samples[0], samples[10], last)
}

fn bench_full_tick(name: &str, fixture: &Fixture) {
    let (gh, calls) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    calls.store(0, Ordering::Relaxed);
    let inv = Inventory::read(&gh, deadline).expect("inventory");
    let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
    let plan = tick::plan(&world.snapshot, &world.rules, NOW_MS).expect("plan");
    let encoded = serde_json::to_vec(&plan).expect("encode");
    let digest = sha256_hex(&encoded);
    let call_count = calls.load(Ordering::Relaxed);

    let (med, min, max, bytes) = time_median(|| {
        let inv = Inventory::read(&gh, deadline).expect("inventory");
        let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
        let plan = tick::plan(&world.snapshot, &world.rules, NOW_MS).expect("plan");
        serde_json::to_vec(&plan).expect("encode").len()
    });
    println!(
        "{name:<24} median={med:>10} ns  min={min:>10}  max={max:>10}  gh_calls={call_count:>4}  plan_bytes={bytes:>6}  sha256={}",
        &digest[..16]
    );
}

fn bench_pull_requests(name: &str, fixture: &Fixture) {
    let (gh, _) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    let pr_json_len = fixture
        .answers
        .get(&vec![
            "pr".to_owned(),
            "list".to_owned(),
            "--state".to_owned(),
            "all".to_owned(),
            "--limit".to_owned(),
            "1000".to_owned(),
            "--json".to_owned(),
            openwiz_adapter_github::fleets::PR_FIELDS.to_owned(),
        ])
        .map_or(0, Vec::len);
    let (med, min, max, rows) = time_median(|| gh.pull_requests(deadline).expect("prs").rows.len());
    let mib_s = (pr_json_len as f64 / (1024.0 * 1024.0)) / (med as f64 / 1e9);
    println!(
        "{name:<24} median={med:>10} ns  min={min:>10}  max={max:>10}  rows={rows:>4}  bytes={pr_json_len:>7}  throughput={mib_s:.2} MiB/s"
    );
}

fn bench_inventory_only(name: &str, fixture: &Fixture) {
    let (gh, _) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    let (med, min, max, empty) = time_median(|| {
        let inv = Inventory::read(&gh, deadline).expect("inventory");
        usize::from(!inv.is_empty())
    });
    println!("{name:<26} median={med:>10} ns  min={min:>10}  max={max:>10}  nonempty={empty}");
}

fn bench_world_only(name: &str, fixture: &Fixture) {
    let (gh, _) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    let (med, min, max, fleets) = time_median(|| {
        let inv = Inventory::read(&gh, deadline).expect("inventory");
        let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
        world.issues.len()
    });
    println!("{name:<26} median={med:>10} ns  min={min:>10}  max={max:>10}  issues={fleets:>4}");
}

fn bench_world_stage(name: &str, fixture: &Fixture) {
    let (gh, _) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    let mut samples = Vec::with_capacity(11);
    let mut actions = 0usize;
    let warm = Instant::now();
    while warm.elapsed() < Duration::from_millis(30) {
        let inv = Inventory::read(&gh, deadline).expect("inventory");
        let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
        actions = black_box(world.issues.len());
    }
    for _ in 0..11 {
        let inv = Inventory::read(&gh, deadline).expect("inventory");
        let t0 = Instant::now();
        let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
        samples.push(t0.elapsed().as_nanos());
        actions = black_box(world.issues.len());
    }
    samples.sort_unstable();
    let (med, min, max) = (samples[5], samples[0], samples[10]);
    println!("{name:<26} median={med:>10} ns  min={min:>10}  max={max:>10}  issues={actions:>4}");
}

fn bench_plan_only(name: &str, fixture: &Fixture) {
    let (gh, _) = fixture.executor();
    let deadline = Instant::now() + Duration::from_secs(600);
    let inv = Inventory::read(&gh, deadline).expect("inventory");
    let world = World::read(&gh, None, Path::new(""), deadline, inv).expect("world");
    let (med, min, max, actions) = time_median(|| {
        tick::plan(&world.snapshot, &world.rules, NOW_MS)
            .expect("plan")
            .actions
            .len()
    });
    println!("{name:<26} median={med:>10} ns  min={min:>10}  max={max:>10}  actions={actions:>4}");
}

fn main() {
    let _ = &Fixture::executor;
    let small = build_fixture(5, 10, 100);
    let medium = build_fixture(20, 25, 500);
    let large = build_fixture(20, 25, 700);
    let big_fleet = build_fixture(1, 160, 750);
    let _ = small.calls.load(Ordering::Relaxed);

    bench_full_tick("tick_5x10_100m", &small);
    bench_full_tick("tick_20x25_500m", &medium);
    bench_full_tick("tick_20x25_700m", &large);
    bench_full_tick("tick_1x160_750m", &big_fleet);
    bench_inventory_only("inventory_20x25_700m", &large);
    bench_world_stage("world_stage_20x25_700m", &large);
    bench_world_stage("world_stage_1x160_750m", &big_fleet);
    bench_plan_only("plan_only_20x25_700m", &large);
    bench_pull_requests("pull_requests_990", &large);
    let _ = bench_world_only as fn(&str, &Fixture);
}
