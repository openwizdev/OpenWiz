# OpenComputer driver

Login: held by OpenComputer

Work in progress (#2587): this folder is still the [driver template](../template/README.md), copied and renamed, so the kit's red run against it is on record in `evidence/red-kit.txt`. It does not yet reach OpenComputer: the host's management API takes its key in an `x-api-key` header, and the key helper sends only `Authorization: Bearer`, so the ticket's open question on the header form is asked first.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.
