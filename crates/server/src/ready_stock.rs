//! Read-only stock assembly from existing bounded readers. Fixture proofs do not
//! establish live coverage or change notification/work authority.
use openwiz_core::notifications::{
    model::*,
    stock::{self, ProjectFacts},
};
use serde_json::Value;
use std::time::Instant;

/// Supplies original source facts, never assembled counts or notification state.
/// Implementations must obey the caller's deadline and report incomplete reads.
pub trait StockSource: Send + Sync {
    fn read(&self, projects: &[Id], deadline: Instant) -> Vec<ProjectFacts>;
}
fn coverage() -> Coverage {
    Coverage {
        state: CoverageState::Complete,
        gaps: vec![],
    }
}
fn unknown_project(id: Id, why: &str) -> ProjectFacts {
    let mut cov = coverage();
    stock::gap(&mut cov, why);
    ProjectFacts {
        project: id,
        coverage: cov,
        snapshot_at: stock::unknown(why),
        tickets: stock::unknown(why),
        last_good: None,
    }
}
fn time(part: &Value) -> Fact<u64> {
    part["freshness"]["snapshot_at"]["known"]
        .as_u64()
        .map_or_else(
            || stock::unknown("Project enumeration time is unknown"),
            Fact::Known,
        )
}
/// Retain one bounded provider read before capturing the final assembly time.
pub(crate) struct StockRead {
    ids: Vec<Id>,
    supplied: Vec<ProjectFacts>,
    coverage: Coverage,
}
pub(crate) fn read(
    projects: &Value,
    injected: Option<&dyn StockSource>,
    deadline: Instant,
) -> Option<StockRead> {
    let mut cov = coverage();
    if projects["coverage"]["state"] != "complete" {
        stock::gap(&mut cov, "Configured project enumeration is incomplete");
    }
    // The optional stock contract has a narrower identity domain than cockpit.
    // Refuse this whole extension if any identity cannot be represented. The
    // original cockpit/project list remains intact and the client shows unknowns.
    let ids: Option<Vec<Id>> = projects["items"]
        .as_array()?
        .iter()
        .map(|p| p["id"].as_str().and_then(Id::new))
        .collect();
    let ids = ids?;
    let supplied = if Instant::now() < deadline {
        injected.map(|s| s.read(&ids, deadline)).unwrap_or_default()
    } else {
        vec![]
    };
    if Instant::now() >= deadline {
        stock::gap(&mut cov, "Stock source deadline was exhausted");
    }
    Some(StockRead {
        ids,
        supplied,
        coverage: cov,
    })
}
/// In-memory source history only: no disk state, work effect or timestamp renewal.
#[derive(Default)]
pub(crate) struct History {
    samples: std::sync::Mutex<BTreeMap<Id, StockSample>>,
    project_names: std::sync::Mutex<BTreeMap<String, Value>>,
}
pub(crate) const MISSING_PROJECT: &str = "Project not confirmed by current discovery";
impl History {
    /// Remember identities even without a good stock sample. Incomplete, stale
    /// or unread discovery cannot establish that an earlier project was removed.
    /// Called after the final source read so slow reads cannot hide discovery age.
    pub(crate) fn retained_projects(&self, projects: &Value, now: u64) -> Vec<(String, Value)> {
        let rows = projects["items"].as_array().expect("cockpit project items");
        let observed: BTreeSet<_> = rows
            .iter()
            .map(|p| p["id"].as_str().expect("cockpit project id"))
            .collect();
        let complete = projects["coverage"]["state"] == "complete"
            && stock::freshness(time(projects), now).state == FreshnessState::Fresh;
        let mut names = self.project_names.lock().unwrap_or_else(|p| p.into_inner());
        if complete {
            names.retain(|id, _| observed.contains(id.as_str()));
        }
        for row in rows {
            names.insert(row["id"].as_str().unwrap().to_owned(), row["name"].clone());
        }
        let retained = names
            .iter()
            .filter(|(id, _)| !observed.contains(id.as_str()))
            .map(|(id, name)| (id.clone(), name.clone()))
            .collect();
        if complete {
            self.samples
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .retain(|id, _| observed.contains(id.as_str()));
        }
        retained
    }
}
pub(crate) fn assemble(
    projects: &Value,
    read: StockRead,
    now: u64,
    history: &History,
) -> Option<Stock> {
    let StockRead {
        ids: observed,
        supplied,
        coverage: mut cov,
    } = read;
    // Retained identities may include opaque cockpit IDs. Preserve the whole
    // cockpit and omit the optional extension when that domain cannot fit it.
    let ids: Option<Vec<Id>> = projects["items"]
        .as_array()?
        .iter()
        .map(|p| p["id"].as_str().and_then(Id::new))
        .collect();
    let ids = ids?;
    if projects["coverage"]["state"] != "complete" {
        stock::gap(&mut cov, "Configured project enumeration is incomplete");
    }
    if supplied.iter().any(|p| !observed.contains(&p.project)) {
        stock::gap(&mut cov, "Stock source returned an unconfigured project");
    }
    let mut rows = vec![];
    for id in ids {
        let mut matches = supplied.iter().filter(|p| p.project == id);
        let input = if !observed.contains(&id) {
            unknown_project(id, MISSING_PROJECT)
        } else {
            match (matches.next(), matches.next()) {
                (Some(p), None) => p.clone(),
                (Some(_), Some(_)) => {
                    unknown_project(id, "Stock source returned repeated project facts")
                }
                _ => unknown_project(
                    id,
                    "No stock source facts were read for this configured project",
                ),
            }
        };
        rows.push(stock::project(input, now));
    }
    // Validate/deduplicate the current projection before accepting history.
    let mut result = stock::factory(rows, cov, time(projects), now);
    let mut saved = history.samples.lock().unwrap_or_else(|p| p.into_inner());
    for row in &mut result.projects {
        if row.coverage.state == CoverageState::Complete
            && row.freshness.state == FreshnessState::Fresh
            && let (Fact::Known(counts), Fact::Known(at)) =
                (&row.counts, &row.freshness.snapshot_at)
            && counts.unknown == 0
        {
            let sample = StockSample {
                snapshot_at: *at,
                counts: counts.clone(),
            };
            if saved
                .get(&row.project)
                .is_none_or(|old| old.snapshot_at <= *at)
            {
                saved.insert(row.project.clone(), sample);
            }
        }
        if row.last_good.is_none() {
            row.last_good = saved
                .get(&row.project)
                .filter(|sample| sample.snapshot_at <= now)
                .cloned();
        }
    }
    Some(result)
}

use crate::fleets::StockReads;
use openwiz_core::fleet::{
    fleets::{FleetsSource, IssueRow, Links, Listed, MAX_CLOSING_REFERENCES, PrRow, StockPr},
    model::{IssueState, MergedPr, Number, PrFields},
    tickets::{GitHub, IssueAnswer},
};
use openwiz_core::model::Fact as SourceFact;
use openwiz_core::ops::Clock;
use std::collections::{BTreeMap, BTreeSet};

/// The normal installed source path. A repository is assigned only to the one
/// project verified by the existing mapping read. Other projects stay unknown.
pub(crate) struct Installed<'a> {
    pub reads: &'a StockReads<'a>,
    pub github: &'a dyn GitHub,
    pub project: Option<&'a str>,
    pub repository: Option<&'a str>,
    pub clock: &'a dyn Clock,
}
fn approved(row: &IssueRow) -> bool {
    row.labels.iter().any(|l| {
        matches!(
            l.as_str(),
            "ready-for-agent" | "ready-for-human" | "held" | "needs-info"
        )
    })
}
fn complete_links(links: &Links, rows: &BTreeMap<Number, &IssueRow>) -> bool {
    let mut seen = BTreeSet::new();
    links.total == links.nodes.len() as u64
        && links
            .nodes
            .iter()
            .all(|l| seen.insert(l.number) && rows.get(&l.number).is_some_and(|r| r.id == l.id))
}
fn same_issue(answer: &IssueAnswer, row: &IssueRow) -> bool {
    let labels = |ls: &[openwiz_core::fleet::model::NonEmpty]| {
        ls.iter()
            .map(|l| l.as_str().to_owned())
            .collect::<BTreeSet<_>>()
    };
    let blockers: BTreeSet<_> = row.blocked_by.nodes.iter().map(|l| l.number).collect();
    let read: BTreeSet<_> = answer.blocked_by.nodes.iter().map(|l| l.number).collect();
    answer.issue.state == row.state
        && labels(&answer.issue.labels) == labels(&row.labels)
        && answer.blocked_by.total == answer.blocked_by.nodes.len() as u64
        && read.len() == answer.blocked_by.nodes.len()
        && read == blockers
}
fn title_match(number: Number, prs: &Listed<StockPr>) -> Fact<bool> {
    let prefix = format!("#{number}");
    let mut unread = prs.cut_short;
    for p in &prs.rows {
        if matches!(p.pr, PrRow::Open(_)) {
            match &p.title {
                SourceFact::Known(title) => {
                    if let Some(suffix) = title.as_str().strip_prefix(&prefix) {
                        match suffix.chars().next() {
                            Some(c) if c.is_ascii_digit() => {}
                            // The reference measure recognizes Unicode decimal
                            // digits. std's broader numeric category cannot
                            // establish that boundary: retain uncertainty rather
                            // than claiming a match or a negative builder fact.
                            Some(c) if c.is_numeric() => unread = true,
                            _ => return Fact::Known(true),
                        }
                    }
                }
                SourceFact::Unknown(_) => unread = true,
            }
        }
    }
    if unread {
        stock::unknown("Open PR-title evidence is incomplete or unrecognized")
    } else {
        Fact::Known(false)
    }
}
fn merged(
    row: &IssueRow,
    rows: &BTreeMap<Number, &IssueRow>,
    prs: &Listed<StockPr>,
    reads: &StockReads<'_>,
    deadline: Instant,
) -> Fact<bool> {
    if row.state == IssueState::Open {
        return Fact::Known(false);
    }
    if prs.cut_short
        || prs.rows.iter().any(|p| match &p.pr {
            PrRow::Open(f) | PrRow::Merged { facts: f, .. } => {
                f.closes.len() >= MAX_CLOSING_REFERENCES
            }
            _ => false,
        })
    {
        return stock::unknown("Closed-ticket PR discovery is incomplete");
    }
    let matches: Vec<_> = prs
        .rows
        .iter()
        .filter_map(|p| match &p.pr {
            PrRow::Merged {
                facts,
                merge_commit,
                merged_at,
            } if facts
                .closes
                .iter()
                .any(|l| l.number == row.number && l.id == row.id) =>
            {
                Some((facts, merge_commit, merged_at))
            }
            _ => None,
        })
        .collect();
    let [(facts, commit, at)] = matches.as_slice() else {
        return stock::unknown("Closed ticket has no unique verified merge");
    };
    let mut seen = BTreeSet::new();
    if !facts
        .closes
        .iter()
        .all(|l| seen.insert(l.number) && rows.get(&l.number).is_some_and(|r| r.id == l.id))
    {
        return stock::unknown("Closing-reference identity is incomplete or ambiguous");
    }
    let pr = MergedPr {
        fields: PrFields {
            number: facts.number,
            draft: facts.draft,
            head_branch: facts.head_branch.clone(),
            head_commit: facts.head_commit.clone(),
            base_branch: facts.base_branch.clone(),
            closes: facts.closes.iter().map(|l| l.number).collect(),
        },
        merge_commit: (*commit).clone(),
        merged_at: **at,
    };
    if Instant::now() >= deadline {
        return stock::unknown("Merge read deadline was exhausted");
    }
    match reads.on_base(&pr, deadline) {
        Ok(true) => Fact::Known(true),
        _ => stock::unknown("Closed ticket's merge is not verified on its base"),
    }
}
impl Installed<'_> {
    fn facts(&self, id: Id, deadline: Instant) -> ProjectFacts {
        if self.project != Some(id.as_str()) {
            return unknown_project(
                id,
                "No unique configured repository mapping for this project",
            );
        }
        let Some((repository_at, Ok(repository))) = self.reads.repository_read() else {
            return unknown_project(id, "Repository identity could not be read");
        };
        if self.repository != Some(repository.name.as_str()) {
            return unknown_project(id, "Repository readers disagree about project identity");
        }
        // The fleet list may have no spec children and hence no PR discovery.
        // Use the same approved list form once; the wrapper reuses any prior read.
        if Instant::now() < deadline {
            let _ = self.reads.stock_pull_requests(deadline);
        }
        let (issues, prs) = self.reads.captured();
        let (Some((issue_at, Ok(issues))), Some((pr_at, Ok(prs)))) = (issues, prs) else {
            return unknown_project(id, "Required repository enumeration could not be read");
        };
        let mut input = ProjectFacts {
            project: id,
            coverage: coverage(),
            snapshot_at: if [repository_at, issue_at, pr_at]
                .iter()
                .all(|at| *at >= 0 && *at <= self.clock.now().0)
            {
                Fact::Known(repository_at.min(issue_at).min(pr_at) as u64)
            } else {
                stock::unknown("Repository source time is unknown or in the future")
            },
            tickets: stock::unknown("Repository ticket universe is incomplete"),
            last_good: None,
        };
        if prs.cut_short {
            stock::gap(&mut input.coverage, "PR enumeration is incomplete");
        }
        let rows: BTreeMap<_, _> = issues.rows.iter().map(|r| (r.number, r)).collect();
        let ids: BTreeSet<_> = issues.rows.iter().map(|r| r.id.as_str()).collect();
        if issues.cut_short
            || rows.len() != issues.rows.len()
            || ids.len() != issues.rows.len()
            || rows.values().any(|r| {
                !complete_links(&r.sub_issues, &rows)
                    || (r.state == IssueState::Open && !complete_links(&r.blocked_by, &rows))
            })
        {
            stock::gap(
                &mut input.coverage,
                "Native ticket enumeration is incomplete or ambiguous",
            );
            return input;
        }
        // The full approved-label universe is independent of membership in a
        // spec. Count only open work; closed prerequisites remain source evidence
        // for each open ticket's blocker classification, never extra stock rows.
        let mut universe: BTreeSet<_> = rows
            .values()
            .filter(|r| r.state == IssueState::Open && approved(r))
            .map(|r| r.number)
            .collect();
        for row in rows.values() {
            universe.extend(
                row.sub_issues
                    .nodes
                    .iter()
                    .map(|l| l.number)
                    .filter(|n| rows[n].state == IssueState::Open),
            );
        }
        loop {
            let next: Vec<_> = universe
                .iter()
                .flat_map(|n| rows[n].blocked_by.nodes.iter().map(|l| l.number))
                .filter(|n| rows[n].state == IssueState::Open && !universe.contains(n))
                .collect();
            if next.is_empty() {
                break;
            }
            universe.extend(next);
        }
        let mut pr_ids = BTreeSet::new();
        if prs.rows.iter().any(|p| {
            !pr_ids.insert(match &p.pr {
                PrRow::Open(f) | PrRow::Merged { facts: f, .. } => f.number,
                PrRow::Closed { number } => *number,
            })
        }) {
            stock::gap(&mut input.coverage, "PR identities are repeated");
            return input;
        }
        let mut merge_cache = BTreeMap::new();
        let mut tickets = vec![];
        for number in universe {
            let row = rows[&number];
            let title = title_match(number, &prs);
            let start =
                if row.state == IssueState::Open && approved(row) && title != Fact::Known(true) {
                    if Instant::now() >= deadline {
                        stock::unknown("Recorded-start read deadline was exhausted")
                    } else {
                        match self.github.stock_issue(number, deadline) {
                            Ok((answer, SourceFact::Known(v))) if same_issue(&answer, row) => {
                                Fact::Known(v)
                            }
                            _ => stock::unknown("Recorded-start evidence is unread or changed"),
                        }
                    }
                } else {
                    stock::unknown("Recorded-start read is not required for this classification")
                };
            let mut blockers = Fact::Known(true);
            for link in &row.blocked_by.nodes {
                let read = merge_cache.entry(link.number).or_insert_with(|| {
                    merged(rows[&link.number], &rows, &prs, self.reads, deadline)
                });
                match read {
                    Fact::Known(false) => {
                        blockers = Fact::Known(false);
                        break;
                    }
                    Fact::Unknown(_) => {
                        blockers = stock::unknown("A native blocker has no verified merge")
                    }
                    _ => {}
                }
            }
            let own_merge = merge_cache
                .entry(number)
                .or_insert_with(|| merged(row, &rows, &prs, self.reads, deadline))
                .clone();
            tickets.push(stock::TicketFacts {
                number: number.get(),
                open: Fact::Known(row.state == IssueState::Open),
                merged: own_merge,
                labels: Fact::Known(row.labels.iter().map(|l| l.as_str().to_owned()).collect()),
                start_recorded: start,
                matching_open_pr: title,
                blockers_merged: blockers,
                capacity_refused: None,
            });
        }
        input.tickets = Fact::Known(tickets);
        input
    }
}
impl StockSource for Installed<'_> {
    fn read(&self, projects: &[Id], deadline: Instant) -> Vec<ProjectFacts> {
        projects
            .iter()
            .cloned()
            .map(|id| self.facts(id, deadline))
            .collect()
    }
}
