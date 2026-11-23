use serde_json::{Value, json};
use std::fs;
use std::path::Path;
use std::process::{Command, Output, Stdio};

use super::{ROOT, Sandbox};

const UPDATED: &str = "Synthetic loop updated\n";
const CREATED: &str = "Synthetic loop created: loop_syn_7\n";

fn room() -> (Sandbox, String) {
    let sandbox = Sandbox::new();
    let bin = sandbox.0.join("bin");
    fs::remove_file(bin.join("room-cli")).unwrap();
    std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), bin.join("room-cli")).unwrap();
    let scenario = Path::new(ROOT).join("tests/fake-room-cli/loops/scenario.json");
    fs::write(
        bin.join("fake-room-cli.scenario"),
        scenario.to_str().unwrap(),
    )
    .unwrap();
    let prompt = sandbox.0.join("prompt.md");
    fs::write(&prompt, "Synthetic prompt.\n").unwrap();
    (sandbox, prompt.to_str().unwrap().to_owned())
}

fn call(sandbox: &Sandbox, argv: &[&str]) -> Output {
    Command::new(sandbox.0.join("bin/room-cli"))
        .args(argv)
        .env_clear()
        .stdin(Stdio::null())
        .output()
        .unwrap()
}

#[test]
fn a_loop_value_spelled_like_a_flag_is_never_read_as_one() {
    let (sandbox, prompt) = room();
    let p = prompt.as_str();
    let cases: [(&[&str], &str, Value); 3] = [
        (
            &[
                "loop",
                "update",
                "loop_syn_1",
                "--prompt",
                "--prompt-file",
                "--secrets",
                "none",
            ],
            UPDATED,
            json!({}),
        ),
        (
            &[
                "loop",
                "create",
                "--name",
                "Synthetic",
                "--prompt-file",
                p,
                "--cron",
                "0 9 * * *",
                "--timezone",
                "UTC",
                "--new-thread",
                "--provider",
                "codex",
                "--model",
                "--webhook",
                "--reasoning",
                "high",
                "--priority",
                "2",
                "--secrets",
                "none",
            ],
            CREATED,
            json!({"--prompt-file": "Synthetic prompt.\n"}),
        ),
        (
            &[
                "loop",
                "create",
                "--name",
                "--script-file",
                "--prompt-file",
                p,
                "--at",
                "2026-12-01T09:00:00Z",
                "--same-thread",
                "--priority",
                "3",
                "--secrets",
                "none",
            ],
            CREATED,
            json!({"--prompt-file": "Synthetic prompt.\n"}),
        ),
    ];
    for (argv, stdout, files) in cases {
        let log = sandbox.0.join("bin/loop-writes.log");
        let _ = fs::remove_file(&log);
        let out = call(&sandbox, argv);
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert_eq!(out.status.code(), Some(0), "{argv:?}: {stderr}");
        assert_eq!(String::from_utf8_lossy(&out.stdout), stdout, "{argv:?}");
        let line: Value = serde_json::from_str(&fs::read_to_string(&log).unwrap()).unwrap();
        assert_eq!(line, json!({"argv": argv, "files": files}), "{argv:?}");
    }
}

#[test]
fn a_loop_write_whose_record_fails_fails_before_answering() {
    let (sandbox, prompt) = room();
    fs::create_dir(sandbox.0.join("bin/loop-writes.log")).unwrap();
    let writes: [&[&str]; 2] = [
        &["loop", "update", "loop_syn_1", "--name", "Synthetic"],
        &[
            "loop",
            "create",
            "--name",
            "Synthetic",
            "--prompt-file",
            &prompt,
            "--webhook",
            "--new-thread",
            "--priority",
            "4",
            "--secrets",
            "none",
        ],
    ];
    for argv in writes {
        let out = call(&sandbox, argv);
        assert_eq!(out.status.code(), Some(1), "{argv:?}");
        assert_eq!(out.stdout, b"", "{argv:?}");
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(
            stderr.contains("could not be recorded in loop-writes.log"),
            "{stderr}"
        );
    }
}
