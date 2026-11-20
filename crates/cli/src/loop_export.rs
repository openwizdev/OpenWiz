//! `openwiz loop export --project <project> [--out <dir>] [--json]` (LC3,
//! #791; `contracts/loop-cli.v1.md`). One `room-cli loop list --json` read,
//! then one loop file (and its check) per loop of the project, by the
//! adapter's rules. A file that already exists is never replaced: the same
//! bytes are `unchanged`, other bytes refuse that loop with `export-exists`.
//! A loop the adapter cannot represent is reported with its refusals, and
//! the others are still written.

use std::fs;
use std::io::{ErrorKind, Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::time::Instant;

use openwiz_adapter_cloudroom::loop_files::{self, ExportRefusal, Exported};
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::limits::RUN_BUDGET;
use serde_json::{Value, json};

use crate::loop_files::{Args, escape_untrusted};

/// One loop's result in the report.
struct Outcome {
    exported: Exported,
    result: &'static str,
    files: Vec<String>,
}

/// Runs export with parsed `args`; returns the exit code.
pub fn run(args: &Args, stdout: &mut dyn Write, stderr: &mut dyn Write) -> i32 {
    let project = args.project.as_deref().unwrap_or_default();
    let out = args.out.as_deref().unwrap_or(".");
    let source = CloudRoomSource::from_path();
    let read = loop_files::read_list(&source, Instant::now() + RUN_BUDGET)
        .and_then(|items| loop_files::export_project(&items, project));
    let exports = match read {
        Ok(exports) => exports,
        Err(why) => {
            return failed(
                args.json,
                "read_failed",
                &format!("room-cli loop list failed: {why}; nothing was written"),
                "The loop list could not be read; nothing was written.",
                stdout,
                stderr,
            );
        }
    };
    if !HOLDS_FOLDERS
        && exports
            .iter()
            .any(|e| e.files.iter().any(|(rel, _)| rel.contains('/')))
    {
        return failed(
            args.json,
            "unavailable",
            &format!("{NO_HELD_FOLDER}; nothing was written"),
            "A loop with a check is exported only on Linux; nothing was written.",
            stdout,
            stderr,
        );
    }
    let mut outcomes = Vec::new();
    for exported in exports {
        match write(Path::new(out), exported) {
            Ok(outcome) => outcomes.push(outcome),
            Err(why) => {
                return failed(
                    args.json,
                    "read_failed",
                    &format!("could not write to {out}: {why}; the loops before it were written"),
                    "The export folder could not be written; the loops before it were written.",
                    stdout,
                    stderr,
                );
            }
        }
    }
    let code = if outcomes.iter().any(|o| o.result == "refused") {
        5
    } else {
        0
    };
    let printed = if args.json {
        let loops: Vec<Value> = outcomes.iter().map(entry).collect();
        let doc = json!({
            "schema": "openwiz.loop-export.v1", "command": "export", "exit_code": code,
            "project": project, "out": out, "loops": loops,
        });
        writeln!(stdout, "{doc}")
    } else {
        text(&outcomes, project, out, stdout, stderr)
    };
    if printed.is_err() { 1 } else { code }
}

/// Writes one loop's files under `out`, never replacing one with other
/// bytes. Every file is checked before any is written, so a refused loop
/// writes nothing. A check is read and created only through its folder held
/// open ([`Folder`]), so swapping that folder for a link between the check
/// and the write cannot put the check anywhere else.
fn write(out: &Path, mut exported: Exported) -> std::io::Result<Outcome> {
    if !exported.refusals.is_empty() {
        return Ok(refused(exported, Vec::new()));
    }
    let files = exported.files.clone();
    let mut exists = Vec::new();
    let mut missing = Vec::new();
    let mut held = None;
    for (rel, text) in &files {
        match rel.split_once('/') {
            None => match state(&out.join(rel), text)? {
                State::Missing => missing.push(rel.clone()),
                State::Same => {}
                State::Other => exists.push(out.join(rel)),
            },
            Some((dir, name)) => match Folder::open(&out.join(dir))? {
                Held::Missing => missing.push(rel.clone()),
                Held::NotFolder => exists.push(out.join(dir)),
                Held::Folder(folder) => {
                    match state(&folder.entry(name)?, text)? {
                        State::Missing => missing.push(rel.clone()),
                        State::Same => {}
                        State::Other => exists.push(out.join(rel)),
                    }
                    held = Some(folder);
                }
            },
        }
    }
    if !exists.is_empty() {
        return Ok(refused(exported, exists));
    }
    if !missing.is_empty() {
        fs::create_dir_all(out)?;
    }
    // The check first: if its folder turns out to be a link, nothing of this
    // loop has been written yet.
    for (rel, text) in files.iter().rev().filter(|(rel, _)| missing.contains(rel)) {
        let Some((dir, name)) = rel.split_once('/') else {
            create_new(&out.join(rel), text)?;
            continue;
        };
        let folder = match held.take() {
            Some(folder) => folder,
            None => {
                match fs::create_dir(out.join(dir)) {
                    Err(e) if e.kind() != ErrorKind::AlreadyExists => return Err(e),
                    _ => {}
                }
                match Folder::open(&out.join(dir))? {
                    Held::Folder(folder) => folder,
                    Held::Missing | Held::NotFolder => {
                        exported.files.clear();
                        return Ok(refused(exported, vec![out.join(dir)]));
                    }
                }
            }
        };
        create_new(&folder.entry(name)?, text)?;
    }
    let result = if missing.is_empty() {
        "unchanged"
    } else {
        "written"
    };
    Ok(Outcome {
        files: files.into_iter().map(|(rel, _)| rel).collect(),
        exported,
        result,
    })
}

/// The loop refused, with an `export-exists` refusal for each path.
fn refused(mut exported: Exported, exists: Vec<PathBuf>) -> Outcome {
    for path in exists {
        exported.refusals.push(ExportRefusal {
            file: exported.name.clone(),
            code: "export-exists".into(),
            field: "file".into(),
            message: format!(
                "{} already exists with other bytes; nothing was written for this loop",
                path.display()
            ),
        });
    }
    Outcome {
        exported,
        result: "refused",
        files: Vec::new(),
    }
}

/// Whether a check's folder can be held open and written through: only on
/// Linux, through `/proc/self/fd/<fd>`. Rust's standard library has no
/// `openat`, and this workspace allows no unsafe code and no `libc`, so on
/// macOS (and elsewhere) a check could be written only by pathname, which a
/// folder swapped for a link redirects (review R1). There a run with a check
/// is refused before anything is written.
const HOLDS_FOLDERS: bool = cfg!(target_os = "linux");

const NO_HELD_FOLDER: &str = "a loop with a check is exported only on Linux: this system cannot write a check through its folder held open, so a folder swapped for a link could put the check outside --out";

/// `O_NOFOLLOW | O_NONBLOCK`, and `O_DIRECTORY`: Linux UAPI asm-generic, or
/// arch/arm{,64} for ARM; XNU bsd/sys/fcntl.h for macOS.
fn no_follow() -> i32 {
    if cfg!(target_vendor = "apple") {
        0x0100 | 0x0004
    } else if cfg!(any(target_arch = "arm", target_arch = "aarch64")) {
        0o100000 | 0o4000
    } else {
        0o400000 | 0o4000
    }
}

fn directory() -> i32 {
    if cfg!(target_vendor = "apple") {
        0x0010_0000
    } else if cfg!(any(target_arch = "arm", target_arch = "aarch64")) {
        0o40000
    } else {
        0o200000
    }
}

/// What is at a file's path now.
enum State {
    Missing,
    Same,
    Other,
}

/// Compares the file at `path` with `text`, never following a link there
/// and reading at most one byte more than `text`.
fn state(path: &Path, text: &str) -> std::io::Result<State> {
    let file = match fs::OpenOptions::new()
        .read(true)
        .custom_flags(no_follow())
        .open(path)
    {
        Ok(file) => file,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(State::Missing),
        // A link, or anything else that cannot be opened as a plain file.
        Err(e) => {
            return match fs::symlink_metadata(path) {
                Ok(_) => Ok(State::Other),
                Err(_) => Err(e),
            };
        }
    };
    let meta = file.metadata()?;
    if !meta.is_file() || meta.len() != text.len() as u64 {
        return Ok(State::Other);
    }
    let mut bytes = Vec::with_capacity(text.len() + 1);
    file.take(text.len() as u64 + 1).read_to_end(&mut bytes)?;
    Ok(if bytes == text.as_bytes() {
        State::Same
    } else {
        State::Other
    })
}

/// Creates `path` with `text`; never through a file or link already there.
fn create_new(path: &Path, text: &str) -> std::io::Result<()> {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .custom_flags(no_follow())
        .open(path)?
        .write_all(text.as_bytes())
}

/// A check's folder, held open: opened without following a link, so every
/// later read and write of the check goes to this folder, whatever its path
/// points to by then.
struct Folder {
    file: fs::File,
}

enum Held {
    Missing,
    /// A link, a file or anything else that is not a folder.
    NotFolder,
    Folder(Folder),
}

impl Folder {
    fn open(path: &Path) -> std::io::Result<Held> {
        let file = match fs::OpenOptions::new()
            .read(true)
            .custom_flags(no_follow() | directory())
            .open(path)
        {
            Ok(file) => file,
            Err(e) if e.kind() == ErrorKind::NotFound => return Ok(Held::Missing),
            Err(e) => {
                return match fs::symlink_metadata(path) {
                    Ok(_) => Ok(Held::NotFolder),
                    Err(_) => Err(e),
                };
            }
        };
        if !file.metadata()?.is_dir() {
            return Ok(Held::NotFolder);
        }
        Ok(Held::Folder(Folder { file }))
    }

    /// The path of `name` inside this held folder, through the open handle
    /// (`/proc/self/fd/<fd>`), as the GitHub App key reader does. Only Linux
    /// has that route ([`HOLDS_FOLDERS`]); elsewhere this refuses, never
    /// falling back to the folder's pathname.
    fn entry(&self, name: &str) -> std::io::Result<PathBuf> {
        if !HOLDS_FOLDERS {
            return Err(std::io::Error::new(ErrorKind::Unsupported, NO_HELD_FOLDER));
        }
        use std::os::fd::AsRawFd;
        Ok(PathBuf::from(format!("/proc/self/fd/{}", self.file.as_raw_fd())).join(name))
    }
}

fn entry(outcome: &Outcome) -> Value {
    let e = &outcome.exported;
    json!({
        "loop": e.loop_id,
        "id": e.id,
        "result": outcome.result,
        "files": outcome.files,
        "binding": e.binding.as_ref().map(|id| json!({"id": id, "loop": e.loop_id})),
        "refusals": e.refusals.iter().map(|r| json!({
            "file": r.file, "code": r.code, "field": r.field, "message": r.message,
        })).collect::<Vec<_>>(),
        "unmapped": e.unmapped,
    })
}

fn text(
    outcomes: &[Outcome],
    project: &str,
    out: &str,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> std::io::Result<()> {
    let done = outcomes.iter().filter(|o| o.result != "refused").count();
    line(
        stdout,
        &format!(
            "Exported {done} of {} loops of project {project} to {out}.",
            outcomes.len()
        ),
    )?;
    for o in outcomes {
        let e = &o.exported;
        let id = e.id.as_deref().unwrap_or("-");
        let files: Vec<String> = o
            .files
            .iter()
            .map(|f| PathBuf::from(out).join(f).display().to_string())
            .collect();
        line(
            stdout,
            &format!("  {} {id}: {} {}", e.loop_id, o.result, files.join(" ")),
        )?;
        if let Some(binding) = &e.binding {
            line(
                stdout,
                &format!(
                    "    unmarked: plan and apply need --adopt {binding}={}",
                    e.loop_id
                ),
            )?;
        }
        if !e.unmapped.is_empty() {
            line(
                stdout,
                &format!(
                    "    unmapped: the file does not carry {}, which Cloudroom returned and the adapter does not map",
                    e.unmapped.join(", ")
                ),
            )?;
        }
        for r in &e.refusals {
            line(stderr, &format!("{}: {}: {}", r.file, r.field, r.message))?;
        }
    }
    Ok(())
}

/// A failure before any result: one line on stderr, and with `--json` one
/// `openwiz.cli-error.v1` document that carries none of room-cli's text.
fn failed(
    json: bool,
    kind: &str,
    what: &str,
    message: &str,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let _ = line(stderr, &format!("openwiz: loop export: {what}"));
    if json {
        let doc = json!({
            "schema": "openwiz.cli-error.v1", "command": "loop.export", "exit_code": 1,
            "error": {"kind": kind, "message": message},
        });
        let _ = writeln!(stdout, "{doc}");
    }
    1
}

/// Prints one line of human output with every untrusted part escaped: no
/// line here carries a control of its own, so the whole line is escaped.
fn line(stream: &mut dyn Write, text: &str) -> std::io::Result<()> {
    writeln!(stream, "{}", escape_untrusted(text))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::DirBuilderExt;

    fn scratch(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("openwiz-lc3-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        for dir in ["out/syn", "elsewhere"] {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(root.join(dir))
                .unwrap();
        }
        root
    }

    // catches: a check created by pathname after its folder was checked, so
    // swapping the folder for a link in between writes the check outside
    // --out (review R1, the window after the folder is opened). On Linux the
    // check goes into the held folder; where no held-folder route exists
    // (macOS), the check is refused, never resolved through the link.
    #[test]
    fn a_held_folder_keeps_the_check_inside_it_after_a_swap() {
        let root = scratch("swap");
        let Held::Folder(folder) = Folder::open(&root.join("out/syn")).unwrap() else {
            panic!("a real folder opens");
        };
        fs::rename(root.join("out/syn"), root.join("out/moved")).unwrap();
        std::os::unix::fs::symlink(root.join("elsewhere"), root.join("out/syn")).unwrap();
        let created = folder
            .entry("check")
            .and_then(|path| create_new(&path, "#!/bin/sh\nexit 0\n"));
        assert!(
            !root.join("elsewhere/check").exists(),
            "the check went through the link"
        );
        if cfg!(target_os = "linux") {
            created.unwrap();
            assert_eq!(
                fs::read_to_string(root.join("out/moved/check")).unwrap(),
                "#!/bin/sh\nexit 0\n"
            );
        } else {
            assert_eq!(created.unwrap_err().kind(), ErrorKind::Unsupported);
            assert!(!root.join("out/moved/check").exists());
        }
        fs::remove_dir_all(&root).unwrap();
    }

    // catches: a folder opened through a link that appeared before it was
    // opened (review R1, the window between the check and the open).
    #[test]
    fn a_folder_is_never_opened_through_a_link() {
        let root = scratch("link");
        fs::remove_dir(root.join("out/syn")).unwrap();
        std::os::unix::fs::symlink(root.join("elsewhere"), root.join("out/syn")).unwrap();
        assert!(matches!(
            Folder::open(&root.join("out/syn")).unwrap(),
            Held::NotFolder
        ));
        fs::write(root.join("out/file"), "x").unwrap();
        assert!(matches!(
            Folder::open(&root.join("out/file")).unwrap(),
            Held::NotFolder
        ));
        assert!(matches!(
            Folder::open(&root.join("out/none")).unwrap(),
            Held::Missing
        ));
        fs::remove_dir_all(&root).unwrap();
    }
}
