# Changelog check

`python3 -I .github/actions/changelog/test_check.py` tests the public command
against a recording fake `gh`. No account, credential or network is used.
The separate `changelog` job runs these tests and then `check.py` on every
pull request to `main` or `release-*`, including label addition/removal, and on
merge groups. Like `ci.yml`'s jobs, it runs on the `CI_RUNS_ON` repository
variable's runner, else GitHub's `ubuntu-24.04` (#1307). Making it required is a
repository setting, outside this action.

For a PR, the command reads its current metadata, every changed-file page,
then metadata again. It refuses failed reads, incomplete lists, unknown shapes,
a stale event head, or changed labels/base/head/count during those reads.
It makes no GitHub writes. Inputs: `EVENT`, `REPO`, `PR`, `EVENT_HEAD`, `GH_TOKEN`.
Merge groups pass without reading a PR.

Product files include `crates/`, `contracts/`, `skills/`,
`.claude-plugin/`, `Cargo.toml` and `Cargo.lock`. Only the explicitly known infra/docs/test paths in `product()`
are exempt; unknown paths conservatively require a line. Nested docs/tests in
product trees can use the reviewed `no-changelog` label. Renames count both
old and new paths. Added or corrected `changes/<positive ticket number>.md`
counts; a removed line, README, leading-zero name or nested file does not.
The filename is the ticket number, not necessarily the PR number.

This checks presence, not the line's wording or its association to a ticket.
The reviewer still checks format, public wording, truth and any exemption's
reason against `changes/README.md`.

On a pull request or merge group, the workflow then runs
`tools/release/entry.py` over `changes/` for lines added or modified since the
base. That is the release source check: a line whose ticket has no version
milestone fails the pull request. Lines the diff did not change are left to
release, including moved lines recorded there as exclusions.

GitHub's [file-list API](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)
returns at most 3000 files. Larger PRs fail closed, including labelled ones.
The workflow uses `pull_request`, read-only permissions and no persisted Git
credentials; it never uses `pull_request_target` to execute PR code with a
privileged token. It is a normal repository check, not a security boundary
against a contributor who can modify its workflow; review still owns that.
