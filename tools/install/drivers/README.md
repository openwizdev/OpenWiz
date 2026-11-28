# Driver fetcher

`fetch.py` adds a host that is not a core driver. It is a standard-library
command. Setup does not call it yet.

```sh
python3 -I tools/install/drivers/fetch.py add NAME \
  --root ROOT --build BUILD --market-commit SHA [--answer yes|install-unverified]
python3 -I tools/install/drivers/fetch.py list --root ROOT
python3 -I tools/install/drivers/fetch.py update \
  --root ROOT --build BUILD --market-commit SHA
```

`--build` is the selected build. Its `runtime/pins.json`, when present, is
the first-party pin file, and `runtime/kernel/driver-kit/schema.json` is the
kit schema the package is checked against. `--market-commit` is the one
recorded WizMarket `main` commit. `--loopback 127.0.0.1:PORT` dials a fake
GitHub at that address; the host of every URL is still checked.

The fetcher checks the build's kit files against `install-manifest.json`
and installs those bytes alongside the drivers. If the root already has
conflicting kit files, the fetcher asks for a fresh private root.

For `add`, a pin needs no extra answer. A verified listing needs
`--answer yes`. A listed driver needs `--answer install-unverified`
after the warning.

Update checks the selected build for a core driver or first-party pin
before looking at WizMarket. An approved listing driver can move to a
newer verified release automatically if its repository and publisher
match. The fetcher prints a notice for each move. A listing change that
needs consent, including loss of verification, prompts in the terminal
for the specific driver and release. Type `yes` for a verified release,
`install-unverified` for a listed release, or `no` to skip that release.
If an older approval has no recorded source, the next listing update
needs fresh consent.

```sh
python3 -I tools/install/drivers/test_fetch.py
```
