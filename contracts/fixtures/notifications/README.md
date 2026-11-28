# Notifications v1 fixtures

Every row names a `valid` and a `broken` JSON instance in [cases.json](cases.json).
The inputs are synthetic. Each broken instance must fail at the specified JSON
path for the specified schema keyword.

| Pair | Valid instance | Broken instance |
| --- | --- | --- |
| `version` | Exact v1 discriminator | Unrecognised version |
| `complete-file` | Complete preferences file | Missing kind map |
| `extra-field` | Only declared fields | Unknown top-level field |
| `modes` | Push, feed and off on different kinds | Unknown mode |
| `needs-owner-kinds` | All five always-needs-owner feed kinds | Invented feed kind |
| `scroll-only-kinds` | Blocker and both always-scroll-only kinds | Invented scroll-only kind |
| `request-stages` | All eight request stages | Invented request stage |
| `context-items` | All five context-engine item states | Invented context item state |
| `quiet-hours` | Overnight quiet window holds push candidates for the feed and one end-of-window digest | Window supplied as a string |
| `quiet-hours-clock` | Start and end use the local 24-hour clock | End is out of range |
| `quiet-hours-time-zone` | Window includes a time zone | Missing time zone |
| `quiet-hours-iana` | Recognised IANA time zone | Invented time zone |
| `digest-none` | Immediate push outside quiet hours | Boolean digest setting |
| `digest-hourly` | One push listing the hour's queued events | Unsupported cadence |
| `digest-daily` | One push listing the day's queued events | Incorrectly cased cadence |
| `channels` | A nominated extra channel still needs its Settings switch on | T3 supplied as an extra channel |
| `channels-unique` | Each extra channel is nominated once | Repeated nomination |
| `default-needs-owner` | Missing file defaults needs-owner cards to push | Needs-owner cards default to feed |
| `default-other` | Missing file defaults all other events to feed | Other events default to push |
| `default-quiet-hours` | Missing file leaves quiet hours unset | Quiet hours enabled by default |
| `default-digest` | Missing file leaves the digest off | Digest enabled by default |
| `default-channels` | Missing file nominates no extra channels | Extra channel nominated by default |

The default pairs validate against the schema's `onlyWhenNeeded` definition.
That definition describes the effective profile for a missing file. The other
pairs validate against the file schema at its root. Descriptions of delivery
in the table give the expected effect for the ping skill's tests.

Replay N1 with Python 3.11+, `jsonschema` with Draft 2020-12 support, and system
IANA time zone data. Run from the repository root.

~~~sh
python3 -I contracts/fixtures/notifications/test_fixtures.py
~~~
