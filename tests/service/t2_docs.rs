//! R3: the documented synthetic-server command must serve the recording fake.
//! Red run (2026-11-01): selecting this proof exited 101 with
//! "synthetic procedure must build the fixture server" before launching
//! anything. The old recipe selected the production binary with PATH.
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn t2_documented_synthetic_server_uses_the_fixture_and_synthetic_inventory() {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let doc = fs::read_to_string(repo.join("docs/web-access.md")).unwrap();
    let section = doc.split("For the first checks,").nth(1).unwrap();
    let recipe = section
        .split("```sh\n")
        .nth(1)
        .unwrap()
        .split("```")
        .next()
        .unwrap();
    let mut commands = recipe
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty());
    assert_eq!(
        commands.next(),
        Some("cargo build -p openwiz-tests --example openwiz-server --bin fake-room-cli"),
        "synthetic procedure must build the fixture server"
    );
    let replay = commands.collect::<Vec<_>>().join("\n");
    let launch = recipe
        .lines()
        .map(str::trim)
        .find(|line| line.starts_with("OPENWIZ_FIXTURE_PROGRAM="))
        .expect("explicit synthetic program injection");
    assert!(launch.contains("\"<repo>/target/debug/examples/openwiz-server\""));
    assert!(
        !recipe.contains("PATH="),
        "PATH is not the fake-program seam"
    );

    super::process::fixture_binary("openwiz-server");
    assert!(Path::new(env!("CARGO_BIN_EXE_fake-room-cli")).is_file());
    let f = super::Fixture::new();
    let scratch = f.0.join("synthetic scratch with spaces");
    // exec changes only process ownership for cleanup; arguments and the
    // documented environment assignment run through a real POSIX shell.
    let launch = replay
        .replacen(
            "\"<repo>/target/debug/examples/openwiz-server\"",
            "exec \"<repo>/target/debug/examples/openwiz-server\"",
            1,
        )
        .replace("<repo>", repo.to_str().unwrap())
        .replace("<scratch-dir>", scratch.to_str().unwrap())
        .replace("<port>", "0")
        .replace("<openwiz-hostname>", "synthetic.example.invalid")
        .replace("<web-dir>", repo.join("apps/web/out").to_str().unwrap());
    struct Server(Child);
    impl Drop for Server {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let mut server = Server(
        Command::new("/bin/sh")
            .args(["-c", &launch])
            .current_dir(repo)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let stderr = server.0.stderr.take().unwrap();
    let (tx, rx) = mpsc::channel();
    let reader = std::thread::spawn(move || {
        let mut stderr = BufReader::new(stderr);
        let mut first = String::new();
        stderr.read_line(&mut first).unwrap();
        tx.send(first).unwrap();
        let mut rest = String::new();
        stderr.read_to_string(&mut rest).unwrap();
    });
    let first = rx.recv_timeout(Duration::from_secs(10)).unwrap();
    let address: SocketAddr = first
        .trim()
        .strip_prefix("openwiz-server: listening on http://")
        .and_then(|rest| rest.split(' ').next())
        .unwrap_or_else(|| panic!("{first}"))
        .parse()
        .unwrap();
    let mut stream = TcpStream::connect(address).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .unwrap();
    write!(stream, "GET /api/v1/inventory HTTP/1.1\r\nHost: synthetic.example.invalid\r\nConnection: close\r\n\r\n").unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    let (headers, body) = response.split_once("\r\n\r\n").unwrap();
    assert!(headers.starts_with("HTTP/1.1 200 "), "{response}");
    let inventory: serde_json::Value = serde_json::from_str(body).unwrap();
    let sessions = inventory["data"]["sessions"].as_array().unwrap();
    let mut ids: Vec<_> = sessions
        .iter()
        .map(|session| session["id"].as_str().unwrap())
        .collect();
    ids.sort();
    assert_eq!(
        ids,
        [
            "thr_syn_0001",
            "thr_syn_0002",
            "thr_syn_0003",
            "thr_syn_0004",
            "thr_syn_0005",
            "thr_syn_0006"
        ]
    );
    assert!(
        sessions
            .iter()
            .all(|s| s["title"]["known"].as_str().unwrap().contains("Synthetic"))
    );
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        fs::metadata(&scratch).unwrap().permissions().mode() & 0o777,
        0o700
    );
    drop(server);
    reader.join().unwrap();
}
