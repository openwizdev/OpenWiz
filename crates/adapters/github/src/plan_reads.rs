use super::{Relation, Request};
use crate::{allowlist::Invocation, process, tickets::Tickets};
use openwiz_core::{
    fleet::{
        model::Number,
        tickets::{GitHub, Link, PrAnswer, RepositoryAnswer},
    },
    source::SourceError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GapKind {
    UntestedVersion,
    CommandFailed,
    TimedOut,
    BudgetExhausted,
    Malformed,
    MissingField,
    WrongType,
    NotFound,
    Truncated,
    Unsupported,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Failure {
    pub kind: GapKind,
    pub detail: String,
}
pub type Answer<T> = Result<T, Failure>;
pub fn failure(kind: GapKind, detail: &str) -> Failure {
    Failure {
        kind,
        detail: detail.to_owned(),
    }
}
pub fn malformed() -> Failure {
    failure(GapKind::Malformed, "GitHub plan data is malformed")
}

#[derive(Clone, Debug)]
pub struct Listing<T> {
    pub had_items: bool,
    pub rows: Vec<T>,
    pub gaps: Vec<Failure>,
}
impl<T> Default for Listing<T> {
    fn default() -> Self {
        Self {
            had_items: false,
            rows: vec![],
            gaps: vec![],
        }
    }
}
impl<T: Clone> Listing<T> {
    pub fn complete(&self) -> Answer<Vec<T>> {
        self.gaps
            .first()
            .map_or_else(|| Ok(self.rows.clone()), |f| Err(f.clone()))
    }
}
#[derive(Clone, Debug)]
pub struct Milestone {
    pub number: Number,
    pub title: Answer<String>,
}

#[derive(Clone, Debug)]
pub struct Issue {
    pub problems: Vec<Failure>,
    pub number: Number,
    pub title: Answer<String>,
    pub url: Answer<String>,
    pub state: Answer<String>,
    pub milestone: Answer<Option<Milestone>>,
    pub parent: Answer<Option<Link>>,
    pub labels: Listing<String>,
    pub children: Listing<Link>,
    pub blockers: Listing<Link>,
    pub prs: Listing<Link>,
}
#[derive(Clone, Debug)]
pub struct Pr {
    pub answer: PrAnswer,
    pub url: String,
}
#[derive(Clone, Debug)]
pub struct Reader {
    program: PathBuf,
}
impl Reader {
    pub fn new(program: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
        }
    }
    pub fn tickets(&self) -> Tickets {
        Tickets::new(&self.program)
    }
    pub fn repository(&self, deadline: Instant) -> Answer<RepositoryAnswer> {
        let r = self
            .tickets()
            .repository(deadline)
            .map_err(source_failure)?;
        let name = r.name_with_owner.as_str();
        let parts: Vec<_> = name.split('/').collect();
        if parts.len() != 2
            || parts.iter().any(|s| {
                s.is_empty()
                    || s.starts_with('.')
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
            })
            || r.url.as_str() != format!("https://github.com/{name}")
        {
            return Err(malformed());
        }
        Ok(r)
    }
    fn read(
        &self,
        r: Request,
        cursor: Option<&str>,
        deadline: Instant,
    ) -> Answer<(Value, Vec<Failure>)> {
        if Instant::now() >= deadline {
            return Err(failure(
                GapKind::BudgetExhausted,
                "GitHub plan read budget exhausted",
            ));
        }
        let args = r.argv(cursor);
        let words: Vec<_> = args.iter().map(String::as_str).collect();
        let invocation = Invocation::new(&words).ok_or_else(malformed)?;
        let captured = process::run_plan_graphql(Path::new(&self.program), &invocation, deadline)
            .map_err(source_failure)?;
        parse_read_response(r, &captured.stdout, captured.failure.is_some())
    }
    pub fn connection(
        &self,
        r: Request,
        initial: Option<Value>,
        deadline: Instant,
    ) -> Listing<Value> {
        let mut list = Listing::default();
        let mut cursor: Option<String> = None;
        let mut seen = BTreeSet::new();
        let mut total = None;
        let mut first = initial;
        loop {
            let page = if let Some(value) = first.take() {
                Ok((value, vec![]))
            } else {
                self.read(r, cursor.as_deref(), deadline)
            };
            let (value, gaps) = match page {
                Ok(v) => v,
                Err(e) => {
                    list.gaps.push(e);
                    break;
                }
            };
            list.gaps.extend(gaps);
            let parsed = match value {
                Value::Object(mut o) => {
                    list.had_items |= o
                        .get("totalCount")
                        .and_then(Value::as_u64)
                        .is_some_and(|n| n > 0);
                    let keys_ok = o
                        .keys()
                        .all(|k| ["nodes", "totalCount", "pageInfo"].contains(&k.as_str()));
                    let nodes_valid = if keys_ok {
                        if let Some(Value::Array(nodes)) = o.get_mut("nodes") {
                            list.had_items |= !nodes.is_empty();
                            list.rows.append(nodes);
                            true
                        } else {
                            false
                        }
                    } else {
                        false
                    };
                    (|| {
                        if !["nodes", "totalCount", "pageInfo"]
                            .iter()
                            .all(|k| o.contains_key(*k))
                        {
                            return Err(failure(
                                GapKind::MissingField,
                                "GitHub plan field is missing",
                            ));
                        }
                        if o.len() != 3 || !nodes_valid {
                            return Err(malformed());
                        }
                        let count = o["totalCount"].as_u64().ok_or_else(malformed)?;
                        let info = object_ref(&o["pageInfo"], &["hasNextPage", "endCursor"])?;
                        let more = info["hasNextPage"].as_bool().ok_or_else(malformed)?;
                        let next = if info["endCursor"].is_null() {
                            None
                        } else {
                            Some(text(&info["endCursor"])?.to_owned())
                        };
                        Ok((count, more, next))
                    })()
                }
                _ => Err(malformed()),
            };
            let (count, more, next) = match parsed {
                Ok(v) => v,
                Err(e) => {
                    list.gaps.push(e);
                    break;
                }
            };
            if total.is_some_and(|t| t != count) {
                list.gaps.push(failure(
                    GapKind::Truncated,
                    "GitHub plan total changed between pages",
                ));
                break;
            }
            total = Some(count);
            if list.rows.len() as u64 > count {
                list.gaps.push(malformed());
                break;
            }
            if !more {
                if list.rows.len() as u64 != count {
                    list.gaps.push(failure(
                        GapKind::Truncated,
                        "GitHub plan page count does not match its total",
                    ));
                }
                break;
            }
            let Some(next) = next else {
                list.gaps.push(malformed());
                break;
            };
            if list.rows.len() as u64 >= count || !seen.insert(next.clone()) {
                list.gaps.push(malformed());
                break;
            }
            cursor = Some(next);
        }
        list
    }
    pub fn milestones(&self, deadline: Instant) -> Listing<Milestone> {
        convert(
            self.connection(Request::Milestones, None, deadline),
            milestone,
        )
    }
    pub fn issues(&self, deadline: Instant) -> Listing<Issue> {
        let raw = self.connection(Request::Issues, None, deadline);
        convert(raw, |v| self.issue_value(v, deadline))
    }
    pub fn issue(&self, n: Number, deadline: Instant) -> Answer<Issue> {
        let (v, gaps) = self.read(Request::Issue(n.get()), None, deadline)?;
        let mut issue = self.issue_value(v, deadline)?;
        issue.problems.extend(gaps);
        if issue.number != n {
            return Err(malformed());
        }
        Ok(issue)
    }
    fn issue_value(&self, v: Value, deadline: Instant) -> Answer<Issue> {
        let Value::Object(mut o) = v else {
            return Err(malformed());
        };
        const FIELDS: &[&str] = &[
            "number",
            "title",
            "url",
            "state",
            "milestone",
            "parent",
            "labels",
            "subIssues",
            "blockedBy",
            "closedByPullRequestsReferences",
        ];
        if o.keys().any(|k| !FIELDS.contains(&k.as_str())) {
            return Err(malformed());
        }
        let take = |o: &mut Map<String, Value>, field: &str| {
            o.remove(field)
                .ok_or_else(|| failure(GapKind::MissingField, "GitHub plan field is missing"))
        };
        let number = take(&mut o, "number").and_then(|v| positive(&v))?;
        let title = take(&mut o, "title").and_then(into_string);
        let url = take(&mut o, "url").and_then(into_string);
        let state = take(&mut o, "state").and_then(into_string).and_then(|s| {
            if s == "OPEN" || s == "CLOSED" {
                Ok(s)
            } else {
                Err(malformed())
            }
        });
        let milestone = take(&mut o, "milestone").and_then(|v| {
            if v.is_null() {
                Ok(None)
            } else {
                milestone(v).map(Some)
            }
        });
        let parent = take(&mut o, "parent").and_then(|v| {
            if v.is_null() {
                Ok(None)
            } else {
                link(v).map(Some)
            }
        });
        let mut connection = |field: &str, rel| match take(&mut o, field) {
            Ok(v) => self.connection(Request::Relation(number.get(), rel), Some(v), deadline),
            Err(f) => Listing {
                had_items: false,
                rows: vec![],
                gaps: vec![f],
            },
        };
        let labels = convert(connection("labels", Relation::Labels), |v| {
            let mut o = into_object(v, &["name"])?;
            into_string(o.remove("name").expect("checked"))
        });
        let children = convert(connection("subIssues", Relation::SubIssues), link);
        let blockers = convert(connection("blockedBy", Relation::BlockedBy), link);
        let prs = convert(
            connection("closedByPullRequestsReferences", Relation::ClosingPrs),
            link,
        );
        Ok(Issue {
            problems: vec![],
            number,
            title,
            url,
            state,
            milestone,
            parent,
            labels,
            children,
            blockers,
            prs,
        })
    }
    pub fn pr(&self, n: Number, deadline: Instant) -> Answer<Pr> {
        let (v, gaps) = self.read(Request::Pr(n.get()), None, deadline)?;
        if let Some(gap) = gaps.first() {
            return Err(gap.clone());
        }
        self.pr_value(n, v, deadline)
    }
    fn pr_value(&self, n: Number, v: Value, deadline: Instant) -> Answer<Pr> {
        let mut o = into_object(
            v,
            &[
                "number",
                "url",
                "baseRefName",
                "headRefName",
                "headRefOid",
                "isDraft",
                "mergeCommit",
                "mergedAt",
                "state",
                "closingIssuesReferences",
            ],
        )?;
        let url = into_string(o.remove("url").expect("checked"))?;
        let closing = o.remove("closingIssuesReferences").expect("checked");
        let links = self
            .connection(
                Request::Relation(n.get(), Relation::ClosingIssues),
                Some(closing),
                deadline,
            )
            .complete()?;
        o.insert("closingIssuesReferences".to_owned(), Value::Array(links));
        let answer = crate::tickets::pull_request_object(&o).map_err(source_failure)?;
        if answer.number != n {
            return Err(malformed());
        }
        Ok(Pr { answer, url })
    }
    pub fn comments(&self, n: Number, deadline: Instant) -> Answer<Vec<String>> {
        convert(
            self.connection(
                Request::Relation(n.get(), Relation::Comments),
                None,
                deadline,
            ),
            |v| {
                let mut o = into_object(v, &["body"])?;
                match o.remove("body") {
                    Some(Value::String(s)) => Ok(s),
                    _ => Err(malformed()),
                }
            },
        )
        .complete()
    }
}

fn parse_read_response(r: Request, stdout: &[u8], failed: bool) -> Answer<(Value, Vec<Failure>)> {
    let Value::Object(mut root) = strict(stdout)? else {
        return Err(malformed());
    };
    if !root.contains_key("data") || root.keys().any(|k| k != "data" && k != "errors") {
        return Err(malformed());
    }
    let has_errors = root.contains_key("errors");
    let gaps = if failed || has_errors {
        vec![failure(
            GapKind::CommandFailed,
            "GitHub reported an incomplete plan read",
        )]
    } else {
        vec![]
    };
    let mut data = root.remove("data").expect("checked");
    if failed || has_errors {
        mask_errors(&mut data, root.get("errors"));
    }
    let mut data = into_object(data, &["repository"])?;
    let repo = match data.remove("repository") {
        Some(Value::Object(o)) => o,
        _ => {
            return Err(failure(
                GapKind::NotFound,
                "GitHub repository was not returned",
            ));
        }
    };
    let (field, subject) = match r {
        Request::Milestones => ("milestones", None),
        Request::Issues => ("issues", None),
        Request::Issue(_) => ("issue", None),
        Request::Pr(_) => ("pullRequest", None),
        Request::Relation(_, rel) => (
            rel.field(),
            Some(
                if matches!(rel, Relation::ClosingIssues | Relation::Comments) {
                    "pullRequest"
                } else {
                    "issue"
                },
            ),
        ),
    };
    let parent = if let Some(subject) = subject {
        let mut o = into_object(Value::Object(repo), &[subject])?;
        match o.remove(subject) {
            Some(Value::Object(sub)) => sub,
            _ => return Err(malformed()),
        }
    } else {
        repo
    };
    let value = into_object(Value::Object(parent), &[field])?
        .remove(field)
        .expect("checked");
    if value.is_null() {
        return Err(failure(
            GapKind::NotFound,
            "GitHub plan item was not returned",
        ));
    }
    Ok((value, gaps))
}
fn convert<T>(raw: Listing<Value>, parse: impl Fn(Value) -> Answer<T>) -> Listing<T> {
    let mut out = Listing {
        had_items: raw.had_items,
        rows: vec![],
        gaps: raw.gaps,
    };
    for v in raw.rows {
        match parse(v) {
            Ok(v) => out.rows.push(v),
            Err(e) => out.gaps.push(e),
        }
    }
    out
}
pub fn source_failure(e: SourceError) -> Failure {
    let kind = match e {
        SourceError::TimedOut { .. } => GapKind::TimedOut,
        SourceError::NotFound { .. } => GapKind::NotFound,
        SourceError::Malformed { .. } | SourceError::InvalidId { .. } => GapKind::Malformed,
        _ => GapKind::CommandFailed,
    };
    failure(kind, "GitHub plan read failed (detail withheld)")
}
pub fn object(v: &Value, keys: &[&str]) -> Answer<Map<String, Value>> {
    object_ref(v, keys).cloned()
}
fn object_ref<'a>(v: &'a Value, keys: &[&str]) -> Answer<&'a Map<String, Value>> {
    let o = v.as_object().ok_or_else(malformed)?;
    if keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(failure(
            GapKind::MissingField,
            "GitHub plan field is missing",
        ));
    }
    if o.len() != keys.len() {
        return Err(malformed());
    }
    Ok(o)
}
fn into_object(v: Value, keys: &[&str]) -> Answer<Map<String, Value>> {
    let Value::Object(o) = v else {
        return Err(malformed());
    };
    if keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(failure(
            GapKind::MissingField,
            "GitHub plan field is missing",
        ));
    }
    if o.len() != keys.len() {
        return Err(malformed());
    }
    Ok(o)
}
pub fn positive(v: &Value) -> Answer<Number> {
    v.as_u64().and_then(Number::new).ok_or_else(malformed)
}
pub fn text(v: &Value) -> Answer<&str> {
    v.as_str().filter(|s| !s.is_empty()).ok_or_else(malformed)
}
fn into_string(v: Value) -> Answer<String> {
    match v {
        Value::String(s) if !s.is_empty() => Ok(s),
        _ => Err(malformed()),
    }
}
fn milestone(v: Value) -> Answer<Milestone> {
    let Value::Object(mut o) = v else {
        return Err(malformed());
    };
    if o.keys().any(|k| k != "number" && k != "title") {
        return Err(malformed());
    }
    Ok(Milestone {
        number: o.get("number").ok_or_else(malformed).and_then(positive)?,
        title: o
            .remove("title")
            .ok_or_else(|| failure(GapKind::MissingField, "GitHub milestone title is missing"))
            .and_then(into_string),
    })
}
fn link(v: Value) -> Answer<Link> {
    let mut o = into_object(v, &["number", "url"])?;
    Ok(Link {
        number: positive(&o["number"])?,
        url: into_string(o.remove("url").expect("checked"))?,
    })
}

struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = Strict;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("JSON with unique object keys")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut m = Map::new();
                while let Some(k) = a.next_key::<String>()? {
                    match m.entry(k) {
                        serde_json::map::Entry::Vacant(slot) => {
                            slot.insert(a.next_value::<Strict>()?.0);
                        }
                        serde_json::map::Entry::Occupied(_) => {
                            return Err(serde::de::Error::custom("duplicate key"));
                        }
                    }
                }
                Ok(Strict(Value::Object(m)))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut v = vec![];
                while let Some(x) = a.next_element::<Strict>()? {
                    v.push(x.0)
                }
                Ok(Strict(Value::Array(v)))
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(Value::String(v.to_owned())))
            }
            fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Strict, E> {
                Ok(Strict(Value::String(v)))
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(Value::Bool(v)))
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(Value::from(v)))
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Strict, E> {
                Ok(Strict(Value::from(v)))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Strict, E> {
                Ok(Strict(Value::from(v)))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_none<E: serde::de::Error>(self) -> Result<Strict, E> {
                self.visit_unit()
            }
        }
        d.deserialize_any(V)
    }
}
pub fn strict(bytes: &[u8]) -> Answer<Value> {
    serde_json::from_slice::<Strict>(bytes)
        .map(|v| v.0)
        .map_err(|_| malformed())
}

fn mask_errors(data: &mut Value, errors: Option<&Value>) {
    let targets = errors
        .and_then(Value::as_array)
        .filter(|v| !v.is_empty())
        .and_then(|errors| {
            errors
                .iter()
                .map(|error| {
                    let path = error.get("path")?.as_array()?;
                    error_target(data, path)
                })
                .collect::<Option<Vec<_>>>()
        });
    match targets {
        Some(targets) => {
            for path in targets {
                omit_field(data, &path);
            }
        }
        None => uncertain_absences(data),
    }
}

fn error_target(data: &Value, path: &[Value]) -> Option<Vec<Value>> {
    if path.is_empty()
        || !path.iter().all(|segment| match segment {
            Value::String(key) => !key.is_empty(),
            Value::Number(index) => index.is_u64(),
            _ => false,
        })
    {
        return None;
    }
    let mut at = data;
    for (i, segment) in path.iter().enumerate() {
        at = match segment {
            Value::String(key) if !key.is_empty() => at.as_object()?.get(key)?,
            Value::Number(n) => at.as_array()?.get(usize::try_from(n.as_u64()?).ok()?)?,
            _ => return None,
        };
        if at.is_null() || i + 1 == path.len() {
            return Some(path[..=i].to_vec());
        }
    }
    None
}

fn omit_field(data: &mut Value, path: &[Value]) {
    let Some((first, rest)) = path.split_first() else {
        return;
    };
    match first {
        Value::String(key) => {
            if let Some(object) = data.as_object_mut() {
                if rest.is_empty() {
                    object.remove(key);
                } else if let Some(child) = object.get_mut(key) {
                    omit_field(child, rest);
                }
            }
        }
        Value::Number(n) => {
            if let Some(index) = n.as_u64().and_then(|n| usize::try_from(n).ok())
                && let Some(child) = data.as_array_mut().and_then(|v| v.get_mut(index))
            {
                if rest.is_empty() {
                    *child = Value::Null;
                } else {
                    omit_field(child, rest);
                }
            }
        }
        _ => {}
    }
}

fn uncertain_absences(data: &mut Value) {
    match data {
        Value::Object(object) => {
            object.retain(|_, value| !value.is_null());
            if object.get("nodes").is_some_and(Value::is_array) {
                object.remove("pageInfo");
            }
            for value in object.values_mut() {
                uncertain_absences(value);
            }
        }
        Value::Array(values) => {
            for value in values {
                uncertain_absences(value);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod oracle_tests {
    use super::*;

    mod previous {
        use super::*;

        fn string(v: &Value) -> Answer<String> {
            text(v).map(str::to_owned)
        }

        fn milestone(v: Value) -> Answer<Milestone> {
            let o = v.as_object().ok_or_else(malformed)?;
            if o.keys().any(|k| k != "number" && k != "title") {
                return Err(malformed());
            }
            Ok(Milestone {
                number: o.get("number").ok_or_else(malformed).and_then(positive)?,
                title: o
                    .get("title")
                    .ok_or_else(|| {
                        failure(GapKind::MissingField, "GitHub milestone title is missing")
                    })
                    .and_then(string),
            })
        }

        fn link(v: Value) -> Answer<Link> {
            let o = object(&v, &["number", "url"])?;
            Ok(Link {
                number: positive(&o["number"])?,
                url: string(&o["url"])?,
            })
        }

        pub(super) fn parse_read_response(
            r: Request,
            stdout: &[u8],
            failed: bool,
        ) -> Answer<(Value, Vec<Failure>)> {
            let value = strict(stdout)?;
            let root = value.as_object().ok_or_else(malformed)?;
            if !root.contains_key("data") || root.keys().any(|k| k != "data" && k != "errors") {
                return Err(malformed());
            }
            let gaps = if failed || root.contains_key("errors") {
                vec![failure(
                    GapKind::CommandFailed,
                    "GitHub reported an incomplete plan read",
                )]
            } else {
                vec![]
            };
            let mut data = root["data"].clone();
            if failed || root.contains_key("errors") {
                mask_errors(&mut data, root.get("errors"));
            }
            let data = object(&data, &["repository"])?;
            let repo = data["repository"]
                .as_object()
                .ok_or_else(|| failure(GapKind::NotFound, "GitHub repository was not returned"))?;
            let (field, subject) = match r {
                Request::Milestones => ("milestones", None),
                Request::Issues => ("issues", None),
                Request::Issue(_) => ("issue", None),
                Request::Pr(_) => ("pullRequest", None),
                Request::Relation(_, rel) => (
                    rel.field(),
                    Some(
                        if matches!(rel, Relation::ClosingIssues | Relation::Comments) {
                            "pullRequest"
                        } else {
                            "issue"
                        },
                    ),
                ),
            };
            let parent = if let Some(subject) = subject {
                let o = object(&Value::Object(repo.clone()), &[subject])?;
                o[subject].as_object().cloned().ok_or_else(malformed)?
            } else {
                repo.clone()
            };
            let value = object(&Value::Object(parent), &[field])?[field].clone();
            if value.is_null() {
                return Err(failure(
                    GapKind::NotFound,
                    "GitHub plan item was not returned",
                ));
            }
            Ok((value, gaps))
        }

        pub(super) fn connection_initial(value: Value) -> Listing<Value> {
            let mut list = Listing::default();
            list.had_items |= value
                .get("totalCount")
                .and_then(Value::as_u64)
                .is_some_and(|n| n > 0);
            if let Some(o) = value.as_object()
                && o.keys()
                    .all(|k| ["nodes", "totalCount", "pageInfo"].contains(&k.as_str()))
                && let Some(nodes) = o.get("nodes").and_then(Value::as_array)
            {
                list.had_items |= !nodes.is_empty();
                list.rows.extend(nodes.iter().cloned());
            }
            let parsed = (|| {
                let o = object(&value, &["nodes", "totalCount", "pageInfo"])?;
                o["nodes"].as_array().ok_or_else(malformed)?;
                let count = o["totalCount"].as_u64().ok_or_else(malformed)?;
                let info = object(&o["pageInfo"], &["hasNextPage", "endCursor"])?;
                let more = info["hasNextPage"].as_bool().ok_or_else(malformed)?;
                let next = if info["endCursor"].is_null() {
                    None
                } else {
                    Some(text(&info["endCursor"])?.to_owned())
                };
                Ok((count, more, next))
            })();
            let (count, more, next) = match parsed {
                Ok(v) => v,
                Err(e) => {
                    list.gaps.push(e);
                    return list;
                }
            };
            if list.rows.len() as u64 > count {
                list.gaps.push(malformed());
                return list;
            }
            if !more {
                if list.rows.len() as u64 != count {
                    list.gaps.push(failure(
                        GapKind::Truncated,
                        "GitHub plan page count does not match its total",
                    ));
                }
                return list;
            }
            if next.is_none() || list.rows.len() as u64 >= count {
                list.gaps.push(malformed());
            }
            list
        }

        pub(super) fn issue_value(v: Value) -> Answer<Issue> {
            let o = v.as_object().ok_or_else(malformed)?;
            const FIELDS: &[&str] = &[
                "number",
                "title",
                "url",
                "state",
                "milestone",
                "parent",
                "labels",
                "subIssues",
                "blockedBy",
                "closedByPullRequestsReferences",
            ];
            if o.keys().any(|k| !FIELDS.contains(&k.as_str())) {
                return Err(malformed());
            }
            let get = |field: &str| {
                o.get(field)
                    .ok_or_else(|| failure(GapKind::MissingField, "GitHub plan field is missing"))
            };
            let number = positive(get("number")?)?;
            let conn = |field: &str| match get(field) {
                Ok(v) => connection_initial(v.clone()),
                Err(f) => Listing {
                    had_items: false,
                    rows: vec![],
                    gaps: vec![f],
                },
            };
            Ok(Issue {
                problems: vec![],
                number,
                title: get("title").and_then(string),
                url: get("url").and_then(string),
                state: get("state").and_then(string).and_then(|s| {
                    if s == "OPEN" || s == "CLOSED" {
                        Ok(s)
                    } else {
                        Err(malformed())
                    }
                }),
                milestone: get("milestone").and_then(|v| {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        milestone(v.clone()).map(Some)
                    }
                }),
                parent: get("parent").and_then(|v| {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        link(v.clone()).map(Some)
                    }
                }),
                labels: convert(conn("labels"), |v| {
                    let o = object(&v, &["name"])?;
                    string(&o["name"])
                }),
                children: convert(conn("subIssues"), link),
                blockers: convert(conn("blockedBy"), link),
                prs: convert(conn("closedByPullRequestsReferences"), link),
            })
        }

        pub(super) fn pr_value(n: Number, mut v: Value) -> Answer<Pr> {
            let o = object(
                &v,
                &[
                    "number",
                    "url",
                    "baseRefName",
                    "headRefName",
                    "headRefOid",
                    "isDraft",
                    "mergeCommit",
                    "mergedAt",
                    "state",
                    "closingIssuesReferences",
                ],
            )?;
            let url = string(&o["url"])?;
            let links = connection_initial(o["closingIssuesReferences"].clone()).complete()?;
            let o = v.as_object_mut().ok_or_else(malformed)?;
            o.remove("url");
            o.insert("closingIssuesReferences".to_owned(), Value::Array(links));
            let answer =
                crate::tickets::pull_request(&serde_json::to_vec(&v).map_err(|_| malformed())?)
                    .map_err(source_failure)?;
            if answer.number != n {
                return Err(malformed());
            }
            Ok(Pr { answer, url })
        }
    }

    #[test]
    fn move_based_plan_readers_match_previous_clone_oracle() {
        let reader = Reader::new("/synthetic/unused");
        let deadline = Instant::now() + std::time::Duration::from_secs(60);

        let issue_node = r#"{"number":7,"title":"Synthetic \"quoted\"","url":"https://github.invalid/o/r/issues/7","state":"OPEN","milestone":{"number":1,"title":"0.2.0"},"parent":{"number":1,"url":"https://github.invalid/o/r/issues/1"},"labels":{"totalCount":1,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"name":"p1"}]},"subIssues":{"totalCount":0,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]},"blockedBy":{"totalCount":0,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]},"closedByPullRequestsReferences":{"totalCount":1,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"number":8,"url":"https://github.invalid/o/r/pull/8"}]}}"#;
        let conn_good = format!(
            r#"{{"nodes":[{issue_node}],"totalCount":1,"pageInfo":{{"hasNextPage":false,"endCursor":null}}}}"#
        );
        let resp_good = format!(r#"{{"data":{{"repository":{{"issues":{conn_good}}}}}}}"#);
        let resp_err = format!(
            r#"{{"data":{{"repository":{{"issues":{conn_good}}}}},"errors":[{{"path":["repository","issues","nodes",0,"milestone"]}}]}}"#
        );
        for (raw, failed) in [
            (resp_good.as_str(), false),
            (resp_err.as_str(), true),
            (r#"{"data":{"repository":null}}"#, false),
            (r#"{"data":{"repository":{"issues":null}}}"#, false),
            (r#"{"data":{"repository":{"issues":{"a":1,"a":2}}}}"#, false),
            (r#"{"data":{},"extra":1}"#, false),
        ] {
            let old = previous::parse_read_response(Request::Issues, raw.as_bytes(), failed);
            let new = parse_read_response(Request::Issues, raw.as_bytes(), failed);
            assert_eq!(new, old, "parse_read_response mismatch on {raw}");
        }

        for conn_raw in [
            conn_good.as_str(),
            r#"{"nodes":[{"x":1}],"totalCount":1}"#,
            r#"{"nodes":[{"x":1}],"totalCount":2,"pageInfo":{"hasNextPage":false,"endCursor":null}}"#,
            r#"{"nodes":[{"x":1}],"totalCount":1,"pageInfo":{"hasNextPage":false,"endCursor":null},"extra":1}"#,
            r#"{"nodes":"bad","totalCount":0,"pageInfo":{"hasNextPage":false,"endCursor":null}}"#,
            r#"null"#,
        ] {
            let v = strict(conn_raw.as_bytes()).unwrap();
            let old = previous::connection_initial(v.clone());
            let new = reader.connection(Request::Issues, Some(v), deadline);
            assert_eq!(new.had_items, old.had_items, "{conn_raw}");
            assert_eq!(new.rows, old.rows, "{conn_raw}");
            assert_eq!(new.gaps, old.gaps, "{conn_raw}");
        }

        let issue_v = strict(issue_node.as_bytes()).unwrap();
        let old_i = previous::issue_value(issue_v.clone()).unwrap();
        let new_i = reader.issue_value(issue_v, deadline).unwrap();
        assert_eq!(new_i.number, old_i.number);
        assert_eq!(new_i.title, old_i.title);
        assert_eq!(new_i.url, old_i.url);
        assert_eq!(new_i.state, old_i.state);
        assert_eq!(new_i.labels.rows, old_i.labels.rows);
        assert_eq!(new_i.prs.rows, old_i.prs.rows);
        assert_eq!(new_i.parent, old_i.parent);

        let oid = "a".repeat(40);
        let pr_raw = format!(
            r#"{{"number":9,"url":"https://github.invalid/o/r/pull/9","baseRefName":"main","headRefName":"room/x","headRefOid":"{oid}","isDraft":false,"mergeCommit":{{"oid":"{oid}"}},"mergedAt":"2026-10-30T18:30:00Z","state":"MERGED","closingIssuesReferences":{{"totalCount":1,"pageInfo":{{"hasNextPage":false,"endCursor":null}},"nodes":[{{"id":"I_7","number":7,"url":"https://github.invalid/o/r/issues/7","repository":{{"nameWithOwner":"o/r"}}}}]}}}}"#
        );
        let pr_num = Number::new(9).unwrap();
        for raw in [
            pr_raw.clone(),
            pr_raw.replace("\"number\":9,", "\"number\":10,"),
            pr_raw.replace("\"state\":\"MERGED\"", "\"state\":\"OPEN\""),
            pr_raw.replace("\"url\":\"https://github.invalid/o/r/pull/9\",", ""),
        ] {
            let v = strict(raw.as_bytes()).unwrap();
            let old_pr = previous::pr_value(pr_num, v.clone());
            let new_pr = reader.pr_value(pr_num, v, deadline);
            assert_eq!(
                new_pr.as_ref().map(|p| (&p.answer, &p.url)),
                old_pr.as_ref().map(|p| (&p.answer, &p.url)),
                "pr_value mismatch on {raw}"
            );
        }
    }
}
