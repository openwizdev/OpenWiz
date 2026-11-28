# Check shell commands in Markdown

The runner checks `sh`, `shell` and `bash` fences and reports each file and
opening line. Exit 1 means a block or input file failed.

```sh
python3 -I tools/docs-commands/docs_commands.py README.md docs/install.md
```

Put the reason on the opening fence for blocks that need state outside CI.

````markdown
```sh no-run: needs access to a signed-in test account
gh auth status
```
````

Use a disposable Linux runner with Python 3.10+ and util-linux `unshare`.
Each block starts offline in a fresh home with a clean environment and fakes
for commands such as `openwiz`, `gh`, `room-cli`, `boat` and `aws`. The shell
can access filesystem paths visible to the runner. The check log shows statuses.

```sh
python3 -I tools/docs-commands/test_docs_commands.py
```
