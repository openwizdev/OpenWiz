# Privacy check

One read-only command implements `openwiz.open-development.v1` (§ The privacy
check). It never pushes, stages, fetches objects, follows directory symlinks or
writes repository files. Python 3.11+ and Git are its only runtime tools. No new
package dependencies.

```sh
# An explicit staged public directory (also works inside the private clone):
python3 -I tools/privacy-check/check.py --tree /tmp/staged-public \
  --literals /path/to/ClosedWiz/private/evidence/open-development/privacy-check/literals.txt \
  --require-literals

# Immutable Git objects and an exact commit range, without checkout:
python3 -I tools/privacy-check/check.py --repo /path/to/OpenWiz \
  --git-tree HEAD --base origin/main --head HEAD \
  --title-file /tmp/proposed-title --body-file /tmp/proposed-body

# Proposed issue/PR text alone (the ticket mover's seam):
python3 -I tools/privacy-check/check.py --title-file /tmp/proposed-title \
  --body-file /tmp/proposed-body --literals /path/to/literals.txt --require-literals

# Synthetic command and hook proofs; no network and no Rust/browser suites:
python3 -I tools/privacy-check/test_check.py
sh .githooks/test.sh --fixtures-only
```

Inputs combine: a directory, a Git tree, history and text can be checked in one
invocation. Importers must pass `--require-literals`; an absent, empty or
unreadable list refuses. Explicitly supplying an unreadable optional list also
refuses. Every result reports `literals: used` or `literals: not used`.
No inputs, unreadable inputs and unknown workflow syntax refuse.

Exit 0 means no refusal; exit 1 means refusal; malformed command arguments exit
2. Each refusal gives its contract rule, input location and line, without a
source snippet. File locations redact identifiers and escape control characters.
`commit-N` and `commit-tree-N` follow Git's `rev-list` order, newest first; a
`tree:` location names the requested Git tree and `staged:` the directory. The
line is in the commit message, PR text or named file; structural rules use line
1. No message or identifier is printed on errors.

T3 also refuses the two forms that stopped the first skills export (#1409,
WZ2 #2630): a concrete helper snapshot or window location with its per-run
suffix (`snapshot.<suffix>/state.json`, or one under `helper-checks/`), and
an owner machine's CPU facts, i.e. a CPU count, `cpu.max` or quota number next
to the PC, the Mac, an owner's or a host's machine, even wrapped over two
comment lines. Generic templates (`snapshot.*`, `window.<run>`, an all-`X`
mktemp template) and text that says the example is invented, synthetic,
hypothetical or "for example" pass. This is a pattern rule, so it does not
replace review.

Trees refuse private paths even when empty, including symlink entries. Text
rules scan filenames and symlink targets as well as UTF-8 contents. Binary
contents (NUL bytes or recognized image/PDF signatures) need review; unknown
non-UTF-8 encodings refuse. In `contracts/open-development.v1.md` only, fenced
`bad` examples are skipped, preserving line numbers. A `good` example, a line
outside a `bad` block or a `bad` block in any other file is scanned.

History must have exactly the contract's public root and contain its public
anchor. Replace objects are disabled, grafts and shallow clones refuse, and
missing objects are never fetched. Every newly reachable commit after the
anchor has its message, author/committer email and tree checked: deleting a
private file at the tip does not remove it from published history. Without
`--base`, the range begins after the approved public anchor. There is no command
option or environment override for the root, anchor or decider list. Tests
substitute synthetic policy constants in memory and traverse real fixture Git
graphs, including an unrelated root arriving through a merge.

Workflow parsing deliberately recognizes a safe YAML subset: block mappings
and sequences, flow lists, quoted/plain scalars and opaque block scalars. It
refuses duplicate keys, aliases, tags, flow mappings, directives and multiline
plain/quoted scalars. Unrecognized syntax cannot silently drop a runner key.
Each job needs an allowlisted runner or a local reusable workflow present in
the checked tree. Matrix includes are checked as well as the selected axis.
Block-valued runner expressions refuse; block-valued shell steps cannot
introduce YAML keys. Existing private CI's runner fallback may still fail the
contract until the CI tickets change it; this ticket does not edit that workflow.

## Integrations

- **Ruleset check name: `privacy`**, fixed by job id and name in
  `.github/workflows/privacy.yml`. O12 (#1280) requires this name. It runs on
  `ubuntu-24.04` with read-only permissions for every push, PR (including text
  edits) and merge group. Tests use synthetic fixtures on both repositories.
  Its private checkout contains only this tool, hook fixtures and this workflow,
  excluding private files. The event gate exits on the private repository before
  reading its event or tree. On public repositories it checks exact event SHAs and PR title/body.
- **Pre-push:** install with `git config core.hooksPath .githooks`. The hook checks
  each pushed commit before the no-file-change shortcut and before the existing
  format/fast checks. Network destinations other than the private repository
  are guarded, including forks. Local filesystem remotes remain fixture-only.
  Set `OPENWIZ_PRIVACY_LITERALS` to an explicit literals path (or pass
  `hook.py --literals PATH` when invoking the adapter directly). A configured
  list is required and fails closed when unreadable. No directory basename
  discovers a private repository or supplies literals. A deletion publishes no commit. Annotated tags resolve to their commit.
- **Importer/release/skills copy:** O14 (#1282), O13 (#1281), O21 (#1408) use
  `check.py --tree` and/or the Git inputs above before final staging/publishing.
  They own carriage lists and publication; this tool only decides privacy.
- **Ticket mover:** O15 (#1283) uses the title/body inputs after transformations.
- **Rehearsal:** O16 (#1284) uses the same command on the complete staged tree.

No fixture proves live publication. CI without the private list cannot check
named literals. Images, unquoted personal facts and quotations outside the
contract's record forms remain review responsibilities.
