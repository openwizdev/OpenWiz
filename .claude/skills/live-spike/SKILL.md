---
name: live-spike
description: Run a read-only discovery spike on the PC or Mac (structure only) before writing procedures or fixtures for any live claim, under Jake's standing approval. Use at the start of any version that reads or writes real CloudRoom data.
---

# Live spike

**This is PDD done fully:** find out what is really there before writing the tests and procedures that depend on it. 0.0.1 lost days to wrong assumptions: tool locations, `--limit` returning the oldest events, the version format changing.

**Where it runs** ([ADR 0015](../../../docs/adr/0015-live-tests-on-the-pc.md)).

Jake, 2026-11-01: full live tests use the PC, with a quick Mac check per release ([private record](https://github.com/jparker2006/ClosedWiz/issues/555#issuecomment-6565395635)).

Full live tests run on the PC (the approved live-test host), from a Local thread there. Jake approves each live step from any device; use throwaway test threads only.

Each release also gets a quick Mac check: a few minutes when Jake is at the Mac (install that version, `openwiz ls` and `openwiz show` read-only, nothing written), recorded with the release.

The Mac-only checks stay on the Mac: the Mac's fixed `room-cli` location, adding the Mac to the PC's CloudRoom, and the Mac shut for a day.

The standing approval for read-only discovery spikes covers the PC as well as the Mac.

Jake, 2026-10-27: bounded read-only discovery spikes are approved, subject to the recorded limits and revocation ([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704794292)). The PC extension is the 2026-11-01 decision above. Read the current standing approval in the configured private repository each time; ask the orchestrator if it is unavailable. A historical pointer never renews a revoked approval.
- **On the PC:** run from a Local thread there, using its bundled `room-cli` at the location verified in the private machine record. Probe the machine the claim concerns; a PC observation never proves Mac behaviour, or the reverse.
- **On the Mac:** `room-cli mac run` **without `--write`**, with every Mac command starting with:

  ```sh
  export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH";
  ```
- **Allowed calls:** `--version` and `--help`; the reads on OpenWiz's allowlist; `thread count --json`; `thread log --json` with `--limit` or `--after-seq` (at most 100 events per call); and reading `room-cli`'s own code files, never a credential or configuration file.
- **Limits per spike:** at most 200 calls, 30 minutes, and 20 sessions read by id.

**How:**
1. **Write one script** that does every read, masks and scans **on the machine being probed**, and prints **structure only**: keys, types, nullability, enum labels, counts, exit codes, error-line shapes (digits → 9, letters → a), timings and flag behaviour.
2. **Never print** values, ids, titles, content, paths, account names or hosts.
3. **Make the scan's own words safe.** The first v127 spike stopped three times because its placeholders ("key", "1/1") matched real content. Test the script against a fake that plants every output word in titles.
4. **Run it once.** A scan hit stops the spike. A new spike needs a fixed script and the orchestrator's approval.
5. **Compare** with the last recorded shapes, and write `shapes.md` under the version's evidence: same, changed, added, retyped, new labels, and what OpenWiz relies on.

Keep the script, shapes and any stopped-run note in the configured private repository's version evidence. The orchestrator can provide the existing private spike examples. Public summaries contain only structure and technical conclusions, never exact user words, thread ids, machine details or private file links. A public decision names its date and verified private-record comment pointer; exact answers stay private. A discovery spike never proves acceptance.
