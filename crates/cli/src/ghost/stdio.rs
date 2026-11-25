use std::io::{self, BufRead, Write};

use serde_json::Value;

use super::engine::GhostEngine;
use super::protocol::{MAX_BODY_BYTES, RefusalCode, RefusalEnvelope, StdioResponse};

pub fn run_stdio(
    engine: &mut GhostEngine,
    reader: &mut dyn BufRead,
    writer: &mut dyn Write,
) -> io::Result<()> {
    let mut line = String::new();
    loop {
        line.clear();
        let n = reader.read_line(&mut line)?;
        if n == 0 {
            break;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let response = handle_line(engine, trimmed);
        let serialized = serde_json::to_string(&response).map_err(io::Error::other)?;
        writer.write_all(serialized.as_bytes())?;
        writer.write_all(b"\n")?;
        writer.flush()?;
    }
    Ok(())
}

pub fn handle_line(engine: &mut GhostEngine, line: &str) -> StdioResponse {
    if line.len() > MAX_BODY_BYTES {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::PayloadTooLarge,
            "stdio request line exceeds 1 MiB.",
        )
        .into_response();
        return StdioResponse {
            id: None,
            status,
            body,
        };
    }

    let parsed: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::InvalidRequest,
                format!("invalid JSON line: {e}"),
            )
            .into_response();
            return StdioResponse {
                id: None,
                status,
                body,
            };
        }
    };

    let Some(obj) = parsed.as_object() else {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::InvalidRequest,
            "stdio request must be a JSON object.",
        )
        .into_response();
        return StdioResponse {
            id: None,
            status,
            body,
        };
    };

    let id = obj
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned);

    let Some(id_str) = id.clone() else {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::InvalidRequest,
            "stdio request requires a non-empty string id.",
        )
        .into_response();
        return StdioResponse {
            id: None,
            status,
            body,
        };
    };

    for key in obj.keys() {
        if !matches!(key.as_str(), "id" | "route" | "body") {
            let (status, body) = RefusalEnvelope::new(
                RefusalCode::InvalidRequest,
                format!("unknown stdio request field {key:?}."),
            )
            .into_response();
            return StdioResponse {
                id: Some(id_str),
                status,
                body,
            };
        }
    }

    let Some(route) = obj.get("route").and_then(Value::as_str) else {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::InvalidRequest,
            "stdio request requires a string route.",
        )
        .into_response();
        return StdioResponse {
            id: Some(id_str),
            status,
            body,
        };
    };

    let Some(body_val) = obj.get("body").filter(|v| v.is_object()).cloned() else {
        let (status, body) = RefusalEnvelope::new(
            RefusalCode::InvalidRequest,
            "stdio request requires an object body.",
        )
        .into_response();
        return StdioResponse {
            id: Some(id_str),
            status,
            body,
        };
    };

    let (status, body) = engine.dispatch(route, body_val, false);
    StdioResponse {
        id: Some(id_str),
        status,
        body,
    }
}
