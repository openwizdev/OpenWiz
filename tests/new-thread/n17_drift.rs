//! N17: drift. An unexpected receipt shape gives uncertain with a gap; an
//! unexpected catalogue shape gives no options. The version is reported,
//! never a gate (#37): the draft's "an untested version means nothing is
//! created" is dropped (sheet, "Already decided").

use openwiz_adapter_cloudroom::new_thread::{parse_catalogue, spawn_receipt};
use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::model::Fact;
use openwiz_core::new_thread::operation::{NewThreadClient, NewThreadResult};
use openwiz_core::new_thread::outcome::{Outcome, RefusalReason, SpawnReply, Status};
use openwiz_core::source::{SessionSource, SourceError};
use serde_json::json;

use crate::fake::{NewFake, json_of, new_args};
use crate::support::*;

#[test]
fn n17_drift_affected_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 4] = [
        (
            "an_unexpected_catalogue_gives_no_options_and_no_call",
            an_unexpected_catalogue_gives_no_options_and_no_call,
        ),
        (
            "an_unexpected_receipt_is_uncertain_with_a_gap",
            an_unexpected_receipt_is_uncertain_with_a_gap,
        ),
        (
            "an_untested_or_unreadable_version_is_reported_never_a_gate",
            an_untested_or_unreadable_version_is_reported_never_a_gate,
        ),
        (
            "the_schema_says_new_has_its_own_tested_version",
            the_schema_says_new_has_its_own_tested_version,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n17_drift::{name}");
        proof();
    }
}

fn an_unexpected_receipt_is_uncertain_with_a_gap() {
    for (file, reason) in [
        (
            "spawn-receipt-drift-no-id.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "spawn-receipt-drift-other-project.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "spawn-receipt-drift-unsafe-id.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "spawn-receipt-drift-array.json",
            UncertainReason::UnexpectedReceipt,
        ),
        ("spawn-receipt-not-json.txt", UncertainReason::NotJson),
    ] {
        let reply = spawn_receipt(&fixture(file), "prj_syn_0001");
        let SpawnReply::Unclear { reason: got, gaps } = &reply else {
            panic!("{file}: {reply:?}")
        };
        assert_eq!(*got, reason, "{file}");
        assert_eq!(gaps.len(), 1, "{file}");
        let client = FakeClient::answering(SpawnAnswer::Receipt(file));
        let store = MemoryStore::new();
        let report = create(
            &client,
            &store,
            &request(offered(), "Synthetic", "op-n17-r"),
        );
        assert_eq!(report.status, Status::Uncertain, "{file}");
        assert!(!report.gaps.is_empty(), "{file}: a gap");
        let json = serde_json::to_string(&report).unwrap();
        for echoed in ["prj_syn_0002", "Synthetic receipt", "Synthetic unsafe id"] {
            assert!(!json.contains(echoed), "{file}: {echoed} echoed");
        }
    }
}

fn an_unexpected_catalogue_gives_no_options_and_no_call() {
    for file in [
        "cloud-status-drift-ready-not-bool.json",
        "cloud-status-drift-models-object.json",
        "cloud-status-drift-levels-not-list.json",
        "cloud-status-drift-array.json",
    ] {
        assert!(
            matches!(
                parse_catalogue(&fixture(file)),
                Err(SourceError::Malformed { .. })
            ),
            "{file}"
        );
        let client = FakeClient::with_catalogue(file);
        let store = MemoryStore::new();
        let report = create(
            &client,
            &store,
            &request(offered(), "Synthetic", "op-n17-c"),
        );
        let NewThreadResult::Outcome {
            outcome: Outcome::Refused { reason, .. },
            ..
        } = &report.result
        else {
            panic!("{file}: {report:?}")
        };
        assert_eq!(*reason, RefusalReason::NoOptions, "{file}");
        assert_eq!(client.spawns(), 0, "{file}");
    }
}

fn an_untested_or_unreadable_version_is_reported_never_a_gate() {
    for version in [
        Ok("v999".to_owned()),
        Ok("Synthetic".to_owned()),
        Err(SourceError::TimedOut { after_ms: 15_000 }),
    ] {
        let mut client = FakeClient::new();
        client.version = version.clone();
        let store = MemoryStore::new();
        let report = create(
            &client,
            &store,
            &request(offered(), "Synthetic", "op-n17-v"),
        );
        assert_eq!(report.status, Status::Created, "{version:?}");
        assert_eq!(client.spawns(), 1, "{version:?}");
        let source = report.source.expect("reported");
        assert!(!source.version_tested, "{version:?}");
        if version.is_err() || version == Ok("Synthetic".to_owned()) {
            assert!(matches!(source.version, Fact::Unknown(_)));
            assert!(!report.gaps.is_empty(), "{version:?}: a gap");
        }
    }
}

/// The new-thread schema, read from the repository.
fn new_thread_schema() -> serde_json::Value {
    serde_json::from_str(&std::fs::read_to_string(SCHEMA).expect("schema")).expect("JSON")
}

/// The `source:` lines of a text report.
fn source_lines(out: &str) -> Vec<&str> {
    out.lines().filter(|l| l.starts_with("source: ")).collect()
}

/// #200 (the 0.0.3 export review's R1; the orchestrator's Q1 (a), Q2 (a)):
/// v127 was live-tested for the reads only, and no create has ever run
/// live. One `room-cli` source answers the reads with their own tested
/// version and `new` with its own, which is none.
#[test]
fn new_has_its_own_tested_version_never_the_reads() {
    let fake = NewFake::new("n17_own_tested_version");
    let (code, out, err) = fake.cli(&["ls"], "");
    assert_eq!(code, 0, "{err}");
    let header = out.lines().next().unwrap_or_default();
    assert!(
        header.starts_with("openwiz ls · room-cli v127 (tested) · snapshot "),
        "the reads are unchanged:\n{out}"
    );
    let source = fake.source();
    assert_eq!(SessionSource::tested_version(&source), "v127", "the reads'");
    assert_eq!(
        NewThreadClient::tested_version(&source),
        "",
        "new's: none yet"
    );
}

/// #200: `new` at v127, the version the reads were live-tested with, says
/// its version is not live-tested for new threads, in its preview and its
/// report, as text and JSON, in its record and in the release program's
/// `--json`; never `(tested)`.
#[test]
fn a_new_thread_at_the_reads_tested_version_is_not_live_tested_for_new_threads() {
    let not_tested = json!({"name": "room-cli", "version": {"known": "v127"}, "tested_version": "", "version_tested": false});
    let line = vec!["source: room-cli v127 (not live-tested for new threads)"];
    let fake = NewFake::new("n17_not_live_tested");
    let preview = [
        "new",
        "Synthetic project one",
        "--harness",
        "codex",
        "--model",
        "syn-codex-model-01",
        "--effort",
        "high",
        "--op-id",
        "op-n17-p",
        "--",
        "Synthetic preview",
    ];
    let (_, out, err) = fake.cli(&preview, "");
    assert_eq!(
        source_lines(&out),
        line,
        "the preview's text:\n{out}\n{err}"
    );
    let (_, json) = fake.cli_json(&preview, "");
    assert_eq!(json["source"], not_tested, "the preview's JSON");
    assert_eq!(validate_def("preview", &json), Vec::<String>::new());

    let create = new_args("Synthetic project one", "op-n17-t", &[], "Synthetic");
    let (code, out, err) = fake.cli(&create, "");
    assert_eq!(code, 0, "{out}\n{err}");
    assert_eq!(source_lines(&out), line, "the report's text:\n{out}");
    assert!(!out.contains("tested)"), "{out}");
    assert_eq!(fake.record("op-n17-t")["source"], not_tested, "the record");
    let (_, json) = fake.cli_json(&create, "");
    assert_eq!(json["source"], not_tested, "the report's JSON (a replay)");
    assert_eq!(validate_def("report", &json), Vec::<String>::new());

    let release = new_args(
        "Synthetic project one",
        "op-n17-t2",
        &["--json"],
        "Synthetic two",
    );
    let (code, json) = json_of(&fake.run_process(&release, ""));
    assert_eq!(code, Some(0), "{json}");
    assert_eq!(json["source"], not_tested, "the release program");
}

/// #200: the contract says the same as the report: `tested_version` is
/// new's own, empty while no live create has passed, never the reads'.
fn the_schema_says_new_has_its_own_tested_version() {
    let schema = new_thread_schema();
    let source = &schema["$defs"]["source"];
    assert_eq!(
        source["description"],
        "The provider and the version this create read (#37: the version is never a gate). \
         tested_version is new's own: the room-cli version a live create last passed with, \
         or \"\" while none has (#200). It is never the reads' live-tested version in \
         openwiz.inventory.v1. version_tested is true only when version is known and \
         equals it. Evidence, not a requirement."
    );
    assert_eq!(
        source["properties"]["tested_version"],
        json!({"type": "string"})
    );
}
