//! `openwiz fleets` (OpenWiz 0.0.6, spec 1, A4, ClosedWiz#112): every fleet
//! in the repository with its progress, read from GitHub through the `gh`
//! on `PATH` ([`GitHubFleets`]) and worked out by the core
//! ([`openwiz_core::fleet::fleets`]). Read-only, and no CloudRoom read.
//!
//! Its usage line, its `--help` section and its exit codes are here too,
//! so `main.rs` and `lib.rs` hold only their places.

use std::ffi::OsString;
use std::io::Write;
use std::time::Duration;

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::fleet::fleets::{FleetsSource, fleets};
use openwiz_core::fleet::model::{
    Envelope, Fleet, FleetsView, Issue, ListOutcome, NeedsYouKind, Outcome, Read, ReadId, ReadKind,
    SourceName, State, View, WorkedOut,
};
use openwiz_core::limits::RUN_BUDGET;
use openwiz_core::ops::Clock;

use crate::{EXIT_OK, EXIT_USAGE, SystemClock, clean, utc};

/// Its line in `openwiz --help`'s usage.
pub const USAGE: &str = "  openwiz fleets [--json]\n";

/// Its section of `openwiz --help`.
pub const HELP: &str = "fleets
  Every fleet in this repository: each open issue with sub-issues (a spec), its tickets
  and their blockers, read from GitHub through the gh on PATH, in the repository gh finds
  from the current directory. Each ticket's state is worked out from facts only, and each
  fleet shows its progress: its tickets by state, \"4 of 11 merged\", and how many are
  moving (building, in review or changes requested) or blocked. \"Needs you\" lists each
  ticket with a needs-info or held label. Merged means its pull request's merge was read
  back on its base, never an approval, a ready pull request or a closed issue. What it
  can't settle is unknown, with its reason, and a read that fails makes the result
  partial: its gaps name each read that isn't complete. Read-only: only gh's reads on
  OpenWiz's allowlist run, never room-cli, and the version is reported, never a gate.
  --json      print the openwiz.fleet.v1 envelope (its fleets view) instead of text
";

/// Its lines in `openwiz --help`'s exit codes.
pub const EXIT_CODES: &str =
    "  0  fleets: every fleet was printed, complete or partial (its gaps say what is missing)\n";

/// The `openwiz` program's `fleets`, given the arguments after it: the
/// `gh` on `PATH`, the system clock and the run budget.
pub fn run(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    run_with(
        args,
        &GitHubFleets::from_path(),
        &SystemClock,
        RUN_BUDGET,
        stdout,
        stderr,
    )
}

/// [`run`] with its source, clock and budget given, for the tests.
pub fn run_with(
    args: &[OsString],
    source: &dyn FleetsSource,
    clock: &dyn Clock,
    budget: Duration,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let json = match parse(args) {
        Ok(Parsed::Help) => {
            let _ = stdout.write_all(
                crate::response::help(
                    crate::response::Request::for_command("fleets", args).json,
                    crate::help(),
                )
                .as_bytes(),
            );
            return EXIT_OK;
        }
        Ok(Parsed::Run { json }) => json,
        Err(why) => {
            let _ = writeln!(
                stderr,
                "openwiz: fleets: {why}; nothing was read (see openwiz --help)"
            );
            return EXIT_USAGE;
        }
    };
    let envelope = fleets(source, clock, budget);
    let text = if json {
        let mut text = serde_json::to_string_pretty(&envelope).expect("the envelope serializes");
        text.push('\n');
        text
    } else {
        render(&envelope)
    };
    let _ = stdout.write_all(text.as_bytes());
    let _ = stdout.flush();
    EXIT_OK
}

enum Parsed {
    Help,
    Run { json: bool },
}

/// `[--json]`, or `--help` / `-h` anywhere.
fn parse(args: &[OsString]) -> Result<Parsed, String> {
    let mut json = false;
    let mut parsed = None;
    for arg in args {
        let Some(arg) = arg.to_str() else {
            return Err("an argument is not valid UTF-8".to_owned());
        };
        match arg {
            "--help" | "-h" => return Ok(Parsed::Help),
            "--json" if !json => json = true,
            "--json" => parsed = parsed.or(Some("--json is given twice".to_owned())),
            other if other.starts_with('-') => {
                parsed = parsed.or(Some(format!("unknown option {}", clean(other))));
            }
            _ => {
                parsed = parsed.or(Some(
                    "fleets takes no argument (one fleet is openwiz fleet <spec>)".to_owned(),
                ));
            }
        }
    }
    match parsed {
        Some(why) => Err(why),
        None => Ok(Parsed::Run { json }),
    }
}

/// The text: a header line, "needs you", one block per fleet, and the
/// gaps.
pub fn render(envelope: &Envelope) -> String {
    let View::Fleets(view) = &envelope.data else {
        unreachable!("fleets prints the fleets view")
    };
    let reads = Reads(&envelope.reads);
    let mut out = header(envelope, view, &reads);
    out.push_str("\nneeds you\n");
    match &view.needs_you {
        WorkedOut::Known(items) if items.is_empty() => out.push_str("  nothing\n"),
        WorkedOut::Known(items) => {
            for item in items {
                let kind = match item.kind {
                    NeedsYouKind::NeedsInfo => "needs-info",
                    NeedsYouKind::Held => "held",
                };
                out.push_str(&format!(
                    "  #{} {kind}, in fleet #{}\n",
                    item.ticket, item.spec
                ));
            }
        }
        WorkedOut::Unread(ids) => out.push_str(&format!("  unread: {}\n", ids_text(ids))),
    }
    out.push_str("\nfleets\n");
    if view.fleets.is_empty() {
        out.push_str("  none listed\n");
    }
    for fleet in &view.fleets {
        push_fleet(&mut out, fleet, view, &reads);
    }
    let gaps: Vec<&Read> = envelope
        .reads
        .iter()
        .filter(|r| gap(&r.kind).is_some())
        .collect();
    if !gaps.is_empty() {
        out.push_str("\ngaps\n");
        for read in gaps {
            let (state, kind, reason) = gap(&read.kind).expect("an incomplete read");
            out.push_str(&format!(
                "  {} {}: {state} ({kind}): {}\n",
                id_text(read.id),
                subject(&read.kind),
                clean(reason)
            ));
        }
    }
    out
}

/// `openwiz fleets · <repository> · gh <version> (<tested>) · snapshot
/// <time> · <coverage>`.
fn header(envelope: &Envelope, view: &FleetsView, reads: &Reads) -> String {
    let repository = match reads.kind(view.repository) {
        Some(ReadKind::Repository {
            outcome: Outcome::Complete { value },
        }) => clean(value.name.as_str()),
        _ => format!("repository unread ({})", id_text(view.repository)),
    };
    let gh = &envelope.sources.github;
    let version = match reads.kind(gh.version) {
        Some(ReadKind::Version {
            source: SourceName::Github,
            outcome: Outcome::Complete { value },
        }) => clean(value.as_str()),
        _ => format!("version unread ({})", id_text(gh.version)),
    };
    let tested = if gh.version_tested {
        "tested".to_owned()
    } else {
        format!("untested; live-tested: {}", clean(&gh.tested_version))
    };
    let coverage = match envelope.coverage.state {
        Completeness::Complete => "complete".to_owned(),
        Completeness::Partial => {
            let n = envelope
                .reads
                .iter()
                .filter(|r| gap(&r.kind).is_some())
                .count();
            format!("partial, {n} gaps")
        }
    };
    format!(
        "openwiz fleets · {repository} · gh {version} ({tested}) · snapshot {} · {coverage}\n",
        utc(envelope.freshness.snapshot_at)
    )
}

/// `#<spec> <title> (<milestone>): <n> of <m> merged, <k> moving, <b>
/// blocked`, the counts by state, and each ticket whose state is unknown
/// or unread.
fn push_fleet(out: &mut String, fleet: &Fleet, view: &FleetsView, reads: &Reads) {
    let title = match reads.issue(fleet.issue) {
        Some(issue) => {
            let milestone = issue
                .milestone
                .as_ref()
                .map(|m| format!(" ({})", clean(&m.title)))
                .unwrap_or_default();
            format!("{}{milestone}", clean(&issue.title))
        }
        None => format!("(title unread: {})", id_text(fleet.issue)),
    };
    match &fleet.progress {
        WorkedOut::Known(c) => {
            let moving = c.building + c.in_review + c.changes_requested;
            out.push_str(&format!(
                "  #{} {title}: {} of {} merged, {moving} moving, {} blocked\n",
                fleet.spec, c.merged, c.tickets, c.blocked
            ));
            let parts: Vec<String> = [
                ("ready", c.ready),
                ("building", c.building),
                ("in review", c.in_review),
                ("changes requested", c.changes_requested),
                ("held", c.held),
                ("unknown", c.unknown),
            ]
            .iter()
            .filter(|(_, n)| *n > 0)
            .map(|(name, n)| format!("{name} {n}"))
            .collect();
            if !parts.is_empty() {
                out.push_str(&format!("      {}\n", parts.join(", ")));
            }
        }
        WorkedOut::Unread(ids) => out.push_str(&format!(
            "  #{} {title}: progress unread ({})\n",
            fleet.spec,
            ids_text(ids)
        )),
    }
    let tickets = match reads.kind(fleet.tickets) {
        Some(ReadKind::SubIssues { outcome, .. }) => match outcome {
            ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => value.clone(),
            ListOutcome::Failed(_) => Vec::new(),
        },
        _ => Vec::new(),
    };
    for number in tickets {
        let Some(ticket) = view.tickets.iter().find(|t| t.number == number) else {
            continue;
        };
        match &ticket.state {
            State::Known(_) => {}
            State::Unknown(why) => out.push_str(&format!(
                "      #{number} unknown: {}\n",
                clean(why.as_str())
            )),
            State::Unread(ids) => {
                out.push_str(&format!("      #{number} unread ({})\n", ids_text(ids)));
            }
        }
    }
}

/// The reads, by id.
struct Reads<'a>(&'a [Read]);

impl Reads<'_> {
    fn kind(&self, id: ReadId) -> Option<&ReadKind> {
        self.0.iter().find(|r| r.id == id).map(|r| &r.kind)
    }

    fn issue(&self, id: ReadId) -> Option<&Issue> {
        match self.kind(id)? {
            ReadKind::Issue {
                outcome: Outcome::Complete { value },
                ..
            } => Some(value),
            _ => None,
        }
    }
}

/// An incomplete read's state, gap and reason; `None` when complete.
fn gap(kind: &ReadKind) -> Option<(&'static str, String, &str)> {
    fn one<T>(o: &Outcome<T>) -> Option<(&'static str, String, &str)> {
        match o {
            Outcome::Complete { .. } => None,
            Outcome::Failed(f) => Some(("failed", gap_kind(f.gap), f.reason.as_str())),
        }
    }
    fn many<T>(o: &ListOutcome<T>) -> Option<(&'static str, String, &str)> {
        match o {
            ListOutcome::Complete { .. } => None,
            ListOutcome::Partial { reason, .. } => {
                Some(("partial", "truncated".to_owned(), reason.as_str()))
            }
            ListOutcome::Failed(f) => Some(("failed", gap_kind(f.gap), f.reason.as_str())),
        }
    }
    match kind {
        ReadKind::Version { outcome, .. } | ReadKind::Workspace { outcome, .. } => one(outcome),
        ReadKind::Repository { outcome } => one(outcome),
        ReadKind::Issue { outcome, .. } => one(outcome),
        ReadKind::PrDiscovery { outcome, .. } => one(outcome),
        ReadKind::Comments { outcome, .. } => one(outcome),
        ReadKind::MergeReadback { outcome, .. } => one(outcome),
        ReadKind::SpecList { outcome }
        | ReadKind::SubIssues { outcome, .. }
        | ReadKind::BlockedBy { outcome, .. } => many(outcome),
        ReadKind::Checks { outcome, .. } => many(outcome),
        ReadKind::Projects { outcome } => many(outcome),
        ReadKind::Threads { outcome } => many(outcome),
    }
}

/// A gap kind's contract word, such as `command_failed`.
fn gap_kind(kind: GapKind) -> String {
    serde_json::to_value(kind)
        .ok()
        .and_then(|v| v.as_str().map(str::to_owned))
        .unwrap_or_default()
}

/// What a read read, in the contract's words: `checks #961`.
fn subject(kind: &ReadKind) -> String {
    match kind {
        ReadKind::Version { source, .. } => match source {
            SourceName::Github => "gh's version".to_owned(),
            SourceName::Cloudroom => "room-cli's version".to_owned(),
        },
        ReadKind::Repository { .. } => "the repository".to_owned(),
        ReadKind::SpecList { .. } => "the spec list".to_owned(),
        ReadKind::Issue { issue, .. } => format!("issue #{issue}"),
        ReadKind::SubIssues { spec, .. } => format!("sub-issues of #{spec}"),
        ReadKind::BlockedBy { ticket, .. } => format!("blockers of #{ticket}"),
        ReadKind::PrDiscovery { issue, .. } => format!("pull request of #{issue}"),
        ReadKind::Checks { pr, .. } => format!("checks of pull request #{pr}"),
        ReadKind::Comments { pr, .. } => format!("verdict on pull request #{pr}"),
        ReadKind::MergeReadback { pr, .. } => format!("merge read back of pull request #{pr}"),
        ReadKind::Projects { .. } => "the projects".to_owned(),
        ReadKind::Threads { .. } => "the threads".to_owned(),
        ReadKind::Workspace { thread, .. } => {
            format!("branch of thread {}", clean(thread.as_str()))
        }
    }
}

fn id_text(id: ReadId) -> String {
    String::from(id)
}

fn ids_text(ids: &[ReadId]) -> String {
    ids.iter()
        .map(|id| id_text(*id))
        .collect::<Vec<_>>()
        .join(", ")
}
