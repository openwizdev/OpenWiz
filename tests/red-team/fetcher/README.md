# Fetcher copy

A disposable stand-in for the fetcher, for huntr's attack mode (`name:fetcher`
in `docs/agents/huntr.md`). It runs offline on `127.0.0.1` only.

- `server.py` serves `index.json` (each package's name, version, path and
  pinned SHA-256) and the synthetic driver packages in `packages.json`: one
  good package, and one each tampered, swapped after its pin and truncated.
  The index never says which is which. `/redirect/<path>` redirects to
  `fetch.invalid`, a name that never resolves. Every request is logged.
- `loopback.py` is an audit-hook guard: once imported, the process can look
  up, reach, bind and send only to localhost, and can't start other programs.

Run it with `python3 -I tests/red-team/fetcher/server.py`; test it with
`python3 -I tests/red-team/fetcher/test_server.py`. Attack only this copy: no
live key, real user, real request, live tracker or third party, and no load
or flood traffic.
