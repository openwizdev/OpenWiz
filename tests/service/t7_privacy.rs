use super::*;

fn assert_private_files(f: &Fixture, key: &[u8]) {
    fn scan(root: &Path, dir: &Path, key: &[u8]) {
        for entry in fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                scan(root, &path, key);
                continue;
            }
            // Only the recording fake deliberately saves the synthetic child
            // credential in this one transcript. The App must write none.
            if path == root.join("calls.log") {
                continue;
            }
            let bytes = fs::read(&path).unwrap();
            assert!(
                !bytes.windows(TOKEN.len()).any(|w| w == TOKEN.as_bytes()),
                "installation token persisted outside the recording fake"
            );
            if path != root.join("service/app/private-key.pem") {
                assert!(
                    !bytes.windows(key.len()).any(|w| w == key),
                    "private key copied outside its one state file"
                );
            }
        }
    }
    scan(&f.root, &f.root, key);
}

#[test]
fn signing_and_exchange_failures_withhold_private_material_and_persist_no_credentials() {
    let f = Fixture::new();
    let client = f.client();
    let key = fs::read(f.root.join("service/app/private-key.pem")).unwrap();
    client.execute(&call(), soon()).unwrap();
    assert_private_files(&f, &key);

    // Plant the complete synthetic key in a hostile endpoint reply.
    let mut reply: Value = serde_json::from_str(&f.exchange.response.lock().unwrap()).unwrap();
    reply["token"] = json!(std::str::from_utf8(&key).unwrap());
    *f.exchange.response.lock().unwrap() = reply.to_string();
    let error = f.client().execute(&call(), soon()).unwrap_err();
    assert_eq!(
        format!("{error} {error:?}"),
        "GitHub App request refused (details withheld) Error"
    );
    assert_eq!(f.gh_calls().len(), 1);
    assert_eq!(f.exchange.calls.lock().unwrap().len(), 2);
    assert_private_files(&f, &key);

    // A real OpenSSL failure precedes both token transport and gh dispatch.
    let signing = f.client();
    private_file(
        &f.root.join("service/app/private-key.pem"),
        b"synthetic-invalid-private-key-material",
        0o600,
    );
    let error = signing.execute(&call(), soon()).unwrap_err();
    assert_eq!(
        format!("{error} {error:?}"),
        "GitHub App request refused (details withheld) Error"
    );
    assert_eq!(f.exchange.calls.lock().unwrap().len(), 2);
    assert_eq!(f.gh_calls().len(), 1);
    assert_private_files(&f, &key);
}

fn openssl(command: &mut Command, input: &[u8]) -> std::process::Output {
    use std::process::Stdio;
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(input).unwrap();
    child.wait_with_output().unwrap()
}

pub(super) fn verify_signature(f: &Fixture, jwt: &str) {
    let parts: Vec<_> = jwt.split('.').collect();
    assert_eq!(parts.len(), 3);
    let decode = |part: &str| {
        let mut base64 = part.replace('-', "+").replace('_', "/");
        while !base64.len().is_multiple_of(4) {
            base64.push('=');
        }
        let out = openssl(
            Command::new("/usr/bin/openssl").args(["base64", "-d", "-A"]),
            base64.as_bytes(),
        );
        assert!(out.status.success(), "independent base64 decode");
        out.stdout
    };
    assert_eq!(
        serde_json::from_slice::<Value>(&decode(parts[0])).unwrap(),
        json!({"alg":"RS256","typ":"JWT"})
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&decode(parts[1])).unwrap(),
        json!({"iss":"1001","iat":1893455940_u64,"exp":1893456540_u64})
    );
    let public = Command::new("/usr/bin/openssl")
        .args(["pkey", "-in"])
        .arg(f.root.join("service/app/private-key.pem"))
        .arg("-pubout")
        .output()
        .unwrap();
    assert!(public.status.success());
    private_file(&f.root.join("public.pem"), public.stdout, 0o600);
    private_file(&f.root.join("signature"), decode(parts[2]), 0o600);
    let message = format!("{}.{}", parts[0], parts[1]);
    let verify = |input: &[u8]| {
        openssl(
            Command::new("/usr/bin/openssl")
                .args(["dgst", "-sha256", "-verify"])
                .arg(f.root.join("public.pem"))
                .arg("-signature")
                .arg(f.root.join("signature")),
            input,
        )
        .status
        .success()
    };
    assert!(verify(message.as_bytes()), "independent JWT verification");
    assert!(
        !verify(format!("{message}x").as_bytes()),
        "tampered JWT must fail"
    );
}

#[test]
fn key_bytes_stay_out_of_process_arguments_errors_and_logs_and_writes_are_not_retried() {
    use std::{
        io::{BufRead, BufReader},
        os::unix::net::UnixListener,
    };
    let f = Fixture::new();
    let client = f.client();
    private_file(&f.root.join("hold"), b"synthetic", 0o600);
    let listener = UnixListener::bind(f.root.join("gate.sock")).unwrap();
    listener.set_nonblocking(true).unwrap();
    let worker = thread::spawn(move || client.execute(&call(), soon()));
    let until = soon();
    let (mut gate, _) = loop {
        match listener.accept() {
            Ok(v) => break v,
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < until => {
                thread::yield_now()
            }
            Err(_) => panic!("fake gh did not reach the explicit gate"),
        }
    };
    gate.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let mut pid = String::new();
    BufReader::new(&gate).read_line(&mut pid).unwrap();
    let argv = fs::read(format!("/proc/{}/cmdline", pid.trim())).unwrap();
    let key = fs::read(f.root.join("service/app/private-key.pem")).unwrap();
    assert!(!argv.windows(key.len()).any(|w| w == key));
    assert!(!argv.windows(TOKEN.len()).any(|w| w == TOKEN.as_bytes()));
    gate.write_all(b"x").unwrap();
    let output = worker.join().unwrap().unwrap();
    fs::remove_file(f.root.join("hold")).unwrap();
    private_file(&f.root.join("failure"), b"synthetic", 0o600);
    let write = openwiz_adapter_github::writes::Write::IssueComment {
        issue: openwiz_core::fleet::model::Number::new(901).unwrap(),
        body: openwiz_adapter_github::writes::Body::parse("synthetic health record").unwrap(),
    };
    let argv = write.argv();
    let call = Invocation::new(&argv.iter().map(String::as_str).collect::<Vec<_>>()).unwrap();
    let result = f.client().execute(&call, soon());
    assert!(result.is_err());
    let errors = format!(
        "{} {:?}",
        result.as_ref().unwrap_err(),
        result.as_ref().unwrap_err()
    )
    .into_bytes();
    let logs = fs::read(f.root.join("calls.log")).unwrap();
    let marker = std::str::from_utf8(&key)
        .unwrap()
        .lines()
        .nth(1)
        .unwrap()
        .as_bytes();
    for bytes in [&output, &errors, &logs] {
        assert!(!bytes.windows(marker.len()).any(|w| w == marker));
        assert!(!bytes.windows(key.len()).any(|w| w == key));
    }
    assert_eq!(
        f.gh_calls().len(),
        2,
        "one read and one failed write, no uncertain-write retry or read-back"
    );
    assert_eq!(
        f.exchange.calls.lock().unwrap().len(),
        2,
        "one mint per separately constructed client"
    );
}

#[test]
fn personal_credentials_probe() {
    if std::env::var_os("OPENWIZ_T7_PROBE").is_none() {
        return;
    }
    let f = Fixture::new();
    let app = f.client();
    app.execute(&call(), soon()).unwrap();
    openwiz_adapter_github::process::run(&f.root.join("gh"), &call(), soon()).unwrap();
    let calls = f.gh_calls();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls[0]["token"], TOKEN);
    assert_eq!(calls[0]["debug"], Value::Null);
    assert_eq!(calls[1]["token"], "synthetic-personal-token");
    assert_eq!(calls[1]["debug"], "api");
    assert_eq!(calls[1]["repo"], "synthetic-personal/repo");
    assert_eq!(
        std::env::var("GH_TOKEN").unwrap(),
        "synthetic-personal-token"
    );
}
#[test]
fn app_credentials_are_per_child_and_the_personal_runner_is_unchanged() {
    let out = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "privacy::personal_credentials_probe",
            "--nocapture",
        ])
        .env_clear()
        .env("OPENWIZ_T7_PROBE", "1")
        .env("GH_TOKEN", "synthetic-personal-token")
        .env("GH_DEBUG", "api")
        .env("GH_REPO", "synthetic-personal/repo")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
