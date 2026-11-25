use std::collections::HashMap;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::Value;

use super::engine::GhostEngine;
use super::protocol::{
    MAX_BODY_BYTES, RefusalCode, RefusalEnvelope, validate_host, validate_origin,
};

const MAX_HEADER_BYTES: usize = 64 * 1024;
const KNOWN_ROUTES: &[&str] = &[
    "pair", "health", "context", "turns", "complete", "draft", "feedback", "bench",
];

pub fn bind_loopback(port: u16) -> io::Result<TcpListener> {
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    TcpListener::bind(addr)
}

pub fn serve(listener: TcpListener, engine: Arc<Mutex<GhostEngine>>) -> io::Result<()> {
    for incoming in listener.incoming() {
        let Ok(stream) = incoming else {
            continue;
        };
        let _ = handle_connection(stream, &engine);
    }
    Ok(())
}

pub fn serve_with_shutdown(
    listener: TcpListener,
    engine: Arc<Mutex<GhostEngine>>,
    shutdown: Arc<AtomicBool>,
) -> io::Result<()> {
    listener.set_nonblocking(true)?;
    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                let _ = stream.set_nonblocking(false);
                let _ = handle_connection(stream, &engine);
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(5));
            }
            Err(_) => break,
        }
    }
    Ok(())
}

struct ParsedHead {
    method: String,
    target: String,
    headers: HashMap<String, String>,
}

fn handle_connection(stream: TcpStream, engine: &Arc<Mutex<GhostEngine>>) -> io::Result<()> {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));

    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;

    let Some(head) = read_head(&mut reader)? else {
        return Ok(());
    };

    // 1. Host check
    let host_ok = head.headers.get("host").is_some_and(|h| validate_host(h));
    if !host_ok {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::HostNotAllowed,
            "Host header must be 127.0.0.1 or localhost.",
        )
        .into_response();
        return write_json_response(&mut writer, status, &body, None);
    }

    // 2. Origin check (and CORS preflight)
    let origin = head.headers.get("origin").map(String::as_str);
    if head.method == "OPTIONS" {
        match origin {
            Some(o) if validate_origin(o) => {
                return write_cors_preflight(&mut writer, o);
            }
            _ => {
                let (status, body) = RefusalEnvelope::new(
                    RefusalCode::OriginNotAllowed,
                    "Origin is missing or not on the ghost.v1 allowlist.",
                )
                .into_response();
                return write_json_response(&mut writer, status, &body, None);
            }
        }
    }

    let allowed_origin = match origin {
        Some(o) if validate_origin(o) => Some(o),
        Some(_) => {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::OriginNotAllowed,
                "Origin is not on the ghost.v1 allowlist.",
            )
            .into_response();
            return write_json_response(&mut writer, status, &body, None);
        }
        None => None,
    };

    // 3. Pairing token check (required on every HTTP route except POST /ghost/v1/pair)
    let is_pair_route = head.method == "POST" && head.target == "/ghost/v1/pair";
    if !is_pair_route {
        let bearer = head
            .headers
            .get("authorization")
            .and_then(|v| v.strip_prefix("Bearer "))
            .filter(|t| !t.is_empty());
        let Some(token) = bearer else {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::MissingToken,
                "Missing or non-Bearer Authorization header.",
            )
            .into_response();
            return write_json_response(&mut writer, status, &body, allowed_origin);
        };
        let valid = {
            let mut guard = engine.lock().unwrap_or_else(|e| e.into_inner());
            guard.pairing_mut().verify_token(token)
        };
        if !valid {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::InvalidToken,
                "Pairing token is unknown or revoked.",
            )
            .into_response();
            return write_json_response(&mut writer, status, &body, allowed_origin);
        }
    }

    // 4. Method, route, and body
    if head.method != "POST" {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::MethodNotAllowed,
            "Only POST (and OPTIONS for CORS preflight) are allowed.",
        )
        .into_response();
        return write_json_response(&mut writer, status, &body, allowed_origin);
    }

    let route = head
        .target
        .strip_prefix("/ghost/v1/")
        .filter(|r| KNOWN_ROUTES.contains(r));
    let Some(route) = route else {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::UnknownRoute,
            format!("Unknown ghost.v1 route {:?}.", head.target),
        )
        .into_response();
        return write_json_response(&mut writer, status, &body, allowed_origin);
    };

    let content_length = match head.headers.get("content-length") {
        None => 0usize,
        Some(raw) => match raw.trim().parse::<usize>() {
            Ok(n) => n,
            Err(_) => {
                let (status, body) = RefusalEnvelope::new(
                    RefusalCode::InvalidRequest,
                    "Invalid Content-Length header.",
                )
                .into_response();
                return write_json_response(&mut writer, status, &body, allowed_origin);
            }
        },
    };
    if content_length > MAX_BODY_BYTES {
        let (status, body) =
            RefusalEnvelope::new(RefusalCode::PayloadTooLarge, "Request body exceeds 1 MiB.")
                .into_response();
        return write_json_response(&mut writer, status, &body, allowed_origin);
    }

    let mut raw_body = vec![0u8; content_length];
    if content_length > 0 && reader.read_exact(&mut raw_body).is_err() {
        let (status, body) =
            RefusalEnvelope::new(RefusalCode::InvalidRequest, "Incomplete request body.")
                .into_response();
        return write_json_response(&mut writer, status, &body, allowed_origin);
    }

    let body_value: Value = match serde_json::from_slice(&raw_body) {
        Ok(v) => v,
        Err(e) => {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::InvalidRequest,
                format!("Invalid JSON body: {e}"),
            )
            .into_response();
            return write_json_response(&mut writer, status, &body, allowed_origin);
        }
    };

    let (status, resp_body) = {
        let mut guard = engine.lock().unwrap_or_else(|e| e.into_inner());
        guard.dispatch(route, body_value, true)
    };
    write_json_response(&mut writer, status, &resp_body, allowed_origin)
}

fn read_head<R: BufRead>(reader: &mut R) -> io::Result<Option<ParsedHead>> {
    let mut first_line = String::new();
    let n = reader.read_line(&mut first_line)?;
    if n == 0 {
        return Ok(None);
    }
    let mut total = n;
    let mut parts = first_line.trim_end_matches(['\r', '\n']).split_whitespace();
    let Some(method) = parts.next().map(str::to_owned) else {
        return Ok(None);
    };
    let Some(target) = parts.next().map(str::to_owned) else {
        return Ok(None);
    };

    let mut headers = HashMap::new();
    loop {
        let mut line = String::new();
        let bytes = reader.read_line(&mut line)?;
        if bytes == 0 {
            break;
        }
        total += bytes;
        if total > MAX_HEADER_BYTES {
            return Ok(None);
        }
        let trimmed = line.trim_end_matches(['\r', '\n']);
        if trimmed.is_empty() {
            break;
        }
        if let Some((name, value)) = trimmed.split_once(':') {
            headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_owned());
        }
    }

    Ok(Some(ParsedHead {
        method,
        target,
        headers,
    }))
}

fn write_cors_preflight(writer: &mut TcpStream, origin: &str) -> io::Result<()> {
    let response = format!(
        "HTTP/1.1 204 No Content\r\n\
         Access-Control-Allow-Origin: {origin}\r\n\
         Access-Control-Allow-Methods: POST, OPTIONS\r\n\
         Access-Control-Allow-Headers: Authorization, Content-Type\r\n\
         Access-Control-Allow-Private-Network: true\r\n\
         Vary: Origin\r\n\
         Content-Length: 0\r\n\
         Connection: close\r\n\
         \r\n"
    );
    writer.write_all(response.as_bytes())?;
    writer.flush()
}

fn write_json_response(
    writer: &mut TcpStream,
    status: u16,
    body: &Value,
    allowed_origin: Option<&str>,
) -> io::Result<()> {
    let payload = serde_json::to_vec(body).map_err(io::Error::other)?;
    let reason = reason_phrase(status);
    let cors = match allowed_origin {
        Some(origin) => format!("Access-Control-Allow-Origin: {origin}\r\nVary: Origin\r\n"),
        None => String::new(),
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\n\
         Content-Type: application/json\r\n\
         {cors}Content-Length: {}\r\n\
         Connection: close\r\n\
         \r\n",
        payload.len()
    );
    writer.write_all(head.as_bytes())?;
    writer.write_all(&payload)?;
    writer.flush()
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        501 => "Not Implemented",
        503 => "Service Unavailable",
        _ => "Error",
    }
}
