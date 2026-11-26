# CloudRoom effort proof before the fix

Repeated `python3 -I adapters/cloudroom/test_driver.py Driver.test_kit_passes_all_five` with the App key unset and refusing agent CLI stubs first on the outer PATH. The tests supply their own fixture-only PATH to the driver.

```text
50 runs: 49 passed, 1 failed (cloud effort miss), 0 other failures
Run 26, cloud:
fail start: effort: medium never reached a process the run started
```

To isolate the missed sampling window, a separate diagnostic deferred the cloud kit's periodic scans until after the start call (the synchronous post-call scan and status-note checks were unchanged). All 10 runs failed with the same cloud effort miss.

The existing kit test can pass by sampling the short-lived spawn command. The regression proof checks the long-lived fake cloud worker instead; a successful start whose worker retains the effort only in its environment must fail the argv assertion.

```text
$ python3 -I adapters/cloudroom/test_driver.py Driver.test_cloud_worker_keeps_effort_after_spawn
FAIL: test_cloud_worker_keeps_effort_after_spawn
AssertionError: False is not true : the cloud worker lost the effort arguments after spawn
FAILED (failures=1)
```
