# A driver whose host CLI takes effort and exits

Login: stays on your machine
Effort: passed as `--reasoning-level <level>`, for low, medium, high, xhigh and max

The kit's own fixture: at start, the driver runs a one-shot host command, `fake-room thread spawn --reasoning-level <level>`, which takes the effort and exits before start answers; the harness itself is run without it.
