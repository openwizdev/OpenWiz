+++
channel = "indie-hackers"
scheduled_pt = "2026-12-08 10:15"
title = "I let coding agents run my project's tickets end to end. Here's what I had to build first."
links = ["https://github.com/openwizdev/OpenWiz"]
media = []
status = "draft"
posted_link = ""
claims = []
review_notes = """
Draft only. Agents drafted this file; only the owner approves it and posts it by hand from the owner's own account. Nothing here is posted, scheduled or uploaded.

Rules: https://www.indiehackers.com/terms and https://www.indiehackers.com/post/how-do-you-make-a-successful-post-on-indie-hackers-f6745260fd (read 2026-11-28). The post is a build story that teaches something (four lessons from building the coordination layer), keeps the useful detail in the post rather than behind a link, has one repository link at the end, and closes on a specific question. It is a single post by the owner: no bulk outreach, no reposting across groups.

Claims: the copy describes OpenWiz as the repository README describes it today and makes no release claim, so claims is []. Before approving, the owner may add a sentence copied verbatim from the 0.2.0 changelog entry and list it in claims. The date is a placeholder until the runbook (LS7) fixes launch day.

Owner handoff: rewrite any sentence that does not sound like you and keep the disclosure line.
"""
+++

I'm building OpenWiz, a free, open-source kernel for agent factories. You answer a few questions and approve a plan; coding agents write the spec and the tickets, build each one, review it and merge it. This post is about the part that surprised me: the agents were never the hard part. The coordination around them was. I drafted this with help from those agents and edited it myself.

## Where it started

I was using coding agents on real work and kept becoming the glue. I wrote the tickets, started each agent, read every diff, and decided what could merge. My throughput was capped by how many context switches I could take in a day.

## What I had to build first

**1. A place for the factory to remember things.** I put every spec, ticket and status note in plain GitHub issues, under written rules. No database, no server of mine. Anyone, or any tool, that follows the rules can read and write the factory. That one decision made the project easy to inspect, because the whole history is public.

**2. A tiny contract for "where agents run."** Each host gets a driver: a small program in any language that answers four commands, `version`, `start`, `wake` and `stop`. Your own computer, a hosted sandbox, whatever you have. Keeping the contract that small is what made new hosts cheap.

**3. Fences instead of longer prompts.** Each ticket lists the exact files it may change. The builder writes a failing test first, then the change, then one draft pull request. Tight scope fixed more bad behaviour than any prompt rewrite I tried.

**4. A second opinion from a different model.** If you have both Claude Code and Codex, the reviewer is from the other family, and a ticket merges only when that review approves and CI is green. The two families miss different things.

## What I'd tell someone starting the same thing

Decide what "stop" looks like before you decide what "go" looks like. Agents that are allowed to say "blocked, here's why" waste far less of your time than agents that are pushed to always finish.

The project builds itself in public, so you can read the real pull requests, including the ones that went wrong: https://github.com/openwizdev/OpenWiz

My question for other builders using AI agents: what is the one decision you still refuse to hand to an agent, and why that one?
