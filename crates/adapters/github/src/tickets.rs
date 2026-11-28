use std::fmt;
use std::path::PathBuf;
use std::time::Instant;

use openwiz_core::fleet::fleets::{IssueComment, pending_question};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Issue, IssueState, Milestone, NonEmpty, Number,
};
use openwiz_core::fleet::tickets::{
    GitHub, IssueAnswer, Link, ListAnswer, PrAnswer, PrState, RepositoryAnswer,
};
use openwiz_core::model::Timestamp;
use openwiz_core::source::SourceError;
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};

use crate::allowlist::{Invocation, Module};
use crate::process;

pub const ALLOWLIST: Module = Module {
    name: "tickets",
    allows,
};

pub const TESTED_VERSION: &str = "2.100.0";

pub const ISSUE_FIELDS: &str =
    "blockedBy,body,closedByPullRequestsReferences,comments,labels,milestone,state,subIssues,title";

pub const PR_FIELDS: &str = "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state";

pub const CHECK_FIELDS: &str = "bucket,name";

pub const VERDICTS_JQ: &str = r#"[.comments[].body | select(startswith("VERDICT: "))]"#;

pub const START_COMMENTS_JQ: &str = "map({login: .user.login, type: .user.type, body})";

const ISSUES_PREFIX: &str = "repos/{owner}/{repo}/issues/";

fn start_comments_path(n: &str) -> String {
    format!("{ISSUES_PREFIX}{n}/comments?per_page=100")
}

pub const COMPARE_JQ: &str = "{ahead_by: .ahead_by}";

const COMPARE_PREFIX: &str = "repos/{owner}/{repo}/compare/";

fn allows(argv: &[&str]) -> bool {
    match argv {
        ["--version"] => true,
        ["repo", "view", "--json", "nameWithOwner,url"] => true,
        ["issue", "view", n, "--json", fields] => is_number(n) && *fields == ISSUE_FIELDS,
        ["pr", "view", n, "--json", fields] => is_number(n) && *fields == PR_FIELDS,
        ["pr", "checks", n, "--json", fields] => is_number(n) && *fields == CHECK_FIELDS,
        ["pr", "view", n, "--json", "comments", "--jq", jq] => is_number(n) && *jq == VERDICTS_JQ,
        ["api", path, "--jq", jq] => *jq == COMPARE_JQ && compare_path(path).is_some(),
        ["api", path, "--paginate", "--jq", jq] => {
            *jq == START_COMMENTS_JQ
                && path
                    .strip_prefix(ISSUES_PREFIX)
                    .and_then(|p| p.strip_suffix("/comments?per_page=100"))
                    .is_some_and(is_number)
        }
        _ => false,
    }
}

fn is_number(text: &str) -> bool {
    !text.is_empty()
        && text.len() <= 10
        && !text.starts_with('0')
        && text.bytes().all(|b| b.is_ascii_digit())
}

fn compare_path(path: &str) -> Option<(&str, &str)> {
    let (base, commit) = path.strip_prefix(COMPARE_PREFIX)?.split_once("...")?;
    (is_branch(base) && Commit::parse(commit).is_some()).then_some((base, commit))
}

fn is_branch(name: &str) -> bool {
    !name.is_empty()
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'/'))
        && !name.starts_with(['-', '.', '/'])
        && !name.ends_with(['.', '/'])
        && !name.contains("..")
        && !name.contains("//")
}

#[derive(Clone, Debug)]
pub struct Tickets {
    executor: process::Executor,
}

impl Tickets {
    pub fn new(program: impl Into<PathBuf>) -> Self {
        Self::with_executor(process::Executor::program(program))
    }

    pub fn with_executor(executor: process::Executor) -> Self {
        Self { executor }
    }

    pub fn from_path() -> Self {
        Self::new(crate::PROGRAM)
    }

    pub fn record_authors(&self, deadline: Instant) -> Result<RecordAuthors, SourceError> {
        let unread = |_| SourceError::Unavailable {
            detail: "the record authors setting could not be read".to_owned(),
        };
        let reads = crate::tick::TickReads::with_executor(self.executor.clone());
        let repository = reads.repository(deadline).map_err(unread)?;
        let head = reads
            .branch(repository.default.as_str(), deadline)
            .map_err(unread)?;
        let settings = reads.rules(&head, deadline).map_err(unread)?;
        RecordAuthors::read(&settings).map_err(|why| malformed("record authors", why))
    }

    fn run(&self, argv: &[&str], deadline: Instant) -> Result<Vec<u8>, SourceError> {
        let invocation = Invocation::new(argv).ok_or_else(|| SourceError::Unavailable {
            detail: "the call is not on the allowlist, so nothing was run".to_owned(),
        })?;
        self.executor.run(&invocation, deadline)
    }
}

impl GitHub for Tickets {
    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        version(&self.run(&["--version"], deadline)?)
    }

    fn repository(&self, deadline: Instant) -> Result<RepositoryAnswer, SourceError> {
        repository(&self.run(&["repo", "view", "--json", "nameWithOwner,url"], deadline)?)
    }

    fn issue(&self, number: Number, deadline: Instant) -> Result<IssueAnswer, SourceError> {
        let n = number.to_string();
        issue(&self.run(&["issue", "view", &n, "--json", ISSUE_FIELDS], deadline)?)
    }

    fn stock_issue(
        &self,
        number: Number,
        deadline: Instant,
    ) -> Result<(IssueAnswer, openwiz_core::model::Fact<bool>), SourceError> {
        let n = number.to_string();
        let authors = self.record_authors(deadline)?;
        let issue = self.run(&["issue", "view", &n, "--json", ISSUE_FIELDS], deadline)?;
        let comments = self.run(
            &[
                "api",
                &start_comments_path(&n),
                "--paginate",
                "--jq",
                START_COMMENTS_JQ,
            ],
            deadline,
        )?;
        stock_issue(&issue, &comments, &authors)
    }

    fn pull_request(&self, number: Number, deadline: Instant) -> Result<PrAnswer, SourceError> {
        let n = number.to_string();
        let pr = pull_request(&self.run(&["pr", "view", &n, "--json", PR_FIELDS], deadline)?)?;
        if pr.number != number {
            return Err(malformed("pull request", "it names another pull request"));
        }
        Ok(pr)
    }

    fn checks(&self, pr: Number, deadline: Instant) -> Result<Vec<Check>, SourceError> {
        let n = pr.to_string();
        let invocation = Invocation::new(&["pr", "checks", &n, "--json", CHECK_FIELDS])
            .ok_or_else(|| SourceError::Unavailable {
                detail: "the call is not on the allowlist, so nothing was run".to_owned(),
            })?;
        checks(&self.executor.checks(&invocation, deadline)?)
    }

    fn verdict_comments(&self, pr: Number, deadline: Instant) -> Result<Vec<String>, SourceError> {
        let n = pr.to_string();
        let argv = ["pr", "view", &n, "--json", "comments", "--jq", VERDICTS_JQ];
        verdict_comments(&self.run(&argv, deadline)?)
    }

    fn on_base(
        &self,
        commit: &Commit,
        base: &NonEmpty,
        deadline: Instant,
    ) -> Result<bool, SourceError> {
        if !is_branch(base.as_str()) {
            return Err(SourceError::Unavailable {
                detail: "its base branch's name isn't one OpenWiz passes to gh, so nothing was \
                         run"
                .to_owned(),
            });
        }
        let path = format!("{COMPARE_PREFIX}{}...{}", base.as_str(), commit.as_str());
        on_base(&self.run(&["api", &path, "--jq", COMPARE_JQ], deadline)?)
    }
}

fn malformed(what: &str, why: &str) -> SourceError {
    SourceError::Malformed {
        detail: format!("gh's {what} answer: {why}"),
    }
}

pub fn version(stdout: &[u8]) -> Result<String, SourceError> {
    let bad = || malformed("--version", "no version in its first line");
    let text = std::str::from_utf8(stdout).map_err(|_| bad())?;
    let line = text.lines().next().ok_or_else(bad)?;
    let words: Vec<&str> = line.split(' ').collect();
    match words.as_slice() {
        ["gh", "version", v] if is_version(v) => Ok((*v).to_owned()),
        ["gh", "version", v, date]
            if is_version(v) && date.starts_with('(') && date.ends_with(')') =>
        {
            Ok((*v).to_owned())
        }
        _ => Err(bad()),
    }
}

fn is_version(text: &str) -> bool {
    let parts: Vec<&str> = text.split('.').collect();
    parts.len() == 3
        && parts
            .iter()
            .all(|p| !p.is_empty() && p.len() <= 6 && p.bytes().all(|b| b.is_ascii_digit()))
}

pub fn repository(stdout: &[u8]) -> Result<RepositoryAnswer, SourceError> {
    let what = "repo view";
    let doc = document(stdout, what)?;
    let o = object(&doc, &["nameWithOwner", "url"], what)?;
    let name_with_owner = non_empty(&o["nameWithOwner"], what)?;
    let name = match name_with_owner.as_str().split_once('/') {
        Some((owner, name)) if !owner.is_empty() && !name.contains('/') => NonEmpty::new(name),
        _ => None,
    }
    .ok_or_else(|| malformed(what, "nameWithOwner is not <owner>/<name>"))?;
    Ok(RepositoryAnswer {
        name,
        name_with_owner,
        url: non_empty(&o["url"], what)?,
    })
}

pub fn issue(stdout: &[u8]) -> Result<IssueAnswer, SourceError> {
    let what = "issue view";
    let doc = document(stdout, what)?;
    let o = object(
        &doc,
        &[
            "blockedBy",
            "body",
            "closedByPullRequestsReferences",
            "comments",
            "labels",
            "milestone",
            "state",
            "subIssues",
            "title",
        ],
        what,
    )?;
    let state = match text(&o["state"], what)? {
        "OPEN" => IssueState::Open,
        "CLOSED" => IssueState::Closed,
        _ => return Err(malformed(what, "a state other than OPEN or CLOSED")),
    };
    let milestone = match &o["milestone"] {
        Value::Null => None,
        value => {
            let m = object(value, &["description", "dueOn", "number", "title"], what)?;
            text(&m["description"], what)?;
            text_or_null(&m["dueOn"], what)?;
            Some(Milestone {
                number: number(&m["number"], what)?,
                title: text(&m["title"], what)?.to_owned(),
            })
        }
    };
    let mut labels: Vec<NonEmpty> = Vec::new();
    for label in array(&o["labels"], what)? {
        let l = object(label, &["color", "description", "id", "name"], what)?;
        for key in ["color", "description", "id"] {
            text(&l[key], what)?;
        }
        let name = non_empty(&l["name"], what)?;
        if labels.contains(&name) {
            return Err(malformed(what, "a label given twice"));
        }
        labels.push(name);
    }
    let body = text(&o["body"], what)?;
    let mut closed_by = Vec::new();
    for reference in array(&o["closedByPullRequestsReferences"], what)? {
        let r = object(reference, &["id", "number", "repository", "url"], what)?;
        text(&r["id"], what)?;
        if !r["repository"].is_object() {
            return Err(malformed(
                what,
                "a closing pull request's repository is not an object",
            ));
        }
        closed_by.push(link(&r["number"], &r["url"], what)?);
    }
    Ok(IssueAnswer {
        issue: Issue {
            title: text(&o["title"], what)?.to_owned(),
            state,
            milestone,
            labels,
            owned_paths: template_line(body, "**Owned paths:**"),
            relies_on: template_line(body, "**Relies on:**"),
            pending_question: pending_question(
                &array(&o["comments"], what)?
                    .iter()
                    .map(issue_comment)
                    .collect::<Result<Vec<_>, _>>()?,
            ),
        },
        sub_issues: list(&o["subIssues"], what)?,
        blocked_by: list(&o["blockedBy"], what)?,
        closed_by,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordAuthors(std::collections::BTreeSet<String>);

impl RecordAuthors {
    pub fn read(fleet_md: &str) -> Result<Self, &'static str> {
        const REFUSED: &str = "docs/agents/fleet.md names no record authors";
        let mut section = None;
        let mut rows = vec![];
        for line in fleet_md.lines() {
            if line.starts_with("## ") {
                section = Some(line);
            } else if section == Some("## GitHub identity") && is_authors_row(line) {
                rows.push(line);
            }
        }
        let [row] = rows.as_slice() else {
            return Err(REFUSED);
        };
        let cells: Vec<&str> = row.split('|').collect();
        let [_, _, value, rest] = cells.as_slice() else {
            return Err(REFUSED);
        };
        if !rest.trim().is_empty() {
            return Err(REFUSED);
        }
        let mut logins = std::collections::BTreeSet::new();
        for entry in value.split(',') {
            let login = entry
                .trim()
                .strip_prefix('`')
                .and_then(|e| e.strip_suffix('`'))
                .filter(|l| is_login(l))
                .ok_or(REFUSED)?;
            logins.insert(login.to_ascii_lowercase());
        }
        Ok(Self(logins))
    }

    pub fn wrote(&self, login: Option<&str>, kind: Option<&str>) -> bool {
        let (Some(login), Some(kind)) = (login, kind) else {
            return false;
        };
        let login = login.to_ascii_lowercase();
        let app = login.ends_with("[bot]");
        let typed = match kind {
            "Bot" => app,
            "User" => !app,
            _ => false,
        };
        typed && self.0.contains(&login)
    }
}

fn is_authors_row(line: &str) -> bool {
    line.strip_prefix('|')
        .map(|l| l.trim_start_matches(' '))
        .and_then(|l| l.strip_prefix("Record authors"))
        .is_some_and(|l| l.trim_start_matches(' ').starts_with('|'))
}

fn is_login(login: &str) -> bool {
    let name = login.strip_suffix("[bot]").unwrap_or(login);
    !name.is_empty()
        && !name.starts_with('-')
        && !name.ends_with('-')
        && !name.contains("--")
        && name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}

pub fn stock_issue(
    stdout: &[u8],
    comments: &[u8],
    authors: &RecordAuthors,
) -> Result<(IssueAnswer, openwiz_core::model::Fact<bool>), SourceError> {
    let i = issue(stdout)?;
    let started = started(comments, authors)?;
    Ok((i, openwiz_core::model::Fact::Known(started)))
}

fn started(comments: &[u8], authors: &RecordAuthors) -> Result<bool, SourceError> {
    let what = "start record comments";
    let pages = std::str::from_utf8(comments).map_err(|_| malformed(what, "not UTF-8"))?;
    if pages.lines().next().is_none() {
        return Err(malformed(what, "no pages"));
    }
    let mut rows = vec![];
    for page in pages.lines() {
        let page = document(page.as_bytes(), what)?;
        for row in array(&page, what)? {
            let o = object(row, &["body", "login", "type"], what)?;
            let login = text_or_null(&o["login"], what)?;
            let kind = text_or_null(&o["type"], what)?;
            rows.push((
                authors.wrote(login, kind),
                text(&o["body"], what)?.to_owned(),
            ));
        }
    }
    Ok(rows
        .into_iter()
        .filter(|(factory, _)| *factory)
        .rev()
        .take(15)
        .any(|(_, body)| body.starts_with("launch-fleet: start")))
}

fn issue_comment(value: &Value) -> Result<IssueComment, SourceError> {
    let what = "issue comment";
    let c = object(
        value,
        &[
            "id",
            "author",
            "authorAssociation",
            "body",
            "createdAt",
            "includesCreatedEdit",
            "isMinimized",
            "minimizedReason",
            "reactionGroups",
            "url",
            "viewerDidAuthor",
        ],
        what,
    )?;
    for key in ["id", "authorAssociation"] {
        text(&c[key], what)?;
    }
    if !c["minimizedReason"].is_null() {
        text(&c["minimizedReason"], what)?;
    }
    for key in ["includesCreatedEdit", "isMinimized", "viewerDidAuthor"] {
        if !c[key].is_boolean() {
            return Err(malformed(what, "comment metadata is not a boolean"));
        }
    }
    if !c["author"].is_null() && !c["author"].is_object() {
        return Err(malformed(
            what,
            "comment author is neither an object nor null",
        ));
    }
    array(&c["reactionGroups"], what)?;
    let asked_at = iso_ms(text(&c["createdAt"], what)?)
        .filter(|at| at.0 >= 0)
        .ok_or_else(|| malformed(what, "createdAt is not a nonnegative UTC time"))?;
    Ok(IssueComment {
        body: text(&c["body"], what)?.to_owned(),
        link: non_empty(&c["url"], what)?,
        asked_at,
    })
}

fn template_line(body: &str, label: &str) -> Option<NonEmpty> {
    let mut found = body.split('\n').filter_map(|line| line.strip_prefix(label));
    let first = found.next()?;
    if found.next().is_some() {
        return None;
    }
    NonEmpty::new(first.trim())
}

fn list(value: &Value, what: &str) -> Result<ListAnswer, SourceError> {
    let o = object(value, &["nodes", "totalCount"], what)?;
    let mut nodes = Vec::new();
    for node in array(&o["nodes"], what)? {
        let n = object(node, &["id", "number", "state", "title", "url"], what)?;
        for key in ["id", "state", "title"] {
            text(&n[key], what)?;
        }
        nodes.push(link(&n["number"], &n["url"], what)?);
    }
    let total = o["totalCount"]
        .as_u64()
        .ok_or_else(|| malformed(what, "a total that is not a whole number"))?;
    Ok(ListAnswer { nodes, total })
}

fn link(number_value: &Value, url: &Value, what: &str) -> Result<Link, SourceError> {
    Ok(Link {
        number: number(number_value, what)?,
        url: text(url, what)?.to_owned(),
    })
}

pub fn pull_request(stdout: &[u8]) -> Result<PrAnswer, SourceError> {
    let what = "pull request";
    let doc = document(stdout, what)?;
    let o = object(
        &doc,
        &[
            "baseRefName",
            "closingIssuesReferences",
            "headRefName",
            "headRefOid",
            "isDraft",
            "mergeCommit",
            "mergedAt",
            "number",
            "state",
        ],
        what,
    )?;
    pull_request_from_map(o, true)
}

pub(crate) fn pull_request_from_map(
    o: &Map<String, Value>,
    include_closes: bool,
) -> Result<PrAnswer, SourceError> {
    let what = "pull request";
    let merge = match (&o["mergeCommit"], &o["mergedAt"]) {
        (Value::Null, Value::Null) => None,
        (Value::Null, _) | (_, Value::Null) => {
            return Err(malformed(
                what,
                "a merge commit without a merge time, or the reverse",
            ));
        }
        (commit, at) => {
            let c = object(commit, &["oid"], what)?;
            let oid = Commit::parse(text(&c["oid"], what)?)
                .ok_or_else(|| malformed(what, "a merge commit that is not 40 lowercase hex"))?;
            let at = iso_ms(text(at, what)?)
                .ok_or_else(|| malformed(what, "a merge time that is not ISO 8601 UTC"))?;
            Some((oid, at))
        }
    };
    let state = match (text(&o["state"], what)?, merge) {
        ("OPEN", None) => PrState::Open,
        ("CLOSED", None) => PrState::Closed,
        ("MERGED", Some((merge_commit, merged_at))) => PrState::Merged {
            merge_commit,
            merged_at,
        },
        ("OPEN" | "CLOSED", Some(_)) => {
            return Err(malformed(
                what,
                "a merge on a pull request that isn't merged",
            ));
        }
        ("MERGED", None) => return Err(malformed(what, "merged, without its merge commit")),
        _ => return Err(malformed(what, "a state other than OPEN, CLOSED or MERGED")),
    };
    let mut closes = Vec::new();
    if include_closes {
        for reference in array(&o["closingIssuesReferences"], what)? {
            let r = object(reference, &["id", "number", "repository", "url"], what)?;
            text(&r["id"], what)?;
            if !r["repository"].is_object() {
                return Err(malformed(
                    what,
                    "a closed issue's repository is not an object",
                ));
            }
            closes.push(link(&r["number"], &r["url"], what)?);
        }
    }
    Ok(PrAnswer {
        number: number(&o["number"], what)?,
        draft: o["isDraft"]
            .as_bool()
            .ok_or_else(|| malformed(what, "isDraft is not true or false"))?,
        head_branch: non_empty(&o["headRefName"], what)?,
        head_commit: Commit::parse(text(&o["headRefOid"], what)?)
            .ok_or_else(|| malformed(what, "a head commit that is not 40 lowercase hex"))?,
        base_branch: non_empty(&o["baseRefName"], what)?,
        state,
        closes,
    })
}

pub fn checks(stdout: &[u8]) -> Result<Vec<Check>, SourceError> {
    let what = "pr checks";
    let doc = document(stdout, what)?;
    let mut checks = Vec::new();
    for row in array(&doc, what)? {
        let r = object(row, &["bucket", "name"], what)?;
        let result = match text(&r["bucket"], what)? {
            "pass" => CheckResult::Pass,
            "fail" => CheckResult::Fail,
            "pending" => CheckResult::Pending,
            "skipping" => CheckResult::Skipping,
            "cancel" => CheckResult::Cancel,
            _ => {
                return Err(malformed(
                    what,
                    "a bucket other than pass, fail, pending, skipping or cancel",
                ));
            }
        };
        checks.push(Check {
            name: non_empty(&r["name"], what)?,
            result,
        });
    }
    Ok(checks)
}

pub fn verdict_comments(stdout: &[u8]) -> Result<Vec<String>, SourceError> {
    let what = "comments";
    let doc = document(stdout, what)?;
    let mut bodies = Vec::new();
    for body in array(&doc, what)? {
        let body = text(body, what)?;
        if !body.starts_with("VERDICT: ") {
            return Err(malformed(what, "a comment that doesn't start VERDICT"));
        }
        bodies.push(body.to_owned());
    }
    Ok(bodies)
}

pub fn on_base(stdout: &[u8]) -> Result<bool, SourceError> {
    let what = "compare";
    let doc = document(stdout, what)?;
    let o = object(&doc, &["ahead_by"], what)?;
    let ahead = o["ahead_by"]
        .as_u64()
        .ok_or_else(|| malformed(what, "ahead_by is not a whole number"))?;
    Ok(ahead == 0)
}

fn iso_ms(text: &str) -> Option<Timestamp> {
    let b = text.as_bytes();
    let digits = |range: std::ops::Range<usize>| -> Option<i64> {
        let part = b.get(range)?;
        part.iter()
            .all(u8::is_ascii_digit)
            .then(|| std::str::from_utf8(part).ok()?.parse().ok())?
    };
    let shape = b.len() == 20
        && b[4] == b'-'
        && b[7] == b'-'
        && b[10] == b'T'
        && b[13] == b':'
        && b[16] == b':'
        && b[19] == b'Z';
    if !shape {
        return None;
    }
    let (year, month, day) = (digits(0..4)?, digits(5..7)?, digits(8..10)?);
    let (hour, minute, second) = (digits(11..13)?, digits(14..16)?, digits(17..19)?);
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let month_days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let valid = (1970..=9999).contains(&year)
        && (1..=12).contains(&month)
        && day >= 1
        && day <= month_days[usize::try_from(month - 1).ok()?]
        && hour < 24
        && minute < 60
        && second < 60;
    if !valid {
        return None;
    }
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(Timestamp(
        ((days * 24 + hour) * 60 + minute) * 60_000 + second * 1000,
    ))
}

fn document(stdout: &[u8], what: &str) -> Result<Value, SourceError> {
    serde_json::from_slice::<KeysOnce>(stdout)
        .map_err(|_| malformed(what, "not JSON, or a key given twice"))?;
    serde_json::from_slice(stdout).map_err(|_| malformed(what, "not JSON"))
}

fn object<'a>(
    value: &'a Value,
    keys: &[&str],
    what: &str,
) -> Result<&'a Map<String, Value>, SourceError> {
    let Value::Object(map) = value else {
        return Err(malformed(what, "an object was expected"));
    };
    let exact = map.len() == keys.len() && keys.iter().all(|k| map.contains_key(*k));
    if exact {
        Ok(map)
    } else {
        Err(malformed(what, "an object without exactly its keys"))
    }
}

fn array<'a>(value: &'a Value, what: &str) -> Result<&'a Vec<Value>, SourceError> {
    value
        .as_array()
        .ok_or_else(|| malformed(what, "a list was expected"))
}

fn text<'a>(value: &'a Value, what: &str) -> Result<&'a str, SourceError> {
    value
        .as_str()
        .ok_or_else(|| malformed(what, "a string was expected"))
}

fn text_or_null<'a>(value: &'a Value, what: &str) -> Result<Option<&'a str>, SourceError> {
    match value {
        Value::Null => Ok(None),
        value => text(value, what).map(Some),
    }
}

fn non_empty(value: &Value, what: &str) -> Result<NonEmpty, SourceError> {
    NonEmpty::new(text(value, what)?).ok_or_else(|| malformed(what, "an empty string"))
}

fn number(value: &Value, what: &str) -> Result<Number, SourceError> {
    value
        .as_u64()
        .and_then(Number::new)
        .ok_or_else(|| malformed(what, "a number that is not a whole number of 1 or more"))
}

struct KeysOnce;

impl<'de> Deserialize<'de> for KeysOnce {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(KeysOnceVisitor)
    }
}

struct KeysOnceVisitor;

impl<'de> Visitor<'de> for KeysOnceVisitor {
    type Value = KeysOnce;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("JSON with no key given twice")
    }

    fn visit_bool<E>(self, _: bool) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_i64<E>(self, _: i64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_u64<E>(self, _: u64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_f64<E>(self, _: f64) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_str<E>(self, _: &str) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_unit<E>(self) -> Result<KeysOnce, E> {
        Ok(KeysOnce)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<KeysOnce, A::Error> {
        while seq.next_element::<KeysOnce>()?.is_some() {}
        Ok(KeysOnce)
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<KeysOnce, A::Error> {
        let mut seen = std::collections::BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !seen.insert(key) {
                return Err(de::Error::custom("a key given twice"));
            }
            map.next_value::<KeysOnce>()?;
        }
        Ok(KeysOnce)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ISSUE: &str = r#"{"blockedBy":{"nodes":[{"id":"n","number":5,"state":"OPEN","title":"t","url":"u/issues/5"}],"totalCount":1},"body":"x\n**Owned paths:** `a.rs`\n**Relies on:** nothing","comments":[],"closedByPullRequestsReferences":[{"id":"p","number":9,"repository":{"id":"r"},"url":"u/pull/9"}],"labels":[{"color":"c","description":"d","id":"l","name":"ready-for-agent"}],"milestone":{"description":"d","dueOn":null,"number":7,"title":"0.9.1"},"state":"OPEN","subIssues":{"nodes":[],"totalCount":0},"title":"Synthetic"}"#;

    const PR: &str = r#"{"baseRefName":"main","closingIssuesReferences":[{"id":"i","number":4,"repository":{"id":"r"},"url":"u/issues/4"}],"headRefName":"room/syn-4","headRefOid":"4444444444444444444444444444444444444444","isDraft":false,"mergeCommit":{"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"mergedAt":"2026-10-30T18:30:00Z","number":40,"state":"MERGED"}"#;

    #[test]
    fn it_allows_exactly_its_read_forms() {
        let compare =
            "repos/{owner}/{repo}/compare/main...aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        for argv in [
            &["--version"][..],
            &["repo", "view", "--json", "nameWithOwner,url"],
            &["issue", "view", "1", "--json", ISSUE_FIELDS],
            &["issue", "view", "1234567890", "--json", ISSUE_FIELDS],
            &["pr", "view", "20", "--json", PR_FIELDS],
            &["pr", "checks", "20", "--json", CHECK_FIELDS],
            &[
                "pr",
                "view",
                "20",
                "--json",
                "comments",
                "--jq",
                VERDICTS_JQ,
            ],
            &["api", compare, "--jq", COMPARE_JQ],
            &[
                "api",
                "repos/{owner}/{repo}/issues/1234567890/comments?per_page=100",
                "--paginate",
                "--jq",
                START_COMMENTS_JQ,
            ],
            &[
                "api",
                "repos/{owner}/{repo}/compare/release-0.0.3...aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "--jq",
                COMPARE_JQ,
            ],
        ] {
            assert!((ALLOWLIST.allows)(argv), "{argv:?}");
        }
    }

    #[test]
    fn it_refuses_every_near_miss_and_every_write() {
        let a40 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let compare = |base: &str, commit: &str| {
            format!("repos/{{owner}}/{{repo}}/compare/{base}...{commit}")
        };
        let refused: Vec<Vec<String>> = vec![
            vec![],
            vec!["--version".into(), "--json".into()],
            vec![
                "repo".into(),
                "view".into(),
                "--json".into(),
                "nameWithOwner".into(),
            ],
            vec![
                "repo".into(),
                "view".into(),
                "--json".into(),
                "name,url".into(),
            ],
            vec![
                "repo".into(),
                "view".into(),
                "--json".into(),
                "nameWithOwner,url,owner".into(),
            ],
            vec![
                "repo".into(),
                "view".into(),
                "--json".into(),
                "url,nameWithOwner".into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "0".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "01".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "-1".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "12345678901".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "1".into(),
                "--json".into(),
                "body".into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "1".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
                "--web".into(),
            ],
            vec![
                "issue".into(),
                "view".into(),
                "1".into(),
                "--comments".into(),
            ],
            vec![
                "issue".into(),
                "comment".into(),
                "1".into(),
                "--body".into(),
                "synthetic".into(),
            ],
            vec![
                "issue".into(),
                "edit".into(),
                "1".into(),
                "--add-label".into(),
                "held".into(),
            ],
            vec![
                "pr".into(),
                "view".into(),
                "1".into(),
                "--json".into(),
                ISSUE_FIELDS.into(),
            ],
            vec![
                "pr".into(),
                "view".into(),
                "1".into(),
                "--json".into(),
                "comments".into(),
            ],
            vec![
                "pr".into(),
                "view".into(),
                "1".into(),
                "--json".into(),
                "comments".into(),
                "--jq".into(),
                ".".into(),
            ],
            vec![
                "pr".into(),
                "checks".into(),
                "1".into(),
                "--json".into(),
                "bucket,name,link".into(),
            ],
            vec!["pr".into(), "checks".into(), "1".into(), "--watch".into()],
            vec!["pr".into(), "merge".into(), "1".into(), "--merge".into()],
            vec![
                "pr".into(),
                "comment".into(),
                "1".into(),
                "--body".into(),
                "synthetic".into(),
            ],
            vec![
                "api".into(),
                compare("main", a40),
                "--jq".into(),
                ".".into(),
            ],
            vec!["api".into(), compare("main", a40)],
            vec![
                "api".into(),
                compare("main", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("main", "aaaa"),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("-x", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("../x", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("a..b", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("a b", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("main?x=1", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                format!("repos/someone/repo/compare/main...{a40}"),
                "--jq".into(),
                COMPARE_JQ.into(),
            ],
            vec![
                "api".into(),
                compare("main", a40),
                "--jq".into(),
                COMPARE_JQ.into(),
                "-X".into(),
                "POST".into(),
            ],
            vec![
                "api".into(),
                "-X".into(),
                "POST".into(),
                compare("main", a40),
            ],
            vec![
                "api".into(),
                "graphql".into(),
                "-f".into(),
                "query=synthetic".into(),
            ],
        ];
        let comments = |path: &str, flags: &[&str]| -> Vec<String> {
            let mut argv = vec!["api".to_owned(), path.to_owned()];
            argv.extend(flags.iter().map(|&f| f.to_owned()));
            argv
        };
        let p1 = "repos/{owner}/{repo}/issues/1/comments?per_page=100";
        let jq = START_COMMENTS_JQ;
        let mut refused = refused;
        refused.extend([
            comments(p1, &["--jq", jq]),
            comments(p1, &["--paginate"]),
            comments(p1, &["--paginate", "--jq", "."]),
            comments(p1, &["--paginate", "--jq", crate::tick::COMMENTS]),
            comments(p1, &["--jq", jq, "--paginate"]),
            comments(p1, &["--paginate", "--jq", jq, "-X", "POST"]),
            comments(p1, &["-X", "POST", "--paginate", "--jq", jq]),
            comments(p1, &["--paginate", "--jq", jq, "-f", "body=synthetic"]),
            comments(&p1.replace("/1/", "/0/"), &["--paginate", "--jq", jq]),
            comments(&p1.replace("/1/", "/01/"), &["--paginate", "--jq", jq]),
            comments(&p1.replace("/1/", "/x/"), &["--paginate", "--jq", jq]),
            comments(&p1.replace("/1/", "//"), &["--paginate", "--jq", jq]),
            comments(
                &p1.replace("/1/", "/12345678901/"),
                &["--paginate", "--jq", jq],
            ),
            comments(&p1.replace("=100", "=50"), &["--paginate", "--jq", jq]),
            comments(
                &p1.replace("?per_page=100", ""),
                &["--paginate", "--jq", jq],
            ),
            comments(
                &p1.replace("{owner}/{repo}", "synthetic/other"),
                &["--paginate", "--jq", jq],
            ),
            comments(
                &p1.replace("issues/1", "pulls/1"),
                &["--paginate", "--jq", jq],
            ),
            comments(
                "repos/{owner}/{repo}/issues/comments?per_page=100",
                &["--paginate", "--jq", jq],
            ),
            comments(
                &(p1.to_owned() + "&since=2030-01-01"),
                &["--paginate", "--jq", jq],
            ),
        ]);
        for argv in refused {
            let words: Vec<&str> = argv.iter().map(String::as_str).collect();
            assert!(!(ALLOWLIST.allows)(&words), "{argv:?}");
        }
    }

    #[test]
    fn the_version_accepts_an_undated_build() {
        for (out, want) in [
            ("gh version 2.100.0", "2.100.0"),
            ("gh version 2.100.0\n", "2.100.0"),
            ("gh version 2.100.0\r\n", "2.100.0"),
            (
                "gh version 2.100.0\nhttps://example.invalid/synthetic\n",
                "2.100.0",
            ),
            ("gh version 2.101.3", "2.101.3"),
            ("gh version 123456.123456.123456", "123456.123456.123456"),
        ] {
            assert_eq!(version(out.as_bytes()), Ok(want.to_owned()), "{out:?}");
        }
    }

    #[test]
    fn the_version_is_read_from_its_first_line_only() {
        for (out, want) in [
            ("gh version 2.100.0 (2026-09-03)", "2.100.0"),
            ("gh version 2.100.0 (2026-09-03)\r\n", "2.100.0"),
            (
                "gh version 2.100.0 (2026-09-03)\nhttps://example.invalid/synthetic\n",
                "2.100.0",
            ),
            (
                "gh version 123456.123456.123456 (2026-09-03)\n",
                "123456.123456.123456",
            ),
        ] {
            assert_eq!(version(out.as_bytes()), Ok(want.to_owned()), "{out:?}");
        }
        for bad in [
            &b""[..],
            b"gh version 2.100 (2026-09-03)\n",
            b"gh version v2.100.0 (2026-09-03)\n",
            b"gh  version 2.100.0 (2026-09-03)\n",
            b"synthetic\ngh version 2.100.0 (2026-09-03)\n",
            b"synthetic\ngh version 2.100.0\n",
            b"gh version 2.100\n",
            b"gh version 2..0\n",
            b"gh version .100.0\n",
            b"gh version 2.100.\n",
            b"gh version 2.100.0.1\n",
            b"gh version 1234567.100.0\n",
            b"gh version 1234567.100.0 (2026-09-03)\n",
            b"gh version v2.100.0\n",
            b"gh version 2.100.0-rc1\n",
            b"gh version 2.100.0+synthetic\n",
            b"gh version 2.100.0 extra\n",
            b"gh version 2.100.0 (2026-09-03) extra\n",
            b"gh version 2.100.0 \n",
            b"gh  version 2.100.0\n",
            b"gh version\t2.100.0\n",
            b"gh version 2.100.0 (\n",
            b"gh version 2.100.0\0\n",
            b"gh version 2.100.\xff\n",
            b"gh version 2.100.0\n\xff",
            b"gh version 2.100.0 (2026-09-03)\n\xff",
        ] {
            assert!(
                matches!(version(bad), Err(SourceError::Malformed { .. })),
                "{bad:?}"
            );
        }
    }

    #[test]
    fn an_issue_is_read_with_exactly_its_shape() {
        let read = issue(ISSUE.as_bytes()).expect("the good issue");
        assert_eq!(read.issue.title, "Synthetic");
        assert_eq!(read.issue.state, IssueState::Open);
        assert_eq!(
            read.issue.owned_paths.as_ref().map(NonEmpty::as_str),
            Some("`a.rs`")
        );
        assert_eq!(
            read.issue.relies_on.as_ref().map(NonEmpty::as_str),
            Some("nothing")
        );
        assert_eq!(read.blocked_by.total, 1);
        assert_eq!(read.blocked_by.nodes[0].url, "u/issues/5");
        assert_eq!(read.closed_by[0].number.get(), 9);

        let good: Value = serde_json::from_str(ISSUE).expect("JSON");
        let mutate = |f: &dyn Fn(&mut Value)| {
            let mut v = good.clone();
            f(&mut v);
            v.to_string()
        };
        let bad = [
            ISSUE.replacen("{\"blockedBy\"", "{\"title\":\"x\",\"blockedBy\"", 1),
            ISSUE.replacen(
                "\"name\":\"ready-for-agent\"",
                "\"name\":\"a\",\"name\":\"b\"",
                1,
            ),
            mutate(&|v| v["synthetic"] = json_null()),
            mutate(&|v| {
                v.as_object_mut().expect("object").remove("body");
            }),
            mutate(&|v| v["state"] = "open".into()),
            mutate(&|v| v["state"] = "MERGED".into()),
            mutate(&|v| v["title"] = 1.into()),
            mutate(&|v| v["milestone"]["number"] = "7".into()),
            mutate(&|v| v["milestone"]["number"] = serde_json::json!(7.0)),
            mutate(&|v| v["milestone"]["number"] = 0.into()),
            mutate(&|v| v["labels"][0]["name"] = "".into()),
            mutate(&|v| v["labels"] = serde_json::json!([{"name": "x"}])),
            mutate(&|v| v["subIssues"] = serde_json::json!([])),
            mutate(&|v| v["subIssues"]["totalCount"] = serde_json::json!(true)),
            mutate(&|v| v["blockedBy"]["nodes"][0]["number"] = serde_json::json!([5])),
            mutate(&|v| v["blockedBy"]["nodes"][0]["extra"] = 1.into()),
            mutate(&|v| v["closedByPullRequestsReferences"][0]["repository"] = "r".into()),
            mutate(&|v| v["closedByPullRequestsReferences"] = serde_json::json!({})),
            "[1]".to_owned(),
            "{".to_owned(),
        ];
        for text in bad {
            assert!(
                matches!(issue(text.as_bytes()), Err(SourceError::Malformed { .. })),
                "{text}"
            );
        }
        let labels_twice = mutate(&|v| {
            let label = v["labels"][0].clone();
            v["labels"].as_array_mut().expect("labels").push(label);
        });
        assert!(issue(labels_twice.as_bytes()).is_err(), "a label twice");
    }

    fn json_null() -> Value {
        Value::Null
    }

    #[test]
    fn the_template_lines_are_the_one_line_that_starts_with_the_label() {
        let line =
            |body: &str| template_line(body, "**Owned paths:**").map(|v| v.as_str().to_owned());
        assert_eq!(
            line("**Owned paths:** `a`, `b`  "),
            Some("`a`, `b`".to_owned())
        );
        assert_eq!(
            line("x\r\n**Owned paths:** `a`\r\ny"),
            Some("`a`".to_owned())
        );
        assert_eq!(line("no line"), None);
        assert_eq!(line("**Owned paths:**   "), None);
        assert_eq!(
            line("**Owned paths:** a\n**Owned paths:** b"),
            None,
            "two lines"
        );
        assert_eq!(
            line("- **Owned paths:** a"),
            None,
            "not at the line's start"
        );
        assert_eq!(line("**owned paths:** a"), None);
    }

    #[test]
    fn a_pull_request_is_read_with_exactly_its_shape() {
        let read = pull_request(PR.as_bytes()).expect("the good pull request");
        assert_eq!(read.number.get(), 40);
        assert_eq!(
            read.state,
            PrState::Merged {
                merge_commit: Commit::parse(&"b".repeat(40)).expect("commit"),
                merged_at: Timestamp(1_793_385_000_000),
            }
        );
        let good: Value = serde_json::from_str(PR).expect("JSON");
        let mutate = |f: &dyn Fn(&mut Value)| {
            let mut v = good.clone();
            f(&mut v);
            v.to_string()
        };
        let open = |v: &mut Value| {
            v["state"] = "OPEN".into();
            v["mergeCommit"] = Value::Null;
            v["mergedAt"] = Value::Null;
        };
        assert_eq!(
            pull_request(mutate(&open).as_bytes()).map(|p| p.state),
            Ok(PrState::Open)
        );
        let bad = [
            PR.replacen("{\"baseRefName\"", "{\"number\":41,\"baseRefName\"", 1),
            mutate(&|v| v["state"] = "OPEN".into()),
            mutate(&|v| v["mergedAt"] = Value::Null),
            mutate(&|v| v["mergeCommit"] = Value::Null),
            mutate(&|v| {
                open(v);
                v["state"] = "MERGED".into();
            }),
            mutate(&|v| v["state"] = "merged".into()),
            mutate(&|v| v["mergedAt"] = "2026-10-30 18:30:00".into()),
            mutate(&|v| v["mergedAt"] = "2026-02-30T18:30:00Z".into()),
            mutate(&|v| v["mergedAt"] = serde_json::json!(1_793_385_000_000_u64)),
            mutate(&|v| v["mergeCommit"]["oid"] = "B".repeat(40).into()),
            mutate(&|v| v["headRefOid"] = "4444".into()),
            mutate(&|v| v["isDraft"] = "false".into()),
            mutate(&|v| v["headRefName"] = "".into()),
            mutate(&|v| v["number"] = serde_json::json!(40.0)),
            mutate(&|v| v["closingIssuesReferences"][0]["number"] = "4".into()),
            mutate(&|v| {
                v.as_object_mut()
                    .expect("object")
                    .remove("closingIssuesReferences");
            }),
        ];
        for text in bad {
            assert!(
                matches!(
                    pull_request(text.as_bytes()),
                    Err(SourceError::Malformed { .. })
                ),
                "{text}"
            );
        }
    }

    #[test]
    fn checks_verdicts_and_the_read_back_take_only_their_shapes() {
        assert_eq!(
            checks(br#"[{"bucket":"pass","name":"rust"},{"bucket":"cancel","name":"web"}]"#)
                .map(|c| c.iter().map(|c| c.result).collect::<Vec<_>>()),
            Ok(vec![CheckResult::Pass, CheckResult::Cancel])
        );
        for bad in [
            &br#"[{"bucket":"PASS","name":"rust"}]"#[..],
            br#"[{"bucket":"success","name":"rust"}]"#,
            br#"[{"bucket":{"pass":null},"name":"rust"}]"#,
            br#"[{"bucket":"pass","name":"rust","state":"SUCCESS"}]"#,
            br#"[{"bucket":"pass","bucket":"fail","name":"rust"}]"#,
            br#"[["pass","rust"]]"#,
            br#"{"bucket":"pass","name":"rust"}"#,
        ] {
            assert!(checks(bad).is_err(), "{}", String::from_utf8_lossy(bad));
        }
        assert_eq!(verdict_comments(b"[]"), Ok(vec![]));
        assert_eq!(
            verdict_comments(br#"["VERDICT: APPROVE at x"]"#),
            Ok(vec!["VERDICT: APPROVE at x".to_owned()])
        );
        for bad in [
            &b"null"[..],
            br#"["Synthetic"]"#,
            br#"[1]"#,
            br#""VERDICT: x""#,
        ] {
            assert!(
                verdict_comments(bad).is_err(),
                "{}",
                String::from_utf8_lossy(bad)
            );
        }
        assert_eq!(on_base(br#"{"ahead_by":0}"#), Ok(true));
        assert_eq!(on_base(br#"{"ahead_by":2}"#), Ok(false));
        for bad in [
            &br#"{"ahead_by":0,"ahead_by":1}"#[..],
            br#"{"ahead_by":0.0}"#,
            br#"{"ahead_by":-1}"#,
            br#"{"ahead_by":null}"#,
            br#"{"ahead_by":"0"}"#,
            br#"{"ahead_by":0,"status":"ahead"}"#,
            br#"[0]"#,
            b"0",
        ] {
            assert!(on_base(bad).is_err(), "{}", String::from_utf8_lossy(bad));
        }
        assert_eq!(
            repository(
                br#"{"nameWithOwner":"syn-owner/example-repo","url":"https://example.invalid/synthetic/repo"}"#
            )
            .map(|r| (r.name.as_str().to_owned(), r.name_with_owner.as_str().to_owned())),
            Ok(("example-repo".to_owned(), "syn-owner/example-repo".to_owned()))
        );
        for bad in [
            &br#"{"nameWithOwner":"o/r"}"#[..],
            br#"{"name":"r","url":"u"}"#,
            br#"{"nameWithOwner":"","url":"u"}"#,
            br#"{"nameWithOwner":"example-repo","url":"u"}"#,
            br#"{"nameWithOwner":"/r","url":"u"}"#,
            br#"{"nameWithOwner":"o/","url":"u"}"#,
            br#"{"nameWithOwner":"o/r/x","url":"u"}"#,
            br#"{"nameWithOwner":"o/r","nameWithOwner":"o/s","url":"u"}"#,
            br#"{"nameWithOwner":"o/r","url":"u","owner":{"login":"x"}}"#,
        ] {
            assert!(repository(bad).is_err(), "{}", String::from_utf8_lossy(bad));
        }
    }

    #[test]
    fn a_time_is_iso_8601_utc_to_the_second() {
        assert_eq!(iso_ms("1970-01-01T00:00:00Z"), Some(Timestamp(0)));
        assert_eq!(
            iso_ms("2026-10-30T18:30:00Z"),
            Some(Timestamp(1_793_385_000_000))
        );
        assert_eq!(
            iso_ms("2024-02-29T23:59:59Z"),
            Some(Timestamp(1_709_251_199_000))
        );
        for bad in [
            "2023-02-29T00:00:00Z",
            "2026-13-01T00:00:00Z",
            "2026-10-30T24:00:00Z",
            "2026-10-30T18:30:00.000Z",
            "2026-10-30T18:30:00+00:00",
            "2026-10-30t18:30:00Z",
            "1969-12-31T23:59:59Z",
            "+026-10-30T18:30:00Z",
        ] {
            assert_eq!(iso_ms(bad), None, "{bad}");
        }
    }
    const SETTINGS: &str = "# Fleet\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Fallback | today's account |\n| Record authors | `synthetic-app[bot]`, `Synthetic-Owner` |\n\n## Next\n";

    fn authors() -> RecordAuthors {
        RecordAuthors::read(SETTINGS).unwrap()
    }

    #[test]
    fn stock_issue_counts_only_the_factorys_start_records_in_its_last_fifteen() {
        let row = |login: &str, kind: &str, body: Value| serde_json::json!({"login": login, "type": kind, "body": body});
        let factory = |body: &str| row("synthetic-app[bot]", "Bot", body.into());
        let read = |pages: &[Value]| {
            let lines: String = pages.iter().map(|p| p.to_string() + "\n").collect();
            stock_issue(ISSUE.as_bytes(), lines.as_bytes(), &authors())
        };
        let started = |rows: &[Value]| {
            read(&[Value::Array(rows.to_vec())]).unwrap().1
                == openwiz_core::model::Fact::Known(true)
        };
        let mut rows = vec![factory("launch-fleet: started")];
        rows.extend((0..15).map(|_| row("synthetic-owner", "User", "synthetic progress".into())));
        assert!(
            !started(&rows),
            "the factory's own last fifteen hold no start"
        );
        rows[15] = factory("launch-fleet: start checked");
        assert!(started(&rows));
        rows[15] = factory("progress launch-fleet: started");
        assert!(!started(&rows));
        assert!(read(&[]).is_err(), "no pages");
        for bad in [
            row("synthetic-app[bot]", "Bot", Value::Null),
            serde_json::json!({"login": "synthetic-app[bot]", "body": "launch-fleet: started"}),
            serde_json::json!({"login": "synthetic-app[bot]", "type": "Bot", "body": "x", "extra": 1}),
            serde_json::json!({"login": 1, "type": "Bot", "body": "x"}),
        ] {
            rows[0] = bad.clone();
            assert!(read(&[Value::Array(rows.clone())]).is_err(), "{bad}");
        }
        assert!(read(&[serde_json::json!({})]).is_err(), "a page is a list");
    }

    #[test]
    fn record_authors_take_only_the_whole_well_formed_row() {
        let table = |row: &str| {
            format!("## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n{row}\n")
        };
        let good = RecordAuthors::read(&table(
            "| Record authors | `synthetic-app[bot]`, `Synthetic-Owner` |",
        ))
        .unwrap();
        for (login, kind, wrote) in [
            (Some("synthetic-app[bot]"), Some("Bot"), true),
            (Some("SYNTHETIC-APP[BOT]"), Some("Bot"), true),
            (Some("synthetic-app[bot]"), Some("User"), false),
            (Some("synthetic-app"), Some("Bot"), false),
            (Some("synthetic-app"), Some("User"), false),
            (Some("synthetic-owner"), Some("User"), true),
            (Some("synthetic-owner"), Some("Bot"), false),
            (Some("synthetic-owner"), Some("Organization"), false),
            (Some("synthetic-owner"), None, false),
            (Some("synthetic-owner2"), Some("User"), false),
            (Some(""), Some("User"), false),
            (None, Some("Bot"), false),
        ] {
            assert_eq!(good.wrote(login, kind), wrote, "{login:?} {kind:?}");
        }
        assert_eq!(
            good,
            authors(),
            "spacing around cells and other rows don't matter"
        );
        for row in [
            "|Record authors|`a`|",
            "|  Record authors  |  `a` ,`b-c`  |  ",
        ] {
            assert!(RecordAuthors::read(&table(row)).is_ok(), "{row}");
        }
        let refused = |text: &str| RecordAuthors::read(text).is_err();
        for row in [
            "| Record authors | |",
            "| Record authors | `` |",
            "| Record authors | synthetic-app[bot] |",
            "| Record authors | `synthetic-app[bot]`, |",
            "| Record authors | `synthetic-app[bot]` `synthetic-owner` |",
            "| Record authors | `synthetic-app[bot]`, synthetic-owner |",
            "| Record authors | `-synthetic` |",
            "| Record authors | `synthetic-` |",
            "| Record authors | `synthetic--owner` |",
            "| Record authors | `synthetic owner` |",
            "| Record authors | ` synthetic` |",
            "| Record authors | `synthetic[app]` |",
            "| Record authors | `[bot]` |",
            "| Record authors | `synthetic_owner` |",
            "| Record authors | `synthétic` |",
            "| Record authors | `synthetic-app[bot]` | extra |",
            "| Record authors | `synthetic-app[bot]` | |",
            "| Record authors | `synthetic-app[bot]`",
            "| Record authors | `synthetic-app[bot]` |\n| Record authors | `synthetic-owner` |",
        ] {
            assert!(refused(&table(row)), "{row}");
        }
        assert!(refused("# Fleet\n"));
        assert!(refused(&table("| Fallback | today's account |")));
        assert!(refused(
            "## GitHub identityx\n\n| Record authors | `synthetic-owner` |\n"
        ));
        assert!(refused(&format!(
            "{}## Next\n\n| Record authors | `synthetic-owner` |\n",
            table("| Fallback | today's account |")
        )));
    }

    #[test]
    fn the_start_record_reader_reads_each_authors_type() {
        use serde_json::json;
        let start = "launch-fleet: started";
        let row = |login: &str, kind: &str, body: &str| json!({"login": login, "type": kind, "body": body});
        let app = |body: &str| row("synthetic-app[bot]", "Bot", body);
        let outsider = |body: &str| row("synthetic-outsider", "User", body);
        let flood: Vec<Value> = (0..15).map(|_| outsider("synthetic progress")).collect();
        let later: Vec<Value> = (0..15).map(|_| app("synthetic progress")).collect();
        let cases: Vec<(Vec<Vec<Value>>, bool)> = vec![
            (vec![vec![app(start)]], true),
            (vec![vec![row("synthetic-app", "User", start)]], false),
            (vec![vec![row("Synthetic-App[bot]", "User", start)]], false),
            (vec![vec![outsider(start)]], false),
            (vec![vec![app(start)], flood.clone()], true),
            (
                vec![vec![outsider("synthetic progress")], vec![app(start)]],
                true,
            ),
            (vec![vec![app(start)], later], false),
            (
                vec![vec![json!({"login": null, "type": null, "body": start})]],
                false,
            ),
        ];
        for (pages, started) in cases {
            let rest: String = pages
                .iter()
                .map(|page| serde_json::to_string(page).unwrap() + "\n")
                .collect();
            let tickets = Tickets::with_executor(process::Executor::supplied(std::sync::Arc::new(
                move |call: &Invocation, _| {
                    let argv: Vec<&str> = call.argv().iter().map(String::as_str).collect();
                    let mut issue: Value = serde_json::from_str(ISSUE).unwrap();
                    issue["comments"] = json!([{"id":"synthetic-comment","author":{"login":"synthetic-app"},"authorAssociation":"NONE","body":start,"createdAt":"2030-01-15T09:00:00Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":"https://example.invalid/issues/1#synthetic","viewerDidAuthor":false}]);
                    let answer = match argv.as_slice() {
                        ["repo", "view", ..] => json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic/repo","url":"https://example.invalid/synthetic/repo"}).to_string(),
                        ["api", p, ..] if p.contains("/git/ref/heads/") => json!({"sha":"a".repeat(40)}).to_string(),
                        ["api", p, ..] if p.contains("/contents/docs/agents/fleet.md") => SETTINGS.to_owned(),
                        ["issue", "view", "1", ..] => issue.to_string(),
                        ["api", p, "--paginate", ..] if p.contains("/issues/1/comments") => rest.clone(),
                        _ => return Err(malformed("synthetic gh", "unexpected call")),
                    };
                    Ok(answer.into_bytes())
                },
            )));
            let read = tickets
                .stock_issue(
                    Number::new(1).unwrap(),
                    Instant::now() + std::time::Duration::from_secs(5),
                )
                .unwrap();
            assert_eq!(
                read.1,
                openwiz_core::model::Fact::Known(started),
                "{pages:?}"
            );
        }
    }
}
