# GitHub repository settings for 0.2.0

Status: draft. Nothing has been changed and nothing has been posted. This is a checklist for the owner to approve and apply. No agent changed a repository's settings.

Destination: the About panel (description, website and topics) of each public repository under https://github.com/openwizdev, and the organisation's profile. Every description uses the one consistent name, OpenWiz, the open source agent factory. Every repository's website points back to https://openwiz.dev/. Private repositories are out of scope and are not named here.

## Rules, read 2026-11-28

- GitHub Docs, [Classifying your repository with topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics). Only repository admins add topics. A topic uses lowercase letters, numbers and hyphens, is 50 characters or less, and a repository has no more than 20 topics. Topic names are always public.
- GitHub Docs, [Customizing your organization's profile](https://docs.github.com/en/organizations/collaborating-with-groups-in-organizations/customizing-your-organizations-profile) and [Verifying or approving a domain for your organization](https://docs.github.com/en/organizations/managing-organization-settings/verifying-or-approving-a-domain-for-your-organization).
- GitHub Docs, [Update a repository](https://docs.github.com/en/rest/repos/repos#update-a-repository). Changing a description, website or topics needs the Administration permission on the repository.
- The launch kit's GitHub rule in [the launch post kit](../../README.md#channel-rules): engagement stays genuine, and no stars are bought, traded or automated.

## What the factory's token can't change

The factory's GitHub App (`tools/github-app/manifest.json`) holds metadata read, contents write, issues write, pull requests write, checks read and actions read. It has no Administration permission and no organisation permission. So every change below is the owner's to make by hand, and none of it is an agent's.

Owner steps for each repository:

1. Open the repository's main page and choose the gear beside About.
2. Replace Description with the text below.
3. Set Website to the address below.
4. Make Topics match the list below. Remove any topic that is not listed and add the missing ones.
5. Save changes, then reload the page to check the result.

Owner steps for the organisation:

1. Open the organisation's settings, then Profile.
2. Set Description to OpenWiz, the open source agent factory. Leave the display name as OpenWiz and the URL as https://openwiz.dev.
3. Under Verified and approved domains, add openwiz.dev and publish the DNS TXT record GitHub shows. Then the profile shows the domain as verified. This is optional, and the DNS change is the owner's.

## OpenWiz

- **Description:** OpenWiz, the open source agent factory: run fleets of coding agents like Claude Code and Codex on your own machines. Your agents, your machines, your rules.
- **Website:** https://openwiz.dev/
- **Topics (20):** agent-factory, agent-orchestration, agentic-coding, ai, ai-agents, claude-code, cli, cloudroom, code-review, codex, coding-agents, developer-tools, github, llm, multi-agent, open-source, openwiz, rust, self-hosted, software-factory
- **Change from today:** drop `kernel` and `openclaw`, add `agentic-coding` and `self-hosted`. `openclaw` is another project's name and invites confusion. `kernel` describes the code but is not what people search for.

## WizSite

- **Description:** The site of OpenWiz, the open source agent factory: openwiz.dev, its drivers, changelog and app.
- **Website:** https://openwiz.dev/
- **Topics (8):** agent-factory, cloudflare-pages, landing-page, open-source, openwiz, seo, static-site, website

## WizMarket

- **Description:** The marketplace registry for OpenWiz, the open source agent factory: one small file per listing, added by pull request.
- **Website:** https://openwiz.dev/
- **Topics (6):** agent-factory, marketplace, open-source, openwiz, plugin-registry, registry

## WizSkills

- **Description:** The standard skills of OpenWiz, the open source agent factory: grill, plan, build, review and run a fleet of coding agents.
- **Website:** https://openwiz.dev/
- **Topics (9):** agent-factory, agent-skills, ai-agents, claude-code, codex, coding-agents, open-source, openwiz, software-factory

## WizPlugins

- **Description:** Plugins for OpenWiz, the open source agent factory, in the tools you already use, starting with WizBar for CloudRoom.
- **Website:** https://openwiz.dev/
- **Topics (6):** agent-factory, cloudroom, coding-agents, open-source, openwiz, plugins
- **Also check:** GitHub shows no detected licence for this repository, although it has a `LICENSE` file. If the intended licence is a standard one, the owner makes the file match that licence's standard text so GitHub can detect it. That is a change to the repository's content, not to its settings, so it needs its own ticket.

## WizLoops

- **Description:** Wake-ups for OpenWiz, the open source agent factory: Markdown files that run on any host.
- **Website:** https://openwiz.dev/
- **Topics (11):** agent-factory, ai-agents, cloudroom, coding-agents, cron, github-actions, loops, markdown, open-source, openwiz, scheduling

## todo-demo

- **Description:** A to-do app built end to end by OpenWiz, the open source agent factory: grill, spec with its narrated video, tickets, builders and reviews.
- **Website:** https://openwiz.dev/ (empty today)
- **Topics (6):** agent-factory, coding-agents, demo, openwiz, open-source, todo-app (none today)

## .github

- **Description:** The organisation profile of OpenWiz, the open source agent factory.
- **Website:** https://openwiz.dev/
- **Topics (2):** openwiz, open-source (none today)

## marketplace

- **Today:** its description calls it a registry for a plugin marketplace that is not OpenWiz's, and it has no website or topics.
- **Owner decision:** if it belongs to OpenWiz, set Website to https://openwiz.dev/ and Topics to openwiz, and write a description that names OpenWiz, the open source agent factory. If it does not, leave its settings alone and decide separately whether it stays in the organisation. This checklist proposes no wording for it until then.

## Outside this checklist

- Spec #3513 also asks that the driver template link back to openwiz.dev. The template lives in `adapters/template/` in this repository and has no openwiz.dev link today. That is a content change, so it needs its own ticket.
- Profile README, social preview image and pinned repositories are left as they are.

## Owner checklist

- Apply the settings above after the 0.2.0 release is out, so the descriptions match what has shipped.
- After saving each repository, reload it and compare the About panel with this file.
- Ask nobody for stars. Leave stars to people who use OpenWiz.
- Afterwards, note in a follow-up pull request which items were applied and on what date.
