//! 0.0.12 T3 (#1098): `ui`'s noninteractive forms through the shared fixture
//! dispatcher: the capability document, help, usage errors and the refusal
//! without a terminal. None reads a source or state, or opens anything.
//! (Interactive launch is proved in a pseudo-terminal: `tests/terminal/pty.rs`.)
use super::{ROOT, Sandbox, schema};
use serde_json::Value;
use std::{fs, path::Path};

fn contract() -> Value {
    serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("contracts/cli.v1.schema.json")).unwrap(),
    )
    .unwrap()
}

fn untouched(sandbox: &Sandbox) {
    assert!(!sandbox.0.join("calls").exists(), "no source call");
    assert!(!sandbox.0.join("state").exists(), "no state");
    assert!(!sandbox.0.join("home").exists(), "no fallback state");
}

#[test]
fn ui_json_is_the_capability_document_and_opens_nothing() {
    let sandbox = Sandbox::new();
    for args in [
        vec!["ui", "--json"],
        vec!["ui", "--port", "7371", "--json"],
        vec!["ui", "--json", "--allowed-host=openwiz.example"],
    ] {
        let out = sandbox.run(&args);
        assert_eq!(out.status.code(), Some(0), "{args:?}");
        assert!(out.stderr.is_empty());
        assert_eq!(out.stdout.iter().filter(|&&b| b == b'\n').count(), 1);
        let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(schema::validate(&contract(), &doc), Vec::<String>::new());
        // The fixture CLI has no installed sibling beside it.
        assert_eq!(
            doc,
            serde_json::json!({"schema":"openwiz.terminal-capability.v1","available":false,"executable":"openwiz-terminal","transport":"loopback-http","actions":[],"reason":"not installed beside openwiz"})
        );
    }
    untouched(&sandbox);
}

#[test]
fn ui_help_errors_and_non_terminal_use_never_wait_or_launch() {
    let sandbox = Sandbox::new();
    let help = sandbox.run(&["ui", "--help", "--json"]);
    assert_eq!(help.status.code(), Some(0));
    let doc: Value = serde_json::from_slice(&help.stdout).unwrap();
    assert_eq!(doc["schema"], "openwiz.cli-help.v1");
    assert!(
        doc["text"]
            .as_str()
            .unwrap()
            .contains("openwiz ui [--port N]")
    );
    // Audit A1: a value position is never JSON selection, even for help.
    let valued = sandbox.run(&["ui", "--port", "--json", "--help"]);
    assert_eq!(valued.status.code(), Some(0));
    assert!(
        valued
            .stdout
            .starts_with(b"openwiz: the visual terminal app."),
        "text help"
    );
    let text = sandbox.run(&["ui", "-h"]);
    assert_eq!(text.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&text.stdout).contains("--allowed-host NAME"));
    // Piped: a usage error at once, never a wait for a terminal.
    for args in [vec!["ui"], vec!["ui", "--port", "7371"]] {
        let out = sandbox.run(&args);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        assert!(out.stdout.is_empty());
        assert!(
            String::from_utf8_lossy(&out.stderr).starts_with(
                "openwiz: ui needs a terminal on stdin and stdout; nothing was opened"
            )
        );
    }
    // Usage errors, with syntactic JSON, are one cli-error document.
    for args in [
        vec!["ui", "--bogus", "--json"],
        vec!["ui", "--port", "0", "--json"],
        vec!["ui", "--port", "1", "--port", "2", "--json"],
        vec!["ui", "--allowed-host", "127.0.0.1", "--json"],
        vec!["ui", "--allowed-host", "https://openwiz.example", "--json"],
        vec!["ui", "--json=yes", "--json"],
    ] {
        let out = sandbox.run(&args);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(schema::validate(&contract(), &doc), Vec::<String>::new());
        assert_eq!(doc["command"], "ui", "{args:?}");
        assert_eq!(doc["error"]["kind"], "usage");
    }
    // A value is never an option: `--port --json` is a bad port, in text.
    let out = sandbox.run(&["ui", "--port", "--json"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(out.stdout.is_empty());
    assert!(String::from_utf8_lossy(&out.stderr).contains("--port must be one decimal number"));
    untouched(&sandbox);
}

#[test]
fn the_catalogue_registers_ui_with_its_flags_and_capability_schema() {
    let catalogue = super::discovered();
    let ui = catalogue["commands"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "ui")
        .unwrap();
    assert_eq!(ui["argv"], serde_json::json!(["ui"]));
    assert_eq!(
        ui["aliases"],
        serde_json::json!([[]]),
        "interactive no-argument form"
    );
    assert_eq!(
        ui["sources"],
        serde_json::json!([]),
        "never room-cli or gh itself"
    );
    assert_eq!(ui["stdin"], "never");
    assert_eq!(ui["json"], true);
    let codes: Vec<_> = ui["exits"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["code"].as_i64().unwrap())
        .collect();
    assert_eq!(codes, [0, 1, 2]);
    assert_eq!(
        ui["results"][0]["reference"],
        "contracts/cli.v1.schema.json#/$defs/terminal_capability"
    );
    let flag = |name: &str| {
        catalogue["flags"]
            .as_array()
            .unwrap()
            .iter()
            .find(|f| f["name"] == name)
            .unwrap()
            .clone()
    };
    assert_eq!(flag("--port")["default"], "7370");
    assert_eq!(flag("--port")["arity"], "value");
    assert!(flag("--allowed-host")["default"].is_null());
    let notes = catalogue["notes"].to_string();
    assert!(!notes.contains("ui is not available"));
}

/// The CLI's list is the terminal crate's own registry, compiled from the
/// same files: never a second list.
#[test]
fn ui_capability_actions_come_from_the_terminal_registry() {
    let terminal: Vec<&str> = openwiz_terminal::actions::registry()
        .into_iter()
        .filter(|(_, action)| action.is_some())
        .map(|(id, _)| id.capability())
        .collect();
    assert_eq!(super::cli_ui::implemented_actions(), terminal);
    let source = fs::read_to_string(Path::new(ROOT).join("crates/cli/src/ui.rs")).unwrap();
    assert!(source.contains("#[path = \"../../terminal/src/actions/mod.rs\"]"));
    assert!(!source.contains("IMPLEMENTED_ACTIONS"), "no CLI-side list");

    // Registered entries appear, in registry order; unregistered stubs don't.
    use super::cli_ui::actions::{Action, ActionContext, ActionId, ActionInput, ActionResult};
    struct Probe(ActionId);
    impl Action for Probe {
        fn id(&self) -> ActionId {
            self.0
        }
        fn update(&mut self, _: ActionInput, _: &ActionContext) -> ActionResult {
            ActionResult {
                view: Default::default(),
                request: None,
            }
        }
    }
    let registry = || -> Vec<(ActionId, Option<Box<dyn Action>>)> {
        vec![
            (ActionId::Answer, None),
            (ActionId::Send, Some(Box::new(Probe(ActionId::Send)))),
            (
                ActionId::NewThread,
                Some(Box::new(Probe(ActionId::NewThread))),
            ),
        ]
    };
    assert_eq!(
        super::cli_ui::implemented(registry()),
        ["send", "new_thread"]
    );
    // Not installed: nothing is advertised, whatever is registered.
    let doc = super::cli_ui::capability_with(None, super::cli_ui::implemented(registry()));
    assert_eq!(doc["actions"], serde_json::json!([]));
}

fn copy_tree(from: &Path, to: &Path) {
    super::dirs::private_dir_all(to).unwrap();
    for entry in fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), &target).unwrap();
        }
    }
}

/// End to end, as T4-T6 will do it: a copy of the CLI and terminal sources
/// in which only `actions/send.rs` registers an action (and `answer.rs` is
/// an unregistered stub) builds an `openwiz` whose `ui --json` lists `send`
/// and not `answer`. The sibling beside it is never run.
#[test]
fn an_action_registered_in_its_module_appears_in_ui_json() {
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;
    let root = Path::new(ROOT);
    let work = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join(format!("cp-ui-registry-{}", std::process::id()));
    let _ = fs::remove_dir_all(&work);
    super::dirs::private_dir_all(&work).unwrap();
    for dir in [
        "crates/core",
        "crates/adapters/cloudroom",
        "crates/adapters/github",
        "crates/store",
        "crates/cli",
        "crates/terminal/src",
        "contracts",
        "tools/install/platform",
    ] {
        copy_tree(&root.join(dir), &work.join(dir));
    }
    super::dirs::private_dir_all(work.join("tests/service")).unwrap();
    fs::copy(
        root.join("tests/service/t7_transport.rs"),
        work.join("tests/service/t7_transport.rs"),
    )
    .unwrap();
    fs::copy(root.join("Cargo.lock"), work.join("Cargo.lock")).unwrap();
    let manifest = fs::read_to_string(root.join("Cargo.toml")).unwrap();
    let (head, rest) = manifest.split_once("members = [").unwrap();
    let (_, tail) = rest.split_once(']').unwrap();
    fs::write(
        work.join("Cargo.toml"),
        format!(
            "{head}members = [\"crates/core\", \"crates/adapters/cloudroom\", \"crates/adapters/github\", \"crates/store\", \"crates/cli\"]{tail}"
        ),
    )
    .unwrap();
    let actions = work.join("crates/terminal/src/actions");
    fs::write(
        actions.join("send.rs"),
        "//! Fixture registration.\n\
         struct Probe;\n\
         impl super::Action for Probe {\n\
             fn id(&self) -> super::ActionId { super::ActionId::Send }\n\
             fn update(&mut self, _: super::ActionInput, _: &super::ActionContext) -> super::ActionResult {\n\
                 super::ActionResult { view: Default::default(), request: None }\n\
             }\n\
         }\n\
         pub fn register() -> Option<Box<dyn super::Action>> { Some(Box::new(Probe)) }\n",
    )
    .unwrap();
    fs::write(
        actions.join("answer.rs"),
        "pub fn register() -> Option<Box<dyn super::Action>> { None }\n",
    )
    .unwrap();
    let target = Path::new(env!("CARGO_TARGET_TMPDIR")).join("cp-ui-registry-target");
    let build = Command::new(env!("CARGO"))
        .args([
            "build",
            "--offline",
            "-p",
            "openwiz-cli",
            "--bin",
            "openwiz",
            "--target-dir",
        ])
        .arg(&target)
        .current_dir(&work)
        .output()
        .unwrap();
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let install = work.join("install");
    super::dirs::private_dir(&install).unwrap();
    fs::copy(target.join("debug/openwiz"), install.join("openwiz")).unwrap();
    let sibling = install.join("openwiz-terminal");
    fs::write(&sibling, "#!/bin/sh\ntouch \"$(dirname \"$0\")/ran\"\n").unwrap();
    fs::set_permissions(&sibling, fs::Permissions::from_mode(0o700)).unwrap();
    let out = Command::new(install.join("openwiz"))
        .args(["ui", "--json"])
        .env_clear()
        .env("HOME", &install)
        .output()
        .unwrap();
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(doc["available"], true);
    let listed = doc["actions"].as_array().unwrap();
    assert!(listed.contains(&serde_json::json!("send")), "{doc}");
    assert!(!listed.contains(&serde_json::json!("answer")), "{doc}");
    assert_eq!(schema::validate(&contract(), &doc), Vec::<String>::new());
    assert!(
        !install.join("ran").exists(),
        "ui --json never runs the sibling"
    );
    let _ = fs::remove_dir_all(&work);
}
