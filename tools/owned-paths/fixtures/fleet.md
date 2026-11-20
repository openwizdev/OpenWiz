# Fleet (synthetic fixture)

## Supporting edits

The project's standing supporting-edit rule:

1. **Its own rows in shared registries:** `tools/registry/paths.json` and `tests/catalogue.rs`.
2. **Its changelog line** as `changes/<ticket>.md`, whatever its owned paths name.
3. **Its own evidence folder** under `docs/evidence/`.
4. **Synthetic answers to test fakes its change breaks,** with no assertion change.

- **Still ask first** for any `contracts/` change.

## GitHub identity

| Setting | Value |
| --- | --- |
| Not as the App | Pushes that change `.github/workflows/` |
| Record authors | `fleet-app[bot]`, `owner-one` |

## Labels

`held` and `ready-for-agent`.
