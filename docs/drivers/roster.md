# OpenWiz 0.2.0 driver roster

A driver is anything that can start, wake and stop one agent on one ticket
under [driver v1](../../kernel/driver.v1.md). The roster excludes chat apps,
tools and models. An always-on bot qualifies when its API can do those same
three things. [Bot checks are tracked in #3490](https://github.com/openwizdev/OpenWiz/issues/3490).

Only Local is on out of the box. Boat also ships in the OpenWiz kernel and
starts off. The repository column names each driver's 0.2.0 home. Follow the
driver's ticket for the status of a move or a new repository.
[Driver moves](https://github.com/openwizdev/OpenWiz/issues/3027),
[Boat's default](https://github.com/openwizdev/OpenWiz/issues/3557),
[new drivers](https://github.com/openwizdev/OpenWiz/issues/3474).

| Driver | Kind | 0.2.0 repository | Default | WizMarket listing ID | Proof state |
| --- | --- | --- | --- | --- | --- |
| [Local](https://github.com/openwizdev/OpenWiz/issues/3024) | machine | `openwizdev/OpenWiz` | on | [`local`](https://github.com/openwizdev/WizMarket/blob/main/listings/local.json) | verified |
| [Boat](https://github.com/openwizdev/OpenWiz/issues/3557) | sandbox | `openwizdev/OpenWiz` | off | [`boat-dev`](https://github.com/openwizdev/WizMarket/blob/main/listings/boat-dev.json) | verified |
| [Capy](https://github.com/openwizdev/OpenWiz/issues/3019) | agent cloud | `openwizdev/driver-capy` | off | `capy` (planned) | unverified |
| [Claude Code cloud](https://github.com/openwizdev/OpenWiz/issues/3477) | agent cloud | `openwizdev/driver-claude-code-cloud` | off | `claude-code-cloud` (planned) | unverified |
| [Cloudflare Sandbox](https://github.com/openwizdev/OpenWiz/issues/3484) | sandbox | `openwizdev/driver-cloudflare-sandbox` | off | `cloudflare-sandbox` (planned) | unverified |
| [CloudRoom](https://github.com/openwizdev/OpenWiz/issues/3023) | sandbox | `openwizdev/driver-cloudroom` | off | [`cloudroom`](https://github.com/openwizdev/WizMarket/blob/main/listings/cloudroom.json) | listed |
| [Conductor](https://github.com/openwizdev/OpenWiz/issues/3015) | agent cloud | `openwizdev/driver-conductor` | off | [`conductor`](https://github.com/openwizdev/WizMarket/blob/main/listings/conductor.json) | listed |
| [Cursor Cloud Agents](https://github.com/openwizdev/OpenWiz/issues/3016) | agent cloud | `openwizdev/driver-cursor` | off | [`cursor-cloud-agents`](https://github.com/openwizdev/WizMarket/blob/main/listings/cursor-cloud-agents.json) | listed |
| [Daytona](https://github.com/openwizdev/OpenWiz/issues/3481) | sandbox | `openwizdev/driver-daytona` | off | `daytona` (planned) | unverified |
| [Devin](https://github.com/openwizdev/OpenWiz/issues/3022) | agent cloud | `openwizdev/driver-devin` | off | [`devin`](https://github.com/openwizdev/WizMarket/blob/main/listings/devin.json) | listed |
| [Docker (local)](https://github.com/openwizdev/OpenWiz/issues/3483) | sandbox | `openwizdev/driver-docker` | off | `docker` (planned) | unverified |
| [E2B](https://github.com/openwizdev/OpenWiz/issues/3480) | sandbox | `openwizdev/driver-e2b` | off | `e2b` (planned) | unverified |
| [Factory](https://github.com/openwizdev/OpenWiz/issues/3011) | machine | `openwizdev/driver-factory` | off | [`factory`](https://github.com/openwizdev/WizMarket/blob/main/listings/factory.json) | listed |
| [Fly.io Machines](https://github.com/openwizdev/OpenWiz/issues/3486) | sandbox | `openwizdev/driver-fly-machines` | off | `fly-machines` (planned) | unverified |
| [Fly Sprites](https://github.com/openwizdev/OpenWiz/issues/3014) | sandbox | `openwizdev/driver-sprites` | off | [`fly-sprites`](https://github.com/openwizdev/WizMarket/blob/main/listings/fly-sprites.json) | listed |
| [GitHub Codespaces](https://github.com/openwizdev/OpenWiz/issues/3013) | sandbox | `openwizdev/driver-codespaces` | off | [`codespaces`](https://github.com/openwizdev/WizMarket/blob/main/listings/codespaces.json) | listed |
| [GitHub Copilot coding agent](https://github.com/openwizdev/OpenWiz/issues/3479) | agent cloud | `openwizdev/driver-github-copilot-coding-agent` | off | `github-copilot-coding-agent` (planned) | unverified |
| [Google Jules](https://github.com/openwizdev/OpenWiz/issues/3478) | agent cloud | `openwizdev/driver-google-jules` | off | `google-jules` (planned) | unverified |
| [Hermes](https://github.com/openwizdev/OpenWiz/issues/3010) | machine | `openwizdev/driver-hermes` | off | [`hermes`](https://github.com/openwizdev/WizMarket/blob/main/listings/hermes.json) | listed |
| [Modal](https://github.com/openwizdev/OpenWiz/issues/3482) | sandbox | `openwizdev/driver-modal` | off | `modal` (planned) | unverified |
| [Ona](https://github.com/openwizdev/OpenWiz/issues/3021) | sandbox | `openwizdev/driver-ona` | off | `ona` (planned) | unverified |
| [OpenAI Codex cloud](https://github.com/openwizdev/OpenWiz/issues/3476) | agent cloud | `openwizdev/driver-openai-codex-cloud` | off | `openai-codex-cloud` (planned) | unverified |
| [OpenClaw](https://github.com/openwizdev/OpenWiz/issues/2997) | machine | `openwizdev/driver-openclaw` | off | [`openclaw`](https://github.com/openwizdev/WizMarket/blob/main/listings/openclaw.json) | verified |
| [OpenHands Cloud](https://github.com/openwizdev/OpenWiz/issues/3018) | agent cloud | `openwizdev/driver-openhands` | off | [`openhands-cloud`](https://github.com/openwizdev/WizMarket/blob/main/listings/openhands-cloud.json) | listed |
| [Pane](https://github.com/openwizdev/OpenWiz/issues/3012) | machine | `openwizdev/driver-pane` | off | [`pane`](https://github.com/openwizdev/WizMarket/blob/main/listings/pane.json) | listed |
| [SSH/VPS](https://github.com/openwizdev/OpenWiz/issues/3558) | machine | `openwizdev/driver-ssh` | off | `ssh-vps` (planned) | unverified |
| [Tembo](https://github.com/openwizdev/OpenWiz/issues/3020) | agent cloud | `openwizdev/driver-tembo` | off | `tembo` (planned) | unverified |
| [Vercel Sandbox](https://github.com/openwizdev/OpenWiz/issues/3485) | sandbox | `openwizdev/driver-vercel-sandbox` | off | `vercel-sandbox` (planned) | unverified |
| [Warp Oz](https://github.com/openwizdev/OpenWiz/issues/3017) | agent cloud | `openwizdev/driver-warp-oz` | off | [`warp-oz`](https://github.com/openwizdev/WizMarket/blob/main/listings/warp-oz.json) | listed |

- `verified` means the linked listing has a five-check receipt. The 0.2.0
  release bar requires a current receipt for the version that ships.
- `listed` means WizMarket carries the driver and marks it listed pending
  verification.
- `unverified` marks a driver without a current receipt, including planned
  drivers. A planned listing ID comes from its ticket.
- `later` means the [API check](api-check.md) found the host cannot yet
  support the driver. The driver stays visible with its reason in WizMarket.
