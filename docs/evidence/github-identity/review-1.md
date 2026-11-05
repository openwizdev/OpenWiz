# GI7 review round 1: red runs

Review of #2689 at `9a26acb00507d1e9925a7af00ff18fcdbcddf55a`. Every value is synthetic. Temporary folders are shown as `$work`.

## R2: the fallback lost the account's credential

The documented steps, run literally with a fake `openwiz` that refuses (exit 5) and `GH_TOKEN=synthetic-user-token`:

```text
after the failed mint: GH_TOKEN is empty
after the documented fallback: GH_TOKEN unset; before: set
```

After the fix, `sh docs/evidence/github-identity/fallback-check.sh` runs the documented block itself:

```text
ok   GH_TOKEN synthetic-user-token, mint fail: shell=synthetic-user-token app=synthetic-user-token 
ok   GH_TOKEN unset, mint fail: shell=unset app=unset 
ok   GH_TOKEN synthetic-user-token, mint ok: shell=synthetic-user-token app=synthetic-app-token-2549 synthetic-app-token-2549
ok   GH_TOKEN unset, mint ok: shell=unset app=synthetic-app-token-2549 synthetic-app-token-2549
```

## R3: the stderr gates accepted repeated notices

A mutant `loop.sh` that prints the no-secret notice twice. Before the tighter predicates, `TEST_ONLY=fleet-loop sh skills/launch-fleet/scripts/test.sh` gave `2 cases, 0 failed`, and `test-loop.sh`'s `run` passed. Only its exact-count identity case failed. After them, the same mutant gives:

```text
test-loop 1 after 0 ok
4 cases, 3 failed      (TEST_ONLY=loop)
2 cases, 1 failed      (TEST_ONLY=fleet-loop)
```

## R1, loop side: the check was not told it reads as the App

`test-loop.sh`'s fake `gh` records the token and the identity each call gets. Before `loop.sh` exported `LAUNCH_FLEET_GITHUB_AUTH=installation`, the App case failed at its claim (`sh -x`):

```text
+ grep -vx synthetic-app-token-2549 installation $work/gh-token.log
+ [ -z synthetic-app-token-2549 account
```

The probe side (`fleet.sh`, `fixtures/gh.py` and three `test.sh` cases) was approved provisionally under J36. With the `fleet.sh` change undone, `TEST_ONLY='GI7: an unchanged spec read with an App token reads no GraphQL' sh skills/launch-fleet/scripts/test.sh` gives `FAIL ...: run 3 read GraphQL 4 times`.

With it, the three GI7 cases pass (`1 cases, 0 failed` each): an unchanged spec read with an App token reads no GraphQL, another installation gets a full read, and a switch from the account to the App gets a full read. All sixteen GI1 cases still pass.
