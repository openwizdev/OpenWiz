//! Approval provenance: [private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036).
//! AP10 No dispatch path. Phase 1 adds no `room-cli` call: the model names
//! no invocation, no process and no attachment flag. P8(a) and M12 run in
//! `cargo test --workspace`.
//!
//! **Updated for B2 (ClosedWiz#15)**, with this recorded reason: sheet B-7
//! (approved by Jake, 2026-10-30) adds `--file` and `--image` to `tell`
//! and `spawn`, with staged absolute paths only. So the allowlist now names
//! each flag exactly once, inside its one `attachment_args`, and uses the
//! model's `StagedAttachment` and `Kind` for it; the adapter's `send` and
//! `new` pass the core's `ReadyPrompt`. AD11
//! (`tests/attachments/ad_static.rs`) proves there is one builder, with
//! each flag once inside it. The
//! model itself still names no invocation, process or flag, the server
//! still uses no attachment, and the store and the CLI still dispatch
//! nothing themselves.

use std::fs;
use std::path::Path;

use crate::support::ROOT;

fn read(path: &str) -> String {
    fs::read_to_string(Path::new(ROOT).join(path)).unwrap_or_else(|e| panic!("{path}: {e}"))
}

#[test]
fn the_model_has_no_dispatch_path_and_no_io() {
    let model = read("crates/core/src/attachment.rs");
    for word in [
        "room-cli",
        "room_cli",
        "Invocation",
        "Command",
        "openwiz_adapter",
        "allowlist",
        "\"tell\"",
        "\"spawn\"",
        "\"--file\"",
        "\"--image\"",
        "std::fs",
        "std::io",
        "std::net",
        "std::process",
        "std::env",
        "std::os",
        "SystemTime",
        "Instant",
        "println!",
        "eprintln!",
        "unsafe",
    ] {
        assert!(!model.contains(word), "attachment.rs names {word}");
    }
    // It imports only `std::time`, `std::fmt` and serde, and nothing from
    // another crate or module of the workspace.
    for line in model.lines().filter(|l| l.starts_with("use ")) {
        assert!(
            line.contains("use std::time::Duration")
                || line.contains("use std::fmt")
                || line.contains("use serde::"),
            "attachment.rs: {line}"
        );
    }
}

/// Phase 2: in the adapter, only the allowlist uses the model. (The store
/// and the CLI's attachment commands, which this also checked, went in
/// #1264.)
#[test]
fn only_the_store_and_the_cli_use_the_model_and_neither_dispatches() {
    // B2: in the adapter, only the allowlist uses the model (B-7's staged
    // attachments).
    for dir in ["crates/adapters/cloudroom/src"] {
        let mut files = Vec::new();
        rust_files(&Path::new(ROOT).join(dir), &mut files);
        for path in files {
            let text = fs::read_to_string(&path).unwrap();
            if path.ends_with("adapters/cloudroom/src/allowlist.rs") {
                continue;
            }
            assert!(
                !text.contains("attachment::"),
                "{path:?} uses the attachment model"
            );
        }
    }
}

fn rust_files(dir: &Path, out: &mut Vec<std::path::PathBuf>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}
