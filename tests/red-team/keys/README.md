# Key handling copy (RT8 of #3943)

A disposable copy of key handling for huntr's attack mode: a fake key store on `127.0.0.1` that holds only canary keys, one per host in [`kernel/driver-kit/hosts.json`](../../../kernel/driver-kit/hosts.json), with the [key helper](../../../kernel/driver-kit/hostkey.py) pointed at it. Attack this copy, never a live key, keychain or host.

```sh
python3 -I tests/red-team/keys/store.py devin        # prints its origin, then one JSON line per request it sees
echo '{"host":"devin","method":"GET","path":"/v1/sessions"}' |
  env -i PATH=/usr/bin:/bin OPENWIZ_HOSTKEY_TEST_ORIGIN=<origin> python3 -I tests/red-team/keys/loopback.py
python3 -I tests/red-team/keys/test_store.py         # the copy's own test
```

- **The store** (`store.json`): every key has the form `openwiz-canary-<host>-not-a-real-key`; `store.py` refuses to load anything else. A canary found anywhere but the helper's `Authorization` header proves a leak.
- **The fake host** (`store.py`): gives the canary on the helper's test-key path, answers every other request `200 {}`, and logs it with `authorized` (the canary arrived in the helper's header) and `leaked` (the canary was in the path, the body or another header).
- **The guard** (`loopback.py`): runs the key helper, or any script it is given, so that it can resolve and reach only localhost and start no other program, such as a keychain tool. The store's own process can reach only localhost too.
