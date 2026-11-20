//! The command's state directory: where it is by default, that it is
//! never inside a repository, and that every directory and record it makes
//! is synced. Moved here from `tests/messaging/m10_record.rs` (M10) by #809,
//! and beside the state module it checks by #1264, through the start record
//! now that the send record is gone.

use std::ffi::OsString;
use std::fs::{self, DirBuilder};
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

use openwiz_cli::state::{StartFileStore, default_state_dir};

/// The repository root.
const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../..");

/// This run's own private directory, outside every repository (the
/// target directory is inside this one, where the store refuses to write):
/// named after the process and the time, so two runs at once never share
/// one, and never reused.
fn run_root() -> &'static Path {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        let parent = std::env::temp_dir().join("openwiz-state-tests");
        private_dir_all(&parent);
        let planted = fs::symlink_metadata(&parent).map_or(true, |m| !m.is_dir());
        assert!(!planted, "{parent:?} is not a plain directory");
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let dir = parent.join(format!("{}-{nanos}", std::process::id()));
        DirBuilder::new()
            .mode(0o700)
            .create(&dir)
            .expect("this run's own temp dir");
        let repo = Path::new(ROOT).canonicalize().unwrap();
        assert!(!dir.canonicalize().unwrap().starts_with(&repo), "{dir:?}");
        dir
    })
}

fn private_dir_all(dir: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(dir)
        .unwrap();
}

fn store_source() -> String {
    fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("src/state/mod.rs")).unwrap()
}

fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
    let pairs: Vec<(String, OsString)> = pairs
        .iter()
        .map(|(k, v)| ((*k).to_owned(), OsString::from(v)))
        .collect();
    move |name| {
        pairs
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.clone())
    }
}

#[test]
fn the_default_state_directory_is_the_owners_and_outside_the_repository() {
    let home = "/synthetic-home/owner";
    let default = default_state_dir(&env(&[("HOME", home)])).unwrap();
    if cfg!(target_os = "macos") {
        assert_eq!(
            default,
            PathBuf::from(home).join("Library/Application Support/openwiz")
        );
    } else {
        assert_eq!(default, PathBuf::from(home).join(".local/state/openwiz"));
        assert_eq!(
            default_state_dir(&env(&[
                ("HOME", home),
                ("XDG_STATE_HOME", "/synthetic-xdg")
            ]))
            .unwrap(),
            PathBuf::from("/synthetic-xdg/openwiz")
        );
        // A relative XDG_STATE_HOME is ignored, as the XDG spec says.
        assert_eq!(
            default_state_dir(&env(&[("HOME", home), ("XDG_STATE_HOME", "relative")])).unwrap(),
            default
        );
    }
    assert_eq!(
        default_state_dir(&env(&[
            ("HOME", home),
            ("OPENWIZ_STATE_DIR", "/synthetic-state")
        ]))
        .unwrap(),
        PathBuf::from("/synthetic-state")
    );
    // Haiku A7: a relative `OPENWIZ_STATE_DIR` is refused, not silently
    // replaced by the default.
    assert!(
        default_state_dir(&env(&[
            ("HOME", home),
            ("OPENWIZ_STATE_DIR", "relative/dir")
        ]))
        .is_err()
    );
    assert!(default_state_dir(&env(&[])).is_err(), "no HOME: no guess");
    assert!(default_state_dir(&env(&[("HOME", "relative")])).is_err());

    // With the real HOME, the default is not inside this repository.
    if let Some(real) = std::env::var_os("HOME") {
        let real = default_state_dir(&env(&[("HOME", real.to_str().unwrap())])).unwrap();
        let repo = Path::new(ROOT).canonicalize().unwrap();
        assert!(!real.starts_with(&repo), "{real:?} is inside {repo:?}");
    }
}

#[test]
fn every_write_syncs_the_file_and_its_directory() {
    let source = store_source();
    let body = source
        .split("fn write_record")
        .nth(1)
        .expect("the store writes records in one function, write_record");
    let body = &body[..body.find("\n}\n").expect("end of write_record")];
    let order = ["sync_all", "rename", "sync_all"]
        .iter()
        .try_fold(0, |at, word| {
            body[at..].find(word).map(|i| at + i + word.len())
        });
    assert!(
        order.is_some(),
        "write_record syncs the file, renames it into place, then syncs the directory:\n{body}"
    );
}

#[test]
fn every_created_directory_is_synced_in_its_parent() {
    let source = store_source();
    let body = source
        .split("fn create_dir_synced")
        .nth(1)
        .expect("the store creates directories in one function, create_dir_synced");
    let body = &body[..body.find("\n}\n").expect("end of create_dir_synced")];
    assert!(body.contains("create_dir"), "{body}");
    // Round 2: the parent is synced through the store's sync function,
    // which `open` sets to a real fsync.
    assert!(body.contains("sync(parent)"), "{body}");
    let fsync = source.split("fn fsync_dir").nth(1).expect("fsync_dir");
    assert!(fsync[..fsync.find("\n}\n").unwrap()].contains("sync_all"));
    assert!(source.contains("Self::open_with_sync(state_dir, &fsync_dir)"));
    let open = source
        .split("pub fn open_with_sync")
        .nth(1)
        .expect("open_with_sync");
    let open = &open[..open.find("\n    }\n").expect("end of open")];
    // #79 (Sol round 1): the checks moved into `checked_sends`, shared with
    // the read-only opener, which is given no sync and so makes nothing.
    assert!(
        open.contains("Self::checked_sends(state_dir, Some(sync))"),
        "{open}"
    );
    let checked = source
        .split("fn checked_sends")
        .nth(1)
        .expect("checked_sends");
    let checked = &checked[..checked.find("\n    }\n").expect("end of checked_sends")];
    assert!(
        checked.contains("create_dir_synced(dir, sync)"),
        "{checked}"
    );
    assert!(
        !checked.contains("DirBuilder") && !open.contains("DirBuilder"),
        "open creates directories only through create_dir_synced"
    );
    let read_only = source
        .split("pub fn open_read_only")
        .nth(1)
        .expect("open_read_only");
    let read_only = &read_only[..read_only.find("\n    }\n").unwrap()];
    assert!(
        read_only.contains("Self::checked_sends(state_dir, None)"),
        "{read_only}"
    );
}

/// Sol S4: a state directory inside a repository is refused, however it is
/// named.
#[test]
fn a_state_directory_inside_a_repository_is_refused() {
    let repo = run_root().join("m10_repo");
    let _ = fs::remove_dir_all(&repo);
    private_dir_all(&repo.join(".git"));
    let state = repo.join("nested").join("state");
    assert!(StartFileStore::open(&state).is_err());
    assert!(!state.exists(), "nothing created inside the repository");
    // Through a symlink from outside, too.
    let link = run_root().join("m10_repo_link");
    let _ = fs::remove_file(&link);
    std::os::unix::fs::symlink(&repo, &link).unwrap();
    assert!(StartFileStore::open(&link.join("state")).is_err());
    let _ = fs::remove_file(&link);
    let _ = fs::remove_dir_all(&repo);
}

/// Sol S2, round 2: an opener syncs the whole directory chain every time,
/// also when another opener created it and may not have synced it yet.
#[test]
fn every_opener_syncs_the_whole_directory_chain() {
    use std::sync::Mutex;
    let base = run_root().join("m10_chain");
    let _ = fs::remove_dir_all(&base);
    // Another opener made the chain and was stopped before syncing it.
    let state = base.join("a").join("state");
    private_dir_all(&state.join("starts"));
    let synced = Mutex::new(Vec::<PathBuf>::new());
    let record = |dir: &Path| {
        synced.lock().unwrap().push(dir.to_path_buf());
        Ok(())
    };
    let store = StartFileStore::open_with_sync(&state, &record).unwrap();
    let synced = synced.into_inner().unwrap();
    let resolved = state.join("starts").canonicalize().unwrap();
    for dir in resolved.ancestors() {
        assert!(
            synced
                .iter()
                .any(|s| s.canonicalize().ok().as_deref() == Some(dir)),
            "{dir:?} was not synced: {synced:?}"
        );
    }
    drop(store);
    let _ = fs::remove_dir_all(&base);
}

/// Sol S4, round 2: a `starts` that leads into a repository, and a path
/// that only reaches one through `..`, are both refused; nothing is written
/// in the repository.
#[test]
fn no_path_trick_puts_the_record_inside_a_repository() {
    let base = run_root().join("m10_repo_tricks");
    let _ = fs::remove_dir_all(&base);
    let repo = base.join("synthetic-repo");
    private_dir_all(&repo.join(".git"));
    let inside = repo.join("records");
    DirBuilder::new().mode(0o700).create(&inside).unwrap();

    // 1. An outside state directory whose `starts` is a symlink into it.
    let outside = base.join("outside-state");
    private_dir_all(&outside);
    std::os::unix::fs::symlink(&inside, outside.join("starts")).unwrap();
    assert!(StartFileStore::open(&outside).is_err(), "a starts symlink");

    // 2. A path that reaches the repository through `..` of a missing
    //    directory.
    let dotted = base
        .join("missing")
        .join("..")
        .join("synthetic-repo")
        .join("state");
    assert!(StartFileStore::open(&dotted).is_err(), "a .. path");
    assert!(
        !repo.join("state").exists(),
        "nothing made in the repository"
    );
    assert_eq!(
        fs::read_dir(&inside).unwrap().count(),
        0,
        "nothing written in the repository"
    );
    let _ = fs::remove_dir_all(&base);
}
