//! AL1: real adapter/recording fake boundary, synthetic title evidence only.
//! The old fleet fixture predates title and cannot prove it is retained by the
//! stock source independently of closing references or a PR's own number.
use crate::support::{FIXTURES, FakeGh};
use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::fleet::fleets::FleetsSource;
use openwiz_core::fleet::model::NonEmpty;
use openwiz_core::model::Fact;
use serde_json::json;
use std::{
    fs,
    path::Path,
    time::{Duration, Instant},
};

#[test]
fn al1_recorded_pr_list_retains_title_as_stock_evidence_without_closing_references() {
    let fake = FakeGh::new(
        "al1-title-evidence",
        &Path::new(FIXTURES).join("fleets/complete/scenario.json"),
    );
    // Literal approved form, independent of the implementation constant.
    let argv = [
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        "1000",
        "--json",
        "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title",
    ];
    let rows = json!([{"baseRefName":"main","closingIssuesReferences":[],"headRefName":"room/synthetic-al1","headRefOid":"1111111111111111111111111111111111111111","isDraft":false,"mergeCommit":null,"mergedAt":null,"number":95,"state":"OPEN","title":"#902: Synthetic title evidence"}]);
    let scenario = json!({"scenario":"synthetic-al1","synthetic_assumptions":["Every identifier/title and response is synthetic; no live behavior is claimed."],"responses":[{"argv":argv,"stdout":rows.to_string()}]});
    let path = fake.dir.join("al1.json");
    fs::write(&path, scenario.to_string()).unwrap();
    fake.set_scenario(&path);
    let source = GitHubFleets::with_program(fake.program());
    let got = source
        .stock_pull_requests(Instant::now() + Duration::from_secs(5))
        .unwrap();
    assert!(!got.cut_short);
    assert_eq!(got.rows.len(), 1);
    assert_eq!(
        got.rows[0].title,
        Fact::Known(NonEmpty::new("#902: Synthetic title evidence").unwrap())
    );
    let openwiz_core::fleet::fleets::PrRow::Open(pr) = &got.rows[0].pr else {
        panic!("open PR")
    };
    assert_eq!(pr.number.get(), 95);
    assert!(pr.closes.is_empty());
    assert_eq!(fake.invocations(), vec![argv.map(str::to_owned).to_vec()]);
}

#[test]
fn al1_tick_inventory_accepts_the_title_list_without_changing_pr_view_records() {
    let fake = FakeGh::new(
        "al1-tick-title",
        &Path::new(FIXTURES).join("fleets/complete/scenario.json"),
    );
    let argv = [
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        "1000",
        "--json",
        "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title",
    ];
    let row = json!({"baseRefName":"main","closingIssuesReferences":[],"headRefName":"room/synthetic-al1","headRefOid":"1111111111111111111111111111111111111111","isDraft":false,"mergeCommit":null,"mergedAt":null,"number":95,"state":"OPEN","title":"Synthetic title"});
    let path = fake.dir.join("al1-tick.json");
    let write = |row: serde_json::Value| {
        fs::write(&path,json!({"scenario":"synthetic-al1-tick","synthetic_assumptions":["Every field is synthetic; no live behavior is claimed."],"responses":[{"argv":argv,"stdout":json!([row]).to_string()}]}).to_string()).unwrap()
    };
    write(row.clone());
    fake.set_scenario(&path);
    let reader = openwiz_adapter_github::tick::TickReads::new(fake.program());
    let got = reader.pull_requests(Instant::now() + Duration::from_secs(5));
    assert!(
        got.is_ok(),
        "title-bearing inventory must stay readable: {:?}",
        got.err()
    );
    for bad in [
        json!(null),
        json!(false),
        json!(""),
        json!({"known":"Synthetic"}),
    ] {
        let mut v = row.clone();
        v["title"] = bad;
        write(v);
        assert!(
            reader
                .pull_requests(Instant::now() + Duration::from_secs(5))
                .is_err()
        );
    }
    let mut v = row;
    v.as_object_mut().unwrap().remove("title");
    write(v);
    assert!(
        reader
            .pull_requests(Instant::now() + Duration::from_secs(5))
            .is_err()
    );
}
