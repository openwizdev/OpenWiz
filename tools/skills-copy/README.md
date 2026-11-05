# Skills copy (O21)

`copy.py` reads a commit's Git objects and makes only the installable skills tree.
Python 3.11+ and Git; standard library only. It is a dry run unless `--publish`
is explicitly present. Preparation here grants no publication approval.
`--version` is required: see "Generated files" below.

```sh
# No destination is needed for a first-copy preview. No network writes.
python3 -I tools/skills-copy/copy.py --version 0.1.0 --source . --commit origin/main

# Save a checked tree. The output directory must not exist.
python3 -I tools/skills-copy/copy.py --version 0.1.0 --commit HEAD --output /tmp/checked-skills

# Compare with a dedicated skills clone's cached main, without fetching it.
python3 -I tools/skills-copy/copy.py --version 0.1.0 --destination /tmp/skills-clone

# Only after the separate publication approval (#1409 for the first publish):
python3 -I tools/skills-copy/copy.py --version 0.1.0 --commit HEAD \
  --destination /tmp/skills-clone --publish

# Affected synthetic command proofs; all transport is local/fake.
python3 -I tools/skills-copy/test_copy.py
python3 -I tools/skills-copy/test_package.py
python3 -I tools/skills-copy/test_workflow.py
```

The command reports the source commit, selected skills, exact Git tree, file and
byte counts, privacy result, added/modified/deleted paths, parent and proposed
commit. A privacy refusal reports the staged tree and check result, exits 1 and
never opens the publication path. Unknown inputs and failed Git operations also
exit 1. Check diagnostics contain rule/location/line, never matched contents.
`--output` is for a checked dry run, separate from publication.

## Reviewed carriage list

- Each direct skill folder in `skills/`, including all its scripts and tests.
  ClosedWiz's `skills/README.md` is not carried; the copy writes its own
  `skills/README.md` with the package's skill rules, beside the check.
- Each direct skill folder in `wizdev/skills/`, **if that root exists**. There is
  no WizDev folder today (#1288 is unplanned); this is its extension seam. A
  different eventual layout requires a reviewed edit here and in the workflow
  path filters, rather than discovering arbitrary folders by name.
- Nothing under `.claude/skills/`: ClosedWiz's three release skills there
  (export review, live quick check, live spike) stay private (#2630).
- **Carried contracts:** the files the `carried_contracts` list in
  `contracts/wizskills.v1.md` names, read from that contract at the pinned
  commit and written byte for byte at the same relative paths, so a skill's
  `../../contracts/<file>` link resolves in the copy. A missing or unreadable
  contract, a second normative block, a path outside `contracts/`, or a listed
  source that is missing or not a regular file refuses. Nothing else under
  `contracts/` is copied.
- Generated README, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  and `.agents/skills/` and `.claude/skills/` aliases into the copied `skills/`.

## Standalone check

`standalone.py` (WZ2, #2630) checks the staged tree before privacy and
publication. Every relative Markdown link (inline, image or reference), every
path anchored to a script's own location (Python `__file__`, shell `$0`,
JavaScript `import.meta.url`, and variables holding them), every relative
import and every local Python module must resolve to an existing file inside
the tree, by real path. Symlinks inside `skills/` refuse. A part known only at
run time (`ROOT / name`, `"$DIR/$file"`) passes below `skills/` and refuses
anywhere else.

Literal operands are checked too. These are the scripts a command runs in a
shell or console fence or a code span of a skill's Markdown, a shell script's
`python3`/`node`/`sh`/`source` operands (quoted single words included) and any local path run directly (`./x`, `tools/setup.py`), Python `open()`,
`Path("…").read_text()`, `subprocess` argv and loader paths, and JavaScript
`readFileSync` and `spawn` operands. Their working context is the consumer
project, whose root holds `skills/<name>/`, or a folder a script changed to
with an anchored `cd` or `cwd=`. Markdown commands may also be relative to the
skill's own folder. A skill-folder placeholder resolves to its skill
(`<this skill's folder>`, `<skill-directory>`, `<build-ticket skill's folder>`,
`<installed-huntr>`); any other placeholder is unresolved and refuses. A
relative read outside the package passes only for the contracted settings
names. Absolute paths pass only under system roots (`/dev`, `/proc`, `/sys`,
`/etc`, `/usr`, `/bin`, `/tmp`, `/var`). Operands built from variables, a
folder the script cannot know (`cd "$work"`) and synthetic paths in data
files are runtime input. Python imports resolve completely (`pkg.sub`).
Executable files are read by their shebang whatever their suffix, and an
executable with an unsupported interpreter refuses. An unreadable folder
refuses the whole check. Links into the
project's settings (`docs/agents/*.md`, `changes/README.md`, `GLOSSARY.md`)
are refused: name them in words. The allowed settings names come from the
contract's normative block.

```sh
python3 -I tools/skills-copy/standalone.py --tree /tmp/checked-skills
python3 -I tools/skills-copy/test_standalone.py
```

A refusal prints one JSON record per finding, with only `rule`
(`standalone.link`, `.script`, `.import`, `.read`, `.symlink`), the
package-relative `file` and its `line`, and exits 1. A `file` holding a form the privacy check refuses is printed redacted, the same way that check redacts. The copy's report has a
`standalone` entry beside `privacy`: `{"status": "pass", "skills": {}}`, or
`"refused"` with each refused skill's records. Either refusal exits 1 before
any destination read, so nothing is published. The scanner reads the code
lexically (Python by its syntax tree), so it can miss paths built in ways it
does not trace, such as values passed between files or computed strings.
Review still covers those.

Each folder needs a regular SKILL.md. Existing selected roots and their ancestors
must be directories; a file, symlink or submodule there refuses. Duplicate names, selected submodules,
private path components and links outside selected regular files refuse. Files
come from the pinned commit, including executable modes; uncommitted changes
and untracked files have no effect. The exact index ignores neither scripts nor
tests because of copied ignore files, and executes no copied Git filters. No
source Git history, project configuration, credentials or other repository files
are copied. A source commit that changes no copied content gives the same tree.

`tools/privacy-check/check.py --tree` checks the entire generated tree before
publication. Its OpenWiz-specific history anchors do not apply to the separate
skills repository. `--literals PATH` supplies the private named-literal list and
requires it to be readable and nonempty. For the exact GitHub repository identity
`jparker2006/ClosedWiz` (case-insensitive; HTTP(S), SSH, git and scp URL forms with optional SSH username,
with optional `.git`/trailing slash), the command requires its list at
`private/evidence/open-development/privacy-check/literals.txt` by default. Public automation has no private list; every other privacy rule runs.
Binary contents and personal facts outside machine-detectable forms still need
review, as the privacy-check contract documents.

## Generated files

The copy packages the skills as WizSkills, under `openwiz.wizskills.v1`
([contract](../../contracts/wizskills.v1.md)). Like the skills, every input is
read from the pinned commit, never the checkout: the templates in
`tools/skills-copy/package/` and WZ7's check folder.

- `.claude-plugin/plugin.json`: `package/plugin.json` (name `openwiz`, its
  `version` and descriptive fields) plus `skills`, one `./skills/<name>` per
  copied skill, sorted.
- `.claude-plugin/marketplace.json`: `package/marketplace.json`, named
  `wizskills`, with one plugin, `openwiz`, sourced from `./`.
- `CHANGELOG.md`: `package/CHANGELOG.md`, whose one `{{skills}}` line, in its
  latest section, becomes one line per copied skill.
- `README.md`: `package/README.md`, with `{{version}}` filled in: the product,
  versions, and the Claude Code, Codex and `install.sh` installs, pinned to
  that release.
- `LICENSE`: `package/LICENSE`, then each distinct upstream notice the copied
  `SKILL.md` files carry (from its `Copyright (c)` line to the end of its
  warranty paragraph), once each. A `Copyright (c)` line without a complete
  notice refuses.
- `install.sh`: `package/install.sh`, executable (below).
- `check/` and `.github/workflows/ci.yml`: from `tools/skills-copy/package-check/`
  (WZ7, #2632), `check/run.py` stays `check/run.py` and `ci.yml` becomes the one
  workflow; its `README.md`, `test_check.py` and `red-run.txt` stay in ClosedWiz,
  and any other file there refuses. Beside them the copy writes
  `check/standalone.py` (the scanner), `check/wizskills.v1.json` (the contract's
  normative block) and `check/redact.py` (the privacy check's redaction), so the
  scanner reads nothing outside WizSkills (WZ14, #2891). Until that folder exists
  the dry run reports `"check": "missing"` and `--publish` refuses.

**The version.** `--version <version>` (SemVer, no leading `v`) must equal
`package/plugin.json`'s `version` and the latest `## <version> - <YYYY-MM-DD>`
section of `package/CHANGELOG.md`; any disagreement refuses before privacy or
destination work. The report's `package` field names the version and the
check folder's state. A new release moves all three together: the changelog
gains a section, `plugin.json` its version, and the command its input.

**The installer.** `package/install.sh --version <version> --dest <dir>` is
the contract's interface: a POSIX shell and Git; one fetch of the tag
`v<version>` from `https://github.com/openwizdev/WizSkills.git`; the annotated
tag's JSON record (exactly `schema`, `version`, `commit`, `tree`, string values
without escapes; a signed or lightweight tag refuses) checked against the
tagged commit, its tree, every checked-out path's raw bytes and mode (hashed
without Git attributes or filters; a nested `.git`, an empty directory or a
changed line ending refuses), `plugin.json` and the changelog. A missing `<dir>` becomes a detached checkout,
staged in a temporary folder beside it and moved into place only after every
check; an existing one must be that exact clean release (a no-op) or is
refused unchanged. It refuses a symlink anywhere in the destination's path and
a missing parent, and writes nothing on failure. `test_package.py` proves it
against a local fake tagged repository through Git's own `insteadOf`
redirection, and runs the README's install commands the same way.

## Publication and automation

The destination must be a dedicated clean clone with exactly one push URL,
matching its origin, either `git@github.com:openwizdev/WizSkills.git` or
`https://github.com/openwizdev/WizSkills.git` (the destination named
`openwizdev/skills` before, which was never created). Dry runs use only cached refs and
write temporary objects in a disposable repository; destination objects, refs
and working files stay untouched.

Publishing reads remote main and fetches it, creates one commit with that sole
parent (a root commit for an empty destination), imports only that candidate's
objects into the destination clone, and pushes its exact SHA to main. No source
history enters that object database. A matching tree creates no commit and
pushes nothing. The destination's local branch/checkout stays as it was; only
fetched objects/FETCH_HEAD change locally. The commit uses OpenWiz's no-reply
identity and source timestamp; it embeds no private-source commit metadata.

There is no force push, tag push or retry. A competing remote update makes the
ordinary push fail. A failed push or read-back requires inspection before
retrying; it never claims a verified publication. Hooks are disabled for this
single generated-commit push, after the required privacy check. Repository or
credential setup is #1409's work, not this tool's.

The workflow admits only skill-changing pushes to `openwizdev/openwiz` main,
uses `ubuntu-24.04` and a read-only source token, and serializes publications.
`workflow.py` verifies the event and changed paths again before the destination
credential is used. Synthetic proofs run before publication. ClosedWiz and forks
skip the entire job, including checkout. The source of truth stays OpenWiz.

#1409 provisions `SKILLS_COPY_DEPLOY_KEY` on OpenWiz: the private half of a deploy
key registered **only** on `openwizdev/WizSkills`, with write access there. No PAT,
source write permission or organization-wide credential is needed. The workflow
uses checkout's SSH credential handling and cleanup. It assumes #1409's approved
first publish has already created destination main. Before cut-over, #1409 runs
the same command by hand on separately authorized source commits. Live publishing,
credential scope and both agent installs remain #1409's live proofs.
