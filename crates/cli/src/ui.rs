//! `openwiz ui`, and interactive no-argument `openwiz` (terminal contract,
//! "Entry and settings"): both open the visual app's Home by running only
//! the fixed installed sibling `<directory of this executable>/openwiz-terminal`.
//! No shell, `PATH` search, current-directory candidate or other program;
//! no fixture override. The visual pair never enters this crate: the app is
//! a separate executable.
//!
//! `ui --json` prints the `openwiz.terminal-capability.v1` document and
//! starts nothing: no connection, discovery or screen. A `ui` without a
//! terminal on both stdin and stdout is a usage error, never a wait.
//!
//! A module of the `openwiz` binary (`main.rs`), not of the `openwiz-cli`
//! library: it compiles the terminal crate's action registry from that
//! crate's files, which crates linking only the library (the service) never
//! need.

use std::ffi::{OsStr, OsString};
use std::io::Write;
use std::path::{Path, PathBuf};

use openwiz_cli::{EXIT_USAGE, UI_HELP as HELP, UI_USAGE as USAGE, clean};

/// The visual executable's file name.
pub const EXECUTABLE: &str = "openwiz-terminal";

// The terminal crate's action registry, compiled here from its own files
// (no dependency on that crate or the visual pair). Each action module
// registers itself there, so this file never lists actions. `model` is
// re-exported for the action modules; this binary needs only the registry.
// `rustfmt::skip`: rustfmt formats these files in their own crate, and must
// not follow these paths from a tree that copies only this crate's `src/`.
#[allow(dead_code, unused_imports)]
#[rustfmt::skip]
#[path = "../../terminal/src/actions/mod.rs"]
pub mod actions;
#[allow(dead_code)]
#[rustfmt::skip]
#[path = "../../terminal/src/model.rs"]
pub mod model;

/// The capability ids of the actions a registry offers, in its order: only
/// modules whose `register()` returns an action.
pub fn implemented(
    registry: Vec<(actions::ActionId, Option<Box<dyn actions::Action>>)>,
) -> Vec<&'static str> {
    registry
        .into_iter()
        .filter(|(_, action)| action.is_some())
        .map(|(id, _)| id.capability())
        .collect()
}

/// The actions the terminal crate's registry implements in this build.
pub fn implemented_actions() -> Vec<&'static str> {
    implemented(actions::registry())
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UiArgs {
    pub port: Option<u16>,
    pub allowed_host: Option<String>,
    pub json: bool,
    pub help: bool,
}

/// Parses `ui`'s arguments (after `ui`). Values may follow as the next
/// argument or after `=`; a value that looks like a flag is still a value.
pub fn parse_ui(args: &[OsString]) -> Result<UiArgs, String> {
    let mut ui = UiArgs::default();
    if args
        .iter()
        .any(|a| a.as_os_str() == OsStr::new("--help") || a.as_os_str() == OsStr::new("-h"))
    {
        ui.help = true;
        // JSON only from a genuine option position, never a value's.
        ui.json = openwiz_cli::response::Request::for_command("ui", args).json;
        return Ok(ui);
    }
    let mut index = 0;
    while index < args.len() {
        let arg = args[index]
            .to_str()
            .ok_or("an argument is not valid UTF-8")?;
        index += 1;
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) if flag.starts_with("--") => (flag, Some(value.to_owned())),
            _ => (arg, None),
        };
        let mut value = |name: &str| -> Result<String, String> {
            if let Some(v) = inline.clone() {
                return Ok(v);
            }
            let v = args
                .get(index)
                .ok_or(format!("{name} needs a value"))?
                .to_str()
                .ok_or("an argument is not valid UTF-8")?
                .to_owned();
            index += 1;
            Ok(v)
        };
        match flag {
            "--json" if inline.is_some() => return Err("--json takes no value".into()),
            "--json" => ui.json = true,
            "--port" => {
                if ui.port.is_some() {
                    return Err("--port is given more than once".into());
                }
                ui.port = Some(parse_port(&value("--port")?)?);
            }
            "--allowed-host" => {
                if ui.allowed_host.is_some() {
                    return Err("--allowed-host is given more than once".into());
                }
                let name = value("--allowed-host")?;
                if !valid_public_host(&name) {
                    return Err("the allowed host must be a public DNS name: no scheme, path, port, IP address or loopback name".into());
                }
                ui.allowed_host = Some(name);
            }
            other => return Err(format!("ui: unknown argument {}", clean(other))),
        }
    }
    Ok(ui)
}

fn parse_port(value: &str) -> Result<u16, String> {
    const RULE: &str = "--port must be one decimal number from 1 to 65535";
    if value.is_empty()
        || value.len() > 5
        || value.starts_with('0')
        || !value.bytes().all(|b| b.is_ascii_digit())
    {
        return Err(RULE.into());
    }
    value
        .parse::<u32>()
        .ok()
        .filter(|n| (1..=65535).contains(n))
        .map(|n| n as u16)
        .ok_or_else(|| RULE.into())
}

/// The server's configured-public-DNS-name rule (`openwiz-server`'s
/// `SendHost::new`), restated because the CLI must not depend on the server.
pub fn valid_public_host(name: &str) -> bool {
    let dns = name.len() <= 253
        && name.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && !label.starts_with('-')
                && !label.ends_with('-')
                && label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        });
    if !dns {
        return false;
    }
    let lower = name.to_ascii_lowercase();
    let loopback = matches!(
        lower.as_str(),
        "localhost" | "localhost.localdomain" | "ip6-localhost" | "ip6-loopback"
    ) || lower.ends_with(".localhost");
    let last = lower.rsplit('.').next().unwrap_or_default();
    let numeric = last.bytes().all(|b| b.is_ascii_digit()) || last.starts_with("0x");
    !(loopback || numeric || lower.parse::<std::net::IpAddr>().is_ok())
}

/// The fixed sibling of the running executable, by absolute path: never a
/// bare name a `PATH` search could resolve.
pub fn sibling() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|_| "this executable's location is unknown")?;
    if !exe.is_absolute() {
        return Err("this executable's location is not absolute".into());
    }
    let dir = exe
        .parent()
        .ok_or("this executable's directory is unknown")?;
    Ok(dir.join(format!("{EXECUTABLE}{}", std::env::consts::EXE_SUFFIX)))
}

/// A regular file the owner may execute. Never run otherwise.
pub fn usable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

/// The `openwiz.terminal-capability.v1` document, from the sibling's presence
/// and the compiled registry: the sibling is never run for this.
pub fn capability(sibling: Option<&Path>) -> serde_json::Value {
    capability_with(sibling, implemented_actions())
}

/// [`capability`] with a given list of implemented actions.
pub fn capability_with(
    sibling: Option<&Path>,
    implemented: Vec<&'static str>,
) -> serde_json::Value {
    let available = sibling.is_some_and(usable);
    serde_json::json!({
        "schema": "openwiz.terminal-capability.v1",
        "available": available,
        "executable": EXECUTABLE,
        "transport": "loopback-http",
        "actions": if available { implemented } else { Vec::new() },
        "reason": if available {
            serde_json::Value::Null
        } else {
            serde_json::Value::from("not installed beside openwiz")
        },
    })
}

/// Runs the sibling with the parsed settings as distinct arguments, waits
/// for it and returns its exit code.
fn launch(program: &Path, ui: &UiArgs, stderr: &mut dyn Write) -> i32 {
    if !usable(program) {
        let _ = writeln!(
            stderr,
            "openwiz: the terminal app ({EXECUTABLE}) is not installed beside openwiz; nothing was opened"
        );
        return 1;
    }
    let mut command = std::process::Command::new(program);
    if let Some(port) = ui.port {
        command.arg("--port").arg(port.to_string());
    }
    if let Some(host) = &ui.allowed_host {
        command.arg("--allowed-host").arg(host);
    }
    match command.status() {
        Ok(status) => status.code().unwrap_or(1),
        Err(_) => {
            let _ = writeln!(
                stderr,
                "openwiz: the terminal app ({EXECUTABLE}) could not be started; nothing was opened"
            );
            1
        }
    }
}

/// `openwiz ui …`.
pub fn run(
    args: &[OsString],
    terminal: bool,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let ui = match parse_ui(args) {
        Ok(ui) => ui,
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: {why} (see openwiz ui --help)");
            return EXIT_USAGE;
        }
    };
    if ui.help {
        let text = format!("openwiz: the visual terminal app.\n\nUsage:\n{USAGE}\n{HELP}");
        let _ = stdout.write_all(openwiz_cli::response::help(ui.json, text).as_bytes());
        return 0;
    }
    if ui.json {
        let program = sibling().ok();
        let _ = writeln!(stdout, "{}", capability(program.as_deref()));
        return 0;
    }
    if !terminal {
        let _ = writeln!(
            stderr,
            "openwiz: ui needs a terminal on stdin and stdout; nothing was opened (see openwiz ui --help)"
        );
        return EXIT_USAGE;
    }
    match sibling() {
        Ok(program) => launch(&program, &ui, stderr),
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: {why}; nothing was opened");
            1
        }
    }
}
