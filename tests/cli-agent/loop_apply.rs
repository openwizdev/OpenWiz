use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use super::{ROOT, Sandbox, dirs, fixture_cli, place, schema};

const PROJECT: &str = "prj_syn_0001";
const LIST: [&str; 3] = ["loop", "list", "--json"];
const WEBHOOK_CREATE: &str = "loop|create|--name|Wake on a delivery [wizloop:webhook-new]|--prompt-file|@prompt|--webhook|--new-thread|--priority|4|--secrets|none";
const WEBHOOK_PROMPT: &str = "Read the requests that arrived and route each one to its owner.\n";

struct Room(
    PathBuf,
    #[allow(
        dead_code,
        reason = "held only so its Drop removes the sandbox when the Room goes"
    )]
    Sandbox,
);

impl Room {
    fn new(before: Vec<Value>, after: Vec<Value>) -> Self {
        let sandbox = Sandbox::new();
        let root = sandbox.0.clone();
        let bin = root.join("bin");
        for (name, responses) in [("before.json", before), ("after.json", after)] {
            fs::write(
                root.join(name),
                json!({"synthetic_assumptions": ["LC5 synthetic loop answers"], "responses": responses})
                    .to_string(),
            )
            .unwrap();
        }
        fs::write(
            bin.join("fake-room-cli.scenario"),
            root.join("before.json").to_str().unwrap(),
        )
        .unwrap();
        std::os::unix::fs::symlink(
            env!("CARGO_BIN_EXE_fake-room-cli"),
            bin.join("fake-room-cli"),
        )
        .unwrap();
        fs::remove_file(bin.join("room-cli")).unwrap();
        let b = bin.display();
        let after = root.join("after.json");
        let stat = if cfg!(target_os = "macos") {
            "/usr/bin/stat -f '%Lp'"
        } else {
            "/usr/bin/stat -c '%a'"
        };
        place::place_script(
            &bin.join("room-cli"),
            &format!(
                r#"#!/bin/sh
set -e
previous=
for arg do
  case "$previous" in --prompt-file|--script-file)
    printf '%s\n' "$previous" >> '{b}/file-modes.log'
    {stat} "${{arg%/*}}" "$arg" >> '{b}/file-modes.log';;
  esac
  previous=$arg
done
if [ -e '{b}/loop-writes.log' ]; then
  printf '%s' '{}' > '{b}/fake-room-cli.scenario'
fi
exec '{b}/fake-room-cli' "$@"
"#,
                after.display()
            ),
        );
        dirs::private_dir(root.join("tmp")).unwrap();
        Self(root, sandbox)
    }

    fn listing(before: &Value, after: &Value) -> Self {
        Self::new(vec![list(before), accept()], vec![list(after), accept()])
    }

    fn dir(&self) -> &Path {
        &self.0
    }

    fn write(&self, rel: &str, text: &str) -> String {
        let path = self.0.join(rel);
        dirs::private_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, text).unwrap();
        path.to_str().unwrap().to_owned()
    }

    fn run_env(&self, args: &[&str], env: &[(&str, &str)]) -> Output {
        Command::new("/bin/sh")
            .args(["-c", "umask 000; exec \"$@\"", "openwiz-test"])
            .arg(fixture_cli())
            .args(args)
            .env_clear()
            .env("PATH", self.0.join("bin"))
            .env("HOME", self.0.join("home"))
            .env("TMPDIR", self.0.join("tmp"))
            .env("OPENWIZ_STATE_DIR", self.0.join("state"))
            .env("OPENWIZ_FIXTURE_PROGRAM", self.0.join("bin/room-cli"))
            .envs(env.iter().copied())
            .current_dir(&self.0)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    }

    fn apply(&self, args: &[&str]) -> Output {
        let mut all = vec!["loop", "apply"];
        all.extend_from_slice(args);
        all.extend(["--project", PROJECT]);
        self.run_env(&all, &[])
    }

    fn json(&self, args: &[&str]) -> (i32, Value) {
        self.json_env(args, &[])
    }

    fn json_env(&self, args: &[&str], env: &[(&str, &str)]) -> (i32, Value) {
        let mut all = vec!["loop", "apply"];
        all.extend_from_slice(args);
        if !args.contains(&"--project") {
            all.extend(["--project", PROJECT]);
        }
        all.push("--json");
        let output = self.run_env(&all, env);
        let code = output.status.code().unwrap();
        (code, document(&output, code))
    }

    fn calls(&self) -> Vec<Value> {
        fs::read_to_string(self.0.join("bin/invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }

    fn writes(&self) -> Vec<Value> {
        fs::read_to_string(self.0.join("bin/loop-writes.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }

    fn assert_write(&self, command: &str, files: Value, read_back: bool) {
        let writes = self.writes();
        assert_eq!(writes.len(), 1, "one write, never retried: {writes:#?}");
        let expected: Vec<&str> = command
            .split('|')
            .enumerate()
            .map(|(i, word)| {
                if matches!(word, "@prompt" | "@script") {
                    let path = writes[0]["argv"][i].as_str().unwrap();
                    assert!(
                        Path::new(path).starts_with(self.dir().join("tmp")),
                        "{path}"
                    );
                    assert!(!Path::new(path).exists(), "{path} was left behind");
                    path
                } else {
                    word
                }
            })
            .collect();
        let expected = json!(expected);
        assert_eq!(writes, vec![json!({"argv": expected, "files": files})]);
        let mut calls = vec![json!(LIST), expected];
        if read_back {
            calls.push(json!(LIST));
        }
        assert_eq!(self.calls(), calls);
        self.assert_no_temporary_files();
    }

    fn assert_no_temporary_files(&self) {
        let left: Vec<PathBuf> = fs::read_dir(self.0.join("tmp"))
            .unwrap()
            .map(|e| e.unwrap().path())
            .collect();
        assert_eq!(left, Vec::<PathBuf>::new(), "apply left files behind");
    }
}

fn document(output: &Output, code: i32) -> Value {
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    assert!(
        stdout.ends_with('\n') && stdout.lines().count() == 1,
        "{stdout}\n{}",
        String::from_utf8_lossy(&output.stderr)
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
    doc
}

fn contract(name: &str) -> Value {
    serde_json::from_str(&fs::read_to_string(Path::new(ROOT).join("contracts").join(name)).unwrap())
        .unwrap()
}

fn fixture(name: &str) -> String {
    Path::new(ROOT)
        .join("contracts/fixtures/wizloops/valid")
        .join(name)
        .to_str()
        .unwrap()
        .to_owned()
}

fn account() -> Value {
    serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join("tests/fake-room-cli/loops/list.json")).unwrap(),
    )
    .unwrap()
}

fn changed(id: &str, change: impl Fn(&mut Value)) -> Value {
    let mut list = account();
    for item in list["automations"].as_array_mut().unwrap() {
        if item["id"] == id {
            change(item);
        }
    }
    list
}

fn with(item: Value) -> Value {
    let mut list = account();
    list["automations"].as_array_mut().unwrap().push(item);
    list
}

fn list(doc: &Value) -> Value {
    json!({"argv": LIST, "stdout": doc.to_string()})
}

fn accept() -> Value {
    json!({"any_loop_write": "update", "stdout": "Synthetic loop updated\n"})
}

fn argv(words: &str) -> Value {
    json!(words.split('|').collect::<Vec<_>>())
}

fn triage(room: &Room, priority: u8) -> String {
    room.write(
        "loops/syn-triage/check",
        "#!/bin/sh\n# Synthetic check: prints the due items in $WIZLOOP_PARAM_REPO, nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n",
    );
    room.write(
        "loops/syn-triage.md",
        &format!("---\nid: \"syn-triage\"\nname: \"Synthetic triage every ten minutes\"\ntrigger: {{\"cron\": \"*/10 * * * *\", \"timezone\": \"UTC\"}}\ncheck: {{\"run\": \"syn-triage/check\", \"timeout\": 60}}\nthread: \"new\"\nagent: {{\"provider\": \"synthetic-provider\", \"model\": \"synthetic-model\", \"reasoning\": \"medium\"}}\nsecrets: [\"SYNTHETIC_TOKEN\", \".env\"]\npriority: {priority}\nparams: {{\"repo\": \"synthetic-org/synthetic-repo\"}}\n---\nSynthetic: triage the due items the check printed below."),
    )
}

#[test]
fn apply_runs_only_its_plans_command_then_reads_back() {
    let room = Room::listing(
        &account(),
        &changed("loop_syn_1", |l| l["priority"] = json!(3)),
    );
    let file = triage(&room, 3);
    room.write(
        "loops/syn-nightly.md",
        "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"UTC\"}\nthread: \"new\"\nsecrets: \"all\"\npriority: 1\n---\nSynthetic: post a short nightly note.",
    );
    let update = argv("loop|update|loop_syn_1|--priority|3");

    let planned = room.run_env(
        &["loop", "plan", "loops", "--project", PROJECT, "--json"],
        &[],
    );
    let planned: Value = serde_json::from_slice(&planned.stdout).unwrap();
    let triage_item = planned["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|i| i["id"] == "syn-triage")
        .unwrap();
    assert_eq!(
        triage_item["commands"],
        json!([{"argv": update, "files": {}}])
    );
    assert_eq!(room.calls(), vec![json!(LIST)], "plan only read");

    let (code, doc) = room.json(&["syn-triage", "--from", &file]);
    assert_eq!(code, 0, "{doc:#}");
    assert_eq!(
        doc,
        json!({
            "schema": "openwiz.loop-apply.v1", "command": "apply", "exit_code": 0,
            "project": PROJECT, "id": "syn-triage", "file": file, "action": "update",
            "loop": "loop_syn_1", "commands": triage_item["commands"],
            "outcome": "updated", "read_back": {"differences": []}, "refusals": [],
        })
    );
    assert_eq!(
        room.calls(),
        vec![json!(LIST), json!(LIST), update.clone(), json!(LIST)]
    );
    assert_eq!(room.writes(), vec![json!({"argv": update, "files": {}})]);
    room.assert_no_temporary_files();
}

#[test]
fn apply_creates_with_the_plans_files_and_removes_them() {
    let script = "#!/bin/sh\n# wizloop: params from the loop file, as data\nexport WIZLOOP_PARAM_REPO='example-org/example-repo'\n# wizloop: the check\n# Prints one line per due item in $WIZLOOP_PARAM_REPO; nothing when none is due.\nif [ -f due.txt ]; then cat due.txt; fi\nexit 0\n";
    let prompt = "Triage the due items for spec 42 that the check printed below.\n";
    let created = json!({"id": "loop_syn_7", "project_id": PROJECT, "session_id": "thr_syn_0001", "name": "Example triage every ten minutes [wizloop:cron-check]", "cron": "*/10 * * * *", "timezone": "UTC", "run_at": null, "webhook": false, "new_thread": true, "script": script, "agent": {"provider": "example-provider", "model": "example-model", "reasoning": "medium"}, "secrets": ["EXAMPLE_TOKEN", ".env"], "priority": 2, "prompt": prompt, "enabled": true, "last_error": null, "last_run_at": null, "next_run_at": null, "runs": 0});
    let room = Room::new(
        vec![
            list(&account()),
            json!({"any_loop_write": "create", "stdout": "Synthetic loop created: loop_syn_7\n"}),
        ],
        vec![list(&with(created))],
    );
    let file = fixture("cron-check.md");
    let (code, doc) = room.json(&["cron-check", "--from", &file]);
    assert_eq!(code, 0, "{doc:#}");
    let create = "loop|create|--name|Example triage every ten minutes [wizloop:cron-check]|--prompt-file|@prompt|--cron|*/10 * * * *|--timezone|UTC|--new-thread|--script-file|@script|--provider|example-provider|--model|example-model|--reasoning|medium|--priority|2|--secrets|EXAMPLE_TOKEN,.env";
    assert_eq!(
        doc,
        json!({
            "schema": "openwiz.loop-apply.v1", "command": "apply", "exit_code": 0,
            "project": PROJECT, "id": "cron-check", "file": file, "action": "create",
            "loop": "loop_syn_7",
            "commands": [{"argv": argv(create), "files": {"@prompt": prompt, "@script": script}}],
            "outcome": "created", "read_back": {"differences": []}, "refusals": [],
        })
    );
    room.assert_write(
        create,
        json!({"--prompt-file": prompt, "--script-file": script}),
        true,
    );
    let modes = fs::read_to_string(room.dir().join("bin/file-modes.log")).unwrap();
    let modes: Vec<_> = modes.lines().collect();
    assert_eq!(modes.len(), 6, "{modes:?}");
    assert_eq!(modes[0], "--prompt-file");
    assert_eq!(modes[3], "--script-file");
    for (i, owner_bits) in [(1, 0o700), (2, 0o600), (4, 0o700), (5, 0o600)] {
        let mode = u32::from_str_radix(modes[i], 8).unwrap();
        assert_eq!(mode & 0o077, 0, "group/other access: {modes:?}");
        assert_eq!(mode & 0o700, owner_bits, "owner access: {modes:?}");
    }
}

#[test]
fn a_created_webhooks_address_reaches_only_the_caller_once() {
    let address = "https://example.invalid/synthetic/hook";
    let created = json!({"id": "loop_syn_7", "project_id": PROJECT, "session_id": "thr_syn_0001", "name": "Wake on a delivery [wizloop:webhook-new]", "cron": null, "timezone": null, "run_at": null, "webhook": true, "new_thread": true, "script": null, "agent": null, "secrets": [], "priority": 4, "prompt": "Read the requests that arrived and route each one to its owner.\n", "enabled": true, "last_error": null, "last_run_at": null, "next_run_at": null, "runs": 0});
    let answers = vec![
        list(&account()),
        json!({"any_loop_write": "create", "webhook": true, "stdout": format!("Synthetic loop created: loop_syn_7\n{address}\n")}),
    ];
    let room = Room::new(answers.clone(), vec![list(&with(created.clone()))]);
    let file = fixture("webhook-new.md");
    let (code, doc) = room.json(&["webhook-new", "--from", &file]);
    assert_eq!(code, 0, "{doc:#}");
    assert_eq!(
        (&doc["outcome"], &doc["loop"], &doc["webhook_address"]),
        (&json!("created"), &json!("loop_syn_7"), &json!(address))
    );
    fn walk(dir: &Path, address: &str) {
        for entry in fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                walk(&path, address);
            } else if !path.ends_with("before.json") {
                let bytes = fs::read(&path).unwrap_or_default();
                assert!(
                    !String::from_utf8_lossy(&bytes).contains(address),
                    "{} holds the address",
                    path.display()
                );
            }
        }
    }
    room.assert_write(
        WEBHOOK_CREATE,
        json!({"--prompt-file": WEBHOOK_PROMPT}),
        true,
    );
    walk(room.dir(), address);
    let room = Room::new(answers, vec![list(&with(created))]);
    let output = room.apply(&["webhook-new", "--from", &file]);
    assert_eq!(output.status.code(), Some(0));
    let text = String::from_utf8(output.stdout).unwrap();
    assert_eq!(text.matches(address).count(), 1, "{text}");
    room.assert_write(
        WEBHOOK_CREATE,
        json!({"--prompt-file": WEBHOOK_PROMPT}),
        true,
    );
}

#[test]
fn a_differing_read_back_is_reported_and_never_retried() {
    let room = Room::listing(&account(), &account());
    let file = triage(&room, 3);
    let (code, doc) = room.json(&["syn-triage", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(doc["outcome"], "different");
    assert_eq!(
        doc["read_back"],
        json!({"differences": [{"field": "priority", "file": 3, "live": 2}]})
    );
    room.assert_write("loop|update|loop_syn_1|--priority|3", json!({}), true);
}

#[test]
fn an_unclear_outcome_is_unknown_and_never_retried() {
    let update = argv("loop|update|loop_syn_1|--priority|3");
    let slow_list = || {
        let mut answer = list(&account());
        answer["delay_ms"] = json!(600);
        answer
    };
    let cases = [
        (
            "the write hangs",
            Some("3000"),
            vec![
                slow_list(),
                json!({"any_loop_write": "update", "hang": true}),
            ],
            vec![],
            vec![json!(LIST), update.clone()],
        ),
        (
            "the write ends without an exit code",
            None,
            vec![
                slow_list(),
                json!({"any_loop_write": "update", "abort": true}),
            ],
            vec![],
            vec![json!(LIST), update.clone()],
        ),
        (
            "the read-back fails",
            None,
            vec![slow_list(), accept()],
            vec![
                json!({"argv": LIST, "stderr": "Error: HTTP 503: Service Unavailable", "exit": 1}),
            ],
            vec![json!(LIST), update.clone(), json!(LIST)],
        ),
    ];
    for (case, timeout, before, after, calls) in cases {
        let room = Room::new(before, after);
        let file = triage(&room, 3);
        let env: Vec<_> = timeout
            .map(|ms| ("OPENWIZ_FIXTURE_READ_TIMEOUT_MS", ms))
            .into_iter()
            .collect();
        let (code, doc) = room.json_env(&["syn-triage", "--from", &file], &env);
        assert_eq!(code, 6, "{case}: {doc:#}");
        assert_eq!(
            (&doc["outcome"], &doc["read_back"], &doc["action"]),
            (&json!("unknown"), &json!(null), &json!("update")),
            "{case}"
        );
        assert_eq!(room.calls(), calls, "{case}");
        assert_eq!(
            room.writes(),
            vec![json!({"argv": update, "files": {}})],
            "{case}"
        );
        room.assert_no_temporary_files();
        if let Ok(pid) = fs::read_to_string(room.dir().join("bin/hang.pid")) {
            assert!(
                !cfg!(target_os = "linux") || !Path::new("/proc").join(pid.trim()).exists(),
                "{case}: the hung room-cli is still running"
            );
        }
    }
}

#[test]
fn a_command_cloudroom_refuses_is_failed_with_its_message_unchanged() {
    let message = "Error: HTTP 409: Synthetic refusal, the loop changed (try later)";
    let room = Room::new(
        vec![
            list(&account()),
            json!({"any_loop_write": "update", "stderr": message, "exit": 1}),
        ],
        vec![],
    );
    let file = triage(&room, 3);
    let (code, doc) = room.json(&["syn-triage", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (&doc["outcome"], &doc["read_back"]),
        (&json!("failed"), &json!(null))
    );
    assert_eq!(
        doc["refusals"],
        json!([{"file": file, "code": "room-cli", "field": "file", "message": message}])
    );
    room.assert_write("loop|update|loop_syn_1|--priority|3", json!({}), false);
}

#[test]
fn apply_writes_nothing_it_should_not() {
    let room = Room::listing(&account(), &account());
    let file = triage(&room, 3);
    let (code, doc) = room.json(&["syn-nightly", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (
            &doc["outcome"],
            &doc["action"],
            &doc["commands"],
            &doc["read_back"]
        ),
        (
            &json!("refused"),
            &json!("refused"),
            &json!([]),
            &json!(null)
        )
    );
    assert_eq!(
        doc["refusals"],
        json!([{"file": file, "code": "apply-id-mismatch", "field": "id", "message": "the file's id is syn-triage, not syn-nightly"}])
    );
    assert_eq!(room.calls(), Vec::<Value>::new());

    let file = room.write(
        "loops/syn-nightly.md",
        "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"same\"\nsecrets: \"all\"\npriority: 3\n---\nSynthetic: post a short nightly note.",
    );
    let (code, doc) = room.json(&["syn-nightly", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (&doc["outcome"], &doc["action"], &doc["loop"]),
        (&json!("refused"), &json!("refused"), &json!("loop_syn_3"))
    );
    assert_eq!(
        doc["refusals"],
        json!([{"file": file, "code": "cf-update-thread", "field": "thread", "message": "Cloudroom cannot change a loop's thread"}])
    );
    assert_eq!(room.calls(), vec![json!(LIST)]);

    room.write(
        "syn-nightly.md",
        "---\nid: \"syn-nightly\"\nname: \"Synthetic nightly note\"\ntrigger: {\"cron\": \"0 5 * * *\", \"timezone\": \"America/Los_Angeles\"}\nthread: \"new\"\nsecrets: \"all\"\npriority: 3\n---\nSynthetic: post a short nightly note.",
    );
    let (code, doc) = room.json(&["syn-nightly"]);
    assert_eq!(code, 0, "{doc:#}");
    assert_eq!(
        doc,
        json!({
            "schema": "openwiz.loop-apply.v1", "command": "apply", "exit_code": 0,
            "project": PROJECT, "id": "syn-nightly", "file": "./syn-nightly.md",
            "action": "none", "loop": "loop_syn_3", "commands": [],
            "outcome": "unchanged", "read_back": null, "refusals": [],
        })
    );
    assert_eq!(room.calls(), vec![json!(LIST), json!(LIST)]);
    assert_eq!(room.writes(), Vec::<Value>::new());
}

#[test]
fn a_failed_read_before_any_write_exits_1_and_writes_nothing() {
    let room = Room::new(
        vec![
            json!({"argv": LIST, "stderr": "Error: HTTP 503: Service Unavailable", "exit": 1}),
            accept(),
        ],
        vec![],
    );
    let (code, doc) = room.json(&["syn-triage", "--from", "missing.md"]);
    assert_eq!(code, 1, "{doc:#}");
    assert_eq!(doc["schema"], "openwiz.cli-error.v1");
    assert_eq!(room.calls(), Vec::<Value>::new());
    let file = triage(&room, 3);
    let (code, doc) = room.json(&["syn-triage", "--from", &file]);
    assert_eq!(code, 1, "{doc:#}");
    assert_eq!(doc["schema"], "openwiz.cli-error.v1");
    assert_eq!(room.calls(), vec![json!(LIST)]);
    assert_eq!(room.writes(), Vec::<Value>::new());
}

#[test]
fn apply_adopts_an_unmarked_loop_by_its_binding() {
    let room = Room::listing(
        &account(),
        &changed("loop_syn_5", |l| {
            l["name"] = json!("Synthetic hourly kick [wizloop:synthetic-hourly-kick]");
        }),
    );
    room.write("loops/synthetic-hourly-kick/check", "#!/bin/sh\nexit 0\n");
    let file = room.write(
        "loops/synthetic-hourly-kick.md",
        "---\nid: \"synthetic-hourly-kick\"\nname: \"Synthetic hourly kick\"\ntrigger: {\"cron\": \"12 * * * *\", \"timezone\": \"UTC\"}\ncheck: {\"run\": \"synthetic-hourly-kick/check\", \"timeout\": 60}\nthread: \"new\"\nsecrets: []\npriority: 3\n---\nSynthetic: nothing to do.",
    );
    let (code, doc) = room.json(&[
        "synthetic-hourly-kick",
        "--from",
        &file,
        "--adopt",
        "other=loop_syn_5",
    ]);
    assert_eq!(code, 2, "{doc:#}");
    assert_eq!(doc["error"]["kind"], "usage");
    assert_eq!(room.calls(), Vec::<Value>::new());

    let (code, doc) = room.json(&[
        "synthetic-hourly-kick",
        "--from",
        &file,
        "--adopt",
        "synthetic-hourly-kick=loop_syn_5",
    ]);
    assert_eq!(code, 0, "{doc:#}");
    let rename =
        argv("loop|update|loop_syn_5|--name|Synthetic hourly kick [wizloop:synthetic-hourly-kick]");
    assert_eq!(
        (&doc["outcome"], &doc["loop"], &doc["read_back"]),
        (
            &json!("updated"),
            &json!("loop_syn_5"),
            &json!({"differences": []})
        )
    );
    assert_eq!(room.calls(), vec![json!(LIST), rename.clone(), json!(LIST)]);
    assert_eq!(room.writes(), vec![json!({"argv": rename, "files": {}})]);
}

#[cfg(target_os = "linux")]
#[test]
fn apply_refuses_a_loop_with_an_unmapped_setting_and_writes_nothing() {
    let mut budget = account()["automations"][2].clone();
    budget["id"] = json!("loop_syn_8");
    budget["name"] = json!("Synthetic budget [wizloop:syn-budget]");
    budget["prompt"] = json!("Synthetic: report the budget.");
    budget["budget_synthetic"] = json!({"max_runs": 3});
    let accounts = with(budget);
    let room = Room::listing(&accounts, &accounts);
    dirs::private_dir_all(room.dir().join("exported")).unwrap();
    let export = room.run_env(
        &[
            "loop",
            "export",
            "--project",
            PROJECT,
            "--out",
            "exported",
            "--json",
        ],
        &[],
    );
    assert_eq!(export.status.code(), Some(0));
    let file = room.dir().join("exported/syn-budget.md");
    let exported = fs::read_to_string(&file).unwrap();
    let file = file.to_str().unwrap();

    let (code, doc) = room.json(&["syn-budget", "--from", file]);
    assert_eq!(code, 0, "{doc:#}");
    assert_eq!(doc["outcome"], "unchanged");

    fs::write(file, exported.replace("priority: 3", "priority: 1")).unwrap();
    let (code, doc) = room.json(&["syn-budget", "--from", file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (
            &doc["outcome"],
            &doc["action"],
            &doc["loop"],
            &doc["read_back"]
        ),
        (
            &json!("refused"),
            &json!("update"),
            &json!("loop_syn_8"),
            &json!(null)
        )
    );
    assert_eq!(
        doc["commands"],
        json!([{"argv": argv("loop|update|loop_syn_8|--priority|1"), "files": {}}])
    );
    assert_eq!(
        doc["refusals"],
        json!([{"file": file, "code": "apply-unmapped", "field": "file", "message": "Cloudroom loop loop_syn_8 carries settings the adapter does not map (budget_synthetic), and nothing shows that a write keeps them; nothing was written"}])
    );
    assert_eq!(room.writes(), Vec::<Value>::new());
    assert_eq!(
        room.calls(),
        vec![json!(LIST), json!(LIST), json!(LIST)],
        "export's list, then one list for each apply"
    );
}

#[test]
fn text_output_previews_the_command_and_never_prints_a_terminal_control() {
    let message = "Error: HTTP 409: Synthetic\u{1b}]52;c;eA==\u{7} refusal";
    let room = Room::new(
        vec![
            list(&account()),
            json!({"any_loop_write": "update", "stderr": message, "exit": 1}),
        ],
        vec![],
    );
    let file = triage(&room, 3);
    let output = room.apply(&["syn-triage", "--from", &file]);
    assert_eq!(output.status.code(), Some(5));
    let text = String::from_utf8(output.stdout).unwrap();
    let err = String::from_utf8(output.stderr).unwrap();
    for out in [&text, &err] {
        assert!(!out.contains('\u{1b}') && !out.contains('\u{7}'), "{out:?}");
    }
    assert!(
        text.contains("  room-cli 'loop' 'update' 'loop_syn_1' '--priority' '3'\n"),
        "{text}"
    );
    assert!(
        text.contains(&format!(
            "{file}: file: Error: HTTP 409: Synthetic?]52;c;eA==? refusal\n"
        )),
        "{text}"
    );
    assert!(
        text.contains(&format!("{file}: failed loop_syn_1\n")),
        "{text}"
    );
    room.assert_write("loop|update|loop_syn_1|--priority|3", json!({}), false);
}

#[test]
fn a_create_cloudroom_refuses_in_a_loop_started_thread_is_not_created() {
    let message = "Error: Synthetic: a thread a loop started cannot create loops";
    let room = Room::new(
        vec![
            list(&account()),
            json!({"any_loop_write": "create", "stderr": message, "exit": 1}),
        ],
        vec![],
    );
    let file = fixture("webhook-new.md");
    let (code, doc) = room.json(&["webhook-new", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (
            &doc["outcome"],
            &doc["action"],
            &doc["loop"],
            &doc["read_back"]
        ),
        (
            &json!("failed"),
            &json!("create"),
            &json!(null),
            &json!(null)
        )
    );
    assert_eq!(
        doc["refusals"],
        json!([{"file": file, "code": "room-cli", "field": "file", "message": message}])
    );
    assert!(doc.get("webhook_address").is_none(), "{doc:#}");
    room.assert_write(
        WEBHOOK_CREATE,
        json!({"--prompt-file": WEBHOOK_PROMPT}),
        false,
    );
}

#[test]
fn an_in_files_run_time_is_checked_against_its_delay() {
    let at = |run_at: Value| json!({"id": "loop_syn_7", "project_id": PROJECT, "session_id": "thr_syn_0001", "name": "Look again in half an hour [wizloop:in-same]", "cron": null, "timezone": null, "run_at": run_at, "webhook": false, "new_thread": false, "script": null, "agent": null, "secrets": [], "priority": 1, "prompt": "Check what changed in the last 6 hours and say it in one line.\n", "enabled": true, "last_error": null, "last_run_at": null, "next_run_at": null, "runs": 0});
    let file = fixture("in-same.md");
    let create =
        || json!({"any_loop_write": "create", "stdout": "Synthetic loop created: loop_syn_7\n"});
    let room = Room::new(
        vec![list(&account()), create()],
        vec![list(&with(at(json!("2099-01-01T00:00:00Z"))))],
    );
    let (code, doc) = room.json(&["in-same", "--from", &file]);
    assert_eq!(code, 5, "{doc:#}");
    assert_eq!(
        (&doc["outcome"], &doc["loop"]),
        (&json!("different"), &json!("loop_syn_7"))
    );
    assert_eq!(
        doc["read_back"],
        json!({"differences": [{"field": "trigger", "file": {"in": "30m"}, "live": {"at": "2099-01-01T00:00:00Z"}}]})
    );
    room.assert_write(
        "loop|create|--name|Look again in half an hour [wizloop:in-same]|--prompt-file|@prompt|--in|30m|--same-thread|--priority|1|--secrets|none",
        json!({"--prompt-file": "Check what changed in the last 6 hours and say it in one line.\n"}),
        true,
    );
    let room = Room::new(
        vec![list(&account()), create()],
        vec![list(&with(at(json!("soon"))))],
    );
    let (code, doc) = room.json(&["in-same", "--from", &file]);
    assert_eq!(code, 6, "{doc:#}");
    assert_eq!(doc["outcome"], "unknown");
    room.assert_write(
        "loop|create|--name|Look again in half an hour [wizloop:in-same]|--prompt-file|@prompt|--in|30m|--same-thread|--priority|1|--secrets|none",
        json!({"--prompt-file": "Check what changed in the last 6 hours and say it in one line.\n"}),
        true,
    );
}
