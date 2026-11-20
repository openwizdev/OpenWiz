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

use crate::support::*;

/// The flags of `thread tell` OpenWiz never passes, and the mode it never
/// asks for (moved here from M1, `m01_exact_invocation.rs`, by #1264).
const EXCLUDED: &[&str] = &[
    "--model",
    "--reasoning-level",
    "--service-tier",
    "--permission-mode",
    "--send-at",
    "--plan",
    "--file",
    "--image",
    "--hard",
    "auto",
];

/// The exact argument list OpenWiz passes for one tell (moved with
/// [`EXCLUDED`]).
fn tell_argv(target: &str, mode: &str, text: &str) -> Vec<String> {
    [
        "thread", "tell", target, "--mode", mode, "--json", "--", text,
    ]
    .iter()
    .map(|w| (*w).to_owned())
    .collect()
}

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
    // only in the adapter's `cloud status` reader.
    let catalogue = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/new_thread.rs")
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
            // #792 (J109, orchestrator ruling on #792): `--model` also once in
            // each of the two loop write arms, and nowhere else.
            if canonical == allowlist && *flag == "--model" {
                assert!(
                    loop_write_arms_only(&canonical, &allowlist, &text, flag),
                    "{literal} outside ThreadSpawn and the two loop write arms"
                );
                assert!(
                    spawn_arm(&text).contains(&literal),
                    "{literal} outside ThreadSpawn"
                );
                continue;
            }
            if canonical == allowlist && *flag == "--reasoning-level" {
                assert_eq!(text.matches(&literal).count(), 1, "{literal} once");
                assert!(
                    spawn_arm(&text).contains(&literal),
                    "{literal} outside ThreadSpawn"
                );
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
            // #792 (J109): `loop create` and `loop update`, once each, only
            // inside their own argv arms in the allowlist.
            if matches!(*word, "create" | "update") && canonical == allowlist {
                assert!(
                    loop_write_arms_only(&canonical, &allowlist, &text, word),
                    "{word} outside its loop write arm"
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

// #792 (J109): the two loop write arms of the allowlist's argv, each from
// its own `Self::Loop…(a) => {` to that arm's closing brace.
fn loop_write_arm(text: &str, variant: &str) -> String {
    let header = format!("            Self::{variant}(a) => {{\n");
    text.split(&header)
        .nth(1)
        .and_then(|rest| rest.split("\n            }\n").next())
        .unwrap_or_default()
        .to_owned()
}
// `create`, `update` and `--model` only where the allowlist builds the two
// loop writes: each subcommand once, opening its own arm; `--model` once in
// each loop arm and once in `ThreadSpawn`, so three times in the file.
fn loop_write_arms_only(path: &Path, allowlist: &Path, text: &str, word: &str) -> bool {
    let literal = format!("\"{word}\"");
    let compact = |s: &str| s.split_whitespace().collect::<String>();
    let create = loop_write_arm(text, "LoopCreate");
    let update = loop_write_arm(text, "LoopUpdate");
    let headers = ["LoopCreate", "LoopUpdate"]
        .iter()
        .all(|v| text.matches(&format!("Self::{v}(a) =>")).count() == 1);
    path == allowlist
        && headers
        && match word {
            "create" => {
                text.matches(&literal).count() == 1
                    && compact(&create).starts_with("letmutw=vec![\"loop\",\"create\",")
            }
            "update" => {
                text.matches(&literal).count() == 1
                    && compact(&update).starts_with("letmutw=vec![\"loop\",\"update\",")
            }
            "--model" => {
                text.matches(&literal).count() == 3
                    && create.matches(&literal).count() == 1
                    && update.matches(&literal).count() == 1
            }
            _ => false,
        }
}
#[test]
fn loop_write_exception_rejects_other_paths_and_command_like_occurrences() {
    let canonical = Path::new(ROOT)
        .join("crates/adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .unwrap();
    let text = fs::read_to_string(&canonical).unwrap();
    for word in ["create", "update", "--model"] {
        assert!(
            loop_write_arms_only(&canonical, &canonical, &text, word),
            "{word}"
        );
        let other = canonical.with_file_name("loop_files.rs");
        assert!(
            !loop_write_arms_only(&other, &canonical, &text, word),
            "{word}"
        );
    }
    for (word, planted) in [
        (
            "create",
            format!("{text}\nlet argv = [\"loop\", \"create\"];"),
        ),
        (
            "update",
            format!("{text}\nlet argv = [\"loop\", \"update\"];"),
        ),
        ("--model", format!("{text}\nlet argv = [\"--model\"];")),
        (
            "create",
            text.replace("Self::LoopCreate(a) =>", "Self::ThreadArchive(a) =>"),
        ),
        (
            "update",
            text.replace("Self::LoopUpdate(a) =>", "Self::LoopUpdate(a) if true =>"),
        ),
        (
            "create",
            text.replacen(
                "\"loop\",\n                    \"create\"",
                "\"thread\",\n                    \"create\"",
                1,
            ),
        ),
        (
            "update",
            text.replacen("\"loop\", \"update\"", "\"thread\", \"update\"", 1),
        ),
    ] {
        assert_ne!(planted, text, "{word}");
        assert!(
            !loop_write_arms_only(&canonical, &canonical, &planted, word),
            "{word}"
        );
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
