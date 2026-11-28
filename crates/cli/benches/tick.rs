use std::collections::HashMap;
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::TickReads;
use openwiz_cli::fleet::tick::{Inventory, World};
use openwiz_core::messaging::sha256_hex;
use openwiz_core::source::SourceError;
use serde_json::{Value, json};

const REPO: &str = "synthetic/example";
const URL: &str = "https://github.invalid/synthetic/example";
const NOW: u64 = 1_793_400_000_000;
const RULES: &str = "## Builder\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude Code | `--provider claude-code` |\n| Model | Opus | `--model claude-opus-5-5` |\n| Effort | XHigh | `--reasoning-level xhigh` |\n## Reviewer\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Sol | `--model gpt-6.1-sol` |\n| Effort | High | `--reasoning-level high` |\n## CI checks\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `rust` | tests | `main` |\n## Standing merge rules\n| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| A ticket in an approved plan graph | its reviewer | The loop, as soon as the reviewer's APPROVE names that exact commit and CI is green |\n\n## Builder for small tickets\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Sol | `--model gpt-6.1-sol` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer for Claude-built\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Sol | `--model gpt-6.1-sol` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer for GPT-built\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude | `--provider claude-code` |\n| Model | Opus | `--model claude-opus-5-5` |\n| Effort | High | `--reasoning-level high` |\n## GitHub identity\n| Setting | Value |\n| --- | --- |\n| Record authors | `openwiz[bot]`, `syn-owner` |\n";

struct Ticket {
    number: u64,
    title: String,
    body: String,
    blockers: Vec<u64>,
}

struct Pr {
    number: u64,
    ticket: u64,
    head: String,
}

fn link(n: u64) -> Value {
    json!({"id": format!("syn-issue-{n}"), "number": n, "state": "OPEN", "title": "Synthetic", "url": format!("https://example.invalid/issues/{n}")})
}

fn closing(n: u64) -> Value {
    json!([{"id": format!("syn-issue-{n}"), "number": n, "repository": {"id": "syn-repo", "name": "example", "owner": {"id": "syn-owner", "login": "synthetic"}}, "url": format!("{URL}/issues/{n}")}])
}

fn issue(n: u64, title: &str, body: &str, subs: &[u64], blockers: &[u64], label: bool) -> Value {
    let labels = if label {
        json!([{"id": "syn-label-ready-for-agent", "name": "ready-for-agent", "description": "Synthetic", "color": "ffffff"}])
    } else {
        json!([])
    };
    json!({
        "blockedBy": {"nodes": blockers.iter().map(|&b| link(b)).collect::<Vec<_>>(), "totalCount": blockers.len()},
        "body": body, "id": format!("syn-issue-{n}"), "labels": labels, "milestone": null, "number": n,
        "state": "OPEN", "subIssues": {"nodes": subs.iter().map(|&s| link(s)).collect::<Vec<_>>(), "totalCount": subs.len()},
        "title": title
    })
}

fn body_hash(body: &str) -> String {
    sha256_hex(format!("{}\n", body.replace("\n- [x] ", "\n- [ ] ")).as_bytes())
}

fn approval(spec: u64, spec_body: &str, tickets: &[Ticket]) -> String {
    let mut revision = format!(
        "plan-graph revision v2\nspec #{spec} body sha256 {}\n",
        body_hash(spec_body)
    );
    let mut rows = String::new();
    for t in tickets {
        let blocked = |sep: &str| {
            if t.blockers.is_empty() {
                "none".to_owned()
            } else {
                t.blockers
                    .iter()
                    .map(|b| format!("#{b}"))
                    .collect::<Vec<_>>()
                    .join(sep)
            }
        };
        revision.push_str(&format!(
            "ticket #{} blocked-by {} body sha256 {} title {}\n",
            t.number,
            blocked(" "),
            body_hash(&t.body),
            t.title
        ));
        rows.push_str(&format!(
            "| #{} | {} | {} | ready-for-agent |\n",
            t.number,
            t.title,
            blocked(", ")
        ));
    }
    format!(
        "**Plan graph approved by Jake, 2026-10-30, revision 1:** \"approved\"\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n{rows}\nFingerprint: `{}`\n\n```text\n{revision}```\n",
        sha256_hex(revision.as_bytes())
    )
}

fn world(fleets: u64, tickets_per_fleet: u64) -> Vec<(String, String)> {
    let mut issues = vec![];
    let mut prs = vec![];
    let mut comments: Vec<(u64, Value)> = vec![];
    let mut id = 5000;
    let mut comment = |issue: u64, body: String, at: u64, out: &mut Vec<(u64, Value)>| {
        id += 1;
        out.push((issue, json!({"body": body, "created": at, "id": id, "updated": at, "issue_url": format!("https://github.invalid/api/v3/repos/{REPO}/issues/{issue}"), "author": "openwiz[bot]"})));
    };
    for f in 0..fleets {
        let spec = 9 + f * 1000;
        let mut tickets = vec![];
        for i in 0..tickets_per_fleet {
            let number = spec + 1 + i;
            let body = format!(
                "## What to build\n\n{}\n## Acceptance criteria\n\n- [ ] first check\n- [x] second check\n\n**Owned paths:** `crates/example/f{f}_t{i}.rs`\n**Relies on:** nothing",
                format!("Synthetic work item line {i} for ticket {number}.\n").repeat(12)
            );
            for k in 0..3 {
                comment(
                    number,
                    format!(
                        "<!-- openwiz:status v1 -->\nagent: builder\nstate: working\nstep: synthetic step {k}"
                    ),
                    NOW + k,
                    &mut comments,
                );
            }
            if i % 3 == 0 {
                let pr = Pr {
                    number: spec + 500 + i,
                    ticket: number,
                    head: sha256_hex(format!("head {spec} {i}").as_bytes())[..40].to_owned(),
                };
                if i % 6 == 0 {
                    comment(
                        pr.number,
                        format!(
                            "VERDICT: APPROVE at {}\n\n- **R1 [nit]** synthetic finding text",
                            pr.head
                        ),
                        NOW + 10,
                        &mut comments,
                    );
                }
                prs.push(pr);
            }
            tickets.push(Ticket {
                number,
                title: format!("Synthetic ticket {number}"),
                body,
                blockers: if i % 3 == 2 { vec![number - 1] } else { vec![] },
            });
        }
        let spec_body = format!("Synthetic graph {spec}");
        comment(
            spec,
            approval(spec, &spec_body, &tickets),
            NOW,
            &mut comments,
        );
        issues.push(issue(
            spec,
            &format!("Synthetic graph {spec}"),
            &spec_body,
            &tickets.iter().map(|t| t.number).collect::<Vec<_>>(),
            &[],
            false,
        ));
        issues.extend(
            tickets
                .iter()
                .map(|t| issue(t.number, &t.title, &t.body, &[], &t.blockers, true)),
        );
    }
    let base = "b".repeat(40);
    let mut answers = vec![
        ("repo view defaultBranchRef,nameWithOwner,url".to_owned(), json!({"defaultBranchRef": {"name": "main"}, "nameWithOwner": REPO, "url": URL}).to_string()),
        ("repo view nameWithOwner,isPrivate".to_owned(), json!({"nameWithOwner": REPO, "isPrivate": true}).to_string()),
        ("issue list".to_owned(), Value::Array(issues).to_string()),
        ("git/ref/heads/main".to_owned(), json!({"sha": base}).to_string()),
        ("contents/docs/agents/fleet.md".to_owned(), RULES.to_owned()),
        ("pr list".to_owned(), Value::Array(prs.iter().map(|p| json!({
            "baseRefName": "main", "closingIssuesReferences": closing(p.ticket), "headRefName": format!("synthetic-branch-{}", p.ticket),
            "headRefOid": p.head, "isDraft": false, "mergeCommit": null, "mergedAt": null, "number": p.number, "state": "OPEN",
            "title": format!("Synthetic PR {}", p.number)
        })).collect()).to_string()),
    ];
    let rows = comments.into_iter().map(|(_, c)| c).collect::<Vec<_>>();
    let pages = rows.len() / 100 + 1;
    for page in 0..pages {
        let end = ((page + 1) * 100).min(rows.len());
        answers.push((
            format!("issues/comments?per_page=100&page={}", page + 1),
            Value::Array(rows[page * 100..end].to_vec()).to_string(),
        ));
    }
    for p in &prs {
        let h = &p.head;
        answers.push((
            format!("commits/{h}"),
            json!({"sha": h, "subject": "Synthetic green"}).to_string(),
        ));
        answers.push((format!("actions/runs?head_sha={h}&per_page=100"), json!({"total_count": 1, "runs": [{"id": p.number, "head_sha": h, "event": "pull_request", "run_attempt": 1, "updated": NOW + 10_000, "prs": [{"number": p.number, "head": h, "base": base}]}]}).to_string()));
        answers.push((format!("actions/runs/{}/jobs?filter=latest&per_page=100", p.number), json!({"total_count": 1, "jobs": [{"id": p.number * 10, "name": "rust", "status": "completed", "conclusion": "success", "head_sha": h, "run_id": p.number}]}).to_string()));
        answers.push((
            format!("pr checks {}", p.number),
            json!([{"bucket": "pass", "name": "rust"}]).to_string(),
        ));
        answers.push((format!("pr view {}", p.number), json!({
            "baseRefName": "main", "closingIssuesReferences": closing(p.ticket), "headRefName": format!("synthetic-branch-{}", p.ticket),
            "headRefOid": h, "isDraft": false, "mergeCommit": null, "mergedAt": null, "number": p.number, "state": "OPEN"
        }).to_string()));
    }
    answers
}

fn key(argv: &[String]) -> String {
    match argv.first().map(String::as_str) {
        Some("api") => argv[1]
            .trim_start_matches("repos/{owner}/{repo}/")
            .split("?ref=")
            .next()
            .unwrap_or("")
            .to_owned(),
        Some("repo") => format!("repo view {}", argv.get(3).map_or("", String::as_str)),
        Some("issue") => "issue list".to_owned(),
        Some("pr") if argv.get(1).is_some_and(|a| a == "list") => "pr list".to_owned(),
        _ => argv.iter().take(3).cloned().collect::<Vec<_>>().join(" "),
    }
}

fn median_ns(mut call: impl FnMut()) -> u128 {
    let mut iters = 1u32;
    loop {
        let start = Instant::now();
        for _ in 0..iters {
            call();
        }
        if start.elapsed() >= Duration::from_millis(30) || iters >= 20_000 {
            let mut samples = Vec::with_capacity(11);
            for _ in 0..11 {
                let start = Instant::now();
                for _ in 0..iters {
                    call();
                }
                samples.push(start.elapsed().as_nanos() / u128::from(iters));
            }
            samples.sort_unstable();
            break samples[5];
        }
        iters = iters.saturating_mul(2);
    }
}

fn bench(fleets: u64, tickets: u64) {
    let answers = Arc::new(
        world(fleets, tickets)
            .into_iter()
            .collect::<HashMap<_, _>>(),
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let (a, n) = (answers.clone(), calls.clone());
    let gh = TickReads::with_executor(Executor::supplied(Arc::new(move |call, _| {
        n.fetch_add(1, Ordering::Relaxed);
        a.get(&key(call.argv()))
            .map(|s| s.clone().into_bytes())
            .ok_or_else(|| SourceError::Unavailable {
                detail: format!("no synthetic answer for {:?}", call.argv()),
            })
    })));
    let state = std::env::temp_dir().join("openwiz-tick-bench-absent-state");
    let tick = || {
        let deadline = Instant::now() + Duration::from_secs(600);
        let inventory = Inventory::read(&gh, deadline).unwrap();
        let world = World::read(&gh, None, &state, deadline, inventory).unwrap();
        let plan = openwiz_core::fleet::tick::plan(&world.snapshot, &world.rules, NOW / 1000 + 100)
            .unwrap();
        serde_json::to_vec(&plan).unwrap()
    };
    let bytes = tick();
    let digest = sha256_hex(&bytes);
    let plan: Value = serde_json::from_slice(&bytes).unwrap();
    let per_tick = calls.swap(0, Ordering::Relaxed);
    let actions = plan["actions"].as_array().unwrap();
    let starts = actions
        .iter()
        .filter(|a| a["kind"] == "start_builder")
        .count();
    let wakes = actions.iter().filter(|a| a["kind"] == "wake").count();
    assert!(
        starts > 0 && wakes > 0,
        "the synthetic world did not plan: {plan}"
    );
    let ns = median_ns(|| {
        black_box(tick());
    });
    println!(
        "BENCH fleet_tick_{fleets}x{tickets} gh_calls={per_tick} actions={} start_builder={starts} wake={wakes} plan_sha256={digest} median_ns={ns}",
        actions.len()
    );
}

struct Rng(u64);
impl Rng {
    fn below(&mut self, n: usize) -> usize {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        (self.0 % n.max(1) as u64) as usize
    }
}

const STRINGS: &[&str] = &[
    "",
    "é",
    "日本\u{200b}",
    "\u{1f600}",
    "0",
    "-",
    "#1",
    "thr_syn_x",
    "main",
    "VERDICT: APPROVE at ",
    "launch-fleet: held for #1: contract changed, re-approve. ",
    "a\nb",
    "\r\n",
    "x",
];

fn mutate_value(rng: &mut Rng, v: &mut Value, depth: usize) {
    let kids = match v {
        Value::Array(a) if !a.is_empty() => a.len(),
        Value::Object(o) if !o.is_empty() => o.len(),
        _ => 0,
    };
    if kids > 0 && depth < 12 && rng.below(4) != 0 {
        let k = rng.below(kids);
        match v {
            Value::Array(a) => {
                if rng.below(8) == 0 {
                    let dup = a[k].clone();
                    a.push(dup);
                } else if rng.below(8) == 0 {
                    a.remove(k);
                } else {
                    mutate_value(rng, &mut a[k], depth + 1);
                }
            }
            Value::Object(o) => {
                let key = o.keys().nth(k).unwrap().clone();
                if rng.below(10) == 0 {
                    o.remove(&key);
                } else {
                    mutate_value(rng, o.get_mut(&key).unwrap(), depth + 1);
                }
            }
            _ => {}
        }
        return;
    }
    *v = match (rng.below(9), &*v) {
        (0, _) => Value::Null,
        (1, Value::Number(n)) => {
            let x = n.as_u64().unwrap_or(0);
            serde_json::json!(
                [
                    0u64,
                    1,
                    x.wrapping_add(1),
                    x.wrapping_sub(1),
                    u64::MAX,
                    x / 2
                ][rng.below(6)]
            )
        }
        (2, _) => serde_json::json!(-1),
        (3, _) => serde_json::json!(1.5),
        (4, Value::String(s)) => {
            let mut s = s.clone();
            let at = s
                .char_indices()
                .map(|(i, _)| i)
                .nth(rng.below(s.chars().count() + 1))
                .unwrap_or(s.len());
            s.insert_str(at, STRINGS[rng.below(STRINGS.len())]);
            Value::String(s)
        }
        (5, Value::String(s)) => {
            let n = rng.below(s.chars().count() + 1);
            Value::String(s.chars().take(n).collect())
        }
        (6, _) => Value::String(STRINGS[rng.below(STRINGS.len())].to_owned()),
        (7, _) => serde_json::json!([]),
        _ => serde_json::json!({}),
    };
}

fn mutate_text(rng: &mut Rng, text: &str) -> String {
    if rng.below(3) != 0 {
        let lines = text
            .lines()
            .map(|l| match serde_json::from_str::<Value>(l) {
                Ok(mut v) => {
                    if rng.below(2) == 0 {
                        mutate_value(rng, &mut v, 0);
                    }
                    serde_json::to_string(&v).unwrap()
                }
                Err(_) => l.to_owned(),
            })
            .collect::<Vec<_>>();
        return lines.join("\n") + if text.ends_with('\n') { "\n" } else { "" };
    }
    let mut chars = text.chars().collect::<Vec<_>>();
    let at = rng.below(chars.len() + 1);
    match rng.below(4) {
        0 => chars
            .splice(at..at, STRINGS[rng.below(STRINGS.len())].chars())
            .for_each(drop),
        1 if at < chars.len() => {
            chars.remove(at);
        }
        2 => chars.truncate(at),
        _ => {
            let end = (at + rng.below(30)).min(chars.len());
            let copy = chars[at.min(end)..end].to_vec();
            chars.splice(at..at, copy).for_each(drop);
        }
    }
    chars.into_iter().collect()
}

fn fuzz(seconds: u64, seed: u64) {
    let base = world(4, 5);
    let mut rng = Rng(seed);
    let panics: Arc<Mutex<Vec<String>>> = Arc::default();
    let sink = panics.clone();
    std::panic::set_hook(Box::new(move |info| {
        sink.lock().unwrap().push(format!("{info}"))
    }));
    let state = std::env::temp_dir().join("openwiz-tick-bench-absent-state");
    let started = Instant::now();
    let mut cases = 0u64;
    let mut planned = 0u64;
    while started.elapsed() < Duration::from_secs(seconds) {
        let mut answers = base.iter().cloned().collect::<HashMap<_, _>>();
        let mut changed = vec![];
        for _ in 0..1 + rng.below(3) {
            let (k, _) = &base[rng.below(base.len())];
            let text = mutate_text(&mut rng, &answers[k]);
            answers.insert(k.clone(), text.clone());
            changed.push((k.clone(), text));
        }
        let answers = Arc::new(answers);
        let gh = TickReads::with_executor(Executor::supplied(Arc::new(move |call, _| {
            answers
                .get(&key(call.argv()))
                .map(|s| s.clone().into_bytes())
                .ok_or_else(|| SourceError::Unavailable {
                    detail: "no synthetic answer".to_owned(),
                })
        })));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let deadline = Instant::now() + Duration::from_secs(60);
            let inventory = Inventory::read(&gh, deadline)?;
            let world = World::read(&gh, None, &state, deadline, inventory)?;
            let plan =
                openwiz_core::fleet::tick::plan(&world.snapshot, &world.rules, NOW / 1000 + 100)
                    .map_err(|_| "plan unavailable")?;
            serde_json::to_vec(&plan).map_err(|_| "plan encoding failed")
        }));
        cases += 1;
        planned += u64::from(matches!(result, Ok(Ok(_))));
        let caught = std::mem::take(&mut *panics.lock().unwrap());
        assert!(
            caught.is_empty() && result.is_ok(),
            "the tick panicked on {changed:?}: {caught:?}"
        );
    }
    println!(
        "FUZZ fleet_tick_4x5 cases={cases} planned={planned} panics=0 seconds={seconds} seed={seed}"
    );
}

fn main() {
    if let Some(seconds) = std::env::var("OPENWIZ_TICK_FUZZ_SECONDS")
        .ok()
        .and_then(|s| s.parse().ok())
    {
        let seed = std::env::var("OPENWIZ_TICK_FUZZ_SEED")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0x9e37_79b9_7f4a_7c15);
        return fuzz(seconds, seed);
    }
    bench(5, 10);
    bench(20, 25);
}
