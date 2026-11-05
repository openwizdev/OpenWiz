# T6 self-update fixtures and proof plan

These fixtures are synthetic. They never contact GitHub, the PC, the Mac or
CloudRoom. Fixture tests prove local behavior only; T11 owns the live check.

The updater's seam is the fixture Git repository named by spec #262 and C5.
Tests create private temporary repositories with a `main` branch, merge real
synthetic commits, and retain the resulting commit ids as their expected
values. A non-main branch has a different commit to catch the wrong source.

| Claim | Named evidence to write, red first |
| --- | --- |
| A passing merge on main becomes the running build | C5 passing-merge fixture: observe the candidate's running identity after its build and complete test gate |
| A failing merge keeps the previous build running | C5 failing-merge fixture: deliberately break a candidate test, then observe the old identity and a `kept/test` result |
| Failure is recorded honestly | Compare the saved attempt, status and one recorded service-issue comment, including its exact first line, against contract literals and the service schema |
| A changed non-main branch cannot supply an update | Advance only a synthetic topic branch and assert no build or switch for that commit |
| The updater is pull only | Record outbound Git/build/test commands; prove no push, updater listener or inbound update route can trigger a switch |
| Nothing updates before activation | Before the fixture service is started, assert no fetch, candidate build, record or switch |
| A broken fetch, build or switch retains the old build | Inject each failure separately and assert its exact `kept` step without claiming the candidate runs |
| Private state stays private | Check 0700 directories/programs and 0600 files; plant public modes, symlinks and an incorrect clone remote and require refusal before use |
| Only a verified main candidate is executed | Check the fetched full commit, embedded build identity and selected build; reject an unexpected source or identity |

The build and test gate will use the project's complete ordered command set
from `docs/agents/fleet.md`, with one Cargo command at a time and a candidate's
own build directory. A failed command stops the gate before any switch.

The handover follows the ruling on #271: the existing singleton lock and S8
remain in place; changing a link alone never counts as a running candidate.
The process fixture simulates the existing unit's restart by stopping only its
own child and starting the current selection. It never calls systemctl.

The fixture repository contains copies of the production crate sources and the
service schema, with relative dependencies. Its adapted manifests omit the
repository's external test/example targets so its own gate cannot recursively
run the updater proofs. The npm portion is a recording fake over the public
executor seam: it accepts only the five exact web gate forms and writes a
synthetic owner-only export for the build. The Rust job therefore needs no
Node/npm; a missing tool cannot turn the deliberately failing Rust test into a
web-setup failure. Git and every Cargo gate command still execute for real.
The small web scripts and test verdict are synthetic;
the service runtime, startup transaction and embedded server are production
code compiled from the fixture's candidate commit. Each candidate uses its own
target directory. The fixture entrypoint injects a recording App sink and an
executor that refuses network work; production exposes no fixture environment.

Named proofs are in `tests/service/t6_update.rs`. They also check the existing
loopback HTTP listener is the only TCP listener of the service, IPv4 or IPv6
(`/proc/<pid>/net/tcp` and `tcp6`, by socket inode), and that a POST
to an invented update route is refused without an update. All of this is
fixture evidence. GitHub authentication, systemd, activation and PC behavior
remain T11's live acceptance.

The correction probes cover inherited diagnostics after candidate exec, an
explicit gate environment with synthetic service state and secrets absent,
checkout/cache removal on failed and passing gates, and pruning to the running
and previous builds while preserving an outside symlink target. Record fixtures
distinguish definitely-unsent delivery (safe retry of the same saved attempt)
from uncertain delivery (no repost), and resume an unclaimed ready record after
a process restart.

The live fixture status also exposes retrying/uncertain delivery and omits the
optional field after confirmed delivery. Shape tables compare the independent
schema checker with the strict reader; the saved state never gains this field.
