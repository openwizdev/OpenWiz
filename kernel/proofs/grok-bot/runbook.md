# Grok Bot run: the demo repository plan and the owner's steps

For #1396's live run, held until after 2026-11-21. Everything here is done by the owner, Jake, with his own sign-ins and spending. No agent of #1396 handles a credential. Angle brackets are values Jake chooses. Allow about two hours: 10 minutes for step 0, 30 for setup, then the run itself.

## The demo repository plan

| What | Plan |
| --- | --- |
| Demo repository | `<account>/openwiz-grok-demo`, **public** (the evidence links to it), MIT, made with a README so it has a `main` |
| Private records | `<account>/openwiz-grok-demo-records`, **private**: the grill, the private records and launch-fleet's thread, loop and run maps |
| The tiny spec | Suggested for the grill: a `greet.py` that prints `Hello, <name>!`, then a `--shout` option. That should plan into two small tickets, the second blocked by the first. The grill decides; this only keeps it tiny |
| CI | One workflow, `ci`, running `python3 -m unittest` (below). Jake commits it himself, because agents never push workflow files |
| Fleet settings | Builder Claude Code Opus 5.5 Medium, reviewer Codex Sol 6.2 Medium, as OpenWiz's own `docs/agents/fleet.md` |
| Host | `docs/agents/host.md` with `Host: local`: the local driver, on Grok Bot's own computer |
| GitHub identity | Grok Bot's GitHub app acting as Jake's account, limited to these two repositories. The `Record authors` row names Jake's login |

## 0. Check Grok Bot's computer can host the driver (10 minutes, before any setup)

The local driver needs Linux, Python 3.11 or later, and `claude`, `codex`, `gh` and `room-cli` signed in on the machine where it runs. Ask Grok Bot to run these and show the output:

```sh
uname -s; python3 --version; claude --version; codex --version; gh --version; room-cli --version
```

Anything missing that the Bot can't install: stop, and say so on #1396. The run needs another plan, and nothing else is set up yet.

## 1. Sign-ins (Jake only)

On Grok Bot's computer, in its terminal, Jake signs in himself: `claude` (run it once and log in), `codex login`, `gh auth login` (as his own account), and `room-cli`'s sign-in. In the Grok Bot app, connect GitHub to the two repositories only. Never paste a key or token into the chat.

## 2. The repositories

1. Create both repositories on GitHub: the demo repository public with a README, the records repository private.
2. In the demo repository, add `.github/workflows/ci.yml` yourself:

   ```yaml
   name: ci
   on: [pull_request, push]
   jobs:
     ci:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - run: python3 -m unittest discover -v
   ```

3. Turn on branch protection for `main` requiring the `ci` check.

## 3. Skills and the driver on Grok Bot's computer

Ask Grok Bot:

> On your computer, run `git clone --depth 1 --branch v0.2.0 https://github.com/openwizdev/WizSkills ~/wizskills` and `git clone --depth 1 https://github.com/openwizdev/OpenWiz ~/openwiz`. Save each `skills/<name>/SKILL.md` in `~/wizskills` as a skill, and always run a skill's scripts from that folder. Never edit them.

Then, in the Bot's terminal, Jake sets the driver's approval for builders (`<mode>` is a `claude --permission-mode` value he chooses; an unattended builder needs one that lets it run its commands, such as `bypassPermissions`, which is safe enough only on this demo repository):

```sh
mkdir -p ~/.local/state/openwiz-local && chmod 700 ~/.local/state/openwiz-local
printf '{"<account>/openwiz-grok-demo": {"claude": "<mode>"}}\n' > ~/.local/state/openwiz-local/approvals.json
chmod 600 ~/.local/state/openwiz-local/approvals.json
```

## 4. Set up the demo repository

Ask Grok Bot:

> Use the setup skill on `<account>/openwiz-grok-demo`, with `<account>/openwiz-grok-demo-records` as the private repository.

Answer its questions with the plan above (builder and reviewer, record authors `<your login>`, test command `python3 -m unittest discover -v`, CI check `ci`). Then ask:

> In `docs/agents/fleet.md`, add the row `| Harness permission mode | `<mode>` |`, and add `docs/agents/host.md` holding the line `Host: local`. Open a pull request for that and merge it once CI is green. Whenever you run launch-fleet, set `OPENWIZ_ADAPTERS` to `~/openwiz/adapters`.

Setup reads the CI workflow from step 2, so add that first. It opens its own pull request; let the Bot merge it once CI is green.

`<mode>` must be exactly the value in `approvals.json`, or the driver refuses to start.

Optional, and recommended: have the Bot run the driver kit on a throwaway ticket first, as `~/openwiz/adapters/local/README.md` says. A pass there means the driver can start builders on that machine.

## 5. The run

Ask Grok Bot, one at a time, and answer what it asks:

1. > Use the grill skill on: a tiny greet.py for `<account>/openwiz-grok-demo`.
2. > Use to-spec on the confirmed grill.
3. > Use to-tickets on the spec.
4. > Use launch-fleet to launch the approved plan graph.
5. Until every ticket's pull request has merged: > Run launch-fleet's wake for `<account>/openwiz-grok-demo`. (Every 10 minutes or so, by hand or with the Bot's own scheduling if it has one.)

Don't fix anything by hand during the run. If something breaks, note where, and let the Bot handle it with the skills, or stop and say so on #1396. A run that needed a hand fix is evidence of a gap, not of the claim.

## 6. Hand it back

Comment on #1396 that the run is done, with the demo repository's name. The builder then runs `collect.sh` and opens the pull request. Afterwards, Jake can revoke Grok Bot's GitHub access and the sign-ins on its computer, and archive the demo repositories.
