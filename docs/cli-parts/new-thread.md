# Start one Cloud thread from the terminal

Use an already running local server. Open `openwiz ui --allowed-host NAME`
with the owner's configured server host (or use `OPENWIZ_SERVER_ALLOWED_HOST`).
The terminal connects only to loopback. Missing host configuration leaves
creation and its guarded preview disabled; it never starts a server or tunnel.

1. In Sessions (`s`), select a session in the existing project, then press `n`.
   The target is that project's exact id. The project row can select another
   project represented in the current session inventory; projects with no
   listed sessions are not offered by this terminal view.
2. Tab between project, harness, model, effort and first prompt. Space cycles
   the row's offered choices in source order; exact ids may also be typed or
   pasted. Harness/model/effort begin empty. No choice is defaulted or
   substituted. A harness/model change clears downstream choices that are no
   longer offered. Unavailable options retain their reason. Ctrl-R re-reads
   options before a create attempt and invalidates any previous preview.
3. Type or paste the exact first prompt; Ctrl-J inserts a newline. Leading
   dashes, whitespace, quotes and Unicode are preserved. Empty/whitespace-only
   text, NUL and more than 16,384 UTF-8 bytes disable preview/creation. Terminal
   control/invisible characters and line breaks display as replacement
   characters (`�`), without changing the submitted bytes. There is no attachment tray or Local-thread option.
4. Ctrl-P previews. Read the exact target, settings, prompt, operation id and
   every effect, using PgUp/PgDn to scroll the action pane. Options/preview
   show their reported read timestamps; CloudRoom may use a saved copy of
   unknown source age. A stopped/refused preview explains why creation is
   unavailable. Any input change requires a fresh preview. Esc cancels a
   draft without creating anything.
5. Only after inspecting the preview, press the displayed confirmation key
   (initially Ctrl-S) to create once. On terminals without key-release
   reporting, confirmation keys alternate Ctrl-S/Ctrl-Y; held/repeated keys
   cannot dispatch twice. An exact target that cannot fit on its fixed header
   line disables confirmation until the window is enlarged.

After confirmation this attempt's inputs are read-only. It retains its op id
across closing/reopening the panel and navigation. Ctrl-R now reads only that
operation's status, once per explicit request; there is no automatic polling
(zero reads is within the ten-automatic-read maximum), retry or start-over
control. Refusal, failed dispatch and guard rejection also end this screen's
attempt. Quitting the terminal never cancels or replays an already dispatched
create.

**Created** means CloudRoom recorded the thread and prompt. It does not mean
started. The separate start stage can be waiting to start, started as reported,
idle as reported (first-prompt execution unconfirmed), start failed or unknown.
Requested settings stay visible separately from reported configuration; reported
configuration never claims to identify the serving model. Uncertain/in-progress
attempts remain unresolved, and failed, missing or mismatched status reads do
not make them safe to retry. Observed threads alone never resolve uncertainty.

Restart recovery is unavailable: keep the displayed op id before quitting.
After restart, use the existing read-only command
`openwiz new --status <op-id> --json`; it does not create or replay anything.
A fresh terminal does not restore a saved attempt or prove an earlier attempt
failed. Do not reconstruct an uncertain create as a new draft. There is at most
one create attempt per terminal process; a later intentional create needs a
separate process and remains a separate explicitly confirmed operation.

These behaviors have synthetic fixture proof. Real-account operation, Mac
coverage and version acceptance remain unverified until the separately approved
[0.0.12 live check](../live-checks/0.0.12.md).
