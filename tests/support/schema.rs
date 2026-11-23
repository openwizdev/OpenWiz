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
        if chars.get(*i + 1) != Some(&'u') || hex.len() != 4 {
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
        match atoms.split_first() {
            None => text.is_empty(),
            Some((atom, rest)) => {
                let Atom::Class { repeat, .. } = atom;
                if *repeat {
                    let run = text.iter().take_while(|&&c| fits(atom, c)).count();
                    (0..=run).rev().any(|n| matches(rest, &text[n..]))
                } else {
                    text.first().is_some_and(|&c| fits(atom, c)) && matches(rest, &text[1..])
                }
            }
        }
    }

    pub(super) fn lint_pattern(pattern: &str) -> Result<(), String> {
        parse(pattern).map(|_| ())
    }

    pub(super) fn is_match(pattern: &str, text: &str) -> bool {
        let atoms = parse(pattern).expect("a linted pattern");
        matches(&atoms, &text.chars().collect::<Vec<_>>())
    }
}

pub const SCHEMA_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/inventory.v1.schema.json"
);

const KNOWN_KEYWORDS: &[&str] = &[
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "oneOf",
    "minimum",
    "minLength",
    "maxLength",
    "uniqueItems",
    "maximum",
    "exclusiveMinimum",
    "minItems",
    "maxItems",
    "pattern",
    "maxUtf8Bytes",
];

pub fn load_schema() -> Value {
    let text = std::fs::read_to_string(SCHEMA_PATH).expect("schema file is readable");
    serde_json::from_str(&text).expect("schema is JSON")
}

pub fn lint(schema: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    lint_node(schema, schema, "#", &mut errors);
    errors
}

fn lint_node(root: &Value, node: &Value, path: &str, errors: &mut Vec<String>) {
    let Some(rules) = node.as_object() else {
        errors.push(format!("{path}: schema node is not an object"));
        return;
    };
    for (key, child) in rules {
        let at = format!("{path}/{key}");
        match key.as_str() {
            k if !KNOWN_KEYWORDS.contains(&k) => {
                errors.push(format!("{path}: unsupported schema keyword {k}"))
            }
            "additionalProperties" if child != &Value::Bool(false) => {
                errors.push(format!("{at}: only `false` is checked"))
            }
            "uniqueItems"
                if child != &Value::Bool(true)
                    || rules.get("type").and_then(Value::as_str) != Some("array") =>
            {
                errors.push(format!("{at}: only `true` on an array node is checked"))
            }
            "maximum" | "exclusiveMinimum" if child.as_f64().is_none() => {
                errors.push(format!("{at}: expected a number"))
            }
            "minItems" | "maxItems" if child.as_u64().is_none() => {
                errors.push(format!("{at}: expected a nonnegative integer"))
            }
            "pattern" | "maxUtf8Bytes" => {
                if rules.get("type").and_then(Value::as_str) != Some("string") {
                    errors.push(format!("{at}: only on a \"type\": \"string\" node"));
                }
                if key == "pattern" {
                    match child.as_str().map(text_rules::lint_pattern) {
                        Some(Ok(())) => {}
                        Some(Err(_))
                            if child.as_str().is_some_and(|s| parse_pattern(s).is_ok()) => {}
                        Some(Err(error)) => errors.push(format!("{at}: unsupported ({error})")),
                        None => errors.push(format!("{at}: not a string")),
                    }
                } else if child.as_u64().is_none() {
                    errors.push(format!("{at}: not a count"));
                }
            }
            "$ref" => match child.as_str() {
                Some(reference) if resolve(root, reference).is_some() => {}
                _ => errors.push(format!("{at}: unresolvable $ref {child}")),
            },
            "$defs" | "properties" => {
                for (name, sub) in child.as_object().into_iter().flatten() {
                    lint_node(root, sub, &format!("{at}/{name}"), errors);
                }
            }
            "items" => lint_node(root, child, &at, errors),
            "oneOf" => {
                for (i, sub) in child.as_array().into_iter().flatten().enumerate() {
                    lint_node(root, sub, &format!("{at}/{i}"), errors);
                }
            }
            _ => {}
        }
    }
}

pub fn validate(schema: &Value, value: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    check(schema, schema, value, "$", &mut errors);
    errors
}

fn check(root: &Value, schema: &Value, value: &Value, path: &str, errors: &mut Vec<String>) {
    let Some(rules) = schema.as_object() else {
        errors.push(format!("{path}: schema node is not an object"));
        return;
    };
    for key in rules.keys() {
        if !KNOWN_KEYWORDS.contains(&key.as_str()) {
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
        match resolve(root, reference) {
            Some(target) => check(root, target, value, path, errors),
            None => errors.push(format!("{path}: unresolvable $ref {reference}")),
        }
    }

    if let Some(types) = rules.get("type") {
        let allowed: Vec<&str> = match types {
            Value::String(t) => vec![t.as_str()],
            Value::Array(ts) => ts.iter().filter_map(Value::as_str).collect(),
            _ => vec![],
        };
        if !allowed.iter().any(|t| type_matches(t, value)) {
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
            && !if text_rules::lint_pattern(pattern).is_ok() {
                text_rules::is_match(pattern, text)
            } else {
                parse_pattern(pattern).is_ok_and(|atoms| matches_pattern(&atoms, text))
            }
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
                check(root, option, value, path, &mut e);
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
        for (key, child) in object {
            let child_path = format!("{path}.{key}");
            match properties.and_then(|p| p.get(key)) {
                Some(child_schema) => check(root, child_schema, child, &child_path, errors),
                None => {
                    if rules.get("additionalProperties") == Some(&Value::Bool(false)) {
                        errors.push(format!("{path}: unexpected field {key}"));
                    }
                }
            }
        }
    }

    if let (Some(items), Some(array)) = (rules.get("items"), value.as_array()) {
        for (i, item) in array.iter().enumerate() {
            check(root, items, item, &format!("{path}[{i}]"), errors);
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
                    if lo > hi {
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
