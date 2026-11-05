//! Bounded repository-scoped GraphQL reads for the cockpit plan. No writes.
use crate::allowlist::Module;

pub const ALLOWLIST: Module = Module {
    name: "plan",
    allows,
};

#[derive(Clone, Copy, Debug)]
pub enum Relation {
    Labels,
    SubIssues,
    BlockedBy,
    ClosingPrs,
    ClosingIssues,
    Comments,
}

impl Relation {
    pub fn field(self) -> &'static str {
        match self {
            Self::Labels => "labels",
            Self::SubIssues => "subIssues",
            Self::BlockedBy => "blockedBy",
            Self::ClosingPrs => "closedByPullRequestsReferences",
            Self::ClosingIssues => "closingIssuesReferences",
            Self::Comments => "comments",
        }
    }
    fn nodes(self) -> &'static str {
        match self {
            Self::Labels => "name",
            Self::Comments => "body",
            Self::ClosingIssues => "id number url repository{nameWithOwner}",
            _ => "number url",
        }
    }
}

const PAGE: &str = "totalCount pageInfo{hasNextPage endCursor}";
const LINK: &str = "number url";
const MILESTONE: &str = "number title";

#[derive(Clone, Copy, Debug)]
pub enum Request {
    Milestones,
    Issues,
    Issue(u64),
    Pr(u64),
    Relation(u64, Relation),
}

impl Request {
    pub fn query(self) -> String {
        let connection = |field: &str, nodes: &str, args: &str| {
            format!("{field}(first:100,after:$cursor{args}){{{PAGE} nodes{{{nodes}}}}}")
        };
        let issue = || {
            format!(
                "number title url state milestone{{{MILESTONE}}} parent{{{LINK}}} {} {} {} {}",
                connection("labels", "name", ""),
                connection("subIssues", LINK, ""),
                connection("blockedBy", LINK, ""),
                connection(
                    "closedByPullRequestsReferences",
                    LINK,
                    ",includeClosedPrs:true"
                )
            )
        };
        let (vars, body) = match self {
            Self::Milestones => (
                "",
                connection("milestones", MILESTONE, ",states:[OPEN,CLOSED]"),
            ),
            Self::Issues => (
                "",
                connection(
                    "issues",
                    &issue(),
                    ",states:[OPEN,CLOSED],orderBy:{field:CREATED_AT,direction:ASC}",
                ),
            ),
            Self::Issue(_) => (
                ",$number:Int!",
                format!("issue(number:$number){{{}}}", issue()),
            ),
            Self::Pr(_) => (
                ",$number:Int!",
                format!(
                    "pullRequest(number:$number){{number url baseRefName headRefName headRefOid isDraft mergeCommit{{oid}} mergedAt state {}}}",
                    connection(
                        "closingIssuesReferences",
                        "id number url repository{nameWithOwner}",
                        ""
                    )
                ),
            ),
            Self::Relation(_, r) => {
                let subject = if matches!(r, Relation::ClosingIssues | Relation::Comments) {
                    "pullRequest"
                } else {
                    "issue"
                };
                let args = if matches!(r, Relation::ClosingPrs) {
                    ",includeClosedPrs:true"
                } else {
                    ""
                };
                (
                    ",$number:Int!",
                    format!(
                        "{subject}(number:$number){{{}}}",
                        connection(r.field(), r.nodes(), args)
                    ),
                )
            }
        };
        // Nested first pages have their own null cursor; the outer cursor
        // must never skip their first rows when repository pages advance.
        let body = match self {
            Self::Issues => body
                .replacen("labels(first:100,after:$cursor)", "labels(first:100)", 1)
                .replace("subIssues(first:100,after:$cursor)", "subIssues(first:100)")
                .replace("blockedBy(first:100,after:$cursor)", "blockedBy(first:100)")
                .replace(
                    "closedByPullRequestsReferences(first:100,after:$cursor,",
                    "closedByPullRequestsReferences(first:100,",
                ),
            Self::Issue(_) | Self::Pr(_) => body.replace("after:$cursor", "after:null"),
            _ => body,
        };
        let cursor_var = if matches!(self, Self::Issue(_) | Self::Pr(_)) {
            ""
        } else {
            ",$cursor:String"
        };
        format!(
            "query($owner:String!,$name:String!{cursor_var}{vars}){{repository(owner:$owner,name:$name){{{body}}}}}"
        )
    }

    pub fn argv(self, cursor: Option<&str>) -> Vec<String> {
        let mut args: Vec<String> = [
            "api",
            "graphql",
            "-F",
            "owner={owner}",
            "-F",
            "name={repo}",
            "-f",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect();
        args.push(format!("query={}", self.query()));
        if let Self::Issue(n) | Self::Pr(n) | Self::Relation(n, _) = self {
            args.extend(["-F".to_owned(), format!("number={n}")]);
        }
        if let Some(cursor) = cursor {
            args.extend(["-f".to_owned(), format!("cursor={cursor}")]);
        }
        args
    }
}

fn number(s: &str) -> Option<u64> {
    (!s.is_empty() && s.len() <= 10 && !s.starts_with('0') && s.bytes().all(|c| c.is_ascii_digit()))
        .then(|| s.parse().ok())
        .flatten()
}

fn allows(argv: &[&str]) -> bool {
    if argv.len() < 8
        || argv[..7]
            != [
                "api",
                "graphql",
                "-F",
                "owner={owner}",
                "-F",
                "name={repo}",
                "-f",
            ]
    {
        return false;
    }
    let mut at = 8;
    let n = if argv.get(at) == Some(&"-F") {
        let Some(n) = argv
            .get(at + 1)
            .and_then(|s| s.strip_prefix("number="))
            .and_then(number)
        else {
            return false;
        };
        at += 2;
        Some(n)
    } else {
        None
    };
    let cursor = if argv.get(at) == Some(&"-f") {
        let Some(c) = argv.get(at + 1).and_then(|s| s.strip_prefix("cursor=")) else {
            return false;
        };
        if c.is_empty()
            || !c
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"+/=_-".contains(&c))
        {
            return false;
        }
        at += 2;
        Some(c)
    } else {
        None
    };
    if at != argv.len() {
        return false;
    }
    let requests = match n {
        None => vec![Request::Milestones, Request::Issues],
        Some(n) => vec![
            Request::Issue(n),
            Request::Pr(n),
            Request::Relation(n, Relation::Labels),
            Request::Relation(n, Relation::SubIssues),
            Request::Relation(n, Relation::BlockedBy),
            Request::Relation(n, Relation::ClosingPrs),
            Request::Relation(n, Relation::ClosingIssues),
            Request::Relation(n, Relation::Comments),
        ],
    };
    requests.iter().any(|r| {
        r.argv(cursor)
            .iter()
            .map(String::as_str)
            .eq(argv.iter().copied())
    })
}

#[path = "plan_reads.rs"]
mod reads;
pub use reads::*;
