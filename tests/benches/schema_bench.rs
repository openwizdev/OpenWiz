#![allow(
    dead_code,
    reason = "bench exercises selected entrypoints from shared test validator modules"
)]

#[path = "../support/schema.rs"]
mod schema;

#[path = "../fleet/schema.rs"]
mod fleet_schema;

#[path = "../new-thread/pattern.rs"]
mod pattern;

use serde_json::{Value, json};
use std::fs;
use std::hint::black_box;
use std::time::{Duration, Instant};

fn bench<F: FnMut()>(name: &str, bytes: usize, mut f: F) {
    let warm_end = Instant::now() + Duration::from_millis(30);
    let mut warm = 0usize;
    while Instant::now() < warm_end || warm < 3 {
        f();
        warm += 1;
    }
    let t0 = Instant::now();
    f();
    let single = t0.elapsed().as_nanos().max(1);
    let batch = ((10_000_000u128) / single).clamp(1, 50_000) as usize;
    let mut samples = Vec::with_capacity(11);
    for _ in 0..11 {
        let s = Instant::now();
        for _ in 0..batch {
            f();
        }
        samples.push(s.elapsed().as_nanos() as f64 / batch as f64);
    }
    samples.sort_by(|a, b| a.total_cmp(b));
    let med = samples[5];
    let mib_s = if bytes > 0 {
        (bytes as f64 / (1024.0 * 1024.0)) / (med / 1e9)
    } else {
        0.0
    };
    println!("{name:<36} | {bytes:>7} B | {med:>12.1} ns | {mib_s:>8.2} MiB/s");
}

fn load(rel: &str) -> (usize, Value) {
    let path = format!("{}/../{rel}", env!("CARGO_MANIFEST_DIR"));
    let text = fs::read_to_string(&path).expect("fixture readable");
    let bytes = text.len();
    (bytes, serde_json::from_str(&text).expect("fixture JSON"))
}

fn main() {
    let (_, inv_schema) = load("contracts/inventory.v1.schema.json");
    let (env_bytes, env_val) = load("tests/fixtures/envelopes/ls-long-complete.json");
    let (_, loops_schema) = load("contracts/loops.v1.schema.json");
    let (loop_bytes, loop_val) = load("loops/example.json");
    let (fleet_bytes, fleet_schema_val) = load("contracts/fleet.v1.schema.json");

    let star_pat = "^a*a*a*a*a*a*a*a*a*a*b$";
    let star_schema = json!({"type": "string", "pattern": star_pat});
    let star_text = "a".repeat(12);
    let star_val = Value::String(star_text.clone());

    println!(
        "{:<36} | {:>9} | {:>15} | {:>14}",
        "Bench", "Bytes", "Median", "Throughput"
    );
    println!("{}", "-".repeat(84));

    bench("schema::validate(ls-long-complete)", env_bytes, || {
        black_box(schema::validate(
            black_box(&inv_schema),
            black_box(&env_val),
        ));
    });
    bench("fleet_schema::lint(fleet)", fleet_bytes, || {
        black_box(fleet_schema::lint(black_box(&fleet_schema_val)));
    });
    bench("pattern::validate(loops/example)", loop_bytes, || {
        black_box(pattern::validate(
            black_box(&loops_schema),
            black_box(&loop_val),
        ));
    });
    bench("schema::validate(a*x10_b_on_12a)", star_text.len(), || {
        black_box(schema::validate(
            black_box(&star_schema),
            black_box(&star_val),
        ));
    });
    bench("fleet::validate(a*x10_b_on_12a)", star_text.len(), || {
        black_box(fleet_schema::validate(
            black_box(&star_schema),
            black_box(&star_val),
        ));
    });
    bench("pattern::validate(a*x10_b_on_12a)", star_text.len(), || {
        black_box(pattern::validate(
            black_box(&star_schema),
            black_box(&star_val),
        ));
    });
}
