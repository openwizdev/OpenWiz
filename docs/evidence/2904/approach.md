# Approach note: provider-qualified model ids (#2904)

## Grammar

A `model` is one to 100 characters made of `/`-separated segments. Each segment keeps today's character rules: it opens with a letter or digit, then letters, digits, space, `.`, `_`, `:`, `@`, `+` or `-`.

- Schema: `"pattern": "^[A-Za-z0-9][A-Za-z0-9 ._:@+-]*(/[A-Za-z0-9][A-Za-z0-9 ._:@+-]*)*$"` with `"maxLength": 100`, as the `skill` field already pairs a pattern with `maxLength`.
- Local driver `START`: the same pattern with the length as a lookahead, as its `skill` entry already does: `(?=.{1,100}$)[A-Za-z0-9][A-Za-z0-9 ._:@+-]*(/[A-Za-z0-9][A-Za-z0-9 ._:@+-]*)*`.
- Because every segment must open with a letter or digit, these are refused by construction: a leading or trailing `/`, `//`, a `.` or `..` segment, any segment opening with `.`, `-` or a space (so a space-only segment).
- `~` stays out: no `~`-prefixed id appears in the docs of OpenCode, Kilo, Crush (catwalk v3.2.9), Pi or Kimi Code that I read.
- The cap rises from 60 to 100. Real ids pass 60: `openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (61) and `fireworks/accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b` (66), both a catwalk v3.2.9 provider id plus one of its model ids. 100 matches the cap of the start's other identifiers (each `repository` part, a run id) and leaves room for one more routing prefix.

## Threats

- **Path traversal.** No `.` or `..` segment, no segment opening with `.`, no leading `/`: a model that reached a path could not climb out or name an absolute path. Today no driver here puts the model in a path: the local driver passes it as one whole argument (harness-row contract: a placeholder fills a whole argument).
- **Argument injection.** The id and every segment open with a letter or digit, so it can never read as an option (`-x`, `x/-y` refused). There is still no shell: the local driver runs an argument list.
- **URLs.** `scheme://host/...` holds `//`, so it is refused: the field cannot point a harness at another endpoint.
- **Credential shapes.** The kit's `holds_credential` check on start fields is unchanged. `/` widens what the grammar lets through, so the tests check that no real id is flagged, and that a known credential shape is still refused when sent as a model.
- **Length.** One hard cap, 100. The pattern has no nested ambiguity (`/` is outside the segment class), so matching is linear.
- **Encoding.** ASCII ranges only; no newline or control character can pass.

## What the tests can and can't prove

- Can: every real id cited from the five CLIs' docs and sources passes the kit's schema check and `adapters/local/driver start`'s validation (the start then fails later, for the synthetic harness, not for the model); every listed bad shape is refused by both with D3 `model is not valid`; the schema and the local driver agree on every case; every `adapters/*/schema.json` is a byte copy; no real id is flagged as a credential.
- Can't: that any real CLI accepts these ids, or that a run with them works. No real agent CLI is started (refusing stubs sit first on every test's `PATH`). The other drivers (`template`, `boat`, `cloudroom`, `devin`, `openclaw`) keep their own `START` patterns; this ticket copies only their `schema.json`, so their own validation of `/` is unchanged and is each driver's own ticket.

## Update: the other drivers

By the planner's ruling (a), this ticket also changes the `START` model pattern of `adapters/{template,boat,cloudroom,devin,openclaw}/driver` and `KIT_MODEL` in `kernel/live-rig/rig.py` to the same grammar, with one test per driver. So every driver here accepts and refuses the same ids as the schema. `contracts/roster.v1.md` stays unchanged (ruling (2)); its follow-up is the lead's.
