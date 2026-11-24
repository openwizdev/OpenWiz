use std::{ffi::OsString, io::Write, process::Command};

pub const USAGE: &str = "  openwiz init [--repository OWNER/NAME] [--state-dir DIR] [--json]\n  openwiz init --yes --operation ID [--repository OWNER/NAME] [--state-dir DIR] [--json]\n";
pub const HELP: &str = "Place the factory's private brain from the repository's GitHub visibility\nPrivate code keeps the brain in its own .openwiz/brain; public code gets a private\ncompanion OWNER/NAME-brain linked back to it. There is no placement question.\nThe preview reads GitHub through your gh login and saves one proposal; it writes\nnothing on GitHub. --yes --operation applies exactly that proposal: create and link\nthe companion, create the openwiz label and records v1's five workflow labels,\nopen one visible pull request with the brain's records. An uncertain apply is\nreconciled by applying the same operation. Change the location later through the\nbrain_location setting, with the same rules.\n";

const OPTIONS: [&str; 3] = ["--repository", "--state-dir", "--operation"];

pub fn run(args: &[OsString], out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let json = args.iter().any(|a| a == "--json");
    if !args.is_empty()
        && args
            .iter()
            .all(|a| matches!(a.to_str(), Some("--help" | "-h" | "--json")))
        && args
            .iter()
            .any(|a| matches!(a.to_str(), Some("--help" | "-h")))
    {
        let help = crate::response::help(json, format!("{USAGE}\n{HELP}"));
        return if out
            .write_all(help.as_bytes())
            .and_then(|_| out.flush())
            .is_ok()
        {
            0
        } else {
            1
        };
    }
    if !usable(args) {
        return failure(
            json,
            2,
            "usage",
            "Expected openwiz init [--repository OWNER/NAME] [--yes --operation ID]; see openwiz init --help.",
            out,
            err,
        );
    }
    let Some(result) = init_process(args) else {
        return failure(
            json,
            1,
            "unavailable",
            "The verified packaged init runtime is unavailable; reinstall the matching package.",
            out,
            err,
        );
    };
    let code = result.status.code().unwrap_or(1);
    let Some(report) = outcome(&result.stdout, code) else {
        return failure(
            json,
            1,
            "unavailable",
            "The init outcome is unrecognized; run the same preview again before any apply.",
            out,
            err,
        );
    };
    if json {
        return if out
            .write_all(&result.stdout)
            .and_then(|_| out.flush())
            .is_ok()
        {
            code
        } else {
            1
        };
    }
    if report["schema"] == "openwiz.cli-error.v1" {
        let _ = writeln!(
            err,
            "openwiz: {}",
            report["error"]["message"]
                .as_str()
                .unwrap_or("Init failed.")
        );
        return code;
    }
    if text(&report, out).is_err() {
        return 1;
    }
    code
}

fn usable(args: &[OsString]) -> bool {
    let mut seen = Vec::new();
    let mut items = args.iter();
    while let Some(arg) = items.next() {
        let Some(arg) = arg.to_str() else {
            return false;
        };
        if seen.contains(&arg) {
            return false;
        }
        seen.push(arg);
        if OPTIONS.contains(&arg) {
            if !items.next().is_some_and(|v| v.to_str().is_some()) {
                return false;
            }
        } else if !matches!(arg, "--json" | "--yes") {
            return false;
        }
    }
    seen.contains(&"--yes") == seen.contains(&"--operation")
}

fn text(report: &serde_json::Value, out: &mut dyn Write) -> std::io::Result<()> {
    writeln!(out, "{}", report["report_line"].as_str().unwrap_or(""))?;
    let visibility = report["repository"]["visibility"]["known"]
        .as_str()
        .unwrap_or("unknown");
    writeln!(
        out,
        "Repository: {} ({visibility}, read from GitHub)",
        report["repository"]["full_name"].as_str().unwrap_or("")
    )?;
    writeln!(
        out,
        "Outcome: {}",
        report["outcome"].as_str().unwrap_or("unknown")
    )?;
    for effect in report["effects"].as_array().into_iter().flatten() {
        let what = match effect["kind"].as_str() {
            Some("create_companion") => "Create the private companion",
            Some("link_companion") => "Link the companion to the code",
            Some("create_label") => "Create the missing openwiz and workflow labels",
            Some("merge_pull_request") => "Merge the brain's pull request",
            _ => "Open the brain's pull request",
        };
        writeln!(
            out,
            "  {what} on {}: {}",
            effect["repository"].as_str().unwrap_or(""),
            effect["phase"].as_str().unwrap_or("unknown")
        )?;
    }
    for pull in report["pull_requests"].as_array().into_iter().flatten() {
        writeln!(
            out,
            "Pull request: {}#{} ({})",
            pull["repository"].as_str().unwrap_or(""),
            pull["number"],
            pull["state"].as_str().unwrap_or("unknown")
        )?;
    }
    let id = report["operation_id"].as_str().unwrap_or("");
    writeln!(out, "Operation: {id}")?;
    if report["outcome"] == "proposed" {
        writeln!(
            out,
            "Apply it: openwiz init --yes --operation {id} --repository {}",
            report["repository"]["full_name"].as_str().unwrap_or("")
        )?;
    }
    Ok(())
}

fn failure(
    json: bool,
    code: i32,
    kind: &str,
    message: &str,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    if json {
        let report = serde_json::json!({"schema":"openwiz.cli-error.v1","command":"init","exit_code":code,"error":{"kind":kind,"message":message}});
        if writeln!(out, "{report}").is_err() {
            return 1;
        }
    } else {
        let _ = writeln!(err, "openwiz: {message}");
    }
    code
}

fn outcome(bytes: &[u8], code: i32) -> Option<serde_json::Value> {
    let mut input = serde_json::Deserializer::from_slice(bytes);
    let report = serde::Deserialize::deserialize(&mut input).ok()?;
    input.end().ok()?;
    let report: serde_json::Value = report;
    let object = report.as_object()?;
    match report["schema"].as_str()? {
        "openwiz.setup-onboard.v1" => {
            const KEYS: [&str; 16] = [
                "schema",
                "kind",
                "proof_class",
                "synthetic_assumptions",
                "private_record",
                "operation_id",
                "fingerprint",
                "repository",
                "outcome",
                "reason_code",
                "brain",
                "private_content_written",
                "placement_question",
                "report_line",
                "effects",
                "pull_requests",
            ];
            let hex = |v: &serde_json::Value, n| {
                v.as_str().is_some_and(|s| {
                    s.len() == n && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
                })
            };
            let expected = match report["outcome"].as_str()? {
                "proposed" | "applied" => vec![0],
                "refused" => vec![5, 8],
                "uncertain" => vec![6],
                _ => return None,
            };
            (object.len() == KEYS.len()
                && KEYS.iter().all(|k| object.contains_key(*k))
                && report["kind"] == "init_result"
                && report["placement_question"] == false
                && hex(&report["operation_id"], 32)
                && hex(&report["fingerprint"], 64)
                && report["report_line"].as_str().is_some()
                && report["effects"].is_array()
                && report["pull_requests"].is_array()
                && (report["outcome"] == "refused") == report["brain"].is_null()
                && expected.contains(&code))
            .then_some(report)
        }
        "openwiz.cli-error.v1" => (object.len() == 4
            && report["command"] == "init"
            && report["exit_code"].as_i64()? == i64::from(code)
            && [1, 2, 10].contains(&code)
            && report["error"]["message"].as_str().is_some())
        .then_some(report),
        _ => None,
    }
}

fn init_process(args: &[OsString]) -> Option<std::process::Output> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let tool = exe.parent()?.join("runtime/setup/init.py");
    // SECURITY: only this installed sibling, never PATH or a source checkout fallback.
    let meta = std::fs::symlink_metadata(&tool).ok()?;
    if !meta.is_file() || meta.file_type().is_symlink() {
        return None;
    }
    if tool
        .ancestors()
        .skip(1)
        .any(|p| !std::fs::symlink_metadata(p).is_ok_and(|m| !m.file_type().is_symlink()))
    {
        return None;
    }
    let mut command = Command::new("/usr/bin/python3");
    command.arg("-I").arg(tool).args(args).env_clear();
    for name in [
        "HOME",
        "XDG_STATE_HOME",
        "OPENWIZ_STATE_DIR",
        "PATH",
        "GH_CONFIG_DIR",
    ] {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command.stdin(std::process::Stdio::null()).output().ok()
}
