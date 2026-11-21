use serde_json::Value;

const KEYWORDS: &[&str] = &["pattern", "maxUtf8Bytes", "uniqueItems", "minItems"];

const ARRAY_KEYWORDS: &[&str] = &["uniqueItems", "minItems"];

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

pub struct Pattern(Vec<Atom>);

impl Pattern {
    pub fn new(pattern: &str) -> Self {
        Self(parse(pattern).unwrap_or_else(|e| panic!("pattern {pattern:?}: {e}")))
    }

    pub fn is_match(&self, text: &str) -> bool {
        matches(&self.0, &text.chars().collect::<Vec<_>>())
    }
}

pub fn is_match(pattern: &str, text: &str) -> bool {
    Pattern::new(pattern).is_match(text)
}

fn stripped(schema: &Value) -> Value {
    match schema {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(k, _)| !KEYWORDS.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), stripped(v)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(stripped).collect()),
        other => other.clone(),
    }
}

fn lint_node(node: &Value, path: &str, errors: &mut Vec<String>) {
    match node {
        Value::Object(map) => {
            for key in KEYWORDS {
                let (kind, on) = if ARRAY_KEYWORDS.contains(key) {
                    ("array", map.get("type") == Some(&Value::from("array")))
                } else {
                    ("string", map.get("type") == Some(&Value::from("string")))
                };
                if map.contains_key(*key) && !on {
                    errors.push(format!("{path}/{key}: only on a \"type\": \"{kind}\" node"));
                }
            }
            if let Some(u) = map.get("uniqueItems")
                && u != &Value::Bool(true)
            {
                errors.push(format!("{path}/uniqueItems: only true"));
            }
            if let Some(n) = map.get("minItems")
                && n.as_u64().is_none()
            {
                errors.push(format!("{path}/minItems: not a count"));
            }
            if let Some(p) = map.get("pattern") {
                match p.as_str().map(parse) {
                    Some(Ok(_)) => {}
                    Some(Err(e)) => errors.push(format!("{path}/pattern: unsupported ({e})")),
                    None => errors.push(format!("{path}/pattern: not a string")),
                }
            }
            if let Some(n) = map.get("maxUtf8Bytes")
                && n.as_u64().is_none()
            {
                errors.push(format!("{path}/maxUtf8Bytes: not a count"));
            }
            for (k, child) in map {
                if !KEYWORDS.contains(&k.as_str()) {
                    lint_node(child, &format!("{path}/{k}"), errors);
                }
            }
        }
        Value::Array(items) => {
            for (i, item) in items.iter().enumerate() {
                lint_node(item, &format!("{path}/{i}"), errors);
            }
        }
        _ => {}
    }
}

pub fn lint(schema: &Value) -> Vec<String> {
    let mut errors = crate::schema::lint(&stripped(schema));
    lint_node(schema, "#", &mut errors);
    errors
}

pub fn validate(schema: &Value, value: &Value) -> Vec<String> {
    let mut errors = crate::schema::validate(&stripped(schema), value);
    if errors.is_empty() {
        walk(schema, schema, value, "$", &mut errors);
    }
    errors
}

fn structurally(root: &Value, pointer: &str, value: &Value) -> bool {
    let mut probe = stripped(root);
    let object = probe.as_object_mut().expect("an object schema");
    for key in [
        "type",
        "properties",
        "required",
        "oneOf",
        "items",
        "const",
        "enum",
    ] {
        object.remove(key);
    }
    object.insert("$ref".to_owned(), Value::from(format!("#{pointer}")));
    crate::schema::validate(&probe, value).is_empty()
}

fn walk(root: &Value, node: &Value, value: &Value, path: &str, errors: &mut Vec<String>) {
    walk_at(root, node, None, value, path, errors)
}

fn walk_at(
    root: &Value,
    node: &Value,
    pointer: Option<&str>,
    value: &Value,
    path: &str,
    errors: &mut Vec<String>,
) {
    let Some(rules) = node.as_object() else {
        return;
    };
    if let Some(reference) = rules.get("$ref").and_then(Value::as_str) {
        let target = reference.strip_prefix('#').unwrap_or_default();
        if let Some(next) = root.pointer(target) {
            walk_at(root, next, Some(target), value, path, errors);
        }
    }
    if let Some(text) = value.as_str() {
        if let Some(p) = rules.get("pattern").and_then(Value::as_str)
            && !is_match(p, text)
        {
            errors.push(format!("{path}: does not match {p:?}"));
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
    if let (Some(props), Some(object)) = (
        rules.get("properties").and_then(Value::as_object),
        value.as_object(),
    ) {
        for (k, child) in object {
            if let Some(schema) = props.get(k) {
                let at = pointer.map(|p| format!("{p}/properties/{k}"));
                walk_at(
                    root,
                    schema,
                    at.as_deref(),
                    child,
                    &format!("{path}.{k}"),
                    errors,
                );
            }
        }
    }
    if let Some(array) = value.as_array() {
        if let Some(min) = rules.get("minItems").and_then(Value::as_u64)
            && (array.len() as u64) < min
        {
            errors.push(format!("{path}: {} items, fewer than {min}", array.len()));
        }
        if rules.get("uniqueItems") == Some(&Value::Bool(true)) {
            for (i, item) in array.iter().enumerate() {
                if array[..i].contains(item) {
                    errors.push(format!("{path}[{i}]: equal to an earlier item"));
                }
            }
        }
    }
    if let (Some(items), Some(array)) = (rules.get("items"), value.as_array()) {
        for (i, item) in array.iter().enumerate() {
            let at = pointer.map(|p| format!("{p}/items"));
            walk_at(
                root,
                items,
                at.as_deref(),
                item,
                &format!("{path}[{i}]"),
                errors,
            );
        }
    }
    if let Some(branches) = rules.get("oneOf").and_then(Value::as_array) {
        let Some(base) = pointer else {
            errors.push(format!("{path}: a oneOf with no pointer to check it by"));
            return;
        };
        let matched: Vec<usize> = (0..branches.len())
            .filter(|i| structurally(root, &format!("{base}/oneOf/{i}"), value))
            .collect();
        if let [one] = matched.as_slice() {
            let at = format!("{base}/oneOf/{one}");
            walk_at(root, &branches[*one], Some(&at), value, path, errors);
        }
    }
}
