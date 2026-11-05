//! The same Rust test executable supplies fake gh, without Python or Node.
use super::*;
use std::{
    fs::OpenOptions,
    os::unix::{fs::OpenOptionsExt, net::UnixStream},
};

#[test]
fn fixture_gh_process() {
    let Some(root) = std::env::var_os("OPENWIZ_T7_GH_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let request = PathBuf::from(std::env::var_os("OPENWIZ_T7_GH_ARGS").unwrap());
    let bytes = fs::read(&request).unwrap();
    fs::remove_file(request).unwrap();
    assert_eq!(bytes.last(), Some(&0));
    let argv: Vec<_> = bytes[..bytes.len() - 1]
        .split(|b| *b == 0)
        .map(|arg| std::str::from_utf8(arg).unwrap().to_owned())
        .collect();
    let record = json!({"argv":argv,"token":std::env::var("GH_TOKEN").ok(),"repo":std::env::var("GH_REPO").ok(),"host":std::env::var("GH_HOST").ok(),"debug":std::env::var("GH_DEBUG").ok()});
    OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(root.join("calls.log"))
        .unwrap()
        .write_all(format!("{record}\n").as_bytes())
        .unwrap();
    if root.join("hold").exists() {
        let mut gate = UnixStream::connect(root.join("gate.sock")).unwrap();
        writeln!(gate, "{}", std::process::id()).unwrap();
        gate.read_exact(&mut [0]).unwrap();
    }
    // The shell preserves the original output pipe as fd 3 and suppresses
    // libtest's progress lines. Opening our own descriptor needs no unsafe code.
    let mut output = OpenOptions::new()
        .write(true)
        .open("/proc/self/fd/3")
        .unwrap();
    if root.join("failure").exists() {
        let key = fs::read(root.join("service/app/private-key.pem")).unwrap();
        output.write_all(&key).unwrap();
        std::io::stderr().write_all(&key).unwrap();
        std::io::stderr()
            .write_all(b"synthetic-hostile-error")
            .unwrap();
        std::process::exit(9);
    }
    output.write_all(b"{\"synthetic\":\"ok\"}\n").unwrap();
    std::process::exit(0);
}
