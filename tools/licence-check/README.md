# Public repository licence check

Run with the factory's signed-in GitHub CLI from the repository root.

```sh
python3 -I tools/licence-check/check.py
```

The tab-separated report lists every public repository returned by the
organization's paginated GitHub API. Each row gives GitHub's detected SPDX ID
(`none` for a missing licence) and passes only for `Apache-2.0`. The audit
covers the API's default-branch detection. A missing, ambiguous or unreadable
API response can make the audit incomplete. A licence `404` counts as missing
after a repository read confirms visibility is still public.

Add `--file-issues` to open one issue per gap on OpenWiz. The check reads all
open issue titles and skips exact matches. Run one filing invocation at a
time. If an issue creation cannot be confirmed, inspect the open issues
before retrying. Filing starts only after all licence reads succeed. The
tool writes only OpenWiz issues in that mode.

Exit status is 0 when all licences pass, 1 when the completed audit finds
gaps, and 2 when an audit or filing request cannot be confirmed.

Run the offline tests with `python3 -I tools/licence-check/test_check.py`.
