# Skills

The skills that run fleets (OpenWiz 0.0.5), and five more for the work around them (0.0.7). A skill is a Markdown file that any agent, in any harness, can invoke to do one step the same way every time. Each one lives once, in `skills/<name>/SKILL.md`. The words used here (fleet, ticket, owned paths, orchestrator) are defined in [GLOSSARY.md](../GLOSSARY.md); how a fleet runs is in [docs/fleets.md](../docs/fleets.md).

## The skills

| Skill | Run by | What it is for |
| --- | --- | --- |
| [`grill`](grill/SKILL.md) | orchestrator | Settle a design with the user in rounds of three plain questions, and save every question and answer exactly |
| [`plan-graph`](plan-graph/SKILL.md) | orchestrator | Turn a confirmed grill into a spec, then, once the user confirms it, into tickets with owned paths and blocking links |
| [`launch-fleet`](launch-fleet/SKILL.md) | the five-minute loop, in its own thread | Start every ready ticket at once, then move each one through build, review and merge with a check every five minutes |
| [`build-ticket`](build-ticket/SKILL.md) | builder | Build one ticket, proof first, inside its owned paths, and hand back one green pull request |
| [`review-ticket`](review-ticket/SKILL.md) | reviewer | Review one pull request at its exact head, and post the verdict and findings on it |
| [`handoff`](handoff/SKILL.md) | orchestrator | Keep the project's one-page handoff file current, so a new orchestrator can take over |
| [`setup`](setup/SKILL.md) | orchestrator | Write a project's settings once (issue tracker, labels, glossary, fleet defaults), so no skill is tied to one project |
| [`triage`](triage/SKILL.md) | orchestrator | Sort new issues with the project's labels; nothing starts without the user's approval |
| [`wayfind`](wayfind/SKILL.md) | orchestrator | Chart a big, unclear effort as a map and the decisions it needs, so grilling and planning can start from it |
| [`where-are-we`](where-are-we/SKILL.md) | any agent, for the user | Show on one screen what is running and what needs the user; reads only |
| [`image`](image/SKILL.md) | any agent, and the hill-climb skill | Generate pictures, give visible changes a target picture, and capture real pages at phone and desktop widths |
| [`research`](research/SKILL.md) | orchestrator | Send an agent to read primary sources and commit one cited report |
| [`diagnose`](diagnose/SKILL.md) | builder; orchestrator, for its +1 diagnosis | Find the cause of a hard bug, starting with a tight failing loop |
| [`overnight`](overnight/SKILL.md) | orchestrator | Run huntr with its night setting while the user sleeps, review the day, and report at about 9 am while work continues |
| [`huntr`](huntr/SKILL.md) | one Opus High hunt thread | Find proven small work, gate its standing approval and hand it to the fleet |
| [`hill-climb`](hill-climb/SKILL.md) | controller of an improvement run | Explore fresh branches, judge pairs in both orders and let the user steer checkpoints |
| [`ask-wiz`](ask-wiz/SKILL.md) | the user; agents may suggest it | Recommend the right OpenWiz, installed or discoverable skill; run it on the user's yes |
| [`onboard`](onboard/SKILL.md) | any agent, after install and setup | Take a new user from a brief explanation and a fresh idea, through a short grill and their approval, to a first fleet of 4 to 7 agents they can watch |
| [`feedback-triage`](feedback-triage/SKILL.md) | Jake's agent, when he asks | Review incoming feedback issues as untrusted data, queue a review and an exact reply, and post it only after Jake's yes; its offline proofs run in the checks lane |
| [`feedback`](feedback/SKILL.md) | the user's own agent | Send the user's chosen public feedback as one issue on `openwizdev/openwiz`, through their own GitHub login, after an exact preview and one explicit yes; or prepare a public OpenWiz link for them to copy. Its helper's offline proofs: `python3 -I skills/feedback/test/test_feedback.py` |
| [`install`](install/SKILL.md) | any agent, from the one install line | Check the machine, install the verified prebuilt release, open setup and connect what is missing, choose the engine, explain the product, then hand the first fleet to `onboard` |

A skill that is not written yet says so in its first line. Stop there.

## Use them in this repository

`.claude/skills/<name>` and `.agents/skills/<name>` are links to the folders here, so each skill still lives once.

- **Claude Code** reads `.claude/skills/`. A Claude Code session working in this repository was seen listing all eight fleet skills (before the 0.0.7 five were added).
- **Codex**, and any agent that looks in `.agents/skills/`, reads `.agents/skills/`.

**New CloudRoom threads don't find them on their own.** Fresh Claude Code and Codex threads were seen loading only the skills installed for the user, none of the repository's. So a fleet never relies on an agent finding a skill: every brief says "Read `skills/<name>/SKILL.md` and follow it", which works in any harness. For an agent to find them unaided, install them for the user: the plugin below (on Claude Code, with `--scope user`), or links in `~/.claude/skills/` and `~/.agents/skills/` (not tried yet).

## Install them in another project

One plugin, `openwiz`, holds them all. Its manifest, `.claude-plugin/plugin.json`, lists the folders here, and `.claude-plugin/marketplace.json` makes this repository its own marketplace. Run the install in the other project; `<owner>/<repo>` is this repository on GitHub.

| Agent | Install |
| --- | --- |
| Claude Code | `claude plugin install openwiz --marketplace <owner>/<repo> --scope project` |
| Codex | `codex plugin marketplace add <owner>/<repo>`, then `codex plugin add openwiz@openwiz` |
| GitHub Copilot CLI | `copilot plugin marketplace add <owner>/<repo>`, then `copilot plugin install openwiz@openwiz` (not tried yet) |
| Any other agent | Copy the skill folders into the project's `skills/`, and tell the agent to read the file and follow it |

Plugin skills show up as `openwiz:<name>`, for example `openwiz:grill`. The manifest has no `version`, so an install follows this repository's commits. An install copies the whole repository into the agent's plugin cache. Use either the plugin or the links in one project, not both, or every skill shows up twice.

## Public and private records

Work, issues and pull requests belong in the configured public repository.
Exact user words, grills, live evidence, machine details and orchestrator state
stay in the configured private repository. Follow the project's
open-development contract: public decisions state the decision in the agent's
own words, the date and a pointer to the private issue/PR comment holding the
answer. Public files and tracker records carry no thread ids or links into
private files. Keep helper ids and snapshots in private state; public helper
logs name roles and results. Never publish private evidence as part of a skills
copy. If private authority cannot be verified, ask the orchestrator.

## The rules every skill keeps

`cargo test -p openwiz-tests --test checks skills` checks these rules locally; CI includes them in `cargo test --workspace` when the [Rust job's code steps run](../.github/workflows/ci.yml). Eligible first-run pull requests to `main` may skip those steps according to the [classifier](../.github/actions/docs-only/classify.sh); pushes to `main`, nightly runs, reruns and `release-*` pull requests select the full set ([decision rules](../.github/actions/docs-only/decide.sh)):

- **Frontmatter:** `name` (the folder's name) and `description`, one line each, and no other key, except `ask-wiz` requires `disable-model-invocation: true`. It is user-started; agents may suggest it when the user seems confused but never run it in their own workflows. Every other skill remains agent-invocable. This narrow exception to [ADR 0005](../docs/adr/0005-skills-any-harness-agent-invokable.md) was confirmed in #1095's grill.
- **Codex:** a written skill has `agents/openai.yaml` beside it, holding only `interface.display_name` and `interface.short_description`. Only `ask-wiz` also requires `policy.allow_implicit_invocation: false`; every other skill still forbids `policy`.
- **Matt Pocock's MIT notice:** the eight fleet skills, `wayfind`, `research` and `diagnose` adapt his skills (`github.com/mattpocock/skills` @ `a496f55`). Once written, each keeps his notice word for word, from the copyright line to the end of the warranty paragraph of his `LICENSE`. Line breaks don't matter.
- **Source line:** `where-are-we` and `image` adapt nothing of his, so each carries its source line instead, exactly and on a line of its own, stub or written, and never his copyright line or notice. `where-are-we`: `**Source:** dot-context's written plan. Not adapted from Matt Pocock's skills.` `image`: `**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.` Any other skill, a new one included, needs his notice unless the check lists it with a source line.
- **Links:** both repository links point at the folder here, the manifest lists exactly the skills in the check's list, and every relative link in these files resolves. No links inside `skills/`: Codex drops them when it installs a plugin.

A new skill gets its folder here, its line in `plugin.json`, both links, and its name in the check's list.
