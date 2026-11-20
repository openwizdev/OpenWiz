//! OpenWiz integration with the pinned WizSkills install (#555, #814).
//! Keep harness links, local release/installation contracts and wrappers
//! without a green CI replacement. Portable checks belong to WizSkills;
//! each test's disposition is in #814's TV12 ledger, in the private records (#1303).

use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

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

/// The whole body of a skill that is not written yet.
const STUB: &str = "**Not written yet.** This file only fixes the skill's name and path; \
its build ticket writes it. Stop here, and tell whoever invoked it that this skill \
is not ready.";

fn problems(root: &Path) -> Vec<String> {
    let mut out = Vec::new();
    check_links(root, &mut out);
    out
}

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
    root
}

fn write(root: &Path, rel: &str, text: &str) {
    let path = root.join(rel);
    crate::dirs::private_dir_all(path.parent().expect("parent")).expect("dir");
    fs::write(path, text).expect("write");
}

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

fn assert_clean(root: &Path) {
    let found = problems(root);
    assert!(
        found.is_empty(),
        "expected no problems, got:\n{}",
        found.join("\n")
    );
}

fn assert_catches(root: &Path, expected: &str) {
    let found = problems(root);
    assert!(
        found.iter().any(|p| p.contains(expected)),
        "expected a problem containing {expected:?}, got:\n{}",
        found.join("\n")
    );
}

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
}

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

#[test]
fn setup_onboard_contract_passes() {
    let result = std::process::Command::new("python3")
        .args([
            "-I",
            "tools/install/tests/setup-onboard-contract/test_contract.py",
        ])
        .current_dir(ROOT)
        .output()
        .expect("run the setup-onboard contract checks");
    assert!(
        result.status.success(),
        "setup-onboard contract checks failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_init_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/init/test_init.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the init runtime proofs");
    assert!(
        result.status.success(),
        "init runtime proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_login_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "-B", "tools/install/setup/test_github_login.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the setup GitHub login proofs");
    assert!(
        result.status.success(),
        "setup GitHub login proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn setup_onboard_journey_passes() {
    let result = std::process::Command::new("python3")
        .args(["-I", "tools/install/tests/first-hour/test_first_merge.py"])
        .current_dir(ROOT)
        .output()
        .expect("run the first-merge journey and kit proofs");
    assert!(
        result.status.success(),
        "first-merge journey and kit proofs failed: {}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

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
