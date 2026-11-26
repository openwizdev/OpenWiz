//! SHA-256 used for prompt, start and fleet-fingerprint digests.
//! Release numbers: `cargo bench --bench sha256 -p openwiz-core`

use std::hint::black_box;
use std::time::{Duration, Instant};

use openwiz_core::messaging::sha256_hex;

fn median_ns(mut call: impl FnMut()) -> u128 {
    let mut iters = 1u32;
    loop {
        let start = Instant::now();
        for _ in 0..iters {
            call();
        }
        let elapsed = start.elapsed();
        if elapsed >= Duration::from_millis(30) || iters >= 50_000 {
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

fn main() {
    let short = b"openwiz.prompt.attachments.v1\n";
    let ns = median_ns(|| {
        black_box(sha256_hex(black_box(short)));
    });
    report("sha256_short", short.len(), ns);

    let page = vec![b'a'; 4096];
    let ns = median_ns(|| {
        black_box(sha256_hex(black_box(&page)));
    });
    report("sha256_4kib", page.len(), ns);

    let big = vec![b'a'; 1024 * 1024];
    let ns = median_ns(|| {
        black_box(sha256_hex(black_box(&big)));
    });
    report("sha256_1mib", big.len(), ns);
}
