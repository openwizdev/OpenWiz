# Room fixtures

All examples are invented: the families, agents, numbers, repositories, looks
and sound cues are synthetic. Run the offline proof from the repository root
with `python3 -I contracts/fixtures/room/test_fixtures.py`.

`valid.json` names complete records, each valid against
`contracts/room.v1.schema.json`:

| Valid record | Shows |
| --- | --- |
| `owner-scene` | Every owner field read: stations, figures with their taps, the three pipeline lanes, meters with and without a budget, requests, one beacon of each needs-owner kind with its tap lines. |
| `owner-scene-unavailable` | Unreadable sources as null sections listed in `unavailable`, beside a readable empty requests list. |
| `public-scene` | The public mode: the four safe numbers and their read time, nothing else. |
| `public-scene-unavailable` | Unreadable safe numbers as null, never zero; a real zero stays zero. |
| `steer-approve`, `steer-merge`, `steer-answer`, `steer-grant`, `steer-refuse`, `steer-yes`, `steer-no` | Each inbox tap line, sent as an owner message. |
| `steer-pause`, `steer-prioritize` | The room's two own steer lines. |
| `frame-phone-3d` | A phone frame exactly at every cap and above the floor. |
| `frame-phone-2d` | A phone below the floor, in the 2D view. |
| `frame-desktop-reduced` | Reduced motion with only essential movement. |
| `theme-default` | The default `holo-butler` look, sound off. |
| `theme-sound-on` | Another original look, sound turned on by the owner. |

Each `broken.json` row changes one field of its named valid record, and the
schema refuses the result. A row with no `value` removes the field. Paths are
arrays of property names or zero-based array indices. `Covers` names the
field, mode, steer line, budget rule, theme field or accessibility rule the
row breaks; the proof fails if any of them has no row.

| Case | Valid record | Covers | Rule |
| --- | --- | --- | --- |
| scene-schema | `owner-scene` | scene.schema | A scene names `openwiz.room.v1`. |
| scene-read-at | `owner-scene` | scene.read_at | `read_at` is a UTC time. |
| scene-mode | `owner-scene` | scene.mode | The mode is `owner` or `public`. |
| scene-extra | `owner-scene` | scene.closed | An owner scene has no field beyond the contract's. |
| stations-missing | `owner-scene` | scene.stations | An owner scene carries `stations`. |
| station-family | `owner-scene` | station.family | A station's family is a lowercase slug. |
| station-text | `owner-scene` | access.text | A station has a text equivalent. |
| figures-object | `owner-scene` | scene.figures | `figures` is a list. |
| figure-name | `owner-scene` | figure.name | A figure's name is derived from records, never chosen. |
| figure-name-role | `owner-scene` | figure.name | A figure's name matches its role. |
| figure-role | `owner-scene` | figure.role | A figure's role is builder, reviewer, fixer or fleet. |
| figure-state | `owner-scene` | figure.state | A figure's state is one of the states file's agent states. |
| figure-ticket | `owner-scene` | figure.ticket | A builder, reviewer or fixer names its ticket. |
| fleet-ticket | `owner-scene` | figure.ticket | A fleet figure works a spec and names no ticket. |
| figure-station | `owner-scene` | figure.station | A figure stands at a station. |
| figure-text | `owner-scene` | access.text | A figure has a text equivalent. |
| figure-tap | `owner-scene` | figure.taps | A figure's tap is a steer line. |
| figure-merge-tap | `owner-scene` | figure.taps | A figure offers only pause and prioritize; merges come from beacons. |
| pipeline-lane | `owner-scene` | scene.pipeline | The pipeline has exactly the build, review and merge lanes. |
| pipeline-build | `owner-scene` | pipeline.build | The build lane is present. |
| pipeline-review | `owner-scene` | pipeline.review | A pull request number is positive. |
| pipeline-merge | `owner-scene` | pipeline.merge | A pull request names its `owner/repo`. |
| meters-string | `owner-scene` | scene.meters | `meters` is a list. |
| meter-used | `owner-scene` | meter.used_percent | A window's used share is 0 to 100. |
| meter-target | `owner-scene` | meter.budget | A budget carries spend and target. |
| meter-pace | `owner-scene` | meter.pace | Pace is on pace, ahead or behind. |
| requests-missing | `owner-scene` | scene.requests | An owner scene carries `requests`. |
| request-stage | `owner-scene` | request.stage | A request's stage is one of the tracker's stages. |
| request-eta | `owner-scene` | request.eta | An ETA is a UTC time or null. |
| beacons-object | `owner-scene` | scene.beacons | `beacons` is a list. |
| beacon-id | `owner-scene` | beacon.id | A beacon carries its feed card id. |
| beacon-kind | `owner-scene` | beacon.kind | A beacon is a needs-owner kind; scroll-only kinds are not beacons. |
| beacon-wrong-tap | `owner-scene` | beacon.taps | A beacon offers only its own kind's tap line. |
| beacon-grant-only | `owner-scene` | beacon.taps | A grant request offers exactly one grant and one refuse. |
| beacon-key-value | `owner-scene` | beacon.key-needed | A key-needed beacon opens the key card and carries no value. |
| beacon-release-tap | `owner-scene` | beacon.release | A release beacon has no tap. |
| beacon-text | `owner-scene` | access.text | A text equivalent is one line. |
| unavailable-missing | `owner-scene` | scene.unavailable | An owner scene carries `unavailable`. |
| empty-in-place | `owner-scene-unavailable` | unavailable.never-empty | An unreadable source's section is null, never an empty list. |
| null-unlisted | `owner-scene` | unavailable.never-empty | A null section's source is listed in `unavailable`. |
| listed-but-read | `owner-scene` | unavailable.source | A source listed in `unavailable` has a null section. |
| unavailable-source | `owner-scene-unavailable` | unavailable.source | An unavailable source is states, usage, requests or feed. |
| unavailable-reason | `owner-scene-unavailable` | unavailable.reason | An unavailable source carries its reason. |
| owner-as-public | `owner-scene` | mode.owner | A public scene carries no owner field. |
| public-as-owner | `public-scene` | mode.public | An owner scene carries every owner field. |
| public-schema | `public-scene` | public.schema | A public scene names `openwiz.room.v1`. |
| public-mode | `public-scene` | public.mode | A public scene's mode is `public`. |
| public-read-at | `public-scene` | public.read_at | A public scene carries the numbers' read time. |
| public-total | `public-scene` | public.prs_merged_total | A safe number is a non-negative integer or null. |
| public-week | `public-scene` | public.prs_merged_7d | A safe number is an integer. |
| public-drivers | `public-scene` | public.drivers_verified | A safe number is never a string. |
| public-agents | `public-scene` | public.agents_running | A public scene carries all four safe numbers. |
| public-figures | `public-scene` | public.no-names | A public scene carries no names. |
| public-agent-name | `public-scene` | public.no-names | A public scene carries no agent name. |
| public-beacon-id | `public-scene` | public.no-ids | A public scene carries no ids. |
| public-ticket | `public-scene` | public.no-ids | A public scene carries no ticket number. |
| public-taps | `public-scene` | public.no-controls | A public scene carries no controls. |
| public-steer | `public-scene` | public.no-controls | A public scene carries no steer line. |
| steer-approve-fingerprint | `steer-approve` | steer.approve | An approve line names 12 hex of the plan fingerprint. |
| steer-merge-short-head | `steer-merge` | steer.merge | A merge line names the full 40-hex head. |
| steer-answer-no-option | `steer-answer` | steer.answer | An answer line names its option. |
| steer-grant-name | `steer-grant` | steer.grant | A grant line names a comment id. |
| steer-refuse-extra | `steer-refuse` | steer.refuse | A refuse line is exactly the line. |
| steer-yes-short | `steer-yes` | steer.yes | A yes line names the setting proposal. |
| steer-no-id | `steer-no` | steer.no | A no line names the proposal's comment id. |
| steer-pause-agent | `steer-pause` | steer.pause | Pause names a spec, never an agent. |
| steer-prioritize-bare | `steer-prioritize` | steer.prioritize | Prioritize names `#<n>`. |
| steer-two-lines | `steer-pause` | steer.one-line | A steer is one line. |
| steer-trailing-newline | `steer-pause` | steer.one-line | A steer line has no trailing newline. |
| steer-unknown | `steer-pause` | steer.one-line | Only the contract's lines are steer lines. |
| steer-sent-as | `steer-pause` | steer.owner-message | A steer is sent to Wiz as an owner message. |
| steer-applied | `steer-pause` | steer.changes-nothing | A steer records nothing the room did itself. |
| budget-figures | `frame-phone-3d` | budget.figures | A phone 3D frame draws at most 24 figures. |
| budget-draw-calls | `frame-phone-3d` | budget.draw-calls | A phone 3D frame makes at most 120 draw calls. |
| budget-triangles | `frame-phone-3d` | budget.triangles | A phone 3D frame draws at most 150000 triangles. |
| budget-fps-floor | `frame-phone-3d` | budget.fps-floor | A phone 3D frame runs at 30 frames per second or more. |
| budget-no-fallback | `frame-phone-2d` | budget.fallback | Below the floor the phone shows the 2D view. |
| budget-2d-draws | `frame-phone-2d` | budget.fallback | The 2D view draws nothing in 3D. |
| frame-profile | `frame-phone-3d` | frame.profile | A frame's profile is phone or desktop. |
| reduced-motion-drift | `frame-desktop-reduced` | access.reduced-motion | Reduced motion keeps only essential movement. |
| theme-schema | `theme-default` | theme.schema | A theme names `openwiz.room.v1`. |
| theme-kind | `theme-default` | theme.kind | A theme input's kind is `theme`. |
| theme-look | `theme-default` | theme.look | A look id is a lowercase slug. |
| theme-colour | `theme-default` | theme.colours | A colour is `#rrggbb`. |
| theme-colour-missing | `theme-default` | theme.colours | A theme carries every colour role. |
| theme-material | `theme-default` | theme.materials | A material is one of the contract's materials. |
| theme-sound-default-on | `theme-default` | theme.sound | Sound is off unless the owner turned it on. |
| theme-sound-cue | `theme-sound-on` | theme.sound | A sound cue id is a lowercase slug. |
| theme-sound-voice | `theme-sound-on` | theme.sound | A theme carries cues only, never a voice. |
