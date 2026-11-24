# Install OpenWiz 0.1.1

Paste this line into your coding agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Check which OpenWiz release GitHub offers before choosing a host. This guide describes 0.1.1 once its release assets are available. If you install 0.1.0, its agents run on CloudRoom. [Published releases](https://github.com/openwizdev/OpenWiz/releases) · [0.1.0 instructions](https://github.com/openwizdev/OpenWiz/blob/v0.1.0/docs/install.md)

## Before you start

- Use macOS on Apple silicon or Intel, or x86_64 Linux with glibc 2.34 or later. On Linux, `ldd --version` shows the glibc version. Linux ARM has no 0.1.1 package.
- Install Python 3.9 or later, Git and the GitHub CLI. Sign in to GitHub yourself with `gh auth login`.
- Choose where your agents run. On **this computer**, sign in to Claude Code or Codex. For **boat.dev**, sign in with the host as prompted. For **CloudRoom**, install and sign in to CloudRoom. On an Intel Mac, the available hosts are this computer and boat.dev.

## What the agent does

1. **Check the machine.** The agent reads the chosen release, clones its tag and runs the installer’s preflight. It reports the target, free space and required tools. The local and boat.dev paths can proceed without `room-cli`.

2. **Install the verified package.** The agent uses the same tag for the installer, manifest and download. The example below is for the published v0.1.1 assets. Set `openwiz` to a new temporary clone path, `target` to the target printed by preflight, `assets` to a new private download folder and `root` to the install folder (default `~/.local/lib/openwiz`).

   ```sh
   git clone --depth 1 --branch v0.1.1 https://github.com/openwizdev/OpenWiz "$openwiz"
   python3 -I "$openwiz/tools/install/install" preflight
   python3 -I "$openwiz/tools/install/install" download --version v0.1.1 --target "$target" --dir "$assets"
   ```

   The agent checks that the downloaded manifest names version `0.1.1`, then activates the build and verifies its version and source commit. The installer checks the manifest checksum and verifies the package contents before activation. A failed verification leaves the last good build selected.

   ```sh
   python3 -I "$openwiz/tools/install/install" install --assets "$assets" --target "$target" --root "$root"
   "$root/current/openwiz" --build-identity
   ```

3. **Connect GitHub.** The agent uses the `build` and `state_root` paths returned by the installer to check the connections. You complete any sign-in in your own terminal or browser. CloudRoom sign-in is required only for that host.

   ```sh
   OPENWIZ_STATE_DIR="$state_root" python3 -I -B "$build/runtime/setup/setup.py" check --state-dir "$state_root"
   ```

4. **Install the skills and restart the agent.** The installer puts the packaged skills in the install root and in the supported agent folders it finds. It places the contracts and plugin manifest beside the skills. The agent checks the result for its own folder, reports any same-named personal skill it skipped and verifies its installed copy of the install skill.

   ```sh
   python3 -I "$openwiz/tools/install/install" skills --root "$root"
   ```

   Start a new session with the continuation message the agent gives you. For a local 0.1.1 install, it is `continue the OpenWiz install with host local and release v0.1.1`. The other host words are `boat` and `cloud`. The host and tag carry your choices through the restart. [Pinned WizSkills 0.4.2 install procedure](https://github.com/openwizdev/WizSkills/blob/v0.4.2/skills/install/SKILL.md)

5. **Start a first fleet if you want one.** Choose a private demo repository or one of yours. Setup offers a personal GitHub login or your own GitHub App, records the selected project and asks for your harness, model and effort. You confirm the proposed work. For local agents you also choose the harness permission mode. Once the plan passes its checks and the host settings are ready, the agent names the host and cost and asks for your go before launch. [Grok Bot setup](grok-bot.md)

OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. CloudRoom runs use Cloud Credits. Referral verification is unavailable. No referral is applied. [CloudRoom pricing](https://cloudroom.dev/pricing)

## Recovery

Resume with the same host and release. The agent reads the installed state to find the first unfinished step. To check a build, run `python3 -I "$openwiz/tools/install/install" status --root "$root"`. If a build file is damaged, rerun the verified install with the same release assets and root. If you supplied a separate state root, pass the same `--state-root` to the installer.

## Remove it

Ask the agent to remove OpenWiz. If a local fleet heartbeat was installed, the agent identifies its scheduled jobs and previews their removal first. The installer then shows the exact files and settings it would delete:

```sh
python3 -I "$openwiz/tools/install/install" remove --root "$root"
```

Review the list before adding `--yes`. For a separate state root, include the original `--state-root` in both commands. The result lists the OpenWiz skill copies in each agent folder for manual cleanup. Revoke the GitHub App in GitHub and remove any phone-access tunnel or CloudRoom loop separately if you want those gone too.
