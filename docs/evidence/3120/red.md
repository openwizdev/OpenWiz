# Red run on the base driver

The three new cases, run with the base `adapters/local/driver` (memory case skipped: that host already starts processes at `oom_score_adj` 500; it runs under `CI`).

```text
test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) ... 
  test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v2] ... FAIL
  test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v2 parent] ... FAIL
  test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v1] ... FAIL
test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) ... FAIL
test_on_linux_a_turns_shells_go_first_under_memory_pressure_and_the_harness_keeps_its_default (__main__.Local.test_on_linux_a_turns_shells_go_first_under_memory_pressure_and_the_harness_keeps_its_default) ... skipped 'this host already starts processes at oom_score_adj 500 or more'
test_with_no_cpu_quota_or_without_proc_as_on_macos_the_turn_environment_is_unchanged (__main__.Local.test_with_no_cpu_quota_or_without_proc_as_on_macos_the_turn_environment_is_unchanged) ... ok

======================================================================
FAIL: test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v2]
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<checkout>/adapters/local/test_driver.py", line 683, in test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins
    self.assertEqual({k: self.probed(env=env, program=program)[k] for k in CPU}, dict.fromkeys(CPU, '2'))
AssertionError: {'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None, 'CARGO_BUILD_JOBS': None} != {'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2', 'CARGO_BUILD_JOBS': '2'}
- {'CARGO_BUILD_JOBS': None, 'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None}
?                      ^^^^                     ^^^^                      ^^^^

+ {'CARGO_BUILD_JOBS': '2', 'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2'}
?                      ^^^                     ^^^                      ^^^


======================================================================
FAIL: test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v2 parent]
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<checkout>/adapters/local/test_driver.py", line 683, in test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins
    self.assertEqual({k: self.probed(env=env, program=program)[k] for k in CPU}, dict.fromkeys(CPU, '2'))
AssertionError: {'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None, 'CARGO_BUILD_JOBS': None} != {'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2', 'CARGO_BUILD_JOBS': '2'}
- {'CARGO_BUILD_JOBS': None, 'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None}
?                      ^^^^                     ^^^^                      ^^^^

+ {'CARGO_BUILD_JOBS': '2', 'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2'}
?                      ^^^                     ^^^                      ^^^


======================================================================
FAIL: test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins) [v1]
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<checkout>/adapters/local/test_driver.py", line 683, in test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins
    self.assertEqual({k: self.probed(env=env, program=program)[k] for k in CPU}, dict.fromkeys(CPU, '2'))
AssertionError: {'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None, 'CARGO_BUILD_JOBS': None} != {'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2', 'CARGO_BUILD_JOBS': '2'}
- {'CARGO_BUILD_JOBS': None, 'OMP_NUM_THREADS': None, 'PYTHON_CPU_COUNT': None}
?                      ^^^^                     ^^^^                      ^^^^

+ {'CARGO_BUILD_JOBS': '2', 'OMP_NUM_THREADS': '2', 'PYTHON_CPU_COUNT': '2'}
?                      ^^^                     ^^^                      ^^^


======================================================================
FAIL: test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins (__main__.Local.test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<checkout>/adapters/local/test_driver.py", line 686, in test_a_cpu_quota_sizes_the_turns_workers_and_an_owner_set_value_wins
    self.assertEqual({k: probe[k] for k in CPU}, {'OMP_NUM_THREADS': '7', 'PYTHON_CPU_COUNT': '2',
AssertionError: {'OMP_NUM_THREADS': '7', 'PYTHON_CPU_COUNT': None, 'CARGO_BUILD_JOBS': None} != {'OMP_NUM_THREADS': '7', 'PYTHON_CPU_COUNT': '2', 'CARGO_BUILD_JOBS': '2'}
- {'CARGO_BUILD_JOBS': None, 'OMP_NUM_THREADS': '7', 'PYTHON_CPU_COUNT': None}
?                      ^^^^                                              ^^^^

+ {'CARGO_BUILD_JOBS': '2', 'OMP_NUM_THREADS': '7', 'PYTHON_CPU_COUNT': '2'}
?                      ^^^                                              ^^^


----------------------------------------------------------------------
Ran 3 tests in 32.580s

FAILED (failures=4, skipped=1)
```
