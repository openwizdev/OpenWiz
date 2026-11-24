<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/lockup-dark.png">
    <img alt="OpenWiz" src="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/lockup-light.png" width="320">
  </picture>
</h1>

**OpenWiz is the open kernel for agent factories. Bring your own everything. Owned by no one.** This repo is the kernel itself; the [other repos](https://github.com/openwizdev) add skills, loops and the app on top.

You make the decisions: answer a few questions. The agents run the factory: they write the spec and the tickets, build, review and merge. You watch it ship.

This branch documents **OpenWiz 0.1.1**. Check the [published releases](https://github.com/openwizdev/OpenWiz/releases) for availability. If the release you install is 0.1.0, follow its [CloudRoom setup guide](https://github.com/openwizdev/OpenWiz/blob/v0.1.0/docs/install.md).

## Quick start

For 0.1.1 you need Python 3.9 or later, Git, and the GitHub CLI. Use macOS on Apple silicon or Intel, or Linux on x86_64 or ARM64 (aarch64) with glibc 2.34 or later. Choose where agents run: this computer with Claude Code or Codex, boat.dev, or CloudRoom. Only the CloudRoom host needs a CloudRoom login. On an Intel Mac, choose this computer or boat.dev.

Paste this line into your coding agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Your agent verifies the prebuilt release, connects GitHub and installs the skills. You choose whether to start a first fleet after its plan passes the checks. OpenWiz is free. Your model and host charges are your own. [Install guide](docs/install.md) · [Pinned install skill](https://github.com/openwizdev/WizSkills/blob/v0.4.2/skills/install/SKILL.md)

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/map-dark.png">
  <img alt="How the repos fit: WizSkills and WizLoops feed OpenWiz, the kernel. OpenWiz drives your agents and machines and writes records to GitHub. WizSite's app reads GitHub." src="https://raw.githubusercontent.com/openwizdev/.github/main/profile/art/map-light.png" width="560">
</picture>

The kernel is small. Three parts:

- **Records on GitHub.** Specs, tickets and one status note per agent live in your repo's issues. Anything that follows [the rules](kernel/records.v1.md) can read and write your factory. The [records kit](kernel/records-kit/README.md) checks them.
- **Drivers.** A driver is a tiny program, in any language, that answers four commands: `version`, `start`, `wake`, `stop` ([driver v1](kernel/driver.v1.md)). Copy [the template](adapters/template/README.md) to plug in your own host. The release carries drivers for your computer or a VPS, CloudRoom and boat.dev.
- **A test kit.** The [driver kit](kernel/driver-kit/README.md) checks a driver on its real host. A driver that passes can merge.

OpenWiz never touches a login. Your agents use their own signed-in tools, and there is no server of ours.

| Path | What it is |
| --- | --- |
| `kernel/` | The records and driver rules, and their test kits |
| `adapters/` | The drivers, one folder per host |
| `crates/` | The `openwiz` command (Rust) |
| `docs/` | Guides and public decisions |

## Versions

What each version adds is in the [changelog](CHANGELOG.md). A version has at most five outcomes, each one something a user can see or check, and claims nothing its evidence doesn't show; tests alone never prove live behaviour.

## Links

- [openwiz.dev](https://openwiz.dev) · [the app](https://openwiz.dev/app/) · [Changelog](CHANGELOG.md)
- Agents start at [AGENTS.md](AGENTS.md). For anything beyond a small fix, open an issue first. Everything here is public: use synthetic examples only, never personal data, secrets or private links. A new dependency needs the maintainer's approval.
- [Apache License 2.0](LICENSE). A contribution is licensed under the same terms; there is no separate contributor agreement.
