# OpenWiz next-prompt contract v1 (`openwiz.next-prompt.v1`)

The empty composer can ask the local ghost engine for one likely next prompt.
This contract adds `predict` alongside the routes in [ghost v1](ghost.v1.md).
The request, successful response and acceptance record have definitions in
[next-prompt.v1.schema.json](next-prompt.v1.schema.json). Spec #4041 assigns
the predictor to #4043, the T3 composer to #4044 and the acceptance eval to #4045.

## Predict

The composer calls `POST /ghost/v1/predict` with a JSON body containing only
`surface`, or uses `route: "predict"` with that body in ghost's stdio request
envelope. The extension follows ghost v1's HTTP loopback bind, body size limit,
Host, Origin and pairing checks, and its stdio framing and refusal conventions.
Use `#/$defs/predict_request` for the body. `surface` takes the ghost v1 values
`openwiz-app`, `t3-code`, `bb-plugin`, `cli` and `other`.

Call when the composer has no draft text. The request carries the surface
alone. The engine reads the owner's locally available context from these
sources and attributes the winning prompt to its primary source.

| Source | Eligible input |
| --- | --- |
| `open_decision_request` | Open decision requests, including their recommendations when available |
| `factory_feed` | The factory's local feed files |
| `factory_states` | The factory's local states files |
| `recent_owner_ask` | The owner's recent asks in the local ghost context pack |

The engine computes the prediction on the owner's machine. Prediction may use
loopback for a local model. Context, prompts and acceptance data stay on the
machine, with no network calls beyond loopback and no telemetry.

A successful response uses `#/$defs/predict_response`. It contains
`schema: "openwiz.next-prompt.v1"` and either a single `prediction` object or
`prediction: null`. A prediction has an opaque `id` for that prediction
instance (ASCII letters, digits, underscores or hyphens), a nonblank `prompt`
string, one `source` from the table, and numeric `confidence` in `[0, 1]`. Use
ghost v1's starting cutoff of `0.30` as the minimum confidence on the wire. If
there is no eligible candidate or the best candidate falls below that cutoff,
return HTTP or stdio status 200 with
`{"schema":"openwiz.next-prompt.v1","prediction":null}`.

Display a prediction as ghost text only while the composer remains empty.
Discard a reply that no longer matches the current empty state, including a
reply superseded by a newer request. Tab inserts the visible prompt into the
draft and clears the ghost text. Sending still requires the owner's send action.
For a null response or a refused request, leave the empty composer blank. Never
use the placeholder "Ask anything" or return it as a prediction.

## Acceptance records

Prediction acceptance logging is off by default. The owner must explicitly
enable it on their machine. Check that local setting before writing each record.
While disabled, write no acceptance records and do no backfill when enabled.
The log is local JSON Lines only, with zero uploads or telemetry.
`opt_in: true` and `storage: "local"` identify eligible records. The owner's
local setting is the authority for consent.

Each line uses `#/$defs/acceptance_record`. It contains the contract version in
`schema`, `prediction_id` from the displayed prediction, its `surface`, a UTC
timestamp `at` in `YYYY-MM-DDTHH:MM:SSZ` form (validate the calendar date
and time), an `outcome`, `storage` and `opt_in`. Persist only these fields.
Keep the prompt, edited text and source material out of the log. The eval reads
only this opt-in local log and reports acceptance as unavailable when no such
log exists.

| Outcome | Record once per prediction ID |
| --- | --- |
| `shown` | When the prediction first becomes visible as ghost text |
| `accepted` | When Tab inserts that visible prediction into the draft |
| `accepted_then_edited` | When the owner first changes the accepted draft before sending or discarding it |

For one ID and surface, later outcomes require the preceding outcomes to have
been recorded in order. A re-render, an ignored reply or a blank result adds no
record. The edited outcome also counts under accepted, so the eval can count
each outcome by prediction ID without treating edits as additional accepts.

## Fixture proof

The [synthetic valid fixtures](fixtures/next-prompt/valid.json) cover the request,
each source, the blank fallback and all three outcomes. Every
[broken fixture](fixtures/next-prompt/broken.json) changes one field of a valid
fixture. Run `python3 -I contracts/fixtures/next-prompt/test_fixtures.py` with
the Python `jsonschema` validator available. These cases validate record shapes
and the confidence floor. Live source selection, UI actions, event ordering
and consent enforcement are runtime responsibilities.
