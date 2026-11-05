# Offline engine fixtures

The behavioral fixtures are inline in `tests/service/notifications_engine.rs`,
`tests/notifications/policy.rs` and `tests/notifications/durable.rs`.
All values, bindings, source times, provider results and protected state are synthetic.

synthetic_assumptions:
- An independently verifying injected owner supplies SourceFact and an exact
  content binding over saved proposal wording/risk/target; no production source
  binding or full installed proposal authority is claimed.
- A fixture-only DeliveryBoundary reports ready prerequisites and delegates effects
  to T1's RecordingDelivery. RecordingDelivery itself remains unavailable.
- The fixture binding verifier represents an already provisioned protected binding;
  it performs no provisioning, permission prompt or provider call.
- A test subprocess writes a synthetic provider receipt and exits at named crash
  points. This proves local journal behavior, not external exactly-once display.
- Owner authentication is provided by the existing access layer. In-process HTTP
  fixtures prove route/Host/origin guards and state behavior, not live access setup.
