# MeMo, experimental

MeMo ("Memory as a Model") is an opt-in way for an agent to ask a small Memory model about a corpus. The Memory model was fine-tuned on reflection questions and answers, and at inference it answers from its weights. It does not see the source documents, and its answers have no source provenance.

This is off unless you turn it on. Retrieval over the project's docs, and over the private brain when that folder exists, stays the default and is the fallback when the Memory model is off, unreachable, or returns nothing.

The tool is [MeMo](https://arxiv.org/abs/2605.15156) ([code](https://github.com/arunv3rma/MeMo), MIT; [blog](https://arunv3rma.github.io/blogs/memo/); [checkpoints](https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model)). OpenWiz does not vendor that repository. The wrapper is `tools/memo`. It is not in the release package.

## Where it plugs in

OpenWiz already has three knowledge paths. There is no component named WizMemory.

- **GitHub is the factory's memory.** Specs, tickets, pull requests and reviews are the records `openwiz fleet tick` re-reads. MeMo does not replace them. See [How OpenWiz works](how-openwiz-works.md).
- **The private brain** (`.openwiz/brain`, written by `openwiz init`) holds grills, decisions and `settings.json`. That is the project's private knowledge store. Retrieval reads it when `include_brain` is true and the folder is there. The brain settings schema is unchanged.
- **Ask a Wiz** (`contracts/ask-a-wiz.v1.md`) ranks passages from the public docs for the website FAQ. Its own switch stays off until `ASK_A_WIZ` is `on`. MeMo does not call it.

The executive is whatever harness and model the fleet already starts: the Models table in `docs/agents/fleet.md`, or any other driver harness. MeMo is a tool that executive runs. It does not pick a model, and the request it sends to the Memory model names no harness. One OpenAI-compatible chat endpoint serves the Memory model, so the same tool works for every executive OpenWiz can start.

Ghost text is a different engine (autocomplete). This tool does not touch it.

## Enable it

`docs/agents/memo.json` ships with `"enabled": false`. A missing file is the same as that default: `ask` reads the corpus and does not open a connection.

1. Serve a MeMo checkpoint with an OpenAI-compatible server, for example vLLM:

   ```sh
   python3 -m vllm.entrypoints.openai.api_server \
     --host 127.0.0.1 --port 8000 \
     --model <checkpoint> \
     --served-model-name memo
   ```

   `<checkpoint>` is a directory this build wrote, or a model from the Glow-AI MeMo collection. Serving is outside OpenWiz and needs a GPU.

2. In `docs/agents/memo.json`, set `enabled` to `true`, `endpoint` to `http://127.0.0.1:8000/v1`, and `model` to the served name (`memo` above). `fallback` stays `retrieval`. `experimental` stays `true`.
3. If the server wants a bearer token, set `api_key_env` to the name of an environment variable (`OPENWIZ_MEMO_API_KEY`). Put the token in the environment, not in the file. The file refuses a URL that already contains a username or password.

`python3 -I tools/memo/memo.py status` prints the choice and does not call the endpoint.

## Ask

Any agent runs one sub-query per call:

```sh
python3 -I tools/memo/memo.py ask -- "Which ticket owns the fleet merge?"
```

Stdout is one JSON document, `openwiz.memo.answer.v1`.

- `backend` `memo`: the Memory model answered. `provenance` is null and `sources` is empty.
- `backend` `retrieval`: the default, or the fallback after `endpoint_error` or `empty`. Passages are ranked by how many of the question's words they share. `provenance` lists the files, and `sources` holds the passages. A question the corpus does not cover says so.

The executive keeps the reasoning. The MeMo protocol is three stages, all as calls to this command, then an answer the executive writes itself:

1. Grounding: short sub-queries about the facts.
2. Entity identification: sub-queries that turn a partial description into a concrete name.
3. Answer synthesis: the executive writes the final answer from those replies. The Memory model is not given the source documents.

Run it from the project root, or pass `--root`. `--settings` selects a file other than `docs/agents/memo.json`.

## Build a Memory model

Training is not part of CI and does not run unless you ask on a machine with GPUs. From a checkout of OpenWiz:

```sh
python3 -I tools/memo/memo.py build --corpus docs
python3 -I tools/memo/memo.py build --corpus docs --out /tmp/openwiz-memo --execute
```

`build` with no `--execute` or `--train` prints a plan and writes nothing. The plan names the pinned upstream commit, the MIT licence, and the five synthesis steps: fact extraction, consolidation, verification, entity surfacing, and cross-document synthesis.

`--execute` copies the folder's text and Markdown into `<out>/corpus/`, writes `plan.json`, and writes `memo-build.sh`. It does not clone or train. The script clones [arunv3rma/MeMo](https://github.com/arunv3rma/MeMo) at the pinned commit only when you later set `OPENWIZ_MEMO_TRAIN=1`.

Upstream synthesis is written for its own benchmarks. On a GPU machine, run that checkout's five-step pipeline (`data_synthesis_pipeline/`) so it writes `<out>/reflection-qa.json`. Then:

```sh
OPENWIZ_MEMO_TRAIN=1 python3 -I tools/memo/memo.py build --corpus docs --out /tmp/openwiz-memo --train
```

That runs `sft_training/sft_lora_pipeline.py` on the reflection-QA file, with a small LoRA setup on `Qwen/Qwen2.5-1.5B-Instruct` unless `OPENWIZ_MEMO_BASE_MODEL` names another base. It is a starting point, not the paper's benchmark recipe. The paper's scripts remain in the checkout. Without `OPENWIZ_MEMO_TRAIN=1`, `--train` refuses and does not launch a job. Without `reflection-qa.json`, the script stops before training.

When the corpus changes, train again. The old checkpoint still answers from the previous corpus.

## Limitations

- Experimental, and off by default. The fleet, Ask a Wiz, and the brain settings do not call it.
- Training needs GPUs. CI never sets `OPENWIZ_MEMO_TRAIN`.
- A Memory-model answer has no passage, file, or URL to point at. Use retrieval when you need a source.
- The question is sent to the endpoint in the settings. The corpus stays on this machine. Redirects and proxies are not followed, so a bearer token stays on that host. The question cannot choose a URL.
- `tools/memo` is not an `openwiz` subcommand and is not in `help --agent`, so it stays off the CLI catalogue.

## Experimental changelog line

`changes/` only accepts a ticket number, and this experiment has no ticket, so the line is recorded here and is not gathered into a release.

```text
kind: added

On synthetic fixtures, an experimental MeMo tool can ask a Memory model and falls back to document retrieval when that model is off.
```

## Tests

```sh
python3 -I tools/memo/test_memo.py
```

The tests use a local fake endpoint and a fake `git` and `accelerate`. They do not download a model or run a GPU job.
