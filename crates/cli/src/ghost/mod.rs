pub mod context;
pub mod engine;
pub mod http;
pub mod pairing;
pub mod protocol;
pub mod recall;
pub mod stdio;

use std::ffi::OsString;
use std::io::{self, BufRead, Write};
use std::sync::{Arc, Mutex};

use engine::GhostEngine;
use pairing::PairingStore;
use protocol::DEFAULT_PORT;

pub const EXIT_OK: i32 = 0;
pub const EXIT_IO: i32 = 1;
pub const EXIT_USAGE: i32 = 2;
pub const EXIT_NOT_BUILT_YET: i32 = 5;

pub const USAGE: &str = "\
  openwiz ghost serve [--port PORT] [--json]
  openwiz ghost --stdio
  openwiz ghost pair [--json]
  openwiz ghost bench [--source fixtures|log|sent] [--json]
  openwiz ghost forget [--json]
";

pub const HELP: &str = "\
Local ghost text engine and bench (contracts/ghost.v1.md).
Subcommands:
  serve    run the loopback HTTP engine on 127.0.0.1
  --stdio  run the JSON-lines stdio engine (no pairing token)
  pair     print a one-time pairing code for POST /ghost/v1/pair
  bench    replay messages and print the ghost.v1 bench report
  forget   delete the opt-in local ghost event log
";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Subcommand {
    Serve,
    Stdio,
    Pair,
    Bench,
    Forget,
}

impl Subcommand {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Serve => "serve",
            Self::Stdio => "--stdio",
            Self::Pair => "pair",
            Self::Bench => "bench",
            Self::Forget => "forget",
        }
    }

    pub fn parse(token: &str) -> Option<Self> {
        match token {
            "serve" => Some(Self::Serve),
            "--stdio" => Some(Self::Stdio),
            "pair" => Some(Self::Pair),
            "bench" => Some(Self::Bench),
            "forget" => Some(Self::Forget),
            _ => None,
        }
    }
}

pub fn run(args: &[OsString], out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let stdin = io::stdin();
    let mut locked = stdin.lock();
    run_with_io(args, &mut locked, out, err)
}

pub fn run_with_io(
    args: &[OsString],
    input: &mut dyn BufRead,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    let json = args.iter().any(|a| a == "--json");
    if args
        .iter()
        .any(|a| matches!(a.to_str(), Some("--help" | "-h")))
    {
        let text = crate::response::help(json, format!("Usage:\n{USAGE}\n{HELP}"));
        return if out
            .write_all(text.as_bytes())
            .and_then(|()| out.flush())
            .is_ok()
        {
            EXIT_OK
        } else {
            EXIT_IO
        };
    }

    let Some(first) = args.first() else {
        return failure(
            json,
            EXIT_USAGE,
            "usage",
            "ghost needs a subcommand (serve, --stdio, pair, bench, forget); see openwiz ghost --help.",
            out,
            err,
        );
    };

    let Some(first_str) = first.to_str() else {
        return failure(
            json,
            EXIT_USAGE,
            "usage",
            "an argument is not valid UTF-8; see openwiz ghost --help.",
            out,
            err,
        );
    };

    let Some(sub) = Subcommand::parse(first_str) else {
        return failure(
            json,
            EXIT_USAGE,
            "usage",
            &format!(
                "unknown ghost subcommand {}; see openwiz ghost --help.",
                crate::clean(first_str)
            ),
            out,
            err,
        );
    };

    match sub {
        Subcommand::Pair => run_pair(&args[1..], json, out, err),
        Subcommand::Stdio => run_stdio_cmd(&args[1..], json, input, out, err),
        Subcommand::Serve => run_serve(&args[1..], json, out, err),
        Subcommand::Bench | Subcommand::Forget => {
            let message = format!(
                "ghost {} is not built yet (see contracts/ghost.v1.md)",
                sub.as_str()
            );
            failure(json, EXIT_NOT_BUILT_YET, "unavailable", &message, out, err)
        }
    }
}

fn run_pair(args: &[OsString], json: bool, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    for arg in args {
        match arg.to_str() {
            Some("--json") => {}
            Some(other) => {
                return failure(
                    json,
                    EXIT_USAGE,
                    "usage",
                    &format!("unknown option {} for ghost pair", crate::clean(other)),
                    out,
                    err,
                );
            }
            None => {
                return failure(
                    json,
                    EXIT_USAGE,
                    "usage",
                    "an argument is not valid UTF-8; see openwiz ghost --help.",
                    out,
                    err,
                );
            }
        }
    }

    let mut store = match PairingStore::default_file_path() {
        Some(path) => match PairingStore::from_file(path) {
            Ok(s) => s,
            Err(e) => {
                return failure(
                    json,
                    EXIT_IO,
                    "io",
                    &format!("could not open pairing store: {e}"),
                    out,
                    err,
                );
            }
        },
        None => PairingStore::in_memory(),
    };

    let code = match store.issue_code() {
        Ok(c) => c,
        Err(e) => {
            return failure(
                json,
                EXIT_IO,
                "io",
                &format!("could not issue pairing code: {e}"),
                out,
                err,
            );
        }
    };

    let res = if json {
        let payload = serde_json::json!({
            "schema": protocol::SCHEMA_ID,
            "code": code,
        });
        writeln!(out, "{payload}").and_then(|()| out.flush())
    } else {
        writeln!(out, "{code}").and_then(|()| out.flush())
    };
    if res.is_ok() { EXIT_OK } else { EXIT_IO }
}

fn run_stdio_cmd(
    args: &[OsString],
    json: bool,
    input: &mut dyn BufRead,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    if !args.is_empty() {
        return failure(
            json,
            EXIT_USAGE,
            "usage",
            "ghost --stdio takes no extra arguments.",
            out,
            err,
        );
    }
    let mut engine = GhostEngine::system_default();
    match stdio::run_stdio(&mut engine, input, out) {
        Ok(()) => EXIT_OK,
        Err(e) => failure(
            json,
            EXIT_IO,
            "io",
            &format!("ghost --stdio I/O error: {e}"),
            out,
            err,
        ),
    }
}

fn run_serve(args: &[OsString], json: bool, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let mut port = DEFAULT_PORT;
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        let Some(s) = arg.to_str() else {
            return failure(
                json,
                EXIT_USAGE,
                "usage",
                "an argument is not valid UTF-8; see openwiz ghost --help.",
                out,
                err,
            );
        };
        let (flag, inline) = match s.split_once('=') {
            Some((f, v)) if f.starts_with("--") => (f, Some(v)),
            _ => (s, None),
        };
        match flag {
            "--json" if inline.is_none() => {}
            "--port" => {
                let raw = match inline {
                    Some(v) => v,
                    None => match iter.next().and_then(|v| v.to_str()) {
                        Some(v) => v,
                        None => {
                            return failure(
                                json,
                                EXIT_USAGE,
                                "usage",
                                "--port needs a port number.",
                                out,
                                err,
                            );
                        }
                    },
                };
                match raw.parse::<u16>() {
                    Ok(p) => port = p,
                    Err(_) => {
                        return failure(
                            json,
                            EXIT_USAGE,
                            "usage",
                            &format!("--port must be 0..=65535, not {}", crate::clean(raw)),
                            out,
                            err,
                        );
                    }
                }
            }
            "--host" => {
                let raw = match inline {
                    Some(v) => v,
                    None => match iter.next().and_then(|v| v.to_str()) {
                        Some(v) => v,
                        None => {
                            return failure(
                                json,
                                EXIT_USAGE,
                                "usage",
                                "--host needs an address (127.0.0.1 only).",
                                out,
                                err,
                            );
                        }
                    },
                };
                if raw != "127.0.0.1" {
                    return failure(
                        json,
                        EXIT_USAGE,
                        "usage",
                        "ghost serve binds 127.0.0.1 only; non-loopback hosts are refused.",
                        out,
                        err,
                    );
                }
            }
            other => {
                return failure(
                    json,
                    EXIT_USAGE,
                    "usage",
                    &format!("unknown option {} for ghost serve", crate::clean(other)),
                    out,
                    err,
                );
            }
        }
    }

    let listener = match http::bind_loopback(port) {
        Ok(l) => l,
        Err(e) => {
            return failure(
                json,
                EXIT_IO,
                "io",
                &format!("could not bind 127.0.0.1:{port}: {e}"),
                out,
                err,
            );
        }
    };
    let bound = listener
        .local_addr()
        .map(|a| a.to_string())
        .unwrap_or_else(|_| format!("127.0.0.1:{port}"));
    let _ = if json {
        let info = serde_json::json!({
            "schema": protocol::SCHEMA_ID,
            "listening": bound,
        });
        writeln!(out, "{info}").and_then(|()| out.flush())
    } else {
        writeln!(out, "openwiz ghost listening on http://{bound}").and_then(|()| out.flush())
    };

    let engine = Arc::new(Mutex::new(GhostEngine::system_default()));
    match http::serve(listener, engine) {
        Ok(()) => EXIT_OK,
        Err(e) => failure(
            json,
            EXIT_IO,
            "io",
            &format!("ghost serve error: {e}"),
            out,
            err,
        ),
    }
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
        let report = serde_json::json!({
            "schema": "openwiz.cli-error.v1",
            "command": "ghost",
            "exit_code": code,
            "error": { "kind": kind, "message": message }
        });
        if writeln!(out, "{report}").is_err() || out.flush().is_err() {
            return EXIT_IO;
        }
    } else {
        let _ = writeln!(err, "openwiz: {message}");
    }
    code
}
