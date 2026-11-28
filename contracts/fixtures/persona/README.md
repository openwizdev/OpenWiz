# Persona fixtures

All personas, themes, names and voices here are invented for the tests. Run
the offline proof from the repository root with
`python3 -I contracts/fixtures/persona/test_fixtures.py`.

`valid.json` holds one valid record per rule of
[`persona.v1.md`](../../persona.v1.md), keyed by the rule's name. Each
`broken.json` row changes one field of its named valid record. A row with no
`value` removes the field. Paths are arrays of property names. The schema
accepts every valid record and refuses every broken one.

| Case | Valid record | Rule |
| --- | --- | --- |
| missing-greeting | `persona` | Every persona field is present. |
| unknown-family | `persona` | The family is one of the four. |
| two-line-vibe | `persona` | The vibe is one line. |
| unknown-schema | `persona` | The record names `openwiz.persona.v1`. |
| missing-dark | `theme` | A theme has light and dark colours. |
| bad-colour | `theme` | A colour token is a hex colour. |
| extra-token | `theme` | A theme has the named colour tokens only. |
| sounds-on | `theme` | Sound cues are off until the user turns them on. |
| recorded-audio | `theme` | A sound cue is synthesis parameters, never recorded audio. |
| loud-cue | `theme` | A sound cue is subtle. |
| long-cue | `theme` | A sound cue is short. |
| missing-room | `theme` | A theme has the `room` object. |
| room-sentence-mood | `theme` | Room mood is single words. |
| rules-field | `style-only` | A persona can't carry rules. |
| permissions-field | `style-only` | A persona can't carry permissions. |
| tools-field | `style-only` | A persona can't carry tools. |
| facts-field | `style-only` | A persona can't carry facts. |
| speech-extra-field | `style-only` | Nested objects refuse unnamed fields too. |
| frame-drops-next | `facts` | A frame keeps the next-command line. |
| frame-inlines-facts | `facts` | The facts block stands on its own lines. |
| frame-next-first | `facts` | The facts block comes before the next command. |
| error-drops-facts | `facts` | An error keeps its facts block. |
| frame-twice | `facts` | Each slot appears once. |
| json-face | `two-faces` | A persona applies to human text, never JSON. |
| records-face | `two-faces` | A persona never applies to records. |
| json-output-field | `two-faces` | A persona can't restyle JSON output. |
| cloned-voice | `originality` | The voice is original, never a clone. |
| cloud-voice | `originality` | The voice runs on the local engine. |
| voice-sample | `originality` | A persona carries no voice sample. |
| likeness-field | `originality` | A persona carries no likeness. |
