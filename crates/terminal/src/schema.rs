//! The action routes' existing report shapes, checked whole before a body
//! becomes a [`crate::actions::TransportResult::Report`], and the decisions
//! response before its records can be shown or bound: the contracts'
//! own JSON Schemas, embedded at build time, and a checker for the keywords
//! they use (`$ref`, `type`, `required`, `properties`,
//! `additionalProperties`, `items`, `enum`, `const`, `oneOf`, `minimum`,
//! `minLength`, `maxLength`, `minItems`, `maxItems`, `uniqueItems`, `pattern`).
//! `pattern` supports exactly the anchored subset the contracts use (`^…$`
//! over literals and `[…]`/`[^…]` classes with ranges and `\uXXXX`, each
//! optionally `*`), matched in linear time; any other pattern syntax is an
//! error, never a pass. `maxUtf8Bytes` (a byte cap no action report uses)
//! stays the server's. Any other keyword is an error, so a contract change
//! can never be silently skipped.

use std::sync::OnceLock;

use serde_json::Value;

const MESSAGING: &str = include_str!("../../../contracts/messaging.v1.schema.json");
const NEW_THREAD: &str = include_str!("../../../contracts/new-thread.v1.schema.json");
const DECISIONS: &str = include_str!("../../../contracts/decisions.v1.schema.json");

fn parsed(text: &'static str, cell: &'static OnceLock<Value>) -> &'static Value {
    cell.get_or_init(|| serde_json::from_str(text).expect("an embedded contract schema is JSON"))
}

/// The contract definition of a report schema name, if it is one of the
/// seven action reports.
fn definition(schema: &str) -> Option<(&'static Value, &'static str)> {
    static M: OnceLock<Value> = OnceLock::new();
    static N: OnceLock<Value> = OnceLock::new();
    static D: OnceLock<Value> = OnceLock::new();
    let (file, def) = match schema {
        "openwiz.messaging.v1" => (parsed(MESSAGING, &M), "report"),
        "openwiz.send-preview.v1" => (parsed(MESSAGING, &M), "preview"),
        "openwiz.send-lookup.v1" => (parsed(MESSAGING, &M), "lookup"),
        "openwiz.cloud-options.v1" => (parsed(NEW_THREAD, &N), "options"),
        "openwiz.new-thread-preview.v1" => (parsed(NEW_THREAD, &N), "preview"),
        "openwiz.new-thread.v1" => (parsed(NEW_THREAD, &N), "report"),
        "openwiz.new-thread-status.v1" => (parsed(NEW_THREAD, &N), "status_read"),
        // The decisions route's response, whose records bind answers.
        "openwiz.decisions.v1" => (parsed(DECISIONS, &D), "response"),
        _ => return None,
    };
    Some((file, def))
}

/// Whether `body` is a complete `schema` report as the contract defines it.
pub fn validate_report(schema: &str, body: &Value) -> Result<(), String> {
    let (root, def) = definition(schema).ok_or_else(|| format!("{schema} is not a report"))?;
    let node = &root["$defs"][def];
    if node.is_null() {
        return Err(format!("the contract has no {def}"));
    }
    if body.get("schema").and_then(Value::as_str) != Some(schema) {
        return Err(format!("the body is not {schema}"));
    }
    check(root, node, body, "$")
}

const IGNORED: &[&str] = &[
    "$schema",
    "$id",
    "$defs",
    "title",
    "description",
    "maxUtf8Bytes",
];

fn type_matches(name: &str, value: &Value) -> bool {
    match name {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "integer" => value.is_i64() || value.is_u64(),
        "number" => value.is_number(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        _ => false,
    }
}

fn check(root: &Value, node: &Value, value: &Value, at: &str) -> Result<(), String> {
    let Some(rules) = node.as_object() else {
        return Err(format!("{at}: the schema node is not an object"));
    };
    for (key, rule) in rules {
        match key.as_str() {
            k if IGNORED.contains(&k) => {}
            "$ref" => {
                let name = rule
                    .as_str()
                    .and_then(|r| r.strip_prefix("#/$defs/"))
                    .ok_or_else(|| format!("{at}: an unsupported $ref"))?;
                let target = &root["$defs"][name];
                if target.is_null() {
                    return Err(format!("{at}: $ref {name} does not resolve"));
                }
                check(root, target, value, at)?;
            }
            "type" => {
                let names: Vec<&str> = match rule {
                    Value::String(s) => vec![s.as_str()],
                    Value::Array(a) => a.iter().filter_map(Value::as_str).collect(),
                    _ => return Err(format!("{at}: a malformed type")),
                };
                if !names.iter().any(|n| type_matches(n, value)) {
                    return Err(format!("{at}: not of type {names:?}"));
                }
            }
            "const" if value != rule => return Err(format!("{at}: not the constant {rule}")),
            "const" => {}
            "enum" => {
                let items = rule
                    .as_array()
                    .ok_or_else(|| format!("{at}: a malformed enum"))?;
                if !items.contains(value) {
                    return Err(format!("{at}: not one of the variants"));
                }
            }
            "oneOf" => {
                let branches = rule
                    .as_array()
                    .ok_or_else(|| format!("{at}: a malformed oneOf"))?;
                let matched = branches
                    .iter()
                    .filter(|b| check(root, b, value, at).is_ok())
                    .count();
                if matched != 1 {
                    return Err(format!("{at}: matches {matched} variants, not exactly one"));
                }
            }
            "required" => {
                if let Some(object) = value.as_object() {
                    for name in rule
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                    {
                        if !object.contains_key(name) {
                            return Err(format!("{at}: {name} is missing"));
                        }
                    }
                }
            }
            "properties" => {
                if let (Some(object), Some(props)) = (value.as_object(), rule.as_object()) {
                    for (name, sub) in props {
                        if let Some(v) = object.get(name) {
                            check(root, sub, v, &format!("{at}.{name}"))?;
                        }
                    }
                }
            }
            "additionalProperties" => {
                if let Some(object) = value.as_object() {
                    let known = rules.get("properties").and_then(Value::as_object);
                    for (name, v) in object {
                        if known.is_some_and(|k| k.contains_key(name)) {
                            continue;
                        }
                        match rule {
                            Value::Bool(false) => {
                                return Err(format!("{at}: {name} is not a known field"));
                            }
                            Value::Bool(true) => {}
                            sub => check(root, sub, v, &format!("{at}.{name}"))?,
                        }
                    }
                }
            }
            "items" => {
                if let Some(items) = value.as_array() {
                    for (i, item) in items.iter().enumerate() {
                        check(root, rule, item, &format!("{at}[{i}]"))?;
                    }
                }
            }
            "maxItems" => {
                if let (Some(items), Some(max)) = (value.as_array(), rule.as_u64())
                    && (items.len() as u64) > max
                {
                    return Err(format!("{at}: more than {max} items"));
                }
            }
            "minItems" => {
                if let (Some(items), Some(min)) = (value.as_array(), rule.as_u64())
                    && (items.len() as u64) < min
                {
                    return Err(format!("{at}: fewer than {min} items"));
                }
            }
            "uniqueItems" => {
                if let Some(items) = value.as_array()
                    && rule == &Value::Bool(true)
                    && items
                        .iter()
                        .enumerate()
                        .any(|(i, a)| items[..i].contains(a))
                {
                    return Err(format!("{at}: items repeat"));
                }
            }
            "minLength" | "maxLength" => {
                if let (Some(s), Some(n)) = (value.as_str(), rule.as_u64()) {
                    let len = s.chars().count() as u64;
                    if (key == "minLength" && len < n) || (key == "maxLength" && len > n) {
                        return Err(format!("{at}: length out of bounds"));
                    }
                }
            }
            "pattern" => {
                if let Some(text) = value.as_str() {
                    let source = rule
                        .as_str()
                        .ok_or_else(|| format!("{at}: a malformed pattern"))?;
                    let atoms = parse_pattern(source)
                        .map_err(|why| format!("{at}: an unsupported pattern ({why})"))?;
                    if !matches_pattern(&atoms, text) {
                        return Err(format!("{at}: does not match its pattern"));
                    }
                }
            }
            "minimum" => {
                if let (Some(v), Some(min)) = (value.as_f64(), rule.as_f64())
                    && v < min
                {
                    return Err(format!("{at}: below its minimum"));
                }
            }
            other => return Err(format!("{at}: the unsupported schema keyword {other}")),
        }
    }
    Ok(())
}

/// One pattern atom: a set of characters (or its complement), once or `*`.
#[derive(Debug)]
struct Atom {
    ranges: Vec<(char, char)>,
    negated: bool,
    star: bool,
}

impl Atom {
    fn accepts(&self, c: char) -> bool {
        self.ranges.iter().any(|&(lo, hi)| lo <= c && c <= hi) != self.negated
    }
}

fn parse_pattern(source: &str) -> Result<Vec<Atom>, String> {
    let body = source
        .strip_prefix('^')
        .and_then(|b| b.strip_suffix('$'))
        .ok_or("not anchored with ^ and $")?;
    let chars: Vec<char> = body.chars().collect();
    let mut i = 0;
    let escaped = |chars: &[char], i: &mut usize| -> Result<char, String> {
        // At a backslash: only \uXXXX is supported.
        if chars.get(*i + 1) != Some(&'u') || *i + 6 > chars.len() {
            return Err("an unsupported escape".into());
        }
        let hex: String = chars[*i + 2..*i + 6].iter().collect();
        let code = u32::from_str_radix(&hex, 16).map_err(|_| "a malformed \\u escape")?;
        *i += 6;
        char::from_u32(code).ok_or_else(|| "a \\u escape is not a character".into())
    };
    let mut atoms = Vec::new();
    while i < chars.len() {
        let mut atom = match chars[i] {
            '[' => {
                i += 1;
                let negated = chars.get(i) == Some(&'^');
                if negated {
                    i += 1;
                }
                let mut ranges = Vec::new();
                loop {
                    let lo = match chars.get(i) {
                        None => return Err("an unclosed class".into()),
                        Some(']') => {
                            i += 1;
                            break;
                        }
                        Some('\\') => escaped(&chars, &mut i)?,
                        Some(&c) => {
                            i += 1;
                            c
                        }
                    };
                    let hi = if chars.get(i) == Some(&'-')
                        && chars.get(i + 1).is_some_and(|c| *c != ']')
                    {
                        i += 1;
                        match chars.get(i) {
                            Some('\\') => escaped(&chars, &mut i)?,
                            Some(&c) => {
                                i += 1;
                                c
                            }
                            None => return Err("an unclosed range".into()),
                        }
                    } else {
                        lo
                    };
                    if hi < lo {
                        return Err("a reversed range".into());
                    }
                    ranges.push((lo, hi));
                }
                if ranges.is_empty() {
                    return Err("an empty class".into());
                }
                Atom {
                    ranges,
                    negated,
                    star: false,
                }
            }
            '\\' => {
                let c = escaped(&chars, &mut i)?;
                Atom {
                    ranges: vec![(c, c)],
                    negated: false,
                    star: false,
                }
            }
            // `.` outside a class is a wildcard, never a literal here.
            c if "().|?+{}*$^.".contains(c) => {
                return Err(format!("the unsupported operator {c}"));
            }
            c => {
                i += 1;
                Atom {
                    ranges: vec![(c, c)],
                    negated: false,
                    star: false,
                }
            }
        };
        if chars.get(i) == Some(&'*') {
            atom.star = true;
            i += 1;
        }
        atoms.push(atom);
    }
    Ok(atoms)
}

/// Linear-time match of a whole string: the set of atoms reachable after
/// each character, starred atoms optional.
fn matches_pattern(atoms: &[Atom], text: &str) -> bool {
    let n = atoms.len();
    let close = |set: &mut Vec<bool>| {
        for i in 0..n {
            if set[i] && atoms[i].star {
                set[i + 1] = true;
            }
        }
    };
    let mut set = vec![false; n + 1];
    set[0] = true;
    close(&mut set);
    for c in text.chars() {
        let mut next = vec![false; n + 1];
        for i in 0..n {
            if set[i] && atoms[i].accepts(c) {
                next[if atoms[i].star { i } else { i + 1 }] = true;
            }
        }
        close(&mut next);
        if !next.iter().any(|&b| b) {
            return false;
        }
        set = next;
    }
    set[n]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_contract_pattern_parses_and_behaves() {
        for (pattern, good, bad) in [
            ("^[A-Za-z0-9][A-Za-z0-9_-]*$", "op-create", "bad/op"),
            ("^[0-9a-f]*$", "0af9", "g"),
            ("^ow1-[0-9a-f]*$", "ow1-2bb4", "ow2-2bb4"),
            ("^[!-,.-~][!-~]*$", "syn-codex-model-01", "bad model"),
            (
                "^[^\\u0000]*[^\\u0000\\u0009-\\u000d\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000][^\\u0000]*$",
                "  a ",
                " \t ",
            ),
        ] {
            let atoms = parse_pattern(pattern).unwrap();
            assert!(matches_pattern(&atoms, good), "{pattern} {good}");
            assert!(!matches_pattern(&atoms, bad), "{pattern} {bad}");
        }
        for unsupported in ["a", "^a$x", "^(a)$", "^a+$", "^\\d$", "^[a$"] {
            assert!(parse_pattern(unsupported).is_err(), "{unsupported}");
        }
    }
}
