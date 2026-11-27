use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::{Value, json};

#[derive(Clone, Debug)]
pub struct Hit {
    pub path: String,
    pub body: String,
    pub finished: bool,
}

pub struct Running {
    pub url: String,
    pub hits: Arc<Mutex<Vec<Hit>>>,
    stop: Arc<AtomicBool>,
    port: u16,
}

pub fn start(delay_ms: u64, content: &str, prob: f64, stopped_limit: bool) -> Running {
    let listener =
        TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], 0))).expect("bind fake model");
    let port = listener.local_addr().expect("local addr").port();
    let hits = Arc::new(Mutex::new(Vec::new()));
    let stop = Arc::new(AtomicBool::new(false));
    let script = Arc::new(Script {
        delay_ms,
        content: content.to_owned(),
        prob,
        stopped_limit,
    });
    let flag = Arc::clone(&stop);
    let log = Arc::clone(&hits);
    thread::spawn(move || accept_loop(listener, flag, log, script));
    Running {
        url: format!("http://127.0.0.1:{port}"),
        hits,
        stop,
        port,
    }
}

struct Script {
    delay_ms: u64,
    content: String,
    prob: f64,
    stopped_limit: bool,
}

impl Drop for Running {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        let _ = TcpStream::connect_timeout(
            &SocketAddr::from(([127, 0, 0, 1], self.port)),
            Duration::from_millis(50),
        );
    }
}

fn accept_loop(
    listener: TcpListener,
    stop: Arc<AtomicBool>,
    hits: Arc<Mutex<Vec<Hit>>>,
    script: Arc<Script>,
) {
    while !stop.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) if !stop.load(Ordering::Relaxed) => {
                let hits = Arc::clone(&hits);
                let script = Arc::clone(&script);
                thread::spawn(move || handle(stream, hits, script));
            }
            _ => break,
        }
    }
}

fn handle(mut stream: TcpStream, hits: Arc<Mutex<Vec<Hit>>>, script: Arc<Script>) {
    let _ = stream.set_nodelay(true);
    let Some((path, body)) = read_request(&mut stream) else {
        return;
    };
    let body_text = String::from_utf8_lossy(&body).into_owned();
    let steps = script.delay_ms / 10;
    for _ in 0..steps {
        if !still_open(&mut stream) {
            push(&hits, &path, &body_text, false);
            return;
        }
        thread::sleep(Duration::from_millis(10));
    }
    if !still_open(&mut stream) {
        push(&hits, &path, &body_text, false);
        return;
    }
    push(&hits, &path, &body_text, true);
    let _ = stream.write_all(&response(&path, script.as_ref()));
}

fn push(hits: &Mutex<Vec<Hit>>, path: &str, body: &str, finished: bool) {
    let mut guard = hits.lock().unwrap_or_else(|poison| poison.into_inner());
    guard.push(Hit {
        path: path.to_owned(),
        body: body.to_owned(),
        finished,
    });
}

fn still_open(stream: &mut TcpStream) -> bool {
    if stream.set_nonblocking(true).is_err() {
        return false;
    }
    let mut buf = [0u8; 1];
    let open = match stream.read(&mut buf) {
        Ok(0) => false,
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => true,
        Ok(_) => true,
        Err(_) => false,
    };
    let _ = stream.set_nonblocking(false);
    open
}

fn response(path: &str, script: &Script) -> Vec<u8> {
    let logprob = if script.prob > 0.0 && script.prob.is_finite() {
        script.prob.ln()
    } else {
        -20.0
    };
    let value = if path.contains("generate") {
        json!({
            "response": script.content,
            "done": true,
            "logprobs": [{"token": script.content, "logprob": logprob}],
        })
    } else {
        json!({
            "content": script.content,
            "stopped_limit": script.stopped_limit,
            "completion_probabilities": [{
                "content": script.content,
                "probs": [{"tok_str": script.content, "prob": script.prob, "logprob": logprob}],
            }],
        })
    };
    http_json(&value.to_string())
}

fn http_json(body: &str) -> Vec<u8> {
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
    .into_bytes()
}

fn read_request(stream: &mut TcpStream) -> Option<(String, Vec<u8>)> {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut buf = Vec::new();
    let mut tmp = [0u8; 2048];
    let header_end = loop {
        let n = stream.read(&mut tmp).ok()?;
        if n == 0 {
            return None;
        }
        buf.extend_from_slice(&tmp[..n]);
        if let Some(index) = buf.windows(4).position(|window| window == b"\r\n\r\n") {
            break index;
        }
        if buf.len() > 1024 * 1024 {
            return None;
        }
    };
    let header = String::from_utf8(buf[..header_end].to_vec()).ok()?;
    let path = header.lines().next()?.split_whitespace().nth(1)?.to_owned();
    let length = content_length(&header)?;
    let mut body = buf[header_end + 4..].to_vec();
    while body.len() < length {
        let n = stream.read(&mut tmp).ok()?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&tmp[..n]);
        if body.len() > 1024 * 1024 {
            return None;
        }
    }
    if body.len() < length {
        return None;
    }
    body.truncate(length);
    Some((path, body))
}

fn content_length(header: &str) -> Option<usize> {
    header.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse().ok())
            .flatten()
    })
}

pub fn prompt_of(body: &str) -> Option<String> {
    serde_json::from_str::<Value>(body)
        .ok()?
        .get("prompt")?
        .as_str()
        .map(str::to_owned)
}
