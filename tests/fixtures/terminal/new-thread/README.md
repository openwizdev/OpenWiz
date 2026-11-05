# Synthetic T6 fixtures

The executable CP7 cases in `tests/terminal/new_thread.rs` reuse the existing
schema-checked action reports in `tests/terminal/actions/` and inventory
responses in `tests/fixtures/terminal/envelopes/`. Dynamic op ids, bindings,
negative variants and private fake scenarios are constructed by the tests.

Synthetic assumptions: the catalogue order, offered settings, failures,
disconnects, target projects, reported start stages and timing of scripted keys
are controlled fixtures. They are not observations of a live account.

The actual-server cases use the normal synthetic inventory and v127 new-thread
catalogue/receipts, adding a synthetic GitHub remote in private state. Counts
check both spawn invocations and created threads. No test reads private
evidence or the live-kit docs. Optional rendered cell/HTML artifacts are outputs
only, under `OPENWIZ_T6_RENDER_OUT`, and prove fixture display only.
