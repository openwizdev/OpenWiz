use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use openwiz_adapter_github::allowlist::Invocation;
use openwiz_adapter_github::decisions;
use openwiz_adapter_github::fleets::{self as gh_fleets, GitHubFleets};
use openwiz_adapter_github::plan as gh_plan;
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::{self as gh_tick, TickReads};
use openwiz_adapter_github::tickets::{self as gh_tickets, RecordAuthors};
use openwiz_cli::fleet::tick::{Inventory, World};
use openwiz_core::fleet::fleets::{
    FleetsSource, IssueRow, Link as FleetLink, Links, Listed, PrFacts, PrRow, StockPr, fleets,
    pending_question, template_line, verdict,
};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Failed, Issue, IssueState, MergedPr, Milestone, NonEmpty, Number,
    PrFields, Repository,
};
use openwiz_core::fleet::starts;
use openwiz_core::fleet::tick::{
    Agent, Approval, BlockerInput, BuilderFamily, BuilderSource, ChangedFile, CheckRun,
    ContractChange, Fingerprint, FleetFacts, FleetInput, Hold, MergeFact, MergeInput, Observed,
    OpenPr, PlanApproval, PrInput, PrRecords, Ready, ReportComment, Reviewer, Rules, Snapshot,
    SpecRecords, Start, StartReason, StartState, TicketFacts, TicketInput, TicketRecords, plan,
};
use openwiz_core::messaging::{OpId, sha256_hex};
use openwiz_core::model::{Fact, Timestamp};
use openwiz_core::models::{self, SpawnFlags};
use openwiz_core::new_thread::read::StrictJson;
use openwiz_core::new_thread::record::NewThreadRecord;
use openwiz_core::ops::Clock;
use openwiz_core::source::SourceError;
use serde_json::{Map, Value, json};

const FLEET_MD: &str = include_str!("../../docs/agents/fleet.md");

struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Self(if seed == 0 {
            0x9e37_79b9_7f4a_7c15
        } else {
            seed
        })
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }

    fn usize(&mut self, bound: usize) -> usize {
        if bound == 0 {
            0
        } else {
            (self.next_u64() as usize) % bound
        }
    }

    fn bool(&mut self) -> bool {
        (self.next_u64() & 1) == 1
    }

    fn pick<'a, T>(&mut self, slice: &'a [T]) -> &'a T {
        &slice[self.usize(slice.len())]
    }
}

fn flags() -> SpawnFlags {
    SpawnFlags {
        provider: "--provider".to_owned(),
        model: "--model".to_owned(),
        effort: "--reasoning-level".to_owned(),
    }
}

fn num(n: u64) -> Number {
    Number::new(n.max(1)).unwrap()
}

fn ne(s: &str) -> NonEmpty {
    NonEmpty::new(s).unwrap()
}

fn commit(seed: u64) -> Commit {
    Commit::parse(&format!("{seed:040x}")).unwrap()
}

fn static_exec(bytes: Vec<u8>) -> Executor {
    let bytes = Arc::new(bytes);
    Executor::supplied(Arc::new(move |_: &Invocation, _: Instant| {
        Ok((*bytes).clone())
    }))
}

const EDGE_STRINGS: &[&str] = &[
    "",
    "0",
    "01",
    "1",
    "99999999999999999999",
    "OPEN",
    "CLOSED",
    "MERGED",
    "main",
    "release-0.2.0",
    "-bad",
    "a..b",
    "a//b",
    "pass",
    "fail",
    "pending",
    "skipping",
    "cancel",
    "ahead",
    "identical",
    "behind",
    "diverged",
    "IDENTICAL",
    "BEHIND",
    "AHEAD",
    "DIVERGED",
    "ready-for-agent",
    "ready-for-human",
    "needs-info",
    "held",
    "polish",
    "VERDICT: APPROVE at 0000000000000000000000000000000000000001",
    "VERDICT: CHANGES at 0000000000000000000000000000000000000001\n- **R1 [high]** disputed, kept: x\n- **R2 [low]** still open after 2 rounds: y",
    "2026-10-30T18:30:00Z",
    "1970-01-01T00:00:00Z",
    "1969-12-31T23:59:59Z",
    "0000-01-01T00:00:00Z",
    "9999-12-31T23:59:59Z",
    "2024-02-29T23:59:59Z",
    "2025-02-29T00:00:00Z",
    "éé-é-éTé:é:éZ",
    "€a-01-01T00:00:00Z",
    "2026-01-01T00:00:€Z",
    "synthetic/example",
    "https://github.com/synthetic/example",
    "https://example.invalid/synthetic/example/issues/1",
    "https://api.github.com/repos/synthetic/example/issues/1",
    "0000000000000000000000000000000000000001",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "launch-fleet: archived",
    "launch-fleet: started, thread thr_syn_1",
    "launch-fleet: start checked, branch room/syn-1",
    "launch-fleet: held for #1: contract changed, re-approve. a.rs changed in #1.",
    "launch-fleet: review started 0000000000000000000000000000000000000001, thread thr_syn_2",
    "launch-fleet: re-check sent 0000000000000000000000000000000000000001, thread thr_syn_2",
    "launch-fleet: builder fallback due, thread thr_syn_1, branch room/syn-1\nReplacement: thr_syn_2",
    "thr_syn_1",
    "***",
    "a/*b*c*/d",
    "crates/core/",
    "\0\r\n\t",
    "😀é€漢",
    "gh version 2.100.0 (2026-09-03)\n",
];

const EDGE_KEYS: &[&str] = &[
    "id",
    "number",
    "title",
    "body",
    "state",
    "url",
    "labels",
    "milestone",
    "blockedBy",
    "subIssues",
    "nodes",
    "totalCount",
    "pageInfo",
    "hasNextPage",
    "endCursor",
    "baseRefName",
    "headRefName",
    "headRefOid",
    "isDraft",
    "mergeCommit",
    "mergedAt",
    "oid",
    "closingIssuesReferences",
    "closedByPullRequestsReferences",
    "repository",
    "name",
    "owner",
    "login",
    "nameWithOwner",
    "defaultBranchRef",
    "isPrivate",
    "bucket",
    "status",
    "behind_by",
    "ahead_by",
    "data",
    "errors",
    "path",
    "previous",
    "author",
    "created",
    "updated",
    "issue_url",
    "event",
    "label",
    "at",
    "sha",
    "subject",
    "total_count",
    "runs",
    "jobs",
    "head_sha",
    "run_attempt",
    "prs",
    "head",
    "base",
    "conclusion",
    "run_id",
    "comments",
    "createdAt",
    "authorAssociation",
    "includesCreatedEdit",
    "isMinimized",
    "minimizedReason",
    "reactionGroups",
    "viewerDidAuthor",
    "type",
    "schema",
    "op_id",
    "key",
    "project_id",
    "settings",
    "attempts",
    "kind",
    "r0",
    "r1",
    "target",
    "comparison",
    "aheadBy",
    "behindBy",
    "baseTarget",
    "headTarget",
    "parent",
    "extra_key",
    "",
];

fn gen_string(rng: &mut Rng) -> String {
    match rng.usize(5) {
        0..=2 => (*rng.pick(EDGE_STRINGS)).to_owned(),
        3 => {
            let a = *rng.pick(EDGE_STRINGS);
            let b = *rng.pick(EDGE_STRINGS);
            let sep = *rng.pick(&["", " ", "\n", "/", ".", ":", " | ", "`", "*"]);
            format!("{a}{sep}{b}")
        }
        _ => {
            let len = rng.usize(48);
            let mut s = String::with_capacity(len);
            for _ in 0..len {
                let c = match rng.usize(10) {
                    0 => 'é',
                    1 => '€',
                    2 => '😀',
                    3 => '\0',
                    4 => '\n',
                    5 => '|',
                    6 => '`',
                    7 => '"',
                    8 => '\\',
                    _ => (b' ' + (rng.usize(95) as u8)) as char,
                };
                s.push(c);
            }
            s
        }
    }
}

fn gen_json_value(rng: &mut Rng, depth: usize) -> Value {
    let kind = if depth == 0 {
        rng.usize(5)
    } else {
        rng.usize(8)
    };
    match kind {
        0 => Value::Null,
        1 => Value::Bool(rng.bool()),
        2 => match rng.usize(8) {
            0 => json!(0),
            1 => json!(1),
            2 => json!(-1),
            3 => json!(i64::MIN),
            4 => json!(i64::MAX),
            5 => json!(u64::MAX),
            6 => json!(1.5),
            _ => json!(rng.next_u64() % 1000),
        },
        3 | 4 => Value::String(gen_string(rng)),
        5 => {
            let len = rng.usize(5);
            let mut arr = Vec::with_capacity(len);
            for _ in 0..len {
                arr.push(gen_json_value(rng, depth - 1));
            }
            Value::Array(arr)
        }
        _ => {
            let len = rng.usize(7);
            let mut map = Map::new();
            for _ in 0..len {
                let k = if rng.usize(4) == 0 {
                    gen_string(rng)
                } else {
                    (*rng.pick(EDGE_KEYS)).to_owned()
                };
                map.insert(k, gen_json_value(rng, depth - 1));
            }
            Value::Object(map)
        }
    }
}

fn mutate_bytes(rng: &mut Rng, seed: &[u8]) -> Vec<u8> {
    let mut buf = seed.to_vec();
    let ops = 1 + rng.usize(5);
    for _ in 0..ops {
        if buf.len() > 8192 {
            let new_len = rng.usize(2048);
            buf.truncate(new_len);
        }
        match rng.usize(10) {
            0 if !buf.is_empty() => {
                let i = rng.usize(buf.len());
                buf[i] ^= 1 << rng.usize(8);
            }
            1 if !buf.is_empty() => {
                let i = rng.usize(buf.len());
                buf[i] = (rng.next_u64() & 0xff) as u8;
            }
            2 if !buf.is_empty() => {
                let i = rng.usize(buf.len());
                let n = 1 + rng.usize(buf.len().min(32));
                let end = (i + n).min(buf.len());
                buf.drain(i..end);
            }
            3 => {
                let i = rng.usize(buf.len() + 1);
                let piece = (*rng.pick(EDGE_STRINGS)).as_bytes();
                buf.splice(i..i, piece.iter().copied());
            }
            4 => {
                let i = rng.usize(buf.len() + 1);
                let token = *rng.pick(&[
                    b"\"a\":1,\"a\":2".as_slice(),
                    b"[[[[[[[[[[[[[[[[".as_slice(),
                    b"{{{{{{{{{{{{{{{{".as_slice(),
                    b"1e309".as_slice(),
                    b"-0.0".as_slice(),
                    b"18446744073709551616".as_slice(),
                    b"\\uD800".as_slice(),
                    b"\xff\xfe\x00".as_slice(),
                    b"\r\n\r\n".as_slice(),
                    b"null".as_slice(),
                ]);
                buf.splice(i..i, token.iter().copied());
            }
            5 if buf.len() >= 4 => {
                let a = rng.usize(buf.len());
                let len = 1 + rng.usize((buf.len() - a).min(64));
                let chunk = buf[a..a + len].to_vec();
                let b = rng.usize(buf.len() + 1);
                buf.splice(b..b, chunk);
            }
            6 => {
                let i = rng.usize(buf.len() + 1);
                buf.insert(i, *rng.pick(b"{}[]\":,\n|`"));
            }
            7 if !buf.is_empty() => {
                let i = rng.usize(buf.len());
                buf.truncate(i);
            }
            8 => {
                let v = gen_json_value(rng, 3);
                buf = serde_json::to_vec(&v).unwrap();
            }
            _ => {
                let i = rng.usize(buf.len() + 1);
                let extra = format!("\"{}\":", *rng.pick(EDGE_KEYS));
                buf.splice(i..i, extra.bytes());
            }
        }
    }
    buf
}

fn corpus() -> Vec<Vec<u8>> {
    let head = "1".repeat(40);
    let merge = "2".repeat(40);
    vec![
        b"".to_vec(),
        b"{}".to_vec(),
        b"[]".to_vec(),
        b"null".to_vec(),
        b"{\"a\":1,\"a\":2}".to_vec(),
        b"gh version 2.100.0 (2026-09-03)\n".to_vec(),
        serde_json::to_vec(&json!({
            "defaultBranchRef": {"name": "main"},
            "nameWithOwner": "synthetic/example",
            "url": "https://github.com/synthetic/example"
        }))
        .unwrap(),
        serde_json::to_vec(&json!({
            "nameWithOwner": "synthetic/example",
            "url": "https://github.com/synthetic/example"
        }))
        .unwrap(),
        serde_json::to_vec(&json!({
            "nameWithOwner": "synthetic/example"
        }))
        .unwrap(),
        serde_json::to_vec(&json!([{
            "baseRefName": "main",
            "closingIssuesReferences": [{
                "id": "I_syn_1",
                "number": 1,
                "repository": {
                    "id": "R_syn_1",
                    "name": "example",
                    "owner": {"id": "O_syn_1", "login": "synthetic"}
                },
                "url": "https://github.com/synthetic/example/issues/1"
            }],
            "headRefName": "room/syn-1",
            "headRefOid": head,
            "isDraft": false,
            "mergeCommit": {"oid": merge},
            "mergedAt": "2026-10-30T18:30:00Z",
            "number": 10,
            "state": "MERGED",
            "title": "#1: Synthetic PR"
        }]))
        .unwrap(),
        serde_json::to_vec(&json!([{
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": "Ticket 1\n**Owned paths:** `crates/core/src/lib.rs`\n**Relies on:** `contracts/open-development.v1.md`\n",
            "id": "I_syn_1",
            "labels": [{"color": "0e8a16", "description": "Ready", "id": "L_1", "name": "ready-for-agent"}],
            "milestone": {"description": "Syn", "dueOn": null, "number": 1, "title": "0.2.0"},
            "number": 1,
            "state": "OPEN",
            "subIssues": {"nodes": [], "totalCount": 0},
            "title": "Synthetic ticket 1"
        }]))
        .unwrap(),
        serde_json::to_vec(&json!({
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": "Body",
            "closedByPullRequestsReferences": [],
            "comments": [{
                "id": "C_1",
                "author": {"login": "synthetic"},
                "authorAssociation": "OWNER",
                "body": "Question?",
                "createdAt": "2026-10-30T18:30:00Z",
                "includesCreatedEdit": false,
                "isMinimized": false,
                "minimizedReason": null,
                "reactionGroups": [],
                "url": "https://github.com/synthetic/example/issues/1#issuecomment-1",
                "viewerDidAuthor": false
            }],
            "labels": [],
            "milestone": null,
            "state": "OPEN",
            "subIssues": {"nodes": [], "totalCount": 0},
            "title": "Synthetic"
        }))
        .unwrap(),
        serde_json::to_vec(&json!([{"bucket": "pass", "name": "ci"}])).unwrap(),
        serde_json::to_vec(&json!({"status": "identical", "behind_by": 0})).unwrap(),
        serde_json::to_vec(&json!({"ahead_by": 0})).unwrap(),
        serde_json::to_vec(&json!({
            "data": {
                "repository": {
                    "r0": {
                        "target": {"oid": merge},
                        "comparison": {
                            "status": "IDENTICAL",
                            "aheadBy": 0,
                            "behindBy": 0,
                            "baseTarget": {"oid": merge},
                            "headTarget": {"oid": merge}
                        }
                    }
                }
            }
        }))
        .unwrap(),
        serde_json::to_vec(&json!([{
            "id": 1,
            "author": "jparker2006",
            "body": "launch-fleet: archived",
            "created": 1_793_385_000_000_u64,
            "updated": 1_793_385_000_000_u64
        }]))
        .unwrap(),
        serde_json::to_vec(&json!([{
            "id": 1,
            "event": "labeled",
            "label": "held",
            "body": null,
            "at": 1_793_385_000_000_u64
        }]))
        .unwrap(),
        serde_json::to_vec(&json!([{
            "path": "crates/core/src/lib.rs",
            "previous": null,
            "status": "modified"
        }]))
        .unwrap(),
        serde_json::to_vec(&json!({
            "total_count": 1,
            "runs": [{
                "id": 1,
                "head_sha": head,
                "event": "pull_request",
                "run_attempt": 1,
                "updated": 1_793_385_000_000_u64,
                "prs": [{"number": 10, "head": head, "base": merge}]
            }]
        }))
        .unwrap(),
        serde_json::to_vec(&json!({
            "schema": "openwiz.start-record.v1",
            "id": "op-syn-1",
            "key": {
                "repository": "synthetic/example",
                "role": "builder",
                "number": 1,
                "commit": null
            },
            "project_id": "prj_syn_1",
            "settings": {"harness": "codex", "model": "gpt-6.2-sol", "effort": "high"},
            "attempts": [{"op_id": "op-syn-1", "at": 0, "outcome": {"kind": "pending"}}]
        }))
        .unwrap(),
        serde_json::to_vec(&json!({
            "nodes": [],
            "totalCount": 0,
            "pageInfo": {"hasNextPage": false, "endCursor": null}
        }))
        .unwrap(),
    ]
}

fn fuzz_json_parsers(bytes: &[u8], rng: &mut Rng, authors: &RecordAuthors) {
    let deadline = Instant::now() + Duration::from_secs(5);
    let _ = gh_plan::strict(bytes);
    let _ = decisions::document(bytes);
    let _ = gh_tick::document(bytes);
    if let Ok(strict) = serde_json::from_slice::<StrictJson>(bytes) {
        let _ = NewThreadRecord::read(&strict);
    }
    let _ = gh_tickets::version(bytes);
    let _ = gh_tickets::repository(bytes);
    let _ = gh_tickets::issue(bytes);
    let _ = gh_tickets::pull_request(bytes);
    let _ = gh_tickets::checks(bytes);
    let _ = gh_tickets::verdict_comments(bytes);
    let _ = gh_tickets::on_base(bytes);
    let _ = gh_tickets::stock_issue(bytes, bytes, authors);

    if let Ok(s) = std::str::from_utf8(bytes) {
        let _ = openwiz_cli::state::starts::read(s);
        let _ = RecordAuthors::read(s);
        let _ = gh_fleets::is_branch(s);
        let _ = Commit::parse(s);
        let _ = starts::Repository::parse(s);
        let _ = starts::safe_id(s);
        let _ = template_line(s, "**Owned paths:**");
        let _ = template_line(s, "**Relies on:**");
        let _ = verdict(&[s.to_owned()]);
    }

    let exec = static_exec(bytes.to_vec());
    let gf = GitHubFleets::with_executor(exec.clone());
    let _ = gf.version(deadline);
    let _ = gf.repository(deadline);
    let _ = gf.issues(deadline);
    let _ = gf.stock_pull_requests(deadline);
    let _ = gf.checks(num(1), deadline);
    let _ = gf.comments(num(1), deadline);
    let merged_pr = MergedPr {
        fields: PrFields {
            number: num(1),
            draft: false,
            head_branch: ne("room/syn-1"),
            head_commit: commit(1),
            base_branch: ne("main"),
            closes: vec![num(1)],
        },
        merge_commit: commit(2),
        merged_at: Timestamp(1_793_385_000_000),
    };
    let _ = gf.on_base(&merged_pr, deadline);
    let _ = gf.on_bases(&[merged_pr], deadline);

    let tick = TickReads::with_executor(exec);
    let _ = tick.pull_requests(deadline);
    let _ = tick.repository(deadline);
    let _ = tick.branch("main", deadline);
    let _ = tick.contains(&commit(1), &commit(2), deadline);
    let _ = tick.rules(&commit(1), deadline);
    let _ = tick.comments(num(1), deadline);
    let _ = tick.events(num(1), deadline);
    let _ = tick.files(num(1), deadline);
    let _ = tick.subject(&commit(1), deadline);
    let _ = tick.checks_with_parallelism(num(10), &commit(1), deadline, 1);

    let head = format!("{:040x}", 1_u64);
    let base = format!("{:040x}", 2_u64);
    let bytes_for_checks = bytes.to_vec();
    let checks_exec = Executor::supplied(Arc::new(move |call: &Invocation, _: Instant| {
        let argv = call.argv();
        if argv
            .get(1)
            .is_some_and(|p| p.contains("actions/runs?head_sha="))
        {
            Ok(serde_json::to_vec(&json!({
                "total_count": 1,
                "runs": [{
                    "id": 7,
                    "head_sha": head,
                    "event": "pull_request",
                    "run_attempt": 1,
                    "updated": 1_793_385_000_000_u64,
                    "prs": [{"number": 10, "head": head, "base": base}]
                }]
            }))
            .unwrap())
        } else {
            Ok(bytes_for_checks.clone())
        }
    }));
    let _ = TickReads::with_executor(checks_exec).checks_with_parallelism(
        num(10),
        &commit(1),
        deadline,
        1,
    );

    let page_calls = Arc::new(AtomicUsize::new(0));
    let page_calls_ref = Arc::clone(&page_calls);
    let bytes_once = bytes.to_vec();
    let repo_exec = Executor::supplied(Arc::new(move |_: &Invocation, _: Instant| {
        if page_calls_ref.fetch_add(1, Ordering::Relaxed) == 0 {
            Ok(bytes_once.clone())
        } else {
            Ok(b"[]".to_vec())
        }
    }));
    let repo = gh_tick::Repository {
        name: "synthetic/example".to_owned(),
        url: "https://github.com/synthetic/example".to_owned(),
        default: ne("main"),
    };
    let _ =
        TickReads::with_executor(repo_exec).repository_comments_with_page_deadline(&repo, |p| {
            if p <= 2 {
                Ok(deadline)
            } else {
                Err("page cap")
            }
        });

    if let Ok(val) = serde_json::from_slice::<Value>(bytes) {
        let _ = gh_tick::repository(&val);
        let _ = gh_tick::comments(&val);
        let expired = Instant::now() - Duration::from_secs(1);
        let reader = gh_plan::Reader::new("/nonexistent-gh-fuzz");
        let _ = reader.connection(gh_plan::Request::Issues, Some(val), expired);
    }

    let dup_key = *rng.pick(EDGE_KEYS);
    if !dup_key.contains('"') && !dup_key.contains('\\') && !dup_key.contains('\n') {
        let dup = format!("{{\"{dup_key}\":1,\"{dup_key}\":2}}");
        let db = dup.as_bytes();
        assert!(
            gh_plan::strict(db).is_err(),
            "plan::strict accepted duplicate key {dup_key:?}"
        );
        assert!(
            decisions::document(db).is_none(),
            "decisions::document accepted duplicate key {dup_key:?}"
        );
        assert!(
            gh_tick::document(db).is_err(),
            "tick::document accepted duplicate key {dup_key:?}"
        );
        assert!(
            serde_json::from_slice::<StrictJson>(db).is_err(),
            "StrictJson accepted duplicate key {dup_key:?}"
        );
    }
}

fn fuzz_allowlists(rng: &mut Rng) {
    let mut owned = Vec::with_capacity(14);
    let len = rng.usize(14);
    let tokens = [
        "api",
        "graphql",
        "repo",
        "view",
        "issue",
        "list",
        "pr",
        "checks",
        "--json",
        "--jq",
        "--paginate",
        "--include",
        "--state",
        "--limit",
        "--version",
        "--header",
        "-F",
        "-f",
        "all",
        "1000",
        "1",
        "0",
        "owner={owner}",
        "name={repo}",
        "number=1",
        "cursor=abc",
        "main",
        "synthetic/example",
        "--method",
        "POST",
        "DELETE",
        "../etc/passwd",
        "repos/{owner}/{repo}/issues/1",
        "repos/{owner}/{repo}/pulls/1",
        "repos/{owner}/{repo}/compare/main...0000000000000000000000000000000000000001",
    ];
    for _ in 0..len {
        if rng.bool() {
            owned.push((*rng.pick(&tokens)).to_owned());
        } else {
            owned.push(gen_string(rng));
        }
    }
    let refs: Vec<&str> = owned.iter().map(String::as_str).collect();
    let _ = (gh_plan::ALLOWLIST.allows)(&refs);
    let _ = (decisions::ALLOWLIST.allows)(&refs);
    let _ = (gh_tick::ALLOWLIST.allows)(&refs);
    let _ = (gh_fleets::ALLOWLIST.allows)(&refs);
    let _ = (gh_tickets::ALLOWLIST.allows)(&refs);
    let _ = Invocation::new(&refs);

    let mut dangerous = refs.clone();
    dangerous.push("--method");
    dangerous.push("POST");
    assert!(Invocation::new(&dangerous).is_none());
}

fn fuzz_markdown_rules(rng: &mut Rng, f: &SpawnFlags) {
    let mut lines: Vec<String> = FLEET_MD.lines().map(str::to_owned).collect();
    let edits = 1 + rng.usize(6);
    for _ in 0..edits {
        match rng.usize(6) {
            0 if !lines.is_empty() => {
                let i = rng.usize(lines.len());
                lines.remove(i);
            }
            1 if !lines.is_empty() => {
                let i = rng.usize(lines.len());
                let dup = lines[i].clone();
                lines.insert(i, dup);
            }
            2 if !lines.is_empty() => {
                let i = rng.usize(lines.len());
                lines[i] = gen_string(rng);
            }
            3 => {
                let i = rng.usize(lines.len() + 1);
                let row = format!(
                    "| {} | {} | {} | {} | `{}` |",
                    gen_string(rng),
                    gen_string(rng),
                    gen_string(rng),
                    gen_string(rng),
                    gen_string(rng)
                );
                lines.insert(i, row);
            }
            4 => {
                let i = rng.usize(lines.len() + 1);
                let heading = *rng.pick(&[
                    "## Models",
                    "## Builder",
                    "## Builder for small tickets",
                    "## Reviewer for Claude-built",
                    "## Reviewer for GPT-built",
                    "## Fixer",
                    "## CI checks",
                    "## Standing merge rules",
                    "## GitHub identity",
                ]);
                lines.insert(i, heading.to_owned());
            }
            _ if !lines.is_empty() => {
                let i = rng.usize(lines.len());
                lines[i].push_str(&gen_string(rng));
            }
            _ => {}
        }
    }
    let text = lines.join("\n");
    let _ = models::read(&text, f);
    let _ = Rules::parse(&text, f);
    let _ = RecordAuthors::read(&text);
}

fn gen_ne(rng: &mut Rng) -> NonEmpty {
    let s = gen_string(rng);
    NonEmpty::new(&s).unwrap_or_else(|| ne("syn"))
}

fn gen_snapshot(rng: &mut Rng) -> Snapshot {
    let default_branch = match rng.usize(5) {
        0 => Observed::Unread(vec![]),
        1 => Observed::Complete(ne("release-0.2.0")),
        2 => Observed::Complete(gen_ne(rng)),
        _ => Observed::Complete(ne("main")),
    };
    let spec_count = rng.usize(4);
    let mut fleets_vec = Vec::with_capacity(spec_count);
    let mut next_id = 1_u64;
    for s in 0..spec_count {
        let spec = if rng.usize(8) == 0 {
            num(1)
        } else {
            let n = next_id;
            next_id += 1;
            num(n)
        };
        if rng.usize(6) == 0 {
            fleets_vec.push(FleetInput {
                spec,
                facts: Observed::Unread(vec![]),
            });
            continue;
        }
        let ticket_count = rng.usize(8);
        let mut tickets = Vec::with_capacity(ticket_count);
        let mut rows = BTreeMap::new();
        for _ in 0..ticket_count {
            let tid = if rng.usize(10) == 0 {
                spec
            } else {
                let n = next_id;
                next_id += 1;
                num(n)
            };
            if rng.bool() {
                rows.insert(
                    tid,
                    if rng.bool() {
                        Ready::Agent
                    } else {
                        Ready::Human
                    },
                );
            }
            if rng.usize(6) == 0 {
                tickets.push(TicketInput {
                    number: tid,
                    facts: Observed::Unread(vec![]),
                });
                continue;
            }
            let pr_num = num(50_000 + tid.get());
            let head = commit(tid.get() * 2 + 1);
            let merge = commit(tid.get() * 2 + 2);
            let pr_fields = PrFields {
                number: pr_num,
                draft: rng.bool(),
                head_branch: ne(&format!("room/syn-{tid}")),
                head_commit: head.clone(),
                base_branch: if rng.bool() { ne("main") } else { gen_ne(rng) },
                closes: if rng.bool() { vec![tid] } else { vec![] },
            };
            let pr = match rng.usize(5) {
                0 => None,
                1 => Some(PrInput::Several(vec![pr_num, num(pr_num.get() + 1)])),
                2 => Some(PrInput::Merged(MergeInput {
                    pr: MergedPr {
                        fields: pr_fields,
                        merge_commit: merge.clone(),
                        merged_at: Timestamp(match rng.usize(4) {
                            0 => i64::MIN,
                            1 => -1,
                            2 => 0,
                            _ => 1_793_390_000_000,
                        }),
                    },
                    read_back: rng.bool(),
                })),
                _ => {
                    let report_text = match rng.usize(5) {
                        0 => format!("VERDICT: APPROVE at {}", head.as_str()),
                        1 => format!(
                            "VERDICT: CHANGES at {}\n- **R1 [high]** disputed, kept: x\n- **R2 [low]** still open after 3 rounds: y",
                            head.as_str()
                        ),
                        2 => format!(
                            "VERDICT: CHANGES at {}\n- **R{} [medium]** still open after {} rounds: {}",
                            head.as_str(),
                            rng.next_u64(),
                            rng.next_u64(),
                            gen_string(rng)
                        ),
                        _ => gen_string(rng),
                    };
                    let checks = (0..rng.usize(4))
                        .map(|i| Check {
                            name: if i == 0 { ne("ci") } else { gen_ne(rng) },
                            result: *rng.pick(&[
                                CheckResult::Pass,
                                CheckResult::Fail,
                                CheckResult::Pending,
                                CheckResult::Skipping,
                                CheckResult::Cancel,
                            ]),
                        })
                        .collect();
                    Some(PrInput::Open(Box::new(OpenPr {
                        fields: pr_fields,
                        subject: if rng.bool() {
                            "green".to_owned()
                        } else {
                            gen_string(rng)
                        },
                        ci: rng.bool().then(|| CheckRun {
                            head_commit: head.clone(),
                            base_commit: commit(1),
                            checks,
                        }),
                        base_now: rng.bool().then(|| commit(1)),
                        reports: if rng.bool() {
                            vec![ReportComment {
                                comment: num(1 + rng.next_u64() % 10),
                                text: report_text,
                            }]
                        } else {
                            vec![]
                        },
                        starts: if rng.bool() {
                            vec![Start {
                                id: OpId::parse("op-syn-1").unwrap(),
                                state: match rng.usize(4) {
                                    0 => StartState::Pending,
                                    1 => StartState::Uncertain,
                                    2 => StartState::Started {
                                        thread: ne("thr_syn_r"),
                                    },
                                    _ => StartState::Refused {
                                        reason: StartReason::Refused,
                                    },
                                },
                                logged: rng.bool(),
                            }]
                        } else {
                            vec![]
                        },
                        records: PrRecords::default(),
                    })))
                }
            };
            let labels = (0..rng.usize(4))
                .map(|_| {
                    ne(rng.pick(&[
                        "ready-for-agent",
                        "ready-for-human",
                        "needs-info",
                        "held",
                        "polish",
                        "wontfix",
                    ]))
                })
                .collect();
            let relies_on = (0..rng.usize(4)).map(|_| gen_ne(rng)).collect();
            let holds = if rng.bool() {
                vec![Hold {
                    comment: num(2),
                    merged: MergeFact {
                        number: num(900_000),
                        merge_commit: commit(900_000),
                    },
                    files: vec![gen_ne(rng)],
                    notified: rng.bool(),
                }]
            } else {
                vec![]
            };
            let builder = rng.bool().then(|| Agent {
                thread: ne("thr_syn_b"),
                archived: rng.bool(),
            });
            let builder_source = rng.bool().then(|| BuilderSource {
                thread: ne("thr_syn_b"),
                branch: ne(&format!("room/syn-{tid}")),
                family: if rng.bool() {
                    BuilderFamily::Claude
                } else {
                    BuilderFamily::Gpt
                },
                plan_limit: rng.bool(),
            });
            let reviewers = if rng.bool() {
                vec![Reviewer {
                    pr: pr_num,
                    agent: Agent {
                        thread: ne("thr_syn_r"),
                        archived: rng.bool(),
                    },
                    head: head.clone(),
                    last_activity_at: match rng.usize(3) {
                        0 => 0,
                        1 => u64::MAX,
                        _ => 1_793_300_000_000,
                    },
                    given_up: rng.bool(),
                    output: None,
                }]
            } else {
                vec![]
            };
            let blockers = if tid.get() > 1 && rng.bool() {
                let b = num(tid.get() - 1);
                vec![BlockerInput {
                    number: b,
                    state: if rng.bool() {
                        IssueState::Closed
                    } else {
                        IssueState::Open
                    },
                    merged: rng.bool().then(|| MergeInput {
                        pr: MergedPr {
                            fields: PrFields {
                                number: num(80_000 + b.get()),
                                draft: false,
                                head_branch: ne("room/syn-b"),
                                head_commit: commit(b.get()),
                                base_branch: ne("main"),
                                closes: vec![b],
                            },
                            merge_commit: commit(b.get() + 100),
                            merged_at: Timestamp(1_793_380_000_000),
                        },
                        read_back: rng.bool(),
                    }),
                }]
            } else {
                vec![]
            };
            tickets.push(TicketInput {
                number: tid,
                facts: Observed::Complete(TicketFacts {
                    issue: Issue {
                        title: gen_string(rng),
                        state: if rng.bool() {
                            IssueState::Open
                        } else {
                            IssueState::Closed
                        },
                        milestone: None,
                        labels,
                        owned_paths: None,
                        relies_on: None,
                        pending_question: None,
                    },
                    blockers,
                    pr,
                    builder,
                    builder_source,
                    reviewers,
                    starts: vec![],
                    relies_on,
                    holds,
                    held_label_comment: rng.bool().then(|| num(1)),
                    question: rng.bool().then(|| num(5)),
                    records: TicketRecords {
                        archived: rng.bool(),
                        ..Default::default()
                    },
                }),
            });
        }
        let fp = Fingerprint::parse(&format!("{:064x}", s + 1)).unwrap();
        let changes = (0..rng.usize(4))
            .map(|c| ContractChange {
                merged: MergeInput {
                    pr: MergedPr {
                        fields: PrFields {
                            number: num(900_000 + c as u64),
                            draft: false,
                            head_branch: ne("room/syn-c"),
                            head_commit: commit(900_000 + c as u64),
                            base_branch: ne("main"),
                            closes: vec![],
                        },
                        merge_commit: commit(950_000 + c as u64),
                        merged_at: Timestamp(if rng.bool() {
                            1_793_395_000_000
                        } else {
                            i64::MIN
                        }),
                    },
                    read_back: rng.bool(),
                },
                files: vec![ChangedFile {
                    path: gen_ne(rng),
                    previous_path: rng.bool().then(|| gen_ne(rng)),
                    added: rng.bool(),
                }],
            })
            .collect();
        fleets_vec.push(FleetInput {
            spec,
            facts: Observed::Complete(FleetFacts {
                issue: Issue {
                    title: gen_string(rng),
                    state: if rng.bool() {
                        IssueState::Open
                    } else {
                        IssueState::Closed
                    },
                    milestone: None,
                    labels: vec![],
                    owned_paths: None,
                    relies_on: None,
                    pending_question: None,
                },
                approval: rng.bool().then(|| PlanApproval {
                    approval: Approval {
                        comment: num(1),
                        revision: num(1),
                        fingerprint: fp.clone(),
                    },
                    rows,
                    approved_at: if rng.bool() {
                        1_793_380_000_000
                    } else {
                        u64::MAX
                    },
                }),
                fingerprint_now: if rng.bool() {
                    fp
                } else {
                    Fingerprint::parse(&format!("{:064x}", s + 99)).unwrap()
                },
                tickets,
                changes,
                follow_ups: vec![],
                records: SpecRecords {
                    summary_written: rng.bool(),
                    ..Default::default()
                },
            }),
        });
    }
    Snapshot {
        default_branch,
        fleets: if rng.usize(10) == 0 {
            Observed::Unread(vec![])
        } else {
            Observed::Complete(fleets_vec)
        },
    }
}

struct FuzzFleetsSource {
    issues: Vec<IssueRow>,
    prs: Vec<StockPr>,
    checks: Vec<Check>,
    comments: Vec<String>,
    on_base_ok: bool,
}

impl FleetsSource for FuzzFleetsSource {
    fn tested_version(&self) -> &str {
        "2.100.0"
    }
    fn version(&self, _: Instant) -> Result<NonEmpty, Failed> {
        Ok(ne("2.100.0"))
    }
    fn repository(&self, _: Instant) -> Result<Repository, Failed> {
        Ok(Repository {
            name: ne("example"),
        })
    }
    fn issues(&self, _: Instant) -> Result<Listed<IssueRow>, Failed> {
        Ok(Listed {
            cut_short: false,
            rows: self.issues.clone(),
        })
    }
    fn pull_requests(&self, _: Instant) -> Result<Listed<PrRow>, Failed> {
        Ok(Listed {
            cut_short: false,
            rows: self.prs.iter().map(|p| p.pr.clone()).collect(),
        })
    }
    fn stock_pull_requests(&self, _: Instant) -> Result<Listed<StockPr>, Failed> {
        Ok(Listed {
            cut_short: false,
            rows: self.prs.clone(),
        })
    }
    fn checks(&self, _: Number, _: Instant) -> Result<Vec<Check>, Failed> {
        Ok(self.checks.clone())
    }
    fn comments(&self, _: Number, _: Instant) -> Result<Vec<String>, Failed> {
        Ok(self.comments.clone())
    }
    fn on_base(&self, _: &MergedPr, _: Instant) -> Result<bool, Failed> {
        Ok(self.on_base_ok)
    }
}

struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(1_793_400_000_000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

fn fuzz_fleets_and_render(rng: &mut Rng) {
    let spec_n = num(1);
    let t_count = rng.usize(8);
    let mut sub_nodes = Vec::new();
    let mut issues = Vec::new();
    let mut prs = Vec::new();
    for i in 0..t_count {
        let tid = num(2 + i as u64);
        sub_nodes.push(FleetLink {
            number: tid,
            id: ne(&format!("I_syn_{tid}")),
        });
        let blocked = if i > 0 && rng.bool() {
            let b = num(1 + i as u64);
            vec![FleetLink {
                number: b,
                id: ne(&format!("I_syn_{b}")),
            }]
        } else {
            vec![]
        };
        issues.push(IssueRow {
            number: tid,
            id: ne(&format!("I_syn_{tid}")),
            title: gen_string(rng),
            state: if rng.bool() {
                IssueState::Open
            } else {
                IssueState::Closed
            },
            milestone: rng.bool().then(|| Milestone {
                number: num(1),
                title: gen_string(rng),
            }),
            labels: vec![ne(rng.pick(&[
                "ready-for-agent",
                "needs-info",
                "held",
                "polish",
            ]))],
            body: gen_string(rng),
            sub_issues: Links {
                nodes: vec![],
                total: 0,
            },
            blocked_by: Links {
                total: blocked.len() as u64,
                nodes: blocked,
            },
        });
        if rng.bool() {
            let pr_n = num(100 + i as u64);
            let facts = PrFacts {
                number: pr_n,
                draft: rng.bool(),
                head_branch: ne(&format!("room/syn-{tid}")),
                head_commit: commit(pr_n.get()),
                base_branch: ne("main"),
                closes: vec![FleetLink {
                    number: tid,
                    id: ne(&format!("I_syn_{tid}")),
                }],
            };
            let pr = match rng.usize(3) {
                0 => PrRow::Open(facts),
                1 => PrRow::Merged {
                    facts,
                    merge_commit: commit(pr_n.get() + 1000),
                    merged_at: Timestamp(1_793_385_000_000),
                },
                _ => PrRow::Closed { number: pr_n },
            };
            prs.push(StockPr {
                pr,
                title: Fact::Known(gen_ne(rng)),
            });
        }
    }
    issues.push(IssueRow {
        number: spec_n,
        id: ne("I_syn_1"),
        title: gen_string(rng),
        state: IssueState::Open,
        milestone: None,
        labels: vec![],
        body: gen_string(rng),
        sub_issues: Links {
            total: sub_nodes.len() as u64,
            nodes: sub_nodes,
        },
        blocked_by: Links {
            nodes: vec![],
            total: 0,
        },
    });
    let source = FuzzFleetsSource {
        issues,
        prs,
        checks: vec![Check {
            name: ne("ci"),
            result: CheckResult::Pass,
        }],
        comments: vec![gen_string(rng)],
        on_base_ok: rng.bool(),
    };
    let env = fleets(&source, &FixedClock, Duration::from_secs(5));
    let rendered1 = openwiz_cli::fleets::render(&env);
    let rendered2 = openwiz_cli::fleets::render(&env);
    assert_eq!(rendered1, rendered2);
    let _ = pending_question(&[openwiz_core::fleet::fleets::IssueComment {
        body: gen_string(rng),
        link: ne("https://example.invalid/1"),
        asked_at: Timestamp(1_793_385_000_000),
    }]);
}

fn fuzz_world_e2e(rng: &mut Rng) {
    let base_sha = format!("{:040x}", 1_u64);
    let mut responses: BTreeMap<Vec<String>, Vec<u8>> = BTreeMap::new();
    let t1_body = format!(
        "Ticket 2\n**Owned paths:** `crates/core/src/a.rs`\n**Relies on:** {}\n",
        if rng.bool() {
            "nothing".to_owned()
        } else {
            gen_string(rng)
        }
    );
    let t1_title = if rng.bool() {
        "Synthetic ticket 2".to_owned()
    } else {
        gen_string(rng).replace('\n', " ")
    };
    let spec_body = format!("Spec 1\n{}", gen_string(rng));
    let rev_text = format!(
        "plan-graph revision v2\nspec #1 body sha256 {}\nticket #2 blocked-by none body sha256 {} title {}\n",
        sha256_hex(format!("{spec_body}\n").as_bytes()),
        sha256_hex(format!("{t1_body}\n").as_bytes()),
        t1_title
    );
    let fp = sha256_hex(rev_text.as_bytes());
    let valid_approval = format!(
        "**Plan graph approved by Jake, 2026-10-30, revision 1:** Approved.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-1\n\nFingerprint: `{fp}`\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n| #2 | {} | none | ready-for-agent |\n\n```text\n{rev_text}```\n",
        t1_title.replace('|', "\\|")
    );
    let approval_body = match rng.usize(4) {
        0 => valid_approval,
        1 => String::from_utf8_lossy(&mutate_bytes(rng, valid_approval.as_bytes())).into_owned(),
        2 => format!(
            "**Plan graph approved by Jake, 2026-10-30, revision 1:** \"go\" (source)\n\nFingerprint: `{fp}`\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n| #2 | {} | none | ready-for-agent |\n\n```text\n{rev_text}```\n",
            t1_title.replace('|', "\\|")
        ),
        _ => gen_string(rng),
    };
    let held_ticket = rng.bool();
    let closed_ticket = rng.bool();
    let t1_labels = if held_ticket {
        json!([
            {"color": "0e8a16", "description": "Ready", "id": "L_1", "name": "ready-for-agent"},
            {"color": "d93f0b", "description": "Held", "id": "L_2", "name": "held"}
        ])
    } else {
        json!([{"color": "0e8a16", "description": "Ready", "id": "L_1", "name": "ready-for-agent"}])
    };
    let issues = json!([
        {
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": spec_body,
            "id": "I_syn_1",
            "labels": [],
            "milestone": null,
            "number": 1,
            "state": "OPEN",
            "subIssues": {
                "nodes": [{
                    "id": "I_syn_2",
                    "number": 2,
                    "state": if closed_ticket { "CLOSED" } else { "OPEN" },
                    "title": t1_title,
                    "url": "https://example.invalid/synthetic/example/issues/2"
                }],
                "totalCount": 1
            },
            "title": "spec: Synthetic"
        },
        {
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": t1_body,
            "id": "I_syn_2",
            "labels": t1_labels,
            "milestone": null,
            "number": 2,
            "state": if closed_ticket { "CLOSED" } else { "OPEN" },
            "subIssues": {"nodes": [], "totalCount": 0},
            "title": t1_title
        },
        {
            "blockedBy": {"nodes": [], "totalCount": 0},
            "body": format!("Follow-up of #2 (spec #1)\n{}", gen_string(rng)),
            "id": "I_syn_3",
            "labels": [],
            "milestone": null,
            "number": 3,
            "state": "OPEN",
            "subIssues": {"nodes": [], "totalCount": 0},
            "title": "Synthetic follow-up"
        }
    ]);
    let merge_sha = format!("{:040x}", 99_u64);
    let prs = json!([
        {
            "baseRefName": "main",
            "closingIssuesReferences": [{
                "id": "I_syn_2",
                "number": 2,
                "repository": {
                    "id": "R_syn_1",
                    "name": "example",
                    "owner": {"id": "O_syn_1", "login": "synthetic"}
                },
                "url": "https://example.invalid/synthetic/example/issues/2"
            }],
            "headRefName": "room/syn-2",
            "headRefOid": format!("{:040x}", 10_u64),
            "isDraft": rng.bool(),
            "mergeCommit": null,
            "mergedAt": null,
            "number": 50,
            "state": "OPEN",
            "title": "#2: Synthetic PR"
        },
        {
            "baseRefName": "main",
            "closingIssuesReferences": [{
                "id": "I_syn_2",
                "number": 2,
                "repository": {
                    "id": "R_syn_1",
                    "name": "example",
                    "owner": {"id": "O_syn_1", "login": "synthetic"}
                },
                "url": "https://example.invalid/synthetic/example/issues/2"
            }],
            "headRefName": "room/syn-2-old",
            "headRefOid": format!("{:040x}", 11_u64),
            "isDraft": false,
            "mergeCommit": null,
            "mergedAt": null,
            "number": 51,
            "state": "CLOSED",
            "title": "#2: Closed PR"
        },
        {
            "baseRefName": "main",
            "closingIssuesReferences": [],
            "headRefName": "room/syn-contract",
            "headRefOid": format!("{:040x}", 98_u64),
            "isDraft": false,
            "mergeCommit": {"oid": merge_sha},
            "mergedAt": "2026-10-30T19:00:00Z",
            "number": 52,
            "state": "MERGED",
            "title": "Contract change"
        }
    ]);
    let comments = json!([
        {
            "issue_url": "https://example.invalid/api/v3/repos/synthetic/example/issues/1",
            "id": 1,
            "author": "jparker2006",
            "body": approval_body,
            "created": 1_793_380_000_000_u64,
            "updated": 1_793_380_000_000_u64
        },
        {
            "issue_url": "https://example.invalid/api/v3/repos/synthetic/example/issues/2",
            "id": 2,
            "author": "jparker2006",
            "body": gen_string(rng),
            "created": 1_793_381_000_000_u64,
            "updated": 1_793_381_000_000_u64
        },
        {
            "issue_url": "https://example.invalid/api/v3/repos/synthetic/example/issues/2",
            "id": 4,
            "author": "jparker2006",
            "body": gen_string(rng),
            "created": 1_793_381_500_000_u64,
            "updated": 1_793_381_500_000_u64
        },
        {
            "issue_url": "https://example.invalid/api/v3/repos/synthetic/example/issues/50",
            "id": 3,
            "author": "jparker2006",
            "body": gen_string(rng),
            "created": 1_793_382_000_000_u64,
            "updated": 1_793_382_000_000_u64
        },
        {
            "issue_url": "https://example.invalid/api/v3/repos/synthetic/example/issues/51",
            "id": 5,
            "author": "jparker2006",
            "body": gen_string(rng),
            "created": 1_793_382_500_000_u64,
            "updated": 1_793_382_500_000_u64
        }
    ]);
    let is_private = rng.bool();
    responses.insert(
        vec!["repo".into(), "view".into(), "--json".into(), gh_tick::REPOSITORY_FIELDS.into()],
        br#"{"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic/example","url":"https://example.invalid/synthetic/example"}"#.to_vec(),
    );
    responses.insert(
        vec![
            "repo".into(),
            "view".into(),
            "--json".into(),
            "nameWithOwner,isPrivate".into(),
        ],
        serde_json::to_vec(&json!({"nameWithOwner": "synthetic/example", "isPrivate": is_private}))
            .unwrap(),
    );
    responses.insert(
        vec![
            "api".into(),
            "repos/{owner}/{repo}/issues/2/timeline?per_page=100".into(),
            "--paginate".into(),
            "--jq".into(),
            gh_tick::EVENTS.into(),
        ],
        serde_json::to_vec(&json!([
            {"id": 10, "event": "labeled", "label": "held", "body": null, "at": 1_793_380_500_000_u64},
            {"id": 2, "event": "commented", "label": null, "body": gen_string(rng), "at": 1_793_381_000_000_u64}
        ]))
        .unwrap(),
    );
    responses.insert(
        vec![
            "api".into(),
            format!("repos/{{owner}}/{{repo}}/compare/{merge_sha}...{base_sha}"),
            "--jq".into(),
            "{status: .status, behind_by: .behind_by}".into(),
        ],
        br#"{"status":"identical","behind_by":0}"#.to_vec(),
    );
    responses.insert(
        vec![
            "api".into(),
            "repos/{owner}/{repo}/pulls/52/files?per_page=100".into(),
            "--paginate".into(),
            "--jq".into(),
            gh_tick::FILES.into(),
        ],
        serde_json::to_vec(
            &json!([{"path": "crates/core/src/a.rs", "previous": null, "status": "modified"}]),
        )
        .unwrap(),
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
        serde_json::to_vec(&issues).unwrap(),
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
            gh_fleets::PR_FIELDS.into(),
        ],
        serde_json::to_vec(&prs).unwrap(),
    );
    responses.insert(
        vec![
            "api".into(),
            "repos/{owner}/{repo}/git/ref/heads/main".into(),
            "--jq".into(),
            gh_tick::REF.into(),
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
    responses.insert(
        vec![
            "api".into(),
            "repos/{owner}/{repo}/issues/comments?per_page=100&page=1".into(),
            "--jq".into(),
            gh_tick::REPOSITORY_COMMENTS.into(),
        ],
        serde_json::to_vec(&comments).unwrap(),
    );
    let head = format!("{:040x}", 10_u64);
    responses.insert(
        vec![
            "api".into(),
            format!("repos/{{owner}}/{{repo}}/commits/{head}"),
            "--jq".into(),
            gh_tick::COMMIT.into(),
        ],
        serde_json::to_vec(&json!({"sha": head, "subject": gen_string(rng)})).unwrap(),
    );
    responses.insert(
        vec![
            "api".into(),
            format!("repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100"),
            "--paginate".into(),
            "--jq".into(),
            gh_tick::RUNS.into(),
        ],
        br#"{"total_count":0,"runs":[]}"#.to_vec(),
    );
    responses.insert(
        vec![
            "pr".into(),
            "checks".into(),
            "50".into(),
            "--json".into(),
            gh_tickets::CHECK_FIELDS.into(),
        ],
        b"[]".to_vec(),
    );
    responses.insert(
        vec![
            "pr".into(),
            "view".into(),
            "50".into(),
            "--json".into(),
            gh_tickets::PR_FIELDS.into(),
        ],
        serde_json::to_vec(&json!({
            "baseRefName": "main",
            "closingIssuesReferences": [{
                "id": "I_syn_2",
                "number": 2,
                "repository": {"id": "R_syn_1"},
                "url": "https://example.invalid/synthetic/example/issues/2"
            }],
            "headRefName": "room/syn-2",
            "headRefOid": head,
            "isDraft": false,
            "mergeCommit": null,
            "mergedAt": null,
            "number": 50,
            "state": "OPEN"
        }))
        .unwrap(),
    );
    let map = Arc::new(responses);
    let exec = Executor::supplied(Arc::new(move |call: &Invocation, _: Instant| {
        map.get(call.argv())
            .cloned()
            .ok_or_else(|| SourceError::Malformed {
                detail: "unexpected".into(),
            })
    }));
    let gh = TickReads::with_executor(exec);
    let deadline = Instant::now() + Duration::from_secs(5);
    if let Ok(inv) = Inventory::read(&gh, deadline)
        && let Ok(world) = World::read(&gh, None, Path::new("/nonexistent"), deadline, inv)
    {
        let _ = plan(&world.snapshot, &world.rules, 1_793_400_000_000);
    }
}

fn adversarial_cases(authors: &RecordAuthors, rules: &Rules, f: &SpawnFlags) {
    let deep_arr = format!("{}{}", "[".repeat(512), "]".repeat(512));
    let deep_obj = format!("{}1{}", "{\"a\":".repeat(512), "}".repeat(512));
    for bytes in [
        deep_arr.as_bytes(),
        deep_obj.as_bytes(),
        b"{\"a\":1,\"a\":1}",
        b"{\"\":1,\"\":2}",
        b"{\"\\u0061\":1,\"a\":2}",
        b"[1e309]",
        b"[-0.0]",
        b"[18446744073709551616]",
        b"[-9223372036854775809]",
        b"\xef\xbb\xbf{}",
        b"{}\x00",
        b"{} {}",
    ] {
        let mut rng = Rng::new(42);
        fuzz_json_parsers(bytes, &mut rng, authors);
    }
    assert!(gh_plan::strict(br#"{"\u0061":1,"a":2}"#).is_err());
    assert!(decisions::document(br#"{"\u0061":1,"a":2}"#).is_none());
    assert!(gh_tick::document(br#"{"\u0061":1,"a":2}"#).is_err());
    assert!(serde_json::from_slice::<StrictJson>(br#"{"\u0061":1,"a":2}"#).is_err());

    let _ = models::read("", f);
    let _ = Rules::parse("", f);
    let _ = Rules::parse(&"|".repeat(4096), f);

    let snap = Snapshot {
        default_branch: Observed::Complete(ne("main")),
        fleets: Observed::Complete(vec![]),
    };
    let p = plan(&snap, rules, u64::MAX).unwrap();
    assert!(p.actions.is_empty());
}

#[test]
fn fuzz_area4_parsers_and_plan_graph() {
    let seed = std::env::var("OPENWIZ_FUZZ_SEED")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0x9e37_79b9_7f4a_7c15);
    let seconds = std::env::var("OPENWIZ_FUZZ_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);

    let f = flags();
    let rules = Rules::parse(FLEET_MD, &f).unwrap();
    let authors = RecordAuthors::read(FLEET_MD).unwrap();
    let seeds = corpus();
    let mut rng = Rng::new(seed);

    adversarial_cases(&authors, &rules, &f);

    let start = Instant::now();
    let budget = Duration::from_secs(seconds);
    let min_iters = if seconds == 0 { 128_u64 } else { u64::MAX };
    let mut iters = 0_u64;
    let mut next_report = Duration::from_secs(60);

    loop {
        if seconds == 0 {
            if iters >= min_iters {
                break;
            }
        } else if start.elapsed() >= budget {
            break;
        }

        let base = rng.pick(&seeds);
        let mutated = mutate_bytes(&mut rng, base);
        fuzz_json_parsers(&mutated, &mut rng, &authors);

        let val = gen_json_value(&mut rng, 3);
        let encoded = serde_json::to_vec(&val).unwrap();
        fuzz_json_parsers(&encoded, &mut rng, &authors);

        fuzz_allowlists(&mut rng);

        if iters.is_multiple_of(4) {
            fuzz_markdown_rules(&mut rng, &f);
            let snap = gen_snapshot(&mut rng);
            let now = match rng.usize(4) {
                0 => 0,
                1 => u64::MAX,
                _ => 1_793_400_000_000,
            };
            let p1 = plan(&snap, &rules, now);
            let p2 = plan(&snap, &rules, now);
            assert_eq!(p1, p2, "plan must be deterministic");
            if let Ok(p) = p1 {
                let bytes = serde_json::to_vec(&p).unwrap();
                assert!(gh_plan::strict(&bytes).is_ok());
            }
        }

        if iters.is_multiple_of(8) {
            fuzz_fleets_and_render(&mut rng);
            fuzz_world_e2e(&mut rng);
        }

        iters += 1;
        if seconds > 0 && start.elapsed() >= next_report {
            println!(
                "fuzz-area4 progress: elapsed={}s iters={iters} seed={seed}",
                start.elapsed().as_secs()
            );
            next_report += Duration::from_secs(60);
        }
    }

    if seconds > 0 {
        println!(
            "fuzz-area4 finished: elapsed={:.1}s iters={iters} seed={seed}",
            start.elapsed().as_secs_f64()
        );
    }
}
