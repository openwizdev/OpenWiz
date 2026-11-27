use std::hint::black_box;
use std::time::{Duration, Instant};

use openwiz_adapter_cloudroom::loop_files::{CheckText, parse_loop_list, plan, read_loop};

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
            return samples[5];
        }
        iters = iters.saturating_mul(2);
    }
}

fn report(name: &str, bytes: usize, ns: u128) {
    let mib_s = (bytes as f64) / (ns as f64) * 1_000_000_000.0 / (1024.0 * 1024.0);
    println!("BENCH {name} bytes={bytes} median_ns={ns} throughput_mib_s={mib_s:.2}");
}

fn loop_list(n: usize, marked: bool) -> Vec<u8> {
    let mut out = String::from("{\"automations\": [\n");
    for i in 0..n {
        if i != 0 {
            out.push_str(",\n");
        }
        let marker = if marked {
            format!(" [wizloop:syn-triage-{i}]")
        } else {
            String::new()
        };
        out.push_str(&format!(
            r##"  {{"id": "loop_syn_{i}", "project_id": "prj_syn_0001", "session_id": "thr_syn_0001", "name": "Synthetic triage {i}{marker}", "cron": "*/10 * * * *", "timezone": "UTC", "run_at": null, "webhook": false, "new_thread": true, "script": "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REPO='synthetic-org/synthetic-repo'\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n", "agent": {{"provider": "synthetic-provider", "model": "synthetic-model", "reasoning": "medium"}}, "secrets": ["SYNTHETIC_TOKEN", ".env"], "priority": 2, "prompt": "Synthetic: triage the due items the check printed below. Read \"due.txt\" first, then report each item on its own line.", "enabled": true, "last_error": null, "last_run_at": "2030-01-01T00:00:00Z", "next_run_at": "2030-01-01T00:10:00Z", "runs": 3}}"##
        ));
    }
    out.push_str("\n]}\n");
    out.into_bytes()
}

const LOOP_FILE: &str = r#"---
id: "params-env"
name: "Params reach the check as data"
trigger: {"cron": "30 6 * * *", "timezone": "UTC"}
check: {"run": "params-env/check.sh", "timeout": 60}
thread: "new"
params: {"repo": "example-org/example-repo", "ref": "release/\";printf${IFS}WAKE;false${IFS}\"", "title": "it's $(touch marker) `touch marker`", "spec": 7, "note": "the check's output"}
---
Report {{note}} for spec {{spec}} in {{repo}}.
"#;

const CHECK: &str = "#!/bin/sh\n# $WIZLOOP_PARAM_REPO, $WIZLOOP_PARAM_REF, $WIZLOOP_PARAM_TITLE and $WIZLOOP_PARAM_SPEC.\nexit 0\n";

fn main() {
    let list = loop_list(300, true);
    assert_eq!(parse_loop_list(&list).unwrap().len(), 300);
    let ns = median_ns(|| {
        black_box(parse_loop_list(black_box(&list)).unwrap());
    });
    report("loop_list_300", list.len(), ns);

    let mut check = |_: &str| CheckText::Text(CHECK.to_owned());
    let first = read_loop(LOOP_FILE.as_bytes(), &mut check);
    assert!(first.refusals.is_empty(), "{:?}", first.refusals);
    let ns = median_ns(|| {
        black_box(read_loop(black_box(LOOP_FILE.as_bytes()), &mut check));
    });
    report("loop_file_params", LOOP_FILE.len(), ns);

    let files: Vec<_> = (0..50)
        .map(|i| {
            let text = LOOP_FILE.replace("\"params-env\"", &format!("\"synthetic-file-{i}\""));
            (
                format!("loops/{i}.md"),
                read_loop(text.as_bytes(), &mut check),
            )
        })
        .collect();
    let live = parse_loop_list(&loop_list(300, false)).unwrap();
    let planned = plan(&files, &live, "prj_syn_0001", &[], 1_893_456_000);
    assert_eq!(planned.items.len(), 50);
    assert_eq!(planned.unmanaged.len(), 300);
    let ns = median_ns(|| {
        black_box(plan(
            black_box(&files),
            black_box(&live),
            "prj_syn_0001",
            &[],
            1_893_456_000,
        ));
    });
    report("loop_plan_50x300", 0, ns);
}
