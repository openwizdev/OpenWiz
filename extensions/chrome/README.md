<img alt="" src="icons/mark.svg" width="72">

# OpenWiz for Chrome 🧙‍♂️🪄

Chat with a local OpenWiz agent in Chrome's side panel. Ask about the page you are on, or let the agent read, click, type and navigate in a tab after you allow it.

The panel talks only to a bridge on `127.0.0.1`. OpenWiz does not run a hosted chat service for this, and the bridge does not call `room-cli`. CloudRoom threads stay where they are: `openwiz` reaches them through the CloudRoom adapter, which is a separate, live path. This extension does not use it.

## What the agent is

Two ways to reach an agent exist today.

- **Page**, built into the bridge. It answers from the page the panel attaches: address, title, selection and readable text. It can propose a click, typing, a read or opening an `http` or `https` link. It does not perform that action. The panel does, and only after a grant.
- **Command**, optional. Pass one program when you start the bridge. Each turn is one JSON object on its stdin and one JSON object on its stdout, the same shape as a single local-driver turn. The bridge drops any action that is not read, click, type or navigate, and it never runs the action itself. A signed-in harness such as `claude` or `codex` is not started for you.

## Install

You need Python 3.9 or later and Chrome 116 or later. From the repository root:

```sh
python3 -I extensions/chrome/bridge/bridge.py serve
```

The process prints one JSON line with `port` (17418 unless you pass `--port`) and `token`. Leave it running. The token is also stored mode 600 under the state directory (`--state-dir`, or `$OPENWIZ_CHROME_STATE`, or `$XDG_STATE_HOME/openwiz-chrome`, or `~/.local/state/openwiz-chrome`). `bridge.py token` prints it again. `bridge.py token --rotate` replaces it.

Load the extension unpacked:

1. Open `chrome://extensions`.
2. Turn on Developer mode.
3. Choose **Load unpacked** and select this folder, `extensions/chrome`.
4. Click the OpenWiz icon. The side panel opens. The shortcut suggestion is Ctrl+Shift+Y (Command+Shift+Y on macOS); Chrome may ask you to confirm it.
5. Paste the token and choose Connect.

To try tab actions, open [http://127.0.0.1:17418/demo](http://127.0.0.1:17418/demo) while the bridge is running. The bridge serves that page. It is a fixture, not a product site.

A command agent, if you want one:

```sh
python3 -I extensions/chrome/bridge/bridge.py serve \
  --agent-command /absolute/path/to/program --agent-arg one-argument
```

The program must be a file. The bridge does not use a shell. Stdin is `{"schema":"openwiz.chrome.v1","session_id","text","page","history"}`. Stdout is `{"text","actions"}`. `actions` is optional. Each action has `op` of `read`, `click`, `type` or `navigate`, plus `description` and, where they apply, `selector`, `text`, `url` or `value`. At most three actions are kept. `navigate` must be `http` or `https`.

## Use

**Ask about the page.** Leave **Include this page** on. The panel sends the address, title, selection and readable text with your message. Try "What is the title of this page?" or "What does this page say about lanterns?" on the demo page.

**Let it act.** Ask "Click Demo" or "Type a note". The reply names the action and does not run it. Choose **Allow this tab** or **Allow this session**, or **Allow this tab and run** on the action.

- **This tab** lasts until you revoke it or the tab closes.
- **This session** covers every open tab until you revoke it or you quit Chrome. The first time the agent acts on a new site, Chrome may ask you to allow that site. The bridge's own host, `127.0.0.1`, is already allowed so the panel can reach the bridge.

While the action runs, the toolbar badge says **ACT**, the panel says the agent is acting, and the page shows a banner, **OpenWiz agent is acting in this tab**, with **Revoke**. Revoke on the banner drops the permission that allowed the action. Revoke in the panel lists every grant. A grant that is gone cannot start the next action.

**Allow this site in Chrome** appears when the panel could not reach the tab. That is Chrome's own site permission, separate from the OpenWiz grant. Both are required before an action runs on a site the extension cannot already see.

## Permissions

| Permission | Why it is there |
| --- | --- |
| `sidePanel` | The chat is the side panel. |
| `storage` | The pairing token and the include-page choice stay in the browser. Grants live in session storage and clear when Chrome quits. |
| `scripting` | Read the page you asked about, and run an action after a grant. The content script is injected for that tab, not registered for every site. |
| `tabs` | Know which tab is active so a grant is attached to it. |
| `activeTab` | Read the current tab after you open the panel, without a standing host permission. |
| `http://127.0.0.1/*` | Talk to the bridge, and act on the local demo page. |
| optional `http://*/*` and `https://*/*` | Requested only when you allow a tab or a site, and only for that origin. They are not granted at install. |

The manifest has no `content_scripts` entry, no `debugger`, and no `<all_urls>` permission.

## Bridge

`POST` only, `Content-Type: application/json`, body at most 1 MiB, on `127.0.0.1`.

| Route | Body | Reply |
| --- | --- | --- |
| `/chrome/v1/health` | `{}` | `status`, `version`, `agents` |
| `/chrome/v1/agents` | `{}` | `agents`: `page`, and `command` when configured |
| `/chrome/v1/chat` | `session_id`, `agent`, `text`, optional `page` | `text` and `actions` |

`page` is `{url, title, selection, text}`. Every route except `GET /demo` needs `Authorization: Bearer <token>`. `Host` must be loopback. A browser `Origin` must be a Chrome extension origin or `http://127.0.0.1` or `http://localhost` on this port. Anything else is refused. Refusals are `{"refusal":{"code","message"}}`.

## Tests

```sh
python3 -I extensions/chrome/bridge/test_bridge.py
node --test extensions/chrome/policy.test.mjs
```

CI runs both. They use loopback and a fake command. They do not call CloudRoom, `room-cli`, or a model.

## Not in this version

- Chrome Web Store packaging, a developer account, a privacy-policy URL, and the store listing. To publish later, zip this folder, justify the optional host permissions in the listing, and point the listing at a privacy policy that says page text is sent to the local bridge and, if you configured one, to your command agent.
- CloudRoom `thread tell`. That is a live `room-cli` call through the adapter allowlist, and this bridge does not make it.
- Starting `claude`, `codex`, or any other signed-in harness on its own. Set `--agent-command` when you want that turn.
- The bundled page agent is not a frontier model. It answers from the page context you attach and proposes at most one tab action.
