use super::{Sandbox, fixture_cli};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::{fs, os::unix::process::ExitStatusExt};

const REMOVED: &str = "openwiz: the terminal app was removed in OpenWiz 0.0.16; \
                       nothing was opened (see openwiz --help)\n";

fn install(sandbox: &Sandbox) -> PathBuf {
    let dir = sandbox.0.join("install");
    super::dirs::private_dir(&dir).unwrap();
    fs::copy(fixture_cli(), dir.join("openwiz")).unwrap();
    let sibling = dir.join("openwiz-terminal");
    fs::write(&sibling, "#!/bin/sh\n: > \"${0%/*}/ran\"\n").unwrap();
    fs::set_permissions(&sibling, fs::Permissions::from_mode(0o700)).unwrap();
    dir
}

fn env(command: &mut Command, sandbox: &Sandbox) {
    command
        .env_clear()
        .env("PATH", sandbox.0.join("bin"))
        .env("HOME", sandbox.0.join("home"))
        .env("OPENWIZ_STATE_DIR", sandbox.0.join("state"))
        .env("OPENWIZ_FIXTURE_PROGRAM", sandbox.0.join("bin/room-cli"))
        .env("CP1_CALLS", sandbox.0.join("calls"))
        .current_dir(&sandbox.0);
}

fn in_terminal(sandbox: &Sandbox, program: &Path, args: &[&str]) -> Output {
    const DRIVE: &str = "import os, signal, subprocess, sys\n\
        signal.alarm(10)\n\
        main, sub = os.openpty()\n\
        child = subprocess.Popen(sys.argv[1:], stdin=sub, stdout=sub, stderr=sub, start_new_session=True)\n\
        os.close(sub)\n\
        seen = b''\n\
        while True:\n\
        \x20   try:\n\
        \x20       chunk = os.read(main, 4096)\n\
        \x20   except OSError:\n\
        \x20       break\n\
        \x20   if not chunk:\n\
        \x20       break\n\
        \x20   seen += chunk\n\
        sys.stdout.buffer.write(seen)\n\
        sys.exit(child.wait())\n";
    let mut command = Command::new("/usr/bin/python3");
    env(&mut command, sandbox);
    command
        .args(["-I", "-c", DRIVE])
        .arg(program)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .unwrap()
}

#[test]
fn neither_ui_nor_a_bare_openwiz_starts_the_terminal_app() {
    let sandbox = Sandbox::new();
    let dir = install(&sandbox);
    let program = dir.join("openwiz");

    let bare = in_terminal(&sandbox, &program, &[]);
    assert_eq!(bare.status.signal(), None, "killed: it waited");
    assert!(
        !dir.join("ran").exists(),
        "bare openwiz started openwiz-terminal"
    );
    let text = String::from_utf8_lossy(&bare.stdout).replace("\r\n", "\n");
    assert_eq!(bare.status.code(), Some(0), "{text}");
    let help = sandbox.run(&["--help"]);
    assert_eq!(help.status.code(), Some(0));
    assert_eq!(
        text,
        String::from_utf8_lossy(&help.stdout),
        "bare is the help"
    );
    assert!(!text.contains("openwiz ui"), "{text}");

    for args in [&["ui"][..], &["ui", "--port", "7371"]] {
        let out = in_terminal(&sandbox, &program, args);
        let text = String::from_utf8_lossy(&out.stdout).replace("\r\n", "\n");
        assert_eq!(out.status.code(), Some(2), "{args:?}: {text}");
        assert_eq!(text, REMOVED, "{args:?}");
    }

    let mut piped = Command::new(&program);
    env(&mut piped, &sandbox);
    let ui = piped.arg("ui").stdin(Stdio::null()).output().unwrap();
    assert_eq!(ui.status.code(), Some(2));
    assert!(ui.stdout.is_empty());
    assert_eq!(String::from_utf8_lossy(&ui.stderr), REMOVED);

    let bare = sandbox.run(&[]);
    assert_eq!(bare.status.code(), Some(2));
    assert!(bare.stdout.is_empty());
    assert_eq!(
        String::from_utf8_lossy(&bare.stderr),
        "openwiz: no command given (see openwiz --help)\n"
    );

    assert!(!dir.join("ran").exists(), "openwiz-terminal was started");
    assert!(!sandbox.0.join("calls").exists(), "no source call");
    assert!(!sandbox.0.join("state").exists(), "no state");
}

#[test]
fn ui_json_is_a_usage_error_document_and_the_catalogue_has_no_ui() {
    let sandbox = Sandbox::new();
    let out = sandbox.run(&["ui", "--json"]);
    assert_eq!(out.status.code(), Some(2));
    let doc: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(doc["schema"], "openwiz.cli-error.v1");
    assert_eq!(doc["error"]["kind"], "usage");
    let catalogue = super::discovered();
    assert!(
        catalogue["commands"]
            .as_array()
            .unwrap()
            .iter()
            .all(|c| c["name"] != "ui" && c["aliases"] != serde_json::json!([[]])),
        "the agent catalogue still lists the terminal app"
    );
    assert!(!sandbox.0.join("calls").exists(), "no source call");
}
