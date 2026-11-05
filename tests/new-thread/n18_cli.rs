//! N18, the CLI half (A1 phase 2), and N5's: `openwiz new` prints the
//! effects and the exact command before anything is created, and creates
//! only with `--yes` (sheet A-7); the JSON matches the text; every exit code
//! is documented; the text comes from the argument or stdin, never a
//! terminal; `openwiz models` shows the read time, the saved-copy label and
//! every unavailable harness with its reason, and no default. The start is
//! followed within its bound (sheet A-9).

use std::time::Duration;

use openwiz_cli::new_thread::*;
use openwiz_cli::send::random_op_id;
use openwiz_core::new_thread::start::{FOLLOW_INTERVAL, FOLLOW_MAX_READS, FOLLOW_WINDOW};
use serde_json::{Value, json};

use crate::fake::*;
use crate::support::{SCHEMA, clock, strings};

fn new_thread_schema() -> Value {
    serde_json::from_str(&std::fs::read_to_string(SCHEMA).unwrap()).unwrap()
}

fn validate(def: Option<&str>, value: &Value) -> Vec<String> {
    let mut schema = new_thread_schema();
    if let Some(def) = def {
        schema["$ref"] = json!(format!("#/$defs/{def}"));
    }
    crate::pattern::validate(&schema, value)
}

const PREVIEW: [&str; 10] = [
    "new",
    "Synthetic project one",
    "--harness",
    "codex",
    "--model",
    "syn-codex-model-01",
    "--effort",
    "high",
    "--",
    "Synthetic preview",
];

#[test]
fn without_yes_the_effects_and_the_exact_command_are_printed_and_nothing_is_created() {
    let fake = NewFake::new("n18_preview");
    let (code, out, err) = fake.cli(&PREVIEW, "");
    assert_eq!(code, EXIT_NEEDS_YES, "{out}\n{err}");
    for effect in [
        "creates one Cloud thread in Synthetic project one and starts its first turn",
        "starts from the project's default branch on GitHub",
        "copies the project's .env files from this computer",
        "runs with full permissions in its own sandbox",
        "uses one Cloud agent from your plan",
        "this computer must stay awake until the start is confirmed",
        "CloudRoom names it",
    ] {
        assert!(out.contains(effect), "{effect:?} not shown:\n{out}");
    }
    assert!(out.contains("nothing was created"), "{out}");
    let command = printed_command(&out);
    let op = command
        .split(" --op-id '")
        .nth(1)
        .and_then(|rest| rest.split('\'').next())
        .expect("the command names its op id")
        .to_owned();
    assert_eq!(
        command,
        format!(
            "openwiz new 'Synthetic project one' --harness 'codex' --model \
             'syn-codex-model-01' --effort 'high' --op-id '{op}' --text-sha256 {} --yes -- \
             'Synthetic preview'",
            openwiz_core::messaging::sha256_hex(b"Synthetic preview")
        )
    );
    assert!(
        !fake.state.join("new-threads").exists(),
        "no record was opened"
    );
    assert_eq!(fake.spawn_count(), 0);
    let reads: Vec<String> = fake.invocations().iter().map(|a| a.join(" ")).collect();
    assert_eq!(
        reads,
        [
            "--version",
            "project list --json --include-personal",
            "cloud status --json"
        ]
    );

    // The printed command, run as printed, creates exactly what was
    // previewed, under that op id (Sol, round 1, R1).
    let out = run_printed(&["sh"], &fake, &command);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(fake.record(&op)["outcome"]["kind"], "created");
    assert_eq!(
        fake.spawns(),
        vec![spawn_argv(PROJECT, &op, "Synthetic preview")]
    );

    // A create that would be refused shows why, and no command.
    let mut unoffered = PREVIEW;
    unoffered[7] = "ultra";
    let (code, out, _) = fake.cli(&unoffered, "");
    assert_eq!(code, EXIT_NOT_CREATED, "{out}");
    assert!(out.contains("refused: not offered"), "{out}");
    assert!(!out.contains("--yes"), "{out}");
    assert_eq!(fake.spawn_count(), 1);
}

/// The command a preview prints, from its indented `openwiz new` line to
/// the end: it comes last, and spans lines when the text has a line break.
pub fn printed_command(out: &str) -> String {
    let starts: Vec<usize> = out
        .match_indices("\n  openwiz new ")
        .map(|(i, _)| i + 3)
        .collect();
    assert_eq!(starts.len(), 1, "one command:\n{out}");
    let command = &out[starts[0]..];
    command.strip_suffix('\n').unwrap_or(command).to_owned()
}

/// Why `zsh` can't run the round trips, if it can't: it could not be
/// started, it failed, or it isn't zsh (`$ZSH_VERSION` is empty). `None`
/// when it works.
pub fn zsh_problem(zsh: &std::path::Path) -> Option<String> {
    let out = match std::process::Command::new(zsh)
        .args(["-f", "-c", "print -r -- \"$ZSH_VERSION\""])
        .stdin(std::process::Stdio::null())
        .output()
    {
        Ok(out) => out,
        Err(e) => return Some(format!("{} could not be started ({e})", zsh.display())),
    };
    if !out.status.success() {
        return Some(format!("{} failed ({})", zsh.display(), out.status));
    }
    if String::from_utf8_lossy(&out.stdout).trim().is_empty() {
        return Some(format!("{} did not answer as zsh", zsh.display()));
    }
    None
}

/// The shells the printed command is run in, as `[program, options…]`:
/// `sh`, `bash`, and `zsh` (Jake's Mac's shell) with no startup files, as
/// is and with `RC_QUOTES`, which changes what `''` means inside quotes.
///
/// **zsh is required for acceptance, like Rust and Node** (Sol, round 3,
/// R4; `AGENTS.md`): when the `zsh` on `PATH` is missing or broken, this
/// fails the test that asked, with the reason. It never skips.
pub fn shells() -> Vec<Vec<&'static str>> {
    if let Some(problem) = zsh_problem(std::path::Path::new("zsh")) {
        panic!(
            "zsh is required for acceptance, like Rust and Node (AGENTS.md): {problem}. \
             Install it (sudo apt-get install -y zsh) and run the tests again"
        );
    }
    vec![
        vec!["sh"],
        vec!["bash"],
        vec!["zsh", "-f"],
        vec!["zsh", "-f", "-o", "rc_quotes"],
    ]
}

/// Runs `command` exactly as printed, in `shell` (see [`shells`]), with the
/// release `openwiz` and the fake first on `PATH`, this test's state
/// directory, and stdin closed.
pub fn run_printed(shell: &[&str], fake: &NewFake, command: &str) -> std::process::Output {
    let release = openwiz_release();
    let bin = release.parent().expect("the release directory");
    std::process::Command::new(shell[0])
        .args(&shell[1..])
        .arg("-c")
        .arg(command)
        .env(
            "PATH",
            format!(
                "{}:{}",
                bin.display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .env("OPENWIZ_FIXTURE_PROGRAM", fake.program())
        .env("OPENWIZ_STATE_DIR", &fake.state)
        .current_dir(&fake.dir)
        .stdin(std::process::Stdio::null())
        .output()
        .expect("run the printed command")
}

/// Every value the text shows comes from the JSON, and every report kind
/// validates against its contract.
#[test]
fn the_json_matches_the_text() {
    let fake = NewFake::new("n18_json_text");
    let mut preview = PREVIEW.to_vec();
    preview.splice(8..8, ["--op-id", "op-n18-preview"]);
    let cases: Vec<(Vec<&str>, &str, Option<&str>)> = vec![
        (preview, "preview", Some("preview")),
        (
            new_args("Synthetic project one", "op-n18-created", &[], "Synthetic"),
            "created",
            None,
        ),
        (
            new_args("Synthetic project one", "op-n18-created", &[], "Synthetic"),
            "replayed",
            None,
        ),
        (
            new_args(
                "Synthetic project one",
                "op-n18-created",
                &[],
                "Synthetic other",
            ),
            "conflicting",
            None,
        ),
        (
            new_args_by_id("prj_syn_0003", "op-n18-refused", &[], "Synthetic"),
            "refused",
            None,
        ),
        (
            vec!["new", "--status", "op-n18-created"],
            "status",
            Some("status_read"),
        ),
        (
            vec!["new", "--status", "op-n18-none"],
            "no record",
            Some("status_read"),
        ),
        (vec!["models"], "models", Some("options")),
    ];
    for (args, what, def) in cases {
        let (code_text, text, _) = fake.cli(&args, "");
        let (code_json, json) = fake.cli_json(&args, "");
        assert_eq!(code_text, code_json, "{what}");
        let errors = validate(def, &json);
        assert!(errors.is_empty(), "{what}: {json}\n{errors:#?}");
        let mut shown = Vec::new();
        for key in [
            "op_id",
            "summary",
            "text",
            "thread_id",
            "detail",
            "label",
            "harness",
            "model",
        ] {
            collect(&json, key, &mut shown);
        }
        assert!(!shown.is_empty(), "{what}");
        for value in shown {
            assert!(
                text.contains(&value),
                "{what}: {value:?} is in the JSON but not the text:\n{text}"
            );
        }
    }
}

/// Every string under `key`, anywhere in `value`.
fn collect(value: &Value, key: &str, out: &mut Vec<String>) {
    match value {
        Value::Object(map) => {
            for (k, v) in map {
                if k == key
                    && let Value::String(s) = v
                {
                    out.push(s.clone());
                }
                collect(v, key, out);
            }
        }
        Value::Array(items) => items.iter().for_each(|v| collect(v, key, out)),
        _ => {}
    }
}

#[test]
fn every_exit_code_is_documented() {
    let help = openwiz_cli::help();
    for (code, words) in [
        (EXIT_CREATED, "new: created"),
        (EXIT_NOT_CREATED, "new: refused or failed"),
        (EXIT_NEW_UNCERTAIN, "new: uncertain"),
        (EXIT_NEW_IN_PROGRESS, "new: in progress"),
        (EXIT_NEW_CONFLICTING_REUSE, "new: the op id is bound to"),
        (EXIT_NEW_RECORD_UNAVAILABLE, "new: the new-thread record"),
        (EXIT_NEW_NO_RECORD, "new --status: no record"),
        (EXIT_NEEDS_YES, "new without --yes"),
        (EXIT_NO_OPTIONS, "models: nothing can be offered"),
        (EXIT_CREATED, "models: options"),
    ] {
        let line = help
            .lines()
            .find(|l| l.trim_start().starts_with(&format!("{code} ")) && l.contains(words));
        assert!(
            line.is_some(),
            "exit {code} ({words}) is not documented:\n{help}"
        );
    }
    for words in [
        "openwiz new <project> --harness <h> --model <m> --effort <e>",
        "openwiz new --project-id <id>",
        "openwiz new --status <op id> [--json]",
        "[--text-sha256 <hex>]",
        "a text a shell or a paste changed is refused",
        "openwiz models [--json]",
        "--yes",
        "16384 bytes",
        "no retry",
        "never that it started",
        "openwiz.new-thread.v1",
        "openwiz.cloud-options.v1",
    ] {
        assert!(help.contains(words), "{words:?} not in --help:\n{help}");
    }
    let fake = NewFake::new("n18_help");
    for args in [&["new", "--help"][..], &["models", "--help"][..]] {
        let (code, out, _) = fake.cli(args, "");
        assert_eq!(code, 0);
        assert_eq!(out, help);
    }
    assert!(fake.invocations().is_empty(), "help reads nothing");
}

#[test]
fn errors_go_to_stderr_with_stdout_empty_and_read_nothing() {
    let fake = NewFake::new("n18_errors");
    let long = "a".repeat(16_385);
    for (args, stdin) in [
        (vec!["new"], ""),
        (vec!["new", "Synthetic project one", "--bogus"], ""),
        (vec!["new", "Synthetic project one", "--harness"], ""),
        (vec!["new", "--status"], ""),
        (vec!["new", "--status", "op-x", "--yes"], ""),
        (vec!["new", "--status", "op-x", "Synthetic project one"], ""),
        (vec!["new", "--status", "-bad op"], ""),
        (vec!["new", "--json=yes", "Synthetic project one"], ""),
        (
            new_args("Synthetic project one", "op bad", &[], "Synthetic"),
            "",
        ),
        (
            new_args(
                "Synthetic project one",
                "op-x",
                &["--harness", "x"],
                "Synthetic",
            ),
            "",
        ),
        (new_args("Synthetic project one", "op-x", &[], ""), ""),
        (new_args("Synthetic project one", "op-x", &[], " \n "), ""),
        (new_args("Synthetic project one", "op-x", &[], "a\0b"), ""),
        (new_args("Synthetic project one", "op-x", &[], &long), ""),
        (
            vec![
                "new",
                "Synthetic project one",
                "--harness",
                "codex",
                "--model=-model",
                "--effort",
                "high",
                "--yes",
                "--",
                "Synthetic",
            ],
            "",
        ),
        (vec!["models", "--bogus"], ""),
        (vec!["models", "codex"], ""),
    ] {
        let (code, out, err) = fake.cli(&args, stdin);
        assert_eq!(code, 2, "{args:?}: {out}{err}");
        assert!(out.is_empty(), "{out}");
        assert_eq!(err.lines().count(), 1, "{err}");
        assert!(err.starts_with("openwiz: "), "{err}");
    }
    assert!(fake.invocations().is_empty(), "a usage error reads nothing");
    assert!(!fake.state.join("new-threads").exists());
}

#[test]
fn the_text_is_never_read_from_a_terminal() {
    let fake = NewFake::new("n18_terminal");
    let source = fake.source();
    let clock = clock();
    let never = || -> Result<Box<dyn openwiz_core::new_thread::record::NewThreadStore>, _> {
        panic!("no record is opened")
    };
    let never_read_only =
        || -> Result<Option<Box<dyn openwiz_core::new_thread::record::NewThreadStore>>, _> {
            panic!("no record is opened")
        };
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let mut args = new_args("Synthetic project one", "op-n18-tty", &[], "");
    args.truncate(args.len() - 2);
    let args: Vec<String> = args[1..].iter().map(|a| (*a).to_owned()).collect();
    let code = run_new(
        &args,
        NewContext {
            client: &source,
            open_store: &never,
            open_store_read_only: &never_read_only,
            clock: &clock,
            stdin: &mut "Synthetic typed".as_bytes(),
            stdin_is_terminal: true,
            new_op_id: &random_op_id,
            wait: &|_| panic!("no wait"),
        },
        &mut out,
        &mut err,
    );
    assert_eq!(code, 2);
    assert!(String::from_utf8_lossy(&err).contains("a terminal is never read"));
    assert!(fake.invocations().is_empty());
}

#[test]
fn models_shows_the_options_as_reported_and_no_default() {
    let fake = NewFake::new("n18_models");
    let (code, out, err) = fake.cli(&["models"], "");
    assert_eq!(code, EXIT_CREATED, "{err}");
    for words in [
        "as reported by CloudRoom; it may answer from a saved copy",
        "read 2023-11-14T22:23:20Z",
        "codex",
        "claude-code",
        "syn-codex-model-01: low, medium, high, xhigh, max",
        "syn-claude-model-01: low, medium, high, xhigh, max",
        "pi: unavailable (catalogue not reported)",
        "cursor: unavailable (catalogue not reported)",
    ] {
        assert!(out.contains(words), "{words:?} not shown:\n{out}");
    }
    assert!(!out.contains("ultra"), "never offered:\n{out}");
    assert!(
        !out.to_lowercase().contains("default"),
        "no default:\n{out}"
    );
    let reads: Vec<String> = fake.invocations().iter().map(|a| a.join(" ")).collect();
    assert_eq!(reads, ["cloud status --json"], "one read");

    for (test, name, reason) in [
        (
            "n18_models_not_ready",
            "cloud-status-not-ready.json",
            "not_ready",
        ),
        (
            "n18_models_null",
            "cloud-status-harnesses-null.json",
            "harnesses_not_reported",
        ),
        (
            "n18_models_drift",
            "cloud-status-drift-array.json",
            "unexpected_shape",
        ),
    ] {
        let fake = NewFake::with(
            test,
            vec![json!({"argv": ["cloud", "status", "--json"], "stdout_file": file(name)})],
        );
        let (code, json) = fake.cli_json(&["models"], "");
        assert_eq!(code, EXIT_NO_OPTIONS, "{test}: {json}");
        assert_eq!(json["state"]["reason"], reason, "{test}");
        let (_, out, _) = fake.cli(&["models"], "");
        assert!(out.contains("no options"), "{test}: {out}");
    }
}

#[test]
fn models_json_keeps_unavailable_harness_with_its_reason_and_explanation() {
    let fake = NewFake::new("n18_models_json_unavailable");
    let (code, report) = fake.cli_json(&["models"], "");
    assert_eq!(code, EXIT_CREATED, "{report}");
    let cursor: Vec<&Value> = report["unavailable"]
        .as_array()
        .expect("models JSON reports unavailable harnesses")
        .iter()
        .filter(|row| row["harness"] == "cursor")
        .collect();
    assert_eq!(cursor.len(), 1, "one unavailable cursor harness: {report}");
    assert_eq!(cursor[0]["reason"], "catalogue_not_reported", "{report}");
    assert_eq!(
        cursor[0]["text"], "unavailable (catalogue not reported)",
        "{report}"
    );
}

#[test]
fn models_json_preserves_each_harness_reported_steer_capability() {
    for (case, reported, expected) in [
        (
            "true_false",
            [Some(json!(true)), Some(json!(false))],
            [json!(true), json!(false)],
        ),
        (
            "false_true",
            [Some(json!(false)), Some(json!(true))],
            [json!(false), json!(true)],
        ),
        (
            "null_missing",
            [Some(Value::Null), None],
            [Value::Null, Value::Null],
        ),
        (
            "missing_null",
            [None, Some(Value::Null)],
            [Value::Null, Value::Null],
        ),
    ] {
        let mut status: Value =
            serde_json::from_slice(&std::fs::read(file("cloud-status.json")).unwrap()).unwrap();
        for (harness, steer) in ["codex", "claude-code"].into_iter().zip(reported) {
            let row = status["harnesses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|row| row["id"] == harness)
                .expect("synthetic catalogue harness")
                .as_object_mut()
                .unwrap();
            match steer {
                Some(value) => row.insert("steer".into(), value),
                None => row.remove("steer"),
            };
        }
        let fake = NewFake::with(
            &format!("n18_models_steer_{case}"),
            vec![json!({"argv": ["cloud", "status", "--json"], "stdout": status.to_string()})],
        );
        let (code, doc) = fake.cli_json(&["models"], "");
        assert_eq!(code, EXIT_CREATED, "{case}: {doc}");
        let rows = doc["harnesses"].as_array().expect("offered harnesses");
        assert_eq!(rows.len(), 2, "{case}: {doc}");
        for (harness, steer) in ["codex", "claude-code"].into_iter().zip(expected) {
            let row = rows
                .iter()
                .find(|row| row["harness"] == harness)
                .expect("offered synthetic harness");
            assert_eq!(row.get("steer"), Some(&steer), "{case}: {harness}");
        }
        assert_eq!(fake.invocations(), [vec!["cloud", "status", "--json"]]);
    }
}

#[test]
fn models_json_preserves_each_harness_reported_attachment_capabilities() {
    // Variants are synthetic; the reported case leaves the fixture unchanged.
    for (case, codex, claude) in [
        (
            "reported",
            Some(json!({"files": true, "images": true})),
            Some(json!({"files": true, "images": true})),
        ),
        (
            "files_images",
            Some(json!({"files": true, "images": false})),
            Some(json!({"files": false, "images": true})),
        ),
        (
            "images_files",
            Some(json!({"files": false, "images": true})),
            Some(json!({"files": true, "images": false})),
        ),
        (
            "neither",
            Some(json!({"files": false, "images": false})),
            Some(json!({"files": false, "images": false})),
        ),
        ("null_missing", Some(Value::Null), None),
        ("missing_null", None, Some(Value::Null)),
        (
            "known_unknown",
            Some(json!({"files": true, "images": true})),
            None,
        ),
        (
            "unknown_known",
            None,
            Some(json!({"files": false, "images": false})),
        ),
    ] {
        let mut status: Value =
            serde_json::from_slice(&std::fs::read(file("cloud-status.json")).unwrap()).unwrap();
        for row in status["harnesses"].as_array_mut().unwrap() {
            let support = match row["id"].as_str() {
                Some("codex") => &codex,
                Some("claude-code") => &claude,
                _ => continue,
            };
            if case != "reported" {
                match support {
                    Some(value) => row["attachments"] = value.clone(),
                    None => {
                        row.as_object_mut().unwrap().remove("attachments");
                    }
                }
            }
        }
        let fake = NewFake::with(
            &format!("n18_models_attachments_{case}"),
            vec![json!({"argv": ["cloud", "status", "--json"], "stdout": status.to_string()})],
        );
        let (code, doc) = fake.cli_json(&["models"], "");
        assert_eq!(code, EXIT_CREATED, "{case}: {doc}");
        let offered = doc["harnesses"].as_array().unwrap();
        assert_eq!(offered.len(), 2, "{case}: {doc}");
        for (harness, expected) in [
            ("codex", codex.unwrap_or(Value::Null)),
            ("claude-code", claude.unwrap_or(Value::Null)),
        ] {
            let row = offered
                .iter()
                .find(|row| row["harness"] == harness)
                .unwrap();
            assert_eq!(row.get("attachments"), Some(&expected), "{case}: {harness}");
        }
        assert_eq!(
            fake.invocations(),
            [vec!["cloud", "status", "--json"]],
            "{case}: one catalogue read"
        );
    }
}

#[test]
fn the_account_never_reaches_any_output() {
    let mut status: Value =
        serde_json::from_slice(&std::fs::read(file("cloud-status.json")).unwrap()).unwrap();
    status["account"] = json!({"email": "synthetic-account-marker"});
    status["planUsage"] = json!({"plan": "synthetic-plan-marker"});
    let fake = NewFake::with(
        "n18_account",
        vec![json!({"argv": ["cloud", "status", "--json"], "stdout": status.to_string()})],
    );
    for args in [
        &["models", "--json"][..],
        &["models"][..],
        &PREVIEW[..],
        &new_args(
            "Synthetic project one",
            "op-n18-account",
            &["--json"],
            "Synthetic",
        )[..],
    ] {
        let (_, out, err) = fake.cli(args, "");
        for marker in ["synthetic-account-marker", "synthetic-plan-marker"] {
            assert!(!out.contains(marker) && !err.contains(marker), "{args:?}");
        }
    }
    let record = std::fs::read_to_string(fake.record_path("op-n18-account")).unwrap();
    assert!(!record.contains("marker"), "{record}");
}

#[test]
fn the_start_is_followed_within_its_bound() {
    // Waiting forever: at most FOLLOW_MAX_READS reads within FOLLOW_WINDOW.
    let fake = NewFake::with(
        "n18_follow_pending",
        vec![json!({
            "argv": ["thread", "show", THREAD, "--json"],
            "stdout_file": file("thread-show-pending.json"),
        })],
    );
    let (code, json) = fake.cli_json(
        &new_args("Synthetic project one", "op-n18-follow", &[], "Synthetic"),
        "",
    );
    assert_eq!(code, EXIT_CREATED, "created is not started: {json}");
    assert_eq!(json["start"]["stage"]["kind"], "waiting_to_start", "{json}");
    let shows = fake
        .invocations()
        .iter()
        .filter(|a| starts(a, &["thread", "show"]))
        .count() as u32;
    let waits = fake.waits.lock().unwrap().clone();
    assert_eq!(
        shows, FOLLOW_MAX_READS,
        "every read the bound allows, and no more"
    );
    assert_eq!(waits.len() as u32, shows - 1, "a wait between reads");
    assert!(waits.iter().all(|w| *w == FOLLOW_INTERVAL));
    assert!(waits.iter().sum::<Duration>() <= FOLLOW_WINDOW, "{waits:?}");

    // Settled at once: one read, no wait.
    let fake = NewFake::new("n18_follow_active");
    let (code, json) = fake.cli_json(
        &new_args("Synthetic project one", "op-n18-active", &[], "Synthetic"),
        "",
    );
    assert_eq!(code, EXIT_CREATED);
    assert_eq!(json["start"]["stage"]["kind"], "started", "{json}");
    assert_eq!(
        json["start"]["reported"]["model"]["differs_from_requested"]["known"],
        false
    );
    assert!(fake.waits.lock().unwrap().is_empty());

    // Not created: nothing is followed.
    let fake = NewFake::new("n18_follow_refused");
    let (code, json) = fake.cli_json(
        &new_args_by_id("prj_syn_0002", "op-n18-none", &[], "Synthetic"),
        "",
    );
    assert_eq!(code, EXIT_NOT_CREATED);
    assert!(json["start"].is_null(), "{json}");
    assert!(
        !fake
            .invocations()
            .iter()
            .any(|a| starts(a, &["thread", "show"]))
    );
}

#[test]
fn status_is_read_only_and_exits_as_the_record() {
    let fake = NewFake::new("n18_status");
    let (code, json) = fake.cli_json(&["new", "--status", "op-n18-nothing"], "");
    assert_eq!(code, EXIT_NEW_NO_RECORD, "{json}");
    assert_eq!(json["result"]["kind"], "no_record");
    assert!(!fake.state.exists() || !fake.state.join("new-threads").exists());
    assert!(fake.invocations().is_empty(), "no record: nothing is read");

    let (code, _) = fake.cli_json(
        &new_args("Synthetic project one", "op-n18-status", &[], "Synthetic"),
        "",
    );
    assert_eq!(code, EXIT_CREATED);
    let before = fake.invocations().len();
    let (code, json) = fake.cli_json(&["new", "--status", "op-n18-status"], "");
    assert_eq!(code, EXIT_CREATED, "{json}");
    assert_eq!(json["result"]["start"]["stage"]["kind"], "started");
    let after: Vec<Vec<String>> = fake.invocations()[before..].to_vec();
    assert_eq!(after.len(), 1, "one thread show: {after:?}");
    assert!(starts(&after[0], &["thread", "show", THREAD]));
    assert_eq!(fake.spawn_count(), 1);
    let path = fake.record_path("op-n18-status");
    let record = std::fs::read(&path).unwrap();
    let _ = fake.cli(&["new", "--status", "op-n18-status"], "");
    assert_eq!(std::fs::read(&path).unwrap(), record, "never written");
    let mut seen = Vec::new();
    strings(&json, &mut seen);
    assert!(
        seen.iter().all(|s| s != "Synthetic"),
        "the text is never shown"
    );
}

/// Sol, round 1, R1, and round 2, R3: the printed command is exact for any
/// text, given as the argument or on stdin, in every shell it may be pasted
/// into. Every value in it that the owner gave is quoted, never a bare
/// word, so no shell expands it: not `~` or `~user`, zsh's `=cmd`, braces,
/// globs, `$`, backticks, `!`, comments or separators. It is run as printed,
/// stdin closed, in bash (which creates), then zsh as is and with
/// `RC_QUOTES` and `sh` (each replays it: its `--text-sha256` and the op
/// id's binding accept nothing but the same text). Where `sh` has no
/// `$'…'` (dash), it is refused, exit 2, and nothing is created: fail
/// closed. No character unsafe on a terminal is printed raw. Each text runs
/// on its own fake, in parallel.
#[test]
fn the_printed_command_creates_exactly_what_was_previewed() {
    let texts = [
        "~",
        "~/Synthetic",
        "~root",
        "~root/x",
        "=ls",
        "=x",
        "{a,b}",
        "x{1..3}",
        "*",
        "Synthetic * ? [a]",
        "$HOME ${HOME} $(echo x)",
        "`echo x`",
        "it's \"quoted\"",
        "'",
        "''",
        "'leading",
        "trailing'",
        "a''b",
        "!x !! !$",
        "\\back\\slash\\",
        "#not a comment",
        "a;b && c | d > e < f &",
        "line one\nline two\n",
        "~\n=ls {a,b} *\n",
        "\ttab and\r\nCRLF",
        "escape \u{1b}[31m red",
        "bidi \u{202e} and zero width \u{200b}",
        "Unicode: é 漢字 😀",
        "-Synthetic preview",
        "--json",
        "   leading and trailing spaces   ",
    ];
    let mut shells = shells();
    // bash first: it creates; the others replay.
    shells.rotate_left(1);
    assert_eq!(shells[0], ["bash"]);
    openwiz_release();
    std::thread::scope(|scope| {
        for (i, text) in texts.iter().enumerate() {
            let shells = &shells;
            scope.spawn(move || {
                let fake = NewFake::new(&format!("n18_exact_{i}"));
                for stdin in [false, true] {
                    one_text(
                        &fake,
                        shells,
                        text,
                        &format!("op-r3-{i}-{}", u8::from(stdin)),
                        stdin,
                    );
                }
            });
        }
    });
}

/// One text's preview, and its command run in every shell.
fn one_text(fake: &NewFake, shells: &[Vec<&str>], text: &str, op: &str, stdin: bool) {
    let mut args = vec![
        "new",
        "Synthetic project one",
        "--harness",
        "codex",
        "--model",
        "syn-codex-model-01",
        "--effort",
        "high",
        "--op-id",
        op,
    ];
    if !stdin {
        args.extend(["--", text]);
    }
    let out = fake.run_process(&args, if stdin { text } else { "" });
    assert_eq!(out.status.code(), Some(12), "{text:?}");
    let shown = String::from_utf8(out.stdout).expect("UTF-8");
    for unsafe_char in ['\u{1b}', '\r', '\t', '\u{202e}', '\u{200b}'] {
        assert!(!shown.contains(unsafe_char), "{text:?}: {shown}");
    }
    let command = printed_command(&shown);
    // `$'…'` only when a character can't be shown: a line break stays in
    // single quotes, which every POSIX shell reads.
    let unshowable = text.contains(['\t', '\r', '\u{1b}', '\u{202e}', '\u{200b}']);
    let (_, word) = command.split_once(" --yes -- ").expect("the text's word");
    let dollar = word.starts_with("$'");
    assert_eq!(dollar, unshowable, "{text:?}: {command}");
    for (k, shell) in shells.iter().enumerate() {
        let before = fake.spawn_count();
        let run = run_printed(shell, fake, &command);
        let said = String::from_utf8_lossy(&run.stdout).into_owned()
            + &String::from_utf8_lossy(&run.stderr);
        if shell[0] == "sh" && dollar && run.status.code() == Some(2) {
            // A shell without `$'…'` read another text: refused.
            assert!(said.contains("--text-sha256"), "{text:?}: {said}");
            assert_eq!(fake.spawn_count(), before, "{text:?}: nothing created");
            continue;
        }
        assert_eq!(
            run.status.code(),
            Some(0),
            "{text:?} via {shell:?}: {command}\n{said}"
        );
        if k == 0 {
            assert_eq!(fake.spawn_count(), before + 1, "{text:?}");
            assert_eq!(
                fake.spawns().last().expect("a spawn"),
                &spawn_argv(PROJECT, op, text),
                "{text:?} via {shell:?}: {command}"
            );
        } else {
            assert_eq!(
                fake.spawn_count(),
                before,
                "{text:?} via {shell:?}: a replay"
            );
            assert!(said.contains("replayed"), "{text:?} via {shell:?}: {said}");
        }
    }
}

/// R3: whatever changes the text on the way to the create (a paste that
/// turns a tab into spaces, a shell's expansion, other input on stdin) is
/// refused before anything is read or claimed: the printed command carries
/// the text's SHA-256.
#[test]
fn a_text_changed_on_the_way_is_refused() {
    let fake = NewFake::new("n18_changed_text");
    let text = "tab\there";
    let mut args = PREVIEW.to_vec();
    args.splice(8.., ["--op-id", "op-r3-changed", "--", text]);
    let out = fake.run_process(&args, "");
    let command = printed_command(&String::from_utf8(out.stdout).unwrap());
    assert!(command.contains("$'tab\\there'"), "{command}");
    let pasted = command.replace("$'tab\\there'", "'tab    here'");
    let before = fake.invocations().len();
    let run = run_printed(&["bash"], &fake, &pasted);
    assert_eq!(run.status.code(), Some(2), "{pasted}");
    assert!(String::from_utf8_lossy(&run.stderr).contains("SHA-256"));
    assert_eq!(fake.invocations().len(), before, "nothing was read");
    assert!(
        !fake.state.join("new-threads").exists(),
        "nothing was claimed"
    );
    for bad in ["xyz", &"A".repeat(64)] {
        let mut args = new_args("Synthetic project one", "op-r3-bad", &[], "Synthetic");
        args.splice(1..1, ["--text-sha256", bad]);
        let (code, out, err) = fake.cli(&args, "");
        assert_eq!(code, 2, "{bad}: {out}{err}");
        assert!(err.contains("--text-sha256"), "{err}");
    }
    let (code, _, err) = fake.cli(
        &[
            "new",
            "--status",
            "op-r3-bad",
            "--text-sha256",
            &"a".repeat(64),
        ],
        "",
    );
    assert_eq!(code, 2, "{err}");
    assert_eq!(fake.spawn_count(), 0);
}

/// R3: a project name is free text too. One full of shell syntax resolves
/// to the same project in every shell, so the create goes where the
/// preview said.
#[test]
fn a_project_name_with_shell_syntax_is_quoted_too() {
    let fake = NewFake::with(
        "n18_exact_name",
        vec![json!({
            "any_spawn": true,
            // The thread whose `thread show` reads active: the follow ends.
            "stdout": json!({"id": THREAD, "projectId": "prj_syn_0009", "status": "pending"})
                .to_string(),
            "creates": true,
        })],
    );
    for (k, shell) in shells().iter().enumerate() {
        let op = format!("op-r3-name-{k}");
        let args = [
            "new",
            SHELL_SYNTAX_NAME,
            "--harness",
            "codex",
            "--model",
            "syn-codex-model-01",
            "--effort",
            "high",
            "--op-id",
            &op,
            "--",
            "Synthetic",
        ];
        let out = fake.run_process(&args, "");
        let shown = String::from_utf8(out.stdout).expect("UTF-8");
        assert_eq!(out.status.code(), Some(12), "{shown}");
        let command = printed_command(&shown);
        let run = run_printed(shell, &fake, &command);
        assert_eq!(
            run.status.code(),
            Some(0),
            "via {shell:?}: {command}\n{}",
            String::from_utf8_lossy(&run.stderr)
        );
        let spawn = fake.spawns().pop().expect("a spawn");
        assert_eq!(spawn[3], "prj_syn_0009", "via {shell:?}: {command}");
    }
}

/// Sol, round 3, R4: zsh is required for acceptance, like Rust and Node. The
/// round-trip test, run again as its own process with a broken `zsh` (one
/// that exits 127, Sol's reproduction) first on `PATH`, must fail and say
/// why: the cross-shell proof can never pass without zsh.
#[test]
fn the_round_trips_fail_without_a_working_zsh() {
    use std::os::unix::fs::PermissionsExt;
    let dir = crate::support::private_dir("r4-broken-zsh");
    let zsh = dir.join("zsh");
    std::fs::write(&zsh, "#!/bin/sh\nexit 127\n").unwrap();
    std::fs::set_permissions(&zsh, std::fs::Permissions::from_mode(0o755)).unwrap();
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "n18_cli::the_printed_command_creates_exactly_what_was_previewed",
            "--test-threads=1",
        ])
        .env(
            "PATH",
            format!("{}:{}", dir.display(), std::env::var("PATH").unwrap()),
        )
        // Its own fakes, apart from this run's.
        .env(crate::fake::FAKE_ROOT_ENV, dir.join("fakes"))
        .stdin(std::process::Stdio::null())
        .output()
        .expect("run the round-trip test again");
    let said =
        String::from_utf8_lossy(&out.stdout).into_owned() + &String::from_utf8_lossy(&out.stderr);
    assert!(
        !out.status.success(),
        "the round trips passed with a broken zsh:\n{said}"
    );
    assert!(said.contains("zsh is required"), "{said}");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn models_fixture_process_returns_the_offered_catalogue() {
    let fake = NewFake::new("n18_models_process_success");
    let output = fake.run_process(&["models", "--json"], "");
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let catalogue: Value = serde_json::from_slice(&output.stdout).expect("models JSON");
    assert_eq!(catalogue["schema"], "openwiz.cloud-options.v1");
    assert_eq!(catalogue["state"]["kind"], "offered");
    let codex = catalogue["harnesses"]
        .as_array()
        .expect("offered harnesses")
        .iter()
        .find(|row| row["harness"] == "codex")
        .expect("offered codex harness");
    assert_eq!(
        codex["models"][0],
        json!({
            "model": "syn-codex-model-01",
            "efforts": ["low", "medium", "high", "xhigh", "max"]
        })
    );

    let output = fake.run_process(&["models"], "");
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout).expect("models text");
    assert!(
        text.lines()
            .any(|line| line.trim() == "syn-codex-model-01: low, medium, high, xhigh, max"),
        "offered model missing from models text: {text}"
    );
}

/// R4: the probe itself. A `zsh` that can't be started, fails, or isn't
/// zsh is a problem; the one installed here is not.
#[test]
fn the_zsh_probe_finds_a_missing_or_broken_zsh() {
    use std::os::unix::fs::PermissionsExt;
    let dir = crate::support::private_dir("r4-zsh-probe");
    let missing = dir.join("zsh-missing");
    assert!(zsh_problem(&missing).is_some_and(|p| p.contains("could not be started")));
    for (name, body, why) in [
        (
            "zsh-127",
            "#!/bin/sh\nexit 127\n",
            "failed (exit status: 127)",
        ),
        ("zsh-silent", "#!/bin/sh\nexit 0\n", "did not answer as zsh"),
    ] {
        let fake = dir.join(name);
        // Written by a child `sh`, so this process never has the script open
        // for writing. A child another test forks keeps a copy of every file
        // this process has open until it runs its program, and running the
        // script while a copy is open for writing fails with ETXTBSY (#146).
        // `status` returns once the writer has exited: nothing has it open.
        let written = std::process::Command::new("sh")
            .args(["-c", "printf '%s' \"$1\" >\"$2\"", "sh", body])
            .arg(&fake)
            .stdin(std::process::Stdio::null())
            .status()
            .expect("run sh");
        assert!(written.success(), "{name}: not written");
        std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        let problem = zsh_problem(&fake);
        assert!(
            problem.as_deref().is_some_and(|p| p.contains(why)),
            "{name}: {problem:?}"
        );
    }
    // bash is not zsh: it has no `print`, and no `$ZSH_VERSION`.
    assert!(zsh_problem(std::path::Path::new("bash")).is_some());
    assert_eq!(
        zsh_problem(std::path::Path::new("zsh")),
        None,
        "zsh is required"
    );
    let _ = std::fs::remove_dir_all(&dir);
}
