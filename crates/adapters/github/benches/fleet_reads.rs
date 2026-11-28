use std::fmt::Write as _;
use std::hint::black_box;
use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_adapter_github::plan::{
    Reader as PlanReader, Request as PlanRequest, strict as plan_strict,
};
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::TickReads;
use openwiz_core::fleet::fleets::FleetsSource;
use openwiz_core::fleet::model::Number;

fn median_ns(mut call: impl FnMut()) -> u128 {
    let mut iters = 1u32;
    loop {
        let start = Instant::now();
        for _ in 0..iters {
            call();
        }
        if start.elapsed() >= Duration::from_millis(50) || iters >= 5_000 {
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

fn report(name: &str, bytes: usize, ns: u128) {
    let mib_s = (bytes as f64) / (ns as f64) * 1_000_000_000.0 / (1024.0 * 1024.0);
    println!("BENCH {name} bytes={bytes} median_ns={ns} throughput_mib_s={mib_s:.2}");
}

fn issues_payload(count: usize) -> Vec<u8> {
    let mut out = String::with_capacity(count * 1200);
    out.push('[');
    for i in 1..=count {
        if i > 1 {
            out.push(',');
        }
        let state = if i % 5 == 0 { "CLOSED" } else { "OPEN" };
        let milestone = if i % 5 == 0 {
            "null".to_owned()
        } else {
            format!(
                r#"{{"description":"Synthetic milestone {m}","dueOn":null,"number":{m},"title":"v0.2.{m}"}}"#,
                m = (i % 7) + 1
            )
        };
        let links = if i % 3 == 0 {
            let a = i + 10_000;
            let b = i + 20_000;
            format!(
                r#"{{"nodes":[{{"id":"I_syn_{a}","number":{a},"state":"OPEN","title":"Synthetic dep {a}","url":"https://github.invalid/syn-owner/syn-repo/issues/{a}"}},{{"id":"I_syn_{b}","number":{b},"state":"CLOSED","title":"Synthetic dep {b}","url":"https://github.invalid/syn-owner/syn-repo/issues/{b}"}}],"totalCount":2}}"#
            )
        } else {
            r#"{"nodes":[],"totalCount":0}"#.to_owned()
        };
        let _ = write!(
            out,
            r#"{{"blockedBy":{links},"body":"Synthetic ticket #{i}\n\n**Owned paths:** `crates/adapters/github/src/fleets.rs`\n**Relies on:** nothing\n\nDetails line with \"quotes\" and synthetic acceptance criteria for item {i}.","id":"I_kwDO_syn_{i:05}","labels":[{{"color":"0e8a16","description":"Ready","id":"LA_syn_1","name":"ready-for-agent"}},{{"color":"1d76db","description":"Area","id":"LA_syn_2","name":"area:github"}},{{"color":"fbca04","description":"Priority","id":"LA_syn_3","name":"p1"}}],"milestone":{milestone},"number":{i},"state":"{state}","subIssues":{links},"title":"Synthetic ticket {i}: adapter throughput check"}}"#
        );
    }
    out.push(']');
    out.into_bytes()
}

fn prs_payload(count: usize) -> Vec<u8> {
    let mut out = String::with_capacity(count * 900);
    out.push('[');
    for i in 1..=count {
        if i > 1 {
            out.push(',');
        }
        let head_oid = format!("{:040x}", i);
        let merge_oid = format!("{:040x}", i + 1_000_000);
        let (state, merge_commit, merged_at) = match i % 5 {
            0 => ("CLOSED", "null".to_owned(), "null".to_owned()),
            1 | 2 => (
                "MERGED",
                format!(r#"{{"oid":"{merge_oid}"}}"#),
                r#""2026-10-30T18:30:00Z""#.to_owned(),
            ),
            _ => ("OPEN", "null".to_owned(), "null".to_owned()),
        };
        let draft = if i % 7 == 0 { "true" } else { "false" };
        let issue_a = i * 2;
        let issue_b = i * 2 + 1;
        let refs = if i % 4 == 0 {
            format!(
                r#"[{{"id":"I_syn_{issue_a}","number":{issue_a},"repository":{{"id":"R_syn_1","name":"syn-repo","owner":{{"id":"O_syn_1","login":"syn-owner"}}}},"url":"https://github.invalid/syn-owner/syn-repo/issues/{issue_a}"}},{{"id":"I_syn_{issue_b}","number":{issue_b},"repository":{{"id":"R_syn_1","name":"syn-repo","owner":{{"id":"O_syn_1","login":"syn-owner"}}}},"url":"https://github.invalid/syn-owner/syn-repo/issues/{issue_b}"}}]"#
            )
        } else {
            format!(
                r#"[{{"id":"I_syn_{issue_a}","number":{issue_a},"repository":{{"id":"R_syn_1","name":"syn-repo","owner":{{"id":"O_syn_1","login":"syn-owner"}}}},"url":"https://github.invalid/syn-owner/syn-repo/issues/{issue_a}"}}]"#
            )
        };
        let _ = write!(
            out,
            r#"{{"baseRefName":"main","closingIssuesReferences":{refs},"headRefName":"room/syn-branch-{i}","headRefOid":"{head_oid}","isDraft":{draft},"mergeCommit":{merge_commit},"mergedAt":{merged_at},"number":{i},"state":"{state}","title":"Synthetic PR #{i}: parser speedup"}}"#
        );
    }
    out.push(']');
    out.into_bytes()
}

fn checks_payload(count: usize) -> Vec<u8> {
    let buckets = ["pass", "fail", "pending", "skipping", "cancel"];
    let mut out = String::with_capacity(count * 64);
    out.push('[');
    for i in 0..count {
        if i > 0 {
            out.push(',');
        }
        let bucket = buckets[i % buckets.len()];
        let _ = write!(out, r#"{{"bucket":"{bucket}","name":"syn-check-{i:03}"}}"#);
    }
    out.push(']');
    out.into_bytes()
}

fn plan_issues_connection_payload(count: usize) -> Vec<u8> {
    let mut out = String::with_capacity(count * 1000);
    out.push_str(r#"{"nodes":["#);
    for i in 1..=count {
        if i > 1 {
            out.push(',');
        }
        let state = if i % 5 == 0 { "CLOSED" } else { "OPEN" };
        let a = i + 10_000;
        let _ = write!(
            out,
            r#"{{"number":{i},"title":"Synthetic plan ticket {i}","url":"https://github.invalid/syn-owner/syn-repo/issues/{i}","state":"{state}","milestone":{{"number":1,"title":"0.2.0"}},"parent":{{"number":1,"url":"https://github.invalid/syn-owner/syn-repo/issues/1"}},"labels":{{"totalCount":2,"pageInfo":{{"hasNextPage":false,"endCursor":null}},"nodes":[{{"name":"ready-for-agent"}},{{"name":"area:github"}}]}},"subIssues":{{"totalCount":1,"pageInfo":{{"hasNextPage":false,"endCursor":null}},"nodes":[{{"number":{a},"url":"https://github.invalid/syn-owner/syn-repo/issues/{a}"}}]}},"blockedBy":{{"totalCount":0,"pageInfo":{{"hasNextPage":false,"endCursor":null}},"nodes":[]}},"closedByPullRequestsReferences":{{"totalCount":1,"pageInfo":{{"hasNextPage":false,"endCursor":null}},"nodes":[{{"number":{a},"url":"https://github.invalid/syn-owner/syn-repo/pull/{a}"}}]}}}}"#
        );
    }
    let _ = write!(
        out,
        r#"],"totalCount":{count},"pageInfo":{{"hasNextPage":false,"endCursor":null}}}}"#
    );
    out.into_bytes()
}

fn supplied(bytes: Vec<u8>) -> Executor {
    let bytes = Arc::new(bytes);
    Executor::supplied(Arc::new(move |_, _| Ok((*bytes).clone())))
}

fn main() {
    let deadline = Instant::now() + Duration::from_secs(3600);

    let issues_bytes = issues_payload(1_000);
    let issues_len = issues_bytes.len();
    let fleets_issues = GitHubFleets::with_executor(supplied(issues_bytes));
    let ns = median_ns(|| {
        let got = fleets_issues.issues(deadline).unwrap();
        black_box(got);
    });
    report("fleets_issues_1000", issues_len, ns);

    let prs_bytes = prs_payload(1_000);
    let prs_len = prs_bytes.len();
    let fleets_prs = GitHubFleets::with_executor(supplied(prs_bytes.clone()));
    let ns = median_ns(|| {
        let got = fleets_prs.stock_pull_requests(deadline).unwrap();
        black_box(got);
    });
    report("fleets_stock_prs_1000", prs_len, ns);

    let checks_bytes = checks_payload(200);
    let checks_len = checks_bytes.len();
    let fleets_checks = GitHubFleets::with_executor(supplied(checks_bytes));
    let pr_num = Number::new(42).unwrap();
    let ns = median_ns(|| {
        let got = fleets_checks.checks(pr_num, deadline).unwrap();
        black_box(got);
    });
    report("fleets_checks_200", checks_len, ns);

    let tick_prs = TickReads::with_executor(supplied(prs_bytes));
    let ns = median_ns(|| {
        let got = tick_prs.pull_requests(deadline).unwrap();
        black_box(got);
    });
    report("tick_pull_requests_1000", prs_len, ns);

    let plan_bytes = plan_issues_connection_payload(500);
    let plan_reader = PlanReader::new("/synthetic/unused");
    let ns = median_ns(|| {
        let page = plan_strict(black_box(&plan_bytes)).unwrap();
        let got = plan_reader.connection(PlanRequest::Issues, Some(page), deadline);
        black_box(got);
    });
    report("plan_strict_and_connection_500", plan_bytes.len(), ns);
}
