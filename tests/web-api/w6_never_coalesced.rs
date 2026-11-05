//! W6 (#9): sends are never coalesced. Two sends with different op ids are
//! two calls, even when identical (U7's in-flight guard refuses the second
//! while the first is running, unless the owner accepts a possible
//! duplicate); the same op id from two tabs is one call; a conflicting
//! reuse is none. The read routes' single-flight is not on the send path.

use std::thread;
use std::time::Duration;

use serde_json::json;

use crate::http::Response;
use crate::msg::SendFake;
use crate::send_support::{body, good_headers, messages, raw, send_json, serve_send};

fn status(r: &Response) -> String {
    assert_eq!(r.status, 200, "{}", r.text());
    r.json()["status"].as_str().expect("status").to_owned()
}

#[test]
fn identical_sends_with_different_op_ids_are_two_calls() {
    let fake = SendFake::new("web_w6_sequential", "send");
    let s = serve_send(&fake);
    for op in ["w6-op-1", "w6-op-2"] {
        let r = send_json(&s, "thr_syn_0001", &body(op, "queue", "Synthetic W6 text"));
        assert_eq!(status(&r), "accepted");
    }
    assert_eq!(fake.tell_count(), 2);
}

#[test]
fn identical_sends_at_once_are_two_calls_only_when_the_owner_accepts() {
    // Independent owners/fakes, with the exact admitted provider calls held
    // until their overlap (or the competing refusal) has been observed.
    crate::at_once::at_once(&[false, true], 2, |&accepted| {
        let fake = SendFake::new(
            if accepted {
                "web_w6_at_once_accepted"
            } else {
                "web_w6_at_once"
            },
            "send",
        );
        let (s, gate) = crate::send_support::serve_held_tell(&fake, Default::default());
        let _release = crate::send_support::ReleaseTell(gate.clone());
        let mut first = body("w6-op-3", "queue", "Synthetic W6 text");
        let mut second = body("w6-op-4", "queue", "Synthetic W6 text");
        if accepted {
            first["accept_possible_duplicate"] = json!(true);
            second["accept_possible_duplicate"] = json!(true);
            let answers = thread::scope(|scope| {
                let _release = crate::send_support::ReleaseTell(gate.clone());
                let requests: Vec<_> = [first, second]
                    .into_iter()
                    .map(|value| {
                        let s = &s;
                        scope.spawn(move || send_json(s, "thr_syn_0001", &value))
                    })
                    .collect();
                gate.wait_held_calls(2);
                gate.open();
                requests
                    .into_iter()
                    .map(|h| h.join().unwrap())
                    .collect::<Vec<_>>()
            });
            for r in &answers {
                assert_eq!(status(r), "accepted");
            }
            assert_eq!(fake.tell_count(), 2);
        } else {
            let (addr, payload) = (s.addr, first.to_string());
            let h = thread::spawn(move || {
                crate::http::send(
                    addr,
                    &raw(
                        "POST",
                        &messages("thr_syn_0001"),
                        &good_headers(),
                        payload.as_bytes(),
                        true,
                    ),
                )
            });
            gate.wait_held();
            let r = send_json(&s, "thr_syn_0001", &second);
            assert_eq!(status(&r), "possible_duplicate_refused");
            gate.open();
            assert_eq!(status(&h.join().unwrap()), "accepted");
            assert_eq!(fake.tell_count(), 1);
        }
    });
}

#[test]
fn the_same_op_id_from_two_tabs_is_one_call() {
    let fake = SendFake::new("web_w6_two_tabs", "send");
    let (s, gate) = crate::send_support::serve_held_tell(&fake, Default::default());
    let _release = crate::send_support::ReleaseTell(gate.clone());
    let value = body("w6-op-5", "queue", "Synthetic W6 tabs");
    let (done, completed) = std::sync::mpsc::channel();
    let requests: Vec<_> = (0..3)
        .map(|_| {
            let (addr, payload, done) = (s.addr, value.to_string(), done.clone());
            thread::spawn(move || {
                let response = crate::http::send(
                    addr,
                    &raw(
                        "POST",
                        &messages("thr_syn_0001"),
                        &good_headers(),
                        payload.as_bytes(),
                        true,
                    ),
                );
                let _ = done.send(());
                response
            })
        })
        .collect();
    gate.wait_held();
    // Both duplicate requests must answer while the first call is held.
    // This proves overlap directly instead of hoping they arrive in 800 ms.
    for _ in 0..2 {
        completed
            .recv_timeout(Duration::from_secs(10))
            .expect("a duplicate request must answer without repeating the held tell");
    }
    gate.open();
    let answers: Vec<_> = requests.into_iter().map(|r| r.join().unwrap()).collect();
    let statuses: Vec<String> = answers.iter().map(status).collect();
    assert!(statuses.iter().any(|s| s == "accepted"), "{statuses:?}");
    for st in &statuses {
        assert!(st == "accepted" || st == "in_progress", "{statuses:?}");
    }
    assert_eq!(fake.tell_count(), 1);
    // A later retry replays the recorded outcome, with no call.
    let r = send_json(&s, "thr_syn_0001", &value);
    assert_eq!(status(&r), "accepted");
    assert_eq!(r.json()["result"]["replayed"], json!(true));
    assert_eq!(fake.tell_count(), 1);
}

#[test]
fn a_conflicting_reuse_is_no_call() {
    let fake = SendFake::new("web_w6_conflict", "send");
    let s = serve_send(&fake);
    let value = body("w6-op-6", "queue", "Synthetic W6 conflict");
    assert_eq!(status(&send_json(&s, "thr_syn_0001", &value)), "accepted");
    let mut text = value.clone();
    text["text"] = json!("Synthetic W6 conflict, changed");
    let mut mode = value.clone();
    mode["mode"] = json!("steer");
    for (id, changed) in [
        ("thr_syn_0001", text),
        ("thr_syn_0001", mode),
        ("thr_syn_0003", value),
    ] {
        let r = send_json(&s, id, &changed);
        assert_eq!(status(&r), "conflicting_reuse", "{id} {changed}");
    }
    assert_eq!(fake.tell_count(), 1);
}

#[test]
fn the_send_path_has_no_single_flight() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../crates/server/src/send.rs");
    let text = std::fs::read_to_string(path).expect("crates/server/src/send.rs");
    for word in ["Runs", "Call::", "flights", "single-flight"] {
        assert!(!text.contains(word), "the send path mentions {word}");
    }
}
