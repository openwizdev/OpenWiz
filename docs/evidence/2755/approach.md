# Approach: #2755 (LR14), the frozen-head command's follow-ups R2, R4 to R8

Ticket #2755 under spec #2474. The findings come from the re-check of PR #2682 at `9db4bbe`. Every change is in `kernel/live-rig/heads.py`. Each one gets a red fixture in `kernel/live-rig/test_heads.py` and the fake `gh` in `kernel/live-rig/fixtures/heads/bin/gh`. No real `heads.py` run happens, with or without `--post`.

## Approach, one finding per step, red first

1. **R2, one verified identity.** The kit subprocess drops all five overrides unread: `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN` and `GH_HOST`. Its `gh` calls are then pinned to `github.com` with `GH_HOST=github.com`, because the kit's own `gh` commands take no `--hostname`. The login read through `gh api user` (same environment) is stored in `publish.json` as `login`. Before its first write, every publish, fresh or resumed, reads the signed-in login again and refuses on a mismatch. The fake `gh` logs every call's effective host and the token variables it saw, and the kit's GraphQL reads are no longer excluded from the assertion.
2. **R4, ambiguous cached window.** A 304 honours a `Link` next or last header if GitHub sends one. A 304 whose cached page is full (100 comments) refuses, because page one can stay byte-identical while comment 101 adds a newer marker. A 200 still decides from its own `Link` header. Each ticket still gets exactly one comments read. The fake pages at 100 like GitHub does, which replaces the old one-comment `HEADS_PAGED` split.
3. **R5, ambiguous comment POST.** Each pending comment gets a random run id when it is planned. The id is put in its body as a hidden `<!-- openwiz:heads-run <id> -->` line. Before the POST, the journal saves `tried` with the time. After a try with no saved URL, the resume first reads that PR's comments since the try (one REST read). It adopts a comment only if the author is the stored login and the run line matches. It refuses if the window is full. It POSTs again only if no such comment exists. The WizMarket fallback lookup asks for `state=open` and accepts exactly one pull request whose head label, base, title and body all equal the intended ones.
4. **R6, replay validation.** `publish.json` is checked as a whole before anything else: its exact keys and types, run ids, receipt paths, comment indexes and stored outcome. Every pending comment must equal what the rig's line filter and the credential check produce for its fenced kit lines, under the stored login and the `--settings` repository. Every receipt and the WizMarket text must pass the credential check. Any failure exits 2 with zero GitHub calls.
5. **R7, preview with a pending publish.** Without `--post`, an unfinished `publish.json` is validated (R6) and its pending comments and receipts are printed in the fresh-run preview format. The journal is not written, and `gh` is not called. The exit status is the stored outcome (R8).
6. **R8, exit status on resume.** The session outcome (0 or 1) is saved in `publish.json` before the first write. A resume returns it. The test covers a mixed 5+4 session (1) and an all-pass session (0).

## Threat list

- A token or host in the environment sends the kit's reads to another account or host while the receipt names the stored login (R2).
- The account switches between a lost write and its resume, so the old run's comments post as someone else (R2).
- A cached page one that is unchanged hides a newer authorised frozen head on page two, so an old head runs (R4).
- A lost POST response causes a second KN comment for the same run on resume (R5).
- A closed earlier WizMarket publication from the same head is adopted as this run's pull request (R5).
- A hand-edited or corrupted `publish.json` posts a credential shape or a private value (R6).
- A plain preview leaves a pending journal unreadable, or changes or deletes it (R7).
- A resumed publish hides a failed host behind exit 0 (R8).
- A fixture mistake reaches a real agent CLI or a real GitHub host. Every test puts 37 refusing stubs first on `PATH`, and `gh` is the fixture's fake.

## What the tests can prove and can't

They can prove that `heads.py`, against the fake `gh` and the fixture kit, drops and pins the environment it gives every `gh` call (the kit's included), refuses the listed ambiguous or tampered states before any write, makes exactly one POST per run across a lost response, and returns the stored outcome.

They can't prove real GitHub's behaviour: whether a real 304 carries `Link`, whether `since=` and the pulls `head` filter behave exactly as the fake models them, or how gh picks an account on a real machine with several stored logins. Those wait for the rehearsed VPS session (#2583, after this and #2689 merge). They also can't prove the run-id line survives every GitHub rendering. The match is on the raw body that the REST API returns, and the fake returns it unchanged.

## Round 2 addendum: R1 to R3 of the review at `528ede5`

A fresh builder fixes these three once, red first. Each one is a new red fixture in `test_heads.py`.

- **R1, overrides read before the filter.** `stored_login_env()` called `os.environ.items()`, which fetches every value, so the five blocked overrides were read into heads.py before the filter dropped them. The fix iterates the names only and reads only the allowed ones. Same cause, same fix: `git()` copied the whole environment with `dict(os.environ, ...)`, and the `receipt.py` subprocess inherited it unfiltered. Both now get the filtered environment. Proof: an instrumented mapping in place of `os.environ` records every value lookup, and no blocked name may appear. The child-environment and wrong-account tests stay.
- **R2, an edited comment posted twice.** Resume treated "same body" as "same run", so a KN comment edited after a lost POST answer (its marker and author unchanged) looked absent and was posted again. The fix reads every comment page of the PR, up to 30 pages of 100 and refusing beyond that (no `since=`, so no local-clock lower bound), and looks for this run's exact marker under the stored login first. Exactly one unchanged comment is adopted. A marked comment with changed text, or more than one, is refused before any POST with a fixed message that quotes no remote text. Proof: the edited-remote fixture.
- **R3, private text in a replayed receipt.** Replay checked a pending receipt only against the credential pattern, so appended lines (the private throwaway repository name, say) could reach a public WizMarket receipt. Each receipt now names its run record. Before any write, the receipt is rebuilt from that record with `receipt.py`'s own `receipt()` (its header and kit-line rules, private-id and credential limits, `listings.json` and host config checks), with the journal's verified login as the only run-by value. It must equal the stored path and text byte for byte. The record must also match its linked comment: same PR, head and kit lines. Proof: the appended-private-text fixture.

What the tests can't prove:

- R1: the operating system still hands the whole environment block to the process at start. The fix only stops heads.py from turning the blocked values into Python strings or passing them on. The test proves no lookup through `os.environ`. It can't prove a library or the interpreter never reads `environ` itself.
- R2: that real GitHub returns the marker line byte-identical after a web edit that keeps it, or that paging with `page=` is stable while comments are being added. The fake models both. A comment whose author deleted the marker can't be told apart from no comment, so it gets a second POST. That needs the stored login's own edit, and the post is still that login's.
- R3: the run record under `--out` is local and as editable as the journal. Rebuilding from it bounds the receipt to `receipt.py`'s contract (no extra lines, public tokens only), not to what really ran.
