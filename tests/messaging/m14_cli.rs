//! M14 CLI: `--json` matches the text, the JSON matches
//! `contracts/messaging.v1.schema.json`, and each outcome's exit code is
//! documented.
//!
//! The text contract for `openwiz send` (provisional, like 0.0.1's):
//! 1. line 1: `openwiz send · op <op id> · <target id> · <title>`;
//! 2. `effects (read <age> before sending): <effect>` and `paused queue:
//!    <words>`, when the target was read;
//! 3. the summary line: `<Mode> requested · <reported delivery>`;
//! 4. one `gap: <subject> · <detail>` line per gap;
//! 5. a refusal names what to do next (the acknowledgement flag), and a
//!    replay says `replayed`.
//!
//! Unknowns print as `unknown (<reason>)`.

use openwiz_cli::send::{
    EXIT_CONFLICTING_REUSE, EXIT_DELIVERED, EXIT_IN_PROGRESS, EXIT_POSSIBLE_DUPLICATE,
    EXIT_RECORD_UNAVAILABLE, EXIT_SEND_FAILED, EXIT_UNCERTAIN,
};
use openwiz_cli::{EXIT_NOT_FOUND, EXIT_USAGE};
use openwiz_core::ops::Clock;
use serde_json::{Value, json};

use crate::support::*;

/// What the text must contain for a JSON report.
fn wanted(json: &Value) -> Vec<String> {
    let mut wanted = vec![
        format!("op {}", json["op_id"].as_str().unwrap()),
        json["target"]["id"].as_str().unwrap().to_owned(),
        json["summary"].as_str().unwrap().to_owned(),
    ];
    if let Some(title) = json["target"]["title"]["known"].as_str() {
        wanted.push(title.to_owned());
    }
    if !json["effects"].is_null() {
        let effects = &json["effects"];
        wanted.push(match effects["effect"]["known"]["text"].as_str() {
            Some(text) => text.to_owned(),
            None => format!(
                "unknown ({})",
                effects["effect"]["unknown"].as_str().unwrap()
            ),
        });
        wanted.push(match effects["paused_queue"]["known"]["text"].as_str() {
            Some(text) => text.to_owned(),
            None => format!(
                "unknown ({})",
                effects["paused_queue"]["unknown"].as_str().unwrap()
            ),
        });
    }
    for gap in json["gaps"].as_array().unwrap() {
        wanted.push(gap["detail"].as_str().unwrap().to_owned());
    }
    if json["result"]["replayed"] == true {
        wanted.push("replayed".to_owned());
    }
    if let Some(earlier) = json["result"]["earlier"].as_array() {
        for e in earlier {
            wanted.push(e["op_id"].as_str().unwrap().to_owned());
        }
    }
    wanted
}

/// Runs the same command with and without `--json`, each in its own fresh
/// fake and state (a second run on one state would replay the first).
fn both(
    test: &str,
    responses: Vec<Value>,
    setup: &[&[&str]],
    args: &[&str],
) -> (i32, Value, i32, String) {
    both_with_clock(test, responses, setup, args, &clock())
}

/// Like [`both`], but every run uses `clock`, so a test can make the read
/// and the dispatch fall at different times (#932, R1).
fn both_with_clock(
    test: &str,
    responses: Vec<Value>,
    setup: &[&[&str]],
    args: &[&str],
    clock: &dyn Clock,
) -> (i32, Value, i32, String) {
    let mut runs = Vec::new();
    for json_flag in [true, false] {
        let fake = SendFake::with(&format!("{test}_{json_flag}"), responses.clone());
        for s in setup {
            let _ = fake.cli(s, "");
        }
        let mut all: Vec<&str> = args.to_vec();
        if json_flag {
            all.insert(1, "--json");
        }
        let (code, out, err) = fake.cli_with_clock(&all, "", clock);
        runs.push((code, out, err));
    }
    let (json_code, json_out, json_err) = runs.remove(0);
    let (text_code, text_out, _) = runs.remove(0);
    let json: Value = serde_json::from_str(&json_out)
        .unwrap_or_else(|e| panic!("{test}: not JSON ({e}): {json_out}{json_err}"));
    (json_code, json, text_code, text_out)
}

/// (test, responses, setup commands, command, exit code, status).
type Case<'a> = (
    &'a str,
    Vec<Value>,
    Vec<&'a [&'a str]>,
    Vec<&'a str>,
    i32,
    &'a str,
);

#[test]
fn send_text_reports_the_effects_read_age() {
    // #932, R1: the clock advances by 4_500 ms between the read and the work
    // worked out just after it, so the read age is 4_500 ms, never a constant
    // 0 that a formatter printing `age(0)` would also satisfy.
    let (json_code, json, text_code, text) = both_with_clock(
        "m14_read_age",
        vec![],
        &[],
        &["thr_syn_0001", "--op-id", "op-m14-age", "--", "Synthetic"],
        &AdvancingClock::new(4_500),
    );
    assert_eq!((json_code, text_code), (0, 0), "{json}\n{text}");
    // The clock advances between the read and the dispatch, so the age is
    // nonzero and equal to the clock's step.
    assert_eq!(json["effects"]["read_age_ms"], 4_500, "{json}");
    let effect = json["effects"]["effect"]["known"]["text"]
        .as_str()
        .expect("the idle synthetic target has a known effect");
    assert_eq!(effect, "starts a turn; may wake it");
    let expected = format!("effects (read 4s before sending): {effect}");
    assert_eq!(
        text.lines()
            .filter(|line| line.starts_with("effects "))
            .collect::<Vec<_>>(),
        [expected.as_str()],
        "{text}"
    );
}

#[test]
fn the_json_matches_the_text_and_the_schema() {
    let abort = vec![tell_response(
        "thr_syn_0001",
        "queue",
        json!({"abort": true}),
    )];
    let cases: Vec<Case> = vec![
        (
            "m14_sent",
            vec![],
            vec![],
            vec!["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"],
            0,
            "accepted",
        ),
        (
            "m14_steer_sent",
            vec![],
            vec![],
            vec![
                "thr_syn_0001",
                "--op-id",
                "op-m14",
                "--steer",
                "--",
                "Synthetic",
            ],
            0,
            "accepted",
        ),
        (
            "m14_queued",
            vec![],
            vec![],
            vec!["thr_syn_0006", "--op-id", "op-m14", "--", "Synthetic"],
            0,
            "queued",
        ),
        (
            "m14_unknown_effect",
            vec![],
            vec![],
            vec![
                "thr_syn_0015",
                "--op-id",
                "op-m14",
                "--resume-paused-queue",
                "--",
                "Synthetic",
            ],
            0,
            "accepted",
        ),
        (
            "m14_unsupported",
            vec![tell_response(
                "thr_syn_0002",
                "steer",
                json!({"exit":1, "stderr":"Error: HTTP 400: Unsupported mode"}),
            )],
            vec![],
            vec![
                "thr_syn_0002",
                "--op-id",
                "op-m14",
                "--steer",
                "--",
                "Synthetic",
            ],
            5,
            "failed",
        ),
        (
            "m14_paused",
            vec![],
            vec![],
            vec!["thr_syn_0011", "--op-id", "op-m14", "--", "Synthetic"],
            5,
            "failed",
        ),
        (
            "m14_not_found",
            vec![],
            vec![],
            vec!["thr_syn_9999", "--op-id", "op-m14", "--", "Synthetic"],
            3,
            "failed",
        ),
        (
            "m14_uncertain",
            abort.clone(),
            vec![],
            vec!["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"],
            6,
            "uncertain",
        ),
        (
            "m14_replay",
            vec![],
            vec![&["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"]],
            vec!["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"],
            0,
            "accepted",
        ),
        (
            "m14_conflict",
            vec![],
            vec![&["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"]],
            vec!["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic other"],
            8,
            "conflicting_reuse",
        ),
        (
            "m14_duplicate",
            abort,
            vec![&["thr_syn_0001", "--op-id", "op-m14-first", "--", "Synthetic"]],
            vec!["thr_syn_0001", "--op-id", "op-m14", "--", "Synthetic"],
            9,
            "possible_duplicate_refused",
        ),
    ];
    let schema_errors_of = |json: &Value| validate_report(json);
    // Each case has its own fakes (`both`), so the cases run at once (#1260).
    at_once(cases, |(test, responses, setup, args, code, status)| {
        let (json_code, json, text_code, text) = both(test, responses, &setup, &args);
        assert_eq!(json_code, code, "{test}: {json}");
        assert_eq!(text_code, code, "{test}: {text}");
        assert_eq!(json["status"], status, "{test}: {json}");
        let errors = schema_errors_of(&json);
        assert!(errors.is_empty(), "{test}: {errors:#?}\n{json}");
        let first = text.lines().next().unwrap_or_default();
        assert!(
            first.starts_with("openwiz send · op op-m14 · "),
            "{test}: {first}"
        );
        for w in wanted(&json) {
            assert!(text.contains(&w), "{test}: {w:?} not in the text:\n{text}");
        }
        assert_eq!(
            text.lines().filter(|l| l.starts_with("gap: ")).count(),
            json["gaps"].as_array().unwrap().len(),
            "{test}"
        );
    });
}

/// #877: queued receipt IDs remain visible in both public CLI formats.
#[test]
fn queued_receipt_id_matches_json_and_text() {
    let (json_code, json, text_code, text) = both(
        "m14_queued_receipt_id",
        vec![],
        &[],
        &[
            "thr_syn_0006",
            "--op-id",
            "op-m14-queued-id",
            "--",
            "Synthetic",
        ],
    );
    assert_eq!((json_code, text_code), (0, 0), "{json}\n{text}");
    assert_eq!(json["result"]["delivery"]["kind"], "queued");
    assert_eq!(
        json["result"]["delivery"]["queued_message_id"],
        "qmsg_syn_0001"
    );
    assert_eq!(
        text.lines()
            .filter(|line| *line == "queued message: qmsg_syn_0001")
            .count(),
        1,
        "{text}"
    );
}

/// #862: compare full gap lines so a lost subject cannot hide behind its detail.
#[test]
fn send_text_preserves_each_reported_gap_subject_and_detail() {
    let responses = vec![tell_response(
        "thr_syn_0001",
        "queue",
        json!({"abort": true}),
    )];
    let (json_code, json, text_code, text) = both(
        "m14_gap_subject_and_detail",
        responses,
        &[],
        &["thr_syn_0001", "--op-id", "op-m14-gap", "--", "Synthetic"],
    );
    assert_eq!(json_code, EXIT_UNCERTAIN, "{json}");
    assert_eq!(text_code, EXIT_UNCERTAIN, "{text}");
    let gaps = json["gaps"].as_array().unwrap();
    assert!(!gaps.is_empty(), "the fixture must exercise gap rendering");
    let expected: Vec<String> = gaps
        .iter()
        .map(|gap| {
            format!(
                "gap: {} · {}",
                gap["subject"].as_str().unwrap(),
                gap["detail"].as_str().unwrap()
            )
        })
        .collect();
    let actual: Vec<&str> = text
        .lines()
        .filter(|line| line.starts_with("gap: "))
        .collect();
    assert_eq!(actual, expected, "each complete gap line must match JSON");
}

#[test]
fn m14_cli_parser_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 4] = [
        (
            "every_exit_code_is_documented",
            every_exit_code_is_documented,
        ),
        (
            "explicit_attachment_paths_preserve_flag_names_and_literal_message_text",
            explicit_attachment_paths_preserve_flag_names_and_literal_message_text,
        ),
        (
            "help_documents_preview_and_check",
            help_documents_preview_and_check,
        ),
        (
            "op_id_operands_are_validated_as_they_are_parsed",
            op_id_operands_are_validated_as_they_are_parsed,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: m14_cli::{name}");
        proof();
    }
}

fn every_exit_code_is_documented() {
    assert_eq!(EXIT_DELIVERED, 0);
    let help = openwiz_cli::help();
    for (code, words) in [
        (EXIT_DELIVERED, "send: queued, or sent"),
        (EXIT_USAGE, "usage error"),
        (EXIT_NOT_FOUND, "send: the target was not found"),
        (EXIT_SEND_FAILED, "send: failed"),
        (EXIT_UNCERTAIN, "send: uncertain"),
        (EXIT_IN_PROGRESS, "send: in progress"),
        (
            EXIT_CONFLICTING_REUSE,
            "send: the op id is bound to a different",
        ),
        (EXIT_POSSIBLE_DUPLICATE, "send: possible duplicate"),
        (EXIT_RECORD_UNAVAILABLE, "send: the send record"),
    ] {
        let line = help
            .lines()
            .find(|l| l.trim_start().starts_with(&format!("{code} ")) && l.contains(words));
        assert!(
            line.is_some(),
            "exit {code} ({words}) is not documented:\n{help}"
        );
    }
    // #37: Jake approved policy (b), 2026-10-28; no untested-version exit.
    // Private record: https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036
    assert!(
        !help.lines().any(|l| l.trim_start().starts_with("4 ")),
        "exit 4 is still documented:\n{help}"
    );
}

#[test]
fn help_documents_send_its_flags_and_its_limits() {
    let help = openwiz_cli::help();
    for words in [
        "openwiz send <id> [<text>]",
        "--steer",
        "--op-id",
        "--resume-paused-queue",
        "--accept-possible-duplicate",
        "16384 bytes",
        "from stdin",
        "never auto",
        "the provider accepted the message, not that the work completed",
        "can change between the read and the dispatch",
        // B2 (ClosedWiz#15), recorded reason: send attaches staged files
        // (sheet B-7), queue only, all ready or nothing; the help said "no
        // attachments" before.
        "--attach <path>",
        "--attachment <id>",
        "Steer can't carry attachments",
        "Delivery to the agent's machine is never",
        "A file path in the text is sent as text",
        "one target",
    ] {
        assert!(help.contains(words), "{words:?} not in --help:\n{help}");
    }
    // Haiku B-07: the error-stream rule says which outcomes print a report.
    assert!(
        help.contains("send prints its report on stdout for every outcome"),
        "{help}"
    );
    let fake = SendFake::new("m14_help", "send");
    let (code, out, _) = fake.cli(&["--help"], "");
    assert_eq!(code, 0);
    assert_eq!(out, help);
    assert!(fake.invocations().is_empty());
}

#[test]
fn errors_go_to_stderr_with_stdout_empty() {
    let fake = SendFake::new("m14_errors", "send");
    for args in [
        vec![],
        vec!["thr_syn_0001", "--bogus", "--", "Synthetic"],
        vec!["thr_syn_0001", "--op-id"],
        vec!["thr_syn_0001", "--json=yes", "--", "Synthetic"],
    ] {
        let (code, out, err) = fake.cli(&args, "");
        assert_eq!(code, EXIT_USAGE, "{args:?}");
        assert!(out.is_empty(), "{out}");
        assert_eq!(err.lines().count(), 1, "{err}");
        assert!(err.starts_with("openwiz: "), "{err}");
    }
}

/// #828: omitted text must never cause a terminal read, even in JSON mode.
#[test]
fn terminal_stdin_is_refused_before_reading_text_or_opening_state() {
    use openwiz_cli::send::{SendContext, run_send_with};
    use std::io::{Read, Result};

    struct TerminalStdin;
    impl Read for TerminalStdin {
        fn read(&mut self, _: &mut [u8]) -> Result<usize> {
            panic!("terminal stdin was read");
        }
    }

    for json in [false, true] {
        let fake = SendFake::new(&format!("m14_terminal_stdin_{json}"), "send");
        let source = fake.source();
        let mut args = vec!["thr_syn_0001".to_owned()];
        if json {
            args.push("--json".to_owned());
        }
        let (mut out, mut err) = (Vec::new(), Vec::new());
        let code = run_send_with(
            &args,
            SendContext {
                messenger: &source,
                open_store: &|| panic!("opened the send record"),
                open_store_read_only: &|| panic!("opened the read-only send record"),
                clock: &clock(),
                stdin: &mut TerminalStdin,
                stdin_is_terminal: true,
                new_op_id: &|| panic!("generated an op id"),
            },
            &|| panic!("opened the attachment store"),
            &mut out,
            &mut err,
        );
        assert_eq!(code, 2);
        assert!(out.is_empty(), "{out:?}");
        assert_eq!(
            String::from_utf8(err).expect("UTF-8 diagnostic"),
            "openwiz: give the text after the id, or pipe it on stdin (a terminal is never read); nothing was sent (see openwiz --help)\n"
        );
        assert!(!fake.state.exists(), "created send state");
        assert!(fake.invocations().is_empty(), "called the provider");
    }
}

#[test]
fn generated_id_guidance_checks_the_record_without_sending_again() {
    for (name, responses, expected_exit, status) in [
        ("accepted", vec![], EXIT_DELIVERED, "accepted"),
        (
            "uncertain",
            vec![tell_response(
                "thr_syn_0001",
                "queue",
                json!({"abort": true}),
            )],
            EXIT_UNCERTAIN,
            "uncertain",
        ),
    ] {
        let fake = SendFake::with(&format!("m14_guidance_{name}"), responses);
        let (code, out, err) = fake.cli(&["thr_syn_0001", "--json", "Synthetic guidance"], "");
        assert_eq!(code, expected_exit, "{out}{err}");
        let sent: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(sent["status"], status);
        let op_id = sent["op_id"].as_str().unwrap();
        let flags = err
            .split_once(" (use ")
            .and_then(|(_, rest)| rest.strip_suffix(" to check this send again)\n"))
            .expect("generated-ID guidance includes recovery flags");
        let mut args = vec!["thr_syn_0001"];
        args.extend(flags.split_whitespace());
        let calls = fake.invocations();
        assert_eq!(fake.tells().len(), 1);
        let record = std::fs::read(fake.record_path(op_id)).unwrap();

        let (lookup_exit, lookup, lookup_err) = fake.cli(&args, "");
        assert_eq!(lookup_exit, expected_exit, "{lookup}{lookup_err}");
        assert!(lookup.starts_with("openwiz send --check · "), "{lookup}");
        assert!(lookup_err.is_empty(), "{lookup_err}");
        let (json_exit, checked) = fake.cli_json(&args, "");
        assert_eq!(json_exit, expected_exit);
        assert_eq!(checked["schema"], "openwiz.send-lookup.v1");
        assert_eq!(checked["op_id"], op_id);
        assert_eq!(checked["result"]["kind"], "recorded");
        assert_eq!(checked["result"]["report"]["status"], status);
        assert_eq!(fake.invocations(), calls, "lookup called room-cli");
        assert_eq!(fake.tells().len(), 1);
        assert_eq!(std::fs::read(fake.record_path(op_id)).unwrap(), record);
        assert_eq!(
            err,
            format!(
                "openwiz: op id {op_id} (use --op-id {op_id} --check to check this send again)\n"
            )
        );
    }
}

#[test]
fn the_release_build_sends_through_the_fake() {
    let fake = SendFake::new("m14_release", "send");
    let out = fake.run_process(&["send", "thr_syn_0001", "--json"], "Synthetic from stdin");
    let (code, json) = json_of(&out);
    assert_eq!(code, Some(0), "{json}");
    assert!(validate_report(&json).is_empty(), "{json}");
    let op_id = json["op_id"].as_str().unwrap();
    assert!(op_id.starts_with("op-") && op_id.len() == 35, "{op_id}");
    assert_eq!(fake.record(op_id)["delivery"]["kind"], "accepted");
    assert!(
        String::from_utf8_lossy(&out.stderr).contains(op_id),
        "a generated op id is shown before sending"
    );
    let tells = fake.tells();
    assert_eq!(tells.len(), 1);
    assert_eq!(tells[0][7], "Synthetic from stdin");
}

/// #79: `--preview` and `--check` are documented, with their exit codes.
fn help_documents_preview_and_check() {
    use openwiz_cli::send::EXIT_NO_RECORD;
    let help = openwiz_cli::help();
    for words in [
        "openwiz send <id> --preview [--steer] [--json]",
        "openwiz send <id> --op-id <op id> --check [--json]",
        "--preview",
        "--check",
        "no claim and no call",
        "or one in the same mode is still in progress",
        "openwiz.send-preview.v1",
        "openwiz.send-lookup.v1",
    ] {
        assert!(help.contains(words), "{words:?} not in --help:\n{help}");
    }
    assert_eq!(EXIT_NO_RECORD, 11);
    for (code, words) in [
        (EXIT_NO_RECORD, "send --check: no record"),
        (EXIT_POSSIBLE_DUPLICATE, "uncertain or in-progress send"),
        (EXIT_DELIVERED, "send --preview: a send would go ahead"),
        (EXIT_NOT_FOUND, "send --preview: the target was not found"),
        (EXIT_SEND_FAILED, "send --preview: a send would be refused"),
    ] {
        let line = help
            .lines()
            .find(|l| l.trim_start().starts_with(&format!("{code} ")) && l.contains(words));
        assert!(
            line.is_some(),
            "exit {code} ({words}) is not documented:\n{help}"
        );
    }
}

/// #610: synthetic malformed input must not turn a read-only flag into a send.
#[test]
fn missing_op_id_value_must_not_swallow_check_and_dispatch() {
    let fake = SendFake::new("m14_missing_op_id_check", "send");
    let (code, out, err) = fake.cli(
        &[
            "--json",
            "--op-id",
            "--check",
            "--op-id",
            "op-syn-check",
            "thr_syn_0001",
            "--",
            "Synthetic",
        ],
        "",
    );
    println!("fixture exit={code}; fake tell calls={}", fake.tell_count());
    assert_eq!(fake.tell_count(), 0, "malformed arguments dispatched");
    assert!(
        fake.invocations().is_empty(),
        "malformed arguments read room-cli"
    );
    assert!(
        !fake.state.exists(),
        "malformed arguments created send state"
    );
    assert_eq!(code, EXIT_USAGE, "{out}{err}");
    assert!(out.is_empty(), "{out}");
    assert_eq!(err.lines().count(), 1, "{err}");
    assert!(err.starts_with("openwiz: "), "{err}");
}

/// Invalid operands are refused at the public parser boundary, before stdin or stores.
fn op_id_operands_are_validated_as_they_are_parsed() {
    use openwiz_cli::send::parse_send;

    let long = "a".repeat(65);
    for bad in ["", "--check", "--preview", "--", "_x", "a/b", "ünï", &long] {
        for option in [
            vec!["--op-id".to_owned(), bad.to_owned()],
            vec![format!("--op-id={bad}")],
        ] {
            let mut args = vec!["thr_syn_0001".to_owned()];
            args.extend(option);
            assert!(parse_send(&args).is_err(), "accepted {args:?}");
        }
    }
    assert!(parse_send(&["thr_syn_0001".to_owned(), "--op-id".to_owned()]).is_err());
}

#[test]
fn repeated_op_id_options_are_refused_without_reads_or_state() {
    let options = [
        vec!["--op-id", "op-first", "--op-id", "op-first"],
        vec!["--op-id", "op-first", "--op-id", "op-second"],
        vec!["--op-id=op-first", "--op-id=op-second"],
        vec!["--op-id=op-first", "--op-id", "op-second"],
        vec!["--op-id", "op-first", "--op-id=op-second"],
    ];
    for (i, options) in options.iter().enumerate() {
        for stdin in [false, true] {
            let fake = SendFake::new(&format!("m14_repeated_op_{i}_{stdin}"), "send");
            let mut args = vec!["thr_syn_0001", "--json"];
            args.extend(options);
            if !stdin {
                args.extend(["--", "Synthetic"]);
            }
            let (code, out, err) = fake.cli(&args, "Synthetic from stdin");
            assert_eq!(fake.tell_count(), 0, "{args:?} dispatched");
            assert!(fake.invocations().is_empty(), "{args:?} read room-cli");
            assert!(!fake.state.exists(), "{args:?} created state");
            assert_eq!(code, EXIT_USAGE, "{args:?}: {out}{err}");
            assert!(out.is_empty(), "{out}");
            assert_eq!(err.lines().count(), 1, "{err}");
            assert!(err.starts_with("openwiz: "), "{err}");
        }
    }
}

#[test]
fn valid_op_id_forms_preserve_check_and_literal_message_text() {
    use openwiz_cli::send::EXIT_NO_RECORD;

    let long = "a".repeat(64);
    let text = "--check --op-id=op-literal --preview Synthetic";
    for (i, op_id) in ["a", "A_b-9", &long].into_iter().enumerate() {
        for inline in [false, true] {
            let fake = SendFake::new(&format!("m14_valid_op_{i}_{inline}"), "send");
            let option = format!("--op-id={op_id}");
            let mut args = vec!["thr_syn_0001", "--json"];
            args.extend(if inline {
                vec![option.as_str()]
            } else {
                vec!["--op-id", op_id]
            });
            let mut check = args.clone();
            check.push("--check");
            let (code, json) = fake.cli_json(&check, "unused stdin");
            assert_eq!(code, EXIT_NO_RECORD, "{json}");
            assert!(fake.invocations().is_empty());
            assert!(!fake.state.exists());

            args.extend(["--", text]);
            let (code, json) = fake.cli_json(&args, "unused stdin");
            assert_eq!(code, EXIT_DELIVERED, "{json}");
            assert_eq!(json["op_id"], op_id);
            assert_eq!(fake.tell_count(), 1);
            assert_eq!(fake.tells().len(), 1);
            assert_eq!(fake.tells()[0][7], text);
            let before = sends_listing(&fake);
            let calls = fake.invocations();
            let (code, json) = fake.cli_json(&check, "unused stdin");
            assert_eq!(code, EXIT_DELIVERED, "{json}");
            assert_eq!(json["op_id"], op_id);
            assert_eq!(fake.invocations(), calls);
            assert_eq!(sends_listing(&fake), before);
        }
    }
}

/// #789: an attachment operand must not swallow a read-only switch or delimiter.
#[test]
fn missing_attachment_value_must_not_swallow_read_only_switches_and_dispatch() {
    let mut results = Vec::new();
    for (i, operand) in ["--check", "--preview", "--"].into_iter().enumerate() {
        for (j, flag) in ["--attach", "--attachment"].into_iter().enumerate() {
            let fake = SendFake::new(&format!("m14_missing_attachment_{i}_{j}"), "send");
            std::fs::write(fake.dir.join(operand), "Synthetic attachment.\n").unwrap();
            let output = fake.run_process(
                &["send", "thr_syn_0001", flag, operand, "--", "Synthetic"],
                "",
            );
            let code = output.status.code();
            let calls = fake.invocations().len();
            let tells = fake.tell_count();
            let state = fake.state.exists();
            println!(
                "{flag} {operand}: exit={code:?} room_calls={calls} tell_calls={tells} state={state}"
            );
            results.push((code, calls, tells, state, output));
        }
    }
    for (code, calls, tells, state, output) in results {
        assert_eq!(calls, 0, "malformed arguments read room-cli");
        assert_eq!(tells, 0, "malformed arguments dispatched");
        assert!(!state, "malformed arguments created state or staged a file");
        assert_eq!(code, Some(EXIT_USAGE), "{output:?}");
        assert!(output.stdout.is_empty(), "{output:?}");
        let err = String::from_utf8(output.stderr).unwrap();
        assert_eq!(err.lines().count(), 1, "{err}");
        assert!(err.starts_with("openwiz: "), "{err}");
    }
}

fn explicit_attachment_paths_preserve_flag_names_and_literal_message_text() {
    use openwiz_cli::attach::AttachArg;
    use openwiz_cli::send::{SendCommand, parse_send};

    let text = "--check --preview --attach Synthetic";
    for name in ["--check", "--preview", "--"] {
        for (options, expected_path) in [
            (vec![format!("--attach={name}")], name.to_owned()),
            (
                vec!["--attach".to_owned(), format!("./{name}")],
                format!("./{name}"),
            ),
        ] {
            let mut args = vec!["thr_syn_0001".to_owned()];
            args.extend(options);
            args.extend(["--".to_owned(), text.to_owned()]);
            let SendCommand::Send(parsed) = parse_send(&args).expect("explicit path") else {
                panic!("explicit path requested help");
            };
            assert_eq!(parsed.attachments, vec![AttachArg::Path(expected_path)]);
            assert_eq!(parsed.text.as_deref(), Some(text));
            assert!(!parsed.check && !parsed.preview);
        }
    }
}
