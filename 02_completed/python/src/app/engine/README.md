# The analysis & optimization engine

Reference implementation of the agent-centric engine (ADR-0010). Every piece here was
first de-risked as a spike under `analytics/spikes/` (see the validation ledger,
`analytics/docs/adr/adr-0012-...`). Pure standard library — no app runtime deps — so it
imports and unit-tests cleanly and is reusable from both the Travel API and the Fabric
analysis notebook.

## Folder map (by functional area)

| Folder | What it owns | Extend by |
|---|---|---|
| `core/` | shared types (`NodeExec`), the `Registry`, cost primitives | — |
| `instrumentation/` | node-grain capture from the LangGraph event stream (Layer 1) | — |
| `detectors/` | detectors (structural / counterfactual / statistical) | **add a module + `@DETECTORS.register`** |
| `policy/` | the binding SDK (typed params, validate/clamp, fail-closed) | — |
| `policy/domains/` | one policy domain per module | **add a module + `@DOMAINS.register`** |
| `projection/` | projection functions + What-If (scaling, cost-per-outcome) | **add a module + `@PROJECTIONS.register`** |
| `analyst/` | recommendation cards + the five guardrails (LLM proposes / engine computes) | — |
| `autonomy/` | measure → verdict → auto-revert guard (config seam) | — |
| `learning/` | outcome ledger + feedback (re-rank + calibrate) | — |
| `simulation/` | agent-structured synthetic telemetry (no LLM) | tune paths/profiles |

## The one extension gesture

Every pluggable area uses the same `core.Registry`, so adding functionality is always the
same move — create a module in the folder and decorate:

```python
# detectors/my_detector.py
from .base import DETECTORS, Detection

@DETECTORS.register("structural.my_pattern")
def my_pattern(nodes):
    ...
    return Detection(detector="structural.my_pattern", kind="structural", ...)
```

Then add `from . import my_detector` to that folder's `__init__.py` so it registers on
import. (Same pattern for `policy/domains/` and `projection/`.)

## Quick use

```python
from src.app.engine import simulation, detectors, projection

nodes = simulation.simulate(seed=1, n_turns=1000)     # or real node-grain telemetry
findings = detectors.run_all(nodes)                    # what's wrong, per agent × dimension
saving = projection.project("opp-modelfit-supervisor", nodes)  # what it's worth
```

## Self-test

```
cd 02_completed/python
python -m src.app.engine._selftest        # exit 0 = the whole engine wires + works
```
