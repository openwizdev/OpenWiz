# WizSkills v1 (`openwiz.wizskills.v1`)

Contract-first boundary for spec #2622, ticket WZ1 (#2628). This specifies the
future package and installer interfaces; it implements and activates neither.
WizSkills' home is `openwizdev/WizSkills`. Its first version is **0.1.0**,
independent of OpenWiz's versions. The plugin remains **openwiz**, so skill
names remain `openwiz:<name>`.

Authority: Jake, 2026-11-13: approved spec #2622 and its revision 1 plan graph
under the pre-approval of the WizSkills split
([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6848396003)).
This contract relies on [open development v1](open-development.v1.md). It grants
**no repository, publishing or credential authority**. Approval of the plan is
not permission to publish the first release.

## Package layout and checks

Paths below are relative to the WizSkills repository root. Every skill gets
`skills/<name>/SKILL.md`, its `agents/openai.yaml`, and its own scripts, tests
and resources under that folder. All skills move; none is silently dropped.

- `skills/README.md` carries the skill rules. `check/run.py` is the package's
  check entrypoint: `python3 check/run.py` runs the rules, standalone check and
  every skill's own suite, returning nonzero if any is missing or fails.
- `.github/workflows/ci.yml` is the one workflow. It runs that entrypoint on
  every push and pull request, with read-only permissions, no secrets and no
  dependency on a ClosedWiz checkout or private file.
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` package the
  skills; root `README.md`, `CHANGELOG.md`, `LICENSE` notices and executable
  `install.sh` travel with them. Preserve every upstream licence/source notice.
- `contracts/` carries the nine files in the normative block below, **byte for
  byte at the same relative paths**. ClosedWiz retains the source copies for
  its code. After the move it checks each against the pinned installed copy;
  even one byte different fails, naming the file. A skills-only contract moves
  with its users; this does not silently expand the nine shared-source copies.
- The last four in that list (`ops-dispatch.v1.md`, its schema,
  `github-identity.v1.md` and `cli.v1.md`) are pending Jake's decision J40
  (the orchestrator's build-ahead ruling for #2628's review, #2682). If he
  declines, they are dropped from the list and recorded as named gaps.

WZ7 (#2632) owns the rules and suites implementation. The rules retain today's
frontmatter (`name`, `description`; only `ask-wiz` additionally requires
`disable-model-invocation: true`), only Codex `interface.display_name` and
`interface.short_description` (only `ask-wiz` also has
`policy.allow_implicit_invocation: false`), Matt Pocock's exact MIT notice
or the skill's listed original-source line, resolving relative links, no
symlinks inside `skills/`, and the manifest listing exactly the carried skills.
The suite inventory starts from the current skill-suite selection; scale/load
tests that drive OpenWiz's main-repo binaries stay in ClosedWiz. A borrowed
skills-only helper must be carried with its test. Fixture placeholders are not
a substitute for these release checks.

## Standalone rule and refusals

In every copied skill, **every relative Markdown link (inline or reference),
script path, file import and file read must resolve to an existing target
inside the WizSkills tree**. Anchor links use their containing file. Resolve
paths from their actual context: Markdown/imports beside the referring file,
shell commands from their declared working directory. Normalize dot segments
and link encodings before checking containment. Absolute source-checkout paths,
missing targets, escaping symlinks and unresolved file dependencies fail closed.
There are no symlinks inside `skills/`, even if their targets are internal,
because plugin installation may discard them. Tool/module names (Git, Python's
standard library, `gh`, `room-cli`) are not local file dependencies; a tool name
does not permit importing its helper from another checkout.

The **only outside project-file names allowed** are `docs/agents/*.md` (one
file directly in that directory), `changes/README.md` and `GLOSSARY.md`.
Name them in words as the **consumer project's** settings, or read them from
that project at run time. Never hyperlink them from the package, treat them as
packaged files, or execute/import them under this exception. This is no grant
to edit project settings. A path in synthetic fixture **data** is allowed;
an executable fixture, import, link or read is still checked. Calling something
a fixture never exempts executable behaviour. URLs to public documentation
are not relative file dependencies and still obey the privacy rules.

The check inspects the skill files, scripts and test resources, not just
`SKILL.md`. It does not recursively rewrite or extend the byte-identical
carried contracts' own dependencies. A reference *from a skill* must land on a
carried file; a contract's explanatory link alone does not add to the carried
list. If execution needs more files, stop and resolve that dependency rather
than assuming it exists outside the package.

A standalone refusal returns **1**, prevents publication, and reports one
record per finding with **only** `rule`, package-relative `file`, and positive
one-based `line`. Rules are `standalone.link`, `standalone.script`,
`standalone.import`, `standalone.read`, or `standalone.symlink`. An ambiguous
dependency uses its referencing kind; do not silently skip it. For a filesystem
symlink, line is 1. Never echo matched text, targets, source snippets or private
absolute locations. For example (entirely synthetic):

```json
{"rule":"standalone.read","file":"skills/alpha/scripts/check.py","line":7}
```

The copy's dry run reports pass or refusals **for each skill**, separately from
privacy results. WZ2 (#2630) implements reference discovery and refusal; WZ4–6
(#2634–#2636) fix skills without changing their behaviour.

## Version, plugin and changelog

Versions use SemVer, with the initial release 0.1.0 and tags `v<version>` on
WizSkills `main`. Do not reuse or move a released tag. A version has no leading
`v` in JSON, the plugin manifest or the changelog heading. The copy's version
input, plugin `version`, latest changelog section and release record must agree.

`plugin.json` has `name: openwiz`, `version: <version>` and `skills`, exactly
one `./skills/<name>` entry for every carried skill, sorted by name, no extras
or duplicates. Existing descriptive fields may remain. `marketplace.json` has
`name: wizskills`, an `owner` object and exactly one plugin entry, named
`openwiz`, with `source: ./` (repository root). If it repeats the version,
it must agree with `plugin.json`; the plugin manifest is authoritative.

`CHANGELOG.md` starts with `# Changelog`. Sections are newest first, each
`## <version> - <YYYY-MM-DD>`, a real UTC calendar date, then one nonempty
`- <change>` line per change, separated from the heading by a blank line.
Versions are unique; previous sections are preserved. The 0.1.0 section says
this is the first public release of OpenWiz's skills, with one line per skill.
For example (synthetic date and skill):

```text
# Changelog

## 0.1.0 - 2030-01-02

- First public release of OpenWiz's skills: alpha.
```

## Release record and installer

The release's recorded identity lives **outside the Git tree it describes**:
the `v<version>` annotated Git tag's message is a UTF-8 JSON object with exactly
`schema`, `version`, `commit`, `tree`. Schema is
`openwiz.wizskills.release.v1`. The tag directly targets that release commit;
its `commit^{tree}` must equal `tree`. IDs are full lowercase 40-hex Git object
IDs, never abbreviations. This is the WizSkills release commit, not the
ClosedWiz source commit. JSON objects reject duplicate or unknown keys and
wrong types. The example lock/release objects in the fixtures use invented IDs.
The tag record avoids a self-referential file hash and needs no second network
download. It supplies integrity/binding, **not a signed publisher identity**;
publishing gates and the independently checked consumer pin still matter.

`install.sh --version <version> --dest <dir>` requires both arguments exactly
once, rejects unknown arguments, and never defaults to latest or `main`.
Requirements are a POSIX shell and Git. Its only remote read is fetching the
explicit tag from `https://github.com/openwizdev/WizSkills.git`; no live
CloudRoom call, credential creation or other service is involved. Offline
tests redirect this Git transport to a local fake tagged repository.

1. Validate arguments and destination first. Resolve the destination explicitly;
   refuse a symlink destination/ancestor and any non-directory collision.
2. Fetch into isolated temporary staging, verify the annotated tag, exact record,
   peeled commit and full Git tree (names, bytes and executable modes). Verify
   plugin version, changelog version and requested version agree. Failure or
   uncertainty refuses; no fallback fetch, reset, force or automatic retry.
3. A missing destination installs the complete release as a detached Git checkout
   at that commit, retaining its `.git` metadata so it can verify later reuse.
   All tracked package files live directly under `<dir>`, not an extra subfolder.
   Publish the prepared directory atomically only after all verification passes.
4. An existing destination must be that exact version, commit and tree and have
   an identical working tree: complete path set, file bytes, executable modes,
   and no staged, modified, deleted, untracked or ignored extra files outside
   `.git`. Matching is a no-op. A dirty, foreign, empty or mismatched directory
   is refused unchanged. Updating a pin never overwrites an existing install.

**Write nothing on failure** means the destination and pre-existing files,
links, settings and credentials remain untouched; a missing destination stays
missing. Temporary staging outside it is permitted and cleaned up. Do not
create destination parents before verification, or change the caller's Git
configuration to accomplish a fetch. A failed/no-op invocation does not touch
an existing installation. Concurrent installation must never replace a
destination created or changed after validation.

Exit codes: **0** installed or verified no-op; **1** verification/state refusal
(including missing/malformed release record, tree mismatch or dirty destination);
**2** invalid arguments/version; **3** fetch or local I/O failure. Failure
diagnostics on stderr name a fixed reason, never credentials, upstream payloads
or private contents. No failure is success. WZ3 (#2631) builds this installer;
WZ11 (#2633) builds the consumer wrapper and transactional offline tests.

## README's three installs

The README explains the product, versions, dependencies and all three installs,
using **one explicit release**, not a floating branch. It identifies the source
of the installer: a checkout of the chosen release, verified before execution.

1. Claude Code: show `claude plugin marketplace add openwizdev/WizSkills` for
   discovery, then the pinned form
   `claude plugin marketplace add https://github.com/openwizdev/WizSkills.git#v0.1.0`
   and `claude plugin install openwiz@wizskills --scope project`. Use the pinned
   form when adding the marketplace for an actual installation; do not imply
   an unpinned existing registration is pinned by the install command. Check
   the registered ref and installed version. The tag syntax is documented in
   [Claude Code's CLI reference](https://code.claude.com/docs/en/plugins/cli-reference.md#plugin-marketplace-add);
   WZ9 still must try it in a throwaway sandbox.
2. Codex: use the verified `install.sh --version 0.1.0 --dest <dir>`, then expose
   each installed `skills/<name>` folder through a project `.agents/skills/<name>`
   link. Keep resources together and refuse existing conflicting links. This
   links **to** skills; it adds no symlink **inside** a skill. State how to check
   the installed files/version and ask Codex to read the exact `SKILL.md`.
3. Any other agent: the same versioned `install.sh` command, then tell the agent
   to read `<dir>/skills/<name>/SKILL.md`. Do not copy just `SKILL.md`, lose its
   resources or depend on ClosedWiz's paths. Check the requested skill resolves.

Examples here specify documentation, not proof of harness discovery or install
success. WZ9 (#2637) must exercise all three from the local candidate and WZ10
(#2638) must read back the published plugin install after permission to publish.

## ClosedWiz pin and move

`wizskills.lock` is UTF-8 JSON with **exactly** `version`, `commit`, `tree`, all
strings, using the same version and full object-ID forms. The trusted lock must
agree with the fetched tag record, tag target and actual release tree before
running the fetched installer. Do not execute an unverified bootstrap script.
Fetch only the pinned tag; pass a verified local tag/repository to the release
installer through local Git transport redirection if needed, avoiding a second
remote download. No network beyond that tag fetch is allowed.

The consumer installs at the gitignored `.wizskills/` root; the tracked `skills`
symlink has exactly the relative target `.wizskills/skills`. Existing harness
links continue through it. Missing installs use the pin; matching installs do
nothing; dirty/mismatched installs refuse without changes. Verify installed
bytes and the whole tree against the lock, not just the checkout's `HEAD`.
Contract-copy checking uses the normative list and byte equality, not a
directory walk that could silently miss a required file. Missing is failure.
WZ11 owns the installer, WZ12 (#2639) adds the actual pin/link and removes the
tracked skills only after the published release and ownership-cut gates pass.

## Privacy and first-release gates

Jake creates the repository, initially empty and private, with a ruleset on
`main` refusing force-push and deletion. No credential is created by this work.
Before the first release: standalone pass for every skill; the whole candidate
privacy-checked with the private literals list; all package checks green; one
independent full export review of every file; and all three install trials in
a throwaway sandbox. Privacy refusals also catch concrete helper-state
locations and owner-machine facts; synthetic regression data never contains
their real values. WZ2 defines those regressions, not an exemption by filename.

Save the exact candidate commit/tree and results privately. Jake's **explicit
go on that exact candidate** is required; a different commit or tree returns to
review. Only then may the orchestrator push that commit, create its annotated
tag/record, make the repository public and create the release page. Read all
of those back, including commit/tree/tag equality and the published install.
Nothing here performs those steps or bypasses the open-development contract.
The move also waits until every open ticket owning a skill path has merged or
is held and re-pointed with Jake's approval. Fixture tests never prove live
installs, export clearance, publication or that ownership cut.

## Normative fixture vocabulary

This single machine-readable block pins lists and wire forms used by WZ-P1.
The prose above is normative too. `required_files` names minimum entrypoints,
not an allowlist excluding the scripts/resources a skill needs. The carried
list is exact for shared-source copies. Example package placeholders only
demonstrate structure; downstream tests prove real copying and execution.

```wizskills-v1
{
  "schema": "openwiz.wizskills.v1",
  "required_files": ["skills/README.md", "check/run.py", ".github/workflows/ci.yml", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "README.md", "CHANGELOG.md", "LICENSE", "install.sh"],
  "skill_files": ["SKILL.md", "agents/openai.yaml"],
  "carried_contracts": ["contracts/decisions.v1.md", "contracts/decisions.v1.schema.json", "contracts/plan-links.v1.md", "contracts/plan-links.v1.schema.json", "contracts/open-development.v1.md", "contracts/ops-dispatch.v1.md", "contracts/ops-dispatch.v1.schema.json", "contracts/github-identity.v1.md", "contracts/cli.v1.md"],
  "project_settings": ["docs/agents/*.md", "changes/README.md", "GLOSSARY.md"],
  "plugin_name": "openwiz",
  "marketplace_name": "wizskills",
  "version_pattern": "(?:0\\.[1-9][0-9]*|[1-9][0-9]*\\.(?:0|[1-9][0-9]*))\\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?",
  "oid_pattern": "[0-9a-f]{40}",
  "lock_fields": ["version", "commit", "tree"],
  "release_fields": ["schema", "version", "commit", "tree"],
  "release_schema": "openwiz.wizskills.release.v1"
}
```

Run `python3 -I tools/wizskills/test_contract.py` in the source checkout for
WZ-P1: explicit package, pin, changelog, reference and refusal fixtures. It
also verifies that each named carried source exists. It is not the production
standalone scanner or installer. Its failing-first record and claim boundaries
are in `contracts/fixtures/wizskills/`; independent contract review is required.
