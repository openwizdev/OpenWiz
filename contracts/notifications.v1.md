# OpenWiz notifications contract v1 (`openwiz.notifications.v1`)

The preferences file is `.openwiz/notifications.v1.json` under the OpenWiz home
checkout on the user's machine. It contains one UTF-8 JSON object matching the
[preferences schema](notifications.v1.schema.json). All top-level fields are
required. Readers refuse duplicate keys, unknown fields and unknown event kinds.
Use the missing-file default only when the file is absent. An unreadable or
invalid file is an error and must suppress dispatch until it can be read and
validated.

~~~json
{
  "schema": "openwiz.notifications.v1",
  "kinds": {
    "spec-to-approve": "push",
    "quota-switch": "feed",
    "request:merged": "push",
    "context:Drop": "off"
  },
  "quiet_hours": { "start": "22:00", "end": "07:00", "time_zone": "America/Chicago" },
  "digest": "daily",
  "channels": ["synthetic-inbox"]
}
~~~

## Event kinds

`kinds` maps exact, case-sensitive keys to one choice apiece. Omitted keys
inherit **only when needed**. The schema's `eventKind` enum is the complete
allowlist. Refuse an unknown key even if its value is a valid choice.

| Source | Keys | Only-when-needed mode |
| --- | --- | --- |
| Needs-owner feed cards | `spec-to-approve`, `pr-ready-to-merge`, `release`, `key-needed`, `setting-proposal` | `push` |
| Feed blocker | `blocker` | `push` when the card has `needs_owner: true`, otherwise `feed` |
| Scroll-only feed cards | `quota-switch`, `driver-suggestion` | `feed` |
| Subscriber request stages | `request:submitted`, `request:triaged`, `request:building`, `request:pull-request`, `request:reviewed`, `request:merged`, `request:released`, `request:working-on-install` | `feed` |
| [Context-engine ledger items](context-engine.v1.md#item-ledger) | `context:Done`, `context:Ticketed`, `context:Decide`, `context:Reply`, `context:Drop` | `feed` |

An explicit `blocker` setting applies to both kinds of blocker. Use the feed's
`needs_owner` value for the default. The source kinds come from the
[feed card rules](https://github.com/openwizdev/OpenWiz/issues/3410) and the
[subscriber request stages](https://github.com/openwizdev/OpenWiz/issues/3848).

| Choice | Notification behavior |
| --- | --- |
| `push` | Show the item in the feed and make it eligible for a push, subject to quiet hours, digest and channel settings. |
| `feed` | Show the item in the feed. It never enters a push or digest. |
| `off` | Suppress the notification in the feed, single pushes and digests. The source record is untouched. |

## Quiet hours and digest

`quiet_hours: null` disables quiet hours. A window uses IANA `time_zone` and
24-hour local times `start` and `end` in `HH:MM`. Readers check that the named
zone resolves in their IANA time zone data. The schema names this check with the
`iana-time-zone` format. The window includes its start and excludes its end.
An end earlier than the start is on the next day. Equal times make an empty
window.

No push goes out during quiet hours, including a scheduled digest. Items
eligible for push stay visible in the feed while held. At the end of the window,
send one digest listing the held items, including any batch that became due
during the window. This end-of-window digest also applies with `digest: "none"`.
Subsequent scheduled digests exclude items already delivered.

Outside quiet hours, `digest: "none"` permits single pushes as events arrive.
`hourly` and `daily` collect eligible events and send one push listing the
batch at the next hour or day boundary. Use the quiet-hours zone when set,
otherwise the machine's local zone. An empty batch sends nothing. The feed's
one-push-per-card rule also applies to digests. A queued card reaches the ping
ledger only when its push goes out.

## Channels and missing-file default

`channels` lists the unique Settings channel IDs the user nominates for
additional delivery. T3 is the built-in push channel. Use exact IDs from
Settings in `channels`, with `t3` reserved for the built-in route.

A channel beyond T3 is never used unless that channel is on in Settings.
Check Settings at dispatch time for every single push or digest. An absent,
unknown, off or unreadable Settings entry leaves that channel unavailable.
A channel must also be nominated in this file. An empty list selects no
additional channels.

A missing file uses **only when needed**. Needs-owner feed cards are eligible
for push and all other events appear in the feed. There are no quiet hours,
no digest and no extra channels. The schema's `onlyWhenNeeded` definition
records this effective profile for consumers and the
[synthetic fixtures](fixtures/notifications/README.md).
