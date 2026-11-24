# The clean-machine install rehearsal

`rehearse.py` installs one built OpenWiz package the way a stranger's agent would, following the
install skill's no-CloudRoom path ("This computer", Claude Code), and writes a receipt
([`openwiz.rehearsal.v1`](../../contracts/rehearsal.v1.md)). The Packages workflow runs it on
all three targets' archives right after building them (spec #2437), so every release candidate's
run says whether a stranger could install exactly those bytes:

| Job | Target | Machine |
| --- | --- | --- |
| `rehearse-linux` | `x86_64-unknown-linux-gnu` | a `debian:12` container on `ubuntu-24.04`, with only Python 3, Git and CA certificates installed |
| `rehearse-macos` | `aarch64-apple-darwin` | `macos-15`, the system `/usr/bin/python3`, a fresh `HOME` |
| `rehearse-macos` | `x86_64-apple-darwin` | `macos-15-intel`, the same |
| Daily install check (`install-daily.yml`) | all three | the same machines, once a day, on the latest published release's assets and its tag's own `rehearse.py` (a tag without one is neutral, one notice line, no issue change); a failure opens or comments on the one `Daily install check failed` issue, and a pass closes it |

Each job downloads that run's own artifact for its target and uploads its receipt as
`openwiz-rehearsal-<version>-<target>`. The `rehearsal` job is green only when every rehearse
job is. The macOS jobs also run the fixture suite on their machine. A hosted Mac comes with Rust
and Node installed, so there the clean machine is the stranger's environment the runner builds,
not the runner image.

```sh
python3 -I tools/wizskills/install.py   # the install skill at the wizskills.lock commit
python3 -I tools/rehearsal/rehearse.py --assets <run>/packages --target <target> \
  --version <version> --source <commit> --checkout "$PWD" --skills "$PWD/.wizskills/skills" \
  --output rehearsal.json
env -u OPENWIZ_GITHUB_APP_KEY python3 -I tools/rehearsal/test_rehearse.py   # the fixture suite
```

Its six steps, their checks and its exits are in `rehearse.py`'s header. Every command runs with
`env -i`, a fresh `HOME` and a `PATH` of only `python3`, `git`, `sh`, `uname`, `ldd` (Linux only), the fakes
and recording `cargo`, `rustc`, `rustup`, `npm`, `node` and `npx`. None of the 32 agent and host
CLIs in `ABSENT` (`room-cli`, `boat`, `codex` and the rest) may be on it; `claude` and `gh` are the
recording fakes. It refuses to start while a token, App or CloudRoom variable is set.

## The fakes

- `fakes/gh`: signed in as the synthetic account in `fakes/world.json`. Reads answer from that
  world; any write, or any command it doesn't know, is recorded and fails the step.
- `fakes/claude`: answers `--version` only; any other call fails the step.
- `fakes/build-tool`: every build tool; any call fails the step.

`fixtures/release.py` builds the fixture suite's synthetic release with the real packager, and
plants each break the suite checks: a flipped archive byte, a manifest of another version, a
build identity from another commit, a setup check that needs CloudRoom, a dry run that writes to
GitHub and a `cargo` call.

## What it proves, and what it doesn't

A pass proves that on a clean machine of that target, with no build tools and no CloudRoom, these
exact bytes verify, install, report the run's version and commit, set up for the local host, put
their skills into Claude Code and run the first fleet's opening previews and reads with no GitHub
write.

It runs no real fleet: no grill, ticket, builder, reviewer, heartbeat or merge. It touches no real
account or repository: GitHub and Claude Code are fakes, and the first-fleet dry run stops at the
last step a preview can reach with no `--yes` (`where`, `select`, the repository read-back and
`next`), since connecting a repository writes to GitHub. The one `--yes` it gives is `setup.py
prepare --host local`'s, in the `setup` step: it writes only the owner-only local setup state, and
the setup check reads `cloudroom_not_needed` only for a prepared local host. It is not the person's
own rehearsal.
