# openwizdev/OpenWiz#88: the App setup page's button

Headless Chromium rendered `tools/github-app/setup.py`'s start page, served by the tool itself under its own
Content-Security-Policy, for a synthetic `synthetic-owner/synthetic-repo` state. The form was never submitted.
The button was measured on the same markup with a measuring script added, because the live page's policy refuses scripts.

| Render | Width | Button (CSS px) |
| --- | --- | --- |
| [before-390.png](before-390.png) (main) | 390 | 187.9 x 21 |
| [before-1280.png](before-1280.png) (main) | 1280 | 187.9 x 21 |
| [after-390.png](after-390.png) | 390 | 242.4 x 44 |
| [after-1280.png](after-1280.png) | 1280 | 242.4 x 44 |

After: `<html lang="en">`, a `width=device-width, initial-scale=1` viewport, and a nonce'd style giving the
button a minimum 44 x 44 px target. The label, `type="submit"`, manifest field and form action are unchanged.
