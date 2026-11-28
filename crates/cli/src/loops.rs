use crate::state::loops::{Context, SwitchError};
use openwiz_core::ops::Clock;
use std::{ffi::OsString, io::Write};

pub const USAGE: &str = "  openwiz loop off <name> [--json]\n  openwiz loop on <name> [--json]\n";
pub const HELP: &str = "loop off/on <name>\n  Switch one OpenWiz loop by its exact name or ID, recording the trusted operator\n  and time. Off admits no new check or agent; existing effects are kept. Requires\n  verified local repository/project and operator context; otherwise refuses.\n  Waits up to 30 seconds for a running pass; if still busy, retry the command.\n";

pub fn run(
    args: &[OsString],
    context: Option<&Context>,
    clock: &dyn Clock,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    if help_requested(args) {
        return if stdout
            .write_all(
                crate::response::help(
                    crate::response::Request::for_command("loop", args).json,
                    format!("{USAGE}\n{HELP}"),
                )
                .as_bytes(),
            )
            .is_ok()
        {
            0
        } else {
            1
        };
    }
    let Some((enabled, target, json)) = parse(args) else {
        let _ = writeln!(stderr, "openwiz: usage: loop off|on <name> [--json]");
        return 2;
    };
    let result = (|| {
        let context =
            context.ok_or_else(|| SwitchError::from("trusted loop context is unavailable"))?;
        context.switch_with_clock(&target, enabled, clock)
    })();
    match result {
        Ok(event) => {
            let output = if json {
                serde_json::to_string_pretty(&event).unwrap()
            } else {
                format!(
                    "Loop {}: {} (operator {}, at {} ms)",
                    event["loop_id"].as_str().unwrap(),
                    if enabled { "on" } else { "off" },
                    event["actor"].as_str().unwrap(),
                    event["at_ms"]
                )
            };
            if writeln!(stdout, "{output}").is_ok() {
                0
            } else {
                1
            }
        }
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: {why}");
            1
        }
    }
}

pub(crate) fn parse(args: &[OsString]) -> Option<(bool, String, bool)> {
    let strings: Option<Vec<_>> = args.iter().map(|arg| arg.to_str()).collect();
    let strings = strings?;
    let (enabled, target, json) = match strings.as_slice() {
        [command @ ("off" | "on"), target] => (*command == "on", *target, false),
        [command @ ("off" | "on"), target, "--json"] => (*command == "on", *target, true),
        _ => return None,
    };
    (!target.trim().is_empty() && !target.contains('\0'))
        .then(|| (enabled, target.to_owned(), json))
}

pub fn run_local(
    args: &[OsString],
    clock: &dyn Clock,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    if help_requested(args) || parse(args).is_none() {
        return run(args, None, clock, stdout, stderr);
    }
    let context = (|| -> Result<Context, String> {
        let state =
            crate::state::default_state_dir(&|name| std::env::var_os(name)).map_err(|e| e.0)?;
        let checkout = std::env::current_dir().map_err(|_| "cannot identify the local checkout")?;
        crate::state::loops::config::installed(&checkout, &state)
    })();
    match context {
        Ok(context) => run(args, Some(&context), clock, stdout, stderr),
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: {why}");
            1
        }
    }
}

fn help_requested(args: &[OsString]) -> bool {
    let without_json: Vec<_> = args.iter().filter(|a| *a != "--json").collect();
    without_json.len() == 1 && (without_json[0] == "--help" || without_json[0] == "-h")
}
