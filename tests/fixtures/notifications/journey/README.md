# Notification journey fixtures (#2039)

Shared by `tests/notifications/journey.rs` and
`apps/web/test/browser/notifications-journey.test.mjs`. Each test reads one
fenced block below by its info string. Every value is synthetic. The
service config follows `contracts/service.v1.md`'s example, with a
one-second `notifications` pass. The fake `gh` responses and the saved grill
copy the e11 decisions fixtures (`tests/web-api/e11_decisions_support.rs`);
the tests append the comment pages. Nothing here was observed live.

```json journey-config
{"schema": "openwiz.service-config.v1", "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"}, "project": "prj_syn_0001", "orchestrator_thread": "thr_syn_0001", "service_issue": 901, "github_app": {"app_id": 1001, "installation_id": 2002}, "tick": {"every_s": 3600}, "health": {"every_s": 3600}, "server": {"port": 7370, "allowed_host": "openwiz.example.com", "probe_timeout_s": 10}, "notifications": {"every_s": 1}}
```

```json journey-gh
{"synthetic_assumptions": ["All response shapes, URLs, wording, timestamps, identifiers and headers are synthetic, copied from the e11 decisions fixtures (tests/web-api/e11_decisions_support.rs). The journey test appends the comment pages."], "responses": [{"argv": ["repo", "view", "--json", "nameWithOwner"], "stdout": "{\"nameWithOwner\":\"synthetic-owner/synthetic-repo\"}"}, {"argv": ["api", "repos/{owner}/{repo}/issues/901", "--jq", "{number,body,is_pull_request:has(\"pull_request\")}"], "stdout": "{\"number\":901,\"body\":\"Synthetic source\",\"is_pull_request\":true}"}, {"argv": ["api", "repos/{owner}/{repo}/pulls/901", "--jq", "{number,head_sha:.head.sha}"], "stdout": "{\"number\": 901, \"head_sha\": \"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}"}, {"argv": ["api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-f", "query=query($owner:String!,$name:String!,$number:Int!,$expression:String!){repository(owner:$owner,name:$name){pullRequest(number:$number){number headRefOid} object(expression:$expression){__typename ... on Blob{text isTruncated}}}}", "-F", "number=901", "-f", "expression=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:docs/grills/synthetic-choice.md"], "stdout": "{\"data\": {\"repository\": {\"pullRequest\": {\"number\": 901, \"headRefOid\": \"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}, \"object\": {\"__typename\": \"Blob\", \"text\": \"# Grill: synthetic choice (2099-01-01)\\n\\n## Round 1\\nRisk: ordinary\\n\\n**G1 - Synthetic choice?** Exact context \\u5408\\u6210.\\n\\u27a1\\ufe0f Keep spaces. \\n\\n**Robin:**\\n> A synthetic reply.\\n\\nSettled: none. Open: G1.\\n\", \"isTruncated\": false}}}}"}]}
```
