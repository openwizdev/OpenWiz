//! Source-free machine discovery. The embedded catalogue describes shipped forms;
//! its process proof and independent literal matrix guard completeness.

/// One compact JSON document, followed by a newline, without I/O or state access.
pub fn render() -> String {
    let catalogue: serde_json::Value = serde_json::from_str(include_str!("agent-catalogue.json"))
        .expect("the embedded CLI catalogue is valid JSON");
    let mut text = serde_json::to_string(&catalogue).expect("the catalogue serializes");
    text.push('\n');
    text
}
