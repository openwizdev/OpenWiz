use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};
use std::fmt;

pub(crate) fn parse(bytes: &[u8], refuse_fraction: bool) -> Result<Value, serde_json::Error> {
    if refuse_fraction {
        serde_json::from_slice::<Once<true>>(bytes).map(|once| once.0)
    } else {
        serde_json::from_slice::<Once<false>>(bytes).map(|once| once.0)
    }
}

struct Once<const REFUSE_FRACTION: bool>(Value);

impl<'de, const REFUSE_FRACTION: bool> Deserialize<'de> for Once<REFUSE_FRACTION> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer
            .deserialize_any(OnceVisitor::<REFUSE_FRACTION>)
            .map(Once)
    }
}

struct OnceVisitor<const REFUSE_FRACTION: bool>;

impl<'de, const REFUSE_FRACTION: bool> Visitor<'de> for OnceVisitor<REFUSE_FRACTION> {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("JSON with no key given twice")
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        if REFUSE_FRACTION {
            return Err(E::custom("a fractional number"));
        }
        Ok(serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_none<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut out = Vec::new();
        while let Some(Once::<REFUSE_FRACTION>(value)) = seq.next_element()? {
            out.push(value);
        }
        Ok(Value::Array(out))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut out = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if out.contains_key(&key) {
                return Err(de::Error::custom("a key given twice"));
            }
            let Once::<REFUSE_FRACTION>(value) = map.next_value()?;
            out.insert(key, value);
        }
        Ok(Value::Object(out))
    }
}

#[cfg(test)]
pub(crate) mod oracle {
    use super::parse;
    use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
    use serde_json::Value;
    use std::fmt;

    #[derive(Debug, PartialEq, Eq)]
    pub(crate) enum Pass {
        First,
        Second,
    }

    pub(crate) fn two_pass(refuse_fraction: bool, bytes: &[u8]) -> Result<Value, Pass> {
        if refuse_fraction {
            serde_json::from_slice::<openwiz_core::new_thread::read::StrictJson>(bytes)
                .map_err(|_| Pass::First)?;
        } else {
            serde_json::from_slice::<OldKeysOnce>(bytes).map_err(|_| Pass::First)?;
        }
        serde_json::from_slice(bytes).map_err(|_| Pass::Second)
    }

    pub(crate) fn samples() -> Vec<Vec<u8>> {
        let mut out = vec![
            b"null".to_vec(),
            b"true".to_vec(),
            b"false".to_vec(),
            b"0".to_vec(),
            b"-0".to_vec(),
            b"1".to_vec(),
            b"-1".to_vec(),
            b"9223372036854775807".to_vec(),
            b"9223372036854775808".to_vec(),
            b"1.5".to_vec(),
            b"0.0".to_vec(),
            b"1e2".to_vec(),
            b"1e+2".to_vec(),
            br#""""#.to_vec(),
            br#""cafe""#.to_vec(),
            br#""line\n\t\"\\\/\u0041""#.to_vec(),
            b"[]".to_vec(),
            b"{}".to_vec(),
            br#"{"b":1,"a":2,"c":[null,false,"z"]}"#.to_vec(),
            br#"{"a":1,"a":2}"#.to_vec(),
            br#"{"a":{"b":1,"b":2}}"#.to_vec(),
            br#"[1,{"a":1,"a":2}]"#.to_vec(),
            b"".to_vec(),
            b"{".to_vec(),
            b"[".to_vec(),
            br#"{"a":1,}"#.to_vec(),
            b"01".to_vec(),
            br#""\uD800""#.to_vec(),
            b"1 2".to_vec(),
        ];
        let mut rng = Rng(0x0e12_5a11);
        for _ in 0..240 {
            out.push(rng.json(0));
        }
        out
    }

    struct Rng(u64);

    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 = self
                .0
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            self.0
        }

        fn below(&mut self, bound: usize) -> usize {
            (self.next() as usize) % bound
        }

        fn json(&mut self, depth: u32) -> Vec<u8> {
            let kind = if depth >= 4 {
                self.below(4)
            } else {
                self.below(7)
            };
            match kind {
                0 => b"null".to_vec(),
                1 => {
                    if self.below(2) == 0 {
                        b"true".to_vec()
                    } else {
                        b"false".to_vec()
                    }
                }
                2 => self.next().to_string().into_bytes(),
                3 => format!("\"{}\"", self.word()).into_bytes(),
                4 => {
                    let n = self.below(4);
                    let mut out = b"[".to_vec();
                    for i in 0..n {
                        if i != 0 {
                            out.push(b',');
                        }
                        out.extend(self.json(depth + 1));
                    }
                    out.push(b']');
                    out
                }
                _ => {
                    let n = self.below(5);
                    let mut out = b"{".to_vec();
                    let mut first_key = None;
                    for i in 0..n {
                        if i != 0 {
                            out.push(b',');
                        }
                        let key = self.word();
                        if first_key.is_none() {
                            first_key = Some(key.clone());
                        }
                        let key = if i > 0 && self.below(6) == 0 {
                            first_key.clone().unwrap_or(key)
                        } else {
                            key
                        };
                        out.push(b'"');
                        out.extend(key.as_bytes());
                        out.extend(br#"":"#);
                        out.extend(self.json(depth + 1));
                    }
                    out.push(b'}');
                    out
                }
            }
        }

        fn word(&mut self) -> String {
            let alphabet = b"abcdefghij";
            let n = 1 + self.below(6);
            (0..n)
                .map(|_| alphabet[self.below(alphabet.len())] as char)
                .collect()
        }
    }

    struct OldKeysOnce;

    impl<'de> Deserialize<'de> for OldKeysOnce {
        fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
            deserializer.deserialize_any(OldVisitor).map(|()| Self)
        }
    }

    struct OldVisitor;

    impl<'de> Visitor<'de> for OldVisitor {
        type Value = ();

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("JSON with no key given twice")
        }

        fn visit_bool<E: de::Error>(self, _: bool) -> Result<(), E> {
            Ok(())
        }

        fn visit_i64<E: de::Error>(self, _: i64) -> Result<(), E> {
            Ok(())
        }

        fn visit_u64<E: de::Error>(self, _: u64) -> Result<(), E> {
            Ok(())
        }

        fn visit_f64<E: de::Error>(self, _: f64) -> Result<(), E> {
            Ok(())
        }

        fn visit_str<E: de::Error>(self, _: &str) -> Result<(), E> {
            Ok(())
        }

        fn visit_unit<E: de::Error>(self) -> Result<(), E> {
            Ok(())
        }

        fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<(), A::Error> {
            while seq.next_element::<OldKeysOnce>()?.is_some() {}
            Ok(())
        }

        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
            let mut seen = std::collections::BTreeSet::new();
            while let Some(key) = map.next_key::<String>()? {
                if !seen.insert(key) {
                    return Err(de::Error::custom("a key given twice"));
                }
                map.next_value::<OldKeysOnce>()?;
            }
            Ok(())
        }
    }

    #[test]
    fn one_pass_matches_the_two_pass_reader() {
        let mut second = 0;
        for refuse in [false, true] {
            for bytes in samples() {
                let old = two_pass(refuse, &bytes);
                let new = parse(&bytes, refuse);
                match old {
                    Ok(value) => assert_eq!(new.as_ref().ok(), Some(&value), "{refuse} {bytes:?}"),
                    Err(Pass::First) => {
                        assert!(new.is_err(), "{refuse} {bytes:?}");
                    }
                    Err(Pass::Second) => {
                        second += 1;
                        assert!(new.is_err(), "{refuse} {bytes:?}");
                    }
                }
            }
        }
        assert_eq!(second, 0, "a second parse refused bytes the first accepted");
    }
}
