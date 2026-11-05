//! Spec 2's B3 (ClosedWiz#119): the GitHub writes, and S2-3 for GitHub:
//! only allowlisted writes.
//!
//! - **Here, the static check** of the writes module's part of the
//!   allowlist: every form it allows is written out by hand below (each
//!   write, then the read that confirms it, and a close's read before it:
//!   only an issue is closed), every [`Write`] builds exactly
//!   those, near misses are all refused, bad arguments can't be built, and
//!   its source names no forbidden word.
//! - **`b3_fake`, the recording fake `gh`:** each write makes exactly its
//!   call and its read back, and nothing else; a write that fails is never
//!   read back; a write is confirmed only when its read back shows it.
//!
//! **Fixtures only.** Every value is synthetic; no test proves live
//! behaviour (that is B6, #122).

use std::fs;
use std::num::NonZeroU64;
use std::path::Path;

use openwiz_adapter_github::allowlist::{self, Invocation};
use openwiz_adapter_github::writes::{self, Body, LABEL_MAX_LEN, Label, Write};
use openwiz_core::fleet::model::Commit;
use openwiz_core::messaging::MAX_TEXT_BYTES;

#[path = "b3_fake.rs"]
mod fake;

/// The synthetic head of the merge form.
const HEAD: &str = "0123456789abcdef0123456789abcdef01234567";

/// The one GraphQL read: whether a pull request's base has a merge queue.
/// A query, never a mutation; the repository is `gh`'s own placeholders.
const QUEUE_QUERY: &str = "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled}}}";

/// Every form the writes module allows, written out by hand: each write,
/// then the read that confirms it; a close first reads the number's URL,
/// so that only an issue is closed (`gh issue close` also closes a pull
/// request); a merge first reads whether the base has a merge queue, so
/// that a merge is never queued (`gh pr merge` then turns on auto-merge).
const ALLOWED: &[&[&str]] = &[
    &["issue", "comment", "7", "--body", "Synthetic"],
    &["issue", "view", "7", "--json", "comments"],
    &["pr", "comment", "8", "--body", "Synthetic"],
    &["pr", "view", "8", "--json", "comments"],
    &["issue", "edit", "7", "--add-label", "held"],
    &["issue", "view", "7", "--json", "labels"],
    &["issue", "edit", "7", "--remove-label", "held"],
    &["issue", "view", "7", "--json", "labels"],
    &["issue", "view", "7", "--json", "url"],
    &["issue", "close", "7"],
    &["issue", "view", "7", "--json", "state"],
    &[
        "api",
        "graphql",
        "-f",
        QUEUE_QUERY,
        "-F",
        "owner={owner}",
        "-F",
        "repo={repo}",
        "-F",
        "number=8",
    ],
    &[
        "pr",
        "merge",
        "8",
        "--merge",
        "--match-head-commit",
        HEAD,
        "--body",
        "Synthetic",
    ],
    &["pr", "view", "8", "--json", "state,mergeCommit,headRefOid"],
];

fn n(number: u64) -> NonZeroU64 {
    NonZeroU64::new(number).expect("not zero")
}

fn body(text: &str) -> Body {
    Body::parse(text).expect("a valid body")
}

fn label(name: &str) -> Label {
    Label::parse(name).expect("a valid label")
}

/// One of each write, with the values of [`ALLOWED`]. The `match` makes a
/// new kind of write a compile error here, as a reminder to add its forms.
fn every_write() -> Vec<Write> {
    let all = vec![
        Write::IssueComment {
            issue: n(7),
            body: body("Synthetic"),
        },
        Write::PrComment {
            pr: n(8),
            body: body("Synthetic"),
        },
        Write::AddLabel {
            issue: n(7),
            label: label("held"),
        },
        Write::RemoveLabel {
            issue: n(7),
            label: label("held"),
        },
        Write::CloseIssue { issue: n(7) },
        Write::Merge {
            pr: n(8),
            head: Commit::parse(HEAD).expect("a commit"),
            body: body("Synthetic"),
        },
    ];
    for write in &all {
        match write {
            Write::IssueComment { .. }
            | Write::PrComment { .. }
            | Write::AddLabel { .. }
            | Write::RemoveLabel { .. }
            | Write::CloseIssue { .. }
            | Write::Merge { .. } => {}
        }
    }
    all
}

fn owned(forms: &[&[&str]]) -> Vec<Vec<String>> {
    forms
        .iter()
        .map(|form| form.iter().map(|w| (*w).to_owned()).collect())
        .collect()
}

fn words(argv: &[String]) -> Vec<&str> {
    argv.iter().map(String::as_str).collect()
}

#[test]
fn github_write_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 6] = [
        (
            "bad_arguments_cannot_be_built_so_nothing_can_run",
            bad_arguments_cannot_be_built_so_nothing_can_run,
        ),
        (
            "each_form_takes_any_valid_value_as_one_argument",
            each_form_takes_any_valid_value_as_one_argument,
        ),
        (
            "every_write_and_its_read_back_is_exactly_a_form_written_out_here",
            every_write_and_its_read_back_is_exactly_a_form_written_out_here,
        ),
        (
            "the_module_and_the_whole_allowlist_allow_each_form",
            the_module_and_the_whole_allowlist_allow_each_form,
        ),
        (
            "the_module_refuses_every_near_miss",
            the_module_refuses_every_near_miss,
        ),
        (
            "the_near_miss_check_catches_a_planted_loose_allowlist",
            the_near_miss_check_catches_a_planted_loose_allowlist,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: b3_writes::{name}");
        proof();
    }
}

fn every_write_and_its_read_back_is_exactly_a_form_written_out_here() {
    let built: Vec<Vec<String>> = every_write().iter().flat_map(|w| w.calls()).collect();
    assert_eq!(built, owned(ALLOWED));
}

fn the_module_and_the_whole_allowlist_allow_each_form() {
    for form in ALLOWED {
        assert!((writes::ALLOWLIST.allows)(form), "the module: {form:?}");
        assert!(allowlist::allowed(form), "the allowlist: {form:?}");
        assert_eq!(
            Invocation::new(form).as_ref().map(Invocation::argv),
            Some(&owned(&[form])[0][..]),
            "{form:?}"
        );
    }
}

/// The same forms with other values: any issue or pull request number,
/// any valid label, any valid text (a leading dash, a line break, quotes,
/// a `$`, non-ASCII), byte for byte as one argument.
fn each_form_takes_any_valid_value_as_one_argument() {
    let texts = [
        "-x",
        "--help",
        "line one\nline two\n",
        "a'b\"c $HOME `x` \\",
        "Ünïcødé ✓",
        &"a".repeat(MAX_TEXT_BYTES),
    ];
    let mut forms: Vec<Write> = Vec::new();
    for text in texts {
        forms.push(Write::IssueComment {
            issue: n(1),
            body: body(text),
        });
        forms.push(Write::PrComment {
            pr: n(u64::MAX),
            body: body(text),
        });
        forms.push(Write::Merge {
            pr: n(1234567890),
            head: Commit::parse(HEAD).unwrap(),
            body: body(text),
        });
    }
    for name in [
        "needs-info",
        "ready-for-agent",
        "a",
        "0",
        &"a".repeat(LABEL_MAX_LEN),
    ] {
        forms.push(Write::AddLabel {
            issue: n(10),
            label: label(name),
        });
        forms.push(Write::RemoveLabel {
            issue: n(10),
            label: label(name),
        });
    }
    forms.push(Write::CloseIssue { issue: n(u64::MAX) });
    for write in forms {
        for argv in write.calls() {
            assert!(
                (writes::ALLOWLIST.allows)(&words(&argv)),
                "{write:?}: {argv:?}"
            );
        }
        let argv = write.argv();
        let (len, last): (usize, &[&str]) = match &write {
            Write::IssueComment { body, .. } | Write::PrComment { body, .. } => {
                (5, &["--body", body.as_str()])
            }
            Write::Merge { body, .. } => (8, &["--body", body.as_str()]),
            Write::AddLabel { label, .. } => (5, &["--add-label", label.as_str()]),
            Write::RemoveLabel { label, .. } => (5, &["--remove-label", label.as_str()]),
            Write::CloseIssue { issue } => (3, &["close", &issue.to_string()]),
        };
        assert_eq!(argv.len(), len, "{write:?}: {argv:?}");
        assert!(
            argv.ends_with(&owned(&[last])[0]),
            "{write:?}: one argument each: {argv:?}"
        );
    }
}

/// Flags and words no form may carry, whatever the place.
const EXTRA: &[&[&str]] = &[
    &["--delete-branch"],
    &["-d"],
    &["--admin"],
    &["--auto"],
    &["--disable-auto"],
    &["--squash"],
    &["--rebase"],
    &["--merge"],
    &["--force"],
    &["--edit-last"],
    &["--delete-last"],
    &["--create-if-none"],
    &["--yes"],
    &["--web"],
    &["-w"],
    &["--editor"],
    &["-e"],
    &["--repo", "synthetic/repo"],
    &["-R", "synthetic/repo"],
    &["--body-file", "-"],
    &["-F", "-"],
    &["--body", "Synthetic"],
    &["-b", "Synthetic"],
    &["--comment", "Synthetic"],
    &["-c", "Synthetic"],
    &["--reason", "not planned"],
    &["-r", "completed"],
    &["--subject", "Synthetic"],
    &["-t", "Synthetic"],
    &["--author-email", "synthetic@example.invalid"],
    &["--match-head-commit", HEAD],
    &["--add-label", "held"],
    &["--remove-label", "held"],
    &["--jq", "."],
    &["-q", "."],
    &["--template", "{{.}}"],
    &["--json", "body"],
    &["--comments"],
    &["--"],
    &["Synthetic"],
    &["7"],
    &[""],
];

/// Numbers that are not one canonical, positive whole number.
const BAD_NUMBERS: &[&str] = &[
    "",
    "0",
    "00",
    "07",
    "-7",
    "+7",
    "7.0",
    "7e0",
    " 7",
    "7 ",
    "0x7",
    "#7",
    "seven",
    "\u{0667}",
    "18446744073709551616",
    "99999999999999999999",
];

/// Commits that are not 40 lowercase hex digits.
const BAD_COMMITS: &[&str] = &[
    "",
    "HEAD",
    "main",
    "0123456789ABCDEF0123456789ABCDEF01234567",
    "0123456789abcdef0123456789abcdef0123456",
    "0123456789abcdef0123456789abcdef012345678",
    "g123456789abcdef0123456789abcdef01234567",
    " 0123456789abcdef0123456789abcdef0123456",
    "--delete-branch",
];

/// Label names that could be read as a flag, several labels, or another
/// label.
const BAD_LABELS: &[&str] = &[
    "",
    "-held",
    "--held",
    "held,needs-info",
    ",",
    "Held",
    "HELD",
    "held ",
    " held",
    "needs info",
    "held\n",
    "held\t",
    "\"held\"",
    "held'",
    "h\u{e9}ld",
    "held\u{0}",
    "held=1",
    "held/1",
    "held_1",
    "held.1",
];

/// Texts send's rules refuse.
fn bad_bodies() -> Vec<String> {
    vec![
        String::new(),
        " ".to_owned(),
        "\n\t \r".to_owned(),
        "a\u{0}b".to_owned(),
        "a".repeat(MAX_TEXT_BYTES + 1),
    ]
}

/// `form` with the argument at `at` replaced by `with`.
fn replaced(form: &[&str], at: usize, with: &str) -> Vec<String> {
    let mut argv: Vec<String> = form.iter().map(|w| (*w).to_owned()).collect();
    argv[at] = with.to_owned();
    argv
}

/// Every near miss of the allowed forms, each with why it is one.
fn near_misses() -> Vec<(String, Vec<String>)> {
    let mut misses = Vec::new();
    for form in ALLOWED {
        let form_owned: Vec<String> = form.iter().map(|w| (*w).to_owned()).collect();
        // Too short.
        for len in 0..form.len() {
            misses.push((format!("{form:?} cut to {len}"), form_owned[..len].to_vec()));
        }
        // Anything extra, at every place.
        for extra in EXTRA {
            for at in 0..=form.len() {
                let mut argv = form_owned.clone();
                for (i, word) in extra.iter().enumerate() {
                    argv.insert(at + i, (*word).to_owned());
                }
                misses.push((format!("{form:?} with {extra:?} at {at}"), argv));
            }
        }
        // Two neighbours swapped (never the same word twice).
        for at in 0..form.len() - 1 {
            if form[at] != form[at + 1] {
                let mut argv = form_owned.clone();
                argv.swap(at, at + 1);
                misses.push((format!("{form:?} with {at} swapped"), argv));
            }
        }
        // Each word with another case, or a space around it.
        for (at, word) in form.iter().enumerate() {
            for other in [
                word.to_uppercase(),
                format!(" {word}"),
                format!("{word} "),
                format!("{word}\n"),
            ] {
                if other != *word && !(at == form.len() - 1 && form[at] == "Synthetic") {
                    misses.push((
                        format!("{form:?} with {other:?} at {at}"),
                        replaced(form, at, &other),
                    ));
                }
            }
        }
        // Bad values where each value goes.
        let number_at = form
            .iter()
            .position(|w| w.starts_with("number="))
            .unwrap_or(2);
        for bad in BAD_NUMBERS {
            let bad = if number_at == 2 {
                (*bad).to_owned()
            } else {
                format!("number={bad}")
            };
            misses.push((
                format!("{form:?} with the number {bad:?}"),
                replaced(form, number_at, &bad),
            ));
        }
        if let Some(at) = form.iter().position(|w| *w == HEAD) {
            for bad in BAD_COMMITS {
                misses.push((
                    format!("{form:?} with the commit {bad:?}"),
                    replaced(form, at, bad),
                ));
            }
        }
        if form[1] == "edit" {
            for bad in BAD_LABELS {
                misses.push((
                    format!("{form:?} with the label {bad:?}"),
                    replaced(form, 4, bad),
                ));
            }
        }
        if form.contains(&"--body") {
            for bad in bad_bodies() {
                misses.push((
                    format!("{form:?} with a bad text of {} bytes", bad.len()),
                    replaced(form, form.len() - 1, &bad),
                ));
            }
        }
    }
    // Other writes and other reads, near the allowed ones.
    let head = HEAD;
    for other in [
        &["issue", "delete", "7"][..],
        &["issue", "delete", "7", "--yes"],
        &["issue", "reopen", "7"],
        &["issue", "lock", "7"],
        &["issue", "unlock", "7"],
        &["issue", "pin", "7"],
        &["issue", "transfer", "7", "synthetic/repo"],
        &["issue", "develop", "7"],
        &[
            "issue",
            "create",
            "--title",
            "Synthetic",
            "--body",
            "Synthetic",
        ],
        &["issue", "edit", "7", "--title", "Synthetic"],
        &["issue", "edit", "7", "--body", "Synthetic"],
        &["issue", "edit", "7", "--add-assignee", "synthetic"],
        &["issue", "edit", "7", "--milestone", "0.0.0"],
        &[
            "issue",
            "edit",
            "7",
            "--add-label",
            "held",
            "--remove-label",
            "ready-for-agent",
        ],
        &["issue", "edit", "7", "8", "--add-label", "held"],
        &["issue", "close", "7", "--comment", "Synthetic"],
        &["issue", "close", "7", "--reason", "not planned"],
        &["issue", "comment", "7", "--body=Synthetic"],
        &["issue", "comment", "7", "-b", "Synthetic"],
        &[
            "issue",
            "comment",
            "7",
            "--edit-last",
            "--body",
            "Synthetic",
        ],
        &["issue", "comment", "7", "--delete-last", "--yes"],
        &[
            "issue",
            "comment",
            "https://github.invalid/synthetic/repo/issues/7",
            "--body",
            "Synthetic",
        ],
        &["pr", "comment", "8", "--edit-last", "--body", "Synthetic"],
        &["pr", "close", "8"],
        &["pr", "close", "8", "--delete-branch"],
        &["pr", "reopen", "8"],
        &["pr", "ready", "8"],
        &["pr", "ready", "8", "--undo"],
        &["pr", "review", "8", "--approve"],
        &["pr", "edit", "8", "--add-label", "held"],
        &["pr", "edit", "8", "--base", "release-0"],
        &["pr", "update-branch", "8"],
        &["pr", "checkout", "8"],
        &["pr", "merge", "8"],
        &["pr", "merge", "8", "--merge"],
        &["pr", "merge", "8", "--merge", "--match-head-commit", head],
        &["pr", "merge", "8", "--merge", "--body", "Synthetic"],
        &[
            "pr",
            "merge",
            "8",
            "--squash",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--rebase",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--auto",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--admin",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
            "--delete-branch",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
            "-d",
        ],
        &[
            "pr",
            "merge",
            "8",
            "--merge",
            "--match-head-commit=0123456789abcdef0123456789abcdef01234567",
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "pr",
            "merge",
            "room/synthetic-branch",
            "--merge",
            "--match-head-commit",
            head,
            "--body",
            "Synthetic",
        ],
        &[
            "api",
            "-X",
            "POST",
            "repos/{owner}/{repo}/issues/7/comments",
            "-f",
            "body=Synthetic",
        ],
        &["api", "-X", "PUT", "repos/{owner}/{repo}/pulls/8/merge"],
        &[
            "api",
            "-X",
            "DELETE",
            "repos/{owner}/{repo}/git/refs/heads/synthetic",
        ],
        &["api", "graphql", "-f", "query=synthetic"],
        &[
            "api",
            "graphql",
            "-f",
            "query=mutation{x}",
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
        ],
        &["api", "graphql", "-f", QUEUE_QUERY],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner=synthetic",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo=synthetic",
            "-F",
            "number=8",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-f",
            "number=8",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=@-",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
            "--hostname",
            "github.invalid",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
            "-X",
            "POST",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
            "--input",
            "-",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
            "-H",
            "X:y",
        ],
        &[
            "api",
            "graphql",
            "-f",
            QUEUE_QUERY,
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
            "--paginate",
        ],
        &[
            "api",
            "graphql",
            "-f",
            "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled headRefOid}}}",
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=8",
        ],
        &["api", "repos/{owner}/{repo}/pulls/8"],
        &["label", "create", "held"],
        &["label", "delete", "held", "--yes"],
        &["label", "edit", "held", "--name", "synthetic"],
        &["repo", "delete", "--yes"],
        &["repo", "edit", "--default-branch", "synthetic"],
        &["release", "create", "v0.0.0"],
        &["workflow", "run", "ci.yml"],
        &["run", "rerun", "1"],
        &["issue", "view", "7"],
        &["issue", "view", "7", "--json"],
        &["issue", "view", "7", "--json", "comments,body"],
        &["issue", "view", "7", "--json", "body"],
        &["issue", "view", "7", "--json", "labels", "--jq", ".labels"],
        &["issue", "view", "7", "--comments"],
        &["issue", "view", "7", "--json", "state", "--web"],
        &["pr", "view", "8", "--json", "state"],
        &["pr", "view", "8", "--json", "state,headRefOid,mergeCommit"],
        &[
            "pr",
            "view",
            "8",
            "--json",
            "state,mergeCommit,headRefOid,body",
        ],
        &["pr", "view", "8", "--json", "labels"],
        &[
            "issue",
            "view",
            "7",
            "--json",
            "state,mergeCommit,headRefOid",
        ],
        &["issue", "view", "7", "--json", "url,state"],
        &["issue", "view", "7", "--json", "state,url"],
        &["pr", "view", "8", "--json", "url"],
        &["issue", "close", "7", "--duplicate-of", "8"],
        &["pr", "view", "8", "--json", "comments", "--comments"],
    ] {
        misses.push((
            format!("another command {other:?}"),
            other.iter().map(|w| (*w).to_owned()).collect(),
        ));
    }
    misses
}

/// Whether `argv` asks GitHub to change something: a subcommand no read
/// module can allow.
fn is_a_write(argv: &[String]) -> bool {
    let read = |sub: &str| matches!(sub, "view" | "list" | "checks" | "status" | "diff");
    match argv {
        [first, ..] if first == "api" => false,
        [_, sub, ..] => !read(sub) && !argv.iter().any(|w| w == "--version"),
        _ => false,
    }
}

/// The near misses `allows` lets through, and how many there are.
fn near_misses_allowed_by(allows: fn(&[&str]) -> bool, whole: bool) -> (Vec<String>, usize) {
    let allowed = owned(ALLOWED);
    let mut wrongly = Vec::new();
    let misses = near_misses();
    for (why, argv) in &misses {
        if allowed.contains(argv) {
            continue;
        }
        let words = words(argv);
        if allows(&words) {
            wrongly.push(format!("the module allows {why}: {argv:?}"));
        }
        // No module of the allowlist may allow a write this one doesn't:
        // the others only read.
        if whole && is_a_write(argv) && allowlist::allowed(&words) {
            wrongly.push(format!("the allowlist allows {why}: {argv:?}"));
        }
        if whole && is_a_write(argv) && Invocation::new(&words).is_some() {
            wrongly.push(format!("an invocation was built for {why}: {argv:?}"));
        }
    }
    (wrongly, misses.len())
}

fn the_module_refuses_every_near_miss() {
    let (wrongly, count) = near_misses_allowed_by(writes::ALLOWLIST.allows, true);
    assert_eq!(count, 4571, "every near miss is generated");
    assert!(
        wrongly.is_empty(),
        "{} of {count} near misses allowed:\n{}",
        wrongly.len(),
        wrongly.join("\n")
    );
}

/// The near-miss check catches each kind of loose allowlist, planted.
fn the_near_miss_check_catches_a_planted_loose_allowlist() {
    fn exact(argv: &[&str]) -> bool {
        ALLOWED.contains(&argv)
    }
    fn any_tail(argv: &[&str]) -> bool {
        ALLOWED.iter().any(|form| argv.starts_with(form))
    }
    fn any_number(argv: &[&str]) -> bool {
        ALLOWED.iter().any(|form| {
            form.len() == argv.len()
                && form
                    .iter()
                    .zip(argv)
                    .enumerate()
                    .all(|(i, (f, a))| i == 2 || f == a)
        })
    }
    fn any_label(argv: &[&str]) -> bool {
        ALLOWED.iter().any(|form| {
            form.len() == argv.len()
                && form
                    .iter()
                    .zip(argv)
                    .enumerate()
                    .all(|(i, (f, a))| (i == 4 && form[1] == "edit") || f == a)
        })
    }
    fn any_text(argv: &[&str]) -> bool {
        ALLOWED.iter().any(|form| {
            form.len() == argv.len()
                && form
                    .iter()
                    .zip(argv)
                    .enumerate()
                    .all(|(i, (f, a))| (i == form.len() - 1 && *f == "Synthetic") || f == a)
        })
    }
    fn any_commit(argv: &[&str]) -> bool {
        ALLOWED.iter().any(|form| {
            form.len() == argv.len() && form.iter().zip(argv).all(|(f, a)| *f == HEAD || f == a)
        })
    }
    // Exactly the forms, and nothing else: the check finds nothing.
    assert_eq!(near_misses_allowed_by(exact, false).0, Vec::<String>::new());
    for (why, loose) in [
        ("anything after a form", any_tail as fn(&[&str]) -> bool),
        ("any number", any_number),
        ("any label", any_label),
        ("any text", any_text),
        ("any commit", any_commit),
    ] {
        assert!(
            !near_misses_allowed_by(loose, false).0.is_empty(),
            "missed: {why}"
        );
    }
}

fn bad_arguments_cannot_be_built_so_nothing_can_run() {
    for bad in BAD_LABELS {
        assert_eq!(Label::parse(bad), None, "the label {bad:?}");
    }
    assert_eq!(Label::parse(&"a".repeat(LABEL_MAX_LEN + 1)), None);
    for bad in bad_bodies() {
        assert_eq!(Body::parse(&bad), None, "a text of {} bytes", bad.len());
    }
    for bad in BAD_COMMITS {
        assert_eq!(Commit::parse(bad), None, "the commit {bad:?}");
    }
    assert_eq!(NonZeroU64::new(0), None, "no issue or pull request 0");
    for good in [
        "held",
        "needs-info",
        "ready-for-agent",
        "wontfix",
        "a1-b2",
        "0",
    ] {
        assert_eq!(
            Label::parse(good).map(|l| l.as_str().to_owned()),
            Some(good.to_owned())
        );
    }
    for good in ["Synthetic", "-x", " a ", &"a".repeat(MAX_TEXT_BYTES)] {
        assert_eq!(
            Body::parse(good).map(|b| b.as_str().to_owned()),
            Some(good.to_owned())
        );
    }
}

/// Words `writes.rs` must never pass to `gh`, as they appear in Rust: a
/// quoted argument.
const FORBIDDEN: &[&str] = &[
    "\"--delete-branch\"",
    "\"-d\"",
    "\"--admin\"",
    "\"--auto\"",
    "\"--disable-auto\"",
    "\"--squash\"",
    "\"--rebase\"",
    "\"--force\"",
    "\"--edit-last\"",
    "\"--delete-last\"",
    "\"--create-if-none\"",
    "\"--yes\"",
    "\"--web\"",
    "\"--editor\"",
    "\"--repo\"",
    "\"-R\"",
    "\"--body-file\"",
    "\"--comment\"",
    "\"--reason\"",
    "\"--subject\"",
    "\"--jq\"",
    "\"--template\"",
    "mutation",
    "\"-X\"",
    "\"--method\"",
    "\"--input\"",
    "\"--hostname\"",
    "\"--paginate\"",
    "\"delete\"",
    "\"reopen\"",
    "\"lock\"",
    "\"transfer\"",
    "\"create\"",
    "\"review\"",
    "\"ready\"",
    "\"update-branch\"",
    "\"checkout\"",
    "\"label\"",
    "\"repo\"",
    "\"release\"",
    "\"workflow\"",
    "\"run\"",
    "--delete-branch",
    "--admin",
    "--auto",
    "--edit-last",
    "--delete-last",
    "--force",
];

/// What the source rule finds wrong in `text`.
fn source_problems(text: &str) -> Vec<String> {
    let mut problems: Vec<String> = FORBIDDEN
        .iter()
        .filter(|word| text.contains(*word))
        .map(|word| format!("names {word}"))
        .collect();
    // One way to build a call: an allowlisted invocation, run by the
    // supplied executor, with no direct process-runner bypass.
    for (needle, times) in [
        ("Invocation::new(", 1),
        ("executor.run(", 1),
        ("process::run(", 0),
    ] {
        let n = text.matches(needle).count();
        if n != times {
            problems.push(format!("names {needle:?} {n} times, not {times}"));
        }
    }
    // `gh api graphql` only in the one merge-queue read, each word once.
    for word in ["\"api\"", "\"graphql\""] {
        let n = text.matches(word).count();
        if n != 1 {
            problems.push(format!("names {word} {n} times, not once"));
        }
        let queue_read = text
            .split("const READ_MERGE_QUEUE: Form = &[")
            .nth(1)
            .and_then(|rest| rest.split("];").next())
            .unwrap_or_default();
        if !queue_read.contains(word) {
            problems.push(format!("names {word} outside the merge-queue read"));
        }
    }
    for word in ["for_test", "Command::new", "std::process", ".spawn("] {
        if text.contains(word) {
            problems.push(format!("names {word:?}"));
        }
    }
    problems
}

const WRITES: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../crates/adapters/github/src/writes.rs"
);

#[test]
fn the_writes_source_names_no_forbidden_word() {
    let text = fs::read_to_string(WRITES).expect("writes.rs");
    assert_eq!(source_problems(&text), Vec::<String>::new());
}

/// The source rule catches each break it exists for, planted in a copy of
/// the real source.
#[test]
fn the_source_rule_catches_a_planted_break() {
    let real = fs::read_to_string(WRITES).expect("writes.rs");
    assert!(Path::new(WRITES).is_file());
    let plant = |from: &str, to: &str| {
        assert_eq!(
            real.matches(from).count(),
            1,
            "{from:?} is in writes.rs once"
        );
        real.replacen(from, to, 1)
    };
    for (why, planted) in [
        (
            "a branch deleted after a merge",
            plant(
                "Is(\"--merge\")",
                "Is(\"--merge\"), Is(\"--delete-branch\")",
            ),
        ),
        (
            "a forced merge",
            plant("Is(\"--merge\")", "Is(\"--merge\"), Is(\"--admin\")"),
        ),
        (
            "a comment edited",
            plant(
                "const ISSUE_COMMENT: Form = &[",
                "const ISSUE_COMMENT: Form = &[Is(\"--edit-last\"), ",
            ),
        ),
        (
            "another repository",
            plant("Is(\"--merge\")", "Is(\"--merge\"), Is(\"--repo\")"),
        ),
        (
            "a call made around the allowlist",
            plant("Invocation::new(", "Invocation::for_test("),
        ),
        (
            "a GraphQL write",
            plant(
                "const READ_MERGE_QUEUE: Form = &[",
                "const READ_MERGE_QUEUE: Form = &[Is(\"mutation\"), ",
            ),
        ),
        (
            "a second api call",
            plant(
                "const CLOSE_ISSUE: Form = &[",
                "const CLOSE_ISSUE: Form = &[Is(\"api\"), ",
            ),
        ),
        (
            "a second runner",
            plant(
                "executor.run(",
                "std::process::Command::new(program).spawn(); executor.run(",
            ),
        ),
        (
            "a personal runner replacing the supplied executor",
            plant("executor.run(", "process::run(program, "),
        ),
        (
            "a personal runner alongside the supplied executor",
            plant(
                "executor.run(",
                "process::run(program, invocation, deadline); executor.run(",
            ),
        ),
    ] {
        assert!(!source_problems(&planted).is_empty(), "missed: {why}");
    }
}
