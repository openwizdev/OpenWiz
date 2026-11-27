# A fake key-host driver that passes effort

Login: held by Devin
Effort: passed as the `effort` field of the start request

The kit's own fixture: the key-host fixture, with effort in `can`, passing effort to the harness but dropping it from its start request.

The key is your `DEVIN_API_KEY`, or the keychain entry `openwiz-devin`; the driver never sees it.
