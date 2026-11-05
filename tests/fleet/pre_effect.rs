//! #1892: a reviewed preview must constrain the whole tick before any effect.
//! The existing B5 proofs never supplied an execution restriction.
use super::fake::World;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Output;

#[path = "pre_effect_input.rs"]
mod input;

fn preview(w: &World) -> Value {
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    serde_json::from_slice(&o.stdout).unwrap()
}

fn restricted(w: &World, plan: &Value) -> Output {
    let file = w.dir.join("reviewed.json");
    fs::write(&file, serde_json::to_vec(plan).unwrap()).unwrap();
    w.run(&[
        "fleet",
        "tick",
        "--json",
        "--expect-plan",
        file.to_str().unwrap(),
    ])
}

// Include directories, including empty lock/store directories, as well as bytes.
fn state(root: &Path) -> BTreeMap<PathBuf, Option<Vec<u8>>> {
    fn visit(root: &Path, p: &Path, entries: &mut BTreeMap<PathBuf, Option<Vec<u8>>>) {
        if !p.exists() {
            return;
        }
        let value = if p.is_dir() {
            None
        } else {
            Some(fs::read(p).unwrap())
        };
        entries.insert(p.strip_prefix(root).unwrap().into(), value);
        if p.is_dir() {
            for entry in fs::read_dir(p).unwrap() {
                visit(root, &entry.unwrap().path(), entries);
            }
        }
    }
    let mut entries = BTreeMap::new();
    visit(root, root, &mut entries);
    entries
}

fn refused_unchanged(w: &World, run: impl FnOnce() -> Output) {
    let writes = w.writes();
    let before = state(&w.dir.join("state"));
    let external = w.load();
    let o = run();
    assert_eq!(w.writes(), writes, "no partial external effect");
    assert_eq!(
        state(&w.dir.join("state")),
        before,
        "no local write or lock"
    );
    // A usage error for an unimplemented flag is not the claimed refusal.
    assert_eq!(
        o.status.code(),
        Some(1),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert!(String::from_utf8_lossy(&o.stderr).contains("reviewed plan"));
    if !o.stdout.is_empty() {
        // The existing syntactic --json contract wraps handled failures.
        let error: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(error["schema"], "openwiz.cli-error.v1");
        assert_eq!(error["error"]["kind"], "read_failed");
    }
    let after = w.load();
    for key in [
        "issues",
        "comments",
        "threads",
        "spawn_count",
        "merge_bodies",
    ] {
        assert_eq!(after[key], external[key], "external state: {key}");
    }
}

fn two_actions(name: &str) -> World {
    let w = World::new(name);
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    w.tick();
    let p = preview(&w);
    assert_eq!(p["actions"].as_array().unwrap().len(), 2, "{p}");
    assert_eq!(p["actions"][0]["rule"], "finished");
    assert_eq!(p["actions"][1]["rule"], "frontier");
    w
}

#[test]
fn exact_reviewed_plan_proceeds_in_order() {
    let w = two_actions("restricted-exact");
    let mut reviewed = preview(&w);
    reviewed["planned_at"] = 1.into(); // A saved preview is from an earlier time.
    let before = w.writes().len();
    let o = restricted(&w, &reviewed);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let actual: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(actual["mode"], "run");
    assert_eq!(actual["actions"].as_array().unwrap().len(), 2);
    for (action, expected) in actual["actions"]
        .as_array()
        .unwrap()
        .iter()
        .zip(reviewed["actions"].as_array().unwrap())
    {
        assert_eq!(action["outcome"], json!({"state":"done"}));
        let mut action = action.clone();
        action["outcome"] = json!({"state":"planned"});
        assert_eq!(&action, expected);
    }
    let writes = w.writes();
    assert_eq!(writes.len() - before, 5);
    assert_eq!(writes[before].0, "room-cli");
    assert_eq!(writes[before].1[1], "archive");
    assert_eq!(writes[before + 1].1[1], "archive");
    assert_eq!(writes[before + 3].1[1], "spawn");
    assert_eq!(w.load()["spawn_count"], 3);
    assert_eq!(w.load()["threads"]["thr_syn_b5_1"]["archived"], true);

    let empty = World::new("restricted-exact-empty");
    empty.change(|s| {
        s["issues"] = json!([]);
        s["comments"] = json!({});
    });
    let reviewed = preview(&empty);
    assert_eq!(reviewed["actions"], json!([]));
    let o = restricted(&empty, &reviewed);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(doc["actions"], json!([]));
    assert!(empty.writes().is_empty());
    assert!(!empty.dir.join("state").exists());
}

#[test]
fn facts_changing_after_preview_refuse_the_whole_tick() {
    let w = two_actions("restricted-current-drift");
    let reviewed = preview(&w);
    // A new PR replaces the second action after review. The earlier archive
    // remains due, but must not run before the new action is found unreviewed.
    w.pr(11);
    assert_eq!(preview(&w)["actions"][0], reviewed["actions"][0]);
    assert_ne!(preview(&w)["actions"][1], reviewed["actions"][1]);
    refused_unchanged(&w, || restricted(&w, &reviewed));
}

#[test]
fn changed_reviewed_plan_refuses_before_even_its_matching_first_action() {
    crate::at_once::at_once(
        &[
            "extra-current-action",
            "changed-argument",
            "reordered",
            "empty",
            "duplicate",
        ],
        2,
        |&case| {
            let w = two_actions(&format!("restricted-{case}"));
            let mut reviewed = preview(&w);
            let actions = reviewed["actions"].as_array_mut().unwrap();
            match case {
                "extra-current-action" => {
                    actions.pop();
                }
                "changed-argument" => {
                    actions[1]["facts"]["settings"]["model"] = "synthetic-other".into()
                }
                "reordered" => actions.reverse(),
                "empty" => actions.clear(),
                "duplicate" => actions.push(actions[1].clone()),
                _ => unreachable!(),
            }
            refused_unchanged(&w, || restricted(&w, &reviewed));
        },
    );
}

#[test]
fn pending_recovery_refuses_without_settling_or_commenting() {
    let w = World::new("restricted-recovery");
    w.tick();
    let file = fs::read_dir(w.dir.join("state/starts"))
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "json"))
        .unwrap();
    let mut record: Value = serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
    record["attempts"][0]["outcome"] = json!({"kind":"pending"});
    fs::write(&file, serde_json::to_vec(&record).unwrap()).unwrap();
    w.change(|s| s["comments"]["10"] = json!([]));
    let reviewed = preview(&w);
    refused_unchanged(&w, || restricted(&w, &reviewed));
    // Without the restriction the existing recovery path is unchanged.
    w.tick();
    assert_eq!(w.load()["spawn_count"], 1);
    assert_eq!(
        w.load()["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"] == "launch-fleet: started")
            .count(),
        1
    );
}

#[test]
fn malformed_or_changed_envelopes_fail_closed() {
    let w = World::new("restricted-input");
    let good = preview(&w);
    let mut bad = Vec::new();
    for key in [
        "schema",
        "mode",
        "planned_at",
        "default_branch",
        "rules",
        "actions",
    ] {
        let mut p = good.clone();
        p.as_object_mut().unwrap().remove(key);
        bad.push(p);
    }
    for (key, value) in [
        ("schema", json!("unknown")),
        ("mode", json!("run")),
        ("planned_at", json!("1")),
        ("default_branch", json!("other")),
        ("rules", json!({})),
        ("actions", json!({})),
        ("extra", json!(true)),
    ] {
        let mut p = good.clone();
        p[key] = value;
        bad.push(p);
    }
    let mut p = good.clone();
    p["actions"][0]["outcome"] = json!({"state":"done"});
    bad.extend([p, Value::Null, json!([])]);
    for p in bad {
        refused_unchanged(&w, || restricted(&w, &p));
    }
    let file = w.dir.join("bad.json");
    let encoded = serde_json::to_string(&good).unwrap();
    let duplicate = encoded.replacen(
        "\"schema\":",
        "\"schema\":\"openwiz.fleet-tick.v1\",\"schema\":",
        1,
    );
    let nested_duplicate = encoded.replacen(
        "\"kind\":\"start_builder\"",
        "\"kind\":\"start_builder\",\"kind\":\"start_builder\"",
        1,
    );
    assert_ne!(nested_duplicate, encoded);
    for raw in ["{", duplicate.as_str(), nested_duplicate.as_str()] {
        fs::write(&file, raw).unwrap();
        refused_unchanged(&w, || {
            w.run(&["fleet", "tick", "--expect-plan", file.to_str().unwrap()])
        });
    }
    fs::remove_file(&file).unwrap();
    refused_unchanged(&w, || {
        w.run(&["fleet", "tick", "--expect-plan", file.to_str().unwrap()])
    });
}
