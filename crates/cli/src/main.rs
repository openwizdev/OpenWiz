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

fn dispatch_args(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
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
        Some("pro") => match utf8(&args[1..], "nothing was opened", stderr) {
            Some(args) => openwiz_cli::pro::run_system(&args, terminal, stdout, stderr),
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
