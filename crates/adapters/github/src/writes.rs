use std::collections::HashSet;
use std::fmt;
use std::path::Path;
use std::time::Instant;

use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::messaging::validate_text;
use openwiz_core::source::SourceError;
use serde::de::{self, Deserialize, Deserializer, IgnoredAny, MapAccess, SeqAccess, Visitor};

use crate::allowlist::{Invocation, Module};
use crate::process;

pub const ALLOWLIST: Module = Module {
    name: "writes",
    allows,
};

fn allows(argv: &[&str]) -> bool {
    FORMS.iter().any(|form| matches(form, argv))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Word {
    Is(&'static str),
    Num,
    Name,
    Head,
    Text,
    NumVar,
}

use Word::{Head, Is, Name, Num, NumVar, Text};

type Form = &'static [Word];

const ISSUE_COMMENT: Form = &[Is("issue"), Is("comment"), Num, Is("--body"), Text];
const PR_COMMENT: Form = &[Is("pr"), Is("comment"), Num, Is("--body"), Text];
const ADD_LABEL: Form = &[Is("issue"), Is("edit"), Num, Is("--add-label"), Name];
const REMOVE_LABEL: Form = &[Is("issue"), Is("edit"), Num, Is("--remove-label"), Name];
const CLOSE_ISSUE: Form = &[Is("issue"), Is("close"), Num];
const MERGE: Form = &[
    Is("pr"),
    Is("merge"),
    Num,
    Is("--merge"),
    Is("--match-head-commit"),
    Head,
    Is("--body"),
    Text,
];
const READ_ISSUE_COMMENTS: Form = &[Is("issue"), Is("view"), Num, Is("--json"), Is("comments")];
const READ_PR_COMMENTS: Form = &[Is("pr"), Is("view"), Num, Is("--json"), Is("comments")];
const READ_LABELS: Form = &[Is("issue"), Is("view"), Num, Is("--json"), Is("labels")];
const READ_URL: Form = &[Is("issue"), Is("view"), Num, Is("--json"), Is("url")];
const READ_STATE: Form = &[Is("issue"), Is("view"), Num, Is("--json"), Is("state")];
const MERGE_QUEUE_QUERY: &str = "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled}}}";
const READ_MERGE_QUEUE: Form = &[
    Is("api"),
    Is("graphql"),
    Is("-f"),
    Is(MERGE_QUEUE_QUERY),
    Is("-F"),
    Is("owner={owner}"),
    Is("-F"),
    Is("repo={repo}"),
    Is("-F"),
    NumVar,
];
const READ_MERGE: Form = &[
    Is("pr"),
    Is("view"),
    Num,
    Is("--json"),
    Is("state,mergeCommit,headRefOid"),
];

const FORMS: &[Form] = &[
    ISSUE_COMMENT,
    PR_COMMENT,
    ADD_LABEL,
    REMOVE_LABEL,
    CLOSE_ISSUE,
    MERGE,
    READ_ISSUE_COMMENTS,
    READ_PR_COMMENTS,
    READ_LABELS,
    READ_URL,
    READ_STATE,
    READ_MERGE_QUEUE,
    READ_MERGE,
];

fn matches(form: Form, argv: &[&str]) -> bool {
    form.len() == argv.len()
        && form.iter().zip(argv).all(|(word, arg)| match word {
            Is(fixed) => fixed == arg,
            Num => number(arg).is_some(),
            Name => Label::parse(arg).is_some(),
            Head => Commit::parse(arg).is_some(),
            Text => Body::parse(arg).is_some(),
            NumVar => arg.strip_prefix(NUMBER_VAR).and_then(number).is_some(),
        })
}

fn number(arg: &str) -> Option<Number> {
    let digits =
        !arg.is_empty() && !arg.starts_with('0') && arg.bytes().all(|b| b.is_ascii_digit());
    digits.then(|| arg.parse().ok()).flatten()
}

const NUMBER_VAR: &str = "number=";

#[derive(Clone, Copy)]
struct Values<'a> {
    number: Number,
    name: Option<&'a Label>,
    head: Option<&'a Commit>,
    text: Option<&'a Body>,
}

fn fill(form: Form, values: Values<'_>) -> Vec<String> {
    form.iter()
        .map(|word| match word {
            Is(fixed) => (*fixed).to_owned(),
            Num => values.number.to_string(),
            Name => values
                .name
                .map(Label::as_str)
                .unwrap_or_default()
                .to_owned(),
            Head => values
                .head
                .map(Commit::as_str)
                .unwrap_or_default()
                .to_owned(),
            Text => values.text.map(Body::as_str).unwrap_or_default().to_owned(),
            NumVar => format!("{NUMBER_VAR}{}", values.number),
        })
        .collect()
}

pub const LABEL_MAX_LEN: usize = 50;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Label(String);

impl Label {
    pub fn parse(name: &str) -> Option<Self> {
        let valid = !name.is_empty()
            && name.len() <= LABEL_MAX_LEN
            && !name.starts_with('-')
            && name
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
        valid.then(|| Self(name.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Body(String);

impl Body {
    pub fn parse(text: &str) -> Option<Self> {
        validate_text(text).ok().map(|()| Self(text.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Write {
    IssueComment {
        issue: Number,
        body: Body,
    },
    PrComment {
        pr: Number,
        body: Body,
    },
    AddLabel {
        issue: Number,
        label: Label,
    },
    RemoveLabel {
        issue: Number,
        label: Label,
    },
    CloseIssue {
        issue: Number,
    },
    Merge {
        pr: Number,
        head: Commit,
        body: Body,
    },
}

impl Write {
    fn forms(&self) -> (Option<Form>, Form, Form) {
        match self {
            Write::IssueComment { .. } => (None, ISSUE_COMMENT, READ_ISSUE_COMMENTS),
            Write::PrComment { .. } => (None, PR_COMMENT, READ_PR_COMMENTS),
            Write::AddLabel { .. } => (None, ADD_LABEL, READ_LABELS),
            Write::RemoveLabel { .. } => (None, REMOVE_LABEL, READ_LABELS),
            Write::CloseIssue { .. } => (Some(READ_URL), CLOSE_ISSUE, READ_STATE),
            Write::Merge { .. } => (Some(READ_MERGE_QUEUE), MERGE, READ_MERGE),
        }
    }

    fn values(&self) -> Values<'_> {
        let only = |number: Number| Values {
            number,
            name: None,
            head: None,
            text: None,
        };
        match self {
            Write::IssueComment { issue: n, body } | Write::PrComment { pr: n, body } => Values {
                text: Some(body),
                ..only(*n)
            },
            Write::AddLabel { issue, label } | Write::RemoveLabel { issue, label } => Values {
                name: Some(label),
                ..only(*issue)
            },
            Write::CloseIssue { issue } => only(*issue),
            Write::Merge { pr, head, body } => Values {
                head: Some(head),
                text: Some(body),
                ..only(*pr)
            },
        }
    }

    pub fn argv(&self) -> Vec<String> {
        fill(self.forms().1, self.values())
    }

    pub fn calls(&self) -> Vec<Vec<String>> {
        let (before, write, read_back) = self.forms();
        before
            .into_iter()
            .chain([write, read_back])
            .map(|form| fill(form, self.values()))
            .collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Confirmed {
    Commented { url: String },
    Labelled,
    Unlabelled,
    Closed,
    Merged { merge_commit: Commit },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WriteError {
    NotAllowed,
    CheckFailed(SourceError),
    NotAnIssue,
    MergeQueue,
    Failed(SourceError),
    ReadBackFailed(SourceError),
    NotShown(String),
}

impl fmt::Display for WriteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotAllowed => f.write_str("not run: a call is not on the allowlist"),
            Self::CheckFailed(e) => write!(f, "not written: the check before it {e}"),
            Self::NotAnIssue => f.write_str("not written: the number is not that issue's"),
            Self::MergeQueue => f.write_str("not written: the base has a merge queue"),
            Self::Failed(e) => write!(f, "the write {e}; what it did is unknown"),
            Self::ReadBackFailed(e) => write!(f, "not confirmed: the read back {e}"),
            Self::NotShown(why) => write!(f, "not confirmed: {why}"),
        }
    }
}

pub fn perform(program: &Path, write: &Write, deadline: Instant) -> Result<Confirmed, WriteError> {
    perform_with(&process::Executor::program(program), write, deadline)
}

pub fn perform_with(
    executor: &process::Executor,
    write: &Write,
    deadline: Instant,
) -> Result<Confirmed, WriteError> {
    let mut calls = Vec::new();
    for argv in write.calls() {
        let words: Vec<&str> = argv.iter().map(String::as_str).collect();
        calls.push(Invocation::new(&words).ok_or(WriteError::NotAllowed)?);
    }
    let call = |invocation: &Invocation| executor.run(invocation, deadline);
    let (check, rest) = match (write.forms().0, &calls[..]) {
        (Some(_), [check, rest @ ..]) => (Some(check), rest),
        _ => (None, &calls[..]),
    };
    let [write_call, read_call] = rest else {
        return Err(WriteError::NotAllowed);
    };
    if let Some(check) = check {
        let answer = call(check).map_err(WriteError::CheckFailed)?;
        allowed_after(write, &answer)?;
    }
    let printed = call(write_call).map_err(WriteError::Failed)?;
    let read_back = call(read_call).map_err(WriteError::ReadBackFailed)?;
    shows(write, &printed, &read_back)
}

fn allowed_after(write: &Write, answer: &[u8]) -> Result<(), WriteError> {
    match write {
        // External: `gh issue close` also closes a pull request without merging it, https://github.com/cli/cli/blob/trunk/pkg/cmd/issue/close/close.go
        Write::CloseIssue { issue } => {
            let url = read_url(answer).map_err(WriteError::CheckFailed)?;
            if is_the_issue(&url, *issue) {
                Ok(())
            } else {
                Err(WriteError::NotAnIssue)
            }
        }
        // External: on a base that requires a merge queue, `gh pr merge --merge` does not merge: it turns on auto-merge while required checks are pending and adds the pull request to the merge queue once they pass, https://github.com/cli/cli/blob/de06af2c2ea536d5722fda35dc2001565f9b9f64/pkg/cmd/pr/merge/merge.go#L81-L90
        Write::Merge { .. } => match read_merge_queue(answer).map_err(WriteError::CheckFailed)? {
            false => Ok(()),
            true => Err(WriteError::MergeQueue),
        },
        _ => Err(WriteError::NotAllowed),
    }
}

fn shows(write: &Write, printed: &[u8], read_back: &[u8]) -> Result<Confirmed, WriteError> {
    let not_shown = |why: &str| Err(WriteError::NotShown(why.to_owned()));
    match write {
        Write::IssueComment { body, .. } | Write::PrComment { body, .. } => {
            let comments = read_comments(read_back).map_err(WriteError::ReadBackFailed)?;
            let Some(url) = comment_url(printed) else {
                return not_shown("gh did not print one comment URL");
            };
            let mut same = comments.iter().filter(|(u, _)| *u == url);
            match (same.next(), same.next()) {
                (None, _) => not_shown("no comment has the URL gh printed"),
                (Some(_), Some(_)) => not_shown("more than one comment has the URL gh printed"),
                (Some((_, text)), None) if text != body.as_str() => {
                    not_shown("the comment's text is not the text sent")
                }
                (Some(_), None) => Ok(Confirmed::Commented { url }),
            }
        }
        Write::AddLabel { label, .. } => {
            let names = read_labels(read_back).map_err(WriteError::ReadBackFailed)?;
            if names.iter().any(|name| name == label.as_str()) {
                Ok(Confirmed::Labelled)
            } else {
                not_shown("the label is not on the issue")
            }
        }
        Write::RemoveLabel { label, .. } => {
            let names = read_labels(read_back).map_err(WriteError::ReadBackFailed)?;
            if names
                .iter()
                .any(|name| name.eq_ignore_ascii_case(label.as_str()))
            {
                not_shown("the label is still on the issue")
            } else if names.len() >= MAX_LABELS_READ {
                not_shown("the read back holds as many labels as gh reads, so it may be cut off")
            } else {
                Ok(Confirmed::Unlabelled)
            }
        }
        Write::CloseIssue { .. } => match read_issue_state(read_back) {
            Ok(IssueState::Closed) => Ok(Confirmed::Closed),
            Ok(IssueState::Open) => not_shown("the issue is still open"),
            Err(e) => Err(WriteError::ReadBackFailed(e)),
        },
        Write::Merge { head, .. } => {
            let pr = read_merge(read_back).map_err(WriteError::ReadBackFailed)?;
            match pr {
                PrMerge {
                    state: PrState::Merged,
                    merge_commit: Some(merge_commit),
                    head: merged,
                } if merged == *head => Ok(Confirmed::Merged { merge_commit }),
                PrMerge {
                    state: PrState::Merged,
                    merge_commit: Some(_),
                    ..
                } => not_shown("the pull request was merged at another head"),
                PrMerge {
                    state: PrState::Merged,
                    merge_commit: None,
                    ..
                } => not_shown("the pull request shows no merge commit"),
                PrMerge {
                    state: PrState::Open | PrState::Closed,
                    ..
                } => not_shown("the pull request is not merged"),
            }
        }
    }
}

const MAX_LABELS_READ: usize = 100;

fn comment_url(printed: &[u8]) -> Option<String> {
    let line = std::str::from_utf8(printed).ok()?.strip_suffix('\n')?;
    let id = line.rsplit_once("#issuecomment-")?.1;
    let ok = line.starts_with("https://")
        && line.bytes().all(|b| b.is_ascii_graphic())
        && !id.is_empty()
        && id.bytes().all(|b| b.is_ascii_digit());
    ok.then(|| line.to_owned())
}

fn is_the_issue(url: &str, issue: Number) -> bool {
    url.starts_with("https://")
        && url.bytes().all(|b| b.is_ascii_graphic())
        && url
            .strip_suffix(&issue.to_string())
            .is_some_and(|rest| rest.ends_with("/issues/"))
}

enum Json {
    Null,
    Bool(bool),
    Scalar,
    String(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

struct Strict(Json);

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

    fn visit_i64<E: de::Error>(self, _: i64) -> Result<Json, E> {
        Ok(Json::Scalar)
    }

    fn visit_u64<E: de::Error>(self, _: u64) -> Result<Json, E> {
        Ok(Json::Scalar)
    }

    fn visit_f64<E: de::Error>(self, _: f64) -> Result<Json, E> {
        Ok(Json::Scalar)
    }

    fn visit_str<E: de::Error>(self, s: &str) -> Result<Json, E> {
        Ok(Json::String(s.to_owned()))
    }

    fn visit_string<E: de::Error>(self, s: String) -> Result<Json, E> {
        Ok(Json::String(s))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Json, A::Error> {
        let mut items = Vec::new();
        while let Some(Strict(item)) = seq.next_element()? {
            items.push(item);
        }
        Ok(Json::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Json, A::Error> {
        let mut entries: Vec<(String, Json)> = Vec::new();
        let mut seen: Option<HashSet<String>> = None;
        while let Some(key) = map.next_key::<String>()? {
            let duplicate = match &mut seen {
                Some(set) => set.contains(&key),
                None if entries.len() >= 16 => {
                    let mut set = HashSet::with_capacity(entries.len() * 2);
                    for (existing, _) in &entries {
                        set.insert(existing.clone());
                    }
                    let dup = set.contains(&key);
                    seen = Some(set);
                    dup
                }
                None => entries.iter().any(|(k, _)| *k == key),
            };
            if duplicate {
                let _: IgnoredAny = map.next_value()?;
                return Err(de::Error::custom("a key given twice"));
            }
            let Strict(value) = map.next_value()?;
            if let Some(set) = &mut seen {
                set.insert(key.clone());
            }
            entries.push((key, value));
        }
        Ok(Json::Object(entries))
    }
}

impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(JsonVisitor).map(Strict)
    }
}

fn malformed(what: &str) -> SourceError {
    SourceError::Malformed {
        detail: format!("{what} (withheld)"),
    }
}

fn document(stdout: &[u8]) -> Result<Json, SourceError> {
    serde_json::from_slice::<Strict>(stdout)
        .map(|Strict(json)| json)
        .map_err(|_| malformed("not one JSON document with no key given twice"))
}

fn object<'a, const N: usize>(
    json: &'a Json,
    keys: [&str; N],
    what: &str,
) -> Result<[&'a Json; N], SourceError> {
    let shape = || malformed(&format!("{what} is not an object with exactly its keys"));
    let Json::Object(entries) = json else {
        return Err(shape());
    };
    if entries.len() != N {
        return Err(shape());
    }
    let mut values = [&Json::Null; N];
    for (slot, key) in values.iter_mut().zip(keys) {
        *slot = entries
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v)
            .ok_or_else(shape)?;
    }
    Ok(values)
}

fn string<'a>(json: &'a Json, what: &str) -> Result<&'a str, SourceError> {
    match json {
        Json::String(s) => Ok(s),
        _ => Err(malformed(&format!("{what} is not text"))),
    }
}

fn array<'a>(json: &'a Json, what: &str) -> Result<&'a [Json], SourceError> {
    match json {
        Json::Array(items) => Ok(items),
        _ => Err(malformed(&format!("{what} is not a list"))),
    }
}

fn commit(json: &Json, what: &str) -> Result<Commit, SourceError> {
    Commit::parse(string(json, what)?)
        .ok_or_else(|| malformed(&format!("{what} is not a full commit")))
}

const COMMENT_KEYS: [&str; 11] = [
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
];

fn read_comments(stdout: &[u8]) -> Result<Vec<(String, String)>, SourceError> {
    let json = document(stdout)?;
    let [comments] = object(&json, ["comments"], "the answer")?;
    array(comments, "comments")?
        .iter()
        .map(|comment| {
            let values = object(comment, COMMENT_KEYS, "a comment")?;
            let (body, url) = (values[3], values[9]);
            Ok((
                string(url, "a comment's url")?.to_owned(),
                string(body, "a comment's body")?.to_owned(),
            ))
        })
        .collect()
}

fn read_labels(stdout: &[u8]) -> Result<Vec<String>, SourceError> {
    let json = document(stdout)?;
    let [labels] = object(&json, ["labels"], "the answer")?;
    array(labels, "labels")?
        .iter()
        .map(|label| {
            let [_, name, _, _] = object(label, ["id", "name", "description", "color"], "a label")?;
            string(name, "a label's name").map(str::to_owned)
        })
        .collect()
}

fn read_merge_queue(stdout: &[u8]) -> Result<bool, SourceError> {
    let json = document(stdout)?;
    let [data] = object(&json, ["data"], "the answer")?;
    let [repository] = object(data, ["repository"], "data")?;
    let [pr] = object(repository, ["pullRequest"], "repository")?;
    let [enabled] = object(pr, ["isMergeQueueEnabled"], "pullRequest")?;
    match enabled {
        Json::Bool(b) => Ok(*b),
        _ => Err(malformed("isMergeQueueEnabled is not true or false")),
    }
}

fn read_url(stdout: &[u8]) -> Result<String, SourceError> {
    let json = document(stdout)?;
    let [url] = object(&json, ["url"], "the answer")?;
    string(url, "url").map(str::to_owned)
}

enum IssueState {
    Open,
    Closed,
}

fn read_issue_state(stdout: &[u8]) -> Result<IssueState, SourceError> {
    let json = document(stdout)?;
    let [state] = object(&json, ["state"], "the answer")?;
    match string(state, "state")? {
        "OPEN" => Ok(IssueState::Open),
        "CLOSED" => Ok(IssueState::Closed),
        _ => Err(malformed("state is not an issue's")),
    }
}

enum PrState {
    Open,
    Closed,
    Merged,
}

struct PrMerge {
    state: PrState,
    merge_commit: Option<Commit>,
    head: Commit,
}

fn read_merge(stdout: &[u8]) -> Result<PrMerge, SourceError> {
    let json = document(stdout)?;
    let [state, merge_commit, head] =
        object(&json, ["state", "mergeCommit", "headRefOid"], "the answer")?;
    let state = match string(state, "state")? {
        "OPEN" => PrState::Open,
        "CLOSED" => PrState::Closed,
        "MERGED" => PrState::Merged,
        _ => return Err(malformed("state is not a pull request's")),
    };
    let merge_commit = match merge_commit {
        Json::Null => None,
        other => {
            let [oid] = object(other, ["oid"], "mergeCommit")?;
            Some(commit(oid, "mergeCommit's oid")?)
        }
    };
    Ok(PrMerge {
        state,
        merge_commit,
        head: commit(head, "headRefOid")?,
    })
}

#[cfg(test)]
mod before_write_tests {
    use super::*;

    fn number(n: u64) -> Number {
        Number::new(n).unwrap()
    }

    fn url(url: &str) -> String {
        format!(r#"{{"url": "{url}"}}"#)
    }

    fn perform_answering(
        write: &Write,
        check_write_and_read_back: [&str; 3],
    ) -> (Result<Confirmed, WriteError>, Vec<Vec<String>>) {
        let calls = std::sync::Arc::new(std::sync::Mutex::new(Vec::<Vec<String>>::new()));
        let seen = calls.clone();
        let answers = check_write_and_read_back.map(|answer| answer.as_bytes().to_vec());
        let executor = process::Executor::supplied(std::sync::Arc::new(
            move |call: &Invocation, _: Instant| {
                let mut seen = seen.lock().unwrap();
                seen.push(call.argv().to_vec());
                Ok(answers[seen.len() - 1].clone())
            },
        ));
        let result = perform_with(&executor, write, Instant::now());
        let calls = calls.lock().unwrap().clone();
        (result, calls)
    }

    #[test]
    fn a_close_runs_only_on_that_issues_own_url() {
        let close = Write::CloseIssue { issue: number(7) };
        let closed = r#"{"state": "CLOSED"}"#;
        let issue = url("https://github.invalid/synthetic/repo/issues/7");
        let (result, calls) = perform_answering(&close, [&issue, "", closed]);
        assert_eq!(result, Ok(Confirmed::Closed));
        assert_eq!(calls, close.calls());
        for other in [
            "https://github.invalid/synthetic/repo/pull/7",
            "https://github.invalid/synthetic/repo/issues/17",
            "https://github.invalid/synthetic/repo/issues/7/",
            "http://github.invalid/synthetic/repo/issues/7",
        ] {
            let (result, calls) = perform_answering(&close, [&url(other), "", closed]);
            assert_eq!(result, Err(WriteError::NotAnIssue), "{other}");
            assert_eq!(calls, close.calls()[..1], "{other}: only the check ran");
        }
    }

    #[test]
    fn a_merge_runs_only_on_a_base_without_a_merge_queue() {
        let merge = Write::Merge {
            pr: number(8),
            head: Commit::parse(&"a".repeat(40)).unwrap(),
            body: Body::parse("synthetic merge").unwrap(),
        };
        let queue = |enabled: &str| {
            format!(
                r#"{{"data": {{"repository": {{"pullRequest": {{"isMergeQueueEnabled": {enabled}}}}}}}}}"#
            )
        };
        let merged = format!(
            r#"{{"state": "MERGED", "mergeCommit": {{"oid": "{}"}}, "headRefOid": "{}"}}"#,
            "b".repeat(40),
            "a".repeat(40)
        );
        let (result, calls) = perform_answering(&merge, [&queue("false"), "", &merged]);
        assert_eq!(
            result,
            Ok(Confirmed::Merged {
                merge_commit: Commit::parse(&"b".repeat(40)).unwrap()
            })
        );
        assert_eq!(calls, merge.calls());
        let (result, calls) = perform_answering(&merge, [&queue("true"), "", &merged]);
        assert_eq!(result, Err(WriteError::MergeQueue));
        assert_eq!(calls, merge.calls()[..1], "only the check ran");
        let (result, calls) = perform_answering(&merge, [&queue("null"), "", &merged]);
        assert!(matches!(result, Err(WriteError::CheckFailed(_))));
        assert_eq!(calls, merge.calls()[..1], "only the check ran");
    }

    #[test]
    fn wide_objects_reject_duplicates_across_hash_promotion_boundary() {
        for width in [15, 16, 17, 64] {
            let mut obj = String::from("{");
            for i in 0..width {
                if i > 0 {
                    obj.push(',');
                }
                obj.push_str(&format!("\"k{i}\":{i}"));
            }
            assert!(document(format!("{obj}}}").as_bytes()).is_ok());
            assert!(document(format!("{obj},\"k0\":99}}").as_bytes()).is_err());
            assert!(document(format!("{obj},\"k{}\":99}}", width - 1).as_bytes()).is_err());
        }
    }
}
