use openwiz_core::model::Fact;

use crate::support::*;

fn thread_list_calls(fake: &Fake) -> Vec<Vec<String>> {
    fake.invocations()
        .into_iter()
        .filter(|a| a.len() >= 2 && a[0] == "thread" && a[1] == "list")
        .collect()
}

#[test]
fn hidden_and_archived_sessions_are_excluded_by_default() {
    let fake = Fake::new("p11_default", "normal");
    let (code, text, _) = fake.cli(&["ls"]);
    assert_eq!(code, 0);
    assert!(
        !text.contains(HIDDEN_ID) && !text.contains(ARCHIVED_ID),
        "{text}"
    );
    for argv in thread_list_calls(&fake) {
        assert_eq!(argv, ["thread", "list", "--json"], "flags only on request");
    }
}

#[test]
fn hidden_sessions_appear_only_with_hidden() {
    let fake = Fake::new("p11_hidden", "normal");
    let (code, text, _) = fake.cli(&["ls", "--hidden"]);
    assert_eq!(code, 0);
    assert!(text.contains(HIDDEN_ID), "{text}");
    assert!(!text.contains(ARCHIVED_ID), "{text}");
    assert!(
        thread_list_calls(&fake)
            .iter()
            .all(|a| a.iter().any(|w| w == "--include-hidden")
                && !a.iter().any(|w| w == "--include-archived")),
        "{:?}",
        fake.invocations()
    );
}

#[test]
fn archived_sessions_appear_only_with_a() {
    let fake = Fake::new("p11_archived", "normal");
    let (code, text, _) = fake.cli(&["ls", "-a"]);
    assert_eq!(code, 0);
    assert!(text.contains(ARCHIVED_ID), "{text}");
    assert!(!text.contains(HIDDEN_ID), "{text}");
    assert!(
        thread_list_calls(&fake)
            .iter()
            .all(|a| a.iter().any(|w| w == "--include-archived")
                && !a.iter().any(|w| w == "--include-hidden")),
        "{:?}",
        fake.invocations()
    );
}

#[test]
fn a_row_both_hidden_and_archived_requires_both_flags() {
    let mut row = scripted_record(1);
    row.hidden = Fact::Known(true);
    row.archived = Fact::Known(true);
    let source = ScriptedSource::with_records(vec![row]);

    for args in [
        &["ls", "--hidden", "--json"][..],
        &["ls", "-a", "--json"][..],
    ] {
        let result = cli_json_with(&source, args);
        assert_eq!(
            result["data"]["sessions"],
            serde_json::json!([]),
            "{args:?}"
        );
    }

    let result = cli_json_with(&source, &["ls", "--hidden", "-a", "--json"]);
    let sessions = result["data"]["sessions"]
        .as_array()
        .expect("sessions array");
    assert_eq!(sessions.len(), 1);
    assert_eq!(sessions[0]["id"], "thr_syn_0001");
}
