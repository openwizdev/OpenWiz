//! M13 Drift: an unexpected receipt shape gives uncertain with a gap, never
//! accepted. Since #37 the `room-cli` version is never a gate: it is
//! reported, and the send goes on.

use openwiz_cli::send::EXIT_IN_PROGRESS;
use openwiz_core::messaging::Mode;
use openwiz_core::messaging::send::{Delivery, Messenger, Status, UncertainReason};
use openwiz_core::source::SessionSource;

use serde_json::{Value, json};

use crate::m04_outcome_mapping::{delivery, uncertain_reason};
use crate::support::*;

#[test]
fn an_unexpected_receipt_is_uncertain_with_a_gap() {
    // Each row has its own fake, so the rows run at once (#1260).
    let rows = vec![
        (
            "tell-drift-extra-field.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "tell-drift-unknown-delivery.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "tell-drift-unknown-waiting-kind.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "tell-drift-no-queued-message.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "tell-drift-unsafe-queued-id.json",
            UncertainReason::UnexpectedReceipt,
        ),
        (
            "tell-drift-delivery-not-string.json",
            UncertainReason::UnexpectedReceipt,
        ),
        ("tell-drift-array.json", UncertainReason::UnexpectedReceipt),
        ("tell-not-json.txt", UncertainReason::NotJson),
    ];
    at_once(rows, |(file, reason)| {
        let fake = SendFake::with(
            &format!("m13_{file}"),
            vec![tell_response("thr_syn_0001", "queue", receipt(file))],
        );
        let report = fake.report(&request("thr_syn_0001", Mode::Queue, "Synthetic", "op-m13"));
        assert_eq!(report.status, Status::Uncertain, "{file}: {report:#?}");
        assert_eq!(uncertain_reason(&report), reason, "{file}");
        assert!(
            report.gaps.iter().any(|g| g.subject == "thread tell"),
            "{file}: a gap names the receipt: {:#?}",
            report.gaps
        );
        assert!(!matches!(delivery(&report), Delivery::Accepted { .. }));
        let record = fake.record("op-m13");
        assert_eq!(record["delivery"]["kind"], "uncertain", "{file}");
        assert!(!record["gaps"].as_array().unwrap().is_empty(), "{file}");
    });
}

/// A `send` fake whose `room-cli --version` gives `answer` (an inline
/// stdout, or an exit with stderr); every other answer is the `send`
/// scenario's.
fn with_version(test: &str, answer: Value) -> SendFake {
    let mut response = json!({"argv": ["--version"]});
    for (k, v) in answer.as_object().expect("an object") {
        response[k] = v.clone();
    }
    SendFake::with(test, vec![response])
}

/// The report's `source`, as JSON.
fn source_of(report: &openwiz_core::messaging::send::SendReport) -> Value {
    serde_json::to_value(report).expect("report JSON")["source"].clone()
}

/// The `source:` lines of a text report.
fn source_lines(out: &str) -> Vec<&str> {
    out.lines().filter(|l| l.starts_with("source: ")).collect()
}

/// #200 (the 0.0.3 export review's R1; approved by Jake, 2026-11-01):
/// [private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036).
/// v127 was live-tested for the reads only, and no send has ever run live.
/// One `room-cli` source answers the reads with their own tested version and
/// `send` with its own, which is none until 0.0.3's live test passes.
#[test]
fn send_has_its_own_tested_version_never_the_reads() {
    let source = SendFake::new("m13_own_tested_version", "send").source();
    assert_eq!(SessionSource::tested_version(&source), "v127", "the reads'");
    assert_eq!(Messenger::tested_version(&source), "", "send's: none yet");
}

/// #200: a send at v127, the version the reads were live-tested with, says
/// its version is not live-tested for sending, in its report, its record,
/// its text and the release program's `--json`; never `(tested)`.
#[test]
fn a_send_at_the_reads_tested_version_is_not_live_tested_for_sending() {
    let not_tested = json!({"name": "room-cli", "version": {"known": "v127"}, "tested_version": "", "version_tested": false});
    let fake = SendFake::new("m13_not_live_tested", "send");
    let report = fake.report(&request(
        "thr_syn_0001",
        Mode::Queue,
        "Synthetic",
        "op-m13-t",
    ));
    assert_eq!(source_of(&report), not_tested, "the report");
    assert_eq!(fake.record("op-m13-t")["source"], not_tested, "the record");
    let report = serde_json::to_value(&report).unwrap();
    assert_eq!(validate_report(&report), Vec::<String>::new(), "the schema");

    let (code, out, err) = fake.cli(
        &[
            "thr_syn_0002",
            "--op-id",
            "op-m13-t2",
            "--",
            "Synthetic two",
        ],
        "",
    );
    assert_eq!(code, 0, "{err}");
    assert_eq!(
        source_lines(&out),
        vec!["source: room-cli v127 (not live-tested for sending)"],
        "{out}"
    );
    assert!(!out.contains("tested)"), "{out}");

    let output = fake.run_process(
        &[
            "send",
            "thr_syn_0003",
            "--op-id",
            "op-m13-t3",
            "--json",
            "--",
            "Synthetic three",
        ],
        "",
    );
    let (code, json) = json_of(&output);
    assert_eq!(code, Some(0), "{json}");
    assert_eq!(json["source"], not_tested, "the release program");
}

/// #200, failing closed: a record whose source has no tested version but
/// says `version_tested: true` (one no run writes) still replays as not
/// live-tested for sending, never `(tested)`.
#[test]
fn a_record_with_no_tested_version_never_replays_as_tested() {
    let fake = SendFake::new("m13_contradictory_record", "send");
    let args = ["thr_syn_0001", "--op-id", "op-m13-c", "--", "Synthetic"];
    let (code, _, err) = fake.cli(&args, "");
    assert_eq!(code, 0, "{err}");
    let mut record = fake.record("op-m13-c");
    record["source"]["version_tested"] = json!(true);
    assert_eq!(record["source"]["tested_version"], "");
    std::fs::write(fake.record_path("op-m13-c"), record.to_string()).unwrap();

    let (code, out, err) = fake.cli(&args, "");
    assert_eq!(code, 0, "{err}");
    assert!(out.contains("replayed"), "{out}");
    assert_eq!(
        source_lines(&out),
        vec!["source: room-cli v127 (not live-tested for sending)"],
        "{out}"
    );
    assert_eq!(fake.tell_count(), 1, "the replay made no call");
}

/// #200, R1 of the 0.0.3 export review, still open after #250: a record
/// written before #250 says its v127 was tested for sending. Its replay and
/// its lookup, as text and JSON, judge that v127 against this build's own
/// tested version for sending, never the record's stored claim, so they say
/// it is not live-tested for sending. The outcome stays as recorded, the
/// record is unchanged, and nothing is sent again.
#[test]
fn a_record_from_before_250_never_replays_or_looks_up_as_tested() {
    let before = json!({"name": "room-cli", "version": {"known": "v127"}, "tested_version": "v127", "version_tested": true});
    let not_tested = json!({"name": "room-cli", "version": {"known": "v127"}, "tested_version": "", "version_tested": false});
    let fake = SendFake::new("m13_record_before_250", "send");
    let args = ["thr_syn_0001", "--op-id", "op-m13-b", "--", "Synthetic"];
    let (code, _, err) = fake.cli(&args, "");
    assert_eq!(code, 0, "{err}");
    let mut record = fake.record("op-m13-b");
    record["source"] = before.clone();
    std::fs::write(fake.record_path("op-m13-b"), record.to_string()).unwrap();
    // Each report's `source`, and each text's `source:` lines, by where
    // they were seen: all are checked at the end, so a failure shows every
    // one.
    let mut sources: Vec<(&str, Value)> = vec![];
    let mut texts: Vec<(&str, Vec<String>)> = vec![];
    let lines = |out: &str| source_lines(out).into_iter().map(str::to_owned).collect();

    // The replay: the core's report (the web API's too), its text and JSON.
    let replay = request("thr_syn_0001", Mode::Queue, "Synthetic", "op-m13-b");
    let report = serde_json::to_value(fake.report(&replay)).unwrap();
    assert_eq!(report["status"], "accepted", "{report}");
    assert_eq!(report["result"]["replayed"], true, "{report}");
    sources.push(("the core's replay", report["source"].clone()));
    let (code, out, err) = fake.cli(&args, "");
    assert_eq!(code, 0, "{err}");
    assert!(out.contains("replayed"), "{out}");
    texts.push(("the replay's text", lines(&out)));
    let (code, json) = fake.cli_json(&args, "");
    assert_eq!(code, 0, "{json}");
    assert_eq!(json["result"]["replayed"], true, "{json}");
    assert_eq!(validate_report(&json), Vec::<String>::new(), "the schema");
    sources.push(("the replay's JSON", json["source"].clone()));

    // The lookup (`--check`), text and JSON.
    let check = ["thr_syn_0001", "--op-id", "op-m13-b", "--check"];
    let (code, out, err) = fake.cli(&check, "");
    assert_eq!(code, 0, "{err}");
    texts.push(("the lookup's text", lines(&out)));
    let (code, json) = fake.cli_json(&check, "");
    assert_eq!(code, 0, "{json}");
    assert_eq!(json["result"]["kind"], "recorded", "{json}");
    assert_eq!(json["result"]["report"]["status"], "accepted", "{json}");
    sources.push((
        "the lookup's JSON",
        json["result"]["report"]["source"].clone(),
    ));

    // A send still in flight in a build from before #250, looked up.
    let mut held = Held::claim(&fake, "thr_syn_0002", Mode::Queue, "Synthetic", "op-m13-h");
    held.record.source = Some(serde_json::from_value(before.clone()).unwrap());
    held.dispatching();
    let check = ["thr_syn_0002", "--op-id", "op-m13-h", "--check"];
    let (code, out, err) = fake.cli(&check, "");
    assert_eq!(code, EXIT_IN_PROGRESS, "{out}{err}");
    texts.push(("the in-flight lookup's text", lines(&out)));
    let (code, json) = fake.cli_json(&check, "");
    assert_eq!(code, EXIT_IN_PROGRESS, "{json}");
    assert_eq!(json["result"]["report"]["status"], "in_progress", "{json}");
    sources.push((
        "the in-flight lookup's JSON",
        json["result"]["report"]["source"].clone(),
    ));
    assert_eq!(fake.record("op-m13-h")["source"], before, "the held record");
    held.stop();

    let line = vec!["source: room-cli v127 (not live-tested for sending)".to_owned()];
    let expected = (
        sources
            .iter()
            .map(|(what, _)| (*what, not_tested.clone()))
            .collect::<Vec<_>>(),
        texts
            .iter()
            .map(|(what, _)| (*what, line.clone()))
            .collect::<Vec<_>>(),
    );
    assert_eq!((sources, texts), expected, "each source, JSON then text");
    assert_eq!(fake.record("op-m13-b"), record, "the record is unchanged");
    assert_eq!(fake.tell_count(), 1, "nothing was sent again");
}

/// #200 follow-up, failing closed: a record whose version is known but
/// empty is never judged tested, though it equals send's tested version
/// while send has none (`""`).
#[test]
fn a_record_with_an_empty_version_never_replays_as_tested() {
    let fake = SendFake::new("m13_empty_version_record", "send");
    let args = ["thr_syn_0001", "--op-id", "op-m13-e", "--", "Synthetic"];
    let (code, _, err) = fake.cli(&args, "");
    assert_eq!(code, 0, "{err}");
    let mut record = fake.record("op-m13-e");
    record["source"] = json!({"name": "room-cli", "version": {"known": ""}, "tested_version": "v127", "version_tested": true});
    std::fs::write(fake.record_path("op-m13-e"), record.to_string()).unwrap();

    let (code, json) = fake.cli_json(&args, "");
    assert_eq!(code, 0, "{json}");
    assert_eq!(json["result"]["replayed"], true, "{json}");
    assert_eq!(
        json["source"],
        json!({"name": "room-cli", "version": {"known": ""}, "tested_version": "", "version_tested": false}),
        "the replay's JSON"
    );
    assert_eq!(fake.tell_count(), 1, "the replay made no call");
}

/// #200: the contract says the same as the report: `tested_version` is
/// send's own, empty while no live send has passed, never the reads'.
#[test]
fn the_schema_says_send_has_its_own_tested_version() {
    let schema = messaging_schema();
    let source = &schema["$defs"]["source"];
    assert_eq!(
        source["description"],
        "The provider and the version this send read (#37: the version is never a gate). \
         tested_version is send's own: the room-cli version a live send last passed with, \
         or \"\" while none has (#200). It is never the reads' live-tested version in \
         openwiz.inventory.v1. version_tested is true only when version is known and \
         equals it. Evidence, not a requirement."
    );
    assert_eq!(
        source["properties"]["tested_version"],
        json!({"type": "string"})
    );
    assert_eq!(
        source["properties"]["version_tested"],
        json!({"type": "boolean"})
    );
}

/// #200: `--help` names each kind of run's own live-tested version: the
/// reads', v127, and none yet for `send` and `new`.
#[test]
fn help_names_each_kind_of_runs_own_tested_version() {
    let help = openwiz_cli::help();
    let lines: Vec<&str> = help.lines().collect();
    for line in [
        "ls, show, send and new can read and show room-cli --version.",
        "send --preview, models and new --status do not read the version. send --check and attachment never run room-cli.",
        "Any version runs; one other than \
         the run's own live-tested version is marked untested, or not live-tested while it has \
         none.",
        "Live-tested: the reads with v127; send with no version yet; new with no version yet.",
    ] {
        assert_eq!(
            lines.iter().filter(|l| **l == line).count(),
            1,
            "{line:?} not once in --help:\n{help}"
        );
    }
    assert!(
        !help.contains("one other than the live-tested v127"),
        "{help}"
    );
}

/// #797: help must agree with an offline lookup that reads no provider data.
#[test]
fn help_version_wording_agrees_with_offline_check() {
    let fake = SendFake::new("m13_offline_check_help", "send");
    let check = fake.run_process(
        &["send", "thr_syn_0001", "--op-id", "syn-001", "--check"],
        "",
    );
    assert_eq!(check.status.code(), Some(11), "{check:?}");
    assert!(check.stderr.is_empty(), "{check:?}");
    assert!(fake.invocations().is_empty(), "--check read room-cli");
    assert!(!fake.state.exists(), "--check created state");

    for flag in ["--help", "-h"] {
        let output = fake.run_process(&[flag], "");
        assert!(output.status.success(), "{flag}: {output:?}");
        assert!(output.stderr.is_empty(), "{flag}: {output:?}");
        let help = String::from_utf8(output.stdout).expect("UTF-8 help");
        assert!(fake.invocations().is_empty(), "{flag} read room-cli");
        assert!(!fake.state.exists(), "{flag} created state");
        assert!(
            !help.contains("Every run reads room-cli"),
            "{flag}: help claims a version read for an offline command"
        );
        assert!(
            help.contains(concat!(
                "or no record. Takes no text; makes no claim and no call, and never runs\n",
                "              room-cli. --json prints openwiz.send-lookup.v1"
            )),
            "{flag}: help must preserve the offline --check guarantee"
        );
    }
}

/// R1: provider reads can omit --version; help must name the exceptions.
#[test]
fn help_names_provider_reads_without_a_version_read() {
    let fake = SendFake::with(
        "m13_help_version_exceptions",
        vec![json!({
            "argv": ["cloud", "status", "--json"],
            "stdout": include_str!("../fixtures/room-cli-v127/new-thread/cloud-status.json"),
        })],
    );
    for args in [&["send", "thr_syn_0001", "--preview"][..], &["models"][..]] {
        let output = fake.run_process(args, "");
        assert_eq!(output.status.code(), Some(0), "{args:?}: {output:?}");
        assert!(output.stderr.is_empty(), "{args:?}: {output:?}");
    }
    assert_eq!(
        fake.invocations(),
        [
            vec!["thread", "show", "thr_syn_0001", "--json"],
            vec!["thread", "list", "--json"],
            vec!["cloud", "status", "--json"],
        ]
    );
    assert!(!fake.state.exists(), "preview/models created state");
    assert!(
        openwiz_cli::help()
            .contains("send --preview, models and new --status do not read the version."),
        "help overstates version reads for provider-backed commands"
    );
}

/// #37: Jake approved policy (b), 2026-10-28
/// ([private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036)). The `room-cli` version is never a
/// gate for `send` either: any version is read and reported, and the send
/// goes on with every other safeguard. Before, a version other than 0.43.1
/// sent nothing (exit 4). Since #200 send has its own tested version, none
/// yet, so no version is live-tested for sending.
#[test]
fn an_untested_version_never_stops_a_send() {
    let tested = SendFake::new("m13_version_tested", "send");
    let wanted = tested.report(&request(
        "thr_syn_0001",
        Mode::Queue,
        "Synthetic",
        "op-m13-v",
    ));
    assert_eq!(
        source_of(&wanted),
        json!({"name": "room-cli", "version": {"known": "v127"}, "tested_version": "", "version_tested": false}),
        "v127, the reads' tested version, is not live-tested for sending"
    );
    for (i, version) in ["0.44.0", "0.43.1"].iter().enumerate() {
        let fake = with_version(
            &format!("m13_version_{i}"),
            json!({"stdout": format!("{version}\n")}),
        );
        let report = fake.report(&request(
            "thr_syn_0001",
            Mode::Queue,
            "Synthetic",
            "op-m13-v",
        ));
        assert_eq!(
            delivery(&report),
            delivery(&wanted),
            "{version}: sent as on v127"
        );
        assert_eq!(fake.tell_count(), 1, "{version}: one call");
        assert_eq!(
            source_of(&report),
            json!({"name": "room-cli", "version": {"known": version}, "tested_version": "", "version_tested": false}),
            "{version}"
        );
        assert_eq!(
            fake.record("op-m13-v")["source"],
            source_of(&report),
            "{version}: recorded"
        );
        assert!(
            !report
                .gaps
                .iter()
                .any(|g| g.subject == "room-cli --version"),
            "{version}: a known version is not a gap: {:#?}",
            report.gaps
        );

        let (code, out, err) = fake.cli(&["thr_syn_0002", "--", "Synthetic two"], "");
        assert_eq!(code, 0, "{version}: {err}");
        assert_eq!(
            source_lines(&out),
            vec![format!(
                "source: room-cli {version} (not live-tested for sending)"
            )],
            "{version}: the text names the version, never the reads' tested one:\n{out}"
        );
    }
}

/// #37: a version that is not `N.N.N` or `v<N>`, or a failed version read,
/// is unknown with a reason in OpenWiz's controlled words and a gap, as in
/// the reads; the provider's text is never shown, and the send goes on.
#[test]
fn an_unrecognised_or_unreadable_version_never_stops_a_send() {
    for (i, (answer, why)) in [
        (
            json!({"stdout": "Synthetic not a version\n"}),
            "printed a version that is not N.N.N or v<N> (detail withheld)",
        ),
        (
            json!({"exit": 1, "stderr": "Synthetic failure SYNTHETIC_TOKEN=synthetic-secret-value"}),
            "exited 1",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let fake = with_version(&format!("m13_version_unknown_{i}"), answer);
        let report = fake.report(&request("thr_syn_0001", Mode::Queue, "Synthetic", "op-m13-u"));
        assert_ne!(report.status, Status::Failed, "{why}: {report:#?}");
        assert_eq!(fake.tell_count(), 1, "{why}: one call");
        let source = source_of(&report);
        let reason = source["version"]["unknown"].as_str().unwrap_or_default();
        assert!(
            reason.starts_with("room-cli --version ") && reason.contains(why),
            "{why}: {source}"
        );
        assert_eq!(source["version_tested"], false);
        assert!(
            report.gaps.iter().any(|g| g.subject == "room-cli --version" && g.detail == reason),
            "{why}: a gap: {:#?}",
            report.gaps
        );
        let (_, out, err) = fake.cli(&["thr_syn_0002", "--", "Synthetic two"], "");
        let json = serde_json::to_string(&report).unwrap();
        for text in [json.as_str(), out.as_str(), err.as_str()] {
            assert!(
                !text.contains("Synthetic not a version") && !text.contains("synthetic-secret-value"),
                "{why}: the provider's text is shown: {text}"
            );
        }
    }
}

/// #37, Sol's PR #40 finding 1: a failed version read shows safe facts only
/// in `send`'s text, JSON report and record, never the provider's text, even
/// a line in #21's general diagnostic grammar.
#[test]
fn a_failed_version_read_never_echoes_its_error_text_in_send() {
    const MARKER: &str = "Synthetic private version marker";
    let fake = with_version(
        "m13_version_failed",
        json!({"exit": 1, "stderr": format!("Error: HTTP 500: {MARKER}")}),
    );
    let report = fake.report(&request(
        "thr_syn_0001",
        Mode::Queue,
        "Synthetic",
        "op-m13-f",
    ));
    assert_eq!(
        source_of(&report)["version"]["unknown"],
        "room-cli --version exited 1 (detail withheld)"
    );
    let (_, out, err) = fake.cli(
        &[
            "thr_syn_0002",
            "--op-id",
            "op-m13-f2",
            "--",
            "Synthetic two",
        ],
        "",
    );
    let (_, json) = fake.cli_json(
        &[
            "thr_syn_0003",
            "--op-id",
            "op-m13-f3",
            "--",
            "Synthetic three",
        ],
        "",
    );
    for (what, text) in [
        ("report", serde_json::to_string(&report).unwrap()),
        ("text", format!("{out}{err}")),
        ("JSON", json.to_string()),
        ("record", fake.record("op-m13-f").to_string()),
        ("record 2", fake.record("op-m13-f2").to_string()),
        ("record 3", fake.record("op-m13-f3").to_string()),
    ] {
        assert!(!text.contains(MARKER), "{what}: {text}");
        assert!(
            text.contains("exited 1 (detail withheld)"),
            "{what}: {text}"
        );
    }
}

/// #37: a record written before #37 (no `source`, failed as
/// `untested_version`) still loads; its replay reports it as failed, with
/// send's failed exit (5), not the removed exit 4.
#[test]
fn an_earlier_untested_version_record_replays_as_failed() {
    let fake = SendFake::new("m13_version_legacy", "send");
    let args = ["thr_syn_9999", "--op-id", "op-m13-old", "--", "Synthetic"];
    let (code, _, err) = fake.cli(&args, "");
    assert_eq!(code, 3, "the planted record starts as not found: {err}");
    let mut record = fake.record("op-m13-old");
    record["delivery"]["reason"] = json!("untested_version");
    record["delivery"]["text"] =
        json!("failed: room-cli reports 0.44.0, not the tested 0.43.1; nothing was sent");
    record.as_object_mut().unwrap().remove("source");
    std::fs::write(fake.record_path("op-m13-old"), record.to_string()).unwrap();

    let (code, out, err) = fake.cli(&args, "");
    assert_eq!(code, 5, "{out}{err}");
    assert!(out.contains("replayed"), "{out}");
    assert_eq!(fake.tell_count(), 0);
}
