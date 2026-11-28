//! Approval provenance: [private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036).

use std::fs;
use std::path::{Path, PathBuf};

use openwiz_adapter_cloudroom::allowlist::{
    Invocation, LoopAgentArgs, LoopCreateArgs, LoopReschedule, LoopTrigger, LoopUpdateArgs,
    SpawnArgs, THREAD_ID_MAX_LEN, ThreadId,
};
use openwiz_core::attachment::{
    AttachmentId, Kind, PromptAttachment, SafeName, Sha256, StagedAttachment, StagedPath,
};
use openwiz_core::messaging::Mode;

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

const RID: &str = "ow1-0123456789abcdef0123456789abcdef01234567";

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
    &["cloud", "thread-workspace", "thr_syn_0001", "--json"],
    &["thread", "archive", "thr_syn_0001", "--json"],
    &["loop", "list", "--json"],
    &["loop", "resume", "loop_syn_1", "--json"],
    &["loop", "pause", "loop_syn_1", "--json"],
    &[
        "loop",
        "create",
        "--name",
        "Synthetic [wizloop:syn]",
        "--prompt-file",
        "@prompt",
        "--cron",
        "0 9 * * *",
        "--timezone",
        "UTC",
        "--new-thread",
        "--script-file",
        "@script",
        "--provider",
        "syn-provider",
        "--model",
        "syn-model",
        "--reasoning",
        "medium",
        "--priority",
        "3",
        "--secrets",
        "none",
    ],
    &[
        "loop",
        "update",
        "loop_syn_1",
        "--name",
        "Synthetic [wizloop:syn]",
        "--priority",
        "2",
        "--prompt",
        "Synthetic",
        "--at",
        "2030-01-02T03:04:05Z",
        "--script-file",
        "@script",
        "--provider",
        "syn-provider",
        "--model",
        "syn-model",
        "--reasoning",
        "medium",
        "--secrets",
        "all",
    ],
];

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

fn syn_agent() -> LoopAgentArgs {
    LoopAgentArgs {
        provider: "syn-provider".into(),
        model: "syn-model".into(),
        reasoning: "medium".into(),
    }
}

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
        Invocation::LoopCreate(LoopCreateArgs {
            name: "Synthetic [wizloop:syn]".into(),
            prompt_file: "@prompt".into(),
            trigger: LoopTrigger::Cron {
                cron: "0 9 * * *".into(),
                timezone: "UTC".into(),
            },
            new_thread: true,
            script_file: Some("@script".into()),
            agent: Some(syn_agent()),
            priority: "3".into(),
            secrets: "none".into(),
        }),
        Invocation::LoopUpdate(LoopUpdateArgs {
            loop_id: ThreadId::parse("loop_syn_1").expect("valid id"),
            name: Some("Synthetic [wizloop:syn]".into()),
            priority: Some("2".into()),
            prompt: Some("Synthetic".into()),
            trigger: Some(LoopReschedule::At("2030-01-02T03:04:05Z".into())),
            script_file: Some("@script".into()),
            agent: Some(syn_agent()),
            secrets: Some("all".into()),
        }),
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
            | Invocation::LoopPause(_)
            | Invocation::LoopCreate(_)
            | Invocation::LoopUpdate(_) => {}
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
            Invocation::ThreadArchive(_) => {
                assert_eq!(argv[1], "archive");
                (&argv[..], &["archive"])
            }
            Invocation::LoopCreate(_) => {
                assert_eq!(argv[1], "create");
                (&argv[..], &["create"])
            }
            Invocation::LoopUpdate(_) => {
                assert_eq!(argv[1], "update");
                let prompt = argv.iter().position(|a| a == "--prompt");
                let checked: Vec<String> = argv
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| prompt.is_none_or(|p| *i != p + 1))
                    .map(|(_, a)| a.clone())
                    .collect();
                for word in &checked {
                    assert!(
                        !FORBIDDEN.contains(&word.as_str()) || word == "update",
                        "{invocation:?} passes {word}"
                    );
                }
                continue;
            }
            _ => (&argv[..], &[]),
        };
        for word in checked {
            assert!(
                !FORBIDDEN.contains(&word.as_str()) || allowed.contains(&word.as_str()),
                "{invocation:?} passes {word}"
            );
        }
        assert!(
            argv == ["--version"]
                || matches!(
                    invocation,
                    Invocation::LoopCreate(_) | Invocation::LoopUpdate(_)
                )
                || argv.iter().any(|a| a == "--json"),
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

const GITHUB_RUNNER: &str = "../crates/adapters/github/src/process.rs";
const GITHUB_APP: &str = "../crates/adapters/github/src/app.rs";
const GITHUB_APP_TRANSPORT_TESTS: &str = "../crates/adapters/github/src/app_transport_tests.rs";

const LOOP_REPOSITORY: &str = "../crates/cli/src/state/loops/repository.rs";

/// J99 (#635), approved by Jake 2026-11-15: installed `openwiz init` runs only
/// the fixed sibling `runtime/setup/init.py` through absolute
/// `/usr/bin/python3 -I`, with a cleared environment passing only HOME,
/// XDG_STATE_HOME, OPENWIZ_STATE_DIR, PATH and GH_CONFIG_DIR (the last two
/// only locate the existing gh login), and stdin null. No GH_TOKEN or PYTHONPATH.
/// Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6904873199
const INIT_LAUNCHER: &str = "../crates/cli/src/init.rs";

/// J306 (#2192), Jake's choice, 2026-11-22: on macOS the models writer runs
/// only absolute `/bin/ls -lde <file>` to see a file's extended ACL.
/// Private record: https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7077406386
const MODELS_ACL_LISTER: &str = "../crates/cli/src/models.rs";

const JEV_ASKER: &str = "../crates/cli/src/typesafe.rs";

#[test]
fn allowlist_source_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 14] = [
        (
            "init_interpreter_exception_rejects_planted_widening",
            init_interpreter_exception_rejects_planted_widening,
        ),
        (
            "j306_models_lister_exception_rejects_planted_widening",
            j306_models_lister_exception_rejects_planted_widening,
        ),
        (
            "jv1_jev_asker_exception_rejects_planted_widening",
            jv1_jev_asker_exception_rejects_planted_widening,
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
            "t13_key_helper_keeps_one_fixed_descriptor_handover",
            t13_key_helper_keeps_one_fixed_descriptor_handover,
        ),
        (
            "t2_linux_owner_query_keeps_the_existing_kernel_boundary",
            t2_linux_owner_query_keeps_the_existing_kernel_boundary,
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
    let github_runner = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(GITHUB_RUNNER)
        .canonicalize()
        .expect("the GitHub runner");
    let mut ran = false;
    let app = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(GITHUB_APP)
        .canonicalize()
        .unwrap();
    let mut signed = false;
    let app_transport_tests = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(GITHUB_APP_TRANSPORT_TESTS)
        .canonicalize()
        .unwrap();
    let mut transport_tests = false;
    let init_launcher = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(INIT_LAUNCHER)
        .canonicalize()
        .expect("the init launcher");
    let mut init_launched = false;
    let models_lister = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(MODELS_ACL_LISTER)
        .canonicalize()
        .expect("the models writer");
    let mut models_listed = false;
    let jev_asker = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(JEV_ASKER)
        .canonicalize()
        .expect("the Jev asker");
    let mut jev_asked = false;
    let canonical_loop = |file| {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(file)
            .canonicalize()
            .expect("canonical L3 source")
    };
    let loop_repository = canonical_loop(LOOP_REPOSITORY);
    let mut checked_loops = [false; 1];
    for (path, text) in product_sources() {
        let starts_process = text.contains("process::Command")
            || text.contains("Command::new")
            || text.contains("process::{");
        let canonical = path.canonicalize().expect("path");
        let in_adapter = canonical.starts_with(&adapter);
        if canonical == loop_repository {
            assert_eq!(l3_repository_problems(&text), Vec::<String>::new());
            checked_loops[0] = true;
            continue;
        }
        assert!(
            !l3_compact(&text).contains("check::run("),
            "{path:?}: ungated check caller"
        );
        if canonical == github_runner {
            assert_eq!(
                github_runner_problems(&text),
                Vec::<String>::new(),
                "{GITHUB_RUNNER}"
            );
            ran = true;
            continue;
        }
        if canonical == init_launcher {
            assert_eq!(
                init_launcher_problems(&text),
                Vec::<String>::new(),
                "{INIT_LAUNCHER}"
            );
            init_launched = true;
            continue;
        }
        if canonical == models_lister {
            assert_eq!(
                models_lister_problems(&text),
                Vec::<String>::new(),
                "{MODELS_ACL_LISTER}"
            );
            models_listed = true;
            continue;
        }
        if canonical == jev_asker {
            assert_eq!(
                jev_asker_problems(&text),
                Vec::<String>::new(),
                "{JEV_ASKER}"
            );
            jev_asked = true;
            continue;
        }
        assert!(
            !text.contains("run_models_listing_acls"),
            "{path:?} injects a models ACL lister"
        );
        if canonical == app_transport_tests {
            let app_text = fs::read_to_string(&app).unwrap();
            assert_eq!(
                app_text
                    .matches(
                        "#[cfg(test)]\n#[path = \"app_transport_tests.rs\"]\nmod transport_tests;"
                    )
                    .count(),
                1,
                "{GITHUB_APP_TRANSPORT_TESTS} is only app.rs's test module"
            );
            assert_eq!(app_text.matches("app_transport_tests.rs").count(), 1);
            transport_tests = true;
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
    assert!(ran, "{GITHUB_RUNNER} was not checked");
    assert!(signed, "{GITHUB_APP} was not checked");
    assert!(
        transport_tests,
        "{GITHUB_APP_TRANSPORT_TESTS} was not checked"
    );
    assert!(init_launched, "{INIT_LAUNCHER} was not checked");
    assert!(models_listed, "{MODELS_ACL_LISTER} was not checked");
    assert!(jev_asked, "{JEV_ASKER} was not checked");
    assert_eq!(checked_loops, [true; 1], "the canonical L3 gate checked");
}

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
        } else if quote == b'\'' && (bytes[i].is_ascii_whitespace() || i > start + 4) {
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
    let code = l3_compact(include_str!(
        "../../crates/cli/src/state/loops/repository.rs"
    ));
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

fn l3_exceptions_reject_aliased_process_starts() {
    let mut missed = Vec::new();
    for (name, text, inspect) in [(
        "repository",
        include_str!("../../crates/cli/src/state/loops/repository.rs"),
        l3_repository_problems as fn(&str) -> Vec<String>,
    )] {
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

fn no_product_source_spells_a_forbidden_argument() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../crates");
    let allowlist = root
        .join("adapters/cloudroom/src/allowlist.rs")
        .canonicalize()
        .expect("allowlist");
    let cli = root.join("cli").canonicalize().expect("cli");
    for (path, text) in product_sources() {
        let path = path.canonicalize().expect("path");
        for word in FORBIDDEN {
            if matches!(*word, "create" | "update") && path == allowlist {
                let variant = if *word == "create" {
                    "LoopCreate"
                } else {
                    "LoopUpdate"
                };
                let header = format!("            Self::{variant}(a) => {{\n");
                let arm: String = text
                    .split(&header)
                    .nth(1)
                    .and_then(|rest| rest.split("\n            }\n").next())
                    .unwrap_or_default()
                    .split_whitespace()
                    .collect();
                assert_eq!(text.matches(&header).count(), 1, "{path:?}: {variant}");
                assert_eq!(
                    text.matches(&format!("\"{word}\"")).count(),
                    1,
                    "{path:?}: {word}"
                );
                assert!(
                    arm.starts_with(&format!("letmutw=vec![\"loop\",\"{word}\",")),
                    "{path:?}: {word} outside {variant}"
                );
                continue;
            }
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
            let literal = format!("\"{word}\"");
            assert!(!text.contains(&literal), "{path:?} contains {literal}");
        }
    }
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
    let code = l3_compact(include_str!("../../crates/cli/src/state/owner.rs"));
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

fn init_launcher_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("Command", 2),
            ("Command::new(", 1),
            ("init_process", 2),
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
            ("letSome(result)=init_process(args)else", 1),
        ],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn init_process(args: &[OsString]) -> Option<std::process::Output>",
        r#"fn init_process(args: &[OsString]) -> Option<std::process::Output> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let tool = exe.parent()?.join("runtime/setup/init.py");
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
    for name in [
        "HOME",
        "XDG_STATE_HOME",
        "OPENWIZ_STATE_DIR",
        "PATH",
        "GH_CONFIG_DIR",
    ] {
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

fn models_lister_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("Command", 1),
            ("Command::new(", 1),
            ("process::{", 0),
            ("macos_ls", 2),
            (".arg(", 2),
            (".args(", 0),
            (".env_clear(", 1),
            (".env(", 0),
            (".envs(", 0),
            (".current_dir(", 0),
            (".output(", 1),
            (".spawn(", 0),
            (".status(", 0),
            (".exec(", 0),
            ("run_models_listing_acls(", 2),
            (
                r#"letlister:Option<AclLister>=ifstd::env::consts::OS=="macos"{Some(&macos_ls)}else{None};"#,
                1,
            ),
        ],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn macos_ls(path: &Path) -> std::io::Result<std::process::Output>",
        r#"fn macos_ls(path: &Path) -> std::io::Result<std::process::Output> {
    std::process::Command::new("/bin/ls")
        .arg("-lde")
        .arg(path)
        .env_clear()
        .stdin(std::process::Stdio::null())
        .output()
}
"#,
    );
    problems
}

fn j306_models_lister_exception_rejects_planted_widening() {
    let code = l3_compact(include_str!("../../crates/cli/src/models.rs"));
    assert_eq!(models_lister_problems(&code), Vec::<String>::new());
    for (from, to) in [
        (r#"Command::new("/bin/ls")"#, r#"Command::new("ls")"#),
        (r#"Command::new("/bin/ls")"#, r#"Command::new("/bin/sh")"#),
        (r#".arg("-lde")"#, r#".arg("-c")"#),
        (r#".arg("-lde")"#, r#".arg("-lde").arg("-@")"#),
        (".arg(path)", ".args([path])"),
        (".env_clear()", ""),
        (".env_clear()", r#".env_clear().env("LS_COLORS", "syn")"#),
        (".env_clear()", r#".env_clear().current_dir("/synthetic")"#),
        (".stdin(std::process::Stdio::null())", ""),
        (".output()", ".spawn()"),
        (r#"OS=="macos""#, r#"OS!="windows""#),
        ("Some(&macos_ls)", "Some(&|p: &Path| macos_ls(p))"),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !models_lister_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    for extra in [
        r#"fn extra() { std::process::Command::new("/bin/sh").output(); }"#,
        r#"use std::process::Command as C; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"type C = std::process::Command; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"use std::process::{Command as C}; fn extra() { C::new("/bin/sh"); }"#,
        r#"fn extra() { let f = macos_ls; let _ = f(Path::new("/")); }"#,
        r#"fn extra(a: &[String]) { run_models_listing_acls(a, Path::new("."), todo!(), todo!(), None, todo!(), todo!()); }"#,
    ] {
        assert!(
            !models_lister_problems(&format!("{code}{}", l3_compact(extra))).is_empty(),
            "missed {extra}"
        );
    }
}

fn init_interpreter_exception_rejects_planted_widening() {
    let code = l3_compact(include_str!("../../crates/cli/src/init.rs"));
    assert!(init_launcher_problems(&code).is_empty());
    let list = r#"["HOME","XDG_STATE_HOME","OPENWIZ_STATE_DIR","PATH","GH_CONFIG_DIR",]"#;
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
            r#".join("runtime/setup/init.py")"#,
            r#".join("tools/install/setup/init.py")"#,
        ),
        (
            r#".join("runtime/setup/init.py")"#,
            r#".join(std::env::var_os("INIT_PATH").unwrap())"#,
        ),
        (
            "if !meta.is_file() || meta.file_type().is_symlink()",
            "if false",
        ),
        (".ancestors()", ".ancestors().take(0)"),
        (
            list,
            r#"["HOME","XDG_STATE_HOME","OPENWIZ_STATE_DIR","PATH","GH_CONFIG_DIR","GH_TOKEN",]"#,
        ),
        (
            list,
            r#"["HOME","XDG_STATE_HOME","OPENWIZ_STATE_DIR","PATH","GH_CONFIG_DIR","PYTHONPATH",]"#,
        ),
        (
            list,
            r#"["HOME","XDG_STATE_HOME","OPENWIZ_STATE_DIR","PATH","GH_CONFIG_DIR","GH_HOST",]"#,
        ),
        (".stdin(std::process::Stdio::null())", ""),
        (".output().ok()", ".status().ok()"),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !init_launcher_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    for extra in [
        r#"fn extra() { Command::new("/usr/bin/python3").output(); }"#,
        r#"use std::process::Command as C; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"type C = Command; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"fn extra(c: &mut Command) { let _ = Command::spawn(c); }"#,
        r#"fn extra() { let f = init_process; let _ = f(&[]); }"#,
    ] {
        assert!(
            !init_launcher_problems(&format!("{code}{}", l3_compact(extra))).is_empty(),
            "missed {extra}"
        );
    }
}

fn jev_asker_problems(text: &str) -> Vec<String> {
    let code = l3_compact(text);
    let mut problems = Vec::new();
    l3_counts(
        &mut problems,
        &code,
        &[
            ("Command", 1),
            ("Command::new(", 1),
            ("process::{", 0),
            ("jev_process", 2),
            ("run_ask(", 6),
            (".arg(", 2),
            (".args(", 0),
            (".env_clear(", 1),
            (".env(", 2),
            (".envs(", 0),
            (".env_remove(", 0),
            (".current_dir(", 0),
            (".output(", 0),
            (".spawn(", 1),
            (".status(", 0),
            (".exec(", 0),
            ("rustix", 0),
            ("libc", 0),
            ("std::env::current_exe(", 1),
            ("std::env::var_os(", 3),
            (
                "letanswer=jev_process(body.to_string().as_bytes(),until)?;",
                1,
            ),
            ("run_ask(&tool,&key,request,until)", 1),
            (
                "letuntil=answer_until(std::time::Instant::now(),self.deadline);",
                1,
            ),
        ],
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn answer_until(now: std::time::Instant, deadline: std::time::Instant) -> std::time::Instant",
        r#"fn answer_until(now: std::time::Instant, deadline: std::time::Instant) -> std::time::Instant {
    let left = deadline.saturating_duration_since(now) / 2;
    now + left.min(std::time::Duration::from_secs(ANSWER_SECONDS))
}
"#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn jev_process(request: &[u8], until: std::time::Instant) -> Option<Vec<u8>>",
        r#"fn jev_process(request: &[u8], until: std::time::Instant) -> Option<Vec<u8>> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let target = exe.ancestors().nth(2)?;
    if target.file_name()? != "target" {
        return None;
    }
    let tool = target.parent()?.join("tools/typesafe/ask.py");
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
    let key = std::env::var_os("TYPESAFE_API_KEY")?;
    run_ask(&tool, &key, request, until)
}
"#,
    );
    l3_exact_function(
        &mut problems,
        &code,
        "fn run_ask(tool: &std::path::Path, key: &std::ffi::OsStr, request: &[u8], until: std::time::Instant,) -> Option<Vec<u8>>",
        r#"fn run_ask(
    tool: &std::path::Path,
    key: &std::ffi::OsStr,
    request: &[u8],
    until: std::time::Instant,
) -> Option<Vec<u8>> {
    let mut child = std::process::Command::new("/usr/bin/python3")
        .arg("-I")
        .arg(tool)
        .env_clear()
        .env("OPENWIZ_JEV", "1")
        .env("TYPESAFE_API_KEY", key)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .ok()?;
    let stdout = child.stdout.take();
    let reader = std::thread::spawn(move || {
        let mut answer = Vec::new();
        if let Some(out) = stdout {
            let limit = MAX_ANSWER_BYTES as u64 + 1;
            let _ = std::io::Read::read_to_end(&mut std::io::Read::take(out, limit), &mut answer);
        }
        answer
    });
    let sent = child
        .stdin
        .take()
        .map(|mut input| std::io::Write::write_all(&mut input, request));
    let finished = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if matches!(sent, Some(Ok(()))) && std::time::Instant::now() < until => {
                std::thread::sleep(std::time::Duration::from_millis(20));
            }
            _ => break None,
        }
    };
    if finished.is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let answer = reader.join().ok()?;
    finished
        .filter(|status| status.success() && answer.len() <= MAX_ANSWER_BYTES)
        .map(|_| answer)
}
"#,
    );
    problems
}

fn jv1_jev_asker_exception_rejects_planted_widening() {
    let code = l3_compact(include_str!("../../crates/cli/src/typesafe.rs"));
    assert_eq!(jev_asker_problems(&code), Vec::<String>::new());
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
        (".arg(tool)", r#".arg(tool).arg("--extra")"#),
        (".arg(tool)", r#".arg(tool).args(["--extra"])"#),
        (".env_clear()", ""),
        (
            ".env_clear()",
            r#".env_clear().env("PYTHONPATH", "/synthetic")"#,
        ),
        (".env_clear()", r#".env_clear().current_dir("/synthetic")"#),
        ("std::env::current_exe()", "std::env::current_dir()"),
        (".nth(2)", ".nth(3)"),
        (r#"if target.file_name()? != "target""#, "if false"),
        (
            r#".join("tools/typesafe/ask.py")"#,
            r#".join(std::env::var_os("JEV_SCRIPT")?)"#,
        ),
        (
            "if !meta.is_file() || meta.file_type().is_symlink()",
            "if false",
        ),
        (".ancestors().skip(1)", ".ancestors().take(0)"),
        (
            ".stderr(std::process::Stdio::null())",
            ".stderr(std::process::Stdio::inherit())",
        ),
        (".spawn()", ".output()"),
        ("std::io::Read::take(out, limit)", "out"),
        (" && std::time::Instant::now() < until", ""),
        (
            "run_ask(&tool, &key, request, until)",
            r#"run_ask(std::path::Path::new("/tmp/ask.py"), &key, request, until)"#,
        ),
        (
            "now + left.min(std::time::Duration::from_secs(ANSWER_SECONDS))",
            "now + std::time::Duration::from_secs(3600)",
        ),
    ] {
        let planted = l3_plant(&code, from, to);
        assert!(
            !jev_asker_problems(&planted).is_empty(),
            "missed {from} -> {to}"
        );
    }
    for extra in [
        r#"fn extra() { std::process::Command::new("/bin/sh").spawn(); }"#,
        r#"use std::process::Command as C; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"type C = std::process::Command; fn extra() { C::new("/bin/sh").spawn(); }"#,
        r#"use std::process::{Command as C}; fn extra() { C::new("/bin/sh"); }"#,
        r#"fn extra() { let f = jev_process; let _ = f(b"", std::time::Instant::now()); }"#,
        r#"fn extra() { let _ = run_ask(std::path::Path::new("/bin/sh"), std::ffi::OsStr::new(""), b"", std::time::Instant::now()); }"#,
        r#"fn extra() { let _ = rustix::process::getpid(); }"#,
    ] {
        assert!(
            !jev_asker_problems(&format!("{code}{}", l3_compact(extra))).is_empty(),
            "missed {extra}"
        );
    }
}
