# WZ-P1 proof plan

All fixture contents, dates, object IDs and paths are synthetic. The package
JSON is an explicit structural tree example: `files` maps relative names to
UTF-8 contents; `executables` lists executable paths. Contract and licence
contents there are placeholders, never release inputs. Its lock/release IDs
illustrate the wire form, not a real published Git object.

Observable claims and evidence:

- Layout, version, manifest, changelog and pin agreement: validate the package
  example against the contract's normative block, with independent refusal
  examples for missing files, changed identities and invalid metadata.
- Standalone resolution and safe refusals: table of explicit reference examples
  with literal expected rule/file/line records. A plausible regression is treating
  project-setting hyperlinks as permitted runtime reads, or accepting a path
  that escapes the package. No previous WizSkills contract proof exists.
- Carried sources: read the contract's exact list and require every file to exist
  in the source `contracts/` directory. Byte-identical copy behaviour belongs
  to WZ2 (#2630), not this fixture test.
- Privacy and complete prose contract: independent review of the complete diff;
  public examples contain no private paths, real credentials or runtime IDs.

Command: `python3 -I tools/wizskills/test_contract.py` (Python standard library,
offline, reads only this contract, these fixtures and named carried sources).
Readiness: the fixture proof can run now; independent review follows the PR.

Red: `red.txt`, committed before the contract. Three assertions fail specifically
because the required contract does not exist; the duplicate-key check passes.
The checkout prefix in traceback filenames is removed for portable evidence.

The test validates declared examples, not reference discovery from arbitrary
source, Git transport, transactional installation, privacy scanning or live
harness support. Those remain WZ2, WZ3, WZ7, WZ9 and WZ11's proofs. No publication
or live operation is performed.

Helper: one precedent finder at `848e4f84170a607918c20c3eb0512454ce7facc0`;
12 reported items, 12 used as pointers after direct checks, none ignored or
found wrong. Sources inspected: `tools/skills-copy/copy.py`, its README,
`tools/install/install.py`, `contracts/install.v1.md`,
`contracts/release-candidate.v1.md`, `contracts/decisions.v1.md`,
`skills/README.md`, `skills/build-ticket/SKILL.md`, and downstream tickets.
Archived; no-push result: clean #2628, branches 0, comments 3. No helper wrote
any code, test or evidence.

## CI carriage correction

At the first PR head, the required carriage guard refused exactly
`tools/wizskills/test_contract.py` (1 of 7 added paths). Reproduced with
`python3 -I tools/open-import/guard.py --base=origin/main --head=HEAD`
before the correction. The CI run is
[43409989921](https://github.com/jparker2006/ClosedWiz/actions/runs/43409989921).
The explicitly authorized supporting edit adds that exact public source path
to `tools/open-import/paths.json`, so WZ-P1's owned fixture test can pass the
required carriage check. It classifies no other future file. PS1 removed the
policy checksum re-pin requirement; no checksum or importer rule is changed.
