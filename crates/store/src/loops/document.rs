//! Strict loop documents; validation reads the compiled loops.v1 schema.
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};
use std::{fmt, sync::OnceLock};

pub fn parse(text: &str) -> Result<Value, String> {
    parse_with::<true>(text)
}
fn parse_with<const MATHEMATICAL: bool>(text: &str) -> Result<Value, String> {
    let mut decoder = serde_json::Deserializer::from_str(text);
    let Strict(value) = Strict::<MATHEMATICAL>::deserialize(&mut decoder)
        .map_err(|_| "invalid or duplicate loop document field".to_owned())?;
    decoder
        .end()
        .map_err(|_| "trailing loop document data".to_owned())?;
    Ok(value)
}
pub fn read(kind: &str, text: &str) -> Result<Value, String> {
    let value = parse(text)?;
    validate(kind, &value)?;
    Ok(value)
}
pub fn validate(kind: &str, value: &Value) -> Result<(), String> {
    static SCHEMA: OnceLock<Value> = OnceLock::new();
    let schema = SCHEMA.get_or_init(|| {
        serde_json::from_str(include_str!("../../../../contracts/loops.v1.schema.json"))
            .expect("compiled loops schema")
    });
    let rule = schema["$defs"]
        .get(kind)
        .ok_or("unknown loop document kind")?;
    check(schema, rule, value, "$")
}
struct Strict<const MATHEMATICAL: bool>(Value);
impl<'de, const MATHEMATICAL: bool> Deserialize<'de> for Strict<MATHEMATICAL> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct StrictVisitor<const M: bool>;
        impl<'de, const M: bool> Visitor<'de> for StrictVisitor<M> {
            type Value = Strict<M>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("strict JSON")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Strict<M>, E> {
                Ok(Strict(Value::Bool(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Strict<M>, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Strict<M>, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Strict<M>, E> {
                if M && v.fract() == 0.0 && (0.0..18_446_744_073_709_551_616.0).contains(&v) {
                    Ok(Strict(Value::Number((v as u64).into())))
                } else {
                    Err(E::custom("not an unsigned integer in range"))
                }
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Strict<M>, E> {
                Ok(Strict(Value::String(v.to_owned())))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Strict<M>, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Strict<M>, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(value)) = seq.next_element::<Strict<M>>()? {
                    values.push(value);
                }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Strict<M>, A::Error> {
                let mut values = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("duplicate field"));
                    }
                    let Strict(value) = map.next_value::<Strict<M>>()?;
                    values.insert(key, value);
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor::<MATHEMATICAL>)
    }
}

/// The same compiled install-config shape consumed by the service. Its
/// integer syntax remains strict; loops.v1 retains mathematical integers.
pub fn service_config(text: &str) -> Result<Value, String> {
    static SCHEMA: OnceLock<Value> = OnceLock::new();
    let schema = SCHEMA.get_or_init(|| {
        serde_json::from_str(include_str!("../../../../contracts/service.v1.schema.json"))
            .expect("compiled service schema")
    });
    let value = parse_with::<false>(text)?;
    check(schema, &schema["$defs"]["config"], &value, "$")?;
    if value["server"]["port"].as_u64().is_none_or(|n| n > 65535) {
        return Err("invalid service port".to_owned());
    }
    Ok(value)
}

const KEYWORDS: &[&str] = &[
    "$ref",
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
    "pattern",
    "description",
    "minItems",
    "maxUtf8Bytes",
];

fn check(root: &Value, rule: &Value, value: &Value, at: &str) -> Result<(), String> {
    let fail = |why: &str| Err(format!("{at}: {why}"));
    let rules = rule
        .as_object()
        .ok_or_else(|| "unsupported schema node".to_owned())?;
    if rules.keys().any(|key| !KEYWORDS.contains(&key.as_str())) {
        return fail("unsupported schema rule");
    }
    if let Some(reference) = rule["$ref"].as_str() {
        let target = reference
            .strip_prefix('#')
            .and_then(|p| root.pointer(p))
            .ok_or_else(|| "unsupported schema reference".to_owned())?;
        check(root, target, value, at)?;
    }
    if let Some(kind) = rule["type"].as_str() {
        let valid = match kind {
            "object" => value.is_object(),
            "array" => value.is_array(),
            "string" => value.is_string(),
            "integer" => value.is_u64() || value.is_i64(),
            "null" => value.is_null(),
            "boolean" => value.is_boolean(),
            _ => false,
        };
        if !valid {
            return fail(&format!("expected {kind}"));
        }
    }
    if let Some(expected) = rules.get("const")
        && expected != value
    {
        return fail("unexpected constant");
    }
    if let Some(options) = rule["enum"].as_array()
        && !options.contains(value)
    {
        return fail("unknown enum value");
    }
    if let Some(min) = rule["minimum"].as_u64()
        && value.as_u64().is_none_or(|n| n < min)
    {
        return fail("integer is below its minimum");
    }
    if let Some(min) = rule["minItems"].as_u64()
        && value.as_array().is_none_or(|a| (a.len() as u64) < min)
    {
        return fail("too few array items");
    }
    if let Some(text) = value.as_str() {
        if rule["maxUtf8Bytes"]
            .as_u64()
            .is_some_and(|max| text.len() as u64 > max)
        {
            return fail("text exceeds UTF-8 byte limit");
        }
        let len = text.chars().count() as u64;
        if rule["minLength"].as_u64().is_some_and(|min| len < min)
            || rule["maxLength"].as_u64().is_some_and(|max| len > max)
        {
            return fail("string length is outside the contract");
        }
        if let Some(pattern) = rule["pattern"].as_str()
            && !pattern_matches(pattern, text)
        {
            return fail("string does not match the contract pattern");
        }
    }
    if let Some(options) = rule["oneOf"].as_array()
        && options
            .iter()
            .filter(|r| check(root, r, value, at).is_ok())
            .count()
            != 1
    {
        return fail("expected exactly one contract alternative");
    }
    if let Some(required) = rule["required"].as_array() {
        let object = value
            .as_object()
            .ok_or_else(|| format!("{at}: expected object"))?;
        for key in required.iter().filter_map(Value::as_str) {
            if !object.contains_key(key) {
                return fail(&format!("missing field {key}"));
            }
        }
    }
    if let Some(properties) = rule["properties"].as_object() {
        let object = value
            .as_object()
            .ok_or_else(|| format!("{at}: expected object"))?;
        if rule["additionalProperties"] != Value::Bool(false)
            || object.keys().any(|key| !properties.contains_key(key))
        {
            return fail("unexpected field or unsupported object rule");
        }
        for (key, subrule) in properties {
            if let Some(child) = object.get(key) {
                check(root, subrule, child, &format!("{at}.{key}"))?;
            }
        }
    }
    if let Some(items) = rules.get("items") {
        let array = value
            .as_array()
            .ok_or_else(|| format!("{at}: expected array"))?;
        for item in array {
            check(root, items, item, &format!("{at}[]"))?;
        }
    }
    Ok(())
}

fn pattern_matches(pattern: &str, text: &str) -> bool {
    match pattern {
        "^[.]*[-A-Za-z0-9_][-A-Za-z0-9_.]*$" => approval_repository_name(text, false),
        "^[.][.][.][.]*$" => approval_repository_name(text, true),
        "^[\u{1}-\u{10ffff}]*[\u{1}-\u{8}\u{e}-\u{1f}!-\u{84}\u{86}-\u{9f}\u{a1}-\u{167f}\u{1681}-\u{1fff}\u{200b}-\u{2027}\u{202a}-\u{202e}\u{2030}-\u{205e}\u{2060}-\u{2fff}\u{3001}-\u{10ffff}][\u{1}-\u{10ffff}]*$" => {
            !text.contains('\0') && !text.trim().is_empty()
        }
        "^https[:][/][/]github[.]com[/][A-Za-z0-9][-A-Za-z0-9]*[/][.]*[-A-Za-z0-9_][-A-Za-z0-9_.]*[/]issues[/][1-9][0-9]*[#]issuecomment-[1-9][0-9]*$" => {
            approval_reference(text, "issues", false)
        }
        "^https[:][/][/]github[.]com[/][A-Za-z0-9][-A-Za-z0-9]*[/][.][.][.][.]*[/]issues[/][1-9][0-9]*[#]issuecomment-[1-9][0-9]*$" => {
            approval_reference(text, "issues", true)
        }
        "^https[:][/][/]github[.]com[/][A-Za-z0-9][-A-Za-z0-9]*[/][.]*[-A-Za-z0-9_][-A-Za-z0-9_.]*[/]pull[/][1-9][0-9]*[#]issuecomment-[1-9][0-9]*$" => {
            approval_reference(text, "pull", false)
        }
        "^https[:][/][/]github[.]com[/][A-Za-z0-9][-A-Za-z0-9]*[/][.][.][.][.]*[/]pull[/][1-9][0-9]*[#]issuecomment-[1-9][0-9]*$" => {
            approval_reference(text, "pull", true)
        }
        "^[A-Za-z0-9_][-A-Za-z0-9_]*$" => {
            text.bytes()
                .next()
                .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'_')
                && text
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        }
        "^[A-Za-z0-9][-A-Za-z0-9_]*$" => {
            text.bytes()
                .next()
                .is_some_and(|b| b.is_ascii_alphanumeric())
                && text
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        }
        "^[A-Za-z0-9][-A-Za-z0-9]*$" => {
            text.bytes()
                .next()
                .is_some_and(|b| b.is_ascii_alphanumeric())
                && text.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        }
        "^[-A-Za-z0-9_.]*$" => text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b)),
        "^[0-9a-f]*$" => text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "^[A-Za-z0-9][A-Za-z0-9_-]*$" => {
            text.bytes()
                .next()
                .is_some_and(|b| b.is_ascii_alphanumeric())
                && text
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        }
        "^[!-,.-~][!-~]*$" => {
            !text.starts_with('-') && !text.is_empty() && text.bytes().all(|b| b.is_ascii_graphic())
        }
        r"^[^\u0000]*$" => !text.contains('\0'),
        r"^[^\u0000]*[^\u0000\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000][^\u0000]*$" => {
            !text.contains('\0') && !text.trim().is_empty()
        }
        _ => false,
    }
}

// Exact positive L10 pattern forms only. Unknown patterns still return false.
fn approval_repository_name(text: &str, dots_only: bool) -> bool {
    if dots_only {
        text.len() >= 3 && text.bytes().all(|b| b == b'.')
    } else {
        let tail = text.trim_start_matches('.');
        !tail.is_empty()
            && tail
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
    }
}
fn approval_reference(text: &str, kind: &str, dots_only: bool) -> bool {
    let Some(path) = text.strip_prefix("https://github.com/") else {
        return false;
    };
    let parts: Vec<_> = path.split('/').collect();
    let [owner, name, actual_kind, subject] = parts.as_slice() else {
        return false;
    };
    let Some((number, comment)) = subject.split_once("#issuecomment-") else {
        return false;
    };
    let positive = |s: &str| {
        s.starts_with(|c: char| matches!(c, '1'..='9')) && s.bytes().all(|b| b.is_ascii_digit())
    };
    owner
        .bytes()
        .next()
        .is_some_and(|b| b.is_ascii_alphanumeric())
        && owner
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        && approval_repository_name(name, dots_only)
        && *actual_kind == kind
        && positive(number)
        && positive(comment)
}
