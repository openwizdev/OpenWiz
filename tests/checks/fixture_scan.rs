use std::fs;
use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures");
const FAKE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fake-room-cli");

const OBSERVED_KEYS: &[&str] = &[
    "id",
    "projectId",
    "providerId",
    "title",
    "titleFallback",
    "status",
    "visibility",
    "queuedWork",
    "environmentWorkspaceDisplayKind",
    "lastReadAt",
    "latestAttentionAt",
    "createdAt",
    "updatedAt",
    "hasPendingInteraction",
    "parentThreadId",
    "environmentId",
    "environmentHostId",
    "environmentPath",
    "environmentProviderId",
    "environmentIsWorktree",
    "environmentBranchName",
    "archivedAt",
    "sectionId",
    "sourceThreadId",
    "originKind",
    "originPluginId",
    "pinnedAt",
    "deletedAt",
    "pinSortKey",
    "environmentName",
    "purpose",
    "text",
    "percent",
    "sourceSeq",
    "activity",
    "activeBackgroundAgentCount",
    "activeBackgroundCommandCount",
    "activeGoalCount",
    "activePlanModeCount",
    "activeWorkflowCount",
    "runtime",
    "displayStatus",
    "hostReconnectGraceExpiresAt",
    "executionTarget",
    "projectCopy",
    "phase",
    "completed",
    "total",
    "queuedMessageCount",
    "canSpawnChild",
    "thread",
    "execution",
    "model",
    "reasoningLevel",
    "environment",
    "pendingTodos",
    "name",
    "hostId",
    "path",
    "isGitRepo",
    "isWorktree",
    "branchName",
    "baseBranch",
    "defaultBranch",
    "mergeBaseBranch",
    "lifecycle",
    "retireAt",
    "teardown",
    "environmentProviderSelection",
    "machine",
    "type",
    "inputs",
    "environmentProviderInstanceKey",
    "managed",
    "workspaceProvisionType",
    "pullRequest",
    "output",
    "error",
    "kind",
    "gitRemoteUrl",
    "sources",
    "isDefault",
    "machineProviderId",
    "suspendedAt",
    "message",
    "pendingLog",
    "maxPermissionMode",
    "lastSeenAt",
    "lastRejectedProtocolVersion",
];

const OBSERVED_SENT_KEYS: &[&str] = &["threadId", "ok", "delivery", "mode"];

const OBSERVED_QUEUED_KEYS: &[&str] = &[
    "queuedMessage",
    "id",
    "initiator",
    "senderThreadId",
    "threadId",
    "content",
    "type",
    "text",
    "mentions",
    "model",
    "reasoningLevel",
    "permissionMode",
    "serviceTier",
    "hardQueue",
    "sendAt",
    "waitingOn",
    "kind",
    "failureReason",
    "payload",
    "editable",
    "createdAt",
    "updatedAt",
];
const OBSERVED_QUEUED_LABELS: &[&str] = &["agent", "user", "inline"];
const SYNTHETIC_QUEUED_UUID: &str = "00000000-0000-4000-8000-000000000001";
const SYNTHETIC_QUEUED_ID: &str = "qmsg_syn_0001";

const DOCUMENTED_SEND_KEYS: &[&str] = &[
    "delivery",
    "queuedMessage",
    "waitingOn",
    "sendAt",
    "initiator",
    "senderThreadId",
    "scope",
    "threadId",
    "seq",
    "data",
    "requestId",
    "source",
    "input",
    "target",
    "request",
    "serviceTier",
    "permissionMode",
];

const DOCUMENTED_SEND_LABELS: &[&str] = &[
    "sent",
    "queued",
    "waiting",
    "time",
    "thread-busy",
    "turn-starting",
    "provisioning",
    "host-offline",
    "interaction",
    "plugin",
];

const NEW_THREAD_KEYS: &[&str] = &[
    "ready",
    "harnesses",
    "plan",
    "macAccessLevel",
    "planUsage",
    "credits",
    "creditsLimit",
    "extraCredits",
    "extraCreditsTotal",
    "og",
    "localLogins",
    "previews",
    "count",
    "explained",
    "state",
    "issue",
    "attachments",
    "compact",
    "copyLogins",
    "macAccess",
    "macAccessSupported",
    "queue_cancel",
    "queue_edit",
    "queue_reorder",
    "rewind",
    "signingIn",
    "steer",
    "teleport",
    "usedCloud",
    "workspaces",
    "macAccessLevels",
    "lastCloudAt",
    "cloudQueue",
    "repository",
    "signInError",
    "storage",
    "sync",
    "reasoning_levels",
    "provider",
    "models",
    "files",
    "images",
    "goal",
    "prompt_reasoning",
    "provider_selection",
    "service_tier",
    "skill_mentions",
    "subagents",
    "usage",
    "lastError",
];

const NEW_THREAD_LABELS: &[&str] = &[
    "pi", "cursor", "fx", "opencode", "hermes", "devin", "openclaw", "none", "minimal", "low",
    "medium", "xhigh", "max", "ultra", "pending", "starting",
];

const LABELS: &[&str] = &[
    "idle",
    "active",
    "error",
    "claude-code",
    "codex",
    "acp-hermes-agent",
    "visible",
    "hidden",
    "none",
    "project-checkout",
    "personal-workspace",
    "other",
    "unmanaged-worktree",
    "cloud",
    "complete",
    "personal",
    "standard",
    "local_path",
    "persistent",
    "connected",
    "full",
    "high",
];

const SCENARIO_KEYS: &[&str] = &[
    "scenario",
    "description",
    "extends",
    "synthetic_assumptions",
    "responses",
    "argv",
    "stdout_file",
    "stdout",
    "stderr",
    "exit",
    "hang",
    "any_text",
];

const ARGV_WORDS: &[&str] = &[
    "--version",
    "thread",
    "list",
    "--json",
    "--include-hidden",
    "--include-archived",
    "project",
    "--include-personal",
    "--hidden",
    "machine",
    "show",
    "output",
];

const SEND_ARGV_WORDS: &[&str] = &["tell", "--mode", "queue", "steer", "--"];

const ERROR_LINES: &[&str] = &[
    "Error: HTTP 404: Thread not found",
    "Error: HTTP 500: Synthetic server error",
    "Error: HTTP 500: Synthetic private version marker",
];

const SEND_ERROR_LINES: &[&str] = &[
    "Error: HTTP 400: Invalid input",
    "Error: HTTP 400: Unsupported mode",
];

const FAKE_GH: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fake-gh");

const GITHUB_KEYS: &[&str] = &[
    "__typename",
    "active_lock_reason",
    "additions",
    "admin",
    "ahead_by",
    "allow_forking",
    "archive_url",
    "archived",
    "archived_at",
    "archived_by",
    "assignee",
    "assignees",
    "assignees_url",
    "author",
    "authorAssociation",
    "author_association",
    "authoredDate",
    "authors",
    "autoMergeRequest",
    "avatar_url",
    "baseRefName",
    "baseRefOid",
    "base_commit",
    "behind_by",
    "blob_url",
    "blobs_url",
    "blockedBy",
    "blocked_by",
    "blocking",
    "body",
    "branches_url",
    "bucket",
    "changeType",
    "changedFiles",
    "changes",
    "clone_url",
    "closed",
    "closedAt",
    "closedByPullRequestsReferences",
    "closed_at",
    "closed_issues",
    "closingIssuesReferences",
    "collaborators_url",
    "color",
    "comment_count",
    "comments",
    "comments_url",
    "commit",
    "commits",
    "commits_url",
    "committedDate",
    "committer",
    "compare_url",
    "completed",
    "completedAt",
    "conclusion",
    "confused",
    "contents_url",
    "contributors_url",
    "createdAt",
    "created_at",
    "creator",
    "data",
    "date",
    "default",
    "defaultBranchRef",
    "default_branch",
    "deletions",
    "deployments_url",
    "description",
    "detailsUrl",
    "diff_url",
    "disabled",
    "downloads_url",
    "dueOn",
    "due_on",
    "email",
    "event",
    "events_url",
    "eyes",
    "filename",
    "files",
    "followers_url",
    "following_url",
    "fork",
    "forks",
    "forks_count",
    "forks_url",
    "fullDatabaseId",
    "full_name",
    "gists_url",
    "git_commits_url",
    "git_refs_url",
    "git_tags_url",
    "git_url",
    "gravatar_id",
    "hasNextPage",
    "has_discussions",
    "has_downloads",
    "has_issues",
    "has_pages",
    "has_projects",
    "has_pull_requests",
    "has_wiki",
    "headRefName",
    "headRefOid",
    "headRepository",
    "headRepositoryOwner",
    "heart",
    "homepage",
    "hooks_url",
    "hooray",
    "html_url",
    "id",
    "includesCreatedEdit",
    "isCrossRepository",
    "isDefault",
    "isDraft",
    "isMinimized",
    "isPinned",
    "isPrivate",
    "is_bot",
    "is_template",
    "issue",
    "issueDependenciesSummary",
    "issueType",
    "issue_comment_url",
    "issue_dependencies_summary",
    "issue_events_url",
    "issues_url",
    "keys_url",
    "label",
    "labels",
    "labels_url",
    "language",
    "languages_url",
    "latestReviews",
    "laugh",
    "license",
    "link",
    "locked",
    "login",
    "maintain",
    "maintainerCanModify",
    "mergeCommit",
    "mergeStateStatus",
    "merge_base_commit",
    "mergeable",
    "merged",
    "mergedAt",
    "mergedBy",
    "merges_url",
    "message",
    "messageBody",
    "messageHeadline",
    "milestone",
    "milestones_url",
    "minimizedReason",
    "mirror_url",
    "name",
    "nameWithOwner",
    "node_id",
    "nodes",
    "notifications_url",
    "number",
    "oid",
    "open_issues",
    "open_issues_count",
    "organizations_url",
    "owner",
    "pageInfo",
    "parent",
    "parent_issue_url",
    "parents",
    "patch",
    "patch_url",
    "path",
    "payload",
    "percentCompleted",
    "percent_completed",
    "performed_via_github_app",
    "permalink_url",
    "permissions",
    "pinned_comment",
    "potentialMergeCommit",
    "private",
    "pull",
    "pull_request_creation_policy",
    "pulls_url",
    "push",
    "pushed_at",
    "raw_url",
    "reactionGroups",
    "reactions",
    "reason",
    "received_events_url",
    "releases_url",
    "repos_url",
    "repository",
    "repository_url",
    "reviewDecision",
    "reviewRequests",
    "reviews",
    "rocket",
    "sha",
    "signature",
    "site_admin",
    "size",
    "source",
    "ssh_url",
    "stargazers_count",
    "stargazers_url",
    "starred_url",
    "startedAt",
    "state",
    "stateReason",
    "state_reason",
    "status",
    "statusCheckRollup",
    "statuses_url",
    "subIssues",
    "subIssuesSummary",
    "sub_issues_summary",
    "subscribers_url",
    "subscription_url",
    "subscriptions_url",
    "svn_url",
    "tags_url",
    "teams_url",
    "timelineItems",
    "timeline_url",
    "title",
    "topics",
    "total",
    "totalBlockedBy",
    "totalBlocking",
    "totalCount",
    "total_blocked_by",
    "total_blocking",
    "total_commits",
    "total_count",
    "tree",
    "trees_url",
    "triage",
    "type",
    "updatedAt",
    "updated_at",
    "url",
    "user",
    "user_view_type",
    "verification",
    "verified",
    "verified_at",
    "viewerDidAuthor",
    "visibility",
    "watchers",
    "watchers_count",
    "web_commit_signoff_required",
    "willCloseTarget",
    "workflow",
    "workflowName",
];

const GITHUB_LABELS: &[&str] = &[
    "BLOCKED",
    "CANCELLED",
    "CLEAN",
    "CLOSED",
    "COMPLETED",
    "CheckRun",
    "CrossReferencedEvent",
    "FAILURE",
    "IN_PROGRESS",
    "Issue",
    "LabeledEvent",
    "MERGEABLE",
    "MERGED",
    "OPEN",
    "OWNER",
    "PRIVATE",
    "PullRequest",
    "SUCCESS",
    "UNKNOWN",
    "User",
    "added",
    "ahead",
    "identical",
    "modified",
    "open",
    "pass",
    "pending",
    "private",
    "pull_request",
    "ready-for-agent",
    "ready-for-human",
    "needs-info",
    "needs-triage",
    "accessibility",
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
    "main",
];

const GITHUB_DOCUMENTED_LABELS: &[&str] = &["held", "fail", "skipping", "cancel"];

const GITHUB_SCENARIO_KEYS: &[&str] = &[
    "scenario",
    "description",
    "synthetic_assumptions",
    "extends",
    "responses",
];
const GITHUB_RESPONSE_KEYS: &[&str] = &[
    "argv",
    "stdout",
    "stdout_file",
    "stderr",
    "exit",
    "delay_ms",
    "hang",
];

fn files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read dir") {
        let path = entry.expect("entry").path();
        if path.is_dir() {
            files(&path, out);
        } else {
            out.push(path);
        }
    }
}

fn all_files() -> Vec<PathBuf> {
    let mut out = Vec::new();
    files(Path::new(FIXTURES), &mut out);
    files(Path::new(FAKE), &mut out);
    files(Path::new(FAKE_GH), &mut out);
    out.sort();
    out
}

const RELEASE_CANDIDATE_KEYS: &[&str] = &[
    "anchor",
    "app_permissions",
    "archive_sha256",
    "artifacts",
    "artifacts_sha256",
    "attempt_id",
    "authority",
    "binding_sha256",
    "build_id",
    "build_receipt",
    "bytes",
    "candidate",
    "candidate_sha256",
    "changelog",
    "ci",
    "claims",
    "commit",
    "coverage",
    "cutover",
    "decided_at",
    "decisions",
    "evidence",
    "evidence_class",
    "finished_at",
    "gaps",
    "gates",
    "identity",
    "immutable",
    "included_versions",
    "inputs_sha256",
    "install",
    "kit",
    "kit_sha256",
    "manifest_sha256",
    "name",
    "new",
    "notes_sha256",
    "op",
    "original_ship_at",
    "outcome",
    "patch",
    "path",
    "payload_sha256",
    "phases",
    "pointer",
    "preparation_started_at",
    "prerelease",
    "privacy",
    "product",
    "products",
    "promise",
    "promises",
    "publication",
    "reason",
    "record",
    "record_sha256",
    "release_version",
    "repository",
    "required",
    "risk",
    "role",
    "route",
    "schema",
    "schema_valid",
    "scope_sha256",
    "section_sha256",
    "send",
    "sha256",
    "ship",
    "smoke",
    "source",
    "spending",
    "started_at",
    "status",
    "tag",
    "tag_object",
    "target",
    "timing",
    "tree",
    "utf8",
    "value",
    "verification",
    "verified_at",
    "version",
];
const RELEASE_CANDIDATE_LABELS: &[&str] = &[
    "openwiz.release-candidate.v1",
    "openwiz.product.v1",
    "openwizdev/OpenWiz",
    "example/private",
    "cli",
    "server",
    "service",
    "web",
    "runtime",
    "native-query",
    "embedded-record",
    "web-build",
    "tracked-tree",
    "archive",
    "manifest",
    "manifest_alias",
    "manifest_checksum",
    "checksums",
    "SHA256SUMS",
    "yes",
    "no",
    "unknown",
    "live",
    "fixture",
    "dry-run",
    "ci",
    "source-inspection",
    "pass",
    "fail",
    "incomplete",
    "uncertain",
    "complete",
    "failed",
    "changelog_wait",
    "queue",
    "build",
    "checks",
    "publish",
    "install",
    "other",
    "update",
    "add",
    "replace",
    "remove",
    "refuse",
    "ship",
];
const RELEASE_CANDIDATE_TARGETS: &[&str] = &[
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
];
const RELEASE_CANDIDATE_POINTERS: &[&str] = &[
    "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001",
    "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002",
];

fn release_candidate_version(s: &str) -> bool {
    matches!(
        s,
        "0.0.6" | "0.0.7" | "0.0.8" | "0.0.9" | "0.0.10" | "0.0.11" | "0.0.12" | "0.0.99"
    )
}

fn release_candidate_value(s: &str) -> bool {
    let hash = s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
    let synthetic_name = ["synthetic:", "synthetic_", "synthetic-"]
        .iter()
        .any(|prefix| {
            s.strip_prefix(prefix).is_some_and(|rest| {
                !rest.is_empty()
                    && rest
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
            })
        });
    let asset = RELEASE_CANDIDATE_TARGETS.iter().any(|target| {
        s == format!("openwiz-{target}.manifest.json")
            || s == format!("openwiz-{target}.sha256")
            || ["manifest.json", "tar.gz"].iter().any(|extension| {
                s.strip_prefix("openwiz-")
                    .and_then(|rest| rest.strip_suffix(&format!("-{target}.{extension}")))
                    .is_some_and(release_candidate_version)
            })
    });
    let pointer_path = s.strip_prefix('/').is_some_and(|rest| {
        rest.split('/')
            .all(|part| RELEASE_CANDIDATE_KEYS.contains(&part) || matches!(part, "0" | "approval"))
    });
    let notes = s.starts_with("## ")
        && s.lines().all(|line| {
            line.is_empty()
                || line.starts_with("Synthetic")
                || matches!(
                    line,
                    "Fixture-tested: contract shape only; live behaviour is unverified."
                        | "Fixture-tested: contract examples only; live behaviour is unverified."
                )
                || line
                    .strip_prefix("## ")
                    .and_then(|heading| heading.strip_suffix(" · 2030-01-02"))
                    .is_some_and(release_candidate_version)
        });
    s.is_empty()
        || s.starts_with("Synthetic")
        || synthetic_name
        || hash
        || is_synthetic_commit(s)
        || s == "5d069b025c6eacb4123ca8241ba21345f1eae9dd"
        || RELEASE_CANDIDATE_LABELS.contains(&s)
        || RELEASE_CANDIDATE_TARGETS.contains(&s)
        || RELEASE_CANDIDATE_POINTERS.contains(&s)
        || release_candidate_version(s)
        || s.strip_prefix('v').is_some_and(release_candidate_version)
        || asset
        || pointer_path
        || notes
}

fn is_synthetic_id(s: &str) -> bool {
    ["thr_syn_", "prj_syn_", "mch_syn_", "env_syn_", "src_syn_"]
        .iter()
        .any(|p| {
            s.strip_prefix(p)
                .is_some_and(|n| n.len() == 4 && n.bytes().all(|b| b.is_ascii_digit()))
        })
}

fn is_version(s: &str) -> bool {
    if let Some(n) = s.strip_prefix('v') {
        return !n.is_empty() && n.len() <= 6 && n.bytes().all(|b| b.is_ascii_digit());
    }
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 3
        && parts
            .iter()
            .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
}

fn is_synthetic_value(s: &str) -> bool {
    s.is_empty()
        || LABELS.contains(&s)
        || ARGV_WORDS.contains(&s)
        || ERROR_LINES.contains(&s)
        || is_synthetic_id(s)
        || is_version(s)
        || s.starts_with("Synthetic")
        || s.starts_with("synthetic")
        || s.starts_with("syn-")
        || s.starts_with("/synthetic/")
        || s.starts_with("https://example.invalid/synthetic/")
}

fn is_allowed_key(k: &str) -> bool {
    OBSERVED_KEYS.contains(&k) || k.starts_with("synthetic")
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Folder {
    Other,
    ReleaseCandidate,
    Send,
    NewThread,
    GitHub,
}

fn folder(path: &Path) -> Folder {
    if path.parent() == Some(Path::new(FIXTURES).join("release/candidate").as_path()) {
        return Folder::ReleaseCandidate;
    }
    if is_send_fixture(path) {
        Folder::Send
    } else if path.starts_with(Path::new(FIXTURES).join("room-cli-v127/new-thread")) {
        Folder::NewThread
    } else if path.starts_with(Path::new(FIXTURES).join("github")) {
        Folder::GitHub
    } else {
        Folder::Other
    }
}

fn value_in(s: &str, folder: Folder) -> bool {
    if folder == Folder::ReleaseCandidate {
        return release_candidate_value(s);
    }
    value_ok(s, folder == Folder::Send)
        || (folder == Folder::NewThread && NEW_THREAD_LABELS.contains(&s))
        || (folder == Folder::GitHub && is_github_value(s))
}

fn key_in(k: &str, folder: Folder) -> bool {
    if folder == Folder::ReleaseCandidate {
        return RELEASE_CANDIDATE_KEYS.contains(&k);
    }
    if folder == Folder::GitHub {
        return GITHUB_KEYS.contains(&k) || k.starts_with("synthetic");
    }
    key_ok(k, folder == Folder::Send)
        || (folder == Folder::NewThread && NEW_THREAD_KEYS.contains(&k))
}

fn is_github_value(s: &str) -> bool {
    GITHUB_LABELS.contains(&s)
        || GITHUB_DOCUMENTED_LABELS.contains(&s)
        || is_synthetic_commit(s)
        || is_synthetic_branch(s)
        || is_time(s)
        || is_gh_version_line(s)
        || s.strip_prefix("no checks reported on the '")
            .and_then(|s| s.strip_suffix("' branch"))
            .is_some_and(is_synthetic_branch)
}

fn is_synthetic_commit(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 40 && matches!(b[0], b'0'..=b'9' | b'a'..=b'f') && b.iter().all(|c| *c == b[0])
}

fn is_synthetic_branch(s: &str) -> bool {
    s.strip_prefix("room/syn-").is_some_and(|rest| {
        !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    })
}

fn is_time(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 20
        && b.iter().enumerate().all(|(i, c)| match i {
            4 | 7 => *c == b'-',
            10 => *c == b'T',
            13 | 16 => *c == b':',
            19 => *c == b'Z',
            _ => c.is_ascii_digit(),
        })
}

fn is_gh_version_line(s: &str) -> bool {
    let Some((version, date)) = s
        .strip_prefix("gh version ")
        .and_then(|rest| rest.strip_suffix(')'))
        .and_then(|rest| rest.split_once(" ("))
    else {
        return false;
    };
    let d = date.as_bytes();
    is_version(version)
        && !version.starts_with('v')
        && d.len() == 10
        && d.iter().enumerate().all(|(i, c)| match i {
            4 | 7 => *c == b'-',
            _ => c.is_ascii_digit(),
        })
}

fn value_ok(s: &str, send: bool) -> bool {
    is_synthetic_value(s)
        || (send
            && (DOCUMENTED_SEND_LABELS.contains(&s)
                || SEND_ARGV_WORDS.contains(&s)
                || SEND_ERROR_LINES.contains(&s)
                || OBSERVED_QUEUED_LABELS.contains(&s)
                || s == SYNTHETIC_QUEUED_ID
                || s == SYNTHETIC_QUEUED_UUID))
}

fn key_ok(k: &str, send: bool) -> bool {
    is_allowed_key(k)
        || (send
            && (DOCUMENTED_SEND_KEYS.contains(&k)
                || OBSERVED_SENT_KEYS.contains(&k)
                || OBSERVED_QUEUED_KEYS.contains(&k)))
}

fn is_send_fixture(path: &Path) -> bool {
    path.starts_with(Path::new(FIXTURES).join("room-cli-0.43.1/send"))
}

fn private_looking_in(text: &str, context: Folder) -> Vec<String> {
    if context == Folder::ReleaseCandidate {
        let mut text = text.to_owned();
        for pointer in RELEASE_CANDIDATE_POINTERS {
            text = text.replace(&format!("\"{pointer}\""), "\"synthetic-pointer\"");
        }
        let mut bad = private_looking(&text);
        if text.contains("://") {
            bad.push("unexpected release-candidate URL".to_owned());
        }
        return bad;
    }
    if context == Folder::Send {
        let quoted = format!("\"{SYNTHETIC_QUEUED_UUID}\"");
        let quoted_id = format!("\"{SYNTHETIC_QUEUED_ID}\"");
        return private_looking(
            &text
                .replace(&quoted, "\"syn-queued-uuid\"")
                .replace(&quoted_id, "\"syn-queued-id\""),
        );
    }
    private_looking(text)
}

fn private_looking(text: &str) -> Vec<String> {
    let mut found = Vec::new();
    for needle in [
        "/Users/",
        "/home/",
        "C:\\",
        "gho_",
        "ghp_",
        "github_pat_",
        "sk-",
        "xox",
        "BEGIN ",
    ] {
        if text.contains(needle) {
            found.push(needle.to_owned());
        }
    }
    let b = text.as_bytes();
    for (i, _) in text.match_indices('@') {
        let word = |j: usize| b.get(j).is_some_and(|c| c.is_ascii_alphanumeric());
        if i > 0 && word(i - 1) && word(i + 1) {
            found.push(format!("an email address at byte {i}"));
        }
    }
    for (i, _) in text.match_indices("://") {
        let rest = &text[i..];
        if !rest.starts_with("://example.invalid/") {
            found.push(format!("URL at byte {i}"));
        }
    }
    for prefix in ["thr_", "prj_", "mch_", "env_", "src_"] {
        for (i, _) in text.match_indices(prefix) {
            let start_ok = i == 0 || !text.as_bytes()[i - 1].is_ascii_alphanumeric();
            if start_ok && !text[i + prefix.len()..].starts_with("syn_") {
                found.push(format!("non-synthetic id {prefix}… at byte {i}"));
            }
        }
    }
    if text.contains("qmsg_") {
        found.push("a queued message id".to_owned());
    }
    if has_uuid(text) {
        found.push("a UUID".to_owned());
    }
    found
}

fn has_uuid(text: &str) -> bool {
    let b = text.as_bytes();
    let shape = [8, 4, 4, 4, 12];
    let total = 36;
    (0..b.len().saturating_sub(total - 1)).any(|start| {
        let mut i = start;
        for (n, len) in shape.iter().enumerate() {
            if !b[i..i + len].iter().all(u8::is_ascii_hexdigit) {
                return false;
            }
            i += len;
            if n < 4 {
                if b[i] != b'-' {
                    return false;
                }
                i += 1;
            }
        }
        true
    })
}

fn walk(value: &Value, path: &str, bad: &mut Vec<String>, send: bool) {
    let folder = if send { Folder::Send } else { Folder::Other };
    walk_in(value, path, bad, folder)
}

fn walk_in(value: &Value, path: &str, bad: &mut Vec<String>, folder: Folder) {
    match value {
        Value::Object(map) => {
            for (k, v) in map {
                if !key_in(k, folder) {
                    bad.push(format!("{path}: key {k:?} is not a recorded key"));
                }
                walk_in(v, &format!("{path}.{k}"), bad, folder);
            }
        }
        Value::Array(items) => {
            for (i, item) in items.iter().enumerate() {
                walk_in(item, &format!("{path}[{i}]"), bad, folder);
            }
        }
        Value::String(s) => {
            if folder == Folder::ReleaseCandidate {
                bad.extend(private_looking_in(
                    &serde_json::to_string(s).expect("string JSON"),
                    folder,
                ));
            }
            if !value_in(s, folder) {
                bad.push(format!("{path}: value {s:?} is not synthetic"));
            }
        }
        _ => {}
    }
}

fn scan_scenario(path: &Path, value: &Value, bad: &mut Vec<String>) {
    let dir = path.parent().expect("scenario dir");
    let send = is_send_fixture(path);
    let keys_ok = |v: &Value, bad: &mut Vec<String>| {
        for k in v.as_object().into_iter().flatten().map(|(k, _)| k) {
            if !SCENARIO_KEYS.contains(&k.as_str()) || (k == "any_text" && !send) {
                bad.push(format!("unexpected scenario key {k:?}"));
            }
        }
    };
    keys_ok(value, bad);
    for key in ["scenario", "extends"] {
        if let Some(name) = value[key].as_str()
            && !dir.join("..").join(name).join("scenario.json").is_file()
        {
            bad.push(format!("{key} {name:?} is not a scenario"));
        }
    }
    for response in value["responses"].as_array().into_iter().flatten() {
        keys_ok(response, bad);
        for word in response["argv"].as_array().into_iter().flatten() {
            let w = word.as_str().unwrap_or_default();
            if !(ARGV_WORDS.contains(&w)
                || (send && SEND_ARGV_WORDS.contains(&w))
                || is_synthetic_id(w))
            {
                bad.push(format!("argument {w:?} is not allowlisted or synthetic"));
            }
        }
        if let Some(file) = response["stdout_file"].as_str()
            && (file.contains('/') || !dir.join(file).is_file())
        {
            bad.push(format!("stdout_file {file:?} is not a file in {dir:?}"));
        }
        for key in ["stdout", "stderr"] {
            if let Some(text) = response[key].as_str()
                && !value_ok(text, send)
            {
                bad.push(format!("{key} {text:?} is not synthetic"));
            }
        }
    }
}

fn scan_unparsed(text: &str, bad: &mut Vec<String>, send: bool) {
    scan_unparsed_with(text, bad, &|t| key_ok(t, send) || value_ok(t, send), &|t| {
        value_ok(t, send)
    })
}

fn scan_unparsed_in(text: &str, bad: &mut Vec<String>, folder: Folder) {
    scan_unparsed_with(
        text,
        bad,
        &|t| key_in(t, folder) || value_in(t, folder),
        &|t| value_in(t, folder),
    )
}

fn scan_unparsed_with(
    text: &str,
    bad: &mut Vec<String>,
    token_ok: &dyn Fn(&str) -> bool,
    text_ok: &dyn Fn(&str) -> bool,
) {
    let mut tokens = Vec::new();
    let mut rest = text;
    while let Some(start) = rest.find('"') {
        let after = &rest[start + 1..];
        match after.find('"') {
            Some(end) => {
                tokens.push(&after[..end]);
                rest = &after[end + 1..];
            }
            None => {
                tokens.push(after);
                break;
            }
        }
    }
    if tokens.is_empty() {
        let t = text.trim();
        if !text_ok(t) {
            bad.push(format!("text {t:?} is not synthetic"));
        }
    }
    for t in tokens {
        if !token_ok(t) {
            bad.push(format!("token {t:?} is not synthetic"));
        }
    }
}

fn scan_github_scenario(path: &Path, value: &Value, bad: &mut Vec<String>) {
    scan_github_scenario_with(
        path,
        value,
        bad,
        &openwiz_adapter_github::allowlist::allowed,
    )
}

fn scan_github_scenario_with(
    path: &Path,
    value: &Value,
    bad: &mut Vec<String>,
    allowed: &dyn Fn(&[&str]) -> bool,
) {
    let dir = path.parent().expect("scenario dir");
    let keys_ok = |v: &Value, allowed: &[&str], bad: &mut Vec<String>| {
        for k in v.as_object().into_iter().flatten().map(|(k, _)| k) {
            if !allowed.contains(&k.as_str()) {
                bad.push(format!("unexpected scenario key {k:?}"));
            }
        }
    };
    keys_ok(value, GITHUB_SCENARIO_KEYS, bad);
    let name = dir.file_name().and_then(|n| n.to_str());
    if value["scenario"].as_str().is_none() || value["scenario"].as_str() != name {
        bad.push("scenario is not its directory's name".to_owned());
    }
    if !value["description"].as_str().is_some_and(|d| !d.is_empty()) {
        bad.push("no description".to_owned());
    }
    let assumptions = value["synthetic_assumptions"].as_array();
    if !assumptions.is_some_and(|a| !a.is_empty() && a.iter().all(Value::is_string)) {
        bad.push("synthetic_assumptions: label what is not observed".to_owned());
    }
    for key in ["scenario", "extends"] {
        if let Some(name) = value[key].as_str()
            && !dir.join("..").join(name).join("scenario.json").is_file()
        {
            bad.push(format!("{key} {name:?} is not a scenario"));
        }
    }
    for response in value["responses"].as_array().into_iter().flatten() {
        keys_ok(response, GITHUB_RESPONSE_KEYS, bad);
        let argv: Option<Vec<&str>> = response["argv"]
            .as_array()
            .and_then(|words| words.iter().map(Value::as_str).collect());
        match argv {
            None => bad.push(format!("argv {} is not a list of text", response["argv"])),
            Some(argv) if !allowed(&argv) => {
                bad.push(format!("argv {argv:?} is not on the GitHub allowlist"))
            }
            Some(_) => {}
        }
        if let Some(file) = response["stdout_file"].as_str()
            && (file.contains('/') || !dir.join(file).is_file())
        {
            bad.push(format!("stdout_file {file:?} is not a file in {dir:?}"));
        }
        for key in ["stdout", "stderr"] {
            if let Some(text) = response[key].as_str() {
                bad.extend(private_looking(text));
                match serde_json::from_str::<Value>(text) {
                    Ok(json) => walk_in(&json, key, bad, Folder::GitHub),
                    Err(_) => scan_unparsed_in(text, bad, Folder::GitHub),
                }
            }
        }
    }
}

fn scan_file(path: &Path) -> Vec<String> {
    let text = fs::read_to_string(path).expect("fixtures are UTF-8 text");
    scan_text(path, &text)
}

fn scan_text(path: &Path, text: &str) -> Vec<String> {
    let mut bad: Vec<String> = private_looking_in(text, folder(path));
    let in_fake = path.starts_with(FAKE) || path.starts_with(FAKE_GH);
    let is_envelope = path.components().any(|c| c.as_os_str() == "envelopes");
    if in_fake || path.file_name().is_some_and(|n| n == "README.md") {
        return bad;
    }
    if folder(path) == Folder::ReleaseCandidate {
        match crate::strict_json::parse(text.as_bytes()) {
            Ok(value) => walk_in(&value, "$", &mut bad, Folder::ReleaseCandidate),
            Err(_) => bad
                .push("release-candidate fixtures require strict JSON with unique keys".to_owned()),
        }
        return bad;
    }
    match serde_json::from_str::<Value>(text) {
        Ok(value) if is_envelope => walk_envelope(&value, &schema_words(), &mut bad),
        Ok(value)
            if folder(path) == Folder::GitHub
                && path.file_name().is_some_and(|n| n == "scenario.json") =>
        {
            scan_github_scenario(path, &value, &mut bad)
        }
        Ok(value) if path.file_name().is_some_and(|n| n == "scenario.json") => {
            scan_scenario(path, &value, &mut bad)
        }
        Ok(value) => walk_in(&value, "$", &mut bad, folder(path)),
        Err(_) if folder(path) == Folder::GitHub => {
            scan_unparsed_in(text, &mut bad, Folder::GitHub)
        }
        Err(_) => scan_unparsed(text, &mut bad, is_send_fixture(path)),
    }
    bad
}

fn schema_words() -> Vec<String> {
    fn collect(v: &Value, out: &mut Vec<String>) {
        match v {
            Value::Object(map) => {
                for (k, child) in map {
                    match (k.as_str(), child) {
                        ("const", Value::String(s)) => out.push(s.clone()),
                        ("enum", Value::Array(items)) => {
                            out.extend(items.iter().filter_map(Value::as_str).map(str::to_owned))
                        }
                        _ => collect(child, out),
                    }
                }
            }
            Value::Array(items) => items.iter().for_each(|i| collect(i, out)),
            _ => {}
        }
    }
    let mut out = Vec::new();
    collect(&crate::schema::load_schema(), &mut out);
    out
}

fn walk_envelope(value: &Value, words: &[String], bad: &mut Vec<String>) {
    match value {
        Value::Object(map) => {
            for (k, v) in map {
                if !matches!(k.as_str(), "unknown" | "reason" | "detail") {
                    walk_envelope(v, words, bad);
                }
            }
        }
        Value::Array(items) => items.iter().for_each(|i| walk_envelope(i, words, bad)),
        Value::String(s) if !(is_synthetic_value(s) || words.contains(s) || s == "room-cli") => {
            bad.push(format!("value {s:?} is not synthetic"));
        }
        _ => {}
    }
}

#[test]
fn fixtures_contain_only_synthetic_values() {
    let files = all_files();
    assert!(files.len() > 20, "the fixtures are there");
    for fake in [
        Path::new(FAKE).join("main.rs"),
        Path::new(FAKE_GH).join("main.rs"),
    ] {
        assert!(files.contains(&fake), "{fake:?} is not scanned");
    }
    let mut problems = Vec::new();
    for path in &files {
        for p in scan_file(path) {
            problems.push(format!("{}: {p}", path.display()));
        }
    }
    assert!(problems.is_empty(), "{problems:#?}");
}

#[test]
fn release_candidate_examples_have_scoped_synthetic_provenance() {
    let dir = Path::new(FIXTURES).join("release/candidate");
    for name in [
        "synthetic-ready.json",
        "synthetic-combined.json",
        "synthetic-installed.json",
        "refusals.json",
    ] {
        let bad = scan_file(&dir.join(name));
        assert!(bad.is_empty(), "{name}: {:?}", &bad[..bad.len().min(3)]);
    }
    let planted = json!({
        "candidate_sha256": "a".repeat(64),
        "evidence_class": "live",
        "pointer": "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001",
    });
    for relative in [
        "release/candidate-extra/example.json",
        "release/candidate/nested/example.json",
        "release/other/example.json",
        "github/example.json",
        "room-cli-0.43.1/send/example.json",
        "room-cli-v127/new-thread/example.json",
    ] {
        let path = Path::new(FIXTURES).join(relative);
        let mut bad = private_looking_in(&planted.to_string(), folder(&path));
        walk_in(&planted, "$", &mut bad, folder(&path));
        assert!(
            !bad.is_empty(),
            "accepted outside exact directory: {relative}"
        );
    }
}

#[test]
fn release_candidate_privacy_and_unknown_forms_still_refuse() {
    let path = Path::new(FIXTURES).join("release/candidate/synthetic-ready.json");
    for planted in [
        json!({"reason": "Synthetic thr_synprivate123"}),
        json!({"reason": "Synthetic ghp_planted_credential"}),
        json!({"reason": "Synthetic someone@example.com"}),
        json!({"reason": "Synthetic /home/synthetic-owner/file"}),
        json!({"pointer": "https://example.invalid/unexpected"}),
        json!({"reason": "Synthetic https://example.invalid/synthetic/unexpected"}),
        json!({"pointer": "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000003"}),
        json!({"pointer": "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001/extra"}),
        json!({"syntheticUnknownKey": "Synthetic"}),
        json!({"status": "unapproved-status"}),
        json!({"status": "active"}),
        json!({"source": "0123456789abcdef0123456789abcdef01234567"}),
        json!({"sha256": "A".repeat(64)}),
        json!({"name": "openwiz-0.0.99-unknown-target.tar.gz"}),
        json!({"path": "/candidate/unapproved_field"}),
        json!({"utf8": "## 0.0.99 · 2030-01-02\n\nUnapproved release prose.\n"}),
    ] {
        let mut bad = private_looking_in(&planted.to_string(), folder(&path));
        walk_in(&planted, "$", &mut bad, folder(&path));
        assert!(!bad.is_empty(), "accepted release fixture plant: {planted}");
    }
    let encoded = r#"{"reason":"Synthetic \u0067hp_planted_credential"}"#;
    let mut bad = private_looking_in(encoded, folder(&path));
    walk_in(
        &serde_json::from_str::<Value>(encoded).unwrap(),
        "$",
        &mut bad,
        folder(&path),
    );
    assert!(!bad.is_empty(), "accepted encoded credential");
}

#[test]
fn release_candidate_duplicate_keys_cannot_hide_private_values() {
    let path = Path::new(FIXTURES).join("release/candidate/synthetic-ready.json");
    for text in [
        r#"{"reason":"Synthetic \u0067hp_planted_credential","reason":"Synthetic"}"#,
        r#"{"reason":"Synthetic https:\/\/example.invalid\/unexpected","reason":"Synthetic"}"#,
        r#"{"risk":{"send":{"reason":"Synthetic \u0067hp_planted_credential","reason":"Synthetic"}}}"#,
        r#"[{"reason":"Synthetic","rea\u0073on":"Synthetic"}]"#,
    ] {
        assert!(
            !scan_text(&path, text).is_empty(),
            "duplicate key accepted: {text}"
        );
    }
    let independent =
        r#"{"risk":{"send":{"reason":"Synthetic first"},"new":{"reason":"Synthetic second"}}}"#;
    assert!(
        scan_text(&path, independent).is_empty(),
        "separate objects are not duplicate keys"
    );
}

#[test]
fn release_candidate_filename_cannot_select_room_cli_scenario_rules() {
    let path = Path::new(FIXTURES).join("release/candidate/scenario.json");
    for text in [
        r#"{"description":"Synthetic \u0067hp_planted_credential"}"#,
        r#"{"description":"Synthetic"}"#,
        r#"{"description":"Synthetic https:\/\/example.invalid\/unexpected"}"#,
    ] {
        assert!(
            !scan_text(&path, text).is_empty(),
            "candidate scenario bypass: {text}"
        );
    }
    assert!(scan_text(&path, r#"{"reason":"Synthetic"}"#).is_empty());
}

#[test]
fn every_scenario_records_its_synthetic_assumptions() {
    let dir = Path::new(FIXTURES).join("room-cli-0.43.1");
    let mut count = 0;
    for entry in fs::read_dir(&dir).expect("scenarios") {
        let path = entry.expect("entry").path().join("scenario.json");
        let value: Value = serde_json::from_str(&fs::read_to_string(&path).expect("scenario"))
            .expect("scenario JSON");
        let name = path
            .parent()
            .unwrap()
            .file_name()
            .unwrap()
            .to_string_lossy()
            .into_owned();
        assert_eq!(value["scenario"], name.as_str(), "{path:?}");
        assert!(
            value["description"].as_str().is_some_and(|d| !d.is_empty()),
            "{path:?}"
        );
        let assumptions = value["synthetic_assumptions"]
            .as_array()
            .expect("assumptions list");
        assert!(
            !assumptions.is_empty(),
            "{path:?}: label what is not observed"
        );
        count += 1;
    }
    assert!(count >= 13, "every variant has a scenario");
}

#[test]
fn the_scan_catches_planted_private_data() {
    for planted in [
        r#"{"title": "Fix the login page"}"#,
        concat!(r#"{"id": "thr_"#, r#"a1b2c3"}"#),
        r#"{"path": "/Users/someone/project"}"#,
        r#"{"gitRemoteUrl": "https://github.com/someone/repo.git"}"#,
        r#"{"email": "someone@example.com"}"#,
        r#"{"id": "123e4567-e89b-12d3-a456-426614174000"}"#,
        r#"{"secretToken": "Synthetic"}"#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        let mut bad = private_looking(planted);
        walk(&value, "$", &mut bad, false);
        assert!(!bad.is_empty(), "the scan missed {planted}");
    }
    let mut bad = Vec::new();
    scan_unparsed(
        r#"[{"id": "thr_syn_0001", "title": "Real title"#,
        &mut bad,
        false,
    );
    assert!(!bad.is_empty(), "the scan missed a value in truncated JSON");
}

#[test]
fn the_observed_sent_keys_pass_only_in_send_fixtures() {
    for planted in [
        r#"{"ok": true}"#,
        r#"{"mode": "queue"}"#,
        r#"{"threadId":"thr_syn_0001","ok":true,"delivery":"sent","mode":"queue"}"#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        for outside in [Folder::Other, Folder::NewThread, Folder::GitHub] {
            let mut bad = Vec::new();
            walk_in(&value, "$", &mut bad, outside);
            assert!(!bad.is_empty(), "accepted outside send/: {planted}");
        }
        let mut inside = Vec::new();
        walk_in(&value, "$", &mut inside, Folder::Send);
        assert!(inside.is_empty(), "{planted}: {inside:?}");
    }
}

#[test]
fn the_documented_send_shapes_pass_only_in_send_fixtures() {
    for planted in [
        r#"{"delivery": "sent"}"#,
        r#"{"queuedMessage": {"waitingOn": {"kind": "thread-busy"}}}"#,
        r#"{"requestId": "syn-request-0001"}"#,
        r#"{"status": "queued"}"#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        let mut outside = Vec::new();
        walk(&value, "$", &mut outside, false);
        assert!(!outside.is_empty(), "accepted outside send/: {planted}");
        let mut inside = Vec::new();
        walk(&value, "$", &mut inside, true);
        assert!(inside.is_empty(), "{planted}: {inside:?}");
    }
    assert!(!value_ok("Error: HTTP 400: Unsupported mode", false));
    assert!(!value_ok("tell", false));
}

#[test]
fn the_new_thread_shapes_pass_only_in_new_thread_fixtures() {
    for planted in [
        r#"{"ready": true, "harnesses": null}"#,
        r#"{"reasoning_levels": ["xhigh", "ultra"]}"#,
        r#"{"status": "pending", "lastError": null}"#,
        r#"{"id": "openclaw"}"#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        for outside in [Folder::Other, Folder::Send] {
            let mut bad = Vec::new();
            walk_in(&value, "$", &mut bad, outside);
            assert!(!bad.is_empty(), "accepted outside new-thread/: {planted}");
        }
        let mut inside = Vec::new();
        walk_in(&value, "$", &mut inside, Folder::NewThread);
        assert!(inside.is_empty(), "{planted}: {inside:?}");
    }
    for planted in [
        r#"{"account": {"email": "Synthetic"}}"#,
        r#"{"title": "Real title"}"#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        let mut bad = Vec::new();
        walk_in(&value, "$", &mut bad, Folder::NewThread);
        assert!(!bad.is_empty(), "accepted in new-thread/: {planted}");
    }
}

#[test]
fn the_github_shapes_pass_only_in_github_fixtures() {
    for planted in [
        r#"{"headRefName": "room/syn-a1-0001", "baseRefName": "main", "isDraft": false}"#,
        r#"{"state": "MERGED", "mergeCommit": {"oid": "1111111111111111111111111111111111111111"}}"#,
        r#"{"mergedAt": "2026-10-31T00:40:57Z", "closingIssuesReferences": [{"number": 902}]}"#,
        r#"{"subIssues": {"nodes": [{"number": 902, "state": "OPEN"}], "totalCount": 1}}"#,
        r#"[{"bucket": "pass", "name": "synthetic-check"}, {"bucket": "fail"}]"#,
        r#"{"labels": [{"name": "ready-for-agent"}, {"name": "held"}]}"#,
        r#"{"data": {"repository": {"issue": {"blockedBy": {"pageInfo": {"hasNextPage": false}}}}}}"#,
        r#"{"status": "identical", "behind_by": 0}"#,
        r#""gh version 2.100.0 (2026-09-03)""#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        for outside in [Folder::Other, Folder::Send, Folder::NewThread] {
            let mut bad = Vec::new();
            walk_in(&value, "$", &mut bad, outside);
            assert!(!bad.is_empty(), "accepted outside github/: {planted}");
        }
        let mut inside = private_looking(planted);
        walk_in(&value, "$", &mut inside, Folder::GitHub);
        assert!(inside.is_empty(), "{planted}: {inside:?}");
    }
    for planted in [
        r#"{"title": "Fix the login page"}"#,
        r#"{"headRefName": "room/fix-login"}"#,
        r#"{"headRefName": "feature/syn-a1"}"#,
        r#"{"headRefOid": "0123456789abcdef0123456789abcdef01234567"}"#,
        r#"{"headRefOid": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}"#,
        r#"{"oid": "111111111111111111111111111111111111111"}"#,
        r#"{"mergedAt": "2026-10-31 00:40:57"}"#,
        r#"{"url": "https://github.com/someone/repo/pull/1"}"#,
        r#"{"author": {"login": "someone@example.com"}}"#,
        r#"{"projectId": "prj_syn_0001"}"#,
        r#"{"secretToken": "Synthetic"}"#,
        r#""gh version 2.100.0""#,
    ] {
        let value: Value = serde_json::from_str(planted).unwrap();
        let mut bad = private_looking(planted);
        walk_in(&value, "$", &mut bad, Folder::GitHub);
        assert!(!bad.is_empty(), "accepted in github/: {planted}");
    }
    let mut bad = Vec::new();
    scan_unparsed_in(r#"[{"title": "Real title"#, &mut bad, Folder::GitHub);
    assert!(!bad.is_empty(), "the scan missed a value in truncated JSON");
    let mut bad = Vec::new();
    scan_unparsed_in(
        "gh version 2.100.0 (2026-09-03)\n",
        &mut bad,
        Folder::GitHub,
    );
    assert!(bad.is_empty(), "{bad:?}");
}

#[test]
fn a_github_scenario_records_its_name_and_synthetic_assumptions() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("fixture-scan/github/syn-recorded");
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("scenario dir");
    let path = dir.join("scenario.json");
    fs::write(&path, "{}").expect("the scenario file, which names itself");
    let none: Vec<Value> = vec![];
    let scan = |value: Value| {
        let mut bad = Vec::new();
        scan_github_scenario(&path, &value, &mut bad);
        bad
    };
    let good = json!({
        "scenario": "syn-recorded",
        "description": "Synthetic.",
        "synthetic_assumptions": ["Every value is synthetic."],
        "responses": none,
    });
    assert_eq!(scan(good.clone()), Vec::<String>::new());
    for (why, key, value) in [
        ("no name", "scenario", Value::Null),
        ("another scenario's name", "scenario", json!("syn-scenario")),
        ("no description", "description", Value::Null),
        ("an empty description", "description", json!("")),
        ("no assumptions", "synthetic_assumptions", Value::Null),
        ("empty assumptions", "synthetic_assumptions", json!([])),
        (
            "an assumption that is not text",
            "synthetic_assumptions",
            json!([1]),
        ),
    ] {
        let mut scenario = good.clone();
        if value.is_null() {
            scenario.as_object_mut().unwrap().remove(key);
        } else {
            scenario[key] = value;
        }
        assert!(!scan(scenario).is_empty(), "accepted {why}");
    }
}

#[test]
fn a_github_scenario_answers_only_calls_the_allowlist_allows() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("fixture-scan/github/syn-scenario");
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("scenario dir");
    fs::write(dir.join("syn-issue.json"), "{}").expect("stdout file");
    let path = dir.join("scenario.json");
    fs::write(&path, "{}").expect("the scenario file, which names itself");
    let scan = |value: Value| {
        let mut bad = Vec::new();
        scan_github_scenario(&path, &value, &mut bad);
        bad
    };
    let none: Vec<Value> = vec![];
    let accepted = json!({
        "scenario": "syn-scenario",
        "description": "Synthetic.",
        "synthetic_assumptions": ["Every value is synthetic."],
        "responses": none,
    });
    assert_eq!(scan(accepted.clone()), Vec::<String>::new());
    let forms: &[&[&str]] = &[
        &["--version"],
        &["--version", "--extra"],
        &["repo", "view", "--json", "name"],
        &["issue", "view", "902", "--json", "title"],
        &["issue", "view", "902"],
        &["pr", "checks", "902", "--json", "name,bucket"],
        &["pr", "merge", "902", "--merge"],
        &[],
    ];
    let refused = |argv: &[&str], allowed: &dyn Fn(&[&str]) -> bool| {
        let mut scenario = accepted.clone();
        scenario["responses"] = json!([{"argv": argv, "stdout_file": "syn-issue.json"}]);
        let mut bad = Vec::new();
        scan_github_scenario_with(&path, &scenario, &mut bad, allowed);
        let off_the_list = bad
            .iter()
            .filter(|b| b.contains("is not on the GitHub allowlist"))
            .count();
        assert_eq!(
            bad.len(),
            off_the_list,
            "{argv:?}: only the allowlist: {bad:?}"
        );
        off_the_list == 1
    };
    for argv in forms {
        let allowed = openwiz_adapter_github::allowlist::allowed(argv);
        assert_eq!(
            refused(argv, &openwiz_adapter_github::allowlist::allowed),
            !allowed,
            "{argv:?}"
        );
        let mut bad = Vec::new();
        let mut scenario = accepted.clone();
        scenario["responses"] = json!([{"argv": argv, "stdout_file": "syn-issue.json"}]);
        scan_github_scenario(&path, &scenario, &mut bad);
        assert_eq!(
            bad.is_empty(),
            allowed,
            "{argv:?}: the scan uses the real allowlist"
        );
    }
    let planted = |argv: &[&str]| {
        argv == ["--version"] || argv == ["issue", "view", "902", "--json", "title"]
    };
    for argv in forms {
        let allowed =
            *argv == ["--version"] || *argv == ["issue", "view", "902", "--json", "title"];
        assert_eq!(
            refused(argv, &planted),
            !allowed,
            "{argv:?} with the planted allowlist"
        );
    }
    for (why, scenario) in [
        (
            "an unknown top-level key",
            json!({"synthetic_assumptions": [], "responses": [], "respones": []}),
        ),
        (
            "an unknown response key",
            json!({"synthetic_assumptions": [], "responses": [{"argv": [], "any_text": true}]}),
        ),
        (
            "a stdout file elsewhere",
            json!({"synthetic_assumptions": [], "responses": [{"argv": [], "stdout_file": "../x.json"}]}),
        ),
        (
            "a missing stdout file",
            json!({"synthetic_assumptions": [], "responses": [{"argv": [], "stdout_file": "missing.json"}]}),
        ),
        (
            "a scenario name that is not a sibling",
            json!({"scenario": "missing", "synthetic_assumptions": [], "responses": []}),
        ),
        (
            "private inline JSON",
            json!({"synthetic_assumptions": [], "responses": [{"argv": [], "stdout": "{\"title\": \"Real title\"}"}]}),
        ),
        (
            "private inline text",
            json!({"synthetic_assumptions": [], "responses": [{"argv": [], "stderr": "HTTP 404: Not Found"}]}),
        ),
    ] {
        assert!(!scan(scenario).is_empty(), "accepted {why}");
    }
}

#[test]
fn a_github_scenarios_argv_is_only_text() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("fixture-scan/github/syn-argv");
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("scenario dir");
    let path = dir.join("scenario.json");
    for (why, argv) in [
        ("a word that is not text", json!(["issue", 902])),
        ("an argv that is not a list", json!("issue view 902")),
        ("no argv", Value::Null),
    ] {
        let mut response = json!({});
        if !argv.is_null() {
            response["argv"] = argv;
        }
        let mut bad = Vec::new();
        let scenario = json!({"synthetic_assumptions": [], "responses": [response]});
        scan_github_scenario(&path, &scenario, &mut bad);
        assert!(
            bad.iter().any(|b| b.contains("is not a list of text")),
            "{why}: {bad:?}"
        );
    }
}

#[test]
fn no_checks_diagnostic_accepts_only_the_existing_synthetic_branch_form() {
    for branch in ["room/syn-2", "room/syn-a5-0005", "room/syn-A1"] {
        let text = format!("no checks reported on the '{branch}' branch\n");
        let mut bad = Vec::new();
        scan_unparsed_in(&text, &mut bad, Folder::GitHub);
        assert!(bad.is_empty(), "{text:?}: {bad:?}");
        let mut other = Vec::new();
        scan_unparsed_in(&text, &mut other, Folder::Other);
        assert!(!other.is_empty(), "grammar escaped github/: {text:?}");
    }
    for text in [
        "no checks reported on the 'room/feature-real' branch\n",
        "no checks reported on the 'room/syn-' branch\n",
        "no checks reported on the 'room/syn-☃' branch\n",
        "no checks reported on the 'room/syn-real/path' branch\n",
        "no checks reported on the 'room/syn-2_private' branch\n",
        "no checks reported on the 'room/syn-2' branch extra\n",
        "no required checks reported on the 'room/syn-2' branch\n",
        "No checks reported on the 'room/syn-2' branch\n",
        "no checks reported on the 'room/syn-2' branch\nReal data\n",
    ] {
        let mut bad = Vec::new();
        scan_unparsed_in(text, &mut bad, Folder::GitHub);
        assert!(!bad.is_empty(), "accepted {text:?}");
    }
}

#[test]
fn observed_queued_identifiers_and_keys_are_scoped() {
    for id in ["qmsg_syn_0001", "00000000-0000-4000-8000-000000000001"] {
        let text = serde_json::to_string(id).unwrap();
        assert!(private_looking_in(&text, Folder::Send).is_empty(), "{id}");
        assert!(value_in(id, Folder::Send), "{id}");
        for outside in [Folder::Other, Folder::NewThread, Folder::GitHub] {
            assert!(!value_in(id, outside), "identifier accepted outside send/");
        }
    }
    for key in [
        "content",
        "mentions",
        "hardQueue",
        "failureReason",
        "editable",
    ] {
        assert!(key_in(key, Folder::Send), "{key}");
        for outside in [Folder::Other, Folder::GitHub] {
            assert!(!key_in(key, outside), "{key} accepted outside send/");
        }
    }
    assert!(key_in("payload", Folder::Send));
    assert!(!key_in("payload", Folder::Other));
    assert!(
        key_in("payload", Folder::GitHub),
        "the existing webhook shape stays allowed"
    );
    for id in [
        "qmsg_syn_0002",
        "qmsg_private",
        "00000000-0000-4000-8000-000000000002",
        "10000000-0000-4000-8000-000000000001",
    ] {
        assert!(!value_in(id, Folder::Send), "other queued id accepted");
    }
    for text in [
        r#"{"synthetic_note":"Synthetic qmsg_private"}"#,
        r#"{"synthetic_note":"00000000-0000-4000-8000-000000000002"}"#,
        r#"{"synthetic_note":"10000000-0000-4000-8000-000000000001"}"#,
        r#"{"synthetic_note":"prefix00000000-0000-4000-8000-000000000001"}"#,
        r#"{"synthetic_note":"00000000-0000-4000-8000-000000000001suffix"}"#,
    ] {
        assert!(!private_looking_in(text, Folder::Send).is_empty(), "{text}");
    }
    for context in [
        Folder::Send,
        Folder::Other,
        Folder::NewThread,
        Folder::GitHub,
    ] {
        for text in [
            "Synthetic qmsg_syn_0002",
            "Synthetic qmsg_syn_0001",
            "Synthetic prefixqmsg_syn_0001",
            r#""qmsg_syn_0002""#,
        ] {
            assert!(
                !private_looking_in(text, context).is_empty(),
                "queued id escaped prose guard: {text}"
            );
        }
    }
    assert!(
        !private_looking_in(r#""00000000-0000-4000-8000-000000000001""#, Folder::Other).is_empty()
    );
    assert!(!private_looking(r#""00000000-0000-4000-8000-000000000001""#).is_empty());
    assert!(
        scan_file(
            &Path::new(FIXTURES).join("room-cli-0.43.1/send/tell-steer-queued-observed.json")
        )
        .is_empty()
    );
}
