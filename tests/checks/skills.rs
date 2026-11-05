//! The skills folder (OpenWiz 0.0.5, ClosedWiz#96; five more in 0.0.7,
//! ClosedWiz#225): the skills install in one step, and any agent, in any
//! harness, can invoke them.
//!
//! Rules, checked on the repository and on planted breaks:
//! 1. **The list, exactly.** `skills/` holds `README.md` and one real folder
//!    for each name in [`SKILLS`], and no links anywhere (Codex drops links
//!    when it installs a plugin).
//! 2. **Frontmatter.** Each `SKILL.md` opens with `name` (its folder's name)
//!    and `description`, one line each, and no other key. It is an allowlist,
//!    except ask-wiz requires `disable-model-invocation: true` (#1095).
//! 3. **Codex.** `agents/openai.yaml`, where present, holds only
//!    `interface.display_name` and `interface.short_description`, never a
//!    `policy`, except ask-wiz requires `allow_implicit_invocation: false`.
//! 4. **Matt's MIT notice.** Every skill but those in [`NOT_MATTS`] adapts
//!    Matt Pocock's, so once written (any body but the exact [`STUB`]) it
//!    carries his copyright and MIT notice word for word. Each skill in
//!    [`NOT_MATTS`] instead carries its source line, exactly and on a line of
//!    its own, stub or written, and never his copyright line or notice. Every
//!    written skill has its `agents/openai.yaml`.
//! 5. **Links resolve.** `.claude/skills/<name>` and `.agents/skills/<name>`
//!    are links to `../../skills/<name>`, every link in those two folders is
//!    one of them, and every relative Markdown link under `skills/` resolves
//!    inside the repository.
//! 6. **Manifests.** `.claude-plugin/plugin.json` lists exactly
//!    `./skills/<name>` for each skill, beside metadata only, and
//!    `.claude-plugin/marketplace.json` offers that one plugin from `./`.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, FileType};
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

// #1453: pin the operative helper settings, not historical source quotes.
#[test]
fn codex_helpers_use_sol_high_default_tier_and_claude_helpers_keep_their_family() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/fleet.md")).expect("fleet settings");
    let section = |heading| {
        text.split_once(heading)
            .expect("helper section")
            .1
            .split("\n## ")
            .next()
            .unwrap()
    };
    for (heading, expected) in [
        (
            "## Reviewer helpers\n",
            [
                "| Harness | Codex | `--provider codex` |",
                "| Model | Sol 6.1 | `--model gpt-6.1-sol` |",
                "| Effort | High | `--reasoning-level high` |",
            ],
        ),
        (
            "## Builder helpers\n",
            [
                "| Harness | Claude Code | `--provider claude-code` |",
                "| Model | Haiku 5.5 | `--model claude-haiku-5-5` |",
                "| Effort | High | `--reasoning-level high` |",
            ],
        ),
    ] {
        let rows: Vec<_> = section(heading)
            .lines()
            .filter(|line| {
                ["| Harness |", "| Model |", "| Effort |"]
                    .iter()
                    .any(|prefix| line.starts_with(prefix))
            })
            .collect();
        assert_eq!(rows, expected, "{heading}");
    }
    let operative_line = |prefix| {
        let lines: Vec<_> = text
            .lines()
            .filter(|line| line.starts_with(prefix))
            .collect();
        assert_eq!(lines.len(), 1, "one operative {prefix} rule");
        lines[0]
    };
    assert!(operative_line("Codex builders instead use ").contains(
        "Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`)"
    ));
    let policy = operative_line("Codex service tier:");
    for required in [
        "builders, reviewers, helpers and hunters use Sol 6.1 at High, or XHigh for hard work, at the default service tier",
        "Do not enable fast mode; omit `--service-tier` overrides",
        "Source: Jake, 2026-11-07:",
        "superseding the 2026-11-04 fast-mode rule",
        "https://github.com/jparker2006/ClosedWiz/issues/1988#issuecomment-6712108296",
    ] {
        assert!(
            policy.contains(required),
            "missing Codex policy: {required}"
        );
    }
    assert!(operative_line("**Spec #330 ").contains("reviewer helpers Sol 6.1, High"));
    let helpers = fs::read_to_string(Path::new(ROOT).join("docs/agents/helpers.md"))
        .expect("helper settings");
    let flags = helpers
        .lines()
        .find(|line| line.starts_with("- **The flags**"))
        .expect("operative helper flags");
    assert!(flags.contains("Sol 6.1 at High, or XHigh for hard work, at the default service tier"));
    assert!(flags.contains("omit `--service-tier` overrides"));
    let hunters =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("hunter settings");
    assert!(
        hunters
            .lines()
            .any(|line| line == "| Wide hunting and reruns | `codex` | `gpt-6.1-terra` | `high` |")
    );
    let hunt_skill =
        fs::read_to_string(Path::new(ROOT).join("skills/huntr/SKILL.md")).expect("huntr skill");
    assert!(hunt_skill.contains("**Codex Terra 6.1 High** reads widely"));
    for settings in [&text, &helpers] {
        assert!(!settings.contains("gpt-6.1-terra"));
    }
    for (name, settings) in [
        ("fleet", &text),
        ("helpers", &helpers),
        ("hunters", &hunters),
        ("huntr skill", &hunt_skill),
    ] {
        for obsolete in ["--service-tier fast", "High, fast", "High fast"] {
            assert!(
                !settings.contains(obsolete),
                "{name} still requires {obsolete}"
            );
        }
    }
    let claude_review = operative_line("Reviewers of GPT-built pull requests instead use ");
    assert!(claude_review.contains(
        "Claude Code, Haiku 5.5, High (`--provider claude-code --model claude-haiku-5-5 --reasoning-level high`)"
    ));
    assert!(claude_review.contains("another family than the build, helpers included"));
}

// #999: deferring one fresh nightly claim must not stop other due work.
#[test]
fn fresh_nightly_claim_continues_the_ticks_other_lines() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/launch-fleet/SKILL.md"))
        .expect("launch-fleet skill");
    let claim = text
        .split_once("4. **An existing claim is unfinished delivery, not permission to resend.**")
        .expect("nightly claim reconciliation instruction")
        .1
        .split("\n\n")
        .next()
        .expect("fresh claim paragraph")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    assert!(
        claim.contains("leave it alone and go on with the tick's other lines; do not report `needs-you` for this claim."),
        "a fresh claim defers only its own notification: {claim}"
    );
    assert!(!claim.contains("end this tick"));
}

#[test]
fn codex_default_tier_setting_discloses_rust_dispatch_limitation() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/fleet.md")).expect("fleet settings");
    let limitations: Vec<_> = text
        .split("\n\n")
        .filter(|paragraph| paragraph.starts_with("**Rust dispatch limitation (#1465):**"))
        .collect();
    assert_eq!(
        limitations.len(),
        1,
        "one explicit Rust dispatch limitation"
    );
    for required in [
        "`AgentRule` and start `Settings` have no service-tier field",
        "`ThreadSpawn` argument builder emits no service-tier argument",
        "Codex starts depend on endpoint defaults",
        "Effective tiers of existing threads are unverified",
        "this settings change does not establish their tier or change them",
    ] {
        assert!(
            limitations[0].contains(required),
            "missing dispatch disclosure: {required}"
        );
    }
}

#[test]
fn reviewer_builder_family_has_a_recorded_source() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/fleet.md")).expect("fleet settings");
    let reviewer = text
        .split_once("## Reviewer\n")
        .expect("Reviewer section")
        .1
        .split("\n## ")
        .next()
        .expect("Reviewer body");
    let rules: Vec<_> = reviewer
        .lines()
        .filter(|line| line.starts_with("- **Builder family source.**"))
        .collect();
    assert_eq!(rules.len(), 1, "one operative builder-family source rule");
    for required in [
        "launch-fleet: start checked, thread <id>, branch <branch>",
        "branch must match the PR's head branch",
        "read that exact thread's provider with `room-cli`",
        "`codex` means GPT",
        "`claude-code` means Claude",
        "Do not infer family from today's builder settings",
        "missing, unreadable or conflicting",
        "any other provider",
        "family stays unknown and reviewer assignment waits",
    ] {
        assert!(
            rules[0].contains(required),
            "missing source rule: {required}"
        );
    }
}

#[test]
fn diagnose_orchestrator_is_listed_in_the_skills_table() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/README.md")).expect("skills README");
    let rows: Vec<_> = text
        .lines()
        .filter(|line| line.starts_with("| [`diagnose`](diagnose/SKILL.md) |"))
        .collect();
    assert_eq!(rows.len(), 1, "one diagnose row in the skills table");
    assert_eq!(
        rows[0].split('|').nth(2).expect("Run by cell").trim(),
        "builder; orchestrator, for its +1 diagnosis"
    );
}

#[test]
fn diagnose_orchestrator_is_routed_from_review_findings() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/launch-fleet/SKILL.md"))
        .expect("launch-fleet skill");
    let findings: Vec<_> = text
        .split("\n\n")
        .filter(|paragraph| paragraph.starts_with("**Findings** (a `findings` line):"))
        .collect();
    assert_eq!(findings.len(), 1, "one operative Findings instruction");
    assert!(
        findings[0].contains("when `Next:` asks for the orchestrator's diagnosis, tell the orchestrator `Use the diagnose skill. Read 'skills/diagnose/SKILL.md' if present, otherwise find '*/skills/diagnose/SKILL.md' only inside your own harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default HOME/.codex/plugins/cache); Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise CLAUDE_CONFIG_DIR/plugins/cache (default HOME/.claude/plugins/cache); for another harness use its installation metadata. Prefer active installation metadata over cache scanning when available. During cache scans exclude other harness caches, source checkouts, orphaned versions marked .orphaned_at, and targets outside the selected cache. Follow symlinks and deduplicate real paths. Verify .claude-plugin/plugin.json manifest name openwiz and entry ./skills/diagnose; report missing, unreadable or ambiguous matches, otherwise read the unique matching file and follow it for the finding.`;"),
        "the diagnosis escalation must name the skill and instruct the orchestrator to follow it for the finding"
    );
}

// #1000: nightly due lines cannot supply a number to wake.
#[test]
fn launch_fleet_nightly_only_tick_reaches_step_six() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/launch-fleet/SKILL.md"))
        .expect("launch-fleet skill");
    let tick = text
        .split_once("## 2. Each tick\n")
        .expect("Each tick section")
        .1
        .split("\n## ")
        .next()
        .expect("tick body");
    let safety_net = tick
        .lines()
        .find(|line| line.starts_with("- **The safety net's lines:**"))
        .expect("operative safety-net instruction");
    for rule in [
        "`nightly red` lines have no `#N`",
        "handle them in step 6, which runs the full check itself",
        "including lines with `; reconcile comment ...`",
    ] {
        assert!(safety_net.contains(rule), "missing nightly routing: {rule}");
    }
    let early_exit = tick
        .split("\n\n")
        .find(|paragraph| {
            paragraph.starts_with("If there are no numbers, or `wake` prints nothing,")
        })
        .expect("operative early-exit instruction");
    assert!(
        early_exit.contains("archive only when no `nightly red` line is due"),
        "empty numbers or wake output must not discard due nightly work"
    );
}

// #482: project build tools belong in fleet settings, not portable skills.
const ISOLATION_RULE: &str = "Run nothing beside the full set in the same checkout when \
`docs/agents/fleet.md`'s test commands say its builds replace files the tests use; \
anything beside it goes in a separate worktree with its own build output. \
Never share build output between those worktrees.";

// CommonMark fences allow at most three leading spaces. Keep the whole run:
// shorter runs and a different marker cannot close an existing fence.
fn fence_marker(line: &str) -> Option<(u8, usize, &str)> {
    let trimmed = line.trim_start_matches(' ');
    if line.len() - trimmed.len() > 3 {
        return None;
    }
    let marker = *trimmed.as_bytes().first()?;
    if !matches!(marker, b'`' | b'~') {
        return None;
    }
    let count = trimmed.bytes().take_while(|&b| b == marker).count();
    (count >= 3).then_some((marker, count, &trimmed[count..]))
}

fn fence_opener(line: &str) -> Option<(u8, usize)> {
    let (marker, count, info) = fence_marker(line)?;
    (marker != b'`' || !info.contains('`')).then_some((marker, count))
}

fn atx_heading(line: &str) -> bool {
    let text = line.trim_start_matches(' ');
    let hashes = text.bytes().take_while(|&b| b == b'#').count();
    line.len() - text.len() <= 3
        && (1..=6).contains(&hashes)
        && (hashes == text.len() || text[hashes..].starts_with([' ', '\t', '\r', '\n']))
}

// The static gate supports multiline inline code only in plain paragraphs.
// Container syntax is a conservative hard boundary, not recursively unwrapped
// to manufacture an operative prefix (the #994 +1 diagnosis).
fn container_marker(line: &str) -> bool {
    let text = line.trim_start_matches([' ', '\t']);
    if text.starts_with('>') {
        return true;
    }
    let rest = if let Some(rest) = text.strip_prefix(['-', '+', '*']) {
        Some(rest)
    } else {
        let digits = text.bytes().take_while(u8::is_ascii_digit).count();
        (1..=9)
            .contains(&digits)
            .then(|| text[digits..].strip_prefix(['.', ')']))
            .flatten()
    };
    rest.and_then(|suffix| suffix.as_bytes().first())
        .is_some_and(u8::is_ascii_whitespace)
}

// Block structure is determined before inline spans (CommonMark 3.1). A
// paragraph cannot lend its opening backticks to a later block's closer.
fn paragraph_boundary(line: &str) -> bool {
    if line.trim().is_empty()
        || fence_opener(line).is_some()
        || atx_heading(line)
        || container_marker(line)
    {
        return true;
    }
    let text = line.trim_end_matches(['\r', '\n']).trim_start_matches(' ');
    let indent = line.trim_end_matches(['\r', '\n']).len() - text.len();
    if indent > 3 {
        return false; // indentation alone cannot interrupt a paragraph
    }
    let bare = text.trim_end_matches([' ', '\t']);
    if text.starts_with('>')
        || (!bare.is_empty()
            && (bare.bytes().all(|b| b == b'=') || bare.bytes().all(|b| b == b'-')))
        || b"-*_".iter().copied().any(|marker| {
            text.bytes().filter(|&b| b == marker).count() >= 3
                && text
                    .bytes()
                    .all(|b| b == marker || matches!(b, b' ' | b'\t'))
        })
    {
        return true;
    }
    let bullet = text.strip_prefix(['-', '+', '*']);
    let digits = text.bytes().take_while(u8::is_ascii_digit).count();
    let ordered = (digits <= 9
        && text
            .get(..digits)
            .is_some_and(|n| n.parse::<u32>() == Ok(1)))
    .then(|| text[digits..].strip_prefix(['.', ')']))
    .flatten();
    if bullet
        .or(ordered)
        .is_some_and(|rest| rest.starts_with([' ', '\t']) && !rest.trim().is_empty())
    {
        return true;
    }
    // HTML blocks of types 1-6 can interrupt paragraphs; arbitrary inline
    // tags (type 7) cannot. Match the spec's tag names and delimiters exactly.
    if ["<!--", "<?", "<![CDATA["]
        .iter()
        .any(|opener| text.starts_with(opener))
        || text
            .strip_prefix("<!")
            .is_some_and(|s| s.starts_with(|c: char| c.is_ascii_alphabetic()))
    {
        return true;
    }
    let Some(tag) = text.strip_prefix('<') else {
        return false;
    };
    let closing = tag.starts_with('/');
    let tag = tag.strip_prefix('/').unwrap_or(tag);
    let end = tag.bytes().take_while(u8::is_ascii_alphanumeric).count();
    let name = tag[..end].to_ascii_lowercase();
    let suffix = &tag[end..];
    let delimiter = suffix.is_empty() || suffix.starts_with([' ', '\t', '>']);
    (!closing && matches!(name.as_str(), "pre" | "script" | "style" | "textarea") && delimiter)
        || ((delimiter || suffix.starts_with("/>"))
            && "address article aside base basefont blockquote body caption center col colgroup \
                dd details dialog dir div dl dt fieldset figcaption figure footer form frame \
                frameset h1 h2 h3 h4 h5 h6 head header hr html iframe legend li link main menu \
                menuitem nav noframes ol optgroup option p param search section summary table \
                tbody td tfoot th thead title tr track ul"
                .split_ascii_whitespace()
                .any(|block_tag| block_tag == name))
}

// Only a matching backtick run makes an inline code span. An unmatched run
// must not hide a later comment. Spans may cross lines within a paragraph,
// but cannot cross into another block (block parsing comes first).
fn code_span_end(text: &str, ticks: usize) -> Option<usize> {
    let mut offset = 0;
    for (index, line) in text.split_inclusive('\n').enumerate() {
        if index > 0 && paragraph_boundary(line) {
            return None;
        }
        let mut pos = 0;
        while pos < line.len() {
            if line.as_bytes()[pos] == b'`' {
                let count = line[pos..].bytes().take_while(|&b| b == b'`').count();
                if count == ticks {
                    return Some(offset + pos + count);
                }
                pos += count;
            } else {
                pos += 1;
            }
        }
        offset += line.len();
    }
    None
}

/// Physical lines, each with contiguous visible pieces outside fences/comments.
/// Rule matching must not join pieces across a comment to manufacture a rule.
/// Inline code remains visible but its literal comment markers have no effect.
fn visible_lines(section: &str) -> Vec<Vec<&str>> {
    let mut out = Vec::new();
    let mut fence = None;
    let mut comment = false;
    let mut paragraph = false;
    let mut code_until = 0;
    let mut offset = 0;
    for raw in section.split_inclusive('\n') {
        let line = raw.trim_end_matches(['\r', '\n']);
        let start = offset;
        offset += raw.len();
        if let Some((marker, count)) = fence {
            if fence_marker(line).is_some_and(|(close, length, suffix)| {
                close == marker && length >= count && suffix.trim_matches([' ', '\t']).is_empty()
            }) {
                fence = None;
            }
            continue;
        }
        if !comment && code_until <= start {
            if let Some(open) = fence_opener(line) {
                fence = Some(open);
                paragraph = false;
                continue;
            }
            // Indented code is literal only outside an existing paragraph.
            if !paragraph
                && (line.starts_with("    ") || line.trim_start_matches(' ').starts_with('\t'))
            {
                continue;
            }
        }
        let mut pos = 0;
        let mut visible_start = 0;
        let mut pieces = Vec::new();
        while pos < line.len() {
            if comment {
                let Some(end) = line[pos..].find("-->") else {
                    break;
                };
                pos += end + 3;
                visible_start = pos;
                comment = false;
            } else if start + pos < code_until {
                pos = (code_until - start).min(line.len());
            } else if line.as_bytes()[pos] == b'\\' {
                // An escaped '<' or backtick cannot open markup.
                pos = (pos + 2).min(line.len());
            } else if line.as_bytes()[pos] == b'`' {
                let ticks = line[pos..].bytes().take_while(|&b| b == b'`').count();
                pos += ticks;
                // A heading/container-marked opener stays on this physical
                // line. Only plain prose may borrow a later line's closer.
                let text = if atx_heading(line) || container_marker(line) {
                    &line[pos..]
                } else {
                    &section[start + pos..]
                };
                if let Some(end) = code_span_end(text, ticks) {
                    code_until = start + pos + end;
                }
            } else if line.as_bytes()[pos] == b'<' && line[pos..].starts_with("<!--") {
                pieces.push(&line[visible_start..pos]);
                let tail = &line[pos..];
                // The two short HTML comment forms close without a later '-->'.
                if tail.starts_with("<!-->") || tail.starts_with("<!--->") {
                    pos += if tail.starts_with("<!-->") { 5 } else { 6 };
                    visible_start = pos;
                } else {
                    pos += 4;
                    comment = true;
                }
            } else {
                pos += 1;
            }
        }
        if !comment {
            pieces.push(&line[visible_start..]);
        }
        out.push(pieces);
        paragraph = !line.trim().is_empty() && !line.trim_start().starts_with("<!--");
    }
    out
}

fn portable_isolation_rule_holds(section: &str, prefix: &str) -> bool {
    visible_lines(section).into_iter().any(|pieces| {
        let visible_text = pieces.concat().to_ascii_lowercase();
        pieces
            .iter()
            .any(|piece| piece.starts_with(prefix) && piece.contains(ISOLATION_RULE))
            && !["cargo", "target/", "cargo_target_dir"]
                .iter()
                .any(|detail| visible_text.contains(detail))
    })
}

fn assert_portable_isolation_rule(skill: &str, heading: &str, prefix: &str) {
    let text = fs::read_to_string(Path::new(ROOT).join(format!("skills/{skill}/SKILL.md")))
        .expect("skill");
    let section = text
        .split_once(heading)
        .expect("operative section")
        .1
        .split("\n## ")
        .next()
        .expect("section body");
    assert!(
        portable_isolation_rule_holds(section, prefix),
        "skills/{skill}/SKILL.md {section_name}: the isolation rule must be one visible line \
         outside any fenced block or HTML comment, carry the full required wording, and name no \
         project-specific build detail",
        section_name = heading.trim().trim_start_matches('#').trim()
    );
}

#[test]
fn builder_checkout_isolation_is_portable() {
    assert_portable_isolation_rule(
        "build-ticket",
        "## 3. Check before you hand back\n",
        "2. **Scoped local checks:**",
    );
}

// #993: a project's recorded rule need not name its cause, so both sides
// defer to it, not only the reviewer.
#[test]
fn builder_follows_the_fleet_test_command_rule() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/build-ticket/SKILL.md"))
        .expect("build-ticket skill");
    let section = text
        .split_once("## 3. Check before you hand back\n")
        .expect("step 3")
        .1
        .split("\n## ")
        .next()
        .expect("section body");
    assert!(
        visible_lines(section).into_iter().flatten().any(|line| {
            line.starts_with("2. **Scoped local checks:**")
                && line
                    .contains("Follow `docs/agents/fleet.md`'s test-command rule, if it has one.")
        }),
        "build-ticket step 3.2 must follow the fleet's test-command rule"
    );
}

#[test]
fn reviewer_checkout_isolation_is_portable() {
    assert_portable_isolation_rule(
        "review-ticket",
        "## 2. Run the three checks\n",
        "Run nothing beside the full set",
    );
}

#[test]
fn checkout_isolation_check_refuses_hidden_or_shared_output_rules() {
    for (intro, prefix) in [
        (
            "2. **Scoped local checks:** ",
            "2. **Scoped local checks:**",
        ),
        ("", "Run nothing beside the full set"),
    ] {
        let visible = format!("{intro}{ISOLATION_RULE}");
        for bad in [
            format!("```md\n{visible}\n```"),
            format!("~~~md\n{visible}\n~~~"),
            format!("<!--\n{visible}\n-->"),
            visible.replace(" Never share build output between those worktrees.", ""),
        ] {
            assert!(
                !portable_isolation_rule_holds(&bad, prefix),
                "accepted a hidden or incomplete rule: {bad}"
            );
        }
        // R3: a comment cannot shield visible project-specific instructions
        // elsewhere on the rule's physical line. Hidden details are harmless.
        let mut failures = Vec::new();
        for detail in ["cargo test", "target/debug", "CARGO_TARGET_DIR=synthetic"] {
            for bad in [
                format!("{visible} {detail} <!-- note -->"),
                format!("{visible} <!-- note --> {detail}"),
                format!("{visible} <!-- a --> <!-- b --> {detail}"),
            ] {
                if portable_isolation_rule_holds(&bad, prefix) {
                    failures.push(format!("accepted a visible build detail: {bad}"));
                }
            }
            let hidden = format!("{visible} <!-- {detail} --> portable text");
            if !portable_isolation_rule_holds(&hidden, prefix) {
                failures.push(format!(
                    "a hidden build detail hid a portable rule: {hidden}"
                ));
            }
        }
        // Removing a comment must not conceal a forbidden token split across
        // visible pieces of the same line. Expected tokens are literal fixtures.
        for split_detail in [
            "ca<!-- note -->rgo test",
            "tar<!-- note -->get/debug",
            "CA<!-- note -->RGO_TAR<!-- note -->GET_DIR=synthetic",
            "c<!-- a -->ar<!-- b -->go test",
            "CA<!-- note -->RGO test",
        ] {
            let bad = format!("{visible} {split_detail}");
            if portable_isolation_rule_holds(&bad, prefix) {
                failures.push(format!("accepted a split visible build detail: {bad}"));
            }
        }
        for good in [
            format!("{visible} <!-- note --> portable text"),
            format!("{visible} ca<!-- hidden -->r go text"),
            format!("{visible} <!-- note -->\ncargo test"),
        ] {
            if !portable_isolation_rule_holds(&good, prefix) {
                failures.push(format!("unrelated prose hid a portable rule: {good}"));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n\n"));
    }
}

// #994: a harmless fenced example or comment elsewhere in the section must
// not hide a rule that is itself in the clear.
#[test]
fn checkout_isolation_ignores_unrelated_fenced_examples() {
    for prefix in ["2. **Scoped local checks:** ", ""] {
        let visible = format!("{prefix}{ISOLATION_RULE}");
        for example in [
            format!("An example command:\n\n```sh\ncargo test --workspace\n```\n\n{visible}"),
            format!("A note:\n\n<!-- TODO: tidy this -->\n\n{visible}"),
            format!("An example:\n\n~~~text\nnot a rule\n~~~\n\n{visible}"),
        ] {
            assert!(
                portable_isolation_rule_holds(&example, prefix),
                "an unrelated fenced example or comment hid a visible rule:\n{example}"
            );
        }
    }
}

// R1: fence boundaries must match CommonMark, not just a three-byte prefix.
#[test]
fn checkout_isolation_respects_fence_boundaries() {
    for (intro, prefix) in [
        (
            "2. **Scoped local checks:** ",
            "2. **Scoped local checks:**",
        ),
        ("", "Run nothing beside the full set"),
    ] {
        let rule = format!("{intro}{ISOLATION_RULE}");
        let mut failures = Vec::new();
        for (before, expected) in [
            ("````md\n```\n", false),
            ("~~~~md\n~~~\n", false),
            ("```md\n``` trailing info\n", false),
            ("~~~md\n~~~ trailing info\n", false),
            ("```md\n    ```\n", false),
            ("~~~md\n\t~~~\n", false),
            ("```md\n~~~\n", false),
            ("~~~info`allowed\n", false),
            ("   ````md\n   ````` \t\n", true),
            ("   ~~~~md\n   ~~~~~ \t\n", true),
            ("    ```md\n\n", true),
            ("\t~~~md\n\n", true),
            ("```inline code```\n", true),
            ("```language`invalid\n", true),
        ] {
            let section = format!("{before}{rule}");
            if portable_isolation_rule_holds(&section, prefix) != expected {
                failures.push(format!("expected {expected}: {section}"));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n\n"));
    }
}

// R2: a line may open and close several comments, with literal code between.
#[test]
fn checkout_isolation_respects_comment_spans() {
    for (intro, prefix) in [
        (
            "2. **Scoped local checks:** ",
            "2. **Scoped local checks:**",
        ),
        ("", "Run nothing beside the full set"),
    ] {
        let rule = format!("{intro}{ISOLATION_RULE}");
        let mut failures = Vec::new();
        for (section, expected) in [
            (format!("A note <!--\n{rule}\n-->"), false),
            (format!("<!-- note --> <!--\n{rule}\n-->"), false),
            (format!("<!-- note\n--> <!--\n{rule}\n-->"), false),
            (format!("{intro}<!-- {ISOLATION_RULE} -->"), false),
            (
                rule.replace("Run nothing", "Run <!-- note -->nothing"),
                false,
            ),
            (format!("<!-- note -->\n{rule}"), true),
            (format!("A note <!-- closed -->\n{rule}"), true),
            (format!("<!-- note\n--> <!-- closed -->\n{rule}"), true),
            (format!("{rule} <!-- cargo test -->"), true),
            (format!("<!-- closed -->{rule}"), true),
            (format!("<!-- note\n-->{rule}"), true),
            (format!("<!-->{rule}"), true),
            (format!("<!--->{rule}"), true),
            (format!("{rule} <!-- open"), true),
            (format!("`<!--`\n{rule}"), true),
            (format!("``a ` <!-- literal``\n{rule}"), true),
            (format!("A note ``unmatched <!--\n{rule}\n-->"), false),
            // A comment block interrupts a paragraph before inline matching.
            (format!("note `unfinished\n<!--\n{rule}\n-->"), false),
            (format!("note `x\n<!--\ny`\n\n{rule}"), false),
            // A heading also ends the paragraph, even if a later run matches.
            (
                format!("note ``unfinished\n# Heading\nliteral <!-- ``\n{rule}\n-->"),
                false,
            ),
            (
                format!("note ``unfinished\n   ###### Heading\nliteral <!-- ``\n{rule}\n-->"),
                false,
            ),
            (
                format!("# Heading ``unfinished\ntext <!-- ``\n{rule}\n-->"),
                false,
            ),
            (
                format!("note ``unfinished\n===\ntext <!-- ``\n{rule}\n-->"),
                false,
            ),
            // Literal markers can still occur inside a code span that stays
            // within one paragraph; these lines do not start another block.
            (format!("note `x\nliteral <!--\ny`\n\n{rule}"), true),
            (format!("note ``x\n#not-heading <!--\ny``\n\n{rule}"), true),
            (
                format!("note ``x\n####### not-heading <!--\ny``\n\n{rule}"),
                true,
            ),
            (format!("A note\n    <!--\n{rule}\n-->"), false),
            (format!("\\<!-- literal\n{rule}"), true),
            (format!("    <!-- literal\n\n{rule}"), true),
            (format!("\t<!-- literal\n\n{rule}"), true),
            (format!("```md\n<!-- literal\n```\n{rule}"), true),
            (format!("~~~md\n<!-- literal\n~~~\n{rule}"), true),
            (format!("<!-- note\n```\n-->\n{rule}"), true),
            (format!("<!-- note `\n--> <!--\n{rule}\n-->"), false),
        ] {
            if portable_isolation_rule_holds(&section, prefix) != expected {
                failures.push(format!("expected {expected}: {section}"));
            }
        }
        // Other block starts likewise stop paragraph-spanning lookahead.
        for boundary in [
            "---",
            "***",
            "> quote",
            "- item",
            "1. item",
            "<div>",
            "<?pi?>",
            "<!DOCTYPE html>",
            "<![CDATA[x]]>",
            "<pre>",
        ] {
            let section = format!("note ``unfinished\n{boundary}\ntext <!-- ``\n{rule}\n-->");
            if portable_isolation_rule_holds(&section, prefix) {
                failures.push(format!("a block boundary hid a comment: {section}"));
            }
        }
        // R2 +1 diagnosis: containers are hard source-format boundaries,
        // both for the opener's line and for later multiline lookahead.
        for marker in [
            "> ", "> > ", "> - ", "- > ", "- ", "+ ", "* ", "1. ", "2. ", "1) ", "2) ", "   > ",
            "  - ",
        ] {
            for hidden in [
                format!("{marker}# Heading ``unfinished\ntext <!-- ``\n{rule}\n-->"),
                format!("note ``unfinished\n{marker}literal <!-- ``\n{rule}\n-->"),
            ] {
                if portable_isolation_rule_holds(&hidden, prefix) {
                    failures.push(format!("a container boundary hid a comment: {hidden}"));
                }
            }
            let visible = format!("{marker}# Heading ``unfinished\ntext ``\n\n{rule}");
            if !portable_isolation_rule_holds(&visible, prefix) {
                failures.push(format!("a container example hid a visible rule: {visible}"));
            }
        }
        for marker in ["> ", "> - ", "- ", "1. ", "2) ", "    "] {
            let wrapped = format!("{marker}{rule}");
            if portable_isolation_rule_holds(&wrapped, prefix) {
                failures.push(format!("accepted a wrapped operative rule: {wrapped}"));
            }
        }
        for visible in [
            rule.clone(),
            format!("> text `<!--`\n\n{rule}"),
            format!("- item\n\n{rule}"),
            format!("note `x\nliteral <!--\ny`\n\n{rule}"),
        ] {
            if !portable_isolation_rule_holds(&visible, prefix) {
                failures.push(format!(
                    "an unrelated example hid a visible rule: {visible}"
                ));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n\n"));
    }
}

#[test]
fn setup_checkout_isolation_slot_is_optional() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/setup/templates/fleet.md"))
        .expect("fleet template");
    let section = text
        .split_once("## Test commands\n")
        .expect("Test commands section")
        .1
        .split("\n## ")
        .next()
        .expect("section body");
    assert!(
        visible_lines(section)
            .into_iter()
            .flatten()
            .any(|line| { line.starts_with("<isolation rule") && line.contains("optional") }),
        "Test commands needs an optional project-specific isolation rule slot"
    );
}

/// The skills: the eight fleet skills of spec ClosedWiz#95, then the five
/// new skills of spec ClosedWiz#205.
const SKILLS: [&str; 21] = [
    "grill",
    "plan-graph",
    "launch-fleet",
    "build-ticket",
    "review-ticket",
    "handoff",
    "setup",
    "triage",
    "wayfind",
    "where-are-we",
    "image",
    "research",
    "overnight",
    "huntr",
    "hill-climb",
    "diagnose",
    "ask-wiz",
    "onboard",
    "feedback-triage",
    "feedback",
    "install",
];

/// The skills not adapted from Matt Pocock's (spec ClosedWiz#205), each with
/// the source line its `SKILL.md` carries, exactly and on a line of its own,
/// stub or written, in place of his notice, which it must never carry.
/// Every other skill adapts his.
const NOT_MATTS: [(&str, &str); 9] = [
    (
        "hill-climb",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "huntr",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "where-are-we",
        "**Source:** dot-context's written plan. Not adapted from Matt Pocock's skills.",
    ),
    (
        "image",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "overnight",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "onboard",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "feedback-triage",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "feedback",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
    (
        "install",
        "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.",
    ),
];

/// The source line a skill not adapted from Matt Pocock's carries, if `name`
/// is one.
fn source_line(name: &str) -> Option<&'static str> {
    NOT_MATTS
        .iter()
        .find(|(skill, _)| *skill == name)
        .map(|&(_, line)| line)
}

/// Where agents look for skills inside a repository.
const LINK_DIRS: [&str; 2] = [".claude/skills", ".agents/skills"];

/// The only frontmatter keys a skill may have.
const FRONTMATTER_KEYS: [&str; 2] = ["name", "description"];

/// The longest description the Agent Skills format allows.
const DESCRIPTION_MAX_CHARS: usize = 1024;

/// The only keys under `interface:` in `agents/openai.yaml`.
const OPENAI_KEYS: [&str; 2] = ["display_name", "short_description"];

/// The only keys in `plugin.json`: metadata and `skills`. No `version`, so
/// installs follow commits; nothing that ships hooks, commands or servers.
const PLUGIN_KEYS: [&str; 8] = [
    "name",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "skills",
];

/// The only keys in `marketplace.json`, and in its one plugin entry.
const MARKETPLACE_KEYS: [&str; 4] = ["name", "owner", "description", "plugins"];
const MARKETPLACE_ENTRY_KEYS: [&str; 5] = ["name", "source", "description", "category", "keywords"];

/// The whole body of a skill that is not written yet.
const STUB: &str = "**Not written yet.** This file only fixes the skill's name and path; \
its build ticket writes it. Stop here, and tell whoever invoked it that this skill \
is not ready.";

/// How a stub's body starts; a written skill drops it.
const STUB_MARK: &str = "**Not written yet.**";

/// Matt Pocock's copyright and MIT notice, line for line from `LICENSE` in
/// `github.com/mattpocock/skills` @ `a496f55`. Compared with whitespace
/// collapsed, so line breaks don't matter.
const MATT_NOTICE: [&str; 16] = [
    "Copyright (c) 2026 Matt Pocock",
    "Permission is hereby granted, free of charge, to any person obtaining a copy",
    "of this software and associated documentation files (the \"Software\"), to deal",
    "in the Software without restriction, including without limitation the rights",
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell",
    "copies of the Software, and to permit persons to whom the Software is",
    "furnished to do so, subject to the following conditions:",
    "The above copyright notice and this permission notice shall be included in all",
    "copies or substantial portions of the Software.",
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR",
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,",
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE",
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER",
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,",
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE",
    "SOFTWARE.",
];

/// Every rule the repository at `root` breaks, one line each.
fn problems(root: &Path) -> Vec<String> {
    let mut out = Vec::new();
    check_folder(root, &mut out);
    for name in SKILLS {
        check_skill(root, name, &mut out);
    }
    check_plugin(root, &mut out);
    check_marketplace(root, &mut out);
    check_links(root, &mut out);
    check_markdown(root, &mut out);
    check_plan_graph(root, &mut out);
    out
}

// ---- 1. The list, exactly ----

fn check_folder(root: &Path, out: &mut Vec<String>) {
    let Ok(entries) = fs::read_dir(root.join("skills")) else {
        out.push("skills/ is missing".into());
        return;
    };
    let mut found = BTreeSet::new();
    for entry in entries {
        let entry = entry.expect("entry");
        let name = entry.file_name().to_string_lossy().into_owned();
        let kind = entry.file_type().expect("file type");
        let readme = name == "README.md" && kind.is_file();
        if readme || (kind.is_dir() && SKILLS.contains(&name.as_str())) {
            found.insert(name);
        } else {
            out.push(format!(
                "skills/{name}: only README.md and the listed skill folders belong here"
            ));
        }
    }
    for name in ["README.md"].into_iter().chain(SKILLS) {
        if !found.contains(name) {
            out.push(format!("skills/{name} is missing"));
        }
    }
}

// ---- 2 to 4. Each skill ----

fn check_skill(root: &Path, name: &str, out: &mut Vec<String>) {
    let dir = root.join("skills").join(name);
    let at = format!("skills/{name}/SKILL.md");
    let Ok(text) = fs::read_to_string(dir.join("SKILL.md")) else {
        out.push(format!("{at} is missing"));
        return;
    };
    let Some((front, body)) = split_frontmatter(&text) else {
        out.push(format!(
            "{at}: it must open with a `---` line, then the frontmatter, closed by a `---` line"
        ));
        return;
    };
    check_frontmatter(&at, name, &front, out);

    let openai = dir.join("agents/openai.yaml");
    let openai_at = format!("skills/{name}/agents/openai.yaml");
    let has_openai = match fs::read_to_string(&openai) {
        Ok(yaml) => {
            check_openai_yaml(&openai_at, name, &yaml, out);
            true
        }
        Err(_) => false,
    };

    // A skill not adapted from Matt Pocock's, stub or written: its source
    // line, exactly and on a line of its own, and never his notice.
    let source = source_line(name);
    let mut rest = body.clone();
    if let Some(line) = source {
        if !body.lines().any(|l| l.trim() == line) {
            out.push(format!(
                "{at}: carries its source line exactly, on a line of its own: `{line}` \
                 (it is not adapted from Matt Pocock's skills; see skills/README.md)"
            ));
        }
        if collapse(&body).contains(&collapse(MATT_NOTICE[0])) {
            out.push(format!(
                "{at}: must not carry Matt Pocock's copyright or notice: it is not adapted from \
                 his skills (see skills/README.md)"
            ));
        }
        rest = body
            .lines()
            .filter(|l| l.trim() != line)
            .collect::<Vec<_>>()
            .join("\n");
    }

    if rest.trim() == STUB {
        return;
    }
    if body.contains(STUB_MARK) {
        out.push(format!(
            "{at}: a written skill drops the stub line `{STUB_MARK}`"
        ));
    }
    if source.is_none() && !collapse(&body).contains(&collapse(&MATT_NOTICE.join("\n"))) {
        out.push(format!(
            "{at}: a written skill carries Matt Pocock's copyright and MIT notice word for word \
             (it adapts his skills; see skills/README.md)"
        ));
    }
    if !has_openai {
        out.push(format!(
            "{openai_at} is missing: a written skill has one for Codex"
        ));
    }
}

/// The frontmatter lines and the body, or `None` when the file does not
/// open with a `---` line or never closes its frontmatter.
fn split_frontmatter(text: &str) -> Option<(Vec<&str>, String)> {
    let mut lines = text.split('\n');
    if lines.next()? != "---" {
        return None;
    }
    let mut front = Vec::new();
    for line in lines.by_ref() {
        if line == "---" {
            return Some((front, lines.collect::<Vec<_>>().join("\n")));
        }
        front.push(line);
    }
    None
}

fn check_frontmatter(at: &str, name: &str, front: &[&str], out: &mut Vec<String>) {
    let mut values = BTreeMap::new();
    let mut invocation_flags = 0;
    for line in front {
        let Some((key, rest)) = line.split_once(':').filter(|(k, _)| is_key(k)) else {
            out.push(format!(
                "{at}: frontmatter line `{line}` is not a one-line `key: value`"
            ));
            continue;
        };
        if name == "ask-wiz" && key == "disable-model-invocation" {
            invocation_flags += 1;
            if rest != " true" || invocation_flags != 1 {
                out.push(format!(
                    "{at}: ask-wiz requires one `disable-model-invocation: true`"
                ));
            }
            continue;
        }
        if !FRONTMATTER_KEYS.contains(&key) {
            out.push(format!(
                "{at}: frontmatter key `{key}` is not allowed: only `name` and `description`, \
                 so no harness can make the skill user-only (`disable-model-invocation`)"
            ));
            continue;
        }
        match scalar(rest) {
            Ok(value) => {
                if values.insert(key, value).is_some() {
                    out.push(format!("{at}: `{key}` appears twice"));
                }
            }
            Err(why) => out.push(format!("{at}: `{key}` {why}")),
        }
    }
    if name == "ask-wiz" && invocation_flags == 0 {
        out.push(format!(
            "{at}: ask-wiz requires `disable-model-invocation: true`"
        ));
    }
    match values.get("name") {
        None => out.push(format!("{at}: the frontmatter has no `name`")),
        Some(found) if found != name => out.push(format!(
            "{at}: `name` is `{found}`, not its folder's name `{name}`"
        )),
        Some(_) => {}
    }
    match values.get("description") {
        None => out.push(format!("{at}: the frontmatter has no `description`")),
        Some(text) if text.chars().count() > DESCRIPTION_MAX_CHARS => out.push(format!(
            "{at}: `description` is longer than {DESCRIPTION_MAX_CHARS} characters"
        )),
        Some(_) => {}
    }
}

fn is_key(key: &str) -> bool {
    key.starts_with(|c: char| c.is_ascii_lowercase())
        && key
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
}

/// A one-line YAML value, after its key's `:`: a plain scalar YAML reads as
/// the same text, or a quoted one. Anything else is refused, not guessed at.
fn scalar(rest: &str) -> Result<String, &'static str> {
    let raw = rest.trim();
    if raw.is_empty() {
        return Err("needs a value on the same line");
    }
    if !rest.starts_with(' ') {
        return Err("needs a space after its `:`");
    }
    let value = if let Some(inner) = raw.strip_prefix('"') {
        let inner = inner
            .strip_suffix('"')
            .ok_or("opens a double quote it does not close")?;
        let mut value = String::new();
        let mut chars = inner.chars();
        while let Some(c) = chars.next() {
            match c {
                '\\' => match chars.next() {
                    Some(e @ ('"' | '\\')) => value.push(e),
                    _ => return Err("uses an escape other than \\\" or \\\\"),
                },
                '"' => return Err("has an unescaped double quote inside"),
                c => value.push(c),
            }
        }
        value
    } else if let Some(inner) = raw.strip_prefix('\'') {
        let inner = inner
            .strip_suffix('\'')
            .ok_or("opens a single quote it does not close")?;
        if inner.replace("''", "").contains('\'') {
            return Err("has an unescaped single quote inside");
        }
        inner.replace("''", "'")
    } else {
        const INDICATORS: &[char] = &[
            '-', '?', ':', ',', '[', ']', '{', '}', '#', '&', '*', '!', '|', '>', '%', '@', '`',
        ];
        if raw.starts_with(INDICATORS) {
            return Err("starts with a YAML indicator: quote it");
        }
        if raw.contains(": ") || raw.contains(" #") || raw.ends_with(':') {
            return Err("has `: `, ` #` or a final `:`, which YAML misreads: quote it");
        }
        let lower = raw.to_ascii_lowercase();
        let special = ["true", "false", "null", "~", "yes", "no", "on", "off"];
        if special.contains(&lower.as_str()) || raw.parse::<f64>().is_ok() {
            return Err("reads as a YAML boolean, null or number: quote it");
        }
        raw.to_string()
    };
    if value.trim().is_empty() {
        return Err("is empty");
    }
    Ok(value)
}

fn check_openai_yaml(at: &str, name: &str, text: &str, out: &mut Vec<String>) {
    // Only this exact policy is allowed, only for the user-started router.
    // Parse the remaining interface with the existing strict allowlist.
    let text = if name == "ask-wiz" {
        match text
            .trim_end()
            .strip_suffix("policy:\n  allow_implicit_invocation: false")
        {
            Some(interface) => interface,
            None => {
                out.push(format!(
                    "{at}: ask-wiz requires exactly `policy.allow_implicit_invocation: false`"
                ));
                text
            }
        }
    } else {
        text
    };
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    let mut rest = lines.as_slice();
    match rest.split_first() {
        Some((&"interface:", tail)) => rest = tail,
        _ => out.push(format!("{at}: it must open with `interface:`")),
    }
    let mut seen = BTreeSet::new();
    for line in rest {
        let entry = line
            .strip_prefix("  ")
            .and_then(|l| l.split_once(':'))
            .filter(|(k, _)| OPENAI_KEYS.contains(k));
        match entry {
            Some((key, value)) => {
                if let Err(why) = scalar(value) {
                    out.push(format!("{at}: `{key}` {why}"));
                }
                if !seen.insert(key) {
                    out.push(format!("{at}: `{key}` appears twice"));
                }
            }
            None if line.contains("policy") || line.contains("allow_implicit_invocation") => out
                .push(format!(
                    "{at}: `{}` is not allowed: `policy` is Codex's switch that makes a skill \
                     user-only",
                    line.trim()
                )),
            None => out.push(format!(
                "{at}: `{}` is not allowed: only `interface.display_name` and \
                 `interface.short_description`",
                line.trim()
            )),
        }
    }
    for key in OPENAI_KEYS {
        if !seen.contains(key) {
            out.push(format!("{at}: `interface.{key}` is missing"));
        }
    }
}

/// Text with every run of whitespace collapsed to one space.
fn collapse(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

// ---- 6. Manifests ----

/// The JSON object at `rel`. A `Value`, so a missing key reads as null.
fn read_object(root: &Path, rel: &str, out: &mut Vec<String>) -> Option<Value> {
    let Ok(text) = fs::read_to_string(root.join(rel)) else {
        out.push(format!("{rel} is missing"));
        return None;
    };
    match serde_json::from_str(&text) {
        Ok(object @ Value::Object(_)) => Some(object),
        Ok(_) => {
            out.push(format!("{rel} must be a JSON object"));
            None
        }
        Err(e) => {
            out.push(format!("{rel} is not JSON: {e}"));
            None
        }
    }
}

fn only_keys(at: &str, object: &Value, allowed: &[&str], out: &mut Vec<String>) {
    for key in object.as_object().into_iter().flat_map(Map::keys) {
        if !allowed.contains(&key.as_str()) {
            out.push(format!(
                "{at}: `{key}` is not allowed (only {})",
                allowed.join(", ")
            ));
        }
    }
}

fn is_plugin_name(name: &str) -> bool {
    !name.is_empty()
        && !name.starts_with('-')
        && !name.ends_with('-')
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

const PLUGIN: &str = ".claude-plugin/plugin.json";
const MARKETPLACE: &str = ".claude-plugin/marketplace.json";

fn check_plugin(root: &Path, out: &mut Vec<String>) {
    let Some(plugin) = read_object(root, PLUGIN, out) else {
        return;
    };
    only_keys(PLUGIN, &plugin, &PLUGIN_KEYS, out);
    if !plugin["name"].as_str().is_some_and(is_plugin_name) {
        out.push(format!(
            "{PLUGIN}: `name` must be a lowercase-and-hyphens string"
        ));
    }
    if !plugin["description"]
        .as_str()
        .is_some_and(|d| !d.trim().is_empty())
    {
        out.push(format!(
            "{PLUGIN}: `description` must be a non-empty string"
        ));
    }
    let Some(entries) = plugin["skills"].as_array() else {
        out.push(format!(
            "{PLUGIN}: `skills` must be an array of skill folders"
        ));
        return;
    };
    let expected: Vec<String> = SKILLS.iter().map(|n| format!("./skills/{n}")).collect();
    let mut listed = BTreeSet::new();
    for entry in entries {
        let Some(entry) = entry.as_str().filter(|e| expected.iter().any(|x| x == e)) else {
            let shown = entry
                .as_str()
                .map_or_else(|| entry.to_string(), str::to_owned);
            out.push(format!(
                "{PLUGIN}: `{shown}` is not `./skills/<name>` for one of the listed skills"
            ));
            continue;
        };
        if !listed.insert(entry) {
            out.push(format!("{PLUGIN}: `{entry}` is listed twice"));
        }
        if !root.join(entry).join("SKILL.md").is_file() {
            out.push(format!(
                "{PLUGIN}: `{entry}` does not resolve to a folder with a SKILL.md"
            ));
        }
    }
    for entry in &expected {
        if !listed.contains(entry.as_str()) {
            out.push(format!("{PLUGIN}: it does not list `{entry}`"));
        }
    }
}

fn check_marketplace(root: &Path, out: &mut Vec<String>) {
    let Some(market) = read_object(root, MARKETPLACE, out) else {
        return;
    };
    only_keys(MARKETPLACE, &market, &MARKETPLACE_KEYS, out);
    if !market["name"].as_str().is_some_and(is_plugin_name) {
        out.push(format!(
            "{MARKETPLACE}: `name` must be a lowercase-and-hyphens string"
        ));
    }
    if !market["owner"]["name"]
        .as_str()
        .is_some_and(|n| !n.trim().is_empty())
    {
        out.push(format!(
            "{MARKETPLACE}: `owner.name` must be a non-empty string"
        ));
    }
    let entry = match market["plugins"].as_array().map(Vec::as_slice) {
        Some([entry @ Value::Object(_)]) => entry,
        _ => {
            out.push(format!(
                "{MARKETPLACE}: `plugins` must hold exactly one plugin entry, this repository's"
            ));
            return;
        }
    };
    let at = format!("{MARKETPLACE}: `plugins[0]`");
    only_keys(&at, entry, &MARKETPLACE_ENTRY_KEYS, out);
    let plugin_name = fs::read_to_string(root.join(PLUGIN))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|p| p["name"].as_str().map(str::to_owned));
    if entry["name"].as_str() != plugin_name.as_deref() {
        out.push(format!("{at}: `name` must be {PLUGIN}'s `name`"));
    }
    if entry["source"].as_str() != Some("./") || !root.join(PLUGIN).is_file() {
        out.push(format!(
            "{at}: `source` must be `./`, this repository, which holds {PLUGIN}"
        ));
    }
}

// ---- 5. Links ----

fn check_links(root: &Path, out: &mut Vec<String>) {
    for dir in LINK_DIRS {
        for name in SKILLS {
            let link = root.join(dir).join(name);
            let at = format!("{dir}/{name}");
            let expected = Path::new("../../skills").join(name);
            match fs::read_link(&link) {
                Ok(target) if target == expected => {}
                Ok(target) => out.push(format!(
                    "{at} points at `{}`, not `{}`",
                    target.display(),
                    expected.display()
                )),
                Err(_) => {
                    out.push(format!("{at} must be a link to `{}`", expected.display()));
                    continue;
                }
            }
            let real = fs::canonicalize(root.join("skills").join(name)).ok();
            if real.is_none() || fs::canonicalize(&link).ok() != real {
                out.push(format!(
                    "{at} does not resolve to the real folder skills/{name}"
                ));
            }
        }
        let Ok(entries) = fs::read_dir(root.join(dir)) else {
            continue;
        };
        for entry in entries {
            let entry = entry.expect("entry");
            let name = entry.file_name().to_string_lossy().into_owned();
            if SKILLS.contains(&name.as_str()) {
                continue;
            }
            if entry.file_type().expect("file type").is_symlink() {
                out.push(format!(
                    "{dir}/{name} is a link, but not to one of the listed skills"
                ));
            } else if dir == ".agents/skills" {
                out.push(format!(
                    "{dir}/{name}: only the links to the listed skills belong here"
                ));
            }
        }
    }
}

/// Every path under `dir`, with its own type: links are listed, never
/// followed.
fn tree(dir: &Path) -> Vec<(PathBuf, FileType)> {
    let mut out = Vec::new();
    let Ok(entries) = fs::read_dir(dir) else {
        return out;
    };
    for entry in entries {
        let entry = entry.expect("entry");
        let kind = entry.file_type().expect("file type");
        if kind.is_dir() {
            out.extend(tree(&entry.path()));
        }
        out.push((entry.path(), kind));
    }
    out
}

fn check_markdown(root: &Path, out: &mut Vec<String>) {
    let Ok(real_root) = fs::canonicalize(root) else {
        return;
    };
    for (path, kind) in tree(&root.join("skills")) {
        let at = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .display()
            .to_string();
        if kind.is_symlink() {
            out.push(format!(
                "{at} is a link: none belong under skills/ (Codex drops them when it installs a plugin)"
            ));
            continue;
        }
        if !kind.is_file() || path.extension().is_none_or(|e| e != "md") {
            continue;
        }
        let text = fs::read_to_string(&path).expect("markdown");
        for target in markdown_targets(&text) {
            if target.contains("://") || target.starts_with("mailto:") {
                continue;
            }
            let file = target.split(['#', '?']).next().unwrap_or_default();
            if file.is_empty() {
                continue;
            }
            match fs::canonicalize(path.parent().expect("parent").join(file)) {
                Ok(real) if real.starts_with(&real_root) => {}
                Ok(_) => out.push(format!("{at}: link `{target}` leaves the repository")),
                Err(_) => out.push(format!("{at}: link `{target}` does not resolve")),
            }
        }
    }
}

/// The targets of the Markdown links and link definitions in `text`, outside
/// code blocks and code spans.
fn markdown_targets(text: &str) -> Vec<String> {
    let mut targets = Vec::new();
    let mut fence: Option<&str> = None;
    for line in text.lines() {
        let trimmed = line.trim_start();
        if let Some(open) = fence {
            if trimmed.starts_with(open) {
                fence = None;
            }
            continue;
        }
        if let Some(open) = ["```", "~~~"].into_iter().find(|f| trimmed.starts_with(f)) {
            fence = Some(open);
            continue;
        }
        let line: String = line.split('`').step_by(2).collect();
        if let Some((_, def)) = line
            .trim_start()
            .strip_prefix('[')
            .and_then(|l| l.split_once("]: "))
        {
            targets.push(first_token(def));
            continue;
        }
        let mut rest = line.as_str();
        while let Some(i) = rest.find("](") {
            rest = &rest[i + 2..];
            let end = rest.find(')').unwrap_or(rest.len());
            targets.push(first_token(&rest[..end]));
            rest = &rest[end..];
        }
    }
    targets
}

fn first_token(text: &str) -> String {
    let token = text.split_whitespace().next().unwrap_or_default();
    token
        .trim_start_matches('<')
        .trim_end_matches('>')
        .to_string()
}

// #198: bind the check to the operative Contracts rule and the ticket
// template, so a citation elsewhere cannot stand in for either.
const RELIES_RULE: &str = "Every Relies on declaration is exactly one `**Relies on:**` line: comma-separated full repository-relative contract-file paths in backticks, or exactly `nothing`; no prose, partial names, folders or patterns.";
const RELIES_TEMPLATE: &str = "**Relies on:** <comma-separated full repository-relative contract-file paths in backticks, or exactly nothing>";

fn check_plan_graph(root: &Path, out: &mut Vec<String>) {
    let at = "skills/plan-graph/SKILL.md";
    let Ok(text) = fs::read_to_string(root.join(at)) else {
        return; // check_skill reports a missing file.
    };
    if text.contains(STUB_MARK) {
        return;
    }
    let section = text
        .split_once("## 4. Propose the tickets\n")
        .and_then(|(_, tail)| tail.split_once("\nThen show it:"))
        .map(|(body, _)| body);
    let rule_holds = section.is_some_and(|body| {
        let rules: Vec<_> = body
            .lines()
            .filter(|line| line.starts_with("- **Contracts, not code.** "))
            .collect();
        // This operative list has no blocks or HTML comments: required
        // wording hidden in either must not satisfy the visible rule.
        !["<!--", "-->", "```", "~~~"]
            .iter()
            .any(|marker| body.contains(marker))
            && rules.len() == 1
            && rules[0].contains(RELIES_RULE)
    });
    if !rule_holds {
        out.push(format!(
            "{at}: the operative Contracts rule must require checked Relies on file paths"
        ));
    }
    let template = text
        .split_once("**A ticket.**")
        .and_then(|(_, tail)| tail.split_once("```md\n"))
        .and_then(|(_, tail)| tail.split_once("\n```"))
        .map(|(body, _)| body);
    if template.is_none_or(|body| {
        body.lines().filter(|line| *line == RELIES_TEMPLATE).count() != 1
            || body
                .lines()
                .filter(|line| {
                    line.trim_start()
                        .trim_start_matches('*')
                        .starts_with("Relies on:")
                })
                .count()
                != 1
            || body.lines().any(|line| line == "## Relies on")
    }) {
        out.push(format!(
            "{at}: the ticket template needs one inline Relies on file-path declaration"
        ));
    }
}

// ---- Tests ----

#[test]
fn the_skills_folder_passes_the_static_check() {
    let found = problems(Path::new(ROOT));
    assert!(
        found.is_empty(),
        "the skills folder breaks the static check:\n{}",
        found.join("\n")
    );
}

#[test]
fn diagnose_bisect_wrapper_skips_inconclusive_input() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/diagnose/SKILL.md"))
        .expect("diagnose skill");
    let paragraph = text
        .split("\n\n")
        .find(|paragraph| paragraph.starts_with("The template prints "))
        .expect("the human-assisted template's exit-status explanation")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    assert!(
        paragraph.contains(
            "exits 2 for inconclusive input. In a `git bisect run` wrapper, map exit 2 to 125 \
             (skip), so an inconclusive answer never marks a commit bad."
        ),
        "the template's exit-status explanation must map inconclusive exit 2 to bisect skip 125"
    );
}

#[test]
fn research_raw_output_instruction_survives_filling_measurements() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/research/SKILL.md"))
        .expect("research skill");
    let brief = text
        .split_once("```text\n")
        .expect("worker brief opens")
        .1
        .split_once("\n```")
        .expect("worker brief closes")
        .0;
    let plan = brief
        .split_once("Measurements, if about our code: <")
        .expect("measurement placeholder opens")
        .1
        .split_once('>')
        .expect("measurement placeholder closes")
        .0;
    let filled = brief.replacen(&format!("<{plan}>"), "Synthetic measurement plan", 1);
    let instruction = "Paste each run's raw output in full into your notes: \
        your sandbox is archived, and no file there reaches the asker.";
    assert_eq!(
        filled.lines().filter(|line| *line == instruction).count(),
        1,
        "the filled worker brief must retain its fixed raw-output instruction"
    );
}

#[test]
fn huntr_checklist_separates_stale_docs_from_product_text() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("huntr settings");
    let section = text
        .split_once("### Contracts and docs\n")
        .expect("Contracts and docs checklist")
        .1
        .split("\n### ")
        .next()
        .expect("checklist body");
    let items: Vec<_> = section
        .lines()
        .filter(|line| line.starts_with("- **Tier "))
        .collect();
    for (question, tier) in [
        ("Do docs disagree with actual commands?", "1"),
        (
            "Does help text or error text in code disagree with actual commands?",
            "2",
        ),
    ] {
        let matching: Vec<_> = items
            .iter()
            .filter(|line| line.contains(question))
            .collect();
        assert_eq!(matching.len(), 1, "one operative item: {question}");
        let item = matching[0];
        assert!(item.starts_with(&format!("- **Tier {tier}**:")));
        assert!(item.contains("**Proof:** Run the documented command against safe fixtures and assert its literal output against the documentation."));
        if tier == "2" {
            assert!(item.contains("Every existing test passes unchanged."));
        }
    }
    assert!(!items.iter().any(|line| {
        line.starts_with("- **Tier 1**:")
            && (line.contains("help text") || line.contains("error text"))
    }));
}

// #1689 step 4: hunters flag junk tests under TA2's rules. A lost line here would let a
// hunt propose deleting a protected proof or contract test, or cutting without the guards.
#[test]
fn huntr_test_audit_keeps_protected_tests_and_the_coverage_and_kill_guard() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("huntr settings");
    let tests = text
        .split_once("\n### Tests\n")
        .expect("Tests checklist")
        .1
        .split("\n### ")
        .next()
        .expect("Tests checklist body");
    let (general, audit) = tests
        .split_once("\n#### Test audit (`test-audit`)\n")
        .expect("test-audit group inside the Tests category");
    // R2: the rules govern every removal or merge in Tests, not only the subsection.
    let governs =
        "Every test removal or consolidation in this category follows the test-audit rules below";
    assert_eq!(
        general
            .lines()
            .filter(|line| line.contains(governs))
            .count(),
        1,
        "Tests category preamble names the test-audit rules"
    );
    let removals: Vec<_> = general
        .lines()
        .filter(|line| line.starts_with("- **Tier ") && line.contains("duplicate tests"))
        .collect();
    assert_eq!(removals.len(), 1, "the general duplicate-removal item");
    assert!(
        removals[0].contains("follows the test-audit rules below"),
        "{}",
        removals[0]
    );
    let never = audit
        .lines()
        .find(|line| line.starts_with("- **Never deleted, only consolidated:**"))
        .expect("protected-test rule");
    for protected in [
        "P, M, N, AP, A, V",
        "the checks",
        "API, schema, allowlist, security, release, storage, ordering",
        "the pending list's tests",
        "A baseline failure is a bug to report, never a test to delete.",
    ] {
        assert!(never.contains(protected), "protected: {protected}");
    }
    let cuts: Vec<_> = audit
        .lines()
        .filter(|line| line.starts_with("- **Tier 1**:"))
        .collect();
    assert_eq!(
        cuts.len(),
        2,
        "two tier-1 test-audit items: remove and merge"
    );
    for item in cuts {
        assert!(item.contains("within 2 percentage points"), "{item}");
        assert!(
            item.contains("every mutant a removed test kills is also killed by a retained test"),
            "{item}"
        );
    }
}

#[test]
fn overnight_preserves_huntr_risk_tiers_and_open_cap() {
    let settings =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("huntr settings");
    let policy_text = settings
        .split_once("```json\n")
        .expect("huntr policy JSON opens")
        .1
        .split_once("\n```")
        .expect("huntr policy JSON closes")
        .0;
    let policy: Value = serde_json::from_str(policy_text).expect("huntr policy JSON");
    assert_eq!(
        policy["open_cap"],
        json!(50),
        "huntr policy open cap must be 50"
    );
    let cap_rule = "the open-ticket cap in `docs/agents/huntr.md`";
    let text = fs::read_to_string(Path::new(ROOT).join("skills/overnight/SKILL.md"))
        .expect("overnight skill");
    let authority = text
        .lines()
        .find(|line| line.starts_with("**huntr owns all hunting and approval:**"))
        .expect("operative huntr authority paragraph");
    for rule in ["The approved risk tiers (up to `max_tier`)", cap_rule] {
        assert!(authority.contains(rule), "overnight must preserve {rule}");
    }
    let huntr =
        fs::read_to_string(Path::new(ROOT).join("skills/huntr/SKILL.md")).expect("huntr skill");
    let night = huntr
        .lines()
        .find(|line| line.starts_with("**Night setting:**"))
        .expect("operative huntr night paragraph");
    assert!(night.contains(cap_rule), "huntr must preserve {cap_rule}");
}

// ClosedWiz#684: a kind approval is durable. The record is a comment on the
// switch issue (#394) whose first line starts `huntr kind approved:` and names
// the kind and its tier; step 1 reads it on every hunt, and the summary-line-5
// trace row names it. Without this, each fresh hunt thread has no record of an
// approved kind to act on.
#[test]
fn huntr_kind_approval_has_a_durable_record() {
    let record_marker = "`huntr kind approved:`";
    let skill =
        fs::read_to_string(Path::new(ROOT).join("skills/huntr/SKILL.md")).expect("huntr skill");

    let switch_step = skill
        .split_once("Read the switch issue in the settings")
        .expect("step 1 switch read")
        .1
        .split_once("\n\n")
        .expect("step 1 switch paragraph")
        .0;
    assert!(
        switch_step.contains(record_marker),
        "step 1 must read the kind-approval record {record_marker}"
    );

    let kind_rule = skill
        .split_once("A kind that fits no tier cleanly is a **kind proposal**")
        .expect("kind proposal rule")
        .1
        .split_once("\n\n")
        .expect("kind proposal paragraph")
        .0;
    assert!(
        kind_rule.contains(record_marker),
        "the kind-proposal rule must name the durable record {record_marker}"
    );

    let settings =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("huntr settings");

    let proposal = settings
        .split_once("A kind fitting no tier cleanly becomes a **kind proposal**")
        .expect("settings kind proposal rule")
        .1
        .split_once("\n\n")
        .expect("settings kind proposal paragraph")
        .0;
    assert!(
        proposal.contains(record_marker),
        "the settings kind-proposal rule must name the durable record {record_marker}"
    );

    let trace = settings
        .split_once("| 5 / HW6 |")
        .expect("summary line 5 trace row")
        .1
        .split_once('\n')
        .expect("trace row end")
        .0;
    assert!(
        trace.contains(record_marker),
        "the summary-line-5 trace row must name the durable record {record_marker}"
    );
}

// ClosedWiz#684/R1: the kind-approval record is only for kinds needing the HW6
// proposal process (work fitting no configured tier cleanly). Work that fits a
// standing tier is approved by the tier itself and needs no kind comment. The
// step-1 prose must keep both halves: read the record for proposal kinds, and
// preserve standing tier approval for everything else.
#[test]
fn huntr_kind_record_preserves_standing_tier_approval() {
    let skill =
        fs::read_to_string(Path::new(ROOT).join("skills/huntr/SKILL.md")).expect("huntr skill");
    let switch_step = skill
        .split_once("Read the switch issue in the settings")
        .expect("step 1 switch read")
        .1
        .split_once("\n\n")
        .expect("step 1 switch paragraph")
        .0;

    assert!(
        switch_step.contains("fits a configured tier"),
        "step 1 must keep standing tier approval for work that fits a configured tier"
    );
    assert!(
        switch_step.contains("needs an approved kind"),
        "step 1 must scope the missing-record refusal to kinds needing the HW6 proposal process"
    );
    assert!(
        !switch_step.contains("A kind is approved only when such a comment names it"),
        "step 1 must not make a kind comment mandatory for every kind"
    );
}

// ClosedWiz#1685: huntr hunts reliably overnight. One controller holds a
// lease on the switch issue, never found by listing threads; each hunter
// fetches the pinned commit itself with its own sandbox's GitHub login, or
// reports BLOCKED in one line; the controller ends its turn while hunters run,
// files what is proven first on every wake, and posts a result at least every
// 30 minutes and at the end. The dry run proves the scripts on a fake gh.
#[test]
fn huntr_controller_dry_run_passes() {
    let output = std::process::Command::new("node")
        .arg("--test")
        .arg(Path::new(ROOT).join("skills/huntr/scripts/controller.test.mjs"))
        .env_remove("GH_TOKEN")
        .env_remove("GITHUB_TOKEN")
        .output()
        .expect("node runs the huntr dry run");
    assert!(
        output.status.success(),
        "huntr dry run failed:\n{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

// ClosedWiz#2557: feedback-triage's queue, approval binding, refusal,
// repeated yes, sent, uncertain, reconcile-before-retry and untrusted-input
// proofs, on a recording GitHub with synthetic issues only.
#[test]
fn feedback_triage_offline_proofs_pass() {
    let output = std::process::Command::new("python3")
        .args(["-I", "-B", "-m", "unittest", "discover", "-s"])
        .arg(Path::new(ROOT).join("skills/feedback-triage/tests"))
        .env_remove("GH_TOKEN")
        .env_remove("GITHUB_TOKEN")
        .output()
        .expect("python3 runs the feedback-triage proofs");
    assert!(
        output.status.success(),
        "feedback-triage proofs failed:\n{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn huntr_holds_one_controller_by_lease_and_waits_by_waking() {
    let skill =
        fs::read_to_string(Path::new(ROOT).join("skills/huntr/SKILL.md")).expect("huntr skill");
    let settings =
        fs::read_to_string(Path::new(ROOT).join("docs/agents/huntr.md")).expect("huntr settings");
    let step = |heading: &str| {
        skill
            .split_once(heading)
            .unwrap_or_else(|| panic!("{heading}"))
            .1
            .split("\n## ")
            .next()
            .expect("step body")
            .to_owned()
    };
    assert!(
        !skill.contains("thread list"),
        "huntr must never find its controller by listing threads"
    );
    let check = step("## 1. Check whether to hunt\n");
    for rule in [
        "scripts/lease.mjs claim",
        "never by listing threads",
        "scripts/lease.mjs id",
    ] {
        assert!(check.contains(rule), "step 1 must name {rule}");
    }
    assert!(
        !skill.contains("room-cli thread tell"),
        "#394 is the only report channel"
    );
    for rule in [
        "self-generated run ID",
        "Before dispatch, perform any one-time reconciliation the project's huntr settings name",
        "if it is due and cannot be verified, record the gap and stop dispatch",
    ] {
        assert!(check.contains(rule), "start must name {rule}");
    }
    assert!(
        !check.contains("h1"),
        "a reusable skill must not require ClosedWiz's h1 cleanup"
    );
    let reconciliation = settings
        .lines()
        .find(|line| line.starts_with("**First reconciliation (#1734):**"))
        .expect("project's operative one-time reconciliation rule");
    for rule in [
        "h1",
        "eight",
        "abandoned",
        "Once #394 holds a verified record marking these eight abandoned, later hunts skip this step.",
    ] {
        assert!(
            reconciliation.contains(rule),
            "one-time settings must name {rule}"
        );
    }
    let record = step("## 5. Record the result and finish this hunt\n");
    assert!(
        record.contains("only report channel"),
        "record delivery is through #394"
    );
    let dispatch = step("## 2. Read, then dispatch focused hunters\n");
    for rule in [
        "scripts/hunters.mjs brief",
        "scripts/hunters.mjs collect",
        "its own sandbox's GitHub login",
        "`huntr hunter: BLOCKED`",
    ] {
        assert!(dispatch.contains(rule), "step 2 must name {rule}");
    }
    let wake = step("## Waiting: wake, file, checkpoint\n");
    for rule in [
        "ends its turn",
        "files what is proven before anything else",
        "at least every 30 minutes",
        "scripts/lease.mjs renew",
        "scripts/lease.mjs release",
        "scripts/lease.mjs due",
        "every scheduled wake",
        "scripts/lease.mjs record",
    ] {
        assert!(wake.contains(rule), "the wake procedure must name {rule}");
    }
    let lease = settings
        .split_once("## Controller lease (#1685)\n")
        .expect("controller lease settings")
        .1
        .split("\n## ")
        .next()
        .expect("lease body");
    for rule in [
        "45 minutes",
        "`huntr lease: claim",
        "server time",
        "`due <run> scheduled|hunter`",
        "`record <run> <index-file>`",
        "uncommitted changes",
    ] {
        assert!(lease.contains(rule), "the lease settings must name {rule}");
    }
}

#[test]
fn overnight_reuses_huntr_thirty_minute_loop() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/overnight/SKILL.md"))
        .expect("overnight skill");
    let invocation = text
        .split_once("## 3. Invoke huntr with the night setting\n")
        .expect("huntr invocation section")
        .1
        .split("\n## ")
        .next()
        .expect("huntr invocation body");
    let controller = invocation
        .lines()
        .find(|line| line.starts_with("Resolve the sibling [huntr skill]"))
        .expect("operative controller paragraph");
    assert!(
        controller.contains("Use huntr's existing 30-minute loop and controller claims."),
        "overnight must reuse huntr's 30-minute loop"
    );
}

#[test]
fn overnight_day_review_preserves_redacted_technical_facts() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/overnight/SKILL.md"))
        .expect("overnight skill");
    let (_, review) = text
        .split_once("## 2. Review the day as huntr's input\n")
        .expect("day-review section");
    let review = review.split("\n## ").next().expect("day-review body");
    let privacy = review
        .lines()
        .find(|line| line.starts_with("Use only authorized access to session artifacts. "))
        .expect("operative day-review privacy paragraph");
    assert!(
        privacy.contains("Keep raw transcripts and credentials out of Git, issues, briefs and reports; preserve only redacted technical facts, source references and synthetic reproducers."),
        "day review must preserve only redacted technical facts, source references and synthetic reproducers"
    );
}

/// A good repository in a fresh folder for `case`: every skill's stub, the
/// README, both manifests and both sets of links. Synthetic text only.
fn fixture(case: &str) -> PathBuf {
    let root = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("skills-check")
        .join(case);
    let _ = fs::remove_dir_all(&root);
    for name in SKILLS {
        write(&root, &format!("skills/{name}/SKILL.md"), &stub(name));
        for dir in LINK_DIRS {
            crate::dirs::private_dir_all(root.join(dir)).expect("link dir");
            symlink(
                Path::new("../../skills").join(name),
                root.join(dir).join(name),
            )
            .expect("link");
        }
    }
    write(
        &root,
        "skills/README.md",
        "# Synthetic skills\n\nSee [grill](grill/SKILL.md) and `[code](not/a/link.md)`.\n",
    );
    let entries: Vec<String> = SKILLS.iter().map(|n| format!("./skills/{n}")).collect();
    write_json(
        &root,
        PLUGIN,
        &json!({"name": "synthetic-skills", "description": "Synthetic.", "skills": entries}),
    );
    write_json(
        &root,
        MARKETPLACE,
        &json!({
            "name": "synthetic",
            "owner": {"name": "Synthetic"},
            "plugins": [{"name": "synthetic-skills", "source": "./"}]
        }),
    );
    root
}

fn write(root: &Path, rel: &str, text: &str) {
    let path = root.join(rel);
    crate::dirs::private_dir_all(path.parent().expect("parent")).expect("dir");
    fs::write(path, text).expect("write");
}

fn write_json(root: &Path, rel: &str, value: &Value) {
    write(
        root,
        rel,
        &serde_json::to_string_pretty(value).expect("json"),
    );
}

/// A stub: the exact [`STUB`], and its source line if it is in [`NOT_MATTS`].
fn stub(name: &str) -> String {
    let source = source_line(name).map_or_else(String::new, |line| format!("\n{line}\n"));
    let invocation = if name == "ask-wiz" {
        "disable-model-invocation: true\n"
    } else {
        ""
    };
    format!(
        "---\nname: {name}\ndescription: Synthetic description of {name}.\n{invocation}---\n\n{STUB}\n{source}"
    )
}

fn written(name: &str, notice: &str) -> String {
    format!(
        "---\nname: {name}\ndescription: Synthetic description of {name}.\n---\n\n\
         # Synthetic\n\nSynthetic steps.\n\n## Licence\n\n{notice}\n"
    )
}

const OPENAI: &str =
    "interface:\n  display_name: \"Synthetic\"\n  short_description: \"Synthetic skill\"\n";

fn notice() -> String {
    MATT_NOTICE.join("\n")
}

fn assert_clean(root: &Path) {
    let found = problems(root);
    assert!(
        found.is_empty(),
        "expected no problems, got:\n{}",
        found.join("\n")
    );
}

/// The check reports a problem containing `expected` for `root`.
fn assert_catches(root: &Path, expected: &str) {
    let found = problems(root);
    assert!(
        found.iter().any(|p| p.contains(expected)),
        "expected a problem containing {expected:?}, got:\n{}",
        found.join("\n")
    );
}

#[test]
fn the_stubs_and_a_written_skill_pass() {
    let root = fixture("good");
    assert_clean(&root);
    write(&root, "skills/grill/SKILL.md", &written("grill", &notice()));
    write(&root, "skills/grill/agents/openai.yaml", OPENAI);
    assert_clean(&root);
    // Line breaks in the notice don't matter.
    write(
        &root,
        "skills/setup/SKILL.md",
        &written("setup", &collapse(&notice())),
    );
    write(&root, "skills/setup/agents/openai.yaml", OPENAI);
    assert_clean(&root);
    // Quoted values, as Matt's frontmatter uses them.
    write(
        &root,
        "skills/triage/SKILL.md",
        &format!("---\nname: \"triage\"\ndescription: 'Synthetic: it''s quoted.'\n---\n\n{STUB}\n"),
    );
    assert_clean(&root);
}

#[test]
fn a_missing_or_broken_frontmatter_fails() {
    let front = |lines: &str| format!("---\n{lines}\n---\n\n{STUB}\n");
    let long = "x".repeat(DESCRIPTION_MAX_CHARS + 1);
    let cases = [
        (
            "no-frontmatter",
            format!("# Synthetic\n\n{STUB}\n"),
            "must open with a `---` line",
        ),
        (
            "unclosed",
            "---\nname: grill\ndescription: Synthetic.\n".into(),
            "closed by a `---` line",
        ),
        (
            "no-description",
            front("name: grill"),
            "has no `description`",
        ),
        ("no-name", front("description: Synthetic."), "has no `name`"),
        (
            "wrong-name",
            front("name: grilling\ndescription: Synthetic."),
            "not its folder's name `grill`",
        ),
        (
            "folded",
            front("name: grill\ndescription: >\n  Synthetic."),
            "is not a one-line `key: value`",
        ),
        (
            "colon",
            front("name: grill\ndescription: Synthetic: broken."),
            "quote it",
        ),
        (
            "empty",
            front("name: grill\ndescription: \"\""),
            "`description` is empty",
        ),
        (
            "blank",
            front("name: grill\ndescription:"),
            "needs a value on the same line",
        ),
        (
            "no-space",
            front("name:grill\ndescription: Synthetic."),
            "needs a space after its `:`",
        ),
        (
            "boolean",
            front("name: grill\ndescription: true"),
            "reads as a YAML boolean",
        ),
        (
            "number",
            front("name: grill\ndescription: 1.5"),
            "reads as a YAML boolean",
        ),
        (
            "twice",
            front("name: grill\ndescription: One.\ndescription: Two."),
            "appears twice",
        ),
        (
            "long",
            front(&format!("name: grill\ndescription: {long}")),
            "longer than 1024",
        ),
    ];
    for (case, text, expected) in cases {
        let root = fixture(&format!("frontmatter-{case}"));
        write(&root, "skills/grill/SKILL.md", &text);
        assert_catches(&root, expected);
    }
}

#[test]
fn a_user_only_flag_fails() {
    let flagged =
        |flag: &str| format!("---\nname: grill\ndescription: Synthetic.\n{flag}\n---\n\n{STUB}\n");
    for (case, flag) in [
        ("claude", "disable-model-invocation: true"),
        ("claude-false", "disable-model-invocation: false"),
        ("hidden", "user-invocable: false"),
    ] {
        let root = fixture(&format!("user-only-{case}"));
        write(&root, "skills/grill/SKILL.md", &flagged(flag));
        assert_catches(
            &root,
            &format!("key `{}` is not allowed", flag.split(':').next().unwrap()),
        );
    }

    let root = fixture("user-only-codex");
    write(
        &root,
        "skills/grill/agents/openai.yaml",
        &format!("{OPENAI}policy:\n  allow_implicit_invocation: false\n"),
    );
    assert_catches(&root, "Codex's switch that makes a skill user-only");

    for (case, yaml, expected) in [
        (
            "no-interface",
            "  display_name: \"Synthetic\"\n",
            "must open with `interface:`",
        ),
        (
            "no-short",
            "interface:\n  display_name: \"Synthetic\"\n",
            "`interface.short_description` is missing",
        ),
        (
            "extra",
            &format!("{OPENAI}  icon_small: \"x.svg\"\n") as &str,
            "is not allowed",
        ),
    ] {
        let root = fixture(&format!("openai-{case}"));
        write(&root, "skills/grill/agents/openai.yaml", yaml);
        assert_catches(&root, expected);
    }
}

#[test]
fn a_missing_mit_notice_fails() {
    let root = fixture("notice-missing");
    write(
        &root,
        "skills/grill/SKILL.md",
        &written("grill", "Synthetic, no notice."),
    );
    write(&root, "skills/grill/agents/openai.yaml", OPENAI);
    assert_catches(&root, "Matt Pocock's copyright and MIT notice");

    let root = fixture("notice-changed");
    let changed = notice().replace("free of charge", "for a fee");
    write(&root, "skills/grill/SKILL.md", &written("grill", &changed));
    write(&root, "skills/grill/agents/openai.yaml", OPENAI);
    assert_catches(&root, "Matt Pocock's copyright and MIT notice");

    let root = fixture("notice-no-copyright");
    let unsigned = notice().replace("Copyright (c) 2026 Matt Pocock", "");
    write(&root, "skills/grill/SKILL.md", &written("grill", &unsigned));
    write(&root, "skills/grill/agents/openai.yaml", OPENAI);
    assert_catches(&root, "Matt Pocock's copyright and MIT notice");

    let root = fixture("written-no-openai");
    write(&root, "skills/grill/SKILL.md", &written("grill", &notice()));
    assert_catches(&root, "skills/grill/agents/openai.yaml is missing");

    let root = fixture("written-kept-stub-line");
    let kept = written("grill", &format!("{STUB_MARK} Synthetic.\n\n{}", notice()));
    write(&root, "skills/grill/SKILL.md", &kept);
    write(&root, "skills/grill/agents/openai.yaml", OPENAI);
    assert_catches(&root, "drops the stub line");
}

#[test]
fn a_dangling_or_wrong_link_fails() {
    let relink = |root: &Path, rel: &str, target: &str| {
        let link = root.join(rel);
        let _ = fs::remove_file(&link);
        symlink(target, link).expect("link");
    };

    let root = fixture("link-dangling");
    relink(&root, ".agents/skills/grill", "../../skills/gril");
    assert_catches(&root, ".agents/skills/grill points at `../../skills/gril`");
    assert_catches(&root, ".agents/skills/grill does not resolve");

    let root = fixture("link-missing");
    fs::remove_file(root.join(".claude/skills/setup")).expect("remove");
    assert_catches(
        &root,
        ".claude/skills/setup must be a link to `../../skills/setup`",
    );

    let root = fixture("link-other-skill");
    relink(&root, ".claude/skills/triage", "../../skills/setup");
    assert_catches(
        &root,
        ".claude/skills/triage points at `../../skills/setup`",
    );

    let root = fixture("link-absolute");
    let absolute = fs::canonicalize(root.join("skills/handoff")).expect("real");
    relink(
        &root,
        ".claude/skills/handoff",
        absolute.to_str().expect("utf-8"),
    );
    assert_catches(&root, ".claude/skills/handoff points at");

    let root = fixture("link-copied");
    fs::remove_file(root.join(".agents/skills/handoff")).expect("remove");
    write(&root, ".agents/skills/handoff/SKILL.md", &stub("handoff"));
    assert_catches(&root, ".agents/skills/handoff must be a link");

    let root = fixture("link-extra");
    relink(&root, ".claude/skills/old-skill", "../../skills/old-skill");
    assert_catches(
        &root,
        ".claude/skills/old-skill is a link, but not to one of the listed skills",
    );

    let root = fixture("link-extra-file");
    write(&root, ".agents/skills/notes.md", "Synthetic.\n");
    assert_catches(
        &root,
        ".agents/skills/notes.md: only the links to the listed skills",
    );

    // The repository's own older skills stay real folders in .claude/skills.
    let root = fixture("link-older-skill");
    write(&root, ".claude/skills/older/SKILL.md", &stub("older"));
    assert_clean(&root);

    let root = fixture("link-inside-skills");
    relink(&root, "skills/grill/shared.md", "../README.md");
    assert_catches(&root, "skills/grill/shared.md is a link");

    let root = fixture("markdown-dangling");
    write(
        &root,
        "skills/README.md",
        "# Synthetic\n\nSee [gone](gone/SKILL.md).\n",
    );
    assert_catches(
        &root,
        "skills/README.md: link `gone/SKILL.md` does not resolve",
    );

    let root = fixture("markdown-outside");
    write(&root, "../outside-synthetic.md", "Synthetic.\n");
    write(
        &root,
        "skills/README.md",
        "# Synthetic\n\n[out]: ../../outside-synthetic.md\n",
    );
    assert_catches(&root, "leaves the repository");
}

#[test]
fn a_broken_manifest_fails() {
    let plugin = |skills: Value, extra: Value| {
        let mut value =
            json!({"name": "synthetic-skills", "description": "Synthetic.", "skills": skills});
        value
            .as_object_mut()
            .unwrap()
            .extend(extra.as_object().unwrap().clone());
        value
    };
    let all = || -> Vec<Value> {
        SKILLS
            .iter()
            .map(|n| json!(format!("./skills/{n}")))
            .collect()
    };

    let root = fixture("plugin-missing");
    fs::remove_file(root.join(PLUGIN)).expect("remove");
    assert_catches(&root, ".claude-plugin/plugin.json is missing");

    let root = fixture("plugin-not-json");
    write(&root, PLUGIN, "{ synthetic");
    assert_catches(&root, "is not JSON");

    let mut fewer = all();
    fewer.retain(|entry| entry != "./skills/diagnose");
    let mut extra = all();
    extra.push(json!("./skills/extra"));
    let mut slash = all();
    slash[0] = json!("./skills/grill/");
    let mut twice = all();
    twice.push(json!("./skills/setup"));
    let cases = [
        (
            "unlisted",
            plugin(json!(fewer), json!({})),
            "does not list `./skills/diagnose`",
        ),
        (
            "extra",
            plugin(json!(extra), json!({})),
            "`./skills/extra` is not `./skills/<name>`",
        ),
        (
            "slash",
            plugin(json!(slash), json!({})),
            "`./skills/grill/` is not `./skills/<name>`",
        ),
        (
            "twice",
            plugin(json!(twice), json!({})),
            "`./skills/setup` is listed twice",
        ),
        (
            "hooks",
            plugin(json!(all()), json!({"hooks": "./hooks.json"})),
            "`hooks` is not allowed",
        ),
        (
            "version",
            plugin(json!(all()), json!({"version": "0.0.5"})),
            "`version` is not allowed",
        ),
        (
            "no-skills",
            json!({"name": "synthetic-skills", "description": "Synthetic."}),
            "`skills` must be an array",
        ),
    ];
    for (case, value, expected) in cases {
        let root = fixture(&format!("plugin-{case}"));
        write_json(&root, PLUGIN, &value);
        assert_catches(&root, expected);
    }

    let root = fixture("plugin-unresolved");
    fs::remove_file(root.join("skills/grill/SKILL.md")).expect("remove");
    assert_catches(&root, "`./skills/grill` does not resolve");

    let market = |plugins: Value| json!({"name": "synthetic", "owner": {"name": "Synthetic"}, "plugins": plugins});
    let cases = [
        (
            "source",
            market(json!([{"name": "synthetic-skills", "source": "./other"}])),
            "`source` must be `./`",
        ),
        (
            "name",
            market(json!([{"name": "other", "source": "./"}])),
            "`name` must be",
        ),
        (
            "two",
            market(
                json!([{"name": "synthetic-skills", "source": "./"}, {"name": "x", "source": "./"}]),
            ),
            "exactly one plugin entry",
        ),
        (
            "no-owner",
            json!({"name": "synthetic", "plugins": [{"name": "synthetic-skills", "source": "./"}]}),
            "`owner.name`",
        ),
    ];
    for (case, value, expected) in cases {
        let root = fixture(&format!("marketplace-{case}"));
        write_json(&root, MARKETPLACE, &value);
        assert_catches(&root, expected);
    }
}

#[test]
fn the_skill_set_is_exactly_the_list() {
    let root = fixture("set-missing");
    fs::remove_dir_all(root.join("skills/setup")).expect("remove");
    assert_catches(&root, "skills/setup is missing");

    let root = fixture("set-extra");
    write(&root, "skills/extra/SKILL.md", &stub("extra"));
    assert_catches(
        &root,
        "skills/extra: only README.md and the listed skill folders",
    );

    let root = fixture("set-no-readme");
    fs::remove_file(root.join("skills/README.md")).expect("remove");
    assert_catches(&root, "skills/README.md is missing");
}

/// The two source lines, as the orchestrator's diagnosis of #245's R1 worded
/// them: written here, not read from [`NOT_MATTS`].
const WHERE_ARE_WE_SOURCE: &str =
    "**Source:** dot-context's written plan. Not adapted from Matt Pocock's skills.";
const IMAGE_SOURCE: &str =
    "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.";

/// The stub body, then `extra`, for a skill's `SKILL.md`.
fn stub_with(name: &str, extra: &str) -> String {
    format!(
        "---\nname: {name}\ndescription: Synthetic description of {name}.\n---\n\n{STUB}\n{extra}"
    )
}

#[test]
fn only_a_skill_that_adapts_matts_needs_his_notice() {
    // Spec ClosedWiz#205: where-are-we and image adapt nothing of his, so
    // written with their source lines and without his notice they pass.
    let root = fixture("notice-not-matts");
    for (name, source) in [
        ("where-are-we", WHERE_ARE_WE_SOURCE),
        ("image", IMAGE_SOURCE),
    ] {
        write(
            &root,
            &format!("skills/{name}/SKILL.md"),
            &written(name, source),
        );
        write(&root, &format!("skills/{name}/agents/openai.yaml"), OPENAI);
    }
    assert_clean(&root);

    // The other three new skills adapt his, so they still need it.
    for name in ["wayfind", "research", "diagnose"] {
        let root = fixture(&format!("notice-missing-{name}"));
        let body = written(name, "Synthetic, no notice.");
        write(&root, &format!("skills/{name}/SKILL.md"), &body);
        write(&root, &format!("skills/{name}/agents/openai.yaml"), OPENAI);
        assert_catches(
            &root,
            &format!("skills/{name}/SKILL.md: a written skill carries Matt Pocock's"),
        );
    }

    // Notice or not, a written skill has its agents/openai.yaml.
    let root = fixture("not-matts-no-openai");
    write(
        &root,
        "skills/image/SKILL.md",
        &written("image", IMAGE_SOURCE),
    );
    assert_catches(&root, "skills/image/agents/openai.yaml is missing");
}

#[test]
fn a_stub_not_adapted_from_matts_passes_with_its_source_line() {
    let root = fixture("source-stubs");
    write(
        &root,
        "skills/where-are-we/SKILL.md",
        &stub_with("where-are-we", &format!("\n{WHERE_ARE_WE_SOURCE}\n")),
    );
    write(
        &root,
        "skills/image/SKILL.md",
        &stub_with("image", &format!("\n{IMAGE_SOURCE}\n")),
    );
    assert_clean(&root);
}

#[test]
fn a_skill_not_adapted_from_matts_without_its_exact_source_line_fails() {
    // A source line that is missing, changed, another skill's, or not on a
    // line of its own is refused, in a stub and in a written skill.
    let missing = "carries its source line exactly, on a line of its own";
    let image_changed = IMAGE_SOURCE.replace("original to OpenWiz", "original");
    let cases = [
        (
            "stub-no-source",
            "where-are-we",
            stub_with("where-are-we", ""),
        ),
        (
            "stub-changed",
            "image",
            stub_with("image", &format!("\n{image_changed}\n")),
        ),
        (
            "stub-other-skills",
            "where-are-we",
            stub_with("where-are-we", &format!("\n{IMAGE_SOURCE}\n")),
        ),
        (
            "stub-inline",
            "image",
            stub_with("image", &format!("\nSee {IMAGE_SOURCE}\n")),
        ),
        (
            "written-no-source",
            "image",
            written("image", "Synthetic, no source."),
        ),
        (
            "written-listed",
            "where-are-we",
            written("where-are-we", &format!("- {WHERE_ARE_WE_SOURCE}")),
        ),
    ];
    for (case, name, text) in cases {
        let root = fixture(&format!("source-{case}"));
        write(&root, &format!("skills/{name}/SKILL.md"), &text);
        write(&root, &format!("skills/{name}/agents/openai.yaml"), OPENAI);
        assert_catches(&root, &format!("skills/{name}/SKILL.md: {missing}"));
    }
}

#[test]
fn a_skill_not_adapted_from_matts_with_his_notice_fails() {
    // Matt Pocock's notice, or his copyright line alone, is refused there,
    // even beside the right source line: they don't adapt his work.
    let attributed = "must not carry Matt Pocock's copyright or notice";
    let copyright = MATT_NOTICE[0];
    let cases = [
        (
            "stub-notice",
            "image",
            stub_with("image", &format!("\n{IMAGE_SOURCE}\n\n{}\n", notice())),
        ),
        (
            "written-notice",
            "where-are-we",
            written(
                "where-are-we",
                &format!("{WHERE_ARE_WE_SOURCE}\n\n{}", notice()),
            ),
        ),
        (
            "written-copyright",
            "image",
            written("image", &format!("{IMAGE_SOURCE}\n\n{copyright}")),
        ),
    ];
    for (case, name, text) in cases {
        let root = fixture(&format!("attributed-{case}"));
        write(&root, &format!("skills/{name}/SKILL.md"), &text);
        write(&root, &format!("skills/{name}/agents/openai.yaml"), OPENAI);
        assert_catches(&root, &format!("skills/{name}/SKILL.md: {attributed}"));
    }
}

/// #198: exercise the public checker on synthetic ticket bodies, including
/// the shape that made #118's launch-fleet dependency invisible.
#[test]
fn plan_graph_relies_on_form() {
    use std::io::Write;
    use std::process::{Command, Stdio};

    let root = fixture("relies-on-form");
    write(&root, "contracts/widget.v1.md", "Synthetic contract.\n");
    write(&root, "contracts/widget.v1.schema.json", "{}\n");
    write(&root, "skills/launch-fleet/SKILL.md", "Synthetic rules.\n");
    write(&root, "GLOSSARY.md", "Synthetic words.\n");
    symlink(root.join("GLOSSARY.md"), root.join("contracts/alias.md")).expect("synthetic link");
    symlink(&root, root.join("contracts/alias-dir")).expect("synthetic directory link");
    let cases = [
        ("nothing", "**Relies on:** nothing\n", None, true),
        (
            "embedded-cr-duplicate",
            "**Relies \ron:** `contracts/widget.v1.md`\n**Relies on:** `contracts/widget.v1.schema.json`\n",
            None,
            false,
        ),
        (
            "crlf",
            "**Relies on:** `contracts/widget.v1.md`\r\n",
            None,
            true,
        ),
        (
            "bare-cr-boundary",
            "Synthetic title\r**Relies on:** `contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "unicode-boundary",
            "Synthetic title\u{2028}**Relies on:** `contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "one",
            "**Relies on:** `contracts/widget.v1.md`\n",
            None,
            true,
        ),
        (
            "two",
            "**Relies on:** `contracts/widget.v1.md`, `contracts/widget.v1.schema.json`\n",
            None,
            true,
        ),
        ("root-file", "**Relies on:** `GLOSSARY.md`\n", None, true),
        (
            "rules-file",
            "**Relies on:** `skills/launch-fleet/SKILL.md`\n",
            None,
            true,
        ),
        (
            "planned",
            "**Relies on:** `contracts/future.v1.md`\n",
            Some("contracts/future.v1.md"),
            true,
        ),
        (
            "historical-118",
            "**Relies on:** `contracts/fleet-tick.v1.*` (B1); 0.0.5's `launch-fleet` rules (#102)\n",
            None,
            false,
        ),
        (
            "prose",
            "**Relies on:** the review report format (0.0.5 #101)\n",
            None,
            false,
        ),
        (
            "partial-name",
            "**Relies on:** `launch-fleet`\n",
            None,
            false,
        ),
        (
            "partial-file",
            "**Relies on:** `widget.v1.md`\n",
            None,
            false,
        ),
        (
            "mixed",
            "**Relies on:** `contracts/widget.v1.md`; review rules\n",
            None,
            false,
        ),
        (
            "annotation",
            "**Relies on:** `contracts/widget.v1.md` (#110)\n",
            None,
            false,
        ),
        ("folder", "**Relies on:** `contracts/`\n", None, false),
        (
            "glob",
            "**Relies on:** `contracts/widget.v1.*`\n",
            None,
            false,
        ),
        (
            "triple-star-duplicate",
            "***Relies on: `contracts/widget.v1.md`\n**Relies on:** `contracts/widget.v1.schema.json`\n",
            None,
            false,
        ),
        (
            "planned-file-parent",
            "**Relies on:** `contracts/widget.v1.md/future.md`\n",
            Some("contracts/widget.v1.md/future.md"),
            false,
        ),
        ("directory", "**Relies on:** `contracts`\n", None, false),
        (
            "symlink",
            "**Relies on:** `contracts/alias.md`\n",
            None,
            false,
        ),
        (
            "symlink-parent",
            "**Relies on:** `contracts/alias-dir/GLOSSARY.md`\n",
            None,
            false,
        ),
        (
            "planned-symlink",
            "**Relies on:** `contracts/alias-dir/future.md`\n",
            Some("contracts/alias-dir/future.md"),
            false,
        ),
        (
            "missing",
            "**Owned paths:** `contracts/widget.v1.md`\n",
            None,
            false,
        ),
        ("empty", "**Relies on:**\n", None, false),
        (
            "section",
            "## Relies on\n\n`contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "multiline",
            "**Relies on:** `contracts/widget.v1.md`\n`contracts/widget.v1.schema.json`\n",
            None,
            false,
        ),
        (
            "duplicate",
            "**Relies on:** nothing\n**Relies on:** `contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "duplicate-heading",
            "**Relies on:** nothing\n## Relies on\n\n`contracts/widget.v1.md`\n",
            None,
            false,
        ),
        ("empty-ticks", "**Relies on:** ``\n", None, false),
        (
            "unclosed",
            "**Relies on:** `contracts/widget.v1.md\n",
            None,
            false,
        ),
        (
            "double-ticks",
            "**Relies on:** ``contracts/widget.v1.md``\n",
            None,
            false,
        ),
        (
            "nothing-and-file",
            "**Relies on:** nothing, `contracts/widget.v1.md`\n",
            None,
            false,
        ),
        ("quoted-nothing", "**Relies on:** `nothing`\n", None, false),
        ("wrong-case", "**Relies on:** Nothing\n", None, false),
        (
            "absolute",
            "**Relies on:** `/contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "parent",
            "**Relies on:** `../contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "dot",
            "**Relies on:** `./contracts/widget.v1.md`\n",
            None,
            false,
        ),
        (
            "double-slash",
            "**Relies on:** `contracts//widget.v1.md`\n",
            None,
            false,
        ),
        (
            "non-ascii",
            "**Relies on:** `contracts/widgét.md`\n",
            None,
            false,
        ),
        (
            "unknown-file",
            "**Relies on:** `contracts/missing.md`\n",
            None,
            false,
        ),
        (
            "wrong-planned",
            "**Relies on:** `contracts/other.md`\n",
            Some("contracts/future.v1.md"),
            false,
        ),
        (
            "fenced",
            "```md\n**Relies on:** nothing\n```\n",
            None,
            false,
        ),
        (
            "commented",
            "<!--\n**Relies on:** nothing\n-->\n",
            None,
            false,
        ),
    ];
    // CI's Rust phase has sh and jq but no Python; the later skills phase
    // bootstraps Python separately. Keep this public check independent of it.
    let tools = root.join("checker-tools");
    crate::dirs::private_dir_all(&tools).expect("checker tools");
    for name in ["sh", "jq"] {
        let program = std::env::split_paths(&std::env::var_os("PATH").expect("PATH"))
            .map(|dir| dir.join(name))
            .find(|path| path.is_file())
            .expect("existing fleet tool");
        symlink(program, tools.join(name)).expect("tool link");
    }
    let mut wrong = Vec::new();
    for (case, body, planned, valid) in cases {
        let mut command = Command::new("sh");
        command
            .env("PATH", &tools)
            .arg(Path::new(ROOT).join("skills/plan-graph/check-relies.sh"))
            .arg("--root")
            .arg(&root);
        if let Some(path) = planned {
            command.arg("--planned").arg(path);
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("run the public checker");
        // The next heading bounds the declaration. A continuation path before
        // it is part of the same declaration and must not escape the check.
        let ticket = format!(
            "# Synthetic ticket\n\n{body}\n## Acceptance criteria\n\n- [ ] Synthetic proof.\n"
        );
        child
            .stdin
            .take()
            .expect("stdin")
            .write_all(ticket.as_bytes())
            .expect("ticket body");
        let output = child.wait_with_output().expect("checker result");
        if output.status.code() != Some(if valid { 0 } else { 1 }) {
            wrong.push(format!(
                "{case}: expected {}, got {:?}: {}",
                if valid { 0 } else { 1 },
                output.status.code(),
                String::from_utf8_lossy(&output.stderr)
            ));
            continue;
        }
        assert!(
            output.stdout.is_empty(),
            "{case}: a check prints no payload"
        );
        if !valid {
            assert!(
                String::from_utf8_lossy(&output.stderr).starts_with("Relies on: "),
                "{case}: diagnostic"
            );
        }
    }
    assert!(wrong.is_empty(), "unexpected checker verdicts: {wrong:?}");
}

#[test]
fn plan_graph_relies_on_rule_and_template() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/plan-graph/SKILL.md"))
        .expect("plan-graph skill");
    let root = fixture("relies-rule");
    write(&root, "skills/plan-graph/SKILL.md", &text);
    write(&root, "skills/plan-graph/agents/openai.yaml", OPENAI);
    // First prove the real skill carries the operative rule and template.
    let mut found = Vec::new();
    check_plan_graph(&root, &mut found);
    assert!(found.is_empty(), "{}", found.join("\n"));

    let rule = text
        .lines()
        .find(|line| line.starts_with("- **Contracts, not code.** "))
        .expect("operative rule");
    let changed = text.replacen(
        rule,
        "- **Contracts, not code.** Name what the ticket relies on.",
        1,
    );
    // Even keeping the right words in a citation must not satisfy the check.
    write(
        &root,
        "skills/plan-graph/SKILL.md",
        &format!("{changed}\nCitation: {RELIES_RULE}\n"),
    );
    assert_catches(&root, "the operative Contracts rule");

    write(
        &root,
        "skills/plan-graph/SKILL.md",
        &text.replace(RELIES_TEMPLATE, "## Relies on\n\n<contracts>"),
    );
    assert_catches(&root, "the ticket template needs one inline Relies on");
}

#[test]
fn plan_graph_relies_on_rule_is_visible_and_template_is_unique() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("skills/plan-graph/SKILL.md")).expect("skill");
    let rule = text
        .lines()
        .find(|line| line.starts_with("- **Contracts, not code.** "))
        .expect("operative rule");
    let cases = [
        (
            "commented-rule",
            text.replacen(
                rule,
                &format!("- **Contracts, not code.** Name dependencies. <!-- {RELIES_RULE} -->"),
                1,
            ),
            "the operative Contracts rule",
        ),
        (
            "moved-rule",
            format!("{}\n```md\n{rule}\n```\n", text.replacen(rule, "", 1)),
            "the operative Contracts rule",
        ),
        (
            "duplicate-template",
            text.replacen(
                RELIES_TEMPLATE,
                &format!("{RELIES_TEMPLATE}\n**Relies on:** nothing"),
                1,
            ),
            "the ticket template needs one inline Relies on",
        ),
    ];
    let mut missed = Vec::new();
    for (case, body, expected) in cases {
        let root = fixture(&format!("relies-{case}"));
        write(&root, "skills/plan-graph/SKILL.md", &body);
        let mut found = Vec::new();
        check_plan_graph(&root, &mut found);
        if !found.iter().any(|problem| problem.contains(expected)) {
            missed.push(case);
        }
    }
    assert!(
        missed.is_empty(),
        "guard missed planted violations: {missed:?}"
    );
}

/// #379: exercise the research guard through its public CLI, with a fake gh.
#[test]
fn research_worker_github_check() {
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;

    let root = fixture("research-github-check");
    let tools = root.join("tools");
    crate::dirs::private_dir_all(&tools).expect("tools");
    for name in ["sh", "jq", "mktemp", "rm", "cat"] {
        let program = std::env::split_paths(&std::env::var_os("PATH").expect("PATH"))
            .map(|dir| dir.join(name))
            .find(|path| path.is_file())
            .expect("existing tool");
        symlink(program, tools.join(name)).expect("tool link");
    }
    write(
        &root,
        "tools/gh",
        r#"#!/bin/sh
printf '%s\n' "$*" >> "$RESEARCH_FIXTURE/reads"
[ "$#" = 6 ] && [ "$1 $2 $3 $4 $5" = 'api --method GET --paginate --slurp' ] || exit 90
case "$6" in
  'repos/example/widgets/branches?per_page=100') cat "$RESEARCH_FIXTURE/branches" ;;
  'repos/example/widgets/pulls?state=all&per_page=100') cat "$RESEARCH_FIXTURE/pulls" ;;
  'repos/example/widgets/issues/comments?per_page=100') cat "$RESEARCH_FIXTURE/comments" ;;
  'repos/example/widgets/pulls/comments?per_page=100') cat "$RESEARCH_FIXTURE/review-comments" ;;
  *) exit 91 ;;
esac
"#,
    );
    fs::set_permissions(tools.join("gh"), fs::Permissions::from_mode(0o700)).expect("mode");
    let branch = json!({"name": "main", "commit": {"sha": "a".repeat(40)}});
    let pull = json!({"number": 17, "state": "open", "merged_at": null,
        "title": "Synthetic report", "body": "Synthetic evidence", "draft": false,
        "head": {"ref": "research/widgets", "sha": "b".repeat(40), "repo": {"full_name": "example/widgets"}},
        "base": {"ref": "main", "repo": {"full_name": "example/widgets"}}});
    let comment = json!({"id": 23, "body": "Synthetic note", "updated_at": "2026-01-01T00:00:00Z"});
    let script = Path::new(ROOT).join("skills/research/scripts/check-workers.sh");
    let run = |args: &[&str]| {
        Command::new("sh")
            .arg(&script)
            .args(args)
            .env("PATH", &tools)
            .env("GH_REPO", "example/widgets")
            .env("RESEARCH_FIXTURE", &root)
            .output()
            .expect("run research guard")
    };
    let reset = || {
        write_json(&root, "branches", &json!([[branch.clone()], []]));
        write_json(&root, "pulls", &json!([[pull.clone()]]));
        write_json(&root, "comments", &json!([[comment.clone()]]));
        write_json(&root, "review-comments", &json!([[]]));
    };
    reset();
    let before = run(&["snapshot"]);
    assert!(
        before.status.success(),
        "snapshot: {}",
        String::from_utf8_lossy(&before.stderr)
    );
    write(
        &root,
        "before.json",
        &String::from_utf8(before.stdout).expect("JSON"),
    );
    let snapshot = root.join("before.json");
    let snapshot = snapshot.to_str().expect("path");
    let clean = run(&["check", snapshot]);
    assert_eq!(clean.status.code(), Some(0));
    assert_eq!(
        clean.stdout,
        b"clean research: no unexplained changes in checked GitHub surfaces\n"
    );
    assert!(clean.stderr.is_empty());
    let reads = fs::read_to_string(root.join("reads")).expect("reads");
    assert_eq!(reads.lines().count(), 8);
    for endpoint in [
        "branches?per_page=100",
        "pulls?state=all&per_page=100",
        "issues/comments?per_page=100",
        "pulls/comments?per_page=100",
    ] {
        assert_eq!(
            reads
                .lines()
                .filter(|line| line.ends_with(endpoint))
                .count(),
            2
        );
    }
    // Every mutation is independent, with literal expected finding names.
    let moved = json!({"name": "main", "commit": {"sha": "c".repeat(40)}});
    let new = json!({"name": "room/research-worker", "commit": {"sha": "d".repeat(40)}});
    let mut cases = vec![
        (
            "branches",
            json!([[branch.clone()], [new.clone()]]),
            "branch room/research-worker",
        ),
        ("branches", json!([[moved]]), "branch main"),
        ("branches", json!([[]]), "branch main"),
        ("pulls", json!([[]]), "pull request #17"),
        ("comments", json!([[]]), "comment 23"),
        (
            "review-comments",
            json!([[comment.clone()]]),
            "review comment 23",
        ),
    ];
    for (field, value) in [
        ("state", json!("closed")),
        ("merged_at", json!("2026-01-01T00:00:00Z")),
        ("title", json!("Unexpected edit")),
        ("body", json!("Unexpected body")),
        ("draft", json!(true)),
    ] {
        let mut changed = pull.clone();
        changed[field] = value;
        cases.push(("pulls", json!([[changed]]), "pull request #17"));
    }
    let mut extra_pull = pull.clone();
    extra_pull["number"] = json!(18);
    cases.push((
        "pulls",
        json!([[pull.clone()], [extra_pull]]),
        "pull request #18",
    ));
    for (side, field, value) in [
        ("head", "sha", json!("f".repeat(40))),
        ("head", "ref", json!("research/other")),
        ("base", "ref", json!("release-example")),
    ] {
        let mut changed = pull.clone();
        changed[side][field] = value;
        cases.push(("pulls", json!([[changed]]), "pull request #17"));
    }
    let mut edited_comment = comment.clone();
    edited_comment["body"] = json!("Unexpected edit");
    cases.push(("comments", json!([[edited_comment]]), "comment 23"));
    for (file, value, finding) in cases {
        reset();
        write_json(&root, file, &value);
        let result = run(&["check", snapshot]);
        assert_eq!(
            result.status.code(),
            Some(1),
            "{file}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        let output = String::from_utf8(result.stdout).expect("output");
        assert_eq!(output, format!("hit research: {finding}\n"));
        assert!(result.stderr.is_empty());
    }
    // Only an exact, explicitly acknowledged resulting value is exempted.
    reset();
    write_json(&root, "branches", &json!([[branch.clone(), new]]));
    write_json(
        &root,
        "allow.json",
        &json!({"branch room/research-worker": "d".repeat(40)}),
    );
    let allow = root.join("allow.json");
    let result = run(&["check", snapshot, "--allow", allow.to_str().expect("path")]);
    assert_eq!(result.status.code(), Some(0));
    write_json(
        &root,
        "allow.json",
        &json!({"branch room/research-worker": "e".repeat(40)}),
    );
    let result = run(&["check", snapshot, "--allow", allow.to_str().expect("path")]);
    assert_eq!(result.status.code(), Some(2));
    assert!(result.stdout.is_empty());
    // #990: `null` allows the deletion of any item: a branch, a PR or a comment.
    for (file, value, key) in [
        ("branches", json!([[]]), "branch main"),
        ("pulls", json!([[]]), "pull request #17"),
        ("comments", json!([[]]), "comment 23"),
    ] {
        reset();
        write_json(&root, file, &value);
        write_json(&root, "allow.json", &json!({ key: null }));
        let result = run(&["check", snapshot, "--allow", allow.to_str().expect("path")]);
        assert_eq!(result.status.code(), Some(0), "{key}");
        assert_eq!(
            result.stdout,
            b"clean research: no unexplained changes in checked GitHub surfaces\n"
        );
    }
    // `null` allows only a deletion, never an edit of the same item.
    reset();
    let mut edited = pull.clone();
    edited["title"] = json!("Unexpected edit");
    write_json(&root, "pulls", &json!([[edited]]));
    write_json(&root, "allow.json", &json!({"pull request #17": null}));
    let result = run(&["check", snapshot, "--allow", allow.to_str().expect("path")]);
    assert_eq!(result.status.code(), Some(2));
    assert!(result.stdout.is_empty());
    // #991: an allowance must name an actual change, even with the current value.
    reset();
    write_json(&root, "allow.json", &json!({"branch main": "a".repeat(40)}));
    let result = run(&["check", snapshot, "--allow", allow.to_str().expect("path")]);
    assert_eq!(result.status.code(), Some(2));
    assert!(result.stdout.is_empty());
    assert_eq!(
        result.stderr,
        b"check-workers.sh: allowance does not match observed changes\n"
    );
    // #991: only the snapshot validation refuses these; each would otherwise be read.
    let saved: Value =
        serde_json::from_str(&fs::read_to_string(root.join("before.json")).expect("snapshot"))
            .expect("snapshot JSON");
    let mut invalid = Vec::new();
    let mut unknown_key = saved.clone();
    unknown_key["items"]["tag v1"] = json!("a".repeat(40));
    invalid.push(("unknown item key", unknown_key));
    let mut not_sha = saved.clone();
    not_sha["items"]["branch main"] = json!("main");
    invalid.push(("non-SHA branch value", not_sha));
    let mut version = saved;
    version["version"] = json!(2);
    invalid.push(("unknown version", version));
    for (case, value) in invalid {
        reset();
        write_json(&root, "invalid.json", &value);
        let path = root.join("invalid.json");
        let result = run(&["check", path.to_str().expect("path")]);
        assert_eq!(result.status.code(), Some(2), "{case}");
        assert!(result.stdout.is_empty(), "{case}");
        assert_eq!(
            result.stderr, b"check-workers.sh: invalid snapshot\n",
            "{case}"
        );
    }
    // Broken, missing and partial reads never produce a clean result.
    for file in ["branches", "pulls", "comments", "review-comments"] {
        for bad in ["", "{}", "[]", "[[], {}]", "[[{}]]", "[[{}]", "[[], []"] {
            reset();
            write(&root, file, bad);
            let result = run(&["check", snapshot]);
            assert_eq!(result.status.code(), Some(2), "{file}: {bad}");
            assert!(result.stdout.is_empty());
            assert!(!result.stderr.is_empty());
        }
        reset();
        fs::remove_file(root.join(file)).expect("remove fake response");
        let result = run(&["check", snapshot]);
        assert_eq!(result.status.code(), Some(2));
        assert!(result.stdout.is_empty());
    }
    reset();
    write_json(&root, "branches", &json!([[branch.clone()], [branch]]));
    assert_eq!(run(&["snapshot"]).status.code(), Some(2), "duplicate ref");
    for bad in ["{}", "null", "[]", "{\"version\":1}"] {
        write(&root, "bad.json", bad);
        let path = root.join("bad.json");
        assert_eq!(
            run(&["check", path.to_str().expect("path")]).status.code(),
            Some(2)
        );
    }
}

#[test]
fn research_workflow_checks_github_around_dispatch() {
    let skill = fs::read_to_string(Path::new(ROOT).join("skills/research/SKILL.md"))
        .expect("research skill");
    let dispatch = skill
        .split("## 2. Dispatch fresh workers\n")
        .nth(1)
        .expect("dispatch section")
        .split("## Worker:")
        .next()
        .expect("dispatch body");
    let before = dispatch
        .find("check-workers.sh\" snapshot")
        .expect("snapshot");
    let spawn = dispatch.find("room-cli thread spawn").expect("dispatch");
    let archive = dispatch
        .find("Archive each child")
        .expect("archive workers");
    let after = dispatch.find("check-workers.sh\" check").expect("check");
    assert!(before < spawn && spawn < archive && archive < after);
    assert!(dispatch.contains("If the snapshot fails, do not start workers"));
    assert!(dispatch.contains("Keep every hit or error in the report's **Gaps**"));
    assert!(dispatch.contains("Exit 2 means"));
    assert!(
        dispatch.contains(
            "never call that swarm clean while any hit is unexplained or any error remains"
        )
    );
    // #990: `null` allows the deletion of any item, not only a branch.
    let allowance = dispatch
        .lines()
        .find(|line| line.contains("--allow '<exact-changes.json>'"))
        .expect("allowance rule");
    assert!(allowance.contains(
        "For the deletion of any item (a branch, a PR or a comment), the value is `null`."
    ));
    assert!(!allowance.contains("(or `null` for deletion)"));
    // #990: an allowed result is reported as such, never as plain clean.
    assert!(allowance.contains(
        "report the swarm as \"clean after allowances, see Gaps\", never as plain clean"
    ));
}

// #989: each tool call may start a fresh shell, so no dispatch command may
// read a shell variable another block set; the snapshot path is a literal the
// asker records in its notes and passes back to `check`.
#[test]
fn research_snapshot_path_survives_fresh_shells() {
    let skill = fs::read_to_string(Path::new(ROOT).join("skills/research/SKILL.md"))
        .expect("research skill");
    let dispatch = skill
        .split("## 2. Dispatch fresh workers\n")
        .nth(1)
        .expect("dispatch section")
        .split("## Worker:")
        .next()
        .expect("dispatch body");
    let blocks: Vec<&str> = dispatch
        .split("```sh\n")
        .skip(1)
        .map(|rest| rest.split_once("\n```").expect("sh block closes").0)
        .collect();
    assert!(!blocks.is_empty(), "the dispatch section has sh blocks");
    for block in &blocks {
        let assigned: BTreeSet<&str> = block
            .lines()
            .filter_map(|line| line.trim().split_once('='))
            .map(|(name, _)| name)
            .filter(|name| name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'))
            .collect();
        for (at, _) in block.match_indices('$') {
            let name: String = block[at + 1..]
                .trim_start_matches('{')
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
                .collect();
            assert!(
                name.is_empty() || assigned.contains(name.as_str()),
                "dispatch block reads ${name}, set in another shell:\n{block}"
            );
        }
    }
    let commands: Vec<&str> = blocks.iter().flat_map(|block| block.lines()).collect();
    assert!(
        commands.contains(&"mktemp"),
        "mktemp runs alone and prints the path"
    );
    let prose = dispatch.split_whitespace().collect::<Vec<_>>().join(" ");
    assert!(
        prose.contains("Record that literal path in your notes"),
        "the asker records the printed path"
    );

    // #989 R1: a TMPDIR with spaces (or a quote) must still reach the checker
    // as one argument. Run the skill's own commands, each in a fresh `sh -c`,
    // with a fake checker that prints its arguments, after filling the
    // placeholders exactly as the skill says.
    let checker = "sh \"<research-skill-folder>/scripts/check-workers.sh\" ";
    let find = |verb: &str| -> String {
        let found: Vec<&&str> = commands
            .iter()
            .filter(|line| line.starts_with(&format!("{checker}{verb} ")))
            .collect();
        assert_eq!(found.len(), 1, "one `{verb}` command:\n{dispatch}");
        (*found[0]).to_owned()
    };
    let snapshot_command = find("snapshot");
    let check_command = find("check");
    let root = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("skills-check")
        .join("research-snapshot-quoting");
    let _ = fs::remove_dir_all(&root);
    let folder = root.join("skill folder");
    write(
        &folder,
        "scripts/check-workers.sh",
        "for arg in \"$@\"; do printf 'arg:%s\\n' \"$arg\"; done\n",
    );
    let snapshot = root.join("tmp dir/it's a snapshot");
    let allow = root.join("tmp dir/exact changes.json");
    crate::dirs::private_dir_all(snapshot.parent().expect("parent")).expect("tmp dir");
    let quote = |path: &Path| path.to_str().expect("path").replace('\'', "'\\''");
    let shell = |command: &str| {
        let filled = command
            .replace("<research-skill-folder>", folder.to_str().expect("folder"))
            .replace("<snapshot-path>", &quote(&snapshot))
            .replace("<exact-changes.json>", &quote(&allow));
        let output = std::process::Command::new("sh")
            .arg("-c")
            .arg(&filled)
            .current_dir(&root)
            .output()
            .expect("run sh");
        assert!(
            output.status.success(),
            "{filled}\n{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).expect("utf-8")
    };
    let snap = snapshot.to_str().expect("path");
    assert_eq!(shell(&snapshot_command), "");
    assert_eq!(
        fs::read_to_string(&snapshot).expect("snapshot at the recorded path"),
        "arg:snapshot\n"
    );
    assert_eq!(shell(&check_command), format!("arg:check\narg:{snap}\n"));
    let rerun = "`check '<snapshot-path>' --allow '<exact-changes.json>'`";
    assert_eq!(prose.matches(rerun).count(), 1, "the allowance rerun");
    let rerun_command = format!("{checker}{}", rerun.trim_matches('`'));
    assert!(
        prose.contains(
            "replace `<snapshot-path>` inside its single quotes with the path, \
             writing each `'` in it as `'\\''`"
        ),
        "the skill says how to quote the recorded path"
    );
    assert_eq!(
        shell(&rerun_command),
        format!(
            "arg:check\narg:{snap}\narg:--allow\narg:{}\n",
            allow.to_str().expect("path")
        )
    );
    assert_eq!(
        snapshot_command,
        format!("{checker}snapshot > '<snapshot-path>'")
    );
    assert_eq!(check_command, format!("{checker}check '<snapshot-path>'"));
}

// #1095: the confirmed grill makes only ask-wiz user-started.
#[test]
fn ask_wiz_user_started_policy() {
    let root = fixture("ask-wiz-policy");
    let text = written("ask-wiz", &notice()).replacen(
        "description: Synthetic description of ask-wiz.\n",
        "description: Synthetic description of ask-wiz.\ndisable-model-invocation: true\n",
        1,
    );
    let yaml = format!("{OPENAI}policy:\n  allow_implicit_invocation: false\n");
    write(&root, "skills/ask-wiz/SKILL.md", &text);
    write(&root, "skills/ask-wiz/agents/openai.yaml", &yaml);
    assert_clean(&root);

    for bad in [
        text.replace("disable-model-invocation: true\n", ""),
        text.replace(
            "disable-model-invocation: true",
            "disable-model-invocation: false",
        ),
        text.replace(
            "disable-model-invocation: true",
            "disable-model-invocation: \"true\"",
        ),
        text.replace(
            "disable-model-invocation: true",
            "disable-model-invocation: true\ndisable-model-invocation: true",
        ),
    ] {
        write(&root, "skills/ask-wiz/SKILL.md", &bad);
        assert_catches(&root, "disable-model-invocation");
    }
    write(&root, "skills/ask-wiz/SKILL.md", &text);
    for bad in [
        OPENAI.to_owned(),
        yaml.replace(
            "allow_implicit_invocation: false",
            "allow_implicit_invocation: true",
        ),
        yaml.replace(
            "allow_implicit_invocation: false",
            "allow_implicit_invocation: \"false\"",
        ),
        format!("{yaml}  allow_implicit_invocation: false\n"),
        format!("{yaml}  unknown: false\n"),
    ] {
        write(&root, "skills/ask-wiz/agents/openai.yaml", &bad);
        assert_catches(&root, "policy");
    }
}

#[test]
fn ask_wiz_contract() {
    let root = Path::new(ROOT);
    let text = fs::read_to_string(root.join("skills/ask-wiz/SKILL.md")).expect("ask-wiz skill");
    let (front, _) = split_frontmatter(&text).expect("frontmatter");
    let description = front
        .iter()
        .find(|line| line.starts_with("description: "))
        .expect("description");
    for required in ["suggest", "confused", "never run it in their own workflows"] {
        assert!(
            description.contains(required),
            "description needs {required}"
        );
    }
    let section = |heading: &str| {
        text.split_once(heading)
            .expect(heading)
            .1
            .split("\n## ")
            .next()
            .expect("section")
    };
    let main = section("## Main flow\n");
    for name in [
        "grill",
        "plan-graph",
        "launch-fleet",
        "build-ticket",
        "review-ticket",
        "where-are-we",
    ] {
        assert!(main.contains(&format!("`{name}`")), "main flow: {name}");
    }
    for (heading, names) in [
        (
            "## On-ramps\n",
            vec!["triage", "diagnose", "huntr", "wayfind"],
        ),
        ("## Tools\n", vec!["hill-climb", "image", "research"]),
        (
            "## Running the factory\n",
            vec!["handoff", "setup", "overnight"],
        ),
    ] {
        for name in names {
            assert!(
                section(heading).contains(&format!("`{name}`")),
                "{heading}: {name}"
            );
        }
    }
    for required in [
        "Read a skill's SKILL.md before recommending it",
        "skills installed in this session",
        "Wait for the user's yes before running the chosen skill",
        "PHASE-BOUNDARIES.md",
    ] {
        assert!(text.contains(required), "routing rule: {required}");
    }
    let discovery = section("## When no available skill fits\n");
    for required in [
        "trusted sources first",
        "Matt Pocock",
        "Vercel",
        "Anthropic",
        "David Ondrej",
        "npx skills find <query>",
        "GitHub",
        "top three",
        "stars",
        "source",
        "what it does",
        "Read the chosen SKILL.md straight from GitHub",
        "network calls",
        "credentials",
        "deleting things",
        "scripts",
        "install only",
        "wants to keep it",
        "user's yes",
    ] {
        assert!(discovery.contains(required), "discovery rule: {required}");
    }
    assert!(
        ask_wiz_install_rule_holds(discovery),
        "operative installation gate"
    );
    let readme = fs::read_to_string(root.join("skills/README.md")).expect("README");
    assert_eq!(
        readme
            .lines()
            .filter(|line| line.starts_with("| [`ask-wiz`](ask-wiz/SKILL.md) |"))
            .count(),
        1
    );
    for manifest in [PLUGIN, MARKETPLACE] {
        let text = fs::read_to_string(root.join(manifest)).expect("manifest");
        assert!(text.contains("ask-wiz"), "{manifest} describes ask-wiz");
    }
}

#[test]
fn ask_wiz_phase_boundaries() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/ask-wiz/PHASE-BOUNDARIES.md"))
        .expect("phase reference");
    for required in [
        "Keep going",
        "fresh thread",
        "handoff",
        "child thread",
        "primary source",
        "orchestrator",
        "builder",
        "reviewer",
        "ticket",
        "pull request",
    ] {
        assert!(text.contains(required), "phase guide: {required}");
    }
}

// Keep the installation gate as an operative instruction, not scattered words.
fn ask_wiz_install_rule_holds(discovery: &str) -> bool {
    let rules: Vec<_> = discovery
        .split("\n\n")
        .filter(|paragraph| paragraph.starts_with("For a lasting copy,"))
        .collect();
    rules.len() == 1
        && collapse(rules[0])
            == "For a lasting copy, install only when the user wants to keep it, and only on the user's yes to installation."
}

#[test]
fn ask_wiz_install_rule_refuses_ungated_or_hidden_instructions() {
    let text = fs::read_to_string(Path::new(ROOT).join("skills/ask-wiz/SKILL.md")).expect("skill");
    let rule = "For a lasting copy, install only when the user wants to keep it, and only on the\nuser's yes to installation.";
    assert!(text.contains(rule), "operative installation rule");
    let section = text
        .split_once("## When no available skill fits\n")
        .expect("discovery")
        .1;
    assert!(ask_wiz_install_rule_holds(section));
    for changed in [
        section.replace(
            rule,
            "Install immediately. install only; wants to keep it; user's yes.",
        ),
        section.replace(rule, &format!("<!-- {rule} -->")),
        section.replace(rule, &format!("```md\n{rule}\n```")),
        section.replace(rule, &format!("Citation: {rule}")),
    ] {
        assert!(
            !ask_wiz_install_rule_holds(&changed),
            "accepted an absent or hidden installation gate"
        );
    }
}

#[test]
fn feedback_helper_offline_proofs_pass() {
    // #2292: contracts/feedback.v1.md's sender and sharing proof rows, run
    // offline on the skill's recording `gh` and private scratch state.
    let result = std::process::Command::new("python3")
        .args(["-I", "skills/feedback/test/test_feedback.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the feedback helper's offline proofs");
    assert!(
        result.status.success(),
        "feedback helper proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn ci_runs_where_are_we_collector_tests_after_triage() {
    // K16 keeps the full-run order, and selects each folder independently.
    // Execute the owning workflow-boundary proof with synthetic fake suites.
    let result = std::process::Command::new("python3")
        .args([
            "-I",
            "ci/select/test_steps.py",
            "Dispatch.test_triage_and_collector_full_and_selected",
        ])
        .current_dir(ROOT)
        .output()
        .expect("run the synthetic skill-dispatch proof");
    assert!(
        result.status.success(),
        "skill dispatch proof failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

// #1845: these are the operative release instructions an agent follows,
// not evidence that any live run or publication has happened.
fn release_instruction(skill: &str, prefix: &str, required: &[&str]) {
    let text = fs::read_to_string(Path::new(ROOT).join(format!(".claude/skills/{skill}/SKILL.md")))
        .expect("local release skill");
    let paragraphs: Vec<_> = text
        .split("\n\n")
        .map(collapse)
        .filter(|paragraph| paragraph.starts_with(prefix))
        .collect();
    assert_eq!(paragraphs.len(), 1, "{skill}: one operative {prefix} rule");
    for rule in required {
        assert!(paragraphs[0].contains(rule), "{skill}: missing {rule}");
    }
}

#[test]
fn adr0019_live_smoke_and_hands_on_timing() {
    // ADR 0020 keeps ADR 0019's smoke and post-publication feedback decisions.
    release_instruction(
        "live-quick-check",
        "**Release gate:**",
        &[
            "CI, privacy/claims, verified products and an agent-run live smoke on the same combined build must pass",
            "exercise every included version's promise end to end",
            "Changed sending, thread creation, App permissions and spending also need their relevant bounded live checks before publication",
            "Unknown/missing risk or evidence refuses",
            "Jake's actual ship instruction and exact changelog approval are the only human release actions for this path",
            "no per-step live/publish prompt, export-plan, final-diff, standalone Sol-export or mandatory hands-on/device gate",
            "Ordinary code review/CI remain",
            "Hands-on feedback follows publication",
        ],
    );
    release_instruction(
        "live-quick-check",
        "2. **Restrict before effects.**",
        &[
            "kit's own throwaway targets within existing counts, room-cli allowlist and spending bounds",
            "reviewed-plan `--expect-plan` restriction before effects, including refusal of pending-start recovery",
            "Refuse if the restriction or any authority is uncertain",
            "An approved kit covers its steps without another human prompt",
            "No automatic retry",
            "persist consumed attempts and completed steps",
        ],
    );
    release_instruction(
        "live-quick-check",
        "5. **Keep device limits explicit.**",
        &[
            "approved headless emulation",
            "WebKit and real radios stay unverified",
            "Mac-only checks stay on the Mac within existing authority",
            "A required promise left unproved blocks its gate",
            "Optional hands-on/device feedback follows publication",
        ],
    );
}

#[test]
fn adr0019_combined_release_gate() {
    release_instruction(
        "export-review",
        "1. **Prepare one checked candidate.**",
        &[
            "public repository's own history",
            "clean selected commit/build and complete matching products for all supported targets",
            "ordered individual changelog sections for every included version",
            "all seven for the settled 0.0.6–0.0.12 combined release",
            "Bind exact UTF-8 notes, complete artifact/manifest/checksum/alias hashes",
            "Ordinary development plan approval, code review, protected-source and merge CI remain",
        ],
    );
    release_instruction(
        "export-review",
        "3. **Require every automatic gate.**",
        &[
            "Resolve exact-candidate CI, full public source/history/artifact privacy, honest claim evidence and compiled-product verification",
            "Require the combined live smoke to exercise every included promise end to end",
            "live checks for changed sending, thread creation, App permissions or spending",
            "only within existing approved kit targets/counts, allowlists, App grants, host and spending",
            "Unknown risk, unreadable/missing, failed, stale, fixture, dry-run or uncertain required evidence blocks",
            "automatic release gates, not an additional human export approval",
        ],
    );
    let contract = fs::read_to_string(Path::new(ROOT).join("contracts/release-candidate.v1.md"))
        .expect("release candidate contract");
    let coverage: Vec<_> = contract
        .split("\n\n")
        .map(collapse)
        .filter(|paragraph| paragraph.starts_with("`coverage` in smoke is"))
        .collect();
    assert_eq!(coverage.len(), 1, "one operative smoke coverage rule");
    assert!(coverage[0].contains(
        "A smoke coverage row passes only when its live evidence proves the complete user flow for that promise was exercised end to end on the combined candidate"
    ));
    assert!(coverage[0].contains("A partial check cannot satisfy the row"));
}

#[test]
fn adr0019_automatic_export_and_one_final_approval() {
    // The successor removes export approval; it does not activate shipping.
    release_instruction(
        "export-review",
        "**Activation gate:**",
        &[
            "preparation can happen before cut-over, but shipping requires verified O17 after O16 with their existing authorization, prerequisites and holds intact",
            "This skill authorizes neither step, no live run or publication now",
            "Private-to-public release copying remains stopped except specifically assigned O16 work",
            "`release/openwiz/` stays frozen",
        ],
    );
    release_instruction(
        "export-review",
        "2. **Resolve the two actual decisions.**",
        &[
            "Jake's ship instruction and approval of the exact changelog are the only human release actions",
            "approval may precede ship",
            "Verify the existing private decision comments, author, scope, current revision, hashes and candidate/notes bindings",
            "A supplied flag, invented pointer or old decision for another candidate refuses",
            "Store original ship time before effects",
            "No export-plan, final-diff, mandatory Sol-export, mandatory hands-on/ device or second publish instruction",
        ],
    );
    release_instruction(
        "export-review",
        "4. **Invalidate changed inputs.**",
        &[
            "Recompute bindings when source/build, notes, artifacts, kit or risk changes",
            "Recheck current external holds, permissions and gate inputs before each effect",
            "Keep original ship time across resumes, completed steps and consumed attempts",
            "Return blocked/incomplete",
            "no watcher, poll loop or sleep",
        ],
    );
    release_instruction(
        "export-review",
        "5. **Publish and read back when authorized.**",
        &[
            "only after verified cut-over, both actual decisions and every required passing gate",
            "immutable-release and required-check settings",
            "no new settings approval",
            "no-force-push and version order",
            "Read back the annotated tag/peeled public commit, exact approved notes, complete asset bytes/manifests/checksums/aliases and immutable pre-release state",
            "Partial publication is incomplete",
            "never repeat a potentially consumed write automatically",
            "Historical backfill keeps its own explicit gate",
        ],
    );
    release_instruction(
        "export-review",
        "6. **Verify user delivery and report.**",
        &[
            "normal install/update on an already approved test machine",
            "Stop the clock only after matching installation and remote publication verification",
            "Include all time after the original ship instruction: changelog waits, queue, checks/builds, publication and download/update",
            "report preparation separately",
            "Under 30 minutes meets the light target; otherwise record a miss or block",
        ],
    );
}

// The Rust job must retain the instruction files its new contract checks read.
#[test]
fn adr0019_release_skills_are_kept_for_rust_checks() {
    use std::io::Write;
    use std::process::{Command, Stdio};

    for skill in ["export-review", "live-quick-check"] {
        let path = format!(".claude/skills/{skill}/SKILL.md\n");
        for (args, expected) in [(vec![], "web-build rust\n"), (vec!["--skips", "rust"], "")] {
            let mut child = Command::new("sh")
                .arg(".github/actions/docs-only/classify.sh")
                .args(args)
                .current_dir(ROOT)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .expect("run CI classifier");
            child
                .stdin
                .take()
                .expect("classifier stdin")
                .write_all(path.as_bytes())
                .expect("classify release skill");
            let output = child.wait_with_output().expect("classifier result");
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            assert_eq!(output.stdout, expected.as_bytes(), "{path}");
        }
    }
}

// #1108: the onboarding skill's operative rules, read from its own sections,
// so a reworded skill that drops a gate fails here.
#[test]
fn onboard_keeps_its_gates() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("skills/onboard/SKILL.md")).expect("onboard skill");
    let section = |heading: &str| {
        collapse(
            text.split_once(heading)
                .unwrap_or_else(|| panic!("{heading}"))
                .1
                .split("\n## ")
                .next()
                .expect("section"),
        )
    };
    let rules = section("## Rules for the whole journey\n");
    for required in [
        "Install permission is not work approval.",
        "Only plan-graph's separate spec confirmation and its exact-plan approval let tickets start",
        "Never write, fake or infer an approval, and never ask for a blanket yes to future work.",
        "wait for the user's explicit yes to that list. No yes, no effect.",
        "No prewritten plan.",
        "It is no limit on any later fleet",
    ] {
        assert!(rules.contains(required), "rule: {required}");
    }
    let explain = section("## 1. Explain\n");
    for concept in [
        "**idea**",
        "**grill**",
        "**spec**",
        "**tickets**",
        "**builder**",
        "**reviewer**",
        "**merges**",
    ] {
        assert!(explain.contains(concept), "explanation: {concept}");
    }
    let project = section("## 2. Choose a project\n");
    for required in [
        "**fun, quick ideas**",
        "never a plan",
        "**A new disposable demo repository** (the default)",
        "existing repositories",
        "only after the user's yes",
        "`gh repo create <owner>/<name> --private`",
        "never creates twice",
        "This skill creates nothing in CloudRoom.",
    ] {
        assert!(project.contains(required), "project: {required}");
    }
    assert!(
        section("## 3. Grill\n").contains("4 to 7 small"),
        "grill aims small"
    );
    let agents = section("## 4. Choose the agents\n");
    for required in [
        "never fill one in for the user",
        "**Harness**",
        "**Effort**",
        "Cloud",
        "Local",
        "never copy the engine's location into it",
        "`launch` refuses Local and starts nothing",
        "**both** builder tables",
    ] {
        assert!(agents.contains(required), "agents: {required}");
    }
    let plan = section("## 5. Plan\n");
    for required in [
        "**spec confirmation**",
        "**exact-plan approval**",
        "A reply that asks for a change is not an approval.",
    ] {
        assert!(plan.contains(required), "plan: {required}");
    }
    let launch = section("## 6. Launch\n");
    for required in [
        "`<launch-fleet skill's folder>/scripts/fleet.sh frontier`",
        "`openwiz fleet tick --dry-run --json`",
        "--expect-plan",
        "never retry it by hand",
        "On the user's yes",
        "`--yes --confirm <that digest>`",
        "preview again and ask again",
    ] {
        assert!(launch.contains(required), "launch: {required}");
    }
    // No plan, ticket list or template ships with the skill.
    let dir = Path::new(ROOT).join("skills/onboard");
    let mut files: Vec<String> = tree(&dir)
        .into_iter()
        .filter(|(_, kind)| !kind.is_dir())
        .map(|(path, _)| {
            path.strip_prefix(&dir)
                .expect("inside")
                .to_string_lossy()
                .into_owned()
        })
        .collect();
    files.sort();
    assert_eq!(
        files,
        ["SKILL.md", "agents/openai.yaml", "scripts/onboard.py"]
    );
}

// #1108: the recorded onboarding journey runs in the checks binary, so CI's
// always-run set executes it on every run.
#[test]
fn onboard_journey_fixtures_pass() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/onboard/test_journey.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the onboarding journey");
    assert!(
        result.status.success(),
        "onboarding journey failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

// #1109: the install skill follows the confirmed order, read from its own
// numbered sections, and keeps its gates; a reworded skill that drops one fails.
#[test]
fn install_keeps_its_order_and_gates() {
    let text =
        fs::read_to_string(Path::new(ROOT).join("skills/install/SKILL.md")).expect("install skill");
    let steps: Vec<String> = text
        .lines()
        .filter_map(|line| line.strip_prefix("## "))
        .filter(|rest| rest.starts_with(|c: char| c.is_ascii_digit()))
        .map(|rest| rest.split_once(". ").expect("numbered step").1.to_string())
        .collect();
    assert_eq!(
        steps,
        [
            "Preflight",
            "Verified install",
            "Setup and connections",
            "Engine",
            "Explain",
            "First fleet"
        ],
        "the confirmed order"
    );
    let all = collapse(&text);
    for required in [
        "Install permission is not work approval.",
        "Every effect is shown first, then waits for a yes.",
        "Use the agent CLI's JSON, never its screen.",
        "no Rust, Cargo, Node or npm",
        "OpenWiz is free",
        "No referral is applied.",
        "never guess one",
        "Removing OpenWiz from this computer does not revoke",
        "the `onboard` skill",
    ] {
        assert!(all.contains(required), "install skill: {required}");
    }
    let dir = Path::new(ROOT).join("skills/install");
    let mut files: Vec<String> = tree(&dir)
        .into_iter()
        .filter(|(_, kind)| !kind.is_dir())
        .map(|(path, _)| {
            path.strip_prefix(&dir)
                .expect("inside")
                .to_string_lossy()
                .into_owned()
        })
        .collect();
    files.sort();
    assert_eq!(files, ["SKILL.md", "agents/openai.yaml"]);
}

// #1109 (IF9): one install line. The install skill, the public guide and the
// README quote the same line, and the setup page names the same upgrade
// destination. The site lane's own tests (apps/site/test/site.test.mjs) pin
// these same literals in the landing's copied prompt and its upgrade link:
// the rust lane keeps no site files, so each lane checks its side against
// the one literal.
#[test]
fn one_install_line_everywhere() {
    let read = |path: &str| fs::read_to_string(Path::new(ROOT).join(path)).expect(path);
    let line = "Install OpenWiz from github.com/openwizdev/openwiz";
    for path in ["skills/install/SKILL.md", "docs/install.md", "README.md"] {
        assert!(
            read(path).contains(&format!("> {line}\n")),
            "{path} quotes the install line"
        );
    }
    assert!(
        read("apps/web/src/components/Setup.tsx")
            .contains("export const CLOUDROOM_UPGRADE = 'cloudroom.dev/pricing';")
    );
    let guide = read("docs/install.md");
    assert!(guide.contains("](https://cloudroom.dev/pricing)"));
}

// #1109: the cold-consumer install journey and the live kit's offline dry run
// run in the checks binary, so CI's always-run set executes them every run.
#[test]
fn install_journey_and_live_kit_pass() {
    for script in [
        "tools/install/tests/journey/test_journey.py",
        "tools/install/live-kit-test.py",
        "tools/install/tests/first-hour/test_journey.py",
        "tools/install/tests/first-hour/test_kit.py",
    ] {
        let result = std::process::Command::new("python3")
            .args(["-I", script])
            .current_dir(ROOT)
            .output()
            .expect("run python");
        assert!(
            result.status.success(),
            "{script} failed: {}{}",
            String::from_utf8_lossy(&result.stdout),
            String::from_utf8_lossy(&result.stderr)
        );
    }
}
