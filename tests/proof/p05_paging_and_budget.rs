use std::collections::BTreeSet;

use openwiz_core::ops::{Detail, ListRequest};

use crate::support::*;

fn page(offset: usize, limit: usize, detail: Detail) -> ListRequest {
    ListRequest {
        detail,
        offset,
        limit,
        ..ListRequest::default()
    }
}

#[test]
fn long_listing_enriches_only_the_requested_page() {
    let source = ScriptedSource::new(25);
    let env = list_scripted(&source, &page(10, 5, Detail::Long)).expect("list");
    let shown: BTreeSet<String> = ids(&env).into_iter().collect();
    assert_eq!(shown.len(), 5);
    assert_eq!(
        source.detail_ids(),
        shown,
        "detail reads must be for the page only"
    );

    let fake = Fake::new("p05_long_listing_enriches_only_the_page", "normal");
    let env = fake
        .list(&page(0, 2, Detail::Long))
        .expect("ls -l --limit 2");
    let shown: BTreeSet<String> = ids(&env).into_iter().collect();
    let shown_ids: BTreeSet<String> = fake
        .invocations()
        .into_iter()
        .filter(|argv| argv.len() > 2 && argv[0] == "thread" && argv[1] == "show")
        .map(|argv| argv[2].clone())
        .collect();
    assert_eq!(shown_ids, shown, "room-cli thread show only for the page");
}

#[test]
fn the_cli_passes_limit_and_offset() {
    let fake = Fake::new("p05_cli_limit_and_offset", "normal");
    let all = fake.cli_json(&["ls", "--json"]);
    let all: Vec<&str> = all["data"]["sessions"]
        .as_array()
        .expect("sessions")
        .iter()
        .map(|s| s["id"].as_str().expect("id"))
        .collect();
    let page = fake.cli_json(&["ls", "--limit", "2", "--offset", "3", "--json"]);
    let shown: Vec<&str> = page["data"]["sessions"]
        .as_array()
        .expect("sessions")
        .iter()
        .map(|s| s["id"].as_str().expect("id"))
        .collect();
    assert_eq!(shown, all[3..5]);
    assert_eq!(page["coverage"]["counts"]["offset"], 3);
    assert_eq!(page["coverage"]["counts"]["limit"], 2);
    let (code, text, _) = fake.cli(&["ls", "--limit", "2", "--offset", "3"]);
    assert_eq!(code, 0);
    for id in DEFAULT_IDS {
        assert_eq!(
            !row_lines(&text, id).is_empty(),
            shown.contains(&id),
            "{id}:\n{text}"
        );
    }
}

#[test]
fn the_default_page_is_the_first_100_in_stable_order() {
    let source = ScriptedSource::new(150);
    let env = list_scripted(&source, &ListRequest::default()).expect("list");
    let c = env.coverage.counts.as_ref().expect("counts");
    assert_eq!((c.matched, c.offset, c.limit, c.shown), (150, 0, 100, 100));
    let default_page = ids(&env);
    assert_eq!(default_page.len(), 100);

    let everything = ids(&list_scripted(&source, &page(0, 150, Detail::Short)).expect("list"));
    assert_eq!(
        default_page,
        everything[..100],
        "the default page is the first 100 in the stable order"
    );

    let mut reversed_records = source.records.clone();
    reversed_records.reverse();
    let reversed = ScriptedSource::with_records(reversed_records);
    assert_eq!(
        ids(&list_scripted(&reversed, &ListRequest::default()).expect("list")),
        default_page,
        "the source's row order does not change the default page"
    );

    let json = cli_json_with(&source, &["ls", "--json"]);
    let shown: Vec<&str> = json["data"]["sessions"]
        .as_array()
        .expect("sessions")
        .iter()
        .map(|s| s["id"].as_str().expect("id"))
        .collect();
    assert_eq!(shown, default_page);
    assert_eq!(json["coverage"]["counts"]["limit"], 100);
    let (code, text, _) = cli_with(&source, &["ls"]);
    assert_eq!(code, 0);
    let rows: Vec<String> = text.lines().filter_map(row_id).collect();
    assert_eq!(rows.len(), 100, "ls prints 100 rows:\n{text}");
    assert_eq!(
        rows.iter().collect::<BTreeSet<_>>(),
        default_page.iter().collect::<BTreeSet<_>>()
    );
}

#[test]
fn the_order_is_most_recently_updated_first_then_by_id() {
    use openwiz_core::model::{Fact, Timestamp};
    let updated = [
        Fact::Known(Timestamp(T0.0 - 5_000)),
        Fact::Unknown("synthetic unknown time".to_owned()),
        Fact::Known(Timestamp(T0.0 - 1_000)),
        Fact::Known(Timestamp(T0.0 - 5_000)),
        Fact::Unknown("synthetic unknown time".to_owned()),
        Fact::Known(T0),
    ];
    let records: Vec<_> = updated
        .iter()
        .enumerate()
        .map(|(i, at)| {
            let mut r = scripted_record(i + 1);
            r.updated_at = at.clone();
            r
        })
        .collect();
    let expected = [
        "thr_syn_0006",
        "thr_syn_0003",
        "thr_syn_0001",
        "thr_syn_0004",
        "thr_syn_0002",
        "thr_syn_0005",
    ];
    let mut shuffled = records.clone();
    shuffled.rotate_left(2);
    shuffled.swap(0, 3);
    for (label, rows) in [("as listed", records), ("shuffled", shuffled)] {
        let source = ScriptedSource::with_records(rows);
        let env = list_scripted(&source, &ListRequest::default()).expect("list");
        assert_eq!(ids(&env), expected, "{label}");

        let json = cli_json_with(&source, &["ls", "--json"]);
        let shown: Vec<&str> = json["data"]["sessions"]
            .as_array()
            .expect("sessions")
            .iter()
            .map(|s| s["id"].as_str().expect("id"))
            .collect();
        assert_eq!(shown, expected, "{label}: ls --json");

        let (code, text, _) = cli_with(&source, &["ls"]);
        assert_eq!(code, 0);
        let rows: Vec<String> = text.lines().filter_map(row_id).collect();
        assert_eq!(
            rows, expected,
            "{label}: one group, so the text keeps the order:\n{text}"
        );
    }
}
