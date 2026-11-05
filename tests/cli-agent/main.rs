//! CP1: process/schema/zero-source proof. All inputs and identifiers are synthetic.
use serde_json::Value;
use std::ffi::OsString;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::{
    OnceLock,
    atomic::{AtomicU64, Ordering},
};

#[allow(dead_code)]
#[path = "../support/dirs.rs"]
mod dirs;
#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod schema;

// The `openwiz` binary's ui module, as the binary compiles it.
#[allow(dead_code)]
#[path = "../../crates/cli/src/ui.rs"]
mod cli_ui;

mod github_token;
mod process;
mod results;
mod review;
mod ui;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

fn fixture_cli() -> &'static Path {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    BUILT.get_or_init(|| {
        let target = Path::new(env!("CARGO_TARGET_TMPDIR")).parent().unwrap();
        let result = Command::new(env!("CARGO"))
            .args([
                "build",
                "--locked",
                "-p",
                "openwiz-tests",
                "--example",
                "openwiz",
                "--target-dir",
            ])
            .arg(target)
            .current_dir(ROOT)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        target.join("debug/examples/openwiz")
    })
}

struct Sandbox(PathBuf);
impl Sandbox {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-cp1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        dirs::private_dir(&root).unwrap();
        dirs::private_dir(root.join("bin")).unwrap();
        // Both possible source programs leave evidence if discovery calls them.
        let program = root.join("bin/room-cli");
        fs::write(
            &program,
            "#!/bin/sh\nprintf 'unexpected source call\\n' >> \"$CP1_CALLS\"\nexit 99\n",
        )
        .unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
        std::os::unix::fs::symlink(&program, root.join("bin/gh")).unwrap();
        Self(root)
    }

    fn run(&self, args: &[&str]) -> Output {
        self.run_os(&args.iter().map(OsString::from).collect::<Vec<_>>())
    }

    fn run_os(&self, args: &[OsString]) -> Output {
        Command::new(fixture_cli())
            .args(args)
            .env_clear()
            .env("PATH", self.0.join("bin"))
            .env("HOME", self.0.join("home"))
            .env("OPENWIZ_STATE_DIR", self.0.join("state"))
            .env("OPENWIZ_FIXTURE_PROGRAM", self.0.join("bin/room-cli"))
            .env("CP1_CALLS", self.0.join("calls"))
            .current_dir(&self.0)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    }
}

fn discovered() -> Value {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&["help", "--agent"]);
    assert_eq!(output.status.code(), Some(0));
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn cp1_catalogue_covers_the_public_command_flag_and_schema_matrix() {
    let catalogue = discovered();
    // Literal expectations from the existing command parsers/spec, not from the
    // catalogue builder. Forms that forbid write flags have their own rows.
    let matrix = [
        ("help", "--json"),
        ("help.agent", "--agent"),
        ("ls", "-l -a --hidden --limit --offset --json --help"),
        ("show", "--json --help"),
        (
            "send",
            "--steer --op-id --json --resume-paused-queue --accept-possible-duplicate --attach --attachment -- --help",
        ),
        ("send.preview", "--preview --steer --json -- --help"),
        ("send.check", "--check --op-id --json -- --help"),
        (
            "new",
            "--project-id --harness --model --effort --op-id --text-sha256 --attach --attachment --json -- --help --yes",
        ),
        (
            "new.preview",
            "--project-id --harness --model --effort --op-id --text-sha256 --attach --attachment --json -- --help",
        ),
        ("new.status", "--status --json -- --help"),
        ("models", "--json --help"),
        ("attachment.add", "--json -- --help"),
        ("attachment.ls", "--json -- --help"),
        ("attachment.rm", "--json -- --help"),
        ("fleets", "--json --help"),
        ("fleet", "--json"),
        ("fleet.tick", "--json --expect-plan"),
        ("fleet.tick.preview", "--dry-run --json"),
        ("fleet.due", "--github-only --json"),
        ("loop.off", "--json"),
        ("loop.on", "--json"),
        ("ui", "--port --allowed-host --json --help"),
        ("engine.preview", "--json --state-dir --location"),
        (
            "engine.activate",
            "--json --state-dir --yes --operation --root",
        ),
        ("engine.status", "--json --state-dir"),
        ("github.token", "--repository --read --help"),
    ];
    let commands = catalogue["commands"].as_array().unwrap();
    assert_eq!(commands.len(), matrix.len());
    let flags = catalogue["flags"].as_array().unwrap();
    let names: std::collections::BTreeSet<_> =
        flags.iter().map(|f| f["name"].as_str().unwrap()).collect();
    assert_eq!(names.len(), flags.len(), "unique flag definitions");
    for (command, (name, expected)) in commands.iter().zip(matrix) {
        assert_eq!(command["name"], name);
        let actual: Vec<_> = command["flags"]
            .as_array()
            .unwrap()
            .iter()
            .map(|f| f.as_str().unwrap())
            .collect();
        assert_eq!(
            actual,
            expected.split_whitespace().collect::<Vec<_>>(),
            "{name}"
        );
        for flag in &actual {
            assert!(names.contains(flag), "undefined flag {name}: {flag}");
        }
        for flag in command["required_flags"].as_array().unwrap() {
            assert!(
                actual.contains(&flag.as_str().unwrap()),
                "required flag is available"
            );
        }
        assert!(!command["exits"].as_array().unwrap().is_empty());
        assert!(!command["examples"].as_array().unwrap().is_empty());
        assert!(!command["effects"].as_array().unwrap().is_empty());
        for result in command["results"].as_array().unwrap() {
            let (file, fragment) = result["reference"]
                .as_str()
                .unwrap()
                .split_once('#')
                .unwrap();
            let schema: Value =
                serde_json::from_str(&fs::read_to_string(Path::new(ROOT).join(file)).unwrap())
                    .unwrap();
            let target = schema
                .pointer(fragment)
                .unwrap_or_else(|| panic!("unresolved {}", result["reference"]));
            if result["schema"] == "local loop switch event" {
                assert!(
                    target["properties"].get("schema").is_none(),
                    "unchanged event has no schema field"
                );
            } else {
                assert_eq!(
                    target["properties"]["schema"]["const"], result["schema"],
                    "{name} refers to its actual report definition"
                );
            }
        }
        // Parse documented examples at the public parser seam, never dispatch
        // a write. Loop/models/fleets lack a public parser; checked below/help.
        for example in command["examples"].as_array().unwrap() {
            let args: Vec<String> = example
                .as_array()
                .unwrap()
                .iter()
                .map(|a| a.as_str().unwrap().to_owned())
                .collect();
            let os: Vec<_> = args[1..].iter().map(std::ffi::OsString::from).collect();
            match args[0].as_str() {
                "help" | "ls" | "show" => {
                    openwiz_cli::parse(&args).unwrap();
                }
                "send" => {
                    openwiz_cli::send::parse_send(&args[1..]).unwrap();
                }
                "new" => {
                    openwiz_cli::new_thread::parse_new(&args[1..]).unwrap();
                }
                "attachment" => {
                    openwiz_cli::attachment::parse_attachment(&os).unwrap();
                }
                "fleet" if matches!(args[1].as_str(), "tick" | "due") => {
                    openwiz_cli::fleet::tick::parse(&os).unwrap();
                }
                "fleet" => {
                    openwiz_cli::fleet::parse(&os).unwrap();
                }
                "ui" => {
                    cli_ui::parse_ui(&os).unwrap();
                }
                "loop" | "models" | "fleets" => {}
                // The packaged Python parser is exercised by the existing
                // package-proof stage after CI provisions Python.
                "engine" => {}
                "github" => drop(openwiz_cli::github_token::parse(&args[1..]).unwrap()),
                other => panic!("unexpected shipped command {other}"),
            }
        }
    }
    let flag = |name| flags.iter().find(|f| f["name"] == name).unwrap();
    assert_eq!(flag("--limit")["default"], "100");
    assert_eq!(flag("--offset")["default"], "0");
    assert_eq!(flag("--steer")["default"], "false");
    assert_eq!(flag("--help")["aliases"], serde_json::json!(["-h"]));
    for name in ["--harness", "--model", "--effort"] {
        assert!(flag(name)["default"].is_null());
    }
    for name in ["--attach", "--attachment"] {
        assert_eq!(flag(name)["repeatable"], true);
    }
}

#[test]
fn cp1_help_aliases_and_invalid_agent_forms_have_no_effects() {
    let sandbox = Sandbox::new();
    for args in [
        vec!["help"],
        vec!["--help"],
        vec!["-h"],
        vec!["ls", "--help"],
        vec!["show", "-h"],
        vec!["send", "--help"],
        vec!["new", "-h"],
        vec!["models", "--help"],
        vec!["attachment", "--help"],
        vec!["fleets", "-h"],
        vec!["loop", "--help"],
        vec!["loop", "-h"],
        vec!["ui", "--help"],
        vec!["ui", "-h"],
    ] {
        let result = sandbox.run(&args);
        assert_eq!(result.status.code(), Some(0), "{args:?}");
        assert!(result.stdout.starts_with(b"openwiz") || result.stdout.starts_with(b"  openwiz"));
        assert!(result.stderr.is_empty());
    }
    for args in [
        vec!["help", "--agent", "extra"],
        vec!["help", "--agent=true"],
        vec!["help", "--unknown"],
        vec!["ui"],
        vec!["fleet", "tick", "--unknown"],
    ] {
        let result = sandbox.run(&args);
        assert_eq!(result.status.code(), Some(2), "{args:?}");
        assert!(result.stdout.is_empty());
        assert!(result.stderr.starts_with(b"openwiz:"));
    }
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("state").exists());
    assert!(!sandbox.0.join("home").exists());
}

#[test]
fn cp1_zero_call_traps_detect_real_fixture_source_invocations() {
    let room = Sandbox::new();
    let output = room.run(&["ls", "--json"]);
    assert_eq!(output.status.code(), Some(1));
    let calls = fs::read_to_string(room.0.join("calls")).expect("room-cli trap must record calls");
    assert!(!calls.is_empty());
    assert!(calls.lines().all(|line| line == "unexpected source call"));
    let github = Sandbox::new();
    let output = github.run(&["fleets", "--json"]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "a failed fleet read is a partial envelope"
    );
    let calls = fs::read_to_string(github.0.join("calls")).expect("gh trap must record calls");
    assert!(!calls.is_empty());
    assert!(calls.lines().all(|line| line == "unexpected source call"));
}

#[test]
fn cp1_schema_refuses_broken_catalogues_and_pins_additive_result_shapes() {
    let contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap();
    let catalogue = discovered();
    for field in ["flags", "commands", "schema", "kind"] {
        let mut bad = catalogue.clone();
        bad.as_object_mut().unwrap().remove(field);
        assert!(
            !schema::validate(&contract, &bad).is_empty(),
            "missing {field}"
        );
    }
    let mut bad = catalogue.clone();
    bad["commands"][0]["effects"] = serde_json::json!(["arbitrary_process"]);
    assert!(!schema::validate(&contract, &bad).is_empty());
    let mut bad = catalogue.clone();
    bad["commands"][0]["exits"][0]["code"] = serde_json::json!(4);
    assert!(!schema::validate(&contract, &bad).is_empty());
    let documents = [
        serde_json::json!({"schema":"openwiz.cli-error.v1","command":"ls","exit_code":2,"error":{"kind":"usage","message":"unknown option"}}),
        serde_json::json!({"schema":"openwiz.cli-help.v1","text":"synthetic help"}),
        serde_json::json!({"schema":"openwiz.fleet-due.v1","candidates":[{"spec":123,"ticket":124},{"spec":125,"ticket":null}]}),
        serde_json::json!({"schema":"openwiz.terminal-capability.v1","available":false,"executable":"openwiz-terminal","transport":"loopback-http","actions":[],"reason":"not installed"}),
        serde_json::json!({"loop_id":"loop-synthetic","definition_revision":"1111111111111111111111111111111111111111","repository":"synthetic/repo","project":"project-synthetic","enabled":false,"actor":"synthetic-operator","at_ms":1000}),
    ];
    for document in documents {
        assert_eq!(schema::validate(&contract, &document), Vec::<String>::new());
        let mut extra = document.clone();
        extra["unexpected"] = serde_json::json!(true);
        assert!(!schema::validate(&contract, &extra).is_empty());
        for field in document.as_object().unwrap().keys() {
            let mut missing = document.clone();
            missing.as_object_mut().unwrap().remove(field);
            assert!(
                !schema::validate(&contract, &missing).is_empty(),
                "missing {field}"
            );
        }
    }
}

#[test]
fn engine_schema_enforces_identity_numeric_and_effect_bounds() {
    let contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap();
    let mut good = serde_json::json!({"schema":"openwiz.engine.v1","engine":{
        "location":"local","revision":1,"runtime":"0.0.99 1111111111111111111111111111111111111111",
        "operation_id":"0123456789abcdef0123456789abcdef","fingerprint":"2222222222222222222222222222222222222222222222222222222222222222",
        "cost":{"source":"cloudroom_usage","provenance":"measured","credits":0.25,"window_s":86400.5,
            "free_allowance":3000,"observed_at":1000,"allowance_at":1000}},
        "operation":{"operation_id":"0123456789abcdef0123456789abcdef","kind":"activate_engine","phase":"proposed",
            "fingerprint":"2222222222222222222222222222222222222222222222222222222222222222",
            "effects":["Select one engine."],"reason":"Activation remains closed."},
        "activation_allowed":false,"location_status":"not_activated","reason":"Activation needs authorization.",
        "cost":{"provenance":"unknown","credits":null,"window_s":null,"monthly_projection":null,
            "free_allowance":null,"reason":"No current observation."},"default_location":null,"service_config":null,
        "pc_activation":{"state":"absent","operation_id":null},"login":"unknown"});
    assert!(schema::lint(&contract).is_empty());
    assert!(schema::validate(&contract, &good).is_empty());
    good["service_config"] = serde_json::json!({"schema":"openwiz.service-config.v1",
        "repository":{"owner":"a-","name":"synthetic.repo"},"operator":"synthetic-owner",
        "project":"_synthetic","orchestrator_thread":"thr_syn_answer","service_issue":7,
        "github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":300},
        "health":{"every_s":60},"server":{"port":7370,"allowed_host":null,"probe_timeout_s":10}});
    assert!(schema::validate(&contract, &good).is_empty());
    // A held PC activation (#1106 revision 17) names T9's journal operation.
    let mut held = good.clone();
    held["location_status"] = serde_json::json!("held");
    held["pc_activation"] =
        serde_json::json!({"state":"held","operation_id":"0123456789abcdef0123456789abcdef"});
    assert!(schema::validate(&contract, &held).is_empty());
    for (pointer, value) in [
        ("/login", serde_json::json!("current")),
        ("/location_status", serde_json::json!("activated")),
        ("/pc_activation/state", serde_json::json!("verified")),
        ("/pc_activation/operation_id", serde_json::json!("0123")),
        ("/service_config/project", serde_json::json!("-synthetic")),
        (
            "/service_config/orchestrator_thread",
            serde_json::json!("-synthetic"),
        ),
        (
            "/service_config/repository/owner",
            serde_json::json!("-synthetic"),
        ),
        (
            "/engine/operation_id",
            serde_json::json!("g123456789abcdef0123456789abcdef"),
        ),
        ("/engine/fingerprint", serde_json::json!("2")),
        (
            "/engine/runtime",
            serde_json::json!("0X0X99 1111111111111111111111111111111111111111"),
        ),
        ("/engine/revision", serde_json::json!(9007199254740992u64)),
        ("/engine/cost/window_s", serde_json::json!(0)),
        ("/engine/cost/credits", serde_json::json!(-0.25)),
        (
            "/engine/cost/allowance_at",
            serde_json::json!(9007199254740992u64),
        ),
        ("/operation/effects", serde_json::json!([])),
        (
            "/operation/effects",
            serde_json::json!(["a", "b", "c", "d", "e", "f", "g", "h", "i"]),
        ),
        ("/activation_allowed", serde_json::json!(true)),
    ] {
        let mut bad = good.clone();
        *bad.pointer_mut(pointer).unwrap() = value;
        assert!(!schema::validate(&contract, &bad).is_empty(), "{pointer}");
    }
    for field in ["pc_activation", "login"] {
        let mut missing = good.clone();
        missing.as_object_mut().unwrap().remove(field);
        assert!(!schema::validate(&contract, &missing).is_empty(), "{field}");
    }
    let mut absent = good;
    absent["engine"].as_object_mut().unwrap().remove("cost");
    assert!(!schema::validate(&contract, &absent).is_empty());
    for pattern in ["unanchored", "^(a|b)$", "^[a-z]{4,2}$", "^[z-a]$"] {
        assert!(!schema::lint(&serde_json::json!({"type":"string","pattern":pattern})).is_empty());
    }
}

#[test]
fn cp1_advertised_flags_are_accepted_by_the_shipped_public_parsers() {
    let catalogue = discovered();
    for command in catalogue["commands"].as_array().unwrap() {
        let name = command["name"].as_str().unwrap();
        let base = match name {
            "help" => "help",
            "help.agent" => "help",
            "ls" => "ls",
            "show" => "show thread-synthetic",
            "send" => "send thread-synthetic hello",
            "send.preview" => "send thread-synthetic --preview",
            "send.check" => "send thread-synthetic --check --op-id op-synthetic",
            "new" => {
                "new --project-id project-synthetic --harness codex --model model-synthetic --effort high --yes hello"
            }
            "new.preview" => {
                "new --project-id project-synthetic --harness codex --model model-synthetic --effort high hello"
            }
            "new.status" => "new --status op-synthetic",
            "attachment.add" => "attachment add synthetic.txt",
            "attachment.ls" => "attachment ls",
            "attachment.rm" => "attachment rm attachment-synthetic",
            "fleet" => "fleet 123",
            "fleet.tick" => "fleet tick",
            "fleet.tick.preview" => "fleet tick --dry-run",
            "fleet.due" => "fleet due --github-only",
            "ui" => "ui",
            // These three parsers are private; their flags are checked through
            // real processes below, using only trap sources or absent config.
            "fleets" | "models" | "loop.off" | "loop.on" => continue,
            "engine.preview" | "engine.activate" | "engine.status" => continue,
            "github.token" => {
                for flag in command["flags"].as_array().unwrap() {
                    let mut args = vec!["token", "--repository", "synthetic-owner/work"];
                    args.extend(Some(flag.as_str().unwrap()).filter(|f| *f != "--repository"));
                    let args: Vec<String> = args.into_iter().map(str::to_owned).collect();
                    assert!(
                        openwiz_cli::github_token::parse(&args).is_ok(),
                        "advertised flag rejected: {args:?}"
                    );
                }
                continue;
            }
            other => panic!("unmapped form {other}"),
        };
        for flag in command["flags"].as_array().unwrap() {
            let flag = flag.as_str().unwrap();
            let mut args: Vec<String> = base.split_whitespace().map(str::to_owned).collect();
            if !args.iter().any(|a| a == flag) {
                args.push(flag.to_owned());
                let value = match flag {
                    "--limit" => Some("10"),
                    "--offset" => Some("2"),
                    "--op-id" => Some("op-synthetic"),
                    "--attach" => Some("synthetic.txt"),
                    "--attachment" => Some("attachment-synthetic"),
                    "--expect-plan" => Some("synthetic-reviewed-plan.json"),
                    "--port" => Some("7371"),
                    "--allowed-host" => Some("openwiz.example"),
                    "--text-sha256" => {
                        Some("1111111111111111111111111111111111111111111111111111111111111111")
                    }
                    _ => None,
                };
                if let Some(value) = value {
                    args.push(value.to_owned());
                }
            }
            let os: Vec<_> = args[1..].iter().map(std::ffi::OsString::from).collect();
            let accepted = match args[0].as_str() {
                "help" | "ls" | "show" => openwiz_cli::parse(&args).is_ok(),
                "send" => openwiz_cli::send::parse_send(&args[1..]).is_ok(),
                "new" => openwiz_cli::new_thread::parse_new(&args[1..]).is_ok(),
                "attachment" => openwiz_cli::attachment::parse_attachment(&os).is_ok(),
                "fleet" if matches!(args[1].as_str(), "tick" | "due") => {
                    openwiz_cli::fleet::tick::parse(&os).is_ok()
                }
                "fleet" => openwiz_cli::fleet::parse(&os).is_ok(),
                "ui" => cli_ui::parse_ui(&os).is_ok(),
                _ => unreachable!(),
            };
            assert!(accepted, "advertised flag rejected: {args:?}");
        }
    }
    for (args, code) in [
        (vec!["fleets", "--json"], 0),
        (vec!["models", "--json"], 13),
        (vec!["fleet", "tick", "--dry-run", "--json"], 1),
        (vec!["fleet", "due", "--github-only"], 1),
        (vec!["loop", "off", "loop-synthetic", "--json"], 1),
        (vec!["loop", "on", "loop-synthetic", "--json"], 1),
        (vec!["loop", "--json", "off", "loop-synthetic"], 2),
    ] {
        let sandbox = Sandbox::new();
        let output = sandbox.run(&args);
        assert_eq!(
            output.status.code(),
            Some(code),
            "{args:?}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(!sandbox.0.join("state").exists());
    }
}

#[test]
fn cp1_fleet_forms_separate_execution_from_read_only_candidates_and_plans() {
    let catalogue = discovered();
    let commands = catalogue["commands"].as_array().unwrap();
    let form = |name| commands.iter().find(|c| c["name"] == name).unwrap();
    assert_eq!(
        form("fleet.tick")["effects"],
        serde_json::json!(["source_read", "state_read", "state_write", "fleet_action"])
    );
    assert_eq!(
        form("fleet.tick.preview")["effects"],
        serde_json::json!(["source_read", "state_read"])
    );
    assert_eq!(
        form("fleet.tick.preview")["required_flags"],
        serde_json::json!(["--dry-run"])
    );
    assert_eq!(
        form("fleet.due")["effects"],
        serde_json::json!(["source_read"])
    );
    assert_eq!(form("fleet.due")["sources"], serde_json::json!(["gh"]));
    assert_eq!(
        form("fleet.due")["required_flags"],
        serde_json::json!(["--github-only"])
    );
    assert_eq!(form("fleet.due")["json"], true);
    // Inspect the real public parser without executing any fleet action.
    for (args, due, dry_run, json) in [
        (vec!["tick", "--json"], false, false, true),
        (vec!["tick", "--dry-run", "--json"], false, true, true),
        (vec!["due", "--github-only"], true, false, false),
        (vec!["due", "--github-only", "--json"], true, false, true),
    ] {
        let os: Vec<_> = args.into_iter().map(std::ffi::OsString::from).collect();
        let parsed = openwiz_cli::fleet::tick::parse(&os).unwrap();
        assert_eq!(
            (parsed.due, parsed.dry_run, parsed.json),
            (due, dry_run, json)
        );
    }
    for args in [
        vec!["due"],
        vec!["tick", "--json", "--json"],
        vec!["tick", "--dry-run=true"],
        vec!["tick", "--"],
    ] {
        let os: Vec<_> = args.into_iter().map(std::ffi::OsString::from).collect();
        assert!(openwiz_cli::fleet::tick::parse(&os).is_err());
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn cp1_catalogue_is_discoverable_without_sources_or_state() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&["help", "--agent"]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "help --agent must execute: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let catalogue: Value = serde_json::from_slice(&output.stdout).expect("one catalogue document");
    // Compact means a single JSON line, independent of terminal width.
    assert_eq!(output.stdout.iter().filter(|&&b| b == b'\n').count(), 1);
    let contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(schema::lint(&contract), Vec::<String>::new());
    assert_eq!(
        schema::validate(&contract, &catalogue),
        Vec::<String>::new()
    );
    assert_eq!(catalogue["schema"], "openwiz.cli.v1");
    assert_eq!(catalogue["kind"], "catalogue");
    let commands = catalogue["commands"].as_array().unwrap();
    let actual: Vec<_> = commands
        .iter()
        .map(|c| c["name"].as_str().unwrap())
        .collect();
    assert_eq!(
        actual,
        [
            "help",
            "help.agent",
            "ls",
            "show",
            "send",
            "send.preview",
            "send.check",
            "new",
            "new.preview",
            "new.status",
            "models",
            "attachment.add",
            "attachment.ls",
            "attachment.rm",
            "fleets",
            "fleet",
            "fleet.tick",
            "fleet.tick.preview",
            "fleet.due",
            "loop.off",
            "loop.on",
            "ui",
            "engine.preview",
            "engine.activate",
            "engine.status",
            "github.token"
        ]
    );
    assert!(
        !sandbox.0.join("calls").exists(),
        "exactly zero source calls"
    );
    assert!(
        !sandbox.0.join("state").exists(),
        "no state directory created"
    );
    assert!(
        !sandbox.0.join("home").exists(),
        "no fallback state created"
    );

    // Discovery must also leave an existing store byte-for-byte unchanged.
    dirs::private_dir(sandbox.0.join("state")).unwrap();
    fs::write(sandbox.0.join("state/sentinel"), b"synthetic state\n").unwrap();
    let repeated = sandbox.run(&["help", "--agent"]);
    assert_eq!(repeated.status.code(), Some(0));
    assert_eq!(repeated.stdout, output.stdout);
    assert!(repeated.stderr.is_empty());
    assert_eq!(
        fs::read(sandbox.0.join("state/sentinel")).unwrap(),
        b"synthetic state\n"
    );
    assert_eq!(fs::read_dir(sandbox.0.join("state")).unwrap().count(), 1);
    assert!(!sandbox.0.join("calls").exists());
    assert!(!sandbox.0.join("home").exists());
}

// Reuse the existing Node recording fixture, with this target's shared dispatcher.
mod support {
    pub fn openwiz_release() -> std::path::PathBuf {
        super::fixture_cli().to_owned()
    }
}
