use super::{ROOT, Sandbox, place, schema};
use serde_json::{Value, json};
use std::{fs, path::Path, process::Output};

const FLEET: &str = "docs/agents/fleet.md";
const SNAPSHOT: &str = "docs/agents/models-offered.json";

fn project() -> Sandbox {
    let sandbox = Sandbox::new();
    fs::remove_file(sandbox.0.join("bin/room-cli")).unwrap();
    fs::create_dir_all(sandbox.0.join("docs/agents")).unwrap();
    fs::copy(
        Path::new(ROOT).join("contracts/fixtures/models/one-table/fleet.md"),
        sandbox.0.join(FLEET),
    )
    .unwrap();
    sandbox
}

fn install(sandbox: &Sandbox, program: &str) {
    place::place_script(
        &sandbox.0.join("bin").join(program),
        "#!/bin/sh\nprintf 'unexpected harness execution\\n' >> \"$CP1_CALLS\"\nexit 99\n",
    );
}

fn save_host(sandbox: &Sandbox, fixture: &str) {
    let hosts: Value = serde_json::from_slice(
        &fs::read(
            Path::new(ROOT).join("tools/install/tests/setup-onboard-contract/fixtures/hosts.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let project = &hosts["prepared_projects"][fixture]["document"];
    assert!(project.is_object(), "{fixture}");
    let dir = sandbox.0.join("state/setup");
    fs::create_dir_all(&dir).unwrap();
    fs::write(
        dir.join("state.json"),
        json!({
            "schema": "openwiz.setup-state.v1",
            "revision": 1,
            "checks": {"started": 0, "committed": 0},
            "project": project,
            "app": null,
            "observations": {},
            "operations": []
        })
        .to_string(),
    )
    .unwrap();
}

fn report(output: Output, code: i32, contract: &str, definition: &str) -> Value {
    assert_eq!(
        output.status.code(),
        Some(code),
        "stdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    validate(&value, contract, definition);
    value
}

fn validate(value: &Value, contract: &str, definition: &str) {
    let mut contract: Value = serde_json::from_slice(
        &fs::read(Path::new(ROOT).join("contracts").join(contract)).unwrap(),
    )
    .unwrap();
    contract.as_object_mut().unwrap().remove("oneOf");
    contract["$ref"] = json!(format!("#/$defs/{definition}"));
    assert_eq!(schema::validate(&contract, value), Vec::<String>::new());
}

#[test]
fn local_inventory_uses_the_host_and_only_installed_programs() {
    let sandbox = project();
    install(&sandbox, "claude");
    install(&sandbox, "codex");
    for host in ["local", "boat", "synthetic-driver"] {
        let options = report(
            sandbox.run(&["models", "--json", "--host", host]),
            0,
            "new-thread.v1.schema.json",
            "options",
        );
        assert_eq!(options["source"], "local");
        assert_eq!(options["state"], json!({"kind": "offered"}));
        assert_eq!(
            options["harnesses"],
            json!([
                {"harness": "claude-code", "provider": "claude-code",
                 "models": [{"model": "claude-opus-5-5", "efforts": ["medium"]}],
                 "attachments": null, "steer": null},
                {"harness": "codex", "provider": "codex",
                 "models": [{"model": "gpt-6.2-sol", "efforts": ["medium"]}],
                 "attachments": null, "steer": null}
            ])
        );
        assert_eq!(options["unavailable"], json!([]));
    }
    save_host(&sandbox, "local-without-cloudroom-ids");
    fs::remove_file(sandbox.0.join("bin/claude")).unwrap();
    fs::write(sandbox.0.join("bin/claude"), "not executable").unwrap();
    let options = report(
        sandbox.run(&["models", "--json"]),
        0,
        "new-thread.v1.schema.json",
        "options",
    );
    assert_eq!(options["source"], "local");
    assert_eq!(options["harnesses"].as_array().unwrap().len(), 1);
    assert_eq!(options["harnesses"][0]["provider"], "codex");

    fs::remove_file(sandbox.0.join("bin/codex")).unwrap();
    let options = report(
        sandbox.run(&["models", "--json"]),
        13,
        "new-thread.v1.schema.json",
        "options",
    );
    assert_eq!(options["source"], "local");
    assert_eq!(options["state"]["reason"], "harnesses_not_reported");
    assert_eq!(options["harnesses"], json!([]));
    assert!(!sandbox.0.join("calls").exists());

    let cloud = report(
        sandbox.run(&["models", "--json", "--host", "cloud"]),
        13,
        "new-thread.v1.schema.json",
        "options",
    );
    assert!(cloud.get("source").is_none());
    assert_eq!(cloud["state"]["reason"], "read_failed");
}

#[test]
fn local_set_and_show_use_project_roles_without_cloudroom() {
    let sandbox = project();
    install(&sandbox, "codex");
    save_host(&sandbox, "local-without-cloudroom-ids");
    let changed = report(
        sandbox.run(&[
            "models",
            "set",
            "builder",
            "codex",
            "gpt-6.2-sol",
            "medium",
            "--json",
        ]),
        0,
        "models.v1.schema.json",
        "set_report",
    );
    assert_eq!(changed["outcome"], "changed");
    assert!(changed.get("listed").is_none());
    assert!(sandbox.0.join(SNAPSHOT).exists());

    let shown = report(
        sandbox.run(&["models", "show", "--host", "boat", "--json"]),
        0,
        "models.v1.schema.json",
        "show_report",
    );
    assert_eq!(shown["roles"]["builder"]["choice"]["model"], "gpt-6.2-sol");
    assert!(!sandbox.0.join("calls").exists());
}

#[test]
fn local_set_reports_unlisted_choices_and_refuses_unsettable_ones() {
    let sandbox = project();
    install(&sandbox, "codex");
    save_host(&sandbox, "cloud-nine-keys");
    let set = |provider, model, code| {
        report(
            sandbox.run(&[
                "models", "set", "--host", "local", "reviewer", provider, model, "medium", "--json",
            ]),
            code,
            "models.v1.schema.json",
            "set_report",
        )
    };
    for outcome in ["changed", "unchanged"] {
        let accepted = set("codex", "synthetic-vendor/demo", 0);
        assert_eq!(accepted["outcome"], outcome);
        assert_eq!(accepted["listed"], false);
        assert_eq!(
            accepted["after"]["choice"]["model"],
            "synthetic-vendor/demo"
        );
    }

    let fleet = fs::read(sandbox.0.join(FLEET)).unwrap();
    let snapshot = fs::read(sandbox.0.join(SNAPSHOT)).unwrap();
    for (provider, model, reason) in [
        ("claude-code", "claude-opus-5-5", "not_offered"),
        ("codex", "synthetic-vendor/demo:latest", "not_writable"),
    ] {
        let refused = set(provider, model, 5);
        assert_eq!(refused["refusal"]["reason"], reason);
        assert!(refused.get("listed").is_none());
        assert_eq!(fs::read(sandbox.0.join(FLEET)).unwrap(), fleet);
        assert_eq!(fs::read(sandbox.0.join(SNAPSHOT)).unwrap(), snapshot);
    }
    assert!(!sandbox.0.join("calls").exists());
}

#[test]
fn local_inventory_and_snapshot_describe_installed_harnesses() {
    let sandbox = project();
    install(&sandbox, "codex");
    let local_label = "Installed local harnesses with OpenWiz's current choices";
    let options = report(
        sandbox.run(&["models", "--host", "local", "--json"]),
        0,
        "new-thread.v1.schema.json",
        "options",
    );
    assert_eq!(options["label"], local_label);

    report(
        sandbox.run(&[
            "models",
            "set",
            "reviewer",
            "codex",
            "gpt-6.2-sol",
            "medium",
            "--host",
            "local",
            "--json",
        ]),
        0,
        "models.v1.schema.json",
        "set_report",
    );
    let snapshot: Value =
        serde_json::from_slice(&fs::read(sandbox.0.join(SNAPSHOT)).unwrap()).unwrap();
    assert_eq!(snapshot["label"], local_label);
    validate(&snapshot, "models.v1.schema.json", "snapshot");
    assert!(!sandbox.0.join("calls").exists());
}

#[test]
fn list_save_reads_the_saved_local_host_without_cloudroom() {
    let sandbox = project();
    install(&sandbox, "codex");
    save_host(&sandbox, "local-without-cloudroom-ids");
    let listed = report(
        sandbox.run(&["models", "list", "--save", "--json"]),
        0,
        "models.v1.schema.json",
        "list_report",
    );
    assert_eq!(listed["saved"], SNAPSHOT);
    assert_eq!(
        listed["offered"]["label"],
        "Installed local harnesses with OpenWiz's current choices"
    );
    assert_eq!(listed["offered"]["harnesses"][0]["provider"], "codex");
    let snapshot: Value =
        serde_json::from_slice(&fs::read(sandbox.0.join(SNAPSHOT)).unwrap()).unwrap();
    assert_eq!(snapshot, listed["offered"]);
    assert!(!sandbox.0.join("calls").exists());
}
