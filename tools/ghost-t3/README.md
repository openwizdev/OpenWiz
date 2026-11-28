# Ghost text in T3 Code

T3 Code's composer is a Tiptap editor (`data-testid="composer-editor"`). Jake Parker, 2026-11-24: ship a sidecar rather than an upstream pull request, because T3 Code closes unrequested feature hooks ([lead ruling](https://github.com/openwizdev/OpenWiz/issues/3154#issuecomment-7143278142)).

The sidecar draws the gray suffix in an open shadow root at the caret. Tab accepts the rest, Right arrow (or Ctrl/Option+Right, or a tap) accepts the next word and its trailing space, Esc dismisses it until the next word, and a long-press accepts the rest. Accepted text goes in through `document.execCommand("insertText")`, the editor's own input path. Calls are `complete` and `feedback` on `127.0.0.1` only, with redirects refused, as [ghost.v1](../../contracts/ghost.v1.md) describes.

Ticket #3150 (the engine) is still open and has no branch. This build speaks the contract. The tests answer with the golden recall fixtures.

## Desktop

Start the engine, start Chrome with a remote debugging port, and put the pairing token in a one-line file:

```sh
python3 -I tools/ghost-t3/inject.py --debug-port 9222 --engine-port 17417 --token-file token.txt --target-url http://127.0.0.1:3773
```

The injector attaches only to page targets matching `--target-url`, runs the sidecar and binding in an isolated execution world, reinstalls automatically on reload, and sends the token with no Origin header and redirects disabled. Page scripts cannot see the token or the bridge.

## Web

Load this folder as an unpacked extension. Save the token and port on its options page. The background service worker registers a session-scoped `declarativeNetRequest` rule restricted to its own extension initiator and background context (`tabIds: [-1]`) for the configured loopback `complete` and `feedback` routes, removing its `Origin` header while leaving web page `Origin` headers untouched so foreign pages stay refused.

## Proof

```sh
python3 -I tools/ghost-t3/test_sidecar.py
```

Chrome drives a page whose composer element has T3 Code's attributes, replays `contracts/fixtures/ghost/recall-cases.json`, verifies the desktop injector's isolated world, target restriction, and reload handling, and exercises the unpacked web extension against the engine's refusal rules. The run does not boot the T3 Code application.
