# Your first hour with OpenWiz

The aim: install OpenWiz, give it one small idea for your own repository, and
see your first pull request reviewed, checked and merged within an hour.

**Status:** a real first hour, and how long it takes, are not yet verified.

## What happens, in order

Your coding agent walks you through the install and onboarding road in chat,
and you can watch the fleet on GitHub or in the web app at
[openwiz.dev/app](https://openwiz.dev/app/):

1. **Install OpenWiz.** Paste the one install line into your coding agent; see
   [Install OpenWiz](install.md) (for the published 0.1.0 release, follow its
   [OpenWiz 0.1.0](install.md#openwiz-010) section).
2. **Pick a host and connect GitHub.** Choose where your agents run: **this
   computer**, **boat.dev**, or **CloudRoom** (CloudRoom is optional). Your
   installing agent checks each connection on its own (`setup.py check` and
   `github_login.py`), sets the acting GitHub identity (your personal GitHub
   login or your own OpenWiz App), and initializes the project's private brain
   (`openwiz init`).
3. **Give your first idea.** Your installing agent continues through
   [the install skill's onboarding road](https://github.com/openwizdev/WizSkills/blob/v0.5.0/skills/install/SKILL.md#6-the-onboarding-road)
   with one repository (a new demo repository or one of yours). It grills you
   briefly in one short round, and you confirm the grill summary.
4. **Plan and approve the start.** For your first fleet, the plan checks itself
   (no manual spec or plan approval), then your agent previews the start —
   naming the host and what it can cost. Nothing starts until you say yes to
   that preview.
5. **Watch the fleet build.** Builders and reviewers run on the host you chose
   (on this computer via the session runner or optional local heartbeat, on
   boat.dev via the local heartbeat, or in CloudRoom via a fleet thread's loop;
   on 0.1.0 without CloudRoom you start builders by hand). Follow progress on
   GitHub or at [openwiz.dev/app](https://openwiz.dev/app/). See
   [How OpenWiz works](how-openwiz-works.md).
6. **First verified merge.** A merge counts as verified only when GitHub
   reports the pull request merged and the merge commit has been read back on
   its base. A closed pull request or a progress count is never a verified
   merge.

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
