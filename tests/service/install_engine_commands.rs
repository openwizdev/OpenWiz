//! The installed engine's source-free CLI discovery, through the real binary.
use super::*;

#[test]
fn engine_json_boundary_identifies_command_and_consumes_values() {
    for (args, json, command) in [
        (vec!["preview", "--json"], true, "engine.preview"),
        (
            vec!["status", "--state-dir", "--json"],
            false,
            "engine.status",
        ),
        (vec!["invalid", "--json"], true, "unknown"),
    ] {
        let args: Vec<_> = args.into_iter().map(std::ffi::OsString::from).collect();
        let (mut stdout, mut stderr) = (Vec::new(), Vec::new());
        let code = openwiz_cli::engine::run(&args, &mut stdout, &mut stderr);
        assert_ne!(code, 0);
        if json {
            let report: Value = serde_json::from_slice(&stdout).unwrap();
            assert_eq!(report["schema"], "openwiz.cli-error.v1");
            assert_eq!(report["command"], command);
            assert_eq!(report["exit_code"], code);
            assert!(stderr.is_empty());
        } else {
            assert!(stdout.is_empty());
            assert!(!stderr.is_empty());
        }
    }
}

#[test]
fn engine_help_is_source_free_and_registered_in_agent_discovery() {
    let built = Command::new(env!("CARGO"))
        .args(["build", "-p", "openwiz-cli", "--bin", "openwiz", "--locked"])
        .current_dir(ROOT)
        .output()
        .unwrap();
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stderr)
    );
    let cli = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .parent()
        .unwrap()
        .join("debug/openwiz");
    let out = Command::new(&cli)
        .args(["engine", "--help", "--json"])
        .output()
        .unwrap();
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let help: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(help["schema"], "openwiz.cli-help.v1");
    assert!(
        help["text"]
            .as_str()
            .unwrap()
            .contains("Cloud engine activation is an unresolved gap")
    );
    let out = Command::new(&cli)
        .args(["help", "--agent"])
        .output()
        .unwrap();
    assert!(out.status.success());
    let help: Value = serde_json::from_slice(&out.stdout).unwrap();
    for name in ["engine.preview", "engine.activate", "engine.status"] {
        assert!(
            help["commands"]
                .as_array()
                .unwrap()
                .iter()
                .any(|c| c["name"] == name),
            "{name}"
        );
    }
    // Actual installed tool/process proofs run in test_package.py, after CI
    // provisions Python. This Rust-stage discovery proof requires no Python.
}
