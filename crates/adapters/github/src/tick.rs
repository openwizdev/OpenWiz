//! B5's additional GitHub reads. Every invocation is a fixed GET form;
//! projections discard account data at the boundary. No product decisions or writes.
//! REST shapes: docs.github.com/en/rest/{actions/workflow-runs,pulls/pulls,issues/events}.
//! Projection shapes are synthetic until B6 observes them; failed or incomplete reads
//! remain errors. In particular, CI provenance is never inferred from today's base.
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::time::Instant;

use openwiz_core::fleet::model::{Check, CheckResult, Commit, NonEmpty, Number};
use openwiz_core::fleet::tick::{ChangedFile, CheckRun, ReportComment};
use openwiz_core::new_thread::read::StrictJson;
use serde_json::{Map, Value};

use crate::allowlist::{Invocation, Module};
use openwiz_core::fleet::tickets::GitHub;

pub const ALLOWLIST: Module = Module {
    name: "tick",
    allows,
};
pub const REPOSITORY_FIELDS: &str = "defaultBranchRef,nameWithOwner,url";
pub const COMMENTS: &str = "map({id,body,created: (.created_at | fromdateiso8601 * 1000),updated: (.updated_at | fromdateiso8601 * 1000)})";
pub const REPOSITORY_COMMENTS: &str = "map({issue_url,id,body,created: (.created_at | fromdateiso8601 * 1000),updated: (.updated_at | fromdateiso8601 * 1000)})";
pub const FILES: &str = "map({path: .filename,previous: (.previous_filename // null),status})";
pub const EVENTS: &str = "map(select(.event == \"labeled\" or .event == \"unlabeled\" or .event == \"commented\") | {id,event,label: (.label.name // null),body: (.body // null),at: (.created_at | fromdateiso8601 * 1000)})";
pub const RUNS: &str = "{total_count,runs: [.workflow_runs[] | {id,head_sha,event,run_attempt,updated: (.updated_at | fromdateiso8601 * 1000),prs: [.pull_requests[] | {number,head: .head.sha,base: .base.sha}]}]}";
pub const JOBS: &str =
    "{total_count,jobs: [.jobs[] | {id,name,status,conclusion,head_sha,run_id}]}";
pub const COMMIT: &str = "{sha,subject: .commit.message}";
pub const REF: &str = "{sha: .object.sha}";
const PREFIX: &str = "repos/{owner}/{repo}/";
const RAW: &str = "Accept: application/vnd.github.raw+json";

fn positive(s: &str) -> bool {
    !s.starts_with('0') && s.bytes().all(|b| b.is_ascii_digit()) && s.parse::<Number>().is_ok()
}
fn allows(argv: &[&str]) -> bool {
    match argv {
        ["repo", "view", "--json", REPOSITORY_FIELDS] => true,
        ["api", p, "--header", RAW] => p
            .strip_prefix(&format!("{PREFIX}contents/docs/agents/fleet.md?ref="))
            .is_some_and(|s| Commit::parse(s).is_some()),
        ["api", p, "--jq", jq] => {
            if *jq == REPOSITORY_COMMENTS {
                return p
                    .strip_prefix(&format!("{PREFIX}issues/comments?per_page=100&page="))
                    .is_some_and(positive);
            }
            if *jq == COMMIT {
                return p
                    .strip_prefix(&format!("{PREFIX}commits/"))
                    .is_some_and(|s| Commit::parse(s).is_some());
            }
            *jq == REF
                && p.strip_prefix(&format!("{PREFIX}git/ref/heads/"))
                    .is_some_and(crate::fleets::is_branch)
        }
        ["api", p, "--paginate", "--jq", jq] => {
            let Some(p) = p.strip_prefix(PREFIX) else {
                return false;
            };
            if let Some(s) = p.strip_prefix("issues/") {
                return s.split_once('/').is_some_and(|(n, rest)| {
                    positive(n)
                        && ((rest == "comments?per_page=100" && *jq == COMMENTS)
                            || (rest == "timeline?per_page=100" && *jq == EVENTS))
                });
            }
            if let Some(s) = p.strip_prefix("pulls/") {
                return s.strip_suffix("/files?per_page=100").is_some_and(positive) && *jq == FILES;
            }
            if let Some(s) = p.strip_prefix("actions/runs?head_sha=") {
                return s
                    .strip_suffix("&per_page=100")
                    .is_some_and(|s| Commit::parse(s).is_some())
                    && *jq == RUNS;
            }
            if let Some(s) = p.strip_prefix("actions/runs/") {
                return s
                    .strip_suffix("/jobs?filter=latest&per_page=100")
                    .is_some_and(positive)
                    && *jq == JOBS;
            }
            false
        }
        _ => false,
    }
}

pub type Result<T> = std::result::Result<T, &'static str>;
#[derive(Clone, Debug)]
pub struct Comment {
    pub id: Number,
    pub body: String,
    pub created: u64,
    pub updated: u64,
}
impl Comment {
    pub fn report(&self) -> ReportComment {
        ReportComment {
            comment: self.id,
            text: self.body.clone(),
        }
    }
}
/// Complete pagination, with malformed identified issues withheld in full.
/// An unread group never supplies an older approval or partial report list.
pub struct RepositoryComments {
    pub comments: BTreeMap<Number, Vec<Comment>>,
    pub unread: BTreeSet<Number>,
}
/// The existing PR inventory, retaining closed PR links for agent cleanup.
pub struct PullRequests {
    pub rows: Vec<openwiz_core::fleet::fleets::PrRow>,
    pub closed: BTreeMap<Number, Vec<(openwiz_core::fleet::fleets::Link, String)>>,
}
#[derive(Clone, Debug)]
pub struct Event {
    pub id: Number,
    pub event: String,
    pub label: Option<String>,
    pub body: Option<String>,
    pub at: u64,
}
pub struct Repository {
    pub name: String,
    pub url: String,
    pub default: NonEmpty,
}
pub struct TickReads {
    executor: crate::process::Executor,
}
impl TickReads {
    pub fn from_path() -> Self {
        Self::new(crate::PROGRAM)
    }
    pub fn new(program: impl Into<PathBuf>) -> Self {
        Self::with_executor(crate::process::Executor::program(program))
    }
    pub fn with_executor(executor: crate::process::Executor) -> Self {
        Self { executor }
    }
    pub fn executor(&self) -> &crate::process::Executor {
        &self.executor
    }
    pub fn pull_requests(&self, deadline: Instant) -> Result<PullRequests> {
        use openwiz_core::fleet::fleets::{Link, PrFacts, PrRow};
        use openwiz_core::fleet::tickets::PrState;
        let v = self.json(
            &[
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                crate::fleets::PR_FIELDS,
            ],
            deadline,
        )?;
        let mut rows = Vec::new();
        let mut closed = BTreeMap::new();
        for v in array(&v)? {
            let row = object(v, &crate::fleets::PR_FIELDS.split(',').collect::<Vec<_>>())?;
            if string(&row["title"])?.is_empty() {
                return Err("empty PR title");
            }
            let mut references = Vec::new();
            for r in array(&v["closingIssuesReferences"])? {
                let r = object(r, &["id", "number", "repository", "url"])?;
                let repo = object(&r["repository"], &["id", "name", "owner"])?;
                string(&repo["id"])?;
                string(&repo["name"])?;
                let owner = object(&repo["owner"], &["id", "login"])?;
                string(&owner["id"])?;
                string(&owner["login"])?;
                references.push((
                    Link {
                        number: number(&r["number"])?,
                        id: NonEmpty::new(string(&r["id"])?.to_owned()).ok_or("empty issue id")?,
                    },
                    string(&r["url"])?.to_owned(),
                ));
            }
            unique(references.iter().map(|(r, _)| r.number.get()))?;
            unique(references.iter().map(|(r, _)| &r.id))?;
            if string(&row["state"])? == "CLOSED" {
                let number = number(&row["number"])?;
                row["isDraft"].as_bool().ok_or("invalid draft flag")?;
                for key in ["baseRefName", "headRefName", "headRefOid"] {
                    string(&row[key])?;
                }
                if !row["mergeCommit"].is_null() || !row["mergedAt"].is_null() {
                    return Err("closed PR has merge facts");
                }
                closed.insert(number, references);
                rows.push(PrRow::Closed { number });
                continue;
            }
            // PR-view decoding/records keep their exact pre-AL1 shape.
            let mut view = v.clone();
            view.as_object_mut()
                .ok_or("PR is not an object")?
                .remove("title");
            let p = crate::tickets::pull_request(
                &serde_json::to_vec(&view).map_err(|_| "PR encoding failed")?,
            )
            .map_err(|_| "PR inventory unread")?;
            let facts = PrFacts {
                number: p.number,
                draft: p.draft,
                head_branch: p.head_branch,
                head_commit: p.head_commit,
                base_branch: p.base_branch,
                closes: references.iter().map(|(r, _)| r.clone()).collect(),
            };
            rows.push(match p.state {
                PrState::Open => PrRow::Open(facts),
                PrState::Merged {
                    merge_commit,
                    merged_at,
                } => PrRow::Merged {
                    facts,
                    merge_commit,
                    merged_at,
                },
                PrState::Closed => return Err("PR state changed while parsing"),
            });
        }
        Ok(PullRequests { rows, closed })
    }
    fn call(&self, argv: &[&str], deadline: Instant) -> Result<Vec<u8>> {
        let call = Invocation::new(argv).ok_or("tick read is not allowlisted")?;
        self.executor
            .run(&call, deadline)
            .map_err(|_| "GitHub tick read failed")
    }
    fn json(&self, argv: &[&str], deadline: Instant) -> Result<Value> {
        document(&self.call(argv, deadline)?)
    }
    fn pages(&self, path: &str, jq: &str, deadline: Instant) -> Result<Value> {
        let bytes = self.call(
            &["api", &format!("{PREFIX}{path}"), "--paginate", "--jq", jq],
            deadline,
        )?;
        let text = std::str::from_utf8(&bytes).map_err(|_| "pages are not UTF-8")?;
        let pages = text
            .lines()
            .map(|l| document(l.as_bytes()))
            .collect::<Result<Vec<_>>>()?;
        if pages.is_empty() {
            return Err("missing pages");
        }
        Ok(Value::Array(pages))
    }
    pub fn repository(&self, deadline: Instant) -> Result<Repository> {
        repository(&self.json(&["repo", "view", "--json", REPOSITORY_FIELDS], deadline)?)
    }
    pub fn branch(&self, branch: &str, deadline: Instant) -> Result<Commit> {
        let v = self.json(
            &[
                "api",
                &format!("{PREFIX}git/ref/heads/{branch}"),
                "--jq",
                REF,
            ],
            deadline,
        )?;
        let o = object(&v, &["sha"])?;
        commit(&o["sha"])
    }
    /// Compare immutable commit identities, using the existing fleet compare form.
    pub fn contains(&self, merged: &Commit, base: &Commit, deadline: Instant) -> Result<bool> {
        let v = self.json(
            &[
                "api",
                &format!("{PREFIX}compare/{}...{}", merged.as_str(), base.as_str()),
                "--jq",
                "{status: .status, behind_by: .behind_by}",
            ],
            deadline,
        )?;
        let o = object(&v, &["status", "behind_by"])?;
        match (string(&o["status"])?, uint(&o["behind_by"])?) {
            ("ahead" | "identical", 0) => Ok(true),
            ("behind" | "diverged", _) => Ok(false),
            _ => Err("invalid compare state"),
        }
    }
    pub fn rules(&self, at: &Commit, deadline: Instant) -> Result<String> {
        let bytes = self.call(
            &[
                "api",
                &format!("{PREFIX}contents/docs/agents/fleet.md?ref={}", at.as_str()),
                "--header",
                RAW,
            ],
            deadline,
        )?;
        String::from_utf8(bytes).map_err(|_| "rules are not UTF-8")
    }
    pub fn comments(&self, issue: Number, deadline: Instant) -> Result<Vec<Comment>> {
        comments(&self.pages(
            &format!("issues/{issue}/comments?per_page=100"),
            COMMENTS,
            deadline,
        )?)
    }
    /// One complete repository-wide snapshot, including PR conversation comments.
    /// Successful pagination proves empty groups; write gates keep scoped reads.
    pub fn repository_comments(
        &self,
        repo: &Repository,
        deadline: Instant,
    ) -> Result<RepositoryComments> {
        self.repository_comments_with_page_deadline(repo, |_| Ok(deadline))
    }
    /// One process per page, each subject to the runner's READ_TIMEOUT.
    /// The caller supplies the run deadline for the total discovered page work;
    /// returning an error or failing any page exposes no partial snapshot.
    pub fn repository_comments_with_page_deadline(
        &self,
        repo: &Repository,
        mut deadline: impl FnMut(usize) -> Result<Instant>,
    ) -> Result<RepositoryComments> {
        let origin = repo
            .url
            .strip_prefix("https://")
            .and_then(|u| u.split_once('/'))
            .ok_or("invalid repository URL")?;
        if !origin.1.eq_ignore_ascii_case(&repo.name)
            || origin.0.is_empty()
            || !origin
                .0
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b':'))
        {
            return Err("invalid repository URL");
        }
        let api = if origin.0 == "github.com" {
            "https://api.github.com".to_owned()
        } else {
            format!("https://{}/api/v3", origin.0)
        };
        let prefix = format!("{api}/repos/{}/issues/", repo.name);
        let mut out: BTreeMap<Number, Vec<Comment>> = BTreeMap::new();
        let mut ids = BTreeMap::new();
        let mut unread = BTreeSet::new();
        let mut page = 1usize;
        let mut bytes_read = 0usize;
        loop {
            let bytes = self.call(
                &[
                    "api",
                    &format!("{PREFIX}issues/comments?per_page=100&page={page}"),
                    "--jq",
                    REPOSITORY_COMMENTS,
                ],
                deadline(page)?,
            )?;
            // Preserve the previous aggregate process's output bound.
            bytes_read = bytes_read
                .checked_add(bytes.len())
                .filter(|n| *n <= crate::process::MAX_STDOUT_BYTES)
                .ok_or("repository comments exceed output bound")?;
            let document = document(&bytes)?;
            let rows = array(&document)?;
            if rows.len() > 100 {
                return Err("oversized comment page");
            }
            for v in rows {
                let target = string(v.get("issue_url").ok_or("comment has no issue identity")?)?
                    .strip_prefix(&prefix)
                    .ok_or("comment belongs to another repository or origin")?;
                if !positive(target) {
                    return Err("invalid comment issue identity");
                }
                let target = target
                    .parse()
                    .map_err(|_| "invalid comment issue identity")?;
                if let Some(id) = v.get("id").and_then(|v| number(v).ok())
                    && let Some(previous) = ids.insert(id, target)
                {
                    unread.extend([previous, target]);
                }
                match object(v, &["issue_url", "id", "body", "created", "updated"])
                    .and_then(comment)
                {
                    Ok(c) => out.entry(target).or_default().push(c),
                    Err(_) => {
                        unread.insert(target);
                    }
                }
            }
            if rows.len() < 100 {
                break;
            }
            page = page.checked_add(1).ok_or("comment page overflow")?;
        }
        for comments in out.values_mut() {
            comments.sort_by_key(|c| c.id);
        }
        for number in &unread {
            out.remove(number);
        }
        Ok(RepositoryComments {
            comments: out,
            unread,
        })
    }
    pub fn events(&self, issue: Number, deadline: Instant) -> Result<Vec<Event>> {
        let v = self.pages(
            &format!("issues/{issue}/timeline?per_page=100"),
            EVENTS,
            deadline,
        )?;
        let mut out = vec![];
        for v in paged_rows(&v)? {
            let o = object(v, &["id", "event", "label", "body", "at"])?;
            out.push(Event {
                id: number(&o["id"])?,
                event: string(&o["event"])?.into(),
                label: nullable(&o["label"])?,
                body: nullable(&o["body"])?,
                at: uint(&o["at"])?,
            });
        }
        unique(out.iter().map(|e| (e.event.as_str(), e.id.get())))?;
        Ok(out)
    }
    pub fn files(&self, pr: Number, deadline: Instant) -> Result<Vec<ChangedFile>> {
        let v = self.pages(&format!("pulls/{pr}/files?per_page=100"), FILES, deadline)?;
        let rows = paged_rows(&v)?;
        if rows.len() >= 3000 {
            return Err("changed files may be truncated");
        }
        let mut out = vec![];
        for v in rows {
            let o = object(v, &["path", "previous", "status"])?;
            let status = string(&o["status"])?;
            if ![
                "added",
                "removed",
                "modified",
                "renamed",
                "copied",
                "changed",
                "unchanged",
            ]
            .contains(&status)
            {
                return Err("unknown file status");
            }
            let previous_path = nullable(&o["previous"])?
                .map(|s| NonEmpty::new(s).ok_or("empty previous path"))
                .transpose()?;
            if (status == "renamed") != previous_path.is_some() {
                return Err("rename without provenance");
            }
            out.push(ChangedFile {
                path: NonEmpty::new(string(&o["path"])?.to_owned()).ok_or("empty path")?,
                previous_path,
                added: status == "added",
            });
        }
        unique(out.iter().map(|f| f.path.as_str()))?;
        Ok(out)
    }
    pub fn subject(&self, head: &Commit, deadline: Instant) -> Result<String> {
        let v = self.json(
            &[
                "api",
                &format!("{PREFIX}commits/{}", head.as_str()),
                "--jq",
                COMMIT,
            ],
            deadline,
        )?;
        let o = object(&v, &["sha", "subject"])?;
        if commit(&o["sha"])? != *head {
            return Err("commit names another head");
        }
        Ok(string(&o["subject"])?.lines().next().unwrap_or("").into())
    }
    /// Only jobs from pull_request runs explicitly naming this PR/head/base
    /// may constitute its CI. Mixed bases are refused, never set to base-now.
    pub fn checks(&self, pr: Number, head: &Commit, deadline: Instant) -> Result<Option<CheckRun>> {
        self.checks_with_parallelism(pr, head, deadline, 1)
    }
    /// The caller allocates these slots from its shared four-read planning cap.
    /// A failed page withholds the whole CI observation; there is no retry.
    pub fn checks_with_parallelism(
        &self,
        pr: Number,
        head: &Commit,
        deadline: Instant,
        parallel_jobs: usize,
    ) -> Result<Option<CheckRun>> {
        if !(1..=openwiz_core::fleet::tickets::MAX_CONCURRENT_READS).contains(&parallel_jobs) {
            return Err("invalid CI read allocation");
        }
        let v = self.pages(
            &format!("actions/runs?head_sha={}&per_page=100", head.as_str()),
            RUNS,
            deadline,
        )?;
        let rows = counted_pages(&v, "runs")?;
        let mut runs = vec![];
        for v in rows {
            let o = object(
                v,
                &["id", "head_sha", "event", "run_attempt", "updated", "prs"],
            )?;
            let id = number(&o["id"])?;
            if commit(&o["head_sha"])? != *head {
                return Err("workflow names another head");
            }
            number(&o["run_attempt"])?;
            let updated = uint(&o["updated"])?;
            let event = string(&o["event"])?;
            let mut own = vec![];
            for v in array(&o["prs"])? {
                let p = object(v, &["number", "head", "base"])?;
                let n = number(&p["number"])?;
                let h = commit(&p["head"])?;
                let b = commit(&p["base"])?;
                if n == pr && h == *head {
                    own.push(b);
                }
            }
            if event == "pull_request" {
                if own.len() != 1 {
                    return Err("CI has no unique PR provenance");
                }
                runs.push((updated, id, own.remove(0)));
            }
        }
        unique(runs.iter().map(|r| r.1.get()))?;
        runs.sort_by_key(|r| (r.0, r.1));
        let mut checks: std::collections::BTreeMap<NonEmpty, (Number, CheckResult, Commit)> =
            std::collections::BTreeMap::new();
        for chunk in runs.chunks(parallel_jobs) {
            let pages = std::thread::scope(|scope| {
                let workers = chunk
                    .iter()
                    .map(|(_, id, _)| {
                        scope.spawn(move || {
                            self.pages(
                                &format!("actions/runs/{id}/jobs?filter=latest&per_page=100"),
                                JOBS,
                                deadline,
                            )
                        })
                    })
                    .collect::<Vec<_>>();
                workers
                    .into_iter()
                    .map(|worker| worker.join().map_err(|_| "CI worker failed")?)
                    .collect::<Result<Vec<_>>>()
            })?;
            for ((_, id, base), v) in chunk.iter().cloned().zip(pages) {
                let rows = counted_pages(&v, "jobs")?;
                let mut names = BTreeSet::new();
                for v in rows {
                    let o = object(
                        v,
                        &["id", "name", "status", "conclusion", "head_sha", "run_id"],
                    )?;
                    let job_id = number(&o["id"])?;
                    if commit(&o["head_sha"])? != *head || number(&o["run_id"])? != id {
                        return Err("job names another run/head");
                    }
                    let name =
                        NonEmpty::new(string(&o["name"])?.to_owned()).ok_or("empty check name")?;
                    if !names.insert(name.clone()) {
                        return Err("duplicate check");
                    }
                    let result = match (
                        string(&o["status"])?,
                        nullable(&o["conclusion"])?.as_deref(),
                    ) {
                        ("queued" | "in_progress" | "waiting" | "pending" | "requested", None) => {
                            CheckResult::Pending
                        }
                        ("completed", Some("success")) => CheckResult::Pass,
                        ("completed", Some("skipped" | "neutral")) => CheckResult::Skipping,
                        ("completed", Some("cancelled")) => CheckResult::Cancel,
                        (
                            "completed",
                            Some(
                                "failure" | "timed_out" | "action_required" | "stale"
                                | "startup_failure",
                            ),
                        ) => CheckResult::Fail,
                        _ => return Err("unknown job outcome"),
                    };
                    if checks
                        .get(&name)
                        .is_none_or(|(latest, _, _)| job_id > *latest)
                    {
                        checks.insert(name, (job_id, result, base.clone()));
                    }
                }
            }
        }
        let tickets = crate::tickets::Tickets::with_executor(self.executor.clone());
        let all = tickets
            .checks(pr, deadline)
            .map_err(|_| "complete check set unread")?;
        unique(all.iter().map(|c| &c.name))?;
        let current = tickets
            .pull_request(pr, deadline)
            .map_err(|_| "current CI head unread")?;
        if current.head_commit != *head {
            return Err("PR head moved during CI read");
        }
        if all.len() != checks.len()
            || all.iter().any(|c| {
                checks
                    .get(&c.name)
                    .is_none_or(|(_, result, _)| *result != c.result)
            })
        {
            return Err("CI check set or latest results have no matching provenance");
        }
        if checks.is_empty() {
            return Ok(None);
        }
        let base = checks.values().next().unwrap().2.clone();
        if checks.values().any(|(_, _, b)| *b != base) {
            return Err("CI jobs tested different bases");
        }
        Ok(Some(CheckRun {
            head_commit: head.clone(),
            base_commit: base,
            checks: checks
                .into_iter()
                .map(|(name, (_, result, _))| Check { name, result })
                .collect(),
        }))
    }
}

pub fn document(bytes: &[u8]) -> Result<Value> {
    serde_json::from_slice::<StrictJson>(bytes).map_err(|_| "invalid or duplicate JSON value")?;
    serde_json::from_slice(bytes).map_err(|_| "invalid JSON")
}
pub fn object<'a>(v: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>> {
    let o = v.as_object().ok_or("expected object")?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err("unexpected object fields");
    }
    Ok(o)
}
pub fn string(v: &Value) -> Result<&str> {
    v.as_str().ok_or("expected string")
}
pub fn uint(v: &Value) -> Result<u64> {
    v.as_u64().ok_or("expected unsigned integer")
}
pub fn number(v: &Value) -> Result<Number> {
    Number::new(uint(v)?).ok_or("expected positive number")
}
pub fn commit(v: &Value) -> Result<Commit> {
    Commit::parse(string(v)?).ok_or("expected commit")
}
pub fn array(v: &Value) -> Result<&[Value]> {
    v.as_array().map(Vec::as_slice).ok_or("expected array")
}
pub fn nullable(v: &Value) -> Result<Option<String>> {
    if v.is_null() {
        Ok(None)
    } else {
        Ok(Some(string(v)?.into()))
    }
}
fn unique<T: Ord>(items: impl Iterator<Item = T>) -> Result<()> {
    let mut seen = BTreeSet::new();
    for item in items {
        if !seen.insert(item) {
            return Err("duplicate row");
        }
    }
    Ok(())
}
fn paged_rows(v: &Value) -> Result<Vec<&Value>> {
    let pages = array(v)?;
    if pages.is_empty() {
        return Err("missing pages");
    }
    let mut rows = vec![];
    for p in pages {
        rows.extend(array(p)?);
    }
    Ok(rows)
}
fn counted_pages<'a>(v: &'a Value, key: &str) -> Result<Vec<&'a Value>> {
    let pages = array(v)?;
    if pages.is_empty() {
        return Err("missing pages");
    }
    let mut rows = vec![];
    let mut count = None;
    for p in pages {
        let o = object(p, &["total_count", key])?;
        let total = uint(&o["total_count"])?;
        if count.is_some_and(|n| n != total) {
            return Err("changed page total");
        }
        count = Some(total);
        rows.extend(array(&o[key])?);
    }
    if Some(rows.len() as u64) != count {
        return Err("truncated pages");
    }
    Ok(rows)
}
pub fn repository(v: &Value) -> Result<Repository> {
    let o = object(v, &["defaultBranchRef", "nameWithOwner", "url"])?;
    let d = object(&o["defaultBranchRef"], &["name"])?;
    let branch = string(&d["name"])?;
    if !crate::fleets::is_branch(branch) {
        return Err("invalid default branch");
    }
    let name = string(&o["nameWithOwner"])?;
    openwiz_core::fleet::starts::Repository::parse(name).map_err(|_| "invalid repository")?;
    Ok(Repository {
        name: name.into(),
        url: string(&o["url"])?.into(),
        default: NonEmpty::new(branch.to_owned()).unwrap(),
    })
}
pub fn comments(v: &Value) -> Result<Vec<Comment>> {
    let mut out = vec![];
    for v in paged_rows(v)? {
        let o = object(v, &["id", "body", "created", "updated"])?;
        out.push(comment(o)?);
    }
    unique(out.iter().map(|c| c.id.get()))?;
    out.sort_by_key(|c| c.id);
    Ok(out)
}

fn comment(o: &Map<String, Value>) -> Result<Comment> {
    let created = uint(&o["created"])?;
    let updated = uint(&o["updated"])?;
    if updated < created {
        return Err("comment time reversed");
    }
    Ok(Comment {
        id: number(&o["id"])?,
        body: string(&o["body"])?.into(),
        created,
        updated,
    })
}
