use openwiz_core::fleet::tick::Rules;

use crate::md3_models::flags;

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
    let rules = Rules::parse(RULES, &flags()).expect("the current rules file is valid");
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
        assert!(Rules::parse(&text, &flags()).is_err(), "{case}");
    }
    let no_merge = RULES
        .lines()
        .filter(|l| !l.starts_with("| A ticket"))
        .collect::<Vec<_>>()
        .join("\n");
    assert_eq!(
        serde_json::to_value(Rules::parse(&no_merge, &flags()).unwrap()).unwrap()["merge"],
        "none"
    );
    assert!(Rules::parse(include_str!("../../docs/agents/fleet.md"), &flags()).is_ok());
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
            Rules::parse(&RULES.replace(heading, "## Unrecognized"), &flags()).is_err(),
            "missing {heading}"
        );
        assert!(
            Rules::parse(&format!("{RULES}\n{heading}\n"), &flags()).is_err(),
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
            Rules::parse(&RULES.replacen(section, &bad, 1), &flags()).is_err(),
            "bad {heading}"
        );
    }
    let wrong = RULES.replace("--provider claude-code", "--provider codex");
    assert!(Rules::parse(&wrong, &flags()).is_err());
    let fleet = include_str!("../../docs/agents/fleet.md");
    let rules = Rules::parse(fleet, &flags()).unwrap();
    assert_eq!(rules.builder().harness, "antigravity");
    assert_eq!(rules.builder().model, "default");
    assert_eq!(rules.builder().effort, "medium");
    assert_eq!(rules.small_builder().harness, "antigravity");
    assert_eq!(rules.small_builder().model, "default");
    assert_eq!(rules.small_builder().effort, "medium");
    let reviewer = rules
        .reviewer_for(openwiz_core::fleet::tick::BuilderFamily::Gpt)
        .unwrap();
    assert_eq!(reviewer.harness, "claude-code");
    assert_eq!(reviewer.model, "claude-opus-5-5");
    assert_eq!(reviewer.effort, "medium");
    for (case, bad) in [
        (
            "skipped fallback index",
            fleet.replacen("| Reviewer fall-back 1 |", "| Reviewer fall-back 2 |", 1),
        ),
        (
            "fallback follows builder",
            fleet.replacen(
                "| Reviewer fall-back 1 | Antigravity | Gemini 4 Neon | High | `--provider antigravity --reasoning-level high` |",
                "| Reviewer fall-back 1 | follows Builder | | | |",
                1,
            ),
        ),
        (
            "missing reasoning-level",
            fleet.replacen(
                "`--provider antigravity --reasoning-level medium`",
                "`--provider antigravity`",
                1,
            ),
        ),
    ] {
        assert!(Rules::parse(&bad, &flags()).is_err(), "{case}");
    }
    fallback_rows_survive_set(fleet);
    let older = RULES.split("## CI checks").next().unwrap();
    let older = older.replace("--provider codex", "--provider claude-code");
    let row = "`--provider codex --model syn --reasoning-level high` |";
    fallback_rows_survive_set(&format!(
        "{fleet}\n{older}## Fixer\n| Builder family | Harness | Model | Effort | `room-cli thread spawn` flags |\n| --- | --- | --- | --- | --- |\n| Claude | S | S | S | {row}\n| GPT | S | S | S | {row}\n"
    ));
}

fn fallback_rows_survive_set(fleet: &str) {
    use openwiz_core::models::{Choice, Role, write};
    let fallbacks = |text: &str| -> Vec<String> {
        text.lines()
            .filter(|l| l.starts_with("| Reviewer fall-back "))
            .map(str::to_owned)
            .collect()
    };
    assert_eq!(fallbacks(fleet).len(), 2);
    let mut text = fleet.to_owned();
    for effort in ["high", "low"] {
        let asked = write::Asked::Choice(Choice::named("antigravity", "default", effort).unwrap());
        text = write::set(&text, Role::Builder, &asked, &flags())
            .unwrap_or_else(|e| panic!("set refused: {e}"))
            .text
            .unwrap();
        assert_eq!(
            fallbacks(&text),
            fallbacks(fleet),
            "set kept the fall-back rows"
        );
        assert!(
            text.contains(&format!(
                "`--provider antigravity --reasoning-level {effort}`"
            )),
            "set wrote no --model"
        );
        assert!(!text.contains("--model default"), "no row names a model");
        assert!(Rules::parse(&text, &flags()).is_ok());
    }
}

fn b2_1196_setup_template_can_produce_the_strict_rules() {
    let filled = include_str!("../../skills/setup/templates/fleet.md")
        .replace(
            "`--provider <id> --model <id> --reasoning-level <level>`",
            "`--provider codex --model syn-model --reasoning-level high`",
        )
        .replace("`<job name>`", "`synthetic`")
        .replace("`<branch>`", "`main`");
    assert!(
        Rules::parse(&filled, &flags()).is_ok(),
        "setup must emit parseable rules"
    );
}
