# Answer a Needs you item

From Home, press its number (`1`–`9`), or select it with ↑/↓ and Enter. Selection reads only. Inspect the exact proposal, context and recommendation, then press `a` to open Answer. A held/needs-info fleet label without a decision proposal cannot be answered here.

The panel pins the exact configured orchestrator target at the top. PageDown/PageUp scroll the reply, proposal, fingerprint, risk, source/target ages, effects and outcome underneath it. Enlarge a window that cannot show the whole target: a clipped target cannot be confirmed. Ages describe the last action input or refreshed snapshot; confirmation rechecks current source and target age.

Space cycles the focused **Reply kind**. Grill questions offer `yes`, `simplify` and `own words`; confirmations offer `yes` and `own words`. Tab moves to the editable own-words field. Type, paste, use Ctrl-J for a newline and Backspace to remove the last character. Leading/trailing spaces, Unicode and newlines are preserved exactly. The **Sends** field shows the reply and UTF-8 byte count. Displayed control characters are made terminal-safe without changing the reply bytes.

| Selected record | Yes sends | Simplify sends |
| --- | --- | --- |
| Grill question G1 | `G1 yes` (accepts its displayed recommendation) | `simplify G1` |
| Grill summary confirmation | `confirm` | Use own words |
| Spec confirmation #9001 | `confirm spec #9001` | Use own words |
| Plan approval #9001 | `approve #9001` | Use own words |

These identifiers are synthetic examples. Own words always sends exactly your words, with no question prefix. If that reply is ambiguous, the question remains visible in the binding; the terminal does not rewrite it or batch answers.

Press Ctrl-P to read the existing Queue send preview. Inspect its target and effects. It sends nothing. Empty/whitespace-only text, NUL or more than 16,384 UTF-8 bytes is refused, never truncated or split. Answer does not silently acknowledge a paused queue or a possible duplicate; a preview requiring acknowledgement explains the refusal.

Press Ctrl-S to confirm only after preview. Explicit `live`, `release` or `publish` risk needs a second distinct confirmation. Where releases are reported, release Ctrl-S and press again; otherwise the next confirmation is Ctrl-Y, then Ctrl-S alternately. A held key never confirms. Unknown risk, incomplete/stale/unknown sources, unknown current wording, an unverified target or missing configured allowed host disables answering with a reason. Refresh stale reads before previewing again. Changed/removed wording, fingerprint, risk or target requires reopening the displayed item. Editing or Esc cancels the preview/confirmation; nothing is sent by opening, editing, navigation or refresh.

After dispatch, retain the operation id. Ctrl-R performs only the existing send lookup. The same accepted item retains its original operation for status reads; there is no resend key. Another item can open a fresh draft after a matching report confirms delivery. An uncertain/in-progress operation blocks other items until a matching lookup settles it or fresh complete decision coverage proves the original item no longer pending. That source change does not prove delivery. Partial/stale absence and failed status reads never release the lock. A confirmed outcome stays visible even if a later lookup fails; the latest read does not erase earlier confirmation. An explicit refusal or proven failure before dispatch allows an explicitly reopened draft with a new preview and confirmation. Restoring the connection or reading status never retries anything. `accepted`/sent means provider acceptance, never a saved answer, approved decision or completed work. `uncertain`, in-progress, failed, refusal and conflicting reuse remain distinct; a failed status read cannot lower an uncertain outcome. Only the orchestrator's later record change saves/resolves the decision.

This terminal does not offer durable restart recovery. Before quitting, keep the shown operation id and target privately. Use `openwiz send <target> --op-id <op-id> --check --json` for a read-only lookup; a restart never restores a send confirmation or replays a write. Do not interpret absent local metadata as safe to resend.

Fixture proofs exercise the screen, HTTP and actual fake-source server. They establish no live or Mac behaviour. The bounded live part is [answer.md](../live-checks/0.0.12-parts/answer.md); its separate approval remains required.
