# A fake key-host driver with a misplaced effort field

Login: held by Devin
Effort: passed as the `effort` field of the start request

This planted driver omits effort from run creation. It sends the field on
cleanup by default. The kit tests can move the field to a cleanup POST or to
a second request made during start.

The key is your `DEVIN_API_KEY`, or the keychain entry `openwiz-devin`.
