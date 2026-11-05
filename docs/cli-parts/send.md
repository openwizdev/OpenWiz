# Send one message in the terminal

Open an existing session in Sessions (`s`, arrows, Enter), then press `m`.
The target stays fixed at the top. Type or paste the exact message; Ctrl-J
adds a newline. The text is displayed with escapes (`\n`, `\t`, `\\`) so
control bytes cannot run in the terminal. The byte count is UTF-8; requests
retain the original bytes, including whitespace and line breaks. Empty,
whitespace-only, NUL-containing or over-16,384-byte text cannot be sent.

Tab selects a field; Space on mode changes Queue/Steer. Space on **resume
queue** explicitly acknowledges that sending may resume queued work. Space
on **allow duplicate** separately accepts the existing possible-duplicate
risk. Both start unchecked. These are permissions, not evidence that work
was delivered. The server checks the current target and gates again.

Ctrl-P reads the existing send preview. Check the exact target, text, requested
mode, effect, paused-queue information, source read time (Unix milliseconds)
and the reported age of that preview snapshot. The age is explicitly a
server-reported snapshot value, not a continuously advancing clock; Ctrl-P
requests a fresh preview. PageUp/PageDown
scroll the pane while its target stays pinned. A refused/missing preview
cannot send; a paused or unknown queue needs its acknowledgement. Every text,
mode or acknowledgement edit invalidates the preview: preview again.
Esc cancels without sending.

Only after reviewing the matching preview, use Ctrl-S to submit once. Held
keys cannot confirm. Terminals without key-release events alternate Ctrl-S
and Ctrl-Y for successive confirmations; the footer shows the required key.
If the exact target cannot fit, confirmation is disabled until resize.

The screen keeps the requested mode separate from the reported outcome:
accepted means the provider accepted the message, **not completed work**;
queued, failed, refused, uncertain and in-progress remain distinct. The
operation id identifies this bound target/text/mode. Ctrl-R looks up that
operation through a read-only route; it never resends. Missing records,
another target or a lookup failure do not make a possibly sent attempt safe
to repeat. An uncertain attempt has no resend control. A matching recorded failure from
lookup is shown as failed while the replay lock stays in place. If transport
positively establishes that nothing reached the server, an explicit edit can
begin a new attempt; confirmation alone never retries, and the new draft
requires a fresh preview and confirmation under a new operation id.

The shell retains attempts across navigation. **Restart recovery is
unavailable:** before quitting, keep the shown target and operation id locally
and check the existing record with `openwiz send <target> --op-id <op-id>
--check --json` (one command). Restart never replays an operation. Do not
recompose unresolved work to bypass its lock.

The terminal requires an already running local server and the owner's
configured allowed host for guarded requests; see [the CLI guide](../cli.md).
Fixture proofs establish this behavior on synthetic sources; live use remains
subject to the separately approved [0.0.12 kit](../live-checks/0.0.12.md).
