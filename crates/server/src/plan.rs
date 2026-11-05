//! Repository plan projection. The HTTP runner owns slots, guards and deadlines.
use crate::{api, http::Reply};
use openwiz_adapter_github::plan::{self as gh, Answer, Failure, GapKind, Listing, Reader};
use openwiz_core::{
    fleet::{
        fleets::{self, StateFacts},
        model::{self, MergedPr, NonEmpty, Number, PrFields, PullRequest, State, TicketState},
        tickets::{GitHub, Link, PrState},
    },
    limits::RUN_BUDGET,
    model::Fact,
    ops::Clock,
};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::time::Instant;

pub(crate) const ROUTE: &str = "/api/v1/plan";
#[derive(Clone, Debug)]
pub struct Plan {
    reader: Reader,
}
impl Plan {
    pub fn with_program(program: impl Into<PathBuf>) -> Self {
        Self {
            reader: Reader::new(program),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
enum Kind {
    Version,
    SideSpec,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
struct LaneRef {
    kind: Kind,
    number: Number,
}
#[derive(Serialize)]
struct Lane {
    kind: Kind,
    number: Number,
    title: Fact<String>,
}
#[derive(Serialize)]
struct Ticket {
    number: Number,
    title: Fact<String>,
    url: Fact<String>,
    spec: Fact<Option<Number>>,
    lane: Fact<Option<LaneRef>>,
    state: Fact<TicketState>,
    column: Fact<&'static str>,
    labels: Fact<Vec<String>>,
    yours: Fact<bool>,
    blockers: Fact<Vec<Number>>,
    dependents: Fact<Vec<Number>>,
    pr: Fact<Option<PrLink>>,
}
#[derive(Serialize)]
struct PrLink {
    number: Number,
    url: String,
}
#[derive(Serialize)]
struct Chain {
    root: Number,
    blocked_count: usize,
    path: Vec<Number>,
}
struct PrReads {
    pr: Answer<Option<PullRequest>>,
    merged: Answer<bool>,
    checks: Answer<Option<Vec<model::Check>>>,
    review: Answer<Option<Option<model::Review>>>,
    on_base: Answer<Option<bool>>,
}
impl PrReads {
    fn failed(f: Failure) -> Self {
        Self {
            pr: Err(f.clone()),
            merged: Err(f.clone()),
            checks: Err(f.clone()),
            review: Err(f.clone()),
            on_base: Err(f),
        }
    }
    fn complete(&self) -> bool {
        self.pr.is_ok() && self.checks.is_ok() && self.review.is_ok() && self.on_base.is_ok()
    }
}
fn unknown<T>(why: &str) -> Fact<T> {
    Fact::Unknown(why.to_owned())
}
fn fact<T>(a: Answer<T>) -> Fact<T> {
    match a {
        Ok(v) => Fact::Known(v),
        Err(f) => Fact::Unknown(f.detail),
    }
}
fn known<T>(f: &Fact<T>) -> Option<&T> {
    match f {
        Fact::Known(v) => Some(v),
        _ => None,
    }
}
fn has(labels: &[String], s: &str) -> bool {
    labels.iter().any(|l| l == s)
}
fn canonical(repo: &str, kind: &str, link: &Link) -> bool {
    link.url == format!("{repo}/{kind}/{}", link.number)
}

struct Walk<'a> {
    reader: &'a Reader,
    clock: &'a dyn Clock,
    deadline: Instant,
    times: Vec<i64>,
    gaps: Vec<Failure>,
    repo: String,
}
impl Walk<'_> {
    fn at(&mut self) {
        self.times.push(self.clock.now().0);
    }
    fn gap(&mut self, f: Failure) {
        if !self.gaps.contains(&f) {
            self.gaps.push(f)
        }
    }
    fn record<T>(&mut self, a: Answer<T>) -> Answer<T> {
        if let Err(f) = &a {
            self.gap(f.clone());
        }
        a
    }
    fn links(&mut self, list: &Listing<Link>, kind: &str) -> (Vec<Number>, bool) {
        let mut complete = list.gaps.is_empty();
        for f in &list.gaps {
            self.gap(f.clone());
        }
        let mut numbers = BTreeSet::new();
        for l in &list.rows {
            if !canonical(&self.repo, kind, l) || !numbers.insert(l.number) {
                complete = false;
                self.gap(gh::malformed());
            }
        }
        let rows = numbers.into_iter().collect();
        (rows, complete)
    }
    fn status(
        &mut self,
        n: Number,
        issue: &Answer<gh::Issue>,
        prs: &mut BTreeMap<Number, Answer<gh::Pr>>,
    ) -> PrReads {
        let issue = match issue {
            Ok(i) => i,
            Err(f) => return PrReads::failed(f.clone()),
        };
        let (numbers, complete) = self.links(&issue.prs, "pull");
        if !complete {
            return PrReads::failed(gh::malformed());
        }
        let mut open = vec![];
        let mut merged = vec![];
        for number in numbers {
            if let std::collections::btree_map::Entry::Vacant(entry) = prs.entry(number) {
                self.at();
                let answer = self.reader.pr(number, self.deadline);
                let answer = self.record(answer);
                entry.insert(answer);
            }
            let pr = match &prs[&number] {
                Ok(pr) => pr,
                Err(f) => return PrReads::failed(f.clone()),
            };
            let p = &pr.answer;
            if pr.url != format!("{}/pull/{number}", self.repo)
                || p.closes.iter().any(|l| !canonical(&self.repo, "issues", l))
            {
                self.gap(gh::malformed());
                return PrReads::failed(gh::malformed());
            }
            let closes: BTreeSet<_> = p.closes.iter().map(|l| l.number).collect();
            if closes.len() != p.closes.len() || !closes.contains(&n) {
                self.gap(gh::malformed());
                return PrReads::failed(gh::malformed());
            }
            let fields = PrFields {
                number,
                draft: p.draft,
                head_branch: p.head_branch.clone(),
                head_commit: p.head_commit.clone(),
                base_branch: p.base_branch.clone(),
                closes: closes.into_iter().collect(),
            };
            match &p.state {
                PrState::Open => open.push(fields),
                PrState::Closed => {}
                PrState::Merged {
                    merge_commit,
                    merged_at,
                } => merged.push(MergedPr {
                    fields,
                    merge_commit: merge_commit.clone(),
                    merged_at: *merged_at,
                }),
            }
        }
        if merged.len() > 1 {
            let why = gh::failure(
                GapKind::Malformed,
                "more than one merged closing pull request",
            );
            self.gap(why.clone());
            return PrReads::failed(why);
        }
        let pr = match (merged.len(), open.len()) {
            (1, _) => merged.pop().map(PullRequest::Merged),
            (0, 1) => open.pop().map(PullRequest::Open),
            (0, 0) => None,
            _ => Some(PullRequest::Several {
                numbers: open.iter().map(|p| p.number).collect(),
            }),
        };
        let mut checks = Ok(None);
        let mut review = Ok(None);
        let mut on_base = Ok(None);
        match &pr {
            Some(PullRequest::Open(p)) => {
                self.at();
                checks = self.record(
                    self.reader
                        .tickets()
                        .checks(p.number, self.deadline)
                        .map(Some)
                        .map_err(gh::source_failure),
                );
                if let Ok(Some(c)) = &checks {
                    let names: BTreeSet<_> = c.iter().map(|c| &c.name).collect();
                    if names.len() != c.len() {
                        checks = Err(gh::malformed());
                        self.gap(gh::malformed());
                    }
                }
                self.at();
                review = self.record(
                    self.reader
                        .comments(p.number, self.deadline)
                        .and_then(|b| fleets::verdict(&b).map_err(|_| gh::malformed()))
                        .map(Some),
                );
            }
            Some(PullRequest::Merged(p)) => {
                self.at();
                on_base = self.record(
                    self.reader
                        .tickets()
                        .on_base(&p.merge_commit, &p.fields.base_branch, self.deadline)
                        .map(Some)
                        .map_err(gh::source_failure),
                );
            }
            _ => {}
        }
        let is_merged = on_base
            .as_ref()
            .map(|base| fleets::merged(pr.as_ref(), *base))
            .map_err(Clone::clone);
        PrReads {
            pr: Ok(pr),
            merged: is_merged,
            checks,
            review,
            on_base,
        }
    }
}

pub(crate) fn run(config: Option<&Plan>, clock: &dyn Clock) -> Reply {
    let Some(config) = config else {
        return api::error(404, "no_route", "no such route");
    };
    let mut walk = Walk {
        reader: &config.reader,
        clock,
        deadline: clock.monotonic() + RUN_BUDGET,
        times: vec![],
        gaps: vec![],
        repo: String::new(),
    };
    walk.at();
    let repo = walk.record(walk.reader.repository(walk.deadline));
    let mut lanes = BTreeMap::<LaneRef, Fact<String>>::new();
    let mut catalog = BTreeMap::<Number, Answer<gh::Issue>>::new();
    let mut universe = BTreeSet::new();
    let mut enumeration = true;
    if let Ok(repo) = repo {
        walk.repo = repo.url.as_str().to_owned();
        walk.at();
        let milestones = walk.reader.milestones(walk.deadline);
        for f in milestones.gaps {
            walk.gap(f);
            enumeration = false;
        }
        for m in milestones.rows {
            let key = LaneRef {
                kind: Kind::Version,
                number: m.number,
            };
            if lanes.insert(key, fact(walk.record(m.title))).is_some() {
                walk.gap(gh::malformed());
                enumeration = false;
            }
        }
        walk.at();
        let issues = walk.reader.issues(walk.deadline);
        for f in issues.gaps {
            walk.gap(f);
            enumeration = false;
        }
        for i in issues.rows {
            let n = i.number;
            if catalog.insert(n, Ok(i)).is_some() {
                catalog.insert(n, Err(gh::malformed()));
                walk.gap(gh::malformed());
                enumeration = false;
            }
        }
        // A spec is established by native sub-issues, including closed specs.
        // Parent links can preserve membership after a partial child listing.
        let mut specs = BTreeSet::new();
        for (&n, answer) in &catalog {
            if let Ok(i) = answer {
                let (children, full) = walk.links(&i.children, "issues");
                if !full {
                    enumeration = false;
                }
                if i.children.had_items || !children.is_empty() {
                    specs.insert(n);
                }
                universe.extend(children);
                if let Ok(Some(parent)) = &i.parent {
                    if canonical(&walk.repo, "issues", parent) {
                        specs.insert(parent.number);
                        universe.insert(n);
                    } else {
                        walk.gap(gh::malformed());
                        enumeration = false;
                    }
                }
            }
        }
        // Keep side specs even if none of their currently usable rows survived.
        for spec in specs {
            ensure(&mut walk, &mut catalog, spec);
            if let Some(Ok(i)) = catalog.get(&spec) {
                add_lane(&mut walk, &mut lanes, i);
            } else {
                enumeration = false;
            }
        }
        let mut done = BTreeSet::new();
        loop {
            let next = universe.iter().find(|n| !done.contains(*n)).copied();
            let Some(n) = next else { break };
            done.insert(n);
            ensure(&mut walk, &mut catalog, n);
            if let Some(Ok(i)) = catalog.get(&n) {
                let i = i.clone();
                let (blockers, full) = walk.links(&i.blockers, "issues");
                if !full {
                    enumeration = false;
                }
                universe.extend(blockers);
                if let Ok(Some(parent)) = &i.parent
                    && canonical(&walk.repo, "issues", parent)
                {
                    ensure(&mut walk, &mut catalog, parent.number);
                    if let Some(Ok(spec)) = catalog.get(&parent.number) {
                        add_lane(&mut walk, &mut lanes, spec);
                    }
                }
            } else {
                enumeration = false;
            }
        }
    } else {
        enumeration = false;
    }
    for i in catalog.values().filter_map(|i| i.as_ref().ok()) {
        if !i.problems.is_empty() {
            enumeration = false;
            for f in &i.problems {
                walk.gap(f.clone());
            }
        }
    }
    let mut statuses = BTreeMap::new();
    let mut prs = BTreeMap::new();
    for &n in &universe {
        let issue = catalog
            .get(&n)
            .cloned()
            .unwrap_or_else(|| Err(gh::malformed()));
        statuses.insert(n, walk.status(n, &issue, &mut prs));
    }
    let mut tickets = vec![];
    let mut graph = BTreeMap::new();
    let mut graph_complete = enumeration;
    for &n in &universe {
        let status = &statuses[&n];
        let mut blockers = vec![];
        let mut full = false;
        let (title, url, labels, parent, lane, own) = if let Some(Ok(i)) = catalog.get(&n) {
            let title = fact(walk.record(i.title.clone()));
            let url = fact(walk.record(i.url.clone().and_then(|u| {
                if u == format!("{}/issues/{n}", walk.repo) {
                    Ok(u)
                } else {
                    Err(gh::malformed())
                }
            })));
            for f in &i.labels.gaps {
                walk.gap(f.clone());
            }
            let mut label_values = i.labels.rows.clone();
            label_values.sort();
            let unique = label_values.windows(2).all(|w| w[0] != w[1]);
            let label_result = if unique {
                i.labels.complete().map(|_| label_values)
            } else {
                Err(gh::malformed())
            };
            let labels = fact(walk.record(label_result));
            let parent_answer = i.parent.clone().and_then(|p| {
                let declared: BTreeSet<_> = catalog
                    .iter()
                    .filter_map(|(&spec, row)| {
                        row.as_ref()
                            .ok()
                            .filter(|i| {
                                i.children
                                    .rows
                                    .iter()
                                    .any(|l| l.number == n && canonical(&walk.repo, "issues", l))
                            })
                            .map(|_| spec)
                    })
                    .collect();
                if declared.len() > 1
                    || declared
                        .iter()
                        .any(|&n| p.as_ref().is_none_or(|p| p.number != n))
                {
                    return Err(gh::malformed());
                }
                if let Some(p) = &p {
                    if !canonical(&walk.repo, "issues", p) {
                        return Err(gh::malformed());
                    }
                    let spec = catalog
                        .get(&p.number)
                        .and_then(|i| i.as_ref().ok())
                        .ok_or_else(gh::malformed)?;
                    let (children, complete) = walk.links(&spec.children, "issues");
                    if complete && !children.contains(&n) {
                        return Err(gh::malformed());
                    }
                }
                Ok(p)
            });
            let parent = fact(walk.record(parent_answer));
            let lane = match known(&parent) {
                Some(None) => Fact::Known(None),
                Some(Some(p)) => match catalog.get(&p.number) {
                    Some(Ok(spec)) => fact(
                        spec.milestone
                            .clone()
                            .map(|m| Some(lane_key(spec.number, m.as_ref()))),
                    ),
                    _ => unknown("parent spec could not be read"),
                },
                None => unknown("parent spec is unknown"),
            };
            if known(&lane).is_none() {
                walk.gap(gh::malformed());
            }
            (blockers, full) = walk.links(&i.blockers, "issues");
            let milestone = walk.record(i.milestone.clone().and_then(|m| {
                m.map(|m| {
                    m.title.map(|title| model::Milestone {
                        number: m.number,
                        title,
                    })
                })
                .transpose()
            }));
            let own = match (
                &i.state,
                known(&labels),
                known(&title),
                known(&url),
                &milestone,
            ) {
                (Ok(state), Some(labels), Some(title), Some(_), Ok(milestone)) => {
                    Some(model::Issue {
                        title: title.clone(),
                        state: if state == "OPEN" {
                            model::IssueState::Open
                        } else {
                            model::IssueState::Closed
                        },
                        milestone: milestone.clone(),
                        labels: labels.iter().filter_map(NonEmpty::new).collect(),
                        owned_paths: None,
                        relies_on: None,
                        pending_question: None,
                    })
                }
                _ => None,
            };
            if let Err(f) = &i.state {
                walk.gap(f.clone());
            }
            (
                title,
                url,
                labels,
                parent.map(|p| p.map(|p| p.number)),
                lane,
                own,
            )
        } else {
            walk.gap(gh::failure(
                GapKind::NotFound,
                "a referenced plan issue could not be read",
            ));
            (
                unknown("issue unavailable"),
                unknown("issue unavailable"),
                unknown("labels unavailable"),
                unknown("parent unavailable"),
                unknown("parent unavailable"),
                None,
            )
        };
        graph.insert(n, blockers.clone());
        if !full
            || status.merged.is_err()
            || !status.complete()
            || own.is_none()
            || known(&url).is_none()
            || known(&parent).is_none()
        {
            graph_complete = false;
        }
        let merged: Answer<Vec<bool>> = blockers
            .iter()
            .map(|b| {
                statuses
                    .get(b)
                    .ok_or_else(gh::malformed)
                    .and_then(|s| s.merged.clone())
            })
            .collect();
        let state = if let (
            Some(issue),
            Ok(pr),
            Ok(checks),
            Ok(review),
            Ok(on_base),
            Ok(blockers_merged),
        ) = (
            &own,
            &status.pr,
            &status.checks,
            &status.review,
            &status.on_base,
            &merged,
        ) {
            if full && status.complete() {
                match fleets::ticket_state(&StateFacts {
                    issue,
                    pr: pr.as_ref(),
                    checks: checks.as_deref(),
                    review: review.as_ref().map(|r| r.as_ref()),
                    on_base: *on_base,
                    blockers_merged,
                }) {
                    State::Known(s) => Fact::Known(s),
                    State::Unknown(r) => unknown(r.as_str()),
                    State::Unread(_) => unknown("required state reads incomplete"),
                }
            } else {
                unknown("required state reads incomplete")
            }
        } else {
            unknown("required state reads incomplete")
        };
        let column = column(&state, &labels, status, &merged, full);
        let yours = labels.clone().map(|l| has(&l, "ready-for-human"));
        let pr = fact(walk.record(status.pr.clone().and_then(|p| match p {
            Some(PullRequest::Several { .. }) => Err(gh::failure(
                GapKind::Malformed,
                "several closing pull requests; no single PR is established",
            )),
            Some(p) => {
                let number = match p {
                    PullRequest::Open(p) => p.number,
                    PullRequest::Merged(p) => p.fields.number,
                    PullRequest::Several { .. } => unreachable!(),
                };
                Ok(Some(PrLink {
                    number,
                    url: format!("{}/pull/{number}", walk.repo),
                }))
            }
            None => Ok(None),
        })));
        tickets.push(Ticket {
            number: n,
            title,
            url,
            spec: parent,
            lane,
            state,
            column,
            labels,
            yours,
            blockers: if full {
                Fact::Known(blockers)
            } else {
                unknown("prerequisite list incomplete")
            },
            dependents: unknown("dependency graph incomplete"),
            pr,
        });
    }
    // Only complete enumeration and blocker lists establish the full inverse.
    let inverse_complete = enumeration && tickets.iter().all(|t| known(&t.blockers).is_some());
    if inverse_complete {
        for t in &mut tickets {
            t.dependents = Fact::Known(
                graph
                    .iter()
                    .filter_map(|(&n, b)| b.contains(&t.number).then_some(n))
                    .collect(),
            );
        }
    }
    let chain = if graph_complete {
        match critical_chain(&graph, &statuses) {
            Ok(c) => Fact::Known(c),
            Err(f) => {
                walk.gap(f);
                unknown("dependency graph contains a cycle")
            }
        }
    } else {
        unknown("complete prerequisite and merge reads are required")
    };
    let assembled = clock.now().0;
    let time = walk.times.iter().copied().min();
    let freshness=if assembled>=0&&walk.times.iter().all(|&t|t>=0&&t<=assembled) {time.map(|t|serde_json::json!({"state":if assembled-t<=70_000{"fresh"}else{"stale"},"snapshot_at":{"known":t}}))}else{None}.unwrap_or_else(||serde_json::json!({"state":"unknown","snapshot_at":{"unknown":"source clock relationship is unknown"}}));
    let lanes: Vec<_> = lanes
        .into_iter()
        .map(|(k, title)| Lane {
            kind: k.kind,
            number: k.number,
            title,
        })
        .collect();
    let value = serde_json::json!({"schema":"openwiz.plan.v1","snapshot_at":assembled.max(0),"coverage":{"state":if walk.gaps.is_empty(){"complete"}else{"partial"},"gaps":walk.gaps},"freshness":freshness,"lanes":lanes,"tickets":tickets,"critical_chain":chain});
    api::pretty(&value).map_or_else(
        || api::error(500, "internal", "the result could not be written"),
        api::ok,
    )
}
fn ensure(w: &mut Walk<'_>, catalog: &mut BTreeMap<Number, Answer<gh::Issue>>, n: Number) {
    if let std::collections::btree_map::Entry::Vacant(entry) = catalog.entry(n) {
        w.at();
        let a = w.reader.issue(n, w.deadline);
        let a = w.record(a);
        entry.insert(a);
    }
}
fn lane_key(spec: Number, m: Option<&gh::Milestone>) -> LaneRef {
    match m {
        Some(m) => LaneRef {
            kind: Kind::Version,
            number: m.number,
        },
        None => LaneRef {
            kind: Kind::SideSpec,
            number: spec,
        },
    }
}
fn add_lane(w: &mut Walk<'_>, lanes: &mut BTreeMap<LaneRef, Fact<String>>, i: &gh::Issue) {
    match &i.milestone {
        Ok(m) => {
            let key = lane_key(i.number, m.as_ref());
            let title = match m {
                Some(m) => fact(w.record(m.title.clone())),
                None => fact(w.record(i.title.clone())),
            };
            if let Some(old) = lanes.get(&key) {
                if let (Some(a), Some(b)) = (known(old), known(&title))
                    && a != b
                {
                    w.gap(gh::malformed());
                    lanes.insert(key, unknown("lane title readings disagree"));
                }
            } else {
                lanes.insert(key, title);
            }
        }
        Err(f) => w.gap(f.clone()),
    }
}
fn column(
    state: &Fact<TicketState>,
    labels: &Fact<Vec<String>>,
    s: &PrReads,
    blockers: &Answer<Vec<bool>>,
    full: bool,
) -> Fact<&'static str> {
    if matches!(state, Fact::Known(TicketState::Merged)) {
        return Fact::Known("done");
    }
    if s.merged != Ok(false) {
        return unknown("merge status is unknown");
    }
    let Some(labels) = known(labels) else {
        return unknown("labels are unknown");
    };
    if has(labels, "held") || has(labels, "needs-info") {
        return Fact::Known("needs_you");
    }
    if matches!(
        state,
        Fact::Known(TicketState::Building | TicketState::InReview | TicketState::ChangesRequested)
    ) {
        return Fact::Known("building");
    }
    if matches!(s.pr, Ok(None))
        && has(labels, "ready-for-human")
        && full
        && s.complete()
        && blockers.as_ref().is_ok_and(|b| b.iter().all(|b| *b))
    {
        return Fact::Known("needs_you");
    }
    if matches!(
        state,
        Fact::Known(TicketState::Ready | TicketState::Blocked)
    ) {
        return Fact::Known("waiting");
    }
    unknown("state does not establish a column")
}
fn critical_chain(
    graph: &BTreeMap<Number, Vec<Number>>,
    statuses: &BTreeMap<Number, PrReads>,
) -> Answer<Option<Chain>> {
    let mut indegree: BTreeMap<_, _> = graph.iter().map(|(&n, b)| (n, b.len())).collect();
    let mut onward: BTreeMap<Number, Vec<Number>> = graph.keys().map(|&n| (n, vec![])).collect();
    for (&n, blockers) in graph {
        for b in blockers {
            onward.get_mut(b).ok_or_else(gh::malformed)?.push(n);
        }
    }
    let mut roots: BTreeSet<_> = indegree
        .iter()
        .filter_map(|(&n, &d)| (d == 0).then_some(n))
        .collect();
    let mut order = vec![];
    while let Some(n) = roots.pop_first() {
        order.push(n);
        for child in &onward[&n] {
            let d = indegree.get_mut(child).ok_or_else(gh::malformed)?;
            *d -= 1;
            if *d == 0 {
                roots.insert(*child);
            }
        }
    }
    if order.len() != graph.len() {
        return Err(gh::failure(
            GapKind::Malformed,
            "the plan dependency graph contains a cycle",
        ));
    }
    let unfinished: BTreeSet<_> = statuses
        .iter()
        .filter_map(|(&n, s)| (s.merged == Ok(false)).then_some(n))
        .collect();
    let mut longest = BTreeMap::<Number, Vec<Number>>::new();
    for &n in order.iter().rev().filter(|n| unfinished.contains(n)) {
        let best = onward[&n]
            .iter()
            .filter_map(|c| longest.get(c))
            .min_by(|a, b| b.len().cmp(&a.len()).then_with(|| a.cmp(b)));
        let mut path = vec![n];
        if let Some(best) = best {
            path.extend(best);
        }
        longest.insert(n, path);
    }
    let mut best: Option<Chain> = None;
    for &n in &unfinished {
        if graph[&n].iter().any(|b| unfinished.contains(b)) {
            continue;
        }
        let mut reach = BTreeSet::new();
        let mut stack = vec![n];
        while let Some(p) = stack.pop() {
            for &child in &onward[&p] {
                if unfinished.contains(&child) && reach.insert(child) {
                    stack.push(child);
                }
            }
        }
        let candidate = Chain {
            root: n,
            blocked_count: reach.len(),
            path: longest[&n].clone(),
        };
        if best.as_ref().is_none_or(|b| {
            candidate.blocked_count > b.blocked_count
                || (candidate.blocked_count == b.blocked_count
                    && (candidate.path.len() > b.path.len()
                        || (candidate.path.len() == b.path.len() && candidate.root < b.root)))
        }) {
            best = Some(candidate);
        }
    }
    Ok(best)
}
