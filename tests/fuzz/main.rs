use std::cell::Cell;
use std::collections::BTreeSet;
use std::fs;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_adapter_github::process::Executor;
use openwiz_adapter_github::tick::TickReads;
use openwiz_core::fleet::fleets::FleetsSource;
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::tick::Rules;
use openwiz_core::models::SpawnFlags;
use serde_json::Value;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
const TOKENS: &[&[u8]] = &[
    b"null",
    b"true",
    b"false",
    b"0",
    b"-0",
    b"1e999",
    b"-1",
    b"18446744073709551616",
    b"0.5",
    b"\"\"",
    b"\"\\u0000\"",
    b"\"\\ud800\"",
    b"{}",
    b"[]",
    b"[[[[[[[[",
    b"]]]]]]]]",
    b"\"number\":",
    b"\"id\":",
    b"\"state\":\"OPEN\"",
    b"\"state\":\"MERGED\"",
    b"\"nodes\":[",
    b"\"totalCount\":",
    b"\"closingIssuesReferences\":",
    b"\"subIssues\":",
    b"\"blockedBy\":",
    b"| --- | --- | --- |\n",
    b"## Builder\n",
    b"`--provider codex`",
    b"\n",
    b"\r\n",
    b"\xff",
    b"\xe2\x80\xa8",
];

thread_local! {
    static QUIET: Cell<bool> = const { Cell::new(false) };
}

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: usize) -> usize {
        if n == 0 {
            0
        } else {
            (self.next() % n as u64) as usize
        }
    }
}

fn mutate(rng: &mut Rng, corpus: &[Vec<u8>]) -> Vec<u8> {
    let mut input = corpus[rng.below(corpus.len())].clone();
    for _ in 0..1 + rng.below(4) {
        let len = input.len();
        let at = rng.below(len + 1);
        match rng.below(7) {
            0 if len > 0 => input[at.min(len - 1)] ^= 1 << rng.below(8),
            1 if len > 0 => {
                let bytes = b"{}[]\",:\\0-e ";
                input[at.min(len - 1)] = bytes[rng.below(bytes.len())];
            }
            2 => {
                let token = TOKENS[rng.below(TOKENS.len())];
                input.splice(at..at, token.iter().copied());
            }
            3 if len > 0 => {
                let end = (at + 1 + rng.below(32)).min(len);
                input.drain(at.min(end)..end);
            }
            4 if len > 0 => {
                let end = (at + 1 + rng.below(64)).min(len);
                let piece = input[at.min(end)..end].to_vec();
                input.splice(end..end, piece);
            }
            5 => {
                let other = &corpus[rng.below(corpus.len())];
                if !other.is_empty() {
                    let from = rng.below(other.len());
                    let to = (from + 1 + rng.below(128)).min(other.len());
                    let end = (at + rng.below(128)).min(len);
                    input.splice(at..end, other[from..to].iter().copied());
                }
            }
            _ => input.truncate(at),
        }
    }
    input
}

type Check = fn(&[u8]) -> Result<String, String>;

fn same_as_serde(name: &str, input: &[u8], parsed: Option<Value>) -> Result<String, String> {
    match parsed {
        None => Ok(format!("{name}: refused")),
        Some(v) => match serde_json::from_slice::<Value>(input) {
            Ok(plain) if plain == v => Ok(format!("{name}: accepted")),
            other => Err(format!(
                "{name} accepted what serde_json reads as {other:?}"
            )),
        },
    }
}

fn supplied(input: &[u8]) -> Executor {
    let bytes = input.to_vec();
    Executor::supplied(Arc::new(move |_, _| Ok(bytes.clone())))
}

fn shape<T, E: std::fmt::Debug>(result: &Result<T, E>) -> String {
    match result {
        Ok(_) => "ok".into(),
        Err(e) => format!("{e:?}").chars().take(80).collect(),
    }
}

fn targets() -> Vec<(&'static str, Check)> {
    vec![
        ("tick_document", |b| {
            same_as_serde(
                "tick::document",
                b,
                openwiz_adapter_github::tick::document(b).ok(),
            )
        }),
        ("plan_strict", |b| {
            same_as_serde(
                "plan::strict",
                b,
                openwiz_adapter_github::plan::strict(b).ok(),
            )
        }),
        ("decisions_document", |b| {
            same_as_serde(
                "decisions::document",
                b,
                openwiz_adapter_github::decisions::document(b),
            )
        }),
        ("fleets_reads", |b| {
            let source = GitHubFleets::with_executor(supplied(b));
            let deadline = Instant::now() + Duration::from_secs(60);
            let one = Number::new(1).expect("one");
            Ok([
                shape(&source.version(deadline)),
                shape(&source.repository(deadline)),
                shape(&source.issues(deadline)),
                shape(&source.pull_requests(deadline)),
                shape(&source.checks(one, deadline)),
                shape(&source.comments(one, deadline)),
            ]
            .join("|"))
        }),
        ("tick_reads", |b| {
            let gh = TickReads::with_executor(supplied(b));
            let deadline = Instant::now() + Duration::from_secs(60);
            let commit = Commit::parse(&"a".repeat(40)).expect("forty hex digits");
            Ok([
                shape(&gh.pull_requests(deadline)),
                shape(&gh.repository(deadline)),
                shape(&gh.branch("main", deadline)),
                shape(&gh.contains(&commit, &commit, deadline)),
                shape(&gh.rules(&commit, deadline)),
                shape(&gh.comments(Number::new(1).expect("one"), deadline)),
            ]
            .join("|"))
        }),
        ("rules_parse", |b| {
            let flags = SpawnFlags {
                provider: "--provider".into(),
                model: "--model".into(),
                effort: "--reasoning-level".into(),
            };
            Ok(shape(&Rules::parse(&String::from_utf8_lossy(b), &flags)))
        }),
    ]
}

fn files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            files(&path, out);
        } else if path.extension().is_some_and(|e| e == "json" || e == "md") {
            out.push(path);
        }
    }
}

fn seeds() -> Vec<Vec<u8>> {
    let mut paths = Vec::new();
    files(&Path::new(ROOT).join("tests/fixtures/github"), &mut paths);
    paths.push(Path::new(ROOT).join("docs/agents/fleet.md"));
    paths.sort();
    let mut out = BTreeSet::new();
    for path in paths {
        let Ok(bytes) = fs::read(&path) else { continue };
        if let Ok(Value::Object(scenario)) = serde_json::from_slice::<Value>(&bytes)
            && let Some(Value::Array(responses)) = scenario.get("responses")
        {
            for r in responses {
                if let Some(s) = r["stdout"].as_str() {
                    out.insert(s.as_bytes().to_vec());
                }
            }
        }
        if bytes.len() <= 256 * 1024 {
            out.insert(bytes);
        }
    }
    out.into_iter().collect()
}

fn run(check: Check, input: &[u8]) -> Result<String, String> {
    QUIET.with(|q| q.set(true));
    let caught = catch_unwind(AssertUnwindSafe(|| check(input)));
    QUIET.with(|q| q.set(false));
    match caught {
        Ok(result) => result,
        Err(panic) => Err(format!(
            "panicked: {}",
            panic
                .downcast_ref::<&str>()
                .map(|s| (*s).to_owned())
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_default()
        )),
    }
}

fn minimize(check: Check, input: &[u8]) -> Vec<u8> {
    let mut best = input.to_vec();
    let mut chunk = best.len() / 2;
    while chunk > 0 {
        let mut at = 0;
        while at < best.len() {
            let mut smaller = best.clone();
            smaller.drain(at..(at + chunk).min(best.len()));
            if run(check, &smaller).is_err() {
                best = smaller;
            } else {
                at += chunk;
            }
        }
        chunk /= 2;
    }
    best
}

#[test]
fn the_area_four_parsers_never_panic_and_never_disagree_with_serde_json() {
    let seconds: u64 = std::env::var("OPENWIZ_FUZZ_SECONDS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let seed: u64 = std::env::var("OPENWIZ_FUZZ_SEED")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0x0123_4567_89ab_cdef);
    let base = seeds();
    assert!(base.len() > 10, "too few seeds: {}", base.len());
    let loud = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if !QUIET.with(Cell::get) {
            loud(info);
        }
    }));
    let all = targets();
    let share = Duration::from_secs(seconds) / u32::try_from(all.len()).expect("few targets");
    let mut failures = Vec::new();
    for (name, check) in all {
        let mut rng = Rng(seed ^ name.len() as u64 ^ 0x9e37_79b9_7f4a_7c15);
        let mut corpus = base.clone();
        let mut seen = BTreeSet::new();
        let started = Instant::now();
        let mut runs = 0u64;
        while runs < 400 || started.elapsed() < share {
            let input = mutate(&mut rng, &corpus);
            runs += 1;
            match run(check, &input) {
                Ok(outcome) => {
                    if seen.insert(outcome) && corpus.len() < 4096 {
                        corpus.push(input);
                    }
                }
                Err(why) => {
                    let small = minimize(check, &input);
                    failures.push(format!(
                        "{name}: {why}\n  input: {:?}",
                        String::from_utf8_lossy(&small)
                    ));
                    break;
                }
            }
        }
        if seconds > 0 {
            println!(
                "FUZZ {name} runs={runs} outcomes={} corpus={}",
                seen.len(),
                corpus.len()
            );
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
