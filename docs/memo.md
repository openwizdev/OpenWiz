# MeMo, experimental

MeMo ("Memory as a Model") is an opt-in way for an agent to ask a small Memory model about a corpus. The Memory model was fine-tuned on reflection questions and answers, and at inference it answers from its weights. It does not see the source documents, and its answers have no source provenance.

This is off unless you turn it on. Retrieval over the project's docs, and over the private brain when that folder exists, stays the default and is the fallback when the Memory model is off, unreachable, or returns nothing.

The tool is [MeMo](https://arxiv.org/abs/2605.15156) ([code](https://github.com/arunv3rma/MeMo), MIT; [blog](https://arunv3rma.github.io/blogs/memo/); [checkpoints](https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model)). OpenWiz does not vendor that repository. The wrapper is `tools/memo`. It is not in the release package.

## Where it plugs in

OpenWiz already has three knowledge paths. There is no component named WizMemory.

- **GitHub is the factory's memory.** Specs, tickets, pull requests and reviews are the records `openwiz fleet tick` re-reads. MeMo does not replace them. See [How OpenWiz works](how-openwiz-works.md).
- **The private brain** (`.openwiz/brain`, written by `openwiz init`) holds grills, decisions and `settings.json`. That is the project's private knowledge store. Retrieval reads it when `include_brain` is true and the folder is there, after checking that neither root nor any file escapes the checkout via symlinks. The brain settings schema is unchanged.
- **Ask a Wiz** (`contracts/ask-a-wiz.v1.md`) ranks passages from the public docs for the website FAQ. Its own switch stays off until `ASK_A_WIZ` is `on`. MeMo does not call it.

The executive is whatever harness and model the fleet already starts: the Models table in `docs/agents/fleet.md`, or any other driver harness. MeMo is a tool that executive runs. It does not pick a model, and the request it sends to the Memory model names no harness. One OpenAI-compatible chat endpoint serves the Memory model, so the same tool works for every executive OpenWiz can start.

Ghost text is a different engine (autocomplete). This tool does not touch it.

## Enable it

`docs/agents/memo.json` ships with `"enabled": false` and `"endpoint": null`. A repository checkout cannot switch on outbound requests, choose a destination, or select another environment variable as a bearer token: opt-in and endpoint selection belong solely to the operator's environment.

1. Serve a MeMo checkpoint with an OpenAI-compatible server, for example vLLM:

   ```sh
   python3 -m vllm.entrypoints.openai.api_server \
     --host 127.0.0.1 --port 8000 \
     --model <checkpoint> \
     --served-model-name memo
   ```

   `<checkpoint>` is a directory trained with MeMo, or a model from the Glow-AI MeMo collection. Serving is outside OpenWiz and needs a GPU.

2. Opt in from the operator's environment:

   ```sh
   export OPENWIZ_MEMO_ENABLED=1
   export OPENWIZ_MEMO_ENDPOINT=http://127.0.0.1:8000/v1
   ```

   `http://` is accepted only for loopback hosts (`127.0.0.1`, `::1`, `localhost`). Any non-loopback endpoint must use `https://`. URLs with userinfo, queries, or fragments are refused. Set `OPENWIZ_MEMO_MODEL` if you want to override `model` without editing `docs/agents/memo.json`.
3. If the server wants a bearer token, put it in the dedicated `OPENWIZ_MEMO_API_KEY` environment variable (never in the JSON file). `api_key_env` in `docs/agents/memo.json` accepts only `null` or `"OPENWIZ_MEMO_API_KEY"`; no other environment variable can be sent.

`python3 -I tools/memo/memo.py status` prints the effective operator choice and does not call the endpoint.

## Ask

Any agent runs one sub-query per call:

```sh
python3 -I tools/memo/memo.py ask -- "Which ticket owns the fleet merge?"
```

Stdout is one JSON document, `openwiz.memo.answer.v1`.

- `backend` `memo`: the Memory model answered. `provenance` is null and `sources` is empty.
- `backend` `retrieval`: the default, or the fallback after `endpoint_error` (including truncated HTTP responses) or `empty`. Long paragraphs and paragraph groups are split without dropping trailing text, then ranked by shared question words. `provenance` lists the files, and `sources` holds the passages. A question the corpus does not cover says so.

The executive keeps the reasoning. The MeMo protocol is three stages, all as calls to this command, then an answer the executive writes itself:

1. Grounding: short sub-queries about the facts.
2. Entity identification: sub-queries that turn a partial description into a concrete name.
3. Answer synthesis: the executive writes the final answer from those replies. The Memory model is not given the source documents.

Run it from the project root, or pass `--root`. `--settings` selects a project settings file other than `docs/agents/memo.json` (operator opt-in and endpoint still come from `OPENWIZ_MEMO_ENABLED` and `OPENWIZ_MEMO_ENDPOINT`).

## Stage a corpus and train an independently prepared dataset

Training is not part of CI and does not run unless you opt in on a machine with GPUs. From a checkout of OpenWiz:

```sh
python3 -I tools/memo/memo.py build --corpus docs
python3 -I tools/memo/memo.py build --corpus docs --out /tmp/openwiz-memo --execute
```

`build` with no `--execute` or `--train` prints a plan and writes nothing. The plan names the pinned upstream commit, the MIT licence, and the five stages of the upstream MeMo synthesis design.

`--execute` stages the corpus folder's text and Markdown into `<out>/corpus/` alongside `corpus.json`, `plan.json`, and `memo-build.sh`. It refuses overlapping corpus/output folders and refuses non-empty output folders that contain unmanaged files. It does not clone or train.

`tools/memo` stages documents and runs SFT training on an **independently prepared** `<out>/reflection-qa.json` dataset; it does not run data synthesis or convert Markdown files into upstream benchmark formats. Upstream's `data_synthesis_pipeline/` launchers (`bcp_datasynth_pipeline.sh`, `musique_datasynth_pipeline.sh`, `narrativeqa_datasynth_pipeline.sh`) expect benchmark-specific JSONL inputs and produce named benchmark caches. To train on your own corpus, prepare `<out>/reflection-qa.json` in the shape accepted by pinned `sft_training/sft_lora_pipeline.py` (`extract_qa_pairs`): either a JSON array of records or `{"qa_pairs_cache": [...]}` where each record has `doc_id`, `type` (`"surface"` or `"crossdoc"`), and `qa_pairs` (`[{"question": "...", "answer": "..."}]`).

Then, on a GPU machine:

```sh
OPENWIZ_MEMO_TRAIN=1 python3 -I tools/memo/memo.py build --corpus docs --out /tmp/openwiz-memo --train
```

Without `OPENWIZ_MEMO_TRAIN=1`, `--train` refuses before staging or modifying `<out>`. When enabled, `memo-build.sh` requires `<out>/reflection-qa.json`, clones [arunv3rma/MeMo](https://github.com/arunv3rma/MeMo) at the pinned commit (or verifies that an existing `<out>/MeMo` checkout is a clean, non-symlink Git checkout of that exact remote and pin before reuse), and launches `sft_training/sft_lora_pipeline.py` with a small LoRA setup on `Qwen/Qwen2.5-1.5B-Instruct` unless `OPENWIZ_MEMO_BASE_MODEL` names another base.

Telemetry stays offline by default: `memo-build.sh` sets `WANDB_MODE=disabled`, `WANDB_DISABLED=true`, `WANDB_API_KEY=""`, and `--report_to none` so Weights & Biases login and run metadata upload do not run unless you explicitly opt in with `OPENWIZ_MEMO_WANDB=1`.

When the corpus changes, prepare a fresh dataset and train again. The old checkpoint still answers from the previous corpus.

## Limitations

- Experimental, and off by default. The fleet, Ask a Wiz, and the brain settings do not call it.
- Training needs GPUs and an independently prepared `reflection-qa.json` dataset. CI never sets `OPENWIZ_MEMO_TRAIN`.
- A Memory-model answer has no passage, file, or URL to point at. Use retrieval when you need a source.
- Only operator-configured `OPENWIZ_MEMO_ENABLED=1` and `OPENWIZ_MEMO_ENDPOINT` enable outbound requests, and only `OPENWIZ_MEMO_API_KEY` can be sent as a bearer token. Non-loopback endpoints require HTTPS. Redirects and proxies are not followed. The corpus stays on this machine.
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

The tests use a local fake endpoint and a fake `git` and `accelerate` (plus real `git` checkout-verification cases). They do not download a model or run a GPU job.
