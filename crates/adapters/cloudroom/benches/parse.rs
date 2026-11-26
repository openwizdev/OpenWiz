//! Hot-path CloudRoom list reads.
//! Release numbers: `cargo bench --bench parse -p openwiz-adapter-cloudroom`

use std::hint::black_box;
use std::time::{Duration, Instant};

use openwiz_adapter_cloudroom::new_thread::{parse_projects, parse_shown_thread};

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

fn projects(n: usize) -> Vec<u8> {
    let mut out = b"[".to_vec();
    for i in 0..n {
        if i != 0 {
            out.push(b',');
        }
        out.extend(
            format!(
                r#"{{"id":"prj_syn_{i}","name":"Synthetic {i}","kind":"project","gitRemoteUrl":"https://github.com/example/repo{i}"}}"#
            )
            .as_bytes(),
        );
    }
    out.push(b']');
    out
}

fn shown() -> Vec<u8> {
    br#"{"thread":{"id":"thr_syn_bench","status":"running","providerId":"synthetic","lastError":null},"execution":{"model":"synthetic-model","reasoningLevel":"low"}}"#
        .to_vec()
}

fn main() {
    let bytes = projects(4_000);
    let ns = median_ns(|| {
        black_box(parse_projects(black_box(&bytes)).unwrap());
    });
    report("project_list_4000", bytes.len(), ns);

    let shown = shown();
    let ns = median_ns(|| {
        black_box(parse_shown_thread(black_box(&shown), "thr_syn_bench").unwrap());
    });
    report("thread_show", shown.len(), ns);
}
