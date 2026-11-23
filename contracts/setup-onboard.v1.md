# Setup to first merge, version 1 (`openwiz.setup-onboard.v1`)

The shared interface of spec [#625](https://github.com/openwizdev/openwiz/issues/625) (0.0.16, ticket T1 [#632](https://github.com/openwizdev/openwiz/issues/632)): one install
instruction to the first merged implementation pull request on the user's own
repository. It pins the shapes that the later tickets build against: the
selected GitHub identity and the explicit App skip (T2 #633), the user's
private App versus the factory's explicit public App and the protected key
delivery (T3 #606), visibility-aware `openwiz init` and the brain reference
(T5 #635), the joined continuation (T6 #636) and the 0.0.16 timing and action
receipt (T7 #637, T9 #639). The schema is
[setup-onboard.v1.schema.json](setup-onboard.v1.schema.json). Synthetic cases
are in [cases.json](../tools/install/tests/setup-onboard-contract/fixtures/cases.json);
the checks are in `tools/install/tests/setup-onboard-contract/`.

**This contract grants nothing.** It authorizes no sign-in, App registration or
installation, secret save or paste, repository creation, pull request, label,
live read or write, spending, merge, release or publication. Each stays with its
own ticket, its existing approval and T8 #638's exact live-kit authorization. A
document that follows this contract proves only what its proof class and
evidence show; a fixture or recording pass shows the shape is consistent, never
that an absent runtime works. It changes no once-only, authorization,
public-record or token rule of [setup.v1](setup.v1.md),
[github-identity.v1](github-identity.v1.md), [cli.v1](cli.v1.md),
[install.v1](install.v1.md),
[decisions.v1](decisions.v1.md) or [open-development.v1](open-development.v1.md),
which stay authoritative where they apply. Each of those contracts names its
compatible expansion and points here.

## Documents

One document is one JSON object with `schema` equal to
`openwiz.setup-onboard.v1` and one `kind`:

| Kind | What it is | Implemented by |
| --- | --- | --- |
| `identity_selection` | Which GitHub identity acts for the factory on the selected repository, and why it is ready | T2 #633 (login, skip), T3 #606 (the App) |
| `secret_capability` | How the App key reached the protected CloudRoom secret, and what it cost the owner | T3 #606 |
| `init_request` | One `openwiz init` call: preview or an authorized apply | T5 #635 |
| `init_result` | What `openwiz init` read, chose, proposed and did | T5 #635 |
| `brain_reference` | Where settings consumers find the brain | T5 #635, read by T6 #636 |
| `first_merge_receipt` | The 0.0.16 result: under 30 minutes and at most five owner actions | T7 #637 (validator), T9 #639 (live record) |

Objects have exactly the schema's keys, each once: no missing, extra or
duplicate keys, integers as JSON integers, times as nonnegative millisecond
integers. A strict reader refuses duplicate keys and fractional or constant
number spellings, which JSON Schema cannot. `Fact` fields are
`{"known": value}` or `{"unknown": "<reason>"}`; an unread value is never
reported as known.

Every kind carries `proof_class` (`fixture`, `recording` or `live`, as in
first-hour.v1), `synthetic_assumptions` (nonempty exactly when the class is not
`live`) and `private_record` (`null`, or the open-development pointer to the
private comment holding raw evidence; a `live` document needs one). The whole
document text must hold no credential shape: a PEM private-key header, a GitHub
token (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), a JWT, or a
dotenv assignment of `OPENWIZ_GITHUB_APP_KEY` with a value. Details are plain public text.

An evidence item is `basis`, `revision`, `at_ms` and `detail`. `revision` is the
setup check generation (setup-state's `checks`) the observation belongs to.
Only the bases named below establish a state; anything else (a browser opening,
a callback, saved configuration, a test stand-in) is a weak observation.

## Identity selection

`selected` is `app`, `personal_login` or `unselected`. `selection_basis` is
`owner_choice` (chosen in this setup), `saved_choice` (an owner choice saved
earlier and reused), `fallback` or `none`. `app_choice` is `create`, `reuse`,
`skip` or `undecided`. `personal_login` is the user's own GitHub login, with
`state` as in setup.v1 and its evidence. `app` is `null` or the App's
registration, installation, state and evidence.

**Explicit skip, no silent switch.** `personal_login` is selected only after the
owner's explicit `skip`. A `fallback` basis is a silent identity switch and is
refused: App revocation, a refused scope, an unknown identity or a foreign
repository is reported, never turned into the login path or its quota. A
skipped App stays truthfully `missing` (or absent); it is never `verified`.
The token command's own rule still holds: it never falls back internally.

**Readiness.** `ready` is true exactly when the personal login is `verified` and
either `selected: app` with `app_choice` `create` or `reuse` and the App
`verified`, or `selected: personal_login` with `app_choice: skip`. `unselected`
is never ready. CloudRoom, harness, project, engine, builder and reviewer
prerequisites stay independent setup.v1 facts; this is only the identity part.

| State | Established only by (current `revision`) |
| --- | --- |
| Personal login `verified` | Both `github_account_read_back` (the signed-in account read from GitHub) and `repository_access_read_back` (that account's push access to the selected repository read from GitHub). `browser_opened` and `auth_callback_received` never establish it |
| App `verified` | `installation_token_read_back`: an installation token minted for the selected repository and read back, through the existing token command's checks. `manifest_converted`, `app_id_saved` and `install_page_returned` never establish it |

Evidence from another check generation is stale.

**The user's App is private; the factory's is explicitly public.** `mode` is
`user` (each user's own OpenWiz App, J48) or `factory` (the current factory's
multi-account App of github-identity.v1). A `user` App is `visibility: private`
with `visibility_setting: user_default`; a `factory` App is `visibility: public`
with `visibility_setting: explicit_factory`, a separate setting that is never a
default. A `user` App's installation account, every installed repository's
owner and the selected repository's owner must all be its `owner_account`. A
repository outside that account is refused for the user App; it never causes an
automatic switch to a public App. Every installation selects repositories, never
all of them, and a `verified` App covers the selected repository. The permission
profile is github-identity.v1's, unchanged.

## Secret capability

The App key lives once in the CloudRoom secret `OPENWIZ_GITHUB_APP_KEY`
(github-identity.v1), with the public App id as `OPENWIZ_GITHUB_APP_ID`.
`app_registrations` counts App registrations made for this owner; more than one
is a blind replacement registration.

**The named upstream dependency.** The preferred no-paste route needs the
**CloudRoom agent-side save-secret contribution** (`upstream.name:
cloudroom_agent_save_secret`) to ship a supported interface. Its `state` is
`observed_supported`, `not_shipped` or `unknown`. Only
`cloudroom_save_observed` (a real supported save and its later delivery,
observed) establishes `observed_supported`; `test_stand_in`, `documentation`
and `patch_prepared` never do. This contract names no command for it: the
interface is pinned when it is observed, through plan-graph change control. T4
#634's prepared patch alone enables nothing.

| `route` | When | Converted key | Owner steps | Key file |
| --- | --- | --- | --- | --- |
| `agent_save` | Only with `observed_supported` | `stored_by_agent_save` | None: one `agent_save` step by the agent | `none` |
| `protected_paste` | Until then: the existing fallback | `discarded` (the merged tool's safe behaviour with no supported sink; the App's identity is kept) | `open_app_settings`, `generate_key`, `encode_key`, `paste_protected_prompt`, `delete_download`, each by the owner and each `counted`; `download_key` also when the browser asks | `owner_download_deleted` |

**The fallback's temporary owner download, reconciled.** The protected-paste
route is the existing recovery of `docs/agents/github-app.md` (step 4): GitHub
generates a replacement key and the browser downloads it to the owner; the owner
encodes it to one base64 line, pastes it into CloudRoom's own protected prompt
(`room-cli secret request OPENWIZ_GITHUB_APP_KEY`), never the chat, and deletes
the download. That download is the one temporary key file this route has. It is
the owner's, outside the setup and any Git tree, and deleted after provisioning;
`intermediate_key_file` records it. github-identity.v1's rule that nothing
writes the key anywhere else still holds for every OpenWiz component; this is
an explicit, counted exception for the owner's browser download only, never a
no-download route and never a clipboard bridge. A retained download fails; an
unknown one keeps the result unproven.

`delivery` is `verified` only on `delivered_app_id_matches`: the secret reached
the agent's environment and the delivered App id agrees with the saved one. A
closed prompt or an accepted save is not delivery. `outcome` `stored` needs
verified delivery; `failed` and a refused delivery fail; `uncertain` stays
unproven until reconciled, and never permits a second registration. A later run
reuses the saved App and secret; rotation and revocation use the same protected
handling, never routine re-registration.

## Init

`openwiz init` is the installed command of [cli.v1](cli.v1.md#init-0016-t5),
pinned there for T5. An `init_request` names the `repository`, its `mode`
(`preview` or `apply`), the durable `operation_id` and request `fingerprint`
(setup.v1's forms), and `authorization`. A preview carries no authorization; an
apply carries the exact matching operation id and fingerprint, or nothing
happens. There is no placement input.

An `init_result` reports what happened:

- **Visibility first.** `repository.visibility` comes from GitHub's canonical
  repository read (`basis: github_repository_read`). Unknown, ambiguous or
  locally inferred visibility refuses before any private material is written:
  `outcome: refused`, `brain: null`, `private_content_written: none`, no effect.
- **No placement question.** `placement_question` is always `false`.
  Private code gets the brain `in_repository`; public code gets a private
  `companion`. A public repository never receives private content
  (`private_content_written: code_repository` fails).
- **Visible proposals.** Brain files are proposed through a visible pull
  request on the brain's repository (`open` or `merged`). An applied init
  without one is refused. A private repository has no companion effect.
  When init creates the companion in this same apply, it also merges that
  pull request, under the same authorization, right after opening it and
  reading it back, and reports it `merged`; the pull request stays as the
  visible proposal and record. Only GitHub's own replies to this operation's
  create requests count: the companion's repository id and the pull request's
  number and head must still match them. A creation or proposal known only
  from a later read, an existing companion, an in-repository brain and a
  repeated init leave the pull request `open` for the user.
- **One line.** `report_line` names the brain's repository as a whole word and
  says how to change it later.
- **Effects once.** Each effect (`create_companion`, `link_companion`,
  `open_pull_request`, `create_label`, `merge_pull_request`) has
  first-hour.v1's `phase`, `effect_count`, `attempts` and `reconciliation`:
  above one effect is a duplicate; above one attempt without
  `provider_read_back` is a blind retry; `uncertain` stays unproven until
  reconciled. A repeated init reconciles the existing brain, companion, link
  and pending pull requests before any call. `merge_pull_request` belongs only
  beside a `create_companion` of the same companion in the same result; once
  it has an attempt, that creation is `applied`, and once it is `applied`, the
  brain's pull request reads `merged`. Any other merge is
  `phase_effect_mismatch:merge_pull_request`.

Repository creation and changes remain disclosed effects under setup.v1's
explicit, current authorization; this contract adds no route or authority.

## Brain reference

| Field | Meaning |
| --- | --- |
| `location` | `in_repository` (private code) or `companion` (public code) |
| `code_repository`, `code_visibility` | The selected repository and its positively read visibility |
| `brain_repository`, `brain_visibility` | Where the brain lives; it must read back `private` |
| `visibility_basis` | `github_repository_read` |
| `folder` | Always `.openwiz/brain` |
| `setting` | Always `brain_location`: the one setting that changes it later, through the same visible-proposal rules |
| `decision_repositories` | For a companion, exactly decisions.v1's existing pair setting: `public` the code repository, `private` the companion. For in-repository, `null` |

**How current settings consumers find it.** Consumers reuse the existing
interfaces rather than a new configuration system. The setup store keeps the
reference as an optional `brain` field (setup.v1); decisions and the service
find a companion through the existing `decision_repositories` pair in
`service/config.json`. A project without a brain reference is an existing
project and stays readable exactly as today: its setup state, its project
settings and its single-repository or configured-pair discovery are unchanged,
and nothing infers a brain for it. A companion that is the code repository
(case-insensitively), a pair that disagrees, an in-repository brain elsewhere or
a pair on an in-repository brain is refused. Only human-readable records go in
the brain: grills, decisions and the one logical settings record. Specs and
tickets stay GitHub issues. Credentials, machine details, runtime state and
thread identifiers never enter repository content.

## The 0.0.16 receipt

A `first_merge_receipt` is a distinct result beside first-hour.v1's. It never
relabels the first hour: first-hour.v1 keeps its fixed one-hour limit
(`3600000`) and its separate ten-minute-to-running-fleet measure, with their own
meaning and verdicts.

- **Binding.** `binding` names the SHA-256 of the same attempt's first-hour.v1
  result document, the same `candidate` and `repository` facts, and the merge:
  pull request, head, merge commit, GitHub's merge time, `basis`, whether the
  change is an `implementation` or `init_only`, and the reviewed and CI-green
  heads. Only `merge_read_back` with both heads equal to the merged head is a
  verified merge; an init-only merge fails.
- **Clock.** It starts when the public install instruction is opened and ends at
  that merge time (`ended_at_ms` equals `merged_at_ms`). `limit_ms` is
  `1800000` and the rule is `strictly_less_than`: 1,799,999 ms can qualify;
  1,800,000 ms fails. Nothing is paused or subtracted; every wait, help and
  action lies inside the clock.
- **Actions.** `count` is a `Fact` that must equal the log's length; `limit` is
  `5`. A sixth action fails; an unknown count never passes. Every required
  tap, sign-in, permission, App manifest step, key step, protected paste, typed
  choice and its submission, confirmation, approval and spending approval is one
  entry. An agent's stand-in for an owner action is logged as
  `agent_for_owner` and counts exactly like it. A created App logs at least its
  two manifest steps (Create, Install). The protected-paste route logs at least
  four key steps and one paste.
- **Identity and secret route.** `identity` is `app` or `personal_login`.
  `app_registration` is `created`, `reused` or `skipped`, and `secret_route`
  `agent_save`, `protected_paste` or `not_used`. The skip-App path is
  `personal_login`, `skipped`, `not_used`; a created App names the route it
  used, and `secret_route_observed` says that route itself was observed. Each
  route earns its own result: a fallback pass is never claimed from a no-paste
  run, nor the reverse.
- **Decisions, freshness and text.** Both separate saved decisions
  (`spec_confirmation`, `plan_approval`) are true. `freshness` records a
  `fresh` machine and repository, no seeded OpenWiz state and the recorded
  initial tools and sessions. `instruction` and `idea` keep the text used.
  Help from a `prepared_plan` or `private_instruction` keeps it unproven.

## The verdict

The checks sort what a document shows into three lists, as first-hour.v1 does:
**problems** refuse the document itself, **failures** fail the attempt, and
**unproven** keeps it short of a pass. Only a receipt has a `verdict`: `fail`
when there is any failure; `pass` only for a `live` receipt with a pointer, no
synthetic assumptions, no failure and nothing unproven; otherwise `unverified`
(or `fail`). No fixture or recording is ever a live pass, and missing, invalid,
simulated or stale evidence is never success.

## Codes

Every consumer reports exactly these codes. A `:<...>` suffix names the item.

| Code | List | Given when |
| --- | --- | --- |
| `not_strict_json` | problem | the text is not strict JSON |
| `schema` | problem | the document does not match the schema; nothing else is checked |
| `synthetic_live` | problem | a `live` document with synthetic assumptions |
| `synthetic_unlabelled` | problem | a non-`live` document without them |
| `live_without_private_record` | problem | a `live` document without a pointer |
| `leaked_credential` | problem | the document text holds a credential shape |
| `login_weak_evidence` | problem | a verified login without both read-backs |
| `app_weak_evidence` | problem | a verified App without an installation token read-back |
| `stale_evidence:<which>` | problem | the establishing evidence is from another check generation (`personal_login` or `app`) |
| `skip_not_chosen` | problem | the login path is selected without the owner's explicit skip |
| `silent_identity_switch` | problem | the selection is a fallback |
| `selection_without_choice` | problem | an identity is selected with no owner choice |
| `skipped_app_verified` | problem | a skipped App is reported verified |
| `user_app_not_private` | problem | a user App that is public or not on its private default |
| `factory_app_not_explicit` | problem | a factory App that is private or lacks its explicit setting |
| `cross_account_private_app` | problem | a user App used, installed or selected outside its owner's account |
| `all_repositories_installation` | problem | an installation on all repositories |
| `repository_not_installed` | problem | a verified App whose installation does not cover the selected repository |
| `identity_ready_inconsistent` | problem | `ready` is not what the readiness rule gives |
| `upstream_weak_evidence` | problem | the save-secret contribution is called supported without being observed |
| `agent_save_unavailable` | problem | the no-paste route without an observed supported contribution |
| `no_paste_route_inconsistent` | problem | the no-paste route with owner key steps, a key file or an unsaved key |
| `fallback_step_missing:<step>` | problem | the protected-paste route lacks a required owner step |
| `owner_step_uncounted:<step>` | problem | an owner key step is not counted |
| `converted_key_kept` | problem | the protected-paste route did not discard the converted key |
| `fallback_download_unrecorded` | problem | the protected-paste route claims no key download |
| `delivery_weak_evidence` | problem | delivery verified without the delivered App id agreeing |
| `secret_success_claimed` | problem | `stored` without verified delivery |
| `authorization_mismatch` | problem | an apply without the exact matching authorization |
| `preview_authorized` | problem | a preview carrying an authorization |
| `visibility_unverified_init` | problem | init proceeded, chose or wrote without positively read visibility |
| `brain_placement_mismatch` | problem | the brain's location does not follow the code's visibility |
| `brain_visibility_mismatch` | problem | the reference's code visibility is not the visibility read |
| `brain_not_private` | problem | the brain's repository does not read back private |
| `companion_same_repository` | problem | the companion is the code repository |
| `in_repository_mismatch` | problem | an in-repository brain in another repository |
| `brain_pair_mismatch` | problem | the decisions pair setting does not match the placement |
| `unexpected_companion` | problem | a companion effect for private code |
| `outcome_brain_missing` | problem | a proposed or applied init with no brain reference |
| `brain_change_not_visible` | problem | an applied init without a visible open or merged pull request on the brain's repository |
| `report_line_missing_location` | problem | the report line does not name the brain's repository |
| `phase_effect_mismatch:<kind>` | problem | an effect count or attempts that do not match the phase |
| `duplicate_effect_row:<kind>:<repository>` | problem | one effect listed twice |
| `clock_order` | problem | the clock ends before it starts |
| `clock_not_merge` | problem | the clock does not end at the merge time |
| `outside_clock:<list>:<index>` | problem | an action, wait or help lies outside the clock, or a wait ends before it starts |
| `action_count_mismatch` | problem | the known count is not the log's length |
| `merge_weak_evidence` | problem | the merge is not read back at the reviewed, CI-green head |
| `secret_steps_uncounted` | problem | the protected-paste route without its key steps and paste in the log |
| `app_steps_uncounted` | problem | a created App without its two manifest steps in the log |
| `identity_route_inconsistent` | problem | identity, registration and secret route disagree |
| `non_live_pass` | problem | a pass from a fixture or a recording |
| `unproven_pass` | problem | a pass with anything unproven |
| `failure_not_reported` | problem | a failure with a verdict other than `fail` |
| `key_download_retained` | failure | the owner's key download was kept |
| `duplicate_app_registration` | failure | more than one App registration |
| `secret_store_failed` | failure | the store failed or delivery was refused |
| `private_content_published` | failure | private content written to public code |
| `duplicate_effect:<kind>` | failure | an effect count above one |
| `blind_retry:<kind>` | failure | more than one attempt without `provider_read_back` |
| `thirty_minutes_missed` | failure | elapsed time of 1,800,000 ms or more |
| `actions_exceeded` | failure | a known count above five |
| `init_only_merge` | failure | the merge is an init-only change |
| `not_live` | unproven | a fixture or a recording |
| `key_download_unknown` | unproven | whether the key download was deleted is unknown |
| `delivery_unverified` | unproven | delivery missing, unknown or uncertain, or an uncertain outcome |
| `effect_uncertain:<kind>` | unproven | an effect still uncertain |
| `outcome_uncertain` | unproven | init's outcome is uncertain |
| `clock_unknown` | unproven | either clock time is unknown |
| `action_count_unknown` | unproven | the action count is unknown |
| `candidate_unknown` | unproven | the candidate is unknown |
| `repository_unknown` | unproven | the repository is unknown |
| `prepared_help` | unproven | help from a prepared plan or private instruction |
| `not_fresh:<which>` | unproven | the machine or repository is not positively fresh |
| `seeded_state` | unproven | OpenWiz state was seeded |
| `initial_record_missing` | unproven | the initial tools and sessions were not recorded |
| `decision_unsaved:<decision>` | unproven | a separate saved decision is missing |
| `secret_route_unobserved` | unproven | the secret route used was not itself observed |

## Seams

`tools/install/tests/setup-onboard-contract/check.py` is the seam: later
tickets load it by path and report its codes (`check(document)` and
`check_text(text)` return the three lists). It implements no runtime.

| Seam | For | Today |
| --- | --- | --- |
| `identity_selection` producer: setup store `identity` field, server reasons, page | T2 #633 | Pending: no field is written or served |
| User App manifest and owner-bound token paths; `secret_capability` producer | T3 #606 | Pending: the manifest is still the factory's public App |
| `cloudroom_agent_save_secret` interface | T4 #634, then a plan change | Not shipped; no command is named |
| `openwiz init`, `init_request`/`init_result`, setup store `brain` field | T5 #635 | Pending: not in the shipped catalogue |
| Continuation carrying identity and brain into onboard | T6 #636 | Pending |
| Receipt validation inside the installed journey and live kit | T7 #637 | Pending; this checker is its contract-level core |

## Privacy

Public records carry synthetic or sanitized technical values only. Raw account,
machine and session evidence and exact decision words stay in the private
repository, reached through `private_record`. No thread id, token, key,
credential, prompt, transcript or private code appears in any document.

## Proof limits

The schema checks parsed shape; the checks prove these cross-field rules on the
synthetic cases. Together they prove interface consistency only: sign-in, App
creation, key delivery, init, timing, the action count and the merge remain
Unverified until their own evidence.
