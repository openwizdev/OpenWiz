# Factory bench v1

`openwiz.factory-bench.v1` defines the fixed task set, release results and
the comparison between releases. The [JSON Schema](factory-bench.v1.schema.json)
validates the two file shapes. Consumers also check relationships between
records and the files they refer to. The contract grants no spending authority.
Its fixtures are synthetic and the self-test only reads local JSON and
compares values.

## Task set

`bench/factory/tasks.v1.json` contains `schema` with the value
`openwiz.factory-bench.v1`, a human-readable `name`, and a nonempty `tasks`
array. Each task has these required fields.

| Field | Meaning |
| --- | --- |
| `id` | A unique, stable task identifier. Use lowercase ASCII letters and digits with single hyphens between segments. |
| `source.product` | Upstream benchmark product name. |
| `source.repository` | Public HTTPS URL of the upstream repository. |
| `source.commit` | Full pinned upstream Git commit in 40 lowercase hexadecimal characters. |
| `source.licence` | Exact SPDX licence ID from the permissive list below. |
| `instruction` | The instruction the builder receives. |
| `start` | Directory of starting files, relative to the task set's directory (`bench/factory/`). The directory must exist and resolve inside that directory. |
| `judge.run` | Offline judge command run from the root of the judged tree. Its exit status of zero proves a pass. |
| `judge.timeout` | Positive integer timeout in seconds for one judge run. |
| `caps.wall_minutes` | Positive integer wall-clock budget in minutes for the task. |
| `caps.tokens` | Positive integer token budget for the task. |

The permissive list is **MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause and ISC**.
Refuse any other licence value. The task-set checker also verifies that task
IDs are unique, the starting directories exist within the set's directory
and judges require neither network access nor credentials.

The set's hash is the lowercase hexadecimal SHA-256 digest of the complete
task set's canonical JSON bytes. Parse UTF-8 JSON with unique object keys.
Sort object keys lexicographically by Unicode code point at every level and
preserve array order. Serialize with no whitespace between tokens and no
trailing newline. Write integral numbers in decimal without exponents or
leading zeroes. Write Unicode characters directly in UTF-8. Escape quotes,
backslashes and control characters as Python's `json.dumps` does with
`ensure_ascii=False`. For task values represented as integers, the Python
serialization is `json.dumps(task_set, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
Normalize integral values to integers before this serialization.

## Result file

`bench/factory/results/<version>.json` contains `schema` with the value
`openwiz.factory-bench.v1` and these required fields.

| Field | Meaning |
| --- | --- |
| `version` | Candidate release version, equal to the file name without `.json`. |
| `commit` | Candidate Git commit in 40 lowercase hexadecimal characters. |
| `hash` | Canonical task-set hash in 64 lowercase hexadecimal characters. |
| `tasks` | Array with exactly one result for every ID in that task set. Order does not affect the score. |

Each result in `tasks` has these required fields.

| Field | Meaning |
| --- | --- |
| `id` | The corresponding task ID. |
| `result` | `pass` when the judge proves the merged work, `fail` when the judge rejects it, or `unproved: <why>` when no judge verdict was established. Give a nonempty reason on a single line, for example `unproved: not merged`. |
| `wall_minutes` | Measured elapsed wall-clock minutes spent on the task, as a nonnegative number. Fractions are allowed. |
| `tokens` | Measured tokens spent on the task, as a nonnegative integer. |
| `attempts` | Number of attempts made for the task, as a nonnegative integer. |
| `link` | HTTPS URL of the merged pull request, or JSON `null` when there is no merged pull request. |

Both file shapes require all listed fields and reject extra fields. The
schema checks structure. Readers verify the result's version and task-set
hash against their inputs and check exact task ID coverage, including
duplicates. Runners verify that a linked pull request was merged.

## Score and gate

Score the run as the number of `pass` results divided by the total number of
tasks in the set. Both `fail` and `unproved: <why>` contribute zero to the
numerator. Report the unproved task IDs alongside the score.

Apply the following rules in order to the candidate and the immediately
previous release.

| Reading | Condition |
| --- | --- |
| `unknown: <why>` | The candidate result is missing, unreadable or invalid for the candidate and current task set. A previous result that exists and cannot be read or validated also gives `unknown`. |
| `baseline` | The candidate result is valid and the previous release has no result for the current task-set hash. This includes a missing previous release or result, and a valid previous result with a different hash. |
| `fail: <why>` | Both results are valid for the current task-set hash, and the candidate score is more than 0.05 below the previous score. |
| `pass` | Both results are valid for the current task-set hash, and the candidate score is no more than 0.05 below the previous score. An exact drop of 0.05 passes. |

Malformed JSON, a schema violation, a version mismatch or missing or
duplicate task IDs for the declared set make a result invalid. Evaluate the
comparison on exact counts. For two valid results with the same set,
`20 * (previous_passes - candidate_passes) > total_tasks` detects a failing
drop without rounding. A `baseline` satisfies the bench gate. The gate
only reads results. Running a bench is a separate action requiring the
owner's prior approval of its stated cost.

## Synthetic fixtures

[The task set](fixtures/factory-bench/tasks.v1.json) is shared by the four
case files in [the fixtures directory](fixtures/factory-bench/). Each case
wraps the candidate and previous result records, the exact expected gate
reading, the candidate score as a fraction string or `null`, and its
unproved task IDs. A `null` result represents an absent file. The
`baseline` case uses a previous result for a different set. Only the
embedded task-set and result records are schema instances.

Run the offline proof from the repository root.

```sh
python3 -I contracts/fixtures/factory-bench/test_fixtures.py
```
