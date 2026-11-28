use std::fmt;
use std::num::NonZeroU64;
use std::path::PathBuf;
use std::time::Instant;

use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::fleets::{
    FleetsSource, IssueRow, Link, Links, Listed, MERGE_BATCH_SIZE, PrFacts, PrRow, StockPr,
};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Failed, IssueState, MergedPr, Milestone, NonEmpty, Number,
    Repository,
};
use openwiz_core::model::Timestamp;
use openwiz_core::ops::is_version_text;
use openwiz_core::source::SourceError;
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};

use crate::allowlist::{Invocation, Module};
use crate::{PROGRAM, process};

pub const TESTED_VERSION: &str = "2.100.0";

pub const LIST_LIMIT: usize = 1000;

const LIMIT: &str = "1000";

const ISSUE_FIELDS: &str = "blockedBy,body,id,labels,milestone,number,state,subIssues,title";

pub const PR_FIELDS: &str = "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title";

const CHECK_FIELDS: &str = "bucket,name";

const COMMENTS_JQ: &str = "[.comments[].body]";

const COMPARE_JQ: &str = "{status: .status, behind_by: .behind_by}";

const COMPARE_PATH: &str = "repos/{owner}/{repo}/compare/";

pub const ALLOWLIST: Module = Module {
    name: "fleets",
    allows,
};

fn allows(argv: &[&str]) -> bool {
    match argv {
        ["--version"] | ["repo", "view", "--json", "nameWithOwner"] => true,
        [
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            LIMIT,
            "--json",
            ISSUE_FIELDS,
        ] => true,
        [
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            LIMIT,
            "--json",
            PR_FIELDS,
        ] => true,
        ["pr", "checks", n, "--json", CHECK_FIELDS] => is_number(n),
        ["pr", "view", n, "--json", "comments", "--jq", COMMENTS_JQ] => is_number(n),
        ["api", path, "--jq", COMPARE_JQ] => is_compare_path(path),
        ["api", "graphql", ..] => allows_batch(argv),
        _ => false,
    }
}

fn allows_batch(argv: &[&str]) -> bool {
    if argv.len() < 12 || !(argv.len() - 8).is_multiple_of(4) {
        return false;
    }
    let n = (argv.len() - 8) / 4;
    if n > MERGE_BATCH_SIZE {
        return false;
    }
    let mut pairs = Vec::new();
    for i in 0..n {
        let Some(base) = argv[9 + 4 * i].strip_prefix(&format!("base{i}=refs/heads/")) else {
            return false;
        };
        let Some(head) = argv[11 + 4 * i].strip_prefix(&format!("head{i}=")) else {
            return false;
        };
        if !is_branch(base) || Commit::parse(head).is_none() {
            return false;
        }
        pairs.push((base, head));
    }
    batch_args(&pairs)
        .iter()
        .map(String::as_str)
        .eq(argv.iter().copied())
}

fn batch_args(pairs: &[(&str, &str)]) -> Vec<String> {
    let mut vars = String::new();
    let mut body = String::new();
    for i in 0..pairs.len() {
        vars.push_str(&format!(",$base{i}:String!,$head{i}:String!"));
        body.push_str(&format!("r{i}:ref(qualifiedName:$base{i}){{target{{oid}} comparison:compare(headRef:$head{i}){{status aheadBy behindBy baseTarget{{oid}} headTarget{{oid}}}}}}"));
    }
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
    args.push(format!("query=query($owner:String!,$name:String!{vars}){{repository(owner:$owner,name:$name){{{body}}}}}"));
    for (i, (base, head)) in pairs.iter().enumerate() {
        args.extend([
            "-f".into(),
            format!("base{i}=refs/heads/{base}"),
            "-f".into(),
            format!("head{i}={head}"),
        ]);
    }
    args
}

fn is_number(s: &str) -> bool {
    s.bytes().all(|b| b.is_ascii_digit()) && !s.starts_with('0') && s.parse::<NonZeroU64>().is_ok()
}

fn is_compare_path(path: &str) -> bool {
    path.strip_prefix(COMPARE_PATH)
        .and_then(|rest| rest.split_once("..."))
        .is_some_and(|(commit, branch)| Commit::parse(commit).is_some() && is_branch(branch))
}

pub fn is_branch(name: &str) -> bool {
    !name.contains("..")
        && name.split('/').all(|seg| {
            !seg.is_empty()
                && !seg.starts_with(['.', '-'])
                && seg
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
        })
}

pub struct GitHubFleets {
    executor: process::Executor,
}

impl GitHubFleets {
    pub fn from_path() -> Self {
        Self::with_program(PROGRAM)
    }

    pub fn with_program(program: impl Into<PathBuf>) -> Self {
        Self::with_executor(process::Executor::program(program))
    }

    pub fn with_executor(executor: process::Executor) -> Self {
        Self { executor }
    }

    fn call(&self, read: &str, argv: &[&str], deadline: Instant) -> Result<Vec<u8>, Failed> {
        let Some(invocation) = Invocation::new(argv) else {
            return Err(failed(
                GapKind::CommandFailed,
                format!("{read} was not run: it isn't on the allowlist"),
            ));
        };
        self.executor
            .run(&invocation, deadline)
            .map_err(|e| failure(read, &e))
    }

    fn json<T>(
        &self,
        read: &str,
        argv: &[&str],
        deadline: Instant,
        read_answer: impl FnOnce(&Json) -> Got<T>,
    ) -> Result<T, Failed> {
        let out = self.call(read, argv, deadline)?;
        parse_with_strict_json(&out, read, read_answer)
    }
}

fn parse_with_strict_json<T>(
    out: &[u8],
    read: &str,
    read_answer: impl FnOnce(&Json) -> Got<T>,
) -> Result<T, Failed> {
    let tree = serde_json::from_slice::<StrictJson>(out).map_err(|_| {
        failed(
            GapKind::Malformed,
            format!("{read} printed something that isn't one JSON value with each key once"),
        )
    })?;
    read_answer(&tree.0).map_err(|bad| bad.failed(read))
}

fn parse_issues(out: &[u8]) -> Result<Vec<IssueRow>, Failed> {
    match fast::parse_issues(out) {
        Ok(rows) => Ok(rows),
        Err(()) => parse_with_strict_json(out, "gh issue list", |v| list(v, "", issue_row)),
    }
}

fn parse_stock_prs(out: &[u8]) -> Result<Vec<StockPr>, Failed> {
    match fast::parse_stock_prs(out) {
        Ok(rows) => Ok(rows),
        Err(()) => parse_with_strict_json(out, "gh pr list", |v| list(v, "", stock_pr_row)),
    }
}

fn parse_checks(out: &[u8], read: &str) -> Result<Vec<Check>, Failed> {
    match fast::parse_checks(out) {
        Ok(rows) => Ok(rows),
        Err(()) => parse_with_strict_json(out, read, |v| list(v, "", check)),
    }
}

fn parse_comments(out: &[u8], read: &str) -> Result<Vec<String>, Failed> {
    match serde_json::from_slice::<Vec<String>>(out) {
        Ok(rows) => Ok(rows),
        Err(_) => parse_with_strict_json(out, read, |v| {
            list(v, "", |v, at| string(v, at).map(str::to_owned))
        }),
    }
}

impl FleetsSource for GitHubFleets {
    fn tested_version(&self) -> &str {
        TESTED_VERSION
    }

    fn version(&self, deadline: Instant) -> Result<NonEmpty, Failed> {
        let read = "gh --version";
        let out = self
            .call(read, &["--version"], deadline)
            .map_err(|f| Failed {
                gap: GapKind::UntestedVersion,
                reason: f.reason,
            })?;
        version_of(&out).ok_or_else(|| {
            failed(
                GapKind::UntestedVersion,
                format!("{read} printed no recognised version (withheld)"),
            )
        })
    }

    fn repository(&self, deadline: Instant) -> Result<Repository, Failed> {
        let argv = ["repo", "view", "--json", "nameWithOwner"];
        self.json("gh repo view", &argv, deadline, repository_of)
    }

    fn issues(&self, deadline: Instant) -> Result<Listed<IssueRow>, Failed> {
        let argv = [
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            LIMIT,
            "--json",
            ISSUE_FIELDS,
        ];
        let out = self.call("gh issue list", &argv, deadline)?;
        let rows = parse_issues(&out)?;
        Ok(listed(rows))
    }

    fn pull_requests(&self, deadline: Instant) -> Result<Listed<PrRow>, Failed> {
        self.stock_pull_requests(deadline).map(|listed| Listed {
            cut_short: listed.cut_short,
            rows: listed.rows.into_iter().map(|row| row.pr).collect(),
        })
    }

    fn stock_pull_requests(&self, deadline: Instant) -> Result<Listed<StockPr>, Failed> {
        let argv = [
            "pr", "list", "--state", "all", "--limit", LIMIT, "--json", PR_FIELDS,
        ];
        let out = self.call("gh pr list", &argv, deadline)?;
        let rows = parse_stock_prs(&out)?;
        Ok(listed(rows))
    }

    fn checks(&self, pr: Number, deadline: Instant) -> Result<Vec<Check>, Failed> {
        let n = pr.to_string();
        let argv = ["pr", "checks", n.as_str(), "--json", CHECK_FIELDS];
        let read = format!("gh pr checks {n}");
        let invocation = Invocation::new(&argv).ok_or_else(|| {
            failed(
                GapKind::CommandFailed,
                format!("{read} was not run: it isn't on the allowlist"),
            )
        })?;
        let out = self
            .executor
            .checks(&invocation, deadline)
            .map_err(|e| failure(&read, &e))?;
        parse_checks(&out, &read)
    }

    fn comments(&self, pr: Number, deadline: Instant) -> Result<Vec<String>, Failed> {
        let n = pr.to_string();
        let argv = [
            "pr",
            "view",
            n.as_str(),
            "--json",
            "comments",
            "--jq",
            COMMENTS_JQ,
        ];
        let read = format!("gh pr view {n}'s comments");
        let out = self.call(&read, &argv, deadline)?;
        parse_comments(&out, &read)
    }

    fn on_base(&self, pr: &MergedPr, deadline: Instant) -> Result<bool, Failed> {
        let path = format!(
            "{COMPARE_PATH}{}...{}",
            pr.merge_commit.as_str(),
            pr.fields.base_branch.as_str()
        );
        let read = format!("the merge read back of pull request #{}", pr.fields.number);
        if !is_branch(pr.fields.base_branch.as_str()) {
            return Err(non_plain_base(pr.fields.number));
        }
        self.json(
            &read,
            &["api", path.as_str(), "--jq", COMPARE_JQ],
            deadline,
            on_base_of,
        )
    }

    fn on_bases(&self, prs: &[MergedPr], deadline: Instant) -> Vec<Result<bool, Failed>> {
        let plain: Vec<_> = prs
            .iter()
            .filter(|pr| is_branch(pr.fields.base_branch.as_str()))
            .cloned()
            .collect();
        let answers = if plain.is_empty() {
            Vec::new()
        } else {
            let read = "the merge ancestry batch";
            let pairs: Vec<_> = plain
                .iter()
                .map(|pr| (pr.fields.base_branch.as_str(), pr.merge_commit.as_str()))
                .collect();
            let argv = batch_args(&pairs);
            let argv: Vec<_> = argv.iter().map(String::as_str).collect();
            match self.json(read, &argv, deadline, |v| batch_of(v, &plain)) {
                Ok(answers) => answers
                    .into_iter()
                    .map(|a| a.map_err(|b| b.failed(read)))
                    .collect(),
                Err(f) => vec![Err(f); plain.len()],
            }
        };
        let mut answers = answers.into_iter();
        prs.iter()
            .map(|pr| {
                if is_branch(pr.fields.base_branch.as_str()) {
                    answers.next().expect("one answer per plain-base input")
                } else {
                    Err(non_plain_base(pr.fields.number))
                }
            })
            .collect()
    }
}

fn non_plain_base(pr: Number) -> Failed {
    failed(
        GapKind::Malformed,
        format!(
            "the merge read back of pull request #{pr} was not run: its base isn't a plain branch name"
        ),
    )
}

fn failed(gap: GapKind, reason: String) -> Failed {
    Failed {
        gap,
        reason: NonEmpty::new(reason).expect("a reason is never empty"),
    }
}

fn failure(read: &str, e: &SourceError) -> Failed {
    match e {
        SourceError::CommandFailed {
            exit_code: Some(code),
            detail,
        } => failed(
            GapKind::CommandFailed,
            format!("{read} exited {code}: {detail}"),
        ),
        SourceError::CommandFailed {
            exit_code: None, ..
        } => failed(
            GapKind::CommandFailed,
            format!("{read} ended without an exit code (detail withheld)"),
        ),
        SourceError::TimedOut { after_ms } => failed(
            GapKind::TimedOut,
            format!("{read} timed out after {after_ms} ms"),
        ),
        SourceError::Malformed { detail } => failed(GapKind::Malformed, format!("{read} {detail}")),
        SourceError::Unavailable { .. }
        | SourceError::NotFound { .. }
        | SourceError::InvalidId { .. } => failed(
            GapKind::CommandFailed,
            format!("{read} could not be run (detail withheld)"),
        ),
    }
}

fn listed<T>(rows: Vec<T>) -> Listed<T> {
    Listed {
        cut_short: rows.len() >= LIST_LIMIT,
        rows,
    }
}

fn version_of(out: &[u8]) -> Option<NonEmpty> {
    let text = std::str::from_utf8(out).ok()?;
    let line = text.lines().next()?.strip_prefix("gh version ")?;
    let version = match line.split_once(" (") {
        None => line,
        Some((version, date)) => {
            let date = date.strip_suffix(')')?;
            let dated = date.len() == 10
                && date.bytes().enumerate().all(|(i, b)| match i {
                    4 | 7 => b == b'-',
                    _ => b.is_ascii_digit(),
                });
            dated.then_some(version)?
        }
    };
    (is_version_text(version) && !version.starts_with('v'))
        .then(|| NonEmpty::new(version))
        .flatten()
}

#[derive(Clone, Debug, PartialEq)]
enum Json {
    Null,
    Bool(bool),
    Int(i128),
    Fraction,
    String(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

struct StrictJson(Json);

struct JsonVisitor;

impl<'de> Visitor<'de> for JsonVisitor {
    type Value = Json;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value with no key given twice")
    }

    fn visit_unit<E: de::Error>(self) -> Result<Json, E> {
        Ok(Json::Null)
    }

    fn visit_bool<E: de::Error>(self, b: bool) -> Result<Json, E> {
        Ok(Json::Bool(b))
    }

    fn visit_i64<E: de::Error>(self, n: i64) -> Result<Json, E> {
        Ok(Json::Int(n.into()))
    }

    fn visit_u64<E: de::Error>(self, n: u64) -> Result<Json, E> {
        Ok(Json::Int(n.into()))
    }

    fn visit_f64<E: de::Error>(self, _: f64) -> Result<Json, E> {
        Ok(Json::Fraction)
    }

    fn visit_str<E: de::Error>(self, s: &str) -> Result<Json, E> {
        Ok(Json::String(s.to_owned()))
    }

    fn visit_string<E: de::Error>(self, s: String) -> Result<Json, E> {
        Ok(Json::String(s))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Json, A::Error> {
        let mut items = Vec::new();
        while let Some(StrictJson(item)) = seq.next_element()? {
            items.push(item);
        }
        Ok(Json::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Json, A::Error> {
        let mut entries: Vec<(String, Json)> = Vec::new();
        while let Some(key) = map.next_key::<String>()? {
            if entries.iter().any(|(k, _)| *k == key) {
                return Err(de::Error::custom("a key given twice"));
            }
            let StrictJson(value) = map.next_value()?;
            entries.push((key, value));
        }
        Ok(Json::Object(entries))
    }
}

impl<'de> Deserialize<'de> for StrictJson {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(JsonVisitor).map(StrictJson)
    }
}

#[derive(Debug, PartialEq, Eq)]
struct Bad {
    gap: GapKind,
    at: String,
    what: &'static str,
}

impl Bad {
    fn failed(self, read: &str) -> Failed {
        let at = if self.at.is_empty() { "." } else { &self.at };
        failed(
            self.gap,
            format!(
                "{read} printed an answer OpenWiz can't read: {at}: {}",
                self.what
            ),
        )
    }
}

type Got<T> = Result<T, Bad>;

fn bad<T>(gap: GapKind, at: &str, what: &'static str) -> Got<T> {
    Err(Bad {
        gap,
        at: at.to_owned(),
        what,
    })
}

fn object<'j>(v: &'j Json, at: &str, keys: &[&str]) -> Got<Vec<&'j Json>> {
    let Json::Object(entries) = v else {
        return bad(GapKind::WrongType, at, "not an object");
    };
    if entries.iter().any(|(k, _)| !keys.contains(&k.as_str())) {
        return bad(GapKind::Malformed, at, "a key it shouldn't have");
    }
    keys.iter()
        .map(|key| match entries.iter().find(|(k, _)| k == key) {
            Some((_, value)) => Ok(value),
            None => bad(GapKind::MissingField, &format!("{at}.{key}"), "missing"),
        })
        .collect()
}

fn list<T>(v: &Json, at: &str, item: impl Fn(&Json, &str) -> Got<T>) -> Got<Vec<T>> {
    let Json::Array(items) = v else {
        return bad(GapKind::WrongType, at, "not a list");
    };
    items
        .iter()
        .enumerate()
        .map(|(i, v)| item(v, &format!("{at}[{i}]")))
        .collect()
}

fn string<'j>(v: &'j Json, at: &str) -> Got<&'j str> {
    match v {
        Json::String(s) => Ok(s),
        _ => bad(GapKind::WrongType, at, "not text"),
    }
}

fn non_empty(v: &Json, at: &str) -> Got<NonEmpty> {
    match NonEmpty::new(string(v, at)?) {
        Some(s) => Ok(s),
        None => bad(GapKind::Malformed, at, "empty"),
    }
}

fn boolean(v: &Json, at: &str) -> Got<bool> {
    match v {
        Json::Bool(b) => Ok(*b),
        _ => bad(GapKind::WrongType, at, "not true or false"),
    }
}

fn count(v: &Json, at: &str) -> Got<u64> {
    match v {
        Json::Int(n) => u64::try_from(*n).or_else(|_| bad(GapKind::Malformed, at, "below zero")),
        _ => bad(GapKind::WrongType, at, "not a whole number"),
    }
}

fn number(v: &Json, at: &str) -> Got<Number> {
    match Number::new(count(v, at)?) {
        Some(n) => Ok(n),
        None => bad(GapKind::Malformed, at, "not 1 or more"),
    }
}

fn commit(v: &Json, at: &str) -> Got<Commit> {
    match Commit::parse(string(v, at)?) {
        Some(c) => Ok(c),
        None => bad(GapKind::Malformed, at, "not a full commit"),
    }
}

fn null_or<'j, T>(
    v: &'j Json,
    at: &str,
    read: impl FnOnce(&'j Json, &str) -> Got<T>,
) -> Got<Option<T>> {
    match v {
        Json::Null => Ok(None),
        v => read(v, at).map(Some),
    }
}

fn repository_of(v: &Json) -> Got<Repository> {
    let f = object(v, "", &["nameWithOwner"])?;
    let full = string(f[0], ".nameWithOwner")?;
    match full.split_once('/') {
        Some((owner, name)) if !owner.is_empty() && !name.is_empty() && !name.contains('/') => {
            Ok(Repository {
                name: NonEmpty::new(name).expect("not empty"),
            })
        }
        _ => bad(GapKind::Malformed, ".nameWithOwner", "not <owner>/<name>"),
    }
}

fn issue_row(v: &Json, at: &str) -> Got<IssueRow> {
    let keys = [
        "blockedBy",
        "body",
        "id",
        "labels",
        "milestone",
        "number",
        "state",
        "subIssues",
        "title",
    ];
    let f = object(v, at, &keys)?;
    let state = match string(f[6], &format!("{at}.state"))? {
        "OPEN" => IssueState::Open,
        "CLOSED" => IssueState::Closed,
        _ => {
            return bad(
                GapKind::Malformed,
                &format!("{at}.state"),
                "not OPEN or CLOSED",
            );
        }
    };
    Ok(IssueRow {
        number: number(f[5], &format!("{at}.number"))?,
        id: non_empty(f[2], &format!("{at}.id"))?,
        title: string(f[8], &format!("{at}.title"))?.to_owned(),
        state,
        milestone: null_or(f[4], &format!("{at}.milestone"), milestone)?,
        labels: list(f[3], &format!("{at}.labels"), label)?,
        body: string(f[1], &format!("{at}.body"))?.to_owned(),
        sub_issues: links(f[7], &format!("{at}.subIssues"))?,
        blocked_by: links(f[0], &format!("{at}.blockedBy"))?,
    })
}

fn milestone(v: &Json, at: &str) -> Got<Milestone> {
    let f = object(v, at, &["description", "dueOn", "number", "title"])?;
    string(f[0], &format!("{at}.description"))?;
    null_or(f[1], &format!("{at}.dueOn"), string)?;
    Ok(Milestone {
        number: number(f[2], &format!("{at}.number"))?,
        title: string(f[3], &format!("{at}.title"))?.to_owned(),
    })
}

fn label(v: &Json, at: &str) -> Got<NonEmpty> {
    let f = object(v, at, &["color", "description", "id", "name"])?;
    for (i, key) in [(0, "color"), (1, "description"), (2, "id")] {
        string(f[i], &format!("{at}.{key}"))?;
    }
    non_empty(f[3], &format!("{at}.name"))
}

fn links(v: &Json, at: &str) -> Got<Links> {
    let f = object(v, at, &["nodes", "totalCount"])?;
    let nodes = list(f[0], &format!("{at}.nodes"), |v, at| {
        let n = object(v, at, &["id", "number", "state", "title", "url"])?;
        for (i, key) in [(2, "state"), (3, "title"), (4, "url")] {
            string(n[i], &format!("{at}.{key}"))?;
        }
        Ok(Link {
            number: number(n[1], &format!("{at}.number"))?,
            id: non_empty(n[0], &format!("{at}.id"))?,
        })
    })?;
    Ok(Links {
        nodes,
        total: count(f[1], &format!("{at}.totalCount"))?,
    })
}

#[cfg(test)]
fn pr_row(v: &Json, at: &str) -> Got<PrRow> {
    stock_pr_row(v, at).map(|row| row.pr)
}
fn stock_pr_row(v: &Json, at: &str) -> Got<StockPr> {
    let keys = [
        "baseRefName",
        "closingIssuesReferences",
        "headRefName",
        "headRefOid",
        "isDraft",
        "mergeCommit",
        "mergedAt",
        "number",
        "state",
        "title",
    ];
    let f = object(v, at, &keys)?;
    let p = |key: &str| format!("{at}.{key}");
    let title = openwiz_core::model::Fact::Known(non_empty(f[9], &p("title"))?);
    let number = number(f[7], &p("number"))?;
    let draft = boolean(f[4], &p("isDraft"))?;
    let closes = list(f[1], &p("closingIssuesReferences"), closing_reference)?;
    let merge = null_or(f[5], &p("mergeCommit"), |v, at| {
        let m = object(v, at, &["oid"])?;
        Ok(m[0])
    })?;
    let merged_at = null_or(f[6], &p("mergedAt"), string)?;
    let state = string(f[8], &p("state"))?;
    if state == "CLOSED" {
        if merge.is_some() || merged_at.is_some() {
            return bad(GapKind::Malformed, at, "closed, with a merge");
        }
        for (i, key) in [(0, "baseRefName"), (2, "headRefName"), (3, "headRefOid")] {
            string(f[i], &p(key))?;
        }
        return Ok(StockPr {
            pr: PrRow::Closed { number },
            title,
        });
    }
    let facts = PrFacts {
        number,
        draft,
        head_branch: non_empty(f[2], &p("headRefName"))?,
        head_commit: commit(f[3], &p("headRefOid"))?,
        base_branch: non_empty(f[0], &p("baseRefName"))?,
        closes,
    };
    match (state, merge, merged_at) {
        ("OPEN", None, None) => Ok(StockPr {
            pr: PrRow::Open(facts),
            title,
        }),
        ("OPEN", ..) => bad(GapKind::Malformed, at, "open, with a merge"),
        ("MERGED", Some(oid), Some(at_text)) => Ok(StockPr {
            pr: PrRow::Merged {
                facts,
                merge_commit: commit(oid, &p("mergeCommit.oid"))?,
                merged_at: match time(at_text) {
                    Some(t) => t,
                    None => return bad(GapKind::Malformed, &p("mergedAt"), "not a UTC time"),
                },
            },
            title,
        }),
        ("MERGED", ..) => bad(GapKind::MissingField, at, "merged, without its merge"),
        _ => bad(
            GapKind::Malformed,
            &p("state"),
            "not OPEN, MERGED or CLOSED",
        ),
    }
}

fn closing_reference(v: &Json, at: &str) -> Got<Link> {
    let f = object(v, at, &["id", "number", "repository", "url"])?;
    let r = object(f[2], &format!("{at}.repository"), &["id", "name", "owner"])?;
    string(r[0], &format!("{at}.repository.id"))?;
    string(r[1], &format!("{at}.repository.name"))?;
    let o = object(r[2], &format!("{at}.repository.owner"), &["id", "login"])?;
    string(o[0], &format!("{at}.repository.owner.id"))?;
    string(o[1], &format!("{at}.repository.owner.login"))?;
    string(f[3], &format!("{at}.url"))?;
    Ok(Link {
        number: number(f[1], &format!("{at}.number"))?,
        id: non_empty(f[0], &format!("{at}.id"))?,
    })
}

fn check(v: &Json, at: &str) -> Got<Check> {
    let f = object(v, at, &["bucket", "name"])?;
    let result = match string(f[0], &format!("{at}.bucket"))? {
        "pass" => CheckResult::Pass,
        "fail" => CheckResult::Fail,
        "pending" => CheckResult::Pending,
        "skipping" => CheckResult::Skipping,
        "cancel" => CheckResult::Cancel,
        _ => {
            return bad(
                GapKind::Malformed,
                &format!("{at}.bucket"),
                "not one of gh's buckets",
            );
        }
    };
    Ok(Check {
        name: non_empty(f[1], &format!("{at}.name"))?,
        result,
    })
}

fn on_base_of(v: &Json) -> Got<bool> {
    let f = object(v, "", &["status", "behind_by"])?;
    let behind = count(f[1], ".behind_by")?;
    match (string(f[0], ".status")?, behind) {
        ("ahead" | "identical", 0) => Ok(true),
        ("ahead" | "identical", _) => bad(GapKind::Malformed, "", "on its base, yet behind it"),
        ("behind" | "diverged", _) => Ok(false),
        _ => bad(
            GapKind::Malformed,
            ".status",
            "not one of GitHub's compare states",
        ),
    }
}

fn batch_of(v: &Json, prs: &[MergedPr]) -> Got<Vec<Got<bool>>> {
    let Json::Object(root) = v else {
        return bad(GapKind::WrongType, "", "not an object");
    };
    let has_errors = root.iter().any(|(k, _)| k == "errors");
    let top = object(
        v,
        "",
        if has_errors {
            &["data", "errors"]
        } else {
            &["data"]
        },
    )?;
    if has_errors && !matches!(top[1], Json::Array(errors) if errors.is_empty()) {
        return bad(GapKind::Malformed, ".errors", "GraphQL reported errors");
    }
    let data = object(top[0], ".data", &["repository"])?;
    let Json::Object(repo) = data[0] else {
        return bad(GapKind::WrongType, ".data.repository", "not an object");
    };
    let aliases: Vec<_> = (0..prs.len()).map(|i| format!("r{i}")).collect();
    if repo.iter().any(|(k, _)| !aliases.contains(k)) {
        return bad(
            GapKind::Malformed,
            ".data.repository",
            "an unexpected alias",
        );
    }
    Ok(prs
        .iter()
        .zip(aliases)
        .map(|(pr, alias)| {
            let at = format!(".data.repository.{alias}");
            match repo.iter().find(|(k, _)| k == &alias) {
                Some((_, value)) => ancestry_of(value, &at, &pr.merge_commit),
                None => bad(GapKind::MissingField, &at, "missing"),
            }
        })
        .collect())
}

fn ancestry_of(v: &Json, at: &str, merge: &Commit) -> Got<bool> {
    let f = object(v, at, &["target", "comparison"])?;
    let oid = |v, at: &str| -> Got<Commit> {
        let f = object(v, at, &["oid"])?;
        Commit::parse(string(f[0], at)?).ok_or(Bad {
            gap: GapKind::Malformed,
            at: at.to_owned(),
            what: "not a full commit OID",
        })
    };
    let target = oid(f[0], &format!("{at}.target"))?;
    let c = object(
        f[1],
        &format!("{at}.comparison"),
        &["status", "aheadBy", "behindBy", "baseTarget", "headTarget"],
    )?;
    let base = oid(c[3], &format!("{at}.comparison.baseTarget"))?;
    let head = oid(c[4], &format!("{at}.comparison.headTarget"))?;
    if base != target || &head != merge {
        return bad(
            GapKind::Malformed,
            at,
            "comparison targets do not match the requested ancestry",
        );
    }
    let ahead = count(c[1], &format!("{at}.comparison.aheadBy"))?;
    let behind = count(c[2], &format!("{at}.comparison.behindBy"))?;
    if ahead > i32::MAX as u64 || behind > i32::MAX as u64 {
        return bad(
            GapKind::Malformed,
            at,
            "comparison count exceeds a GraphQL Int",
        );
    }
    match (
        string(c[0], &format!("{at}.comparison.status"))?,
        ahead,
        behind,
        base == head,
    ) {
        ("IDENTICAL", 0, 0, true) | ("BEHIND", 0, 1.., false) => Ok(true),
        ("AHEAD", 1.., 0, false) | ("DIVERGED", 1.., 1.., false) => Ok(false),
        _ => bad(
            GapKind::Malformed,
            at,
            "inconsistent comparison status, counts or targets",
        ),
    }
}

fn time(s: &str) -> Option<Timestamp> {
    let b = s.as_bytes();
    let shape = b.len() == 20
        && b.iter().enumerate().all(|(i, c)| match i {
            4 | 7 => *c == b'-',
            10 => *c == b'T',
            13 | 16 => *c == b':',
            19 => *c == b'Z',
            _ => c.is_ascii_digit(),
        });
    if !shape {
        return None;
    }
    let n = |r: std::ops::Range<usize>| s[r].parse::<i64>().ok();
    let (y, m, d) = (n(0..4)?, n(5..7)?, n(8..10)?);
    let (h, min, sec) = (n(11..13)?, n(14..16)?, n(17..19)?);
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    let days_in = [
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
    if !(1..=12).contains(&m) || d < 1 || d > days_in[usize::try_from(m - 1).ok()?] {
        return None;
    }
    if h > 23 || min > 59 || sec > 59 {
        return None;
    }
    let (y, m) = if m <= 2 { (y - 1, m + 9) } else { (y, m - 3) };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * m + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(Timestamp(
        ((days * 24 + h) * 60 + min) * 60_000 + sec * 1000,
    ))
}

#[path = "fleets_fast.rs"]
pub(crate) mod fast;

#[cfg(test)]
mod tests {
    use super::*;

    fn tree(text: &str) -> Json {
        serde_json::from_str::<StrictJson>(text).expect("JSON").0
    }

    #[test]
    fn a_branch_is_a_plain_name() {
        let long = "a".repeat(300);
        for good in [
            "main",
            "release-0.0.3",
            "room/syn-a1-0001",
            "a_b.c",
            "x/y/z",
            long.as_str(),
        ] {
            assert!(is_branch(good), "{good}");
        }
        for name in [
            "", "/main", "main/", "a//b", ".hidden", "-x", "a/.b", "a..b", "a b", "a?b", "a#b",
            "a%2e", "a~1", "a^", "a:b", "ü",
        ] {
            assert!(!is_branch(name), "{name:?}");
        }
    }

    #[test]
    fn the_version_is_only_a_recognised_one() {
        for (out, want) in [
            (
                "gh version 2.100.0 (2026-09-03)\nhttps://example.invalid/x\n",
                Some("2.100.0"),
            ),
            ("gh version 2.101.3 (2026-12-01)", Some("2.101.3")),
            ("gh version 2.100 (2026-09-03)", None),
            ("gh version v2.100.0 (2026-09-03)", None),
            ("gh version 2.100.0", Some("2.100.0")),
            (
                "gh version 2.100.0\nhttps://example.invalid/x\n",
                Some("2.100.0"),
            ),
            ("gh version 2.100.0 ", None),
            ("gh version 2.100.0 (", None),
            ("gh version 2.100.0 (2026-9-3)", None),
            ("gh version 2.100.0-rc1 (2026-09-03)", None),
            ("synthetic", None),
            ("", None),
        ] {
            assert_eq!(
                version_of(out.as_bytes()).as_ref().map(NonEmpty::as_str),
                want,
                "{out:?}"
            );
        }
        assert_eq!(version_of(&[0xff, 0xfe]), None);
    }

    #[test]
    fn a_time_is_gh_s_utc_form() {
        assert_eq!(time("1970-01-01T00:00:00Z"), Some(Timestamp(0)));
        assert_eq!(
            time("2026-10-30T18:30:00Z"),
            Some(Timestamp(1_793_385_000_000))
        );
        assert_eq!(
            time("2026-10-31T09:00:00Z"),
            Some(Timestamp(1_793_437_200_000))
        );
        assert_eq!(
            time("2024-02-29T23:59:59Z"),
            Some(Timestamp(1_709_251_199_000))
        );
        for t in [
            "2026-10-30T18:30:00.000Z",
            "2026-10-30T18:30:00+00:00",
            "2026-10-30 18:30:00Z",
            "2026-13-01T00:00:00Z",
            "2025-02-29T00:00:00Z",
            "2026-10-30T24:00:00Z",
            "2026-10-32T00:00:00Z",
            "",
        ] {
            assert_eq!(time(t), None, "{t}");
        }
    }

    #[test]
    fn a_reader_takes_only_the_exact_shape() {
        assert!(serde_json::from_str::<StrictJson>(r#"{"a": 1, "a": 1}"#).is_err());
        assert!(
            serde_json::from_str::<StrictJson>(
                r#"[{"bucket": "pass", "bucket": "pass", "name": "x"}]"#
            )
            .is_err()
        );
        let good = r#"[{"bucket": "pass", "name": "syn-build"}, {"bucket": "cancel", "name": "syn-test"}]"#;
        assert_eq!(list(&tree(good), "", check).map(|c| c.len()), Ok(2));
        for (text, gap) in [
            (r#"{"bucket": "pass", "name": "x"}"#, GapKind::WrongType),
            (r#"[["pass", "x"]]"#, GapKind::WrongType),
            (r#"[{"bucket": "pass"}]"#, GapKind::MissingField),
            (
                r#"[{"bucket": "pass", "name": "x", "state": "SUCCESS"}]"#,
                GapKind::Malformed,
            ),
            (r#"[{"bucket": "PASS", "name": "x"}]"#, GapKind::Malformed),
            (
                r#"[{"bucket": {"pass": null}, "name": "x"}]"#,
                GapKind::WrongType,
            ),
            (r#"[{"bucket": "pass", "name": ""}]"#, GapKind::Malformed),
            (r#"[{"bucket": "pass", "name": 1}]"#, GapKind::WrongType),
        ] {
            assert_eq!(
                list(&tree(text), "", check).map_err(|b| b.gap),
                Err(gap),
                "{text}"
            );
        }
        for (text, gap) in [
            (
                r#"{"status": "identical", "behind_by": 1.0}"#,
                GapKind::WrongType,
            ),
            (
                r#"{"status": "identical", "behind_by": "0"}"#,
                GapKind::WrongType,
            ),
            (
                r#"{"status": "identical", "behind_by": true}"#,
                GapKind::WrongType,
            ),
            (
                r#"{"status": "identical", "behind_by": -1}"#,
                GapKind::Malformed,
            ),
            (
                r#"{"status": "identical", "behind_by": 1}"#,
                GapKind::Malformed,
            ),
            (
                r#"{"status": "IDENTICAL", "behind_by": 0}"#,
                GapKind::Malformed,
            ),
            (r#"{"status": "identical"}"#, GapKind::MissingField),
            (r#"{"status": null, "behind_by": 0}"#, GapKind::WrongType),
            (r#"["identical", 0]"#, GapKind::WrongType),
        ] {
            assert_eq!(
                on_base_of(&tree(text)).map_err(|b| b.gap),
                Err(gap),
                "{text}"
            );
        }
        for (text, want) in [
            (r#"{"status": "identical", "behind_by": 0}"#, true),
            (r#"{"behind_by": 0, "status": "ahead"}"#, true),
            (r#"{"status": "behind", "behind_by": 3}"#, false),
            (r#"{"status": "diverged", "behind_by": 2}"#, false),
        ] {
            assert_eq!(on_base_of(&tree(text)), Ok(want), "{text}");
        }
        for (text, ok) in [
            (r#"{"nameWithOwner": "syn-owner/syn-repo"}"#, true),
            (r#"{"nameWithOwner": "syn-repo"}"#, false),
            (r#"{"nameWithOwner": "/syn-repo"}"#, false),
            (r#"{"nameWithOwner": "syn-owner/"}"#, false),
            (r#"{"nameWithOwner": "a/b/c"}"#, false),
            (
                r#"{"nameWithOwner": "syn-owner/syn-repo", "name": "syn-repo"}"#,
                false,
            ),
            (r#"{"name": "syn-repo"}"#, false),
        ] {
            assert_eq!(repository_of(&tree(text)).is_ok(), ok, "{text}");
        }
        assert_eq!(
            repository_of(&tree(r#"{"nameWithOwner": "syn-owner/syn-repo"}"#))
                .map(|r| r.name.as_str().to_owned()),
            Ok("syn-repo".to_owned())
        );
    }

    fn pr(fields: &str) -> String {
        format!(
            r#"[{{"title":"Synthetic stock work", "baseRefName": "main", "closingIssuesReferences": [], "headRefName": "room/syn-a",
            "headRefOid": "{}", "isDraft": false, "number": 5{fields}}}]"#,
            "1".repeat(40)
        )
    }

    #[test]
    fn a_pull_request_row_is_open_merged_or_closed_exactly() {
        let ok = |t: &str| list(&tree(t), "", pr_row);
        let merge = format!(r#"{{"oid": "{}"}}"#, "2".repeat(40));
        assert!(matches!(
            ok(&pr(
                r#", "mergeCommit": null, "mergedAt": null, "state": "OPEN""#
            ))
            .as_deref(),
            Ok([PrRow::Open(_)])
        ));
        assert!(matches!(
            ok(&pr(&format!(
                r#", "mergeCommit": {merge}, "mergedAt": "2026-10-30T18:30:00Z", "state": "MERGED""#
            )))
            .as_deref(),
            Ok([PrRow::Merged {
                merged_at: Timestamp(1_793_385_000_000),
                ..
            }])
        ));
        assert!(matches!(
            ok(&pr(
                r#", "mergeCommit": null, "mergedAt": null, "state": "CLOSED""#
            ))
            .as_deref(),
            Ok([PrRow::Closed { .. }])
        ));
        for (fields, gap) in [
            (
                format!(r#", "mergeCommit": {merge}, "mergedAt": null, "state": "OPEN""#),
                GapKind::Malformed,
            ),
            (
                r#", "mergeCommit": null, "mergedAt": null, "state": "MERGED""#.to_owned(),
                GapKind::MissingField,
            ),
            (
                format!(r#", "mergeCommit": {merge}, "mergedAt": "2026-10-30", "state": "MERGED""#),
                GapKind::Malformed,
            ),
            (
                r#", "mergeCommit": null, "mergedAt": null, "state": "open""#.to_owned(),
                GapKind::Malformed,
            ),
            (
                r#", "mergeCommit": null, "mergedAt": null, "state": "DRAFT""#.to_owned(),
                GapKind::Malformed,
            ),
            (
                r#", "mergeCommit": null, "mergedAt": null"#.to_owned(),
                GapKind::MissingField,
            ),
            (
                r#", "mergeCommit": null, "mergedAt": null, "state": "OPEN", "unexpected": "x""#
                    .to_owned(),
                GapKind::Malformed,
            ),
        ] {
            assert_eq!(
                ok(&pr(&fields)).map(|_| ()).map_err(|b| b.gap),
                Err(gap),
                "{fields}"
            );
        }
    }
    #[test]
    fn al1_pr_title_read_is_exactly_the_approved_field_expansion() {
        const FIELDS: &str = "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title";
        let argv = [
            "pr", "list", "--state", "all", "--limit", "1000", "--json", FIELDS,
        ];
        assert!(allows(&argv), "AL1 title-bearing list must be allowlisted");
        for fields in [
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state",
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title,author",
            "title",
            "title,title",
        ] {
            assert!(!allows(&[
                "pr", "list", "--state", "all", "--limit", "1000", "--json", fields
            ]));
        }
        for suffix in ["--web", "--method", "POST"] {
            let mut wrong = argv.to_vec();
            wrong.push(suffix);
            assert!(!allows(&wrong));
        }
    }
    fn al1_pr_wire(extra: &str) -> String {
        pr(&format!(
            r#", "mergeCommit":null, "mergedAt":null, "state":"OPEN"{extra}"#
        ))
        .replacen(r#""title":"Synthetic stock work", "#, "", 1)
    }
    #[test]
    fn al1_pr_title_is_required_for_every_listed_row() {
        for state in ["OPEN", "MERGED", "CLOSED"] {
            let mut missing =
                al1_pr_wire("").replace("\"state\":\"OPEN\"", &format!("\"state\":\"{state}\""));
            if state == "MERGED" {
                missing = missing
                    .replace(
                        "\"mergeCommit\":null",
                        &format!("\"mergeCommit\":{{\"oid\":\"{}\"}}", "2".repeat(40)),
                    )
                    .replace("\"mergedAt\":null", "\"mergedAt\":\"2030-01-15T09:00:00Z\"");
            }
            let valid = missing.replacen('{', r#"{"title":"Synthetic stock work","#, 1);
            assert!(list(&tree(&valid), "", pr_row).is_ok());
            assert_eq!(
                list(&tree(&missing), "", pr_row).unwrap_err().gap,
                GapKind::MissingField,
                "missing title in {state}"
            );
        }
    }
    #[test]
    fn al1_pr_title_shape_is_strict_and_not_a_tagged_value() {
        let valid = al1_pr_wire(r#", "title":"Synthetic stock work""#);
        assert!(
            list(&tree(&valid), "", pr_row).is_ok(),
            "approved title-bearing shape must be accepted"
        );
        for title in [
            "null",
            "false",
            "12",
            "[]",
            r#"{}"#,
            r#"{"known":"synthetic-a"}"#,
            r#""""#,
        ] {
            let bad = al1_pr_wire(&format!(r#", "title":{title}"#));
            assert!(list(&tree(&bad), "", pr_row).is_err(), "accepted {bad}");
        }
        let extra = al1_pr_wire(r#", "title":"synthetic-a", "unexpected":"synthetic""#);
        assert!(list(&tree(&extra), "", pr_row).is_err());
        let duplicate = al1_pr_wire(r#", "title":"synthetic-a", "title":"synthetic-b""#);
        assert!(serde_json::from_str::<StrictJson>(&duplicate).is_err());
    }

    #[test]
    fn fast_issue_reader_matches_strict_json_oracle_on_valid_and_malformed_inputs() {
        let valid_full = r#"[
            {
                "blockedBy":{"nodes":[{"id":"I_1","number":10,"state":"OPEN","title":"","url":""}],"totalCount":1},
                "body":"line1\n\"quoted\"",
                "id":"I_main",
                "labels":[{"color":"","description":"","id":"","name":"ready-for-agent"}],
                "milestone":{"description":"","dueOn":"2026-10-30T00:00:00Z","number":1,"title":""},
                "number":1,
                "state":"OPEN",
                "subIssues":{"nodes":[],"totalCount":0},
                "title":""
            },
            {
                "\u0062lockedBy":{"nodes":[],"totalCount":18446744073709551615},
                "body":"",
                "id":"I_closed",
                "labels":[],
                "milestone":null,
                "number":18446744073709551615,
                "state":"CLOSED",
                "subIssues":{"nodes":[],"totalCount":0},
                "title":"escaped \u0074itle"
            }
        ]"#;
        let cases = [
            "[]".to_owned(),
            valid_full.to_owned(),
            valid_full.replace("\"OPEN\"", "\"DRAFT\""),
            valid_full.replace("\"number\":1,", "\"number\":0,"),
            valid_full.replace("\"number\":1,", "\"number\":-1,"),
            valid_full.replace("\"number\":1,", "\"number\":1.0,"),
            valid_full.replace("\"totalCount\":1", "\"totalCount\":-1"),
            valid_full.replace("\"id\":\"I_main\",", "\"id\":\"\","),
            valid_full.replace("\"name\":\"ready-for-agent\"", "\"name\":\"\""),
            valid_full.replace("\"title\":\"\"", "\"title\":\"\", \"title\":\"dup\""),
            valid_full.replace("\"title\":\"\"", "\"title\":\"\", \"extra\":1"),
            valid_full.replace("\"milestone\":null,", ""),
            format!("{valid_full} trailing"),
            "{}".to_owned(),
            "not json".to_owned(),
        ];
        for raw in &cases {
            let bytes = raw.as_bytes();
            let old = parse_with_strict_json(bytes, "gh issue list", |v| list(v, "", issue_row));
            let new = parse_issues(bytes);
            assert_eq!(new, old, "mismatch on {raw}");
            assert_eq!(
                fast::parse_issues(bytes).ok(),
                old.ok(),
                "fast path diverged on {raw}"
            );
        }
    }

    #[test]
    fn fast_pr_and_checks_readers_match_strict_json_oracle() {
        let oid_a = "a".repeat(40);
        let oid_b = "b".repeat(40);
        let valid_prs = format!(
            r#"[
                {{"baseRefName":"main","closingIssuesReferences":[{{"id":"I_1","number":1,"repository":{{"id":"R","name":"n","owner":{{"id":"O","login":"l"}}}},"url":""}}],"headRefName":"room/a","headRefOid":"{oid_a}","isDraft":true,"mergeCommit":null,"mergedAt":null,"number":1,"state":"OPEN","title":"Open PR"}},
                {{"baseRefName":"main","closingIssuesReferences":[],"headRefName":"room/b","headRefOid":"{oid_a}","isDraft":false,"mergeCommit":{{"oid":"{oid_b}"}},"mergedAt":"2026-10-30T18:30:00Z","number":2,"state":"MERGED","title":"Merged PR"}},
                {{"\u0062aseRefName":"","closingIssuesReferences":[],"headRefName":"","headRefOid":"not-a-commit","isDraft":false,"mergeCommit":null,"mergedAt":null,"number":3,"state":"CLOSED","title":"Closed PR"}}
            ]"#
        );
        let pr_cases = [
            "[]".to_owned(),
            valid_prs.clone(),
            valid_prs.replace("\"state\":\"CLOSED\"", "\"state\":\"OPEN\""),
            valid_prs.replace("\"mergedAt\":null", "\"mergedAt\":\"2026-10-30T18:30:00Z\""),
            valid_prs.replace(
                &format!(r#""mergeCommit":{{"oid":"{oid_b}"}}"#),
                r#""mergeCommit":null"#,
            ),
            valid_prs.replace("2026-10-30T18:30:00Z", "1969-12-31T23:59:59Z"),
            valid_prs.replace("2026-10-30T18:30:00Z", "2025-02-29T00:00:00Z"),
            valid_prs.replace("\"title\":\"Open PR\"", "\"title\":\"\""),
            valid_prs.replace(
                "\"title\":\"Open PR\"",
                "\"title\":\"Open PR\",\"title\":\"dup\"",
            ),
            valid_prs.replace("\"login\":\"l\"", "\"login\":\"l\",\"extra\":true"),
            valid_prs.replace("\"isDraft\":true", "\"isDraft\":1"),
            format!("{valid_prs}[]"),
        ];
        for raw in &pr_cases {
            let bytes = raw.as_bytes();
            let old = parse_with_strict_json(bytes, "gh pr list", |v| list(v, "", stock_pr_row));
            let new = parse_stock_prs(bytes);
            assert_eq!(new, old, "PR mismatch on {raw}");
            assert_eq!(
                fast::parse_stock_prs(bytes).ok(),
                old.ok(),
                "fast PR path diverged on {raw}"
            );
        }

        let check_cases = [
            "[]",
            r#"[{"bucket":"pass","name":"a"},{"bucket":"fail","name":"b"},{"bucket":"pending","name":"c"},{"bucket":"skipping","name":"d"},{"\u0062ucket":"cancel","name":"e"}]"#,
            r#"[{"bucket":"PASS","name":"a"}]"#,
            r#"[{"bucket":"pass","name":""}]"#,
            r#"[{"bucket":"pass","name":"a","bucket":"pass"}]"#,
            r#"[{"bucket":"pass","name":"a","extra":1}]"#,
            r#"[{"bucket":"pass"}]"#,
            "{}",
        ];
        for raw in check_cases {
            let bytes = raw.as_bytes();
            let old = parse_with_strict_json(bytes, "gh pr checks 1", |v| list(v, "", check));
            let new = parse_checks(bytes, "gh pr checks 1");
            assert_eq!(new, old, "checks mismatch on {raw}");
            assert_eq!(
                fast::parse_checks(bytes).ok(),
                old.ok(),
                "fast checks path diverged on {raw}"
            );
        }

        let comment_cases = [
            "[]",
            r#"["", "hello\nworld", "escaped \u0021"]"#,
            r#"[1]"#,
            r#"[{"a":1,"a":2}]"#,
            "not json",
        ];
        for raw in comment_cases {
            let bytes = raw.as_bytes();
            let old = parse_with_strict_json(bytes, "gh pr view 1's comments", |v| {
                list(v, "", |v, at| string(v, at).map(str::to_owned))
            });
            let new = parse_comments(bytes, "gh pr view 1's comments");
            assert_eq!(new, old, "comments mismatch on {raw}");
        }
    }

    #[test]
    fn fast_readers_match_oracle_across_deterministic_mutations() {
        let oid_a = "a".repeat(40);
        let oid_b = "b".repeat(40);
        let issue_seed = br#"[{"blockedBy":{"nodes":[{"id":"I_1","number":2,"state":"OPEN","title":"t","url":"u"}],"totalCount":1},"body":"b\n\"q\"","id":"I_0","labels":[{"color":"c","description":"d","id":"L","name":"p1"}],"milestone":{"description":"d","dueOn":null,"number":1,"title":"m"},"number":1,"state":"OPEN","subIssues":{"nodes":[],"totalCount":0},"title":"T"}]"#;
        let pr_seed = format!(
            r#"[{{"baseRefName":"main","closingIssuesReferences":[{{"id":"I_1","number":1,"repository":{{"id":"R","name":"n","owner":{{"id":"O","login":"l"}}}},"url":"u"}}],"headRefName":"room/x","headRefOid":"{oid_a}","isDraft":false,"mergeCommit":{{"oid":"{oid_b}"}},"mergedAt":"2026-10-30T18:30:00Z","number":5,"state":"MERGED","title":"PR"}},{{"baseRefName":"","closingIssuesReferences":[],"headRefName":"","headRefOid":"bad","isDraft":true,"mergeCommit":null,"mergedAt":null,"number":6,"state":"CLOSED","title":"C"}}]"#
        )
        .into_bytes();
        let check_seed = br#"[{"bucket":"pass","name":"ci"},{"bucket":"pending","name":"lint"}]"#;

        let mut rng = 0x5eed_cafe_1234_5678u64;
        let mut next = || {
            rng ^= rng << 13;
            rng ^= rng >> 7;
            rng ^= rng << 17;
            rng
        };
        let alphabet: &[u8] = b"0123456789\"{},:[]\\u0062nulltruefalse-OPENCLOSEDMRG";

        let mutate = |seed: &[u8], next: &mut dyn FnMut() -> u64| -> Vec<u8> {
            let mut buf = seed.to_vec();
            let edits = (next() % 4) as usize + 1;
            for _ in 0..edits {
                if buf.is_empty() {
                    break;
                }
                let pos = (next() as usize) % buf.len();
                match next() % 4 {
                    0 => buf[pos] = alphabet[(next() as usize) % alphabet.len()],
                    1 => {
                        buf.remove(pos);
                    }
                    2 => buf.insert(pos, alphabet[(next() as usize) % alphabet.len()]),
                    _ => buf.truncate(pos),
                }
            }
            buf
        };

        for _ in 0..600 {
            let bytes = mutate(issue_seed, &mut next);
            let old = parse_with_strict_json(&bytes, "gh issue list", |v| list(v, "", issue_row));
            assert_eq!(parse_issues(&bytes), old);
            assert_eq!(fast::parse_issues(&bytes).ok(), old.ok());

            let bytes = mutate(&pr_seed, &mut next);
            let old = parse_with_strict_json(&bytes, "gh pr list", |v| list(v, "", stock_pr_row));
            assert_eq!(parse_stock_prs(&bytes), old);
            assert_eq!(fast::parse_stock_prs(&bytes).ok(), old.ok());

            let bytes = mutate(check_seed, &mut next);
            let old = parse_with_strict_json(&bytes, "gh pr checks 1", |v| list(v, "", check));
            assert_eq!(parse_checks(&bytes, "gh pr checks 1"), old);
            assert_eq!(fast::parse_checks(&bytes).ok(), old.ok());
        }
    }
}
