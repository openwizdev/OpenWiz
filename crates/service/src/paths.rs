//! Private-state checks. macOS uses an ephemeral owner probe; never reads a key.
use std::fs;
use std::io::ErrorKind;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

/// Inspect settings without changing them. macOS may briefly create/remove an
/// empty owner probe in private state under Jake's #1102 ruling.
pub fn inspect(root: &Path) -> Result<(), String> {
    openwiz_store::loops::inspect_state(root)
}

fn checked(
    path: &Path,
    label: &str,
    directory: bool,
    required: bool,
    uid: u32,
) -> Result<(), String> {
    let fail = |rule: &str| Err(format!("{label}: {rule}"));
    let meta = match fs::symlink_metadata(path) {
        Ok(meta) => meta,
        Err(e) if !required && e.kind() == ErrorKind::NotFound => return Ok(()),
        Err(_) => return fail("cannot inspect the required path"),
    };
    if meta.file_type().is_symlink() {
        return fail("symlinks are refused");
    }
    if meta.uid() != uid {
        return fail("must be owned by the service's user");
    }
    if meta.mode() & 0o077 != 0 {
        return fail("must not be open to group or others");
    }
    if (directory && !meta.is_dir()) || (!directory && (!meta.is_file() || meta.nlink() != 1)) {
        return fail(if directory {
            "must be a directory"
        } else {
            "must be a regular file"
        });
    }
    Ok(())
}

/// Private singleton metadata is checked before it is opened or replaced.
pub(crate) fn inspect_runtime(root: &Path) -> Result<(), String> {
    use std::os::unix::fs::FileTypeExt;
    let uid = openwiz_store::attachments::effective_uid()?;
    checked(
        &root.join("service/run.lock"),
        "service/run.lock",
        false,
        false,
        uid,
    )?;
    match fs::symlink_metadata(root.join("service/status.sock")) {
        Ok(meta)
            if meta.file_type().is_socket() && meta.uid() == uid && meta.mode() & 0o077 == 0 =>
        {
            Ok(())
        }
        Err(e) if e.kind() == ErrorKind::NotFound => Ok(()),
        _ => Err(
            "service/status.sock: must be a private socket owned by the service's user".to_owned(),
        ),
    }
}
