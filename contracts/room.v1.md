# OpenWiz room contract v1 (`openwiz.room.v1`)

IM1 of spec #3870. The room is a 3D view of one factory, with a 2D text
equivalent, rendered from one scene file. This contract fixes that file, its
two modes, the steer lines the room may send, the phone budget and the theme
input. The [schema](room.v1.schema.json) checks every record shape here. The
[offline fixtures](fixtures/room/README.md) give one valid record and at least
one broken record for every field, mode, steer line, budget rule and theme
field; every family, agent, number, repository, look and sound cue in them is
invented. This contract grants the room no write route and no authority.

Every record has `schema: "openwiz.room.v1"`. Every listed field is required,
and readers refuse unknown fields in records and nested objects. Times are UTC
`YYYY-MM-DDTHH:MM:SSZ`. A slug is lowercase letters and digits joined by single
hyphens. A text field is one line with no control characters. Schema validity
is a shape check; the reader rules below are checked by the producer and the
room.

```json
{
  "schema": "openwiz.room.v1",
  "scene_file": ".openwiz/room.v1.json",
  "modes": [
    "owner",
    "public"
  ],
  "sources": {
    "stations": "states",
    "figures": "states",
    "pipeline": "states",
    "meters": "usage",
    "requests": "requests",
    "beacons": "feed"
  },
  "steer_lines": {
    "approve": "approve plan #<spec> fingerprint <first 12 hex>",
    "merge": "merge <owner>/<repo>#<n> at <40-hex head>",
    "answer": "answer decision <id> <option>",
    "grant": "grant <comment id>",
    "refuse": "refuse <comment id>",
    "yes": "yes to setting proposal <comment id>",
    "no": "no to setting proposal <comment id>",
    "pause": "pause spec #<n>",
    "prioritize": "prioritize #<n>"
  },
  "phone_budget": {
    "max_figures": 24,
    "max_draw_calls": 120,
    "max_triangles": 150000,
    "min_fps": 30,
    "below_floor": "2d"
  },
  "default_theme": {
    "schema": "openwiz.room.v1",
    "kind": "theme",
    "look": "holo-butler",
    "colours": {
      "background": "#0b1020",
      "surface": "#141c33",
      "text": "#e6f1ff",
      "accent": "#5ad1ff",
      "ok": "#4fd18b",
      "warn": "#f2c14e",
      "alert": "#ff6b6b"
    },
    "materials": {
      "figure": "glass",
      "station": "metal",
      "panel": "emissive",
      "floor": "matte"
    },
    "sound": {
      "on": false,
      "set_by": "default",
      "cues": {
        "beacon": "soft-chime",
        "merge": "two-note-rise",
        "alert": "low-pulse"
      }
    }
  }
}
```

## The scene file

`.openwiz/room.v1.json` in the home checkout, written whole and atomically by
the scene producer from the owner's existing files only. It has no `kind`. The
room reads it and nothing else; it never fetches GitHub or any other service.

| Field | Owner mode | Source |
| --- | --- | --- |
| `schema` | `openwiz.room.v1` | |
| `read_at` | when the producer read its sources | |
| `mode` | `owner` | |
| `stations` | one per model family: `family` (slug), `label`, `text` | the states file |
| `figures` | one per agent: `name`, `role`, `state`, `ticket`, `station`, `text`, `taps` | the states file |
| `pipeline` | the lanes `build`, `review` and `merge`, each a list of pull requests: `repository`, `number`, `ticket` (or null), `text` | the states file |
| `meters` | one per lane window: `lane`, `window`, `used_percent` (0 to 100), `resets_at` (or null), `budget`, `text` | `openwiz usage --json` |
| `requests` | one per subscriber request: `repository`, `number`, `stage`, `eta` (or null), `text` | the requests file |
| `beacons` | one per open Needs-you card: `id` (the feed card id), `kind`, `text`, `taps` | the feed file |
| `unavailable` | each source that couldn't be read: `source` (`states`, `usage`, `requests` or `feed`) and `reason` | |

- **Figures.** A figure's `name` is the states file's derived name, never
  chosen: `builder-<ticket>`, `reviewer-<pr>-<round>`, `fixer-<pr>-<round>` or
  `fleet-<spec>`, matching its `role`. Its `state` is one of `queued`,
  `building`, `ci`, `review`, `fix`, `merge` or `done`. A fleet figure works a
  spec, so its `ticket` is null; every other figure names its ticket. `station`
  is the family slug of the station it stands at.
- **Meters.** `budget` is null for a lane with no target, or `spent`, `target`,
  `unit` (`percent`, `seconds`, `credits` or `dollars`), `by` and `pace` (`on
  pace`, `ahead` or `behind`), as `openwiz usage --json` reports them. An
  unreadable meter is never a window at 0.
- **Requests.** `stage` is one of `submitted`, `triaged`, `building`,
  `pull-request`, `reviewed`, `merged`, `released` or `working-on-install`.
  `eta` is an estimate from queue position and recent throughput, never a
  promise; null means there is no estimate yet.
- **Beacons.** Only needs-owner card kinds are beacons: `spec-to-approve`,
  `pr-ready-to-merge`, `decision-request`, `grant-request`, `setting-proposal`,
  `key-needed` and `release`. Scroll-only cards are not in the room.
- **Unavailable, never empty in place.** Each section is null exactly when its
  source (the pin's `sources`) is listed in `unavailable` with its reason. A
  readable source with nothing in it is an empty list; an unreadable one is
  never an empty list, a zero or a default state.
- **Reader rules.** Each family has one station, every figure stands at a
  listed station, figure names are unique, a pull request sits in one lane,
  and a source is listed at most once.

## Modes

- **`owner`** carries every field above and allows controls: the taps on
  figures and beacons. It is shown only to the owner, in WizBar, T3 and on the
  owner's phone.
- **`public`** carries exactly `schema`, `mode`, `read_at` and the showcase's
  four safe numbers, `prs_merged_total`, `prs_merged_7d`, `drivers_verified`
  and `agents_running`, each a non-negative integer or null for unavailable,
  with `read_at` the showcase export's own read time. It is built only from the
  showcase data file (`openwiz.showcase.v1`). It carries no name, no id, no
  ticket or pull request number, no link and no control, and the schema
  refuses any other field. A public room draws its stations and figures as
  anonymous shapes sized by these numbers.

## Steer lines

A steer line is the one line a room control sends. The room hands it to the
board's token-guarded tap route, which sends it to the Wiz thread as an owner
message. Wiz checks it exactly as it checks a Needs-you card tap and then acts,
or says why not. The room changes nothing itself, keeps no record of a steer
and has no write route of its own. A `steer` record is that message:

| Field | Value |
| --- | --- |
| `kind` | `steer` |
| `line` | one line from the table below, byte for byte, with no trailing newline |
| `sent_as` | `owner-message` |

| Line | Offered on | Comes from |
| --- | --- | --- |
| `approve plan #<spec> fingerprint <first 12 hex>` | a `spec-to-approve` beacon, once | the inbox contract's taps |
| `merge <owner>/<repo>#<n> at <40-hex head>` | a `pr-ready-to-merge` beacon, once | the inbox contract's taps |
| `answer decision <id> <option>` | a `decision-request` beacon, one per option | the inbox contract's taps |
| `grant <comment id>` and `refuse <comment id>` | a `grant-request` beacon, one of each | the inbox contract's taps |
| `yes to setting proposal <comment id>` and `no to setting proposal <comment id>` | a `setting-proposal` beacon, one of each | the feed spec's Yes and No |
| `pause spec #<n>` | a figure, for its spec | the room |
| `prioritize #<n>` | a figure, for its ticket | the room |

A `key-needed` beacon has no tap: it carries `opens: "key-card"`, opens the
key card and never sends or holds a value. A `release` beacon has no tap; a
release still needs the owner's ship instruction. A figure offers only `pause`
and `prioritize`. Each tap is a `label` and its `line`. Ids are the decision
record's id, the option as the record names it, and GitHub's numeric comment
id. The inbox contract (`openwiz.inbox.v1`) owns the inbox lines; the room
sends them unchanged.

## Phone budget

On a phone the 3D room keeps inside the pin's `phone_budget`: at most 24
figures drawn, 120 draw calls and 150000 triangles a frame, at 30 frames per
second or more. Below the floor the room switches to its 2D view, which draws
nothing in 3D. A scene with more figures than the cap draws the cap and shows
the rest as a count at each station; the 2D view always lists every figure.
The room measures itself with `frame` records:

| Field | Value |
| --- | --- |
| `kind` | `frame` |
| `profile` | `phone` or `desktop`; the caps and floor apply to `phone` |
| `view` | `3d` or `2d` |
| `fps` | the measured frames per second |
| `figures_drawn`, `draw_calls`, `triangles` | counts for the frame; 0 in the 2D view |
| `reduced_motion` | whether the reader asked for reduced motion |
| `moving` | which movements run: `figure-idle`, `pipeline-flow`, `camera-drift`, `holo-shimmer`, `beacon-pulse`, `state-change` |

## Theme input

A `theme` record sets the room's look; the owner's persona or theme, including
one from WizMarket, supplies it. A persona changes style only, never facts,
safety rules or agent permissions.

| Field | Value |
| --- | --- |
| `kind` | `theme` |
| `look` | the look id, a slug |
| `colours` | `background`, `surface`, `text`, `accent`, `ok`, `warn` and `alert`, each `#rrggbb` |
| `materials` | `figure`, `station`, `panel` and `floor`, each `matte`, `satin`, `gloss`, `glass`, `metal`, `emissive` or `wireframe` |
| `sound` | `on`, `set_by` (`default` or `owner`) and `cues`: `beacon`, `merge` and `alert`, each a cue id slug |

Sound is off unless the owner turns it on: a theme always arrives with `on:
false` and `set_by: "default"`, and `on: true` needs `set_by: "owner"`. Cues
are short synthesized tones; a theme carries no voice. The default look,
`holo-butler`, is the pin's `default_theme`: an original translucent helper in
cool blues, not modelled on any named character.

## Accessibility

Every station, figure, pull request, meter, request and beacon carries `text`,
its one-line text equivalent, and the room's 2D view is those lines from the
same scene file, in a screen-reader-friendly list with the same controls. With
reduced motion asked for, `moving` holds at most `state-change`: an element
changing state changes in place, and every other movement stops.

## Originality

Every look, name and sound cue is original. No look, figure, name or sound
uses a trademarked name, a real person's or character's likeness, or a voice
clone. Figure names come only from records.
