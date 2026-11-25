use super::records;
use crate::state::StartFileStore;
use openwiz_adapter_cloudroom::{fleet as cloud, source::CloudRoomSource};
use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_adapter_github::tick::{Comment, Result, TickReads};
use openwiz_core::fleet::fleets::{FleetsSource, IssueRow, Links, PrFacts, PrRow};
use openwiz_core::fleet::model::{Commit, ListOutcome, MergedPr, NonEmpty, Number, PrFields};
use openwiz_core::fleet::starts::{self, AttemptOutcome, StartRecord};
use openwiz_core::fleet::tick::*;
use openwiz_core::messaging::OpId;
use openwiz_core::messaging::send::Messenger;
use openwiz_core::model::{Fact, SessionId};
use openwiz_core::source::{SessionRecord, SessionScope, SessionSource};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::rc::Rc;
use std::time::Instant;

#[derive(Clone, Copy)]
enum PlanningDeadline {
    Initial(Instant),
}
impl PlanningDeadline {
    fn at(self) -> Instant {
        match self {
            Self::Initial(deadline) => deadline,
        }
    }
    fn with_work(self, work_items: usize) -> Result<Instant> {
        match self {
            Self::Initial(deadline) => deadline
                .checked_add(openwiz_core::limits::fleet_tick_planning_allowance(
                    work_items,
                ))
                .ok_or("planning deadline overflow"),
        }
    }
}

#[derive(Default)]
struct MergeCache {
    files: BTreeMap<(String, Number, Commit, Commit), Vec<ChangedFile>>,
    contains: BTreeMap<(String, Commit, Commit), Result<bool>>,
}
#[derive(Clone)]
struct OpenReads {
    subject: String,
    ci: Option<CheckRun>,
    base_now: Commit,
}
enum Prefetch {
    Contains(Commit),
    Open(PrFacts),
}
enum Prefetched {
    Contains(Commit, Result<bool>),
    Open(Number, Result<OpenReads>),
}
fn open_reads(
    gh: &TickReads,
    pr: &PrFacts,
    deadline: Instant,
    parallel_jobs: usize,
) -> Result<OpenReads> {
    Ok(OpenReads {
        subject: gh.subject(&pr.head_commit, deadline)?,
        ci: gh.checks_with_parallelism(pr.number, &pr.head_commit, deadline, parallel_jobs)?,
        base_now: gh.branch(pr.base_branch.as_str(), deadline)?,
    })
}
pub struct Inventory {
    repository: openwiz_adapter_github::tick::Repository,
    issues: Vec<IssueRow>,
    prs: Vec<PrRow>,
    closed: BTreeMap<Number, Vec<(openwiz_core::fleet::fleets::Link, String)>>,
}
impl Inventory {
    pub fn read(gh: &TickReads, deadline: Instant) -> Result<Self> {
        let source = GitHubFleets::with_executor(gh.executor().clone());
        let (repository, issues, prs) = std::thread::scope(|scope| {
            let repository = scope.spawn(|| gh.repository(deadline));
            let issues = scope.spawn(|| {
                source
                    .issues(deadline)
                    .map_err(|_| "issue inventory unread")
            });
            let prs = scope.spawn(|| gh.pull_requests(deadline));
            Ok((
                repository
                    .join()
                    .map_err(|_| "repository worker failed")??,
                issues.join().map_err(|_| "issue worker failed")??,
                prs.join().map_err(|_| "PR worker failed")??,
            ))
        })?;
        if issues.cut_short || prs.rows.len() >= openwiz_adapter_github::fleets::LIST_LIMIT {
            return Err("repository inventory incomplete");
        }
        Ok(Self {
            repository,
            issues: issues.rows,
            prs: prs.rows,
            closed: prs.closed,
        })
    }
    pub fn is_empty(&self) -> bool {
        self.issues.is_empty()
    }
}
struct ClosedPrReferences {
    candidates: BTreeSet<Number>,
    targets: Result<Vec<Number>>,
}
struct Reviewers {
    agents: Vec<(u64, Reviewer)>,
    retired_rechecks: BTreeSet<Number>,
}
pub struct World {
    legacy_records: bool,
    cache: Rc<RefCell<MergeCache>>,
    base: Commit,
    unread_comments: BTreeSet<Number>,
    closed_prs: BTreeMap<Number, ClosedPrReferences>,
    pr_reads: BTreeMap<Number, Result<OpenReads>>,
    pub deadline: Instant,
    pub repository: openwiz_adapter_github::tick::Repository,
    pub issues: BTreeMap<Number, IssueRow>,
    pub prs: Vec<PrRow>,
    pub comments: BTreeMap<Number, Vec<Comment>>,
    pub authors: BTreeSet<String>,
    pub starts: Vec<StartRecord>,
    title_rows: RefCell<Option<Result<Vec<SessionRecord>>>>,
    pub project: Option<String>,
    pub orchestrator: Option<String>,
    pub snapshot: Snapshot,
    pub rules: Rules,
}
impl World {
    pub fn read(
        gh: &TickReads,
        room: Option<&CloudRoomSource>,
        state: &Path,
        deadline: Instant,
        inventory: Inventory,
    ) -> Result<Self> {
        Self::read_scoped(
            gh,
            room,
            state,
            PlanningDeadline::Initial(deadline),
            None,
            Rc::default(),
            inventory,
        )
    }
    fn read_scoped(
        gh: &TickReads,
        room: Option<&CloudRoomSource>,
        state: &Path,
        budget: PlanningDeadline,
        only_spec: Option<Number>,
        cache: Rc<RefCell<MergeCache>>,
        inventory: Inventory,
    ) -> Result<Self> {
        let deadline = budget.at();
        let Inventory {
            repository,
            issues: listed,
            prs,
            closed,
        } = inventory;
        let mut issues = BTreeMap::new();
        let mut nodes = BTreeSet::new();
        for row in listed {
            if !nodes.insert(row.id.clone()) || issues.insert(row.number, row).is_some() {
                return Err("duplicate issue");
            }
        }
        for row in issues.values() {
            links(&row.sub_issues, &issues)?;
            links(&row.blocked_by, &issues)?;
        }
        let closed_prs = closed
            .into_iter()
            .map(|(pr, refs)| {
                let candidates = refs
                    .iter()
                    .filter(|(link, _)| issues.get(&link.number).is_some_and(|i| i.id == link.id))
                    .map(|(link, _)| link.number)
                    .collect();
                let targets = (|| {
                    if refs.is_empty()
                        || refs.len() >= openwiz_core::fleet::fleets::MAX_CLOSING_REFERENCES
                    {
                        return Err("closed PR references incomplete");
                    }
                    let mut targets = Vec::new();
                    for (link, url) in refs {
                        if issues.get(&link.number).is_some_and(|i| i.id == link.id) {
                            if url != format!("{}/issues/{}", repository.url, link.number) {
                                return Err("closed PR reference identity disagrees");
                            }
                            targets.push(link.number);
                        }
                    }
                    Ok(targets)
                })();
                (
                    pr,
                    ClosedPrReferences {
                        candidates,
                        targets,
                    },
                )
            })
            .collect();
        let specs = issues
            .values()
            .filter(|i| !i.sub_issues.nodes.is_empty())
            .map(|i| i.number)
            .collect::<BTreeSet<_>>();
        let mut placed = BTreeMap::new();
        let mut unread_specs = BTreeSet::new();
        for spec in &specs {
            for link in &issues[spec].sub_issues.nodes {
                if specs.contains(&link.number) {
                    unread_specs.insert(*spec);
                    unread_specs.insert(link.number);
                }
                if let Some(other) = placed.insert(link.number, *spec) {
                    unread_specs.insert(other);
                    unread_specs.insert(*spec);
                }
            }
        }
        let mut pr_ids = BTreeSet::new();
        for row in &prs {
            let (id, refs) = match row {
                PrRow::Open(p) | PrRow::Merged { facts: p, .. } => (p.number, Some(&p.closes)),
                PrRow::Closed { number } => (*number, None),
            };
            if !pr_ids.insert(id) {
                return Err("duplicate PR");
            }
            if let Some(refs) = refs
                && refs.len() >= 100
            {
                return Err("closing references may be truncated");
            }
        }
        let branch = gh.branch(repository.default.as_str(), deadline)?;
        let text = gh.rules(&branch, deadline)?;
        let flags = crate::models::spawn_flags().map_err(|_| "rules unread or invalid")?;
        let rules = Rules::parse(&text, &flags).map_err(|_| "rules unread or invalid")?;
        let authors = records::record_authors(&text)?;
        let starts = if room.is_some() {
            start_records(state, &repository.name)?
        } else {
            vec![]
        };
        let project = if let Some(room) = room {
            let repo =
                cloud::Repository::parse(&repository.name).ok_or("invalid repository identity")?;
            match cloud::projects(room, &repo, deadline) {
                ListOutcome::Complete { value } if value.len() == 1 => {
                    Some(value[0].id.as_str().into())
                }
                _ => None,
            }
        } else {
            None
        };
        let prs: Vec<PrRow> = prs
            .into_iter()
            .map(|mut p| {
                if let PrRow::Open(facts) | PrRow::Merged { facts, .. } = &mut p {
                    facts
                        .closes
                        .retain(|r| issues.get(&r.number).is_some_and(|i| i.id == r.id));
                }
                p
            })
            .collect();
        let mut comment_pages = 0usize;
        let (comments, unread_comments) = if only_spec.is_none() {
            let all = gh.repository_comments_with_page_deadline(&repository, |page| {
                comment_pages = page;
                budget.with_work(page)
            })?;
            let mut comments = all
                .comments
                .into_iter()
                .map(|(n, cs)| (n, records::factory(cs, &authors)))
                .collect::<BTreeMap<_, _>>();
            for number in issues.keys().copied().chain(prs.iter().map(|p| match p {
                PrRow::Open(p) | PrRow::Merged { facts: p, .. } => p.number,
                PrRow::Closed { number } => *number,
            })) {
                comments.entry(number).or_default();
            }
            (comments, all.unread)
        } else {
            (BTreeMap::new(), BTreeSet::new())
        };
        let deadline = budget.with_work(comment_pages)?;
        let legacy_records = openwiz_adapter_github::allowlist::Invocation::new(&[
            "repo",
            "view",
            "--json",
            "nameWithOwner,isPrivate",
        ])
        .and_then(|call| gh.executor().run(&call, deadline).ok())
        .and_then(|bytes| openwiz_adapter_github::tick::document(&bytes).ok())
        .is_some_and(|metadata| records::private_repository(&repository.name, &metadata));
        let mut world = Self {
            legacy_records,
            cache,
            base: branch,
            unread_comments,
            closed_prs,
            pr_reads: BTreeMap::new(),
            deadline,
            snapshot: Snapshot {
                default_branch: Observed::Complete(repository.default.clone()),
                fleets: Observed::Complete(vec![]),
            },
            repository,
            issues,
            prs,
            comments,
            authors,
            starts,
            title_rows: RefCell::new(None),
            project,
            orchestrator: None,
            rules,
        };
        let specs = world
            .issues
            .values()
            .filter(|i| !i.sub_issues.nodes.is_empty())
            .map(|i| i.number)
            .collect::<Vec<_>>();
        world.prefetch(
            gh,
            &specs
                .iter()
                .copied()
                .filter(|s| only_spec.is_none_or(|n| n == *s) && !unread_specs.contains(s))
                .collect::<Vec<_>>(),
            budget,
            room.is_some(),
            comment_pages,
        )?;
        let deadline = world.deadline;
        let mut fleets = vec![];
        for spec in specs {
            if only_spec.is_some_and(|n| n != spec) {
                continue;
            }
            let facts = if unread_specs.contains(&spec) {
                Observed::Unread(vec![Problem::Graph])
            } else {
                world
                    .fleet(gh, room, spec, deadline)
                    .map(Observed::Complete)
                    .unwrap_or_else(|_| Observed::Unread(vec![Problem::Graph]))
            };
            fleets.push(FleetInput { spec, facts });
        }
        world.snapshot.fleets = Observed::Complete(fleets);
        Ok(world)
    }
    pub fn read_factory(
        &self,
        gh: &TickReads,
        number: Number,
        deadline: Instant,
    ) -> Result<Vec<Comment>> {
        Ok(records::factory(
            gh.comments(number, deadline)?,
            &self.authors,
        ))
    }
    fn read_comments(
        &mut self,
        gh: &TickReads,
        number: Number,
        deadline: Instant,
    ) -> Result<Vec<Comment>> {
        if self.unread_comments.contains(&number) {
            return Err("issue comments unread");
        }
        if let Some(c) = self.comments.get(&number) {
            records::check_forms(c, self.legacy_records)?;
            return Ok(c.clone());
        }
        let c = self.read_factory(gh, number, deadline)?;
        records::check_forms(&c, self.legacy_records)?;
        self.comments.insert(number, c.clone());
        Ok(c)
    }
    fn summary_needs_merges(
        &self,
        row: &IssueRow,
        approval: Option<&PlanApproval>,
        written: bool,
    ) -> bool {
        row.state == openwiz_core::fleet::model::IssueState::Open
            && !written
            && approval.is_some_and(|a| {
                !a.rows.is_empty()
                    && a.rows.keys().all(|n| {
                        row.sub_issues.nodes.iter().any(|l| l.number == *n)
                            && self.issues.get(n).is_some_and(|i| {
                                i.state == openwiz_core::fleet::model::IssueState::Closed
                            })
                    })
            })
    }
    fn agent_work(&self, specs: &[Number], deadline: Instant) -> usize {
        let tickets = specs
            .iter()
            .flat_map(|s| self.issues[s].sub_issues.nodes.iter().map(|l| l.number))
            .collect::<BTreeSet<_>>();
        let mut work = 0_usize;
        for ticket in &tickets {
            if self.unread_comments.contains(ticket) {
                continue;
            }
            let mut builders = BTreeSet::new();
            for r in self
                .starts
                .iter()
                .filter(|r| r.key().role() == starts::Role::Builder && r.key().number() == *ticket)
            {
                for a in r.attempts() {
                    if let AttemptOutcome::Created { thread_id } = &a.outcome
                        && starts::safe_id(thread_id)
                    {
                        builders.insert(thread_id.as_str());
                    }
                }
            }
            if let Some(cs) = self.comments.get(ticket) {
                for id in records::lines(cs)
                    .filter_map(|l| l.strip_prefix("launch-fleet: started, thread "))
                {
                    if starts::safe_id(id) {
                        builders.insert(id);
                    }
                }
            }
            work = work.saturating_add(builders.len());
        }
        for p in &self.prs {
            let (pr, related) = match p {
                PrRow::Open(p) | PrRow::Merged { facts: p, .. } => (
                    p.number,
                    p.closes.iter().any(|l| tickets.contains(&l.number)),
                ),
                PrRow::Closed { number } => (
                    *number,
                    self.closed_prs.get(number).is_some_and(|refs| {
                        refs.targets
                            .as_ref()
                            .is_ok_and(|ns| ns.iter().any(|n| tickets.contains(n)))
                    }),
                ),
            };
            if related
                && !self.unread_comments.contains(&pr)
                && let Some(cs) = self.comments.get(&pr)
                && let Ok(reviewers) = self.reviewers(None, pr, cs, false, deadline)
            {
                work = work.saturating_add(reviewers.agents.len().saturating_mul(2));
            }
        }
        work
    }
    fn prefetch(
        &mut self,
        gh: &TickReads,
        specs: &[Number],
        budget: PlanningDeadline,
        read_agents: bool,
        comment_pages: usize,
    ) -> Result<()> {
        let mut targets = BTreeSet::new();
        let mut commits = BTreeSet::new();
        let mut open = BTreeMap::new();
        let mut agent_specs = Vec::new();
        for spec in specs {
            if self.unread_comments.contains(spec) {
                continue;
            }
            let Some(comments) = self.comments.get(spec) else {
                continue;
            };
            let Ok(approval) = records::approval(comments, self.legacy_records) else {
                continue;
            };
            agent_specs.push(*spec);
            let row = &self.issues[spec];
            let summary = self.summary_needs_merges(
                row,
                approval.as_ref(),
                records::spec_records(comments).summary_written,
            );
            let mut contracts = false;
            for link in &row.sub_issues.nodes {
                let ticket = &self.issues[&link.number];
                if ticket.state == openwiz_core::fleet::model::IssueState::Open {
                    let prs = self
                        .prs
                        .iter()
                        .filter_map(|p| match p {
                            PrRow::Open(p)
                                if p.closes.iter().any(|l| l.number == ticket.number) =>
                            {
                                Some(p)
                            }
                            _ => None,
                        })
                        .collect::<Vec<_>>();
                    if let [p] = prs.as_slice() {
                        open.insert(p.number, (*p).clone());
                    }
                    targets.extend(ticket.blocked_by.nodes.iter().map(|l| l.number));
                    if !self.prs.iter().any(|p| matches!(p, PrRow::Open(p) if p.closes.iter().any(|l| l.number == ticket.number))) {
                        targets.insert(ticket.number);
                    }
                    contracts |= records::relies(&ticket.body).is_ok_and(|p| !p.is_empty());
                } else if summary {
                    targets.insert(ticket.number);
                }
            }
            if row.state == openwiz_core::fleet::model::IssueState::Open
                && contracts
                && let Some(a) = &approval
            {
                for p in &self.prs {
                    if let PrRow::Merged {
                        facts,
                        merge_commit,
                        merged_at,
                    } = p
                        && facts.base_branch == self.repository.default
                        && merged_at.0
                            >= i64::try_from(a.approved_at).map_err(|_| "approval time overflow")?
                    {
                        commits.insert(merge_commit.clone());
                    }
                }
            }
        }
        for target in targets {
            let matched = self.prs.iter().filter(|p| matches!(p, PrRow::Merged { facts, .. } if facts.closes.iter().any(|l| l.number == target))).collect::<Vec<_>>();
            if let [
                PrRow::Merged {
                    facts,
                    merge_commit,
                    ..
                },
            ] = matched.as_slice()
                && facts.base_branch == self.repository.default
            {
                commits.insert(merge_commit.clone());
            }
        }
        let jobs = commits
            .into_iter()
            .filter(|merge| {
                !self.cache.borrow().contains.contains_key(&(
                    self.repository.name.clone(),
                    merge.clone(),
                    self.base.clone(),
                ))
            })
            .map(Prefetch::Contains)
            .chain(open.into_values().map(Prefetch::Open))
            .collect::<Vec<_>>();
        let work = jobs.len().saturating_add(comment_pages);
        let deadline = budget.with_work(work)?;
        let agent_work = if read_agents {
            self.agent_work(&agent_specs, deadline)
        } else {
            0
        };
        let deadline = budget.with_work(work.saturating_add(agent_work))?;
        self.deadline = deadline;
        for chunk in jobs.chunks(openwiz_core::fleet::tickets::MAX_CONCURRENT_READS) {
            let parallel_jobs = openwiz_core::fleet::tickets::MAX_CONCURRENT_READS / chunk.len();
            let answers = std::thread::scope(|scope| {
                let workers = chunk
                    .iter()
                    .map(|job| {
                        let base = &self.base;
                        scope.spawn(move || match job {
                            Prefetch::Contains(merge) => Prefetched::Contains(
                                merge.clone(),
                                gh.contains(merge, base, deadline),
                            ),
                            Prefetch::Open(p) => Prefetched::Open(
                                p.number,
                                open_reads(gh, p, deadline, parallel_jobs),
                            ),
                        })
                    })
                    .collect::<Vec<_>>();
                workers
                    .into_iter()
                    .map(|worker| worker.join().map_err(|_| "planning worker failed"))
                    .collect::<Result<Vec<_>>>()
            })?;
            for answer in answers {
                match answer {
                    Prefetched::Contains(merge, answer) => {
                        self.cache.borrow_mut().contains.insert(
                            (self.repository.name.clone(), merge, self.base.clone()),
                            answer,
                        );
                    }
                    Prefetched::Open(pr, answer) => {
                        self.pr_reads.insert(pr, answer);
                    }
                }
            }
        }
        Ok(())
    }
    fn fleet(
        &mut self,
        gh: &TickReads,
        room: Option<&CloudRoomSource>,
        spec: Number,
        deadline: Instant,
    ) -> Result<FleetFacts> {
        let row = self.issues[&spec].clone();
        let comments = self.read_comments(gh, spec, deadline)?;
        let approval = records::approval(&comments, self.legacy_records)?;
        let rows = row
            .sub_issues
            .nodes
            .iter()
            .map(|l| &self.issues[&l.number])
            .collect::<Vec<_>>();
        let fingerprint_now = records::fingerprint(&row, &rows);
        let mut spec_records = records::spec_records(&comments);
        let fp = serde_json::to_value(&fingerprint_now).map_err(|_| "fingerprint unavailable")?;
        let current_prefix = format!(
            "launch-fleet: needs approval: changed since revision {} (fingerprint now {})",
            approval.as_ref().map_or(0, |a| a.approval.revision.get()),
            &fp.as_str().ok_or("invalid fingerprint")?[..12]
        );
        if records::has(&comments, &current_prefix) {
            spec_records.approval_notified.push(fingerprint_now.clone());
        }
        let mut changes = vec![];
        let contracts_needed = row.state == openwiz_core::fleet::model::IssueState::Open
            && rows.iter().any(|r| {
                r.state == openwiz_core::fleet::model::IssueState::Open
                    && records::relies(&r.body).is_ok_and(|p| !p.is_empty())
            });
        if contracts_needed && let Some(a) = &approval {
            for pr in &self.prs {
                if let PrRow::Merged {
                    facts,
                    merge_commit,
                    merged_at,
                } = pr
                    && facts.base_branch == self.repository.default
                    && merged_at.0
                        >= i64::try_from(a.approved_at).map_err(|_| "approval time overflow")?
                {
                    let pr = merged(facts, merge_commit, *merged_at);
                    let read_back = self.contains(gh, &pr, deadline)?;
                    let key = (
                        self.repository.name.clone(),
                        facts.number,
                        facts.head_commit.clone(),
                        merge_commit.clone(),
                    );
                    let cached = self.cache.borrow().files.get(&key).cloned();
                    let files = if let Some(files) = cached {
                        files
                    } else {
                        let files = gh.files(facts.number, deadline)?;
                        self.cache.borrow_mut().files.insert(key, files.clone());
                        files
                    };
                    changes.push(ContractChange {
                        merged: MergeInput { pr, read_back },
                        files,
                    });
                }
            }
        }
        let closed_pr_unneeded =
            !self.summary_needs_merges(&row, approval.as_ref(), spec_records.summary_written);
        let mut tickets = vec![];
        for l in &row.sub_issues.nodes {
            let result = self.ticket(gh, room, l.number, closed_pr_unneeded, deadline);
            tickets.push(TicketInput {
                number: l.number,
                facts: result
                    .map(Observed::Complete)
                    .unwrap_or_else(|_| Observed::Unread(vec![Problem::Records])),
            });
        }
        Ok(FleetFacts {
            issue: records::issue(&row),
            approval,
            fingerprint_now,
            tickets,
            changes,
            follow_ups: self
                .issues
                .values()
                .filter(|i| {
                    i.state == openwiz_core::fleet::model::IssueState::Open
                        && row.sub_issues.nodes.iter().any(|t| {
                            i.body
                                .starts_with(&format!("Follow-up of #{} (spec #{spec})", t.number))
                        })
                })
                .map(|i| i.number)
                .collect(),
            records: spec_records,
        })
    }
    fn contains(&self, gh: &TickReads, pr: &MergedPr, deadline: Instant) -> Result<bool> {
        let base = if pr.fields.base_branch == self.repository.default {
            self.base.clone()
        } else {
            gh.branch(pr.fields.base_branch.as_str(), deadline)?
        };
        let key = (
            self.repository.name.clone(),
            pr.merge_commit.clone(),
            base.clone(),
        );
        if let Some(found) = self.cache.borrow().contains.get(&key) {
            return *found;
        }
        let found = gh.contains(&pr.merge_commit, &base, deadline);
        self.cache.borrow_mut().contains.insert(key, found);
        found
    }
    fn merge_for(
        &self,
        issue: Number,
        gh: &TickReads,
        deadline: Instant,
    ) -> Result<Option<MergeInput>> {
        let matching = self.prs.iter().filter(|p| matches!(p,PrRow::Merged {facts,..} if facts.closes.iter().any(|r| r.number == issue))).collect::<Vec<_>>();
        if matching.len() > 1 {
            return Err("multiple merged PRs");
        }
        match matching.first() {
            Some(PrRow::Merged {
                facts,
                merge_commit,
                merged_at,
            }) => {
                let pr = merged(facts, merge_commit, *merged_at);
                let read_back = self.contains(gh, &pr, deadline)?;
                Ok(Some(MergeInput { pr, read_back }))
            }
            _ => Ok(None),
        }
    }
    fn titled_thread(
        &self,
        room: Option<&CloudRoomSource>,
        matches: impl Fn(&str) -> bool,
        branch: Option<&str>,
        deadline: Instant,
    ) -> Result<Option<String>> {
        let Some(room) = room else { return Ok(None) };
        let project = self.project.as_deref().ok_or("thread project unread")?;
        if self.title_rows.borrow().is_none() {
            let rows = room
                .list_sessions(
                    SessionScope {
                        include_hidden: true,
                        include_archived: true,
                    },
                    deadline,
                )
                .map_err(|_| "thread titles unread")
                .and_then(|rows| {
                    if rows.unreadable.is_empty() {
                        Ok(rows.records)
                    } else {
                        Err("thread titles incomplete")
                    }
                });
            *self.title_rows.borrow_mut() = Some(rows);
        }
        let rows = self.title_rows.borrow();
        let rows = rows.as_ref().unwrap().as_ref().map_err(|e| *e)?;
        let mut found = BTreeSet::new();
        let mut seen = BTreeSet::new();
        for row in rows {
            if !seen.insert(&row.id) {
                return Err("duplicate thread identity");
            }
            let Fact::Known(ref p) = row.project_id else {
                return Err("thread project unread");
            };
            if p.0 != project {
                continue;
            }
            let Fact::Known(ref title) = row.title else {
                return Err("thread title unread");
            };
            if !matches(title) {
                continue;
            }
            if !row.problems.is_empty() || !starts::safe_id(&row.id.0) {
                return Err("matching thread incomplete");
            }
            if let Some(branch) = branch
                && !branch_matches(room, &row.id.0, branch, deadline)?
            {
                continue;
            }
            found.insert(row.id.0.clone());
        }
        if found.len() > 1 {
            return Err("multiple threads match a public record");
        }
        Ok(found.into_iter().next())
    }
    fn ticket(
        &mut self,
        gh: &TickReads,
        room: Option<&CloudRoomSource>,
        id: Number,
        closed_pr_unneeded: bool,
        deadline: Instant,
    ) -> Result<TicketFacts> {
        let row = self.issues[&id].clone();
        let comments = self.read_comments(gh, id, deadline)?;
        let mut blockers = vec![];
        for l in row
            .blocked_by
            .nodes
            .iter()
            .filter(|_| row.state == openwiz_core::fleet::model::IssueState::Open)
        {
            blockers.push(BlockerInput {
                number: l.number,
                state: self.issues[&l.number].state,
                merged: self.merge_for(l.number, gh, deadline)?,
            });
        }
        let mut starts = vec![];
        let mut builders = BTreeSet::new();
        for r in self
            .starts
            .iter()
            .filter(|r| r.key().role() == starts::Role::Builder && r.key().number() == id)
        {
            starts.extend(start_facts(r, &comments));
            for a in r.attempts() {
                if let AttemptOutcome::Created { thread_id } = &a.outcome {
                    builders.insert(thread_id.clone());
                }
            }
        }
        for l in records::lines(&comments) {
            if let Some(s) = l.strip_prefix("launch-fleet: started, thread ") {
                if !starts::safe_id(s) {
                    return Err("invalid builder record");
                }
                builders.insert(s.into());
            }
        }
        let checked = records::checked_builder(&comments);
        if checked.is_none()
            && records::lines(&comments).any(|l| l.starts_with("launch-fleet: start checked"))
        {
            return Err("builder checked records malformed or conflicting");
        }
        if let Some((Some(thread), _)) = &checked {
            builders.insert(thread.as_str().to_owned());
        }
        let public_builder = records::has(&comments, "launch-fleet: started")
            || records::lines(&comments)
                .any(|l| l.starts_with("launch-fleet: start checked, branch "));
        if public_builder {
            let prefix = format!("#{id}: ");
            let titled = self.titled_thread(
                room,
                |title| title.starts_with(&prefix),
                checked.as_ref().map(|(_, b)| b.as_str()),
                deadline,
            )?;
            if let Some(thread) = titled {
                builders.insert(thread);
            }
            if builders.is_empty()
                && !(room.is_none() && records::has(&comments, "launch-fleet: archived"))
            {
                return Err("public builder gone or out of reach");
            }
        }
        let replacement = records::fallback_replacement(&comments)?;
        let builder_replaced = replacement.is_some();
        if let Some((old, replacement, branch)) = replacement {
            if checked.as_ref() != Some(&(Some(replacement), branch)) {
                return Err("fallback replacement does not match the checked branch");
            }
            builders.remove(old.as_str());
            starts
                .retain(|s| !matches!(&s.state, StartState::Started { thread } if *thread == old));
        }
        if builders.len() > 1 {
            return Err("more than one builder");
        }
        if public_builder
            && let (Some(room), Some((_, branch)), Some(thread)) =
                (room, checked.as_ref(), builders.iter().next())
            && !branch_matches(room, thread, branch.as_str(), deadline)?
        {
            return Err("builder branch conflicts with checked record");
        }
        let checked = checked.and_then(|(_, branch)| {
            builders
                .iter()
                .next()
                .and_then(NonEmpty::new)
                .map(|thread| (thread, branch))
        });
        let archived = records::has(&comments, "launch-fleet: archived");
        if row.state == openwiz_core::fleet::model::IssueState::Closed && !archived {
            let mut heads = BTreeSet::new();
            let mut other_heads = BTreeSet::new();
            for p in self.prs.iter().filter_map(|p| match p {
                PrRow::Open(p) | PrRow::Merged { facts: p, .. } => Some(p),
                _ => None,
            }) {
                if p.closes.iter().any(|r| r.number == id) {
                    heads.insert(p.head_commit.as_str());
                } else if !p.closes.is_empty() {
                    other_heads.insert(p.head_commit.as_str());
                }
            }
            let unrelated = |head: &str| other_heads.contains(head) && !heads.contains(head);
            for (pr, refs) in &self.closed_prs {
                let candidate = refs.candidates.contains(&id);
                let known = self.unread_comments.contains(pr)
                    || self.starts.iter().any(|r| {
                        r.key().role() == starts::Role::Reviewer
                            && r.key().number() == *pr
                            && (candidate
                                || r.key().commit().is_none_or(|h| !unrelated(h.as_str())))
                    })
                    || self.comments.get(pr).is_some_and(|cs| {
                        records::lines(cs).any(|l| {
                            [
                                "launch-fleet: review started ",
                                "launch-fleet: review told again ",
                                "launch-fleet: review failed ",
                                "launch-fleet: review given up ",
                                "launch-fleet: re-check sent ",
                            ]
                            .iter()
                            .filter_map(|p| l.strip_prefix(p))
                            .any(|s| {
                                candidate
                                    || s.get(..40).is_none_or(|head| {
                                        Commit::parse(head).is_none() || !unrelated(head)
                                    })
                            })
                        })
                    });
                if known {
                    refs.targets.as_ref().map_err(|e| *e)?;
                }
            }
        }
        let builder = builders
            .into_iter()
            .next()
            .map(|id| agent(room, &id, archived, deadline))
            .transpose()?;
        let open = self
            .prs
            .iter()
            .filter_map(|p| match p {
                PrRow::Open(p) if p.closes.iter().any(|r| r.number == id) => Some(p.clone()),
                _ => None,
            })
            .collect::<Vec<_>>();
        let mut reviewers = vec![];
        let ticket_prs = self
            .prs
            .iter()
            .filter_map(|p| match p {
                PrRow::Open(p) | PrRow::Merged { facts: p, .. }
                    if p.closes.iter().any(|r| r.number == id) =>
                {
                    Some(p.number)
                }
                _ => None,
            })
            .chain(self.closed_prs.iter().filter_map(|(pr, refs)| {
                refs.targets
                    .as_ref()
                    .ok()
                    .filter(|ns| ns.contains(&id))
                    .map(|_| *pr)
            }))
            .collect::<Vec<_>>();
        let mut pr_comments = BTreeMap::new();
        let mut retired_rechecks = BTreeMap::new();
        for p in &ticket_prs {
            let c = self.read_comments(gh, *p, deadline)?;
            let resolved = self.reviewers(room, *p, &c, archived, deadline)?;
            reviewers.extend(resolved.agents);
            retired_rechecks.insert(*p, resolved.retired_rechecks);
            pr_comments.insert(*p, c);
        }
        reviewers.sort_by_key(|(started, r)| (*started, r.agent.thread.clone()));
        let reviewers = reviewers.into_iter().map(|(_, r)| r).collect();
        let pr = match open.as_slice() {
            _ if closed_pr_unneeded
                && row.state == openwiz_core::fleet::model::IssueState::Closed =>
            {
                None
            }
            [] => self.merge_for(id, gh, deadline)?.map(PrInput::Merged),
            [p] => {
                let reads = self
                    .pr_reads
                    .get(&p.number)
                    .cloned()
                    .unwrap_or_else(|| open_reads(gh, p, deadline, 1))?;
                let c = &pr_comments[&p.number];
                let ps = self
                    .starts
                    .iter()
                    .filter(|r| {
                        r.key().role() == starts::Role::Reviewer && r.key().number() == p.number
                    })
                    .flat_map(|r| start_facts(r, c))
                    .collect();
                Some(PrInput::Open(Box::new(OpenPr {
                    fields: fields(p),
                    subject: reads.subject,
                    ci: reads.ci,
                    base_now: Some(reads.base_now),
                    reports: c
                        .iter()
                        .filter(|c| records::first(c).starts_with("VERDICT:"))
                        .map(Comment::report)
                        .collect(),
                    starts: ps,
                    records: records::pr_records(c, &retired_rechecks[&p.number]),
                })))
            }
            many => Some(PrInput::Several(many.iter().map(|p| p.number).collect())),
        };
        let events = if row.labels.iter().any(|l| l.as_str() == "held") {
            gh.events(id, deadline)?
        } else {
            vec![]
        };
        let merges = self
            .prs
            .iter()
            .filter_map(|p| match p {
                PrRow::Merged {
                    facts,
                    merge_commit,
                    ..
                } => Some((facts.number, merge_commit.clone())),
                _ => None,
            })
            .collect();
        let (holds, held_label_comment) = records::holds(&comments, &events, &merges)?;
        let question = comments
            .iter()
            .rev()
            .find(|c| !records::first(c).starts_with("launch-fleet:"))
            .map(|c| c.id);
        let builder_source = checked.as_ref().filter(|_| !builder_replaced).and_then(|(thread, branch)| {
            let room = room?;
            if builder.as_ref()?.thread != *thread {
                return None;
            }
            if let Some(PrInput::Open(p)) = &pr
                && p.fields.head_branch != *branch
            {
                return None;
            }
            let detail = room
                .session_detail(&SessionId(thread.as_str().into()), deadline)
                .ok()?;
            if detail.session.id.0 != thread.as_str() || !detail.session.problems.is_empty() {
                return None;
            }
            let family = match detail.session.provider {
                Fact::Known(ref p) if p == "codex" => BuilderFamily::Gpt,
                Fact::Known(ref p) if p == "claude-code" => BuilderFamily::Claude,
                _ => return None,
            };
            let stopped =
                matches!(detail.session.status, Fact::Known(ref s) if s == "idle" || s == "error");
            let plan_limit = family == BuilderFamily::Claude
                && stopped
                && room
                    .session_output(&SessionId(thread.as_str().into()), deadline)
                    .ok()
                    .filter(|o| o.problems.is_empty())
                    .is_some_and(|o| {
                        [o.output, o.error].iter().any(
                            |f| matches!(f, Fact::Known(Some(text)) if claude_plan_limit(text)),
                        )
                    });
            Some(BuilderSource {
                thread: thread.clone(),
                branch: branch.clone(),
                family,
                plan_limit,
            })
        });
        let mut ticket_records = records::ticket_records(&comments);
        ticket_records.builder_fallback_due = records::fallback_due(&comments);
        Ok(TicketFacts {
            issue: records::issue(&row),
            blockers,
            pr,
            builder,
            builder_source,
            reviewers,
            starts,
            relies_on: records::relies(&row.body)?,
            holds,
            held_label_comment,
            question,
            records: ticket_records,
        })
    }
    fn reviewers(
        &self,
        room: Option<&CloudRoomSource>,
        pr: Number,
        comments: &[Comment],
        archived: bool,
        deadline: Instant,
    ) -> Result<Reviewers> {
        if room.is_none() && archived {
            return Ok(Reviewers {
                agents: vec![],
                retired_rechecks: BTreeSet::new(),
            });
        }
        let mut known: BTreeMap<String, (Commit, u64, u64)> = BTreeMap::new();
        for r in self
            .starts
            .iter()
            .filter(|r| r.key().role() == starts::Role::Reviewer && r.key().number() == pr)
        {
            for a in r.attempts() {
                if let AttemptOutcome::Created { thread_id } = &a.outcome {
                    known.insert(
                        thread_id.clone(),
                        (
                            r.key().commit().ok_or("review without head")?.clone(),
                            a.at.0.try_into().map_err(|_| "invalid start time")?,
                            a.at.0.try_into().map_err(|_| "invalid start time")?,
                        ),
                    );
                }
            }
        }
        let records = records::review_records(comments)?;
        let mut failed = BTreeSet::new();
        let mut span = None;
        let mut closed_spans = BTreeSet::new();
        for (index, r) in records.iter().enumerate() {
            if r.kind == "review started" {
                span = Some(index);
            }
            if matches!(r.kind, "review failed" | "review given up") {
                if let Some(thread) = &r.thread {
                    failed.insert(thread.as_str().to_owned());
                }
                if r.thread.is_none() {
                    let span = span.ok_or("review give-up without a start")?;
                    closed_spans.insert(span);
                }
            }
        }
        let mut current = None;
        let mut span_closed = false;
        let mut retired_rechecks = BTreeSet::new();
        for (index, r) in records.iter().enumerate() {
            if r.kind == "review started" {
                let mut candidates = self
                    .starts
                    .iter()
                    .filter(|s| {
                        s.key().role() == starts::Role::Reviewer
                            && s.key().number() == pr
                            && s.key().commit() == Some(&r.head)
                    })
                    .flat_map(|s| s.attempts())
                    .filter_map(|a| match &a.outcome {
                        AttemptOutcome::Created { thread_id } => Some(thread_id.clone()),
                        _ => None,
                    })
                    .collect::<BTreeSet<_>>();
                if let Some(thread) = &r.thread {
                    candidates.clear();
                    candidates.insert(thread.as_str().to_owned());
                } else {
                    let prefix = format!("Review #{pr} at ");
                    if let Some(thread) = self.titled_thread(
                        room,
                        |title| {
                            title.strip_prefix(&prefix).is_some_and(|short| {
                                !short.is_empty() && r.head.as_str().starts_with(short)
                            })
                        },
                        None,
                        deadline,
                    )? {
                        candidates.insert(thread);
                    }
                }
                if candidates.len() != 1 {
                    return Err("reviewer gone or ambiguous");
                }
                let id = candidates.into_iter().next().unwrap();
                known
                    .entry(id.clone())
                    .or_insert((r.head.clone(), r.updated, r.created));
                current = Some(id.clone());
                span_closed = closed_spans.contains(&index);
                if span_closed {
                    failed.insert(id);
                }
            }
            let id = r
                .thread
                .as_ref()
                .map(|t| t.as_str())
                .or(current.as_deref())
                .ok_or("review activity without a start")?;
            let entry = known.get_mut(id).ok_or("review activity without a start")?;
            if failed.contains(id) || (r.thread.is_none() && span_closed) {
                if r.kind == "re-check sent" {
                    retired_rechecks.insert(r.comment);
                }
                continue;
            }
            entry.0 = r.head.clone();
            entry.1 = r.updated;
        }
        let mut out = vec![];
        for (id, (head, at, first_at)) in known {
            let agent = agent(room, &id, archived, deadline)?;
            let output = if failed.contains(&id) {
                None
            } else if let Some(room) = room {
                let output = room
                    .session_output(&SessionId(id.clone()), deadline)
                    .map_err(|_| "review output unread")?;
                if !output.problems.is_empty() {
                    return Err("review output partial");
                }
                match output.output {
                    Fact::Known(Some(text)) => openwiz_core::fleet::fleets::verdict(&[text])
                        .map_err(|_| "malformed reviewer output")?,
                    Fact::Known(None) => None,
                    _ => return Err("review output unread"),
                }
            } else {
                None
            };
            out.push((
                first_at,
                Reviewer {
                    pr,
                    agent,
                    head,
                    last_activity_at: at,
                    given_up: failed.contains(&id),
                    output,
                },
            ));
        }
        Ok(Reviewers {
            agents: out,
            retired_rechecks,
        })
    }
}
fn branch_matches(
    room: &CloudRoomSource,
    thread: &str,
    branch: &str,
    deadline: Instant,
) -> Result<bool> {
    let thread = NonEmpty::new(thread).ok_or("invalid builder identity")?;
    match cloud::workspace(room, &thread, deadline) {
        openwiz_core::fleet::model::Outcome::Complete { value } => Ok(value.as_str() == branch),
        _ => Err("thread branch unread"),
    }
}

fn links(links: &Links, issues: &BTreeMap<Number, IssueRow>) -> Result<()> {
    if links.total != links.nodes.len() as u64 {
        return Err("incomplete links");
    }
    let mut seen = BTreeSet::new();
    for l in &links.nodes {
        if !seen.insert(l.number) || issues.get(&l.number).is_none_or(|i| i.id != l.id) {
            return Err("duplicate, foreign or missing link");
        }
    }
    Ok(())
}
fn fields(p: &PrFacts) -> PrFields {
    PrFields {
        number: p.number,
        draft: p.draft,
        head_branch: p.head_branch.clone(),
        head_commit: p.head_commit.clone(),
        base_branch: p.base_branch.clone(),
        closes: p.closes.iter().map(|l| l.number).collect(),
    }
}
fn merged(p: &PrFacts, c: &Commit, at: openwiz_core::model::Timestamp) -> MergedPr {
    MergedPr {
        fields: fields(p),
        merge_commit: c.clone(),
        merged_at: at,
    }
}
fn agent(
    room: Option<&CloudRoomSource>,
    id: &str,
    archived: bool,
    deadline: Instant,
) -> Result<Agent> {
    if !starts::safe_id(id) {
        return Err("invalid stored thread");
    }
    let archived = if let Some(room) = room {
        let target = room
            .read_target(&SessionId(id.into()), deadline)
            .map_err(|_| "agent unread")?;
        if target.id.0 != id {
            return Err("wrong agent");
        }
        match target.archived {
            Fact::Known(b) => b,
            _ => return Err("agent archive state unread"),
        }
    } else {
        archived
    };
    Ok(Agent {
        thread: NonEmpty::new(id).unwrap(),
        archived,
    })
}
pub fn start_records(state: &Path, repo: &str) -> Result<Vec<StartRecord>> {
    let Some(store) = StartFileStore::open_read_only(state).map_err(|_| "start store unread")?
    else {
        return Ok(vec![]);
    };
    let mut out = vec![];
    for entry in std::fs::read_dir(store.dir()).map_err(|_| "start inventory unread")? {
        let entry = entry.map_err(|_| "start inventory unread")?;
        let name = entry.file_name();
        let name = name.to_str().ok_or("invalid start filename")?;
        if let Some(id) = name.strip_suffix(".json") {
            let op = OpId::parse(id).map_err(|_| "invalid start filename")?;
            let r = store
                .record(&op)
                .map_err(|_| "start record unread")?
                .ok_or("start disappeared")?;
            if r.key().repository().as_str().eq_ignore_ascii_case(repo) {
                out.push(r)
            }
        }
    }
    out.sort_by_key(|r| (r.attempts()[0].at.0, r.id().as_str().to_owned()));
    Ok(out)
}
fn start_facts(r: &StartRecord, comments: &[Comment]) -> Vec<Start> {
    r.attempts()
        .iter()
        .map(|a| {
            let state = match &a.outcome {
                AttemptOutcome::Pending => StartState::Pending,
                AttemptOutcome::Uncertain { .. } => StartState::Uncertain,
                AttemptOutcome::Created { thread_id } => StartState::Started {
                    thread: NonEmpty::new(thread_id).unwrap(),
                },
                AttemptOutcome::NotCreated { status, .. } => match status {
                    starts::NotCreated::Refused => StartState::Refused {
                        reason: StartReason::Refused,
                    },
                    starts::NotCreated::Failed => StartState::Failed {
                        reason: StartReason::Interrupted,
                    },
                },
            };
            let logged =
                records::lines(comments).any(|l| l.ends_with(&format!("(start {})", a.op_id)));
            Start {
                id: a.op_id.clone(),
                state,
                logged,
            }
        })
        .collect()
}

fn claude_plan_limit(text: &str) -> bool {
    text.lines().any(|line| {
        let line = line.trim();
        line == "Claude usage limit reached"
            || line == "You've hit your limit"
            || line
                .strip_prefix("You've hit your limit · resets ")
                .is_some_and(|s| !s.is_empty())
    })
}

#[cfg(test)]
mod budget_tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn initial_allowance_uses_the_original_deadline() {
        let observed = Instant::now();
        let original = observed - Duration::from_secs(120);
        assert_eq!(
            PlanningDeadline::Initial(original).with_work(5).unwrap(),
            observed - Duration::from_secs(90)
        );
    }
}
