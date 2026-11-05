//! Approval provenance: [private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036).
//! M12 Allowlist: `thread tell` is `send`'s only write, and every other
//! mutating subcommand is still refused. P8(a) is updated for it (see the
//! evidence README for the recorded reason).
//!
//! **Updated for OpenWiz 0.0.4 (ClosedWiz#11, A1 phase 2, N16)**, with this
//! recorded reason: sheet item A-2 (approved by Jake, 2026-10-30) adds
//! `cloud status --json` and the second write, `thread spawn`, in the shapes
//! spike run 3 recorded. `spawn`, `--model` and `--reasoning-level` may now
//! be spelled only in the allowlist, inside `ThreadSpawn`'s argv, never in
//! `tell`'s; `--model` is also `openwiz new`'s own option in the CLI. The
//! catalogue key `steer` stays only in the adapter's `cloud status` reader.
//! `tell`'s shape and every other refusal are unchanged; N16
//! (`tests/new-thread/n16_allowlist.rs`) proves `spawn`'s shape.
//!
//! **Updated for B2 (ClosedWiz#15)**, with this recorded reason: sheet B-7
//! (approved by Jake, 2026-10-30) adds `--file` and `--image` to `tell`
//! and `spawn`, only with staged paths. A path in the text remains text
//! (#15, AD12). So each flag may be spelled only in the allowlist,
//! once, inside its one `attachment_args`, and the fake (its own copy of the
//! allowlist) takes them only in OpenWiz's position, with a staged copy's
//! absolute path, and never with steer. Every other refusal is unchanged.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use openwiz_adapter_cloudroom::allowlist::{Invocation, ThreadId};
use openwiz_core::messaging::Mode;

use crate::m01_exact_invocation::{EXCLUDED, tell_argv};
use crate::support::*;

/// Subcommands that change something. Only `tell` may ever be passed.
const MUTATING: &[&str] = &[
    "spawn",
    "fork",
    "tell",
    "stop",
    "archive",
    "unarchive",
    "update",
    "move",
    "hide",
    "unhide",
    "delete",
    "create",
    "send",
    "mark-read",
    "queue",
    "retry",
    "steer",
    "resume",
    "pause",
];

fn all_reads() -> Vec<Invocation> {
    let id = ThreadId::parse("thr_syn_0001").unwrap();
    vec![
        Invocation::Version,
        Invocation::ThreadList {
            include_hidden: true,
            include_archived: true,
        },
        Invocation::ProjectList { hidden: true },
        Invocation::MachineList,
        Invocation::ThreadShow(id.clone()),
        Invocation::ThreadOutput(id),
        Invocation::CloudStatus,
    ]
}

#[test]
fn thread_tell_is_sends_only_write_in_exactly_its_shape() {
    for read in all_reads() {
        let argv = read.argv();
        for word in MUTATING {
            assert!(!argv.iter().any(|a| a == word), "{read:?} passes {word}");
        }
    }
    let id = ThreadId::parse("thr_syn_0001").unwrap();
    for (mode, word) in [(Mode::Queue, "queue"), (Mode::Steer, "steer")] {
        for text in [
            "Synthetic",
            "--file /synthetic/x",
            "-x",
            "auto",
            "--mode auto",
            "line\nbreak",
        ] {
            let argv = Invocation::ThreadTell {
                id: id.clone(),
                mode,
                text: text.to_owned(),
                attachments: vec![],
            }
            .argv();
            assert_eq!(argv, tell_argv("thr_syn_0001", word, text));
            for flag in EXCLUDED {
                assert!(
                    !argv[..7].iter().any(|a| a == flag),
                    "{flag} before the text: {argv:?}"
                );
            }
        }
    }
}

#[test]
fn the_fake_refuses_every_other_write_and_every_other_tell_shape() {
    let fake = SendFake::new("m12_fake_refuses", "send");
    let refused: Vec<Vec<&str>> = vec![
        vec!["thread", "spawn", "--json"],
        vec!["thread", "stop", "thr_syn_0001"],
        vec!["thread", "archive", "thr_syn_0001"],
        vec!["thread", "queue", "create", "thr_syn_0001", "--hard", "x"],
        vec!["thread", "queue", "list", "thr_syn_0001", "--json"],
        vec!["thread", "log", "thr_syn_0001", "--json"],
        vec![
            "thread",
            "tell",
            "thr_syn_0001",
            "--mode",
            "auto",
            "--json",
            "--",
            "x",
        ],
        vec!["thread", "tell", "thr_syn_0001", "--json", "--", "x"],
        vec![
            "thread",
            "tell",
            "thr_syn_0001",
            "--mode",
            "queue",
            "--",
            "x",
        ],
        vec![
            "thread",
            "tell",
            "thr_syn_0001",
            "--mode",
            "queue",
            "--json",
            "x",
        ],
        vec![
            "thread",
            "tell",
            "thr_syn_0001",
            "--mode",
            "queue",
            "--json",
            "--file",
            "x",
            "--",
            "y",
        ],
        vec![
            "thread",
            "tell",
            "--",
            "thr_syn_0001",
            "--mode",
            "queue",
            "--json",
            "x",
        ],
        vec![
            "thread", "tell", "-x", "--mode", "queue", "--json", "--", "x",
        ],
    ];
    for args in &refused {
        let out = Command::new(fake.program())
            .args(args)
            .output()
            .expect("run the fake");
        assert_eq!(out.status.code(), Some(97), "{args:?}");
    }
    assert_eq!(fake.tell_count(), 0, "a refused call is not counted");
}

/// B2 (sheet B-7): the fake takes `--file` and `--image` only after
/// `--json` and before `--`, in queue mode, each with a staged copy's
/// absolute path; every other form is refused before anything is counted.
#[test]
fn the_fake_takes_attachment_flags_only_with_staged_paths_in_queue() {
    let fake = SendFake::new("m12_fake_attachments", "send");
    let staged = "/synthetic/state/attachments/att-syn-1/syn-notes.txt";
    let tell = |mode: &str, tail: &[&str]| -> Vec<String> {
        let mut argv: Vec<String> = ["thread", "tell", "thr_syn_0001", "--mode", mode, "--json"]
            .iter()
            .map(|w| (*w).to_owned())
            .collect();
        argv.extend(tail.iter().map(|w| (*w).to_owned()));
        argv.extend(["--".to_owned(), "x".to_owned()]);
        argv
    };
    let refused = [
        tell("steer", &["--file", staged]),
        tell("queue", &["--file", "syn-notes.txt"]),
        tell(
            "queue",
            &[
                "--file",
                "file:///synthetic/state/attachments/att-syn-1/syn-notes.txt",
            ],
        ),
        tell(
            "queue",
            &[
                "--file",
                "/synthetic/../attachments/att-syn-1/syn-notes.txt",
            ],
        ),
        tell(
            "queue",
            &["--file", "/synthetic/./attachments/att-syn-1/syn-notes.txt"],
        ),
        tell(
            "queue",
            &["--file", "/synthetic/state/other/att-syn-1/syn-notes.txt"],
        ),
        tell(
            "queue",
            &["--file", "/synthetic/state/attachments/-att/syn-notes.txt"],
        ),
        tell(
            "queue",
            &["--file", "/synthetic/state/attachments/att-syn-1/.hidden"],
        ),
        tell("queue", &["--file"]),
        tell("queue", &["--attach", staged]),
        tell("queue", &["--image", staged, "--model", "m"]),
    ];
    for args in &refused {
        let out = Command::new(fake.program())
            .args(args)
            .output()
            .expect("run the fake");
        assert_eq!(out.status.code(), Some(97), "{args:?}");
    }
    assert_eq!(fake.tell_count(), 0, "a refused call is not counted");
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}

#[test]
fn no_product_source_spells_an_excluded_flag_or_another_write() {
    let mut files = Vec::new();
    rust_files(&Path::new(ROOT).join("crates"), &mut files);
    assert!(files.len() > 10);
    let allowlist = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .unwrap();
    // OpenWiz 0.0.4 (ClosedWiz#11, A1 phase 2): the catalogue key `steer`,
    // only in the adapter's `cloud status` reader; and `openwiz new`'s own
    // `--model` option, only in the CLI's `new` (not a room-cli argument
    // there).
    let catalogue = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/new_thread.rs")
        .canonicalize()
        .unwrap();
    let new_command = Path::new(ROOT)
        .join("crates/cli/src/new_thread.rs")
        .canonicalize()
        .unwrap();
    let service_reader = Path::new(ROOT)
        .join("crates/service/src/document.rs")
        .canonicalize()
        .unwrap();
    let terminal_actions = Path::new(ROOT)
        .join(TERMINAL_ACTIONS)
        .canonicalize()
        .unwrap();
    // `spawn`'s own flags, only inside `ThreadSpawn`'s argv in the allowlist.
    let spawn_arm = |text: &str| {
        text.split("Self::ThreadSpawn(")
            .nth(1)
            .and_then(|rest| rest.split("],").next())
            .unwrap_or_default()
            .to_owned()
    };
    // OpenWiz 0.0.6 (ClosedWiz#120, B4): `archive`, only inside
    // `ThreadArchive`'s argv in the allowlist.
    let archive_arm = |text: &str| {
        text.split("Self::ThreadArchive(")
            .nth(1)
            .and_then(|rest| rest.split("],").next())
            .unwrap_or_default()
            .to_owned()
    };
    for path in files {
        let text = fs::read_to_string(&path).unwrap();
        let canonical = path.canonicalize().unwrap();
        for flag in EXCLUDED {
            let literal = format!("\"{flag}\"");
            if canonical == allowlist && matches!(*flag, "--model" | "--reasoning-level") {
                assert_eq!(text.matches(&literal).count(), 1, "{literal} once");
                assert!(
                    spawn_arm(&text).contains(&literal),
                    "{literal} outside ThreadSpawn"
                );
                continue;
            }
            if canonical == new_command && *flag == "--model" {
                continue;
            }
            if canonical == allowlist && matches!(*flag, "--file" | "--image") {
                assert_eq!(text.matches(&literal).count(), 1, "{literal} once");
                let builder = text
                    .split("pub fn attachment_args(")
                    .nth(1)
                    .and_then(|rest| rest.split("\n}\n").next())
                    .unwrap_or_default();
                assert!(
                    builder.contains(&literal),
                    "{literal} outside attachment_args"
                );
                continue;
            }
            assert!(!text.contains(&literal), "{path:?} contains {literal}");
        }
        for word in MUTATING {
            let literal = format!("\"{word}\"");
            if *word == "update" {
                assert!(
                    service_update_fields_only(&canonical, &service_reader, &text),
                    "{path:?}: update is not the service JSON field"
                );
                continue;
            }
            if *word == "resume" && canonical == allowlist {
                assert!(
                    loop_resume_arm_only(&canonical, &allowlist, &text),
                    "resume outside its exact argv arm"
                );
                continue;
            }
            if *word == "pause" && canonical == allowlist {
                assert!(
                    loop_pause_arm_only(&canonical, &allowlist, &text),
                    "pause outside its exact argv arm"
                );
                continue;
            }
            let is_allowlist = canonical == allowlist;
            if *word == "tell" && is_allowlist {
                continue;
            }
            // `queue` and `steer` are the core's mode words, passed through
            // `Mode::as_str`; `send` is OpenWiz's own command, parsed by the
            // CLI. Neither is a room-cli subcommand there.
            let mode_words = path.ends_with("core/src/messaging/mod.rs");
            if matches!(*word, "queue" | "steer") && mode_words {
                continue;
            }
            if *word == "send" && path.starts_with(Path::new(ROOT).join("crates/cli")) {
                continue;
            }
            // #1098 (orchestrator ruling): the Send action's capability id,
            // once, in the terminal's action seam, and nowhere else there.
            if *word == "send" && canonical == terminal_actions && send_capability_id_only(&text) {
                continue;
            }
            if *word == "spawn" && canonical == allowlist {
                assert!(spawn_arm(&text).contains(&literal), "spawn outside its arm");
                continue;
            }
            if *word == "archive" && canonical == allowlist {
                assert_eq!(text.matches(&literal).count(), 1, "{literal} once");
                assert!(
                    archive_arm(&text).contains(&literal),
                    "archive outside its arm"
                );
                continue;
            }
            if *word == "steer" && canonical == catalogue {
                continue;
            }
            assert!(!text.contains(&literal), "{path:?} contains {literal}");
        }
    }
}

// #269: only the service contract reader may quote this JSON field. This
// helper is shared by the source scan and its planted command-like breaks.
fn service_update_fields_only(path: &Path, reader: &Path, text: &str) -> bool {
    text.match_indices("\"update\"").all(|(at, literal)| {
        if path == reader.with_file_name("update.rs") {
            let start = text[..at].rfind('\n').map_or(0, |n| n + 1);
            let end = text[at..].find('\n').map_or(text.len(), |n| at + n);
            return text[start..end].trim() == "const UPDATE: &str = \"update\";";
        }
        if path != reader {
            return false;
        }
        let before = &text[..at];
        let Some(prefix) = before.strip_suffix("value[") else {
            return false;
        };
        let boundary = prefix
            .chars()
            .next_back()
            .is_none_or(|c| !c.is_alphanumeric() && c != '_');
        boundary && text[at + literal.len()..].starts_with(']')
    })
}

#[test]
fn service_update_exception_never_allows_a_command_or_another_file() {
    let reader = Path::new(ROOT)
        .join("crates/service/src/document.rs")
        .canonicalize()
        .unwrap();
    let other = Path::new(ROOT)
        .join("crates/service/src/runtime.rs")
        .canonicalize()
        .unwrap();
    let fields =
        r#"!value["update"].is_null(); value["update"]["outcome"]; value["update"][field];"#;
    assert!(service_update_fields_only(&reader, &reader, fields));
    for bad in [
        r#"let argv = ["thread", "update", "thr_syn_0001"];"#,
        r#"value["update"]; let argv = ["update"];"#,
        r#"other_value["update"];"#,
        r#"value["update", "argument"];"#,
    ] {
        assert!(
            !service_update_fields_only(&reader, &reader, bad),
            "command-like occurrence escaped: {bad}"
        );
    }
    assert!(!service_update_fields_only(&other, &reader, fields));
    let updater = reader.with_file_name("update.rs").canonicalize().unwrap();
    let key = "const UPDATE: &str = \"update\";";
    assert!(service_update_fields_only(&updater, &reader, key));
    assert!(!service_update_fields_only(&other, &reader, key));
    assert!(!service_update_fields_only(
        &updater,
        &reader,
        &format!("{key}\nlet argv = [\"update\"];")
    ));
}

/// #1098's one terminal exception (as in p08a): the action seam may spell
/// `"send"` exactly once, as `ActionId::Send`'s capability id.
const TERMINAL_ACTIONS: &str = "crates/terminal/src/actions/mod.rs";

fn send_capability_id_only(text: &str) -> bool {
    text.matches("\"send\"").count() == 1 && text.contains("ActionId::Send => \"send\",")
}

#[test]
fn m12_the_terminal_send_exception_refuses_any_widening() {
    let actions = fs::read_to_string(Path::new(ROOT).join(TERMINAL_ACTIONS)).unwrap();
    assert!(send_capability_id_only(&actions));
    // A second literal anywhere, or the literal outside the capability arm.
    for widened in [
        format!("{actions}\nconst X: &str = \"send\";\n"),
        actions.replace(
            "ActionId::Send => \"send\",",
            "ActionId::Send => \"send\",\n            ActionId::Answer => \"send\",",
        ),
        actions.replace(
            "ActionId::Send => \"send\",",
            "ActionId::Send => \"message\",",
        ) + "\nconst X: &str = \"send\";\n",
    ] {
        assert_ne!(widened, actions);
        assert!(!send_capability_id_only(&widened), "{widened}");
    }
    // The exception is that file and that word only: every other terminal
    // source spells no mutating word, and the seam spells no other one.
    let mut files = Vec::new();
    rust_files(&Path::new(ROOT).join("crates/terminal"), &mut files);
    assert!(!files.is_empty());
    for path in files {
        let text = fs::read_to_string(&path).unwrap();
        for word in MUTATING {
            let literal = format!("\"{word}\"");
            if *word == "send" && path.ends_with("actions/mod.rs") {
                continue;
            }
            assert!(!text.contains(&literal), "{path:?} contains {literal}");
        }
    }
}

// T5 owns only the canonical LoopResume argv arm, never another write.
fn loop_resume_arm_only(path: &Path, allowlist: &Path, text: &str) -> bool {
    path == allowlist
        && text.matches("\"resume\"").count() == 1
        && text.contains(
            "Self::LoopResume(id) => vec![\"loop\", \"resume\", id.as_str(), \"--json\"],",
        )
}
fn loop_pause_arm_only(path: &Path, allowlist: &Path, text: &str) -> bool {
    path == allowlist
        && text.matches("\"pause\"").count() == 1
        && text
            .contains("Self::LoopPause(id) => vec![\"loop\", \"pause\", id.as_str(), \"--json\"],")
}
#[test]
fn t5_loop_pause_exception_rejects_other_paths_and_command_like_occurrences() {
    let canonical = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .unwrap();
    let text = fs::read_to_string(&canonical).unwrap();
    assert!(loop_pause_arm_only(&canonical, &canonical, &text));
    assert!(!loop_pause_arm_only(
        &canonical.with_file_name("loops.rs"),
        &canonical,
        &text
    ));
    for planted in [
        format!("{text}\nlet argv = [\"loop\", \"pause\"];"),
        text.replace("Self::LoopPause(id) =>", "Self::ThreadArchive(id) =>"),
        text.replace("Self::LoopPause(id) =>", "Self::LoopPause(id) if true =>"),
        text.replace(
            "vec![\"loop\", \"pause\", id.as_str(), \"--json\"]",
            "vec![\"thread\", \"pause\", id.as_str(), \"--json\"]",
        ),
    ] {
        assert_ne!(planted, text);
        assert!(!loop_pause_arm_only(&canonical, &canonical, &planted));
    }
}
#[test]
fn t5_loop_resume_exception_rejects_other_paths_and_command_like_occurrences() {
    let canonical = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .unwrap();
    let text = fs::read_to_string(&canonical).unwrap();
    assert!(loop_resume_arm_only(&canonical, &canonical, &text));
    let other = canonical.with_file_name("loops.rs");
    assert!(!loop_resume_arm_only(&other, &canonical, &text));
    for planted in [
        format!("{text}\nlet argv = [\"loop\", \"resume\"];"),
        text.replace("Self::LoopResume(id) =>", "Self::ThreadArchive(id) =>"),
        text.replace("Self::LoopResume(id) =>", "Self::LoopResume(id) if true =>"),
        text.replace(
            "vec![\"loop\", \"resume\", id.as_str(), \"--json\"]",
            "vec![\"thread\", \"resume\", id.as_str(), \"--json\"]",
        ),
    ] {
        assert_ne!(planted, text);
        assert!(!loop_resume_arm_only(&canonical, &canonical, &planted));
    }
}
