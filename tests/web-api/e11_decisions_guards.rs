//! EP3: exact read forms and the existing HTTP guards protect the new read.
use crate::{e11_decisions_support as s, fake::Fake};
use serde_json::json;

#[test]
fn e11_decisions_refuses_methods_queries_bodies_and_foreign_hosts_before_reads() {
    let room = Fake::new("e11_guard_room", "normal");
    let gh = s::fake("e11_guard_gh", vec![]);
    let server = s::serve(&gh, &room);
    for method in [
        "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE",
    ] {
        let response = server.request(method, "/api/v1/decisions");
        assert_eq!(response.status, 405, "{method}");
        assert_eq!(response.header("Allow"), Some("GET"));
        crate::c3_routes::headers(&response);
        if method == "HEAD" {
            assert!(response.body.is_empty());
            assert_eq!(response.header("Content-Length"), None);
        }
    }
    for query in [
        "?",
        "?source=synthetic-secret",
        "?target=thr_syn_forged",
        "?x=1&x=2",
        "?schema=1",
    ] {
        let response = server.get(&format!("/api/v1/decisions{query}"));
        assert_eq!(response.status, 400, "{query}");
        crate::c3_routes::headers(&response);
    }
    for header in [
        "Content-Length: 1\r\n",
        "Transfer-Encoding: chunked\r\n",
        "Content-Length: 0\r\nContent-Length: 0\r\n",
    ] {
        let response = server.send(
            format!(
                "GET /api/v1/decisions HTTP/1.1\r\nHost: {}\r\n{header}\r\nx",
                server.host()
            )
            .as_bytes(),
        );
        assert_eq!(response.status, 400);
    }
    let response = server.send(b"GET /api/v1/decisions HTTP/1.1\r\nHost: foreign.invalid\r\n\r\n");
    assert_eq!(response.status, 421);
    let log = server.settled_log();
    assert_eq!(log.lines().count(), 17, "{log}");
    for secret in ["synthetic-secret", "thr_syn_forged", "source=", "schema="] {
        assert!(!log.contains(secret), "{log}");
    }
    assert!(room.invocations().is_empty());
    assert!(gh.invocations().is_empty());
}

#[test]
fn e11_decisions_allowlist_accepts_only_the_exact_read_forms() {
    use openwiz_adapter_github::{allowlist::Invocation, decisions};
    for args in [
        s::argv(1, 1),
        s::argv(2, 100),
        vec![
            "repo".into(),
            "view".into(),
            "synthetic-owner/work".into(),
            "--json".into(),
            "nameWithOwner,isPrivate".into(),
        ],
        vec![
            "api".into(),
            "--include".into(),
            "repos/other/repo/issues/comments?per_page=100&sort=created&direction=desc&page=1"
                .into(),
            "--jq".into(),
            decisions::COMMENT_FIELDS.into(),
        ],
        vec![
            "api".into(),
            "repos/{owner}/{repo}/issues/901".into(),
            "--jq".into(),
            decisions::SUBJECT_FIELDS.into(),
        ],
    ] {
        let refs: Vec<_> = args.iter().map(String::as_str).collect();
        assert!(decisions::allows(&refs));
        assert!(Invocation::new(&refs).is_some());
        for extra in ["--method", "POST", "--field", "body=synthetic"] {
            let mut bad = refs.clone();
            bad.push(extra);
            assert!(!decisions::allows(&bad));
            assert!(Invocation::new(&bad).is_none());
        }
    }
    for path in [
        "repos/{owner}/{repo}/issues/comments?per_page=100&sort=created&direction=asc&page=1",
        "repos/{owner}/{repo}/issues/comments?per_page=100&sort=created&direction=desc&page=0",
        "repos/{owner}/{repo}/issues/comments?per_page=100&sort=created&direction=desc&page=01",
        "repos/{owner}/{repo}/issues/comments?per_page=100&sort=created&direction=desc&page=1&method=POST",
        "repos/{owner}/{repo}/issues/comments?per_page=100&sort=created&direction=desc&page=١",
        "repos/{owner}/{repo}/issues/comments?per_page=101&sort=created&direction=desc&page=1",
        "repos/other/repo/extra/issues/comments?per_page=100&sort=created&direction=desc&page=1",
        "repos/other/../issues/comments?per_page=100&sort=created&direction=desc&page=1",
        "repos/other/./issues/comments?per_page=100&sort=created&direction=desc&page=1",
    ] {
        let args = ["api", "--include", path, "--jq", decisions::COMMENT_FIELDS];
        assert!(!decisions::allows(&args));
        assert!(Invocation::new(&args).is_none());
    }
    for n in ["0", "01", "-1", "1/../2", "1?x=1", "18446744073709551616"] {
        let path = format!("repos/{{owner}}/{{repo}}/issues/{n}");
        let args = ["api", &path, "--jq", decisions::SUBJECT_FIELDS];
        assert!(!decisions::allows(&args));
        assert!(Invocation::new(&args).is_none());
    }
}

#[test]
fn e11_decisions_grill_reads_allow_only_pinned_scoped_sources() {
    use openwiz_adapter_github::{allowlist::Invocation, decisions};
    for args in [s::grill_head_argv(), s::grill_blob_argv()] {
        let args: Vec<_> = args
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert!(decisions::allows(&args));
        assert!(Invocation::new(&args).is_some());
        for extra in ["--method", "POST", "--hostname", "example.invalid"] {
            let mut bad = args.clone();
            bad.push(extra);
            assert!(!decisions::allows(&bad));
        }
    }
    for expression in [
        "expression=main:docs/grills/synthetic-choice.md".to_owned(),
        format!("expression={}:docs/grills/../secret.md", s::GRILL_HEAD),
        format!("expression={}:docs/grills/-synthetic.md", s::GRILL_HEAD),
        format!("expression={}:docs/grills/synthetic.md?x=1", s::GRILL_HEAD),
        format!("expression={}:other/synthetic.md", s::GRILL_HEAD),
        format!("expression={}:docs/grills/synthetic.md", "A".repeat(40)),
    ] {
        let mut args = s::grill_blob_argv();
        *args.as_array_mut().unwrap().last_mut().unwrap() = json!(expression);
        let refs: Vec<_> = args
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert!(!decisions::allows(&refs), "{expression}");
    }
}
