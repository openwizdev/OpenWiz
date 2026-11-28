# OpenWiz persona v1 (`openwiz.persona.v1`)

A persona supplies the style of Wiz's human-facing words. A theme supplies
its colours, optional sounds and room look.

## Files

A pack contains `persona.json` and its matching `theme.json`. Users can
select a different theme by its own ID. Each file is a UTF-8 JSON object
with each field written once, validated by
[`persona.v1.schema.json`](persona.v1.schema.json).

### Persona

| Field | Meaning |
| --- | --- |
| `schema` | `openwiz.persona.v1` |
| `id` | A lowercase slug with alphanumeric parts separated by hyphens |
| `name` | The original display name |
| `family` | `film-ai`, `character`, `pro` or `fun` |
| `vibe` | A one-line generic description |
| `tone`, `vocabulary` | The tone and a list of wording cues |
| `greeting`, `sign_off` | Optional framing text, written as an empty string when unused |
| `error_style`, `docs_tone` | Framing for human errors and docs answers |
| `speech` | A `voice_id` from the local engine's reviewed voice registry and a `pace` multiplier from 0.5 to 2, with 1 at the engine's normal pace |

Render style values as text. They can influence framing vocabulary and tone.
Facts, instructions, tools, permissions and safety rules come from the
ordinary producer and its existing authority checks. The schema refuses
unknown fields at every level. A style consumer treats even words inside an
allowed field as untrusted style data and refuses attempts to grant authority
or rewrite facts.

### Theme

| Field | Meaning |
| --- | --- |
| `schema`, `id` | The same version and slug form as a persona |
| `light`, `dark` | Each has `background`, `surface`, `text`, `muted`, `accent` and `border` in six-digit `#RRGGBB` form |
| `sounds` | Optional `needs_you` and `status` cues in an object. An empty object is silent. |
| `room` | The immersive room reads this field for its look. It contains a `palette` of colours, a `lighting` description and `mood` words. |

Each cue supplies `waveform` (`sine` or `triangle`), `frequency_hz`
(80 to 2,000), `duration_ms` (1 to 250) and `gain` (0 to 0.15 on a 0 to 1
scale). The client synthesizes cues at playback and takes no recordings or
asset references from the theme. Sounds and spoken updates are off by
default. Only the user's corresponding setting enables playback. A voice id
selects a reviewed original voice on the local engine. [Persona
settings](https://github.com/openwizdev/OpenWiz/issues/3905).

The immersive room uses `theme.room` as its palette, lighting and mood
input. Its own contract handles the scene, controls and rendering.
[Immersive room spec](https://github.com/openwizdev/OpenWiz/issues/3870).

## Facts and the two faces

Every human message carries its facts block and next-command line from the
plain producer. The persona can add framing before or after those parts.
Insert the two source parts in order, byte for byte, including whitespace,
line endings and command quoting. The plain producer supplies the
next-command line even when there is no command to run. A style renderer
uses the plain presentation if it cannot preserve either part exactly.

JSON output, records and contracts use their existing machine-facing
producers. Bypass persona rendering for them so their bytes are identical
under every persona.

## Originality and proof

Use original names, generic one-line vibes and original local voices.
Review rejects trademarked names, copied likenesses and voices cloned from
a person or character. Schema validation checks shape. Review checks
originality of the name, wording and selected voice.

Run `python3 -I contracts/fixtures/persona/test_fixtures.py` to validate the
synthetic persona and theme and refuse each broken variant. The rendering
examples check the separate byte-preservation rule, including changes to
whitespace in otherwise equivalent machine output.
