use openwiz_adapter_github::allowlist::allowed;
use openwiz_adapter_github::{fleets, writes};

const ISSUE_FIELDS: &str = "blockedBy,body,id,labels,milestone,number,state,subIssues,title";
const PR_FIELDS: &str = "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title";

const GOOD: &[&[&str]] = &[
    &["--version"],
    &["repo", "view", "--json", "nameWithOwner"],
    &[
        "issue",
        "list",
        "--state",
        "all",
        "--limit",
        "1000",
        "--json",
        ISSUE_FIELDS,
    ],
    &[
        "pr", "list", "--state", "all", "--limit", "1000", "--json", PR_FIELDS,
    ],
    &["pr", "checks", "952", "--json", "bucket,name"],
    &[
        "pr",
        "view",
        "952",
        "--json",
        "comments",
        "--jq",
        "[.comments[].body]",
    ],
    &[
        "api",
        "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...main",
        "--jq",
        "{status: .status, behind_by: .behind_by}",
    ],
    &[
        "api",
        "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...release-0.0.3",
        "--jq",
        "{status: .status, behind_by: .behind_by}",
    ],
    &[
        "api",
        "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...room/syn-a1",
        "--jq",
        "{status: .status, behind_by: .behind_by}",
    ],
];

#[test]
fn github_read_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 3] = [
        (
            "ancestry_query_is_bounded_pinned_and_read_only",
            ancestry_query_is_bounded_pinned_and_read_only,
        ),
        (
            "it_allows_its_existing_read_forms",
            it_allows_its_existing_read_forms,
        ),
        (
            "it_refuses_every_write_and_every_near_miss",
            it_refuses_every_write_and_every_near_miss,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: a4_fleets::allowlist_forms::{name}");
        proof();
    }
}

fn it_allows_its_existing_read_forms() {
    for argv in GOOD {
        assert!(allowed(argv), "{argv:?}");
        assert!((fleets::ALLOWLIST.allows)(argv), "{argv:?}");
    }
}

fn it_refuses_every_write_and_every_near_miss() {
    let compare = "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...main";
    let jq = "{status: .status, behind_by: .behind_by}";
    for argv in [
        &[][..],
        &["--help"],
        &["version"],
        &["--version", "--json"],
        &["repo", "view"],
        &["repo", "view", "--json", "name"],
        &["repo", "view", "--json", "nameWithOwner", "--web"],
        &["repo", "edit", "--description", "synthetic"],
        &["repo", "delete", "--yes"],
        &[
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            ISSUE_FIELDS,
        ],
        &[
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "999",
            "--json",
            ISSUE_FIELDS,
        ],
        &[
            "issue", "list", "--state", "all", "--limit", "1000", "--json", "number",
        ],
        &[
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            ISSUE_FIELDS,
            "--web",
        ],
        &[
            "issue",
            "list",
            "--json",
            ISSUE_FIELDS,
            "--state",
            "all",
            "--limit",
            "1000",
        ],
        &["issue", "view", "1", "--json", "title"],
        &[
            "issue",
            "create",
            "--title",
            "synthetic",
            "--body",
            "synthetic",
        ],
        &["issue", "reopen", "1"],
        &["issue", "delete", "1", "--yes"],
        &["issue", "lock", "1"],
        &["issue", "transfer", "1", "synthetic"],
        &[
            "pr", "list", "--state", "all", "--limit", "1000", "--json", "number",
        ],
        &["pr", "checks", "952"],
        &["pr", "checks", "952", "--json", "bucket,name", "--watch"],
        &["pr", "checks", "0", "--json", "bucket,name"],
        &["pr", "checks", "0952", "--json", "bucket,name"],
        &["pr", "checks", "-1", "--json", "bucket,name"],
        &["pr", "checks", "+952", "--json", "bucket,name"],
        &["pr", "checks", "95 2", "--json", "bucket,name"],
        &[
            "pr",
            "checks",
            "18446744073709551616",
            "--json",
            "bucket,name",
        ],
        &["pr", "checks", "room/syn-a1", "--json", "bucket,name"],
        &[
            "pr",
            "view",
            "952",
            "--json",
            "comments",
            "--jq",
            ".comments",
        ],
        &["pr", "view", "952", "--comments"],
        &["pr", "merge", "952", "--merge"],
        &["pr", "close", "952"],
        &["pr", "ready", "952"],
        &["pr", "edit", "952", "--title", "synthetic"],
        &["pr", "review", "952", "--approve"],
        &["pr", "create", "--fill"],
        &["label", "create", "held"],
        &["api", compare],
        &["api", compare, "--jq", ".status"],
        &["api", compare, "--jq", jq, "-X", "GET"],
        &["api", "-X", "POST", compare, "--jq", jq],
        &["api", compare, "--jq", jq, "--method", "POST"],
        &["api", compare, "--jq", jq, "-f", "x=y"],
        &["api", compare, "--jq", jq, "-F", "x=y"],
        &["api", compare, "--jq", jq, "--input", "synthetic"],
        &["api", "graphql", "--jq", jq],
        &["api", "repos/{owner}/{repo}/issues/1/comments", "--jq", jq],
        &[
            "api",
            "repos/{owner}/{repo}/compare/main...main",
            "--jq",
            jq,
        ],
        &["api", "repos/{owner}/{repo}/compare/222...main", "--jq", jq],
        &[
            "api",
            "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...main?x=1",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...../x",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...-x",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/2222222222222222222222222222222222222222...a//b",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...main",
            "--jq",
            jq,
        ],
        &[
            "api",
            "repos/someone/repo/compare/2222222222222222222222222222222222222222...main",
            "--jq",
            jq,
        ],
    ] {
        assert!(!(fleets::ALLOWLIST.allows)(argv), "{argv:?}");
        assert!(!allowed(argv), "{argv:?}");
    }

    for argv in [
        &["issue", "comment", "1", "--body", "synthetic"][..],
        &["issue", "edit", "1", "--add-label", "held"],
        &["issue", "close", "1"],
        &["pr", "view", "952", "--json", "comments"],
        &["pr", "comment", "952", "--body", "synthetic"],
    ] {
        assert!(!(fleets::ALLOWLIST.allows)(argv), "{argv:?}");
        assert!((writes::ALLOWLIST.allows)(argv), "{argv:?}");
        assert!(allowed(argv), "{argv:?}");
    }
}

fn ancestry_query_is_bounded_pinned_and_read_only() {
    let sha = "b".repeat(40);
    for n in [1, 20] {
        let pairs: Vec<_> = (0..n)
            .map(|i| (format!("release/syn-{i}"), sha.clone()))
            .collect();
        let args = super::edges::batch_argv(&pairs);
        let allows = |a: &[String]| {
            (fleets::ALLOWLIST.allows)(&a.iter().map(String::as_str).collect::<Vec<_>>())
        };
        assert!(allows(&args));
        for (index, replacement) in [
            (0, "pr"),
            (1, "graphql?query=mutation"),
            (2, "--raw-field"),
            (3, "owner=other"),
            (5, "name=other"),
            (
                7,
                "query=mutation{deleteRef(input:{refId:\"synthetic\"}){clientMutationId}}",
            ),
            (7, "query=query{viewer{login}}"),
            (8, "-F"),
            (9, "base0=main"),
            (9, "base0=refs/tags/main"),
            (9, "base0=refs/heads/../main"),
            (9, "base0=refs/heads/main?x=1"),
            (9, "base0=refs/heads/main\"}){viewer{login}}#"),
            (9, "base0=refs/heads/-main"),
            (9, "base0=refs/heads/main//x"),
            (11, "head0=HEAD"),
            (11, "head0=bbbbbbb"),
            (11, "head0=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"),
        ] {
            let mut bad = args.clone();
            bad[index] = replacement.to_owned();
            assert!(!allows(&bad), "{bad:?}");
        }
        for extra in [
            vec!["--paginate"],
            vec!["-X", "POST"],
            vec!["-f", "query=mutation{}"],
            vec!["-f", "head0=HEAD"],
        ] {
            let mut bad = args.clone();
            bad.extend(extra.into_iter().map(str::to_owned));
            assert!(!allows(&bad));
        }
        let mut bad = args.clone();
        bad[7] = bad[7].replace("status aheadBy", "commits{totalCount} status aheadBy");
        assert!(!allows(&bad));
        let mut bad = args.clone();
        bad[7] = bad[7].replace("compare(headRef:$head0)", "compare(headRef:$base0)");
        assert!(!allows(&bad));
    }
    for n in [0, 21] {
        let args = super::edges::batch_argv(&vec![("main".to_owned(), sha.clone()); n]);
        assert!(!(fleets::ALLOWLIST.allows)(
            &args.iter().map(String::as_str).collect::<Vec<_>>()
        ));
    }
}
