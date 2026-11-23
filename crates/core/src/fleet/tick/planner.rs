use super::super::model::{CheckResult, IssueState, NonEmpty, Number, Review, Verdict};
use super::rules::{branch_matches, unique};
use super::*;
use std::collections::BTreeSet;

pub fn plan(snapshot: &Snapshot, rules: &Rules, planned_at: u64) -> Result<Plan, PlanError> {
    let Observed::Complete(default) = &snapshot.default_branch else {
        return Err(PlanError::RepositoryUnread);
    };
    if !valid_branch(default.as_str()) {
        return Err(PlanError::InvalidSnapshot);
    }
    let Observed::Complete(fleets) = &snapshot.fleets else {
        return Err(PlanError::SpecsUnread);
    };
    let mut ids = BTreeSet::new();
    for f in fleets {
        if !ids.insert(f.spec) {
            return Err(PlanError::InvalidSnapshot);
        }
    }
    let mut tickets = BTreeSet::new();
    for f in fleets {
        if let Observed::Complete(f) = &f.facts {
            for t in &f.tickets {
                if !tickets.insert(t.number) || ids.contains(&t.number) {
                    return Err(PlanError::InvalidSnapshot);
                }
            }
        }
    }
    let mut out = Plan {
        schema: Schema::V1,
        mode: Mode::DryRun,
        planned_at,
        default_branch: default.clone(),
        rules: rules.clone(),
        actions: vec![],
    };
    if default.as_str().starts_with("release-") {
        return Ok(out);
    }
    for f in fleets {
        fleet(&mut out, f);
    }
    out.actions.sort_by_key(|a| {
        (
            a.spec,
            a.ticket.is_none(),
            a.ticket,
            a.kind,
            a.detail.order(),
        )
    });
    Ok(out)
}

fn valid_branch(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 255
        && !s.starts_with('-')
        && s.bytes().all(|b| b.is_ascii_graphic())
}
fn emit(out: &mut Plan, spec: Number, ticket: Option<Number>, detail: Detail) {
    out.actions.push(Action {
        kind: detail.kind(),
        spec,
        ticket,
        detail,
        outcome: Planned {
            state: PlannedState::Planned,
        },
    });
}
fn look(
    out: &mut Plan,
    spec: Number,
    ticket: Option<Number>,
    reasons: Vec<String>,
    recorded: &[String],
) {
    let reason = reasons
        .into_iter()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>()
        .join("; ");
    if !recorded.contains(&reason) {
        emit(out, spec, ticket, Detail::Look { reason });
    }
}
fn unread(problems: &[Problem]) -> Vec<String> {
    if problems.is_empty() {
        vec!["required facts unread".into()]
    } else {
        problems.iter().map(|p| p.reason().into()).collect()
    }
}
fn fleet(out: &mut Plan, input: &FleetInput) {
    let spec = input.spec;
    let Observed::Complete(f) = &input.facts else {
        if let Observed::Unread(p) = &input.facts {
            look(out, spec, None, unread(p), &[]);
        }
        return;
    };
    if !unique(
        &f.changes
            .iter()
            .map(|c| c.merged.pr.fields.number)
            .collect::<Vec<_>>(),
    ) {
        look(
            out,
            spec,
            None,
            vec!["duplicate contract merge".into()],
            &f.records.looked,
        );
        return;
    }
    let approved = f.approval.as_ref();
    if approved.is_some_and(|a| {
        a.rows
            .keys()
            .any(|n| !f.tickets.iter().any(|t| t.number == *n))
    }) {
        look(
            out,
            spec,
            None,
            vec!["approved ticket missing from graph".into()],
            &f.records.looked,
        );
        return;
    }
    let current = approved.is_some_and(|a| a.approval.fingerprint == f.fingerprint_now);
    let start = out.actions.len();
    let mut stale_ready = false;
    for t in &f.tickets {
        stale_ready |= ticket(out, spec, f, t, current);
    }
    if f.issue.state == IssueState::Closed {
        return;
    }
    if stale_ready
        && let Some(a) = approved
        && !current
        && !f.records.approval_notified.contains(&f.fingerprint_now)
    {
        emit(
            out,
            spec,
            None,
            Detail::ReApprove {
                approval: a.approval.clone(),
                fingerprint_now: f.fingerprint_now.clone(),
            },
        );
    }
    let Some(approval) = approved else { return };
    if approval.rows.is_empty() {
        return;
    }
    let complete = f
        .tickets
        .iter()
        .all(|t| matches!(t.facts, Observed::Complete(_)));
    if !complete {
        return;
    }
    let closed = |t: &TicketInput| matches!(&t.facts,Observed::Complete(t) if t.issue.state==IssueState::Closed);
    let planned_closed = f
        .tickets
        .iter()
        .filter(|t| approval.rows.contains_key(&t.number))
        .all(closed);
    let mut follow_ups = f.follow_ups.clone();
    follow_ups.extend(
        f.tickets
            .iter()
            .filter(|t| !approval.rows.contains_key(&t.number) && !closed(t))
            .map(|t| t.number),
    );
    follow_ups.sort();
    follow_ups.dedup();
    if planned_closed
        && !f.tickets.iter().any(|input| {
            matches!(&input.facts, Observed::Complete(t)
            if t.issue.state == IssueState::Closed
                && matches!(&t.pr, Some(PrInput::Merged(m))
                    if !verified_for(m, &out.default_branch, input.number)))
        })
        && !f.records.summary_written
        && f.tickets.iter().all(|input| {
            matches!(&input.facts, Observed::Complete(t)
            if ticket_problems(t, out.planned_at).is_empty())
        })
    {
        let merged = f
            .tickets
            .iter()
            .filter_map(|t| {
                let Observed::Complete(facts) = &t.facts else {
                    return None;
                };
                if let Some(PrInput::Merged(m)) = &facts.pr
                    && verified_for(m, &out.default_branch, t.number)
                {
                    return Some(SummaryMerge {
                        ticket: t.number,
                        pr: m.pr.fields.number,
                    });
                }
                None
            })
            .collect::<Vec<_>>();
        let mut merged = merged;
        merged.sort_by_key(|m| m.ticket);
        emit(out, spec, None, Detail::SpecSummary { merged, follow_ups });
    } else if f.records.summary_written
        && follow_ups.is_empty()
        && f.tickets.iter().all(closed)
        && f.tickets.iter().all(|input| {
            matches!(&input.facts, Observed::Complete(t)
            if ticket_problems(t, out.planned_at).is_empty() && thread_facts(t).is_empty())
        })
        && !f.tickets.is_empty()
        && out.actions[start..]
            .iter()
            .all(|a| a.kind != Kind::Archive && a.kind != Kind::Wake)
    {
        out.actions.truncate(start);
        let mut tickets = f.tickets.iter().map(|t| t.number).collect::<Vec<_>>();
        tickets.sort();
        emit(out, spec, None, Detail::AllClosed { tickets });
    }
}

fn verified(m: &MergeInput, default: &NonEmpty) -> bool {
    m.read_back && m.pr.fields.base_branch == *default
}
fn verified_for(m: &MergeInput, default: &NonEmpty, issue: Number) -> bool {
    verified(m, default) && m.pr.fields.closes.contains(&issue)
}
fn merge_fact(m: &MergeInput) -> MergeFact {
    MergeFact {
        number: m.pr.fields.number,
        merge_commit: m.pr.merge_commit.clone(),
    }
}
fn pr_fact(p: &OpenPr) -> PrFact {
    PrFact {
        number: p.fields.number,
        head_commit: p.fields.head_commit.clone(),
        base_branch: p.fields.base_branch.clone(),
    }
}
fn ready_label(t: &TicketFacts, label: &str) -> bool {
    let triage = [
        "ready-for-agent",
        "ready-for-human",
        "needs-info",
        "needs-triage",
        "wontfix",
        "held",
    ];
    t.issue.labels.iter().any(|l| l.as_str() == label)
        && !t
            .issue
            .labels
            .iter()
            .any(|l| triage.contains(&l.as_str()) && l.as_str() != label)
}
fn blockers(t: &TicketFacts, default: &NonEmpty) -> Option<Vec<BlockerFact>> {
    let mut facts = Vec::new();
    for b in &t.blockers {
        let Some(m) = &b.merged else { return None };
        if b.state != IssueState::Closed || !verified_for(m, default, b.number) {
            return None;
        }
        facts.push(BlockerFact {
            number: b.number,
            pr: m.pr.fields.number,
            merge_commit: m.pr.merge_commit.clone(),
        });
    }
    facts.sort_by_key(|b| b.number);
    Some(facts)
}
fn thread_facts(t: &TicketFacts) -> Vec<ThreadFact> {
    let mut th = Vec::new();
    if let Some(b) = &t.builder
        && (!b.archived || !t.records.archived)
    {
        th.push(ThreadFact {
            thread: b.thread.clone(),
            role: Role::Builder,
        });
    }
    for r in &t.reviewers {
        if !r.agent.archived || !t.records.archived {
            th.push(ThreadFact {
                thread: r.agent.thread.clone(),
                role: Role::Reviewer,
            });
        }
    }
    th
}
fn start_problems(starts: &[Start], threads: &[&NonEmpty], reasons: &mut Vec<String>) {
    if !unique(&starts.iter().map(|s| s.id.as_str()).collect::<Vec<_>>()) {
        reasons.push("duplicate start record".into());
    }
    if starts
        .iter()
        .any(|s| matches!(s.state, StartState::Pending | StartState::Uncertain))
    {
        reasons.push("start outcome unsettled".into());
    }
    if starts
        .iter()
        .any(|s| matches!(&s.state,StartState::Started{thread} if !threads.contains(&thread)))
    {
        reasons.push("started thread has no verified placement".into());
    }
}
fn unlogged(starts: &[Start]) -> Option<(&Start, NoThread, StartReason)> {
    starts.iter().find_map(|s| {
        if s.logged {
            None
        } else {
            match s.state {
                StartState::Refused { reason } => Some((s, NoThread::Refused, reason)),
                StartState::Failed { reason } => Some((s, NoThread::Failed, reason)),
                _ => None,
            }
        }
    })
}
fn retry(starts: &[Start]) -> Option<RetryFact> {
    starts.last().and_then(|s| match s.state {
        StartState::Refused { .. } => Some(RetryFact {
            start: s.id.clone(),
            state: NoThread::Refused,
        }),
        StartState::Failed { .. } => Some(RetryFact {
            start: s.id.clone(),
            state: NoThread::Failed,
        }),
        _ => None,
    })
}
fn settled_no_thread(starts: &[Start]) -> bool {
    starts.iter().all(|s| {
        matches!(
            s.state,
            StartState::Refused { .. } | StartState::Failed { .. }
        )
    })
}
fn ticket_problems(t: &TicketFacts, now: u64) -> Vec<String> {
    let mut reasons = Vec::new();
    if !unique(&t.issue.labels) {
        reasons.push("duplicate label".into());
    }
    if !unique(&t.blockers.iter().map(|b| b.number).collect::<Vec<_>>()) {
        reasons.push("duplicate blocker".into());
    }
    let threads = t
        .builder
        .iter()
        .map(|b| &b.thread)
        .chain(t.reviewers.iter().map(|r| &r.agent.thread))
        .collect::<Vec<_>>();
    if !unique(&threads) {
        reasons.push("duplicate agent thread".into());
    }
    start_problems(
        &t.starts,
        &t.builder.iter().map(|b| &b.thread).collect::<Vec<_>>(),
        &mut reasons,
    );
    if t.starts
        .iter()
        .filter(|s| matches!(s.state, StartState::Started { .. }))
        .count()
        > 1
    {
        reasons.push("more than one builder start".into());
    }
    if !unique(&t.holds.iter().map(|h| h.comment).collect::<Vec<_>>()) {
        reasons.push("duplicate hold record".into());
    }
    if let Some(PrInput::Several(_)) = &t.pr {
        reasons.push("more than one open pull request".into());
    }
    if let Some(PrInput::Open(p)) = &t.pr {
        open_problems(p, t, now, &mut reasons);
    }
    reasons
}

fn ticket(
    out: &mut Plan,
    spec: Number,
    f: &FleetFacts,
    input: &TicketInput,
    current: bool,
) -> bool {
    let id = input.number;
    let Observed::Complete(t) = &input.facts else {
        if let Observed::Unread(p) = &input.facts {
            look(out, spec, Some(id), unread(p), &[]);
        }
        return false;
    };
    let reasons = ticket_problems(t, out.planned_at);
    if !reasons.is_empty() {
        look(out, spec, Some(id), reasons, &t.records.looked);
        return false;
    }
    if t.issue.state == IssueState::Closed {
        let threads = thread_facts(t);
        if !threads.is_empty() {
            emit(out, spec, Some(id), Detail::Finished { threads });
        }
        return false;
    }
    if let Some(PrInput::Merged(m)) = &t.pr {
        if verified_for(m, &out.default_branch, id) {
            emit(
                out,
                spec,
                Some(id),
                Detail::Merged {
                    merged: merge_fact(m),
                },
            );
        }
        return false;
    }
    if t.issue.labels.iter().any(|l| l.as_str() == "needs-info")
        && let Some(question) = t.question
        && t.records.question_passed.is_none_or(|c| question > c)
    {
        emit(out, spec, Some(id), Detail::NeedsInfo { question });
    }
    if let Some((s, state, reason)) = unlogged(&t.starts) {
        emit(
            out,
            spec,
            Some(id),
            Detail::BuilderRefused {
                start: s.id.clone(),
                state,
                reason: reason.text(),
            },
        );
    }
    let hit = contract_hit(f, t, id, &out.default_branch);
    let authority = f
        .approval
        .as_ref()
        .filter(|a| current && f.issue.state == IssueState::Open && a.rows.contains_key(&id))
        .filter(|_| hit.is_none() || t.builder.is_some());
    if let Some(PrInput::Open(p)) = &t.pr {
        open_actions(out, spec, id, t, p, authority);
    }
    let Some(a) = &f.approval else { return false };
    let Some(role) = a.rows.get(&id) else {
        return false;
    };
    if f.issue.state == IssueState::Closed {
        return false;
    }
    let held = t.issue.labels.iter().any(|l| l.as_str() == "held");
    let has_unreleased_hold = t.holds.iter().any(|h| h.comment >= a.approval.comment);
    if let Some((change, files)) = &hit {
        let merged = merge_fact(&change.merged);
        if let Some(builder) = &t.builder {
            emit(
                out,
                spec,
                Some(id),
                Detail::ContractChanged {
                    merged,
                    files: files.clone(),
                    relies_on: t.relies_on.clone(),
                    builder: builder.thread.clone(),
                },
            );
        } else if t.pr.is_some() {
            look(
                out,
                spec,
                Some(id),
                vec!["contract change has no verified builder".into()],
                &t.records.looked,
            );
            return false;
        } else {
            emit(
                out,
                spec,
                Some(id),
                Detail::ContractHold {
                    merged,
                    files: files.clone(),
                    relies_on: t.relies_on.clone(),
                    ready_label: match role {
                        Ready::Agent => "ready-for-agent",
                        Ready::Human => "ready-for-human",
                    },
                },
            );
        }
    }
    if current
        && held
        && hit.is_none()
        && let Some(h) = t.holds.iter().max_by_key(|h| h.comment)
        && a.approval.comment > h.comment
        && t.held_label_comment.is_some_and(|c| c <= h.comment)
    {
        emit(
            out,
            spec,
            Some(id),
            Detail::Release {
                hold: h.comment,
                approval: a.approval.clone(),
            },
        );
    }
    if let Some(h) = t
        .holds
        .iter()
        .filter(|h| !h.notified)
        .min_by_key(|h| h.merged.number)
    {
        let mut files = h.files.clone();
        files.sort();
        files.dedup();
        emit(
            out,
            spec,
            Some(id),
            Detail::Held {
                hold: h.comment,
                merged: h.merged.clone(),
                files,
            },
        );
    }
    if current
        && *role == Ready::Agent
        && !held
        && !has_unreleased_hold
        && hit.is_none()
        && !t.records.builder_fallback_due
        && let Some(source) = &t.builder_source
        && source.family == BuilderFamily::Claude
        && source.plan_limit
        && t.builder
            .as_ref()
            .is_some_and(|b| b.thread == source.thread && !b.archived)
        && t.pr
            .as_ref()
            .is_none_or(|p| matches!(p, PrInput::Open(p) if p.fields.head_branch == source.branch))
    {
        if out.rules.small_builder().harness == "codex" {
            emit(
                out,
                spec,
                Some(id),
                Detail::Restart {
                    builder: source.thread.clone(),
                    branch: source.branch.clone(),
                    settings: out.rules.small_builder().clone(),
                },
            );
        } else {
            look(
                out,
                spec,
                Some(id),
                vec!["fallback builder is not another family".into()],
                &t.records.looked,
            );
        }
    }
    let blockers = blockers(t, &out.default_branch);
    let unheld = !held && !has_unreleased_hold && hit.is_none();
    if *role == Ready::Human {
        if current
            && t.issue
                .labels
                .iter()
                .any(|l| l.as_str() == "ready-for-human")
            && unheld
            && !t.records.person_notified
            && let Some(blockers) = blockers
        {
            emit(
                out,
                spec,
                Some(id),
                Detail::PersonReady {
                    title: t.issue.title.clone(),
                    approval: a.approval.clone(),
                    blockers,
                },
            );
        }
        return false;
    }
    let could_start = ready_label(t, "ready-for-agent")
        && unheld
        && blockers.is_some()
        && t.pr.is_none()
        && t.builder.is_none()
        && settled_no_thread(&t.starts);
    if could_start && current {
        emit(
            out,
            spec,
            Some(id),
            Detail::Frontier {
                settings: out.rules.builder_for(&t.issue.labels).clone(),
                title: t.issue.title.clone(),
                approval: a.approval.clone(),
                labels: t.issue.labels.clone(),
                blockers: blockers.unwrap_or_default(),
                retry_after: retry(&t.starts),
            },
        );
    }
    could_start && !current
}

fn path_matches(pattern: &str, path: &str) -> bool {
    if pattern.ends_with('/') {
        return path.starts_with(pattern);
    }
    let p = pattern.split('/').collect::<Vec<_>>();
    let f = path.split('/').collect::<Vec<_>>();
    p.len() == f.len() && p.iter().zip(f).all(|(p, f)| glob_component(p, f))
}
fn glob_component(pattern: &str, text: &str) -> bool {
    let parts = pattern.split('*').collect::<Vec<_>>();
    if parts.len() == 1 {
        return pattern == text;
    }
    let Some(mut rest) = text.strip_prefix(parts[0]) else {
        return false;
    };
    for part in &parts[1..parts.len() - 1] {
        let Some(at) = rest.find(part) else {
            return false;
        };
        rest = &rest[at + part.len()..];
    }
    rest.ends_with(parts[parts.len() - 1])
}
fn contract_hit<'a>(
    f: &'a FleetFacts,
    t: &TicketFacts,
    id: Number,
    default: &NonEmpty,
) -> Option<(&'a ContractChange, Vec<NonEmpty>)> {
    let approval = f.approval.as_ref()?;
    f.changes
        .iter()
        .filter_map(|c| {
            if !verified(&c.merged, default)
                || c.merged.pr.merged_at.0 < 0
                || c.merged.pr.merged_at.0 as u64 <= approval.approved_at
                || c.merged.pr.fields.closes.contains(&id)
                || t.records.noted.contains(&c.merged.pr.fields.number)
                || t.holds
                    .iter()
                    .any(|h| h.merged.number == c.merged.pr.fields.number)
            {
                return None;
            }
            let mut files = c
                .files
                .iter()
                .filter(|f| !f.added)
                .flat_map(|f| std::iter::once(&f.path).chain(f.previous_path.iter()))
                .filter(|path| {
                    t.relies_on
                        .iter()
                        .any(|p| path_matches(p.as_str(), path.as_str()))
                })
                .cloned()
                .collect::<Vec<_>>();
            files.sort();
            files.dedup();
            (!files.is_empty()).then_some((c, files))
        })
        .min_by_key(|(c, _)| c.merged.pr.fields.number)
}

struct Report {
    fact: VerdictFact,
    disputed: Vec<String>,
    diagnosis: Vec<Finding>,
}
fn latest_report(p: &OpenPr) -> Result<Option<Report>, &'static str> {
    let Some(c) = p.reports.iter().max_by_key(|c| c.comment) else {
        return Ok(None);
    };
    let line = c.text.lines().next().ok_or("malformed latest verdict")?;
    let (verdict, id) = if let Some(s) = line.strip_prefix("VERDICT: APPROVE at ") {
        (Verdict::Approve, s)
    } else if let Some(s) = line.strip_prefix("VERDICT: CHANGES at ") {
        (Verdict::Changes, s)
    } else {
        return Err("malformed latest verdict");
    };
    let commit = super::super::model::Commit::parse(id).ok_or("malformed latest verdict")?;
    let mut report = Report {
        fact: VerdictFact {
            verdict,
            commit,
            comment: c.comment,
        },
        disputed: vec![],
        diagnosis: vec![],
    };
    if verdict == Verdict::Approve {
        return Ok(Some(report));
    }
    let mut ids = BTreeSet::new();
    let mut disputes = Vec::new();
    let mut diagnoses = Vec::new();
    for line in c.text.lines().filter(|l| l.starts_with("- **R")) {
        let rest = line.strip_prefix("- **R").ok_or("malformed finding")?;
        let (id, rest) = rest.split_once(" [").ok_or("malformed finding")?;
        if id.is_empty() || id.starts_with('0') || !id.bytes().all(|b| b.is_ascii_digit()) {
            return Err("malformed finding");
        }
        let number = id.parse::<u64>().map_err(|_| "malformed finding")?;
        if !ids.insert(number) {
            return Err("duplicate finding");
        }
        let (severity, rest) = rest.split_once("]** ").ok_or("malformed finding")?;
        if !["high", "medium", "low"].contains(&severity) {
            return Err("malformed finding");
        }
        let label = format!("R{id}");
        if rest.starts_with("disputed, kept:") {
            disputes.push((number, label.clone()));
        }
        if let Some(rest) = rest.strip_prefix("still open after ")
            && let Some((rounds, _)) = rest.split_once(" rounds:")
            && !rounds.is_empty()
            && rounds.bytes().all(|b| b.is_ascii_digit())
            && let Ok(rounds) = rounds.parse::<u64>()
            && rounds >= 2
        {
            diagnoses.push((number, Finding { id: label, rounds }));
        }
    }
    disputes.sort_by_key(|f| f.0);
    diagnoses.sort_by_key(|f| f.0);
    report.disputed = disputes.into_iter().map(|f| f.1).collect();
    report.diagnosis = diagnoses.into_iter().map(|f| f.1).collect();
    Ok(Some(report))
}
fn open_problems(p: &OpenPr, t: &TicketFacts, now: u64, reasons: &mut Vec<String>) {
    let reviewers = t
        .reviewers
        .iter()
        .filter(|r| r.pr == p.fields.number)
        .collect::<Vec<_>>();
    start_problems(
        &p.starts,
        &reviewers
            .iter()
            .map(|r| &r.agent.thread)
            .collect::<Vec<_>>(),
        reasons,
    );
    if t.issue.state == IssueState::Closed {
        return;
    }
    if !unique(&p.reports.iter().map(|r| r.comment).collect::<Vec<_>>()) {
        reasons.push("duplicate report comment".into());
    }
    if p.ci
        .as_ref()
        .is_some_and(|c| !unique(&c.checks.iter().map(|c| &c.name).collect::<Vec<_>>()))
    {
        reasons.push("duplicate check name".into());
    }
    if reviewers.iter().filter(|r| !r.given_up).count() > 1 {
        reasons.push("more than one active reviewer".into());
    }
    match latest_report(p) {
        Err(reason) => reasons.push(reason.into()),
        Ok(report) => {
            for r in reviewers.iter().filter(|r| !r.given_up) {
                let reviewed = r.output.as_ref().is_some_and(|v| v.commit == r.head)
                    || report.as_ref().is_some_and(|v| v.fact.commit == r.head);
                if !reviewed && now.saturating_sub(r.last_activity_at) >= 1_800_000 {
                    reasons.push(format!(
                        "reviewer quiet for 30 minutes on {} since {}",
                        r.head.as_str(),
                        r.last_activity_at
                    ));
                }
            }
        }
    }
}
fn handback(s: &str) -> bool {
    s.split(|c: char| !c.is_alphanumeric() && c != '_')
        .any(|w| w.eq_ignore_ascii_case("green"))
}
fn green(out: &Plan, p: &OpenPr) -> bool {
    let Some(ci) = &p.ci else { return false };
    if ci.head_commit != p.fields.head_commit {
        return false;
    }
    let required = out
        .rules
        .ci_checks
        .iter()
        .filter(|c| {
            c.required_on
                .iter()
                .any(|b| branch_matches(b, p.fields.base_branch.as_str()))
        })
        .collect::<Vec<_>>();
    !required.is_empty()
        && required.iter().all(|c| {
            ci.checks
                .iter()
                .any(|x| x.name.as_str() == c.name && x.result == CheckResult::Pass)
        })
        && ci.checks.iter().all(|c| {
            !matches!(
                c.result,
                CheckResult::Fail | CheckResult::Cancel | CheckResult::Pending
            )
        })
}
fn open_actions(
    out: &mut Plan,
    spec: Number,
    id: Number,
    t: &TicketFacts,
    p: &OpenPr,
    authority: Option<&PlanApproval>,
) {
    if p.fields.draft
        || p.fields.base_branch != out.default_branch
        || out.default_branch.as_str().starts_with("release-")
        || !p.fields.closes.contains(&id)
    {
        return;
    }
    let fact = pr_fact(p);
    let head = &p.fields.head_commit;
    let reviewers = t
        .reviewers
        .iter()
        .filter(|r| r.pr == p.fields.number)
        .collect::<Vec<_>>();
    if let Some((s, state, reason)) = unlogged(&p.starts) {
        emit(
            out,
            spec,
            Some(id),
            Detail::ReviewerRefused {
                pr: fact.clone(),
                start: s.id.clone(),
                state,
                reason: reason.text(),
            },
        );
    }
    let Ok(report) = latest_report(p) else { return };
    let on_head = report.as_ref().filter(|r| r.fact.commit == *head);
    let checks =
        p.ci.as_ref()
            .filter(|c| c.head_commit == *head)
            .map(|c| c.checks.clone())
            .unwrap_or_default();
    let green = green(out, p);
    if handback(&p.subject) {
        if checks
            .iter()
            .any(|c| matches!(c.result, CheckResult::Fail | CheckResult::Cancel))
            && !p.records.ci_sent.contains(head)
        {
            if let Some(b) = &t.builder {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::CiFailed {
                        pr: fact.clone(),
                        subject: p.subject.clone(),
                        checks: checks.clone(),
                        builder: b.thread.clone(),
                    },
                );
            }
        } else if green
            && let Some(r) = on_head
            && r.fact.verdict == Verdict::Changes
            && !p.records.findings_sent.contains(head)
            && let Some(b) = &t.builder
        {
            emit(
                out,
                spec,
                Some(id),
                Detail::ReviewFindings {
                    pr: fact.clone(),
                    checks: checks.clone(),
                    verdict: r.fact.clone(),
                    builder: b.thread.clone(),
                },
            );
        }
        if authority.is_some()
            && green
            && on_head.is_none()
            && !p.records.recheck_sent.contains(head)
        {
            let new_reviewer = reviewers.is_empty() || reviewers.iter().all(|r| r.given_up);
            let source = t.builder_source.as_ref().filter(|s| {
                s.branch == p.fields.head_branch
                    && t.builder.as_ref().is_some_and(|b| b.thread == s.thread)
            });
            if new_reviewer && source.is_none() {
                look(
                    out,
                    spec,
                    Some(id),
                    vec!["builder family unknown or conflicting".into()],
                    &t.records.looked,
                );
                return;
            }
            let review = source
                .and_then(|s| out.rules.reviewer_for(s.family))
                .cloned();
            if new_reviewer && review.is_none() {
                look(
                    out,
                    spec,
                    Some(id),
                    vec!["review waits: no other-family reviewer".into()],
                    &t.records.looked,
                );
                return;
            }
            if let (true, Some(settings)) = (reviewers.is_empty(), review.clone()) {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::FirstReview {
                        settings,
                        pr: fact.clone(),
                        subject: p.subject.clone(),
                        checks: checks.clone(),
                    },
                );
            } else if let (true, Some(settings)) = (reviewers.iter().all(|r| r.given_up), review) {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::FreshReview {
                        settings,
                        pr: fact.clone(),
                        subject: p.subject.clone(),
                        checks: checks.clone(),
                        given_up: reviewers.iter().map(|r| r.agent.thread.clone()).collect(),
                    },
                );
            } else if let Some(r) = reviewers.iter().find(|r| {
                !r.given_up
                    && r.head != *head
                    && (r.output.as_ref().is_some_and(|v| v.commit == r.head)
                        || report.as_ref().is_some_and(|v| v.fact.commit == r.head))
            }) {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::ReCheck {
                        pr: fact.clone(),
                        subject: p.subject.clone(),
                        checks: checks.clone(),
                        reviewer: r.agent.thread.clone(),
                        last_verdict: report.as_ref().map(|r| r.fact.clone()),
                    },
                );
            }
        }
    }
    if let Some(r) = on_head {
        if r.fact.verdict == Verdict::Changes {
            if !r.disputed.is_empty() && !p.records.dispute_asked.contains(head) {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::Disputed {
                        pr: fact.clone(),
                        verdict: r.fact.clone(),
                        findings: r.disputed.clone(),
                    },
                );
            }
            if !r.diagnosis.is_empty() && !p.records.diagnosis_asked.contains(head) {
                emit(
                    out,
                    spec,
                    Some(id),
                    Detail::Diagnosis {
                        pr: fact,
                        verdict: r.fact.clone(),
                        findings: r.diagnosis.clone(),
                    },
                );
            }
        } else if let Some(a) = authority
            && green
            && out.rules.merge == MergeRule::Adr0008
            && p.ci
                .as_ref()
                .is_some_and(|ci| Some(&ci.base_commit) == p.base_now.as_ref())
        {
            let review = Review {
                verdict: r.fact.verdict,
                commit: r.fact.commit.clone(),
            };
            if let Some(reviewer) = reviewers
                .iter()
                .find(|x| !x.given_up && x.head == *head && x.output.as_ref() == Some(&review))
            {
                if p.records.merge_blocked.contains(head) {
                    look(
                        out,
                        spec,
                        Some(id),
                        vec![format!(
                            "merge blocked on the approved head {}",
                            head.as_str()
                        )],
                        &t.records.looked,
                    );
                } else if let Some(base_commit) = &p.base_now {
                    emit(
                        out,
                        spec,
                        Some(id),
                        Detail::Adr0008 {
                            approval: a.approval.clone(),
                            pr: fact,
                            base_commit: base_commit.clone(),
                            verdict: r.fact.clone(),
                            reviewer: reviewer.agent.thread.clone(),
                            checks,
                        },
                    );
                }
            }
        }
    }
}
