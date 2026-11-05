//! C3/C4: recording fixtures only; never a live room-cli or gh.
//! synthetic_assumptions: loop list rows use id/name/paused, pending T11's
//! endpoint check. Thread moves, archived-thread reads and failed/lost writes
//! are synthetic scenarios; no fixture result establishes live behavior.
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::health::model::{Id, Repository};
use openwiz_core::limits::RUN_BUDGET;
use std::{
    fs::{self, DirBuilder},
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};
/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2559, as
/// #1754).
fn place(src: &Path, dst: &Path) {
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &Path, dst: &Path) -> std::process::Child {
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
fn placed(cp: std::process::Child, dst: &Path) {
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    fs::set_permissions(dst, fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &Path, text: &str) {
    let src = dst.with_extension("src");
    fs::write(&src, text).unwrap();
    place(&src, dst);
    fs::remove_file(&src).unwrap();
}
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-t5-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&root).unwrap();
        let f = Self(root);
        fs::write(f.0.join("loops.json"), r#"[{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":true},{"id":"loop_other","name":"launch-fleet other-owner/other-repo","paused":true}]"#).unwrap();
        place_script(
            &f.0.join("room"),
            r#"#!/usr/bin/python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
with (root/'calls').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\n')
args=sys.argv[1:]
if args==['loop','list','--json']: print((root/'loops.json').read_text())
elif args==['loop','resume','loop_syn_1','--json']:
    rows=json.loads((root/'loops.json').read_text()); rows[0]['paused']=False
    (root/'loops.json').write_text(json.dumps(rows)); print('{}')
elif len(args)==4 and args[:2]==['loop','pause'] and args[3]=='--json':
    if not (root/'deny-pause').exists():
        rows=json.loads((root/'loops.json').read_text())
        for row in rows:
            if row['id']==args[2]: row['paused']=True
        if (root/'foreign-pause').exists(): rows[0]['name']='launch-fleet other-owner/other-repo'
        if (root/'missing-pause').exists(): rows=rows[1:]
        (root/'loops.json').write_text(json.dumps(rows))
        if (root/'malformed-pause').exists(): (root/'loops.json').write_text('{}')
    if (root/'lost-pause').exists(): sys.exit(2)
    print('{}')
else: sys.exit(2)
"#,
        );
        f
    }
    fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.0.join("room"))
    }
    fn calls(&self) -> Vec<serde_json::Value> {
        fs::read_to_string(self.0.join("calls"))
            .unwrap_or_default()
            .lines()
            .map(|s| serde_json::from_str(s).unwrap())
            .collect()
    }
}
// TA2 fixture diagnostics BEGIN
/// Only synthetic fixture state: bounded previews, never a recursive dump.
fn emit_fixture_failure(root: &std::path::Path, label: &str, allowed: &[&str]) {
    use std::io::{Read, Write};
    use std::os::unix::fs::MetadataExt;
    const FILE_BYTES: usize = 4096;
    const REPORT_BYTES: usize = 32 * 1024;

    fn metadata(root: &std::path::Path, relative: &std::path::Path) -> Option<fs::Metadata> {
        let mut path = root.to_path_buf();
        if !fs::symlink_metadata(&path).ok()?.is_dir() {
            return None;
        }
        for part in relative.components() {
            let std::path::Component::Normal(part) = part else {
                return None;
            };
            path.push(part);
            if fs::symlink_metadata(&path).ok()?.file_type().is_symlink() {
                return None;
            }
        }
        fs::symlink_metadata(path).ok()
    }
    fn append(out: &mut String, text: &str, clipped: &mut bool) {
        let mut end = text
            .len()
            .min((REPORT_BYTES - 256).saturating_sub(out.len()));
        while !text.is_char_boundary(end) {
            end -= 1;
        }
        out.push_str(&text[..end]);
        *clipped |= end != text.len();
    }
    let mut out = format!("[TA2 service-ci-diagnostics {label}] synthetic fixture failure\n");
    let mut clipped = false;
    let mut files = Vec::new();
    for name in allowed {
        let relative = std::path::PathBuf::from(name);
        match metadata(root, &relative) {
            Some(meta) if meta.is_dir() => {
                if let Ok(entries) = fs::read_dir(root.join(&relative)) {
                    let mut entries: Vec<_> = entries.take(9).filter_map(Result::ok).collect();
                    entries.sort_by_key(|entry| entry.file_name());
                    if entries.len() > 8 {
                        append(
                            &mut out,
                            &format!("{name}: directory truncated=true\n"),
                            &mut clipped,
                        );
                    }
                    files.extend(
                        entries
                            .into_iter()
                            .take(8)
                            .map(|e| relative.join(e.file_name())),
                    );
                }
            }
            Some(_) => files.push(relative),
            None => append(
                &mut out,
                &format!("{name}: missing or refused\n"),
                &mut clipped,
            ),
        }
    }
    if files.len() > 16 {
        append(&mut out, "file_list_truncated=true\n", &mut clipped);
    }
    for relative in files.into_iter().take(16) {
        let name = relative.to_string_lossy();
        let Some(meta) = metadata(root, &relative).filter(|m| m.is_file() && m.nlink() == 1) else {
            append(
                &mut out,
                &format!("{name}: refused non-regular or linked file\n"),
                &mut clipped,
            );
            continue;
        };
        let Ok(file) = fs::File::open(root.join(&relative)) else {
            append(&mut out, &format!("{name}: unread\n"), &mut clipped);
            continue;
        };
        if !file
            .metadata()
            .is_ok_and(|m| m.dev() == meta.dev() && m.ino() == meta.ino() && m.nlink() == 1)
        {
            append(
                &mut out,
                &format!("{name}: changed during capture\n"),
                &mut clipped,
            );
            continue;
        }
        let mut bytes = Vec::new();
        if file
            .take((FILE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .is_err()
        {
            append(&mut out, &format!("{name}: unread\n"), &mut clipped);
            continue;
        }
        let truncated = bytes.len() > FILE_BYTES;
        bytes.truncate(FILE_BYTES);
        let preview = format!(
            "{name}: truncated={truncated} {:?}\n",
            String::from_utf8_lossy(&bytes)
        );
        append(&mut out, &preview, &mut clipped);
    }
    out.push_str(&format!(
        "[TA2 service-ci-diagnostics end] output_truncated={clipped}\n"
    ));
    let _ = std::io::stderr().lock().write_all(out.as_bytes());
}
// TA2 fixture diagnostics END

impl Drop for Fixture {
    fn drop(&mut self) {
        // TA2 failure snapshot BEGIN
        if std::thread::panicking() {
            emit_fixture_failure(
                &self.0,
                "health",
                &[
                    "service/state.json",
                    "gh-calls",
                    "calls",
                    "loops.json",
                    "comments.json",
                    "service/config.json",
                    "service/health",
                ],
            );
        }
        // TA2 failure snapshot END
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn deadline() -> Instant {
    Instant::now() + RUN_BUDGET
}
fn repo() -> Repository {
    Repository::parse("synthetic-owner", "synthetic-repo").unwrap()
}
#[test]
fn reads_and_resumes_only_the_owned_loop_with_verified_readback() {
    let f = Fixture::new();
    let rows = f.source().health_loops(deadline()).unwrap();
    assert_eq!(
        rows.len(),
        2,
        "the full list is needed for ownership decisions"
    );
    f.source()
        .resume_loop(&Id::parse("loop_syn_1").unwrap(), &repo(), deadline())
        .unwrap();
    assert_eq!(
        f.calls(),
        serde_json::json!([
            ["loop", "list", "--json"],
            ["loop", "list", "--json"],
            ["loop", "resume", "loop_syn_1", "--json"],
            ["loop", "list", "--json"]
        ])
        .as_array()
        .unwrap()
        .clone()
    );
    let rows: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(f.0.join("loops.json")).unwrap()).unwrap();
    assert_eq!(rows[0]["paused"], false);
    assert_eq!(rows[1]["paused"], true);
}
#[test]
fn foreign_and_unknown_loops_are_never_resumed() {
    let f = Fixture::new();
    for id in ["loop_other", "loop_missing"] {
        assert!(
            f.source()
                .resume_loop(&Id::parse(id).unwrap(), &repo(), deadline())
                .is_err()
        );
    }
    assert_eq!(
        f.calls(),
        serde_json::json!([["loop", "list", "--json"], ["loop", "list", "--json"]])
            .as_array()
            .unwrap()
            .clone()
    );
}
#[test]
fn malformed_or_duplicate_loop_rows_refuse_the_entire_list() {
    for text in [
        r#"[{"id":"loop_syn_1","id":"loop_other","name":"launch-fleet synthetic-owner/synthetic-repo","paused":true}]"#,
        r#"[{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":"true"}]"#,
        r#"[{"id":"loop_syn_1","name":"a","paused":true},{"id":"loop_syn_1","name":"b","paused":false}]"#,
    ] {
        let f = Fixture::new();
        fs::write(f.0.join("loops.json"), text).unwrap();
        assert!(
            f.source()
                .resume_loop(&Id::parse("loop_syn_1").unwrap(), &repo(), deadline())
                .is_err()
        );
        assert_eq!(
            f.calls(),
            serde_json::json!([["loop", "list", "--json"]])
                .as_array()
                .unwrap()
                .clone()
        );
    }
}

/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let target = fs::metadata(path).unwrap();
    fs::read_dir("/proc/self/fd")
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = fs::metadata(Path::new("/proc/self/fd").join(&fd)).ok()?;
            let info = fs::read_to_string(Path::new("/proc/self/fdinfo").join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2559 (as #1754): a child another test forks while the fake room-cli is
/// being placed inherits every descriptor this process holds at that moment,
/// until it execs. A writable one keeps the placed file busy, so launching it
/// fails with ETXTBSY (errno 26) and the expected call never happens. The
/// copy is held mid-way on a FIFO, where this process must hold no writer for
/// it; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_the_fake_room_cli_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let f = Fixture::new();
    let program = f.0.join("placed");
    let held = writers_mid_copy(&f, &program);
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
    let f = Fixture::new();
    let destination = f.0.join("placed");
    DirBuilder::new().mode(0o700).create(&destination).unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(fs::read_dir(&destination).unwrap().count(), 0);
}
/// #2594: the proof above fails, never hangs, when its copier fails before
/// opening the FIFO. Here `cp` cannot stat a destination under a regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let f = Fixture::new();
    writers_mid_copy(&f, &f.0.join("loops.json").join("placed"));
}
/// #2707, #2734: a copier still waiting on the FIFO when a proof fails is
/// killed and reaped as its `Copy` unwinds, never left behind. With no writer
/// started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let f = Fixture::new();
    let fifo = f.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = f.0.join("placed");
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
/// Places a script at `program` as `place` does, from a FIFO this process
/// writes, and returns how many writers this process held for `program`
/// while the copy was held mid-way. One deadline bounds every wait.
#[cfg(target_os = "linux")]
fn writers_mid_copy(f: &Fixture, program: &Path) -> usize {
    let fifo = f.0.join("source.fifo");
    assert!(
        std::process::Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .unwrap()
            .success()
    );
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
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
    source: Option<fs::File>,
    cp: Option<std::process::Child>,
    program: PathBuf,
    until: Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &Path, program: &Path, until: Instant) -> Self {
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
            std::thread::spawn(move || fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(Duration::from_millis(10));
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
            Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(Instant::now() < self.until, "the copier never finished");
            std::thread::sleep(Duration::from_millis(10));
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
        let until = self.until.max(Instant::now() + Duration::from_secs(1));
        while !self.ended() && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}

#[path = "t5_server.rs"]
mod server;

#[path = "t5_tick.rs"]
mod tick;

#[path = "t5_restart.rs"]
mod restart;

#[path = "t5_execution.rs"]
mod execution;

#[path = "t5_runtime.rs"]
mod runtime;

#[path = "t5_takeover.rs"]
mod takeover;
