//! Bundle discovery and the recorded PC launcher markers (#267).
//!
//! PC selection ties kernel process executable metadata to a verified bundle;
//! stale mounts never select themselves. The marker check takes
//! observed ownership, mode and prefix facts; neither function runs a program.
//! The process runner resolves the default launcher anew for each call. Only
//! test entrypoints inject a private root and synthetic ownership in code.
//!
//! BX1 (#2098): two running roots stay refused as ambiguous, except CloudRoom's
//! GUI and its direct child bridge supervisor running from two mounts of one
//! AppImage file with byte-identical launchers; see [`Discovery::locate`].

use std::fs;
use std::io::ErrorKind;
use std::io::{Read, Write};
use std::os::fd::AsFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::{Component, Path, PathBuf};
use std::sync::{Mutex, OnceLock};

use crate::allowlist::{MAC_BUNDLE_CLI, PC_BUNDLE_CLI, PC_BUNDLE_PREFIX, PC_BUNDLE_ROOT};

static DISCOVERY: OnceLock<Discovery> = OnceLock::new();

/// Discovery inputs supplied in code by an entrypoint. Real binaries use
/// fixed system discovery; fixture binaries supply their private filesystem.
pub struct Discovery {
    root: PathBuf,
    metadata: fn(&fs::Metadata) -> LauncherMetadata,
    fixed: bool,
    process_root: PathBuf,
}

impl Discovery {
    /// Fixture filesystem seam for running-process evidence. System discovery
    /// always uses Linux proc metadata, never an environment-selected path.
    pub fn with_process_root(mut self, root: PathBuf) -> Self {
        self.process_root = root;
        self
    }

    pub fn pc(root: PathBuf, metadata: fn(&fs::Metadata) -> LauncherMetadata) -> Self {
        Self {
            root,
            metadata,
            fixed: false,
            process_root: PathBuf::from("/proc"),
        }
    }

    /// A fixed app-bundle launcher (the Mac's location), using the same
    /// marker verification without scanning or consulting PATH.
    pub fn fixed(path: PathBuf, metadata: fn(&fs::Metadata) -> LauncherMetadata) -> Self {
        Self {
            root: path,
            metadata,
            fixed: true,
            process_root: PathBuf::from("/proc"),
        }
    }

    pub fn system() -> Self {
        if cfg!(target_os = "macos") {
            Self::fixed(PathBuf::from(MAC_BUNDLE_CLI), real_metadata)
        } else {
            Self::pc(PathBuf::from(PC_BUNDLE_ROOT), real_metadata)
        }
    }

    /// Finds and verifies the launcher anew. No candidate is executed here.
    pub fn resolve(&self) -> Result<PathBuf, LocateError> {
        self.locate().map(|located| located.launcher)
    }

    /// [`Discovery::resolve`], with how the launcher was chosen, for
    /// diagnostics. On the PC exactly one running root selects itself. Two
    /// are accepted only as CloudRoom's AppImage pair (BX1, #2098): the GUI's
    /// head process directly started the bridge's head process; the GUI's
    /// launcher (the GUI head's parent) and the bridge head each record their
    /// own mount as `APPDIR` and the same canonical `APPIMAGE` regular file;
    /// both roots pass every launcher check; and their launchers are
    /// byte-identical. The launcher then comes from the bridge's mount. Any
    /// other shape of two or more roots is [`LocateError::Ambiguous`].
    pub fn locate(&self) -> Result<Located, LocateError> {
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

    /// The launcher file's own checks: type, siblings, prefix, owner, mode.
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
            // A fixed Mac app is trusted at its installed location, and may
            // be owned by the installing user rather than root. Require its
            // launcher to retain the application's actual owner.
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
        // Only this user's app processes are in scope. A root-owned app
        // executable still runs as its installing user. Selection never reads
        // argv, environment or process names; none of those establishes
        // identity. Only the BX1 pair check reads two environment values,
        // and only to refuse a pair the kernel facts already allow.
        let user = fs::metadata(self.process_root.join("self"))
            .map_err(|_| LocateError::Unreadable)?
            .uid();
        let entries = fs::read_dir(&self.process_root).map_err(|_| LocateError::Unreadable)?;
        let mut roots: Vec<Root> = Vec::new();
        for entry in entries {
            let found = entry
                .map_err(|_| LocateError::Unreadable)
                .and_then(|entry| self.running_root(&entry, user, &mut before_read));
            let (pid, mount, candidate) = match found {
                Ok(Some(found)) => found,
                Ok(None) => continue,
                // Two roots were refused here before BX1; a later fault
                // leaves their pair unverified, so it stays ambiguous.
                Err(_) if roots.len() > 1 => return Err(LocateError::Ambiguous),
                Err(error) => return Err(error),
            };
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
        // One order whatever the scan's: the pair check never depends on it.
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
        // Layout alone never selects a launcher. It only distinguishes an
        // absent bundle from mounted bundles with no verified process match.
        match pc_bundle_candidate(&self.root) {
            Ok(_) | Err(LocateError::Ambiguous) => Err(LocateError::NoRunningApp),
            Err(error) => Err(error),
        }
    }

    /// One process entry: its pid and its verified root's launcher, if it
    /// runs an app directly in a mount with the recorded layout.
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
            // Exited/zombie and non-dumpable processes supply no readable
            // exe identity. Only a readable, verified app can select a mount.
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
        // The executable's name alone is never identity. It must live
        // directly in a mount containing the recorded CloudRoom layout.
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

    /// BX1 (#2098): CloudRoom's GUI and its bridge supervisor, two mounts of
    /// one AppImage file. `None` refuses the pair; the caller reports it as
    /// ambiguous. Each condition below is required, with no fallback.
    fn appimage_pair(&self, user: u32, roots: [&Root; 2]) -> Option<(PathBuf, Basis)> {
        // Every verified process of both roots, with its recorded parent.
        let mut family = Vec::new();
        for (index, root) in roots.iter().enumerate() {
            for pid in &root.pids {
                let pid: u32 = pid.parse().ok()?;
                family.push((pid, self.parent(pid)?, index));
            }
        }
        let member = |pid: u32| family.iter().find(|(member, ..)| *member == pid);
        // Each root has exactly one head, whose parent is outside that root,
        // and every other process of the root descends from it within it.
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
        // The bridge head's direct parent is the GUI head, one way round only.
        let parent_of = |index: usize| member(heads[index]).map(|&(_, parent, _)| parent);
        let bridge = match (parent_of(0)? == heads[1], parent_of(1)? == heads[0]) {
            (false, true) => 1,
            (true, false) => 0,
            _ => return None,
        };
        let gui = 1 - bridge;
        // The GUI's own environment is not readable as a record on the PC;
        // its launcher, the GUI head's direct parent, carries it. That
        // launcher runs as this user and from neither root. (The scan has
        // already refused a pid entry that is not a directory.)
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
        // Both roots pass every launcher check, with byte-identical launchers.
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

    /// The parent pid from `<pid>/stat`: `<pid> (<comm>) <state> <ppid> ...`,
    /// where the comm may itself hold spaces and parentheses.
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

    /// One process's AppImage record: exactly one `APPDIR`, naming `mount`
    /// exactly, and exactly one `APPIMAGE`, a canonical path to a
    /// regular file. Returns that path with the file's device and inode.
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
        // Canonical means absolute, with no symlink, `.` or `..` component.
        if fs::canonicalize(path).ok()?.as_os_str() != path.as_os_str() {
            return None;
        }
        let file = fs::symlink_metadata(path).ok()?;
        file.is_file()
            .then(|| (path.to_path_buf(), (file.dev(), file.ino())))
    }
}

const STAT_LIMIT: u64 = 4096;
const ENVIRON_LIMIT: u64 = 1 << 20;
const LAUNCHER_LIMIT: u64 = 16 << 20;

/// A whole file of at most `limit` bytes; a longer one is refused.
fn read_bounded(path: &Path, limit: u64) -> Option<Vec<u8>> {
    let mut bytes = Vec::new();
    fs::File::open(path)
        .ok()?
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .ok()?;
    (bytes.len() as u64 <= limit).then_some(bytes)
}

/// One distinct running root: its mount, its launcher and its processes.
struct Root {
    mount: PathBuf,
    launcher: PathBuf,
    pids: Vec<String>,
}

/// How discovery chose the launcher, for diagnostics (#2098).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Basis {
    /// The fixed app-bundle location (the Mac).
    Fixed,
    /// The one running app mount.
    OneRoot,
    /// CloudRoom's GUI and its direct child bridge supervisor, two mounts of
    /// one AppImage file with byte-identical launchers. The launcher comes
    /// from the bridge's mount.
    AppImagePair { gui: PathBuf, bridge: PathBuf },
}

impl Basis {
    /// One line naming the choice, for an owner reading diagnostics.
    pub fn describe(&self) -> String {
        match self {
            Self::Fixed => "room-cli from the fixed app bundle".to_owned(),
            Self::OneRoot => "room-cli from the one running app mount".to_owned(),
            Self::AppImagePair { gui, bridge } => format!(
                "room-cli from the bridge's mount {} (paired with the GUI's mount {}: \
                 one AppImage file, identical room-cli)",
                shown(bridge),
                shown(gui)
            ),
        }
    }
}

/// A path for one diagnostic line: every control character (a newline, an
/// escape sequence) becomes `?`, so a mount name cannot forge or style output.
fn shown(path: &Path) -> String {
    path.display()
        .to_string()
        .chars()
        .map(|c| if c.is_control() { '?' } else { c })
        .collect()
}

/// A verified launcher and how it was chosen. Nothing here was executed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Located {
    pub launcher: PathBuf,
    pub basis: Basis,
}

/// No symlinked root, mount or directory component may redirect verification.
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

/// Entry-point injection, once per process. Production passes `system()`;
/// fixture entrypoints supply a private root and synthetic ownership in code.
/// No environment variable or build feature selects a different discovery.
pub fn install(discovery: Discovery) -> Result<(), LocateError> {
    DISCOVERY
        .set(discovery)
        .map_err(|_| LocateError::UnexpectedFile)
}

/// Resolves the legacy default program name at each call, never via PATH.
/// Explicit absolute programs remain the adapter's in-process injection seam.
pub fn program(program: &Path) -> Result<PathBuf, openwiz_core::source::SourceError> {
    if program == Path::new(crate::PROGRAM) {
        let located = DISCOVERY.get_or_init(Discovery::system).locate()?;
        report(&located.basis);
        Ok(located.launcher)
    } else if program.is_absolute() {
        Ok(program.to_path_buf())
    } else {
        Err(LocateError::UnexpectedFile.into())
    }
}

/// The owner-visible record of an AppImage-pair choice (#2098): one
/// sanitized stderr line beside any command output (the CLI contract's
/// stderr diagnostics), written when the pair is chosen and again only after
/// the choice changes, however many `room-cli` calls a process makes.
///
/// It is written through its own duplicate of file descriptor 2, never
/// `eprintln!`: a caller may hold the process's stderr lock for a whole
/// command while another thread resolves the launcher (`openwiz fleet`),
/// and a write error (a full disk, a closed pipe) must not abort the
/// command. A failed write loses only this note.
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
            LocateError::NotRunning => "no bundled launcher",
            LocateError::NoRunningApp => "no running app identified",
            LocateError::Ambiguous => "ambiguous app bundles",
            LocateError::UnexpectedFile => "unexpected bundle file",
            LocateError::Unreadable => "unreadable app bundle",
        };
        let detail = format!("CloudRoom not running: room-cli could not be started ({reason})");
        // Two or more running mounts: most often one app mid-update (#1336).
        // `openwiz_core::ops::launch_failure_category` matches this exact text.
        let detail = if error == LocateError::Ambiguous {
            format!(
                "{detail}. CloudRoom is mid-update (two running app mounts): \
                 restart CloudRoom to finish the update, then try again."
            )
        } else {
            detail
        };
        Self::Unavailable { detail }
    }
}

/// Why bundle discovery could not supply a verified launcher.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocateError {
    NotRunning,
    NoRunningApp,
    Ambiguous,
    UnexpectedFile,
    Unreadable,
}

/// Observed Unix ownership and mode of the launcher's regular file.
/// Filesystem adapters supply real metadata; fixtures use synthetic facts.
#[derive(Clone, Copy, Debug)]
pub struct LauncherMetadata {
    pub uid: u32,
    pub mode: u32,
}

/// Checks the observed PC launcher's ownership, permissions and two-line
/// prefix without running it. File type and sibling checks are separate.
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

/// Selects a candidate under the supplied bundle root (a private fixture
/// directory in tests). The result still requires identity verification.
/// This function neither searches PATH nor executes a candidate.
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

/// Inspect each component without following symlinks. The shared /tmp prefix
/// also contains unrelated apps and files: non-directory mount entries and
/// paths this user cannot search supply no executable candidate. Wrong types
/// inside a searchable bundle, and every other error, still fail closed.
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

// #1036 red run (2026-11-05), before the NotFound handling fix:
// cargo test -p openwiz-adapter-cloudroom --lib process_exit_tests
// Exit 101: 2 passed; 4 failed. vanished_{target,exe_before_metadata,
// exe_before_final_link}: Err(Unreadable), expected Err(NoRunningApp).
// vanished_mount: Err(NotRunning), expected Ok(the synthetic survivor).
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

    // Synthetic proc/mount relationships only; no real process is inspected.
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

    // The named cases and assertions stay intact; this table owns their shared contract.
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

// #1336: two running mounts stay refused, mid-update included. On the PC the
// GUI, its helpers and the bridge all run the same app binary (the bridge is
// started with the GUI's own executable), so neither the executable nor the
// parent chain establishes which process is the bridge (#1339 R1). Synthetic
// proc/mount relationships only; no real process is inspected. Each `stat`
// line records a parent only to show that parentage alone selects nothing:
// BX1's pair (#2098) also needs both AppImage records, which none of these
// fixtures has (its proofs are in `tests/service/t2_bundle_pair.rs`).
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
        /// Every mount gets the full recorded layout and a verified launcher.
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

        /// A process running `binary` directly in `mount`, with its parent
        /// recorded in `stat`, or no `stat` at all.
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

        /// A process running the mount's one app binary, as on the PC.
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

    /// The PC's shape: the GUI on OLD launched the bridge supervisor on NEW.
    fn mid_update() -> Fixture {
        let f = Fixture::new(&[OLD, NEW, STALE[0], STALE[1]]);
        f.app("201", OLD, "1"); // the GUI
        f.app("202", OLD, "201"); // a GUI helper on its own mount
        f.app("301", NEW, "201"); // the bridge supervisor, launched by the GUI
        f.app("302", NEW, "301"); // the bridge, the supervisor's child
        f
    }

    fn gui_on_old_mount_supervising_bridge_on_new_mount_is_refused() {
        assert_eq!(mid_update().resolve(), Err(LocateError::Ambiguous));
    }

    // R1 (#1339 review): each role runs its own synthetic binary; parentage
    // would pick NEW in both, though a bridge runs on OLD.
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

    // The named cases and assertions stay intact; this table owns their shared contract.
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

    // The refusal tells the owner what to do, and core still recognises it
    // as the "ambiguous bundle" category; the two strings change together.
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
        f.runs("301", NEW, "synthetic-app", None); // one mount needs no parent record
        assert_eq!(f.resolve(), Ok(f.cli(NEW)));
    }
}
