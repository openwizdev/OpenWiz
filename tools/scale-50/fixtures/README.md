# Synthetic report fixtures

`workload-v1.json` fixes FA3's scale schedule and declares its synthetic
assumptions. Those assumptions also apply to `report-v1.json`: a hand-authored
consumer example, not an observed load run. Its request totals, distributions,
role interval and candidate identities are literal invented values for reader
and comparator proofs. No live response or identifier is retained.

Actual synthetic measurements are written separately by the FA3 invocation.
They carry `evidence_class: fixture`, frozen workload/tool/config identities and
explicit coverage/gaps. Neither fixture establishes live capacity.
