# Install OpenWiz

Tell your coding agent (Claude Code, Codex, Cursor or another):

> Install OpenWiz

That phrase is the whole install instruction. The agent follows [Install OpenWiz](../AGENTS.md#install-openwiz). The numbered steps below are the command reference for OpenWiz 0.1.1. `<tag>` in them is `v0.1.1`. They are not the steps for 0.1.0, and not the steps for a later release. This page says what that install does, the commands it runs, what it may change, and how to recover or remove it.

Using Grok Bot? See [Grok Bot + OpenWiz](grok-bot.md).

**Status:** this is the install for OpenWiz 0.1.1 ("OpenWiz 0.02"), which is coming and not released yet; the current release is OpenWiz 0.1.0. CloudRoom is optional: setup is done when GitHub's sign-in is verified, and CloudRoom's sign-in too only if you pick CloudRoom. Installing today? Follow [OpenWiz 0.1.0](#openwiz-010) at the end.

## Platforms

These platform levels apply to OpenWiz 0.2.0.

- **Supported.** macOS on Apple silicon and Intel, and Linux on x86_64 and aarch64 with glibc 2.34 or later. The release bar is a clean-machine install and first fleet on both operating systems.
- **Community.** Windows through WSL uses the corresponding Linux build and requirements. It works for some users. The project does not test WSL.
- **Unsupported.** Native Windows. Run the installer from a Linux distribution inside WSL instead.

## Before you start

- **A supported computer:** macOS on Apple silicon or Intel, or Linux on x86_64 or ARM64 (aarch64) with glibc 2.34 or later (`ldd --version` shows it). **An Intel Mac installs with no CloudRoom,** on 0.1.1 and on 0.1.0 alike: preflight reads it ready. CloudRoom has no Intel Mac build and no ARM64 Linux build, so on an Intel Mac or on ARM64 Linux, agents run on this computer or on boat.dev. On x86_64 Linux older than glibc 2.39, `openwiz` may print a `GLIBC_2.39` warning and still work. On ARM64 Linux the package has to be built for glibc 2.34; a hard `GLIBC_2.39` requirement does not start.
- **Python 3.9 or later, `git`, and the GitHub CLI** (`gh`, signed in with `gh auth login`).
- **Where your agents run,** asked first, before anything else: this computer, boat.dev or CloudRoom. CloudRoom is optional: only the CloudRoom choice needs it installed.
  - **This computer:** the Claude Code or Codex you're signed in to, and your `gh` login. Nothing else to sign in to.
  - **boat.dev:** its `boat` CLI, which you install and sign in to yourself, and in boat.dev's dashboard your GitHub account connected with write access to the repository, and your Claude Code or Codex key or account login. It bills per second while a sandbox runs, on your plan.
  - **CloudRoom:** installed, opened once and signed in (opening it once creates its `room-cli`).
- **For the automatic fleet on this computer or boat.dev:** `jq`, and Claude Code or Codex installed on this computer, because the heartbeat's GitHub check runs here even when your agents run on boat.dev. The orchestrator it starts runs on the host you chose: on this computer, or in a boat.dev sandbox, billed per second like the builders.

## What happens, in order

The agent runs each command itself and reads its JSON. `<root>` is the install folder, by default `~/.local/lib/openwiz`: use a new or empty folder that holds nothing else, because the installer also accepts a folder that already has other files in it. If you give `install install` a separate `--state-root`, it too must be a new or empty folder used by OpenWiz alone, never one shared with another app. `<target>` is `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu` or `aarch64-unknown-linux-gnu`.

1. **Preflight.** It clones this repository at `<tag>` into a private temporary folder as `$openwiz` (`git clone --depth 1 --branch "$tag" -- https://github.com/openwizdev/OpenWiz "$openwiz"`, and only after the whole value of `<tag>` matches `v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)`) and checks this computer: Python, a supported system, free disk space, and whether `room-cli`, `gh` and `git` are installed. It reads only; anything missing comes with its next step. A missing `room-cli` never stops it: it says CloudRoom is optional, needed only if you pick it. On an Intel Mac it reads ready and notes that agents run on this computer or on boat.dev.

   ```sh
   python3 -I "$openwiz"/tools/install/install preflight
   ```

2. **Verified download and install.** Before downloading or activating anything, check that the selected `<tag>` is `v0.1.1` (`<version>` is `0.1.1`, the version this guide expects); if not, stop without downloading or activating. Pass `--version "$tag"` so `download` fetches that exact release tag from GitHub (not GitHub's Latest release, which may have moved), checks the manifest against its checksum and the package's SHA-256 hash against the manifest and `SHA256SUMS`, and writes nothing to `<root>`. No Rust, Node or source build is needed. A hash proves the files are the release's files; it is not a publisher signature. A failed check changes nothing, and an earlier install keeps working.

   ```sh
   python3 -I "$openwiz"/tools/install/install download --target <target> --dir <new private folder> --version "$tag"
   ```

   Check before activation that `download` printed `"outcome": "downloaded"` and `"version"` equal to `<version>` (`0.1.1`), and that `<that folder>/openwiz-<target>.manifest.json` reports `"version"` equal to `<version>` (`0.1.1`); if either differs, stop and do not run `install install`. Only after that check passes, activate the verified build:

   ```sh
   python3 -I "$openwiz"/tools/install/install install --assets <that folder> --target <target> --root <root>
   ```

   `install` prints `"activated": true`, the version, and the `build` and `state_root` folders, written below as `<build>` and `<state>`. `download --version "$tag"` reads `https://github.com/openwizdev/OpenWiz/releases/download/$tag/` (`v0.1.1` once 0.1.1 is out); if it refuses with "could not be completed safely", check the [releases page](https://github.com/openwizdev/OpenWiz/releases). The same three files will be under `https://github.com/openwizdev/OpenWiz/releases/download/v0.1.1/` once 0.1.1 is out: `openwiz-<target>.sha256`, `openwiz-<target>.manifest.json` and `openwiz-0.1.1-<target>.tar.gz`. Put them in a new private folder (mode 700, files 600), verify `openwiz-<target>.manifest.json` names `"version": "0.1.1"` before activation, and run `install install --assets` on it; it checks every hash the same way.

   Then it proves the build: `<root>/current/openwiz --build-identity` prints the version (`0.1.1`) and the source commit. The `openwiz` program lives there, not on your `PATH`: typing `openwiz` alone says "command not found".

   **Early builds (OpenWiz Pro, opt-in):** with no extra flag, `install download` reads only public releases from `openwizdev/OpenWiz` and installs on the `packaged` channel. Because step 1's `$openwiz` clone is pinned to `v0.1.1` (which does not accept `--early`), OpenWiz Pro members first clone the current default branch into a separate private temporary folder (or use an installer from `0.2.0` or later once released), then pass `--early` to `install download`:

   ```sh
   openwiz_early=$(mktemp -d)/OpenWiz
   git clone --depth 1 https://github.com/openwizdev/OpenWiz "$openwiz_early"
   python3 -I "$openwiz_early"/tools/install/install download --early --target <target> --dir <new private folder>
   python3 -I "$openwiz_early"/tools/install/install install --assets <that folder> --target <target> --root <root>
   ```

   `download --early` uses your existing `gh` login (without storing or logging any token) to check prereleases tagged `v<version>-rc.<n>` in the private `openwizpro/WizPro` repository alongside public releases, picks whichever is newer by semver, and verifies `SHA256SUMS`, the manifest and the archive the same way. Installing writes `{"schema":"openwiz.update-channel.v1","channel":"early"}` to `<root>/channel.json` (switching an existing `packaged` install to `early` only after the new build verifies and activates), and later updates follow the newest early or public release by semver so you are never left behind a public release. If `gh` is missing or not logged in, it refuses and tells you to run `gh auth login`; if your account does not have access to `openwizpro/WizPro` (HTTP 404), it refuses and links to [openwiz.dev/pro](https://openwiz.dev/pro/). `install remove` removes an `early` `channel.json` the same as `packaged`.

3. **Setup and logins.** Nothing opens in a browser by itself: the agent reads each connection with one check, run from the installed build, and reruns it after each change.

   ```sh
   OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/setup/setup.py check --state-dir <state>
   ```

   It prints one code per part: `cloudroom`, `personal_github`, `github_app`, `harness` and `project`. On a new computer expect codes such as `app_missing`, `harness_unselected`, `identity_unselected` and `project_unprepared`: those wait until you pick a repository. A connection is ready only when a check proves it, never because a setting was saved.

   - **CloudRoom,** only if you pick it; otherwise skip this row, and no `cloudroom_*` code `check` prints blocks the install: `runtime/cloudroom/cloudroom.py status` reads whether CloudRoom is installed and signed in; `runtime/cloudroom/cloudroom.py install` shows CloudRoom's published installer and its checksum and waits for your yes; `runtime/cloudroom/cloudroom.py sign-in` opens CloudRoom's own sign-in once, where you sign in yourself. Each takes `--state-dir <state>`. CloudRoom is done when `check` reads `cloudroom_login_verified`.
   - **GitHub:** `runtime/setup/github_login.py sign-in --state-dir <state>` reuses your existing `gh` login, or shows what GitHub's own browser sign-in will do and waits for your yes. You paste no token.
   - **`identity_unreadable`** (for `personal_github`): GitHub's answer could not be read just then. Wait a minute and run `check` again; it usually clears.

4. **Skills into your agents, then a restart.** Only now, with setup checked and the logins done, it copies OpenWiz's skills from that release's package (the WizSkills release recorded by `wizskills.lock` on `<tag>`) into each agent found on this computer: `~/.claude/skills` (Claude Code), `~/.codex/skills` (Codex), `~/.cursor/skills` (Cursor), `~/.config/opencode/skills` (OpenCode) and `~/.grok/skills` (Grok). A skill of yours with the same name stops the step before anything is written.

   ```sh
   python3 -I "$openwiz"/tools/install/install skills --root <root>
   ```

   Your agent finds the skills the next time it starts. Restart it (a new session), then paste the one message for your host: `continue the OpenWiz install with host local` (this computer), `with host boat` (boat.dev) or `with host cloud` (CloudRoom). It resumes at the first unfinished step, from the installed files.

5. **Explain.** A few sentences on ideas, grills, specs, tickets, builders, independent review and merges.
6. **First fleet.** The same agent continues through the install skill's first-fleet section when you want to try it:
   - It offers a few quick ideas and a new private demo repository, or one of yours. That one repository is used from here on.
   - It connects GitHub for that repository. Then you choose your own OpenWiz App (Create, then Install on that repository only) or skip it. If you skip it, your personal GitHub login acts for the factory and setup says so; the App is never shown as verified.
   - It saves the project with your harness, model and effort, asked once, and makes its private brain (`openwiz init`): in your repository if it is private, or in a new private companion repository if it is public. It tells you where in one line and opens a pull request you merge.
   - On this computer it asks you once for each harness's permission mode, and never picks one for you. For this computer or boat.dev it opens one pull request naming the host, which you merge.
   - It grills you briefly and plans 4 to 7 small tickets. You confirm the spec, then approve the exact plan, as two separate answers.
   - It shows the start, naming the host and what it can cost. Only your yes to that starts anything.
   - In 0.1.1 the automatic fleet runs on this computer, on boat.dev or in CloudRoom. **With CloudRoom,** it runs in one fleet thread with its own loop, which starts the approved tickets' builders and their reviewers, and your yes covers its Cloud Credits. **With this computer or boat.dev,** a local heartbeat runs it instead: a scheduled job on this computer (launchd on macOS, a systemd user timer or cron on Linux), shown first and installed on your yes. It checks GitHub from this computer every ten minutes and starts or wakes the fleet's orchestrator only when work is due, on the host you chose: here, or in a boat.dev sandbox, billed per second. Saying "run the fleet now" runs the same check at once while the job is active; a paused job skips it until `resume`. The orchestrator starts builders, and reviewers through the same driver: a reviewer from the other family when you have both Claude Code and Codex, and with only one, a review by the same family, marked "same-family review".

## What it may change, and when

- **Nothing without your yes.** Before signing in, creating or skipping the GitHub App, saving project settings, creating the brain, setting up phone access or starting agents, the agent shows exactly what will happen and waits for your yes to that.
- **Installing is not approving work.** Saying yes to the install or setup approves no plan. Agents start only after you confirm a spec and approve its plan.
- **Your files.** The install writes only to its own folder (by default `~/.local/lib/openwiz`), its private state inside it, and OpenWiz's skills in your agents' skill folders (step 4). Existing settings, credentials and skills of your own are never replaced.
- **GitHub.** Your own OpenWiz App is private to your account and installed only on repositories you select, with read access to metadata, checks and actions and write access to contents, issues and pull requests. Your personal login acts only if you explicitly skip the App; an App that fails or is removed never switches to it on its own.
- **Credentials.** Never paste a key or token into the chat. **This computer** uses the Claude Code or Codex and `gh` logins you already have. **boat.dev** uses what you connect in its dashboard: your GitHub account with write access, and your Claude Code or Codex key or account login; OpenWiz touches none of it. **Your OpenWiz App's key,** if you create the App, is kept by setup in owner-only state on this computer (`<state>/service/app/`). With **CloudRoom**, if setup asks you for the App's key, paste it only into CloudRoom's secret prompt.
- **Cost.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. On this computer, agents use your own Claude Code or Codex plan. boat.dev bills its sandboxes per second on your boat.dev plan. If you pick CloudRoom, its cloud agents, including each fleet thread, use your CloudRoom Cloud Credits. Your model provider bills you directly. More credits are CloudRoom's own plan, bought from [CloudRoom](https://cloudroom.dev/pricing), not from OpenWiz. Referral verification is unavailable. No referral is applied.

## If it is interrupted or fails

Start a new session of your agent and say "continue the OpenWiz install": every step checks what is already done before doing anything. A repeated install reuses the verified build. A refused install or update leaves the last good build in use. Setup, sign-in, App and brain steps remember their operation, so an interrupted step is finished or replaced, never done twice; an unclear result is checked before anything is retried.

`install status --root <root>` checks the installed build against its manifest. If it reports `installed asset mismatch`, a file in the build was changed, and installing the same release again refuses the same way. To repair it and keep your settings, delete only the `<root>/current` link and the one build folder it points to (`<build>`, inside `<state>/service/builds/`), and nothing else in `<state>/service/`. Then run step 2's `install install` again. If a connection shows a code that is not ready, follow its step above, then run `setup.py check` again.

## Remove it

Ask the agent to remove OpenWiz. It goes in this order:

- **First, the heartbeat,** if a fleet runs on this computer or boat.dev. From the installed launch-fleet skill's folder (for example `~/.claude/skills/launch-fleet`), `python3 -I scripts/heartbeat.py status <owner>/<repo> <spec>` shows the job. `heartbeat.py pause <owner>/<repo> <spec>` stops it for now (`resume` brings it back). `heartbeat.py remove <owner>/<repo> <spec>` takes down the schedule, stops the fleet's orchestrator and deletes the heartbeat's state. Remove each one before deleting OpenWiz's files, or the job keeps running.
- **Then the install:** `python3 -I "$openwiz"/tools/install/install remove --root <root>` (from the `<tag>` clone in step 1; add `--state-root <state>` if you gave one) previews exactly what OpenWiz made: the `current` link, `channel.json`, `install.lock`, its marked skill copies in `<root>/skills`, the verified builds and its settings in `<state>`. With `--yes` it deletes exactly those, then removes each folder left empty. Anything else stays, links are never followed, and it refuses while an install or update is running.
- **The skill copies in your agents stay:** `install remove` lists, for each agent, a `path` (a shared folder such as `~/.claude/skills`) and the `names` of OpenWiz's skill folders inside it. Remove just those named folders inside each `path`, never the listed folder itself: it also holds your own skills.
- Your repositories, branches, pull requests and CloudRoom threads are your work and are never deleted.

**Removing OpenWiz from this computer does not revoke its access.** To revoke it:

- uninstall OpenWiz's GitHub App, or remove repositories from it, in your GitHub settings;
- delete any Cloudflare Tunnel and Access application, or Tailscale rule, made for phone access;
- delete a fleet thread's loop in CloudRoom when you no longer want that fleet to run;
- remove each local heartbeat (`heartbeat.py remove`), as above, when a fleet runs on this computer or boat.dev.

## OpenWiz 0.1.0

OpenWiz 0.1.0 ("OpenWiz 0.01") also installs with no CloudRoom, on Apple silicon, an Intel Mac or Linux on x86_64. Its [install skill](https://github.com/openwizdev/WizSkills/blob/33eef93ba30cd8db256f6fe270e3ed28747a79bd/skills/install/SKILL.md) (WizSkills commit `33eef93ba30cd8db256f6fe270e3ed28747a79bd`, version 0.2.2) is that commit, not `v0.1.0`'s `wizskills.lock`. On 0.1.0 the automatic fleet runs in CloudRoom; without CloudRoom you plan (grill, spec, tickets), start each builder by hand on this computer or on boat.dev, and review and merge its pull request yourself. 0.1.0 has no `install remove`: its install skill lists exactly what to delete.

When the skill URL cannot be read directly, recover it by commit first and follow it from the top, or run these complete 0.1.0 steps in order:

1. **Recover and verify the pinned 0.1.0 install skill** (also needed in step 5 below):

   ```sh
   wizskills=$(mktemp -d)
   expected_commit=33eef93ba30cd8db256f6fe270e3ed28747a79bd
   expected_tree=30d1eaf27658efd8f781f98703fbbdb81bcd705d
   git init -q -- "$wizskills"
   git -C "$wizskills" fetch -q --depth 1 -- https://github.com/openwizdev/WizSkills "$expected_commit"
   git -C "$wizskills" switch -q --detach FETCH_HEAD
   head_commit=$(git -C "$wizskills" rev-parse HEAD)
   install_tree=$(git -C "$wizskills" rev-parse HEAD:skills/install)
   ```

   Verify `$head_commit` equals `33eef93ba30cd8db256f6fe270e3ed28747a79bd` and `$install_tree` equals `30d1eaf27658efd8f781f98703fbbdb81bcd705d`; if the fetch fails or either hash mismatches, stop and say so. When the skill URL could not be read, follow `"$wizskills"/skills/install/SKILL.md` from the top.

2. **Preflight:** clone tag `v0.1.0` into a new private temporary folder and run preflight:

   ```sh
   openwiz=$(mktemp -d)
   git clone --depth 1 --branch v0.1.0 -- https://github.com/openwizdev/OpenWiz "$openwiz"
   python3 -I "$openwiz"/tools/install/install preflight
   ```

3. **Verified download and install:** 0.1.0's `install download` has no `--version` and reads GitHub's Latest release (which stops being 0.1.0 once 0.1.1 is released). Select 0.1.0 explicitly from `https://github.com/openwizdev/OpenWiz/releases/download/v0.1.0/` into a new private folder (mode 700, files 600), verify the manifest names `"version": "0.1.0"` before activation, then run `install install --assets` and prove `--build-identity`:

   ```sh
   assets=$(mktemp -d)
   chmod 700 "$assets"
   umask 077
   for f in openwiz-<target>.sha256 openwiz-<target>.manifest.json openwiz-0.1.0-<target>.tar.gz; do
     curl -fsSL --proto '=https' -o "$assets/$f" "https://github.com/openwizdev/OpenWiz/releases/download/v0.1.0/$f"
   done
   python3 -I -c 'import json, sys; assert json.load(open(sys.argv[1]))["version"] == "0.1.0"' "$assets/openwiz-<target>.manifest.json"
   python3 -I "$openwiz"/tools/install/install install --assets "$assets" --target <target> --root <root>
   <root>/current/openwiz --build-identity
   ```

   `install` checks every hash and prints `"activated": true`, `<build>` and `<state>`, and `<root>/current/openwiz --build-identity` reads `0.1.0`.

4. **Setup and logins:** check connections from the installed 0.1.0 build and rerun `check` after each change:

   ```sh
   OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/setup/setup.py check --state-dir <state>
   OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/setup/github_login.py sign-in --state-dir <state>
   ```

   `github_login.py sign-in` reuses a verified `gh` login, or previews browser sign-in and completes with `--yes` on your yes. **CloudRoom,** only if you pick it (otherwise skip every `cloudroom_*` code): run `OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/cloudroom/cloudroom.py status --state-dir <state>`, `OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/cloudroom/cloudroom.py install --state-dir <state>` (preview, then `--yes --operation <id>` on your yes; only if you pick CloudRoom), and `OPENWIZ_STATE_DIR=<state> python3 -I -B <build>/runtime/cloudroom/cloudroom.py sign-in --state-dir <state>` until `check` reads `cloudroom_login_verified`.

5. **Skills and required `install` skill replacement:** run `install skills`, then overwrite each agent's packaged `install` skill from the verified `"$wizskills"/skills/install` folder before restarting. The 0.1.0 archive ships `install` skill `version: 0.2.0`, which tells a restarted agent to run `install open` — a command the `v0.1.0` installer rejects.

   ```sh
   python3 -I "$openwiz"/tools/install/install skills --root <root>
   src="$wizskills/skills/install"
   if [ "$(git -C "$wizskills" rev-parse HEAD)" != "$expected_commit" ] || [ "$(git -C "$wizskills" rev-parse HEAD:skills/install)" != "$expected_tree" ]; then
     echo "SOURCE MISMATCH" >&2; false
   else
     failed=no
     for d in "$HOME/.claude/skills" "$HOME/.codex/skills" ${CODEX_HOME:+"$CODEX_HOME/skills"} "$HOME/.cursor/skills" "$HOME/.config/opencode/skills" "$HOME/.grok/skills"; do
       [ -f "$d/install/.openwiz-skill" ] || continue
       cp -R "$src"/. "$d/install/"
       same=yes
       for f in $(cd "$src" && find . -type f); do cmp -s "$src/$f" "$d/install/$f" || same=no; done
       if [ "$same" = yes ] && grep -q '^version: 0.2.2$' "$d/install/SKILL.md" && ! grep -q -e 'install ope[n] ' -e 'from the setup pag[e]' -e 'Restart the OpenWiz serve[r]' "$d/install/SKILL.md" "$d/install"/scripts/*.py; then
         echo "ok: $d/install"
       else
         echo "STILL OLD: $d/install" >&2; failed=yes
       fi
     done
     [ "$failed" = no ]
   fi
   ```

   If `SOURCE MISMATCH` or `STILL OLD` appears, stop before restarting and tell the user; never restart onto the 0.1.0 archive's `0.2.0` copy. Once every installed folder prints `ok:`, restart the agent and say `continue the OpenWiz install`.
