# Releasing

Updated for <version>.

This process governs new OpenWiz publications. It supersedes the earlier
requirement to write the changelog fresh at export: its lines are written for
the public in product pull requests, then checked again before publishing.
Previously published versions and their changelog entries stay unchanged.

## Versions and evidence

OpenWiz, the PACP protocol and individual adapters have separate version lines.
A number records a change; it does not establish compatibility between them.
Each software release states its protocol dependencies, the exact external tool
and service versions tested, and the minimum build toolchain. An untested
dependency is not a compatibility claim. A 0.0.x release is a pre-release and
makes no compatibility promise. The 0.0.0 documents are a design preview, no
implementation.

A version has at most five meaningful outcomes, preferably one to three. Each
outcome describes something a user can see or check, with its claims and needed
evidence agreed before work starts. Release notes state what was tested and
what remains unproven. Fixture tests do not prove live behaviour; a formal proof
requires an actual formal proof. Do not claim an untested integration, an
unshipped command or protocol conformance without a conformance suite.

## Changelog lines

Every product ticket brings one `changes/<ticket>.md` file in its pull request.
The filename uses its positive decimal ticket number without leading zeroes.
The first line is `kind: <kind>`, followed by one blank line and one short public
sentence on one physical line, ending in punctuation and a newline. The kind is
one of `added`, `changed`, `fixed`, `removed` or `security`. There are no other
fields; the ticket's milestone supplies the version.

The builder writes the line while the change is fresh. The reviewer checks its
format, milestone and meaning against the change and its evidence: true,
user-facing, safe to publish and no stronger than what was proved. Examples are
synthetic; personal data, credentials, internal references and private links
never belong in the sentence. CI refuses a product change without its line.
Infra, documentation and tests use the `no-changelog` pull request label instead;
the reviewer checks that the exemption does not hide a product change.

At release, gather the version's lines under its agreed headline in
`CHANGELOG.md`, newest version first. Each entry has its version, approved ISO
date, headline, at most five short lines, a sentence saying what was tested and
what remains unproven, and a link to its GitHub Release page. If there are too
many lines, combine or drop them in the source through review; never silently
truncate them. Only published versions appear in the public changelog. Update
the short public roadmap with Now and Next, one line each, at the same release.

## Review and publication

The [release-on-demand policy](docs/adr/0020-release-on-demand.md) and
[release candidate contract](contracts/release-candidate.v1.md) govern the future
public-source path **after verified O17 cut-over**. Preparation may happen
beforehand. Editing this guidance activates nothing: O16/O17 prerequisites,
holds and separate authorization remain. The historical 0.0.0 releasing document
stays frozen; private-copy release work stays stopped except specifically
assigned O16 needs.

1. Prepare one candidate from the public repository's own history, with ordered
   included versions, complete matching compiled products/artifacts and exact
   changelog bytes. No private-to-public release copy. Keep all seven settled
   0.0.6–0.0.12 sections when shipping that combined release. Ordinary development
   review, plan approval and protected-main/required-check rules remain.
2. Resolve Jake's actual ship instruction and exact changelog approval from
   verified private decision records. Changelog approval may come first. These
   are the only human release actions; there is no export-plan, final-diff,
   standalone Sol-export, mandatory device/hands-on or second publish approval.
   A caller inventing an approval argument supplies no authority.
3. Require current candidate-bound CI, privacy/claims, product identity and
   agent-run combined live smoke evidence. Exercise every included version's
   promise end to end on that combined build. Sending, thread creation,
   App-permission and spending changes also
   require their relevant live results. Unknown risk or missing, stale, failed,
   unreadable or uncertain evidence blocks publication. Fixtures never prove live
   behaviour. Use only approved kits on their own throwaway targets, within
   existing counts, allowlists, App grants and spending; ship widens none of them.
4. Agents publish the exact checked public commit, approved notes and complete
   artifacts in version order once all gates pass. Verify immutable releases
   and required checks, annotated tag/commit, exact notes and every expected
   asset, manifest, checksum and alias by reading them back. No force-push,
   protected-source bypass, moved tag or rewritten published entry. Partial or
   uncertain writes stop for inspection; never automatically retry them.
5. Verify a matching normal user install/update on an already approved test
   machine. Measure from the original ship instruction through that verification,
   including any approval wait, queue, remaining checks/builds, publishing and
   download/update time. Preparation time is separate; resume never resets ship
   time. Strictly under 30 minutes passes the light timing target; a slower or
   blocked run records the miss or gap honestly. Jake's hands-on feedback follows
   publication. End on incomplete progress; no watcher, poll loop or sleep.

Published releases and tags stay locked. Older versions can receive missing tags
and release pages only under their separately approved historical backfill at
original checked public commits. A new release's ship instruction does not
authorize backfill. The existing release tool's legacy export/report and approval
flags are not evidence that the successor candidate path has been implemented.

## Fixes after publication

An ordinary fix ships in the next version. A privacy or security fix ships at
once as its own small version, with the correction noted in that new version's
changelog entry. Never republish an existing version with changed contents.
Every release retains the unmodified Apache License 2.0 text and all required
third-party attribution.

## Reviewed binary artifacts

For versions that offer prebuilt packages, review the exact three target bundles,
complete asset inventories, manifests and SHA256SUMS alongside the checked public candidate.
Review each archive's contents and skill/runtime text for privacy and licensing;
a hash alone does not establish a signed publisher identity. Keep the release
check's exact `release-asset` privacy/claims disposition for each new binary;
this is an automatic gate input, not a separate human export approval. Publish only the checked
bytes, with both versioned manifests and the identical target aliases used for
pull-only updates. The artifact workflow only assembles files and grants no
publication authority. A missing target or mismatched alias is an incomplete
release; do not advertise it as installable. Keep the source channel available.
