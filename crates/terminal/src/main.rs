//! `openwiz-terminal`, normally started by `openwiz` or `openwiz ui` from the
//! same installed directory. Needs a terminal on stdin and stdout.

use std::io::IsTerminal;
use std::process::ExitCode;

use openwiz_terminal::app::App;
use openwiz_terminal::config::{self, ALLOWED_HOST_ENV, Invocation};
use openwiz_terminal::http::Client;
use openwiz_terminal::render::Theme;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let settings = match config::parse(&args, std::env::var_os(ALLOWED_HOST_ENV)) {
        Ok(Invocation::Help) => {
            print!("{}", config::usage());
            return ExitCode::SUCCESS;
        }
        Ok(Invocation::Run(settings)) => settings,
        Err(why) => {
            eprintln!("openwiz-terminal: {why}");
            return ExitCode::from(2);
        }
    };
    if !(std::io::stdin().is_terminal() && std::io::stdout().is_terminal()) {
        eprintln!("openwiz-terminal: needs a terminal on stdin and stdout; nothing was opened");
        return ExitCode::from(2);
    }
    let theme = Theme::from_env(|k| std::env::var(k).ok());
    let client = Client::new(&settings);
    match openwiz_terminal::run::run(App::new(settings), client, theme) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("openwiz-terminal: {e}; the terminal was restored and nothing was sent");
            ExitCode::from(1)
        }
    }
}
