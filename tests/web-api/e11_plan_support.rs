//! Synthetic GitHub response builders; no live IDs, bodies or accounts.
#![allow(dead_code)]
use crate::pattern;
use crate::{
    fake::{self, Fake},
    http::TestServer,
    support::FakeGh,
};
use openwiz_adapter_github::plan::Request;
use openwiz_server::{Config, Plan};
use serde_json::{Value, json};
use std::fs;
use std::sync::{Arc, Mutex};

pub const REPO: &str = "https://github.com/synthetic-owner/example-repo";

pub fn page(nodes: Vec<Value>) -> Value {
    json!({"totalCount":nodes.len(),"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":nodes})
}
pub fn link(n: u64) -> Value {
    json!({"number":n,"url":format!("{REPO}/issues/{n}")})
}
pub fn issue(
    n: u64,
    parent: Option<u64>,
    children: &[u64],
    blockers: &[u64],
    labels: &[&str],
) -> Value {
    json!({"number":n,"title":format!("Synthetic issue {n}"),"url":format!("{REPO}/issues/{n}"),"state":"OPEN",
        "milestone":null,"parent":parent.map(link),
        "labels":page(labels.iter().map(|s| json!({"name":s})).collect()),
        "subIssues":page(children.iter().map(|&n|link(n)).collect()),
        "blockedBy":page(blockers.iter().map(|&n|link(n)).collect()),
        "closedByPullRequestsReferences":page(vec![])})
}
pub fn answer(request: Request, cursor: Option<&str>, value: Value) -> Value {
    json!({"argv":request.argv(cursor),"stdout":json!({"data":{"repository":value}}).to_string()})
}
pub fn responses(issues: Vec<Value>, milestones: Vec<Value>) -> Vec<Value> {
    vec![
        json!({"argv":["repo","view","--json","nameWithOwner,url"],"stdout":json!({"nameWithOwner":"synthetic-owner/example-repo","url":REPO}).to_string()}),
        answer(
            Request::Milestones,
            None,
            json!({"milestones":page(milestones)}),
        ),
        answer(Request::Issues, None, json!({"issues":page(issues)})),
    ]
}
pub fn github(name: &str, responses: Vec<Value>) -> FakeGh {
    let fake = FakeGh::new(
        name,
        std::path::Path::new(crate::support::FIXTURES)
            .join("fleets/complete/scenario.json")
            .as_path(),
    );
    let path = fake.dir.join("plan.json");
    fs::write(&path,json!({"scenario":"synthetic-plan","synthetic_assumptions":["All identifiers, titles, URLs, timestamps and paginated GraphQL shapes are synthetic; no live behavior is claimed."],"responses":responses}).to_string()).unwrap();
    fake.set_scenario(&path);
    fake
}
pub fn serve(room: &Fake, gh: &FakeGh, config: Config) -> TestServer {
    serve_clock(room, gh, config, Arc::new(fake::clock()))
}
pub fn serve_clock(
    room: &Fake,
    gh: &FakeGh,
    config: Config,
    clock: Arc<dyn openwiz_core::ops::Clock>,
) -> TestServer {
    let log = Arc::new(Mutex::new(Vec::new()));
    let lines = log.clone();
    let server = openwiz_server::start_with_plan(
        openwiz_server::bind(0).unwrap(),
        config,
        Arc::new(room.source()),
        clock,
        Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
        None,
        Some(Plan::with_program(gh.program())),
    )
    .unwrap();
    TestServer {
        addr: server.local_addr(),
        server,
        log,
    }
}
pub fn read(s: &TestServer) -> Value {
    let r = s.get("/api/v1/plan");
    assert_eq!(r.status, 200, "{}", r.text());
    let value = r.json();
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/plan.v1.schema.json")).unwrap();
    assert_eq!(
        pattern::validate(&schema, &value),
        Vec::<String>::new(),
        "{value:#}"
    );
    value
}
pub fn row(value: &Value, n: u64) -> &Value {
    value["tickets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["number"] == n)
        .unwrap()
}

pub const HEAD: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
pub fn merge(n: u64) -> String {
    format!("{n:040x}")
}
pub fn closing(issue: &mut Value, prs: &[u64]) {
    issue["closedByPullRequestsReferences"] = page(
        prs.iter()
            .map(|&n| json!({"number":n,"url":format!("{REPO}/pull/{n}")}))
            .collect(),
    );
}
pub fn pr(n: u64, ticket: u64, state: &str, draft: bool) -> Value {
    json!({"number":n,"url":format!("{REPO}/pull/{n}"),"state":state,"isDraft":draft,"headRefName":format!("synthetic-{n}"),"headRefOid":HEAD,"baseRefName":"main",
        "mergeCommit":if state=="MERGED"{json!({"oid":merge(n)})}else{Value::Null},"mergedAt":if state=="MERGED"{json!("2026-01-01T00:00:00Z")}else{Value::Null},
        "closingIssuesReferences":page(vec![json!({"id":format!("I_synthetic_{ticket}"),"number":ticket,"url":format!("{REPO}/issues/{ticket}"),"repository":{"nameWithOwner":"synthetic-owner/example-repo"}})])})
}
pub fn pr_responses(
    n: u64,
    ticket: u64,
    state: &str,
    draft: bool,
    checks: Value,
    bodies: Vec<&str>,
    on_base: bool,
) -> Vec<Value> {
    let mut responses = vec![answer(
        Request::Pr(n),
        None,
        json!({"pullRequest":pr(n,ticket,state,draft)}),
    )];
    if state == "OPEN" {
        responses.push(json!({"argv":["pr","checks",n.to_string(),"--json","bucket,name"],"stdout":checks.to_string()}));
        responses.push(answer(Request::Relation(n,openwiz_adapter_github::plan::Relation::Comments),None,json!({"pullRequest":{"comments":page(bodies.into_iter().map(|s|json!({"body":s})).collect())}})));
    } else if state == "MERGED" {
        responses.push(json!({"argv":["api",format!("repos/{{owner}}/{{repo}}/compare/main...{}",merge(n)),"--jq","{ahead_by: .ahead_by}"],"stdout":json!({"ahead_by":if on_base{0}else{1}}).to_string()}));
    }
    responses
}
