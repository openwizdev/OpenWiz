//! CP2: exercise the same dispatcher as production through a real process.
use super::{ROOT, Sandbox, schema};
use serde_json::Value;
use std::{ffi::OsString, fs, os::unix::ffi::OsStringExt, path::Path};

fn document(output: &std::process::Output, code: i32, schema_name: &str) -> Value {
    assert_eq!(
        output.status.code(),
        Some(code),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stdout.ends_with(b"\n"),
        "one newline-terminated document: {:?}",
        output.stdout
    );
    let doc: Value = serde_json::from_slice(&output.stdout).expect("exactly one JSON document");
    assert_eq!(doc["schema"], schema_name);
    let contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(schema::validate(&contract, &doc), Vec::<String>::new());
    doc
}

#[test]
fn cp2_usage_errors_cover_every_dispatch_family_without_effects() {
    let sandbox = Sandbox::new();
    for (args, command) in [
        (vec!["ls", "--unknown", "--json"], "ls"),
        (vec!["show", "--json"], "show"),
        (vec!["models", "--unknown", "--json"], "models"),
        (vec!["fleets", "--json", "--json"], "fleets"),
        (vec!["fleet", "--json"], "fleet"),
        (vec!["fleet", "tick", "--unknown", "--json"], "fleet.tick"),
        (
            vec!["fleet", "tick", "--dry-run", "--unknown", "--json"],
            "fleet.tick.preview",
        ),
        (vec!["fleet", "due", "--json"], "fleet.due"),
        (
            vec!["loop", "off", "synthetic", "--unknown", "--json"],
            "loop.off",
        ),
        (
            vec!["loop", "on", "synthetic", "--unknown", "--json"],
            "loop.on",
        ),
        (vec!["unknown-synthetic", "--json"], "unknown"),
        (vec!["ls", "--json=value", "--json"], "ls"),
        (
            vec!["loop", "off", "synthetic", "--json", "--json"],
            "loop.off",
        ),
    ] {
        let doc = document(&sandbox.run(&args), 2, "openwiz.cli-error.v1");
        assert_eq!(doc["command"], command, "{args:?}");
        assert_eq!(doc["exit_code"], 2);
        assert_eq!(doc["error"]["kind"], "usage");
    }
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
}

#[test]
fn cp2_json_help_is_one_document_with_no_reads_or_state() {
    let sandbox = Sandbox::new();
    for args in [
        vec!["help", "--json"],
        vec!["--help", "--json"],
        vec!["ls", "--help", "--json"],
        vec!["show", "-h", "--json"],
        vec!["models", "--help", "--json"],
        vec!["fleets", "-h", "--json"],
        vec!["loop", "--help", "--json"],
    ] {
        let doc = document(&sandbox.run(&args), 0, "openwiz.cli-help.v1");
        assert!(doc["text"].as_str().unwrap().contains("openwiz"));
    }
    document(
        &sandbox.run(&["help", "--agent", "--json"]),
        2,
        "openwiz.cli-error.v1",
    );
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
}

#[test]
fn cp2_json_selection_respects_values_delimiters_and_invalid_bytes() {
    let sandbox = Sandbox::new();
    for args in [
        vec!["ls", "--limit", "--json"],
        vec!["ls", "--offset=--json"],
        vec!["ls", "--json=true"],
    ] {
        let output = sandbox.run(&args);
        assert_eq!(output.status.code(), Some(2), "{args:?}");
        assert!(
            output.stdout.is_empty(),
            "data must not select JSON: {args:?}"
        );
    }
    for command in ["ls", "show", "models", "fleets", "fleet", "loop"] {
        let output = sandbox.run_os(&[
            OsString::from(command),
            OsString::from_vec(vec![0xff]),
            OsString::from("--json"),
        ]);
        document(&output, 2, "openwiz.cli-error.v1");
    }
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
}

#[test]
fn cp2_no_command_json_is_bounded_usage_without_effects() {
    let sandbox = Sandbox::new();
    let out = sandbox.run(&[]);
    assert_eq!(out.status.code(), Some(2));
    assert!(out.stdout.is_empty());
    document(&sandbox.run(&["--json"]), 2, "openwiz.cli-error.v1");
    assert!(!sandbox.0.join("state").exists());
    assert!(!sandbox.0.join("calls").exists());
}

#[test]
fn cp2_all_known_value_options_consume_flag_looking_data() {
    let sandbox = Sandbox::new();
    for (command, flag) in [("ls", "--limit"), ("ls", "--offset")] {
        let inline = format!("{flag}=--json");
        for args in [
            vec![command, flag, "--json"],
            vec![command, inline.as_str()],
        ] {
            let out = sandbox.run(&args);
            assert_eq!(out.status.code(), Some(2), "{args:?}");
            assert!(out.stdout.is_empty(), "{args:?}");
        }
    }
    for invalid in [b"--json\xff".as_slice(), b"--json=\xff"] {
        let out = sandbox.run_os(&[OsString::from("ls"), OsString::from_vec(invalid.to_vec())]);
        assert_eq!(out.status.code(), Some(2));
        assert!(out.stdout.is_empty());
    }
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
}
