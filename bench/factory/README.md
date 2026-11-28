# Factory bench runner

`bench/factory/run.py` prepares disposable benchmark tickets and scores merged results under [`contracts/factory-bench.v1.md`](../../contracts/factory-bench.v1.md). It uses only the Python standard library and the owner's signed-in `gh`.

## Prepare disposable tickets

Preview the number of disposable repositories and the cap-based cost estimate without creating anything:

```sh
python3 -I bench/factory/run.py prepare <version> --owner <account>
```

Create one private disposable repository (`openwiz-bench-<version>-<id>`) and one ticket per task after confirming the estimate:

```sh
python3 -I bench/factory/run.py prepare <version> --owner <account> --yes
```

`prepare` starts no agents; the fleet runs on those tickets through `launch-fleet` as usual.

## Score merged results and clean up

Judge each task's merged pull request with its timeout, write `bench/factory/results/<version>.json`, and delete (or archive when deletion is refused) every disposable repository:

```sh
python3 -I bench/factory/run.py score <version> --owner <account>
```

Any task with no merged pull request within its wall-clock cap is recorded as `unproved: not merged`.

## Offline tests

Run the fixture suite with no real network, tokens, or GitHub account:

```sh
python3 -I bench/factory/test_run.py -v
```
