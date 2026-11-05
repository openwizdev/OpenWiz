# Install OpenWiz

Paste this one line into the coding agent you already use (Claude Code, Codex or another):

> Install OpenWiz from github.com/openwizdev/openwiz

The agent follows the [install skill](../skills/install/SKILL.md). This page says what it does, what it may change, and how to recover or remove it.

**Status:** the install journey is tested on synthetic fixtures only. A real install on a fresh machine, and the time it takes, are not yet verified.

## What happens, in order

1. **Preflight.** The agent checks this computer: Python 3.9 or later, a supported system (macOS on Apple silicon or Intel, or Linux on x86_64), free disk space, and whether CloudRoom's `room-cli`, `gh` and `git` are installed. It reads only; nothing is installed or changed. Anything missing comes with its next step.
2. **Verified install.** It downloads the latest OpenWiz release from GitHub and checks every file's SHA-256 hash against the release's manifest before using it. No Rust, Node or source build is needed. A hash proves the files are the release's files; it is not a publisher signature. A failed check changes nothing, and an earlier install keeps working.
3. **Setup and connections.** It opens the setup page on your own computer (`http://127.0.0.1:7370/setup`) and checks each connection on its own: CloudRoom, your agent harness, your agents' GitHub login, OpenWiz's GitHub App, your project, the engine and, optionally, phone access. Existing CloudRoom sign-ins are reused. A connection is ready only when a check proves it, never because a setting was saved.
4. **Engine.** It shows where OpenWiz's engine would run, Cloud or Local, and what it is expected to cost in Cloud Credits, labelled measured, estimated or unknown. You choose.
5. **Explain.** A few sentences on ideas, grills, specs, tickets, builders, independent review and merges.
6. **First fleet.** The [onboard skill](../skills/onboard/SKILL.md) offers a few quick ideas, grills you briefly, plans 4 to 7 small tickets and starts them only after you approve that exact plan.

## What it may change, and when

- **Nothing without your yes.** Before connecting the GitHub App, saving project settings, setting up phone access, starting the engine or starting agents, the agent shows exactly what will happen and waits for your yes to that.
- **Installing is not approving work.** Saying yes to the install or setup approves no plan. Agents start only after you confirm a spec and approve its plan.
- **Your files.** The install writes only to its own folder (by default `~/.local/lib/openwiz`) and its private state inside it. Existing settings and credentials are never replaced.
- **GitHub.** OpenWiz's GitHub App is installed only on repositories you select, with read access to metadata, checks and actions and write access to contents, issues and pull requests. There is no personal-token fallback.
- **Credentials.** Keys stay in owner-only storage: files on the computer that runs the engine, or CloudRoom's own secret store. If setup asks you for the App's key, paste it only into CloudRoom's secret prompt. Never paste a key or token into the chat.
- **Cost.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. Cloud agents and a Cloud engine use your CloudRoom Cloud Credits, and your model provider bills you directly. More credits are CloudRoom's own plan, bought from [CloudRoom](https://cloudroom.dev/pricing), not from OpenWiz. Referral verification is unavailable. No referral is applied.

## If it is interrupted or fails

Ask the agent to continue: every step checks what is already done before doing anything. A repeated install reuses the verified build. A refused install or update leaves the last good build in use. Setup and engine steps remember their operation, so an interrupted step is finished or replaced, never done twice; an unclear result is checked before anything is retried.

If the setup page does not open, ask the agent to check the install's status and open setup again. If a connection shows refused or unknown, follow its next step, then check again.

## Remove it

Ask the agent to remove OpenWiz. It stops only this installation's own server and engine, then deletes the install folder. It keeps your settings unless you ask it to delete them too. Your repositories, branches, pull requests and CloudRoom threads are your work and are never deleted.

**Removing OpenWiz from this computer does not revoke its access.** To revoke it:

- uninstall OpenWiz's GitHub App, or remove repositories from it, in your GitHub settings;
- delete any Cloudflare Tunnel and Access application, or Tailscale rule, made for phone access;
- remove the engine's Loop in CloudRoom, if one was created.
