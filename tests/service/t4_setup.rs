//! Execute the documented setup blocks only against synthetic files and tools.
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Output},
    sync::atomic::{AtomicU64, Ordering},
};

const README: &str = include_str!("../../deploy/pc/README.md");
fn block(index: usize) -> &'static str {
    README
        .split("```sh\n")
        .nth(index + 1)
        .unwrap()
        .split("```")
        .next()
        .unwrap()
}
fn dir(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn file(path: &Path, body: impl AsRef<[u8]>, mode: u32) {
    dir(path.parent().unwrap());
    // Every file goes through `place`, so no fake program is written here.
    place_script(path, std::str::from_utf8(body.as_ref()).unwrap());
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
}
struct Setup(PathBuf);
impl Setup {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-t4-setup-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        dir(&root.join("home"));
        dir(&root.join("work"));
        dir(&root.join("tools"));
        let setup = Self(root);
        file(
            &setup.0.join("tools/git"),
            "#!/bin/sh\nprintf '0123456789abcdef0123456789abcdef01234567\\n'\n",
            0o700,
        );
        file(
            &setup.0.join("work/target/release/openwiz-service"),
            "synthetic program",
            0o700,
        );
        file(
            &setup.0.join("work/apps/web/out/index.html"),
            "synthetic page",
            0o600,
        );
        file(
            &setup.0.join("work/deploy/pc/config.example.json"),
            include_bytes!("../../deploy/pc/config.example.json"),
            0o600,
        );
        file(
            &setup.0.join("work/deploy/pc/openwiz.service"),
            include_bytes!("../../deploy/pc/openwiz.service"),
            0o600,
        );
        for tool in ["loginctl", "systemctl"] {
            file(
                &setup.0.join("tools").join(tool),
                "#!/bin/sh\n{ printf '%s' \"${0##*/}\"; printf ' <%s>' \"$@\"; printf '\\n'; } >> \"$T4_CALLS\"\n",
                0o700,
            );
        }
        file(&setup.0.join("tools/sleep"), "#!/bin/sh\nexit 0\n", 0o700);
        setup
    }
    fn home(&self, path: &str) -> PathBuf {
        self.0.join("home").join(path)
    }
    fn run(&self, script: &str, fail: bool) -> Output {
        Command::new("/bin/bash")
            .args(["-c", script])
            .current_dir(self.0.join("work"))
            .env("HOME", self.0.join("home"))
            .env("USER", "synthetic-owner")
            .env(
                "PATH",
                format!("{}:/usr/bin:/bin", self.0.join("tools").display()),
            )
            .env("T4_CALLS", self.0.join("setup-calls"))
            .env("T4_COUNT", self.0.join("status-count"))
            .env("T4_ALWAYS_FAIL", if fail { "1" } else { "0" })
            .output()
            .unwrap()
    }
}
impl Drop for Setup {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn prove_staging(script: &str) {
    for existing in [
        ".local/state/openwiz/service/config.json",
        ".config/systemd/user/openwiz.service",
        ".local/lib/openwiz/source",
    ] {
        let f = Setup::new();
        let path = f.home(existing);
        file(&path, b"existing synthetic owner file", 0o600);
        let out = f.run(script, false);
        assert!(
            !out.status.success(),
            "staging must refuse existing {existing}"
        );
        assert_eq!(fs::read(path).unwrap(), b"existing synthetic owner file");
        assert!(!f.home(".local/lib/openwiz/current").exists());
    }
    let f = Setup::new();
    let out = f.run(script, false);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(
        fs::read(f.home(".local/state/openwiz/service/config.json")).unwrap(),
        include_bytes!("../../deploy/pc/config.example.json")
    );
    let unit = f.home(".config/systemd/user/openwiz.service");
    assert_eq!(
        fs::read(&unit).expect("fresh staging must install the user unit"),
        include_bytes!("../../deploy/pc/openwiz.service")
    );
    assert_eq!(
        fs::metadata(&unit).unwrap().permissions().mode() & 0o777,
        0o600,
        "staged user unit must be owner-only"
    );
    assert!(
        f.home(".local/lib/openwiz/current/web/index.html")
            .is_file()
    );
    assert_eq!(
        fs::read_link(f.home(".local/lib/openwiz/source")).unwrap(),
        f.0.join("work").canonicalize().unwrap()
    );
    assert_eq!(
        fs::metadata(f.home(".local/lib/openwiz/current/openwiz-service"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
}

fn prove_bootstrap(script: &str) {
    for fail in [false, true] {
        let f = Setup::new();
        file(
            &f.home(".local/lib/openwiz/current/openwiz-service"),
            "#!/bin/sh\nn=$(cat \"$T4_COUNT\" 2>/dev/null || printf 0)\nn=$((n + 1))\nprintf '%s\\n' \"$n\" > \"$T4_COUNT\"\n[ \"$T4_ALWAYS_FAIL\" = 0 ] && [ \"$n\" -ge 3 ]\n",
            0o700,
        );
        let out = f.run(script, fail);
        assert_eq!(
            out.status.success(),
            !fail,
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert_eq!(
            fs::read_to_string(f.0.join("setup-calls")).unwrap(),
            concat!(
                "loginctl <enable-linger> <synthetic-owner>\n",
                "systemctl <--user> <daemon-reload>\n",
                "systemctl <--user> <enable> <--now> <openwiz.service>\n",
            ),
            "bootstrap must enable lingering, reload, then enable the user service"
        );
        assert_eq!(
            fs::read_to_string(f.0.join("status-count")).unwrap().trim(),
            if fail { "30" } else { "3" }
        );
    }
}

#[test]
fn documented_staging_preserves_existing_config_and_unit() {
    prove_staging(block(1));
}

#[test]
fn documented_bootstrap_waits_for_status_and_fails_if_it_never_answers() {
    prove_bootstrap(block(2));
}

#[test]
fn staging_proof_rejects_missing_changed_or_public_unit() {
    let install =
        "install -m 600 deploy/pc/openwiz.service \"$HOME/.config/systemd/user/openwiz.service\"";
    for replacement in [
        "".to_string(),
        install.replace("deploy/pc/openwiz.service", "deploy/pc/config.example.json"),
        install.replace("-m 600", "-m 644"),
    ] {
        assert!(
            block(1).contains(install),
            "mutation must change the fixture"
        );
        let script = block(1).replace(install, &replacement);
        assert!(
            std::panic::catch_unwind(|| prove_staging(&script)).is_err(),
            "staging proof accepted unit install mutation: {replacement:?}"
        );
    }
}

#[test]
fn bootstrap_proof_rejects_missing_or_reordered_setup_calls() {
    let calls = [
        "loginctl enable-linger \"$USER\"\n",
        "systemctl --user daemon-reload\n",
        "systemctl --user enable --now openwiz.service\n",
    ];
    let mut rejected = Vec::new();
    for call in calls {
        assert!(block(2).contains(call), "mutation must change the fixture");
        let script = block(2).replace(call, "");
        rejected.push(std::panic::catch_unwind(|| prove_bootstrap(&script)).is_err());
    }
    let original = format!("{}{}", calls[0], calls[1]);
    assert!(block(2).contains(&original));
    let script = block(2).replace(&original, &format!("{}{}", calls[1], calls[0]));
    rejected.push(std::panic::catch_unwind(|| prove_bootstrap(&script)).is_err());
    assert_eq!(
        rejected,
        vec![true; 4],
        "missing calls, then reordered calls"
    );
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2583, as
/// #2559 and #1754).
fn place(src: &std::path::Path, dst: &std::path::Path) {
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &std::path::Path, dst: &std::path::Path) -> std::process::Child {
    use std::process::Stdio;
    // `cp` would copy into a directory and succeed (#2721, #2731).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cp runs")
}
/// Waits for `place`'s `cp` to succeed, then makes `dst` executable, owner-only.
fn placed(cp: std::process::Child, dst: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &std::path::Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &std::path::Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (
        std::path::Path::new("/proc/self/fd"),
        std::path::Path::new("/proc/self/fdinfo"),
    );
    let target = std::fs::metadata(path).unwrap();
    std::fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = std::fs::metadata(fds.join(&fd)).ok()?;
            let info = std::fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2583 (as #2559): this binary's fakes are placed while other test threads
/// fork. The copy is held mid-way on a FIFO, where this process must hold no
/// writer for the placed file; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_a_fake_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = PlaceDir::new("ow-place-t4setup");
    let program = dir.0.join("placed");
    let held = writers_mid_copy(&dir.0, &program);
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = std::process::Command::new(&program).output().unwrap();
    assert!(run.status.success());
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2731 (as #2721): a directory at the exact destination is refused,
/// instead of `cp` placing the program inside that directory and reporting
/// success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-place-dir-t4setup-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
/// #2699 (as #2594): the proof above fails, never hangs, when its copier fails
/// before opening the FIFO. Here `cp` cannot stat a destination under a
/// regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let dir = PlaceDir::new("ow-place-t4setup-early");
    let file = dir.0.join("file");
    std::fs::write(&file, "").unwrap();
    writers_mid_copy(&dir.0, &file.join("placed"));
}
/// #2707, #2734: a copier still waiting on the FIFO when a proof fails is
/// killed and reaped as its `Copy` unwinds, never left behind. With no writer
/// started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let dir = PlaceDir::new("ow-place-t4setup-late");
    let fifo = dir.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = dir.0.join("placed");
    let cp = copier(&fifo, &program);
    let pid = cp.id();
    let unwound = std::panic::catch_unwind(move || {
        let _copy = Copy {
            source: None,
            cp: Some(cp),
            program,
            until: std::time::Instant::now(),
        };
        panic!("the proof failed while its copier waited");
    });
    assert!(unwound.is_err());
    let left = std::fs::metadata(format!("/proc/{pid}")).map(|_| ());
    assert_eq!(
        left.map_err(|e| e.kind()),
        Err(std::io::ErrorKind::NotFound),
        "the copier was left running or unreaped after the proof unwound"
    );
}
/// An owner-only scratch directory for one FIFO proof, removed when dropped,
/// even by a failing proof.
#[cfg(target_os = "linux")]
struct PlaceDir(std::path::PathBuf);
#[cfg(target_os = "linux")]
impl PlaceDir {
    fn new(prefix: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
#[cfg(target_os = "linux")]
impl Drop for PlaceDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
/// Places a script at `program` as `place` does, from a FIFO in `dir` this
/// process writes, and returns how many writers this process held for
/// `program` while the copy was held mid-way.
#[cfg(target_os = "linux")]
fn writers_mid_copy(dir: &std::path::Path, program: &std::path::Path) -> usize {
    use std::time::{Duration, Instant};
    let fifo = dir.join("source.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while std::fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
        copy.check("the copy started");
    }
    let held = writers(program);
    copy.write(b"printf 'PLACED\\n'\n");
    copy.finish();
    held
}
/// `place`'s `cp` copying a FIFO to `program`, and this process's writer for
/// that FIFO. Dropped, even by a failing proof, it closes the writer, so the
/// copier reads its end, then kills a copier still running after a short
/// grace and reaps it (#2707).
#[cfg(target_os = "linux")]
struct Copy {
    source: Option<std::fs::File>,
    cp: Option<std::process::Child>,
    program: std::path::PathBuf,
    until: std::time::Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &std::path::Path, program: &std::path::Path, until: std::time::Instant) -> Self {
        let mut copy = Self {
            source: None,
            cp: Some(copier(fifo, program)),
            program: program.to_owned(),
            until,
        };
        // Opening blocks until a reader has the FIFO open, so it runs on its
        // own thread while this one watches the copier and the deadline.
        let opening = {
            let fifo = fifo.to_owned();
            std::thread::spawn(move || std::fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || std::time::Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = std::fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        copy.source = Some(opening.join().unwrap().unwrap());
        copy
    }
    fn ended(&mut self) -> bool {
        self.cp
            .as_mut()
            .is_none_or(|cp| cp.try_wait().unwrap().is_some())
    }
    /// Fails if the copier has ended or `until` has passed; else waits a moment.
    fn check(&mut self, waiting_for: &str) {
        assert!(!self.ended(), "the copier ended before {waiting_for}");
        assert!(
            std::time::Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(
                std::time::Instant::now() < self.until,
                "the copier never finished"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        placed(self.cp.take().unwrap(), &self.program);
    }
}
#[cfg(target_os = "linux")]
impl Drop for Copy {
    fn drop(&mut self) {
        drop(self.source.take());
        // The copier ends soon after its end of file: a short grace past a
        // missed deadline, never an unbounded wait.
        let now = std::time::Instant::now();
        let until = self.until.max(now + std::time::Duration::from_secs(1));
        while !self.ended() && std::time::Instant::now() < until {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}
