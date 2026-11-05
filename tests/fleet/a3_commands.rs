//! A3 (ClosedWiz#111): the wiring of `openwiz fleets` and `openwiz fleet
//! <spec>`, which stays when A4 and A5 build them. The program sends each
//! command to its own file's `run`, and `openwiz --help` carries each
//! file's own usage line, section and exit codes in their places.
//!
//! What the stubs do (say not yet, read nothing) is each command's own,
//! proven in `a4_fleets.rs` and `a5_fleet.rs`, which A4 and A5 replace (Sol
//! on #247, R1).

use std::fs;
use std::path::Path;

use openwiz_cli::{fleet, fleets};

use crate::support::Run;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// The text of `main.rs` from `start` up to the next branch.
fn arm<'a>(main: &'a str, start: &str) -> &'a str {
    assert_eq!(main.matches(start).count(), 1, "main.rs has `{start}` once");
    main.split(start)
        .nth(1)
        .and_then(|rest| rest.split("Some(").next())
        .expect("an arm")
}

#[test]
fn the_program_sends_each_command_to_its_own_files_run() {
    // The signature main.rs calls: the arguments after the name, stdout and
    // stderr. A change to it is a compile error here.
    let _: [Run; 2] = [fleets::run, fleet::run];
    let main = fs::read_to_string(Path::new(ROOT).join("crates/cli/src/main.rs")).expect("main.rs");
    assert_eq!(
        main.matches("match args.first().and_then(|a| a.to_str()) {")
            .count(),
        1,
        "the dispatcher matches the actual command argument"
    );
    for name in ["fleets", "fleet"] {
        let start = format!("Some(\"{name}\") =>");
        let call: String = arm(&main, &start).split_whitespace().collect();
        assert_eq!(
            call,
            format!("openwiz_cli::{name}::run(&args[1..],stdout,stderr),"),
            "`openwiz {name}` goes to its own file's run, with nothing else"
        );
    }
}

#[test]
fn the_help_carries_each_commands_own_lines_in_their_places() {
    let help = openwiz_cli::help();
    let find = |part: &str| {
        help.find(part)
            .unwrap_or_else(|| panic!("{part:?} is not in --help:\n{help}"))
    };
    let usage = find("\nUsage:\n");
    let usage_end = usage
        + help[usage..]
            .find("  openwiz --help\n")
            .expect("--help's line");
    let exit_codes = help.rfind("\nExit codes:\n").expect("the exit codes");
    // Up to and with the newline that ends the last exit code's line.
    let on_error = exit_codes
        + help[exit_codes..]
            .find("\nOn an error, stdout is empty")
            .expect("the error note")
        + 1;
    for (name, usage_line, section, exits) in [
        ("fleets", fleets::USAGE, fleets::HELP, fleets::EXIT_CODES),
        ("fleet", fleet::USAGE, fleet::HELP, fleet::EXIT_CODES),
    ] {
        assert!(
            help[usage..usage_end].contains(usage_line),
            "{name}'s USAGE is in the usage list, before --help's line:\n{help}"
        );
        assert!(
            help[usage_end..exit_codes].contains(section),
            "{name}'s HELP is a section before the exit codes:\n{help}"
        );
        assert!(
            help[exit_codes..on_error].contains(exits),
            "{name}'s EXIT_CODES are in the exit codes:\n{help}"
        );
    }
}
