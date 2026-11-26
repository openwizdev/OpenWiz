use std::{ffi::OsString, io::Write};

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

Status: stubbed in GS1; subcommands exit 5 until built.
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

    let message = format!(
        "ghost {} is not built yet (see contracts/ghost.v1.md)",
        sub.as_str()
    );
    failure(json, EXIT_NOT_BUILT_YET, "unavailable", &message, out, err)
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
