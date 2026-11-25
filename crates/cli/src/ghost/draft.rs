use std::io::{BufRead, Write};

/// Stub. GS5's draft tier is not built yet; every stdio line is `not_implemented`.
pub fn serve(
    _settings: &[u8],
    _pack: &[u8],
    mut input: impl BufRead,
    mut output: impl Write,
) -> std::io::Result<()> {
    let mut line = String::new();
    while input.read_line(&mut line)? > 0 {
        let id = json_id(&line).unwrap_or("null".to_owned());
        writeln!(
            output,
            r#"{{"id":{id},"status":501,"body":{{"refusal":{{"code":"not_implemented","message":"Draft is not built yet."}}}}}}"#
        )?;
        output.flush()?;
        line.clear();
    }
    Ok(())
}

fn json_id(line: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let id = value.get("id")?.as_str()?;
    serde_json::to_string(id).ok()
}
