//! Literal examples of every existing gh form, through the public service
//! executor. These are transport proofs, not merge-policy or scheduler proofs.
use super::*;

#[test]
fn every_existing_tick_and_health_form_uses_the_shared_app_token() {
    let f = Fixture::new();
    let client = f.client();
    let forms: &[&[&str]] = &[
        &["--version"],
        &["repo", "view", "--json", "nameWithOwner"],
        &["repo", "view", "--json", "nameWithOwner,url"],
        &[
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "blockedBy,body,id,labels,milestone,number,state,subIssues,title",
        ],
        &[
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title",
        ],
        &[
            "issue",
            "view",
            "901",
            "--json",
            "blockedBy,body,closedByPullRequestsReferences,comments,labels,milestone,state,subIssues,title",
        ],
        &[
            "pr",
            "view",
            "902",
            "--json",
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state",
        ],
        &["pr", "checks", "902", "--json", "bucket,name"],
        &[
            "pr",
            "view",
            "902",
            "--json",
            "comments",
            "--jq",
            "[.comments[].body]",
        ],
        &[
            "pr",
            "view",
            "902",
            "--json",
            "comments",
            "--jq",
            r#"[.comments[].body | select(startswith("VERDICT: "))]"#,
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/0123456789abcdef0123456789abcdef01234567...main",
            "--jq",
            "{status: .status, behind_by: .behind_by}",
        ],
        &[
            "api",
            "repos/{owner}/{repo}/compare/main...0123456789abcdef0123456789abcdef01234567",
            "--jq",
            "{ahead_by: .ahead_by}",
        ],
        &[
            "issue",
            "comment",
            "901",
            "--body",
            "synthetic health record",
        ],
        &["pr", "comment", "902", "--body", "synthetic tick record"],
        &["issue", "edit", "901", "--add-label", "needs-info"],
        &["issue", "edit", "901", "--remove-label", "needs-info"],
        &["issue", "close", "901"],
        &[
            "pr",
            "merge",
            "902",
            "--merge",
            "--match-head-commit",
            "0123456789abcdef0123456789abcdef01234567",
            "--body",
            "synthetic approved merge",
        ],
        &["issue", "view", "901", "--json", "comments"],
        &["pr", "view", "902", "--json", "comments"],
        &["issue", "view", "901", "--json", "labels"],
        &["issue", "view", "901", "--json", "url"],
        &["issue", "view", "901", "--json", "state"],
        &[
            "api",
            "graphql",
            "-f",
            "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled}}}",
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            "number=902",
        ],
        &[
            "pr",
            "view",
            "902",
            "--json",
            "state,mergeCommit,headRefOid",
        ],
    ];
    assert_eq!(forms.len(), 25);
    for form in forms {
        let call = Invocation::new(form).expect("the documented existing form is allowlisted");
        assert_eq!(
            client.clone().execute(&call, soon()).unwrap(),
            b"{\"synthetic\":\"ok\"}\n"
        );
    }
    let expected:Vec<_> = forms.iter().map(|form|json!({"argv":form,"token":TOKEN,"repo":"github.com/synthetic-owner/synthetic-repo","host":"github.com","debug":null})).collect();
    assert_eq!(
        f.gh_calls(),
        expected,
        "every argv and child credential, with no missing or extra call"
    );
    assert_eq!(f.exchange.calls.lock().unwrap().len(), 1);
}
