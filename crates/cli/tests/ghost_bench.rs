#[path = "../src/ghost/bench.rs"]
mod bench;
#[path = "../../../ci/ghost-bench.rs"]
mod gate;
#[path = "../src/ghost/log.rs"]
mod log;
#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../../../tests/support/schema.rs"]
mod schema;

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Value, json};

static TEMP: AtomicU64 = AtomicU64::new(0);

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixtures() -> PathBuf {
    repo_root().join("contracts/fixtures/ghost")
}

fn context_pack() -> PathBuf {
    fixtures().join("context-pack.json")
}

fn temp_state(name: &str) -> PathBuf {
    let n = TEMP.fetch_add(1, Ordering::Relaxed);
    let dir = std::env::temp_dir().join(format!("ow-ghost-{name}-{}-{n}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn validate(def_name: &str, value: &Value) -> Vec<String> {
    let mut root = read_json(&repo_root().join("contracts/ghost.v1.schema.json"));
    root.as_object_mut().unwrap().insert(
        "$ref".to_owned(),
        Value::String(format!("#/$defs/{def_name}")),
    );
    schema::validate(&root, value)
}

fn near(value: &Value, expect: f64) {
    let got = value.as_f64().unwrap_or(f64::NAN);
    assert!((got - expect).abs() < 1e-9, "{got} != {expect}");
}

fn env_empty(name: &str) -> Option<OsString> {
    let _ = name;
    None
}

fn baseline() -> Value {
    read_json(&fixtures().join("bench-baseline.json"))
}

#[test]
fn fixture_model_matches_the_recall_rows() {
    let pack = context_pack();
    let cases = [
        ("J1", Some(" all recs")),
        ("approve #4", Some("2 and merge")),
        ("ship magic", Some("-link sign-in")),
        ("all r", Some("ecs")),
        ("the seat bil", Some("ling spec")),
        ("zzq", None),
    ];
    for (prefix, ghost) in cases {
        let got = bench::fixture_suffix(&pack, prefix, bench::FixtureModel::Baseline).unwrap();
        assert_eq!(got.as_deref(), ghost, "prefix {prefix}");
    }
    let weak = bench::fixture_suffix(&pack, "J1", bench::FixtureModel::Weak).unwrap();
    assert_eq!(weak, None);
}

#[test]
fn bench_report_matches_the_recorded_baseline_and_schema() {
    let report = bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Baseline,
        None,
    )
    .unwrap();
    let errors = validate("bench_report", &report);
    assert!(errors.is_empty(), "{}", errors.join("\n"));
    let recorded = baseline();
    let expect = &recorded["recorded"];
    assert_eq!(report["messages"], expect["messages"]);
    assert_eq!(report["overall"]["shown"], expect["shown"]);
    assert_eq!(report["overall"]["accepted"], expect["accepted"]);
    near(
        &report["overall"]["acceptance_rate"],
        expect["acceptance_rate"].as_f64().unwrap(),
    );
    near(
        &report["overall"]["chars_saved_per_message"],
        expect["chars_saved_per_message"].as_f64().unwrap(),
    );
    near(
        &report["overall"]["suggestions_per_message"],
        expect["suggestions_per_message"].as_f64().unwrap(),
    );
    near(&report["overall"]["p50_latency_ms"], 1.0);
    near(&report["overall"]["p90_latency_ms"], 1.0);
    assert_eq!(report["per_tier"][0]["tier"], "recall");
    assert_eq!(report["per_tier"][0]["metrics"]["shown"], expect["shown"]);
    for surface in ["openwiz-app", "t3-code", "bb-plugin", "cli"] {
        let row = report["per_surface"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["surface"] == surface)
            .unwrap();
        let want = &expect["per_surface"][surface];
        assert_eq!(row["metrics"]["shown"], want["shown"], "{surface}");
        assert_eq!(row["metrics"]["accepted"], want["accepted"], "{surface}");
        near(
            &row["metrics"]["chars_saved_per_message"],
            want["chars_saved_per_message"].as_f64().unwrap(),
        );
    }
    let (code, stdout, stderr) = run_bench(&["--source", "fixtures"], &env_empty);
    assert_eq!(code, 0, "{stderr}");
    let printed: Value = serde_json::from_str(stdout.trim()).unwrap();
    assert_eq!(printed["overall"]["shown"], report["overall"]["shown"]);
}

#[test]
fn ci_gate_passes_on_the_baseline() {
    let report = bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Baseline,
        None,
    )
    .unwrap();
    gate::check(&report, &baseline()).unwrap();
}

#[test]
fn ci_gate_fails_the_slow_model_on_p90() {
    let report = bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Slow,
        None,
    )
    .unwrap();
    near(&report["overall"]["p90_latency_ms"], 200.0);
    near(&report["overall"]["acceptance_rate"], 1.0);
    let error = gate::check(&report, &baseline()).unwrap_err();
    assert!(error.contains("p90"), "{error}");
}

#[test]
fn ci_gate_fails_the_weak_model_on_acceptance_and_characters() {
    let mut report = bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Weak,
        None,
    )
    .unwrap();
    assert_eq!(report["overall"]["shown"], 0);
    assert!(report["overall"]["p90_latency_ms"].is_null());
    let baseline = baseline();
    let error = gate::check(&report, &baseline).unwrap_err();
    assert!(error.contains("acceptance"), "{error}");
    report["overall"]["acceptance_rate"] = baseline["acceptance_rate_min"].clone();
    let error = gate::check(&report, &baseline).unwrap_err();
    assert!(error.contains("characters saved"), "{error}");
}

#[test]
fn logging_is_off_until_the_setting_is_on() {
    let state = temp_state("off");
    assert!(!log::logging_enabled(&state));
    let notes = state.join("notes.txt");
    fs::write(&notes, "keep\n").unwrap();
    bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Baseline,
        Some(&state),
    )
    .unwrap();
    assert!(
        !log::events_path(&state).exists(),
        "logging off must not create the log"
    );
    assert_eq!(fs::read_to_string(&notes).unwrap(), "keep\n");
    let _ = fs::remove_dir_all(&state);
}

#[test]
fn logging_writes_only_the_local_file() {
    let state = temp_state("on");
    let notes = state.join("notes.txt");
    fs::write(&notes, "keep\n").unwrap();
    log::set_logging(&state, true).unwrap();
    assert!(log::logging_enabled(&state));
    bench::replay_file(
        &fixtures().join("replay-set.json"),
        bench::FixtureModel::Baseline,
        Some(&state),
    )
    .unwrap();
    assert!(
        log::events_path(&state).is_file(),
        "logging on must write the one local file"
    );
    let ghost = state.join("ghost");
    let mut names: Vec<_> = fs::read_dir(&ghost)
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    names.sort();
    assert_eq!(names, ["events.jsonl", "settings.json"]);
    assert_eq!(fs::read_to_string(&notes).unwrap(), "keep\n");
    let lines: Vec<_> = fs::read_to_string(log::events_path(&state))
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect();
    assert!(!lines.is_empty());
    for line in &lines {
        let event: Value = serde_json::from_str(line).unwrap();
        let errors = validate("event", &event);
        assert!(errors.is_empty(), "{line}\n{}", errors.join("\n"));
    }
    assert!(log::append_event(&state, &json!({})).is_err());
    let after = fs::read_to_string(log::events_path(&state)).unwrap();
    assert_eq!(
        after.lines().count(),
        lines.len(),
        "a bad event must not be written"
    );
    let _ = fs::remove_dir_all(&state);
}

#[test]
fn forget_deletes_the_log_and_nothing_else() {
    let state = temp_state("forget");
    log::set_logging(&state, true).unwrap();
    let event = json!({
        "schema": "openwiz.ghost.v1", "kind": "event", "at": "2026-11-24T12:00:00Z",
        "suggestion_id": "sug_syn_1", "session_id": "thr_syn_1", "surface": "cli",
        "outcome": "shown", "tier": "recall", "confidence": 0.5, "latency_ms": 1.0,
        "chars_accepted": 0
    });
    assert!(log::append_event(&state, &event).unwrap());
    let sibling = state.join("ghost").join("kept.txt");
    fs::write(&sibling, "keep\n").unwrap();
    let outside = state.join("outside.txt");
    fs::write(&outside, "keep\n").unwrap();
    assert!(log::forget(&state).unwrap());
    assert!(!log::events_path(&state).exists());
    assert_eq!(
        fs::read_to_string(state.join("ghost/settings.json")).unwrap(),
        "{\"logging\":true}\n"
    );
    assert_eq!(fs::read_to_string(&sibling).unwrap(), "keep\n");
    assert_eq!(fs::read_to_string(&outside).unwrap(), "keep\n");
    assert!(!log::forget(&state).unwrap());
    let (code, _out, err) = run_forget(&state);
    assert_eq!(code, 0, "{err}");
    let _ = fs::remove_dir_all(&state);
}

#[test]
fn bench_reads_the_opt_in_log() {
    let state = temp_state("read");
    log::set_logging(&state, true).unwrap();
    let shown = json!({
        "schema": "openwiz.ghost.v1", "kind": "event", "at": "2026-11-24T12:00:00Z",
        "suggestion_id": "sug_syn_9", "session_id": "thr_syn_9", "surface": "cli",
        "outcome": "shown", "tier": "recall", "confidence": 0.5, "latency_ms": 4.0,
        "chars_accepted": 0
    });
    let mut accepted = shown.clone();
    accepted["outcome"] = json!("accepted_all");
    accepted["chars_accepted"] = json!(4);
    log::append_event(&state, &shown).unwrap();
    log::append_event(&state, &accepted).unwrap();
    assert_eq!(log::read_events(&state).unwrap().len(), 2);
    let path = log::events_path(&state);
    let schema = read_json(&repo_root().join("contracts/ghost.v1.schema.json"));
    let source = schema["$defs"]["bench_source"]["enum"]
        .as_array()
        .unwrap()
        .iter()
        .find(|source| !matches!(source.as_str(), Some("fixtures" | "sent")))
        .unwrap();
    let args = [
        "--source",
        source.as_str().unwrap(),
        "--replay",
        path.to_str().unwrap(),
    ];
    let (code, stdout, stderr) = run_bench(&args, &env_empty);
    assert_eq!(code, 0, "{stderr}");
    let report: Value = serde_json::from_str(&stdout).unwrap();
    let errors = validate("bench_report", &report);
    assert!(errors.is_empty(), "{}", errors.join("\n"));
    assert_eq!(&report["source"], source);
    assert_eq!(report["messages"], 1);
    assert_eq!(report["overall"]["shown"], 1);
    assert_eq!(report["overall"]["accepted"], 1);
    near(&report["overall"]["chars_saved_per_message"], 4.0);
    near(&report["overall"]["p90_latency_ms"], 4.0);
    let _ = fs::remove_dir_all(&state);
}

#[test]
fn bad_inputs_fail_closed_and_sent_messages_replay() {
    let state = temp_state("bad");
    fs::create_dir_all(state.join("ghost")).unwrap();
    fs::write(
        state.join("ghost/settings.json"),
        "{\"logging\":true,\"logging\":false}\n",
    )
    .unwrap();
    assert!(!log::logging_enabled(&state));
    let broken = fixtures().join("replay-set.json");
    let text = fs::read_to_string(&broken)
        .unwrap()
        .replace("\"text\"", "\"text\" , \"extra\"");
    let bad = state.join("bad.json");
    fs::write(&bad, text).unwrap();
    assert!(bench::replay_file(&bad, bench::FixtureModel::Baseline, None).is_err());
    let (code, _out, err) = run_bench(&["--source", "nope"], &env_empty);
    assert_eq!(code, 2, "{err}");
    let sent = state.join("sent.json");
    let pack = context_pack().canonicalize().unwrap();
    fs::write(
        &sent,
        format!(
            "{{\"schema\":\"openwiz.ghost.v1\",\"kind\":\"replay_fixtures\",\"context_fixture\":{},\"messages\":[{{\"id\":\"msg_syn_1\",\"surface\":\"cli\",\"session_id\":\"thr_syn_1\",\"text\":\"J1 all recs\"}}]}}\n",
            serde_json::to_string(&pack.to_string_lossy()).unwrap()
        ),
    )
    .unwrap();
    let report = bench::replay_file(&sent, bench::FixtureModel::Baseline, None).unwrap();
    assert_eq!(report["messages"], 1);
    assert_eq!(report["overall"]["accepted"], 1);
    near(&report["overall"]["chars_saved_per_message"], 9.0);
    let _ = fs::remove_dir_all(&state);
}

#[test]
fn sent_bench_reads_skill_json_from_openwiz_ghost_home() {
    let home = temp_state("skill-home");
    let pack = context_pack().canonicalize().unwrap();
    let replay = home.join("replay.json");
    fs::write(
        &replay,
        format!(
            "{{\"schema\":\"openwiz.ghost.v1\",\"kind\":\"replay_fixtures\",\"context_fixture\":{},\"messages\":[{{\"id\":\"msg_syn_skill\",\"surface\":\"cli\",\"session_id\":\"thr_syn_skill\",\"text\":\"take all recs today\"}}]}}\n",
            serde_json::to_string(&pack.to_string_lossy()).unwrap()
        ),
    )
    .unwrap();
    let skill = |never: &str| {
        fs::write(
            home.join("skill.json"),
            format!(
                "{{\"phrases\":[\"take all recs today\"],\"codes\":[],\"tone\":\"short\",\"never_suggest\":{never}}}\n"
            ),
        )
        .unwrap();
    };
    let env = |name: &str| (name == "OPENWIZ_GHOST_HOME").then(|| home.clone().into_os_string());
    let args = ["--source", "sent", "--replay", replay.to_str().unwrap()];
    skill("[]");
    let (code, stdout, stderr) = run_bench(&args, &env);
    assert_eq!(code, 0, "{stderr}");
    let report: Value = serde_json::from_str(stdout.trim()).unwrap();
    assert!(validate("bench_report", &report).is_empty());
    assert_eq!(report["source"], "sent");
    assert!(
        report["overall"]["chars_saved_per_message"]
            .as_f64()
            .unwrap()
            > 0.0
    );
    skill("[\"take all recs today\"]");
    let (code, stdout, stderr) = run_bench(&args, &env);
    assert_eq!(code, 0, "{stderr}");
    let blocked: Value = serde_json::from_str(stdout.trim()).unwrap();
    assert_eq!(blocked["overall"]["shown"], 0);
    fs::remove_file(home.join("skill.json")).unwrap();
    assert_ne!(run_bench(&args, &env).0, 0);
    let (code, stdout, stderr) = run_bench(&["--source", "fixtures"], &env);
    assert_eq!(code, 0, "{stderr}");
    let fixtures_report: Value = serde_json::from_str(stdout.trim()).unwrap();
    assert_eq!(fixtures_report["overall"]["shown"], 8);
    let _ = fs::remove_dir_all(&home);
}

fn run_bench(args: &[&str], env: &dyn Fn(&str) -> Option<OsString>) -> (i32, String, String) {
    let os: Vec<OsString> = args.iter().map(OsString::from).collect();
    let mut out = Vec::new();
    let mut err = Vec::new();
    let code = bench::run_with(&os, &mut out, &mut err, env);
    (
        code,
        String::from_utf8_lossy(&out).into_owned(),
        String::from_utf8_lossy(&err).into_owned(),
    )
}

fn run_forget(state: &Path) -> (i32, String, String) {
    let mut out = Vec::new();
    let mut err = Vec::new();
    let dir = state.to_path_buf();
    let env = move |name: &str| {
        if name == "OPENWIZ_STATE_DIR" {
            Some(dir.clone().into_os_string())
        } else {
            None
        }
    };
    let code = log::run_with(&[], &mut out, &mut err, &env);
    (
        code,
        String::from_utf8_lossy(&out).into_owned(),
        String::from_utf8_lossy(&err).into_owned(),
    )
}
