use std::fs;
use std::io::ErrorKind;
use std::io::{Read, Write};
use std::os::fd::AsFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::{Component, Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use crate::allowlist::{MAC_BUNDLE_CLI, PC_BUNDLE_CLI, PC_BUNDLE_PREFIX, PC_BUNDLE_ROOT};

static DISCOVERY: OnceLock<Discovery> = OnceLock::new();

pub struct Discovery {
    root: PathBuf,
    metadata: fn(&fs::Metadata) -> LauncherMetadata,
    fixed: bool,
    process_root: PathBuf,
    search_path: Option<std::ffi::OsString>,
}

impl Discovery {
    pub fn with_process_root(mut self, root: PathBuf) -> Self {
        self.process_root = root;
        self
    }

    pub fn with_search_path(mut self, path: std::ffi::OsString) -> Self {
        self.search_path = Some(path);
        self
    }

    pub fn pc(root: PathBuf, metadata: fn(&fs::Metadata) -> LauncherMetadata) -> Self {
        Self {
            root,
            metadata,
            fixed: false,
            process_root: PathBuf::from("/proc"),
            search_path: None,
        }
    }

    pub fn fixed(path: PathBuf, metadata: fn(&fs::Metadata) -> LauncherMetadata) -> Self {
        Self {
            root: path,
            metadata,
            fixed: true,
            process_root: PathBuf::from("/proc"),
            search_path: None,
        }
    }

    pub fn system() -> Self {
        let discovery = if cfg!(target_os = "macos") {
            Self::fixed(PathBuf::from(MAC_BUNDLE_CLI), real_metadata)
        } else {
            Self::pc(PathBuf::from(PC_BUNDLE_ROOT), real_metadata)
        };
        match std::env::var_os("PATH") {
            Some(path) => discovery.with_search_path(path),
            None => discovery,
        }
    }

    pub fn resolve(&self) -> Result<PathBuf, LocateError> {
        self.locate().map(|located| located.launcher)
    }

    pub fn locate(&self) -> Result<Located, LocateError> {
        self.candidates().map(|mut found| found.swap_remove(0))
    }

    pub fn candidates(&self) -> Result<Vec<Located>, LocateError> {
        match retry_ambiguous(Duration::from_millis(100), || self.locate_once()) {
            Err(error @ (LocateError::NotRunning | LocateError::NoRunningApp)) => {
                let found: Vec<_> = self
                    .on_search_path()
                    .into_iter()
                    .map(|launcher| Located {
                        launcher,
                        basis: Basis::Path,
                    })
                    .collect();
                if found.is_empty() {
                    Err(error)
                } else {
                    Ok(found)
                }
            }
            located => located.map(|one| vec![one]),
        }
    }

    fn on_search_path(&self) -> Vec<PathBuf> {
        let Some(search) = self.search_path.as_ref() else {
            return Vec::new();
        };
        std::env::split_paths(search)
            .filter(|dir| dir.is_absolute())
            .map(|dir| dir.join(crate::PROGRAM))
            .filter(|candidate| {
                fs::metadata(candidate).is_ok_and(|file| {
                    file.is_file() && file.mode() & 0o111 != 0 && file.mode() & 0o022 == 0
                })
            })
            .collect()
    }

    fn locate_once(&self) -> Result<Located, LocateError> {
        if !self.root.is_absolute() {
            return Err(LocateError::UnexpectedFile);
        }
        let (launcher, basis) = if self.fixed {
            check_directories(self.root.parent().ok_or(LocateError::UnexpectedFile)?)?;
            (self.root.clone(), Basis::Fixed)
        } else {
            self.running_bundle_candidate()?
        };
        self.verify(&launcher)?;
        Ok(Located { launcher, basis })
    }

    fn verify(&self, candidate: &Path) -> Result<(), LocateError> {
        let metadata = fs::symlink_metadata(candidate).map_err(|_| LocateError::Unreadable)?;
        if !metadata.is_file() {
            return Err(LocateError::UnexpectedFile);
        }
        check_siblings(candidate).map_err(|_| LocateError::UnexpectedFile)?;
        let mut prefix = [0; b"#!/bin/sh\n\":\" //;".len()];
        fs::File::open(candidate)
            .and_then(|mut file| file.read_exact(&mut prefix))
            .map_err(|_| LocateError::UnexpectedFile)?;
        let owner = if self.fixed {
            let app = candidate
                .ancestors()
                .nth(8)
                .ok_or(LocateError::UnexpectedFile)?;
            if app.file_name() != Some(std::ffi::OsStr::new("Cloudroom.app")) {
                return Err(LocateError::UnexpectedFile);
            }
            let app_metadata = fs::symlink_metadata(app).map_err(|_| LocateError::Unreadable)?;
            if !app_metadata.is_dir() {
                return Err(LocateError::UnexpectedFile);
            }
            (self.metadata)(&app_metadata).uid
        } else {
            0
        };
        check_markers_for_owner((self.metadata)(&metadata), &prefix, owner)
    }

    fn running_bundle_candidate(&self) -> Result<(PathBuf, Basis), LocateError> {
        self.running_bundle_candidate_with(|_| {})
    }

    fn running_bundle_candidate_with(
        &self,
        mut before_read: impl FnMut(&Path),
    ) -> Result<(PathBuf, Basis), LocateError> {
        check_directories(&self.root)?;
        check_directories(&self.process_root)?;
        let user = fs::metadata(self.process_root.join("self"))
            .map_err(|_| LocateError::Unreadable)?
            .uid();
        let entries = fs::read_dir(&self.process_root).map_err(|_| LocateError::Unreadable)?;
        let mut roots: Vec<Root> = Vec::new();
        let mut descendants = Vec::new();
        for entry in entries {
            let found = entry
                .map_err(|_| LocateError::Unreadable)
                .and_then(|entry| self.running_root(&entry, user, &mut before_read));
            let (pid, mount, candidate) = match found {
                Ok(Some(found)) => found,
                Ok(None) => continue,
                Err(_) if roots.len() > 1 => return Err(LocateError::Ambiguous),
                Err(error) => return Err(error),
            };
            if self.own_descendant(&pid, user) {
                self.verify(&candidate)?;
                let file = fs::symlink_metadata(&candidate).map_err(|_| LocateError::Unreadable)?;
                if !file.is_file() {
                    return Err(LocateError::UnexpectedFile);
                }
                descendants.push((candidate, file.dev(), file.ino()));
                continue;
            }
            let known = roots.len();
            match roots.iter_mut().find(|root| root.launcher == candidate) {
                Some(root) => root.pids.push(pid),
                None if known > 1 => return Err(LocateError::Ambiguous),
                None => roots.push(Root {
                    mount,
                    launcher: candidate,
                    pids: vec![pid],
                }),
            }
        }
        if !roots.is_empty()
            && descendants.iter().any(|(launcher, dev, ino)| {
                !roots.iter().any(|root| {
                    root.launcher == *launcher
                        && fs::symlink_metadata(&root.launcher).is_ok_and(|file| {
                            file.is_file() && file.dev() == *dev && file.ino() == *ino
                        })
                })
            })
        {
            return Err(LocateError::Ambiguous);
        }
        roots.sort_by(|a, b| a.launcher.cmp(&b.launcher));
        match roots.as_slice() {
            [one] => return Ok((one.launcher.clone(), Basis::OneRoot)),
            [first, second] => {
                return self
                    .appimage_pair(user, [first, second])
                    .ok_or(LocateError::Ambiguous);
            }
            _ => {}
        }
        match pc_bundle_candidate(&self.root) {
            Ok(_) | Err(LocateError::Ambiguous) => Err(LocateError::NoRunningApp),
            Err(error) => Err(error),
        }
    }

    fn running_root(
        &self,
        entry: &fs::DirEntry,
        user: u32,
        before_read: &mut impl FnMut(&Path),
    ) -> Result<Option<(String, PathBuf, PathBuf)>, LocateError> {
        let name = entry.file_name();
        let bytes = name.as_encoded_bytes();
        if bytes.is_empty() || bytes[0] == b'0' || !bytes.iter().all(u8::is_ascii_digit) {
            return Ok(None);
        }
        let process = entry.path();
        let metadata = match fs::symlink_metadata(&process) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(LocateError::Unreadable),
        };
        if !metadata.is_dir() {
            return Err(LocateError::UnexpectedFile);
        }
        if metadata.uid() != user {
            return Ok(None);
        }
        let exe = process.join("exe");
        let target = match fs::read_link(&exe) {
            Ok(target) => target,
            Err(error)
                if matches!(
                    error.kind(),
                    ErrorKind::NotFound | ErrorKind::PermissionDenied
                ) =>
            {
                return Ok(None);
            }
            Err(error) if error.kind() == ErrorKind::InvalidInput => {
                return Err(LocateError::UnexpectedFile);
            }
            Err(_) => return Err(LocateError::Unreadable),
        };
        let Ok(relative) = target.strip_prefix(&self.root) else {
            return Ok(None);
        };
        let parts: Vec<_> = relative.components().collect();
        let [Component::Normal(mount), Component::Normal(app)] = parts.as_slice() else {
            return Ok(None);
        };
        if !mount
            .as_encoded_bytes()
            .starts_with(PC_BUNDLE_PREFIX.as_bytes())
        {
            return Ok(None);
        }
        let mount = self.root.join(mount);
        if target != mount.join(app) {
            return Err(LocateError::UnexpectedFile);
        }
        let Some(candidate) = bundle_file(&mount, false)? else {
            return Ok(None);
        };
        before_read(&mount);
        match check_directories(&mount) {
            Ok(()) => {}
            Err(LocateError::NotRunning) => return Ok(None),
            Err(error) => return Err(error),
        }
        before_read(&target);
        let app_metadata = match fs::symlink_metadata(&target) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(LocateError::Unreadable),
        };
        before_read(&exe);
        let running = match fs::metadata(&exe) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(LocateError::Unreadable),
        };
        let facts = (self.metadata)(&app_metadata);
        if !app_metadata.is_file()
            || facts.uid != 0
            || facts.mode & 0o022 != 0
            || facts.mode & 0o111 == 0
            || app_metadata.dev() != running.dev()
            || app_metadata.ino() != running.ino()
        {
            return Err(LocateError::UnexpectedFile);
        }
        before_read(&exe);
        match fs::read_link(&exe) {
            Ok(current) if current == target => {}
            Ok(_) => return Err(LocateError::UnexpectedFile),
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(LocateError::Unreadable),
        }
        Ok(Some((
            name.to_string_lossy().into_owned(),
            mount,
            candidate,
        )))
    }

    fn own_descendant(&self, pid: &str, user: u32) -> bool {
        self.descendant_of(pid, std::process::id(), user)
    }

    fn descendant_of(&self, pid: &str, ancestor: u32, user: u32) -> bool {
        let Some(ancestor_identity) = self.process_identity(ancestor, user) else {
            return false;
        };
        let Ok(mut current) = pid.parse::<u32>() else {
            return false;
        };
        let mut family = Vec::new();
        let mut child_start = u64::MAX;
        for _ in 0..64 {
            if current == ancestor {
                return !family.is_empty()
                    && ancestor_identity.1 <= child_start
                    && self.process_identity(ancestor, user) == Some(ancestor_identity)
                    && family.iter().rev().all(|&(pid, identity)| {
                        self.process_identity(pid, user) == Some(identity)
                    });
            }
            let Some(identity) = self.process_identity(current, user) else {
                return false;
            };
            if identity.1 < ancestor_identity.1
                || identity.1 > child_start
                || family.iter().any(|&(pid, _)| pid == current)
            {
                return false;
            }
            family.push((current, identity));
            child_start = identity.1;
            current = identity.0;
        }
        false
    }

    fn process_identity(&self, pid: u32, user: u32) -> Option<(u32, u64)> {
        let process = self.process_root.join(pid.to_string());
        let metadata = fs::symlink_metadata(&process).ok()?;
        if !metadata.is_dir() || metadata.uid() != user {
            return None;
        }
        let stat = read_bounded(&process.join("stat"), STAT_LIMIT)?;
        let stat = std::str::from_utf8(&stat).ok()?;
        let rest = stat.strip_prefix(&format!("{pid} ("))?;
        let mut fields = rest[rest.rfind(')')? + 1..].split_ascii_whitespace();
        let state = fields.next()?;
        if state.len() != 1 || !state.bytes().all(|b| b.is_ascii_alphabetic()) {
            return None;
        }
        let parent = fields.next()?;
        let start = fields.nth(17)?;
        if [parent, start]
            .iter()
            .any(|v| v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()))
        {
            return None;
        }
        Some((parent.parse().ok()?, start.parse().ok()?))
    }

    fn appimage_pair(&self, user: u32, roots: [&Root; 2]) -> Option<(PathBuf, Basis)> {
        let mut family = Vec::new();
        for (index, root) in roots.iter().enumerate() {
            for pid in &root.pids {
                let pid: u32 = pid.parse().ok()?;
                family.push((pid, self.parent(pid)?, index));
            }
        }
        for i in 0..family.len() {
            let (pid, parent, index) = family[i];
            if family.iter().any(|&(member, ..)| member == parent) {
                continue;
            }
            let mut current = parent;
            for _ in 0..64 {
                if let Some(&(ancestor, _, root)) =
                    family.iter().find(|&&(member, ..)| member == current)
                {
                    if root == index && self.descendant_of(&pid.to_string(), ancestor, user) {
                        family[i].1 = ancestor;
                    }
                    break;
                }
                let Some((parent, _)) = self.process_identity(current, user) else {
                    break;
                };
                current = parent;
            }
        }
        let member = |pid: u32| family.iter().find(|(member, ..)| *member == pid);
        let mut heads = [None; 2];
        for &(pid, parent, index) in &family {
            if member(parent).is_none_or(|&(.., root)| root != index)
                && heads[index].replace(pid).is_some()
            {
                return None;
            }
        }
        let heads = [heads[0]?, heads[1]?];
        for &(pid, _, index) in &family {
            let mut current = pid;
            for _ in 0..family.len() {
                if current == heads[index] {
                    break;
                }
                current = member(current)?.1;
            }
            if current != heads[index] {
                return None;
            }
        }
        let parent_of = |index: usize| member(heads[index]).map(|&(_, parent, _)| parent);
        let bridge = match (parent_of(0)? == heads[1], parent_of(1)? == heads[0]) {
            (false, true) => 1,
            (true, false) => 0,
            _ => return None,
        };
        let gui = 1 - bridge;
        let launcher = parent_of(gui)?;
        if member(launcher).is_some() {
            return None;
        }
        let process = fs::symlink_metadata(self.process_root.join(launcher.to_string())).ok()?;
        if !process.is_dir() || process.uid() != user {
            return None;
        }
        let appimage = self.appimage_record(launcher, &roots[gui].mount)?;
        if self.appimage_record(heads[bridge], &roots[bridge].mount)? != appimage {
            return None;
        }
        for root in roots {
            self.verify(&root.launcher).ok()?;
        }
        if read_bounded(&roots[0].launcher, LAUNCHER_LIMIT)?
            != read_bounded(&roots[1].launcher, LAUNCHER_LIMIT)?
        {
            return None;
        }
        Some((
            roots[bridge].launcher.clone(),
            Basis::AppImagePair {
                gui: roots[gui].mount.clone(),
                bridge: roots[bridge].mount.clone(),
            },
        ))
    }

    fn parent(&self, pid: u32) -> Option<u32> {
        let stat = read_bounded(
            &self.process_root.join(pid.to_string()).join("stat"),
            STAT_LIMIT,
        )?;
        let stat = std::str::from_utf8(&stat).ok()?;
        let rest = stat.strip_prefix(&format!("{pid} ("))?;
        let mut fields = rest[rest.rfind(')')? + 1..].split_ascii_whitespace();
        let (_state, parent) = (fields.next()?, fields.next()?);
        if parent.is_empty() || !parent.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        parent.parse().ok()
    }

    fn appimage_record(&self, pid: u32, mount: &Path) -> Option<(PathBuf, (u64, u64))> {
        let environ = read_bounded(
            &self.process_root.join(pid.to_string()).join("environ"),
            ENVIRON_LIMIT,
        )?;
        let only = |key: &[u8]| {
            let mut values = environ
                .split(|byte| *byte == 0)
                .filter_map(|entry| entry.strip_prefix(key));
            match (values.next(), values.next()) {
                (Some(value), None) => Some(value),
                _ => None,
            }
        };
        if only(b"APPDIR=")? != mount.as_os_str().as_bytes() {
            return None;
        }
        let path = Path::new(std::ffi::OsStr::from_bytes(only(b"APPIMAGE=")?));
        if fs::canonicalize(path).ok()?.as_os_str() != path.as_os_str() {
            return None;
        }
        let file = fs::symlink_metadata(path).ok()?;
        file.is_file()
            .then(|| (path.to_path_buf(), (file.dev(), file.ino())))
    }
}

fn retry_ambiguous<T>(
    budget: Duration,
    mut read: impl FnMut() -> Result<T, LocateError>,
) -> Result<T, LocateError> {
    let stop = std::time::Instant::now() + budget;
    let mut result = read();
    for _ in 1..3 {
        if !matches!(result, Err(LocateError::Ambiguous)) {
            return result;
        }
        let remaining = stop.saturating_duration_since(std::time::Instant::now());
        if remaining.is_zero() {
            return result;
        }
        std::thread::sleep(Duration::from_millis(10).min(remaining));
        if std::time::Instant::now() >= stop {
            return result;
        }
        result = read();
    }
    result
}

const STAT_LIMIT: u64 = 4096;
const ENVIRON_LIMIT: u64 = 1 << 20;
const LAUNCHER_LIMIT: u64 = 16 << 20;

#[cfg(test)]
mod ambiguous_retry_tests {
    use super::*;

    #[test]
    fn only_ambiguity_retries_with_attempt_and_time_bounds() {
        let mut calls = 0;
        let result = retry_ambiguous(Duration::from_secs(1), || {
            calls += 1;
            if calls == 1 {
                Err(LocateError::Ambiguous)
            } else {
                Ok("verified fixture")
            }
        });
        assert_eq!(result, Ok("verified fixture"));
        assert_eq!(calls, 2);

        for (budget, error, expected_calls) in [
            (Duration::from_secs(1), LocateError::Ambiguous, 3),
            (Duration::ZERO, LocateError::Ambiguous, 1),
            (Duration::from_secs(1), LocateError::UnexpectedFile, 1),
            (Duration::from_secs(1), LocateError::Unreadable, 1),
            (Duration::from_secs(1), LocateError::NoRunningApp, 1),
            (Duration::from_secs(1), LocateError::NotRunning, 1),
        ] {
            let mut calls = 0;
            let result: Result<(), _> = retry_ambiguous(budget, || {
                calls += 1;
                Err(error)
            });
            assert_eq!(result, Err(error));
            assert_eq!(calls, expected_calls, "{error:?}, {budget:?}");
        }
    }

    #[test]
    fn a_positive_budget_stops_retries_once_a_scan_overruns_it() {
        let mut calls = 0;
        let result: Result<(), _> = retry_ambiguous(Duration::from_millis(20), || {
            calls += 1;
            if calls == 1 {
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(LocateError::Ambiguous)
        });
        assert_eq!(result, Err(LocateError::Ambiguous));
        assert_eq!(calls, 1);
    }
}

fn read_bounded(path: &Path, limit: u64) -> Option<Vec<u8>> {
    let mut bytes = Vec::new();
    fs::File::open(path)
        .ok()?
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .ok()?;
    (bytes.len() as u64 <= limit).then_some(bytes)
}

struct Root {
    mount: PathBuf,
    launcher: PathBuf,
    pids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Basis {
    Fixed,
    OneRoot,
    Path,
    AppImagePair { gui: PathBuf, bridge: PathBuf },
}

impl Basis {
    pub fn describe(&self) -> String {
        match self {
            Self::Fixed => "room-cli from the fixed app bundle".to_owned(),
            Self::OneRoot => "room-cli from the one running app mount".to_owned(),
            Self::Path => "room-cli from PATH".to_owned(),
            Self::AppImagePair { gui, bridge } => format!(
                "room-cli from the bridge's mount {} (paired with the GUI's mount {}: \
                 one AppImage file, identical room-cli)",
                shown(bridge),
                shown(gui)
            ),
        }
    }
}

fn shown(path: &Path) -> String {
    path.display()
        .to_string()
        .chars()
        .map(|c| if c.is_control() { '?' } else { c })
        .collect()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Located {
    pub launcher: PathBuf,
    pub basis: Basis,
}

fn check_directories(path: &Path) -> Result<(), LocateError> {
    if !path.is_absolute() {
        return Err(LocateError::UnexpectedFile);
    }
    let mut current = PathBuf::new();
    for part in path.components() {
        if !matches!(part, Component::RootDir | Component::Normal(_)) {
            return Err(LocateError::UnexpectedFile);
        }
        current.push(part);
        let metadata = fs::symlink_metadata(&current).map_err(|error| match error.kind() {
            ErrorKind::NotFound => LocateError::NotRunning,
            _ => LocateError::Unreadable,
        })?;
        if !metadata.is_dir() {
            return Err(LocateError::UnexpectedFile);
        }
    }
    Ok(())
}

fn real_metadata(metadata: &fs::Metadata) -> LauncherMetadata {
    LauncherMetadata {
        uid: metadata.uid(),
        mode: metadata.mode(),
    }
}

pub fn install(discovery: Discovery) -> Result<(), LocateError> {
    DISCOVERY
        .set(discovery)
        .map_err(|_| LocateError::UnexpectedFile)
}

pub fn programs(program: &Path) -> Result<Vec<PathBuf>, openwiz_core::source::SourceError> {
    if program == Path::new(crate::PROGRAM) {
        let found = DISCOVERY.get_or_init(Discovery::system).candidates()?;
        report(&found[0].basis);
        Ok(found.into_iter().map(|located| located.launcher).collect())
    } else if program.is_absolute() {
        Ok(vec![program.to_path_buf()])
    } else {
        Err(LocateError::UnexpectedFile.into())
    }
}

fn report(basis: &Basis) {
    static LAST: Mutex<Option<Basis>> = Mutex::new(None);
    let mut last = LAST.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    if last.as_ref() != Some(basis) {
        if matches!(basis, Basis::AppImagePair { .. })
            && let Ok(fd) = std::io::stderr().as_fd().try_clone_to_owned()
        {
            let line = format!("openwiz: note: {}\n", basis.describe());
            let _ = fs::File::from(fd).write_all(line.as_bytes());
        }
        *last = Some(basis.clone());
    }
}

impl From<LocateError> for openwiz_core::source::SourceError {
    fn from(error: LocateError) -> Self {
        let reason = match error {
            LocateError::NotRunning => "no bundled launcher and no room-cli on PATH",
            LocateError::NoRunningApp => "no running app identified",
            LocateError::Ambiguous => "ambiguous app bundles",
            LocateError::UnexpectedFile => "unexpected bundle file",
            LocateError::Unreadable => "unreadable app bundle",
        };
        let detail = format!("CloudRoom not running: room-cli could not be started ({reason})");
        let detail = match error {
            LocateError::Ambiguous => format!(
                "{detail}. CloudRoom is mid-update (two running app mounts): \
                 restart CloudRoom to finish the update, then try again."
            ),
            LocateError::NotRunning | LocateError::NoRunningApp => {
                format!("{detail}. Open the CloudRoom app once and sign in.")
            }
            _ => detail,
        };
        Self::Unavailable { detail }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocateError {
    NotRunning,
    NoRunningApp,
    Ambiguous,
    UnexpectedFile,
    Unreadable,
}

#[derive(Clone, Copy, Debug)]
pub struct LauncherMetadata {
    pub uid: u32,
    pub mode: u32,
}

pub fn check_launcher_markers(
    metadata: LauncherMetadata,
    prefix: &[u8],
) -> Result<(), LocateError> {
    check_markers_for_owner(metadata, prefix, 0)
}

fn check_markers_for_owner(
    metadata: LauncherMetadata,
    prefix: &[u8],
    owner: u32,
) -> Result<(), LocateError> {
    if metadata.uid == owner
        && metadata.mode & 0o022 == 0
        && metadata.mode & 0o111 != 0
        && prefix.starts_with(b"#!/bin/sh\n\":\" //;")
    {
        Ok(())
    } else {
        Err(LocateError::UnexpectedFile)
    }
}

pub fn pc_bundle_candidate(root: &Path) -> Result<PathBuf, LocateError> {
    let entries = fs::read_dir(root).map_err(|error| match error.kind() {
        ErrorKind::NotFound => LocateError::NotRunning,
        _ => LocateError::Unreadable,
    })?;
    let mut found = None;
    for entry in entries {
        let entry = entry.map_err(|_| LocateError::Unreadable)?;
        if entry
            .file_name()
            .as_encoded_bytes()
            .starts_with(PC_BUNDLE_PREFIX.as_bytes())
            && let Some(candidate) = bundle_file(&entry.path(), true)?
        {
            if found.is_some() {
                return Err(LocateError::Ambiguous);
            }
            found = Some(candidate);
        }
    }
    found.ok_or(LocateError::NotRunning)
}

fn bundle_file(mount: &Path, skip_unsearchable: bool) -> Result<Option<PathBuf>, LocateError> {
    let mut path = mount.to_path_buf();
    let components: Vec<_> = Path::new(PC_BUNDLE_CLI).components().collect();
    for index in 0..=components.len() {
        if index > 0 {
            path.push(components[index - 1]);
        }
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) if cannot_search(&error) && skip_unsearchable => return Ok(None),
            Err(_) => return Err(LocateError::Unreadable),
        };
        if index == 0 && !metadata.is_dir() {
            return Ok(None);
        }
        let expected_type = if index == components.len() {
            metadata.is_file()
        } else {
            metadata.is_dir()
        };
        if !expected_type {
            return Err(LocateError::UnexpectedFile);
        }
    }
    if let Err(error) = check_siblings(&path) {
        return if cannot_search(&error) && skip_unsearchable {
            Ok(None)
        } else if cannot_search(&error) {
            Err(LocateError::Unreadable)
        } else {
            Err(LocateError::UnexpectedFile)
        };
    }
    Ok(Some(path))
}

fn cannot_search(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        ErrorKind::PermissionDenied | ErrorKind::NotConnected
    )
}

fn check_siblings(path: &Path) -> std::io::Result<()> {
    for sibling in ["daemon-bundle.mjs", "index.js"] {
        let metadata = fs::symlink_metadata(path.with_file_name(sibling))?;
        if !metadata.is_file() {
            return Err(ErrorKind::InvalidData.into());
        }
    }
    Ok(())
}

#[cfg(test)]
mod process_exit_tests {
    use super::*;
    use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Fixture(PathBuf);

    fn directory(path: &Path) {
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(path)
            .unwrap();
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn scan(phase: usize, has_survivor: bool, mutation: fn(&Path)) -> Result<PathBuf, LocateError> {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let fixture = Fixture(Path::new("/tmp").join(format!(
            "openwiz-process-exit-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )));
        directory(&fixture.0);
        let proc = fixture.0.join("proc");
        directory(&proc.join("self"));
        let mut survivor = None;
        for pid in ["101", "102"] {
            if pid == "102" && !has_survivor {
                continue;
            }
            let mount = fixture.0.join(format!(".mount_synthetic_{pid}"));
            let cli = mount.join(PC_BUNDLE_CLI);
            directory(cli.parent().unwrap());
            fs::write(&cli, "#!/bin/sh\n\":\" //; exit 0\n").unwrap();
            for sibling in ["daemon-bundle.mjs", "index.js"] {
                fs::write(cli.with_file_name(sibling), "synthetic sibling\n").unwrap();
            }
            let app = mount.join("synthetic-app");
            fs::write(&app, "synthetic app\n").unwrap();
            fs::set_permissions(&app, fs::Permissions::from_mode(0o555)).unwrap();
            directory(&proc.join(pid));
            symlink(app, proc.join(pid).join("exe")).unwrap();
            if pid == "102" {
                survivor = Some(cli);
            }
        }
        let discovery = Discovery::pc(fixture.0.clone(), |m| LauncherMetadata {
            uid: 0,
            mode: m.mode(),
        })
        .with_process_root(proc);
        let mut reads = 0;
        let result = discovery
            .running_bundle_candidate_with(|path| {
                if path
                    .strip_prefix(&fixture.0)
                    .unwrap()
                    .components()
                    .any(|part| {
                        part.as_os_str() == "101" || part.as_os_str() == ".mount_synthetic_101"
                    })
                {
                    reads += 1;
                    if reads == phase {
                        mutation(path);
                    }
                }
            })
            .map(|(launcher, _)| launcher);
        assert_eq!(reads, phase, "the mutation must reach its intended read");
        if let Some(expected) = survivor {
            assert_eq!(result, Ok(expected));
        }
        result
    }

    fn disappears(phase: usize) {
        for has_survivor in [false, true] {
            let result = scan(phase, has_survivor, |path| {
                if path.is_dir() {
                    fs::remove_dir_all(path).unwrap();
                } else {
                    fs::remove_file(path).unwrap();
                }
            });
            if !has_survivor {
                assert_eq!(
                    result,
                    Err(if phase == 1 {
                        LocateError::NotRunning
                    } else {
                        LocateError::NoRunningApp
                    })
                );
            }
        }
    }

    fn vanished_mount_is_skipped() {
        disappears(1);
    }

    fn vanished_target_is_skipped() {
        disappears(2);
    }

    fn vanished_exe_before_metadata_is_skipped() {
        disappears(3);
    }

    fn vanished_exe_before_final_link_is_skipped() {
        disappears(4);
    }

    #[test]
    fn vanished_process_entries_are_skipped_at_every_read_phase() {
        let cases: [(&str, fn()); 4] = [
            ("vanished_mount_is_skipped", vanished_mount_is_skipped),
            ("vanished_target_is_skipped", vanished_target_is_skipped),
            (
                "vanished_exe_before_metadata_is_skipped",
                vanished_exe_before_metadata_is_skipped,
            ),
            (
                "vanished_exe_before_final_link_is_skipped",
                vanished_exe_before_final_link_is_skipped,
            ),
        ];
        for (name, case) in cases {
            eprintln!("{name}");
            case();
        }
    }

    #[test]
    fn other_metadata_errors_still_fail_closed() {
        assert_eq!(
            scan(3, false, |path| {
                fs::remove_file(path).unwrap();
                symlink(path, path).unwrap();
            }),
            Err(LocateError::Unreadable)
        );
    }

    #[test]
    fn changed_executable_identity_still_fails_closed() {
        assert_eq!(
            scan(4, false, |path| {
                fs::remove_file(path).unwrap();
                symlink("synthetic-replacement", path).unwrap();
            }),
            Err(LocateError::UnexpectedFile)
        );
    }
}

#[cfg(test)]
mod mid_update_tests {
    use super::*;
    use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Fixture(PathBuf);

    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn directory(path: &Path) {
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(path)
            .unwrap();
    }

    impl Fixture {
        fn new(mounts: &[&str]) -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let fixture = Fixture(Path::new("/tmp").join(format!(
                "openwiz-mid-update-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            )));
            directory(&fixture.0.join("proc/self"));
            for mount in mounts {
                let cli = fixture.cli(mount);
                directory(cli.parent().unwrap());
                fs::write(&cli, "#!/bin/sh\n\":\" //; exit 0\n").unwrap();
                fs::set_permissions(&cli, fs::Permissions::from_mode(0o755)).unwrap();
                for sibling in ["daemon-bundle.mjs", "index.js"] {
                    fs::write(cli.with_file_name(sibling), "synthetic sibling\n").unwrap();
                }
            }
            fixture
        }

        fn cli(&self, mount: &str) -> PathBuf {
            self.0.join(mount).join(PC_BUNDLE_CLI)
        }

        fn runs(&self, pid: &str, mount: &str, binary: &str, ppid: Option<&str>) {
            let path = self.0.join(mount).join(binary);
            if !path.exists() {
                fs::write(&path, "synthetic executable\n").unwrap();
                fs::set_permissions(&path, fs::Permissions::from_mode(0o555)).unwrap();
            }
            let process = self.0.join("proc").join(pid);
            directory(&process);
            symlink(path, process.join("exe")).unwrap();
            if let Some(ppid) = ppid {
                let stat = format!("{pid} (synthetic) S {ppid} {pid} {pid} 0 -1 0\n");
                fs::write(process.join("stat"), stat).unwrap();
            }
        }

        fn app(&self, pid: &str, mount: &str, ppid: &str) {
            self.runs(pid, mount, "synthetic-app", Some(ppid));
        }

        fn resolve(&self) -> Result<PathBuf, LocateError> {
            Discovery::pc(self.0.clone(), |m| LauncherMetadata {
                uid: 0,
                mode: m.mode(),
            })
            .with_process_root(self.0.join("proc"))
            .resolve()
        }
    }

    const OLD: &str = ".mount_synthetic_old";
    const NEW: &str = ".mount_synthetic_new";
    const STALE: [&str; 2] = [".mount_synthetic_stale_a", ".mount_synthetic_stale_b"];

    fn mid_update() -> Fixture {
        let f = Fixture::new(&[OLD, NEW, STALE[0], STALE[1]]);
        f.app("201", OLD, "1");
        f.app("202", OLD, "201");
        f.app("301", NEW, "201");
        f.app("302", NEW, "301");
        f
    }

    #[test]
    fn a_bridge_launched_through_a_shell_under_the_gui_is_refused() {
        let f = Fixture::new(&[OLD, NEW]);
        f.runs("100", "", "synthetic-shell", Some("1"));
        f.app("201", OLD, "100");
        f.runs("400", "", "synthetic-shell", Some("201"));
        f.app("301", NEW, "201");
        let identity = |pid: &str, parent: &str, start: u64| {
            fs::write(
                f.0.join("proc").join(pid).join("stat"),
                format!(
                    "{pid} (synthetic (app)) S {parent} 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 {start} 0\n"
                ),
            )
            .unwrap();
        };
        identity("201", "100", 100);
        identity("400", "201", 110);
        identity("301", "201", 120);
        let appimage = f.0.join("Synthetic.AppImage");
        fs::write(&appimage, "synthetic AppImage\n").unwrap();
        for (pid, mount) in [("100", OLD), ("301", NEW)] {
            fs::write(
                f.0.join("proc").join(pid).join("environ"),
                format!(
                    "APPDIR={}\0APPIMAGE={}\0",
                    f.0.join(mount).display(),
                    appimage.display()
                ),
            )
            .unwrap();
        }
        assert_eq!(f.resolve(), Ok(f.cli(NEW)), "direct pair baseline");
        identity("301", "400", 120);
        assert_eq!(f.resolve(), Err(LocateError::Ambiguous));
    }

    fn gui_on_old_mount_supervising_bridge_on_new_mount_is_refused() {
        assert_eq!(mid_update().resolve(), Err(LocateError::Ambiguous));
    }

    fn a_bridge_on_each_mount_under_one_gui_is_refused() {
        let f = Fixture::new(&[OLD, NEW]);
        f.runs("201", OLD, "synthetic-gui", Some("1"));
        f.runs("202", OLD, "synthetic-old-bridge", Some("201"));
        f.runs("301", NEW, "synthetic-new-supervisor", Some("201"));
        f.runs("302", NEW, "synthetic-new-bridge", Some("301"));
        assert_eq!(f.resolve(), Err(LocateError::Ambiguous));
    }

    fn a_new_mount_helper_with_the_bridge_on_the_old_mount_never_selects_new() {
        let f = Fixture::new(&[OLD, NEW]);
        f.runs("201", OLD, "synthetic-gui", Some("1"));
        f.runs("202", OLD, "synthetic-old-bridge", Some("201"));
        f.runs("301", NEW, "synthetic-new-helper", Some("201"));
        assert_eq!(f.resolve(), Err(LocateError::Ambiguous));
    }

    fn other_parent_shapes_on_two_or_more_mounts_are_refused() {
        type Shape = fn(&Fixture);
        let shapes: [(&str, Shape); 6] = [
            ("two independent bridges", |f| {
                f.app("201", OLD, "1");
                f.app("301", NEW, "1");
            }),
            ("a second, independent start on NEW", |f| {
                f.app("201", OLD, "1");
                f.app("301", NEW, "201");
                f.app("303", NEW, "1");
            }),
            ("links in both directions", |f| {
                f.app("201", OLD, "1");
                f.app("301", NEW, "201");
                f.app("203", OLD, "301");
            }),
            ("three running mounts", |f| {
                f.app("201", OLD, "1");
                f.app("301", NEW, "201");
                f.app("401", STALE[0], "201");
            }),
            ("a parent cycle beside a valid root", |f| {
                f.app("201", OLD, "1");
                f.app("301", NEW, "201");
                f.app("303", NEW, "304");
                f.app("304", NEW, "303");
            }),
            ("no parent record", |f| {
                f.runs("201", OLD, "synthetic-app", None);
                f.runs("301", NEW, "synthetic-app", None);
            }),
        ];
        for (name, shape) in shapes {
            let f = Fixture::new(&[OLD, NEW, STALE[0]]);
            shape(&f);
            assert_eq!(f.resolve(), Err(LocateError::Ambiguous), "{name}");
        }
    }

    #[test]
    fn multiple_running_mounts_remain_refused_for_all_process_shapes() {
        let cases: [(&str, fn()); 4] = [
            (
                "gui_on_old_mount_supervising_bridge_on_new_mount_is_refused",
                gui_on_old_mount_supervising_bridge_on_new_mount_is_refused,
            ),
            (
                "a_bridge_on_each_mount_under_one_gui_is_refused",
                a_bridge_on_each_mount_under_one_gui_is_refused,
            ),
            (
                "a_new_mount_helper_with_the_bridge_on_the_old_mount_never_selects_new",
                a_new_mount_helper_with_the_bridge_on_the_old_mount_never_selects_new,
            ),
            (
                "other_parent_shapes_on_two_or_more_mounts_are_refused",
                other_parent_shapes_on_two_or_more_mounts_are_refused,
            ),
        ];
        for (name, case) in cases {
            eprintln!("{name}");
            case();
        }
    }

    #[test]
    fn the_refusal_carries_the_mid_update_guidance_and_keeps_its_category() {
        let openwiz_core::source::SourceError::Unavailable { detail } =
            LocateError::Ambiguous.into()
        else {
            panic!("an ambiguous bundle is unavailable");
        };
        assert_eq!(
            detail,
            "CloudRoom not running: room-cli could not be started (ambiguous app bundles). \
             CloudRoom is mid-update (two running app mounts): restart CloudRoom to finish \
             the update, then try again."
        );
        assert_eq!(
            openwiz_core::ops::launch_failure_category(&detail),
            Some("ambiguous bundle")
        );
    }

    #[test]
    fn stale_mounts_beside_one_running_mount_are_ignored() {
        let f = Fixture::new(&[NEW, STALE[0], STALE[1]]);
        f.runs("301", NEW, "synthetic-app", None);
        assert_eq!(f.resolve(), Ok(f.cli(NEW)));
    }
}

#[cfg(test)]
mod shown_tests {
    use super::*;

    #[test]
    fn a_mount_name_cannot_forge_or_style_a_diagnostic_line() {
        let path = Path::new("/tmp/.mount_a\nopenwiz: note: forged\x1b[31m");
        assert_eq!(shown(path), "/tmp/.mount_a?openwiz: note: forged?[31m");
    }
}
