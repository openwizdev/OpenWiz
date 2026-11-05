//! O4/P4: public GitHub records contain no CloudRoom thread identifiers.
//! Existing B5 lifecycle proofs checked dispatch, but allowed ids in comments.
//! These synthetic endpoints exercise the same CLI boundary, including retries.
use super::fake::{self, World};
use serde_json::{Value, json};

fn public_records(w: &World) {
    let mut count = 0;
    for (tool, args) in w.writes() {
        if tool == "gh" {
            for flag in ["--body", "--body-file"] {
                if let Some(i) = args.iter().position(|a| a == flag) {
                    assert_eq!(flag, "--body", "scan the actual body, not a filename");
                    let body = &args[i + 1];
                    count += 1;
                    assert!(
                        !body.contains("thr_"),
                        "public record leaks a thread: {body}"
                    );
                }
            }
        }
    }
    assert!(count > 0, "must scan actual writes");
}

#[test]
fn p4_tick_writes_thread_free_records_through_merge_and_finished() {
    let w = public_world("p4-public-lifecycle");
    let started = w.tick();
    assert_eq!(started["actions"][0]["outcome"]["state"], "done");
    // Fails first on the planted synthetic thread in today's started record.
    public_records(&w);
    w.pr(10);
    let review = w.tick();
    assert_eq!(review["actions"][0]["rule"], "first_review", "{review}");
    assert_eq!(review["actions"][0]["outcome"]["state"], "done");
    public_records(&w);
    w.approve(10);
    assert_eq!(w.tick()["actions"][0]["rule"], "adr_0008");
    let finished = w.tick();
    assert!(
        finished["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "finished")
    );
    public_records(&w);
}

const NEXT: &str = "cccccccccccccccccccccccccccccccccccccccc";

fn dry(w: &World) -> Value {
    let out = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

/// 2141: legacy acceptance follows a positively read privacy fact, including
/// its canonical identity, rather than a repository's fixed spelling.
#[test]
fn p4_legacy_compatibility_requires_verified_repository_privacy() {
    for (case, repo, metadata, legacy) in [
        (
            "named-public",
            "jparker2006/ClosedWiz",
            json!({"nameWithOwner":"jparker2006/ClosedWiz","isPrivate":false}),
            false,
        ),
        (
            "other-private",
            "synthetic-records/archive",
            json!({"nameWithOwner":"synthetic-records/archive","isPrivate":true}),
            true,
        ),
        (
            "unknown",
            "jparker2006/ClosedWiz",
            json!({"nameWithOwner":"jparker2006/ClosedWiz","isPrivate":null}),
            false,
        ),
        ("unread", "jparker2006/ClosedWiz", json!({}), false),
        (
            "wrong-name",
            "jparker2006/ClosedWiz",
            json!({"nameWithOwner":"synthetic-other/archive","isPrivate":true}),
            false,
        ),
    ] {
        let w = World::new(&format!("2141-privacy-{case}"));
        w.change(|s| {
            s["repository"] = repo.into();
            s["repository_privacy"] = metadata;
            if case == "unread" {
                s["overrides"][serde_json::to_string(&json!([
                    "gh",
                    ["repo", "view", "--json", "nameWithOwner,isPrivate"]
                ]))
                .unwrap()] = json!(97);
            }
        });
        let result = dry(&w);
        assert_eq!(
            result["actions"][0]["rule"],
            if legacy { "frontier" } else { "look" },
            "{case}: {result}"
        );
        assert!(w.writes().is_empty());
    }
}

fn reviewing(name: &str, public: bool, stored: bool) -> World {
    let w = if public {
        public_world(name)
    } else {
        World::new(name)
    };
    w.tick();
    w.pr(10);
    assert_eq!(w.tick()["actions"][0]["rule"], "first_review");
    w.change(|s| {
        s["threads"]["thr_syn_b5_1"]["title"] = "#10: Synthetic ticket 10".into();
        s["threads"]["thr_syn_b5_1"]["branch"] = "synthetic-branch-10".into();
        s["threads"]["thr_syn_b5_2"]["title"] =
            format!("Review #110 at {}", &fake::HEAD10[..8]).into();
        for (number, cs) in s["comments"].as_object_mut().unwrap() {
            for c in cs.as_array_mut().unwrap() {
                let body = c["body"].as_str().unwrap().to_owned();
                if public {
                    c["body"] = body
                        .replace(", thread thr_syn_b5_1", "")
                        .replace(", thread thr_syn_b5_2", "")
                        .into();
                } else if body == "launch-fleet: started" {
                    c["body"] = "launch-fleet: started, thread thr_syn_b5_1".into();
                } else if body.starts_with("launch-fleet: start checked, branch ") {
                    c["body"] = body
                        .replace(
                            "start checked, branch ",
                            "start checked, thread thr_syn_b5_1, branch ",
                        )
                        .into();
                } else if number == "110"
                    && body == format!("launch-fleet: review started {}", fake::HEAD10)
                {
                    c["body"] = format!("{body}, thread thr_syn_b5_2").into();
                }
            }
        }
    });
    if !stored {
        std::fs::remove_dir_all(w.dir.join("state/starts")).unwrap();
    }
    w
}

#[test]
fn p4_recheck_lineage_merge_and_archive_with_public_and_legacy_records() {
    crate::at_once::at_once(
        &[(false, false), (false, true), (true, false), (true, true)],
        4,
        |&(public, stored)| {
            let w = reviewing(&format!("p4-recheck-{public}-{stored}"), public, stored);
            w.approve(10);
            w.change(|s| s["prs"][0]["head"] = NEXT.into());
            let recheck = w.tick();
            assert_eq!(recheck["actions"].as_array().unwrap().len(), 1, "{recheck}");
            assert_eq!(recheck["actions"][0]["rule"], "re_check", "{recheck}");
            assert_eq!(
                recheck["actions"][0]["outcome"]["state"], "done",
                "{recheck}"
            );
            assert!(
                w.writes()
                    .iter()
                    .any(|(t, a)| t == "room-cli" && a[1] == "tell" && a[2] == "thr_syn_b5_2")
            );
            // The new record's commit differs from its reviewer's start commit.
            w.approve(10);
            let merge = w.tick();
            assert_eq!(merge["actions"][0]["rule"], "adr_0008", "{merge}");
            assert_eq!(merge["actions"][0]["outcome"]["state"], "done", "{merge}");
            let archived = w.tick();
            assert!(
                archived["actions"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|a| a["rule"] == "finished"),
                "{archived}"
            );
            assert_eq!(w.load()["threads"]["thr_syn_b5_2"]["archived"], true);
            public_records(&w);
        },
    );
}

#[test]
fn p4_quiet_giveup_closes_the_whole_span_even_after_an_in_place_edit() {
    crate::at_once::at_once(
        &[(false, false), (false, true), (true, false), (true, true)],
        4,
        |&(public, stored)| {
            let w = reviewing(&format!("p4-giveup-{public}-{stored}"), public, stored);
            let suffix = if public { "" } else { ", thread thr_syn_b5_2" };
            w.change(|s| {
                s["prs"][0]["head"] = NEXT.into();
                s["comments"]["110"].as_array_mut().unwrap().extend([
                    json!({"id":3001,"body":format!("launch-fleet: re-check sent {NEXT}{suffix}"),"created":1793400020000_u64,"updated":1793400020000_u64}),
                    json!({"id":3002,"body":format!("launch-fleet: review told again {NEXT}{suffix}"),"created":1793400030000_u64,"updated":1793400030000_u64})
                ]);
            });
            let quiet = dry(&w);
            assert_eq!(quiet["actions"][0]["rule"], "look", "{quiet}");
            assert!(
                quiet["actions"][0]["facts"]["reason"]
                    .as_str()
                    .unwrap()
                    .contains("reviewer quiet"),
                "{quiet}"
            );
            w.change(|s| {
                let c = s["comments"]["110"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|c| c["id"] == 3001)
                    .unwrap();
                c["body"] = if public {
                    format!("launch-fleet: review given up {NEXT}: synthetic stop")
                } else {
                    format!("launch-fleet: review failed {NEXT}{suffix}: synthetic stop")
                }
                .into();
                c["updated"] = 1893400040000_u64.into();
                s["comment_time"] = 1793400040000_u64.into();
                // The API's vector order and updated time are not lineage order.
                s["comments"]["110"].as_array_mut().unwrap().reverse();
            });
            let calls = w.calls().len();
            let fresh = w.tick();
            assert_eq!(fresh["actions"][0]["rule"], "fresh_review", "{fresh}");
            assert_eq!(fresh["actions"][0]["outcome"]["state"], "done", "{fresh}");
            assert!(!w.calls()[calls..].iter().any(|(t, a)| {
                t == "room-cli"
                    && a.get(1)
                        .is_some_and(|a| ["output", "tell"].contains(&a.as_str()))
                    && a.get(2).is_some_and(|a| a == "thr_syn_b5_2")
            }));
            assert_eq!(w.load()["spawn_count"], 3);
            w.approve(10);
            let merge = w.tick();
            assert_eq!(merge["actions"][0]["rule"], "adr_0008", "{merge}");
            assert_eq!(merge["actions"][0]["outcome"]["state"], "done", "{merge}");
            assert!(!w.calls()[calls..].iter().any(|(t, a)| {
                t == "room-cli"
                    && a.get(1)
                        .is_some_and(|a| ["output", "tell"].contains(&a.as_str()))
                    && a.get(2).is_some_and(|a| a == "thr_syn_b5_2")
            }));
            public_records(&w);
        },
    );
}

#[test]
fn p4_ambiguous_titles_and_disagreement_never_choose_an_agent() {
    crate::at_once::at_once(
        &[
            "wrong-branch-stored",
            "wrong-branch-anonymous",
            "unread-branch-stored",
            "builder-two",
            "builder-disagrees",
            "reviewer-two",
            "reviewer-disagrees",
            "unread-titles",
            "legacy-on-public",
            "wrong-branch",
            "orphan",
            "bad-start",
        ],
        4,
        |&case| {
            let w = reviewing(
                &format!("p4-{case}"),
                true,
                matches!(
                    case,
                    "builder-disagrees"
                        | "reviewer-disagrees"
                        | "unread-titles"
                        | "wrong-branch-stored"
                        | "wrong-branch-anonymous"
                        | "unread-branch-stored"
                ),
            );
            let stored_branch = matches!(
                case,
                "wrong-branch-stored" | "wrong-branch-anonymous" | "unread-branch-stored"
            );
            if stored_branch {
                // R1: a completed review and failed CI expose misrouted repair sends.
                // Earlier wrong-branch coverage removed B4 state and missed this.
                w.approve(10);
                w.change(|s| {
                    s["prs"][0]["ci"] = "failure".into();
                    if case != "wrong-branch-stored" {
                        s["threads"]["thr_syn_b5_1"]["title"] =
                            "Synthetic anonymous builder".into();
                    }
                });
            }
            w.change(|s| match case {
            "wrong-branch-stored" | "wrong-branch-anonymous" => s["threads"]["thr_syn_b5_1"]["branch"] = "other-branch".into(),
            "unread-branch-stored" => s["overrides"][serde_json::to_string(&json!(["room-cli", ["cloud", "thread-workspace", "thr_syn_b5_1", "--json"]])).unwrap()] = json!(97),
            "builder-two" | "builder-disagrees" => {
                s["threads"]["thr_syn_duplicate"] = s["threads"]["thr_syn_b5_1"].clone();
                if case == "builder-disagrees" { s["threads"]["thr_syn_b5_1"]["title"] = "Synthetic unrelated thread".into(); }
            }
            "reviewer-two" => s["threads"]["thr_syn_duplicate"] = s["threads"]["thr_syn_b5_2"].clone(),
            "reviewer-disagrees" => {
                s["threads"]["thr_syn_duplicate"] = s["threads"]["thr_syn_b5_2"].clone();
                s["threads"]["thr_syn_b5_2"]["title"] = "Synthetic unrelated review".into();
            }
            "unread-titles" => s["overrides"][serde_json::to_string(&json!(["room-cli", ["thread", "list", "--json", "--include-hidden", "--include-archived"]])).unwrap()] = json!(97),
            "legacy-on-public" => s["comments"]["10"][0]["body"] = "launch-fleet: started, thread thr_syn_b5_1".into(),
            "wrong-branch" => s["threads"]["thr_syn_b5_1"]["branch"] = "other-branch".into(),
            "orphan" => s["comments"]["110"] = json!([{"id":3001,"body":format!("launch-fleet: re-check sent {NEXT}"),"created":1793400020000_u64,"updated":1793400020000_u64}]),
            "bad-start" => s["comments"]["110"][0]["body"] = "launch-fleet: review started invalid".into(),
            _ => unreachable!()
        });
            let before = w.writes();
            let doc = w.tick();
            assert_eq!(doc["actions"][0]["rule"], "look", "{case}: {doc}");
            assert_eq!(w.writes(), before, "{case}");
        },
    );
}

#[test]
fn p4_helper_and_other_project_titles_do_not_match_the_builder() {
    for stored in [false, true] {
        let w = reviewing(&format!("p4-helper-titles-{stored}"), true, stored);
        w.change(|s| {
            s["threads"]["thr_syn_helper"] = s["threads"]["thr_syn_b5_1"].clone();
            s["threads"]["thr_syn_helper"]["title"] = "#10 helper scout".into();
            s["threads"]["thr_syn_foreign"] = s["threads"]["thr_syn_b5_1"].clone();
            s["threads"]["thr_syn_foreign"]["project"] = "prj_syn_other".into();
            // Same-title candidates on another branch are still filtered, even
            // while the actual private builder's checked branch is enforced.
            s["threads"]["thr_syn_other_branch"] = s["threads"]["thr_syn_b5_1"].clone();
            s["threads"]["thr_syn_other_branch"]["branch"] = "unrelated-branch".into();
        });
        w.approve(10);
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["rule"], "adr_0008", "{doc}");
        assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
        public_records(&w);
    }
}

fn public_approval() -> String {
    fake::APPROVAL.replacen("\"approved\"\n", "approved as proposed.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001\n", 1)
}

#[test]
fn p4_public_approval_keeps_the_same_fingerprint_and_requires_a_pointer() {
    for (case, body, accepted) in [
        ("public", public_approval(), true),
        ("legacy", fake::APPROVAL.into(), false),
        ("missing", public_approval().replace("Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001\n", ""), false),
        ("public-pointer", public_approval().replace("ClosedWiz/issues/9001", "OpenWiz/issues/9001"), false),
        ("leading-zero", public_approval().replace("issues/9001", "issues/09001"), false),
        ("repeated", public_approval().replace("Private record: ", "Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001\nPrivate record: "), false),
        ("quoted", public_approval().replace("approved as proposed.", "\"approved as proposed\""), false),
    ] {
        let w = World::new(&format!("p4-approval-{case}"));
        w.change(|s| {
            // Unknown repository identity takes the public rules too.
            s["repository"] = "synthetic/public-repository".into();
            s["comments"]["9"][0]["body"] = body.into();
        });
        let doc = dry(&w);
        assert_eq!(doc["actions"][0]["rule"], if accepted { "frontier" } else { "look" }, "{case}: {doc}");
        assert!(w.writes().is_empty());
    }
}

fn public_world(name: &str) -> World {
    let w = World::new(name);
    w.change(|s| {
        s["repository"] = "synthetic/public-repository".into();
        s["comments"]["9"][0]["body"] = public_approval().into();
    });
    w
}

#[test]
fn p4_fallback_record_is_thread_free_and_an_injected_branch_is_refused() {
    for inject in [false, true] {
        let w = if inject {
            World::new("p4-injected-branch")
        } else {
            public_world("p4-fallback")
        };
        w.tick();
        w.change(|s| {
            s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into();
            if inject {
                s["threads"]["thr_syn_b5_1"]["branch"] = "room/thr_syn_private".into();
                for c in s["comments"]["10"].as_array_mut().unwrap() {
                    if c["body"]
                        .as_str()
                        .unwrap()
                        .starts_with("launch-fleet: start checked,")
                    {
                        c["body"] =
                            "launch-fleet: start checked, branch room/thr_syn_private".into();
                    }
                }
            }
        });
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["rule"], "restart", "{doc}");
        assert_eq!(
            doc["actions"][0]["outcome"]["state"],
            if inject { "refused" } else { "done" },
            "{doc}"
        );
        public_records(&w);
        if !inject {
            assert!(
                w.load()["comments"]["10"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|c| c["body"]
                        == "launch-fleet: builder fallback due, branch synthetic-branch-10")
            );
            assert!(w.tick()["actions"].as_array().unwrap().is_empty());
        }
    }
}

#[test]
fn p4_github_only_due_defers_thread_free_identity_to_tick() {
    let w = public_world("p4-due-public");
    w.tick();
    let before = w.calls().len();
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(due.status.success());
    assert_eq!(
        String::from_utf8_lossy(&due.stdout).trim(),
        "fleet #9: candidate #10"
    );
    assert!(w.calls()[before..].iter().all(|(tool, _)| tool == "gh"));
    assert!(w.tick()["actions"].as_array().unwrap().is_empty());
}

#[test]
fn p4_legacy_giveup_targets_its_explicit_thread_across_new_spans() {
    let w = reviewing("p4-legacy-giveup-target", false, true);
    w.change(|s| {
        s["prs"][0]["head"] = NEXT.into();
        s["threads"]["thr_syn_otherreview"] = s["threads"]["thr_syn_b5_2"].clone();
        s["comments"]["110"].as_array_mut().unwrap().extend([
            json!({"id":3001,"body":format!("launch-fleet: review started {NEXT}, thread thr_syn_otherreview"),"created":1793400020000_u64,"updated":1793400020000_u64}),
            json!({"id":3002,"body":format!("launch-fleet: review failed {}, thread thr_syn_b5_2: synthetic stop", fake::HEAD10),"created":1793400030000_u64,"updated":1793400030000_u64})
        ]);
    });
    w.approve(10);
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "adr_0008", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
    assert_eq!(w.load()["spawn_count"], 2);
    public_records(&w);
}

#[test]
fn p4_appended_giveup_retires_every_recheck_alias() {
    for stored in [false, true] {
        let w = reviewing(&format!("p4-appended-giveup-{stored}"), true, stored);
        w.change(|s| {
            s["prs"][0]["head"] = NEXT.into();
            s["comment_time"] = 1793400050000_u64.into();
            s["comments"]["110"].as_array_mut().unwrap().extend([
                json!({"id":3001,"body":format!("launch-fleet: re-check sent {NEXT}"),"created":1793400020000_u64,"updated":1793400020000_u64}),
                json!({"id":3002,"body":format!("launch-fleet: review given up {NEXT}: synthetic stop"),"created":1793400030000_u64,"updated":1793400030000_u64}),
                json!({"id":3003,"body":format!("launch-fleet: review told again {NEXT}"),"created":1793400040000_u64,"updated":1793400040000_u64})
            ]);
        });
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["rule"], "fresh_review", "{doc}");
        assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
        public_records(&w);
    }
}

#[test]
fn p4_conflicting_checked_branches_cannot_receive_ci_messages() {
    let w = reviewing("p4-conflicting-branches", true, false);
    w.approve(10);
    w.change(|s| {
        s["prs"][0]["ci"] = "failure".into();
        s["comments"]["10"].as_array_mut().unwrap().push(json!({"id":3001,"body":"launch-fleet: start checked, branch another-branch","created":1793400020000_u64,"updated":1793400020000_u64}));
    });
    let before = w.writes();
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
    assert_eq!(w.writes(), before);
}

#[test]
fn p4_public_approval_refuses_quoted_words_below_the_heading() {
    let w = public_world("p4-quoted-approval-body");
    w.change(|s| {
        s["comments"]["9"][0]["body"] =
            format!("{}\nJake: \"synthetic approval\"", public_approval()).into()
    });
    assert_eq!(dry(&w)["actions"][0]["rule"], "look");
}
