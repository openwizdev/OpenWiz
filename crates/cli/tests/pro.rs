use std::fs::{self, DirBuilder};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use openwiz_cli::pro;

#[test]
fn non_interactive_pro_and_print_flag_print_url_without_launching_browser() {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let dir = std::env::temp_dir().join(format!("openwiz-pro-test-{}-{nanos}", std::process::id()));
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .unwrap();
    let log = dir.join("opener-calls");
    for name in ["open", "xdg-open"] {
        let script = dir.join(name);
        fs::write(
            &script,
            "#!/bin/sh\necho called >> \"$PRO_CALLS\"\nexit 99\n",
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
    }

    for args in [&["pro"][..], &["pro", "--print"][..]] {
        let output = Command::new(env!("CARGO_BIN_EXE_openwiz"))
            .args(args)
            .env_clear()
            .env("PATH", &dir)
            .env("PRO_CALLS", &log)
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(0), "{args:?}");
        assert_eq!(
            String::from_utf8(output.stdout).unwrap(),
            format!("{}\n", pro::URL)
        );
        assert!(output.stderr.is_empty(), "{args:?}");
    }
    assert!(
        !log.exists(),
        "browser opener must not run non-interactively"
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn help_lists_pro_and_bad_pro_args_exit_with_usage() {
    for args in [&["--help"][..], &["pro", "--help"][..]] {
        let output = Command::new(env!("CARGO_BIN_EXE_openwiz"))
            .args(args)
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(0), "{args:?}");
        let stdout = String::from_utf8(output.stdout).unwrap();
        assert!(stdout.contains(pro::USAGE), "{stdout}");
        assert!(stdout.contains(pro::URL), "{stdout}");
        assert!(output.stderr.is_empty());
    }

    let output = Command::new(env!("CARGO_BIN_EXE_openwiz"))
        .args(["pro", "--unknown"])
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.starts_with(b"openwiz:"));
}
