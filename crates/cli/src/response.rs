//! Process response boundary: select JSON from syntax, preserve existing reports,
//! and supply a declared error only when the command attempted no stdout write.
use std::ffi::OsStr;
use std::io::{self, Write};

#[derive(Debug)]
pub struct Request {
    pub json: bool,
    pub command: &'static str,
}

impl Request {
    pub fn new<S: AsRef<OsStr>>(args: &[S]) -> Self {
        let command = args.first().and_then(|s| s.as_ref().to_str()).unwrap_or("");
        let mut request = Self::for_command(command, args.get(1..).unwrap_or_default());
        request.json |= command == "--json";
        request
    }

    pub fn for_command<S: AsRef<OsStr>>(command: &str, args: &[S]) -> Self {
        let mut json = false;
        let mut preview = false;
        let mut check = false;
        let mut yes = false;
        let mut status = false;
        let mut dry_run = false;
        let mut agent = false;
        let mut index = 0;
        while index < args.len() {
            let bytes = args[index].as_ref().as_encoded_bytes();
            index += 1;
            // Loop's target is a positional value, even when named --json.
            if command == "loop"
                && index == 2
                && args
                    .first()
                    .is_some_and(|a| matches!(a.as_ref().to_str(), Some("on" | "off")))
            {
                continue;
            }
            if bytes == b"--" {
                break;
            }
            let flag = bytes.split(|b| *b == b'=').next().unwrap_or_default();
            let takes_value = match command {
                "ls" => matches!(flag, b"--limit" | b"--offset"),
                "send" => matches!(flag, b"--op-id" | b"--attach" | b"--attachment"),
                "new" => crate::new_thread::is_value_option(flag),
                "ui" => matches!(flag, b"--port" | b"--allowed-host"),
                "fleet" => flag == b"--expect-plan",
                _ => false,
            };
            if command == "new" && flag == b"--status" {
                status = true;
            }
            if takes_value {
                if flag.len() == bytes.len() {
                    index += 1;
                }
                continue;
            }
            // Only an exact ASCII option token selects a switch. Unknown or
            // malformed options do not stop scanning for a later genuine one.
            match bytes {
                b"--json" => json = true,
                b"--preview" => preview = true,
                b"--check" => check = true,
                b"--yes" => yes = true,
                b"--dry-run" => dry_run = true,
                b"--agent" => agent = true,
                _ => {}
            }
        }
        let first = args.first().and_then(|s| s.as_ref().to_str());
        let command = match command {
            "ls" => "ls",
            "show" => "show",
            "send" if check => "send.check",
            "send" if preview => "send.preview",
            "send" => "send",
            "new" if status => "new.status",
            "new" if yes => "new",
            "new" => "new.preview",
            "models" => "models",
            "attachment" => match first {
                Some("add") => "attachment.add",
                Some("ls") => "attachment.ls",
                Some("rm") => "attachment.rm",
                _ => "unknown",
            },
            "fleets" => "fleets",
            "fleet" => match first {
                Some("due") => "fleet.due",
                Some("tick") if dry_run => "fleet.tick.preview",
                Some("tick") => "fleet.tick",
                _ => "fleet",
            },
            "loop" => match first {
                Some("off") => "loop.off",
                Some("on") => "loop.on",
                _ => "unknown",
            },
            "ui" => "ui",
            "help" if agent => "help.agent",
            "help" | "--help" | "-h" => "help",
            _ => "unknown",
        };
        Self { json, command }
    }
}

pub fn help(json: bool, text: String) -> String {
    if json {
        format!(
            "{}\n",
            serde_json::json!({"schema": "openwiz.cli-help.v1", "text": text})
        )
    } else {
        text
    }
}

struct Output<'a> {
    inner: &'a mut dyn Write,
    attempted: bool,
}
impl Write for Output<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.attempted |= !bytes.is_empty();
        self.inner.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

/// This boundary streams existing documents unchanged. Even a failed first
/// write counts as an attempt: never append an error to a broken document.
pub fn run(
    request: &Request,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
    dispatch: impl FnOnce(&mut dyn Write, &mut dyn Write) -> i32,
) -> i32 {
    let mut output = Output {
        inner: stdout,
        attempted: false,
    };
    let code = dispatch(&mut output, stderr);
    if request.json && !output.attempted && code != 0 {
        let (kind, message) = match code {
            2 => (
                "usage",
                "Invalid command arguments or input; see openwiz help --agent.",
            ),
            3 => ("not_found", "The requested target was not found."),
            10 => (
                "store_unavailable",
                "The local operation or attachment store is unavailable.",
            ),
            5 => (
                "unavailable",
                "The request was refused before an outcome report was available.",
            ),
            _ => (
                "read_failed",
                "The command could not read its required source or local context.",
            ),
        };
        let doc = serde_json::json!({
            "schema": "openwiz.cli-error.v1", "command": request.command,
            "exit_code": code, "error": {"kind": kind, "message": message}
        });
        let _ = writeln!(output, "{doc}");
        let _ = output.flush();
    }
    code
}
