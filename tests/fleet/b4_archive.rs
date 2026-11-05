//! B4 (ClosedWiz#120): archiving a finished agent's thread with `thread
//! archive <id> --json`, the CloudRoom allowlist's third write (spec #116,
//! "New writes: CloudRoom `thread archive`"; observed in help, 0.43.1, the
//! call never run).
//!
//! The recording fake shows exactly the calls each case makes and nothing
//! else: a `thread show` first, the one archive only when the thread is
//! there and not archived yet, and a `thread show` after it, whose
//! `archivedAt` alone says it was archived. The fake answers that second
//! read from `after_archive` only once a call with `"archives": true` took.

use std::fs;
use std::time::{Duration, Instant};

use openwiz_adapter_cloudroom::allowlist::{Invocation, ThreadId};
use openwiz_adapter_cloudroom::archive::ArchiveOutcome;
use serde_json::{Value, json};

use super::fake::*;

/// The thread every archive here is of: the 0.43.1 fixture's, not
/// archived.
const ID: &str = "thr_syn_0001";

const SHOW_0001: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/room-cli-0.43.1/normal/thread-show-0001.json"
);

fn id() -> ThreadId {
    ThreadId::parse(ID).expect("an id")
}

/// The fixture's `thread show`, with `archivedAt` set to `at`, written into
/// the fake's directory; its absolute path.
fn show_file(fake: &Fake, at: Value) -> String {
    let text = fs::read_to_string(SHOW_0001).expect("the fixture");
    let mut show: Value = serde_json::from_str(&text).expect("JSON");
    show["thread"]["archivedAt"] = at;
    let path = fake.dir.join(format!("show-{}.json", unique(&show)));
    fs::write(&path, show.to_string()).expect("write the answer");
    path.to_str().expect("utf-8").to_owned()
}

fn unique(value: &Value) -> String {
    openwiz_core::messaging::sha256_hex(value.to_string().as_bytes())[..12].to_owned()
}

fn show() -> Vec<String> {
    ["thread", "show", ID, "--json"].map(str::to_owned).to_vec()
}

fn archive() -> Vec<String> {
    ["thread", "archive", ID, "--json"]
        .map(str::to_owned)
        .to_vec()
}

/// `thread show`, not archived; archived once a call took.
fn show_before_and_after(fake: &Fake) -> Value {
    json!({
        "argv": show(),
        "stdout_file": show_file(fake, Value::Null),
        "after_archive": {"stdout_file": show_file(fake, json!(1_700_000_900_000_i64))},
    })
}

fn archive_with(fake: &Fake, responses: Vec<Value>) -> ArchiveOutcome {
    fake.respond(responses);
    fake.source()
        .archive_thread(&id(), Instant::now() + Duration::from_secs(10))
}

#[test]
fn the_archive_is_built_in_exactly_its_one_shape() {
    assert_eq!(Invocation::ThreadArchive(id()).argv(), archive());
    // The id is one argument and never a flag: `ThreadId` can't hold one.
    for bad in ["", "-x", "--self", "thr syn", "thr;syn"] {
        assert!(ThreadId::parse(bad).is_err(), "{bad:?}");
    }
}

#[test]
fn an_unarchived_thread_is_archived_once_and_read_back() {
    let fake = Fake::new("b4_archive_ok", vec![]);
    let responses = vec![
        show_before_and_after(&fake),
        json!({"argv": archive(), "archives": true, "stdout": "{}"}),
    ];
    assert_eq!(archive_with(&fake, responses), ArchiveOutcome::Archived);
    assert_eq!(fake.invocations(), vec![show(), archive(), show()]);
    assert_eq!(fake.archive_count(), 1);
}

#[test]
fn an_archived_thread_is_done_with_no_call() {
    let fake = Fake::new("b4_archive_already", vec![]);
    let responses = vec![json!({
        "argv": show(),
        "stdout_file": show_file(&fake, json!(1_700_000_800_000_i64)),
    })];
    assert_eq!(
        archive_with(&fake, responses),
        ArchiveOutcome::AlreadyArchived
    );
    assert_eq!(fake.invocations(), vec![show()]);
    assert_eq!(fake.archive_count(), 0);
}

#[test]
fn a_thread_not_found_is_not_archived() {
    let fake = Fake::new("b4_archive_missing", vec![]);
    let responses = vec![json!({
        "argv": show(),
        "stderr": "Error: HTTP 404: Thread not found",
        "exit": 1,
    })];
    assert_eq!(archive_with(&fake, responses), ArchiveOutcome::NotFound);
    assert_eq!(fake.invocations(), vec![show()]);
}

#[test]
fn a_thread_that_cant_be_read_is_never_archived_blind() {
    let fake = Fake::new("b4_archive_unread", vec![]);
    let duplicated = {
        let text = fs::read_to_string(SHOW_0001).unwrap();
        text.replacen("\"archivedAt\"", "\"archivedAt\": 1, \"archivedAt\"", 1)
    };
    let answer =
        |thread: Value| json!({"argv": show(), "stdout": json!({"thread": thread}).to_string()});
    let cases = vec![
        json!({"argv": show(), "stderr": "Error: Synthetic failure", "exit": 1}),
        json!({"argv": show(), "stdout": "Synthetic not JSON"}),
        json!({"argv": show(), "stdout": duplicated}),
        answer(json!({"id": "thr_syn_0002", "archivedAt": null})),
        answer(json!({"id": ID, "archivedAt": "yes"})),
        answer(json!({"id": ID, "archivedAt": 1.5})),
        answer(json!({"id": ID})),
    ];
    for case in cases {
        let outcome = archive_with(&fake, vec![case.clone()]);
        assert!(
            matches!(outcome, ArchiveOutcome::NotRead { .. }),
            "{case}: {outcome:?}"
        );
    }
    assert_eq!(fake.archive_count(), 0, "no archive was called");
    assert!(fake.invocations().iter().all(|a| *a == show()));
}

#[test]
fn an_archive_that_did_not_take_says_so() {
    let fake = Fake::new("b4_archive_not_taken", vec![]);
    // Exit 0, but CloudRoom did not archive it.
    let outcome = archive_with(
        &fake,
        vec![
            show_before_and_after(&fake),
            json!({"argv": archive(), "stdout": "{}"}),
        ],
    );
    assert!(
        matches!(outcome, ArchiveOutcome::NotArchived { .. }),
        "{outcome:?}"
    );
    // Refused.
    let outcome = archive_with(
        &fake,
        vec![
            show_before_and_after(&fake),
            json!({"argv": archive(), "stderr": "Error: Synthetic refusal", "exit": 1}),
        ],
    );
    let ArchiveOutcome::NotArchived { words } = &outcome else {
        panic!("{outcome:?}");
    };
    assert!(words.contains("exited 1"), "{words}");
    assert_eq!(fake.archive_count(), 2);
    assert_eq!(
        fake.invocations(),
        vec![show(), archive(), show(), show(), archive(), show()]
    );
}

#[test]
fn an_archive_that_cant_be_read_back_is_unconfirmed() {
    let fake = Fake::new("b4_archive_unconfirmed", vec![]);
    let outcome = archive_with(
        &fake,
        vec![
            json!({
                "argv": show(),
                "stdout_file": show_file(&fake, Value::Null),
                "after_archive": {"stderr": "Error: Synthetic failure", "exit": 1},
            }),
            json!({"argv": archive(), "archives": true, "stdout": "{}"}),
        ],
    );
    assert!(
        matches!(outcome, ArchiveOutcome::Unconfirmed { .. }),
        "{outcome:?}"
    );
    assert_eq!(fake.archive_count(), 1, "never retried");
    assert_eq!(fake.invocations(), vec![show(), archive(), show()]);
}

/// The fake's own copy of the allowlist takes the archive in its one shape
/// only, so a call built any other way fails in every test.
#[test]
fn the_fake_refuses_every_other_archive_shape() {
    let fake = Fake::new("b4_archive_shapes", vec![]);
    for argv in [
        vec!["thread", "archive", ID],
        vec!["thread", "archive", "--self", "--json"],
        vec!["thread", "archive", "--json", ID],
        vec!["thread", "archive", ID, "--json", "--self"],
        vec!["thread", "unarchive", ID, "--json"],
        // An id `ThreadId` refuses: never counted as an archive.
        vec!["thread", "archive", "thr syn", "--json"],
        vec!["thread", "archive", concat!("thr_", "s\u{ff}n"), "--json"],
        vec!["thread", "archive", "thr;syn", "--json"],
    ] {
        let status = std::process::Command::new(fake.program())
            .args(&argv)
            .output()
            .expect("run the fake")
            .status;
        assert_eq!(status.code(), Some(97), "{argv:?}");
    }
    assert_eq!(fake.archive_count(), 0);
}
