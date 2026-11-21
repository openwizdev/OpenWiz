use serde_json::{Value, json};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Output;

use super::{ROOT, Sandbox, schema};

const PROJECT: &str = "prj_syn_0001";

struct Fake(Sandbox);

impl Fake {
    fn new() -> Self {
        Self::with_scenario(&Path::new(ROOT).join("tests/fake-room-cli/loops/scenario.json"))
    }

    fn with_scenario(scenario: &Path) -> Self {
        let sandbox = Sandbox::new();
        let bin = sandbox.0.join("bin");
        fs::remove_file(bin.join("room-cli")).unwrap();
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), bin.join("room-cli"))
            .unwrap();
        fs::write(
            bin.join("fake-room-cli.scenario"),
            scenario.to_str().unwrap(),
        )
        .unwrap();
        Self(sandbox)
    }

    fn answering(list: Value) -> Self {
        let fake = Self::new();
        let path = fake.0.0.join("scenario.json");
        fs::write(&path, json!({"responses": [list]}).to_string()).unwrap();
        fs::write(
            fake.0.0.join("bin/fake-room-cli.scenario"),
            path.to_str().unwrap(),
        )
        .unwrap();
        fake
    }

    fn dir(&self) -> &Path {
        &self.0.0
    }

    fn run(&self, args: &[&str]) -> Output {
        let mut all = vec!["loop", "plan"];
        all.extend(args);
        self.0.run(&all)
    }

    fn json(&self, args: &[&str]) -> (i32, Value) {
        let mut all = args.to_vec();
        all.push("--json");
        let output = self.run(&all);
        let code = output.status.code().unwrap();
        let stdout = String::from_utf8(output.stdout).unwrap();
        assert!(
            stdout.ends_with('\n') && stdout.lines().count() == 1,
            "{stdout}"
        );
        let doc: Value = serde_json::from_str(&stdout).unwrap();
        let against = contract(if doc["schema"] == "openwiz.cli-error.v1" {
            "cli.v1.schema.json"
        } else {
            "loop-cli.v1.schema.json"
        });
        assert_eq!(
            schema::validate(&against, &doc),
            Vec::<String>::new(),
            "{doc:#}"
        );
        assert_eq!(doc["exit_code"], code, "{doc:#}");
        (code, doc)
    }

    fn calls(&self) -> Vec<Value> {
        fs::read_to_string(self.0.0.join("bin/invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }

    fn assert_only_listed(&self) {
        assert_eq!(self.calls(), vec![json!(["loop", "list", "--json"])]);
        assert!(
            !self.0.0.join("bin/loop-writes.log").exists(),
            "plan wrote a loop"
        );
    }

    fn write(&self, path: &str, text: &str) -> PathBuf {
        let path = self.0.0.join(path);
        super::dirs::private_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, text).unwrap();
        path
    }
}

fn contract(name: &str) -> Value {
    serde_json::from_str(&fs::read_to_string(Path::new(ROOT).join("contracts").join(name)).unwrap())
        .unwrap()
}

fn fixtures() -> PathBuf {
    Path::new(ROOT).join("contracts/fixtures/wizloops")
}

fn argv(words: &str) -> Value {
    json!(words.split('|').collect::<Vec<_>>())
}

fn item<'a>(doc: &'a Value, file: &str) -> &'a Value {
    doc["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|i| i["file"].as_str().unwrap().ends_with(file))
        .unwrap_or_else(|| panic!("no item for {file}: {doc:#}"))
}

fn codes(item: &Value) -> Vec<(String, String)> {
    item["refusals"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            (
                r["code"].as_str().unwrap().into(),
                r["field"].as_str().unwrap().into(),
            )
        })
        .collect()
}

#[test]
fn plan_creates_each_valid_fixture_as_the_adapters_table_says() {
    let fake = Fake::new();
    let valid = fixtures().join("valid");
    let (code, doc) = fake.json(&[valid.to_str().unwrap(), "--project", "prj_syn_0009"]);
    assert_eq!(code, 5, "five fixtures are refused by the adapter");
    fake.assert_only_listed();
    let files: Vec<&str> = doc["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["file"].as_str().unwrap())
        .collect();
    let names = [
        "all-secrets-new.md",
        "all-secrets-same.md",
        "at-same.md",
        "cron-check.md",
        "fast-no-check.md",
        "in-same.md",
        "long-check.md",
        "params-env.md",
        "python-check.md",
        "same-thread-agent.md",
        "script-only.md",
        "short-check.md",
        "webhook-new.md",
    ];
    let expected: Vec<String> = names
        .iter()
        .map(|n| format!("{}/{n}", valid.display()))
        .collect();
    assert_eq!(files, expected, "one item per file, in byte order of name");
    let cron_check_script = "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REPO='example-org/example-repo'\n# wizloop: the check\n# Prints one line per due item in $WIZLOOP_PARAM_REPO; nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n";
    let params_env_script = "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REF='release/\";printf${IFS}WAKE;false${IFS}\"'\nexport WIZLOOP_PARAM_REPO='example-org/example-repo'\nexport WIZLOOP_PARAM_SPEC=7\nexport WIZLOOP_PARAM_TITLE='it'\\''s $(touch marker) `touch marker`'\n# wizloop: the check\n# Reads its params from the environment as data and prints nothing, so no\n# agent starts: $WIZLOOP_PARAM_REPO, $WIZLOOP_PARAM_REF, $WIZLOOP_PARAM_TITLE\n# and $WIZLOOP_PARAM_SPEC.\nexit 0\n";
    let script_only = fs::read_to_string(valid.join("script-only/check.sh")).unwrap();
    let creates = [
        (
            "cron-check.md",
            "loop|create|--name|Example triage every ten minutes [wizloop:cron-check]|--prompt-file|@prompt|--cron|*/10 * * * *|--timezone|UTC|--new-thread|--script-file|@script|--provider|example-provider|--model|example-model|--reasoning|medium|--priority|2|--secrets|EXAMPLE_TOKEN,.env",
            json!({"@prompt": "Triage the due items for spec 42 that the check printed below.\n", "@script": cron_check_script}),
        ),
        (
            "at-same.md",
            "loop|create|--name|One reminder [wizloop:at-same]|--prompt-file|@prompt|--at|2030-01-02T03:04:05Z|--same-thread|--priority|3|--secrets|none",
            json!({"@prompt": "Remind the owner to read the example report.\n"}),
        ),
        (
            "in-same.md",
            "loop|create|--name|Look again in half an hour [wizloop:in-same]|--prompt-file|@prompt|--in|30m|--same-thread|--priority|1|--secrets|none",
            json!({"@prompt": "Check what changed in the last 6 hours and say it in one line.\n"}),
        ),
        (
            "webhook-new.md",
            "loop|create|--name|Wake on a delivery [wizloop:webhook-new]|--prompt-file|@prompt|--webhook|--new-thread|--priority|4|--secrets|none",
            json!({"@prompt": "Read the requests that arrived and route each one to its owner.\n"}),
        ),
        (
            "script-only.md",
            "loop|create|--name|Kick an example job hourly [wizloop:script-only]|--prompt-file|@prompt|--cron|12 * * * *|--timezone|America/Los_Angeles|--new-thread|--script-file|@script|--priority|3|--secrets|none",
            json!({"@prompt": "Nothing to do: the check does the work and prints nothing.\n", "@script": script_only}),
        ),
        (
            "all-secrets-new.md",
            "loop|create|--name|A new-thread loop with every secret [wizloop:all-secrets-new]|--prompt-file|@prompt|--cron|0 5 * * *|--timezone|UTC|--new-thread|--priority|3|--secrets|all",
            json!({"@prompt": "Post a short note on the example repository.\n"}),
        ),
        (
            "all-secrets-same.md",
            "loop|create|--name|A same-thread loop with every secret [wizloop:all-secrets-same]|--prompt-file|@prompt|--cron|15 5 * * *|--timezone|UTC|--same-thread|--priority|3|--secrets|all",
            json!({"@prompt": "Post a short note on the example repository.\n"}),
        ),
        (
            "params-env.md",
            "loop|create|--name|Params reach the check as data [wizloop:params-env]|--prompt-file|@prompt|--cron|30 6 * * *|--timezone|UTC|--new-thread|--script-file|@script|--priority|3|--secrets|none",
            json!({"@prompt": "Report the check's output for spec 7 in example-org/example-repo.\n", "@script": params_env_script}),
        ),
    ];
    for (file, words, texts) in creates {
        let item = item(&doc, &format!("/{file}"));
        assert_eq!(item["action"], "create", "{file}");
        assert_eq!(item["id"], file.trim_end_matches(".md"), "{file}");
        assert_eq!(
            (&item["loop"], &item["paused"]),
            (&Value::Null, &json!(false)),
            "{file}"
        );
        assert_eq!(
            item["commands"],
            json!([{"argv": argv(words), "files": texts}]),
            "{file}"
        );
        assert_eq!(
            (&item["differences"], &item["refusals"]),
            (&json!([]), &json!([])),
            "{file}"
        );
    }
    for (file, code, field) in [
        ("python-check.md", "cf-check-shell", "check.run"),
        ("same-thread-agent.md", "cf-agent-same-thread", "agent"),
        ("fast-no-check.md", "cf-too-frequent", "trigger.cron"),
        ("long-check.md", "cf-check-timeout", "check.timeout"),
        ("short-check.md", "cf-check-timeout", "check.timeout"),
    ] {
        let item = item(&doc, &format!("/{file}"));
        assert_eq!(item["action"], "refused", "{file}");
        assert_eq!(item["commands"], json!([]), "{file}");
        assert_eq!(
            codes(item),
            vec![(code.to_owned(), field.to_owned())],
            "{file}"
        );
        assert_eq!(
            item["refusals"][0]["file"],
            format!("{}/{file}", valid.display())
        );
    }
    assert_eq!(
        item(&doc, "/long-check.md")["refusals"][0]["message"],
        "Cloudroom runs a check for exactly 60 seconds; set the timeout to 60"
    );
    for file in ["/at-same.md", "/in-same.md", "/all-secrets-same.md"] {
        let notes = item(&doc, file)["notes"].as_array().unwrap();
        assert!(
            notes
                .iter()
                .any(|n| n.as_str().unwrap().contains("environment")),
            "{file}"
        );
    }
    assert_eq!(
        (&doc["unmanaged"], &doc["orphans"]),
        (&json!([]), &json!([]))
    );
}

#[test]
fn plan_refuses_each_invalid_fixture_with_its_expected_refusals() {
    let expected: Value =
        serde_json::from_str(&fs::read_to_string(fixtures().join("expected.json")).unwrap())
            .unwrap();
    let fake = Fake::new();
    let invalid = fixtures().join("invalid");
    let folder = fixtures().join("invalid-folder/duplicate-id");
    let (code, doc) = fake.json(&[
        invalid.to_str().unwrap(),
        folder.to_str().unwrap(),
        "--project",
        "prj_syn_0009",
    ]);
    assert_eq!(code, 5);
    fake.assert_only_listed();
    let mut seen = 0;
    for (name, entry) in expected["fixtures"].as_object().unwrap() {
        let Some(file) = name.strip_prefix("invalid/") else {
            continue;
        };
        seen += 1;
        let shown = format!("{}/{file}", invalid.display());
        let item = item(&doc, &format!("/invalid/{file}"));
        assert_eq!(item["file"], shown);
        assert_eq!(
            (&item["action"], &item["commands"]),
            (&json!("refused"), &json!([])),
            "{name}"
        );
        let want: Vec<Value> = entry["refusals"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| json!({"file": shown, "code": r["code"], "field": r["field"], "message": r["message"]}))
            .collect();
        assert_eq!(item["refusals"], json!(want), "{name}");
    }
    assert_eq!(seen, 47, "every invalid fixture is planned");
    let a = item(&doc, "/duplicate-id/a.md");
    assert_eq!(a["action"], "create");
    let b = item(&doc, "/duplicate-id/b.md");
    assert_eq!(b["action"], "refused");
    assert_eq!(
        b["refusals"],
        json!([{"file": format!("{}/b.md", folder.display()), "code": "duplicate-id", "field": "id", "message": "same-id is also the id of a.md"}])
    );
    assert_eq!(doc["items"].as_array().unwrap().len(), 49);
}

const ACCOUNT_FILES: [(&str, &str); 7] = [
    (
        "loops/syn-triage.md",
        "---\nid: \"syn-triage\"\nname: \"Synthetic triage every ten minutes\"\ntrigger: {\"cron\": \"*/10 * * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"syn-triage/check\", \"timeout\": 60}\nthread: \"new\"\nagent: {\"provider\": \"synthetic-provider\", \"model\": \"synthetic-model\", \"reasoning\": \"medium\"}\nsecrets: [\"SYNTHETIC_TOKEN\", \".env\"]\npriority: 2\nparams: {\"repo\": \"synthetic-org/synthetic-repo\"}\n---\nSynthetic: triage the due items the check printed below.",
    ),
    (
        "loops/syn-triage/check",
        "#!/bin/sh\n# Synthetic check: prints the due items in $WIZLOOP_PARAM_REPO, nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n",
    ),
    (
        "loops/syn-delivery.md",
        "---\nid: \"syn-delivery\"\nname: \"Synthetic delivery\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\nsecrets: []\npriority: 4\n---\nSynthetic: route each request that arrived to its owner.",
    ),
    (
        "loops/syn-nightly.md",
        "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"new\"\nsecrets: \"all\"\npriority: 3\n---\nSynthetic: post a short nightly note.",
    ),
    (
        "loops/syn-reminder.md",
        "---\nid: \"syn-reminder\"\nname: \"Synthetic reminder\"\ntrigger: {\"at\": \"2030-01-02T03:04:05.000Z\"}\nthread: \"same\"\nsecrets: []\npriority: 1\n---\nSynthetic: remind the owner to read the report.",
    ),
    (
        "loops/synthetic-hourly-kick.md",
        "---\nid: \"synthetic-hourly-kick\"\nname: \"Synthetic hourly kick\"\ntrigger: {\"cron\": \"12 * * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"synthetic-hourly-kick/check\", \"timeout\": 60}\nthread: \"new\"\nsecrets: []\npriority: 3\n---\nSynthetic: nothing to do.",
    ),
    ("loops/synthetic-hourly-kick/check", "#!/bin/sh\nexit 0\n"),
];

fn account(fake: &Fake) -> PathBuf {
    for (path, text) in ACCOUNT_FILES {
        fake.write(path, text);
    }
    fake.dir().join("loops")
}

#[test]
fn plan_of_the_accounts_own_files_shows_no_difference() {
    let fake = Fake::new();
    let loops = account(&fake);
    let (code, doc) = fake.json(&[
        loops.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "synthetic-hourly-kick=loop_syn_5",
    ]);
    assert_eq!(code, 0, "{doc:#}");
    fake.assert_only_listed();
    for (file, id, live, paused) in [
        ("syn-delivery.md", "syn-delivery", "loop_syn_2", false),
        ("syn-nightly.md", "syn-nightly", "loop_syn_3", false),
        ("syn-reminder.md", "syn-reminder", "loop_syn_4", true),
        ("syn-triage.md", "syn-triage", "loop_syn_1", false),
    ] {
        let item = item(&doc, &format!("/{file}"));
        assert_eq!(item["id"], id);
        assert_eq!(
            (&item["action"], &item["loop"], &item["paused"]),
            (&json!("none"), &json!(live), &json!(paused)),
            "{file}"
        );
        assert_eq!(
            (&item["commands"], &item["differences"], &item["refusals"]),
            (&json!([]), &json!([]), &json!([])),
            "{file}"
        );
    }
    let kick = item(&doc, "/synthetic-hourly-kick.md");
    assert_eq!(
        (&kick["action"], &kick["loop"]),
        (&json!("update"), &json!("loop_syn_5"))
    );
    assert_eq!(
        kick["commands"],
        json!([{"argv": ["loop", "update", "loop_syn_5", "--name", "Synthetic hourly kick [wizloop:synthetic-hourly-kick]"], "files": {}}])
    );
    assert_eq!(
        (&kick["differences"], &kick["refusals"]),
        (&json!([]), &json!([]))
    );
    assert_eq!(
        (&doc["unmanaged"], &doc["orphans"]),
        (&json!([]), &json!([]))
    );

    let (code, doc) = fake.json(&[loops.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(code, 5);
    let kick = item(&doc, "/synthetic-hourly-kick.md");
    assert_eq!(codes(kick), vec![("cf-unmarked-match".into(), "id".into())]);
    assert_eq!(kick["commands"], json!([]));
    assert_eq!(
        doc["unmanaged"],
        json!([{"loop": "loop_syn_5", "name": "Synthetic hourly kick"}])
    );

    let output = fake.run(&[
        loops.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "synthetic-hourly-kick=loop_syn_5",
    ]);
    assert_eq!(output.status.code(), Some(0));
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(
        text.contains(&format!(
            "{}/syn-reminder.md: no change to loop_syn_4 (paused)\n",
            loops.display()
        )),
        "{text}"
    );
    assert!(text.contains("  room-cli 'loop' 'update' 'loop_syn_5' '--name' 'Synthetic hourly kick [wizloop:synthetic-hourly-kick]'\n"), "{text}");
    assert!(text.ends_with("Nothing was changed.\n"), "{text}");
}

fn files_under(dir: &Path) -> Vec<(String, Vec<u8>)> {
    fn walk(root: &Path, dir: &Path, out: &mut Vec<(String, Vec<u8>)>) {
        for entry in fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path == root.join("bin") {
                continue;
            }
            if path.is_dir() {
                walk(root, &path, out);
            } else {
                let rel = path.strip_prefix(root).unwrap().display().to_string();
                out.push((rel, fs::read(&path).unwrap_or_default()));
            }
        }
    }
    let mut out = Vec::new();
    walk(dir, dir, &mut out);
    out.sort();
    out
}

#[cfg(target_os = "linux")]
#[test]
fn export_then_plan_shows_no_difference() {
    let list: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("tests/fake-room-cli/loops/list.json")).unwrap(),
    )
    .unwrap();
    let mut automations = list["automations"].as_array().unwrap().clone();
    let mut budget = automations
        .iter()
        .find(|a| a["id"] == "loop_syn_3")
        .unwrap()
        .clone();
    budget["id"] = json!("loop_syn_8");
    budget["name"] = json!("Synthetic budget [wizloop:syn-budget]");
    budget["prompt"] = json!("Synthetic: report the budget.");
    budget["budget_synthetic"] = json!({"max_runs": 3});
    automations.push(budget);
    let fake = Fake::answering(json!({
        "argv": ["loop", "list", "--json"],
        "stdout": json!({"automations": automations}).to_string(),
    }));
    let out = fake.dir().join("exported");
    super::dirs::private_dir_all(&out).unwrap();
    let before = files_under(fake.dir());

    let export = fake.0.run(&[
        "loop",
        "export",
        "--project",
        PROJECT,
        "--out",
        "exported",
        "--json",
    ]);
    assert_eq!(
        export.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&export.stderr)
    );
    let report: Value = serde_json::from_slice(&export.stdout).unwrap();
    let mut against = contract("loop-cli.v1.schema.json");
    against["$ref"] = json!("#/$defs/export_report");
    assert_eq!(schema::validate(&against, &report), Vec::<String>::new());
    let exported = report["loops"].as_array().unwrap();
    assert_eq!(exported.len(), 6, "{report:#}");
    assert!(
        exported.iter().all(|l| l["result"] == "written"),
        "{report:#}"
    );
    let unmapped: Vec<(&Value, &Value)> = exported
        .iter()
        .filter(|l| l["unmapped"] != json!([]))
        .map(|l| (&l["id"], &l["unmapped"]))
        .collect();
    assert_eq!(
        unmapped,
        [(&json!("syn-budget"), &json!(["budget_synthetic"]))]
    );
    let after_export = files_under(fake.dir());
    assert!(
        after_export
            .iter()
            .filter(|f| !before.contains(f))
            .all(|(rel, _)| rel.starts_with("exported/")),
        "{:?}",
        after_export.iter().map(|f| &f.0).collect::<Vec<_>>()
    );
    let bindings: Vec<String> = exported
        .iter()
        .filter(|l| !l["binding"].is_null())
        .map(|l| {
            format!(
                "{}={}",
                l["binding"]["id"].as_str().unwrap(),
                l["binding"]["loop"].as_str().unwrap()
            )
        })
        .collect();
    assert_eq!(bindings, ["synthetic-hourly-kick=loop_syn_5"]);

    let (code, doc) = fake.json(&[
        out.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        &bindings[0],
    ]);
    assert_eq!(code, 0, "{doc:#}");
    assert_eq!(
        fake.calls(),
        vec![
            json!(["loop", "list", "--json"]),
            json!(["loop", "list", "--json"])
        ]
    );
    assert!(!fake.dir().join("bin/loop-writes.log").exists());
    assert_eq!(files_under(fake.dir()), after_export, "plan wrote a file");

    let items = doc["items"].as_array().unwrap();
    assert_eq!(items.len(), 6, "{doc:#}");
    for item in items {
        assert_eq!(
            (&item["differences"], &item["refusals"]),
            (&json!([]), &json!([])),
            "{item:#}"
        );
    }
    for (file, live) in [
        ("syn-budget.md", "loop_syn_8"),
        ("syn-delivery.md", "loop_syn_2"),
        ("syn-nightly.md", "loop_syn_3"),
        ("syn-reminder.md", "loop_syn_4"),
        ("syn-triage.md", "loop_syn_1"),
    ] {
        let item = item(&doc, &format!("/{file}"));
        assert_eq!(
            (&item["action"], &item["loop"], &item["commands"]),
            (&json!("none"), &json!(live), &json!([])),
            "{file}"
        );
    }
    let kick = item(&doc, "/synthetic-hourly-kick.md");
    assert_eq!(
        kick["commands"],
        json!([{"argv": ["loop", "update", "loop_syn_5", "--name", "Synthetic hourly kick [wizloop:synthetic-hourly-kick]"], "files": {}}])
    );
    assert_eq!(
        (&doc["unmanaged"], &doc["orphans"]),
        (&json!([]), &json!([]))
    );
    for item in items {
        let named = item["notes"]
            .as_array()
            .unwrap()
            .iter()
            .any(|n| n.as_str().unwrap().contains("budget_synthetic"));
        assert_eq!(named, item["id"] == "syn-budget", "{item:#}");
    }
    let text = fake.run(&[
        out.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        &bindings[0],
    ]);
    assert_eq!(text.status.code(), Some(0));
    let text = String::from_utf8(text.stdout).unwrap();
    let budget_lines: Vec<&str> = text
        .lines()
        .filter(|l| l.contains("budget_synthetic"))
        .collect();
    assert_eq!(budget_lines.len(), 1, "{text}");
}

#[test]
fn plan_shows_each_difference_and_the_update_that_makes_it() {
    let fake = Fake::new();
    let loops = account(&fake);
    fake.write("loops/syn-triage.md", "---\nid: \"syn-triage\"\nname: \"Synthetic triage, renamed\"\ntrigger: {\"cron\": \"*/10 * * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"syn-triage/check\", \"timeout\": 60}\nthread: \"new\"\nagent: {\"provider\": \"synthetic-provider\", \"model\": \"synthetic-model\", \"reasoning\": \"high\"}\nsecrets: [\".env\", \"SYNTHETIC_TOKEN\"]\npriority: 3\nparams: {\"repo\": \"synthetic-org/other-repo\"}\n---\nSynthetic: triage the due items the check printed below.");
    fs::write(loops.join("syn-nightly.md"), "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 6 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"new\"\nsecrets: []\nparams: {\"when\": \"morning\"}\n---\nSynthetic: post a short {{when}} note.").unwrap();
    fake.write("loops/syn-reminder.md", "---\nid: \"syn-reminder\"\nname: \"Synthetic reminder\"\ntrigger: {\"at\": \"2030-01-01T19:04:05-08:00\"}\nthread: \"same\"\nsecrets: []\npriority: 2\n---\nSynthetic: remind the owner to read the report.");
    let (code, doc) = fake.json(&[
        loops.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "synthetic-hourly-kick=loop_syn_5",
    ]);
    assert_eq!(code, 0, "{doc:#}");
    fake.assert_only_listed();
    let triage = item(&doc, "/syn-triage.md");
    assert_eq!(triage["action"], "update");
    let script = "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REPO='synthetic-org/other-repo'\n# wizloop: the check\n# Synthetic check: prints the due items in $WIZLOOP_PARAM_REPO, nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n";
    let live_script = "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REPO='synthetic-org/synthetic-repo'\n# wizloop: the check\n# Synthetic check: prints the due items in $WIZLOOP_PARAM_REPO, nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n";
    assert_eq!(
        triage["differences"],
        json!([
            {"field": "name", "file": "Synthetic triage, renamed", "live": "Synthetic triage every ten minutes"},
            {"field": "agent", "file": {"provider": "synthetic-provider", "model": "synthetic-model", "reasoning": "high"}, "live": {"provider": "synthetic-provider", "model": "synthetic-model", "reasoning": "medium"}},
            {"field": "priority", "file": 3, "live": 2},
            {"field": "check", "file": script, "live": live_script},
        ]),
        "secrets in another order are no difference"
    );
    assert_eq!(
        triage["commands"],
        json!([{"argv": argv("loop|update|loop_syn_1|--name|Synthetic triage, renamed [wizloop:syn-triage]|--priority|3|--script-file|@script|--provider|synthetic-provider|--model|synthetic-model|--reasoning|high"), "files": {"@script": script}}])
    );
    let nightly = item(&doc, "/syn-nightly.md");
    assert_eq!(
        nightly["differences"],
        json!([
            {"field": "trigger", "file": {"cron": "0 6 * * *", "timezone": "America/Los_Angeles"}, "live": {"cron": "0 5 * * *", "timezone": "America/Los_Angeles"}},
            {"field": "secrets", "file": [], "live": "all"},
            {"field": "body", "file": "Synthetic: post a short morning note.", "live": "Synthetic: post a short nightly note."},
        ]),
        "every secret and none are never equal"
    );
    assert_eq!(
        nightly["commands"],
        json!([{"argv": argv("loop|update|loop_syn_3|--prompt|Synthetic: post a short morning note.|--cron|0 6 * * *|--timezone|America/Los_Angeles|--secrets|none"), "files": {}}])
    );
    let reminder = item(&doc, "/syn-reminder.md");
    assert_eq!(
        reminder["differences"],
        json!([{"field": "priority", "file": 2, "live": 1}]),
        "one instant, two spellings"
    );
    assert_eq!(
        reminder["commands"],
        json!([{"argv": argv("loop|update|loop_syn_4|--priority|2"), "files": {}}])
    );
    assert_eq!(reminder["paused"], true);

    let output = fake.run(&[
        loops.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "synthetic-hourly-kick=loop_syn_5",
    ]);
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(
        text.contains(&format!(
            "{}/syn-reminder.md: priority: 1 -> 2\n",
            loops.display()
        )),
        "{text}"
    );
}

#[test]
fn plan_refuses_what_the_adapter_cannot_do() {
    type Case<'a> = (&'a str, &'a str, &'a [&'a str], &'a [(&'a str, &'a str)]);
    let cases: [Case; 8] = [
        (
            "syn-delivery.md",
            "---\nid: \"syn-delivery\"\nname: \"Synthetic delivery\"\ntrigger: {\"cron\": \"0 9 * * *\", \"timezone\": \"UTC\"}\nthread: \"new\"\n---\nSynthetic: route.",
            &[],
            &[("cf-update-webhook", "trigger")],
        ),
        (
            "syn-reminder.md",
            "---\nid: \"syn-reminder\"\nname: \"Synthetic reminder\"\ntrigger: {\"at\": \"2030-01-02T03:04:05Z\"}\nthread: \"new\"\npriority: 1\n---\nSynthetic: remind the owner to read the report.",
            &[],
            &[("cf-update-thread", "thread")],
        ),
        (
            "syn-triage.md",
            "---\nid: \"syn-triage\"\nname: \"Synthetic triage every ten minutes\"\ntrigger: {\"cron\": \"0 9 * * *\", \"timezone\": \"UTC\"}\nthread: \"new\"\nagent: {\"provider\": \"synthetic-provider\", \"model\": \"synthetic-model\", \"reasoning\": \"medium\"}\n---\nSynthetic: triage.",
            &[],
            &[("cf-update-remove-check", "check")],
        ),
        (
            "syn-triage.md",
            "---\nid: \"syn-triage\"\nname: \"Synthetic triage every ten minutes\"\ntrigger: {\"cron\": \"*/10 * * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"check\", \"timeout\": 60}\nthread: \"new\"\n---\nSynthetic: triage.",
            &[],
            &[("cf-update-remove-agent", "agent")],
        ),
        (
            "syn-reminder.md",
            "---\nid: \"syn-reminder\"\nname: \"Synthetic reminder\"\ntrigger: {\"in\": \"30m\"}\nthread: \"same\"\n---\nSynthetic: remind.",
            &[],
            &[("cf-in-existing", "trigger.in")],
        ),
        (
            "past.md",
            "---\nid: \"past\"\nname: \"Synthetic past\"\ntrigger: {\"at\": \"2001-01-02T03:04:05Z\"}\nthread: \"same\"\n---\nSynthetic: too late.",
            &[],
            &[("cf-at-past", "trigger.at")],
        ),
        (
            "syn-nightly.md",
            "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"new\"\nsecrets: \"all\"\n---\nSynthetic: post a short nightly note.",
            &["--adopt", "syn-nightly=loop_syn_5"],
            &[("cf-adopt-binding", "id")],
        ),
        (
            "other.md",
            "---\nid: \"other\"\nname: \"Synthetic other\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\n---\nSynthetic: another project's loop.",
            &["--adopt", "other=loop_syn_6"],
            &[("cf-adopt-binding", "id")],
        ),
    ];
    for (name, text, extra, want) in cases {
        let fake = Fake::new();
        let path = fake.write(name, text);
        fake.write("check", "#!/bin/sh\nexit 0\n");
        let mut args = vec![path.to_str().unwrap(), "--project", PROJECT];
        args.extend(extra);
        let (code, doc) = fake.json(&args);
        assert_eq!(code, 5, "{name}: {doc:#}");
        fake.assert_only_listed();
        let item = &doc["items"][0];
        assert_eq!(
            (&item["action"], &item["commands"]),
            (&json!("refused"), &json!([])),
            "{name}"
        );
        let want: Vec<(String, String)> = want
            .iter()
            .map(|(c, f)| ((*c).into(), (*f).into()))
            .collect();
        assert_eq!(codes(item), want, "{name}");
    }
    let fake = Fake::new();
    let path = fake.write("syn-nightly.md", "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"new\"\nsecrets: \"all\"\n---\nSynthetic: post a short nightly note.");
    let (_, doc) = fake.json(&[
        path.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "syn-nightly=loop_syn_2",
    ]);
    assert_eq!(
        doc["items"][0]["refusals"][0]["message"],
        "the binding to Cloudroom loop loop_syn_2 cannot be used: it already carries a marker"
    );
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!((code, &doc["items"][0]["action"]), (0, &json!("none")));
    assert_eq!(
        doc["unmanaged"],
        json!([{"loop": "loop_syn_5", "name": "Synthetic hourly kick"}])
    );
    assert_eq!(
        doc["orphans"],
        json!([{"loop": "loop_syn_1", "id": "syn-triage"}, {"loop": "loop_syn_2", "id": "syn-delivery"}, {"loop": "loop_syn_4", "id": "syn-reminder"}])
    );
}

#[test]
fn plan_refuses_a_marker_two_loops_carry() {
    let row = |id: &str| json!({"id": id, "project_id": PROJECT, "name": "Synthetic twin [wizloop:twin]", "cron": "0 9 * * *", "timezone": "UTC", "run_at": null, "webhook": false, "new_thread": true, "script": null, "agent": null, "secrets": [], "priority": 3, "prompt": "Synthetic.", "enabled": true});
    let fake = Fake::answering(
        json!({"argv": ["loop", "list", "--json"], "stdout": json!({"automations": [row("loop_syn_8"), row("loop_syn_9")]}).to_string()}),
    );
    let path = fake.write("twin.md", "---\nid: \"twin\"\nname: \"Synthetic twin\"\ntrigger: {\"cron\": \"0 9 * * *\", \"timezone\": \"UTC\"}\nthread: \"new\"\n---\nSynthetic.");
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(code, 5);
    assert_eq!(
        codes(&doc["items"][0]),
        vec![("cf-duplicate-marker".into(), "id".into())]
    );
    assert_eq!(doc["items"][0]["loop"], Value::Null);
}

#[test]
fn plan_stops_before_planning_when_a_read_fails() {
    let fake = Fake::answering(
        json!({"argv": ["loop", "list", "--json"], "stderr": "Error: synthetic failure", "exit": 1}),
    );
    let path = fake.write("a.md", "---\nid: \"a\"\nname: \"Synthetic\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\n---\nSynthetic.");
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(
        (code, &doc["schema"], &doc["error"]["kind"]),
        (1, &json!("openwiz.cli-error.v1"), &json!("read_failed"))
    );
    let fake = Fake::answering(
        json!({"argv": ["loop", "list", "--json"], "stdout": "{\"automations\": [{\"id\": \"x\", \"id\": \"y\"}]}"}),
    );
    let path = fake.write("a.md", "---\nid: \"a\"\nname: \"Synthetic\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\n---\nSynthetic.");
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(
        (code, &doc["error"]["kind"]),
        (1, &json!("read_failed")),
        "a duplicate key refuses the list"
    );

    let fake = Fake::new();
    let missing = fake.dir().join("missing.md");
    let (code, doc) = fake.json(&[missing.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!((code, &doc["error"]["kind"]), (1, &json!("read_failed")));
    assert_eq!(fake.calls(), Vec::<Value>::new(), "no room-cli call");
    let path = fake.write("a.md", "---\nid: \"a\"\nname: \"Synthetic\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\n---\nSynthetic.");
    let (code, doc) = fake.json(&[
        path.to_str().unwrap(),
        "--project",
        PROJECT,
        "--adopt",
        "b=loop_syn_5",
    ]);
    assert_eq!((code, &doc["error"]["kind"]), (2, &json!("usage")));
    assert_eq!(fake.calls(), Vec::<Value>::new(), "no room-cli call");
}

#[test]
fn a_refused_checks_params_still_count_as_used() {
    let fake = Fake::new();
    fake.write("slow/check", "#!/bin/sh\necho \"$WIZLOOP_PARAM_REPO\"\n");
    let path = fake.write("slow.md", "---\nid: \"slow\"\nname: \"Synthetic slow\"\ntrigger: {\"cron\": \"0 9 * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"slow/check\", \"timeout\": 901}\nthread: \"new\"\nparams: {\"repo\": \"synthetic-org/synthetic-repo\"}\n---\nSynthetic.");
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(code, 5);
    assert_eq!(
        codes(&doc["items"][0]),
        vec![("bad-timeout".into(), "check.timeout".into())]
    );
}

#[test]
fn a_live_setting_the_adapter_does_not_map_is_reported() {
    let row = json!({"id": "loop_syn_8", "project_id": PROJECT, "name": "Synthetic delivery [wizloop:syn-delivery]", "cron": null, "timezone": null, "run_at": null, "webhook": true, "new_thread": true, "script": null, "agent": null, "secrets": [], "priority": 4, "prompt": "Synthetic: route each request that arrived to its owner.", "enabled": true, "budget_synthetic": {"max_runs": 3}});
    let fake = Fake::answering(
        json!({"argv": ["loop", "list", "--json"], "stdout": json!({"automations": [row]}).to_string()}),
    );
    let (_, text) = ACCOUNT_FILES[2];
    let path = fake.write("syn-delivery.md", text);
    let (code, doc) = fake.json(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(code, 0, "{doc:#}");
    let item = &doc["items"][0];
    assert_eq!(
        (&item["action"], &item["differences"]),
        (&json!("none"), &json!([]))
    );
    let notes: Vec<&str> = item["notes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| n.as_str().unwrap())
        .collect();
    assert!(
        notes
            .iter()
            .any(|n| n.contains("budget_synthetic") && n.contains("not map")),
        "{notes:?}"
    );
    let output = fake.run(&[path.to_str().unwrap(), "--project", PROJECT]);
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("budget_synthetic")
    );
}

#[test]
fn human_output_escapes_terminal_controls_and_json_keeps_them() {
    const ESC: char = '\u{1b}';
    let mut list: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("tests/fake-room-cli/loops/list.json")).unwrap(),
    )
    .unwrap();
    list["automations"][4]["name"] = json!("Synthetic \u{1b}[2J\u{1b}[Hkick");
    let fake =
        Fake::answering(json!({"argv": ["loop", "list", "--json"], "stdout": list.to_string()}));
    let body = "Synthetic: \u{1b}[2J\u{1b}[Hforged\nsecond \u{202e}line.";
    let nightly = fake.write(
        "loops/syn-nightly.md",
        &format!("---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {{\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}}\nthread: \"new\"\nsecrets: \"all\"\n---\n{body}"),
    );
    let hook = fake.write(
        &format!("loops/hook{ESC}[2J.md"),
        &format!("---\nid: \"hook\"\nname: \"Synthetic hook\"\ntrigger: {{\"webhook\": true}}\nthread: \"new\"\n---\n{body}\n"),
    );
    let args = [
        nightly.to_str().unwrap(),
        hook.to_str().unwrap(),
        "--project",
        PROJECT,
    ];
    let output = fake.run(&args);
    assert_eq!(output.status.code(), Some(0));
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(
        !text.contains(ESC) && !text.contains('\u{202e}'),
        "{text:?}"
    );
    assert!(
        text.contains("forged\nsecond"),
        "a preview keeps its line breaks: {text:?}"
    );
    let (_, doc) = fake.json(&args);
    let nightly_item = item(&doc, "/syn-nightly.md");
    assert_eq!(
        nightly_item["commands"][0]["argv"][4], body,
        "JSON keeps the original"
    );
    assert_eq!(
        item(&doc, "[2J.md")["commands"][0]["files"]["@prompt"],
        format!("{body}\n")
    );
    assert!(doc["unmanaged"][0]["name"].as_str().unwrap().contains(ESC));
    let start = text.find("  room-cli 'loop' 'update'").unwrap() + "  room-cli ".len();
    let command = shell_command(&text[start..]);
    let shell = fake.dir().join("shell");
    super::dirs::private_dir_all(shell.join("bin")).unwrap();
    let recorder = shell.join("bin/room-cli");
    fs::write(
        &recorder,
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$0.calls\"\nexit 97\n",
    )
    .unwrap();
    fs::set_permissions(&recorder, fs::Permissions::from_mode(0o700)).unwrap();
    let script = fake.write(
        "shell/argv.sh",
        &format!(
            "[ \"$(command -v room-cli)\" = '{}' ] || exit 3\nset -- {command}\nprintf '%s\\0' \"$@\"\n",
            recorder.display()
        ),
    );
    let run = std::process::Command::new("/bin/sh")
        .arg(&script)
        .env_clear()
        .env("PATH", shell.join("bin"))
        .env("HOME", &shell)
        .current_dir(&shell)
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap();
    assert_eq!(
        fs::read_to_string(shell.join("bin/room-cli.calls")).ok(),
        None,
        "the script ran room-cli: {command:?}"
    );
    assert!(
        run.status.success() && run.stderr.is_empty(),
        "{run:?}: {command:?}"
    );
    let words: Vec<String> = String::from_utf8(run.stdout)
        .unwrap()
        .split_terminator('\0')
        .map(str::to_owned)
        .collect();
    assert_eq!(
        json!(words),
        nightly_item["commands"][0]["argv"],
        "{command:?}"
    );
    let missing = fake.dir().join(format!("gone{ESC}[2J.md"));
    let output = fake.run(&[missing.to_str().unwrap(), "--project", PROJECT]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(
        stderr.contains("gone") && !stderr.contains(ESC),
        "{stderr:?}"
    );
    let option = format!("--kick{ESC}[2J");
    let output = fake.run(&[&option, "--project", PROJECT, "--json"]);
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(
        stderr.starts_with("openwiz: usage: ")
            && stderr.contains("--kick")
            && !stderr.contains(ESC),
        "{stderr:?}"
    );
    let doc: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(
        doc["error"]["message"].as_str().unwrap().contains(&option),
        "{doc}"
    );
}

fn shell_command(text: &str) -> &str {
    let (mut single, mut double, mut inner, mut escaped) = (false, false, false, false);
    for (i, c) in text.char_indices() {
        match c {
            _ if escaped => escaped = false,
            '\'' if single => single = false,
            _ if single => {}
            '\'' if double => inner = !inner,
            _ if inner => {}
            '\\' => escaped = true,
            '"' => double = !double,
            '\'' => single = true,
            '\n' if !double => return &text[..i],
            _ => {}
        }
    }
    text
}

#[test]
fn a_multibyte_delay_is_refused_and_the_other_files_still_plan() {
    let fake = Fake::new();
    let bad = fake.write("example.md", "---\nid: \"example\"\nname: \"Synthetic\"\ntrigger: {\"in\": \"30分\"}\nthread: \"same\"\n---\nSynthetic.");
    let good = fake.write("good.md", "---\nid: \"good\"\nname: \"Synthetic good\"\ntrigger: {\"webhook\": true}\nthread: \"new\"\n---\nSynthetic.");
    let (code, doc) = fake.json(&[
        bad.to_str().unwrap(),
        good.to_str().unwrap(),
        "--project",
        PROJECT,
    ]);
    assert_eq!(code, 5);
    assert_eq!(
        codes(&doc["items"][0]),
        vec![("bad-in".into(), "trigger.in".into())]
    );
    assert_eq!(doc["items"][1]["action"], "create");
}
