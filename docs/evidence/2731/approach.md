# #2731 approach: a test for sealed_gh's seal-presence check

## Approach

One new `SystemGh` test in `tools/github-app/test_agent_token.py`, and no change to `agent-token.py`.
The test runs the whole `gh` path (`helper.gh`) five times through the existing `run_gh` seam. A fake
`fcntl.fcntl` passes every call to the real one, and only changes the answer to `F_GET_SEALS`: it
clears one seal (seal, shrink, grow or write, one per run), or none in the fifth run.

- A seal reported missing: gh is withheld with "the gh this run chose was changed", nothing is
  executed, and the token lookup is never reached.
- No seal cleared (the control): the same fake lets gh run from its sealed copy, so the fake itself
  is not what stops gh.
- Each run also asserts the exact reads of `F_GET_SEALS` and that the real copy held all four seals,
  so the refusal comes from the report and not from a copy that failed to seal.

Red is shown in a scratch worktree with `fcntl.fcntl(sealed, get_seals) & seals == seals and` deleted
from `sealed_gh`: the test must fail at its own assertion (gh ran with the token). The log is
`docs/evidence/2731/red.log`, with the temporary folder's path replaced by a synthetic one.

## Threat list

1. The seal read-back deleted or skipped: a copy the kernel reports as unsealed gets the token.
2. The read-back weakened to a subset of the seals (for example write only): covered by clearing
   each of the four seals on its own.
3. The refusal placed after the token lookup: covered by `looked=False` (no lookup happened).
4. A test that passes because the fake breaks sealing in general: covered by the control run and by
   asserting the real seals behind each faked answer.
5. A token in the test's output: the test uses the file's synthetic `TOKEN`, and `run_gh` already
   asserts it reaches no output, path or argument list.

## What the test can and cannot prove

- Proves: when `F_GET_SEALS` reports any one of the four seals missing, `sealed_gh` returns no copy
  and `gh` stops before the token lookup; with all four reported, gh runs from the sealed copy.
- Cannot prove: that a real kernel ever reports a missing seal after a successful `F_ADD_SEALS`
  (it should not; the check is defence in depth), or anything about a live system gh, macOS, or a
  kernel without memfd sealing. The missing seal is supplied by a fake, so this is a proof of the
  helper's reaction, not of kernel behaviour.

## Scope

Owned: `tools/github-app/test_agent_token.py` (shared: only the new test's lines). Supporting:
`docs/evidence/2731/` (this note and the red log). `agent-token.py` is not touched; #2872 and #2874
are changing it.
