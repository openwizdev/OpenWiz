//! B2 proof plan (#118). Fixture tests only; no live claim.
//!
//! Rules: table-test fleet.md's operative rows, malformed forms and duplicates.
//! S2-1: one eligible merge, then remove each authority, head, reviewer, CI,
//! base and branch condition independently; every negative has zero merges.
//! Frontier: approved rows across versions, verified blockers, ready labels,
//! starts (including crashes and uncertainty), holds, people and stale plans.
//! Reviews: first/fresh/re-check, findings and CI failures; per-head records.
//! S2-4: an idle snapshot yields exactly [] and no judgment items.
//! S2-5: exact/directory/folder-local glob contract matches; holds block starts,
//! building tickets get notes; two hits are consumed lowest PR first per tick.
//! S2-6: closed-ticket agents archived once; close/unlock and summary lifecycle.
//! Judgment: new questions, independent dispute/diagnosis records, unread or
//! duplicate facts, quiet reviewers and blocked merges yield one combined look.
//! Output: exact facts against independent literals, every action against the
//! published tick schema, canonical ordering, and no additional dependencies.

use openwiz_core::fleet::tick::Rules;

const RULES: &str = "## Builder
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-builder` |
| Effort | Synthetic | `--reasoning-level high` |
## Reviewer for GPT-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider claude-code` |
| Model | Synthetic | `--model syn-reviewer` |
| Effort | Synthetic | `--reasoning-level high` |
## Builder for small tickets
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-small` |
| Effort | Synthetic | `--reasoning-level high` |
## Reviewer for Claude-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Synthetic | `--provider codex` |
| Model | Synthetic | `--model syn-gpt-reviewer` |
| Effort | Synthetic | `--reasoning-level high` |
## CI checks
| Check | Runs | Required on |
| --- | --- | --- |
| `web-build` | Synthetic | `main`, `release-*` |
| `rust` | Synthetic | `main`, `release-*` |
| `web-test` | Synthetic | `main`, `release-*` |
## Standing merge rules
| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph | Synthetic | The loop, as soon as the reviewer's APPROVE names that exact commit and all checks pass |
";

#[test]
fn fleet_rules_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 4] = [
        (
            "b2_1196_all_conditional_tables_are_strict_and_other_family",
            b2_1196_all_conditional_tables_are_strict_and_other_family,
        ),
        (
            "b2_1196_setup_template_can_produce_the_strict_rules",
            b2_1196_setup_template_can_produce_the_strict_rules,
        ),
        ("b2_reads_the_operative_rules", b2_reads_the_operative_rules),
        (
            "b2_rules_refuse_every_malformed_operative_form",
            b2_rules_refuse_every_malformed_operative_form,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: b2_planner::{name}");
        proof();
    }
}

fn b2_reads_the_operative_rules() {
    let rules = Rules::parse(RULES).expect("the current rules file is valid");
    let value = serde_json::to_value(rules).unwrap();
    assert_eq!(value["builder"]["model"], "syn-builder");
    assert_eq!(value["reviewer_gpt"]["model"], "syn-reviewer");
    assert_eq!(value["merge"], "adr_0008");
}

fn b2_rules_refuse_every_malformed_operative_form() {
    let bad = [
        (
            "missing section",
            RULES.replace("## Builder", "## Not Builder"),
        ),
        ("duplicate section", format!("{RULES}\n## Builder\n")),
        (
            "wrong header",
            RULES.replace("| Setting | Value |", "| Value | Setting |"),
        ),
        (
            "bad separator",
            RULES.replace("| --- | --- | --- |", "| --- | :--- | --- |"),
        ),
        (
            "extra cell",
            RULES.replace("| Harness | Synthetic |", "| Harness | extra | Synthetic |"),
        ),
        (
            "duplicate setting",
            RULES.replace("| Model |", "| Harness |"),
        ),
        (
            "wrong flag",
            RULES.replace("--provider codex", "--harness codex"),
        ),
        (
            "uppercase setting",
            RULES.replace("--provider codex", "--provider Codex"),
        ),
        (
            "unicode setting",
            RULES.replace("--provider codex", "--provider cödex"),
        ),
        (
            "template setting",
            RULES.replace("--model syn-builder", "--model <id>"),
        ),
        (
            "duplicate check",
            RULES.replace("`rust` | Synthetic", "`web-build` | Synthetic"),
        ),
        (
            "duplicate branch",
            RULES.replace("`main`, `release-*`", "`main`, `main`"),
        ),
        ("middle glob", RULES.replace("release-*", "release-*-a")),
        (
            "branch separator",
            RULES.replace("`main`, `release-*`", "`main`,`release-*`"),
        ),
        (
            "duplicate merge row",
            format!("{RULES}{}", RULES.lines().last().unwrap()),
        ),
    ];
    for (case, text) in bad {
        assert!(Rules::parse(&text).is_err(), "{case}");
    }
    let no_merge = RULES
        .lines()
        .filter(|l| !l.starts_with("| A ticket"))
        .collect::<Vec<_>>()
        .join("\n");
    assert_eq!(
        serde_json::to_value(Rules::parse(&no_merge).unwrap()).unwrap()["merge"],
        "none"
    );
    assert!(Rules::parse(include_str!("../../docs/agents/fleet.md")).is_ok());
}

#[path = "b2_cases.rs"]
mod cases;

fn b2_1196_all_conditional_tables_are_strict_and_other_family() {
    for heading in [
        "## Builder for small tickets",
        "## Reviewer for Claude-built",
        "## Reviewer for GPT-built",
    ] {
        assert!(
            Rules::parse(&RULES.replace(heading, "## Unrecognized")).is_err(),
            "missing {heading}"
        );
        assert!(
            Rules::parse(&format!("{RULES}\n{heading}\n")).is_err(),
            "duplicate {heading}"
        );
        let at = RULES.find(heading).unwrap();
        let tail = &RULES[at..];
        let end = tail[heading.len()..]
            .find("\n## ")
            .map_or(tail.len(), |i| heading.len() + i);
        let section = &tail[..end];
        let bad = section.replace("| Model |", "| Harness |");
        assert!(
            Rules::parse(&RULES.replacen(section, &bad, 1)).is_err(),
            "bad {heading}"
        );
    }
    let wrong = RULES.replace("--provider claude-code", "--provider codex");
    assert!(Rules::parse(&wrong).is_err());
    let rules = Rules::parse(include_str!("../../docs/agents/fleet.md")).unwrap();
    assert_eq!(rules.builder().harness, "claude-code");
    assert_eq!(rules.builder().model, "claude-opus-5-5");
    assert_eq!(rules.builder().effort, "high");
    assert_eq!(rules.small_builder().harness, "codex");
    assert_eq!(rules.small_builder().model, "gpt-6.1-sol");
    assert_eq!(rules.small_builder().effort, "high");
    assert_eq!(
        rules
            .reviewer_for(openwiz_core::fleet::tick::BuilderFamily::Claude)
            .harness,
        "codex"
    );
    assert_eq!(
        rules
            .reviewer_for(openwiz_core::fleet::tick::BuilderFamily::Gpt)
            .harness,
        "claude-code"
    );
}

fn b2_1196_setup_template_can_produce_the_strict_rules() {
    // Fill the template's setting/check placeholders with synthetic literals.
    // A fresh setup must supply every table the product requires.
    let filled = include_str!("../../skills/setup/templates/fleet.md")
        .replace("`--provider <id>`", "`--provider codex`")
        .replace("`--model <id>`", "`--model syn-model`")
        .replace("`--reasoning-level <level>`", "`--reasoning-level high`")
        .replace("`<job name>`", "`synthetic`")
        .replace("`<branch>`", "`main`");
    assert!(
        Rules::parse(&filled).is_ok(),
        "setup must emit parseable rules"
    );
}
