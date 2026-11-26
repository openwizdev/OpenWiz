# EF15 approach and proof plan

The effort probe gets a fresh loopback host. Take one locked snapshot of its
request log when the driver's start call returns, before issuing cleanup. A
synchronous host request is logged before its response, so a driver that waits
for the host's response before returning can prove receipt without a delay.
There is no grace period for asynchronous delivery. Cleanup still runs for an
accepted start, including when its receipt is missing.

Only an unambiguous creation POST from that snapshot can carry the configured
field. The probe treats a sole POST made during start as the creation request.
A second POST makes that inference ambiguous, even if only one of the two
carries effort. The fake host has no host-independent way to tell what an
arbitrary POST does. Keep the existing refusal guard for any start-time POST.

The existing kit CLI test covers a successful key-host start, missing effort
and a refusal after a POST. Extend that table with a planted driver that only
sends the setting in cleanup. Also exercise effort sent on a cleanup POST, a
start-time non-POST, and one of two start-time POSTs. Each should fail the
start verdict while leaving the key check able to exercise the lifecycle. The
fixtures use synchronous requests and do not depend on scheduler timing.

The builder can run these proofs with synthetic inputs using test_kit.py and
run the companion test_hostkey.py suite. They show what the loopback host
received and what the kit reports. They cannot establish whether a live host
applies the value or distinguish the live semantics of a lone arbitrary POST.
