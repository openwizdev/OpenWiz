//! Strict service document readers. The embedded contract supplies the shape;
//! unknown schema rules fail closed. Errors contain rules, never input values.
use std::fmt;
use std::sync::OnceLock;

use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};

#[derive(Clone, Copy)]
pub enum Document {
    Config,
    State,
    Status,
    Record,
}

impl Document {
    fn definition(self) -> &'static str {
        match self {
            Self::Config => "config",
            Self::State => "state",
            Self::Status => "status",
            Self::Record => "record",
        }
    }
}

pub fn read(kind: Document, text: &str) -> Result<Value, String> {
    let mut deserializer = serde_json::Deserializer::from_str(text);
    let Strict(value) = Strict::deserialize(&mut deserializer)
        .map_err(|_| "expected strict JSON with no duplicate fields".to_owned())?;
    deserializer
        .end()
        .map_err(|_| "unexpected data after the JSON document".to_owned())?;
    validate(kind, &value)?;
    semantic(kind, &value)?;
    Ok(value)
}

/// Validate an already strictly parsed document, including one we will print.
/// Config validates the strict base independently of loop admission, including
/// for callers such as update construction and pending recovery.
pub fn validate(kind: Document, value: &Value) -> Result<(), String> {
    let schema = schema();
    if matches!(kind, Document::Config) {
        let mut base = value.clone();
        if let Some(object) = base.as_object_mut() {
            object.remove("loops");
        }
        check(schema, &schema["$defs"]["config"], &base, "$")
    } else {
        check(schema, &schema["$defs"][kind.definition()], value, "$")
    }
}

/// Loop admission must validate the complete enclosing configuration and both
/// required LP1 fragments. Independent service jobs use base validation above.
pub fn validate_loop_config(value: &Value) -> Result<(), String> {
    if value.get("loops").is_none() {
        return Err("required loop configuration is absent".to_owned());
    }
    let schema = schema();
    check(schema, &schema["$defs"]["config"], value, "$")
}

fn schema() -> &'static Value {
    static SCHEMA: OnceLock<Value> = OnceLock::new();
    SCHEMA.get_or_init(|| {
        serde_json::from_str(include_str!("../../../contracts/service.v1.schema.json"))
            .expect("the compiled service contract is JSON")
    })
}

struct Strict(Value);

impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = Strict;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("strict JSON")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(Value::Bool(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Strict, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Strict, E> {
                Number::from_f64(v)
                    .map(|n| Strict(Value::Number(n)))
                    .ok_or_else(|| E::custom("nonfinite number"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(Value::String(v.to_owned())))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Strict, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(value)) = seq.next_element()? {
                    values.push(value);
                }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Strict, A::Error> {
                let mut values = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("duplicate field"));
                    }
                    let Strict(value) = map.next_value()?;
                    values.insert(key, value);
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
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
];

fn check(root: &Value, rule: &Value, value: &Value, at: &str) -> Result<(), String> {
    let fail = |why: &str| Err(format!("{at}: {why}"));
    let rules = rule
        .as_object()
        .ok_or_else(|| "unsupported schema node".to_owned())?;
    if rules.keys().any(|key| !KEYWORDS.contains(&key.as_str())) {
        return fail("unsupported schema rule");
    }
    if rule["$ref"] == "#/$defs/loop_approvals" {
        // Reuse L10's exact reader for its full approved fragment, including
        // binding uniqueness and patterns outside the base schema subset.
        return crate::loops::approval::Approvals::read(&value.to_string())
            .map(|_| ())
            .map_err(|_| format!("{at}: invalid trusted loop approvals"));
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
    if let Some(text) = value.as_str() {
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

/// Only the contract's observed pattern forms are supported.
fn pattern_matches(pattern: &str, text: &str) -> bool {
    let id_tail = |b: u8| b.is_ascii_alphanumeric() || b == b'_' || b == b'-';
    let first = text.bytes().next();
    match pattern {
        "^[A-Za-z0-9_][-A-Za-z0-9_]*$" => {
            first.is_some_and(|b| b.is_ascii_alphanumeric() || b == b'_')
                && text.bytes().all(id_tail)
        }
        "^[A-Za-z0-9][-A-Za-z0-9_]*$" => {
            first.is_some_and(|b| b.is_ascii_alphanumeric()) && text.bytes().all(id_tail)
        }
        "^[A-Za-z0-9][-A-Za-z0-9]*$" => {
            first.is_some_and(|b| b.is_ascii_alphanumeric())
                && text.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        }
        "^[-A-Za-z0-9_.]*$" => text.bytes().all(|b| id_tail(b) || b == b'.'),
        "^[-A-Za-z0-9_][-A-Za-z0-9_.]*$" => {
            first.is_some_and(id_tail) && text.bytes().all(|b| id_tail(b) || b == b'.')
        }
        "^[.][-A-Za-z0-9_]$" => {
            text.len() == 2 && text.starts_with('.') && id_tail(text.as_bytes()[1])
        }
        "^[0-9a-f]*$" => text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "^i[1-9][0-9]*$" => text.strip_prefix('i').is_some_and(|s| {
            s.starts_with(|c: char| matches!(c, '1'..='9')) && s.bytes().all(|b| b.is_ascii_digit())
        }),
        _ => false,
    }
}

fn semantic(kind: Document, value: &Value) -> Result<(), String> {
    if matches!(kind, Document::Record) {
        return Ok(());
    }
    use std::collections::BTreeSet;
    let require = |yes: bool, rule: &str| {
        if yes {
            Ok(())
        } else {
            Err(format!("service document violates {rule}"))
        }
    };
    if matches!(kind, Document::Config) {
        if let Some(pair) = value.get("decision_repositories") {
            let name = |role: &str| {
                format!(
                    "{}/{}",
                    pair[role]["owner"].as_str().unwrap(),
                    pair[role]["name"].as_str().unwrap()
                )
            };
            for role in ["public", "private"] {
                let repo_name = pair[role]["name"].as_str().unwrap();
                require(
                    matches!(
                        std::path::Path::new(repo_name).components().next(),
                        Some(std::path::Component::Normal(_))
                    ),
                    "decision repository name is one ordinary path component",
                )?;
            }
            require(
                !name("public").eq_ignore_ascii_case(&name("private")),
                "decision repository roles must differ",
            )?;
        }
        return require(
            value["server"]["port"].as_u64().unwrap() <= 65535,
            "server.port: 1 to 65535",
        );
    }
    let at = value["at"].as_u64().unwrap_or(u64::MAX);
    let retired = value.get("retired_loops").and_then(Value::as_array);
    if let Some(rows) = retired {
        let mut loops = BTreeSet::new();
        for row in rows {
            require(
                loops.insert(row["loop"].as_str().unwrap()),
                "TK1: duplicate retired loop",
            )?;
        }
    }
    let time = |v: &Value| v.as_u64().unwrap_or(0);
    let tick = &value["tick"];
    if !tick["last_ended"].is_null() {
        require(
            time(&tick["last_ended"]["started_at"]) <= time(&tick["last_ended"]["ended_at"]),
            "S6: tick end before start",
        )?;
    }
    fn check_times(v: &Value, at: u64) -> bool {
        match v {
            Value::Object(map) => map.iter().all(|(key, child)| {
                let is_time = matches!(
                    key.as_str(),
                    "at" | "since"
                        | "started_at"
                        | "ended_at"
                        | "opened_at"
                        | "healthy_since"
                        | "run_started_at"
                        | "due_at_ms"
                        | "started_at_ms"
                );
                (!is_time || child.is_null() || child.as_u64().is_some_and(|n| n <= at))
                    && check_times(child, at)
            }),
            Value::Array(values) => values.iter().all(|v| check_times(v, at)),
            _ => true,
        }
    }
    require(check_times(value, at), "S6: a time after the report")?;
    let mut ids = BTreeSet::new();
    let mut subjects = BTreeSet::new();
    let mut watchdog_notifications = std::collections::BTreeMap::new();
    let incidents = value["incidents"].as_array().unwrap();
    for incident in incidents {
        let id = incident["id"].as_str().unwrap();
        let n = id[1..]
            .parse::<u64>()
            .map_err(|_| "incident id is outside the counter range".to_owned())?;
        require(ids.insert(id), "S2: duplicate incident id")?;
        if matches!(kind, Document::State) {
            require(
                n < value["next_incident"].as_u64().unwrap(),
                "S2: next_incident",
            )?;
        }
        require(
            subjects.insert(subject(incident)),
            "S2: duplicate incident subject",
        )?;
        let opened = time(&incident["opened_at"]);
        require(
            incident["healthy_since"].is_null() || time(&incident["healthy_since"]) >= opened,
            "S6: healthy time before incident",
        )?;
        if incident["check"] == "watchdog" {
            require(
                incident["needs_you"]["at"] == incident["opened_at"],
                "LP4: immediate notification intent",
            )?;
            watchdog_times(incident, opened)?;
            let op = incident["needs_you"]["op_id"].as_str().unwrap();
            require(
                watchdog_notifications.insert(op, id).is_none(),
                "LP4: notification identity reused",
            )?;
        } else if incident["check"] != "cloudroom" {
            let first = &incident["tries"]["first"];
            let second = &incident["tries"]["second"];
            require(
                second.is_null() || (!first.is_null() && !first["outcome"].is_null()),
                "S3: second try before first outcome",
            )?;
            require(
                second.is_null() || time(&second["at"]) >= time(&first["at"]),
                "S3: try order",
            )?;
            for attempt in [first, second].into_iter().filter(|v| !v.is_null()) {
                require(time(&attempt["at"]) >= opened, "S3: try before incident")?;
                require(
                    attempt["comment"].is_null() || !attempt["outcome"].is_null(),
                    "save outcome before comment",
                )?;
                if matches!(kind, Document::State) && attempt["outcome"]["owner"] == "service_tick"
                {
                    require(
                        retired.is_some_and(|rows| {
                            rows.iter().any(|row| {
                                row["spec"] == incident["spec"]
                                    && row["loop"] == attempt["outcome"]["retired_loop"]
                                    && row["phase"] == "active"
                            })
                        }),
                        "TK1: service takeover requires its active retirement record",
                    )?;
                }
            }
            require(
                incident["needs_you"].is_null()
                    || (!first.is_null()
                        && !second.is_null()
                        && !first["outcome"].is_null()
                        && !second["outcome"].is_null()),
                "S4: Needs you before two outcomes",
            )?;
        }
        if !incident["needs_you"].is_null() {
            require(
                time(&incident["needs_you"]["at"]) >= opened,
                "S6: Needs you before incident",
            )?;
        }
    }
    let mut pending_ids = BTreeSet::new();
    if let Some(deliveries) = value.get("watchdog_deliveries").and_then(Value::as_array) {
        for item in deliveries {
            let id = item["id"].as_str().unwrap();
            let n = id[1..]
                .parse::<u64>()
                .map_err(|_| "invalid watchdog delivery id")?;
            require(
                pending_ids.insert(id),
                "LP4: duplicate pending notification",
            )?;
            if matches!(kind, Document::State) {
                require(
                    n < value["next_incident"].as_u64().unwrap(),
                    "S2: pending notification counter",
                )?;
            }
            require(
                item["needs_you"]["at"] == item["opened_at"],
                "LP4: immediate pending notification",
            )?;
            watchdog_times(item, time(&item["opened_at"]))?;
            let op = item["needs_you"]["op_id"].as_str().unwrap();
            require(
                watchdog_notifications
                    .insert(op, id)
                    .is_none_or(|previous| previous == id),
                "LP4: pending notification identity reused",
            )?;
            if let Some(active) = incidents.iter().find(|i| i["id"] == id) {
                require(active == item, "LP4: pending notification binding")?;
            }
        }
    }
    let pass = &value["last_pass"];
    if !pass.is_null() {
        let mut subjects = BTreeSet::new();
        let mut unread = BTreeSet::new();
        let mut read = BTreeSet::new();
        let results = pass["results"].as_array().unwrap();
        require(
            results.first().is_some_and(|v| v["check"] == "cloudroom"),
            "cloudroom first",
        )?;
        for result in results {
            let check = result["check"].as_str().unwrap();
            if check == "watchdog" {
                let mut problems = BTreeSet::new();
                for problem in result["open"].as_array().unwrap() {
                    require(
                        problems.insert(subject(problem)),
                        "LP4: duplicate open problem",
                    )?;
                    watchdog_times(problem, time(&pass["at"]))?;
                }
                let mut unknown = BTreeSet::new();
                for row in result["unknown"].as_array().unwrap() {
                    require(
                        unknown.insert((
                            row["loop_id"].as_str().unwrap(),
                            row["kind"].as_str().unwrap(),
                        )),
                        "LP4: duplicate unknown category",
                    )?;
                }
                let actual = incidents
                    .iter()
                    .filter(|i| i["check"] == "watchdog")
                    .map(subject)
                    .collect::<BTreeSet<_>>();
                require(problems == actual, "LP4: result and incidents disagree")?;
            }
            if result.get("unread").is_some() {
                require(unread.insert(check), "S1: duplicate unread check")?;
            } else {
                read.insert(check);
                require(subjects.insert(subject(result)), "S1: duplicate result")?;
            }
        }
        require(unread.is_disjoint(&read), "S1: unread check has subjects")?;
        for check in ["cloudroom", "tick", "server"] {
            require(read.contains(check), "S1: missing service check")?;
        }
        let mut fixes = BTreeSet::new();
        for fix in pass["fixes"].as_array().unwrap() {
            let incident = incidents
                .iter()
                .find(|i| i["id"] == fix["incident"])
                .ok_or_else(|| "service document violates S7: missing fix incident".to_owned())?;
            let check = match fix["fix"].as_str().unwrap() {
                "resume_loop" => "loop",
                "restart_tick" => "tick",
                "take_over_fleet_thread" => "fleet_thread",
                "restart_server" => "server",
                _ => unreachable!(),
            };
            require(
                incident["check"] == check && fixes.insert(incident["id"].as_str().unwrap()),
                "S7: mismatched fix incident",
            )?;
            for key in ["loop", "spec", "thread"] {
                require(
                    fix.get(key) == incident.get(key),
                    "S7: mismatched fix subject",
                )?;
            }
            let attempt = if fix["try"] == 1 { "first" } else { "second" };
            require(
                !incident["tries"][attempt].is_null(),
                "S7: missing saved try",
            )?;
        }
        let mut needs = BTreeSet::new();
        for id in pass["needs_you"].as_array().unwrap() {
            require(
                needs.insert(id.as_str().unwrap()),
                "S7: duplicate Needs you",
            )?;
            require(
                incidents
                    .iter()
                    .any(|i| i["id"] == *id && !i["needs_you"].is_null()),
                "S7: missing Needs you incident",
            )?;
        }
    }
    if matches!(kind, Document::Status) && value.get("update_record").is_some() {
        require(
            !value["update"].is_null(),
            "update record requires a saved attempt",
        )?;
    }
    if matches!(kind, Document::Status) && !value["update"].is_null() {
        let field = if value["update"]["outcome"]["state"] == "switched" {
            "to"
        } else {
            "from"
        };
        require(
            value["service"]["build"] == value["update"][field],
            "S8: update and running build disagree",
        )?;
    }
    Ok(())
}

fn subject(value: &Value) -> (String, String) {
    if value.get("loop_id").is_some() {
        return (
            "watchdog".into(),
            serde_json::json!([value["loop_id"], value["broken"]]).to_string(),
        );
    }
    let check = value["check"].as_str().unwrap();
    let id = match check {
        "loop" => value["loop"]["id"].as_str().unwrap().to_owned(),
        "fleet_thread" => value["spec"].to_string(),
        _ => String::new(),
    };
    (check.to_owned(), id)
}

fn watchdog_times(value: &Value, observed: u64) -> Result<(), String> {
    let broken = &value["broken"];
    let valid = match broken["what"].as_str() {
        Some("missed") => broken["due_at_ms"]
            .as_u64()
            .is_some_and(|due| due < observed),
        Some("stuck") => broken["started_at_ms"].as_u64().is_some_and(|start| {
            observed
                .checked_sub(start)
                .is_some_and(|elapsed| elapsed > broken["timeout_ms"].as_u64().unwrap())
        }),
        Some("disabled_by_failures") => true,
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err("LP4: invalid watchdog evidence time".into())
    }
}
