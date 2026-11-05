//! The GitHub writes of running fleets (spec 2's B3, ClosedWiz#119): five
//! narrow writes through `gh`, each read back, and nothing else (spec
//! #116; the 0.0.6 grill, Q6).
//!
//! | Write | Its call | Its read back |
//! | --- | --- | --- |
//! | comment on an issue | `issue comment <n> --body <text>` | `issue view <n> --json comments` |
//! | comment on a pull request | `pr comment <n> --body <text>` | `pr view <n> --json comments` |
//! | add a label | `issue edit <n> --add-label <label>` | `issue view <n> --json labels` |
//! | remove a label | `issue edit <n> --remove-label <label>` | `issue view <n> --json labels` |
//! | close an issue | `issue close <n>`, after `issue view <n> --json url` | `issue view <n> --json state` |
//! | merge a pull request | `pr merge <n> --merge --match-head-commit <head> --body <text>`, after the merge-queue read below | `pr view <n> --json state,mergeCommit,headRefOid` |
//!
//! [`FORMS`] is that table, and the one place each form is spelt: the
//! module's part of the allowlist allows exactly an argument list one form
//! matches, with every value checked, and each [`Write`] fills its forms.
//! Never a branch deleted, a merge forced, queued or squashed, a comment
//! edited or deleted, another repository named, or any other `gh` command:
//! no form has one.
//!
//! **Every value is checked by its type** before anything runs: a number is
//! a [`Number`], written in full; a head a [`Commit`] (40 lowercase hex
//! digits); a [`Label`] only lowercase ASCII letters, digits and `-`, not
//! first (so never a flag, and never two labels: `gh` splits
//! `--add-label` at commas); and a [`Body`] `send`'s text rules
//! ([`validate_text`]). A text is passed byte for byte as one argument
//! after `--body`, which `gh` (pflag) takes as the value even when it starts
//! with `-` (gh 2.100.0's source, read for #119; not observed live).
//!
//! **A close is made only on an issue.** `gh issue close <n>` also closes a
//! pull request without merging it (gh 2.100.0, `close.go`), so a close
//! first reads the number's `url`, and closes only when it is that issue's
//! own (`https://…/issues/<n>`): anything else is [`WriteError::NotAnIssue`],
//! and nothing is written. A comment or a label on a pull request's number
//! is the same kind of write, so those take any number.
//!
//! **A merge is made only when the base has no merge queue** (R1 of the
//! review at `9aae308`). On a base with one, `gh pr merge --merge` turns on
//! auto-merge instead (gh 2.100.0, `merge.go`), a later merge no check
//! would see. `gh pr view --json` has no such field, so a merge first makes
//! the one GraphQL read here, a query with `gh`'s own `{owner}` and
//! `{repo}` placeholders:
//! `api graphql -f query=<the query> -F owner={owner} -F repo={repo} -F number=<n>`,
//! answered `{"data": {"repository": {"pullRequest": {"isMergeQueueEnabled": <bool>}}}}`.
//! Only an exact `false` lets the merge run; `true` is
//! [`WriteError::MergeQueue`], and a failed read or any other answer is
//! [`WriteError::CheckFailed`]: nothing is written.
//!
//! **Each write is read back** ([`perform`]), and is confirmed only when the
//! read back, read strictly, shows it (whoever made it):
//! - a comment: `gh` prints the new comment's URL (gh 2.100.0's source, not
//!   observed live), and exactly one comment has that URL, with exactly the
//!   text sent;
//! - a label added: one label has exactly its name; removed: none has it,
//!   in any case, and fewer than 100 are read (`gh` reads at most 100, so a
//!   full list may be cut off);
//! - a close: the issue is `CLOSED`;
//! - a merge: the pull request is `MERGED`, at the head asked for, with a
//!   merge commit (`docs/agents/fleet.md`, "How a merge is done").
//!
//! A write that fails or is stopped is never read back: what it did is
//! unknown, and the next tick's reads tell. Nothing is retried.
//!
//! **The readers are strict**, on B1's pattern (PR #88): an object only,
//! with exactly the keys `gh` 2.100.0 prints (A1, `shapes.md`), each once,
//! the kept ones each of its own type and every state from its fixed list.
//! Only what a check needs is kept; no error shows anything `gh` printed or
//! anything sent.

use std::fmt;
use std::path::Path;
use std::time::Instant;

use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::messaging::validate_text;
use openwiz_core::source::SourceError;
use serde::de::{self, Deserialize, Deserializer, IgnoredAny, MapAccess, SeqAccess, Visitor};

use crate::allowlist::{Invocation, Module};
use crate::process;

/// This module's part of the allowlist.
pub const ALLOWLIST: Module = Module {
    name: "writes",
    allows,
};

/// Whether `argv` is exactly one of [`FORMS`], every value checked.
fn allows(argv: &[&str]) -> bool {
    FORMS.iter().any(|form| matches(form, argv))
}

/// One word of a form: itself, or the place of one checked value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Word {
    /// Exactly this word.
    Is(&'static str),
    /// An issue's or pull request's number, in full: a [`Number`].
    Num,
    /// A [`Label`].
    Name,
    /// A head: a [`Commit`].
    Head,
    /// A [`Body`].
    Text,
    /// A GraphQL variable: `number=` and a [`Number`], in full.
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
/// The one GraphQL read: whether pull request `$number`'s base has a merge
/// queue. A query; nothing else is ever sent to `api`.
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

/// Every form this module allows: the writes, the reads before a close and
/// a merge, and the read backs.
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

/// Whether `argv` is exactly `form`, each value checked.
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

/// A number written in full: ASCII digits, no leading zero, 1 to
/// `u64::MAX`.
fn number(arg: &str) -> Option<Number> {
    let digits =
        !arg.is_empty() && !arg.starts_with('0') && arg.bytes().all(|b| b.is_ascii_digit());
    digits.then(|| arg.parse().ok()).flatten()
}

/// The start of the [`NumVar`] word.
const NUMBER_VAR: &str = "number=";

/// The values one write fills its forms with.
#[derive(Clone, Copy)]
struct Values<'a> {
    number: Number,
    name: Option<&'a Label>,
    head: Option<&'a Commit>,
    text: Option<&'a Body>,
}

/// `form` filled with `values`. A place with no value is left empty, which
/// no form allows, so it can never run.
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

/// The longest label name accepted: GitHub's own limit.
pub const LABEL_MAX_LEN: usize = 50;

/// A label name that is safe to pass as one argument, and is one label:
/// 1 to [`LABEL_MAX_LEN`] lowercase ASCII letters, digits and `-`, not
/// starting with `-`. So it can't be read as a flag, `gh` can't split it
/// into two labels at a comma, and no other label differs from it only in
/// case.
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

/// A comment's or a merge commit's text, on `send`'s text rules
/// ([`validate_text`]): not empty or only whitespace, no NUL, at most
/// 16 KiB of UTF-8. Anything else, a leading `-` or a line break, is passed
/// as it is.
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

/// One write, its values checked by their types.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Write {
    /// A comment on an issue.
    IssueComment { issue: Number, body: Body },
    /// A comment on a pull request.
    PrComment { pr: Number, body: Body },
    /// A label added to an issue.
    AddLabel { issue: Number, label: Label },
    /// A label removed from an issue.
    RemoveLabel { issue: Number, label: Label },
    /// An issue closed; never a pull request.
    CloseIssue { issue: Number },
    /// A pull request merged with a merge commit, only at `head`, with
    /// `body` as the merge commit's text.
    Merge {
        pr: Number,
        head: Commit,
        body: Body,
    },
}

impl Write {
    /// The read before the write, its write, and its read back.
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

    /// The write's own call: its arguments after `gh`.
    pub fn argv(&self) -> Vec<String> {
        fill(self.forms().1, self.values())
    }

    /// Every call [`perform`] makes when all goes well, in order: a close's
    /// or a merge's read before it, the write, then its read back.
    pub fn calls(&self) -> Vec<Vec<String>> {
        let (before, write, read_back) = self.forms();
        before
            .into_iter()
            .chain([write, read_back])
            .map(|form| fill(form, self.values()))
            .collect()
    }
}

/// What a confirmed write did, as its read back shows it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Confirmed {
    /// The comment is there, at this URL (the one `gh` printed), with
    /// exactly the text sent.
    Commented { url: String },
    /// The label is on the issue.
    Labelled,
    /// The label is not on the issue.
    Unlabelled,
    /// The issue is closed.
    Closed,
    /// The pull request is merged, at the head asked for, by this merge
    /// commit.
    Merged { merge_commit: Commit },
}

/// Why a write is not confirmed. Never anything `gh` printed or anything
/// sent: the reasons are OpenWiz's own words.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WriteError {
    /// Nothing ran: a call is on no module's allowlist. Unreachable for a
    /// [`Write`], whose values its types check; refused all the same.
    NotAllowed,
    /// The read before a close or a merge failed, or isn't the exact
    /// shape: nothing was written.
    CheckFailed(SourceError),
    /// The number is not that issue's (a pull request's, say), so nothing
    /// was closed.
    NotAnIssue,
    /// The pull request's base has a merge queue, where a merge would turn
    /// on auto-merge: nothing was written.
    MergeQueue,
    /// The write failed, or was stopped: what it did on GitHub is unknown.
    /// It was not read back.
    Failed(SourceError),
    /// The write exited 0, but its read back failed, or isn't the exact
    /// shape: not confirmed.
    ReadBackFailed(SourceError),
    /// The write exited 0, and its read back doesn't show it: why.
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

/// Makes `write` through `program` (`gh`), then reads it back, each call
/// stopped at `deadline` at the latest. Every call is built first, so
/// nothing runs unless all of them are allowed.
pub fn perform(program: &Path, write: &Write, deadline: Instant) -> Result<Confirmed, WriteError> {
    perform_with(&process::Executor::program(program), write, deadline)
}

/// The same preconditions and read-back, through an explicitly supplied executor.
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

/// Whether the read before `write` lets it be made: a close only on that
/// issue, a merge only on a base with no merge queue.
fn allowed_after(write: &Write, answer: &[u8]) -> Result<(), WriteError> {
    match write {
        Write::CloseIssue { issue } => {
            let url = read_url(answer).map_err(WriteError::CheckFailed)?;
            if is_the_issue(&url, *issue) {
                Ok(())
            } else {
                Err(WriteError::NotAnIssue)
            }
        }
        Write::Merge { .. } => match read_merge_queue(answer).map_err(WriteError::CheckFailed)? {
            false => Ok(()),
            true => Err(WriteError::MergeQueue),
        },
        // No other write has a read before it.
        _ => Err(WriteError::NotAllowed),
    }
}

/// Whether the read back shows `write` done.
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

/// The most labels `gh issue view --json labels` reads (gh 2.100.0,
/// `labels(first: 100)`).
const MAX_LABELS_READ: usize = 100;

/// The comment URL `gh` printed: exactly one line, `https://`, printable
/// ASCII with no space, ending `#issuecomment-` and its id's digits.
fn comment_url(printed: &[u8]) -> Option<String> {
    let line = std::str::from_utf8(printed).ok()?.strip_suffix('\n')?;
    let id = line.rsplit_once("#issuecomment-")?.1;
    let ok = line.starts_with("https://")
        && line.bytes().all(|b| b.is_ascii_graphic())
        && !id.is_empty()
        && id.bytes().all(|b| b.is_ascii_digit());
    ok.then(|| line.to_owned())
}

/// Whether `url` is issue `issue`'s own: `https://`, printable ASCII with
/// no space, ending `/issues/<issue>`.
fn is_the_issue(url: &str, issue: Number) -> bool {
    url.starts_with("https://")
        && url.bytes().all(|b| b.is_ascii_graphic())
        && url
            .strip_suffix(&issue.to_string())
            .is_some_and(|rest| rest.ends_with("/issues/"))
}

// The strict readers. `gh`'s answer is read into a [`Json`] tree by one
// hand-written visitor that refuses a key given twice (`serde_json::Value`
// would keep only the last), then read on B1's rules.

/// One JSON value. Numbers are never read, so only their kind is kept.
enum Json {
    Null,
    Bool(bool),
    Scalar,
    String(String),
    Array(Vec<Json>),
    /// In document order; no key twice.
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
        while let Some(key) = map.next_key::<String>()? {
            if entries.iter().any(|(k, _)| *k == key) {
                let _: IgnoredAny = map.next_value()?;
                return Err(de::Error::custom("a key given twice"));
            }
            let Strict(value) = map.next_value()?;
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

/// A read that isn't the exact shape, in OpenWiz's words only.
fn malformed(what: &str) -> SourceError {
    SourceError::Malformed {
        detail: format!("{what} (withheld)"),
    }
}

/// The whole answer, as one JSON document.
fn document(stdout: &[u8]) -> Result<Json, SourceError> {
    serde_json::from_slice::<Strict>(stdout)
        .map(|Strict(json)| json)
        .map_err(|_| malformed("not one JSON document with no key given twice"))
}

/// The values of exactly `keys`, in that order, from an object that has
/// exactly those keys.
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

/// Every key of one comment, as `gh` 2.100.0 prints it (A1, `shapes.md`).
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

/// Each comment's URL and text: `{"comments": [...]}`.
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

/// Each label's name: `{"labels": [{"id", "name", "description", "color"}]}`.
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

/// Whether the base has a merge queue: `{"data": {"repository":
/// {"pullRequest": {"isMergeQueueEnabled": true | false}}}}`, each object
/// with exactly that key, and the value a JSON boolean.
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

/// The URL: `{"url": "…"}`.
fn read_url(stdout: &[u8]) -> Result<String, SourceError> {
    let json = document(stdout)?;
    let [url] = object(&json, ["url"], "the answer")?;
    string(url, "url").map(str::to_owned)
}

enum IssueState {
    Open,
    Closed,
}

/// An issue's state: `{"state": "OPEN" | "CLOSED"}`.
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

/// A pull request's merge: `{"state": "OPEN" | "CLOSED" | "MERGED",
/// "mergeCommit": null | {"oid": <commit>}, "headRefOid": <commit>}`.
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
