# T6 / CP7: one Cloud-thread create, for the bounded 0.0.12 kit

**Preparation only. No live permission or endpoint claim.** #1104 integrates
this part after exact-head fixture CI and independent review. CP7 fixture
behavior is covered by `tests/terminal/new_thread.rs`; CP8 is unverified until
an agent observes the separately permitted Local PC run under ADRs 0015/0016.
Graph approval, this part and fixture success grant no live create or release.

Before this part, #1104 must verify earlier versions' live gates, Jake's
version-level live-kit permission, the exact installed head/tree and the
pre-existing designated throwaway target/project. Run the required read-only
PC discovery first: verify the installed endpoint/configuration and current
spawn/tell argument shapes. Treat the terminal's existing fixed adapter
argument shape as unverified against that endpoint until discovery confirms
it. A mismatch or missing target stops the kit for revision; do not provision
an extra thread or change the allowlist. The total kit budget stays **two sends
(one answer and one manual message) and one additional Cloud thread**. This
part consumes only that one create, with no attachments or Local creation.

| Step | Observation and bound |
| --- | --- |
| Options | On the existing session's project, press `n`. Check exact project id, empty harness/model/effort and offered/unavailable choices. Choose only explicitly offered settings. No create. |
| Prompt/preview | Use a harmless synthetic first prompt. Inspect exact prompt, project, chosen settings, op id and all effects with PgUp/PgDn. Ctrl-P previews only. Check each option/preview timestamp and saved-copy limitation. No create. |
| Change/cancel | Change the prompt after preview; confirmation must be unavailable until re-preview. Esc cancels; inspect that no new thread was made. This uses no create. Reopen and compose the one final draft. |
| Confirm | Read the fresh final preview; retain the op id outside repository evidence. Confirm once with the displayed key. This is the sole create budget. If it refuses, fails, disconnects or remains uncertain, do not attempt again. |
| Outcome/status | Check recorded creation separately from reported start. Ctrl-R reads status only. Missing/refused status is a gap, not safe-to-retry evidence. Do not infer first-prompt completion from created/idle or serving model from reported settings. |
| Retention/cleanup | Close/reopen the panel and navigate: same attempt/op id, no additional create. Resize and quit: cursor/raw mode/main screen restored. After restart, inspect only `openwiz new --status <retained-op-id> --json`; never recompose/replay. No further write. |

Do not deliberately induce an additional create to test held keys or network
failures live; fixture proofs cover them. With the permitted single attempt,
any uncertainty consumes the budget and stays unresolved. Status reads are
explicit, bounded one per request, with no automatic polling or retry route.

Record only tested head/tree, sanitized observations, actual write/read counts,
fixture/live evidence classes and remaining gaps. No real project/thread/op ids,
prompt, transcript, credentials or configuration secrets enter repository
files. PC observations prove only the PC. The separately permitted Mac check
is read-only and has its own evidence; it never runs this create step.
Publishing, release, tunnels and paid evaluations retain separate gates.
