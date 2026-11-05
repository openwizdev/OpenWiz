# Public CloudRoom setup: decision and consumer handoff

The sanitized decision behind
[contracts/public-cloudroom-setup.v1.md](../../contracts/public-cloudroom-setup.v1.md)
(ticket P2, #2201, of spec #2194). It grants no real CloudRoom download,
installation, sign-in, account change, message or publication. PR2 stays
Unverified until #2207 observes a real install and sign-in.

## Decision

- Jake, 2026-11-13: OpenWiz bundles CloudRoom's installation, with one CloudRoom
  sign-in screen and a short powered-by CloudRoom line. CloudRoom's founder is
  told as a courtesy afterwards; his answer, or none, never blocks this work, its
  merge or the release
  ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6847807740)).

The record was read back from the private repository on 2026-11-13, and that
repository's visibility was read as private the same day. The public form of
the approval is on #2201.

## Choices the contract makes inside the decision

These are interface details the decision left open. A reviewer can challenge
each one.

- **Install only on an explicit yes, from CloudRoom's own published links.**
  CloudRoom's agent install guide names one GitHub release link per platform.
  The tool requires that release's GitHub digest and its `SHA256SUMS.txt` line
  to agree before proposing anything, and the download to match before
  installing.
- **Never replace.** Any existing installation is reused as it is, so nothing
  is reinstalled, replaced or downgraded. On a platform with no checkable
  installer, CloudRoom's download page opens instead.
- **One sign-in, CloudRoom's own.** The tool opens CloudRoom's sign-in link
  once (or the app, before it has ever opened). Signed in shows only on
  CloudRoom's positive, current account read.
- **Powered-by wording:** exactly `Powered by CloudRoom`, as the last line of
  the CloudRoom step only, with no logo or link.

Nothing in the code, docs or tests waits for, asks for or records the courtesy
note's answer.

## Consumers

| Ticket | Takes from this |
| --- | --- |
| #1109 | Wires `runtime/cloudroom/cloudroom.py status`, `install` and `sign-in` into the install line and the install skill |
| #2207 | Observes a real install, reuse and sign-in with those commands on the installed candidate |
