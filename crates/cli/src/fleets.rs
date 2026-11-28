use std::collections::HashMap;
use std::ffi::OsString;
use std::io::Write;
use std::time::Duration;

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::fleet::fleets::{FleetsSource, fleets};
use openwiz_core::fleet::model::{
    Envelope, Fleet, FleetsView, Issue, ListOutcome, NeedsYouKind, Number, Outcome, Read, ReadId,
    ReadKind, SourceName, State, TicketCore, View, WorkedOut,
};
use openwiz_core::limits::RUN_BUDGET;
use openwiz_core::ops::Clock;

use crate::{EXIT_OK, EXIT_USAGE, SystemClock, clean, utc};

pub const USAGE: &str = "  openwiz fleets [--json]\n";

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

pub const EXIT_CODES: &str =
    "  0  fleets: every fleet was printed, complete or partial (its gaps say what is missing)\n";

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
    let mut tickets_by_number: HashMap<Number, &TicketCore> =
        HashMap::with_capacity(view.tickets.len());
    for ticket in &view.tickets {
        tickets_by_number.entry(ticket.number).or_insert(ticket);
    }
    out.push_str("\nfleets\n");
    if view.fleets.is_empty() {
        out.push_str("  none listed\n");
    }
    for fleet in &view.fleets {
        push_fleet(&mut out, fleet, &tickets_by_number, &reads);
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

fn push_fleet(
    out: &mut String,
    fleet: &Fleet,
    tickets_by_number: &HashMap<Number, &TicketCore>,
    reads: &Reads,
) {
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
    let tickets: &[Number] = match reads.kind(fleet.tickets) {
        Some(ReadKind::SubIssues { outcome, .. }) => match outcome {
            ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => {
                value.as_slice()
            }
            ListOutcome::Failed(_) => &[],
        },
        _ => &[],
    };
    for &number in tickets {
        let Some(ticket) = tickets_by_number.get(&number) else {
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

struct Reads<'a>(&'a [Read]);

impl Reads<'_> {
    fn kind(&self, id: ReadId) -> Option<&ReadKind> {
        if let Some(slot) = id.0.checked_sub(1).and_then(|i| usize::try_from(i).ok())
            && let Some(read) = self.0.get(slot)
            && read.id == id
        {
            return Some(&read.kind);
        }
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

fn gap_kind(kind: GapKind) -> String {
    serde_json::to_value(kind)
        .ok()
        .and_then(|v| v.as_str().map(str::to_owned))
        .unwrap_or_default()
}

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

#[cfg(test)]
mod render_oracle {
    use super::*;
    use openwiz_core::fleet::model::{
        Counts, Coverage, Freshness, Gh, GitHubSource, IssueState, Milestone, NonEmpty, Repository,
        SchemaId, Sources, TicketState,
    };
    use openwiz_core::model::Timestamp;

    fn old_kind(reads: &[Read], id: ReadId) -> Option<&ReadKind> {
        reads.iter().find(|r| r.id == id).map(|r| &r.kind)
    }

    fn old_render(envelope: &Envelope) -> String {
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
            let title = match old_kind(&envelope.reads, fleet.issue) {
                Some(ReadKind::Issue {
                    outcome: Outcome::Complete { value: issue },
                    ..
                }) => {
                    let milestone = issue
                        .milestone
                        .as_ref()
                        .map(|m| format!(" ({})", clean(&m.title)))
                        .unwrap_or_default();
                    format!("{}{milestone}", clean(&issue.title))
                }
                _ => format!("(title unread: {})", id_text(fleet.issue)),
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
            let tickets = match old_kind(&envelope.reads, fleet.tickets) {
                Some(ReadKind::SubIssues { outcome, .. }) => match outcome {
                    ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => {
                        value.clone()
                    }
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

    #[test]
    fn indexed_render_matches_linear_scan_oracle_including_out_of_order_and_duplicate_tickets() {
        let n = |v: u64| Number::new(v).unwrap();
        let ne = |s: &str| NonEmpty::new(s).unwrap();
        let mut reads = vec![
            Read {
                id: ReadId(9),
                kind: ReadKind::Version {
                    source: SourceName::Github,
                    outcome: Outcome::Complete {
                        value: ne("2.100.0"),
                    },
                },
            },
            Read {
                id: ReadId(2),
                kind: ReadKind::Repository {
                    outcome: Outcome::Complete {
                        value: Repository {
                            name: ne("example"),
                        },
                    },
                },
            },
            Read {
                id: ReadId(1),
                kind: ReadKind::Issue {
                    issue: n(1),
                    outcome: Outcome::Complete {
                        value: Issue {
                            title: "spec: Synthetic".to_owned(),
                            state: IssueState::Open,
                            milestone: Some(Milestone {
                                number: n(1),
                                title: "0.2.0".to_owned(),
                            }),
                            labels: vec![],
                            owned_paths: None,
                            relies_on: None,
                            pending_question: None,
                        },
                    },
                },
            },
            Read {
                id: ReadId(4),
                kind: ReadKind::SubIssues {
                    spec: n(1),
                    outcome: ListOutcome::Complete {
                        value: vec![n(2), n(3), n(4)],
                    },
                },
            },
            Read {
                id: ReadId(5),
                kind: ReadKind::SpecList {
                    outcome: ListOutcome::Complete { value: vec![n(1)] },
                },
            },
        ];
        let tickets = vec![
            TicketCore {
                number: n(2),
                state: State::Unknown(ne("first duplicate wins")),
                issue: ReadId(1),
                blocked_by: ReadId(4),
                pr: ReadId(5),
                ci: None,
                review: None,
                on_base: None,
            },
            TicketCore {
                number: n(2),
                state: State::Known(TicketState::Merged),
                issue: ReadId(1),
                blocked_by: ReadId(4),
                pr: ReadId(5),
                ci: None,
                review: None,
                on_base: None,
            },
            TicketCore {
                number: n(3),
                state: State::Unread(vec![ReadId(9), ReadId(2)]),
                issue: ReadId(1),
                blocked_by: ReadId(4),
                pr: ReadId(5),
                ci: None,
                review: None,
                on_base: None,
            },
        ];
        for reverse_reads in [false, true] {
            if reverse_reads {
                reads.reverse();
            }
            let env = Envelope {
                schema: SchemaId::V1,
                sources: Sources {
                    github: GitHubSource {
                        name: Gh::Gh,
                        version: ReadId(9),
                        tested_version: "2.100.0".to_owned(),
                        version_tested: true,
                    },
                    cloudroom: None,
                },
                reads: reads.clone(),
                coverage: Coverage {
                    state: Completeness::Complete,
                },
                freshness: Freshness {
                    snapshot_at: Timestamp(1_793_400_000_000),
                },
                data: View::Fleets(FleetsView {
                    repository: ReadId(2),
                    specs: ReadId(5),
                    fleets: vec![Fleet {
                        spec: n(1),
                        issue: ReadId(1),
                        tickets: ReadId(4),
                        progress: WorkedOut::Known(Counts {
                            tickets: 3,
                            merged: 0,
                            ready: 0,
                            building: 0,
                            in_review: 0,
                            changes_requested: 0,
                            held: 0,
                            blocked: 0,
                            unknown: 2,
                        }),
                    }],
                    tickets: tickets.clone(),
                    blockers: vec![],
                    needs_you: WorkedOut::Known(vec![]),
                }),
            };
            assert_eq!(render(&env), old_render(&env));
        }
    }
}
