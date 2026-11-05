//! The runtime: worker threads for jobs, the crossterm event loop, and the
//! terminal guard that restores the cursor, raw mode and the main screen on
//! quit, on a handled error, on Ctrl-C and on a panic.

use std::io::{self, Write};
use std::sync::Arc;
use std::sync::mpsc::{Receiver, Sender, channel};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crossterm::event::{
    self, DisableBracketedPaste, EnableBracketedPaste, Event, KeyCode, KeyEvent, KeyEventKind,
    KeyModifiers, KeyboardEnhancementFlags, PopKeyboardEnhancementFlags,
    PushKeyboardEnhancementFlags,
};
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use crossterm::{cursor, execute};
use ratatui::Terminal;
use ratatui::backend::{Backend, CrosstermBackend};

use crate::app::{App, Completion, Flow, Job, Key, KeyPress, Now};
use crate::http::Client;
use crate::render::{Theme, draw};
use crate::transport;

/// The shell and its workers. Every job runs once on its own thread; the
/// app bounds how many reads are in flight.
pub struct Shell {
    pub app: App,
    client: Arc<Client>,
    tx: Sender<Completion>,
    rx: Receiver<Completion>,
    outstanding: usize,
}

impl Shell {
    pub fn new(app: App, client: Client) -> Self {
        let (tx, rx) = channel();
        Self {
            app,
            client: Arc::new(client),
            tx,
            rx,
            outstanding: 0,
        }
    }

    /// Starts every job that is due.
    pub fn pump(&mut self, now: Now) {
        for job in self.app.jobs(now) {
            self.outstanding += 1;
            let client = Arc::clone(&self.client);
            let tx = self.tx.clone();
            std::thread::spawn(move || {
                let completion = match job {
                    Job::Read { id, path, .. } => Completion::Read {
                        id,
                        result: client.get(&path),
                    },
                    Job::Action { id, request, .. } => Completion::Action {
                        id,
                        result: transport::execute(&client, &request),
                    },
                };
                let _ = tx.send(completion);
            });
        }
    }

    /// Applies every finished job.
    pub fn drain(&mut self, now: Now) {
        while let Ok(done) = self.rx.try_recv() {
            self.outstanding -= 1;
            self.app.complete(done, now);
        }
    }

    pub fn outstanding(&self) -> usize {
        self.outstanding
    }

    /// Waits until no job is running (or `limit` passes), applying each
    /// result at `now` and starting what becomes due. Tests use it.
    pub fn settle(&mut self, now: Now, limit: Duration) -> bool {
        let end = Instant::now() + limit;
        self.pump(now);
        while self.outstanding > 0 {
            let left = end.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return false;
            }
            match self.rx.recv_timeout(left) {
                Ok(done) => {
                    self.outstanding -= 1;
                    self.app.complete(done, now);
                    self.pump(now);
                }
                Err(_) => return false,
            }
        }
        true
    }

    pub fn paste(&mut self, text: &str, now: Now) {
        self.app.paste(text, now);
        self.pump(now);
    }

    pub fn key(&mut self, press: KeyPress, now: Now) -> Flow {
        let flow = self.app.key(press, now);
        self.pump(now);
        flow
    }
}

/// Maps a crossterm key event: a press, a reported repeat (which can never
/// confirm) or a reported release (which only re-arms confirmation).
pub fn key_press(event: &KeyEvent, _release_reported: bool) -> Option<KeyPress> {
    let ctrl = event.modifiers.contains(KeyModifiers::CONTROL);
    let key = match event.code {
        KeyCode::Char(c) if ctrl => Key::Ctrl(c.to_ascii_lowercase()),
        KeyCode::Char(c) => Key::Char(c),
        KeyCode::Up => Key::Up,
        KeyCode::Down => Key::Down,
        KeyCode::Enter => Key::Enter,
        KeyCode::Esc => Key::Esc,
        KeyCode::Tab => Key::Tab,
        KeyCode::BackTab => Key::BackTab,
        KeyCode::Backspace => Key::Backspace,
        KeyCode::PageUp => Key::PageUp,
        KeyCode::PageDown => Key::PageDown,
        _ => return None,
    };
    Some(KeyPress {
        key,
        repeat: event.kind == KeyEventKind::Repeat,
        release: event.kind == KeyEventKind::Release,
    })
}

fn now(start: Instant) -> Now {
    Now {
        mono_ms: start.elapsed().as_millis() as u64,
        wall_ms: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0),
    }
}

/// Puts the terminal back however the app ends.
struct Guard {
    enhanced: bool,
}

fn restore(enhanced: bool) {
    let mut out = io::stdout();
    if enhanced {
        let _ = execute!(out, PopKeyboardEnhancementFlags);
    }
    let _ = execute!(
        out,
        DisableBracketedPaste,
        LeaveAlternateScreen,
        cursor::Show
    );
    let _ = disable_raw_mode();
    let _ = out.flush();
}

impl Drop for Guard {
    fn drop(&mut self) {
        restore(self.enhanced);
    }
}

/// Runs the app until the owner quits. Errors come back after the terminal
/// is restored.
pub fn run(app: App, client: Client, theme: Theme) -> io::Result<()> {
    enable_raw_mode()?;
    let mut guard = Guard { enhanced: false };
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        restore(true);
        previous(info);
    }));
    // Bracketed paste: pasted text arrives as one paste, never as keys.
    execute!(
        io::stdout(),
        EnterAlternateScreen,
        cursor::Hide,
        EnableBracketedPaste
    )?;
    let enhanced = matches!(
        crossterm::terminal::supports_keyboard_enhancement(),
        Ok(true)
    );
    if enhanced {
        execute!(
            io::stdout(),
            PushKeyboardEnhancementFlags(KeyboardEnhancementFlags::REPORT_EVENT_TYPES)
        )?;
        guard.enhanced = true;
    }
    // A terminal without a size cannot be drawn: a handled failure, after
    // which the guard restores the terminal like any other exit.
    match crossterm::terminal::size() {
        Ok((cols, rows)) if cols > 0 && rows > 0 => {}
        _ => return Err(io::Error::other("the terminal reports no size")),
    }
    let mut terminal = Terminal::new(CrosstermBackend::new(io::stdout()))?;
    let start = Instant::now();
    let mut shell = Shell::new(app, client);
    shell.app.key_release_reported = enhanced;
    let result = event_loop(&mut terminal, &mut shell, start, &theme);
    drop(terminal);
    drop(guard);
    result
}

fn event_loop<B: Backend>(
    terminal: &mut Terminal<B>,
    shell: &mut Shell,
    start: Instant,
    theme: &Theme,
) -> io::Result<()>
where
    B::Error: Into<io::Error>,
{
    loop {
        let t = now(start);
        shell.drain(t);
        shell.pump(t);
        terminal
            .draw(|frame| draw(frame, &shell.app, t, theme))
            .map_err(Into::into)?;
        if event::poll(Duration::from_millis(250))? {
            match event::read()? {
                Event::Key(k) => {
                    if let Some(press) = key_press(&k, shell.app.key_release_reported)
                        && shell.key(press, now(start)) == Flow::Quit
                    {
                        return Ok(());
                    }
                }
                Event::Paste(text) => shell.paste(&text, now(start)),
                Event::Resize(_, _) => terminal.autoresize().map_err(Into::into)?,
                _ => {}
            }
        }
    }
}
