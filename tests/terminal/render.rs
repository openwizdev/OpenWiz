//! CP4: the M6 language in cells. Screens at 120×40, 80×24 and a very small
//! size, through ratatui's test backend: words and shapes for every state,
//! gold only for Needs you, purple for live and selected, readable without
//! true colour, colour or UTF-8, and no raw control bytes from data.
//!
//! With `OPENWIZ_RENDER_OUT=<dir>`, each render is also written there as text
//! and as coloured HTML, for review.

use openwiz_terminal::app::{App, Key, KeyPress, Now};
use openwiz_terminal::ratatui::Terminal;
use openwiz_terminal::ratatui::backend::TestBackend;
use openwiz_terminal::ratatui::buffer::Buffer;
use openwiz_terminal::ratatui::style::Color;
use openwiz_terminal::render::{Colour, Theme, Token, draw};

use super::support::{FixtureServer, Reply, SETTLE, fixture, now, shell};

pub fn buffer(app: &App, at: Now, width: u16, height: u16, theme: Theme) -> Buffer {
    let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
    terminal.draw(|f| draw(f, app, at, &theme)).unwrap();
    terminal.backend().buffer().clone()
}

pub fn rows(buffer: &Buffer) -> Vec<String> {
    let area = buffer.area;
    (0..area.height)
        .map(|y| {
            (0..area.width)
                .map(|x| buffer[(x, y)].symbol().to_owned())
                .collect::<String>()
                .trim_end()
                .to_owned()
        })
        .collect()
}

/// The screen's text at a size, in the true-colour UTF-8 theme.
pub fn text(app: &App, at: Now, width: u16, height: u16) -> String {
    rows(&buffer(app, at, width, height, Theme::TRUE_UNICODE)).join("\n")
}

fn rgb(token: Token) -> Color {
    let (r, g, b) = token.rgb();
    Color::Rgb(r, g, b)
}

/// Every cell whose symbol starts `word`'s first character at the row/col
/// where `word` begins.
fn find(buffer: &Buffer, word: &str) -> Option<(u16, u16)> {
    let lines = rows(buffer);
    for (y, line) in lines.iter().enumerate() {
        if let Some(byte) = line.find(word) {
            let x = line[..byte].chars().count() as u16;
            return Some((x, y as u16));
        }
    }
    None
}

fn save(name: &str, buffer: &Buffer) {
    let Some(dir) = std::env::var_os("OPENWIZ_RENDER_OUT") else {
        return;
    };
    let dir = std::path::PathBuf::from(dir);
    std::fs::write(
        dir.join(format!("{name}.txt")),
        rows(buffer).join("\n") + "\n",
    )
    .unwrap();
    let css = |c: Color, fallback: &str| match c {
        Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        _ => fallback.to_owned(),
    };
    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><style>body{background:#000;margin:16px}pre{font:14px/1.25 ui-monospace,Menlo,monospace;margin:0}</style><pre>",
    );
    let area = buffer.area;
    for y in 0..area.height {
        // One span per run of cells with the same style.
        let mut run: Option<(String, String)> = None;
        let flush = |run: &mut Option<(String, String)>, html: &mut String| {
            if let Some((style, text)) = run.take() {
                html.push_str(&format!("<span style=\"{style}\">{text}</span>"));
            }
        };
        for x in 0..area.width {
            let cell = &buffer[(x, y)];
            let bold = cell
                .modifier
                .contains(openwiz_terminal::ratatui::style::Modifier::BOLD);
            let style = format!(
                "color:{};background:{}{}",
                css(cell.fg, "#e8eaed"),
                css(cell.bg, "#0e0f11"),
                if bold { ";font-weight:700" } else { "" }
            );
            let symbol = cell
                .symbol()
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            match &mut run {
                Some((s, text)) if *s == style => text.push_str(&symbol),
                _ => {
                    flush(&mut run, &mut html);
                    run = Some((style, symbol));
                }
            }
        }
        flush(&mut run, &mut html);
        html.push('\n');
    }
    html.push_str("</pre>\n");
    std::fs::write(dir.join(format!("{name}.html")), html).unwrap();
}

fn loaded() -> (FixtureServer, openwiz_terminal::run::Shell) {
    let server = FixtureServer::home();
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    (server, shell)
}

#[test]
fn home_at_120x40_uses_the_m6_tokens_words_and_shapes() {
    let (_server, shell) = loaded();
    let b = buffer(&shell.app, now(0), 120, 40, Theme::TRUE_UNICODE);
    save("home-120x40", &b);
    let screen = rows(&b).join("\n");
    // Navigation keeps its three destinations, Home selected.
    for nav in [
        "OpenWiz",
        "Home",
        "Sessions",
        "Fleets",
        "connected",
        "127.0.0.1:",
    ] {
        assert!(screen.contains(nav), "{nav}:\n{screen}");
    }
    // Canvas behind the navigation, sheet behind the content.
    assert_eq!(b[(0, 0)].bg, rgb(Token::Canvas));
    assert_eq!(b[(60, 30)].bg, rgb(Token::Sheet));
    // Gold only for Needs you: its heading, numbers and diamonds.
    let (x, y) = find(&b, "Needs you").unwrap();
    assert_eq!(b[(x, y)].fg, rgb(Token::Attention));
    let (x, y) = find(&b, "◆ #9001").unwrap();
    assert_eq!(b[(x, y)].fg, rgb(Token::Attention));
    let gold: Vec<_> = (0..40)
        .flat_map(|y| (0..120).map(move |x| (x, y)))
        .filter(|&(x, y)| b[(x, y)].fg == rgb(Token::Attention))
        .map(|(x, y)| b[(x, y)].symbol().to_owned())
        .collect();
    let gold_text: String = gold.concat();
    for allowed in gold_text.chars() {
        assert!(
            "Needs you needs12◆▌·".contains(allowed),
            "gold used outside Needs you: {gold_text:?}"
        );
    }
    // Live is purple and carries a shape and a word, never colour alone.
    let (x, y) = find(&b, "◉ Synthetic active session").unwrap();
    assert_eq!(b[(x, y)].fg, rgb(Token::Live));
    assert!(screen.contains("Synthetic active session · active"));
    assert!(screen.contains("○ Synthetic idle session · idle"));
    // The selected destination: a purple edge on the selected surface.
    let (x, y) = find(&b, "▌Home").unwrap();
    assert_eq!(b[(x, y)].fg, rgb(Token::Live));
    assert_eq!(b[(x + 1, y)].bg, rgb(Token::Selected));
    // Untrusted control characters never reach the terminal.
    assert!(!screen.contains('\u{1b}') && !screen.contains('\u{202e}'));
    assert!(screen.contains("Synthetic �[31mred� title"), "{screen}");
}

#[test]
fn every_screen_is_readable_at_80x24_and_a_very_small_resize() {
    let (_server, mut shell) = loaded();
    let mut screens = Vec::new();
    for (name, keys) in [
        ("home", vec![]),
        ("needs-you-item", vec![Key::Char('1')]),
        ("sessions", vec![Key::Esc, Key::Char('s'), Key::Down]),
        ("session-detail", vec![Key::Enter]),
        ("fleets", vec![Key::Esc, Key::Char('f'), Key::Down]),
        ("fleet-detail", vec![Key::Enter]),
    ] {
        for key in keys {
            shell.key(KeyPress::press(key), now(1));
        }
        assert!(shell.settle(now(1), SETTLE));
        for (w, h) in [(120, 40), (80, 24), (36, 10)] {
            let b = buffer(&shell.app, now(1), w, h, Theme::TRUE_UNICODE);
            save(&format!("{name}-{w}x{h}"), &b);
            let screen = rows(&b).join("\n");
            // Navigation survives every size; the active destination is marked.
            assert!(screen.contains("Home"), "{name} {w}x{h}:\n{screen}");
            assert!(screen.contains("Fleets"), "{name} {w}x{h}:\n{screen}");
            assert!(screen.contains("▌"), "{name} {w}x{h}: no selection mark");
            // A key hint stays on the last row.
            let last = rows(&b).last().cloned().unwrap();
            assert!(
                last.contains("q quit") || last.contains("Esc"),
                "{name} {w}x{h}: {last:?}"
            );
            screens.push((name, w, screen));
        }
    }
    let at = |n: &str, w: u16| {
        screens
            .iter()
            .find(|(name, width, _)| *name == n && *width == w)
            .map(|(_, _, s)| s.clone())
            .unwrap()
    };
    // Narrow screens keep the content's first words, not clipped away.
    assert!(at("home", 80).contains("Needs you"));
    assert!(at("home", 36).contains("Needs you"));
    assert!(at("session-detail", 36).contains("Session"));
    assert!(at("fleet-detail", 80).contains("Fleet #9001"));
}

#[test]
fn readable_without_true_colour_colour_or_utf8() {
    let (_server, shell) = loaded();
    // 256 colours: the nearest indexed cells.
    let indexed = Theme {
        colour: Colour::Indexed,
        unicode: true,
    };
    let b = buffer(&shell.app, now(0), 80, 24, indexed);
    let (x, y) = find(&b, "Needs you").unwrap();
    assert_eq!(b[(x, y)].fg, Color::Indexed(214));
    // NO_COLOR: no colour anywhere; selection is reversed, state in words.
    let none = Theme {
        colour: Colour::None,
        unicode: true,
    };
    let b = buffer(&shell.app, now(0), 80, 24, none);
    save("home-80x24-no-color", &b);
    for y in 0..24 {
        for x in 0..80 {
            assert!(matches!(b[(x, y)].fg, Color::Reset), "fg at {x},{y}");
            assert!(matches!(b[(x, y)].bg, Color::Reset), "bg at {x},{y}");
        }
    }
    // ASCII: no special glyphs, distinct ASCII shapes instead.
    let ascii = Theme {
        colour: Colour::True,
        unicode: false,
    };
    let b = buffer(&shell.app, now(0), 120, 40, ascii);
    save("home-120x40-ascii", &b);
    let screen = rows(&b).join("\n");
    for glyph in ["◆", "◉", "○", "◌", "✓", "▌", "·", "█", "░"] {
        assert!(!screen.contains(glyph), "{glyph} in the ASCII theme");
    }
    assert!(screen.contains("1 ! #9001 spec confirmation"), "{screen}");
    assert!(
        screen.contains("@ Synthetic active session - active"),
        "{screen}"
    );
    assert!(
        screen.contains("o Synthetic idle session - idle"),
        "{screen}"
    );
    assert!(screen.contains(">Home"), "{screen}");
    // The environment picks the theme.
    let env = |pairs: &'static [(&'static str, &'static str)]| {
        Theme::from_env(move |k| {
            pairs
                .iter()
                .find(|(n, _)| *n == k)
                .map(|(_, v)| v.to_string())
        })
    };
    assert_eq!(
        env(&[("COLORTERM", "truecolor"), ("LANG", "en_US.UTF-8")]),
        Theme::TRUE_UNICODE
    );
    assert_eq!(
        env(&[("NO_COLOR", "1"), ("LANG", "C")]).colour,
        Colour::None
    );
    assert!(!env(&[("LANG", "C")]).unicode);
    assert_eq!(env(&[]).colour, Colour::Indexed);
}

#[test]
fn an_unavailable_server_and_partial_reads_render_their_words() {
    let server = FixtureServer::home();
    server.route(
        "/api/v1/decisions",
        Reply::ok(fixture("decisions-partial.json")),
    );
    server.route(
        "/api/v1/inventory",
        Reply::status(502, "read_failed", "thread list timed out"),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let b = buffer(&shell.app, now(0), 120, 40, Theme::TRUE_UNICODE);
    save("home-partial-120x40", &b);
    let screen = rows(&b).join("\n");
    assert!(screen.contains("decisions: partial · 1 gap"), "{screen}");
    assert!(
        screen.contains("sessions: unavailable · HTTP 502 read_failed: thread list timed out"),
        "{screen}"
    );
    assert!(
        screen.contains("1 ◆ #9003 held"),
        "fleet facts still show:\n{screen}"
    );
}
