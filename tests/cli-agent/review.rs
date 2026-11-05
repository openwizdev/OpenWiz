//! First review R1–R3. All targets, paths and bytes are synthetic assumptions;
//! the real fixture CLI shares production dispatch, with recording source traps.
use super::{ROOT, Sandbox, discovered, schema};
use serde_json::{Value, json};
use std::ffi::OsString;
use std::fs;
use std::os::unix::ffi::OsStringExt;
use std::path::Path;

const INVENTORY_HELP: &str = "Help precedence: standalone --help or -h anywhere after the command selects human help before parsing, including separate value positions and after --. Embedded values such as --limit=--help do not match.";
const FLEETS_HELP: &str = "Help precedence: standalone --help or -h selects human help despite earlier ordinary errors, unless an earlier argument is not UTF-8. Arguments after help are not parsed; embedded option values do not match.";
const ATTACHMENT_IDS: &str = "Attachment IDs in the combined ordered --attach/--attachment list must be unique. Late duplicate-ID rejection exits 2 without send/create; staged copies and opened local stores may remain.";

fn form<'a>(catalogue: &'a Value, name: &str) -> &'a Value {
    catalogue["commands"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == name)
        .unwrap()
}

#[test]
fn r1_help_precedence_matches_the_shipped_parser_and_catalogue() {
    let sandbox = Sandbox::new();
    let catalogue = discovered();
    let help_flag = catalogue["flags"]
        .as_array()
        .unwrap()
        .iter()
        .find(|flag| flag["name"] == "--help")
        .unwrap();
    assert_eq!(help_flag["arity"], "switch");
    assert_eq!(help_flag["inline"], false);
    for text in ["--help", "--help=", "--help=1"] {
        let args = ["thread-synthetic", "--", text].map(str::to_owned);
        let openwiz_cli::send::SendCommand::Send(parsed) =
            openwiz_cli::send::parse_send(&args).unwrap()
        else {
            panic!("message text requested help");
        };
        assert_eq!(parsed.text.as_deref(), Some(text));
        let args = [
            "project-synthetic",
            "--harness",
            "codex",
            "--model",
            text,
            "--effort",
            "high",
            "--",
            text,
        ]
        .map(str::to_owned);
        let openwiz_cli::new_thread::NewCommand::New(parsed) =
            openwiz_cli::new_thread::parse_new(&args).unwrap()
        else {
            panic!("model value or prompt text requested help");
        };
        assert_eq!(parsed.model.as_deref(), Some(text));
        assert_eq!(parsed.text.as_deref(), Some(text));
    }
    for args in [
        vec!["ls", "--unknown", "--help"],
        vec!["ls", "--limit", "--help"],
        vec!["ls", "--offset", "-h"],
        vec!["ls", "--", "--help"],
        vec!["show", "--unknown", "--help"],
        vec!["show", "--", "-h"],
    ] {
        let strings: Vec<_> = args.iter().map(|s| (*s).to_owned()).collect();
        assert_eq!(
            openwiz_cli::parse(&strings).unwrap(),
            openwiz_cli::Command::Help
        );
        let output = sandbox.run(&args);
        assert_eq!(output.status.code(), Some(0), "{args:?}");
        assert_eq!(output.stdout, openwiz_cli::help().as_bytes());
        assert!(output.stderr.is_empty());
    }
    for flag in ["--help", "-h"] {
        let output = sandbox.run(&["fleets", "--unknown", flag]);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(output.stdout, openwiz_cli::help().as_bytes());
        assert!(output.stderr.is_empty());
    }
    let invalid = OsString::from_vec(vec![0xff]);
    for (args, expected) in [
        (
            vec![
                OsString::from("fleets"),
                invalid.clone(),
                OsString::from("--help"),
            ],
            2,
        ),
        (
            vec![OsString::from("fleets"), OsString::from("--help"), invalid],
            0,
        ),
    ] {
        let output = sandbox.run_os(&args);
        assert_eq!(output.status.code(), Some(expected));
        if expected == 0 {
            assert_eq!(output.stdout, openwiz_cli::help().as_bytes());
            assert!(output.stderr.is_empty());
        } else {
            assert!(output.stdout.is_empty());
            assert!(output.stderr.starts_with(b"openwiz:"));
        }
    }
    for args in [
        vec!["ls", "--limit=--help"],
        vec!["show", "--help=1"],
        vec!["fleets", "--json=--help"],
    ] {
        let output = sandbox.run(&args);
        assert_eq!(
            output.status.code(),
            Some(2),
            "embedded help is data: {args:?}"
        );
        assert!(output.stdout.is_empty());
    }
    // HX1: the two option-splitting parsers must agree with inline=false,
    // including empty values; standalone help and legacy precedence stay put.
    let mut cases = Vec::new();
    for command in ["send", "new", "show", "models", "ui"] {
        for (flag, code) in [
            ("--help", 0),
            ("-h", 0),
            ("--help=1", 2),
            ("--help=", 2),
            ("--help=--json", 2),
        ] {
            cases.push((vec![command, flag], code));
        }
    }
    for command in ["send", "new"] {
        for (tail, code) in [
            (vec!["--help", "--unknown"], 0),
            (vec!["--unknown", "--help"], 2),
            (vec!["--help", "--help=1"], 0),
            (vec!["--help=1", "--help"], 2),
            (vec!["--op-id", "--help"], 2),
            (vec!["--op-id=--help"], 2),
            (vec!["--", "--help"], 2),
            (vec!["--", "--help=1"], 2),
        ] {
            let mut args = vec![command];
            args.extend(tail);
            cases.push((args, code));
        }
    }
    for (args, code) in cases {
        for json in [false, true] {
            let mut args = args.clone();
            if json {
                args.insert(1, "--json");
            }
            let output = sandbox.run(&args);
            assert_eq!(output.status.code(), Some(code), "{args:?}");
            if json {
                let doc: Value = serde_json::from_slice(&output.stdout).unwrap();
                assert_eq!(
                    doc["schema"],
                    if code == 0 {
                        "openwiz.cli-help.v1"
                    } else {
                        "openwiz.cli-error.v1"
                    },
                    "{args:?}"
                );
                if code == 2 {
                    assert_eq!(doc["exit_code"], 2);
                    assert_eq!(doc["error"]["kind"], "usage");
                }
            } else if code == 2 {
                assert!(output.stdout.is_empty(), "{args:?}");
                assert!(output.stderr.starts_with(b"openwiz:"), "{args:?}");
            } else {
                assert!(!output.stdout.is_empty(), "{args:?}");
                assert!(output.stderr.is_empty(), "{args:?}");
            }
        }
    }
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
    assert!(!sandbox.0.join("home").exists());

    for name in ["ls", "show"] {
        assert!(
            form(&catalogue, name)["rules"]
                .as_array()
                .unwrap()
                .contains(&json!(INVENTORY_HELP)),
            "{name}: catalogue must state actual help precedence"
        );
    }
    assert!(
        form(&catalogue, "fleets")["rules"]
            .as_array()
            .unwrap()
            .contains(&json!(FLEETS_HELP))
    );
}

#[test]
fn r2_duplicate_attachment_rejection_retains_staged_bytes_without_source_calls() {
    for name in ["send", "new", "new.preview"] {
        let sandbox = Sandbox::new();
        fs::write(sandbox.0.join("old.txt"), b"synthetic old bytes\n").unwrap();
        fs::write(sandbox.0.join("new.txt"), b"synthetic newly staged bytes\n").unwrap();
        let staged = sandbox.run(&["attachment", "add", "--json", "old.txt"]);
        assert_eq!(
            staged.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&staged.stderr)
        );
        let report: Value = serde_json::from_slice(&staged.stdout).unwrap();
        assert_eq!(report["ready"].as_array().unwrap().len(), 1);
        let id = report["ready"][0]["staged"]["attachment"]["id"]
            .as_str()
            .unwrap();
        let mut args = if name == "send" {
            vec!["send", "thread-synthetic", "--op-id", "op-synthetic"]
        } else {
            vec![
                "new",
                "--project-id",
                "project-synthetic",
                "--harness",
                "codex",
                "--model",
                "model-synthetic",
                "--effort",
                "high",
                "--op-id",
                "op-synthetic",
            ]
        };
        if name == "new" {
            args.push("--yes");
        }
        args.extend([
            "--attach",
            "new.txt",
            "--attachment",
            id,
            "--attachment",
            id,
            "--",
            "synthetic prompt",
        ]);
        let rejected = sandbox.run(&args);
        assert_eq!(
            rejected.status.code(),
            Some(2),
            "{name}: {}",
            String::from_utf8_lossy(&rejected.stderr)
        );
        assert!(rejected.stdout.is_empty());
        assert!(String::from_utf8_lossy(&rejected.stderr).contains("listed twice"));
        assert!(
            !sandbox.0.join("calls").exists(),
            "{name}: exactly zero CloudRoom/gh calls"
        );
        assert_eq!(
            sandbox.0.join("state/sends").is_dir(),
            name == "send",
            "send opens its store before late validation"
        );
        assert!(!sandbox.0.join("state/new-threads").exists());

        let listed = sandbox.run(&["attachment", "ls", "--json"]);
        assert_eq!(listed.status.code(), Some(0));
        let report: Value = serde_json::from_slice(&listed.stdout).unwrap();
        let attachments = report["attachments"].as_array().unwrap();
        assert_eq!(
            attachments.len(),
            2,
            "original plus retained newly staged copy"
        );
        assert_eq!(report["broken"], json!([]));
        assert_eq!(report["expired"], json!([]));
        for (filename, bytes) in [
            ("old.txt", b"synthetic old bytes\n".as_slice()),
            ("new.txt", b"synthetic newly staged bytes\n".as_slice()),
        ] {
            let a = attachments
                .iter()
                .find(|a| a["attachment"]["name"] == filename)
                .unwrap();
            let copy = sandbox
                .0
                .join("state/attachments")
                .join(a["attachment"]["id"].as_str().unwrap())
                .join(filename);
            assert_eq!(fs::read(copy).unwrap(), bytes);
            assert_eq!(fs::read(sandbox.0.join(filename)).unwrap(), bytes);
        }
        assert!(!sandbox.0.join("calls").exists());
    }
}

#[test]
fn r2_catalogue_qualifies_late_usage_rejection_and_unique_ids() {
    let catalogue = discovered();
    for name in ["send", "new", "new.preview"] {
        let command = form(&catalogue, name);
        let usage = command["exits"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["code"] == 2)
            .unwrap();
        assert_eq!(
            usage["meaning"],
            "Usage error or out-of-bounds request; no send/create. Attachment preparation and opened local stores may remain.",
            "{name}: usage does not guarantee unchanged local state"
        );
        assert!(
            command["rules"]
                .as_array()
                .unwrap()
                .contains(&json!(ATTACHMENT_IDS)),
            "{name}: combined attachment IDs must be unique"
        );
    }
}

#[test]
fn r3_catalogue_and_schema_cover_conditional_external_programs() {
    let catalogue = discovered();
    for (name, expected) in [
        ("send", json!(["room-cli", "df"])),
        ("new", json!(["room-cli", "df"])),
        ("new.preview", json!(["room-cli", "df"])),
        ("loop.off", json!(["git"])),
        ("loop.on", json!(["git"])),
    ] {
        assert_eq!(
            form(&catalogue, name)["sources"],
            expected,
            "{name}: every possible external program is advertised"
        );
    }
    let contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(schema::lint(&contract), Vec::<String>::new());
    assert_eq!(
        schema::validate(&contract, &catalogue),
        Vec::<String>::new()
    );
    let mut unknown = catalogue.clone();
    let command = unknown["commands"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|c| c["name"] == "loop.off")
        .unwrap();
    command["sources"] = json!(["unknown-program"]);
    assert!(
        !schema::validate(&contract, &unknown).is_empty(),
        "unknown programs still fail closed"
    );
}
