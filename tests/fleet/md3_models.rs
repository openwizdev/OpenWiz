use std::fs;
use std::path::Path;

use openwiz_adapter_cloudroom::allowlist::{Invocation, SpawnArgs};
use openwiz_core::fleet::tick::{AgentRule, BuilderFamily, Rules};
use openwiz_core::models::SpawnFlags;
use serde_json::Value;

const MODELS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/fixtures/models");

const TAIL: &str = "
## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `rust` | Synthetic | `main` |

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph | Synthetic | The loop, as soon as the reviewer's APPROVE names that exact commit and all checks pass |
";

pub(crate) fn flags() -> SpawnFlags {
    let (provider, model, effort) = ("claude-code", "syn-md3-flags", "medium");
    let request = format!("ow1-{}", "0".repeat(40));
    let args = SpawnArgs::new("syn-md3", provider, model, effort, &request, "syn").unwrap();
    let argv = Invocation::ThreadSpawn(args).argv();
    let word = |value: &str| {
        let at = argv.iter().position(|w| w == value).unwrap();
        argv[at - 1].clone()
    };
    SpawnFlags {
        provider: word(provider),
        model: word(model),
        effort: word(effort),
    }
}

pub(crate) fn fixture(case: &str) -> String {
    fs::read_to_string(Path::new(MODELS).join(case).join("fleet.md")).unwrap() + TAIL
}

fn read(case: &str) -> Result<Rules, &'static str> {
    Rules::parse(&fixture(case), &flags())
}

fn agent(choice: &Value) -> Option<AgentRule> {
    (!choice.is_null()).then(|| AgentRule {
        harness: choice["provider"].as_str().unwrap().to_owned(),
        model: choice["model"].as_str().unwrap().to_owned(),
        effort: choice["effort"].as_str().unwrap().to_owned(),
    })
}

fn j255(harness: &str, model: &str) -> Option<AgentRule> {
    Some(AgentRule {
        harness: harness.to_owned(),
        model: model.to_owned(),
        effort: "medium".to_owned(),
    })
}

type Picks = [Option<AgentRule>; 6];

fn picks(rules: &Rules) -> Picks {
    [
        Some(rules.builder().clone()),
        Some(rules.small_builder().clone()),
        rules.reviewer_for(BuilderFamily::Claude).cloned(),
        rules.reviewer_for(BuilderFamily::Gpt).cloned(),
        rules.fixer(BuilderFamily::Claude).cloned(),
        rules.fixer(BuilderFamily::Gpt).cloned(),
    ]
}

#[test]
fn md3_one_table_and_five_tables_give_the_same_j255_choices() {
    let opus = j255("claude-code", "claude-opus-5-5");
    let sol = j255("codex", "gpt-6.2-sol");
    let today: Picks = [
        opus.clone(),
        opus.clone(),
        sol.clone(),
        opus.clone(),
        opus,
        sol,
    ];
    for case in ["one-table", "five-tables", "both"] {
        let rules = read(case);
        assert_eq!(rules.as_ref().map(picks), Ok(today.clone()), "{case}");
    }
}

#[test]
fn md3_every_tick_readable_fixture_agrees_with_its_show() {
    for case in [
        "one-table",
        "five-tables",
        "both",
        "overridden",
        "same-family",
    ] {
        let show: Value = serde_json::from_str(
            &fs::read_to_string(Path::new(MODELS).join(case).join("show.json")).unwrap(),
        )
        .unwrap();
        let roles = &show["roles"];
        let want: Picks = [
            agent(&roles["builder"]["choice"]),
            agent(&roles["small_builder"]["choice"]),
            agent(&show["reviews"]["claude"]["choice"]),
            agent(&show["reviews"]["gpt"]["choice"]),
            agent(&show["fixers"]["claude"]["choice"]),
            agent(&show["fixers"]["gpt"]["choice"]),
        ];
        assert_eq!(read(case).as_ref().map(picks), Ok(want), "{case}");
    }
}

#[test]
fn md3_a_same_family_reviewer_falls_back_to_the_builder_or_waits() {
    let review =
        |text: &str, family| Rules::parse(text, &flags()).map(|r| r.reviewer_for(family).cloned());
    let opus = j255("claude-code", "claude-opus-5-5");
    let sol = j255("codex", "gpt-6.2-sol");
    let mut high = opus.clone();
    if let Some(h) = high.as_mut() {
        h.effort = "high".to_owned();
    }
    let one = fixture("one-table");
    let same = fixture("same-family");
    let gpt = one.replace(
        "| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |",
        "| Builder | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |",
    );
    assert_ne!(gpt, one);
    for (case, text, family, want) in [
        ("builder fallback", &one, BuilderFamily::Gpt, opus),
        ("claude waits", &same, BuilderFamily::Claude, None),
        ("reviewer serves gpt", &same, BuilderFamily::Gpt, high),
        ("both gpt waits", &gpt, BuilderFamily::Gpt, None),
        ("both gpt reviews claude", &gpt, BuilderFamily::Claude, sol),
    ] {
        assert_eq!(review(text, family), Ok(want), "{case}");
    }
}

#[test]
fn md3_a_broken_models_table_is_refused_never_read_past() {
    let five = fixture("five-tables");
    let broken = five.replacen(
        "## Builder\n",
        "## Models\n\n| Role | Harness |\n| --- | --- |\n\n## Builder\n",
        1,
    );
    assert!(Rules::parse(&five, &flags()).is_ok());
    assert_eq!(
        Rules::parse(&broken, &flags()).err(),
        Some("models table refused")
    );
    let twice = format!("{}\n## Models\n", fixture("one-table"));
    assert_eq!(
        Rules::parse(&twice, &flags()).err(),
        Some("models table refused")
    );
}

#[test]
fn md3_a_namespaced_or_upper_case_id_is_read_and_an_overlong_one_refused() {
    let one = fixture("one-table");
    let long = format!("--model {}", "x".repeat(129));
    for (to, want) in [
        ("--model vendor/demo", Ok(Some("vendor/demo"))),
        ("--model Sol-6.2", Ok(Some("Sol-6.2"))),
        (long.as_str(), Err("invalid agent setting")),
    ] {
        let text = one.replacen("--model gpt-6.2-sol", to, 1);
        assert_ne!(text, one);
        let model = Rules::parse(&text, &flags()).map(|r| {
            r.reviewer_for(BuilderFamily::Claude)
                .map(|a| a.model.clone())
        });
        assert_eq!(model, want.map(|m| m.map(String::from)), "{to}");
    }
}

#[test]
fn md3_five_tables_keep_the_older_lowercase_setting_form() {
    let five = fixture("five-tables");
    assert!(Rules::parse(&five, &flags()).is_ok());
    for (from, to) in [
        ("`--reasoning-level medium`", "`--reasoning-level Medium`"),
        ("`--model gpt-6.2-sol`", "`--model vendor/demo`"),
    ] {
        let text = five.replacen(from, to, 1);
        assert_ne!(text, five);
        assert_eq!(
            Rules::parse(&text, &flags()).err(),
            Some("invalid agent setting"),
            "{to}"
        );
    }
}
