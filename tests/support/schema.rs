use serde_json::Value;

mod text_rules {
    #[derive(Debug)]
    enum Atom {
        Class {
            negated: bool,
            ranges: Vec<(char, char)>,
            repeat: bool,
        },
    }

    fn escape(chars: &[char], i: &mut usize) -> Result<char, String> {
        let hex: String = chars
            .get(*i + 2..*i + 6)
            .ok_or("a short escape")?
            .iter()
            .collect();
        if chars.get(*i + 1) != Some(&'u')
            || hex.len() != 4
            || !hex.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("an escape other than \\uXXXX".to_owned());
        }
        let code = u32::from_str_radix(&hex, 16).map_err(|_| "a bad \\u escape")?;
        *i += 6;
        char::from_u32(code).ok_or_else(|| "a surrogate escape".to_owned())
    }

    const SPECIAL: &[char] = &[
        '.', '|', '?', '*', '+', '(', ')', '{', '}', '^', '$', '[', ']',
    ];

    fn parse(pattern: &str) -> Result<Vec<Atom>, String> {
        let body = pattern
            .strip_prefix('^')
            .and_then(|p| p.strip_suffix('$'))
            .ok_or("not anchored with ^ and $")?;
        let chars: Vec<char> = body.chars().collect();
        let mut atoms = Vec::new();
        let mut i = 0;
        while i < chars.len() {
            let (negated, ranges) = match chars[i] {
                '[' => {
                    i += 1;
                    let negated = chars.get(i) == Some(&'^');
                    if negated {
                        i += 1;
                    }
                    let mut ranges = Vec::new();
                    loop {
                        let lo = match chars.get(i) {
                            None => return Err("an unclosed class".to_owned()),
                            Some(']') => {
                                i += 1;
                                break;
                            }
                            Some('[') | Some('^') => return Err("[ or ^ inside a class".to_owned()),
                            Some('\\') => escape(&chars, &mut i)?,
                            Some(&c) => {
                                i += 1;
                                c
                            }
                        };
                        if chars.get(i) != Some(&'-') || chars.get(i + 1) == Some(&']') {
                            ranges.push((lo, lo));
                            continue;
                        }
                        i += 1;
                        let hi = match chars.get(i) {
                            None => return Err("an open range".to_owned()),
                            Some('[') | Some('^') => return Err("[ or ^ inside a class".to_owned()),
                            Some('\\') => escape(&chars, &mut i)?,
                            Some(&c) => {
                                i += 1;
                                c
                            }
                        };
                        if lo > hi {
                            return Err("a reversed range".to_owned());
                        }
                        ranges.push((lo, hi));
                    }
                    if ranges.is_empty() {
                        return Err("an empty class".to_owned());
                    }
                    (negated, ranges)
                }
                '\\' => {
                    let c = escape(&chars, &mut i)?;
                    (false, vec![(c, c)])
                }
                c if SPECIAL.contains(&c) => return Err(format!("{c:?} outside a class")),
                c => {
                    i += 1;
                    (false, vec![(c, c)])
                }
            };
            let repeat = chars.get(i) == Some(&'*');
            if repeat {
                i += 1;
            }
            atoms.push(Atom::Class {
                negated,
                ranges,
                repeat,
            });
        }
        Ok(atoms)
    }

    fn fits(atom: &Atom, c: char) -> bool {
        let Atom::Class {
            negated, ranges, ..
        } = atom;
        ranges.iter().any(|&(lo, hi)| lo <= c && c <= hi) != *negated
    }

    fn matches(atoms: &[Atom], text: &[char]) -> bool {
        let mut reachable = vec![false; text.len() + 1];
        reachable[0] = true;
        let mut next = vec![false; text.len() + 1];
        for atom in atoms {
            next.fill(false);
            let Atom::Class { repeat, .. } = atom;
            if *repeat {
                for i in 0..=text.len() {
                    if reachable[i] {
                        next[i] = true;
                    }
                    if next[i] && i < text.len() && fits(atom, text[i]) {
                        next[i + 1] = true;
                    }
                }
            } else {
                for i in 0..text.len() {
                    if reachable[i] && fits(atom, text[i]) {
                        next[i + 1] = true;
                    }
                }
            }
            std::mem::swap(&mut reachable, &mut next);
            if !reachable.iter().any(|&b| b) {
                return false;
            }
        }
        reachable[text.len()]
    }

    #[cfg(test)]
    #[allow(
        dead_code,
        reason = "test oracle exercised in checks/schema_conformance"
    )]
    fn previous_matches(atoms: &[Atom], text: &[char]) -> bool {
        match atoms.split_first() {
            None => text.is_empty(),
            Some((atom, rest)) => {
                let Atom::Class { repeat, .. } = atom;
                if *repeat {
                    let run = text.iter().take_while(|&&c| fits(atom, c)).count();
                    (0..=run).rev().any(|n| previous_matches(rest, &text[n..]))
                } else {
                    text.first().is_some_and(|&c| fits(atom, c))
                        && previous_matches(rest, &text[1..])
                }
            }
        }
    }

    pub(super) fn lint_pattern(pattern: &str) -> Result<(), String> {
        parse(pattern).map(|_| ())
    }

    pub(super) fn try_match(pattern: &str, text: &str) -> Option<bool> {
        let atoms = parse(pattern).ok()?;
        Some(matches(&atoms, &text.chars().collect::<Vec<_>>()))
    }

    #[cfg(test)]
    #[allow(
        dead_code,
        reason = "test oracle exercised in checks/schema_conformance"
    )]
    pub(super) fn is_match(pattern: &str, text: &str) -> bool {
        let atoms = parse(pattern).expect("a linted pattern");
        matches(&atoms, &text.chars().collect::<Vec<_>>())
    }

    #[cfg(test)]
    #[allow(
        dead_code,
        reason = "test oracle exercised in checks/schema_conformance"
    )]
    pub(super) fn previous_is_match(pattern: &str, text: &str) -> bool {
        let atoms = parse(pattern).expect("a linted pattern");
        previous_matches(&atoms, &text.chars().collect::<Vec<_>>())
    }
}

pub const SCHEMA_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/inventory.v1.schema.json"
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
            | "uniqueItems"
            | "maximum"
            | "exclusiveMinimum"
            | "minItems"
            | "maxItems"
            | "pattern"
            | "maxUtf8Bytes"
    )
}

pub fn load_schema() -> Value {
    let text = std::fs::read_to_string(SCHEMA_PATH).expect("schema file is readable");
    serde_json::from_str(&text).expect("schema is JSON")
}

pub fn lint(schema: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    let mut path = String::from("#");
    lint_node(schema, schema, &mut path, &mut errors);
    errors
}

fn lint_node(root: &Value, node: &Value, path: &mut String, errors: &mut Vec<String>) {
    use std::fmt::Write as _;

    let Some(rules) = node.as_object() else {
        errors.push(format!("{path}: schema node is not an object"));
        return;
    };
    let base_len = path.len();
    for (key, child) in rules {
        match key.as_str() {
            k if !is_known_keyword(k) => {
                errors.push(format!("{path}: unsupported schema keyword {k}"));
            }
            "additionalProperties" if child != &Value::Bool(false) => {
                errors.push(format!("{path}/{key}: only `false` is checked"));
            }
            "uniqueItems"
                if child != &Value::Bool(true)
                    || rules.get("type").and_then(Value::as_str) != Some("array") =>
            {
                errors.push(format!(
                    "{path}/{key}: only `true` on an array node is checked"
                ));
            }
            "maximum" | "exclusiveMinimum" if child.as_f64().is_none() => {
                errors.push(format!("{path}/{key}: expected a number"));
            }
            "minItems" | "maxItems" if child.as_u64().is_none() => {
                errors.push(format!("{path}/{key}: expected a nonnegative integer"));
            }
            "pattern" | "maxUtf8Bytes" => {
                if rules.get("type").and_then(Value::as_str) != Some("string") {
                    errors.push(format!("{path}/{key}: only on a \"type\": \"string\" node"));
                }
                if key == "pattern" {
                    match child.as_str().map(text_rules::lint_pattern) {
                        Some(Ok(())) => {}
                        Some(Err(_))
                            if child.as_str().is_some_and(|s| parse_pattern(s).is_ok()) => {}
                        Some(Err(error)) => {
                            errors.push(format!("{path}/{key}: unsupported ({error})"));
                        }
                        None => errors.push(format!("{path}/{key}: not a string")),
                    }
                } else if child.as_u64().is_none() {
                    errors.push(format!("{path}/{key}: not a count"));
                }
            }
            "$ref" => match child.as_str().and_then(|r| Some((r, resolve(root, r)?))) {
                Some((reference, target)) => {
                    if let Some(target_rules) = target.as_object()
                        && (target_rules.contains_key("$ref") || target_rules.contains_key("oneOf"))
                    {
                        let mut seen = vec![reference];
                        if has_ref_cycle(root, target, &mut seen) {
                            errors.push(format!("{path}/{key}: cyclic $ref {reference}"));
                        }
                    }
                }
                None => errors.push(format!("{path}/{key}: unresolvable $ref {child}")),
            },
            "$defs" | "properties" => {
                path.push('/');
                path.push_str(key);
                let key_len = path.len();
                for (name, sub) in child.as_object().into_iter().flatten() {
                    path.push('/');
                    path.push_str(name);
                    lint_node(root, sub, path, errors);
                    path.truncate(key_len);
                }
                path.truncate(base_len);
            }
            "items" => {
                path.push('/');
                path.push_str(key);
                lint_node(root, child, path, errors);
                path.truncate(base_len);
            }
            "oneOf" => {
                path.push('/');
                path.push_str(key);
                let key_len = path.len();
                for (i, sub) in child.as_array().into_iter().flatten().enumerate() {
                    let _ = write!(path, "/{i}");
                    lint_node(root, sub, path, errors);
                    path.truncate(key_len);
                }
                path.truncate(base_len);
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

pub fn validate(schema: &Value, value: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    let mut refs = Vec::new();
    let mut path = String::from("$");
    check(schema, schema, value, &mut path, &mut refs, &mut errors);
    errors
}

#[cfg(test)]
#[allow(
    dead_code,
    reason = "test oracle exercised in checks/schema_conformance"
)]
pub fn text_rule_oracle_matches(pattern: &str, text: &str) -> (bool, bool) {
    (
        text_rules::is_match(pattern, text),
        text_rules::previous_is_match(pattern, text),
    )
}

fn check<'a>(
    root: &'a Value,
    schema: &'a Value,
    value: &Value,
    path: &mut String,
    refs: &mut Vec<&'a str>,
    errors: &mut Vec<String>,
) {
    use std::fmt::Write as _;

    let Some(rules) = schema.as_object() else {
        errors.push(format!("{path}: schema node is not an object"));
        return;
    };
    for key in rules.keys() {
        if !is_known_keyword(key.as_str()) {
            errors.push(format!("{path}: unsupported schema keyword {key}"));
        }
    }
    if let Some(unique) = rules.get("uniqueItems") {
        if unique != &Value::Bool(true)
            || rules.get("type").and_then(Value::as_str) != Some("array")
        {
            errors.push(format!(
                "{path}: uniqueItems checks only `true` on an array node"
            ));
        } else if let Some(array) = value.as_array()
            && array
                .iter()
                .enumerate()
                .any(|(i, item)| array[..i].contains(item))
        {
            errors.push(format!("{path}: array items are not unique"));
        }
    }

    if let Some(reference) = rules.get("$ref").and_then(Value::as_str) {
        if refs.contains(&reference) {
            errors.push(format!("{path}: cyclic $ref {reference}"));
            return;
        }
        match resolve(root, reference) {
            Some(target) => {
                refs.push(reference);
                check(root, target, value, path, refs, errors);
                refs.pop();
            }
            None => errors.push(format!("{path}: unresolvable $ref {reference}")),
        }
    }

    if let Some(types) = rules.get("type") {
        let matched = match types {
            Value::String(t) => type_matches(t, value),
            Value::Array(ts) => ts
                .iter()
                .filter_map(Value::as_str)
                .any(|t| type_matches(t, value)),
            _ => false,
        };
        if !matched {
            let allowed: Vec<&str> = match types {
                Value::String(t) => vec![t.as_str()],
                Value::Array(ts) => ts.iter().filter_map(Value::as_str).collect(),
                _ => vec![],
            };
            errors.push(format!("{path}: expected type {allowed:?}, got {value}"));
            return;
        }
    }

    if let Some(expected) = rules.get("const")
        && value != expected
    {
        errors.push(format!("{path}: expected {expected}, got {value}"));
    }
    if let Some(options) = rules.get("enum").and_then(Value::as_array)
        && !options.contains(value)
    {
        errors.push(format!("{path}: {value} is not one of {options:?}"));
    }
    if let (Some(min), Some(n)) = (rules.get("minimum").and_then(Value::as_f64), value.as_f64())
        && n < min
    {
        errors.push(format!("{path}: {n} is below the minimum {min}"));
    }
    if let (Some(min), Some(s)) = (
        rules.get("minLength").and_then(Value::as_u64),
        value.as_str(),
    ) && (s.chars().count() as u64) < min
    {
        errors.push(format!("{path}: shorter than {min} characters"));
    }
    if let (Some(max), Some(n)) = (rules.get("maximum").and_then(Value::as_f64), value.as_f64())
        && n > max
    {
        errors.push(format!("{path}: {n} exceeds maximum {max}"));
    }
    if let (Some(min), Some(n)) = (
        rules.get("exclusiveMinimum").and_then(Value::as_f64),
        value.as_f64(),
    ) && n <= min
    {
        errors.push(format!("{path}: {n} must exceed {min}"));
    }
    if let Some(a) = value.as_array() {
        if let Some(min) = rules.get("minItems").and_then(Value::as_u64)
            && (a.len() as u64) < min
        {
            errors.push(format!("{path}: too few items"));
        }
        if let Some(max) = rules.get("maxItems").and_then(Value::as_u64)
            && (a.len() as u64) > max
        {
            errors.push(format!("{path}: too many items"));
        }
    }
    if let (Some(max), Some(s)) = (
        rules.get("maxLength").and_then(Value::as_u64),
        value.as_str(),
    ) && s.chars().count() as u64 > max
    {
        errors.push(format!("{path}: longer than {max} characters"));
    }
    if let Some(text) = value.as_str() {
        if let Some(pattern) = rules.get("pattern").and_then(Value::as_str)
            && !text_rules::try_match(pattern, text).unwrap_or_else(|| {
                parse_pattern(pattern).is_ok_and(|atoms| matches_pattern(&atoms, text))
            })
        {
            errors.push(format!("{path}: does not match {pattern:?}"));
        }
        if let Some(max) = rules.get("maxUtf8Bytes").and_then(Value::as_u64)
            && text.len() as u64 > max
        {
            errors.push(format!(
                "{path}: {} bytes of UTF-8, above {max}",
                text.len()
            ));
        }
    }

    if let Some(options) = rules.get("oneOf").and_then(Value::as_array) {
        let passing = options
            .iter()
            .filter(|option| {
                let mut e = Vec::new();
                check(root, option, value, path, refs, &mut e);
                e.is_empty()
            })
            .count();
        if passing != 1 {
            errors.push(format!(
                "{path}: matches {passing} of the oneOf options, not exactly one"
            ));
        }
    }

    if let Some(object) = value.as_object() {
        let properties = rules.get("properties").and_then(Value::as_object);
        if let Some(required) = rules.get("required").and_then(Value::as_array) {
            for key in required.iter().filter_map(Value::as_str) {
                if !object.contains_key(key) {
                    errors.push(format!("{path}: missing required field {key}"));
                }
            }
        }
        let base_len = path.len();
        for (key, child) in object {
            match properties.and_then(|p| p.get(key)) {
                Some(child_schema) => {
                    path.push('.');
                    path.push_str(key);
                    let mut child_refs = Vec::new();
                    check(root, child_schema, child, path, &mut child_refs, errors);
                    path.truncate(base_len);
                }
                None => {
                    if rules.get("additionalProperties") == Some(&Value::Bool(false)) {
                        errors.push(format!("{path}: unexpected field {key}"));
                    }
                }
            }
        }
    }

    if let (Some(items), Some(array)) = (rules.get("items"), value.as_array()) {
        let base_len = path.len();
        for (i, item) in array.iter().enumerate() {
            let _ = write!(path, "[{i}]");
            let mut item_refs = Vec::new();
            check(root, items, item, path, &mut item_refs, errors);
            path.truncate(base_len);
        }
    }
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
    let pointer = reference.strip_prefix('#')?;
    root.pointer(pointer)
}

struct Atom {
    ranges: Vec<(char, char)>,
    min: usize,
    max: Option<usize>,
}
fn parse_pattern(pattern: &str) -> Result<Vec<Atom>, ()> {
    let body = pattern
        .strip_prefix('^')
        .and_then(|s| s.strip_suffix('$'))
        .ok_or(())?;
    if !body.is_ascii() || !body.contains('[') {
        return Err(());
    }
    let chars: Vec<_> = body.chars().collect();
    let mut index = 0;
    let mut atoms = Vec::new();
    while index < chars.len() {
        let mut ranges = Vec::new();
        if chars[index] == '[' {
            index += 1;
            while index < chars.len() && chars[index] != ']' {
                let lo = chars[index];
                index += 1;
                if matches!(lo, '^' | '[' | '\\') {
                    return Err(());
                }
                if chars.get(index) == Some(&'-') && chars.get(index + 1).is_some_and(|c| *c != ']')
                {
                    let hi = chars[index + 1];
                    index += 2;
                    if matches!(hi, '^' | '[' | '\\') || lo > hi {
                        return Err(());
                    }
                    ranges.push((lo, hi));
                } else {
                    ranges.push((lo, lo));
                }
            }
            if ranges.is_empty() || chars.get(index) != Some(&']') {
                return Err(());
            }
            index += 1;
        } else {
            let mut literal = chars[index];
            index += 1;
            if literal == '\\' {
                literal = *chars.get(index).ok_or(())?;
                index += 1;
                if !".[]{}()^$*+?|\\-".contains(literal) {
                    return Err(());
                }
            } else if ".[]{}()^$*+?|".contains(literal) {
                return Err(());
            }
            ranges.push((literal, literal));
        }
        let (mut min, mut max) = (1, Some(1));
        match chars.get(index) {
            Some('*') => {
                min = 0;
                max = None;
                index += 1;
            }
            Some('+') => {
                max = None;
                index += 1;
            }
            Some('?') => {
                min = 0;
                index += 1;
            }
            Some('{') => {
                index += 1;
                let start = index;
                while chars.get(index).is_some_and(char::is_ascii_digit) {
                    index += 1;
                }
                min = chars[start..index]
                    .iter()
                    .collect::<String>()
                    .parse()
                    .map_err(|_| ())?;
                max = Some(min);
                if chars.get(index) == Some(&',') {
                    index += 1;
                    let start = index;
                    while chars.get(index).is_some_and(char::is_ascii_digit) {
                        index += 1;
                    }
                    max = if start == index {
                        None
                    } else {
                        Some(
                            chars[start..index]
                                .iter()
                                .collect::<String>()
                                .parse()
                                .map_err(|_| ())?,
                        )
                    };
                }
                if chars.get(index) != Some(&'}') || max.is_some_and(|m| m < min) {
                    return Err(());
                }
                index += 1;
            }
            _ => {}
        }
        atoms.push(Atom { ranges, min, max });
    }
    Ok(atoms)
}
fn matches_pattern(atoms: &[Atom], text: &str) -> bool {
    use std::collections::BTreeSet;
    let chars: Vec<_> = text.chars().collect();
    let mut positions = BTreeSet::from([0]);
    for atom in atoms {
        let mut next = BTreeSet::new();
        for start in positions {
            let available = chars[start..]
                .iter()
                .take(atom.max.unwrap_or(chars.len()))
                .take_while(|c| atom.ranges.iter().any(|(lo, hi)| lo <= *c && *c <= hi))
                .count();
            if available >= atom.min {
                for count in atom.min..=available {
                    next.insert(start + count);
                }
            }
        }
        positions = next;
    }
    positions.contains(&chars.len())
}
