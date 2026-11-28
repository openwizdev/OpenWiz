# One-tap publishing to WizMarket v1

`openwiz.market-publish.v1` is the contract between the market skill's
publish step ([#3388](https://github.com/openwizdev/OpenWiz/issues/3388)) and
the write-driver Wiz entry ([#3488](https://github.com/openwizdev/OpenWiz/issues/3488)).
Other “Wiz, add X” flows use the same command and result.

## Command

```text
python3 -I skills/market/scripts/publish.py --kind <driver|harness|skill|loop> --path <folder> --check <report> [--receipt <kit-receipt>]
```

Run this command once for the artifact just built, after the flow has a passing
report for it. Pass each argument value as a single argument.

| Argument | Value |
| --- | --- |
| `--kind` | Exactly one of `driver`, `harness`, `skill` or `loop`. |
| `--path` | The folder containing the artifact Wiz just built. |
| `--check` | The passing check report for that artifact. The publish step checks it before offering to publish. |
| `--receipt` | Optional path to the artifact's 5-of-5 kit receipt. It supplies verification evidence for a driver or harness. |

If the publish step is missing, the caller says “Publishing is not available
yet.” It makes no offer or invocation and records the `unavailable` result.

## Preview and consent

Prepare the proposed WizMarket v3 listing and its accompanying files. Refuse a
failed check or any private repository, account or path in the proposed files
before asking. Give a short reason without echoing private values. If a supplied
input cannot be read or parsed, diagnose it and stop before asking.

Show every file that would go into the pull request and the GitHub account that
would open it, then ask once. Keep the preview and question on the user-facing
channel, such as standard error, with standard output reserved for the result.
Only the exact lower-case reply `yes` after removing its line terminator grants
consent. An empty reply, EOF, surrounding spaces, or any other answer declines.

After a yes, use the previewed files and the user's own `gh` login and fork to
open one pull request against WizMarket. Create the user's fork if needed. An
offer authorizes at most one post attempt. If the attempt fails or its result
cannot be confirmed, report the refusal with a safe reason and never retry
the attempt or invoke the step again for that offer.

## Listing status

A driver or harness is `verified` with a current 5-of-5 kit receipt for that
artifact. Include that receipt in the proposed files. A skill is `verified`
when its skill check passed, including its eval and regression gate. A general
passing report alone does not establish that skill proof. In every other
publishable case, including a loop, the listing is `listed`.

## Result and exit code

The step writes exactly one newline-terminated JSON object to standard output
for `posted`, `declined` and `refused`, with no other output on that stream.
Parse each field once. The object's `schema` is `openwiz.market-publish.v1`;
its `outcome` and remaining fields follow this table.

| Exit | Outcome | Remaining fields and meaning |
| --- | --- | --- |
| 0 | `posted` | `pr_url` is the confirmed HTTPS WizMarket pull request URL. `status` is the listing status written, `listed` or `verified`. |
| 3 | `declined` | No additional fields. The answer did not grant consent and nothing was posted. |
| 1 | `refused` | `reason` is one nonblank line describing why the step refused, such as a failed check, a private reference, or a post it could not confirm. |
| 2 | No result | The input could not be read or parsed. Standard output is empty and the diagnostic goes to standard error. |
| No invocation | `unavailable` | The caller records an object with only `schema` and `outcome`. There is no process exit code or standard output. |

The root of [the JSON Schema](market-publish.v1.schema.json) validates the
public result object. The [fixture check](fixtures/market-publish/README.md)
validates synthetic observations of the command and its caller against the
same schema's `$defs/fixture`.

## Synthetic example

A driver passes its check with a current 5-of-5 receipt. The preview lists
`listings/synthetic-driver.json` and `receipts/synthetic-driver/kit.txt` and
names `synthetic-publisher`. The user replies `yes` and the step exits 0.

```text
python3 -I skills/market/scripts/publish.py --kind driver --path synthetic/driver --check synthetic/check.json --receipt synthetic/kit.txt
{"schema":"openwiz.market-publish.v1","outcome":"posted","pr_url":"https://github.com/openwizdev/WizMarket/pull/900001","status":"verified"}
```
