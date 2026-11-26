# MeMo tool

Experimental, off by default. An agent asks a Memory model at an OpenAI-compatible endpoint, and document retrieval is the default and the fallback. The design, the settings, and the build steps are in [docs/memo.md](../../docs/memo.md).

```sh
python3 -I tools/memo/memo.py status
python3 -I tools/memo/memo.py ask -- "Which ticket owns the fleet merge?"
python3 -I tools/memo/memo.py build --corpus docs
python3 -I tools/memo/test_memo.py
```

Upstream is [MeMo](https://github.com/arunv3rma/MeMo) (MIT). This folder does not copy that code. `memo-build.sh`, written by `build --execute`, clones the pinned commit and runs training only when `OPENWIZ_MEMO_TRAIN=1`.
