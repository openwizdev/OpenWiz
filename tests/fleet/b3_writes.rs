use std::fs;
use std::num::NonZeroU64;

use openwiz_adapter_github::allowlist::{self, Invocation};
use openwiz_adapter_github::writes::{self, Body, LABEL_MAX_LEN, Label, Write};
use openwiz_core::fleet::model::Commit;
use openwiz_core::messaging::MAX_TEXT_BYTES;

#[path = "b3_fake.rs"]
mod fake;

const HEAD: &str = "0123456789abcdef0123456789abcdef01234567";

const QUEUE_QUERY: &str = "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled}}}";

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
    let cases: [(&str, fn()); 5] = [
        (
            "bad_arguments_cannot_be_built_so_nothing_can_run",
            bad_arguments_cannot_be_built_so_nothing_can_run,
        ),
        (
            "each_form_takes_any_valid_value_as_one_argument",
            each_form_takes_any_valid_value_as_one_argument,
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

fn bad_bodies() -> Vec<String> {
    vec![
        String::new(),
        " ".to_owned(),
        "\n\t \r".to_owned(),
        "a\u{0}b".to_owned(),
        "a".repeat(MAX_TEXT_BYTES + 1),
    ]
}

fn replaced(form: &[&str], at: usize, with: &str) -> Vec<String> {
    let mut argv: Vec<String> = form.iter().map(|w| (*w).to_owned()).collect();
    argv[at] = with.to_owned();
    argv
}

fn near_misses() -> Vec<(String, Vec<String>)> {
    let mut misses = Vec::new();
    for form in ALLOWED {
        let form_owned: Vec<String> = form.iter().map(|w| (*w).to_owned()).collect();
        for len in 0..form.len() {
            misses.push((format!("{form:?} cut to {len}"), form_owned[..len].to_vec()));
        }
        for extra in EXTRA {
            for at in 0..=form.len() {
                let mut argv = form_owned.clone();
                for (i, word) in extra.iter().enumerate() {
                    argv.insert(at + i, (*word).to_owned());
                }
                misses.push((format!("{form:?} with {extra:?} at {at}"), argv));
            }
        }
        for at in 0..form.len() - 1 {
            if form[at] != form[at + 1] {
                let mut argv = form_owned.clone();
                argv.swap(at, at + 1);
                misses.push((format!("{form:?} with {at} swapped"), argv));
            }
        }
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

fn is_a_write(argv: &[String]) -> bool {
    let read = |sub: &str| matches!(sub, "view" | "list" | "checks" | "status" | "diff");
    match argv {
        [first, ..] if first == "api" => false,
        [_, sub, ..] => !read(sub) && !argv.iter().any(|w| w == "--version"),
        _ => false,
    }
}

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

fn source_problems(text: &str) -> Vec<String> {
    let mut problems: Vec<String> = FORBIDDEN
        .iter()
        .filter(|word| text.contains(*word))
        .map(|word| format!("names {word}"))
        .collect();
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
