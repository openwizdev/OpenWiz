# e2e for live checks and review evidence

Source review for [OpenWiz #3705](https://github.com/openwizdev/OpenWiz/issues/3705) under the [0.2.0 research spec](https://github.com/openwizdev/OpenWiz/issues/3703), 2026-11-28. This review used public documentation and source. It ran no e2e test, installed no package, signed up for no service, used no secret, and made no model call or upstream write.

## Identity, licence and maintenance

e2e is the TypeScript test runner from TesterArmy, now published under the GitHub owner `e2e-inc`. TesterArmy's launch post links the former `tester-army/e2e` address, which redirects to [`e2e-inc/e2e`](https://github.com/e2e-inc/e2e), and describes the same mix of UI agent steps and exact assertions, with existing model subscriptions. [Launch post](https://dev.to/testerarmy/introducing-e2e-open-source-agentic-testing-for-web-ios-and-android-4flb) · [Former repository address](https://github.com/tester-army/e2e)

The earliest stable runner package I could verify is `e2e@0.15.0`, published to npm on 2026-09-30. The earlier `0.1.0` entry says “Coming soon.” and has no repository metadata. The repository's first published GitHub release is `e2e@0.15.1` on 2026-10-01. [npm publication timestamps](https://registry.npmjs.org/e2e) · [0.15.0 package metadata](https://registry.npmjs.org/e2e/0.15.0) · [0.1.0 package metadata](https://registry.npmjs.org/e2e/0.1.0) · [First GitHub release](https://github.com/e2e-inc/e2e/releases/tag/e2e%400.15.1)

This evaluation reads `e2e@0.25.0` at commit [`1642ef238634d1269650b8aa5df2fa0a91086e4b`](https://github.com/e2e-inc/e2e/commit/1642ef238634d1269650b8aa5df2fa0a91086e4b). The licence file is Apache License, Version 2.0, SPDX `Apache-2.0`, which meets the research spec's permissive-licence rule. [Pinned licence](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/LICENSE) · [Research licence rule](https://github.com/openwizdev/OpenWiz/issues/3703)

The November 25 runner release and November 27 mainline desktop work show recent maintenance. The project is pre-1.0 and its security policy supports only the latest published `0.x` minor of each package. The policy names a private reporting route and response targets. Future release cadence and compatibility across minor versions are unverified. [0.25.0 release](https://github.com/e2e-inc/e2e/releases/tag/e2e%400.25.0) · [November 27 desktop work](https://github.com/e2e-inc/e2e/pull/2403) · [Pinned security policy](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/SECURITY.md)

## Live checks and review evidence

The web engine uses Playwright and supports per-target viewport sizes. The runner can mix `agent.act` navigation with locator assertions that check exact UI outcomes. Its JSON report includes step labels and statuses, and the local HTML report shows attempts, steps, screenshots and failures. To get images for passing checkpoints, request a named `app.screenshot()` at each checkpoint. For a failure the runner attempts a screenshot when the engine supports it. [Pinned quickstart](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/quickstart.mdx) · [Web targets](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/web.mdx) · [Report fields and capture modes](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/debugging.mdx) · [HTML step status source](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/packages/html-reporter/app/test.tsx)

One proposed check covers the browser portion of the openwiz.dev live check, #3523. Run against a preview of the exact PR head with a public synthetic listing and 390 px and 1440 px viewport targets. The steps below are a test design with example expectations. [Live-check ticket #3523](https://github.com/openwizdev/OpenWiz/issues/3523) · [Web targets](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/web.mdx) · [Pinned quickstart](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/quickstart.mdx)

| Checkpoint | Evidence of a pass |
| --- | --- |
| Search and filter | Ask the agent to find the fixture via search and the status filter. Assert the selected filter and expected result card with locators. Save `filtered-results`. |
| Open the listing | Open that card. Assert the fixture's exact heading, status and reason. Save `listing-status`. |

A reviewer would get the head SHA, preview or fixture version, viewport, expected result, actual step status and image for each checkpoint. Keep the JSON and screenshot files together, or use the local HTML report with embedded images. On a planted wrong reason, the second assertion should fail and the report should identify it. An unexecuted checkpoint or a missing screenshot is incomplete evidence. A provider or browser startup error is a run error. Review images before sharing because screenshot masking covers secure fields only. [Reporters](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/reference/reporters.mdx) · [Exit codes and artifacts](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/debugging.mdx) · [Screenshot handling](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/reference/security.mdx#screenshots-after-a-secret-fill)

This could help a reviewer reproduce a narrow web flow and give the live-check owner supporting evidence. The release spec #3533 reads recorded live-check ticket outcomes and asks the owner to prove a clean-machine install and first fleet on macOS and Linux. #3523 also requires a real phone and Mac, pasting the install line into T3, and other steps outside these two browser checkpoints. Keep those owner steps in the release gate. Run reliability and evidence completeness on OpenWiz are unverified. [Release spec #3533](https://github.com/openwizdev/OpenWiz/issues/3533) · [Live-check ticket #3523](https://github.com/openwizdev/OpenWiz/issues/3523)

## Subscription and run cost

The local runner and browser can run without a paid e2e service. The maintainers describe local and CI use with the owner's choice of model and no e2e markup. The pinned docs describe existing ChatGPT Plus or Pro, Copilot, OpenCode Console and SuperGrok or X Premium+ routes, plus Claude Code or Codex through the separate ACP adapter. API-key and local-model routes are available. e2e's docs recommend API providers for unattended CI on the ChatGPT, Copilot and SuperGrok routes. [TesterArmy service transition](https://tester.army/) · [Launch post](https://dev.to/testerarmy/introducing-e2e-open-source-agentic-testing-for-web-ios-and-android-4flb) · [Subscriptions](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/subscriptions.mdx) · [Models](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/models.mdx)

For a run covered by an existing subscription's included usage, the incremental provider charge is zero and live calls consume quota. Additional credits or separately billed providers follow the owner's plan. The exact quota and incremental price of the example run are unverified. They depend on the plan, model, UI and number of live calls. A deterministic test or a successful replay of a previously verified `agent.act` step uses zero model calls for those steps. A cache miss or fallback can call the model, and `agent.assert` runs live. The report sums usage and includes estimated dollars when available. A missing price field leaves the charge unknown. [ChatGPT plan usage](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan) · [Subscriptions](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/subscriptions.mdx) · [Replay cache](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/cache.mdx) · [Report cost aggregation](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/packages/e2e/src/report/build.ts)

## WizMarket fit

An opt-in `tool` entry with status `listed` fits #3384. Owners can choose the pinned runner and local Playwright engine for their own factories, using the upstream setup guide and their own provider when they want agent steps. The tool category shows upstream setup for the user to run. The card should name the Node.js requirement (22.22.3 or later on Node 22, or 24.8 or later), model usage, and the telemetry opt-out. e2e's CLI sends usage telemetry by default. Setting `E2E_TELEMETRY_DISABLED=1` before invoking it disables telemetry. Use a synthetic target and keep the report local unless the owner chooses to share it. [WizMarket spec #3384](https://github.com/openwizdev/OpenWiz/issues/3384) · [Tool install behavior #3387](https://github.com/openwizdev/OpenWiz/issues/3387) · [Pinned Node requirement](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/packages/e2e/package.json) · [Telemetry](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/telemetry.mdx) · [OpenWiz privacy spec #3456](https://github.com/openwizdev/OpenWiz/issues/3456)

## Proposed follow-up ticket

### Title

List e2e as an opt-in UI verification tool in WizMarket

### Parent

[WizMarket #3384](https://github.com/openwizdev/OpenWiz/issues/3384), using the v3 tool category and #3387's show-only path. Discovery evidence is in [RX2 #3705](https://github.com/openwizdev/OpenWiz/issues/3705).

### What to build

Add one public `e2e` listing in WizMarket. Link the canonical repository, release, pinned Apache-2.0 licence and upstream setup guide. Explain the local browser setup, the optional model and its usage limits, and how to disable telemetry before the first invocation. Set the status to `listed`. Route the listing through the existing tool display and owner-choice flow. The scope is the listing record in WizMarket.

### Acceptance criteria

- The v3 index displays exactly one e2e entry with category `tool` and status `listed`. Its repository, release, licence and setup links resolve.
- The listing describes Node and local browser prerequisites, zero model calls for deterministic tests, provider quota or charges for live agent steps, and `E2E_TELEMETRY_DISABLED=1` before first invocation.
- A fixture selection shows the upstream setup and leaves execution to the owner. It requests no credential, starts no process or model, and adds no default factory tool, release gate or artifact upload.

### Proof

Run WizMarket's listing validation and index check on the entry and exercise the #3387 tool path with a fixture index. Review the card against the pinned [licence](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/LICENSE), [setup guide](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/quickstart.mdx) and [telemetry docs](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/telemetry.mdx).

**Verdict** — listing-only. Local browser execution and step-level evidence make e2e an opt-in fit for WizMarket. The pre-1.0 support policy, default telemetry and unverified OpenWiz run reliability and usage cost leave too little evidence to put it in OpenWiz's release or review process. [WizMarket spec](https://github.com/openwizdev/OpenWiz/issues/3384) · [Support policy](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/SECURITY.md) · [Telemetry](https://github.com/e2e-inc/e2e/blob/1642ef238634d1269650b8aa5df2fa0a91086e4b/docs/telemetry.mdx)
