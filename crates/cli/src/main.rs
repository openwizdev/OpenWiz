use std::ffi::OsString;
use std::io::{self, IsTerminal, Write};
use std::process::ExitCode;

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_cli::{EXIT_USAGE, SystemClock};

fn main() -> ExitCode {
    dispatch(openwiz_adapter_cloudroom::locate::Discovery::system())
}

const PRODUCT_PREFIX: &[u8] = b"OPENWIZ_PRODUCT_V1:";
const PRODUCT_PREFIX_LEN: usize = PRODUCT_PREFIX.len();
static PRODUCT: [u8; PRODUCT_PREFIX_LEN + IDENTITY.len() + 1] = product_record(IDENTITY);
const IDENTITY: &str = match option_env!("OPENWIZ_PRODUCT_IDENTITY") {
    Some(json) => json,
    None => "",
};

const fn product_record<const N: usize>(json: &str) -> [u8; N] {
    let (prefix, json) = (PRODUCT_PREFIX, json.as_bytes());
    let mut record = [b'\n'; N];
    let mut at = 0;
    while at < N - 1 {
        record[at] = if at < prefix.len() {
            prefix[at]
        } else {
            json[at - prefix.len()]
        };
        at += 1;
    }
    record
}

fn build_identity() -> std::process::ExitCode {
    use std::io::Write;
    if !IDENTITY.is_empty()
        && std::io::stdout()
            .write_all(&PRODUCT[PRODUCT_PREFIX_LEN..])
            .is_ok()
    {
        return std::process::ExitCode::SUCCESS;
    }
    eprintln!("build identity is unavailable");
    std::process::ExitCode::FAILURE
}

pub fn dispatch(discovery: openwiz_adapter_cloudroom::locate::Discovery) -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if args == ["--build-identity"] {
        return build_identity();
    }
    if args.first().is_some_and(|a| a == "init") {
        return ExitCode::from(
            u8::try_from(openwiz_cli::init::run(
                &args[1..],
                &mut io::stdout().lock(),
                &mut io::stderr().lock(),
            ))
            .unwrap_or(1),
        );
    }
    if args.first().is_some_and(|a| a == "ghost") {
        return ExitCode::from(
            u8::try_from(openwiz_cli::ghost::run(
                &args[1..],
                &mut io::stdout().lock(),
                &mut io::stderr().lock(),
            ))
            .unwrap_or(1),
        );
    }
    let request = openwiz_cli::response::Request::new(&args);
    let code = openwiz_cli::response::run(
        &request,
        &mut io::stdout().lock(),
        &mut io::stderr().lock(),
        |stdout, stderr| {
            if openwiz_adapter_cloudroom::locate::install(discovery).is_err() {
                let _ = writeln!(stderr, "openwiz: discovery already configured");
                return 1;
            }
            dispatch_args(&args, stdout, stderr)
        },
    );
    ExitCode::from(u8::try_from(code).unwrap_or(1))
}

fn locale_is_utf8(lc_all: Option<&str>, lc_ctype: Option<&str>, lang: Option<&str>) -> bool {
    [lc_all, lc_ctype, lang]
        .into_iter()
        .flatten()
        .find(|value| !value.is_empty())
        .is_some_and(|value| {
            let lower = value.to_ascii_lowercase();
            lower.contains("utf-8") || lower.contains("utf8")
        })
}

fn utf8_locale() -> bool {
    locale_is_utf8(
        std::env::var("LC_ALL").ok().as_deref(),
        std::env::var("LC_CTYPE").ok().as_deref(),
        std::env::var("LANG").ok().as_deref(),
    )
}

// Human help on a terminal. Piped output and `--json` stay byte-for-byte plain.
fn banner_line(args: &[OsString], terminal: bool, utf8: bool) -> Option<&'static str> {
    let words = args
        .iter()
        .map(|arg| arg.to_str())
        .collect::<Option<Vec<_>>>()?;
    let human = if words.is_empty() {
        terminal
    } else if words.contains(&"--json") {
        false
    } else if words.first() == Some(&"help") {
        words == ["help"]
    } else {
        words.iter().any(|word| *word == "--help" || *word == "-h")
    };
    if !human || !terminal {
        return None;
    }
    Some(if utf8 {
        "🧙‍♂️🪄 OpenWiz\n"
    } else {
        "OpenWiz\n"
    })
}

fn dispatch_args(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    if let Some(line) = banner_line(args, io::stdout().is_terminal(), utf8_locale()) {
        let _ = write!(stdout, "{line}");
    }
    let terminal = io::stdin().is_terminal() && io::stdout().is_terminal();
    match args.first().and_then(|a| a.to_str()) {
        None if args.is_empty() && terminal => openwiz_cli::run(
            &["--help".to_owned()],
            &CloudRoomSource::from_path(),
            &SystemClock,
            stdout,
            stderr,
        ),
        Some("fleets") => openwiz_cli::fleets::run(&args[1..], stdout, stderr),
        Some("fleet") => openwiz_cli::fleet::run(&args[1..], stdout, stderr),
        Some("loop") if openwiz_cli::loop_files::handles(args.get(1).and_then(|a| a.to_str())) => {
            openwiz_cli::loop_files::run(&args[1..], stdout, stderr)
        }
        Some("loop") => openwiz_cli::loops::run_local(&args[1..], &SystemClock, stdout, stderr),
        Some("models") => match utf8(&args[1..], "nothing was read", stderr) {
            Some(args) => openwiz_cli::models::run_models(
                &args,
                &CloudRoomSource::from_path(),
                &SystemClock,
                stdout,
                stderr,
            ),
            None => EXIT_USAGE,
        },
        _ => match utf8(args, "nothing was read", stderr) {
            Some(args) => openwiz_cli::run(
                &args,
                &CloudRoomSource::from_path(),
                &SystemClock,
                stdout,
                stderr,
            ),
            None => EXIT_USAGE,
        },
    }
}

fn utf8(args: &[OsString], nothing: &str, stderr: &mut dyn Write) -> Option<Vec<String>> {
    let args = args
        .iter()
        .map(|a| a.clone().into_string().ok())
        .collect::<Option<Vec<String>>>();
    if args.is_none() {
        let _ = writeln!(
            stderr,
            "openwiz: an argument is not valid UTF-8; {nothing} (see openwiz --help)"
        );
    }
    args
}

#[cfg(test)]
mod product_identity {
    #[test]
    fn the_compiled_record_is_this_programs_canonical_identity() {
        let json = std::str::from_utf8(&super::PRODUCT)
            .unwrap()
            .strip_prefix("OPENWIZ_PRODUCT_V1:")
            .and_then(|r| r.strip_suffix('\n'))
            .unwrap();
        let value: std::collections::BTreeMap<String, String> = serde_json::from_str(json).unwrap();
        assert_eq!(
            serde_json::to_string(&value).unwrap(),
            json,
            "canonical JSON"
        );
        let keys: Vec<_> = value.keys().map(String::as_str).collect();
        assert_eq!(keys, ["product", "schema", "source", "target", "version"]);
        assert_eq!(value["product"], "cli");
        assert_eq!(value["schema"], "openwiz.product.v1");
        assert_eq!(value["version"], env!("CARGO_PKG_VERSION"));
    }
}

#[cfg(test)]
mod banner {
    use std::ffi::OsString;

    use super::{banner_line, locale_is_utf8};

    fn args(words: &[&str]) -> Vec<OsString> {
        words.iter().copied().map(OsString::from).collect()
    }

    #[test]
    fn utf8_locale_follows_lc_all_then_lc_ctype_then_lang() {
        assert!(!locale_is_utf8(None, None, None));
        assert!(!locale_is_utf8(
            Some("C"),
            Some("en_US.UTF-8"),
            Some("en_US.UTF-8")
        ));
        assert!(locale_is_utf8(Some("C.UTF-8"), None, None));
        assert!(locale_is_utf8(None, Some("en_US.utf8"), Some("C")));
        assert!(locale_is_utf8(None, None, Some("en_US.UTF-8")));
        assert!(!locale_is_utf8(Some(""), None, Some("C")));
        assert!(locale_is_utf8(Some(""), None, Some("en_US.UTF-8")));
    }

    #[test]
    fn the_mark_is_only_on_human_help_in_a_terminal() {
        let mark = "🧙‍♂️🪄 OpenWiz\n";
        let plain = "OpenWiz\n";
        assert_eq!(banner_line(&args(&[]), true, true), Some(mark));
        assert_eq!(banner_line(&args(&[]), true, false), Some(plain));
        assert_eq!(banner_line(&args(&[]), false, true), None);
        assert_eq!(banner_line(&args(&["--help"]), true, true), Some(mark));
        assert_eq!(banner_line(&args(&["-h"]), true, false), Some(plain));
        assert_eq!(banner_line(&args(&["help"]), true, true), Some(mark));
        assert_eq!(
            banner_line(&args(&["ls", "--help"]), true, true),
            Some(mark)
        );
        assert_eq!(banner_line(&args(&["--help"]), false, true), None);
        assert_eq!(banner_line(&args(&["--json", "--help"]), true, true), None);
        assert_eq!(banner_line(&args(&["help", "--agent"]), true, true), None);
        assert_eq!(banner_line(&args(&["help", "--json"]), true, true), None);
        assert_eq!(banner_line(&args(&["ls"]), true, true), None);
        assert_eq!(
            banner_line(&args(&["ls", "--limit=--help"]), true, true),
            None
        );
    }
}
