//! B5's dispatch. Uses B3/B4 and send; final records follow successful writes.
use super::{graph::World, records};
use openwiz_adapter_cloudroom::{
    allowlist::ThreadId, archive::ArchiveOutcome, source::CloudRoomSource,
};
use openwiz_adapter_github::{
    tick::{Comment, TickReads},
    writes::{self, Body, Confirmed, Label, Write, WriteError},
};
use openwiz_core::fleet::model::{ListOutcome, Number};
use openwiz_core::fleet::starts::{
    self, AttemptOutcome, Locked, StartKey, StartOutcome, StartRequest, StartStore,
};
use openwiz_core::fleet::tick::*;
use openwiz_core::health::model::Id;
use openwiz_core::messaging::send::{Messenger, SendRequest, Status, send};
use openwiz_core::model::SessionId;
use openwiz_core::new_thread::Settings;
use openwiz_core::ops::Clock;
use openwiz_store::{FileStore, NewThreadFileStore, StartFileStore};
use serde_json::{Value, json};
use std::path::Path;
use std::time::Instant;

type Done = Result<(), Failure>;
#[derive(Debug)]
struct Failure {
    state: &'static str,
    reason: &'static str,
}
fn fail(reason: &'static str) -> Failure {
    Failure {
        state: "failed",
        reason,
    }
}
fn uncertain(reason: &'static str) -> Failure {
    Failure {
        state: "uncertain",
        reason,
    }
}
fn refused(reason: &'static str) -> Failure {
    Failure {
        state: "refused",
        reason,
    }
}
fn result(done: Done) -> Value {
    match done {
        Ok(()) => json!({"state":"done"}),
        Err(f) => json!({"state":f.state,"reason":f.reason}),
    }
}
struct Executor<'a> {
    world: &'a mut World,
    gh: &'a TickReads,
    room: &'a CloudRoomSource,
    state: &'a Path,
    deadline: Instant,
    control: Option<&'a super::Control>,
}
impl Executor<'_> {
    fn write(&mut self, w: Write) -> Result<Confirmed, Failure> {
        writes::perform_with(self.gh.executor(), &w, self.deadline).map_err(|e| match e {
            WriteError::NotAllowed | WriteError::NotAnIssue | WriteError::MergeQueue => {
                refused("GitHub write refused before dispatch")
            }
            WriteError::CheckFailed(_) => fail("GitHub precondition unread; nothing written"),
            WriteError::Failed(_) | WriteError::ReadBackFailed(_) | WriteError::NotShown(_) => {
                uncertain("GitHub write not confirmed")
            }
        })
    }
    fn comment(&mut self, id: Number, pr: bool, text: String) -> Done {
        if records::contains_thread_id(&text) {
            return Err(refused("public record contains a thread id"));
        }
        // Read afresh: a prior tick may have completed a write after this
        // snapshot, including between a close's reason and the close itself.
        let current = self
            .gh
            .comments(id, self.deadline)
            .map_err(|_| fail("comment records unread"))?;
        self.world.comments.insert(id, current.clone());
        let line = text.lines().next().ok_or_else(|| fail("empty record"))?;
        if records::has(&current, line) {
            return Ok(());
        }
        let body = Body::parse(&text).ok_or_else(|| fail("record text invalid"))?;
        let w = if pr {
            Write::PrComment { pr: id, body }
        } else {
            Write::IssueComment { issue: id, body }
        };
        let Confirmed::Commented { url } = self.write(w)? else {
            return Err(uncertain("comment read-back missing"));
        };
        let id_value = url
            .rsplit('-')
            .next()
            .and_then(|s| records::n(s).ok())
            .ok_or_else(|| uncertain("comment identifier unread"))?;
        let now = crate::SystemClock.now().0.max(0) as u64;
        self.world.comments.entry(id).or_default().push(Comment {
            id: id_value,
            body: text,
            created: now,
            updated: now,
        });
        Ok(())
    }
    fn send(&self, target: &str, text: String) -> Done {
        let store = FileStore::open(self.state).map_err(|_| fail("send store unavailable"))?;
        let op = crate::send::random_op_id().map_err(|_| fail("send id unavailable"))?;
        let mut request = SendRequest::new(SessionId(target.into()), text, op);
        request.budget = self.deadline.saturating_duration_since(Instant::now());
        let owned;
        let messenger: &dyn Messenger = if let Some(control) = self.control {
            owned = self.room.project_messenger(
                Id::parse(control.project())
                    .ok_or_else(|| refused("invalid configured project"))?,
            );
            &owned
        } else {
            self.room
        };
        let report = send(messenger, &store, &crate::SystemClock, &request)
            .map_err(|_| fail("message not sent"))?;
        match report.status {
            Status::Queued | Status::Accepted => Ok(()),
            Status::Uncertain | Status::InProgress => Err(uncertain("message outcome uncertain")),
            _ => Err(fail("message not delivered")),
        }
    }
    fn restart_due(
        &mut self,
        ticket: Number,
        builder: &openwiz_core::fleet::model::NonEmpty,
        branch: &openwiz_core::fleet::model::NonEmpty,
    ) -> Done {
        let repo = starts::Repository::parse(&self.world.repository.name)
            .map_err(|_| fail("invalid repository"))?;
        let key = StartKey::builder(repo, ticket);
        let store =
            StartFileStore::open(self.state).map_err(|_| fail("start store unavailable"))?;
        if !matches!(
            store.lock(&key).map_err(|_| fail("builder lock unread"))?,
            Locked::Mine(_)
        ) {
            return Err(refused("builder start or fallback already in progress"));
        }
        let result = (|| {
            let comments = self
                .gh
                .comments(ticket, self.deadline)
                .map_err(|_| fail("fallback records unread"))?;
            if records::fallback_due(&comments) {
                return Err(refused("builder fallback already recorded"));
            }
            self.comment(ticket, false, records::fallback_record(builder, branch))
        })();
        store.unlock(&key);
        result
    }
    fn start(&mut self, key: StartKey, rule: &AgentRule) -> Result<String, Failure> {
        let project = self
            .world
            .project
            .clone()
            .ok_or_else(|| fail("no unique CloudRoom project for repository"))?;
        let settings = Settings {
            harness: rule.harness.clone(),
            model: rule.model.clone(),
            effort: rule.effort.clone(),
        };
        let mut request = StartRequest::new(key, project, settings);
        request.budget = self.deadline.saturating_duration_since(Instant::now());
        let threads = NewThreadFileStore::open(self.state)
            .map_err(|_| fail("new-thread store unavailable"))?;
        let starts =
            StartFileStore::open(self.state).map_err(|_| fail("start store unavailable"))?;
        let report = starts::start_agent(
            self.room,
            &threads,
            &starts,
            &crate::SystemClock,
            &crate::send::random_op_id,
            &request,
        )
        .map_err(|_| fail("agent start incomplete"))?;
        if !report.gaps.is_empty() {
            return Err(uncertain("agent start record incomplete"));
        }
        match report.outcome {
            StartOutcome::Started { thread_id, .. } => Ok(thread_id),
            StartOutcome::NotStarted { .. } | StartOutcome::Conflicting { .. } => {
                Err(refused("agent start refused"))
            }
            StartOutcome::Uncertain { .. } | StartOutcome::InProgress => {
                Err(uncertain("agent start outcome uncertain"))
            }
        }
    }
    fn notify(&mut self, action: &Action, text: String, record: String, summary: bool) -> Done {
        let target = self
            .world
            .orchestrator
            .as_deref()
            .filter(|s| starts::safe_id(s))
            .ok_or_else(|| fail("orchestrator thread missing or invalid"))?;
        self.send(target, format!("Needs you: {text}"))?;
        if summary {
            return self.comment(action.spec, false, record);
        }
        self.comment(action.spec, false, format!("**Needs you:** {text}"))?;
        self.comment(action.ticket.unwrap_or(action.spec), false, record)
    }
    fn action(&mut self, a: &Action) -> Done {
        let ticket = a.ticket.unwrap_or(a.spec);
        match &a.detail {
            Detail::Frontier { settings, .. } => {
                let repo = starts::Repository::parse(&self.world.repository.name)
                    .map_err(|_| fail("invalid repository"))?;
                self.start(StartKey::builder(repo, ticket), settings)?;
                self.comment(ticket, false, "launch-fleet: started".into())
            }
            Detail::FirstReview { pr, settings, .. } | Detail::FreshReview { pr, settings, .. } => {
                let repo = starts::Repository::parse(&self.world.repository.name)
                    .map_err(|_| fail("invalid repository"))?;
                self.start(
                    StartKey::reviewer(repo, pr.number, pr.head_commit.clone()),
                    settings,
                )?;
                self.comment(
                    pr.number,
                    true,
                    format!("launch-fleet: review started {}", pr.head_commit.as_str()),
                )
            }
            Detail::ReCheck { pr, reviewer, .. } => {
                self.send(reviewer.as_str(),format!("Re-check pull request #{} at {}: read skills/review-ticket/SKILL.md, Re-checks.",pr.number,pr.head_commit.as_str()))?;
                self.comment(
                    pr.number,
                    true,
                    format!("launch-fleet: re-check sent {}", pr.head_commit.as_str()),
                )
            }
            Detail::ReviewFindings { pr, builder, .. } => {
                self.send(builder.as_str(),format!("The review of pull request #{} at {} asks for changes: read the report there. Fix or dispute each open finding, then hand back a new green head.",pr.number,pr.head_commit.as_str()))?;
                self.comment(
                    pr.number,
                    true,
                    format!("launch-fleet: findings sent {}", pr.head_commit.as_str()),
                )
            }
            Detail::CiFailed {
                pr,
                checks,
                builder,
                ..
            } => {
                let failed = checks
                    .iter()
                    .filter(|c| {
                        matches!(
                            c.result,
                            openwiz_core::fleet::model::CheckResult::Fail
                                | openwiz_core::fleet::model::CheckResult::Cancel
                        )
                    })
                    .map(|c| c.name.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                self.send(builder.as_str(),format!("CI failed on pull request #{} at {}: {}. Read the failed job, reproduce it, fix it and hand back a new green head.",pr.number,pr.head_commit.as_str(),failed))?;
                self.comment(
                    pr.number,
                    true,
                    format!("launch-fleet: CI failure sent {}", pr.head_commit.as_str()),
                )
            }
            Detail::ContractChanged {
                merged,
                files,
                builder,
                ..
            } => {
                let paths = files
                    .iter()
                    .map(|s| s.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                self.send(
                    builder.as_str(),
                    format!(
                        "Contract changed in #{}: {paths}. Check the change before continuing.",
                        merged.number
                    ),
                )?;
                self.comment(
                    ticket,
                    false,
                    format!("launch-fleet: noted #{}", merged.number),
                )
            }
            Detail::Adr0008 {
                approval,
                pr,
                base_commit,
                verdict,
                ..
            } => {
                // Recheck the base immediately before the write, independently
                // of the match-head condition enforced by B3's merge command.
                if self
                    .gh
                    .branch(pr.base_branch.as_str(), self.deadline)
                    .map_err(|_| fail("base unread before merge"))?
                    != *base_commit
                {
                    return Err(refused("base moved since CI"));
                }
                let rule = format!(
                    "ADR 0008: approval revision {} (comment {}), APPROVE (comment {}), CI green",
                    approval.revision, approval.comment, verdict.comment
                );
                let body = Body::parse(&format!(
                    "Merge #{} at {} by {rule}",
                    pr.number,
                    pr.head_commit.as_str()
                ))
                .ok_or_else(|| fail("merge record invalid"))?;
                if let Err(e) = self.write(Write::Merge {
                    pr: pr.number,
                    head: pr.head_commit.clone(),
                    body,
                }) {
                    // A failed merge never turns into a successful outcome.
                    self.comment(
                        pr.number,
                        true,
                        format!(
                            "launch-fleet: merge blocked {}: merge not confirmed",
                            pr.head_commit.as_str()
                        ),
                    )?;
                    return Err(e);
                }
                self.comment(
                    ticket,
                    false,
                    format!(
                        "launch-fleet: merged #{} at {} by {rule}",
                        pr.number,
                        pr.head_commit.as_str()
                    ),
                )
            }
            Detail::Merged { merged } => {
                self.comment(
                    ticket,
                    false,
                    format!(
                        "launch-fleet: closed: merged in #{} at {}",
                        merged.number,
                        merged.merge_commit.as_str()
                    ),
                )?;
                self.write(Write::CloseIssue { issue: ticket })?;
                Ok(())
            }
            Detail::AllClosed { .. } => {
                self.comment(
                    a.spec,
                    false,
                    "launch-fleet: closed: every ticket is closed".into(),
                )?;
                self.write(Write::CloseIssue { issue: a.spec })?;
                Ok(())
            }
            Detail::ContractHold {
                merged,
                files,
                ready_label,
                ..
            } => {
                let current = &self.world.issues[&ticket].labels;
                if !current.iter().any(|l| l.as_str() == "held") {
                    self.write(Write::AddLabel {
                        issue: ticket,
                        label: Label::parse("held").unwrap(),
                    })?;
                }
                if self.world.issues[&ticket]
                    .labels
                    .iter()
                    .any(|l| l.as_str() == *ready_label)
                {
                    self.write(Write::RemoveLabel {
                        issue: ticket,
                        label: Label::parse(ready_label).unwrap(),
                    })?;
                }
                let paths = files
                    .iter()
                    .map(|s| s.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                self.comment(ticket,false,format!("launch-fleet: held for #{}: contract changed, re-approve. {paths} changed in #{}.",merged.number,merged.number))
            }
            Detail::Release { .. } => {
                self.write(Write::RemoveLabel {
                    issue: ticket,
                    label: Label::parse("held").unwrap(),
                })?;
                Ok(())
            }
            Detail::Finished { threads } => {
                for t in threads {
                    let id = ThreadId::parse(t.thread.as_str())
                        .map_err(|_| fail("invalid archive target"))?;
                    let outcome = if let Some(control) = self.control {
                        self.room.archive_owned(
                            &Id::parse(id.as_str())
                                .ok_or_else(|| fail("invalid archive target"))?,
                            &Id::parse(control.project())
                                .ok_or_else(|| refused("invalid configured project"))?,
                            self.deadline,
                        )
                    } else {
                        self.room.archive_thread(&id, self.deadline)
                    };
                    match outcome {
                        ArchiveOutcome::Archived | ArchiveOutcome::AlreadyArchived => {}
                        ArchiveOutcome::Unconfirmed { .. } => {
                            return Err(uncertain("archive outcome uncertain"));
                        }
                        _ => return Err(fail("agent not archived")),
                    }
                }
                self.comment(ticket, false, "launch-fleet: archived".into())
            }
            Detail::BuilderRefused { start, state, .. } => {
                let verb = if *state == NoThread::Refused {
                    "refused"
                } else {
                    "failed"
                };
                self.comment(
                    ticket,
                    false,
                    format!("launch-fleet: start {verb}: agent not created (start {start})"),
                )
            }
            Detail::ReviewerRefused {
                pr, start, state, ..
            } => {
                let verb = if *state == NoThread::Refused {
                    "refused"
                } else {
                    "failed"
                };
                self.comment(
                    pr.number,
                    true,
                    format!(
                        "launch-fleet: review {verb} {}: agent not created (start {start})",
                        pr.head_commit.as_str()
                    ),
                )
            }
            Detail::Restart {
                builder, branch, ..
            } => self.restart_due(ticket, builder, branch),
            Detail::NeedsInfo { .. }
            | Detail::Disputed { .. }
            | Detail::Diagnosis { .. }
            | Detail::Look { .. } => Ok(()),
            Detail::Held { merged, .. } => self.notify(
                a,
                format!(
                    "#{ticket} is held for #{}; re-approve its plan.",
                    merged.number
                ),
                format!("launch-fleet: needs you sent: held for #{}", merged.number),
                false,
            ),
            Detail::PersonReady { .. } => self.notify(
                a,
                format!("#{ticket} is ready, and only you can do it"),
                "launch-fleet: told the user".into(),
                false,
            ),
            Detail::ReApprove {
                approval,
                fingerprint_now,
            } => {
                let fp = serde_json::to_value(fingerprint_now)
                    .map_err(|_| fail("fingerprint unavailable"))?;
                self.notify(a,format!("spec #{} changed since revision {}; approve its current plan.",a.spec,approval.revision),format!("launch-fleet: needs approval: changed since revision {} (fingerprint now {})",approval.revision,&fp.as_str().ok_or_else(||fail("fingerprint unavailable"))?[..12]),false)
            }
            Detail::SpecSummary { merged, follow_ups } => {
                let merges = merged
                    .iter()
                    .map(|m| format!("#{} in #{}", m.ticket, m.pr))
                    .collect::<Vec<_>>()
                    .join(", ");
                let follow = follow_ups
                    .iter()
                    .map(|n| format!("#{n}"))
                    .collect::<Vec<_>>()
                    .join(", ");
                self.notify(
                    a,
                    format!("spec #{} is done: {merges}. Follow-ups: {follow}.", a.spec),
                    format!("launch-fleet: spec summary: {merges}; follow-ups: {follow}"),
                    true,
                )
            }
        }
    }
}
pub fn perform(
    world: &mut World,
    gh: &TickReads,
    room: &CloudRoomSource,
    state: &Path,
    deadline: Instant,
    a: &Action,
    control: Option<&super::Control>,
) -> Value {
    if control.is_some_and(|c| {
        c.check(world.project.as_deref())
            .and_then(|()| c.check_fleet(a.spec))
            .is_err()
    }) {
        return result(Err(refused("tick control refused dispatch")));
    }
    if let Some(control) = control
        && let Err(reason) = control.check_completion(&a.detail)
    {
        return result(Err(refused(reason)));
    }
    // A service repair pins placement for every action, without repeating
    // the whole GitHub inventory for actions that need no authority refresh.
    if let Some(control) = control {
        let Some(repository) =
            openwiz_adapter_cloudroom::fleet::Repository::parse(&world.repository.name)
        else {
            return result(Err(refused("configured project changed or unread")));
        };
        match openwiz_adapter_cloudroom::fleet::projects(room, &repository, deadline) {
            ListOutcome::Complete { value }
                if value.len() == 1 && control.check(Some(value[0].id.as_str())).is_ok() => {}
            _ => return result(Err(refused("configured project changed or unread"))),
        }
    }
    // Re-read authority immediately before a start or merge. B4 additionally
    // serializes starts under their own durable key lock across processes.
    let gated = matches!(
        a.kind,
        Kind::StartBuilder | Kind::StartReviewer | Kind::Merge
    ) || matches!(a.detail, Detail::Release { .. } | Detail::Restart { .. });
    if gated
        && !still_authorized(
            world,
            gh,
            room,
            state,
            deadline,
            a,
            Authority {
                pending: None,
                control,
            },
        )
    {
        return result(Err(refused("action authority changed or unread")));
    }
    if control.is_some_and(|c| {
        c.check(world.project.as_deref())
            .and_then(|()| c.check_fleet(a.spec))
            .is_err()
    }) {
        return result(Err(refused("tick control refused dispatch")));
    }
    result(
        Executor {
            world,
            gh,
            room,
            state,
            deadline,
            control,
        }
        .action(a),
    )
}
/// Recovery is eligible only where the planner would authorize that exact
/// start with its pending marker removed. B4 then reconciles under its lock
/// before any possible retry. A stale plan cannot turn recovery into a start.
/// Each action it ran and its outcome are returned, so the caller can add them
/// to the JSON document and report an unsuccessful one through the plain
/// diagnostic, without executing it again.
pub fn recover(
    world: &mut World,
    gh: &TickReads,
    room: &CloudRoomSource,
    state: &Path,
    deadline: Instant,
    now: u64,
    control: Option<&super::Control>,
) -> Result<Vec<Value>, &'static str> {
    if let Some(control) = control {
        control.check(world.project.as_deref())?;
    }
    let pending = world
        .starts
        .iter()
        .filter(|r| {
            matches!(
                r.attempts().last().unwrap().outcome,
                AttemptOutcome::Pending
            )
        })
        .cloned()
        .collect::<Vec<_>>();
    if pending.is_empty() {
        return Ok(vec![]);
    }
    let mut recovered = Vec::new();
    for record in pending {
        if let Some(control) = control {
            control.check(world.project.as_deref())?;
        }
        let mut snapshot = world.snapshot.clone();
        without_pending(&mut snapshot, &record);
        let p = plan(&snapshot, &world.rules, now).map_err(|_| "recovery plan unavailable")?;
        let eligible = p
            .actions
            .iter()
            .find(|a| match (&a.detail, record.key().role()) {
                (Detail::Frontier { .. }, starts::Role::Builder) => {
                    a.ticket == Some(record.key().number())
                }
                (
                    Detail::FirstReview { pr, .. } | Detail::FreshReview { pr, .. },
                    starts::Role::Reviewer,
                ) => {
                    pr.number == record.key().number()
                        && Some(&pr.head_commit) == record.key().commit()
                }
                _ => false,
            });
        if let Some(a) = eligible
            && control.is_none_or(|c| c.check_fleet(a.spec).is_ok())
            && still_authorized(
                world,
                gh,
                room,
                state,
                deadline,
                a,
                Authority {
                    pending: Some(&record),
                    control,
                },
            )
        {
            if let Some(control) = control {
                control.check(world.project.as_deref())?;
                if control.check_fleet(a.spec).is_err() {
                    continue;
                }
            }
            let mut reported = serde_json::to_value(a).map_err(|_| "recovery encoding failed")?;
            reported["outcome"] = result(
                Executor {
                    world,
                    gh,
                    room,
                    state,
                    deadline,
                    control,
                }
                .action(a),
            );
            recovered.push(reported);
        }
    }
    if !recovered.is_empty() {
        *world = world.refresh(gh, room, state, deadline, None)?;
        if let Some(control) = control {
            control.check(world.project.as_deref())?;
        }
    }
    Ok(recovered)
}

/// Facts omitted from an action's public evidence (rules and project identity)
/// must still match before executing its previously planned request.
struct Authority<'a> {
    pending: Option<&'a starts::StartRecord>,
    control: Option<&'a super::Control>,
}
fn still_authorized(
    world: &World,
    gh: &TickReads,
    room: &CloudRoomSource,
    state: &Path,
    deadline: Instant,
    action: &Action,
    authority: Authority<'_>,
) -> bool {
    let Authority { pending, control } = authority;
    let Ok(mut fresh) = world.refresh(gh, room, state, deadline, Some(action.spec)) else {
        return false;
    };
    if control.is_some_and(|c| {
        c.check(fresh.project.as_deref())
            .and_then(|()| c.check_fleet(action.spec))
            .is_err()
    }) {
        return false;
    }
    if fresh.rules != world.rules
        || !fresh
            .repository
            .name
            .eq_ignore_ascii_case(&world.repository.name)
        || fresh.repository.default != world.repository.default
        || (matches!(
            action.detail,
            Detail::Frontier { .. } | Detail::FirstReview { .. } | Detail::FreshReview { .. }
        ) && fresh.project != world.project)
    {
        return false;
    }
    if let Some(record) = pending {
        without_pending(&mut fresh.snapshot, record);
    }
    plan(
        &fresh.snapshot,
        &fresh.rules,
        crate::SystemClock.now().0.max(0) as u64,
    )
    .is_ok_and(|p| p.actions.iter().any(|a| a == action))
}
fn without_pending(snapshot: &mut Snapshot, record: &starts::StartRecord) {
    if let Observed::Complete(fleets) = &mut snapshot.fleets {
        for f in fleets {
            if let Observed::Complete(f) = &mut f.facts {
                for t in &mut f.tickets {
                    if let Observed::Complete(t) = &mut t.facts {
                        t.starts
                            .retain(|s| !record.attempts().iter().any(|a| a.op_id == s.id));
                        if let Some(PrInput::Open(p)) = &mut t.pr {
                            p.starts
                                .retain(|s| !record.attempts().iter().any(|a| a.op_id == s.id));
                        }
                    }
                }
            }
        }
    }
}
