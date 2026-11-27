# Your first hour with OpenWiz

The aim: install OpenWiz, give it one small idea for your own repository, and
see your first pull request reviewed, checked and merged within an hour.

**Status:** the local web view and its First hour page were removed; the app
now lives at [openwiz.dev/app](https://openwiz.dev/app), which has no First
hour page. A real first hour, and how long it takes, are not yet verified.

## The six steps

Your installing agent takes you through six steps:

1. **Install OpenWiz.** Paste the one install line into your coding agent; see
   [Install OpenWiz](install.md).
2. **Connect your accounts.** Your installing agent checks each connection on
   its own with `setup.py check` ([Install OpenWiz](install.md), step 3), and
   opens CloudRoom's own sign-in only if you pick CloudRoom. Setup checks your
   agent harness login. It does not check a reviewer from the other model
   family. Once the connections are verified, setup says which identity
   acts: your own OpenWiz App, or your personal GitHub login if you chose to
   skip the App. A skipped App needs nothing more, and there is no engine to
   choose. The private brain is made by your installing agent (`openwiz init`)
   and checked as part of the project.
3. **Give your first idea.** Your installing agent continues through
   [install's onboarding road](../skills/install/SKILL.md#6-the-onboarding-road) with the same repository, or
   give it one small idea in a thread on your project. It grills you briefly.
4. **Confirm the grill.** Your yes to the grill's summary confirms it. The plan
   then checks itself and records its own approval, so you are asked for no
   spec or plan approval. Approving work does not approve spending.
5. **Watch the fleet build.** Builders start only after the plan is approved
   and you say yes to the start, which names the host and what it can cost.
   Ask your installing agent for progress: a count is never a merge. See
   [How OpenWiz works](how-openwiz-works.md).
6. **First verified merge.** A merge shows as verified only when GitHub reports
   the pull request merged and the merge commit has been read back on its
   base. A closed pull request or a progress count is never a verified merge.

## When something goes wrong

- **Refused:** nothing took effect. Follow the step's next action, and your
  drafts stay.
- **Check first:** a reply was lost, so OpenWiz cannot tell whether the step
  took effect. Ask your installing agent to check the operation by its id
  before trying again, and never start it a second time.
- **Failed or unknown:** a read did not answer or answered only in part. Ask
  your installing agent to read it again. Work already running carries on.

For feedback, or a link to share, ask your agent to use the `feedback` skill.
OpenWiz is free now. Paid plans come later. CloudRoom and model charges are
separate and not included.
