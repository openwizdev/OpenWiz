//! Display-only cleaning of untrusted text (session titles, final output,
//! decision wording, server reasons). A draft's bytes for a request are
//! never passed through here: only what is drawn is.

/// Characters that could break a line, drive the terminal or reorder what
/// it shows: controls, line and paragraph separators, bidi controls and
/// zero-width or invisible format marks (the CLI's rule).
pub fn unsafe_for_terminal(c: char) -> bool {
    c.is_control()
        || matches!(
            c,
            '\u{00AD}'
                | '\u{061C}'
                | '\u{180E}'
                | '\u{200B}'..='\u{200F}'
                | '\u{2028}'..='\u{202E}'
                | '\u{2060}'..='\u{206F}'
                | '\u{FEFF}'
                | '\u{FFF9}'..='\u{FFFB}'
        )
}

/// The most characters the renderer draws as one piece of a line: a longer
/// line is drawn as several consecutive pieces, never cut, so scrolling
/// within one piece always fits ratatui's offsets.
pub const DISPLAY_MAX_CHARS: usize = 16_384;

/// One line: every unsafe character, line breaks included, becomes `�`.
pub fn line(text: &str) -> String {
    text.chars()
        .map(|c| {
            if unsafe_for_terminal(c) {
                '\u{FFFD}'
            } else {
                c
            }
        })
        .collect()
}

/// A block: lines kept, tabs as four spaces, every other unsafe character `�`.
pub fn block(text: &str) -> Vec<String> {
    text.split('\n')
        .map(|l| line(&l.replace('\t', "    ")))
        .collect()
}

/// A known age in its largest whole unit, as the CLI prints it.
pub fn age(ms: i64) -> String {
    if ms < 0 {
        return "in the future".into();
    }
    let s = ms / 1_000;
    for (unit, size) in [("d", 86_400), ("h", 3_600), ("m", 60)] {
        if s >= size {
            return format!("{}{unit}", s / size);
        }
    }
    format!("{s}s")
}
