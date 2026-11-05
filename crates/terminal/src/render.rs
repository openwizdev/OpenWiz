//! Draws the shell in the accepted M6 Observatory language, translated into
//! terminal cells: a dark canvas (navigation), sheet (content) and panel
//! (action pane); purple only for live and selected; gold only for Needs you;
//! and every state as a word plus a shape, so colour never carries it alone.
//! Without true colour it uses the nearest 256-colour cells; with `NO_COLOR`
//! none; without a UTF-8 locale, ASCII shapes. Text from any source is
//! drawn through [`crate::sanitize`].

use ratatui::Frame;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Clear, Paragraph, Wrap};

use crate::actions::ActionId;
use crate::app::{App, Detail, LaneKind, Nav, NeedKey, Now};
use crate::model::{Coverage, Fact, Freshness, Session, TICKET_STATES};
use crate::sanitize::{age, block, line};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Colour {
    True,
    Indexed,
    None,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Theme {
    pub colour: Colour,
    pub unicode: bool,
}

impl Theme {
    /// From the environment: `NO_COLOR`, `COLORTERM` and the locale.
    pub fn from_env(get: impl Fn(&str) -> Option<String>) -> Self {
        let colour = if get("NO_COLOR").is_some_and(|v| !v.is_empty()) {
            Colour::None
        } else if get("COLORTERM").is_some_and(|v| v == "truecolor" || v == "24bit") {
            Colour::True
        } else {
            Colour::Indexed
        };
        let locale = ["LC_ALL", "LC_CTYPE", "LANG"]
            .iter()
            .find_map(|k| get(k).filter(|v| !v.is_empty()))
            .unwrap_or_default()
            .to_ascii_lowercase();
        Self {
            colour,
            unicode: locale.contains("utf-8") || locale.contains("utf8"),
        }
    }

    pub const TRUE_UNICODE: Theme = Theme {
        colour: Colour::True,
        unicode: true,
    };
}

/// The M6 tokens (`apps/web/styles/tokens.css`), with 256-colour neighbours.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Token {
    Canvas,
    Sheet,
    Panel,
    Selected,
    Text,
    Secondary,
    Tertiary,
    Live,
    Attention,
}

impl Token {
    pub fn rgb(self) -> (u8, u8, u8) {
        match self {
            Token::Canvas => (0x0e, 0x0f, 0x11),
            Token::Sheet => (0x15, 0x17, 0x19),
            Token::Panel => (0x1c, 0x1e, 0x21),
            Token::Selected => (0x29, 0x22, 0x38),
            Token::Text => (0xe8, 0xea, 0xed),
            Token::Secondary => (0xb6, 0xbd, 0xc8),
            Token::Tertiary => (0x9c, 0xa5, 0xb3),
            Token::Live => (0xa7, 0x8b, 0xfa),
            Token::Attention => (0xfd, 0xb9, 0x27),
        }
    }

    fn indexed(self) -> u8 {
        match self {
            Token::Canvas => 233,
            Token::Sheet => 234,
            Token::Panel => 235,
            Token::Selected => 236,
            Token::Text => 255,
            Token::Secondary => 250,
            Token::Tertiary => 247,
            Token::Live => 141,
            Token::Attention => 214,
        }
    }
}

/// The five M6 status tiers (`design-rules.md`): t1 Needs you, t2 done,
/// t3 live, t4 waiting, t5 unknown/other.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tier {
    T1,
    T2,
    T3,
    T4,
    T5,
}

impl Theme {
    pub fn colour(&self, token: Token) -> Color {
        match self.colour {
            Colour::True => {
                let (r, g, b) = token.rgb();
                Color::Rgb(r, g, b)
            }
            Colour::Indexed => Color::Indexed(token.indexed()),
            Colour::None => Color::Reset,
        }
    }

    fn fg(&self, token: Token) -> Style {
        Style::default().fg(self.colour(token))
    }

    pub fn glyph(&self, tier: Tier) -> &'static str {
        match (tier, self.unicode) {
            (Tier::T1, true) => "◆",
            (Tier::T2, true) => "✓",
            (Tier::T3, true) => "◉",
            (Tier::T4, true) => "○",
            (Tier::T5, true) => "◌",
            (Tier::T1, false) => "!",
            (Tier::T2, false) => "+",
            (Tier::T3, false) => "@",
            (Tier::T4, false) => "o",
            (Tier::T5, false) => ".",
        }
    }

    fn tier_style(&self, tier: Tier) -> Style {
        match tier {
            Tier::T1 => self.fg(Token::Attention).add_modifier(Modifier::BOLD),
            Tier::T2 => self.fg(Token::Text),
            Tier::T3 => self.fg(Token::Live),
            Tier::T4 | Tier::T5 => self.fg(Token::Secondary),
        }
    }

    fn mark(&self, tier: Tier) -> Span<'static> {
        Span::styled(format!("{} ", self.glyph(tier)), self.tier_style(tier))
    }

    fn dot(&self) -> &'static str {
        if self.unicode { " · " } else { " - " }
    }

    fn edge(&self) -> &'static str {
        if self.unicode { "▌" } else { ">" }
    }

    fn selected(&self) -> Style {
        match self.colour {
            Colour::None => Style::default().add_modifier(Modifier::REVERSED),
            _ => Style::default().bg(self.colour(Token::Selected)),
        }
    }
}

/// The session status words' tiers (M6: active is live, idle waits, error
/// needs the owner; any other word is t5).
pub fn session_tier(status: &Fact<String>) -> Tier {
    match status.known().map(String::as_str) {
        Some("active") => Tier::T3,
        Some("idle") => Tier::T4,
        Some("error") => Tier::T1,
        _ => Tier::T5,
    }
}

pub fn ticket_tier(state: &str) -> Tier {
    match state {
        "held" | "needs_info" => Tier::T1,
        "merged" => Tier::T2,
        "building" | "in_review" | "changes_requested" => Tier::T3,
        "ready" | "blocked" => Tier::T4,
        _ => Tier::T5,
    }
}

fn fact_text(fact: &Fact<String>) -> String {
    match fact {
        Fact::Known(v) => line(v),
        Fact::Unknown(why) => format!("unknown ({})", line(why)),
    }
}

/// The layout class for a size.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Size {
    Wide,
    Narrow,
}

pub fn size_class(area: Rect) -> Size {
    if area.width >= 72 && area.height >= 12 {
        Size::Wide
    } else {
        Size::Narrow
    }
}

pub fn draw(frame: &mut Frame, app: &App, now: Now, theme: &Theme) {
    let area = frame.area();
    let canvas = Style::default()
        .bg(theme.colour(Token::Canvas))
        .fg(theme.colour(Token::Text));
    let sheet = Style::default()
        .bg(theme.colour(Token::Sheet))
        .fg(theme.colour(Token::Text));
    frame.render_widget(Block::default().style(canvas), area);
    let (nav_area, main_area, footer_area) = match size_class(area) {
        Size::Wide => {
            let rows = Layout::default()
                .direction(Direction::Vertical)
                .constraints([Constraint::Min(1), Constraint::Length(1)])
                .split(area);
            let cols = Layout::default()
                .direction(Direction::Horizontal)
                .constraints([Constraint::Length(22), Constraint::Min(1)])
                .split(rows[0]);
            (cols[0], cols[1], rows[1])
        }
        Size::Narrow => {
            let rows = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(1),
                    Constraint::Min(0),
                    Constraint::Length(1),
                ])
                .split(area);
            (rows[0], rows[1], rows[2])
        }
    };
    match size_class(area) {
        Size::Wide => draw_sidebar(frame, app, now, theme, nav_area, canvas),
        Size::Narrow => draw_tabs(frame, app, theme, nav_area, canvas),
    }
    frame.render_widget(Block::default().style(sheet), main_area);
    let inner = Rect {
        x: main_area.x + u16::from(main_area.width > 40),
        y: main_area.y,
        width: main_area
            .width
            .saturating_sub(if main_area.width > 40 { 2 } else { 0 }),
        height: main_area.height,
    };
    let lines = match &app.detail {
        None => match app.nav {
            Nav::Home => home(app, now, theme),
            Nav::Sessions => sessions(app, now, theme),
            Nav::Fleets => fleets(app, now, theme),
        },
        Some(Detail::Session(id)) => session_detail(app, id, now, theme),
        Some(Detail::Fleet(spec)) => fleet_detail(app, *spec, now, theme),
        Some(Detail::Need(key)) => need_detail(app, key, now, theme),
    };
    let lines = pieces(lines);
    let follow = app.follow && app.detail.is_none();
    let slice = viewport(
        &lines,
        inner.width,
        inner.height,
        follow,
        app.scroll,
        (&app.view_offset, &app.view_max, &app.view_height),
    );
    frame.render_widget(
        Paragraph::new(lines[slice.from..].to_vec())
            .style(sheet)
            .wrap(Wrap { trim: false })
            .scroll((slice.within, 0)),
        inner,
    );
    if app.open_action().is_some() {
        draw_action(frame, app, theme, main_area);
    }
    frame.render_widget(
        Paragraph::new(footer(app, theme)).style(canvas.fg(theme.colour(Token::Tertiary))),
        footer_area,
    );
}

/// Visual rows one line takes when wrapped at `width` (at least one). A
/// displayed line is at most [`crate::sanitize::DISPLAY_MAX_CHARS`]
/// characters, so this always fits a ratatui scroll offset.
fn line_rows(line: &Line<'static>, width: u16) -> usize {
    Paragraph::new(vec![line.clone()])
        .wrap(Wrap { trim: false })
        .line_count(width)
        .max(1)
}

/// Splits every line longer than [`crate::sanitize::DISPLAY_MAX_CHARS`]
/// characters into consecutive pieces of at most that many (a single longer
/// grapheme cluster keeps its own piece), cutting only between grapheme
/// clusters and keeping each span's and the line's style. Nothing is
/// dropped: the sanitizer has already replaced every control character.
fn pieces(lines: Vec<Line<'static>>) -> Vec<Line<'static>> {
    let max = crate::sanitize::DISPLAY_MAX_CHARS;
    let mut out = Vec::with_capacity(lines.len());
    for l in lines {
        if l.spans
            .iter()
            .map(|s| s.content.chars().count())
            .sum::<usize>()
            <= max
        {
            out.push(l);
            continue;
        }
        // Cut only between grapheme clusters (ratatui's own segmentation),
        // so a combining mark always stays with its base character.
        let mut current: Vec<Span<'static>> = Vec::new();
        let mut used = 0;
        for span in &l.spans {
            let mut segment = String::new();
            for grapheme in span.styled_graphemes(Style::default()) {
                let n = grapheme.symbol.chars().count();
                if used > 0 && used + n > max {
                    if !segment.is_empty() {
                        current.push(Span::styled(std::mem::take(&mut segment), span.style));
                    }
                    out.push(Line::from(std::mem::take(&mut current)).style(l.style));
                    used = 0;
                }
                segment.push_str(grapheme.symbol);
                used += n;
            }
            if !segment.is_empty() {
                current.push(Span::styled(segment, span.style));
            }
        }
        if !current.is_empty() {
            out.push(Line::from(current).style(l.style));
        }
    }
    out
}

fn is_selected(l: &Line<'_>) -> bool {
    l.style.bg.is_some() || l.style.add_modifier.contains(Modifier::REVERSED)
}

/// What to draw: the first line, and the visual rows to skip within it.
struct Slice {
    from: usize,
    within: u16,
}

/// Chooses the first visual row to show, counting wrapped rows at `width`
/// in `usize` (a page can wrap to more rows than `u16` holds): the owner's
/// own position, or, while following, one that keeps the selected line in
/// view. A selected line taller than the view keeps one anchor, its top, so
/// identical draws show identical screens. Records what it chose, so page
/// keys move from what is on screen.
fn viewport(
    lines: &[Line<'static>],
    width: u16,
    height: u16,
    follow: bool,
    requested: usize,
    cells: (
        &std::cell::Cell<usize>,
        &std::cell::Cell<usize>,
        &std::cell::Cell<u16>,
    ),
) -> Slice {
    let (offset_cell, max_cell, height_cell) = cells;
    let heights: Vec<usize> = lines.iter().map(|l| line_rows(l, width)).collect();
    let total: usize = heights.iter().sum();
    let view = usize::from(height);
    let max = total.saturating_sub(view);
    let mut offset = if follow { offset_cell.get() } else { requested }.min(max);
    if follow && let Some(i) = lines.iter().position(is_selected) {
        let top: usize = heights[..i].iter().sum();
        let bottom = top + heights[i];
        if heights[i] >= view || top < offset {
            offset = top.min(max);
        } else if bottom > offset + view {
            offset = (bottom - view).min(max);
        }
    }
    offset_cell.set(offset);
    max_cell.set(max);
    height_cell.set(height);
    let mut before = 0;
    for (from, h) in heights.iter().enumerate() {
        if before + h > offset {
            return Slice {
                from,
                within: u16::try_from(offset - before).unwrap_or(u16::MAX),
            };
        }
        before += h;
    }
    Slice {
        from: lines.len(),
        within: 0,
    }
}

fn draw_sidebar(frame: &mut Frame, app: &App, now: Now, theme: &Theme, area: Rect, canvas: Style) {
    let mut lines = vec![
        Line::from(Span::styled(
            " OpenWiz",
            theme.fg(Token::Text).add_modifier(Modifier::BOLD),
        )),
        Line::default(),
    ];
    for (nav, label, key) in [
        (Nav::Home, "Home", 'h'),
        (Nav::Sessions, "Sessions", 's'),
        (Nav::Fleets, "Fleets", 'f'),
    ] {
        let on = app.nav == nav;
        let mut spans = vec![Span::styled(
            if on { theme.edge() } else { " " },
            theme.fg(Token::Live),
        )];
        spans.push(Span::styled(
            format!("{label:<10}"),
            if on {
                theme.fg(Token::Text).add_modifier(Modifier::BOLD)
            } else {
                theme.fg(Token::Secondary)
            },
        ));
        spans.push(Span::styled(format!(" {key}"), theme.fg(Token::Tertiary)));
        if nav == Nav::Home {
            let n = app.needs().len();
            if n > 0 {
                spans.push(Span::styled(
                    format!(" {} {n}", theme.glyph(Tier::T1)),
                    theme.tier_style(Tier::T1),
                ));
            }
        }
        let mut l = Line::from(spans);
        if on {
            l = l.style(theme.selected());
        }
        lines.push(l);
    }
    lines.push(Line::default());
    for l in connection(app, now, theme) {
        lines.push(l);
    }
    frame.render_widget(
        Paragraph::new(lines)
            .style(canvas)
            .wrap(Wrap { trim: false }),
        area,
    );
}

fn connection(app: &App, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let port = app.settings.port;
    let unavailable = [LaneKind::Decisions, LaneKind::Fleets, LaneKind::Inventory]
        .iter()
        .all(|k| {
            app.errors
                .get(k)
                .is_some_and(|e| e.reason.contains("unavailable"))
        });
    let any_good = app.inventory.is_some() || app.fleets.is_some() || app.decisions.is_some();
    let (tier, word) = if unavailable {
        (Tier::T5, "disconnected")
    } else if any_good {
        (Tier::T3, "connected")
    } else {
        (Tier::T5, "reading")
    };
    let _ = now;
    vec![
        Line::from(vec![
            Span::raw(" "),
            theme.mark(tier),
            Span::styled(word.to_owned(), theme.fg(Token::Secondary)),
        ]),
        Line::from(Span::styled(
            format!(" 127.0.0.1:{port}"),
            theme.fg(Token::Tertiary),
        )),
        Line::from(Span::styled(
            match &app.settings.allowed_host {
                Some(_) => " writes: host set".to_owned(),
                None => " writes: off (no host)".to_owned(),
            },
            theme.fg(Token::Tertiary),
        )),
    ]
}

fn draw_tabs(frame: &mut Frame, app: &App, theme: &Theme, area: Rect, canvas: Style) {
    let mut spans = Vec::new();
    for (nav, label) in [
        (Nav::Home, "Home"),
        (Nav::Sessions, "Sessions"),
        (Nav::Fleets, "Fleets"),
    ] {
        let on = app.nav == nav;
        let style = if on {
            theme
                .selected()
                .fg(theme.colour(Token::Text))
                .add_modifier(Modifier::BOLD)
        } else {
            theme.fg(Token::Secondary)
        };
        spans.push(Span::styled(
            format!("{}{label} ", if on { theme.edge() } else { " " }),
            style,
        ));
        if nav == Nav::Home {
            let n = app.needs().len();
            if n > 0 {
                spans.push(Span::styled(
                    format!("{}{n} ", theme.glyph(Tier::T1)),
                    theme.tier_style(Tier::T1),
                ));
            }
        }
    }
    frame.render_widget(Paragraph::new(Line::from(spans)).style(canvas), area);
}

fn footer(app: &App, theme: &Theme) -> Line<'static> {
    if let Some(notice) = &app.notice {
        return Line::from(Span::styled(
            format!(" {}", line(notice)),
            theme.fg(Token::Secondary),
        ));
    }
    let hints = if app.open_action().is_some() {
        if app.confirm_key() == 'y' {
            "Esc close  Tab field  PgUp/PgDn scroll  Ctrl-P preview  Ctrl-Y confirm again  Ctrl-R status"
        } else {
            "Esc close  Tab field  PgUp/PgDn scroll  Ctrl-P preview  Ctrl-S confirm  Ctrl-R status"
        }
    } else {
        match (&app.detail, app.nav) {
            (Some(Detail::Need(_)), _) => "q quit  Esc back  a answer  j/k scroll  r refresh",
            (Some(Detail::Session(_)), _) => {
                "q quit  Esc back  m message  n new thread  j/k scroll  r refresh"
            }
            (Some(Detail::Fleet(_)), _) => "q quit  Esc back  j/k scroll  r refresh",
            (None, Nav::Home) => "q quit  1-9 open item  s sessions  f fleets  r refresh",
            (None, _) => "q quit  j/k move  Enter open  h home  Tab next  r refresh",
        }
    };
    Line::from(format!(" {hints}"))
}

fn heading(text: &str, theme: &Theme, attention: bool) -> Line<'static> {
    let style = if attention {
        theme.fg(Token::Attention).add_modifier(Modifier::BOLD)
    } else {
        theme.fg(Token::Text).add_modifier(Modifier::BOLD)
    };
    Line::from(Span::styled(text.to_owned(), style))
}

/// A part's coverage, source age, gaps, staleness and failure, in words.
fn part_status(
    app: &App,
    kind: LaneKind,
    good: Option<(Coverage, usize, Option<u64>)>,
    now: Now,
    theme: &Theme,
) -> Line<'static> {
    let d = theme.dot();
    let mut words = format!("  {}: ", kind.name());
    let error = app.errors.get(&kind);
    match good {
        None => match error {
            Some(e) => words.push_str(&format!("unavailable{d}{}", line(&e.reason))),
            None => words.push_str("reading…"),
        },
        Some((coverage, gaps, source_age)) => {
            match coverage {
                Coverage::Complete => words.push_str("complete"),
                Coverage::Partial => words.push_str(&format!(
                    "partial{d}{gaps} gap{}",
                    if gaps == 1 { "" } else { "s" }
                )),
            }
            match source_age {
                Some(ms) => words.push_str(&format!("{d}read {} ago", age(ms as i64))),
                None => words.push_str(&format!("{d}source age unknown")),
            }
            if app.stale(kind, source_age) {
                words.push_str(&format!("{d}stale"));
            }
            if let Some(e) = error {
                words.push_str(&format!("{d}last refresh failed: {}", line(&e.reason)));
            }
        }
    }
    if app.late(kind, now) {
        words.push_str(&format!("{d}late"));
    }
    Line::from(Span::styled(words, theme.fg(Token::Tertiary)))
}

/// Each gap of a part, in its own words: kind, subject and detail.
fn gap_lines(gaps: &[crate::model::Gap], theme: &Theme) -> Vec<Line<'static>> {
    gaps.iter()
        .map(|g| {
            let subject = g
                .subject
                .as_deref()
                .map(|s| format!(" {}", line(s)))
                .unwrap_or_default();
            Line::from(Span::styled(
                format!("    gap {}{subject}: {}", line(&g.kind), line(&g.detail)),
                theme.fg(Token::Tertiary),
            ))
        })
        .collect()
}

fn home(app: &App, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let d = theme.dot();
    let mut out = vec![heading("Needs you", theme, true)];
    out.push(part_status(
        app,
        LaneKind::Decisions,
        app.decisions.as_ref().map(|g| {
            (
                g.data.coverage,
                g.data.gaps.len(),
                g.age_of(g.data.source_snapshot_at.known().copied(), now),
            )
        }),
        now,
        theme,
    ));
    if let Some(g) = &app.decisions {
        out.extend(gap_lines(&g.data.gaps, theme));
    }
    if let Some(g) = &app.decisions
        && g.data.freshness != Freshness::Fresh
    {
        out.push(Line::from(Span::styled(
            format!(
                "  decision sources: {}",
                match g.data.freshness {
                    Freshness::Stale => "stale",
                    _ => "freshness unknown",
                }
            ),
            theme.fg(Token::Tertiary),
        )));
    }
    let needs = app.needs();
    for (i, key) in needs.iter().enumerate() {
        let first = out.len();
        let selected = app.selected_need.as_ref() == Some(key);
        let n = i + 1;
        let number = if n <= 9 { format!("{n}") } else { " ".into() };
        let mut spans = vec![
            Span::styled(
                format!("  {number} "),
                theme.fg(Token::Attention).add_modifier(Modifier::BOLD),
            ),
            theme.mark(Tier::T1),
        ];
        match key {
            NeedKey::Decision { .. } => {
                if let Some(b) = app.binding(key) {
                    let question = b
                        .question_id
                        .as_deref()
                        .map(|q| format!(" {}", line(q)))
                        .unwrap_or_default();
                    let kind = b
                        .record
                        .get("kind")
                        .and_then(|k| k.as_str())
                        .unwrap_or("record")
                        .replace('_', " ");
                    spans.push(Span::styled(
                        format!(
                            "#{} {kind}{question}{d}risk {}",
                            b.subject_number,
                            line(&b.risk)
                        ),
                        theme.fg(Token::Text),
                    ));
                    out.push(Line::from(spans));
                    if let Some(first) = b.proposal.first() {
                        out.push(Line::from(Span::styled(
                            format!("       {}", line(first)),
                            theme.fg(Token::Secondary),
                        )));
                    }
                }
            }
            NeedKey::Fleet { kind, spec, ticket } => {
                spans.push(Span::styled(
                    format!("#{ticket} {}{d}fleet #{spec}", kind.replace('_', " ")),
                    theme.fg(Token::Text),
                ));
                out.push(Line::from(spans));
                out.push(Line::from(Span::styled(
                    "       fleet label only: no answerable proposal".to_owned(),
                    theme.fg(Token::Tertiary),
                )));
                let need = app.fleets.as_ref().and_then(|g| match &g.data.needs_you {
                    Fact::Known(n) => n
                        .iter()
                        .find(|n| n.spec == *spec && n.ticket == *ticket && &n.kind == kind),
                    Fact::Unknown(_) => None,
                });
                if let Some(need) = need {
                    out.extend(question(need, now, theme, "       "));
                }
            }
        }
        if selected && out.len() > first {
            out[first] = out[first].clone().style(theme.selected());
        }
    }
    if needs.is_empty() {
        out.push(Line::from(Span::styled(
            if nothing_needs_you(app, now) {
                format!("  {} Nothing needs you: decisions and fleets are complete and fresh", theme.glyph(Tier::T2))
            } else {
                "  No items shown. Coverage is incomplete, so this is not a claim that nothing needs you".to_owned()
            },
            theme.fg(Token::Secondary),
        )));
    }
    out.push(Line::default());
    out.push(heading("Fleets", theme, false));
    out.extend(fleet_rows(app, now, theme, false));
    out.push(Line::default());
    out.push(heading("Sessions", theme, false));
    out.extend(session_rows(app, now, theme, false, |s| {
        s.archived.known() != Some(&true)
    }));
    out
}

/// A fleet Needs you item's pending question, as the source reported it:
/// its first line, when it was asked and any explicit risk; each unknown
/// with its reason. Shown, never answerable here.
fn question(
    need: &crate::model::FleetNeed,
    now: Now,
    theme: &Theme,
    indent: &str,
) -> Vec<Line<'static>> {
    let d = theme.dot();
    let wording = match &need.wording {
        Fact::Known(w) => Span::styled(format!("{indent}{}", line(w)), theme.fg(Token::Text)),
        Fact::Unknown(why) => Span::styled(
            format!("{indent}question not read: {}", line(why)),
            theme.fg(Token::Tertiary),
        ),
    };
    let asked = match &need.asked_at {
        Fact::Known(at) => format!("asked {} ago", age(now.wall_ms - at)),
        Fact::Unknown(_) => "asked unknown".to_owned(),
    };
    let risk = match &need.risk {
        Fact::Known(r) => format!("risk {}", line(r)),
        Fact::Unknown(why) => format!("risk unknown ({})", line(why)),
    };
    vec![
        Line::from(wording),
        Line::from(Span::styled(
            format!("{indent}{asked}{d}{risk}"),
            theme.fg(Token::Tertiary),
        )),
    ]
}

/// Only complete, fresh coverage of every required part can say so.
pub fn nothing_needs_you(app: &App, now: Now) -> bool {
    let decisions = app.decisions.as_ref().is_some_and(|g| {
        g.data.coverage == Coverage::Complete
            && g.data.freshness == Freshness::Fresh
            && g.data.items.is_empty()
            && !app.stale(
                LaneKind::Decisions,
                g.age_of(g.data.source_snapshot_at.known().copied(), now),
            )
    });
    let fleets = app.fleets.as_ref().is_some_and(|g| {
        g.data.coverage == Coverage::Complete
            && matches!(&g.data.needs_you, Fact::Known(n) if n.is_empty())
            && !app.stale(LaneKind::Fleets, g.age_of(Some(g.data.snapshot_at), now))
    });
    decisions && fleets
}

fn session_rows(
    app: &App,
    now: Now,
    theme: &Theme,
    selectable: bool,
    keep: impl Fn(&Session) -> bool,
) -> Vec<Line<'static>> {
    let d = theme.dot();
    let mut out = vec![part_status(
        app,
        LaneKind::Inventory,
        app.inventory.as_ref().map(|g| {
            (
                g.data.coverage,
                g.data.gaps.len(),
                g.age_of(Some(g.data.snapshot_at), now),
            )
        }),
        now,
        theme,
    )];
    let Some(inv) = &app.inventory else {
        return out;
    };
    out.extend(gap_lines(&inv.data.gaps, theme));
    let rows: Vec<_> = inv.data.sessions.iter().filter(|s| keep(s)).collect();
    if rows.is_empty() {
        out.push(Line::from(Span::styled(
            match inv.data.coverage {
                Coverage::Complete => "  No sessions".to_owned(),
                Coverage::Partial => "  No sessions shown; the read is partial".to_owned(),
            },
            theme.fg(Token::Secondary),
        )));
    }
    for s in rows {
        let on = selectable && app.selected_session.as_deref() == Some(s.id.as_str());
        let tier = session_tier(&s.status);
        let edge = if on {
            Span::styled(theme.edge().to_owned(), theme.fg(Token::Live))
        } else if tier == Tier::T1 {
            Span::styled(theme.edge().to_owned(), theme.fg(Token::Attention))
        } else {
            Span::raw(" ")
        };
        let updated = match (&s.updated_at, inv.data.snapshot_at) {
            (Fact::Known(at), _) => format!("{} ago", age(now.wall_ms - at)),
            (Fact::Unknown(_), _) => "age unknown".into(),
        };
        let project = match &s.project {
            Some((_, name)) => fact_text(name),
            None => "ungrouped".into(),
        };
        let mut l = Line::from(vec![
            edge,
            Span::raw(" "),
            theme.mark(tier),
            Span::styled(fact_text(&s.title), theme.fg(Token::Text)),
            Span::styled(
                format!(
                    "{d}{}{d}{}{d}{}{d}{project}{d}{updated}",
                    fact_text(&s.status),
                    fact_text(&s.provider),
                    fact_text(&s.location),
                ),
                theme.fg(Token::Tertiary),
            ),
        ]);
        if on {
            l = l.style(theme.selected());
        }
        out.push(l);
    }
    out
}

fn sessions(app: &App, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let mut out = vec![heading("Sessions", theme, false)];
    out.extend(session_rows(app, now, theme, true, |_| true));
    out
}

fn progress(theme: &Theme, counts: &Fact<(u64, [u64; 8])>) -> String {
    match counts {
        Fact::Known((total, by)) => {
            let merged = by[4];
            let width = 10u64;
            let filled = (merged * width).checked_div(*total).unwrap_or(0) as usize;
            let (on, off) = if theme.unicode {
                ("█", "░")
            } else {
                ("#", "-")
            };
            format!(
                "{merged} of {total} merged {}{}",
                on.repeat(filled),
                off.repeat(width as usize - filled)
            )
        }
        Fact::Unknown(why) => format!("progress unknown ({})", line(why)),
    }
}

fn fleet_rows(app: &App, now: Now, theme: &Theme, selectable: bool) -> Vec<Line<'static>> {
    let d = theme.dot();
    let mut out = vec![part_status(
        app,
        LaneKind::Fleets,
        app.fleets.as_ref().map(|g| {
            (
                g.data.coverage,
                g.data.gaps.len(),
                g.age_of(Some(g.data.snapshot_at), now),
            )
        }),
        now,
        theme,
    )];
    let Some(fleets) = &app.fleets else {
        return out;
    };
    out.extend(gap_lines(&fleets.data.gaps, theme));
    if fleets.data.fleets.is_empty() {
        out.push(Line::from(Span::styled(
            match fleets.data.coverage {
                Coverage::Complete => "  No fleets".to_owned(),
                Coverage::Partial => "  No fleets shown; the read is partial".to_owned(),
            },
            theme.fg(Token::Secondary),
        )));
    }
    for f in &fleets.data.fleets {
        let on = selectable && app.selected_fleet == Some(f.spec);
        let needs = match &fleets.data.needs_you {
            Fact::Known(n) => n.iter().filter(|n| n.spec == f.spec).count(),
            Fact::Unknown(_) => 0,
        };
        let tier = match &f.progress {
            Fact::Known((total, by)) if *total > 0 && by[4] == *total => Tier::T2,
            Fact::Known(_) => Tier::T3,
            Fact::Unknown(_) => Tier::T5,
        };
        let mut spans = vec![
            Span::styled(
                if on { theme.edge() } else { " " }.to_owned(),
                theme.fg(Token::Live),
            ),
            Span::raw(" "),
            theme.mark(tier),
            Span::styled(
                format!("#{} {}", f.spec, fact_text(&f.title)),
                theme.fg(Token::Text),
            ),
            Span::styled(
                format!("{d}{}", progress(theme, &f.progress)),
                theme.fg(Token::Tertiary),
            ),
        ];
        if needs > 0 {
            spans.push(Span::styled(
                format!("{d}{} {needs} needs you", theme.glyph(Tier::T1)),
                theme.tier_style(Tier::T1),
            ));
        }
        let mut l = Line::from(spans);
        if on {
            l = l.style(theme.selected());
        }
        out.push(l);
    }
    out
}

fn fleets(app: &App, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let mut out = vec![heading("Fleets", theme, false)];
    out.extend(fleet_rows(app, now, theme, true));
    out
}

fn field(label: &str, value: String, theme: &Theme) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!("  {label:<14}"), theme.fg(Token::Tertiary)),
        Span::styled(value, theme.fg(Token::Text)),
    ])
}

fn action_hint(app: &App, id: ActionId, key: char, theme: &Theme) -> Line<'static> {
    let text = if app.action_available(id) {
        format!("  {key}  {}", id.label())
    } else {
        format!(
            "  {key}  {}: unavailable in this build; nothing can be sent",
            id.label()
        )
    };
    Line::from(Span::styled(text, theme.fg(Token::Secondary)))
}

fn session_detail(app: &App, id: &str, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let good = app.sessions.get(id);
    let mut out = vec![heading("Session", theme, false)];
    out.push(part_status(
        app,
        LaneKind::SessionDetail,
        good.map(|g| {
            (
                g.data.coverage,
                g.data.gaps.len(),
                g.age_of(Some(g.data.snapshot_at), now),
            )
        }),
        now,
        theme,
    ));
    let Some(good) = good else {
        out.push(field("id", line(id), theme));
        return out;
    };
    let s = &good.data.session;
    let tier = session_tier(&s.status);
    out.push(Line::from(vec![
        Span::raw("  "),
        theme.mark(tier),
        Span::styled(
            fact_text(&s.title),
            theme.fg(Token::Text).add_modifier(Modifier::BOLD),
        ),
    ]));
    out.push(field("id", line(&s.id), theme));
    out.push(field("status", fact_text(&s.status), theme));
    out.push(field("provider", fact_text(&s.provider), theme));
    out.push(field(
        "project",
        match &s.project {
            Some((_, name)) => fact_text(name),
            None => "ungrouped".into(),
        },
        theme,
    ));
    out.push(field("location", fact_text(&s.location), theme));
    out.push(field(
        "reported",
        format!(
            "model {}, effort {}",
            fact_text(&s.model),
            fact_text(&s.effort)
        ),
        theme,
    ));
    out.push(field(
        "updated",
        match &s.updated_at {
            Fact::Known(at) => format!("{} ago", age(now.wall_ms - at)),
            Fact::Unknown(why) => format!("unknown ({})", line(why)),
        },
        theme,
    ));
    out.push(field(
        "started",
        match &s.started_at {
            Fact::Known(at) => format!("{} ago", age(now.wall_ms - at)),
            Fact::Unknown(why) => format!("unknown ({})", line(why)),
        },
        theme,
    ));
    out.push(field(
        "recap",
        match &s.recap {
            Fact::Known(Some(t)) => line(t),
            Fact::Known(None) => "no recap yet".into(),
            Fact::Unknown(why) => format!("unknown ({})", line(why)),
        },
        theme,
    ));
    for gap in &good.data.gaps {
        out.push(field(
            "gap",
            format!("{}: {}", line(&gap.kind), line(&gap.detail)),
            theme,
        ));
    }
    out.push(Line::default());
    out.push(action_hint(app, ActionId::Send, 'm', theme));
    out.push(action_hint(app, ActionId::NewThread, 'n', theme));
    out.push(Line::default());
    out.push(heading("Final output", theme, false));
    match &good.data.final_output {
        Fact::Known(Some(text)) => {
            for l in block(text) {
                out.push(Line::from(Span::styled(
                    format!("  {l}"),
                    theme.fg(Token::Text),
                )));
            }
        }
        Fact::Known(None) => out.push(Line::from("  no final output yet")),
        Fact::Unknown(why) => out.push(Line::from(format!("  unknown ({})", line(why)))),
    }
    match &good.data.reported_error {
        Fact::Known(Some(text)) => {
            out.push(Line::default());
            out.push(heading("Reported error", theme, false));
            for l in block(text) {
                out.push(Line::from(format!("  {l}")));
            }
        }
        Fact::Known(None) => {}
        Fact::Unknown(why) => out.push(field("error", format!("unknown ({})", line(why)), theme)),
    }
    out
}

fn fleet_detail(app: &App, spec: u64, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let good = app.fleet_details.get(&spec);
    let mut out = vec![heading(&format!("Fleet #{spec}"), theme, false)];
    out.push(part_status(
        app,
        LaneKind::FleetDetail,
        good.map(|g| {
            (
                g.data.coverage,
                g.data.gaps.len(),
                g.age_of(Some(g.data.snapshot_at), now),
            )
        }),
        now,
        theme,
    ));
    let Some(good) = good else {
        return out;
    };
    let f = &good.data;
    out.push(field("title", fact_text(&f.fleet.title), theme));
    out.push(field("progress", progress(theme, &f.fleet.progress), theme));
    for gap in &f.gaps {
        out.push(field(
            "gap",
            format!(
                "{} {}: {}",
                line(&gap.kind),
                line(gap.subject.as_deref().unwrap_or("")),
                line(&gap.detail)
            ),
            theme,
        ));
    }
    out.push(Line::default());
    out.push(heading("Needs you", theme, true));
    match &f.needs_you {
        Fact::Known(n) if n.is_empty() => out.push(Line::from("  none in this fleet's reads")),
        Fact::Known(n) => {
            for need in n {
                out.push(Line::from(vec![
                    Span::raw("  "),
                    theme.mark(Tier::T1),
                    Span::raw(format!("#{} {}", need.ticket, need.kind.replace('_', " "))),
                ]));
                out.extend(question(need, now, theme, "     "));
            }
        }
        Fact::Unknown(why) => out.push(Line::from(format!("  unknown ({})", line(why)))),
    }
    out.push(Line::default());
    out.push(heading("Tickets", theme, false));
    for state in TICKET_STATES {
        let tickets: Vec<_> = f
            .tickets
            .iter()
            .filter(|t| match &t.state {
                Fact::Known(s) => s == state,
                Fact::Unknown(_) => state == "unknown",
            })
            .collect();
        if tickets.is_empty() {
            continue;
        }
        let tier = ticket_tier(state);
        out.push(Line::from(vec![
            Span::raw("  "),
            theme.mark(tier),
            Span::styled(
                format!("{} {}", state.replace('_', " "), tickets.len()),
                theme.fg(Token::Secondary).add_modifier(Modifier::BOLD),
            ),
        ]));
        for t in tickets {
            let why = match &t.state {
                Fact::Unknown(why) => format!(" (unknown: {})", line(why)),
                _ => String::new(),
            };
            out.push(Line::from(Span::styled(
                format!("     #{} {}{why}", t.number, fact_text(&t.title)),
                theme.fg(Token::Text),
            )));
        }
    }
    out
}

fn need_detail(app: &App, key: &NeedKey, now: Now, theme: &Theme) -> Vec<Line<'static>> {
    let mut out = vec![heading("Needs you", theme, true)];
    let gone = || {
        vec![Line::from(Span::styled(
            "  This item is no longer listed. Nothing was answered; go back and choose again."
                .to_owned(),
            Style::default(),
        ))]
    };
    match key {
        NeedKey::Decision { .. } => {
            let Some(b) = app.binding(key) else {
                out.extend(gone());
                return out;
            };
            out.push(part_status(
                app,
                LaneKind::Decisions,
                app.decisions.as_ref().map(|g| {
                    (
                        g.data.coverage,
                        g.data.gaps.len(),
                        g.age_of(g.data.source_snapshot_at.known().copied(), now),
                    )
                }),
                now,
                theme,
            ));
            if let Some(g) = &app.decisions {
                out.extend(gap_lines(&g.data.gaps, theme));
            }
            out.push(field(
                "subject",
                format!("{} #{}", b.subject_kind.replace('_', " "), b.subject_number),
                theme,
            ));
            out.push(field("record", line(&b.request_id), theme));
            if let Some(q) = &b.question_id {
                out.push(field("question", line(q), theme));
            }
            out.push(field("risk", line(&b.risk), theme));
            out.push(field(
                "current",
                match &b.current {
                    Fact::Known(true) => "yes".into(),
                    Fact::Known(false) => "no".into(),
                    Fact::Unknown(why) => format!("unknown ({})", line(why)),
                },
                theme,
            ));
            out.push(field(
                "answer to",
                match &b.target {
                    Fact::Known(Some(t)) => line(t),
                    Fact::Known(None) => "no orchestrator is configured".into(),
                    Fact::Unknown(why) => format!("unknown ({})", line(why)),
                },
                theme,
            ));
            if !b.context.is_empty() {
                out.push(Line::default());
                out.push(heading("Context", theme, false));
                for w in &b.context {
                    for l in block(w) {
                        out.push(Line::from(format!("  {l}")));
                    }
                }
            }
            out.push(Line::default());
            out.push(heading("Proposal", theme, false));
            for w in &b.proposal {
                for l in block(w) {
                    out.push(Line::from(format!("  {l}")));
                }
            }
            if !b.recommendation.is_empty() {
                out.push(Line::default());
                out.push(heading("Recommendation", theme, false));
                for w in &b.recommendation {
                    for l in block(w) {
                        out.push(Line::from(format!("  {l}")));
                    }
                }
            }
            out.push(Line::default());
            out.push(action_hint(app, ActionId::Answer, 'a', theme));
        }
        NeedKey::Fleet { kind, spec, ticket } => {
            let listed = app.needs().contains(key);
            if !listed {
                out.extend(gone());
                return out;
            }
            out.push(field("ticket", format!("#{ticket}"), theme));
            out.push(field("fleet", format!("#{spec}"), theme));
            out.push(field("state", kind.replace('_', " "), theme));
            out.push(Line::default());
            out.push(Line::from(Span::styled(
                "  A fleet label only: there is no answerable proposal here, so nothing can be answered from this screen."
                    .to_owned(),
                theme.fg(Token::Secondary),
            )));
        }
    }
    out
}

fn draw_action(frame: &mut Frame, app: &App, theme: &Theme, area: Rect) {
    let Some(id) = app.open_action() else {
        return;
    };
    let view = app.action_views.get(&id).cloned().unwrap_or_default();
    let panel = Style::default()
        .bg(theme.colour(Token::Panel))
        .fg(theme.colour(Token::Text));
    let height = area.height.saturating_mul(2) / 3;
    let rect = Rect {
        x: area.x,
        y: area.y + area.height - height,
        width: area.width,
        height,
    };
    // The title and the exact target stay fixed at the top; the rest
    // scrolls under them. A target that can't be shown whole on its line
    // cannot be confirmed.
    let header = vec![
        heading(&line(&view.title), theme, false),
        field("to", line(&view.target), theme),
    ];
    // The actually drawn rows (no minimum of one): a pane with no width
    // shows nothing, and a target that wraps is not shown whole.
    let target_rows = Paragraph::new(vec![header[1].clone()])
        .wrap(Wrap { trim: false })
        .line_count(rect.width);
    app.target_shown
        .set(rect.width > 0 && rect.height >= 3 && target_rows == 1 && !view.target.is_empty());
    let mut lines = Vec::new();
    let editable: Vec<_> = view
        .fields
        .iter()
        .filter(|f| f.3)
        .map(|f| f.0.clone())
        .collect();
    for (fid, label, value, _) in &view.fields {
        let focused = editable.get(app.action_focus()) == Some(fid);
        let mut l = field(&line(label), line(value), theme);
        if focused {
            l = l.style(theme.selected());
        }
        lines.push(l);
    }
    for e in &view.effects {
        lines.push(field("effect", line(e), theme));
    }
    if let Some(age_ms) = view.preview_age_ms {
        lines.push(field("preview", format!("read {} ago", age(age_ms)), theme));
    }
    lines.push(field("status", line(&view.status), theme));
    if let Some(r) = &view.reason {
        lines.push(field("reason", line(r), theme));
    }
    if let Some(o) = &view.outcome {
        lines.push(field("outcome", line(o), theme));
    }
    if let Some(op) = &view.op_id {
        lines.push(field("op id", line(op), theme));
    }
    if !view.controls.is_empty() {
        lines.push(Line::from(Span::styled(
            format!("  {}", line(&view.controls.join("  "))),
            theme.fg(Token::Tertiary),
        )));
    }
    frame.render_widget(Clear, rect);
    let head = Rect {
        height: rect.height.min(2),
        ..rect
    };
    frame.render_widget(Paragraph::new(header).style(panel), head);
    let body = Rect {
        y: rect.y + head.height,
        height: rect.height - head.height,
        ..rect
    };
    let lines = pieces(lines);
    let slice = viewport(
        &lines,
        body.width,
        body.height,
        app.action_follow,
        app.action_scroll,
        (&app.action_offset, &app.action_max, &app.action_height),
    );
    frame.render_widget(
        Paragraph::new(lines[slice.from..].to_vec())
            .style(panel)
            .wrap(Wrap { trim: false })
            .scroll((slice.within, 0)),
        body,
    );
}
