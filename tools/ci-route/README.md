## Workflow lint

From an OpenWiz checkout, pass the workflow directory of the repository to check.

```sh
python3 -I tools/ci-route/lint_workflows.py ../WizSkills/.github/workflows
```

The lint reads the directory's `.yml` and `.yaml` workflow files. It checks
`jobs.<id>.runs-on` against [the CI routing contract](../../contracts/ci-routing.v1.md)
and accepts either of the contract's exact expressions and GitHub-hosted macOS
and Windows labels. Reusable workflow calls delegate runner selection to the
called workflow.

For static matrices that use `${{ matrix.<key> }}`, the lint checks the runner
axis and explicit runner overrides in `include`. It checks all declared runner
values, including values removed by `exclude`. Dynamic matrices and runner
expressions the lint cannot resolve fail the check.

Each offending job prints one line with the filename, job ID, and `runs-on`.
Unreadable workflows get a file diagnostic. The command exits 1 when it reports
a problem and 0 when all checked jobs comply.
