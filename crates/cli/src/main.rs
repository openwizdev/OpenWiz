//! The `openwiz` program: the CloudRoom adapter (the verified app bundle)
//! and the system clock, wired to [`openwiz_cli::run`]; for `send`, the
//! send record in the owner's state directory, wired to
//! [`openwiz_cli::send::run_send`]; for `new` and `models`, the
//! new-thread record beside it, wired to [`openwiz_cli::new_thread`]; and
//! for `attachment`, the attachment store beside them, wired to
//! [`openwiz_cli::attachment::run_attachment`] (no `room-cli`); and
//! `fleets` and `fleet`, to [`openwiz_cli::fleets::run`] and
//! [`openwiz_cli::fleet::run`], given only their arguments and the output
//! streams, so each command's own file wires whatever it reads. `ui`, and no
//! arguments in a terminal, run the fixed sibling `openwiz-terminal`
//! (`ui.rs`).

use std::ffi::OsString;
use std::io::{self, IsTerminal, Write};
use std::process::ExitCode;

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_cli::attachment::{self, AttachmentContext};
use openwiz_cli::new_thread::{self, NewContext};
use openwiz_cli::send::{self, SendContext};
use openwiz_cli::{EXIT_USAGE, SystemClock};
use openwiz_core::messaging::record::{SendStore, StoreError};
use openwiz_core::new_thread::record::NewThreadStore;
use openwiz_core::ops::Clock;
use openwiz_store::attachments::{Claims, Df, NoClaims, RecordedClaims};
use openwiz_store::{AttachmentStore, FileStore, NewThreadFileStore, default_state_dir};

// The visual app's entry: part of this binary only (see `ui.rs`).
#[allow(dead_code)]
#[path = "ui.rs"]
mod ui;

fn main() -> ExitCode {
    dispatch(openwiz_adapter_cloudroom::locate::Discovery::system())
}

/// RL4 (#1148): this program's compiled product identity, one record (prefix,
/// canonical JSON, LF) in its read-only data; the build script writes the JSON
/// (contracts/release-candidate.v1.md, "Minimum product identity").
static PRODUCT: [u8; IDENTITY.len() + 20] = product_record(IDENTITY);
const IDENTITY: &str = match option_env!("OPENWIZ_PRODUCT_IDENTITY") {
    Some(json) => json,
    None => "",
};

const fn product_record<const N: usize>(json: &str) -> [u8; N] {
    let (prefix, json) = (b"OPENWIZ_PRODUCT_V1:", json.as_bytes());
    let mut record = [b'\n'; N];
    let mut at = 0;
    while at < N - 1 {
        record[at] = if at < 19 { prefix[at] } else { json[at - 19] };
        at += 1;
    }
    record
}

/// `--build-identity`: print the compiled identity and nothing else. It reads
/// no state or account, calls no `room-cli` and binds nothing. An unknown
/// identity refuses.
fn build_identity() -> std::process::ExitCode {
    use std::io::Write;
    // Past the 19-byte prefix: naming the prefix again would add a second record.
    if !IDENTITY.is_empty() && std::io::stdout().write_all(&PRODUCT[19..]).is_ok() {
        return std::process::ExitCode::SUCCESS;
    }
    eprintln!("build identity is unavailable");
    std::process::ExitCode::FAILURE
}

/// The real CLI and test-only fixture entrypoint share every dispatch path.
pub fn dispatch(discovery: openwiz_adapter_cloudroom::locate::Discovery) -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if args == ["--build-identity"] {
        return build_identity();
    }
    // Engine owns its complete syntax/JSON boundary, including value operands.
    if args.first().is_some_and(|a| a == "engine") {
        return ExitCode::from(
            u8::try_from(openwiz_cli::engine::run(
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
    // Only a terminal on both stdin and stdout may open the visual app.
    let terminal = io::stdin().is_terminal() && io::stdout().is_terminal();
    match args.first().and_then(|a| a.to_str()) {
        None if args.is_empty() && terminal => ui::run(&[], true, stdout, stderr),
        Some("ui") => ui::run(&args[1..], terminal, stdout, stderr),
        Some("send") => run_send(&args[1..], stdout, stderr),
        Some("new") => run_new(&args[1..], stdout, stderr),
        Some("attachment") => run_attachment(&args[1..], stdout, stderr),
        Some("fleets") => openwiz_cli::fleets::run(&args[1..], stdout, stderr),
        Some("fleet") => openwiz_cli::fleet::run(&args[1..], stdout, stderr),
        Some("loop") => openwiz_cli::loops::run_local(&args[1..], &SystemClock, stdout, stderr),
        Some("models") => match utf8(&args[1..], "nothing was read", stderr) {
            Some(args) => new_thread::run_models(
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

/// The arguments as UTF-8, or `None` after one `openwiz: ` line saying
/// `nothing` happened. A text must reach `room-cli` byte for byte, so an
/// argument that is not UTF-8 is refused rather than converted.
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

/// `openwiz new`: the new-thread record in the owner's state directory.
fn run_new(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    let Some(args) = utf8(args, "nothing was created", stderr) else {
        return EXIT_USAGE;
    };
    let open_store = || -> Result<Box<dyn NewThreadStore>, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        Ok(Box::new(NewThreadFileStore::open(&dir)?))
    };
    let open_store_read_only = || -> Result<Option<Box<dyn NewThreadStore>>, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        let store = NewThreadFileStore::open_read_only(&dir)?;
        Ok(store.map(|s| Box::new(s) as Box<dyn NewThreadStore>))
    };
    let open_attachments = || -> Result<AttachmentStore, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        AttachmentStore::open(&dir)
    };
    let stdin = io::stdin();
    let stdin_is_terminal = stdin.is_terminal();
    new_thread::run_new_with(
        &args,
        NewContext {
            client: &CloudRoomSource::from_path(),
            open_store: &open_store,
            open_store_read_only: &open_store_read_only,
            clock: &SystemClock,
            stdin: &mut stdin.lock(),
            stdin_is_terminal,
            new_op_id: &send::random_op_id,
            wait: &std::thread::sleep,
        },
        &open_attachments,
        stdout,
        stderr,
    )
}

/// `openwiz attachment`: the attachment store in the owner's state
/// directory, its free space measured by `/bin/df` (sheet B-3). Paths are
/// passed as given, UTF-8 or not; nothing calls `room-cli`. Each
/// attachment's claim is read from its operation's record (B2): one a send
/// or a new thread may still use is never removed or expired.
fn run_attachment(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    let open_store = || -> Result<AttachmentStore, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        AttachmentStore::open(&dir)
    };
    let open_store_read_only = || -> Result<Option<AttachmentStore>, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        AttachmentStore::open_read_only(&dir)
    };
    // Without a state directory the store can't be opened either, so the
    // claims are never asked.
    let claims: Box<dyn Claims> = match default_state_dir(&|name| std::env::var_os(name)) {
        Ok(dir) => Box::new(RecordedClaims::new(&dir, SystemClock.now())),
        Err(_) => Box::new(NoClaims),
    };
    attachment::run_attachment(
        args,
        AttachmentContext {
            open_store: &open_store,
            open_store_read_only: &open_store_read_only,
            clock: &SystemClock,
            free_space: &Df,
            claims: claims.as_ref(),
        },
        stdout,
        stderr,
    )
}

/// `openwiz send`. The text must reach `room-cli` byte for byte, so an
/// argument that is not UTF-8 is refused rather than converted.
fn run_send(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    let Some(args) = utf8(args, "nothing was sent", stderr) else {
        return EXIT_USAGE;
    };
    let open_store = || -> Result<Box<dyn SendStore>, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        Ok(Box::new(FileStore::open(&dir)?))
    };
    let open_store_read_only = || -> Result<Option<Box<dyn SendStore>>, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        let store = FileStore::open_read_only(&dir)?;
        Ok(store.map(|s| Box::new(s) as Box<dyn SendStore>))
    };
    let open_attachments = || -> Result<AttachmentStore, StoreError> {
        let dir = default_state_dir(&|name| std::env::var_os(name))?;
        AttachmentStore::open(&dir)
    };
    let stdin = io::stdin();
    let stdin_is_terminal = stdin.is_terminal();
    send::run_send_with(
        &args,
        SendContext {
            messenger: &CloudRoomSource::from_path(),
            open_store: &open_store,
            open_store_read_only: &open_store_read_only,
            clock: &SystemClock,
            stdin: &mut stdin.lock(),
            stdin_is_terminal,
            new_op_id: &send::random_op_id,
        },
        &open_attachments,
        stdout,
        stderr,
    )
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
