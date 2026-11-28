#![allow(
    dead_code,
    reason = "included by more than one test target, and each uses only part of it"
)]

use std::collections::BTreeSet;

use serde_json::Value;

pub const SCHEMA_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/fleet.v1.schema.json"
);

fn is_known_keyword(key: &str) -> bool {
    matches!(
        key,
        "$schema"
            | "$id"
            | "$defs"
            | "$ref"
            | "title"
            | "description"
            | "type"
            | "required"
            | "properties"
            | "additionalProperties"
            | "items"
            | "enum"
            | "const"
            | "oneOf"
            | "minimum"
            | "minLength"
            | "maxLength"
            | "pattern"
    )
}

pub fn load_schema() -> Value {
    let text = std::fs::read_to_string(SCHEMA_PATH).expect("the fleet schema is readable");
    serde_json::from_str(&text).expect("the fleet schema is JSON")
}

pub fn lint(schema: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    let mut at = String::from("#");
    lint_node(schema, schema, &mut at, &mut errors);
    errors
}

fn lint_node(root: &Value, node: &Value, at: &mut String, errors: &mut Vec<String>) {
    use std::fmt::Write as _;

    let Some(rules) = node.as_object() else {
        errors.push(format!("{at}: schema node is not an object"));
        return;
    };
    let base_len = at.len();
    for (key, child) in rules {
        match key.as_str() {
            k if !is_known_keyword(k) => {
                errors.push(format!("{at}: unsupported schema keyword {k}"));
            }
            "additionalProperties" if child != &Value::Bool(false) => {
                errors.push(format!("{at}/{key}: only `false` is checked"));
            }
            "pattern" => {
                if let Err(why) = child
                    .as_str()
                    .ok_or("not a string".to_owned())
                    .and_then(parse)
                {
                    errors.push(format!("{at}/{key}: {why}"));
                }
            }
            "$ref" => match child.as_str().and_then(|r| Some((r, resolve(root, r)?))) {
                Some((reference, target)) => {
                    if let Some(target_rules) = target.as_object()
                        && (target_rules.contains_key("$ref") || target_rules.contains_key("oneOf"))
                    {
                        let mut seen = vec![reference];
                        if has_ref_cycle(root, target, &mut seen) {
                            errors.push(format!("{at}/{key}: cyclic $ref {reference}"));
                        }
                    }
                }
                None => errors.push(format!("{at}/{key}: unresolvable $ref {child}")),
            },
            "$defs" | "properties" => {
                at.push('/');
                at.push_str(key);
                let key_len = at.len();
                for (name, sub) in child.as_object().into_iter().flatten() {
                    at.push('/');
                    at.push_str(name);
                    lint_node(root, sub, at, errors);
                    at.truncate(key_len);
                }
                at.truncate(base_len);
            }
            "items" => {
                at.push('/');
                at.push_str(key);
                lint_node(root, child, at, errors);
                at.truncate(base_len);
            }
            "oneOf" => {
                at.push('/');
                at.push_str(key);
                let key_len = at.len();
                for (i, sub) in child.as_array().into_iter().flatten().enumerate() {
                    let _ = write!(at, "/{i}");
                    lint_node(root, sub, at, errors);
                    at.truncate(key_len);
                }
                at.truncate(base_len);
            }
            _ => {}
        }
    }
}

fn has_ref_cycle<'a>(root: &'a Value, node: &'a Value, seen: &mut Vec<&'a str>) -> bool {
    let Some(rules) = node.as_object() else {
        return false;
    };
    if let Some(reference) = rules.get("$ref").and_then(Value::as_str) {
        if seen.contains(&reference) {
            return true;
        }
        if let Some(target) = resolve(root, reference) {
            seen.push(reference);
            let cyclic = has_ref_cycle(root, target, seen);
            seen.pop();
            if cyclic {
                return true;
            }
        }
    }
    if let Some(options) = rules.get("oneOf").and_then(Value::as_array) {
        for option in options {
            if has_ref_cycle(root, option, seen) {
                return true;
            }
        }
    }
    false
}

#[derive(Default, Debug)]
pub struct Coverage(pub BTreeSet<(String, String)>);

pub fn validate(schema: &Value, value: &Value) -> Vec<String> {
    validate_with(schema, value, &mut Coverage::default())
}

pub fn validate_with(schema: &Value, value: &Value, coverage: &mut Coverage) -> Vec<String> {
    let mut errors = Vec::new();
    let mut hits = Coverage::default();
    let mut refs = Vec::new();
    check(schema, "#", value, "$", &mut refs, &mut errors, &mut hits);
    if errors.is_empty() {
        coverage.0.extend(hits.0);
    }
    errors
}

fn node<'a>(root: &'a Value, at: &str) -> &'a Value {
    resolve(root, at).unwrap_or(&Value::Null)
}

fn check<'a>(
    root: &'a Value,
    at: &str,
    value: &Value,
    path: &str,
    refs: &mut Vec<&'a str>,
    errors: &mut Vec<String>,
    hits: &mut Coverage,
) {
    let Some(rules) = node(root, at).as_object() else {
        errors.push(format!("{path}: schema node {at} is not an object"));
        return;
    };
    for key in rules.keys() {
        if !is_known_keyword(key.as_str()) {
            errors.push(format!("{path}: unsupported schema keyword {key}"));
        }
    }
    if let Some(reference) = rules.get("$ref").and_then(Value::as_str) {
        if refs.contains(&reference) {
            errors.push(format!("{path}: cyclic $ref {reference}"));
            return;
        }
        match resolve(root, reference) {
            Some(_) => {
                refs.push(reference);
                check(root, reference, value, path, refs, errors, hits);
                refs.pop();
            }
            None => errors.push(format!("{path}: unresolvable $ref {reference}")),
        }
    }
    if let Some(types) = rules.get("type") {
        let allowed: Vec<&str> = match types {
            Value::String(t) => vec![t.as_str()],
            Value::Array(ts) => ts.iter().filter_map(Value::as_str).collect(),
            _ => vec![],
        };
        match allowed.iter().find(|t| type_matches(t, value)) {
            None => {
                errors.push(format!("{path}: expected type {allowed:?}, got {value}"));
                return;
            }
            Some(t) if types.is_array() => {
                hits.0.insert((at.to_owned(), format!("type {t}")));
            }
            Some(_) => {}
        }
    }
    if let Some(expected) = rules.get("const")
        && value != expected
    {
        errors.push(format!("{path}: expected {expected}, got {value}"));
    }
    if let Some(options) = rules.get("enum").and_then(Value::as_array) {
        if options.contains(value) {
            hits.0.insert((at.to_owned(), format!("enum {value}")));
        } else {
            errors.push(format!("{path}: {value} is not one of {options:?}"));
        }
    }
    if let (Some(min), Some(n)) = (rules.get("minimum").and_then(Value::as_f64), value.as_f64())
        && n < min
    {
        errors.push(format!("{path}: {n} is below the minimum {min}"));
    }
    if let Some(s) = value.as_str() {
        let chars = s.chars().count() as u64;
        if let Some(min) = rules.get("minLength").and_then(Value::as_u64)
            && chars < min
        {
            errors.push(format!("{path}: shorter than {min} characters"));
        }
        if let Some(max) = rules.get("maxLength").and_then(Value::as_u64)
            && chars > max
        {
            errors.push(format!("{path}: longer than {max} characters"));
        }
        if let Some(pattern) = rules.get("pattern").and_then(Value::as_str) {
            match parse(pattern) {
                Ok(atoms) if matches(&atoms, s) => {}
                Ok(_) => errors.push(format!("{path}: {s:?} does not match {pattern}")),
                Err(why) => errors.push(format!("{path}: pattern {pattern}: {why}")),
            }
        }
    }
    if let Some(options) = rules.get("oneOf").and_then(Value::as_array) {
        let mut passing = Vec::new();
        for i in 0..options.len() {
            let mut e = Vec::new();
            let mut h = Coverage::default();
            check(
                root,
                &format!("{at}/oneOf/{i}"),
                value,
                path,
                refs,
                &mut e,
                &mut h,
            );
            if e.is_empty() {
                passing.push((i, h));
            }
        }
        if passing.len() == 1 {
            let (i, h) = passing.pop().expect("one");
            hits.0.insert((at.to_owned(), format!("oneOf {i}")));
            hits.0.extend(h.0);
        } else {
            errors.push(format!(
                "{path}: matches {} of the oneOf options, not exactly one",
                passing.len()
            ));
        }
    }
    if let Some(object) = value.as_object() {
        let properties = rules.get("properties").and_then(Value::as_object);
        for key in rules
            .get("required")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
        {
            if !object.contains_key(key) {
                errors.push(format!("{path}: missing required field {key}"));
            }
        }
        for (key, child) in object {
            let child_path = format!("{path}.{key}");
            if properties.is_some_and(|p| p.contains_key(key)) {
                hits.0.insert((at.to_owned(), format!("property {key}")));
                let child_at = format!("{at}/properties/{}", escape(key));
                let mut child_refs = Vec::new();
                check(
                    root,
                    &child_at,
                    child,
                    &child_path,
                    &mut child_refs,
                    errors,
                    hits,
                );
            } else if rules.get("additionalProperties") == Some(&Value::Bool(false)) {
                errors.push(format!("{path}: unexpected field {key}"));
            }
        }
    }
    if let (Some(_), Some(array)) = (rules.get("items"), value.as_array()) {
        for (i, item) in array.iter().enumerate() {
            let mut item_refs = Vec::new();
            check(
                root,
                &format!("{at}/items"),
                item,
                &format!("{path}[{i}]"),
                &mut item_refs,
                errors,
                hits,
            );
        }
    }
}

fn escape(key: &str) -> String {
    key.replace('~', "~0").replace('/', "~1")
}

fn type_matches(t: &str, value: &Value) -> bool {
    match t {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        "integer" => value.is_i64() || value.is_u64(),
        "number" => value.is_number(),
        _ => false,
    }
}

fn resolve<'a>(root: &'a Value, reference: &str) -> Option<&'a Value> {
    root.pointer(reference.strip_prefix('#')?)
}

#[derive(Debug)]
struct Atom {
    class: Vec<(char, char)>,
    repeat: bool,
}

fn parse(pattern: &str) -> Result<Vec<Atom>, String> {
    let body = pattern
        .strip_prefix('^')
        .and_then(|p| p.strip_suffix('$'))
        .ok_or("not anchored with ^ and $")?;
    let mut chars = body.chars().peekable();
    let mut atoms = Vec::new();
    while let Some(c) = chars.next() {
        let class = match c {
            '[' => {
                let mut class = Vec::new();
                loop {
                    let first = chars.next().ok_or("an unclosed [")?;
                    if first == ']' {
                        break;
                    }
                    if "\\^[".contains(first) {
                        return Err(format!("{first:?} in a class is not supported"));
                    }
                    if chars.peek() == Some(&'-') {
                        chars.next();
                        let last = chars.next().ok_or("an unclosed range")?;
                        if last == ']' || last < first || "\\^[".contains(last) {
                            return Err("a range that is not supported".to_owned());
                        }
                        class.push((first, last));
                    } else {
                        class.push((first, first));
                    }
                }
                if class.is_empty() {
                    return Err("an empty class".to_owned());
                }
                class
            }
            c if c.is_ascii_alphanumeric() || c == '_' || c == '-' => vec![(c, c)],
            other => return Err(format!("{other:?} is not supported")),
        };
        let repeat = chars.peek() == Some(&'*');
        if repeat {
            chars.next();
        }
        atoms.push(Atom { class, repeat });
    }
    Ok(atoms)
}

fn matches(atoms: &[Atom], s: &str) -> bool {
    let chars: Vec<char> = s.chars().collect();
    let in_class = |atom: &Atom, c: char| atom.class.iter().any(|(a, b)| (*a..=*b).contains(&c));
    let mut reachable = vec![false; chars.len() + 1];
    reachable[0] = true;
    let mut next = vec![false; chars.len() + 1];
    for atom in atoms {
        next.fill(false);
        if atom.repeat {
            for i in 0..=chars.len() {
                if reachable[i] {
                    next[i] = true;
                }
                if next[i] && i < chars.len() && in_class(atom, chars[i]) {
                    next[i + 1] = true;
                }
            }
        } else {
            for i in 0..chars.len() {
                if reachable[i] && in_class(atom, chars[i]) {
                    next[i + 1] = true;
                }
            }
        }
        std::mem::swap(&mut reachable, &mut next);
        if !reachable.iter().any(|&b| b) {
            return false;
        }
    }
    reachable[chars.len()]
}

#[cfg(test)]
fn previous_matches(atoms: &[Atom], s: &str) -> bool {
    let in_class = |atom: &Atom, c: char| atom.class.iter().any(|(a, b)| (*a..=*b).contains(&c));
    match atoms.split_first() {
        None => s.is_empty(),
        Some((atom, rest)) if atom.repeat => {
            let mut tail = s;
            loop {
                if previous_matches(rest, tail) {
                    return true;
                }
                match tail.chars().next() {
                    Some(c) if in_class(atom, c) => tail = &tail[c.len_utf8()..],
                    _ => return false,
                }
            }
        }
        Some((atom, rest)) => match s.chars().next() {
            Some(c) if in_class(atom, c) => previous_matches(rest, &s[c.len_utf8()..]),
            _ => false,
        },
    }
}

#[cfg(test)]
pub fn pattern_oracle_matches(pattern: &str, text: &str) -> (bool, bool) {
    let atoms = parse(pattern).expect("a linted fleet pattern");
    (matches(&atoms, text), previous_matches(&atoms, text))
}
