# Approach note: #2844 (EF16), an unknown provider's effort gets driver v1's exact refusal

## Approach

A start with `effort` first runs `room-cli provider models <provider> --json`, where `<provider>` is the one the driver
itself sends: the start's `harness`, already checked against its pattern and the kit's credential check, or its fixed
Cloudroom name (`claude` is `claude-code`). Today any failure of that lookup gets the fixed lookup-failure words.

The change classifies one outcome of that one call, and nothing else:

- `room-cli` exits exactly 1, prints nothing on stdout, and its whole stderr, trailing whitespace removed, equals
  `Unknown provider <provider>. See room-cli provider list.`, built by the driver from the provider it sent.
- That outcome becomes a fixed internal classification, never text taken from stderr. The answer is driver v1's
  refusal: `next` is exactly the refusal text, and `error` is fixed words with the start's own `harness` and `effort`
  fields, which the driver validated before the lookup. Nothing is saved or spawned.
- Every other outcome keeps today's fixed lookup-failure words, unchanged: another exit code, any stdout, a timeout,
  a signed-out answer, or a stderr that differs from the expected line by any character.

The comparison is exact equality against a string the driver built, so no part of stderr is ever copied, sliced or
interpolated into `error` or `next`. The other commands (`spawn`, `tell`, `archive`, `list`, `show`) keep their
existing classification; the new one applies only to `provider models`.

## Threats

1. **Stderr text reaching the answer** (R17). The answer's only variable parts are the validated `harness` and
   `effort` fields. A stderr carrying a synthetic credential gets the fixed lookup-failure words, and the test checks
   the credential appears nowhere in the JSON.
2. **A mismatched provider name in the diagnostic.** `Unknown provider <other>` for a provider the driver did not
   send is not this start's answer. It is not equal to the expected line, so it gets the fixed lookup-failure words.
   The name in it never reaches the answer.
3. **A genuine lookup failure misread as unknown.** A signed-out answer, a timeout, a non-1 exit, any stdout, or a
   near-miss line (a longer or shorter name, extra text before or after it) all keep the fixed lookup-failure words.
4. **A credential-shaped provider name.** The provider comes only from the start's `harness`, which the kit's
   credential check refuses before `room-cli` runs, so a credential-shaped name never reaches the lookup or the
   expected line. The answer echoes the harness the caller sent, never the diagnostic's copy of it.

## What the tests can and cannot prove

They can prove, on the synthetic `fixtures/room-cli`, that the exact diagnostic for the provider the driver sent
gets the exact refusal, with nothing saved or spawned; that each near-miss and mismatched diagnostic keeps the fixed
lookup words; and that a synthetic credential in stderr never reaches `error` or `next`.

They cannot prove that a real `room-cli` prints exactly that line. The line is the one the fixture already prints for
`room-cli`'s unknown-provider diagnostic. If a later `room-cli` rewords it, the driver falls back to the fixed
lookup-failure words (fail closed: nothing starts), not to a wrong refusal. They also cannot prove live behaviour;
EF7's live check covers a known provider.
