# WizSkills installer (for agents)

ClosedWiz installs the WizSkills release pinned in `wizskills.lock` into the
gitignored `.wizskills/`, like any user. The contract is
[WizSkills v1](../../contracts/wizskills.v1.md).

**When `.wizskills/` is missing, run this once from the repository root:**

```sh
python3 -I tools/wizskills/install.py
```

It needs Python 3, a POSIX shell and Git, and reads the network only to fetch
the pinned tag from `https://github.com/openwizdev/WizSkills.git`. It checks
that tag's release record, target commit and tree against the lock, then runs
that release's own `install.sh` from the verified local copy.

| Exit | Meaning | What to do |
| --- | --- | --- |
| 0 | Installed, or already the pinned release: nothing changed | Carry on |
| 1 | Refused: the install is dirty, another version or not a WizSkills checkout, or the release does not match the lock | Read the reason. It changed nothing; never delete or edit `.wizskills/` to get past it without asking |
| 2 | `wizskills.lock` is missing or malformed | Ask; the lock is the pin |
| 3 | The fetch or local I/O failed | Check the network and retry once by hand |

A current install is verified without any fetch: commit, tree, index and
every file's raw bytes and mode, ignored and untracked files included. No
Git configuration or attribute of the caller or the release changes what is
verified, and the release installer fetches only the verified local copy.

**Contract copies.** The five carried contracts in `.wizskills/contracts/`
must equal ClosedWiz's own `contracts/` files byte for byte:

```sh
python3 -I tools/wizskills/check_contracts.py
```

It exits 1 naming each file that differs or is missing.

**Tests** (offline, on a local fake tagged repository):
`python3 -I tools/wizskills/test_install.py`.
