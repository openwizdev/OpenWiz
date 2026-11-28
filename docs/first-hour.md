# Your first hour with OpenWiz

The aim: install OpenWiz, give it one small idea for your own repository, and
see your first pull request reviewed, checked and merged within an hour.

**Status:** a real first hour, and how long it takes, are not yet verified.
The current release is **OpenWiz 0.1.0**; automatic fleets outside CloudRoom
and self-checking first-fleet onboarding arrive in **OpenWiz 0.1.1** (not
released yet).

## What happens, in order

Your coding agent walks you through the published **OpenWiz 0.1.0** install
and first fleet in chat, and you can watch progress on GitHub or in the web
app at [openwiz.dev/app](https://openwiz.dev/app/):

1. **Install OpenWiz.** Tell your coding agent:

   > Install OpenWiz

   That phrase is the whole install instruction. The agent follows
   [Install OpenWiz](../AGENTS.md#install-openwiz). Today's commands are the
   [0.1.0 steps](install.md#openwiz-010).
2. **Pick a host and connect GitHub.** Choose where your agents run: **this
   computer**, **boat.dev**, or **CloudRoom** (CloudRoom is optional). Your
   installing agent checks each connection on its own (`setup.py check` and
   `github_login.py`, plus CloudRoom sign-in only if you chose CloudRoom).
   When connecting a repository for a CloudRoom fleet, it sets the acting
   GitHub identity (your own OpenWiz App or an explicit skip to your personal
   GitHub login) and initializes the project's private brain (`openwiz init`).
3. **Give your first idea.** With CloudRoom, your installing agent continues
   through 0.1.0's
   [first-fleet onboarding](https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md#6-first-fleet)
   with one repository (a new private demo repository or one of yours), then
   grills you briefly (one or two short rounds) until you confirm the grill
   summary. Without CloudRoom (this computer or boat.dev), follow 0.1.0's
   [Without CloudRoom](https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md#without-cloudroom)
   steps to run `setup` and `grill` in your project's clone.
4. **Plan and approve the start.** On 0.1.0 with CloudRoom, your agent writes
   the spec (`to-spec`) and waits for your spec confirmation, cuts 4 to 7 small
   tickets (`to-tickets`) and waits for your exact-plan approval, and then
   previews the launch (naming the fleet thread, loop, builders, reviewer and
   Cloud Credits) and waits for your separate yes to start. Without CloudRoom,
   after you confirm the grill, `to-spec` and `to-tickets` write the spec,
   create the tickets and record the machine plan approval; your agent then
   previews each hand-started builder (naming the repository, ticket, harness,
   model and any charges) and waits for your separate yes before starting it.
5. **Watch the fleet build.** On 0.1.0 with CloudRoom, one fleet thread on a
   CloudRoom Loop starts builders on ready tickets, sends pull requests to an
   independent reviewer from the other model family, and merges approved, green
   work. Without CloudRoom (this computer or boat.dev), you start each builder
   by hand through its driver, and review, wake and merge its pull request
   yourself — no automatic fleet or reviewer starts without CloudRoom on 0.1.0
   (see
   [0.1.0 hand-start instructions](https://github.com/openwizdev/WizSkills/blob/maint/0.2/skills/install/SKILL.md#without-cloudroom)).
   Follow progress on GitHub or at [openwiz.dev/app](https://openwiz.dev/app/).
   See [How OpenWiz works](how-openwiz-works.md).
6. **First verified merge.** A merge counts as verified only when GitHub
   reports the pull request merged and the merge commit has been read back on
   its base. A closed pull request or a progress count is never a verified
   merge.

## OpenWiz 0.1.1 (coming next)

Requires **OpenWiz 0.1.1 or later** (not released yet) with WizSkills `v0.5.0`
— do not use its Connect commands on 0.1.0, where `openwiz models` does not
take `--host`. On 0.1.1,
[the install skill's onboarding road](https://github.com/openwizdev/WizSkills/blob/v0.5.0/skills/install/SKILL.md#6-the-onboarding-road)
adds:

- **Self-checking first-fleet plan:** after one short grill round and your
  confirmation of the grill summary, `to-tickets` checks and approves the
  first-fleet plan itself (no manual spec or plan approval for that first
  fleet); nothing still starts until you say yes to the launch preview naming
  the host and what it can cost.
- **Automatic fleets on every host:** builders and reviewers run on **this
  computer** (via the local session runner in chat, with an opt-in local
  heartbeat to keep running after chat closes), on **boat.dev** (via the local
  heartbeat), or in **CloudRoom** (via a fleet thread's loop).

## When something goes wrong

- **Interrupted:** start a new session of your coding agent and say
  `continue the OpenWiz install`; each step checks what is already done before
  acting. See [If it is interrupted or fails](install.md#if-it-is-interrupted-or-fails).
- **Refused:** nothing took effect. Follow the step's next action.
- **Uncertain result:** if a reply was lost so OpenWiz cannot tell whether a
  step took effect, check its state before retrying and never start it a second
  time.

OpenWiz is free now. Paid plans come later. CloudRoom, boat.dev and model
charges are separate and not included.
