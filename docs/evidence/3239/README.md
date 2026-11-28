# How to run the #3138 contract proof

`docs/evidence/3138/test_contracts.py` imports `jsonschema` to check the
release manifest against Draft 2020-12. Nothing else in this repository
declares that package, and `python3 -I` on a stock Python stops with
`ModuleNotFoundError: No module named 'jsonschema'`.

Run it in a virtual environment with jsonschema 4.23.0:

```sh
python3 -m venv /tmp/ow-3138-evidence
/tmp/ow-3138-evidence/bin/pip install 'jsonschema==4.23.0'
/tmp/ow-3138-evidence/bin/python -I docs/evidence/3138/test_contracts.py
```

This check is not a CI job. Adding `jsonschema` to the repository still needs
approval before any CI check adopts it.
