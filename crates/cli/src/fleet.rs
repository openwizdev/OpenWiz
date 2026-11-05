//! `openwiz fleet <spec> [--json]` (OpenWiz 0.0.6, spec 1, A5,
//! ClosedWiz#113): one fleet's tickets, worked out fresh from GitHub
//! through `gh`: each ticket's state, blockers (in any version), owned
//! paths and relies-on, its pull request, CI and the reviewer's verdict,
//! and "needs you". A ticket is merged only once its merge is read back.
//!
//! `--json` prints the `openwiz.fleet.v1` envelope
//! (`contracts/fleet.v1.md`); the text shows the same facts. Read-only:
//! only allowlisted `gh` and `room-cli` reads run. A ticket's builder is
//! placed through A6's verified thread, branch and pull request chain.
//!
//! Its usage line, its `--help` section and its exit codes are here too,
//! so A5 changes only this file.

#[path = "fleet_tick.rs"]
pub mod tick;

use std::ffi::OsString;
use std::fmt::Write as _;
use std::io::Write;
use std::time::{Duration, Instant};

use openwiz_adapter_cloudroom::{fleet as cloudroom, source::CloudRoomSource};
use openwiz_adapter_github::tickets::{TESTED_VERSION, Tickets};
use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::fleet::agents;
use openwiz_core::fleet::model::{
    Check, Counts, Envelope, Failed, FleetView, Issue, ListOutcome, NeedsYou, NeedsYouKind,
    NonEmpty, Number, Outcome, PullRequest, Read, ReadId, ReadKind, State, TicketCore, TicketState,
    UnplacedReason, Verdict, View, WorkedOut,
};
use openwiz_core::fleet::tickets::{
    self, AgentReads, Agents, Ci, FleetRequest, GitHub, Placed, Records, RepositoryAnswer,
    TestedVersions,
};
use openwiz_core::limits::RUN_BUDGET;
use openwiz_core::ops::Clock;

use crate::{EXIT_OK, EXIT_READ_FAILED, EXIT_USAGE, SystemClock};

/// Its line in `openwiz --help`'s usage.
pub const USAGE: &str = "  openwiz fleet <spec> [--json]\n";

/// Its section of `openwiz --help`.
pub const HELP: &str = "fleet <spec>
  One fleet: the spec issue <spec> and its tickets (its sub-issues), read from GitHub
  through gh, in the repository of the working directory. Each ticket's state, its
  blockers (in any version), owned paths, relies on, pull request, CI and the
  reviewer's verdict, and the \"needs you\" items. Merged means the pull request's
  merge commit was read back on its base: never an approval, a ready pull request or
  a closed issue. Unknowns stay unknown, with their reasons; a failed read makes the
  answer partial. Reads gh's version, repo view, issue view, pr view, pr checks
  and api compare; room-cli's version, CloudRoom projects, threads and Cloud workspaces.
  Builders are placed only through the verified thread, branch and pull request chain.
  --json prints openwiz.fleet.v1.
";

/// Its lines in `openwiz --help`'s exit codes.
pub const EXIT_CODES: &str = "  0  fleet: the fleet was printed, complete or partial
  1  fleet: the spec or its ticket list couldn't be read; nothing was printed
";

/// `fleet`'s arguments.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FleetArgs {
    pub spec: Number,
    pub json: bool,
}

/// `<spec> [--json]`, in either order: a spec number of 1 or more, written
/// plainly.
pub fn parse(args: &[OsString]) -> Result<FleetArgs, String> {
    let mut spec = None;
    let mut json = false;
    for arg in args {
        let arg = arg
            .to_str()
            .ok_or_else(|| "fleet: an argument is not UTF-8".to_owned())?;
        if arg == "--json" {
            if json {
                return Err("fleet: --json given twice".to_owned());
            }
            json = true;
        } else if arg.starts_with('-') {
            return Err("fleet: unknown option".to_owned());
        } else if spec.is_some() {
            return Err("fleet: one spec only".to_owned());
        } else {
            spec = Some(spec_number(arg).ok_or_else(|| {
                "fleet: <spec> must be an issue number: 1 to 10 digits, no leading zero".to_owned()
            })?);
        }
    }
    let spec = spec.ok_or_else(|| "fleet: which spec? (openwiz fleet <spec>)".to_owned())?;
    Ok(FleetArgs { spec, json })
}

fn spec_number(text: &str) -> Option<Number> {
    let plain = !text.is_empty()
        && text.len() <= 10
        && !text.starts_with('0')
        && text.bytes().all(|b| b.is_ascii_digit());
    plain.then(|| text.parse().ok()).flatten()
}

/// The `openwiz` program's `fleet`, given the arguments after it.
pub fn run(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    if args.first().is_some_and(|a| a == "tick" || a == "due") {
        return tick::run(args, stdout, stderr);
    }
    run_with(
        &Tickets::from_path(),
        &FleetAgents(CloudRoomSource::from_path()),
        &SystemClock,
        RUN_BUDGET,
        args,
        stdout,
        stderr,
    )
}

/// Connects A6's adapter reads and pure placement to the fleet operation.
struct FleetAgents(CloudRoomSource);

impl Agents for FleetAgents {
    fn read(&self, repository: Option<&RepositoryAnswer>, deadline: Instant) -> AgentReads {
        let repository =
            repository.and_then(|r| cloudroom::Repository::parse(r.name_with_owner.as_str()));
        let Some(repository) = repository else {
            // The version is independent; selecting projects requires this
            // repository's verified identity. Never guess from its name alone.
            let version = cloudroom::version(&self.0, deadline);
            let projects = ListOutcome::Failed(Failed {
                gap: GapKind::BudgetExhausted,
                reason: NonEmpty::new("not read: the repository couldn't be read or identified")
                    .expect("the reason is not empty"),
            });
            return AgentReads {
                version,
                threads: cloudroom::threads(&self.0, &projects, deadline),
                projects,
                workspaces: Vec::new(),
            };
        };
        let reads = cloudroom::read(&self.0, &repository, deadline);
        AgentReads {
            version: reads.version,
            projects: reads.projects,
            threads: reads.threads,
            workspaces: reads.workspaces,
        }
    }

    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed {
        let placements = agents::place(spec, reads)
            .expect("the fleet operation records every placement read exactly once");
        Placed {
            builders: tickets.iter().map(|&t| placements.builder(t)).collect(),
            unplaced: placements.unplaced(),
        }
    }
}

/// [`run`] with its GitHub source, agents, clock and budget given.
pub fn run_with(
    github: &dyn GitHub,
    agents: &dyn Agents,
    clock: &dyn Clock,
    budget: Duration,
    args: &[OsString],
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let args = match parse(args) {
        Ok(args) => args,
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: {why} (see openwiz --help)");
            return EXIT_USAGE;
        }
    };
    let envelope = tickets::fleet(
        FleetRequest { spec: args.spec },
        github,
        agents,
        TestedVersions {
            github: TESTED_VERSION,
            cloudroom: openwiz_adapter_cloudroom::TESTED_VERSION,
        },
        clock,
        budget,
    );
    if let Some(why) = tickets::fleet_unreadable(&envelope) {
        let _ = writeln!(
            stderr,
            "openwiz: fleet: #{}'s tickets couldn't be read ({}): {}",
            args.spec,
            gap_name(why.gap),
            crate::clean(why.reason.as_str())
        );
        return EXIT_READ_FAILED;
    }
    let text = if args.json {
        let mut text = serde_json::to_string_pretty(&envelope)
            .unwrap_or_else(|e| format!("{{\"error\": \"{e}\"}}"));
        text.push('\n');
        text
    } else {
        render(&envelope)
    };
    if stdout.write_all(text.as_bytes()).is_err() {
        return EXIT_READ_FAILED;
    }
    EXIT_OK
}

/// The contract's name of a gap.
fn gap_name(gap: GapKind) -> String {
    serde_json::to_value(gap)
        .ok()
        .and_then(|v| v.as_str().map(str::to_owned))
        .unwrap_or_default()
}

const NOT_READ: &str = "not read";

/// The text of `openwiz fleet <spec>`: the same facts as `--json`.
pub fn render(envelope: &Envelope) -> String {
    let View::Fleet(view) = &envelope.data else {
        return String::new();
    };
    let reads = Records::new(&envelope.reads);
    let mut out = String::new();
    let spec = view.fleet.spec;
    match reads.issue(view.fleet.issue) {
        Some(issue) => {
            let _ = writeln!(out, "fleet #{spec}: {}", crate::clean(&issue.title));
            let _ = writeln!(out, "version: {}", milestone(issue));
        }
        None => {
            let _ = writeln!(out, "fleet #{spec}: {NOT_READ}");
        }
    }
    let _ = writeln!(out, "progress: {}", progress(&view.fleet.progress));
    let _ = writeln!(out, "needs you: {}", needs_you(&view.needs_you));
    for ticket in &view.tickets {
        let t = &ticket.core;
        let issue = reads.issue(t.issue);
        let title = issue.map_or(NOT_READ.to_owned(), |i| crate::clean(&i.title));
        let _ = writeln!(out, "\n#{}  {}  {title}", t.number, state(&t.state));
        let _ = writeln!(out, "  pull request: {}", pull_request(&reads, t));
        let mut blockers = match reads.list(t.blocked_by) {
            Some([]) => "none".to_owned(),
            Some(numbers) => numbers
                .iter()
                .map(|b| blocker(view, &reads, *b))
                .collect::<Vec<_>>()
                .join(", "),
            None => NOT_READ.to_owned(),
        };
        if !reads.complete(t.blocked_by) && reads.list(t.blocked_by).is_some() {
            blockers.push_str("; and more, not read (GitHub listed only these)");
        }
        let _ = writeln!(out, "  blocked by: {blockers}");
        let line = |value: Option<&NonEmpty>| {
            value.map_or(
                "unknown (not exactly one such line in its body)".to_owned(),
                |v| crate::clean(v.as_str()),
            )
        };
        match issue {
            Some(issue) => {
                let _ = writeln!(out, "  owned paths: {}", line(issue.owned_paths.as_ref()));
                let _ = writeln!(out, "  relies on: {}", line(issue.relies_on.as_ref()));
            }
            None => {
                let _ = writeln!(out, "  owned paths: {NOT_READ}");
                let _ = writeln!(out, "  relies on: {NOT_READ}");
            }
        }
        // A builder is shown only when the chain could be worked out; the
        // agents line below says when it couldn't.
        match &ticket.builder {
            WorkedOut::Known(Some(thread)) => {
                let _ = writeln!(out, "  builder: {}", crate::clean(thread.as_str()));
            }
            WorkedOut::Known(None) => {
                let _ = writeln!(out, "  builder: none placed");
            }
            WorkedOut::Unread(_) => {}
        }
    }
    let agents = match &view.unplaced {
        WorkedOut::Known(threads) if threads.is_empty() => "every thread placed".to_owned(),
        WorkedOut::Known(threads) => {
            let threads: Vec<String> = threads
                .iter()
                .map(|u| {
                    format!(
                        "{} ({})",
                        crate::clean(u.thread.as_str()),
                        unplaced_word(u.reason)
                    )
                })
                .collect();
            format!("unplaced: {}", threads.join(", "))
        }
        WorkedOut::Unread(ids) => format!("unknown ({})", unread(ids)),
    };
    let _ = writeln!(out, "\nagents: {agents}");
    let github = &envelope.sources.github;
    let _ = writeln!(
        out,
        "gh {} ({}, live-tested {})",
        reads.version(github.version).unwrap_or(NOT_READ),
        if github.version_tested {
            "tested"
        } else {
            "untested"
        },
        crate::clean(&github.tested_version),
    );
    let incomplete: Vec<String> = envelope
        .reads
        .iter()
        .filter_map(|read| incomplete(read).map(|why| format!("  {} {why}", String::from(read.id))))
        .collect();
    match envelope.coverage.state {
        Completeness::Complete => {
            let _ = writeln!(out, "complete: every read was complete");
        }
        Completeness::Partial => {
            let _ = writeln!(out, "partial: {} reads incomplete", incomplete.len());
            for line in incomplete {
                let _ = writeln!(out, "{line}");
            }
        }
    }
    out
}

fn unplaced_word(reason: UnplacedReason) -> &'static str {
    match reason {
        UnplacedReason::NoBranch => "no branch",
        UnplacedReason::SharedBranch => "a shared branch",
        UnplacedReason::NoPullRequest => "no pull request",
        UnplacedReason::SeveralTickets => "several tickets",
        UnplacedReason::SeveralIssues => "its pull request closes several issues",
    }
}

fn milestone(issue: &Issue) -> String {
    issue
        .milestone
        .as_ref()
        .map_or("none".to_owned(), |m| crate::clean(&m.title))
}

fn state(state: &State) -> String {
    match state {
        State::Known(s) => state_word(*s).to_owned(),
        State::Unknown(why) => format!("unknown ({})", crate::clean(why.as_str())),
        State::Unread(ids) => format!("unknown ({})", unread(ids)),
    }
}

fn state_word(state: TicketState) -> &'static str {
    match state {
        TicketState::Ready => "ready",
        TicketState::Building => "building",
        TicketState::InReview => "in review",
        TicketState::ChangesRequested => "changes requested",
        TicketState::Merged => "merged",
        TicketState::Held => "held",
        TicketState::Blocked => "blocked",
    }
}

fn unread(ids: &[ReadId]) -> String {
    let ids: Vec<String> = ids.iter().map(|&id| String::from(id)).collect();
    format!("not read: {}", ids.join(", "))
}

fn progress(progress: &WorkedOut<Counts>) -> String {
    match progress {
        WorkedOut::Known(c) => format!(
            "{} of {} merged; {} ready, {} building, {} in review, {} changes requested, \
             {} held, {} blocked, {} unknown",
            c.merged,
            c.tickets,
            c.ready,
            c.building,
            c.in_review,
            c.changes_requested,
            c.held,
            c.blocked,
            c.unknown
        ),
        WorkedOut::Unread(ids) => format!("unknown ({})", unread(ids)),
    }
}

fn needs_you(items: &WorkedOut<Vec<NeedsYou>>) -> String {
    match items {
        WorkedOut::Known(items) if items.is_empty() => "none".to_owned(),
        WorkedOut::Known(items) => items
            .iter()
            .map(|item| {
                let kind = match item.kind {
                    NeedsYouKind::NeedsInfo => "needs info",
                    NeedsYouKind::Held => "held",
                };
                format!("#{} {kind}", item.ticket)
            })
            .collect::<Vec<_>>()
            .join(", "),
        WorkedOut::Unread(ids) => format!("unknown ({})", unread(ids)),
    }
}

fn pull_request(reads: &Records<'_>, t: &TicketCore) -> String {
    match reads.pull_request(t.pr) {
        None => NOT_READ.to_owned(),
        Some(None) => "none".to_owned(),
        Some(Some(PullRequest::Several { numbers })) => {
            let numbers: Vec<String> = numbers.iter().map(|n| format!("#{n}")).collect();
            format!(
                "several pull requests ({}): none is its own",
                numbers.join(", ")
            )
        }
        Some(Some(PullRequest::Merged(pr))) => {
            let base = crate::clean(pr.fields.base_branch.as_str());
            let read_back = match t.on_base.and_then(|id| reads.on_base(id)) {
                Some(true) => format!("merge read back on {base}"),
                Some(false) => format!("merge NOT found on {base}"),
                None => format!("merge on {base} {NOT_READ}"),
            };
            format!("#{} merged on GitHub; {read_back}", pr.fields.number)
        }
        Some(Some(PullRequest::Open(pr))) => {
            let draft = if pr.draft { "draft" } else { "open" };
            let ci = match t.ci.and_then(|id| reads.checks(id)) {
                Some(checks) => ci_word(checks).to_owned(),
                None => NOT_READ.to_owned(),
            };
            let verdict = match t.review.and_then(|id| reads.review(id)) {
                Some(Some(review)) => {
                    let word = match review.verdict {
                        Verdict::Approve => "APPROVE",
                        Verdict::Changes => "CHANGES",
                    };
                    let on = if review.commit == pr.head_commit {
                        "on its head"
                    } else {
                        "on an older commit"
                    };
                    format!("{word} {on}")
                }
                Some(None) => "none".to_owned(),
                None => NOT_READ.to_owned(),
            };
            format!("#{} {draft}; CI {ci}; verdict {verdict}", pr.number)
        }
    }
}

fn ci_word(checks: &[Check]) -> &'static str {
    match tickets::ci(checks) {
        Ci::Failed => "failed",
        Ci::Pending => "pending",
        Ci::Passed => "passed",
        Ci::None => "none",
    }
}

/// A blocker: whether it merged, and its version when it isn't this
/// fleet's.
fn blocker(view: &FleetView, reads: &Records<'_>, b: Number) -> String {
    let Some(entry) = view.blockers.iter().find(|x| x.number == b) else {
        return format!("#{b}");
    };
    let merged = match entry.merged {
        WorkedOut::Known(true) => "merged",
        WorkedOut::Known(false) => "not merged",
        WorkedOut::Unread(_) => "merged unknown",
    };
    let place = match &entry.fleet {
        WorkedOut::Known(Some(_)) => "this fleet".to_owned(),
        _ => match reads.issue(entry.issue) {
            Some(issue) => format!("version {}", milestone(issue)),
            None => format!("version {NOT_READ}"),
        },
    };
    format!("#{b} {merged} ({place})")
}

/// Why a read is incomplete: its gap and reason; `None` when complete.
fn incomplete(read: &Read) -> Option<String> {
    let failed = |why: &Failed| {
        Some(format!(
            "{}: {}",
            gap_name(why.gap),
            crate::clean(why.reason.as_str())
        ))
    };
    match &read.kind {
        ReadKind::Version { outcome, .. } | ReadKind::Workspace { outcome, .. } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::Repository { outcome } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::Issue { outcome, .. } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::PrDiscovery { outcome, .. } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::Comments { outcome, .. } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::MergeReadback { outcome, .. } => match outcome {
            Outcome::Failed(why) => failed(why),
            Outcome::Complete { .. } => None,
        },
        ReadKind::SpecList { outcome }
        | ReadKind::SubIssues { outcome, .. }
        | ReadKind::BlockedBy { outcome, .. } => list_incomplete(outcome),
        ReadKind::Checks { outcome, .. } => list_incomplete(outcome),
        ReadKind::Projects { outcome } => list_incomplete(outcome),
        ReadKind::Threads { outcome } => list_incomplete(outcome),
    }
}

fn list_incomplete<T>(outcome: &ListOutcome<T>) -> Option<String> {
    match outcome {
        ListOutcome::Complete { .. } => None,
        ListOutcome::Partial { reason, .. } => {
            Some(format!("truncated: {}", crate::clean(reason.as_str())))
        }
        ListOutcome::Failed(why) => Some(format!(
            "{}: {}",
            gap_name(why.gap),
            crate::clean(why.reason.as_str())
        )),
    }
}
