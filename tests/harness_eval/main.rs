mod harness;

use std::fs;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use harness::{
    Brief, Call, Hook, HookEvent, Outcome, Reply, Scenario, Stop, Unit, baseline, gated, preloaded,
    run,
};

fn dir(name: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openwiz-harness-{name}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn scenario(root: &Path, check: &[&str], units: &[(&str, &str)]) -> Scenario {
    Scenario {
        instruction: "Fix the unit.".to_owned(),
        units: units
            .iter()
            .map(|(id, scope)| Unit {
                id: (*id).to_owned(),
                scope: (*scope).to_owned(),
            })
            .collect(),
        check: check.iter().map(|part| (*part).to_owned()).collect(),
        workspace: root.to_path_buf(),
        constraints_file: root.join("constraints.txt"),
    }
}

fn check(body: &str) -> Vec<String> {
    vec!["python3".to_owned(), "-c".to_owned(), body.to_owned()]
}

fn task(root: &Path, body: &str) -> Scenario {
    scenario(root, &[], &[("task", "fix this unit only")]).with_check(check(body))
}

trait WithCheck {
    fn with_check(self, check: Vec<String>) -> Self;
}

impl WithCheck for Scenario {
    fn with_check(mut self, check: Vec<String>) -> Self {
        self.check = check;
        self
    }
}

fn say(text: &str) -> Reply {
    Reply {
        text: text.to_owned(),
        calls: vec![],
    }
}

fn tool(op: &str, input: &str) -> Reply {
    Reply {
        text: String::new(),
        calls: vec![Call {
            op: op.to_owned(),
            input: input.to_owned(),
        }],
    }
}

fn claim(_: &Brief) -> Reply {
    say("looks good. I am confident.")
}

fn oracle_ok(task: &Scenario) -> bool {
    Command::new(&task.check[0])
        .args(&task.check[1..])
        .current_dir(&task.workspace)
        .status()
        .unwrap()
        .success()
}

fn false_done(outcome: &Outcome, task: &Scenario) -> bool {
    outcome.stop == Stop::Green && !oracle_ok(task)
}

const FAIL: &str =
    "import sys\nsys.stdout.write('task\\tcheck failed\\tcheck:1\\n')\nsys.exit(1)\n";

const CHANGING: &str = "\
from pathlib import Path
import sys
p = Path('n')
n = int(p.read_text()) if p.exists() else 0
p.write_text(str(n + 1))
sys.stdout.write('handlers\\tfail %d\\thandlers/auth.py:%d\\n' % (n, 10 + n))
sys.exit(1)
";

const SAME: &str = "\
import sys
sys.stdout.write('handlers\\ttest_auth_redirect failed\\thandlers/auth.py:88\\n')
sys.exit(1)
";

const MARKER: &str = "\
import os, sys
if os.path.exists('marker'):
    sys.stdout.write('CONSTRAINT: adapters preserve keyword args exactly\\n')
    sys.exit(0)
sys.stdout.write('handlers\\tmarker missing\\thandlers/auth.py:1\\n')
sys.exit(1)
";

const PASS: &str = "import sys\nsys.exit(0)\n";

fn bash_then_done(input: &'static str) -> impl FnMut(&Brief) -> Reply {
    let mut pending = true;
    move |_: &Brief| {
        if pending {
            pending = false;
            tool("bash", input)
        } else {
            say("done")
        }
    }
}

fn write_then_done(input: &'static str) -> impl FnMut(&Brief) -> Reply {
    let mut pending = true;
    move |_: &Brief| {
        if pending {
            pending = false;
            tool("write", input)
        } else {
            say("done")
        }
    }
}

fn times_then_done(count: u32, input: &'static str) -> impl FnMut(&Brief) -> Reply {
    let mut left = count;
    move |_: &Brief| {
        if left > 0 {
            left -= 1;
            tool("bash", input)
        } else {
            say("done")
        }
    }
}

fn clean_exit(brief: &Brief) -> Reply {
    if brief.observations.is_empty() && brief.corrections.is_empty() {
        tool("bash", r#"{"argv":["/usr/bin/true"]}"#)
    } else {
        say("no errors raised")
    }
}

fn recovers(brief: &Brief) -> Reply {
    if brief.observations.iter().any(|line| line.contains("wrote")) {
        return say("done");
    }
    if brief
        .corrections
        .iter()
        .any(|line| line.contains("VERDICT: red"))
    {
        return tool("write", r#"{"path":"marker","body":"ok"}"#);
    }
    claim(brief)
}

#[test]
fn a_confident_claim_is_not_done_when_the_check_fails() {
    let root = dir("claim");
    let task = task(&root, FAIL);
    let before = run(&baseline(), &task, &mut claim);
    let after = run(&gated(), &task, &mut claim);
    assert!(false_done(&before, &task), "{before:?}");
    assert_eq!(after.stop, Stop::Stall);
    assert!(!false_done(&after, &task), "{after:?}");
    assert!(after.reds >= 2, "{after:?}");
}

#[test]
fn a_clean_tool_exit_is_not_a_check() {
    let root = dir("clean-tool");
    let task = task(&root, FAIL);
    let before = run(&baseline(), &task, &mut clean_exit);
    let after = run(&gated(), &task, &mut clean_exit);
    assert!(false_done(&before, &task), "{before:?}");
    assert_ne!(after.stop, Stop::Green);
    assert!(!false_done(&after, &task));
    assert!(after.tool_calls >= 1, "{after:?}");
    assert!(after.checks >= 1, "{after:?}");
}

#[test]
fn a_passing_program_is_green() {
    let root = dir("pass");
    let task = task(&root, PASS);
    let after = run(&gated(), &task, &mut claim);
    assert_eq!(after.stop, Stop::Green);
    assert!(!false_done(&after, &task));
    assert_eq!(after.checks, 1);
}

#[test]
fn a_red_check_names_only_the_failed_unit() {
    let root = dir("batch");
    for (id, bytes) in [
        ("handlers", 2000),
        ("utils", 2000),
        ("types", 2000),
        ("docs", 2000),
    ] {
        fs::write(root.join(id), "u".repeat(bytes)).unwrap();
    }
    let task = scenario(
        &root,
        &[],
        &[
            ("handlers", "fix handlers only"),
            ("utils", "fix utils only"),
            ("types", "fix types only"),
            ("docs", "fix docs only"),
        ],
    )
    .with_check(check(SAME));
    let after = run(&gated(), &task, &mut claim);
    let batch_bytes = 8000;
    assert_eq!(after.corrections_sent, 1, "{after:?}");
    assert!(
        after.correction_text.contains("UNIT: handlers"),
        "{}",
        after.correction_text
    );
    assert!(after.correction_text.contains("VERDICT: red"));
    assert!(
        after
            .correction_text
            .contains("REASON: test_auth_redirect failed")
    );
    assert!(
        after
            .correction_text
            .contains("EVIDENCE: handlers/auth.py:88")
    );
    assert!(after.correction_text.contains("SCOPE: fix handlers only"));
    for other in ["utils", "types", "docs"] {
        assert!(
            !after.correction_text.contains(other),
            "{}",
            after.correction_text
        );
    }
    assert!(
        after.correction_bytes < batch_bytes,
        "{}",
        after.correction_bytes
    );
    let before = run(&baseline(), &task, &mut claim);
    assert_eq!(before.corrections_sent, 0);
    assert!(false_done(&before, &task));
}

#[test]
fn the_third_different_red_escalates() {
    let root = dir("three");
    let task = task(&root, CHANGING);
    let after = run(&gated(), &task, &mut claim);
    assert_eq!(after.stop, Stop::Escalated, "{after:?}");
    assert_eq!(after.checks, 3, "{after:?}");
    assert_eq!(after.corrections_sent, 2, "{after:?}");
    assert!(!false_done(&after, &task));
}

#[test]
fn the_same_evidence_twice_stalls() {
    let root = dir("stall");
    let task = task(&root, SAME);
    let after = run(&gated(), &task, &mut claim);
    assert_eq!(after.stop, Stop::Stall, "{after:?}");
    assert_eq!(after.checks, 2, "{after:?}");
    assert_eq!(after.reds, 2, "{after:?}");
}

#[test]
fn a_fix_after_one_correction_is_green() {
    let root = dir("fix");
    let task = task(&root, MARKER);
    let before = run(&baseline(), &task, &mut recovers);
    assert!(false_done(&before, &task), "{before:?}");
    assert!(!root.join("marker").exists());
    let after = run(&gated(), &task, &mut recovers);
    assert_eq!(after.stop, Stop::Green, "{after:?}");
    assert_eq!(after.corrections_sent, 1, "{after:?}");
    assert!(root.join("marker").exists());
    assert!(!false_done(&after, &task));
}

#[test]
fn an_accepted_result_is_a_constraint_on_the_next_brief() {
    let root = dir("learn");
    let task = task(&root, MARKER);
    fs::write(root.join("marker"), "ok").unwrap();
    let before = run(&baseline(), &task, &mut claim);
    assert!(before.constraints_written.is_empty(), "{before:?}");
    let after = run(&gated(), &task, &mut claim);
    assert_eq!(after.stop, Stop::Green, "{after:?}");
    assert_eq!(
        after.constraints_written,
        vec!["adapters preserve keyword args exactly".to_owned()]
    );
    let mut seen = Vec::new();
    let next = run(&gated(), &task, &mut |brief: &Brief| {
        seen = brief.constraints.clone();
        say("done")
    });
    assert_eq!(
        seen,
        vec!["adapters preserve keyword args exactly".to_owned()]
    );
    assert_eq!(next.constraints_seen, seen);
    assert!(before.constraints_seen.is_empty());
}

#[test]
fn a_migration_delete_stays_closed_when_the_model_is_confident() {
    let root = dir("migrate");
    fs::create_dir_all(root.join("migrations")).unwrap();
    fs::write(root.join("migrations/001.sql"), "create table t(id int);\n").unwrap();
    let task = task(&root, PASS);
    let mut model = |brief: &Brief| {
        if brief.observations.is_empty() {
            tool("delete", r#"{"path":"migrations/001.sql"}"#)
        } else {
            say("I am confident.")
        }
    };
    let before = run(&baseline(), &task, &mut model);
    assert_eq!(before.stop, Stop::Green, "{before:?}");
    assert_eq!(before.hard_applied, 1);
    assert!(!root.join("migrations/001.sql").exists());
    fs::write(root.join("migrations/001.sql"), "create table t(id int);\n").unwrap();
    let after = run(&gated(), &task, &mut model);
    assert_eq!(after.stop, Stop::ClosedLane, "{after:?}");
    assert_eq!(after.hard_applied, 0);
    assert_eq!(after.hard_refused, 1);
    assert!(root.join("migrations/001.sql").exists());
}

#[test]
fn a_contained_write_lands_when_the_check_passes() {
    let root = dir("note");
    let body = "\
import os, sys
sys.exit(0 if os.path.exists('src/note.txt') else 1)
";
    let task = task(&root, body);
    let mut model = |brief: &Brief| {
        if brief.observations.iter().any(|line| line.contains("wrote")) {
            say("done")
        } else {
            tool("write", r#"{"path":"src/note.txt","body":"ok"}"#)
        }
    };
    let before = run(&baseline(), &task, &mut model);
    assert_eq!(before.stop, Stop::Green);
    assert_eq!(fs::read_to_string(root.join("src/note.txt")).unwrap(), "ok");
    fs::remove_file(root.join("src/note.txt")).unwrap();
    let after = run(&gated(), &task, &mut model);
    assert_eq!(after.stop, Stop::Green, "{after:?}");
    assert_eq!(fs::read_to_string(root.join("src/note.txt")).unwrap(), "ok");
    assert_eq!(after.contained_applied, 1);
}

#[test]
fn pre_tool_exit_2_blocks_and_any_other_exit_does_not() {
    let root = dir("hook");
    let script = root.join("hook.py");
    fs::write(
        &script,
        "\
import json, sys
data = json.load(sys.stdin)
code = int(sys.argv[1])
if code == 2 and 'curl' in data.get('input', ''):
    sys.stderr.write('blocked: curl is not allowed\\n')
    sys.exit(2)
sys.exit(0 if code == 2 else code)
",
    )
    .unwrap();
    let curl = r#"{"argv":["python3","-c","open('curled','w').write('1')"],"note":"curl"}"#;
    let mut blocking = gated();
    blocking.hooks = vec![Hook {
        event: HookEvent::PreTool,
        program: "python3".to_owned(),
        args: vec![script.display().to_string(), "2".to_owned()],
    }];
    let blocked = run(&blocking, &task(&root, PASS), &mut bash_then_done(curl));
    assert_eq!(blocked.tool_calls_blocked, 1, "{blocked:?}");
    assert_eq!(blocked.tool_calls, 0);
    assert!(!root.join("curled").exists());
    assert_eq!(blocked.stop, Stop::Green, "{blocked:?}");

    let mut passing = gated();
    passing.hooks = vec![Hook {
        event: HookEvent::PreTool,
        program: "python3".to_owned(),
        args: vec![script.display().to_string(), "1".to_owned()],
    }];
    let allowed = run(&passing, &task(&root, PASS), &mut bash_then_done(curl));
    assert_eq!(allowed.tool_calls_blocked, 0, "{allowed:?}");
    assert_eq!(allowed.tool_calls, 1, "{allowed:?}");
    assert!(root.join("curled").exists());
}

#[test]
fn a_failing_check_is_not_cleared_when_the_stop_hook_stands_down() {
    let root = dir("stop-active");
    let script = root.join("stop.py");
    fs::write(
        &script,
        "\
import json, sys
data = json.load(sys.stdin)
if data.get('stop_hook_active'):
    sys.exit(0)
sys.stderr.write('not yet\\n')
sys.exit(2)
",
    )
    .unwrap();
    let mut config = gated();
    config.hooks = vec![Hook {
        event: HookEvent::Stop,
        program: "python3".to_owned(),
        args: vec![script.display().to_string()],
    }];
    let after = run(&config, &task(&root, FAIL), &mut claim);
    assert_ne!(after.stop, Stop::Green, "{after:?}");
    assert!(
        after.correction_text.contains("REASON: check failed"),
        "{}",
        after.correction_text
    );
    assert!(
        !after.correction_text.contains("not yet"),
        "{}",
        after.correction_text
    );
}

#[test]
fn stop_hook_exit_2_blocks_a_passing_check() {
    let root = dir("stop-block");
    let script = root.join("stop.py");
    fs::write(
        &script,
        "\
import sys
sys.stderr.write('tests have not run\\n')
sys.exit(2)
",
    )
    .unwrap();
    let mut config = gated();
    config.hooks = vec![Hook {
        event: HookEvent::Stop,
        program: "python3".to_owned(),
        args: vec![script.display().to_string()],
    }];
    let after = run(&config, &task(&root, PASS), &mut claim);
    assert_ne!(after.stop, Stop::Green, "{after:?}");
    assert!(
        after.correction_text.contains("tests have not run"),
        "{}",
        after.correction_text
    );
}

#[test]
fn tool_output_over_the_cap_is_truncated() {
    let root = dir("trunc");
    let task = task(&root, PASS);
    let input = r#"{"argv":["python3","-c","print('x'*50000, end='')"]}"#;
    let before = run(&baseline(), &task, &mut bash_then_done(input));
    let after = run(&gated(), &task, &mut bash_then_done(input));
    assert_eq!(before.raw_tool_bytes, 50_000, "{before:?}");
    assert_eq!(before.kept_tool_bytes, 50_000, "{before:?}");
    assert_eq!(before.truncated, 0);
    assert_eq!(after.raw_tool_bytes, 50_000, "{after:?}");
    let marker = format!("\n[truncated {} bytes]", 50_000 - 8 * 1024);
    assert_eq!(after.kept_tool_bytes, 8 * 1024 + marker.len(), "{after:?}");
    assert_eq!(after.truncated, 1);
    assert!(
        after.handoff_bytes <= harness::HANDOFF_MAX_BYTES,
        "{}",
        after.handoff_bytes
    );
    assert!(before.handoff_bytes >= 50_000, "{}", before.handoff_bytes);
}

#[test]
fn the_same_failing_command_twice_stalls() {
    let root = dir("spin");
    let task = task(&root, PASS);
    let mut spin = |_: &Brief| tool("bash", r#"{"argv":["/usr/bin/false"]}"#);
    let mut open = baseline();
    open.measurement_ceiling = Some(30);
    let before = run(&open, &task, &mut spin);
    let after = run(&gated(), &task, &mut spin);
    assert_eq!(before.stop, Stop::Ceiling, "{before:?}");
    assert_eq!(before.tool_calls, 30, "{before:?}");
    assert_eq!(after.stop, Stop::Stall, "{after:?}");
    assert_eq!(after.tool_calls, 2, "{after:?}");
}

#[test]
fn context_is_loaded_for_the_touched_directory_only() {
    let root = dir("jit");
    fs::write(root.join("AGENTS.md"), "R".repeat(500)).unwrap();
    fs::write(root.join("other-AGENTS.md"), "nope").unwrap();
    fs::create_dir_all(root.join("pkg")).unwrap();
    fs::write(root.join("pkg/CLAUDE.md"), "P".repeat(400)).unwrap();
    fs::create_dir_all(root.join("other")).unwrap();
    fs::write(root.join("other/AGENTS.md"), "O".repeat(700)).unwrap();
    fs::create_dir_all(root.join("skills/one")).unwrap();
    fs::write(root.join("skills/one/SKILL.md"), "S".repeat(800)).unwrap();
    let task = task(&root, PASS);
    let input = r#"{"path":"pkg/main.txt","body":"x"}"#;
    let before = run(&baseline(), &task, &mut write_then_done(input));
    let loaded = run(&preloaded(), &task, &mut write_then_done(input));
    let after = run(&gated(), &task, &mut write_then_done(input));
    assert_eq!(before.context_file_bytes, 0, "{before:?}");
    assert_eq!(before.context_files, 0);
    let preloaded_bytes = 500 + 400 + 700 + 800;
    assert_eq!(loaded.context_files, 4, "{loaded:?}");
    assert_eq!(loaded.context_file_bytes, preloaded_bytes, "{loaded:?}");
    assert_eq!(after.context_files, 2, "{after:?}");
    assert_eq!(after.context_file_bytes, 500 + 400, "{after:?}");
    assert!(!after.handoff_text.contains(&"S".repeat(80)));
    assert!(
        loaded.final_brief_bytes > after.final_brief_bytes,
        "{loaded:?} {after:?}"
    );
}

#[test]
fn a_context_file_over_the_cap_is_cut() {
    let root = dir("cap");
    fs::write(root.join("AGENTS.md"), "A".repeat(3_000)).unwrap();
    let task = task(&root, PASS);
    let after = run(
        &gated(),
        &task,
        &mut write_then_done(r#"{"path":"note.txt","body":"n"}"#),
    );
    assert_eq!(after.context_files, 1, "{after:?}");
    assert!(
        after.context_file_bytes < 3_000,
        "{}",
        after.context_file_bytes
    );
    assert!(
        after.context_file_bytes > 2 * 1024,
        "{}",
        after.context_file_bytes
    );
}

#[test]
fn old_tool_results_compact_under_the_byte_budget() {
    let root = dir("compact");
    let task = task(&root, PASS);
    let input = r#"{"argv":["python3","-c","print('y'*3000, end='')"]}"#;
    let before = run(&baseline(), &task, &mut times_then_done(8, input));
    let after = run(&gated(), &task, &mut times_then_done(8, input));
    assert_eq!(before.compactions, 0, "{before:?}");
    assert!(
        before.final_brief_bytes >= 8 * 3_000,
        "{}",
        before.final_brief_bytes
    );
    assert!(after.compactions >= 1, "{after:?}");
    assert!(
        after.final_brief_bytes < before.final_brief_bytes,
        "{after:?} {before:?}"
    );
    assert!(
        after.handoff_bytes <= harness::HANDOFF_MAX_BYTES,
        "{}",
        after.handoff_bytes
    );
    assert!(
        before.handoff_bytes >= 8 * 3_000,
        "{}",
        before.handoff_bytes
    );
}

#[test]
fn a_red_check_with_multiple_failed_units_sends_one_five_line_correction() {
    let root = dir("multi-red");
    let body = "\
import sys
sys.stdout.write('handlers\\tauth failed\\thandlers/auth.py:12\\n')
sys.stdout.write('utils\\tparse failed\\tutils/parse.py:34\\n')
sys.exit(1)
";
    let task = scenario(
        &root,
        &[],
        &[
            ("handlers", "fix handlers only"),
            ("utils", "fix utils only"),
        ],
    )
    .with_check(check(body));
    let after = run(&gated(), &task, &mut claim);
    assert_eq!(
        after.correction_text.lines().count(),
        5,
        "{}",
        after.correction_text
    );
    assert!(
        after.correction_text.contains("UNIT: handlers"),
        "{}",
        after.correction_text
    );
    assert!(
        !after.correction_text.contains("utils"),
        "{}",
        after.correction_text
    );
}

#[test]
fn handoff_pairs_failed_unit_with_its_evidence() {
    let root = dir("handoff-unit");
    let body = "\
import sys
sys.stdout.write('handlers\\tbroken\\thandlers.rs:17\\n')
sys.exit(1)
";
    let task = scenario(
        &root,
        &[],
        &[
            ("utils", "fix utils only"),
            ("handlers", "fix handlers only"),
        ],
    )
    .with_check(check(body));
    let after = run(&gated(), &task, &mut claim);
    assert!(
        after.handoff_text.contains("UNIT: handlers\n"),
        "{}",
        after.handoff_text
    );
    assert!(
        after.handoff_text.contains("EVIDENCE: handlers.rs:17\n"),
        "{}",
        after.handoff_text
    );
}

#[test]
fn driver_probe_runs_without_a_timeout_binary() {
    let root = dir("no-timeout");
    let sys_bin = root.join("sys-bin");
    fs::create_dir_all(&sys_bin).unwrap();
    let python3 = std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .map(|dir| dir.join("python3"))
        .find(|path| path.is_file())
        .expect("python3 must be on PATH");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&python3, sys_bin.join("python3")).unwrap();
    let probe = driver_probe_with_system_path(&sys_bin.display().to_string());
    assert_eq!(probe.start_exit, 0, "{probe:?}");
    assert!(probe.accepted, "{probe:?}");
}

#[test]
fn portable_deadline_kills_a_hanging_process() {
    let python3 = std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .map(|dir| dir.join("python3"))
        .find(|path| path.is_file())
        .expect("python3 must be on PATH");
    let err = run_with_deadline(
        &python3,
        &["-c", "import time; time.sleep(10)"],
        &std::collections::BTreeMap::new(),
        b"",
        std::time::Duration::from_millis(100),
    )
    .unwrap_err();
    assert_eq!(err.kind(), std::io::ErrorKind::TimedOut, "{err}");
}

#[test]
fn the_driver_accepts_exit_0_while_a_program_fails_and_keeps_the_log() {
    let probe = driver_probe();
    assert_eq!(probe.start_exit, 0, "{probe:?}");
    assert_eq!(probe.oracle_exit, 1, "{probe:?}");
    assert!(probe.accepted);
    assert!(!probe.verdict_fields, "{probe:?}");
    assert_eq!(probe.pad_bytes, 50_000, "{probe:?}");
    assert_eq!(probe.log_bytes, 50_022, "{probe:?}");
    let prompt = "Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.";
    assert_eq!(probe.prompt, prompt, "{probe:?}");
    assert_eq!(probe.prompt_bytes, prompt.len());
}

#[test]
fn eval_report_matches_these_runs() {
    let report = measure();
    eprintln!("{report}");
    assert_eq!(report.baseline_false_done, 6);
    assert_eq!(report.gated_false_done, 0);
    assert_eq!(report.driver_accepted_while_oracle_fails, 1);
    assert_eq!(report.driver_pad_bytes, 50_000);
    assert_eq!(report.driver_prompt_bytes, report.driver_prompt.len());
    assert_eq!(report.correction_bytes_before, 0);
    assert_eq!(report.correction_bytes_after, 116);
    assert_eq!(report.checks_before_changing_red, 0);
    assert_eq!(report.checks_after_changing_red, 3);
    assert_eq!(report.checks_after_same_red, 2);
    assert_eq!(report.constraints_before, 0);
    assert_eq!(report.constraints_after, 1);
    assert_eq!(report.hard_applied_before, 1);
    assert_eq!(report.hard_applied_after, 0);
    assert_eq!(report.spin_tools_before, 30);
    assert_eq!(report.spin_tools_after, 2);
    assert_eq!(report.tool_kept_before, 50_000);
    assert_eq!(report.tool_kept_after, 8_216);
    assert_eq!(report.context_bytes_before, 0);
    assert_eq!(report.context_bytes_jit, 900);
    assert_eq!(report.context_bytes_preload, 2_400);
    assert_eq!(report.brief_bytes_before, 24_013);
    assert_eq!(report.brief_bytes_after, 15_073);
    assert_eq!(report.handoff_bytes_before, 24_008);
    assert_eq!(report.handoff_bytes_after, 400);
    assert_eq!(report.model_tokens, None);
}

struct Report {
    baseline_false_done: u32,
    gated_false_done: u32,
    driver_accepted_while_oracle_fails: u32,
    driver_pad_bytes: usize,
    driver_log_bytes: usize,
    driver_prompt: String,
    driver_prompt_bytes: usize,
    correction_bytes_before: usize,
    correction_bytes_after: usize,
    checks_before_changing_red: u32,
    checks_after_changing_red: u32,
    checks_after_same_red: u32,
    constraints_before: usize,
    constraints_after: usize,
    hard_applied_before: u32,
    hard_applied_after: u32,
    spin_tools_before: u32,
    spin_tools_after: u32,
    tool_kept_before: usize,
    tool_kept_after: usize,
    context_bytes_before: usize,
    context_bytes_jit: usize,
    context_bytes_preload: usize,
    brief_bytes_before: usize,
    brief_bytes_after: usize,
    handoff_bytes_before: usize,
    handoff_bytes_after: usize,
    hook_blocks_before: u32,
    hook_blocks_after: u32,
    wall_before_ms: u128,
    wall_after_ms: u128,
    driver_wall_ms: u128,
    model_tokens: Option<u64>,
}

impl std::fmt::Display for Report {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "metric\tbefore\tafter")?;
        writeln!(
            f,
            "false_done_on_6_seeded_claims\t{}\t{}",
            self.baseline_false_done, self.gated_false_done
        )?;
        writeln!(
            f,
            "driver_start_accepted_while_oracle_exits_1\t{}\tdriver unchanged",
            self.driver_accepted_while_oracle_fails
        )?;
        writeln!(
            f,
            "driver_prompt_bytes\t{}\tdriver unchanged",
            self.driver_prompt_bytes
        )?;
        writeln!(
            f,
            "driver_log_bytes_for_50000_payload\t{}\tdriver unchanged",
            self.driver_log_bytes
        )?;
        writeln!(
            f,
            "driver_payload_bytes_kept\t{}\tdriver unchanged",
            self.driver_pad_bytes
        )?;
        writeln!(
            f,
            "correction_bytes_on_4_unit_red\t{}\t{}",
            self.correction_bytes_before, self.correction_bytes_after
        )?;
        writeln!(
            f,
            "checks_on_changing_failure\t{}\t{}",
            self.checks_before_changing_red, self.checks_after_changing_red
        )?;
        writeln!(
            f,
            "checks_on_repeated_evidence\t0\t{}",
            self.checks_after_same_red
        )?;
        writeln!(
            f,
            "constraints_in_next_brief\t{}\t{}",
            self.constraints_before, self.constraints_after
        )?;
        writeln!(
            f,
            "hard_to_reverse_deletes_applied\t{}\t{}",
            self.hard_applied_before, self.hard_applied_after
        )?;
        writeln!(
            f,
            "tool_calls_on_repeated_failure\t{}\t{}",
            self.spin_tools_before, self.spin_tools_after
        )?;
        writeln!(
            f,
            "tool_bytes_kept_from_50000\t{}\t{}",
            self.tool_kept_before, self.tool_kept_after
        )?;
        writeln!(
            f,
            "context_file_bytes_driver_shaped\t{}\t{}",
            self.context_bytes_before, self.context_bytes_jit
        )?;
        writeln!(
            f,
            "context_file_bytes_preload_mode\t{}\tpreload is not the gated default",
            self.context_bytes_preload
        )?;
        writeln!(
            f,
            "final_brief_bytes_after_8x3000\t{}\t{}",
            self.brief_bytes_before, self.brief_bytes_after
        )?;
        writeln!(
            f,
            "handoff_bytes_after_8x3000\t{}\t{}",
            self.handoff_bytes_before, self.handoff_bytes_after
        )?;
        writeln!(
            f,
            "pre_tool_blocks\t{}\t{}",
            self.hook_blocks_before, self.hook_blocks_after
        )?;
        writeln!(
            f,
            "loop_wall_ms\t{}\t{}",
            self.wall_before_ms, self.wall_after_ms
        )?;
        writeln!(f, "driver_probe_wall_ms\t{}\t", self.driver_wall_ms)?;
        writeln!(f, "model_tokens\tnot measured\tnot measured")?;
        Ok(())
    }
}

fn measure() -> Report {
    let mut baseline_false = 0u32;
    let mut gated_false = 0u32;
    let mut wall_before = std::time::Duration::ZERO;
    let mut wall_after = std::time::Duration::ZERO;
    for (name, body, model) in false_done_cases() {
        let root = dir(name);
        let task = task(&root, body);
        let before = run(&baseline(), &task, &mut model());
        baseline_false += u32::from(false_done(&before, &task));
        let after = run(&gated(), &task, &mut model());
        wall_before += before.wall;
        wall_after += after.wall;
        gated_false += u32::from(false_done(&after, &task));
    }

    let batch_root = dir("report-batch");
    for id in ["handlers", "utils", "types", "docs"] {
        fs::write(batch_root.join(id), "u".repeat(2000)).unwrap();
    }
    let batch = scenario(
        &batch_root,
        &[],
        &[
            ("handlers", "fix handlers only"),
            ("utils", "fix utils only"),
            ("types", "fix types only"),
            ("docs", "fix docs only"),
        ],
    )
    .with_check(check(SAME));
    let batch_before = run(&baseline(), &batch, &mut claim);
    let batch_after = run(&gated(), &batch, &mut claim);

    let three_root = dir("report-three");
    let three = task(&three_root, CHANGING);
    let three_before = run(&baseline(), &three, &mut claim);
    let three_after = run(&gated(), &three, &mut claim);
    let same_root = dir("report-same");
    let same = task(&same_root, SAME);
    let same_after = run(&gated(), &same, &mut claim);

    let learn_root = dir("report-learn");
    fs::write(learn_root.join("marker"), "ok").unwrap();
    let learn = task(&learn_root, MARKER);
    let learn_before = run(&baseline(), &learn, &mut claim);
    let learn_after = run(&gated(), &learn, &mut claim);

    let hard_root = dir("report-hard");
    fs::create_dir_all(hard_root.join("migrations")).unwrap();
    fs::write(
        hard_root.join("migrations/001.sql"),
        "create table t(id int);\n",
    )
    .unwrap();
    let hard = task(&hard_root, PASS);
    let mut hard_model = |brief: &Brief| {
        if brief.observations.is_empty() {
            tool("delete", r#"{"path":"migrations/001.sql"}"#)
        } else {
            say("I am confident.")
        }
    };
    let hard_before = run(&baseline(), &hard, &mut hard_model);
    fs::write(
        hard_root.join("migrations/001.sql"),
        "create table t(id int);\n",
    )
    .unwrap();
    let hard_after = run(&gated(), &hard, &mut hard_model);

    let spin_root = dir("report-spin");
    let spin_task = task(&spin_root, PASS);
    let mut spin = |_: &Brief| tool("bash", r#"{"argv":["/usr/bin/false"]}"#);
    let mut open = baseline();
    open.measurement_ceiling = Some(30);
    let spin_before = run(&open, &spin_task, &mut spin);
    let spin_after = run(&gated(), &spin_task, &mut spin);

    let trunc_root = dir("report-trunc");
    let trunc_task = task(&trunc_root, PASS);
    let trunc_input = r#"{"argv":["python3","-c","print('x'*50000, end='')"]}"#;
    let trunc_before = run(&baseline(), &trunc_task, &mut bash_then_done(trunc_input));
    let trunc_after = run(&gated(), &trunc_task, &mut bash_then_done(trunc_input));

    let ctx_root = dir("report-ctx");
    fs::write(ctx_root.join("AGENTS.md"), "R".repeat(500)).unwrap();
    fs::create_dir_all(ctx_root.join("pkg")).unwrap();
    fs::write(ctx_root.join("pkg/CLAUDE.md"), "P".repeat(400)).unwrap();
    fs::create_dir_all(ctx_root.join("other")).unwrap();
    fs::write(ctx_root.join("other/AGENTS.md"), "O".repeat(700)).unwrap();
    fs::create_dir_all(ctx_root.join("skills/one")).unwrap();
    fs::write(ctx_root.join("skills/one/SKILL.md"), "S".repeat(800)).unwrap();
    let ctx = task(&ctx_root, PASS);
    let ctx_input = r#"{"path":"pkg/main.txt","body":"x"}"#;
    let ctx_before = run(&baseline(), &ctx, &mut write_then_done(ctx_input));
    let ctx_preload = run(&preloaded(), &ctx, &mut write_then_done(ctx_input));
    let ctx_after = run(&gated(), &ctx, &mut write_then_done(ctx_input));

    let flood_root = dir("report-flood");
    let flood = task(&flood_root, PASS);
    let flood_input = r#"{"argv":["python3","-c","print('y'*3000, end='')"]}"#;
    let flood_before = run(&baseline(), &flood, &mut times_then_done(8, flood_input));
    let flood_after = run(&gated(), &flood, &mut times_then_done(8, flood_input));

    let hook_root = dir("report-hook");
    let script = hook_root.join("hook.py");
    fs::write(
        &script,
        "\
import json, sys
data = json.load(sys.stdin)
if 'curl' in data.get('input', ''):
    sys.stderr.write('blocked: curl is not allowed\\n')
    sys.exit(2)
sys.exit(0)
",
    )
    .unwrap();
    let hook_task = task(&hook_root, PASS);
    let curl = r#"{"argv":["/usr/bin/true"],"note":"curl"}"#;
    let hook_before = run(&baseline(), &hook_task, &mut bash_then_done(curl));
    let mut hook_config = gated();
    hook_config.hooks = vec![Hook {
        event: HookEvent::PreTool,
        program: "python3".to_owned(),
        args: vec![script.display().to_string()],
    }];
    let hook_after = run(&hook_config, &hook_task, &mut bash_then_done(curl));

    let driver_started = std::time::Instant::now();
    let probe = driver_probe();
    let driver_wall = driver_started.elapsed();

    Report {
        baseline_false_done: baseline_false,
        gated_false_done: gated_false,
        driver_accepted_while_oracle_fails: u32::from(probe.accepted && probe.oracle_exit != 0),
        driver_pad_bytes: probe.pad_bytes,
        driver_log_bytes: probe.log_bytes,
        driver_prompt: probe.prompt,
        driver_prompt_bytes: probe.prompt_bytes,
        correction_bytes_before: batch_before.correction_bytes,
        correction_bytes_after: batch_after.correction_bytes,
        checks_before_changing_red: three_before.checks,
        checks_after_changing_red: three_after.checks,
        checks_after_same_red: same_after.checks,
        constraints_before: learn_before.constraints_written.len(),
        constraints_after: learn_after.constraints_written.len(),
        hard_applied_before: hard_before.hard_applied,
        hard_applied_after: hard_after.hard_applied,
        spin_tools_before: spin_before.tool_calls,
        spin_tools_after: spin_after.tool_calls,
        tool_kept_before: trunc_before.kept_tool_bytes,
        tool_kept_after: trunc_after.kept_tool_bytes,
        context_bytes_before: ctx_before.context_file_bytes,
        context_bytes_jit: ctx_after.context_file_bytes,
        context_bytes_preload: ctx_preload.context_file_bytes,
        brief_bytes_before: flood_before.final_brief_bytes,
        brief_bytes_after: flood_after.final_brief_bytes,
        handoff_bytes_before: flood_before.handoff_bytes,
        handoff_bytes_after: flood_after.handoff_bytes,
        hook_blocks_before: hook_before.tool_calls_blocked,
        hook_blocks_after: hook_after.tool_calls_blocked,
        wall_before_ms: wall_before.as_millis(),
        wall_after_ms: wall_after.as_millis(),
        driver_wall_ms: driver_wall.as_millis(),
        model_tokens: None,
    }
}

type CaseModel = fn() -> Box<dyn FnMut(&Brief) -> Reply>;

fn false_done_cases() -> Vec<(&'static str, &'static str, CaseModel)> {
    vec![
        ("fd-claim", FAIL, || Box::new(claim)),
        ("fd-clean", FAIL, || {
            Box::new(|brief: &Brief| {
                if brief.observations.is_empty() && brief.corrections.is_empty() {
                    tool("bash", r#"{"argv":["/usr/bin/true"]}"#)
                } else {
                    say("no errors raised")
                }
            })
        }),
        ("fd-fix", MARKER, || Box::new(recovers)),
        ("fd-three", CHANGING, || Box::new(claim)),
        ("fd-same", SAME, || Box::new(claim)),
        ("fd-batch", SAME, || Box::new(claim)),
    ]
}

#[derive(Debug)]
struct DriverProbe {
    start_exit: i32,
    oracle_exit: i32,
    accepted: bool,
    verdict_fields: bool,
    pad_bytes: usize,
    log_bytes: usize,
    prompt: String,
    prompt_bytes: usize,
}

fn driver_probe() -> DriverProbe {
    driver_probe_with_system_path("/usr/bin:/bin")
}

fn driver_probe_with_system_path(system_path: &str) -> DriverProbe {
    let root = dir("driver");
    let bin_dir = root.join("bin");
    let repos = root.join("repos/example/site/docs/agents");
    let state = root.join("state");
    fs::create_dir_all(&bin_dir).unwrap();
    fs::create_dir_all(&repos).unwrap();
    fs::create_dir_all(&state).unwrap();
    fs::write(
        repos.join("fleet.md"),
        "# Fleet\n\n| Setting | Value |\n| --- | --- |\n| Harness permission mode | `acceptEdits` |\n",
    )
    .unwrap();
    let approvals = state.join("approvals.json");
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&approvals)
        .unwrap();
    file.write_all(br#"{"example/site":{"claude":"acceptEdits"}}"#)
        .unwrap();
    let argv_path = root.join("argv.txt");
    let harness = bin_dir.join("claude");
    fs::write(
        &harness,
        format!(
            "#!/usr/bin/env python3\nimport os, sys\nopen({argv:?}, 'w').write('\\n'.join(sys.argv))\nn = int(os.environ.get('OPENWIZ_EVAL_PAD', '0'))\nsys.stdout.write('x' * n)\nif n:\n    sys.stdout.write('\\n')\nsys.stdout.write('done: all tests pass\\n')\n",
            argv = argv_path,
        ),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut mode = fs::metadata(&harness).unwrap().permissions();
        mode.set_mode(0o700);
        fs::set_permissions(&harness, mode).unwrap();
    }
    let gh_src = Path::new(env!("CARGO_MANIFEST_DIR")).join("../adapters/local/fixtures/gh");
    let gh = bin_dir.join("gh");
    fs::copy(&gh_src, &gh).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut mode = fs::metadata(&gh).unwrap().permissions();
        mode.set_mode(0o700);
        fs::set_permissions(&gh, mode).unwrap();
    }
    let driver = Path::new(env!("CARGO_MANIFEST_DIR")).join("../adapters/local/driver");
    let env = std::collections::BTreeMap::from([
        (
            "PATH".to_owned(),
            format!("{}:{system_path}", bin_dir.display()),
        ),
        (
            "OPENWIZ_LOCAL_STATE".to_owned(),
            state.display().to_string(),
        ),
        ("OPENWIZ_LOCAL_SETTLE".to_owned(), "2".to_owned()),
        ("OPENWIZ_EVAL_PAD".to_owned(), "50000".to_owned()),
        (
            "OPENWIZ_EVAL_ARGV".to_owned(),
            argv_path.display().to_string(),
        ),
        (
            "FAKE_REPOS".to_owned(),
            root.join("repos").display().to_string(),
        ),
        ("LANG".to_owned(), "C".to_owned()),
    ]);
    let output = run_with_deadline(
        &driver,
        &["start"],
        &env,
        br#"{"repository":"example/site","ticket":7,"skill":"build-ticket","harness":"claude","model":"claude-opus-5-5"}"#,
        std::time::Duration::from_secs(20),
    )
    .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "driver start failed\nstdout: {stdout}\nstderr: {stderr}"
    );
    let parsed: serde_json::Value = serde_json::from_str(stdout.trim()).unwrap();
    let run_id = parsed["run"].as_str().unwrap().to_owned();
    let verdict_fields = ["verdict", "unit", "evidence"]
        .into_iter()
        .all(|key| parsed.get(key).is_some());
    let log = fs::read(state.join(format!("{run_id}.log"))).unwrap_or_default();
    let argv = fs::read_to_string(&argv_path).unwrap_or_default();
    let prompt = argv
        .lines()
        .skip_while(|line| *line != "-p")
        .nth(1)
        .unwrap_or("")
        .to_owned();
    let oracle = Command::new("python3")
        .args(["-c", "import sys; sys.exit(1)"])
        .status()
        .unwrap();
    let _ = run_with_deadline(
        &driver,
        &["stop"],
        &env,
        format!(r#"{{"run":"{run_id}"}}"#).as_bytes(),
        std::time::Duration::from_secs(20),
    );
    DriverProbe {
        start_exit: output.status.code().unwrap_or(1),
        oracle_exit: oracle.code().unwrap_or(1),
        accepted: parsed.get("run").is_some(),
        verdict_fields,
        pad_bytes: log.iter().filter(|byte| **byte == b'x').count(),
        log_bytes: log.len(),
        prompt_bytes: prompt.len(),
        prompt,
    }
}

fn run_with_deadline(
    program: &Path,
    args: &[&str],
    env: &std::collections::BTreeMap<String, String>,
    stdin_bytes: &[u8],
    timeout: std::time::Duration,
) -> std::io::Result<std::process::Output> {
    use std::io::Read;
    let mut child = Command::new(program)
        .args(args)
        .env_clear()
        .envs(env)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()?;
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(stdin_bytes);
    }
    let stdout_handle = child.stdout.take().map(|mut out| {
        std::thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = out.read_to_end(&mut buf);
            buf
        })
    });
    let stderr_handle = child.stderr.take().map(|mut err| {
        std::thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = err.read_to_end(&mut buf);
            buf
        })
    });
    let deadline = std::time::Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait()? {
            let stdout = stdout_handle
                .and_then(|handle| handle.join().ok())
                .unwrap_or_default();
            let stderr = stderr_handle
                .and_then(|handle| handle.join().ok())
                .unwrap_or_default();
            return Ok(std::process::Output {
                status,
                stdout,
                stderr,
            });
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "{} timed out after {}ms",
                    program.display(),
                    timeout.as_millis()
                ),
            ));
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
}
