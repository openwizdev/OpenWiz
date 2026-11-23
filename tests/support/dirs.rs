use std::fs::DirBuilder;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;

pub fn private_dir(dir: impl AsRef<Path>) -> io::Result<()> {
    DirBuilder::new().mode(0o700).create(dir)
}

pub fn private_dir_all(dir: impl AsRef<Path>) -> io::Result<()> {
    DirBuilder::new().recursive(true).mode(0o700).create(dir)
}
