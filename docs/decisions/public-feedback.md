# Public feedback and sharing: decision and consumer handoff

The sanitized decision behind [contracts/feedback.v1.md](../../contracts/feedback.v1.md)
(ticket P4, #2203, of spec #2194), and what each later ticket takes from it. This
record decides an interface only. It sends no feedback, posts no reply and grants
no live, account, spending or publication authority. PR7 stays Unverified.

## Decisions

- Jake, 2026-11-10: feedback goes to a GitHub issue on the public OpenWiz
  repository, created by the user's agent after it shows the user the exact text
  and destination and gets a yes, carrying only content the user chose and
  nothing private ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6763149732)).
- Jake, 2026-11-13: confirmed that route as written, through the user's own
  GitHub login after an exact preview and an explicit yes; and added the receiver
  side: his agent reviews incoming feedback issues, queues each for his approval,
  and then replies to the user ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6845243425)).

Both records were read back from the private repository on 2026-11-13; that
repository's visibility was read as private the same day. The destination,
`openwizdev/openwiz`, was read as public, unarchived and with issues enabled on
2026-11-13. A consumer re-reads the destination at every preview: this read is
not evidence for later.

## What was decided, in short

| Question | Answer |
| --- | --- |
| Destination | One issue on `openwizdev/openwiz`; no other transport |
| Who submits | The user's own agent, through the user's own existing GitHub login |
| Not used | The OpenWiz GitHub App, Jake's or OpenWiz's credentials, a token given to OpenWiz, a new login, a server route |
| Consent | An exact preview of destination, account, title and whole body (with its visible marker), then one explicit yes for one attempt |
| Content | Only the title and body the user chose; nothing collected around them |
| Outcomes | `sent` (issue read back), `failed` (proven not created), `uncertain` (anything else), reconciled before any further attempt |
| Sharing | Preview, then copy, of editable text and one allowlisted public URL; separate from feedback; never sends |
| Receiver | Jake's agent reads feedback issues as untrusted data, queues a review and an exact reply, and posts it only after Jake's yes |

## Choices this contract makes inside the decision

These are interface details the decision left open; a reviewer can challenge
each one.

- **A visible marker** (`OpenWiz feedback operation <operation_id>`) as the body's
  last line. A user who is not a repository collaborator cannot set labels, so a
  label cannot identify feedback; the marker also lets reconciliation find the
  operation's own issue. It carries only a random id.
- **Failed is narrow:** only a complete 401, 403, 404, 410, 422 or 429 response.
  Everything else is uncertain, and there is no reconciliation result that turns
  uncertain into failed in this version: an uncertain operation is never sent
  again, and the user can check the issue list themselves.
- **One account check by numeric id,** not login alone, so a renamed or
  switched account cannot reuse a consent.
- **Share allowlist** of the repository URL and destination issue URLs only. The
  public site's address is not yet recorded in a contract, so it is not on the
  list; adding it is a revision of the contract.

## Consumer tickets

Both are in #2194's approved revision 8, with native links already in the graph
(read 2026-11-13). Neither starts its live part here.

| Ticket | Builds | Relies on | Native links | Proof it owes |
| --- | --- | --- | --- | --- |
| #2292 (P14) | Sender and sharing: the packaged `feedback` skill and its offline operation helper; the app's chosen-public-content handoff and share affordance | `contracts/feedback.v1.md`, `contracts/first-hour.v1.md`, its schema, `contracts/setup.v1.md`, `contracts/web-api.v1.md`, `contracts/open-development.v1.md` | blocked by #2203 and #2200; blocks #2204, #2205, #2206, #2207 | The contract's sender and sharing rows, red first, on recording GitHub and clipboard seams; it settles the first-hour `feedback` gate only after its verified merge |
| #2557 (P16) | Receiver: the packaged `feedback-triage` skill, its queue, review and reply helper | `contracts/feedback.v1.md`, `contracts/open-development.v1.md` | blocked by #2203; blocks #2208 | The contract's receiver rows, red first, on a recording GitHub with synthetic injection-style issues |

The installed journey (#2204), pages (#2205), independent security review
(#2206) and integrated acceptance (#2207) keep their own gates and depend on #2292
as a native producer. A real feedback issue, reply or share needs its own
explicitly authorized synthetic live check with a known destination.

## Seams left for the consumers

- **The issue shape** and the marker line, for #2292 to write and #2557 to
  recognize.
- **The phase table** (`draft` to `uncertain`) for #2292's private operation
  record.
- **The proof table** of the contract, as the cases each consumer's tests cover.
