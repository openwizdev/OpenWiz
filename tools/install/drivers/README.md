# Driver fetcher

`fetch.py` adds a host that is not a core driver. It is a standard-library
command. Setup does not call it yet.

```sh
python3 -I tools/install/drivers/fetch.py add NAME \
  --root ROOT --build BUILD --market-commit SHA [--answer yes|install-unverified]
python3 -I tools/install/drivers/fetch.py list --root ROOT
python3 -I tools/install/drivers/fetch.py update \
  --root ROOT --build BUILD --market-commit SHA [--answer yes|install-unverified]
```

`--build` is the selected build. Its `runtime/pins.json`, when present, is
the first-party pin file, and `runtime/kernel/driver-kit/schema.json` is the
kit schema the package is checked against. `--market-commit` is the one
recorded WizMarket `main` commit. `--loopback 127.0.0.1:PORT` dials a fake
GitHub at that address; the host of every URL is still checked.

A pin needs no extra answer. A verified listing needs `--answer yes`. A
listed driver needs `--answer install-unverified` after the warning. An
update moves a verified driver from the same repository and publisher and
prints one notice. Any other change asks again.

```sh
python3 -I tools/install/drivers/test_fetch.py
```
