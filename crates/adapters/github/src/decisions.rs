//! GitHub reads for decision requests. No write forms.
use crate::{
    allowlist::{Invocation, Module},
    process,
};
use openwiz_core::source::SourceError;
use serde_json::Value;
use std::path::PathBuf;
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Instant,
};

#[path = "decisions_json.rs"]
mod strict;

pub const COMMENT_FIELDS: &str = "[.[] | {id,body,issue_url,created_at,updated_at}]";
pub const SUBJECT_FIELDS: &str = "{number,body,is_pull_request:has(\"pull_request\")}";
pub const GRILL_HEAD_FIELDS: &str = "{number,head_sha:.head.sha}";
const GRILL_QUERY: &str = "query($owner:String!,$name:String!,$number:Int!,$expression:String!){repository(owner:$owner,name:$name){pullRequest(number:$number){number headRefOid} object(expression:$expression){__typename ... on Blob{text isTruncated}}}}";

pub const ALLOWLIST: Module = Module {
    name: "decisions",
    allows,
};

fn positive(s: &str) -> bool {
    !s.starts_with('0')
        && s.bytes().all(|b| b.is_ascii_digit())
        && s.parse::<u64>().is_ok_and(|n| n > 0)
}

fn valid_repo(repo: &str) -> bool {
    repo.split_once('/').is_some_and(|(owner, name)| {
        openwiz_core::health::model::Repository::parse(owner, name).is_some()
            && matches!(
                std::path::Path::new(name).components().next(),
                Some(std::path::Component::Normal(_))
            )
    })
}
fn issues_suffix(path: &str) -> Option<&str> {
    if let Some(s) = path.strip_prefix("repos/{owner}/{repo}/issues/") {
        return Some(s);
    }
    let (repo, suffix) = path.strip_prefix("repos/")?.split_once("/issues/")?;
    valid_repo(repo).then_some(suffix)
}
fn commit_id(s: &str) -> bool {
    s.len() == 40
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn grill_file(s: &str) -> bool {
    s.strip_prefix("docs/grills/")
        .and_then(|s| s.strip_suffix(".md"))
        .is_some_and(|s| {
            s.as_bytes().first().is_some_and(u8::is_ascii_alphanumeric)
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
        })
}

fn source_repo(owner_flag: &str, owner: &str, name_flag: &str, name: &str) -> bool {
    if (owner_flag, owner, name_flag, name) == ("-F", "owner={owner}", "-F", "name={repo}") {
        return true;
    }
    owner_flag == "-f"
        && name_flag == "-f"
        && owner
            .strip_prefix("owner=")
            .zip(name.strip_prefix("name="))
            .is_some_and(|(owner, name)| valid_repo(&format!("{owner}/{name}")))
}

pub fn allows(argv: &[&str]) -> bool {
    match argv {
        [
            "repo",
            "view",
            "--json",
            "nameWithOwner" | "nameWithOwner,isPrivate",
        ] => true,
        ["repo", "view", repo, "--json", "nameWithOwner,isPrivate"] => valid_repo(repo),
        ["api", "--include", path, "--jq", COMMENT_FIELDS] => issues_suffix(path)
            .and_then(|s| s.strip_prefix("comments?per_page="))
            .and_then(|s| s.split_once("&sort=created&direction=desc&page="))
            .is_some_and(|(size, page)| matches!(size, "1" | "100") && positive(page)),
        ["api", path, "--jq", SUBJECT_FIELDS] => issues_suffix(path).is_some_and(positive),
        ["api", path, "--jq", GRILL_HEAD_FIELDS] => path
            .strip_prefix("repos/{owner}/{repo}/pulls/")
            .or_else(|| {
                let (repo, suffix) = path.strip_prefix("repos/")?.split_once("/pulls/")?;
                valid_repo(repo).then_some(suffix)
            })
            .is_some_and(positive),
        [
            "api",
            "graphql",
            owner_flag,
            owner,
            name_flag,
            name,
            "-f",
            query,
            "-F",
            number,
            "-f",
            expression,
        ] => {
            source_repo(owner_flag, owner, name_flag, name)
                && *query == format!("query={GRILL_QUERY}")
                && number.strip_prefix("number=").is_some_and(positive)
                && expression
                    .strip_prefix("expression=")
                    .and_then(|s| s.split_once(':'))
                    .is_some_and(|(head, path)| commit_id(head) && grill_file(path))
        }
        _ => false,
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Comment {
    pub repository: String,
    pub id: u64,
    pub subject: u64,
    pub body: String,
    pub created_at: u64,
    pub updated_at: u64,
}
pub struct Discovery {
    pub comments: Vec<Comment>,
    /// Duplicate identities within a single scan, as opposed to an edit
    /// observed across scans. Consumers must not select a winner for these.
    pub duplicate_ids: BTreeSet<(String, u64)>,
    pub errors: Vec<SourceError>,
    pub snapshot_complete: bool,
}
pub struct Subject {
    pub number: u64,
    pub body: Option<String>,
    pub is_pull_request: bool,
}

fn malformed() -> SourceError {
    SourceError::Malformed {
        detail: "decision source has an invalid shape or inconsistent pagination".into(),
    }
}

pub fn document(bytes: &[u8]) -> Option<Value> {
    strict::document(bytes)
}

fn exact(v: &Value, keys: &[&str]) -> bool {
    v.as_object()
        .is_some_and(|o| o.len() == keys.len() && keys.iter().all(|k| o.contains_key(*k)))
}

#[derive(Clone, Debug)]
pub struct GitHubDecisions {
    program: PathBuf,
    repositories: Result<Option<[String; 2]>, ()>,
}

impl GitHubDecisions {
    pub fn with_program(program: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
            repositories: Ok(None),
        }
    }

    pub fn from_path() -> Self {
        Self::with_program(crate::PROGRAM)
    }

    /// Read only the optional role setting, never infer a private sibling.
    /// A missing settings file preserves cwd; a bad setting never falls back.
    pub fn with_settings(mut self, path: &std::path::Path) -> Self {
        self.repositories = match std::fs::read(path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(_) => Err(()),
            Ok(bytes) => (|| {
                let value = document(&bytes).filter(Value::is_object).ok_or(())?;
                let Some(pair) = value.get("decision_repositories") else {
                    return Ok(None);
                };
                if !exact(pair, &["public", "private"]) {
                    return Err(());
                }
                let name = |role: &str| -> Result<String, ()> {
                    let repo = &pair[role];
                    if !exact(repo, &["owner", "name"]) {
                        return Err(());
                    }
                    let owner = repo["owner"].as_str().ok_or(())?;
                    let name = repo["name"].as_str().ok_or(())?;
                    let full = format!("{owner}/{name}");
                    if !valid_repo(&full) {
                        return Err(());
                    }
                    Ok(full)
                };
                let (public, private) = (name("public")?, name("private")?);
                if public.eq_ignore_ascii_case(&private) {
                    return Err(());
                }
                Ok(Some([public, private]))
            })(),
        };
        self
    }

    fn call(&self, argv: &[&str], deadline: Instant) -> Result<Vec<u8>, SourceError> {
        let call = Invocation::new(argv).ok_or_else(malformed)?;
        process::run(&self.program, &call, deadline)
    }

    pub fn subject(&self, n: u64, deadline: Instant) -> Result<Subject, SourceError> {
        if self
            .repositories
            .as_ref()
            .map_err(|_| malformed())?
            .is_some()
        {
            return Err(malformed());
        }
        self.subject_in("", n, deadline)
    }
    pub fn subject_in(
        &self,
        repo: &str,
        n: u64,
        deadline: Instant,
    ) -> Result<Subject, SourceError> {
        let explicit = self.repositories.as_ref().map_err(|_| malformed())?;
        if explicit
            .as_ref()
            .is_some_and(|p| !p.iter().any(|r| r.eq_ignore_ascii_case(repo)))
        {
            return Err(malformed());
        }
        let route = if explicit.is_some() {
            repo
        } else {
            "{owner}/{repo}"
        };
        let path = format!("repos/{route}/issues/{n}");
        let out = self.call(&["api", &path, "--jq", SUBJECT_FIELDS], deadline)?;
        let v = document(&out)
            .filter(|v| exact(v, &["number", "body", "is_pull_request"]))
            .ok_or_else(malformed)?;
        if v["number"].as_u64() != Some(n) {
            return Err(malformed());
        }
        Ok(Subject {
            number: n,
            body: match &v["body"] {
                Value::Null => None,
                Value::String(body) => Some(body.clone()),
                _ => return Err(malformed()),
            },
            is_pull_request: v["is_pull_request"].as_bool().ok_or_else(malformed)?,
        })
    }

    /// Read only the named saved grill at this PR's current immutable head.
    /// The blob read rechecks the PR head; a moved head or unavailable object
    /// is an incomplete read, never a fallback to the default branch.
    pub fn grill(&self, n: u64, file: &str, deadline: Instant) -> Result<String, SourceError> {
        self.grill_in("", n, file, deadline)
    }

    /// Bind the saved source to the verified comment repository, as subject_in does.
    pub fn grill_in(
        &self,
        repo: &str,
        n: u64,
        file: &str,
        deadline: Instant,
    ) -> Result<String, SourceError> {
        let explicit = self.repositories.as_ref().map_err(|_| malformed())?;
        if explicit
            .as_ref()
            .is_some_and(|p| !p.iter().any(|r| r.eq_ignore_ascii_case(repo)))
        {
            return Err(malformed());
        }
        let (route, owner_flag, owner, name_flag, name) = if explicit.is_some() {
            let (owner, name) = repo
                .split_once('/')
                .filter(|_| valid_repo(repo))
                .ok_or_else(malformed)?;
            (
                repo,
                "-f",
                format!("owner={owner}"),
                "-f",
                format!("name={name}"),
            )
        } else {
            (
                "{owner}/{repo}",
                "-F",
                "owner={owner}".to_owned(),
                "-F",
                "name={repo}".to_owned(),
            )
        };
        if !grill_file(file) {
            return Err(malformed());
        }
        let path = format!("repos/{route}/pulls/{n}");
        let out = self.call(&["api", &path, "--jq", GRILL_HEAD_FIELDS], deadline)?;
        let head = document(&out)
            .filter(|v| exact(v, &["number", "head_sha"]) && v["number"].as_u64() == Some(n))
            .ok_or_else(malformed)?;
        let head = head["head_sha"]
            .as_str()
            .filter(|s| commit_id(s))
            .ok_or_else(malformed)?;
        let query = format!("query={GRILL_QUERY}");
        let number = format!("number={n}");
        let expression = format!("expression={head}:{file}");
        let out = self.call(
            &[
                "api",
                "graphql",
                owner_flag,
                &owner,
                name_flag,
                &name,
                "-f",
                &query,
                "-F",
                &number,
                "-f",
                &expression,
            ],
            deadline,
        )?;
        let v = document(&out).ok_or_else(malformed)?;
        let data = &v["data"];
        let repo = &data["repository"];
        let pr = &repo["pullRequest"];
        let blob = &repo["object"];
        if !exact(&v, &["data"])
            || !exact(data, &["repository"])
            || !exact(repo, &["pullRequest", "object"])
            || !exact(pr, &["number", "headRefOid"])
            || pr["number"].as_u64() != Some(n)
            || pr["headRefOid"].as_str() != Some(head)
            || !exact(blob, &["__typename", "text", "isTruncated"])
            || blob["__typename"] != "Blob"
            || blob["isTruncated"] != false
        {
            return Err(malformed());
        }
        blob["text"]
            .as_str()
            .map(str::to_owned)
            .ok_or_else(malformed)
    }

    fn page(
        &self,
        repo: &str,
        page: u64,
        size: u64,
        deadline: Instant,
    ) -> Result<(Vec<Value>, Option<u64>), SourceError> {
        let route = if self.repositories.as_ref().is_ok_and(Option::is_some) {
            repo
        } else {
            "{owner}/{repo}"
        };
        let path = format!(
            "repos/{route}/issues/comments?per_page={size}&sort=created&direction=desc&page={page}"
        );
        let out = self.call(
            &["api", "--include", &path, "--jq", COMMENT_FIELDS],
            deadline,
        )?;
        let text = std::str::from_utf8(&out)
            .map_err(|_| malformed())?
            .replace("\r\n", "\n");
        let (head, body) = text.split_once("\n\n").ok_or_else(malformed)?;
        let mut lines = head.lines();
        let status: Vec<_> = lines
            .next()
            .ok_or_else(malformed)?
            .split_whitespace()
            .collect();
        if status.len() < 2 || !status[0].starts_with("HTTP/") || status[1] != "200" {
            return Err(malformed());
        }
        let mut last = None;
        let mut seen_link = false;
        for line in lines {
            let (key, value) = line.split_once(':').ok_or_else(malformed)?;
            if !key.eq_ignore_ascii_case("link") {
                continue;
            }
            if seen_link {
                return Err(malformed());
            }
            seen_link = true;
            let mut relations = BTreeSet::new();
            for link in value.trim().split(',') {
                let (url, rel) = link.trim().split_once("; rel=\"").ok_or_else(malformed)?;
                let rel = rel.strip_suffix('"').ok_or_else(malformed)?;
                if !matches!(rel, "first" | "prev" | "next" | "last") || !relations.insert(rel) {
                    return Err(malformed());
                }
                let prefix = format!("<https://api.github.com/repos/{repo}/issues/comments?");
                let query = url
                    .strip_prefix(&prefix)
                    .or_else(|| {
                        let (id, query) = url
                            .strip_prefix("<https://api.github.com/repositories/")?
                            .split_once("/issues/comments?")?;
                        positive(id).then_some(query)
                    })
                    .and_then(|s| s.strip_suffix('>'))
                    .ok_or_else(malformed)?;
                let mut pairs = std::collections::BTreeMap::new();
                for pair in query.split('&') {
                    let (k, v) = pair.split_once('=').ok_or_else(malformed)?;
                    if pairs.insert(k, v).is_some() {
                        return Err(malformed());
                    }
                }
                let size_text = size.to_string();
                if pairs.len() != 4
                    || pairs.get("per_page") != Some(&size_text.as_str())
                    || pairs.get("sort") != Some(&"created")
                    || pairs.get("direction") != Some(&"desc")
                {
                    return Err(malformed());
                }
                let n = *pairs.get("page").ok_or_else(malformed)?;
                if !positive(n) {
                    return Err(malformed());
                }
                if rel == "last" {
                    last = Some(n.parse().map_err(|_| malformed())?);
                }
            }
        }
        let v = document(body.as_bytes()).ok_or_else(malformed)?;
        let rows = v.as_array().ok_or_else(malformed)?.clone();
        if rows.len() as u64 > size {
            return Err(malformed());
        }
        Ok((rows, last))
    }

    fn count(&self, repo: &str, deadline: Instant) -> Result<u64, SourceError> {
        let (rows, last) = self.page(repo, 1, 1, deadline)?;
        match last {
            Some(total) if total > 1 && rows.len() == 1 => Ok(total),
            None => Ok(rows.len() as u64),
            _ => Err(malformed()),
        }
    }

    pub fn read(&self, deadline: Instant) -> Discovery {
        self.read_with(deadline, |_| {})
    }

    /// Observe each parsed comment before reading further pages. Consumers
    /// can verify needed identities while the original budget is available.
    pub fn read_with(&self, deadline: Instant, mut observe: impl FnMut(&Comment)) -> Discovery {
        let mut all = Self::empty();
        let repos = match &self.repositories {
            Err(()) => {
                all.errors.push(malformed());
                all.snapshot_complete = false;
                return all;
            }
            Ok(Some(pair)) => pair
                .iter()
                .enumerate()
                .map(|(i, r)| {
                    (|| {
                        let bytes = self.call(
                            &["repo", "view", r, "--json", "nameWithOwner,isPrivate"],
                            deadline,
                        )?;
                        let v = document(&bytes)
                            .filter(|v| exact(v, &["nameWithOwner", "isPrivate"]))
                            .ok_or_else(malformed)?;
                        let name = v["nameWithOwner"]
                            .as_str()
                            .filter(|n| valid_repo(n) && n.eq_ignore_ascii_case(r))
                            .ok_or_else(malformed)?;
                        if v["isPrivate"].as_bool() != Some(i == 1) {
                            return Err(malformed());
                        }
                        Ok(name.to_owned())
                    })()
                })
                .collect::<Vec<_>>(),
            Ok(None) => vec![(|| {
                let bytes = self.call(&["repo", "view", "--json", "nameWithOwner"], deadline)?;
                let v = document(&bytes)
                    .filter(|v| exact(v, &["nameWithOwner"]))
                    .ok_or_else(malformed)?;
                v["nameWithOwner"]
                    .as_str()
                    .filter(|n| valid_repo(n))
                    .map(str::to_owned)
                    .ok_or_else(malformed)
            })()],
        };
        for repo in repos {
            match repo {
                Ok(repo) => {
                    let read = self.read_repository(&repo, deadline, &mut observe);
                    all.comments.extend(read.comments);
                    all.duplicate_ids.extend(read.duplicate_ids);
                    all.errors.extend(read.errors);
                    all.snapshot_complete &= read.snapshot_complete;
                }
                Err(error) => {
                    all.errors.push(error);
                    all.snapshot_complete = false;
                }
            }
        }
        all
    }
    fn empty() -> Discovery {
        Discovery {
            comments: vec![],
            duplicate_ids: BTreeSet::new(),
            errors: vec![],
            snapshot_complete: true,
        }
    }
    /// The configured role is a transport fact; consumers decide which
    /// request kinds belong there. Single-repository mode has no role pair.
    pub fn private_role(&self, repo: &str) -> Option<bool> {
        self.repositories
            .as_ref()
            .ok()?
            .as_ref()?
            .iter()
            .position(|r| r.eq_ignore_ascii_case(repo))
            .map(|i| i == 1)
    }
    fn read_repository(
        &self,
        repo: &str,
        deadline: Instant,
        mut observe: impl FnMut(&Comment),
    ) -> Discovery {
        let mut read = Discovery {
            comments: Vec::new(),
            duplicate_ids: BTreeSet::new(),
            errors: Vec::new(),
            snapshot_complete: true,
        };
        let result = (|| {
            self.scan(repo, deadline, &mut read, &mut observe)?;
            let mut verification = Discovery {
                comments: Vec::new(),
                duplicate_ids: BTreeSet::new(),
                errors: Vec::new(),
                snapshot_complete: true,
            };
            // Verification is another bounded observation under the same
            // deadline, not a retry or a claim of an atomic GitHub snapshot.
            let checked = self.scan(repo, deadline, &mut verification, &mut observe);
            if checked.is_ok() && read.comments != verification.comments {
                read.errors.push(malformed());
                read.snapshot_complete = false;
            }
            let seen: BTreeMap<_, _> = read
                .comments
                .iter()
                .enumerate()
                .map(|(i, c)| (c.id, i))
                .collect();
            for row in verification.comments {
                if !seen.get(&row.id).is_some_and(|&i| read.comments[i] == row) {
                    // Preserve newly observed records and conflicting edits.
                    // Duplicate identities remain ambiguous to the consumer.
                    read.comments.push(row);
                }
            }
            for error in verification.errors {
                if !read.errors.contains(&error) {
                    read.errors.push(error);
                }
            }
            read.duplicate_ids.extend(verification.duplicate_ids);
            checked?;
            if !read.errors.is_empty() {
                read.snapshot_complete = false;
            }
            Ok(())
        })();
        if let Err(error) = result {
            read.errors.push(error);
            read.snapshot_complete = false;
        }
        read
    }

    fn scan(
        &self,
        repo: &str,
        deadline: Instant,
        read: &mut Discovery,
        observe: &mut impl FnMut(&Comment),
    ) -> Result<(), SourceError> {
        // Newest pages come first so an incomplete read retains recent work.
        // Full coverage still requires totals, unique ids and verification.
        let total = self.count(repo, deadline)?;
        let mut ids = BTreeSet::new();
        for page in 1..=total.div_ceil(100) {
            let (rows, last) = self.page(repo, page, 100, deadline)?;
            if rows.len() as u64 != (total - (page - 1) * 100).min(100)
                || last.is_some_and(|n| n != total.div_ceil(100))
            {
                return Err(malformed());
            }
            for row in rows {
                match comment(&row, repo) {
                    Some(row) => {
                        if !ids.insert(row.id) {
                            read.duplicate_ids.insert((repo.to_owned(), row.id));
                        }
                        observe(&row);
                        read.comments.push(row);
                    }
                    None => read.errors.push(malformed()),
                }
            }
        }
        if self.count(repo, deadline)? != total {
            return Err(malformed());
        }
        if !read.duplicate_ids.is_empty() {
            return Err(malformed());
        }
        Ok(())
    }
}

fn comment(v: &Value, repo: &str) -> Option<Comment> {
    if !exact(v, &["id", "body", "issue_url", "created_at", "updated_at"]) {
        return None;
    }
    let id = v["id"].as_u64().filter(|n| *n > 0)?;
    let prefix = format!("https://api.github.com/repos/{repo}/issues/");
    let subject = v["issue_url"].as_str()?.strip_prefix(&prefix)?;
    if !positive(subject) {
        return None;
    }
    let created_at = iso_ms(v["created_at"].as_str()?)?;
    let updated_at = iso_ms(v["updated_at"].as_str()?)?;
    if updated_at < created_at {
        return None;
    }
    Some(Comment {
        repository: repo.to_owned(),
        id,
        subject: subject.parse().ok()?,
        body: v["body"].as_str()?.into(),
        created_at,
        updated_at,
    })
}

fn iso_ms(s: &str) -> Option<u64> {
    let b = s.as_bytes();
    if b.len() != 20
        || b[4] != b'-'
        || b[7] != b'-'
        || b[10] != b'T'
        || b[13] != b':'
        || b[16] != b':'
        || b[19] != b'Z'
    {
        return None;
    }
    let n = |a: usize, z: usize| {
        let v = &s[a..z];
        v.bytes()
            .all(|b| b.is_ascii_digit())
            .then(|| v.parse::<i64>().ok())
            .flatten()
    };
    let (year, month, day, hour, minute, second) = (
        n(0, 4)?,
        n(5, 7)?,
        n(8, 10)?,
        n(11, 13)?,
        n(14, 16)?,
        n(17, 19)?,
    );
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days = [
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
    if !(1970..=9999).contains(&year)
        || !(1..=12).contains(&month)
        || day < 1
        || day > days[(month - 1) as usize]
        || hour > 23
        || minute > 59
        || second > 59
    {
        return None;
    }
    let y = year - i64::from(month <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * ((month + 9) % 12) + 2) / 5 + day - 1;
    let date = era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468;
    u64::try_from(((date * 24 + hour) * 60 + minute) * 60000 + second * 1000).ok()
}
