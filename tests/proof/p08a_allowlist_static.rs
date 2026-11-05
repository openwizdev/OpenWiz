//! Approval provenance: [private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036).
//! P8(a) Allowlist, static: no invocation outside the allowlist.
//!
//! This passes in ticket 1. It checks every [`Invocation`] the adapter can
//! build, the id guard that stops an id becoming a flag, and that only the
//! adapter's allowlist can start a process. Which invocations a real run
//! makes is checked against the fake's log in the other proof cases.
//!
//! **Updated for OpenWiz 0.0.3 (ClosedWiz#8, M12)**, with this recorded
//! reason: #8 adds exactly one write to the allowlist, `thread tell <id>
//! --mode queue|steer --json -- <text>` (documented, not observed; the
//! argument shape must be rechecked on the owner's endpoint before any live
//! send). So `ALLOWED` gains its two forms, `tell` may appear only as the
//! subcommand of [`Invocation::ThreadTell`]: once in the allowlist's source,
//! inside that variant's argv, and `send` (OpenWiz's own command name, not a `room-cli` word)
//! only in the CLI's source. Every read is checked as before, and every
//! other forbidden word stays forbidden everywhere.
//!
//! **Updated for OpenWiz 0.0.4 (ClosedWiz#11, A1 phase 2, N16)**, with this
//! recorded reason: sheet A-2, approved by Jake on 2026-10-30, adds exactly
//! two invocations in the shapes spike run 3 recorded (`room-cli` v131 help and one structure-only read): the read
//! `cloud status --json`, and the second write, `thread spawn --project
//! <id> --machine cloud --provider <p> --model <m> --reasoning-level <l>
//! --request-id <rid> --json --prompt <text>` (the flags observed in help;
//! the call itself never ran). So `ALLOWED` gains their forms, and `spawn`
//! may appear only as the subcommand of [`Invocation::ThreadSpawn`]: once in
//! the allowlist's source, inside that variant's argv. Phase 1's exemption
//! for `crates/adapters/cloudroom/src/new_thread.rs` is gone: the argv is
//! built only here now.
//!
//! **Updated for OpenWiz 0.0.4 (ClosedWiz#14, B1 phase 2)**, with this
//! recorded reason: staging an attachment must never leave less than 1 GiB
//! free on the state volume (sheet B-3), and the standard library can't
//! measure free space without `unsafe` or a new crate. Jake approved B-3
//! option (a) on #14, 2026-10-31: the store may run exactly
//! `/bin/df -P -k <state dir>` with `LC_ALL=C` and nothing else, failing
//! closed (any error or unparsable output stages nothing). So
//! `crates/store/src/attachments.rs` is the one source outside the adapter
//! that may start a process, and only that one: one `Command::new`, of
//! `DF_PROGRAM` (`/bin/df`), with exactly `DF_ARGS` (`-P -k`), the directory,
//! a cleared environment and `LC_ALL=C`
//! (`the_free_space_measure_runs_only_bin_df`). It names no `room-cli`
//! word; every other source is checked as before.
//!
//! **T2 native App exception (ClosedWiz#1102, Jake, 2026-11-05):**
//! macOS App signing may use only absolute `/usr/bin/python3 -I -c` with the
//! compiled-in reviewed security.py, inspect/sign and private root, a cleared
//! environment and no PATH or override (comment 6672035698). This is an App-only
//! exception; P8(a)'s store guard below remains unchanged, `/bin/df` only.
//!
//! **Updated for OpenWiz 0.0.4 (ClosedWiz#15, B2)**, with this recorded
//! reason: sheet B-7 (approved by Jake, 2026-10-30) adds `--file <path>`
//! and `--image <path>` to `tell` and `spawn`, with staged absolute paths
//! only; the type forbids any other path. So `ALLOWED` gains one form
//! of each write with attachments (a file, then an image: the core's
//! dispatch order), the tail after `--json` and before the text's `--` or
//! `--prompt`, each path a staged copy's (`StagedPath`, buildable only from
//! an absolute, plain `attachments` directory, an attachment id and a safe
//! name). The flags are built only by the allowlist's one
//! `attachment_args`, which no forbidden word reaches; every other form and
//! every other check are unchanged.
//!
//! **Updated for OpenWiz 0.0.6 (ClosedWiz#111, A3)**, with this recorded
//! reason: spec #107 (approved by Jake, 2026-10-31) reads GitHub through
//! `gh` behind a fixed allowlist of reads, and the orchestrator decided on
//! #111 (2026-10-31, Q3 (a)) that A3 adds the GitHub adapter's one runner,
//! and that this check lets the GitHub adapter start a process only there.
//! So `crates/adapters/github/src/process.rs` is the second source outside
//! the CloudRoom adapter that may start a process, and only that one: one
//! `Command::new(program)`, with exactly an `Invocation`'s argv, stdin
//! closed and both outputs piped, and nothing else
//! (`the_github_runner_runs_only_an_invocation`). An `Invocation` is built
//! only from an argument list a module of the GitHub adapter's allowlist
//! allows; every module is empty in A3. Every other source is checked as
//! before.
//!
//! **Updated for OpenWiz 0.0.6 (ClosedWiz#114, A6)**, with this recorded
//! reason: spec #107's verified chain needs each Cloud thread's branch, which
//! CloudRoom reports only through `cloud thread-workspace <id> --json`
//! (A1's spike, #109). Jake approved that one read-only invocation on #107
//! (Q1), 2026-10-31. So `ALLOWED`
//! gains its one form, `cloud thread-workspace <id> --json`, with the id a
//! [`ThreadId`], so it can't become a flag. It is a read: no forbidden word,
//! and every other form and every other check are unchanged.
//!
//! **Updated for OpenWiz 0.0.6 (ClosedWiz#120, B4)**, with this recorded
//! reason: spec #116 (approved by Jake, 2026-10-31) adds the CloudRoom
//! `thread archive` write, and the orchestrator widened #120's paths to
//! this file (2026-11-01). It adds exactly one invocation,
//! [`Invocation::ThreadArchive`]: `thread archive <id> --json` (observed in
//! help, 0.43.1; the call never run). So `ALLOWED` gains its one form, and
//! `archive` may appear only as that variant's subcommand. Every other form
//! and every other check are unchanged.
//!
//! **Updated for OpenWiz 0.0.9 (ClosedWiz#545, L3)**: Jake's approved
//! #541 plan and the executor contract authorize local immutable Git reads
//! and an exactly approved check, with its deadline and own-group cleanup.
//! Ops recorded the bounded paths/invocations in #545 comment 6631634142.
//! Only repository.rs and check.rs below gain exceptions; CloudRoom writes
//! still go through the existing new-thread gates and adapter allowlist.
//! #1014 hardens those same Git reads with pinned config and environment;
//! scope/ops authority: the explicit ruling in #1014 comment 6649970932.
//! Correction R1/R2's config setup read/allowlist and canonical worktree pin
//! are authorized by #1014 comment 6651994842.

use std::fs;
use std::path::{Path, PathBuf};

use openwiz_adapter_cloudroom::allowlist::{Invocation, SpawnArgs, THREAD_ID_MAX_LEN, ThreadId};
use openwiz_core::attachment::{
    AttachmentId, Kind, PromptAttachment, SafeName, Sha256, StagedAttachment, StagedPath,
};
use openwiz_core::messaging::Mode;

/// The two staged copies of the attachment forms (B2): a file, then an
/// image.
const STAGED_FILE: &str = "/synthetic/state/attachments/att-syn-0001/syn-notes.txt";
const STAGED_IMAGE: &str = "/synthetic/state/attachments/att-syn-0002/syn-photo.png";

fn staged() -> Vec<StagedAttachment> {
    [
        ("att-syn-0001", "syn-notes.txt", Kind::File),
        ("att-syn-0002", "syn-photo.png", Kind::Image),
    ]
    .into_iter()
    .map(|(id, name, kind)| {
        let id = AttachmentId::parse(id).unwrap();
        let name = SafeName::parse(name).unwrap();
        StagedAttachment {
            path: StagedPath::new(Path::new("/synthetic/state/attachments"), &id, &name).unwrap(),
            attachment: PromptAttachment {
                id,
                sha256: Sha256::parse(&"0".repeat(64)).unwrap(),
                size_bytes: 1,
                kind,
                name,
            },
        }
    })
    .collect()
}

/// The request id of the spawn forms below.
const RID: &str = "ow1-0123456789abcdef0123456789abcdef01234567";

/// The allowlist as approved in ClosedWiz#2, written out by hand.
const ALLOWED: &[&[&str]] = &[
    &["--version"],
    &["thread", "list", "--json"],
    &["thread", "list", "--json", "--include-hidden"],
    &["thread", "list", "--json", "--include-archived"],
    &[
        "thread",
        "list",
        "--json",
        "--include-hidden",
        "--include-archived",
    ],
    &["project", "list", "--json", "--include-personal"],
    &[
        "project",
        "list",
        "--json",
        "--include-personal",
        "--hidden",
    ],
    &["machine", "list", "--json"],
    &["thread", "show", "thr_syn_0001", "--json"],
    &["thread", "output", "thr_syn_0001", "--json"],
    // The one write (OpenWiz 0.0.3, ClosedWiz#8). Documented, not observed.
    &[
        "thread",
        "tell",
        "thr_syn_0001",
        "--mode",
        "queue",
        "--json",
        "--",
        "Synthetic",
    ],
    &[
        "thread",
        "tell",
        "thr_syn_0001",
        "--mode",
        "steer",
        "--json",
        "--",
        "Synthetic",
    ],
    // OpenWiz 0.0.4 (ClosedWiz#11, sheet A-2): the catalogue read and the
    // second write, in the shapes spike run 3 recorded.
    &["cloud", "status", "--json"],
    &[
        "thread",
        "spawn",
        "--project",
        "prj_syn_0001",
        "--machine",
        "cloud",
        "--provider",
        "codex",
        "--model",
        "syn-codex-model-01",
        "--reasoning-level",
        "high",
        "--request-id",
        RID,
        "--json",
        "--prompt",
        "Synthetic",
    ],
    // B2 (ClosedWiz#15, sheet B-7): each write with attachments, staged
    // absolute paths only, the tail before the text's placement.
    &[
        "thread",
        "tell",
        "thr_syn_0001",
        "--mode",
        "queue",
        "--json",
        "--file",
        STAGED_FILE,
        "--image",
        STAGED_IMAGE,
        "--",
        "Synthetic",
    ],
    &[
        "thread",
        "spawn",
        "--project",
        "prj_syn_0001",
        "--machine",
        "cloud",
        "--provider",
        "codex",
        "--model",
        "syn-codex-model-01",
        "--reasoning-level",
        "high",
        "--request-id",
        RID,
        "--json",
        "--file",
        STAGED_FILE,
        "--image",
        STAGED_IMAGE,
        "--prompt",
        "Synthetic",
    ],
    // OpenWiz 0.0.6 (ClosedWiz#114, A6): one Cloud thread's branch,
    // approved by Jake on #107, 2026-10-31.
    &["cloud", "thread-workspace", "thr_syn_0001", "--json"],
    // B4 (ClosedWiz#120): the third write, observed in help (0.43.1).
    &["thread", "archive", "thr_syn_0001", "--json"],
    // T5: only inventory and a single verified owned-loop resume.
    &["loop", "list", "--json"],
    &["loop", "resume", "loop_syn_1", "--json"],
    &["loop", "pause", "loop_syn_1", "--json"],
];

/// Arguments that must never be passed, whatever the invocation.
const FORBIDDEN: &[&str] = &[
    "--work-status",
    "--git-diff",
    "log",
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
];

/// Every invocation the adapter can build. The `match` makes a new variant
/// a compile error here, as a reminder to add its forms to `all`; it cannot
/// force that by itself.
fn every_invocation() -> Vec<Invocation> {
    let id = ThreadId::parse("thr_syn_0001").expect("valid id");
    let all = vec![
        Invocation::Version,
        Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        },
        Invocation::ThreadList {
            include_hidden: true,
            include_archived: false,
        },
        Invocation::ThreadList {
            include_hidden: false,
            include_archived: true,
        },
        Invocation::ThreadList {
            include_hidden: true,
            include_archived: true,
        },
        Invocation::ProjectList { hidden: false },
        Invocation::ProjectList { hidden: true },
        Invocation::MachineList,
        Invocation::ThreadShow(id.clone()),
        Invocation::ThreadOutput(id.clone()),
        Invocation::ThreadTell {
            id: id.clone(),
            mode: Mode::Queue,
            text: "Synthetic".to_owned(),
            attachments: vec![],
        },
        Invocation::ThreadTell {
            id,
            mode: Mode::Steer,
            text: "Synthetic".to_owned(),
            attachments: vec![],
        },
        Invocation::CloudStatus,
        Invocation::ThreadSpawn(
            SpawnArgs::new(
                "prj_syn_0001",
                "codex",
                "syn-codex-model-01",
                "high",
                RID,
                "Synthetic",
            )
            .expect("valid spawn arguments"),
        ),
        Invocation::ThreadTell {
            id: ThreadId::parse("thr_syn_0001").expect("valid id"),
            mode: Mode::Queue,
            text: "Synthetic".to_owned(),
            attachments: staged(),
        },
        Invocation::ThreadSpawn(
            SpawnArgs::new(
                "prj_syn_0001",
                "codex",
                "syn-codex-model-01",
                "high",
                RID,
                "Synthetic",
            )
            .expect("valid spawn arguments")
            .with_attachments(staged()),
        ),
        Invocation::CloudThreadWorkspace(ThreadId::parse("thr_syn_0001").expect("valid id")),
        Invocation::ThreadArchive(ThreadId::parse("thr_syn_0001").expect("valid id")),
        Invocation::LoopList,
        Invocation::LoopResume(ThreadId::parse("loop_syn_1").expect("valid id")),
        Invocation::LoopPause(ThreadId::parse("loop_syn_1").expect("valid id")),
    ];
    for invocation in &all {
        match invocation {
            Invocation::Version
            | Invocation::ThreadList { .. }
            | Invocation::ProjectList { .. }
            | Invocation::MachineList
            | Invocation::ThreadShow(_)
            | Invocation::ThreadOutput(_)
            | Invocation::ThreadTell { .. }
            | Invocation::CloudStatus
            | Invocation::ThreadSpawn(_)
            | Invocation::CloudThreadWorkspace(_)
            | Invocation::ThreadArchive(_)
            | Invocation::LoopList
            | Invocation::LoopResume(_)
            | Invocation::LoopPause(_) => {}
        }
    }
    all
}

#[test]
fn allowlist_argv_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 5] = [
        (
            "every_invocation_is_on_the_allowlist",
            every_invocation_is_on_the_allowlist,
        ),
        (
            "hidden_and_archived_flags_are_added_only_on_request",
            hidden_and_archived_flags_are_added_only_on_request,
        ),
        (
            "ids_cannot_become_flags_or_extra_arguments",
            ids_cannot_become_flags_or_extra_arguments,
        ),
        (
            "no_invocation_passes_a_forbidden_argument",
            no_invocation_passes_a_forbidden_argument,
        ),
        (
            "ta3_staged_totals_reach_tell_and_spawn_allowances",
            ta3_staged_totals_reach_tell_and_spawn_allowances,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: p08a_allowlist_static::{name}");
        proof();
    }
}

fn every_invocation_is_on_the_allowlist() {
    let built: Vec<Vec<String>> = every_invocation().iter().map(Invocation::argv).collect();
    let allowed: Vec<Vec<String>> = ALLOWED
        .iter()
        .map(|a| a.iter().map(|w| (*w).to_owned()).collect())
        .collect();
    assert_eq!(built, allowed);
}

fn hidden_and_archived_flags_are_added_only_on_request() {
    let plain = Invocation::ThreadList {
        include_hidden: false,
        include_archived: false,
    }
    .argv();
    assert!(
        !plain
            .iter()
            .any(|a| a == "--include-hidden" || a == "--include-archived")
    );
    assert!(
        !Invocation::ProjectList { hidden: false }
            .argv()
            .iter()
            .any(|a| a == "--hidden")
    );
}

fn no_invocation_passes_a_forbidden_argument() {
    for invocation in every_invocation() {
        let argv = invocation.argv();
        // The two writes: `tell` and `spawn` are their subcommands, and the
        // text after `--` or `--prompt` is not an argument to `room-cli` (it
        // is the message or the prompt).
        // B2: the attachment tail sits before the text's placement; its
        // paths are staged copies, never a word room-cli reads as a command.
        let (checked, allowed): (&[String], &[&str]) = match invocation {
            Invocation::ThreadTell { .. } => {
                assert_eq!(argv[1], "tell");
                let end = argv.len() - 2;
                assert_eq!(argv[end], "--", "the text follows --");
                (&argv[..=end], &["tell"])
            }
            Invocation::ThreadSpawn(_) => {
                assert_eq!(argv[1], "spawn");
                let end = argv.len() - 2;
                assert_eq!(argv[end], "--prompt", "the text follows --prompt");
                (&argv[..=end], &["spawn"])
            }
            // B4: `archive` is the third write's subcommand, and nothing
            // else.
            Invocation::ThreadArchive(_) => {
                assert_eq!(argv[1], "archive");
                (&argv[..], &["archive"])
            }
            _ => (&argv[..], &[]),
        };
        for word in checked {
            assert!(
                !FORBIDDEN.contains(&word.as_str()) || allowed.contains(&word.as_str()),
                "{invocation:?} passes {word}"
            );
        }
        // Every read asks for JSON, except --version, which prints plain text.
        assert!(
            argv == ["--version"] || argv.iter().any(|a| a == "--json"),
            "{argv:?}"
        );
    }
}

fn ids_cannot_become_flags_or_extra_arguments() {
    for bad in [
        "",
        "-",
        "--work-status",
        "-x",
        "thr syn",
        "thr\nsyn",
        "thr;syn",
        "thr/syn",
        "thr=syn",
        "thr\u{0}syn",
        "thr_syn_ÿ",
    ] {
        assert!(ThreadId::parse(bad).is_err(), "accepted {bad:?}");
    }
    assert!(ThreadId::parse(&"a".repeat(THREAD_ID_MAX_LEN + 1)).is_err());
    for good in ["thr_syn_0001", "a", "A-1_b", &"a".repeat(THREAD_ID_MAX_LEN)] {
        let id = ThreadId::parse(good).expect(good);
        let argv = Invocation::ThreadShow(id).argv();
        assert_eq!(argv.len(), 4, "the id stays one argument");
        assert_eq!(argv[2], good);
    }
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read dir") {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}

fn product_sources() -> Vec<(PathBuf, String)> {
    let crates = Path::new(env!("CARGO_MANIFEST_DIR")).join("../crates");
    let mut files = Vec::new();
    rust_files(&crates, &mut files);
    assert!(!files.is_empty());
    files
        .into_iter()
        .map(|p| {
            let text = fs::read_to_string(&p).expect("source");
            (p, text)
        })
        .collect()
}

/// The store's attachment module retains P8(a)'s one fixed program, `/bin/df`.
const FREE_SPACE_MEASURE: &str = "../crates/store/src/attachments.rs";

/// The GitHub adapter's runner: the one source there that may start a
/// process, `gh` with an allowlisted invocation only (#111, Q3 (a)).
const GITHUB_RUNNER: &str = "../crates/adapters/github/src/process.rs";
const GITHUB_APP: &str = "../crates/adapters/github/src/app.rs";

const LOOP_REPOSITORY: &str = "../crates/store/src/loops/repository.rs";
const LOOP_CHECK: &str = "../crates/service/src/loops/check.rs";
const LOOP_EXECUTOR: &str = "../crates/service/src/loops/mod.rs";

/// 0.0.12 T3 (#1098, orchestrator ruling): the CLI's one process start, the
/// visual app's fixed sibling `openwiz-terminal`, by an absolute path from
/// the running binary's own directory; no shell, no `PATH` search.
const TERMINAL_LAUNCHER: &str = "../crates/cli/src/ui.rs";
/// The same ruling's second exception: the Send action's capability id,
/// `"send"`, once, in the terminal crate's action seam.
const TERMINAL_ACTIONS: &str = "../crates/terminal/src/actions/mod.rs";

/// EN1 (#1106), approved 2026-11-07: only the fixed isolated interpreter
/// and installed sibling tool, with the minimized environment. Activation and
/// every other gate remain closed.
/// Private record: https://github.com/jparker2006/ClosedWiz/issues/1106#issuecomment-6714565014
const ENGINE_LAUNCHER: &str = "../crates/cli/src/engine.rs";

#[test]
fn allowlist_source_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 18] = [
        (
            "engine_interpreter_exception_rejects_planted_widening",
            engine_interpreter_exception_rejects_planted_widening,
        ),
        (
            "l3_check_admission_rejects_removed_approval_or_limits",
            l3_check_admission_rejects_removed_approval_or_limits,
        ),
        (
            "l3_check_exception_rejects_planted_breaks",
            l3_check_exception_rejects_planted_breaks,
        ),
        (
            "l3_exceptions_reject_aliased_process_starts",
            l3_exceptions_reject_aliased_process_starts,
        ),
        (
            "l3_repository_exception_rejects_planted_breaks",
            l3_repository_exception_rejects_planted_breaks,
        ),
        (
            "no_product_source_spells_a_forbidden_argument",
            no_product_source_spells_a_forbidden_argument,
        ),
        (
            "only_the_adapter_can_start_a_process_and_only_from_the_allowlist",
            only_the_adapter_can_start_a_process_and_only_from_the_allowlist,
        ),
        (
            "service_update_field_exception_catches_command_like_literals",
            service_update_field_exception_catches_command_like_literals,
        ),
        (
            "t13_key_helper_keeps_one_fixed_descriptor_handover",
            t13_key_helper_keeps_one_fixed_descriptor_handover,
        ),
        (
            "t2_linux_owner_query_keeps_the_existing_kernel_boundary",
            t2_linux_owner_query_keeps_the_existing_kernel_boundary,
        ),
        (
            "t2_store_retains_p8s_single_program_exception",
            t2_store_retains_p8s_single_program_exception,
        ),
        (
            "t7_app_guards_catch_extra_programs_arguments_environments_and_endpoints",
            t7_app_guards_catch_extra_programs_arguments_environments_and_endpoints,
        ),
        (
            "t7_signing_argv_uses_only_the_pinned_descriptor_path",
            t7_signing_argv_uses_only_the_pinned_descriptor_path,
        ),
        (
            "t7_the_approved_app_runner_preserves_the_personal_runner",
            t7_the_approved_app_runner_preserves_the_personal_runner,
        ),
        (
            "t7_the_token_endpoint_rejects_suffixes",
            t7_the_token_endpoint_rejects_suffixes,
        ),
        (
            "the_github_runner_rule_catches_a_planted_break",
            the_github_runner_rule_catches_a_planted_break,
        ),
        (
            "the_terminal_exceptions_refuse_any_widening",
            the_terminal_exceptions_refuse_any_widening,
        ),
        (
            "updater_runner_exception_still_rejects_extra_effects",
            updater_runner_exception_still_rejects_extra_effects,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: p08a_allowlist_static::{name}");
        proof();
    }
}

fn only_the_adapter_can_start_a_process_and_only_from_the_allowlist() {
    let adapter = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../crates/adapters/cloudroom")
        .canonicalize()
        .expect("adapter dir");
    let measure = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(FREE_SPACE_MEASURE)
        .canonicalize()
        .expect("the free-space measure");
    let github_runner = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(GITHUB_RUNNER)
        .canonicalize()
        .expect("the GitHub runner");
    let mut measured = false;
    let mut ran = false;
    let app = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(GITHUB_APP)
        .canonicalize()
        .unwrap();
    let mut signed = false;
    let updater = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../crates/service/src/update.rs")
        .canonicalize()
        .unwrap();
    let mut updated = false;
    let launcher = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(TERMINAL_LAUNCHER)
        .canonicalize()
        .expect("the terminal launcher");
    let mut launched = false;
    let engine_launcher = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(ENGINE_LAUNCHER)
        .canonicalize()
        .expect("the engine launcher");
    let mut engine_launched = false;
    let canonical_loop = |file| {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(file)
            .canonicalize()
            .expect("canonical L3 source")
    };
    let loop_repository = canonical_loop(LOOP_REPOSITORY);
    let loop_check = canonical_loop(LOOP_CHECK);
    let loop_executor = canonical_loop(LOOP_EXECUTOR);
    let mut checked_loops = [false; 3];
    for (path, text) in product_sources() {
        let starts_process = text.contains("process::Command")
            || text.contains("Command::new")
            || text.contains("process::{");
        let canonical = path.canonicalize().expect("path");
        let in_adapter = canonical.starts_with(&adapter);
        // Exact canonical files, never the loops directory as a whole.
        if canonical == loop_repository {
            assert_eq!(l3_repository_problems(&text), Vec::<String>::new());
            checked_loops[0] = true;
            continue;
        }
        if canonical == loop_check {
            assert_eq!(l3_check_problems(&text), Vec::<String>::new());
            checked_loops[1] = true;
            continue;
        }
        if canonical == loop_executor {
            assert_eq!(l3_executor_problems(&text), Vec::<String>::new());
            checked_loops[2] = true;
            // The executor itself gains no process-start exception.
        } else {
            assert!(
                !l3_compact(&text).contains("check::run("),
                "{path:?}: ungated check caller"
            );
        }
        if canonical == updater {
            assert_eq!(
                updater_runner_problems(&text),
                Vec::<String>::new(),
                "T6 updater runner"
            );
            updated = true;
            continue;
        }
        if canonical == measure {
            the_free_space_measure_runs_only_bin_df(&text);
            measured = true;
            continue;
        }
        if canonical == github_runner {
            assert_eq!(
                github_runner_problems(&text),
                Vec::<String>::new(),
                "{GITHUB_RUNNER}"
            );
            ran = true;
            continue;
        }
        if canonical == launcher {
            assert_eq!(
                terminal_launcher_problems(&text),
                Vec::<String>::new(),
                "{TERMINAL_LAUNCHER}"
            );
            launched = true;
            continue;
        }
        if canonical == engine_launcher {
            assert_eq!(
                engine_launcher_problems(&text),
                Vec::<String>::new(),
                "{ENGINE_LAUNCHER}"
            );
            engine_launched = true;
            continue;
        }
        if canonical == app {
            assert_eq!(
                app_source_problems(&text),
                Vec::<String>::new(),
                "{GITHUB_APP}"
            );
            signed = true;
            continue;
        }
        assert!(
            !starts_process || in_adapter,
            "{path:?} starts a process outside the canonical permitted sources"
        );
        if in_adapter {
            assert!(
                !text.contains(".arg("),
                "{path:?}: arguments come only from Invocation::argv"
            );
            for (i, _) in text.match_indices(".args(") {
                let call = &text[i..text[i..].find(')').map_or(text.len(), |j| i + j + 1)];
                assert!(
                    call.contains("argv("),
                    "{path:?}: {call} is not Invocation::argv"
                );
            }
        }
    }
    assert!(measured, "{FREE_SPACE_MEASURE} was not checked");
    assert!(ran, "{GITHUB_RUNNER} was not checked");
    assert!(signed, "{GITHUB_APP} was not checked");
    assert!(updated, "the canonical updater runner was not checked");
    assert!(launched, "{TERMINAL_LAUNCHER} was not checked");
    assert!(engine_launched, "{ENGINE_LAUNCHER} was not checked");
    assert_eq!(checked_loops, [true; 3], "all canonical L3 gates checked");
}

// Normalize layout and discard comments, retaining literal contents. A cited
// gate in a comment must not stand in for the operative function or call.
fn l3_compact(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(end) = l3_literal_end(bytes, i) {
            out.extend_from_slice(&bytes[i..end]);
            i = end;
        } else if bytes[i..].starts_with(b"//") {
            i += bytes[i..]
                .iter()
                .position(|b| *b == b'\n')
                .unwrap_or(bytes.len() - i);
        } else if bytes[i..].starts_with(b"/*") {
            let mut depth = 1;
            i += 2;
            while i < bytes.len() && depth > 0 {
                if bytes[i..].starts_with(b"/*") {
                    depth += 1;
                    i += 2;
                } else if bytes[i..].starts_with(b"*/") {
                    depth -= 1;
                    i += 2;
                } else {
                    i += 1;
                }
            }
        } else {
            if !bytes[i].is_ascii_whitespace() {
                out.push(bytes[i]);
            }
            i += 1;
        }
    }
    String::from_utf8(out).unwrap()
}

fn l3_literal_end(bytes: &[u8], start: usize) -> Option<usize> {
    let quote = bytes[start];
    if quote != b'"' && quote != b'\'' {
        return None;
    }
    let mut i = start + 1;
    while i < bytes.len() {
        if bytes[i] == b'\\' {
            i += 2;
        } else if bytes[i] == quote {
            return Some(i + 1);
        }
        // An apostrophe naming a lifetime is not a character literal.
        else if quote == b'\'' && (bytes[i].is_ascii_whitespace() || i > start + 4) {
            return None;
        } else {
            i += 1;
        }
    }
    None
}

fn l3_function<'a>(code: &'a str, signature: &str) -> Option<&'a str> {
    let bytes = code.as_bytes();
    let mut i = 0;
    let mut found = None;
    while i < bytes.len() {
        if let Some(end) = l3_literal_end(bytes, i) {
            i = end;
            continue;
        }
        if code[i..].starts_with(signature) {
            if found.is_some() {
                return None;
            }
            let start = i;
            i += signature.len();
            if bytes.get(i) != Some(&b'{') {
                return None;
            }
            let mut depth = 0;
            loop {
                match *bytes.get(i)? {
                    b'{' => depth += 1,
                    b'}' => depth -= 1,
                    _ => {}
                }
                i += 1;
                if depth == 0 {
                    break;
                }
                if let Some(end) = l3_literal_end(bytes, i) {
                    i = end;
                }
            }
            found = Some(&code[start..i]);
        } else {
            // Move over a complete UTF-8 character outside literals too.
            i += code[i..].chars().next()?.len_utf8();
        }
    }
    found
}

fn l3_exact_function(problems: &mut Vec<String>, code: &str, signature: &str, expected: &str) {
    let signature = l3_compact(signature);
    if l3_function(code, &signature) != Some(l3_compact(expected).as_str()) {
        problems.push(format!("changed or missing {signature}"));
    }
}

fn l3_counts(problems: &mut Vec<String>, code: &str, counts: &[(&str, usize)]) {
    for &(marker, expected) in counts {
        if code.matches(marker).count() != expected {
            problems.push(format!("{marker}: expected {expected}"));
        }
    }
}

fn l3_repository_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("structGitRead(Vec<String>);", 1),
            ("GitRead(", 1),
            ("Self(", 1),
            ("Command::new(", 1),
            // Count qualified calls too: C::new/C::spawn must not hide
            // behind unchanged Command::new/.spawn counts (#1015).
            ("::new(", 9),
            ("Vec::new(", 2),
            ("BTreeSet::new(", 1),
            ("model::NonEmpty::new(", 1),
            ("NonZeroU64::new(", 2),
            ("NewThreadRequest::new(", 1),
            ("fs::DirBuilder::new(", 1),
            ("::spawn(", 0),
            ("::status(", 0),
            ("::output(", 0),
            ("::exec(", 0),
            ("Commandas", 0),
            ("processas", 0),
            // The existing import and the synthetic test's process id.
            ("process::", 2),
            ("process::Command,", 1),
            ("std::process::id()", 1),
            (".arg(", 4),
            (".args(", 2),
            (".output(", 1),
            (".spawn(", 0),
            (".status(", 0),
            (".exec(", 0),
            (".env(", 5),
            (".envs(", 0),
            (".env_clear(", 1),
            (".env_remove(", 0),
            (".current_dir(", 0),
            ("check::run(", 0),
            ("run_git(", 3),
        ],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn parse(args: &[&str]) -> Result<Self, String>",
        r#"
        fn parse(args: &[&str]) -> Result<Self, String> {
            let allowed = match args {
                ["config", "--local", "--no-includes", "--null", "--list"] => true,
                ["rev-parse", "--verify", "refs/remotes/origin/HEAD^{commit}" | "HEAD^{commit}",] => true,
                ["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--name-only",] => true,
                ["ls-tree", "-z", tree] => tree.strip_suffix(":loops").is_some_and(revision),
                ["ls-tree", "-z", commit, "--", "loops"] => revision(commit),
                ["cat-file", "blob", id] => revision(id),
                _ => false,
            };
            if !allowed { return Err("local Git read is not allowlisted".to_owned()); }
            Ok(Self(args.iter().map(|arg| (*arg).to_owned()).collect()))
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn argv(&self) -> &[String]",
        r#"
        fn argv(&self) -> &[String] { &self.0 }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn revision(s: &str) -> bool",
        r#"
        fn revision(s: &str) -> bool {
            matches!(s.len(), 40 | 64) && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn git(root: &Path, args: &[&str]) -> Result<Vec<u8>, String>",
        r#"
        fn git(root: &Path, args: &[&str]) -> Result<Vec<u8>, String> {
            let read = GitRead::parse(args)?;
            let root = root.canonicalize().map_err(|_| "cannot resolve loop checkout".to_owned())?;
            let config = GitRead::parse(&["config", "--local", "--no-includes", "--null", "--list"])?;
            validate_config(&run_git(&root, &config)?)?;
            run_git(&root, &read)
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn run_git(root: &Path, read: &GitRead) -> Result<Vec<u8>, String>",
        r#"
        fn run_git(root: &Path, read: &GitRead) -> Result<Vec<u8>, String> {
            let out = Command::new("git")
                .env_clear()
                .env("PATH", "/usr/bin:/bin")
                .env("GIT_CONFIG_GLOBAL", "/dev/null")
                .env("GIT_CONFIG_SYSTEM", "/dev/null")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_OPTIONAL_LOCKS", "0")
                .args(["-c", "core.fsmonitor=false"])
                .arg("-C").arg(root).arg("--work-tree").arg(root).args(read.argv()).output()
                .map_err(|_| "cannot read loop checkout".to_owned())?;
            if !out.status.success() {
                return Err("cannot resolve immutable default-branch definitions".to_owned());
            }
            Ok(out.stdout)
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn validate_config(bytes: &[u8]) -> Result<(), String>",
        r#"
        fn validate_config(bytes: &[u8]) -> Result<(), String> {
            let refused = || "loop checkout configuration is not allowlisted".to_owned();
            let config = std::str::from_utf8(bytes).map_err(|_| refused())?;
            if !config.is_empty() && !config.ends_with('\0') { return Err(refused()); }
            for entry in config.split_terminator('\0') {
                let (key, value) = entry.split_once('\n').ok_or_else(refused)?;
                if !allowed_config(key, value) { return Err(refused()); }
            }
            Ok(())
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn config_boolean(value: &str) -> bool",
        r#"
        fn config_boolean(value: &str) -> bool {
            matches!(value.to_ascii_lowercase().as_str(), "true" | "false" | "yes" | "no" | "on" | "off" | "1" | "0")
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn allowed_config(key: &str, value: &str) -> bool",
        r#"
        fn allowed_config(key: &str, value: &str) -> bool {
            if !key.is_ascii() || key.bytes().any(|b| b.is_ascii_control()) { return false; }
            match key {
                "core.repositoryformatversion" => return matches!(value, "0" | "1"),
                "core.bare" => { return matches!(value.to_ascii_lowercase().as_str(), "false" | "no" | "off" | "0"); }
                "core.filemode" | "core.symlinks" | "core.ignorecase" | "core.precomposeunicode"
                | "commit.gpgsign" => return config_boolean(value),
                "core.logallrefupdates" => return config_boolean(value) || value == "always",
                "extensions.objectformat" => return matches!(value, "sha1" | "sha256"),
                "extensions.partialclone" => return !value.is_empty(),
                "core.fsmonitor" | "core.worktree" | "core.hookspath" | "user.name" | "user.email"
                | "user.signingkey" | "diff.external" => return true,
                _ => {}
            }
            let Some((section, rest)) = key.split_once('.') else { return false; };
            let Some((name, field)) = rest.rsplit_once('.') else { return false; };
            if name.is_empty() { return false; }
            match (section, field) {
                ("branch", "remote" | "merge")
                | ("remote", "url" | "fetch" | "partialclonefilter")
                | ("diff", "textconv") => true,
                ("remote", "promisor") => config_boolean(value),
                _ => false,
            }
        }
    "#,
    );
    problems
}

fn l3_check_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("Command::new(", 2),
            ("::new(", 3),
            ("Vec::new(", 1),
            // Only the existing pipe-reader thread uses qualified spawn.
            ("::spawn(", 1),
            ("thread::spawn(", 1),
            ("::status(", 0),
            ("::output(", 0),
            ("::exec(", 0),
            ("Commandas", 0),
            ("processas", 0),
            ("process::", 2),
            ("process::{Command,Stdio},", 1),
            ("os::unix::process::CommandExt,", 1),
            (".arg(", 0),
            (".args(", 2),
            (".current_dir(", 1),
            (".process_group(", 1),
            (".spawn(", 1),
            (".status(", 1),
            (".output(", 0),
            (".exec(", 0),
            (".env(", 0),
            (".envs(", 0),
            (".env_clear(", 0),
            (".env_remove(", 0),
            ("check::run(", 0),
        ],
    );
    let signature = "pubfnrun(root:&Path,check:&Value,clock:&dynClock)->Value";
    let body = l3_function(&code, signature).unwrap_or_default();
    let before_spawn = l3_compact(
        r#"
        pub fn run(root: &Path, check: &Value, clock: &dyn Clock) -> Value {
            let argv = check["argv"].as_array().unwrap();
            let Some(deadline) = clock.monotonic()
                .checked_add(Duration::from_millis(check["timeout_ms"].as_u64().unwrap()))
            else { return failed(); };
            let mut child = match Command::new(argv[0].as_str().unwrap())
                .args(argv[1..].iter().map(|s| s.as_str().unwrap()))
                .current_dir(root).stdin(Stdio::null()).stdout(Stdio::piped())
                .stderr(Stdio::null()).process_group(0).spawn()
            { Ok(child) => child, Err(_) => return failed(), };
    "#,
    );
    if !body.starts_with(&before_spawn) {
        problems.push("check argv/cwd/deadline before spawn changed".to_owned());
    }
    for required in [
        r#"let result = loop { if clock.monotonic() >= deadline { break json!({"kind":"check_timed_out"}); }"#,
        "if let (Some(status), Some(output)) = (&status, &output)",
        r#"let _ = Command::new("/bin/kill").args(["-KILL", "--", &format!("-{}", child.id())])
            .stdout(Stdio::null()).stderr(Stdio::null()).status();
            let _ = child.kill(); let _ = child.wait();"#,
    ] {
        if !body.contains(&l3_compact(required)) {
            problems.push(format!("missing check gate: {required}"));
        }
    }
    problems
}

fn l3_executor_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[("check::run(", 1), ("modcheck;", 1)],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn approved(&self, d: &Definition) -> bool",
        r#"
        fn approved(&self, d: &Definition) -> bool {
            self.services.approval.as_ref().is_some_and(|approval| approval.verify(&d.value, &d.revision))
        }
    "#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn valid_limits(&self) -> Result<Limits, String>",
        r#"
        fn valid_limits(&self) -> Result<Limits, String> {
            let limits = self.config.limits.ok_or("shared loop capacities were not supplied")?;
            if [limits.checks, limits.agents].iter().any(|c| c.urgent_reserve > c.max) {
                return Err("invalid shared loop capacities".to_owned());
            }
            Ok(limits)
        }
    "#,
    );
    let snapshot = l3_function(&code, "fnsnapshot(&self,repo:&Repository,definitions:&[Definition],runs:&[Value],switches:&serde_json::Map<String,Value>,)->Result<model::Snapshot,String>").unwrap_or_default();
    if !snapshot.contains(&l3_compact(r#"
        let definitions = definitions.iter().map(|d| {
            d.project(switches[d.value["id"].as_str().unwrap()].as_bool().unwrap() && self.approved(d),)
        }).collect();
    "#)) { problems.push("snapshot does not require exact definition approval".to_owned()); }
    let pass =
        l3_function(&code, "pubfnpass(&self)->Result<Vec<Value>,String>").unwrap_or_default();
    let mut previous = 0;
    for required in [
        "let limits = match self.valid_limits()",
        "let definitions = repository.current()?;",
        "let snapshot = self.snapshot(&repository, &definitions, &runs, &switches)?;",
        "let plan = model::plan(&snapshot, self.now()?, &limits)",
        r#"if let model::Action::Check { loop_id, revision, occurrence: model::Occurrence::Scheduled { due_at_ms }, } = action"#,
        r#"let d = definitions.iter().find(|d| d.value["id"] == loop_id.as_str() && d.revision == revision.as_str()).ok_or("missing planned definition")?;"#,
        r#"let mut result = check::run(&self.config.checkout, &d.value["check"], self.services.clock.as_ref(),);"#,
    ] {
        match pass[previous..].find(&l3_compact(required)) {
            Some(at) => previous += at + l3_compact(required).len(),
            None => problems.push(format!("missing or reordered admission gate: {required}")),
        }
    }
    // No new CloudRoom route: the existing validation and preview still
    // precede durable reservation and the existing new_thread operation.
    for required in [
        "if !self.approved(&definition)",
        "if request.validate().is_err()",
        "let ready = preview_new_thread(",
        "if !ready || !self.approved(&definition)",
        "let _ = new_thread(",
    ] {
        if !pass.contains(&l3_compact(required)) {
            problems.push(format!("missing existing new-thread gate: {required}"));
        }
    }
    problems
}

fn l3_plant(code: &str, from: &str, to: &str) -> String {
    let from = l3_compact(from);
    assert_eq!(
        code.matches(&from).count(),
        1,
        "plant must replace one operative {from}"
    );
    code.replacen(&from, &l3_compact(to), 1)
}

fn l3_repository_exception_rejects_planted_breaks() {
    let code = l3_compact(include_str!("../../crates/store/src/loops/repository.rs"));
    assert!(l3_repository_problems(&code).is_empty());
    for (from, to) in [
        (r#"Command::new("git")"#, r#"Command::new("room-cli")"#),
        (".env_clear()", ""),
        (
            r#".env("PATH", "/usr/bin:/bin")"#,
            r#".env("PATH", "/tmp")"#,
        ),
        (r#".env("GIT_CONFIG_GLOBAL", "/dev/null")"#, ""),
        (r#".env("GIT_CONFIG_SYSTEM", "/dev/null")"#, ""),
        (r#".env("GIT_NO_LAZY_FETCH", "1")"#, ""),
        (r#".env("GIT_OPTIONAL_LOCKS", "0")"#, ""),
        (r#".args(["-c", "core.fsmonitor=false"])"#, ""),
        (".args(read.argv())", ".args(args)"),
        (
            ".args(read.argv())",
            r#".args(read.argv()).arg("--synthetic-extra")"#,
        ),
        ("let read = GitRead::parse(args)?;", ""),
        (
            r#"["cat-file", "blob", id] => revision(id), _ => false,"#,
            r#"["cat-file", "blob", id] => revision(id), _ => true,"#,
        ),
        ("validate_config(&run_git(&root, &config)?)?;", ""),
        (
            "validate_config(&run_git(&root, &config)?)?;",
            "validate_config(b\"\")?;",
        ),
        ("if !allowed_config(key, value)", "if false"),
        (
            "if !config.is_empty() && !config.ends_with('\\0')",
            "if false",
        ),
        ("if name.is_empty()", "if false"),
        ("_ => {}", "_ => { return true; }"),
        (
            r#""user.signingkey" | "diff.external" => return true,"#,
            r#""user.signingkey" | "diff.external" | "include.path" | "filter.synthetic.clean" | "filter.synthetic.process" | "extensions.worktreeconfig" => return true,"#,
        ),
        (
            r#"let root = root.canonicalize().map_err(|_| "cannot resolve loop checkout".to_owned())?;"#,
            "let root = root.to_path_buf();",
        ),
        (r#".arg("--work-tree").arg(root)"#, ""),
        (
            r#".arg("--work-tree").arg(root)"#,
            r#".arg("--work-tree").arg("/synthetic/other")"#,
        ),
        (
            r#"["config", "--local", "--no-includes", "--null", "--list"] => true,"#,
            r#"["config", "--local", "--includes", "--null", "--list"] => true,"#,
        ),
        (
            r#"["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--name-only",] => true,"#,
            r#"["fetch", "origin"] => true,"#,
        ),
        (
            r#"["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--name-only",] => true,"#,
            r#"["diff", "--no-textconv", "HEAD", "--name-only",] => true,"#,
        ),
        (
            r#"["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--name-only",] => true,"#,
            r#"["diff", "--no-ext-diff", "HEAD", "--name-only",] => true,"#,
        ),
        (
            r#"["cat-file", "blob", id] => revision(id),"#,
            r#"["cat-file", "blob", _] => true,"#,
        ),
        (
            r#"tree.strip_suffix(":loops").is_some_and(revision)"#,
            "true",
        ),
        (
            r#"["ls-tree", "-z", commit, "--", "loops"] => revision(commit),"#,
            r#"["ls-tree", "-z", commit, "--", "loops"] => true,"#,
        ),
        (
            r#"["ls-tree", "-z", commit, "--", "loops"] => revision(commit),"#,
            r#"["ls-tree", "-z", commit, "--", _target] => revision(commit),"#,
        ),
        ("matches!(s.len(), 40 | 64)", "true"),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !l3_repository_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    let extra = format!("{code}fn extra() {{ Command::new(\"git\").output(); }}");
    assert!(!l3_repository_problems(&extra).is_empty());
}

fn l3_check_exception_rejects_planted_breaks() {
    let code = l3_compact(include_str!("../../crates/service/src/loops/check.rs"));
    assert!(l3_check_problems(&code).is_empty());
    for (from, to) in [
        (
            "Command::new(argv[0].as_str().unwrap())",
            r#"Command::new("sh")"#,
        ),
        (
            ".args(argv[1..].iter().map(|s| s.as_str().unwrap()))",
            ".args(arbitrary_arguments)",
        ),
        (
            ".current_dir(root)",
            r#".current_dir("/synthetic/other-root")"#,
        ),
        (
            ".current_dir(root)",
            r#".arg("synthetic-extra").current_dir(root)"#,
        ),
        (".process_group(0)", ".process_group(1)"),
        ("check[\"timeout_ms\"].as_u64().unwrap()", "u64::MAX"),
        (
            "if clock.monotonic() >= deadline",
            "if false /* if clock.monotonic() >= deadline */",
        ),
        (
            "&format!(\"-{}\", child.id())",
            "&format!(\"-{}\", std::process::id())",
        ),
        ("&format!(\"-{}\", child.id())", "&caller_supplied_target"),
        (
            "&format!(\"-{}\", child.id())",
            "&format!(\"{}\", child.id())",
        ),
        ("\"-KILL\", \"--\"", "\"-TERM\", \"--\""),
        (
            r#"Command::new("/bin/kill")"#,
            r#"Command::new("/bin/kill").arg("-1")"#,
        ),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !l3_check_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    let extra = format!("{code}fn extra() {{ Command::new(\"sh\").spawn(); }}");
    assert!(!l3_check_problems(&extra).is_empty());
}

// #1015: extra starts must fail even when literal Command::new/.spawn
// counts stay unchanged. Mutate copies only; no planted command is executed.
fn l3_exceptions_reject_aliased_process_starts() {
    let mut missed = Vec::new();
    for (name, text, inspect) in [
        (
            "repository",
            include_str!("../../crates/store/src/loops/repository.rs"),
            l3_repository_problems as fn(&str) -> Vec<String>,
        ),
        (
            "check",
            include_str!("../../crates/service/src/loops/check.rs"),
            l3_check_problems as fn(&str) -> Vec<String>,
        ),
    ] {
        assert!(inspect(text).is_empty(), "clean {name}");
        for extra in [
            r#"use std::process::Command as C;
                fn extra() { let _ = C::spawn(&mut C::new("/bin/true")); }"#,
            r#"use std::process::{Command as C};
                fn extra() { let _ = C::spawn(&mut C::new("/bin/true")); }"#,
            r#"type C = Command;
                fn extra() { let _ = C::spawn(&mut C::new("/bin/true")); }"#,
            r#"fn extra(c: &mut Command) { let _ = Command::spawn(c); }"#,
            r#"type C = Command; fn extra() { let _ = C::new("/bin/true"); }"#,
            "use std::process::{self};",
            "use std::process as p;",
            "use std::{process as p};",
            "use std::process::Command;",
            "use std::process::Command as C;",
            "use Command as C;",
        ] {
            if inspect(&format!("{text}\n{extra}")).is_empty() {
                missed.push((name, extra));
            }
        }
    }
    assert!(missed.is_empty(), "missed planted breaks: {missed:#?}");
}

fn l3_check_admission_rejects_removed_approval_or_limits() {
    let code = l3_compact(include_str!("../../crates/service/src/loops/mod.rs"));
    assert!(l3_executor_problems(&code).is_empty());
    for (from, to) in [
        (
            ".is_some_and(|approval| approval.verify(&d.value, &d.revision))",
            ".is_none()",
        ),
        ("&& self.approved(d)", "/* && self.approved(d) */"),
        (
            "let limits = match self.valid_limits()",
            "let limits = match Ok(arbitrary_limits)",
        ),
        ("c.urgent_reserve > c.max", "false"),
        (
            "let plan = model::plan(&snapshot, self.now()?, &limits).map_err(|_| \"invalid loop snapshot\".to_owned())?;",
            "let plan = arbitrary_plan(&snapshot)?;",
        ),
        ("&d.value[\"check\"],", "&unverified_check,"),
        ("if request.validate().is_err()", "if false"),
        ("if !ready || !self.approved(&definition)", "if !ready"),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !l3_executor_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
}

fn updater_runner_problems(text: &str) -> Vec<String> {
    let mut problems = Vec::new();
    for (marker, count) in [
        ("Command::new(", 1),
        ("Command::new(call.program())", 1),
        (".args(", 1),
        (".args(call.argv())", 1),
        (".current_dir(call.directory())", 1),
        (".process_group(0)", 1),
        (".stdin(Stdio::null())", 1),
        (".stdout(Stdio::null())", 1),
        (".stderr(Stdio::null())", 1),
        ("if !allows_command(call.program(), &args)", 1),
        (".env(", 7),
        (".env_remove(", 0),
        (".envs(", 0),
        (".env_clear(", 1),
        (".arg(", 0),
        (".env(\"OPENWIZ_SERVICE_BUILD\", call.commit.as_str())", 1),
        (".env(\"CIRCLE_NODE_TOTAL\", \"2\")", 1),
        (".env(\"CARGO_BUILD_JOBS\", \"2\")", 1),
        (".env(\"LANG\", \"C.UTF-8\")", 1),
        (".env(key, value)", 1),
        ("for key in GATE_ENV", 1),
        (".env(\"GIT_TERMINAL_PROMPT\", \"0\")", 1),
        (".env(\"GIT_CONFIG_NOSYSTEM\", \"1\")", 1),
        (".spawn()", 1),
        (".status()", 1),
        (".exec()", 1),
        ("pub fn new(", 0),
        ("pub program:", 0),
        ("pub argv:", 0),
    ] {
        if text.matches(marker).count() != count {
            problems.push(format!("{marker}: expected {count}"));
        }
    }
    let compact: String = text.split_whitespace().collect();
    if !compact.contains("constGATE_ENV:&[&str]=&[\"PATH\",\"HOME\",\"CARGO_HOME\",\"RUSTUP_HOME\",\"OPENWIZ_CHROMIUM\",];") {
        problems.push("gate environment is not the exact tool allowlist".to_owned());
    }
    problems
}

fn updater_runner_exception_still_rejects_extra_effects() {
    let text = include_str!("../../crates/service/src/update.rs");
    assert!(updater_runner_problems(text).is_empty());
    for bad in [
        text.replace(".env_clear()", ""),
        text.replace(
            "\"OPENWIZ_CHROMIUM\",",
            "\"OPENWIZ_CHROMIUM\", \"OPENWIZ_STATE_DIR\",",
        ),
        text.replace("Command::new(call.program())", "Command::new(\"room-cli\")"),
        text.replace(
            ".args(call.argv())",
            ".args(call.argv()).arg(\"synthetic-extra\")",
        ),
        text.replace(".args(call.argv())", ".args(arbitrary_arguments)"),
        text.replace("if !allows_command(call.program(), &args)", "if false"),
        text.replace(
            ".env(\"CIRCLE_NODE_TOTAL\", \"2\")",
            ".env(\"SYNTHETIC_UNAPPROVED\", \"2\")",
        ),
        format!("{text}\nfn bad() {{ Command::new(\"room-cli\").spawn(); }}"),
    ] {
        assert!(!updater_runner_problems(&bad).is_empty());
    }
}

/// #111's one exception for GitHub, and nothing more: one process, of the
/// program it is given, with exactly an `Invocation`'s argv, stdin closed
/// and both outputs piped, in exactly that call. No other argument,
/// variable or directory can be given, and nothing else is started.
fn github_runner_problems(text: &str) -> Vec<String> {
    let Some((personal, app)) = split_app_runner(text) else {
        return vec!["missing or repeated App runner boundary".to_owned()];
    };
    let text = personal.as_str();
    let mut problems = app_runner_problems(app);
    for needle in [
        "Command::new(",
        "Command::new(program)",
        "invocation: &Invocation,",
        ".args(invocation.argv())",
        ".args(",
        "use std::process::{Child, Command, Stdio};",
    ] {
        let n = text.matches(needle).count();
        if n != 1 {
            problems.push(format!("names {needle:?} {n} times, not once"));
        }
    }
    for word in [
        ".arg(",
        ".env(",
        ".envs(",
        ".env_clear(",
        ".env_remove(",
        ".current_dir(",
        ".status(",
        ".output(",
        "process::Command",
        "CommandExt",
        "room-cli",
        "room_cli",
    ] {
        if text.contains(word) {
            problems.push(format!("names {word:?}"));
        }
    }
    let call: String = text
        .split("Command::new(program)")
        .nth(1)
        .and_then(|rest| rest.split(".spawn()").next())
        .unwrap_or_default()
        .split_whitespace()
        .collect();
    if call
        != ".args(invocation.argv()).stdin(Stdio::null()).stdout(Stdio::piped())\
            .stderr(Stdio::piped())"
    {
        problems.push(format!("the call is {call:?}"));
    }
    problems
}

fn t7_the_approved_app_runner_preserves_the_personal_runner() {
    let real =
        fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_RUNNER)).unwrap();
    assert!(
        github_runner_problems(&real).is_empty(),
        "only the approved App extension may join the unchanged personal runner"
    );
}

/// The GitHub runner's rule catches each break it exists for, planted in a
/// copy of the real runner.
fn the_github_runner_rule_catches_a_planted_break() {
    let whole = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_RUNNER))
        .expect("the GitHub runner");
    let (real, app) = split_app_runner(&whole).unwrap();
    let plant = |from: &str, to: &str| {
        assert_eq!(
            real.matches(from).count(),
            1,
            "{from:?} is in the runner once"
        );
        real.replacen(from, to, 1)
    };
    for (why, planted) in [
        (
            "an extra argument",
            plant(
                ".args(invocation.argv())",
                ".args(invocation.argv()).arg(\"--repo\")",
            ),
        ),
        (
            "arguments not from an invocation",
            plant(".args(invocation.argv())", ".args([\"api\", \"user\"])"),
        ),
        (
            "a variable",
            plant(
                ".stdin(Stdio::null())",
                ".env(\"GH_REPO\", \"x\").stdin(Stdio::null())",
            ),
        ),
        (
            "an open stdin",
            plant(".stdin(Stdio::null())", ".stdin(Stdio::inherit())"),
        ),
        (
            "a second process",
            plant(
                "Command::new(program)",
                "Command::new(program); Command::new(program)",
            ),
        ),
        (
            "another program",
            plant("Command::new(program)", "Command::new(\"sh\")"),
        ),
        (
            "arguments of any kind",
            plant("invocation: &Invocation,", "invocation: &[String],"),
        ),
    ] {
        let full = format!("{planted}{APP_START}{app}{APP_END}");
        assert!(!github_runner_problems(&full).is_empty(), "missed {why}");
    }
}

const APP_START: &str =
    "// T7 App runner. The personal runner above retains its original spawn chain.";
const APP_END: &str = "// End T7 App runner.";
fn split_app_runner(text: &str) -> Option<(String, &str)> {
    if text.matches(APP_START).count() != 1 || text.matches(APP_END).count() != 1 {
        return None;
    }
    let (before, rest) = text.split_once(APP_START)?;
    let (app, after) = rest.split_once(APP_END)?;
    Some((format!("{before}{after}"), app))
}
fn compact(text: &str) -> String {
    text.split_whitespace().collect()
}
fn chain(text: &str, constructor: &str) -> String {
    text.split_once(constructor)
        .and_then(|(_, s)| s.split_once(".spawn()"))
        .map(|(s, _)| compact(s))
        .unwrap_or_default()
}
fn app_runner_problems(text: &str) -> Vec<String> {
    let mut errors = Vec::new();
    for (word, count) in [
        ("Command::new(", 1),
        ("Command::new(program)", 1),
        (".args(", 1),
        (".arg(", 0),
        (".env(", 4),
        (".env_clear(", 1),
        (".spawn()", 1),
        ("call: &Invocation,", 1),
        ("pub(crate) fn run_app(", 1),
        ("pub(crate) fn app_output(", 1),
    ] {
        if text.matches(word).count() != count {
            errors.push(format!("App runner: {word}"));
        }
    }
    for word in [
        ".envs(",
        ".env_remove(",
        ".current_dir(",
        ".output(",
        ".status(",
        "process::Command",
        "CommandExt",
        "room-cli",
        "room_cli",
    ] {
        if text.contains(word) {
            errors.push(format!("App runner: {word}"));
        }
    }
    if chain(text, "Command::new(program)")
        != ".args(call.argv()).env_clear().env(\"GH_TOKEN\",credential).env(\"GH_REPO\",repository).env(\"GH_HOST\",\"github.com\").env(\"PATH\",\"/usr/bin:/bin\").stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped())"
    {
        errors.push("App child spawn changed".to_owned());
    }
    errors
}
fn app_source_problems(text: &str) -> Vec<String> {
    let mut errors = Vec::new();
    for (word, count) in [
        // GI5 (#2547, J26): a second fixed curl call, its status read.
        ("Command::new(", 4),
        ("Command::new(PYTHON_PROGRAM)", 1),
        ("Command::new(CURL_PROGRAM)", 2),
        ("Command::new(OPENSSL_PROGRAM)", 1),
        (".args(", 4),
        (".arg(", 2),
        (".env_clear(", 4),
        (".env(", 0),
        (".spawn()", 4),
        ("https://", 2),
        ("http://", 0),
    ] {
        if text.matches(word).count() != count {
            errors.push(format!("App tools: {word}"));
        }
    }
    for word in [
        ".envs(",
        ".env_remove(",
        ".current_dir(",
        ".output(",
        ".status(",
        "process::Command",
        "CommandExt",
        "room-cli",
        "room_cli",
    ] {
        if text.contains(word) {
            errors.push(format!("App tools: {word}"));
        }
    }
    let source = compact(text);
    for exact in [
        "constPYTHON_PROGRAM:&str=\"/usr/bin/python3\";",
        "constOPENSSL_PROGRAM:&str=\"/usr/bin/openssl\";",
        "constSIGN_ARGS:[&str;3]=[\"dgst\",\"-sha256\",\"-sign\"];",
        r#"letkey=format!("/proc/{}/fd/{}",std::process::id(),key.as_raw_fd());"#,
        r#"#[cfg(target_os="macos")]fnkey_tool("#,
        r#"constSECURITY_SCRIPT:&str=include_str!("../../../../tools/install/platform/security.py");"#,
        "constCURL_PROGRAM:&str=\"/usr/bin/curl\";",
        "constCURL_ARGS:[&str;15]=[\"--disable\",\"--silent\",\"--show-error\",\"--fail-with-body\",\"--max-time\",\"15\",\"--proto\",\"=https\",\"--max-redirs\",\"0\",\"--config\",\"-\",\"--write-out\",\"\\\\n%{http_code}\",\"--no-progress-meter\",];",
        r#"https://api.github.com/app/installations/{installation}/access_tokens\"\nrequest=\"POST\"\n"#,
        // GI5 (#2547, J26): the second call's list, URL template and endpoints.
        "constCURL_STATUS_ARGS:[&str;14]=[\"--disable\",\"--silent\",\"--show-error\",\"--max-time\",\"15\",\"--proto\",\"=https\",\"--max-redirs\",\"0\",\"--config\",\"-\",\"--write-out\",\"\\\\n%{http_code}\",\"--no-progress-meter\",];",
        r#""url=\"https://api.github.com/{url}\"\n{post}header=\"Authorization:Bearer{jwt}\"\nheader=\"Accept:application/vnd.github+json\"\nheader=\"X-GitHub-Api-Version:2026-03-10\"\n""#,
        r#"format!("repos/{repository}/installation")"#,
        r#"format!("app/installations/{installation}/access_tokens")"#,
        r#""request=\"POST\"\nheader=\"Content-Type:application/json\"\ndata={data}\n""#,
    ] {
        if source.matches(exact).count() != 1 {
            errors.push(format!("App fixed declaration changed: {exact}"));
        }
    }
    if chain(text, "Command::new(OPENSSL_PROGRAM)")
        != ".args(SIGN_ARGS).arg(key).env_clear().stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())"
    {
        errors.push("Linux pinned signing spawn changed".to_owned());
    }
    if chain(text, "Command::new(PYTHON_PROGRAM)")
        != ".args([\"-I\",\"-c\",SECURITY_SCRIPT,mode]).arg(root).env_clear().stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())"
    {
        errors.push("App signing spawn changed".to_owned());
    }
    // Each curl spawn, in order: the token exchange, then GI5's status call.
    let curl: Vec<String> = text
        .split("Command::new(CURL_PROGRAM)")
        .skip(1)
        .map(|s| {
            s.split_once(".spawn()")
                .map(|(s, _)| compact(s))
                .unwrap_or_default()
        })
        .collect();
    if curl
        != [
            ".args(CURL_ARGS).env_clear().stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())",
            ".args(CURL_STATUS_ARGS).env_clear().stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())",
        ]
    {
        errors.push("App HTTPS spawn changed".to_owned());
    }
    errors
}

fn t7_signing_argv_uses_only_the_pinned_descriptor_path() {
    let app = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_APP)).unwrap();
    let path = r#".args(["-I", "-c", SECURITY_SCRIPT, mode])"#;
    assert_eq!(app.matches(path).count(), 1);
    let changed = app.replacen(
        path,
        r#".args(["-I", "-c", "synthetic-private-material", mode])"#,
        1,
    );
    assert!(
        !app_source_problems(&changed).is_empty(),
        "signing key material must never become an argument"
    );
}

fn t7_the_token_endpoint_rejects_suffixes() {
    let app = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_APP)).unwrap();
    let end = r#"access_tokens\"\nrequest"#;
    assert_eq!(app.matches(end).count(), 1);
    for suffix in ["/synthetic", "?synthetic=1", "#synthetic"] {
        // GI5's two templates take no suffix either.
        for (from, to) in [
            ("/installation\")", format!("/installation{suffix}\")")),
            ("/access_tokens\")", format!("/access_tokens{suffix}\")")),
            ("{url}\\\"", format!("{{url}}{suffix}\\\"")),
        ] {
            assert_eq!(app.matches(from).count(), 1, "{from}");
            assert!(
                !app_source_problems(&app.replacen(from, &to, 1)).is_empty(),
                "missed GI5 endpoint suffix {suffix} at {from}"
            );
        }
        let changed = app.replacen(end, &format!("access_tokens{suffix}\\\"\\nrequest"), 1);
        assert!(
            !app_source_problems(&changed).is_empty(),
            "missed endpoint suffix {suffix}"
        );
    }
}

fn t7_app_guards_catch_extra_programs_arguments_environments_and_endpoints() {
    let runner =
        fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_RUNNER)).unwrap();
    let app = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(GITHUB_APP)).unwrap();
    assert!(github_runner_problems(&runner).is_empty());
    assert!(
        app_source_problems(&app).is_empty(),
        "{:?}",
        app_source_problems(&app)
    );
    for (from, to) in [
        (".args(call.argv())", ".args(call.argv()).arg(\"--repo\")"),
        (
            ".env(\"GH_TOKEN\", credential)",
            ".env(\"GH_TOKEN\", credential).env(\"GH_DEBUG\", \"api\")",
        ),
        (".env_clear()", ".env_remove(\"GH_TOKEN\")"),
        (".args(call.argv())", ".args([\"api\", \"user\"])"),
    ] {
        assert_eq!(runner.matches(from).count(), 1);
        assert!(
            !github_runner_problems(&runner.replacen(from, to, 1)).is_empty(),
            "missed {from}"
        );
    }
    for (from, to) in [
        (
            "Command::new(CURL_PROGRAM)\n            .args(CURL_ARGS)",
            "Command::new(\"sh\")\n            .args(CURL_ARGS)",
        ),
        (
            "Command::new(CURL_PROGRAM)\n            .args(CURL_STATUS_ARGS)",
            "Command::new(\"sh\")\n            .args(CURL_STATUS_ARGS)",
        ),
        ("Command::new(PYTHON_PROGRAM)", "Command::new(\"python3\")"),
        (
            "const PYTHON_PROGRAM: &str = \"/usr/bin/python3\";",
            "const PYTHON_PROGRAM: &str = \"/usr/local/bin/python3\";",
        ),
        (".args(CURL_ARGS)", ".args(CURL_ARGS).arg(\"--location\")"),
        (
            ".args([\"-I\", \"-c\", SECURITY_SCRIPT, mode])",
            ".args([\"-I\", \"-c\", SECURITY_SCRIPT, mode]).env(\"OPENSSL_CONF\", \"synthetic\")",
        ),
        (
            "https://api.github.com/app/",
            "https://other.example.com/app/",
        ),
        (
            "\"--fail-with-body\",\n    \"--max-time\",\n    \"15\",\n    \"--proto\",\n    \"=https\"",
            "\"--fail-with-body\",\n    \"--max-time\",\n    \"15\",\n    \"--proto\",\n    \"=http,https\"",
        ),
        (".arg(root)", ".arg(root).arg(\"--extra\")"),
        // GI5's second curl call: its program, list, chain and endpoints.
        (
            ".args(CURL_STATUS_ARGS)",
            ".args(CURL_STATUS_ARGS).arg(\"--location\")",
        ),
        (
            ".args(CURL_STATUS_ARGS)\n            .env_clear()",
            ".args(CURL_STATUS_ARGS)\n            .env_remove(\"HOME\")",
        ),
        (
            "const CURL_STATUS_ARGS: [&str; 14] = [\n    \"--disable\",",
            "const CURL_STATUS_ARGS: [&str; 14] = [\n    \"--location\",",
        ),
        (
            "\"--show-error\",\n    \"--max-time\",\n    \"15\",\n    \"--proto\",\n    \"=https\"",
            "\"--show-error\",\n    \"--max-time\",\n    \"15\",\n    \"--proto\",\n    \"=http,https\"",
        ),
        (
            "https://api.github.com/{url}",
            "https://other.example.com/{url}",
        ),
        (
            "\"repos/{repository}/installation\"",
            "\"repos/{repository}/hooks\"",
        ),
        (
            "\"app/installations/{installation}/access_tokens\"",
            "\"app/installations/{installation}\"",
        ),
        (
            "data = {data}\\n",
            "data = {data}\\nheader = \\\"X-Extra: 1\\\"\\n",
        ),
    ] {
        assert_eq!(app.matches(from).count(), 1);
        assert!(
            !app_source_problems(&app.replacen(from, to, 1)).is_empty(),
            "missed {from}"
        );
    }
}

/// B-3's one exception, and nothing more: one process, of `/bin/df`, with
/// `-P -k`, the directory, a cleared environment and `LC_ALL=C`, in exactly
/// that call. No other program, argument or variable can be given.
fn the_free_space_measure_runs_only_bin_df(text: &str) {
    let once = |needle: &str| {
        assert_eq!(
            text.matches(needle).count(),
            1,
            "{FREE_SPACE_MEASURE} names {needle:?} once"
        );
    };
    once("Command::new(");
    once("Command::new(DF_PROGRAM)");
    once("pub const DF_PROGRAM: &str = \"/bin/df\";");
    once("pub const DF_ARGS: [&str; 2] = [\"-P\", \"-k\"];");
    once("use std::process::{Command, Stdio};");
    once(".args(");
    once(".arg(");
    once(".env(");
    let call = text
        .split("Command::new(DF_PROGRAM)")
        .nth(1)
        .and_then(|rest| rest.split(".output()").next())
        .expect("the call");
    let call: String = call.split_whitespace().collect();
    assert_eq!(
        call,
        ".args(DF_ARGS).arg(dir).env_clear().env(\"LC_ALL\",\"C\").stdin(Stdio::null())\
         .stdout(Stdio::piped()).stderr(Stdio::null())",
        "the measure's call is exactly /bin/df -P -k <dir>, LC_ALL=C, nothing else"
    );
    for word in [
        "process::Command",
        "process::Child",
        "CommandExt",
        ".spawn(",
        ".status(",
        ".envs(",
        ".current_dir(",
        ".env_remove(",
        "room-cli",
        "room_cli",
    ] {
        assert!(!text.contains(word), "{FREE_SPACE_MEASURE} names {word}");
    }
}

fn no_product_source_spells_a_forbidden_argument() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../crates");
    let allowlist = root
        .join("adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .expect("allowlist");
    let cli = root.join("cli").canonicalize().expect("cli");
    let terminal_actions = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(TERMINAL_ACTIONS)
        .canonicalize()
        .expect("the terminal action seam");
    let service_reader = root
        .join("service/src/document.rs")
        .canonicalize()
        .expect("service reader");
    for (path, text) in product_sources() {
        let path = path.canonicalize().expect("path");
        for word in FORBIDDEN {
            if *word == "update" {
                assert!(
                    service_update_fields_only(&path, &service_reader, &text),
                    "{path:?}: update is not the service JSON field"
                );
                continue;
            }
            // The two writes' subcommands, only where the allowlist builds
            // them, each exactly once, inside its variant's argv; and
            // OpenWiz's own `send` command, only in the CLI.
            let arm = |variant: &str| {
                text.split(variant)
                    .nth(1)
                    .and_then(|rest| rest.split("],").next())
                    .unwrap_or_default()
                    .to_owned()
            };
            if *word == "tell" && path == allowlist {
                assert_eq!(text.matches("\"tell\"").count(), 1, "{path:?}");
                assert!(
                    arm("Self::ThreadTell {").contains("\"tell\""),
                    "{path:?}: tell outside ThreadTell"
                );
                continue;
            }
            if *word == "spawn" && path == allowlist {
                assert_eq!(text.matches("\"spawn\"").count(), 1, "{path:?}");
                assert!(
                    arm("Self::ThreadSpawn(").contains("\"spawn\""),
                    "{path:?}: spawn outside ThreadSpawn"
                );
                continue;
            }
            // B4 (ClosedWiz#120): the third write's subcommand, the same way.
            if *word == "archive" && path == allowlist {
                assert_eq!(text.matches("\"archive\"").count(), 1, "{path:?}");
                assert!(
                    arm("Self::ThreadArchive(").contains("\"archive\""),
                    "{path:?}: archive outside ThreadArchive"
                );
                continue;
            }
            if *word == "send" && path.starts_with(&cli) {
                continue;
            }
            // #1098: the Send capability id, once, and nothing else.
            if *word == "send" && path == terminal_actions && send_capability_id_only(&text) {
                continue;
            }
            let literal = format!("\"{word}\"");
            assert!(!text.contains(&literal), "{path:?} contains {literal}");
        }
    }
}

// #269: the same exact service JSON-field exception as M12, with no
// command-like literal allowed, in this file or anywhere else.
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

fn service_update_field_exception_catches_command_like_literals() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../crates/service/src");
    let reader = root.join("document.rs").canonicalize().unwrap();
    let other = root.join("runtime.rs").canonicalize().unwrap();
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
    let updater = root.join("update.rs").canonicalize().unwrap();
    let key = "const UPDATE: &str = \"update\";";
    assert!(service_update_fields_only(&updater, &reader, key));
    assert!(!service_update_fields_only(&other, &reader, key));
    assert!(!service_update_fields_only(
        &updater,
        &reader,
        &format!("{key}\nlet argv = [\"update\"];")
    ));
}

fn t13_key_helper_keeps_one_fixed_descriptor_handover() {
    fn allowed(script: &str) -> bool {
        let code: String = script.split_whitespace().collect();
        code.matches("os.execve(").count() == 1
            && code.contains("os.execve('/usr/bin/openssl',['/usr/bin/openssl','dgst','-sha256','-sign','/dev/fd/'+str(key)],{})")
            && code.contains("os.set_inheritable(key,True)")
            && !code.contains("subprocess") && !code.contains("os.system")
    }
    let script = include_str!("../../tools/install/platform/security.py");
    assert!(allowed(script));
    for (from, to) in [
        ("'/dev/fd/'+str(key)", "sys.argv[2]"),
        ("os.set_inheritable(key, True)", "pass"),
        ("'/usr/bin/openssl'", "'/bin/sh'"),
        ("], {})", "], os.environ)"),
    ] {
        assert!(script.contains(from));
        assert!(!allowed(&script.replace(from, to)), "missed {from}");
    }
}

fn t2_linux_owner_query_keeps_the_existing_kernel_boundary() {
    let code = l3_compact(include_str!("../../crates/store/src/attachments.rs"));
    let linux = code
        .split_once("#[cfg(target_os=\"linux\")]")
        .map(|(_, tail)| tail.split("#[cfg").next().unwrap_or_default())
        .unwrap_or_default();
    let body = l3_function(linux, "pubfneffective_uid()->Result<u32,String>").unwrap_or_default();
    assert!(
        body.contains("fs::metadata(\"/proc/self\")")
            && body.contains("meta.uid()")
            && !body.contains("Command::new")
            && !body.contains(".output()"),
        "Linux ownership must use its existing kernel metadata, with no subprocess"
    );
}

fn t2_store_retains_p8s_single_program_exception() {
    let text = include_str!("../../crates/store/src/attachments.rs");
    the_free_space_measure_runs_only_bin_df(text);
}

/// #1098's launcher exception, exactly: one `Command::new(program)` whose
/// program is `sibling()`'s absolute `<current_exe dir>/openwiz-terminal`,
/// run with `.status()` and only `--port`/`--allowed-host` as arguments; no
/// shell, environment, working directory, `PATH`, spawn, exec or other
/// program. Read without comments and layout, literals kept.
fn terminal_launcher_problems(text: &str) -> Vec<String> {
    let text = l3_compact(text);
    let mut problems = Vec::new();
    for (needle, times) in [
        ("constEXECUTABLE:&str=\"openwiz-terminal\";", 1),
        ("letexe=std::env::current_exe()", 1),
        ("if!exe.is_absolute(){", 1),
        (
            "dir.join(format!(\"{EXECUTABLE}{}\",std::env::consts::EXE_SUFFIX))",
            1,
        ),
        ("Command::new(", 1),
        ("letmutcommand=std::process::Command::new(program);", 1),
        (
            "fnlaunch(program:&Path,ui:&UiArgs,stderr:&mutdynWrite)->i32{if!usable(program){",
            1,
        ),
        ("launch(", 2),
        (
            "matchsibling(){Ok(program)=>launch(&program,&ui,stderr),",
            1,
        ),
        (".arg(", 4),
        ("command.arg(\"--port\").arg(port.to_string());", 1),
        ("command.arg(\"--allowed-host\").arg(host);", 1),
        ("matchcommand.status(){", 1),
        (".status()", 1),
    ] {
        let n = text.matches(needle).count();
        if n != times {
            problems.push(format!("names {needle:?} {n} times, not {times}"));
        }
    }
    if text.contains("pubfnlaunch") {
        problems.push("launch is callable outside the launcher".to_owned());
    }
    for word in [
        ".args(",
        ".env(",
        ".envs(",
        ".env_clear(",
        ".env_remove(",
        ".current_dir(",
        ".output(",
        ".spawn(",
        ".exec(",
        "CommandExt",
        "process::{",
        "var_os(",
        "env::var(",
        "\"PATH\"",
        "\"sh\"",
        "\"/bin/",
        "\"-c\"",
        "\"room-cli\"",
        "\"gh\"",
    ] {
        if text.contains(word) {
            problems.push(format!("names {word:?}"));
        }
    }
    problems
}

/// #1098's capability exception, exactly: one `"send"`, as `ActionId::Send`'s
/// capability id.
fn send_capability_id_only(text: &str) -> bool {
    let text = l3_compact(text);
    text.matches("\"send\"").count() == 1 && text.contains("ActionId::Send=>\"send\",")
}

fn the_terminal_exceptions_refuse_any_widening() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let launcher = fs::read_to_string(root.join(TERMINAL_LAUNCHER)).unwrap();
    assert_eq!(terminal_launcher_problems(&launcher), Vec::<String>::new());
    let widened = [
        // A second process, a shell, or a name PATH would resolve.
        launcher.replace(
            "match command.status() {",
            "let _ = std::process::Command::new(\"sh\").status();\n    match command.status() {",
        ),
        launcher.replace(
            "std::process::Command::new(program)",
            "std::process::Command::new(\"openwiz-terminal\")",
        ),
        launcher.replace("\"openwiz-terminal\";", "\"openwiz-other\";"),
        launcher.replace("if !exe.is_absolute() {", "if false {"),
        launcher.replace("Ok(dir.join(", "Ok(std::env::current_dir().unwrap().join("),
        // Other arguments, environment or working directory.
        launcher.replace(
            "match command.status() {",
            "command.arg(\"--extra\");\n    match command.status() {",
        ),
        launcher.replace(
            "match command.status() {",
            "command.args([\"-c\"]);\n    match command.status() {",
        ),
        launcher.replace(
            "match command.status() {",
            "command.env(\"PATH\", \"/tmp\");\n    match command.status() {",
        ),
        launcher.replace(
            "match command.status() {",
            "command.current_dir(\"/\");\n    match command.status() {",
        ),
        launcher.replace("match command.status() {", "match command.spawn() {"),
        // Callable from elsewhere, with another path.
        launcher.replace("fn launch(program", "pub fn launch(program"),
        launcher.replace(
            "Ok(program) => launch(&program, &ui, stderr),",
            "Ok(_) => launch(Path::new(\"openwiz-terminal\"), &ui, stderr),",
        ),
    ];
    for (i, text) in widened.iter().enumerate() {
        assert_ne!(text, &launcher, "mutation {i} did not apply");
        assert!(
            !terminal_launcher_problems(text).is_empty(),
            "mutation {i} widened the launcher exception unnoticed"
        );
    }

    let actions = fs::read_to_string(root.join(TERMINAL_ACTIONS)).unwrap();
    assert!(send_capability_id_only(&actions));
    for text in [
        actions.replace(
            "ActionId::Send => \"send\",",
            "ActionId::Send => \"send\",\n            // \"send\"",
        ),
        format!("{actions}\nconst X: &str = \"send\";\n"),
        actions.replace(
            "ActionId::Send => \"send\",",
            "ActionId::Send => \"message\",",
        ),
    ] {
        // A comment never counts; a second literal or another place does.
        let widened = l3_compact(&text).matches("\"send\"").count() > 1
            || !l3_compact(&text).contains("ActionId::Send=>\"send\",");
        assert_eq!(!send_capability_id_only(&text), widened, "{text}");
    }
    assert!(!send_capability_id_only(&format!(
        "{actions}\nconst X: &str = \"send\";\n"
    )));
    // The exception is for "send" in that one file only: every other
    // forbidden word, and every other terminal source, stays refused.
    for (path, text) in product_sources() {
        if path.starts_with(root.join("../crates/terminal")) {
            for word in FORBIDDEN.iter().filter(|w| **w != "send") {
                assert!(!text.contains(&format!("\"{word}\"")), "{path:?}: {word}");
            }
            if !path.ends_with("actions/mod.rs") {
                assert!(!text.contains("\"send\""), "{path:?}");
            }
            assert!(!text.contains("Command::new") && !text.contains("process::Command"));
        }
    }
}

// #1680: the public invocation must carry the allowance for the aggregate
// staged bytes. These expectations are literal B2 examples, not its formula.
fn ta3_staged_totals_reach_tell_and_spawn_allowances() {
    use std::time::Duration;
    for (sizes, seconds) in [
        (vec![], 0),
        (vec![1], 1),
        (vec![1_048_576], 1),
        (vec![1_048_577], 2),
        (vec![1_048_575, 1], 1),
        (vec![1_048_576, 1], 2),
    ] {
        let attachments: Vec<_> = sizes
            .iter()
            .zip(staged())
            .map(|(&size, mut a)| {
                a.attachment.size_bytes = size;
                a
            })
            .collect();
        let tell = Invocation::ThreadTell {
            id: ThreadId::parse("thr_syn_0001").unwrap(),
            mode: Mode::Queue,
            text: "Synthetic".to_owned(),
            attachments: attachments.clone(),
        };
        let spawn = Invocation::ThreadSpawn(
            SpawnArgs::new(
                "prj_syn_0001",
                "codex",
                "syn-codex-model-01",
                "high",
                RID,
                "Synthetic",
            )
            .unwrap()
            .with_attachments(attachments),
        );
        for invocation in [tell, spawn] {
            assert_eq!(
                invocation.allowance(),
                Duration::from_secs(seconds),
                "{sizes:?}"
            );
        }
    }
    for read in [
        Invocation::Version,
        Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        },
        Invocation::ProjectList { hidden: false },
        Invocation::MachineList,
    ] {
        assert_eq!(read.allowance(), Duration::ZERO);
    }
}

// #1106 EN1: negative controls for the exact installed interpreter boundary.
fn engine_launcher_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("Command", 2),
            ("Command::new(", 1),
            ("engine_process", 2),
            (".arg(", 2),
            (".args(", 1),
            (".env_clear(", 1),
            (".env(", 1),
            (".envs(", 0),
            (".env_remove(", 0),
            (".current_dir(", 0),
            (".output(", 1),
            (".spawn(", 0),
            (".status(", 0),
            (".exec(", 0),
            ("std::env::current_exe(", 1),
            ("std::env::var_os(", 1),
            ("letresult=engine_process(args);", 1),
        ],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn engine_process(args: &[OsString]) -> Option<std::process::Output>",
        r#"fn engine_process(args: &[OsString]) -> Option<std::process::Output> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let tool = exe.parent()?.join("runtime/engine/engine.py");
    // Only this installed sibling, never PATH or a source checkout fallback.
    let meta = std::fs::symlink_metadata(&tool).ok()?;
    if !meta.is_file() || meta.file_type().is_symlink() {
        return None;
    }
    if tool
        .ancestors()
        .skip(1)
        .any(|p| !std::fs::symlink_metadata(p).is_ok_and(|m| !m.file_type().is_symlink()))
    {
        return None;
    }
    let mut command = Command::new("/usr/bin/python3");
    command.arg("-I").arg(tool).args(args).env_clear();
    for name in ["HOME", "XDG_STATE_HOME", "OPENWIZ_STATE_DIR"] {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command.stdin(std::process::Stdio::null()).output().ok()
}
"#,
    );
    problems
}

fn engine_interpreter_exception_rejects_planted_widening() {
    let code = l3_compact(include_str!("../../crates/cli/src/engine.rs"));
    assert!(engine_launcher_problems(&code).is_empty());
    for (from, to) in [
        (
            r#"Command::new("/usr/bin/python3")"#,
            r#"Command::new("python3")"#,
        ),
        (
            r#"Command::new("/usr/bin/python3")"#,
            r#"Command::new("/bin/sh")"#,
        ),
        (r#".arg("-I")"#, r#".arg("-c")"#),
        (".env_clear()", ""),
        (".env_clear()", r#".env_clear().env("PATH", "/synthetic")"#),
        (
            ".env_clear()",
            r#".env_clear().env("PYTHONPATH", "/synthetic")"#,
        ),
        (".env_clear()", r#".env_clear().current_dir("/synthetic")"#),
        (".args(args)", r#".arg("--extra").args(args)"#),
        ("std::env::current_exe()", "std::env::current_dir()"),
        (
            ".canonicalize().ok()?",
            ".canonicalize().unwrap_or_default()",
        ),
        (
            r#".join("runtime/engine/engine.py")"#,
            r#".join("tools/install/engine/engine.py")"#,
        ),
        (
            r#".join("runtime/engine/engine.py")"#,
            r#".join(std::env::var_os("ENGINE_PATH").unwrap())"#,
        ),
        (
            "if !meta.is_file() || meta.file_type().is_symlink()",
            "if false",
        ),
        (".ancestors()", ".ancestors().take(0)"),
        (
            r#"["HOME", "XDG_STATE_HOME", "OPENWIZ_STATE_DIR"]"#,
            r#"["HOME", "XDG_STATE_HOME", "PATH"]"#,
        ),
        (".stdin(std::process::Stdio::null())", ""),
        (".output().ok()", ".status().ok()"),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !engine_launcher_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    for extra in [
        r#"fn extra() { Command::new("/usr/bin/python3").output(); }"#,
        r#"use std::process::Command as C; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"type C = Command; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"fn extra(c: &mut Command) { let _ = Command::spawn(c); }"#,
        r#"fn extra() { let f = engine_process; let _ = f(&[]); }"#,
    ] {
        assert!(
            !engine_launcher_problems(&format!("{code}{}", l3_compact(extra))).is_empty(),
            "missed {extra}"
        );
    }
}
