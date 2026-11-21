use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub fn place(src: &Path, dst: &Path) {
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    let out = std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(std::process::Stdio::null())
        .output()
        .expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}

pub fn place_script(dst: &Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
