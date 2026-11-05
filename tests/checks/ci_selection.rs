//! The CI selection record, v1 (#1405, X0 of spec #1256): every valid
//! fixture in `ci/selection/valid/` matches
//! `contracts/ci-selection.v1.schema.json` and keeps the contract's rules
//! beyond the schema (`contracts/ci-selection.v1.md`, "Rules beyond the
//! schema"), and every invalid fixture in `ci/selection/invalid/` is refused,
//! for the reason its name gives. Fixtures prove the record's shape, never a
//! live run.

use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
const SCHEMA: &str = "contracts/ci-selection.v1.schema.json";
const CONTRACT: &str = "contracts/ci-selection.v1.md";
const FIXTURES: &str = "ci/selection";

/// Each invalid fixture, and a part of the refusal it must get: a schema
/// error's path, or a rule's words.
const INVALID: &[(&str, &str)] = &[
    ("action-missing", "rule 3: run.action"),
    ("action-on-push", "rule 3: run.action"),
    ("always-skipped", "$.lanes.always"),
    ("base-all-zeros", "rule 3: run.base is all zeros"),
    ("base-branch-other", "rule 3: run.base_branch feature-x"),
    ("diff-read-without-paths", "$.diff.paths: 0 items"),
    ("duplicate-key", "rule 1: a repeated key"),
    ("empty-diff-reason-on-read-diff", "rule 5: empty_diff"),
    ("empty-diff-unnamed", "rule 5: empty_diff"),
    ("extra-field", "$: unexpected field notes"),
    ("failed-diff-unnamed", "rule 5: failed_diff"),
    ("full-lane-skipped", "$.lanes.web"),
    ("full-reason-unknown", "$.selection.reasons[1]: matches 0"),
    ("full-test-skipped", "$.lanes.rust.skipped: expected []"),
    ("full-web-export-skipped", "$.builds.web_export"),
    ("full-without-reason", "$.selection.reasons: 0 items"),
    ("head-not-a-sha", "$.run.head: does not match"),
    ("lane-extra", "$.lanes: unexpected field docs"),
    ("lane-missing", "$.lanes: missing required field web"),
    ("lane-unknown-decision", "$.lanes.web: matches 0"),
    ("nightly-on-pull-request", "rule 4: nightly"),
    ("not-read-without-event", "rule 5: a not_read diff"),
    ("pull-request-number-missing", "rule 3: run.pull_request"),
    ("pull-request-number-on-push", "rule 3: run.pull_request"),
    ("pull-request-without-base", "rule 3: run.base"),
    ("push-main-unnamed", "rule 4: push_main"),
    ("push-to-release", "rule 4: a push"),
    (
        "ready-for-review-on-synchronize",
        "rule 4: ready_for_review",
    ),
    ("ready-for-review-unnamed", "rule 4: ready_for_review"),
    ("reason-twice", "rule 9: unknown_path"),
    ("release-branch-unnamed", "rule 4: release_branch"),
    ("rerun-on-first-attempt", "rule 4: rerun"),
    ("rerun-unnamed", "rule 4: rerun"),
    ("run-without-tests", "$.lanes.rust.tests: 0 items"),
    ("rust-test-unknown-kind", "rule 7: rust:bin:openwiz"),
    ("selected-empty-diff", "$.diff.state: expected \"read\""),
    ("selected-on-push", "$.run.event: expected \"pull_request\""),
    (
        "selected-ready-for-review",
        "$.run.action: \"ready_for_review\" is not one of",
    ),
    (
        "selected-release-branch",
        "$.run.base_branch: expected \"main\"",
    ),
    ("selected-rerun", "$.run.attempt: expected 1"),
    ("skill-test-of-another-skill", "rule 7: skill:launch-fleet"),
    ("skill-twice", "rule 8: the skill triage has two lanes"),
    ("skip-blank-reason", "$.lanes.site: matches 0"),
    ("skip-without-reason", "$.lanes.web: matches 0"),
    ("skipped-test-without-reason", "$.lanes.rust: matches 0"),
    ("store-wrong-attempt", "rule 2: ci-selection-1"),
    (
        "store-wrong-file",
        "$.store.file: expected \"ci-selection.json\"",
    ),
    (
        "test-in-another-lane",
        "rule 7: rust:test:fleet is not a test of the web lane",
    ),
    ("test-twice", "rule 6: rust:lib:openwiz-server"),
    ("test-without-name", "rule 7: rust:test:"),
    (
        "unknown-path-not-in-diff",
        "rule 5: unknown_path names tools/other/run.sh",
    ),
    ("unknown-path-without-diff", "rule 5: unknown_path"),
    (
        "web-export-skip-without-reason",
        "$.builds.web_export: matches 0",
    ),
    (
        "wrong-schema",
        "$.schema: expected \"openwiz.ci-selection.v1\"",
    ),
];

fn path(relative: &str) -> PathBuf {
    Path::new(ROOT).join(relative)
}

fn text(at: &Path) -> String {
    fs::read_to_string(at).unwrap_or_else(|e| panic!("{}: {e}", at.display()))
}

fn schema() -> Value {
    serde_json::from_str(&text(&path(SCHEMA))).expect("the schema is JSON")
}

/// The JSON file names in one fixtures folder, without `.json`.
fn names(folder: &str) -> Vec<String> {
    let mut out: Vec<String> = fs::read_dir(path(&format!("{FIXTURES}/{folder}")))
        .unwrap_or_else(|e| panic!("{FIXTURES}/{folder}: {e}"))
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .map(|name| {
            name.strip_suffix(".json")
                .unwrap_or_else(|| panic!("{FIXTURES}/{folder}/{name}: only .json files"))
                .to_owned()
        })
        .collect();
    out.sort();
    out
}

/// The object keys written in a JSON text, counted outside strings.
fn keys_in_text(json: &str) -> usize {
    let (mut keys, mut in_string, mut escaped, mut ended_string) = (0, false, false, false);
    for c in json.chars() {
        if in_string {
            match (escaped, c) {
                (true, _) => escaped = false,
                (false, '\\') => escaped = true,
                (false, '"') => {
                    in_string = false;
                    ended_string = true;
                }
                _ => {}
            }
            continue;
        }
        match c {
            '"' => in_string = true,
            ':' if ended_string => keys += 1,
            c if c.is_whitespace() => continue,
            _ => {}
        }
        ended_string = false;
    }
    keys
}

/// The object keys a parsed value kept.
fn keys_in_value(value: &Value) -> usize {
    match value {
        Value::Object(map) => map.len() + map.values().map(keys_in_value).sum::<usize>(),
        Value::Array(items) => items.iter().map(keys_in_value).sum(),
        _ => 0,
    }
}

/// Every refusal of a record's text: rule 1 (read exactly), then the
/// schema, then the rules beyond it. Empty means valid.
fn refusals(json: &str) -> Vec<String> {
    let value: Value = match serde_json::from_str(json) {
        Ok(value) => value,
        Err(e) => return vec![format!("not JSON: {e}")],
    };
    if keys_in_text(json) != keys_in_value(&value) {
        return vec!["rule 1: a repeated key".to_owned()];
    }
    let errors = schema_errors(&value);
    if !errors.is_empty() {
        return errors;
    }
    rules(&value)
}

/// The schema's errors. A refused record is checked again against the one
/// branch its `selection.mode` names, so the error names the field, not
/// only the top-level `oneOf`.
fn schema_errors(value: &Value) -> Vec<String> {
    let mut schema = schema();
    let errors = crate::pattern::validate(&schema, value);
    if errors.is_empty() {
        return errors;
    }
    let branch = match value.pointer("/selection/mode").and_then(Value::as_str) {
        Some("full") => "#/$defs/full",
        Some("selected") => "#/$defs/selected",
        _ => return errors,
    };
    schema["$ref"] = json!(branch);
    let detail = crate::pattern::validate(&schema, value);
    if detail.is_empty() { errors } else { detail }
}

fn str_at<'a>(value: &'a Value, pointer: &str) -> &'a str {
    value.pointer(pointer).and_then(Value::as_str).unwrap_or("")
}

/// The contract's rules 2 to 9, on a record the schema already accepts.
fn rules(plan: &Value) -> Vec<String> {
    let mut out = Vec::new();
    let run = &plan["run"];
    let event = str_at(run, "/event");
    let attempt = run["attempt"].as_u64().unwrap_or(0);
    let base_branch = str_at(run, "/base_branch");

    // Rule 2: the store names its attempt.
    let artifact = str_at(plan, "/store/artifact");
    if artifact != format!("ci-selection-{attempt}") {
        out.push(format!(
            "rule 2: {artifact} is not ci-selection-{attempt}, for attempt {attempt}"
        ));
    }

    // Rule 3: the run's fields fit its event.
    if (event == "pull_request") != run["pull_request"].is_u64() {
        out.push(format!(
            "rule 3: run.pull_request is {} on a {event} run",
            run["pull_request"]
        ));
    }
    if (event == "pull_request") != run["action"].is_string() {
        out.push(format!(
            "rule 3: run.action is {} on a {event} run",
            run["action"]
        ));
    }
    if event == "pull_request" && run["base"].is_null() {
        out.push("rule 3: run.base is null on a pull_request run".to_owned());
    }
    if run["base"]
        .as_str()
        .is_some_and(|b| b.bytes().all(|c| c == b'0'))
    {
        out.push("rule 3: run.base is all zeros, not a commit".to_owned());
    }
    if base_branch != "main" && !base_branch.starts_with("release-") {
        out.push(format!(
            "rule 3: run.base_branch {base_branch} is neither main nor release-*"
        ));
    }

    let reasons: Vec<&Value> = plan
        .pointer("/selection/reasons")
        .and_then(Value::as_array)
        .map(|r| r.iter().collect())
        .unwrap_or_default();
    let has = |code: &str| reasons.iter().any(|r| r["code"] == code);

    // Rule 4: every event that selects everything says so, and only it.
    let events = [
        ("push_main", event == "push", "run.event is push"),
        ("nightly", event == "schedule", "run.event is schedule"),
        (
            "merge_group",
            event == "merge_group",
            "run.event is merge_group",
        ),
        ("rerun", attempt > 1, "run.attempt is above 1"),
        (
            "ready_for_review",
            str_at(run, "/action") == "ready_for_review",
            "run.action is ready_for_review",
        ),
        (
            "release_branch",
            base_branch.starts_with("release-"),
            "run.base_branch starts with release-",
        ),
    ];
    for (code, happened, when) in events {
        if has(code) != happened {
            out.push(format!("rule 4: {code} exactly when {when}"));
        }
    }
    if event == "push" && base_branch != "main" {
        out.push(format!("rule 4: a push into {base_branch}, not main"));
    }

    // Rule 5: doubts match the diff.
    let diff = str_at(plan, "/diff/state");
    let needs_no_diff = [
        "push_main",
        "nightly",
        "merge_group",
        "rerun",
        "release_branch",
        "ready_for_review",
        "stale_event",
    ];
    if diff == "not_read" && !needs_no_diff.iter().any(|code| has(code)) {
        out.push("rule 5: a not_read diff with no reason that needs no diff".to_owned());
    }
    for (code, state) in [("empty_diff", "empty"), ("failed_diff", "failed")] {
        if has(code) != (diff == state) {
            out.push(format!("rule 5: {code} exactly when diff.state is {state}"));
        }
    }
    let changed: BTreeSet<&str> = plan
        .pointer("/diff/paths")
        .and_then(Value::as_array)
        .map(|p| p.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    for reason in &reasons {
        let code = reason["code"].as_str().unwrap_or("");
        let Some(paths) = reason["paths"].as_array() else {
            continue;
        };
        if diff != "read" {
            out.push(format!(
                "rule 5: {code} with a diff that is {diff}, not read"
            ));
        }
        for p in paths.iter().filter_map(Value::as_str) {
            if !changed.contains(p) {
                out.push(format!("rule 5: {code} names {p}, not in diff.paths"));
            }
        }
    }

    // Rule 9: each reason code once.
    let mut codes = BTreeSet::new();
    for code in reasons.iter().filter_map(|r| r["code"].as_str()) {
        if !codes.insert(code) {
            out.push(format!("rule 9: {code} is given twice"));
        }
    }

    // Rules 6 to 8: each test once, in its own lane; each skill once.
    let lanes = &plan["lanes"];
    let mut seen = BTreeSet::new();
    let mut skills = BTreeSet::new();
    let mut each = vec![
        ("always", &lanes["always"], vec!["always:".to_owned()]),
        (
            "rust",
            &lanes["rust"],
            vec!["rust:lib:".to_owned(), "rust:test:".to_owned()],
        ),
        (
            "web",
            &lanes["web"],
            vec!["web:unit:".to_owned(), "web:browser:".to_owned()],
        ),
        (
            "site",
            &lanes["site"],
            vec!["site:".to_owned(), "release:".to_owned()],
        ),
    ];
    for lane in lanes["skills"].as_array().into_iter().flatten() {
        let skill = str_at(lane, "/skill");
        if !skills.insert(skill) {
            out.push(format!("rule 8: the skill {skill} has two lanes"));
        }
        each.push((
            "skills",
            lane,
            vec![format!("skill:{skill}:"), format!("skill:{skill}")],
        ));
    }
    for (name, lane, forms) in each {
        let ran = lane["tests"].as_array().into_iter().flatten();
        let skipped = lane["skipped"].as_array().into_iter().flatten();
        let ids = ran
            .filter_map(Value::as_str)
            .chain(skipped.filter_map(|s| s["test"].as_str()));
        for id in ids {
            if !seen.insert(id) {
                out.push(format!("rule 6: {id} is in the plan twice"));
            }
            let fits = forms.iter().any(|form| match form.strip_suffix(':') {
                Some(_) => id
                    .strip_prefix(form.as_str())
                    .is_some_and(|n| !n.is_empty()),
                None => id == form,
            });
            if !fits {
                out.push(format!("rule 7: {id} is not a test of the {name} lane"));
            }
        }
    }
    out
}

#[test]
fn ci_selection_schema_is_checkable_and_refuses_malformed_roots() {
    let schema = schema();
    assert_eq!(schema["title"], "openwiz.ci-selection.v1");
    assert_eq!(crate::pattern::lint(&schema), Vec::<String>::new());
    for malformed in [
        "null",
        "[]",
        "{}",
        "\"Synthetic\"",
        r#"{"schema": "openwiz.ci-selection.v1"}"#,
    ] {
        assert!(!refusals(malformed).is_empty(), "{malformed}");
    }
}

#[test]
fn ci_selection_folder_holds_its_readme_and_fixtures_only() {
    let mut top: Vec<String> = fs::read_dir(path(FIXTURES))
        .expect("the fixtures folder")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .collect();
    top.sort();
    assert_eq!(top, ["README.md", "invalid", "reads", "valid"]);
    let readme = text(&path(&format!("{FIXTURES}/README.md")));
    // Each fixture has its own row in the README's tables, and each row a fixture.
    let rows: BTreeSet<String> = readme
        .lines()
        .filter_map(|l| l.strip_prefix("| `"))
        .filter_map(|l| l.split_once(".json` |"))
        .map(|(name, _)| name.to_owned())
        .collect();
    let files: BTreeSet<String> = ["valid", "invalid", "reads"]
        .iter()
        .flat_map(|folder| {
            names(folder)
                .into_iter()
                .map(move |n| format!("{folder}/{n}"))
        })
        .collect();
    assert_eq!(rows, files, "README rows against the fixture files");
}

#[test]
fn ci_selection_every_valid_fixture_passes() {
    let mut modes = BTreeSet::new();
    let mut events = BTreeSet::new();
    let mut actions = BTreeSet::new();
    let mut codes = BTreeSet::new();
    for name in names("valid") {
        let json = text(&path(&format!("{FIXTURES}/valid/{name}.json")));
        assert_eq!(refusals(&json), Vec::<String>::new(), "valid/{name}");
        let plan: Value = serde_json::from_str(&json).unwrap();
        let mode = plan["selection"]["mode"].as_str().unwrap().to_owned();
        assert!(
            name.starts_with(&format!("{mode}-")),
            "valid/{name}: {mode}"
        );
        modes.insert(mode);
        events.insert(plan["run"]["event"].as_str().unwrap().to_owned());
        if let Some(action) = plan["run"]["action"].as_str() {
            actions.insert(action.to_owned());
        }
        for reason in plan["selection"]["reasons"]
            .as_array()
            .into_iter()
            .flatten()
        {
            codes.insert(reason["code"].as_str().unwrap().to_owned());
        }
    }
    // A plan for every full-run reason and every event, and selected plans.
    let schema = schema();
    let mut every: BTreeSet<String> = BTreeSet::new();
    for branch in schema["$defs"]["reason"]["oneOf"].as_array().unwrap() {
        let code = &branch["properties"]["code"];
        let listed = code["enum"].as_array().cloned().unwrap_or_default();
        every.extend(
            listed
                .iter()
                .chain(code.get("const"))
                .map(|c| c.as_str().unwrap().to_owned()),
        );
    }
    assert_eq!(every.len(), 12, "the reason codes");
    assert_eq!(codes, every);
    let all_events: BTreeSet<String> = schema["$defs"]["run"]["properties"]["event"]["enum"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e.as_str().unwrap().to_owned())
        .collect();
    assert_eq!(events, all_events);
    let all_actions: BTreeSet<String> = schema["$defs"]["action"]["enum"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a.as_str().unwrap().to_owned())
        .collect();
    assert_eq!(all_actions.len(), 4, "the pull request actions");
    assert_eq!(actions, all_actions);
    assert_eq!(modes, BTreeSet::from(["full".into(), "selected".into()]));
    for name in ["selected-skill-only", "selected-mixed"] {
        assert!(
            path(&format!("{FIXTURES}/valid/{name}.json")).is_file(),
            "{name}"
        );
    }
}

#[test]
fn ci_selection_every_invalid_fixture_is_refused_for_its_reason() {
    let expected: Vec<String> = INVALID.iter().map(|(n, _)| n.to_string()).collect();
    assert_eq!(names("invalid"), expected, "the invalid fixtures, in order");
    let mut failures = Vec::new();
    for (name, why) in INVALID {
        let got = refusals(&text(&path(&format!("{FIXTURES}/invalid/{name}.json"))));
        if !got.iter().any(|e| e.contains(why)) {
            failures.push(format!("invalid/{name}: wanted {why:?}, got {got:?}"));
        }
    }
    assert!(failures.is_empty(), "\n{}", failures.join("\n"));
}

#[test]
fn ci_selection_contract_tables_match_the_schema() {
    let contract = text(&path(CONTRACT));
    let schema = schema();
    // Each table row's first cell, in backticks, under one heading.
    let rows = |heading: &str| -> BTreeSet<String> {
        let section = contract
            .split("\n## ")
            .find(|s| s.starts_with(heading))
            .unwrap_or_else(|| panic!("{CONTRACT}: no section {heading}"));
        let own = section.split("\n### ").next().unwrap();
        own.lines()
            .filter_map(|l| l.strip_prefix("| `"))
            .filter_map(|l| l.split_once("` |"))
            .map(|(cell, _)| cell.to_owned())
            .collect()
    };
    let strings = |values: &Value| -> BTreeSet<String> {
        values
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_owned())
            .collect()
    };
    let defs = &schema["$defs"];
    let mut codes = BTreeSet::new();
    for branch in defs["reason"]["oneOf"].as_array().unwrap() {
        let code = &branch["properties"]["code"];
        match code.get("enum") {
            Some(listed) => codes.extend(strings(listed)),
            None => {
                codes.insert(code["const"].as_str().unwrap().to_owned());
            }
        }
    }
    assert_eq!(rows("Full runs"), codes, "the reason codes");
    let lanes: BTreeSet<String> = strings(&defs["lanes_full"]["required"]);
    assert_eq!(rows("Lanes"), lanes, "the lanes");
    let builds: BTreeSet<String> = strings(&defs["builds_full"]["required"]);
    assert_eq!(rows("Builds"), builds, "the builds");
    let states: BTreeSet<String> = defs["diff"]["oneOf"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| {
            let b = match b.get("$ref") {
                Some(r) => schema.pointer(&r.as_str().unwrap()[1..]).unwrap(),
                None => b,
            };
            b["properties"]["state"]["const"]
                .as_str()
                .unwrap()
                .to_owned()
        })
        .collect();
    assert_eq!(rows("The diff"), states, "the diff states");
    assert!(
        contract.contains("`ci-selection-<attempt>`"),
        "the artifact"
    );
    assert_eq!(
        defs["store"]["properties"]["file"]["const"],
        "ci-selection.json"
    );
    assert!(contract.contains("`ci-selection.json`"), "the file");
}

/// The contract's "Reading a merged pull request's plan", on one synthetic
/// read case (`ci/selection/reads/`): the run and attempt whose plan holds
/// for the pull request, or `"unknown"`.
fn lookup(case: &Value) -> Value {
    let unknown = json!("unknown");
    let (pr, head) = (&case["pull_request"], &case["head"]);
    let same_head: Vec<&Value> = case["runs"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|r| {
            r["workflow"] == ".github/workflows/ci.yml"
                && r["event"] == "pull_request"
                && &r["head_sha"] == head
        })
        .collect();
    // An association that can't be read (missing or null) might be this
    // pull request's: unknown, before any run is chosen.
    if same_head.iter().any(|r| !r["pull_requests"].is_array()) {
        return unknown;
    }
    let Some(run) = same_head
        .into_iter()
        .filter(|r| {
            r["pull_requests"]
                .as_array()
                .is_some_and(|prs| prs.contains(pr))
        })
        .max_by_key(|r| r["id"].as_u64())
    else {
        return unknown;
    };
    let Some(last) = run["attempts"]
        .as_array()
        .into_iter()
        .flatten()
        .max_by_key(|a| a["attempt"].as_u64())
    else {
        return unknown;
    };
    let attempt = &last["attempt"];
    let artifact = format!("ci-selection-{attempt}");
    let Some(file) = last["artifacts"][&artifact].as_str() else {
        return unknown;
    };
    let json = text(&path(&format!("{FIXTURES}/{file}")));
    if !refusals(&json).is_empty() {
        return unknown;
    }
    let plan: Value = serde_json::from_str(&json).expect("checked");
    let bound = [
        (&plan["run"]["pull_request"], pr),
        (&plan["run"]["head"], head),
        (&plan["run"]["id"], &run["id"]),
        (&plan["run"]["attempt"], attempt),
        (&plan["store"]["artifact"], &json!(artifact)),
    ];
    if bound.iter().any(|(got, want)| got != want) {
        return unknown;
    }
    json!({"run": run["id"], "attempt": attempt})
}

#[test]
fn ci_selection_reads_find_each_merged_pull_requests_plan() {
    let mut failures = Vec::new();
    let reads = names("reads");
    assert_eq!(reads.len(), 13, "the read cases");
    for name in reads {
        let case: Value =
            serde_json::from_str(&text(&path(&format!("{FIXTURES}/reads/{name}.json"))))
                .expect("a read case");
        let got = lookup(&case);
        if got != case["expected"] {
            failures.push(format!(
                "reads/{name}: wanted {}, got {got}",
                case["expected"]
            ));
        }
    }
    assert!(failures.is_empty(), "\n{}", failures.join("\n"));
}
