use std::io::{self, Write};
use std::process::{Command, Stdio};

use crate::{EXIT_OK, EXIT_READ_FAILED, EXIT_USAGE, UsageError, clean};

pub const URL: &str = "https://openwiz.dev/pro/";
pub const USAGE: &str = "  openwiz pro [--print]\n";
pub const HELP: &str = "pro [--print]
  Prints https://openwiz.dev/pro/ and, in an interactive terminal on macOS or
  Linux, opens it in the default browser (open / xdg-open). --print or a
  non-interactive terminal only prints. Reads no account and starts no payment.
";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Platform {
    MacOs,
    Linux,
    Other,
}

impl Platform {
    pub fn current() -> Self {
        if cfg!(target_os = "macos") {
            Self::MacOs
        } else if cfg!(target_os = "linux") {
            Self::Linux
        } else {
            Self::Other
        }
    }

    pub fn opener(self) -> Option<&'static str> {
        match self {
            Self::MacOs => Some("open"),
            Self::Linux => Some("xdg-open"),
            Self::Other => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Parsed {
    Help,
    Open { print_only: bool },
}

pub fn parse(args: &[String]) -> Result<Parsed, UsageError> {
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Ok(Parsed::Help);
    }
    let mut print_only = false;
    for arg in args {
        match arg.as_str() {
            "--print" if !print_only => print_only = true,
            "--print" => return Err(UsageError("pro: --print is given once".to_owned())),
            other => {
                return Err(UsageError(format!(
                    "pro: unknown option or argument {}",
                    clean(other)
                )));
            }
        }
    }
    Ok(Parsed::Open { print_only })
}

pub trait Opener {
    fn open(&self, program: &str, url: &str) -> io::Result<()>;
}

pub struct ProcessOpener;

impl Opener for ProcessOpener {
    fn open(&self, program: &str, url: &str) -> io::Result<()> {
        let status = Command::new(program)
            .arg(url)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()?;
        if status.success() {
            Ok(())
        } else {
            Err(io::Error::other(format!(
                "{program} exited with status {status}"
            )))
        }
    }
}

pub struct Context<'a> {
    pub interactive: bool,
    pub platform: Platform,
    pub opener: &'a dyn Opener,
}

pub fn run_system(
    args: &[String],
    interactive: bool,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let opener = ProcessOpener;
    let ctx = Context {
        interactive,
        platform: Platform::current(),
        opener: &opener,
    };
    run(args, &ctx, stdout, stderr)
}

pub fn run(
    args: &[String],
    ctx: &Context<'_>,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let parsed = match parse(args) {
        Ok(parsed) => parsed,
        Err(UsageError(message)) => {
            let _ = writeln!(stderr, "openwiz: {message} (see openwiz --help)");
            return EXIT_USAGE;
        }
    };
    match parsed {
        Parsed::Help => {
            let text = crate::help();
            if stdout
                .write_all(text.as_bytes())
                .and_then(|()| stdout.flush())
                .is_err()
            {
                let _ = writeln!(stderr, "openwiz: could not write output");
                return EXIT_READ_FAILED;
            }
            EXIT_OK
        }
        Parsed::Open { print_only } => {
            if writeln!(stdout, "{URL}")
                .and_then(|()| stdout.flush())
                .is_err()
            {
                let _ = writeln!(stderr, "openwiz: could not write output");
                return EXIT_READ_FAILED;
            }
            if !print_only
                && ctx.interactive
                && let Some(program) = ctx.platform.opener()
                && let Err(error) = ctx.opener.open(program, URL)
            {
                let _ = writeln!(
                    stderr,
                    "openwiz: could not open {URL} with {program}: {}",
                    clean(&error.to_string())
                );
            }
            EXIT_OK
        }
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::io;

    use super::*;

    struct RecordingOpener {
        calls: RefCell<Vec<(String, String)>>,
        fail: Option<&'static str>,
    }

    impl RecordingOpener {
        fn ok() -> Self {
            Self {
                calls: RefCell::new(Vec::new()),
                fail: None,
            }
        }

        fn failing(message: &'static str) -> Self {
            Self {
                calls: RefCell::new(Vec::new()),
                fail: Some(message),
            }
        }

        fn calls(&self) -> Vec<(String, String)> {
            self.calls.borrow().clone()
        }
    }

    impl Opener for RecordingOpener {
        fn open(&self, program: &str, url: &str) -> io::Result<()> {
            self.calls
                .borrow_mut()
                .push((program.to_owned(), url.to_owned()));
            match self.fail {
                Some(message) => Err(io::Error::other(message)),
                None => Ok(()),
            }
        }
    }

    fn run_case(
        args: &[&str],
        interactive: bool,
        platform: Platform,
        opener: &RecordingOpener,
    ) -> (i32, String, String) {
        let args: Vec<String> = args.iter().map(|s| (*s).to_owned()).collect();
        let ctx = Context {
            interactive,
            platform,
            opener,
        };
        let (mut out, mut err) = (Vec::new(), Vec::new());
        let code = run(&args, &ctx, &mut out, &mut err);
        (
            code,
            String::from_utf8(out).unwrap(),
            String::from_utf8(err).unwrap(),
        )
    }

    #[test]
    fn interactive_macos_and_linux_print_and_invoke_platform_opener() {
        for (platform, expected_program) in
            [(Platform::MacOs, "open"), (Platform::Linux, "xdg-open")]
        {
            let opener = RecordingOpener::ok();
            let (code, out, err) = run_case(&[], true, platform, &opener);
            assert_eq!(code, EXIT_OK);
            assert_eq!(out, format!("{URL}\n"));
            assert!(err.is_empty(), "{err}");
            assert_eq!(
                opener.calls(),
                vec![(expected_program.to_owned(), URL.to_owned())]
            );
        }
    }

    #[test]
    fn print_flag_non_interactive_and_other_platforms_only_print() {
        for (args, interactive, platform) in [
            (&["--print"][..], true, Platform::MacOs),
            (&["--print"][..], true, Platform::Linux),
            (&[][..], false, Platform::MacOs),
            (&[][..], false, Platform::Linux),
            (&[][..], true, Platform::Other),
        ] {
            let opener = RecordingOpener::ok();
            let (code, out, err) = run_case(args, interactive, platform, &opener);
            assert_eq!(code, EXIT_OK);
            assert_eq!(out, format!("{URL}\n"));
            assert!(err.is_empty(), "{err}");
            assert!(opener.calls().is_empty(), "{:?}", opener.calls());
        }
    }

    #[test]
    fn opener_failure_still_prints_url_and_reports_on_stderr() {
        let opener = RecordingOpener::failing("synthetic opener failure");
        let (code, out, err) = run_case(&[], true, Platform::Linux, &opener);
        assert_eq!(code, EXIT_OK);
        assert_eq!(out, format!("{URL}\n"));
        assert!(err.contains("xdg-open"), "{err}");
        assert!(err.contains("synthetic opener failure"), "{err}");
    }

    #[test]
    fn help_and_usage_errors_never_invoke_opener() {
        for help_arg in ["--help", "-h"] {
            let opener = RecordingOpener::ok();
            let (code, out, err) = run_case(&[help_arg], true, Platform::MacOs, &opener);
            assert_eq!(code, EXIT_OK);
            assert!(out.contains(USAGE), "{out}");
            assert!(out.contains(HELP), "{out}");
            assert!(err.is_empty(), "{err}");
            assert!(opener.calls().is_empty());
        }
        for bad in [
            &["--unknown"][..],
            &["--print=true"][..],
            &["--print", "--print"][..],
            &["extra"][..],
        ] {
            let opener = RecordingOpener::ok();
            let (code, out, err) = run_case(bad, true, Platform::MacOs, &opener);
            assert_eq!(code, EXIT_USAGE, "{bad:?}");
            assert!(out.is_empty(), "{out}");
            assert!(err.starts_with("openwiz:"), "{err}");
            assert!(opener.calls().is_empty());
        }
    }
}
