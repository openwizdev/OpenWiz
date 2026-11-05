//! Ready-stock policy over independently read facts. No I/O or work authority.
use super::model::*;

/// One ticket's original source facts. PR matching is plan-links' title measure,
/// never closing references or active inventory. An explicitly unread capacity fact stays unknown.
#[derive(Clone, Debug)]
pub struct TicketFacts {
    pub number: u64,
    pub open: Fact<bool>,
    pub merged: Fact<bool>,
    pub labels: Fact<Vec<String>>,
    pub start_recorded: Fact<bool>,
    pub matching_open_pr: Fact<bool>,
    pub blockers_merged: Fact<bool>,
    /// None: no existing source reports a refusal; no new capacity source is required.
    pub capacity_refused: Option<Fact<bool>>,
}
#[derive(Clone, Debug)]
pub struct ProjectFacts {
    pub project: Id,
    pub coverage: Coverage,
    /// Oldest required source snapshot, not request assembly time.
    pub snapshot_at: Fact<u64>,
    pub tickets: Fact<Vec<TicketFacts>>,
    pub last_good: Option<StockSample>,
}

pub fn text(s: &str) -> Text {
    Text::new(s).expect("nonempty stock reason")
}
pub fn unknown<T>(s: &str) -> Fact<T> {
    Fact::Unknown(text(s))
}
pub fn gap(coverage: &mut Coverage, why: &str) {
    coverage.state = CoverageState::Partial;
    let found = Gap {
        source: SourceOwner::Plan,
        reason: text(why),
    };
    if !coverage.gaps.contains(&found) {
        coverage.gaps.push(found);
    }
}
pub fn freshness(at: Fact<u64>, now: u64) -> Freshness {
    match at {
        Fact::Known(t) if t <= now => Freshness {
            state: if now - t <= 70_000 {
                FreshnessState::Fresh
            } else {
                FreshnessState::Stale
            },
            snapshot_at: Fact::Known(t),
        },
        _ => Freshness {
            state: FreshnessState::Unknown,
            snapshot_at: unknown("Required source time is missing or in the future"),
        },
    }
}

fn empty_counts() -> StockCounts {
    StockCounts {
        ready: 0,
        running: 0,
        blocked: 0,
        held: 0,
        unapproved: 0,
        owner_wait: 0,
        capacity_wait: 0,
        unknown: 0,
        state: StockState::RunningDry,
    }
}
fn finish(c: &mut StockCounts) {
    c.state = if c.unknown > 0 {
        StockState::Indeterminate
    } else if c.ready == 0 {
        StockState::RunningDry
    } else if c.running == 0 {
        StockState::NoBuilders
    } else if u128::from(c.ready) >= 2 * u128::from(c.running) {
        StockState::Fed
    } else {
        StockState::LowStock
    };
}
fn known<T>(f: &Fact<T>) -> Result<&T, String> {
    match f {
        Fact::Known(v) => Ok(v),
        Fact::Unknown(why) => Err(why.as_str().to_owned()),
    }
}
fn bucket(t: &TicketFacts) -> Result<Option<usize>, String> {
    if !*known(&t.open)? {
        return if *known(&t.merged)? {
            Ok(None)
        } else {
            Err("Closed ticket has no verified merge".into())
        };
    }
    let labels = known(&t.labels)?;
    let has = |l: &str| labels.iter().any(|s| s == l);
    let approved = ["ready-for-agent", "ready-for-human", "held", "needs-info"]
        .iter()
        .any(|l| has(l));
    if !approved {
        return Ok(Some(4));
    }
    // A positive source on either side establishes a builder. Otherwise both
    // negatives are required before classifying any lower bucket.
    if t.start_recorded == Fact::Known(true) || t.matching_open_pr == Fact::Known(true) {
        return Ok(Some(1));
    }
    known(&t.start_recorded)?;
    known(&t.matching_open_pr)?;
    if has("held") {
        return Ok(Some(3));
    }
    if has("needs-info") || has("ready-for-human") {
        return Ok(Some(5));
    }
    if !*known(&t.blockers_merged)? {
        return Ok(Some(2));
    }
    if let Some(refused) = &t.capacity_refused
        && *known(refused)?
    {
        return Ok(Some(6));
    }
    Ok(Some(0))
}

pub fn project(input: ProjectFacts, now: u64) -> ProjectStock {
    let mut coverage = input.coverage;
    let fresh = freshness(input.snapshot_at, now);
    if fresh.state == FreshnessState::Unknown {
        gap(
            &mut coverage,
            "Required source time is missing or in the future",
        );
    }
    if !coverage.gaps.is_empty() {
        coverage.state = CoverageState::Partial;
    }
    if coverage.state == CoverageState::Partial && coverage.gaps.is_empty() {
        gap(&mut coverage, "Project source enumeration is incomplete");
    }
    let counts = match input.tickets {
        Fact::Unknown(why) => {
            gap(&mut coverage, why.as_str());
            Fact::Unknown(why)
        }
        Fact::Known(tickets) => {
            let mut counts = [0u64; 8];
            let mut seen = std::collections::BTreeSet::new();
            // Duplicate identities invalidate the enumeration, not two tickets.
            let duplicate = tickets
                .iter()
                .any(|t| t.number == 0 || !seen.insert(t.number));
            if duplicate {
                gap(&mut coverage, "Ticket identities are missing or repeated");
                unknown("Ticket enumeration is ambiguous")
            } else {
                for t in &tickets {
                    match bucket(t) {
                        Ok(Some(i)) => counts[i] += 1,
                        Ok(None) => {}
                        Err(why) => {
                            counts[7] += 1;
                            gap(&mut coverage, &why);
                        }
                    }
                }
                let [
                    ready,
                    running,
                    blocked,
                    held,
                    unapproved,
                    owner_wait,
                    capacity_wait,
                    unknown,
                ] = counts;
                let mut c = StockCounts {
                    ready,
                    running,
                    blocked,
                    held,
                    unapproved,
                    owner_wait,
                    capacity_wait,
                    unknown,
                    state: StockState::Indeterminate,
                };
                finish(&mut c);
                Fact::Known(c)
            }
        }
    };
    let last_good = input.last_good.filter(|sample| {
        let valid = sample.snapshot_at <= now
            && sample.counts.check().is_ok()
            && sample.counts.unknown == 0;
        if !valid {
            gap(&mut coverage, "Last-good stock sample is invalid");
        }
        valid
    });
    ProjectStock {
        project: input.project,
        coverage,
        freshness: fresh,
        counts,
        last_good,
    }
}

/// Combine every configured project. The caller must retain missing projects
/// and supply the original project-enumeration snapshot and coverage.
pub fn factory(
    mut projects: Vec<ProjectStock>,
    mut coverage: Coverage,
    at: Fact<u64>,
    now: u64,
) -> Stock {
    let mut seen = std::collections::BTreeSet::new();
    let mut repeated = std::collections::BTreeSet::new();
    projects.retain(|p| {
        if seen.insert(p.project.clone()) {
            true
        } else {
            gap(&mut coverage, "Configured project identities are repeated");
            repeated.insert(p.project.clone());
            false
        }
    });
    for p in &mut projects {
        if repeated.contains(&p.project) {
            gap(&mut p.coverage, "Configured project readings are ambiguous");
            p.counts = unknown("Configured project readings are ambiguous");
        }
    }
    // Validate each required time before taking a minimum: an older project
    // timestamp must never hide a future discovery timestamp.
    let mut oldest = match at {
        Fact::Known(t) if t <= now => Fact::Known(t),
        _ => {
            gap(
                &mut coverage,
                "Configured project discovery time is missing or in the future",
            );
            unknown("Configured project discovery time is invalid")
        }
    };
    for p in &projects {
        for g in &p.coverage.gaps {
            coverage.state = CoverageState::Partial;
            if !coverage.gaps.contains(g) {
                coverage.gaps.push(g.clone());
            }
        }
        if p.coverage.state == CoverageState::Partial {
            gap(&mut coverage, "Required project facts are incomplete");
        }
        if !matches!(p.counts, Fact::Known(ref c) if c.unknown == 0) {
            gap(&mut coverage, "Required project counts are unknown");
        }
        oldest = match (oldest, &p.freshness.snapshot_at) {
            (Fact::Known(a), Fact::Known(b)) if *b <= now => Fact::Known(a.min(*b)),
            _ => unknown("A required source snapshot is unknown"),
        };
    }
    let fresh = freshness(oldest, now);
    if fresh.state == FreshnessState::Unknown {
        gap(&mut coverage, "A required source snapshot is unknown");
    }
    if !coverage.gaps.is_empty() {
        coverage.state = CoverageState::Partial;
    }
    if coverage.state == CoverageState::Partial && coverage.gaps.is_empty() {
        gap(
            &mut coverage,
            "Configured project enumeration is incomplete",
        );
    }
    let mut sum = empty_counts();
    let mut overflow = false;
    for p in &projects {
        if let Fact::Known(c) = &p.counts {
            for (target, n) in [
                &mut sum.ready,
                &mut sum.running,
                &mut sum.blocked,
                &mut sum.held,
                &mut sum.unapproved,
                &mut sum.owner_wait,
                &mut sum.capacity_wait,
                &mut sum.unknown,
            ]
            .into_iter()
            .zip([
                c.ready,
                c.running,
                c.blocked,
                c.held,
                c.unapproved,
                c.owner_wait,
                c.capacity_wait,
                c.unknown,
            ]) {
                match target.checked_add(n) {
                    Some(value) => *target = value,
                    None => overflow = true,
                }
            }
        }
    }
    if overflow {
        gap(&mut coverage, "Factory count exceeds the supported bound");
    }
    finish(&mut sum);
    let totals =
        if coverage.state == CoverageState::Complete && fresh.state == FreshnessState::Fresh {
            Fact::Known(sum)
        } else {
            unknown("Current factory totals require complete fresh project facts")
        };
    Stock {
        coverage,
        freshness: fresh,
        projects,
        totals,
    }
}
