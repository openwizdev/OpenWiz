//! Hot-path JSON reads: fleet tick documents and issue view.
//! Release numbers: `cargo bench --bench parse -p openwiz-adapter-github`

use std::hint::black_box;
use std::time::{Duration, Instant};

use openwiz_adapter_github::tick;
use openwiz_adapter_github::tickets;

fn median_ns(mut call: impl FnMut()) -> u128 {
    let mut iters = 1u32;
    loop {
        let start = Instant::now();
        for _ in 0..iters {
            call();
        }
        let elapsed = start.elapsed();
        if elapsed >= Duration::from_millis(30) || iters >= 20_000 {
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

fn tick_payload(items: usize) -> Vec<u8> {
    let mut out = b"[".to_vec();
    for i in 0..items {
        if i != 0 {
            out.push(b',');
        }
        out.extend(format!(
            r#"{{"id":{i},"event":"labeled","label":"ready-for-agent","body":"synthetic comment {i}","at":1700000000000}}"#
        ).as_bytes());
    }
    out.push(b']');
    out
}

fn issue_payload(body_bytes: usize) -> Vec<u8> {
    let body = "x".repeat(body_bytes);
    format!(
        r#"{{"blockedBy":{{"nodes":[{{"id":"n","number":5,"state":"OPEN","title":"t","url":"u/issues/5"}}],"totalCount":1}},"body":"{body}\n**Owned paths:** `a.rs`\n**Relies on:** nothing","comments":[],"closedByPullRequestsReferences":[{{"id":"p","number":9,"repository":{{"id":"r"}},"url":"u/pull/9"}}],"labels":[{{"color":"c","description":"d","id":"l","name":"ready-for-agent"}}],"milestone":{{"description":"d","dueOn":null,"number":7,"title":"0.9.1"}},"state":"OPEN","subIssues":{{"nodes":[],"totalCount":0}},"title":"Synthetic"}}"#
    )
    .into_bytes()
}

fn main() {
    let tick_bytes = tick_payload(4_000);
    let ns = median_ns(|| {
        black_box(tick::document(black_box(&tick_bytes)).unwrap());
    });
    report("tick_document_4000", tick_bytes.len(), ns);

    let issue_bytes = issue_payload(256 * 1024);
    let ns = median_ns(|| {
        black_box(tickets::issue(black_box(&issue_bytes)).unwrap());
    });
    report("issue_view_256kib_body", issue_bytes.len(), ns);
}
