use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::ffi::OsString;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_adapter_github::allowlist::Invocation;
use openwiz_adapter_github::process::Execute;
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::{Comment, Event, TickReads};
use openwiz_adapter_github::tickets::{self, RecordAuthors};
use openwiz_core::fleet::fleets::{IssueRow, Links};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Issue, IssueState, MergedPr, NonEmpty, Number, PrFields,
};
use openwiz_core::fleet::tick::{
    self, Agent, Approval, BlockerInput, ChangedFile, CheckRun, ContractChange, Fingerprint,
    FleetFacts, FleetInput, Hold, MergeFact, MergeInput, Observed, OpenPr, PlanApproval, PrInput,
    Problem, Ready, ReportComment, Reviewer, Rules, Snapshot, SpecRecords, Start, StartReason,
    StartState, TicketFacts, TicketInput, TicketRecords,
};
use openwiz_core::messaging::OpId;
use openwiz_core::model::Timestamp;
use openwiz_core::models::{self, Choice, Role, write};
use openwiz_core::source::SourceError;

use crate::fleet::tick::{Inventory, World, records};
use crate::state::loops::{config, document, repository};
use crate::state::starts;

struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Self(seed.max(1))
    }

    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }

    fn below(&mut self, n: usize) -> usize {
        if n <= 1 {
            return 0;
        }
        (self.next() % n as u64) as usize
    }

    fn coin(&mut self) -> bool {
        self.next() & 1 == 1
    }

    fn pick<'a, T>(&mut self, items: &'a [T]) -> &'a T {
        &items[self.below(items.len())]
    }
}

const TOKENS: &[&str] = &[
    "",
    " ",
    "\t",
    "\n",
    "\r\n",
    "\0",
    "\\",
    "\"",
    "'",
    "`",
    "```",
    "```text\n",
    "~~~",
    "|",
    "\\|",
    ":",
    ":** ",
    ", ",
    "#",
    "#0",
    "#1",
    "#18446744073709551615",
    "#18446744073709551616",
    "0",
    "-1",
    "99999999999999999999",
    "[remote \"]",
    "[REMOTE \"]",
    "[remote \"\"]",
    "[remote \"origin\"]",
    "[include]",
    "[url \"https://example.invalid\"]",
    "url = https://github.com/synthetic-owner/synthetic-repo.git",
    "insteadOf = https://github.com/",
    "pushInsteadOf = https://github.com/",
    "launch-fleet: ",
    "launch-fleet: archived",
    "launch-fleet: started",
    "launch-fleet: started, thread thr_syn_1",
    "launch-fleet: start checked, branch main",
    "launch-fleet: start checked, thread thr_syn_1, branch main",
    "launch-fleet: held for #1: contract changed, re-approve. a.md changed in #1.",
    "launch-fleet: builder fallback due, thread thr_syn_1, branch main\nReplacement: thr_syn_2",
    "launch-fleet: review started ",
    "launch-fleet: review failed ",
    "launch-fleet: review given up ",
    "launch-fleet: re-check sent ",
    "launch-fleet: merge blocked ",
    "launch-fleet: findings sent ",
    "launch-fleet: CI failure sent ",
    "launch-fleet: dispute asked ",
    "launch-fleet: diagnosis asked ",
    "launch-fleet: noted #1",
    "launch-fleet: look: reason",
    "launch-fleet: spec summary",
    "launch-fleet: asked the orchestrator",
    "launch-fleet: told the user",
    "VERDICT: APPROVE at ",
    "**Plan graph approved by ",
    ", revision 1:** \"go\" (\"src\")",
    "Private record: https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-2",
    "Fingerprint: `",
    "plan-graph revision v2\n",
    "plan-graph revision v1\n",
    "ticket #1 blocked-by none body sha256 ",
    " title ",
    "| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n",
    "- [x] ",
    "- [X] ",
    "* [x]\t",
    "+ [x]\n",
    "## Models",
    "## Builder",
    "## Builder for small tickets",
    "## Reviewer for Claude-built",
    "## Reviewer for GPT-built",
    "## Fixer",
    "## CI checks",
    "## Standing merge rules",
    "## GitHub identity",
    "| Record authors | `synthetic-bot` |",
    "**Owned paths:** ",
    "**Relies on:** ",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "thr_syn_1",
    "thr_",
    "prj_syn_1",
    "“",
    "”",
    "é",
    "日本",
    "\u{200b}",
    "\u{1f600}",
    "\u{feff}",
    "*",
    "**",
    "../",
    "/",
    "{",
    "}",
    "[",
    "]",
    "null",
    "true",
    "false",
    "1e308",
    "18446744073709551616.0",
    "1e20",
    "-0.0",
];

const CONFIG_SEEDS: &[&str] = &[
    "[remote \"origin\"]\n\turl = https://github.com/synthetic-owner/synthetic-repo.git\n",
    "[remote \"origin\"]\n\turl = git@github.com:synthetic-owner/synthetic-repo.git\n",
    "[remote \"origin\"]\n\turl = ssh://git@github.com/synthetic-owner/synthetic-repo\n",
    "[remote \"]\n",
    "[REMOTE \"]\n",
    "[remote \"\"]\n",
    "[remote \"a\"]\n[remote \"origin\"]\nurl = https://github.com/synthetic-owner/synthetic-repo\n",
    "[url \"https://example.invalid/\"]\n\tinsteadOf = https://github.com/\n",
    "[include]\n\tpath = other\n",
];

const DEFINITION_SEED: &str = r#"{
  "schema": "openwiz.loops.v1",
  "kind": "definition",
  "id": "syn-loop-1",
  "name": "Synthetic loop",
  "owner": "synthetic-owner",
  "wake": {"kind": "interval", "every_ms": 60000, "anchor_ms": 0},
  "check": {"argv": ["echo", "ok"], "timeout_ms": 5000},
  "action": {
    "project": {"kind": "id", "value": "prj_syn_1"},
    "harness": "claude-code",
    "model": "claude-opus-5-5",
    "effort": "medium",
    "brief": "Synthetic brief"
  },
  "authority": {
    "approved_by": "synthetic-owner",
    "approval_ref": "synthetic-ref",
    "scope": "synthetic-scope"
  },
  "budget": {"window_ms": 3600000, "max_agent_starts": 4},
  "enabled": true,
  "mode": "active",
  "priority": "normal"
}"#;

const RUN_SEED: &str = r#"{
  "schema": "openwiz.loops.v1",
  "kind": "run",
  "id": "syn-run-1",
  "loop_id": "syn-loop-1",
  "definition_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "wake": {"kind": "interval", "due_at_ms": 1000},
  "started_at_ms": 1000,
  "updated_at_ms": 2000,
  "cost": {"kind": "known", "usd_micros": 10},
  "result": {"kind": "quiet"}
}"#;

const SERVICE_CONFIG_SEED: &str = r#"{
  "schema": "openwiz.service-config.v1",
  "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"},
  "operator": "synthetic-operator",
  "project": "prj_syn_1",
  "orchestrator_thread": "thr_syn_1",
  "service_issue": 1,
  "github_app": {"app_id": 1, "installation_id": 2},
  "tick": {"every_s": 60},
  "health": {"every_s": 60},
  "server": {"port": 8080, "allowed_host": null, "probe_timeout_s": 5}
}"#;

const START_SEED: &str = r#"{
  "schema": "openwiz.start-record.v1",
  "id": "ow1-0000000000000000000000000000000000000000",
  "key": {
    "repository": "synthetic-owner/synthetic-repo",
    "role": "builder",
    "number": 7,
    "commit": null
  },
  "project_id": "prj_syn_1",
  "settings": {"harness": "codex", "model": "gpt-6.2-sol", "effort": "medium"},
  "attempts": [{"op_id": "op-syn-1", "at": 0, "outcome": {"kind": "pending"}}]
}"#;

const PR_LIST_SEED: &str = r#"[{
  "baseRefName": "main",
  "closingIssuesReferences": [{
    "id": "I_syn_1",
    "number": 1,
    "repository": {"id": "R1", "name": "synthetic-repo", "owner": {"id": "O1", "login": "synthetic-owner"}},
    "url": "https://github.com/synthetic-owner/synthetic-repo/issues/1"
  }],
  "headRefName": "room/syn-1",
  "headRefOid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "isDraft": false,
  "mergeCommit": {"oid": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
  "mergedAt": "2026-11-20T00:00:00Z",
  "number": 10,
  "state": "MERGED",
  "title": "Synthetic PR"
}]"#;

const PR_VIEW_SEED: &str = r#"{
  "baseRefName": "main",
  "closingIssuesReferences": [{
    "id": "I_syn_1",
    "number": 1,
    "repository": {"id": "R1", "name": "synthetic-repo", "owner": {"id": "O1", "login": "synthetic-owner"}},
    "url": "https://github.com/synthetic-owner/synthetic-repo/issues/1"
  }],
  "headRefName": "room/syn-1",
  "headRefOid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "isDraft": false,
  "mergeCommit": null,
  "mergedAt": null,
  "number": 10,
  "state": "OPEN"
}"#;

const ISSUE_VIEW_SEED: &str = r#"{
  "blockedBy": {"nodes": [], "totalCount": 0},
  "body": "**Owned paths:** `crates/cli/src/`\n**Relies on:** nothing\n",
  "closedByPullRequestsReferences": [],
  "comments": [],
  "labels": [{"color": "ffffff", "description": "", "id": "L1", "name": "ready-for-agent"}],
  "milestone": null,
  "state": "OPEN",
  "subIssues": {"nodes": [], "totalCount": 0},
  "title": "Synthetic issue"
}"#;

const FLEET_MD_SEED: &str = "\
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

const APPROVAL_SEED: &str = "\
**Plan graph approved by synthetic, revision 1:** \"go\"

Fingerprint: `0000000000000000000000000000000000000000000000000000000000000000`

| Ticket | Title | Blocked by | Label |
| --- | --- | --- | --- |
| #2 | Synthetic | none | ready-for-agent |

```text
plan-graph revision v2
spec #1 body sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
ticket #2 blocked-by none body sha256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb title Synthetic
```
";

fn mutate_str(rng: &mut Rng, seed: &str) -> String {
    let mut chars: Vec<char> = seed.chars().collect();
    let ops = 1 + rng.below(5);
    for _ in 0..ops {
        match rng.below(6) {
            0 => {
                let at = rng.below(chars.len() + 1);
                let tok = rng.pick(TOKENS);
                let extra: Vec<char> = tok.chars().collect();
                chars.splice(at..at, extra);
            }
            1 if !chars.is_empty() => {
                let start = rng.below(chars.len());
                let max_del = (chars.len() - start).min(24);
                let len = 1 + rng.below(max_del);
                chars.drain(start..start + len);
            }
            2 if !chars.is_empty() => {
                let at = rng.below(chars.len());
                let tok = rng.pick(TOKENS);
                let end = (at + 1 + rng.below(12)).min(chars.len());
                chars.splice(at..end, tok.chars());
            }
            3 if !chars.is_empty() => {
                let start = rng.below(chars.len());
                let len = 1 + rng.below((chars.len() - start).min(16));
                let slice = chars[start..start + len].to_vec();
                let dst = rng.below(chars.len() + 1);
                chars.splice(dst..dst, slice);
            }
            4 => {
                let cut = rng.below(chars.len() + 1);
                chars.truncate(cut);
            }
            _ => {
                let at = rng.below(chars.len() + 1);
                let b = (rng.next() % 128) as u8 as char;
                chars.insert(at, b);
            }
        }
        if chars.len() > 4096 {
            chars.truncate(4096);
        }
    }
    chars.into_iter().collect()
}

fn mutate_bytes(rng: &mut Rng, seed: &[u8]) -> Vec<u8> {
    let mut out = seed.to_vec();
    let ops = 1 + rng.below(5);
    for _ in 0..ops {
        match rng.below(5) {
            0 if !out.is_empty() => {
                let at = rng.below(out.len());
                out[at] ^= 1u8 << rng.below(8);
            }
            1 => {
                let at = rng.below(out.len() + 1);
                let tok = rng.pick(TOKENS).as_bytes();
                out.splice(at..at, tok.iter().copied());
            }
            2 if !out.is_empty() => {
                let at = rng.below(out.len());
                let end = (at + 1 + rng.below(16)).min(out.len());
                out.drain(at..end);
            }
            3 => {
                let at = rng.below(out.len() + 1);
                out.insert(at, (rng.next() & 0xff) as u8);
            }
            _ => {
                let cut = rng.below(out.len() + 1);
                out.truncate(cut);
            }
        }
        if out.len() > 4096 {
            out.truncate(4096);
        }
    }
    out
}

fn mutate_json_value(rng: &mut Rng, value: &mut serde_json::Value) {
    match value {
        serde_json::Value::Object(map) => {
            let keys: Vec<String> = map.keys().cloned().collect();
            if !keys.is_empty() {
                let k = rng.pick(&keys).clone();
                match rng.below(5) {
                    0 => {
                        if let Some(v) = map.get_mut(&k) {
                            mutate_json_value(rng, v);
                        }
                    }
                    1 => {
                        map.remove(&k);
                    }
                    2 => {
                        let repl = match rng.below(10) {
                            0 => serde_json::Value::Null,
                            1 => serde_json::json!(0),
                            2 => serde_json::json!(1),
                            3 => serde_json::json!(-1),
                            4 => serde_json::json!(u64::MAX),
                            5 => serde_json::json!(i64::MAX),
                            6 => serde_json::json!(1.0),
                            7 => serde_json::json!(""),
                            8 => serde_json::json!(true),
                            _ => serde_json::json!([]),
                        };
                        map.insert(k, repl);
                    }
                    3 => {
                        let extra = mutate_str(rng, "extra");
                        map.insert(extra, serde_json::json!(null));
                    }
                    _ => {
                        if let Some(serde_json::Value::String(s)) = map.get_mut(&k) {
                            *s = mutate_str(rng, s);
                        }
                    }
                }
            }
        }
        serde_json::Value::Array(items) => {
            if !items.is_empty() && rng.coin() {
                let i = rng.below(items.len());
                mutate_json_value(rng, &mut items[i]);
            } else {
                items.push(serde_json::json!(null));
            }
        }
        serde_json::Value::String(s) => {
            *s = mutate_str(rng, s);
        }
        serde_json::Value::Number(_) => {
            *value = match rng.below(7) {
                0 => serde_json::json!(0),
                1 => serde_json::json!(-1),
                2 => serde_json::json!(u64::MAX),
                3 => serde_json::json!(i64::MAX),
                4 => serde_json::json!(i64::MIN),
                5 => serde_json::json!(1.5),
                _ => serde_json::json!(65536),
            };
        }
        serde_json::Value::Bool(b) => {
            *b = !*b;
        }
        serde_json::Value::Null => {
            *value = serde_json::json!({"oid": mutate_str(rng, "a")});
        }
    }
}

fn mutate_json_str(rng: &mut Rng, seed: &str) -> String {
    if rng.coin()
        && let Ok(mut v) = serde_json::from_str::<serde_json::Value>(seed)
    {
        for _ in 0..1 + rng.below(3) {
            mutate_json_value(rng, &mut v);
        }
        return v.to_string();
    }
    mutate_str(rng, seed)
}

fn mock_reads(payload: Vec<u8>) -> TickReads {
    let bytes = Arc::new(payload);
    let handler: Arc<Execute> = Arc::new(move |_call: &Invocation, _| Ok((*bytes).clone()));
    TickReads::with_executor(Executor::supplied(handler))
}

fn fuzz_config(rng: &mut Rng) {
    let base = rng.pick(CONFIG_SEEDS);
    let text = mutate_str(rng, base);
    let repo = if rng.coin() {
        "synthetic-owner/synthetic-repo".to_owned()
    } else {
        mutate_str(rng, "synthetic-owner/synthetic-repo")
    };
    let _ = config::origin_matches_config(&text, &repo);
}

fn fuzz_loops_documents(rng: &mut Rng) {
    let def = mutate_json_str(rng, DEFINITION_SEED);
    let _ = document::parse(&def);
    if let Ok(value) = document::read("definition", &def) {
        let d = repository::Definition {
            value,
            revision: "a".repeat(40),
        };
        let _ = d.project(rng.coin());
        let finding = mutate_str(rng, "finding");
        let _ = d.request(&finding, OpId::parse("syn-op").unwrap());
    }
    let run = mutate_json_str(rng, RUN_SEED);
    let _ = document::read("run", &run);
    let cfg = mutate_json_str(rng, SERVICE_CONFIG_SEED);
    let _ = document::service_config(&cfg);
    let raw = mutate_bytes(
        rng,
        b"core.bare\nfalse\0remote.origin.url\nhttps://example.invalid\0",
    );
    let _ = repository::validate_config(&raw);
    let a0 = mutate_str(rng, "cat-file");
    let a1 = mutate_str(rng, "blob");
    let a2 = mutate_str(rng, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    let _ = repository::GitRead::parse(&[a0.as_str(), a1.as_str(), a2.as_str()]);
}

fn fuzz_starts(rng: &mut Rng) {
    let s = mutate_json_str(rng, START_SEED);
    let _ = starts::read(&s);
}

fn fuzz_records(rng: &mut Rng) {
    let body = mutate_str(rng, APPROVAL_SEED);
    let n1 = Number::new(1).unwrap();
    let n2 = Number::new(2).unwrap();
    let c1 = Comment {
        id: n1,
        author: Some(mutate_str(rng, "synthetic-bot")),
        body: body.clone(),
        created: rng.next(),
        updated: rng.next(),
    };
    let tok = *rng.pick(TOKENS);
    let c2 = Comment {
        id: n2,
        author: if rng.coin() {
            Some(mutate_str(rng, "synthetic-bot"))
        } else {
            None
        },
        body: mutate_str(rng, tok),
        created: rng.next(),
        updated: rng.next(),
    };
    let comments = [c1, c2];
    let _ = records::n(&body);
    let _ = records::record_authors(&body);
    let _ = records::approval(&comments, false);
    let _ = records::approval(&comments, true);
    let _ = records::relies(&body);
    let _ = records::spec_records(&comments);
    let _ = records::looked(&comments);
    let _ = records::ticket_records(&comments);
    let mut retired = BTreeSet::new();
    if rng.coin() {
        retired.insert(n1);
    }
    let _ = records::pr_records(&comments, &retired);
    let mut merges = BTreeMap::new();
    merges.insert(
        n1,
        Commit::parse("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").unwrap(),
    );
    let ev = Event {
        id: n1,
        event: mutate_str(rng, "labeled"),
        label: Some(mutate_str(rng, "held")),
        body: Some(body.clone()),
        at: rng.next(),
    };
    let _ = records::holds(&comments, &[ev], &merges);
    let _ = records::checked_builder(&comments);
    let _ = records::contains_thread_id(&body);
    let _ = records::fallback_due(&comments);
    let _ = records::fallback_replacement(&comments);
    let _ = records::review_records(&comments);
    let _ = records::check_forms(&comments, false);
    let _ = records::check_forms(&comments, true);
    let spec = IssueRow {
        number: n1,
        id: NonEmpty::new("I_1").unwrap(),
        title: mutate_str(rng, "Spec"),
        state: IssueState::Open,
        milestone: None,
        labels: vec![],
        body: body.clone(),
        sub_issues: Links {
            nodes: vec![],
            total: 0,
        },
        blocked_by: Links {
            nodes: vec![],
            total: 0,
        },
    };
    let ticket = IssueRow {
        number: n2,
        id: NonEmpty::new("I_2").unwrap(),
        title: mutate_str(rng, "Ticket"),
        state: IssueState::Open,
        milestone: None,
        labels: vec![],
        body,
        sub_issues: Links {
            nodes: vec![],
            total: 0,
        },
        blocked_by: Links {
            nodes: vec![],
            total: 0,
        },
    };
    let _ = records::issue(&ticket);
    let _ = records::revision(&spec, &[&ticket]);
    let _ = records::fingerprint(&spec, &[&ticket]);
    let mut authors = BTreeSet::new();
    authors.insert("synthetic-bot".to_owned());
    records::records_oracle_tests::assert_oracles_match(
        &spec, &ticket, &comments, &retired, &authors,
    );
}

fn fuzz_models_and_rules(rng: &mut Rng) {
    let flags = crate::models::spawn_flags().unwrap();
    let md = mutate_str(rng, FLEET_MD_SEED);
    let _ = Rules::parse(&md, &flags);
    let _ = models::read(&md, &flags);
    let role = *rng.pick(&Role::ALL);
    let asked = if rng.coin() {
        write::Asked::Follows
    } else {
        write::Asked::Choice(Choice::named("codex", "gpt-6.2-sol", "medium").unwrap())
    };
    let _ = write::set(&md, role, &asked, &flags);
    let _ = crate::models::valid_host(&md);
    let acl = mutate_str(
        rng,
        "-rw-r--r--+ 1 syn syn 0 Nov 28 00:00 fleet.md\n 0: user:syn allow read\n",
    );
    let _ = crate::models::extended_acl(&acl);
    let _ = Fingerprint::parse(&md);
}

fn fuzz_cli_parsers(rng: &mut Rng) {
    let count = rng.below(6);
    let mut strings = Vec::with_capacity(count);
    let mut os_args = Vec::with_capacity(count);
    for _ in 0..count {
        let seed = *rng.pick(&[
            "ls",
            "show",
            "fleet",
            "tick",
            "due",
            "--dry-run",
            "--github-only",
            "--json",
            "--limit",
            "--offset",
            "-la",
            "--repository",
            "--read",
            "token",
            "on",
            "off",
            "validate",
            "plan",
            "apply",
            "export",
            "--project",
            "--adopt",
            "--from",
            "--yes",
            "--operation",
            "--",
            "syn",
        ]);
        let s = if rng.coin() {
            seed.to_owned()
        } else {
            mutate_str(rng, seed)
        };
        os_args.push(OsString::from(&s));
        strings.push(s);
    }
    let _ = crate::parse(&strings);
    let _ = crate::fleet::parse(&os_args);
    let _ = crate::fleet::tick::parse(&os_args);
    let _ = crate::github_token::parse(&strings);
    let _ = crate::loop_files::parse(&os_args);
    let _ = crate::loops::parse(&os_args);
    let _ = crate::init::usable(&os_args);
    let _ = crate::response::Request::new(&os_args);
    if let Some(first) = strings.first() {
        let _ = crate::clean(first);
        let _ = crate::loop_files::escape_untrusted(first);
    }
    let init_bytes = mutate_bytes(
        rng,
        br#"{"schema":"openwiz.cli-error.v1","command":"init","exit_code":2,"error":{"kind":"usage","message":"bad"}}"#,
    );
    let _ = crate::init::outcome(&init_bytes, (rng.next() % 12) as i32);
}

fn fuzz_github_parsers(rng: &mut Rng) {
    let deadline = Instant::now() + Duration::from_secs(60);
    let pr_list = if rng.coin() {
        mutate_json_str(rng, PR_LIST_SEED).into_bytes()
    } else {
        mutate_bytes(rng, PR_LIST_SEED.as_bytes())
    };
    let _ = openwiz_adapter_github::tick::document(&pr_list);
    let gh = mock_reads(pr_list);
    let _ = gh.pull_requests(deadline);

    let pr_view = if rng.coin() {
        mutate_json_str(rng, PR_VIEW_SEED).into_bytes()
    } else {
        mutate_bytes(rng, PR_VIEW_SEED.as_bytes())
    };
    let _ = tickets::pull_request(&pr_view);

    let issue_view = if rng.coin() {
        mutate_json_str(rng, ISSUE_VIEW_SEED).into_bytes()
    } else {
        mutate_bytes(rng, ISSUE_VIEW_SEED.as_bytes())
    };
    let _ = tickets::issue(&issue_view);

    let checks_bytes = mutate_bytes(rng, br#"[{"bucket":"pass","name":"ci"}]"#);
    let _ = tickets::checks(&checks_bytes);

    let ver_bytes = mutate_bytes(rng, b"gh version 2.100.0 (2026-10-01)\n");
    let _ = tickets::version(&ver_bytes);

    let repo_bytes = mutate_bytes(
        rng,
        br#"{"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.com/synthetic-owner/synthetic-repo"}"#,
    );
    let _ = tickets::repository(&repo_bytes);
    let _ = tickets::on_base(&mutate_bytes(rng, br#"{"ahead_by":0}"#));
    let _ = tickets::verdict_comments(&mutate_bytes(rng, br#"["VERDICT: APPROVE"]"#));

    let comments_bytes = mutate_bytes(
        rng,
        br#"[{"id":1,"author":"synthetic-bot","body":"hi","created":10,"updated":10}]"#,
    );
    let gh_c = mock_reads(comments_bytes);
    let _ = gh_c.comments(Number::new(1).unwrap(), deadline);
    let _ = gh_c.events(Number::new(1).unwrap(), deadline);
    let _ = gh_c.files(Number::new(1).unwrap(), deadline);
    let _ = gh_c.subject(
        &Commit::parse("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").unwrap(),
        deadline,
    );

    let md = mutate_str(rng, FLEET_MD_SEED);
    if let Ok(authors) = RecordAuthors::read(&md) {
        let login = mutate_str(rng, "synthetic-bot");
        let kind = mutate_str(rng, "User");
        let _ = authors.wrote(Some(&login), Some(&kind));
    }
    let _ = openwiz_adapter_github::fleets::is_branch(&md);
}

fn fuzz_planner(rng: &mut Rng) {
    let flags = crate::models::spawn_flags().unwrap();
    let rules = Rules::parse(FLEET_MD_SEED, &flags).unwrap();
    let n1 = Number::new(1).unwrap();
    let n2 = Number::new(2).unwrap();
    let n3 = Number::new(3).unwrap();
    let n10 = Number::new(10).unwrap();
    let c_a = Commit::parse("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").unwrap();
    let c_b = Commit::parse("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").unwrap();
    let fp = Fingerprint::parse(&"a".repeat(64)).unwrap();

    let pat = NonEmpty::new(mutate_str(rng, "crates/*/src/*.rs"))
        .unwrap_or_else(|| NonEmpty::new("a").unwrap());
    let changed_path = NonEmpty::new(mutate_str(rng, "crates/cli/src/main.rs"))
        .unwrap_or_else(|| NonEmpty::new("a").unwrap());

    let mut approval_rows = BTreeMap::new();
    approval_rows.insert(
        n2,
        if rng.coin() {
            Ready::Agent
        } else {
            Ready::Human
        },
    );
    let approval = if rng.coin() {
        Some(PlanApproval {
            approval: Approval {
                comment: n1,
                revision: n1,
                fingerprint: fp.clone(),
            },
            rows: approval_rows,
            approved_at: rng.next(),
        })
    } else {
        None
    };

    let pr = match rng.below(4) {
        0 => None,
        1 => Some(PrInput::Open(Box::new(OpenPr {
            fields: PrFields {
                number: n10,
                draft: rng.coin(),
                head_branch: NonEmpty::new("room/syn-2").unwrap(),
                head_commit: c_a.clone(),
                base_branch: NonEmpty::new("main").unwrap(),
                closes: vec![n2],
            },
            subject: mutate_str(rng, "#2: green: done"),
            ci: if rng.coin() {
                Some(CheckRun {
                    head_commit: c_a.clone(),
                    base_commit: c_b.clone(),
                    checks: vec![Check {
                        name: NonEmpty::new("ci").unwrap(),
                        result: *rng.pick(&[
                            CheckResult::Pass,
                            CheckResult::Fail,
                            CheckResult::Pending,
                            CheckResult::Skipping,
                            CheckResult::Cancel,
                        ]),
                    }],
                })
            } else {
                None
            },
            base_now: Some(c_b.clone()),
            reports: vec![ReportComment {
                comment: n3,
                text: mutate_str(
                    rng,
                    "VERDICT: APPROVE at aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                ),
            }],
            starts: vec![Start {
                id: OpId::parse("op-syn-1").unwrap(),
                state: StartState::Refused {
                    reason: StartReason::Refused,
                },
                logged: rng.coin(),
            }],
            records: Default::default(),
        }))),
        2 => Some(PrInput::Merged(MergeInput {
            pr: MergedPr {
                fields: PrFields {
                    number: n10,
                    draft: false,
                    head_branch: NonEmpty::new("room/syn-2").unwrap(),
                    head_commit: c_a.clone(),
                    base_branch: NonEmpty::new("main").unwrap(),
                    closes: vec![n2],
                },
                merge_commit: c_b.clone(),
                merged_at: Timestamp(rng.next() as i64),
            },
            read_back: rng.coin(),
        })),
        _ => Some(PrInput::Several(vec![n10, n3])),
    };

    let snapshot = Snapshot {
        default_branch: Observed::Complete(NonEmpty::new("main").unwrap()),
        fleets: Observed::Complete(vec![FleetInput {
            spec: n1,
            facts: if rng.coin() {
                Observed::Complete(FleetFacts {
                    issue: Issue {
                        title: "Spec".to_owned(),
                        state: if rng.coin() {
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
                    approval,
                    fingerprint_now: fp,
                    tickets: vec![TicketInput {
                        number: n2,
                        facts: Observed::Complete(TicketFacts {
                            issue: Issue {
                                title: "Ticket".to_owned(),
                                state: if rng.coin() {
                                    IssueState::Open
                                } else {
                                    IssueState::Closed
                                },
                                milestone: None,
                                labels: if rng.coin() {
                                    vec![NonEmpty::new("ready-for-agent").unwrap()]
                                } else {
                                    vec![NonEmpty::new("held").unwrap()]
                                },
                                owned_paths: None,
                                relies_on: None,
                                pending_question: None,
                            },
                            blockers: vec![BlockerInput {
                                number: n3,
                                state: IssueState::Closed,
                                merged: None,
                            }],
                            pr,
                            builder: if rng.coin() {
                                Some(Agent {
                                    thread: NonEmpty::new("thr_syn_1").unwrap(),
                                    archived: rng.coin(),
                                })
                            } else {
                                None
                            },
                            builder_source: None,
                            reviewers: vec![Reviewer {
                                pr: n10,
                                agent: Agent {
                                    thread: NonEmpty::new("thr_syn_2").unwrap(),
                                    archived: rng.coin(),
                                },
                                head: c_a.clone(),
                                last_activity_at: rng.next(),
                                given_up: rng.coin(),
                                output: None,
                            }],
                            starts: vec![],
                            relies_on: vec![pat],
                            holds: if rng.coin() {
                                vec![Hold {
                                    comment: n3,
                                    merged: MergeFact {
                                        number: n10,
                                        merge_commit: c_b.clone(),
                                    },
                                    files: vec![changed_path.clone()],
                                    notified: rng.coin(),
                                }]
                            } else {
                                vec![]
                            },
                            held_label_comment: if rng.coin() { Some(n3) } else { None },
                            question: if rng.coin() { Some(n3) } else { None },
                            records: TicketRecords::default(),
                        }),
                    }],
                    changes: vec![ContractChange {
                        merged: MergeInput {
                            pr: MergedPr {
                                fields: PrFields {
                                    number: n10,
                                    draft: false,
                                    head_branch: NonEmpty::new("room/syn-3").unwrap(),
                                    head_commit: c_a,
                                    base_branch: NonEmpty::new("main").unwrap(),
                                    closes: vec![n3],
                                },
                                merge_commit: c_b,
                                merged_at: Timestamp(rng.next() as i64),
                            },
                            read_back: rng.coin(),
                        },
                        files: vec![ChangedFile {
                            path: changed_path,
                            previous_path: None,
                            added: rng.coin(),
                        }],
                    }],
                    follow_ups: vec![],
                    records: SpecRecords::default(),
                })
            } else {
                Observed::Unread(vec![Problem::Graph])
            },
        }]),
    };

    let rand_now = rng.next();
    let now = *rng.pick(&[
        0u64,
        1,
        1_760_000_000_000,
        i64::MAX as u64,
        u64::MAX,
        rand_now,
    ]);
    let _ = tick::plan(&snapshot, &rules, now);
}

fn fuzz_end_to_end_tick(rng: &mut Rng) {
    let mut answers: HashMap<Vec<String>, Vec<u8>> = HashMap::new();
    let put = |map: &mut HashMap<Vec<String>, Vec<u8>>, argv: &[&str], body: Vec<u8>| {
        map.insert(argv.iter().map(|s| (*s).to_owned()).collect(), body);
    };
    let head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    let base = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    put(
        &mut answers,
        &[
            "repo",
            "view",
            "--json",
            openwiz_adapter_github::tick::REPOSITORY_FIELDS,
        ],
        br#"{"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.com/synthetic-owner/synthetic-repo"}"#.to_vec(),
    );
    put(
        &mut answers,
        &["repo", "view", "--json", "nameWithOwner,isPrivate"],
        br#"{"nameWithOwner":"synthetic-owner/synthetic-repo","isPrivate":true}"#.to_vec(),
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
        br#"[{"blockedBy":{"nodes":[],"totalCount":0},"body":"Spec","id":"I_1","labels":[],"milestone":null,"number":1,"state":"OPEN","subIssues":{"nodes":[{"id":"I_2","number":2,"state":"OPEN","title":"T2","url":"https://github.com/synthetic-owner/synthetic-repo/issues/2"}],"totalCount":1},"title":"Spec"},{"blockedBy":{"nodes":[],"totalCount":0},"body":"**Owned paths:** `a.rs`\n**Relies on:** nothing\n","id":"I_2","labels":[{"color":"0e8a16","description":"","id":"L1","name":"ready-for-agent"}],"milestone":null,"number":2,"state":"OPEN","subIssues":{"nodes":[],"totalCount":0},"title":"T2"}]"#.to_vec(),
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
        PR_LIST_SEED.as_bytes().to_vec(),
    );
    put(
        &mut answers,
        &[
            "api",
            "repos/{owner}/{repo}/git/ref/heads/main",
            "--jq",
            openwiz_adapter_github::tick::REF,
        ],
        format!(r#"{{"sha":"{base}"}}"#).into_bytes(),
    );
    let fleet_path = format!("repos/{{owner}}/{{repo}}/contents/docs/agents/fleet.md?ref={base}");
    put(
        &mut answers,
        &[
            "api",
            &fleet_path,
            "--header",
            "Accept: application/vnd.github.raw+json",
        ],
        FLEET_MD_SEED.as_bytes().to_vec(),
    );
    put(
        &mut answers,
        &[
            "api",
            "repos/{owner}/{repo}/issues/comments?per_page=100&page=1",
            "--jq",
            openwiz_adapter_github::tick::REPOSITORY_COMMENTS,
        ],
        br#"[]"#.to_vec(),
    );
    let cmp_path = format!("repos/{{owner}}/{{repo}}/compare/{base}...{base}");
    put(
        &mut answers,
        &[
            "api",
            &cmp_path,
            "--jq",
            "{status: .status, behind_by: .behind_by}",
        ],
        br#"{"status":"ahead","behind_by":0}"#.to_vec(),
    );
    let commit_path = format!("repos/{{owner}}/{{repo}}/commits/{head}");
    put(
        &mut answers,
        &[
            "api",
            &commit_path,
            "--jq",
            openwiz_adapter_github::tick::COMMIT,
        ],
        format!(r##"{{"sha":"{head}","subject":"#2: green"}}"##).into_bytes(),
    );

    let keys: Vec<Vec<String>> = answers.keys().cloned().collect();
    let victim = rng.pick(&keys).clone();
    if let Some(body) = answers.get_mut(&victim) {
        if let Ok(s) = std::str::from_utf8(body) {
            *body = mutate_json_str(rng, s).into_bytes();
        } else {
            *body = mutate_bytes(rng, body);
        }
    }

    let answers = Arc::new(answers);
    let handler: Arc<Execute> = Arc::new(move |call: &Invocation, _| {
        answers
            .get(call.argv())
            .cloned()
            .ok_or_else(|| SourceError::Unavailable {
                detail: "unmocked".to_owned(),
            })
    });
    let gh = TickReads::with_executor(Executor::supplied(handler));
    let deadline = Instant::now() + Duration::from_secs(30);
    if let Ok(inv) = Inventory::read(&gh, deadline)
        && let Ok(world) = World::read(&gh, None, Path::new(""), deadline, inv)
    {
        let _ = tick::plan(&world.snapshot, &world.rules, 1_760_000_000_000);
    }
}

fn run_fuzz(seed: u64, budget: Duration, min_iters: u64) -> u64 {
    let mut rng = Rng::new(seed);
    let start = Instant::now();
    let mut iters = 0u64;
    while iters < min_iters || start.elapsed() < budget {
        match (iters % 8) as usize {
            0 => fuzz_config(&mut rng),
            1 => fuzz_loops_documents(&mut rng),
            2 => fuzz_starts(&mut rng),
            3 => fuzz_records(&mut rng),
            4 => fuzz_models_and_rules(&mut rng),
            5 => fuzz_cli_parsers(&mut rng),
            6 => {
                if iters.is_multiple_of(16) {
                    fuzz_github_parsers(&mut rng);
                } else {
                    fuzz_planner(&mut rng);
                }
            }
            _ => {
                if iters.is_multiple_of(32) {
                    fuzz_end_to_end_tick(&mut rng);
                } else {
                    fuzz_records(&mut rng);
                }
            }
        }
        iters += 1;
    }
    iters
}

#[test]
fn fuzz_area1_smoke() {
    let iters = run_fuzz(0x5eed_cafe_1234_5678, Duration::from_millis(50), 1400);
    assert!(iters >= 1400);
}

#[test]
#[ignore = "long-running release fuzz harness; set OPENWIZ_FUZZ_SECONDS"]
fn fuzz_area1_soak() {
    let secs: u64 = std::env::var("OPENWIZ_FUZZ_SECONDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1200);
    let seed: u64 = std::env::var("OPENWIZ_FUZZ_SEED")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0x5eed_cafe_1234_5678);
    let start = Instant::now();
    let iters = run_fuzz(seed, Duration::from_secs(secs), 10_000);
    println!(
        "fuzz_area1_soak seed={seed} completed {iters} iterations in {:.2}s (0 panics)",
        start.elapsed().as_secs_f64()
    );
}
