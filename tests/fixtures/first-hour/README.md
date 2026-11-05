# Synthetic first-hour contract examples

synthetic_assumptions: every candidate, repository, time, digest, operation id,
finding and ticket number below is invented to exercise
contracts/first-hour.v1.md. None is an observation of an install, a CloudRoom or
GitHub account, a harness, a review, CI or a merge, and none is a live pass. The
recording example stands in for #2204's recording-provider journey; the recovery
examples stand in for #2222's fault cases.

README fixtures use the repository scanner's prose-and-example form. The checks in
tools/install/tests/first-hour-contract/ read the one fenced JSON map below:

- `examples`: complete documents. Each has the exact `problems`, `failures` and
  `unproven` codes the contract requires for it, written by hand from the
  contract's rules.
- `recording-feedback-settled` is `recording-complete` with only its feedback
  gate settled by its one approved producer, #2292 (the `feedback` skill and the
  app's handoff and share): the mapping a record uses after #2292's verified
  merge. The setup and paid-offer gates stay unresolved, so it stays unproven.
- The variant `offer-settled-by-free-only-producer` (#2293) also settles that
  example's `paid_offer` gate, by its one approved producer, #2293 (the
  free-only copy and offer evidence of contracts/public-offer.v1.md): the
  mapping a record uses after #2293's verified merge. It is not a paid offer, a
  trial or a payment receipt, and needs none. The setup gate stays unresolved,
  so it stays unproven. The other `offer-` variants keep the gate: settled
  without its producer, renamed, or given its producer as its decision ticket,
  the record is refused.
- `variants`: one change to a named example (`set` a value, `append` an item or
  `delete` a key, each at a path of keys and indices) and the exact codes the
  changed document must produce. A document is refused when `problems` is
  nonempty. It is a success only as a `live` pass with all three lists empty,
  which no example here is or can become.

```json
{
  "examples": {
    "recording-complete": {
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      },
      "document": {
        "schema": "openwiz.first-hour.v1",
        "kind": "result",
        "verdict": "unverified",
        "proof_class": "recording",
        "synthetic_assumptions": ["Synthetic recording-provider journey: every id, time and digest is invented."],
        "private_record": null,
        "candidate": {
          "known": {
            "version": "0.0.99",
            "source": "1111111111111111111111111111111111111111",
            "target": "x86_64-unknown-linux-gnu",
            "manifest_sha256": "2222222222222222222222222222222222222222222222222222222222222222"
          }
        },
        "repository": { "known": { "full_name": "syn-owner/syn-first-hour", "selected_by_owner": true } },
        "clock": {
          "started_at_ms": { "known": 1700000000000 },
          "ended_at_ms": { "known": 1700002820000 },
          "limit_ms": 3600000
        },
        "stages": [
          { "id": "public_instruction", "state": "verified", "reason": "Synthetic: the public install instruction was opened.",
            "evidence": [{ "basis": "instruction_opened", "at_ms": 1700000000000, "detail": "Synthetic instruction page opened." }] },
          { "id": "install", "state": "verified", "reason": "Synthetic: the candidate installed.",
            "evidence": [{ "basis": "install_result", "at_ms": 1700000300000, "detail": "Synthetic install result for the candidate." }] },
          { "id": "connections", "state": "verified", "reason": "Synthetic: every prerequisite of the selected engine verified.",
            "evidence": [{ "basis": "setup_component_verified", "at_ms": 1700000900000, "detail": "Synthetic setup read with every component verified." }] },
          { "id": "idea", "state": "verified", "reason": "Synthetic: a fresh small idea was saved.",
            "evidence": [{ "basis": "idea_saved", "at_ms": 1700001200000, "detail": "Synthetic idea saved for the selected repository." }] },
          { "id": "spec_confirmation", "state": "verified", "reason": "Synthetic: the spec confirmation was saved.",
            "evidence": [{ "basis": "decision_saved", "at_ms": 1700001500000, "detail": "Synthetic resolved confirmation record." }] },
          { "id": "plan_approval", "state": "verified", "reason": "Synthetic: the exact plan approval was saved.",
            "evidence": [{ "basis": "decision_saved", "at_ms": 1700001680000, "detail": "Synthetic resolved approval of the current revision." }] },
          { "id": "fleet", "state": "verified", "reason": "Synthetic: the approved builders started.",
            "evidence": [{ "basis": "agents_running", "at_ms": 1700001800000, "detail": "Synthetic builder started." }] },
          { "id": "review", "state": "verified", "reason": "Synthetic: the independent reviewer approved the head.",
            "evidence": [{ "basis": "review_approve_exact_head", "at_ms": 1700002700000, "detail": "Synthetic APPROVE naming the head." }] },
          { "id": "ci", "state": "verified", "reason": "Synthetic: every required check was green on the head.",
            "evidence": [{ "basis": "ci_green_exact_head", "at_ms": 1700002580000, "detail": "Synthetic green required checks." }] },
          { "id": "merge", "state": "verified", "reason": "Synthetic: the merge was read back at the approved head.",
            "evidence": [{ "basis": "merge_read_back", "at_ms": 1700002820000, "detail": "Synthetic merged state at the approved head." }] }
        ],
        "builder": {
          "harness": "claude_code", "model": "Synthetic builder model", "effort": "high", "location": "cloud",
          "usable": "verified", "extra_prerequisites": [],
          "evidence": [{ "basis": "harness_run_observed", "at_ms": 1700001800000, "detail": "Synthetic builder run observed." }]
        },
        "reviewer": {
          "harness": "codex", "model": "Synthetic reviewer model", "effort": "high", "location": "cloud",
          "usable": "verified", "extra_prerequisites": ["Synthetic separate sign-in for the reviewer harness."],
          "evidence": [{ "basis": "harness_run_observed", "at_ms": 1700002500000, "detail": "Synthetic reviewer run observed." }]
        },
        "waits": [
          { "stage": "install", "kind": "install", "started_at_ms": 1700000060000, "ended_at_ms": 1700000240000, "detail": "Synthetic download and verification." },
          { "stage": "fleet", "kind": "queue", "started_at_ms": 1700001700000, "ended_at_ms": 1700001800000, "detail": "Synthetic builder queue." },
          { "stage": "ci", "kind": "ci", "started_at_ms": 1700002400000, "ended_at_ms": 1700002580000, "detail": "Synthetic CI run." }
        ],
        "help": [
          { "stage": "connections", "at_ms": 1700000600000, "source": "public_docs", "detail": "Synthetic public setup page read." }
        ],
        "retained_work": [
          { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" },
          { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
          { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
        ],
        "operations": [
          { "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2", "kind": "connect_app", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" },
          { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "provider_read_back" },
          { "operation_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3", "kind": "start_agent", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" },
          { "operation_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4", "kind": "merge", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" }
        ],
        "interruptions": [
          {
            "interruption": "lost_reply",
            "before": [
              { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
              { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
            ],
            "after": [
              { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
              { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
            ],
            "operations": [
              { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase_before": "uncertain", "phase_after": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "provider_read_back" }
            ],
            "explanation": {
              "what_happened": "Synthetic: the confirmation's reply was lost; its send record showed it was sent once.",
              "took_effect": "yes",
              "next_action": "Synthetic: nothing to resend; wait for the saved confirmation."
            }
          },
          {
            "interruption": "browser_restart",
            "before": [
              { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" }
            ],
            "after": [
              { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" }
            ],
            "operations": [],
            "explanation": {
              "what_happened": "Synthetic: the browser restarted during setup; the saved setup state was read back unchanged.",
              "took_effect": "no",
              "next_action": "Synthetic: continue setup from the saved state."
            }
          },
          {
            "interruption": "update_rejected",
            "before": [
              { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
              { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
            ],
            "after": [
              { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
              { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
            ],
            "operations": [],
            "explanation": {
              "what_happened": "Synthetic: an update was refused before activation; the last good build stayed selected.",
              "took_effect": "no",
              "next_action": "Synthetic: keep working on the current build."
            }
          }
        ],
        "findings": [
          { "id": "F1", "severity": "low", "work_loss": false, "summary": "Synthetic low finding.", "owner": 9001, "disposition": "open" }
        ],
        "gaps": [
          { "claim": "PR2", "reason": "Synthetic: no usable-login observation in a recording." },
          { "claim": "PR3", "reason": "Synthetic: no independent security review." },
          { "claim": "PR5", "reason": "Synthetic: no reviewed page captures." }
        ],
        "gates": {
          "cloudroom_setup": { "decision_ticket": 2201, "state": "unresolved", "producers": [] },
          "paid_offer": { "decision_ticket": 2202, "state": "unresolved", "producers": [] },
          "feedback": { "decision_ticket": 2203, "state": "unresolved", "producers": [] }
        },
        "ten_minute_fleet": { "owner": 1110, "state": "unmeasured", "elapsed_ms": null }
      }
    },
    "recording-feedback-settled": {
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:paid_offer", "not_live"]
      },
      "document": {
        "schema": "openwiz.first-hour.v1",
        "kind": "result",
        "verdict": "unverified",
        "proof_class": "recording",
        "synthetic_assumptions": ["Synthetic recording-provider journey: every id, time and digest is invented."],
        "private_record": null,
        "candidate": {
          "known": {
            "version": "0.0.99",
            "source": "1111111111111111111111111111111111111111",
            "target": "x86_64-unknown-linux-gnu",
            "manifest_sha256": "2222222222222222222222222222222222222222222222222222222222222222"
          }
        },
        "repository": { "known": { "full_name": "syn-owner/syn-first-hour", "selected_by_owner": true } },
        "clock": {
          "started_at_ms": { "known": 1700000000000 },
          "ended_at_ms": { "known": 1700002820000 },
          "limit_ms": 3600000
        },
        "stages": [
          { "id": "public_instruction", "state": "verified", "reason": "Synthetic: the public install instruction was opened.",
            "evidence": [{ "basis": "instruction_opened", "at_ms": 1700000000000, "detail": "Synthetic instruction page opened." }] },
          { "id": "install", "state": "verified", "reason": "Synthetic: the candidate installed.",
            "evidence": [{ "basis": "install_result", "at_ms": 1700000300000, "detail": "Synthetic install result for the candidate." }] },
          { "id": "connections", "state": "verified", "reason": "Synthetic: every prerequisite of the selected engine verified.",
            "evidence": [{ "basis": "setup_component_verified", "at_ms": 1700000900000, "detail": "Synthetic setup read with every component verified." }] },
          { "id": "idea", "state": "verified", "reason": "Synthetic: a fresh small idea was saved.",
            "evidence": [{ "basis": "idea_saved", "at_ms": 1700001200000, "detail": "Synthetic idea saved for the selected repository." }] },
          { "id": "spec_confirmation", "state": "verified", "reason": "Synthetic: the spec confirmation was saved.",
            "evidence": [{ "basis": "decision_saved", "at_ms": 1700001500000, "detail": "Synthetic resolved confirmation record." }] },
          { "id": "plan_approval", "state": "verified", "reason": "Synthetic: the exact plan approval was saved.",
            "evidence": [{ "basis": "decision_saved", "at_ms": 1700001680000, "detail": "Synthetic resolved approval of the current revision." }] },
          { "id": "fleet", "state": "verified", "reason": "Synthetic: the approved builders started.",
            "evidence": [{ "basis": "agents_running", "at_ms": 1700001800000, "detail": "Synthetic builder started." }] },
          { "id": "review", "state": "verified", "reason": "Synthetic: the independent reviewer approved the head.",
            "evidence": [{ "basis": "review_approve_exact_head", "at_ms": 1700002700000, "detail": "Synthetic APPROVE naming the head." }] },
          { "id": "ci", "state": "verified", "reason": "Synthetic: every required check was green on the head.",
            "evidence": [{ "basis": "ci_green_exact_head", "at_ms": 1700002580000, "detail": "Synthetic green required checks." }] },
          { "id": "merge", "state": "verified", "reason": "Synthetic: the merge was read back at the approved head.",
            "evidence": [{ "basis": "merge_read_back", "at_ms": 1700002820000, "detail": "Synthetic merged state at the approved head." }] }
        ],
        "builder": {
          "harness": "claude_code", "model": "Synthetic builder model", "effort": "high", "location": "cloud",
          "usable": "verified", "extra_prerequisites": [],
          "evidence": [{ "basis": "harness_run_observed", "at_ms": 1700001800000, "detail": "Synthetic builder run observed." }]
        },
        "reviewer": {
          "harness": "codex", "model": "Synthetic reviewer model", "effort": "high", "location": "cloud",
          "usable": "verified", "extra_prerequisites": ["Synthetic separate sign-in for the reviewer harness."],
          "evidence": [{ "basis": "harness_run_observed", "at_ms": 1700002500000, "detail": "Synthetic reviewer run observed." }]
        },
        "waits": [
          { "stage": "install", "kind": "install", "started_at_ms": 1700000060000, "ended_at_ms": 1700000240000, "detail": "Synthetic download and verification." },
          { "stage": "fleet", "kind": "queue", "started_at_ms": 1700001700000, "ended_at_ms": 1700001800000, "detail": "Synthetic builder queue." },
          { "stage": "ci", "kind": "ci", "started_at_ms": 1700002400000, "ended_at_ms": 1700002580000, "detail": "Synthetic CI run." }
        ],
        "help": [
          { "stage": "connections", "at_ms": 1700000600000, "source": "public_docs", "detail": "Synthetic public setup page read." }
        ],
        "retained_work": [
          { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" },
          { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
          { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
        ],
        "operations": [
          { "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2", "kind": "connect_app", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" },
          { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "provider_read_back" },
          { "operation_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3", "kind": "start_agent", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" },
          { "operation_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4", "kind": "merge", "phase": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "none" }
        ],
        "interruptions": [
          {
            "interruption": "lost_reply",
            "before": [
              { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
              { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
            ],
            "after": [
              { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
              { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
            ],
            "operations": [
              { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase_before": "uncertain", "phase_after": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "provider_read_back" }
            ],
            "explanation": {
              "what_happened": "Synthetic: the confirmation's reply was lost; its send record showed it was sent once.",
              "took_effect": "yes",
              "next_action": "Synthetic: nothing to resend; wait for the saved confirmation."
            }
          },
          {
            "interruption": "browser_restart",
            "before": [
              { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" }
            ],
            "after": [
              { "kind": "setup_state", "id": "syn-setup-state", "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7", "basis": "owner_state_read_back" }
            ],
            "operations": [],
            "explanation": {
              "what_happened": "Synthetic: the browser restarted during setup; the saved setup state was read back unchanged.",
              "took_effect": "no",
              "next_action": "Synthetic: continue setup from the saved state."
            }
          },
          {
            "interruption": "update_rejected",
            "before": [
              { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
              { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
            ],
            "after": [
              { "kind": "branch", "id": "room/syn-first-hour-1", "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8", "basis": "repository_read_back" },
              { "kind": "commit", "id": "dadadadadadadadadadadadadadadadadadadada", "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9", "basis": "repository_read_back" }
            ],
            "operations": [],
            "explanation": {
              "what_happened": "Synthetic: an update was refused before activation; the last good build stayed selected.",
              "took_effect": "no",
              "next_action": "Synthetic: keep working on the current build."
            }
          }
        ],
        "findings": [
          { "id": "F1", "severity": "low", "work_loss": false, "summary": "Synthetic low finding.", "owner": 9001, "disposition": "open" }
        ],
        "gaps": [
          { "claim": "PR2", "reason": "Synthetic: no usable-login observation in a recording." },
          { "claim": "PR3", "reason": "Synthetic: no independent security review." },
          { "claim": "PR5", "reason": "Synthetic: no reviewed page captures." }
        ],
        "gates": {
          "cloudroom_setup": { "decision_ticket": 2201, "state": "unresolved", "producers": [] },
          "paid_offer": { "decision_ticket": 2202, "state": "unresolved", "producers": [] },
          "feedback": { "decision_ticket": 2203, "state": "settled", "producers": [2292] }
        },
        "ten_minute_fleet": { "owner": 1110, "state": "unmeasured", "elapsed_ms": null }
      }
    },
    "recovery-lost-reply": {
      "expect": { "problems": [], "failures": [], "unproven": ["candidate_unknown", "not_live"] },
      "document": {
        "schema": "openwiz.first-hour.v1",
        "kind": "recovery",
        "verdict": "unverified",
        "proof_class": "fixture",
        "synthetic_assumptions": ["Synthetic fault case: the ids and digests are invented."],
        "private_record": null,
        "candidate": { "unknown": "Synthetic component case: no installed candidate." },
        "case": {
          "interruption": "lost_reply",
          "before": [
            { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
            { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
          ],
          "after": [
            { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" },
            { "kind": "draft", "id": "syn-draft-confirmation", "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6", "basis": "tab_session_storage" }
          ],
          "operations": [
            { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase_before": "uncertain", "phase_after": "applied", "effect_count": 1, "attempts": 1, "reconciliation": "provider_read_back" }
          ],
          "explanation": {
            "what_happened": "Synthetic: the reply was lost; the send record showed one send.",
            "took_effect": "yes",
            "next_action": "Synthetic: nothing to resend."
          }
        }
      }
    },
    "recovery-uncertain-held": {
      "expect": { "problems": [], "failures": [], "unproven": ["candidate_unknown", "not_live", "operation_uncertain:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"] },
      "document": {
        "schema": "openwiz.first-hour.v1",
        "kind": "recovery",
        "verdict": "unverified",
        "proof_class": "fixture",
        "synthetic_assumptions": ["Synthetic fault case: the ids and digests are invented."],
        "private_record": null,
        "candidate": { "unknown": "Synthetic component case: no installed candidate." },
        "case": {
          "interruption": "lost_reply",
          "before": [
            { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" }
          ],
          "after": [
            { "kind": "pending_operation", "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5", "basis": "owner_state_read_back" }
          ],
          "operations": [
            { "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "kind": "send", "phase_before": "uncertain", "phase_after": "uncertain", "effect_count": 0, "attempts": 1, "reconciliation": "none" }
          ],
          "explanation": {
            "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
            "took_effect": "unknown",
            "next_action": "Synthetic: read the send record by its op id before anything else."
          }
        }
      }
    }
  },
  "variants": {
    "empty-lost-reply": {
      "from": "recovery-lost-reply",
      "set": [
        [
          [
            "case",
            "before"
          ],
          []
        ],
        [
          [
            "case",
            "after"
          ],
          []
        ],
        [
          [
            "case",
            "operations"
          ],
          []
        ],
        [
          [
            "case",
            "explanation",
            "took_effect"
          ],
          "no"
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "candidate_unknown",
          "not_live",
          "recovery_operations_missing:case",
          "recovery_work_missing:case"
        ]
      }
    },
    "recovery-missing-original-intent": {
      "from": "recovery-lost-reply",
      "set": [
        [
          [
            "case",
            "before"
          ],
          [
            {
              "kind": "draft",
              "id": "syn-draft-confirmation",
              "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
              "basis": "tab_session_storage"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "candidate_unknown",
          "not_live",
          "recovery_intent_missing:case:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ]
      }
    },
    "recovery-missing-operation-observation": {
      "from": "recovery-lost-reply",
      "set": [
        [
          [
            "case",
            "operations"
          ],
          []
        ],
        [
          [
            "case",
            "explanation",
            "took_effect"
          ],
          "no"
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "candidate_unknown",
          "not_live",
          "recovery_operation_missing:case:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
          "recovery_operations_missing:case"
        ]
      }
    },
    "final-operation-omitted": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "uncertain",
                "effect_count": 0,
                "attempts": 1,
                "reconciliation": "none"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
              "took_effect": "unknown",
              "next_action": "Synthetic: read the send record by its op id before anything else."
            }
          }
        ],
        [
          [
            "operations"
          ],
          [
            {
              "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
              "kind": "connect_app",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3",
              "kind": "start_agent",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4",
              "kind": "merge",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "final_operation_missing:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live",
          "operation_uncertain:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ]
      }
    },
    "final-state-erases-uncertainty": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "uncertain",
                "effect_count": 0,
                "attempts": 1,
                "reconciliation": "none"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
              "took_effect": "unknown",
              "next_action": "Synthetic: read the send record by its op id before anything else."
            }
          }
        ],
        [
          [
            "operations",
            1,
            "reconciliation"
          ],
          "none"
        ]
      ],
      "expect": {
        "problems": [
          "failure_not_reported"
        ],
        "failures": [
          "uncertainty_erased:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live",
          "operation_uncertain:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ]
      }
    },
    "final-operation-kind-contradicts-recovery": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations",
            1,
            "kind"
          ],
          "connect_app"
        ]
      ],
      "expect": {
        "problems": [
          "operation_history_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "final-operation-count-regresses": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "operations",
            0,
            "attempts"
          ],
          2
        ]
      ],
      "expect": {
        "problems": [
          "operation_history_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "later-recovery-reconciles-intent": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "uncertain",
                "effect_count": 0,
                "attempts": 1,
                "reconciliation": "none"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
              "took_effect": "unknown",
              "next_action": "Synthetic: read the send record by its op id before anything else."
            }
          }
        ]
      ],
      "append": [
        [
          [
            "interruptions"
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "applied",
                "effect_count": 1,
                "attempts": 1,
                "reconciliation": "provider_read_back"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the confirmation's reply was lost; its send record showed it was sent once.",
              "took_effect": "yes",
              "next_action": "Synthetic: nothing to resend; wait for the saved confirmation."
            }
          }
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "later-recovery-contradicts-prior-phase": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "uncertain",
                "effect_count": 0,
                "attempts": 1,
                "reconciliation": "none"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
              "took_effect": "unknown",
              "next_action": "Synthetic: read the send record by its op id before anything else."
            }
          }
        ]
      ],
      "append": [
        [
          [
            "interruptions"
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "proposed",
                "phase_after": "applied",
                "effect_count": 1,
                "attempts": 1,
                "reconciliation": "provider_read_back"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the confirmation's reply was lost; its send record showed it was sent once.",
              "took_effect": "yes",
              "next_action": "Synthetic: nothing to resend; wait for the saved confirmation."
            }
          }
        ]
      ],
      "expect": {
        "problems": [
          "operation_history_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-before-first": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "before"
          ],
          [
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "draft",
              "id": "syn-draft-confirmation",
              "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
              "basis": "tab_session_storage"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:0:before:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-after-first": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "after"
          ],
          [
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "draft",
              "id": "syn-draft-confirmation",
              "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
              "basis": "tab_session_storage"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:0:after:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-final-work-first": {
      "from": "recording-complete",
      "set": [
        [
          [
            "retained_work"
          ],
          [
            {
              "kind": "setup_state",
              "id": "syn-setup-state",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "setup_state",
              "id": "syn-setup-state",
              "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "branch",
              "id": "room/syn-first-hour-1",
              "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8",
              "basis": "repository_read_back"
            },
            {
              "kind": "commit",
              "id": "dadadadadadadadadadadadadadadadadadadada",
              "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9",
              "basis": "repository_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:retained_work:setup_state:syn-setup-state"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-final-intent-first": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations"
          ],
          [
            {
              "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
              "kind": "prepare_project",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
              "kind": "connect_app",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            },
            {
              "operation_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3",
              "kind": "start_agent",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4",
              "kind": "merge",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_operation:operations:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-intent-first": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "operations"
          ],
          [
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase_before": "uncertain",
              "phase_after": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            },
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase_before": "uncertain",
              "phase_after": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_operation:0:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-before-last": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "before"
          ],
          [
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "draft",
              "id": "syn-draft-confirmation",
              "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
              "basis": "tab_session_storage"
            },
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:0:before:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-after-last": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "after"
          ],
          [
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "draft",
              "id": "syn-draft-confirmation",
              "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
              "basis": "tab_session_storage"
            },
            {
              "kind": "pending_operation",
              "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:0:after:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-final-work-last": {
      "from": "recording-complete",
      "set": [
        [
          [
            "retained_work"
          ],
          [
            {
              "kind": "setup_state",
              "id": "syn-setup-state",
              "content": "a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7a7",
              "basis": "owner_state_read_back"
            },
            {
              "kind": "branch",
              "id": "room/syn-first-hour-1",
              "content": "b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8b8",
              "basis": "repository_read_back"
            },
            {
              "kind": "commit",
              "id": "dadadadadadadadadadadadadadadadadadadada",
              "content": "c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9",
              "basis": "repository_read_back"
            },
            {
              "kind": "setup_state",
              "id": "syn-setup-state",
              "content": "0000000000000000000000000000000000000000000000000000000000000000",
              "basis": "owner_state_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_work:retained_work:setup_state:syn-setup-state"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-final-intent-last": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations"
          ],
          [
            {
              "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
              "kind": "connect_app",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            },
            {
              "operation_id": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3",
              "kind": "start_agent",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4",
              "kind": "merge",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            },
            {
              "operation_id": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
              "kind": "prepare_project",
              "phase": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "none"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_operation:operations:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "duplicate-recovery-intent-last": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0,
            "operations"
          ],
          [
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase_before": "uncertain",
              "phase_after": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            },
            {
              "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
              "kind": "send",
              "phase_before": "uncertain",
              "phase_after": "applied",
              "effect_count": 1,
              "attempts": 1,
              "reconciliation": "provider_read_back"
            }
          ]
        ]
      ],
      "expect": {
        "problems": [
          "duplicate_operation:0:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "pending-fingerprint-contradicts-earlier-recovery": {
      "from": "recording-complete",
      "set": [
        [
          [
            "interruptions",
            0
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5",
                "basis": "owner_state_read_back"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "uncertain",
                "effect_count": 0,
                "attempts": 1,
                "reconciliation": "none"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the reply was lost and the record is not yet read.",
              "took_effect": "unknown",
              "next_action": "Synthetic: read the send record by its op id before anything else."
            }
          }
        ]
      ],
      "append": [
        [
          [
            "interruptions"
          ],
          {
            "interruption": "lost_reply",
            "before": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "0000000000000000000000000000000000000000000000000000000000000000",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "after": [
              {
                "kind": "pending_operation",
                "id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "content": "0000000000000000000000000000000000000000000000000000000000000000",
                "basis": "owner_state_read_back"
              },
              {
                "kind": "draft",
                "id": "syn-draft-confirmation",
                "content": "f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6f6",
                "basis": "tab_session_storage"
              }
            ],
            "operations": [
              {
                "operation_id": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "kind": "send",
                "phase_before": "uncertain",
                "phase_after": "applied",
                "effect_count": 1,
                "attempts": 1,
                "reconciliation": "provider_read_back"
              }
            ],
            "explanation": {
              "what_happened": "Synthetic: the confirmation's reply was lost; its send record showed it was sent once.",
              "took_effect": "yes",
              "next_action": "Synthetic: nothing to resend; wait for the saved confirmation."
            }
          }
        ]
      ],
      "expect": {
        "problems": [
          "work_history_mismatch:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "zero-call-proposal-result": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations",
            0,
            "phase"
          ],
          "proposed"
        ],
        [
          [
            "operations",
            0,
            "effect_count"
          ],
          0
        ],
        [
          [
            "operations",
            0,
            "attempts"
          ],
          0
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "zero-call-proposal-recovery": {
      "from": "recovery-lost-reply",
      "set": [
        [["case", "operations", 0, "kind"], "connect_app"],
        [
          [
            "case",
            "interruption"
          ],
          "setup_interrupted"
        ],
        [
          [
            "case",
            "operations",
            0,
            "phase_before"
          ],
          "proposed"
        ],
        [
          [
            "case",
            "operations",
            0,
            "phase_after"
          ],
          "proposed"
        ],
        [
          [
            "case",
            "operations",
            0,
            "effect_count"
          ],
          0
        ],
        [
          [
            "case",
            "operations",
            0,
            "attempts"
          ],
          0
        ],
        [
          [
            "case",
            "operations",
            0,
            "reconciliation"
          ],
          "none"
        ],
        [
          [
            "case",
            "explanation",
            "took_effect"
          ],
          "no"
        ]
      ],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": [
          "candidate_unknown",
          "not_live"
        ]
      }
    },
    "zero-call-recovery-prior-applied": {
      "from": "recovery-lost-reply",
      "set": [
        [["case", "interruption"], "setup_interrupted"],
        [["case", "operations", 0, "kind"], "connect_app"],
        [["case", "operations", 0, "phase_before"], "applied"],
        [["case", "operations", 0, "phase_after"], "proposed"],
        [["case", "operations", 0, "effect_count"], 0],
        [["case", "operations", 0, "attempts"], 0],
        [["case", "explanation", "took_effect"], "no"]
      ],
      "expect": {
        "problems": ["phase_attempt_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "failures": [],
        "unproven": ["candidate_unknown", "not_live"]
      }
    },
    "zero-call-recovery-prior-uncertain": {
      "from": "recovery-lost-reply",
      "set": [
        [["case", "interruption"], "setup_interrupted"],
        [["case", "operations", 0, "kind"], "connect_app"],
        [["case", "operations", 0, "phase_before"], "uncertain"],
        [["case", "operations", 0, "phase_after"], "proposed"],
        [["case", "operations", 0, "effect_count"], 0],
        [["case", "operations", 0, "attempts"], 0],
        [["case", "explanation", "took_effect"], "no"]
      ],
      "expect": {
        "problems": ["phase_attempt_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "failures": [],
        "unproven": ["candidate_unknown", "not_live"]
      }
    },
    "zero-call-embedded-prior-applied": {
      "from": "recording-complete",
      "set": [
        [["interruptions", 0, "interruption"], "setup_interrupted"],
        [["interruptions", 0, "operations", 0, "phase_before"], "applied"],
        [["interruptions", 0, "operations", 0, "phase_after"], "proposed"],
        [["interruptions", 0, "operations", 0, "effect_count"], 0],
        [["interruptions", 0, "operations", 0, "attempts"], 0],
        [["interruptions", 0, "explanation", "took_effect"], "no"],
        [["operations", 1, "phase"], "proposed"],
        [["operations", 1, "effect_count"], 0],
        [["operations", 1, "attempts"], 0]
      ],
      "expect": {
        "problems": ["phase_attempt_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "zero-call-embedded-prior-uncertain": {
      "from": "recording-complete",
      "set": [
        [["interruptions", 0, "interruption"], "setup_interrupted"],
        [["interruptions", 0, "operations", 0, "phase_before"], "uncertain"],
        [["interruptions", 0, "operations", 0, "phase_after"], "proposed"],
        [["interruptions", 0, "operations", 0, "effect_count"], 0],
        [["interruptions", 0, "operations", 0, "attempts"], 0],
        [["interruptions", 0, "explanation", "took_effect"], "no"],
        [["operations", 1, "phase"], "proposed"],
        [["operations", 1, "effect_count"], 0],
        [["operations", 1, "attempts"], 0]
      ],
      "expect": {
        "problems": ["phase_attempt_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "applied-with-zero-calls": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations",
            0,
            "attempts"
          ],
          0
        ]
      ],
      "expect": {
        "problems": [
          "phase_attempt_mismatch:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live"
        ]
      }
    },
    "uncertain-with-zero-calls": {
      "from": "recording-complete",
      "set": [
        [
          [
            "operations",
            0,
            "attempts"
          ],
          0
        ],
        [
          [
            "operations",
            0,
            "phase"
          ],
          "uncertain"
        ],
        [
          [
            "operations",
            0,
            "effect_count"
          ],
          0
        ]
      ],
      "expect": {
        "problems": [
          "phase_attempt_mismatch:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"
        ],
        "failures": [],
        "unproven": [
          "gate_unresolved:cloudroom_setup",
          "gate_unresolved:feedback",
          "gate_unresolved:paid_offer",
          "not_live",
          "operation_uncertain:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"
        ]
      }
    },
    "setup-state-sha256-too-short": {
      "from": "recording-complete",
      "set": [[["retained_work", 0, "content"], "1111111111111111111111111111111111111111"]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "branch-commit-hash-too-long": {
      "from": "recording-complete",
      "set": [[["retained_work", 1, "content"], "2222222222222222222222222222222222222222222222222222222222222222"]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "fixture-claims-pass": {
      "from": "recording-complete",
      "set": [[["verdict"], "pass"]],
      "expect": {
        "problems": ["non_live_pass", "unproven_pass"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "synthetic-labelled-live": {
      "from": "recording-complete",
      "set": [[["proof_class"], "live"]],
      "expect": {
        "problems": ["live_without_private_record", "synthetic_live"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer"]
      }
    },
    "unlabelled-recording": {
      "from": "recording-complete",
      "set": [[["synthetic_assumptions"], []]],
      "expect": {
        "problems": ["synthetic_unlabelled"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "missed-hour-failed": {
      "from": "recording-complete",
      "set": [[["verdict"], "fail"], [["clock", "ended_at_ms", "known"], 1700003720000],
              [["stages", 9, "evidence", 0, "at_ms"], 1700003720000]],
      "expect": {
        "problems": [],
        "failures": ["hour_missed"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "exactly-one-hour": {
      "from": "recording-complete",
      "set": [[["clock", "ended_at_ms", "known"], 1700003600000],
              [["stages", 9, "evidence", 0, "at_ms"], 1700003600000]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "missed-hour-not-failed": {
      "from": "recording-complete",
      "set": [[["clock", "ended_at_ms", "known"], 1700003720000],
              [["stages", 9, "evidence", 0, "at_ms"], 1700003720000]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["hour_missed"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "clock-unknown": {
      "from": "recording-complete",
      "set": [[["clock", "ended_at_ms"], { "unknown": "Synthetic: the merge time was not read back." }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["clock_unknown", "gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "clock-ends-before-start": {
      "from": "recording-complete",
      "set": [[["clock", "ended_at_ms", "known"], 1699999990000]],
      "expect": {
        "problems": ["clock_order"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "closed-pr-as-merge": {
      "from": "recording-complete",
      "set": [[["stages", 9, "evidence", 0, "basis"], "pr_closed"]],
      "expect": {
        "problems": ["stage_weak_evidence:merge"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "reachable-cloudroom-as-connected": {
      "from": "recording-complete",
      "set": [[["stages", 2, "evidence", 0, "basis"], "cloudroom_reachable"]],
      "expect": {
        "problems": ["stage_weak_evidence:connections"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "accepted-answer-as-approval": {
      "from": "recording-complete",
      "set": [[["stages", 5, "evidence", 0, "basis"], "answer_accepted"]],
      "expect": {
        "problems": ["stage_weak_evidence:plan_approval"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "running-grid-as-review": {
      "from": "recording-complete",
      "set": [[["stages", 7, "evidence", 0, "basis"], "agents_running"]],
      "expect": {
        "problems": ["stage_weak_evidence:review"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "listed-harness-as-usable": {
      "from": "recording-complete",
      "set": [[["reviewer", "evidence", 0, "basis"], "harness_listed"]],
      "expect": {
        "problems": ["seat_weak_evidence:reviewer"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "stale-merge-evidence": {
      "from": "recording-complete",
      "set": [[["stages", 9, "evidence", 0, "at_ms"], 1699990000000]],
      "expect": {
        "problems": ["stale_evidence:merge"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "stale-builder-evidence": {
      "from": "recording-complete",
      "set": [[["builder", "evidence", 0, "at_ms"], 1699990000000]],
      "expect": {
        "problems": ["stale_evidence:builder"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "missing-review": {
      "from": "recording-complete",
      "set": [[["stages", 7, "state"], "missing"], [["stages", 7, "evidence"], []]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "stage_unverified:review"]
      }
    },
    "failed-ci": {
      "from": "recording-complete",
      "set": [[["verdict"], "fail"], [["stages", 8, "state"], "failed"]],
      "expect": {
        "problems": [],
        "failures": ["stage_failed:ci"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "stages-out-of-order": {
      "from": "recording-complete",
      "set": [[["stages", 7, "id"], "ci"], [["stages", 8, "id"], "review"],
              [["stages", 7, "evidence", 0, "basis"], "ci_green_exact_head"],
              [["stages", 8, "evidence", 0, "basis"], "review_approve_exact_head"]],
      "expect": {
        "problems": ["stage_order"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "unusable-reviewer": {
      "from": "recording-complete",
      "set": [[["reviewer", "usable"], "missing"], [["reviewer", "evidence"], []]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "seat_unusable:reviewer"]
      }
    },
    "same-family-review": {
      "from": "recording-complete",
      "set": [[["reviewer", "harness"], "claude_code"]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "reviewer_not_independent"]
      }
    },
    "prepared-plan-help": {
      "from": "recording-complete",
      "append": [[["help"], { "stage": "idea", "at_ms": 1700001100000, "source": "prepared_plan", "detail": "Synthetic prepared plan handed over." }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "prepared_help"]
      }
    },
    "wait-outside-clock": {
      "from": "recording-complete",
      "set": [[["waits", 2, "ended_at_ms"], 1700002900000]],
      "expect": {
        "problems": ["outside_clock:wait:2"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "help-outside-clock": {
      "from": "recording-complete",
      "set": [[["help", 0, "at_ms"], 1699999000000]],
      "expect": {
        "problems": ["outside_clock:help:0"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "unknown-candidate": {
      "from": "recording-complete",
      "set": [[["candidate"], { "unknown": "Synthetic: the build identity was not read." }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["candidate_unknown", "gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "unknown-repository": {
      "from": "recording-complete",
      "set": [[["repository"], { "unknown": "Synthetic: the selected repository was not read back." }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "repository_unknown"]
      }
    },
    "duplicate-effect": {
      "from": "recording-complete",
      "set": [[["operations", 2, "effect_count"], 2]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["duplicate_effect:c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "blind-retry": {
      "from": "recording-complete",
      "set": [[["operations", 0, "attempts"], 2]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["blind_retry:b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "reconciled-retry": {
      "from": "recording-complete",
      "set": [[["operations", 0, "attempts"], 2], [["operations", 0, "reconciliation"], "provider_read_back"]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "applied-without-effect": {
      "from": "recording-complete",
      "set": [[["operations", 3, "effect_count"], 0]],
      "expect": {
        "problems": ["phase_effect_mismatch:d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "operation-left-uncertain": {
      "from": "recording-complete",
      "set": [[["operations", 1, "phase"], "uncertain"], [["operations", 1, "effect_count"], 0], [["operations", 1, "reconciliation"], "none"]],
      "expect": {
        "problems": ["operation_history_mismatch:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "operation_uncertain:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"]
      }
    },
    "uncertainty-erased-by-refusal": {
      "from": "recording-complete",
      "set": [[["interruptions", 0, "operations", 0, "phase_after"], "refused"],
              [["interruptions", 0, "operations", 0, "effect_count"], 0],
              [["interruptions", 0, "operations", 0, "reconciliation"], "none"],
              [["interruptions", 0, "explanation", "took_effect"], "no"]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["uncertainty_erased:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "effect-hidden-in-explanation": {
      "from": "recording-complete",
      "set": [[["interruptions", 0, "explanation", "took_effect"], "no"]],
      "expect": {
        "problems": ["explanation_inconsistent:0"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "draft-lost-in-browser-restart": {
      "from": "recording-complete",
      "append": [[["interruptions", 1, "before"], { "kind": "draft", "id": "syn-draft-idea", "content": "1717171717171717171717171717171717171717171717171717171717171717", "basis": "tab_session_storage" }]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["work_lost:draft:syn-draft-idea"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "tab-storage-claimed-across-browser-restart": {
      "from": "recording-complete",
      "append": [[["interruptions", 1, "before"], { "kind": "draft", "id": "syn-draft-idea", "content": "1717171717171717171717171717171717171717171717171717171717171717", "basis": "tab_session_storage" }],
                 [["interruptions", 1, "after"], { "kind": "draft", "id": "syn-draft-idea", "content": "1717171717171717171717171717171717171717171717171717171717171717", "basis": "tab_session_storage" }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live", "retention_unproven:draft:syn-draft-idea"]
      }
    },
    "branch-changed-after-rejected-update": {
      "from": "recording-complete",
      "set": [[["interruptions", 2, "after", 0, "content"], "0000000000000000000000000000000000000000"]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["work_lost:branch:room/syn-first-hour-1"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "work-loss-finding-accepted": {
      "from": "recording-complete",
      "append": [[["findings"], { "id": "F2", "severity": "medium", "work_loss": true, "summary": "Synthetic draft lost on removal.", "owner": 9002, "disposition": "accepted_gap" }]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["open_blocking_finding:F2"],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "fixed-blocker": {
      "from": "recording-complete",
      "append": [[["findings"], { "id": "F3", "severity": "blocker", "work_loss": false, "summary": "Synthetic fixed blocker.", "owner": 9003, "disposition": "fixed" }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "pr4-gap": {
      "from": "recording-complete",
      "append": [[["gaps"], { "claim": "PR4", "reason": "Synthetic: no removal case observed." }]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gap:PR4", "gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "gate-settled-without-producers": {
      "from": "recording-complete",
      "set": [[["gates", "feedback", "state"], "settled"]],
      "expect": {
        "problems": ["gate_producers:feedback"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "gate-producers-while-unresolved": {
      "from": "recording-complete",
      "set": [[["gates", "paid_offer", "producers"], [9004]]],
      "expect": {
        "problems": ["gate_producers:paid_offer"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "offer-settled-by-free-only-producer": {
      "from": "recording-feedback-settled",
      "set": [[["gates", "paid_offer", "state"], "settled"], [["gates", "paid_offer", "producers"], [2293]]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "not_live"]
      }
    },
    "offer-settled-without-its-producer": {
      "from": "recording-feedback-settled",
      "set": [[["gates", "paid_offer", "state"], "settled"]],
      "expect": {
        "problems": ["gate_producers:paid_offer"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "offer-gate-renamed-free-only": {
      "from": "recording-feedback-settled",
      "set": [[["gates", "free_only"], { "decision_ticket": 2202, "state": "settled", "producers": [2293] }]],
      "delete": [["gates", "paid_offer"]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "offer-producer-as-decision-ticket": {
      "from": "recording-feedback-settled",
      "set": [[["gates", "paid_offer", "decision_ticket"], 2293], [["gates", "paid_offer", "state"], "settled"], [["gates", "paid_offer", "producers"], [2293]]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "ten-minute-met-too-slow": {
      "from": "recording-complete",
      "set": [[["ten_minute_fleet", "state"], "met"], [["ten_minute_fleet", "elapsed_ms"], 700000]],
      "expect": {
        "problems": ["ten_minute_inconsistent"],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "ten-minute-met-at-the-limit": {
      "from": "recording-complete",
      "set": [[["ten_minute_fleet", "state"], "met"], [["ten_minute_fleet", "elapsed_ms"], 600000]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "ten-minute-missed-is-not-a-first-hour-failure": {
      "from": "recording-complete",
      "set": [[["ten_minute_fleet", "state"], "missed"], [["ten_minute_fleet", "elapsed_ms"], 700000]],
      "expect": {
        "problems": [],
        "failures": [],
        "unproven": ["gate_unresolved:cloudroom_setup", "gate_unresolved:feedback", "gate_unresolved:paid_offer", "not_live"]
      }
    },
    "missing-retained-work": {
      "from": "recording-complete",
      "delete": [["retained_work"]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "extra-key": {
      "from": "recording-complete",
      "set": [[["synthetic_extra"], true]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "wrong-gate-ticket": {
      "from": "recording-complete",
      "set": [[["gates", "feedback", "decision_ticket"], 2202]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "hour-limit-changed": {
      "from": "recording-complete",
      "set": [[["clock", "limit_ms"], 4200000]],
      "expect": { "problems": ["schema"], "failures": [], "unproven": [] }
    },
    "recovery-blind-retry": {
      "from": "recovery-lost-reply",
      "set": [[["case", "operations", 0, "attempts"], 2], [["case", "operations", 0, "effect_count"], 2],
              [["case", "operations", 0, "reconciliation"], "none"]],
      "expect": {
        "problems": ["failure_not_reported"],
        "failures": ["blind_retry:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1", "duplicate_effect:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                     "uncertainty_erased:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "unproven": ["candidate_unknown", "not_live"]
      }
    },
    "recovery-pending-record-lost": {
      "from": "recovery-lost-reply",
      "set": [[["verdict"], "fail"]],
      "delete": [["case", "after", 0]],
      "expect": {
        "problems": [],
        "failures": ["work_lost:pending_operation:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"],
        "unproven": ["candidate_unknown", "not_live"]
      }
    },
    "recovery-unknown-called-no": {
      "from": "recovery-uncertain-held",
      "set": [[["case", "explanation", "took_effect"], "no"]],
      "expect": {
        "problems": ["explanation_inconsistent:case"],
        "failures": [],
        "unproven": ["candidate_unknown", "not_live", "operation_uncertain:a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"]
      }
    },
    "recovery-claims-pass": {
      "from": "recovery-lost-reply",
      "set": [[["verdict"], "pass"]],
      "expect": {
        "problems": ["non_live_pass", "unproven_pass"],
        "failures": [],
        "unproven": ["candidate_unknown", "not_live"]
      }
    }
  }
}
```
