# Validation spikes (ADR-0012)

Throwaway proofs that **de-risk the design before implementation**. Each spike answers **one
question** with a **binary exit criterion**, observed — not "should work." Pass → promote into the
reference implementation + mark the ledger row `Grounded`. Fail → cut or redesign the element.

Run (pure stdlib where possible):

```
python analytics/spikes/<name>.py    # exit 0 = pass
```

| Spike | Question | Result |
|---|---|---|
| **B13** `b13_fixture_harness.py` | Can detectors be validated with **constructed ground truth** (not a hand-authored catalog)? | **PASS** (2026-08-01) — structural repeated-node + counterfactual model-fit, each with matched positive/negative fixtures; counterfactual **recovers the injected saving magnitude** exactly. |
| **B7** `b7_analyst_guardrails.py` | Does the engine stop a bad/hallucinating analyst? (safety half) | **PASS** (2026-08-01) — rejects uncited/out-of-seam/free-form cards; **overrides an invented saving to the engine value**; forces code-seam autonomy to staged/L3. *(Quality half — real-LLM pass-rate — deferred.)* |
| **B1** `b1_node_grain_capture.py` | Is node-grain telemetry derivable from the existing stream, cost-neutral? | **PASS** (2026-08-01) — one record per agent with per-node attribution; **reconciles to today's turn total**; 0 new model calls. *(Live capture deferred.)* |
| **B10** `b10_policy_binding_sdk.py` | Is `params` a safe typed contract (not an opaque blob)? | **PASS** (2026-08-01) — clamps bounds, rejects unknown models, enforces invariants, **fails closed**; discovery manifest. |
| **B16** `b16_autonomy_guard.py` | Can config auto-revert safely on a bad verdict? | **PASS** (2026-08-01) — auto-reverts config on adverse/insufficient w/ audit; holds below min-sample; human-gates non-config. |
| **B19** `b19_outcome_linkage.py` | Does a correlation key enable session-grain cost-per-outcome? | **PASS** (2026-08-01) — join impossible without `sessionId`, correct with it. *(App code-wiring pending.)* |
| **B15** `b15_outcome_ledger.py` | Does the system learn from outcomes without fine-tuning? | **PASS** (2026-08-01) — re-ranks by track record + deterministic calibration. |
| **B17** `b17_node_grain_simulator.py` | Can we fabricate agent-structured telemetry, no LLM? | **PASS** (2026-08-01) — 0% missing structure, correct distributions, reproducible. |
| **B8** `b8_projection_whatif.py` | Does projection generalize + scale honestly? | **PASS** (2026-08-01) — matches ground truth, usage-scaling, price-only vs behavior-changing split. |

See `analytics/docs/adr/adr-0012-validation-driven-delivery-loop-and-ledger.md` for the full ledger.
