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

See `analytics/docs/adr/adr-0012-validation-driven-delivery-loop-and-ledger.md` for the full ledger.
