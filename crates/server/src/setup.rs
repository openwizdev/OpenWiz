//! Installation and connection readiness are separate. No external calls and no
//! file here: lib.rs reads the setup tools' owner-only state through the store
//! (#1105), and this composes the report from it.

use crate::SetupState;
use crate::http::{API_HEADERS, Reply};
use serde_json::{Value, json};
use std::time::{SystemTime, UNIX_EPOCH};

/// The components a setup check observes (the store's own list).
const CHECKED: [&str; 7] = [
    "cloudroom",
    "harness",
    "personal_github",
    "github_app",
    "project",
    "engine",
    "remote_access",
];

pub(crate) const ROUTE: &str = "/api/v1/setup";

/// Evidence older than this, or from the future beyond clock drift, is not
/// current: the component is unknown until it is checked again.
const CURRENT_MS: u64 = 60 * 60 * 1000;
const DRIFT_MS: u64 = 5 * 60 * 1000;

/// T1's defaults: nothing checked. Installing bytes alone never proves an
/// account is ready. T4 (`engine`) and T5 (`remote_access`) replace their own rows.
const DEFAULTS: [(&str, &str, &str, &str); 7] = [
    (
        "cloudroom",
        "unknown",
        "CloudRoom has not been checked.",
        "Ask your installing agent to check CloudRoom on this host.",
    ),
    (
        "harness",
        "unknown",
        "Your agent harness has not been checked.",
        "Choose a harness and verify its login, model and effort in CloudRoom.",
    ),
    (
        "personal_github",
        "unknown",
        "Your agent's GitHub identity has not been checked.",
        "Verify the selected agent can push to your chosen repository.",
    ),
    (
        "github_app",
        "missing",
        "OpenWiz GitHub App readiness is not configured.",
        "Connect OpenWiz's App to only the repositories you choose, then verify its permissions.",
    ),
    (
        "project",
        "missing",
        "No verified project is configured.",
        "Choose a repository and CloudRoom project, then confirm CI, review and answer routing.",
    ),
    (
        "engine",
        "missing",
        "No engine has been selected or activated.",
        "Choose Cloud or Local after reviewing costs and the proposed effects.",
    ),
    (
        "remote_access",
        "unknown",
        "Authenticated phone access has not been verified.",
        "Use a named Cloudflare Tunnel with owner-only Access, or authenticated Tailscale.",
    ),
];

const CHECK_AGAIN: &str = "Ask your installing agent to run the setup check again.";

/// Every observation code the setup check writes, its component and state,
/// and fixed public text. A code not listed here is unknown, never trusted.
#[rustfmt::skip]
const CODES: [(&str, &str, &str, &str, &str); 53] = [
    ("cloudroom", "cloudroom_reachable", "unknown", "CloudRoom answered a live read, but no check here proves your CloudRoom login is current.", "Keep CloudRoom open and signed in. No current login evidence is available to this check yet."),
    ("cloudroom", "cloudroom_missing", "missing", "The installed OpenWiz CLI or CloudRoom's room-cli was not found on this host.", "Install CloudRoom and sign in, then check again."),
    ("cloudroom", "cloudroom_unreadable", "unknown", "CloudRoom could not be read; the check got no usable answer.", "Open CloudRoom and sign in, then check again."),
    ("cloudroom", "cloudroom_partial", "unknown", "CloudRoom answered only in part: a supporting read failed or timed out, so the connection is unproven.", "Open CloudRoom and sign in, then check again."),
    // #2201 (contracts/public-cloudroom-setup.v1.md): CloudRoom's install, reuse and sign-in step.
    ("cloudroom", "cloudroom_not_installed", "missing", "CloudRoom is not installed on this host.", "Ask your installing agent to install CloudRoom in setup, or install it from CloudRoom's download page, then check again."),
    ("cloudroom", "cloudroom_installing", "unknown", "CloudRoom is being installed; it is not installed until the install is confirmed.", "Wait for the install to finish, then check again."),
    ("cloudroom", "cloudroom_installed", "unknown", "CloudRoom was installed by setup, but it has not opened yet, so no login was read.", "Ask your installing agent to open CloudRoom's sign-in, sign in there, then check again."),
    ("cloudroom", "cloudroom_reused", "unknown", "Your existing CloudRoom installation is reused as it is, but it has not opened yet, so no login was read.", "Ask your installing agent to open CloudRoom's sign-in, sign in there, then check again."),
    ("cloudroom", "cloudroom_install_failed", "unknown", "The CloudRoom install failed, so CloudRoom is not confirmed installed.", "Ask your installing agent to retry the same install operation, or install CloudRoom from its download page."),
    ("cloudroom", "cloudroom_install_uncertain", "unknown", "The CloudRoom install did not report back; whether it finished is unknown.", "Ask your installing agent to check the same install operation against what is actually installed before trying again."),
    ("cloudroom", "cloudroom_install_declined", "refused", "You declined the CloudRoom install, so nothing was installed.", "Install CloudRoom from its download page, or ask your installing agent for a new install preview."),
    ("cloudroom", "cloudroom_checksum_mismatch", "refused", "The downloaded CloudRoom installer did not match CloudRoom's published checksum, so nothing was installed.", "Ask your installing agent for a new install preview, or install CloudRoom from its download page."),
    ("cloudroom", "cloudroom_unsupported", "refused", "CloudRoom publishes no installer OpenWiz can check for this platform, so OpenWiz installs nothing.", "Install CloudRoom from its download page, open it once, then check again."),
    ("cloudroom", "cloudroom_destination_blocked", "refused", "A file that is not executable is already at ~/Applications/Cloudroom.AppImage, so OpenWiz installs nothing over it and leaves it unchanged.", "Make that file executable if it is your CloudRoom, or move it away, then check again."),
    ("cloudroom", "cloudroom_login_missing", "missing", "CloudRoom is installed and reports no signed-in account.", "Ask your installing agent to open CloudRoom's sign-in once, sign in there, then check again."),
    ("cloudroom", "cloudroom_login_unknown", "unknown", "CloudRoom is installed, but it gave no current login evidence.", "Open CloudRoom and sign in if it asks, then check again."),
    ("cloudroom", "cloudroom_login_verified", "verified", "CloudRoom is installed and reports a signed-in account now.", "Nothing to do for CloudRoom."),
    ("harness", "harness_listed", "unknown", "CloudRoom lists your chosen harness, model and effort, possibly from a saved copy; that harness's login is not proven.", "Keep that harness signed in within CloudRoom. No current login evidence is available to this check yet."),
    ("harness", "harness_unselected", "missing", "No harness, model and effort are chosen yet.", "Save your project settings with a harness, model and effort."),
    ("harness", "harness_unavailable", "refused", "CloudRoom does not offer your chosen harness, model or effort.", "Choose one CloudRoom offers, or fix that harness's login in CloudRoom, then check again."),
    ("harness", "harness_unreadable", "unknown", "CloudRoom's harness options could not be read.", CHECK_AGAIN),
    ("personal_github", "identity_verified", "verified", "Your agents' own GitHub login can push to the selected repository.", "Nothing to do."),
    ("personal_github", "identity_unselected", "missing", "No repository is selected yet.", "Save your project settings with a repository."),
    ("personal_github", "identity_signed_out", "missing", "No GitHub login is available to your agents on this host.", "Sign in to GitHub for your agents (gh auth login), then check again."),
    ("personal_github", "identity_bot", "refused", "Your agents' GitHub login is an App or bot account, not your own identity.", "Sign your agents in with your own GitHub account, separate from OpenWiz's App."),
    ("personal_github", "identity_no_push", "refused", "Your agents' GitHub login cannot push to the selected repository.", "Give that login write access to the repository, then check again."),
    ("personal_github", "identity_unreadable", "unknown", "GitHub did not answer the identity check.", CHECK_AGAIN),
    ("github_app", "app_verified", "verified", "OpenWiz's App is installed on selected repositories with its service permissions and issued a token for the selected repository.", "Nothing to do."),
    ("github_app", "app_missing", "missing", "OpenWiz's GitHub App is not registered on this host.", "Connect OpenWiz's App to only the repositories you choose, then verify its permissions."),
    ("github_app", "app_not_installed", "missing", "OpenWiz's App is registered but not installed for the selected repository's owner.", "Install the App on only the selected repositories, then check again."),
    ("github_app", "app_read_only", "refused", "The App's installation lacks write access to Contents, Issues or Pull requests.", "Accept the App's requested permissions in GitHub, then check again."),
    ("github_app", "app_permissions_mismatch", "refused", "The App's installation has different permissions from OpenWiz's service profile.", "Reconnect the App with Metadata read, Contents, Issues and Pull requests write, Checks and Actions read."),
    ("github_app", "app_all_repositories", "refused", "The App is installed on all repositories; OpenWiz needs only selected repositories.", "Change the installation to only the selected repositories, then check again."),
    ("github_app", "app_wrong_repository", "refused", "The App's installation does not include the selected repository.", "Add the selected repository to the App's installation, then check again."),
    ("github_app", "app_revoked", "refused", "GitHub no longer has this App installation; it was removed or revoked.", "Reconnect: install the App again on only the selected repositories."),
    ("github_app", "app_suspended", "refused", "The App's installation is suspended.", "Unsuspend the installation in GitHub, then check again."),
    ("github_app", "app_key_rejected", "refused", "GitHub rejected the App's key; it was deleted, rotated or has expired.", "Reconnect the App so this host holds a current key."),
    ("github_app", "app_unreadable", "unknown", "GitHub did not answer the App check.", CHECK_AGAIN),
    ("github_app", "app_token_unusable", "unknown", "GitHub's token answer was missing, malformed or not currently valid, so access is unproven.", CHECK_AGAIN),
    ("github_app", "app_files_unusable", "refused", "This host's saved App key or ID is missing, unsafe or unreadable.", "Keep the App's key and ID owner-only (0600) in this host's OpenWiz state, or reconnect the App."),
    ("project", "project_verified", "verified", "Your explicit operator, service record issue, answer target, fleet settings and pinned runtime were checked.", "Nothing to do."),
    ("project", "project_unprepared", "missing", "No project settings have been saved.", "Preview and confirm your project settings with the setup tool."),
    ("project", "project_settings_missing", "missing", "The selected repository has no fleet settings (docs/agents/fleet.md) from the setup skill.", "Run the setup skill in your repository and merge its settings, then check again."),
    ("project", "project_issue_refused", "refused", "The service record issue is missing, closed or a pull request.", "Choose an open issue in the selected repository for service records."),
    ("project", "project_answer_refused", "refused", "The answer target thread was not found in the selected CloudRoom project.", "Choose your orchestrator thread in the selected CloudRoom project."),
    ("project", "project_runtime_missing", "missing", "The packaged skill runtime was not found or is not pinned.", "Reinstall OpenWiz's verified release, then check again."),
    ("project", "project_unreadable", "unknown", "The project settings could not be checked.", CHECK_AGAIN),
    ("remote_access", "access_cloudflare_verified", "verified", "The named tunnel, owner-only Access, origin check and unauthenticated, expired and foreign refusals were verified.", "Recheck after signing in again, reconnecting or restarting the host. Preserve pending work and check its operation ID; never resend on reconnect."),
    ("remote_access", "access_tailscale_verified", "verified", "Private HTTPS Serve, the current owner-only policy and device authorization and expiry were verified with Tailscale's current-policy deny test.", "Recheck after reconnecting or restarting the host. Policy evidence is not a live observation of a phone or network."),
    ("remote_access", "access_refused", "refused", "The route did not prove owner-only access and refusal; phone access is not ready.", "Fix the policy, loopback route or refusal checks. Reconcile the same setup operation before changing routes."),
    ("remote_access", "access_expired", "refused", "The checked account, session or device authorization is expired or unavailable.", "Sign in again, preserve drafts and operation IDs, then recheck the same route. Never resend work on reconnect."),
    ("remote_access", "access_unavailable", "unknown", "Current phone-access evidence could not be read or was not recognized.", "Restore the connection and check the same setup operation. A running tunnel alone is insufficient."),
    ("remote_access", "access_checking", "unknown", "Phone access is being checked; no current refusal evidence is recorded.", "Reconcile this setup operation after a lost reply. Read pending work's status rather than resending it."),
];

fn code(component: &str, code: &str) -> Option<(&'static str, &'static str, &'static str)> {
    CODES
        .iter()
        .find(|(c, k, ..)| *c == component && *k == code)
        .map(|(_, _, state, reason, next)| (*state, *reason, *next))
}

fn component(
    id: &'static str,
    defaults: (&'static str, &'static str, &'static str),
    state: Option<&SetupState>,
    now: u64,
) -> (&'static str, &'static str, &'static str) {
    let Some(state) = state else { return defaults };
    let Some(observed) = state.observations.get(id) else {
        return defaults;
    };
    let current = observed.revision == state.revision
        && observed.at <= now.saturating_add(DRIFT_MS)
        && now.saturating_sub(observed.at) <= CURRENT_MS;
    match code(id, &observed.code) {
        Some(found) if current => found,
        Some(_) => (
            "unknown",
            "The last check is out of date or was made for another selection.",
            CHECK_AGAIN,
        ),
        None => (
            "unknown",
            "The last check's result is not recognized.",
            CHECK_AGAIN,
        ),
    }
}

/// The report from the setup state read at `now` (Unix ms). Readiness needs
/// every prerequisite verified by current evidence for the current selection;
/// an unreadable state is unknown, never an error body.
fn report_at(read: Result<Option<&SetupState>, ()>, now: u64) -> Value {
    let (state, unreadable) = match read {
        Ok(state) => (state, false),
        Err(()) => (None, true),
    };
    let engine = state.and_then(|s| {
        s.engine.as_ref().filter(|e| {
            e.revision == s.revision
                && s.project.as_ref().and_then(|p| p.runtime.as_deref()) == Some(e.runtime.as_str())
        })
    });
    let components = DEFAULTS
        .into_iter()
        .map(|(id, state_default, reason, next)| {
            let checked = CHECKED.contains(&id);
            let (s, r, n) = if id == "engine" && engine.is_some() {
                ("unknown", "Engine selection is saved; activation remains closed and no runtime is verified.", "Current login evidence and approved host provisioning are required. Check the saved operation; never retry an uncertain activation.")
            } else if unreadable && checked {
                ("unknown", "This host's setup state could not be read safely.", "Check that OpenWiz's state directory is owner-only, then run the setup check again.")
            } else if checked {
                component(id, (state_default, reason, next), state, now)
            } else {
                (state_default, reason, next)
            };
            json!({"id":id,"state":s,"reason":r,"next":n})
        })
        .collect::<Vec<_>>();
    // Overall readiness: every prerequisite of the selected engine verified.
    // Phone access is reported, never inferred; T1's engine stays unselected.
    let ready = components
        .iter()
        .filter(|c| c["id"] != "remote_access")
        .all(|c| c["state"] == "verified");
    let operations = state
        .map(|s| {
            s.operations
                .iter()
                .map(|o| {
                    json!({"operation_id":o.operation_id,"kind":o.kind,"phase":o.phase,
                    "fingerprint":o.fingerprint,"effects":o.effects,"reason":o.reason})
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let mut report = json!({"schema":"openwiz.setup.v1","ready":ready,"components":components,
        "engine":"unselected","cost":{"provenance":"unknown","credits":null,
        "window_s":null,"monthly_projection":null,"free_allowance":null,
        "reason":"Cloud Credits have not been measured."},"operations":operations});
    if let Some(engine) = engine {
        report["engine"] = json!(engine.location);
        report["cost"]["reason"] = json!(
            "Cloud Credits are unknown; choose an engine explicitly. Provider charges are separate and unavailable."
        );
        if let Some(cost) = &engine.cost {
            let current = [cost.observed_at, cost.allowance_at]
                .iter()
                .all(|at| *at <= now && now - at <= CURRENT_MS);
            if let (true, Some(credits), Some(window), Some(allowance)) = (
                current,
                cost.credits.as_f64(),
                cost.window_s.as_f64(),
                cost.free_allowance.as_f64(),
            ) {
                let projection = credits / window * 2_592_000.0;
                if projection.is_finite() {
                    let choice = if cost.provenance != "measured" {
                        "Choose a location explicitly."
                    } else if projection > allowance / 10.0 {
                        "Free-account default: Local."
                    } else {
                        "Free-account default: Cloud."
                    };
                    report["cost"] = json!({"provenance":cost.provenance,"credits":credits,
                        "window_s":window,"monthly_projection":projection,"free_allowance":allowance,
                            "reason":format!("Recorded CloudRoom usage: {credits} credits over {window} seconds; current free allowance {allowance}. Projection estimates 30 days at the observed rate. {choice} Provider charges are separate and unavailable.")});
                }
            }
        }
    }
    report
}

pub(crate) fn run(read: Result<Option<SetupState>, ()>) -> Reply {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or(0);
    Reply {
        status: 200,
        headers: API_HEADERS,
        extra: Vec::new(),
        body: serde_json::to_vec(&report_at(
            read.as_ref().map(Option::as_ref).map_err(|_| ()),
            now,
        ))
        .expect("setup report serializes"),
    }
}

#[cfg(test)]
mod composed {
    //! #1105: readiness composed from the setup tools' state, as the store
    //! reads it (its file checks are the store's own tests).
    use crate::SetupState;

    const NOW: u64 = 1_767_225_600_000;

    fn parse(text: &str) -> SetupState {
        serde_json::from_str(text).unwrap()
    }
    fn observed(codes: &[(&str, &str)], revision: u64, at: u64) -> String {
        let observations = codes
            .iter()
            .map(|(c, code)| {
                format!(r#""{c}":{{"code":"{code}","revision":{revision},"at":{at}}}"#)
            })
            .collect::<Vec<_>>()
            .join(",");
        format!(
            r#"{{"schema":"openwiz.setup-state.v1","revision":3,"checks":{{"started":1,"committed":1}},"project":{{"repository":"synthetic-owner/synthetic-consumer","project":"prj_synthetic","operator":"synthetic-owner","service_issue":7,"answer_thread":"thr_synthetic_answer","harness":"claude-code","model":"synthetic-model","effort":"high","runtime":null}},"app":{{"app_id":1001,"installation_id":2002}},"observations":{{{observations}}},"operations":[{{"operation_id":"0123456789abcdef0123456789abcdef","kind":"connect_app","phase":"uncertain","fingerprint":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","effects":["Register OpenWiz's GitHub App."],"reason":"GitHub did not answer; check before trying again."}}]}}"#
        )
    }
    const ALL: [(&str, &str); 5] = [
        ("cloudroom", "cloudroom_reachable"),
        ("harness", "harness_listed"),
        ("personal_github", "identity_verified"),
        ("github_app", "app_verified"),
        ("project", "project_verified"),
    ];
    fn states(report: &serde_json::Value) -> Vec<(String, String)> {
        report["components"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| {
                (
                    c["id"].as_str().unwrap().to_owned(),
                    c["state"].as_str().unwrap().to_owned(),
                )
            })
            .collect()
    }
    fn expect(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs
            .iter()
            .map(|(a, b)| ((*a).to_owned(), (*b).to_owned()))
            .collect()
    }

    #[test]
    fn current_evidence_verifies_each_component_but_not_the_factory() {
        let state = parse(&observed(&ALL, 3, NOW - 1_000));
        let report = super::report_at(Ok(Some(&state)), NOW);
        assert_eq!(
            states(&report),
            expect(&[
                ("cloudroom", "unknown"),
                ("harness", "unknown"),
                ("personal_github", "verified"),
                ("github_app", "verified"),
                ("project", "verified"),
                ("engine", "missing"),
                ("remote_access", "unknown"),
            ])
        );
        assert_eq!(report["ready"], false, "no engine is selected");
        assert_eq!(report["operations"][0]["phase"], "uncertain");
        let app = &report["components"][3];
        assert!(
            app["reason"]
                .as_str()
                .unwrap()
                .contains("selected repositor")
        );
    }

    #[test]
    fn refusals_are_public_fixed_text_and_independent() {
        let mut codes = ALL;
        codes[3] = ("github_app", "app_read_only");
        codes[2] = ("personal_github", "identity_bot");
        let state = parse(&observed(&codes, 3, NOW - 1_000));
        let report = super::report_at(Ok(Some(&state)), NOW);
        let got = states(&report);
        assert_eq!(got[2].1, "refused");
        assert_eq!(got[3].1, "refused");
        assert_eq!(got[0].1, "unknown", "an inventory read alone");
        assert_eq!(got[4].1, "verified");
        assert_eq!(report["ready"], false);
        assert!(
            report["components"][3]["reason"]
                .as_str()
                .unwrap()
                .contains("write")
        );
    }

    #[test]
    fn stale_old_future_or_unrecognized_evidence_is_unknown() {
        for (revision, at, code) in [
            (2, NOW - 1_000, "app_verified"),
            (3, NOW - 3_600_001, "app_verified"),
            (3, NOW + 300_001, "app_verified"),
            (3, NOW - 1_000, "app_trust_me"),
        ] {
            let state = parse(&observed(&[("github_app", code)], revision, at));
            let report = super::report_at(Ok(Some(&state)), NOW);
            assert_eq!(
                report["components"][3]["state"], "unknown",
                "{revision} {at} {code}"
            );
        }
    }

    #[test]
    fn a_harness_listing_or_partial_cloudroom_read_is_never_verified() {
        // Review R5: no code a check could write verifies the harness, and a
        // partial inventory read is unknown.
        for (component, at, code) in [
            ("harness", 1, "harness_verified"),
            ("harness", 1, "harness_listed"),
            ("cloudroom", 0, "cloudroom_partial"),
            // Review R5 (re-check): an inventory read alone never verifies CloudRoom.
            ("cloudroom", 0, "cloudroom_verified"),
            ("cloudroom", 0, "cloudroom_reachable"),
        ] {
            let state = parse(&observed(&[(component, code)], 3, NOW - 1_000));
            let report = super::report_at(Ok(Some(&state)), NOW);
            assert_eq!(report["components"][at]["state"], "unknown", "{code}");
        }
    }

    #[test]
    fn unreadable_state_reports_unknown_never_an_error_body() {
        let report = super::report_at(Err(()), NOW);
        assert_eq!(report["ready"], false);
        assert!(
            states(&report)[..5]
                .iter()
                .all(|(_, state)| state == "unknown")
        );
        assert_eq!(
            super::report_at(Ok(None), NOW)["components"][3]["state"],
            "missing"
        );
    }

    #[test]
    fn remote_access_needs_current_refusal_evidence_for_the_selection() {
        for (code, expected) in [
            ("access_cloudflare_verified", "verified"),
            ("access_tailscale_verified", "verified"),
            ("access_refused", "refused"),
            ("access_expired", "refused"),
            ("access_unavailable", "unknown"),
            ("access_checking", "unknown"),
            ("access_tunnel_running", "unknown"),
        ] {
            let state = parse(&observed(&[("remote_access", code)], 3, NOW - 1_000));
            let report = super::report_at(Ok(Some(&state)), NOW);
            assert_eq!(report["components"][6]["state"], expected, "{code}");
            assert_eq!(
                report["ready"], false,
                "phone evidence cannot verify the engine"
            );
        }
        for (revision, at) in [(2, NOW - 1_000), (3, NOW - 3_600_001), (3, NOW + 300_001)] {
            let state = parse(&observed(
                &[("remote_access", "access_cloudflare_verified")],
                revision,
                at,
            ));
            assert_eq!(
                super::report_at(Ok(Some(&state)), NOW)["components"][6]["state"],
                "unknown"
            );
        }
        assert_eq!(
            super::report_at(Err(()), NOW)["components"][6]["state"],
            "unknown"
        );
    }

    #[test]
    fn cloudroom_install_and_login_codes_show_honest_states() {
        // #2201, contracts/public-cloudroom-setup.v1.md: each install and
        // login result, its state, and a word its reason must carry. Only a
        // positive current login read verifies; failed, uncertain and
        // in-progress installs are never installed or signed in.
        for (code, expected, word) in [
            ("cloudroom_not_installed", "missing", "not installed"),
            ("cloudroom_installing", "unknown", "being installed"),
            ("cloudroom_installed", "unknown", "installed"),
            ("cloudroom_reused", "unknown", "existing"),
            ("cloudroom_install_failed", "unknown", "failed"),
            ("cloudroom_install_uncertain", "unknown", "unknown"),
            ("cloudroom_install_declined", "refused", "declined"),
            ("cloudroom_checksum_mismatch", "refused", "checksum"),
            ("cloudroom_unsupported", "refused", "platform"),
            ("cloudroom_destination_blocked", "refused", "not executable"),
            ("cloudroom_login_missing", "missing", "no signed-in"),
            ("cloudroom_login_unknown", "unknown", "no current login"),
            ("cloudroom_login_verified", "verified", "signed-in account"),
        ] {
            let state = parse(&observed(&[("cloudroom", code)], 3, NOW - 1_000));
            let report = super::report_at(Ok(Some(&state)), NOW);
            let row = &report["components"][0];
            assert_eq!(row["state"], expected, "{code}");
            let reason = row["reason"].as_str().unwrap();
            assert!(reason.contains(word), "{code}: {reason}");
            assert!(!row["next"].as_str().unwrap().is_empty(), "{code}");
            assert_eq!(
                report["ready"], false,
                "{code}: CloudRoom alone is never ready"
            );
            // Old evidence is unknown, even a verified login.
            let old = parse(&observed(&[("cloudroom", code)], 3, NOW - 3_600_001));
            assert_eq!(
                super::report_at(Ok(Some(&old)), NOW)["components"][0]["state"],
                "unknown",
                "{code}"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::{Config, ROUTES, SystemClock, bind, start};
    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::sync::Arc;
    use std::time::Duration;

    #[test]
    fn setup_static_routes_are_exact_startup_loaded_and_no_store() {
        let fixture = crate::web::SetupFixture::new();
        let absent = crate::WebRoot::open(fixture.root()).unwrap();
        fixture.write_setup("synthetic missing prerequisites");
        let loaded = crate::WebRoot::open(fixture.root()).unwrap();
        fixture.write_setup("synthetic changed after startup");
        for path in ["/setup", "/setup/"] {
            let template = crate::web::route(path).expect("setup is a registered static route");
            assert!(crate::web::serve(&absent, template, path).is_none());
            let reply = crate::web::serve(&loaded, template, path).unwrap();
            assert_eq!(reply.body, b"synthetic missing prerequisites");
            assert!(
                reply
                    .extra
                    .iter()
                    .any(|(key, value)| *key == "Cache-Control" && value == "no-store")
            );
            assert!(
                reply
                    .headers
                    .contains(&("Content-Security-Policy", crate::PAGE_CSP))
            );
        }
        for path in ["/setup.html", "/setup/x", "/Setup", "/%73etup"] {
            assert!(crate::web::route(path).is_none());
        }
        fixture.symlink_setup();
        assert!(crate::WebRoot::open(fixture.root()).is_err());
    }

    #[test]
    fn setup_is_readable_without_prerequisites_and_refuses_effects() {
        assert!(
            ROUTES
                .iter()
                .any(|r| r.method == "GET" && r.path == "/api/v1/setup")
        );
        let server = start(
            bind(0).unwrap(),
            Config::default(),
            Arc::new(CloudRoomSource::new("/synthetic-fixture-no-room-cli")),
            Arc::new(SystemClock),
            Arc::new(|_| {}),
        )
        .unwrap();
        let ask = |method: &str, path: &str| {
            let mut stream = TcpStream::connect(server.local_addr()).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            write!(
                stream,
                "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
                server.local_addr().port()
            )
            .unwrap();
            let mut response = String::new();
            stream.read_to_string(&mut response).unwrap();
            response
        };
        let response = ask("GET", "/api/v1/setup");
        assert!(response.starts_with("HTTP/1.1 200"), "{response}");
        assert!(response.contains("Cache-Control: no-store"));
        let value: serde_json::Value =
            serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap();
        assert_eq!(value["schema"], "openwiz.setup.v1");
        assert_eq!(value["ready"], false);
        assert_eq!(value["engine"], "unselected");
        assert_eq!(value["operations"], serde_json::json!([]));
        assert_eq!(value["components"].as_array().unwrap().len(), 7);
        assert!(
            value["components"]
                .as_array()
                .unwrap()
                .iter()
                .all(
                    |v| matches!(v["state"].as_str(), Some("missing" | "unknown"))
                        && !v["reason"].as_str().unwrap().is_empty()
                        && !v["next"].as_str().unwrap().is_empty()
                )
        );
        assert_eq!(value["cost"]["provenance"], "unknown");
        assert!(value["cost"]["credits"].is_null());
        assert!(ask("GET", "/api/v1/setup?activate=1").starts_with("HTTP/1.1 400"));
        assert!(ask("POST", "/api/v1/setup").starts_with("HTTP/1.1 405"));
    }
}
