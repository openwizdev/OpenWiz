# Scoped review

- Only tools/ci-bench paths; no workflow, runner settings, dependencies or product files changed.
- Price source read directly 2026-11-14: https://usejog.com/docs/pricing/. All three requested sizes have public rates. Jog's documented second billing is applied only to those sizes. Unknown/multiple Jog labels precede generic self-hosted fallback and stay unknown.
- Both report headlines share their calculation and adjacent-PST-day delta. Merged PR cost uses total CI window spend; successful-code cost keeps its existing numerator. Zero denominators and absent historical cost records stay unknown.
- Chart manually rendered in Chromium on two synthetic daily windows; four legible headlines, four decimal USD figures and absolute day-over-day changes. No new cost goals were invented. Tab closed after capture.
- Existing timestamp optimization proof retains its original byte hashes by freezing the historical price input, rather than changing expected hashes to match this build. Existing date and unknown counts now include both cost panels; their original timing/goal/line assertions remain.
- Checklist: input format and stored cost schema unchanged; tests at CLI measure/dashboard boundaries; no live behavior inferred from fixtures; red tests committed before each production slice; optional stored cost still backward compatible; evidence fixtures synthetic. Full workspace/browser suites are left to CI per fleet policy. Infra exemption: no product changelog.

Refreshed onto current main before the first successful push. The affected benchmark suite now includes main's required-cohort and outcome tests: 113 passed; cargo fmt passed. The price fixture still preserves the original timestamp-proof hashes. No production changes were needed for the refresh.
