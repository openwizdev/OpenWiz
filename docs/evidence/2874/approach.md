# #2874 approach: a mint that loses its folder keeps the new token for a later revoke

## Approach

`token_for` in `tools/github-app/agent-token.py` already knows when a mint's answer could not be stored (`stored = False`). Today that path goes straight to the emergency `DELETE /installation/token` with no copy, so a refused DELETE leaves the token live and unfindable.

The change is in that path only:

1. Before the DELETE, open recovery storage: the same private folder when it is still linked, otherwise `recovery(env)`, which walks the configured path again through `Private(create=True)` and so recreates the folder under the same checks as every other use (no symlink, outside every Git tree, parents only the owner or root can change, a 0700 directory the owner owns).
2. Under the folder lock, `keep` the token there as `kept-<request>-<random>.json`, 0600, written by the existing temp-file-and-rename `Private.write`.
3. Only then make the emergency DELETE, through `revoke_held(target, …)`: a 204 removes the copy, anything else leaves it.
4. On a refusal, check again before saying anything: walk the configured path once more through `recovery(env)`, and under its lock confirm that `kept_tokens` there still holds this token, writing the copy again if it went while the DELETE was pending. The first save is only a promise about the moment before the HTTP call; this check is what the message rests on.
5. The refusal line says which happened: revoked; not revoked but a copy a later revoke can find exists now; or not revoked and no such copy (storage could not be rebuilt or verified), which tells the owner to suspend the installation.

Nothing new is needed for finding it: `revoke` reads the request's `kept-` files through `kept_tokens`, and every later mint of the request DELETEs its live `kept-` tokens after it stores its own. Both drop the copy on 204 and ignore it once expired. This is the route `rescue` already uses for a run whose folder went (#2732 R4).

## Threats

- **A refused or unreachable emergency DELETE leaves a live token nobody holds** (the ticket's bug). Closed by saving before sending.
- **The recreated folder is not ours** (a symlink, another owner's directory, group or world access, inside a Git tree). `Private` refuses each; then no copy is written, the DELETE is still tried, and the message says to suspend the installation. The token is never written to unverified storage.
- **The token leaks through the message, a log or an argument.** The refusal line is fixed text plus a fixed reason; the token only goes to the 0600 copy and the `Authorization` header.
- **The copy is handed out as a usable token.** `kept-` files are read only by revoke paths; no mint, `gh` or git path serves them (kept from #2732).
- **The folder or the copy goes while the DELETE is pending** (#2880 R1). The message is decided after the DELETE, from a fresh walk of the configured path, never from the earlier save; a missing copy is written again into verified storage, and if that fails the line says to suspend the installation.
- **A copy outlives a successful DELETE.** `revoke_held` unlinks every holder of the token on 204, under the lock.
- **PR #2876 (#2872) edits the same file.** It changes `run`'s snapshot name and `retire`; this change touches neither, and the new test goes inside `FinalRound`, not after it.

## What the tests can and cannot prove

Can, on fakes (a fake token service, a fake GitHub API on loopback, synthetic tokens):

- With the folder deleted mid-mint and the emergency DELETE refused, one 0600 `kept-` copy exists in a recreated 0700 folder, it was there when the DELETE arrived, a later `revoke` finds it, DELETEs that token once and removes the copy, and a later mint does the same.
- With the DELETE answered 204, no copy remains.
- With the folder or the copy removed while a refused DELETE is pending, a copy is written again and a later `revoke` finds it; with a symlink planted in the folder's place, nothing is written through it and the line says to suspend the installation. The planted symlink is the fixture for storage that fails verification, at the first save and after the refusal.
- No output, call or file outside the private copy carries the token.

Cannot:

- That GitHub's real API revokes the token, or how it answers a second DELETE. Live behaviour is GA5's.
- A full disk: `findable` treats any `OSError` as no copy, so it ends in the "suspend the installation" line, but no test fills a disk.
- A folder removed after the final check; nothing on the host can rule that out, and the line describes the state at the check.
- That an expired copy is ever deleted from disk: it is ignored by every reader, as before; cleanup of expired `kept-` files is not this ticket's.
