# OpenWiz persona contract, version 1 (`openwiz.persona.v1`)

A persona is the style of Wiz's human-facing words: its tone, vocabulary,
greeting, sign-off, error style and docs tone, and the voice it speaks in. A
theme is its look: colours, sound cues and a room. This contract fixes both
files and the rules that keep a persona to style only. The schema is
[`persona.v1.schema.json`](persona.v1.schema.json); its fixtures and proof are
in [`fixtures/persona/`](fixtures/persona/README.md).

Authority: PS1 of the 0.2.0 personas and themes spec (#3868).

## Words

| Word | Meaning here |
| --- | --- |
| **Persona** | The style of Wiz's human-facing words; never its facts, rules or permissions. |
| **Theme** | Colours, sound cues and a room look. It follows the persona unless the user swaps it. |
| **Facts block** | The exact facts of one message: what happened, numbers, names. |
| **Next command** | The exact command the user runs next. |
| **Human face** | Text written for a person to read: messages, errors, help and docs answers. |
| **Machine face** | JSON output, records and contracts. |

## The persona file

One JSON object with each field once, and no other field.

| Field | Rule |
| --- | --- |
| `schema` | `openwiz.persona.v1`. |
| `kind` | `persona`. |
| `id` | Lowercase words joined by `-`, at most 40 characters. |
| `name` | An original name, one line. See [Originality](#originality). |
| `family` | One of `film-ai`, `character`, `pro`, `fun`. |
| `vibe` | One line describing the vibe in generic words. |
| `tone` | One line. |
| `vocabulary` | One to 24 distinct words or short phrases the persona likes to use. |
| `greeting`, `sign_off` | One line each. |
| `frame` | The template for an ordinary human message. See [The facts rule](#the-facts-rule). |
| `error_style` | The template for a human error message, with the same rule. |
| `docs_tone` | One line saying how Wiz's docs answers read. |
| `speech` | `engine` is `local`; `voice` is a local engine voice id, `local:<name>`; `pace` is 0.5 to 2 (1 is normal); `original` is `true`. |
| `faces` | Exactly `["human"]`. See [Two faces](#two-faces). |
| `theme` | The `id` of the persona's matching theme. |

```json
{
  "schema": "openwiz.persona.v1",
  "kind": "persona",
  "id": "fixture-lanternkeep",
  "name": "Lanternkeep",
  "family": "film-ai",
  "vibe": "A calm, attentive household AI that keeps things tidy and explains gently.",
  "tone": "calm, courteous, brief",
  "vocabulary": [
    "certainly",
    "in order",
    "at your service"
  ],
  "greeting": "Good evening. Everything is in order.",
  "sign_off": "At your service.",
  "frame": "A brief update:\n{facts}\nWhen you are ready:\n{next}",
  "error_style": "My apologies, something went wrong.\n{facts}\nTo set it right:\n{next}",
  "docs_tone": "patient, step by step, one idea at a time",
  "speech": {
    "engine": "local",
    "voice": "local:fixture-warm-01",
    "pace": 0.95,
    "original": true
  },
  "faces": [
    "human"
  ],
  "theme": "fixture-lanternkeep"
}
```

## The theme file

| Field | Rule |
| --- | --- |
| `schema`, `kind`, `id` | `openwiz.persona.v1`, `theme`, and an id as for a persona. |
| `colors` | `light` and `dark`, each with exactly the tokens `background`, `surface`, `text`, `muted`, `accent`, `warning` and `danger`, as lowercase `#rrggbb`. |
| `sounds` | `enabled` is `false`: cues stay off until the user turns them on in their settings. `cues` maps `done`, `needs_you`, `failed` or `started` to synthesis parameters: `wave` (`sine`, `triangle`, `square`, `sawtooth`), `frequency_hz` (100 to 2000), `duration_ms` (20 to 400) and `gain` (0 to 0.3). There is no field for recorded audio, so a theme can't ship a sound file. |
| `room` | The `room` object is the field the immersive room reads to give the 3D room its look: `palette` (two to six colours), `lighting` (one short line of lighting words) and `mood` (one to five single lowercase words). This contract fixes only the field; how the room renders it belongs to the immersive room spec. |

```json
{
  "schema": "openwiz.persona.v1",
  "kind": "theme",
  "id": "fixture-lanternkeep",
  "colors": {
    "light": {
      "background": "#f7f4ee",
      "surface": "#ffffff",
      "text": "#1d1b18",
      "muted": "#6b665e",
      "accent": "#2f6f8f",
      "warning": "#9a6400",
      "danger": "#b3261e"
    },
    "dark": {
      "background": "#14161a",
      "surface": "#1d2026",
      "text": "#ecebe8",
      "muted": "#9a978f",
      "accent": "#7cc3e0",
      "warning": "#e0a84a",
      "danger": "#f2766d"
    }
  },
  "sounds": {
    "enabled": false,
    "cues": {
      "done": {
        "wave": "sine",
        "frequency_hz": 660,
        "duration_ms": 120,
        "gain": 0.15
      },
      "needs_you": {
        "wave": "triangle",
        "frequency_hz": 520,
        "duration_ms": 180,
        "gain": 0.2
      }
    }
  },
  "room": {
    "palette": [
      "#14161a",
      "#2f6f8f",
      "#e9d9b4"
    ],
    "lighting": "warm lamps, low and even",
    "mood": [
      "calm",
      "orderly",
      "warm"
    ]
  }
}
```

## Style only

A persona changes words, theme and sounds, nothing else. Every object in the
schema refuses any field it doesn't name, so a persona or theme can't carry
facts, rules, tools, permissions, safety settings or anything an agent acts
on.

## The facts rule

Every human message has a facts block and a next-command line. A persona may
frame them but never change them, byte for byte. `frame` and `error_style`
are templates with exactly one `{facts}` slot and then exactly one `{next}`
slot, each alone on its own line. Other lines are the persona's framing and
hold no `{` or `}`. The renderer replaces `{facts}` with the facts block
and `{next}` with the next command, unchanged. A template that drops,
repeats, reorders or shares a line with either slot is refused.

## Two faces

A persona applies only to the human face. JSON output, records and contracts
are the same bytes under every persona, and a persona has no field to change
them: `faces` is exactly `["human"]`.

## Originality

Names are original and vibes are described in generic words. A persona never
uses a trademarked name, a real or fictional character's likeness or a cloned
voice. The schema keeps speech on the local engine with an original voice
and has no field for a voice sample or a likeness; whether a name, vibe or
voice is really original is checked in review, against this rule.
