//! `openwiz github token --repository <owner/name> [--read]` (GI5, #2547;
//! [contracts/github-identity.v1.md], "The token command"): one short-lived
//! installation token for the installation covering that repository, minted
//! from the App key in the `OPENWIZ_GITHUB_APP_KEY` Cloudroom secret, printed
//! alone on stdout for `GH_TOKEN` and git's credential helper. `--read` asks
//! for exactly the read profile. Nothing stores the token.
//!
//! The key and the token never reach an argument, a URL, a log, an error or
//! any output but that one stdout line. Every failure is one fixed sentence.

use std::ffi::OsString;
use std::io::Write;
use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_adapter_github::app::{self, CurlExchange, Exchange, Refusal, SecretApp};

use crate::{EXIT_NOT_FOUND, EXIT_OK, EXIT_READ_FAILED, EXIT_USAGE, UsageError};

/// The Cloudroom secret holding the App's key: the PEM file, base64, one line.
pub const SECRET: &str = "OPENWIZ_GITHUB_APP_KEY";
/// The App's public id, written by setup beside the secret.
pub const APP_ID: &str = "OPENWIZ_GITHUB_APP_ID";
/// GitHub refused, or the token failed the contract or the expiry guards.
pub const EXIT_REFUSED: i32 = 5;
/// The whole command's budget: the installation lookup and the mint.
const BUDGET: Duration = Duration::from_secs(30);

pub const USAGE: &str = "  openwiz github token --repository OWNER/NAME [--read]\n";
pub const HELP: &str = "github token --repository OWNER/NAME [--read]
  Mints one GitHub App installation token (about an hour) for the installation
  that covers OWNER/NAME, from the App key in the OPENWIZ_GITHUB_APP_KEY secret
  and the App id in OPENWIZ_GITHUB_APP_ID. Prints only the token on stdout and
  `expires_at <unix seconds>` on stderr; stores nothing. --read asks for the
  read-only profile. Exits 0 printed, 1 key, App id or GitHub unavailable,
  2 usage, 3 repository not installed, 5 refused.
";

/// `openwiz github token`'s options.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenArgs {
    /// `owner/name`, as GitHub names them.
    pub repository: String,
    /// `--read`: exactly the read profile.
    pub read: bool,
}

/// What the command line asks for.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Parsed {
    Help,
    Token(TokenArgs),
}

/// Parses the arguments after `github`. Errors name no value, so a pasted
/// secret never reaches stderr.
pub fn parse(args: &[String]) -> Result<Parsed, UsageError> {
    let usage = |why: &str| Err(UsageError(format!("github token: {why}")));
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Ok(Parsed::Help);
    }
    let Some(rest) = args.strip_prefix(&["token".to_owned()]) else {
        return usage("the only github command is token");
    };
    let (mut repository, mut read) = (None, false);
    let mut args = rest.iter();
    while let Some(arg) = args.next() {
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) if flag.starts_with("--") => (flag, Some(value.to_owned())),
            _ => (arg.as_str(), None),
        };
        match flag {
            "--read" if inline.is_none() => read = true,
            "--repository" if repository.is_none() => {
                let Some(value) = inline.or_else(|| args.next().cloned()) else {
                    return usage("--repository needs OWNER/NAME");
                };
                repository = Some(value);
            }
            "--repository" => return usage("--repository is given once"),
            _ => return usage("unknown option or argument"),
        }
    }
    let Some(repository) = repository else {
        return usage("--repository OWNER/NAME is required");
    };
    let Ok(parsed) = openwiz_core::fleet::starts::Repository::parse(&repository) else {
        return usage("--repository is OWNER/NAME, as GitHub names them");
    };
    Ok(Parsed::Token(TokenArgs {
        repository: parsed.as_str().to_owned(),
        read,
    }))
}

/// Where the command gets its key, App id, GitHub and time.
pub struct Context {
    /// The `OPENWIZ_GITHUB_APP_KEY` value, if set.
    pub secret: Option<OsString>,
    /// The `OPENWIZ_GITHUB_APP_ID` value, if set.
    pub app_id: Option<OsString>,
    pub exchange: Arc<dyn Exchange>,
    pub clock: Arc<dyn app::Clock>,
}

impl Context {
    /// This process's environment, HTTPS through the fixed `/usr/bin/curl`,
    /// and the system clock.
    pub fn system() -> Self {
        Self {
            secret: std::env::var_os(SECRET),
            app_id: std::env::var_os(APP_ID),
            exchange: Arc::new(CurlExchange),
            clock: Arc::new(app::SystemClock),
        }
    }
}

/// Runs `openwiz github ...` and returns the exit code.
pub fn run(
    args: &[String],
    context: Context,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let say = |stderr: &mut dyn Write, code: i32, line: &str| {
        let _ = writeln!(stderr, "openwiz: github token: {line}");
        code
    };
    let token = match parse(args) {
        Ok(Parsed::Help) => {
            return match stdout
                .write_all(HELP.as_bytes())
                .and_then(|()| stdout.flush())
            {
                Ok(()) => EXIT_OK,
                Err(_) => say(stderr, EXIT_READ_FAILED, "could not write output"),
            };
        }
        Ok(Parsed::Token(token)) => token,
        Err(UsageError(message)) => {
            let _ = writeln!(
                stderr,
                "openwiz: {message} (see openwiz github token --help)"
            );
            return EXIT_USAGE;
        }
    };
    let deadline = Instant::now() + BUDGET;
    let Some(app) = secret_app(context) else {
        return say(
            stderr,
            EXIT_READ_FAILED,
            "the App key or App id is missing or unreadable; no token was minted",
        );
    };
    let minted = match app.mint(&token.repository, token.read, deadline) {
        Ok(minted) => minted,
        Err(Refusal::Unavailable) => {
            return say(
                stderr,
                EXIT_READ_FAILED,
                "GitHub gave no complete answer; no token was minted",
            );
        }
        Err(Refusal::NotInstalled) => {
            return say(
                stderr,
                EXIT_NOT_FOUND,
                "the repository is not covered by an installation of this App",
            );
        }
        Err(Refusal::Refused) => {
            return say(
                stderr,
                EXIT_REFUSED,
                "GitHub refused the token (details withheld); no token was printed",
            );
        }
    };
    let mut line = minted.token;
    line.push('\n');
    if stdout
        .write_all(line.as_bytes())
        .and_then(|()| stdout.flush())
        .is_err()
    {
        return say(stderr, EXIT_READ_FAILED, "could not write output");
    }
    let _ = writeln!(stderr, "expires_at {}", minted.expires_at);
    EXIT_OK
}

/// The key from the secret and the App id, each strictly: the id is a
/// positive decimal with no sign or leading zero. Neither is ever echoed.
fn secret_app(context: Context) -> Option<SecretApp> {
    let app_id = context.app_id?.into_string().ok()?;
    if app_id.starts_with('0') || !app_id.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let app_id = app_id.parse::<u64>().ok()?;
    let secret = context.secret?.into_string().ok()?;
    SecretApp::from_secret(&secret, app_id, context.exchange, context.clock).ok()
}
