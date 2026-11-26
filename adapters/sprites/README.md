# Fly Sprites driver
Login: held by Fly.io

Effort: the host can't set it yet (driver v1 has no effort field yet, so every run uses the harness's default effort, and a `start` that names an effort is refused and creates nothing)

**Billing: Claude Code runs on an Anthropic API key, not a Claude subscription.** Claude Code goes through Fly's Anthropic connector, which holds an Anthropic API key and bills your Anthropic account for every request; a Claude Pro or Max subscription can't be used. Codex goes through Fly's OpenAI connector, which holds an OpenAI API key and bills your OpenAI project, or through Fly's Codex connector with your ChatGPT plan, where Fly offers it (it is rolling out, and availability varies by organization). Source: Fly's [connector catalog](https://fly.io/sprites/ecosystem/) (its Anthropic, OpenAI and Codex entries) and [connectors](https://docs.fly.io/sprites/concepts/connectors) docs.

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own [Fly Sprite](https://docs.fly.io/sprites), through your own signed-in `sprite` CLI. One Python file, standard library only, built from [`adapters/template/`](../template/) with the [boat driver](../boat/README.md) as prior art. The harness's key stays in a Fly [connector](https://docs.fly.io/sprites/concepts/connectors), and the Sprites gateway attaches it to each request, so neither the driver nor the Sprite ever holds it.

Each `sprite` command and flag below is in Fly's [CLI reference](https://docs.fly.io/sprites/cli/commands).

| Command | What it does on Sprites |
| --- | --- |
| `start` | `sprite create --skip-console --label openwiz openwiz-<run>`: a new Sprite for the run, with the `openwiz` label that your connectors' access policies match (below). One `sprite exec -s <name>` installs the WizSkills release OpenWiz pins (`wizskills.lock`) in the Sprite, the way the boat driver installs the pinned release. Then the first turn: a local `sprite exec -s <name> -- <harness command>` under the driver's own supervisor. For `claude` the command is `claude -p --session-id <uuid>`, with `ANTHROPIC_BASE_URL` set to the Anthropic connector's gateway URL, `https://api.sprites.dev/v1/gateway/anthropic/<connection id>`. For `codex` it is `codex exec --json`, with `OPENAI_BASE_URL` set to the gateway URL of the connector you chose for Codex, the OpenAI connector or the Codex connector: `https://api.sprites.dev/v1/gateway/<provider>/<connection id>`, where `<provider>` is that connector's own and `<connection id>` is `$OPENWIZ_SPRITES_OPENAI`. The thread id it prints is saved. Fly's [gateway URL](https://docs.fly.io/sprites/concepts/connectors#calling-a-connector-from-a-sprite) names the provider and the connection id as separate parts, and each connector's detail page shows its exact URL. The gateway URL is the only connector value the driver passes. Where a harness refuses to start with no key variable set, the driver sets a fixed placeholder word that is not a key and that the kit's credential check would refuse, never a real key. If any step after the create fails, `start` destroys the new Sprite before it refuses. |
| `wake` | Refused after a driver `stop`, and for an unknown run (driver v1, D5). While the last turn still runs, nothing: that agent is awake and reads the ticket itself. Otherwise a new local `sprite exec` turn with `claude -p --resume <uuid>` or `codex exec resume <id>`: the same agent, with its memory. A paused Sprite wakes on the `exec`, and its disk (with `~/.claude` and `~/.codex`) survives the pause. |
| `stop` | Ends every local process the turns started, then `sprite destroy --force <name>`: the Sprite and its disk are gone for good. Stopping a run that is already stopped answers again (driver v1, D6). |

**Pausing.** A Sprite is active, and billed for compute, while something uses it, and an `exec` command still running counts. About 30 seconds after the last activity it pauses: compute billing stops, and the disk stays ([lifecycle](https://docs.fly.io/sprites/concepts/lifecycle), [idle detection](https://docs.fly.io/sprites/working-with-sprites#idle-detection)). So a running turn, an open `sprite exec`, keeps its Sprite active, and between turns the Sprite pauses on its own. Each turn runs under the driver's own supervisor, so the driver answers at once and `stop` reaches every process the turn started. Locking, saving a run before starting anything for it, and the supervisor follow the [boat driver](../boat/README.md): a wake and a stop take turns, and no run is left with two agents or with one left running.

**No key in, no diagnostic out.** The driver never reads, passes or prints a key (driver v1, N1 to N3). It calls `sprite` with your environment unchanged and sends no GitHub login into the Sprite. The connection ids it reads are not secrets: a connection id only names a connector, and the gateway accepts a call only from a running Sprite that the connector's access policy lets in. A failed `sprite` command answers fixed words that name the failure and its fix; `sprite`'s own text never reaches the driver's answer.

`version` adds `many-at-once` and `own-sandbox` to `can`: every run gets its own Sprite.

## Before the first run (yours to do)

1. Install the [`sprite` CLI](https://docs.fly.io/sprites/cli/installation) (`curl -fsSL https://sprites.dev/install.sh | sh`) and sign in to it yourself: [`sprite login`](https://docs.fly.io/sprites/cli/authentication) signs you in to your Fly.io account in the browser. Use `sprite login -o <org>` to pick the organization the Sprites run in.
2. **Add the connectors,** in the Fly.io dashboard: your organization, then Sprites → Connectors → Add connector ([connectors](https://docs.fly.io/sprites/concepts/connectors), [catalog](https://fly.io/sprites/ecosystem/)). You add the key there, and it never leaves the connector:
   - for `claude`: the **Anthropic** connector, with an API key from the Anthropic Console;
   - for `codex`, one of two: the **OpenAI** connector, with a project API key from platform.openai.com; or the **Codex** connector, with your ChatGPT plan. For the Codex connector, Fly's step is to sign in with ChatGPT when you create a Sprite in its Codex integration, and the connector then keeps that sign-in. Availability varies by organization while Fly rolls it out, so it may not be offered to you yet ([catalog entry](https://fly.io/sprites/ecosystem/#connectors/codex));
   - and the **GitHub** connector, which you authorize through GitHub's own consent screen, for the agent's access to your repositories, issues and pull requests.
3. **Give each connector an access policy** on its detail page (Access Configuration): turn off "Allow all sprites" and set **Sprite Labels** to `openwiz`, the label `start` puts on every Sprite it creates. A connector is deny-by-default: with no policy it refuses every Sprite, and the run's model calls fail with `403 forbidden`. Don't use "Allow all sprites": it lets every Sprite in your organization use the key.
4. **Name the connection,** not the key: set `$OPENWIZ_SPRITES_ANTHROPIC` (for `claude`) to the Anthropic connector's connection id, or `$OPENWIZ_SPRITES_OPENAI` (for `codex`) to the connection id of the OpenAI or Codex connector you chose, shown on its detail page with its gateway URL. The id is not a secret. The key stays in the connector, the gateway attaches it on each request, and the Sprite and the driver never see it.

**Taking the key back.** Deleting a connector stops every future gateway call through it at once; Fly destroys its stored credential ([connector deletion](https://docs.fly.io/sprites/concepts/connectors#list-inspect-delete)). It doesn't stop a Sprite or a turn that is already running. To cut off access, also `stop` every run that uses it (or `sprite destroy` its Sprite), and revoke or rotate the key where it was issued: in the Anthropic Console for the Anthropic connector, in your OpenAI project for the OpenAI connector, with OpenAI for the Codex connector's ChatGPT sign-in, and in your GitHub settings for the GitHub connector's authorization.

`harness` is `claude` or `codex`, the two with a connector above; `start` refuses any other harness before it creates anything.

**Costs:** Sprites bills compute by the second while a Sprite is active, and nothing for compute while it is paused, plus the storage it writes, to your Fly.io organization ([Sprites](https://docs.fly.io/sprites)). `stop` destroys the Sprite, which ends both. The provider bills the model: your Anthropic account for `claude`, your OpenAI project for `codex`, or your ChatGPT plan and its usage limits through the Codex connector.

**Effort:** runs use the harness's default effort, because driver v1's `start` has no effort field yet. A `start` that names an effort is refused, so an effort is never dropped silently. The refusal creates nothing, and its `next` is: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. Each prompt tells the agent to write its status note's model as `<model> default effort`. This line follows the driver: once it takes the effort field (driver v1 after #2558), the `Effort:` line above names the flag.

**Not yet checked live:** how the agent pushes its branch through the GitHub connector (Fly documents the gateway for API calls, not a `git push`), whether Claude Code and Codex answer through the gateway with no key of their own, and whether `codex exec` runs on a ChatGPT plan through the Codex connector's gateway URL. The live check (#2642) answers each and records how the branch was pushed.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/sprites/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
python3 -I adapters/sprites/test_driver.py      # the fixture tests, on a synthetic sprite CLI
```

The kit run creates a real Sprite in your organization and calls the model through your connector, which both cost money; `sprite destroy --force <name>` any Sprite it leaves. `fixtures/bin/sprite` is a synthetic `sprite` CLI, whose `exec` runs a synthetic harness locally.
