//! Connection settings for an already running local `openwiz-server`
//! (terminal contract, "Entry and settings"). The TCP peer is always
//! `127.0.0.1`; only the port and the owner's allowed host can be chosen.

use std::ffi::OsString;

/// The server's existing default port (`openwiz-server --port`, provisional).
pub const DEFAULT_PORT: u16 = 7370;

/// The environment variable the server itself reads for its public host.
pub const ALLOWED_HOST_ENV: &str = "OPENWIZ_SERVER_ALLOWED_HOST";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Settings {
    pub port: u16,
    /// The owner's configured public host name. `None`: guarded requests are
    /// unavailable and loopback reads still work.
    pub allowed_host: Option<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            port: DEFAULT_PORT,
            allowed_host: None,
        }
    }
}

/// What the command line asked for.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Invocation {
    Run(Settings),
    Help,
}

pub fn usage() -> &'static str {
    "openwiz-terminal: the OpenWiz visual terminal app, over a running local openwiz-server.

Usage:
  openwiz ui [--port N] [--allowed-host NAME]
  openwiz-terminal [--port N] [--allowed-host NAME]

  --port N               the server's port on 127.0.0.1 (default 7370)
  --allowed-host NAME    the server's configured public host name, for guarded
                         requests; otherwise OPENWIZ_SERVER_ALLOWED_HOST. Without
                         one, only reads work

It never starts a server, runs room-cli or gh, or connects anywhere but 127.0.0.1.
Keys: h Home, s Sessions, f Fleets, 1-9 open a Needs you item, arrows or j/k move,
Enter opens, Esc goes back, r refreshes, q quits.
"
}

/// Parses the visual executable's arguments. `env_host` is the owner's
/// `OPENWIZ_SERVER_ALLOWED_HOST`; an explicit `--allowed-host` wins, and an
/// empty environment value is ignored, as the server does.
pub fn parse(args: &[OsString], env_host: Option<OsString>) -> Result<Invocation, String> {
    let mut port: Option<u16> = None;
    let mut host: Option<String> = None;
    let mut index = 0;
    while index < args.len() {
        let Some(arg) = args[index].to_str() else {
            return Err("an argument is not valid UTF-8".into());
        };
        index += 1;
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) if flag.starts_with("--") => (flag, Some(value.to_owned())),
            _ => (arg, None),
        };
        let mut value = |name: &str| -> Result<String, String> {
            if let Some(value) = inline.clone() {
                return Ok(value);
            }
            let next = args
                .get(index)
                .and_then(|a| a.to_str())
                .ok_or_else(|| format!("{name} needs a value"))?;
            index += 1;
            Ok(next.to_owned())
        };
        match flag {
            "--help" | "-h" if inline.is_none() => return Ok(Invocation::Help),
            "--port" => {
                if port.is_some() {
                    return Err("--port is given more than once".into());
                }
                port = Some(parse_port(&value("--port")?)?);
            }
            "--allowed-host" => {
                if host.is_some() {
                    return Err("--allowed-host is given more than once".into());
                }
                let name = value("--allowed-host")?;
                if !valid_public_host(&name) {
                    return Err(HOST_RULE.into());
                }
                host = Some(name);
            }
            _ => return Err("unknown argument (see --help)".into()),
        }
    }
    let allowed_host = match host {
        Some(host) => Some(host),
        None => match env_host {
            Some(value) if value.is_empty() => None,
            Some(value) => {
                let value = value
                    .into_string()
                    .map_err(|_| format!("{ALLOWED_HOST_ENV} is not valid UTF-8"))?;
                if !valid_public_host(&value) {
                    return Err(format!("{ALLOWED_HOST_ENV}: {HOST_RULE}"));
                }
                Some(value)
            }
            None => None,
        },
    };
    Ok(Invocation::Run(Settings {
        port: port.unwrap_or(DEFAULT_PORT),
        allowed_host,
    }))
}

pub const HOST_RULE: &str = "the allowed host must be a public DNS name: no scheme, path, port, IP address or loopback name";

/// One decimal number, 1 to 65535, without sign or leading zero.
pub fn parse_port(value: &str) -> Result<u16, String> {
    const RULE: &str = "--port must be one decimal number from 1 to 65535";
    if value.is_empty()
        || value.len() > 5
        || !value.bytes().all(|b| b.is_ascii_digit())
        || value.starts_with('0')
    {
        return Err(RULE.into());
    }
    match value.parse::<u32>() {
        Ok(n) if (1..=65535).contains(&n) => Ok(n as u16),
        _ => Err(RULE.into()),
    }
}

/// The server's configured-public-DNS-name rule (`openwiz-server`'s
/// `valid_host_name` and `SendHost::new`), restated here because this crate
/// may not depend on the server.
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
