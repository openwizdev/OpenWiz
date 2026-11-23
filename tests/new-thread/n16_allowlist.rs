use openwiz_adapter_cloudroom::allowlist::{Invocation, SpawnArgs};
use openwiz_core::messaging::MAX_TEXT_BYTES;

const RID: &str = "ow1-0123456789abcdef0123456789abcdef01234567";

fn args(
    project: &str,
    provider: &str,
    model: &str,
    effort: &str,
    rid: &str,
    prompt: &str,
) -> Result<SpawnArgs, String> {
    SpawnArgs::new(project, provider, model, effort, rid, prompt).map_err(|e| e.0)
}

#[test]
fn n16_allowlist_affected_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 2] = [
        (
            "a_spawn_can_only_be_built_with_safe_arguments",
            a_spawn_can_only_be_built_with_safe_arguments,
        ),
        (
            "the_two_additions_in_exactly_their_shapes",
            the_two_additions_in_exactly_their_shapes,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n16_allowlist::{name}");
        proof();
    }
}

fn the_two_additions_in_exactly_their_shapes() {
    assert_eq!(
        Invocation::CloudStatus.argv(),
        ["cloud", "status", "--json"]
    );
    let spawn = args(
        "prj_syn_0001",
        "codex",
        "syn-codex-model-01",
        "high",
        RID,
        "-Synthetic",
    )
    .unwrap();
    assert_eq!(
        Invocation::ThreadSpawn(spawn).argv(),
        [
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
            "-Synthetic",
        ]
    );
}

fn a_spawn_can_only_be_built_with_safe_arguments() {
    let ok = (
        "prj_syn_0001",
        "codex",
        "syn-codex-model-01",
        "high",
        RID,
        "Synthetic",
    );
    assert!(args(ok.0, ok.1, ok.2, ok.3, ok.4, ok.5).is_ok());
    assert!(args(ok.0, "claude-code", ok.2, "max", ok.4, ok.5).is_ok());
    let cap = "a".repeat(MAX_TEXT_BYTES + 1);
    for (what, bad) in [
        ("project", args("-x", ok.1, ok.2, ok.3, ok.4, ok.5)),
        ("project", args("prj syn", ok.1, ok.2, ok.3, ok.4, ok.5)),
        ("project", args("", ok.1, ok.2, ok.3, ok.4, ok.5)),
        ("provider", args(ok.0, "pi", ok.2, ok.3, ok.4, ok.5)),
        ("provider", args(ok.0, "acp-cursor", ok.2, ok.3, ok.4, ok.5)),
        ("provider", args(ok.0, "--provider", ok.2, ok.3, ok.4, ok.5)),
        ("model", args(ok.0, ok.1, "-m", ok.3, ok.4, ok.5)),
        ("model", args(ok.0, ok.1, "syn model", ok.3, ok.4, ok.5)),
        ("model", args(ok.0, ok.1, "", ok.3, ok.4, ok.5)),
        (
            "model",
            args(ok.0, ok.1, &"m".repeat(129), ok.3, ok.4, ok.5),
        ),
        ("effort", args(ok.0, ok.1, ok.2, "ultra", ok.4, ok.5)),
        ("effort", args(ok.0, ok.1, ok.2, "none", ok.4, ok.5)),
        ("effort", args(ok.0, ok.1, ok.2, "", ok.4, ok.5)),
        ("request", args(ok.0, ok.1, ok.2, ok.3, "syn-request", ok.5)),
        ("request", args(ok.0, ok.1, ok.2, ok.3, "ow1-0123", ok.5)),
        (
            "request",
            args(ok.0, ok.1, ok.2, ok.3, &RID.to_uppercase(), ok.5),
        ),
        ("text", args(ok.0, ok.1, ok.2, ok.3, ok.4, "")),
        ("text", args(ok.0, ok.1, ok.2, ok.3, ok.4, " \n")),
        ("text", args(ok.0, ok.1, ok.2, ok.3, ok.4, "a\0b")),
        ("text", args(ok.0, ok.1, ok.2, ok.3, ok.4, &cap)),
    ] {
        let why = bad.expect_err(what);
        assert!(!why.is_empty());
    }
}
