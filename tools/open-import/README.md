# Local public-tree preparation

`import.py` implements O14 of the open development contract. Python 3.11+ and
Git are the only runtime tools. It has no network operation, push, branch update,
checkout, source fetch, package dependency, watcher or live application call.

The inputs are separate existing local repositories. Resolve/fetch their commits
before running this tool. Missing objects refuse rather than being fetched. A
shallow repository, graft, unsupported entry or unreadable input refuses. The
destination must have a local `refs/heads/main`; its canonical public ancestry is
checked by the actual O3 checker on the candidate before a destination write.
Repository subdirectory inputs resolve to the worktree root (or bare Git root),
so an output beside the supplied subdirectory still counts as inside that input.
Use a verified O3 implementation and its matching private literals file, extracted
outside both inputs. Do not put that list in a public repository.

```sh
python3 -I tools/open-import/import.py tree \
  --source /path/to/ClosedWiz --commit SOURCE_COMMIT \
  --destination /path/to/OpenWiz \
  --checker /private/checker/tools/privacy-check/check.py \
  --literals /private/checker/literals.txt
```

The default is a dry run: no input object, ref, index or worktree changes. A
temporary, independent object store receives only the destination's reachable
history. Selected source blobs are read individually, with replacement objects
and lazy fetches disabled. No source refs, commits, notes, tags, history pack or
object-store link is copied. The temporary store is deleted on exit.

Successful JSON includes the candidate commit and tree, destination base, file
count, byte count, added/deleted/modified file counts, and the check's result.
Identical inputs produce identical commits and trees, using a fixed noreply
identity, fixed message and the destination base's timestamp. This is one ordinary
commit with exactly the destination `main` as its parent, including an unchanged
tree. Dry-run commit IDs are informational: their objects disappear with scratch.

`tree --write-local` additionally saves the checked commit's objects in the local
destination. It leaves every branch, HEAD, index and worktree untouched. Dirty
inputs are allowed: their committed bytes are read, and their local edits survive.
The JSON adds `saved: true`. Any later branch creation, push or PR is a separate,
gated cut-over action outside this tool.

Exit 0 means checked; exit 1 means refused/unreadable; invalid CLI arguments exit
2. On a candidate privacy refusal, JSON still reports size and diff counts with
`status: refused` and the full checker output, but no commit is saved. Earlier
input, ancestry/shape or patch-binding failures report an error on stderr. Git
stderr and source snippets are never printed. An existing public baseline can
contain text being replaced: the checker judges the candidate and its one-commit
range, rather than rescanning old baseline trees as newly published material.

## Reviewed carriage list

`paths.json` is the carriage list reviewed with this PR. `source` follows O1's
public code/docs/contracts/skills/test classes and its folder patterns. For the
current tree it explicitly adds the subsequent CI selection/hosted/escape code,
CLI docs, live-check procedures/tools, scale tests, skills evaluation and the
approved open-development tools. These are code or procedures under the same
public classes. New top-level folders and new tools need a list review: unknown
source paths refuse the import, even when their contents look public.

`keep` takes precedence over `source`. Only these destination files survive from
the old public tree: its README, changelog, licence spellings, contributing and
releasing guides. Their source counterparts are omitted. The plugin and
marketplace manifests are not kept: `source` carries them byte for byte
(#2428). Other old destination files are removed unless selected from source.
This intentionally preserves OpenWiz's own public installation/release wording.

Private classes and retiring paths are unconditionally excluded, including all
`private/`, grills except their README, the overflow/capacity tools and the PC
runner kit except its three explicitly public files (test runner, cache helper
and attributes). O3 checks all selected contents, paths and symlink targets with
the required named literals before final staging. Symlinks must resolve within
the selected public tree; absolute, escaping, private, cyclic and dangling links
refuse. Resolution traverses each symlink before applying later parent (`..`)
components, including repeated finite uses of an alias. Executable modes, binary
bytes and safe symlinks are retained. Submodules
are refused. SHA-256 Git repositories are currently unsupported.

## Public-file patch seam for O15 (#1283)

Use an exact source base/head range and the exact destination main that will
receive the patch. Patch generation is also a dry run, except for its explicitly
requested new output directory, which must be outside both input repositories.
This excludes every registered worktree of each input (primary and siblings),
plus its canonical Git and common directories, even if a linked worktree was
supplied. Git's NUL-delimited inventory preserves whitespace in worktree paths;
an unreadable or malformed inventory refuses. Containment is rechecked just
before artifact creation. Symlink aliases cannot bypass these exclusions.
The folder is owner-only; an existing folder refuses rather than overwriting a
previous reviewed artifact.

```sh
python3 -I tools/open-import/import.py patch \
  --source /path/to/ClosedWiz --source-base SOURCE_BASE --commit SOURCE_HEAD \
  --destination /path/to/OpenWiz \
  --checker /private/checker/tools/privacy-check/check.py \
  --literals /private/checker/literals.txt --output /private/reviewed-patch
```

The output is exactly:

- `public.patch`: ordinary Git binary diff, with full blob IDs and no source
  commit headers, message, author or history. Renames become deletion/addition.
- `binding.json`: `openwiz.public-patch.v1`, retained **privately**, with exact
  `source_base`, `source_head`, `destination_base`, expected destination `tree`,
  `patch_sha256`, `policy_sha256`, sorted changed public `paths`, and an `excluded`
  count for changed private/retired/preserved paths omitted from the patch.

The JSON command result supplies `binding_sha256`. Review both artifacts and
record that digest in O15's private move state; it is the required trust input to
reapplication. Never publish the binding or fetch a source branch into OpenWiz.
The binding is provenance for the reviewer, not a signature or an automatic
approval. Source base must be an ancestor of source head. Unknown changed paths
refuse; a range with no carried public changes refuses. Public paths with private
contents refuse even when the offending text was removed: both sides of the diff
are checked. Source diff-presentation settings cannot change the patch format.
Those early old/new scans include actual unchanged destination workflow files
and symlinks as context. A reusable workflow reference can therefore resolve
without adding that unchanged file to the patch. A genuinely missing reference
still refuses; the complete applied tree is checked separately afterward.

```sh
python3 -I tools/open-import/import.py apply-patch \
  --destination /path/to/OpenWiz --patch-dir /private/reviewed-patch \
  --binding-sha256 REVIEWED_BINDING_SHA256 \
  --checker /private/checker/tools/privacy-check/check.py \
  --literals /private/checker/literals.txt
```

Reapplication requires no ClosedWiz access. It verifies the reviewed binding
digest, strict binding shape, policy digest, current destination main, patch
digest, exact changed public paths and complete expected result tree. It applies
without three-way fallback, then checks the complete resulting tree, new commit
metadata and ancestry with O3. A conflict, stale main, edited byte, missing
checker/list or mismatched tree refuses before any destination change. There is
no retarget/retry/rebase or public PR creation. `apply-patch --write-local` saves
only the checked ordinary commit, with the same ref/index/worktree guarantees.

O15 may consume this seam only after its implementation/list are reviewed. It
still owns PR text checks, both tracker links, private mapping and publication
gates. The import/patch tool grants no migration authority.

## Per-PR carriage guard

`guard.py` keeps the carriage list from drifting (#2412). The `changes` job of
the required `ci` workflow runs it on every pull request and merge group:

```sh
python3 -I tools/open-import/guard.py --base=BASE_SHA --head=HEAD
```

It takes every path the change adds: present at head, but neither on the base
nor at the branch point. Renames count at their new name; deleted and modified
paths, and paths already on `main`, are not judged. Each added path is
classified with this importer's own `carries` and `private_or_retired`, loaded
from `import.py` rather than copied, against `paths.json` at head. It passes
when `source` or `keep` selects it, or a private/retiring class covers it.

Any other added path fails the check. The output lists every unclassified path,
one per line, and how to classify it in the same pull request: a public path
gets a matching `source` entry (the exact path, or its folder as `<folder>/**`);
a private path goes under an existing private class such as `private/`, or the
contract's private/retiring classes are extended in `import.py` for their own
review. Exit 1 is that refusal. An unreadable base, head or list, or a shallow
clone, fails closed with exit 2. Its proofs are `test_guard.py`, which the same
step runs first.

## Proofs and limits

```sh
python3 -I tools/open-import/test_import.py
cargo fmt --check
```

The CLI proofs use real Git and the real O3 checker, with synthetic history roots
set only in the test harness (the same technique as O3's own history tests).
No production root/anchor override exists. Fixture literals are synthetic;
real-main preparation uses the separately pinned actual checker and private list.

Fixture tests prove preparation, never publication or live acceptance. Privacy's
binary-image/personal-fact limitations remain review responsibilities. Current
real-main refusals are recorded under the ticket's owned private evidence, and
the whole-tree clean result belongs to O16 after the public-word tickets merge.
