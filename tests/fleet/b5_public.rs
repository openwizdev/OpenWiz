use super::fake::{self, World};
use serde_json::{Value, json};

fn dry(w: &World) -> Value {
    let out = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

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
fn p4_public_approval_refuses_quoted_words_below_the_heading() {
    let w = public_world("p4-quoted-approval-body");
    w.change(|s| {
        s["comments"]["9"][0]["body"] =
            format!("{}\nJake: \"synthetic approval\"", public_approval()).into()
    });
    assert_eq!(dry(&w)["actions"][0]["rule"], "look");
}

#[test]
fn p4_718_a_missing_or_malformed_record_authors_row_stops_the_tick() {
    let row = "| Record authors | `openwiz[bot]`, `syn-owner` |\n";
    for (case, replacement) in [
        ("missing", String::new()),
        ("empty", "| Record authors |  |\n".to_owned()),
        (
            "unquoted",
            "| Record authors | `openwiz[bot]`, syn-owner |\n".to_owned(),
        ),
        (
            "bad login",
            "| Record authors | `openwiz[bot]`, `-syn` |\n".to_owned(),
        ),
        (
            "extra cell",
            "| Record authors | `openwiz[bot]` | x |\n".to_owned(),
        ),
        ("twice", format!("{row}{row}")),
        ("other section", String::new()),
    ] {
        let w = public_world(&format!("718-row-{}", case.replace(' ', "-")));
        w.change(|s| {
            let mut rules = s["rules"].as_str().unwrap().replace(row, &replacement);
            if case == "other section" {
                rules.push_str(&format!(
                    "## Elsewhere\n| Setting | Value |\n| --- | --- |\n{row}"
                ));
            }
            s["rules"] = rules.into();
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(
            !o.status.success(),
            "{case}: {}",
            String::from_utf8_lossy(&o.stdout)
        );
        assert!(w.writes().is_empty(), "{case}");
    }
}

#[test]
fn p4_github_only_due_defers_thread_free_identity_to_tick() {
    let w = public_world("p4-due-public");
    super::builder_started(&w);
    let before = w.calls().len();
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(due.status.success());
    assert_eq!(
        String::from_utf8_lossy(&due.stdout).trim(),
        "fleet #9: candidate #10"
    );
    assert!(w.calls()[before..].iter().all(|(tool, _)| tool == "gh"));
    assert!(dry(&w)["actions"].as_array().unwrap().is_empty());
}
