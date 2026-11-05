# Changelog lines

Every ticket that changes the product brings one file in its pull request.
The builder writes it while the change is fresh; the reviewer checks it like
code. Release tools gather the sentences for a version into its public entry.
This file is the contract for those writers, reviewers and readers.

## Format

- **Product change:** a change to the product's code, web app or contracts; skills, CI, docs, tests and evidence are not product changes and use the label instead.
- **File:** `changes/<ticket>.md`, where `<ticket>` is the positive decimal ticket number without leading zeroes, not the pull request number; one file per product ticket.
- **Fields:** UTF-8 text: `kind: <kind>` on the first line, one blank line, then the `sentence` on one physical line, ending with a newline; no frontmatter delimiters, extra fields, headings, bullets or additional lines.
- **Kinds:** exactly one lowercase value: `added` (new capability), `changed` (existing behaviour changes), `fixed` (a bug corrected), `removed` (a capability removed), `security` (a privacy or security correction).
- **Version:** the ticket's milestone supplies the version; there is no version field in the file, and the filename carries no version. A missing or non-version milestone cannot assign a product line to a release: ask on the ticket rather than guess.

The sentence is one short, complete public sentence ending in `.`, `!` or `?`.
Use plain text, with inline code for a command or option if it helps the reader.
Keep it about a result the user can see or check, not the implementation work.
Choose the kind that best describes that result; do not put several changes or
kinds in one file.

## Writing and review rules

- Say what this ticket makes true, no stronger than its evidence. A fixture test proves behaviour on fixtures; it never proves the feature works on a real account or machine. State that limit in the sentence when it matters.
- Write for the public from the start. No private context, transcripts, credentials, personal data, private links, real identifiers, internal ticket or pull request references, or evidence paths belong in the sentence. Examples are synthetic.
- Infra, docs and tests use the `no-changelog` pull request label instead of a product line. The label is not a way to exempt a product change; reviewers check the reason for it.
- Add or correct the line in the same pull request as the product change. Use its owned path, or a current, explicitly approved supporting envelope that covers this exact changelog edit; for an envelope edit, record the acceptance criterion, supported owned path and why the edit is necessary. If neither authority covers `changes/<ticket>.md`, ask on the ticket for that exact path before editing it. An envelope does not authorize changes to this contract or any other protected rule, and does not widen an older approval. Keep the line accurate through review.
- The reviewer checks the name, format, kind, milestone and public sentence against the diff and its evidence. A missing or wrong required line is a finding, graded under the usual review rules; a syntactically valid line can still be false, private or unsupported.

These files are inputs to a release, not proof that it was published. Gathering
and publishing do not weaken the export's privacy and claim checks. Published
entries never change: an ordinary fix belongs to the next version, and an urgent
privacy or security fix gets its own small version. This contract does not
change the frozen `release/openwiz/` files or authorize publishing.

## Format examples

All ticket numbers and behaviour below are synthetic. Good format alone says
nothing about whether the sentence is true.

### Good: changes/4101.md

```text
kind: added

You can export the inventory as a JSON file.
```

### Good: changes/4102.md

```text
kind: fixed

On synthetic fixtures, cancelling an export leaves the existing file unchanged.
```

### Bad: unknown kind

Use one of the five kinds, not a synonym.

```text
kind: improved

You can export the inventory as a JSON file.
```

### Bad: missing sentence

A kind alone gives the release reader nothing to publish.

```text
kind: fixed

```

### Bad: extra version field

The version comes from the ticket's milestone.

```text
kind: added
version: 0.0.99

You can export the inventory as a JSON file.
```

## Editorial examples

Assume each stated piece of evidence exists for the synthetic example.

| Bad sentence | Why it fails review | Better sentence |
| --- | --- | --- |
| Improved export internals. | An activity, with no result for the user. | Cancelling an export leaves the existing file unchanged. |
| Export works on every account. | Only synthetic fixtures were tested. | On synthetic fixtures, cancelling an export leaves the existing file unchanged. |
| Fixed ticket #4102 using the private review notes. | Internal references and private context, even though the format parses. | Cancelling an export leaves the existing file unchanged. |
| You can export the inventory as a JSON file. | The ticket only previews an export; writing a file is unproven. | You can preview an inventory export without writing a file. |

Keep proof details on the private ticket or pull request; the public sentence
must stand on its own. Review both truth and evidence strength before it merges.
