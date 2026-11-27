# A fake key-host driver that starts a run before refusing effort

Login: held by Devin
Effort: passed as the `effort` field of the start request, by harness:

| Harness | Effort |
| --- | --- |
| `claude` | the `effort` field of the start request |
| `fake-harness` | can't (synthetic) |

The kit's own fixture: the key-host fixture, sending its start request to the host before it refuses the effort with the refusal text.

The key is your `DEVIN_API_KEY`, or the keychain entry `openwiz-devin`; the driver never sees it.
