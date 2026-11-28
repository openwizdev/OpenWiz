# Always-on bot API checks

The [driver roster](roster.md) lists each public bot platform OpenWiz documents.
A bot passes the [API check](api-check.md) when its documented interface can
start, wake and stop one agent on one ticket under [driver v1](../../kernel/driver.v1.md).
These checks use vendor documentation.

## Grok Bot

OpenWiz documents how to [use its skills inside Grok Bot](../grok-bot.md).

```text
openwiz:api-check v1
result: later: no documented programmable stop for one ticket's agent run
start: POST to a configured routine webhook URL with its authentication header and an optional JSON body. HTTP 200 confirms a run started. The guide does not specify a ticket-scoped run ID in the response — https://docs.x.ai/grok-bot/skills-routines-and-automations#webhooks (read 2026-11-28)
wake: The app keeps the Bot conversation. Pausing or resuming a routine changes its schedule, and the guide documents no call to resume the same agent by run ID — https://docs.x.ai/grok-bot/skills-routines-and-automations#manage-routines (read 2026-11-28)
stop: The enterprise Organization API terminates a member’s shared cloud computer and affects all work on it. The vendor documents no programmable stop for a single ticket’s run — https://docs.x.ai/grok-bot/computers#run-operations-through-the-api (read 2026-11-28)
running: The app’s routine history shows Running, Succeeded or Failed. The guide documents no callable status lookup for one run — https://docs.x.ai/grok-bot/skills-routines-and-automations#manage-routines (read 2026-11-28)
cost: Each routine run spends usage. Pausing unused routines prevents future runs and usage. The guide describes usage limits and optional on-demand spend, with no per-run machine billing control — https://docs.x.ai/grok-bot/skills-routines-and-automations#routines-and-usage (read 2026-11-28)
login: The user signs into the app in their browser and can link an eligible subscription. The vendor documents no signed-in CLI for the driver lifecycle — https://docs.x.ai/grok-bot/get-started#2-sign-in (read 2026-11-28)
```
