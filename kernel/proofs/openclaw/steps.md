# Running the OpenClaw proof: Jake's steps

Everything here needs Jake: his machine, his sign-ins, his new repositories and his answers to the grill. Nothing in it hands a login to OpenWiz: each tool signs in on its own, and no token is pasted anywhere. Names in `<angle brackets>` are his choice ([demo-plan.md](demo-plan.md)). Allow about an hour of wall time, most of it the fleet working on its own.

## 0. The machine

A Linux computer or VPS that stays on during the run. The local driver reads `/proc`, so it does not run on macOS. Check it has Git, Python 3.11 or later, Node 22 or later (for OpenClaw) and `gh`.

## 1. Sign in (Jake, once)

1. `gh auth login`, as Jake, with `repo` scope; check with `gh auth status`.
2. Claude Code: install it and run `claude` once to sign in with the Anthropic account. The builders run as `claude -p` on this machine. Claude is only ever used through Anthropic's own sign-in.
3. `room-cli`, signed in to Jake's CloudRoom: launch-fleet still starts reviewers with it.
4. OpenClaw: install it and run `openclaw onboard --install-daemon`, choosing its model and signing that model in. If the model is Claude, sign in through Anthropic directly, never through another provider.

## 2. Install the skills and the driver

```sh
git clone --quiet --depth 1 --branch v0.2.0 https://github.com/openwizdev/WizSkills.git wizskills-installer
git -C wizskills-installer cat-file tag v0.2.0        # the release record: commit and tree
git -C wizskills-installer rev-parse HEAD 'HEAD^{tree}'  # must print exactly that commit and tree
sh wizskills-installer/install.sh --version 0.2.0 --dest "$HOME/wizskills"
claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.2.0
claude plugin install openwiz@wizskills --scope user   # builders find build-ticket in every fresh clone
git clone --quiet https://github.com/openwizdev/OpenWiz.git "$HOME/openwiz"   # the local driver
```

Load the skills into OpenClaw: in `~/.openclaw/openclaw.json`, set `skills.load.extraDirs` to `["~/wizskills/skills"]` ([OpenClaw's skills config](https://docs.openclaw.ai/tools/skills-config)), then restart the gateway. Unverified on Jake's OpenClaw version: if its `openclaw skills list` doesn't show `launch-fleet`, tell OpenClaw instead to read `~/wizskills/skills/<name>/SKILL.md` for each step, the route [WizSkills' install guide](https://github.com/openwizdev/WizSkills/blob/v0.2.0/docs/install.md#any-other-agent) gives any other agent.

## 3. Create the two repositories

```sh
gh repo create <owner>/lakers-page --public --add-readme
gh repo create <owner>/lakers-page-records --private --add-readme
gh repo view <owner>/lakers-page-records --json isPrivate   # must say true
```

## 4. Choose the builders' permission mode (Jake, once)

The local driver runs a builder only with the mode Jake approved on this machine for this repository (its [README](../../../adapters/local/README.md)). Unattended builders run Git, tests and `gh`, so `acceptEdits` is not enough; `bypassPermissions` is, and belongs only on a machine Jake is content for an agent to use freely.

```sh
export OPENWIZ_LOCAL_STATE="$HOME/.local/state/openwiz-local"
mkdir -p "$OPENWIZ_LOCAL_STATE" && chmod 700 "$OPENWIZ_LOCAL_STATE"
printf '{"<owner>/lakers-page": {"claude": "<mode>"}}\n' > "$OPENWIZ_LOCAL_STATE/approvals.json"
chmod 600 "$OPENWIZ_LOCAL_STATE/approvals.json"
```

The demo repository's `docs/agents/fleet.md` gets the same value in one row, `| Harness permission mode | `<mode>` |`, during step 5.

## 5. Start OpenClaw

Give OpenClaw this message, with the names filled in, in the shell environment above plus `OPENWIZ_ADAPTERS="$HOME/openwiz/adapters"`:

> You are the orchestrator for a new project, `<owner>/lakers-page`, with `<owner>/lakers-page-records` as its private records repository. Use the OpenWiz skills from `~/wizskills/skills/`. Run `setup` first: the host is `local` (write `docs/agents/host.md`), builders are Claude Code (`claude`, model `claude-opus-5-5`), reviewers start with `room-cli`, the record authors are my login (and my GitHub App's bot, if installed), and the harness permission mode is `<mode>`. Then `grill` me about a one-page Lakers fan site (see `kernel/proofs/openclaw/demo-plan.md` in OpenWiz), `to-spec`, `to-tickets` with its plan checks, and once I approve the plan, `launch-fleet`. Keep every exact answer of mine in the records repository only.

Then answer the grill and approve the spec and the plan when asked. Everything after the plan approval runs on its own.

## 6. When the last pull request has merged

Tell the KN7 builder on #1372 (or the orchestrator) that the run is done, with the two repository names. The builder then, without Jake:

1. collects the public repository's records with read-only `gh` calls into a raw folder outside any checkout;
2. runs `python3 -I kernel/records-kit/check.py --repo <owner>/lakers-page` and keeps its output;
3. runs [`sanitize.py`](sanitize.py) with the private literals list (Jake's machine, account and records-repository names, one per line, kept in ClosedWiz), fills in [template.md](template.md) and opens the pull request.

Nothing from the records repository is copied; the evidence points to it with private-record links.

## Undo

The demo repositories are disposable: archive or delete them when the proof has merged. Stop the fleet's loop through `launch-fleet`, then delete `$OPENWIZ_LOCAL_STATE/work/` once no run is live.
