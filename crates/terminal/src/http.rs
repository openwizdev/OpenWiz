//! The thin loopback HTTP/1.1 client (terminal contract, "Common bounded
//! reads"): standard-library TCP to `127.0.0.1:<port>` only, one request per
//! connection with `Connection: close`, no redirects, proxy, compression,
//! pipelining or automatic retry. Responses are bounded: a 16 KiB head of at
//! most 64 header lines, a 32 MiB body and one 70-second deadline for the
//! whole connection and request.

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::time::{Duration, Instant};

use crate::config::Settings;

pub const HEAD_MAX_BYTES: usize = 16 * 1024;
pub const HEAD_MAX_LINES: usize = 64;
pub const BODY_MAX_BYTES: usize = 32 * 1024 * 1024;
pub const DEADLINE: Duration = Duration::from_secs(70);

/// A complete HTTP reply. A non-success status keeps its status; it never
/// becomes a success envelope.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reply {
    pub status: u16,
    /// `Retry-After` in seconds, when the server sent a plain number.
    pub retry_after: Option<u64>,
    pub body: Vec<u8>,
}

/// Why no complete reply arrived. `dispatched` is false only when no byte
/// of the request can have reached the server (the connection was never
/// made, or the request was never begun); anything later is unknown.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failure {
    pub dispatched: bool,
    pub reason: String,
}

#[derive(Clone, Debug)]
pub struct Client {
    pub port: u16,
    pub allowed_host: Option<String>,
    /// The whole connection's deadline: [`DEADLINE`] in production.
    pub deadline: Duration,
}

impl Client {
    pub fn new(settings: &Settings) -> Self {
        Self {
            port: settings.port,
            allowed_host: settings.allowed_host.clone(),
            deadline: DEADLINE,
        }
    }

    /// A loopback read: `Host: 127.0.0.1:<port>`.
    pub fn get(&self, path: &str) -> Result<Reply, Failure> {
        let head = format!(
            "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
            self.port
        );
        self.exchange(path, head.into_bytes())
    }

    /// A guarded POST (send, create, or the new-thread preview): only with the
    /// owner's configured host, never inferred, and never retried.
    pub fn post_guarded(&self, path: &str, body: &[u8]) -> Result<Reply, Failure> {
        let Some(host) = self.allowed_host.as_deref() else {
            return Err(Failure {
                dispatched: false,
                reason: "no allowed host is configured, so guarded requests are unavailable".into(),
            });
        };
        let mut request = format!(
            "POST {path} HTTP/1.1\r\nHost: {host}\r\nOrigin: https://{host}\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        )
        .into_bytes();
        request.extend_from_slice(body);
        self.exchange(path, request)
    }

    fn exchange(&self, path: &str, request: Vec<u8>) -> Result<Reply, Failure> {
        let before = |reason: &str| Failure {
            dispatched: false,
            reason: reason.to_owned(),
        };
        if !path.starts_with("/api/v1/") || path.bytes().any(|b| b <= b' ' || b == 0x7f) {
            return Err(before("the request path is not an API path"));
        }
        let start = Instant::now();
        let address = SocketAddr::from((Ipv4Addr::LOCALHOST, self.port));
        let mut stream = TcpStream::connect_timeout(&address, self.deadline).map_err(|e| {
            before(&format!(
                "the server at 127.0.0.1:{} is unavailable ({})",
                self.port,
                e.kind()
            ))
        })?;
        let after = |reason: String| Failure {
            dispatched: true,
            reason,
        };
        let remaining = |start: Instant| -> Result<Duration, Failure> {
            self.deadline
                .checked_sub(start.elapsed())
                .filter(|d| !d.is_zero())
                .ok_or_else(|| after("no complete answer within the deadline".into()))
        };
        stream
            .set_write_timeout(Some(remaining(start)?))
            .map_err(|e| after(format!("the connection failed ({})", e.kind())))?;
        stream
            .write_all(&request)
            .and_then(|()| stream.flush())
            .map_err(|e| after(format!("the request could not be completed ({})", e.kind())))?;
        let mut received = Vec::new();
        let mut chunk = [0u8; 16 * 1024];
        let head_end = loop {
            if let Some(end) = find(&received, b"\r\n\r\n") {
                break end;
            }
            if received.len() > HEAD_MAX_BYTES {
                return Err(after("the answer's head is too large".into()));
            }
            stream.set_read_timeout(Some(remaining(start)?)).ok();
            match stream.read(&mut chunk) {
                Ok(0) => return Err(after("the answer ended before its head".into())),
                Ok(n) => received.extend_from_slice(&chunk[..n]),
                Err(e) => return Err(after(format!("no complete answer ({})", e.kind()))),
            }
        };
        if head_end + 4 > HEAD_MAX_BYTES {
            return Err(after("the answer's head is too large".into()));
        }
        let head = std::str::from_utf8(&received[..head_end])
            .map_err(|_| after("the answer's head is not text".into()))?;
        let (status, retry_after, length) = parse_head(head).map_err(after)?;
        let mut body = received[head_end + 4..].to_vec();
        loop {
            if body.len() > BODY_MAX_BYTES {
                return Err(after("the answer is too large".into()));
            }
            if let Some(length) = length
                && body.len() >= length
            {
                break;
            }
            stream.set_read_timeout(Some(remaining(start)?)).ok();
            match stream.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => body.extend_from_slice(&chunk[..n]),
                Err(e) => return Err(after(format!("no complete answer ({})", e.kind()))),
            }
        }
        if let Some(length) = length
            && body.len() != length
        {
            return Err(after("the answer's body is truncated or too long".into()));
        }
        Ok(Reply {
            status,
            retry_after,
            body,
        })
    }
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

type Head = (u16, Option<u64>, Option<usize>);

fn parse_head(head: &str) -> Result<Head, String> {
    let mut lines = head.split("\r\n");
    let status_line = lines.next().unwrap_or_default();
    let mut parts = status_line.splitn(3, ' ');
    let version = parts.next().unwrap_or_default();
    let code = parts.next().unwrap_or_default();
    if !matches!(version, "HTTP/1.1" | "HTTP/1.0")
        || code.len() != 3
        || !code.bytes().all(|b| b.is_ascii_digit())
    {
        return Err("the answer is not HTTP/1.x".into());
    }
    let status: u16 = code
        .parse()
        .map_err(|_| "the answer's status is malformed")?;
    let mut retry_after = None;
    let mut length = None;
    let mut count = 0;
    for line in lines {
        count += 1;
        if count > HEAD_MAX_LINES {
            return Err("the answer has too many header lines".into());
        }
        let (name, value) = line
            .split_once(':')
            .ok_or("the answer has a malformed header line")?;
        let value = value.trim();
        if name.eq_ignore_ascii_case("content-length") {
            if length.is_some() || value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
                return Err("the answer's Content-Length is malformed or repeated".into());
            }
            let n: usize = value
                .parse()
                .map_err(|_| "the answer's Content-Length is malformed")?;
            if n > BODY_MAX_BYTES {
                return Err("the answer is too large".into());
            }
            length = Some(n);
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err("the answer uses a transfer encoding".into());
        } else if name.eq_ignore_ascii_case("content-encoding") {
            return Err("the answer is compressed".into());
        } else if name.eq_ignore_ascii_case("retry-after") {
            retry_after = value.parse().ok();
        }
    }
    if (300..400).contains(&status) {
        return Err("the answer is a redirect, which is never followed".into());
    }
    Ok((status, retry_after, length))
}

/// The `{"error": {"kind", "message"}}` body's safe reason, if it has one.
pub fn error_reason(reply: &Reply) -> String {
    let parsed = crate::json::parse(&reply.body).ok();
    let error = parsed.as_ref().and_then(|v| v.get("error"));
    let kind = error.and_then(|e| e.get("kind")).and_then(|k| k.as_str());
    let message = error
        .and_then(|e| e.get("message"))
        .and_then(|m| m.as_str());
    match (kind, message) {
        (Some(kind), Some(message)) => format!("HTTP {} {kind}: {message}", reply.status),
        (Some(kind), None) => format!("HTTP {} {kind}", reply.status),
        _ => format!("HTTP {}", reply.status),
    }
}
