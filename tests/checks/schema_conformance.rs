use std::fs;
use std::path::Path;

use openwiz_core::envelope::{
    Completeness, Counts, Coverage, Envelope, Freshness, Gap, GapKind, SCHEMA_ID, SourceInfo,
};
use openwiz_core::limits::PURPOSE_MAX_CHARS;
use openwiz_core::model::{
    BoundedText, Fact, FinalOutput, Grouping, Inventory, Location, ProjectId, Recap,
    ReportedConfiguration, Session, SessionId, SessionView, Timestamp,
};
use serde_json::{Value, json};

use crate::schema::{lint, load_schema, validate};

const ENVELOPES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/envelopes");

fn envelope_fixtures() -> Vec<(String, Value)> {
    let mut out: Vec<(String, Value)> = fs::read_dir(ENVELOPES)
        .expect("envelopes dir")
        .map(|e| e.expect("entry").path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .map(|p| {
            let text = fs::read_to_string(&p).expect("fixture");
            let name = p.file_name().unwrap().to_string_lossy().into_owned();
            (name, serde_json::from_str(&text).expect("fixture is JSON"))
        })
        .collect();
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

#[test]
fn the_schema_limits_match_the_core_limits() {
    let schema = load_schema();
    let recap_text = &schema["$defs"]["recap"]["oneOf"][0]["properties"]["text"];
    assert_eq!(recap_text["maxLength"], PURPOSE_MAX_CHARS as u64);
    assert_eq!(PURPOSE_MAX_CHARS, 120, "the approved recap length");
}

#[test]
fn the_checker_rejects_missing_and_mistyped_fields() {
    let schema = load_schema();
    let (_, good) = envelope_fixtures()
        .into_iter()
        .find(|(n, _)| n == "ls-long-complete.json")
        .expect("ls-long-complete.json");
    type Mutation = (&'static str, fn(&mut Value));
    let mutations: [Mutation; 8] = [
        ("missing coverage", |v| {
            v.as_object_mut().unwrap().remove("coverage");
        }),
        ("wrong schema id", |v| {
            v["schema"] = json!("openwiz.inventory.v2")
        }),
        ("status not a fact", |v| {
            v["data"]["sessions"][0]["status"] = json!("idle")
        }),
        ("age as a string", |v| {
            v["data"]["sessions"][0]["age_ms"] = json!({"known": "60s"})
        }),
        ("an empty unknown reason", |v| {
            v["data"]["sessions"][0]["title"] = json!({"unknown": ""})
        }),
        ("unknown without reason", |v| {
            v["data"]["sessions"][0]["title"] = json!({"unknown": null})
        }),
        ("an unexpected field on a session", |v| {
            v["data"]["sessions"][0]["model"] = json!({"known": "synthetic-model-a"})
        }),
        ("recap over 120 characters", |v| {
            v["data"]["sessions"][0]["recap"]["known"]["text"] = json!("Synthetic ".repeat(13))
        }),
    ];
    for (what, mutate) in mutations {
        let mut bad = good.clone();
        mutate(&mut bad);
        assert!(
            !validate(&schema, &bad).is_empty(),
            "the checker accepted: {what}"
        );
    }
}

fn sample_session(n: u32) -> Session {
    Session {
        id: SessionId(format!("thr_syn_{n:04}")),
        title: Fact::Known(format!("Synthetic session {n}")),
        provider: Fact::Known("codex".to_owned()),
        status: Fact::Unknown("not reported by room-cli: status is missing".to_owned()),
        location: Fact::Known(Location::Local {
            machine: Fact::Unknown("host is not in the machine list".to_owned()),
        }),
        group: Grouping::Project {
            id: ProjectId("prj_syn_0001".to_owned()),
            name: Fact::Known("Synthetic project one".to_owned()),
        },
        parent: Fact::Known(Some(SessionId("thr_syn_0001".to_owned()))),
        hidden: Fact::Known(false),
        archived: Fact::Unknown("archivedAt has the wrong type".to_owned()),
        recap: Fact::Known(Recap::PurposeAsReported(BoundedText {
            text: "Synthetic purpose.".to_owned(),
            truncated: false,
        })),
        reported_configuration: ReportedConfiguration {
            model: Fact::Known("synthetic-model-a".to_owned()),
            effort: Fact::Unknown("not read: ls without -l".to_owned()),
        },
        updated_at: Fact::Known(Timestamp(1_700_000_000_000)),
        age_ms: Fact::Known(60_000),
        started_at: Fact::Known(Timestamp(1_699_999_000_000)),
    }
}

const EVERY_GAP_KIND: [GapKind; 8] = [
    GapKind::UntestedVersion,
    GapKind::CommandFailed,
    GapKind::TimedOut,
    GapKind::BudgetExhausted,
    GapKind::Malformed,
    GapKind::MissingField,
    GapKind::WrongType,
    GapKind::NotFound,
];

fn sample_envelope<T>(data: T, counts: Option<Counts>) -> Envelope<T> {
    Envelope {
        schema: SCHEMA_ID.to_owned(),
        source: SourceInfo {
            name: "room-cli".to_owned(),
            version: Fact::Unknown("room-cli --version timed out".to_owned()),
            tested_version: "v127".to_owned(),
            version_tested: false,
        },
        coverage: Coverage {
            state: Completeness::Partial,
            counts,
        },
        freshness: Freshness {
            snapshot_at: Timestamp(1_700_000_600_000),
        },
        gaps: EVERY_GAP_KIND
            .iter()
            .map(|&kind| Gap {
                kind,
                subject: Some("thr_syn_0001".to_owned()),
                detail: "Synthetic gap".to_owned(),
            })
            .collect(),
        data,
    }
}

#[test]
fn the_core_types_serialize_to_schema_valid_json() {
    let schema = load_schema();
    assert_eq!(schema["title"], SCHEMA_ID);
    assert_eq!(lint(&schema), Vec::<String>::new());
    let mut no_recap = sample_session(2);
    no_recap.recap = Fact::Known(Recap::NoRecapYet);
    no_recap.location = Fact::Known(Location::Cloud);
    no_recap.group = Grouping::Ungrouped {
        reason: "Synthetic reason".to_owned(),
    };
    no_recap.parent = Fact::Known(None);
    let list = sample_envelope(
        Inventory {
            sessions: vec![sample_session(1), no_recap.clone()],
        },
        Some(Counts {
            listed: 2,
            unreadable: 0,
            excluded_hidden: 0,
            excluded_archived: 0,
            hidden_read: true,
            archived_read: false,
            matched: 2,
            offset: 0,
            limit: 50,
            shown: 2,
        }),
    );
    let shows = [
        SessionView {
            session: sample_session(1),
            final_output: Fact::Known(FinalOutput::Reported(BoundedText {
                text: "Synthetic output".to_owned(),
                truncated: true,
            })),
            reported_error: Fact::Known(Some(BoundedText {
                text: "Synthetic error".to_owned(),
                truncated: false,
            })),
        },
        SessionView {
            session: no_recap,
            final_output: Fact::Known(FinalOutput::NoFinalOutputYet),
            reported_error: Fact::Known(None),
        },
        SessionView {
            session: sample_session(3),
            final_output: Fact::Unknown("thread output failed".to_owned()),
            reported_error: Fact::Unknown("thread output failed".to_owned()),
        },
    ];
    let mut complete = list.clone();
    complete.coverage.state = Completeness::Complete;
    complete.gaps.clear();
    let mut values = vec![
        serde_json::to_value(&list).unwrap(),
        serde_json::to_value(&complete).unwrap(),
    ];
    for show in shows {
        values.push(serde_json::to_value(sample_envelope(show, None)).unwrap());
    }
    for value in values {
        let errors = validate(&schema, &value);
        assert!(errors.is_empty(), "{errors:#?}\n{value:#}");
    }
    assert!(Path::new(crate::schema::SCHEMA_PATH).is_file());
}

#[path = "../fleet/schema.rs"]
mod fleet_schema;

#[test]
fn validators_reject_bad_unicode_escapes_invalid_range_bounds_and_cyclic_refs() {
    let plus_escape = json!({"type": "string", "pattern": "^[\\u+00A]$"});
    assert!(
        !lint(&plus_escape).is_empty(),
        "support/schema.rs accepted \\u+00A"
    );
    assert!(
        !crate::pattern::lint(&plus_escape).is_empty(),
        "new-thread/pattern.rs accepted \\u+00A"
    );

    for bad_range in ["^[0-\\]$", "^[0-[]$", "^[0-^]$", "^[a-[]*$"] {
        let s = json!({"type": "string", "pattern": bad_range});
        assert!(
            !lint(&s).is_empty(),
            "support/schema.rs accepted {bad_range}"
        );
        assert!(
            !fleet_schema::lint(&s).is_empty(),
            "fleet/schema.rs accepted {bad_range}"
        );
        assert!(
            !crate::pattern::lint(&s).is_empty(),
            "new-thread/pattern.rs accepted {bad_range}"
        );
    }

    let cyclic = json!({
        "$defs": { "a": { "$ref": "#/$defs/a" } },
        "$ref": "#/$defs/a"
    });
    assert!(
        !lint(&cyclic).is_empty(),
        "support/schema.rs accepted cyclic $ref"
    );
    assert!(
        !fleet_schema::lint(&cyclic).is_empty(),
        "fleet/schema.rs accepted cyclic $ref"
    );
    assert!(
        !crate::pattern::lint(&cyclic).is_empty(),
        "new-thread/pattern.rs accepted cyclic $ref"
    );
    assert!(!validate(&cyclic, &json!({})).is_empty());
    assert!(!fleet_schema::validate(&cyclic, &json!({})).is_empty());
    assert!(!crate::pattern::validate(&cyclic, &json!({})).is_empty());
}

#[test]
fn repeated_star_patterns_match_without_exponential_backtracking() {
    let pat = "^a*a*a*a*a*a*a*a*a*a*a*a*b$";
    let schema = json!({"type": "string", "pattern": pat});
    let value = json!("a".repeat(14));
    let started = std::time::Instant::now();
    assert!(!validate(&schema, &value).is_empty());
    assert!(!fleet_schema::validate(&schema, &value).is_empty());
    assert!(!crate::pattern::validate(&schema, &value).is_empty());
    assert!(
        started.elapsed() < std::time::Duration::from_millis(50),
        "repeated star matching took {:?}",
        started.elapsed()
    );
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }

    fn usize(&mut self, upper: usize) -> usize {
        (self.next_u64() as usize) % upper
    }
}

fn gen_pattern(rng: &mut SplitMix64, allow_neg_and_escape: bool) -> String {
    let literals = ['a', 'b', '0', '1', '_', '-'];
    let count = 1 + rng.usize(4);
    let mut pat = String::from("^");
    for _ in 0..count {
        match rng.usize(3) {
            0 => pat.push(literals[rng.usize(literals.len())]),
            1 => {
                pat.push('[');
                if allow_neg_and_escape && rng.usize(3) == 0 {
                    pat.push('^');
                }
                let items = 1 + rng.usize(3);
                for _ in 0..items {
                    match rng.usize(3) {
                        0 => pat.push_str("a-b"),
                        1 if allow_neg_and_escape => pat.push_str("\\u0030-\\u0032"),
                        _ => pat.push(literals[rng.usize(literals.len() - 1)]),
                    }
                }
                if allow_neg_and_escape && rng.usize(4) == 0 {
                    pat.push('-');
                }
                pat.push(']');
            }
            _ => {
                if allow_neg_and_escape {
                    pat.push_str("\\u0061");
                } else {
                    pat.push('a');
                }
            }
        }
        if rng.usize(2) == 0 {
            pat.push('*');
        }
    }
    pat.push('$');
    pat
}

fn gen_text(rng: &mut SplitMix64) -> String {
    let alphabet = ['a', 'b', 'c', '0', '1', '2', '_', '-', '\u{00e9}'];
    let len = rng.usize(8);
    (0..len)
        .map(|_| alphabet[rng.usize(alphabet.len())])
        .collect()
}

#[test]
fn linear_pattern_matchers_agree_with_previous_recursive_oracles() {
    let curated_text_rule = [
        "^$",
        "^a*$",
        "^[^a-b]*a[^0-9]*$",
        "^[a-z0-9_-]*$",
        "^[\\u0020-\\u007e]*$",
        "^a*b*a*$",
        "^[ab-]*b$",
    ];
    let curated_fleet = [
        "^$",
        "^a*$",
        "^[-a-z0-9_]*$",
        "^a*b*a*$",
        "^[-ab]*b$",
        "^a[a-b]*b$",
    ];
    let samples = ["", "a", "b", "ab", "aba", "a-b_0", "xyz", "\n", "\u{00e9}"];

    for pat in curated_text_rule {
        for text in samples {
            let (new_s, old_s) = crate::schema::text_rule_oracle_matches(pat, text);
            assert_eq!(
                new_s, old_s,
                "support/schema mismatch on {pat:?} / {text:?}"
            );
            let (new_p, old_p) = crate::pattern::pattern_oracle_matches(pat, text);
            assert_eq!(
                new_p, old_p,
                "new-thread/pattern mismatch on {pat:?} / {text:?}"
            );
            assert_eq!(
                new_s, new_p,
                "cross-validator mismatch on {pat:?} / {text:?}"
            );
        }
    }
    for pat in curated_fleet {
        for text in samples {
            let (new_f, old_f) = fleet_schema::pattern_oracle_matches(pat, text);
            assert_eq!(new_f, old_f, "fleet/schema mismatch on {pat:?} / {text:?}");
        }
    }

    let mut rng = SplitMix64(0x0003_6430_0000_0001);
    for _ in 0..400 {
        let pat = gen_pattern(&mut rng, true);
        let fpat = gen_pattern(&mut rng, false);
        for _ in 0..8 {
            let text = gen_text(&mut rng);
            let (new_s, old_s) = crate::schema::text_rule_oracle_matches(&pat, &text);
            assert_eq!(
                new_s, old_s,
                "support/schema mismatch on {pat:?} / {text:?}"
            );
            let (new_p, old_p) = crate::pattern::pattern_oracle_matches(&pat, &text);
            assert_eq!(
                new_p, old_p,
                "new-thread/pattern mismatch on {pat:?} / {text:?}"
            );
            let (new_f, old_f) = fleet_schema::pattern_oracle_matches(&fpat, &text);
            assert_eq!(new_f, old_f, "fleet/schema mismatch on {fpat:?} / {text:?}");
        }
    }
}

#[test]
fn pattern_validate_agrees_with_previous_validate_on_contract_schemas() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let loops_schema: Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("contracts/loops.v1.schema.json")).unwrap(),
    )
    .unwrap();
    let loops_example: Value =
        serde_json::from_str(&std::fs::read_to_string(root.join("loops/example.json")).unwrap())
            .unwrap();

    let mut bad_pattern = loops_example.clone();
    bad_pattern["name"] = json!("bad\nname");
    let mut bad_variant = loops_example.clone();
    bad_variant["trigger"] = json!({"kind": "unknown"});
    let mut dup_items = loops_example.clone();
    if let Some(arr) = dup_items.get_mut("tags").and_then(Value::as_array_mut)
        && let Some(first) = arr.first().cloned()
    {
        arr.push(first);
    }

    for candidate in [
        loops_example,
        bad_pattern,
        bad_variant,
        dup_items,
        json!({}),
        json!(null),
    ] {
        assert_eq!(
            crate::pattern::validate(&loops_schema, &candidate),
            crate::pattern::previous_validate(&loops_schema, &candidate),
            "pattern::validate diverged on {candidate}"
        );
    }
}

#[test]
#[ignore = "opt-in seeded soak fuzz test for schema validators"]
fn fuzz_schema_validators_seeded_soak() {
    let mut rng = SplitMix64(0x5eed_cafe_1234_5678);
    let chars = [
        '^', '$', '[', ']', '-', '\\', 'u', '+', '0', '9', 'a', 'z', '*', '?', '.', '(', ')',
    ];
    for _ in 0..25_000 {
        let len = rng.usize(18);
        let pat: String = (0..len).map(|_| chars[rng.usize(chars.len())]).collect();
        let schema = json!({"type": "string", "pattern": pat});
        let text = gen_text(&mut rng);
        let val = Value::String(text);
        if lint(&schema).is_empty() {
            let _ = validate(&schema, &val);
        }
        if fleet_schema::lint(&schema).is_empty() {
            let _ = fleet_schema::validate(&schema, &val);
        }
        if crate::pattern::lint(&schema).is_empty() {
            let _ = crate::pattern::validate(&schema, &val);
        }
    }
}
