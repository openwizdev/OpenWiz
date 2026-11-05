//! LP1 is a safety fuse solely on loop checks and original loop agents.
//! These capacities do not govern fleet work or descendants. This module
//! neither opens configuration files nor registers runtime jobs (L12).
use openwiz_core::loops::{Capacity, Limits};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use std::{fmt, io::Read};

/// Read required `loops.limits` from supplied `service/config.json` bytes.
/// The caller owns protected file access and enclosing config validation.
/// No input value is included in diagnostics. Errors supply no capacities;
/// callers must hold loop admission, never substitute defaults.
pub fn read(config: impl Read) -> Result<Limits, String> {
    let mut decoder = serde_json::Deserializer::from_reader(config);
    let Strict(config) = Strict::deserialize(&mut decoder)
        .map_err(|_| "loop limits require readable strict JSON without duplicate fields")?;
    decoder
        .end()
        .map_err(|_| "loop limits require one complete JSON document")?;
    let limits = config
        .as_object()
        .and_then(|c| c.get("loops"))
        .and_then(Value::as_object)
        .and_then(|l| l.get("limits"))
        .ok_or("required loops.limits record is absent or malformed")?;
    let record = exact(limits, &["checks", "agents"])?;
    let limits = Limits {
        checks: capacity(&record["checks"])?,
        agents: capacity(&record["agents"])?,
    };
    // This is an approved policy, not a default or a configurable fleet ceiling.
    // A structurally valid different policy still requires explicit approval.
    if limits.checks
        != (Capacity {
            max: 4,
            urgent_reserve: 1,
        })
        || limits.agents
            != (Capacity {
                max: 16,
                urgent_reserve: 4,
            })
    {
        return Err("loop capacities differ from approved LP1 policy".into());
    }
    Ok(limits)
}
fn exact<'a>(value: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>, String> {
    value
        .as_object()
        .filter(|map| map.len() == keys.len() && keys.iter().all(|key| map.contains_key(*key)))
        .ok_or_else(|| "loop limits require exactly the declared record fields".into())
}
fn capacity(value: &Value) -> Result<Capacity, String> {
    let fields = exact(value, &["max", "urgent_reserve"])?;
    let integer = |key| {
        fields[key]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .ok_or_else(|| "loop capacity fields must be unsigned integers in range".to_owned())
    };
    let capacity = Capacity {
        max: integer("max")?,
        urgent_reserve: integer("urgent_reserve")?,
    };
    if capacity.urgent_reserve > capacity.max {
        return Err("loop urgent reserve exceeds its total capacity".into());
    }
    Ok(capacity)
}

// Retain service JSON integer syntax and reject duplicates before constructing
// a map, including at the enclosing config/loops levels and in other records.
// Full service-config schema validation remains with L12's composition.
struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
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
        decoder.deserialize_any(StrictVisitor)
    }
}
