# A driver whose start runs a short-lived child

Login: held by Devin
Effort: passed as the `effort` field of the start request

The kit's own fixture: a key host that sends the start's effort in its start request. Its main start runs a child holding a credential on its command line, which exits before start answers.

The key is your `DEVIN_API_KEY`, or the keychain entry `openwiz-devin`; the driver never sees it.
