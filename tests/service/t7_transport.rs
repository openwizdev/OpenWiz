//! Check the production curl config with a local HTTP fixture. Only this test
//! substitutes the URL and TLS protocol; production exposes neither override.
use super::*;
use std::{
    io::{ErrorKind, Read, Write},
    net::TcpListener,
    thread,
    time::Duration,
};

#[test]
fn real_curl_reads_the_fixed_config_and_keeps_bearer_auth_and_json_off_argv() {
    for (status, accepted) in [(201, true), (200, false), (302, false), (403, false)] {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut data = Vec::new();
            loop {
                let mut buf = [0; 1024];
                let n = match socket.read(&mut buf) {
                    Err(error) if error.kind() == ErrorKind::Interrupted => continue,
                    result => result.unwrap(),
                };
                assert!(n > 0);
                data.extend_from_slice(&buf[..n]);
                if let Some(at) = data.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = std::str::from_utf8(&data[..at]).unwrap();
                    let len: usize = headers
                        .lines()
                        .find_map(|l| {
                            l.to_ascii_lowercase()
                                .strip_prefix("content-length: ")
                                .map(str::to_owned)
                        })
                        .unwrap()
                        .parse()
                        .unwrap();
                    if data.len() >= at + 4 + len {
                        break;
                    }
                }
            }
            let reply: &[u8] = if status == 403 {
                b"synthetic-private-exchange-diagnostic"
            } else {
                b"{\"synthetic\":\"ok\"}"
            };
            write!(
                socket,
                "HTTP/1.1 {status} Synthetic\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                reply.len()
            )
            .unwrap();
            socket.write_all(reply).unwrap();
            data
        });
        let config = token_config(
            2002,
            "synthetic.jwt.signature",
            br#"{"repositories":["synthetic-repo"],"permissions":{"metadata":"read"}}"#,
        )
        .unwrap();
        assert!(config.starts_with(
            "url = \"https://api.github.com/app/installations/2002/access_tokens\"\n"
        ));
        let local = config.replacen(
            "https://api.github.com",
            &format!("http://127.0.0.1:{port}"),
            1,
        );
        let child = Command::new(CURL_PROGRAM)
            .args(CURL_ARGS)
            .args(["--proto", "=http"])
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let result = process::app_output(
            child,
            local.into_bytes(),
            Instant::now() + Duration::from_secs(10),
        )
        .map_err(|_| Error)
        .and_then(token_answer);
        assert_eq!(result.is_ok(), accepted, "HTTP {status}");
        if let Err(error) = &result {
            assert_eq!(
                format!("{error} {error:?}"),
                "GitHub App request refused (details withheld) Error"
            );
        }
        if let Ok(body) = result {
            assert_eq!(body, br#"{"synthetic":"ok"}"#);
        }
        let request = server.join().unwrap();
        let at = request.windows(4).position(|w| w == b"\r\n\r\n").unwrap();
        let headers = std::str::from_utf8(&request[..at]).unwrap();
        assert!(headers.starts_with("POST /app/installations/2002/access_tokens HTTP/1.1\r\n"));
        assert!(headers.contains("Authorization: Bearer synthetic.jwt.signature\r\n"));
        assert_eq!(
            serde_json::from_slice::<Value>(&request[at + 4..]).unwrap(),
            json!({"repositories":["synthetic-repo"],"permissions":{"metadata":"read"}})
        );
    }
}
