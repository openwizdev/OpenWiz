//! Approval fingerprints and append-only fleet records read by B5. No I/O.
use openwiz_adapter_github::tick::{Comment, Event, Result};
use openwiz_core::fleet::fleets::IssueRow;
use openwiz_core::fleet::model::{NonEmpty, Number};
use openwiz_core::fleet::tick::*;
use openwiz_core::messaging::sha256_hex;
use std::collections::{BTreeMap, BTreeSet};

pub fn issue(row: &IssueRow) -> openwiz_core::fleet::model::Issue {
    openwiz_core::fleet::model::Issue {
        title: row.title.clone(),
        state: row.state,
        milestone: row.milestone.clone(),
        labels: row.labels.clone(),
        owned_paths: openwiz_core::fleet::fleets::template_line(&row.body, "**Owned paths:**"),
        relies_on: openwiz_core::fleet::fleets::template_line(&row.body, "**Relies on:**"),
        pending_question: None,
    }
}
pub fn n(s: &str) -> Result<Number> {
    if s.starts_with('0') || !s.bytes().all(|b| b.is_ascii_digit()) {
        return Err("invalid number");
    }
    s.parse().map_err(|_| "invalid number")
}
fn blocker_set(s: &str) -> Result<BTreeSet<Number>> {
    let mut blockers = BTreeSet::new();
    if s == "none" {
        return Ok(blockers);
    }
    for part in s.split(',') {
        let mut tokens = part.split_ascii_whitespace().peekable();
        if tokens.peek().is_none() {
            return Err("empty blocker element");
        }
        for token in tokens {
            let id = n(token.strip_prefix('#').ok_or("invalid blocker")?)?;
            if !blockers.insert(id) {
                return Err("duplicate blocker");
            }
        }
    }
    Ok(blockers)
}
pub fn first(c: &Comment) -> &str {
    c.body.lines().next().unwrap_or("")
}
pub fn has(comments: &[Comment], line: &str) -> bool {
    comments.iter().any(|c| first(c) == line)
}
pub fn lines(comments: &[Comment]) -> impl Iterator<Item = &str> {
    comments.iter().map(first)
}

fn body_hash(body: &str) -> String {
    let mut normalized = String::new();
    for part in body.split_inclusive('\n') {
        let mut line = part.to_owned();
        let b = line.as_bytes();
        let indent = b.iter().take_while(|c| matches!(c, b' ' | b'\t')).count();
        if b.get(indent)
            .is_some_and(|c| matches!(c, b'-' | b'*' | b'+'))
        {
            let mut pos = indent + 1;
            while b.get(pos).is_some_and(|c| matches!(c, b' ' | b'\t')) {
                pos += 1;
            }
            if pos > indent + 1
                && matches!(b.get(pos..pos + 3), Some(b"[x]" | b"[X]"))
                && b.get(pos + 3)
                    .is_none_or(|c| matches!(c, b' ' | b'\t' | b'\r' | b'\n'))
            {
                line.replace_range(pos + 1..pos + 2, " ");
            }
        }
        normalized.push_str(&line);
    }
    normalized.push('\n');
    sha256_hex(normalized.as_bytes())
}
pub fn revision(spec: &IssueRow, rows: &[&IssueRow]) -> String {
    let mut rows = rows.to_vec();
    rows.sort_by_key(|r| r.number);
    let mut text = format!(
        "plan-graph revision v2\nspec #{} body sha256 {}\n",
        spec.number,
        body_hash(&spec.body)
    );
    for row in rows {
        let mut blockers = row
            .blocked_by
            .nodes
            .iter()
            .map(|b| b.number)
            .collect::<Vec<_>>();
        blockers.sort();
        let blocked = if blockers.is_empty() {
            "none".into()
        } else {
            blockers
                .iter()
                .map(|n| format!("#{n}"))
                .collect::<Vec<_>>()
                .join(" ")
        };
        text.push_str(&format!(
            "ticket #{} blocked-by {} body sha256 {} title {}\n",
            row.number,
            blocked,
            body_hash(&row.body),
            row.title
        ));
    }
    text
}
pub fn fingerprint(spec: &IssueRow, rows: &[&IssueRow]) -> Fingerprint {
    Fingerprint::parse(&sha256_hex(revision(spec, rows).as_bytes())).unwrap()
}
fn approval_header(c: &Comment) -> &str {
    c.body
        .lines()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("")
        .trim()
}
// #558/R9: the heading after `:** ` is the user's exact words in double
// quotes, optionally followed by one bracketed source: `"<words>" (<source>)`.
// The words may contain interior quotes; the source may too. Nothing may
// follow the source's closing bracket.
fn approval_words_ok(words: &str) -> bool {
    let (quoted, source) = split_words_and_source(words);
    quoted.len() >= 3
        && quoted.starts_with('"')
        && quoted.ends_with('"')
        && (source.is_empty() || balanced_source(source))
}
// Splits `"<words>" (<source>)` at the closing quote of the words: the
// rightmost `"` whose suffix is whitespace and one balanced `(...)` group.
fn split_words_and_source(words: &str) -> (&str, &str) {
    for (at, _) in words.char_indices().filter(|(_, c)| *c == '"').rev() {
        let rest = &words[at + 1..];
        let source = rest.trim_start_matches([' ', '\t']);
        if source.len() < rest.len() && source.starts_with('(') && balanced_source(source) {
            return (&words[..at + 1], source);
        }
    }
    (words, "")
}
// A bracketed source is one balanced `(...)` group covering the whole suffix,
// with any parentheses inside a quoted region ignored.
fn balanced_source(source: &str) -> bool {
    if !source.starts_with('(') || !source.ends_with(')') {
        return false;
    }
    let mut depth = 0i32;
    let mut in_quote = false;
    for (i, c) in source.char_indices() {
        match c {
            '"' => in_quote = !in_quote,
            '(' if !in_quote => depth += 1,
            ')' if !in_quote => {
                depth -= 1;
                if depth < 0 || (depth == 0 && i != source.len() - 1) {
                    return false;
                }
            }
            _ => {}
        }
    }
    depth == 0 && !in_quote
}
// Match plan-graph's Markdown table boundary, retaining original indexes so
// rows separated by prose or fenced examples cannot become one approval table.
fn approval_table(body: &str) -> Vec<(usize, &str)> {
    let mut fence: Option<(u8, usize)> = None;
    let mut table = vec![];
    for (index, line) in body.lines().enumerate() {
        let tail = line.trim_start_matches(' ');
        let indented = line.len() - tail.len() > 3;
        if let Some((ch, size)) = fence {
            let count = tail.bytes().take_while(|b| *b == ch).count();
            if !indented && count >= size && tail[count..].bytes().all(|b| b == b' ') {
                fence = None;
            }
            continue;
        }
        if !indented && let Some(ch @ (b'`' | b'~')) = tail.bytes().next() {
            let count = tail.bytes().take_while(|b| *b == ch).count();
            if count >= 3 {
                fence = Some((ch, count));
                continue;
            }
        }
        if line.trim_start().starts_with('|') {
            table.push((index, line));
        }
    }
    table
}
pub fn private_repository(repository: &str, metadata: &serde_json::Value) -> bool {
    openwiz_adapter_github::tick::object(metadata, &["nameWithOwner", "isPrivate"]).is_ok()
        && metadata["nameWithOwner"]
            .as_str()
            .is_some_and(|name| name.eq_ignore_ascii_case(repository))
        && metadata["isPrivate"].as_bool() == Some(true)
}

pub fn check_forms(comments: &[Comment], legacy: bool) -> Result<()> {
    if !legacy
        && comments.iter().any(|c| {
            first(c).starts_with("launch-fleet:")
                && (contains_thread_id(&c.body) || first(c).contains(", thread "))
        })
    {
        return Err("private fleet record on public repository");
    }
    Ok(())
}

fn pointer_ok(pointer: &str) -> bool {
    let Some(tail) = pointer.strip_prefix("https://github.com/jparker2006/ClosedWiz/") else {
        return false;
    };
    let tail = tail
        .strip_prefix("issues/")
        .or_else(|| tail.strip_prefix("pull/"));
    tail.and_then(|s| s.split_once("#issuecomment-"))
        .is_some_and(|(issue, comment)| n(issue).is_ok() && n(comment).is_ok())
}
fn attributed_quotes(c: &Comment) -> bool {
    let decider = approval_header(c)
        .strip_prefix("**Plan graph approved by ")
        .and_then(|s| s.split_once(','))
        .map_or("Jake", |(name, _)| name);
    c.body.lines().any(|line| {
        let mut quoted = false;
        let mut since = 0;
        for (at, mark) in line
            .char_indices()
            .filter(|(_, c)| matches!(c, '"' | '“' | '”'))
        {
            if !quoted {
                let prefix = line[since..at].trim_end_matches('\\').trim_end();
                if (prefix.ends_with(':') || prefix.ends_with(":**"))
                    && prefix
                        .split(|c: char| !c.is_alphanumeric() && c != '_')
                        .any(|word| word == "Jake" || word == decider)
                {
                    return true;
                }
            } else {
                since = at + mark.len_utf8();
            }
            quoted = !quoted;
        }
        false
    })
}
fn public_approval_ok(c: &Comment, decision: &str) -> bool {
    let mut lines = c.body.lines();
    let first = lines.next().unwrap_or("");
    let second = lines.next().unwrap_or("");
    !first.trim().is_empty()
        && !decision.trim().is_empty()
        && !decision.contains(['"', '“', '”'])
        && second
            .strip_prefix("Private record: ")
            .is_some_and(pointer_ok)
        && c.body
            .lines()
            .filter(|l| l.starts_with("Private record:"))
            .count()
            == 1
        && !c.body.lines().any(|l| l.trim_start().starts_with('>'))
        && !contains_thread_id(&c.body)
        && !attributed_quotes(c)
}

pub fn approval(comments: &[Comment], legacy: bool) -> Result<Option<PlanApproval>> {
    let Some(c) = comments
        .iter()
        .filter(|c| approval_header(c).starts_with("**Plan graph approved by"))
        .max_by_key(|c| c.id)
    else {
        return Ok(None);
    };
    let header = approval_header(c);
    let (_, rest) = header
        .split_once(", revision ")
        .ok_or("approval has no revision")?;
    let (rev, words) = rest.split_once(":** ").ok_or("invalid approval heading")?;
    // #558/R9: plan-graph's template quotes the user's words exactly
    // (`"<words>"`, nothing after). The reader also accepts a bracketed
    // source appended after the closing quote (`"<words>" (<source>)`),
    // so an approval that names its thread still reads.
    if !public_approval_ok(c, words) && !(legacy && approval_words_ok(words)) {
        return Err("approval has no valid decision and private pointer");
    }
    let revision = n(rev)?;
    let hashes = c
        .body
        .lines()
        .filter_map(|l| {
            l.strip_prefix("Fingerprint: `")
                .and_then(|s| s.strip_suffix('`'))
        })
        .collect::<Vec<_>>();
    let [hash] = hashes.as_slice() else {
        return Err("approval fingerprint missing or repeated");
    };
    let fp = Fingerprint::parse(hash).ok_or("invalid fingerprint")?;
    let blocks = c.body.match_indices("```text\n").collect::<Vec<_>>();
    let [(start, _)] = blocks.as_slice() else {
        return Err("approval revision text missing or repeated");
    };
    let tail = &c.body[start + 8..];
    let (text, _) = tail.split_once("```").ok_or("unclosed revision text")?;
    if !(text.starts_with("plan-graph revision v2\n")
        || text.starts_with("plan-graph revision v1\n"))
        || !text.ends_with('\n')
        || sha256_hex(text.as_bytes()) != *hash
    {
        return Err("invalid revision fingerprint");
    }
    let mut rows = BTreeMap::new();
    let mut headers = 0;
    let table = approval_table(&c.body);
    if table.len() < 2 || table.windows(2).any(|p| p[1].0 != p[0].0 + 1) {
        return Err("approval table is not one contiguous block");
    }
    for (index, (_, l)) in table.iter().enumerate() {
        // Match check-approval.sh: only an even backslash run leaves a pipe
        // unescaped, including the required closing delimiter.
        let mut escaped = false;
        let cells = l
            .trim_end()
            .split(|ch| {
                let separator = ch == '|' && !escaped;
                escaped = ch == '\\' && !escaped;
                separator
            })
            .collect::<Vec<_>>();
        let ["", cells @ .., ""] = cells.as_slice() else {
            return Err("invalid approval row");
        };
        let cells = cells.iter().map(|s| s.trim()).collect::<Vec<_>>();
        if index == 0 {
            if cells != ["Ticket", "Title", "Blocked by", "Label"] {
                return Err("invalid approval table header");
            }
            headers += 1;
            continue;
        }
        if index == 1 {
            if cells.len() != 4
                || !cells.iter().all(|c| {
                    let c = c.strip_prefix(':').unwrap_or(c);
                    let c = c.strip_suffix(':').unwrap_or(c);
                    c.len() >= 3 && c.bytes().all(|b| b == b'-')
                })
            {
                return Err("invalid approval table separator");
            }
            continue;
        }
        if cells.len() != 4 || cells[1].is_empty() {
            return Err("invalid approval table");
        }
        let id = n(cells[0].strip_prefix('#').ok_or("invalid ticket cell")?)?;
        let ready = match cells[3] {
            "ready-for-agent" => Ready::Agent,
            "ready-for-human" => Ready::Human,
            _ => return Err("unknown approved role"),
        };
        let prefix = format!("ticket #{id} blocked-by ");
        let revrow = text
            .lines()
            .filter(|l| l.starts_with(&prefix))
            .collect::<Vec<_>>();
        // The table escapes pipes; the issue title in the revision is raw.
        let title = cells[1].replace("\\|", "|");
        if revrow.len() != 1 || !revrow[0].ends_with(&format!(" title {title}")) {
            return Err("table disagrees with revision");
        }
        let blockers = revrow[0]
            .strip_prefix(&prefix)
            .unwrap()
            .split_once(" body sha256 ")
            .ok_or("invalid revision row")?
            .0;
        if blocker_set(blockers)? != blocker_set(cells[2])? {
            return Err("table blockers disagree with revision");
        }
        if rows.insert(id, ready).is_some() {
            return Err("duplicate approved ticket");
        }
    }
    if headers != 1 || text.lines().filter(|l| l.starts_with("ticket #")).count() != rows.len() {
        return Err("incomplete approval table");
    }
    Ok(Some(PlanApproval {
        approval: Approval {
            comment: c.id,
            revision,
            fingerprint: fp,
        },
        rows,
        approved_at: c.created,
    }))
}
pub fn relies(body: &str) -> Result<Vec<NonEmpty>> {
    let lines = body
        .lines()
        .filter_map(|l| l.strip_prefix("**Relies on:**"))
        .collect::<Vec<_>>();
    let line = match lines.as_slice() {
        [] => return Ok(vec![]),
        [s] if !s.trim().is_empty() => s.trim(),
        _ => return Err("ambiguous relies-on"),
    };
    if line.eq_ignore_ascii_case("nothing") || line.eq_ignore_ascii_case("none") {
        return Ok(vec![]);
    }
    // Only explicitly backticked paths are contracts, never inferred from prose.
    let mut out = vec![];
    let mut tail = line;
    while let Some((_, after)) = tail.split_once('`') {
        let (path, rest) = after.split_once('`').ok_or("unclosed relied-on path")?;
        if path.is_empty() || path.starts_with('/') || path.contains("..") || !path.is_ascii() {
            return Err("invalid relied-on path");
        }
        if path.contains('/') || path.contains('.') {
            out.push(NonEmpty::new(path).unwrap());
        }
        tail = rest;
    }
    Ok(out)
}
pub fn spec_records(comments: &[Comment]) -> SpecRecords {
    SpecRecords {
        summary_written: lines(comments).any(|l| {
            l == "launch-fleet: spec summary" || l.starts_with("launch-fleet: spec summary:")
        }),
        looked: looked(comments),
        approval_notified: vec![],
    }
}
pub fn looked(comments: &[Comment]) -> Vec<String> {
    lines(comments)
        .filter_map(|l| l.strip_prefix("launch-fleet: look: ").map(str::to_owned))
        .collect()
}
pub fn ticket_records(comments: &[Comment]) -> TicketRecords {
    let mut r = TicketRecords {
        archived: has(comments, "launch-fleet: archived"),
        looked: looked(comments),
        ..Default::default()
    };
    for c in comments {
        let l = first(c);
        if l == "launch-fleet: asked the orchestrator" {
            r.question_passed = Some(c.id);
        }
        if l == "launch-fleet: told the user" {
            r.person_notified = true;
        }
        if let Some(s) = l
            .strip_prefix("launch-fleet: noted #")
            .and_then(|s| n(s).ok())
        {
            r.noted.push(s);
        }
    }
    r
}
pub fn pr_records(comments: &[Comment], retired_rechecks: &BTreeSet<Number>) -> PrRecords {
    let mut r = PrRecords::default();
    for c in comments {
        let l = first(c);
        for (prefix, out) in [
            ("findings sent ", &mut r.findings_sent),
            ("CI failure sent ", &mut r.ci_sent),
            ("re-check sent ", &mut r.recheck_sent),
            ("dispute asked ", &mut r.dispute_asked),
            ("diagnosis asked ", &mut r.diagnosis_asked),
            ("merge blocked ", &mut r.merge_blocked),
        ] {
            if prefix == "re-check sent " && retired_rechecks.contains(&c.id) {
                continue;
            }
            if let Some(tail) = l.strip_prefix(&format!("launch-fleet: {prefix}")) {
                let (head, rest) = tail.split_at_checked(40).unwrap_or(("", ""));
                let valid_suffix = if prefix == "re-check sent " {
                    rest.is_empty()
                        || rest
                            .strip_prefix(", thread ")
                            .is_some_and(openwiz_core::fleet::starts::safe_id)
                } else if prefix == "merge blocked " {
                    rest.starts_with(": ") && rest.len() > 2
                } else {
                    rest.is_empty()
                };
                if valid_suffix && let Some(c) = openwiz_core::fleet::model::Commit::parse(head) {
                    out.push(c);
                }
            }
        }
    }
    r
}
pub fn holds(
    comments: &[Comment],
    events: &[Event],
    merges: &BTreeMap<Number, openwiz_core::fleet::model::Commit>,
) -> Result<(Vec<Hold>, Option<Number>)> {
    let mut holds = vec![];
    for c in comments {
        let Some(tail) = first(c).strip_prefix("launch-fleet: held for #") else {
            continue;
        };
        let (pr, files) = tail
            .split_once(": contract changed, re-approve. ")
            .ok_or("malformed hold record")?;
        let pr = n(pr)?;
        let suffix = format!(" changed in #{pr}.");
        let files = files.strip_suffix(&suffix).ok_or("malformed hold files")?;
        let files = files
            .split(", ")
            .map(|s| NonEmpty::new(s).ok_or("empty hold path"))
            .collect::<Result<Vec<_>>>()?;
        let merge_commit = merges.get(&pr).ok_or("hold merge missing")?.clone();
        holds.push(Hold {
            comment: c.id,
            merged: MergeFact {
                number: pr,
                merge_commit,
            },
            files,
            notified: has(
                comments,
                &format!("launch-fleet: needs you sent: held for #{pr}"),
            ),
        });
    }
    // Timeline order, rather than second-resolution timestamps, proves the
    // latest held application preceded this exact tick's hold record.
    let latest = events
        .iter()
        .rposition(|e| e.event == "labeled" && e.label.as_deref() == Some("held"));
    let own = latest.and_then(|pos| {
        holds
            .iter()
            .rev()
            .find(|h| {
                events.iter().enumerate().any(|(i, e)| {
                    i > pos
                        && e.event == "commented"
                        && e.id == h.comment
                        && e.body.as_deref()
                            == comments
                                .iter()
                                .find(|c| c.id == h.comment)
                                .map(|c| c.body.as_str())
                })
            })
            .map(|h| h.comment)
    });
    Ok((holds, own))
}

/// A unique checked builder; conflicts and malformed records never pick a family.
pub fn checked_builder(comments: &[Comment]) -> Option<(Option<NonEmpty>, NonEmpty)> {
    let mut branches = BTreeSet::new();
    let mut threads = BTreeSet::new();
    for line in lines(comments) {
        let Some(tail) = line.strip_prefix("launch-fleet: start checked, ") else {
            continue;
        };
        let branch = if let Some(s) = tail.strip_prefix("thread ") {
            let (thread, branch) = s.split_once(", branch ")?;
            if !openwiz_core::fleet::starts::safe_id(thread) {
                return None;
            }
            threads.insert(NonEmpty::new(thread)?);
            branch
        } else {
            tail.strip_prefix("branch ")?
        };
        if branch.len() > 255
            || branch.is_empty()
            || branch.starts_with('-')
            || !branch.bytes().all(|b| b.is_ascii_graphic())
        {
            return None;
        }
        branches.insert(NonEmpty::new(branch)?);
    }
    if branches.len() == 1 && threads.len() <= 1 {
        Some((threads.into_iter().next(), branches.into_iter().next()?))
    } else {
        None
    }
}

/// T1 of open-development.v1: a thread token is private even in free text.
pub fn contains_thread_id(text: &str) -> bool {
    text.match_indices("thr_").any(|(at, _)| {
        text.as_bytes()
            .get(at + 4)
            .is_some_and(u8::is_ascii_alphanumeric)
    })
}

pub fn fallback_record(_builder: &NonEmpty, branch: &NonEmpty) -> String {
    format!(
        "launch-fleet: builder fallback due, branch {}",
        branch.as_str()
    )
}

pub fn fallback_due(comments: &[Comment]) -> bool {
    // Even a malformed claim cannot establish that no fallback was consumed.
    lines(comments).any(|l| l.starts_with("launch-fleet: builder fallback due,"))
}

/// A completed manual restart supplements the due record, without erasing it.
pub fn fallback_replacement(
    comments: &[Comment],
) -> Result<Option<(NonEmpty, NonEmpty, NonEmpty)>> {
    let mut replacements = Vec::new();
    for c in comments {
        let Some(s) = first(c).strip_prefix("launch-fleet: builder fallback due, thread ") else {
            continue;
        };
        let lines = c
            .body
            .lines()
            .skip(1)
            .filter_map(|l| l.strip_prefix("Replacement: "))
            .collect::<Vec<_>>();
        if lines.is_empty() {
            continue;
        }
        let [replacement] = lines.as_slice() else {
            return Err("conflicting fallback replacement");
        };
        let (old, branch) = s
            .split_once(", branch ")
            .ok_or("malformed fallback record")?;
        if !openwiz_core::fleet::starts::safe_id(old)
            || !openwiz_core::fleet::starts::safe_id(replacement)
            || old == *replacement
            || branch.is_empty()
            || branch.len() > 255
            || branch.starts_with('-')
            || !branch.bytes().all(|b| b.is_ascii_graphic())
        {
            return Err("invalid fallback replacement");
        }
        replacements.push((
            NonEmpty::new(old).unwrap(),
            NonEmpty::new(*replacement).unwrap(),
            NonEmpty::new(branch).unwrap(),
        ));
    }
    match replacements.len() {
        0 => Ok(None),
        1 => Ok(replacements.pop()),
        _ => Err("conflicting fallback replacement"),
    }
}

/// Activity is ordered by creation, not edit time: an edited give-up still
/// closes its original reviewer span. Legacy failed starts without a thread
/// are not reviewer give-ups.
pub struct ReviewRecord {
    pub comment: Number,
    pub kind: &'static str,
    pub head: openwiz_core::fleet::model::Commit,
    pub thread: Option<NonEmpty>,
    pub created: u64,
    pub updated: u64,
}
pub fn review_records(comments: &[Comment]) -> Result<Vec<ReviewRecord>> {
    let mut ordered = comments.iter().collect::<Vec<_>>();
    ordered.sort_by_key(|c| (c.created, c.id));
    let mut out = Vec::new();
    for c in ordered {
        for kind in [
            "review started",
            "re-check sent",
            "review told again",
            "review given up",
            "review failed",
        ] {
            let Some(tail) = first(c).strip_prefix(&format!("launch-fleet: {kind} ")) else {
                continue;
            };
            if kind == "review failed" && !tail.contains(", thread ") {
                continue;
            }
            let (head, thread) = if let Some((head, tail)) = tail.split_once(", thread ") {
                let thread = if kind == "review failed" {
                    let (thread, why) = tail.split_once(": ").ok_or("invalid review failure")?;
                    if why.is_empty() {
                        return Err("empty review failure");
                    }
                    thread
                } else {
                    tail
                };
                if !openwiz_core::fleet::starts::safe_id(thread) {
                    return Err("invalid reviewer thread");
                }
                (head, Some(NonEmpty::new(thread).unwrap()))
            } else if kind == "review given up" {
                let (head, why) = tail.split_once(": ").ok_or("invalid review give-up")?;
                if why.is_empty() {
                    return Err("empty review give-up");
                }
                (head, None)
            } else {
                (tail, None)
            };
            out.push(ReviewRecord {
                comment: c.id,
                kind,
                head: openwiz_core::fleet::model::Commit::parse(head)
                    .ok_or("invalid review head")?,
                thread,
                created: c.created,
                updated: c.updated,
            });
        }
    }
    Ok(out)
}
