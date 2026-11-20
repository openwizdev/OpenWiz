# The demo project

What OpenClaw builds for proof B1 of spec #1365: a greenfield project, from an empty repository to merged pull requests. Every name below is a proposal; Jake chooses the real ones when he runs it ([steps.md](steps.md)), and they stay private until the evidence is sanitized.

## Two repositories

| Repository | Visibility | Holds |
| --- | --- | --- |
| `<owner>/lakers-page` | Public (Jake's choice) | The page, its tracker (spec, tickets, status notes, pull requests, reviews) and its `docs/agents/` settings |
| `<owner>/lakers-page-records` | Private | The grill with Jake's exact answers, the private-record comments approvals point to, and launch-fleet's thread, loop and run maps |

The records repository is what [`setup`](https://github.com/openwizdev/WizSkills/blob/v0.2.0/skills/setup/SKILL.md) asks for as "the verified private repository"; a fleet can't run without one.

## The project

A one-page Lakers fan site: plain HTML, CSS and a little JavaScript, no build step and no dependencies, served by GitHub Pages or opened as a file. Small enough that a fleet finishes it in one sitting, real enough to need a spec, several tickets, a blocker and reviews.

The grill decides the details. A spec of about this shape is expected:

| Ticket | Builds | Blocked by |
| --- | --- | --- |
| 1 | The page's skeleton (`index.html`, `style.css`), and `check.sh`: a tiny check that the page's links resolve and its HTML is well-formed, run in CI | none |
| 2 | The roster section, rendered from `data/roster.json` | 1 |
| 3 | The schedule section, rendered from `data/schedule.json` | 1 |
| 4 | Phone and desktop layout, and an accessibility pass (headings, contrast, alt text) | 2, 3 |

No team logos, photos or scraped data: the data files are written by hand, so nothing on the page needs a licence.

## What the run uses

- **Orchestrator:** OpenClaw, on Jake's own Linux computer or VPS, with WizSkills v0.2.0 loaded. It runs `setup`, `grill`, `to-spec`, `to-tickets` and `launch-fleet` exactly as any orchestrator would.
- **Host:** `docs/agents/host.md` says `Host: local`, so launch-fleet starts each builder through OpenWiz's [local driver](../../../adapters/local/README.md) on that same machine (records v1, section 6).
- **Builders:** Claude Code through the local driver, with the `build-ticket` skill.
- **Reviewers:** launch-fleet still starts reviewers with `room-cli` (KN6 changed only builders), so the machine needs a signed-in `room-cli` too.
- **GitHub identity:** whatever the run's `docs/agents/fleet.md` names: Jake's own login today, or his GitHub App if he installs it on the demo repository (spec #1365, G1).

## Done means

The ticket's two acceptance criteria, checked on the run's records with [template.md](template.md):

1. One recorded run with a grill, a spec, the plan checks, builders, reviews and merged pull requests, and status notes throughout.
2. Nothing private in the evidence, and Jake signed in wherever a login was needed.
