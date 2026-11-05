//! Synthetic GitHub shapes, including pagination headers; none is live evidence.
#![allow(dead_code)]
use crate::{
    fake::{self, Fake},
    http::TestServer,
    support::FakeGh,
};
use openwiz_adapter_github::decisions::GitHubDecisions;
use openwiz_server::{Config, Decisions, ReadSources};
use serde_json::{Value, json};

use crate::pattern;

fn schema() -> Value {
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/decisions.v1.schema.json")).unwrap();
    fn strip(v: &Value) -> Value {
        match v {
            Value::Object(o) => Value::Object(
                o.iter()
                    .filter(|(k, _)| k.as_str() != "maxItems")
                    .map(|(k, v)| (k.clone(), strip(v)))
                    .collect(),
            ),
            Value::Array(a) => Value::Array(a.iter().map(strip).collect()),
            _ => v.clone(),
        }
    }
    let stripped = strip(&schema);
    assert!(pattern::lint(&stripped).is_empty());
    stripped
}

pub fn schema_accepts(value: &Value) -> bool {
    pattern::validate(&schema(), value).is_empty()
}

pub fn check(value: &Value) {
    let errors = pattern::validate(&schema(), value);
    assert!(errors.is_empty(), "{errors:?}: {value}");
    // The only maxItems rules in this contract are questions and summary.
    for item in value["items"].as_array().unwrap() {
        if let Some(a) = item["request"]["questions"].as_array() {
            assert!(a.len() <= 3);
        }
        if let Some(a) = item["request"]["summary"].as_array() {
            assert!(a.len() <= 10);
        }
    }
}
use std::{
    fs,
    sync::{Arc, Mutex},
};

pub fn record(id: &str, status: &str) -> Value {
    // Literal vectors calculated independently with Python hashlib over the
    // contract's canonical UTF-8 JSON. No production hashing code is used.
    let fingerprint = match id {
        "synthetic-bad" => "4f65b059b73e586271eb98802f69c6d7d0f8570305008054c5a61e024a82a6f7",
        "synthetic-date" => "b9cc1a77f554ed8cd036e494b4af434ea98f109d603de3263514e06305253a46",
        "synthetic-current" => "941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4",
        "synthetic-open" => "a362c2cc752a0ee9f7be29ef3fdf2f29286ae9b8a2611e68515ffe8f51a4bf49",
        "synthetic-answered" => "48a40119c6f28c9a02608961c5613f5e9bad48269d0fba632df9b598a2b3a568",
        "synthetic-first" => "27234f8810be4235c8b6bf45176f1a1e2c6006e44570a2eff939f0cf11877540",
        "synthetic-last" => "5b27e87779bb33c51e8e816aa00f6443720c6e45aba55e8c2dd3f05b77095e87",
        "synthetic-duplicate" => "cbfd83689b2cad7b2ba0d5712246bad3ab10b8fbf3eedd6828f1fac97808419f",
        "synthetic-round" => "145702a2b34407c469d0eef221420d07eebec61a5398388648d67b2d9c9a605e",
        _ => panic!("add a literal independent fingerprint for this synthetic proposal"),
    };
    json!({"schema":"openwiz.decisions.v1", "kind":"grill_round", "id":id,
        "status": status, "fingerprint":fingerprint, "risk":"ordinary",
        "grill_file":"docs/grills/synthetic-choice.md", "round":1,
        "questions":[{"id":"G1", "decides":"Synthetic choice?", "context":"Exact context 合成.", "recommendation":"Keep spaces. "}],
        "answered": if status == "resolved" {json!(["G1"])} else {json!([])}})
}

pub fn comment(id: u64, body: &str) -> Value {
    json!({"id":id,"body":body,"issue_url":"https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/901",
        "created_at":"1970-01-01T00:00:01Z", "updated_at":"1970-01-01T00:00:02Z"})
}

pub fn fenced(record: &Value) -> String {
    format!("Synthetic prose.\n```json\n{record}\n```\n")
}

pub fn argv(page: u64, size: u64) -> Vec<String> {
    vec![
        "api".into(),
        "--include".into(),
        format!(
            "repos/{{owner}}/{{repo}}/issues/comments?per_page={size}&sort=created&direction=desc&page={page}"
        ),
        "--jq".into(),
        "[.[] | {id,body,issue_url,created_at,updated_at}]".into(),
    ]
}

pub fn page(rows: &[Value], total: u64, size: u64) -> String {
    let link = if total > size {
        format!(
            "Link: <https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/comments?per_page={size}&sort=created&direction=desc&page={}>; rel=\"last\"\r\n",
            total.div_ceil(size)
        )
    } else {
        String::new()
    };
    format!("HTTP/2.0 200 OK\r\n{link}\r\n{}", json!(rows))
}

pub fn fake(name: &str, rows: Vec<Value>) -> FakeGh {
    let gh = crate::support::world_fake(name, &crate::support::world::World::default());
    let total = rows.len() as u64;
    let first: Vec<_> = rows.iter().take(1).cloned().collect();
    let mut scenario = json!({"synthetic_assumptions":["All response shapes, URLs, wording, timestamps, identifiers and headers are synthetic."],
    "responses":[
        {"argv":["repo","view","--json","nameWithOwner"], "stdout":"{\"nameWithOwner\":\"synthetic-owner/synthetic-repo\"}"},
        {"argv":argv(1,1),"stdout":page(&first,total,1)},
        {"argv":["api","repos/{owner}/{repo}/issues/901","--jq","{number,body,is_pull_request:has(\"pull_request\")}"],
             "stdout":"{\"number\":901,\"body\":\"Synthetic source\",\"is_pull_request\":true}"},
            {"argv":["api","repos/{owner}/{repo}/issues/902","--jq","{number,body,is_pull_request:has(\"pull_request\")}"],
             "stdout":"{\"number\":902,\"body\":\"Synthetic spec source\",\"is_pull_request\":false}"}
    ]});
    for (i, chunk) in rows.chunks(100).enumerate() {
        scenario["responses"]
            .as_array_mut()
            .unwrap()
            .push(json!({"argv":argv(i as u64+1,100),"stdout":page(chunk,total,100)}));
    }
    let path = gh.dir.join("decisions.json");
    fs::write(&path, scenario.to_string()).unwrap();
    gh.set_scenario(&path);
    saved_grill(&gh, "Synthetic source");
    gh
}

pub fn change(gh: &FakeGh, edit: impl FnOnce(&mut Value)) {
    let path = gh.dir.join("decisions.json");
    let mut scenario = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    edit(&mut scenario);
    fs::write(path, scenario.to_string()).unwrap();
}

pub fn serve(gh: &FakeGh, room: &Fake) -> TestServer {
    serve_with(
        gh,
        room,
        Config::default(),
        Ok(None),
        Arc::new(fake::clock()),
    )
}

pub fn serve_with(
    gh: &FakeGh,
    room: &Fake,
    config: Config,
    target: Result<Option<String>, ()>,
    clock: Arc<dyn openwiz_core::ops::Clock>,
) -> TestServer {
    serve_source(
        room,
        config,
        target,
        clock,
        GitHubDecisions::with_program(gh.program()),
    )
}

pub fn serve_source(
    room: &Fake,
    config: Config,
    target: Result<Option<String>, ()>,
    clock: Arc<dyn openwiz_core::ops::Clock>,
    github: GitHubDecisions,
) -> TestServer {
    let listener = openwiz_server::bind(0).unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let lines = log.clone();
    let server = openwiz_server::start_with_read_sources(
        listener,
        config,
        Arc::new(room.source()),
        clock,
        Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
        ReadSources {
            fleets: None,
            plan: None,
            decisions: Some(Decisions { github, target }),
        },
    )
    .unwrap();
    TestServer {
        addr: server.local_addr(),
        server,
        log,
    }
}

pub fn serve_targets(
    gh: &FakeGh,
    room: &Fake,
    targets: openwiz_server::NotificationTargets,
) -> TestServer {
    serve_targets_with_clock(gh, room, targets, Arc::new(fake::clock()))
}

pub fn serve_targets_with_clock(
    gh: &FakeGh,
    room: &Fake,
    targets: openwiz_server::NotificationTargets,
    clock: Arc<dyn openwiz_core::ops::Clock>,
) -> TestServer {
    let listener = openwiz_server::bind(0).unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let lines = log.clone();
    let server = openwiz_server::start_with_notification_targets(
        listener,
        Config::default(),
        Arc::new(room.source()),
        clock,
        Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
        openwiz_server::NotificationReadSources {
            reads: ReadSources {
                decisions: Some(Decisions {
                    github: GitHubDecisions::with_program(gh.program()),
                    target: Ok(None),
                }),
                ..ReadSources::default()
            },
            targets,
        },
        None,
    )
    .unwrap();
    TestServer {
        addr: server.local_addr(),
        server,
        log,
    }
}

// Synthetic immutable PR-head file reads. The saved human source deliberately
// contains no request block; each test supplies the independent saved source.
pub const GRILL_HEAD: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
pub const GRILL_QUERY: &str = "query($owner:String!,$name:String!,$number:Int!,$expression:String!){repository(owner:$owner,name:$name){pullRequest(number:$number){number headRefOid} object(expression:$expression){__typename ... on Blob{text isTruncated}}}}";

pub fn grill_head_argv() -> Value {
    json!([
        "api",
        "repos/{owner}/{repo}/pulls/901",
        "--jq",
        "{number,head_sha:.head.sha}"
    ])
}

pub fn grill_blob_argv() -> Value {
    json!([
        "api",
        "graphql",
        "-F",
        "owner={owner}",
        "-F",
        "name={repo}",
        "-f",
        format!("query={GRILL_QUERY}"),
        "-F",
        "number=901",
        "-f",
        format!("expression={GRILL_HEAD}:docs/grills/synthetic-choice.md")
    ])
}

pub fn saved_grill(gh: &FakeGh, text: &str) {
    change(gh, |scenario| {
        scenario["responses"]
            .as_array_mut()
            .unwrap()
            .retain(|r| r["argv"] != grill_head_argv() && r["argv"] != grill_blob_argv());
        scenario["responses"].as_array_mut().unwrap().extend([
            json!({"argv":grill_head_argv(),"stdout":json!({"number":901,"head_sha":GRILL_HEAD}).to_string()}),
            json!({"argv":grill_blob_argv(),"stdout":json!({"data":{"repository":{"pullRequest":{"number":901,"headRefOid":GRILL_HEAD},"object":{"__typename":"Blob","text":text,"isTruncated":false}}}}).to_string()}),
        ]);
    });
}
