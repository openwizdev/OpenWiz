# OpenWiz voice prompter v1

## Hold, talk, release

Voice is off in a new settings file. When the owner turns it on, holding the
talk key starts one capture and releasing it ends the capture. Transcribe
that capture once, make the four decisions below, then deliver the resulting
text. Use the focused composer at release by default. This can be Wiz chat in
T3 or an agent's composer. An explicit, uniquely named route selects that
target instead. If the target is missing, ambiguous or changed before
delivery, refuse the delivery.

Typing inserts text in the target composer without submitting it. A command
goes to the local Wiz thread through `t3 thread send`. The named route for a
command must resolve to Wiz. A route to an unrelated thread or agent is
refused. Voice is the owner's input. Agents continue to use GitHub records
for their own messages.

## Decisions

Each answer is one JSON object matching
[`voice.v1.schema.json`](voice.v1.schema.json), with each field occurring once.
The discriminator is `kind`. Each decision has a closed set of `value` values
and a numeric `confidence` from 0 to 1.

| Kind | Values and fields | Exact rule |
| --- | --- | --- |
| `command_or_text` | `command`, `text` | After trimming surrounding whitespace, the fixed prefix `Wiz, ` with text after it makes a command. Otherwise type the text. |
| `route` | `focused`, `thread`, `agent`. Named values carry the exact `name`. | Match the `to <name>: ` prefix against local names exactly. One match selects that target. With no match use `focused` as the fallback answer. Refuse delivery if an explicit address is unresolved. |
| `term_fix` | `keep`, `replace`. A replacement carries `heard` and `term`. | Replace a whole word or phrase only when its exact locally known form maps to one different term. Otherwise keep it. |
| `respeak` | `replace_last`, `append`. | Append. |

Match an address after the wake prefix, if present. Remove control prefixes
from the content delivered. Preserve ordinary text, including a wake phrase
that appears in the middle of an utterance. A `replace_last` affects only
the previous unsent phrase in the same composer when that phrase is still
there. Otherwise append. A sent command stays sent.

Jev answers only when the owner turns it on. Use the exact rule with Jev
off, or if its answer is unavailable, malformed, for another kind, or below
that decision's floor. At the floor the answer is eligible. Exact answers use
confidence 1. A model answer still needs a current target. A Jev replacement
must match the heard text and use a term in the local project glossary or
learned words. An explicit valid address takes priority over a model guess.

## Decision and transfer policy

```json
{
  "defaults": {"voice": {"enabled": false, "model": "local", "jev": false}, "telemetry": false},
  "wake_phrase": "Wiz, ",
  "confidence_floors": {"command_or_text": 0.90, "route": 0.90, "term_fix": 0.80, "respeak": 0.90},
  "network": {"speech": ["audio", "transcript"], "jev": ["decision_text"], "telemetry": ["event"]}
}
```

The policy gives semantic defaults. The `voice` settings row exposes on or
off, the speech `model` (`local` or `cloud:<provider>`), and `jev` on or off.
The settings ticket defines the file representation and checks the selected
provider. [Settings row #3698](https://github.com/openwizdev/OpenWiz/issues/3698).

By default the prompter sends nothing off the machine. With voice on and a
local model, transcription runs offline. Audio or the speech transcript may
go only to the selected speech provider, and only while the owner has
explicitly selected its cloud model. Recheck the selection before sending.
An unavailable provider cannot fall back to a different cloud provider.

Jev has its own opt-in, even with local speech. Tell the owner once when they
turn it on that decision text can go to Jev. Send only the minimum text needed
for that decision. The Jev request excludes audio, the full transcript, the
glossary, learned words and the target inventory. If the decision would
require sending those inputs, use the exact rule locally. The settings
file's separate `telemetry` toggle alone authorizes voice telemetry events.
These events carry no speech, transcripts, decision text or learned words.

Code names, project terms from `GLOSSARY.md`, and the owner's past fixes stay
on the machine. Use them in the relevant project context. The voice
interface receives text from the speech app over its local interface and
stores only learned words. The prompt deliberately handed to the composer
or local Wiz thread is distinct from speech-provider, Jev and telemetry
traffic. [Local interface #3699](https://github.com/openwizdev/OpenWiz/issues/3699).

## Fixture proof

Run `python3 -I contracts/fixtures/voice/test_fixtures.py`. The synthetic
fixtures check the answer shapes and a reference evaluation of the exact
rules, confidence floors and transfer policy. They exercise no real voice
app, account, provider or network connection.
