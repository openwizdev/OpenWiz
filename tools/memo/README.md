# MeMo tool

Experimental, off by default. An agent asks a Memory model at an operator-configured OpenAI-compatible endpoint (`OPENWIZ_MEMO_ENABLED=1` and `OPENWIZ_MEMO_ENDPOINT`, with optional `OPENWIZ_MEMO_API_KEY`), and document retrieval is the default and the fallback. The design, operator controls, and build steps are in [docs/memo.md](../../docs/memo.md).

```sh
python3 -I tools/memo/memo.py status
python3 -I tools/memo/memo.py ask -- "Which ticket owns the fleet merge?"
python3 -I tools/memo/memo.py build --corpus docs
python3 -I tools/memo/test_memo.py
```

Upstream is [MeMo](https://github.com/arunv3rma/MeMo) (MIT). This folder does not copy that code. `memo-build.sh`, written by `build --execute`, verifies or clones the pinned commit and trains on an independently prepared `reflection-qa.json` only when `OPENWIZ_MEMO_TRAIN=1`, keeping Weights & Biases telemetry disabled unless `OPENWIZ_MEMO_WANDB=1`.
