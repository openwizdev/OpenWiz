+++
channel = "reddit"
scheduled_pt = "2026-12-08 10:00"
title = "OpenWiz Reddit drafts: r/sideprojects and r/ClaudeCode"
links = ["https://github.com/openwizdev/OpenWiz"]
media = []
status = "draft"
posted_link = ""
claims = []
review_notes = """
Draft only. Agents drafted this file; only the owner approves it and posts each post and every reply by hand from the owner's own account. No bot account, no second account, no automation, no vote requests, no vote trading, no coordinated voting. Nothing here is posted, scheduled or uploaded.

One file holds one draft per eligible subreddit on the Reddit list (docs/launch/reddit-communities.md, read 2026-11-28), each under its own heading with its title, flair and time. The header title is a kit label; post the title under each heading. Both dates are placeholders until the runbook (LS7) fixes launch day; keep Reddit after TikTok and Shorts at 9 AM PT and keep the two posts at least ninety minutes apart, so the same promotion is never repeated across communities in quick succession.

Claims: both posts describe OpenWiz as the repository README describes it today and make no release claim, so claims is []. Before approving, the owner may add up to two sentences copied verbatim from the 0.2.0 changelog entry and list each one in claims.

r/sideprojects: rules https://www.reddit.com/r/sideprojects/about/ (rules 1, 2, 4, 5 and 6, read 2026-11-28). Self-promotion rule: the post is a substantive showcase that discloses the owner's role in its first line, explains the problem and the implementation, and links only to the repository, with no ads, affiliate links or DM funnel. Frequency rule: this is OpenWiz's first post there; share again only after a significant update. Flair rule: flair is required, so post with `Showcase: Open Source` (the repository is Apache-2.0). Title rule: none stated; the title says what the project does. Participation rule: the owner answers comments and takes part beyond this post.

r/ClaudeCode: rules https://www.reddit.com/r/ClaudeCode/about/ (rules 1-6, read 2026-11-28) and https://www.reddit.com/r/ClaudeCode/comments/1y3g07r/weekly_showcase_thread_what_are_you_building_with/. Self-promotion rule: a standalone showcase must focus on Claude Code and explain what was built, how Claude Code was used and what was learned; this draft is centred on the Claude Code builder workflow with a worked example and three lessons, with no disguised ad, referral link or affiliate code. If the owner judges it a simple project share instead, cut it to the first two paragraphs and post it as a reply in that week's showcase thread, with no flair. Frequency rule: the weekly thread runs every 7 days and repeated promotion is prohibited; this is one standalone post, not repeated. Flair rule: flair is required for a standalone showcase, so post with `Built with Claude`. Title rule: none stated; the title names the Claude Code workflow so its relevance is clear.

r/opensource: skipped, no draft. Rule 3 bars AI-generated content and the launch copy is agent-drafted (https://www.reddit.com/r/opensource/about/).

r/programming: skipped, no draft. Rule 5 bans product promotion and "I made this" demo posts, and the rules prohibit LLM-written content (https://www.reddit.com/r/programming/about/).

r/selfhosted: skipped, no draft. A general release announcement has no demonstrated self-hosting use case and does not qualify for the Wednesday exception (https://www.reddit.com/r/selfhosted/about/).

Owner handoff: rewrite any sentence that does not sound like you, keep the disclosure lines, check each subreddit's current rules and your own recent activity there on the day, then set status and posted_link yourself.
"""
+++

## r/sideprojects

Flair: `Showcase: Open Source`
Post: 2026-12-08 10:00 PT

### Title

OpenWiz: an open-source kernel that lets coding agents run a small software factory on GitHub

### Post

I'm the maintainer of OpenWiz, and I drafted this post with help from the same agents it runs.

**The problem.** I kept handing coding agents bigger jobs and then spending my time as the glue: turning an idea into tickets, starting each agent, checking what it changed, and deciding what could merge. The agents were fine at the work. The coordination was the bottleneck.

**What OpenWiz does.** You answer a few questions and approve a plan. Agents then write the spec and the tickets, build each ticket, review it and merge it, and you watch it ship. Nothing starts until you approve the plan.

**How it's built.** The kernel is small and has three parts:

- **Records on GitHub.** Specs, tickets and one status note per agent live in the repo's issues, under written rules, so anything that follows the rules can read and write the factory.
- **Drivers.** A driver is a tiny program in any language that answers four commands: `version`, `start`, `wake` and `stop`. The release carries drivers for your own computer and two hosted options, and a template for your own host.
- **Test kits.** One checks the records and one checks a driver on its real host.

Each ticket lists the paths it may change. A builder agent writes a failing test first, makes the change and opens a draft pull request. A reviewer from another model family (Claude Code or Codex) reviews that exact commit, and it merges only when the review approves and CI is green. OpenWiz never touches a login: your agents use their own signed-in tools, and there is no server of ours.

OpenWiz builds itself, in public, in its own repository, so you can read the pull requests its agents wrote and reviewed and see how it really behaves, mistakes included.

Code (Apache-2.0): https://github.com/openwizdev/OpenWiz

I'd like feedback on one design choice: keeping every factory record in plain GitHub issues instead of a database. Where do you think that breaks down first?

## r/ClaudeCode

Flair: `Built with Claude`
Post: 2026-12-08 11:30 PT

### Title

How I run Claude Code as a ticket-by-ticket builder with a reviewer from another model family

### Post

I maintain OpenWiz, an open-source kernel for agent factories. Claude Code is one of its two builder families, so here is how a Claude Code session fits in and what I've learned from it. I drafted this with help from the agents and edited it myself.

**What the Claude Code session gets.** One ticket. The ticket says what to build, lists the exact paths the session may change, and gives acceptance criteria. The session is told to confirm the ticket's blockers are merged and that no pull request for it already exists, and to stop if not.

**What it does.** It writes a failing test for the acceptance criteria first, makes the change, and opens one draft pull request. The pull request body names its builder model, so the reviewer knows which family wrote it. It never merges, approves, tags or publishes.

**Who checks it.** When you have both Claude Code and Codex signed in, a reviewer from the other family reviews that exact commit. With only one, it's a same-family review, and it's labelled that way. A ticket merges only when the review approves and CI is green.

**A worked example.** This post came from a ticket like that. The session got two owned paths, a list of subreddits with each one's rules, and the instruction to draft only. It wrote its own check of the acceptance criteria first, watched it fail, then wrote the drafts, and I'm the one who read your sub's rules again and hit post.

**Lessons so far:**

1. Owned paths matter more than prompts. A Claude Code session with a short list of files it may touch makes far fewer surprising changes than one with a long, careful prompt.
2. "Stop and report" needs to be a normal, successful outcome. When a session can say "blocked" without failing, it stops inventing workarounds.
3. Cross-family review catches different things. Each family tends to miss its own habits and spot the other's.

Repo: https://github.com/openwizdev/OpenWiz

If you run Claude Code on scoped tickets: how do you tell it which files it may touch, and does it respect the limit?
