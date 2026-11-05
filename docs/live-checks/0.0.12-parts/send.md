# 0.0.12 bounded message part (T5 / CP6)

This is a procedure for #1104, not permission to run it. Under ADRs 0015/0016,
a Local PC agent runs it only after earlier version gates, read-only discovery
of the installed endpoint/tell arguments/server settings, and Jake's explicit
version-level permission. Fixture tests prove no live behavior.

Use the kit's **pre-existing designated throwaway target** and a synthetic
message. This part consumes **at most one send**, within the entire kit's two
sends (one answer plus this message) and one create. Missing target means
stop/revise the kit; never create an extra test target. No attachments,
other targets, retries, tunnels, merges, releases or publishing.

1. Open `openwiz ui` with the discovered local port and owner's allowed-host
   setting. Sessions → the designated session → `m`. Check the displayed
   target against the independently designated one without recording it in
   repository evidence.
2. Compose a harmless synthetic message. Choose Queue (or the separately
   approved mode). Ctrl-P previews; check target, exact escaped text/byte
   count, requested mode, effects and source age. Scroll with PageDown.
   Esc cancels: zero sends so far. Resize and return; cancellation must not
   submit or replace the draft with a different target.
3. Reopen that same target, compose/review the same bounded message. If a
   paused-queue acknowledgement is needed, verify that resuming the target's
   queued work is within the permission; otherwise stop. Explicitly tick
   only the approved acknowledgement and preview again. A duplicate gate or
   unresolved earlier operation is a stop/gap for this no-retry kit, not
   authority to tick allow-duplicate or compose again.
4. Record the operation id privately for lookup. Only after the displayed
   effects/target are reviewed, press the shown confirmation key once.
   Consume the send allowance even if the response disconnects or is
   uncertain; never repeat the operation. No held/repeated confirmation
   should cause another send (fixture proof covers these negative cases).
5. Read the outcome, requested mode and operation id. Ctrl-R performs only
   lookup. Accepted means provider acceptance, never completed work. Keep
   uncertain/in-progress/missing-record states as gaps; no resend. The CLI
   `openwiz send <target> --op-id <op-id> --check --json` is the existing
   read-only fallback if the terminal exits; restart recovery is unavailable.
6. Esc/back and quit. Verify cursor/input restoration and read back the send
   record. Store only tested head/tree, send/lookup counts, sanitized outcome
   categories and remaining gaps, never identifiers, text or transcripts.

The separate Mac check stays read-only; this part grants it no send.
