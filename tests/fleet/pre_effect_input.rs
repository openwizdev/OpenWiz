//! EX1 input contract: a plan path is data, and restrictions cannot be dropped
//! by parser combinations. The old response selector has no fleet value flag.
use super::*;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;

#[test]
fn plan_value_does_not_select_json_or_preview() {
    let w = World::new("restricted-value-syntax");
    for (args, json, command, code) in [
        (
            vec!["tick", "--expect-plan", "--json"],
            false,
            "fleet.tick",
            1,
        ),
        (
            vec!["tick", "--expect-plan", "--dry-run", "--json"],
            true,
            "fleet.tick",
            1,
        ),
        (vec!["tick", "--expect-plan=--json"], false, "fleet.tick", 2),
        (
            vec!["tick", "--expect-plan=--json", "--json"],
            true,
            "fleet.tick",
            2,
        ),
    ] {
        let request = openwiz_cli::response::Request::for_command("fleet", &args);
        assert_eq!((request.json, request.command), (json, command), "{args:?}");
        let mut cli = vec!["fleet"];
        cli.extend(args);
        let out = w.command(&cli).current_dir(&w.dir).output().unwrap();
        assert_eq!(out.status.code(), Some(code));
        if json {
            let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
            assert_eq!(doc["schema"], "openwiz.cli-error.v1");
            assert_eq!(doc["command"], "fleet.tick");
        } else {
            assert!(out.stdout.is_empty(), "path data must not select JSON");
        }
    }
    assert!(
        w.calls().is_empty(),
        "bad/missing files need no external read"
    );
    assert!(!w.dir.join("state").exists());
}

#[test]
fn restriction_syntax_keeps_the_path_and_refuses_invalid_combinations() {
    use openwiz_cli::fleet::tick::parse;
    for (args, path) in [
        (
            vec!["tick", "--expect-plan", "synthetic plan.json", "--json"],
            "synthetic plan.json",
        ),
        (vec!["tick", "--json", "--expect-plan", "--json"], "--json"),
    ] {
        let args: Vec<_> = args.into_iter().map(OsString::from).collect();
        let p = parse(&args).unwrap();
        assert!(!p.due && !p.dry_run && p.json);
        assert_eq!(p.expect_plan.as_deref(), Some(Path::new(path)));
    }
    for args in [
        vec!["tick", "--expect-plan"],
        vec!["tick", "--expect-plan", ""],
        vec!["tick", "--expect-plan=a"],
        vec!["tick", "--expect-plan", "a", "--expect-plan", "b"],
        vec!["tick", "--expect-plan", "a", "--dry-run"],
        vec!["tick", "--dry-run", "--expect-plan", "a"],
        vec!["due", "--github-only", "--expect-plan", "a"],
    ] {
        let args: Vec<_> = args.into_iter().map(OsString::from).collect();
        assert!(parse(&args).is_err(), "{args:?}");
    }
    assert!(
        parse(&[
            "tick".into(),
            "--expect-plan".into(),
            OsString::from_vec(vec![0xff])
        ])
        .is_err()
    );
}
