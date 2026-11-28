use std::ffi::OsString;
use std::io::Write;

use crate::response;

#[path = "loop_apply.rs"]
mod loop_apply;
#[path = "loop_export.rs"]
mod loop_export;
#[path = "loop_plan.rs"]
mod loop_plan;
#[path = "loop_validate.rs"]
mod loop_validate;

pub const USAGE: &str = "  openwiz loop validate <path>... [--catalog] [--json]
  openwiz loop export --project <project> [--out <dir>] [--json]
  openwiz loop plan <path>... --project <project> [--adopt <id>=<loop>]... [--json]
  openwiz loop apply <id> --project <project> [--from <path>] [--adopt <id>=<loop>] [--json]
";
pub const HELP: &str = "loop validate/export/plan/apply
  Loop files in the WizLoops format, with Cloudroom as the adapter
  (contracts/loop-cli.v1.md). validate checks loop files and names each
  problem by file and field. plan prints the exact room-cli commands and the
  differences against room-cli loop list, and changes nothing. apply runs
  only those commands for one id, once, then reads the loop back and reports
  any difference; an unclear outcome exits 6 and is never retried.
";

pub fn escape_untrusted(text: &str) -> String {
    crate::clean(text)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Runner {
    Cloudroom,
    T3,
    Cron,
    Systemd,
    GithubActions,
}

impl Runner {
    pub fn from_name(name: &str) -> Option<Self> {
        Some(match name {
            "cloudroom" => Self::Cloudroom,
            "t3" => Self::T3,
            "cron" => Self::Cron,
            "systemd" => Self::Systemd,
            "github-actions" => Self::GithubActions,
            _ => return None,
        })
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Cloudroom => "cloudroom",
            Self::T3 => "t3",
            Self::Cron => "cron",
            Self::Systemd => "systemd",
            Self::GithubActions => "github-actions",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Command {
    Validate,
    Export,
    Plan,
    Apply,
}

impl Command {
    pub fn from_word(word: &str) -> Option<Self> {
        Some(match word {
            "validate" => Self::Validate,
            "export" => Self::Export,
            "plan" => Self::Plan,
            "apply" => Self::Apply,
            _ => return None,
        })
    }

    pub fn word(self) -> &'static str {
        match self {
            Self::Validate => "validate",
            Self::Export => "export",
            Self::Plan => "plan",
            Self::Apply => "apply",
        }
    }

    pub fn ticket(self) -> u32 {
        match self {
            Self::Validate => 790,
            Self::Export => 791,
            Self::Plan => 792,
            Self::Apply => 793,
        }
    }

    pub fn runners(self) -> &'static [Runner] {
        match self {
            Self::Validate | Self::Export | Self::Plan | Self::Apply => &[],
        }
    }

    fn options(self) -> &'static [&'static str] {
        match self {
            Self::Validate => &["--catalog"],
            Self::Export => &["--project", "--out"],
            Self::Plan => &["--project", "--adopt"],
            Self::Apply => &["--project", "--from", "--adopt"],
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Args {
    pub command: Command,
    pub operands: Vec<String>,
    pub catalog: bool,
    pub project: Option<String>,
    pub out: Option<String>,
    pub file: Option<String>,
    pub adopt: Vec<(String, String)>,
    pub json: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Parsed {
    Run(Args),
    Runner(Runner, Args),
    Help { json: bool },
}

pub fn handles(word: Option<&str>) -> bool {
    word.and_then(Command::from_word).is_some()
}

fn json_selected(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|a| *a != "--")
        .any(|a| a == "--json")
}

pub fn parse(args: &[OsString]) -> Result<Parsed, String> {
    parse_with(args, Command::runners)
}

fn select_runner(
    command: Command,
    value: Option<&str>,
    selected: &mut Option<Runner>,
    available: fn(Command) -> &'static [Runner],
) -> Result<(), String> {
    let word = command.word();
    if command == Command::Validate {
        return Err(format!("loop {word} has no option --runner"));
    }
    let name = value
        .filter(|v| !v.is_empty() && !v.starts_with('-'))
        .ok_or("--runner needs a value")?;
    let runner = Runner::from_name(name).ok_or_else(|| {
        format!("--runner needs one of cloudroom, t3, cron, systemd or github-actions, not {name}")
    })?;
    if selected.replace(runner).is_some() {
        return Err("--runner appears more than once".into());
    }
    if !available(command).contains(&runner) {
        return Err(format!("loop {word} cannot use --runner {name}"));
    }
    Ok(())
}

pub fn parse_with(
    args: &[OsString],
    available: fn(Command) -> &'static [Runner],
) -> Result<Parsed, String> {
    let strings: Vec<&str> = args
        .iter()
        .map(|a| a.to_str())
        .collect::<Option<_>>()
        .ok_or("an argument is not valid UTF-8")?;
    let (word, rest) = strings.split_first().ok_or("missing loop command")?;
    let command = Command::from_word(word).ok_or("unknown loop command")?;
    let json = json_selected(args);
    let options_end = rest.iter().position(|a| *a == "--").unwrap_or(rest.len());
    if rest[..options_end]
        .iter()
        .any(|a| *a == "--help" || *a == "-h")
    {
        return Ok(Parsed::Help { json });
    }
    let mut parsed = Args {
        command,
        operands: Vec::new(),
        catalog: false,
        project: None,
        out: None,
        file: None,
        adopt: Vec::new(),
        json,
    };
    let mut seen_json = false;
    let mut runner = None;
    let mut options = rest[..options_end].iter();
    while let Some(&token) = options.next() {
        if !token.starts_with('-') {
            parsed.operands.push(token.to_owned());
            continue;
        }
        if token == "--json" {
            if std::mem::replace(&mut seen_json, true) {
                return Err("--json appears more than once".into());
            }
            continue;
        }
        if token == "--runner" {
            select_runner(command, options.next().copied(), &mut runner, available)?;
            continue;
        }
        if !command.options().contains(&token) {
            return Err(format!("loop {word} has no option {token}"));
        }
        if token == "--catalog" {
            if std::mem::replace(&mut parsed.catalog, true) {
                return Err("--catalog appears more than once".into());
            }
            continue;
        }
        let value = *options
            .next()
            .filter(|v| !v.is_empty() && !v.starts_with('-') && !v.chars().any(char::is_control))
            .ok_or_else(|| format!("{token} needs a value"))?;
        let slot = match token {
            "--project" => &mut parsed.project,
            "--out" => &mut parsed.out,
            "--from" => &mut parsed.file,
            _ => {
                let (id, target) = value
                    .split_once('=')
                    .filter(|(id, target)| !id.is_empty() && !target.is_empty())
                    .ok_or("--adopt needs <id>=<loop>")?;
                if command == Command::Apply && !parsed.adopt.is_empty() {
                    return Err("--adopt appears more than once".into());
                }
                parsed.adopt.push((id.to_owned(), target.to_owned()));
                continue;
            }
        };
        if slot.replace(value.to_owned()).is_some() {
            return Err(format!("{token} appears more than once"));
        }
    }
    parsed
        .operands
        .extend(rest.iter().skip(options_end + 1).map(|a| (*a).to_owned()));
    let operands_ok = match command {
        Command::Validate | Command::Plan => !parsed.operands.is_empty(),
        Command::Export => parsed.operands.is_empty(),
        Command::Apply => parsed.operands.len() == 1,
    };
    if !operands_ok {
        return Err(format!("wrong operands for loop {word}"));
    }
    let cloudroom = matches!(runner, None | Some(Runner::Cloudroom));
    if command != Command::Validate && cloudroom && parsed.project.is_none() {
        return Err(format!("loop {word} needs --project <project>"));
    }
    Ok(match runner {
        None => Parsed::Run(parsed),
        Some(runner) => Parsed::Runner(runner, parsed),
    })
}

pub fn run(args: &[OsString], stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    let name = args
        .first()
        .and_then(|a| a.to_str())
        .and_then(Command::from_word)
        .map_or("unknown", |c| match c {
            Command::Validate => "loop.validate",
            Command::Export => "loop.export",
            Command::Plan => "loop.plan",
            Command::Apply => "loop.apply",
        });
    match parse(args) {
        Ok(Parsed::Help { json }) => {
            let text = format!("Usage:\n{USAGE}\n{HELP}");
            i32::from(
                stdout
                    .write_all(response::help(json, text).as_bytes())
                    .is_err(),
            )
        }
        Ok(Parsed::Runner(runner, _)) => usage_error(
            args,
            name,
            &format!("no route for --runner {}", runner.name()),
            stdout,
            stderr,
        ),
        Ok(Parsed::Run(args)) if args.command == Command::Validate => {
            loop_validate::run(&args, stdout, stderr)
        }
        Ok(Parsed::Run(args)) if args.command == Command::Export => {
            loop_export::run(&args, stdout, stderr)
        }
        Ok(Parsed::Run(args)) if args.command == Command::Plan => {
            loop_plan::run(&args, stdout, stderr)
        }
        Ok(Parsed::Run(args)) => loop_apply::run(&args, stdout, stderr),
        Err(why) => usage_error(args, name, &why, stdout, stderr),
    }
}

fn usage_error(
    args: &[OsString],
    name: &str,
    why: &str,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let help = match name {
        "unknown" => "openwiz --help".to_owned(),
        _ => format!("openwiz {} --help", name.replace('.', " ")),
    };
    let text = writeln!(
        stderr,
        "openwiz: usage: {}; nothing was read (see {help})",
        escape_untrusted(why)
    );
    let written = if json_selected(args) {
        let doc = serde_json::json!({
            "schema": "openwiz.cli-error.v1", "command": name, "exit_code": 2,
            "error": {"kind": "usage", "message": format!("Invalid loop arguments: {why}.")}
        });
        writeln!(stdout, "{doc}")
    } else {
        text
    };
    if written.is_err() { 1 } else { 2 }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn run_args(args: &[&str]) -> (i32, String, String) {
        let args: Vec<OsString> = args.iter().map(OsString::from).collect();
        let (mut out, mut err) = (Vec::new(), Vec::new());
        let code = run(&args, &mut out, &mut err);
        (
            code,
            String::from_utf8(out).unwrap(),
            String::from_utf8(err).unwrap(),
        )
    }

    #[test]
    fn arguments_follow_the_contract() {
        let project = Some("prj_syn_0001".to_owned());
        let accepted: [(&[&str], Args); 5] = [
            (
                &["validate", "a.md", "--catalog", "b", "--", "-dash.md"],
                Args {
                    command: Command::Validate,
                    operands: vec!["a.md".into(), "b".into(), "-dash.md".into()],
                    catalog: true,
                    project: None,
                    out: None,
                    file: None,
                    adopt: vec![],
                    json: false,
                },
            ),
            (
                &[
                    "export",
                    "--out",
                    "exported",
                    "--project",
                    "prj_syn_0001",
                    "--json",
                ],
                Args {
                    command: Command::Export,
                    operands: vec![],
                    catalog: false,
                    project: project.clone(),
                    out: Some("exported".into()),
                    file: None,
                    adopt: vec![],
                    json: true,
                },
            ),
            (
                &[
                    "plan",
                    "a.md",
                    "--project",
                    "prj_syn_0001",
                    "--adopt",
                    "a=loop_syn_1",
                    "--adopt",
                    "b=loop_syn_2",
                    "--",
                    "--json",
                ],
                Args {
                    command: Command::Plan,
                    operands: vec!["a.md".into(), "--json".into()],
                    catalog: false,
                    project: project.clone(),
                    out: None,
                    file: None,
                    adopt: vec![
                        ("a".into(), "loop_syn_1".into()),
                        ("b".into(), "loop_syn_2".into()),
                    ],
                    json: false,
                },
            ),
            (
                &[
                    "apply",
                    "a",
                    "--project",
                    "prj_syn_0001",
                    "--from",
                    "x/a.md",
                    "--adopt",
                    "a=loop_syn_1",
                ],
                Args {
                    command: Command::Apply,
                    operands: vec!["a".into()],
                    catalog: false,
                    project: project.clone(),
                    out: None,
                    file: Some("x/a.md".into()),
                    adopt: vec![("a".into(), "loop_syn_1".into())],
                    json: false,
                },
            ),
            (
                &["apply", "--json", "--project", "prj_syn_0001", "a=b"],
                Args {
                    command: Command::Apply,
                    operands: vec!["a=b".into()],
                    catalog: false,
                    project,
                    out: None,
                    file: None,
                    adopt: vec![],
                    json: true,
                },
            ),
        ];
        for (args, expected) in accepted {
            let os: Vec<OsString> = args.iter().map(OsString::from).collect();
            assert_eq!(parse(&os), Ok(Parsed::Run(expected)), "{args:?}");
        }
        for args in [
            &["validate"][..],
            &["validate", "a.md", "--project", "prj_syn_0001"],
            &["validate", "a.md", "--catalog", "--catalog"],
            &["validate", "a.md", "--strict"],
            &["export"],
            &["export", "extra", "--project", "prj_syn_0001"],
            &["export", "--project=prj_syn_0001"],
            &["export", "--project", "--json"],
            &["export", "--project", ""],
            &[
                "export",
                "--project",
                "prj_syn_0001",
                "--project",
                "prj_syn_0002",
            ],
            &["export", "--project", "prj_syn_0001", "--out"],
            &["plan", "--project", "prj_syn_0001"],
            &["plan", "a.md"],
            &["plan", "a.md", "--project", "prj_syn_0001", "--adopt", "a"],
            &[
                "plan",
                "a.md",
                "--project",
                "prj_syn_0001",
                "--adopt",
                "=loop_syn_1",
            ],
            &[
                "plan",
                "a.md",
                "--project",
                "prj_syn_0001",
                "--from",
                "a.md",
            ],
            &["apply", "--project", "prj_syn_0001"],
            &["apply", "a", "b", "--project", "prj_syn_0001"],
            &["apply", "a"],
            &[
                "apply",
                "a",
                "--project",
                "prj_syn_0001",
                "--adopt",
                "a=l1",
                "--adopt",
                "a=l2",
            ],
            &["apply", "a", "--project", "prj_syn_0001", "--out", "x"],
            &[
                "apply",
                "a",
                "--project",
                "prj_syn_0001",
                "--from",
                "a\tb.md",
            ],
        ] {
            let (code, out, err) = run_args(args);
            assert_eq!(code, 2, "{args:?}");
            assert_eq!(out.is_empty(), !args.contains(&"--json"), "{args:?}");
            assert!(err.starts_with("openwiz: usage: "), "{args:?}: {err}");
            let mut json = args.to_vec();
            json.insert(1, "--json");
            let (code, out, _) = run_args(&json);
            assert_eq!(code, 2, "{json:?}");
            let doc: Value = serde_json::from_str(&out).unwrap();
            assert_eq!(doc["schema"], "openwiz.cli-error.v1", "{json:?}");
            assert_eq!(doc["command"], format!("loop.{}", args[0]));
            assert_eq!(
                (&doc["exit_code"], &doc["error"]["kind"]),
                (&2.into(), &"usage".into())
            );
        }
        let (code, out, _) = run_args(&["validate", "a.md", "--json", "--json"]);
        assert_eq!(code, 2);
        assert_eq!(
            serde_json::from_str::<Value>(&out).unwrap()["error"]["kind"],
            "usage"
        );
        let bad = [OsString::from("validate"), {
            use std::os::unix::ffi::OsStringExt;
            OsString::from_vec(vec![0xff])
        }];
        assert!(parse(&bad).is_err(), "not UTF-8");
    }

    fn os(args: &[&str]) -> Vec<OsString> {
        args.iter().map(OsString::from).collect()
    }

    const NAMES: [(&str, Runner); 5] = [
        ("cloudroom", Runner::Cloudroom),
        ("t3", Runner::T3),
        ("cron", Runner::Cron),
        ("systemd", Runner::Systemd),
        ("github-actions", Runner::GithubActions),
    ];

    #[test]
    fn the_runner_names_map_to_distinct_values() {
        for (i, (name, runner)) in NAMES.iter().enumerate() {
            assert_eq!(Runner::from_name(name), Some(*runner), "{name}");
            assert_eq!(runner.name(), *name);
            for (_, other) in &NAMES[i + 1..] {
                assert_ne!(runner, other);
            }
        }
        for name in [
            "",
            "T3",
            "Cloudroom",
            "github_actions",
            "githubactions",
            "t3 ",
            "crontab",
        ] {
            assert_eq!(Runner::from_name(name), None, "{name:?}");
        }
    }

    #[test]
    fn no_command_enables_a_runner_yet() {
        for word in ["validate", "export", "plan", "apply"] {
            let command = Command::from_word(word).unwrap();
            assert!(command.runners().is_empty(), "{word}");
            for (name, _) in NAMES {
                let (code, out, err) =
                    run_args(&[word, "a", "--project", "prj_syn_0001", "--runner", name]);
                assert_eq!((code, out.as_str()), (2, ""), "{word} {name}");
                assert!(err.starts_with("openwiz: usage: "), "{err}");
                assert!(err.contains("nothing was read"), "{err}");
            }
        }
    }

    fn everywhere(command: Command) -> &'static [Runner] {
        match command {
            Command::Validate | Command::Export => &[Runner::T3, Runner::Cron],
            Command::Plan => &[Runner::T3, Runner::Cloudroom, Runner::GithubActions],
            Command::Apply => &[Runner::Systemd],
        }
    }

    #[test]
    fn a_selected_runner_needs_the_command_to_enable_it() {
        let selected = |args: &[&str]| match parse_with(&os(args), everywhere) {
            Ok(Parsed::Runner(runner, args)) => Ok((runner, args)),
            Ok(other) => panic!("{other:?}"),
            Err(why) => Err(why),
        };
        let (runner, args) = selected(&["plan", "a.md", "--runner", "t3", "--json"]).unwrap();
        assert_eq!(runner, Runner::T3);
        assert_eq!(
            (args.operands, args.project, args.json),
            (vec!["a.md".into()], None, true)
        );
        let (runner, _) = selected(&["plan", "a.md", "--runner", "github-actions"]).unwrap();
        assert_eq!(runner, Runner::GithubActions);
        let (runner, _) = selected(&["apply", "a", "--runner", "systemd"]).unwrap();
        assert_eq!(runner, Runner::Systemd);
        let (runner, args) =
            selected(&["export", "--project", "prj_syn_0001", "--runner", "cron"]).unwrap();
        assert_eq!(
            (runner, args.project.as_deref()),
            (Runner::Cron, Some("prj_syn_0001"))
        );
        assert!(
            selected(&["plan", "a.md", "--runner", "cloudroom"])
                .unwrap_err()
                .contains("--project")
        );
        for args in [
            &["plan", "a.md", "--runner", "cron"][..],
            &["export", "--runner", "systemd"],
            &["apply", "a", "--runner", "t3"],
            &[
                "apply",
                "a",
                "--project",
                "prj_syn_0001",
                "--runner",
                "cloudroom",
            ],
            &["validate", "a.md", "--runner", "t3"],
            &["validate", "a.md", "--runner", "cron"],
            &["plan", "a.md", "--runner"],
            &["plan", "a.md", "--runner", ""],
            &["plan", "a.md", "--runner", "--json"],
            &["plan", "a.md", "--runner", "T3"],
            &["plan", "a.md", "--runner", "kubernetes"],
            &["plan", "a.md", "--runner=t3"],
            &["plan", "a.md", "--runner", "t3", "--runner", "t3"],
            &[
                "plan",
                "a.md",
                "--runner",
                "t3",
                "--runner",
                "github-actions",
            ],
        ] {
            assert!(selected(args).is_err(), "{args:?}");
        }
    }

    #[test]
    fn without_a_selector_the_cloudroom_rules_are_unchanged() {
        for args in [
            &["export", "--project", "prj_syn_0001"][..],
            &["plan", "a.md", "--project", "prj_syn_0001"],
            &["apply", "a", "--project", "prj_syn_0001"],
            &["validate", "a.md"],
            &[
                "plan",
                "a.md",
                "--project",
                "prj_syn_0001",
                "--",
                "--runner",
                "t3",
            ],
        ] {
            let fallback = parse(&os(args));
            assert!(matches!(fallback, Ok(Parsed::Run(_))), "{args:?}");
            assert_eq!(parse_with(&os(args), everywhere), fallback, "{args:?}");
        }
        for args in [&["export"][..], &["plan", "a.md"], &["apply", "a"]] {
            for available in [Command::runners, everywhere] {
                let why = parse_with(&os(args), available).unwrap_err();
                assert!(
                    why.ends_with("needs --project <project>"),
                    "{args:?}: {why}"
                );
            }
        }
    }

    #[test]
    fn escape_untrusted_replaces_terminal_controls() {
        assert_eq!(
            escape_untrusted("a\u{1b}[2Jb\u{1b}]52;c;eA==\u{7}c\rd\ne\u{202e}f"),
            "a?[2Jb?]52;c;eA==?c?d?e\u{fffd}f"
        );
        assert_eq!(
            escape_untrusted("Synthetic: plain text"),
            "Synthetic: plain text"
        );
    }

    #[test]
    fn a_usage_error_never_prints_a_terminal_control() {
        let bad = "--x\u{1b}]52;c;eA==\u{7}";
        let (code, out, err) = run_args(&["export", "--project", "prj_syn_0001", bad]);
        assert_eq!((code, out.as_str()), (2, ""));
        assert_eq!(
            err,
            "openwiz: usage: loop export has no option --x?]52;c;eA==?; nothing was read (see openwiz loop export --help)\n"
        );
        let (code, out, err) = run_args(&["export", "--json", "--project", "prj_syn_0001", bad]);
        assert_eq!(code, 2);
        assert!(!err.contains('\u{1b}'), "{err:?}");
        let doc: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(
            doc["error"]["message"],
            format!("Invalid loop arguments: loop export has no option {bad}.")
        );
    }

    #[test]
    fn a_usage_error_names_its_help_and_exits_1_when_output_fails() {
        struct Broken;
        impl Write for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("synthetic write failure"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        for word in ["validate", "export", "plan", "apply"] {
            let (code, _, err) = run_args(&[word, "--x"]);
            assert_eq!(code, 2, "{word}");
            assert!(
                err.ends_with(&format!("(see openwiz loop {word} --help)\n")),
                "{err}"
            );
            let (help, _, _) = run_args(&[word, "--help"]);
            assert_eq!(help, 0, "{word}");
            let args = [OsString::from(word), OsString::from("--x")];
            assert_eq!(run(&args, &mut Vec::new(), &mut Broken), 1, "{word}");
            let json = [word, "--x", "--json"].map(OsString::from);
            assert_eq!(run(&json, &mut Broken, &mut Vec::new()), 1, "{word}");
            assert_eq!(run(&json, &mut Vec::new(), &mut Broken), 2, "{word}");
        }
    }

    #[test]
    fn help_lists_the_four_commands_and_reads_nothing() {
        let (code, out, err) = run_args(&["plan", "--help"]);
        assert_eq!((code, err.as_str()), (0, ""));
        for line in USAGE.lines() {
            assert!(out.contains(line), "{line}");
        }
        let (code, out, _) = run_args(&["export", "-h", "--json"]);
        assert_eq!(code, 0);
        let doc: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(doc["schema"], "openwiz.cli-help.v1");
    }
}
