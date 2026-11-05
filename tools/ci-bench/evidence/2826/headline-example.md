Synthetic fixture report excerpt; not a live cost measurement.

# CI bench

PRs an hour first, the headline. The first point is the 2026-11-01 baseline (2026-10-31T07:16:31Z to 2026-11-01T07:16:31Z). Made by `tools/ci-bench/bench.py chart`; every number is in the tables below.

| Window | Minutes per PR (median) | PRs/hour capacity | USD/merged PR | USD/code run |
| --- | ---: | ---: | ---: | ---: |
| 2026-11-01 baseline | 8.62 | 17.36 | unknown | unknown |
| 2030-01-01 PST | 1.50 | 200.00 | $0.0077 | $0.0066 |
| 2030-01-02 PST | 1.50 | 200.00 | $0.0154 | $0.0132 |
| Day-over-day (latest full PST day) | +0.00 | +0.00 | +$0.0077 | +$0.0066 |

USD/merged PR = total window CI spend / PRs merged in that window; includes failures, docs-only and scheduled runs. USD/code run averages only successful code-run spend. These are list-rate estimates before free minutes, not invoices or attributed PR costs. Zero merges or missing prices stay unknown. Day-over-day compares adjacent complete PST days only.

